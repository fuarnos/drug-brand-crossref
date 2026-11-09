"""四语（en / es / zh / zh-Hant）i18n 一致性门禁（只读、纯静态、毫秒级）。

规则来源（用户 2026-11-10）：**多语言翻译要同步更新，写进底层逻辑，不能英语和西语滞后。**
也就是四语必须键集一致、内容同步，缺译不许静默回落英文，而且必须由构建期/CI 拦住，
不能靠人记得改。

本脚本是这条规则的**静态守卫**：不建站、不读库、不联网，只解析
  site/build.py                          18 个 i18n 字典常量（AST，不 import，避免副作用）
  data/i18n_zh_hant.json                 zh-Hant 覆盖字典（缺键时构建期回落简体 zh）
  data/release_notes_i18n.json           What's new 的四语译文（逐版本逐条）
  CHANGELOG.md                           版本与条目数的唯一真相源
  data/terminology_glossary.csv          术语表（专有名词 / 缩写，用于「同形」白名单判定）

规则（默认 --strict：有 FAIL 即退出码 1）
  FAIL  键集不一致：某语言缺 key（会给完整 key 清单），或 dict 里多出 en 没有的 key
  FAIL  缺译：非 en 语言的值与其 en 值完全相同，且不属于专有名词 / 缩写 / 单位 /
        有意同形（白名单见 PSEUDO_OK_KEYS / PSEUDO_ACRONYMS / UNITS）
  FAIL  zh-Hant 缺键：既不在 build.py 的 zh-Hant 字典里、也不在 i18n_zh_hant.json 里
        （构建期会静默回落简体 zh，等于繁体用户看到简体）
  FAIL  zh-Hant 未转换：json 值与 zh 值相同且含「只可能是简体」的字
  FAIL  最新版 release notes 缺语言：CHANGELOG 第一节在 json 里缺 zh/en/es/zh-Hant，
        或条目数与 CHANGELOG 不符（这正是「英语和西语滞后」最常发生的地方）
  FAIL  术语不一致：LABEL_I18N 的剂型 / 释放机制译名与 data/label_translations.csv 不符
        （单位符号类紧凑写法已在 LABEL_TERM_OK 登记，不算不一致）
  FAIL  模板引用了不存在的 key：data-i18n="x.y" 在合并后的字典里找不到（页面会渲染空白）
  WARN  值等于英文但命中白名单（可疑同形：缩写 / 外来词 / 疑似机器翻译没改）
  WARN  陈旧 key：字典里有、en 没有；json 里有、base 里没有
  WARN  历史版本 release notes 缺语言（积压；不阻断，但要清）
  WARN  硬编码文案：HTML 模板里直接写、没走 data-i18n（标出影响哪些语言）
  INFO  有意同形 / 大型三语并列块（例如 LICENCE_HTML 的许可原文，四语并列展示是设计要求）

用法
    python deploy/i18n_check.py                          # 人类可读摘要
    python deploy/i18n_check.py --json .tmp/i18n.json    # 额外写机器可读 JSON
    python deploy/i18n_check.py --no-strict              # 只报告，退出码恒 0（排查用）
    python deploy/i18n_check.py --max-list 200           # 摘要里每类最多列几条（默认 40）

接在 deploy/ci_checks.py 里（fast 与全量都跑）；也可单独跑。
边界：本脚本只读文件，不改 build.py / 译文；与 etl/check_translations.py 分工——
那边查「译得对不对」（术语 / 数字 / 单位 / 占位符 / HTML），这边查「有没有、齐不齐」。
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_PY = ROOT / "site" / "build.py"
ZH_HANT_JSON = ROOT / "data" / "i18n_zh_hant.json"
RELEASE_JSON = ROOT / "data" / "release_notes_i18n.json"
CHANGELOG = ROOT / "CHANGELOG.md"
GLOSSARY_CSV = ROOT / "data" / "terminology_glossary.csv"
# 剂型 / 释放机制 / 单位 / 状态的四语术语表（项目内唯一真相源，见 reports/terminology-accuracy.md）
LABEL_CSV = ROOT / "data" / "label_translations.csv"

LANGS = ("en", "es", "zh", "zh-Hant")
BASE_LANGS = ("en", "es", "zh")

# site/build.py 里的 18 个 i18n 字典（顺序 = 声明顺序；新增字典请同步加到这里）
I18N_DICTS = (
    "I18N", "LABEL_I18N", "COVERAGE_I18N", "NAME_LANG_I18N", "UI_I18N", "SHELL_I18N",
    "GLOSSARY_I18N", "ABOUT_I18N", "PAGE_I18N", "META_I18N", "WARN_I18N", "COMBO_I18N",
    "MAKER_I18N", "FILTER_I18N", "BILINGUAL_I18N", "ATC_I18N", "ATC_L1_I18N",
    "ATC_CLASS_I18N",
)
# 这 7 个字典不写 zh-Hant，繁体由 data/i18n_zh_hant.json 覆盖（构建期回落简体 zh）
ZH_HANT_FROM_JSON = {"I18N", "ABOUT_I18N", "PAGE_I18N", "META_I18N", "WARN_I18N",
                     "COMBO_I18N", "MAKER_I18N"}
# build.py 里真正合并进 I18N（= i18n.js 下发字典）的字典：模块级 COVERAGE/NAME_LANG
# 各有一段 setdefault().update()，其余走 _merge_static_i18n()。顺序与 build.py 一致。
I18N_MERGED = ("ABOUT_I18N", "PAGE_I18N", "WARN_I18N", "COMBO_I18N", "MAKER_I18N",
               "META_I18N", "GLOSSARY_I18N", "ATC_I18N", "BILINGUAL_I18N", "FILTER_I18N",
               "LABEL_I18N", "UI_I18N", "SHELL_I18N", "COVERAGE_I18N", "NAME_LANG_I18N")
# 只在服务端用的字典（不合并进 I18N）：仍按四语键集检查，但不进「合并后字典」口径
I18N_SERVER_ONLY = ("ATC_L1_I18N", "ATC_CLASS_I18N")

# ── 白名单：有意「四语同形」的 key（值本来就该一样）─────────────────────────
# 键 = i18n key（任意字典），值 = 原因。只放「不需要翻译」的，别拿它盖住真缺译。
PSEUDO_OK_KEYS: dict[str, str] = {
    "release.none": "占位符 —（不是文案）",
    "unit.iu": "IU/UI 之外的同形单位写法，见 LABEL_I18N 注释",
    "unit.unit": "单位名在 es 与 en 同形（unidad 已单独使用）",
    "unit.mci": "mCi 是国际单位符号",
    "unit.ug": "mcg 是国际单位符号",
    "unit.microgram": "mcg 是国际单位符号",
    "atc.label": "ATC 是专有缩写",
    "glossary.t.inn": "INN 专有缩写，不翻译",
    "glossary.t.ban": "BAN 专有缩写，不翻译",
    "glossary.t.usan": "USAN 专有缩写，不翻译",
    "glossary.t.mah": "MAH 专有缩写，不翻译",
    "glossary.t.din": "DIN 专有缩写，不翻译",
    "glossary.t.ndc": "NDC 专有缩写，不翻译",
    "glossary.t.artg": "ARTG 专有缩写，不翻译",
    "glossary.t.fdc": "FDC 专有缩写，不翻译",
    "glossary.t.lasa": "LASA / tall-man 是专有提法，原文保留",
    "glossary.t.otc": "OTC 专有缩写，不翻译",
    "glossary.t.rx": "Rx 是处方符号",
    "bilingual.source.manual": "editorial 在 es 同形（editado 会更含糊）",
    "parse.match.nickname": "alias 在 es 同形",
    "parse.match.pinyin": "pinyin 是拼音专名",
    "warn.sev.info": "Info 是 es 常用缩写（informativa 只用于长句）",
    # 市场名：es 里 China / Australia / Hong Kong 就是原名
    "home.cn": "China 在 es 同形",
    "home.au": "Australia 在 es 同形",
    "home.hk": "Hong Kong 在 es 同形",
    # NAME_LANG_I18N 全部 key 由 _pseudo_lang_ok 统一放行（角标用「该名字自身的语言」）
}
# 可疑同形（WARN）：外来词 / 只换了大小写的词，值得人看一眼
PSEUDO_SUSPECT_KEYS: dict[str, str] = {
    "form.pellet": "pellet 在 es 医学术语里可用，但也可写 gránulo/pellets",
    "form.stick": "stick 在 es 里是外来词（可写 barra/pluma）",
    "form.kit": "kit 在 es 同形，但也可写 equipo",
    "form.gas": "gas 在 es 同形（gas/ gaseous 均可），确认即可",
}
# LABEL_I18N 里刻意用「紧凑显示缩写」的 key：与 data/label_translations.csv 的全称不同，
# 属于设计选择（页面表格宽度有限），不算术语不一致。
LABEL_TERM_OK: dict[str, str] = {
    "unit.mci": "显示用单位符号 mCi（术语表给全称「毫居里」）",
    "unit.ug": "显示用单位符号 mcg（术语表给「微克」）",
    "unit.microgram": "显示用单位符号 mcg（术语表给「微克」）",
    "unit.万iu": "「10 万 IU」为紧凑写法（术语表给「10 万国际单位」）",
    "unit.meq": "「meq / mEq」大小写差异，视为同一符号",
    "release.none": "「—」是空值占位符，术语表的 not applicable 不进表格",
    "release.DR": "界面用「延迟释放/改良释放」区分 ER/MR，术语表给「迟释/肠溶」",
}
# 单位 / 缩写类 token：值属于这些就当作「不需要翻译」
UNITS = {"mg", "mcg", "μg", "ug", "g", "kg", "ml", "mL", "l", "L", "IU", "UI", "%",
         "mEq", "mCi", "meq", "—", "-", "·", "×"}
# 专有名词 / 缩写：值全大写且 ≤8 字符、或命中 glossary 的 term_en，视为不翻译
ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9/&+.\- ]{1,11}$")

# ── 硬编码文案：已知可接受（品牌名 / 三语并列法律块）────────────────────────────
HARDCODED_INFO_TEXTS: dict[str, str] = {
    "Medicine Brand Cross-Reference": "站点英文名，属于品牌（标题多语化见 reports 的 P1）",
    "药品商品名跨国定位": "站点中文名，属于品牌",
}
HARDCODED_INFO_CONSTS: dict[str, str] = {
    "LICENCE_HTML": "许可原文按 EN / 中文 / ES 三语并列展示（设计如此，非缺陷）",
}
# 历史 release notes 缺口已知清单（补齐后请从本表移除；最新版永远不在此表）
RELEASE_BACKLOG_OK: set[str] = set()

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")
LATIN_RE = re.compile(r"[A-Za-z]")
TAG_OPEN_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)((?:\s[^<>]*)?)>")
TEXT_NODE_RE = re.compile(r">([^<>]{1,300})<")
I18N_ATTR_RE = re.compile(r"data-i18n")
# 语言标签（(EN) / (ES) / (中文)）：四语界面都显示同一个，不需要翻译
LANG_LABEL_RE = re.compile(r"^\(?(EN|ES|ZH|中文|繁體中文|简体中文|繁體|简体)\)?$")
DATA_I18N_RE = re.compile(r"data-i18n(?:-html|-title|-meta|-attr|-aria|-ph)?=\"([A-Za-z0-9_.\-]+)\"")
CODE_MARKERS = ("\\b", "\\r", "\\n", "var ", "function(", "=>", "return ", "document.",
                "querySelector", "localStorage", "window.", "replace(", "':", "';")
PLACEHOLDER_RES = (re.compile(r"@@[A-Za-z0-9_]+@@"), re.compile(r"\{[a-z][a-z0-9_]*\}"))


# ── 结果收集 ────────────────────────────────────────────────────────────────
@dataclass
class Findings:
    """按级别收集问题；list 里保留可直接写进报告/JSON 的明细。"""

    fail: list[dict] = field(default_factory=list)
    warn: list[dict] = field(default_factory=list)
    info: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, level: str, rule: str, detail: str, **extra) -> None:
        row = {"rule": rule, "detail": detail, **extra}
        {"FAIL": self.fail, "WARN": self.warn, "INFO": self.info}[level].append(row)

    @property
    def ok(self) -> bool:
        return not self.fail


# ── 1. 解析 site/build.py 的字典常量（AST，不 import）──────────────────────────
def _module_namespace(tree: ast.Module) -> dict[str, object]:
    """模块级简单常量（REPORT_REPO / SITE_URL 等），供 f-string 求值用。"""
    ns: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            try:
                ns[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                continue
    return ns


def _eval_text(node: ast.AST, ns: dict[str, object]) -> str | None:
    """把常量 / f-string 求值成文本；解析不了的表达式用 \\x00 占位。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                if isinstance(part.value, ast.Name) and part.value.id in ns:
                    out.append(str(ns[part.value.id]))
                    continue
                # 嵌套 f-string / 常量表达式：能求值就拼进来，否则占位
                inner = _eval_text(part.value, ns)
                out.append(inner if inner is not None else "\x00")
            else:
                out.append("\x00")
        return "".join(out)
    return None


