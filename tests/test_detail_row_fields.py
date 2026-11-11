"""明细面板列下标契约：必须来自 ROW_FIELDS，不许手写数字。

2026-11-12 P0-2（v0.11.2）：``detPanelHTML()`` 把「品牌」列写成 ``r[3]``，而
``etl/build_detail_buckets.py`` 的 ROW_FIELDS 里 [3] 是 pack → 382,035 条明细行中
232,353 条（60.8%）的「品牌」列显示成包装原文（``1 BOTTLE…`` / ``2/50/100…``），
另有 138,460 条被误显示成「无商品名」。

本测试锁三件事（防第三次踩：v0.6.1 补 ``e.f`` 时已踩过一次同类漂移）：
1. ROW_FIELDS 的语义（brand=2 / pack=3，12 列）；
2. build.py 从 ROW_FIELDS 读字段表并注入 app.js，前端用 ``DETAIL_COL.brand/.pack`` 取名；
3. ``detPanelHTML()`` 里不许再出现 ``brandCell = r[<数字>]`` 这种硬编码。

单独跑：``python -m unittest tests.test_detail_row_fields -v``
"""
from __future__ import annotations

import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ETL = ROOT / "etl" / "build_detail_buckets.py"
BUILD = ROOT / "site" / "build.py"


def row_fields() -> list[str]:
    """按 etl/build_detail_buckets.py 的源码解析 ROW_FIELDS（不导入 ETL 进程）。"""
    src = ETL.read_text(encoding="utf-8")
    m = re.search(r"^ROW_FIELDS\s*=\s*\[(.*?)\]", src, re.S | re.M)
    if not m:
        raise AssertionError("etl/build_detail_buckets.py 里找不到 ROW_FIELDS")
    return [part.strip().strip("\"'") for part in m.group(1).replace("\n", " ").split(",")
            if part.strip()]


def build_src() -> str:
    return BUILD.read_text(encoding="utf-8")


def det_panel_js(src: str | None = None) -> str:
    """截出 APP_JS 里 detPanelHTML() 的函数体（到下一个顶层 function 前）。"""
    s = src if src is not None else build_src()
    m = re.search(r"function detPanelHTML\(.*?\n\}\n", s, re.S)
    if not m:
        raise AssertionError("site/build.py 里找不到 detPanelHTML()")
    return m.group(0)


def load_build_module():
    """只导入常量/函数，不跑 main()（构建脚本 py 文件无 __main__ 副作用）。"""
    spec = importlib.util.spec_from_file_location("site_build_detail_fields", BUILD)
    if spec is None or spec.loader is None:
        raise AssertionError("无法加载 site/build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DetailRowFieldsTest(unittest.TestCase):
    def test_row_fields_contract(self) -> None:
        fields = row_fields()
        self.assertEqual(len(fields), 12, f"ROW_FIELDS 列数变了：{fields}")
        self.assertEqual(fields.index("brand"), 2, "brand 不在第 2 列：明细面板品牌列会错位")
        self.assertEqual(fields.index("pack"), 3, "pack 不在第 3 列：包装列约定变了")
        self.assertEqual(fields.index("country"), 1)
        self.assertEqual(fields.index("mah"), 9)

    def test_build_reads_row_fields_from_etl(self) -> None:
        src = build_src()
        self.assertRegex(
            src,
            re.compile(r"def _detail_row_fields\(\).*?build_detail_buckets\.py", re.S),
            "build.py 没有从 etl/build_detail_buckets.py 读 ROW_FIELDS",
        )
        self.assertIn("DETAIL_ROW_FIELDS = _detail_row_fields()", src)
        self.assertIn('replace("__DETAIL_ROW_FIELDS__", json.dumps(DETAIL_ROW_FIELDS', src,
                      "APP_JS 里的字段表占位符没有被替换成 ROW_FIELDS")

    def test_build_helper_matches_etl(self) -> None:
        module = load_build_module()
        self.assertEqual(list(module.DETAIL_ROW_FIELDS), row_fields())

    def test_det_panel_uses_named_columns(self) -> None:
        js = det_panel_js()
        self.assertIn("DETAIL_COL.brand", js, "品牌列没有用 DETAIL_COL.brand")
        self.assertIn("DETAIL_COL.pack", js, "包装列没有用 DETAIL_COL.pack")
        self.assertIsNone(
            re.search(r"brandCell\s*=\s*r\[\d+\]", js),
            "detPanelHTML() 里又出现了 brandCell = r[数字] 的硬编码",
        )
        # 注入到 app.js 的两列下标与 ROW_FIELDS 一致
        fields = row_fields()
        self.assertEqual(fields.index("brand"), 2)
        self.assertEqual(fields.index("pack"), 3)

    def test_placeholder_replaced_in_app_js_recipe(self) -> None:
        """app.js 的写出路径必须消费字段表占位符（缺了它前端拿到的是 __DETAIL_ROW_FIELDS__）。"""
        src = build_src()
        self.assertIn("__DETAIL_ROW_FIELDS__", src)
        self.assertRegex(
            src,
            r'\(OUT / "assets" / "app\.js"\)\.write_text\([\s\S]{0,400}__DETAIL_ROW_FIELDS__',
            "app.js 写出时没有替换 __DETAIL_ROW_FIELDS__",
        )

    def test_core_fields_carry_trade_flags(self) -> None:
        """P0-1 同批：core 列清单必须含 t / nc / eo（漏了会让 85% 结果行走「无商品名」）。"""
        src = build_src()
        m = re.search(r"^CORE_FIELDS = \((.*?)\)", src, re.S | re.M)
        self.assertIsNotNone(m, "site/build.py 里没有 CORE_FIELDS 常量")
        fields = {part.strip().strip("\"'") for part in m.group(1).replace("\n", " ").split(",")}
        for name in ("t", "nc", "eo"):
            self.assertIn(name, fields, f"core 字段清单缺 {name}")
        self.assertIn("encode_core 漏字段", src, "encode_core() 缺漏列守卫")


if __name__ == "__main__":
    unittest.main()
