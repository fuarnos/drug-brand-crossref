"""社区叫法种子测试：只测数据形状，不碰数据库。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from ingest_community_terms import SOURCES, TERMS  # noqa: E402


class CommunityTermsTests(unittest.TestCase):
    def test_countries_present(self):
        countries = {t[1] for t in TERMS}
        for c in ("CN", "GB", "AU", "ES"):
            self.assertIn(c, countries)

    def test_all_terms_have_source_url(self):
        for t in TERMS:
            self.assertTrue(t[7].startswith("http"), t[0])
            self.assertIn(t[6], SOURCES, t[0])

    def test_chinese_community_terms(self):
        terms = {t[0]: t for t in TERMS}
        self.assertEqual(terms["闭口神器"][5], ["adapalene"])
        self.assertEqual(terms["聪明药"][5], ["methylphenidate", "modafinil"])


if __name__ == "__main__":
    unittest.main()
