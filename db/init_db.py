"""初始化数据库：把 db/schema.sql 应用到 data/drugs.db。可重复运行。

除了建表，还负责三处**结构迁移**（都幂等，老库可直接升级）：

1. v0.4 `variant` 加列 `salt_code` / `strength_basis`（`_ensure_variant_columns`）；
2. v0.4.2 补两个小索引 `idx_artg_name` / `idx_variant_substance`（`_ensure_indexes`，
   来自 DB 优化审计 `reports/db-optimization.md`）；
3. `product.country` 的 CHECK 枚举。SQLite 改不了 CHECK，只能重建表。市场是逐步加的
   （US → GB → CN → ES → MX），所以每次 schema.sql 扩了枚举，这里就把老库里的 product
   表换成新定义，数据原样搬过去。


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


def _ensure_source_columns(db: sqlite3.Connection) -> None:
    """给已有库补 source.data_as_of / source.data_as_of_note（SQLite 只能 ALTER ADD）。"""
    have = {r[1] for r in db.execute("PRAGMA table_info(source)")}
    for name, ddl in (("data_as_of", "TEXT"), ("data_as_of_note", "TEXT")):
        if name not in have:
            db.execute(f"ALTER TABLE source ADD COLUMN {name} {ddl}")
            print(f"迁移 source 表：新增列 {name}")
    db.commit()


def _ensure_variant_columns(db: sqlite3.Connection) -> None:
    """v0.4：给已有库补 variant.salt_code / variant.strength_basis。

    SQLite 的 ALTER TABLE ADD COLUMN 是幂等的安全操作（先查 PRAGMA table_info）；
    NOT NULL 列必须带非 NULL 默认值，这里正好用 '' / 'unknown'，存量行语义正确：
    盐未规范化、强度基准未知。
    """
    have = {r[1] for r in db.execute("PRAGMA table_info(variant)")}
    if not have:                       # 空库还没建 variant（正常不会发生）
        return
    for name, ddl in (
        ("salt_code", "TEXT NOT NULL DEFAULT ''"),
        ("strength_basis", "TEXT NOT NULL DEFAULT 'unknown' "
                           "CHECK (strength_basis IN "
                           "('base', 'salt', 'salt_equivalent', 'unknown'))"),
    ):
        if name not in have:
            db.execute(f"ALTER TABLE variant ADD COLUMN {name} {ddl}")
            print(f"迁移 variant 表：新增列 {name}")
    db.execute("CREATE INDEX IF NOT EXISTS idx_variant_salt_code ON variant (salt_code)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_variant_basis ON variant (strength_basis)")
    db.commit()


def _ensure_indexes(db: sqlite3.Connection) -> None:
    """v0.4.2：给已有库补 DB 优化审计落地的两个小索引（幂等）。

    空库会由 schema.sql 的 `CREATE INDEX IF NOT EXISTS` 建好；老库跑 init_db 时走这里。
    真实库若已经手工建过同名索引，IF NOT EXISTS 不会重复建、也不会报错。

    - idx_artg_name：site/build.py ARTG 列表 ORDER BY name（实测 50 → 32 ms）
    - idx_variant_substance：成分 → variant 点查（0.6 → 0.1 ms）
    审计依据 reports/db-optimization.md §3.2；**不要**顺手跑 ANALYZE（实测会让 build 查询变慢 2–3 倍）。
    """
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_variant_substance ON variant (substance_id)",
        "CREATE INDEX IF NOT EXISTS idx_artg_name ON artg_entry (name)",
    ):
        db.execute(ddl)
    db.commit()


def build(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path, timeout=60)
    schema_text = SCHEMA.read_text(encoding="utf-8")
    target = markets(schema_text)

    # v0.4：老库必须先补 variant 新列，否则 schema.sql 里建在 salt_code 上的索引
    # 会直接报 "no such column"（CREATE TABLE IF NOT EXISTS 不会改已存在的表）。
    _ensure_variant_columns(db)
    db.executescript(schema_text)
    db.commit()
    _ensure_source_columns(db)
    _ensure_variant_columns(db)
    _ensure_indexes(db)

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
