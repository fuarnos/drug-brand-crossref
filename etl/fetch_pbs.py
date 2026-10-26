"""抓 PBS 官方数据 API（澳洲）→ data/raw/pbs/api/*.json。

为什么走 API 而不是抓网页
------------------------
1. **许可**：PBS 网页的版权声明只允许「个人参考用途」的复制；API 返回的 `_meta`
   写明 "Permission is granted to use and redistribute this content, as long as all
   copyright statements are retained." —— 这是唯一可以公开再发布的入口。
2. **结构**：`/items` 一行 = PBS 编码 × 品牌 × 包装，字段直接给
   `brand_name` / `drug_name` / `schedule_form` / `organisation_id`，
   不用再从 HTML 里猜。
3. **稳定**：每月 1 日更新，`schedule_code` 标识月份，可回取 12 个月。

访问方式（官方公开 API，无需注册）
----------------------------------
    GET https://data-api.health.gov.au/pbs/api/v3/<endpoint>
    header: subscription-key: <public key>
    限速：每 20 秒 1 次（全体用户共享），所以脚本里硬性 sleep。

public key 来自官方 Postman collection（PBS Public Data API）里公开的变量，
不是私人凭证。

产物
----
    data/raw/pbs/api/schedule.json       当前 schedule 元数据
    data/raw/pbs/api/items.json          /items 全量
    data/raw/pbs/api/organisations.json  /organisations 全量（id → 申办方名）
    data/raw/pbs/api/meta.json           抓取时间 / schedule_code / 版权声明

用法
----
    python etl/fetch_pbs.py            # 有缓存就跳过；--force 重抓
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "pbs" / "api"
BASE = "https://data-api.health.gov.au/pbs/api/v3/"
PUBLIC_KEY = "2384af7c667342ceb5a736fe29f1dc6b"   # 官方 Postman collection 公开变量
RATE_SECONDS = 21
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

_last_call = 0.0


def api(path: str, tries: int = 4) -> dict:
    """调一次 API；强制遵守 20 秒限速，429 时退避重试。"""
    global _last_call
    for attempt in range(tries):
        wait = RATE_SECONDS - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            req = Request(BASE + path, headers={
                "User-Agent": UA,
                "Accept": "application/json",
                "subscription-key": PUBLIC_KEY,
            })
            with urlopen(req, timeout=180) as resp:
                _last_call = time.time()
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            _last_call = time.time()
            if e.code == 429:
                back = 30 + attempt * 20
                print(f"  429 限速，等 {back}s 重试…", file=sys.stderr)
                time.sleep(back)
                continue
            raise SystemExit(f"{path} -> HTTP {e.code}: {e.read()[:300]}")
        except (URLError, TimeoutError, OSError) as e:
            _last_call = time.time()
            print(f"  网络错误 {e}；{5 + attempt * 5}s 后重试", file=sys.stderr)
            time.sleep(5 + attempt * 5)
    raise SystemExit(f"{path} 连续失败")


def fetch_all(force: bool) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    meta_path = CACHE / "meta.json"
    if meta_path.exists() and not force:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        print(f"已有缓存：schedule {meta['schedule_code']}（{meta['retrieved_at']}）")
        return meta

    print("1/3 取当前 schedule …")
    sch = api("schedules?get_latest_schedule_only=true&limit=1")
    rows = sch.get("data") or []
    if not rows:
        raise SystemExit("schedules 返回空")
    sched = rows[0]
    code = sched["schedule_code"]
    print(f"    schedule_code={code} effective={sched['effective_date']}")

    print("2/3 取 items（约 1.5 万行）…")
    items = api(f"items?schedule_code={code}&limit=100000")
    data = items.get("data") or []
    total = items["_meta"].get("total_records")
    print(f"    {len(data)} / {total} 行")
    if total and len(data) < total:
        # 单次上限不够就翻页；page 参数是 API 的通用分页
        page = 2
        while len(data) < total:
            more = api(f"items?schedule_code={code}&limit=100000&page={page}")
            chunk = more.get("data") or []
            if not chunk:
                break
            data.extend(chunk)
            page += 1
            print(f"    … 翻到第 {page} 页，累计 {len(data)}")

    print("3/3 取 organisations …")
    orgs = api(f"organisations?schedule_code={code}&limit=100000")
    org_rows = orgs.get("data") or []
    if orgs["_meta"].get("total_records", 0) > len(org_rows):
        page = 2
        while True:
            more = api(f"organisations?schedule_code={code}&limit=100000&page={page}")
            chunk = more.get("data") or []
            if not chunk:
                break
            org_rows.extend(chunk)
            page += 1

    copyright_text = ""
    for msg in items["_meta"]["info"].get("messages", []):
        if msg.get("type") == "copyright":
            copyright_text = " ".join(msg.get("content") or [])

    meta = {
        "schedule_code": code,
        "effective_date": sched.get("effective_date"),
        "revision_number": sched.get("revision_number"),
        "source_url": BASE,
        "retrieved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "n_items": len(data),
        "n_organisations": len(org_rows),
        "copyright": copyright_text,
    }
    (CACHE / "schedule.json").write_text(json.dumps(sched, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    (CACHE / "items.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (CACHE / "organisations.json").write_text(json.dumps(org_rows, ensure_ascii=False),
                                              encoding="utf-8")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成：{len(data)} items / {len(org_rows)} organisations")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略缓存重新抓")
    args = ap.parse_args()
    t0 = time.time()
    meta = fetch_all(args.force)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"用时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
