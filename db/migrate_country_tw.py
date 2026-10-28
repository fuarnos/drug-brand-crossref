"""TW 市场 schema 迁移：给 product.country CHECK 增加 'TW'（默认 dry-run）。

背景
----
SQLite 不能改 CHECK 约束，只能「重建表 + 搬数据」。`db/init_db.py` 已在每次启动时按
`db/schema.sql` 的枚举自动迁移；本脚本是**独立、可回滚、可计时**的迁移工具，用于：
  - 迁移前 dry-run 审计（当前枚举、行数、索引/视图/外键、磁盘占用、预计动作）；
  - 在 DB 副本上实测迁移耗时与完整性（行数/内容 hash/索引/视图/FK/quick_check 不变）；
  - 生成撤销清单，支持 `--rollback` 重建回旧枚举（要求库里没有 TW 行）。

安全
----
- `--apply/--rollback` 默认**拒绝写 data/drugs.db**（本任务要求只在副本验证）；
  Lead 批准后加 `--allow-real`（并先用 --backup-dir 备份）。
- 迁移期间用 `BEGIN IMMEDIATE` 独占写锁，409k 行 product 表重建大约数秒；
  其它进程不要同时读写该库；建议先停 build/ingest。
- 只重建 product 表；product_component / product_name / corroboration 的外键不动
  （legacy_alter_table=ON 防止把子表 FK 改指向 product_old）；视图仍按名字引用 product。

用法：
    python db/migrate_country_tw.py --db .tmp/tw-schema/drugs-test.db            # dry-run
    python db/migrate_country_tw.py --db ... --apply [--backup-dir DIR]
    python db/migrate_country_tw.py --db ... --rollback [--manifest PATH]
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
DEFAULT_MANIFEST = ROOT / ".tmp" / "tw-schema" / "country_tw_manifest.json"
NEW_MARKET = "TW"

CHECK_RE = re.compile(r"country\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(country\s+IN\s*\(([^)]*)\)\)",
                      re.I)
PRODUCT_DDL_RE = re.compile(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?product\s*\(", re.I)


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


def product_ddl(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='product'").fetchone()
    if not row:
        raise SystemExit("找不到 product 表")
    return row["sql"]


def ddl_markets(ddl: str) -> list[str]:
    m = CHECK_RE.search(ddl or "")
    if not m:
        return []
    return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]


def ddl_with_markets(ddl: str, markets: list[str]) -> str:
    repl = "'" + "', '".join(markets) + "'"
    new, n = CHECK_RE.subn("country TEXT NOT NULL CHECK (country IN (%s))" % repl, ddl, count=1)
    if n != 1:
        raise SystemExit("product DDL 里找不到 country CHECK，无法重建")
    return new


def recreate_ddl(ddl: str) -> str:
    """把 sqlite_master 里的 CREATE TABLE product 改成可重放形式（去掉 IF NOT EXISTS 也行）。"""
    return re.sub(r"^CREATE TABLE\s+(?:IF NOT EXISTS\s+)?product\s*\(",
                  "CREATE TABLE product (", ddl, count=1, flags=re.I)


def product_indexes(con: sqlite3.Connection) -> list[str]:
    return [r["sql"] for r in con.execute(
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
        "fk_violations": len(con.execute("PRAGMA foreign_key_check").fetchall()),
        "quick_check": con.execute("PRAGMA quick_check").fetchone()[0],
        "db_size": None,
    }


def verify(con: sqlite3.Connection, before: dict, target_markets: list[str],
           label: str) -> dict:
    after = snapshot(con)
    problems: list[str] = []
    if after["product_rows"] != before["product_rows"]:
        problems.append("行数 %d → %d" % (before["product_rows"], after["product_rows"]))
    if after["product_hash"] != before["product_hash"]:
        problems.append("product_id 内容 hash 变化")
    if after["country_counts"] != before["country_counts"]:
        problems.append("country 分布变化: %s → %s" % (before["country_counts"], after["country_counts"]))
    if [i for i in after["indexes"]] != [i for i in before["indexes"]]:
        problems.append("product 索引定义变化:\n  before=%s\n  after=%s" % (
            before["indexes"], after["indexes"]))
    if after["views"] != before["views"]:
        problems.append("视图集合变化")
    for v in after["views"]:
        try:
            con.execute("SELECT 1 FROM %s LIMIT 1" % v).fetchone()
        except sqlite3.Error as e:  # noqa: PERF203
            problems.append("视图 %s 不可查: %s" % (v, e))
    if after["fk_violations"] != 0:
        problems.append("foreign_key_check %d 条违规" % after["fk_violations"])
    if after["quick_check"] != "ok":
        problems.append("quick_check=%s" % after["quick_check"])
    if sorted(after["markets"]) != sorted(target_markets):
        problems.append("country 枚举 %s ≠ 目标 %s" % (after["markets"], target_markets))
    if problems:
        raise SystemExit("[%s] 校验失败：\n  - %s" % (label, "\n  - ".join(problems)))
    return after


def rebuild(con: sqlite3.Connection, target_markets: list[str]) -> None:
    """重建 product 表到目标 country 枚举，保留数据与 product 索引。"""
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
    ap = argparse.ArgumentParser(description="product.country CHECK 增加 TW（默认 dry-run）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--allow-real", action="store_true",
                    help="允许写 data/drugs.db（默认禁止；Lead 批准正式迁移时使用）")
    ap.add_argument("--backup-dir", type=Path, default=None,
                    help="apply 前把 DB 复制到该目录（建议真实库必填）")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--vacuum", action="store_true",
                    help="迁移/回滚成功后跑 VACUUM 回收旧表页（实测 409k 行约 4s，DB 325→453→325 MB）")
    args = ap.parse_args()
    if sum([args.apply, args.rollback, args.dry_run]) > 1:
        ap.error("--apply / --dry-run / --rollback 互斥")
    real = DEFAULT_DB.resolve()
    if (args.apply or args.rollback) and args.db.resolve() == real and not args.allow_real:
        raise SystemExit("拒绝写 data/drugs.db：本任务要求只在副本验证；"
                         "Lead 批准后加 --allow-real（建议同时 --backup-dir）。")
    readonly = not (args.apply or args.rollback)
    con = connect(args.db, readonly=readonly)
    current = ddl_markets(product_ddl(con))
    before = snapshot(con)
    before["db_size"] = args.db.stat().st_size
    print("=== TW country 迁移 [%s] ===" % (
        "apply" if args.apply else ("rollback" if args.rollback else "dry-run")))
    print("db:", args.db, "| size:", "%.1f MB" % (before["db_size"] / 1e6))
    print("当前 country 枚举:", current)
    print("product 行数: %d | 分布: %s" % (before["product_rows"], before["country_counts"]))
    print("product 索引:", before["indexes"])
    print("视图:", before["views"], "| FK 违规:", before["fk_violations"], "| quick_check:", before["quick_check"])

    if args.rollback:
        if not args.manifest.exists():
            raise SystemExit(f"找不到迁移清单: {args.manifest}（无法确定回滚目标枚举）")
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        target = data["before"]["markets"]
        print("回滚目标枚举:", target)
        tw_rows = con.execute("SELECT COUNT(*) FROM product WHERE country=?", (NEW_MARKET,)).fetchone()[0]
        if tw_rows:
            con.close()
            raise SystemExit(f"库里有 {tw_rows} 条 TW 产品，拒绝回滚（先迁走/删除 TW 数据）")
        t0 = time.perf_counter()
        rebuild(con, target)
        elapsed = time.perf_counter() - t0
        after = con.json if False else None  # noqa: F841
        after = snapshot(con)
        after["db_size"] = args.db.stat().st_size
        verify(con, before, target, "rollback")
        if after["product_hash"] != data["before"]["product_hash"]:
            raise SystemExit("回滚后内容 hash 与迁移前不一致")
        if args.vacuum:
            t_v = time.perf_counter()
            con.execute("VACUUM")
            print("VACUUM 完成：%.2fs，DB %.1f MB（回收旧页）" % (
                time.perf_counter() - t_v, args.db.stat().st_size / 1e6))
        data["rolled_back_at"] = now()
        data["rollback_seconds"] = round(elapsed, 2)
        args.manifest.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("回滚完成：%.2fs；行数/hash/索引/视图/FK/quick_check 均一致" % elapsed)
        print("→", args.manifest.relative_to(ROOT) if args.manifest.is_relative_to(ROOT) else args.manifest)
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
    if args.dry_run or not args.apply:
        print("\n[dry-run] 将执行：")
        print("  1) 备份（如指定）→ 2) BEGIN IMMEDIATE + RENAME product→product_old")
        print("  3) 用新 CHECK 重建 product（%d 行 INSERT）→ 4) 重建 product 索引 → DROP 旧表"
              % before["product_rows"])
        print("  5) 校验 行数/hash/索引/视图/FK/quick_check → 6) 生成撤销清单")
        print("实测：重建约 2–9s（init_db 8.8s / migrate 2.2s，取决于缓存与磁盘）；"
              "不 VACUUM 则 DB 文件 +~128MB，--vacuum 回收约 4s（副本实测见 reports/tw-country-migration.md）")
        print("（未写库；正式执行用 --apply --db <副本> 或 Lead 加 --allow-real）")
        con.close()
        return 0

    # apply
    if args.backup_dir:
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = args.backup_dir / (
            "%s.before-tw-%s.db" % (args.db.stem, datetime.now().strftime("%Y%m%d-%H%M%S")))
        t_b = time.perf_counter()
        shutil.copy2(args.db, backup)
        print("已备份: %s（%.1fs，%.1f MB）" % (
            backup, time.perf_counter() - t_b, backup.stat().st_size / 1e6))
    t0 = time.perf_counter()
    rebuild(con, target)
    elapsed = time.perf_counter() - t0
    after = snapshot(con)
    after["db_size"] = args.db.stat().st_size
    verify(con, before, target, "apply")
    if args.vacuum:
        t_v = time.perf_counter()
        con.execute("VACUUM")
        print("VACUUM 完成：%.2fs，DB %.1f MB（回收旧表页）" % (
            time.perf_counter() - t_v, args.db.stat().st_size / 1e6))
        after["db_size"] = args.db.stat().st_size
    manifest = {
        "tool": "db/migrate_country_tw.py", "db": str(args.db.resolve()),
        "created_at": now(), "market_added": NEW_MARKET,
        "before": before, "after": after,
        "apply_seconds": round(elapsed, 2),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("迁移完成：%.2fs | 行数 %d（不变）| hash 一致 | 索引 %d | 视图 %d | FK 0 | quick_check ok" % (
        elapsed, after["product_rows"], len(after["indexes"]), len(after["views"])))
    print("新 country 枚举:", after["markets"])
    print("DB size: %.1f MB → %.1f MB（峰值约 +1 份 product 表）" % (
        before["db_size"] / 1e6, after["db_size"] / 1e6))
    print("撤销清单:", args.manifest)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
