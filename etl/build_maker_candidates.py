# -*- coding: utf-8 -*-
"""厂家页数据准备（task-47）：从 product.mah 生成可构建的厂家清单。

只读 `data/drugs.db`，输出：
  data/maker_candidates.csv     每个「规范化厂家」一行：显示名/slug/产品数/市场/品牌数/是否建页…
  data/maker_blacklist.json     占位/黑名单规则 + 命中条目
  .tmp/maker-data/stats.json    审计统计（供报告引用）

规则
----
- **规范化 key**：NFKC → trim → 内部空白折叠 → casefold → 去标点（. , ; : ' " ( ) &）
  → 空白折叠。用于合并大小写/标点差异（如 `PFIZER, S.A. DE C.V.` 与 `Pfizer S.A. de C.V.`）。
- **显示名**：同一 key 下出现次数最多的原始写法（保留原大小写/标点）。
- **占位/黑名单**：Special Order（含 Drug Tariff 变体）、Various、Unknown、N/A、None、
  Not stated、Sin marca、Desconocido、纯符号/纯数字/长度 ≤2 等。
- **slug**：
  - 拉丁名：NFKD 去重音 → 小写 → 非字母数字→`-` → 折叠；截断 48 字符；
  - 非拉丁名（中文等）：lib 没有拼音库，用 `maker-<sha1(key)前10位>` 稳定短哈希；
  - 全局唯一：冲突/截断时追加 `-<sha1前6位>`。
- **是否建页**：`n_products >= 2` 且非占位 → `has_page=1`；`is_placeholder=1` 的一律不建页。

用法：
    python etl/build_maker_candidates.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "drugs.db"
OUT_CSV = ROOT / "data" / "maker_candidates.csv"
OUT_BLACK = ROOT / "data" / "maker_blacklist.json"
EVID = ROOT / ".tmp" / "maker-data"
TODAY = date.today().isoformat()

MIN_PRODUCTS = 2
SLUG_MAX = 48

# 占位/黑名单：whole-string 规则 + 包含规则（含规则只用于明显占位词，避免误伤真名）
PLACEHOLDER_EXACT = {
    "special order", "drug tariff special order", "part viiid drug tariff special order",
    "various", "unknown", "n/a", "na", "none", "not stated", "not specified",
    "sin marca", "desconocido", "no especificado", "no declarado", "other", "generic",
    "s/m", "s+", "x", "xx", "xxx", "无", "不详", "未知", "未提供", "无厂家", "暂无",
}
PLACEHOLDER_CONTAINS = ("special order",)   # 只收 special order 家族
PUNCT_RE = re.compile(r"[.,;:'\"()\[\]{}&/\\|]+")
DASH_RE = re.compile(r"[-\u2010-\u2015\uff0d]+")


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def norm_key(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw or "")
    s = s.replace("\u00a0", " ").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.casefold()
    s = PUNCT_RE.sub(" ", s)
    s = DASH_RE.sub("-", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_placeholder(raw: str, key: str) -> tuple[bool, str]:
    if not key:
        return True, "empty"
    k = key.strip()
    if k in PLACEHOLDER_EXACT:
        return True, "exact_%s" % k
    for pat in PLACEHOLDER_CONTAINS:
        if pat in k:
            return True, "contains_special_order"
    if len(k) <= 2:
        return True, "too_short"
    if re.fullmatch(r"[\d .,/\-]+", k):
        return True, "digits_only"
    if re.fullmatch(r"[-_=*+#. ]+", k):
        return True, "symbols_only"
    return False, ""


def has_latin(s: str) -> bool:
    return bool(re.search(r"[A-Za-z]", s))


def slug_base(key: str) -> str:
    if not key:
        return ""
    a = strip_acc(key).lower()
    a = re.sub(r"[^a-z0-9]+", "-", a).strip("-")
    if len(a) > SLUG_MAX:
        a = a[:SLUG_MAX].rstrip("-")
    return a


def sha(s: str, n: int = 10) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def make_slugs(keys: list[str]) -> dict[str, str]:
    """稳定 slug + 全局唯一（冲突时追加短哈希）。"""
    out: dict[str, str] = {}
    used: Counter[str] = Counter()
    for k in keys:
        base = slug_base(k)
        if not base or not has_latin(k):
            base = "maker-" + sha(k, 10)
        used[base] += 1
    seen: set[str] = set()
    for k in keys:
        base = slug_base(k)
        if not base or not has_latin(k):
            base = "maker-" + sha(k, 10)
        slug = base if (used[base] == 1 and base not in seen) else f"{base}-{sha(k, 6)}"
        while slug in seen:
            slug = f"{slug}-{sha(k + slug, 4)}"
        seen.add(slug)
        out[k] = slug
    return out


def connect_ro() -> sqlite3.Connection:
    uri = "file:" + str(DB.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    con = connect_ro()

    # 1) 读产品 → 厂家；产品市场分布
    products = [dict(r) for r in con.execute(
        "SELECT product_id, country, mah, source_id FROM product")]
    raw_counter: Counter[str] = Counter()
    key_display: dict[str, Counter[str]] = defaultdict(Counter)   # key → 原始写法计数
    key_products: dict[str, set[str]] = defaultdict(set)
    key_markets: dict[str, Counter[str]] = defaultdict(Counter)
    key_map: dict[str, str] = {}                                  # product_id → key
    n_null = 0
    for p in products:
        raw = (p["mah"] or "").strip()
        if not raw:
            n_null += 1
            continue
        raw_counter[raw] += 1
        k = norm_key(raw)
        key_display[k][raw] += 1
        key_products[k].add(p["product_id"])
        key_markets[k][p["country"]] += 1
        key_map[p["product_id"]] = k

    # 2) 品牌数（trade 名 key）+ 样本
    con.execute("PRAGMA query_only=ON")
    key_brands: dict[str, set[str]] = defaultdict(set)
    brand_counter: dict[str, Counter[str]] = defaultdict(Counter)
    pid2trade: dict[str, list[str]] = defaultdict(list)
    # 一次性读 product_name（只 trade）
    for r in con.execute("""SELECT pn.product_id, nk.norm FROM product_name pn
                            JOIN name_key nk ON nk.key_id=pn.key_id
                            WHERE pn.name_type='trade'"""):
        k = key_map.get(r["product_id"])
        if not k:
            continue
        brand = r["norm"]
        pid2trade[r["product_id"]].append(brand)
        if brand not in key_brands[k]:
            key_brands[k].add(brand)
            brand_counter[k][brand] += 1

    # 3) 逐 key 组装
    rows = []
    for k, products_set in key_products.items():
        raw = key_display[k].most_common(1)[0][0]
        ph, ph_reason = is_placeholder(raw, k)
        markets = dict(key_markets[k].most_common())
        rows.append({
            "maker_name": raw,
            "maker_key": k,
            "n_products": len(products_set),
            "n_markets": len(markets),
            "markets": ";".join(f"{c}:{n}" for c, n in list(markets.items())[:10]),
            "n_brands": len(key_brands.get(k, set())),
            "sample_brands": " / ".join(b for b, _ in brand_counter[k].most_common(5)),
            "is_placeholder": 1 if ph else 0,
            "placeholder_rule": ph_reason,
            "has_page": 1 if (not ph and len(products_set) >= MIN_PRODUCTS) else 0,
        })
    rows.sort(key=lambda r: (-r["n_products"], r["maker_name"]))

    # 4) slug（只给需要建页/全部？全部也给，便于黑名单核对；但 CSV 只保留非占位 + 占位示例？）
    keys_order = [r["maker_key"] for r in rows]
    slug_map = make_slugs(keys_order)
    for r in rows:
        r["slug"] = slug_map[r["maker_key"]]
        r["has_page"] = int(r["has_page"])

    pages = [r for r in rows if r["has_page"] == 1]
    placeholders = [r for r in rows if r["is_placeholder"] == 1]
    too_few = [r for r in rows if not r["is_placeholder"] and r["n_products"] < MIN_PRODUCTS]

    out_rows = pages + too_few + placeholders   # 全部落盘，has_page 区分
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        cols = ["maker_name", "maker_key", "slug", "n_products", "n_markets", "markets",
                "n_brands", "sample_brands", "is_placeholder", "placeholder_rule", "has_page"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    # 5) 黑名单 JSON
    black = {
        "generated_at": TODAY,
        "db": str(DB),
        "note": ("占位/不可建页厂家黑名单。build.py 生成厂家页时应跳过 is_placeholder=1 的厂家；"
                 "Special Order 家族 = 药品未备货时的代订占位，不是真实生产厂家。"),
        "min_products_for_page": MIN_PRODUCTS,
        "rules": {
            "exact": sorted(PLACEHOLDER_EXACT),
            "contains": list(PLACEHOLDER_CONTAINS),
            "heuristics": ["n_products<2 不建页（too_few）", "空 mah 不建页",
                           "纯数字/纯符号/长度<=2 视为占位"],
        },
        "entries": [{"maker": r["maker_name"], "maker_key": r["maker_key"],
                     "n_products": r["n_products"], "rule": r["placeholder_rule"],
                     "raw_forms": sorted(key_display[r["maker_key"]])[:10]}
                    for r in placeholders],
    }
    OUT_BLACK.write_text(json.dumps(black, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6) 统计
    n_raw = len(raw_counter)
    n_keys = len(rows)
    n_pages = len(pages)
    n_too_few = len(too_few)
    n_ph = len(placeholders)
    n_ph_products = sum(r["n_products"] for r in placeholders)
    n_cjk = sum(1 for r in rows if not has_latin(r["maker_key"]))
    n_multi_market = sum(1 for r in pages if r["n_markets"] >= 2)
    slug_collisions = n_keys - len(set(r["slug"] for r in rows))
    stats = {
        "generated_at": TODAY, "db": str(DB),
        "products_total": len(products), "products_with_mah": len(products) - n_null,
        "products_null_mah": n_null,
        "distinct_raw_mah": n_raw,
        "raw_mah_min_2_products": sum(1 for v in raw_counter.values() if v >= MIN_PRODUCTS),
        "distinct_normalized_makers": n_keys,
        "normalization_merged": n_raw - n_keys,
        "placeholders": n_ph,
        "placeholder_products": n_ph_products,
        "too_few_products": n_too_few,
        "page_candidates": n_pages,
        "page_candidates_multi_market": n_multi_market,
        "page_thresholds": {
            str(t): sum(1 for r in rows if not r["is_placeholder"] and r["n_products"] >= t)
            for t in (2, 3, 5, 10, 50)
        },
        "non_latin_makers": n_cjk,
        "slug_collisions": slug_collisions,
        "top_makers": [{"maker": r["maker_name"], "slug": r["slug"],
                        "n_products": r["n_products"], "n_markets": r["n_markets"],
                        "n_brands": r["n_brands"]} for r in pages[:30]],
        "top_placeholders": [{"maker": r["maker_name"], "n_products": r["n_products"],
                              "rule": r["placeholder_rule"]} for r in
                             sorted(placeholders, key=lambda r: -r["n_products"])[:10]],
        "by_country_distinct_raw": {r["country"]: r["d"] for r in con.execute(
            """select country, count(distinct mah) d from product
               where mah is not null and trim(mah)<>'' group by country""")},
    }
    (EVID / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                     encoding="utf-8")

    print("=== 厂家页数据准备 ===")
    print(f"产品 {len(products):,}（mah 空 {n_null:,}）| 原始 distinct mah {n_raw:,}"
          f" → 规范化厂家 {n_keys:,}（合并 {n_raw - n_keys:,}）")
    print(f"占位厂家 {n_ph:,}（覆盖 {n_ph_products:,} 产品）| 仅 1 产品厂家 {n_too_few:,}"
          f" | 非拉丁名厂家 {n_cjk:,}")
    print(f"**可建页厂家 {n_pages:,}**（≥{MIN_PRODUCTS} 产品、非占位；其中跨市场 "
          f"{n_multi_market:,}）| slug 冲突 {slug_collisions}")
    print(f"→ {OUT_CSV.relative_to(ROOT)}  {len(out_rows):,} 行")
    print(f"→ {OUT_BLACK.relative_to(ROOT)}  {n_ph:,} 条黑名单")
    print("\nTop 15 可建页厂家：")
    for r in pages[:15]:
        print(f"  {r['slug']:<44} {r['maker_name'][:46]:<48} {r['n_products']:>5} 产品"
              f"  {r['n_markets']} 市场  {r['n_brands']} 品牌")
    print("\n占位样例：")
    for e in black["entries"][:6]:
        print("  ", e)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
