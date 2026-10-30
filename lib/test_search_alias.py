"""同物异名检索层测试（task-141b）：搜 dextrose 也能看到 Glucose 的条目。

边界（与 `lib/test_search.py` 同一套夹具口径）：
- 异名命中是**追加候选**：分数低于精确名命中、高于纯前缀噪声，主结果相对顺序不变；
- 「这个名字指哪个成分」只从**单成分产品**推断，复方里的辅料（氯化钠/注射用水）不当种子；
- 异名卡片只收单成分条目（同一成分的条目，不是「配方里顺带有它」的复方），
  标 `tier="inn_alias"` + `match_source="inn_alias"`，与俗称（nickname / drug_term）区分；
- 异名表缺失时静默关闭，行为回到「只有名字检索」；
- 只读：不改 `data/drugs.db`、不改站点。

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
    ("glucose", "Glucose", "葡萄糖"),
    ("dextrose", "Dextrose", ""),
    ("anhydrous-dextrose", "Anhydrous Dextrose", ""),
    ("sodium-chloride", "Sodium Chloride", "氯化钠"),
    ("atorvastatin", "Atorvastatin", "阿托伐他汀"),
]

# (pid, country, brand, form, base, release, [(sub, strength, unit)])
PRODUCTS = [
    ("CN-glucose-inj", "CN", "葡萄糖注射液", "injection", "injection", "none",
     [("glucose", 50.0, "g")]),
    ("CN-glucose-powder", "CN", "葡萄糖粉剂", "powder", "powder", "none",
     [("glucose", 500.0, "g")]),
    ("US-dextrose-inj", "US", "DEXTROSE", "injection", "injection", "none",
     [("dextrose", 50.0, "g")]),
    ("CA-dextrose-inj", "CA", "DEXTROSE INJECTION", "injection", "injection", "none",
     [("dextrose", 25.0, "g")]),
    # 复方：dextrose 在这里只是成分之一，它的 key 对 "dextrose" 只是前缀噪声
    ("US-dextrose-nacl", "US", "Dextrose and Sodium Chloride", "liquid", "liquid", "none",
     [("dextrose", 5.0, "g"), ("sodium-chloride", 0.9, "g")]),
    # anhydrous-dextrose 只有复方产品 → 不该作为「同组成分条目」被追加
    ("US-anhydrous-combo", "US", "ANHYDROUS DEXTROSE MIX", "liquid", "liquid", "none",
     [("anhydrous-dextrose", 5.0, "g"), ("sodium-chloride", 0.9, "g")]),
    # 只有复方产品的名字：不能从它的成分反推「Fizzy = Glucose」
    ("US-fizzy", "US", "Fizzy Combo", "tablet", "tablet", "none",
     [("glucose", 1.0, "g"), ("sodium-chloride", 0.5, "g")]),
    # 对照组：不在异名表里，行为必须与改造前一致
    ("US-lipitor", "US", "Lipitor", "tablet", "tablet", "none",
     [("atorvastatin", 20.0, "mg")]),
]

# 夹具用的最小异名表（只放 Glucose 一组，避免依赖 data/substance_aliases.csv 的内容）
ALIAS_CSV = """canonical_inn,canonical_id,alias_inn,alias_id,relation,source,note
Glucose,glucose,Dextrose,dextrose,synonym,INN vs USAN,美国标签用 Dextrose
Glucose,glucose,Anhydrous Dextrose,anhydrous-dextrose,hydrate_variant,US label,无水写法
"""


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

    # 俗称路径（nickname）：用来证明它与异名（inn_alias）是两条不同的来源
    db.execute(
        "INSERT INTO nickname (substance_id, alias, alias_norm, label_zh, kind,"
        " confidence, source, note, created_at)"
        " VALUES ('glucose','右旋糖','右旋糖','葡萄糖','legacy','documented',"
        " 'test','中文旧名','2026-01-01')")
    db.commit()
    db.close()


class AliasSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = ROOT / ".tmp" / "test-search-alias"
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        cls.tmpdir.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.tmpdir / "t.db"
        build_fixture(cls.db_path)
        cls.alias_path = cls.tmpdir / "aliases.csv"
        cls.alias_path.write_text(ALIAS_CSV, encoding="utf-8")
        cls.idx = SearchIndex(cls.db_path, alias_path=cls.alias_path)
        # 对照组：异名表缺失 → 与改造前的检索行为一致
        cls.idx_plain = SearchIndex(cls.db_path, alias_path=cls.tmpdir / "nope.csv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.idx.close()
        cls.idx_plain.close()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    @staticmethod
    def _alias_cards(res) -> list:
        return [c for c in res.cards if c.match_source == "inn_alias"]

    # --- 1) 异名互见（验收的主路径）-----------------------------------------
    def test_english_query_shows_glucose_entries(self):
        # 搜 dextrose → 追加 Glucose 的条目
        res = self.idx.search("dextrose")
        alias = self._alias_cards(res)
        self.assertTrue(alias, "搜 dextrose 应追加 Glucose 条目")
        self.assertIn("Glucose", {c.composition for c in alias})
        self.assertTrue(all(c.tier == "inn_alias" for c in alias))
        self.assertIn("inn_alias", res.match_detail)
        meta = res.match_detail["inn_alias"]
        self.assertEqual(meta["source"], "data/substance_aliases.csv")
        self.assertEqual(meta["seed_names"], ["Dextrose"])
        self.assertIn("Glucose", meta["group_names"])
        self.assertIn("同一成分", res.note)
        self.assertIn("不代表剂型/规格可互换", res.note)

    def test_chinese_query_shows_dextrose_entries(self):
        # 搜 葡萄糖 → 追加 Dextrose 的条目
        res = self.idx.search("葡萄糖")
        alias = self._alias_cards(res)
        self.assertTrue(alias, "搜 葡萄糖 应追加 Dextrose 条目")
        self.assertIn("Dextrose", {c.composition for c in alias})
        self.assertIn("Dextrose", res.match_detail["inn_alias"]["group_names"])

    def test_alias_is_addition_not_replacement(self):
        # 主结果（按名字命中的中文条目）还在，异名只是追加
        res = self.idx.search("葡萄糖")
        main = [c for c in res.cards if c.match_source != "inn_alias"]
        self.assertTrue(main)
        self.assertTrue(any("葡萄糖" in c.brand for c in main))
        # 结果级 match_source 只在「结果全是异名带来」时才标
        self.assertEqual(res.match_source, "")
        self.assertTrue(res.total_keys > 0)

    # --- 2) 打分与排序 -------------------------------------------------------
    def test_score_between_exact_and_prefix(self):
        res = self.idx.search("dextrose", limit=25)
        exact = [c for c in res.cards if c.tier == "exact"]
        prefix = [c for c in res.cards if c.tier == "prefix"]
        alias = [c for c in res.cards if c.tier == "inn_alias"]
        self.assertTrue(exact and prefix and alias, [c.tier for c in res.cards])
        self.assertLess(alias[0].score, exact[0].score, "异名必须低于精确名命中")
        self.assertGreater(alias[0].score, prefix[0].score, "异名必须高于纯前缀噪声")
        # 位置：精确命中全部在异名之前，异名全部在前缀噪声之前
        last_exact = max(i for i, c in enumerate(res.cards) if c.tier == "exact")
        first_alias = min(i for i, c in enumerate(res.cards) if c.tier == "inn_alias")
        last_alias = max(i for i, c in enumerate(res.cards) if c.tier == "inn_alias")
        first_prefix = min(i for i, c in enumerate(res.cards) if c.tier == "prefix")
        self.assertLess(last_exact, first_alias)
        self.assertLess(last_alias, first_prefix)

    def test_main_result_order_unchanged(self):
        # 开/关异名层，主结果的相对顺序与数量必须一致（只是多了追加候选）
        for query in ("dextrose", "葡萄糖"):
            on = [c.key_id for c in self.idx.search(query, limit=25).cards
                  if c.match_source != "inn_alias"]
            off = [c.key_id for c in self.idx_plain.search(query, limit=25).cards]
            self.assertEqual(on, off, query)

    def test_alias_cards_do_not_duplicate_main(self):
        for query in ("dextrose", "葡萄糖"):
            res = self.idx.search(query, limit=25)
            sigs = [(c.country, c.composition, c.dosage_form) for c in res.cards]
            self.assertEqual(len(sigs), len(set(sigs)), query)

    # --- 3) 边界：只认单成分、只回单成分卡 ------------------------------------
    def test_alias_cards_are_single_component(self):
        res = self.idx.search("dextrose", limit=25)
        for c in self._alias_cards(res):
            self.assertEqual(len(c.substances), 1, c.composition)
        # 复方里顺带有 anhydrous-dextrose 的条目不算「同组成分的条目」
        # （它作为「名字前缀命中的主结果」可以出现，但不能被当成异名追加）
        self.assertNotIn("ANHYDROUS DEXTROSE MIX",
                         {c.brand for c in self._alias_cards(res)})

    def test_combo_only_name_is_not_seeded(self):
        # 「Fizzy Combo」只有复方产品：不能从它的成分猜「Fizzy = Glucose」
        res = self.idx.search("fizzy")
        self.assertTrue(res.cards)
        self.assertFalse(self._alias_cards(res))
        self.assertEqual(res.match_detail, {})
        self.assertEqual(res.note, "")

    # --- 4) 国家过滤 / 上限 / 精确命中不被挤掉 --------------------------------
    def test_country_filter_can_be_fully_alias(self):
        # 名字本身在 CN 没有条目，但异名线索能带出 CN 的葡萄糖
        res = self.idx.search("dextrose", country="CN")
        self.assertTrue(res.cards)
        self.assertEqual(res.match_source, "inn_alias")
        self.assertTrue(all(c.match_source == "inn_alias" for c in res.cards))
        self.assertTrue(all(c.country == "CN" for c in res.cards))
        self.assertEqual(res.cards[0].composition, "Glucose")
        self.assertNotIn("没有收录", res.note)

    def test_limit_respected(self):
        for limit in (1, 2, 5, 10, 25):
            res = self.idx.search("dextrose", limit=limit)
            self.assertLessEqual(len(res.cards), limit, limit)

    def test_precise_hits_never_evicted(self):
        # 两张精确命中占满 limit=2：异名不许把它们挤掉
        res = self.idx.search("dextrose", limit=2)
        self.assertEqual(len(res.cards), 2)
        self.assertTrue(all(c.tier == "exact" for c in res.cards))

    # --- 5) 与俗称区分 / 缺表降级 -------------------------------------------
    def test_nickname_path_stays_separate(self):
        res = self.idx.search("右旋糖")
        self.assertTrue(res.cards)
        self.assertEqual(res.cards[0].tier, "nickname")
        self.assertEqual(res.alias.get("origin"), "nickname")
        self.assertFalse(self._alias_cards(res))
        self.assertEqual(res.match_source, "")

    def test_missing_alias_csv_degrades_to_name_search(self):
        for query in ("dextrose", "葡萄糖"):
            res = self.idx_plain.search(query, limit=25)
            self.assertFalse([c for c in res.cards if c.match_source], query)
            self.assertEqual(res.match_detail, {}, query)
            self.assertEqual(res.note, "", query)

    def test_alias_map_loaded_from_csv(self):
        self.assertEqual(len(self.idx.alias.pairs), 2)
        self.assertEqual(self.idx.alias.canonical("dextrose"), "glucose")
        self.assertEqual(len(self.idx_plain.alias.pairs), 0)


class RealDbAliasTests(unittest.TestCase):
    """真库只读回归：验收用的两条查询（缺库时跳过）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = ROOT / "data" / "drugs.db"
        if not cls.db.exists():
            raise unittest.SkipTest("无 data/drugs.db，跳过真库回归")
        cls._real_connect = sqlite3.connect

        def ro_connect(database, *args, **kwargs):
            s = str(database)
            kwargs.setdefault("timeout", 60)
            if "mode=ro" not in s:
                return cls._real_connect("file:" + s + "?mode=ro", uri=True, *args, **kwargs)
            return cls._real_connect(database, *args, **kwargs)

        sqlite3.connect = ro_connect
        cls.idx = SearchIndex(cls.db)

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "idx", None) is not None:
            cls.idx.close()
        if getattr(cls, "_real_connect", None) is not None:
            sqlite3.connect = cls._real_connect

    def test_real_csv_used(self):
        self.assertGreaterEqual(len(self.idx.alias.pairs), 5)

    def test_dextrose_sees_glucose(self):
        res = self.idx.search("dextrose")
        alias = [c for c in res.cards if c.match_source == "inn_alias"]
        self.assertTrue(alias, "搜 dextrose 应看到 Glucose 条目")
        self.assertTrue(any("Glucose" in c.substances for c in alias))
        meta = res.match_detail.get("inn_alias", {})
        self.assertEqual(meta.get("source"), "data/substance_aliases.csv")
        self.assertGreater(meta.get("shown", 0), 0)

    def test_glucose_sees_dextrose(self):
        res = self.idx.search("葡萄糖")
        alias = [c for c in res.cards if c.match_source == "inn_alias"]
        self.assertTrue(alias, "搜 葡萄糖 应看到 Dextrose 条目")
        self.assertTrue(any("Dextrose" in c.substances for c in alias))

    def test_unrelated_name_untouched(self):
        # 不在异名表里的药：结果与异名层无关
        res = self.idx.search("lipitor")
        self.assertEqual(res.match_source, "")
        self.assertFalse([c for c in res.cards if c.match_source])
        self.assertEqual(res.match_detail, {})


if __name__ == "__main__":
    unittest.main()
