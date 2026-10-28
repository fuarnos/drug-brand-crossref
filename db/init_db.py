"""初始化数据库：把 db/schema.sql 应用到 data/drugs.db。可重复运行。

除了建表，还负责四处**结构迁移**（都幂等，老库可直接升级）：

1. v0.4 `variant` 加列 `salt_code` / `strength_basis`（`_ensure_variant_columns`）；
2. v0.4.2 补两个小索引 `idx_artg_name` / `idx_variant_substance`（`_ensure_indexes`，
   来自 DB 优化审计 `reports/db-optimization.md`）；
3. `source` 表补 `data_as_of` / `data_as_of_note`（`_ensure_source_columns`）；
4. `product.country` 的 CHECK 枚举。SQLite 改不了 CHECK，只能重建表。市场是逐步加的
   （US → GB → CN → ES → MX → AU → CA → **TW** → **HK**），所以每次 schema.sql 扩了枚举，这里就把
   老库里的 product 表换成新定义，数据原样搬过去。
5. **区域层（region）**：EU = 欧盟集中审批（EMA），不是国家市场。schema 的 `product.country`
   改为可空并新增 `product.region`（country 与 region 二选一，CHECK 约束）；老库缺 region 列
   或 country 仍是 NOT NULL 时，用同一套 `_rebuild_product()` 重建（列拷贝、region 默认 NULL），
   同时 `coverage` 视图改为 `COALESCE(country, region)` 分组（EU 单独一行）。

重建流程（v0.4.3 修复：旧表占着 `idx_product_country` 的名字，`CREATE INDEX IF NOT EXISTS`
会在旧表还在时被跳过、删旧表后索引就丢了；现在改为「先建新表 → 搬数据 → 删旧表 →
显式重建 product 索引」）：

    ALTER TABLE product RENAME TO product_old   （legacy_alter_table=ON，避免把子表外键
                                                  /视图引用一起改成指向 product_old）
    <用 schema.sql 里的 product DDL 建新 product>
    INSERT INTO product (公共列) SELECT 公共列 FROM product_old
    DROP TABLE product_old
    <显式 CREATE INDEX ... ON product>           （此时名字已空出）
    校验：行数 / 索引集合 / 视图可查 / foreign_key_check / quick_check

迁移**只对副本**（`--db .tmp/...`）验证时也安全；真实库建议先由 run_all 备份。
`python db/migrate_country_tw.py` / `db/migrate_country_hk.py` 是同一套逻辑的独立可回滚版本
（task-62 / task-88；init_db 路径没有撤销清单，回滚走 DB 备份恢复）。
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "drugs.db"

CHECK_RE = re.compile(
    r"country\s+TEXT\s+(?:NOT\s+NULL\s+|NULL\s+)?CHECK\s*\(\s*"
    r"(?:country\s+IS\s+NULL\s+OR\s+)?country\s+IN\s*\(([^)]*)\)\)", re.I)
STATUS_RE = re.compile(
    r"status\s+TEXT\s+NOT\s+NULL\s+DEFAULT\s+'active'\s*CHECK\s*\(status\s+IN\s*\(([^)]*)\)\)",
    re.I)
PRODUCT_DDL_RE = re.compile(r"CREATE TABLE IF NOT EXISTS product\s*\(", re.I)


def _enum(match: re.Match | None) -> set[str]:
    if not match:
        return set()
    return {x.strip().strip("'\"") for x in match.group(1).split(",") if x.strip()}


def markets(sql: str) -> set[str]:
    return _enum(CHECK_RE.search(sql or ""))


def statuses(sql: str) -> set[str]:
    return _enum(STATUS_RE.search(sql or ""))


def product_ddl(schema_text: str) -> str:
    """从 schema.sql 提取 product 的 CREATE TABLE 语句（括号配平，取到行首 `);`）。"""
    m = PRODUCT_DDL_RE.search(schema_text)
    if not m:
        raise SystemExit("schema.sql 里找不到 product 建表语句")
    i = schema_text.find("(", m.end() - 1)
    depth = 0
    for j in range(i, len(schema_text)):
        ch = schema_text[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = schema_text.find(";", j)
                return schema_text[m.start():end + 1]
    raise SystemExit("product 建表语句括号不配平")


def product_index_ddls(schema_text: str) -> list[str]:
    return [m.group(0) for m in re.finditer(
        r"CREATE INDEX IF NOT EXISTS \w+ ON product\s*\([^;]*\);", schema_text, re.I | re.S)]


def snapshot(db: sqlite3.Connection) -> dict:
    product_rows = db.execute("SELECT COUNT(*) FROM product").fetchone()[0]
    indexes = sorted((r[0], r[1] or "") for r in db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='product'"
        " AND name NOT LIKE 'sqlite_autoindex%'"))
    views = sorted(r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"))
    return {"product_rows": product_rows, "product_indexes": indexes, "views": views}


def verify_migration(db: sqlite3.Connection, before: dict, expected_index_names: set[str]) -> None:
    after = snapshot(db)
    problems: list[str] = []
    if after["product_rows"] != before["product_rows"]:
        problems.append("product 行数 %d → %d" % (before["product_rows"], after["product_rows"]))
    after_idx = {n for n, _s in after["product_indexes"]}
    if not expected_index_names.issubset(after_idx):
        problems.append("product 索引缺失: %s" % sorted(expected_index_names - after_idx))
    for v in after["views"]:
        try:
            db.execute("SELECT 1 FROM %s LIMIT 1" % v).fetchone()
        except sqlite3.Error as e:  # noqa: PERF203
            problems.append("视图 %s 不可查询: %s" % (v, e))
    fk = db.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        problems.append("foreign_key_check 有 %d 条违规" % len(fk))
    quick = db.execute("PRAGMA quick_check").fetchone()[0]
    if quick != "ok":
        problems.append("quick_check=%s" % quick)
    if problems:
        raise SystemExit("product 表迁移校验失败：\n  - " + "\n  - ".join(problems))
    print(f"  迁移校验 OK：{after['product_rows']:,} 行、{len(after['product_indexes'])} 个 product 索引、"
          f"{len(after['views'])} 个视图可查、foreign_key_check 0、quick_check ok")


def _ensure_source_columns(db: sqlite3.Connection) -> None:
    """给已有库补 source.data_as_of / source.data_as_of_note（SQLite 只能 ALTER ADD）。"""
    have = {r[1] for r in db.execute("PRAGMA table_info(source)")}
    for name, ddl in (("data_as_of", "TEXT"), ("data_as_of_note", "TEXT")):
        if name not in have:
            db.execute(f"ALTER TABLE source ADD COLUMN {name} {ddl}")
            print(f"迁移 source 表：新增列 {name}")
    db.commit()


def _ensure_variant_columns(db: sqlite3.Connection) -> None:
    """v0.4：给已有库补 variant.salt_code / variant.strength_basis。"""
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
    """v0.4.2：给已有库补 DB 优化审计落地的两个小索引（幂等）。"""
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_variant_substance ON variant (substance_id)",
        "CREATE INDEX IF NOT EXISTS idx_artg_name ON artg_entry (name)",
    ):
        db.execute(ddl)
    db.commit()


def _rebuild_product(db: sqlite3.Connection, schema_text: str) -> None:
    """按 schema.sql 的 product 定义重建表（country/status CHECK 变更用），保留数据与索引。"""
    t0 = time.perf_counter()
    before = snapshot(db)
    ddl = product_ddl(schema_text)
    index_ddls = product_index_ddls(schema_text)
    db.executescript("PRAGMA foreign_keys=OFF;")
    db.execute("PRAGMA legacy_alter_table=ON")
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("ALTER TABLE product RENAME TO product_old")
        db.execute(ddl)
        old_cols = [r[1] for r in db.execute("PRAGMA table_info(product_old)")]
        new_cols = {r[1] for r in db.execute("PRAGMA table_info(product)")}
        cols = [c for c in old_cols if c in new_cols]
        if not cols:
            raise SystemExit("product 新表与旧表没有公共列，拒绝迁移")
        col_sql = ", ".join(cols)
        db.execute("INSERT INTO product (%s) SELECT %s FROM product_old" % (col_sql, col_sql))
        db.execute("DROP TABLE product_old")
        for one in index_ddls:              # 旧表删掉后，索引名空出，显式重建
            db.execute(one)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA legacy_alter_table=OFF")
        db.executescript("PRAGMA foreign_keys=ON;")
    expected = {re.search(r"(\w+)", d.replace("CREATE INDEX IF NOT EXISTS", "")).group(1)
                for d in index_ddls}
    verify_migration(db, before, expected)
    print(f"  重建 product 表耗时 {time.perf_counter() - t0:.2f}s")


def _product_region_needed(db: sqlite3.Connection) -> bool:
    """老库是否需要为「区域层（region）」重建 product 表。

    需要重建的两种情况：
    1. product 表没有 `region` 列（schema 已加，老库未迁移）；
    2. `country` 仍是 NOT NULL（区域层要写 country=NULL，必须放宽为可空）。
    """
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='product'").fetchone()
    if not row:
        return False
    info = {r[1]: r for r in db.execute("PRAGMA table_info(product)")}
    if "region" not in info:
        return True
    return bool(info["country"][3])     # notnull=1 → 需重建放宽


def build(db_path: Path) -> sqlite3.Connection:
    t0 = time.perf_counter()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path, timeout=60)
    schema_text = SCHEMA.read_text(encoding="utf-8")
    target = markets(schema_text)
    target_status = statuses(schema_text)

    # v0.4：老库必须先补 variant 新列，否则 schema.sql 里建在 salt_code 上的索引
    # 会直接报 "no such column"（CREATE TABLE IF NOT EXISTS 不会改已存在的表）。
    _ensure_variant_columns(db)

    # 迁移要在 executescript(schema_text) 之前做：新版 coverage 视图引用 p.region，
    # 老库还没有 region 列时先重建 product，再执行 schema 建/刷视图。
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='product'").fetchone()
    have = markets(row[0]) if row else set()
    have_status = statuses(row[0]) if row else set()
    region_need = _product_region_needed(db)
    if row and ((target and have != target) or (target_status and have_status != target_status)
                or region_need):
        missing = ", ".join(sorted(target - have)) or "(none)"
        missing_st = ", ".join(sorted(target_status - have_status)) or "(none)"
        print(f"迁移 product 表：country {sorted(have)} → {sorted(target)}（新增 {missing}）；"
              f"status 新增 {missing_st}；region 列/country 可空: {'需要' if region_need else '已就绪'}")
        _rebuild_product(db, schema_text)

    db.executescript(schema_text)
    db.commit()
    _ensure_source_columns(db)
    _ensure_variant_columns(db)
    _ensure_indexes(db)
    print(f"init_db 完成：{db_path}（{time.perf_counter() - t0:.2f}s）")
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
