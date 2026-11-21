"""CZ 层测试：Q15 两张窄表折进 ETL + 「重跑后无组件产品仍 1,424」。

- 纯函数测试不碰库；
- 集成测试只读打开 `data/drugs.db`（mode=ro）+ 快照 ZIP + Q6 manifest，把
  `substance` / `variant` 拷进内存库模拟 `cmd_apply` 的两段式（pending 新成分创建），
  **不写 data/drugs.db、不跑全量 ingest**。缺库 / 快照 / manifest 时 skip（CI 无库）。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))

import cz  # noqa: E402

DB = ROOT / "data" / "drugs.db"
Q6_MANIFEST = ROOT / "data" / "sources" / "cz_component_fill_manifest_20261118.json"
# 2026-11-18 Q6 写库后的验收线（报告 §5.2）；数据窗口再动 CZ 时同步更新这里。
# 2026-11-21 NO（DMP FEST）写库新增 361 个成分主档后，CZ 重跑计划能多匹配 15 个产品
# （+34 个成分行，走的是既有 strip_salt / 名称精确命中路径，不是 Q6 回退）；
# 2026-11-22 KR（HIRA 약가마스터）写库新增 2,544 个成分主档后，CZ 重跑计划再多匹配 141 个产品
# （+169 个成分行，同样走既有精确/去盐命中，不是 Q6 回退）。
# 下面改成「KR 窗口后的重跑计划」基线，并与现库用 ≤/≥ 比较：共享主档只会让计划多映射。
CZ_NO_COMPONENT = 1268
CZ_WITH_COMPONENT = 67313
CZ_COMPONENTS = 91184
# 现库（上一次 CZ 写库）口径，用于「不回退」比较
CZ_DB_NO_COMPONENT = 1424
CZ_DB_WITH_COMPONENT = 67157
CZ_DB_COMPONENTS = 90981


class NameMapTables(unittest.TestCase):
    """Q15 两张表本身：条数、精确命中、non-substance 不当 miss、目标 substance 存在。"""

    def test_table_sizes(self):
        self.assertEqual(len(cz.NAME_MAP), 15)
        self.assertEqual(len(cz.NON_SUBSTANCE), 15)

    def test_name_map_resolves_exactly(self):
        for name, (sid, why) in cz.NAME_MAP.items():
            with self.subTest(name=name):
                self.assertTrue(why.strip())
                self.assertEqual(cz._resolve_ingredient(name, {}, {}, {}),
                                 (sid, None, "name-map", None))

    def test_non_substance_is_ignored_not_miss(self):
        for name, why in cz.NON_SUBSTANCE.items():
            with self.subTest(name=name):
                self.assertTrue(why.strip())
                self.assertEqual(cz._resolve_ingredient(name, {}, {}, {}),
                                 (None, None, "non-substance", None))

    @unittest.skipUnless(DB.exists(), "没有 data/drugs.db")
    def test_name_map_targets_exist_in_db(self):
        con = cz.connect_ro(DB)
        try:
            ids = {r[0] for r in con.execute("SELECT substance_id FROM substance")}
        finally:
            con.close()
        missing = {sid for sid, _why in cz.NAME_MAP.values()} - ids
        self.assertEqual(missing, set(), f"NAME_MAP 目标成分不在库内：{sorted(missing)}")

    def test_q6_script_shares_the_same_tables(self):
        path = ROOT / "db" / "q6_cz_component_fill.py"
        if not path.exists():
            self.skipTest("q6 历史脚本不存在")
        spec = importlib.util.spec_from_file_location("q6_cz_component_fill", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # 只 import，不执行 CLI
        self.assertIs(mod.NAME_MAP, cz.NAME_MAP)
        self.assertIs(mod.NON_SUBSTANCE, cz.NON_SUBSTANCE)


@unittest.skipUnless(DB.exists() and cz.ZIP_PATH.exists() and Q6_MANIFEST.exists(),
                     "缺 data/drugs.db / CZ 快照 / Q6 manifest（CI 无库时跳过）")
class RerunKeepsQ6Fill(unittest.TestCase):
    """模拟 `cz.py --apply` 重跑：第一次 plan 收集 pending → 内存库建假成分 → 第二次 plan。"""

    @classmethod
    def setUpClass(cls) -> None:
        manifest = json.loads(Q6_MANIFEST.read_text(encoding="utf-8"))
        cls.manifest_ids = {r["product_id"] for r in manifest["rows"]}

        db = cz.connect_ro(DB)
        try:
            cls.db_no_component = db.execute(
                "SELECT COUNT(*) FROM product p WHERE p.country='CZ' AND NOT EXISTS"
                " (SELECT 1 FROM product_component pc WHERE pc.product_id=p.product_id)"
            ).fetchone()[0]
            cls.db_with_component = db.execute(
                "SELECT COUNT(DISTINCT pc.product_id) FROM product_component pc"
                " JOIN product p ON p.product_id=pc.product_id WHERE p.country='CZ'"
            ).fetchone()[0]
            cls.db_components = db.execute(
                "SELECT COUNT(*) FROM product_component pc JOIN product p"
                " ON p.product_id=pc.product_id WHERE p.country='CZ'"
            ).fetchone()[0]
            who = cz.load_who_inn()
            first = cz.build_plan(db, who)
            cls.first_stats = first["stats"]
            cls.first_pending = first["pending_new"]
            pending = first["pending_new"]

            mem = sqlite3.connect(":memory:")
            mem.row_factory = sqlite3.Row
            mem.execute("CREATE TABLE substance (substance_id TEXT PRIMARY KEY, inn_en TEXT)")
            mem.execute("CREATE TABLE variant (variant_id TEXT PRIMARY KEY,"
                        " substance_id TEXT, salt_code TEXT)")
            mem.executemany("INSERT INTO substance VALUES (?,?)",
                            db.execute("SELECT substance_id, inn_en FROM substance"))
            mem.executemany("INSERT INTO variant VALUES (?,?,?)",
                            db.execute("SELECT variant_id, substance_id, salt_code FROM variant"))
            new_map: dict[str, list[str]] = {}
            for i, key in enumerate(sorted(pending)):
                sid, vid = f"sim-sub-{i}", f"sim-var-{i}"
                mem.execute("INSERT INTO substance VALUES (?,?)", (sid, pending[key][0]))
                mem.execute("INSERT INTO variant VALUES (?,?,?)", (vid, sid, ""))
                new_map[key] = [sid, vid]
            mem.commit()
            cls.plan = cz.build_plan(mem, who, new_map)
            mem.close()
        finally:
            db.close()

    def test_rerun_keeps_cz_no_component_at_1268(self):
        no_comp = sum(1 for p in self.plan["products"] if not p["components"])
        with_comp = sum(1 for p in self.plan["products"] if p["components"])
        self.assertEqual(no_comp, CZ_NO_COMPONENT,
                         "重跑 CZ 后无组件产品数变了（数据窗口改过就同步期望值）")
        self.assertEqual(with_comp, CZ_WITH_COMPONENT)
        # 重跑计划 vs 现库：NO 窗口新增的成分主档会让计划多映射（≥），但绝不回退
        # （Q6 的 684 个产品由 test_all_q6_filled_products_keep_components 单独保证）。
        self.assertEqual(self.db_no_component, CZ_DB_NO_COMPONENT)
        self.assertEqual(self.db_with_component, CZ_DB_WITH_COMPONENT)
        self.assertEqual(self.db_components, CZ_DB_COMPONENTS)
        self.assertLessEqual(no_comp, self.db_no_component,
                             "重跑计划的无组件产品不应多于现库（共享主档只会补映射）")
        self.assertGreaterEqual(with_comp, self.db_with_component)
        self.assertGreaterEqual(self.plan["stats"]["components"], self.db_components)
        self.assertEqual(self.plan["stats"]["components"], CZ_COMPONENTS)
        self.assertEqual(self.plan["stats"]["products_components_skipped"], 1265)
        self.assertEqual(self.plan["stats"]["products_without_ingredient"], 3)

    def test_all_q6_filled_products_keep_components(self):
        plan_ids = {p["product_id"] for p in self.plan["products"] if p["components"]}
        missing = self.manifest_ids - plan_ids
        self.assertEqual(len(self.manifest_ids), 684)
        self.assertEqual(missing, set(), f"重跑会回退 Q6 的 {len(missing)} 个产品")

    def test_non_substance_names_are_dropped_not_pending(self):
        # ② 的名字不能再被 new_substance_name 建成新成分（Q15 前会走 pending 分支）
        self.assertGreater(self.first_stats["skip_non_substance_name"], 0,
                           "non-substance 名字应被摘掉并计数")
        for name in cz.NON_SUBSTANCE:
            key = cz.norm_inn(name)
            base = cz.strip_salt(key) or key
            with self.subTest(name=name):
                self.assertNotIn(key, self.first_pending)
                self.assertNotIn(base, self.first_pending)


if __name__ == "__main__":
    unittest.main()
