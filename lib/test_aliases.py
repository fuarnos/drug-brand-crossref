"""`lib/aliases.py` 单元测试（同物异名对照表）。

重点：
- 表本身可解析、关系值合法、行不重复；
- 并查集对称（A↔B 双向都能查到同组）；
- 名称查询不区分大小写与标点；
- 表里引用的 substance_id 都真实存在（有库时校验，只读开库）。
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from lib.aliases import DEFAULT_PATH, RELATIONS, load, norm

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"


class TestAliasFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.am = load()

    def test_file_exists(self) -> None:
        self.assertTrue(DEFAULT_PATH.exists(), f"缺少异名表：{DEFAULT_PATH}")

    def test_has_pairs(self) -> None:
        self.assertGreaterEqual(len(self.am.pairs), 5, "异名表条目过少，检查 CSV 是否被截断")

    def test_relations_valid(self) -> None:
        for p in self.am.pairs:
            self.assertIn(p.relation, RELATIONS, f"{p.alias_inn} 关系值非法：{p.relation}")

    def test_ids_nonempty_and_distinct(self) -> None:
        seen: set[tuple[str, str]] = set()
        for p in self.am.pairs:
            self.assertTrue(p.canonical_id and p.alias_id, "id 不能为空")
            self.assertNotEqual(p.canonical_id, p.alias_id, f"{p.alias_inn} 自指")
            key = (p.canonical_id, p.alias_id)
            self.assertNotIn(key, seen, f"重复行：{key}")
            seen.add(key)

    def test_has_source(self) -> None:
        for p in self.am.pairs:
            self.assertTrue(p.source, f"{p.alias_inn} 缺来源列（source 必填）")


class TestAliasLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.am = load()

    def test_canonical_symmetric(self) -> None:
        self.assertEqual(self.am.canonical("dextrose"), self.am.canonical("glucose"))
        self.assertEqual(self.am.canonical("glyburide"), self.am.canonical("glibenclamide"))

    def test_aliases_excludes_self(self) -> None:
        group = self.am.aliases("glucose")
        self.assertIn("dextrose", group)
        self.assertNotIn("glucose", group)

    def test_group_contains_self(self) -> None:
        self.assertIn("glucose", self.am.group("glucose"))

    def test_lookup_name_ignores_case_and_punct(self) -> None:
        self.assertEqual(self.am.lookup_name("Dextrose"), self.am.lookup_name("dextrose"))
        self.assertIn("glucose", self.am.lookup_name("  DEXTROSE "))

    def test_unknown_is_empty(self) -> None:
        self.assertEqual(self.am.lookup_name("not-a-real-substance"), frozenset())
        self.assertEqual(self.am.aliases("not-a-real-substance"), frozenset())
        self.assertEqual(self.am.canonical("not-a-real-substance"), "not-a-real-substance")

    def test_norm(self) -> None:
        self.assertEqual(norm("Povidone-Iodine"), "povidone iodine")
        self.assertEqual(norm("  Dextrose,  Anhydrous "), "dextrose anhydrous")


class TestAliasIdsExist(unittest.TestCase):
    """表里每个 id 都必须能在库里找到（避免拼错 id 造成静默失效）。"""

    def test_ids_exist_in_db(self) -> None:
        if not DB.exists():
            self.skipTest("无本地库，跳过 id 校验")
        am = load()
        con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
        try:
            known = {r[0] for r in con.execute("SELECT substance_id FROM substance")}
        finally:
            con.close()
        missing = {p.alias_id for p in am.pairs} | {p.canonical_id for p in am.pairs}
        missing -= known
        self.assertFalse(missing, f"异名表引用了不存在的 substance_id：{sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
