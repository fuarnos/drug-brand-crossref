# -*- coding: utf-8 -*-
"""task-141：生成 cases_v4.json = cases_v3（511）+ ATC/大类用例（37）。

期望来自 DB 结构（substance.atc / categories.json prefixes → active 产品最多成分），
不用检索输出反推。输出 tests/trilingual/cases_v4.json。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
import categories as cat_mod  # noqa: E402

CASES_V3 = ROOT / "tests/trilingual/cases_v3.json"
CASES_V4 = ROOT / "tests/trilingual/cases_v4.json"
DB = ROOT / "data/drugs.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
db_sha = hashlib.sha256(DB.read_bytes()).hexdigest()
v3 = json.loads(CASES_V3.read_text(encoding="utf-8"))
cases = list(v3["cases"])
used = {c["case_id"] for c in cases}
new: list[dict] = []


def top_substance(like_prefixes: list[str]) -> str | None:
    cond = " OR ".join("s.atc LIKE ?" for _ in like_prefixes)
    r = db.execute(
        f"""SELECT v.substance_id, COUNT(DISTINCT p.product_id) n
            FROM product_component pc
            JOIN variant v ON v.variant_id = pc.variant_id
            JOIN substance s ON s.substance_id = v.substance_id
            JOIN product p ON p.product_id = pc.product_id AND p.status = 'active'
            WHERE s.atc IS NOT NULL AND ({cond})
            GROUP BY v.substance_id ORDER BY n DESC LIMIT 1""",
        tuple(p + "%" for p in like_prefixes),
    ).fetchone()
    return r["substance_id"] if r else None


def add(cat: str, lang: str, query: str, sid: str | None, source: str,
        detail: str) -> None:
    if not sid:
        return
    n = sum(1 for c in new if c["category"] == cat) + 1
    cid = f"v4-{cat}-{n:04d}"
    assert cid not in used
    used.add(cid)
    new.append({
        "case_id": cid, "category": cat, "lang": lang, "query": query,
        "query_type": "atc" if cat == "atc" else "category",
        "country": None,
        "expected": {"substance_ids": [sid], "policy": "must_hit",
                     "min_tier": "top5"},
        "expect_empty": False,
        "provenance": {"source": source, "detail": detail,
                       "generator": "tests/search_eval/gen_atc_category_cases.py",
                       "generated_at": now(), "db_sha256": db_sha},
        "tags": ["v4", cat],
    })


# A. ATC 精确码（7 位，取有 active 产品的 top 8）
l5 = db.execute("""
    SELECT s.atc AS atc, COUNT(DISTINCT p.product_id) n
    FROM product_component pc JOIN variant v ON v.variant_id = pc.variant_id
    JOIN substance s ON s.substance_id = v.substance_id
    JOIN product p ON p.product_id = pc.product_id AND p.status='active'
    WHERE s.atc IS NOT NULL AND length(s.atc)=7
    GROUP BY s.atc ORDER BY n DESC LIMIT 8""").fetchall()
for r in l5:
    add("atc", "en", r["atc"], top_substance([r["atc"]]),
        "DB substance.atc", f"exact code {r['atc']} ({r['n']} products)")

# B. ATC 前缀/类别码
for code in ("C07", "C10AA", "N02", "J01", "A10"):
    add("atc", "en", code, top_substance([code]),
        "DB substance.atc", f"prefix code {code}")

# C. 16 大类四语 label（按语言轮换）
langs = ["en", "es", "zh", "zh-Hant"]
for i, cat in enumerate(cat_mod.CATEGORY_SNAPSHOT):
    lang = langs[i % len(langs)]
    label = (cat.get("labels") or {}).get(lang) or (cat.get("labels") or {}).get("en")
    if not label:
        continue
    add("category", lang, label, top_substance(cat["prefixes"]),
        "site/dist/data/categories.json",
        f"category {cat['id']} label[{lang}]={label!r} prefixes={cat['prefixes']}")

# D. 口语别名（8 个）
coll = list(cat_mod.COLLOQUIAL_ALIASES.items())
picked = 0
for alias, cat_id in coll:
    if picked >= 8:
        break
    cat = cat_mod.category_by_id(cat_id)
    if not cat:
        continue
    add("category", "zh", alias, top_substance(cat["prefixes"]),
        "lib/categories.py COLLOQUIAL_ALIASES",
        f"colloquial {alias!r} -> {cat_id} prefixes={cat['prefixes']}")
    picked += 1

db.close()
cases.extend(new)
meta = {
    "version": "v4.0",
    "generated_at": now(),
    "base": {"file": "tests/trilingual/cases_v3.json", "n": len(v3["cases"]),
             "meta": v3.get("meta")},
    "db_sha256": db_sha,
    "n_cases": len(cases),
    "new_cases": len(new),
    "new_categories": dict(Counter(c["category"] for c in new)),
    "new_kinds": dict(Counter(c["query_type"] for c in new)),
    "categories": dict(Counter(c["category"] for c in cases)),
    "policies": dict(Counter(c["expected"]["policy"] for c in cases)),
    "generator": "tests/search_eval/gen_atc_category_cases.py",
}
CASES_V4.write_text(json.dumps({"meta": meta, "cases": cases}, ensure_ascii=False,
                               indent=1), encoding="utf-8")
print("written", CASES_V4, "cases", len(cases), "new", len(new),
      "kinds", meta["new_kinds"])
