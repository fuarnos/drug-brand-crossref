#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中文俗名/别名抽取 → 成分映射 → Tier B 候选 CSV（不写数据库）。

输入（按可用性合并）：
  1. `data/raw/cn_slang/raw_terms.jsonl`（另一 agent 抓取；有则用，字段
     term/platform/url/title/snippet/fetched_at/lang）—— 用「俗称/外号/又叫/也叫/
     黑话/网络叫法」等句式从 title+snippet 抽取术语，并用同文中的库内药名做锚点定成分；
  2. 仓库现有别名表：
     - `reports/cn_aliases.csv`（alias → target_cn，source=wikipedia/wikidata）
     - `reports/wiki_aliases.csv`（wiki_title / alias / kind / pageid）
     - `data/cn_aliases_final.csv`（alias → name，前两者的合并表）
     - `reports/ahospital_aliases.csv`（name → alias，公开健康平台页面整理）

处理：
  * 归一化：NFKC（全半角/上标）、去空格标点、繁→简；
  * 过滤：首尾功能词/句子碎片、纯剂型词、纯商品名（已在 product_name 中）、
    毒品/娱乐性用药（整条丢弃并计数）、同形异义无法唯一确定成分（substance_id 留空，标 ambiguous）；
  * 与库内（只读）商品名/成分名/别名精确或剥剂型/盐基规则匹配得到 substance_id；
  * Tier B 定案：全部进 drug_term（不新增 nickname）；2 个独立来源→documented，1 个→community；
  * 去重：nickname + drug_term + product_name（只读查库）+ 本表内部按 normalized 去重。

输出：
  `data/cn_slang_candidates.csv`（列：term,normalized,lang,region,platform,substance_id,
  method,confidence,source_url,snippet,license,term_type,label_zh）
  以及终端统计（Tier B / Tier C 计数、来源分布、样例）。

用法：
    python etl/extract_cn_slang.py            # 写 CSV
    python etl/extract_cn_slang.py --dry-run  # 只统计不写文件
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
import ingest_nhsa as nh  # noqa: E402
from normalize_name import _T2S, normalize  # noqa: E402

DB = ROOT / "data" / "drugs.db"
RAW_TERMS = ROOT / "data" / "raw" / "cn_slang" / "raw_terms.jsonl"
OUT_CSV = ROOT / "data" / "cn_slang_candidates.csv"
CN_ALIASES = ROOT / "reports" / "cn_aliases.csv"
WIKI_ALIASES = ROOT / "reports" / "wiki_aliases.csv"
FINAL_ALIASES = ROOT / "data" / "cn_aliases_final.csv"
AHOSPITAL = ROOT / "reports" / "ahospital_aliases.csv"

# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
RE_SPACES = re.compile(r"[\s\u3000]+")
RE_PUNCT = re.compile(r"[·•・\-—_/\\.,;:!?()\[\]{}'\"’‘“”《》<>]+")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


