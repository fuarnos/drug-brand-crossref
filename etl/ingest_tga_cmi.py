"""TGA CMI 目录 → SQLite（澳洲 OTC / 非 PBS 药品）。

数据：data/raw/tga_cmi/cmi.json（etl/fetch_tga_cmi.py 抓的目录页）。
一行 = 商品名 + 有效成分；没有规格/剂型，所以强度留空。

做法
----
1. 只补 PBS 没覆盖到的「品牌 × 成分」组合；PBS 已有的不重复写。
2. 状态写 unknown：目录里出现只说明「有 CMI 文档」，不等于当前在售。
3. 成分按分号拆，走和 PBS/dm+d 同一套 BAN→USAN 别名表。

许可：只取目录页的事实字段（商品名、成分），不抓 CMI 文档正文
（文档有独立的许可协议，再发布需 sponsor 同意）。

用法：python etl/ingest_tga_cmi.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from ingest_openfda_ndc import slug  # noqa: E402
from ingest_pbs import EXTRA_ALIASES  # noqa: E402
from ingest_dmd import ALIASES  # noqa: E402
from normalize_name import normalize  # noqa: E402

CACHE = ROOT / "data" / "raw" / "tga_cmi"
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "tga_cmi"
TODAY = date.today().isoformat()
LISTING_URL = "https://www.ebs.tga.gov.au/ebs/picmi/picmirepository.nsf/PICMI?OpenForm"


def canonical(name: str) -> str:
    base = re.sub(r"\s*\([^)]*\)", "", name).strip().lower()
    base = re.sub(r"\s+", " ", base)
    return EXTRA_ALIASES.get(base) or ALIASES.get(base) or base


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    payload = json.loads((CACHE / "cmi.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    print(f"cmi.json：{len(rows)} 条（{payload['retrieved_at']}）")

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
        (SOURCE_ID, "TGA CMI repository (consumer medicine information index)",
         LISTING_URL,
         "TGA public register listing（仅事实字段；CMI 文档本身另有许可，未复制）",
         "https://www.tga.gov.au/copyright", payload["retrieved_at"],
         "只覆盖有 CMI 的药品（注册类 OTC + 处方药）；listed medicines 不在内；无规格/剂型"))

    # 已有的 AU「品牌 × 成分」组合，避免和 PBS 重复
    have: dict[str, set[frozenset[str]]] = {}
    per_product: dict[str, tuple[str, set[str]]] = {}
    for pid, key, sid in db.execute(
        """SELECT p.product_id, pn.key_id, v.substance_id
           FROM product p
           JOIN product_name pn ON pn.product_id = p.product_id AND pn.name_type = 'trade'
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           WHERE p.country = 'AU'"""
    ):
        slot = per_product.setdefault(pid, (key, set()))
        slot[1].add(sid)
    for key, sids in per_product.values():
        have.setdefault(key, set()).add(frozenset(sids))

    counts = {"rows": 0, "kept": 0, "dup": 0, "skip_empty": 0}
    n = 0
    for r in rows:
        n += 1
        if args.limit and n > args.limit:
            break
        counts["rows"] += 1
        brand = (r.get("trade_name") or "").strip()
        ings_raw = [x for x in (r.get("ingredients") or "").split(";") if x.strip()]
        if not brand or not ings_raw:
            counts["skip_empty"] += 1
            continue
        ings = [canonical(x) for x in ings_raw]
        key = (normalize(brand).norm, frozenset(slug(i) for i in ings))
        if key in have.get(key[0], set()):
            counts["dup"] += 1
            continue
        have.setdefault(key[0], set()).add(key[1])

        pid = ("AU-CMI-" + slug(brand) + "-" +
               hashlib.md5(json.dumps(sorted(key[1]), ensure_ascii=False)
                           .encode()).hexdigest()[:6])
        db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
            " route, release, pack, mah, approval_id, category, is_branded, status,"
            " source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "AU", "not stated", "unknown", None, "none", None, None,
             r.get("cmi_id"), "TGA CMI", 1, "unknown", SOURCE_ID, LISTING_URL,
             payload["retrieved_at"],
             "TGA CMI 目录；无规格/剂型；有 CMI ≠ 当前在售"))
        for ord_, ing in enumerate(ings):
            sid = slug(ing)
            db.execute("INSERT OR IGNORE INTO substance (substance_id, inn_en) VALUES (?,?)",
                       (sid, ing.title()))
            db.execute("INSERT OR IGNORE INTO variant (variant_id, substance_id) VALUES (?,?)",
                       (sid, sid))
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)", (pid, ord_, sid, None, None, None, None))

        for raw, ntype, primary in ((brand, "trade", 1),
                                    (" + ".join(ings), "inn", 0)):
            k = normalize(raw).norm
            if not k:
                continue
            db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                       " VALUES (?,?,?,?)", (k, k, k.replace(" ", ""), "latin"))
            db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                       " VALUES (?,?,?)", (k, raw, SOURCE_ID))
            db.execute("INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                       " is_primary) VALUES (?,?,?,?)", (pid, k, ntype, primary))
        counts["kept"] += 1
        if counts["kept"] % 1000 == 0:
            db.commit()
            print(f"  ... {counts['kept']}")

    db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY, counts["rows"],
         counts["kept"], counts["dup"], "ok",
         f"{counts['skip_empty']} 行缺成分；{counts['dup']} 条与 PBS 重复"))
    db.commit()
    print("counts:", counts)
    print("coverage:", list(db.execute("SELECT * FROM coverage")))
    db.close()


if __name__ == "__main__":
    main()
