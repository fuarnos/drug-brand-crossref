"""P0-3 别名闸门回归测试（整句 / 说明文字 / 剂型尾缀 / 两名挤一格）。

运行：python -m unittest discover -s etl -t etl
背景：reports/2026-11-12-p0-3-alias-cleanup.md（用户走查「也叫」里出现整句）。
金值：45 行脏样本全拦；候选 CSV 1108 行上 core 拦 64 / extended 拦 67。
"""

from __future__ import annotations

import unittest

from alias_rules import (
    SELF_CHECK_CANDIDATE_GOLDEN,
    SELF_CHECK_JUNK,
    SELF_CHECK_KEEP,
    alias_junk_reason,
    self_check,
)
from extract_cn_slang import is_junk_term


class TestAliasRules(unittest.TestCase):
    def test_core_rules_coverage(self):
        """45 行脏样本必须全部被拦（用户点名的三条也在里面）。"""
        self.assertEqual(len(SELF_CHECK_JUNK), 45)
        missed = [t for t in SELF_CHECK_JUNK if not alias_junk_reason(t)]
        self.assertEqual(missed, [], f"未拦住：{missed}")

    def test_legit_aliases_pass(self):
        """合法叫法不能被误杀，尤其是含「的松」的糖皮质激素。"""
        bad = [(t, alias_junk_reason(t)) for t in SELF_CHECK_KEEP if alias_junk_reason(t)]
        self.assertEqual(bad, [], f"误杀：{bad}")

    def test_user_reported_samples(self):
        """用户 2026-11-11 走查点名的三条 + 同源整句。"""
        for t in ("宣传自己的商品", "生产厂家为突出", "硫酸氢氯吡格雷片是波立维",
                  "可以说都很低调", "无环鸟苷的阿昔洛韦", "多潘立酮或吗丁啉"):
            self.assertTrue(alias_junk_reason(t), f"{t} 应被拦")

    def test_inline_judgement_not_line_start(self):
        """P0-3 的直接修复点：句中「是/为/的」也要拦，不是只看行首。"""
        self.assertTrue(alias_junk_reason("他达拉非是药品"))
        self.assertTrue(alias_junk_reason("生产厂家为突出"))
        self.assertTrue(alias_junk_reason("瑞舒伐他汀的"))
        # 行首那三个 ^ 锚点已经删掉（留着就是「句中放行」的原因）
        self.assertFalse(alias_junk_reason("强的松"))
        self.assertFalse(alias_junk_reason("醋酸可的松"))

    def test_extract_gate_delegates(self):
        """抽取侧闸门 is_junk_term() 必须与 alias_rules 同口径。"""
        for t in SELF_CHECK_JUNK:
            self.assertTrue(is_junk_term(t, ""), f"extract 未拦：{t}")
        self.assertFalse(is_junk_term("强的松", ""))
        self.assertFalse(is_junk_term("泰诺", ""))

    def test_cross_ingredient_combo(self):
        """成分名组合规则：只对「够长且含别的成分名」的写法生效，短名/母体不误杀。"""
        names = frozenset({"阿昔洛韦", "四环素", "葡萄糖"})
        self.assertTrue(alias_junk_reason("无环鸟苷的阿昔洛韦", other_ingredient_names=names))
        self.assertEqual(alias_junk_reason("二甲胺四环素", other_ingredient_names=names), "")
        self.assertEqual(alias_junk_reason("葡萄糖胺", other_ingredient_names=names), "")

    def test_candidate_csv_golden(self):
        """候选 CSV 上的拦截数（CSV 重新生成后要改 alias_rules 里的金值并写进报告）。"""
        fails = self_check(verbose=False)
        golden = [f for f in fails if "候选 CSV" in f]
        self.assertEqual(golden, [], f"候选 CSV 金值不符（期望 {SELF_CHECK_CANDIDATE_GOLDEN}）：{golden}")


if __name__ == "__main__":
    unittest.main()
