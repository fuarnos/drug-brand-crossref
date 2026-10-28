# -*- coding: utf-8 -*-
"""lib 大类（category）检索：与客户端 app.js 的 `catHit()` / 16 大类配置对齐。

来源
----
- 16 大类定义（id/url/prefixes/四语 labels/aliases）快照自构建产物
  `site/dist/data/categories.json`（站点 v0.7.1 起）。生成器：`tests/gen_categories.py`
  （即 `.tmp/lib-cat-search/gen_categories.py` 的落库版）；构建配置变化后重跑并跑单测同步检查。
- 客户端 `catHit()` 的匹配口径：NFKD 去重音 + 去空格 + 小写后做**整串相等**匹配
  （见 site/build.py 的 `_catNorm`），本模块严格复刻。
- **口语别名**（退烧药/消炎药/胃药…）是 lib 侧扩展：客户端目前只认官方 label/alias，
  task-124 审计发现「退烧药」在客户端 0 结果；这里补一层口语映射，返回 matching source。
- 只读；不改 build.py/DB，客户端行为不变。
"""
from __future__ import annotations

import re
import unicodedata

# 16 大类（顺序与客户端 CATS.categories 一致；匹配时按顺序取第一个命中）
CATEGORY_SNAPSHOT: list[dict] = [
    {
        'id': 'antihypertensives', 'url': 'cat/antihypertensives.html',
        'prefixes': ['C02', 'C03', 'C07', 'C08', 'C09'],
        'labels': {'en': 'Blood-pressure medicines', 'es': 'Medicamentos para la presión arterial', 'zh': '降压药', 'zh-Hant': '降壓藥'},
        'aliases': ['Blood-pressure medicines', 'antihypertensives'],
    },
    {
        'id': 'antibiotics', 'url': 'cat/antibiotics.html',
        'prefixes': ['J01'],
        'labels': {'en': 'Antibiotics', 'es': 'Antibióticos', 'zh': '抗生素', 'zh-Hant': '抗生素'},
        'aliases': ['Antibiotics', 'antibiotics'],
    },
    {
        'id': 'diabetes', 'url': 'cat/diabetes.html',
        'prefixes': ['A10'],
        'labels': {'en': 'Diabetes medicines', 'es': 'Medicamentos para la diabetes', 'zh': '降糖药', 'zh-Hant': '降糖藥'},
        'aliases': ['Diabetes medicines', 'diabetes'],
    },
    {
        'id': 'weight-loss', 'url': 'cat/weight-loss.html',
        'prefixes': ['A08'],
        'labels': {'en': 'Weight-loss medicines', 'es': 'Medicamentos para perder peso', 'zh': '减肥药', 'zh-Hant': '減肥藥'},
        'aliases': ['Weight-loss medicines', 'weight-loss'],
    },
    {
        'id': 'cold-medicine', 'url': 'cat/cold-medicine.html',
        'prefixes': ['R05', 'N02BE', 'R06'],
        'labels': {'en': 'Cold & cough medicines', 'es': 'Medicamentos para resfriado y tos', 'zh': '感冒药', 'zh-Hant': '感冒藥'},
        'aliases': ['Cold & cough medicines', 'cold-medicine'],
    },
    {
        'id': 'analgesics', 'url': 'cat/analgesics.html',
        'prefixes': ['N02', 'M01A'],
        'labels': {'en': 'Pain & fever relief', 'es': 'Analgésicos y antitérmicos', 'zh': '退烧止痛', 'zh-Hant': '退燒止痛'},
        'aliases': ['Pain & fever relief', 'analgesics'],
    },
    {
        'id': 'allergy', 'url': 'cat/allergy.html',
        'prefixes': ['R06'],
        'labels': {'en': 'Allergy medicines', 'es': 'Medicamentos para la alergia', 'zh': '抗过敏药', 'zh-Hant': '抗過敏藥'},
        'aliases': ['Allergy medicines', 'allergy'],
    },
    {
        'id': 'acid-related', 'url': 'cat/acid-related.html',
        'prefixes': ['A02'],
        'labels': {'en': 'Stomach / acid medicines', 'es': 'Medicamentos gástricos / de acidez', 'zh': '胃药', 'zh-Hant': '胃藥'},
        'aliases': ['Stomach / acid medicines', 'acid-related'],
    },
    {
        'id': 'anticoagulants', 'url': 'cat/anticoagulants.html',
        'prefixes': ['B01'],
        'labels': {'en': 'Blood thinners / antithrombotics', 'es': 'Anticoagulantes / antitrombóticos', 'zh': '抗凝/抗血栓', 'zh-Hant': '抗凝/抗血栓'},
        'aliases': ['Blood thinners / antithrombotics', 'anticoagulants'],
    },
    {
        'id': 'statins', 'url': 'cat/statins.html',
        'prefixes': ['C10AA'],
        'labels': {'en': 'Statins', 'es': 'Estatinas', 'zh': '他汀类', 'zh-Hant': '他汀類'},
        'aliases': ['Statins', 'statins'],
    },
    {
        'id': 'beta-blockers', 'url': 'cat/beta-blockers.html',
        'prefixes': ['C07'],
        'labels': {'en': 'Beta blockers', 'es': 'Betabloqueantes', 'zh': 'β受体阻滞剂', 'zh-Hant': 'β受體阻滯劑'},
        'aliases': ['Beta blockers', 'beta-blockers'],
    },
    {
        'id': 'antidepressants', 'url': 'cat/antidepressants.html',
        'prefixes': ['N06A'],
        'labels': {'en': 'Antidepressants', 'es': 'Antidepresivos', 'zh': '抗抑郁药', 'zh-Hant': '抗抑鬱藥'},
        'aliases': ['Antidepressants', 'antidepressants'],
    },
    {
        'id': 'asthma-copd', 'url': 'cat/asthma-copd.html',
        'prefixes': ['R03'],
        'labels': {'en': 'Asthma / COPD inhalers', 'es': 'Inhaladores para asma / EPOC', 'zh': '哮喘/慢阻肺用药', 'zh-Hant': '哮喘/慢阻肺用藥'},
        'aliases': ['Asthma / COPD inhalers', 'asthma-copd'],
    },
    {
        'id': 'corticosteroids', 'url': 'cat/corticosteroids.html',
        'prefixes': ['H02'],
        'labels': {'en': 'Steroid hormones', 'es': 'Hormonas esteroideas', 'zh': '激素/糖皮质激素', 'zh-Hant': '激素/糖皮質激素'},
        'aliases': ['Steroid hormones', 'corticosteroids'],
    },
    {
        'id': 'antivirals', 'url': 'cat/antivirals.html',
        'prefixes': ['J05'],
        'labels': {'en': 'Antivirals', 'es': 'Antivirales', 'zh': '抗病毒药', 'zh-Hant': '抗病毒藥'},
        'aliases': ['Antivirals', 'antivirals'],
    },
    {
        'id': 'dermatologicals', 'url': 'cat/dermatologicals.html',
        'prefixes': ['D'],
        'labels': {'en': 'Skin medicines', 'es': 'Medicamentos dermatológicos', 'zh': '皮肤外用药', 'zh-Hant': '皮膚外用藥'},
        'aliases': ['Skin medicines', 'dermatologicals'],
    },
]

