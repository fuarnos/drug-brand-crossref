"""P0-3 删除清单读取的回归测试（两种列格式都要能执行）。

运行：python -m unittest discover -s etl -t etl
背景：`data/alias_cleanup_removals.csv`（审计格式：id,term,source,…）与
`data/drug_term_removals.csv`（执行格式：id,table,alias,…）列名不同，
`clean_drug_terms.py` 必须两种都能读，否则 DB 窗口会「45 行全部跳过」。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from clean_drug_terms import load_removals

ROOT = Path(__file__).resolve().parents[1]


class TestLoadRemovals(unittest.TestCase):
    def test_execution_format(self):
        rows = load_removals(ROOT / "data" / "drug_term_removals.csv")
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(r["table"] in ("drug_term", "nickname") for r in rows))
        self.assertTrue(all(r["alias"] for r in rows))

    def test_audit_format_maps_term_to_alias(self):
        path = ROOT / "data" / "alias_cleanup_removals.csv"
        if not path.exists():
            self.skipTest("data/alias_cleanup_removals.csv 不存在")
        rows = load_removals(path)
        self.assertEqual(len(rows), 45)
        self.assertTrue(all(r["alias"] for r in rows))
        # 审计格式没有 table 列 → 'auto'，由 plan() 用 id+别名唯一匹配决定
        self.assertTrue(all(r["table"] == "auto" for r in rows))
        self.assertIn("宣传自己的商品", {r["alias"] for r in rows})


if __name__ == "__main__":
    unittest.main()
