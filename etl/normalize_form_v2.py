"""剂型 / 释放机制归一化 v2（task-7）：把四条规则一次性落到存量库（默认只跑 dry-run）。

背景
----
- `reports/consistency-audit-form-20261110.md`（R1 剂型族、R2 回退成原文整串、R3 释放机制）
- `reports/form-effervescent-20261110.md`（新增 `effervescent` 类，948 行）

四条规则（每条都给「改前 → 改后」计数）
------------------------------------
FORM-EFF       原文写泡腾（7 种拼写）→ `form_base='effervescent'`
FORM-ORDER     原文写注射剂 / 粉剂，但 `form_base='liquid'` → `injection` / `powder`
               （`FORM_BASES` 里 `liquid` 原先排第 3，把 `injection, solution`、`Powder For
               Solution` 全吃成液体；现在 `liquid` 排最后）
FORM-FALLBACK  `form_base` 回退成原文整串 → 词表认得的落具体类，认不出的一律 `other`
RELEASE        原文写缓释/控释/肠溶，但 `release='none'` → `ER` / `DR`

判定谓词**不在这里写**（仓库里已经有 5 套剂型实现，本脚本是第 6 处调用点，不是第 6 套规则）
----
- `form_base_of()` / `release_of()` ← `etl/ingest_openfda_ndc.py`（各入库脚本共用同一套）
- 西语 / 繁中 / 简中 → 英文剂型 ← `ingest_cima.form_base_es` / `ingest_tw_tfda.tw_form_base`
  / `ingest_nhsa.translate_form`（各自的来源语言只有它认）
- 「回退成原文整串」← `db/consistency_audit_form.py` 的 `is_unmapped()`
- 释放词表复核 ← `db/consistency_audit_form.py` 的 `RE_ER` / `RE_DR`（审计同一套口径）

CN 只做 `effervescent`
---------------------
CN 的 `form_base` 是「中文剂型 → 英文词 → form_base_of → cleanup_cn_data 白名单」三段拼出来的，
直接按原文重算会把 `糊剂`/`冻干粉`/`锭剂` 这类已收敛到 canonical 的 1,005 行打回 `other`
（dry-run 实测），所以 CN 只落 `effervescent` 这一类，其余保持 `cleanup_cn_data` 的口径。

用法
----
    & $py etl/normalize_form_v2.py                        # dry-run（默认，只读）
    & $py etl/normalize_form_v2.py --db .tmp/copy.db --apply --journal .tmp/j.csv
    & $py etl/normalize_form_v2.py --apply --allow-real   # 写真实库（先自动备份 + 写 journal）
    & $py etl/normalize_form_v2.py --rollback             # 按 journal 反向恢复（幂等）

回滚点：`data/backups/drugs-before-normalize-v2-<run_id>.db`（apply 前自动复制）
journal：`data/backups/form-normalization-v2-journal-<run_id>.csv`（`--journal` 可改路径；
`data/backups/` 按 AGENTS §9 不入库，它和备份是同一份回滚资产）
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "db"))

from consistency_audit_form import (  # noqa: E402  审计的谓词（单一来源）
    PLACEHOLDER_BASES, RE_DR, RE_ER, classify, is_unmapped,
)
from ingest_cima import form_base_es as cima_form_base  # noqa: E402
from ingest_mx import form_base_es as mx_form_base  # noqa: E402
from ingest_nhsa import translate_form  # noqa: E402
from ingest_openfda_ndc import form_base_of, release_of  # noqa: E402
from ingest_tw_tfda import tw_form_base  # noqa: E402

DB = ROOT / "data" / "drugs.db"
BACKUP_DIR = ROOT / "data" / "backups"
REAL_DB = DB.resolve()

RULE_EFF = "FORM-EFF"
RULE_ORDER = "FORM-ORDER"
RULE_FALLBACK = "FORM-FALLBACK"
RULE_RELEASE = "RELEASE"
RULE_ORDER_LIST = (RULE_EFF, RULE_ORDER, RULE_FALLBACK, RULE_RELEASE)
RULE_DESC = {
    RULE_EFF: "泡腾 → form_base='effervescent'",
    RULE_ORDER: "原文写注射剂/粉剂而 form_base='liquid' → injection / powder",
    RULE_FALLBACK: "form_base 回退成原文整串 → 具体类，认不出落 other",
    RULE_RELEASE: "原文写缓释/肠溶而 release='none' → ER / DR",
}


@dataclass(frozen=True)
class Change:
    product_id: str
    field: str          # form_base / release
    old: str
    new: str
    rule: str
    market: str
    source_id: str


class _Row:
    """只带 form_base 的壳子：`is_unmapped()` 只看这个字段。"""

    __slots__ = ("form_base",)

    def __init__(self, form_base: str) -> None:
        self.form_base = form_base


# ---------------------------------------------------------------- 读库

@dataclass(frozen=True)
class ProductRow:
    product_id: str
    market: str
    dosage_form: str
    form_base: str | None
    release: str
    source_id: str


def connect(path: Path, write: bool) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"找不到数据库：{path}")
    if write:
        return sqlite3.connect(path, timeout=180)
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=180)


def load_rows(con: sqlite3.Connection) -> list[ProductRow]:
    out: list[ProductRow] = []
    for pid, country, region, form, fbase, rel, src in con.execute(
        "SELECT product_id, country, region, dosage_form, form_base, release, source_id"
        " FROM product"
    ):
        out.append(ProductRow(pid, country or region or "?", form or "", fbase,
                              rel or "none", src or ""))
    return out


# ---------------------------------------------------------------- 规则

def predict_form_base(p: ProductRow) -> str:
    """按该市场的入库翻译器重算 form_base（与各 ingest 的产出同一套规则）。"""
    if p.market == "TW":
        return tw_form_base(p.dosage_form)
    if p.market == "ES":
        return cima_form_base(p.dosage_form)
    if p.market == "MX":
        return mx_form_base(p.dosage_form)
    if p.market == "CN":
        return form_base_of(translate_form(p.dosage_form))
    return form_base_of(p.dosage_form)


def is_fallback_value(old: str) -> bool:
    """旧值是不是「归一化没命中、把原文塞进 form_base」（审计 R2 的判据）。"""
    b = (old or "").strip()
    if not b or b.lower() in PLACEHOLDER_BASES:
        return False
    return is_unmapped(_Row(b))


def family_accepts(dosage_form: str, base: str) -> bool:
    """审计的族判据认不认这个目标值。

    FORM-ORDER 用它当闸门：原文里同时有 `vial` 和 `nebuliser` 的（GB 286 行
    `… nebuliser liquid unit dose vials`）审计判「吸入族」，改成 injection 会**新增**
    一条冲突；这类行留在 `liquid`（审计判 coarse，不算错），并计入「规则外」清单。
    """
    fam = classify(dosage_form)
    if fam is None:
        return True
    return fam.fam_id == base or base in fam.ok


def plan(rows: list[ProductRow]) -> tuple[list[Change], list[Change]]:
    """返回 (要改的行, 规则外会变但不动的行)。"""
    changes: list[Change] = []
    outside: list[Change] = []
    for p in rows:
        new_fb = predict_form_base(p)
        old_fb = (p.form_base or "").strip()
        # form_base：NULL 表示来源根本没有剂型列（HK 13,935 行），不动
        if p.form_base is not None and new_fb != old_fb:
            if new_fb == "effervescent":
                rule = RULE_EFF
            elif p.market == "CN":
                rule = ""            # CN 只做 effervescent（见模块 docstring）
            elif old_fb == "liquid" and new_fb in ("injection", "powder") \
                    and family_accepts(p.dosage_form, new_fb):
                rule = RULE_ORDER
            elif old_fb == "liquid" and new_fb in ("injection", "powder"):
                rule = ""            # 原文族判为别的剂型（吸入/眼用/试剂盒），不按注射/粉剂改
            elif is_fallback_value(old_fb):
                rule = RULE_FALLBACK
            else:
                rule = ""
            item = Change(p.product_id, "form_base", old_fb, new_fb, rule,
                          p.market, p.source_id)
            (changes if rule else outside).append(item)
        # release：只在 now='none' 时补判，绝不覆盖已有值（CN/ES 的部分 release 是按
        # 商品名推的，重算会抹掉；反向 8,392 行属显示层要标注的问题，不在本规则内）
        if p.release == "none":
            new_rel = release_of(p.dosage_form)
            if new_rel != "none":
                changes.append(Change(p.product_id, "release", "none", new_rel,
                                      RULE_RELEASE, p.market, p.source_id))
    return changes, outside


# ---------------------------------------------------------------- 下游影响（只读）

def downstream_counts(con: sqlite3.Connection, changes: list[Change]) -> dict[str, int]:
    """受影响的下游产物条数：name_key / 成分页 / 矩阵拆分行 / 单包装页。

    口径（与 site/build.py 的两条展示路径对应）：
      name_key         检索索引里 `f`（剂型集合）会变的名字 key（任一 name_type）
      成分页            受影响成分数（成分页的剂型筛选器 / 矩阵行）
      matrix_split_rows 改前泡腾与非泡腾混在同一个「成分×释放×规格」键里、改后拆开的键
      单包装页          只挂一个产品的 trade 名 key（走 raw form 表格那批页）
    """
    pid_fb = {c.product_id: c.new for c in changes if c.field == "form_base"}
    pids = set(pid_fb)
    if not pids:
        return {"name_key": 0, "substance": 0, "matrix_split_rows": 0,
                "single_pack_keys": 0}
    trade_products: dict[str, set[str]] = defaultdict(set)
    eff_keys: set[str] = set()
    eff_trade_keys: set[str] = set()
    for pid, kid, ntype in con.execute(
            "SELECT product_id, key_id, name_type FROM product_name"):
        if ntype == "trade":
            trade_products[kid].add(pid)
        if pid in pids:
            eff_keys.add(kid)
            if ntype == "trade":
                eff_trade_keys.add(kid)

    substance = con.execute(
        "SELECT COUNT(DISTINCT v.substance_id) FROM product_component pc"
        f" JOIN variant v ON v.variant_id = pc.variant_id"
        f" WHERE pc.product_id IN ({','.join('?' * len(pids))})", sorted(pids)).fetchone()[0]

    # 矩阵行键（site/build.py）= (成分, 释放机制, 规格)；泡腾与非泡腾混在同一键里会被
    # 合成一行，改后拆开。这里数「改前混合、改后不再混合」的键。
    groups: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for sid, rel, val, unit, pid in con.execute(
        "SELECT v.substance_id, p.release, pc.strength_value, pc.strength_unit, p.product_id"
        " FROM product p JOIN product_component pc ON pc.product_id = p.product_id"
        " JOIN variant v ON v.variant_id = pc.variant_id WHERE pc.ord = 0"):
        g = groups[(sid, rel, val, unit)]
        g[0 if pid_fb.get(pid) == "effervescent" else 1] += 1
    matrix_split = sum(1 for g in groups.values() if g[0] and g[1])
    return {"name_key": len(eff_keys), "substance": substance,
            "matrix_split_rows": matrix_split,
            "single_pack_keys": sum(1 for k in eff_trade_keys if len(trade_products[k]) == 1)}


def remaining_conflicts(rows: list[ProductRow], changes: list[Change]) -> dict[str, int]:
    """按「改后」的投影状态复核四条验收式。

    族口径（`classify`）与关键词口径（`form_base_of`）都算一遍：族口径是审计报告的口径
    （「注射剂误判剩余 0」按它验收），关键词口径多出来的部分是原文含注射/粉剂字样、但
    审计判成别的剂型族的行（列明原因，不算未修的错）。
    """
    fb = {c.product_id: c.new for c in changes if c.field == "form_base"}
    rel = {c.product_id: c.new for c in changes if c.field == "release"}
    inj_fam = pow_fam = inj_kw = pow_kw = 0
    eff = 0
    rel_conflict = 0
    powder_shaped: Counter[str] = Counter()
    kw_residue: dict[str, Counter] = {"injection": Counter(), "powder": Counter()}
    for p in rows:
        now_fb = fb.get(p.product_id, (p.form_base or "").strip())
        now_rel = rel.get(p.product_id, p.release)
        want = predict_form_base(p)
        fam = classify(p.dosage_form)
        fam_id = fam.fam_id if fam else ""
        if now_fb == "effervescent":
            eff += 1
        if now_fb == "liquid" and fam_id == "injection":
            inj_fam += 1
        if now_fb == "liquid" and fam_id == "powder":
            pow_fam += 1
        if now_fb == "liquid" and want == "injection":
            inj_kw += 1
            kw_residue["injection"][fam_id or "未命中"] += 1
        if now_fb == "liquid" and want == "powder":
            pow_kw += 1
            kw_residue["powder"][fam_id or "未命中"] += 1
        if now_fb not in ("powder", "effervescent", "injection") and want == "powder":
            powder_shaped[f"{now_fb or '∅'} → {want}"] += 1
        text = p.dosage_form.lower()
        if now_rel == "none" and (RE_ER.search(text) or RE_DR.search(text)):
            rel_conflict += 1
    return {"effervescent": eff, "injection_mislabeled": inj_fam,
            "powder_mislabeled": pow_fam, "release_none_with_text": rel_conflict,
            "injection_keyword_residue": inj_kw, "powder_keyword_residue": pow_kw,
            "kw_residue_detail": kw_residue,
            "powder_shaped_not_powder": sum(powder_shaped.values()),
            "powder_shaped_detail": powder_shaped}


# ---------------------------------------------------------------- 输出

def print_plan(changes: list[Change], outside: list[Change], top: int = 8) -> None:
    print(f"\n=== 计划改动 {len(changes):,} 行 ===")
    for rule in RULE_ORDER_LIST:
        items = [c for c in changes if c.rule == rule]
        if not items:
            continue
        print(f"\n[{rule}] {RULE_DESC[rule]}：{len(items):,} 行")
        print("  按市场：" + "  ".join(f"{k}={v:,}" for k, v in
                                    Counter(c.market for c in items).most_common()))
        print("  按来源：" + "  ".join(f"{k}={v:,}" for k, v in
                                    Counter(c.source_id for c in items).most_common()))
        pairs = Counter((c.old or "∅", c.new) for c in items)
        print(f"  改前→改后 Top {top}：")
        for (old, new), n in pairs.most_common(top):
            print(f"    {n:>6,}  {old!r} → {new!r}")

    if outside:
        print(f"\n[规则外] 新规则会算出不同值、但**不在本脚本改动范围**：{len(outside):,} 行")
        print("  按市场：" + "  ".join(f"{k}={v:,}" for k, v in
                                    Counter(c.market for c in outside).most_common()))
        for (old, new), n in Counter((c.old or "∅", c.new) for c in outside).most_common(top):
            markets = Counter(c.market for c in outside
                              if (c.old or "∅", c.new) == (old, new))
            print(f"    {n:>6,}  {old!r} → {new!r}   {dict(markets.most_common(4))}")


def print_checks(checks: dict[str, int], down: dict[str, dict[str, int]],
                 rows_n: int) -> None:
    print("\n=== 改后复核（投影状态，尚未写库）===")
    print(f"  effervescent 条数：{checks['effervescent']:,}（预期 948）")
    print(f"  注射剂误判剩余（审计族判 injection、form_base 仍 liquid）："
          f"{checks['injection_mislabeled']:,}（预期 0）")
    print(f"  粉剂误判剩余（审计族判 powder、form_base 仍 liquid）："
          f"{checks['powder_mislabeled']:,}（预期 0）")
    print(f"  AU/SG release='none' 与原文冲突剩余：{checks['release_none_with_text']:,}（预期 0）")
    print(f"  原文含注射词但 form_base 仍 liquid：{checks['injection_keyword_residue']:,}"
          f"  族分布 {dict(checks['kw_residue_detail']['injection'].most_common(6))}")
    print(f"  原文含粉剂词但 form_base 仍 liquid：{checks['powder_keyword_residue']:,}"
          f"  族分布 {dict(checks['kw_residue_detail']['powder'].most_common(6))}")
    print(f"  原文写粉剂但 form_base 不是 powder/effervescent/injection："
          f"{checks['powder_shaped_not_powder']:,}")
    for k, n in list(checks["powder_shaped_detail"].most_common(8)):
        print(f"      {n:>6,}  {k}")
    print("\n=== 下游影响（现查）===")
    print(f"  {'口径':<8} {'name_key':>9} {'成分页':>7} {'矩阵拆分行':>10} {'单包装页':>9}")
    for label, d in down.items():
        print(f"  {label:<8} {d['name_key']:>9,} {d['substance']:>7,}"
              f" {d['matrix_split_rows']:>10,} {d['single_pack_keys']:>9,}")
    print("  （预期：泡腾口径 806 / 204 / 145 / 484）")
    print(f"  product 总数（不变）：{rows_n:,}")


# ---------------------------------------------------------------- 写库

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_id() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


def backup_db(path: Path, run_id: str) -> Path:
    """写库前先复制一份：真实库落到 `data/backups/`，副本演练落在 DB 同目录。"""
    dest_dir = BACKUP_DIR if path.resolve() == REAL_DB else path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{path.stem}-before-normalize-v2-{run_id}.db"
    if path.resolve() == REAL_DB:
        dest = dest_dir / f"drugs-before-normalize-v2-{run_id}.db"
    shutil.copy2(path, dest)
    return dest


def write_journal(changes: list[Change], run_id: str, journal: Path) -> Path:
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run_id", "product_id", "field", "old_value", "new_value",
                    "rule", "market", "source_id", "applied_at"])
        stamp = _now()
        for c in changes:
            w.writerow([run_id, c.product_id, c.field, c.old, c.new, c.rule,
                        c.market, c.source_id, stamp])
    return journal


def apply_changes(con: sqlite3.Connection, changes: list[Change]) -> int:
    done = 0
    with con:                                  # 一个事务；任何一条对不上都回滚
        for c in changes:
            cur = con.execute(
                f"UPDATE product SET {c.field} = ? WHERE product_id = ? AND {c.field} = ?",
                (c.new, c.product_id, c.old))
            if cur.rowcount != 1:
                raise SystemExit(
                    f"写入失败：{c.product_id} 的 {c.field} 不是 {c.old!r}"
                    f"（rowcount={cur.rowcount}），已回滚，请重新 dry-run")
            done += cur.rowcount
    return done


def read_journal(journal: Path) -> list[Change]:
    with journal.open(encoding="utf-8") as fh:
        return [Change(r["product_id"], r["field"], r["old_value"], r["new_value"],
                       r["rule"], r["market"], r["source_id"]) for r in csv.DictReader(fh)]


def rollback(con: sqlite3.Connection, changes: list[Change]) -> int:
    done = 0
    with con:
        for c in changes:
            cur = con.execute(
                f"UPDATE product SET {c.field} = ? WHERE product_id = ? AND {c.field} = ?",
                (c.old, c.product_id, c.new))
            done += cur.rowcount
    return done


def post_check(con: sqlite3.Connection) -> None:
    quick = con.execute("PRAGMA quick_check").fetchone()[0]
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    print(f"  PRAGMA quick_check：{quick}")
    print(f"  PRAGMA foreign_key_check：{len(fk)} 行违规")


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="剂型/释放机制归一化 v2（task-7）")
    ap.add_argument("--db", default=str(DB), help="数据库路径（默认 data/drugs.db）")
    ap.add_argument("--dry-run", action="store_true", help="只读 + 只打印（默认）")
    ap.add_argument("--apply", action="store_true", help="写库（先自动备份 + 写 journal）")
    ap.add_argument("--rollback", action="store_true", help="按 journal 反向恢复")
    ap.add_argument("--journal", default="", help="journal CSV 路径（rollback 时读）")
    ap.add_argument("--run-id", default="", help="rollback 用的 run_id 选择 journal")
    ap.add_argument("--allow-real", action="store_true", help="允许写真实库 data/drugs.db")
    ap.add_argument("--top", type=int, default=8, help="每类给几个样例（默认 8）")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.apply and args.rollback:
        raise SystemExit("--apply 与 --rollback 只能选一个")
    db_path = Path(args.db)
    mode = "apply" if args.apply else "rollback" if args.rollback else "dry-run"

    if mode == "rollback":
        journal = Path(args.journal) if args.journal else _latest_journal(args.run_id)
        if not journal.exists():
            raise SystemExit(f"找不到 journal：{journal}")
        changes = read_journal(journal)
        if db_path.resolve() == REAL_DB and not args.allow_real:
            raise SystemExit("回滚真实库要加 --allow-real（先确认备份与 report 口径）")
        con = connect(db_path, write=True)
        n = rollback(con, changes)
        print(f"=== 回滚 {journal.name}：{n:,} 行恢复（journal {len(changes):,} 行）===")
        by_rule = Counter(c.rule for c in changes)
        print("  按规则：" + "  ".join(f"{k}={v:,}" for k, v in by_rule.most_common()))
        post_check(con)
        con.close()
        return 0

    con = connect(db_path, write=(mode == "apply"))
    rows = load_rows(con)
    changes, outside = plan(rows)
    print(f"=== 剂型/释放机制归一化 v2（{mode}）  products={len(rows):,}  "
          f"库={db_path} ===")
    print_plan(changes, outside, args.top)
    checks = remaining_conflicts(rows, changes)
    down = {
        "泡腾": downstream_counts(con, [c for c in changes if c.rule == RULE_EFF]),
        "全量": downstream_counts(con, changes),
    }
    print_checks(checks, down, len(rows))

    if mode == "dry-run":
        print("\n（dry-run：只读，未写库。加 --apply --allow-real 才落库）")
        con.close()
        return 0

    if db_path.resolve() == REAL_DB and not args.allow_real:
        con.close()
        raise SystemExit("写真实库要加 --allow-real（Lead 批准后）")

    run_id = args.run_id or _run_id()
    journal = Path(args.journal) if args.journal else (
        BACKUP_DIR / f"form-normalization-v2-journal-{run_id}.csv")
    backup = backup_db(db_path, run_id)
    print(f"\n=== 写库 ===")
    print(f"  备份：{backup}")
    print(f"  journal：{journal}")
    n = apply_changes(con, changes)
    write_journal(changes, run_id, journal)
    print(f"  已改 {n:,} 行（journal {len(changes):,} 行，run_id={run_id}）")
    post_check(con)
    for field in ("form_base", "release"):
        if field == "form_base":
            got = dict(con.execute("SELECT form_base, COUNT(*) FROM product"
                                   " GROUP BY 1 ORDER BY 2 DESC LIMIT 12"))
        else:
            got = dict(con.execute("SELECT release, COUNT(*) FROM product GROUP BY 1"))
        print(f"  改后 {field} 分布：{got}")
    con.close()
    return 0


def _latest_journal(run_id: str) -> Path:
    pat = (f"form-normalization-v2-journal-{run_id}.csv" if run_id
           else "form-normalization-v2-journal-*.csv")
    found = sorted(BACKUP_DIR.glob(pat))
    if not found:
        return BACKUP_DIR / "form-normalization-v2-journal-<run_id>.csv"
    return found[-1]


if __name__ == "__main__":
    raise SystemExit(main())
