# -*- coding: utf-8 -*-
"""task-111 单测：lib/pinyin.py 与站点客户端 `_pinyin_tokens` 口径一致性。

- 字表与 site/build.py::_PINYIN_CHARS_TEXT 同步（build.py 可读时校验）；
- token 口径（s:/j:/i:）与客户端一致；
- 多音字候选（lib 超集，客户端不变）；
- lib/search.py 的拼音候选：拉丁拼音查询在 name_key 零命中时命中中文 key。
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

import lib.pinyin as pinyin_mod  # noqa: E402
from lib.search import SearchIndex  # noqa: E402


def _client_table() -> dict[str, str] | None:
    build = ROOT / "site" / "build.py"
    if not build.exists():
        return None
    src = build.read_text(encoding="utf-8")
    m = re.search(r'_PINYIN_CHARS_TEXT\s*=\s*"(.*?)"', src, re.S)
    if not m:
        return None
    out = {}
    for part in m.group(1).split():
        ch, _, py = part.partition(":")
        if ch and py:
            out[ch] = py
    return out


class PinyinTableTest(unittest.TestCase):
    def test_table_sync_with_build_py(self) -> None:
        client = _client_table()
        if client is None:
            self.skipTest("site/build.py 不可读（发布环境无构建脚本）")
        ours = pinyin_mod.pinyin_dict()
        self.assertGreater(len(ours), 1500)
        self.assertEqual(len(ours), len(client), "拼音字表与 build.py 不同步")
        # 只抽样比较：完整比较留给 gen 脚本（避免单测输出巨大 diff）
        for ch in list(client)[:200] + list(ours)[:200]:
            self.assertEqual(ours.get(ch), client.get(ch), f"读音不同: {ch}")

    def test_token_parity(self) -> None:
        # 与客户端 _pinyin_tokens 相同口径的样例
        self.assertEqual(set(pinyin_mod.pinyin_tokens("布洛芬")),
                         {"s:bu", "s:luo", "s:fen", "j:buluofen", "i:blf"})
        self.assertEqual(set(pinyin_mod.pinyin_tokens("泰诺")),
                         {"s:tai", "s:nuo", "j:tainuo", "i:tn"})
        # 单字只有 s:
        self.assertEqual(set(pinyin_mod.pinyin_tokens("片")), {"s:pian"})

    def test_query_tokens_priority(self) -> None:
        self.assertEqual(pinyin_mod.query_tokens("buluofen"),
                         ["j:buluofen", "i:buluofen", "s:buluofen"])
        self.assertEqual(pinyin_mod.query_tokens("blf"), ["j:blf", "i:blf", "s:blf"])
        self.assertEqual(pinyin_mod.query_tokens("x"), ["s:x"])

    def test_polyphone_candidates(self) -> None:
        readings = pinyin_mod.readings_of("重")
        self.assertIn("zhong", readings)
        self.assertIn("chong", readings)
        # 用表内两字词验证连写 token 的多音字替换（阿胶：a-jiao / e-jiao）
        toks = pinyin_mod.pinyin_tokens("阿胶", polyphone=True)
        self.assertIn("s:e", toks)
        self.assertIn("j:ejiao", toks)
        # 关闭多音字时与客户端一致（只有默认读音）
        default = pinyin_mod.pinyin_tokens("阿胶")
        self.assertIn("j:ajiao", default)
        self.assertNotIn("j:ejiao", default)

    def test_compact_query(self) -> None:
        self.assertEqual(pinyin_mod.compact_query("Buluo Fen!  "), "buluofen")
        self.assertEqual(pinyin_mod.compact_query("对乙酰氨基酚"), "")


class PinyinSearchTest(unittest.TestCase):
    """lib/search.py 的拼音候选（只读 DB；DB 不存在时跳过）。"""

    @classmethod
    def setUpClass(cls) -> None:
        db = ROOT / "data" / "drugs.db"
        if not db.exists():
            raise unittest.SkipTest("没有 data/drugs.db")
        cls._real_connect = sqlite3.connect

        def ro_connect(database, *a, **kw):
            s = str(database)
            kw.setdefault("timeout", 60)
            if "mode=ro" not in s:
                return cls._real_connect("file:" + s + "?mode=ro", uri=True, *a, **kw)
            return cls._real_connect(database, *a, **kw)

        sqlite3.connect = ro_connect
        cls.idx = SearchIndex(db)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.idx.close()
        sqlite3.connect = cls._real_connect

    def test_pinyin_full(self) -> None:
        res = self.idx.search("buluofen")
        self.assertTrue(res.cards, "buluofen 应该通过拼音层命中布洛芬")
        self.assertEqual(res.cards[0].tier, "pinyin")
        substances = {s.casefold() for c in res.cards for s in c.substances}
        self.assertTrue(any("ibuprofen" in s for s in substances), substances)

    def test_pinyin_initials(self) -> None:
        res = self.idx.search("blf")
        self.assertTrue(res.cards)
        self.assertEqual(res.cards[0].tier, "pinyin")

    def test_pinyin_with_space(self) -> None:
        res = self.idx.search("tai nuo")
        self.assertTrue(res.cards, "tai nuo 应命中泰诺")
        self.assertEqual(res.cards[0].tier, "pinyin")

    def test_pinyin_multi_reading(self) -> None:
        # 多音字候选：默认读音与额外读音都能进入候选池（用「重」类药名验证 token 层，
        # 检索结果取决于库内是否有对应 key；这里只断言 token 索引包含额外读音）
        self.idx._get_pinyin_index()
        self.assertTrue(any(tok.startswith("s:chong") for tok in self.idx._pinyin_index))

    def test_english_unaffected(self) -> None:
        res = self.idx.search("lipitor")
        self.assertTrue(res.cards)
        self.assertEqual(res.cards[0].tier, "exact")
        # 普通英文查询不应出现 pinyin tier
        self.assertTrue(all(c.tier != "pinyin" for c in res.cards))

    def test_no_pinyin_for_short_gibberish(self) -> None:
        # 纯拉丁无意义串不应因拼音层产生卡片（可能被 fuzzy 命中，但不该 pinyin tier）
        res = self.idx.search("qzxwvb")
        self.assertTrue(all(c.tier != "pinyin" for c in res.cards))


if __name__ == "__main__":
    unittest.main()
