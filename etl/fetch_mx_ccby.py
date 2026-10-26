# -*- coding: utf-8 -*-
"""拉取 datos.gob.mx 上 4 个 CC-BY-4.0 药品/耗材采购明细数据集（CKAN datastore）。

为什么要有这个脚本
------------------
COFEPRIS 注册清单**没有浓度列**。现有 MX 浓度只来自 ISSSTE 目录 + PROFECO 价格，
覆盖率 28.7%。datos.gob.mx 上还有 4 份同许可（CC-BY-4.0）的公立机构采购明细，
字段里带「通用名 / 剂型 / 浓度」，是 D 类证据里唯一「许可干净」的新增来源。

数据源（package_id → 发布机构）
-------------------------------
  adquisicion_medicamentos_demanda                 INPRFM（国家精神病学研究所）
  medicamentos_productos_farmaceuticos_adquiridos_hgmgg  HGMGG（墨西哥总医院）
  entrada_medicamentos                             INER（国家呼吸病研究所）
  adquisicion_insumos_salud                        SEMAR（海军部）

做法：每个 package 只发 1 次 package_show + 1 次 datastore_search（行数 < 4k，
一页拉完），不做翻页轰炸。

产物（data/raw/mx/ccby/）
-------------------------
  <key>.json    每个数据集的完整 records + 许可/抓取时间/资源 id（自带出处）
  meta.json     4 个数据集的索引 + 许可证 + 落盘时间（供 ingest 与报告引用）
  download.log  本次抓取的命令行输出（便于审计）

用法：
    python etl/fetch_mx_ccby.py                 # 查看缓存状态（默认不联网）
    python etl/fetch_mx_ccby.py --download      # 联网拉取/刷新缓存
    python etl/fetch_mx_ccby.py --download --only inprfm
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "mx" / "ccby"
META = OUT / "meta.json"

BASE = "https://datos.gob.mx/api/3/action"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
LICENSE = "CC-BY-4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
ATTRIBUTION = ("Gobierno de México — datos.gob.mx（CKAN），各数据集由发布机构署名；"
               "本站在此基础上做字段归一与浓度回填，属改编（adapted）。")

PACKAGES = {
    "inprfm": {
        "package": "adquisicion_medicamentos_demanda",
        "label": "INPRFM — Adquisición de medicamentos (demanda)",
        "org": "Instituto Nacional de Psiquiatría Ramón de la Fuente Muñiz",
        "fields": ["sus_activ", "forma_farma", "cntcn"],
    },
    "hgmgg": {
        "package": "medicamentos_productos_farmaceuticos_adquiridos_hgmgg",
        "label": "HGMGG — Medicamentos y productos farmacéuticos adquiridos",
        "org": "Hospital General de México Dr. Eduardo Liceaga",
        "fields": ["descripcion", "clave_cnis"],
    },
    "iner": {
        "package": "entrada_medicamentos",
        "label": "INER — Entrada de medicamentos",
        "org": "Instituto Nacional de Enfermedades Respiratorias",
        "fields": ["descripcion", "clave"],
    },
    "semar": {
        "package": "adquisicion_insumos_salud",
        "label": "SEMAR — Adquisición de insumos de salud",
        "org": "Secretaría de Marina",
        "fields": ["descripcion_insumo", "clave"],
    },
}


def _ctx() -> ssl.SSLContext:
    return ssl.create_default_context()


def ckan(action: str, timeout: int = 120, **params) -> dict:
    url = f"{BASE}/{action}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            return json.loads(r.read().decode("utf-8"))
    except ssl.SSLError:
        # 少数 CI/代理环境证书链不全；重试一次不校验证书（只读公开数据）。
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))


def pick_datastore_resource(pkg: dict) -> dict:
    """挑一个 datastore_active 的资源；没有就退回第一个。"""
    resources = pkg.get("resources") or []
    for res in resources:
        if res.get("datastore_active"):
            return res
    if resources:
        return resources[0]
    raise RuntimeError("package 没有任何 resource")


def fetch_one(key: str, spec: dict, max_rows: int) -> dict:
    pkg_show = ckan("package_show", id=spec["package"])["result"]
    res = pick_datastore_resource(pkg_show)
    rid = res.get("id")
    found = ckan("datastore_search", resource_id=rid, limit=max_rows)["result"]
    records = list(found.get("records") or [])
    total = found.get("total", len(records))
    if total > len(records):  # 极少见；补一页，不做无上限翻页
        page = ckan("datastore_search", resource_id=rid, limit=max_rows,
                    offset=len(records))["result"].get("records") or []
        records.extend(page)

    lic = (pkg_show.get("license_title") or pkg_show.get("license_id") or "").strip()
    lic_url = pkg_show.get("license_url") or ""
    if "cc-by" in (pkg_show.get("license_id") or "").lower() or "Creative Commons" in lic:
        lic, lic_url = LICENSE, (lic_url or LICENSE_URL)

    meta = {
        "key": key,
        "package_id": spec["package"],
        "title": pkg_show.get("title") or spec["label"],
        "label": spec["label"],
        "organization": spec.get("org"),
        "license": lic,
        "license_url": lic_url or LICENSE_URL,
        "license_id": pkg_show.get("license_id"),
        "metadata_modified": pkg_show.get("metadata_modified"),
        "dataset_url": f"https://datos.gob.mx/dataset/{spec['package']}",
        "resource_id": rid,
        "resource_name": res.get("name"),
        "resource_format": res.get("format"),
        "resource_url": res.get("url"),
        "retrieved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "total": total,
        "rows": len(records),
        "columns": sorted({k for r in records[:50] for k in r}),
        "fields_used": spec["fields"],
        "attribution": ATTRIBUTION,
        "note": "采购明细，不是全国浓度表；只用于『唯一值才写』的保守回填。",
    }
    payload = {"meta": meta, "records": records}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{key}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    meta["file"] = str(path.relative_to(ROOT)).replace("\\", "/")
    print(f"  [{key}] {meta['rows']:>5}/{total:>5} 行  [{meta['license']}]  → {meta['file']}")
    return meta


def status() -> int:
    if not META.exists():
        print(f"还没有缓存：{META.relative_to(ROOT)}")
        print("先运行：python etl/fetch_mx_ccby.py --download")
        return 1
    meta = json.loads(META.read_text(encoding="utf-8"))
    print(f"缓存：{META.relative_to(ROOT)}  抓取时间 {meta.get('retrieved_at')}")
    print(f"许可：{meta.get('license')}  {meta.get('license_url')}")
    for key, ds in (meta.get("datasets") or {}).items():
        print(f"  {key:<7} {ds['rows']:>5} 行  {ds['license']:<10} {ds['title'][:60]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="联网拉取并写缓存")
    ap.add_argument("--only", choices=list(PACKAGES), default=None)
    ap.add_argument("--max-rows", type=int, default=32000)
    args = ap.parse_args()

    if not args.download:
        return status()

    OUT.mkdir(parents=True, exist_ok=True)
    old = {}
    if META.exists():
        try:
            old = json.loads(META.read_text(encoding="utf-8")).get("datasets") or {}
        except json.JSONDecodeError:
            old = {}

    datasets: dict[str, dict] = dict(old)
    keys = [args.only] if args.only else list(PACKAGES)
    print(f"datos.gob.mx CKAN：拉取 {len(keys)} 个 CC-BY-4.0 数据集 ...")
    for i, key in enumerate(keys):
        spec = PACKAGES[key]
        try:
            datasets[key] = fetch_one(key, spec, args.max_rows)
        except Exception as e:  # noqa: BLE001
            print(f"  [{key}] 失败：{type(e).__name__} {e}")
            if args.only:
                return 1
        if i + 1 < len(keys):
            time.sleep(0.4)  # 轻量请求，别刷 CKAN

    meta = {
        "source": "datos.gob.mx (CKAN API)",
        "api": BASE,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "attribution": ATTRIBUTION,
        "retrieved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "datasets": {k: v for k, v in datasets.items() if k in keys or k not in PACKAGES},
    }
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {META.relative_to(ROOT)}  （{len(datasets)} 个数据集）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