def _eval_dict(node: ast.AST, ns: dict[str, object]) -> dict[str, dict[str, str]] | None:
    """i18n 字典 {lang: {key: text}}；值里有 f-string 时用 _eval_text 兜底。"""
    if not isinstance(node, ast.Dict):
        return None
    out: dict[str, dict[str, str]] = {}
    for k_node, v_node in zip(node.keys, node.values):
        if not (isinstance(k_node, ast.Constant) and isinstance(k_node.value, str)):
            return None
        if not isinstance(v_node, ast.Dict):
            return None
        table: dict[str, str] = {}
        for k2, v2 in zip(v_node.keys, v_node.values):
            if not (isinstance(k2, ast.Constant) and isinstance(k2.value, str)):
                return None
            text = _eval_text(v2, ns)
            if text is None:
                try:
                    text = str(ast.literal_eval(v2))
                except (ValueError, TypeError, SyntaxError):
                    return None
            table[k2.value] = text
        out[k_node.value] = table
    return out


def load_build_i18n(path: Path = BUILD_PY) -> tuple[dict[str, dict[str, dict[str, str]]],
                                                    dict[str, int], ast.Module, str]:
    """返回 ({字典名: {lang: {key: text}}}, {字典名: 行号}, AST, 源码)。"""
    src = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    ns = _module_namespace(tree)
    dicts: dict[str, dict[str, dict[str, str]]] = {}
    lines: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id.endswith("_I18N")) \
                    and not (isinstance(target, ast.Name) and target.id == "I18N"):
                continue
            parsed = _eval_dict(node.value, ns)
            lines[target.id] = node.lineno
            if parsed is not None:
                dicts[target.id] = parsed
    return dicts, lines, tree, src


