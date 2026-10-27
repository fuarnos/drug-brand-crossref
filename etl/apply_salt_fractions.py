"""D2 盐基折算回填：`variant.base_fraction` ← 盐表 + 碱基分子量。

数据来源：
  - data/salt_base_fraction.csv —— 40 行盐→碱基通用折算规则（盐代码、化学计量
    比 n、反离子增量分子量 Δ、示例、PubChem 来源、验证状态）；
  - BASE_MW（本文件的 Python 常量，27 个物质的碱基分子量，来自
    .tmp/dose/base_mw_verified.csv 的 PubChem 逐条核对结果；可用 --base-mw-csv 覆盖）。

公式（reports/dose-mapping-plan.md §2.1）：

    f = n·M(base) / (n·M(base) + Δ)          （水合物再 + k·18.015）

写入条件（三条同时满足，否则只统计、不写库）：
  1. `salt_code` 命中盐表且是**单一可折算盐**（'mixed' / 'non_salt' / 'hyclate'
     自动排除；水合物默认排除，--include-hydrate 才按 k·H2O 折算）；
  2. `strength_basis` 已人工确认（base / salt / salt_equivalent）——默认全库
     'unknown'，未知时**只统计不写**，宁可不出结论也不猜；
  3. 该 substance 的碱基分子量已知，且 `base_fraction` 仍是默认 1.0（不覆盖人工值）。

CLI：
    python etl/apply_salt_fractions.py --dry-run     # 默认：出候选 CSV + 统计
    python etl/apply_salt_fractions.py --apply       # 事务写 base_fraction（先备份）
    python etl/apply_salt_fractions.py --rollback    # 用备份 CSV 还原
    python etl/apply_salt_fractions.py --verify      # 库里 base_fraction 分布

安全：真实库 data/drugs.db 上的 --apply/--rollback 需要显式 --confirm-real-db；
本轮只在 .tmp/dose-impl/ 的副本上验证应用/幂等/回滚。
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_salts import classify_salt, has_salt_code_column  # noqa: E402

DEFAULT_DB = ROOT / "data" / "drugs.db"
DEFAULT_CSV = ROOT / "data" / "salt_base_fraction.csv"
DEFAULT_BACKUP_DIR = ROOT / ".tmp" / "dose-impl" / "backups"
DEFAULT_AUDIT = ROOT / ".tmp" / "dose-impl" / "base_fraction_candidates.csv"
WATER_MW = 18.015

# 碱基分子量（PubChem 核对，2026-10 From .tmp/dose/base_mw_verified.csv）。
# 键 = substance_id；值 = (分子量 g/mol, 来源说明)。
BASE_MW: dict[str, tuple[float, str]] = {
    "amlodipine": (408.9, "PubChem C20H25ClN2O5 408.9"),
    "amoxicillin": (365.4, "PubChem C16H19N3O5S 365.4"),
    "atorvastatin": (558.6, "PubChem C33H35FN2O5 558.6"),
    "bupropion": (239.74, "PubChem C13H18ClNO 239.74"),
    "clindamycin": (425.0, "PubChem C18H33ClN2O5S 425.0"),
    "dexamethasone": (392.5, "PubChem C22H29FO5 392.5, back-calculated from salt"),
    "diclofenac": (296.15, "sodium salt 318.1 - 21.982"),
    "diphenhydramine": (255.35, "PubChem C17H21NO 255.35"),
    "erythromycin": (733.9, "PubChem C37H67NO13 733.9, back-calculated from salt"),
    "hydrocortisone": (362.5, "PubChem C21H30O5 362.5, back-calculated from salt"),
    "ibuprofen": (206.28, "PubChem C13H18O2 206.28, back-calculated from salt"),
    "levofloxacin": (361.4, "PubChem C18H20FN3O4 361.4, back-calculated from salt"),
    "levothyroxine": (776.87, "PubChem C15H11I4NO4 776.87"),
    "lidocaine": (234.34, "PubChem C14H22N2O 234.34"),
    "metformin": (129.16, "PubChem C4H11N5 129.16"),
    "metoprolol": (267.36, "PubChem C15H25NO3 267.36"),
    "naproxen": (230.26, "PubChem C14H14O3 230.26"),
    "olanzapine": (312.4, "PubChem C17H20N4S 312.4, back-calculated from salt"),
    "omeprazole": (345.4, "magnesium salt 713.1 - (2M+22.289)"),
    "phenylephrine": (167.2, "PubChem C9H13NO2 167.2"),
    "pseudoephedrine": (165.23, "PubChem C10H15NO 165.23"),
    "quetiapine": (383.5, "PubChem C21H25N3O2S 383.5"),
    "rosuvastatin": (481.5, "calcium salt 1001.1 - (2M+38.06)"),
    "sertraline": (306.2, "PubChem C17H17Cl2N 306.2"),
    "sildenafil": (474.6, "citrate 666.7 - 192.124"),
    "telmisartan": (514.6, "PubChem C33H30N4O2 514.6"),
    "venlafaxine": (277.4, "PubChem C17H27NO2 277.4"),
}

KNOWN_BASIS = {"base", "salt", "salt_equivalent"}


def load_rules(path: Path) -> dict[str, dict]:
    rules: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            code = (r.get("salt_code") or "").strip()
            if not code:
                continue
            rules[code] = {
                "salt_en": r.get("salt_en", ""),
                "category": r.get("category", ""),
                "n_base": int(float(r.get("n_base") or 1)),
                "increment_mw": float(r.get("increment_mw") or 0),
                "increment_formula": r.get("increment_formula", ""),
                "status": (r.get("status") or "").strip(),
            }
    return rules


def load_base_mw(path: Path | None) -> dict[str, tuple[float, str]]:
    """--base-mw-csv 覆盖内嵌 BASE_MW（列：substance_id,base_mw,source）。"""
    merged = dict(BASE_MW)
    if path is None:
        return merged
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            sid = (r.get("substance_id") or "").strip()
            if not sid:
                continue
            try:
                merged[sid] = (float(r["base_mw"]), r.get("source", ""))
            except (KeyError, TypeError, ValueError):
                continue
    return merged


def base_fraction(rule: dict, base_mw: float, water: float = 0.0) -> float:
    n = rule["n_base"]
    delta = rule["increment_mw"] + water * WATER_MW
    return n * base_mw / (n * base_mw + delta)


def _connect(db_path: Path, write: bool) -> sqlite3.Connection:
    if write:
        return sqlite3.connect(db_path, timeout=120)
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)


def _guard_target(db_path: Path, action: str, confirmed: bool) -> None:
    try:
        is_real = db_path.resolve() == DEFAULT_DB.resolve()
    except OSError:
        is_real = False
    if is_real and action in ("apply", "rollback") and not confirmed:
        raise SystemExit(
            f"拒绝在真实库 {db_path} 上执行 --{action}：本轮只允许副本验证。\n"
            "确认要写时加 --confirm-real-db，并先备份 data/drugs.db。"
        )


def _scan(db: sqlite3.Connection, rules: dict[str, dict],
          base_mw: dict[str, tuple[float, str]], include_hydrate: bool,
          only_verified: bool) -> tuple[list[dict], dict[str, int]]:
    sql = """
        SELECT v.variant_id, v.substance_id, v.salt, v.salt_code, v.strength_basis,
               v.base_fraction, v.hydrate, v.ester,
               (SELECT COUNT(*) FROM product_component pc
                 WHERE pc.variant_id = v.variant_id) AS n_components
        FROM variant v
        WHERE v.salt_code NOT IN ('', 'mixed', 'non_salt')
    """
    counts: dict[str, int] = {}
    rows: list[dict] = []

    def bump(k: str, n: int = 1) -> None:
        counts[k] = counts.get(k, 0) + n

    for (vid, sid, salt, code, basis, cur_f, hydrate, ester,
         n_comp) in db.execute(sql):
        norm = classify_salt(salt or "")
        row = {
            "variant_id": vid, "substance_id": sid, "salt": salt or "",
            "salt_code": code, "kind": norm.kind, "strength_basis": basis,
            "base_mw": "", "n_base": "", "increment_mw": "",
            "base_fraction": "", "n_components": n_comp,
            "decision": "", "reason": "",
        }
        bump("scanned_variants")
        if norm.kind in ("salt_hydrate",) and not include_hydrate:
            row["decision"], row["reason"] = "skip", "水合物：须先确认强度按无水/含水计"
            bump("skip_hydrate")
            counts["skip_hydrate_components"] = counts.get(
                "skip_hydrate_components", 0) + n_comp
            rows.append(row)
            continue
        rule = rules.get(code)
        if rule is None:
            row["decision"], row["reason"] = "skip", "salt_code 不在盐表"
            bump("skip_no_rule")
            rows.append(row)
            continue
        if rule["status"] == "manual_review":
            row["decision"], row["reason"] = "skip", "盐表标 manual_review"
            bump("skip_manual_review")
            rows.append(row)
            continue
        if only_verified and rule["status"] != "verified":
            row["decision"], row["reason"] = "skip", "非 verified（--only-verified）"
            bump("skip_not_verified")
            rows.append(row)
            continue
        if basis not in KNOWN_BASIS:
            row["decision"], row["reason"] = "basis_unknown", "strength_basis=unknown，只统计不写"
            bump("basis_unknown")
            counts["basis_unknown_components"] = counts.get(
                "basis_unknown_components", 0) + n_comp
            rows.append(row)
            continue
        if sid not in base_mw:
            row["decision"], row["reason"] = "skip", "无碱基分子量"
            bump("skip_no_base_mw")
            rows.append(row)
            continue
        if cur_f != 1.0:
            row["decision"], row["reason"] = "skip", "base_fraction 已有非默认值，不覆盖"
            bump("skip_already_set")
            rows.append(row)
            continue
        mw, mw_src = base_mw[sid]
        f = round(base_fraction(rule, mw), 4)
        row.update({
            "base_mw": f"{mw:g}", "n_base": rule["n_base"],
            "increment_mw": rule["increment_mw"], "base_fraction": f,
            "decision": "fill", "reason": f"{mw_src}; +{rule['increment_formula']}",
        })
        bump("fillable_variants")
        counts["fillable_components"] = counts.get(
            "fillable_components", 0) + n_comp
        rows.append(row)
    return rows, counts


def _summary(db: sqlite3.Connection, counts: dict[str, int]) -> None:
    total_v = db.execute("SELECT COUNT(*) FROM variant").fetchone()[0]
    total_c = db.execute("SELECT COUNT(*) FROM product_component").fetchone()[0]
    salt_c = db.execute(
        "SELECT COUNT(*) FROM product_component pc JOIN variant v"
        " ON v.variant_id = pc.variant_id WHERE v.salt <> ''").fetchone()[0]
    fill_v = counts.get("fillable_variants", 0)
    fill_c = counts.get("fillable_components", 0)

    def pct(a: int, b: int) -> str:
        return f"{100.0 * a / b:.2f}%" if b else "n/a"

    print("=== apply_salt_fractions 统计 ===")
    print(f"扫到的可折算 salt_code variant : {counts.get('scanned_variants', 0):,}")
    print(f"可填 variant / 组件            : {fill_v:,} / {fill_c:,}")
    print(f"  · 占含盐组件                 : {pct(fill_c, salt_c)}")
    print(f"  · 占全部组件                 : {pct(fill_c, total_c)}")
    print(f"strength_basis=unknown（只统计）: {counts.get('basis_unknown', 0):,} variant / "
          f"{counts.get('basis_unknown_components', 0):,} 组件")
    print(f"水合物待人工核对               : {counts.get('skip_hydrate', 0):,} variant / "
          f"{counts.get('skip_hydrate_components', 0):,} 组件")
    print(f"无碱基分子量                   : {counts.get('skip_no_base_mw', 0):,}")
    print(f"盐表未收录 / manual_review     : "
          f"{counts.get('skip_no_rule', 0):,} / {counts.get('skip_manual_review', 0):,}")
    print(f"已有非默认值（不覆盖）         : {counts.get('skip_already_set', 0):,}")
    print(f"variant 总数 / 组件总数        : {total_v:,} / {total_c:,}")


def _write_audit(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["variant_id", "substance_id", "salt", "salt_code", "kind",
            "strength_basis", "base_mw", "n_base", "increment_mw",
            "base_fraction", "n_components", "decision", "reason"]
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _write_backup(changes: list[tuple], backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = backup_dir / f"rollback_base_fraction_{stamp}.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["variant_id", "base_fraction_before", "base_fraction_after"])
        w.writerows(changes)
    (backup_dir / "rollback_base_fraction_latest.csv").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _latest_backup(backup_dir: Path) -> Path | None:
    files = sorted(backup_dir.glob("rollback_base_fraction_*.csv"))
    files = [p for p in files if not p.name.endswith("_latest.csv")]
    return files[-1] if files else None


def _run(args: argparse.Namespace, mode: str) -> int:
    rules = load_rules(args.csv)
    base_mw = load_base_mw(args.base_mw_csv)
    db = _connect(args.db, write=(mode != "dry"))
    try:
        if not has_salt_code_column(db):
            raise SystemExit(f"{args.db} 还没有 variant.salt_code 列："
                             "先跑 python db/init_db.py --db <path>，再跑 normalize_salts --apply")
        rows, counts = _scan(db, rules, base_mw, args.include_hydrate,
                             args.only_verified)
        _summary(db, counts)
        _write_audit(rows, args.out)
        print(f"候选审计 CSV                   : {args.out}")
        if mode != "apply":
            return 0
        changes = [(r["variant_id"], 1.0, r["base_fraction"])
                   for r in rows if r["decision"] == "fill"]
        if not changes:
            print("可写 0 行（strength_basis 未知或已填过），本次不写库。")
            return 0
        backup = _write_backup(changes, args.backup_dir)
        print(f"回滚备份                       : {backup}")
        with db:
            db.executemany(
                "UPDATE variant SET base_fraction=? WHERE variant_id=? AND base_fraction=1.0",
                [(after, vid) for vid, _, after in changes],
            )
        print(f"已写入 base_fraction：{len(changes):,} 行")
        return 0
    finally:
        db.close()


def cmd_rollback(args: argparse.Namespace) -> int:
    path = args.rollback_file or _latest_backup(args.backup_dir)
    if path is None:
        print(f"找不到备份 CSV（{args.backup_dir}），无法回滚。", file=sys.stderr)
        return 1
    with Path(path).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    db = _connect(args.db, write=True)
    try:
        current = dict(db.execute("SELECT variant_id, base_fraction FROM variant"))
        todo = []
        skipped = 0
        for r in rows:
            vid = r["variant_id"]
            cur = current.get(vid)
            after = float(r["base_fraction_after"])
            if cur is not None and abs(cur - after) < 1e-12:
                todo.append((float(r["base_fraction_before"]), vid))
            else:
                skipped += 1
        with db:
            db.executemany(
                "UPDATE variant SET base_fraction=? WHERE variant_id=?", todo)
        print("=== apply_salt_fractions --rollback ===")
        print(f"备份文件 : {path}")
        print(f"还原行数 : {len(todo):,}（跳过已变更 {skipped:,}）")
        return 0
    finally:
        db.close()


def cmd_verify(args: argparse.Namespace) -> int:
    db = _connect(args.db, write=False)
    try:
        if not has_salt_code_column(db):
            print(f"{args.db} 还没有 variant.salt_code 列：先跑 db/init_db.py",
                  file=sys.stderr)
            return 1
        print("=== apply_salt_fractions --verify ===")
        print(f"  base_fraction<>1.0          : "
              f"{db.execute('SELECT COUNT(*) FROM variant WHERE base_fraction<>1.0').fetchone()[0]:,}")
        print(f"  of which salt_code 非空     : "
              f"{db.execute('SELECT COUNT(*) FROM variant WHERE base_fraction<>1.0 AND salt_code<>\'\'').fetchone()[0]:,}")
        for basis, n in db.execute(
                "SELECT strength_basis, COUNT(*) FROM variant GROUP BY strength_basis"):
            print(f"  strength_basis {basis:16} {n:,}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只统计（默认）")
    mode.add_argument("--apply", action="store_true", help="事务写 base_fraction")
    mode.add_argument("--rollback", action="store_true", help="用备份 CSV 还原")
    mode.add_argument("--verify", action="store_true", help="打印库内分布")
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="盐表 CSV")
    ap.add_argument("--base-mw-csv", type=Path, default=None,
                    help="可选：覆盖内嵌 BASE_MW 的 CSV（substance_id,base_mw,source）")
    ap.add_argument("--out", type=Path, default=DEFAULT_AUDIT, help="候选审计 CSV")
    ap.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    ap.add_argument("--rollback-file", type=Path, default=None)
    ap.add_argument("--include-hydrate", action="store_true",
                    help="水合物也按 k·H2O 折算（默认跳过、待人工确认强度基准）")
    ap.add_argument("--only-verified", action="store_true",
                    help="只填盐表 status=verified 的 9 类盐（最保守）")
    ap.add_argument("--confirm-real-db", action="store_true")
    args = ap.parse_args(argv)

    action = "verify" if args.verify else ("rollback" if args.rollback
                                           else ("apply" if args.apply else "dry"))
    if action in ("apply", "rollback"):
        _guard_target(args.db, action, args.confirm_real_db)
    if not args.db.exists():
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 1
    if not args.csv.exists():
        print(f"盐表不存在：{args.csv}", file=sys.stderr)
        return 1
    if action == "verify":
        return cmd_verify(args)
    if action == "rollback":
        return cmd_rollback(args)
    return _run(args, action)


if __name__ == "__main__":
    raise SystemExit(main())
