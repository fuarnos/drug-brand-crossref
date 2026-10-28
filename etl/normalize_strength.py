# -*- coding: utf-8 -*-
"""规格单位归一化 + 液体浓度/异常规格标记（task-135）。

范围
----
只处理 `product_component` 单位的**文本规范化**，不改数值（不做 g↔mg 换算）：
- `strength_unit` / `per_volume_unit`：iu→IU、ug/μg/µg/microgram→mcg、unit/units/u→unit、
  ml→mL、l→L、meq→mEq、umol→µmol、ml/vial 等空格/大小写/同义变体；
- 生物制品单位（vg/vp/pfu/ffu/cfu/genome copies…）统一大小写并单独标记；
- 识别不了的保留原文并输出 `unrecognized` 清单，不猜。

标记（flags，默认只读；`--flags` 导出 CSV；`--mark-notes` 才写 DB）
---------------------------------------------------------------
- `liquid_no_concentration`：液体剂型、有 strength_value 但 per_volume_value 为空
  （页面应展示「总量，浓度未提供」，不参与同规格比较）；
- `liquid_no_strength_no_concentration`：液体、strength 与 per_volume 都空；
- `invalid_strength`：strength_value <= 0（建议展示「源值异常」，不猜）；
- `extreme_strength`：strength_value >= 100000（科学计数+单位说明；多为 vg/genome copies）；
- `trade_name_contains_dose`：trade 名混入 mg/tablet/片/胶囊等（只建议 build 拆分，不改原文）。
`--mark-notes` 会把 `[strength-norm:<reason>]` 追加到 product.note（幂等、可回滚）。

安全
----
- 默认 `--dry-run`，只读 DB；
- `--apply` 默认拒绝真实库（需 `--allow-real`），单事务 + 撤销清单（旧值/new值）；
- `--rollback` 只恢复「当前值 == 新生值」的行，被别的改动动过的行记冲突不覆盖；幂等。

用法
----
    python etl/normalize_strength.py                        # dry-run
    python etl/normalize_strength.py --flags .tmp/strength-norm/flags.csv
    python etl/normalize_strength.py --db .tmp/strength-norm/test.db --apply
    python etl/normalize_strength.py --db .tmp/strength-norm/test.db --rollback
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "drugs.db"
WORK = ROOT / ".tmp" / "strength-norm"
DEFAULT_MANIFEST = WORK / "normalize_manifest.json"

# 明确变体 → 规范单位（键为原文精确值；先做空白归一）
UNIT_MAP = {
    "ml": "mL", "ML": "mL", "mL": "mL", "l": "L", "L": "L",
    "ml/ml": "mL/mL", "ml/ampoule": "mL/ampoule", "microlitres/ml": "µL/mL",
    "ug": "mcg", "μg": "mcg", "µg": "mcg", "microgram": "mcg", "micrograms": "mcg",
    "ug/ml": "mcg/mL", "mcg/ml": "mcg/mL", "mcg /g": "mcg/g",
    "iu": "IU", "IU": "IU", "iu/ml": "IU/mL", "iu/g": "IU/g", "iu/vial": "IU/vial",
    "iu/ampoule": "IU/ampoule", "万iu": "万IU", "kiu": "kIU", "miu": "MIU",
    "unit": "unit", "units": "unit", "u": "unit", "U": "unit",
    "u/ml": "unit/mL", "units/ml": "unit/mL", "u/ ml": "unit/mL",
    "u/g": "unit/g", "u/vial": "unit/vial", "million units": "million unit",
    "du": "DU", "tu": "TU", "lf": "LF", "b": "B",
    "meq": "mEq", "mEq/ml": "mEq/mL", "mmol/ml": "mmol/mL", "nmol/ml": "nmol/mL",
    "umol": "µmol", "mcmol": "µmol",
    "% w/v": "%w/v", "%w/v": "%w/v", "%w/w": "%w/w",
    "mci": "mCi", "uci": "µCi", "ci": "Ci", "mcci": "mCi",
    "mbq/ml": "MBq/mL", "gbq/ml": "GBq/mL", "kbq/ml": "kBq/mL",
    "ccid50": "CCID50", "log10 tcid50": "log10 TCID50", "log10 pfu": "log10 PFU",
    "pfu": "PFU", "ffu": "FFU", "cfu": "CFU", "vg": "VG", "vp": "VP", "bvg": "BVG",
    "genome copies": "genome copies", "cells": "cells", "ppm": "ppm",
    "mgvial": "mg/vial", "mgi/ml": "mg/mL", "mg/ vial": "mg/vial",
    "mg/ ml": "mg/mL", "mg / ml": "mg/mL", "mg /vial": "mg/vial",
    "g/ vial": "g/vial", "g / vial": "g/vial", "g /ml": "g/mL",
    "%": "%", "ul": "µL", "mcl": "µL", "gm/vial": "g/vial",
    "mg/tab": "mg/tablet", "units/vial": "unit/vial", "mu": "mU",
}
# 形如 "X/Y" 的统一大小写规则（X,Y 已知时）
DENOM = {"ml": "mL", "l": "L", "vial": "vial", "ampoule": "ampoule", "sachet": "sachet",
         "tablet": "tablet", "capsule": "capsule", "caplet": "caplet", "patch": "patch",
         "plaster": "plaster", "syringe": "syringe", "dose": "dose", "actuation": "actuation",
         "inhalation": "inhalation", "spray": "spray", "sheet": "sheet", "bottle": "bottle",
         "packet": "packet", "unit": "unit", "g": "g", "mg": "mg", "mcg": "mcg"}
NUMER = {"mg": "mg", "g": "g", "mcg": "mcg", "kg": "kg", "iu": "IU", "unit": "unit",
         "u": "unit", "ml": "mL", "l": "L", "meq": "mEq", "mmol": "mmol",
         "umol": "µmol", "nmol": "nmol", "mci": "mCi", "mbq": "MBq", "gbq": "GBq",
         "kbq": "kBq", "ci": "Ci"}
UNRECOGNIZED_KEEP = {"nil", "gal", "mm", "m", "cm", "wk", "min", "dose", "kg", "ppm",
                     "genome copies", "cells"}
BIOLOGIC = {"VG", "VP", "PFU", "FFU", "CFU", "BVG", "CCID50", "log10 TCID50",
            "log10 PFU", "kIU", "MIU", "LF", "DU", "TU", "B", "mCi", "µCi", "Ci",
            "MBq/mL", "GBq/mL", "kBq/mL"}
TRADE_DOSE_RE = re.compile(
    r"(?:\d+(?:[.,]\d+)?\s*(?:mg|g|mcg|µg|ug|iu|ml)\b|tablet|capsule|"
    r"片|胶囊|顆|毫克|公絲)", re.I)


def norm_unit(raw: str | None) -> tuple[str | None, str]:
    """返回 (规范单位, rule)；rule = exact/denom/unrecognized/empty/keep。"""
    if raw is None:
        return None, "empty"
    s = re.sub(r"\s+", " ", str(raw)).strip()
    if not s:
        return None, "empty"
    if s in UNIT_MAP:
        return UNIT_MAP[s], "exact"
    if s in UNRECOGNIZED_KEEP:
        return s, "keep"
    if "/" in s:
        num, den = s.split("/", 1)
        num, den = num.strip(), den.strip()
        nn, nd = NUMER.get(num.lower()), DENOM.get(den.lower())
        if nn and nd:
            return f"{nn}/{nd}", "denom"
    # 单个词大小写归一
    if s.lower() in NUMER:
        return NUMER[s.lower()], "single"
    return s, "unrecognized"


def _connect(db: Path, write: bool) -> sqlite3.Connection:
    if write:
        db_ = sqlite3.connect(db, timeout=120)
        db_.execute("PRAGMA foreign_keys=ON")
        return db_
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=120)


def _guard(db: Path, allow_real: bool) -> None:
    try:
        is_real = db.resolve() == DEFAULT_DB.resolve()
    except OSError:
        is_real = False
    if is_real and not allow_real:
        raise SystemExit(f"拒绝写真实库 {db}：先副本验证；Lead 批准窗口加 --allow-real。")


def plan(db: sqlite3.Connection) -> dict:
    """扫描单位变更 + 生成 flags（只读，不写库）。"""
    changes = []          # (product_id, ord, field, old, new, rule)
    rules = Counter()
    unrec = Counter()
    for r in db.execute(
            "SELECT product_id,ord,strength_unit,per_volume_unit FROM product_component"):
        for field, idx in (("strength_unit", 2), ("per_volume_unit", 3)):
            old = r[idx]
            new, rule = norm_unit(old)
            rules[rule] += 1
            if rule == "unrecognized":
                unrec[old] += 1
            if old is not None and new != old:
                changes.append((r[0], r[1], field, old, new, rule))
    flags = []
    for r in db.execute("""
            SELECT pc.product_id, pc.ord, pc.strength_value, pc.strength_unit,
                   pc.per_volume_value, p.form_base, p.country
            FROM product_component pc JOIN product p ON p.product_id=pc.product_id"""):
        pid, ord_, sv, su, pv, form, country = r
        if form == "liquid" and sv is not None and pv is None:
            flags.append((pid, ord_, "liquid_no_concentration", f"{sv} {su or ''}".strip()))
        elif form == "liquid" and sv is None and pv is None:
            flags.append((pid, ord_, "liquid_no_strength_no_concentration", ""))
        if sv is not None and sv <= 0:
            flags.append((pid, ord_, "invalid_strength", str(sv)))
        if sv is not None and sv >= 100000:
            flags.append((pid, ord_, "extreme_strength", f"{sv} {su or ''}".strip()))
    trade_products = set()
    for r in db.execute("""
            SELECT DISTINCT p.product_id, nv.raw FROM product p
            JOIN product_name pn ON pn.product_id=p.product_id AND pn.name_type='trade'
            JOIN name_variant nv ON nv.key_id=pn.key_id"""):
        if TRADE_DOSE_RE.search(r[1] or ""):
            trade_products.add(r[0])
    for pid in trade_products:
        flags.append((pid, None, "trade_name_contains_dose", ""))
    return {"changes": changes, "rules": dict(rules), "unrecognized": dict(unrec),
            "flags": flags, "trade_products": len(trade_products)}


def _write_flags(flags: list[tuple], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["product_id", "ord", "reason", "detail"])
        w.writerows(flags)


def cmd_dry_run(args) -> int:
    db = _connect(args.db, write=False)
    try:
        p = plan(db)
        counts = Counter(f[2] for f in p["flags"])
        rows_by_field = Counter(c[2] for c in p["changes"])
        before = defaultdict(Counter)
        for pid, ord_, field, old, new, rule in p["changes"]:
            before[field][old] += 1
        print("=== normalize_strength dry-run ===")
        print(f"DB: {args.db}")
        print(f"单位变更行: {len(p['changes'])}（{dict(rows_by_field)}）")
        print(f"规则: {p['rules']}")
        print("尚未识别单位（保留原文）:", json.dumps(p["unrecognized"], ensure_ascii=False))
        print("变更 top:", [[old, n] for old, n in
                            Counter((c[3], c[4]) for c in p["changes"]).most_common(20)])
        print("flags:", dict(counts))
        print(f"液体无浓度产品估计: {len({f[0] for f in p['flags'] if f[2]=='liquid_no_concentration'})}")
        if args.flags:
            _write_flags(p["flags"], args.flags)
            print("flags CSV:", args.flags)
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / "dryrun.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        db.close()
    return 0


def cmd_apply(args) -> int:
    _guard(args.db, args.allow_real)
    if not args.db.exists():
        raise SystemExit(f"DB 不存在：{args.db}")
    db = _connect(args.db, write=True)
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    prev = None
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prev = None
    try:
        p = plan(db)
        changes = p["changes"]
        flags = p["flags"]
        notes: list[tuple[str, str, str]] = []   # (product_id, old_note, new_note)
        if args.mark_notes:
            by_pid = defaultdict(set)
            for pid, ord_, reason, detail in flags:
                by_pid[pid].add(reason)
            for pid in sorted(by_pid):
                row = db.execute("SELECT note FROM product WHERE product_id=?", (pid,)).fetchone()
                old = row[0] if row else ""
                tags = [f"[strength-norm:{r}]" for r in sorted(by_pid[pid])]
                new = (old + " " + " ".join(tags)).strip() if old else " ".join(tags)
                if new != old:
                    notes.append((pid, old or "", new))
        t0 = datetime.now(timezone.utc)
        db.execute("BEGIN IMMEDIATE")
        for pid, ord_, field, old, new, rule in changes:
            cur = db.execute(f"UPDATE product_component SET {field}=? WHERE product_id=? AND ord=?",
                             (new, pid, ord_))
            if cur.rowcount != 1:
                raise RuntimeError(f"更新行数异常: {pid} {ord_} {field}")
        if args.mark_notes:
            for pid, old, new in notes:
                db.execute("UPDATE product SET note=? WHERE product_id=?", (new, pid))
        db.commit()
        elapsed = round((datetime.now(timezone.utc) - t0).total_seconds(), 2)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    old_keys = {tuple(x["created"]) for x in (prev or {}).get("changes", [])} if prev else set()
    if prev and prev.get("db") != str(args.db):
        prev = None           # 撤销清单属于别的 DB，不合并
    merged_changes = {tuple(x["created"]): x for x in (prev or {}).get("changes", [])}
    for pid, ord_, field, old, new, rule in changes:
        key = (pid, ord_, field)
        if key not in merged_changes:       # 保留首次 apply 的 old 值
            merged_changes[key] = {"created": [pid, ord_, field], "old": old,
                                   "new": new, "rule": rule}
    merged_notes = {x["product_id"]: x for x in (prev or {}).get("notes", [])}
    for pid, old, new in notes:
        if pid not in merged_notes:
            merged_notes[pid] = {"product_id": pid, "old": old, "new": new}
    manifest = {
        "tool": "etl/normalize_strength.py", "db": str(args.db),
        "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "changes": list(merged_changes.values()),
        "notes": list(merged_notes.values()),
        "trade_products": p["trade_products"],
        "flags": [{"product_id": f[0], "ord": f[1], "reason": f[2], "detail": f[3]}
                  for f in flags[:200000]],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    flags_path = ROOT / ".tmp" / "strength-norm" / "flags.csv"
    _write_flags(flags, flags_path)
    (WORK / "apply_stats.json").write_text(json.dumps({
        "unit_changes": len(changes), "note_changes": len(notes),
        "rules": p["rules"], "flags": dict(Counter(f[2] for f in flags)),
        "trade_products": p["trade_products"], "elapsed_s": elapsed,
        "db": str(args.db)}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"=== 已写入 {args.db} ===")
    print(f"单位变更 {len(changes)} 行；note 标记 {len(notes)} 产品；"
          f"flags: {dict(Counter(f[2] for f in flags))}；耗时 {elapsed}s")
    print("撤销清单:", manifest_path)
    return 0


def cmd_rollback(args) -> int:
    _guard(args.db, args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单：{manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = _connect(args.db, write=True)
    restored = conflicts = 0
    notes_restored = notes_conflict = 0
    try:
        db.execute("BEGIN IMMEDIATE")
        for item in data.get("changes", []):
            pid, ord_, field = item["created"]
            old, new = item["old"], item["new"]
            cur = db.execute(f"SELECT {field} FROM product_component WHERE product_id=? AND ord=?",
                             (pid, ord_)).fetchone()
            if cur is None or cur[0] != new:
                conflicts += 1
                continue
            db.execute(f"UPDATE product_component SET {field}=? WHERE product_id=? AND ord=?",
                       (old, pid, ord_))
            restored += 1
        for item in data.get("notes", []):
            pid, old, new = item["product_id"], item["old"], item["new"]
            cur = db.execute("SELECT note FROM product WHERE product_id=?", (pid,)).fetchone()
            if cur is None or (cur[0] or "") != new:
                notes_conflict += 1
                continue
            db.execute("UPDATE product SET note=? WHERE product_id=?", (old or None, pid))
            notes_restored += 1
        db.commit()
    finally:
        db.close()
    print(f"=== 回滚完成 === 单位行 {restored}（冲突 {conflicts}）；"
          f"note {notes_restored}（冲突 {notes_conflict}）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="规格单位归一化 + 液体/异常规格标记（task-135）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只读统计（默认）")
    mode.add_argument("--apply", action="store_true", help="写入（默认限副本）")
    mode.add_argument("--rollback", action="store_true", help="按撤销清单回滚")
    ap.add_argument("--allow-real", action="store_true")
    ap.add_argument("--flags", type=Path, default=None, help="导出 flags CSV（dry-run）")
    ap.add_argument("--mark-notes", action="store_true", help="apply 时给 flags 产品 note 追加标记")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = ap.parse_args(argv)
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
