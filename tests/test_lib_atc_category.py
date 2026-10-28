# -*- coding: utf-8 -*-
"""task-139 单测：lib 的 ATC 码 / 大类检索（与客户端 v0.6.4 / v0.7.1 对齐）。

- ATC 识别口径与客户端 `atcQuery()` 一致；
- 16 大类四语 label / alias 匹配与客户端 `catHit()` 口径一致；口语别名是 lib 扩展；
- SearchIndex.search 返回 match_source（atc / category）与结果卡；
- 普通名字检索行为不变。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

import categories as cat_mod  # noqa: E402
from lib.search import SearchIndex  # noqa: E402

DIST_CATS = ROOT / "site" / "dist" / "data" / "categories.json"
DB = ROOT / "data" / "drugs.db"


class AtcDetectTest(unittest.TestCase):
    def test_client_parity(self) -> None:
        # 与 app.js `atcQuery` 的样例一致
        for q in ("C07", "C07A", "C07AB", "C07AB02", "c07ab02", " A07 "):
            self.assertTrue(cat_mod.atc_query(q), q)
        for q in ("C7", "7C07", "AB12", "C07AB021", "lipitor", "C07 AB02", ""):
            self.assertEqual(cat_mod.atc_query(q), "", q)

    def test_returns_uppercase(self) -> None:
        self.assertEqual(cat_mod.atc_query("c07ab02"), "C07AB02")


class CategoryMatchTest(unittest.TestCase):
    def test_snapshot_sync_with_dist(self) -> None:
        if not DIST_CATS.exists():
            self.skipTest("site/dist/data/categories.json 不存在（未建站）")
        data = json.loads(DIST_CATS.read_text(encoding="utf-8"))
        dist = {c["id"]: c for c in data["categories"] if c.get("kind") == "cat"}
        ours = {c["id"]: c for c in cat_mod.CATEGORY_SNAPSHOT}
        self.assertEqual(set(dist), set(ours), "大类 id 与构建产物不同步")
        for cid, c in ours.items():
            d = dist[cid]
            self.assertEqual(c["prefixes"], list(d.get("prefixes") or []))
            for lang in ("en", "es", "zh", "zh-Hant"):
                if (d.get("labels") or {}).get(lang):
                    self.assertEqual(c["labels"].get(lang), d["labels"][lang])

    def test_four_language_labels(self) -> None:
        cat = cat_mod.match_category("降压药")
        self.assertIsNotNone(cat)
        self.assertEqual(cat["cat"]["id"], "antihypertensives")
        self.assertEqual(cat["source"], "label")
        self.assertEqual(cat_mod.match_category("降壓藥")["cat"]["id"], "antihypertensives")
        self.assertEqual(cat_mod.match_category("Blood-pressure medicines")["cat"]["id"],
                         "antihypertensives")
        self.assertEqual(
            cat_mod.match_category("Medicamentos para la presión arterial")["cat"]["id"],
            "antihypertensives")

    def test_colloquial_aliases(self) -> None:
        # 部分口语别名本身就是官方 zh label（如 胃药/降糖药），source 会是 label；
        # 这里先断言「类别正确」，再单独验证纯口语别名走 colloquial 分支。
        for q, cid in (("退烧药", "analgesics"), ("消炎药", "antibiotics"),
                       ("胃药", "acid-related"), ("降糖药", "diabetes"),
                       ("减肥药", "weight-loss"), ("感冒药", "cold-medicine"),
                       ("他汀", "statins"), ("抗病毒药", "antivirals")):
            m = cat_mod.match_category(q)
            self.assertIsNotNone(m, q)
            self.assertEqual(m["cat"]["id"], cid)
            self.assertIn(m["source"], ("label", "alias", "colloquial"))
        for q in ("退烧药", "消炎药", "他汀"):
            self.assertEqual(cat_mod.match_category(q)["source"], "colloquial", q)
        # 带重音/空格也按客户端 catNorm 归一
        self.assertEqual(cat_mod.match_category("Antibióticos")["cat"]["id"], "antibiotics")

    def test_no_false_positive(self) -> None:
        for q in ("lipitor", "药", "C07", "tylenol", ""):
            self.assertIsNone(cat_mod.match_category(q), q)


class AtcCategorySearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.exists():
            raise unittest.SkipTest("没有 data/drugs.db")
        cls._real_connect = sqlite3.connect

        def ro_connect(database, *a, **kw):
            s = str(database)
            kw.setdefault("timeout", 60)
            if "mode=ro" not in s:
                return cls._real_connect("file:" + s + "?mode=ro", uri=True, *a, **kw)
            return cls._real_connect(database, *a, **kw)

        sqlite3.connect = ro_connect
        cls.idx = SearchIndex(DB)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.idx.close()
        sqlite3.connect = cls._real_connect

    def test_atc_exact_code(self) -> None:
        res = self.idx.search("C07AB02")
        self.assertEqual(res.match_source, "atc")
        self.assertTrue(res.cards)
        subs = {s.casefold() for c in res.cards for s in c.substances}
        self.assertTrue(any("metoprolol" in s or "bisoprolol" in s or "atenolol" in s
                            for s in subs), subs)
        self.assertEqual(res.cards[0].tier, "atc")

    def test_atc_prefix_more_than_code(self) -> None:
        code = self.idx.search("C07AB02")
        prefix = self.idx.search("C07")
        self.assertEqual(prefix.match_source, "atc")
        self.assertGreaterEqual(prefix.total_keys, code.total_keys)

    def test_atc_case_insensitive(self) -> None:
        self.assertEqual(self.idx.search("c07ab02").match_source, "atc")

    def test_category_label_zh(self) -> None:
        res = self.idx.search("降压药")
        self.assertEqual(res.match_source, "category")
        self.assertTrue(res.cards)
        self.assertEqual(res.match_detail["category_id"], "antihypertensives")
        self.assertEqual(res.cards[0].tier, "category")

    def test_category_labels_en_es_zh_hant(self) -> None:
        for q in ("Blood-pressure medicines",
                  "Medicamentos para la presión arterial", "降壓藥"):
            res = self.idx.search(q)
            self.assertEqual(res.match_source, "category", q)
            self.assertTrue(res.cards, q)

    def test_category_colloquial(self) -> None:
        res = self.idx.search("退烧药")
        self.assertEqual(res.match_source, "category")
        self.assertTrue(res.cards)
        self.assertEqual(res.match_detail["category_id"], "analgesics")
        self.assertEqual(res.match_detail["source"], "colloquial")

    def test_regular_name_unaffected(self) -> None:
        res = self.idx.search("lipitor")
        self.assertEqual(res.match_source, "")
        self.assertTrue(res.cards)
        self.assertEqual(res.cards[0].tier, "exact")

    def test_invalid_atc_not_misrouted(self) -> None:
        self.assertNotEqual(self.idx.search("C7").match_source, "atc")
        self.assertNotEqual(self.idx.search("C07AB021").match_source, "atc")


if __name__ == "__main__":
    unittest.main()
