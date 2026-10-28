# -*- coding: utf-8 -*-
"""生成 lib/pinyin.py：把 site/build.py 的拼音字表 + 客户端 token 算法移植进 lib（只读 build.py）。

运行：python tests/gen_pinyin_lib.py
输出：lib/pinyin.py（新文件；不改 build.py）；改字表后重跑本脚本
"""
import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "site" / "build.py").read_text(encoding="utf-8")
m = re.search(r'_PINYIN_CHARS_TEXT\s*=\s*"(.*?)"', src, re.S)
assert m, "build.py 里找不到 _PINYIN_CHARS_TEXT"
table_text = m.group(1)
parts = table_text.split()
print("pinyin chars:", len(parts))

# 多音字候选（仅 lib 使用；客户端保持默认读音不变）。只收录药名里常见的多音字；
# 每个字的候选包含默认读音（若表里有）之外的其他常用读音。
POLY = {
    "重": ["chong"], "长": ["zhang"], "行": ["hang"], "乐": ["yue"],
    "参": ["can"], "柏": ["bo"], "薄": ["bo"], "阿": ["e"],
    "熟": ["shou"], "血": ["xie"], "降": ["xiang"], "调": ["diao"],
    "都": ["du"], "发": ["fa"], "差": ["chai", "ci"], "着": ["zhuo"],
    "和": ["huo"], "率": ["shuai"], "哪": ["nei"], "卡": ["qia"],
    "曾": ["zeng"], "单": ["shan"], "解": ["xie"], "藏": ["zang"],
    "枸": ["ju"], "桔": ["ju"], "便": ["pian"], "石": ["dan"],
    "术": ["zhu"], "大": ["dai"], "地": ["de"], "塞": ["se"],
    "壳": ["qiao"], "给": ["ji"], "曲": ["qu"], "佛": ["fu"],
    "觉": ["jiao"], "侧": ["zhai"], "削": ["xiao"], "舍": ["she"],
    "膏": ["gao"], "散": ["san"], "数": ["shu"], "中": ["zhong"],
    "为": ["wei"], "与": ["yu"], "校": ["jiao"], "艾": ["yi"],
}
wrapped = "\n".join(textwrap.wrap(table_text, 100))
py = f'''# -*- coding: utf-8 -*-
"""拼音归一（lib 层）：移植自站点客户端 `site/build.py` 的 `_pinyin_tokens` 口径。

背景
----
站点客户端的拼音层（`app.js` 的 `pinyinFetch()` / `layerCandidates()`）依赖构建产物
`data/idx/pinyin.json`（token → 索引条目），lib/search.py 之前没有对应能力，导致
CLI/tests/服务端检索无法命中拼音查询（reports/search-eval-v3.md 的 65 例 gap）。

本模块把同一套 **默认读音字表 + token 口径**（s:音节 / j:连写 / i:首字母）移植进 lib，
并在 lib 侧额外提供 **多音字候选**（`POLYPHONE_EXTRA`）——客户端行为不变：
  - 字表来源：`site/build.py::_PINYIN_CHARS_TEXT`（1,582 字，生成时快照，见文件底部），
    `python .tmp/pinyin-lib/gen_pinyin_lib.py` 可重新提取；
  - token 生成与客户端 `_pinyin_tokens()` 完全一致（polyphone=False 时）；
  - 本模块只在 lib/CLI/tests 侧使用，**不进入站点 dist**，不增加页面体积；
  - 客户端仍用构建的 pinyin.json（默认读音），多音字候选是 lib 的超集能力。

许可：字表本身是 pinyin-pro（MIT）生成的读音数据，构建侧已在用；读音/药名属事实数据。
"""
from __future__ import annotations

import re

# 汉字 → 默认拼音（与 site/build.py 的 _PINYIN_CHARS_TEXT 同源）
_PINYIN_CHARS_TEXT = """{wrapped}"""

_PINYIN_DICT: dict[str, str] | None = None
_CJK = re.compile(r"[\\u3400-\\u9fff]")


def pinyin_dict() -> dict[str, str]:
    """字符 → 默认拼音（懒解析，进程内只解析一次）。"""
    global _PINYIN_DICT
    if _PINYIN_DICT is None:
        out: dict[str, str] = {{}}
        for part in _PINYIN_CHARS_TEXT.split():
            ch, _, py = part.partition(":")
            if ch and py:
                out[ch] = py
        _PINYIN_DICT = out
    return _PINYIN_DICT


# 多音字候选（默认读音见 pinyin_dict；这里只列“额外读音”，避免与表重复）
POLYPHONE_EXTRA: dict[str, tuple[str, ...]] = {{
{chr(10).join(f'    {ch!r}: {tuple(vals)!r},' for ch, vals in POLY.items())}
}}


def readings_of(ch: str) -> tuple[str, ...]:
    """单字读音候选：默认读音 + 多音字额外读音（去重、保持顺序）。"""
    default = pinyin_dict().get(ch)
    out = []
    if default:
        out.append(default)
    for extra in POLYPHONE_EXTRA.get(ch, ()):
        if extra not in out:
            out.append(extra)
    return tuple(out)


def _default_syllables(text: str) -> list[str]:
    """客户端口径的字串 → 音节列表：汉字用默认读音，ASCII 字母数字按单字符。"""
    table = pinyin_dict()
    syl: list[str] = []
    for ch in text or "":
        if "\\u3400" <= ch <= "\\u9fff":
            syl.append(table.get(ch, ""))
        elif ch.isascii() and ch.isalnum():
            syl.append(ch.lower())
    return [s for s in syl if s]


def _tokens_of_syllables(syl: list[str]) -> set[str]:
    toks: set[str] = set()
    for s in syl:
        toks.add("s:" + s)
    if len(syl) > 1:
        toks.add("j:" + "".join(syl))
        toks.add("i:" + "".join(x[0] for x in syl))
    return toks


def pinyin_tokens(text: str, polyphone: bool = False, max_variants: int = 8) -> list[str]:
    """汉字串 → token 集合（与客户端同口径）。

    polyphone=True 时额外生成多音字候选（最多 max_variants 个变体）：
      - 对每个多音字位置替换成额外读音，生成对应的 s:/j:/i: token；
      - 变体数量按「额外读音个数」截断，避免组合爆炸。
    默认 polyphone=False，与 app.js 的 _pinyin_tokens 完全一致。
    """
    default_syl = _default_syllables(text)
    toks = _tokens_of_syllables(default_syl)
    if not polyphone or not default_syl:
        return sorted(toks)
    table = pinyin_dict()
    # 逐字构建（与 _default_syllables 同口径：缺读音的汉字跳过），
    # 同时记录多音字位置 → 额外读音，避免下标错位。
    syl_all: list[str] = []
    extra_pos: list[tuple[int, list[str]]] = []
    for ch in text or "":
        if "\\u3400" <= ch <= "\\u9fff":
            p = table.get(ch)
            if not p:
                continue
            pos = len(syl_all)
            syl_all.append(p)
            alts = [x for x in POLYPHONE_EXTRA.get(ch, ()) if x and x != p]
            if alts:
                extra_pos.append((pos, alts))
        elif ch.isascii() and ch.isalnum():
            syl_all.append(ch.lower())
    variants = 0
    for pos, alts in extra_pos:
        for alt in alts:
            if variants >= max_variants:
                break
            syl = list(syl_all)
            syl[pos] = alt
            toks |= _tokens_of_syllables(syl)
            variants += 1
    return sorted(toks)


def compact_query(query: str) -> str:
    """拼音查询归一：小写、只留 ASCII 字母数字（与客户端 compact 口径一致）。"""
    s = (query or "").casefold()
    return "".join(ch for ch in s if ch.isascii() and ch.isalnum())


def query_tokens(query: str) -> list[str]:
    """拼音查询 → 候选 token 列表（顺序 = 客户端查找优先级 j > i > s）。

    客户端（app.js:3123）：
        PY_MAP.get('j:' + nq) || PY_MAP.get('i:' + nq) || PY_MAP.get('s:' + nq)
    """
    q = compact_query(query)
    if not q:
        return []
    if len(q) == 1:
        return ["s:" + q]
    return ["j:" + q, "i:" + q, "s:" + q]


def is_cjk_text(text: str) -> bool:
    return bool(_CJK.search(text or ""))


# 快照来源：site/build.py::_PINYIN_CHARS_TEXT（1,582 字）。
# 重新提取：python .tmp/pinyin-lib/gen_pinyin_lib.py（会与本模块的 pinyin_dict 对比）。
'''
out = ROOT / "lib" / "pinyin.py"
out.write_text(py, encoding="utf-8")
print("written", out, "bytes", len(py.encode()))
