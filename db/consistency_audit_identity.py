"""名称 / 成分 / 状态 / 来源 一致性审计（只读）。

背景：用户报「力度伸是 VC 泡腾片，站点显示片剂」后追问「肯定还有别的类似的问题」。
本脚本只查 **名称 / 成分 / 状态 / 来源** 这一侧的自相矛盾，不碰剂型规格口径
（剂型/规格由另一路审计负责，这里只在「名字里写了剂型但 form_base 不符」时出数）。

八条规则（每条输出：条数 / 样例 / 分布 / 修法归类 / 能否自动修）：

1. 品牌被当成成分：`substance.inn_en` 实为商品名；`product_name.name_type='inn'`
   与所属成分的 `inn_en` 不一致；名称写「复方」但只登记了 1 个成分。
2. 名称里带剂型词（泡腾/缓释/…/注射液）但 `product.form_base` / `release` 不符。
3. 中文名缺失：`substance.inn_zh` 缺失（按 ATC 大类）；`name_lang` 为空 / 与文本不符。
4. 状态自相矛盾：状态与 `status_date` 冲突、同一 approval_id 状态冲突、
   同成分同国家 active/withdrawn 并存。
5. 来源与市场错配：`source_id × country` 非对角项。
6. 同名不同药被命名差异放大：`collision` severe 里本应同一成分的候选。
7. `name_key.script` 与文本实际字符集不符。
8. 重复名称：同一 `norm` / `raw` / `compact` 对应多个 key。

用法：
    & $py db/consistency_audit_identity.py                 # 人读摘要
    & $py db/consistency_audit_identity.py --json out.json # 附带机器可读结果

只读：`file:data/drugs.db?mode=ro`；不写库、不构建、不改任何数据文件。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "drugs.db"
ALIAS_CSV = ROOT / "data" / "substance_aliases.csv"
MARKETS_JSON = ROOT / "data" / "markets.json"

# ── 修法归类（固定五个取值，报告与 JSON 共用） ──────────────────────────────
FIX_RULE = "规则"        # 入库/建站时按规则重算，可自动
FIX_MIGRATE = "迁移"     # 需要一次性数据迁移（改名/合并/回填），脚本可生成清单
FIX_DISPLAY = "显示层"   # 数据不动，页面上标注/降级展示
FIX_SOURCE = "来源本身"  # 源数据没有这个信息，改不了
FIX_DROP = "丢弃计数"    # 判不了、不猜：丢弃并计数，不手工标注单条

# ── 规则 2：名称里的剂型词 → (正则, 允许的 form_base, 期望 release) ──────────
# 用词形而不是单字：「乳」会撞「乳果糖/乳酸」，「栓」会撞「血栓」，「贴」会撞「贴现」这类。
# 只匹配名称文本（norm + 全部 name_variant.raw），不匹配 dosage_form 字段。
FORM_WORDS: dict[str, tuple[re.Pattern[str], frozenset[str], frozenset[str] | None]] = {
    "泡腾": (re.compile("泡腾"), frozenset({"tablet", "powder", "capsule", "granule"}), None),
    "缓释": (re.compile("缓释"), frozenset(), frozenset({"ER", "SR", "MR", "GITS"})),
    "控释": (re.compile("控释"), frozenset(), frozenset({"ER", "SR", "MR", "GITS"})),
    "肠溶": (re.compile("肠溶"), frozenset(), frozenset({"DR"})),
    "口服液": (re.compile("口服液"), frozenset({"liquid"}), None),
    "滴剂": (re.compile("滴剂"), frozenset({"liquid"}), None),
    "胶囊": (re.compile("胶囊"), frozenset({"capsule"}), None),
    "咀嚼": (re.compile("咀嚼"), frozenset({"tablet", "gum, chewing"}), None),
    "喷雾": (re.compile("喷雾"), frozenset({"inhalation", "inhalant", "nasal", "topical"}), None),
    "栓": (re.compile("栓(剂)?$|栓剂"), frozenset({"suppository"}), None),
    "贴": (re.compile("贴(剂|膏|布)"), frozenset({"plaster", "topical", "cloth", "film"}), None),
    "膏": (re.compile("(软膏|乳膏|膏药|膏剂|膏$)"), frozenset({"topical", "salve"}), None),
    "乳": (re.compile("(乳膏|乳剂|乳液|乳胶|搽剂乳)"), frozenset({"topical", "liquid"}), None),
    "注射液": (re.compile("注射液|注射用"), frozenset({"injection", "powder"}), None),
}

# ── 规则 6：盐 / 酯 / 水合物词，用来判「只差盐型」 ──────────────────────────
# 只剥**词尾**盐型：Warfarin Sodium → warfarin、Atorvastatin Calcium → atorvastatin。
# 无机盐整名（Sodium Chloride / Magnesium Sulfate Heptahydrate）不剥，否则会剩下一个
# 元素名，把「氯化钠」和「枸橼酸钠」误判成同一成分。
SALT_SUFFIX = frozenset(
    {
        "hydrochloride", "dihydrochloride", "hcl", "hydrobromide", "dihydrobromide",
        "hbr", "sodium", "disodium", "potassium", "dipotassium", "calcium",
        "magnesium", "lithium", "zinc", "sulfate", "sulphate", "phosphate",
        "diphosphate", "acetate", "maleate", "citrate", "tartrate", "succinate",
        "besilate", "besylate", "mesylate", "mesilate", "tosylate", "fumarate",
        "hemifumarate", "nitrate", "bromide", "chloride", "iodide", "carbonate",
        "bicarbonate", "lactate", "gluconate", "oxalate", "salicylate", "benzoate",
        "propionate", "valerate", "dipropionate", "butyrate", "stearate",
        "palmitate", "oleate", "ester", "ethyl", "methyl", "anhydrous",
        "monohydrate", "dihydrate", "trihydrate", "hemihydrate", "hydrate",
        "heptahydrate", "pentahydrate", "sesquihydrate", "na", "k", "ca",
    }
)
# 名字第一个词是这些时，整名是无机盐/元素，不剥后缀。
INORGANIC_HEADS = frozenset(
    {
        "sodium", "potassium", "calcium", "magnesium", "lithium", "zinc",
        "aluminium", "aluminum", "iron", "barium", "copper", "selenium",
        "chloride", "iodine", "fluoride", "phosphate", "sulfate", "sulphate",
    }
)
STOPWORDS = frozenset(
    {"and", "with", "in", "for", "of", "the", "plus", "oral", "inj", "solution",
     "tablet", "tablets", "capsule", "capsules", "mg", "ml", "g", "iu"}
)
# form_base 的「不知道」取值：不能当作「与名称不符」。
UNKNOWN_FORMS = frozenset({"", "(空)", "unknown", "other"})

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3005]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
# 中文制剂通用名常见剂型后缀：这类名称天然不等于单一成分名，不算「对不上」。
FORM_SUFFIX_RE = re.compile(
    r"(片|胶囊|颗粒|软膏|乳膏|凝胶|注射液|注射用|口服液|滴眼液|滴剂|喷雾剂|气雾剂|"
    r"栓|贴|散|丸|糖浆|糊剂|洗剂|酊|搽剂|溶液|眼膏|胶浆|含片|咀嚼片)$"
)


def norm_name(name: str) -> str:
    """与 lib/aliases.norm 同一口径：小写、标点转空格、压缩空白。"""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (name or "").lower())).strip()


def compact_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def salt_tokens(name: str) -> frozenset[str]:
    return frozenset(t for t in norm_name(name).split() if t in SALT_SUFFIX)


def strip_salt(name: str) -> str:
    """去掉词尾盐型词（保留无机盐整名与至少一个实词）。"""
    tokens = norm_name(name).split()
    if tokens and tokens[0] in INORGANIC_HEADS:
        return " ".join(tokens)
    while len(tokens) > 1 and tokens[-1] in SALT_SUFFIX:
        tokens.pop()
    return " ".join(tokens)


def significant_tokens(name: str) -> set[str]:
    """名称里能标识成分的词（去掉盐型、停用词与过短词）。"""
    return {
        t
        for t in norm_name(name).split()
        if t not in SALT_SUFFIX and t not in STOPWORDS and len(t) >= 5
    }


def expected_script(text: str) -> str:
    """按文本实际字符集判定 script（CJK 优先于拉丁）。"""
    if HAN_RE.search(text):
        return "han"
    if KANA_RE.search(text):
        return "kana"
    if HANGUL_RE.search(text):
        return "hangul"
    if CYRILLIC_RE.search(text):
        return "cyrillic"
    return "latin"


def cjk_chars(text: str) -> str:
    return "".join(CJK_RE.findall(text or ""))


def common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """编辑距离（带上限提前退出）；用于区分拼写差异与完全对不上。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def connect_ro() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"找不到数据库：{DB_PATH}")
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


