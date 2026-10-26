"""抓 TGA 的 CMI 目录（澳洲非 PBS 药品）→ data/raw/tga_cmi/cmi.json。

为什么是这里
------------
PBS 只收补贴处方药，所以 Panadol / Nurofen 这类 OTC 在 PBS 层查不到；
TGA 的 ARTG（注册总表）没有批量导出、官网还挡程序化访问。
但 TGA 的 eBusiness Services 上有一个**公开的 CMI 目录**：
按首字母列出所有「有 Consumer Medicine Information 的药品」，每行给
    商品名 · 有效成分（分号分隔）· CMI 文档编号
这就是「注册类 OTC」的品牌→成分表（Panadol、Nurofen 都在里面）。

边界（必须如实写进页面）
------------------------
- **只覆盖有 CMI 的药品**：注册类 OTC + 处方药；**listed medicines**
  （Gaviscon、Mylanta、维生素、防晒这类 AUST L 产品）不需要 CMI，不在目录里。
- 目录**没有规格/剂型**，所以这一层的强度留空。
- CMI 文档本身有许可门（下载要先点同意，且再发布要 sponsor 许可），
  所以只取目录里的**事实字段**（商品名、成分），不抓文档正文。

用法：python etl/fetch_tga_cmi.py
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "tga_cmi"
BASE = "https://www.ebs.tga.gov.au/ebs/picmi/picmirepository.nsf/PICMI"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
LETTERS = list("0123457ABCDEFGHIJKLMNOPQRSTUVWXYZ")

RE_ROW = re.compile(r"<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>", re.S)
RE_TAG = re.compile(r"<[^>]+>")


def clean(s: str) -> str:
    s = RE_TAG.sub(" ", s or "")
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
    return re.sub(r"\s+", " ", s).strip()


def fetch(url: str, tries: int = 3) -> str | None:
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            with urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except HTTPError as e:
            if e.code == 404:
                return None
            print(f"  ! {e.code} {url}")
        except (URLError, TimeoutError, OSError) as e:
            print(f"  ! {url} {e}")
        time.sleep(1.5 * (i + 1))
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    out_path = CACHE / "cmi.json"
    if out_path.exists() and not args.force:
        rows = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"已有缓存：{len(rows)} 条（--force 重抓）")
        return

    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for k in LETTERS:
        html = fetch(f"{BASE}?OpenForm&t=CMI&k={k}&r=/")
        if not html:
            print(f"  {k}: 抓取失败")
            continue
        n = 0
        for tr in RE_ROW.findall(html):
            name, info, ings = clean(tr[0]), tr[1], clean(tr[2])
            if not name or name.lower() == "trade name":
                continue
            key = (name.lower(), ings.lower())
            if key in seen:
                continue
            seen.add(key)
            m = re.search(r"id=([A-Za-z0-9\-]+)", info)
            rows.append({
                "trade_name": name,
                "ingredients": ings,
                "cmi_id": m.group(1) if m else None,
            })
            n += 1
        print(f"  {k}: {n}")
        time.sleep(0.4)

    payload = {
        "retrieved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source_url": "https://www.ebs.tga.gov.au/ebs/picmi/picmirepository.nsf/PICMI?OpenForm",
        "n": len(rows),
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"cmi.json：{len(rows)} 条")


if __name__ == "__main__":
    main()
