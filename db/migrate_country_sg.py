# -*- coding: utf-8 -*-
"""把 'SG' 加入 product.country 的 CHECK 枚舉（只改 DB 副本；真實庫需 --allow-real）。

背景：schema 的 country CHECK 是白名單，新增國家必須重建 product 表（同 db/init_db.py
的國家擴展做法）。本腳本冪等：已含 SG 則直接退出。只重建 product 表，保留 region 列、
兩者互斥 CHECK、全部列與資料，並重建 product 上的索引。

用法：
    python db/migrate_country_sg.py --db .tmp/sg-ingest/test.db            # 副本
    python db/migrate_country_sg.py --db .tmp/sg-ingest/test.db --dry-run
    python db/migrate_country_sg.py --db data/drugs.db --allow-real        # 真實庫（需批准）
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "drugs.db"
RE_COUNTRY_IN = re.compile(r"country\s+IN\s*\(([^)]*)\)")


def _guard_real(db_path: Path, allow_real: bool) -> None:
    if db_path.resolve() == DEFAULT_DB.resolve() and not allow_real:
        raise SystemExit(
            f"拒絕在真實庫 {db_path} 重建 product 表：本任務只允許 DB 副本。\n"
            "確需真實庫時加 --allow-real（先備份 data/drugs.db）。")


def add_sg_to_country(sql: str) -> str:
    """在 country IN (...) 的白名單裡插入 'SG'。"""
    m = RE_COUNTRY_IN.search(sql)
    if not m:
        raise SystemExit("找不到 country IN (...) 白名單，schema 可能已變更，拒絕盲改。")
    items = [x.strip() for x in m.group(1).split(",") if x.strip()]
    if any(x.strip("'\" ") == "SG" for x in items):
        return sql
    items.append("'SG'")
    new_list = ", ".join(items)
    return sql[:m.start(1)] + new_list + sql[m.end(1):]


def migrate(db_path: Path, dry_run: bool = False) -> dict:
    db = sqlite3.connect(db_path, timeout=120, isolation_level=None)
    try:
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='product'").fetchone()
        if not row or not row[0]:
            raise SystemExit("找不到 product 表")
        old_sql = row[0]
        n_before = db.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        indexes = [r[0] for r in db.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='product' "
            "AND sql IS NOT NULL")]
        if "country IN" not in old_sql:
            raise SystemExit("product.country 不是 CHECK 白名單，拒絕盲改。")
        new_sql = add_sg_to_country(old_sql)
        already = new_sql == old_sql
        report = {"db": str(db_path), "dry_run": dry_run, "already": already,
                  "products": n_before, "indexes": len(indexes)}
        if already:
            print(f"product.country 已含 SG，無需遷移（{db_path}，{n_before:,} 行）")
            return report
        if dry_run:
            print(f"[dry-run] {db_path}：{n_before:,} 行；將重建 product 表，"
                  f"country 白名單加 'SG'，重建 {len(indexes)} 個索引")
            print("old:", RE_COUNTRY_IN.search(old_sql).group(0))
            print("new:", RE_COUNTRY_IN.search(new_sql).group(0))
            return report
        # 重建表（同 init_db 國家擴展做法：FK off + legacy alter 避免改寫子表 FK）
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("PRAGMA legacy_alter_table=ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("ALTER TABLE product RENAME TO product_sg_old")
            db.execute(new_sql)
            db.execute("INSERT INTO product SELECT * FROM product_sg_old")
            db.execute("DROP TABLE product_sg_old")
            for sql in indexes:
                db.execute(sql)
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        db.execute("PRAGMA legacy_alter_table=OFF")
        db.execute("PRAGMA foreign_keys=ON")
        n_after = db.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        integ = db.execute("PRAGMA integrity_check").fetchone()[0]
        fk = db.execute("PRAGMA foreign_key_check").fetchall()
        report.update({"products_after": n_after, "integrity": integ,
                       "fk_violations": len(fk),
                       "country_has_sg": "'SG'" in db.execute(
                           "SELECT sql FROM sqlite_master WHERE name='product'").fetchone()[0]})
        print(f"遷移完成：{db_path}｜product {n_before:,} → {n_after:,} 行｜"
              f"integrity={integ}｜FK 違規={len(fk)}｜country 含 SG="
              f"{report['country_has_sg']}")
        if n_after != n_before:
            raise SystemExit("重建後行數不一致，請檢查！")
        return report
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="product.country CHECK 加入 SG（副本用）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-real", action="store_true",
                    help="允許改 data/drugs.db（需備份）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON 結果")
    args = ap.parse_args(argv)
    if not args.db.exists():
        raise SystemExit(f"DB 不存在：{args.db}")
    _guard_real(args.db, args.allow_real)
    report = migrate(args.db, dry_run=args.dry_run)
    if args.json:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