# ── 数据装载 ────────────────────────────────────────────────────────────────


def load(db: sqlite3.Connection) -> dict:
    """一次性装载审计需要的表（477k 产品 / 652k 名称，内存可承受，约 3 秒）。"""
    data: dict = {}

    data["substance"] = {
        r[0]: {"inn_en": r[1] or "", "inn_zh": r[2] or "", "atc": r[3] or "", "name_lang": r[4]}
        for r in db.execute(
            "SELECT substance_id, inn_en, inn_zh, atc, name_lang FROM substance"
        )
    }
    data["variant_sub"] = {
        r[0]: r[1] for r in db.execute("SELECT variant_id, substance_id FROM variant")
    }
    data["product"] = {
        r[0]: {
            "country": r[1],
            "region": r[2],
            "form_base": r[3] or "",
            "release": r[4] or "none",
            "status": r[5],
            "status_date": r[6],
            "source_id": r[7],
            "approval_id": r[8] or "",
            "dosage_form": r[9] or "",
        }
        for r in db.execute(
            "SELECT product_id, country, region, form_base, release, status,"
            " status_date, source_id, approval_id, dosage_form FROM product"
        )
    }
    prod_subs: dict[str, set[str]] = defaultdict(set)
    for pid, vid in db.execute("SELECT product_id, variant_id FROM product_component"):
        sid = data["variant_sub"].get(vid)
        if sid:
            prod_subs[pid].add(sid)
    data["prod_subs"] = prod_subs

    data["name_key"] = {
        r[0]: {"norm": r[1] or "", "compact": r[2] or "", "script": r[3], "lang": r[4]}
        for r in db.execute("SELECT key_id, norm, compact, script, lang FROM name_key")
    }
    key_raw: dict[str, list[str]] = defaultdict(list)
    raw_keys: dict[str, set[str]] = defaultdict(set)
    for kid, raw in db.execute("SELECT key_id, raw FROM name_variant"):
        key_raw[kid].append(raw or "")
        raw_keys[raw or ""].add(kid)
    data["key_raw"] = key_raw
    data["raw_keys"] = raw_keys

    data["product_name"] = list(
        db.execute("SELECT product_id, key_id, name_type FROM product_name")
    )
    data["key_products"] = defaultdict(list)
    data["product_names"] = defaultdict(list)
    for pid, kid, ntype in data["product_name"]:
        data["key_products"][kid].append((pid, ntype))
        data["product_names"][pid].append((kid, ntype))

    data["brand_keys"] = {r[0] for r in db.execute("SELECT key_id FROM name_family")}
    return data


def load_alias_groups() -> dict[str, str]:
    """data/substance_aliases.csv → {substance_id: 组代表 id}（并查集）。"""
    if not ALIAS_CSV.exists():
        return {}
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    with ALIAS_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            a = (row.get("canonical_id") or "").strip()
            b = (row.get("alias_id") or "").strip()
            if a and b:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
    return {k: find(k) for k in parent}


def load_alias_names() -> dict[str, set[str]]:
    """data/substance_aliases.csv → {substance_id: {同一成分的其它写法}}。"""
    out: dict[str, set[str]] = defaultdict(set)
    if not ALIAS_CSV.exists():
        return {}
    with ALIAS_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            a, b = (row.get("canonical_id") or "").strip(), (row.get("alias_id") or "").strip()
            if a and b:
                out[a].add(row.get("alias_inn") or "")
                out[b].add(row.get("canonical_inn") or "")
    return out


