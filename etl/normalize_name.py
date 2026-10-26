"""商品名归一化：把任何国家、任何文字的输入压成可比较的查找键。

设计要点
--------
1. 归一化在构建索引和查询时**必须走同一个函数**，否则匹配永远对不上。
2. 中文保留汉字（不走拼音），另存 `compact`（去空格）用于连写匹配。
3. 西里尔字母转写成拉丁，因为俄语/乌克兰语包装上的商品名和英文名常是同一串音。
4. 强度从名字里切出来单独存：`Sortis 20mg` 的名字是 sortis，不是 sortis20mg。
5. 剂型/释放机制词只做提示，不参与名字键——它们是消歧用的分面，不是身份。

已知待补
--------
- 繁简表目前是药名常用的约 90 字，不是全表；后续换 OpenCC 的完整 T2S 表。
- 汉字尚未产出拼音键（`pinyin`），做中英互查时需要补。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --- 西里尔 → 拉丁 ---------------------------------------------------------
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # 乌克兰语补充
    "і": "i", "ї": "i", "є": "ye", "ґ": "g",
}

# --- 繁体 → 简体（药名常用字，非全表） --------------------------------------
_T2S = {
    "鹽": "盐", "黴": "霉", "靈": "灵", "膠": "胶", "錠": "锭", "劑": "剂",
    "釋": "释", "緩": "缓", "濕": "湿", "顆": "颗", "軟": "软", "噴": "喷",
    "霧": "雾", "靜": "静", "脈": "脉", "註": "注", "懸": "悬", "腸": "肠",
    "鉀": "钾", "鈉": "钠", "鎂": "镁", "鈣": "钙", "鋅": "锌", "鐵": "铁",
    "銅": "铜", "維": "维", "環": "环", "諾": "诺", "羥": "羟", "腎": "肾",
    "膽": "胆", "臟": "脏", "壓": "压", "貧": "贫", "過": "过", "寧": "宁",
    "鎮": "镇", "熱": "热", "瀉": "泻", "嘔": "呕", "暈": "晕", "頭": "头",
    "癲": "癫", "癇": "痫", "癢": "痒", "銀": "银", "癬": "癣", "瘡": "疮",
    "膿": "脓", "癒": "愈", "復": "复", "發": "发", "蘇": "苏", "雙": "双",
    "醣": "糖", "鑒": "鉴", "驗": "验", "臨": "临", "藥": "药", "醫": "医",
    "體": "体", "質": "质", "類": "类", "長": "长", "點": "点", "開": "开",
    "關": "关", "準": "准", "製": "制", "廠": "厂", "國": "国", "產": "产",
    "進": "进", "衛": "卫", "屬": "属", "專": "专", "說": "说", "書": "书",
    "對": "对", "應": "应", "為": "为", "與": "与", "號": "号", "時": "时",
    "間": "间", "無": "无", "萬": "万", "舊": "旧", "輕": "轻", "釋": "释",
}

# --- 剂型 / 释放机制词（只做提示，不进名字键） -------------------------------
_FORM_TOKENS = {
    "tablet", "tablets", "tab", "tabs", "capsule", "capsules", "cap", "caps",
    "film", "coated", "coatedtablet", "sugar", "sugarcoated",
    "sr", "er", "xr", "xl", "mr", "cr", "dr", "ir", "gits", "od",
    "oral", "solution", "suspension", "syrup", "injection", "infusion",
    "cream", "ointment", "gel", "drops", "drop", "spray", "inhaler",
    "suppository", "patch", "powder", "granules", "sachet",
    "片", "錠", "锭", "粒", "胶囊", "膠囊", "袋", "瓶", "支", "丸",
    "缓释", "緩釋", "控释", "控釋", "肠溶", "腸溶", "分散", "咀嚼",
    "口崩", "糖浆", "糖漿", "口服液", "注射液", "乳膏", "软膏", "軟膏",
    "凝胶", "凝膠", "喷雾", "噴霧", "吸入", "栓", "贴", "貼", "粉", "颗粒",
    # 配方限定词：不删掉会污染成分键（"Paracetamol ... sugar free" → paracetamol free）
    "free", "soluble", "dispersible", "effervescent", "orodispersible",
    "sugar-free", "sf",
}

_TRADEMARK = re.compile(r"[®™©]")

# 强度：先配比（875/125 mg）、再浓度（5 mg/5 ml）、最后单值
_RE_RATIO = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[/:]\s*(\d+(?:[.,]\d+)?)\s*(mg|mcg|µg|μg|g|мг|мкг|г)\b",
    re.IGNORECASE,
)
_RE_CONC = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg|mcg|µg|μg|g|iu|ме|мг|мкг|г)\s*/\s*"
    r"(\d+(?:[.,]\d+)?)\s*(ml|мл|l|л)\b",
    re.IGNORECASE,
)
_RE_RATIO_NOUNIT = re.compile(r"\b(\d{2,4})\s*/\s*(\d{2,4})\b")
_RE_SINGLE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg|mcg|µg|μg|ug|g|ml|ml|iu|ме|мг|мкг|г|мл|%|万单位)\b",
    re.IGNORECASE,
)

_UNIT = {
    "мг": "mg", "мкг": "mcg", "г": "g", "мл": "ml", "ме": "iu",
}


def _unit(u: str) -> str:
    return _UNIT.get(u.lower(), u.lower())


def _script(s: str) -> str:
    for ch in s:
        if "\u4e00" <= ch <= "\u9fff":
            return "han"
        if "\u0400" <= ch <= "\u04ff":
            return "cyrillic"
    return "latin"


def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c)
    )


def _translit(s: str) -> str:
    out = []
    for ch in s:
        if ch in _CYR:
            out.append(_CYR[ch])
        elif ch.isascii():
            out.append(ch)
        elif ch.isspace():
            out.append(" ")
        else:
            out.append(" ")
    return "".join(out)


def _t2s(s: str) -> str:
    return "".join(_T2S.get(c, c) for c in s)


@dataclass(frozen=True)
class NormName:
    """归一化结果。`norm` 是主键，`compact` 是连写备用键。"""

    norm: str
    compact: str
    strengths: tuple[tuple[str, str], ...]
    form_hint: tuple[str, ...]
    script: str
    raw: str

    @property
    def is_empty(self) -> bool:
        return not self.norm


def normalize(raw: str) -> NormName:
    """把任意写法的商品名/通用名压成可比较的键。"""
    src = raw or ""
    script = _script(src)

    s = unicodedata.normalize("NFKC", src)
    s = _TRADEMARK.sub(" ", s).casefold()

    if script == "cyrillic":
        s = _translit(s)
    if script == "han":
        s = _t2s(s)

    s = _strip_diacritics(s)

    strengths: list[tuple[str, str]] = []
    forms: list[str] = []

    def take_ratio(m: re.Match) -> str:
        u = _unit(m.group(3))
        strengths.append((m.group(1).replace(",", "."), u))
        strengths.append((m.group(2).replace(",", "."), u))
        return " "

    def take_conc(m: re.Match) -> str:
        strengths.append(
            (f"{m.group(1).replace(',', '.')}/{m.group(3).replace(',', '.')}",
             f"{_unit(m.group(2))}/{_unit(m.group(4))}")
        )
        return " "

    def take_single(m: re.Match) -> str:
        strengths.append((m.group(1).replace(",", "."), _unit(m.group(2))))
        return " "

    s = _RE_RATIO.sub(take_ratio, s)
    s = _RE_CONC.sub(take_conc, s)
    s = _RE_SINGLE.sub(take_single, s)

    def take_ratio_nounit(m: re.Match) -> str:
        strengths.append((m.group(1), ""))
        strengths.append((m.group(2), ""))
        return " "

    s = _RE_RATIO_NOUNIT.sub(take_ratio_nounit, s)

    # 标点与符号折叠成空格
    s = re.sub(r"[\-–—_/\\.,;:!?()\[\]{}'\"’‘“”·•*&+]", " ", s)
    tokens = s.split()

    kept: list[str] = []
    for t in tokens:
        if t in _FORM_TOKENS:
            if t not in forms:
                forms.append(t)
            continue
        kept.append(t)

    norm = " ".join(kept)
    return NormName(
        norm=norm,
        compact=norm.replace(" ", ""),
        strengths=tuple(strengths),
        form_hint=tuple(forms),
        script=script,
        raw=src,
    )
