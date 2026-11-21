# -*- coding: utf-8 -*-
"""task-139 单测：lib 的 ATC 码 / 大类检索（与客户端 v0.6.4 / v0.7.1 对齐）。

- ATC 识别口径与客户端 `atcQuery()` 一致；
- 16 大类四语 label / alias 匹配与客户端 `catHit()` 口径一致；口语别名是 lib 扩展；
- v0.10.3：口语词表（66 条）是唯一来源；「口语词 = 真实 name_key」的防遮蔽白名单；
  12 个口语词的验收（期望大类 + 期望首个成分）；
- SearchIndex.search 返回 match_source（atc / category）与结果卡；
- 普通名字检索行为不变。
- v0.13.0：数据窗口加 CZ 68,581 + LV 18,766 产品后，两条 Top-1 期望按「现查 DB」口径
  更新（减肥药 Orlistat→Semaglutide、抗抑郁药 Venlafaxine→Duloxetine）；口径与实现未变，
  数字与判定见 reports/2026-11-16-atc-category-top1.md。
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
            self.assertEqual(c.get("aliases"), list(d.get("aliases") or []),
                             f"{cid} 的 aliases 与构建产物不同步")
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


class ColloquialTableTest(unittest.TestCase):
    """v0.10.3 #2：口语词表单一来源 + 防遮蔽白名单（不碰 DB 的部分）。"""

    def test_table_is_single_source(self) -> None:
        # 66 条是审计基线（reports/search-discovery-audit-20261110.md §3.1）；改动必须同步报告
        self.assertEqual(len(cat_mod.COLLOQUIAL_ALIASES), 66)
        ids = {c["id"] for c in cat_mod.CATEGORY_SNAPSHOT}
        self.assertLessEqual(set(cat_mod.COLLOQUIAL_ALIASES.values()), ids,
                             "口语词指向了不存在的大类 id")

    def test_client_alias_export(self) -> None:
        by = cat_mod.colloquial_aliases_by_category()
        flat = [w for words in by.values() for w in words]
        self.assertEqual(len(flat), 65, "66 条口语词减去 1 条防遮蔽白名单")
        self.assertEqual(len(by), 16, "16 个大类都应分到口语词")
        self.assertIn("退烧药", by["analgesics"])
        self.assertIn("blood pressure medicine", by["antihypertensives"])
        self.assertNotIn("antibiotic", flat, "防遮蔽白名单里的词不进客户端 aliases")

    def test_shadowed_word_keeps_name_path(self) -> None:
        # 「ANTIBIOTIC」是美/加在售商品名 → 大类层让给药名/俗称层
        self.assertIsNone(cat_mod.match_category("antibiotic"))
        self.assertTrue(cat_mod.is_shadowed("Antibiotic"))
        # 复数官方 label 仍然进大类
        m = cat_mod.match_category("antibiotics")
        self.assertIsNotNone(m)
        self.assertEqual(m["cat"]["id"], "antibiotics")


