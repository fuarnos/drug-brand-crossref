# -*- coding: utf-8 -*-
"""生成「原名 + 译名 + 翻译来源/版本」数据表（task-100，通用模型）。

输出
----
  data/translations.csv            通用长表（任何市场/语言只加行）
  data/ingredient_names_i18n.csv   成分宽表（en + zh/zh-Hant/es/pt + 来源/置信度）
  data/label_translations.csv      标签宽表（剂型/状态/释放/单位 × en/es/zh/zh-Hant/pt）

原则
----
- **品牌名不翻译**：product_name 原值以 source=non_translation 入表（按国家市场语言）。
- **缺 zh 不盲译**：没有 CN 产品通用名/overrides 证据的 zh 留空；AI 候选（zh-Hant 简繁转换）
  一律 machine_translated=1、confidence=low、display_default=false，默认不上页面。
- 来源分级：official(WHO/EMA 等官方标准) / regulator(药监/EU 机构事实) / pharmacopoeia(药典/命名原则) /
  ai(机器候选) / non_translation(品牌原名)。
- 版本：`version = <表格快照日期>.N`（重跑且源数据变化时 N+1）；`updated_at` 为 ISO8601 时间。
- 只读 DB（mode=ro）；不写 DB、不改 site/build.py、不联网。

用法
----
    python etl/build_translation_tables.py
    python etl/build_translation_tables.py --brand-limit 5000   # 每个市场品牌原名行数上限（0=全部）
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
WHO_INN = ROOT / "data" / "who_inn_names.csv"
INN_ZH_BACKFILL = ROOT / "data" / "inn_zh_backfill.csv"
ES_OVERRIDES = ROOT / "data" / "es_inn_overrides.csv"
GLOSSARY = ROOT / "data" / "terminology_glossary.csv"
T2S = ROOT / "data" / "zh_hant_t2s.json"
MARKETS = ROOT / "data" / "markets.json"
OUT_LONG = ROOT / "data" / "translations.csv"
OUT_ING = ROOT / "data" / "ingredient_names_i18n.csv"
OUT_LABEL = ROOT / "data" / "label_translations.csv"
EVIDENCE = ROOT / ".tmp" / "translation-provenance"

SNAPSHOT = datetime.now(timezone.utc).astimezone()
VERSION = f"{SNAPSHOT:%Y-%m-%d}.1"
UPDATED_AT = SNAPSHOT.isoformat(timespec="seconds")

URL_NHSA = "https://code.nhsa.gov.cn/yp/toPublicGoodsData.html"
URL_WHO_INN = "https://www.who.int/teams/health-product-and-policy-standards/inn/inn-lists"
URL_CHP = ("https://www.chp.org.cn/ydw/upload/sites/chp/newscenter/news/attachments/000033.html")
URL_CIMA = "https://cima.aemps.es/cima/publico/home.html"
URL_INFOMED = "https://extranet.infarmed.pt/INFOMED-fo/"
URL_CITS = ("https://www.infarmed.pt/web/infarmed/profissionais-de-saude/"
            "prescricao-e-dispensa/cedencia-de-base-de-dados-de-medicamentos")

# 国家 → 该市场商品名原名语言（品牌不译，仅标记原名语言）
COUNTRY_LANG = {
    "US": "en", "GB": "en", "AU": "en", "CA": "en",
    "ES": "es", "MX": "es", "CN": "zh", "TW": "zh-Hant",
    "PT": "pt",
}

LONG_COLUMNS = ["entity_type", "entity_id", "field", "lang", "value", "source",
                "source_url", "machine_translated", "confidence", "version", "updated_at"]

ING_COLUMNS = [
    "substance_id", "inn_en",
    "name_zh", "source_zh", "source_url_zh", "confidence_zh",
    "name_zh_hant", "source_zh_hant", "source_url_zh_hant", "confidence_zh_hant",
    "name_es", "source_es", "source_url_es", "confidence_es",
    "name_pt", "source_pt", "source_url_pt", "confidence_pt",
    "machine_translated", "display_default_zh", "display_default_zh_hant",
    "display_default_es", "display_default_pt",
    "version", "updated_at", "notes",
]

LABEL_COLUMNS = [
    "category", "code", "field",
    "en", "es", "zh", "zh_hant", "pt",
    "source_en", "source_es", "source_zh", "source_zh_hant", "source_pt",
    "source_url", "confidence", "machine_translated", "display_default",
    "version", "updated_at", "notes",
]

long_rows: list[dict] = []
ing_rows: list[dict] = []
label_rows: list[dict] = []
stats: dict = {}


def norm(s: str) -> str:
    """与站点检索归一一致：NFKD 去重音、小写、非字母数字换空格。"""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


def iso(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def add_long(entity_type: str, entity_id: str, field: str, lang: str, value: str,
             source: str, source_url: str = "", machine: int = 0,
             confidence: str = "reference") -> None:
    if not value:
        return
    long_rows.append({
        "entity_type": entity_type, "entity_id": entity_id, "field": field,
        "lang": lang, "value": value.strip(), "source": source,
        "source_url": source_url, "machine_translated": machine,
        "confidence": confidence, "version": VERSION, "updated_at": UPDATED_AT,
    })


# ---------------------------------------------------------------------------
# 1. 来源读取
# ---------------------------------------------------------------------------
def load_who_inn() -> dict[str, dict]:
    out = {}
    with WHO_INN.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            en = (row.get("inn_en") or "").strip()
            if en:
                out.setdefault(norm(en), row)
                out.setdefault(base_name(en), row)
    return out


SALT_WORDS = {
    "hydrochloride", "dihydrochloride", "hydrobromide", "sulfate", "sulphate", "phosphate",
    "sodium", "potassium", "calcium", "magnesium", "besylate", "besilate", "mesylate",
    "maleate", "fumarate", "tartrate", "succinate", "citrate", "acetate", "lactate",
    "nitrate", "bromide", "chloride", "hydrate", "monohydrate", "dihydrate",
    "trihydrate", "hemihydrate", "sesquihydrate", "anhydrous", "disodium", "dipotassium",
}
SYNONYMS = {
    "acetaminophen": "paracetamol", "paracetamol": "acetaminophen",
    "albuterol": "salbutamol", "salbutamol": "albuterol",
    "epinephrine": "adrenaline", "adrenaline": "epinephrine",
    "norepinephrine": "noradrenaline", "noradrenaline": "norepinephrine",
    "furosemide": "frusemide", "frusemide": "furosemide",
    "rifampin": "rifampicin", "rifampicin": "rifampin",
    "glibenclamide": "glyburide", "glyburide": "glibenclamide",
}


def base_name(inn: str) -> str:
    """去掉末尾盐/水合物词，保留母体名。"""
    words = norm(inn).split()
    while words and words[-1] in SALT_WORDS:
        words.pop()
    return " ".join(words)


def load_inn_zh_backfill() -> dict[str, dict]:
    out = {}
    if INN_ZH_BACKFILL.exists():
        with INN_ZH_BACKFILL.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                sid = (row.get("substance_id") or "").strip()
                if sid:
                    out[sid] = row
    return out


def load_es_overrides() -> dict[str, dict]:
    out = {}
    if ES_OVERRIDES.exists():
        with ES_OVERRIDES.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                sid = (row.get("en_substance_id") or "").strip()
                if sid and row.get("status") == "mergeable":
                    out.setdefault(sid, row)
    return out


def load_glossary() -> list[dict]:
    if not GLOSSARY.exists():
        return []
    with GLOSSARY.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_t2s() -> dict[str, str]:
    if not T2S.exists():
        return {}
    data = json.loads(T2S.read_text(encoding="utf-8"))
    pairs = data.get("map") or {}
    # t2s 是「繁→简」，反转为「简→繁」（同一简体取第一个繁体值）
    out: dict[str, str] = {}
    for trad, simp in pairs.items():
        out.setdefault(simp, trad)
    return out


def to_hant(text: str, mapping: dict[str, str]) -> str:
    return "".join(mapping.get(c, c) for c in text)


def extract_url(text: str) -> str:
    m = re.search(r"https?://[^\s，,;；)】]+", text or "")
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# 2. 成分名称
# ---------------------------------------------------------------------------
def build_ingredients(db: sqlite3.Connection) -> None:
    who = load_who_inn()
    backfill = load_inn_zh_backfill()
    es_ov = load_es_overrides()
    t2s = load_t2s()

    substances = db.execute(
        "SELECT substance_id, inn_en, inn_zh FROM substance ORDER BY substance_id").fetchall()
    n_zh = n_zh_hant_ai = n_es_who = n_es_cima = n_pt = 0
    zh_by_source = Counter()
    for sid, inn_en, inn_zh in substances:
        inn_en = (inn_en or "").strip() or sid
        zh = (inn_zh or "").strip()
        src_zh = url_zh = conf_zh = ""
        disp_zh = 0
        if zh:
            bf = backfill.get(sid)
            if bf:
                method = bf.get("method", "")
                confidence = (bf.get("confidence") or "medium").strip()
                src_zh = "regulator"          # 来自 CN 产品通用名 / overrides（NHSA 事实）
                url_zh = extract_url(bf.get("evidence", "")) or URL_NHSA
                conf_zh = confidence
                zh_by_source[f"backfill:{method}"] += 1
            else:
                src_zh = "regulator"          # 既有 inn_zh（旧回填批次，任务-42）
                url_zh = URL_NHSA
                conf_zh = "medium"
                zh_by_source["legacy_batch"] += 1
            disp_zh = 1 if conf_zh == "high" else 0
            n_zh += 1
            add_long("substance", sid, "name", "zh", zh, src_zh, url_zh,
                     machine=0, confidence=conf_zh)

        # zh-Hant：目前没有官方台湾 INN 清单（中華藥典/食藥署无开放批量源）。
        # 不做自动简繁转换写入——错误转换（如「醋酸→醋痠」）比缺名更糟；留空由 build 回退原名。
        zh_hant = ""
        n_zh_hant_ai = 0

        # es：优先 WHO INN 官方西语名；其次 AEMPS CIMA 合并表（待确认许可）
        who_row = who.get(norm(inn_en)) or who.get(base_name(inn_en))
        if not who_row:
            syn = SYNONYMS.get(norm(inn_en)) or SYNONYMS.get(base_name(inn_en))
            if syn:
                who_row = who.get(norm(syn))
        es = src_es = url_es = conf_es = ""
        disp_es = 0
        if who_row and (who_row.get("inn_es") or "").strip():
            es = who_row["inn_es"].strip()
            src_es, url_es, conf_es = "official", who_row.get("source_url") or URL_WHO_INN, "high"
            disp_es = 1
            n_es_who += 1
            add_long("substance", sid, "name", "es", es, src_es, url_es,
                     machine=0, confidence=conf_es)
        elif sid in es_ov and (es_ov[sid].get("es_name") or "").strip():
            es = es_ov[sid]["es_name"].strip()
            src_es = "regulator"
            url_es = extract_url(es_ov[sid].get("evidence", "")) or URL_CIMA
            conf_es = "medium"
            disp_es = 1
            n_es_cima += 1
            add_long("substance", sid, "name", "es", es, src_es, url_es,
                     machine=0, confidence=conf_es)

        # pt：无官方/授权葡语 INN 数据（INFOMED 未授权）→ 留空，不 AI 盲译
        row = {
            "substance_id": sid, "inn_en": inn_en,
            "name_zh": zh, "source_zh": src_zh, "source_url_zh": url_zh,
            "confidence_zh": conf_zh,
            "name_zh_hant": zh_hant, "source_zh_hant": "ai" if zh_hant else "",
            "source_url_zh_hant": "", "confidence_zh_hant": "low" if zh_hant else "",
            "name_es": es, "source_es": src_es, "source_url_es": url_es,
            "confidence_es": conf_es,
            "name_pt": "", "source_pt": "", "source_url_pt": "", "confidence_pt": "",
            "machine_translated": 1 if zh_hant else 0,
            "display_default_zh": disp_zh,
            "display_default_zh_hant": 0,
            "display_default_es": disp_es,
            "display_default_pt": 0,
            "version": VERSION, "updated_at": UPDATED_AT,
            "notes": ("；".join(x for x in [
                ("zh-Hant 无官方批量源，留空（不自动简繁转换）" if zh else ""),
                ("" if zh else "zh 缺官方/半官方来源，留空未盲译"),
            ] if x)),
        }
        ing_rows.append(row)

    stats["ingredients"] = {
        "substances": len(substances),
        "name_en": sum(1 for r in ing_rows if r["inn_en"]),
        "name_zh": n_zh,
        "name_zh_hant_ai": n_zh_hant_ai,
        "name_es_official_who": n_es_who,
        "name_es_cima": n_es_cima,
        "name_pt_official": n_pt,
        "zh_source_breakdown": dict(zh_by_source),
    }


# ---------------------------------------------------------------------------
# 3. 标签（剂型/状态/释放/单位）
# ---------------------------------------------------------------------------
# DB 高频 form_base 中不在术语表 dosage_form 里的补充（人工参考译名；pt 为 INFARMED 常规术语）
EXTRA_FORMS = [
    ("liquid", "liquid", "líquido", "液体", "液體", "líquido"),
    ("topical", "topical", "tópico", "外用", "外用", "tópico"),
    ("pellet", "pellet", "pélete", "微丸", "微丸", "pélete"),
    ("unknown", "unknown", "desconocido", "未知", "未知", "desconhecido"),
    ("inhalation", "inhalation", "inhalación", "吸入剂", "吸入劑", "inalação"),
    ("stick", "stick", "barra", "棒剂", "棒劑", "bastão"),
    ("kit", "kit", "kit", "套装", "套組", "conjunto"),
    ("gas", "gas", "gas", "气体", "氣體", "gás"),
    ("cloth", "cloth", "paño", "布剂", "布劑", "pano"),
    ("soap", "soap", "jabón", "皂剂", "皂劑", "sabão"),
    ("swab", "swab", "torunda", "拭子", "拭子", "zaragatoa"),
    ("mouthwash", "mouthwash", "enjuague bucal", "漱口水", "漱口水", "elixir bucal"),
    ("gum, chewing", "chewing gum", "chicle", "咀嚼胶", "咀嚼膠", "goma de mascar"),
    ("globule", "globule", "glóbulo", "球剂", "球劑", "glóbulo"),
    ("oil", "oil", "aceite", "油剂", "油劑", "óleo"),
    ("rinse", "rinse", "enjuague", "冲洗剂", "沖洗劑", "lavagem"),
    ("jelly", "jelly", "gelatina", "凝胶剂", "凝膠劑", "gelatina"),
    ("灌肠剂", "enema", "enema", "灌肠剂", "灌腸劑", "enema"),
    ("体外诊断试剂", "in-vitro diagnostic reagent", "reactivo de diagnóstico in vitro",
     "体外诊断试剂", "體外診斷試劑", "reagente de diagnóstico in vitro"),
    ("lipstick", "lipstick", "barra de labios", "唇膏", "唇膏", "batom"),
]
EXTRA_RELEASE = [
    ("IR", "immediate-release", "liberación inmediata", "速释", "速釋", "libertação imediata"),
    ("ER", "extended-release", "liberación prolongada", "缓释", "緩釋", "libertação prolongada"),
    ("DR", "delayed-release", "liberación retardada", "迟释/肠溶", "延遲釋放/腸溶", "libertação retardada"),
    ("MR", "modified-release", "liberación modificada", "改良释放", "修飾釋放", "libertação modificada"),
    ("none", "not applicable", "no aplicable", "无", "無", "não aplicável"),
]
# 术语表 dosage_form 行已含常见剂型；这里补充 status/unit 的 pt，并统一 source 口径
STATUS_PT = {"active": "ativo", "discontinued": "descontinuado",
             "withdrawn": "retirado", "unknown": "desconhecido"}
UNIT_PT = {"mg": "mg", "mL": "mL", "ml": "mL", "IU": "UI", "UI": "UI",
           "%": "%", "mEq": "mEq", "g": "g", "mcg": "mcg"}


def source_for_label(source_id: str) -> str:
    return {
        "chp_naming": "pharmacopoeia",
        "who_inn": "official", "who_stem": "official", "ema": "official",
        "tw_pharmacopoeia": "pharmacopoeia", "hk_drugoffice": "regulator",
        "cima": "regulator", "project": "official",
    }.get(source_id, "official")


def build_labels() -> None:
    glossary = load_glossary()
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for row in glossary:
        by_domain[row.get("domain", "")].append(row)

    seen_codes: set[str] = set()

    def add_label(category: str, field: str, code: str, en: str, es: str, zh: str,
                  zh_hant: str, pt: str, *, source_en: str, source_es: str,
                  source_zh: str, source_zh_hant: str, source_pt: str,
                  source_url: str, confidence: str, machine: int, display: int,
                  notes: str = "", url_pt: str = "", url_es: str = "") -> None:
        key = f"{category}:{code}"
        if key in seen_codes or not en:
            return
        seen_codes.add(key)
        label_rows.append({
            "category": category, "code": code, "field": field,
            "en": en, "es": es, "zh": zh, "zh_hant": zh_hant, "pt": pt,
            "source_en": source_en, "source_es": source_es, "source_zh": source_zh,
            "source_zh_hant": source_zh_hant, "source_pt": source_pt,
            "source_url": source_url, "confidence": confidence,
            "machine_translated": machine, "display_default": display,
            "version": VERSION, "updated_at": UPDATED_AT, "notes": notes,
        })
        for lang, value, src in (("en", en, source_en), ("es", es, source_es),
                                 ("zh", zh, source_zh), ("zh-Hant", zh_hant, source_zh_hant),
                                 ("pt", pt, source_pt)):
            url = source_url
            if lang == "pt" and url_pt:
                url = url_pt
            elif lang == "es" and url_es:
                url = url_es
            add_long("label", key, field, lang, value, src, url,
                     machine=machine, confidence=confidence)

    # 术语表中的剂型（中/繁来自药典/命名原则；西语参考 AEMPS；pt 参考 INFARMED 术语）
    for row in by_domain.get("dosage_form", []):
        src = source_for_label(row.get("source_id", ""))
        add_label("form", "form", row["term_en"], row["term_en"], row.get("term_es", ""),
                  row.get("term_zh", ""), row.get("term_zh_hant", ""),
                  _pt_form(row["term_en"]), source_en="official", source_es="regulator",
                  source_zh=src, source_zh_hant=src, source_pt="regulator",
                  source_url=row.get("source_url", ""), confidence=row.get("confidence") or "reference",
                  machine=0, display=1, url_pt=URL_INFOMED, url_es=URL_CIMA,
                  notes="中文剂型名参考药品通用名称命名原则；pt 为 INFARMED/欧洲葡语常规术语（待母语复核）")
    for row in by_domain.get("status", []):
        code = iso(row["term_en"])
        add_label("status", "status", code, row["term_en"], row.get("term_es", ""),
                  row.get("term_zh", ""), row.get("term_zh_hant", ""),
                  STATUS_PT.get(code, ""), source_en="official", source_es="official",
                  source_zh=source_for_label(row.get("source_id", "")),
                  source_zh_hant=source_for_label(row.get("source_id", "")),
                  source_pt="regulator", source_url=row.get("source_url", ""),
                  confidence="reference", machine=0, display=1, url_pt=URL_INFOMED,
                  url_es=URL_CIMA,
                  notes="状态标签；与站点 i18n drug.status.* 对齐，pt 为参考译名")
    for row in by_domain.get("unit", []):
        # 术语表行只用于「是否有官方来源」的参考；实际标签按下方 DB token 输出
        _ = row
    # 补充 DB 高频 form_base（术语表未覆盖的）
    for code, en, es, zh, zh_hant, pt in EXTRA_FORMS:
        add_label("form", "form", code, en, es, zh, zh_hant, pt,
                  source_en="official", source_es="regulator", source_zh="pharmacopoeia",
                  source_zh_hant="pharmacopoeia", source_pt="regulator",
                  source_url=URL_CHP, confidence="reference", machine=0, display=1,
                  url_pt=URL_INFOMED, url_es=URL_CIMA,
                  notes="补充 DB 高频剂型；pt 为欧洲葡语常规术语（待母语复核）")
    # 单位：按 DB strength_unit 原始 token（build 显示时用 code 对齐），中文/葡语为参考写法
    unit_table = [
        ("mg", "mg", "mg", "毫克", "毫克", "mg", 0, 1),
        ("g", "g", "g", "克", "公克", "g", 0, 1),
        ("%", "%", "%", "%", "%", "%", 0, 1),
        ("ml", "ml", "ml", "毫升", "毫升", "mL", 0, 1),
        ("mcg", "mcg", "mcg", "微克", "微克", "mcg", 0, 1),
        ("iu", "IU", "UI", "国际单位", "國際單位", "UI", 0, 1),
        ("unit", "unit(s)", "unidad", "单位", "單位", "unidade", 0, 1),
        ("ug", "mcg", "mcg", "微克", "微克", "mcg", 1, 1),
        ("microgram", "mcg", "mcg", "微克", "微克", "mcg", 1, 1),
        ("l", "L", "L", "升", "升", "L", 0, 1),
        ("万iu", "10k IU", "10 mil UI", "10 万国际单位", "10 萬國際單位", "10 mil UI", 0, 1),
        ("kg", "kg", "kg", "千克", "公斤", "kg", 0, 1),
        ("meq", "mEq", "mEq", "毫当量", "毫當量", "mEq", 0, 1),
        ("u", "U", "U", "单位", "單位", "U", 0, 1),
        ("mci", "mCi", "mCi", "毫居里", "毫居里", "mCi", 0, 1),
        ("IU", "IU", "UI", "国际单位", "國際單位", "UI", 0, 1),
        ("units", "units", "unidades", "单位", "單位", "unidades", 0, 1),
        ("lf", "LF", "LF", "效价单位", "效價單位", "LF", 1, 0),
        ("mm", "mm", "mm", "毫米", "毫米", "mm", 0, 1),
        ("m", "m", "m", "米", "公尺", "m", 0, 1),
    ]
    for code, en, es, zh, zh_hant, pt, machine, display in unit_table:
        add_label("unit", "unit", code, en, es, zh, zh_hant, pt,
                  source_en="official", source_es="official", source_zh="pharmacopoeia",
                  source_zh_hant="pharmacopoeia", source_pt="regulator",
                  source_url=URL_CHP, confidence="reference", machine=machine,
                  display=display, url_pt=URL_INFOMED, url_es=URL_CIMA,
                  notes=("等价写法归一（ug/microgram→mcg），数据显示仍用原始 token" if machine
                         else "国际单位保持原写法；中文/葡语为参考写法"))

    # 释放机制（术语表无 release 域；项目参考译名，pt 用 INFARMED/欧洲葡语术语）
    for code, en, es, zh, zh_hant, pt in EXTRA_RELEASE:
        add_label("release", "release", code, en, es, zh, zh_hant, pt,
                  source_en="official", source_es="regulator", source_zh="pharmacopoeia",
                  source_zh_hant="pharmacopoeia", source_pt="regulator",
                  source_url=URL_CITS, confidence="reference", machine=0,
                  display=0 if code == "none" else 1, url_pt=URL_INFOMED, url_es=URL_CIMA,
                  notes="释放机制标签；none 仅在需要显示时回退「—」")

    stats["labels"] = {
        "rows": len(label_rows),
        "by_category": dict(Counter(r["category"] for r in label_rows)),
        "langs": dict(Counter(lang for r in label_rows for lang in
                              ("en", "es", "zh", "zh_hant", "pt") if r[lang])),
    }


def _pt_form(en: str) -> str:
    table = {
        "tablet": "comprimido", "film-coated tablet": "comprimido revestido por película",
        "capsule": "cápsula", "oral solution": "solução oral", "suspension": "suspensão",
        "injection": "injeção/injetável", "infusion": "infusão", "cream": "creme",
        "ointment": "pomada", "gel": "gel", "suppository": "supositório",
        "inhaler": "inalador", "powder": "pó", "granule": "granulado", "patch": "adesivo",
        "drops": "gotas", "eye drops": "colírio", "nasal spray": "spray nasal",
        "syrup": "xarope", "emulsion": "emulsão",
    }
    return table.get(en.lower(), "")


# ---------------------------------------------------------------------------
# 4. 品牌名（不翻译；只存对应市场原名）
# ---------------------------------------------------------------------------
BRAND_SQL = """
WITH pairs AS (
    SELECT p.country AS country, pn.key_id AS key_id, nv.raw AS raw,
           COUNT(DISTINCT p.product_id) AS n
    FROM product p
    JOIN product_name pn ON pn.product_id = p.product_id AND pn.is_primary = 1
    JOIN name_variant nv ON nv.key_id = pn.key_id
    GROUP BY p.country, pn.key_id, nv.raw
),
ranked AS (
    SELECT country, key_id, raw, n,
           ROW_NUMBER() OVER (PARTITION BY country, key_id ORDER BY n DESC, raw) AS rn
    FROM pairs
)
SELECT country, key_id, raw, n FROM ranked WHERE rn = 1 ORDER BY country, n DESC, key_id
"""


def build_brands(db: sqlite3.Connection, limit_per_market: int) -> None:
    rows = db.execute(BRAND_SQL).fetchall()
    by_country: dict[str, list] = defaultdict(list)
    for country, key_id, raw, n in rows:
        by_country[country].append((n, key_id, raw))
    total_products = db.execute("SELECT country, COUNT(*) FROM product GROUP BY country").fetchall()
    totals = {c: n for c, n in total_products}
    picked = 0
    coverage = {}
    for country, items in by_country.items():
        items.sort(key=lambda t: (-t[0], t[1]))
        chosen = items if limit_per_market <= 0 else items[:limit_per_market]
        lang = COUNTRY_LANG.get(country, "und")
        chosen_products = 0
        chosen_rows = 0
        for n, key_id, raw in chosen:
            if not raw:
                continue
            chosen_rows += 1
            chosen_products += n
            add_long("product_name", f"{country}:{key_id}", "name", lang,
                     raw, "non_translation", "", machine=0, confidence="high")
        picked += chosen_rows
        coverage[country] = {
            "rows": chosen_rows,
            "products": chosen_products,
            "total_products": totals.get(country, 0),
            "coverage_pct": round(100 * chosen_products / max(totals.get(country, 0), 1), 1),
        }
    stats["brand_names"] = {
        "rows": picked,
        "limit_per_market": limit_per_market,
        "coverage_by_market": coverage,
        "note": "品牌名不翻译：value=对应市场 product_name 原值；source=non_translation；"
                "按 (country, key_id) 去重，limit=0 时全量（文件会很大）",
    }


# ---------------------------------------------------------------------------
# 5. 输出
# ---------------------------------------------------------------------------
def write_csv(path: Path, columns: list[str], rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path.stat().st_size


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成翻译来源/版本数据表（只读 DB）")
    ap.add_argument("--brand-limit", type=int, default=2000,
                    help="每个市场品牌原名行数上限（0=全量，文件很大）")
    args = ap.parse_args(argv)

    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        build_ingredients(db)
        build_labels()
        build_brands(db, args.brand_limit)
    finally:
        db.close()

    long_rows.sort(key=lambda r: (r["entity_type"], r["entity_id"], r["field"], r["lang"]))
    sz_long = write_csv(OUT_LONG, LONG_COLUMNS, long_rows)
    sz_ing = write_csv(OUT_ING, ING_COLUMNS, ing_rows)
    sz_label = write_csv(OUT_LABEL, LABEL_COLUMNS, label_rows)

    stats.update({
        "version": VERSION, "updated_at": UPDATED_AT,
        "rows": {"translations": len(long_rows), "ingredients": len(ing_rows),
                 "labels": len(label_rows)},
        "bytes": {"translations": sz_long, "ingredients": sz_ing, "labels": sz_label},
        "long_by_source": dict(Counter(r["source"] for r in long_rows)),
        "long_by_lang": dict(Counter(r["lang"] for r in long_rows)),
        "long_by_entity": dict(Counter(r["entity_type"] for r in long_rows)),
        "machine_translated_rows": sum(1 for r in long_rows if r["machine_translated"]),
        "display_hidden_rows": sum(1 for r in long_rows if r["machine_translated"]),
    })
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "build_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"version={VERSION} updated_at={UPDATED_AT}")
    print(f"wrote {OUT_LONG.relative_to(ROOT)} rows={len(long_rows)} size={sz_long/1e6:.2f} MB")
    print(f"wrote {OUT_ING.relative_to(ROOT)} rows={len(ing_rows)} size={sz_ing/1e6:.2f} MB")
    print(f"wrote {OUT_LABEL.relative_to(ROOT)} rows={len(label_rows)} size={sz_label/1e6:.2f} MB")
    print("long by entity:", stats["long_by_entity"])
    print("long by source:", stats["long_by_source"])
    print("long by lang:", stats["long_by_lang"])
    print("ingredient coverage:", stats["ingredients"])
    print("label stats:", stats["labels"])
    print("brand stats:", {k: stats["brand_names"][k] for k in ("rows", "limit_per_market")})
    for c, v in stats["brand_names"]["coverage_by_market"].items():
        print(f"  brand {c}: {v['rows']} rows, {v['coverage_pct']}% products covered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
