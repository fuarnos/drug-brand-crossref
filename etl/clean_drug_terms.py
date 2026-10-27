#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清理 nickname / drug_term 中的毒品与娱乐性用药黑话（用户口径：只保留合法药品俗名）。

输入：`data/drug_term_removals.csv`（id,table,alias,substance_id,reason,evidence；
由只读扫描 + 规则生成；见 reports/drug-term-cleanup.md）

安全设计
--------
- 默认 **dry-run**（只读打开数据库，逐条校验 id 存在且 alias 匹配，打印计划）；
- `--apply`：事务内 `DELETE`，写完整行快照撤销清单（默认 `.tmp/drug-term-cleanup/undo_*.json`）；
- `--rollback [manifest]`：用快照 `INSERT OR REPLACE` 恢复，幂等（已存在则跳过）；
- 校验 id + alias 双重匹配，防止 SQLite id 复用导致删错；
- 不写真实库由 Lead 决定；本轮只在 `.tmp/drug-term-cleanup/drugs-test.db` 副本验证。

用法
----
    python etl/clean_drug_terms.py                 # dry-run（默认）
    python etl/clean_drug_terms.py --db X --apply  # 写库 + 撤销清单
    python etl/clean_drug_terms.py --db X --rollback [manifest]
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
CSV_DEFAULT = ROOT / "data" / "drug_term_removals.csv"
DB_DEFAULT = ROOT / "data" / "drugs.db"
MANIFEST_DIR = ROOT / ".tmp" / "drug-term-cleanup"

TABLES = {
    "drug_term": dict(pk="term_id", alias="term"),
    "nickname": dict(pk="nickname_id", alias="alias"),
}


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


def load_removals(csv_path: Path) -> list[dict]:
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    out = []
    for r in rows:
        item = {k: (r.get(k) or "").strip() for k in
                ("id", "table", "alias", "substance_id", "reason", "evidence")}
        try:
            item["id"] = int(item["id"])
        except ValueError:
            item["id"] = -1
        out.append(item)
    return out


def plan(con: sqlite3.Connection, rows: list[dict]) -> dict:
    accepted: list[dict] = []
    skipped: list[dict] = []
    by_table: Counter = Counter()
    for r in rows:
        table = r["table"]
        if table not in TABLES:
            skipped.append(dict(**r, why=f"未知表 {table}"))
            continue
        meta = TABLES[table]
        row = con.execute(f"SELECT * FROM {table} WHERE {meta['pk']}=?",
                          (r["id"],)).fetchone()
        if row is None:
            skipped.append(dict(**r, why="行不存在（可能已删除/已清理）"))
            continue
        cur_alias = row[meta["alias"]] or ""
        if cur_alias != r["alias"]:
            skipped.append(dict(**r, why=f"alias 不匹配：库内为 {cur_alias!r}"))
            continue
        accepted.append(dict(**r, snapshot=dict(row)))
        by_table[table] += 1
    return dict(rows=rows, accepted=accepted, skipped=skipped, by_table=by_table)


def print_plan(p: dict) -> None:
    print(f"删除清单：{len(p['rows'])} 行")
    print(f"可删除：{len(p['accepted'])} 行；跳过：{len(p['skipped'])} 行")
    print("按表分布:", dict(p["by_table"]))
    reasons = Counter()
    for a in p["accepted"]:
        key = a["reason"].split("；")[0]
        reasons[key] += 1
    print("按原因分布:")
    for k, v in reasons.most_common():
        print(f"  {v:>4}  {k}")
    src = Counter(a["evidence"].split(" | ")[0] for a in p["accepted"])
    print("按来源分布:", dict(src))
    print("\n样例（前 15）:")
    for a in p["accepted"][:15]:
        print(f"  {a['table']:<10} {a['id']:>4}  {a['alias']:<16} "
              f"{a['substance_id'] or '-':<22} {a['reason'][:60]}")
    if p["skipped"]:
        print("\n跳过明细（前 10）:")
        for s in p["skipped"][:10]:
            print(f"  {s['table']} {s['id']} {s['alias']}: {s['why']}")


def apply_plan(con: sqlite3.Connection, p: dict, db_path: Path, csv_path: Path,
               manifest_path: Path) -> int:
    accepted = p["accepted"]
    if not accepted:
        print("没有可删除的行（幂等或全部被跳过），未写库。")
        return 0
    manifest = dict(tool="etl/clean_drug_terms.py", db=str(db_path.resolve()),
                    csv=str(csv_path.resolve()),
                    csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                    created_at=utc_now(), committed=False, deleted=[])
    try:
        con.execute("BEGIN IMMEDIATE")
        for a in accepted:
            table = a["table"]
            meta = TABLES[table]
            cur = con.execute(
                f"DELETE FROM {table} WHERE {meta['pk']}=? AND {meta['alias']}=?",
                (a["id"], a["alias"]))
            if cur.rowcount != 1:
                raise RuntimeError(f"删除 {table}#{a['id']} 影响 {cur.rowcount} 行，中止")
            manifest["deleted"].append(dict(table=table, row=a["snapshot"],
                                            reason=a["reason"], evidence=a["evidence"]))
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
    print(f"已删除 {len(accepted)} 行；撤销清单: {manifest_path}")
    return len(accepted)


def rollback(con: sqlite3.Connection, manifest_path: Path) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not data.get("committed"):
        raise SystemExit(f"清单 {manifest_path} 未标记 committed，拒绝回滚")
    if data.get("rolled_back_at"):
        print(f"清单已于 {data['rolled_back_at']} 回滚过，继续执行幂等回填")
    restored = 0
    existed = 0
    con.execute("BEGIN IMMEDIATE")
    try:
        for rec in reversed(data.get("deleted", [])):
            table = rec["table"]
            row = rec["row"]
            meta = TABLES[table]
            pk = row[meta["pk"]]
            if con.execute(f"SELECT 1 FROM {table} WHERE {meta['pk']}=?", (pk,)).fetchone():
                existed += 1
                continue
            cols = list(row.keys())
            ph = ",".join("?" * len(cols))
            con.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})",
                        tuple(row[c] for c in cols))
            restored += 1
        data["rolled_back_at"] = utc_now()
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
    except Exception:
        con.rollback()
        raise
    print(f"已恢复 {restored} 行；已存在跳过 {existed} 行")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="清理 nickname/drug_term 中的毒品与娱乐性用药黑话（默认 dry-run）。")
    ap.add_argument("--csv", default=str(CSV_DEFAULT), help="删除清单 CSV")
    ap.add_argument("--db", default=str(DB_DEFAULT), help="SQLite 数据库")
    ap.add_argument("--apply", action="store_true", help="事务删除 + 撤销清单")
    ap.add_argument("--dry-run", action="store_true", help="只出计划（默认）")
    ap.add_argument("--rollback", nargs="?", const="latest", default=None,
                    help="回滚：可给清单路径，缺省取最新清单")
    ap.add_argument("--manifest", default=None, help="撤销清单路径")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"删除清单不存在: {csv_path}")
    rows = load_removals(csv_path)

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

    con = connect(db_path, readonly=not args.apply)
    try:
        p = plan(con, rows)
        print(f"DB: {db_path}  ({'只读' if not args.apply else '读写'})")
        print(f"CSV: {csv_path}")
        print()
        print_plan(p)
        if args.apply:
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