# 药名常见繁体字 → 简体（人工整理；只做「繁体→简体」，绝不反向猜）
_EXTRA_T2S = {
    "黴": "霉", "鹽": "盐", "銨": "铵", "鹼": "碱", "桿": "杆",
    "韋": "韦", "樂": "乐", "諾": "诺", "嗎": "吗", "靈": "灵",
    "醯": "酰", "膽": "胆", "臟": "脏", "壓": "压", "熱": "热",
    "鎮": "镇", "寧": "宁", "腎": "肾", "腸": "肠", "濕": "湿",
    "顆": "颗", "軟": "软", "霧": "雾", "靜": "静", "脈": "脉",
    "註": "注", "懸": "悬", "鐵": "铁", "銅": "铜", "鋅": "锌",
    "鈣": "钙", "鎂": "镁", "鈉": "钠", "鉀": "钾", "劑": "剂",
    "膠": "胶", "錠": "锭", "釋": "释", "緩": "缓", "癬": "癣",
    "癢": "痒", "醣": "糖", "鑒": "鉴", "驗": "验", "藥": "药",
    "醫": "医", "體": "体", "質": "质", "類": "类", "長": "长",
    "點": "点", "開": "开", "關": "关", "製": "制", "廠": "厂",
    "國": "国", "產": "产", "進": "进", "衛": "卫", "專": "专",
    "說": "说", "書": "书", "對": "对", "應": "应", "為": "为",
    "與": "与", "號": "号", "時": "时", "間": "间", "無": "无",
    "萬": "万", "舊": "旧", "輕": "轻", "檸": "柠", "檸檬": "柠檬",
    "氫": "氢", "鋇": "钡", "鉍": "铋", "鋁": "铝", "鉬": "钼",
    "鈷": "钴", "錳": "锰", "鉻": "铬", "鈦": "钛", "釓": "钆",
    "鉑": "铂", "銥": "铱", "鎝": "锝", "鎵": "镓", "鉈": "铊",
    "釔": "钇", "鑥": "镥", "鐳": "镭", "釙": "钋", "碼": "码",
    "羥": "羟", "嗎啡": "吗啡", "嗎": "吗", "吩": "吩", "啶": "啶",
    "嗪": "嗪", "唑": "唑", "哌": "哌", "咪": "咪", "噻": "噻",
    "吲": "吲", "哚": "哚", "喹": "喹", "爾": "尔", "酯": "酯",
    "醚": "醚", "酮": "酮", "酚": "酚", "醛": "醛", "醇": "醇",
    "醯胺": "酰胺", "睾": "睾", "睪": "睾", "黃": "黄", "苷": "苷",
    "黴素": "霉素", "激素": "激素", "膽鹼": "胆碱", "膽": "胆",
    "腎上腺": "肾上腺", "腎": "肾", "甲狀腺": "甲状腺", "狀": "状",
    "腎上腺素": "肾上腺素", "嗎啉": "吗啉", "嗎啉胍": "吗啉胍",
    "胍": "胍", "呱": "呱", "唄": "呗", "噠": "哒", "腖": "胨",
    "泓": "泓", "羥基": "羟基", "羥": "羟", "羧": "羧", "碸": "砜",
}
T2S = {**_T2S, **_EXTRA_T2S}


def to_simplified(s: str) -> str:
    return "".join(T2S.get(c, c) for c in s)


def norm_key(s: str) -> str:
    """用于去重/匹配的键：全半角、简繁、空格标点全压掉。"""
    s = nfkc(s)
    s = RE_SPACES.sub("", s)
    s = RE_PUNCT.sub("", s)
    return to_simplified(s).lower()


def term_display(s: str) -> str:
    """展示用：去首尾空白，保留原写法。"""
    return re.sub(r"\s+", " ", nfkc(s)).strip()


# ---------------------------------------------------------------------------
# 合法性 / 质量过滤
# ---------------------------------------------------------------------------
# 毒品与娱乐性用药（术语本身或映射到的成分命中即整条丢弃，计入 Tier C）
DRUG_ABUSE_TERMS = [
    "冰毒", "甲基苯丙胺", "摇头丸", "麻古", "麻果", "K粉", "海洛因",
    "白粉", "可卡因", "古柯碱", "大麻", "飞叶子", "笑气", "一氧化二氮",
    "神仙水", "开心水", "蓝精灵", "浴盐", "丧尸药", "邮票", "麦角酸",
    "致幻剂", "迷幻药", "迷幻蘑菇", "天使粉", "摇头水", "奶茶粉", "咖啡包",
    "彩虹烟", "上头电子烟", "合成大麻素", "安非他命", "迷奸药", "听话水",
    "蒙汗药", "乖乖水", "催情水", "γ-羟基丁酸", "GHB",
    "K仔", "k仔", "K他命", "k他命", "特别K", "特K", "揹K", "O仔",
    "白瓜子", "蓝精灵",
]
# 上述有些是合法处方药/前体，是否丢弃按「映射到的管制成分」判断（见 DRUG_ABUSE_SIDS）
DRUG_ABUSE_SIDS = {
    "methamphetamine", "cocaine", "heroin", "diamorphine", "mdma",
    "methylenedioxymethamphetamine", "cannabis", "tetrahydrocannabinol", "lsd",
    "lysergic-acid-diethylamide", "psilocybine", "psilocybin",
    "ghb", "gamma-hydroxybutyrate", "phencyclidine",
    "synthetic-cannabinoid", "mephedrone", "cathinone",
}
# 句子碎片/功能词：命中即丢
JUNK_PATTERNS = [
    r"上市", r"首次", r"批准", r"用于", r"一种", r"属于", r"称为", r"又称", r"也叫",
    r"^是", r"^为", r"^的", r"^在", r"^与", r"^和", r"^或", r"^等", r"^及",
    r"成分", r"制剂", r"剂量", r"服用", r"疗效", r"作用", r"适应症", r"说明书",
    r"化学名", r"商品名$", r"通用名", r"英文名", r"别名$",
    r"注射剂$", r"片剂$", r"口服液$", r"胶囊剂$", r"栓剂$", r"咀嚼片$", r"滴眼液$",
    r"以其为", r"制成",
]
RE_JUNK = re.compile("|".join(JUNK_PATTERNS))
RE_HAN = re.compile(r"[\u4e00-\u9fff]")
RE_ONLY_HAN_PUNCT = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9·\-]+$")
# 剂量/规格/数字串
RE_DOSE = re.compile(r"\d+\s*(mg|ml|g|μg|ug|片|粒|袋|支|瓶|万单位|iu)", re.I)

