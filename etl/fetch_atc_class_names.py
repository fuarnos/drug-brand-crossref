# -*- coding: utf-8 -*-
"""ATC L1–L4 类名数据：Wikidata（CC0）四语标签 → data/atc_class_names.csv。

背景（reports/atc-intuition-audit.md）：
  - site/build.py 只有 25 个手写 L2–L4 类名 + 14 个 L1 名；1,154 个类目页 96.7% 无类名。
  - DB `substance.atc_name` 59% 空、非空 46.6% 是药名，不是类名；不得用于类目名。

做法：
  1) SPARQL 取 Wikidata 上带 P267（ATC code）且长度 1/3/4/5 的「类目 item」；
  2) `wbgetentities` 批量取 en/zh/zh-hans/zh-hant/zh-tw/zh-hk/es 标签 + 描述 + P31；
  3) 每个 code 选最像「类目」的 item：优先描述里 "therapeutic subgroup ...: <官方类名>"，
     其次非 "ATC code XXX" 的概念标签；**排除与 drug 药名相同的候选**（禁止把药名当类名）；
  4) zh-Hant：优先 Wikidata zh-hant/zh-tw/zh-hk 标签；缺失时用 OpenCC 词典（.tmp/zh-hant/）
     + 台湾药事术语表转换（confidence=medium，报告标注待复核）；
  5) 与 build.py 现有手写 25 条（+14 条 L1）对比：缺失/冲突清单。

只读 DB（mode=ro）；不写 DB / site/build.py；输出 data/atc_class_names.csv + .tmp/atc-names/ 缓存与统计。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import ssl
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
BUILD = ROOT / "site" / "build.py"
OUT_CSV = ROOT / "data" / "atc_class_names.csv"
CACHE = ROOT / ".tmp" / "atc-names"
OPENCC_DIR = ROOT / ".tmp" / "zh-hant"

UA = "ATC-class-names/1.0 (https://github.com/fuarnos/drug-brand-crossref; fuarnos@gmail.com)"
CTX = ssl.create_default_context()
SNAPSHOT = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

SPARQL_CLASSES = """
SELECT DISTINCT ?item ?code ?desc WHERE {
  ?item wdt:P267 ?code .
  FILTER(STRLEN(?code) <= 5)
  OPTIONAL { ?item schema:description ?desc . FILTER(LANG(?desc) = "en") }
}
ORDER BY ?code
"""

# 自建台湾药事/通用术语表（简→繁；OpenCC TWPhrases 未覆盖的常见 ATC 词）
TW_TERMS = {
    "受体": "受體", "抑制剂": "抑制劑", "激动剂": "促效劑", "拮抗剂": "拮抗劑",
    "阻滞剂": "阻斷劑", "阻断剂": "阻斷劑", "抗组胺": "抗組織胺",
    "抗过敏": "抗過敏", "抗菌药": "抗菌藥", "抗病毒药": "抗病毒藥",
    "降压药": "降血壓藥", "降糖药": "降血糖藥", "胃药": "胃藥",
    "激素": "荷爾蒙", "糖皮质激素": "糖皮質激素", "皮质类固醇": "皮質類固醇",
    "非甾体": "非類固醇", "抗炎": "抗發炎", "镇痛": "鎮痛",
    "麻醉": "麻醉", "利尿": "利尿", "抗凝": "抗凝",
    "免疫抑制": "免疫抑制", "抗肿瘤": "抗腫瘤", "抗生素": "抗生素",
    "维生素": "維生素", "电解质": "電解質", "营养": "營養",
    "呼吸系统": "呼吸系統", "消化系统": "消化系統", "心血管": "心血管",
    "神经系统": "神經系統", "皮肤": "皮膚", "泌尿": "泌尿",
    "感觉器官": "感覺器官", "抗寄生虫": "抗寄生蟲", "血液": "血液",
    "全身用": "全身用", "复方": "複方", "单方": "單方",
}
MAX_PHRASE_LEN = 10


# ---------------------------------------------------------------------------
# 网络
# ---------------------------------------------------------------------------
def sparql(query: str, timeout: int = 120) -> dict:
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
        {"query": query, "format": "json"})
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
        return json.loads(resp.read())


def wb_entities(ids: list[str], batch: int = 50) -> dict[str, dict]:
    out: dict[str, dict] = {}
    langs = "en|zh|zh-hans|zh-hant|zh-tw|zh-hk|es"
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": "labels|descriptions|claims", "languages": langs, "format": "json"})
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120, context=CTX) as resp:
            data = json.loads(resp.read())
        out.update(data.get("entities") or {})
    return out


def load_or_fetch_classes(refresh: bool) -> list[dict]:
    cache = CACHE / "wd_class_items_raw.json"
    if cache.exists() and not refresh:
        rows = json.loads(cache.read_text(encoding="utf-8"))
        if isinstance(rows, list):
            # 兼容早期缓存（含 item/code/desc 的 SPARQL bindings）
            out = []
            for r in rows:
                out.append({"item": r["item"]["value"], "code": r["code"]["value"],
                            "desc": (r.get("desc") or {}).get("value", "")})
            return out
    data = sparql(SPARQL_CLASSES)
    rows = [{"item": b["item"]["value"], "code": b["code"]["value"],
             "desc": (b.get("desc") or {}).get("value", "")}
            for b in data["results"]["bindings"]]
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def load_or_fetch_entities(ids: list[str], refresh: bool) -> dict[str, dict]:
    cache = CACHE / "wd_entities.json"
    if cache.exists() and not refresh:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except json.JSONDecodeError:
            pass
    ents = wb_entities(ids)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(ents, ensure_ascii=False), encoding="utf-8")
    return ents


# ---------------------------------------------------------------------------
# OpenCC（简→繁，台湾用语；复用 task-53/70 缓存词典）
# ---------------------------------------------------------------------------
def load_dict(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        src, targets = parts[0].strip(), parts[1].strip().split()
        if src and targets:
            out[src] = targets[0]
    return out


def load_opencc() -> dict[str, dict[str, str]] | None:
    files = {
        "st_phrases": "STPhrases.txt", "st_chars": "STCharacters.txt",
        "tw_phrases": "TWPhrases.txt", "tw_var_phrases": "TWVariantsPhrases.txt",
        "tw_variants": "TWVariants.txt", "ts_chars": "TSCharacters.txt",
    }
    dicts: dict[str, dict[str, str]] = {}
    for key, name in files.items():
        path = OPENCC_DIR / name
        if not path.exists():
            return None
        dicts[key] = load_dict(path)
    # TWP 源词多为繁体；补一份简体键
    expanded = dict(dicts["tw_phrases"])
    ts_chars = dicts["ts_chars"]
    for src, dst in dicts["tw_phrases"].items():
        simp = "".join(ts_chars.get(ch, ch) for ch in src)
        if simp != src:
            expanded.setdefault(simp, dst)
    dicts["tw_phrases_expanded"] = expanded
    return dicts


def apply_phrase_map(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return text
    out, i, n = [], 0, len(text)
    while i < n:
        matched = None
        for length in range(min(MAX_PHRASE_LEN, n - i), 0, -1):
            chunk = text[i:i + length]
            if chunk in mapping:
                matched = (chunk, mapping[chunk])
                break
        if matched:
            out.append(matched[1]); i += len(matched[0])
        else:
            out.append(text[i]); i += 1
    return "".join(out)


def looks_traditional(text: str, dicts: dict[str, dict[str, str]]) -> bool:
    ts = dicts.get("ts_chars") or {}
    return any(ts.get(ch, ch) != ch for ch in text)


def to_simp(text: str, dicts: dict[str, dict[str, str]]) -> str:
    ts = dicts.get("ts_chars") or {}
    return "".join(ts.get(ch, ch) for ch in text)


def to_hant(text: str, dicts: dict[str, dict[str, str]]) -> str:
    """简→繁（台湾用语）。规则同 task-53 build_hant.py：短语优先 → 逐字 STCharacters → 变体/术语兜底。"""
    stages = [
        ("TW", TW_TERMS),
        ("TWP", dicts["tw_phrases_expanded"]),
        ("STP", dicts["st_phrases"]),
        ("TWV", dicts["tw_var_phrases"]),
    ]
    st_chars, tw_variants = dicts["st_chars"], dicts["tw_variants"]
    out, i, n = [], 0, len(text)
    while i < n:
        matched = None
        for _label, mapping in stages:
            for length in range(min(MAX_PHRASE_LEN, n - i), 0, -1):
                chunk = text[i:i + length]
                if chunk in mapping:
                    matched = (mapping[chunk], len(chunk))
                    break
            if matched:
                break
        if matched:
            out.append(matched[0]); i += matched[1]
        else:
            ch = text[i]
            out.append(st_chars.get(ch, ch)); i += 1
    result = "".join(out)
    result = apply_phrase_map(result, dicts["tw_var_phrases"])
    result = apply_phrase_map(result, tw_variants)
    result = apply_phrase_map(result, TW_TERMS)
    return result


# ---------------------------------------------------------------------------
# 构建
# ---------------------------------------------------------------------------
def target_codes() -> set[str]:
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT atc FROM substance WHERE atc IS NOT NULL AND atc <> ''").fetchall()
    finally:
        db.close()
    codes = set()
    for (atc,) in rows:
        atc = (atc or "").strip()
        for ln in (1, 3, 4, 5):
            if len(atc) >= ln:
                codes.add(atc[:ln])
    return codes


def level_of(code: str) -> int:
    return {1: 1, 3: 2, 4: 3, 5: 4}.get(len(code), 0)


def build_py_names() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """返回 (L1 手写名, L2–L4 手写名)。"""
    tree = ast.parse(BUILD.read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("ATC_L1_I18N", "ATC_CLASS_I18N"):
                try:
                    out[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
    return out.get("ATC_L1_I18N", {}), out.get("ATC_CLASS_I18N", {})


def entity_label(ent: dict, lang: str) -> str:
    labels = ent.get("labels") or {}
    val = labels.get(lang) or {}
    return (val.get("value") or "").strip()


def entity_desc(ent: dict) -> str:
    descs = ent.get("descriptions") or {}
    val = descs.get("en") or {}
    return (val.get("value") or "").strip()


BAD_LABEL_RE = re.compile(
    r"(?i)^(anexo|anexo:|categoría|categoria|category|list of|liste|lista de|atc\s*(code|代碼|代码|código|kod)|atc代码|atc代碼|atc分類|atc分类|分类列表|列表)")


def is_code_label(label: str) -> bool:
    label = (label or "").strip()
    if not label:
        return True
    if BAD_LABEL_RE.match(label):
        return True
    # 纯「ATC A01」/「A01 (ATC)」/「Código ATC A01」等
    if re.match(r"(?i)^(atc|código atc|atc代码|atc代碼)\s*[A-Z]?\d{1,6}$", label):
        return True
    return False


def extract_class_name(item_id: str, ent: dict, code: str, drug_names: set[str]) -> dict:
    """从 item 提取类名候选（不把药名当类名）。"""
    desc = entity_desc(ent)
    labels = {lang: entity_label(ent, lang) for lang in
              ("en", "zh", "zh-hans", "zh-hant", "zh-tw", "zh-hk", "es")}
    en_label = labels["en"]
    out: dict = {"item": item_id, "desc": desc, "labels": labels,
                 "name_en": "", "quality": "none", "is_code_item": is_code_label(en_label)}
    # 1) 官方类名：description 里的 therapeutic subgroup: NAME
    m = re.search(r"therapeutic subgroup of the Anatomical Therapeutic Chemical Classification System:\s*([^.;]+)", desc, re.I)
    if m:
        name = m.group(1).strip().rstrip(".")
        out.update(name_en=name, quality="official")
        return out
    # 2) description 里 ... therapeutic subgroup ...（无冒号）→ 用非代码标签
    if "therapeutic subgroup" in desc.lower():
        if en_label and not is_code_label(en_label) and en_label.strip().lower() not in drug_names:
            out.update(name_en=en_label, quality="official-label")
            return out
    # 3) 概念标签（非 "ATC code X"、非药名）
    if en_label and not is_code_label(en_label) and en_label.strip().lower() not in drug_names:
        quality = "concept"
        if any(k in desc.lower() for k in ("class of", "group of", "drugs used", "medication",
                                           "agents", "inhibitor", "blocker", "antibiotic",
                                           "antiviral", "antifungal", " analgesic", "diuretic",
                                           "corticosteroid", "vitamin", "vaccine")):
            quality = "concept-desc"
        out.update(name_en=en_label, quality=quality)
    return out


def pick_names(code: str, candidates: list[dict], dicts: dict | None, drug_names: set[str]) -> dict:
    """从多个 item 中挑出四语名；排除药名。"""
    parsed = []
    for item_id, ent in candidates:
        info = extract_class_name(item_id, ent, code, drug_names)
        if info["name_en"] or not info["is_code_item"]:
            parsed.append(info)
    # 优先 official > official-label > concept-desc > concept > code-label
    order = {"official": 0, "official-label": 1, "concept-desc": 2, "concept": 3, "none": 9}
    parsed.sort(key=lambda x: (order.get(x["quality"], 9), x["is_code_item"]))
    best = next((p for p in parsed if p["name_en"]), parsed[0] if parsed else None)
    row = {"name_en": "", "name_zh": "", "name_es": "", "name_zh_hant": "",
           "confidence": "none", "wikidata_id": "", "notes": ""}
    if not best:
        return row
    row["name_en"] = best["name_en"]
    row["wikidata_id"] = best["item"]
    # 同一 item / 其他候选的本地化标签（非代码标签、非药名）
    def pick_label(langs: tuple[str, ...]) -> str:
        # 只从同一个选中 item 取本地化标签，避免不同概念 item 混出「英文 antithrombotic / 简中 抗血栓 /
        # 繁中 抗凝劑」这种跨来源不一致；缺语言就留空，交由人工覆盖。
        for lang in langs:
            val = best["labels"].get(lang, "")
            if val and not is_code_label(val) and val.strip().lower() not in drug_names:
                return val
        return ""
    raw_zh = pick_label(("zh", "zh-hans"))
    raw_hant = pick_label(("zh-hant", "zh-tw", "zh-hk"))
    row["name_es"] = pick_label(("es",))
    # zh：Wikidata 的 zh 标签有时是繁体（台湾/香港编辑默认），先检测并转简体
    if raw_zh:
        if dicts and looks_traditional(raw_zh, dicts):
            row["name_zh"] = to_simp(raw_zh, dicts)
            if not raw_hant:
                raw_hant = raw_zh
            row["notes"] = "zh 标签原为繁体，已用 TSCharacters 转简体（zh-Hant 保留原标签）"
        else:
            row["name_zh"] = raw_zh
    # zh-Hant：优先 Wikidata 繁体标签；否则 zh→OpenCC+台湾术语转换
    if raw_hant:
        row["name_zh_hant"] = raw_hant
    elif row["name_zh"] and dicts:
        row["name_zh_hant"] = to_hant(row["name_zh"], dicts)
        row["notes"] = (row["notes"] + "；" if row["notes"] else "") +             "zh-Hant 由 zh 经 OpenCC+台湾术语转换，待复核"
    # 置信度：官方类名 > 概念标签；zh-Hant 转换的降为 medium
    if not row["name_en"]:
        row["confidence"] = "none"
    elif best["quality"] in ("official", "official-label"):
        row["confidence"] = "high"
    else:
        row["confidence"] = "medium"
    if row["name_zh_hant"] and not raw_hant and row["confidence"] == "high":
        row["confidence"] = "medium"
    return row


# --- v2 Wikipedia merge ---
WIKI_LANGS = {
    "en": "ATC code {code}",
    "zh": "ATC代码 ({code})",
    "es": "Anexo:Código ATC {code}",
}
WIKI_OUT = ROOT / "data" / "atc_class_names_v2.csv"
WIKI_CACHE = ROOT / ".tmp" / "atc-names2"


def _clean_wiki_name(text: str) -> str:
    s = text or ""
    s = re.sub(r"<ref[^>]*>.*?</ref>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\{\{[^{}]*\}\}", " ", s)
    s = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[.;。;]+$", "", s).strip()
    return s


def _wiki_page_url(lang: str, title: str) -> str:
    return (f"https://{lang}.wikipedia.org/wiki/"
            + urllib.parse.quote(title.replace(" ", "_"), safe="()_,'"))


def _fetch_wiki_pages(codes: list[str], lang: str, refresh: bool) -> dict[str, dict]:
    """抓 L1/L2 页面 wikitext；L3/L4 名称在 L2 页面标题/表格中。"""
    cache = WIKI_CACHE / f"wiki_{lang}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    titles = [WIKI_LANGS[lang].format(code=c) for c in codes if len(c) in (1, 3)]
    pages: dict[str, dict] = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        params = {"action": "query", "titles": "|".join(chunk), "prop": "revisions",
                  "rvprop": "content", "rvslots": "main", "redirects": 1, "format": "json"}
        url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=120, context=CTX) as resp:
            data = json.loads(resp.read())
        for p in (data.get("query", {}).get("pages") or {}).values():
            if "missing" in p or "revisions" not in p:
                continue
            title = p.get("title", "")
            try:
                slot = p["revisions"][0]["slots"]["main"]
                text = slot.get("*") or slot.get("content") or ""
            except (KeyError, IndexError):
                continue
            pages[title] = {"text": text, "url": _wiki_page_url(lang, title)}
        print(f"  wiki {lang}: fetched {min(i + 50, len(titles))}/{len(titles)}", flush=True)
    WIKI_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return pages


def _parse_wiki_names(lang: str, pages: dict[str, dict], target: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}

    def put(code: str, name: str, url: str) -> None:
        code = (code or "").strip().upper()
        name = _clean_wiki_name(name)
        if code not in target or not name or len(name) > 120:
            return
        out.setdefault(code, {"name": name, "url": url})

    for title, page in pages.items():
        text, url = page["text"], page["url"]
        if lang == "en":
            for m in re.finditer(r'id="([A-Z0-9]{3,5})"></span>\s*([A-Z0-9]{3,5})\s+([^=<]+?)\s*=+', text):
                put(m.group(1), m.group(3), url)
            for m in re.finditer(r"\{\{ATC codes lead\|([A-Z])\|(\d{2})(?:\|([^}|]+))?\}\}", text):
                if m.group(3):
                    put(m.group(1) + m.group(2), m.group(3), url)
        elif lang == "zh":
            for m in re.finditer(r"\{\{anchor\|([A-Z0-9]{3,5})\}\}\s*([A-Z0-9]{3,5})\s+([^=（<\n]+)", text):
                put(m.group(1), m.group(3), url)
            for m in re.finditer(r"\{\{ATC codes lead\|([A-Z])\|(\d{2})(?:\|([^}|]+))?\}\}", text):
                if m.group(3):
                    put(m.group(1) + m.group(2), m.group(3), url)
        else:  # es
            for m in re.finditer(r"==+\s*([A-Z0-9]{2,5})\s+([^=\n]+?)\s*==+", text):
                put(m.group(1), m.group(2), url)
            for m in re.finditer(r"'''\s*([A-Z0-9]{3,5})\s+([^*<\n]+?)\s*\.?\s*'''", text):
                put(m.group(1), m.group(2), url)
    return out


def _license_of(source: str) -> str:
    return {"editorial": "editorial (project)", "wikidata": "CC0 1.0",
            "wikipedia": "CC BY-SA 4.0",
            "wikipedia-zh-converted": "CC BY-SA 4.0 (derived zh-Hant)"}.get(source, "")


def build_v2(UA_: str, CTX_, ROOT_, BUILD_, OUT_CSV_, level_of_, build_py_names_,
             load_opencc_, to_hant_) -> int:
    """参数由 etl/fetch_atc_class_names.py 注入（避免跨文件重复 import 循环）。"""
    global UA, CTX, ROOT, BUILD, OUT_CSV
    UA, CTX, ROOT, BUILD, OUT_CSV = UA_, CTX_, ROOT_, BUILD_, OUT_CSV_
    WIKI_CACHE.mkdir(parents=True, exist_ok=True)
    import csv as _csv
    editorial_l2 = {
        "A05": "Bile and liver therapy", "A12": "Mineral supplements",
        "A16": "Other alimentary tract and metabolism products",
        "B05": "Blood substitutes and perfusion solutions",
        "C01": "Cardiac therapy", "L03": "Immunostimulants",
    }
    v1 = list(_csv.DictReader(open(OUT_CSV, encoding="utf-8-sig")))
    codes = [r["code"] for r in v1]
    target = set(codes)
    by_code_v1 = {r["code"]: r for r in v1}
    l1_manual, class_manual = build_py_names_()
    manual: dict[str, dict[str, str]] = {}
    for lang, mapping in l1_manual.items():
        for code, name in (mapping or {}).items():
            manual.setdefault(code, {})[lang] = name
    for lang, mapping in class_manual.items():
        for code, name in (mapping or {}).items():
            manual.setdefault(code, {})[lang] = name
    dicts = load_opencc_()

    wiki_names: dict[str, dict[str, dict]] = {}
    for lang in WIKI_LANGS:
        pages = _fetch_wiki_pages(codes, lang, False)
        wiki_names[lang] = _parse_wiki_names(lang, pages, target)
        print(f"  wiki {lang}: parsed {len(wiki_names[lang])} codes", flush=True)

    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (s or "").lower())

    rows, conflicts = [], []
    coverage = Counter()
    by_level = defaultdict(Counter)
    missing = defaultdict(list)
    for code in codes:
        level = level_of_(code)
        base = by_code_v1[code]
        names, sources, urls = {}, {}, {}
        for lang in ("en", "zh", "es"):
            manual_name = (manual.get(code, {}) or {}).get(lang, "").strip()
            v1_name = (base.get("name_" + lang) or "").strip()
            wi = wiki_names.get(lang, {}).get(code)
            wiki_name = (wi or {}).get("name", "").strip()
            if wiki_name and (manual_name or v1_name) and norm(wiki_name) != norm(manual_name or v1_name):
                conflicts.append({"code": code, "lang": lang,
                                  "higher": manual_name or v1_name,
                                  "higher_source": "editorial" if manual_name else "wikidata",
                                  "wikipedia": wiki_name})
            if manual_name:
                names[lang], sources[lang], urls[lang] = manual_name, "editorial", ""
            elif v1_name:
                names[lang], sources[lang], urls[lang] = v1_name, "wikidata", base.get("source_url") or ""
            elif wiki_name:
                names[lang], sources[lang], urls[lang] = wiki_name, "wikipedia", (wi or {}).get("url", "")
            elif lang == "en" and code in editorial_l2:
                names[lang], sources[lang], urls[lang] = editorial_l2[code], "editorial", ""
            else:
                names[lang], sources[lang], urls[lang] = "", "", ""
        manual_hant = (manual.get(code, {}) or {}).get("zh-Hant", "").strip()
        v1_hant = (base.get("name_zh_hant") or "").strip()
        notes = ""
        if manual_hant:
            hant, src_hant, url_hant = manual_hant, "editorial", ""
        elif v1_hant:
            hant, src_hant, url_hant = v1_hant, "wikidata", base.get("source_url") or ""
        elif names.get("zh") and dicts:
            hant = to_hant_(names["zh"], dicts)
            src_hant, url_hant = "wikipedia-zh-converted", urls.get("zh", "")
            if hant and hant != names["zh"]:
                notes = "zh-Hant 由 Wikipedia zh 经 OpenCC+台湾术语转换，待复核"
        else:
            hant, src_hant, url_hant = "", "", ""
        row = {"code": code, "level": level,
               "name_en": names["en"], "name_zh": names["zh"],
               "name_es": names["es"], "name_zh_hant": hant,
               "source_en": sources["en"], "source_zh": sources["zh"],
               "source_es": sources["es"], "source_zh_hant": src_hant,
               "url_en": urls["en"], "url_zh": urls["zh"],
               "url_es": urls["es"], "url_zh_hant": url_hant,
               "license_en": _license_of(sources["en"]), "license_zh": _license_of(sources["zh"]),
               "license_es": _license_of(sources["es"]), "license_zh_hant": _license_of(src_hant),
               "fallback_text": f"ATC {code} · 类名待补充", "notes": notes}
        for lang, key in (("en", "name_en"), ("zh", "name_zh"), ("es", "name_es"), ("zh-Hant", "name_zh_hant")):
            if row[key]:
                coverage[lang] += 1
                by_level[level][f"name_{lang}"] += 1
            else:
                missing[lang].append(code)
        by_level[level]["total"] += 1
        if any(row[k] for k in ("name_en", "name_zh", "name_es", "name_zh_hant")):
            by_level[level]["any"] += 1
        rows.append(row)

    header = ["code", "level", "name_en", "name_zh", "name_es", "name_zh_hant",
              "source_en", "source_zh", "source_es", "source_zh_hant",
              "url_en", "url_zh", "url_es", "url_zh_hant",
              "license_en", "license_zh", "license_es", "license_zh_hant",
              "fallback_text", "notes"]
    with WIKI_OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    stats = {"total": len(rows), "coverage": dict(coverage),
             "by_level": {str(k): dict(v) for k, v in sorted(by_level.items())},
             "conflicts_count": len(conflicts), "conflicts_sample": conflicts[:40],
             "missing": {k: len(v) for k, v in missing.items()},
             "missing_sample": {k: v[:40] for k, v in missing.items()}}
    (WIKI_CACHE / "build_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    (WIKI_CACHE / "conflicts.json").write_text(
        json.dumps(conflicts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {WIKI_OUT.relative_to(ROOT)} rows={len(rows)}")
    print("coverage:", dict(coverage))
    print("by level:", json.dumps(stats["by_level"], ensure_ascii=False))
    print("missing:", stats["missing"], "wiki conflicts:", len(conflicts))
    return 0

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Wikidata ATC class names -> CSV（CC0）")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重新抓 Wikidata/Wikipedia")
    ap.add_argument("--v2", action="store_true", help="生成 v2（人工/编辑 > Wikidata > Wikipedia）")
    args = ap.parse_args(argv)
    if args.v2:
        return build_v2(UA, CTX, ROOT, BUILD, OUT_CSV, level_of, build_py_names,
                        load_opencc, to_hant)
    CACHE.mkdir(parents=True, exist_ok=True)

    codes = target_codes()
    raw = load_or_fetch_classes(args.refresh)
    by_code: dict[str, list[dict]] = defaultdict(list)
    item_ids: set[str] = set()
    for r in raw:
        code = (r.get("code") or "").strip()
        item_uri = r.get("item") or ""
        if not code or code not in codes:
            continue
        iid = item_uri.rsplit("/", 1)[-1]
        if not iid:
            continue
        by_code[code].append({"item": iid, "desc": r.get("desc") or ""})
        item_ids.add(iid)
    ents = load_or_fetch_entities(sorted(item_ids), args.refresh)

    # 药名集合（禁止把药名当类名）
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        drug_names = {(r[0] or "").strip().lower() for r in
                      db.execute("SELECT inn_en FROM substance WHERE inn_en IS NOT NULL AND inn_en <> ''")}
    finally:
        db.close()
    dicts = load_opencc()
    if dicts is None:
        print("WARN: OpenCC 词典缺失（.tmp/zh-hant/），zh-Hant 仅用 Wikidata 标签，不自动转换")

    rows = []
    stats = {"by_level": defaultdict(lambda: Counter()), "quality": Counter(),
             "excluded_drug_like": 0, "code_label_items": 0}
    for code in sorted(codes, key=lambda c: (level_of(c), c)):
        level = level_of(code)
        cands = []
        for c in by_code.get(code, []):
            ent = ents.get(c["item"])
            if not ent:
                continue
            cands.append((c["item"], ent))
        names = pick_names(code, cands, dicts, drug_names)
        if not names["name_en"] and not names["name_zh"] and not names["name_es"]:
            stats["by_level"][level]["none"] += 1
        row = {
            "code": code, "level": level,
            "name_en": names["name_en"], "name_zh": names["name_zh"],
            "name_es": names["name_es"], "name_zh_hant": names["name_zh_hant"],
            "source_url": f"https://www.wikidata.org/wiki/{names['wikidata_id']}" if names["wikidata_id"] else "",
            "license": "CC0" if names["wikidata_id"] else "",
            "confidence": names["confidence"] if names["wikidata_id"] else "none",
            "wikidata_id": names["wikidata_id"],
            "notes": names["notes"],
        }
        rows.append(row)
        stats["by_level"][level]["total"] += 1
        stats["quality"][row["confidence"]] += 1
        for lang, key in (("en", "name_en"), ("zh", "name_zh"), ("es", "name_es"), ("zh-Hant", "name_zh_hant")):
            if row[key]:
                stats["by_level"][level][f"name_{lang}"] += 1
        if row["source_url"]:
            stats["by_level"][level]["any"] += 1

    # 写 CSV
    header = ["code", "level", "name_en", "name_zh", "name_es", "name_zh_hant",
              "source_url", "license", "confidence", "wikidata_id", "notes"]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    import csv as _csv
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)

    # 与 build.py 手写名对比
    l1_manual, class_manual = build_py_names()
    manual: dict[str, dict[str, str]] = {}
    for lang, mapping in l1_manual.items():
        for code, name in (mapping or {}).items():
            manual.setdefault(code, {})[lang] = name
    for lang, mapping in class_manual.items():
        for code, name in (mapping or {}).items():
            manual.setdefault(code, {})[lang] = name
    by_code_rows = {r["code"]: r for r in rows}
    compare = {"manual_codes": len(manual), "in_csv": 0, "missing_in_csv": [], "conflicts": [],
               "same": 0, "wikidata_missing_code": []}
    for code, langs in manual.items():
        row = by_code_rows.get(code)
        if not row or not row["name_en"]:
            compare["missing_in_csv"].append({"code": code, "manual_en": langs.get("en", ""),
                                             "level": level_of(code)})
            continue
        compare["in_csv"] += 1
        for lang, csv_key in (("en", "name_en"), ("zh", "name_zh"), ("es", "name_es"),
                              ("zh-Hant", "name_zh_hant")):
            m = (langs.get(lang) or "").strip()
            w = (row.get(csv_key) or "").strip()
            if not m or not w:
                continue
            norm = lambda s: re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", s.lower())
            if norm(m) == norm(w):
                compare["same"] += 1
            else:
                compare["conflicts"].append({"code": code, "lang": lang, "manual": m,
                                             "wikidata": w, "confidence": row["confidence"]})
    missing_codes = sorted(set(codes) - set(by_code))
    compare["wikidata_missing_code"] = missing_codes[:50]
    compare["wikidata_missing_count"] = len(missing_codes)

    stats_out = {
        "generated_at": SNAPSHOT,
        "target_codes": len(codes),
        "wikidata_items": len(item_ids),
        "codes_with_items": len(by_code),
        "by_level": {str(k): dict(v) for k, v in sorted(stats["by_level"].items())},
        "confidence": dict(stats["quality"]),
        "manual_compare": compare,
        "total_rows": len(rows),
        "coverage": {
            lang: sum(1 for r in rows if r[key]) for lang, key in
            (("en", "name_en"), ("zh", "name_zh"), ("es", "name_es"), ("zh-Hant", "name_zh_hant"))
        },
    }
    (CACHE / "build_stats.json").write_text(
        json.dumps(stats_out, ensure_ascii=False, indent=1), encoding="utf-8")
    (CACHE / "manual_compare.json").write_text(
        json.dumps(compare, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT_CSV.relative_to(ROOT)} rows={len(rows)}")
    print(f"target codes={len(codes)}; codes with Wikidata item={len(by_code)}; "
          f"coverage={stats_out['coverage']}")
    print("by level:", json.dumps(stats_out["by_level"], ensure_ascii=False))
    print("confidence:", stats_out["confidence"])
    print("manual compare: in_csv=%d missing_in_csv=%d conflicts=%d same=%d" % (
        compare["in_csv"], len(compare["missing_in_csv"]), len(compare["conflicts"]), compare["same"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
