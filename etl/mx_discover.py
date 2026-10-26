# -*- coding: utf-8 -*-
"""发现 COFEPRIS「Listados de Registros Sanitarios de Medicamentos」页面的全部附件。

背景（2026-10-25 侦察结论）：
- HTML 页面本身被 gob.mx 的 JS 反爬（Challenge Validation）挡住，urllib 直接 GET 只能拿到 1.8 KB 挑战页。
- 但 `cms/uploads/attachment/file/<id>/<name>` 的**文件本体**可以直接下载（200 / application/pdf）。
- 通过 r.jina.ai 的 HTML 模式（X-Return-Format: html）可以拿到渲染后的真实 HTML，href 完整保留。

于是流程是：jina 取链接 → 直接回源下载 → 落 data/raw/mx/。

用法：
    python etl/mx_discover.py                # 只刷新 manifest.json
    python etl/mx_discover.py --download alop  # 下载全部 alopáticos
    python etl/mx_discover.py --download all   # 下载清单里全部（很大，慎用）
"""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "mx"
MANIFEST = RAW / "manifest.json"

PAGE = "https://www.gob.mx/cofepris/documentos/registros-sanitarios-medicamentos"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def http_get(url: str, timeout: int = 180, extra_headers: dict | None = None) -> bytes:
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "es-MX,es;q=0.9"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.read()


def page_html_via_jina(url: str) -> str:
    """gob.mx 的 HTML 有 JS 反爬；jina reader 以 HTML 模式返回渲染结果。"""
    return http_get(
        "https://r.jina.ai/" + url,
        timeout=240,
        extra_headers={"X-Return-Format": "html"},
    ).decode("utf-8", "replace")


def classify(text: str, url: str) -> str:
    t = f"{text} {urllib.parse.unquote(url)}".lower()
    rules = [
        ("revocado", r"revocad"),
        ("cancelado", r"cancelad"),
        ("prorrogado", r"prorrog"),
        ("modificacion", r"modific"),
        ("huerfano", r"hu[eé]rfano"),
        ("enteral", r"enteral"),
        ("vacuna", r"vacun"),
        ("alopatico", r"alop|regalopa"),
        ("herbolario", r"herbol"),
        ("homeopatico", r"homeop"),
        ("vitaminico", r"vitamin"),
        ("remedio", r"remedio"),
        ("formula", r"f[oó]rmula"),
    ]
    for kind, pat in rules:
        if re.search(pat, t):
            return kind
    return "otro"


def year_of(text: str, url: str) -> str:
    for s in (text, urllib.parse.unquote(url)):
        m = re.search(r"(19|20)\d{2}", s)
        if m:
            return m.group(0)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", default="", metavar="KIND",
                    help="下载哪些类别：alop / revocado / cancelado / all")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存，重新取页面")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)

    if MANIFEST.exists() and not args.refresh:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        print(f"用缓存清单：{len(man['files'])} 个附件（--refresh 可重取）")
    else:
        print(f"GET (jina) {PAGE}")
        page = page_html_via_jina(PAGE)
        print(f"  HTML {len(page):,} bytes")
        seen, files = set(), []
        for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", page, re.S | re.I):
            attrs, inner = m.group(1), m.group(2)
            hm = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
            if not hm:
                continue
            href = html.unescape(hm.group(1)).strip()
            if not re.search(r"cms/uploads/attachment/file/\d+/", href, re.I):
                continue
            url = urllib.parse.urljoin(PAGE, href)
            if url in seen:
                continue
            seen.add(url)
            label = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner))).strip()
            if not label:
                label = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
            files.append({
                "label": label,
                "url": url,
                "year": year_of(label, url),
                "kind": classify(label, url),
                "name": Path(urllib.parse.urlparse(url).path).name,
            })
        files.sort(key=lambda f: (f["kind"], f["year"], f["name"]))
        man = {"page": PAGE, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": files}
        MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  附件 {len(files)} 个 → {MANIFEST.relative_to(ROOT)}")

    files = man["files"]
    by_kind: dict[str, int] = {}
    for f in files:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    print("  分类：" + "  ".join(f"{k}={v}" for k, v in sorted(by_kind.items(), key=lambda x: -x[1])))

    if not args.download:
        for f in files:
            if f["kind"] == "alopatico":
                print(f"    {f['year']}  {f['name']:<45}{f['url']}")
        return 0

    kinds = {"alop": {"alopatico"}, "revocado": {"revocado"}, "cancelado": {"cancelado"},
             "prorrogado": {"prorrogado"}}
    if args.download == "all":
        want = {f["kind"] for f in files}
    elif args.download in kinds:
        want = kinds[args.download]
    else:
        print(f"未知类别 {args.download}；可选 alop / revocado / cancelado / all")
        return 2

    ok = skip = fail = 0
    for f in files:
        if f["kind"] not in want:
            continue
        dest = RAW / f["name"]
        if dest.exists() and dest.stat().st_size > 1024:
            skip += 1
            continue
        try:
            blob = http_get(f["url"])
        except Exception as e:  # noqa: BLE001 - 单个文件失败不影响整批
            print(f"  FAIL {f['name']}: {type(e).__name__} {e}")
            fail += 1
            time.sleep(1.0)
            continue
        if not blob.startswith(b"%PDF"):
            print(f"  SKIP {f['name']}: 不是 PDF（{blob[:40]!r}）")
            fail += 1
            continue
        dest.write_bytes(blob)
        ok += 1
        print(f"  OK   {f['name']:<45}{len(blob):>10,} bytes")
        time.sleep(0.4)  # 对政府站点客气一点
    print(f"下载完成：新增 {ok}，已存在 {skip}，失败 {fail} → {RAW.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
