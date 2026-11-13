"""T15 只读清单：精度归整建议 + 名称-规格冲突（只出清单，不写库）。

做两件事，都只读 `data/drugs.db`（sqlite3 URI `mode=ro`），不改任何数据、不改索引：

1. **精度归整建议**（用户评审 §1.5「499.9996 mg」）：组件强度落在常用整数档位附近、
   且偏差同时满足「绝对值 ≤ 0.01」「相对值 ≤ 0.01%」时，给一个建议显示值。
   **原始值不动**：清单只是给显示层用的候选，写库/数据包仍保留原值。
2. **名称-规格冲突**（§1.4「250 mg 分组下出现名称含 1000」）：商品名里抽到的强度 token
   与该产品结构化 `product_component` 的强度对不上（量纲归一、多种写法解析后仍对不上）。
   判定门槛按 T10 §6.1：**只有「同一 name_key 下所有单方产品共享唯一规格」的键才参与判定**，
   多规格键（如 `panadol` 键下 160/325/500/1000 mg 并存）一律排除；再排除
   盐型基准 / 名称自述另一基准 / 组合装枚举三类不可比情形，收窄前后数字都会打印。
   只出清单供人工复核，不判断哪个值对、不做结论性改写。

> 冲突清单是**候选集**，现库 `variant.base_fraction` 全为 1.0（碱基折算没数据），
> 抽样约 7 成属「同一支药不同计量基准」的误报，消费前请看
> `reports/2026-11-14-t15-spec-lists.md` §6 的误报风险。

用法（在仓库根跑）：

    & $py db/list_spec_issues.py                 # 两份 CSV 都出，落到 data/sources/
    & $py db/list_spec_issues.py --date 20261114 # 钉死文件名里的日期，便于复跑比对
    & $py db/list_spec_issues.py --only conflict # 只出其中一份

边界：不做用药建议、不做剂量换算、不改 `product_name` / `product_component`。
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "drugs.db"
OUT_DIR = ROOT / "data" / "sources"
BJ = ZoneInfo("Asia/Shanghai")

# ---------------------------------------------------------------- 精度归整规则

# 常用整数档位：药品标签上真正会出现的整数强度（mg / mcg / IU 等）。
PRECISION_TIERS: tuple[int, ...] = (
    10, 20, 25, 40, 50, 100, 125, 200, 250, 300, 400, 500, 600, 750, 800, 1000,
)
# 双阈值：绝对偏差与相对偏差都要小，才算「浮点/换算残渣」而不是真实剂量。
PRECISION_ABS_TOL = 0.01        # 绝对值 ≤ 0.01（单位同原值的单位）
PRECISION_REL_TOL = 0.0001      # 相对值 ≤ 0.01%

# 预筛 SQL：任何档位命中都必然满足 |v - round(v)| ≤ 0.01，先让 SQLite 砍掉 97% 的整数行。
PRECISION_SQL = """
SELECT pc.product_id, pc.ord, v.substance_id, s.inn_en, p.country,
       pc.strength_value, pc.strength_unit, pc.per_volume_value, pc.per_volume_unit
  FROM product_component pc
  JOIN product   p ON p.product_id = pc.product_id
  JOIN variant   v ON v.variant_id = pc.variant_id
  JOIN substance s ON s.substance_id = v.substance_id
 WHERE pc.strength_value IS NOT NULL
   AND pc.strength_value > 0
   AND ABS(pc.strength_value - ROUND(pc.strength_value)) <= ?
 ORDER BY p.country, pc.product_id, pc.ord
