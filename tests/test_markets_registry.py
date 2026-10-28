"""市场/语言注册表测试（docs/市场扩展接口.md 的验收门槛）。

运行（仓库根目录）：

    & $py -m unittest tests.test_markets_registry -v

覆盖：
    - data/markets.json / data/languages.json 结构、字段、格式、唯一性；
    - 现有 7 市场 + TW 占位 + EU region 占位（disabled）；
    - en/es/zh 启用、zh-Hant 预留、EU 语言占位（disabled）；
    - source_id 与 DB source 表一致、enabled 市场与国家集合 = DB product.country 集合；
    - 语言默认国家/默认语言交叉一致性；
    - dummy 市场/语言可注册（`with_market` / `with_language`）且不报错；
    - 非法注册会被拒绝（重复/坏 flag/未知 source/未知 parent/bad script…）；
    - lib/markets.py CLI；docs/市场扩展接口.md 关键段落存在。

只读：不写 DB、不写注册表、不跑 site/build.py。
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import markets as M  # noqa: E402

MARKETS_JSON = ROOT / "data" / "markets.json"
LANGUAGES_JSON = ROOT / "data" / "languages.json"
DOCS = ROOT / "docs" / "市场扩展接口.md"
DB = ROOT / "data" / "drugs.db"

# 现有站点（site/build.py 的 LANGS 与 i18n home.* key），注册表必须覆盖且不改其语义。
SITE_LANGS = {("en", ""), ("es", "es/"), ("zh", "zh/")}
SITE_COUNTRY_I18N = {"US", "GB", "CN", "ES", "MX", "AU", "CA"}


def _db_countries() -> set[str] | None:
    if not DB.exists():
        return None
    import sqlite3
    uri = "file:" + str(DB.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        return {r[0] for r in con.execute("SELECT DISTINCT country FROM product")}
    finally:
        con.close()


class RegistryBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw_markets = json.loads(MARKETS_JSON.read_text(encoding="utf-8"))
        cls.raw_languages = json.loads(LANGUAGES_JSON.read_text(encoding="utf-8"))
        cls.source_ids = M.db_source_ids(DB)
        cls.reg = M.MarketsRegistry.load(source_ids=cls.source_ids)
        cls.db_countries = _db_countries()

    # --- 小工具 ---
    def market_dict(self, code: str = "US") -> dict:
        return cls_raw(self.raw_markets["markets"], code)

    def language_dict(self, code: str = "en") -> dict:
        return cls_raw(self.raw_languages["languages"], code)


def cls_raw(items: list[dict], code: str) -> dict:
    for row in items:
        if row["code"] == code:
            return dict(row)
    raise AssertionError(f"注册表里没有 {code}")


class TestJsonStructure(RegistryBase):
    def test_files_and_schema_version(self) -> None:
        self.assertTrue(MARKETS_JSON.exists())
        self.assertTrue(LANGUAGES_JSON.exists())
        for raw in (self.raw_markets, self.raw_languages):
            self.assertIsInstance(raw.get("schema_version"), int)
            self.assertGreaterEqual(raw["schema_version"], 1)
            self.assertTrue(raw.get("updated"))
            self.assertTrue(raw.get("description"))

    def test_required_fields_present(self) -> None:
        for row in self.raw_markets["markets"]:
            missing = [k for k in M.REQUIRED_MARKET_FIELDS if k not in row]
            self.assertFalse(missing, f"市场 {row.get('code')} 缺 {missing}")
            self.assertIsInstance(row["name"], dict)
            for lang in ("en", "es", "zh"):
                self.assertTrue((row["name"].get(lang) or "").strip(),
                                f"市场 {row['code']} 缺 name.{lang}")
            self.assertIsInstance(row["languages"], list)
            self.assertIsInstance(row["enabled"], bool)
            self.assertIsInstance(row["order"], int)
        for row in self.raw_languages["languages"]:
            missing = [k for k in M.REQUIRED_LANGUAGE_FIELDS if k not in row]
            self.assertFalse(missing, f"语言 {row.get('code')} 缺 {missing}")
            for lang in ("en", "es", "zh"):
                self.assertTrue((row["name"].get(lang) or "").strip(),
                                f"语言 {row['code']} 缺 name.{lang}")

    def test_registry_is_valid(self) -> None:
        errs = self.reg.validate()
        self.assertEqual([], errs, "注册表校验失败:\n" + "\n".join(errs))

    def test_known_top_level_keys(self) -> None:
        self.assertIn("markets", self.raw_markets)
        self.assertIn("languages", self.raw_languages)
        self.assertIn("planned_markets", self.raw_languages)


class TestMarkets(RegistryBase):
    def test_registered_market_set(self) -> None:
        codes = set(self.reg.markets)
        self.assertEqual({"US", "GB", "CA", "AU", "ES", "MX", "CN", "TW", "EU"}, codes)
        self.assertEqual({"US", "GB", "CA", "AU", "ES", "MX", "CN"}, set(self.reg.country_order))
        self.assertEqual({"US", "GB", "CA", "AU", "ES", "MX", "CN"},
                         {m.code for m in self.reg.enabled_markets})
        self.assertEqual(("EU",), self.reg.region_codes)

    def test_market_required_shape(self) -> None:
        for m in self.reg.markets.values():
            self.assertRegex(m.code, r"^[A-Z]{2,3}$")
            self.assertIn(m.kind, (M.KIND_COUNTRY, M.KIND_REGION))
            self.assertGreater(m.order, 0)
            self.assertIn(m.group, M.ALLOWED_GROUPS)
            if m.enabled:
                self.assertTrue(m.source_id)
                self.assertRegex(m.i18n_key, r"^home\.[a-z0-9_]+$")
                self.assertEqual({*m.languages, m.default_lang}, set(m.languages))

    def test_orders_unique(self) -> None:
        orders = [m.order for m in self.reg.markets.values()]
        self.assertEqual(len(orders), len(set(orders)))

    def test_flags_are_regional_indicator_pairs(self) -> None:
        for m in self.reg.markets.values():
            self.assertEqual(2, len(m.flag), f"{m.code} flag 长度")
            for ch in m.flag:
                self.assertTrue(0x1F1E6 <= ord(ch) <= 0x1F1FF, f"{m.code} flag 字符非法")
        flags = [m.flag for m in self.reg.markets.values()]
        self.assertEqual(len(flags), len(set(flags)), "flag 不能重复")

    def test_i18n_keys_unique_and_match_existing_site_keys(self) -> None:
        keys = [m.i18n_key for m in self.reg.markets.values()]
        self.assertEqual(len(keys), len(set(keys)))
        for m in self.reg.enabled_markets:
            self.assertEqual(f"home.{m.code.lower()}", m.i18n_key)
        # 现有 7 国的 i18n key 与 site/build.py I18N 的 home.* 完全一致（只核对，不改 build）
        self.assertEqual({f"home.{c.lower()}" for c in SITE_COUNTRY_I18N},
                         {m.i18n_key for m in self.reg.enabled_markets})
        # 占位市场的 key 已预留，便于后续直接启用
        self.assertEqual("home.tw", self.reg.require_market("TW").i18n_key)
        self.assertEqual("home.eu", self.reg.require_market("EU").i18n_key)

    def test_enabled_market_sources_exist_in_db(self) -> None:
        if self.source_ids is None:
            self.skipTest("data/drugs.db 不存在，跳过 source 表校验")
        for m in self.reg.enabled_markets:
            self.assertIn(m.source_id, self.source_ids, f"{m.code} source_id 未登记")
            for sid in m.extra_source_ids:
                self.assertIn(sid, self.source_ids, f"{m.code} extra source {sid} 未登记")

    def test_enabled_markets_match_db_countries(self) -> None:
        if self.db_countries is None:
            self.skipTest("data/drugs.db 不存在，跳过国家集合校验")
        self.assertEqual(set(self.reg.country_order), self.db_countries,
                         "注册表启用国家与 DB product.country 不一致（改 DB 前先改注册表）")

    def test_parent_relationship(self) -> None:
        eu = self.reg.require_market("EU")
        self.assertTrue(eu.is_region)
        self.assertIsNone(eu.parent)
        self.assertFalse(eu.enabled)
        for code in self.reg.country_order:
            self.assertIsNone(self.reg.require_market(code).parent)
        # 若将来国家挂到 region 下，父节点必须是 region
        for m in self.reg.markets.values():
            if self.reg.market("EU") and m.parent == "EU":
                self.assertTrue(self.reg.require_market("EU").is_region)

    def test_region_placeholder_cannot_be_enabled_alone(self) -> None:
        # 手工构造「EU enabled 但没有子市场」的注册表 → 校验必须报错
        eu = self.reg.require_market("EU")
        markets = dict(self.reg.markets)
        markets["EU"] = M.Market(**{**eu.__dict__, "enabled": True})
        broken = M.MarketsRegistry(markets, self.reg.languages,
                                   source_ids=self.source_ids,
                                   planned_markets=self.reg.planned_markets)
        errs = broken.validate()
        self.assertTrue(any("region 至少要有 1 个启用的子市场" in e for e in errs), errs)

    def test_tw_is_planned_placeholder(self) -> None:
        tw = self.reg.require_market("TW")
        self.assertEqual(M.KIND_COUNTRY, tw.kind)
        self.assertFalse(tw.enabled)
        self.assertIsNone(tw.source_id)
        self.assertEqual("zh-Hant", tw.default_lang)
        self.assertIn("zh-Hant", tw.languages)

    def test_market_names_three_languages(self) -> None:
        for m in self.reg.markets.values():
            for lang in ("en", "es", "zh"):
                self.assertTrue(m.display_name(lang))
                self.assertNotEqual(m.code, m.display_name(lang))


class TestLanguages(RegistryBase):
    def test_registered_language_set(self) -> None:
        codes = set(self.reg.languages)
        self.assertEqual({"en", "es", "zh", "zh-Hant", "de", "fr", "it", "nl", "pl", "pt"},
                         codes)
        self.assertEqual({"en", "es", "zh"}, {x.code for x in self.reg.enabled_languages})

    def test_language_required_shape(self) -> None:
        for lang in self.reg.languages.values():
            self.assertRegex(lang.code, M.RE_LANG.pattern)
            self.assertIn(lang.script, M.ALLOWED_SCRIPTS)
            self.assertIn(lang.dir, M.ALLOWED_DIRS)
            self.assertRegex(lang.hreflang, M.RE_HREFLANG.pattern)
            self.assertTrue(lang.path == "" or M.RE_PATH.match(lang.path), lang.path)
            self.assertTrue(lang.native_name.strip())
            self.assertTrue(1 <= len(lang.ui_label) <= 8)
            self.assertGreater(lang.order, 0)

    def test_orders_unique(self) -> None:
        orders = [x.order for x in self.reg.languages.values()]
        self.assertEqual(len(orders), len(set(orders)))

    def test_paths_and_hreflang_unique(self) -> None:
        paths = [x.path for x in self.reg.languages.values() if x.path]
        self.assertEqual(len(paths), len(set(paths)))
        hreflangs = [x.hreflang for x in self.reg.languages.values()]
        self.assertEqual(len(hreflangs), len(set(hreflangs)))
        prefixes = [x.i18n_key_prefix for x in self.reg.languages.values()]
        self.assertEqual(len(prefixes), len(set(prefixes)))

    def test_zh_hant_placeholder(self) -> None:
        zh_hant = self.reg.require_language("zh-Hant")
        self.assertFalse(zh_hant.enabled)
        self.assertEqual("traditional", zh_hant.script)
        self.assertEqual("zh-Hant", zh_hant.hreflang)
        self.assertEqual("zh-Hant/", zh_hant.path)
        self.assertEqual("TW", zh_hant.default_country)
        self.assertEqual("zh-Hant", zh_hant.i18n_key_prefix)
        self.assertEqual("繁中", zh_hant.ui_label)
        self.assertEqual("繁體中文", zh_hant.native_name)
        # 繁体语言默认国家 TW 已在市场表登记（占位），只等数据源
        self.assertIsNotNone(self.reg.market("TW"))

    def test_eu_language_placeholders(self) -> None:
        for code in ("de", "fr", "it", "nl", "pl", "pt"):
            lang = self.reg.require_language(code)
            self.assertFalse(lang.enabled)
            self.assertEqual("EU", lang.region)
            self.assertIn(lang.default_country, self.reg.planned_markets)
            self.assertIsNone(self.reg.market(lang.default_country))
        self.assertIn("DE", self.reg.planned_markets)

    def test_enabled_language_default_country_enabled(self) -> None:
        for lang in self.reg.enabled_languages:
            market = self.reg.market_for_language(lang.code)
            self.assertIsNotNone(market, lang.code)
            assert market is not None
            self.assertTrue(market.enabled, lang.code)
            self.assertIn(lang.code, market.languages)
            self.assertEqual(lang.code, market.default_lang)

    def test_site_langs_compatibility(self) -> None:
        """现有 site/build.py 的 LANGS 三入口必须能从注册表推导出来（不改 build，只核对）。"""
        self.assertEqual(SITE_LANGS, {(x.code, x.path) for x in self.reg.enabled_languages})
        self.assertEqual({"en": "", "es": "es/", "zh": "zh/"}, self.reg.hreflang_map())
        self.assertEqual({"en", "es", "zh"}, set(self.reg.i18n_prefixes()))

    def test_language_ui_labels_unique(self) -> None:
        labels = [x.ui_label for x in self.reg.languages.values()]
        self.assertEqual(len(labels), len(set(labels)))


class TestDummyRegistration(RegistryBase):
    """dummy 市场/语言：能注册、校验通过、不影响现有数据。"""

    def _dummy_market(self, **over) -> dict:
        data = {
            "code": "ZZ", "kind": "country", "parent": None, "group": "GLOBAL",
            "name": {"en": "Dummyland", "es": "País Ficticio", "zh": "测试国"},
            "i18n_key": "home.zz", "flag": "🇿🇿",
            "source_id": "manual_seed", "extra_source_ids": [],
            "default_lang": "en", "languages": ["en"],
            "enabled": True, "order": 95, "notes": "dummy 测试市场",
        }
        data.update(over)
        return data

    def _dummy_language(self, **over) -> dict:
        data = {
            "code": "xx", "name": {"en": "Testish", "es": "Testish", "zh": "测试语"},
            "native_name": "Testish", "ui_label": "XX", "script": "latin", "dir": "ltr",
            "hreflang": "xx", "path": "xx/", "i18n_key_prefix": "xx",
            "default_country": "DE", "region": "EU", "enabled": False, "order": 110,
            "notes": "dummy 测试语言",
        }
        data.update(over)
        return data

    def test_dummy_market_registers_without_error(self) -> None:
        reg2 = self.reg.with_market(self._dummy_market())
        self.assertIn("ZZ", reg2.markets)
        self.assertIn("ZZ", reg2.country_order)   # enabled 国家进入规范顺序
        self.assertEqual([], reg2.validate())
        # 原注册表不被修改（不可变）
        self.assertNotIn("ZZ", self.reg.markets)
        self.assertEqual([], self.reg.validate())
        # round-trip
        m = reg2.require_market("ZZ")
        self.assertEqual("ZZ", m.code)
        self.assertEqual("Dummyland", m.display_name("en"))
        self.assertEqual(95, m.order)

    def test_dummy_market_disabled_allows_no_source(self) -> None:
        reg2 = self.reg.with_market(self._dummy_market(enabled=False, source_id=None,
                                                       languages=["en"]))
        self.assertEqual([], reg2.validate())
        self.assertFalse(reg2.require_market("ZZ").enabled)

    def test_dummy_language_registers_without_error(self) -> None:
        reg2 = self.reg.with_language(self._dummy_language())
        self.assertEqual([], reg2.validate())
        lang = reg2.require_language("xx")
        self.assertEqual("DE", lang.default_country)
        self.assertEqual([], self.reg.validate())

    def test_dummy_region_with_child(self) -> None:
        # 空 region 不能 enabled（校验强制）；先注册 disabled region + enabled 子市场，
        # 子市场挂到 region 下是合法层级（未来 EU 成员国即此形态）。
        region = {
            "code": "AA", "kind": "region", "parent": None, "group": "GLOBAL",
            "name": {"en": "Dummy Region", "es": "Región Ficticia", "zh": "测试区域"},
            "i18n_key": "home.aa", "flag": "🇦🇦", "source_id": None,
            "default_lang": "en", "languages": [],
            "enabled": False, "order": 96, "notes": "dummy region（带子市场，先 disabled）",
        }
        child = self._dummy_market(code="ZZ", parent="AA", order=97)
        reg2 = self.reg.with_market(region).with_market(child)
        self.assertEqual([], reg2.validate())
        self.assertTrue(reg2.require_market("AA").is_region)
        self.assertFalse(reg2.require_market("AA").enabled)
        self.assertEqual("AA", reg2.require_market("ZZ").parent)


class TestInvalidRegistration(RegistryBase):
    def _dummy_market(self, **over) -> dict:
        data = TestDummyRegistration._dummy_market(self, **over)
        return data

    def test_duplicate_code_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.with_market(self._dummy_market(code="US"))

    def test_bad_flag_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.with_market(self._dummy_market(flag="🇺"))

    def test_missing_source_rejected_for_enabled(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.with_market(self._dummy_market(source_id=None))

    def test_unknown_source_rejected(self) -> None:
        if self.source_ids is None:
            self.skipTest("DB 不存在，无法校验未知 source")
        with self.assertRaises(ValueError):
            self.reg.with_market(self._dummy_market(source_id="no_such_source_xyz"))

    def test_unknown_default_language_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.with_market(self._dummy_market(default_lang="qq"))

    def test_bad_kind_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.with_market(self._dummy_market(kind="planet"))

    def test_unknown_parent_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.with_market(self._dummy_market(parent="NO_SUCH"))

    def test_duplicate_order_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.reg.with_market(self._dummy_market(order=10))   # 与 US 冲突

    def test_bad_language_rejected(self) -> None:
        base = TestDummyRegistration._dummy_language(self)
        for over in ({"script": "klingon"}, {"dir": "sideways"},
                     {"path": "/xx/"}, {"hreflang": "es"},  # hreflang 重复
                     {"path": "es/"},                       # path 重复
                     {"default_country": "ZZ_NOT_REGISTERED"}):
            with self.assertRaises(ValueError, msg=f"应拒绝 {over}"):
                self.reg.with_language({**base, **over})

    def test_enabled_language_with_disabled_default_country_rejected(self) -> None:
        base = TestDummyRegistration._dummy_language(self)
        with self.assertRaises(ValueError):
            self.reg.with_language({**base, "code": "yy", "hreflang": "yy", "path": "yy/",
                                    "i18n_key_prefix": "yy", "ui_label": "YY",
                                    "order": 120, "default_country": "TW", "enabled": True})


class TestApiHelpers(RegistryBase):
    def test_require_raises_for_unknown(self) -> None:
        with self.assertRaises(KeyError):
            self.reg.require_market("ZZ")
        with self.assertRaises(KeyError):
            self.reg.require_language("zz")

    def test_languages_for_market(self) -> None:
        self.assertEqual(["en"], [x.code for x in self.reg.languages_for_market("US")])
        self.assertEqual(["es"], [x.code for x in self.reg.languages_for_market("MX")])
        self.assertEqual(["es"], [x.code for x in self.reg.languages_for_market("ES")])
        self.assertEqual(["zh"], [x.code for x in self.reg.languages_for_market("CN")])
        self.assertEqual((), self.reg.languages_for_market("EU"))

    def test_display_names_and_helpers(self) -> None:
        self.assertEqual("美国", self.reg.require_market("US").display_name("zh"))
        self.assertEqual("United States", self.reg.require_market("US").display_name("fr"))
        self.assertEqual("Español", self.reg.require_language("es").native_name)
        self.assertTrue(self.reg.require_language("pt").is_rtl is False)

    def test_as_dict_roundtrip(self) -> None:
        data = self.reg.as_dict()
        self.assertEqual(len(self.reg.markets), len(data["markets"]))
        self.assertEqual(len(self.reg.languages), len(data["languages"]))
        m = M.Market.from_dict(data["markets"][0])
        self.assertEqual(m.code, data["markets"][0]["code"])
        self.assertEqual(m.to_dict(), data["markets"][0])
        lang = M.Language.from_dict(data["languages"][0])
        self.assertEqual(lang.to_dict(), data["languages"][0])
        self.assertIn("planned_markets", data)

    def test_registry_is_immutable_snapshot(self) -> None:
        snapshot = dict(self.reg.markets)
        self.reg.with_market(TestDummyRegistration._dummy_market(self))
        self.assertEqual(snapshot.keys(), self.reg.markets.keys())


class TestCliAndDocs(RegistryBase):
    def test_cli_check_passes(self) -> None:
        p = subprocess.run([sys.executable, str(ROOT / "lib" / "markets.py"), "--check"],
                           capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        self.assertEqual(0, p.returncode, p.stderr[-500:])

    def test_cli_json_output(self) -> None:
        p = subprocess.run([sys.executable, str(ROOT / "lib" / "markets.py"), "--json"],
                           capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        self.assertEqual(0, p.returncode, p.stderr[-500:])
        data = json.loads(p.stdout)
        self.assertEqual(9, len(data["markets"]))
        self.assertEqual(10, len(data["languages"]))
        self.assertEqual("US", data["markets"][0]["code"])

    def test_cli_no_db_mode(self) -> None:
        p = subprocess.run([sys.executable, str(ROOT / "lib" / "markets.py"),
                            "--no-db", "--check"],
                           capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        self.assertEqual(0, p.returncode, p.stderr[-500:])

    def test_docs_exist_and_cover_extension_contract(self) -> None:
        self.assertTrue(DOCS.exists(), "缺 docs/市场扩展接口.md")
        text = DOCS.read_text(encoding="utf-8")
        for needle in ("新增市场", "新增语言", "market 表", "迁移", "TW", "EU",
                       "etl/markets/", "lib/markets.py", "data/markets.json",
                       "data/languages.json"):
            self.assertIn(needle, text, f"文档缺关键内容: {needle}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
