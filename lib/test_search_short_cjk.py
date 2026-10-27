"""中文短查询检索回归测试（P0：幽灵 exact / 中文 contains 门槛）。

背景（reports/trilingual-query-tests.md，task-19）：
- 旧 `_resolve_keys()` 无条件把查询本身当 exact key，不校验该 key 是否在库里；
  中文 3 字通用名（库里真实 key 常是「盐酸舍曲林片」这类盐型前缀长名）
  会得到一个不存在的 key → 0 结果，还提示「名字对上了，但没有在售产品」。
- contains 分支对中文沿用英文的 len>=4 门槛，2–3 字中文名被挡在门外。

修复后约定（与站点客户端 v0.2.1 `tier()` 的 `cjk ? 2 : 4` 一致）：
- exact 只认库里真实存在的 name_key；
- 中文 contains 最短 2 字；拉丁仍 4 字；模糊匹配仍 4 字起。

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
    ("sertraline", "Sertraline", "舍曲林"),
    ("fluoxetine", "Fluoxetine", "氟西汀"),
    ("quetiapine", "Quetiapine", "喹硫平"),
    ("amlodipine", "Amlodipine", "氨氯地平"),
    ("atorvastatin", "Atorvastatin", "阿托伐他汀"),
    ("sildenafil", "Sildenafil", "西地那非"),
]

# (pid, country, brand, comp substance, strength) —— 品牌名 = 中文长名（盐型+剂型前缀），
# 刻意让「舍曲林」不是任何 key 的前缀，只能靠 contains 命中。
PRODUCTS = [
    ("CN-sertraline", "CN", "盐酸舍曲林片", "sertraline", 50.0),
    ("CN-fluoxetine", "CN", "盐酸氟西汀胶囊", "fluoxetine", 20.0),
    ("CN-quetiapine", "CN", "富马酸喹硫平片", "quetiapine", 25.0),
    ("CN-amlodipine", "CN", "苯磺酸氨氯地平片", "amlodipine", 5.0),
    ("CN-amlodipine2", "CN", "苯磺酸氨氯地平分散片", "amlodipine", 5.0),
    ("US-lipitor", "US", "Lipitor", "atorvastatin", 20.0),
    ("US-atorvastatin", "US", "atorvastatin", "atorvastatin", 10.0),
    ("CN-viagra", "CN", "万艾可", "sildenafil", 50.0),
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

    for pid, country, brand, sub, strength in PRODUCTS:
        db.execute(
            "INSERT INTO product (product_id, country, dosage_form, form_base, route,"
            " release, is_branded, status, source_id, retrieved_at)"
            " VALUES (?,?,?,?,?,?,1,'active','test','2026-01-01')",
            (pid, country, "tablet", "tablet", "oral", "none"))
        db.execute(
            "INSERT INTO product_component (product_id, ord, variant_id,"
            " strength_value, strength_unit) VALUES (?,0,?,?, 'mg')",
            (pid, sub, strength))
        n = normalize(brand)
        db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                   " VALUES (?,?,?,?)", (n.norm, n.norm, n.compact, n.script))
        db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                   " VALUES (?,?, 'test')", (n.norm, brand))
        db.execute("INSERT INTO product_name (product_id, key_id, name_type, is_primary)"
                   " VALUES (?,?, 'trade', 1)", (pid, n.norm))

    # 俗称路径：2 字中文别名仍应先走 alias（不被短查询规则影响）
    db.execute(
        "INSERT INTO nickname (substance_id, alias, alias_norm, label_zh, kind,"
        " confidence, source, note, created_at)"
        " VALUES ('sildenafil','伟哥','伟哥','西地那非','slang','community',"
        " 'test','中文网络通行叫法','2026-01-01')")
    db.commit()
    db.close()


class ShortCjkSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = ROOT / ".tmp" / "test-search-short-cjk"
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        cls.tmpdir.mkdir(parents=True, exist_ok=True)
        cls.db_path = cls.tmpdir / "t.db"
        build_fixture(cls.db_path)
        cls.idx = SearchIndex(cls.db_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.idx.close()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    # --- 1) 3 字中文通用名：不能是幽灵 exact，必须 contains 到盐型长 key -------------
    def test_three_char_generic_hits_salt_prefixed_key(self):
        for query, expected_key, expected_sub in (
            ("舍曲林", "盐酸舍曲林片", "Sertraline"),
            ("氟西汀", "盐酸氟西汀胶囊", "Fluoxetine"),
            ("喹硫平", "富马酸喹硫平片", "Quetiapine"),
        ):
            res = self.idx.search(query)
            self.assertTrue(res.cards, f"{query} 应有结果")
            self.assertEqual(res.cards[0].key_id, expected_key, query)
            self.assertIn(expected_sub, res.cards[0].substances, query)
            self.assertNotEqual(res.note, "名字对上了，但没有在售产品",
                                f"{query} 不应出现幽灵 exact 的误导提示")

    def test_exact_tier_requires_real_key(self):
        # 舍曲林 不在 name_key 里：resolved keys 必须全是真实 key，且 tier 不是 exact
        keys = self.idx._resolve_keys(normalize("舍曲林"))
        self.assertEqual([k for k, _t in keys], ["盐酸舍曲林片"])
        self.assertEqual(keys[0][1], "contains")
        self.assertNotIn("舍曲林", dict(keys))

    def test_unknown_cjk_name_is_honest(self):
        # 库里没有「埃索美拉唑」（只有通用的艾司奥美拉唑）→ 明确说没有匹配，而不是假的 exact
        res = self.idx.search("埃索美拉唑")
        self.assertTrue(res.empty)
        self.assertEqual(res.note, "没有匹配的名字")
        self.assertEqual(res.total_keys, 0)

    # --- 2) 2 字中文 contains（与站点客户端 cjk?2:4 一致）-------------------------
    def test_two_char_cjk_contains(self):
        res = self.idx.search("地平")
        self.assertTrue(res.cards)
        keys = {c.key_id for c in res.cards}
        self.assertTrue(any("氨氯地平" in k for k in keys), keys)

        res2 = self.idx.search("氨氯")
        self.assertTrue(res2.cards)
        self.assertTrue(any("氨氯地平" in c.key_id for c in res2.cards))

    def test_two_char_cjk_prefix_still_works(self):
        # 本身是 key 前缀的 2 字查询仍走 prefix，不因新门槛变差
        keys = dict(self.idx._resolve_keys(normalize("盐酸")))
        self.assertIn("盐酸舍曲林片", keys)
        self.assertIn("盐酸氟西汀胶囊", keys)

    def test_one_char_cjk_does_not_contains(self):
        # 1 字不进入 contains（避免噪声）；本夹具里没有以「地」开头的 key → 应无结果
        res = self.idx.search("地")
        self.assertEqual(res.total_keys, 0)
        self.assertEqual(res.note, "没有匹配的名字")

    # --- 3) 拉丁行为不回归 ------------------------------------------------------
    def test_latin_contains_threshold_unchanged(self):
        # 4 字拉丁 contains 有效（"tati" 在 "atorvastatin" 里）；3 字不进入 contains
        self.assertTrue(self.idx.search("tati").cards)
        res = self.idx.search("tat")
        self.assertEqual(res.total_keys, 0)
        self.assertEqual(res.note, "没有匹配的名字")

    def test_latin_exact_and_fuzzy_unchanged(self):
        res = self.idx.search("Lipitor")
        self.assertEqual(res.cards[0].tier, "exact")
        # 4 字以上仍可 fuzzy（拼错一个字符）
        res2 = self.idx.search("atorvastatni")
        self.assertTrue(res2.cards)
        self.assertEqual(res2.cards[0].tier, "fuzzy")

    def test_short_cjk_no_fuzzy(self):
        # 3 字中文拼错不做 fuzzy 扩展（与客户端一致：fuzzy 需 4 字以上）
        res = self.idx.search("舍曲宁")
        self.assertEqual(res.total_keys, 0)
        self.assertEqual(res.note, "没有匹配的名字")

    # --- 4) 俗称路径不受影响（alias 在 _resolve_keys 之前）-------------------------
    def test_two_char_nickname_still_resolves(self):
        res = self.idx.search("伟哥")
        self.assertTrue(res.cards)
        self.assertEqual(res.alias["substance_id"], "sildenafil")
        self.assertEqual(res.cards[0].tier, "nickname")


if __name__ == "__main__":
    unittest.main()
