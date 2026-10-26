"""检索层测试：用一个最小夹具库验证打分、消歧、碰撞。

运行：python -m unittest discover -s lib -t lib -v
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "lib"))

from normalize_name import normalize  # noqa: E402
from search import SearchIndex  # noqa: E402

SCHEMA = ROOT / "db" / "schema.sql"

# (substance_id, inn_en, inn_zh)
SUBS = [
    ("atorvastatin", "Atorvastatin", "阿托伐他汀"),
    ("acetaminophen", "Acetaminophen", "对乙酰氨基酚"),
    ("diphenhydramine", "Diphenhydramine", "苯海拉明"),
    ("acrivastine", "Acrivastine", "阿伐斯汀"),
    ("pseudoephedrine", "Pseudoephedrine", "伪麻黄碱"),
]

# (pid, country, brand, form, base, release, [(sub, strength, unit)])
PRODUCTS = [
    ("US-lipitor-20", "US", "Lipitor", "tablet, film coated", "tablet", "none",
     [("atorvastatin", 20.0, "mg")]),
    ("US-lipitor-40", "US", "Lipitor", "tablet, film coated", "tablet", "none",
     [("atorvastatin", 40.0, "mg")]),
    ("CN-lipitor-20", "CN", "立普妥", "tablet", "tablet", "none",
     [("atorvastatin", 20.0, "mg")]),
    ("US-tylenol", "US", "Tylenol Extra Strength", "tablet", "tablet", "none",
     [("acetaminophen", 500.0, "mg")]),
    ("CN-tylenol", "CN", "泰诺", "tablet", "tablet", "none",
     [("acetaminophen", 325.0, "mg"), ("pseudoephedrine", 30.0, "mg")]),
    ("US-benadryl", "US", "Benadryl", "tablet", "tablet", "none",
     [("diphenhydramine", 25.0, "mg")]),
    ("GB-benadryl", "GB", "Benadryl Allergy Relief", "capsule", "capsule", "none",
     [("acrivastine", 8.0, "mg")]),
]


def build_fixture(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.execute(
        "INSERT INTO source (source_id, name, retrieved_at) VALUES ('test','test','2026-01-01')")
    for sid, en, zh in SUBS:
        db.execute("INSERT INTO substance (substance_id, inn_en, inn_zh) VALUES (?,?,?)",
                   (sid, en, zh))
        db.execute("INSERT INTO variant (variant_id, substance_id) VALUES (?,?)", (sid, sid))

    for pid, country, brand, form, base, rel, comps in PRODUCTS:
        db.execute(
            "INSERT INTO product (product_id, country, dosage_form, form_base, route,"
            " release, is_branded, status, source_id, retrieved_at)"
            " VALUES (?,?,?,?,?,?,1,'active','test','2026-01-01')",
            (pid, country, form, base, "oral", rel))
        for i, (sub, val, unit) in enumerate(comps):
            db.execute(
                "INSERT INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit) VALUES (?,?,?,?,?)",
                (pid, i, sub, val, unit))
        n = normalize(brand)
        db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                   " VALUES (?,?,?,?)", (n.norm, n.norm, n.compact, n.script))
        db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                   " VALUES (?,?, 'test')", (n.norm, brand))
        db.execute("INSERT INTO product_name (product_id, key_id, name_type, is_primary)"
                   " VALUES (?,?, 'trade', 1)", (pid, n.norm))

    db.execute("INSERT INTO brand_family (family_id, label, note)"
               " VALUES ('tylenol','Tylenol / 泰诺','美国单方、中国复方')")
    for key in ("tylenol extra strength", "泰诺"):
        db.execute("INSERT INTO name_family (key_id, family_id) VALUES (?, 'tylenol')", (key,))
    db.commit()
    db.close()


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "t.db"
        build_fixture(cls.db_path)
        cls.idx = SearchIndex(cls.db_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.idx.close()
        cls.tmp.cleanup()

    # --- 归一化到检索的链路 ---
    def test_case_variants_land_on_same_key(self):
        for q in ("Lipitor 20mg", "LIPITOR", "lipitor 20 mg", "Ｌｉｐｉｔｏｒ"):
            res = self.idx.search(q)
            self.assertTrue(res.cards, q)
            self.assertEqual(res.cards[0].key_id, "lipitor", q)

    def test_cyrillic_and_chinese(self):
        self.assertEqual(self.idx.search("立普妥 20mg").cards[0].key_id, "立普妥")
        # 西里尔写法的 Lipitor 走音译键，这里只验证不报错且能返回候选
        self.assertIsNotNone(self.idx.search("ЛИПИТОР"))

    # --- 打分与消歧 ---
    def test_strength_boost_puts_matching_strength_first(self):
        # 8 mg 是 GB 的阿伐斯汀，25 mg 是美国的苯海拉明：剂量线索应把 GB 那条顶上来
        res = self.idx.search("Benadryl 8 mg")
        self.assertEqual(res.cards[0].country, "GB")
        self.assertEqual(res.cards[0].strength_text, "8 mg")
        self.assertGreater(res.cards[0].score, res.cards[1].score)

    def test_country_filter_is_strict(self):
        res = self.idx.search("Lipitor", country="CN")
        self.assertTrue(all(c.country == "CN" for c in res.cards))
        # Lipitor 这个名字在中国没有收录：应给明确说明，而不是回退到美国结果
        res2 = self.idx.search("Lipitor", country="CN")
        self.assertTrue(all(c.country == "CN" for c in res2.cards))

    def test_country_filter_empty_explains(self):
        res = self.idx.search("泰诺", country="US")
        self.assertTrue(res.empty)
        self.assertIn("查不到不代表", res.note)

    def test_never_single_answer_for_ambiguous_brand(self):
        res = self.idx.search("Benadryl")
        keys = {c.key_id for c in res.cards}
        self.assertIn("benadryl", keys)
        self.assertGreaterEqual(len(keys), 2)
        subs = {c.composition for c in res.cards}
        self.assertGreaterEqual(len(subs), 2)

    def test_empty_and_dose_only(self):
        self.assertTrue(self.idx.search("   ").empty)
        res = self.idx.search("20 mg")
        self.assertTrue(res.empty)
        self.assertEqual(res.note, "只给了剂量，没有药名")

    # --- 碰撞 ---
    def test_severe_collision_detected(self):
        page = self.idx.name_page("泰诺")
        self.assertIsNotNone(page)
        self.assertEqual(page["level"], "severe")
        self.assertEqual(len(page["substances"]), 2)

    def test_info_level_for_plain_brand(self):
        self.assertEqual(self.idx.name_page("lipitor")["level"], "info")

    # --- 身份卡 ---
    def test_drug_page_cross_country(self):
        page = self.idx.drug_page("atorvastatin")
        self.assertIsNotNone(page)
        self.assertIn("US", page["by_country"])
        self.assertIn("CN", page["by_country"])

    def test_unknown_substance(self):
        self.assertIsNone(self.idx.drug_page("nope"))


if __name__ == "__main__":
    unittest.main()