# 来源平台 → (platform, license)
SOURCE_META = {
    "cn_aliases.csv": ("wikipedia_zh", "CC BY-SA 4.0（维基百科/维基数据；仅存短名+链接）"),
    "wiki_aliases.csv": ("wikipedia_zh", "CC BY-SA 4.0（维基百科重定向；仅存短名+链接）"),
    "cn_aliases_final.csv": ("wikipedia_zh", "CC BY-SA 4.0（维基百科/维基数据合并表）"),
    "ahospital_aliases.csv": ("alihealth_cn", "公开健康平台页面整理（许可待确认；仅存短名+链接）"),
    "raw_terms": ("community_web", "用户/社区公开内容（仅存叫法事实+原链接）"),
}


def is_junk_term(term: str, target: str) -> str:
    t = term_display(term)
    if not t or not RE_HAN.search(t):
        return "非中文/空"
    if len(t) < 2:
        return "太短"
    if len(t) > 16:
        return "句子碎片（过长）"
    if RE_DOSE.search(t):
        return "含剂量/规格"
    if not RE_ONLY_HAN_PUNCT.match(t):
        return "含异常标点"
    if RE_JUNK.search(t):
        return "句子碎片/功能词"
    if re.search(r"[A-Za-z]{2,}", t):
        return "含英文片段"
    if re.search(r"出售|销售|等於|包括|也作|市面|通用名|學名藥|学名药", t):
        return "句子碎片/功能词"
    if re.search(r"什么|来源|體系|体系|^叫|^为|^為|^其|^法|^名|药名$|名称$", t):
        return "句子碎片/功能词"
    if re.search(r"梗|段子|玩笑|揭秘|真相|恶搞|注意|测评|攻略|网友|评论", t):
        return "段子/点评/网络噪音"
    if t[0].isascii():
        return "化学系统名/编号"
    if t[0].isdigit() and not re.match(r"^\d{2,4}[\u4e00-\u9fff]{2,8}$", t):
        return "化学系统名/编号"
    if len(t) > 10 and len(re.findall(r"氨基|羟基|羧基|甲基|乙基|丙基|丁基|苯基|硝基|巯基|酰|酮|醛|醇|酯|醚", t)) >= 3:
        return "化学系统名"
    if norm_key(t) == norm_key(target):
        return "与规范名相同"
    return ""


def legality(term: str, sids: list[str], sid_names: dict[str, str]) -> str:
    """毒品/娱乐性用药过滤：返回原因，空字符串=通过。"""
    k = norm_key(term)
    for bad in DRUG_ABUSE_TERMS:
        if norm_key(bad) and norm_key(bad) in k:
            return f"毒品/娱乐性用药词：{bad}"
    for sid in sids:
        base = sid_names.get(sid, "").split("-")[0]
        if sid in DRUG_ABUSE_SIDS or base in DRUG_ABUSE_SIDS:
            return f"映射到管制/娱乐性成分：{sid_names.get(sid, sid)}"
    return ""