# ── 2. 合并成 i18n.js 实际下发的字典（复刻 build.py 的装载顺序）────────────────
def effective_i18n(dicts: dict[str, dict[str, dict[str, str]]],
                   zh_hant: dict[str, str]) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """复刻 build.py：I18N 打底 → 各字典按声明顺序覆盖 → zh-Hant 用 json + build.py 覆盖。

    返回 ({lang: {key: text}}, {lang: [靠回落拿到的 key]})。
    """
    eff: dict[str, dict[str, str]] = {lang: {} for lang in LANGS}
    for lang in BASE_LANGS:
        eff[lang].update(dicts.get("I18N", {}).get(lang) or {})
    for name in I18N_MERGED:
        for lang in BASE_LANGS:
            eff[lang].update((dicts.get(name) or {}).get(lang) or {})
    fallback: dict[str, list[str]] = {lang: [] for lang in LANGS}
    # zh-Hant：先简体兜底，再 json 覆盖，再 build.py 的 zh-Hant 字典覆盖
    hant: dict[str, str] = {}
    for key, text in eff["zh"].items():
        hant[key] = text
        fallback["zh-Hant"].append(key)
    for key, text in zh_hant.items():
        hant[key] = text
        if key in fallback["zh-Hant"]:
            fallback["zh-Hant"].remove(key)
    for name in I18N_MERGED:
        for key, text in ((dicts.get(name) or {}).get("zh-Hant") or {}).items():
            hant[key] = text
            if key in fallback["zh-Hant"]:
                fallback["zh-Hant"].remove(key)
    eff["zh-Hant"] = hant
    # en/es/zh 缺 key 时 i18n.js 回落英文，这里记下来
    for lang in ("es", "zh"):
        fallback[lang] = [k for k in eff["en"] if k not in eff[lang]]
    fallback["en"] = []
    return eff, fallback


# ── 3. 逐字典键集 / 伪翻译 ──────────────────────────────────────────────────
def _simplified_like_chars(eff: dict[str, dict[str, str]]) -> set[str]:
    """「只在简体文本里出现、繁体文本里从不出现」的字。

    比「繁→简字表的简体值 − 繁体键」更可靠：糊/同/面/搜 这类字既是简体也是繁体，
    只在另一套字形不同（药/藥、场/場、设/設）时才该判定为「没转换」。
    """
    zh_chars = {c for v in eff["zh"].values() for c in v if CJK_RE.match(c)}
    hant_chars = {c for v in eff["zh-Hant"].values() for c in v if CJK_RE.match(c)}
    return zh_chars - hant_chars


def _pseudo_verdict(dict_name: str, lang: str, key: str, value: str,
                    glossary_terms: set[str]) -> tuple[str, str]:
    """判定「值与 en 相同」属于 OK / SUSPECT / FAIL。返回 (级别, 原因)。"""
    if dict_name == "NAME_LANG_I18N":
        return "INFO", "角标按「该名字自身的语言」写（v0.9.4 设计，不翻译不音译）"
    stripped = value.strip()
    if not stripped:
        return "FAIL", "空值"
    if key in PSEUDO_OK_KEYS:
        return "INFO", PSEUDO_OK_KEYS[key]
    if key in PSEUDO_SUSPECT_KEYS:
        return "WARN", PSEUDO_SUSPECT_KEYS[key]
    if not LATIN_RE.search(stripped):
        return "INFO", "纯符号 / 数字，无需翻译"
    if stripped in UNITS:
        return "INFO", "计量单位符号"
    if stripped.lower() in glossary_terms:
        return "INFO", "术语表里的专有名词 / 缩写"
    if ACRONYM_RE.match(stripped):
        return "WARN", "全大写缩写，确认是否专有名词"
    if lang in ("zh", "zh-Hant") and not CJK_RE.search(stripped):
        return "FAIL", "中文值是英文（真缺译）"
    return "FAIL", "与英文完全相同（未翻译）"


