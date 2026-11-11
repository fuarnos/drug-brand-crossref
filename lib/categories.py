# -*- coding: utf-8 -*-
"""lib 大类（category）检索：与客户端 app.js 的 `catHit()` / 16 大类配置对齐。

来源与口径
----------
- 16 大类定义（id/url/prefixes/四语 labels，`CATEGORY_SNAPSHOT`）是构建产物
  `site/dist/data/categories.json` 的**镜像快照**，现与站点 v0.11.2 产物一致
  （= `site/build.py` 的 `CONSUMER_CATEGORIES`）。同步方向只有一个：
  **build.py（线上真相）→ 本快照**，不许反过来拿 lib 的旧口径去改构建。
  `tests/test_lib_atc_category.py::test_snapshot_sync_with_dist` 逐字段比对；
  v0.11.3 起该用例的快照同步部分也进了 `deploy/ci_checks.py --fast`（0.01 s），
  漂移当天就会变红（此前只在全量模式跑，漂了 3 个版本没人发现）。
- **`aliases` 是派生的，不手抄**（v0.11.3）：`[官方英文 label, 大类 id, *该类口语别名]`，
  与 `site/build.py` 构建期同一口径。快照里原来逐字抄了 97 条，v0.10.3 把口语别名
  接进构建后没重建，16 类全部对不上——见
  `reports/2026-11-13-lib-atc-category-fix.md`。
- 客户端 `catHit()` 的匹配口径：NFKD 去重音 + 去空格 + 小写后做**整串相等**匹配
  （见 site/build.py 的 `_catNorm`），本模块严格复刻。
- **口语别名**（`COLLOQUIAL_ALIASES`，66 条）是**唯一来源**：lib 匹配、构建期
  `data/categories.json` 的各类 `aliases`、`data/idx/cats.json` 的 `words` 都从这一份表
  生成（v0.10.3 起；`site/build.py` 的接入片段见
  `reports/v0103-search-impl-20261110.md`）。客户端目前只认官方 label/alias，
  task-124 审计发现「退烧药」在客户端 0 结果，就是因为词表只活在 lib 里。
- **防遮蔽**：口语词与真实商品名撞车时，不许把商品名结果藏掉（AGENTS §1 先定位名字）。
  撞车分两档：
    1. **全等 name_key**（如 `antibiotic` = 美/加在售 OTC 抗菌软膏的商品名）→ 列进
       `NAME_KEY_SHADOW_EXCEPTIONS`，保持药名检索路径：不并进客户端 aliases、
       本模块也不认它为大类词。
    2. **名字包含命中**（感冒药 / 消炎药 / 他汀 等有 2–29 条）→ 允许大类接管，
       这是本批的产品意图（0 结果/几条噪音 → 整类候选集）。
  `assert_no_unlisted_shadow()` 在单测里对 `name_key` 现查，保证新的**全等**撞车
  必须先登记例外，不会悄悄上线。
- 只读；不改 DB、不改 build.py、不改碰撞语义。
"""
from __future__ import annotations

import re
import unicodedata

