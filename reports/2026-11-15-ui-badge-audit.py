"""只读审计：全站「国家 / 剂型 / 状态」三类 capsule 徽章逐个计数（L8 收敛清单的对账数字）。

用法（仓库根目录）：
    $py = 'C:\\Users\\asus\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe'
    & $py reports/2026-11-15-ui-badge-audit.py                       # 扫 site/dist，落 .tmp/ui-baseline/badge-audit.json
    & $py reports/2026-11-15-ui-badge-audit.py --dist .tmp/dist-after --json .tmp/ui-baseline/badge-audit-after.json

口径：
  - 逐文件读 `class="..."` 属性，按空白切 token；一个元素 = 一处命中的 class 属性。
  - 国家胶囊   = 含 token `tag` 且含国家码 token（us/cn/gb/…）+ `.mkchip` + `.lf-chip`。
  - 剂型胶囊   = `.form-tag` + `.formchip` + `.tr-badge`（剂型切换 chip）。
  - 状态胶囊   = `.st-badge` + `.badge` + `.atc-st` + `.st-word` + `.cmp-b` + `.nolang-badge`
                 + `.brand-none`（=「无商品名 / 无此名」这类身份徽标）。
  - 其它胶囊   = `.catchip`（分类入口，不计入上面三类，但同属「胶囊堆积」清单）。
只读：不写 site/dist、不写库、不改任何源文件。
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASS_RE = re.compile(r'class="([^"]{1,200})"')
COUNTRY_CODES = {"us", "cn", "gb", "ca", "au", "es", "mx", "tw", "sg", "hk", "eu"}
FORM_TOKENS = {"form-tag", "formchip", "tr-badge"}
STATUS_TOKENS = {"st-badge", "badge", "atc-st", "st-word", "cmp-b", "nolang-badge", "brand-none"}
OTHER_TOKENS = {"catchip"}
FILTER_TOKENS = {"lf-chip", "mkchip"}


def categorize(tokens: set[str]) -> list[str]:
    """返回这个元素命中的类别（可能多类，如 `st-badge st-unknown nolang-badge`）。"""
    cats: list[str] = []
    if "tag" in tokens and tokens & COUNTRY_CODES:
        cats.append("country:capsule")
    elif "tag" in tokens:
        cats.append("country:tag-other")      # combo / warn / L3 / picked 等非国家 tag
    if tokens & FORM_TOKENS:
        cats.append("form:capsule")
    if tokens & STATUS_TOKENS:
        cats.append("status:capsule")
    if tokens & FILTER_TOKENS:
        cats.append("filter:chip")
    if tokens & OTHER_TOKENS:
        cats.append("other:catchip")
    return cats


def dir_bucket(rel: Path) -> str:
    parts = rel.parts
    if len(parts) == 1:
        return "(root)"
    return parts[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="全站徽章计数（只读）")
    ap.add_argument("--dist", default=str(ROOT / "site" / "dist"))
    ap.add_argument("--json", default=str(ROOT / ".tmp" / "ui-baseline" / "badge-audit.json"))
    args = ap.parse_args(argv)

    dist = Path(args.dist)
    files = sorted(dist.rglob("*.html"))
    if not files:
        print(f"没有 HTML 产物：{dist}")
        return 2

    cat_total: Counter[str] = Counter()
    cat_by_dir: dict[str, Counter[str]] = defaultdict(Counter)
    class_pair: Counter[str] = Counter()      # 具体组合键 → 次数（对账用）
    country_detail: Counter[str] = Counter()  # tag.us / tag.cn … 逐个
    status_detail: Counter[str] = Counter()
    form_detail: Counter[str] = Counter()
    pages_with: Counter[str] = Counter()
    n_pages = 0

    for fp in files:
        try:
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        n_pages += 1
        bucket = dir_bucket(fp.relative_to(dist))
        seen_cats: set[str] = set()
        for m in CLASS_RE.finditer(txt):
            tokens = set(m.group(1).split())
            cats = categorize(tokens)
            if not cats:
                continue
            for c in cats:
                cat_total[c] += 1
                cat_by_dir[bucket][c] += 1
                seen_cats.add(c)
            key = ".".join(sorted(tokens))
            class_pair[key] += 1
            if "country:capsule" in cats:
                for t in sorted(tokens & COUNTRY_CODES):
                    country_detail[f"tag.{t}"] += 1
            if "form:capsule" in cats:
                for t in sorted(tokens & FORM_TOKENS):
                    form_detail[t] += 1
            if "status:capsule" in cats:
                for t in sorted(tokens & STATUS_TOKENS):
                    status_detail[t] += 1
                for t in sorted(x for x in tokens if x.startswith("st-") and x != "st-badge"):
                    status_detail[f"…{t}"] += 1
                for t in sorted(x for x in tokens if x.startswith("badge-")):
                    status_detail[f"…{t}"] += 1
        for c in seen_cats:
            pages_with[c] += 1

    out = {
        "dist": str(dist),
        "pages_scanned": n_pages,
        "totals": dict(cat_total.most_common()),
        "pages_with": dict(pages_with.most_common()),
        "by_dir": {k: dict(v.most_common()) for k, v in sorted(cat_by_dir.items())},
        "country_detail": dict(country_detail.most_common()),
        "form_detail": dict(form_detail.most_common()),
        "status_detail": dict(status_detail.most_common()),
        "class_pairs_top": [[k, v] for k, v in class_pair.most_common(60)],
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"扫描 {n_pages} 个 HTML（{dist}）")
    for k, v in out["totals"].items():
        print(f"  {k:22s} {v:10,d}   出现在 {pages_with.get(k, 0):,d} 页")
    print(f"JSON {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
