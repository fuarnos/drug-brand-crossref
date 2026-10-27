"""盐名规范化（D2 数据层 P0）：`variant.salt` 原文 → `variant.salt_code`。

背景见 reports/dose-mapping-plan.md §1.2：variant 里约 1/4 的 `salt` 值不是盐
（疫苗株、油脂、螯合物、水合物、酯类、整段成分名），且同一盐有多种写法
（hydrochloride / hcl / clorhidrato / cloruro de hidrógeno …）。
折算前提是「只对真正的单盐折算」，所以先把分类做干净：

    salt_code = 规范化盐代码（与 data/salt_base_fraction.csv 的 salt_code 对齐）
              | 'mixed'    复盐 / 混合盐 / 未收录盐 / 盐+未知词 → 必须人工核对，不折算
              | 'non_salt' 不是盐（疫苗株、油、螯合物、酯、水合物单独出现、生物制品…）
              | ''         来源没有给盐（salt 为空）

`variant.salt` 原文**不改**（可追溯；collision / 命名逻辑继续用它）。
本脚本只写 `variant.salt_code`，支持 dry-run / apply / rollback，apply 前把旧值
落成 CSV 备份，rollback 按备份还原（只还原仍等于 apply 后值的行，避免覆盖人工修改）。

CLI：
    python etl/normalize_salts.py --dry-run    # 默认；只统计 + 写审计 CSV，不写库
    python etl/normalize_salts.py --apply      # 事务写 variant.salt_code
    python etl/normalize_salts.py --rollback   # 用最近一次 apply 备份还原
    python etl/normalize_salts.py --verify     # 打印库里 salt_code 分布

ingest 侧只调用 `insert_variant()`（openFDA / CA DPD 两处），老库没跑 init_db 时
会自动退回旧 SQL（不写 salt_code），保证 ETL 不会因缺列而崩。
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "drugs.db"
WORK_DIR = ROOT / ".tmp" / "dose-impl"
DEFAULT_AUDIT = WORK_DIR / "salt_normalization.csv"
DEFAULT_BACKUP_DIR = WORK_DIR / "backups"

# ---------------------------------------------------------------------------
# 词表：canonical salt_code → 多语言别名
# 只收录 data/salt_base_fraction.csv 里有的 40 个盐/形态代码 + 常见多语种写法。
# ---------------------------------------------------------------------------
SALT_ALIASES: dict[str, set[str]] = {
    "hydrochloride": {
        "hydrochloride", "hydrochlorid", "hcl", "hydrochloride", "chlorhydrate",
        "clorhidrato", "cloridrato", "hidrocloruro", "idrocloruro",
        "cloridrato", "hydrochloridum",
    },
    "hydrobromide": {
        "hydrobromide", "hbr", "bromhydrate", "bromhidrato", "hidrobromuro",
        "bromidrato", "hydrobromidum",
    },
    "sulfate": {
        "sulfate", "sulphate", "sulfato", "sulfas", "sulfat", "sulphate",
        "sulfato", "sulfurico",
    },
    "phosphate": {"phosphate", "fosfato", "phosphat", "phosphato", "phosphate"},
    "nitrate": {"nitrate", "nitrato", "nitrat"},
    "acetate": {"acetate", "acetato", "acetat", "acetate", "acétate"},
    "lactate": {"lactate", "lactato", "lactat"},
    "citrate": {"citrate", "citrato", "citrat"},
    "maleate": {"maleate", "maleato", "maléate", "maleat"},
    "fumarate": {"fumarate", "fumarato", "fumarat"},
    "succinate": {"succinate", "succinato", "succinat"},
    "tartrate": {"tartrate", "tartrato", "tartrat"},
    "besylate": {
        "besylate", "besilate", "besilato", "benzenesulfonate",
        "benzenesulfonato", "bésylate", "besilat",
    },
    "mesylate": {
        "mesylate", "mesilate", "mesilato", "methanesulfonate",
        "mésylate", "mesilat",
    },
    "tosylate": {"tosylate", "tosilate", "tosilato", "toluenesulfonate"},
    "gluconate": {"gluconate", "gluconato", "gluconat"},
    "benzoate": {"benzoate", "benzoato", "benzoat"},
    "aspartate": {"aspartate", "aspartato", "aspartat"},
    "pamoate": {"pamoate", "embonate", "pamoato", "embonato", "pamoat"},
    "tromethamine": {"tromethamine", "trometamol", "tromethamin", "tris"},
    "meglumine": {"meglumine", "meglumina", "meglumin"},
    "sodium": {"sodium", "natrium", "sodio", "sodico", "sódico", "sódica", "sodica"},
    "potassium": {"potassium", "kalium", "potasio", "potasico", "potásico"},
    "calcium": {"calcium", "calcio", "kalzium"},
    "magnesium": {"magnesium", "magnesio", "magnésio"},
    "chloride": {"chloride", "chlorid", "chlorure", "cloruro", "cloreto"},
    "bromide": {"bromide", "bromid", "bromure", "bromuro", "brometo"},
    "iodide": {"iodide", "iodid", "iodure", "ioduro", "iodeto"},
    "xinafoate": {"xinafoate", "xinafoato"},
    "hyclate": {"hyclate", "hiclate"},
}

# 酯（非盐）：出现在 salt 字段里是误判，分流为 non_salt，不参与 D2 折算
ESTER_TOKENS: dict[str, set[str]] = {
    "valerate": {"valerate", "valerato", "valerat"},
    "propionate": {"propionate", "propionato", "propionat"},
    "dipropionate": {"dipropionate", "dipropionato", "dipropionat"},
    "decanoate": {"decanoate", "decanoato", "decanoat"},
    "enanthate": {"enanthate", "enantato", "enantat"},
    "cypionate": {"cypionate", "cipionato", "cipionat"},
    "palmitate": {"palmitate", "palmitato", "palmitat"},
    "furoate": {"furoate", "furoato", "furoat"},
    "stearate": {"stearate", "estearato", "stearat"},
    "aceponate": {"aceponate", "aceponato"},
    "buteprate": {"buteprate", "buteprato"},
    "undecanoate": {"undecanoate", "undecanoato"},
}

# 水合物标记：不影响「盐代码」，但会影响折算（多 k·H2O），apply 阶段默认跳过
WATER_TOKENS = {
    "hydrate", "monohydrate", "dihydrate", "trihydrate", "tetrahydrate",
    "hemihydrate", "sesquihydrate", "hemipentahydrate", "pentahydrate",
    "hexahydrate", "heptahydrate", "octahydrate",
    "hidrato", "monohidrato", "dihidrato", "trihidrato", "tetrahidrato",
    "hemihidrato", "sesquihidrato", "hidrat",
}

# 无水晶型说明：不改变分子量，可以正常折算
ANHYDROUS_TOKENS = {"anhydrous", "anhidro", "anhidra", "anhidro", "anhydre", "anhyd"}

# 溶剂化物 / 晶型修饰词：会改变分子量且不是盐，出现即人工核对
SOLVATE_TOKENS = {
    "solvate", "solvato", "ethanolate", "etanolato", "methanolate",
    "metanolato", "isopropanolate", "propanolato", "propylene", "glycol",
    "monoethanolate",
}

# 明确不是盐的词（疫苗株、油脂、螯合物、动植物提取物、生物制品、无机氧化物…）
NON_SALT_TOKENS = {
    # 生物制品 / 疫苗
    "human", "inactivated", "activated", "recombinant", "synthetic", "toxoid",
    "protein", "carrier", "complex", "immunoglobulin", "serum", "plasma",
    "peptide", "dna", "rna", "mrna", "vlp", "bcg", "cell", "culture",
    "diploid", "virus", "vaccine", "strain", "strain", "bovine", "equine",
    "ovine", "feline", "canine", "porcine", "pork", "calf", "rabbit", "mouse",
    "rat", "ins", "nph", "fsh", "fim", "rh", "prp", "bsa", "crm",
    # 油脂 / 提取物
    "oil", "oils", "extract", "tincture", "resin", "oleoresin", "powder",
    "kelp", "yeast", "liver", "egg", "shell", "shells", "oyster", "dolomite",
    "bone", "meal", "wheat", "soy", "soybean", "palm", "pineapple", "papaya",
    "papain", "bromelain", "echinacea", "feverfew", "hops", "valerian",
    "ginger", "anise", "coriander", "peppermint", "chamomile", "basil",
    "cinnamon", "capsicum", "currant", "cranberry", "acerola", "rosemary",
    "thistle", "buckwheat", "betula", "equisetum", "aloe", "senna", "sennosides",
    "ephedra", "pollen", "propolis", "shark", "cod", "halibut", "fish", "liver",
    "vegetable", "mineral", "plant", "dunaliella", "spirulina", "glucosamine",
    "chondroitin", "collagen", "gelatin", "casein", "albumin", "lactose",
    "starch", "cellulose", "silica", "talc", "kaolin", "charcoal",
    # 螯合物 / 矿物复合物（不是可折算的盐）
    "chelate", "chelated", "hvp", "amino", "durapatite",
    "hydroxyapatite", "hydroxide", "oxide", "carbonate", "bicarbonate",
}

# 有机物 / 药剂专用名词常见单字，出现即说明 salt 字段其实是完整成分名 → 人工核对
# （不在此表的未知词同样会走到 mixed/non_salt，这一组只是让常见药名更早落 mixed）


@dataclass
class SaltNorm:
    salt_code: str                 # '' / 'mixed' / 'non_salt' / canonical code
    kind: str                      # empty|salt|salt_hydrate|salt_mixed|ester|hydrate|non_salt|solvate
    tokens: list[str] = field(default_factory=list)
    reason: str = ""


def _ascii(text: str) -> str:
    """去重音 + 小写 + 非字母数字换空格。'Sódico' → 'sodico'，'povidone-iodine' → 两词。"""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    out = []
    for ch in s.lower():
        out.append(ch if ch.isalnum() else " ")
    return " ".join("".join(out).split())


def _tokenize(raw: str) -> list[str]:
    return [t for t in _ascii(raw).split() if t and not t.isdigit()]


_SALT_LOOKUP: dict[str, str] = {
    alias: code for code, aliases in SALT_ALIASES.items() for alias in aliases
}
_ESTER_LOOKUP: dict[str, str] = {
    alias: code for code, aliases in ESTER_TOKENS.items() for alias in aliases
}


def classify_salt(raw: str) -> SaltNorm:
    """盐字符串 → SaltNorm。纯函数，ingest 与回填脚本共用同一套口径。"""
    tokens = _tokenize(raw)
    if not tokens:
        if (raw or "").strip():
            return SaltNorm("non_salt", "non_salt", tokens, "只有数字/符号")
        return SaltNorm("", "empty", tokens, "salt 为空")

    salt_codes: list[str] = []
    esters: list[str] = []
    waters: list[str] = []
    anhydrous = False
    solvates: list[str] = []
    unknown: list[str] = []
    non_salt_hit: list[str] = []

    for tok in tokens:
        if tok in _SALT_LOOKUP:
            salt_codes.append(_SALT_LOOKUP[tok])
        elif tok in _ESTER_LOOKUP:
            esters.append(_ESTER_LOOKUP[tok])
        elif tok in WATER_TOKENS:
            waters.append(tok)
        elif tok in ANHYDROUS_TOKENS:
            anhydrous = True
        elif tok in SOLVATE_TOKENS:
            solvates.append(tok)
        elif tok in NON_SALT_TOKENS:
            non_salt_hit.append(tok)
        else:
            unknown.append(tok)

    # 1) 明确非盐词优先：疫苗/油脂/螯合物/生物制品，哪怕同时出现一个盐词
    if non_salt_hit:
        return SaltNorm("non_salt", "non_salt", tokens,
                        f"非盐标记 {sorted(set(non_salt_hit))}")
    # 2) 溶剂化物：不是盐、改分子量，必须人工
    if solvates:
        return SaltNorm("mixed", "solvate", tokens,
                        f"溶剂化物 {sorted(set(solvates))}，非盐需人工核对")
    # 3) 多个盐词 / 盐词+酯 / 盐词+未知词 → 复盐或整段成分名，人工核对
    if len(salt_codes) > 1:
        return SaltNorm("mixed", "salt_mixed", tokens,
                        f"多个盐词 {sorted(set(salt_codes))}")
    if len(salt_codes) == 1 and (esters or unknown):
        bits = sorted(set(salt_codes + esters + unknown))
        return SaltNorm("mixed", "salt_mixed", tokens, f"盐+未识别词 {bits}")
    # 4) 恰好一个盐词，其余只是水合物/无水晶型说明 → 可折算（水合物单独标记）
    if len(salt_codes) == 1:
        code = salt_codes[0]
        if code == "hyclate":               # 复盐+溶剂化物，折算表标"必须人工核对"
            return SaltNorm("hyclate", "review", tokens, "hyclate 复盐，须人工核对")
        if waters:
            return SaltNorm(code, "salt_hydrate", tokens,
                            f"水合物 {sorted(set(waters))}，按无水/含水计须核说明书")
        return SaltNorm(code, "salt", tokens,
                        "无水晶型说明" if anhydrous else "单一盐")
    # 5) 没有盐词：酯 / 只有水合物 / 其它垃圾
    if esters:
        return SaltNorm("non_salt", "ester", tokens,
                        f"酯（非盐）{sorted(set(esters))}，应落 variant.ester")
    if waters:
        return SaltNorm("non_salt", "hydrate", tokens,
                        f"只有水合物 {sorted(set(waters))}，没有盐")
    return SaltNorm("non_salt", "non_salt", tokens, "无可识别盐型 token")


def salt_code_of(raw: str) -> str:
    """轻量封装：给 ingest 用，只要 salt_code。"""
    return classify_salt(raw).salt_code


# ---------------------------------------------------------------------------
# DB 辅助
# ---------------------------------------------------------------------------
_HAS_SALT_CODE: dict[int, bool] = {}


def has_salt_code_column(db: sqlite3.Connection) -> bool:
    key = id(db)
    if key not in _HAS_SALT_CODE:
        cols = {r[1] for r in db.execute("PRAGMA table_info(variant)")}
        _HAS_SALT_CODE[key] = "salt_code" in cols
    return _HAS_SALT_CODE[key]


def insert_variant(db: sqlite3.Connection, variant_id: str, substance_id: str,
                   salt: str) -> None:
    """ingest 统一入口：老库没迁移时自动退回旧 SQL（不写 salt_code）。"""
    code = salt_code_of(salt or "")
    if has_salt_code_column(db):
        db.execute(
            "INSERT OR IGNORE INTO variant (variant_id, substance_id, salt, salt_code)"
            " VALUES (?,?,?,?)",
            (variant_id, substance_id, salt or "", code),
        )
    else:
        db.execute(
            "INSERT OR IGNORE INTO variant (variant_id, substance_id, salt)"
            " VALUES (?,?,?)",
            (variant_id, substance_id, salt or ""),
        )


def _connect(db_path: Path, write: bool) -> sqlite3.Connection:
    if write:
        return sqlite3.connect(db_path, timeout=120)
    uri = f"file:{db_path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=120)


def _guard_target(db_path: Path, action: str, confirmed: bool) -> None:
    """真实库只读轮次：--apply/--rollback 默认拒绝，必须显式 --confirm-real-db。"""
    try:
        is_real = db_path.resolve() == DEFAULT_DB.resolve()
    except OSError:
        is_real = False
    if is_real and action in ("apply", "rollback") and not confirmed:
        raise SystemExit(
            f"拒绝在真实库 {db_path} 上执行 --{action}：本轮只允许副本验证。\n"
            "确认要写时加 --confirm-real-db，并先备份 data/drugs.db。"
        )


def _counts(db: sqlite3.Connection) -> dict[str, int]:
    rows = db.execute(
        "SELECT salt_code, COUNT(*) FROM variant GROUP BY salt_code").fetchall()
    return {code: n for code, n in rows}


def _planned_changes(db: sqlite3.Connection) -> tuple[list[tuple], list[dict]]:
    """返回 (changes, audit)：changes=[(variant_id, before, after)]，仅含实际变化。"""
    if has_salt_code_column(db):
        current = {vid: code for vid, code in
                   db.execute("SELECT variant_id, salt_code FROM variant")}
    else:
        current = {}                    # 老库还没迁移：before 一律视为 ''
    changes: list[tuple[str, str, str]] = []
    audit: dict[str, dict] = {}
    for vid, salt in db.execute("SELECT variant_id, salt FROM variant"):
        norm = classify_salt(salt)
        if current.get(vid, "") != norm.salt_code:
            changes.append((vid, current.get(vid, ""), norm.salt_code))
        key = salt or ""
        row = audit.setdefault(key, {
            "salt_raw": key, "n_variants": 0, "salt_code": norm.salt_code,
            "kind": norm.kind, "reason": norm.reason,
        })
        row["n_variants"] += 1
    return changes, sorted(audit.values(), key=lambda r: (-r["n_variants"], r["salt_raw"]))


def _write_audit(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["salt_raw", "n_variants", "salt_code",
                                           "kind", "reason"])
        w.writeheader()
        w.writerows(rows)


def _write_backup(changes: list[tuple], backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = backup_dir / f"rollback_normalize_salts_{stamp}.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["variant_id", "salt_code_before", "salt_code_after"])
        w.writerows(changes)
    latest = backup_dir / "rollback_normalize_salts_latest.csv"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _latest_backup(backup_dir: Path) -> Path | None:
    files = sorted(backup_dir.glob("rollback_normalize_salts_*.csv"))
    files = [p for p in files if not p.name.endswith("_latest.csv")]
    return files[-1] if files else None


def _print_summary(db: sqlite3.Connection, audit: list[dict],
                   changes: list[tuple], title: str) -> None:
    total = db.execute("SELECT COUNT(*) FROM variant").fetchone()[0]
    with_salt = db.execute(
        "SELECT COUNT(*) FROM variant WHERE salt <> ''").fetchone()[0]
    by_kind: dict[str, int] = {}
    for r in audit:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + r["n_variants"]
    by_code: dict[str, int] = {}
    for r in audit:
        by_code[r["salt_code"]] = by_code.get(r["salt_code"], 0) + r["n_variants"]
    canonical = sum(n for c, n in by_code.items() if c not in ("", "mixed", "non_salt"))
    print(f"=== {title} ===")
    print(f"variant 总数             : {total:,}")
    print(f"salt 非空（原值）        : {with_salt:,}  去重 {len(audit):,} 个串")
    print(f"分类（按 variant 计）    : 可折算单盐 {canonical:,} / mixed "
          f"{by_code.get('mixed', 0):,} / non_salt {by_code.get('non_salt', 0):,} / "
          f"空 {by_code.get('', 0):,}")
    print(f"按形态                   : {dict(sorted(by_kind.items()))}")
    if changes:
        before = sum(1 for _, b, _ in changes if b != "")
        print(f"本次实际变更行           : {len(changes):,}（原 salt_code 非空 {before:,}）")
    else:
        print("本次实际变更行           : 0（已是最新口径，幂等）")


def cmd_dry_run(args: argparse.Namespace) -> int:
    db = _connect(args.db, write=False)
    changes, audit = _planned_changes(db)
    _print_summary(db, audit, changes, "normalize_salts --dry-run")
    _write_audit(audit, args.out)
    print(f"审计 CSV                 : {args.out}")
    db.close()
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    db = _connect(args.db, write=True)
    try:
        if not has_salt_code_column(db):
            raise SystemExit(f"{args.db} 还没有 variant.salt_code 列："
                             "先跑 python db/init_db.py --db <path>")
        changes, audit = _planned_changes(db)
        _print_summary(db, audit, changes, "normalize_salts --apply")
        _write_audit(audit, args.out)
        if not changes:
            print("无需写库。")
            return 0
        backup = _write_backup(changes, args.backup_dir)
        print(f"回滚备份                 : {backup}")
        with db:
            db.executemany(
                "UPDATE variant SET salt_code=? WHERE variant_id=?",
                [(after, vid) for vid, _, after in changes],
            )
        print(f"已写入 {len(changes):,} 行 salt_code。")
    finally:
        db.close()
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    path = args.rollback_file or _latest_backup(args.backup_dir)
    if path is None:
        print(f"找不到备份 CSV（{args.backup_dir}），无法回滚。", file=sys.stderr)
        return 1
    with Path(path).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    db = _connect(args.db, write=True)
    try:
        if not has_salt_code_column(db):
            raise SystemExit(f"{args.db} 还没有 variant.salt_code 列："
                             "先跑 python db/init_db.py --db <path>")
        todo = []
        skipped = 0
        current = {vid: code for vid, code in
                   db.execute("SELECT variant_id, salt_code FROM variant")}
        for r in rows:
            vid = r["variant_id"]
            if current.get(vid, "") == r["salt_code_after"]:
                todo.append((r["salt_code_before"], vid))
            else:
                skipped += 1
        with db:
            db.executemany("UPDATE variant SET salt_code=? WHERE variant_id=?", todo)
        print(f"=== normalize_salts --rollback ===")
        print(f"备份文件                 : {path}")
        print(f"还原行数                 : {len(todo):,}（跳过已变更 {skipped:,}）")
    finally:
        db.close()
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    db = _connect(args.db, write=False)
    if not has_salt_code_column(db):
        print(f"{args.db} 还没有 variant.salt_code 列：先跑 db/init_db.py",
              file=sys.stderr)
        db.close()
        return 1
    counts = _counts(db)
    print("=== normalize_salts --verify ===")
    for code, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {code or '(空)':24} {n:,}")
    print(f"  合计 {sum(counts.values()):,}")
    db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB,
                    help=f"SQLite 路径（默认 {DEFAULT_DB}）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只统计/写审计 CSV（默认）")
    mode.add_argument("--apply", action="store_true", help="事务写 variant.salt_code")
    mode.add_argument("--rollback", action="store_true", help="用备份 CSV 还原")
    mode.add_argument("--verify", action="store_true", help="打印 salt_code 分布")
    ap.add_argument("--out", type=Path, default=DEFAULT_AUDIT,
                    help=f"审计 CSV 输出路径（默认 {DEFAULT_AUDIT}）")
    ap.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    ap.add_argument("--rollback-file", type=Path, default=None)
    ap.add_argument("--confirm-real-db", action="store_true",
                    help="允许写 data/drugs.db（默认拒绝）")
    args = ap.parse_args(argv)

    action = "verify" if args.verify else ("rollback" if args.rollback
                                           else ("apply" if args.apply else "dry_run"))
    if action in ("apply", "rollback"):
        _guard_target(args.db, action, args.confirm_real_db)
    if not args.db.exists():
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 1

    if action == "verify":
        return cmd_verify(args)
    if action == "rollback":
        return cmd_rollback(args)
    if action == "apply":
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