def check_dicts(dicts, lines, eff, fallback, zh_hant, glossary_terms, out: Findings) -> None:
    """① 每个字典的四语键集 ② 合并后缺键 ③ 伪翻译 ④ 陈旧 key。"""
    # ① 字典在不在、能不能解析
    for name in I18N_DICTS:
        if name not in dicts:
            out.add("FAIL", "dict-missing", f"{name} 解析失败或不存在（build.py 里名字/结构变了？）",
                    dict=name, line=lines.get(name))
    shapes: list[dict] = []
    for name in I18N_DICTS:
        table = dicts.get(name) or {}
        langs = [lang for lang in LANGS if lang in table]
        row = {"dict": name, "line": lines.get(name), "langs": langs,
               "counts": {lang: len(table[lang]) for lang in langs}}
        shapes.append(row)
        en = set(table.get("en") or {})
        if not en:
            out.add("FAIL", "dict-no-en", f"{name} 没有 en 字典（英文是兜底基准）", dict=name)
            continue
        for lang in LANGS:
            if lang == "en":
                continue
            if lang not in table:
                if not (lang == "zh-Hant" and name in ZH_HANT_FROM_JSON):
                    out.add("FAIL", "dict-no-lang",
                            f"{name} 没有 {lang}（该字典不写 zh-Hant 时必须确认 zh-Hant 走 json）",
                            dict=name, lang=lang)
                continue
            missing = sorted(en - set(table[lang]))
            # 「多出来的 key」只有在合并后的 en 里也找不到才算陈旧；
            # 基础字典（I18N）里的 key 在别的字典重复定义是正常写法
            extra = sorted(k for k in set(table[lang]) - en if k not in eff["en"])
            row[f"missing_{lang}"] = missing
            row[f"extra_{lang}"] = extra
            if missing:
                out.add("FAIL", "dict-key-missing",
                        f"{name} 的 {lang} 缺 {len(missing)} 个 key", dict=name, lang=lang,
                        keys=missing)
            if extra:
                out.add("WARN", "dict-key-extra",
                        f"{name} 的 {lang} 多出 {len(extra)} 个字典里不存在的 key（陈旧 / 拼错）",
                        dict=name, lang=lang, keys=extra)
    out.stats["dicts"] = shapes

    # ② 合并后的有效字典：谁缺 key（i18n.js 会静默回落英文）
    for lang in ("es", "zh", "zh-Hant"):
        missing = sorted(fallback.get(lang) or [])
        if missing:
            out.add("FAIL", "eff-key-missing",
                    f"合并后 {lang} 缺 {len(missing)} 个 key（运行时会静默回落 "
                    f"{'简体 zh' if lang == 'zh-Hant' else '英文'}）",
                    lang=lang, keys=missing)
    for lang in LANGS:
        out.stats[f"eff_{lang}"] = len(eff[lang])

    # ③ 伪翻译：值 == en 值（先按字典判，再对合并后的字典补一遍）
    same_rows: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    for name in I18N_DICTS:
        table = dicts.get(name) or {}
        en = table.get("en") or {}
        for lang in ("es", "zh", "zh-Hant"):
            for key, text in (table.get(lang) or {}).items():
                en_text = en.get(key)
                if not en_text or text != en_text or not text.strip():
                    continue
                level, reason = _pseudo_verdict(name, lang, key, text, glossary_terms)
                same_rows.append({"dict": name, "lang": lang, "key": key,
                                  "value": text, "level": level, "reason": reason})
                seen_pairs.add((lang, key))
    for lang in ("es", "zh", "zh-Hant"):
        for key, text in (eff.get(lang) or {}).items():
            if (lang, key) in seen_pairs:
                continue
            en_text = eff["en"].get(key)
            if en_text and text == en_text and text.strip():
                level, reason = _pseudo_verdict("(merged)", lang, key, text, glossary_terms)
                same_rows.append({"dict": "(merged)", "lang": lang, "key": key,
                                  "value": text, "level": level, "reason": reason})
    out.stats["pseudo_same"] = len(same_rows)
    out.stats["pseudo_by_lang"] = dict(Counter(r["lang"] for r in same_rows))
    out.stats["pseudo_by_level"] = dict(Counter(r["level"] for r in same_rows))
    for row in same_rows:
        if row["level"] == "FAIL":
            out.add("FAIL", "pseudo-translation",
                    f"[{row['lang']}] {row['key']} 与英文完全相同：{row['value'][:60]!r}"
                    f"（{row['reason']}）", **{k: row[k] for k in ("dict", "lang", "key", "value")})
        elif row["level"] == "WARN":
            out.add("WARN", "pseudo-suspect",
                    f"[{row['lang']}] {row['key']} 命中白名单但可疑：{row['value'][:60]!r}"
                    f"（{row['reason']}）", **{k: row[k] for k in ("dict", "lang", "key", "value")})
    out.stats["pseudo_rows"] = same_rows

    # ④ zh-Hant json：陈旧 key / 简体未转换
    base_zh = set(eff["zh"])
    stale = sorted(set(zh_hant) - base_zh)
    if stale:
        out.add("WARN", "zh-hant-stale",
                f"data/i18n_zh_hant.json 里 {len(stale)} 个 key 在 base 里已不存在（陈旧）",
                keys=stale)
    simp_like = _simplified_like_chars(eff)
    untranslated: list[dict] = []
    for key, text in zh_hant.items():
        zh_text = eff["zh"].get(key)
        if zh_text is None or text != zh_text:
            continue
        # 繁体覆盖值和简体一模一样：含「只在简体文本里出现」的字才算没转换
        bad = sorted({c for c in text if c in simp_like})
        if bad:
            untranslated.append({"key": key, "chars": "".join(bad), "value": text[:80]})
    if untranslated:
        out.add("FAIL", "zh-hant-untranslated",
                f"{len(untranslated)} 个 key 的繁体值与简体完全相同且含简体专用字（等于没转换）",
                keys=[r["key"] for r in untranslated])
    out.stats["zh_hant"] = {"keys": len(zh_hant), "stale": len(stale),
                            "untranslated": len(untranslated),
                            "covered": len(set(zh_hant) & base_zh),
                            "untranslated_rows": untranslated}


