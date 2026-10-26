"""ARTG 名称层 → 补产品（只补「品牌已经认识」的那些）。

思路
----
ARTG 目录只有名字（"PANADOL OSTEO 665 mg modified release tablets"），没有成分。
但名字里的品牌部分，往往已经在我们库里出现过（PBS / CMI / 人工种子）。
所以：
    1. 把名字里的剂型/释放/包装词剥掉，归一化成品牌键；
    2. 在 AU 已有产品里找**完全同名**的品牌键；
    3. 只有该品牌指向唯一一组成分时，才按名字里的规格/剂型建产品。

匹配不上、或品牌对应多组成分（同名不同药）的，一律跳过——宁可漏，不猜。

用法：python etl/ingest_artg_enrich.py
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from ingest_openfda_ndc import form_base_of, slug  # noqa: E402
from ingest_pbs import parse_strengths  # noqa: E402
from normalize_name import normalize  # noqa: E402

DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "artg_enrich"
TODAY = date.today().isoformat()

# ARTG 名字里的剂型/释放/包装短语：不剥掉就永远对不上品牌键
NOISE = re.compile(
    r"^\s*(?:copy\s+of|duplicate\s+of)\s+|"
    r"\b(?:modified|extended|prolonged|sustained|immediate|controlled)\s+release\b|"
    r"\bfilm[- ]coated\b|\benteric[- ]coated\b|\bgastro[- ]resistant\b|"
    r"\bhard\s+capsules?\b|\bsoft\s+capsules?\b|\bblister\s+packs?\b|"
    r"\bbottles?\b|\bsachets?\b|\bvials?\b|\bampoules?\b|\bpre[- ]filled\s+pens?\b|"
    r"\bpen\s+devices?\b|\bpack\s+sizes?\b|\bflavours?\b|\bflavors?\b|"
    r"\bwith\s+pump\b|\bpumps?\b",
    re.I)


def brand_key(name: str) -> str:
    cleaned = NOISE.sub(" ", name)
    return normalize(cleaned).norm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    db = sqlite3.connect(DB, timeout=60)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("DELETE FROM product_component WHERE product_id IN "
               "(SELECT product_id FROM product WHERE source_id=?)", (SOURCE_ID,))
    db.execute("DELETE FROM product_name WHERE product_id IN "
               "(SELECT product_id FROM product WHERE source_id=?)", (SOURCE_ID,))
    db.execute("DELETE FROM product WHERE source_id=?", (SOURCE_ID,))

    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        (SOURCE_ID, "ARTG index enrichment (TGA eBS current medicines)",
         "https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview",
         "TGA public register（名称层事实字段）", "https://www.tga.gov.au/copyright",
         TODAY, "只给「品牌已认识」的 ARTG 条目补规格/剂型；成分沿用同名品牌，不猜"))

    # 品牌键 → {成分集合}：同一品牌若对应多组成分，说明同名不同药，跳过
    prod_subs: dict[str, set[str]] = {}
    prod_vars: dict[str, list[str]] = {}
    prod_key: dict[str, str] = {}
    for key, pid, _ord, vid, sid in db.execute(
        """SELECT pn.key_id, p.product_id, pc.ord, v.variant_id, v.substance_id
           FROM product p
           JOIN product_name pn ON pn.product_id = p.product_id AND pn.name_type = 'trade'
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           WHERE p.country = 'AU' AND p.source_id != ?
           ORDER BY p.product_id, pc.ord""", (SOURCE_ID,)
    ):
        prod_subs.setdefault(pid, set()).add(sid)
        prod_vars.setdefault(pid, []).append(vid)
        prod_key[pid] = key

    brand_sets: dict[str, set[frozenset[str]]] = {}
    brand_vars: dict[tuple[str, frozenset[str]], list[str]] = {}
    for pid, sids in prod_subs.items():
        fs = frozenset(sids)
        brand_sets.setdefault(prod_key[pid], set()).add(fs)
        brand_vars.setdefault((prod_key[pid], fs), prod_vars[pid])

    print(f"AU 已有品牌键 {len(brand_sets)} 个")

    rows = list(db.execute(
        "SELECT artg_id, name, sponsor, name_norm FROM artg_entry"))
    print(f"artg_entry：{len(rows)} 条")

    counts = {"rows": 0, "matched": 0, "added": 0, "dup": 0,
              "no_strength": 0, "ambiguous": 0}
    seen: set[tuple] = set()
    n = 0
    for artg_id, name, sponsor, _norm in rows:
        n += 1
        if args.limit and n > args.limit:
            break
        counts["rows"] += 1
        key = brand_key(name)
        sets = brand_sets.get(key)
        if not sets:
            continue
        if len(sets) > 1:
            counts["ambiguous"] += 1
            continue
        sids = next(iter(sets))
        vids = brand_vars[(key, sids)]
        counts["matched"] += 1

        strengths = parse_strengths(name)
        if not strengths:
            counts["no_strength"] += 1
            continue
        comps = tuple(vids)
        sig = (key, comps, tuple(strengths), form_base_of(name))
        if sig in seen:
            counts["dup"] += 1
            continue
        seen.add(sig)

        pid = f"AU-ARTG-{artg_id}-{slug(name)[:60]}"
        db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
            " route, release, pack, mah, approval_id, category, is_branded, status,"
            " status_date, source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "AU", name[:120], form_base_of(name), None, "none", None, sponsor,
             artg_id, "ARTG", 1, "active", TODAY, SOURCE_ID,
             f"https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview",
             TODAY, "ARTG 名称层补全；成分沿用同名品牌的已知成分"))
        # 成分顺序按已有产品来（sids 集合无序，展示顺序影响不大）
        for ord_, sid in enumerate(comps):
            st = strengths[ord_] if ord_ < len(strengths) else (None, None, None, None)
            sval, unit, pv, pu = st
            try:
                sval_f = float(sval) if sval not in (None, "") else None
            except ValueError:
                sval_f = None
            try:
                pv_f = float(pv) if pv not in (None, "") else None
            except ValueError:
                pv_f = None
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)", (pid, ord_, sid, sval_f, unit, pv_f, pu))
        for raw, ntype, primary in ((name, "trade", 1),):
            k = normalize(name).norm
            if not k:
                continue
            db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                       " VALUES (?,?,?,?)", (k, k, k.replace(" ", ""), "latin"))
            db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                       " VALUES (?,?,?)", (k, name, SOURCE_ID))
            db.execute("INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                       " is_primary) VALUES (?,?,?,?)", (pid, k, ntype, primary))
        counts["added"] += 1
        if counts["added"] % 1000 == 0:
            db.commit()
            print(f"  ... {counts['added']}")

    db.commit()
    print("counts:", counts)
    for row in db.execute("SELECT country, n_products FROM coverage ORDER BY country"):
        print("coverage:", row)
    db.close()


if __name__ == "__main__":
    main()