def load_market_sources() -> dict[str, str]:
    """data/markets.json → {source_id: market}（主源 + 辅助源）。"""
    if not MARKETS_JSON.exists():
        return {}
    raw = json.loads(MARKETS_JSON.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for m in raw.get("markets", []):
        for sid in [m.get("source_id"), *(m.get("extra_source_ids") or [])]:
            if sid:
                out.setdefault(str(sid), m["code"])
    return out


# ── 规则 1：品牌被当成成分 ──────────────────────────────────────────────────


def rule1_brand_as_ingredient(data: dict) -> dict:
    subs = data["substance"]
    keys = data["name_key"]
    key_products = data["key_products"]
    prod_subs = data["prod_subs"]
    base = {sid: strip_salt(s["inn_en"]) for sid, s in subs.items()}
    atc = {sid: s["atc"] for sid, s in subs.items()}

    # 1a：inn_en 带注册商标符号
    reg = [
        {"substance_id": sid, "inn_en": s["inn_en"]}
        for sid, s in subs.items()
        if re.search(r"[®™©]", s["inn_en"])
    ]

    # 1b：inn_en 与品牌家族（name_family，唯一人工表）里的商标写法相同
    brand_norms = {keys[k]["norm"] for k in data["brand_keys"] if k in keys}
    brand_hits = [
        {"substance_id": sid, "inn_en": s["inn_en"], "inn_zh": s["inn_zh"]}
        for sid, s in subs.items()
        if norm_name(s["inn_en"]) in brand_norms
    ]

    # 1c：这个字符串被「不含该成分」的产品当成 trade 名 → 该 substance 是品牌名。
    #     盐型拆分（同 base / 同 ATC4 / 同中文名）不算：那是 R6 的重复成分问题。
    trade_key_by_norm: dict[str, str] = {}
    for kid, k in keys.items():
        if any(nt == "trade" for _, nt in key_products.get(kid, ())):
            trade_key_by_norm.setdefault(k["norm"], kid)

    zh_c = {sid: cjk_chars(s["inn_zh"]) for sid, s in subs.items()}

    def different_drug(a: str, b: str) -> bool:
        if a == b:
            return False
        if base.get(a) and base.get(a) == base.get(b):
            return False
        aa, ab = atc.get(a, ""), atc.get(b, "")
        if len(aa) >= 4 and aa[:4] == ab[:4]:
            return False
        if zh_c.get(a) and zh_c.get(a) == zh_c.get(b):
            return False
        return True

    foreign_brand: list[dict] = []
    for sid, s in subs.items():
        kid = trade_key_by_norm.get(norm_name(s["inn_en"]))
        if not kid:
            continue
        foreign = set()
        for pid, nt in key_products.get(kid, ()):
            if nt != "trade":
                continue
            comps = prod_subs.get(pid) or set()
            if not comps:
                continue
            if any(different_drug(sid, x) for x in comps) and not any(
                not different_drug(sid, x) for x in comps
            ):
                foreign.add(pid)
        if foreign:
            foreign_brand.append(
                {
                    "substance_id": sid,
                    "inn_en": s["inn_en"],
                    "inn_zh": s["inn_zh"],
                    "atc": s["atc"],
                    "n_foreign_products": len(foreign),
                    "countries": sorted(
                        {
                            data["product"][p]["country"] or data["product"][p]["region"]
                            for p in foreign
                        }
                    ),
                }
            )
    foreign_brand.sort(key=lambda r: -r["n_foreign_products"])

    # 1d：name_type='inn' 但名称对不上该成分的通用名（en / zh / 异名表 / 西语词形）。
    #     口径：product_name 的 'inn' 允许是本地语言通用名（ES 的 atorvastatina、CN 的
    #     阿托伐他汀），所以先做四路匹配，再按证据类型分桶；判不了的进「丢弃计数」。
    alias_names = load_alias_names()

    def match_kind(knorm: str, sid: str) -> str:
        """名称与该成分通用名的匹配证据；'none' = 对不上。"""
        comp = compact_name(knorm)
        base_c = compact_name(base.get(sid, ""))
        if comp:
            if base_c and (base_c in comp or comp in base_c):
                return "contains"
            if significant_tokens(base.get(sid, "")) & significant_tokens(knorm):
                return "token_overlap"  # 复方 / 无机盐 / 多词名
        zc = cjk_chars(knorm)
        zh_c = cjk_chars(subs[sid]["inn_zh"])
        if zc and zh_c:
            if zc in zh_c or zh_c in zc:
                return "zh_contains"
            if any(zh_c[i : i + 3] in zc for i in range(len(zh_c) - 2)):
                return "zh_contains"  # 盐基长短不同：磷酸西格列汀 vs 西格列汀二甲双胍片
            if len(set(zc) & set(zh_c)) / max(len(set(zc)), 1) >= 0.6:
                return "zh_overlap"
        if comp:
            for alias in alias_names.get(sid, ()):
                ac = compact_name(alias)
                if ac and (ac in comp or comp in ac):
                    return "alias"
            if base_c and common_prefix(base_c, comp) >= 6:
                return "prefix"  # 西语/葡语词形（atorvastatin → atorvastatina）
            if base_c and len(base_c) <= 24 and edit_distance(base_c, comp) <= 2:
                return "spelling"
        return "none"

    inn_bad: list[dict] = []
    inn_bad_products: set[str] = set()
    per_country: Counter = Counter()
    buckets: Counter = Counter()
    bucket_samples: dict[str, list[dict]] = defaultdict(list)
    spelling_n = 0
    kinds: Counter = Counter()
    for pid, kid, ntype in data["product_name"]:
        if ntype != "inn":
            continue
        k = keys.get(kid)
        if not k:
            continue
        sids = prod_subs.get(pid) or set()
        if not sids:
            continue
        results = [match_kind(k["norm"], s) for s in sids]
        kinds.update(results)
        if any(r not in ("none", "spelling") for r in results):
            continue
        row = {
            "product_id": pid,
            "key_norm": k["norm"],
            "country": data["product"][pid]["country"],
            "component_inn": sorted(base.get(s, "") for s in sids),
        }
        if "spelling" in results:
            # 只差拼写（如 gaunfacine/guanfacine）：进异名表即可，不算身份错
            spelling_n += 1
            if len(bucket_samples["spelling"]) < 5:
                bucket_samples["spelling"].append(row)
            continue
        inn_bad.append(row)
        inn_bad_products.add(pid)
        per_country[data["product"][pid]["country"] or "?"] += 1
        zc = cjk_chars(k["norm"])
        if zc and any(cjk_chars(subs[s]["inn_zh"]) for s in sids):
            if FORM_SUFFIX_RE.search(k["norm"]):
                bucket = "中文名带剂型后缀（复方/制剂通用名，属正常，丢弃计数）"
            else:
                bucket = "中文名与成分 inn_zh 对不上（需核，可能是映射错）"
        elif zc:
            bucket = "成分缺中文名，中文名无法核对（丢弃计数）"
        elif len(sids) > 1:
            bucket = "复方/多成分名，别名表未覆盖（丢弃计数）"
        else:
            bucket = "拉丁名对不上（本地语言/顺势疗法/OTC 商品名，源语义，丢弃计数）"
        buckets[bucket] += 1
        if len(bucket_samples[bucket]) < 5:
            bucket_samples[bucket].append(row)

    # 1e：名称写「复方」但成分表只登记了 1 个成分（复方漏挂成分）
    combo_single: dict[str, dict] = {}
    for pid, kid, ntype in data["product_name"]:
        if ntype != "inn":
            continue
        k = keys.get(kid)
        if not k or "复方" not in k["norm"]:
            continue
        sids = prod_subs.get(pid) or set()
        if len(sids) != 1:
            continue
        combo_single.setdefault(
            k["norm"],
            {
                "key_norm": k["norm"],
                "country": data["product"][pid]["country"],
                "component_inn": sorted(base.get(s, "") for s in sids),
                "n_products": 0,
            },
        )["n_products"] += 1
    combo_single_rows = sorted(combo_single.values(), key=lambda r: -r["n_products"])

    return {
        "id": "R1",
        "title": "品牌被当成成分 / INN 名称与成分不符",
        "count": len(reg)
        + len(brand_hits)
        + len(foreign_brand)
        + len(inn_bad)
        + sum(r["n_products"] for r in combo_single_rows),
        "parts": {
            "inn_en 含 ®/™/©": {"count": len(reg), "samples": reg[:5]},
            "inn_en 等于品牌家族写法": {"count": len(brand_hits), "samples": brand_hits[:5]},
            "inn_en 被别家产品当 trade 名（品牌当成分）": {
                "count": len(foreign_brand),
                "samples": foreign_brand[:5],
            },
            "name_type=inn 与成分通用名对不上": {
                "count": len(inn_bad),
                "products": len(inn_bad_products),
                "by_country": dict(per_country.most_common()),
                "by_bucket": dict(buckets.most_common()),
                "bucket_samples": {k: v for k, v in bucket_samples.items()},
                "spelling_only": spelling_n,
                "match_kinds": dict(kinds.most_common()),
                "rows": inn_bad,
                "samples": inn_bad[:5],
            },
            "名称含「复方」但只登记 1 个成分": {
                "count": sum(r["n_products"] for r in combo_single_rows),
                "distinct_names": len(combo_single_rows),
                "samples": combo_single_rows[:5],
            },
        },
        "fix": FIX_MIGRATE,
        "actionable": {
            "品牌名/异名缺口（改名为成分或补 alias）": len(foreign_brand),
            "中文名映射错（需核后改映射）": buckets.get("中文名与成分 inn_zh 对不上（需核，可能是映射错）", 0),
            "拼写差异（补 data/substance_aliases.csv）": spelling_n,
        },
        "drop_counted": len(inn_bad)
        - buckets.get("中文名与成分 inn_zh 对不上（需核，可能是映射错）", 0),
        "fix_note": "®™ 可规则清洗（规则）；品牌当成分需改名/并入（迁移，先出清单）；"
        "name_type=inn 允许本地语言通用名（ES 的 atorvastatina、CN 的阿托伐他汀），"
        "按「包含 / 词重叠 / 中文连续 3 字 / 别名表 / 词形前缀」多路匹配后仍对不上的才计入；"
        "只差拼写的单列（补 data/substance_aliases.csv，不合并）；其余丢弃计数。",
        "auto_fixable": "部分（拼写类可自动补异名表；中文名映射错按 ATC/别名批量核；复方补成分需证据）",
    }


# ── 规则 2：名称带剂型词但字段不符 ──────────────────────────────────────────


def rule2_form_words(data: dict) -> dict:
    keys = data["name_key"]
    key_products = data["key_products"]
    products = data["product"]

    word_products: dict[str, set[str]] = {w: set() for w in FORM_WORDS}
    word_keys: dict[str, int] = {w: 0 for w in FORM_WORDS}
    for kid, k in keys.items():
        joined = "\n".join([k["norm"], *data["key_raw"].get(kid, [])])
        for w, (pat, _, _) in FORM_WORDS.items():
            if pat.search(joined):
                word_keys[w] += 1
                for pid, _ in key_products.get(kid, ()):
                    word_products[w].add(pid)

    matrix: dict[str, dict[str, int]] = {}
    samples: dict[str, list[dict]] = {}
    contradiction: set[str] = set()
    coarse: set[str] = set()  # 名称词在 dosage_form 原文里也有：form_base 粒度不足，不算矛盾
    pid_words: dict[str, set[str]] = defaultdict(set)
    for w, pids in word_products.items():
        for pid in pids:
            pid_words[pid].add(w)

    # 词 × form_base 分布（原始矩阵，按词统计）
    for w in FORM_WORDS:
        counter: Counter = Counter()
        for pid in word_products[w]:
            p = products.get(pid)
            if p:
                counter[p["form_base"] or "(空)"] += 1
        counter["__products__"] = len(word_products[w])
        counter["__keys__"] = word_keys[w]
        matrix[w] = dict(counter)

    # 逐个产品判：名称里所有剂型词的期望取并集（「肠溶缓释片」不能被判成矛盾）
    for pid, words in pid_words.items():
        p = products.get(pid)
        if not p:
            continue
        ok_forms: set[str] = set()
        ok_release: set[str] = set()
        for w in words:
            _, forms, rel = FORM_WORDS[w]
            ok_forms |= forms
            if rel:
                ok_release |= rel
        fb = p["form_base"] or "(空)"
        # 空 / unknown / other 是「不知道」，不是「不符」——不计矛盾
        form_bad = bool(ok_forms) and fb not in ok_forms and fb not in UNKNOWN_FORMS
        rel_bad = bool(ok_release) and (p["release"] or "none") not in ok_release
        if not (form_bad or rel_bad):
            continue
        # 归因到具体词：形态不符优先记形态词，否则记释放词
        word = next(
            (w for w in words if FORM_WORDS[w][1] and fb not in FORM_WORDS[w][1]),
            next((w for w in words if FORM_WORDS[w][2]), ""),
        )
        if any(w in (p["dosage_form"] or "") for w in words):
            coarse.add(pid)
            continue
        contradiction.add(pid)
        if len(samples.setdefault(word, [])) < 5:
            samples[word].append(
                {
                    "product_id": pid,
                    "word": word,
                    "country": p["country"] or p["region"],
                    "dosage_form": p["dosage_form"],
                    "form_base": p["form_base"],
                    "release": p["release"],
                    "name_evidence": _evidence_text(data, pid, word),
                }
            )

    for w in FORM_WORDS:
        matrix[w]["__contradiction__"] = sum(
            1
            for pid in word_products[w]
            if pid in contradiction
            and (
                (
                    bool(FORM_WORDS[w][1])
                    and (products[pid]["form_base"] or "(空)") not in FORM_WORDS[w][1]
                    and (products[pid]["form_base"] or "(空)") not in UNKNOWN_FORMS
                )
                or (
                    FORM_WORDS[w][2] is not None
                    and (products[pid]["release"] or "none") not in FORM_WORDS[w][2]
                )
            )
        )
        matrix[w]["__mismatch__"] = matrix[w]["__contradiction__"]
        samples.setdefault(w, [])

    return {
        "id": "R2",
        "title": "名称里带剂型词，但 form_base / release 不符",
        "count": len(contradiction),
        "matrix": matrix,
        "samples": samples,
        "coarse_count": len(coarse - contradiction),
        "fix": FIX_DISPLAY,
        "fix_note": "名称里的剂型词是源事实（包装/说明书），form_base 是归一化字段："
        "入库时按词表给名称打 form_qualifier（规则），显示层优先用名称原词；"
        "form_base 本身改不改由剂型规格审计决定，本报告不动。"
        "名称词在 dosage_form 原文里也有、只是 form_base 更粗的，单列为「粒度不足」，不计入矛盾。",
        "auto_fixable": "是（显示层/规则）",
    }


def _evidence_text(data: dict, pid: str, word: str) -> str:
    """给样例附上命中词所在的那条名称原文（任意 name_type）。"""
    for kid, _ntype in data["product_names"].get(pid, ()):
        for t in [data["name_key"].get(kid, {}).get("norm", ""), *data["key_raw"].get(kid, [])]:
            if word in t:
                return t[:48]
    return ""


# ── 规则 3：中文名缺失 / name_lang ─────────────────────────────────────────


def rule3_missing_zh(data: dict) -> dict:
    subs = data["substance"]
    miss = []
    all_by_class: Counter = Counter()
    miss_by_class: Counter = Counter()
    for sid, s in subs.items():
        cls = s["atc"][:1] if s["atc"] else "(无ATC)"
        all_by_class[cls] += 1
        if not s["inn_zh"].strip():
            miss_by_class[cls] += 1
            miss.append({"substance_id": sid, "inn_en": s["inn_en"], "atc": s["atc"]})

    top = [
        {
            "atc_class": cls,
            "missing": n,
            "total": all_by_class[cls],
            "rate": round(n / all_by_class[cls], 4) if all_by_class[cls] else 0,
        }
        for cls, n in miss_by_class.most_common(10)
    ]

    null_lang = [sid for sid, s in subs.items() if not s["name_lang"]]
    lang_bad = []
    for sid, s in subs.items():
        lang = s["name_lang"]
        if not lang:
            continue
        has_cjk = bool(CJK_RE.search(s["inn_en"]))
        if lang == "en" and has_cjk:
            lang_bad.append(
                {"substance_id": sid, "inn_en": s["inn_en"], "name_lang": lang, "issue": "标 en 但含 CJK"}
            )
        elif lang == "zh" and not has_cjk:
            lang_bad.append(
                {"substance_id": sid, "inn_en": s["inn_en"], "name_lang": lang, "issue": "标 zh 但无 CJK"}
            )

    return {
        "id": "R3",
        "title": "中文名缺失 / name_lang 与文本不符",
        "count": len(miss) + len(null_lang) + len(lang_bad),
        "parts": {
            "inn_zh 缺失": {
                "count": len(miss),
                "total_substances": len(subs),
                "top_atc_class": top,
                "samples": miss[:5],
            },
            "name_lang 为空": {"count": len(null_lang), "samples": null_lang[:5]},
            "name_lang 与文本不符": {"count": len(lang_bad), "samples": lang_bad[:5]},
        },
        "fix": FIX_SOURCE,
        "actionable": {
            "有 ATC 可按映射回填中文名": sum(1 for m in miss if m["atc"]),
            "无 ATC / 无标准中文名（丢弃计数）": sum(1 for m in miss if not m["atc"]),
        },
        "drop_counted": sum(1 for m in miss if not m["atc"]),
        "fix_note": "中文名缺失是源事实（WHO INN 中文表只覆盖一部分；配方辅料/疫苗株/植物提取物无中文名）："
        "有 ATC 的常用药可按 atc→中文名映射回填（迁移）；其余丢弃计数，不猜。"
        "name_lang 按文本字符集重算（规则，可自动）。",
        "auto_fixable": "部分",
    }


# ── 规则 4：状态自相矛盾 ───────────────────────────────────────────────────


def rule4_status(data: dict) -> dict:
    products = data["product"]

    term_null = [
        {
            "product_id": pid,
            "status": p["status"],
            "country": p["country"] or p["region"],
            "source_id": p["source_id"],
            "dosage_form": p["dosage_form"],
        }
        for pid, p in products.items()
        if p["status"] in ("withdrawn", "discontinued") and not (p["status_date"] or "").strip()
    ]
    term_src = Counter((r["source_id"], r["country"]) for r in term_null)

    active_dated = [
        {
            "product_id": pid,
            "status_date": p["status_date"],
            "country": p["country"] or p["region"],
            "source_id": p["source_id"],
        }
        for pid, p in products.items()
        if p["status"] == "active" and (p["status_date"] or "").strip()
    ]
    active_src = Counter(r["source_id"] for r in active_dated)
    active_dates = Counter(r["status_date"] for r in active_dated)

    by_appr: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    by_appr_cross: dict[str, set[str]] = defaultdict(set)
    for p in products.values():
        a = p["approval_id"]
        if not a:
            continue
        by_appr[(p["source_id"], p["country"] or p["region"] or "", a)].add(p["status"])
        by_appr_cross[a].add(p["country"] or p["region"] or "")
    appr_conflict = {k: v for k, v in by_appr.items() if len(v) > 1}
    appr_cross = {
        a: sorted(cs) for a, cs in by_appr_cross.items() if len([c for c in cs if c]) > 1
    }

    pair_subs: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: {"active": set(), "withdrawn": set()}
    )
    for pid, sids in data["prod_subs"].items():
        p = products.get(pid)
        if not p or not p["country"] or p["status"] not in ("active", "withdrawn"):
            continue
        for sid in sids:
            pair_subs[(sid, p["country"])][p["status"]].add(pid)

    coexist = []
    for (sid, country), d in pair_subs.items():
        if d["active"] and d["withdrawn"]:
            coexist.append(
                {
                    "substance_id": sid,
                    "inn_en": data["substance"].get(sid, {}).get("inn_en", ""),
                    "country": country,
                    "n_active": len(d["active"]),
                    "n_withdrawn": len(d["withdrawn"]),
                    "sample_active": sorted(d["active"])[:2],
                    "sample_withdrawn": sorted(d["withdrawn"])[:2],
                }
            )
    coexist.sort(key=lambda r: -(r["n_active"] + r["n_withdrawn"]))

    return {
        "id": "R4",
        "title": "状态与状态日期 / 批文号 / 同成分跨国状态自相矛盾",
        "count": len(term_null) + len(active_dated) + len(appr_conflict),
        "parts": {
            "withdrawn/discontinued 但 status_date 为空": {
                "count": len(term_null),
                "by_source_country": [
                    {"source_id": s, "country": c, "n": n}
                    for (s, c), n in term_src.most_common()
                ],
                "samples": term_null[:5],
            },
            "active 但 status_date 非空": {
                "count": len(active_dated),
                "by_source": dict(active_src.most_common()),
                "distinct_dates": dict(active_dates.most_common(5)),
                "samples": active_dated[:5],
            },
            "同一 approval_id 状态冲突（同源同国）": {
                "count": len(appr_conflict),
                "samples": [
                    {"source_country_approval": list(k), "statuses": sorted(v)}
                    for k, v in list(appr_conflict.items())[:5]
                ],
            },
            "同一 approval_id 跨国同号（命名空间，非状态冲突）": {
                "count": len(appr_cross),
                "samples": list(appr_cross.items())[:5],
            },
            "同成分同国家 active+withdrawn 并存": {
                "count": len(coexist),
                "samples": coexist[:5],
            },
        },
        "fix": FIX_RULE,
        "actionable": {
            "active 行 status_date 置空（可一次迁移）": len(active_dated),
            "discontinued/withdrawn 无日期（源缺失，丢弃计数）": len(term_null),
            "同成分同国并存（不同批文，正常；仅计数）": len(coexist),
        },
        "drop_counted": len(term_null),
        "fix_note": "active 却写 status_date 是 ETL 把抓取日写进了 status_date（规则修：active 一律置空，"
        "迁移可一次性清 1,703 行）；CIMA discontinued 无日期是源本身缺失（丢弃计数，不猜日期）；"
        "approval_id 跨国同号说明它不是全局唯一键（显示层/规则：不得单键 join）；"
        "同国并存多为不同批文，不做自动处置，仅计数。",
        "auto_fixable": "部分是（active+status_date 可自动置空；discontinued 无日期不能自动）",
    }


