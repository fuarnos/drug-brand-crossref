# -*- coding: utf-8 -*-
"""把 PROFECO 三个年度（2024/2025/2026）的药品价格调查并成一份。

单一年度的商品名只有 378 个左右（价格调查是同一批 SKU 在几十家连锁店的重复），
但不同年度的 SKU 并不完全重合，合起来能多认出一批商品名，用来回填浓度。

走 CKAN datastore（repodatos 直连 403），每份资源都带 catalogo 过滤，只要 Medicamentos。

产出 data/raw/mx/profeco_all.csv（producto · presentacion · marca · precio · fecha · year）

用法：python etl/fetch_profeco_hist.py
"""

from __future__ import annotations

import csv
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "mx"
API = "https://datos.gob.mx/api/3/action"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
PACKAGES = [
    "programa_quien_es_quien_precios_2024",
    "programa_quien_es_quien_precios_2025",
    "programa_quien_es_quien_precios_2026",
]


def api(path: str, **params) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180, context=ssl.create_default_context()) as r:
        return json.loads(r.read())


def main() -> int:
    seen: dict[tuple[str, str], dict] = {}
    for pkg in PACKAGES:
        try:
            data = api("package_show", id=pkg)
        except Exception as e:  # noqa: BLE001
            print(f"{pkg}: 取包失败 {type(e).__name__} {e}")
            continue
        resources = data["result"]["resources"]
        print(f"{pkg}: {len(resources)} 份资源")
        for res in resources:
            rid = res["id"]
            try:
                out = api("datastore_search", resource_id=rid, limit=32000,
                          filters=json.dumps({"catalogo": "Medicamentos"}))
            except Exception as e:  # noqa: BLE001
                print(f"   skip {res['name'][:40]}: {type(e).__name__}")
                continue
            recs = out["result"].get("records") or []
            added = 0
            for r in recs:
                k = ((r.get("producto") or "").strip().lower(),
                     (r.get("presentacion") or "").strip().lower())
                if not k[0]:
                    continue
                if k not in seen:
                    seen[k] = {"producto": r.get("producto"), "presentacion": r.get("presentacion"),
                               "marca": r.get("marca"), "precio": r.get("precio"),
                               "fecha": r.get("fecha_registro"), "year": pkg[-4:]}
                    added += 1
            if added:
                print(f"   {res['name'][:44]:<46}+{added} 新组合")
            time.sleep(0.2)

    RAW.mkdir(parents=True, exist_ok=True)
    out_path = RAW / "profeco_all.csv"
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["producto", "presentacion", "marca", "precio",
                                          "fecha", "year"])
        w.writeheader()
        w.writerows(seen.values())
    prods = {v["producto"].strip().lower() for v in seen.values()}
    print(f"\n合计 {len(seen):,} 个「商品名+包装」组合，{len(prods):,} 个商品名 → "
          f"{out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