# ---------------------------------------------------------------------------
# DB（只读）索引
# ---------------------------------------------------------------------------
def build_db_index(con: sqlite3.Connection) -> dict:
    cur = con.cursor()
    sub = {sid: (zh or en or sid) for sid, en, zh in
           cur.execute("SELECT substance_id, inn_en, inn_zh FROM substance")}
    sub_en = {sid: (en or "") for sid, en in
              cur.execute("SELECT substance_id, inn_en FROM substance")}

    base_index: dict[str, set[str]] = defaultdict(set)  # 中文名（剥剂型/盐基）→ sids
    for sid, zh in cur.execute("SELECT substance_id, inn_zh FROM substance"):
        if zh and zh.strip():
            base_index[norm_key(zh)].add(sid)
            for c in nh.reduction_chain(zh.strip()):
                base_index[norm_key(c)].add(sid)
    # 中文商品名（所有国家，script=han）→ sids；用剥剂型后的基名做索引
    for nm, sid in cur.execute("""
        SELECT DISTINCT nk.norm, v.substance_id
        FROM product_name pn
        JOIN name_key nk ON nk.key_id = pn.key_id
        JOIN product p ON p.product_id = pn.product_id
        JOIN product_component pc ON pc.product_id = p.product_id
        JOIN variant v ON v.variant_id = pc.variant_id
        WHERE nk.script = 'han'
    """):
        base_index[norm_key(nm)].add(sid)
        for c in nh.reduction_chain(nm):
            base_index[norm_key(c)].add(sid)
    # 库内别名（nickname + drug_term）
    db_alias: dict[str, set[str]] = defaultdict(set)
    for a, sid in cur.execute("SELECT alias_norm, substance_id FROM nickname"):
        db_alias[norm_key(a)].add(sid)
    for a, sid in cur.execute("SELECT term_norm, substance_id FROM drug_term"):
        db_alias[norm_key(a)].add(sid)
        if sid:
            base_index[norm_key(a)].add(sid)
    # 去重用：全部商品名 norm + 现有 nickname/drug_term norm
    pn_all = {norm_key(n) for (n,) in cur.execute(
        "SELECT DISTINCT norm FROM name_key")}
    existing_terms = {norm_key(a) for (a,) in cur.execute(
        "SELECT alias_norm FROM nickname")} | {norm_key(t) for (t,) in cur.execute(
            "SELECT term_norm FROM drug_term")}
    return dict(sub=sub, sub_en=sub_en, base_index=base_index, db_alias=db_alias,
                pn_all=pn_all, existing_terms=existing_terms, sub_names=sub)


def resolve(target: str, idx: dict) -> tuple[list[str], str]:
    """规范名 → substance 候选 + 匹配方法。"""
    candidates = [target] + [c for c in nh.reduction_chain(target) if c != target]
    for c in candidates:
        k = norm_key(c)
        if not k:
            continue
        if k in idx["base_index"]:
            sids = sorted(idx["base_index"][k])
            if len(sids) == 1:
                return sids, "exact" if c == target else "chain"
            return sids, "ambiguous"
        if k in idx["db_alias"] and idx["db_alias"][k]:
            sids = sorted(idx["db_alias"][k])
            return (sids, "alias") if len(sids) == 1 else (sids, "ambiguous")
    # 尝试维基百科/维基数据处理后的规范名
    n = normalize(target)
    for key in (n.norm, n.compact):
        k = norm_key(key)
        if k in idx["base_index"]:
            sids = sorted(idx["base_index"][k])
            return (sids, "normalize") if len(sids) == 1 else (sids, "ambiguous")
    return [], ""


RE_PATTERN = re.compile(
    r"(?:又称|又名|又叫|也叫|俗称|俗称作|俗称做|俗称其|别称|别名|外号|简称|通常叫|通常称|"
    r"民间叫|网络叫法|网络叫|黑话|谐音|代称|商品名|商品名称|商业用名|品牌名|商标名|注册名|"
    r"译名|旧称|曾用名|中文名|音译)(?:则)?(?:为|作|做|叫|有|是|包括|如|例如|：|:)?"
    r"[「『“\"']?([\u4e00-\u9fff0-9A-Za-z·\-/、]{2,20})[」』”\"']?"
)
RE_REVERSE = re.compile(
    r"([\u4e00-\u9fff0-9A-Za-z·\-]{2,12})的(?:通用名|学名|成分名|药品名|有效成分|INN)"
)
RE_TITLE_BRAND = re.compile(
    r"^([\u4e00-\u9fff0-9A-Za-z·\-]{2,12}?)(?:又叫|也叫|俗称|是什么药|是什么|的通用名|的商品名|"
    r"别名|外号)"
)
RE_TITLE_ALIAS = re.compile(
    r"^(.{2,30}?)[（(](?:俗称|又名|别名|又称|也叫|又叫)[：:为]?\s*"
    r"([\u4e00-\u9fffA-Za-z0-9·\-]{2,16})[)）]"
)