# ── 4. 标签术语一致性（LABEL_I18N vs data/label_translations.csv）───────────
def _load_label_terms() -> dict[tuple[str, str], dict[str, str]]:
    """读剂型/释放机制/单位的四语术语表：{(category, code): {en,es,zh,zh-Hant}}。"""
    out: dict[tuple[str, str], dict[str, str]] = {}
    try:
        with LABEL_CSV.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                cat = (row.get("category") or "").strip()
                code = (row.get("code") or "").strip()
                if not cat or not code:
                    continue
                out[(cat, code)] = {
                    "en": (row.get("en") or "").strip(),
                    "es": (row.get("es") or "").strip(),
                    "zh": (row.get("zh") or "").strip(),
                    "zh-Hant": (row.get("zh_hant") or "").strip(),
                }
    except OSError:
        return {}
    return out


def check_label_terms(dicts, out: Findings) -> None:
    """LABEL_I18N 的译名必须跟术语表一致：剂型/释放机制对不上算 FAIL，单位缩写算已登记。"""
    terms = _load_label_terms()
    label = dicts.get("LABEL_I18N") or {}
    if not terms or not label:
        return
    rows: list[dict] = []
    for lang in ("es", "zh", "zh-Hant"):
        for key, value in (label.get(lang) or {}).items():
            cat, _, code = key.partition(".")
            term = terms.get((cat, code))
            if not term or not term.get(lang):
                continue
            if term[lang].strip() == value.strip():
                continue
            rows.append({"key": key, "lang": lang, "build": value, "table": term[lang],
                         "category": cat})
    out.stats["label_terms"] = {"checked": sum(len(label.get(lang) or {})
                                              for lang in ("es", "zh", "zh-Hant")),
                               "mismatch": len(rows), "rows": rows}
    for row in rows:
        level = "INFO" if row["key"] in LABEL_TERM_OK else (
            "FAIL" if row["category"] == "form" else "WARN")
        detail = (f"[{row['lang']}] LABEL_I18N.{row['key']} = {row['build']!r}，"
                  f"术语表（data/label_translations.csv）为 {row['table']!r}")
        if level == "INFO":
            out.add("INFO", "label-term-ok", detail + f"（已登记：{LABEL_TERM_OK[row['key']]}）",
                    **{k: row[k] for k in ("key", "lang")})
        else:
            out.add(level, "label-term-mismatch", detail + " —— 译名不一致（视为该语言滞后）",
                    **{k: row[k] for k in ("key", "lang")})



# ── 5. 模板引用的 key 是否存在 ───────────────────────────────────────────────
def check_template_refs(src: str, eff: dict[str, dict[str, str]], out: Findings) -> None:
    refs = set(DATA_I18N_RE.findall(src))
    missing = sorted(r for r in refs if r not in eff["en"])
    out.stats["template_refs"] = len(refs)
    if missing:
        out.add("FAIL", "template-ref-missing",
                f"{len(missing)} 个 data-i18n key 在字典里不存在（页面会渲染空白）", keys=missing)
    # 服务端直接取值 I18N["xx"]["k"]：key 不存在会 KeyError / 空
    direct: set[tuple[str, str]] = set()
    for m in re.finditer(r"I18N\[\"(en|es|zh|zh-Hant)\"\]\[\"([^\"]+)\"\]", src):
        direct.add((m.group(1), m.group(2)))
    bad_direct = sorted({f"{lang}:{key}" for lang, key in direct if key not in eff[lang]})
    if bad_direct:
        out.add("FAIL", "template-direct-missing",
                f"{len(bad_direct)} 处直接取字典的 key 不存在", keys=bad_direct)
    out.stats["template_direct_refs"] = len(direct)


