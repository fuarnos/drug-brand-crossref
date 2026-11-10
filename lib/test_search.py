"""检索层测试：用一个最小夹具库验证打分、消歧、碰撞。

运行：python -m unittest discover -s lib -t lib -v
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
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
    ("metformin", "Metformin", "二甲双胍"),
    # v0.11.0：EU 区域层回归用（同一商品名同时有国别行和区域层行）
    ("denosumab", "Denosumab", "地舒单抗"),
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
    ("CN-glucophage", "CN", "格华止", "tablet", "tablet", "none",
     [("metformin", 500.0, "mg")]),
    ("US-prolia", "US", "Prolia", "injection, solution", "injection", "none",
     [("denosumab", 60.0, "mg")]),
]

# 区域层（EU=EMA 集中审批）产品：schema 要求 country IS NULL + region='EU'（二选一）。
# 刻意只给 region —— 检索层任何未做 COALESCE(p.country, p.region) 的取数都会拿到 None，
# 下面的 EU 回归测试因此会在「裸 p.country」实现下失败（这正是它要锁住的行为）。
# (pid, brand, form, base, release, [(sub, strength, unit)])
EU_PRODUCTS = [
    ("EU-prolia", "Prolia", "injection, solution", "injection", "none",
     [("denosumab", 60.0, "mg")]),
]


def insert_product(db: sqlite3.Connection, pid: str, brand: str, form: str, base: str,
                   rel: str, comps: list[tuple[str, float, str]], *,
                   country: str | None = None, region: str | None = None,
                   route: str = "oral") -> None:
    """写一行产品（country / region 二选一）、它的成分和商品名。"""
    db.execute(
        "INSERT INTO product (product_id, country, region, dosage_form, form_base, route,"
        " release, is_branded, status, source_id, retrieved_at)"
        " VALUES (?,?,?,?,?,?,?,1,'active','test','2026-01-01')",
        (pid, country, region, form, base, route, rel))
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
        insert_product(db, pid, brand, form, base, rel, comps, country=country)
    # 区域层行：country 保持 NULL，只给 region（见上面 EU_PRODUCTS 的注释）。
    for pid, brand, form, base, rel, comps in EU_PRODUCTS:
        insert_product(db, pid, brand, form, base, rel, comps, region="EU",
                       route="subcutaneous")

    db.execute("INSERT INTO brand_family (family_id, label, note)"
               " VALUES ('tylenol','Tylenol / 泰诺','美国单方、中国复方')")
    for key in ("tylenol extra strength", "泰诺"):
        db.execute("INSERT INTO name_family (key_id, family_id) VALUES (?, 'tylenol')", (key,))
    db.execute(
        "INSERT INTO nickname (substance_id, alias, alias_norm, label_zh, kind,"
        " confidence, source, note, created_at)"
        " VALUES ('metformin','两只青蛙','两只青蛙','二甲双胍','slang','user',"
        " 'test','用户提供的网络俗称','2026-01-01')")
    # 美国街头叫法 / 类别 / 本库无产品：三种情形各一条。
    for term, norm, ttype, sid, zh, en, mzh, men in (
        ("bars", "bars", "street", "metformin", "二甲双胍", "Metformin",
         None, None),
        ("water pill", "water pill", "class", None, "利尿剂", "Diuretics",
         "利尿剂的类别叫法。", "Class term for diuretics."),
        ("molly", "molly", "street", None, "MDMA", "MDMA",
         "摇头丸；本库无上市产品。", "MDMA; no marketed product in this database."),
    ):
        db.execute(
            "INSERT INTO drug_term (term, term_norm, term_type, country, label_zh,"
            " label_en, meaning_zh, meaning_en, substance_id, confidence,"
            " source_id, note, created_at)"
            " VALUES (?,?,?, 'US', ?,?,?,?,?, 'documented', 'test', '', '2026-01-01')",
            (term, norm, ttype, zh, en, mzh, men, sid))
    db.execute(
        "INSERT INTO confusable_pair (name_a, name_b, norm_a, norm_b,"
        " a_substance_id, b_substance_id, reason, severity, source_id, note, created_at)"
        " VALUES ('Metformin','Acetaminophen','metformin','acetaminophen',"
        " 'metformin','acetaminophen','both','high','test','fixture','2026-01-01')")
    db.commit()
    db.close()


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 临时库放仓库内 .tmp/（已 ignore）：有些受限环境会锁住 %TEMP%，
        # 而工作区本身总是可写的。不用 tempfile：它会建 0o700 的目录，
        # 在某些 Windows 沙箱里会变成「自己反而进不去」。
        cls.tmpdir = ROOT / ".tmp" / "test-search"
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        cls.tmpdir.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.tmpdir / "t.db"
        build_fixture(cls.db_path)
        cls.idx = SearchIndex(cls.db_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.idx.close()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

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

    # --- 俗称 / 网络别名 -------------------------------------------------
    def test_nickname_resolves_to_substance(self):
        res = self.idx.search("两只青蛙")
        self.assertTrue(res.cards)
        self.assertEqual(res.alias["substance_id"], "metformin")
        self.assertEqual(res.alias["label_zh"], "二甲双胍")
        self.assertEqual(res.alias["kind"], "slang")
        self.assertEqual(res.cards[0].brand, "格华止")
        self.assertEqual(res.cards[0].composition, "Metformin")
        self.assertEqual(res.cards[0].tier, "nickname")
        self.assertIn("网络俗称", res.note)

    def test_nickname_with_strength_and_country(self):
        res = self.idx.search("两只青蛙 500mg", country="CN")
        self.assertTrue(res.cards)
        self.assertTrue(all(c.country == "CN" for c in res.cards))
        self.assertEqual(res.cards[0].strength_text, "500 mg")

    def test_nickname_country_empty_is_honest(self):
        res = self.idx.search("两只青蛙", country="US")
        self.assertTrue(res.empty)
        self.assertIn("查不到不代表", res.note)

    def test_nickname_is_not_a_product_name(self):
        # 俗称不能污染碰撞/同名页：它只指向成分，不冒充包装上的名字
        self.assertIsNone(self.idx.name_page("两只青蛙"))

    # --- 美国街头叫法 / 类别词 / 无上市产品 -------------------------------
    def test_drug_term_street_name_resolves(self):
        res = self.idx.search("bars")
        self.assertTrue(res.cards)
        self.assertEqual(res.alias["substance_id"], "metformin")
        self.assertEqual(res.alias["kind"], "street")
        self.assertEqual(res.alias["origin"], "drug_term")
        self.assertIn("街头叫法", res.note)

    def test_drug_term_class_is_not_a_product(self):
        res = self.idx.search("water pill")
        self.assertTrue(res.empty)
        self.assertEqual(res.alias["kind"], "class")
        self.assertIn("类别叫法", res.note)
        self.assertIsNone(res.alias["substance_id"])

    def test_drug_term_unmapped_is_honest(self):
        res = self.idx.search("molly")
        self.assertTrue(res.empty)
        self.assertEqual(res.alias["kind"], "street")
        self.assertIn("本库", res.note)
        self.assertIn("MDMA", res.note)

    # --- 易混淆药对 ---
    def test_confusable_pair_is_flagged(self):
        res = self.idx.search("metformin")
        self.assertTrue(res.confused)
        self.assertEqual(res.confused[0]["name"], "Acetaminophen")

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

    # --- 区域层（EU=EMA）country 归一化：v0.11.0 P0 回归 -------------------
    # 夹具里 EU-prolia 只写 region='EU'、country 为 NULL（schema 二选一）。
    # 若 lib/search.py 的取数退回裸 `p.country`，卡片 country 会变成 None：
    # 第一条测试直接失败；name_page / drug_page 还会在 sorted(None, 'US') 上抛 TypeError。
    def test_eu_region_card_country_is_eu(self):
        res = self.idx.search("Prolia")
        self.assertTrue(res.cards)
        self.assertEqual([c for c in res.cards if c.country is None], [],
                         "EU 区域层卡片的 country 不能是 None")
        self.assertIn("EU", {c.country for c in res.cards})
        # 国家过滤也要能吃区域层：裸 p.country 实现下这里恒 0 条，还回「在 EU 没有收录」的假阴性
        res_eu = self.idx.search("Prolia", country="EU")
        self.assertTrue(res_eu.cards)
        self.assertEqual({c.country for c in res_eu.cards}, {"EU"})

    def test_eu_region_pages_sort_eu_with_country(self):
        # 原 bug 崩溃点：sorted({c.country ...}) / sorted(s["countries"]) 里 None 与 'US' 比较
        page = self.idx.name_page("prolia")
        self.assertIsNotNone(page)
        self.assertEqual(sorted(page["countries"]), ["EU", "US"])
        self.assertEqual(page["substances"][0]["countries"], ["EU", "US"])
        drug = self.idx.drug_page("denosumab")
        self.assertIsNotNone(drug)
        self.assertIn("EU", drug["by_country"])
        self.assertNotIn(None, drug["by_country"])


if __name__ == "__main__":
    unittest.main()
