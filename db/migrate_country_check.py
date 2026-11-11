"""`product.country` 的 CHECK 枚举迁移：一次补齐 **FR / LV / JP / KR**（默认 dry-run）。

背景
----
SQLite 改不了 CHECK，只能「重建表 + 搬数据」。`db/init_db.py` 每次启动都会按
`db/schema.sql` 的枚举自动迁移，但需要**可回滚、可计时、可先在副本演练**的独立工具；
本脚本就是那条路径的显式版本（同 `db/migrate_country_tw.py` / `migrate_country_hk.py`）。

v0.11.3（task-56）：FR 的 ETL 已在副本跑通，但真库写不进去——country CHECK 只有 10 个市场。
按 phaseb-plan 建议**一次把 FR/LV/JP/KR 四个一起加**，省两次重建表（每次重建 40 万行表约 2–10 s）。

**枚举先行、数据后到**：本脚本只改 CHECK，不写任何产品行；四国的数据入库由各自
`etl/markets/*.py` 的 `--apply` 完成，registry（`data/markets.json`）另行按窗口启用。

安全
----
- `--apply` / `--rollback` **默认拒绝写 `data/drugs.db`**，必须显式加 `--allow-real`
  （真库窗口由 Lead 执行；建议同时 `--backup-dir data/backups`）。
- 目标枚举以 `db/schema.sql` 为**单一真相源**：脚本不硬编码市场表，schema 里有什么就迁到什么。
- 迁移用 `BEGIN IMMEDIATE` 独占写锁；期间不要有 build / ingest 在跑。
- 只重建 `product` 表；`product_component` / `product_name` / `corroboration` 的外键不动
  （`legacy_alter_table=ON` 防止把子表 FK 指向 `product_old`），视图仍按名字引用 product。
- 回滚要求库里**没有**新枚举的行（FR/LV/JP/KR）；有就拒绝，避免把数据静默丢掉。

用法
----
    python db/migrate_country_check.py --db .tmp/country-mig/drugs-copy.db            # dry-run
    python db/migrate_country_check.py --db .tmp/country-mig/drugs-copy.db --apply
    python db/migrate_country_check.py --db .tmp/country-mig/drugs-copy.db --rollback
    # 真库窗口（Lead 执行；先备份）：
    python db/migrate_country_check.py --allow-real --backup-dir data/backups --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "drugs.db"
DEFAULT_MANIFEST = ROOT / ".tmp" / "country-mig" / "country_check_manifest.json"

# 本任务新增的四个市场（仅用于「回滚前置检查」与报告；目标枚举仍从 schema.sql 读）
NEW_MARKETS = ("FR", "LV", "JP", "KR")

CHECK_RE = re.compile(
    r"country\s+TEXT\s+(?:NOT\s+NULL\s+|NULL\s+)?CHECK\s*\(\s*"
    r"(?:country\s+IS\s+NULL\s+OR\s+)?country\s+IN\s*\(([^)]*)\)\)", re.I)
PRODUCT_DDL_RE = re.compile(r"CREATE TABLE IF NOT EXISTS product\s*\(", re.I)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        con = sqlite3.connect(db_path, timeout=120)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# schema / DDL 读取
# ---------------------------------------------------------------------------
def enum_of(text: str) -> list[str]:
    """从 product 的 CREATE TABLE 里取 country 枚举（保持 schema 里的顺序）。"""
    m = CHECK_RE.search(text or "")
    if not m:
        return []
    return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]


def schema_text() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def target_markets() -> list[str]:
    """目标枚举 = schema.sql 里 product 的 country CHECK 枚举（单一真相源）。"""
    markets = enum_of(schema_text())
    if not markets:
        raise SystemExit("schema.sql 里找不到 product.country 的 CHECK 枚举")
    return markets


def product_ddl(con: sqlite3.Connection) -> str:
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='product'").fetchone()
    if not row or not row["sql"]:
        raise SystemExit("库里找不到 product 表（先用 db/init_db.py 建库）")
    return row["sql"]


def product_ddl_from_schema() -> str:
    """从 schema.sql 抽 product 的建表语句（括号配平，取到 `);`）。"""
    text = schema_text()
    m = PRODUCT_DDL_RE.search(text)
    if not m:
        raise SystemExit("schema.sql 里找不到 product 建表语句")
    i = text.find("(", m.end() - 1)
    depth = 0
    for j in range(i, len(text)):
        ch = text[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = text.find(";", j)
                return text[m.start():end + 1]
    raise SystemExit("schema.sql 的 product 建表语句括号不配平")


def product_index_ddls(con: sqlite3.Connection | None = None) -> list[str]:
    """product 上的索引：优先用「库里现存的」（保证跟当前库一致）。"""
    if con is not None:
        rows = [r["sql"] for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='product'"
            " AND sql IS NOT NULL ORDER BY name")]
        if rows:
            return rows
    text = schema_text()
    return [m.group(0) for m in re.finditer(
        r"CREATE INDEX IF NOT EXISTS \w+ ON product\s*\([^;]*\);", text, re.I | re.S)]


def recreate_ddl(ddl: str) -> str:
    """把 sqlite_master 里的 DDL 改成可重放形式（去掉 IF NOT EXISTS / 保留列定义）。"""
    return re.sub(r"^CREATE TABLE\s+(?:IF NOT EXISTS\s+)?product\s*\(",
                  "CREATE TABLE product (", ddl, count=1, flags=re.I)


# ---------------------------------------------------------------------------
# 快照 / 校验
# ---------------------------------------------------------------------------
def content_hash(con: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    for r in con.execute("SELECT product_id FROM product ORDER BY product_id"):
        h.update(r[0].encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def snapshot(con: sqlite3.Connection, db_path: Path) -> dict:
    ddl = product_ddl(con)
    return {
        "markets": enum_of(ddl),
        "product_rows": con.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "product_hash": content_hash(con),
        "country_counts": {r[0]: r[1] for r in con.execute(
            "SELECT country, COUNT(*) FROM product GROUP BY country ORDER BY country")},
        "indexes": sorted(r["sql"] for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='product'"
            " AND sql IS NOT NULL")),
        "views": sorted(r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")),
        "fk_violations": len(con.execute("PRAGMA foreign_key_check").fetchall()),
        "quick_check": con.execute("PRAGMA quick_check").fetchone()[0],
        "db_size": db_path.stat().st_size,
    }


def verify(con: sqlite3.Connection, before: dict, target: list[str], label: str,
           *, expect_hash: str | None = None) -> dict:
    after = snapshot(con, Path(con.execute("PRAGMA database_list").fetchone()[2]))
    problems: list[str] = []
    if after["product_rows"] != before["product_rows"]:
        problems.append("product 行数 %d → %d" % (before["product_rows"], after["product_rows"]))
    if after["product_hash"] != before["product_hash"]:
        problems.append("product_id 内容 hash 变化")
    if expect_hash and after["product_hash"] != expect_hash:
        problems.append("回滚后 hash 与迁移前不一致")
    if after["country_counts"] != before["country_counts"]:
        problems.append("country 分布变化：%s → %s" % (
            before["country_counts"], after["country_counts"]))
    if after["indexes"] != before["indexes"]:
        problems.append("product 索引定义变化：\n  before=%s\n  after=%s" % (
            before["indexes"], after["indexes"]))
    if after["views"] != before["views"]:
        problems.append("视图集合变化：%s → %s" % (before["views"], after["views"]))
    for v in after["views"]:
        try:
            con.execute("SELECT 1 FROM %s LIMIT 1" % v).fetchone()
        except sqlite3.Error as e:  # noqa: PERF203
            problems.append("视图 %s 不可查：%s" % (v, e))
    if after["fk_violations"]:
        problems.append("foreign_key_check 有 %d 条违规" % after["fk_violations"])
    if after["quick_check"] != "ok":
        problems.append("quick_check=%s" % after["quick_check"])
    if sorted(after["markets"]) != sorted(target):
        problems.append("country 枚举 %s ≠ 目标 %s" % (after["markets"], target))
    if problems:
        raise SystemExit("[%s] 校验失败：\n  - %s" % (label, "\n  - ".join(problems)))
    return after


# ---------------------------------------------------------------------------
# 重建
# ---------------------------------------------------------------------------
def rebuild(con: sqlite3.Connection, new_ddl: str, index_ddls: list[str]) -> float:
    """按新 DDL 重建 product（搬数据 + 重建索引），返回耗时秒。"""
    t0 = time.perf_counter()
    con.executescript("PRAGMA foreign_keys=OFF;")
    con.execute("PRAGMA legacy_alter_table=ON")
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("ALTER TABLE product RENAME TO product_old")
        con.execute(new_ddl)
        old_cols = [r[1] for r in con.execute("PRAGMA table_info(product_old)")]
        new_cols = {r[1] for r in con.execute("PRAGMA table_info(product)")}
        cols = [c for c in old_cols if c in new_cols]
        if not cols:
            raise SystemExit("新旧 product 表没有公共列，拒绝迁移")
        col_sql = ", ".join(cols)
        con.execute("INSERT INTO product (%s) SELECT %s FROM product_old" % (col_sql, col_sql))
        con.execute("DROP TABLE product_old")
        for ddl in index_ddls:          # 旧表删掉后索引名才空出来
            con.execute(ddl)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.execute("PRAGMA legacy_alter_table=OFF")
        con.executescript("PRAGMA foreign_keys=ON;")
    return time.perf_counter() - t0


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="product.country CHECK 迁移：一次补 FR/LV/JP/KR（默认 dry-run）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="执行迁移（写库）")
    g.add_argument("--dry-run", action="store_true", help="只打印计划（默认行为）")
    g.add_argument("--rollback", action="store_true", help="按 manifest 回滚到迁移前的枚举")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--allow-real", action="store_true",
                    help="允许写 data/drugs.db（默认拒绝；真库窗口由 Lead 显式开启）")
    ap.add_argument("--backup-dir", type=Path, default=None,
                    help="apply/rollback 前把 DB 复制到该目录（真库建议 data/backups）")
    ap.add_argument("--vacuum", action="store_true",
                    help="迁移后 VACUUM 回收旧表页（不 VACUUM 时 DB 会临时涨约一份 product 表）")
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"数据库不存在：{args.db}")
    real = DEFAULT_DB.resolve()
    writing = args.apply or args.rollback
    if writing and args.db.resolve() == real and not args.allow_real:
        raise SystemExit(
            "拒绝写 data/drugs.db：请先在副本上演练，真库窗口由 Lead 加 --allow-real 执行"
            "（建议同时 --backup-dir data/backups）。")

    target = target_markets()
    missing_in_schema = [m for m in NEW_MARKETS if m not in target]
    if missing_in_schema:
        raise SystemExit(f"schema.sql 的 country 枚举里缺少 {missing_in_schema}，先改 schema.sql")

    con = connect(args.db, readonly=not writing)
    try:
        ddl = product_ddl(con)
        current = enum_of(ddl)
        before = snapshot(con, args.db)
        mode = "apply" if args.apply else ("rollback" if args.rollback else "dry-run")
        print(f"=== product.country CHECK 迁移 [{mode}] ===")
        print(f"db      : {args.db}（{before['db_size'] / 1e6:.1f} MB）")
        print(f"schema  : {SCHEMA.relative_to(ROOT)}  sha256={hashlib.sha256(schema_text().encode()).hexdigest()[:16]}…")
        print(f"当前枚举: {current}")
        print(f"目标枚举: {target}")
        print(f"待新增  : {[m for m in target if m not in current] or '无（已是目标枚举）'}")
        print(f"product : {before['product_rows']:,} 行 | 分布 {before['country_counts']}")
        print(f"索引 {len(before['indexes'])} 个 | 视图 {len(before['views'])} 个 | "
              f"FK 违规 {before['fk_violations']} | quick_check {before['quick_check']}")

        # ---------------- rollback ----------------
        if args.rollback:
            if not args.manifest.exists():
                raise SystemExit(f"找不到迁移清单：{args.manifest}（无法确定回滚目标）")
            data = json.loads(args.manifest.read_text(encoding="utf-8"))
            back_target = data["before"]["markets"]
            print(f"\n回滚目标枚举: {back_target}")
            rows = con.execute(
                "SELECT country, COUNT(*) FROM product WHERE country IN (%s) GROUP BY country"
                % ",".join("?" * len(NEW_MARKETS)), NEW_MARKETS).fetchall()
            if rows:
                raise SystemExit(
                    "库里有新枚举市场的产品行 %s，拒绝回滚（先迁走/删除这些数据，"
                    "否则重建会静默丢行）" % [(r[0], r[1]) for r in rows])
            if args.backup_dir:
                args.backup_dir.mkdir(parents=True, exist_ok=True)
                bak = args.backup_dir / f"{args.db.stem}.before-rollback-{datetime.now():%Y%m%d-%H%M%S}.db"
                shutil.copy2(args.db, bak)
                print(f"已备份: {bak}")
            # 回滚目标 DDL：用 manifest 里记录的 schema 版本枚举重建（不依赖当前 schema.sql）
            new_ddl = recreate_ddl(
                CHECK_RE.sub(lambda _m: "country TEXT NULL CHECK (country IS NULL OR country IN (%s))"
                             % ("'" + "', '".join(back_target) + "'"), ddl, count=1))
            elapsed = rebuild(con, new_ddl, product_index_ddls(con) or [])
            after = verify(con, before, back_target, "rollback",
                           expect_hash=data["before"]["product_hash"])
            if args.vacuum:
                t0 = time.perf_counter()
                con.execute("VACUUM")
                print(f"VACUUM 完成：{time.perf_counter() - t0:.2f}s")
            data["rolled_back_at"] = now()
            data["rollback_seconds"] = round(elapsed, 2)
            args.manifest.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
            print(f"\n回滚完成：{elapsed:.2f}s | 行数 {after['product_rows']:,}（不变）| "
                  f"hash 与迁移前一致 | 枚举 {after['markets']}")
            return 0

        # ---------------- 幂等 / dry-run ----------------
        if sorted(current) == sorted(target):
            print("\n已是目标枚举（幂等）：无需迁移。")
            return 0
        if not args.apply:
            print("\n[dry-run] 将执行：")
            print("  1) （可要求）备份 → 2) BEGIN IMMEDIATE + RENAME product→product_old")
            print(f"  3) 用 schema.sql 的 DDL 重建 product（{before['product_rows']:,} 行搬数据）")
            print("  4) 重建 product 索引 → DROP 旧表 → 5) 校验 行数/hash/枚举/索引/视图/FK/quick_check")
            print("  6) 写撤销清单（含迁移前完整快照）")
            print("预计：重建 2–10s；不 VACUUM 时 DB 临时 +约一份 product 表。")
            print("（未写库；演练用 --apply --db <副本>，真库加 --allow-real）")
            return 0

        # ---------------- apply ----------------
        if args.backup_dir:
            args.backup_dir.mkdir(parents=True, exist_ok=True)
            bak = args.backup_dir / f"{args.db.stem}.before-country-check-{datetime.now():%Y%m%d-%H%M%S}.db"
            t0 = time.perf_counter()
            shutil.copy2(args.db, bak)
            print(f"\n已备份: {bak}（{time.perf_counter() - t0:.1f}s，"
                  f"{bak.stat().st_size / 1e6:.1f} MB）")
        new_ddl = product_ddl_from_schema()
        elapsed = rebuild(con, new_ddl, product_index_ddls(con))
        after = verify(con, before, target, "apply")
        if args.vacuum:
            t0 = time.perf_counter()
            con.execute("VACUUM")
            print(f"VACUUM 完成：{time.perf_counter() - t0:.2f}s，DB "
                  f"{args.db.stat().st_size / 1e6:.1f} MB")
            after["db_size"] = args.db.stat().st_size
        manifest = {
            "tool": "db/migrate_country_check.py",
            "db": str(args.db.resolve()),
            "created_at": now(),
            "schema_sha256": hashlib.sha256(schema_text().encode()).hexdigest(),
            "markets_added": [m for m in target if m not in current],
            "before": before,
            "after": after,
            "apply_seconds": round(elapsed, 2),
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        print(f"\n迁移完成：{elapsed:.2f}s | 行数 {after['product_rows']:,}（不变）| "
              f"hash 一致 | 枚举 {after['markets']}")
        print(f"DB size: {before['db_size'] / 1e6:.1f} MB → {after['db_size'] / 1e6:.1f} MB"
              f"（峰值约 +1 份 product 表）")
        print(f"撤销清单: {args.manifest}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