def clean_brand(x: str) -> str:
    x = re.sub(r"^(?:叫|为|為|作|做|其|了|是|有)", "", (x or "").strip())
    x = re.sub(r"(?:等等|之类的|之类|等药|等物|等)$", "", x).strip()
    return x


def extract_from_text(text: str) -> list[dict]:
    """从标题/摘要抽取 (term, pattern) 对。"""
    out: list[dict] = []
    def clean_term(x: str) -> str:
        x = re.sub(r"^(?:则|包括|如|例如|及其|叫|为|為|作|做|其|了|是|有)", "", x.strip())
        x = re.sub(r"(?:等等|之类的|之类|等药|等物|等)$", "", x).strip()
        return x

    for m in RE_PATTERN.finditer(text or ""):
        for term in re.split(r"[/、]", m.group(1)):
            term = clean_term(term)
            if 2 <= len(term) <= 16:
                out.append(dict(term=term, pattern=m.group(0)[:40]))
    for m in RE_REVERSE.finditer(text or ""):
        term = clean_term(m.group(1))
        if 2 <= len(term) <= 12:
            out.append(dict(term=term, pattern="反向：X的通用名为Y"))
    m = RE_TITLE_ALIAS.search(text or "")
    if m:
        out.append(dict(term=clean_term(m.group(2)), pattern="标题模式"))
    return out



GENERIC_WORDS = {
    "口服", "注射", "静脉", "肌肉", "外用", "局部", "成人", "儿童", "婴儿", "孕妇",
    "哺乳", "患者", "药物", "药品", "治疗", "用于", "每天", "每日", "一次", "常见",
    "商品名", "通用名", "化学名", "别名", "名称", "作用", "功效", "适应症", "剂量",
    "片剂", "胶囊", "颗粒", "溶液", "软膏", "乳膏", "滴眼液", "注射液", "复方",
}


def _is_generic_word(s: str) -> bool:
    return len(s) <= 2 or s in GENERIC_WORDS


def anchors_in_text(text: str, idx: dict) -> list[tuple[str, str, int]]:
    """在同文中找库内药名作为成分锚点（最长优先，去重叠）。

    返回 [(substance_id, 命中的中文名)]。
    """
    found: list[tuple[int, int, str]] = []
    k = norm_key(text)
    # 直接扫描原文的连续子串：长度 2-12
    plain = nfkc(text)
    for L in range(12, 1, -1):
        for i in range(0, max(0, len(plain) - L + 1)):
            cand = plain[i:i + L]
            if not RE_HAN.search(cand):
                continue
            key = norm_key(cand)
            if key and key in idx["base_index"]:
                found.append((i, i + L, cand))
    # 去重叠：长优先
    found.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
    used: list[tuple[int, int]] = []
    hits: list[tuple[str, str, int]] = []
    for a, b, cand in found:
        if any(not (b <= ua or a >= ub) for ua, ub in used):
            continue
        used.append((a, b))
        for sid in sorted(idx["base_index"][norm_key(cand)]):
            hits.append((sid, cand, a))
    seen = set()
    out = []
    for sid, cand, pos in hits:
        if (sid, cand) in seen:
            continue
        seen.add((sid, cand))
        out.append((sid, cand, pos))
    return out


