"""初始化数据库：把 db/schema.sql 应用到 data/drugs.db。可重复运行。

除了建表，还负责一处**结构迁移**：product.country 的 CHECK 枚举。
SQLite 改不了 CHECK，只能重建表。市场是逐步加的（US → GB → CN → ES → MX），
所以每次 schema.sql 扩了枚举，这里就把老库里的 product 表换成新定义，数据原样搬过去。

    ALTER TABLE product RENAME TO product_old   （legacy_alter_table=ON，避免把子表外键
                                                 一起改成指向 product_old）
    <重跑 schema.sql 建新 product>
    INSERT INTO product SELECT * FROM product_old
    DROP TABLE product_old
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "drugs.db"

CHECK_RE = re.compile(r"country\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(country\s+IN\s*\(([^)]*)\)\)",
                      re.I)
STATUS_RE = re.compile(
    r"status\s+TEXT\s+NOT\s+NULL\s+DEFAULT\s+'active'\s*CHECK\s*\(status\s+IN\s*\(([^)]*)\)\)",
    re.I)


def _enum(match: re.Match | None) -> set[str]:
    if not match:
        return set()
    return {x.strip().strip("'\"") for x in match.group(1).split(",") if x.strip()}


def markets(sql: str) -> set[str]:
    return _enum(CHECK_RE.search(sql or ""))


def statuses(sql: str) -> set[str]:
    return _enum(STATUS_RE.search(sql or ""))


def build(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path, timeout=60)
    schema_text = SCHEMA.read_text(encoding="utf-8")
    target = markets(schema_text)

    db.executescript(schema_text)
    db.commit()

    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='product'").fetchone()
    have = markets(row[0]) if row else set()
    have_status = statuses(row[0]) if row else set()
    target_status = statuses(schema_text)
    if row and ((target and have != target) or (target_status and have_status != target_status)):
        missing = ", ".join(sorted(target - have)) or "(none)"
        missing_st = ", ".join(sorted(target_status - have_status)) or "(none)"
        print(f"迁移 product 表：country {sorted(have)} → {sorted(target)}（新增 {missing}）；"
              f"status 新增 {missing_st}")
        db.executescript("PRAGMA foreign_keys=OFF;")
        db.execute("PRAGMA legacy_alter_table=ON")
        db.execute("BEGIN")
        db.execute("ALTER TABLE product RENAME TO product_old")
        db.executescript(schema_text)          # 建回新的 product（含新 CHECK）
        db.execute("INSERT INTO product SELECT * FROM product_old")
        db.execute("DROP TABLE product_old")
        db.commit()
        db.execute("PRAGMA legacy_alter_table=OFF")
        db.executescript("PRAGMA foreign_keys=ON;")
    return db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()

    db = build(args.db)
    print(f"db  : {args.db}")
    for kind, name in db.execute(
        "SELECT type, name FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ):
        print(f"  {kind:6} {name}")
    prod_sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE name='product'").fetchone()[0]
    print(f"  market {sorted(markets(prod_sql))}")
    print(f"  status {sorted(statuses(prod_sql))}")
    db.close()


if __name__ == "__main__":
    main()
