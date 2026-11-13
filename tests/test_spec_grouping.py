"""T10（v0.11.6）：规格串 / 分组键 / 复方行 / 冲突徽标 的纯函数契约。

背景（用户评审 §1.1–§1.5，`reports/2026-11-14-t10-grouping-plan.md`）：
- `960 mg/30 mL` 不能被缩成 `960 mg`，也不能让一个「片剂」标签代表一瓶液体；
- `499.9996 mg` 这类 TGA 换算残渣只在显示层归整，**数据层一个字节都不改**；
- 复方行要能列出「全部活性成分 + 各自含量」，但不做换算、不求和、不判断能否互换；
- 名称-规格冲突徽标只做机制，v0.11.6 **默认关闭**（T15 清单约 9 成是基准差）。

单独跑：`python -m unittest tests.test_spec_grouping -v`
"""
from __future__ import annotations

import importlib.util
import os
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "site" / "build.py"


def _load_build():
    """按文件路径导入 site/build.py（不跑 main()，只取纯函数）。"""
    spec = importlib.util.spec_from_file_location("dsh_site_build_t10", BUILD)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


B = _load_build()


class SpecTextTests(unittest.TestCase):
    """`_spec_text` / `_spec_kind`：全站唯一规格串（plan §3.1）。"""

    def test_plain_strength_unchanged(self) -> None:
        self.assertEqual(B._spec_text(500, "mg"), "500 mg")
        self.assertEqual(B._spec_text(1, "g"), "1000 mg")
        self.assertEqual(B._spec_text(None, "mg"), "")

    def test_per_volume_keeps_relation(self) -> None:
        """960 mg/30 mL 不许缩成 960 mg（用户评审 §1.2 的核心靶点）。"""
        self.assertEqual(B._spec_text(960, "mg", 30, "mL"), "960 mg/30 mL")
        self.assertEqual(B._spec_text(0.4, "mg", 1, "tablet"), "0.4 mg/1 tablet")
        self.assertEqual(B._spec_text(7, "mg", 24, "h"), "7 mg/24 h")

    def test_kind_classification(self) -> None:
        self.assertEqual(B._spec_kind("mL"), "volume")
        self.assertEqual(B._spec_kind("L"), "volume")
        self.assertEqual(B._spec_kind("mg"), "mass")
        self.assertEqual(B._spec_kind("h"), "time")
        self.assertEqual(B._spec_kind("tablet"), "count")
        self.assertEqual(B._spec_kind(""), "count")


class SnapStrengthTests(unittest.TestCase):
    """`_snap_strength`：窄口归整（plan §4.1 / §4.3 反例保护）。"""

    def test_conversion_noise_snaps(self) -> None:
        for raw in ("499.9996", "499.9995", "500.0003", "500.0053", "500.0081", "500.0082"):
            self.assertEqual(B._normalized_strength(Decimal(raw), "mg"), "500 mg", raw)

    def test_real_decimals_untouched(self) -> None:
        """0.00025 不能被抹成 0；469.01 / 100.008 不能被贴成整数。"""
        for raw in ("0.00025", "0.008", "0.0001"):
            self.assertNotEqual(B._normalized_strength(Decimal(raw), "mg"), "0 mg", raw)
        self.assertEqual(B._normalized_strength(Decimal("469.01"), "mg"), "469.01 mg")
        self.assertEqual(B._normalized_strength(Decimal("100.008"), "mg"), "100.008 mg")
        # 未归整时保持原来的千分位写法（不做顺手格式化）
        self.assertEqual(B._normalized_strength(Decimal("666666.666667"), "mg"),
                         "666,666.666667 mg")

    def test_snap_needs_both_thresholds(self) -> None:
        self.assertEqual(B._snap_strength(Decimal("499.9996")), Decimal("500"))
        self.assertEqual(B._snap_strength(Decimal("469.01")), Decimal("469.01"))
        self.assertEqual(B._snap_strength(Decimal("0.9999")), Decimal("0.9999"))


class SortKeyTests(unittest.TestCase):
    """`_spec_num` / `_sort_strength`：同一口径，认千分位与科学计数（plan §3.4 排序）。"""

    def test_thousands_separator(self) -> None:
        self.assertEqual(B._spec_num("1,000,000 IU"), 1000000.0)
        self.assertEqual(B._spec_num("1.23e+06 mg"), 1230000.0)
        self.assertEqual(B._spec_num("960 mg/30 mL"), 960.0)

    def test_sort_strength_delegates(self) -> None:
        for text in ("1,000 mg", "500 mg", "0.5 mg", ""):
            self.assertEqual(B._sort_strength(text), B._spec_num(text), text)