class NameKeyShadowTest(unittest.TestCase):
    """v0.10.3 #2：现查 name_key，新的「口语词 = 商品名」撞车必须先登记白名单。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not DB.exists():
            raise unittest.SkipTest("没有 data/drugs.db")
        cls.db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()

    def test_no_unlisted_shadow(self) -> None:
        self.assertEqual(cat_mod.find_name_key_shadows(self.db), ["antibiotic"])
        cat_mod.assert_no_unlisted_shadow(self.db)   # 新增撞车会抛 ValueError


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

    def test_shadowed_colloquial_not_category(self) -> None:
        # 防遮蔽：这个词是真商品名（美/加 OTC 抗菌软膏），不许被大类接走
        res = self.idx.search("antibiotic")
        self.assertNotEqual(res.match_source, "category")

    def test_real_product_name_not_swallowed(self) -> None:
        # 报告 §3.4-4 的验收项：真实商品名「消炎药膏」仍返回商品名结果
        res = self.idx.search("消炎药膏")
        self.assertEqual(res.match_source, "")
        self.assertTrue(res.cards)
        self.assertIn("Sulfanilamide",
                      {s for c in res.cards for s in c.substances})

    def test_colloquial_acceptance_words(self) -> None:
        """v0.10.3 #2 验收：12 个口语词 → 期望大类 + 期望首个成分（现查 DB 口径）。

        v0.13.0 数据窗口（新增 CZ / LV）后两条期望随现查变化，非实现改动：
        · 减肥药：Semaglutide 316 > Orlistat 308（剔除 CZ+LV 复算：Orlistat 254 > Semaglutide 207）
        · 抗抑郁药：Duloxetine 866 > Venlafaxine 815（剔除 CZ+LV：Venlafaxine 813 > Duloxetine 658）
        口径仍是「该类别内 active 产品最多的成分」（见 test_category_top1_by_ingredient_total）。

        v0.18.0 数据窗口（新增 MY 马来西亚 29,956 条）后又有两条期望随现查变化，实现未变：
        · 抗凝药：Rivaroxaban 2,421 > Aspirin 2,388（MY 数据把 Rivaroxaban 顶到第一）
        · 抗抑郁药：Escitalopram 868 > Duloxetine 867（差 1 条；卡片显示去盐基名）

        v1.1.0（NO 入库）：Duloxetine 874 > Escitalopram Oxalate 868（剔除 NO 时 868 > 862）；
        期望值随数据窗口变化、实现不变（874−862=+12：NO 7 行 + EU 区域层 5 行；
        Escitalopram 系 +14，基盐名分列、不合并）。

        v1.2.0（KR 入库，97,356 品目）后 4 条期望随现查变化，实现未变：
        · 降糖药：Metformin Hydrochloride 3,941 > Metformin 2,961（KR 把 metformin HCl 品目挂到盐型行）
        · 减肥药：Orlistat 361 > Semaglutide 353
        · 他汀：Rosuvastatin Calcium 2,053 / 去盐基名 1,463 > Atorvastatin 1,914（首卡显示基名 Rosuvastatin）
        · 抗抑郁药：Escitalopram Oxalate 974 > Duloxetine 874（首卡 ES 显示基名 Escitalopram；
          本条为 v1.1.0 那次 Duloxetine 改动的回退）
        """
        cases = [
            ("退烧药", "analgesics", "Acetaminophen"),
            ("消炎药", "antibiotics", "Amoxicillin"),
            ("胃药", "acid-related", "Omeprazole"),
            ("降血压药", "antihypertensives", "Hydrochlorothiazide"),
            ("降糖药", "diabetes", "Metformin Hydrochloride"),  # v1.2.0 KR：3,941 > Metformin 2,961
            ("减肥药", "weight-loss", "Orlistat"),              # v1.2.0 KR：361 > Semaglutide 353
            ("感冒药", "cold-medicine", "Acetaminophen"),
            ("抗过敏药", "allergy", "Chlorpheniramine"),
            ("抗凝药", "anticoagulants", "Rivaroxaban"),   # v0.18.0 MY：2,421 > Aspirin 2,388
            ("他汀", "statins", "Rosuvastatin"),            # v1.2.0 KR：钙盐 2,053/基名 1,463 > Atorvastatin 1,914
            ("抗抑郁药", "antidepressants", "Escitalopram"),  # v1.2.0 KR：草酸盐 974 > Duloxetine 874
            ("皮肤药", "dermatologicals", "Zinc Oxide"),
        ]
        for q, cid, ing in cases:
            res = self.idx.search(q)
            self.assertEqual(res.match_source, "category", q)
            self.assertEqual(res.match_detail["category_id"], cid, q)
            self.assertTrue(res.cards, q)
            self.assertIn(ing, res.cards[0].substances, f"{q} 的首个成分应为 {ing}")

    def test_category_top1_by_ingredient_total(self) -> None:
        """v0.10.3 #3 排序：Top-1 = 该类别里 active 产品最多的成分（方案 H）。

        v0.13.0 按现查 DB 更新抗抑鬱藥期望：Venlafaxine 815 < Duloxetine 866；
        剔除 CZ+LV 复算为 Venlafaxine 813 > Duloxetine 658（旧期望在旧窗口成立）。
        注意：Venlafaxine Hydrochloride 是另一条 substance 行（434，其中 CZ 395），
        本口径按 substance 行计数（与 gen_atc_category_cases.py / 客户端 atc-ing 同源），
        不合并盐型；合并后 815+434=1,249 的口径不在本任务范围（见报告 §5）。

        v1.2.0（KR 入库）再回退一次：Escitalopram Oxalate 974 > Duloxetine 874
        （首卡 ES `ESCITALOPRAM` 显示去盐基名）——期望随数据窗口变化，实现未变。
        """
        for q, cid, ing in (("抗过敏药", "allergy", "Chlorpheniramine"),
                            ("Blood-pressure medicines", "antihypertensives",
                             "Hydrochlorothiazide"),
                            ("抗抑鬱藥", "antidepressants", "Escitalopram")):  # v1.2.0 KR：974 > 874
            res = self.idx.search(q)
            self.assertEqual(res.match_detail["category_id"], cid, q)
            # 首位卡片可以是复方卡（如 Irbesartan + Hydrochlorothiazide），但必须含期望成分
            self.assertIn(ing, res.cards[0].substances, q)

    def test_invalid_atc_not_misrouted(self) -> None:
        self.assertNotEqual(self.idx.search("C7").match_source, "atc")
        self.assertNotEqual(self.idx.search("C07AB021").match_source, "atc")


if __name__ == "__main__":
    unittest.main()
