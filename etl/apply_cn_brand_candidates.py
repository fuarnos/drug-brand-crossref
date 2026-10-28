# -*- coding: utf-8 -*-
"""CN 商品名候选入库（task-108）。

数据：`data/cn_brand_candidates.csv`（542 行；high 31 / medium 511；来源 NHSA 快照/公示批次/省级医保局）。
规则
----
- 按 `approval_id` 找到 `country='CN'` 的产品；只补 `product_name(name_type='trade')`，
  **不改通用名身份、不合并产品**；
- 同名品牌按批文区分（同品牌不同批文 → 各自挂到对应产品）；
- 同一产品**已有 trade 名**：若 key 相同 → skip(已存在)；不同 → **conflict，不写**；
- 无批文号 / 无匹配产品 → skip 并记录；
- name_key/name_variant 缺失时创建（raw 保留来源原文；script/source 记录）；
- 幂等；单事务；撤销清单（新增 product_name/name_key/name_variant/source 行）；`--rollback` 精确恢复。

用法
----
    python etl/apply_cn_brand_candidates.py --dry-run            # 默认 high
    python etl/apply_cn_brand_candidates.py --dry-run --min-confidence all
    python etl/apply_cn_brand_candidates.py --db .tmp/cn-brand-apply/test.db --apply --min-confidence high
    python etl/apply_cn_brand_candidates.py --db .tmp/cn-brand-apply/test.db --apply --min-confidence all
    python etl/apply_cn_brand_candidates.py --db .tmp/cn-brand-apply/test.db --rollback
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
DEFAULT_DB = ROOT / "data" / "drugs.db"
DEFAULT_CSV = ROOT / "data" / "cn_brand_candidates.csv"
WORK = ROOT / ".tmp" / "cn-brand-apply"
DEFAULT_MANIFEST = WORK / "manifest.json"
TODAY = date.today().isoformat()
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

SOURCE_MAP = {"nhsa_snapshot": "nhsa", "nhsa_public_batch": "nhsa",
              "jiangsu_ybj": "jiangsu_ybj", "beijing_ybj": "beijing_ybj",
              "qinghai_ybj": "qinghai_ybj", "zhejiang_ybj": "zhejiang_ybj"}
SOURCE_NAMES = {
    "jiangsu_ybj": "江苏省医疗保障局 药品挂网/阳光采购目录（公开查询）",
    "beijing_ybj": "北京市医疗保障局 药品挂网/阳光采购目录（公开查询）",
    "qinghai_ybj": "青海省医疗保障局 药品挂网目录（公开查询）",
    "zhejiang_ybj": "浙江省医疗保障局 药品挂网目录（公开查询）",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def compact(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", (s or "").lower())


def script_of(s: str) -> str:
    return "han" if CJK.search(s or "") else "latin"


def connect(p: Path, write=False):
    return sqlite3.connect(p, timeout=120) if write else sqlite3.connect(
        f"file:{p.as_posix()}?mode=ro", uri=True, timeout=120)


def load_candidates(path: Path, min_conf: str) -> tuple[list[dict], Counter]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    conf = {"high": {"high"}, "medium": {"high", "medium"}, "all": {"high", "medium", "low"}}
    keep = [r for r in rows if r.get("confidence") in conf[min_conf]]
    stats = Counter({"csv_total": len(rows), "selected": len(keep),
                     **{f"conf_{k}": v for k, v in Counter(r.get("confidence") for r in keep).items()}})
    return keep, stats


def build_plan(db: sqlite3.Connection, rows: list[dict]) -> dict:
    stats = Counter()
    plans = []
    skipped = []
    source_ids = {r[0] for r in db.execute("select source_id from source")}
    key_exists = {r[0] for r in db.execute("select key_id from name_key")}
    source_cache = {}
    for r in rows:
        brand = (r.get("brand_name") or "").strip()
        appr = (r.get("approval_id") or "").strip()
        if not brand:
            stats["skip_no_brand"] += 1
            skipped.append({**r, "_reason": "no_brand"})
            continue
        if not appr:
            stats["skip_no_approval"] += 1
            skipped.append({**r, "_reason": "no_approval"})
            continue
        pids = [x[0] for x in db.execute(
            "select product_id from product where country='CN' and approval_id=?", (appr,))]
        if not pids:
            stats["skip_no_product"] += 1
            skipped.append({**r, "_reason": "no_product"})
            continue
        raw_norm = norm(r.get("brand_norm") or brand)
        key_id = raw_norm
        exists_key = key_id in key_exists
        src = SOURCE_MAP.get(r.get("source", ""), "manual_seed")
        src_exists = src in source_ids
        added = 0
        for pid in pids:
            existing = [x[0] for x in db.execute(
                """select nk.key_id from product_name pn join name_key nk on nk.key_id=pn.key_id
                   where pn.product_id=? and pn.name_type='trade'""", (pid,))]
            if key_id in existing:
                stats["skip_already"] += 1
                continue
            if existing:
                stats["skip_conflict"] += 1
                skipped.append({**r, "_reason": "conflict_existing_trade",
                                "product_id": pid, "existing_keys": existing})
                continue
            plans.append({"brand_name": brand, "key_id": key_id, "product_id": pid,
                          "approval_id": appr, "source_id": src, "confidence": r.get("confidence"),
                          "source": r.get("source"), "source_url": r.get("source_url"),
                          "license_note": r.get("license_note"), "data_as_of": r.get("data_as_of")})
            stats["attach_products"] += 1
            added += 1
        if added:
            stats["candidate_attached"] += 1
            if not exists_key:
                stats["new_name_keys"] += 1
                key_exists.add(key_id)
            if not src_exists:
                source_cache[src] = source_cache.get(src, 0) + 1
    stats["unique_keys"] = len({p["key_id"] for p in plans})
    stats["unique_products"] = len({p["product_id"] for p in plans})
    return {"plans": plans, "stats": stats, "skipped": skipped,
            "new_sources": sorted(source_cache), "source_ids": sorted(source_ids)}


def cmd_dry_run(args) -> int:
    rows, cstats = load_candidates(args.csv, args.min_confidence)
    db = connect(args.db)
    plan = build_plan(db, rows)
    db.close()
    print("=== CN 品牌候选 dry-run ===")
    print("CSV:", dict(cstats), "| plan:", dict(plan["stats"]))
    print("将新增 sources:", plan["new_sources"])
    print("Top 计划样例:", [[p["product_id"], p["brand_name"]] for p in plan["plans"][:8]])
    print("skip 明细:", Counter(s["_reason"] for s in plan["skipped"]))
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "dryrun.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    if plan["skipped"]:
        fields = ["_reason", "brand_name", "approval_id", "generic_name", "company",
                  "source", "product_id", "existing_keys", "confidence"]
        with (WORK / "skipped.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(plan["skipped"])
    return 0


def _ensure_source(db: sqlite3.Connection, src: str, row: dict) -> None:
    if db.execute("select 1 from source where source_id=?", (src,)).fetchone():
        return
    db.execute("""insert into source (source_id,name,url,license,license_url,retrieved_at,
                    data_as_of,data_as_of_note,notes) values (?,?,?,?,?,?,?,?,?)""",
               (src, SOURCE_NAMES.get(src, src), row.get("source_url") or "",
                "政府公开信息；仅事实字段（商品名/批文/企业），非商业再发布需署名并可撤下",
                row.get("source_url") or "", TODAY, row.get("data_as_of") or "",
                "公开查询/省级挂网（非全库）", row.get("license_note") or ""))


def cmd_apply(args) -> int:
    if args.db.resolve() == DEFAULT_DB.resolve() and not args.allow_real:
        raise SystemExit("拒绝写真实库：先副本验证；窗口需 --allow-real")
    rows, cstats = load_candidates(args.csv, args.min_confidence)
    db = connect(args.db, write=True)
    db.row_factory = sqlite3.Row
    plan = build_plan(connect(args.db), rows)
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    prev = None
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prev = None
    if prev and prev.get("db") != str(args.db):
        prev = None
    merged_pn = {f"{x['product_id']}|{x['key_id']}": x
                 for x in (prev or {}).get("product_names", [])}
    merged_keys = list((prev or {}).get("created_keys", []))
    merged_variants = [tuple(x) for x in (prev or {}).get("created_variants", [])]
    merged_sources = list((prev or {}).get("created_sources", []))
    run_id = f"cn-brand-{TODAY}" if not prev else prev.get("run_id", f"cn-brand-{TODAY}")
    manifest = {"tool": "etl/apply_cn_brand_candidates.py", "db": str(args.db),
                "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "min_confidence": args.min_confidence,
                "created_sources": merged_sources, "created_keys": merged_keys,
                "created_variants": [list(x) for x in merged_variants],
                "product_names": list(merged_pn.values()), "run_id": run_id}
    try:
        db.execute("BEGIN IMMEDIATE")
        for src in plan["new_sources"]:
            row = next((p for p in plan["plans"] if p["source_id"] == src), {})
            _ensure_source(db, src, row)
            if src not in manifest["created_sources"]:
                manifest["created_sources"].append(src)
        key_created = False
        for p in plan["plans"]:
            kid = p["key_id"]
            row = db.execute("select 1 from name_key where key_id=?", (kid,)).fetchone()
            if not row:
                db.execute("insert into name_key (key_id,norm,compact,script) values (?,?,?,?)",
                           (kid, norm(p["brand_name"]), compact(p["brand_name"]),
                            script_of(p["brand_name"])))
                if kid not in manifest["created_keys"]:
                    manifest["created_keys"].append(kid)
                key_created = True
            else:
                key_created = False
            v = db.execute("select 1 from name_variant where key_id=? and raw=?",
                           (kid, p["brand_name"])).fetchone()
            if not v:
                db.execute("insert into name_variant (key_id,raw,source_id) values (?,?,?)",
                           (kid, p["brand_name"], p["source_id"]))
                if [kid, p["brand_name"]] not in manifest["created_variants"]:
                    manifest["created_variants"].append([kid, p["brand_name"]])
            db.execute("""insert or ignore into product_name
                          (product_id,key_id,name_type,is_primary) values (?,?,'trade',1)""",
                       (p["product_id"], kid))
            item = {"product_id": p["product_id"], "key_id": kid,
                    "brand_name": p["brand_name"], "created_key": key_created}
            merged_pn[f"{p['product_id']}|{kid}"] = item
        manifest["product_names"] = list(merged_pn.values())
        db.execute("""insert or replace into ingest_run
                      (run_id,source_id,started_at,finished_at,rows_in,rows_kept,rows_rejected,status,note)
                      values (?,?,?,?,?,?,?,?,?)""",
                   (manifest["run_id"], "nhsa", TODAY,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    cstats["selected"], len(plan["plans"]),
                    cstats["selected"] - len({x["product_id"] for x in plan["plans"]}),
                    "ok", json.dumps({"tool": "cn-brand-candidates", "stats": dict(plan["stats"])},
                                     ensure_ascii=False)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== CN 品牌候选入库完成 ===")
    print("新增 product_name:", len(manifest["product_names"]),
          "| new keys:", len(manifest["created_keys"]), "| variants:", len(manifest["created_variants"]),
          "| sources:", manifest["created_sources"])
    print("撤销清单:", manifest_path)
    return 0


def cmd_rollback(args) -> int:
    if args.db.resolve() == DEFAULT_DB.resolve() and not args.allow_real:
        raise SystemExit("拒绝写真实库：窗口需 --allow-real")
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单：{manifest_path}")
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = connect(args.db, write=True)
    pn_del = keys_del = var_del = 0
    try:
        db.execute("BEGIN IMMEDIATE")
        for item in m.get("product_names", []):
            cur = db.execute("""delete from product_name where product_id=? and key_id=?
                                and name_type='trade'""", (item["product_id"], item["key_id"]))
            pn_del += cur.rowcount
        for kid, raw in m.get("created_variants", []):
            cur = db.execute("delete from name_variant where key_id=? and raw=?", (kid, raw))
            var_del += cur.rowcount
        for kid in m.get("created_keys", []):
            if db.execute("select 1 from product_name where key_id=? limit 1", (kid,)).fetchone():
                continue
            db.execute("delete from name_variant where key_id=?", (kid,))
            db.execute("delete from name_key where key_id=?", (kid,))
            keys_del += 1
        db.execute("delete from ingest_run where run_id=?", (m.get("run_id") or "",))
        for src in m.get("created_sources", []):
            ref = db.execute("select 1 from name_variant where source_id=? limit 1", (src,)).fetchone()
            if not ref:
                db.execute("delete from source where source_id=?", (src,))
        db.commit()
    finally:
        db.close()
    print(f"=== 回滚完成：product_name {pn_del}、name_key {keys_del}、name_variant {var_del} ===")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CN 商品名候选入库（task-108）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只统计（默认）")
    mode.add_argument("--apply", action="store_true", help="写入（默认限副本）")
    mode.add_argument("--rollback", action="store_true", help="按撤销清单回滚")
    ap.add_argument("--allow-real", action="store_true")
    ap.add_argument("--min-confidence", choices=["high", "medium", "all"], default="high",
                    help="默认 high；窗口建议 high 后再 medium/all")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = ap.parse_args(argv)
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