# ---------------------------------------------------------------------------
# 收集候选
# ---------------------------------------------------------------------------
def load_alias_tables() -> list[dict]:
    recs: list[dict] = []

    def add(term, target, platform, url, snippet, license_, method):
        recs.append(dict(term=term, target=target, platform=platform, source_url=url,
                         snippet=snippet, license=license_, method=method))

    if CN_ALIASES.exists():
        for row in csv.DictReader(open(CN_ALIASES, encoding="utf-8-sig")):
            a, t = row.get("alias", ""), row.get("target_cn", "")
            if not a or not t:
                continue
            src = (row.get("source") or "wikipedia").strip()
            url = (f"https://www.wikidata.org/w/index.php?search={quote(t)}"
                   if src == "wikidata" else
                   f"https://zh.wikipedia.org/wiki/{quote(t)}")
            add(a, t, "wikipedia_zh" if src != "wikidata" else "wikidata",
                url, f"{src}：{t} 的别名 {a}", SOURCE_META["cn_aliases.csv"][1],
                "alias_table")
    wiki_url_by_pageid: dict[str, str] = {}
    if WIKI_ALIASES.exists():
        for row in csv.DictReader(open(WIKI_ALIASES, encoding="utf-8-sig")):
            a, t = row.get("alias", ""), row.get("wiki_title", "")
            pageid = (row.get("pageid") or "").strip()
            if not a or not t:
                continue
            url = (f"https://zh.wikipedia.org/?curid={pageid}" if pageid
                   else f"https://zh.wikipedia.org/wiki/{quote(t)}")
            add(a, t, "wikipedia_zh", url, f"wikipedia redirect：{t} ← {a}",
                SOURCE_META["wiki_aliases.csv"][1], "alias_table")
            if pageid:
                wiki_url_by_pageid.setdefault(t, url)
    if FINAL_ALIASES.exists():
        for row in csv.DictReader(open(FINAL_ALIASES, encoding="utf-8-sig")):
            a, t = row.get("alias", ""), row.get("name", "")
            if not a or not t:
                continue
            url = wiki_url_by_pageid.get(t) or f"https://zh.wikipedia.org/wiki/{quote(t)}"
            add(a, t, "wikipedia_zh", url, f"别名表：{t} ← {a}",
                SOURCE_META["cn_aliases_final.csv"][1], "alias_table")
    if AHOSPITAL.exists():
        for row in csv.DictReader(open(AHOSPITAL, encoding="utf-8-sig")):
            a, t = row.get("alias", ""), row.get("name", "")
            if not a or not t:
                continue
            url = (f"https://www.alihealth.cn/search?keyword={quote(t)}")
            add(a, t, "alihealth_cn", url, f"公开健康平台页面：{t} 的别名 {a}",
                SOURCE_META["ahospital_aliases.csv"][1], "alias_table")
    return recs


def load_raw_terms(idx: dict) -> tuple[list[dict], Counter]:
    """raw_terms.jsonl 存在时：句式抽取 + 锚点定成分。"""
    stats: Counter = Counter()
    recs: list[dict] = []
    if not RAW_TERMS.exists():
        return recs, stats
    for ln in RAW_TERMS.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            stats["bad_json"] += 1
            continue
        stats["rows"] += 1
        text = " ".join(str(r.get(k) or "") for k in ("title", "snippet", "term"))
        platform = str(r.get("platform") or "community_web")
        url = str(r.get("url") or r.get("source_url") or "")
        license_ = str(r.get("license") or SOURCE_META["raw_terms"][1])
        anchors = anchors_in_text(text, idx)
        extracted = extract_from_text(text)
        mt = RE_TITLE_BRAND.search(str(r.get("title") or ""))
        if mt:
            extracted.append(dict(term=clean_brand(mt.group(1)), pattern="标题品牌词"))
        # 原始 term 字段本身也算一条候选
        if r.get("term"):
            extracted.append(dict(term=str(r["term"]), pattern="raw_term"))
        for e in extracted:
            sids, method = resolve(e["term"], idx)
            if not sids and anchors:
                nterm = norm_key(e["term"])
                # 术语在原文中的位置：优先标题里的位置，否则第一次出现
                tpos = -1
                for src in (str(e.get("_title") or ""), text):
                    if e["term"] in src:
                        tpos = src.find(e["term"])
                        break
                valid = [(abs(pos - tpos), sid) for sid, cand, pos in anchors
                         if len(cand) >= 3 and norm_key(cand) not in nterm
                         and not _is_generic_word(cand)]
                if valid:
                    valid.sort()
                    best_dist = valid[0][0]
                    near = [sid for dist, sid in valid if dist <= best_dist + 40]
                    sids = list(dict.fromkeys(near))
                    method = "anchor_in_context"
            if not sids:
                stats["no_substance"] += 1
                continue
            stats["with_substance"] += 1
            recs.append(dict(term=e["term"], target="", platform=platform,
                             source_url=url,
                             snippet=text[:200], license=license_,
                             method=method, sids_hint=sids,
                             pattern=e.get("pattern", ""),
                             _title=str(r.get("title") or "")))
    return recs, stats


