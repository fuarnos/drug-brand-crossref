# -*- coding: utf-8 -*-
"""单位归一 v2（体积 + per_volume 质量，DB 层，Decimal + 幂等 + 撤销清单）— task-3 第二批。

范围（Lead 2026-10-30 批准）
--------------------------
只做**数值可安全换算**的部分（文本统一由 `etl/normalize_strength.py` 另跑）：

| 字段 | 原单位 | 目标 | 因子（对 value） |
|---|---|---|---|
| strength_unit | l / L | mL | ×1000 |
| per_volume_unit | l / L | mL | ×1000 |
| per_volume_unit | ul / mcl / µl / μl | mL | ×0.001 |
| per_volume_unit | g | mg | ×1000 |
| per_volume_unit | kg | mg | ×1,000,000 |

**不动**：IU / U / unit / vg / mEq / % 等非质量非体积单位的数值（无换算因子，只做文本统一）；
strength 里残留的 `g`/`kg`（task-16 判定的 >100,000 mg 异常值，不重算）。

换算用 `decimal.Decimal`（从 REAL 的最短 repr 起算），不引入浮点误差；写回 REAL。
`per_volume` 是「每 X 单位含多少」的分母量，换算时同步缩放分母值，保持物理比例不变。

用法
----
    python etl/normalize_units_batch2.py                 # dry-run（默认只读）
    python etl/normalize_units_batch2.py --db <副本> --apply
    python etl/normalize_units_batch2.py --apply --allow-real --db data/drugs.db \
        --manifest .tmp/unit-norm-mass/manifest_batch2.json
    python etl/normalize_units_batch2.py --rollback --allow-real --manifest <上面文件>
"""

from __future__ import annotations

import argparse
import csv
import json
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
DEFAULT_MANIFEST = WORK / "manifest_batch2.json"
DEFAULT_AUDIT = WORK / "audit_batch2.csv"
SCRIPT_VERSION = "2026-10-30"

# (字段, 单位小写) -> (因子, 目标单位)
CONVERT = {
    ("strength_unit", "l"): (Decimal(1000), "mL"),
    ("per_volume_unit", "l"): (Decimal(1000), "mL"),
    ("per_volume_unit", "ul"): (Decimal("0.001"), "mL"),
    ("per_volume_unit", "mcl"): (Decimal("0.001"), "mL"),
    ("per_volume_unit", "µl"): (Decimal("0.001"), "mL"),
    ("per_volume_unit", "μl"): (Decimal("0.001"), "mL"),
    ("per_volume_unit", "g"): (Decimal(1000), "mg"),
    ("per_volume_unit", "kg"): (Decimal(1_000_000), "mg"),
}
# 只用于统计「这批里还有什么没做」的候选家族（不做数值换算）
UNTOUCHED_NUMERIC = {"iu", "u", "unit", "units", "meq", "vg", "vp", "%", "%w/w", "%w/v",
                     "万iu", "mci", "uci", "ci", "kiu", "miu", "pfu", "ffu", "cfu"}


def connect(db: Path, write: bool) -> sqlite3.Connection:
    if write:
        return sqlite3.connect(db, timeout=180)
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=180)


def guard_real(db: Path, allow_real: bool, action: str) -> None:
    if db.resolve() == DEFAULT_DB.resolve() and not allow_real:
        raise SystemExit(f"拒绝{action}真实库 {DEFAULT_DB}：先副本 dry-run；Lead 批准后加 --allow-real。")


def scan(db: sqlite3.Connection) -> dict:
    rows = list(db.execute(
        "SELECT product_id, ord, strength_value, strength_unit, per_volume_value, per_volume_unit"
        " FROM product_component ORDER BY product_id, ord"))
    changes: list[tuple] = []
    skips: list[tuple] = []
    families: Counter = Counter()
    for pid, ord_, sv, su, pv, pu in rows:
        for field, unit, val in (("strength_unit", su, sv), ("per_volume_unit", pu, pv)):
            key = (unit or "").strip().lower()
            if not key:
                continue
            families[f"{field}:{key}"] += 1
            spec = CONVERT.get((field, key))
            if not spec:
                continue
            factor, target = spec
            if val is None:
                skips.append((pid, ord_, field, None, unit, "value_missing"))
                continue
            if val <= 0:
                skips.append((pid, ord_, field, val, unit, "non_positive"))
                continue
            dec = Decimal(repr(float(val))) * factor
            changes.append((pid, ord_, field, val, unit, float(dec), target))
    return {"rows": len(rows), "changes": changes, "skips": skips,
            "families": {k: v for k, v in families.items() if k.split(":", 1)[1] in
                         {u for (_f, u) in CONVERT} | UNTOUCHED_NUMERIC}}


def write_audit(path: Path, plan: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["kind", "product_id", "ord", "field", "old_value", "old_unit",
                    "new_value", "new_unit", "reason"])
        for pid, ord_, field, val, unit, new, target in plan["changes"]:
            w.writerow(["change", pid, ord_, field, val, unit, new, target, "numeric_convert"])
        for pid, ord_, field, val, unit, reason in plan["skips"]:
            w.writerow(["skip", pid, ord_, field, val, unit, "", "", reason])


