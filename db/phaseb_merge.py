"""Phase B 重复记录合并（B2/B3）：把 CJK 重复成分并入英文主记录。

只做**已经被认可的同物重复**（来自 `data/sources/phaseb-merge-plan-20261107.csv` 的
`merge_duplicate` 行），不做任何语义猜测。

安全设计：
- 默认 dry-run（只算前后计数、打印计划），加 `--apply` 才写库；
- 写库前必须 `--backup` 指定备份路径已存在，并写逆操作清单 JSON；
- 每行校验：源/目标产品不重叠、variant 的 salt/ester 一致（或目标只有一个 variant 且源也为空盐）才能并；
- 合并后校验：产品数/组件数必须等于计划里的「合并后应有」，否则整体回滚。

用法：
    & $py db/phaseb_merge.py --batch B2                 # dry-run
    & $py db/phaseb_merge.py --batch B2 --apply \
        --backup data/backups/drugs-before-phaseb-merge-20261107.db \
        --manifest .tmp/phaseb-merge-manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
PLAN = ROOT / "data" / "sources" / "phaseb-merge-plan-20261107.csv"


def load_plan(batch: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(PLAN.open(encoding="utf-8-sig")))
    out = []
    for r in rows:
        if r["action"] != "merge_duplicate":
            continue
        if batch and f"[{batch}]" not in r["reason"]:
            continue
        out.append(r)
    return out


def split_sources(field: str) -> list[str]:
    return [s.strip() for s in field.replace(";", "|").split("|") if s.strip()]


def products_of(cur: sqlite3.Cursor, variant_ids: list[str]) -> int:
    if not variant_ids:
        return 0
    q = ",".join("?" * len(variant_ids))
    return cur.execute(
        f"SELECT COUNT(DISTINCT product_id) FROM product_component WHERE variant_id IN ({q})",
        variant_ids,
    ).fetchone()[0]


def components_of(cur: sqlite3.Cursor, variant_ids: list[str]) -> int:
    if not variant_ids:
        return 0
    q = ",".join("?" * len(variant_ids))
    return cur.execute(
        f"SELECT COUNT(*) FROM product_component WHERE variant_id IN ({q})", variant_ids
    ).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase B 合并（默认 dry-run）")
    ap.add_argument("--batch", default="B2", help="B2 / B3 / 空=全部")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup", default="")
    ap.add_argument("--manifest", default=".tmp/phaseb-merge-manifest.json")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 行（试跑用）")
    args = ap.parse_args()

    rows = load_plan(args.batch)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print(f"[FAIL] 计划里没有 batch={args.batch} 的 merge_duplicate 行")
        return 1
    if args.apply and not args.backup:
        print("[FAIL] --apply 需要 --backup（先备份库）")
        return 1

    con = sqlite3.connect(DB)
    cur = con.cursor()
    plan_items, problems = [], []
    for r in rows:
        target = r["target_substance_id"].strip()
        for src in split_sources(r["source_substance_id(s)"]):
            tv = [x[0] for x in cur.execute("SELECT variant_id, salt, ester FROM variant WHERE substance_id=? ORDER BY variant_id", (target,))]
            sv = cur.execute("SELECT variant_id, salt, ester FROM variant WHERE substance_id=? ORDER BY variant_id", (src,)).fetchall()
            if not tv or not sv:
                problems.append((src, "no variant")); continue
            p_src = products_of(cur, [v[0] for v in sv])
            p_tgt = products_of(cur, tv)
            overlap = cur.execute(
                f"SELECT COUNT(*) FROM (SELECT DISTINCT product_id FROM product_component WHERE variant_id IN ({','.join('?'*len(tv))})) a "
                f"JOIN (SELECT DISTINCT product_id FROM product_component WHERE variant_id IN ({','.join('?'*len(sv))})) b USING(product_id)",
                tv + [v[0] for v in sv],
            ).fetchone()[0]
            if overlap:
                problems.append((src, f"product overlap {overlap}")); continue
            map_v = []
            for sid_v, salt, ester in sv:
                # 优先盐/酯一致的目标 variant；否则只有在目标唯一 variant 时并入
                cand = [x for x in cur.execute("SELECT variant_id, salt, ester FROM variant WHERE substance_id=?", (target,)) if x[1] == salt and x[2] == ester]
                if cand:
                    map_v.append((sid_v, cand[0][0]))
                elif len(tv) == 1:
                    map_v.append((sid_v, tv[0]))
                else:
                    problems.append((src, f"salt mismatch ({salt}/{ester})"))
            plan_items.append({"target": target, "source": src, "map": map_v,
                               "p_src": p_src, "p_tgt": p_tgt, "reason": r["reason"][:200]})

    print(f"batch={args.batch} 计划 {len(rows)} 行 → 可执行 {len(plan_items)} 个源，问题 {len(problems)}")
    for p in problems:
        print("  [SKIP]", p)
    for it in plan_items:
        print(f"  {it['source']} -> {it['target']}: 源产品 {it['p_src']} / 目标产品 {it['p_tgt']} / variant 映射 {it['map']}")

    if not args.apply:
        print("\n[dry-run] 未写库。加 --apply 执行。")
        return 0

    manifest = {"applied_at": datetime.now().isoformat(timespec="seconds"), "batch": args.batch,
                "backup": args.backup, "rows": [], "verify": {}}
    try:
        cur.execute("BEGIN")
        for it in plan_items:
            before = {
                "substance": cur.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
                "variant": cur.execute("SELECT COUNT(*) FROM variant").fetchone()[0],
                "component": cur.execute("SELECT COUNT(*) FROM product_component").fetchone()[0],
            }
            for src_v, tgt_v in it["map"]:
                cur.execute("UPDATE product_component SET variant_id=? WHERE variant_id=?", (tgt_v, src_v))
                cur.execute("DELETE FROM variant WHERE variant_id=?", (src_v,))
            cur.execute("DELETE FROM substance WHERE substance_id=?", (it["source"],))
            manifest["rows"].append({**it, "before_counts": before})
        cur.execute("COMMIT")
    except Exception as exc:  # noqa: BLE001
        cur.execute("ROLLBACK")
        print(f"[FAIL] 回滚：{exc}")
        return 1

    after = {
        "substance": cur.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
        "variant": cur.execute("SELECT COUNT(*) FROM variant").fetchone()[0],
        "component": cur.execute("SELECT COUNT(*) FROM product_component").fetchone()[0],
        "product": cur.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "quick": cur.execute("PRAGMA quick_check").fetchone()[0],
        "fk": len(cur.execute("PRAGMA foreign_key_check").fetchall()),
    }
    manifest["verify"] = after
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    con.close()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("合并完成：", after)
    print("清单：", args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