def classify_term_type(term: str, method: str, pattern: str) -> str:
    if re.search(r"黑话|外号|网络叫法|谐音|代称", pattern or ""):
        return "street"
    if re.search(r"(药|针|丸|片)$", term) and len(term) <= 4:
        return "class"
    if method == "alias_table" or pattern in ("raw_term", "标题模式"):
        return "folk"
    return "folk"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="抽取中文俗名候选（Tier B，不写库）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写 CSV")
    args = ap.parse_args()

    con = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
    idx = build_db_index(con)
    con.close()

    records = load_alias_tables()
    raw_recs, raw_stats = load_raw_terms(idx)
    records.extend(raw_recs)

    drop = Counter()
    accepted: dict[str, dict] = {}   # norm_key -> candidate
    for r in records:
        term = term_display(r["term"])
        term = re.sub(r"^(?:有|包括|如|例如)", "", term).strip()
        reason = is_junk_term(term, r.get("target") or "")
        if reason:
            drop[reason] += 1
            continue
        if not (r.get("source_url") or "").strip():
            drop["无来源链接"] += 1
            continue
        # 目标 → substance
        sids: list[str] = list(r.get("sids_hint") or [])
        method = r.get("method", "")
        if not sids:
            sids, m = resolve(r["target"], idx) if r.get("target") else ([], "")
            method = m or method
        # 用 term 自身再试一次（有些 term 本身就是库内成分名/商品名变体）
        if not sids:
            sids, m = resolve(term, idx)
            method = m or method
        if not sids:
            drop["目标未映射到库内成分（无法确认药品）"] += 1
            continue
        if len(sids) > 1:
            en_pref = [s for s in sids
                       if not s.startswith(("cn-", "mx-es-"))]
            if len(en_pref) == 1:
                sids = en_pref
                method = (method or "") + "+disambiguated"
            else:
                drop["同形异义（映射到多个成分）"] += 1
                continue
        legal = legality(term, sids, idx["sub_names"])
        if legal:
            drop["毒品/娱乐性用药"] += 1
            continue
        key = norm_key(term)
        if not key:
            drop["归一化后为空"] += 1
            continue
        if key in idx["base_index"]:
            drop["与库内规范名/成分名相同（非俗名）"] += 1
            continue
        # 去重：库内已有 nickname/drug_term/product_name
        if key in idx["existing_terms"]:
            drop["库内已有 nickname/drug_term"] += 1
            continue
        if key in idx["pn_all"]:
            drop["纯商品名（已在 product_name）"] += 1
            continue
        # 展示写法：保留原始写法（繁体/异体），normalized 才是简体去标点键
        display = term
        is_hant = to_simplified(term) != term
        ttype = classify_term_type(display, method, r.get("pattern", ""))
        sid = sids[0] if (len(sids) == 1 and ttype != "class") else ""
        label_zh = idx["sub_names"].get(sid, "") if sid else ""
        src = dict(platform=r.get("platform", ""), source_url=r.get("source_url", ""),
                   snippet=r.get("snippet", ""), license=r.get("license", ""),
                   method=method, term_type=ttype)
        platform = r.get("platform", "")
        # 独立来源：平台 + 主域名（wikipedia 视为同一来源族）
        dom = re.sub(r"^https?://", "", r.get("source_url", "")).split("/")[0]
        src_id = "wikipedia" if platform.startswith("wikipedia") else (
            "wikidata" if platform == "wikidata" else (dom or platform))
        cur = accepted.get(key)
        if cur is None:
            cur = dict(term=display, normalized=key,
                       lang="zh-Hant" if is_hant else "zh-Hans",
                       region="CN", platform=platform, substance_id=sid,
                       method=method, source_url=r.get("source_url", ""),
                       snippet=r.get("snippet", ""), license=r.get("license", ""),
                       term_type=ttype, label_zh=label_zh,
                       _sources=set(), _sids=set(sids), _license=set(),
                       _platforms=Counter(), _methods=set())
            accepted[key] = cur
        cur["_sources"].add(src_id)
        cur["_sids"].update(sids)
        cur["_platforms"][platform] += 1
        cur["_methods"].add(method)
        if r.get("license"):
            cur["_license"].add(r["license"])
        if not cur["snippet"] and r.get("snippet"):
            cur["snippet"] = r["snippet"]
        if not cur["source_url"] and r.get("source_url"):
            cur["source_url"] = r["source_url"]
        if not cur["substance_id"] and len(sids) == 1 and cur["term_type"] != "class":
            cur["substance_id"] = sids[0]
            cur["label_zh"] = idx["sub_names"].get(sids[0], "")

    rows: list[dict] = []
    tier_b = Counter()
    for key, c in accepted.items():
        n_src = len(c["_sources"])
        confidence = "documented" if n_src >= 2 else "community"
        # 同形异义：多来源映射到不同成分 → substance_id 留空并标 ambiguous
        sids = c["_sids"]
        sid = c["substance_id"] if len(sids) <= 1 else ""
        label_zh = idx["sub_names"].get(sid, "") if sid else ""
        method = ",".join(sorted(c["_methods"]))
        if len(sids) > 1:
            method = "ambiguous"
        if not sid:
            tier_b["substance_unmapped"] += 1
        else:
            tier_b["with_substance"] += 1
        examples = "" if sid else ";".join(sorted(sids)[:5])
        tier_b[f"confidence_{confidence}"] += 1
        tier_b[f"type_{c['term_type']}"] += 1
        rows.append(dict(
            term=c["term"], normalized=c["normalized"], lang=c["lang"],
            region=c["region"], platform=";".join(p for p in c["_platforms"]),
            substance_id=sid, method=method, confidence=confidence,
            source_url=c["source_url"], snippet=c["snippet"][:200],
            license="; ".join(sorted(c["_license"])) or
                    SOURCE_META.get("raw_terms", ("", ""))[1],
            term_type=c["term_type"], label_zh=label_zh, examples=examples))

    # 排序：有成分优先、documented 优先、按术语
    rows.sort(key=lambda r: (r["substance_id"] == "", r["confidence"] != "documented",
                             r["term"]))
    cols = ["term", "normalized", "lang", "region", "platform", "substance_id",
            "method", "confidence", "source_url", "snippet", "license",
            "term_type", "label_zh", "examples"]
    if not args.dry_run:
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)

    # ---- 统计 ----
    print("== 输入 ==")
    print(f"raw_terms: {raw_stats or '无 raw_terms.jsonl'}")
    print(f"别名表记录: {len(records)}（其中 raw: {len(raw_recs)}）")
    print("\n== Tier C（丢弃）==")
    for k, v in drop.most_common():
        print(f"  {k}: {v}")
    print(f"  合计丢弃: {sum(drop.values())}")
    print("\n== Tier B（候选）==")
    print(f"去重后候选: {len(rows)}")
    for k, v in tier_b.most_common():
        print(f"  {k}: {v}")
    print(f"  可入库（有 substance_id）: {sum(1 for r in rows if r['substance_id'])}")
    print(f"  documented: {sum(1 for r in rows if r['confidence'] == 'documented')}")
    print(f"  nickname 新增: 0（本轮只进 drug_term）")
    print("\n== 来源分布 ==")
    for k, v in Counter(r["platform"].split(";")[0] for r in rows).most_common():
        print(f"  {k}: {v}")
    print("\n== 样例（有成分 + documented）==")
    n = 0
    for r in rows:
        if r["substance_id"] and r["confidence"] == "documented":
            print(f"  {r['term']} → {r['label_zh']}({r['substance_id']}) "
                  f"[{r['term_type']}/{r['platform']}]")
            n += 1
            if n >= 25:
                break
    if not args.dry_run:
        print(f"\n写入 {OUT_CSV}")


if __name__ == "__main__":
    main()
