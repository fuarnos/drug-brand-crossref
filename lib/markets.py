"""市场 / 语言注册表（唯一真相源，供扩展接口使用）。

为什么要有这一层
----------------
站点原来把「支持哪些国家/语言」硬编码在 `site/build.py`（`LANGS`、国家下拉框、
sitemap 顺序）、`db/schema.sql`（`product.country` 的 CHECK 枚举）和 About 文案里，
加一个市场要改四五处、容易漏。本模块把「市场 / 语言」抽成数据文件 + 一个小 API：

    data/markets.json     市场：现有 7 国（US/GB/CA/AU/ES/MX/CN）+ 占位 TW + EU region（disabled）
    data/languages.json   UI 语言：en/es/zh + zh-Hant（预留）+ EU 语言占位（disabled）
    lib/markets.py        读取 / 校验 / 查询 / 注册（本文件）

**本模块不改数据库、不改站点构建**：它只是扩展接口的注册表与文档化校验。
站点与 ETL 的接入步骤见 `docs/市场扩展接口.md`。

字段（与 data/*.json 一致）
--------------------------
Market（每个市场）：
    code            大写代码：国家 ISO 3166-1 alpha-2（US/GB/CN/TW…），region（EU）
    kind            country | region
    parent          None 或 region 代码（未来 EU 成员国 → parent=EU）
    group           导航分组：NA / EUROPE / LATAM / ASIA / OCEANIA
    name            {en, es, zh} 显示名（站点当前 3 种 UI 语言都要有）
    i18n_key        站点 i18n key（现有 home.us … home.ca；新市场 home.<code 小写>）
    flag            国旗/区域旗 emoji（两个 regional indicator，如 🇺🇸 / 🇪🇺）
    source_id       主数据源 source_id（enabled 市场必填，必须存在于 DB source 表）
    extra_source_ids 辅助来源（同样必须存在于 DB source 表）
    default_lang    该市场默认 UI 语言（必须在本注册表里且 enabled）
    languages       该市场可用的 UI 语言
    enabled         是否上线
    order           显示顺序（市场间唯一）
    notes           备注（许可/数据口径/占位原因）

Language（每种语言）：
    code            BCP47：en / es / zh / zh-Hant / de …
    name            {en, es, zh} 语言名
    native_name     本族语名（English / Español / 简体中文 / 繁體中文 …）
    ui_label        语言切换按钮短标签（EN / ES / 中文 / 繁中）
    script          latin / han / traditional / cyrillic / …
    dir             ltr | rtl
    hreflang        <link rel=alternate hreflang> 的值
    path            站点 URL 路径：en=""（根），es="es/"，zh="zh/"，zh-Hant="zh-Hant/"
    i18n_key_prefix 站点 I18N 字典的段名（与 code 相同；zh-Hant 为带连字符的 key）
    default_country 该语言默认市场（enabled 语言必须是 enabled 市场）
    region          可选：EU 之类区域标签（EU 语言占位用）
    enabled / order / notes

校验规则（`MarketsRegistry.validate()`，测试在 tests/test_markets_registry.py）
------------------------------------------------------------------------------
市场：code 格式/唯一；kind/parent（父必须是 region，region 不能有 parent）；
order 唯一；enabled 市场必须有 flag/i18n_key/source_id（且 source_id 在 DB source 表）、
default_lang 必须是 enabled 语言；市场名 en/es/zh 齐全；enabled region 至少一个
enabled 子市场（防止空区域上线）；disabled 占位可不填 source_id。
语言：code/hreflang/path/i18n_key_prefix 格式与唯一；script/dir 合法；enabled 语言的
default_country 必须是 enabled 市场；disabled 语言的 default_country 必须在
markets ∪ planned_markets（预留给 TW / EU 国家）。

用法
----
    python lib/markets.py                 # 打印注册表摘要 + 校验结果
    python lib/markets.py --json          # 输出合并后的 JSON（供构建脚本/文档引用）
    python lib/markets.py --check         # 只校验；有错退出码 1（CI/验收用）
    python lib/markets.py --no-db         # 不连 DB，跳过 source_id 存在性校验

    from lib import markets
    reg = markets.load()                  # 自动读 DB source 表做 source_id 校验
    reg.enabled_markets                   # ("US", "GB", "CA", "AU", "ES", "MX", "CN")
    reg.country_order                     # 国家页/下拉框的规范顺序
    reg.hreflang_map()                    # {"en": "", "es": "es/", "zh": "zh/"}
    reg.languages_for_market("MX")
    reg.validate()                        # list[str]，空 = 通过
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MARKETS_JSON = DATA_DIR / "markets.json"
LANGUAGES_JSON = DATA_DIR / "languages.json"
DB_DEFAULT = DATA_DIR / "drugs.db"

KIND_COUNTRY = "country"
KIND_REGION = "region"
ALLOWED_KINDS = (KIND_COUNTRY, KIND_REGION)
ALLOWED_SCRIPTS = ("latin", "han", "traditional", "cyrillic", "japanese",
                   "korean", "arabic", "devanagari", "other")
ALLOWED_DIRS = ("ltr", "rtl")
ALLOWED_GROUPS = ("NA", "EUROPE", "LATAM", "ASIA", "OCEANIA", "AFRICA", "GLOBAL")

RE_CODE = re.compile(r"^[A-Z]{2,3}$")
RE_LANG = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z]{2,8})*$")
RE_HREFLANG = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z]{2,8})*$")
RE_PATH = re.compile(r"^[A-Za-z0-9_-]+/$")
RE_I18N_KEY = re.compile(r"^home\.[a-z0-9_]+$")
FLAG_RI = (0x1F1E6, 0x1F1FF)

# 必填字段（JSON 里允许并列的可选字段：extra_source_ids / group / notes 等）
REQUIRED_MARKET_FIELDS = (
    "code", "kind", "parent", "name", "i18n_key", "flag", "source_id",
    "default_lang", "languages", "enabled", "order",
)
REQUIRED_LANGUAGE_FIELDS = (
    "code", "name", "native_name", "ui_label", "script", "dir", "hreflang",
    "path", "i18n_key_prefix", "default_country", "enabled", "order",
)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Market:
    code: str
    kind: str
    name: dict[str, str]
    i18n_key: str
    flag: str
    source_id: str | None
    default_lang: str
    languages: tuple[str, ...]
    enabled: bool
    order: int
    parent: str | None = None
    group: str = ""
    extra_source_ids: tuple[str, ...] = ()
    notes: str = ""

    @property
    def is_country(self) -> bool:
        return self.kind == KIND_COUNTRY

    @property
    def is_region(self) -> bool:
        return self.kind == KIND_REGION

    def display_name(self, lang: str = "en") -> str:
        return self.name.get(lang) or self.name.get("en") or self.code

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "kind": self.kind, "parent": self.parent,
            "group": self.group, "name": dict(self.name),
            "i18n_key": self.i18n_key, "flag": self.flag,
            "source_id": self.source_id,
            "extra_source_ids": list(self.extra_source_ids),
            "default_lang": self.default_lang,
            "languages": list(self.languages),
            "enabled": self.enabled, "order": self.order, "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Market":
        missing = [k for k in REQUIRED_MARKET_FIELDS if k not in d]
        if missing:
            raise ValueError(f"市场 {d.get('code', '?')} 缺字段: {', '.join(missing)}")
        return cls(
            code=str(d["code"]).strip(),
            kind=str(d["kind"]).strip(),
            name={str(k): str(v) for k, v in (d.get("name") or {}).items()},
            i18n_key=str(d.get("i18n_key") or ""),
            flag=str(d.get("flag") or ""),
            source_id=(str(d["source_id"]).strip() if d.get("source_id") else None),
            default_lang=str(d.get("default_lang") or ""),
            languages=tuple(str(x) for x in (d.get("languages") or [])),
            enabled=bool(d.get("enabled")),
            order=int(d.get("order", 0)),
            parent=(str(d["parent"]).strip() if d.get("parent") else None),
            group=str(d.get("group") or ""),
            extra_source_ids=tuple(str(x) for x in (d.get("extra_source_ids") or [])),
            notes=str(d.get("notes") or ""),
        )


@dataclass(frozen=True)
class Language:
    code: str
    name: dict[str, str]
    native_name: str
    ui_label: str
    script: str
    dir: str
    hreflang: str
    path: str
    i18n_key_prefix: str
    default_country: str
    enabled: bool
    order: int
    region: str | None = None
    notes: str = ""

    @property
    def is_rtl(self) -> bool:
        return self.dir == "rtl"

    def display_name(self, lang: str = "en") -> str:
        return self.name.get(lang) or self.name.get("en") or self.code

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "name": dict(self.name),
            "native_name": self.native_name, "ui_label": self.ui_label,
            "script": self.script, "dir": self.dir, "hreflang": self.hreflang,
            "path": self.path, "i18n_key_prefix": self.i18n_key_prefix,
            "default_country": self.default_country, "region": self.region,
            "enabled": self.enabled, "order": self.order, "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Language":
        missing = [k for k in REQUIRED_LANGUAGE_FIELDS if k not in d]
        if missing:
            raise ValueError(f"语言 {d.get('code', '?')} 缺字段: {', '.join(missing)}")
        return cls(
            code=str(d["code"]).strip(),
            name={str(k): str(v) for k, v in (d.get("name") or {}).items()},
            native_name=str(d.get("native_name") or ""),
            ui_label=str(d.get("ui_label") or ""),
            script=str(d.get("script") or ""),
            dir=str(d.get("dir") or ""),
            hreflang=str(d.get("hreflang") or ""),
            path=str(d.get("path") or ""),
            i18n_key_prefix=str(d.get("i18n_key_prefix") or ""),
            default_country=str(d.get("default_country") or ""),
            enabled=bool(d.get("enabled")),
            order=int(d.get("order", 0)),
            region=(str(d["region"]) if d.get("region") else None),
            notes=str(d.get("notes") or ""),
        )


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"注册表文件不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or (
            "markets" not in data and "languages" not in data):
        raise ValueError(f"{path} 不是合法的注册表 JSON（缺 markets/languages 顶层键）")
    return data


def db_source_ids(db_path: Path | str | None = None) -> set[str] | None:
    """只读打开 DB，取 source 表 id 集合；DB 不存在时返回 None（跳过该项校验）。"""
    path = Path(db_path or DB_DEFAULT)
    if not path.exists():
        return None
    uri = "file:" + str(path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=30)
        try:
            return {row[0] for row in con.execute("SELECT source_id FROM source")}
        finally:
            con.close()
    except sqlite3.Error:
        return None


class MarketsRegistry:
    """不可变的市场/语言注册表；`with_market` / `with_language` 返回新实例（供测试注册 dummy）。"""

    def __init__(
        self,
        markets: Mapping[str, Market],
        languages: Mapping[str, Language],
        *,
        source_ids: Iterable[str] | None = None,
        planned_markets: Iterable[str] = (),
        schema_version: int = 1,
        updated: str = "",
    ) -> None:
        self._markets = dict(markets)
        self._languages = dict(languages)
        self.source_ids: set[str] | None = set(source_ids) if source_ids is not None else None
        self.planned_markets: tuple[str, ...] = tuple(planned_markets)
        self.schema_version = schema_version
        self.updated = updated

    # --- 读取/构造 ---
    @classmethod
    def load(
        cls,
        markets_path: Path | str | None = None,
        languages_path: Path | str | None = None,
        *,
        source_ids: Iterable[str] | None = None,
        use_db: bool = True,
    ) -> "MarketsRegistry":
        mpath = Path(markets_path or MARKETS_JSON)
        lpath = Path(languages_path or LANGUAGES_JSON)
        mraw = load_json(mpath)
        lraw = load_json(lpath)
        markets = {m["code"]: Market.from_dict(m) for m in mraw.get("markets", [])}
        languages = {x["code"]: Language.from_dict(x) for x in lraw.get("languages", [])}
        known = source_ids if source_ids is not None else (db_source_ids() if use_db else None)
        return cls(
            markets, languages, source_ids=known,
            planned_markets=lraw.get("planned_markets") or (),
            schema_version=int(mraw.get("schema_version", 1)),
            updated=str(mraw.get("updated") or ""),
        )

    # --- 基础访问 ---
    @property
    def markets(self) -> dict[str, Market]:
        return dict(self._markets)

    @property
    def languages(self) -> dict[str, Language]:
        return dict(self._languages)

    def market(self, code: str) -> Market | None:
        return self._markets.get(code)

    def language(self, code: str) -> Language | None:
        return self._languages.get(code)

    def require_market(self, code: str) -> Market:
        m = self._markets.get(code)
        if m is None:
            raise KeyError(f"未注册的市场: {code}")
        return m

    def require_language(self, code: str) -> Language:
        lang = self._languages.get(code)
        if lang is None:
            raise KeyError(f"未注册的语言: {code}")
        return lang

    @property
    def enabled_markets(self) -> tuple[Market, ...]:
        return tuple(sorted((m for m in self._markets.values() if m.enabled),
                            key=lambda m: (m.order, m.code)))

    @property
    def enabled_languages(self) -> tuple[Language, ...]:
        return tuple(sorted((x for x in self._languages.values() if x.enabled),
                            key=lambda x: (x.order, x.code)))

    @property
    def country_order(self) -> tuple[str, ...]:
        """国家页/国家下拉框的规范顺序（enabled 的 country-kind 市场）。"""
        return tuple(m.code for m in self.enabled_markets if m.is_country)

    @property
    def region_codes(self) -> tuple[str, ...]:
        return tuple(m.code for m in self._markets.values() if m.is_region)

    def languages_for_market(self, code: str) -> tuple[Language, ...]:
        m = self._markets.get(code)
        if m is None:
            return ()
        out = [self._languages[c] for c in m.languages if c in self._languages]
        return tuple(sorted(out, key=lambda x: (x.order, x.code)))

    def market_for_language(self, code: str) -> Market | None:
        lang = self._languages.get(code)
        if lang is None:
            return None
        return self._markets.get(lang.default_country)

    def hreflang_map(self) -> dict[str, str]:
        """可以进 <link rel=alternate hreflang> 的 {hreflang: 站点路径}（仅 enabled 语言）。"""
        return {x.hreflang: x.path for x in self.enabled_languages}

    def i18n_prefixes(self) -> dict[str, str]:
        return {x.code: x.i18n_key_prefix for x in self.enabled_languages}

    # --- 序列化 ---
    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "updated": self.updated,
            "markets": [m.to_dict() for m in sorted(self._markets.values(),
                                                     key=lambda m: (m.order, m.code))],
            "languages": [x.to_dict() for x in sorted(self._languages.values(),
                                                      key=lambda x: (x.order, x.code))],
            "planned_markets": list(self.planned_markets),
        }

    # --- 注册（dummy 市场/语言冒烟 & 未来扩展用） ---
    def with_market(self, data: Mapping[str, Any] | Market) -> "MarketsRegistry":
        m = data if isinstance(data, Market) else Market.from_dict(data)
        if m.code in self._markets:
            raise ValueError(f"市场已存在: {m.code}")
        markets = dict(self._markets)
        markets[m.code] = m
        cand = self._copy(markets=markets)
        new_errors = _diff_errors(self.validate(), cand.validate())
        if new_errors:
            raise ValueError("市场注册失败: " + "; ".join(new_errors))
        return cand

    def with_language(self, data: Mapping[str, Any] | Language) -> "MarketsRegistry":
        x = data if isinstance(data, Language) else Language.from_dict(data)
        if x.code in self._languages:
            raise ValueError(f"语言已存在: {x.code}")
        languages = dict(self._languages)
        languages[x.code] = x
        cand = self._copy(languages=languages)
        new_errors = _diff_errors(self.validate(), cand.validate())
        if new_errors:
            raise ValueError("语言注册失败: " + "; ".join(new_errors))
        return cand

    def _copy(self, *, markets: Mapping[str, Market] | None = None,
              languages: Mapping[str, Language] | None = None) -> "MarketsRegistry":
        return MarketsRegistry(
            markets if markets is not None else self._markets,
            languages if languages is not None else self._languages,
            source_ids=self.source_ids,
            planned_markets=self.planned_markets,
            schema_version=self.schema_version,
            updated=self.updated,
        )

    # --- 校验 ---
    def validate(self) -> list[str]:
        errs: list[str] = []
        errs += _validate_markets(self._markets, self._languages, self.source_ids)
        errs += _validate_languages(self._languages, self._markets, self.planned_markets)
        errs += _validate_cross(self._markets, self._languages, self.planned_markets)
        return errs

    def validate_or_raise(self) -> None:
        errs = self.validate()
        if errs:
            raise ValueError("注册表校验失败:\n- " + "\n- ".join(errs))


def _diff_errors(before: list[str], after: list[str]) -> list[str]:
    """注册新条目后新增的错误（用于判断这一条是否合法）。"""
    seen = set(before)
    return [e for e in after if e not in seen]


# ---------------------------------------------------------------------------
# 单项校验
# ---------------------------------------------------------------------------
def _valid_flag(flag: str) -> bool:
    return (len(flag) == 2 and all(FLAG_RI[0] <= ord(ch) <= FLAG_RI[1] for ch in flag))


def _validate_markets(markets: Mapping[str, Market],
                      languages: Mapping[str, Language],
                      source_ids: set[str] | None) -> list[str]:
    errs: list[str] = []
    seen_order: dict[int, str] = {}
    seen_i18n: dict[str, str] = {}
    seen_flag: dict[str, str] = {}
    for code, m in markets.items():
        p = f"市场 {code}"
        if m.code != code:
            errs.append(f"{p}: code 与 key 不一致 ({m.code!r})")
        if not RE_CODE.match(m.code):
            errs.append(f"{p}: code 必须是大写 2–3 位（ISO 3166-1 alpha-2 / 区域码）")
        if m.kind not in ALLOWED_KINDS:
            errs.append(f"{p}: kind 必须是 {ALLOWED_KINDS}")
        if not isinstance(m.order, int) or m.order <= 0:
            errs.append(f"{p}: order 必须是正整数")
        if m.order in seen_order:
            errs.append(f"{p}: order={m.order} 与 {seen_order[m.order]} 重复")
        seen_order.setdefault(m.order, m.code)
        if m.parent:
            if m.parent not in markets:
                errs.append(f"{p}: parent={m.parent} 未注册")
            elif markets[m.parent].kind != KIND_REGION:
                errs.append(f"{p}: parent={m.parent} 不是 region")
            elif m.parent == m.code:
                errs.append(f"{p}: parent 不能指向自己")
        if m.kind == KIND_REGION and m.parent:
            errs.append(f"{p}: region 不能再有 parent（本轮只支持一层区域）")
        if m.flag:
            if not _valid_flag(m.flag):
                errs.append(f"{p}: flag={m.flag!r} 必须是两个 regional indicator（如 🇺🇸）")
            if m.flag in seen_flag:
                errs.append(f"{p}: flag 与 {seen_flag[m.flag]} 重复")
            seen_flag.setdefault(m.flag, m.code)
        for lang_key in ("en", "es", "zh"):
            if not (m.name.get(lang_key) or "").strip():
                errs.append(f"{p}: name 缺 {lang_key}（站点 3 种 UI 语言都需要）")
        if m.group and m.group not in ALLOWED_GROUPS:
            errs.append(f"{p}: group={m.group!r} 不在 {ALLOWED_GROUPS}")
        if not m.languages and m.kind == KIND_COUNTRY:
            errs.append(f"{p}: country 市场的 languages 不能为空")
        if not m.languages and m.kind == KIND_REGION and m.enabled:
            errs.append(f"{p}: 启用的 region 必须声明至少一种语言")
        for lang_code in m.languages:
            if lang_code not in languages:
                errs.append(f"{p}: languages 引用了未注册语言 {lang_code}")
        if not m.default_lang:
            errs.append(f"{p}: default_lang 必填")
        elif m.default_lang not in languages:
            errs.append(f"{p}: default_lang={m.default_lang} 未注册")
        elif m.languages and m.default_lang not in m.languages:
            errs.append(f"{p}: default_lang={m.default_lang} 不在 languages 列表里")

        if m.enabled:
            if not m.group:
                errs.append(f"{p}: 启用市场必须有 group（导航分组）")
            if not _valid_flag(m.flag):
                errs.append(f"{p}: 启用市场必须有合法 flag")
            if not RE_I18N_KEY.match(m.i18n_key):
                errs.append(f"{p}: 启用市场 i18n_key 需匹配 home.<code>")
            if m.i18n_key in seen_i18n:
                errs.append(f"{p}: i18n_key 与 {seen_i18n[m.i18n_key]} 重复")
            seen_i18n.setdefault(m.i18n_key, m.code)
            if not m.source_id:
                errs.append(f"{p}: 启用市场必须有 source_id")
            if m.default_lang and languages.get(m.default_lang) \
                    and not languages[m.default_lang].enabled:
                errs.append(f"{p}: default_lang={m.default_lang} 未启用")
            for lang_code in m.languages:
                if languages.get(lang_code) and not languages[lang_code].enabled:
                    errs.append(f"{p}: 启用了未启用的语言 {lang_code}")
        else:
            if m.i18n_key and not RE_I18N_KEY.match(m.i18n_key):
                errs.append(f"{p}: i18n_key 格式应为 home.<code>（禁用占位可为空）")
            if m.source_id is None and m.extra_source_ids:
                errs.append(f"{p}: 禁用占位不应挂 extra_source_ids（source_id 为空）")

        for sid in ([m.source_id] if m.source_id else []) + list(m.extra_source_ids):
            if source_ids is not None and sid not in source_ids:
                errs.append(f"{p}: source_id={sid} 不在 DB source 表（先登记数据来源）")

    # enabled region 必须有 enabled 子市场（防止空区域上线）
    children: dict[str, list[str]] = {}
    for m in markets.values():
        if m.parent:
            children.setdefault(m.parent, []).append(m.code)
    for code, m in markets.items():
        if m.kind == KIND_REGION and m.enabled:
            kids = [c for c in children.get(code, []) if markets[c].enabled]
            if not kids:
                errs.append(f"市场 {code}: 启用的 region 至少要有 1 个启用的子市场")
    return errs


def _validate_languages(languages: Mapping[str, Language],
                        markets: Mapping[str, Market],
                        planned_markets: tuple[str, ...]) -> list[str]:
    errs: list[str] = []
    seen_order: dict[int, str] = {}
    seen_hreflang: dict[str, str] = {}
    seen_path: dict[str, str] = {}
    seen_prefix: dict[str, str] = {}
    seen_label: dict[str, str] = {}
    known_countries = set(markets) | set(planned_markets)
    for code, lang in languages.items():
        p = f"语言 {code}"
        if lang.code != code:
            errs.append(f"{p}: code 与 key 不一致 ({lang.code!r})")
        if not RE_LANG.match(lang.code):
            errs.append(f"{p}: code 不是合法 BCP47 片段（en / zh-Hant / pt-BR…）")
        if lang.script not in ALLOWED_SCRIPTS:
            errs.append(f"{p}: script={lang.script!r} 不在 {ALLOWED_SCRIPTS}")
        if lang.dir not in ALLOWED_DIRS:
            errs.append(f"{p}: dir={lang.dir!r} 必须是 {ALLOWED_DIRS}")
        if not RE_HREFLANG.match(lang.hreflang or ""):
            errs.append(f"{p}: hreflang={lang.hreflang!r} 不合法")
        if lang.hreflang in seen_hreflang:
            errs.append(f"{p}: hreflang 与 {seen_hreflang[lang.hreflang]} 重复")
        seen_hreflang.setdefault(lang.hreflang, code)
        ok_path = lang.path == "" or bool(RE_PATH.match(lang.path))
        if not ok_path:
            errs.append(f"{p}: path={lang.path!r} 必须为空或形如 'es/'")
        if lang.path in seen_path and lang.path != "":
            errs.append(f"{p}: path 与 {seen_path[lang.path]} 重复")
        seen_path.setdefault(lang.path, code)
        if not lang.i18n_key_prefix:
            errs.append(f"{p}: i18n_key_prefix 必填（站点 I18N 字典段名）")
        if lang.i18n_key_prefix in seen_prefix:
            errs.append(f"{p}: i18n_key_prefix 与 {seen_prefix[lang.i18n_key_prefix]} 重复")
        seen_prefix.setdefault(lang.i18n_key_prefix, code)
        if not (1 <= len(lang.ui_label) <= 8):
            errs.append(f"{p}: ui_label 长度需 1–8（语言切换按钮）")
        if lang.ui_label in seen_label:
            errs.append(f"{p}: ui_label 与 {seen_label[lang.ui_label]} 重复")
        seen_label.setdefault(lang.ui_label, code)
        if not isinstance(lang.order, int) or lang.order <= 0:
            errs.append(f"{p}: order 必须是正整数")
        if lang.order in seen_order:
            errs.append(f"{p}: order={lang.order} 与 {seen_order[lang.order]} 重复")
        seen_order.setdefault(lang.order, code)
        if not lang.native_name.strip():
            errs.append(f"{p}: native_name 不能为空")
        for lang_key in ("en", "es", "zh"):
            if not (lang.name.get(lang_key) or "").strip():
                errs.append(f"{p}: name 缺 {lang_key}")
        if not lang.default_country:
            errs.append(f"{p}: default_country 必填")
        elif lang.default_country not in known_countries:
            errs.append(f"{p}: default_country={lang.default_country} 既不在 markets 也不在 planned_markets")
        elif lang.default_country in markets:
            mk = markets[lang.default_country]
            if lang.code not in mk.languages:
                errs.append(f"{p}: default_country={lang.default_country} 的 languages 未包含该语言")
            if lang.enabled and not mk.enabled:
                errs.append(f"{p}: enabled 语言的 default_country={lang.default_country} 未启用")
    return errs


def _validate_cross(markets: Mapping[str, Market],
                    languages: Mapping[str, Language],
                    planned_markets: tuple[str, ...]) -> list[str]:
    errs: list[str] = []
    # 每种 enabled 语言必须有 enabled 默认市场，且该市场把语言列进 languages
    for lang in languages.values():
        if not lang.enabled:
            continue
        mk = markets.get(lang.default_country)
        if mk is None:
            errs.append(f"语言 {lang.code}: enabled 但默认市场 {lang.default_country} 未注册")
        elif not mk.enabled:
            errs.append(f"语言 {lang.code}: enabled 但默认市场 {lang.default_country} 未启用")
        elif lang.code not in mk.languages:
            errs.append(f"语言 {lang.code}: 默认市场 {lang.default_country} 未声明该语言")
    # 每个 enabled 市场的 default_lang 必须是 enabled 语言
    for m in markets.values():
        if not m.enabled:
            continue
        lang = languages.get(m.default_lang)
        if lang is None:
            errs.append(f"市场 {m.code}: default_lang={m.default_lang} 未注册")
        elif not lang.enabled:
            errs.append(f"市场 {m.code}: default_lang={m.default_lang} 未启用")
    # planned_markets 不应与已注册市场冲突（planned 是未来国家，注册后要从 planned 移除）
    for code in planned_markets:
        if code in markets:
            errs.append(f"planned_markets 含已注册市场 {code}（注册后应移除）")
    return errs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_summary(reg: MarketsRegistry) -> None:
    print(f"== 市场/语言注册表 v{reg.schema_version} · {reg.updated} ==")
    print(f"\n市场 {len(reg.markets)} 个（启用 {len(reg.enabled_markets)}）:")
    print(f"  {'code':<4} {'kind':<8} {'flag':<4} {'order':>5}  {'source_id':<16} "
          f"{'lang':<8} {'group':<8} name(en/zh)")
    for m in sorted(reg.markets.values(), key=lambda x: (x.order, x.code)):
        print(f"  {m.code:<4} {m.kind:<8} {m.flag:<4} {m.order:>5}  "
              f"{(m.source_id or '-'):<16} {(m.default_lang or '-'):<8} "
              f"{(m.group or '-'):<8} {m.display_name('en')} / {m.display_name('zh')}"
              f"{'' if m.enabled else '  [disabled]'}"
              f"{f'  parent={m.parent}' if m.parent else ''}")
    print(f"\n语言 {len(reg.languages)} 个（启用 {len(reg.enabled_languages)}）:")
    print(f"  {'code':<8} {'hreflang':<9} {'path':<10} {'label':<5} {'default':<8} script")
    for x in sorted(reg.languages.values(), key=lambda v: (v.order, v.code)):
        print(f"  {x.code:<8} {x.hreflang:<9} {(x.path or '(root)'):<10} {x.ui_label:<5} "
              f"{x.default_country:<8} {x.script}"
              f"{'' if x.enabled else '  [disabled]'}")
    print(f"\nhreflang → 路径: {reg.hreflang_map()}")
    print(f"国家规范顺序: {', '.join(reg.country_order)}")


def main(argv: list[str] | None = None) -> int:
    # 管道输出统一 UTF-8，避免 Windows 控制台代码页让调用方按 UTF-8 解码失败
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="市场/语言注册表：读取、校验、导出 JSON")
    ap.add_argument("--json", action="store_true", help="输出合并后的注册表 JSON")
    ap.add_argument("--check", action="store_true", help="只校验；有错退出码 1")
    ap.add_argument("--no-db", action="store_true", help="不连 DB，跳过 source_id 存在性校验")
    ap.add_argument("--markets", default=None, help="覆盖 markets.json 路径")
    ap.add_argument("--languages", default=None, help="覆盖 languages.json 路径")
    args = ap.parse_args(argv)

    try:
        reg = MarketsRegistry.load(args.markets, args.languages, use_db=not args.no_db)
    except (FileNotFoundError, ValueError) as e:
        print(f"!! {e}", file=sys.stderr)
        return 2
    errs = reg.validate()
    if args.json:
        print(json.dumps(reg.as_dict(), ensure_ascii=False, indent=2))
        return 1 if (args.check and errs) else 0
    if not args.check:
        _print_summary(reg)
        print()
    if errs:
        print(f"!! 校验失败 {len(errs)} 项:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("校验通过：市场/语言注册表一致" if not args.check else "OK: 注册表校验通过")
    if reg.source_ids is None:
        print("（注意：未读取到 DB source 表，已跳过 source_id 存在性校验；用默认 DB 或传 --no-db 明确）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
