#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 `data/inn_zh_backfill.csv` 的中文成分名回填到 `substance.inn_zh`。

安全设计
--------
- 默认 **dry-run**（只读打开 DB）：校验 CSV 与库内状态，打印将回填条数 / 覆盖率
  before-after / 按 confidence 分布；不写库。
- `--apply`：事务内 **只更新当前 inn_zh 为空的行**（绝不覆盖已有值），先写完整撤销清单
  （旧值 + 新值）再 commit；任一行更新 0 行或多行 → 中止回滚。
- `--rollback [manifest]`：把新值精确恢复为旧值（旧值为 NULL/空串时恢复为空串/NULL 原样）；
  只回滚「当前值 == 写入值」的行，已被别人改过的行记冲突、不覆盖；可重复执行（幂等）。
- `--min-confidence high|medium|low`：默认只回填 high；先跑 high、人工抽检后再放开 medium。

用法
----
    python etl/apply_inn_zh.py                      # dry-run（默认 high）
    python etl/apply_inn_zh.py --dry-run --min-confidence medium
    python etl/apply_inn_zh.py --db X.db --apply --min-confidence high
    python etl/apply_inn_zh.py --db X.db --rollback [manifest]

本轮验证只在 `.tmp/inn-zh/` 的 DB 副本上做；真实库由 Lead 决定何时 apply。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_DEFAULT = ROOT / "data" / "inn_zh_backfill.csv"
DB_DEFAULT = ROOT / "data" / "drugs.db"
MANIFEST_DIR = ROOT / ".tmp" / "inn-zh"
CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True, timeout=60)
    else:
        con = sqlite3.connect(str(db_path), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def load_rows(csv_path: Path) -> list[dict]:
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    out = []
    for r in rows:
        r = {k: (r.get(k) or "").strip() for k in
             ("substance_id", "inn_en", "zh_candidate", "confidence", "method",
              "count", "share", "variants", "evidence")}
        out.append(r)
    return out


def build_plan(con: sqlite3.Connection, rows: list[dict], min_conf: str) -> dict:
    accepted, skipped = [], []
    dist = Counter()
    min_rank = CONF_RANK[min_conf]
    for r in rows:
        conf = r["confidence"] or "low"
        if (CONF_RANK.get(conf, 9)) > min_rank:
            dist["低于置信度门槛"] += 1
            continue
        if not r["substance_id"] or not r["zh_candidate"]:
            skipped.append(dict(r, why="substance_id/候选为空"))
            continue
        row = con.execute("SELECT substance_id, inn_en, inn_zh FROM substance"
                          " WHERE substance_id=?", (r["substance_id"],)).fetchone()
        if row is None:
            skipped.append(dict(r, why="substance 不存在"))
            continue
        if (row["inn_en"] or "") != r["inn_en"]:
            skipped.append(dict(r, why=f"inn_en 不一致：库内 {row['inn_en']!r}"))
            continue
        cur = row["inn_zh"] or ""
        if cur.strip():
            skipped.append(dict(r, why=f"已有 inn_zh={cur!r}（不覆盖，幂等跳过）"))
            dist["已有值跳过"] += 1
            continue
        accepted.append(dict(r, old_inn_zh=(row["inn_zh"] if row["inn_zh"] is not None
                                            else None)))
        dist[f"confidence_{conf}"] += 1
    total_sub = con.execute("SELECT COUNT(*) FROM substance").fetchone()[0]
    existing = con.execute(
        "SELECT COUNT(*) FROM substance WHERE inn_zh IS NOT NULL"
        " AND trim(inn_zh)<>''").fetchone()[0]
    return dict(rows=rows, accepted=accepted, skipped=skipped, dist=dist,
                total_sub=total_sub, existing=existing)


def print_plan(p: dict, min_conf: str) -> None:
    print(f"DB: 共 {p['total_sub']} 个 substance；已有 inn_zh {p['existing']}")
    print(f"CSV 行数 {len(p['rows'])}；min-confidence={min_conf}")
    print(f"可回填：{len(p['accepted'])} 行；跳过：{len(p['skipped'])} 行")
    print("分布:", dict(p["dist"]))
    after = p["existing"] + len(p["accepted"])
    print(f"覆盖率: {p['existing']}/{p['total_sub']} → {after}/{p['total_sub']}"
          f"（{p['existing']/p['total_sub']*100:.1f}% → "
          f"{after/p['total_sub']*100:.1f}%）")
    if p["skipped"]:
        print("\n跳过明细（前 10）:")
        for s in p["skipped"][:10]:
            print(f"  {s['substance_id']} {s['inn_en']}: {s['why']}")
    print("\n样例（前 20）:")
    for r in p["accepted"][:20]:
        print(f"  {r['inn_en']:<28} -> {r['zh_candidate']:<10} {r['confidence']:<6}"
              f" {r['method']}")


def apply_plan(con: sqlite3.Connection, p: dict, db_path: Path, csv_path: Path,
               manifest_path: Path) -> int:
    accepted = p["accepted"]
    if not accepted:
        print("没有可回填的行（幂等或全部跳过），未写库。")
        return 0
    manifest = dict(tool="etl/apply_inn_zh.py", db=str(db_path.resolve()),
                    csv=str(csv_path.resolve()),
                    csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                    created_at=utc_now(), committed=False, rows=[])
    try:
        con.execute("BEGIN IMMEDIATE")
        for a in accepted:
            cur = con.execute(
                "UPDATE substance SET inn_zh=? WHERE substance_id=?"
                " AND (inn_zh IS NULL OR trim(inn_zh)='')",
                (a["zh_candidate"], a["substance_id"]))
            if cur.rowcount != 1:
                raise RuntimeError(f"更新 {a['substance_id']} 影响 {cur.rowcount} 行，中止")
            manifest["rows"].append(dict(
                substance_id=a["substance_id"], inn_en=a["inn_en"],
                old_inn_zh=a["old_inn_zh"], new_inn_zh=a["zh_candidate"],
                confidence=a["confidence"], method=a["method"],
                evidence=a["evidence"]))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
        manifest["committed"] = True
        manifest["committed_at"] = utc_now()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception:
        con.rollback()
        print("!! 写库失败，已回滚事务", file=sys.stderr)
        raise
    print(f"已回填 {len(accepted)} 行；撤销清单: {manifest_path}")
    return len(accepted)


def rollback(con: sqlite3.Connection, manifest_path: Path) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not data.get("committed"):
        raise SystemExit(f"清单 {manifest_path} 未标记 committed，拒绝回滚")
    if data.get("rolled_back_at"):
        print(f"清单已于 {data['rolled_back_at']} 回滚过，继续幂等恢复")
    restored = 0
    skipped = 0
    conflicts = []
    con.execute("BEGIN IMMEDIATE")
    try:
        for rec in reversed(data.get("rows", [])):
            sid = rec["substance_id"]
            row = con.execute("SELECT inn_zh FROM substance WHERE substance_id=?",
                              (sid,)).fetchone()
            if row is None:
                conflicts.append(f"{sid}: substance 已不存在")
                continue
            cur = row["inn_zh"]
            if cur == rec["old_inn_zh"] or (cur is None and rec["old_inn_zh"] is None):
                skipped += 1
                continue
            if cur != rec["new_inn_zh"]:
                conflicts.append(f"{sid}: 当前值 {cur!r} 已被改动，跳过")
                continue
            con.execute("UPDATE substance SET inn_zh=? WHERE substance_id=?",
                        (rec["old_inn_zh"], sid))
            restored += 1
        data["rolled_back_at"] = utc_now()
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
    except Exception:
        con.rollback()
        raise
    print(f"已恢复 {restored} 行；已回滚/未改跳过 {skipped} 行")
    if conflicts:
        print(f"!! {len(conflicts)} 个冲突未恢复:")
        for c in conflicts[:20]:
            print("   " + c)
        raise SystemExit(2)


def main() -> None:
    ap = argparse.ArgumentParser(description="把 inn_zh 回填 CSV 写入 substance.inn_zh"
                                             "（默认 dry-run）")
    ap.add_argument("--csv", default=str(CSV_DEFAULT))
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--min-confidence", choices=["high", "medium", "low"],
                    default="high", help="最低置信度（默认 high）")
    ap.add_argument("--apply", action="store_true", help="事务写库 + 撤销清单")
    ap.add_argument("--dry-run", action="store_true", help="只出计划（默认）")
    ap.add_argument("--rollback", nargs="?", const="latest", default=None)
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"回填 CSV 不存在: {csv_path}")

    if args.rollback is not None:
        con = connect(db_path, readonly=False)
        try:
            if args.rollback == "latest":
                cands = sorted(MANIFEST_DIR.glob("undo_*.json"),
                               key=lambda p: p.stat().st_mtime)
                if not cands:
                    raise SystemExit(f"{MANIFEST_DIR} 下没有 undo_*.json")
                mp = cands[-1]
            else:
                mp = Path(args.rollback)
            print(f"回滚清单: {mp}")
            rollback(con, mp)
        finally:
            con.close()
        return

    rows = load_rows(csv_path)
    con = connect(db_path, readonly=not args.apply)
    try:
        p = build_plan(con, rows, args.min_confidence)
        print(f"DB: {db_path}  ({'只读' if not args.apply else '读写'})")
        print(f"CSV: {csv_path}")
        print()
        print_plan(p, args.min_confidence)
        if args.apply:
            if p["skipped"]:
                # 只提示：已有值/失效行跳过是幂等设计，不阻断
                print(f"\n（{len(p['skipped'])} 行跳过，见上）")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            manifest = Path(args.manifest) if args.manifest else (
                MANIFEST_DIR / f"undo_{stamp}.json")
            print()
            apply_plan(con, p, db_path, csv_path, manifest)
        else:
            print("\n(dry-run，未写库。Lead 审核后加 --apply 执行)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