# ── 5. release notes（What's new）四语完整性 ────────────────────────────────
def parse_changelog(path: Path = CHANGELOG) -> list[dict]:
    """解析 CHANGELOG 的版本节：版本号、日期、条目文本。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    sections: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = re.match(r"^## (v[0-9][^\s]*)\s*[—–-]\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            cur = {"version": m.group(1), "date": m.group(2), "items": []}
            sections.append(cur)
            continue
        if cur is not None:
            if line.startswith("## "):
                cur = None
            elif re.match(r"^\s*-\s+\S", line):
                cur["items"].append(line.strip())
            elif line.startswith("### "):
                continue
    return sections


def check_release_notes(sections: list[dict], out: Findings,
                        path: Path = RELEASE_JSON) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out.add("FAIL", "release-json", f"读不到 {path.name}：{exc}")
        data = {}
    versions = {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}
    rows: list[dict] = []
    if not sections:
        out.add("FAIL", "changelog", "CHANGELOG.md 解析不到版本节")
        return
    latest = sections[0]
    missing_versions: list[dict] = []
    missing_items = 0
    incomplete_versions: list[dict] = []
    for idx, sec in enumerate(sections):
        ver, items = sec["version"], sec["items"]
        block = versions.get(ver)
        row = {"version": ver, "date": sec["date"], "changelog_items": len(items),
               "in_json": block is not None, "langs": {}, "ok": False}
        rows.append(row)
        if not block:
            missing_versions.append({"version": ver, "items": len(items)})
            missing_items += len(items)
            if idx == 0:
                out.add("FAIL", "release-latest-missing",
                        f"最新版 {ver}（{sec['date']}）在 {path.name} 里没有译文："
                        f"en/es 用户看到的是中文原文 + 「译文待补」", version=ver)
            continue
        bad: list[str] = []
        for lang in LANGS:
            vals = block.get(lang)
            n = len(vals) if isinstance(vals, list) else 0
            row["langs"][lang] = n
            if not n:
                bad.append(lang)
            elif n != len(items):
                bad.append(f"{lang}(条数 {n}≠{len(items)})")
        row["ok"] = not bad
        if bad:
            if idx == 0:
                out.add("FAIL", "release-latest-incomplete",
                        f"最新版 {ver} 四语不齐：缺 {', '.join(bad)}", version=ver, missing=bad)
            elif ver not in RELEASE_BACKLOG_OK:
                incomplete_versions.append({"version": ver, "missing": bad,
                                            "items": len(items)})
    # 历史版本积压：聚合成一条 WARN（逐版明细在 JSON 里），否则一次刷出几十条噪声
    backlog = [v for v in missing_versions if v["version"] not in RELEASE_BACKLOG_OK
               and v["version"] != latest["version"]]
    if backlog:
        span = f"{backlog[-1]['version']}→{backlog[0]['version']}" if len(backlog) > 1 \
            else backlog[0]["version"]
        out.add("WARN", "release-backlog",
                f"{len(backlog)} 个历史版本没有译文（{span}，共 {missing_items} 条）："
                f"What's new 上这些版本只有中文原文",
                versions=[v["version"] for v in backlog], items=missing_items)
    if incomplete_versions:
        detail = "；".join(f"{v['version']} 缺 {', '.join(v['missing'])}（{v['items']} 条）"
                          for v in incomplete_versions[:6])
        out.add("WARN", "release-backlog-incomplete",
                f"{len(incomplete_versions)} 个版本有译文但四语不齐：{detail}"
                + ("…" if len(incomplete_versions) > 6 else ""),
                versions=[v["version"] for v in incomplete_versions])
    stale = sorted(set(versions) - {s["version"] for s in sections})
    if stale:
        out.add("WARN", "release-stale",
                f"{path.name} 里 {len(stale)} 个版本 CHANGELOG 已没有（陈旧）", keys=stale)
    meta = data.get("_meta") or {}
    if isinstance(meta, dict) and meta.get("versions") not in (None, len(versions)):
        out.add("WARN", "release-meta",
                f"_meta.versions={meta.get('versions')} 与实际 {len(versions)} 个版本不符")
    out.stats["release"] = {
        "changelog_versions": len(sections), "json_versions": len(versions),
        "latest": latest["version"], "latest_ok": bool(rows and rows[0]["ok"]),
        "latest_items": len(latest["items"]),
        "missing_versions": [v["version"] for v in missing_versions],
        "missing_items": missing_items,
        "incomplete_versions": incomplete_versions,
        "rows": rows,
    }


# ── 6. 硬编码文案（HTML 模板里直接写、没走 data-i18n）──────────────────────────
def _enclosing_functions(tree: ast.AST) -> tuple[dict[int, str], dict[int, ast.AST]]:
    """(id(节点) → 所在函数名) 与 (id(节点) → 父节点)，用来给硬编码行标注位置。"""
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node
    names: dict[int, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        cur = node
        while id(cur) in parent:
            cur = parent[id(cur)]
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names[id(node)] = cur.name
                break
    return names, parent


def _looks_like_code(frag: str) -> bool:
    """片段像代码 / 正则而不是给用户看的文案。"""
    if re.search(r"\(\?|\\[A-Za-z]|\]\+|\)\*|\\s|\|", frag):
        return True
    return any(ch in frag for ch in ("{", "}", "\x00"))


def check_hardcoded(tree: ast.Module, out: Findings) -> None:
    """扫 HTML 模板里的裸文案：有标签、没有 data-i18n、文案不是来自字典。"""
    ns = _module_namespace(tree)
    dict_spans: list[tuple[int, int]] = []
    code_spans: list[tuple[int, int]] = []
    big_consts: list[tuple[int, int, str, str]] = []
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            span = (node.lineno, node.end_lineno or node.lineno)
            if target.id.endswith("_I18N") or target.id == "I18N":
                dict_spans.append(span)
            text = _eval_text(node.value, ns)
            if not isinstance(text, str):
                continue
            if target.id.endswith("_JS") or target.id in {"CSS", "APP_JS"}:
                code_spans.append(span)
            elif len(text) > 1500:
                big_consts.append((span[0], span[1], target.id, text))

    fnames, parent = _enclosing_functions(tree)
    hits: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        if isinstance(node, ast.Constant):
            if id(node) in docstrings:
                continue
            # f-string 的片段单独求值会丢上下文（标签被切断 → 误判成没有 data-i18n），
            # 只处理最外层的 JoinedStr
            if isinstance(parent.get(id(node)), ast.JoinedStr):
                continue
        lineno = node.lineno
        if any(a <= lineno <= b for a, b in dict_spans + code_spans):
            continue
        if any(a <= lineno <= b for a, b, _n, _t in big_consts):
            continue
        text = _eval_text(node, ns)
        if not text or "<" not in text or ">" not in text:
            continue
        if any(marker in text for marker in CODE_MARKERS):
            continue
        for m in TEXT_NODE_RE.finditer(text):
            frag = m.group(1).strip()
            if not frag or len(frag) < 3 or not LATIN_RE.search(frag):
                continue
            if _looks_like_code(frag):
                continue
            opens = list(TAG_OPEN_RE.finditer(text[: m.start() + 1]))
            if opens:
                tag = opens[-1]
                if I18N_ATTR_RE.search(tag.group(0)):
                    continue
                if tag.group(1).lower() in {"script", "style", "meta", "link"}:
                    continue
            if (lineno, frag) in seen:
                continue
            seen.add((lineno, frag))
            has_cjk = bool(CJK_RE.search(frag))
            has_latin = bool(LATIN_RE.search(frag))
            impact = "mixed" if (has_cjk and has_latin) else ("zh" if has_cjk else "latin")
            hits.append({"line": lineno, "text": frag, "impact": impact,
                         "function": fnames.get(id(node), "?")})

    # 大型常量（>1500 字符）：不逐条列，单独记一条
    for start, end, name, text in big_consts:
        if name in HARDCODED_INFO_CONSTS:
            out.add("INFO", "hardcoded-info",
                    f"{name}（L{start}-{end}，{len(text)} 字符）：{HARDCODED_INFO_CONSTS[name]}",
                    line=start, const=name)
            continue
        sub = [h for h in hits if start <= h["line"] <= end]
        if not sub:
            continue
        out.add("WARN", "hardcoded-big",
                f"{name}（L{start}-{end}，{len(text)} 字符）里有 {len(sub)} 处裸文案"
                f"（{'含中文' if CJK_RE.search(text) else '纯外文'}）",
                line=start, const=name)

    for h in hits:
        if h["text"] in HARDCODED_INFO_TEXTS:
            out.add("INFO", "hardcoded-info",
                    f"L{h['line']} {h['text']!r}：{HARDCODED_INFO_TEXTS[h['text']]}",
                    line=h["line"], text=h["text"])
            continue
        if LANG_LABEL_RE.match(h["text"]):
            out.add("INFO", "hardcoded-info",
                    f"L{h['line']} {h['text']!r}：语言标签（四语都显示同一个，不需要翻译）",
                    line=h["line"], text=h["text"])
            continue
        impact_text = {"mixed": "中英混排（四语用户都看到同一串）",
                       "zh": "只有中文（en/es 用户看到中文）",
                       "latin": "英文（zh/zh-Hant 用户看到英文）"}[h["impact"]]
        out.add("WARN", "hardcoded",
                f"L{h['line']}（{h['function']}）{h['text'][:70]!r} —— {impact_text}",
                **{k: h[k] for k in ("line", "text", "impact", "function")})
    real = [h for h in hits if h["text"] not in HARDCODED_INFO_TEXTS
            and not LANG_LABEL_RE.match(h["text"])]
    out.stats["hardcoded"] = {
        "count": len(real),
        "by_impact": dict(Counter(h["impact"] for h in real)),
        "big_consts": [{"line": a, "end": b, "const": n, "chars": len(t)}
                       for a, b, n, t in big_consts],
        "rows": hits,
    }


# ── 7. 自检：证明门禁真的会红（--self-test，不依赖真实仓库数据）────────────────
def self_test() -> int:
    """用合成样例跑一遍规则，确认「该红的红、该绿的绿」。返回失败条数。"""
    bad = 0

    def expect(cond: bool, what: str) -> None:
        nonlocal bad
        print(("  ok   " if cond else "  FAIL ") + what)
        if not cond:
            bad += 1

    # ① 键集：es 缺 key → FAIL；zh-Hant 缺 key 且不在 json → FAIL
    dicts = {
        "I18N": {"en": {"a": "A", "b": "B"}, "es": {"a": "A"}, "zh": {"a": "甲", "b": "乙"}},
        "LABEL_I18N": {"en": {"c": "C"}, "es": {"c": "C"}, "zh": {"c": "丙"},
                       "zh-Hant": {"c": "丙"}},
    }
    eff, fallback = effective_i18n(dicts, {"a": "甲_"})
    out = Findings()
    check_dicts(dicts, {"I18N": 1, "LABEL_I18N": 2}, eff, fallback,
                {"a": "甲_"}, {"inn"}, out)
    rules = {r["rule"] for r in out.fail}
    expect("dict-key-missing" in rules, "es 缺 key 会被判 FAIL（dict-key-missing）")
    expect("eff-key-missing" in rules, "合并后缺 key 会被判 FAIL（eff-key-missing）")
    expect("b" in (fallback["es"] + fallback["zh"]), "缺 key 出现在回落清单里")

    # ② 伪翻译：es 值 == en 值 → FAIL；专有名词 / 单位 / NAME_LANG 角标 → 放行
    expect(_pseudo_verdict("I18N", "es", "x.y", "Same English sentence", set())[0] == "FAIL",
           "es 与 en 同值的英文句子 → FAIL")
    expect(_pseudo_verdict("I18N", "zh", "x.y", "Same English sentence", set())[0] == "FAIL",
           "zh 值是英文句子 → FAIL")
    expect(_pseudo_verdict("LABEL_I18N", "es", "unit.mcg", "mcg", set())[0] == "INFO",
           "单位符号 mcg 同形 → 放行")
    expect(_pseudo_verdict("GLOSSARY_I18N", "es", "glossary.t.inn", "INN", {"inn"})[0] == "INFO",
           "术语表里的缩写 INN → 放行")
    expect(_pseudo_verdict("NAME_LANG_I18N", "zh", "name.no_en",
                           "No English name recorded", set())[0] == "INFO",
           "NAME_LANG_I18N 角标 → 放行")

    # ③ zh-Hant 未转换：繁体值与简体同值且含简体专用字 → FAIL
    eff2 = {"zh": {"j": "这个药品", "k": "同成分的商品"},
            "zh-Hant": {"j": "其他", "k": "同成分的商品"}}
    simp_like = _simplified_like_chars(eff2)
    expect(bool(simp_like & set("这个药品")), "能识别「只在简体里出现」的字")
    expect(not (simp_like & set("同成分的商品")), "繁简同形字（同 / 成分 / 商品）不算未转换")

    # ④ 标签术语：和 data/label_translations.csv 对不上 → FAIL（单位缩写类已登记，不报）
    terms = _load_label_terms()
    expect(bool(terms), f"读到术语表 {len(terms)} 条")
    out_t = Findings()
    check_label_terms({"LABEL_I18N": {"es": {"form.tablet": "comprimido",
                                             "form.pellet": "gránulo",
                                             "unit.mcg": "mcg"}}}, out_t)
    expect(any(r["rule"] == "label-term-mismatch" and r["key"] == "form.pellet"
               for r in out_t.fail), "剂型译名与术语表不符 → FAIL")
    expect(not any(r["key"] == "form.tablet" for r in out_t.fail),
           "与术语表一致的剂型不报")

    # ⑤ 模板引用：data-i18n 指向不存在的 key → FAIL
    out2 = Findings()
    check_template_refs('<p data-i18n="a">x</p><p data-i18n="nope">y</p>',
                        {"en": {"a": "A"}, "es": {}, "zh": {}, "zh-Hant": {}}, out2)
    expect(any(r["rule"] == "template-ref-missing" for r in out2.fail),
           "data-i18n 指向不存在的 key → FAIL")

    # ⑤ release notes：最新版缺译文 → FAIL
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td) / "CHANGELOG.md"
        ch.write_text("## v9.9.9 — 2026-01-01\n\n- 一条\n- 两条\n", encoding="utf-8")
        js = Path(td) / "release.json"
        js.write_text(json.dumps({"v9.9.9": {"zh": ["甲"], "en": ["a"], "es": ["b"],
                                             "zh-Hant": ["丙"]}}), encoding="utf-8")
        out3 = Findings()
        check_release_notes(parse_changelog(ch), out3, js)
        expect(any(r["rule"] == "release-latest-incomplete" for r in out3.fail),
               "最新版条目数不符 → FAIL")
        js.write_text(json.dumps({"v9.9.9": {"zh": ["甲", "乙"], "en": ["a", "b"],
                                             "es": ["c", "d"], "zh-Hant": ["丙", "丁"]}}),
                      encoding="utf-8")
        out4 = Findings()
        check_release_notes(parse_changelog(ch), out4, js)
        expect(not out4.fail, "四语齐 + 条数对 → 不报 FAIL")

    # ⑥ 硬编码：裸文案被抓、带 data-i18n 的不抓
    src = ('X = """<p class="a">Hello user</p>'
           '<p data-i18n="k">Hello user</p>"""\n')
    out5 = Findings()
    check_hardcoded(ast.parse(src), out5)
    hits = [r for r in out5.warn if r["rule"] == "hardcoded"]
    expect(len(hits) == 1, f"只抓没有 data-i18n 的那一处（实际 {len(hits)}）")

    print(f"\nself-test: {'全部通过' if not bad else f'{bad} 项失败'}")
    return bad


