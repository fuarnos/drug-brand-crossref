"""Q2 三条确定性合并：去性状限定词后同名同物 → re-point 到已有成分并删重复成分。

依据：`reports/2026-11-17-q2-cz-substance-classify.md` §4（写库窗口执行清单）。
三对（from → to），每对都已现查影响行数：

    acetic-acid-glacial            → acetic-acid            （6 组件 / 6 产品）
    ethinylestradiol-micronized    → ethinylestradiol       （20 / 20）
    ferrous-sulfate-dried          → ferrous-sulfate        （4 / 4）

做法（一个事务）：`UPDATE variant SET substance_id=<to>` → `DELETE FROM substance WHERE
substance_id=<from>`；不做任何剂量/等效判断，只做身份去重。

CLI：
    python db/q2_merge_substances.py --dry-run          # 默认：只查，不改
    python db/q2_merge_substances.py --apply --db <副本> --manifest <json>
    python db/q2_merge_substances.py --rollback --db <副本> --manifest <json>
真实库写需显式 `--allow-real`（先备份 data/drugs.db）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))
from _ingest_common import connect, guard_real, now, sha256_file  # noqa: E402

DEFAULT_DB = ROOT / "data" / "drugs.db"
DEFAULT_MANIFEST = ROOT / "data" / "sources" / "q2_merge_manifest_20261118.json"

# (from, to, 依据)
MERGES: tuple[tuple[str, str, str], ...] = (
    ("acetic-acid-glacial", "acetic-acid",
     "Acetic Acid Glacial = 冰醋酸（纯醋酸），与 Acetic Acid 同一物质；仅性状限定词 Glacial"),
    ("ethinylestradiol-micronized", "ethinylestradiol",
     "Ethinylestradiol Micronized = 微粉化炔雌醇，与 Ethinylestradiol 同一物质；仅粒径限定词"),
    ("ferrous-sulfate-dried", "ferrous-sulfate",
     "Ferrous Sulfate Dried = 干燥硫酸亚铁，与 Ferrous Sulfate 同一物质；仅干燥工艺限定词"),
)

SUBSTANCE_COLUMNS = ("substance_id", "inn_en", "inn_zh", "atc", "atc_name", "drug_class",
                     "ddd_value", "ddd_unit", "ddd_route", "source_id", "method",
                     "confidence", "decided_at", "name_lang")


def _row(db, sql: str, args=()):
    return db.execute(sql, args).fetchone()


def snapshot_counts(db) -> dict:
    """写前 / 写后 / 回滚后共用的计数口径。"""
    return {
        "substance": _row(db, "SELECT COUNT(*) FROM substance")[0],
        "variant": _row(db, "SELECT COUNT(*) FROM variant")[0],
        "product_component": _row(db, "SELECT COUNT(*) FROM product_component")[0],
        "product": _row(db, "SELECT COUNT(*) FROM product")[0],
        "substance_sukl_dlp": _row(
            db, "SELECT COUNT(*) FROM substance WHERE source_id='sukl_dlp'")[0],
    }


def plan(db) -> dict:
    """只读：现查三条合并的对象、影响行数与引用面。返回可写进 manifest 的结构。"""
    out = []
    for frm, to, why in MERGES:
        f = _row(db, "SELECT * FROM substance WHERE substance_id=?", (frm,))
        t = _row(db, "SELECT * FROM substance WHERE substance_id=?", (to,))
        if f is None or t is None:
            raise SystemExit(f"合并对象不存在：{frm}={f is not None} {to}={t is not None}")
        variants = [dict(r) for r in db.execute(
            "SELECT variant_id, substance_id, salt, hydrate, ester, salt_code"
            " FROM variant WHERE substance_id=?", (frm,))]
        comps = _row(db, "SELECT COUNT(*) FROM product_component pc JOIN variant v"
                         " ON v.variant_id=pc.variant_id WHERE v.substance_id=?", (frm,))[0]
        prods = _row(db, "SELECT COUNT(DISTINCT pc.product_id) FROM product_component pc"
                         " JOIN variant v ON v.variant_id=pc.variant_id WHERE v.substance_id=?",
                     (frm,))[0]
        refs = {}
        for table, col in (("nickname", "substance_id"), ("drug_term", "substance_id")):
            try:
                refs[f"{table}.{col}"] = _row(
                    db, f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (frm,))[0]
            except Exception:  # noqa: BLE001  表可能不存在
                refs[f"{table}.{col}"] = None
        out.append({
            "from": frm, "to": to, "why": why,
            "from_row": {k: f[k] for k in SUBSTANCE_COLUMNS},
            "to_row": {k: t[k] for k in SUBSTANCE_COLUMNS},
            "variants": variants,
            "n_components": comps,
            "n_products": prods,
            "refs": refs,
        })
    return {"merges": out, "counts_before": snapshot_counts(db)}


def apply(db, plan_data: dict, db_path: Path) -> dict:
    """一个事务内 re-point + 删重复成分。返回写后计数。"""
    db.execute("BEGIN IMMEDIATE")
    try:
        for m in plan_data["merges"]:
            for v in m["variants"]:
                db.execute("UPDATE variant SET substance_id=? WHERE variant_id=?",
                           (m["to"], v["variant_id"]))
            db.execute("DELETE FROM substance WHERE substance_id=?", (m["from"],))
        counts = snapshot_counts(db)
        if counts["product_component"] != plan_data["counts_before"]["product_component"]:
            raise RuntimeError("组件行数发生变化，回滚本事务")
        if counts["variant"] != plan_data["counts_before"]["variant"]:
            raise RuntimeError("variant 行数发生变化，回滚本事务")
        if counts["substance"] != plan_data["counts_before"]["substance"] - len(MERGES):
            raise RuntimeError("substance 行数与预期不符，回滚本事务")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return counts


def rollback(db, manifest: dict) -> dict:
    """按 manifest 精确还原：先补回 substance 行，再把 variant 指回 from。"""
    db.execute("BEGIN IMMEDIATE")
    try:
        for m in manifest["merges"]:
            cols = [k for k in SUBSTANCE_COLUMNS]
            db.execute(
                f"INSERT OR IGNORE INTO substance ({','.join(cols)})"
                f" VALUES ({','.join('?' * len(cols))})",
                [m["from_row"][k] for k in cols])
            for v in m["variants"]:
                db.execute("UPDATE variant SET substance_id=? WHERE variant_id=?",
                           (m["from"], v["variant_id"]))
        counts = snapshot_counts(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只查（默认）")
    mode.add_argument("--apply", action="store_true", help="事务写库")
    mode.add_argument("--rollback", action="store_true", help="按 manifest 还原")
    ap.add_argument("--allow-real", action="store_true")
    args = ap.parse_args(argv)

    action = "rollback" if args.rollback else ("apply" if args.apply else "dry")
    if action in ("apply", "rollback"):
        guard_real(args.db, DEFAULT_DB, action, args.allow_real)
    write = action != "dry"
    db = connect(args.db, write=write)
    try:
        if action == "rollback":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            counts = rollback(db, manifest)
            print(f"=== Q2 合并回滚 {args.db} ===")
            print(json.dumps(counts, ensure_ascii=False, indent=1))
            return 0

        data = plan(db)
        print(f"=== Q2 三条确定性合并（{action}）{args.db} ===")
        for m in data["merges"]:
            print(f"  {m['from']:32} → {m['to']:22} variant={len(m['variants'])}"
                  f" 组件={m['n_components']} 产品={m['n_products']} 其它引用={m['refs']}")
        print("  写前计数:", data["counts_before"])
        if action != "apply":
            print("（dry-run：未写库）")
            return 0

        data.update({
            "tool": "db/q2_merge_substances.py", "db": str(args.db),
            "db_bytes": args.db.stat().st_size,
            "sha256_before": sha256_file(args.db),
            "created_at": now(), "action": "merge_substances",
        })
        data["counts_after"] = apply(db, data, args.db)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        print("  写后计数:", data["counts_after"])
        print(f"  manifest: {args.manifest}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