class ComboLineTests(unittest.TestCase):
    """复方行「全部成分 + 各自含量」：只列事实（plan §5.2）。"""

    def test_lists_every_ingredient_with_its_amount(self) -> None:
        html = B._combo_line_html(
            [("acetaminophen", "325 mg"), ("oxycodone", "5 mg")],
            {"acetaminophen": ("Acetaminophen", "对乙酰氨基酚"),
             "oxycodone": ("Oxycodone", "羟考酮")})
        self.assertIn("Acetaminophen", html)
        self.assertIn("325 mg", html)
        self.assertIn("Oxycodone", html)
        self.assertIn("5 mg", html)
        self.assertIn("对乙酰氨基酚", html)
        self.assertIn(" + ", html)
        # 红线：不给换算 / 求和 / 替代判断
        for banned in ("合计", "总量", "换算", "替代", "等效"):
            self.assertNotIn(banned, html)

    def test_missing_strength_does_not_crash(self) -> None:
        self.assertIn("Zinc", B._combo_line_html([("zinc", "")], {"zinc": ("Zinc", "")}))


class SpecConflictTests(unittest.TestCase):
    """名称-规格冲突：默认关闭（Lead 2026-11-14 收紧范围）。"""

    def test_default_off_renders_nothing(self) -> None:
        self.assertEqual(B.load_spec_conflicts(enabled=False), {})
        self.assertEqual(B._spec_conflict_badge(("500 mg", "tablet", "none", ""), {}, {}), "")

    def test_enabled_badge_keeps_value_and_sort_untouched(self) -> None:
        spec = ("250 mg", "tablet", "none", "")
        html = B._spec_conflict_badge(
            spec, {spec: "1000 MG"}, {"matrix.spec_conflict": "strength unverified"})
        self.assertIn('data-i18n="matrix.spec_conflict"', html)
        self.assertIn('data-spec-conflict="1000 MG"', html)
        self.assertIn("strength unverified", html)
        # 数值原样：徽标不许改规格串
        self.assertNotIn("1000 mg", html)

    def test_env_switch(self) -> None:
        old = os.environ.pop("SPEC_CONFLICT", None)
        try:
            self.assertEqual(B.load_spec_conflicts(), {})
        finally:
            if old is not None:
                os.environ["SPEC_CONFLICT"] = old


class IndexFieldTests(unittest.TestCase):
    """索引/core 的字段契约：新增 fs 必须同时进 CORE_FIELDS 与 CORE_ARRAY_COLS。"""

    def test_fs_declared_in_core_contract(self) -> None:
        self.assertIn("fs", B.CORE_FIELDS)
        self.assertIn("fs", B.CORE_ARRAY_COLS)

    def test_fs_pack_compact_and_capped(self) -> None:
        """`fs` 只写多剂型条目；紧凑串带剂型；组/规格都有上限（体积护栏）。"""
        one = B._fs_pack({"tablet": ["500 mg"]})
        self.assertIsNone(one, "单剂型不该写 fs（用 s + f 回退）")
        self.assertIsNone(B._fs_pack({}))
        multi = B._fs_pack({
            "tablet": ["500 mg", "325 mg", "1000 mg", "200 mg"],
            "liquid": ["960 mg/30 mL"],
            "capsule": ["500 mg"],
            "powder": ["500 mg/950 mg"],
        })
        self.assertEqual(multi[0], "tablet|500 mg;325 mg;1000 mg")
        self.assertLessEqual(len(multi), 3)
        self.assertIn("liquid|960 mg/30 mL", multi)
        self.assertNotIn("powder|500 mg/950 mg", multi)

    def test_multi_form_sentinel_used(self) -> None:
        """多剂型时 f 写 "multi"，客户端据此显示「多剂型」而不是第一个剂型。"""
        src = BUILD.read_text(encoding="utf-8")
        self.assertIn('"multi" if len([fm for fm in a["fs"] if fm]) > 1', src)
        self.assertIn("matrix.multi_form", src)
        # 客户端按紧凑串解析（剂型|规格;规格）
        self.assertIn("specPairsOf", src)
        self.assertIn("s.indexOf('|')", src)


if __name__ == "__main__":
    unittest.main()
