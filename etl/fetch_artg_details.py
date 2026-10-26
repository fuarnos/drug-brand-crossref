"""抓 ARTG 的 Public Summary（详情 PDF）并解析成分 → data/raw/artg/details.jsonl。

背景
----
ARTG 目录页只有「商品名 + 申办方 + ARTG ID」。但每条记录的 Public Summary PDF
（eBS 的 xmlmillr6 servlet）里有：状态、批准类别、剂型、给药途径、
**Active Ingredients（带规格）**。这是补「listed OTC 没有成分」的唯一官方来源。

默认只抓一批消费品牌（Mylanta / Ural / Panadol / Nurofen / Gaviscon …），
因为全量 34,594 条 × ~830 KB ≈ 29 GB，先做高价值子集；要全量加 --all。

注意：Public Summary 页脚写着「© Commonwealth of Australia … not permitted to
re-transmit, distribute or commercialise the material without prior written
approval」。这里只取事实字段（成分/规格/剂型/状态），不复制文档正文。

用法
----
    python etl/fetch_artg_details.py                 # 默认品牌清单
    python etl/fetch_artg_details.py --all           # 全量（约 29 GB）
    python etl/fetch_artg_details.py --limit 50      # 试跑
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".pylibs"))
import pypdf  # noqa: E402

CACHE = ROOT / "data" / "raw" / "artg"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
BASE = "https://www.ebs.tga.gov.au"
LISTING = BASE + "/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview&Start="
DETAIL = (BASE + "/servlet/xmlmillr6?dbid=ebs/PublicHTML/pdfStore.nsf"
          "&docid={unid}&agid=(PrintDetailsPublic)&actionid=1")

# 先做「用户真的会搜」的消费品牌；按名称前缀匹配
DEFAULT_BRANDS = [
    "mylanta", "ural", "gaviscon", "panadol", "nurofen", "berocca", "blackmores",
    "swisse", "nature's own", "natures own", "centrum", "elevit", "ostelin",
    "bioglan", "herron", "bio island", "caruso's", "carusos", "cenovis",
    "codral", "sudafed", "demazin", "benadryl", "claratyne", "zyrtec", "telfast",
    "aerius", "imodium", "gastro-stop", "buscopan", "senokot", "coloxyl",
    "dulcolax", "microlax", "soov", "bepanthen", "lucas' papaw", "canesten",
    "daktarin", "fess", "nasonex", "flixonase", "rhinocort", "otrivin",
    "betadine", "voltaren", "nicorette", "nicabate", "quantum", "blackmores",
]

RE_ROW = re.compile(
    r"openMILL\('([^']+)'\)\">(.*?)</a></td><td>(.*?)</td><td>(.*?)</td>", re.S)


def fetch(url: str, timeout: int = 180) -> bytes | None:
    for i in range(3):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as r:
                return r.read()
        except HTTPError as e:
            if e.code == 404:
                return None
            print(f"  ! HTTP {e.code} {url[-60:]}")
        except (URLError, TimeoutError, OSError) as e:
            print(f"  ! {e} {url[-60:]}")
        time.sleep(1.5 * (i + 1))
    return None


def listing_page(start: int) -> list[tuple[str, str, str, str]]:
    data = fetch(LISTING + str(start))
    if not data:
        return []
    t = data.decode("utf-8", "replace")
    out = []
    for unid, name, sponsor, artg in RE_ROW.findall(t):
        out.append((unid, html.unescape(re.sub("<[^>]+>", "", name)).strip(),
                    html.unescape(re.sub("<[^>]+>", "", sponsor)).strip(), artg))
    return out


def crawl_listing(workers: int = 20) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    start = 1
    while True:
        batch = [start + i * 30 for i in range(workers)]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            pages = list(ex.map(listing_page, batch))
        added = 0
        for page_rows in pages:
            if not page_rows:
                if added == 0:
                    return rows
                continue
            for r in page_rows:
                if r[0] in seen:
                    continue
                seen.add(r[0])
                rows.append(r)
                added += 1
        if added == 0:
            return rows
        start += workers * 30
        if len(rows) % 3000 < workers * 30:
            print(f"  listing {len(rows)}", flush=True)


def parse_detail(data: bytes) -> dict | None:
    try:
        rd = pypdf.PdfReader(io.BytesIO(data))
        txt = "\n".join((p.extract_text() or "") for p in rd.pages)
    except Exception:
        return None
    txt = txt.replace("\u00a0", " ")
    if "Active Ingredients" not in txt:
        return None
    lines = [x.strip() for x in txt.splitlines() if x.strip()]
    out: dict = {"ingredients": [], "raw_status": "", "approval_area": "",
                 "dosage_form": "", "route": ""}

    def grab(pattern: str) -> str:
        m = re.search(pattern + r"\s*(.+)", txt)
        return m.group(1).strip() if m else ""

    out["header"] = grab(r"Summary for ARTG Entry:")
    out["raw_status"] = grab(r"\bStatus\b")
    out["approval_area"] = grab(r"Approval Area")
    out["dosage_form"] = grab(r"Dosage Form")
    out["route"] = grab(r"Route of Administration")

    try:
        a = lines.index("Active Ingredients")
    except ValueError:
        a = -1
    stop = re.compile(r"^(Public Summary|Page \d|This is not|The onus|Visit |©|"
                      r"Other Ingredients)", re.I)
    if a >= 0:
        for line in lines[a + 1: a + 12]:
            if stop.match(line):
                break
            if re.match(r"^[A-Za-z]", line) and len(line) > 2:
                out["ingredients"].append(line)
    if not out["ingredients"]:
        return None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--brands", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    entries_path = CACHE / "entries_with_unid.jsonl"
    if entries_path.exists() and not args.all:
        entries = [json.loads(x) for x in entries_path.open(encoding="utf-8")]
        print(f"复用 listing 缓存：{len(entries)} 条")
    else:
        print("crawl listing（约 1,150 页）…")
        rows = crawl_listing()
        entries = [{"unid": u, "name": n, "sponsor": s, "artg_id": a}
                   for (u, n, s, a) in rows]
        entries_path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries), encoding="utf-8")
        print(f"  {len(entries)} 条")

    brands = [b.strip().lower() for b in (args.brands.split(",") if args.brands
                                          else DEFAULT_BRANDS) if b.strip()]
    if args.all:
        targets = entries
    else:
        def brand_rank(e: dict) -> int:
            low = e["name"].lower()
            for i, b in enumerate(brands):
                if low.startswith(b) or (" " + b) in low:
                    return i
            return len(brands)

        targets = [e for e in entries
                   if any(e["name"].lower().startswith(b) or
                          (" " + b) in e["name"].lower() for b in brands)]
        targets.sort(key=lambda e: (brand_rank(e), e["name"]))
    if args.limit:
        targets = targets[:args.limit]
    print(f"待抓详情：{len(targets)} 条（品牌清单 {len(brands)} 个）")

    out_path = CACHE / "details.jsonl"
    done: set[str] = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                done.add(json.loads(line)["unid"])
            except Exception:
                pass
    targets = [t for t in targets if t["unid"] not in done]
    print(f"  {len(targets)} 条待抓（已完成 {len(done)}）")

    fh = out_path.open("a", encoding="utf-8")
    lock = threading.Lock()
    n = 0
    t0 = time.time()

    def one(e: dict) -> None:
        nonlocal n
        data = fetch(DETAIL.format(unid=e["unid"]))
        if not data:
            return
        parsed = parse_detail(data)
        if not parsed:
            return
        row = {**e, **parsed, "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        with lock:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
            if n % 10 == 0:
                fh.flush()
                print(f"  … {n}/{len(targets)}  ({time.time()-t0:.0f}s)", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(one, targets))
    fh.close()
    print(f"完成：{n} 条 → {out_path}")


if __name__ == "__main__":
    main()