# 16 大类（顺序与客户端 CATS.categories 一致；匹配时按顺序取第一个命中）
# 快照自 site/dist/data/categories.json（站点 v0.10.1；v0.10.3 修正 9 处过期：
# 5 处四语 label + weight-loss / cold-medicine 的 prefixes）。
# **`aliases` 不写在这里**：它是 `COLLOQUIAL_ALIASES` 的派生结果，见文件下方
# 「aliases 派生」一节（v0.11.3 起）。手工镜像那份已经漂移了 3 个版本。
CATEGORY_SNAPSHOT: list[dict] = [
    {
        'id': 'antihypertensives', 'url': 'cat/antihypertensives.html',
        'prefixes': ['C02', 'C03', 'C07', 'C08', 'C09'],
        'labels': {'en': 'Blood-pressure medicines', 'es': 'Medicamentos para la presión arterial', 'zh': '降压药', 'zh-Hant': '降血壓藥'},
    },
    {
        'id': 'antibiotics', 'url': 'cat/antibiotics.html',
        'prefixes': ['J01'],
        'labels': {'en': 'Antibiotics', 'es': 'Antibióticos', 'zh': '抗生素', 'zh-Hant': '抗生素'},
    },
    {
        'id': 'diabetes', 'url': 'cat/diabetes.html',
        'prefixes': ['A10'],
        'labels': {'en': 'Diabetes medicines', 'es': 'Medicamentos para la diabetes', 'zh': '降糖药', 'zh-Hant': '降血糖藥'},
    },
    {
        'id': 'weight-loss', 'url': 'cat/weight-loss.html',
        'prefixes': ['A08', 'A10BJ', 'A10BX16'],
        'labels': {'en': 'Weight-loss medicines', 'es': 'Medicamentos para perder peso', 'zh': '减肥药', 'zh-Hant': '減重藥'},
    },
    {
        'id': 'cold-medicine', 'url': 'cat/cold-medicine.html',
        'prefixes': ['R05', 'N02BE'],
        'labels': {'en': 'Cold & cough medicines', 'es': 'Medicamentos para resfriado y tos', 'zh': '感冒咳嗽药', 'zh-Hant': '感冒咳嗽藥'},
    },
    {
        'id': 'analgesics', 'url': 'cat/analgesics.html',
        'prefixes': ['N02', 'M01A'],
        'labels': {'en': 'Pain & fever relief', 'es': 'Analgésicos y antitérmicos', 'zh': '退烧止痛', 'zh-Hant': '退燒止痛'},
    },
    {
        'id': 'allergy', 'url': 'cat/allergy.html',
        'prefixes': ['R06'],
        'labels': {'en': 'Allergy medicines', 'es': 'Medicamentos para la alergia', 'zh': '抗过敏药', 'zh-Hant': '抗過敏藥'},
    },
    {
        'id': 'acid-related', 'url': 'cat/acid-related.html',
        'prefixes': ['A02'],
        'labels': {'en': 'Stomach / acid medicines', 'es': 'Medicamentos gástricos / de acidez', 'zh': '胃药', 'zh-Hant': '胃藥'},
    },
    {
        'id': 'anticoagulants', 'url': 'cat/anticoagulants.html',
        'prefixes': ['B01'],
        'labels': {'en': 'Blood thinners / antithrombotics', 'es': 'Anticoagulantes / antitrombóticos', 'zh': '抗凝药', 'zh-Hant': '抗凝血藥'},
    },
    {
        'id': 'statins', 'url': 'cat/statins.html',
        'prefixes': ['C10AA'],
        'labels': {'en': 'Statins', 'es': 'Estatinas', 'zh': '他汀类', 'zh-Hant': '他汀類'},
    },
    {
        'id': 'beta-blockers', 'url': 'cat/beta-blockers.html',
        'prefixes': ['C07'],
        'labels': {'en': 'Beta blockers', 'es': 'Betabloqueantes', 'zh': 'β受体阻滞剂', 'zh-Hant': 'β受體阻斷劑'},
    },
    {
        'id': 'antidepressants', 'url': 'cat/antidepressants.html',
        'prefixes': ['N06A'],
        'labels': {'en': 'Antidepressants', 'es': 'Antidepresivos', 'zh': '抗抑郁药', 'zh-Hant': '抗憂鬱藥'},
    },
    {
        'id': 'asthma-copd', 'url': 'cat/asthma-copd.html',
        'prefixes': ['R03'],
        'labels': {'en': 'Asthma / COPD inhalers', 'es': 'Inhaladores para asma / EPOC', 'zh': '哮喘·慢阻肺吸入剂', 'zh-Hant': '哮喘·慢阻肺吸入劑'},
    },
    {
        'id': 'corticosteroids', 'url': 'cat/corticosteroids.html',
        'prefixes': ['H02'],
        'labels': {'en': 'Steroid hormones', 'es': 'Hormonas esteroideas', 'zh': '激素类', 'zh-Hant': '荷爾蒙類'},
    },
    {
        'id': 'antivirals', 'url': 'cat/antivirals.html',
        'prefixes': ['J05'],
        'labels': {'en': 'Antivirals', 'es': 'Antivirales', 'zh': '抗病毒药', 'zh-Hant': '抗病毒藥'},
    },
    {
        'id': 'dermatologicals', 'url': 'cat/dermatologicals.html',
        'prefixes': ['D'],
        'labels': {'en': 'Skin medicines', 'es': 'Medicamentos dermatológicos', 'zh': '皮肤外用药', 'zh-Hant': '皮膚外用藥'},
    },
]

