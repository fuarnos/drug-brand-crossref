"""L8 徽章收敛只读审计（task-8 / alias-site，2026-11-16）。

口径与 `reports/2026-11-15-ui-badge-audit.py`（旧基线 150,651 / 48,315 的来源）**逐条一致**，
只是多了三个拆分维度，便于写施工清单：

  1. 按页型（results/home · drug · name · combo · maker · atc · cat · rootpage · locale）
  2. 按 class 组合（`st-badge st-active`、`tag.warn`、`badge sev` …）
  3. 每页型最重的页面（抽检 URL）

用法（仓库根目录）：
    $py = 'C:\\Users\\asus\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe'
    & $py .tmp/l8-badge-audit.py
    & $py .tmp/l8-badge-audit.py --dist site/dist --json .tmp/l8-badge-audit.json

只读：不写 site/dist、不写库、不改任何源文件。
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASS_RE = re.compile(r'class="([^"]{1,300})"')

# —— 以下四个集合与旧脚本完全一致（对账口径不能漂）——
NOT_COUNTRY = {"warn", "combo", "picked-tag", "on", "off"}
FORM_TOKENS = {"form-tag", "formchip", "tr-badge"}
STATUS_TOKENS = {"st-badge", "badge", "atc-st", "st-word", "cmp-b", "nolang-badge", "brand-none"}
OTHER_TOKENS = {"catchip"}
FILTER_TOKENS = {"lf-chip", "mkchip"}

PTYPES = ("drug", "name", "combo", "maker", "atc", "cat")


def is_country_token(t: str) -> bool:
    """2 位小写字母 = 市场码（us/cn/gb/…/cz/lv），以后加市场不用改这里。"""
    return len(t) == 2 and t.isalpha() and t.islower() and t not in NOT_COUNTRY


def categorize(tokens: set[str]) -> list[str]:
    cats: list[str] = []
    cc = {t for t in tokens if is_country_token(t)}
    if "tag" in tokens and cc:
        cats.append("country:capsule")
    elif "tag" in tokens:
        cats.append("country:tag-other")      # combo / warn / L1-L4 / picked 等非国家 tag
    if tokens & FORM_TOKENS:
        cats.append("form:capsule")
    if tokens & STATUS_TOKENS:
        cats.append("status:capsule")
    if tokens & FILTER_TOKENS:
        cats.append("filter:chip")
    if tokens & OTHER_TOKENS:
        cats.append("other:catchip")
    return cats


def page_type(rel: Path) -> str:
    """把产物路径映射到「页型」；旧脚本用的是目录桶，这里细分。"""
    parts = rel.parts
    if len(parts) == 1:
        return "results/home" if rel.stem == "index" else "rootpage"
    top = parts[0]
    if top in PTYPES:
        return top
    if top in {"zh", "es", "fr", "zh-hant"}:
        return "locale"
    return "other"


def label(tokens: set[str], cats: list[str]) -> str:
    """class 组合的稳定标签：国家码抽象成 <cc>，避免 us/au/… 各占一行。"""
    if "country:capsule" in cats:
        return "tag.<cc>"
    if "country:tag-other" in cats:
        mods = sorted(t for t in tokens if t != "tag")
        return "tag" + ("." + ".".join(mods) if mods else "")
    if "form:capsule" in cats:
        return ".".join(sorted(tokens & FORM_TOKENS)) or "form"
    if "status:capsule" in cats:
        keep = sorted(t for t in tokens if t in STATUS_TOKENS or t.startswith(("st-", "badge-", "cmp-")))
        return ".".join(keep)
    if "filter:chip" in cats:
        return ".".join(sorted(tokens & FILTER_TOKENS))
    if "other:catchip" in cats:
        return "catchip"
    return "."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="L8 徽章收敛只读审计")
    ap.add_argument("--dist", default=str(ROOT / "site" / "dist"))
    ap.add_argument("--json", default=str(ROOT / ".tmp" / "l8-badge-audit.json"))
    args = ap.parse_args(argv)

    dist = Path(args.dist)
    files = sorted(dist.rglob("*.html"))
    if not files:
        print(f"没有 HTML 产物：{dist}")
        return 2

    total: Counter[str] = Counter()                     # 类别总计（对旧基线）
    total_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    variant: Counter[str] = Counter()                   # class 组合总计
    variant_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    country: Counter[str] = Counter()                   # tag.us / tag.cz …
    country_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    status_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    pages_with: Counter[str] = Counter()
    page_badges: dict[str, list[tuple[int, str]]] = defaultdict(list)   # 每页型最重的页面
    pages_by_type: Counter[str] = Counter()
    n_pages = 0

    for fp in files:
        try:
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = fp.relative_to(dist)
        ptype = page_type(rel)
        n_pages += 1
        pages_by_type[ptype] += 1
        seen: set[str] = set()
        page_count = 0
        for m in CLASS_RE.finditer(txt):
            tokens = set(m.group(1).split())
            cats = categorize(tokens)
            if not cats:
                continue
            page_count += 1
            lab = label(tokens, cats)
            variant[lab] += 1
            variant_by_type[ptype][lab] += 1
            for c in cats:
                total[c] += 1
                total_by_type[ptype][c] += 1
                seen.add(c)
            if "country:capsule" in cats:
                for t in sorted(t for t in tokens if is_country_token(t)):
                    country[f"tag.{t}"] += 1
                    country_by_type[ptype][f"tag.{t}"] += 1
            if "status:capsule" in cats:
                status_by_type[ptype][lab] += 1
        for c in seen:
            pages_with[c] += 1
        if page_count:
            page_badges[ptype].append((page_count, rel.as_posix()))

    top_pages = {
        k: [{"path": p, "badges": n} for n, p in sorted(v, reverse=True)[:6]]
        for k, v in page_badges.items()
    }

    out = {
        "dist": str(dist),
        "pages_scanned": n_pages,
        "pages_by_type": dict(pages_by_type.most_common()),
        "totals": dict(total.most_common()),
        "pages_with": dict(pages_with.most_common()),
        "totals_by_type": {k: dict(v.most_common()) for k, v in sorted(total_by_type.items())},
        "variant_top": [[k, v] for k, v in variant.most_common(40)],
        "variant_by_type": {
            k: [[kk, vv] for kk, vv in v.most_common(24)] for k, v in sorted(variant_by_type.items())
        },
        "country_detail": dict(country.most_common()),
        "country_by_type": {k: dict(v.most_common()) for k, v in sorted(country_by_type.items())},
        "status_by_type": {k: dict(v.most_common()) for k, v in sorted(status_by_type.items())},
        "top_pages": top_pages,
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"扫描 {n_pages:,d} 个 HTML（{dist}）")
    print("页型分布：" + "  ".join(f"{k}={v:,d}" for k, v in pages_by_type.most_common()))
    for k, v in out["totals"].items():
        print(f"  {k:22s} {v:10,d}   出现在 {pages_with.get(k, 0):,d} 页")
    print(f"JSON {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
