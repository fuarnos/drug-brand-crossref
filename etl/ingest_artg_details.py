"""ARTG Public Summary 详情 → 产品（补 listed OTC 的成分与规格）。

数据：data/raw/artg/details.jsonl（etl/fetch_artg_details.py 抓的 1,728 条消费品牌）。
每条含：ARTG ID / 名称 / 申办方 / 状态 / 批准类别 / 剂型 / 途径 / 有效成分（带规格）。

做法
----
1. 每条详情建一个 AU 产品，成分与规格直接来自 ARTG（不再靠猜）。
2. 如果同品牌、同成分的低质量记录已经存在（CMI 无规格 / ARTG 名称层补全 / 人工种子），
   先删旧记录再写新的——避免同一品牌出现「有规格」和「无规格」两条。
3. 只取事实字段，不复制文档正文（Public Summary 页脚有版权限制）。

用法：python etl/ingest_artg_details.py
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
from ingest_pbs import EXTRA_ALIASES  # noqa: E402
from ingest_dmd import ALIASES  # noqa: E402
from normalize_name import normalize  # noqa: E402

CACHE = ROOT / "data" / "raw" / "artg"
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "artg_detail"
TODAY = date.today().isoformat()
LOWER_SOURCES = ("tga_cmi", "artg_enrich", "manual_seed", "artg_detail")

RE_ING = re.compile(
    r"^(?P<name>.*?)\s+(?P<val>\d+(?:\.\d+)?|\.\d+)\s*"
    r"(?P<unit>mg|mcg|micrograms?|g|mL|ml|L|units?|IU|iu|%)"
    r"(?:\s*/\s*(?:(?P<pv>\d+(?:\.\d+)?)\s*)?(?P<pu>mL|ml|g|dose|actuation|unit))?",
    re.I)


def canonical(name: str) -> str:
    base = re.sub(r"\([^)]*\)", " ", name).strip().lower()
    base = re.sub(r"\s+", " ", base)
    return EXTRA_ALIASES.get(base) or ALIASES.get(base) or base


def parse_ingredient(line: str) -> tuple[str, float | None, str | None,
                                        float | None, str | None]:
    m = RE_ING.match(line)
    if not m:
        return canonical(line), None, None, None, None
    name = m.group("name").strip()
    val = m.group("val")
    val = float(val if not val.startswith(".") else "0" + val)
    unit = m.group("unit")
    unit = {"ml": "ml", "mg": "mg", "mcg": "mcg"}.get(unit.lower(), unit.lower())
    pv = m.group("pv")
    pv = float(pv) if pv else (1.0 if m.group("pu") else None)
    pu = (m.group("pu") or "").lower() or None
    return canonical(name), val, unit, pv, pu


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(x) for x in (CACHE / "details.jsonl").open(encoding="utf-8")]
    print(f"details.jsonl：{len(rows)} 条")

    db = sqlite3.connect(DB, timeout=60)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.execute("PRAGMA foreign_keys=ON")
    for table in ("product_component", "product_name"):
        db.execute(f"DELETE FROM {table} WHERE product_id IN "
                   f"(SELECT product_id FROM product WHERE source_id=?)", (SOURCE_ID,))
    db.execute("DELETE FROM product WHERE source_id=?", (SOURCE_ID,))
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        (SOURCE_ID, "ARTG Public Summary (TGA eBS)",
         "https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview",
         "© Commonwealth of Australia（只取事实字段：成分/规格/剂型/状态）",
         "https://www.tga.gov.au/copyright", TODAY,
         "1,728 条消费品牌；PDF 摘要解析 Active Ingredients"))

    # 已有产品的「品牌键 + 成分集合」→ pid / source
    per: dict[str, tuple[str, set[str], str]] = {}
    for key, pid, sid, src in db.execute(
        """SELECT pn.key_id, p.product_id, v.substance_id, p.source_id
           FROM product p
           JOIN product_name pn ON pn.product_id = p.product_id AND pn.name_type = 'trade'
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           WHERE p.country = 'AU'"""
    ):
        if pid not in per:
            per[pid] = (key, set(), src)
        per[pid][1].add(sid)
    index: dict[tuple[str, frozenset[str]], list[str]] = {}
    for pid, (key, sids, src) in per.items():
        index.setdefault((key, frozenset(sids)), []).append(pid)

    counts = {"rows": 0, "added": 0, "replaced": 0, "dup": 0, "skip": 0}
    seen: set[tuple] = set()
    n = 0
    for r in rows:
        n += 1
        if args.limit and n > args.limit:
            break
        counts["rows"] += 1
        name = (r.get("name") or "").strip()
        ings = r.get("ingredients") or []
        if not name or not ings:
            counts["skip"] += 1
            continue
        parsed = []
        for line in ings:
            cname, val, unit, pv, pu = parse_ingredient(line)
            if cname:
                parsed.append((cname, val, unit, pv, pu))
        if not parsed:
            counts["skip"] += 1
            continue
        brand_key = normalize(name).norm
        sig = (brand_key, tuple(p[0] for p in parsed),
               tuple((p[1], p[2]) for p in parsed))
        if sig in seen:
            counts["dup"] += 1
            continue
        seen.add(sig)

        sids = frozenset(slug(p[0]) for p in parsed)
        for old in index.get((brand_key, sids), []):
            src = per[old][2]
            if src in LOWER_SOURCES:
                for table in ("product_component", "product_name"):
                    db.execute(f"DELETE FROM {table} WHERE product_id=?", (old,))
                db.execute("DELETE FROM product WHERE product_id=?", (old,))
                counts["replaced"] += 1

        status = {"active": "active", "cancelled": "withdrawn",
                  "suspended": "withdrawn"}.get(
                      (r.get("raw_status") or "").strip().lower(), "unknown")
        pid = f"AU-ARTG-{r['artg_id']}"
        db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
            " route, release, pack, mah, approval_id, category, is_branded, status,"
            " status_date, source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "AU", (r.get("dosage_form") or "not stated")[:120],
             form_base_of(r.get("dosage_form") or ""), r.get("route") or None, "none",
             None, r.get("sponsor"), r["artg_id"], r.get("approval_area"), 1, status,
             TODAY, SOURCE_ID,
             "https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview",
             r.get("retrieved_at") or TODAY,
             "ARTG Public Summary；成分/规格取自官方摘要"))
        for ord_, (cname, val, unit, pv, pu) in enumerate(parsed):
            sid = slug(cname)
            db.execute("INSERT OR IGNORE INTO substance (substance_id, inn_en) VALUES (?,?)",
                       (sid, cname.title()))
            db.execute("INSERT OR IGNORE INTO variant (variant_id, substance_id) VALUES (?,?)",
                       (sid, sid))
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)", (pid, ord_, sid, val, unit, pv, pu))
        k = brand_key
        if k:
            db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                       " VALUES (?,?,?,?)", (k, k, k.replace(" ", ""), "latin"))
            db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                       " VALUES (?,?,?)", (k, name, SOURCE_ID))
            db.execute("INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                       " is_primary) VALUES (?,?,?,?)", (pid, k, "trade", 1))
        counts["added"] += 1
        if counts["added"] % 300 == 0:
            db.commit()
            print(f"  ... {counts['added']}")

    db.commit()
    print("counts:", counts)
    for row in db.execute("SELECT country, n_products FROM coverage ORDER BY country"):
        print("coverage:", row)
    for row in db.execute(
            "SELECT DISTINCT nv.raw, p.status, pc.strength_value, pc.strength_unit "
            "FROM product p "
            "JOIN product_name pn ON pn.product_id = p.product_id "
            "JOIN name_variant nv ON nv.key_id = pn.key_id "
            "JOIN product_component pc ON pc.product_id = p.product_id "
            "WHERE p.country='AU' AND pn.key_id LIKE '%mylanta%' LIMIT 5"):
        print("  mylanta:", row)
    db.close()


if __name__ == "__main__":
    main()
