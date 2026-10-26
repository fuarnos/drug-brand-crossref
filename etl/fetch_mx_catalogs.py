# -*- coding: utf-8 -*-
"""拉墨西哥两个公开目录，做浓度回填的底料。

数据源（都在 datos.gob.mx，许可 CC BY 4.0）：
  1. ISSSTE《Catálogo Institucional de Insumos》——公共采购目录，通用名 + 剂型 + 浓度。
     1,590 条，descripcion 形如「Ácido Acetilsalicilico. Tableta. Cada Tableta Contiene: ... 500 Mg.」
  2. PROFECO《Quién es quién en los precios》——零售价格调查，商品名 + 包装（含浓度）。
     约 15 万行，去重后是「品名 + 包装」的组合，能给商品名级的浓度。

为什么走 CKAN datastore：repodatos.atdt.gob.mx 直连是 403（Akamai），
但 datos.gob.mx 的 datastore_search 能取到同一份数据。

产物（data/raw/mx/）：
  issste_catalogo.csv    clave, descripcion, unidad_presentacion, grupo_terapeutico
  profeco_medicamentos.csv  producto, presentacion, marca, precio

用法：
    python etl/fetch_mx_catalogs.py                 # 两个都拉
    python etl/fetch_mx_catalogs.py --only issste
    python etl/fetch_mx_catalogs.py --max-rows 60000
"""

from __future__ import annotations

import argparse
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
API = "https://datos.gob.mx/api/3/action/datastore_search"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

PACKAGES = {
    "issste": {
        "package": "catalogo_institucional_insumos",
        "out": RAW / "issste_catalogo.csv",
        "fields": ["clave", "descripcion", "unidad_presentacion", "grupo_terapeutico"],
        "filters": None,
        "limit": 32000,
    },
    "profeco": {
        "package": "programa_quien_es_quien_precios_2026",
        "out": RAW / "profeco_medicamentos.csv",
        "fields": ["producto", "presentacion", "marca", "precio", "fecha_registro"],
        "filters": {"catalogo": "Medicamentos"},
        "limit": 32000,
    },
}


def api_get(params: dict, timeout: int = 180) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return json.loads(r.read())


def resource_id(package: str) -> str:
    req = urllib.request.Request(
        f"https://datos.gob.mx/api/3/action/package_show?id={package}",
        headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120, context=ssl.create_default_context()) as r:
        data = json.loads(r.read())
    return data["result"]["resources"][0]["id"]


def fetch_one(spec: dict, max_rows: int) -> int:
    rid = resource_id(spec["package"])
    params = {"resource_id": rid, "limit": spec["limit"]}
    if spec["filters"]:
        params["filters"] = json.dumps(spec["filters"])
    first = api_get(params)
    total = first["result"]["total"]
    rows = list(first["result"]["records"])
    offset = len(rows)
    while offset < min(total, max_rows):
        params["offset"] = offset
        time.sleep(0.3)
        try:
            page = api_get(params)["result"]["records"]
        except Exception as e:  # noqa: BLE001
            print(f"    分页失败 offset={offset}: {type(e).__name__} {e}")
            break
        if not page:
            break
        rows.extend(page)
        offset += len(page)
        print(f"    {offset:,}/{min(total, max_rows):,}")
    spec["out"].parent.mkdir(parents=True, exist_ok=True)
    with spec["out"].open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=spec["fields"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  → {spec['out'].relative_to(ROOT)}  {len(rows):,} 行（源共 {total:,}）")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["issste", "profeco"], default=None)
    ap.add_argument("--max-rows", type=int, default=60000)
    args = ap.parse_args()

    for name, spec in PACKAGES.items():
        if args.only and name != args.only:
            continue
        print(f"[{name}] {spec['package']}")
        try:
            fetch_one(spec, args.max_rows)
        except Exception as e:  # noqa: BLE001
            print(f"  失败：{type(e).__name__} {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
