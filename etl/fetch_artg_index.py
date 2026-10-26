"""抓 ARTG 现行药品目录（名称层）→ data/raw/artg/medicine_index.jsonl。

为什么从这里抓
--------------
ARTG 全量没有批量文件，www.tga.gov.au 还挡程序化访问；但 TGA 的 eBusiness Services
（www.ebs.tga.gov.au，另一台机器，不挡）有一个公开的「Australian Register - Current
Medicines」列表，30 条/页，字段是：商品名 · 申办方 · ARTG ID。

这一层**只有名字，没有成分**——但名字里通常已经带了规格和剂型
（"GAVISCON DUAL ACTION PEPPERMINT LIQUID 500 mg/213 mg/325 mg oral suspension"），
足以回答「这个牌子在澳洲注册过吗、ARTG 号是多少、谁登记的」。

用法
----
    python etl/fetch_artg_index.py            # 断点续抓
    python etl/fetch_artg_index.py --force    # 从头抓
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "artg"
BASE = "https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview&Start="
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
STEP = 30
WINDOW = 12          # 一批并发 12 页
LOCK = threading.Lock()


def fetch(start: int, tries: int = 3) -> str | None:
    for i in range(tries):
        try:
            req = Request(BASE + str(start), headers={"User-Agent": UA,
                                                      "Accept": "text/html"})
            with urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except HTTPError as e:
            if e.code == 404:
                return None
            print(f"  ! HTTP {e.code} Start={start}")
        except (URLError, TimeoutError, OSError) as e:
            print(f"  ! {e} Start={start}")
        time.sleep(1.5 * (i + 1))
    return None


def parse(html: str) -> list[dict]:
    m = re.search(r'<th class="prod"[^>]*>.*?</table>', html, re.S)
    if not m:
        return []
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S):
        cells = []
        for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S):
            c = re.sub(r"<[^>]+>", " ", c)
            c = c.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
            cells.append(re.sub(r"\s+", " ", c).strip())
        if len(cells) >= 3 and cells[0]:
            out.append({"name": cells[0], "sponsor": cells[1], "artg_id": cells[2]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--window", type=int, default=WINDOW)
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    out_path = CACHE / "medicine_index.jsonl"
    state_path = CACHE / "state.json"
    if args.force and out_path.exists():
        out_path.unlink()
    if state_path.exists() and not args.force:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {"next_start": 1, "count": 0}

    seen: set[str] = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                seen.add(json.loads(line)["artg_id"])
            except Exception:
                pass
    print(f"续抓：Start={state['next_start']}，已有 {len(seen)} 条")

    fh = out_path.open("a", encoding="utf-8")
    start = state["next_start"]
    done = False
    t0 = time.time()
    try:
        while not done:
            batch = [start + i * STEP for i in range(args.window)]
            with ThreadPoolExecutor(max_workers=args.window) as ex:
                pages = list(ex.map(lambda s: (s, fetch(s)), batch))
            for s, html in pages:
                rows = parse(html) if html else []
                if not rows:
                    done = True
                    break
                for r in rows:
                    if r["artg_id"] in seen:
                        continue
                    seen.add(r["artg_id"])
                    r["retrieved_at"] = datetime.now(timezone.utc).astimezone() \
                        .isoformat(timespec="seconds")
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            start += args.window * STEP
            fh.flush()
            state = {"next_start": start, "count": len(seen)}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            print(f"  Start≈{start}  累计 {len(seen)} 条  "
                  f"({time.time() - t0:.0f}s)", flush=True)
    finally:
        fh.close()

    print(f"完成：{len(seen)} 条 → {out_path}")


if __name__ == "__main__":
    main()