def print_plan(plan: dict) -> None:
    by_field = Counter((c[2], c[4], c[6]) for c in plan["changes"])
    print("=== 单位归一 v2（体积 + per_volume 质量）dry-run ===")
    print(f"  扫描 components {plan['rows']:,}；可换算 {len(plan['changes']):,}"
          f"；跳过 {len(plan['skips']):,}")
    for (field, old, new), n in sorted(by_field.items(), key=lambda kv: -kv[1]):
        print(f"    {field:<18} {old:>4} → {new:<3} {n:>7,} 行")
    if plan["skips"]:
        print("  跳过原因：", dict(Counter(s[5] for s in plan["skips"])))
    print("  候选家族剩余（含不动单位，供第二批文本阶段）：")
    for k, v in sorted(plan["families"].items(), key=lambda kv: -kv[1])[:14]:
        print(f"    {k:<34} {v:>7,}")


def cmd_dry_run(args) -> int:
    db = connect(args.db, write=False)
    try:
        plan = scan(db)
    finally:
        db.close()
    print_plan(plan)
    out = Path(args.audit) if args.audit else DEFAULT_AUDIT
    write_audit(out, plan)
    print(f"  明细 CSV：{out}")
    for pid, ord_, field, val, unit, new, target in plan["changes"][:6]:
        print(f"    样例 {pid} ord={ord_} {field}: {val} {unit} → {new} {target}")
    return 0


def cmd_apply(args) -> int:
    guard_real(args.db, args.allow_real, "写")
    db = connect(args.db, write=True)
    t0 = time.perf_counter()
    try:
        plan = scan(db)
        if not plan["changes"]:
            print("没有可换算的行（已归一化 / 幂等）。")
            return 0
        run_id = f"unit-b2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        db.execute("BEGIN IMMEDIATE")
        done = 0
        for pid, ord_, field, val, unit, new, target in plan["changes"]:
            col_val, col_unit = (("strength_value", "strength_unit") if field == "strength_unit"
                                 else ("per_volume_value", "per_volume_unit"))
            cur = db.execute(
                f"UPDATE product_component SET {col_val}=?, {col_unit}=?"
                f" WHERE product_id=? AND ord=? AND {col_val}=? AND {col_unit}=?",
                (new, target, pid, ord_, val, unit))
            done += cur.rowcount
        db.commit()
        manifest = {
            "script": Path(__file__).name, "version": SCRIPT_VERSION, "run_id": run_id,
            "db": str(Path(args.db).resolve()),
            "factors": {f"{f}:{u}": [str(fac), t] for (f, u), (fac, t) in CONVERT.items()},
            "counts": {"scanned": plan["rows"], "converted": done,
                       "by_field": {f"{f}:{o}->{n}": c for (f, o, n), c in
                                    Counter((c[2], c[4], c[6]) for c in plan["changes"]).items()},
                       "skips": dict(Counter(s[5] for s in plan["skips"]))},
            "changes": [list(c) for c in plan["changes"]],
        }
        mpath = Path(args.manifest) if args.manifest else DEFAULT_MANIFEST
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        out = Path(args.audit) if args.audit else DEFAULT_AUDIT
        write_audit(out, plan)
        print(f"写入 {done:,} 行（事务 {time.perf_counter() - t0:.2f}s）；run_id={run_id}")
        print(f"撤销清单：{mpath}（{mpath.stat().st_size / 1024:.0f} KB）；明细：{out}")
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
        for pid, ord_, field, old_val, old_unit, new_val, new_unit in manifest["changes"]:
            col_val, col_unit = (("strength_value", "strength_unit") if field == "strength_unit"
                                 else ("per_volume_value", "per_volume_unit"))
            cur = db.execute(
                f"UPDATE product_component SET {col_val}=?, {col_unit}=?"
                f" WHERE product_id=? AND ord=? AND {col_val}=? AND {col_unit}=?",
                (float(old_val), old_unit, pid, ord_, float(new_val), new_unit))
            restored += cur.rowcount
        db.commit()
        print(f"回滚 {restored:,} 行（事务 {time.perf_counter() - t0:.2f}s）")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="单位归一 v2：体积 L/µL→mL、per_volume g/kg→mg（幂等可回滚）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true", help="只读统计（默认）")
    ap.add_argument("--apply", action="store_true", help="写入（真实库需 --allow-real）")
    ap.add_argument("--rollback", action="store_true", help="按撤销清单回滚")
    ap.add_argument("--allow-real", action="store_true", help="允许写 data/drugs.db")
    ap.add_argument("--manifest", default=None, help="撤销清单（默认 .tmp/unit-norm-mass/manifest_batch2.json）")
    ap.add_argument("--audit", default=None, help="明细 CSV（默认 .tmp/unit-norm-mass/audit_batch2.csv）")
    args = ap.parse_args(argv)
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