# 口语别名 → 大类 id（**唯一来源**：lib 匹配 + 构建期 categories.json / cats.json 同源生成）
COLLOQUIAL_ALIASES: dict[str, str] = {
    "退烧药": "analgesics", "退燒藥": "analgesics", "退热药": "analgesics",
    "退熱藥": "analgesics", "发烧药": "analgesics", "fever medicine": "analgesics",
    "fever reducer": "analgesics", "painkiller": "analgesics",
    "pain killer": "analgesics", "止痛药": "analgesics", "止痛藥": "analgesics",
    "消炎药": "antibiotics", "消炎藥": "antibiotics", "antibiotic": "antibiotics",
    "胃药": "acid-related", "胃藥": "acid-related", "stomach medicine": "acid-related",
    "降血压药": "antihypertensives", "降血壓藥": "antihypertensives",
    "降压药": "antihypertensives", "降壓藥": "antihypertensives",
    "blood pressure medicine": "antihypertensives",
    "blood pressure medicines": "antihypertensives",
    "降糖药": "diabetes", "降糖藥": "diabetes", "糖尿病药": "diabetes",
    "糖尿病藥": "diabetes", "diabetes medicine": "diabetes",
    "减肥药": "weight-loss", "減肥藥": "weight-loss",
    "weight loss medicine": "weight-loss",
    "感冒药": "cold-medicine", "感冒藥": "cold-medicine",
    "cold medicine": "cold-medicine",
    "抗过敏药": "allergy", "抗過敏藥": "allergy", "allergy medicine": "allergy",
    "抗凝药": "anticoagulants", "抗凝藥": "anticoagulants",
    "blood thinner": "anticoagulants", "blood thinners": "anticoagulants",
    "他汀": "statins", "statin": "statins", "降脂药": "statins", "降脂藥": "statins",
    "beta阻滞剂": "beta-blockers", "beta 阻滞剂": "beta-blockers",
    "beta blocker": "beta-blockers", "beta blockers": "beta-blockers",
    "抗抑郁药": "antidepressants", "抗抑鬱藥": "antidepressants",
    "antidepressant": "antidepressants",
    "哮喘药": "asthma-copd", "哮喘藥": "asthma-copd",
    "asthma medicine": "asthma-copd", "inhaler": "asthma-copd",
    "激素": "corticosteroids", "类固醇": "corticosteroids",
    "類固醇": "corticosteroids", "steroid": "corticosteroids",
    "抗病毒药": "antivirals", "抗病毒藥": "antivirals", "antiviral": "antivirals",
    "皮肤药": "dermatologicals", "皮膚藥": "dermatologicals",
    "skin medicine": "dermatologicals",
}

# 客户端 atcQuery 口径（site/build.py）：字母开头 + 两位数字 + 可选 0–2 位字母/0–2 位数字
_RE_ATC = re.compile(r"^[A-Z]\d{2}(?:[A-Z]{0,2}\d{0,2})?$")

# 与 `name_key.norm` **全等** 的口语词（防遮蔽白名单，v0.10.3）。
# 这些词本身就是真实上架的商品名：客户端 render() 里 catHit() 排在名字检索之前，
# 一旦并进 categories.json 的 aliases，就会把商品名结果整片换成大类候选集。
# 规则：全等撞车一律让给药名检索（AGENTS §1 先定位名字）；「名字包含」命中不算撞车，
# 允许大类接管（感冒药 / 消炎药 / 他汀 那 2–29 条噪音 → 整类候选集，是本批的产品意图）。
NAME_KEY_SHADOW_EXCEPTIONS: dict[str, str] = {
    "antibiotic": (
        "ANTIBIOTIC 是美/加在售 OTC 复方抗菌软膏的真实商品名（Neomycin / Bacitracin "
        "Zinc / Polymyxin B，name_key.norm='antibiotic'）；英文类名 Antibiotics（复数，"
        "官方 label）仍能进大类，这个词留给药名检索。"
    ),
}

_SHADOW_NORMS: frozenset[str] = frozenset()   # 见下方 cat_norm() 之后赋值（归一化口径同客户端）


def atc_query(raw: str) -> str:
    """与客户端 atcQuery 完全一致的 ATC 码识别；不是 ATC 返回空串。"""
    s = str(raw or "").strip().upper()
    return s if _RE_ATC.match(s) else ""


def cat_norm(s: str) -> str:
    """客户端 _catNorm：NFKD 去组合重音 + 去空白 + 小写。"""
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", "", t).lower()


# 白名单词的归一化形态（定义在 cat_norm 之后，保证与匹配口径同源）
_SHADOW_NORMS = frozenset(cat_norm(w) for w in NAME_KEY_SHADOW_EXCEPTIONS)


def is_shadowed(word: str) -> bool:
    """这个词是否属于「全等撞车、让给药名检索」的白名单。"""
    return cat_norm(word) in _SHADOW_NORMS


