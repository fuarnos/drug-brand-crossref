"""NIDA 快照解析测试：只测纯函数，不碰数据库。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from ingest_us_terms import clean_term, parse_nida  # noqa: E402


class NidaParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = {e["title"]: e for e in parse_nida()}

    def test_core_entries_present(self):
        self.assertGreaterEqual(len(self.entries), 50)
        for title in ("Cocaine", "Fentanyl", "MDMA", "Benzodiazepines"):
            self.assertIn(title, self.entries)

    def test_cocaine_aliases(self):
        aliases = self.entries["Cocaine"]["aliases"]
        self.assertIn("Coke", aliases)
        self.assertIn("Crack", aliases)

    def test_manual_split_in_synthetic_cannabinoids(self):
        aliases = self.entries["Synthetic Cannabinoids"]["aliases"]
        self.assertIn("Skooby Snax", aliases)
        self.assertIn("Crazy Clown", aliases)
        self.assertNotIn("Skooby Snax and Crazy Clown", aliases)

    def test_clean_term(self):
        self.assertEqual(clean_term("and Tango & Cash"), "Tango & Cash")
        self.assertEqual(clean_term("25l"), "25I")


if __name__ == "__main__":
    unittest.main()