# ── 规则 5：来源与市场错配 ─────────────────────────────────────────────────


def rule5_source_market(data: dict) -> dict:
    products = data["product"]
    registered = load_market_sources()

    cross: Counter = Counter()
    for p in products.values():
        cross[(p["source_id"], p["country"] or f"region:{p['region']}")] += 1
    by_source: dict[str, Counter] = defaultdict(Counter)
    for (src, market), n in cross.items():
        by_source[src][market] += n

    offdiag: list[dict] = []
    offdiag_n = 0
    for src, counter in sorted(by_source.items()):
        main_market = max(counter, key=counter.get)
        expected = registered.get(src)
        # 人工种子表天然跨市场：不按「单源单市场」判
        if src == "manual_seed":
            continue
        for market, n in counter.most_common():
            if market == (expected or main_market):
                continue
            offdiag_n += n
            offdiag.append(
                {
                    "source_id": src,
                    "market": market,
                    "n": n,
                    "expected_market": expected or f"{main_market}(modal)",
                }
            )

    manual_seed = {
        m: n for (s, m), n in cross.items() if s == "manual_seed"
    }

    return {
        "id": "R5",
        "title": "source_id × country 非对角（来源与市场错配）",
        "count": offdiag_n,
        "parts": {
            "matrix": [
                {
                    "source_id": src,
                    "registered_market": registered.get(src),
                    "total": sum(counter.values()),
                    "markets": dict(counter.most_common()),
                }
                for src, counter in sorted(by_source.items())
            ],
            "off_diagonal": offdiag,
            "manual_seed_by_market": manual_seed,
        },
        "fix": FIX_RULE,
        "fix_note": "markets.json 已登记每个市场的 source_id（含 extra_source_ids）：非对角项可作为"
        " ci_checks 断言（规则，可自动）；真错配是入库国家参数写错，重跑该源即可，判不了的丢弃计数。"
        "manual_seed 是人工种子表，天然跨市场，不计入。",
        "auto_fixable": "是（断言/校验；错配需重跑入库）",
    }


