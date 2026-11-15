# -*- coding: utf-8 -*-
"""给药途径（route）回填：按 `data/sources/route_rules_20261115.csv` 派生，只填空值。

背景（`reports/2026-11-15-m1-window-dryrun.md` §C）：全库 `product.route` 空 245,480 行
（49.6%），规则表能填 89.2%。本脚本是该规则的落库实现，口径与 dry-run 一致：

  1. 只更新 `route IS NULL OR route=''` 的行，**已有 route 一律不动**；
  2. 优先级：`dosage_form` 文本 > `form_base` > 商品名尾缀（`name_suffix`，低置信）；
  3. 目标词表只用库里已有写法（oral / topical / injection / ophthalmic / inhalation /
     rectal / nasal / dental / transdermal），不新造枚举；
  4. **「喷雾/噴霧 → inhalation」歧义修正**：只有 `form_base='inhalation'` 或商品名含「吸入」
     才填，否则留空（dry-run 抽检发现的唯一可疑条就是这条）；
  5. 没有信号的行一律留空（约 2.6 万行，主要是 AU / US 的泛剂型）。

纪律：route 是「给药途径」事实派生，不涉及剂量、不涉及可替代性判断。

CLI：
    python etl/route_backfill.py --dry-run                      # 默认：只读，打印每条规则将命中多少行
    python etl/route_backfill.py --apply --db .tmp/xxx.db       # 副本演练
    python etl/route_backfill.py --apply --allow-real --db data/drugs.db
    python etl/route_backfill.py --rollback --allow-real --manifest data/sources/route_backfill_manifest_20261116.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))

import _ingest_common as common  # noqa: E402

try:  # pragma: no cover - 只影响终端显示
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

RULES_CSV = ROOT / "data" / "sources" / "route_rules_20261115.csv"
REAL_DB = ROOT / "data" / "drugs.db"
MANIFEST_DEFAULT = ROOT / "data" / "sources" / "route_backfill_manifest_20261116.json"
KIND_ORDER = {"dosage_form": 0, "form_base": 1, "name_suffix": 2}
# 「喷雾」既可能是外用喷雾也可能是吸入：只有这两类证据才落 inhalation。
AMBIGUOUS_INHALATION_TOKENS = ("喷雾", "噴霧")
ROUTE_VOCAB = ("oral", "topical", "injection", "ophthalmic", "inhalation", "rectal",
               "nasal", "dental", "transdermal")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_rules(path: Path = RULES_CSV) -> list[dict]:
    """读规则表 → 规则列表；`verdict != fill*` 的一律不用（规则表自己标了「不填」）。"""
    rules: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for idx, row in enumerate(csv.DictReader(fh)):
            verdict = (row.get("verdict") or "").strip()
            kind = (row.get("kind") or "").strip()
            spec = (row.get("rule") or "").strip()
            route = (row.get("route") or "").strip()
            if not verdict.startswith("fill") or kind not in KIND_ORDER or not spec:
                continue
            if route not in ROUTE_VOCAB:
                raise SystemExit(f"规则表里出现未收录的 route 词：{route!r}（不新造枚举）")
            rules.append({
                "idx": idx, "route": route, "kind": kind, "spec": spec,
                "hit_rows": int((row.get("hit_rows") or "0").strip() or 0),
                "verdict": verdict,
                "evidence": (row.get("evidence") or "").strip(),
            })
    rules.sort(key=lambda r: (KIND_ORDER[r["kind"]], r["idx"]))
    return rules


def _rule_sql(rule: dict) -> tuple[str, list, str]:
    """规则 → (WHERE 片段, 参数, 展示用 token)。列名固定写 `product.` 以配合子查询。"""
    spec = rule["spec"]
    if rule["kind"] == "dosage_form":
        token = spec.split("~", 1)[1]
        where = "product.dosage_form LIKE ?"
        params: list = [f"%{token}%"]
        if token in AMBIGUOUS_INHALATION_TOKENS:
            where += (" AND (product.form_base = 'inhalation'"
                      " OR EXISTS (SELECT 1 FROM product_name pn"
                      "   JOIN name_variant nv ON nv.key_id = pn.key_id"
                      "   WHERE pn.product_id = product.product_id AND nv.raw LIKE '%吸入%'))")
    elif rule["kind"] == "form_base":
        token = spec.split("=", 1)[1]
        where = "product.form_base = ?"
        params = [token]
    else:  # name_suffix
        token = spec.split("~", 1)[1]
        where = ("EXISTS (SELECT 1 FROM product_name pn"
                 " JOIN name_variant nv ON nv.key_id = pn.key_id"
                 " WHERE pn.product_id = product.product_id AND nv.raw LIKE ?)")
        params = [f"%{token}%"]
    return where, params, token


def route_counts(db: sqlite3.Connection) -> dict:
    row = db.execute(
        "SELECT COUNT(*) AS n,"
        " SUM(CASE WHEN route IS NULL OR route='' THEN 1 ELSE 0 END) AS empty,"
        " SUM(CASE WHEN route IS NOT NULL AND route<>'' THEN 1 ELSE 0 END) AS filled"
        " FROM product").fetchone()
    return {"product": row["n"], "route_empty": row["empty"], "route_filled": row["filled"]}


def run_plan(db: sqlite3.Connection, rules: list[dict], apply: bool) -> dict:
    """按规则顺序更新空 route；apply=False 只计数（SELECT），True 才 UPDATE。返回逐规则统计。

    dry-run 用内存 `claimed` 模拟「前面的规则已经填过」的状态，否则同一条空行会被多条规则
    重复计数（实测会算出比空值总数还大的命中数）。
    """
    done: list[dict] = []
    claimed: set[str] = set()
    for rule in rules:
        where, params, token = _rule_sql(rule)
        base = f"FROM product WHERE (product.route IS NULL OR product.route='') AND ({where})"
        ids = [r[0] for r in db.execute("SELECT product.product_id " + base, params)]
        if not apply:
            ids = [pid for pid in ids if pid not in claimed]
            claimed.update(ids)
        changed = 0
        if apply and ids:
            db.executemany("UPDATE product SET route=? WHERE product_id=?"
                           " AND (route IS NULL OR route='')", [(rule["route"], pid) for pid in ids])
            changed = len(ids)
        done.append({
            "route": rule["route"], "rule": rule["spec"], "kind": rule["kind"],
            "verdict": rule["verdict"], "token": token, "csv_hit_rows": rule["hit_rows"],
            "matched": len(ids), "changed": changed, "product_ids": ids,
        })
    return {"rules": done}


def cmd_dry_run(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    rules = load_rules(args.rules)
    db = common.connect(db_path, write=False)
    try:
        before = route_counts(db)
        plan = run_plan(db, rules, apply=False)
    finally:
        db.close()
    matched = sum(r["matched"] for r in plan["rules"])
    print("=== route 回填 dry-run（只读）===")
    print(f"  规则 {len(rules)} 条 · 空 route {before['route_empty']:,} → 可填 {matched:,}")
    print(f"  预计回填后空值 {before['route_empty'] - matched:,}")
    for r in plan["rules"][:12]:
        print(f"   {r['route']:<11} {r['rule']:<32} 命中 {r['matched']:>7,}（dry-run 表 {r['csv_hit_rows']:,}）")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    common.guard_real(db_path, REAL_DB, "apply", args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    rules = load_rules(args.rules)
    t0 = time.perf_counter()
    sha_before = common.sha256_file(db_path)
    db = common.connect(db_path, write=True)
    try:
        before = route_counts(db)
        db.execute("BEGIN IMMEDIATE")
        plan = run_plan(db, rules, apply=True)
        db.commit()
        after = route_counts(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    total = sum(r["changed"] for r in plan["rules"])
    manifest = {
        "tool": "etl/route_backfill.py",
        "db": str(db_path),
        "created_at": _now(),
        "rules_file": str(args.rules.relative_to(ROOT) if args.rules.is_relative_to(ROOT)
                          else args.rules),
        "rules_sha256": _sha256(args.rules),
        "db_sha256_before": sha_before,
        "db_sha256_after": common.sha256_file(db_path),
        "counts_before": before,
        "counts_after": after,
        "total_changed": total,
        "ambiguous_inhalation_tokens": list(AMBIGUOUS_INHALATION_TOKENS),
        "rules": plan["rules"],
        "rollback_hint": (
            "python etl/route_backfill.py --rollback --allow-real --db <同一个库> --manifest <本文件>；"
            "只把本清单里记过的 product_id 的 route 清回 NULL（不碰别的行）。"),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== route 回填完成 ===")
    print(json.dumps({"counts_before": before, "counts_after": after,
                      "total_changed": total}, ensure_ascii=False, indent=1))
    print(f"  撤销清单 {manifest_path}")
    print(f"  db sha256 {sha_before[:16]}… → {manifest['db_sha256_after'][:16]}… · "
          f"耗时 {time.perf_counter() - t0:.1f}s")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    common.guard_real(db_path, REAL_DB, "rollback", args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单：{manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = common.connect(db_path, write=True)
    cleared = 0
    try:
        db.execute("BEGIN IMMEDIATE")
        for rule in manifest.get("rules") or []:
            ids = [(pid,) for pid in rule.get("product_ids") or []]
            if not ids:
                continue
            before = db.total_changes
            db.executemany("UPDATE product SET route=NULL WHERE product_id=? AND route=?",
                           [(pid, rule["route"]) for (pid,) in ids])
            cleared += db.total_changes - before
        db.commit()
        after = route_counts(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print("=== route 回填回滚完成 ===")
    print(json.dumps({"cleared_rows": cleared, "counts_after": after}, ensure_ascii=False, indent=1))
    expected = manifest.get("counts_before") or {}
    diff = after["route_empty"] - int(expected.get("route_empty", 0))
    if diff:
        print(f"  !! 回滚后空 route 数 {after['route_empty']:,} ≠ 写前 "
              f"{expected.get('route_empty', 0):,}（差 {diff}）")
        return 1
    print("  已回到写前空值基线")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="route 回填：按规则表派生给药途径（只填空值）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只读：打印每条规则将命中多少行（默认）")
    mode.add_argument("--apply", action="store_true", help="写库（真实库需 --allow-real）")
    mode.add_argument("--rollback", action="store_true", help="按 manifest 把本次写入的 route 清回 NULL")
    ap.add_argument("--db", type=Path, default=REAL_DB, help="库路径（默认 data/drugs.db）")
    ap.add_argument("--rules", type=Path, default=RULES_CSV, help="规则表 CSV")
    ap.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT, help="撤销清单路径")
    ap.add_argument("--allow-real", action="store_true", help="允许写真实库 data/drugs.db")
    args = ap.parse_args(argv)
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
