# -*- coding: utf-8 -*-
"""拉取 Wikidata 的 ATC 码（P267）与可用交叉键，缓存为本地 JSON。

为什么选 Wikidata
-----------------
WHOCC 的 ATC/DDD 索引有版权（不能整表再发布），而 Wikidata 的 ATC 声明是
社区整理的结构化数据，CC0 1.0（公共领域贡献），可再发布、可改编。
本次只把 P267（ATC code）当作「ATC 码来源」用，不复制 WHOCC 文本。

抓什么（一次 SPARQL，别刷端点）
------------------------------
  P267  ATC code（字符串，如 N02BE01）
  P715  DrugBank ID        —— 备用交叉键（本次 DB 没有该列，先缓存）
  P231  CAS Registry Number —— 备用交叉键（本次 DB 没有该列，先缓存）
  rdfs:label  en/es/zh     —— 英文 INN / 西语通用名 / 中文名匹配用

产物
----
  data/raw/wikidata/atc_p267.json   {"meta": {...}, "rows": [...]}
  data/raw/wikidata/meta.json       许可 + 抓取时间 + 行数（ingest 会读）

用法：
    python etl/fetch_wikidata_atc.py               # 查看缓存状态（默认不联网）
    python etl/fetch_wikidata_atc.py --download    # SPARQL 拉取并写缓存
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "wikidata"
CACHE = OUT / "atc_p267.json"
META = OUT / "meta.json"

ENDPOINT = "https://query.wikidata.org/sparql"
LICENSE = "CC0 1.0 (public domain dedication)"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
UA = ("drug-brand-crossref/0.3 (ATC coverage ETL; one-off SPARQL; "
      "contact: https://github.com/fuarnos/drug-brand-crossref)")

SPARQL = """
SELECT ?drug ?atc ?drugbank ?cas ?label ?lang WHERE {
  ?drug wdt:P267 ?atc .
  OPTIONAL { ?drug wdt:P715 ?drugbank . }
  OPTIONAL { ?drug wdt:P231 ?cas . }
  OPTIONAL {
    ?drug rdfs:label ?label .
    BIND(LANG(?label) AS ?lang)
    FILTER(LANG(?label) IN ("en", "es", "zh"))
  }
}
"""


def fetch() -> list[dict]:
    url = f"{ENDPOINT}?{urllib.parse.urlencode({'query': SPARQL, 'format': 'json'})}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/sparql-results+json",
    })
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=180, context=ctx) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"SPARQL HTTP {e.code}: {e.read()[:400]!r}") from e
    data = json.loads(raw)
    bindings = data.get("results", {}).get("bindings") or []
    rows: list[dict] = []
    for b in bindings:
        rows.append({
            "drug": b.get("drug", {}).get("value", ""),
            "atc": b.get("atc", {}).get("value", ""),
            "drugbank": b.get("drugbank", {}).get("value", ""),
            "cas": b.get("cas", {}).get("value", ""),
            "label": b.get("label", {}).get("value", ""),
            "lang": b.get("lang", {}).get("value", ""),
        })
    return rows


def status() -> int:
    if not CACHE.exists():
        print(f"还没有缓存：{CACHE.relative_to(ROOT)}")
        print("先运行：python etl/fetch_wikidata_atc.py --download")
        return 1
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    print(f"缓存：{CACHE.relative_to(ROOT)}  {CACHE.stat().st_size / 1024:.0f} KB")
    print(json.dumps(meta, ensure_ascii=False, indent=2)[:1200])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="跑一次 SPARQL 并写缓存")
    args = ap.parse_args()
    if not args.download:
        return status()

    print("query.wikidata.org SPARQL：P267 + P715 + P231 + 标签(en/es/zh) ...")
    rows = fetch()
    OUT.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    drugs = {r["drug"] for r in rows}
    atcs = {r["atc"] for r in rows if r["atc"]}
    meta = {
        "source": "Wikidata Query Service (WDQS)",
        "endpoint": ENDPOINT,
        "query": " ".join(SPARQL.split()),
        "properties": {"P267": "ATC code", "P715": "DrugBank ID", "P231": "CAS Registry Number"},
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "attribution": "Wikidata contributors, CC0 1.0；本站只用 P267 码值，不复制 WHOCC 文本。",
        "retrieved_at": retrieved,
        "rows": len(rows),
        "distinct_drugs": len(drugs),
        "distinct_atc": len(atcs),
        "with_drugbank": len({r["drugbank"] for r in rows if r["drugbank"]}),
        "with_cas": len({r["cas"] for r in rows if r["cas"]}),
        "note": "一次拉取；ingest 只对 substance.atc 为空的成分做唯一码回填。",
    }
    CACHE.write_text(json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False),
                     encoding="utf-8")
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {CACHE.relative_to(ROOT)}  {len(rows):,} 行 / "
          f"{len(drugs):,} 个药物 / {len(atcs):,} 个 ATC 码  [{LICENSE}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
