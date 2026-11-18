"""Q6 CZ 167 个未映射名字 → 组件补写（「非单一成分」窄词表 + 去性状限定词映射）。

背景：CZ 入库口径是「复方缺一味就整条不写组件」，因此 2,108 个 CZ 产品没有组件行
（`reports/2026-11-16-m1-window-exec.md` §4.3）。其中挡路的名字共 167 个，本脚本只处理
**能判定的那部分**，判不了的继续留空并计数（不硬塞）：

  ① `NAME_MAP`：去掉性状/剂型/浓度限定词后能**精确**落到库内已有成分的 CZ 写法
     （如 `SODIUM (S)-LACTATE SOLUTION` → `sodium-lactate`）。逐条写明去掉了什么，
      不做任何剂量/等效判断；
  ② `NON_SUBSTANCE`：多组分配方名（植物油、中链甘油三酯、复方挥发油）与特殊生物制品
     （抗蛇毒血清、自体细胞制品）——库里没有单一实体、EU 层也不当单一活性成分，
      按 `etl/markets/jp.py` 的 `is_non_substance()` 同一口径登记。

Q15（2026-11-19）：两张表已折进 `etl/markets/cz.py`（唯一真相源），本脚本改为从那里 import；
表内容不再在本文件维护，新逻辑以 etl 为准。本脚本只保留 2026-11-18 写库窗口的历史 CLI。

写库条件：该产品当前 0 行组件 ∧ 至少 1 个成分能映射到库内 variant ∧ 其余成分全部落在
①或②里。写出的组件**只含能映射的成分**，被 ② 摘掉的名字记在 manifest 与报告里。

CLI：
    python db/q6_cz_component_fill.py --dry-run            # 默认：只读，算增量
    python db/q6_cz_component_fill.py --apply --db <副本> --manifest <json>
    python db/q6_cz_component_fill.py --rollback --db <副本> --manifest <json>
真实库写需显式 `--allow-real`（先备份 data/drugs.db）。
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))
import cz  # noqa: E402
from cz import NAME_MAP, NON_SUBSTANCE  # noqa: E402  （Q15 起表在 etl/markets/cz.py，唯一真相源）
from _ingest_common import connect, guard_real, sha256_file  # noqa: E402
from ingest_ema_medicines import _variant_resolver  # noqa: E402

DEFAULT_DB = ROOT / "data" / "drugs.db"
DEFAULT_MANIFEST = ROOT / "data" / "sources" / "cz_component_fill_manifest_20261118.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cz_counts(db) -> dict:
    """CZ 组件口径的 before / after 计数。"""
    return {
        "cz_products": db.execute(
            "SELECT COUNT(*) FROM product WHERE country='CZ'").fetchone()[0],
        "cz_products_with_components": db.execute(
            "SELECT COUNT(DISTINCT pc.product_id) FROM product_component pc JOIN product p"
            " ON p.product_id=pc.product_id WHERE p.country='CZ'").fetchone()[0],
        "cz_components": db.execute(
            "SELECT COUNT(*) FROM product_component pc JOIN product p"
            " ON p.product_id=pc.product_id WHERE p.country='CZ'").fetchone()[0],
        "product": db.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "product_component": db.execute("SELECT COUNT(*) FROM product_component").fetchone()[0],
    }


def build(db) -> dict:
    """只读：按快照重算 → 每个无组件产品该不该补、补哪几行。"""
    with_comp = {r[0] for r in db.execute(
        "SELECT DISTINCT pc.product_id FROM product_component pc JOIN product p"
        " ON p.product_id=pc.product_id WHERE p.country='CZ'")}
    cz_products = {r[0] for r in db.execute("SELECT product_id FROM product WHERE country='CZ'")}
    snap = cz.load_snapshot()
    T = snap["tables"]
    latky = {r["KOD_LATKY"]: r for r in T["dlp_latky.csv"]}
    db_inn = cz.db_substances(db)
    resolve = _variant_resolver(db)

    active_by: dict[str, list[dict]] = collections.defaultdict(list)
    for r in T["dlp_slozeni.csv"]:
        if (r.get("S") or "").strip() != "L":
            continue
        active_by[(r.get("KOD_SUKL") or "").strip()].append(r)
    for rows in active_by.values():
        rows.sort(key=lambda r: int(r.get("SQ") or 0) if (r.get("SQ") or "").isdigit() else 0)

    plan_rows: list[dict] = []
    counts: collections.Counter = collections.Counter()
    dropped: collections.Counter = collections.Counter()
    for code, rows in active_by.items():
        pid = f"CZ-{code}"[:64]
        if pid not in cz_products or pid in with_comp:
            continue
        counts["no_component_products"] += 1
        comps: list[dict] = []
        blocked: list[dict] = []
        for cr in rows:
            lk = latky.get(cr["KOD_LATKY"])
            name_en = ((lk or {}).get("NAZEV_EN") or "").strip() or \
                      ((lk or {}).get("NAZEV_INN") or "").strip()
            if not name_en:
                blocked.append({"name": "", "why": "no_name"})
                continue
            sid, tier = cz.map_inn(name_en, db_inn)
            how = tier
            if not sid and name_en in NAME_MAP:
                sid, why = NAME_MAP[name_en]
                how = f"name-map（{why}）"
            if not sid:
                blocked.append({"name": name_en,
                                "why": "non-substance" if name_en in NON_SUBSTANCE else "unknown"})
                continue
            vid = resolve(sid, name_en)
            if not vid:
                blocked.append({"name": name_en, "why": "no_variant"})
                continue
            strength, kind = cz._component_strength(cr.get("AMNT"), cr.get("UN"))
            counts[f"strength:{kind}"] += 1
            comps.append({"variant_id": vid, "strength": strength, "token": name_en, "how": how})
        if not comps or any(b["why"] != "non-substance" for b in blocked):
            for b in blocked:
                if b["why"] == "non-substance":
                    counts["blocked_bad"] += 0
                else:
                    counts[f"blocked:{b['why']}"] += 1
            if not comps:
                counts["skip_no_mappable"] += 1
            else:
                counts["skip_unknown_ingredient"] += 1
            continue
        for b in blocked:
            dropped[b["name"]] += 1
        counts["fill_products"] += 1
        counts["fill_components"] += len(comps)
        plan_rows.append({"product_id": pid, "kod_sukl": code,
                          "components": [{"ord": i, "variant_id": c["variant_id"],
                                          "strength": c["strength"], "token": c["token"],
                                          "how": c["how"]} for i, c in enumerate(comps)],
                          "dropped_non_substance": [b["name"] for b in blocked]})
    return {"rows": plan_rows, "counts": dict(counts),
            "dropped": dict(dropped.most_common()),
            "snapshot": snap["tables"].get("dlp_platnost.csv") or []}


def apply(db, plan: dict) -> int:
    """单事务写入组件行（产品当前必须 0 行，防重复）。"""
    written = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        for r in plan["rows"]:
            n = db.execute("SELECT COUNT(*) FROM product_component WHERE product_id=?",
                           (r["product_id"],)).fetchone()[0]
            if n:
                raise RuntimeError(f"{r['product_id']} 已有 {n} 行组件，拒绝覆盖")
            for c in r["components"]:
                s = c["strength"] or {}
                db.execute(
                    "INSERT INTO product_component (product_id, ord, variant_id, strength_value,"
                    " strength_unit, per_volume_value, per_volume_unit) VALUES (?,?,?,?,?,?,?)",
                    (r["product_id"], c["ord"], c["variant_id"], s.get("value"),
                     s.get("unit"), s.get("per_volume_value"), s.get("per_volume_unit")))
                written += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return written


def rollback(db, manifest: dict) -> int:
    n = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        for r in manifest["rows"]:
            for c in r["components"]:
                n += db.execute("DELETE FROM product_component WHERE product_id=? AND ord=?"
                                " AND variant_id=?",
                                (r["product_id"], c["ord"], c["variant_id"])).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    ap.add_argument("--allow-real", action="store_true")
    args = ap.parse_args(argv)

    action = "rollback" if args.rollback else ("apply" if args.apply else "dry")
    if action in ("apply", "rollback"):
        guard_real(args.db, DEFAULT_DB, action, args.allow_real)
    db = connect(args.db, write=action != "dry")
    try:
        if action == "rollback":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            n = rollback(db, manifest)
            print(f"=== Q6 组件补写回滚 {args.db}：删 {n} 行组件 ===")
            print("  现查:", json.dumps(cz_counts(db), ensure_ascii=False))
            return 0

        before = cz_counts(db)
        plan = build(db)
        print(f"=== Q6 CZ 组件补写（{action}）{args.db} ===")
        print("  写前:", json.dumps(before, ensure_ascii=False))
        print("  计划:", json.dumps(plan["counts"], ensure_ascii=False))
        print(f"  可写 {len(plan['rows'])} 产品 / "
              f"{sum(len(r['components']) for r in plan['rows'])} 行组件")
        print("  被②摘掉的名字:", json.dumps(plan["dropped"], ensure_ascii=False)[:400])
        if action != "apply":
            return 0

        written = apply(db, plan)
        after = cz_counts(db)
        manifest = {
            "tool": "db/q6_cz_component_fill.py", "db": str(args.db),
            "db_bytes": args.db.stat().st_size, "sha256_before": sha256_file(args.db),
            "created_at": now(), "action": "cz_component_fill",
            "name_map": {k: v[0] for k, v in NAME_MAP.items()},
            "non_substance": NON_SUBSTANCE,
            "counts": plan["counts"], "before": before, "after": after,
            "rows_written": written, "rows": plan["rows"],
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        print(f"  已写 {written} 行组件；写后: {json.dumps(after, ensure_ascii=False)}")
        print(f"  manifest: {args.manifest}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