# ── 8. 汇总输出 ─────────────────────────────────────────────────────────────
def _glossary_terms() -> set[str]:
    """术语表里的英文术语（专有名词 / 缩写），用来放行「同形」判定。"""
    terms: set[str] = set()
    try:
        with GLOSSARY_CSV.open(encoding="utf-8-sig") as fh:
            head = fh.readline()
            idx = head.split(",").index("term_en") if "term_en" in head else -1
            if idx < 0:
                return terms
            for line in fh:
                parts = line.split(",")
                if len(parts) > idx and parts[idx].strip():
                    terms.add(parts[idx].strip().lower())
    except (OSError, ValueError):
        pass
    return terms


def run(args: argparse.Namespace) -> tuple[Findings, dict]:
    out = Findings()
    build_py: Path = getattr(args, "build_py", None) or BUILD_PY
    try:
        dicts, lines, tree, src = load_build_i18n(build_py)
    except (OSError, SyntaxError) as exc:
        out.add("FAIL", "build-py", f"读不到 {build_py}：{exc}")
        return out, {"ok": False, "counts": {"fail": 1, "warn": 0, "info": 0},
                     "stats": {}, "fail": out.fail, "warn": [], "info": []}
    try:
        zh_hant_all = json.loads(ZH_HANT_JSON.read_text(encoding="utf-8"))
        zh_hant = zh_hant_all.get("zh-Hant") or {}
    except (OSError, ValueError):
        zh_hant = {}
        out.add("FAIL", "zh-hant-json", "读不到 data/i18n_zh_hant.json")
    eff, fallback = effective_i18n(dicts, zh_hant)
    check_dicts(dicts, lines, eff, fallback, zh_hant, _glossary_terms(), out)
    check_label_terms(dicts, out)
    check_template_refs(src, eff, out)
    sections = parse_changelog()
    check_release_notes(sections, out)
    check_hardcoded(tree, out)
    out.add("INFO", "server-only-dicts",
            f"{len(I18N_SERVER_ONLY)} 个字典只在服务端用、不合并进 i18n.js："
            f"{', '.join(I18N_SERVER_ONLY)}（仍按四语键集检查，故合并后键数少于逐字典之和）")
    out.stats["langs"] = list(LANGS)
    out.stats["build_py"] = str(build_py)
    payload = {
        "ok": out.ok,
        "counts": {"fail": len(out.fail), "warn": len(out.warn), "info": len(out.info)},
        "stats": out.stats,
        "fail": out.fail,
        "warn": out.warn,
        "info": out.info,
    }
    return out, payload