# ── 规则 6：同名不同药是否被命名差异放大 ───────────────────────────────────


def rule6_collision_false_severe(data: dict) -> dict:
    subs = data["substance"]
    keys = data["name_key"]
    alias = load_alias_groups()

    base = {sid: strip_salt(s["inn_en"]) for sid, s in subs.items()}
    salts = {sid: salt_tokens(s["inn_en"]) for sid, s in subs.items()}
    atc = {sid: s["atc"] for sid, s in subs.items()}
    zh = {sid: (s["inn_zh"] or "").strip() for sid, s in subs.items()}

    with connect_ro() as db:
        severe = [r[0] for r in db.execute("SELECT key_id FROM collision WHERE level='severe'")]
    severe_set = set(severe)

    key_subs: dict[str, set[str]] = defaultdict(set)
    for kid in severe_set:
        for pid, _ in data["key_products"].get(kid, ()):
            key_subs[kid] |= data["prod_subs"].get(pid) or set()

    def reason(a: str, b: str) -> str | None:
        """判定这一对是不是「本应同一成分」，返回证据类型；不是则 None。"""
        if not a or not b or a == b:
            return None
        if alias.get(a) and alias.get(a) == alias.get(b):
            return "alias_table"
        aa, ab = atc.get(a, ""), atc.get(b, "")
        sa, sb = salts.get(a) or frozenset(), salts.get(b) or frozenset()
        ba, bb = base.get(a, ""), base.get(b, "")
        if ba and ba == bb:
            # 同 base：两侧都写了不同盐（tartrate vs succinate）是合法拆分，不并
            if sa and sb and sa != sb:
                return None
            return "same_base_after_salt_strip"
        if zh.get(a) and zh.get(a) == zh.get(b):
            if not aa or not ab or aa[:4] == ab[:4]:
                return "same_inn_zh"
        if len(aa) >= 7 and aa == ab:
            return "same_atc_code"  # 只认 7 位全码；5 位是 ATC 4 级类别，不代表同一成分
        if len(aa) >= 4 and aa[:4] == ab[:4]:
            ca, cb = compact_name(ba), compact_name(bb)
            if ca and cb and abs(len(ca) - len(cb)) <= 2:
                if len(ca) == len(cb):
                    diff = [i for i, (x, y) in enumerate(zip(ca, cb)) if x != y]
                    # 只差最后一个字符的（vitamin A / vitamin D / vitamin D3）是不同成分，不并
                    if diff and not (len(diff) == 1 and diff[0] == len(ca) - 1):
                        if len(diff) <= 2:
                            return "spelling_near"
                if len(ca) > 6 and (ca.startswith(cb) or cb.startswith(ca)):
                    extra = ca[len(cb) :] if ca.startswith(cb) else cb[len(ca) :]
                    if not (extra and (extra.isdigit() or len(extra) <= 2)):
                        return "spelling_near"
        return None

    candidates: list[dict] = []
    compared = 0
    for kid, sids in key_subs.items():
        if len(sids) < 2 or len(sids) > 12:  # 复合维生素/保健品大杂烩不做两两比较
            continue
        lst = sorted(sids)
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                a, b = lst[i], lst[j]
                if not atc.get(a) and not atc.get(b):
                    continue
                compared += 1
                why = reason(a, b)
                if not why:
                    continue
                candidates.append(
                    {
                        "key_id": kid,
                        "norm": keys.get(kid, {}).get("norm", ""),
                        "a": a,
                        "a_inn": subs[a]["inn_en"],
                        "a_atc": atc[a],
                        "a_zh": zh[a],
                        "b": b,
                        "b_inn": subs[b]["inn_en"],
                        "b_atc": atc[b],
                        "b_zh": zh[b],
                        "reason": why,
                        "n_products": len({pid for pid, _ in data["key_products"].get(kid, ())}),
                    }
                )

    uniq: dict[tuple[str, str], dict] = {}
    for c in candidates:
        key = tuple(sorted((c["a"], c["b"])))
        prev = uniq.get(key)
        if prev is None or c["n_products"] > prev["n_products"]:
            uniq[key] = c
    pairs = sorted(uniq.values(), key=lambda r: -r["n_products"])
    by_reason = Counter(p["reason"] for p in pairs)
    affected_products = sum(p["n_products"] for p in pairs)
    samples_by_reason: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        if len(samples_by_reason[p["reason"]]) < 5:
            samples_by_reason[p["reason"]].append(p)

    return {
        "id": "R6",
        "title": "collision severe 里本应同一成分、因命名差异被拆开的候选",
        "count": len(pairs),
        "parts": {
            "severe_key_total": len(severe),
            "compared_pairs": compared,
            "by_reason": dict(by_reason.most_common()),
            "affected_name_keys_products": affected_products,
            "samples_by_reason": dict(samples_by_reason),
            "samples": pairs[:5],
        },
        "fix": FIX_MIGRATE,
        "actionable": {
            "并入同一 substance（同 base 去盐 / 同 ATC 全码）": by_reason.get(
                "same_base_after_salt_strip", 0
            )
            + by_reason.get("same_atc_code", 0),
            "异名表已覆盖但 collision 未使用（改视图，规则）": by_reason.get("alias_table", 0),
            "拼写差异（补 data/substance_aliases.csv）": by_reason.get("spelling_near", 0),
            "受影响名称行（这些 key 目前被判 severe）": affected_products,
        },
        "fix_note": "同 base（只差盐型写法）、同 ATC 全码 → 并入同一 substance（迁移），"
        "执行前用 db/phaseb_merge.py --dry-run 校验产品/组件/variant 计数；"
        "异名表已收录的（dextrose/glucose 等）说明 collision 视图没读别名表，改视图即可（规则）；"
        "只是拼写相近的进 data/substance_aliases.csv（异名，不合并）；"
        "两侧盐型不同（tartrate vs succinate）、只差末位字母（vitamin A/D）不算重复，已排除；"
        "证据不足的丢弃计数。",
        "auto_fixable": "清单可自动生成，执行需 DB 窗口",
    }


