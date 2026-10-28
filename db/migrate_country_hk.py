"""HK country CHECK 迁移：给 product.country 枚举加 'HK'（默认 dry-run，副本验证用）。

背景
----
香港衞生署「註冊藥劑製品名單」要入库，但 `product.country` CHECK 只有
US/GB/CN/ES/MX/AU/CA/TW。SQLite 改不了 CHECK，只能重建 product 表；本脚本是
`db/migrate_country_tw.py` 的同构版本（task-88）：

    python db/migrate_country_hk.py --db .tmp/hk-ingest/drugs-hk.db            # dry-run
    python db/migrate_country_hk.py --db ... --apply [--backup-dir DIR] [--vacuum]
    python db/migrate_country_hk.py --db ... --rollback [--manifest PATH]

安全
----
- `--apply/--rollback` 默认**拒绝写 data/drugs.db**（需 `--allow-real`；本任务只在副本跑）。
- 只重建 product 表：数据原样搬、保留 product 索引；子表 FK/视图不动
  （`legacy_alter_table=ON`）；`BEGIN IMMEDIATE` 独占写锁。
- 校验：行数 / product_id 内容 hash / country 分布 / 索引 / 视图可查 / FK / quick_check。
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
DEFAULT_DB = ROOT / "data" / "drugs.db"
DEFAULT_MANIFEST = ROOT / ".tmp" / "hk-ingest" / "country_hk_manifest.json"
NEW_MARKET = "HK"

CHECK_RE = re.compile(r"country\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(country\s+IN\s*\(([^)]*)\)\)", re.I)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=60)
    con = sqlite3.connect(db_path, timeout=120)
    con.row_factory = sqlite3.Row
    return con


def product_ddl(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='product'").fetchone()
    if not row:
        raise SystemExit("找不到 product 表")
    return row[0]


def ddl_markets(ddl: str) -> list[str]:
    m = CHECK_RE.search(ddl or "")
    return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()] if m else []


def ddl_with_markets(ddl: str, markets: list[str]) -> str:
    repl = "'" + "', '".join(markets) + "'"
    new, n = CHECK_RE.subn("country TEXT NOT NULL CHECK (country IN (%s))" % repl, ddl, count=1)
    if n != 1:
        raise SystemExit("product DDL 里找不到 country CHECK")
    return new


def recreate_ddl(ddl: str) -> str:
    return re.sub(r"^CREATE TABLE\s+(?:IF NOT EXISTS\s+)?product\s*\(",
                  "CREATE TABLE product (", ddl, count=1, flags=re.I)


def product_indexes(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='product'"
        " AND sql IS NOT NULL ORDER BY name")]


def content_hash(con: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    for r in con.execute("SELECT product_id FROM product ORDER BY product_id"):
        h.update(r[0].encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def snapshot(con: sqlite3.Connection) -> dict:
    return {
        "product_rows": con.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "product_hash": content_hash(con),
        "country_counts": {r[0]: r[1] for r in con.execute(
            "SELECT country, COUNT(*) FROM product GROUP BY country ORDER BY country")},
        "markets": ddl_markets(product_ddl(con)),
        "indexes": sorted(product_indexes(con)),
        "views": sorted(r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")),
    }


def verify(con: sqlite3.Connection, before: dict, target_markets: list[str], label: str) -> dict:
    after = snapshot(con)
    problems: list[str] = []
    if after["product_rows"] != before["product_rows"]:
        problems.append("行数 %d → %d" % (before["product_rows"], after["product_rows"]))
    if after["product_hash"] != before["product_hash"]:
        problems.append("product_id 内容 hash 变化")
    if after["country_counts"] != before["country_counts"]:
        problems.append("country 分布变化")
    if after["indexes"] != before["indexes"]:
        problems.append("product 索引定义变化")
    if after["views"] != before["views"]:
        problems.append("视图集合变化")
    for v in after["views"]:
        try:
            con.execute("SELECT 1 FROM %s LIMIT 1" % v).fetchone()
        except sqlite3.Error as e:  # noqa: PERF203
            problems.append("视图 %s 不可查: %s" % (v, e))
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        problems.append("foreign_key_check %d 条违规" % len(fk))
    quick = con.execute("PRAGMA quick_check").fetchone()[0]
    if quick != "ok":
        problems.append("quick_check=%s" % quick)
    if sorted(after["markets"]) != sorted(target_markets):
        problems.append("country 枚举 %s ≠ 目标 %s" % (after["markets"], target_markets))
    if problems:
        raise SystemExit("[%s] 校验失败：\n  - %s" % (label, "\n  - ".join(problems)))
    return after


def rebuild(con: sqlite3.Connection, target_markets: list[str]) -> None:
    old_ddl = product_ddl(con)
    new_ddl = recreate_ddl(ddl_with_markets(old_ddl, target_markets))
    index_ddls = product_indexes(con)
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
            raise SystemExit("新旧表没有公共列")
        col_sql = ", ".join(cols)
        con.execute("INSERT INTO product (%s) SELECT %s FROM product_old" % (col_sql, col_sql))
        con.execute("DROP TABLE product_old")
        for one in index_ddls:
            con.execute(one)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.execute("PRAGMA legacy_alter_table=OFF")
        con.executescript("PRAGMA foreign_keys=ON;")


def main() -> int:
    ap = argparse.ArgumentParser(description="product.country CHECK 增加 HK（默认 dry-run）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--allow-real", action="store_true")
    ap.add_argument("--backup-dir", type=Path, default=None)
    ap.add_argument("--vacuum", action="store_true")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = ap.parse_args()
    if sum([args.apply, args.rollback, args.dry_run]) > 1:
        ap.error("--apply / --dry-run / --rollback 互斥")
    real = DEFAULT_DB.resolve()
    if (args.apply or args.rollback) and args.db.resolve() == real and not args.allow_real:
        raise SystemExit("拒绝写 data/drugs.db：本任务只在副本验证；Lead 批准后加 --allow-real。")
    con = connect(args.db, readonly=not (args.apply or args.rollback))
    current = ddl_markets(product_ddl(con))
    before = snapshot(con)
    before["db_size"] = args.db.stat().st_size
    print("=== HK country 迁移 [%s] ===" % (
        "apply" if args.apply else ("rollback" if args.rollback else "dry-run")))
    print("db:", args.db, "| size: %.1f MB" % (before["db_size"] / 1e6))
    print("当前 country 枚举:", current, "| product 行数:", before["product_rows"])
    print("分布:", before["country_counts"], "| 索引:", before["indexes"], "| 视图:", before["views"])

    if args.rollback:
        if not args.manifest.exists():
            raise SystemExit(f"找不到迁移清单: {args.manifest}")
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        target = data["before"]["markets"]
        hk_rows = con.execute("SELECT COUNT(*) FROM product WHERE country=?", (NEW_MARKET,)).fetchone()[0]
        if hk_rows:
            con.close()
            raise SystemExit(f"库里有 {hk_rows} 条 HK 产品，拒绝回滚")
        t0 = time.perf_counter()
        rebuild(con, target)
        elapsed = time.perf_counter() - t0
        verify(con, before, target, "rollback")
        data["rolled_back_at"] = now()
        data["rollback_seconds"] = round(elapsed, 2)
        args.manifest.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("回滚完成：%.2fs；行数/hash/索引/视图/FK/quick_check 均一致" % elapsed)
        con.close()
        return 0

    target = list(current)
    if NEW_MARKET not in target:
        target.append(NEW_MARKET)
    print("目标 country 枚举:", target)
    if NEW_MARKET in current:
        print("已是目标枚举（幂等）：无需迁移。")
        con.close()
        return 0
    if not args.apply:
        print("\n[dry-run] 将重建 product 表（%d 行）加入 HK 枚举；不写库。" % before["product_rows"])
        con.close()
        return 0
    if args.backup_dir:
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = args.backup_dir / ("%s.before-hk-%s.db" % (
            args.db.stem, datetime.now().strftime("%Y%m%d-%H%M%S")))
        shutil.copy2(args.db, backup)
        print("已备份:", backup)
    t0 = time.perf_counter()
    rebuild(con, target)
    elapsed = time.perf_counter() - t0
    after = snapshot(con)
    verify(con, before, target, "apply")
    if args.vacuum:
        t_v = time.perf_counter()
        con.execute("VACUUM")
        print("VACUUM 完成：%.2fs" % (time.perf_counter() - t_v))
    after["db_size"] = args.db.stat().st_size
    manifest = {"tool": "db/migrate_country_hk.py", "db": str(args.db.resolve()),
                "created_at": now(), "market_added": NEW_MARKET,
                "before": before, "after": after, "apply_seconds": round(elapsed, 2)}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("迁移完成：%.2fs | 行数 %d（不变）| hash 一致 | 新枚举 %s" % (
        elapsed, after["product_rows"], after["markets"]))
    print("DB size: %.1f MB → %.1f MB；撤销清单 %s" % (
        before["db_size"] / 1e6, after["db_size"] / 1e6, args.manifest))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
