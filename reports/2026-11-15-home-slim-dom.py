"""v0.11.10 DOM 证据：首页 / 成分页市场块 / About 的 before-after 片段。"""
from __future__ import annotations

import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AFTER = ROOT / ".tmp" / "v01110"
BEFORE = ROOT / "site" / "dist"


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8").read() if p.exists() else ""


def main() -> None:
    print("=" * 78)
    print("① 首页 E1–E5（before = site/dist 上一版产物）")
    for tag, root in (("before", BEFORE), ("after", AFTER)):
        h = read(root / "index.html")
        if not h:
            print(f"  [{tag}] 无 index.html")
            continue
        print(f"\n  [{tag}] index.html {len(h):,} 字符")
        print(f"    「按类别」入口数         : {len(re.findall(r'data-i18n=\"nav.categories\"', h))}")
        btn = re.search(r'<button[^>]*id="qgo"[^>]*>(.*?)</button>', h, re.S)
        print(f"    搜索按钮               : {btn.group(0)[:150] if btn else '(无)'}")
        tr = re.search(r'<div class="tryrow">.*?</div>', h, re.S)
        print(f"    可点击示例行           : {'有（%d 个按钮）' % len(re.findall('data-q=', tr.group(0))) if tr else '无'}")
        lh = re.search(r'<p class="sub" id="loadhint"[^>]*>', h)
        print(f"    加载说明 #loadhint     : {lh.group(0) if lh else '(无元素)'}")
        liners = re.findall(r'<span class="upd-liner">(.*?)</span>', h)
        print(f"    更新日志一句话         : {liners[:3]}")

    print("\n" + "=" * 78)
    print("② 成分页市场块（amlodipine，before = site/dist）")
    for tag, root in (("before", BEFORE), ("after", AFTER)):
        h = read(root / "drug" / "amlodipine.html")
        if not h:
            continue
        blocks = len(re.findall(r'class="mkblock"', h))
        details = len(re.findall(r'<details class="mkblock"', h))
        opens = len(re.findall(r'<details class="mkblock"[^>]* open', h))
        print(f"\n  [{tag}] amlodipine.html {len(h):,} 字符 · mkblock {blocks} · details {details} · 默认展开 {opens}")
        if tag == "before":
            m = re.search(r'<section class="mkblock" id="mk-CN".*?</section>', h, re.S)
            print(f"    before 块: {(m.group(0)[:320] if m else '(无)')}…")
        else:
            for mk in ("CN", "US", "GB"):
                m = re.search(rf'<details class="mkblock" id="mk-{mk}".*?</summary>', h, re.S)
                print(f"    after  {mk} 块头: {(m.group(0)[:330] if m else '(无)')}")
            print(f"    控件: {'Expand all / Collapse all' if 'data-mk-all=\"open\"' in h else '缺失'}")

    print("\n" + "=" * 78)
    print("③ About：E4 加载说明一节")
    for tag, root in (("before", BEFORE), ("after", AFTER)):
        h = read(root / "about.html")
        m = re.search(r'<div data-i18n-html="about.loading">.{0,300}', h, re.S)
        print(f"  [{tag}] about.loading: {'有' if m else '缺'}")
        if m:
            print(f"    {m.group(0)[:260]}")

    print("\n" + "=" * 78)
    print("④ 四语首页：搜索按钮 + 示例（服务端渲染，各语言各一份）")
    for lang, path in (("en", "index.html"), ("es", "es/index.html"),
                       ("zh", "zh/index.html"), ("zh-Hant", "zh-hant/index.html")):
        h = read(AFTER / path)
        if not h:
            continue
        btn = re.search(r'<span class="sbg-t"[^>]*>(.*?)</span>', h)
        tr = re.search(r'<div class="tryrow">(.*?)</div>', h, re.S)
        print(f"  [{lang}] 按钮文字={btn.group(1) if btn else '?'} · 示例="
              f"{re.findall(r'data-q=\"([^\"]+)\"', tr.group(1))[:3] if tr else '?'}")


if __name__ == "__main__":
    main()