# ── 规则 7：script 标注 ────────────────────────────────────────────────────


def rule7_script(data: dict) -> dict:
    keys = data["name_key"]
    bad = []
    for kid, k in keys.items():
        text = k["norm"] or (data["key_raw"].get(kid) or [""])[0]
        exp = expected_script(text)
        if exp != k["script"]:
            bad.append(
                {
                    "key_id": kid,
                    "norm": text[:40],
                    "script": k["script"],
                    "expected": exp,
                    "raw": (data["key_raw"].get(kid) or [""])[0][:40],
                }
            )
    by_pair = Counter((b["script"], b["expected"]) for b in bad)
    return {
        "id": "R7",
        "title": "name_key.script 与实际字符集不符",
        "count": len(bad),
        "parts": {
            "by_pair": [
                {"script": s, "expected": e, "n": n} for (s, e), n in by_pair.most_common()
            ],
            "samples": bad[:5],
        },
        "fix": FIX_RULE,
        "fix_note": "script 由文本字符集推导（规则，可自动重算）；不需要人工标注。",
        "auto_fixable": "是",
    }


# ── 规则 8：重复名称 ──────────────────────────────────────────────────────


def rule8_duplicate_names(data: dict) -> dict:
    keys = data["name_key"]

    norm_multi = Counter(k["norm"] for k in keys.values() if k["norm"])
    norm_dup = {n: c for n, c in norm_multi.items() if c > 1}

    compact_multi = Counter(k["compact"] for k in keys.values() if k["compact"])
    compact_dup = {c: n for c, n in compact_multi.items() if n > 1}

    raw_multi = {r: ks for r, ks in data["raw_keys"].items() if len(ks) > 1}
    raw_samples = [
        {
            "raw": r[:50],
            "n_keys": len(ks),
            "norms": [keys[k]["norm"][:30] for k in list(ks)[:3]],
        }
        for r, ks in sorted(raw_multi.items(), key=lambda kv: -len(kv[1]))[:5]
    ]
    compact_samples = [
        {
            "compact": c,
            "n_keys": n,
            "norms": [k["norm"] for k in keys.values() if k["compact"] == c][:4],
        }
        for c, n in sorted(compact_dup.items(), key=lambda kv: -kv[1])[:5]
    ]

    # 影响面：重复 compact / raw 下的 key 一共挂了多少产品（检索会拆成多条）
    compact_kids: dict[str, list[str]] = defaultdict(list)
    for kid, k in keys.items():
        if k["compact"]:
            compact_kids[k["compact"]].append(kid)
    compact_affected = sum(
        len(data["key_products"].get(kid, ()))
        for c in compact_dup
        for kid in compact_kids.get(c, ())
    )
    raw_affected = sum(
        len(data["key_products"].get(kid, ())) for ks in raw_multi.values() for kid in ks
    )

    return {
        "id": "R8",
        "title": "重复名称（norm / compact / raw 对应多个 key）",
        "count": len(norm_dup) + len(compact_dup) + len(raw_multi),
        "parts": {
            "同一 norm 多 key（schema UNIQUE 应恒为 0）": {"count": len(norm_dup)},
            "同一 compact 多 key": {
                "count": len(compact_dup),
                "affected_name_rows": compact_affected,
                "samples": compact_samples,
            },
            "同一 raw 多 key": {
                "count": len(raw_multi),
                "affected_name_rows": raw_affected,
                "samples": raw_samples,
            },
        },
        "fix": FIX_RULE,
        "actionable": {
            "compact 相同可合并的 key 组": len(compact_dup),
            "受影响的名称行": compact_affected,
            "raw 相同但分属不同 key（按 compact 归一）": len(raw_multi),
        },
        "fix_note": "norm 唯一是 schema 约束（现在 0）；compact 重复会稀释检索召回，"
        "归一化时按 compact 归并可迁移；raw 多 key 多为同名的不同写法，按 compact 归一（规则）。",
        "auto_fixable": "是（compact 合并需迁移）",
    }


