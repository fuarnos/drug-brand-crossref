"""加拿大：Health Canada DPD Open API → data/raw/ca/dpd/*.json（带缓存，可离线重跑）。

背景
----
加拿大没有「一份覆盖处方 + OTC 的公开批量文件」：
- DPD 数据提取包（allfiles.zip）挂在 www.canada.ca 下的 /content/dam/…，
  本机对那台机器的 /content 路径一律超时（Akamai 挡程序化下载），2026-10 实测 HEAD/GET 均 30s 超时。
- DPD 的网页查询（health-products.canada.ca/dpd-bdpp）能查到「商品名 + 强度」，
  但结果是服务端 DataTables（wb-tables），只返回第一页；翻页接口 `getNextPage` 需要
  服务端会话里的 ajaxBean，直接请求恒定 500（NullPointerException）。所以不能当批量源。
- 同一台主机上的 **DPD Open API**（/api/drug/<endpoint>/?lang=en&type=json）是公开的，
  每个端点一次返回全量 JSON，字段与数据提取包一致（含 strength / strength_unit）。

本脚本抓 9 个端点，落地到 data/raw/ca/dpd/。许可：DPD 条款允许**非商业**再使用，
需注明信息来源（https://healthycanadians.gc.ca/important-eng.php#a6），站点 About 页照写。

用法
----
    python etl/fetch_ca_dpd.py              # 缺什么抓什么（已缓存不重下）
    python etl/fetch_ca_dpd.py --force      # 全部重抓
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "ca" / "dpd"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
API = "https://health-products.canada.ca/api/drug/{ep}/?lang=en&type=json"

# 端点 → 说明。ingredient / biosimilar 在该 API 上不存在（404），成分用 activeingredient。
ENDPOINTS = {
    "drugproduct": "DIN 级产品：商品名 / 描述 / 公司 / 剂型代码之外的字段",
    "activeingredient": "成分 + 强度（strength / strength_unit / dosage_value / dosage_unit）",
    "form": "剂型",
    "route": "给药途径",
    "status": "状态 + 状态日期 + 原始上市日期",
    "packaging": "包装",
    "schedule": "处方 / 非处方等类别",
    "therapeuticclass": "治疗分类（含 ATC 4 位）",
    "company": "公司",
}


def fetch(ep: str, timeout: int = 300) -> list[dict]:
    url = API.format(ep=ep)
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            if not isinstance(data, list) or not data:
                raise ValueError(f"{ep}: 返回不是非空数组")
            return data
        except Exception as e:  # noqa: BLE001 - 网络抖动/限流都重试
            last = e
            print(f"  ! {ep} 第 {attempt + 1} 次失败：{type(e).__name__} {str(e)[:120]}",
                  flush=True)
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"抓取 {ep} 失败：{last}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    meta_path = CACHE / "meta.json"
    meta: dict = {"retrieved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "source_page": "https://www.canada.ca/en/health-canada/services/drugs-health-products"
                                 "/drug-products/drug-product-database/what-data-extract-drug-product"
                                 "-database.html",
                  "api_base": API, "endpoints": {}}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    for ep, desc in ENDPOINTS.items():
        path = CACHE / f"{ep}.json"
        if path.exists() and not args.force and path.stat().st_size > 1000:
            rows = json.loads(path.read_text(encoding="utf-8"))
            print(f"  = {ep:18s} 复用缓存 {len(rows):7d} 行 ({desc})", flush=True)
        else:
            t0 = time.time()
            rows = fetch(ep)
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            print(f"  + {ep:18s} 下载 {len(rows):7d} 行 "
                  f"{path.stat().st_size / 1e6:6.1f} MB {time.time() - t0:5.1f}s ({desc})",
                  flush=True)
            meta["retrieved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        meta["endpoints"][ep] = {"rows": len(rows), "file": path.name, "desc": desc}

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n缓存目录：{CACHE.relative_to(ROOT)}  检索时间 {meta['retrieved_at']}")


if __name__ == "__main__":
    main()