def colloquial_aliases_by_category() -> dict[str, list[str]]:
    """口语词按大类分组（已剔除 `NAME_KEY_SHADOW_EXCEPTIONS`）。

    构建期把它并进 `data/categories.json` 各类的 `aliases`、并写进
    `data/idx/cats.json` 的 `words`；老客户端也会立刻生效（`catHit()` 本来就遍历 aliases）。
    """
    out: dict[str, list[str]] = {}
    for word, cat_id in COLLOQUIAL_ALIASES.items():
        if is_shadowed(word):
            continue
        out.setdefault(cat_id, []).append(word)
    return out


# ── aliases 派生（v0.11.3）────────────────────────────────────────────────
# 构建期口径见 site/build.py:11544：
#     aliases = [官方英文 label, 大类 id, *该类口语别名（已剔除防遮蔽白名单）]
# 快照原来把这 97 条逐字抄在 CATEGORY_SNAPSHOT 里，v0.10.3 把口语别名接进构建后
# 一直没重建 —— 16 类全部与产物不一致，`tests.test_lib_atc_category` 红了 3 个版本
# （该用例那时只在 ci_checks 全量模式跑，--fast 里是 SKIP，日常看不见）。
# 改成派生后：词表/label 一改自动同步，「构建侧公式被改掉」仍由
# test_snapshot_sync_with_dist 逐字段比对产物来守。
_COLLOQUIAL_BY_CAT: dict[str, list[str]] = colloquial_aliases_by_category()
_COLLOQUIAL_WORDS: frozenset[str] = frozenset(COLLOQUIAL_ALIASES)

for _cat in CATEGORY_SNAPSHOT:
    _cat["aliases"] = [_cat["labels"]["en"], _cat["id"],
                       *_COLLOQUIAL_BY_CAT.get(_cat["id"], [])]
del _cat


def find_name_key_shadows(db) -> list[str]:
    """现查 DB：哪些口语词的 norm 与某个 `name_key.norm` 全等（含已登记白名单）。"""
    norms = {r[0] for r in db.execute("SELECT norm FROM name_key")}
    return [w for w in COLLOQUIAL_ALIASES if cat_norm(w) in norms]


def assert_no_unlisted_shadow(db) -> None:
    """构建期 / 单测断言：出现新的「口语词 = 真实 name_key」必须先登记白名单。

    白名单是人工判断（哪个词该让给药名），所以这里只拦「没登记就悄悄上线」。
    """
    bad = [w for w in find_name_key_shadows(db) if not is_shadowed(w)]
    if bad:
        raise ValueError(
            "口语词与真实商品名撞车，且没登记 NAME_KEY_SHADOW_EXCEPTIONS："
            + "、".join(bad)
            + "（要么从口碑词表移除，要么加进白名单并写明理由）")


def _by_id(cat_id: str) -> dict | None:
    for c in CATEGORY_SNAPSHOT:
        if c["id"] == cat_id:
            return c
    return None


def match_category(query: str) -> dict | None:
    """大类词匹配：先官方 label/alias（客户端口径），再口语别名。

    返回 {cat, matched, source}；source ∈ label / alias / colloquial。
    与客户端 catHit() 一样：长度 <2 不匹配；整串相等匹配，不做子串。
    `NAME_KEY_SHADOW_EXCEPTIONS` 里的词不在这里接走（它们是真商品名，走药名检索），
    保证 lib 与改造后的客户端口径一致。

    v0.11.3：`cat["aliases"]` 现在含构建期的口语别名（镜像产物），所以 alias 这一轮
    要跳过口语词 —— 否则「退烧药」会被判成 source=alias，`source` 三分类的语义就变了。
    口语词仍旧由下面的 colloquial 分支认领；与官方 zh label 同形的词（胃药 / 降糖药）
    仍先被 label 分支接走，与 v0.10.3 行为一致。
    """
    q = cat_norm(query)
    if len(q) < 2:
        return None
    for cat in CATEGORY_SNAPSHOT:
        for lang, label in (cat.get("labels") or {}).items():
            if label and cat_norm(label) == q:
                return {"cat": cat, "matched": label, "source": "label",
                        "lang": lang}
        for alias in cat.get("aliases") or []:
            if alias in _COLLOQUIAL_WORDS:
                continue
            if alias and cat_norm(alias) == q:
                return {"cat": cat, "matched": alias, "source": "alias",
                        "lang": ""}
    for raw, cat_id in COLLOQUIAL_ALIASES.items():
        if cat_norm(raw) == q and not is_shadowed(raw):
            cat = _by_id(cat_id)
            if cat:
                return {"cat": cat, "matched": raw, "source": "colloquial",
                        "lang": ""}
    return None


def category_by_id(cat_id: str) -> dict | None:
    return _by_id(cat_id)