"""

PRECISION_HEADER: tuple[str, ...] = (
    "product_id", "ord", "substance_id", "inn_en", "country",
    "strength_value", "strength_unit", "per_volume_value", "per_volume_unit",
    "suggested_display",
)

# ---------------------------------------------------------------- 名称-规格规则

# 名称里的强度写法：数字（可能带 FR 的空格千分位）+ 单位。
# 单位族按 Lead 的 T10 口径取 mg|g|mcg|ml|iu|ui|%：同族内换算后比数值，
# 其它写法（cellules、log10 TCID50、mEq…）在结构化侧语义不同，跳过不比对。
_NUM = r"\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?"
TOKEN_RE = re.compile(
    r"(?P<num>" + _NUM + r")\s*"
    r"(?P<unit>microgrammes?|micrograms?|µg|μg|mcg|mg|grammes?|grams?|g|"
    r"ml|l|%|U\.I\.|UI|IU|unités?|units?)(?![\w/])",
    re.IGNORECASE,
)

# 单位 → (量纲, 折算到量纲基准的系数)。质量基准 = mg、体积基准 = mL、活性基准 = IU、百分比基准 = %。
# 折算只用于「同量纲比较」，不是剂量换算：结论只写「名称与结构化规格是否一致」。
UNIT_FACTOR: dict[str, tuple[str, float]] = {
    "mg": ("mass", 1.0),
    "g": ("mass", 1000.0),
    "gramme": ("mass", 1000.0),
    "grammes": ("mass", 1000.0),
    "gram": ("mass", 1000.0),
    "grams": ("mass", 1000.0),
    "mcg": ("mass", 0.001),
    "µg": ("mass", 0.001),
    "μg": ("mass", 0.001),
    "microgramme": ("mass", 0.001),
    "microgrammes": ("mass", 0.001),
    "microgram": ("mass", 0.001),
    "micrograms": ("mass", 0.001),
    "iu": ("activity", 1.0),
    "ui": ("activity", 1.0),
    "u.i.": ("activity", 1.0),
    "unité": ("activity", 1.0),
    "unités": ("activity", 1.0),
    "unit": ("activity", 1.0),
    "units": ("activity", 1.0),
    "ml": ("volume", 1.0),
    "l": ("volume", 1000.0),
    "%": ("percent", 1.0),
}
# 名称-规格比较的容差与精度归整保持一致：0.01 绝对 + 0.01% 相对。
# 这样「100 mg 的名称 ↔ 100.008 mg 的结构化值」只进精度清单，不会被两边同时记账。
VALUE_EPS = 1e-6

# 名称自己声明了「强度按另一个基准计」→ 数字对不上是预期内的，本规则不适用：
#   "terbinafine 250mg (as hydrochloride)"、"pantoprazole (as sodium sesquihydrate) 40 mg"、
#   "alendronate sodium trihydrate (equivalent to 70 mg alendronic acid)"
NAME_OTHER_BASIS_RE = re.compile(
    r"\(\s*(?:as|equivalent\s+to|equiv\.?\s+to)\b"
    r"|\bequivalent\s+to\b"
    r"|\bas\s+(?:the\s+)?[a-z]",
    re.IGNORECASE,
)

# 组合装 / 起始装 / 套装：名称把多个规格枚举出来（"5mg+10 mg+15 mg+20"、
# "15mg transdermal patches + 2mg medicated gum"），结构化侧只记一个规格，无法一对一比。
NAME_PACK_ENUM_RE = re.compile(
    r"(?:\d|[a-z])\s*(?:mg|g|mcg|microgrammes?|micrograms?|µg|μg|iu|ui|u\.i\.|units?|unités?)"
    r"\s*\+",
    re.IGNORECASE,
)

# 一行一个组件（含盐型/折算信息）；名称单独取，避免组件数与名称数相乘造成重复计数。
CONFLICT_COMPONENT_SQL = """
SELECT pc.product_id, p.country, p.form_base, pc.ord, pc.strength_value, pc.strength_unit,
       pc.per_volume_value, pc.per_volume_unit, COALESCE(v.base_fraction, 1.0),
       COALESCE(v.salt, ''), COALESCE(v.hydrate, ''), COALESCE(v.ester, '')
  FROM product_component pc
  JOIN product p ON p.product_id = pc.product_id
  LEFT JOIN variant v ON v.variant_id = pc.variant_id
 ORDER BY pc.product_id, pc.ord
"""

CONFLICT_NAME_SQL = """
SELECT pn.product_id, pn.key_id, nv.raw
  FROM product_name pn
  JOIN name_variant nv ON nv.key_id = pn.key_id
 WHERE pn.name_type = 'trade'
 ORDER BY pn.product_id, pn.key_id, nv.raw
