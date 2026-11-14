"""v0.11.9 DOM 证据提取：combo / drug / name / about 的前后片段。

用法：
  $py reports/2026-11-15-t18-t21-dom.py .tmp/v0119-after [.tmp/v0119-before]
before 缺省时用 site/dist（上一次线上构建产物）做对照。
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMBOS = [
    "ferric-oxide-red+pramoxine+zinc-oxide.html",
    "allantoin+dimethicone.html",
    "acetaminophen+dextromethorphan+diphenhydramine+phenylephrine.html",
    "aluminum-hydroxide+calcium-carbonate+magnesium-carbonate.html",
    "amlodipine+ramipril.html",
]
DRUGS = ["insulin-glargine.html", "amoxicillin.html"]


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8").read() if p.exists() else ""


def combo_rows(html: str) -> list[str]:
    # 改动后的行带 data-key；改动前的行没有 → 两种都收
    rows = re.findall(r'<tr data-key=.*?</tr>', html, re.S)
    if rows:
        return rows
    return [r for r in re.findall(r'<tr>.*?</tr>', html, re.S) if 'class="c-brand"' in r]


def drug_spec_bits(html: str) -> dict:
    return {
        "no_basis_tags": len(re.findall(r'data-i18n="spec.no_basis"', html)),
        "cannot_compare": len(re.findall(r'data-i18n="spec.cannot_compare"', html)),
        "page_note": len(re.findall(r'data-i18n="spec.no_basis_note"', html)),
        "also_in": len(re.findall(r'data-i18n="drug.also_in"', html)),
        "size": len(html),
    }


def main() -> None:
    after = ROOT / (sys.argv[1] if len(sys.argv) > 1 else ".tmp/v0119-after")
    before = ROOT / (sys.argv[2] if len(sys.argv) > 2 else "site/dist")

    print("=" * 78)
    print("① 复方页：Dose 列 from 「多值斜杠串」→「每条记录成分 + 各自含量」")
    for slug in COMBOS:
        a = read(after / "combo" / slug)
        b = read(before / "combo" / slug)
        rows_a, rows_b = combo_rows(a), combo_rows(b)
        print(f"\n--- {slug}  after {len(a):,} B / {len(rows_a)} 品牌行"
              f"（before {len(b):,} B / {len(rows_b)} 行）")
        for tag, rows in (("before", rows_b), ("after", rows_a)):
            if not rows:
                print(f"  [{tag}] （无数据）")
                continue
            cell = re.search(r'<td class="c-dose".*?</td>', rows[0], re.S)
            if not cell:
                cell = re.search(r'<td data-label="Dose".*?</td>', rows[0], re.S)
            print(f"  [{tag}] {cell.group(0)[:420] if cell else '(no dose cell)'}")

    print("\n" + "=" * 78)
    print("② 成分页：缺计量基准的规格标 + 对照处排除")
    for name in DRUGS:
        a = read(after / "drug" / name)
        b = read(before / "drug" / name)
        print(f"\n--- {name}")
        print(f"  before: {drug_spec_bits(b)}")
        print(f"  after : {drug_spec_bits(a)}")
        m = re.search(r'<span class="tag warn" data-i18n="spec.no_basis">.{0,160}', a, re.S)
        if m:
            print(f"  badge 片段: {m.group(0)[:200]}")
        m2 = re.search(r'<p class="sub spec-nobasis-note"[^>]*>.{0,220}', a, re.S)
        if m2:
            print(f"  page note : {m2.group(0)[:240]}")
        m3 = re.search(r'<span class="tag" data-i18n="spec.cannot_compare">.{0,80}', a, re.S)
        if m3:
            print(f"  matrix    : {m3.group(0)[:120]}")

    print("\n" + "=" * 78)
    print("③ 名字页：页面级「同名不代表可互换」出现次数")
    for name in ("lyrica.html",):
        for tag, root in (("before", before), ("after", after)):
            html = read(root / "name" / name)
            n = len(re.findall(r'data-i18n="name.notice"', html))
            print(f"  {name} [{tag}] name.notice 出现 {n} 次，页面 {len(html):,} B")

    print("\n" + "=" * 78)
    print("④ About：nickname 口径")
    for tag, root in (("before", before), ("after", after)):
        html = read(root / "about.html")
        m = re.search(r'<div data-i18n-html="about.nick">.{0,300}', html, re.S)
        m2 = re.search(r'<div data-i18n-html="about.nick_merged">.{0,420}', html, re.S)
        print(f"\n  [{tag}] about.html {len(html):,} B")
        print(f"    about.nick       : {(m.group(0)[:220] if m else '(缺)')}")
        print(f"    about.nick_merged: {(m2.group(0)[:420] if m2 else '(缺 —— 改动前无此段)')}")


if __name__ == "__main__":
    main()
