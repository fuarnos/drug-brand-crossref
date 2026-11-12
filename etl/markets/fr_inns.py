"""FR 独有 INN 补种（v0.11.5 task-6 加分项）：只补**有可核 ATC 出处**的法国常用 INN。

背景：BDPM 里有一批法国常用成分在库里没有 `substance` 行（`reports/2026-11-14-fr-quality.md` §4），
导致这些产品没有 component。本脚本把其中 **WHOCC ATC/DDD Index 能查到唯一 ATC 码** 的补进库：

| INN（英文） | ATC | 出处（WHOCC ATC/DDD Index 2026，逐条按名检索） |
|---|---|---|
| Oxomemazine | R06AD08 | https://atcddd.fhi.no/atc_ddd_index/?name=oxomemazine |
| Metopimazine | A04AD05 | https://atcddd.fhi.no/atc_ddd_index/?name=metopimazine |
| Thiocolchicoside | M03BX05 | https://atcddd.fhi.no/atc_ddd_index/?name=thiocolchicoside |
| Cyamemazine | N05AA06 | https://atcddd.fhi.no/atc_ddd_index/?name=cyamemazine |
| Josamycin | J01FA07 | https://atcddd.fhi.no/atc_ddd_index/?name=josamycin |
| Promestriene | G03CA09 | https://atcddd.fhi.no/atc_ddd_index/?name=promestriene |
| Omoconazole | D01AC13 | https://atcddd.fhi.no/atc_ddd_index/?name=omoconazole （另 G01AF16 妇科用；表只存一列，存皮肤科码，两个都记在报告） |

**没补的 3 个**（WHOCC 2026 索引按名检索 **无条目**，拿不到可核 ATC，按纪律不猜）：
`Biclotymol`、`Propericiazine`、`Bretovameran`。

写入约定（沿用仓库现状）：只插 `substance` + 一条 `variant`（`variant_id = substance_id`，
salt/hydrate/ester 空、`base_fraction=1.0`、`interchange='unknown'`）；`source_id`/`method`/`confidence`
等列留空（与库里 12,637 行现状一致），出处记在本 docstring 与报告里，不另建 `source` 行（新数据源要先过许可）。

三段式：默认 `--dry-run`（只读）；`--apply` 写库（真库需 `--allow-real`，写 manifest 供 `--rollback`）；
`--rollback` 只删本次插入的行。

用法：
    python etl/markets/fr_inns.py --dry-run --db .tmp/fr-ingest/drugs_fr_copy.db
    python etl/markets/fr_inns.py --apply --db .tmp/fr-ingest/drugs_fr_copy.db --manifest .tmp/fr-inns/manifest.json
    python etl/markets/fr_inns.py --apply --allow-real --db data/drugs.db --manifest .tmp/fr-inns/manifest_real.json
    python etl/markets/fr_inns.py --rollback --allow-real --db data/drugs.db --manifest .tmp/fr-inns/manifest_real.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REAL_DB = ROOT / "data" / "drugs.db"

# (substance_id, inn_en, atc)
FR_INNS: list[tuple[str, str, str]] = [
    ("oxomemazine", "Oxomemazine", "R06AD08"),
    ("metopimazine", "Metopimazine", "A04AD05"),
    ("thiocolchicoside", "Thiocolchicoside", "M03BX05"),
    ("cyamemazine", "Cyamemazine", "N05AA06"),
    ("josamycin", "Josamycin", "J01FA07"),
    ("promestriene", "Promestriene", "G03CA09"),
    ("omoconazole", "Omoconazole", "D01AC13"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_ro(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    return db


def open_rw(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=180)
    db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = sqlite3.Row
    return db


def guard_real(db_path: Path, action: str, allow_real: bool) -> None:
    """真库保护（沿用 etl/markets/fr.py / etl/ingest_eu.py 的写法）。"""
    try:
        is_real = db_path.resolve() == REAL_DB.resolve()
    except OSError:
        is_real = False
    if is_real and not allow_real:
        raise SystemExit(f"拒绝在真库 {db_path} 执行 {action}：需要 --allow-real（并已备份）。")
    if is_real:
        print(f"!! 警告：正在对真实库 {db_path} 执行 {action}（--allow-real）")


def plan(db: sqlite3.Connection) -> list[dict]:
    """逐条判断：已存在（按 id 或 inn_en）就跳过，否则给出待插入行。"""
    out: list[dict] = []
    for sid, inn_en, atc in FR_INNS:
        row = db.execute(
            "SELECT substance_id, inn_en, atc FROM substance"
            " WHERE substance_id=? OR inn_en=?", (sid, inn_en)).fetchone()
        has_variant = db.execute("SELECT 1 FROM variant WHERE substance_id=?", (sid,)).fetchone()
        out.append({"substance_id": sid, "inn_en": inn_en, "atc": atc,
                    "exists": row is not None,
                    "existing": dict(row) if row else None,
                    "has_variant": has_variant is not None})
    return out


def cmd_dry_run(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    if not db_path.exists():
        raise SystemExit(f"库不存在：{db_path}")
    db = open_ro(db_path)
    try:
        rows = plan(db)
    finally:
        db.close()
    print(f"=== FR 独有 INN 补种 dry-run（只读：{db_path}）===")
    for r in rows:
        state = "已存在→跳过" if r["exists"] else ("将新增（variant " + ("有" if r["has_variant"] else "无") + "）")
        print(f"  {r['substance_id']:<18} {r['inn_en']:<18} {r['atc']:<8} {state}")
    new = [r for r in rows if not r["exists"]]
    print(f"  计划新增 substance {len(new)} 个 · variant {sum(1 for r in new if not r['has_variant'])} 条")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    guard_real(db_path, "apply", args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    db = open_rw(db_path)
    inserted_sub: list[str] = []
    inserted_var: list[str] = []
    counts_before = {"substance": db.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
                     "variant": db.execute("SELECT COUNT(*) FROM variant").fetchone()[0]}
    try:
        db.execute("BEGIN IMMEDIATE")
        for r in plan(db):
            if r["exists"]:
                continue
            db.execute("INSERT INTO substance (substance_id, inn_en, atc) VALUES (?,?,?)",
                       (r["substance_id"], r["inn_en"], r["atc"]))
            inserted_sub.append(r["substance_id"])
            if not r["has_variant"]:
                db.execute(
                    "INSERT INTO variant (variant_id, substance_id, salt, hydrate, ester,"
                    " base_fraction, interchange, interchange_note, salt_code, strength_basis)"
                    " VALUES (?,?,'','','',1.0,'unknown','','','unknown')",
                    (r["substance_id"], r["substance_id"]))
                inserted_var.append(r["substance_id"])
        db.commit()
        counts_after = {"substance": db.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
                        "variant": db.execute("SELECT COUNT(*) FROM variant").fetchone()[0]}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    manifest = {
        "tool": "etl/markets/fr_inns.py",
        "db": str(db_path),
        "db_is_real": db_path.resolve() == REAL_DB.resolve(),
        "created_at": _now(),
        "source": "WHOCC ATC/DDD Index 2026（按 INN 名逐条检索；URL 见脚本 docstring）",
        "inns": [{"substance_id": s, "inn_en": i, "atc": a} for s, i, a in FR_INNS],
        "inserted_substances": inserted_sub,
        "inserted_variants": inserted_var,
        "counts_before": counts_before,
        "counts_after": counts_after,
        "rollback_hint": ("python etl/markets/fr_inns.py --rollback --allow-real --db <库> "
                          "--manifest <本文件>"),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== FR 独有 INN 补种完成 ===")
    print(json.dumps({"inserted_substances": inserted_sub, "inserted_variants": inserted_var,
                      "counts_before": counts_before, "counts_after": counts_after},
                     ensure_ascii=False, indent=1))
    print(f"  撤销清单 {manifest_path}")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    guard_real(db_path, "rollback", args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = open_rw(db_path)
    removed = {"substance": 0, "variant": 0}
    try:
        db.execute("BEGIN IMMEDIATE")
        for sid in data.get("inserted_variants") or []:
            removed["variant"] += db.execute(
                "DELETE FROM variant WHERE variant_id=? AND substance_id=?", (sid, sid)).rowcount
        for sid in data.get("inserted_substances") or []:
            left = db.execute("SELECT 1 FROM variant WHERE substance_id=?", (sid,)).fetchone()
            if left:
                print(f"  !! {sid} 还有 variant 行，跳过删除（可能被其它数据引用）")
                continue
            removed["substance"] += db.execute(
                "DELETE FROM substance WHERE substance_id=?", (sid,)).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"=== 回滚完成 ===")
    print(json.dumps({"removed": removed,
                      "counts_now": {"substance": None, "variant": None}},
                     ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="FR 独有 INN 补种：只补 WHOCC ATC 索引里能查到唯一 ATC 码的法国常用 INN。")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只读，打印计划（默认）")
    mode.add_argument("--apply", action="store_true", help="事务写库（幂等：已存在则跳过）")
    mode.add_argument("--rollback", action="store_true", help="按 manifest 撤销本次插入")
    ap.add_argument("--db", type=Path, default=ROOT / ".tmp" / "fr-ingest" / "drugs_fr_copy.db",
                    help="目标库（默认 .tmp 副本；真库需 --allow-real + 备份）")
    ap.add_argument("--manifest", type=Path,
                    default=ROOT / ".tmp" / "fr-inns" / "manifest.json",
                    help="撤销清单路径（apply 写、rollback 读）")
    ap.add_argument("--allow-real", action="store_true", help="允许对真库 data/drugs.db 执行 apply/rollback")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply:
        return cmd_apply(args)
    if args.rollback:
        return cmd_rollback(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