# 口语别名 → 大类 id（lib 扩展；不改变客户端行为）
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


def atc_query(raw: str) -> str:
    """与客户端 atcQuery 完全一致的 ATC 码识别；不是 ATC 返回空串。"""
    s = str(raw or "").strip().upper()
    return s if _RE_ATC.match(s) else ""


def cat_norm(s: str) -> str:
    """客户端 _catNorm：NFKD 去组合重音 + 去空白 + 小写。"""
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", "", t).lower()


def _by_id(cat_id: str) -> dict | None:
    for c in CATEGORY_SNAPSHOT:
        if c["id"] == cat_id:
            return c
    return None


def match_category(query: str) -> dict | None:
    """大类词匹配：先官方 label/alias（客户端口径），再口语别名（lib 扩展）。

    返回 {cat, matched, source}；source ∈ label / alias / colloquial。
    与客户端 catHit() 一样：长度 <2 不匹配；整串相等匹配，不做子串。
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
            if alias and cat_norm(alias) == q:
                return {"cat": cat, "matched": alias, "source": "alias",
                        "lang": ""}
    for raw, cat_id in COLLOQUIAL_ALIASES.items():
        if cat_norm(raw) == q:
            cat = _by_id(cat_id)
            if cat:
                return {"cat": cat, "matched": raw, "source": "colloquial",
                        "lang": ""}
    return None


def category_by_id(cat_id: str) -> dict | None:
    return _by_id(cat_id)