def _print_summary(out: Findings, args: argparse.Namespace) -> None:
    st = out.stats
    print("== i18n 一致性门禁（四语 en / es / zh / zh-Hant）==")
    print(f"build.py: {st.get('build_py')}  有效字典: "
          + " / ".join(f"{lang} {st.get(f'eff_{lang}', 0)} 键" for lang in LANGS))
    rel = st.get("release") or {}
    print(f"release notes: CHANGELOG {rel.get('changelog_versions', 0)} 版 / json "
          f"{rel.get('json_versions', 0)} 版，最新 {rel.get('latest', '?')} "
          f"{'四语齐' if rel.get('latest_ok') else '不齐/缺'}；缺 {len(rel.get('missing_versions') or [])} 版"
          f"（{rel.get('missing_items', 0)} 条待译）")
    hard = st.get("hardcoded") or {}
    print(f"硬编码文案: {hard.get('count', 0)} 处 {hard.get('by_impact') or {}}")
    print(f"伪翻译(值==en): {st.get('pseudo_same', 0)} 条 {st.get('pseudo_by_level') or {}}")
    print(f"\nFAIL {len(out.fail)} / WARN {len(out.warn)} / INFO {len(out.info)}")
    for level, rows in (("FAIL", out.fail), ("WARN", out.warn)):
        if not rows:
            continue
        by_rule = Counter(r["rule"] for r in rows)
        print(f"\n-- {level} -- " + ", ".join(f"{k}={v}" for k, v in by_rule.most_common()))
        for row in rows[: args.max_list]:
            print(f"  [{row['rule']}] {row['detail']}")
            keys = row.get("keys") or []
            if keys:
                shown = ", ".join(str(k) for k in keys[: args.max_keys])
                more = "" if len(keys) <= args.max_keys else f" …（共 {len(keys)} 个）"
                print(f"      {shown}{more}")
        if len(rows) > args.max_list:
            print(f"  … 还有 {len(rows) - args.max_list} 条（--json 看全量）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="四语 i18n 一致性门禁（只读、纯静态）")
    ap.add_argument("--json", type=Path, default=None, help="同时写机器可读 JSON 到这个路径")
    ap.add_argument("--strict", dest="strict", action="store_true", default=True,
                    help="有 FAIL 时退出码 1（默认）")
    ap.add_argument("--no-strict", dest="strict", action="store_false", help="只报告，退出码恒 0")
    ap.add_argument("--build-py", type=Path, default=BUILD_PY,
                    help="只检查指定的 build.py（默认 site/build.py；自查 / 变异测试用）")
    ap.add_argument("--max-list", type=int, default=40, help="摘要里每级最多列几条（默认 40）")
    ap.add_argument("--max-keys", type=int, default=12, help="每条清单最多列几个 key（默认 12）")
    ap.add_argument("--quiet", action="store_true", help="只打印汇总行")
    ap.add_argument("--self-test", action="store_true",
                    help="用合成样例验证规则本身（证明门禁会红），不读仓库数据")
    args = ap.parse_args(argv)

    if args.self_test:
        return 1 if self_test() else 0

    out, payload = run(args)
    if not args.quiet:
        _print_summary(out, args)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
        print(f"\nJSON: {args.json}")
    if args.strict and not out.ok:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