"""

CONFLICT_HEADER: tuple[str, ...] = (
    "product_id", "country", "product_name", "name_strength_token",
    "structured_strength", "form_base", "reason",
)


# ---------------------------------------------------------------- 只读开库


def ro_connect(db_path: Path) -> sqlite3.Connection:
    """只读打开 SQLite（URI mode=ro），任何写操作都会直接报错。"""
    if not db_path.exists():
        raise SystemExit(f"找不到数据库：{db_path}（本脚本不会建库，请先确认 data/drugs.db 在）")
    return sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True)


def beijing_today() -> str:
    """北京今天的 YYYYMMDD（文件名用；北京时间定日期，避免跨时区差一天）。"""
    return datetime.now(BJ).strftime("%Y%m%d")


# ---------------------------------------------------------------- 精度归整


def match_tier(value: float) -> int | None:
    """返回命中的常用档位；不命中或正好等于档位（无需归整）时返回 None。"""
    for tier in PRECISION_TIERS:
        diff = abs(value - tier)
        if diff == 0:
            return None                     # 本来就整齐，不用给建议
        if diff <= PRECISION_ABS_TOL and diff <= PRECISION_REL_TOL * tier:
            return tier
    return None


def suggested_display(tier: int, unit: str | None) -> str:
    """拼建议显示值：档位整数 + 原单位（单位为空时只出数字）。"""
    unit = (unit or "").strip()
    return f"{tier} {unit}".strip()


def build_precision_rows(db: sqlite3.Connection) -> list[dict[str, str]]:
    """产出精度归整建议行（只建议显示值，原始强度原样带出）。"""
    out: list[dict[str, str]] = []
    for (product_id, ord_, substance_id, inn_en, country,
         value, unit, per_vol, per_vol_unit) in db.execute(PRECISION_SQL, (PRECISION_ABS_TOL,)):
        tier = match_tier(float(value))
        if tier is None:
            continue
        out.append({
            "product_id": product_id,
            "ord": str(ord_),
            "substance_id": substance_id,
            "inn_en": inn_en or "",
            "country": country or "",
            "strength_value": repr(float(value)),
            "strength_unit": unit or "",
            "per_volume_value": "" if per_vol is None else repr(float(per_vol)),
            "per_volume_unit": per_vol_unit or "",
            "suggested_display": suggested_display(tier, unit),
        })
    return out


# ---------------------------------------------------------------- 名称-规格冲突


def normalize_unit(raw_unit: str) -> tuple[str, float] | None:
    """单位归一：返回 (量纲, 折算系数)；不认识的单位返回 None（该 token 直接跳过）。"""
    return UNIT_FACTOR.get(raw_unit.strip().lower().rstrip("."))


def numeric_candidates(num_text: str) -> list[float]:
    """把名称里的数字文本拆成候选值。

    商品名里的逗号/空格既可能是千分位（`1 000`、`5,000`），也可能是小数点
    （法语 `2,5`），还可能只是品牌名里的编号（`A 313`、`CACIT VITAMINE D3`）。
    为了不把品牌数字当成剂量误报，这里把所有合理解析都算候选，只要有一个能在
    结构化规格里找到，就不算冲突。
    """
    groups = [g for g in re.split(r"[ \u00a0\u202f]", num_text.strip()) if g]
    if not groups:
        return []
    cands: list[float] = []
    for start in range(len(groups)):
        joined = "".join(groups[start:])
        variants = [joined.replace(",", ".")]                 # 逗号当小数点（法语）
        if re.search(r",\d{3}(?:\D|$)", joined):
            variants.append(joined.replace(",", ""))          # 逗号当千分位（英语）
        for text in variants:
            try:
                value = float(text)
            except ValueError:
                continue
            if value > 0 and value not in cands:
                cands.append(value)
    return cands


def extract_tokens(name: str) -> list[tuple[str, str, list[float]]]:
    """抽出名称里的强度 token：[(原始写法, 量纲, [候选值...])]，只保留质量 / 活性量纲。

    紧跟 `/` 之后的数字是分母（`500 mg/100 g`、`150 mg/1.5 mg per g`），
    代表浓度而不是强度，直接跳过——否则整条浓度写法都会被当成剂量比对。
    """
    tokens: list[tuple[str, str, list[float]]] = []
    for m in TOKEN_RE.finditer(name):
        if m.start() > 0 and name[m.start() - 1] in "/":
            continue
        norm = normalize_unit(m.group("unit"))
        if norm is None:
            continue
        dim, factor = norm
        cands = [v * factor for v in numeric_candidates(m.group("num"))]
        if not cands:
            continue
        tokens.append((f"{m.group('num').strip()} {m.group('unit')}", dim, cands))
    return tokens


Component = tuple[float, str, float | None, str | None, float]
# (strength_value, strength_unit, per_volume_value, per_volume_unit, base_fraction)


def close_enough(cand: float, ref: float) -> bool:
    """同量纲值比较：用与精度归整同一套容差（0.01 绝对 / 0.01% 相对）。"""
    diff = abs(cand - ref)
    return diff <= VALUE_EPS or diff <= PRECISION_ABS_TOL or diff <= PRECISION_REL_TOL * abs(ref)


def format_strength(components: list[Component]) -> str:
    """把结构化规格拼成可读文本：`500 mg` / `250 mg/100 mg` / `960 mg/30 mL`。"""
    parts: list[str] = []
    for value, unit, per_vol, per_vol_unit, _base in components:
        text = f"{value:g} {unit}".strip()
        if per_vol:
            text += f"/{per_vol:g} {per_vol_unit or ''}".rstrip()
        parts.append(text)
    return "/".join(parts) if parts else ""


def build_conflict_rows(db: sqlite3.Connection) -> tuple[list[dict[str, str]], Counter[str]]:
    """产出名称-规格冲突行（口径：**同一 name_key 下所有单方产品共享唯一规格**）。

    判定式（最终版，T10 §6.1）：
      1. 只取 `name_type='trade'` 的名称；
      2. 一个 name_key 只有在该 key 下的**单方产品**（组件数恰为 1）共享**唯一**
         `(strength_value, strength_unit)` 时才可判定 —— 多规格键（如 `panadol` 键下
         160/325/500/1000 mg 并存）一律排除，避免「PANADOL TABLET 500 mg 挂在 160 mg
         液体上」这类假阳性；
      3. 名称里的数字 + 单位按单位族（mg|g|mcg|ml|l|iu|ui|%）换算到同量纲后比数值，
         容差与精度清单一致（≤0.01 或 ≤0.01%）；
      4. 不一致才出行，`reason` 里带上该 key 的规格数与产品数，便于复核。

    另外三条「同一支药、不同计量基准」的排除（会单独计数打印，可用 `--strict` 关掉）：
      * 结构化强度带盐型 / 水合物 / 酯（`variant.salt|hydrate|ester` 非空）；
      * 名称自己声明了另一基准（`(as hydrochloride)`、`equivalent to …`）；
      * 名称用 `+` 枚举多个规格（组合装 / 起始装 / 套装）。
    """
    # 产品 → 组件 / 国家 / 剂型 / 盐型标记
    products: dict[str, dict[str, object]] = {}
    for (product_id, country, form_base, ord_, value, unit,
         per_vol, per_vol_unit, base_fraction, salt, hydrate, ester) in db.execute(CONFLICT_COMPONENT_SQL):
        rec = products.get(product_id)
        if rec is None:
            rec = {"country": country or "", "form_base": form_base or "",
                   "components": [], "salt_basis": False}
            products[product_id] = rec
        if salt or hydrate or ester:
            rec["salt_basis"] = True
        if value is None:
            continue
        comps = rec["components"]
        assert isinstance(comps, list)
        comps.append((ord_, float(value), unit or "",
                      None if per_vol is None else float(per_vol),
                      per_vol_unit, float(base_fraction or 1.0)))

    # 名称：product -> {key_id: [raw...]}
    names: dict[str, dict[str, list[str]]] = {}
    for product_id, key_id, raw in db.execute(CONFLICT_NAME_SQL):
        product_names = names.setdefault(product_id, {})
        raws = product_names.setdefault(key_id, [])
        if raw not in raws:
            raws.append(raw)

    # key → 该 key 下的产品
    key_products: dict[str, set[str]] = {}
    for product_id, product_names in names.items():
        for key_id in product_names:
            key_products.setdefault(key_id, set()).add(product_id)

    stats: Counter[str] = Counter()
    stats["keys_total"] = len(key_products)

    # key → 唯一规格（只由单方产品定义）；多规格键直接排除
    key_spec: dict[str, tuple[float, str]] = {}
    for key_id, product_ids in key_products.items():
        specs: set[tuple[float, str]] = set()
        for product_id in product_ids:
            comps = products.get(product_id, {}).get("components") or []
            if len(comps) == 1:
                _ord, value, unit, _pv, _pvu, _bf = comps[0]
                specs.add((value, unit.strip().lower()))
        if len(specs) == 1:
            key_spec[key_id] = next(iter(specs))
        elif len(specs) > 1:
            stats["keys_multi_spec"] += 1
        else:
            stats["keys_no_single_product"] += 1
    stats["keys_unique_spec"] = len(key_spec)

    rows: list[dict[str, str]] = []
    for product_id in sorted(names):
        rec = products.get(product_id)
        if rec is None:
            continue
        comps = rec["components"]
        assert isinstance(comps, list)
        ordered = sorted(comps, key=lambda c: c[0])
        structured = format_strength([(v, u, pv, pvu, bf) for _o, v, u, pv, pvu, bf in ordered])
        for key_id, raws in names[product_id].items():
            key_specs = key_spec.get(key_id)
            for raw in raws:
                stats["names_scanned"] += 1
                if len(comps) != 1:
                    stats["skip_combination_product"] += 1
                    continue
                if key_specs is None:
                    stats["skip_key_not_unique_spec"] += 1
                    continue
                tokens = extract_tokens(raw)
                if not tokens:
                    stats["skip_no_token"] += 1
                    continue
                _ord, spec_value, spec_unit, _pv, _pvu, _bf = comps[0]
                norm = normalize_unit(spec_unit)
                if norm is None:
                    stats["skip_spec_unit_not_comparable"] += 1
                    continue
                spec_dim, spec_factor = norm
                bad: list[str] = []
                for raw_token, dim, cands in tokens:
                    if dim != spec_dim:
                        stats["skip_token_other_dimension"] += 1
                        continue
                    if any(close_enough(c, spec_value * spec_factor) for c in cands):
                        continue
                    bad.append(raw_token)
                if not bad:
                    stats["matched_ok"] += 1
                    continue
                stats["hit_literal"] += 1
                if rec["salt_basis"]:
                    stats["drop_salt_basis"] += 1
                    continue
                if NAME_OTHER_BASIS_RE.search(raw):
                    stats["drop_declared_basis"] += 1
                    continue
                if NAME_PACK_ENUM_RE.search(raw):
                    stats["drop_pack_enum"] += 1
                    continue
                rows.append({
                    "product_id": product_id,
                    "country": str(rec["country"]),
                    "product_name": raw,
                    "name_strength_token": " + ".join(bad),
                    "structured_strength": structured,
                    "form_base": str(rec["form_base"]),
                    "reason": (f"name_token_not_in_key_spec;key_specs=1;"
                               f"key_products={len(key_products[key_id])};"
                               f"key_spec={spec_value:g} {spec_unit}".strip()),
                })
    return rows, stats


# ---------------------------------------------------------------- 输出


def write_csv(path: Path, header: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    """写 CSV：UTF-8 + 换行 LF，字段固定顺序，缺失值写空串。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(header), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in header})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T15 只读清单：精度归整建议 + 名称-规格冲突")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="数据库路径（默认 data/drugs.db，只读打开）")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR, help="CSV 输出目录（默认 data/sources/）")
    parser.add_argument("--date", default=beijing_today(), help="文件名日期 YYYYMMDD（默认北京今天）")
    parser.add_argument("--only", choices=("precision", "conflict"), help="只生成其中一份清单")
    args = parser.parse_args(argv)

    db = ro_connect(args.db)
    try:
        if args.only != "conflict":
            rows = build_precision_rows(db)
            path = args.out_dir / f"precision_normalize_{args.date}.csv"
            write_csv(path, PRECISION_HEADER, rows)
            by_country = Counter(r["country"] for r in rows)
            print(f"[精度归整] {len(rows)} 行 → {path.relative_to(ROOT)}")
            print(f"           档位={len(PRECISION_TIERS)} 个，容差=±{PRECISION_ABS_TOL} 且 ≤{PRECISION_REL_TOL:.2%}")
            print("           按国家：" + "、".join(f"{k or '空'}:{v}" for k, v in by_country.most_common()))
            print("           按建议值：" + "、".join(
                f"{k}:{v}" for k, v in Counter(r["suggested_display"] for r in rows).most_common()))
        if args.only != "precision":
            rows, stats = build_conflict_rows(db)
            path = args.out_dir / f"name_spec_conflict_{args.date}.csv"
            write_csv(path, CONFLICT_HEADER, rows)
            by_country = Counter(r["country"] for r in rows)
            print(f"[名称-规格冲突] 收窄后 {len(rows)} 行 → {path.relative_to(ROOT)}")
            print(f"           name_key {stats['keys_total']} 个：唯一规格 {stats['keys_unique_spec']}、"
                  f"多规格排除 {stats['keys_multi_spec']}、无单方产品 {stats['keys_no_single_product']}")
            print(f"           扫过 trade 名称 {stats['names_scanned']} 条：复方产品 {stats['skip_combination_product']}、"
                  f"键非唯一规格 {stats['skip_key_not_unique_spec']}、无强度 token {stats['skip_no_token']}、"
                  f"规格单位不可比 {stats['skip_spec_unit_not_comparable']}、"
                  f"量纲不同 {stats['skip_token_other_dimension']}、一致 {stats['matched_ok']}、"
                  f"按字面命中 {stats['hit_literal']}")
            print(f"           字面命中后排除：盐型/水合物基准 {stats['drop_salt_basis']}、"
                  f"名称自述另一基准 {stats['drop_declared_basis']}、"
                  f"名称枚举多规格 {stats['drop_pack_enum']}")
            print("           按国家：" + "、".join(f"{k or '空'}:{v}" for k, v in by_country.most_common()))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
