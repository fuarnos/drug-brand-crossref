"""侦察 COFEPRIS「Listados de Registros Sanitarios de Medicamentos」页面的真实下载链接。

只做两件事：
1. 拉页面 HTML，抽出所有附件链接（按 .pdf / .xls(x) / .csv / .zip 分类）。
2. 打印按年份分组的清单，供人工确认哪一批是「在册（vigentes）」口径。

用法：
    python etl/probe_cofepris.py                # 只列链接
    python etl/probe_cofepris.py --download 3   # 再下载最近 3 个 alopáticos 文件到 data/raw/mx
"""

from __future__ import annotations

import argparse
import html
import re
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "mx"

PAGE = "https://www.gob.mx/cofepris/documentos/registros-sanitarios-medicamentos"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch(url: str, timeout: int = 90) -> bytes:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def extract_links(page_html: str) -> list[tuple[str, str]]:
    """返回 [(链接文字, 绝对 URL)]，只保留附件类链接。"""
    out: list[tuple[str, str]] = []
    # <a href="...">text</a>，容忍跨行与属性顺序
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", page_html, re.S | re.I):
        attrs, inner = m.group(1), m.group(2)
        href_m = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
        if not href_m:
            continue
        href = html.unescape(href_m.group(1)).strip()
        if not re.search(r"\.(pdf|xlsx?|csv|zip|txt)(\?|$)", href, re.I):
            continue
        text = re.sub(r"<[^>]+>", " ", inner)
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        out.append((text, urllib.parse.urljoin(PAGE, href)))
    # 去重但保序
    seen, uniq = set(), []
    for t, u in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append((t, u))
    return uniq


def year_of(text: str) -> str:
    m = re.search(r"(19|20)\d{2}", text)
    return m.group(0) if m else "----"


def kind_of(text: str) -> str:
    t = text.lower()
    for k, pat in (
        ("alopatico", r"alop"),
        ("herbolario", r"herbol"),
        ("homeopatico", r"homeop"),
        ("vitaminico", r"vitamin"),
        ("remedio", r"remedio"),
        ("revocado", r"revocad"),
        ("cancelado", r"cancelad"),
        ("prorrogado", r"prorrog"),
        ("huerfano", r"huerfano|huérfano"),
        ("enteral", r"enteral"),
        ("vacuna", r"vacun"),
        ("modificacion", r"modific"),
    ):
        if re.search(pat, t):
            return k
    return "otro"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", type=int, default=0, metavar="N",
                    help="下载最近 N 个 alopáticos 文件")
    ap.add_argument("--all-alop", action="store_true", help="下载全部 alopáticos 文件")
    args = ap.parse_args()

    print(f"GET {PAGE}")
    page = fetch(PAGE).decode("utf-8", "replace")
    print(f"  HTML {len(page):,} bytes")

    links = extract_links(page)
    print(f"  附件链接 {len(links)} 个\n")

    rows = [(year_of(t), kind_of(t), t, u) for t, u in links]
    print(f"{'year':<6}{'kind':<14}{'text':<58}url")
    for y, k, t, u in rows:
        print(f"{y:<6}{k:<14}{t[:56]:<58}{u}")

    alop = [(y, t, u) for y, k, t, u in rows if k == "alopatico" and y.isdigit()]
    alop.sort(key=lambda r: r[0])
    print(f"\nalopáticos 按年份：{len(alop)} 个，{alop[0][0] if alop else '-'} ~ {alop[-1][0] if alop else '-'}")

    targets = alop if args.all_alop else alop[-args.download:] if args.download else []
    if not targets:
        return 0

    RAW.mkdir(parents=True, exist_ok=True)
    for y, t, u in targets:
        name = f"alopaticos_{y}{Path(urllib.parse.urlparse(u).path).suffix or '.bin'}"
        dest = RAW / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  skip {name} ({dest.stat().st_size:,} bytes)")
            continue
        print(f"  GET {u}")
        blob = fetch(u)
        dest.write_bytes(blob)
        print(f"    -> {name}  {len(blob):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