# ── 主流程 ────────────────────────────────────────────────────────────────


def print_human(results: list[dict], counts: dict) -> None:
    print("== 名称 / 成分 / 状态 / 来源 一致性审计（只读）==")
    print(f"库：{DB_PATH}")
    print(f"时间：{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}")
    print("表计数：" + "  ".join(f"{k}={v:,}" for k, v in counts.items()))
    print()

    print("规则总览：")
    for r in results:
        print(
            f"  {r['id']}  {r['title']}\n"
            f"      条数={r['count']:,}  修法={r['fix']}  可自动修={r['auto_fixable']}"
        )
    print()

    for r in results:
        print(f"── {r['id']} {r['title']} ──")
        print(f"  合计 {r['count']:,}；修法={r['fix']}；可自动修={r['auto_fixable']}")
        if r.get("actionable"):
            print("  可动/不可动拆分：" + json.dumps(r["actionable"], ensure_ascii=False))
        if r.get("drop_counted"):
            print(f"  丢弃并计数：{r['drop_counted']:,}")
        print(f"  说明：{r['fix_note']}")
        if r["id"] == "R2":
            print(
                f"  矛盾 {r['count']} 个产品；另「名称词在 dosage_form 里也有、只是 form_base 更粗」"
                f" {r.get('coarse_count', 0)} 个产品（不计入矛盾）"
            )
            print("  词 × form_base 矩阵（__contradiction__ = 名称与字段矛盾）：")
            for w, row in r["matrix"].items():
                cells = ", ".join(
                    f"{k}={v}"
                    for k, v in row.items()
                    if k not in ("__mismatch__", "__contradiction__", "__products__", "__keys__")
                )
                print(
                    f"    {w}: 产品 {row['__products__']}，不符 {row['__mismatch__']}，"
                    f"矛盾 {row['__contradiction__']}，key {row['__keys__']}；{cells}"
                )
            print("  矛盾样例（每条给 1 个）：")
            for w, rows in r["samples"].items():
                for row in rows[:1]:
                    print(f"    {w}: {json.dumps(row, ensure_ascii=False)}")
            print()
            continue

        for key, part in r["parts"].items():
            if isinstance(part, dict) and "count" in part:
                print(f"  {key}: {part['count']:,}")
                if key.startswith("name_type=inn") and part.get("by_bucket"):
                    for b, n in part["by_bucket"].items():
                        print(f"      分桶 {b}: {n:,}")
                for sub in ("by_source_country", "by_source", "distinct_dates",
                            "by_country", "by_reason", "by_pair", "top_atc_class",
                            "off_diagonal", "manual_seed_by_market",
                            "affected_name_rows", "spelling_only", "match_kinds"):
                    if sub in part and part[sub]:
                        print(f"    {sub}: {json.dumps(part[sub], ensure_ascii=False)[:400]}")
                for s in part.get("samples", [])[:3]:
                    print(f"    样例: {json.dumps(s, ensure_ascii=False)[:300]}")
            elif isinstance(part, int):
                print(f"  {key}: {part:,}")
            elif isinstance(part, list):
                print(f"  {key}: {len(part)} 行")
                for s in part[:3]:
                    print(f"    样例: {json.dumps(s, ensure_ascii=False)[:400]}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="名称/成分/状态/来源一致性审计（只读）")
    parser.add_argument("--json", type=Path, help="把结构化结果写到 JSON")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    with connect_ro() as db:
        data = load(db)
        counts = {
            t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in (
                "substance",
                "variant",
                "product",
                "product_component",
                "product_name",
                "name_key",
                "name_variant",
            )
        }

    results = [
        rule1_brand_as_ingredient(data),
        rule2_form_words(data),
        rule3_missing_zh(data),
        rule4_status(data),
        rule5_source_market(data),
        rule6_collision_false_severe(data),
        rule7_script(data),
        rule8_duplicate_names(data),
    ]

    print_human(results, counts)

    if args.json:
        payload = {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "db": str(DB_PATH),
            "counts": counts,
            "rules": results,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 已写入 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
