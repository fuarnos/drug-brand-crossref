# -*- coding: utf-8 -*-
"""单位归一 v1：重量单位 → mg（task-16，DB 层，幂等 + Decimal 精确换算）。

范围
----
只动 `product_component.strength_value / strength_unit`：
    g → mg（×1000）
    kg → mg（×1,000,000）
    µg 及同义写法（ug / mcg / microgram(s) / μg / µg）→ mg（÷1000）
    ng → mg（÷1,000,000）
数值用 `decimal.Decimal` 换算（从 DB 的 REAL 取最短 repr 再换算），不引入浮点误差；
`strength_unit` 统一写成 `mg`。**不改产品身份**（不动 product/批文/厂家/成分映射）。

不动（第二批，计入 skip 清单）
------------------------------
IU / unit / vg / mEq / 百分比 / 体积（mL、L）等非重量单位；复合单位（mg/mL、g/L、
g/vial、mcg/dose…）；复方比例、范围值、无单位、非正值、换算后 > --max-mg（默认
100,000 mg）的异常值 —— 全部跳过并计数，不猜。

用法
----
    python etl/normalize_units_mass.py                      # dry-run（默认只读）
    python etl/normalize_units_mass.py --db <副本> --dry-run
    python etl/normalize_units_mass.py --apply --db <副本>
    python etl/normalize_units_mass.py --apply --allow-real --db data/drugs.db \
        --manifest .tmp/unit-norm-mass/manifest.json
    python etl/normalize_units_mass.py --rollback --allow-real --db data/drugs.db \
        --manifest .tmp/unit-norm-mass/manifest.json

dry-run 只读（`mode=ro`）；apply 才写，且默认拒绝真实库（需 `--allow-real`）。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "drugs.db"
WORK = ROOT / ".tmp" / "unit-norm-mass"
DEFAULT_MANIFEST = WORK / "manifest.json"
DEFAULT_AUDIT = WORK / "audit.csv"
SCRIPT_VERSION = "2026-10-30"
MAX_MG_DEFAULT = 100_000

# 单位 → 换算到 mg 的因子（key 为 strip().lower() 后的写法）
FACTORS: dict[str, Decimal] = {
    "g": Decimal(1000),
    "kg": Decimal(1_000_000),
    "mcg": Decimal("0.001"),
    "ug": Decimal("0.001"),
    "microgram": Decimal("0.001"),
    "micrograms": Decimal("0.001"),
    "μg": Decimal("0.001"),
    "µg": Decimal("0.001"),
    "ng": Decimal("0.000001"),
}
MASS_FAMILY = set(FACTORS) | {"mg"}
RANGE_RE = re.compile(r"\d\s*[-–~]\s*\d")

# 第二批（只计数，不动）：常见非重量 / 复合单位归类
NON_MASS_NOTE = {
    "iu": "IU（国际单位）→ 第二批", "IU": "IU（国际单位）→ 第二批",
    "u": "U/单位 → 第二批", "unit": "U/单位 → 第二批", "units": "U/单位 → 第二批",
    "万iu": "万IU → 第二批", "meq": "mEq → 第二批", "mmol": "mmol → 第二批",
    "%": "百分比 → 第二批", "%w/w": "百分比 → 第二批", "%w/v": "百分比 → 第二批",
    "ml": "体积 mL → 第二批", "l": "体积 L → 第二批", "mcl": "体积 µL → 第二批",
    "ul": "体积 µL → 第二批",
}


def connect(db: Path, write: bool) -> sqlite3.Connection:
    if write:
        return sqlite3.connect(db, timeout=180)
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=180)


def guard_real(db: Path, allow_real: bool, action: str) -> None:
    if db.resolve() == DEFAULT_DB.resolve() and not allow_real:
        raise SystemExit(f"拒绝{action}真实库 {DEFAULT_DB}：先副本 dry-run；Lead 批准后加 --allow-real。")


def classify(unit: str | None, value: float | None, max_mg: Decimal) -> tuple[str, Decimal | None]:
    """返回 (bucket, factor)。bucket: convert / already_mg / skip:<reason>。"""
    u = (unit or "").strip()
    if not u:
        return ("skip:unit_missing" if value is not None else "skip:no_unit_no_value"), None
    key = u.lower()
    if value is None:
        return "skip:value_missing", None
    if key == "mg":
        return "already_mg", None
    if RANGE_RE.search(u):
        return "skip:range_text", None
    if "/" in u or " per " in f" {key} " or key.endswith("per"):
        return "skip:compound_unit", None
    if key not in FACTORS:
        return ("skip:not_mass" if key not in MASS_FAMILY else "skip:unknown"), None
    if value <= 0:
        return "skip:non_positive", None
    factor = FACTORS[key]
    converted = Decimal(repr(float(value))) * factor
    if converted > max_mg:
        return "skip:abnormal_converted", None
    return "convert", factor


def scan(db: sqlite3.Connection, max_mg: Decimal) -> dict:
    """只读扫描：返回 changes / skip 明细 / 单位前后计数。"""
    rows = list(db.execute(
        "SELECT product_id, ord, strength_value, strength_unit FROM product_component"
        " ORDER BY product_id, ord"))
    before = Counter((r[3] or "<NULL>") for r in rows)
    changes: list[tuple] = []
    skips: list[tuple] = []
    buckets: Counter = Counter()
    for pid, ord_, val, unit in rows:
        bucket, factor = classify(unit, val, max_mg)
        buckets[bucket] += 1
        if bucket == "convert":
            dec = Decimal(repr(float(val))) * factor
            new_val = float(dec)
            changes.append((pid, ord_, val, unit, new_val))
        elif bucket.startswith("skip:"):
            skips.append((pid, ord_, val, unit, bucket.split(":", 1)[1]))
    after = Counter(before)
    for _pid, _o, _v, unit, _n in changes:
        after[unit] -= 1
        after["mg"] += 1
    return {"rows": len(rows), "changes": changes, "skips": skips,
            "buckets": dict(buckets), "before": dict(before), "after": dict(after)}


def write_audit(path: Path, plan: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["kind", "product_id", "ord", "old_value", "old_unit", "new_value", "reason"])
        for pid, ord_, val, unit, new in plan["changes"]:
            w.writerow(["change", pid, ord_, val, unit, new, "mass_to_mg"])
        for pid, ord_, val, unit, reason in plan["skips"]:
            w.writerow(["skip", pid, ord_, val, unit, "", reason])


def print_plan(plan: dict, max_mg: Decimal) -> None:
    b = plan["buckets"]
    conv = b.get("convert", 0)
    print("=== 单位归一 v1（重量 → mg）dry-run ===")
    print(f"  扫描 components {plan['rows']:,}；可换算 {conv:,}；已 mg {b.get('already_mg', 0):,}"
          f"；跳过 {sum(v for k, v in b.items() if k.startswith('skip:')):,}")
    print(f"  换算明细：{ {k: v for k, v in plan['buckets'].items() if k in ('convert', 'already_mg')} }")
    print("  跳过原因：")
    for k, v in sorted(b.items()):
        if k.startswith("skip:"):
            print(f"    {k.split(':', 1)[1]:<22} {v:>7,}")
    print("  改动前单位 Top10：", dict(Counter(plan["before"]).most_common(10)))
    print("  改动后单位 Top10：", dict(Counter(plan["after"]).most_common(10)))
    print(f"  阈值 --max-mg = {max_mg}（换算后超过即跳过，不猜）")


def cmd_dry_run(args) -> int:
    db = connect(args.db, write=False)
    db.row_factory = sqlite3.Row
    try:
        plan = scan(db, Decimal(args.max_mg))
    finally:
        db.close()
    print_plan(plan, Decimal(args.max_mg))
    out = Path(args.audit) if args.audit else DEFAULT_AUDIT
    write_audit(out, plan)
    print(f"  明细 CSV：{out}")
    print("  样例（前 10 条换算）：")
    for pid, ord_, val, unit, new in plan["changes"][:10]:
        print(f"    {pid} ord={ord_}: {val} {unit} → {new} mg")
    return 0


def cmd_apply(args) -> int:
    guard_real(args.db, args.allow_real, "写")
    db = connect(args.db, write=True)
    db.row_factory = sqlite3.Row
    max_mg = Decimal(args.max_mg)
    t0 = time.perf_counter()
    try:
        plan = scan(db, max_mg)
        if not plan["changes"]:
            print("没有可换算的行（已归一化 / 幂等）。")
            return 0
        run_id = f"unit-mass-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        db.execute("BEGIN IMMEDIATE")
        done = 0
        for pid, ord_, val, unit, new_val in plan["changes"]:
            cur = db.execute(
                "UPDATE product_component SET strength_value=?, strength_unit='mg'"
                " WHERE product_id=? AND ord=? AND strength_value=? AND strength_unit=?",
                (new_val, pid, ord_, val, unit))
            done += cur.rowcount
        db.commit()
        manifest = {
            "script": Path(__file__).name, "version": SCRIPT_VERSION, "run_id": run_id,
            "db": str(Path(args.db).resolve()), "max_mg": str(max_mg),
            "factor_map": {k: str(v) for k, v in FACTORS.items()},
            "counts": {"scanned": plan["rows"], "converted": done,
                       "buckets": plan["buckets"]},
            "before": plan["before"], "after": plan["after"],
            "changes": [[pid, ord_, val, unit, new_val]
                        for pid, ord_, val, unit, new_val in plan["changes"]],
        }
        mpath = Path(args.manifest) if args.manifest else DEFAULT_MANIFEST
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        out = Path(args.audit) if args.audit else DEFAULT_AUDIT
        write_audit(out, plan)
        print(f"写入 {done:,} 行（事务 {time.perf_counter() - t0:.2f}s）；run_id={run_id}")
        print(f"撤销清单：{mpath}（{mpath.stat().st_size / 1024:.0f} KB）；明细 CSV：{out}")
        return 0
    finally:
        db.close()


def cmd_rollback(args) -> int:
    guard_real(args.db, args.allow_real, "回滚")
    mpath = Path(args.manifest) if args.manifest else DEFAULT_MANIFEST
    if not mpath.exists():
        raise SystemExit(f"找不到撤销清单 {mpath}")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    db = connect(args.db, write=True)
    t0 = time.perf_counter()
    try:
        db.execute("BEGIN IMMEDIATE")
        restored = 0
        for pid, ord_, old_val, old_unit, new_val in manifest["changes"]:
            cur = db.execute(
                "UPDATE product_component SET strength_value=?, strength_unit=?"
                " WHERE product_id=? AND ord=? AND strength_value=? AND strength_unit='mg'",
                (float(old_val), old_unit, pid, ord_, float(new_val)))
            restored += cur.rowcount
        db.commit()
        print(f"回滚 {restored:,} 行（事务 {time.perf_counter() - t0:.2f}s）"
              f"；清单 run_id={manifest.get('run_id')}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="单位归一 v1：重量单位 → mg（幂等 / 可回滚）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="目标 DB（默认 data/drugs.db）")
    ap.add_argument("--dry-run", action="store_true", help="只读统计（默认行为）")
    ap.add_argument("--apply", action="store_true", help="写入（真实库需 --allow-real）")
    ap.add_argument("--rollback", action="store_true", help="按撤销清单回滚")
    ap.add_argument("--allow-real", action="store_true", help="允许写 data/drugs.db")
    ap.add_argument("--max-mg", default=str(MAX_MG_DEFAULT),
                    help="换算后超过该 mg 值视为异常并跳过（默认 100000）")
    ap.add_argument("--manifest", default=None, help="撤销清单路径（默认 .tmp/unit-norm-mass/manifest.json）")
    ap.add_argument("--audit", default=None, help="明细 CSV 路径（默认 .tmp/unit-norm-mass/audit.csv）")
    args = ap.parse_args(argv)
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
