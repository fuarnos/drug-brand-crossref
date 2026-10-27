# -*- coding: utf-8 -*-
"""拉取 ChEMBL 的 ATC 分类表（WHO INN 名 → ATC 码），缓存到 data/raw/chembl/。

为什么是 ChEMBL
---------------
WHOCC 的 ATC/DDD 索引有版权，不能整表复制；ChEMBL（EMBL-EBI）把 ATC 分类
（`atc_class` 表：level1–5 + who_name）作为开放数据发布，许可 **CC BY-SA 4.0**，
可再发布/改编（需署名 + 相同方式共享）。本站只取「7 位 ATC 码 + WHO INN 名」
做对齐，**不复制 WHOCC 的 DDD 文本**；atc_name 用 ChEMBL 的 who_name（INN）。

抓什么（一次分页，别刷端点）
--------------------------
  /atc_class.json?limit=1000&offset=N   → 5,579 行（2026-10 快照）
  字段：level1…level5 / *_description / who_name

产物
----
  data/raw/chembl/atc_class.json   {"meta": {...}, "atc_class": [...]}
  data/raw/chembl/meta.json        许可 + 抓取时间 + 行数（ingest 会读）

用法：
    python etl/fetch_chembl_atc.py               # 查看缓存状态（默认不联网）
    python etl/fetch_chembl_atc.py --download    # 拉取并写缓存
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "chembl"
CACHE = OUT / "atc_class.json"
META = OUT / "meta.json"

API = "https://www.ebi.ac.uk/chembl/api/data"
LICENSE = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
ATTRIBUTION = ("ChEMBL — EMBL-EBI, CC BY-SA 4.0；本站只取 ATC 分类的码值与 WHO INN 名，"
               "不复制 WHOCC 的 DDD 文本。")
UA = ("drug-brand-crossref/0.3 (ATC coverage ETL; ChEMBL atc_class bulk; "
      "contact: https://github.com/fuarnos/drug-brand-crossref)")
PAGE = 1000
SLEEP = 1.0   # 限速：EBI 公共 API，别刷


def api_get(path: str, params: dict, timeout: int = 90) -> dict:
    import urllib.parse
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    ctx = ssl.create_default_context()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read()[:300]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise SystemExit(f"ChEMBL HTTP {e.code}: {body!r}") from e
    raise SystemExit("ChEMBL 重试耗尽")


def fetch_all() -> list[dict]:
    rows: list[dict] = []
    offset = 0
    total = None
    while True:
        d = api_get("atc_class.json", {"limit": PAGE, "offset": offset})
        page = d.get("atc") or []
        meta = d.get("page_meta") or {}
        total = meta.get("total_count", total)
        rows.extend(page)
        print(f"  offset {offset:>5}  本页 {len(page):>4}  累计 {len(rows):>5}"
              f" / {total if total is not None else '?'}")
        if not page or total is None or len(rows) >= total:
            break
        offset += len(page)
        time.sleep(SLEEP)
    return rows


def status() -> int:
    if not CACHE.exists():
        print(f"还没有缓存：{CACHE.relative_to(ROOT)}")
        print("先运行：python etl/fetch_chembl_atc.py --download")
        return 1
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    print(f"缓存：{CACHE.relative_to(ROOT)}  {CACHE.stat().st_size / 1024:.0f} KB")
    print(json.dumps(meta, ensure_ascii=False, indent=2)[:1200])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="ChEMBL atc_class → 本地缓存")
    ap.add_argument("--download", action="store_true", help="联网拉取并写缓存")
    args = ap.parse_args()
    if not args.download:
        return status()

    print("ChEMBL atc_class.json 分页拉取（5,579 行，limit=1000，限速 1s）...")
    rows = fetch_all()
    OUT.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    keep = [{k: r.get(k) for k in ("level1", "level2", "level3", "level4", "level5",
                                   "level5_description", "who_name")} for r in rows]
    atcs = {r["level5"] for r in keep if r.get("level5")}
    names = {r["who_name"] for r in keep if r.get("who_name")}
    meta = {
        "source": "ChEMBL (EMBL-EBI) — ATC classification",
        "endpoint": f"{API}/atc_class.json",
        "query": "limit=1000&offset=N（全量分页）",
        "fields": ["level1", "level2", "level3", "level4", "level5", "who_name"],
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "attribution": ATTRIBUTION,
        "retrieved_at": retrieved,
        "rows": len(keep),
        "distinct_level5": len(atcs),
        "distinct_who_names": len(names),
        "note": ("只取 7 位 ATC 码与 WHO INN 名做对齐；不复制 WHOCC 的 DDD 文本。"
                 "衍生映射需按 CC BY-SA 4.0 署名并以相同方式共享。"),
    }
    CACHE.write_text(json.dumps({"meta": meta, "atc_class": keep},
                                ensure_ascii=False), encoding="utf-8")
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {CACHE.relative_to(ROOT)}  {len(keep):,} 行 / "
          f"{len(atcs):,} 个 ATC 码 / {len(names):,} 个 WHO 名  [{LICENSE}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
