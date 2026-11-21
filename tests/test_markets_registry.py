"""市场/语言注册表测试（docs/市场扩展接口.md 的验收门槛）。

运行（仓库根目录）：

    & $py -m unittest tests.test_markets_registry -v

覆盖：
    - data/markets.json / data/languages.json 结构、字段、格式、唯一性；
    - 现有 15 国 + EU region（2026-11-20，含 CZ / LV / MY）；
    - en/es/zh/zh-Hant/fr/ko/ja/cs/lv 启用（v0.17.0 起 9 语）、EU 语言占位（disabled）；
    - **LG3（v0.15.0）门禁**：每个启用市场必须声明 `ui_languages` / `ui_language_gaps`，
      且与「站点实际渲染的界面语言」+「市场母语」现查一致（缺字段 / 写错 → 红）；
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
from collections.abc import Iterable, Mapping, Sequence
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
# v0.7.0（task-87）：TW 市场 + zh-Hant 语言启用 → 8 国/4 语；
# v0.8.0（SG 启用窗口）：SG 市场启用 → 9 国；语言仍 4（SG 为英文市场）。
# v0.9.0（HK 启用）：HK 接入 → 10 市场；语言仍 4（HK 为繁中/英文名称层）。
# v0.11.4（2026-11-14）：FR 市场 + fr 语言启用 → 11 国/5 语。
# v0.12.0（2026-11-15）：JP 市场启用（薬価基準 12,442 品目）→ 12 国/5 语（不新增 ja UI 语言）。
# v0.13.0（2026-11-16）：CZ / LV 市场启用（SÚKL DLP / ZVA HumanProducts）→ 14 国/5 语
#   （不新增 cs / lv UI 语言，两个市场默认英文，与 JP 同型）。
# v0.13.8（2026-11-18，LG1）：ko 接入为第 6 个界面语言（不加 KR 市场）→ 14 国/6 语。
# v0.16.0（2026-11-20，L2）：ja 接入为第 7 个界面语言（只加界面语言，不加市场）→ 14 国/7 语。
# v0.17.0（2026-11-20，L3）：cs / lv 接入为第 8、9 个界面语言（只加界面语言，不加市场）→ 14 国/9 语。
# 2026-11-20（M7/task-7）：MY 市场接入（NPRA/QUEST3+）→ 15 国 + EU；马来语界面未接入，gap=["ms"]。
# 2026-11-22（NO，v1.1.0）：NO 市场接入（DMP FEST 2.5.1 / NLOD 2.0）→ 16 国 + EU；
#   挪威语界面未接入（本版不新增界面语言），gap=["nb","no"]。
# 2026-11-22（KR，v1.2.0）：KR 市场接入（HIRA 약가마스터 / KOGL 제1유형）→ 17 国 + EU；
#   韩语界面已存在（ko，LG1 纯界面语言）→ gap=[]。
SITE_LANGS = {("en", ""), ("es", "es/"), ("zh", "zh/"), ("zh-Hant", "zh-Hant/"),
              ("fr", "fr/"), ("ko", "ko/"), ("ja", "ja/"), ("cs", "cs/"), ("lv", "lv/")}
SITE_COUNTRY_I18N = {"US", "GB", "CN", "ES", "MX", "AU", "CA", "TW", "SG", "HK",
                     "FR", "JP", "CZ", "LV", "MY", "NO", "KR"}
# v0.11.0：EU 区域层启用（kind=region，own_data=true，不进 country_order）
SITE_REGION_I18N = {"EU"}


def _db_countries() -> set[str] | None:
    if not DB.exists():
        return None
    import sqlite3
    uri = "file:" + str(DB.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        # v0.11.0：EU 区域层行的 country 为 NULL，国家集合只取非空值
        return {r[0] for r in con.execute("SELECT DISTINCT country FROM product")
                if r[0]}
    finally:
        con.close()


def _db_regions() -> set[str] | None:
    if not DB.exists():
        return None
    import sqlite3
    uri = "file:" + str(DB.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        return {r[0] for r in con.execute("SELECT DISTINCT region FROM product")
                if r[0]}
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


# ---------------------------------------------------------------------------
# LG3（v0.15.0）门禁：市场「界面语言覆盖」声明
# ---------------------------------------------------------------------------
# 语义（Lead 2026-11-19 确认，按**站点实际**）：
#   ui_languages     = 站点对该市场真的渲染的界面语言全集 = data/languages.json 里
#                      `enabled: true` 的 code（按 order）。构建对**每个市场**都出全部
#                      语言页面（根 = en，/es/ /zh/ /zh-Hant/ /fr/ /ko/），所以少写就是
#                      谎报、多写就是引用未启用语言。
#   ui_language_gaps = 该市场**母语**里未被 ui_languages 覆盖的 code（全覆盖 = []，
#                      不许省略、不许留空猜）。现查只有 JP=ja / CZ=cs / LV=lv 未覆盖。
# 用户 2026-11-19 要求「市场界面语言覆盖」透明化，正是这条门禁：防再出现
# 「收了几万条数据却没有该语言界面」。新增市场必须先在 MARKET_NATIVE_LANGS 登记母语，
# 否则门禁红（不许默认通过）。
MARKET_NATIVE_LANGS: dict[str, tuple[str, ...]] = {
    "US": ("en",), "GB": ("en",), "CA": ("en", "fr"), "AU": ("en",),
    "SG": ("en",), "ES": ("es",), "MX": ("es",), "CN": ("zh",),
    "TW": ("zh-Hant",), "HK": ("zh-Hant",), "FR": ("fr",), "EU": ("en",),
    "JP": ("ja",), "CZ": ("cs",), "LV": ("lv",), "MY": ("ms",),
    # 2026-11-22（NO）：挪威语两种 BCP47 写法都在站点界面语言之外（nb = Bokmål，no = 宏语言）。
    "NO": ("nb", "no"),
    # 2026-11-22（KR，v1.2.0）：韩语界面已启用（ko 是 LG1 纯界面语言）→ 缺口为空。
    "KR": ("ko",),
}
UI_LANG_FIELDS = ("ui_languages", "ui_language_gaps")


def ui_language_errors(markets: Iterable[Mapping[str, object]],
                       enabled_langs: Sequence[str],
                       native: Mapping[str, tuple[str, ...]] | None = None) -> list[str]:
    """LG3 门禁：返回界面语言覆盖声明的问题列表（空 = 通过）。

    入参是 `data/markets.json` 的 `markets` 原始 dict 列表（可含假市场），
    `enabled_langs` 是 `data/languages.json` 里 enabled 的 code（按 order）。

    规则：
      1. 每个 enabled 市场必须有 `ui_languages` / `ui_language_gaps`（缺 → 问题）；
      2. `ui_languages` 必须是非空字符串数组、无重复、每项都是 enabled 界面语言；
      3. `ui_languages` 必须**恰好**等于 enabled 界面语言全集（站点对每个市场都渲染全部）；
      4. `ui_language_gaps` 必须恰好等于「母语 − ui_languages」；市场母语未登记 → 问题。
    """
    out: list[str] = []
    fam_table = MARKET_NATIVE_LANGS if native is None else native
    want = list(enabled_langs)
    for row in markets:
        code = str(row.get("code") or "?")
        if not row.get("enabled"):
            continue
        for key in UI_LANG_FIELDS:
            if key not in row:
                out.append(f"市场 {code}: 缺 {key}（启用市场必须声明界面语言覆盖）")
        ui = row.get("ui_languages")
        gaps = row.get("ui_language_gaps")
        if ui is not None:
            if not isinstance(ui, list) or not all(isinstance(x, str) for x in ui):
                out.append(f"市场 {code}: ui_languages 必须是字符串数组")
            elif not ui:
                out.append(f"市场 {code}: ui_languages 不能为空")
            else:
                extra = [x for x in ui if x not in want]
                if extra:
                    out.append(f"市场 {code}: ui_languages 含未启用的界面语言 {extra}")
                if len(ui) != len(set(ui)):
                    out.append(f"市场 {code}: ui_languages 有重复")
                if list(ui) != want:
                    out.append(f"市场 {code}: ui_languages 与站点渲染的 {want} 不一致"
                               f"（现查 {list(ui)}）")
        if gaps is not None:
            if not isinstance(gaps, list) or not all(isinstance(x, str) for x in gaps):
                out.append(f"市场 {code}: ui_language_gaps 必须是字符串数组")
            else:
                if len(gaps) != len(set(gaps)):
                    out.append(f"市场 {code}: ui_language_gaps 有重复")
                fam = fam_table.get(code)
                if fam is None:
                    out.append(f"市场 {code}: 未登记母语（MARKET_NATIVE_LANGS），"
                               f"无法校验 ui_language_gaps")
                else:
                    covered = set(ui) if isinstance(ui, list) else set()
                    expect = [x for x in fam if x not in covered]
                    if list(gaps) != expect:
                        out.append(f"市场 {code}: ui_language_gaps 应为 {expect}"
                                   f"（现查 {list(gaps)}）")
    return out


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
        # 2026-11-20（M7）：MY 已随数据启用（enabled 市场 == DB 国家集合）
        # 2026-11-22（NO）：NO 已随 FEST 数据启用 → 16 国 + EU。
        self.assertEqual({"US", "GB", "CA", "AU", "ES", "MX", "CN", "TW", "SG", "HK",
                          "EU", "FR", "JP", "CZ", "LV", "MY", "NO", "KR"},
                         codes)
        self.assertEqual({"US", "GB", "CA", "AU", "ES", "MX", "CN", "TW", "SG", "HK",
                          "FR", "JP", "CZ", "LV", "MY", "NO", "KR"},
                         set(self.reg.country_order))
        # v0.11.0：EU 区域层启用（own_data=true，国家集合不变）
        self.assertEqual({"US", "GB", "CA", "AU", "ES", "MX", "CN", "TW", "SG", "HK",
                          "EU", "FR", "JP", "CZ", "LV", "MY", "NO", "KR"},
                         {m.code for m in self.reg.enabled_markets})
        self.assertEqual(("EU",), self.reg.region_codes)

    def test_cz_lv_market_rows(self) -> None:
        """v0.13.0：CZ / LV 市场行（五语名 / i18n_key / source_id / 英文市场，不新增 UI 语言）。"""
        for code, source_id, order in (("CZ", "sukl_dlp", 130),
                                       ("LV", "zva_lv_register", 140)):
            m = self.reg.require_market(code)
            self.assertTrue(m.enabled, code)
            self.assertEqual(M.KIND_COUNTRY, m.kind, code)
            self.assertEqual("EUROPE", m.group, code)
            self.assertIsNone(m.parent, code)
            self.assertEqual(f"home.{code.lower()}", m.i18n_key, code)
            self.assertEqual(source_id, m.source_id, code)
            self.assertEqual(order, m.order, code)
            self.assertEqual(("en",), m.languages, code)
            self.assertEqual("en", m.default_lang, code)
            for lang in ("en", "es", "zh", "zh-Hant", "fr"):
                self.assertTrue((m.name.get(lang) or "").strip(),
                                f"{code} 缺 name.{lang}")

    def test_my_market_row(self) -> None:
        """2026-11-20（M7）：MY 市场行（15 国 + EU；9 语界面，母语 ms 缺口）。"""
        m = self.reg.require_market("MY")
        self.assertTrue(m.enabled)
        self.assertEqual(M.KIND_COUNTRY, m.kind)
        self.assertEqual("ASIA", m.group)
        self.assertIsNone(m.parent)
        self.assertEqual("home.my", m.i18n_key)
        self.assertEqual("my_npra_products", m.source_id)
        self.assertEqual(125, m.order)
        self.assertEqual(("en",), m.languages)
        self.assertEqual("en", m.default_lang)
        row = self.market_dict("MY")
        self.assertEqual(["ms"], row["ui_language_gaps"])
        self.assertEqual(9, len(row["ui_languages"]))
        for lang in ("en", "es", "zh"):
            self.assertTrue((m.name.get(lang) or "").strip(),
                            f"MY 缺 name.{lang}")

    def test_no_market_row(self) -> None:
        """2026-11-22（NO，v1.1.0）：NO 市场行（16 国 + EU；9 语界面，母语 nb/no 缺口）。"""
        m = self.reg.require_market("NO")
        self.assertTrue(m.enabled)
        self.assertEqual(M.KIND_COUNTRY, m.kind)
        self.assertEqual("EUROPE", m.group)
        self.assertIsNone(m.parent)
        self.assertEqual("home.no", m.i18n_key)
        self.assertEqual("dmp_fest", m.source_id)
        self.assertEqual(150, m.order)
        self.assertEqual(("en",), m.languages)
        self.assertEqual("en", m.default_lang)
        row = self.market_dict("NO")
        # NLOD 2.0 要求登记挪威语界面缺口（nb / no 两种写法都写）
        self.assertEqual(["nb", "no"], row["ui_language_gaps"])
        self.assertEqual(9, len(row["ui_languages"]))
        self.assertEqual("2026-11-10", row["data_as_of"])
        for lang in ("en", "es", "zh", "zh-Hant", "fr", "ko", "ja", "cs", "lv"):
            self.assertTrue((m.name.get(lang) or "").strip(),
                            f"NO 缺 name.{lang}")

    def test_kr_market_row(self) -> None:
        """2026-11-22（KR，v1.2.0）：KR 市场行（17 国 + EU；韩语界面已存在，gap=[]）。"""
        m = self.reg.require_market("KR")
        self.assertTrue(m.enabled)
        self.assertEqual(M.KIND_COUNTRY, m.kind)
        self.assertEqual("ASIA", m.group)
        self.assertIsNone(m.parent)
        self.assertEqual("home.kr", m.i18n_key)
        self.assertEqual("hira_kr_medprice", m.source_id)
        self.assertEqual(160, m.order)
        self.assertEqual(("ko",), m.languages)
        self.assertEqual("ko", m.default_lang)
        row = self.market_dict("KR")
        self.assertEqual([], row["ui_language_gaps"])
        self.assertEqual(9, len(row["ui_languages"]))
        self.assertEqual("2026-08-31", row["data_as_of"])
        for lang in ("en", "es", "zh", "zh-Hant", "fr", "ko", "ja", "cs", "lv"):
            self.assertTrue((m.name.get(lang) or "").strip(), f"KR 缺 name.{lang}")

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
        # 现有市场（15 国 + EU 区域层）的 i18n key 与 site/build.py I18N 的 home.* 完全一致
        self.assertEqual({f"home.{c.lower()}" for c in SITE_COUNTRY_I18N | SITE_REGION_I18N},
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
        # v0.11.0：区域层（product.region）与注册表 region 集合一致
        regions = _db_regions()
        self.assertIsNotNone(regions)
        self.assertEqual(set(self.reg.region_codes), regions,
                         "注册表区域层与 DB product.region 不一致")

    def test_parent_relationship(self) -> None:
        eu = self.reg.require_market("EU")
        self.assertTrue(eu.is_region)
        self.assertIsNone(eu.parent)
        # v0.11.0：EU 区域层启用（自带数据，不等子市场）
        self.assertTrue(eu.enabled)
        self.assertTrue(eu.own_data)
        self.assertEqual("eu_union_register", eu.source_id)
        self.assertIn("ema_medicines", eu.extra_source_ids)
        for code in self.reg.country_order:
            self.assertIsNone(self.reg.require_market(code).parent)
        # 若将来国家挂到 region 下，父节点必须是 region
        for m in self.reg.markets.values():
            if self.reg.market("EU") and m.parent == "EU":
                self.assertTrue(self.reg.require_market("EU").is_region)

    def test_region_without_own_data_cannot_be_enabled_alone(self) -> None:
        # 手工构造「EU enabled 但没有子市场、也没声明 own_data」→ 校验必须报错
        eu = self.reg.require_market("EU")
        markets = dict(self.reg.markets)
        markets["EU"] = M.Market(**{**eu.__dict__, "own_data": False})
        broken = M.MarketsRegistry(markets, self.reg.languages,
                                   source_ids=self.source_ids,
                                   planned_markets=self.reg.planned_markets)
        errs = broken.validate()
        self.assertTrue(any("region 至少要有 1 个启用的子市场" in e for e in errs), errs)
        # 真实注册表（own_data=true）必须通过
        self.assertEqual([], self.reg.validate())

    def test_tw_is_planned_placeholder(self) -> None:
        tw = self.reg.require_market("TW")
        self.assertEqual(M.KIND_COUNTRY, tw.kind)
        # v0.7.0（task-87）：TW 已启用（数据源 tfda_tw / 16,457 产品已在真实库）
        self.assertTrue(tw.enabled)
        self.assertEqual("tfda_tw", tw.source_id)
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
        self.assertEqual({"en", "es", "zh", "zh-Hant", "de", "fr", "ko", "ja", "cs", "lv",
                          "it", "nl", "pl", "pt"},
                         codes)
        # v0.11.4：fr 随 FR 市场启用（2026-11-14）；v0.13.8：ko 为纯界面语言（无 KR 市场）；
        # v0.16.0：ja 同为纯界面语言；v0.17.0：cs / lv 同为纯界面语言（不新增市场）
        self.assertEqual({"en", "es", "zh", "zh-Hant", "fr", "ko", "ja", "cs", "lv"},
                         {x.code for x in self.reg.enabled_languages})

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
        # v0.7.0（task-87）：zh-Hant 已启用（TW 默认语言，/zh-hant/ 路由）
        self.assertTrue(zh_hant.enabled)
        self.assertEqual("traditional", zh_hant.script)
        self.assertEqual("zh-Hant", zh_hant.hreflang)
        self.assertEqual("zh-Hant/", zh_hant.path)
        self.assertEqual("TW", zh_hant.default_country)
        self.assertEqual("zh-Hant", zh_hant.i18n_key_prefix)
        self.assertEqual("繁中", zh_hant.ui_label)
        self.assertEqual("繁體中文", zh_hant.native_name)
        # 繁体语言默认国家 TW 已启用
        tw = self.reg.market("TW")
        self.assertIsNotNone(tw)
        assert tw is not None
        self.assertTrue(tw.enabled)

    def test_eu_language_placeholders(self) -> None:
        # v0.11.4：fr 已启用（FR 市场），不再属于 EU 占位语言
        for code in ("de", "it", "nl", "pl", "pt"):
            lang = self.reg.require_language(code)
            self.assertFalse(lang.enabled)
            self.assertEqual("EU", lang.region)
            self.assertIn(lang.default_country, self.reg.planned_markets)
            self.assertIsNone(self.reg.market(lang.default_country))
        self.assertIn("DE", self.reg.planned_markets)

    def test_enabled_language_default_country_enabled(self) -> None:
        for lang in self.reg.enabled_languages:
            if not lang.default_country:
                # v0.13.8（LG1）：ko 是「纯界面语言」（用户定：不加 KR 市场）→ 无默认市场
                self.assertIsNone(self.reg.market_for_language(lang.code), lang.code)
                continue
            market = self.reg.market_for_language(lang.code)
            self.assertIsNotNone(market, lang.code)
            assert market is not None
            self.assertTrue(market.enabled, lang.code)
            self.assertIn(lang.code, market.languages)
            self.assertEqual(lang.code, market.default_lang)

    def test_site_langs_compatibility(self) -> None:
        """现有 site/build.py 的 LANGS 入口必须能从注册表推导出来（v0.17.0 起九语含 cs/lv）。"""
        self.assertEqual(SITE_LANGS, {(x.code, x.path) for x in self.reg.enabled_languages})
        self.assertEqual({"en": "", "es": "es/", "zh": "zh/", "zh-Hant": "zh-Hant/",
                          "fr": "fr/", "ko": "ko/", "ja": "ja/", "cs": "cs/", "lv": "lv/"},
                         self.reg.hreflang_map())
        self.assertEqual({"en", "es", "zh", "zh-Hant", "fr", "ko", "ja", "cs", "lv"},
                         set(self.reg.i18n_prefixes()))

    def test_language_ui_labels_unique(self) -> None:
        labels = [x.ui_label for x in self.reg.languages.values()]
        self.assertEqual(len(labels), len(set(labels)))


class TestUiLanguageCoverage(RegistryBase):
    """LG3（v0.15.0）：16 个启用市场必须声明界面语言覆盖，且声明与现查一致。"""

    def _enabled_lang_codes(self) -> list[str]:
        """data/languages.json 里 enabled 的 code，按 order 排序（= 站点渲染顺序）。"""
        rows = [x for x in self.raw_languages["languages"] if x.get("enabled")]
        rows.sort(key=lambda x: (x.get("order") or 9999, x["code"]))
        return [x["code"] for x in rows]

    def test_gate_passes_on_real_registry(self) -> None:
        codes = self._enabled_lang_codes()
        self.assertEqual(["en", "es", "zh", "zh-Hant", "fr", "ko", "ja", "cs", "lv"], codes)
        self.assertEqual([], ui_language_errors(self.raw_markets["markets"], codes),
                         "markets.json 的界面语言覆盖声明与现查不一致")

    def test_every_enabled_market_declares_both_fields(self) -> None:
        enabled = [m for m in self.raw_markets["markets"] if m.get("enabled")]
        self.assertEqual(18, len(enabled))
        for row in enabled:
            for key in UI_LANG_FIELDS:
                self.assertIn(key, row, f"市场 {row['code']} 缺 {key}")
            self.assertIsInstance(row["ui_languages"], list)
            self.assertIsInstance(row["ui_language_gaps"], list)

    def test_ui_languages_are_the_six_rendered_ones(self) -> None:
        codes = self._enabled_lang_codes()
        for row in self.raw_markets["markets"]:
            if not row.get("enabled"):
                continue
            self.assertEqual(codes, row["ui_languages"], f"市场 {row['code']}")

    def test_gaps_match_native_language(self) -> None:
        for code, fam in MARKET_NATIVE_LANGS.items():
            row = self.market_dict(code)
            covered = set(row["ui_languages"])
            self.assertEqual([x for x in fam if x not in covered],
                             row["ui_language_gaps"], code)
        # 17 市场逐个核对（2026-11-22）：9 种界面语言覆盖 16 国 + EU；
        # MY 母语 ms、NO 母语 nb/no 未接入（本版不新增界面语言，只登记缺口）
        self.assertEqual({"MY": ["ms"], "NO": ["nb", "no"]},
                         {m["code"]: m["ui_language_gaps"]
                          for m in self.raw_markets["markets"] if m["ui_language_gaps"]})

    # --- 反例：证明门禁不空转（假市场 / 假声明必须红） ---
    def _fake(self, code: str = "JP", **over) -> dict:
        """伪声明：拿真实市场行做底（保留母语可查），覆盖字段后当「假记录」喂门禁。"""
        row = dict(self.market_dict(code))
        row.update(over)
        return row

    def test_fake_market_missing_fields_fails(self) -> None:
        fake = self._fake()
        for key in UI_LANG_FIELDS:
            fake.pop(key)
        errs = ui_language_errors([fake], self._enabled_lang_codes())
        self.assertTrue(any("缺 ui_languages" in e for e in errs), errs)
        self.assertTrue(any("缺 ui_language_gaps" in e for e in errs), errs)

    def test_fake_market_wrong_gaps_fails(self) -> None:
        # 2026-11-20（v0.17.0）：9 语已覆盖全部市场母语，真实缺口为空；
        # 反例改为「谎报一个不存在的缺口」——JP 的母语 ja 已被覆盖，声明 gaps=["ja"] 必须红
        fake = self._fake("JP", ui_language_gaps=["ja"])
        errs = ui_language_errors([fake], self._enabled_lang_codes())
        self.assertTrue(any("ui_language_gaps 应为 []" in e for e in errs), errs)

    def test_fake_market_shrunk_ui_languages_fails(self) -> None:
        # 只写 en（「仅英文」）：站点实际出 9 语 → 谎报，必须红
        fake = self._fake(ui_languages=["en"], ui_language_gaps=["ja"])
        errs = ui_language_errors([fake], self._enabled_lang_codes())
        self.assertTrue(any("不一致" in e and "ui_languages" in e for e in errs), errs)

    def test_fake_market_with_disabled_ui_language_fails(self) -> None:
        fake = self._fake(ui_languages=[*self.market_dict("JP")["ui_languages"], "de"])
        errs = ui_language_errors([fake], self._enabled_lang_codes())
        self.assertTrue(any("未启用的界面语言 ['de']" in e for e in errs), errs)

    def test_fake_market_without_native_language_fails(self) -> None:
        # 新增市场没登记母语 → 不许悄悄通过
        fake = dict(self._fake(), code="ZZ", ui_language_gaps=[])
        errs = ui_language_errors([fake], self._enabled_lang_codes(),
                                  native={"JP": ("ja",)})
        self.assertTrue(any("未登记母语" in e for e in errs), errs)


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
        self.assertEqual(["en"], [x.code for x in self.reg.languages_for_market("EU")])

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
        # v0.13.0（2026-11-16）：15 市场（14 国 + EU region）；v0.13.8：10 → 11（含 ko）；
        # v0.16.0：11 → 12（含 ja）；v0.17.0：12 → 14（含 cs / lv）；2026-11-20：16（+ MY）；
        # 2026-11-22：17（+ NO）；v1.2.0：18（+ KR）
        self.assertEqual(18, len(data["markets"]))
        self.assertEqual(14, len(data["languages"]))
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
