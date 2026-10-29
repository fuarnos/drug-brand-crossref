# -*- coding: utf-8 -*-
"""task-26 溯源字段的 schema 回滚（DROP COLUMN）；默认 dry-run。

只回滚 **task-26 新增的 8 个 nullable 列**：
    substance    : source_id / method / confidence / decided_at
    brand_family : source_id / method / confidence / decided_at

用法：
    python db/migrate_provenance.py --db .tmp/prov/drugs.db          # dry-run（只打印）
    python db/migrate_provenance.py --db .tmp/prov/drugs.db --apply  # 真正 DROP

说明：
- `db/init_db.py` 只加列、不删列，**不能**当回滚；本脚本补上回滚路径。
- 回滚前请先备份（`Copy-Item data\\drugs.db data\\backups\\...`）；整库兜底用备份恢复更稳。
- DROP COLUMN 需要 SQLite ≥ 3.35（本项目实测 3.53.1）；这 8 列无索引/视图依赖。
- DROP 后文件会留 freelist；如需回收体积，回滚后跑 `VACUUM`。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DEFAULT = ROOT / "data" / "drugs.db"

COLUMNS = {
    "substance": ("decided_at", "confidence", "method", "source_id"),
    "brand_family": ("decided_at", "confidence", "method", "source_id"),
}


def plan(db: sqlite3.Connection) -> list[tuple[str, str]]:
    todo: list[tuple[str, str]] = []
    for table, cols in COLUMNS.items():
        have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        for col in cols:                     # 反序：后加的列先删
            if col in have:
                todo.append((table, col))
    return todo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="回滚 task-26 溯源列（DROP COLUMN）")
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--apply", action="store_true", help="真正执行（默认 dry-run）")
    args = ap.parse_args(argv)
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    con = sqlite3.connect(db_path, timeout=120)
    try:
        todo = plan(con)
        if not todo:
            print("没有需要回滚的列（已是迁移前状态）")
            return 0
        print(f"回滚计划（{len(todo)} 列，{'执行' if args.apply else 'dry-run'}）：")
        for table, col in todo:
            print(f"  ALTER TABLE {table} DROP COLUMN {col}")
        if not args.apply:
            print("\n（dry-run：未改库；加 --apply 执行）")
            return 0
        for table, col in todo:
            con.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
        con.commit()
        left = plan(con)
        print(f"完成：剩余待删 {len(left)} 列；quick_check={con.execute('pragma quick_check').fetchone()[0]}"
              f"；freelist={con.execute('pragma freelist_count').fetchone()[0]}"
              f"（可 VACUUM 回收）")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
