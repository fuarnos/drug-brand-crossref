"""别名匹配键（V7b）：别名 → 成分 Top-1 的服务端口径测试。

背景
----
`nickname` / `drug_term` 是「人嘴里的叫法」，指向活性成分（或类别）。它们的匹配键
原先直接读 DB 的 `alias_norm`，那份值是历史归一化写下的（只覆盖约 90 个常用繁简字），
于是「阿司匹靈」这类繁体叫法在客户端（toSimp 2,966 字）能转、在服务端对不上；
`654-2` 这类带标点的叫法也会因标点处理不同而漏。

V7b 口径
--------
匹配键一律用 `lib.search.alias_key()` 现算，与站点 app.js 的 `norm()` 逐字一致：
繁→简（`data/zh_hant_t2s.json` 2,966 字）→ NFKC → lower → 去 ®™© → 去组合音标
→ 标点/符号→空格 → 压空白；比较时再加「去空格」「去音标去空格」两档。
**不改 DB 里的 alias_norm、不改 nickname/product_name 数据。**

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
from search import (  # noqa: E402
    SearchIndex, alias_key, alias_key_matches, alias_query_key,
)

SCHEMA = ROOT / "db" / "schema.sql"

# (substance_id, inn_en, inn_zh)
SUBS = [
    ("aspirin", "Aspirin", "阿司匹林"),
    ("glucose", "Glucose", "葡萄糖"),
    ("atorvastatin", "Atorvastatin", "阿托伐他汀"),
    ("anisodamine", "Anisodamine", "山莨菪碱"),
]

# (pid, country, brand, form, base, release, [(sub, strength, unit)])
PRODUCTS = [
    ("US-aspirin-325", "US", "Aspirin", "tablet", "tablet", "none",
     [("aspirin", 325.0, "mg")]),
    ("CN-aspirin-bayer", "CN", "拜阿司匹灵", "tablet", "tablet", "none",
     [("aspirin", 100.0, "mg")]),
    ("US-glucose-inj", "US", "DEXTROSE 50%", "injection", "injection", "none",
     [("glucose", 50.0, "g")]),
    ("US-lipitor", "US", "Lipitor", "tablet", "tablet", "none",
     [("atorvastatin", 20.0, "mg")]),
    ("CN-anisodamine", "CN", "654-2片", "tablet", "tablet", "none",
     [("anisodamine", 5.0, "mg")]),
]

# 俗称夹具：(alias, 存进 DB 的 alias_norm 故意写旧, substance_id, kind)
NICKNAMES = [
    # 繁体叫法 + 陈旧 alias_norm：证明匹配键不读 DB 的 alias_norm
    ("阿司匹靈", "阿司匹靈", "aspirin", "legacy"),
    # 标点不同：DB 里是空格写法，实际查询常带连字符
    ("morning-after pill", "morning after pill", "aspirin", "slang"),
    # 简称 + 标点
    ("654-2", "654 2", "anisodamine", "abbrev"),
    # 同名的类别词（drug_term, 无成分）与成分条目并存 → 应优先成分
    ("普拿疼", "普拿疼", "aspirin", "legacy"),
]

# (term, term_norm, substance_id, term_type, label_zh, meaning_zh)
DRUG_TERMS = [
    # 同名、无成分的类别词：用于证明「有成分优先」
    ("普拿疼", "普拿疼", None, "folk", None, None),
    # 一个叫法指向两个成分：应返回候选集，不是唯一答案
    ("双糖", "双糖", "glucose", "folk", "葡萄糖", None),
    ("双糖", "双糖", "atorvastatin", "folk", "阿托伐他汀", None),
    # 纯类别词：没有成分可落，只给说明
    ("water pill", "water pill", None, "folk", "利尿剂", "利尿药的一类叫法"),
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

    for alias, alias_norm, sid, kind in NICKNAMES:
        db.execute(
            "INSERT INTO nickname (substance_id, alias, alias_norm, label_zh, kind,"
            " confidence, source, note, created_at)"
            " VALUES (?,?,?,?,?,'documented','test','测试夹具','2026-01-01')",
            (sid, alias, alias_norm, None, kind))
    for term, term_norm, sid, term_type, label_zh, meaning_zh in DRUG_TERMS:
        db.execute(
            "INSERT INTO drug_term (term, term_norm, term_type, country, label_zh,"
            " meaning_zh, substance_id, confidence, source_url, created_at)"
            " VALUES (?,?,?,'US',?,?,?,'documented','https://example.invalid','2026-01-01')",
            (term, term_norm, term_type, label_zh, meaning_zh, sid))
    db.commit()
    db.close()


class AliasKeyUnitTests(unittest.TestCase):
    """匹配键本身：两端共用的规则（客户端 app.js norm() 的同口径）。"""

    def test_traditional_simplified_same_key(self):
        self.assertEqual(alias_key("阿司匹靈"), alias_key("阿司匹灵"))
        self.assertEqual(alias_key("猛健樂"), alias_key("猛健乐"))
        self.assertEqual(alias_key("替西帕肽"), "替西帕肽")

    def test_punctuation_folds_to_space(self):
        self.assertEqual(alias_key("morning-after pill"), "morning after pill")
        self.assertEqual(alias_key("654-2"), "654 2")
        self.assertEqual(alias_key("顺-二氯·二氨合铂"), "顺 二氯 二氨合铂")

    def test_accents_and_case_fold(self):
        self.assertEqual(alias_key("Bromelaína"), "bromelaína")
        self.assertEqual(alias_key("Bromelaina"), "bromelaina")
        # 重音差异由 alias_key_matches 的第二档兜住（与客户端 _flatAccents 同口径）
        self.assertTrue(alias_key_matches(alias_key("Bromelaína"),
                                          alias_key("Bromelaina")))

    def test_query_key_strips_dose(self):
        self.assertEqual(alias_query_key("泰诺 500mg"), "泰诺")
        self.assertEqual(alias_query_key("morning after pill 325 mg"),
                         "morning after pill")
        self.assertEqual(alias_query_key("654-2"), "654 2")


class NicknameAliasSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = ROOT / ".tmp" / "test-search-nickname-key"
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        cls.tmpdir.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.tmpdir / "t.db"
        build_fixture(cls.db_path)
        cls.idx = SearchIndex(cls.db_path, alias_path=cls.tmpdir / "nope.csv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.idx.close()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _top1_subs(self, res) -> set[str]:
        return set(res.cards[0].substances) if res.cards else set()

    def test_traditional_alias_lands_on_ingredient(self):
        for q in ("阿司匹靈", "阿司匹灵"):
            res = self.idx.search(q)
            self.assertEqual(res.alias.get("substance_id"), "aspirin", q)
            self.assertIn("Aspirin", self._top1_subs(res), q)
            self.assertEqual(res.cards[0].tier, "nickname", q)
            self.assertEqual([c.get("substance_id") for c in res.aliases], ["aspirin"], q)

    def test_punctuation_variants_and_dose(self):
        for q in ("morning-after pill", "morning after pill",
                  "morning after pill 325 mg"):
            res = self.idx.search(q)
            self.assertEqual(res.alias.get("substance_id"), "aspirin", q)
            self.assertIn("Aspirin", self._top1_subs(res), q)

    def test_abbrev_with_dash(self):
        res = self.idx.search("654-2")
        self.assertEqual(res.alias.get("substance_id"), "anisodamine")
        self.assertIn("Anisodamine", self._top1_subs(res))

    def test_mapped_row_wins_over_class_duplicate(self):
        # 同一叫法既有类别词（无成分）又有成分：首卡必须是成分，不能是不可点的类别词
        res = self.idx.search("普拿疼")
        self.assertEqual(res.alias.get("substance_id"), "aspirin")
        self.assertEqual(len(res.aliases), 1)
        self.assertIn("Aspirin", self._top1_subs(res))

    def test_ambiguous_alias_returns_candidates(self):
        res = self.idx.search("双糖")
        sids = {a.get("substance_id") for a in res.aliases}
        self.assertEqual(sids, {"glucose", "atorvastatin"})   # 候选集，不是唯一答案
        seen = {s for c in res.cards for s in c.substances}
        self.assertIn("Glucose", seen)
        self.assertIn("Atorvastatin", seen)
        self.assertIn("可能指", res.note)
        # 首卡只能落一个成分；另一条仍必须出现在候选集里
        self.assertTrue(self._top1_subs(res) & {"Glucose", "Atorvastatin"})

    def test_unmapped_class_term_keeps_explanation(self):
        res = self.idx.search("water pill")
        self.assertEqual(len(res.aliases), 1)
        self.assertIsNone(res.aliases[0]["substance_id"])
        self.assertEqual(res.cards, [])
        self.assertIn("民间叫法", res.note)
        self.assertIn("可能对应多种成分", res.note)


if __name__ == "__main__":
    unittest.main()
