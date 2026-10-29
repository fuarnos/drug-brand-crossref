# -*- coding: utf-8 -*-
"""数据溯源写入口（task-26）：给 substance / brand_family 打 source/method/confidence/decided_at。

口径（Lead 2026-10-30 批准）
--------------------------
- 列：`source_id` / `method ∈ {rule, multi-source, editorial, imported}` /
  `confidence ∈ {high, medium, low, unknown}` / `decided_at`（ISO8601 UTC，决策时间）。
- **空才写**：只在目标行四列全空时写入；已有值时按强度提升：
  `editorial(4) > multi-source(3) > rule(2) > imported(1)`，**同级不覆盖**（保留最早决策）。
- **旧行不伪造**：迁移前的行保持 NULL＝「来源未记录」；唯一例外是 `brand_family`
  （该表 100% 来自人工种子 `data/seed_families.py`，来源可确证，`--backfill` 标 editorial）。
- 本脚本**不写 data/drugs.db 的其它字段**、不建表、不改 schema。

用法
----
    python etl/provenance.py --status                    # 覆盖率（NULL vs 已填）
    python etl/provenance.py --backfill                  # 只回填 brand_family（旧 substance 保持 NULL）
    python etl/provenance.py --backfill --apply          # 真正写入（默认 dry-run）
    python etl/provenance.py --mark atorvastatin --source manual_seed --method editorial \
        --confidence high                               # 单条标记（dry-run；加 --apply 写入）

供 ETL 复用的接口：

    from provenance import mark_substance, mark_family
    mark_substance(db, sid, source_id="nhsa", method="imported", confidence="high")
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DEFAULT = ROOT / "data" / "drugs.db"
SEED_FAMILIES = ROOT / "data" / "seed_families.py"

METHODS = ("rule", "multi-source", "editorial", "imported")
CONFIDENCE = ("high", "medium", "low", "unknown")
RANK = {"imported": 1, "rule": 2, "multi-source": 3, "editorial": 4}
COLUMNS = ("source_id", "method", "confidence", "decided_at")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _decide(cur: tuple, method: str, source_id: str, confidence: str,
            decided_at: str | None) -> dict | None:
    """返回要更新的字段 dict；None 表示不写（已有更强/同级决策，或参数不合法）。"""
    if method not in METHODS:
        raise ValueError(f"method 必须是 {METHODS}，收到 {method!r}")
    if confidence not in CONFIDENCE:
        raise ValueError(f"confidence 必须是 {CONFIDENCE}，收到 {confidence!r}")
    cur_source, cur_method, cur_conf, cur_at = cur
    if cur_method in RANK and RANK[method] <= RANK[cur_method]:
        return None                       # 同级/更弱：不覆盖（保留最早决策）
    return {"source_id": source_id, "method": method, "confidence": confidence,
            "decided_at": decided_at or _now_iso()}


def mark_substance(con: sqlite3.Connection, substance_id: str, source_id: str,
                   method: str, confidence: str, decided_at: str | None = None) -> bool:
    """按强度提升写 substance 溯源；返回是否写入。"""
    row = con.execute(
        f"SELECT {', '.join(COLUMNS)} FROM substance WHERE substance_id=?",
        (substance_id,)).fetchone()
    if row is None:
        raise KeyError(f"substance 不存在：{substance_id}")
    upd = _decide(tuple(row), method, source_id, confidence, decided_at)
    if not upd:
        return False
    con.execute(
        "UPDATE substance SET source_id=?, method=?, confidence=?, decided_at=?"
        " WHERE substance_id=?", (*upd.values(), substance_id))
    return True


def mark_family(con: sqlite3.Connection, family_id: str, source_id: str,
                method: str, confidence: str, decided_at: str | None = None) -> bool:
    """按强度提升写 brand_family 溯源；返回是否写入。"""
    row = con.execute(
        f"SELECT {', '.join(COLUMNS)} FROM brand_family WHERE family_id=?",
        (family_id,)).fetchone()
    if row is None:
        raise KeyError(f"brand_family 不存在：{family_id}")
    upd = _decide(tuple(row), method, source_id, confidence, decided_at)
    if not upd:
        return False
    con.execute(
        "UPDATE brand_family SET source_id=?, method=?, confidence=?, decided_at=?"
        " WHERE family_id=?", (*upd.values(), family_id))
    return True


def status(con: sqlite3.Connection) -> dict:
    out = {}
    for table in ("substance", "brand_family"):
        total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        filled = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_id IS NOT NULL"
            " OR method IS NOT NULL OR confidence IS NOT NULL OR decided_at IS NOT NULL"
        ).fetchone()[0]
        by_method = dict(con.execute(
            f"SELECT COALESCE(method,'<NULL>'), COUNT(*) FROM {table} GROUP BY 1").fetchall())
        out[table] = {"total": total, "filled": filled, "null": total - filled,
                      "by_method": by_method}
    return out


def _seed_mtime_iso() -> str | None:
    if not SEED_FAMILIES.exists():
        return None
    ts = datetime.fromtimestamp(SEED_FAMILIES.stat().st_mtime, tz=timezone.utc)
    return ts.isoformat(timespec="seconds").replace("+00:00", "Z")


def backfill_families(con: sqlite3.Connection, dry_run: bool) -> list[dict]:
    """brand_family：人工种子表 → editorial / manual_seed / high。"""
    decided = _seed_mtime_iso() or _now_iso()
    plans = []
    for (fid,) in con.execute("SELECT family_id FROM brand_family ORDER BY family_id").fetchall():
        row = con.execute(
            f"SELECT {', '.join(COLUMNS)} FROM brand_family WHERE family_id=?", (fid,)).fetchone()
        upd = _decide(tuple(row), "editorial", "manual_seed", "high", decided)
        if upd:
            plans.append({"table": "brand_family", "id": fid, **upd})
            if not dry_run:
                con.execute(
                    "UPDATE brand_family SET source_id=?, method=?, confidence=?, decided_at=?"
                    " WHERE family_id=?", (*upd.values(), fid))
    if not dry_run:
        con.commit()
    return plans


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="数据溯源写入口（substance / brand_family）")
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--status", action="store_true", help="打印覆盖率")
    ap.add_argument("--backfill", action="store_true",
                    help="回填 brand_family（旧 substance 保持 NULL，不伪造）")
    ap.add_argument("--apply", action="store_true", help="真正写入（默认 dry-run）")
    ap.add_argument("--mark", metavar="SUBSTANCE_ID", help="给单个 substance 打标记")
    ap.add_argument("--source", default="manual_seed")
    ap.add_argument("--method", default="editorial", choices=METHODS)
    ap.add_argument("--confidence", default="high", choices=CONFIDENCE)
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")
    con = sqlite3.connect(db_path, timeout=120)
    try:
        if args.status or not (args.backfill or args.mark):
            st = status(con)
            print(f"DB: {db_path}")
            for table, s in st.items():
                print(f"  {table:<13} 总 {s['total']:,}｜已标记 {s['filled']:,}｜NULL {s['null']:,}"
                      f"｜method 分布 {s['by_method']}")
            return 0

        if args.mark:
            try:
                ok = mark_substance(con, args.mark, args.source, args.method,
                                    args.confidence)
            except KeyError as e:
                raise SystemExit(str(e))
            print(f"substance {args.mark}: {'写入' if ok else '跳过（已有同级/更强记录）'}"
                  f"{'' if args.apply else '（dry-run，未提交）'}")
            if args.apply:
                con.commit()
            else:
                con.rollback()
            return 0

        plans = backfill_families(con, dry_run=not args.apply)
        print(f"brand_family 回填计划：{len(plans)} 行"
              f"{'（已写入）' if args.apply else '（dry-run，未提交）'}")
        for p in plans:
            print(f"  {p['id']}: {p['source_id']} / {p['method']} / {p['confidence']}"
                  f" / {p['decided_at']}")
        if not plans:
            print("  无需回填（已有记录或表为空）")
        print("  注：substance 旧行按 Lead 决定保持 NULL（不伪造来源）；新数据由各 ingest 调用 "
              "mark_substance() 写入。")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
