"""静态站生成：SQLite → site/dist/

产物：
    index.html          搜索（客户端匹配，返回候选集与碰撞提示）
    drug/<id>.html      成分身份卡（各国商品名对照）
    name/<id>.html      名字页（这个名字下挂了哪些药——碰撞页）
    confused.html       FDA tall-man 易混淆药对
    about.html          数据来源、覆盖率、免责
    whats-new.html      更新日志（由 CHANGELOG.md 生成）
    404.html            路径不存在时的兜底页
    robots.txt          全站可抓 + sitemap 地址
    sitemap.xml         全站 HTML 的 sitemap
    data/index.json     旧检索索引（v0.6.1 起默认不再生成；仅 WRITE_LEGACY_INDEX=1 过渡写）
    data/idx/core.json  检索索引唯一真相源（列式 + 字典编码；客户端 decodeCore 解码）
    data/idx/legacy-mini.json  可选二级兜底（WRITE_LEGACY_MINI=1 时生成；core 损坏时用）
    data/aliases.json   俗称 / 街头叫法 / 类别词索引
    data/confused.json  易混淆药对索引
    assets/             css + js

用法：python site/build.py
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# v0.10.2：口语类别词表（退烧药 / 降压药 / painkiller…）的唯一来源在 lib/categories.py，
# 构建期把同一份表写进 data/categories.json（客户端 aliases）与 data/idx/cats.json（words）。
# build.py 不是包，直接跑时 sys.path[0] 是 site/，所以先把仓库根加进去。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from lib.categories import (  # noqa: E402  （必须在 sys.path 插入之后）
    COLLOQUIAL_ALIASES,
    assert_no_unlisted_shadow,
    cat_norm,
    colloquial_aliases_by_category,
)

DB = ROOT / "data" / "drugs.db"
# 默认 site/dist；SITE_OUT 允许并发构建到独立目录，避免两个进程互相 rmtree。
OUT = Path(os.environ.get("SITE_OUT") or (ROOT / "site" / "dist"))
# 报错入口：静态站没有后端，用 GitHub Issue 收集纠错，附上查询词和页面 URL。
REPORT_REPO = "https://github.com/fuarnos/drug-brand-crossref"
# 公开站根地址：404 页、robots.txt、sitemap.xml、canonical / hreflang / OG 里要用绝对 URL。
# 2026-11-12 用户定新口径：主站 = 自有域名 drugcrossref.com，gh-pages 只作备份；
# 所以这里一律写主域（gh-pages 上的 canonical 指主域是预期行为）。
SITE_URL = "https://drugcrossref.com/"
# 构建版本号：给 css/js/json 带 ?v=，避免用户拿到缓存里的旧代码。
# v0.9.9 task-14：从 `int(time.time())` 改成「输入内容哈希」。
# 旧写法每次构建都换号 → 121,280 个产物里 112,692 个（每页 <head> 的 ?v=）逐字节全变，
# gh-pages 发布 diff 爆到 11 万文件、GitHub Pages 构建反复超时。内容哈希保证：
# 同一份源码 + 同一份数据，两次构建逐字节一致；只有输入真的变了才换号。
BUILD_V = ""  # main() 开头用 _compute_build_v() 写定（要等模块常量就位）

CHANGELOG = ROOT / "CHANGELOG.md"

# v0.6.2：繁体中文（zh-Hant）UI。字典来自 data/i18n_zh_hant.json（由简体 I18N 经
# OpenCC + 台湾用语表转换，247 键）；缺键回退简体 zh。搜索输入繁体→简体归一用
# data/zh_hant_t2s.json（OpenCC TSCharacters 常用字子集，构建期注入 app.js）。
ZH_HANT_I18N_FILE = ROOT / "data" / "i18n_zh_hant.json"
ZH_HANT_T2S_FILE = ROOT / "data" / "zh_hant_t2s.json"

# v0.10.2：四语（en / es / zh / zh-Hant）一致性守卫。用户规则（2026-11-10）：
# 多语言翻译必须同步更新、写进底层逻辑，缺译不许静默回落。这里记录「只能回落简体」
# 的 zh-Hant key，main() 里由 _assert_i18n_complete() 判定是否允许构建。
I18N_REQUIRED_LANGS = ("en", "es", "zh", "zh-Hant")
ZH_HANT_FALLBACK_KEYS: list[str] = []
# 允许回落简体的 zh-Hant key（历史遗留，补上繁体值后请从这里删掉；新 key 一律不许进）
ZH_HANT_FALLBACK_OK: set[str] = set()


def _sha1_inputs(*paths: Path) -> str:
    """把若干输入文件的「名字 + 内容」串起来做 sha1（缺失文件用占位符，不抛错）。"""
    h = hashlib.sha1()
    for p in paths:
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


def _compute_build_v() -> str:
    """构建版本号 = 静态资源源码的内容哈希（task-14，替代 time.time()）。

    只哈希「决定 css/js 字节」的输入：build.py 自身（CSS / APP_JS / BILINGUAL_JS /
    ATC4_JS / LANG_META_JS 都是本文件里的常量）+ zh-Hant 两份字典。
    **刻意不含数据库**：数据更新（最常见的一类发布）不该让 12 万页的 ?v= 全变；
    资源文件的缓存 TTL（GitHub Pages 10 分钟）与 HTML 同量级，数据新鲜度不受影响。
    结果转成十进制数字串，保持线上 `?v=<数字>` 的既有形状（deploy/verify_live.py 会校验）。
    """
    digest = _sha1_inputs(Path(__file__).resolve(), ZH_HANT_I18N_FILE, ZH_HANT_T2S_FILE)
    # 取 8 位十六进制转十进制并定宽补零：恒为 10 位数字，与旧的时间戳同宽
    # （121k 页 × 每页 2–4 处 ?v=，宽度变化会让 dist 体积无谓变动）。
    return f"{int(digest[:8], 16):010d}"


def _load_json_file(path: Path) -> dict:
    """读 JSON 对象；文件缺失/损坏返回 {}（构建不因此失败）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_zh_hant_dict() -> dict[str, str]:
    payload = _load_json_file(ZH_HANT_I18N_FILE)
    mapping = payload.get("zh-Hant") or {}
    return {str(k): str(v) for k, v in mapping.items()} if isinstance(mapping, dict) else {}


def _load_zh_hant_t2s() -> dict[str, str]:
    payload = _load_json_file(ZH_HANT_T2S_FILE)
    mapping = payload.get("map") or {}
    return {str(k): str(v) for k, v in mapping.items()} if isinstance(mapping, dict) else {}


def _subst_placeholders(text: str, values: dict) -> str:
    for key, val in values.items():
        text = text.replace("@@" + str(key) + "@@", str(val))
    return text


def _env_value(key: str, default: str = "") -> str:
    """从环境变量或仓库根 .env 读配置（.env 不入库，供本机构建用）。"""
    val = os.environ.get(key, "").strip()
    if val:
        return val
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


# 访问统计：GoatCounter（cookieless，后台看 PV/UV/来源/国家/浏览器/屏幕尺寸）。
# code 放 .env 的 GOATCOUNTER_CODE=...；不配置就不注入脚本，站点完全不受影响。
GOATCOUNTER_CODE = re.sub(r"[^A-Za-z0-9_-]", "", _env_value("GOATCOUNTER_CODE"))
GC_TAG = (
    f'\n<script data-goatcounter="https://{GOATCOUNTER_CODE}.goatcounter.com/count"'
    f' async src="https://gc.zgo.at/count.js"></script>'
) if GOATCOUNTER_CODE else ""


def _read_latest_release() -> tuple[str, str]:
    """页脚显示的版本：CHANGELOG 最上面的 ## vX — date。"""
    try:
        text = CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    m = re.search(r"^## (v[0-9][^\s]*)\s*[—–-]\s*(\d{4}-\d{2}-\d{2})", text, re.M)
    return (m.group(1), m.group(2)) if m else ("", "")


LATEST_VERSION, LATEST_DATE = _read_latest_release()

DISEASE_NOTE = (
    "本站只做「名字 → 成分」的标识对应，不提供用药建议、"
    "不换算服药剂量、不建议替换药品。"
)

# 三语界面文案。英文是默认、也是 HTML 里的兜底文本；
# 页面加载后 i18n.js 按 ?lang= / localStorage / 浏览器语言替换带 data-i18n 的元素。
I18N = {
    "en": {
        "nav.search": "Search", "nav.confused": "Confused names", "nav.about": "About",
        "nav.whatsnew": "What's new",
        # 2026-11-11 UI：壳与搜索区的 aria-label 走 i18n（原来四处硬编码英文）
        "nav.primary": "Primary navigation", "nav.more": "More",
        "nav.sections": "Sections",
        "nav.search_compact": "Search a name",
        # 2026-11-11 UI：H1 三语统一口径「查一个药名，看它在各国是什么」（spec §3.5）
        "home.h1": "Look up a medicine name — see what it is in each country",
        "home.sub": ("Brand name, generic name, nickname, or a line from the pack — Chinese, "
                     "full-width and Cyrillic input all work."),
        # 候选集单独一行（16px 正常前景色），不再埋在 home.sub 第二句里
        "home.candidate": "You always get a candidate set, never a single answer.",
        # 2026-11-12 v0.11.2（条目 8）：首页三步流程（输名 → 确认产品 → 选目标市场）。
        # 搜索框上方常驻一条紧凑流程；有查询时由 .has-q 隐藏，不占结果首屏。
        "flow.s1": "Name", "flow.s2": "Confirm product", "flow.s3": "Target market",
        "home.recent": "Recently updated",
        "home.recent_all": "See all updates →",
        "home.ph": "Brand name / generic name / nickname / a line from the pack",
        "home.all": "All countries and regions", "home.us": "United States",
        "home.gb": "United Kingdom", "home.cn": "China", "home.es": "Spain",
        "home.mx": "Mexico", "home.au": "Australia", "home.ca": "Canada",
        "home.sg": "Singapore",
        "home.tw": "Taiwan",
        "home.hk": "Hong Kong",
        "home.eu": "European Union (EU)",
        "home.fr": "France",
        "coverage.gap.fr": ("BDPM (ANSM) — Licence Ouverte / etalab-2.0, attribution required; "
                            "update date in the data package; authorisation ≠ on sale."),
        "about.fr_source": ('<p class="sub"><b>France</b> : BDPM (Base de données publique des '
                            'médicaments, ANSM), <b>Licence Ouverte / etalab-2.0</b>; attribution '
                            'and update date required. Data as of <b>2026-11-03</b>. Facts only '
                            '(name, ingredient, form, manufacturer, authorisation). '
                            '<a href="https://base-donnees-publique.medicaments.gouv.fr/">BDPM</a>.</p>'),
        "eu.region_title": "EU centralised authorisation (EMA)",
        "eu.region_note": ("Authorised at EU level — not a record of sale in any single country. "
                           "The EU register carries no strength, dosage form or pack size."),
        "eu.coverage_note": ("EU regional layer — central authorisations only; "
                             "authorisation ≠ on sale in each country."),
        "coverage.gap.eu": ("Regional layer: central authorisations (EMA / EC Union Register). "
                            "No strength, form or pack size; authorisation ≠ on sale in a country."),
        "home.coverage": ("An empty result does not mean the medicine does not exist. "
                          "Coverage (countries and regions):"),
        "home.loading": "Loading index…",
        "home.hint_idle": ("First search loads one index shard (median ~1.0 MB, ~0.16 MB gzip); "
                           "the full index (core ~42 MB raw, ~9–10 MB gzip) fills in the "
                           "background — start typing, focus the search box, or pick a sample."),
        "home.hint_loading": "Loading an index shard (median ~1.0 MB, ~0.16 MB gzip)…",
        # v0.6.6：成分页多国并排矩阵
        "matrix.spec": "Strength / form / release",
        "matrix.original": "Recorded as",
        "matrix.none": "not recorded",
        "matrix.country_all": "All",
        "matrix.country_clear": "Clear",
        "matrix.market_count": "Markets {shown}/{total}",
        "matrix.empty_markets": "Select at least one market to show columns.",
        "matrix.scroll_hint": "Scroll horizontally for more markets →",
        "matrix.hidden_note": ("Discontinued, withdrawn or unverified-status products are hidden "
                               "by default; Hong Kong and Australia records are shown as "
                               "exceptions."),
        "matrix.capped": "Showing the first {shown} of {total} strength/form rows.",
        "matrix.hk_note": ("Hong Kong records are name/ingredient-level only: no strength, "
                           "dosage form or registration status; being on the register does not "
                           "prove current supply."),
        "matrix.au_note": ("Australia ARTG data has no registration-status column, so status is "
                           "shown as unknown; being on the register does not mean currently "
                           "marketed."),
        # v0.6.7：/warn 分页
        "warn.page_prev": "Previous", "warn.page_next": "Next",
        "warn.pagination": "Warning pages",
        "warn.page_status": "Page {n} of {total} · {count} warnings",
        "error.index_failed": "The index failed to load.",
        "error.local_file": ("If you opened this page directly, the browser blocks local file "
                             "reads — run python -m http.server and visit "
                             "http://localhost:8000/."),
        "error.retry": "Retry",
        "res.matched": "names matched", "res.none": "No match",
        "res.brands": "brand names found",
        "res.alias": "alias matched",
        "res.alias_no_products": "not a single product — see the note above",
        "res.notin": "Not covered in this country",
        "res.caveat": "an empty result does not mean the drug does not exist",
    "res.partial": "partial results — loading the full index…",
        "artg.title": "Also on the ARTG (ingredient not captured yet)",
        "artg.note": ("These entries are registered in Australia, but this site has not linked "
                      "them to an active ingredient yet — so they are not shown as products."),
        "artg.sponsor": "Sponsor", "artg.id": "ARTG ID",
        "res.fuzzy": "No exact match — closest names",
        "card.packs": "packs",
        "col.ing": "Ingredient", "col.dose": "Dose",
        "col.brand": "Brand", "col.mah": "Manufacturer",
        "same.ing": "Other products with the same ingredient",
        "same.note": "You searched a brand name — this is what else contains the same active ingredient.",
        "same.warning": "Same name or same ingredient does not mean interchangeable.",
        "same.related": "Contains one of the same ingredients (not the same composition)",
        "same.related_note": "These records share at least one ingredient with your search, but the full ingredient sets differ. They are not the same product.",
        "res.records_noun": "records",
        "res.matched_name": "Matched name",
        "res.no_brand_note": "{n} record(s) have no trade name and are shown at name level.",
        # v0.9.7 task-12 UI 批次 A-1：结果页身份卡 / 分页 / 零结果三动作（ES 同理）
        "res.identity.ingredient": "Active ingredient",
        "res.identity.markets": "Markets covered",
        "res.identity.records": "{n} records",
        "res.same_name": "Same name, different drug",
        "res.not_interchangeable": "Not interchangeable across markets",
        "res.identity_note": ("The same name can point to a different ingredient in another "
                              "market. Check the ingredient, strength and form — not just the name."),
        "res.action_drug": "Open ingredient page",
        "res.action_copy": "Copy generic name",
        # 2026-11-11 v0.11.2（条目 9/10）：身份卡标题 + 折叠摘要 + 来源市场（?src=）
        "res.identity_title": "candidate 1 of {n}",
        "res.more_detail": "More strengths / more records",
        "res.src_label": "Source market (only records from):",
        "res.src_all": "All source markets",
        "res.src_active": "source market {c}",
        "res.empty_h1": "No match for “{q}”",
        "res.empty_spelling": "Check the spelling, or try the generic name",
        "res.empty_browse": "Browse by category",
        "res.empty_coverage": "See coverage & freshness",
        "res.details": "Details",
        "res.col_market": "Market",
        "res.showing": "Showing {n} of {total}",
        "badge.severe": "Same name, different drug",
        "badge.warning": "Different release",
        "badge.combo": "Combination",
        "fam.title": "The same brand in other markets",
        "fam.warn": "Same brand, different drug",
        "drug.brand": "Brand", "drug.strength": "Strength", "drug.nostrength": "not disclosed",
        "drug.release": "Release", "drug.status": "Status",
        "drug.status.active": "active", "drug.status.discontinued": "discontinued",
        "drug.status.withdrawn": "withdrawn", "drug.status.unknown": "unknown",
        "drug.status_note.discontinued": "expired",
        "drug.status_note.withdrawn": "market authorisation withdrawn",
        "drug.status_note.unknown": "validity unknown",
        "drug.no_brand": "(no brand name)", "drug.also_called": "Also called:",
        # v0.9.6 task-141c：同一成分的「同物异名」（data/substance_aliases.csv）——
        # 只列出别的写法，不翻译、不改主名；与俗称（also_called）分开显示。
        "drug.also_known": "Also known as:", "syn.tag": "synonym",
        "brand.none": "No trade name",
        "a11y.skip": "Skip to content",
        "ingredient.unrecorded": "Ingredient not recorded (name-level)",
        "badge.export_only": "Export only",
        "drug.records": "records", "drug.showing": "showing first 40 of",
        "drug.sid": "Substance ID",
        "drug.notice": ("The same ingredient can carry completely different brand names in "
                        "different countries, and the same name can point to a different "
                        "ingredient. Listed by country — not interchangeable."),
        "drug.empty": "No products recorded yet.",
        "drug.confused": "Easily confused with",
        "drug.confused_note": ("FDA recommends tall-man lettering for this pair; check the "
                               "ingredient, not the name."),
        "drug.confused_all": "All pairs",
        "name.countries": "Countries & regions", "name.form": "Form",
        "name.strength": "Strength", "name.release": "Release",
        "name.also": "Also written as", "name.found": "Found in",
        "name.empty": "No records",
        "name.single_note": "Only one product record for this name so far.",
        "name.severe": ("This brand name points to different active ingredients in different "
                        "countries or variants. Check the composition, never treat the names "
                        "as equivalent."),
        "name.warning": ("Same name, but immediate vs modified release — not interchangeable."),
        "nick.hit": "Nickname",
        "nick.slang": "internet nickname", "nick.legacy": "older name",
        "nick.translit": "transliterated old name", "nick.abbrev": "abbreviation",
        "nick.misnomer": "common misnomer",
        "nick.unverified": "user-provided (unverified)",
        "nick.community": "community name",
        "nick.source": "Source",
        "nick.tag": "nickname",
        "nick.street": "US street name", "nick.folk": "folk name",
        "nick.class": "class term",
        "nick.class_caveat": ("This is a class term, not a specific medicine — it can cover "
                              "several ingredients. Check the ingredient."),
        "nick.folk_caveat": ("This is a folk/category term, not a specific medicine — it can "
                             "cover several ingredients. A product whose name contains the "
                             "term is not necessarily in that class; check the ingredient."),
        "nick.nomap_caveat": ("This term points to a substance with no marketed product in "
                              "this database, so no product list is shown."),
        "nick.ambiguous": ("This nickname may point to more than one ingredient — "
                           "check the composition."),
        "nick.caveat": ("Nicknames point to an ingredient, not to a specific pack: the same "
                        "ingredient is sold under different brand names in each country."),
        # task-141c：同物异名（INN vs USAN / 拼写变体）命中的身份卡，与俗称卡区分。
        "nick.synonym": "synonym",
        "nick.synonym_hit": "Also known as",
        "nick.synonym_caveat": ("Another name for the same active ingredient (INN vs USAN or a "
                                "spelling variant). It identifies the ingredient — products in "
                                "different countries are still not interchangeable."),
        "footer": ("Information only — not medical advice, and no substitute for a pharmacist."),
        "report.link": "Report a data error",
        "report.all": "Known issues",
        "report.note": "Wrong ingredient, wrong dose, or a drug we do not have? Tell us:",
        "report.cta": "Report this result",
        "report.issue_title": "Data error: ",
        "report.field_query": "Query", "report.field_page": "Page",
        "report.field_expected": "Expected result", "report.field_actual": "Actual result",
        "report.field_pack": "Pack or lot",
        "conf.title": "Easily confused drug names",
        "conf.intro": ("Look-alike / sound-alike pairs from the FDA Name Differentiation Project. "
                       "This is the official tall-man list, not the full ISMP LASA list."),
        "conf.note": ("A pair here means the names can be mistaken for each other; it does not "
                      "mean the drugs are interchangeable. FDA recommends tall-man lettering."),
        "conf.pair": "Pair", "conf.tml": "Tall-man spelling",
        "conf.search_hit": "This name is easily confused with",
        # 2026-11-11 v0.11.2（条目 10）：这个控件的语义一直是「目标市场」——查询词先定位成分
        #（不受国家限制），再把这个成分在该国的商品名列出来（见 APP_JS render() 的注释）。
        # 这里只把话说清，`?country=` 的语义与 URL 一字不动；来源市场另用新增的 `?src=`。
        "home.country_label": "Target market: show the names used there (optional)",
        # 2026-11-11 UI：国家/地区下拉收进「更多筛选」details，summary 用这句
        "home.country_summary": "Target market (optional)",
        # 2026-11-11 UI：可见提交按钮 + 「/ 聚焦」提示 + 自动完成列表的无障碍名
        "home.submit": "Search", "home.slash_hint": "Press / to focus",
        "home.suggestions": "Suggestions",
        "home.country_label_sel": "Target market: see what it is called in {country}:",
        "country.missing": "This country/region has no product listed under this name.",
        "country.missing_note": ("The name matched an ingredient, not a product in this "
                                 "country/region. Switch country/region or open the ingredient page."),
        "country.open_card": "Ingredient page",
        "country.change": "Change country/region",
        "parse.label": "Parsed query",
        "parse.name": "Name", "parse.dose": "Dose", "parse.form": "Form",
        "parse.match": "Match",
        "parse.match.exact": "exact", "parse.match.compact": "joined",
        "parse.match.prefix": "prefix", "parse.match.contains": "substring",
        "parse.match.fuzzy": "fuzzy", "parse.match.nickname": "alias",
    "parse.match.pinyin": "pinyin",
        "parse.match.country": "country view", "parse.match.none": "no match",
        "ac.suggestions": "Suggestions",
        "res.brands_noun": "brands",
        "res.show_brands": "Show all brands",
        "res.fold": "Show fewer",
        "res.load_more": "Load more",
        "res.loaded_all": "All results shown",
        "res.copy": "Copy table", "res.csv": "Download CSV",
        "res.copied": "Copied", "res.copy_fail": "Copy failed — select the table manually",
        "res.col_country": "Countries & regions", "res.col_form": "Form",
        "res.col_match": "Match", "res.col_link": "Page",
        "a3.salt": "Salt forms:", "a3.release": "Release:",
        "a3.incompat": "Not interchangeable — see warning",
        "row.report": "Report this row",
        "report.field_row": "Row",
        "a1.expand": "Details", "a1.loading": "Loading details…",
        "a1.none": "No product records for this name.",
        "a1.goto": "Open substance page",
        "a1.market": "Market", "a1.pack": "Pack", "a1.approval": "Approval / NDC / DIN",
        "a1.status": "Status", "a1.source": "Source", "a1.raw": "Original record",
        "a1.more": ("Showing the first 12 records; see the <a href=\"{url}\">"
                    "substance page</a> for all."),
    },
    "es": {
        "nav.search": "Buscar", "nav.confused": "Nombres confundibles", "nav.about": "Acerca de",
        "nav.whatsnew": "Novedades",
        "nav.primary": "Navegación principal", "nav.more": "Más",
        "nav.sections": "Secciones",
        "nav.search_compact": "Buscar un nombre",
        "home.h1": "Busca un nombre de medicamento y mira qué es en cada país",
        "home.sub": ("Nombre comercial, genérico, apodo o una línea del envase — también funciona "
                     "en chino, ancho completo y cirílico."),
        "home.candidate": "Siempre obtienes un conjunto de candidatos, nunca una única respuesta.",
        # v0.11.2（条目 8）：三步流程，与 en/zh 同步
        "flow.s1": "Nombre", "flow.s2": "Confirmar producto", "flow.s3": "Mercado destino",
        "home.recent": "Novedades recientes",
        "home.recent_all": "Ver todas las novedades →",
        "home.ph": "Nombre comercial / genérico / apodo / una línea del envase",
        "home.all": "Todos los países y regiones", "home.us": "Estados Unidos",
        "home.gb": "Reino Unido", "home.cn": "China", "home.es": "España",
        "home.mx": "México", "home.au": "Australia", "home.ca": "Canadá",
        "home.sg": "Singapur",
        "home.tw": "Taiwán",
        "home.hk": "Hong Kong",
        "home.eu": "Unión Europea (UE)",
        "home.fr": "Francia",
        "coverage.gap.fr": ("BDPM (ANSM) — Licence Ouverte / etalab-2.0, atribución obligatoria; "
                            "fecha de actualización en el paquete de datos; autorización ≠ venta."),
        "about.fr_source": ('<p class="sub"><b>Francia</b> : BDPM (Base de données publique des '
                            'médicaments, ANSM), <b>Licence Ouverte / etalab-2.0</b>; atribución y '
                            'fecha de actualización obligatorias. Datos a <b>2026-11-03</b>. Solo '
                            'hechos (nombre, principio, forma, fabricante, autorización). '
                            '<a href="https://base-donnees-publique.medicaments.gouv.fr/">BDPM</a>.</p>'),
        "eu.region_title": "Autorización centralizada de la UE (EMA)",
        "eu.region_note": ("Autorizado a nivel de la UE: no es un registro de venta en ningún país "
                           "concreto. El registro de la UE no incluye dosis, forma farmacéutica "
                           "ni tamaño de envase."),
        "eu.coverage_note": ("Capa regional de la UE: solo autorizaciones centralizadas; "
                             "autorización ≠ venta en cada país."),
        "coverage.gap.eu": ("Capa regional: autorizaciones centralizadas (EMA / Registro de la Unión). "
                            "Sin dosis, forma ni envase; autorización ≠ venta en un país."),
        "home.coverage": ("Un resultado vacío no significa que el medicamento no exista. "
                          "Cobertura (países y regiones):"),
        "home.loading": "Cargando el índice…",
        "home.hint_idle": ("La primera búsqueda carga un fragmento del índice (mediana ~1,0 MB; "
                           "~0,16 MB gzip); el índice completo (core ~42 MB sin comprimir, "
                           "~9–10 MB gzip) se completa en segundo plano — empieza a escribir, "
                           "enfoca el buscador o elige un ejemplo."),
        "home.hint_loading": "Cargando un fragmento del índice (mediana ~1,0 MB; ~0,16 MB gzip)…",
        # v0.6.6：成分页多国并排矩阵
        "matrix.spec": "Concentración / forma / liberación",
        "matrix.original": "Registrado como",
        "matrix.none": "no consta",
        "matrix.country_all": "Todos",
        "matrix.country_clear": "Ninguno",
        "matrix.market_count": "Mercados {shown}/{total}",
        "matrix.empty_markets": "Selecciona al menos un mercado para mostrar columnas.",
        "matrix.scroll_hint": "Desplázate horizontalmente para ver más mercados →",
        "matrix.hidden_note": ("Los productos retirados, suspendidos o con estado no verificado "
                               "se ocultan por defecto; los registros de Hong Kong y Australia se "
                               "muestran como excepciones."),
        "matrix.capped": "Mostrando las primeras {shown} de {total} filas de concentración/forma.",
        "matrix.hk_note": ("Los registros de Hong Kong solo tienen capa de nombre/ingrediente: "
                           "sin concentración, forma farmacéutica ni estado de registro; estar en "
                           "el registro no prueba que se comercialice actualmente."),
        "matrix.au_note": ("Los datos ARTG de Australia no incluyen columna de estado de "
                           "registro; el estado se muestra como desconocido. Estar en el registro "
                           "no significa que se comercialice actualmente."),
        # v0.6.7：/warn 分页
        "warn.page_prev": "Anterior", "warn.page_next": "Siguiente",
        "warn.pagination": "Páginas de avisos",
        "warn.page_status": "Página {n} de {total} · {count} avisos",
        "error.index_failed": "No se pudo cargar el índice.",
        "error.local_file": ("Si abriste esta página directamente, el navegador bloquea la "
                             "lectura de archivos locales — ejecuta python -m http.server y "
                             "visita http://localhost:8000/."),
        "error.retry": "Reintentar",
        "res.matched": "nombres encontrados", "res.none": "Sin resultados",
        "res.brands": "nombres comerciales encontrados",
        "res.alias": "alias encontrado",
        "res.alias_no_products": "no es un producto único — ver la nota",
        "res.notin": "No incluido en este país/región",
        "res.caveat": "un resultado vacío no significa que el medicamento no exista",
    "res.partial": "resultados parciales — cargando el índice completo…",
        "artg.title": "También en el ARTG (principio activo no registrado)",
        "artg.note": ("Estos registros existen en Australia, pero el sitio todavía no los ha "
                      "vinculado a un principio activo, así que no se muestran como productos."),
        "artg.sponsor": "Titular", "artg.id": "ID ARTG",
        "res.fuzzy": "Sin coincidencia exacta — nombres más parecidos",
        "card.packs": "envases",
        "col.ing": "Principio activo", "col.dose": "Dosis",
        "col.brand": "Marca", "col.mah": "Fabricante",
        "same.ing": "Mismo principio activo, otros productos",
        "same.note": "Buscaste una marca: esto es lo demás que contiene el mismo principio activo.",
        "same.warning": "Mismo nombre o mismo principio no significa que sean intercambiables.",
        "same.related": "Contiene uno de los mismos principios (no la misma composición)",
        "same.related_note": "Estos registros comparten al menos un principio con tu búsqueda, pero el conjunto completo es distinto. No son el mismo producto.",
        "res.records_noun": "registros",
        "res.matched_name": "Nombre coincidente",
        "res.no_brand_note": "{n} registro(s) sin nombre comercial se muestran a nivel de nombre.",
        # v0.9.7 task-12
        "res.identity.ingredient": "Principio activo",
        "res.identity.markets": "Mercados cubiertos",
        "res.identity.records": "{n} registros",
        "res.same_name": "Mismo nombre, otro medicamento",
        "res.not_interchangeable": "No intercambiable entre mercados",
        "res.identity_note": ("El mismo nombre puede señalar otro principio activo en otro "
                              "mercado. Comprueba principio, concentración y forma, no solo el nombre."),
        "res.action_drug": "Ver la ficha del principio",
        "res.action_copy": "Copiar nombre genérico",
        "res.identity_title": "candidato 1 de {n}",
        "res.more_detail": "Más concentraciones / más registros",
        "res.src_label": "Mercado de origen (solo registros de):",
        "res.src_all": "Todos los mercados de origen",
        "res.src_active": "mercado de origen {c}",
        "res.empty_h1": "Sin resultados para «{q}»",
        "res.empty_spelling": "Revisa la ortografía o prueba el nombre genérico",
        "res.empty_browse": "Explorar por categoría",
        "res.empty_coverage": "Ver cobertura y actualización",
        "res.details": "Detalles",
        "res.col_market": "Mercado",
        "res.showing": "Mostrando {n} de {total}",
        "badge.severe": "Mismo nombre, otro medicamento",
        "badge.warning": "Liberación diferente",
        "badge.combo": "Combinación",
        "fam.title": "La misma marca en otros mercados",
        "fam.warn": "Misma marca, otro medicamento",
        "drug.brand": "Marca", "drug.strength": "Concentración", "drug.nostrength": "no publicado",
        "drug.release": "Liberación", "drug.status": "Estado",
        "drug.status.active": "activo", "drug.status.discontinued": "descatalogado",
        "drug.status.withdrawn": "retirado", "drug.status.unknown": "desconocido",
        "drug.status_note.discontinued": "caducado",
        "drug.status_note.withdrawn": "autorización retirada",
        "drug.status_note.unknown": "validez desconocida",
        "drug.no_brand": "(sin nombre comercial)", "drug.also_called": "También llamado:",
        "drug.also_known": "También conocido como:", "syn.tag": "sinónimo",
        "brand.none": "Sin nombre comercial",
        "a11y.skip": "Saltar al contenido",
        "ingredient.unrecorded": "Principio no registrado (nivel de nombre)",
        "badge.export_only": "Solo exportación",
        "drug.records": "registros", "drug.showing": "mostrando 40 de",
        "drug.sid": "ID de sustancia",
        "drug.notice": ("Un mismo principio activo puede tener nombres comerciales totalmente "
                        "distintos según el país, y un mismo nombre puede corresponder a otro "
                        "principio activo. Listado por país — no son intercambiables."),
        "drug.empty": "Todavía no hay productos registrados.",
        "drug.confused": "Fácil de confundir con",
        "drug.confused_note": ("La FDA recomienda tall-man lettering para este par; "
                               "comprueba el principio activo, no el nombre."),
        "drug.confused_all": "Todos los pares",
        "name.countries": "Países y regiones", "name.form": "Forma",
        "name.strength": "Concentración", "name.release": "Liberación",
        "name.also": "También escrito como", "name.found": "Presente en",
        "name.empty": "Sin registros",
        "name.single_note": "Solo un registro de producto con este nombre por ahora.",
        "name.severe": ("Este nombre comercial corresponde a principios activos distintos "
                        "según el país o la variante. Comprueba la composición; nunca trates "
                        "los nombres como equivalentes."),
        "name.warning": ("Mismo nombre, pero liberación inmediata frente a modificada — "
                         "no son intercambiables."),
        "nick.hit": "Apodo",
        "nick.slang": "apodo de internet", "nick.legacy": "nombre antiguo",
        "nick.translit": "nombre antiguo transliterado", "nick.abbrev": "abreviatura",
        "nick.misnomer": "denominación errónea habitual",
        "nick.unverified": "aportado por el usuario (sin verificar)",
        "nick.community": "nombre de la comunidad",
        "nick.source": "Fuente",
        "nick.tag": "apodo",
        "nick.street": "nombre callejero en EE. UU.", "nick.folk": "nombre popular",
        "nick.class": "término de clase",
        "nick.class_caveat": ("Es un término de clase, no un medicamento concreto: puede "
                              "abarcar varios principios activos. Comprueba el principio activo."),
        "nick.folk_caveat": ("Es un término popular/de categoría, no un medicamento concreto: "
                             "puede abarcar varios principios activos. Un producto cuyo nombre "
                             "contiene el término no pertenece necesariamente a esa clase."),
        "nick.nomap_caveat": ("Este término apunta a una sustancia sin producto comercializado "
                              "en esta base de datos; no se muestra lista de productos."),
        "nick.ambiguous": ("Este apodo puede corresponder a más de un principio activo — "
                           "comprueba la composición."),
        "nick.caveat": ("Los apodos señalan un principio activo, no un envase concreto: el mismo "
                        "principio se vende con marcas distintas en cada país."),
        "nick.synonym": "sinónimo",
        "nick.synonym_hit": "También conocido como",
        "nick.synonym_caveat": ("Otro nombre del mismo principio activo (INN frente a USAN o una "
                                "variante ortográfica). Identifica el principio; los productos de "
                                "otros países siguen sin ser intercambiables."),
        "footer": ("Solo información — no es consejo médico ni sustituye a un farmacéutico."),
        "report.link": "Informar de un error",
        "report.all": "Problemas conocidos",
        "report.note": "¿Principio activo equivocado, dosis equivocada o falta un medicamento? Escríbenos:",
        "report.cta": "Informar de este resultado",
        "report.issue_title": "Error de datos: ",
        "report.field_query": "Consulta", "report.field_page": "Página",
        "report.field_expected": "Resultado esperado", "report.field_actual": "Resultado real",
        "report.field_pack": "Envase o lote",
        "conf.title": "Nombres de medicamentos fáciles de confundir",
        "conf.intro": ("Pares de nombres parecidos o que suenan igual, del proyecto de "
                       "diferenciación de nombres de la FDA. Es la lista oficial tall-man, "
                       "no la lista LASA completa de ISMP."),
        "conf.note": ("Un par significa que los nombres pueden confundirse; no significa que "
                      "los medicamentos sean intercambiables. La FDA recomienda tall-man lettering."),
        "conf.pair": "Par", "conf.tml": "Grafía tall-man",
        "conf.search_hit": "Este nombre se confunde fácilmente con",
        # v0.11.2（条目 10）：与 en/zh 同步成「目标市场」口径（?country= 语义不变）
        "home.country_label": "Mercado destino: muestra los nombres usados allí (opcional)",
        "home.country_summary": "Mercado destino (opcional)",
        "home.submit": "Buscar", "home.slash_hint": "Pulsa / para enfocar",
        "home.suggestions": "Sugerencias",
        "home.country_label_sel": "Mercado destino: cómo se llama en {country}:",
        "country.missing": "Este país/región no tiene ningún producto registrado con este nombre.",
        "country.missing_note": ("El nombre coincide con un principio activo, no con un producto "
                                 "de este país/región. Cambia de país/región o abre la ficha del "
                                 "principio activo."),
        "country.open_card": "Ficha del principio",
        "country.change": "Cambiar país/región",
        "parse.label": "Consulta interpretada",
        "parse.name": "Nombre", "parse.dose": "Dosis", "parse.form": "Forma",
        "parse.match": "Coincidencia",
        "parse.match.exact": "exacta", "parse.match.compact": "unida",
        "parse.match.prefix": "prefijo", "parse.match.contains": "subcadena",
        "parse.match.fuzzy": "aproximada", "parse.match.nickname": "alias",
    "parse.match.pinyin": "pinyin",
        "parse.match.country": "vista por país", "parse.match.none": "sin coincidencias",
        "ac.suggestions": "Sugerencias",
        "res.brands_noun": "marcas",
        "res.show_brands": "Mostrar todas las marcas",
        "res.fold": "Mostrar menos",
        "res.load_more": "Cargar más",
        "res.loaded_all": "Todos los resultados mostrados",
        "res.copy": "Copiar tabla", "res.csv": "Descargar CSV",
        "res.copied": "Copiado", "res.copy_fail": "No se pudo copiar — selecciona la tabla",
        "res.col_country": "Países y regiones", "res.col_form": "Forma",
        "res.col_match": "Coincidencia", "res.col_link": "Página",
        "a3.salt": "Formas salinas:", "a3.release": "Liberación:",
        "a3.incompat": "No intercambiables — ver aviso",
        "row.report": "Informar de esta fila",
        "report.field_row": "Fila",
        "a1.expand": "Detalles", "a1.loading": "Cargando detalles…",
        "a1.none": "No hay registros de producto para este nombre.",
        "a1.goto": "Abrir página del principio activo",
        "a1.market": "Mercado", "a1.pack": "Envase", "a1.approval": "Registro / NDC / DIN",
        "a1.status": "Estado", "a1.source": "Fuente", "a1.raw": "Registro original",
        "a1.more": ("Se muestran los primeros 12 registros; "
                    "<a href=\"{url}\">la página del principio activo</a> tiene todos."),
    },
    "zh": {
        "nav.search": "检索", "nav.confused": "易混淆药名", "nav.about": "关于",
        "nav.whatsnew": "更新日志",
        "nav.primary": "主导航", "nav.more": "更多",
        "nav.sections": "分区导航",
        "nav.search_compact": "搜一个药名",
        "home.h1": "查一个药名，看它在各国是什么",
        "home.sub": "商品名、通用名、俗称或包装上一行字；中英文、全角、西里尔字母都能搜。",
        "home.candidate": "结果永远是候选集，不是唯一答案。",
        # v0.11.2（条目 8）：三步流程（输名 → 确认产品 → 选目标市场）
        "flow.s1": "输名", "flow.s2": "确认产品", "flow.s3": "选目标市场",
        "home.recent": "最近更新",
        "home.recent_all": "查看全部更新 →",
        "home.ph": "商品名 / 通用名 / 俗称 / 包装上的一行字",
        "home.all": "全部国家和地区", "home.us": "美国",
        "home.gb": "英国", "home.cn": "中国", "home.es": "西班牙",
        "home.mx": "墨西哥", "home.au": "澳大利亚", "home.ca": "加拿大",
        "home.sg": "新加坡",
        "home.tw": "中国台湾",
        "home.hk": "中国香港",
        "home.eu": "欧盟（EU）",
        "home.fr": "法国",
        "coverage.gap.fr": "BDPM（ANSM）— Licence Ouverte / etalab-2.0，须署名；更新日期见数据包；授权有效 ≠ 在售。",
        "about.fr_source": ('<p class="sub"><b>法国</b>：BDPM（Base de données publique des médicaments，ANSM），'
                            '<b>Licence Ouverte / etalab-2.0</b>，须署名并注明更新日期；数据截至 <b>2026-11-03</b>。'
                            '只存事实栏位（名称、成分、剂型、厂家、授权号）。'
                            '<a href="https://base-donnees-publique.medicaments.gouv.fr/">BDPM</a>。</p>'),
        "eu.region_title": "欧盟集中审批（EMA）",
        "eu.region_note": ("欧盟层授权，不是某一国家的在售记录；欧盟登记不含规格、剂型、包装。"),
        "eu.coverage_note": "欧盟区域层——仅集中审批产品；授权有效 ≠ 各国在售。",
        "coverage.gap.eu": "区域层：欧盟集中审批（EMA / EC Union Register）；不含规格、剂型、包装；授权有效 ≠ 某国在售。",
        "home.coverage": "查不到不代表这个药不存在。当前覆盖（国家和地区）：",
        "home.loading": "正在加载索引…",
        "home.hint_idle": ("首次搜索只加载一个检索分片（中位约 1.0 MB，gzip 后约 0.16 MB）；"
                           "完整索引（core 约 42 MB，gzip 后约 9–10 MB）会在后台补全"
                           "——直接输入、点搜索框或选一个示例。"),
        "home.hint_loading": "正在加载检索分片（中位约 1.0 MB，gzip 后约 0.16 MB）…",
        # v0.6.6：成分页多国并排矩阵
        "matrix.spec": "规格 / 剂型 / 释放",
        "matrix.original": "原记录",
        "matrix.none": "未收录",
        "matrix.country_all": "全选",
        "matrix.country_clear": "清空",
        "matrix.market_count": "市场 {shown}/{total}",
        "matrix.empty_markets": "至少选择一个市场才会显示列。",
        "matrix.scroll_hint": "左右滑动查看更多市场 →",
        "matrix.hidden_note": "已停售、撤市或状态未确认的产品默认隐藏；香港及澳大利亚记录例外显示。",
        "matrix.capped": "仅显示前 {shown} / {total} 个规格行。",
        "matrix.hk_note": ("香港记录仅名称/成分层：无规格、无剂型、无注册状态；"
                           "在册不代表在售。"),
        "matrix.au_note": ("澳大利亚 ARTG 数据无注册状态列，状态一律显示「未确认」；"
                           "在册不代表在售。"),
        # v0.6.7：/warn 分页
        "warn.page_prev": "上一页", "warn.page_next": "下一页",
        "warn.pagination": "警示分页",
        "warn.page_status": "第 {n} / {total} 页 · 共 {count} 条",
        "error.index_failed": "索引没加载成功。",
        "error.local_file": ("如果是本地双击打开的页面，浏览器会拦截本地文件读取——请用 "
                             "python -m http.server 起服务后访问 http://localhost:8000/。"),
        "error.retry": "重试",
        "res.matched": "个名字命中", "res.none": "没有匹配的名字",
        "res.brands": "个商品名命中",
        "res.alias": "个别名命中",
        "res.alias_no_products": "不是单一商品，见上方说明",
        "res.notin": "所选国家/地区没有收录这个名字",
        "res.caveat": "查不到不代表这个药不存在",
    "res.partial": "部分结果 —— 正在加载完整索引…",
        "artg.title": "ARTG 也有登记（成分尚未收录）",
        "artg.note": "这些条目在澳洲 ARTG 有登记，但本站还没把成分对上，所以不作为产品展示。",
        "artg.sponsor": "申办方", "artg.id": "ARTG 编号",
        "res.fuzzy": "没有精确命中，以下是最接近的名字",
        "card.packs": "个包装",
        "col.ing": "成分", "col.dose": "剂量",
        "col.brand": "品牌", "col.mah": "厂家",
        "same.ing": "同成分的其他商品",
        "same.note": "你搜的是商品名 —— 下面是同一活性成分的其他商品。",
        "same.warning": "同名或同成分，都不代表可以互換。",
        "same.related": "含相同成分之一（不是同一複方）",
        "same.related_note": "這些記錄與你搜的成分至少有一個相同，但完整成分集合不同；它們不是同一種產品。",
        "res.records_noun": "筆紀錄",
        "res.matched_name": "命中名",
        "res.no_brand_note": "有 {n} 筆紀錄沒有商品名，按名稱層展示。",
        "same.warning": "同名或同成分，都不代表可以互换。",
        "same.related": "含相同成分之一（不是同一复方）",
        "same.related_note": "这些记录与你搜的成分至少有一个相同，但完整成分集合不同；它们不是同一种产品。",
        "res.records_noun": "条记录",
        "res.matched_name": "命中名",
        "res.no_brand_note": "有 {n} 条记录没有商品名，按名称层展示。",
        # v0.9.7 task-12
        "res.identity.ingredient": "活性成分",
        "res.identity.markets": "覆盖市场",
        "res.identity.records": "{n} 条记录",
        "res.same_name": "同名不同药",
        "res.not_interchangeable": "跨市场不可互换",
        "res.identity_note": ("同一个名字在别的市场可能指向另一种成分；"
                              "请按成分、规格、剂型核对，不要只看名字。"),
        "res.action_drug": "查看成分页",
        "res.action_copy": "复制标准名",
        "res.identity_title": "共 {n} 条候选，这是第 1 条",
        "res.more_detail": "更多同规格 / 更多记录",
        "res.src_label": "来源市场（只看这些登记库的记录）：",
        "res.src_all": "全部来源市场",
        "res.src_active": "来源市场 {c}",
        "res.empty_h1": "没有匹配「{q}」",
        "res.empty_spelling": "检查拼写，或改用通用名",
        "res.empty_browse": "按类别浏览",
        "res.empty_coverage": "看覆盖与新鲜度",
        "res.details": "详情",
        "res.col_market": "市场",
        "res.showing": "显示 {n} / {total}",
        "badge.severe": "同名不同药",
        "badge.warning": "释放机制不同",
        "badge.combo": "复方",
        "fam.title": "同一品牌在其他市场的写法",
        "fam.warn": "同名不同药",
        "drug.brand": "商品名", "drug.strength": "规格", "drug.nostrength": "未公开",
        "drug.release": "释放", "drug.status": "状态",
        "drug.status.active": "在售", "drug.status.discontinued": "已停售",
        "drug.status.withdrawn": "已撤市", "drug.status.unknown": "状态未知",
        "drug.status_note.discontinued": "有效期已过",
        "drug.status_note.withdrawn": "批文已撤销",
        "drug.status_note.unknown": "有效期待确认",
        "drug.no_brand": "（无商品名）", "drug.also_called": "也叫：",
        "drug.also_known": "也称：", "syn.tag": "异名",
        "brand.none": "无商品名",
        "a11y.skip": "跳到主要内容",
        "ingredient.unrecorded": "成分未收录（名称层）",
        "badge.export_only": "仅供出口",
        "drug.records": "条记录", "drug.showing": "仅显示前 40 条，共",
        "drug.sid": "规范成分",
        "drug.notice": ("同一成分在不同国家可能用完全不同的商品名；同名也可能指向不同成分。"
                        "下方按国家列出，不代表可以互换。"),
        "drug.empty": "暂无已收录产品。",
        "drug.confused": "易混淆",
        "drug.confused_note": "FDA 建议这一对使用 tall-man 大小写；请核对成分，不要按名字等同。",
        "drug.confused_all": "查看全部药对",
        "name.countries": "国家/地区", "name.form": "剂型",
        "name.strength": "规格", "name.release": "释放",
        "name.also": "写法", "name.found": "覆盖",
        "name.empty": "无记录",
        "name.single_note": "该名称目前仅收录 1 个产品记录。",
        "name.severe": ("这个商品名在不同国家或不同变体下指向不同活性成分，"
                        "选药前必须核对成分，不能按名字等同。"),
        "name.warning": "同名产品存在缓释/速释差异，不能直接互换。",
        "nick.hit": "俗称命中",
        "nick.slang": "网络俗称", "nick.legacy": "旧名",
        "nick.translit": "音译旧名", "nick.abbrev": "简称",
        "nick.misnomer": "常见误称",
        "nick.unverified": "用户提供（未证实）",
        "nick.community": "社区叫法",
        "nick.source": "出处",
        "nick.tag": "俗称",
        "nick.street": "美国街头叫法", "nick.folk": "民间叫法",
        "nick.class": "类别俗称",
        "nick.class_caveat": "这是类别叫法，不是具体药名，可能对应多种成分；请按成分核对。",
        "nick.folk_caveat": "这是民间叫法，不是具体药名，可能对应多种成分；名字里含这个词的商品不一定属于该类别，请按成分核对。",
        "nick.nomap_caveat": "这个词指向的成分在本库没有上市产品记录，因此不列商品名。",
        "nick.ambiguous": "这个叫法可能对应不止一个成分，请按成分核对。",
        "nick.caveat": "俗称指向成分，不指向某个包装；同一成分在各国的商品名不同。",
        "nick.synonym": "异名",
        "nick.synonym_hit": "也称",
        "nick.synonym_caveat": ("同一活性成分的另一种写法（INN 与 USAN 差异或拼写变体）。"
                                "只用于确认成分身份，不代表不同国家的产品可以互换。"),
        "footer": "本站只做标识对应，不构成用药建议，不能替代医师或药师。",
        "report.link": "报错 / 纠错",
        "report.all": "已知问题",
        "report.note": "成分错了、剂量错了、或者库里没有这个药？告诉我们：",
        "report.cta": "报告这个结果",
        "report.issue_title": "数据错误：",
        "report.field_query": "查询词", "report.field_page": "页面",
        "report.field_expected": "期望结果", "report.field_actual": "实际结果",
        "report.field_pack": "包装或批号",
        "conf.title": "容易混淆的药物",
        "conf.intro": ("来自 FDA Name Differentiation Project 的形似/音似药对。"
                       "这是官方 tall-man 名单，不是 ISMP 全量 LASA 清单。"),
        "conf.note": ("列在这里只说明两个名字可能被看错/听错，不表示两种药可以互换。"
                      "FDA 建议这一对使用 tall-man 大小写。"),
        "conf.pair": "药对", "conf.tml": "建议 tall-man 写法",
        "conf.search_hit": "这个药名容易与以下名字混淆",
        # v0.11.2（条目 10）：与 en/es 同步成「目标市场」口径（?country= 语义不变）
        "home.country_label": "目标市场：看当地用什么名字（可选）",
        "home.country_label_sel": "目标市场：看{country}当地的叫法：",
        "home.country_summary": "目标市场（可选）",
        "home.submit": "搜索", "home.slash_hint": "按 / 聚焦",
        "home.suggestions": "搜索建议",
        "country.missing": "该国家/地区没有以这个名字上架的产品。",
        "country.missing_note": "这个名字命中的是成分卡，不是该国家/地区上架的产品。可以换一个国家/地区，或直接看成分卡。",
        "country.open_card": "看成分卡",
        "country.change": "换国家/地区",
        "parse.label": "检索解析",
        "parse.name": "名称", "parse.dose": "剂量", "parse.form": "剂型",
        "parse.match": "匹配方式",
        "parse.match.exact": "精确", "parse.match.compact": "连写",
        "parse.match.prefix": "前缀", "parse.match.contains": "包含",
        "parse.match.fuzzy": "模糊", "parse.match.nickname": "别名",
    "parse.match.pinyin": "拼音",
        "parse.match.country": "国家/地区视图", "parse.match.none": "无匹配",
        "ac.suggestions": "搜索建议",
        "res.brands_noun": "个品牌",
        "res.show_brands": "展开全部品牌",
        "res.fold": "折叠",
        "res.load_more": "加载更多",
        "res.loaded_all": "已显示全部结果",
        "res.copy": "复制表格", "res.csv": "下载 CSV",
        "res.copied": "已复制", "res.copy_fail": "复制失败，请手动选择表格",
        "res.col_country": "国家/地区", "res.col_form": "剂型",
        "res.col_match": "匹配方式", "res.col_link": "页面",
        "a3.salt": "盐型：", "a3.release": "释放：",
        "a3.incompat": "不可互换 — 见警示",
        "row.report": "报告这一行",
        "report.field_row": "行",
        "a1.expand": "详情", "a1.loading": "正在加载明细…",
        "a1.none": "这个名字下没有产品记录。",
        "a1.goto": "打开成分页",
        "a1.market": "市场", "a1.pack": "包装", "a1.approval": "批准号 / NDC / DIN",
        "a1.status": "状态", "a1.source": "来源", "a1.raw": "原始记录",
        "a1.more": "仅显示前 12 条记录，<a href=\"{url}\">全部见成分页</a>。",
    },
}

# v0.11.4：FR 站点侧准备（task-55）。开关：data/languages.json 的 fr.enabled=false +
# data/markets.json 的 FR.enabled=false → LANGS 不含 fr，不生成 /fr/，线上产物不变。
# I18N["fr"] 的键集与 I18N["en"] 完全相同（_merge_static_i18n 里按 en 键补全）；
# 本字典是高频 UI 的机器翻译（约 170 键），其余键暂回退英文，开开关前需补齐
# （reports/2026-11-13-fr-site-prep.md 的开启清单里有「en==fr 待补键」检查步骤）。
FR_I18N: dict[str, str] = {
    "nav.search": "Rechercher", "nav.confused": "Noms trompeurs", "nav.about": "À propos",
    "nav.whatsnew": "Nouveautés", "nav.primary": "Navigation principale", "nav.more": "Plus",
    "nav.sections": "Sections", "nav.search_compact": "Rechercher un nom",
    "home.h1": "Recherchez un nom de médicament — voyez ce qu'il est dans chaque pays",
    "home.sub": ("Nom commercial, nom générique, surnom ou une ligne de la boîte — le chinois, "
                 "le pleine largeur et le cyrillique fonctionnent aussi."),
    "home.candidate": "Vous obtenez toujours un ensemble de candidats, jamais une réponse unique.",
    "flow.s1": "Nom", "flow.s2": "Confirmer le produit", "flow.s3": "Marché cible",
    "home.recent": "Récemment mis à jour", "home.recent_all": "Voir toutes les mises à jour →",
    "home.ph": "Nom commercial / générique / surnom / une ligne de la boîte",
    "home.all": "Tous les pays et régions", "home.us": "États-Unis", "home.gb": "Royaume-Uni",
    "home.cn": "Chine", "home.es": "Espagne", "home.mx": "Mexique", "home.au": "Australie",
    "home.ca": "Canada", "home.sg": "Singapour", "home.tw": "Chine Taïwan",
    "home.hk": "Chine Hong Kong", "home.eu": "Union européenne (UE)",
    "eu.region_title": "Autorisation centralisée UE (EMA)",
    "eu.region_note": ("Autorisé au niveau de l'UE — pas une preuve de vente dans un pays donné. "
                       "Le registre de l'UE ne contient ni dosage, ni forme, ni conditionnement."),
    "eu.coverage_note": ("Couche régionale UE — autorisations centralisées uniquement ; "
                         "autorisation ≠ vente dans chaque pays."),
    "coverage.gap.eu": ("Couche régionale : autorisations centralisées (EMA / registre de l'Union). "
                        "Ni dosage, ni forme, ni conditionnement ; autorisation ≠ vente."),
    "home.coverage": ("Un résultat vide ne signifie pas que le médicament n'existe pas. Couverture :"),
    "home.loading": "Chargement…",
    "home.hint_idle": ("La première recherche charge un fragment d'index (médiane ~1 Mo, "
                       "~0,16 Mo gzip) ; l'index complet (~42 Mo brut, ~9–10 Mo gzip) se charge "
                       "en arrière-plan — commencez à taper, ciblez la recherche ou choisissez un exemple."),
    "home.hint_loading": "Chargement de l'index…",
    "matrix.spec": "Dosage", "matrix.original": "Libellé d'origine", "matrix.none": "Non renseigné",
    "matrix.country_all": "Tous les pays", "matrix.country_clear": "Effacer",
    "matrix.market_count": "Marchés {shown}/{total}",
    "matrix.empty_markets": "Sélectionnez au moins un marché pour afficher des colonnes.",
    "matrix.scroll_hint": "Faites défiler horizontalement pour plus de marchés →",
    "matrix.hidden_note": "Les marchés masqués restent accessibles via le sélecteur.",
    "matrix.capped": "Limité aux {n} premiers dosages.",
    "warn.page_prev": "Précédent", "warn.page_next": "Suivant",
    "warn.pagination": "Pagination des alertes",
    "warn.page_status": "Page {n} sur {total} · {count} alertes",
    "error.index_failed": "Échec du chargement de l'index.",
    "error.local_file": ("Ouvrez le site via un serveur local (les fichiers JSON ne sont pas lus "
                         "depuis file://)."),
    "error.retry": "Réessayer",
    "res.matched": "correspondances", "res.none": "Aucun résultat", "res.brands": "marques",
    "res.alias": "alias", "res.alias_no_products": "alias sans produit",
    "res.notin": "absent de",
    "res.caveat": "Un nom identique ne prouve pas que les produits sont interchangeables.",
    "res.partial": "Index partiel — les résultats se complètent en arrière-plan.",
    "artg.title": "Nom enregistré au registre ARTG",
    "artg.note": "L'enregistrement ne prouve pas la vente.",
    "artg.sponsor": "Sponsor", "artg.id": "ARTG ID",
    "res.fuzzy": "approchant", "card.packs": "conditionnements",
    "col.ing": "Principe actif", "col.dose": "Dosage", "col.brand": "Marque", "col.mah": "Fabricant",
    "same.ing": "Autres produits avec le même principe actif",
    "same.note": "Vous avez cherché une marque — voici d'autres produits avec le même principe actif.",
    "same.warning": "Même nom ou même principe actif ne signifie pas interchangeables.",
    "same.related": "Contient l'un des mêmes principes actifs (pas la même association)",
    "same.related_note": ("Ces enregistrements partagent au moins un principe actif, mais pas "
                          "l'association complète ; ce ne sont pas les mêmes produits."),
    "res.records_noun": "enregistrements", "res.matched_name": "nom correspondant",
    "res.no_brand_note": "{n} enregistrements sans nom commercial sont affichés par nom.",
    "res.identity.ingredient": "Principe actif", "res.identity.markets": "Marchés couverts",
    "res.identity.records": "{n} enregistrements", "res.same_name": "Même nom, autre médicament",
    "res.not_interchangeable": "Non interchangeables entre marchés",
    "res.identity_note": ("Le même nom peut désigner un autre principe actif ailleurs ; vérifiez "
                          "le principe, le dosage et la forme."),
    "res.action_drug": "Ouvrir la fiche du principe actif",
    "res.action_copy": "Copier le nom générique",
    "res.identity_title": "candidat 1 sur {n}",
    "res.more_detail": "Plus de dosages / plus d'enregistrements",
    "res.src_label": "Marché source (enregistrements de) :",
    "res.src_all": "Tous les marchés sources", "res.src_active": "marché source {c}",
    "res.empty_h1": "Aucun résultat pour « {q} »",
    "res.empty_spelling": "Vérifiez l'orthographe ou essayez le nom générique",
    "res.empty_browse": "Parcourir par catégorie", "res.empty_coverage": "Voir la couverture",
    "res.details": "Détails", "res.col_market": "Marchés",
    "res.showing": "{n} sur {total} affichés", "res.density": "Densité",
    "badge.severe": "Même nom, autre médicament", "badge.warning": "Non interchangeable",
    "badge.combo": "Association", "fam.title": "La même marque dans d'autres marchés",
    "fam.warn": "Même nom, autre médicament",
    "drug.brand": "Marque", "drug.strength": "Dosage", "drug.nostrength": "non indiqué",
    "drug.release": "Libération", "drug.status": "Statut",
    "drug.status.active": "En vente", "drug.status.discontinued": "Commercialisation arrêtée",
    "drug.status.withdrawn": "Retiré", "drug.status.unknown": "Statut inconnu",
    "brand.none": "Pas de nom commercial", "brand.mah": "Fabricant :",
    "a11y.skip": "Aller au contenu", "ingredient.unrecorded": "Non enregistré",
    "badge.export_only": "Export uniquement",
    "home.country_label": "Marché cible : voir les noms utilisés sur place (facultatif)",
    "home.country_summary": "Marché cible (facultatif)", "home.submit": "Rechercher",
    "home.slash_hint": "Appuyez sur / pour cibler", "home.suggestions": "Suggestions",
    "home.country_label_sel": "Marché cible : comment cela s'appelle à {country} :",
    "country.missing": "Ce pays/région n'a aucun produit enregistré sous ce nom.",
    "country.missing_note": ("Le nom correspond à un principe actif, pas à un produit de ce pays. "
                             "Changez de pays ou ouvrez la fiche du principe actif."),
    "country.open_card": "Fiche du principe actif", "country.change": "Changer de pays/région",
    "parse.label": "Analyse de la requête", "parse.name": "Nom", "parse.dose": "Dosage",
    "parse.form": "Forme", "parse.match": "Correspondance",
    "parse.match.exact": "exacte", "parse.match.compact": "sans espaces",
    "parse.match.prefix": "préfixe", "parse.match.contains": "contenu",
    "parse.match.fuzzy": "approchant", "parse.match.nickname": "alias",
    "parse.match.pinyin": "pinyin", "parse.match.country": "vue pays",
    "parse.match.none": "aucune",
    "ac.suggestions": "Suggestions", "res.brands_noun": "marques",
    "res.show_brands": "Afficher toutes les marques", "res.fold": "Réduire",
    "res.load_more": "Charger plus", "res.loaded_all": "Tous les résultats affichés",
    "res.copy": "Copier le tableau", "res.csv": "Télécharger CSV",
    "res.copied": "Copié", "res.copy_fail": "Copie impossible, sélectionnez le tableau",
    "res.col_country": "Pays/région", "res.col_form": "Forme",
    "res.col_match": "Type de correspondance", "res.col_link": "Page",
    "a3.salt": "Forme saline :", "a3.release": "Libération :",
    "a3.incompat": "Non interchangeables — voir alertes", "row.report": "Signaler cette ligne",
    "report.field_row": "Ligne", "a1.expand": "Détails", "a1.loading": "Chargement du détail…",
    "a1.none": "Aucun produit sous ce nom.", "a1.goto": "Ouvrir la fiche du principe actif",
    "a1.market": "Marché", "a1.pack": "Conditionnement", "a1.approval": "Autorisation / NDC / DIN",
    "a1.status": "Statut", "a1.source": "Source", "a1.raw": "Enregistrement d'origine",
    "a1.more": ("Seuls les 12 premiers enregistrements sont affichés ; "
                "<a href=\"{url}\">voir tous sur la fiche du principe actif</a>."),
    "nav.coverage": "Couverture", "coverage.title": "Couverture et fraîcheur",
    "coverage.intro": "Chiffres par marché, d'après la base.",
    "coverage.notice": ("Les chiffres de couverture sont des faits d'enregistrement, pas des "
                        "recommandations."),
    "coverage.col.market": "Marché", "coverage.col.products": "Produits",
    "coverage.col.mapping": "Principe actif associé", "coverage.col.spec": "Dosage",
    "coverage.col.last": "Dernière mise à jour", "coverage.col.asof": "Données au",
    "coverage.col.notes": "Notes", "coverage.no_brand": "enregistrements sans nom commercial",
    "coverage.source_note": "Sources et licences : voir À propos.",
    "name.no_en": "Pas de nom anglais", "name.no_es": "Pas de nom espagnol",
    "name.no_zh": "Pas de nom chinois", "name.no_zh_hant": "Pas de nom chinois traditionnel",
    "about.title": "À propos",
    "about.lead": ("Nous identifions un médicament et comparons son identité entre pays — "
                   "sans conseil d'utilisation."),
    "about.rules": "Règles", "about.nick": "Surnoms", "about.terms": "Conditions",
    "about.sources": "Sources et licences", "about.samename": "Même nom, autre médicament",
    "about.gaps": "Lacunes connues", "about.analytics": "Statistiques",
    "about.stats": "Chiffres clés",
    "whatsnew.title": "Nouveautés", "whatsnew.intro": "Historique des versions.",
    "whatsnew.lang_note": "Les anciennes versions peuvent n'être que partiellement traduites.",
    "whatsnew.pending": "Traduction à venir",
    "notfound.title": "Page introuvable", "notfound.p1": "Cette adresse n'existe pas.",
    "notfound.p2": "Essayez la recherche.", "notfound.search": "Rechercher",
    "notfound.about": "À propos", "notfound.confused": "Noms trompeurs",
    "notfound.whatsnew": "Nouveautés", "notfound.report": "Signaler",
    "nav.warn": "Alertes",
    "warn.title": "Alertes : même nom, autre médicament / non interchangeables",
    "warn.intro": "Alertes publiées, avec leur source réglementaire.",
    "warn.count": "{n} alertes publiées.", "warn.no_advice": "Aucun conseil d'utilisation.",
    "warn.group.high": "Gravité élevée", "warn.group.medium": "Moyenne", "warn.group.info": "Info",
    "warn.sev.high": "Élevée", "warn.sev.medium": "Moyenne", "warn.sev.info": "Info",
    "warn.source": "Source", "warn.related": "Lié", "warn.countries": "Pays",
    "warn.reviewed": "Vérifié", "warn.drug_summary": "Résumé", "warn.see_all": "Tout voir",
    "warn.empty": "Aucune alerte publiée.",
    "warn.source_note": "Chaque alerte cite sa source réglementaire.",
    "combo.title": "Association à dosage fixe",
    "combo.intro": "Cette page décrit une association exacte de principes actifs.",
    "combo.ingredients": "Principes actifs", "combo.products": "Marques avec cette association exacte",
    "combo.no_advice": "Aucun conseil d'utilisation.",
    "combo.empty": "Aucune marque enregistrée pour cette association.",
    "combo.capped": "Limité aux {cap} premières marques sur {total}.",
    "combo.source_note": "Mêmes sources que les fiches de principes actifs.",
    "combo.see_warnings": "Voir les alertes", "combo.no_page": "Pas de page de marque",
    "combo.stub_badge": "Page non détaillée",
    "combo.stub_note": ("Cette page d'association n'est pas détaillée ; utilisez les fiches de "
                        "principes actifs ou la recherche."),
    "combo.stub_search": "Rechercher",
    "maker.title": "Fabricants",
    "maker.intro": ("{name} — {products} produits dans {markets} marchés, {brands} noms commerciaux."),
    "maker.stats": "Chiffres", "maker.by_country": "Par pays", "maker.brand": "Marque",
    "maker.ingredient": "Principe actif", "maker.source": "Source",
    "maker.capped": "Limité aux {n} premiers produits.", "maker.no_page": "Pas de page fabricant",
    "maker.no_page_count": "{n} autres sans page", "maker.empty": "Aucun produit.",
    "maker.single_note": "Un seul produit enregistré.",
    "maker.source_note": "Sources et licences : voir À propos.",
    "glossary.title": "Glossaire", "glossary.intro": "Termes utilisés sur le site.",
    "glossary.term": "Terme", "glossary.def": "Définition",
    "glossary.note": "Définitions factuelles, sans conseil.",
    "tab.search": "Recherche", "tab.categories": "Catégories", "tab.coverage": "Couverture",
    "tab.about": "À propos", "nav.categories": "Catégories", "nav.markets": "Marchés",
    "nav.all_categories": "Toutes les catégories", "nav.glossary": "Glossaire",
    "nav.atc": "ATC", "nav.menu": "Menu",
    "form.tablet": "comprimé", "form.capsule": "gélule", "form.liquid": "liquide",
    "form.injection": "injection", "form.topical": "topique", "form.powder": "poudre",
    "form.suppository": "suppositoire", "form.inhalation": "inhalation",
    "form.pellet": "granulé", "form.stick": "bâtonnet", "form.kit": "kit",
    "form.gas": "gaz", "form.unknown": "forme inconnue", "form.effervescent": "effervescent",
    "form.granule": "granulé", "form.solution": "solution",
    "release.ER": "libération prolongée", "release.DR": "libération différée",
    "release.MR": "libération modifiée", "release.none": "—",
    "unit.iu": "UI", "unit.unit": "unité", "unit.meq": "mEq", "unit.mci": "mCi",
    "unit.ug": "µg", "unit.microgram": "µg", "unit.万iu": "100 000 UI",
    "u1.title": "Comprendre en 3 étapes", "u1.step1": "Saisissez le nom de la boîte",
    "u1.step1_hint": "Marque, générique, surnom ou une ligne de la boîte ; le dosage peut être inclus.",
    "u1.step2": "Vérifiez ce candidat : principe, dosage, forme",
    "u1.step2_hint": "La carte ne montre qu'un candidat, jamais la réponse ; comparez avec votre boîte.",
    "u1.step3": "Choisissez le marché cible",
    "u1.step3_hint": "Choisissez un marché cible pour voir le nom local ; la liste des candidats ne change pas.",
    "u1.try": "Essayez :", "u1.close": "Fermer", "u1.aria": "Guide de démarrage",
    "u2.title": "Noms par pays", "u2.hint": "Le nom du même principe actif sur place ; cliquez pour voir les produits.",
    "u2.none": "aucun", "u2.none_hint": "Aucun enregistrement pour ce pays.", "u2.multi": "plusieurs",
    "parse.atc": "Code ATC", "parse.match.atc": "préfixe ATC", "atc.label": "ATC",
    "atc.hint": "Correspondance par préfixe ATC", "atc.hit": "correspondances", "atc.none": "aucun",
    "atc.none_meta": "Aucun code ATC correspondant.", "atc.loading": "Chargement des données ATC…",
    "site.name": "Référentiel des noms commerciaux de médicaments",
    "report.note": "Mauvais principe, dosage ou médicament absent ? Dites-le-nous :",
    "report.cta": "Signaler ce résultat", "report.link": "Signaler", "report.all": "Tous les signalements",
    "report.issue_title": "Erreur de données : ", "report.field_query": "Requête",
    "report.field_page": "Page", "report.field_expected": "Attendu", "report.field_actual": "Obtenu",
    "report.field_pack": "Boîte",
    "conf.title": "Médicaments à ne pas confondre", "conf.intro": "Paires de noms proches.",
    "conf.note": "Un nom proche ne signifie pas interchangeables.",
    "conf.pair": "Paire", "conf.tml": "Écriture tall-man",
    "conf.search_hit": "Ce nom est facilement confondu avec",
    # v0.11.6 task-1（T12 C2/C3/C4）：品牌页「配方差异」表（fr 跟随 en 键集）。
    "fam.cmp_title": "Noms de marque liés et différences de formule",
    "fam.cmp_intro": ("Un même nom de marque peut être enregistré autrement et contenir des "
                      "principes actifs différents selon le marché. Ce tableau établit une "
                      "correspondance d'identité : ce n'est pas une traduction, et il n'implique "
                      "pas que les produits soient interchangeables."),
    "fam.cmp_market": "Marché",
    "fam.cmp_name": "Nom enregistré",
    "fam.cmp_ing": "Principes actifs complets",
    "fam.cmp_rel": "Lien avec cette page",
    "fam.cmp_this": "Cette page",
    "fam.rel.same": "Principes actifs identiques",
    "fam.rel.diff": "Principes actifs différents : non interchangeables",
    "fam.rel.partial": ("Certains principes actifs en commun : pas la même association, "
                        "non interchangeables"),
    "fam.rel.release": ("Principes actifs identiques, libération différente : non "
                        "interchangeables"),
    "fam.rel.none": "Aucun principe actif enregistré",
    # T10（plan §9）：与 en 同键集。
    "matrix.multi_form": "Formes galéniques multiples",
    "drug.mono_section": "Uniquement ce principe actif",
    "drug.combo_section": "Associations contenant ce principe actif",
    "matrix.spec_conflict": "dosage non vérifié",
    "name.form_spec": "Dosage par forme galénique",
    # T13（v0.11.7）：成分页筛选条、可点击计数、来源/日期提示、分类页搜索。
    "lf.market": "Marché", "lf.kind": "Type", "lf.all": "Tous", "lf.title": "Filtres",
    "lf.all_kinds": "Tous types", "lf.spec": "Dosage",
    "lf.spec_ph": "Filtrer les dosages, p. ex. 500 mg",
    "lf.none": "Aucune ligne ne correspond à ces filtres.",
    "lf.count": "{shown} sur {total} lignes",
    "drug.more_names": "Voir les {n} autres",
    "drug.mkx_more": "{n} autres marchés",
    "drug.spec_count": "{shown} sur {n} affichées",
    "mkmeta.source": "Origine", "mkmeta.asof": "Données au",
    "mkmeta.undisclosed": "certains enregistrements n'indiquent pas le dosage",
    "mkmeta.unknown": "inclut des enregistrements au statut inconnu (pas une preuve de vente)",
    "cat.help": "Comment lire cette liste", "cat.subcat": "Sous-classe",
    "cat.search_ph": "Rechercher un principe dans cette catégorie",
    "cat.search_none": "Aucun principe ne correspond.",
    "coverage.col.products": "Enregistrements",
    "t11.pick_this": "Celle-ci", "t11.pick_mine": "C'est celle-ci",
    "t11.picked": "Sélectionnée",
    "t11.reselect": "Changer", "t11.compare_link": "Comparer champ par champ →",
    "t11.still_candidates": "L'ensemble des candidats reste {n} enregistrements — celle-ci n'en est qu'un. Voir tous les candidats ↓",
    "t11.all_markets": "Tous",
    "t11.cmp_title": "Comparaison champ par champ (identité seulement)",
    "t11.cmp_you": "Votre enregistrement", "t11.cmp_target": "Marché cible",
    "t11.same": "Identique", "t11.diff": "Différent", "t11.missing": "Non enregistré",
    "t11.name": "Nom enregistré", "t11.spec": "Dosage", "t11.release": "Libération",
    "t11.cmp_note": "Comparaison de champs d'identité uniquement. Un nom ou un principe actif identique ne signifie pas que les produits sont interchangeables.",
    "t11.adv": "Filtres avancés",
    "res.src_label": "Marché d'enregistrement (seulement les enregistrements de ce marché)",
}
FR_I18N.update({
    # v0.11.5 task-3：fr 启用时由 FR_PREP_KEYS 覆盖本行，两处保持同一句。
    "coverage.gap.fr": "BDPM (ANSM) — Licence Ouverte / etalab-2.0, attribution requise ; date de mise à jour dans le paquet de données ; autorisation ≠ vente. 1 987 produits sur 15 799 ont une teneur issue du nom du produit (la composition BDPM ne donne pas de dosage) ; données au 2026-11-03.",
    "about.fr_source": "<p class=\"sub\"><b>France</b> : BDPM (Base de données publiques des médicaments, ANSM), <b>Licence Ouverte / etalab-2.0</b>; attribution et date de mise à jour requises. Données au <b>2026-11-03</b>. Faits uniquement (nom, ingrédient, forme, fabricant, autorisation). <a href=\"https://base-donnees-publique.medicaments.gouv.fr/\">BDPM</a>.</p>",
    "matrix.hk_note": "Les enregistrements de Hong Kong portent uniquement sur le nom/l'ingrédient : pas de concentration, de forme posologique ou de statut d'enregistrement ; le fait d'être inscrit au registre ne prouve pas l'approvisionnement actuel.",
    "matrix.au_note": "Les données australiennes ARTG ne comportent pas de colonne de statut d'enregistrement, le statut est donc affiché comme inconnu ; être inscrit au registre ne signifie pas être actuellement commercialisé.",
    "artg.sponsor": "Parrainer",
    "artg.id": "ID ARTG",
    "drug.status_note.discontinued": "expiré",
    "drug.status_note.withdrawn": "autorisation de mise sur le marché retirée",
    "drug.status_note.unknown": "validité inconnue",
    "drug.no_brand": "(pas de marque)",
    "drug.also_called": "Aussi appelé :",
    "drug.also_known": "Aussi connu sous le nom de :",
    "syn.tag": "synonyme",
    "drug.records": "enregistrements",
    "drug.showing": "montrant les 40 premiers de",
    "drug.sid": "Identifiant de la substance",
    "drug.notice": "Le même ingrédient peut porter des noms de marque complètement différents selon les pays, et le même nom peut désigner un ingrédient différent. Répertorié par pays – non interchangeable.",
    "drug.empty": "Aucun produit enregistré pour l'instant.",
    "drug.confused": "Facilement confondu avec",
    "drug.confused_note": "La FDA recommande le lettrage d'un homme de grande taille pour cette paire ; vérifiez l'ingrédient, pas le nom.",
    "drug.confused_all": "Toutes les paires",
    "name.countries": "Pays et régions",
    "name.form": "Formulaire",
    "name.strength": "Force",
    "name.release": "Libérer",
    "name.also": "Également écrit comme",
    "name.found": "Trouvé dans",
    "name.empty": "Aucun enregistrement",
    "name.single_note": "Jusqu'à présent, un seul enregistrement de produit pour ce nom.",
    "name.severe": "Ce nom de marque désigne différents principes actifs selon les pays ou les variantes. Vérifiez la composition, ne traitez jamais les noms comme équivalents.",
    "name.warning": "Même nom, mais version immédiate ou modifiée – non interchangeable.",
    "nick.hit": "Surnom",
    "nick.slang": "surnom Internet",
    "nick.legacy": "ancien nom",
    "nick.translit": "ancien nom translittéré",
    "nick.abbrev": "abréviation",
    "nick.misnomer": "terme abusif",
    "nick.unverified": "fourni par l'utilisateur (non vérifié)",
    "nick.community": "nom de la communauté",
    "nick.tag": "surnom",
    "nick.street": "Nom de la rue aux États-Unis",
    "nick.folk": "nom populaire",
    "nick.class": "terme de classe",
    "nick.class_caveat": "Il s’agit d’un terme de classe et non d’un médicament spécifique : il peut recouvrir plusieurs ingrédients. Vérifiez l'ingrédient.",
    "nick.folk_caveat": "Il s’agit d’un terme populaire/catégorie, et non d’un médicament spécifique – il peut couvrir plusieurs ingrédients. Un produit dont le nom contient le terme n'appartient pas nécessairement à cette classe ; vérifiez l'ingrédient.",
    "nick.nomap_caveat": "Ce terme désigne une substance sans produit commercialisé dans cette base de données, donc aucune liste de produits n'est affichée.",
    "nick.ambiguous": "Ce surnom peut faire référence à plusieurs ingrédients – vérifiez la composition.",
    "nick.caveat": "Les surnoms font référence à un ingrédient et non à un emballage spécifique : le même ingrédient est vendu sous des marques différentes dans chaque pays.",
    "nick.synonym": "synonyme",
    "nick.synonym_hit": "Aussi connu sous le nom",
    "nick.synonym_caveat": "Un autre nom pour le même ingrédient actif (INN vs USAN ou une variante orthographique). Il identifie l'ingrédient — les produits des différents pays ne sont toujours pas interchangeables.",
    "footer": "Information uniquement – ​​pas de conseil médical et ne remplace pas un pharmacien.",
    "meta.coverage.title": "Couverture et fraîcheur · Référence croisée des marques de médicaments",
    "meta.coverage.desc": "Produits, cartographie des ingrédients, couverture des spécifications, dernière synchronisation et lacunes connues pour chaque marché ; les chiffres sont calculés à partir de la base de données actuelle.",
    "coverage.gap.us": "Source entièrement ouverte FDA ; travaux du gouvernement américain relevant du domaine public.",
    "coverage.gap.gb": "Source dm+d complète ; Attribution de la licence du gouvernement ouvert.",
    "coverage.gap.ca": "Source DPD complète ; réutilisation non commerciale avec attribution.",
    "coverage.gap.au": "L'exportation ARTG n'a pas de colonne de statut d'enregistrement ; le statut est inconnu, pas « en vente ». Certains produits n'ont aucun enregistrement d'ingrédients.",
    "coverage.gap.sg": "L'inscription enregistrée ne prouve pas l'approvisionnement actuel.",
    "coverage.gap.cn": "Aucune licence de redistribution publique confirmée ; certains disques n'ont pas de nom commercial.",
    "coverage.gap.es": "La licence source pour la redistribution est en attente de confirmation.",
    "coverage.gap.mx": "La licence source est en attente de confirmation ; les inscriptions plus anciennes sont incluses.",
    "coverage.gap.tw": "La force est analysée à partir du nom du produit ; la confiance est limitée.",
    "coverage.gap.hk": "Couche de nom/ingrédient uniquement : pas de concentration, de forme ou de statut d'enregistrement ; enregistré ≠ commercialisé.",
    "about.tw_source": "<p class=\"sub\"><b>Taiwan 台灣</b> : TFDA 「全部藥品許可證資料集」 (ensemble de données data.gov.tw 9122) sous <b>Open Government Data License v1.0 (OGDL v1.0)</b> ; attribution requise : 衛福部食藥署 TFDA. Données au <b>2026-10-22</b> (synchronisation hebdomadaire). Faits uniquement (nom du produit, ingrédients, forme posologique, fabricant, numéro de licence, statut). <b>Les points forts sont analysés à partir des noms de produits, la confiance est donc limitée.</b> Licence : <a href=\"https://data.gov.tw/license\">data.gov.tw/license</a>.</p>",
    "about.sg_source": "<p class=\"sub\"><b>Singapour 新加坡</b> : HSA <b>Liste des produits thérapeutiques enregistrés</b> (ensemble de données data.gov.sg d_767279312753558cbf19d48344577084) sous la <b>Singapour Open Data License v1.0 (SODL)</b> ; attribution et lien de licence requis, aucune approbation gouvernementale implicite. Données au <b>2026-08-07</b> (mises à jour tous les 6 mois). <b>Le fait d'être inscrit au registre ne signifie pas que le produit est actuellement commercialisé.</b> Les noms de marques restent en anglais et ne sont jamais traduits ; seuls les noms d'ingrédients chinois (inn_zh) peuvent être affichés. Attribution : contient des informations tirées de la liste des produits thérapeutiques enregistrés, consultée le 2026-10-28 auprès de la Health Sciences Authority (HSA) et mise à disposition sous la licence Open Data de Singapour v1.0 (<a href=\"https://data.gov.sg/open-data-licence\">licence</a>).</p>",
    "about.hk_source": "<p class=\"sub\"><b>Hong Kong 中国香港</b> : Drug Office, Department of Health — <b>Liste des produits pharmaceutiques enregistrés</b> (ensemble de données data.gov.hk hk-dh-dh_do-hk-dh-do-pharmaceutical-product) sous <b>DATA.GOV.HK Terms and Conditions</b> (réutilisation gratuite avec attribution ; non approbation implicite du gouvernement). Données au <b>2026-10-23</b>. <b>Couche de nom/ingrédient uniquement – pas de dosage, de forme posologique ou de statut d'enregistrement ; le fait d'être inscrit au registre ne prouve pas l'approvisionnement actuel.</b></p>",
    "about.au_source": "<p class=\"sub\"><b>Australie</b> : TGA <b>ARTG Medicines 2026-10-28</b> (Registre australien des produits thérapeutiques ; attribution TGA/ARTG). Données au <b>2026-10-28</b>. L'exportation n'a <b>aucune colonne de statut d'enregistrement</b>, le statut est donc affiché comme inconnu ; <b>être inscrit au registre ne signifie pas être actuellement commercialisé</b>. 3 911 produits n'ont aucun enregistrement d'ingrédients et sont affichés au niveau du nom uniquement.</p>",
    "about.eu_source": "<p class=\"sub\"><b>Couche régionale de l'UE</b> : [[3]Commission européenne — Registre de l'Union des médicaments</b> (CC BY 4.0 ; attribution Commission européenne / Registre de l'Union) plus données [[5]EMA Medicines</b> pour vérification croisée (source : Agence européenne des médicaments (EMA) ; pas de logo de l'EMA, pas d'approbation implicite). Autorisations centrales uniquement (médicaments à usage humain), données au <b>2026-11-03</b>. <b>Une autorisation de l'UE ne constitue pas un enregistrement de vente dans un seul pays, et le registre ne contient aucun dosage, forme posologique ou taille d'emballage.</b> Les produits qui ne correspondent à aucun ingrédient connu sont affichés au niveau du nom uniquement.</p>",
    "conf.source_note": "Source : <a href=\"https://www.fda.gov/drugs/medication-errors-related-cder-regulated-drug-products/fda-name-differentiation-project\" target=\"_blank\" rel=\"noopener\">Projet de différenciation des noms de la FDA</a> (contenu à jour au 12/06/2026 ; travaux du gouvernement américain). Seules les paires @@CONF_PAIRS@@ officiellement republiables de la liste FDA sont incluses ; le copyright ISMP/ECRI « Liste des noms de médicaments confus » n'est pas copié. Les noms uniques figurant sur la liste de la FDA sans paire (hydromorphone, mitoxantrone) ne sont pas répertoriés. Une paire est un avertissement concernant les noms, et non une déclaration selon laquelle les médicaments sont équivalents.",
    "warn.sev.info": "Informations",
    "combo.compact": "combinaison",
    "combo.cross_title": "Même combinaison sur d'autres marchés",
    "combo.cross_exact": "Ces marchés enregistrent des produits contenant la même combinaison d’ingrédients actifs. Identité uniquement – ​​et non une recommandation selon laquelle les produits sont interchangeables.",
    "combo.cross_products": "produits",
    "combo.cross_record": "enregistrer",
    "combo.cross_overlap": "La combinaison la plus proche trouvée sur d’autres marchés est similaire mais PAS identique : elle n’est pas interchangeable.",
    "combo.cross_none": "Aucun produit avec cette combinaison n'est encore enregistré sur les autres marchés couverts.",
    "combo.cross_primary": "Seul l’ingrédient principal est le même : il ne s’agit PAS de la même association à dose fixe.",
    "combo.cross_primary_link": "Voir l'ingrédient principal",
    "combo.cross_unmatched": "La comparaison entre marchés n'est pas disponible pour ce nom groupé.",
    "meta.index.title": "Références croisées sur les marques de médicaments : noms de médicaments dans tous les pays",
    "meta.index.desc": "Recherchez un nom de marque, un nom générique ou un surnom et consultez l'ingrédient actif, la concentration et les noms du même produit dans d'autres pays. Référence publique et non commerciale.",
    "meta.about.title": "À propos · Référence croisée des marques de médicaments",
    "meta.about.desc": "Comment fonctionne ce croisement : sources et couverture, licences et attribution, lacunes connues et règles éditoriales. Référence uniquement, pas un avis médical.",
    "meta.confused.title": "Noms de médicaments faciles à confondre · Référence croisée des marques de médicaments",
    "meta.confused.desc": "Paires de sosies et de sons semblables d'hommes de grande taille de la FDA : un avertissement sur les noms, pas une déclaration selon laquelle les médicaments sont interchangeables.",
    "meta.warn.title": "Avertissements : même nom, médicament différent · Référence croisée des marques de médicaments",
    "meta.warn.desc": "Avertissements publiés sur les produits et combinaisons de médicaments de même nom/différents qui ne sont pas interchangeables selon les pays, les formes de sel ou les mécanismes de libération. Information seulement.",
    "meta.whatsnew.title": "Quoi de neuf · Référence croisée entre les marques de médicaments",
    "meta.whatsnew.desc": "Notes de version pour les références croisées des marques de médicaments : correctifs et ajouts dans chaque version.",
    "glossary.t.inn": "AUBERGE",
    "glossary.d.inn": "Dénomination commune internationale : le nom générique de l'OMS pour un ingrédient actif (par exemple, acétaminophène/paracétamol, métoprolol).",
    "glossary.t.ban": "INTERDIRE",
    "glossary.d.ban": "British Approved Name : le nom générique britannique, généralement identique à INN ; quelques noms plus anciens diffèrent (par exemple, adrénaline pour épinéphrine).",
    "glossary.t.usan": "USAAN",
    "glossary.d.usan": "Nom adopté aux États-Unis : le nom générique américain ; principalement DCI, mais parfois différent (par exemple albutérol pour le salbutamol).",
    "glossary.t.atc": "Code ATC",
    "glossary.d.atc": "Classification Anatomique Thérapeutique Chimique (OMS) : un code tel que C07AB02. Les premières lettres/chiffres sont regroupés par organe/système, classe et substance – utiles pour trouver le même type de médicament sur tous les marchés.",
    "glossary.d.mah": "Titulaire de l'autorisation de mise sur le marché : l'entreprise qui détient la licence pour un produit sur un marché ; pas nécessairement l'usine.",
    "glossary.t.din": "VACARME",
    "glossary.d.din": "Numéro d'identification du médicament : l'identifiant canadien du produit; Le DIN-HM est utilisé pour les produits homéopathiques.",
    "glossary.t.ndc": "CDN",
    "glossary.d.ndc": "National Drug Code : l'identifiant du produit américain (étiqueteur + produit + segments d'emballage).",
    "glossary.d.artg": "Numéro du Registre australien des produits thérapeutiques : identifie un bien thérapeutique répertorié/enregistré pour l'Australie.",
    "glossary.d.fdc": "Association à dose fixe : deux ingrédients actifs ou plus dans un seul produit (par exemple metformine + glibenclamide). Une page combinée sur ce site.",
    "glossary.t.lasa": "LASA / homme de grande taille",
    "glossary.d.lasa": "Noms de médicaments qui se ressemblent et se ressemblent. Les lettres « grand homme » de la FDA et la liste de noms confus aident à éviter les confusions entre des noms similaires.",
    "glossary.t.otc": "De gré à gré",
    "glossary.d.otc": "En vente libre : vendu sans ordonnance sur ce marché ; le même médicament peut être délivré uniquement sur ordonnance ailleurs.",
    "glossary.t.rx": "réception",
    "glossary.d.rx": "Médicament uniquement sur ordonnance sur ce marché.",
    "glossary.t.strength": "Force",
    "glossary.d.strength": "La quantité de principe actif par unité (par exemple 500 mg par comprimé) ; les forces et les formes de version peuvent varier selon les marchés.",
    "atc.browse_title": "Rechercher par classe ATC",
    "atc.browse_intro": "Les classes ATC de l’OMS regroupent les médicaments par organe/système et classe pharmacologique. Partez d’un groupe de niveau supérieur ou d’une catégorie de consommateurs ; chaque page répertorie les ingrédients actifs enregistrés ici.",
    "atc.level": "Niveau ATC",
    "atc.parent": "Classe parentale",
    "atc.children": "Cours pour enfants",
    "atc.ingredients": "Principes actifs de cette classe",
    "atc.count": "{n} ingrédients actifs",
    "atc.more": "et {n} plus",
    "atc.no_data": "Aucun ingrédient actif enregistré dans cette classe pour le moment.",
    "atc.unnamed": "Le nom de la classe n'a pas encore été révisé — le code ATC fait autorité.",
    "atc.ai_note": "Les noms de classe et de catégorie sont des traductions éditoriales ou assistées par l’IA ; seuls le code ATC et la hiérarchie de l'OMS font autorité.",
    "atc.source_note": "Les codes ATC et la hiérarchie font référence à l’index ATC/DDD du Centre collaborateur de l’OMS pour la méthodologie des statistiques sur les médicaments (droit d’auteur WHOCC ; l’index lui-même n’est pas reproduit). Les informations sur les ingrédients/concentrations proviennent des dossiers des régulateurs répertoriés dans À propos.",
    "atc.show_all": "Afficher tout {n} (affichant actuellement {shown})",
    "atc.salt_label": "Forme de sel :",
    "atc.status_note": "Les badges de statut résument les enregistrements de produits détenus pour chaque ingrédient (actif / abandonné / retiré / inconnu), et les codes de marché après chaque badge indiquent où ce statut est enregistré. Seuls certains registres publient une colonne d'état : CA, ES et MX le font ; AU et HK n'ont pas de colonne de statut et sont enregistrés comme inconnus ; Les enregistrements CN, US, GB, TW et SG sont inscrits au registre et marqués comme actifs.",
    "atc.markets_hint": "Chaque marché affiche désormais un statut agrégé : un marché est considéré comme en vente s'il a un enregistrement actif ; les statuts des enregistrements individuels sont affichés dans les détails. Un même marché peut également avoir plusieurs enregistrements d'enregistrement avec des statuts différents, de sorte que chaque marché n'apparaît ici qu'une seule fois ; il s'agit d'un fait enregistré, pas d'un jugement de sécurité.",
    "atc.ing_more": "{n} plus d'ingrédients — la liste complète apparaît lorsque le chargement de l'index complet est terminé.",
    "atc.nolang_note": "Un nom manquant est marqué dans sa ligne uniquement lorsqu'il s'agit d'une exception ; alors que la plupart des noms en manquent, la liste reste anonyme.",
    "atc.names_source_note": "Les noms de classes sont des traductions éditoriales ou proviennent de Wikipédia (CC BY-SA 4.0) / Wikidata (CC0) ; chaque page ATC répertorie la source exacte, la licence et le lien pour chaque langue. Seuls le code ATC et la hiérarchie de l'OMS font autorité.",
    "atc.all_classes": "Toutes les classes ATC",
    "atc.search_link": "Rechercher cette classe",
    "atc.view_class": "Voir cette classe ATC",
    "atc.categories_link": "Catégories de consommateurs",
    "atc4.summary": "Par forme galénique, sur tous les marchés",
    "atc4.loading": "Chargement des détails du formulaire…",
    "atc4.notice": "Une classe ATC regroupe uniquement les médicaments selon une pharmacologie/chimie similaire – cela ne signifie pas qu’ils sont interchangeables. Un ingrédient, une forme posologique, un mécanisme de libération ou une concentration différents ne sont pas interchangeables.",
    "atc4.scope": "Seuls les ingrédients avec une classe ATC enregistrée sont répertoriés (@@ATC_ALL@@ de @@ATC_ALL_N@@).",
    "atc4.form_col": "Forme posologique",
    "atc4.form_other": "d'autres formes",
    "atc4.sort_note": "Les lignes sont alphabétiques par forme posologique et les marchés suivent un ordre de marché fixe ; rien ici n’est classé ou recommandé. Seuls les ingrédients avec des enregistrements de produits comportent des lignes.",
    "atc4.empty": "Aucun enregistrement de produit au niveau du formulaire pour cette classe pour le moment.",
    "atc4.error": "Impossible de charger les détails du formulaire.",
    "cat.quick_title": "Parcourir par catégorie",
    "cat.browse_title": "Catégories de consommateurs courantes",
    "cat.intro": "Collections de sujets éditoriaux : chaque catégorie correspond aux classes ATC et aux ingrédients actifs. C'est une façon de parcourir, pas une preuve que les médicaments sont équivalents.",
    "cat.disclaimer": "Collection thématique – pas une revendication d’équivalence ou d’interchangeabilité.",
    "cat.count": "{n} ingrédients actifs",
    "cat.related_atc": "Classes ATC associées",
    "cat.no_data": "Aucun ingrédient actif enregistré pour cette catégorie pour le moment.",
    "cat.back": "Toutes les classes et catégories ATC",
    "parse.category": "Catégorie",
    "parse.category_note": "Collection de sujets correspondant – pas un nom, ni une revendication d'équivalence.",
    "parse.match.category": "Catégorie / Classe ATC",
    "bilingual.toggle": "Afficher l'original",
    "bilingual.brand_note": "Nom tel qu'enregistré sur ce marché – pas une traduction.",
    "bilingual.source.official": "officiel",
    "bilingual.source.regulator": "régulateur",
    "bilingual.source.pharmacopoeia": "pharmacopée",
    "bilingual.source.manual": "éditorial",
    "matrix.brand_note": "Chaque colonne de pays/région affiche les noms commerciaux enregistrés localement, et non les traductions.",
    "matrix.filters": "Filtres",
    "matrix.mobile_filters": "Filtres",
    "matrix.country": "Pays et régions",
    "matrix.form": "Formulaire",
    "matrix.release": "Libérer",
    "matrix.spec_search": "Force de recherche",
    "matrix.reset": "Restaurer les valeurs par défaut",
    "matrix.all": "Tous",
    "matrix.showing": "{n} / {total} lignes",
    "matrix.sort_note": "Les atouts communs d’abord ; force non divulguée en dernier.",
    "matrix.spec_check": "vérifier la force",
    "matrix.close": "Fermer",
    "form.kit": "trousse",
    "unit.meq": "mÉq",
    "meta.glossary.title": "Glossaire · Référence croisée entre les marques de médicaments",
    "meta.glossary.desc": "Brèves définitions des codes et termes utilisés sur ce site : INN, BAN, USAN, ATC, MAH, DIN, NDC, ARTG, FDC, LASA, OTC, Rx, Strength.",
    "about.data_package": "Paquet de données",
    "about.dataset_jsonld": "Métadonnées de l'ensemble de données (schema.org)",
    "about.checksums": "Sommes de contrôle SHA-256",
    "about.data_dictionary": "Dictionnaire de données",
    "about.licences_summary": "Sources de données et licences",
    "atc.ing_overview": "Ingrédients actifs de cette classe ATC : les lignes de noms de marque se chargent en arrière-plan.",
    "matrix.hidden_rows": "{n} des lignes supplémentaires de force/forme sont enregistrées uniquement dans {mk} et ne sont pas affichées dans ce tableau.",
    "matrix.hidden_show": "Ajouter ce marché en colonne",
    "matrix.undisclosed_note": "« non divulgué » signifie que la source ne publie pas la concentration – cela ne signifie pas que le produit n'en a pas.",
    "name.form_source": "tel qu'enregistré par la source",
    "name.form_granularity_cn": "La source enregistre la forme posologique uniquement au niveau de la classe (par exemple, « comprimé » ); les sous-formes effervescentes/enrobées ne sont pas distinguées.",
    "matrix.filters_short": "Filtres",
    "brand.mah_note": "Ce produit n'a pas de nom commercial enregistré ; le titulaire de l'autorisation de mise sur le marché est indiqué à la place.",
    "drug.forms_all": "Toutes les formes galéniques",
    "drug.forms_label": "Formes posologiques",
    "drug.forms_short": "Formulaires",
    "drug.also_in": "également dans",
    "drug.undisclosed_block": "Enregistrements sans force déclarée",
    "drug.specs": "points forts",
    "drug.compare_side": "Table côte à côte",
    "drug.view_list": "Retour à la liste",
    "drug.more_specs": "Autres atouts",
    "drug.more_specs_n": "Autres dosages : {n} · {m} formes posologiques",
    "drug.ms_more": "Ce formulaire a {n} plus",
    "drug.full_list": "Liste complète dans le paquet de données",
    "drug.und_more": "et {n} autres ({k} fabricants)",
    "drug.undisclosed_n": "{n} enregistrements · {k} fabricants",
    "drug.brand_group": "Avec un nom de marque",
    "drug.mah_group": "Fabricant uniquement",
    "drug.compare_note": "Un tableau côte à côte n'est proposé que lorsque cet ingrédient a des records sur de nombreux marchés ; sinon, cette liste représente l’ensemble du tableau.",
    "drug.markets": "marchés",
    "name.notice": "Même nom – vérifiez l’ingrédient ; les noms ne sont pas interchangeables.",
    "name.show_more": "Afficher plus",
    "warn.filter.all": "Tous",
    "cat.all_link": "Toutes les catégories →",
    "coverage.sort_products": "Par produits",
    "coverage.sort_market": "Par marché",
    "glossary.h2": "Termes et codes",
    "conf.h2": "Paires d'hommes de grande taille FDA",
    "atc.more_notes": "Remarques et licences",
})


# 覆盖页/About 的 FR 专用文案（不放进 I18N["fr"]，避免 fr 键集 ≠ en；开开关时按清单并入
# en/es/zh + 重生成 zh-Hant，并由 FR_I18N 提供 fr 值）。
FR_PREP_KEYS: dict[str, str] = {
    "home.fr": "France",
    # v0.11.5 task-3：法国行补「规格来源」说明（fr-only；en/es/zh 各自的 coverage.gap.fr 不动）。
    # 1,987 / 15,799 来自 reports/2026-11-14-fr-quality.md（品名补足，BDPM composition 未给剂量）；
    # 该说明成立的前提是 task-68 的 FR apply 已写库，否则本行规格% 仍是 71.2%。
    "coverage.gap.fr": ("BDPM (ANSM) — Licence Ouverte / etalab-2.0, attribution requise ; "
                        "date de mise à jour dans le paquet de données ; autorisation ≠ vente. "
                        "1 987 produits sur 15 799 ont une teneur issue du nom du produit "
                        "(la composition BDPM ne donne pas de dosage) ; données au 2026-11-03."),
    "about.fr_source": ("<p class=\"sub\"><b>France</b> : BDPM (Base de données publique des "
                        "médicaments, ANSM), <b>Licence Ouverte / etalab-2.0</b> ; attribution "
                        "et date de mise à jour requises. Données au <b>2026-11-03</b>. Faits "
                        "seulement (nom, principe, forme, titulaire, autorisation). "
                        "<a href=\"https://base-donnees-publique.medicaments.gouv.fr/\">BDPM</a>.</p>"),
}


# v0.6.2：四语言。zh-Hant 的 URL 目录用全小写 zh-hant/（hreflang 仍是 BCP47 zh-Hant）。
# v0.11.4（task-55）：LANGS 由 data/languages.json 的 enabled 决定 —— fr 目前 enabled:false
# → 不生成 /fr/、不产 fr 资产；把 fr 改成 true 才会上线（开启清单见 reports/2026-11-13-fr-site-prep.md）。
_BASE_LANGS = [("en", "EN", ""), ("es", "ES", "es/"), ("zh", "中文", "zh/"),
               ("zh-Hant", "繁", "zh-hant/")]


def _enabled_ui_langs() -> list[tuple[str, str, str]]:
    """注册表 enabled 语言 → 站点 LANGS（仅收已具备 I18N 字典的语言）。"""
    langs = list(_BASE_LANGS)
    try:
        reg = json.loads((ROOT / "data" / "languages.json").read_text(encoding="utf-8"))
        enabled = {x.get("code") for x in reg.get("languages", []) if x.get("enabled")}
    except (OSError, ValueError):
        enabled = set()
    for code, label, path in (("fr", "FR", "fr/"),):
        # 注意：I18N["fr"] 由 _merge_static_i18n() 在 main() 里生成，模块导入时还不存在；
        # 这里只按注册表 enabled 判断（fr 的语言字典在构建前一定已就绪）。
        if code in enabled:
            langs.append((code, label, path))
    return langs


LANGS = _enabled_ui_langs()
# 构建期四语硬拦：跟随 LANGS（fr 关闭时仍是 4 语；开启后 fr 也纳入键集检查）。
I18N_REQUIRED_LANGS = tuple(code for code, _label, _path in LANGS)
LANG_PATH = {code: path for code, _label, path in LANGS}
LANG_HREFLANG = {code: ("zh-Hant" if code == "zh-Hant" else code)
                 for code, _label, _path in LANGS}
# i18n.js 运行时用：?lang=zh-hant、/zh-hant/、navigator.language=zh-TW 等 → zh-Hant
LANG_ALIASES = {
    "zh-hant": "zh-Hant", "zh_hant": "zh-Hant", "zh-tw": "zh-Hant",
    "zh-hk": "zh-Hant", "zh-mo": "zh-Hant",
    "zh-hans": "zh", "zh-cn": "zh", "zh-sg": "zh",
}
LANG_META_JS = (
    "var LANG_PATH=" + json.dumps(LANG_PATH, ensure_ascii=False, separators=(",", ":")) + ";\n"
    + "var LANG_ALIAS=" + json.dumps(LANG_ALIASES, ensure_ascii=False, separators=(",", ":")) + ";\n"
    # v0.10.1：首页只内联当前语言字典时，canon() 仍要知道站点支持哪些语言
    # （否则 ?lang=es / localStorage=zh 会被当成不支持 → 掉回 en）。
    + "var I18N_LANGS=" + json.dumps([c for c, _l, _p in LANGS], separators=(",", ":")) + ";\n"
    + "var DEFAULT_LANG='en';"
)

# v0.10.2：语言判定（?lang= → 路径 → localStorage → navigator.language）只有这一份源码。
# boot.js 要在插入字典包**之前**就知道该拉哪份，i18n.js 里也要用它算 window.LANG，
# 两处引用同一段文本，改这里两边同时生效（LANG_PATH/LANG_ALIAS/I18N_LANGS 来自 LANG_META_JS）。
# 函数名加 __dsh 前缀：boot.js 是普通脚本，函数会落在全局，避免和 app.js 撞名。
LANG_PICK_JS = r"""
function __dshLangHas(y){
  if(!y) return false;
  if((window.I18N_LANGS || []).indexOf(y) >= 0) return true;   // v0.10.1：以支持列表为准
  return !!(window.I18N && window.I18N[y]);
}
function __dshCanonLang(x){
  if(!x) return '';
  var c = String(x).trim();
  if(__dshLangHas(c)) return c;
  var l = c.toLowerCase();
  if(LANG_ALIAS[l] && __dshLangHas(LANG_ALIAS[l])) return LANG_ALIAS[l];
  var base = l.split('-')[0];
  if(base && __dshLangHas(base)) return base;
  return '';
}
function __dshRelPath(rootPath){
  // 相对站点根的路径，例如 /drug-brand-crossref/es/ → "es/"，子页 → "drug/x.html"。
  var p = location.pathname;
  rootPath = rootPath || '/';
  return p.indexOf(rootPath) === 0 ? p.slice(rootPath.length) : p.replace(/^\//, '');
}
function __dshPickLang(rootPath){
  var q = __dshCanonLang(new URLSearchParams(location.search).get('lang'));
  if(q){ try{localStorage.setItem('lang',q);}catch(e){} return q; }
  var first = __dshRelPath(rootPath).split('/').filter(Boolean)[0] || '';
  // 直接进 /es/、/zh/、/zh-hant/（hreflang 主入口）时把语言写进 localStorage，
  // 这样点导航去 /about.html 等根路径页面不会掉回 en。
  var seg = __dshCanonLang(first);
  if(seg){ try{localStorage.setItem('lang',seg);}catch(e){} return seg; }
  try{ var s = __dshCanonLang(localStorage.getItem('lang')); if(s) return s; }catch(e){}
  var n = __dshCanonLang(navigator.language);
  return n || (window.DEFAULT_LANG || 'en');
}
"""

# ── v0.6.3 U3：界面标签本地化（LABEL_I18N）+ U1/U2 文案（UI_I18N） ──────────
# 单一数据源：服务端 label helper 与客户端 T() 共用同一批 key；zh-Hant 直接给值，
# 不再依赖 data/i18n_zh_hant.json（新 key 无法及时进该 JSON 时也不会回落简体）。
LABEL_I18N = {
    "en": {
        "form.tablet": "tablet", "form.capsule": "capsule", "form.liquid": "liquid",
        "form.injection": "injection", "form.topical": "topical", "form.powder": "powder",
        "form.suppository": "suppository", "form.inhalation": "inhalation",
        "form.pellet": "pellet", "form.stick": "stick", "form.kit": "kit",
        "form.gas": "gas", "form.unknown": "unknown",
        "form.effervescent": "effervescent", "form.granule": "granules", "form.solution": "solution",
        "release.ER": "extended-release", "release.DR": "delayed-release",
        "release.MR": "modified-release", "release.none": "—",
        "unit.iu": "IU", "unit.unit": "unit", "unit.meq": "mEq", "unit.mci": "mCi",
        "unit.ug": "mcg", "unit.microgram": "mcg", "unit.万iu": "10k IU",
    },
    "es": {
        "form.tablet": "comprimido", "form.capsule": "cápsula", "form.liquid": "líquido",
        "form.injection": "inyectable", "form.topical": "tópico", "form.powder": "polvo",
        "form.suppository": "supositorio", "form.inhalation": "inhalación",
        "form.pellet": "pélete", "form.stick": "barra", "form.kit": "kit",
        "form.gas": "gas", "form.unknown": "desconocido",
        "form.effervescent": "efervescente", "form.granule": "granulado", "form.solution": "solución",
        "release.ER": "liberación prolongada", "release.DR": "liberación retardada",
        "release.MR": "liberación modificada", "release.none": "—",
        "unit.iu": "UI", "unit.unit": "unidad", "unit.meq": "meq", "unit.mci": "mCi",
        "unit.ug": "mcg", "unit.microgram": "mcg", "unit.万iu": "10 000 UI",
    },
    "zh": {
        "form.tablet": "片剂", "form.capsule": "胶囊", "form.liquid": "液体",
        "form.injection": "注射剂", "form.topical": "外用", "form.powder": "粉末",
        "form.suppository": "栓剂", "form.inhalation": "吸入剂",
        "form.pellet": "微丸", "form.stick": "棒剂", "form.kit": "套装",
        "form.gas": "气体", "form.unknown": "未知",
        "form.effervescent": "泡腾剂", "form.granule": "颗粒", "form.solution": "溶液",
        "release.ER": "缓释", "release.DR": "延迟释放",
        "release.MR": "改良释放", "release.none": "—",
        "unit.iu": "国际单位", "unit.unit": "单位", "unit.meq": "毫当量", "unit.mci": "mCi",
        "unit.ug": "mcg", "unit.microgram": "mcg", "unit.万iu": "10 万 IU",
    },
    "zh-Hant": {
        "form.tablet": "錠劑", "form.capsule": "膠囊", "form.liquid": "液體",
        "form.injection": "注射劑", "form.topical": "外用", "form.powder": "粉末",
        "form.suppository": "栓劑", "form.inhalation": "吸入劑",
        "form.pellet": "微丸", "form.stick": "棒劑", "form.kit": "套組",
        "form.gas": "氣體", "form.unknown": "未知",
        "form.effervescent": "泡騰劑", "form.granule": "顆粒", "form.solution": "溶液",
        "release.ER": "緩釋", "release.DR": "延遲釋放",
        "release.MR": "修飾釋放", "release.none": "—",
        "unit.iu": "國際單位", "unit.unit": "單位", "unit.meq": "毫當量", "unit.mci": "mCi",
        "unit.ug": "mcg", "unit.microgram": "mcg", "unit.万iu": "10 萬 IU",
    },
}
# v0.9.4 A4：每市场覆盖与新鲜度页（只列事实，不做等价/用药判断）。
COVERAGE_I18N = {
    "en": {
        "nav.coverage": "Coverage",
        "meta.coverage.title": "Coverage & freshness · Medicine Brand Cross-Reference",
        "meta.coverage.desc": ("Products, ingredient mapping, spec coverage, last sync and known gaps "
                               "for each market; figures are computed from the current database."),
        "coverage.title": "Coverage & freshness",
        "coverage.intro": ("What each market contributes, how complete it is, and when it was last "
                           "synced. Counts are records, not unique medicines; a blank/0% means the "
                           "source does not publish that field."),
        "coverage.notice": ("This page lists data facts only. It does not imply that products are "
                            "interchangeable, on sale, or equivalent across markets."),
        "coverage.col.market": "Market",
        "coverage.col.products": "Products",
        "coverage.col.mapping": "Ingredient mapped",
        "coverage.col.spec": "Spec coverage",
        "coverage.col.last": "Last sync",
        "coverage.col.asof": "Data as of",
        "coverage.col.notes": "Known gaps",
        "coverage.no_brand": "no trade-name records",
        "coverage.source_note": ("Sources and licences: see About and docs/许可清单.md. Restricted "
                                  "sources are aggregated only in the data package."),
        "coverage.gap.us": "Full openFDA source; public-domain US government work.",
        "coverage.gap.gb": "Full dm+d source; Open Government Licence attribution.",
        "coverage.gap.ca": "Full DPD source; non-commercial reuse with attribution.",
        "coverage.gap.au": "ARTG export has no registration-status column; status is unknown, not 'on sale'. Some products have no ingredient records.",
        "coverage.gap.sg": "Registered listing does not prove current supply.",
        "coverage.gap.cn": "No public redistribution licence confirmed; some records have no trade name.",
        "coverage.gap.es": "Source licence for redistribution is pending confirmation.",
        "coverage.gap.mx": "Source licence is pending confirmation; older registrations are included.",
        "coverage.gap.tw": "Strength is parsed from the product name; confidence is limited.",
        "coverage.gap.hk": "Name/ingredient layer only: no strength, form or registration status; registered ≠ marketed.",
    },
    "es": {
        "nav.coverage": "Cobertura",
        "meta.coverage.title": "Cobertura y frescura · Medicine Brand Cross-Reference",
        "meta.coverage.desc": ("Productos, mapeo de principios, cobertura de concentración, última "
                               "sincronización y huecos por mercado; cifras calculadas desde la base actual."),
        "coverage.title": "Cobertura y frescura",
        "coverage.intro": ("Qué aporta cada mercado, su grado de completitud y la última sincronización. "
                           "Los conteos son registros, no medicamentos únicos; 0% significa que la fuente "
                           "no publica ese campo."),
        "coverage.notice": ("Esta página solo describe datos. No implica que los productos sean "
                            "intercambiables, estén a la venta o sean equivalentes entre mercados."),
        "coverage.col.market": "Mercado",
        "coverage.col.products": "Productos",
        "coverage.col.mapping": "Principio mapeado",
        "coverage.col.spec": "Cobertura de concentración",
        "coverage.col.last": "Última sincronización",
        "coverage.col.asof": "Datos hasta",
        "coverage.col.notes": "Huecos conocidos",
        "coverage.no_brand": "registros sin nombre comercial",
        "coverage.source_note": ("Fuentes y licencias: ver About y docs/许可清单.md. Las fuentes "
                                  "restringidas solo se agregan en el paquete de datos."),
        "coverage.gap.us": "Fuente openFDA completa; obra del gobierno de EE. UU. de dominio público.",
        "coverage.gap.gb": "Fuente dm+d completa; atribución de Open Government Licence.",
        "coverage.gap.ca": "Fuente DPD completa; reutilización no comercial con atribución.",
        "coverage.gap.au": "La exportación ARTG no trae estado de registro; el estado es desconocido, no «en venta». Algunos productos no tienen ingredientes.",
        "coverage.gap.sg": "Estar en el listado no prueba que se comercialice actualmente.",
        "coverage.gap.cn": "No hay licencia pública de redistribución confirmada; algunos registros no tienen nombre comercial.",
        "coverage.gap.es": "La licencia de redistribución está pendiente de confirmación.",
        "coverage.gap.mx": "La licencia está pendiente de confirmación; se incluyen registros antiguos.",
        "coverage.gap.tw": "La concentración se extrae del nombre del producto; confianza limitada.",
        "coverage.gap.hk": "Solo capa de nombre/ingrediente: sin concentración, forma ni estado de registro; en registro ≠ en venta.",
    },
    "zh": {
        "nav.coverage": "覆盖与新鲜度",
        "meta.coverage.title": "覆盖与新鲜度 · 药品商品名跨国定位",
        "meta.coverage.desc": "各市场的产品数、成分映射率、规格覆盖、最后同步与已知缺口；数字按当前数据库构建期计算。",
        "coverage.title": "覆盖与新鲜度",
        "coverage.intro": "各市场贡献什么、完整度如何、最后同步时间。计数是记录数，不是去重药品数；空白或 0% 表示来源不提供该字段。",
        "coverage.notice": "本页只列数据事实，不代表产品可互换、在售或跨市场等价。",
        "coverage.col.market": "市场",
        "coverage.col.products": "产品数",
        "coverage.col.mapping": "成分已映射",
        "coverage.col.spec": "规格覆盖",
        "coverage.col.last": "最后同步",
        "coverage.col.asof": "数据截止",
        "coverage.col.notes": "已知缺口",
        "coverage.no_brand": "条记录无商品名",
        "coverage.source_note": "来源与许可见 About 与 docs/许可清单.md；受限来源在数据包中只以聚合形式出现。",
        "coverage.gap.us": "openFDA 全量；美国政府公开领域作品。",
        "coverage.gap.gb": "dm+d 全量；Open Government Licence 署名。",
        "coverage.gap.ca": "DPD 全量；非商业再使用须署名。",
        "coverage.gap.au": "ARTG 导出无注册状态列；状态未知，不等于在售。部分产品无成分记录。",
        "coverage.gap.sg": "在册不等于当前在售。",
        "coverage.gap.cn": "公开再发布许可未确认；部分记录无商品名。",
        "coverage.gap.es": "再发布许可待确认。",
        "coverage.gap.mx": "许可待确认；包含较早注册记录。",
        "coverage.gap.tw": "规格由品名解析，置信度有限。",
        "coverage.gap.hk": "仅名称/成分层：无规格、无剂型、无注册状态；在册≠在售。",
    },
    "zh-Hant": {
        "nav.coverage": "覆蓋與新鮮度",
        "meta.coverage.title": "覆蓋與新鮮度 · 藥品商品名跨國定位",
        "meta.coverage.desc": "各市場的產品數、成分映射率、規格覆蓋、最後同步與已知缺口；數字按目前資料庫建置期計算。",
        "coverage.title": "覆蓋與新鮮度",
        "coverage.intro": "各市場貢獻什麼、完整度如何、最後同步時間。計數是紀錄數，不是去重藥品數；空白或 0% 表示來源不提供該欄位。",
        "coverage.notice": "本頁只列資料事實，不代表產品可互換、在售或跨市場等價。",
        "coverage.col.market": "市場",
        "coverage.col.products": "產品數",
        "coverage.col.mapping": "成分已映射",
        "coverage.col.spec": "規格覆蓋",
        "coverage.col.last": "最後同步",
        "coverage.col.asof": "資料截止",
        "coverage.col.notes": "已知缺口",
        "coverage.no_brand": "筆紀錄無商品名",
        "coverage.source_note": "來源與許可見 About 與 docs/許可清單.md；受限來源在資料包中只以聚合形式出現。",
        "coverage.gap.us": "openFDA 全量；美國政府公開領域作品。",
        "coverage.gap.gb": "dm+d 全量；Open Government Licence 署名。",
        "coverage.gap.ca": "DPD 全量；非商業再使用須署名。",
        "coverage.gap.au": "ARTG 匯出無註冊狀態欄；狀態未知，不等於在售。部分產品無成分紀錄。",
        "coverage.gap.sg": "在冊不等於目前在售。",
        "coverage.gap.cn": "公開再發布許可未確認；部分紀錄無商品名。",
        "coverage.gap.es": "再發布許可待確認。",
        "coverage.gap.mx": "許可待確認；包含較早註冊紀錄。",
        "coverage.gap.tw": "規格由品名解析，置信度有限。",
        "coverage.gap.hk": "僅名稱/成分層：無規格、無劑型、無註冊狀態；在冊≠在售。",
    },
}
for _lang, _kv in COVERAGE_I18N.items():
    I18N.setdefault(_lang, {}).update(_kv)
# v0.9.4 name_lang：base 名语言与译名缺失角标（不翻译、不音译）
NAME_LANG_I18N = {
    "en": {"name.no_en": "No English name recorded", "name.no_es": "Sin nombre en español",
           "name.no_zh": "无中文名", "name.no_zh_hant": "無中文名"},
    "es": {"name.no_en": "No English name recorded", "name.no_es": "Sin nombre en español",
           "name.no_zh": "无中文名", "name.no_zh_hant": "無中文名"},
    "zh": {"name.no_en": "No English name recorded", "name.no_es": "Sin nombre en español",
           "name.no_zh": "无中文名", "name.no_zh_hant": "無中文名"},
    "zh-Hant": {"name.no_en": "No English name recorded",
                "name.no_es": "Sin nombre en español",
                "name.no_zh": "無中文名", "name.no_zh_hant": "無中文名"},
}
for _lang, _kv in NAME_LANG_I18N.items():
    I18N.setdefault(_lang, {}).update(_kv)
UI_I18N = {
    "en": {
        "u1.title": "How to use it in 3 steps",
        "u1.step1": "Type the name from the pack",
        "u1.step1_hint": ("Brand, generic name, nickname, or a line from the pack — "
                          "dose included is fine."),
        # 2026-11-11 v0.11.2（条目 8）：三步改成「输名 → 确认这条候选的成分/规格/剂型 → 选目标市场」
        "u1.step2": "Check this candidate: ingredient, strength, dosage form",
        "u1.step2_hint": ("The card shows one candidate, never the answer — check its "
                          "ingredient, strength and form against your pack."),
        "u1.step3": "Pick the target market",
        "u1.step3_hint": ("Pick a target market to see what the same ingredient is called "
                          "there; the candidate list itself does not change."),
        "u1.try": "Try:", "u1.close": "Dismiss", "u1.aria": "Getting-started guide",
        "u2.title": "Names by country/region",
        "u2.hint": ("Same ingredient, local name — click a country/region to see its products. "
                    "Not listed does not prove it is unavailable there."),
        "u2.none": "Not listed",
        "u2.none_hint": ("No product under this ingredient in this market's public data. "
                         "This does not prove it is unavailable there."),
        "u2.multi": "Several ingredients match — switch country/region to see the full list.",
        # v0.6.4 A2：ATC 码搜索 + B10 术语表
        "nav.glossary": "Glossary",
        "meta.glossary.title": "Glossary · Medicine Brand Cross-Reference",
        "meta.glossary.desc": ("Short definitions of the codes and terms used on this site: "
                               "INN, BAN, USAN, ATC, MAH, DIN, NDC, ARTG, FDC, LASA, OTC, Rx, "
                               "strength."),
        "parse.atc": "ATC code", "parse.match.atc": "ATC code",
        "atc.label": "ATC",
        "atc.hint": ("ATC prefix match — results are products whose active ingredient carries "
                     "this ATC code, not brand-name matches."),
        "atc.hit": ("ATC {code}: {n} product names matched by active-ingredient ATC code. "
                    "Identity only — not a recommendation."),
        "atc.none": "No recorded active ingredient carries this ATC code or prefix.",
        "atc.none_meta": "No ATC match for {code}",
        "atc.loading": "Loading the index for ATC search…",
        # v0.10.2 i18n：原来写死在模板里的 9 处文案（404 标题品牌名 / About 数据包四链接 /
        # 许可折叠标题 / 组合页 stub 三句）。四语齐，模板改走 data-i18n。
        "site.name": "Medicine Brand Cross-Reference",
        "about.data_package": "Data package",
        "about.dataset_jsonld": "Dataset metadata (schema.org)",
        "about.checksums": "SHA-256 checksums",
        "about.data_dictionary": "Data dictionary",
        "about.licences_summary": "Data sources and licences",
        "combo.stub_badge": "Combination record",
        "combo.stub_note": ("This combination page is not expanded; use the ingredient pages "
                            "or search."),
        "combo.stub_search": "Search",
        # ATC 码首查（v0.10.2 快车道）：先给成分摘要，商品名行由 core 在后台补
        "atc.ing_overview": ("Active ingredients in this ATC class — brand-name rows load in "
                             "the background."),
        # v0.10.2 task-4：矩阵里「可见列全空」的行不渲染，但必须说明还有多少、一键加列
        "matrix.hidden_rows": ("{n} more strength/form rows are recorded only in {mk} and are "
                               "not shown in this table."),
        "matrix.hidden_show": "Add this market as a column",
        "matrix.undisclosed_note": ("“not disclosed” means the source does not publish the "
                                    "strength — it does not mean the product has none."),
        # v0.10.2 R1：剂型列并列「来源原文」+ 中国来源的剂型粒度说明
        "name.form_source": "as recorded by source",
        "name.form_granularity_cn": ("Source records dose form only at class level (e.g. "
                                     "“tablet”); effervescent/coated sub-forms are not "
                                     "distinguished."),
        "matrix.filters_short": "Filters",
        # v0.10.2 task-10：CN 无商品名的产品，名称位显示「厂家：<上市许可持有人>」
        "brand.mah": "Manufacturer:",
        "brand.mah_note": ("This product has no registered trade name; the market "
                           "authorisation holder is shown instead."),
        # v0.10.3 task-16：成分页按国家分组清单
        "drug.forms_all": "All dosage forms",
        "drug.forms_label": "Dosage forms",
        "drug.forms_short": "Forms",
        "drug.also_in": "also in",
        "drug.undisclosed_block": "Records without a stated strength",
        "drug.specs": "strengths",
        "drug.compare_side": "Side-by-side table",
        "drug.view_list": "Back to the list",
        "drug.more_specs": "Other strengths",
        "drug.more_specs_n": "Other strengths: {n} · {m} dosage forms",
        "drug.ms_more": "This form has {n} more",
        "drug.full_list": "Full list in the data package",
        "drug.und_more": "and {n} more ({k} manufacturers)",
        "drug.undisclosed_n": "{n} records · {k} manufacturers",
        "drug.brand_group": "With a brand name",
        "drug.mah_group": "Manufacturer only",
        "drug.compare_note": "A side-by-side table is offered only when this ingredient has records in many markets; otherwise this list is the whole picture.",
        # v0.11.6 task-1（T12 C2/C3/C4）：品牌页「相关品牌名称与配方差异」表。
        # 文案只说身份对应与不可互换，不提 collision 视图的分级（「碰撞」是内部术语）。
        "fam.cmp_title": "Related brand names and formula differences",
        "fam.cmp_intro": ("A brand name can be registered differently and carry different active "
                          "ingredients in each market. This table is an identity mapping — not a "
                          "translation, and not a claim that the products are interchangeable."),
        "fam.cmp_market": "Market",
        "fam.cmp_name": "Registered name",
        "fam.cmp_ing": "All active ingredients",
        "fam.cmp_rel": "Relation",
        "fam.cmp_this": "This page",
        "fam.rel.same": "Same active ingredients",
        "fam.rel.diff": "Different active ingredients — not interchangeable",
        "fam.rel.partial": ("Some active ingredients in common — not the same combination, "
                            "not interchangeable"),
        "fam.rel.release": "Same active ingredients, different release — not interchangeable",
        "fam.rel.none": "No active ingredient recorded",
        # T10（plan §9）：剂型/规格成对、单复方分段、规格冲突机制（默认关闭）。
        "matrix.multi_form": "Multiple dosage forms",
        "drug.mono_section": "Only this ingredient",
        "drug.combo_section": "Combination products containing this ingredient",
        "matrix.spec_conflict": "strength unverified",
        "name.form_spec": "Strength by dosage form",
        # T13（v0.11.7，用户评审 D1–D7）：成分页筛选条、可点击计数、来源/日期提示、分类页搜索。
        "lf.market": "Market", "lf.kind": "Kind", "lf.all": "All", "lf.title": "Filters",
        "lf.all_kinds": "All kinds", "lf.spec": "Strength",
        "lf.spec_ph": "Filter strengths, e.g. 500 mg",
        "lf.none": "No row matches these filters.",
        "lf.count": "{shown} of {total} rows",
        "drug.more_names": "Show the other {n}",
        "drug.mkx_more": "Other {n} markets",
        "drug.spec_count": "{shown} shown of {n}",
        "mkmeta.source": "Source", "mkmeta.asof": "Data as of",
        "mkmeta.undisclosed": "some records have no stated strength",
        "mkmeta.unknown": "includes records with unknown status (not proof of sale)",
        "cat.help": "How to read this list", "cat.subcat": "Subclass",
        "cat.search_ph": "Search an ingredient in this category",
        "cat.search_none": "No ingredient matches.",
        "coverage.col.products": "Records",
        # T11（v0.11.7）：三步确认 + 对照（B1–B3）。徽标只用 same/diff/missing，不用「等价/可替代/可互换」。
        "t11.pick_this": "This one", "t11.pick_mine": "This is mine",
        "t11.picked": "Selected",
        "t11.reselect": "Reselect", "t11.compare_link": "Compare item by item →",
        "t11.still_candidates": "The candidate set is still {n} records — this is only one of them. See all candidates ↓",
        "t11.all_markets": "All",
        "t11.cmp_title": "Item-by-item comparison (identity only)",
        "t11.cmp_you": "Yours", "t11.cmp_target": "Target market",
        "t11.same": "Same", "t11.diff": "Different", "t11.missing": "Not recorded",
        "t11.name": "Registered name", "t11.spec": "Strength", "t11.release": "Release",
        "t11.cmp_note": "Field-by-field identity comparison only. Same name or same ingredient does not mean the products are interchangeable.",
        "t11.adv": "Advanced filters",
        "res.src_label": "Record market (only records registered here)",
    },
    "es": {
        "u1.title": "Cómo funciona en 3 pasos",
        "u1.step1": "Escribe el nombre del envase",
        "u1.step1_hint": ("Marca, genérico, apodo o una línea del envase; la dosis puede "
                          "ir incluida."),
        "u1.step2": "Comprueba este candidato: principio activo, dosis y forma",
        "u1.step2_hint": ("La tarjeta muestra un candidato, nunca la respuesta: compara "
                          "principio activo, dosis y forma con tu envase."),
        "u1.step3": "Elige el mercado destino",
        "u1.step3_hint": ("Elige un mercado destino para ver cómo se llama el mismo "
                          "principio activo allí; la lista de candidatos no cambia."),
        "u1.try": "Prueba:", "u1.close": "Cerrar", "u1.aria": "Guía de inicio",
        "u2.title": "Nombres por país/región",
        "u2.hint": ("Mismo principio, nombre local: haz clic en un país/región para ver sus "
                    "productos. «Sin datos» no prueba que no exista allí."),
        "u2.none": "Sin datos",
        "u2.none_hint": ("Sin datos públicos para este principio en ese mercado; no prueba "
                         "que no exista allí."),
        "u2.multi": "Varios principios coinciden — cambia de país/región para ver la lista completa.",
        # v0.6.4 A2：ATC 码搜索 + B10 术语表
        "nav.glossary": "Glosario",
        "meta.glossary.title": "Glosario · Medicine Brand Cross-Reference",
        "meta.glossary.desc": ("Definiciones breves de los códigos y términos usados en el sitio: "
                               "INN, BAN, USAN, ATC, MAH, DIN, NDC, ARTG, FDC, LASA, OTC, Rx, "
                               "concentración."),
        "parse.atc": "Código ATC", "parse.match.atc": "Código ATC",
        "atc.label": "ATC",
        "atc.hint": ("Coincidencia por prefijo ATC: los resultados son productos cuyo principio "
                     "activo lleva este código ATC, no nombres comerciales."),
        "atc.hit": ("ATC {code}: {n} nombres de producto coinciden por el código ATC del "
                    "principio activo. Solo identidad, no una recomendación."),
        "atc.none": "Ningún principio activo registrado lleva este código o prefijo ATC.",
        "atc.none_meta": "Sin coincidencias ATC para {code}",
        "atc.loading": "Cargando el índice para la búsqueda ATC…",
        # v0.10.2 i18n：与 en 同一批 key（模板里原来写死的 9 处）
        "site.name": "Referencia cruzada de marcas de medicamentos",
        "about.data_package": "Paquete de datos",
        "about.dataset_jsonld": "Metadatos del conjunto de datos (schema.org)",
        "about.checksums": "Sumas de verificación SHA-256",
        "about.data_dictionary": "Diccionario de datos",
        "about.licences_summary": "Fuentes de datos y licencias",
        "combo.stub_badge": "Registro de combinación",
        "combo.stub_note": ("Esta página de combinación no está ampliada; usa las páginas de "
                            "principios o la búsqueda."),
        "combo.stub_search": "Buscar",
        # ATC 码首查（v0.10.2 快车道）：先给成分摘要，商品名行由 core 在后台补
        "atc.ing_overview": ("Principios activos de esta clase ATC — las filas de nombres "
                             "comerciales se cargan en segundo plano."),
        "matrix.hidden_rows": ("Hay {n} filas de concentración/forma registradas solo en {mk} "
                               "que no se muestran en esta tabla."),
        "matrix.hidden_show": "Añadir este mercado como columna",
        "matrix.undisclosed_note": ("«no consta» significa que la fuente no publica la "
                                    "concentración; no significa que el producto no la tenga."),
        "name.form_source": "según la fuente",
        "name.form_granularity_cn": ("La fuente registra solo la forma de nivel de clase (p. ej. "
                                     "«comprimido»); no distingue subformas como efervescente o "
                                     "recubierto."),
        "matrix.filters_short": "Filtros",
        "brand.mah": "Titular:",
        "brand.mah_note": ("Este producto no tiene nombre comercial registrado; se muestra el "
                           "titular de la autorización."),
        # v0.10.3 task-16：成分页按国家分组清单
        "drug.forms_all": "Todas las formas farmacéuticas",
        "drug.forms_label": "Formas farmacéuticas",
        "drug.forms_short": "Formas",
        "drug.also_in": "también en",
        "drug.undisclosed_block": "Registros sin concentración indicada",
        "drug.specs": "presentaciones",
        "drug.compare_side": "Tabla comparativa",
        "drug.view_list": "Volver a la lista",
        "drug.more_specs": "Otras presentaciones",
        "drug.more_specs_n": "Otras concentraciones: {n} · {m} formas farmacéuticas",
        "drug.ms_more": "Esta forma tiene {n} más",
        "drug.full_list": "Lista completa en el paquete de datos",
        "drug.und_more": "y {n} más ({k} fabricantes)",
        "drug.undisclosed_n": "{n} registros · {k} fabricantes",
        "drug.brand_group": "Con nombre comercial",
        "drug.mah_group": "Solo fabricante",
        "drug.compare_note": "La tabla comparativa solo se ofrece cuando este principio tiene registros en muchos mercados; si no, esta lista es la información completa.",
        # v0.11.6 task-1（T12 C2/C3/C4）：品牌页「配方差异」表（与 en 同键集）。
        "fam.cmp_title": "Nombres de marca relacionados y diferencias de fórmula",
        "fam.cmp_intro": ("Un nombre de marca puede estar registrado de otra forma y contener "
                          "principios activos distintos en cada mercado. Esta tabla es una "
                          "correspondencia de identidad: no es una traducción y no implica que "
                          "los productos sean intercambiables."),
        "fam.cmp_market": "Mercado",
        "fam.cmp_name": "Nombre registrado",
        "fam.cmp_ing": "Principios activos completos",
        "fam.cmp_rel": "Relación",
        "fam.cmp_this": "Esta página",
        "fam.rel.same": "Mismos principios activos",
        "fam.rel.diff": "Principios activos distintos: no intercambiables",
        "fam.rel.partial": ("Comparte parte de los principios activos: no es la misma "
                            "combinación, no intercambiables"),
        "fam.rel.release": ("Mismos principios activos, liberación distinta: no intercambiables"),
        "fam.rel.none": "Sin principios activos registrados",
        # T10（plan §9）：与 en 同键集。
        "matrix.multi_form": "Varias formas farmacéuticas",
        "drug.mono_section": "Solo este principio activo",
        "drug.combo_section": "Asociaciones que contienen este principio activo",
        "matrix.spec_conflict": "concentración sin verificar",
        "name.form_spec": "Concentración por forma",
        # T13（v0.11.7）：成分页筛选条、可点击计数、来源/日期提示、分类页搜索。
        "lf.market": "Mercado", "lf.kind": "Tipo", "lf.all": "Todos", "lf.title": "Filtros",
        "lf.all_kinds": "Todos los tipos", "lf.spec": "Concentración",
        "lf.spec_ph": "Filtrar concentraciones, p. ej. 500 mg",
        "lf.none": "Ninguna fila coincide con estos filtros.",
        "lf.count": "{shown} de {total} filas",
        "drug.more_names": "Ver los otros {n}",
        "drug.mkx_more": "{n} mercados más",
        "drug.spec_count": "{shown} de {n} mostradas",
        "mkmeta.source": "Fuente", "mkmeta.asof": "Datos a",
        "mkmeta.undisclosed": "algunos registros no indican la concentración",
        "mkmeta.unknown": "incluye registros con estado desconocido (no implica venta)",
        "cat.help": "Cómo leer esta lista", "cat.subcat": "Subclase",
        "cat.search_ph": "Buscar un principio en esta categoría",
        "cat.search_none": "Ningún principio coincide.",
        "coverage.col.products": "Registros",
        "t11.pick_this": "Esta", "t11.pick_mine": "Es esta",
        "t11.picked": "Elegida",
        "t11.reselect": "Elegir otra", "t11.compare_link": "Comparar campo por campo →",
        "t11.still_candidates": "El conjunto de candidatos sigue siendo {n} registros: esta es solo una. Ver todos los candidatos ↓",
        "t11.all_markets": "Todos",
        "t11.cmp_title": "Comparación campo por campo (solo identidad)",
        "t11.cmp_you": "Tu registro", "t11.cmp_target": "Mercado destino",
        "t11.same": "Igual", "t11.diff": "Distinto", "t11.missing": "Sin registro",
        "t11.name": "Nombre registrado", "t11.spec": "Concentración", "t11.release": "Liberación",
        "t11.cmp_note": "Solo se comparan campos de identidad. Mismo nombre o mismo principio no significa que los productos sean intercambiables.",
        "t11.adv": "Filtros avanzados",
        "res.src_label": "Mercado del registro (solo registros de aquí)",
    },
    "zh": {
        "u1.title": "三步看懂",
        "u1.step1": "输入包装上的名字",
        "u1.step1_hint": "商品名、通用名、俗称或包装上一行字；可连剂量一起输入。",
        "u1.step2": "核对这条候选：成分、规格、剂型",
        "u1.step2_hint": "卡片只概括其中一条候选，不是答案；拿成分、规格、剂型和包装对一遍。",
        "u1.step3": "选目标市场",
        "u1.step3_hint": "选一个目标市场，看这个成分在当地叫什么；候选列表本身不变。",
        "u1.try": "试试：", "u1.close": "关闭", "u1.aria": "使用引导",
        "u2.title": "国家/地区叫法",
        "u2.hint": "同一成分在当地叫什么；点国家/地区看该地商品。未收录不等于该国家/地区没有这个药。",
        "u2.none": "未收录",
        "u2.none_hint": "公开数据里暂无该国该成分的产品；不等于该国没有这个药。",
        "u2.multi": "多成分/多结果，切国家/地区查看全部。",
        # v0.6.4 A2：ATC 码搜索 + B10 术语表
        "nav.glossary": "术语表",
        "meta.glossary.title": "术语表 · 药品商品名跨国定位",
        "meta.glossary.desc": ("本站常用代码与术语的简短解释：INN、BAN、USAN、ATC、MAH、DIN、NDC、"
                               "ARTG、FDC、LASA、OTC、Rx、规格。"),
        "parse.atc": "ATC 码", "parse.match.atc": "ATC 码",
        "atc.label": "ATC",
        "atc.hint": "按 ATC 码前缀匹配：结果是「活性成分带有该 ATC 码」的产品，不是商品名匹配。",
        "atc.hit": "ATC {code}：{n} 个商品名按活性成分 ATC 码命中。只做身份对应，不构成推荐。",
        "atc.none": "已收录的活性成分中没有这个 ATC 码或前缀。",
        "atc.none_meta": "{code} 没有 ATC 命中",
        "atc.loading": "正在加载索引以进行 ATC 搜索…",
        # v0.10.2 i18n：与 en 同一批 key（模板里原来写死的 9 处 + ATC 首查摘要）
        "site.name": "药品商品名跨国定位",
        "about.data_package": "数据包",
        "about.dataset_jsonld": "数据集元数据（schema.org）",
        "about.checksums": "SHA-256 校验和",
        "about.data_dictionary": "字段字典",
        "about.licences_summary": "数据来源与许可",
        "combo.stub_badge": "组合记录",
        "combo.stub_note": "该组合页暂未展开；请从成分页或搜索入口查看。",
        "combo.stub_search": "搜索",
        "atc.ing_overview": "该 ATC 类目下的活性成分——商品名行由完整索引在后台补全。",
        "matrix.hidden_rows": "另有 {n} 个规格/剂型仅在 {mk} 有记录（未在本表显示）。",
        "matrix.hidden_show": "把这个市场加为一列",
        "matrix.undisclosed_note": "「未公开」表示来源没有披露规格，不等于该产品没有规格。",
        "name.form_source": "来源原文",
        "name.form_granularity_cn": "来源只记到剂型大类（如「片剂」），不细分泡腾、薄膜衣等子剂型。",
        "matrix.filters_short": "筛选",
        "brand.mah": "厂家：",
        "brand.mah_note": "该产品没有登记商品名，这里显示上市许可持有人。",
        # v0.10.3 task-16：成分页按国家分组清单
        "drug.forms_all": "全部剂型",
        "drug.forms_label": "剂型",
        "drug.forms_short": "剂型",
        "drug.also_in": "也在",
        "drug.undisclosed_block": "未公开规格的记录",
        "drug.specs": "个规格",
        "drug.compare_side": "并排对照表",
        "drug.view_list": "回到清单",
        "drug.more_specs": "其余规格",
        "drug.more_specs_n": "其余规格 {n} 个 · 涉及 {m} 种剂型",
        "drug.ms_more": "该剂型还有 {n} 个",
        "drug.full_list": "完整清单见数据包",
        "drug.und_more": "还有 {n} 个（{k} 个厂家）",
        "drug.undisclosed_n": "{n} 个记录 · {k} 个厂家",
        "drug.brand_group": "有商品名",
        "drug.mah_group": "仅厂家",
        "drug.compare_note": "并排对照表只在该成分跨市场记录较多时提供；否则这份清单就是全部。",
        # v0.11.6 task-1（T12 C2/C3/C4）：品牌页「配方差异」表（与 en 同键集）。
        "fam.cmp_title": "相关品牌名称与配方差异",
        "fam.cmp_intro": ("同一个品牌名在各市场的注册名与活性成分可以不同。下表只做身份对应"
                          "——不是翻译对照，也不代表这些产品可以互换。"),
        "fam.cmp_market": "市场",
        "fam.cmp_name": "注册名",
        "fam.cmp_ing": "完整活性成分",
        "fam.cmp_rel": "关系说明",
        "fam.cmp_this": "本页",
        "fam.rel.same": "活性成分相同",
        "fam.rel.diff": "活性成分不同，不可互换",
        "fam.rel.partial": "成分部分相同，不是同一复方，不可互换",
        "fam.rel.release": "成分相同，释放机制不同，不可互换",
        "fam.rel.none": "成分未收录",
        # T10（plan §9）：与 en 同键集。
        "matrix.multi_form": "多剂型",
        "drug.mono_section": "仅含此成分",
        "drug.combo_section": "含此成分的复方",
        "matrix.spec_conflict": "规格待核实",
        "name.form_spec": "规格（按剂型）",
        # T13（v0.11.7）：成分页筛选条、可点击计数、来源/日期提示、分类页搜索。
        "lf.market": "市场", "lf.kind": "成分类型", "lf.all": "全部", "lf.title": "筛选",
        "lf.all_kinds": "单方与复方", "lf.spec": "规格",
        "lf.spec_ph": "筛选规格，如 500 mg",
        "lf.none": "没有符合这些筛选条件的行。",
        "lf.count": "已展示 {shown} / 共 {total} 行",
        "drug.more_names": "查看其余 {n} 项",
        "drug.mkx_more": "另 {n} 个市场",
        "drug.spec_count": "展示 {shown} 个，共 {n} 个",
        "mkmeta.source": "来源", "mkmeta.asof": "数据截止",
        "mkmeta.undisclosed": "部分记录未公开规格",
        "mkmeta.unknown": "含状态未知记录（不等于在售）",
        "cat.help": "怎么看这份清单", "cat.subcat": "子类别",
        "cat.search_ph": "在本类中搜索成分",
        "cat.search_none": "没有匹配的成分。",
        "coverage.col.products": "记录数",
        "t11.pick_this": "这条", "t11.pick_mine": "我用的是这条",
        "t11.picked": "已选",
        "t11.reselect": "重选", "t11.compare_link": "逐项对照 →",
        "t11.still_candidates": "候选集仍然是 {n} 条记录——这条只是其中一条。看全部候选 ↓",
        "t11.all_markets": "全部",
        "t11.cmp_title": "逐项对照（只比身份字段）",
        "t11.cmp_you": "你这条", "t11.cmp_target": "目标市场",
        "t11.same": "相同", "t11.diff": "不同", "t11.missing": "未收录",
        "t11.name": "注册名", "t11.spec": "规格", "t11.release": "释放",
        "t11.cmp_note": "只按登记字段做身份对照；名字相同或成分相同都不代表这些产品可以互换。",
        "t11.adv": "高级筛选",
        "res.src_label": "记录市场（只看登记在这里的记录）",
    },
    "zh-Hant": {
        "u1.title": "三步看懂",
        "u1.step1": "輸入包裝上的名字",
        "u1.step1_hint": "商品名、通用名、俗稱或包裝上一行字；可連劑量一起輸入。",
        "u1.step2": "核對這條候選：成分、規格、劑型",
        "u1.step2_hint": "卡片只概括其中一條候選，不是答案；拿成分、規格、劑型和包裝對一遍。",
        "u1.step3": "選目標市場",
        "u1.step3_hint": "選一個目標市場，看這個成分在當地叫什麼；候選清單本身不變。",
        "u1.try": "試試：", "u1.close": "關閉", "u1.aria": "使用引導",
        "u2.title": "國家/地區叫法",
        "u2.hint": "同一成分在當地叫什麼；點國家/地區看該地商品。未收錄不等於該國家/地區沒有這個藥。",
        "u2.none": "未收錄",
        "u2.none_hint": "公開資料裡暫無該國該成分的產品；不等於該國沒有這個藥。",
        "u2.multi": "多成分/多結果，切國家/地區查看全部。",
        # v0.6.4 A2：ATC 码搜索 + B10 術語表
        "nav.glossary": "術語表",
        "meta.glossary.title": "術語表 · 藥品商品名跨國定位",
        "meta.glossary.desc": ("本站常用代碼與術語的簡短解釋：INN、BAN、USAN、ATC、MAH、DIN、NDC、"
                               "ARTG、FDC、LASA、OTC、Rx、規格。"),
        "parse.atc": "ATC 碼", "parse.match.atc": "ATC 碼",
        "atc.label": "ATC",
        "atc.hint": "依 ATC 碼前綴比對：結果是「有效成分帶有此 ATC 碼」的產品，不是商品名比對。",
        "atc.hit": "ATC {code}：{n} 個商品名依有效成分 ATC 碼命中。只做身分對應，不構成推薦。",
        "atc.none": "已收錄的有效成分中沒有這個 ATC 碼或前綴。",
        "atc.none_meta": "{code} 沒有 ATC 命中",
        "atc.loading": "正在載入索引以進行 ATC 搜尋…",
        # v0.10.2 i18n：與 en 同一批 key（模板裡原來寫死的 9 處 + ATC 首查摘要）
        "site.name": "藥品商品名跨國定位",
        "about.data_package": "資料包",
        "about.dataset_jsonld": "資料集詮釋資料（schema.org）",
        "about.checksums": "SHA-256 校驗碼",
        "about.data_dictionary": "欄位字典",
        "about.licences_summary": "資料來源與許可",
        "combo.stub_badge": "組合紀錄",
        "combo.stub_note": "該組合頁暫未展開；請從成分頁或搜尋入口查看。",
        "combo.stub_search": "搜尋",
        "atc.ing_overview": "該 ATC 類目下的有效成分——商品名資料列由完整索引在背景補齊。",
        "matrix.hidden_rows": "另有 {n} 個規格/劑型僅在 {mk} 有記錄（未在本表顯示）。",
        "matrix.hidden_show": "把這個市場加為一欄",
        "matrix.undisclosed_note": "「未公開」表示來源沒有揭露規格，不等於該產品沒有規格。",
        "name.form_source": "來源原文",
        "name.form_granularity_cn": "來源只記到劑型大類（如「錠劑」），不細分發泡、膜衣等子劑型。",
        "matrix.filters_short": "篩選",
        "brand.mah": "廠商：",
        "brand.mah_note": "該產品沒有登記商品名，這裡顯示上市許可持有人。",
        # v0.10.3 task-16：成分页按国家分组清单
        "drug.forms_all": "全部劑型",
        "drug.forms_label": "劑型",
        "drug.forms_short": "劑型",
        "drug.also_in": "也在",
        "drug.undisclosed_block": "未公開規格的紀錄",
        "drug.specs": "個規格",
        "drug.compare_side": "並排對照表",
        "drug.view_list": "回到清單",
        "drug.more_specs": "其餘規格",
        "drug.more_specs_n": "其餘規格 {n} 個 · 涉及 {m} 種劑型",
        "drug.ms_more": "該劑型還有 {n} 個",
        "drug.full_list": "完整清單見資料包",
        "drug.und_more": "還有 {n} 個（{k} 個廠商）",
        "drug.undisclosed_n": "{n} 個記錄 · {k} 個廠商",
        "drug.brand_group": "有商品名",
        "drug.mah_group": "僅廠商",
        "drug.compare_note": "並排對照表只在該成分跨市場紀錄較多時提供；否則這份清單就是全部。",
        # v0.9.7 task-12 UI 批次 A-1：结果页身份卡 / 分页 / 零结果（繁体显式覆盖层）
        "res.identity.ingredient": "有效成分",
        "res.identity.markets": "覆蓋市場",
        "res.identity.records": "{n} 筆紀錄",
        "res.same_name": "同名不同藥",
        "res.not_interchangeable": "跨市場不可互換",
        "res.identity_note": ("同一個名字在別的市場可能指向另一種成分；"
                              "請依成分、規格、劑型核對，不要只看名字。"),
        "res.action_drug": "查看成分頁",
        "res.action_copy": "複製標準名",
        "res.identity_title": "共 {n} 條候選，這是第 1 條",
        "res.src_label": "來源市場（只看這些登記庫的紀錄）：",
        "res.src_all": "全部來源市場",
        "res.src_active": "來源市場 {c}",
        "res.empty_h1": "沒有符合「{q}」",
        "res.empty_spelling": "檢查拼寫，或改用通用名",
        "res.empty_browse": "依類別瀏覽",
        "res.empty_coverage": "看覆蓋與新鮮度",
        "res.details": "詳情",
        "res.col_market": "市場",
        "res.showing": "顯示 {n} / {total}",
        "home.sub": "商品名、通用名、俗稱或包裝上一行字；中英文、全形、西里爾字母都能搜。",
        "home.candidate": "結果永遠是候選集，不是唯一答案。",
        "home.recent": "最近更新",
        "home.recent_all": "查看全部更新 →",
        "home.hint_idle": ("首次搜尋只載入一個檢索分片（中位約 1.0 MB，gzip 後約 0.16 MB）；"
                           "完整索引（core 約 42 MB，gzip 後約 9–10 MB）會在背景補齊"
                           "——直接輸入、點搜尋框或選一個範例。"),
        "home.hint_loading": "正在載入檢索分片（中位約 1.0 MB，gzip 後約 0.16 MB）…",
        # v0.6.6：成分頁多國並排矩陣
        "matrix.spec": "規格 / 劑型 / 釋放",
        "matrix.none": "未收錄",
        "matrix.hidden_note": "已停售、撤市或狀態未確認的產品預設隱藏；香港記錄（僅名稱/成分層）例外顯示。",
        "matrix.capped": "僅顯示前 {shown} / {total} 個規格列。",
        "matrix.original": "原紀錄",
        "matrix.country_all": "全選",
        "matrix.country_clear": "清除",
        "matrix.market_count": "市場 {shown}/{total}",
        "matrix.empty_markets": "至少選一個市場才會顯示欄。",
        "matrix.scroll_hint": "左右滑動查看更多市場 →",
        "brand.none": "無商品名",
        "a11y.skip": "跳至主要內容",
        "ingredient.unrecorded": "成分未收錄（名稱層）",
        "badge.export_only": "僅供出口",
        "maker.single_note": "目前未收錄該廠商的其他產品。",
        "name.single_note": "此名稱目前僅收錄 1 筆產品紀錄。",
        # task-141c：同物異名（成分頁「也稱」+ 檢索身份卡）的繁中值，避免回落簡體。
        "drug.also_known": "也稱：", "syn.tag": "異名",
        "nick.synonym": "異名",
        "nick.synonym_hit": "也稱",
        "nick.synonym_caveat": ("同一有效成分的另一種寫法（INN 與 USAN 差異或拼寫變體）。"
                                "只用於確認成分身分，不代表不同國家的產品可以互換。"),
        # v0.6.7：/warn 分頁
        "warn.page_prev": "上一頁", "warn.page_next": "下一頁",
        "warn.pagination": "警示分頁",
        "warn.page_status": "第 {n} / {total} 頁 · 共 {count} 條",
        # 2026-11-13 task-27：TW 中文标签改「中国台湾」（与「中国香港」一致）；
        # zh-Hant 不再手写覆盖，由 data/i18n_zh_hant.json 生成器给出的「中國台灣」生效。
        "home.hk": "中國香港",
        "home.eu": "歐盟（EU）",
        "home.fr": "法國",
        "coverage.gap.fr": "BDPM（ANSM）— Licence Ouverte / etalab-2.0，須署名；更新日期見資料包；授權有效 ≠ 在售。",
        "about.fr_source": ('<p class="sub"><b>法國</b>：BDPM（Base de données publique des médicaments，ANSM），'
                            '<b>Licence Ouverte / etalab-2.0</b>，須署名並註明更新日期；資料截至 <b>2026-11-03</b>。'
                            '只存事實欄位（名稱、成分、劑型、廠商、授權號）。'
                            '<a href="https://base-donnees-publique.medicaments.gouv.fr/">BDPM</a>。</p>'),
        "eu.region_title": "歐盟集中審批（EMA）",
        "eu.region_note": "歐盟層授權，不是某一國家的在售記錄；歐盟登記不含規格、劑型、包裝。",
        "eu.coverage_note": "歐盟區域層——僅集中審批產品；授權有效 ≠ 各國在售。",
        "coverage.gap.eu": "區域層：歐盟集中審批（EMA / EC Union Register）；不含規格、劑型、包裝；授權有效 ≠ 某國在售。",
        "about.tw_source": (
            '<p class="sub"><b>中國台灣</b>：TFDA「全部藥品許可證資料集」（data.gov.tw 資料集 9122）'
            '依<b>政府資料開放授權條款第 1 版（OGDL v1.0）</b>釋出，須署名「衛福部食藥署 TFDA」；'
            '資料截止 <b>2026-10-22</b>（每週同步）。只存事實欄位（品名、成分、劑型、廠商、'
            '許可證號、狀態）。<b>規格由品名解析，置信度有限。</b>'
            '授權：<a href="https://data.gov.tw/license">data.gov.tw/license</a>。</p>'),
        # v0.7.x：SG 市場（英文市場；zh-Hant 直接給值）
        "home.sg": "新加坡",
        "about.sg_source": (
            '<p class="sub"><b>新加坡</b>：HSA「Listing of Registered Therapeutic Products」'
            '（data.gov.sg 資料集 d_767279312753558cbf19d48344577084）依<b>新加坡開放資料授權條款'
            '第 1 版（SODL v1.0）</b>釋出，須署名並鏈回授權頁，不得暗示政府背書；資料截止 '
            '<b>2026-08-07</b>（每 6 個月更新）。<b>在冊名單不代表在售。</b>商品名保留英文原文、'
            '不翻譯；中文僅成分名（inn_zh）可顯示。</p>'),
        # v0.11.6 task-1（T12 C2/C3/C4）：品牌頁「配方差異」表（與 en 同鍵集）。
        "fam.cmp_title": "相關品牌名稱與配方差異",
        "fam.cmp_intro": ("同一個品牌名在各市場的註冊名與活性成分可以不同。下表只做身分對應"
                          "——不是翻譯對照，也不代表這些產品可以互換。"),
        "fam.cmp_market": "市場",
        "fam.cmp_name": "註冊名",
        "fam.cmp_ing": "完整活性成分",
        "fam.cmp_rel": "關係說明",
        "fam.cmp_this": "本頁",
        "fam.rel.same": "活性成分相同",
        "fam.rel.diff": "活性成分不同，不可互換",
        "fam.rel.partial": "成分部分相同，不是同一複方，不可互換",
        "fam.rel.release": "成分相同，釋放機制不同，不可互換",
        "fam.rel.none": "成分未收錄",
        # T10（plan §9）：與 en 同鍵集。
        "matrix.multi_form": "多劑型",
        "drug.mono_section": "僅含此成分",
        "drug.combo_section": "含此成分的複方",
        "matrix.spec_conflict": "規格待核實",
        "name.form_spec": "規格（按劑型）",
        # T13（v0.11.7）：成分頁篩選條、可點擊計數、來源/日期提示、分類頁搜尋。
        "lf.market": "市場", "lf.kind": "成分類型", "lf.all": "全部", "lf.title": "篩選",
        "lf.all_kinds": "單方與複方", "lf.spec": "規格",
        "lf.spec_ph": "篩選規格，如 500 mg",
        "lf.none": "沒有符合這些篩選條件的列。",
        "lf.count": "已顯示 {shown} / 共 {total} 列",
        "drug.more_names": "檢視其餘 {n} 項",
        "drug.mkx_more": "另 {n} 個市場",
        "drug.spec_count": "顯示 {shown} 個，共 {n} 個",
        "mkmeta.source": "來源", "mkmeta.asof": "資料截止",
        "mkmeta.undisclosed": "部分記錄未公開規格",
        "mkmeta.unknown": "含狀態未知記錄（不等於在售）",
        "cat.help": "怎麼看這份清單", "cat.subcat": "子類別",
        "cat.search_ph": "在本類中搜尋成分",
        "cat.search_none": "沒有符合的成分。",
        "coverage.col.products": "紀錄數",
        "t11.pick_this": "這筆", "t11.pick_mine": "我用的是這筆",
        "t11.picked": "已選",
        "t11.reselect": "重選", "t11.compare_link": "逐項對照 →",
        "t11.still_candidates": "候選集仍然是 {n} 筆記錄——這筆只是其中一筆。看全部候選 ↓",
        "t11.all_markets": "全部",
        "t11.cmp_title": "逐項對照（只比身分欄位）",
        "t11.cmp_you": "你這筆", "t11.cmp_target": "目標市場",
        "t11.same": "相同", "t11.diff": "不同", "t11.missing": "未收錄",
        "t11.name": "註冊名", "t11.spec": "規格", "t11.release": "釋放",
        "t11.cmp_note": "只按登記欄位做身分對照；名稱相同或成分相同都不代表這些產品可以互換。",
        "t11.adv": "進階篩選",
        "res.src_label": "記錄市場（只看登記在這裡的記錄）",
    },
}

# ── v0.9.8 task-13（UI 批次 A-2）：统一外壳 / 名字页警示 / 成分页身份行文案 ──
SHELL_I18N = {
    "en": {
        "nav.categories": "Categories", "nav.markets": "Markets",
        "nav.all_categories": "All categories & ATC",
        "tab.search": "Search", "tab.categories": "Categories",
        "tab.coverage": "Coverage", "tab.about": "About",
        "drug.markets": "markets",
        "name.notice": "Same name — check the ingredient; names are not interchangeable.",
        "name.show_more": "Show more",
        "warn.filter.all": "All", "cat.all_link": "All categories →", "coverage.sort_products": "By products", "coverage.sort_market": "By market", "glossary.h2": "Terms & codes", "conf.h2": "FDA tall-man pairs", "atc.more_notes": "Notes & licences", "res.density": "Compact view",
    },
    "es": {
        "nav.categories": "Categorías", "nav.markets": "Mercados",
        "nav.all_categories": "Todas las categorías y ATC",
        "tab.search": "Buscar", "tab.categories": "Categorías",
        "tab.coverage": "Cobertura", "tab.about": "Acerca de",
        "drug.markets": "mercados",
        "name.notice": "Mismo nombre — comprueba el principio activo; no son intercambiables.",
        "name.show_more": "Ver más",
        "warn.filter.all": "Todas", "cat.all_link": "Todas las categorías →", "coverage.sort_products": "Por productos", "coverage.sort_market": "Por mercado", "glossary.h2": "Términos y códigos", "conf.h2": "Pares tall-man de la FDA", "atc.more_notes": "Notas y licencias", "res.density": "Vista compacta",
    },
    "zh": {
        "nav.categories": "按类别", "nav.markets": "按市场",
        "nav.all_categories": "全部类别与 ATC",
        "tab.search": "搜索", "tab.categories": "类别",
        "tab.coverage": "覆盖", "tab.about": "关于",
        "drug.markets": "个市场",
        "name.notice": "同名不代表同一成分——请核对成分，不可互换。",
        "name.show_more": "显示更多",
        "warn.filter.all": "全部", "cat.all_link": "全部类别 →", "coverage.sort_products": "按产品数", "coverage.sort_market": "按市场", "glossary.h2": "术语与代码", "conf.h2": "FDA tall-man 易混淆药对", "atc.more_notes": "说明与许可", "res.density": "紧凑视图",
    },
    "zh-Hant": {
        "nav.categories": "按類別", "nav.markets": "按市場",
        "nav.all_categories": "全部類別與 ATC",
        "tab.search": "搜尋", "tab.categories": "類別",
        "tab.coverage": "覆蓋", "tab.about": "關於",
        "drug.markets": "個市場",
        "name.notice": "同名不代表同一成分——請核對成分，不可互換。",
        "name.show_more": "顯示更多",
        "warn.filter.all": "全部", "cat.all_link": "全部類別 →", "coverage.sort_products": "按產品數", "coverage.sort_market": "按市場", "glossary.h2": "術語與代碼", "conf.h2": "FDA tall-man 易混淆藥對", "atc.more_notes": "說明與許可", "res.density": "緊湊視圖",
    },
}

# ── v0.6.4 B10：术语表 /glossary.html（四语，INN/BAN/USAN/ATC/MAH/DIN/NDC/ARTG/FDC/LASA…）──
GLOSSARY_I18N = {
    "en": {
        "glossary.title": "Glossary",
        "glossary.intro": ("Short definitions for the codes and terms you see on product labels, "
                           "regulator records and on this site. It is a decoding aid, not medical "
                           "advice."),
        "glossary.term": "Term", "glossary.def": "Meaning",
        "glossary.note": ("Same acronym can differ by country (e.g. a DIN is Canadian, an ARTG "
                          "number is Australian). Always read the code with its source."),
        "glossary.t.inn": "INN",
        "glossary.d.inn": ("International Nonproprietary Name: the WHO generic name for an active "
                           "ingredient (e.g. acetaminophen/paracetamol, metoprolol)."),
        "glossary.t.ban": "BAN",
        "glossary.d.ban": ("British Approved Name: the UK generic name, usually identical to INN; "
                           "a few older names differ (e.g. adrenaline for epinephrine)."),
        "glossary.t.usan": "USAN",
        "glossary.d.usan": ("United States Adopted Name: the US generic name; mostly INN, but "
                            "sometimes different (e.g. albuterol for salbutamol)."),
        "glossary.t.atc": "ATC code",
        "glossary.d.atc": ("Anatomical Therapeutic Chemical classification (WHO): a code such as "
                           "C07AB02. The first letters/numbers group by organ/system, class and "
                           "substance — useful for finding the same kind of drug across markets."),
        "glossary.t.mah": "MAH",
        "glossary.d.mah": ("Marketing Authorisation Holder: the company that holds the licence "
                           "for a product in a market; not necessarily the factory."),
        "glossary.t.din": "DIN",
        "glossary.d.din": ("Drug Identification Number: the Canadian product identifier; "
                           "DIN-HM is used for homeopathic products."),
        "glossary.t.ndc": "NDC",
        "glossary.d.ndc": ("National Drug Code: the US product identifier (labeler + product + "
                           "package segments)."),
        "glossary.t.artg": "ARTG",
        "glossary.d.artg": ("Australian Register of Therapeutic Goods number: identifies a "
                            "therapeutic good listed/registered for Australia."),
        "glossary.t.fdc": "FDC",
        "glossary.d.fdc": ("Fixed-Dose Combination: two or more active ingredients in one product "
                           "(e.g. metformin + glibenclamide). A combination page on this site."),
        "glossary.t.lasa": "LASA / tall-man",
        "glossary.d.lasa": ("Look-Alike, Sound-Alike drug names. FDA 'tall-man' lettering and the "
                            "confused-names list help avoid mix-ups between similar names."),
        "glossary.t.otc": "OTC",
        "glossary.d.otc": ("Over-the-counter: sold without a prescription in that market; the "
                           "same medicine may be prescription-only elsewhere."),
        "glossary.t.rx": "Rx",
        "glossary.d.rx": "Prescription-only medicine in that market.",
        "glossary.t.strength": "Strength",
        "glossary.d.strength": ("The amount of active ingredient per unit (e.g. 500 mg per "
                                "tablet); strengths and release forms can vary between markets."),
    },
    "es": {
        "glossary.title": "Glosario",
        "glossary.intro": ("Definiciones breves de los códigos y términos que aparecen en envases, "
                           "registros de reguladores y en este sitio. Ayuda para descifrar, no es "
                           "consejo médico."),
        "glossary.term": "Término", "glossary.def": "Significado",
        "glossary.note": ("El mismo acrónimo puede variar según el país (un DIN es canadiense, un "
                          "número ARTG es australiano). Lee siempre el código con su fuente."),
        "glossary.t.inn": "INN",
        "glossary.d.inn": ("Nombre genérico internacional (OMS) del principio activo; p. ej. "
                           "acetaminofeno/paracetamol, metoprolol."),
        "glossary.t.ban": "BAN",
        "glossary.d.ban": ("Nombre genérico británico; casi siempre igual al INN, con algunas "
                           "excepciones (adrenalina por epinefrina)."),
        "glossary.t.usan": "USAN",
        "glossary.d.usan": ("Nombre genérico adoptado en EE. UU.; normalmente INN, a veces "
                            "distinto (albuterol por salbutamol)."),
        "glossary.t.atc": "Código ATC",
        "glossary.d.atc": ("Clasificación Anatómica Terapéutica Química (OMS): código tipo "
                           "C07AB02; agrupa por órgano, clase y sustancia y ayuda a encontrar "
                           "fármacos equivalentes entre mercados."),
        "glossary.t.mah": "MAH",
        "glossary.d.mah": ("Titular de la autorización de comercialización: empresa que posee la "
                           "licencia del producto en un mercado; no siempre es la fábrica."),
        "glossary.t.din": "DIN",
        "glossary.d.din": ("Drug Identification Number: identificador de producto canadiense; "
                           "DIN-HM se usa para homeopáticos."),
        "glossary.t.ndc": "NDC",
        "glossary.d.ndc": ("National Drug Code: identificador de producto estadounidense "
                           "(etiquetador + producto + envase)."),
        "glossary.t.artg": "ARTG",
        "glossary.d.artg": ("Australian Register of Therapeutic Goods: número de registro "
                            "australiano del producto terapéutico."),
        "glossary.t.fdc": "FDC",
        "glossary.d.fdc": ("Combinación en dosis fija: dos o más principios activos en un mismo "
                           "producto (p. ej. metformina + glibenclamida)."),
        "glossary.t.lasa": "LASA / tall-man",
        "glossary.d.lasa": ("Nombres parecidos o que suenan igual. La tipografía tall-man de la "
                            "FDA y las listas de nombres confundibles ayudan a evitar errores."),
        "glossary.t.otc": "OTC",
        "glossary.d.otc": ("Venta libre: sin receta en ese mercado; el mismo medicamento puede "
                           "ser de prescripción en otro país."),
        "glossary.t.rx": "Rx",
        "glossary.d.rx": "Medicamento con receta en ese mercado.",
        "glossary.t.strength": "Concentración",
        "glossary.d.strength": ("Cantidad de principio activo por unidad (p. ej. 500 mg por "
                                "comprimido); concentraciones y formas pueden variar entre países."),
    },
    "zh": {
        "glossary.title": "术语表",
        "glossary.intro": ("包装、监管记录和本站里常见代码/术语的简短解释。只帮助读代码，不是医疗建议。"),
        "glossary.term": "术语", "glossary.def": "含义",
        "glossary.note": ("同一个缩写在不同国家含义可能不同（DIN 是加拿大、ARTG 是澳大利亚）；"
                          "看代码时务必连同来源一起看。"),
        "glossary.t.inn": "INN",
        "glossary.d.inn": "国际非专利名（WHO）：活性成分的全球通用名，如对乙酰氨基酚、美托洛尔。",
        "glossary.t.ban": "BAN",
        "glossary.d.ban": "英国批准名：通常与 INN 相同，少数旧名不同（如 adrenaline 对应 epinephrine）。",
        "glossary.t.usan": "USAN",
        "glossary.d.usan": "美国采用名：多数同 INN，个别不同（如 albuterol 对应 salbutamol）。",
        "glossary.t.atc": "ATC 码",
        "glossary.d.atc": ("ATC 解剖治疗化学分类（WHO），如 C07AB02：按器官系统、类别、成分分组，"
                           "便于跨市场找同类药。"),
        "glossary.t.mah": "MAH",
        "glossary.d.mah": "上市许可持有人：在某市场持有该产品许可的公司，不一定是生产工厂。",
        "glossary.t.din": "DIN",
        "glossary.d.din": "加拿大药品识别号；DIN-HM 用于顺势疗法产品。",
        "glossary.t.ndc": "NDC",
        "glossary.d.ndc": "美国国家药品代码（企业 + 产品 + 包装三段）。",
        "glossary.t.artg": "ARTG",
        "glossary.d.artg": "澳大利亚治疗用品登记号：标识在澳登记的治疗用品。",
        "glossary.t.fdc": "FDC",
        "glossary.d.fdc": "固定剂量复方：一个产品含两种或以上活性成分（如二甲双胍 + 格列本脲）。",
        "glossary.t.lasa": "LASA / tall-man",
        "glossary.d.lasa": "形似/音似药名。FDA 的 tall-man 大小写写法和易混淆药名表用于减少拿错药。",
        "glossary.t.otc": "OTC",
        "glossary.d.otc": "非处方药：在该市场无需处方；同一药在别国可能只作处方药。",
        "glossary.t.rx": "Rx",
        "glossary.d.rx": "该市场的处方药。",
        "glossary.t.strength": "规格/强度",
        "glossary.d.strength": "每单位活性成分含量（如每片 500 mg）；不同国家规格和释放剂型可能不同。",
    },
    "zh-Hant": {
        "glossary.title": "術語表",
        "glossary.intro": ("包裝、監管紀錄和本站裡常見代碼/術語的簡短解釋。只幫助讀代碼，不是醫療建議。"),
        "glossary.term": "術語", "glossary.def": "含義",
        "glossary.note": ("同一個縮寫在不同國家含義可能不同（DIN 是加拿大、ARTG 是澳大利亞）；"
                          "看代碼時務必連同來源一起看。"),
        "glossary.t.inn": "INN",
        "glossary.d.inn": "國際非專利名（WHO）：有效成分的全球通用名，如對乙醯氨基酚、美托洛爾。",
        "glossary.t.ban": "BAN",
        "glossary.d.ban": "英國批准名：通常與 INN 相同，少數舊名不同（如 adrenaline 對應 epinephrine）。",
        "glossary.t.usan": "USAN",
        "glossary.d.usan": "美國採用名：多數同 INN，個別不同（如 albuterol 對應 salbutamol）。",
        "glossary.t.atc": "ATC 碼",
        "glossary.d.atc": ("ATC 解剖治療化學分類（WHO），如 C07AB02：依器官系統、類別、成分分組，"
                           "便於跨市場找同類藥。"),
        "glossary.t.mah": "MAH",
        "glossary.d.mah": "上市許可持有人：在某市場持有該產品許可的公司，不一定是生產工廠。",
        "glossary.t.din": "DIN",
        "glossary.d.din": "加拿大藥品識別號；DIN-HM 用於順勢療法產品。",
        "glossary.t.ndc": "NDC",
        "glossary.d.ndc": "美國國家藥品代碼（企業 + 產品 + 包裝三段）。",
        "glossary.t.artg": "ARTG",
        "glossary.d.artg": "澳大利亞治療用品登記號：標識在澳登記的治療用品。",
        "glossary.t.fdc": "FDC",
        "glossary.d.fdc": "固定劑量複方：一個產品含兩種或以上有效成分（如二甲雙胍 + 格列本脲）。",
        "glossary.t.lasa": "LASA / tall-man",
        "glossary.d.lasa": "形似/音似藥名。FDA 的 tall-man 大小寫寫法和易混淆藥名表用於減少拿錯藥。",
        "glossary.t.otc": "OTC",
        "glossary.d.otc": "非處方藥：在該市場無需處方；同一藥在別國可能只作處方藥。",
        "glossary.t.rx": "Rx",
        "glossary.d.rx": "該市場的處方藥。",
        "glossary.t.strength": "規格/強度",
        "glossary.d.strength": "每單位有效成分含量（如每片 500 mg）；不同國家規格和釋放劑型可能不同。",
    },
}
# U1 防闪烁：首页 head 里在 body 解析前先打标记（localStorage flag → html.u1-off）。
U1_HEAD_JS = ("<script>try{if(localStorage.getItem('u1.dismiss.v1')==='1')"
              "document.documentElement.className+=' u1-off';}catch(e){}</script>")

# ── i18n P1：About / What's new / Confused / 404 的三语正文 ────────────────
# 用法：About 正文按块走 `data-i18n-html`（i18n.js 用 innerHTML 替换，块内可含链接/表格）；
# 动态数字用 @@PLACEHOLDER@@（main() 里替换成当前库的统计值，不写死数字）。
# 许可段落直接用 reports/license-audit.md §4 的三语并排版（同一段内 EN/中文/ES 并列，
# 是「许可原文三语并列」，不是漏翻）。
DOCS_LICENCE_URL = ("https://github.com/fuarnos/drug-brand-crossref/blob/main/"
                    "docs/%E8%AE%B8%E5%8F%AF%E6%B8%85%E5%8D%95.md")

ABOUT_I18N = {
    "en": {
        "about.title": "About",
        "about.lead": (
            '<p class="sub"><b>One job:</b> turn a brand name into the actual substance, and say '
            'how sure we are. The site is public, ad-free and non-commercial. Every answer is a '
            'candidate set, never a prescription.</p>'),
        "about.rules": (
            '<h2>Three rules</h2><ol>'
            '<li><b>A brand name is not a primary key.</b> Every query returns a set of '
            'candidates; identity is pinned by country × form × strength × active ingredient.</li>'
            '<li><b>Collisions are derived, not annotated.</b> When one name hangs off different '
            'ingredients, the site flags “same name, different drug” automatically.</li>'
            '<li><b>No dosing advice.</b> Identification and “not interchangeable” warnings only — '
            'no dose conversion, no substitution recommendations.</li></ol>'),
        "about.nick": (
            '<h2>Nicknames and old names</h2>'
            '<p>“Two frogs” (liǎng zhī qīngwā) is not a brand name and is never stored as one: it '
            'points to an ingredient, metformin. Nicknames are a separate, hand-maintained table — '
            'searchable, but deliberately kept out of the brand-name tables. When one matches, the '
            'page labels it (<i>internet nickname / older name</i>) and then lists that ingredient’s '
            'brands; it is never presented as a name printed on a pack. Every entry carries a '
            'source; “user-provided” is shown as <i>unverified</i> and is not promoted to '
            '<code>documented</code> until an independent source is attached. No source, no new '
            'entry.</p>'
            '<ul class="sub">'
            '<li>@@NICKNAMES@@ nicknames are curated by hand in <code>data/seed_nicknames.py</code> '
            'and rebuilt — not scraped.</li>'
            '<li>Nicknames never enter collision detection and never get a “same name” page: a '
            'nickname is not an identity, the ingredient is.</li></ul>'),
        "about.terms": (
            '<h2>Folk names and class terms</h2>'
            '<p>A separate table (<code>drug_term</code>, @@DRUGTERMS@@ entries) holds folk names '
            'and category terms for <b>legal medicines only</b>: water pill, blood thinner, '
            'sleeping pill (shuìqiányào), the pill, morning-after pill, statin. Unlike '
            '<code>nickname</code>, it may point to a class rather than one ingredient, so '
            '<code>substance_id</code> is nullable; <code>alias_all</code> unions both tables for '
            'search. <b>Drugs of abuse and recreational slang are explicitly out of scope</b> '
            '(street / recreational drug slang); such entries were removed from the database and are not '
            're-added.</p>'
            '<ul class="sub">'
            '<li><b>NIDA / DEA lists</b> are no longer used for recreational slang; only '
            'prescription-drug category terms that are legal medicines are kept, each with a '
            'source URL.</li>'
            '<li><b>MedlinePlus (NLM)</b> contributes common folk/category terms (US Government '
            'work); community sources (CN/GB/AU/ES) are labelled <i>community name</i> and stay '
            'searchable. FDA tall-man pairs: @@CONFUSABLE@@ official pairs. '
            '<a href="confused.html">See the list</a>.</li></ul>'),
        "about.sources": (
            '<h2>Sources and coverage</h2>'
            '<div class="tablewrap"><table><tr><th>Country / region</th><th>Products</th>'
            '<th>Data as of</th></tr>@@COV@@</table></div>'
            '<p class="sub"><b>Data as of</b> = the date the source itself published / took effect '
            '/ snapshotted, not our crawl date. <code>live</code> = a live directory with no '
            'single source date; <b>—</b> = annual lists only.</p>'
            '<p class="sub"><b>US</b>: openFDA NDC Directory (US Government public data). '
            '<b>UK</b>: NHSBSA dm+d, Open Government Licence v3.0 — '
            '<i>Contains public sector information licensed under the Open Government Licence '
            'v3.0.</i> <b>Spain</b>: AEMPS CIMA — re-use allowed with express attribution and the '
            'date of last update; not an open licence (see licences below). <b>Mexico</b>: '
            'COFEPRIS registration lists (no stated open licence; factual fields with links) plus '
            'strength back-fill from datos.gob.mx procurement/price datasets, CC BY 4.0. '
            '<b>Australia</b>: PBS Schedule API (copyright notice retained) + TGA CMI directory '
            '+ curated listed-OTC seeds — factual fields only, no full CMI/ARTG text. '
            '<b>Canada</b>: Health Canada DPD — non-commercial re-use with source acknowledgement. '
            '<b>China</b>: 国家医保局 医保药品分类与代码数据库 (2025-04-04 snapshot); no open '
            'redistribution licence was found, so only factual fields with links are stored.</p>'),
        "about.tw_source": (
            '<p class="sub"><b>Taiwan 台灣</b>: TFDA 「全部藥品許可證資料集」 (data.gov.tw '
            'dataset 9122) under <b>Open Government Data Licence v1.0 (OGDL v1.0)</b>; '
            'attribution required: 衛福部食藥署 TFDA. Data as of <b>2026-10-22</b> (weekly '
            'sync). Facts only (product name, ingredients, dosage form, manufacturer, licence '
            'number, status). <b>Strengths are parsed from product names, so confidence is '
            'limited.</b> Licence: <a href="https://data.gov.tw/license">data.gov.tw/license</a>.</p>'),
        "about.sg_source": (
            '<p class="sub"><b>Singapore 新加坡</b>: HSA <b>Listing of Registered Therapeutic '
            'Products</b> (data.gov.sg dataset d_767279312753558cbf19d48344577084) under the '
            '<b>Singapore Open Data Licence v1.0 (SODL)</b>; attribution and licence link '
            'required, no government endorsement implied. Data as of <b>2026-08-07</b> '
            '(updated every 6 months). <b>Being on the register does not mean the product is '
            'currently marketed.</b> Brand names stay in English and are never translated; only '
            'Chinese ingredient names (inn_zh) may be shown. Attribution: Contains information '
            'from Listing of Registered Therapeutic Products accessed on 2026-10-28 from Health '
            'Sciences Authority (HSA), and made available under the Singapore Open Data Licence '
            'v1.0 (<a href="https://data.gov.sg/open-data-licence">licence</a>).</p>'),
        "about.hk_source": (
            '<p class="sub"><b>Hong Kong 中国香港</b>: Drug Office, Department of Health — '
            '<b>Registered Pharmaceutical Products</b> list (data.gov.hk dataset '
            'hk-dh-dh_do-hk-dh-do-pharmaceutical-product) under <b>DATA.GOV.HK Terms and '
            'Conditions</b> (free reuse with attribution; no government endorsement implied). '
            'Data as of <b>2026-10-23</b>. <b>Name/ingredient layer only — no strength, dosage '
            'form or registration status; being on the register does not prove current supply.</b></p>'),
        "about.au_source": (
            '<p class="sub"><b>Australia</b>: TGA <b>ARTG Medicines 2026-10-28</b> (Australian '
            'Register of Therapeutic Goods; attribution TGA/ARTG). Data as of '
            '<b>2026-10-28</b>. The export has <b>no registration-status column</b>, so status is '
            'shown as unknown; <b>being on the register does not mean currently marketed</b>. '
            '3,911 products have no ingredient records and are shown at name level only.</p>'),
        "about.eu_source": (
            '<p class="sub"><b>EU regional layer</b>: <b>European Commission — Union Register of '
            'medicinal products</b> (CC BY 4.0; attribution European Commission / Union Register) '
            'plus <b>EMA Medicines</b> data for cross-checking (source: European Medicines Agency '
            '(EMA); no EMA logo, no implied endorsement). Central authorisations only (human '
            'medicines), data as of <b>2026-11-03</b>. <b>An EU authorisation is not a record of '
            'sale in any single country, and the register carries no strength, dosage form or pack '
            'size.</b> Products that map to no known ingredient are shown at name level only.</p>'),
        "about.samename": (
            '<h2>Why “same name, different drug” happens</h2>'
            '<p class="sub">The same trademark is held by different companies in different '
            'markets, and the formula can differ completely. Verified examples: US <b>Tylenol</b> '
            'is single-ingredient acetaminophen 500 mg, while China <b>泰诺</b> is a four-ingredient '
            'cold medicine and the single-ingredient product is <b>泰诺林</b>; US <b>Benadryl</b> '
            'is diphenhydramine, UK <b>Benadryl</b> is acrivastine; US <b>Gaviscon</b> is an '
            'aluminium/magnesium antacid, UK Gaviscon is an alginate raft.</p>'),
        "about.gaps": (
            '<h2>Known gaps</h2><ul class="sub">'
            '<li>China has 146,344 chemical-drug registrations, but ~9% resolve only to a '
            'China-only substance (no English INN yet), and China’s ATC is stored at level 4. '
            'Traditional Chinese medicines (TCM) are not loaded.</li>'
            '<li>Strength equivalence stops at level D1 (same salt form); salt–base conversion '
            '(D2) and bioavailability judgement (D3) are not implemented.</li>'
            '<li>Mexico has no strength column in the regulator’s lists; only 29% of products '
            'could be back-filled from public catalogues.</li>'
            '<li>Canada’s DPD has no pack size or price, and many OTC consumer packs were '
            'authorised before the DPD’s electronic era, so a shelf product can be missing.</li>'
            '<li><b>ATC coverage — two denominators:</b> @@ATC_ALL_PCT@@% of all substances '
            '(@@ATC_ALL@@ / @@ATC_ALL_N@@) and @@ATC_DRUG_PCT@@% of drug entities (inn_drug, '
            '@@ATC_DRUG@@ / @@ATC_DRUG_N@@). The gap is mostly non-drug entities (homeopathic, '
            'herbal, food, material), not missing data. ATC data comes from Wikidata P267 (CC0) '
            'and ChEMBL (CC BY-SA 4.0); WHOCC’s ATC/DDD index needs a licence and is not used.</li>'
            '</ul>'),
        "about.analytics": (
            '<h2>Analytics</h2><p class="sub">This site uses '
            '<a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a> '
            'for anonymous, cookie-free analytics. No personal data is stored and it is not used '
            'for advertising. We only see page views, referring sites, country/region, browser and '
            'screen size, plus on-site search terms and result clicks, to improve search quality. '
            'Search terms (including queries that returned no result) are sent only as aggregate '
            'event names — the normalized query text, never linked to an account, IP address or '
            'device identifier. Search events are emitted only when you submit (Enter, a sample '
            'chip or an autocomplete choice), never for intermediate typing, and carry only the '
            'query length and interface language. '
            'See the <a href="https://www.goatcounter.com/privacy" target="_blank" '
            'rel="noopener">GoatCounter privacy policy</a>.</p>'),
        "about.stats": (
            '<p class="sub">Stats: @@PRODUCTS@@ products · @@SUBSTANCES@@ substances · '
            '@@KEYS@@ name keys · @@ALIASES@@ aliases (@@NICKNAMES@@ hand-curated nicknames, '
            '@@DRUGTERMS@@ folk/class terms) · @@CONFUSABLE@@ FDA confused pairs · @@SEVERE@@ names '
            'flagged “same name, different drug”.</p>'),
    },
    "es": {
        "about.title": "Acerca de",
        "about.lead": (
            '<p class="sub"><b>Un solo trabajo:</b> convertir un nombre comercial en el principio '
            'activo real y decir con qué seguridad lo sabemos. El sitio es público, sin anuncios y '
            'sin ánimo de lucro. Toda respuesta es un conjunto de candidatos, nunca una receta.</p>'),
        "about.rules": (
            '<h2>Tres reglas</h2><ol>'
            '<li><b>Un nombre comercial no es clave primaria.</b> Cada consulta devuelve un '
            'conjunto de candidatos; la identidad se fija por país × forma × concentración × '
            'principio activo.</li>'
            '<li><b>Las colisiones se derivan, no se anotan.</b> Cuando un nombre corresponde a '
            'principios activos distintos, el sitio marca automáticamente «mismo nombre, otro '
            'medicamento».</li>'
            '<li><b>Sin consejo de dosificación.</b> Solo identificación y avisos de «no '
            'intercambiable»: sin conversión de dosis ni recomendaciones de sustitución.</li></ol>'),
        "about.nick": (
            '<h2>Apodos y nombres antiguos</h2>'
            '<p>«Dos ranas» (liǎng zhī qīngwā) no es un nombre comercial y nunca se guarda como tal: '
            'apunta a un principio activo, la metformina. Los apodos están en una tabla aparte '
            'mantenida a mano: se pueden buscar, pero se mantienen fuera de las tablas de nombres '
            'comerciales. '
            'Cuando uno coincide, la página lo etiqueta (<i>apodo de internet / nombre antiguo</i>) '
            'y enumera las marcas de ese principio; nunca se presenta como un nombre impreso en el '
            'envase. Cada entrada lleva fuente; «aportado por el usuario» se muestra como '
            '<i>sin verificar</i> y no pasa a <code>documented</code> hasta adjuntar una fuente '
            'independiente. Sin fuente no hay entrada nueva.</p>'
            '<ul class="sub">'
            '<li>@@NICKNAMES@@ apodos se mantienen a mano en '
            '<code>data/seed_nicknames.py</code> y se reconstruyen; no se rastrean.</li>'
            '<li>Los apodos no entran en la detección de colisiones ni generan página de «mismo '
            'nombre»: un apodo no es una identidad, el principio activo sí.</li></ul>'),
        "about.terms": (
            '<h2>Nombres populares y términos de clase</h2>'
            '<p>Una tabla aparte (<code>drug_term</code>, @@DRUGTERMS@@ entradas) recoge nombres '
            'populares y términos de categoría de <b>medicamentos legales únicamente</b>: water '
            'pill, blood thinner, pastilla para dormir, «la píldora», «la píldora del día '
            'después», estatina. A diferencia de <code>nickname</code>, puede apuntar a una clase '
            'y no a un principio, así que <code>substance_id</code> puede ser nulo; '
            '<code>alias_all</code> une ambas tablas para la búsqueda. <b>Las drogas de abuso y la '
            'jerga recreativa quedan explícitamente fuera</b> (jerga de la calle / recreativa); esas '
            'entradas se eliminaron de la base y no se vuelven a añadir.</p>'
            '<ul class="sub">'
            '<li>Las listas de <b>NIDA / DEA</b> ya no se usan para jerga recreativa; solo se '
            'conservan términos de categoría de medicamentos legales, cada uno con su URL de '
            'fuente.</li>'
            '<li><b>MedlinePlus (NLM)</b> aporta términos populares/de categoría (obra del '
            'Gobierno de EE. UU.); las fuentes comunitarias (CN/GB/AU/ES) se etiquetan '
            '<i>nombre de la comunidad</i> y siguen siendo buscables. Pares tall-man de la FDA: '
            '@@CONFUSABLE@@ pares oficiales. <a href="confused.html">Ver la lista</a>.</li></ul>'),
        "about.sources": (
            '<h2>Fuentes y cobertura</h2>'
            '<div class="tablewrap"><table><tr><th>País / región</th><th>Productos</th>'
            '<th>Datos hasta</th></tr>@@COV@@</table></div>'
            '<p class="sub"><b>Datos hasta</b> = la fecha en que la propia fuente publicó / entró '
            'en vigor / tomó la instantánea, no la fecha de nuestro rastreo. <code>live</code> = '
            'directorio en vivo sin fecha única; <b>—</b> = solo listas anuales.</p>'
            '<p class="sub"><b>EE. UU.</b>: openFDA NDC Directory (datos públicos del Gobierno de '
            'EE. UU.). <b>Reino Unido</b>: NHSBSA dm+d, Open Government Licence v3.0 — '
            '<i>Contains public sector information licensed under the Open Government Licence '
            'v3.0.</i> <b>España</b>: AEMPS CIMA — reutilización permitida citando expresamente '
            'la fuente y la fecha de última actualización; no es licencia abierta (ver licencias). '
            '<b>México</b>: listas de registro sanitario de COFEPRIS (sin licencia abierta '
            'declarada; solo campos fácticos con enlaces) y concentraciones completadas con '
            'conjuntos de datos de datos.gob.mx, CC BY 4.0. <b>Australia</b>: API PBS Schedule '
            '(aviso de copyright conservado) + directorio TGA CMI + semillas OTC verificadas a '
            'mano; solo campos fácticos, sin texto completo de CMI/ARTG. <b>Canadá</b>: Health '
            'Canada DPD — reutilización no comercial con mención de la fuente. <b>China</b>: base '
            'de datos de clasificación y códigos de medicamentos del NHSA (instantánea '
            '2025-04-04); no se encontró licencia abierta de redistribución, así que solo se '
            'guardan campos fácticos con enlaces.</p>'),
        "about.tw_source": (
            '<p class="sub"><b>Taiwán 台灣</b>: TFDA «全部藥品許可證資料集» (data.gov.tw, '
            'conjunto 9122) bajo la <b>Licencia de Datos Gubernamentales Abiertos v1.0 '
            '(OGDL v1.0)</b>; atribución: 衛福部食藥署 TFDA. Datos hasta <b>2026-10-22</b> '
            '(sincronización semanal). Solo campos fácticos (nombre, principios, forma, '
            'fabricante, nº de licencia, estado). <b>Las concentraciones proceden del análisis '
            'de los nombres de producto, con confianza limitada.</b> Licencia: '
            '<a href="https://data.gov.tw/license">data.gov.tw/license</a>.</p>'),
        "about.sg_source": (
            '<p class="sub"><b>Singapur 新加坡</b>: HSA <b>Listing of Registered Therapeutic '
            'Products</b> (data.gov.sg, conjunto d_767279312753558cbf19d48344577084) bajo la '
            '<b>Licencia de Datos Abiertos de Singapur v1.0 (SODL)</b>; se exige atribución y '
            'enlace a la licencia; no implica respaldo gubernamental. Datos hasta '
            '<b>2026-08-07</b> (actualización cada 6 meses). <b>Estar en el registro no significa '
            'que el producto esté actualmente comercializado.</b> Los nombres comerciales se '
            'conservan en inglés y no se traducen; solo los nombres chinos de principios activos '
            '(inn_zh) pueden mostrarse. Atribución: Contains information from Listing of '
            'Registered Therapeutic Products accessed on 2026-10-28 from Health Sciences '
            'Authority (HSA), and made available under the Singapore Open Data Licence v1.0 '
            '(<a href="https://data.gov.sg/open-data-licence">licencia</a>).</p>'),
        "about.hk_source": (
            '<p class="sub"><b>Hong Kong 中国香港</b>: Drug Office, Department of Health — '
            'lista de <b>Registered Pharmaceutical Products</b> (data.gov.hk, conjunto '
            'hk-dh-dh_do-hk-dh-do-pharmaceutical-product) bajo las <b>condiciones de uso de '
            'DATA.GOV.HK</b> (reutilización libre con atribución; sin respaldo gubernamental). '
            'Datos hasta <b>2026-10-23</b>. <b>Solo capa de nombre/ingrediente: sin '
            'concentración, forma farmacéutica ni estado de registro; estar en el registro no '
            'prueba que se comercialice actualmente.</b></p>'),
        "about.au_source": (
            '<p class="sub"><b>Australia</b>: TGA <b>ARTG Medicines 2026-10-28</b> (Australian '
            'Register of Therapeutic Goods; atribución TGA/ARTG). Datos hasta '
            '<b>2026-10-28</b>. La exportación <b>no incluye columna de estado de registro</b>, '
            'así que el estado se muestra como desconocido; <b>estar en el registro no significa '
            'que se comercialice actualmente</b>. 3,911 productos no tienen componentes '
            'registrados y se muestran solo a nivel de nombre.</p>'),
        "about.eu_source": (
            '<p class="sub"><b>Capa regional de la UE</b>: <b>Comisión Europea — Union Register '
            'of medicinal products</b> (CC BY 4.0; atribución Comisión Europea / Union Register) '
            'y datos de <b>EMA Medicines</b> para contraste (fuente: European Medicines Agency '
            '(EMA); sin logotipo ni respaldo implícito). Solo autorizaciones centralizadas '
            '(medicamentos humanos), datos hasta <b>2026-11-03</b>. <b>Una autorización de la UE '
            'no es un registro de venta en un país concreto, y el registro no incluye dosis, '
            'forma farmacéutica ni tamaño de envase.</b> Los productos sin ingrediente identificado '
            'se muestran solo a nivel de nombre.</p>'),
        "about.samename": (
            '<h2>Por qué ocurre «mismo nombre, otro medicamento»</h2>'
            '<p class="sub">La misma marca pertenece a empresas distintas en cada mercado y la '
            'fórmula puede ser totalmente diferente. Ejemplos verificados: <b>Tylenol</b> en EE. UU. '
            'es paracetamol de un solo principio 500 mg, mientras que <b>泰诺</b> en China es un '
            'antigripal de cuatro principios y el producto de un solo principio es <b>泰诺林</b>; '
            '<b>Benadryl</b> en EE. UU. es difenhidramina y en el Reino Unido <b>Benadryl</b> '
            'es acrivastina; '
            '<b>Gaviscon</b> en EE. UU. es un antiácido de aluminio/magnesio y en el Reino Unido '
            'es una barrera de alginato.</p>'),
        "about.gaps": (
            '<h2>Lagunas conocidas</h2><ul class="sub">'
            '<li>China tiene 146.344 registros de medicamentos químicos, pero ~9% solo resuelven a '
            'una sustancia exclusiva de China (sin INN en inglés); su ATC se guarda en nivel 4. '
            'No se cargan los medicamentos chinos tradicionales (TCM).</li>'
            '<li>La equivalencia de concentración llega al nivel D1 (misma forma salina); la '
            'conversión sal–base (D2) y la biodisponibilidad (D3) no están implementadas.</li>'
            '<li>México no tiene columna de concentración en las listas del regulador; solo el 29% '
            'de los productos pudo completarse desde catálogos públicos.</li>'
            '<li>El DPD de Canadá no tiene tamaño de envase ni precio, y muchos envases OTC se '
            'autorizaron antes de la era electrónica del DPD, así que un producto de estantería '
            'puede faltar.</li>'
            '<li><b>Cobertura ATC — dos denominadores:</b> @@ATC_ALL_PCT@@% de todas las '
            'sustancias (@@ATC_ALL@@ / @@ATC_ALL_N@@) y @@ATC_DRUG_PCT@@% de las entidades '
            'farmacéuticas (inn_drug, @@ATC_DRUG@@ / @@ATC_DRUG_N@@). La diferencia son sobre '
            'todo entidades no farmacéuticas (homeopáticas, herbales, alimentos, materiales), no '
            'datos ausentes. Los ATC vienen de Wikidata P267 (CC0) y ChEMBL (CC BY-SA 4.0); el '
            'índice ATC/DDD de WHOCC requiere licencia y no se usa.</li></ul>'),
        "about.analytics": (
            '<h2>Estadísticas de visita</h2><p class="sub">Este sitio usa '
            '<a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a> '
            'para estadísticas anónimas sin cookies: no guarda datos personales y no se usa para '
            'publicidad. Solo se registran visitas, sitios de referencia, país/región, navegador y '
            'tamaño de pantalla, además de las búsquedas y clics en resultados, para mejorar la '
            'búsqueda. Los términos de búsqueda (incluidas las búsquedas sin resultado) se envían '
            'solo como nombres de evento agregados: el texto normalizado de la consulta, nunca '
            'vinculado a una cuenta, dirección IP o identificador de dispositivo. Los eventos de '
            'búsqueda se envían solo al enviar (Enter, un ejemplo o una sugerencia), nunca durante '
            'la escritura intermedia, y solo llevan la longitud de la consulta y el idioma de la '
            'interfaz. '
            'Ver la <a href="https://www.goatcounter.com/privacy" target="_blank" '
            'rel="noopener">política de privacidad de GoatCounter</a>.</p>'),
        "about.stats": (
            '<p class="sub">Cifras: @@PRODUCTS@@ productos · @@SUBSTANCES@@ sustancias · '
            '@@KEYS@@ claves de nombre · @@ALIASES@@ alias (@@NICKNAMES@@ apodos mantenidos a mano, '
            '@@DRUGTERMS@@ términos populares/de clase) · @@CONFUSABLE@@ pares confundibles de la '
            'FDA · @@SEVERE@@ nombres marcados «mismo nombre, otro medicamento».</p>'),
    },
    "zh": {
        "about.title": "关于本站",
        "about.lead": (
            '<p class="sub"><b>这里只有一件事：</b>把商品名定位到真正的成分，并说明它到底有多'
            '可信。本站公开、无广告、非商业；所有答案都是候选集，不是处方。</p>'),
        "about.rules": (
            '<h2>三条底线</h2><ol>'
            '<li><b>商品名不是主键。</b>每次查询返回候选集，唯一性由「国家 × 剂型 × 规格 × '
            '活性成分」锁定。</li>'
            '<li><b>碰撞自动推导，不手工标注。</b>一个名字挂到不同成分时，站点自动标出'
            '「同名不同药」。</li>'
            '<li><b>不给用药建议。</b>只做身份对应与「不可互换」提示——不做剂量换算，'
            '不给替代建议。</li></ol>'),
        "about.nick": (
            '<h2>俗称与旧名</h2>'
            '<p>「两只青蛙」不是商品名，也永远不当作商品名存储：它指向成分二甲双胍。'
            '俗称是单独的人工维护表，可检索，但刻意不进入商品名表。命中时先标注'
            '<i>「网络俗称 / 旧名」</i>，再列该成分的商品名，绝不把它说成包装上的名字。每条都写出处；'
            '「用户提供」只算线索，公开页标<i>「未证实」</i>，找到独立出处后才升级为 '
            '<code>documented</code>。没有来源就不新增。</p>'
            '<ul class="sub"><li>@@NICKNAMES@@ 条俗称在 <code>data/seed_nicknames.py</code> '
            '里人工维护并重建，不自动抓取。</li>'
            '<li>俗称不参与同名碰撞推导，也不生成同名页——昵称不是身份，成分才是。</li></ul>'),
        "about.terms": (
            '<h2>民间叫法与类别词</h2>'
            '<p>另有一张表 <code>drug_term</code>（@@DRUGTERMS@@ 条）收录<b>合法药品</b>的民间'
            '叫法与类别词：water pill（利尿剂）、blood thinner（抗凝药）、睡前药、the pill、'
            'morning-after pill、statin 等。与 <code>nickname</code> 不同，它可以指向类别而不是'
            '单一成分，因此 <code>substance_id</code> 可空；检索层读 <code>alias_all</code> '
            '统一视图。<b>毒品与娱乐性用药黑话明确不在收录范围</b>（街头/娱乐性用药黑话），'
            '此类条目已从库中移除，不再新增。</p>'
            '<ul class="sub"><li><b>NIDA / DEA 清单</b>不再用于娱乐性黑话，只保留合法药品的'
            '处方药类别词，并逐条带出处 URL。</li>'
            '<li><b>MedlinePlus（NLM）</b>提供常见民间/类别词（美国政府作品）；社区来源'
            '（CN/GB/AU/ES）标<i>「社区叫法」</i>并保留检索。FDA 官方 tall-man 药对：'
            '@@CONFUSABLE@@ 对，<a href="confused.html">见列表</a>。</li></ul>'),
        "about.sources": (
            '<h2>数据来源与覆盖</h2>'
            '<div class="tablewrap"><table><tr><th>国家/地区</th><th>已收录产品</th>'
            '<th>数据截止</th></tr>@@COV@@</table></div>'
            '<p class="sub"><b>数据截止</b> = 数据源自己发布 / 生效 / 快照的日期，不是我们的抓取'
            '日期。<code>live</code> = 实时目录，源头没有单独日期；<b>—</b> = 只有年度清单。</p>'
            '<p class="sub"><b>美国</b>：openFDA NDC Directory（美国政府公开数据）。'
            '<b>英国</b>：NHSBSA dm+d，Open Government Licence v3.0——'
            '<i>Contains public sector information licensed under the Open Government Licence '
            'v3.0.</i> <b>西班牙</b>：AEMPS CIMA——引用须注明来源与文件最后更新日期，非开放许可'
            '（见下方许可段）。<b>墨西哥</b>：COFEPRIS 注册清单（未标注开放许可，只存事实字段并'
            '链回原文）；规格回填来自 datos.gob.mx 的采购/价格数据集，CC BY 4.0。'
            '<b>澳洲</b>：PBS Schedule API（保留版权声明）+ TGA CMI 目录 + 人工核对的 listed '
            'OTC 种子，只存事实字段，不转载 CMI/ARTG 全文。<b>加拿大</b>：Health Canada DPD，'
            '允许非商业再使用并须注明来源。<b>中国</b>：国家医保局「医保药品分类与代码数据库」'
            '（2025-04-04 快照）；未找到开放的再发布许可，只存事实字段并链回原文。</p>'),
        "about.tw_source": (
            '<p class="sub"><b>中国台湾</b>：TFDA「全部藥品許可證資料集」（data.gov.tw 資料集 9122）'
            '依<b>政府資料開放授權條款第 1 版（OGDL v1.0）</b>釋出，須署名「衛福部食藥署 TFDA」；'
            '資料截止 <b>2026-10-22</b>（每週同步）。只存事實欄位（品名、成分、劑型、廠商、'
            '許可證號、狀態）。<b>規格由品名解析，置信度有限。</b>'
            '授權：<a href="https://data.gov.tw/license">data.gov.tw/license</a>。</p>'),
        "about.sg_source": (
            '<p class="sub"><b>新加坡</b>：HSA「Listing of Registered Therapeutic Products」'
            '（data.gov.sg 数据集 d_767279312753558cbf19d48344577084）依<b>新加坡开放数据许可'
            '第 1 版（SODL v1.0）</b>释出，须署名并链回许可页，不得暗示政府背书；数据截止 '
            '<b>2026-08-07</b>（每 6 个月更新）。<b>在册名单不代表在售。</b>商品名保留英文原文、'
            '不翻译；中文仅成分名（inn_zh）可显示。署名：Contains information from Listing of '
            'Registered Therapeutic Products accessed on 2026-10-28 from Health Sciences '
            'Authority (HSA), and made available under the Singapore Open Data Licence v1.0'
            '（<a href="https://data.gov.sg/open-data-licence">许可</a>）。</p>'),
        "about.hk_source": (
            '<p class="sub"><b>中国香港</b>：香港衞生署藥物辦公室「<b>註冊藥劑製品名單</b>」'
            '（data.gov.hk 数据集 hk-dh-dh_do-hk-dh-do-pharmaceutical-product），依 '
            '<b>DATA.GOV.HK 使用条款</b>可自由再使用、须署名（不暗示政府背书）；数据截止 '
            '<b>2026-10-23</b>。仅名称/持有人/注册号/活性成分层——<b>无规格、无剂型、无注册状态；'
            '在册不代表在售。</b></p>'),
        "about.au_source": (
            '<p class="sub"><b>澳大利亚</b>：TGA <b>ARTG Medicines 2026-10-28</b>'
            '（Australian Register of Therapeutic Goods；署名 TGA/ARTG）；数据截止 '
            '<b>2026-10-28</b>。导出<b>无注册状态列</b>，状态一律显示「未确认」；'
            '<b>在册不代表在售</b>。另有 3,911 个无成分记录的产品，仅按名称层展示。</p>'),
        "about.eu_source": (
            '<p class="sub"><b>欧盟区域层</b>：<b>欧盟委员会 — Union Register of medicinal '
            'products</b>（CC BY 4.0；署名 European Commission / Union Register），'
            '并用 <b>EMA Medicines</b> 数据交叉核对（来源：European Medicines Agency（EMA）；'
            '不使用 EMA logo、不暗示背书）。只收人用药品的集中审批产品，数据截止 '
            '<b>2026-11-03</b>。<b>欧盟授权不是某一国家的在售记录，登记也不含规格、剂型、包装。</b>'
            '映射不到已知成分的产品仅按名称层展示。</p>'),
        "about.samename": (
            '<h2>为什么会有「同名不同药」</h2>'
            '<p class="sub">同一个商标在不同市场属于不同公司，配方可能完全不同。已验证的例子：'
            '美国 <b>Tylenol</b> 是单一成分对乙酰氨基酚 500 mg，中国 <b>泰诺</b> 是四成分感冒药，'
            '单一成分产品叫 <b>泰诺林</b>；美国 <b>Benadryl</b> 是苯海拉明，英国 <b>Benadryl</b> '
            '是阿伐斯汀；美国 <b>Gaviscon</b> 是铝/镁抗酸剂，英国 Gaviscon 是海藻酸盐筏剂。</p>'),
        "about.gaps": (
            '<h2>已知缺口</h2><ul class="sub">'
            '<li>中国已入库 14.6 万条化学药注册，但约 9% 只能落到 CN 专属成分（暂无英文 INN），'
            'ATC 只到第 4 级；中成药未收录。</li>'
            '<li>剂量对应只做到同型对应（D1）；盐基折算（D2）与生物利用度判定（D3）未做。</li>'
            '<li>墨西哥官方清单没有浓度列，只有 29% 的产品能从公开目录回填。</li>'
            '<li>加拿大 DPD 没有包装数量/价格，很多 OTC 消费装在 DPD 电子化之前就获批，'
            '货架上有的产品可能查不到。</li>'
            '<li><b>ATC 覆盖——两个分母：</b>全部 substance 为 @@ATC_ALL_PCT@@%'
            '（@@ATC_ALL@@ / @@ATC_ALL_N@@），药物实体（inn_drug）为 @@ATC_DRUG_PCT@@%'
            '（@@ATC_DRUG@@ / @@ATC_DRUG_N@@）。缺口主要是非药物实体（顺势疗法、草药、食品、'
            '材料），不是没抓到数据。ATC 来自 Wikidata P267（CC0）与 ChEMBL（CC BY-SA 4.0）；'
            'WHOCC 的 ATC/DDD 索引需要授权，未使用。</li></ul>'),
        "about.analytics": (
            '<h2>访问统计</h2><p class="sub">本站使用 '
            '<a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a> '
            '做匿名访问统计：不使用 cookie、不记录个人数据、不用于广告；只统计页面浏览、来源'
            '网站、国家/地区、浏览器与屏幕尺寸，以及站内搜索词和结果点击，用于改进检索质量。'
            '搜索词（含无结果的查询）仅以聚合事件名发送——只含归一化查询文本，不与账号、IP 或'
            '设备标识关联。搜索事件只在提交时发送（回车、示例词或自动完成选项），输入过程中的'
            '中间态不会发送；仅附带查询长度与界面语言。'
            '详见 <a href="https://www.goatcounter.com/privacy" target="_blank" '
            'rel="noopener">GoatCounter 隐私政策</a>。</p>'),
        "about.stats": (
            '<p class="sub">统计：@@PRODUCTS@@ 个产品 · @@SUBSTANCES@@ 个成分 · '
            '@@KEYS@@ 个检索名 · @@ALIASES@@ 条别名（其中 @@NICKNAMES@@ 条人工俗称、'
            '@@DRUGTERMS@@ 条民间/类别词）· @@CONFUSABLE@@ 对 FDA 易混淆药对 · '
            '@@SEVERE@@ 个名字被标「同名不同药」。</p>'),
    },
}

# What's new / Confused / 404 的三语文案（同样走 data-i18n / data-i18n-html）。
PAGE_I18N = {
    "en": {
        "whatsnew.title": "What's new",
        "whatsnew.intro": ('Every release ships with a short summary. Old versions '
                           'are backfilled from git tags; the full history lives in '
                           f'<a href="{REPORT_REPO}/blob/main/CHANGELOG.md" target="_blank" '
                           'rel="noopener">CHANGELOG.md</a>.'),
        "whatsnew.lang_note": ('Release notes are machine-translated (AI); the Chinese original in '
                               'CHANGELOG.md is authoritative.'),
        "whatsnew.pending": ('Chinese original only — English/Spanish translation pending.'),
        "conf.source_note": (
            'Source: <a href="https://www.fda.gov/drugs/medication-errors-related-'
            'cder-regulated-drug-products/fda-name-differentiation-project" target="_blank" '
            'rel="noopener">FDA Name Differentiation Project</a> (content current as of '
            '2026-06-12; US Government work). Only the @@CONF_PAIRS@@ officially re-publishable '
            'pairs from the FDA list are included; the copyright ISMP/ECRI “List of Confused Drug '
            'Names” is not copied. Single names in the FDA list without a pair (hydromorphone, '
            'mitoxantrone) are not listed. A pair is a warning about names, not a statement that '
            'the drugs are equivalent.'),
        "notfound.title": "Page not found",
        "notfound.p1": ("This address has no page. It may be an old link, a typo, or a renamed "
                        "entry."),
        "notfound.p2": ("Go back to the home page and type a medicine name (brand, generic or "
                        "nickname)."),
        "notfound.search": "Search", "notfound.about": "About",
        "notfound.confused": "Confused names", "notfound.whatsnew": "What's new",
        "notfound.report": ('If an internal link is broken, tell us on '
                            f'<a href="{REPORT_REPO}/issues/new?labels=data-error&amp;'
                            'template=data-error.yml">GitHub</a>.'),
    },
    "es": {
        "whatsnew.title": "Novedades",
        "whatsnew.intro": ('Cada versión incluye un resumen breve. Las versiones '
                           'antiguas se rellenan desde las etiquetas de git; el historial completo '
                           f'está en <a href="{REPORT_REPO}/blob/main/CHANGELOG.md" '
                           'target="_blank" rel="noopener">CHANGELOG.md</a>.'),
        "whatsnew.lang_note": ('Las notas de versión están traducidas automáticamente (IA); el '
                               'original chino en CHANGELOG.md es la referencia.'),
        "whatsnew.pending": ('Solo original en chino — traducción al inglés/español pendiente.'),
        "conf.source_note": (
            'Fuente: <a href="https://www.fda.gov/drugs/medication-errors-related-'
            'cder-regulated-drug-products/fda-name-differentiation-project" target="_blank" '
            'rel="noopener">FDA Name Differentiation Project</a> (contenido actualizado a '
            '2026-06-12; obra del Gobierno de EE. UU.). Solo se incluyen los @@CONF_PAIRS@@ pares '
            'oficiales reutilizables de la lista de la FDA; la lista con copyright de ISMP/ECRI no '
            'se copia. Los nombres sueltos sin pareja (hidromorfona, mitoxantrona) no se listan. '
            'Un par es un aviso sobre nombres, no una afirmación de equivalencia.'),
        "notfound.title": "Página no encontrada",
        "notfound.p1": ("Esta dirección no tiene página. Puede ser un enlace antiguo, una errata o "
                        "una entrada renombrada."),
        "notfound.p2": ("Vuelve al inicio y escribe el nombre de un medicamento (comercial, "
                        "genérico o apodo)."),
        "notfound.search": "Buscar", "notfound.about": "Acerca de",
        "notfound.confused": "Nombres confundibles", "notfound.whatsnew": "Novedades",
        "notfound.report": ('Si un enlace interno está roto, avísanos en '
                            f'<a href="{REPORT_REPO}/issues/new?labels=data-error&amp;'
                            'template=data-error.yml">GitHub</a>.'),
    },
    "zh": {
        "whatsnew.title": "更新日志",
        "whatsnew.intro": ('每次上线都带一条更新摘要；旧版本已按 git tag 补到这里，'
                           f'完整历史见 <a href="{REPORT_REPO}/blob/main/CHANGELOG.md" '
                           'target="_blank" rel="noopener">CHANGELOG.md</a>。'),
        "whatsnew.lang_note": "英文/西语更新说明为 AI 机器翻译；中文原文（CHANGELOG.md）为准。",
        "whatsnew.pending": "中文原文；英/西语译文待补。",
        "conf.source_note": (
            '来源：<a href="https://www.fda.gov/drugs/medication-errors-related-'
            'cder-regulated-drug-products/fda-name-differentiation-project" target="_blank" '
            'rel="noopener">FDA Name Differentiation Project</a>（内容截至 2026-06-12，'
            '美国政府作品）。只收 FDA 官方可再发布的 @@CONF_PAIRS@@ 对；ISMP/ECRI 的'
            '《List of Confused Drug Names》有版权，未整表复制。FDA 表里的单名条目'
            '（hydromorphone、mitoxantrone）没有配对，未列入。药对只说明名字可能混淆，'
            '不表示两种药可以互换。'),
        "notfound.title": "页面不存在",
        "notfound.p1": "这个地址没有对应的页面。可能是链接过期、拼写有误，或页面已改名。",
        "notfound.p2": "回到首页输入一个药名（商品名、通用名、俗称都可以）。",
        "notfound.search": "检索", "notfound.about": "关于",
        "notfound.confused": "易混淆药名", "notfound.whatsnew": "更新日志",
        "notfound.report": ('如果是站内链接坏了，欢迎到 '
                            f'<a href="{REPORT_REPO}/issues/new?labels=data-error&amp;'
                            'template=data-error.yml">GitHub</a> 报一声。'),
    },
}

# ── v0.5.5：页面 title / meta description / OG 本地化（en/es/zh）────────────
# 根页面（about/confused/warn/whats-new/首页）用 data-i18n-title / data-i18n-meta
# 让 i18n.js 在语言切换时同步 <title>、description、og:title/description；
# /es/、/zh/ 静态副本在构建期直接写入对应语言。
META_I18N = {
    "en": {
        "meta.index.title": "Medicine Brand Cross-Reference — drug names across countries",
        "meta.index.desc": ("Search a brand name, generic name or nickname and see the active "
                            "ingredient, strength, and the same product's names in other "
                            "countries. Public, non-commercial reference."),
        "meta.about.title": "About · Medicine Brand Cross-Reference",
        "meta.about.desc": ("How this cross-reference works: sources and coverage, licences and "
                            "attribution, known gaps and editorial rules. Reference only, not "
                            "medical advice."),
        "meta.confused.title": "Easily confused drug names · Medicine Brand Cross-Reference",
        "meta.confused.desc": ("FDA tall-man look-alike / sound-alike pairs: a warning about names, "
                               "not a statement that the drugs are interchangeable."),
        "meta.warn.title": "Warnings: same name, different drug · Medicine Brand Cross-Reference",
        "meta.warn.desc": ("Published warnings on same-name / different-drug products and "
                           "combinations that are not interchangeable across countries, salt "
                           "forms or release mechanisms. Information only."),
        "meta.whatsnew.title": "What's new · Medicine Brand Cross-Reference",
        "meta.whatsnew.desc": ("Release notes for the drug brand cross-reference: fixes and "
                               "additions in each version."),
    },
    "es": {
        "meta.index.title": ("Referencia cruzada de marcas de medicamentos: nombres en distintos "
                             "países"),
        "meta.index.desc": ("Busca un nombre comercial, genérico o un apodo y consulta el principio "
                            "activo, la concentración y los nombres del mismo producto en otros "
                            "países. Referencia pública y sin ánimo de lucro."),
        "meta.about.title": "Acerca de · Medicine Brand Cross-Reference",
        "meta.about.desc": ("Cómo funciona esta referencia cruzada: fuentes y cobertura, licencias "
                            "y atribución, lagunas conocidas y reglas editoriales. Solo "
                            "información, no consejo médico."),
        "meta.confused.title": ("Nombres de medicamentos fáciles de confundir · Medicine Brand "
                                "Cross-Reference"),
        "meta.confused.desc": ("Pares tall-man de la FDA con nombres parecidos o que suenan igual; "
                               "un aviso sobre nombres, no una afirmación de intercambiabilidad."),
        "meta.warn.title": ("Alertas: mismo nombre, otro medicamento · Medicine Brand "
                            "Cross-Reference"),
        "meta.warn.desc": ("Avisos publicados sobre productos con el mismo nombre y distinto "
                           "principio activo, y combinaciones no intercambiables entre países, "
                           "formas salinas o mecanismos de liberación."),
        "meta.whatsnew.title": "Novedades · Medicine Brand Cross-Reference",
        "meta.whatsnew.desc": ("Notas de versión de la referencia cruzada: correcciones y novedades "
                               "de cada versión."),
    },
    "zh": {
        "meta.index.title": "药品商品名跨国定位 — 跨国家/语言的药品名对照",
        "meta.index.desc": ("输入商品名、通用名或俗称，查它的活性成分、剂量，以及其他国家的商品名。"
                            "公开、非商业的参考站。"),
        "meta.about.title": "关于 · 药品商品名跨国定位",
        "meta.about.desc": ("本站如何工作：数据来源与覆盖、许可与署名、已知缺口与编辑规则。"
                            "仅供参考，不构成用药建议。"),
        "meta.confused.title": "易混淆药名 · 药品商品名跨国定位",
        "meta.confused.desc": "FDA tall-man 形似/音似药对；这是对名字的警示，不代表两种药可以互换。",
        "meta.warn.title": "警示：同名不同药 / 不可互换 · 药品商品名跨国定位",
        "meta.warn.desc": ("已发布的警示：同名不同药，以及跨国、盐型或释放机制下不可互换的复方"
                           "产品。"),
        "meta.whatsnew.title": "更新日志 · 药品商品名跨国定位",
        "meta.whatsnew.desc": "药品商品名跨国定位的版本更新说明。",
    },
}


def _atc_coverage(db: sqlite3.Connection) -> dict:
    """ATC 双口径（动态）：全部 substance vs 药物实体（entity_type.csv 里 inn_drug）。

    药物实体分母 = entity_type.csv 中 entity_type=inn_drug、且当前库里存在的 substance。
    这样 About 的数字随库/CSV 自动更新，不在模板里写死。
    """
    import csv as _csv

    path = ROOT / "data" / "entity_type.csv"
    drug_ids: set[str] = set()
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in _csv.DictReader(fh):
                if (row.get("entity_type") or "").strip() == "inn_drug":
                    sid = (row.get("substance_id") or "").strip()
                    if sid:
                        drug_ids.add(sid)
    rows = db.execute("SELECT substance_id, atc FROM substance").fetchall()
    all_n = len(rows)
    all_atc = sum(1 for _sid, atc in rows if atc)
    drug = [(sid, atc) for sid, atc in rows if sid in drug_ids]
    drug_n = len(drug)
    drug_atc = sum(1 for _sid, atc in drug if atc)

    def pct(a: int, n: int) -> float:
        return round(a / n * 100, 1) if n else 0.0

    return {"all_atc": all_atc, "all_n": all_n, "all_pct": pct(all_atc, all_n),
            "drug_atc": drug_atc, "drug_n": drug_n, "drug_pct": pct(drug_atc, drug_n)}


def _i18n_placeholders(stats: dict, atc_cov: dict, coverage, source_cover) -> dict:
    """把 About/Confused 里 @@XXX@@ 占位符替换成当前库的统计值（构建期算，不写死）。"""
    by_country: dict[str, list] = {}
    for r in source_cover:
        by_country.setdefault(r["country"], []).append(r)
    cov = "".join(
        f"<tr><td>{esc(r['country'])}</td><td>{r['n_products']:,}</td>"
        f"<td>{_as_of_cell(by_country.get(r['country'], []))}</td></tr>" for r in coverage)
    return {
        "COV": cov,
        "PRODUCTS": f"{stats['products']:,}",
        "SUBSTANCES": f"{stats['substances']:,}",
        "KEYS": f"{stats['keys']:,}",
        "ALIASES": f"{stats['aliases']:,}",
        "NICKNAMES": f"{stats['nickname']:,}",
        "DRUGTERMS": f"{stats['drug_term']:,}",
        "CONFUSABLE": str(stats["confusable"]),
        "CONF_PAIRS": str(stats["confusable"]),
        "SEVERE": f"{stats['severe']:,}",
        "ATC_ALL_PCT": f"{atc_cov['all_pct']:.1f}",
        "ATC_ALL": f"{atc_cov['all_atc']:,}",
        "ATC_ALL_N": f"{atc_cov['all_n']:,}",
        "ATC_DRUG_PCT": f"{atc_cov['drug_pct']:.1f}",
        "ATC_DRUG": f"{atc_cov['drug_atc']:,}",
        "ATC_DRUG_N": f"{atc_cov['drug_n']:,}",
        "WARN_TOTAL": str(stats.get("warn_total", 0)),
        "WARN_HIGH": str(stats.get("warn_high", 0)),
        "WARN_MEDIUM": str(stats.get("warn_medium", 0)),
        "WARN_INFO": str(stats.get("warn_info", 0)),
    }


def _merge_static_i18n(values: dict) -> None:
    """把 ABOUT_I18N / PAGE_I18N / WARN_I18N 合并进 I18N，并替换 @@占位符@@。"""
    for lang in ("en", "es", "zh"):
        for source in (ABOUT_I18N[lang], PAGE_I18N[lang], WARN_I18N[lang], COMBO_I18N[lang],
                       MAKER_I18N[lang], META_I18N[lang], GLOSSARY_I18N[lang],
                       ATC_I18N[lang], BILINGUAL_I18N[lang], FILTER_I18N[lang],
                       LABEL_I18N[lang], UI_I18N[lang], SHELL_I18N[lang]):
            for key, text in source.items():
                merged = text
                for ph, val in values.items():
                    merged = merged.replace("@@" + ph + "@@", str(val))
                I18N[lang][key] = merged
    # v0.11.4（task-55）FR 站点准备：I18N["fr"] **键集与 en 完全相同**。
    # 高频 UI 用 FR_I18N 的机器翻译；其余键（含 ABOUT/PAGE 等合并进来的）暂用 en 占位。
    # fr 在 languages.json 里 enabled:false 时不会生成 /fr/ 页面，也不影响现有四语产物。
    # 开开关前：把 en==fr 的键补完（检查命令见 reports/2026-11-13-fr-site-prep.md）。
    fr_values = dict(FR_I18N)
    if "fr" in I18N_REQUIRED_LANGS:      # 仅开启后并入 FR 专用键（届时 en/es/zh 也要补）
        fr_values.update(FR_PREP_KEYS)
    I18N["fr"] = {k: (fr_values.get(k) or v) for k, v in I18N["en"].items()}
    if "fr" in I18N_REQUIRED_LANGS:
        for key, text in fr_values.items():
            if key not in I18N["fr"]:
                I18N["fr"][key] = text


def _install_zh_hant(values: dict) -> None:
    """装载 zh-Hant 字典：简体 zh 兜底 + data/i18n_zh_hant.json 覆盖，并替换 @@占位符@@。

    必须在 _merge_static_i18n 之后调用（此时 zh 已含全部静态字典与动态占位符）。
    """
    base = dict(I18N.get("zh") or I18N["en"])
    overrides = _load_zh_hant_dict()
    merged: dict[str, str] = {}
    fallback = 0
    from_extra: set[str] = set()
    for key, text in base.items():
        value = overrides.get(key)
        if value is None:
            fallback += 1
            value = text
        merged[key] = _subst_placeholders(value, values)
    for key, text in overrides.items():
        if key not in merged:
            merged[key] = _subst_placeholders(text, values)
    # v0.6.3：U1/U2/U3 新 key 的 zh-Hant 值直接来自 build.py（不依赖 JSON 是否已补齐），
    # 避免新 key 回落到简体中文。
    for extra in (LABEL_I18N["zh-Hant"], UI_I18N["zh-Hant"], GLOSSARY_I18N["zh-Hant"],
                  ATC_I18N["zh-Hant"], BILINGUAL_I18N["zh-Hant"], FILTER_I18N["zh-Hant"],
                  COVERAGE_I18N["zh-Hant"], NAME_LANG_I18N["zh-Hant"],
                  SHELL_I18N["zh-Hant"]):
        for key, text in extra.items():
            merged[key] = _subst_placeholders(text, values)
            from_extra.add(key)
    I18N["zh-Hant"] = merged
    # 记下哪些 key 只能拿简体充数（json 没覆盖、build.py 也没给繁体值）
    global ZH_HANT_FALLBACK_KEYS
    ZH_HANT_FALLBACK_KEYS = [k for k in merged
                             if k not in overrides and k not in from_extra]
    print(f"i18n zh-Hant: {len(merged)} keys "
          f"({len(overrides)} from json, {fallback} fallback zh)", flush=True)


def _assert_i18n_complete() -> None:
    """构建期硬拦四语不一致（用户规则 2026-11-10：翻译必须同步，缺译不许静默回落）。

    i18n.js 的回落顺序是「当前语言 → zh-Hant 先看简体 → 英文」，所以缺 key 不会报错，
    只会让西语/繁中用户静默看到英文或简体——那类滞后正是本函数要拦住的。
    与 deploy/i18n_check.py（CI 的 fast 模式也跑）同一口径：那边静态查字典常量，
    这边查合并后的运行时字典，双保险，谁也不能绕过。

    失败时打印缺哪些 key 并以 SystemExit 中止构建（不写任何页面）。
    确属无需翻译的 key 走 ZH_HANT_FALLBACK_OK / i18n_check.py 的白名单，别默默放行。
    """
    en = set(I18N["en"])
    problems: list[str] = []
    for lang in I18N_REQUIRED_LANGS:
        if lang not in I18N:
            problems.append(f"缺整份 {lang} 字典")
            continue
        missing = sorted(en - set(I18N[lang]))
        extra = sorted(set(I18N[lang]) - en)
        if missing:
            problems.append(f"{lang} 缺 {len(missing)} 个 key（会静默回落）："
                            f"{', '.join(missing[:12])}")
        if extra and lang != "en":
            problems.append(f"{lang} 多出 {len(extra)} 个 en 没有的 key（陈旧/拼错）："
                            f"{', '.join(extra[:12])}")
    bad_hant = sorted(set(ZH_HANT_FALLBACK_KEYS) - ZH_HANT_FALLBACK_OK)
    if bad_hant:
        problems.append(f"zh-Hant 有 {len(bad_hant)} 个 key 只能回落简体（繁体用户看到简体）："
                        f"{', '.join(bad_hant[:12])}")
    if problems:
        raise SystemExit("i18n 四语不一致，构建中止（补译文，或在 ZH_HANT_FALLBACK_OK "
                         "里登记已知遗留）：\n  " + "\n  ".join(problems))
    print(f"i18n 四语一致: {len(en)} keys × {len(I18N_REQUIRED_LANGS)} 语言"
          f"（zh-Hant 回落 {len(ZH_HANT_FALLBACK_OK)} 个已登记 key）", flush=True)


def _load_i18n_check():
    """懒加载 `deploy/i18n_check.py`（只读、无副作用），复用 CI 的同一份判定规则。

    构建期不重写一份「什么算缺译」的逻辑——否则两边口径会漂。文件不在时返回 None，
    由调用方降级（CI 仍会在提交时跑它）。
    """
    path = ROOT / "deploy" / "i18n_check.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("_i18n_check_build", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    # dataclass 装饰器要求模块已登记在 sys.modules（否则 cls.__module__ 取不到 __dict__）
    sys.modules.setdefault(spec.name or "_i18n_check_build", mod)
    spec.loader.exec_module(mod)
    return mod


def _assert_i18n_rules() -> None:
    """构建期复跑 CI 的两条硬规则（v0.10.2 用户规则：翻译必须同步，不许英语/西语滞后）。

    ① `release notes` 最新版本节四语齐全（只查「最新版」，历史积压是 WARN 不拦构建）；
    ② `LABEL_I18N` 的剂型/释放机制译名与 `data/label_translations.csv` 一致
       （术语表是单一真相源，build.py 手写的译名必须跟它对齐）。

    判定代码直接复用 `deploy/i18n_check.py`（`check_release_notes` / `check_label_terms`），
    与 CI 完全同口径；有 FAIL 就打印清单并中止构建，一个页面都不写。
    """
    mod = _load_i18n_check()
    if mod is None:
        print("i18n rules  : deploy/i18n_check.py 不在，跳过（CI 仍会跑）", flush=True)
        return
    findings = mod.Findings()
    try:
        sections = mod.parse_changelog()
    except Exception as exc:                       # noqa: BLE001  只报告，不中断
        sections = []
        print(f"i18n rules  : CHANGELOG 解析失败（{exc}），跳过 release notes 检查", flush=True)
    if sections:
        mod.check_release_notes(sections, findings)
    mod.check_label_terms({"LABEL_I18N": LABEL_I18N}, findings)
    hard = [f for f in findings.fail]
    if hard:
        lines = [f"{r['rule']}: {r['detail']}" for r in hard]
        raise SystemExit("i18n 规则不通过，构建中止（与 deploy/i18n_check.py 同口径）：\n  "
                         + "\n  ".join(lines))
    latest = sections[0]["version"] if sections else "?"
    warn_n = len(findings.warn)
    print(f"i18n rules  : 最新版 {latest} 四语齐全 · LABEL_I18N 术语一致"
          f"（WARN {warn_n} 条不拦构建）", flush=True)


# ── /warn 页 + 成分页警示：文案三语（页面 UI；警示正文来自 dose_warning 数据）──
WARN_I18N = {
    "en": {
        "nav.warn": "Warnings",
        "warn.title": "Warnings: same name, different drug",
        "warn.intro": ('<p class="sub">Published warnings about names that are easily confused, '
                       'or products that are <b>not interchangeable</b> — across countries, salt '
                       'forms or release mechanisms. This page only flags identity and '
                       'interchangeability; it contains <b>no dosing advice</b> and no substitution '
                       'recommendations.</p>'),
        "warn.count": ('<p class="sub">@@WARN_TOTAL@@ published warnings: @@WARN_HIGH@@ high '
                       'severity, @@WARN_MEDIUM@@ medium, @@WARN_INFO@@ info. Draft warnings are '
                       'not shown.</p>'),
        "warn.no_advice": ('Not medical advice. Check the actual pack and the ingredient, and ask '
                          'a pharmacist before changing products.'),
        "warn.group.high": "High severity — do not assume interchangeability",
        "warn.group.medium": "Medium severity — check before assuming equivalence",
        "warn.group.info": "Also worth knowing",
        "warn.sev.high": "High", "warn.sev.medium": "Medium", "warn.sev.info": "Info",
        "warn.source": "Regulatory source",
        "warn.related": "Related ingredient",
        "warn.countries": "Markets",
        "warn.reviewed": "Reviewed by",
        "warn.drug_summary": "Safety warnings for this ingredient",
        "warn.see_all": "See all warnings",
        "warn.empty": "No published warnings yet.",
        "warn.source_note": ('<b>Sources &amp; licences</b>: each warning links to the regulator’s '
                             'original document (DailyMed/FDA, EMA/MHRA, Health Canada DPD, AEMPS '
                             'CIMA, PBS/TGA, NMPA …). We publish factual excerpts only and keep the '
                             'source link; labels, SmPC/CMI full texts are not reproduced. See the '
                             'licence register in About for terms.'),
    },
    "es": {
        "nav.warn": "Alertas",
        "warn.title": "Alertas: mismo nombre, otro medicamento",
        "warn.intro": ('<p class="sub">Alertas publicadas sobre nombres que se confunden '
                       'fácilmente, o productos que <b>no son intercambiables</b> — entre países, '
                       'formas salinas o mecanismos de liberación. Esta página solo señala '
                       'identidad e intercambiabilidad; <b>no contiene consejos de dosificación</b> '
                       'ni recomendaciones de sustitución.</p>'),
        "warn.count": ('<p class="sub">@@WARN_TOTAL@@ alertas publicadas: @@WARN_HIGH@@ de '
                       'severidad alta, @@WARN_MEDIUM@@ media, @@WARN_INFO@@ informativas. Las '
                       'alertas en borrador no se muestran.</p>'),
        "warn.no_advice": ('No es consejo médico. Comprueba el envase y el principio activo, y '
                          'consulta a un farmacéutico antes de cambiar de producto.'),
        "warn.group.high": "Severidad alta — no supongas que son intercambiables",
        "warn.group.medium": "Severidad media — comprueba antes de asumir equivalencia",
        "warn.group.info": "También conviene saberlo",
        "warn.sev.high": "Alta", "warn.sev.medium": "Media", "warn.sev.info": "Info",
        "warn.source": "Fuente regulatoria",
        "warn.related": "Principio relacionado",
        "warn.countries": "Mercados",
        "warn.reviewed": "Revisado por",
        "warn.drug_summary": "Alertas de seguridad de este principio activo",
        "warn.see_all": "Ver todas las alertas",
        "warn.empty": "Todavía no hay alertas publicadas.",
        "warn.source_note": ('<b>Fuentes y licencias</b>: cada alerta enlaza al documento original '
                             'del regulador (DailyMed/FDA, EMA/MHRA, Health Canada DPD, AEMPS CIMA, '
                             'PBS/TGA, NMPA …). Solo publicamos extractos fácticos y conservamos el '
                             'enlace; no reproducimos prospectos ni textos completos SmPC/CMI. Las '
                             'condiciones están en el registro de licencias de «Acerca de».'),
    },
    "zh": {
        "nav.warn": "警示",
        "warn.title": "警示：同名不同药 / 不可互换",
        "warn.intro": ('<p class="sub">已发布的警示：名字容易混淆、或产品<b>不可互换</b>——'
                       '涉及不同国家、盐型或释放机制。本页只说明身份与不可互换性，'
                       '<b>不提供任何用药建议</b>，也不给替代方案。</p>'),
        "warn.count": ('<p class="sub">已发布 @@WARN_TOTAL@@ 条：高严重度 @@WARN_HIGH@@ 条、'
                       '中 @@WARN_MEDIUM@@ 条、提示 @@WARN_INFO@@ 条。草稿状态不展示。</p>'),
        "warn.no_advice": "这不是医疗建议。换药前请核对实际包装与成分，并咨询药师。",
        "warn.group.high": "高严重度——不要假定可以互换",
        "warn.group.medium": "中严重度——先核对再假定等效",
        "warn.group.info": "也值得了解",
        "warn.sev.high": "高", "warn.sev.medium": "中", "warn.sev.info": "提示",
        "warn.source": "监管来源",
        "warn.related": "相关成分",
        "warn.countries": "涉及市场",
        "warn.reviewed": "核验",
        "warn.drug_summary": "该成分的安全警示",
        "warn.see_all": "查看全部警示",
        "warn.empty": "暂无已发布警示。",
        "warn.source_note": ('<b>来源与许可</b>：每条警示都链接到监管机构原文（DailyMed/FDA、'
                             'EMA/MHRA、Health Canada DPD、AEMPS CIMA、PBS/TGA、NMPA 等）。'
                             '本站只发布事实摘录并保留来源链接，不转载说明书、SmPC/CMI 全文；'
                             '具体条款见「关于」里的许可清单。'),
    },
}

# ── 组合页（/combo/<成分集合slug>.html）三语文案 ─────────────────────
COMBO_I18N = {
    "en": {
        "combo.title": "Fixed-dose combination",
        "combo.intro": ('<p class="sub">This page lists brands whose active-ingredient set is '
                        'exactly the combination below. It is identity information only — a '
                        'fixed-dose combination is not the same product as its single '
                        'ingredients, and the brand names are not interchangeable across '
                        'markets.</p>'),
        "combo.ingredients": "Active ingredients",
        "combo.products": "Brands with this exact combination",
        "combo.no_advice": ('Not medical advice. Check the pack and the exact composition before '
                            'comparing products; ask a pharmacist if unsure.'),
        "combo.empty": "No brand names recorded for this combination yet.",
        "combo.capped": "Showing the first {cap} of {total} names.",
        "combo.source_note": ('<b>Source &amp; licence</b>: built from the same regulator data as '
                              'the ingredient pages (openFDA, dm+d, CIMA, COFEPRIS, PBS/TGA, '
                              'Health Canada DPD, NHSA). Facts only; see the '
                              '<a href="../about.html#licences">licence register</a>.'),
        "combo.see_warnings": "See warnings for these ingredients",
        "combo.no_page": "No separate brand page for this name",
        "combo.compact": "combination",
        # v0.6.0：跨市场同组合区块
        "combo.cross_title": "Same combination in other markets",
        "combo.cross_exact": ('These markets record products with the same active-ingredient '
                              'combination. Identity only — not a recommendation that products '
                              'are interchangeable.'),
        "combo.cross_products": "products",
        "combo.cross_record": "record",
        "combo.cross_overlap": ('The closest combination found in other markets is similar but '
                                'NOT identical — it is not interchangeable.'),
        "combo.cross_none": ('No product with this combination is recorded in the other covered '
                             'markets yet.'),
        "combo.cross_primary": ('Only the main ingredient is the same — this is NOT the same '
                                'fixed-dose combination.'),
        "combo.cross_primary_link": "View the main ingredient",
        "combo.cross_unmatched": ('Cross-market comparison is not available for this grouped '
                                  'name.'),
    },
    "es": {
        "combo.title": "Combinación en dosis fija",
        "combo.intro": ('<p class="sub">Esta página enumera las marcas cuyo conjunto de principios '
                        'activos es exactamente la combinación siguiente. Es solo información de '
                        'identidad: una combinación en dosis fija no es el mismo producto que sus '
                        'principios por separado, y los nombres comerciales no son intercambiables '
                        'entre mercados.</p>'),
        "combo.ingredients": "Principios activos",
        "combo.products": "Marcas con esta combinación exacta",
        "combo.no_advice": ('No es consejo médico. Comprueba el envase y la composición exacta '
                            'antes de comparar productos; consulta a un farmacéutico si dudas.'),
        "combo.empty": "Todavía no hay nombres comerciales para esta combinación.",
        "combo.capped": "Mostrando los primeros {cap} de {total} nombres.",
        "combo.source_note": ('<b>Fuente y licencia</b>: mismos datos regulatorios que las páginas '
                              'de principios activos (openFDA, dm+d, CIMA, COFEPRIS, PBS/TGA, '
                              'Health Canada DPD, NHSA). Solo hechos; ver el '
                              '<a href="../about.html#licences">registro de licencias</a>.'),
        "combo.see_warnings": "Ver alertas de estos principios",
        "combo.no_page": "Este nombre no tiene página de marca propia",
        "combo.compact": "combinación",
        # v0.6.0：跨市场同组合区块
        "combo.cross_title": "Misma combinación en otros mercados",
        "combo.cross_exact": ('Estos mercados registran productos con la misma combinación de '
                              'principios activos. Solo identidad — no es una recomendación de '
                              'intercambiabilidad.'),
        "combo.cross_products": "productos",
        "combo.cross_record": "registro",
        "combo.cross_overlap": ('La combinación más cercana en otros mercados es similar pero '
                                'NO idéntica: no son intercambiables.'),
        "combo.cross_none": ('Todavía no hay productos con esta combinación en los otros '
                             'mercados cubiertos.'),
        "combo.cross_primary": ('Solo coincide el principio principal — NO es la misma '
                                'combinación en dosis fija.'),
        "combo.cross_primary_link": "Ver el principio principal",
        "combo.cross_unmatched": ('La comparación entre mercados no está disponible para este '
                                  'nombre agrupado.'),
    },
    "zh": {
        "combo.title": "复方组合",
        "combo.intro": ('<p class="sub">本页列出「活性成分集合恰好等于下面这组」的商品名。'
                        '这里只做身份对应：复方产品≠各单方成分的简单相加，同名商品在不同'
                        '市场也不可互换。</p>'),
        "combo.ingredients": "活性成分",
        "combo.products": "属于该组合的商品名",
        "combo.no_advice": "这不是医疗建议。比较产品前请核对实际包装与完整成分；不确定时咨询药师。",
        "combo.empty": "该组合暂无已收录商品名。",
        "combo.capped": "仅显示前 {cap} / {total} 条。",
        "combo.source_note": ('<b>来源与许可</b>：与成分页使用同一批监管数据（openFDA、dm+d、'
                              'CIMA、COFEPRIS、PBS/TGA、Health Canada DPD、国家医保局）。'
                              '只做事实字段；见 <a href="../about.html#licences">许可清单</a>。'),
        "combo.see_warnings": "查看这些成分的警示",
        "combo.no_page": "这个名字没有独立品牌页",
        "combo.compact": "复方",
        # v0.6.0：跨市场同组合区块
        "combo.cross_title": "其他国家/地区的同组合",
        "combo.cross_exact": "这些市场收录了成分组合完全相同的产品。只做身份对应，不代表可以互换或替代。",
        "combo.cross_products": "个产品",
        "combo.cross_record": "记录",
        "combo.cross_overlap": "其他市场最接近的组合相近但并不完全相同——不可互换。",
        "combo.cross_none": "其他已收录市场暂无该成分组合的产品。",
        "combo.cross_primary": "仅主成分相同，这不是同一个复方组合。",
        "combo.cross_primary_link": "查看主成分",
        "combo.cross_unmatched": "这个合并后的名称暂无法做跨市场对照。",
    },
}

# ── v0.5.4：厂家页（/maker/<slug>.html）与结果行厂家链接 ─────────────
# 页数守卫：≥2 产品阈值会有 10,975 页；按 v0.5.3 基线（50,953 文件 / 279 MB）
# 预估会超过 400 MB，所以按任务约定降到 ≥5 产品（6,997 页），并在报告里记录。
MAKER_MIN_PRODUCTS = 1
MAKERS: dict[str, dict] = {}
# v0.9.0 task-6：单包装名字页体积守卫。全量 10 万页预计 dist >800MB，
# 默认只生成 CN/TW/ES/MX 子集（Lead 批准的降级口径）；设 SINGLE_NAME_ALL=1 可全量。
SINGLE_NAME_PAGE_MARKETS: set[str] | None = (
    None if os.environ.get("SINGLE_NAME_ALL") == "1" else {"CN", "TW", "ES", "MX"})
# v0.9.1 体积策略：只给「≥2 个产品 或 ≥2 个市场」的组合建页；
# 组合 slug → 是否建页。load_index 填充，build_combo_pages / 索引 cu 共用。
COMBO_PAGE_SLUGS: set[str] = set()
# v0.9.1 体积/链接策略：实际生成 drug 页的 substance_id，供 combo 页避免 404。
DRUG_PAGE_IDS: set[str] = set()
# v0.9.0：单产品厂家页 / 单包装名字页 noindex，且不进 sitemap（build_seo_files 跳过）。
NOINDEX_RELS: set[str] = set()


# v0.5.4：厂家名规范化必须与 etl/build_maker_candidates.py 的 norm_key 完全一致，
# 否则 CSV 里的 maker_key 匹配不到 DB 的 product.mah（会漏建厂家页 / 链接失效）。
PUNCT_RE = re.compile(r"[.,;:'\"()\[\]{}&/\\|]+")
DASH_RE = re.compile(r"[-\u2010-\u2015\uff0d]+")


def norm_maker(s: str) -> str:
    """厂家名规范化：NFKC → 空白折叠 → casefold → 去标点 → 破折号→'-'（与 data 任务一致）。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00a0", " ").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.casefold()
    s = PUNCT_RE.sub(" ", s)
    s = DASH_RE.sub("-", s)
    return re.sub(r"\s+", " ", s).strip()


def load_makers(threshold: int = MAKER_MIN_PRODUCTS) -> dict[str, dict]:
    """data/maker_candidates.csv → {norm_key: {name, slug, n, has}}。

    只把 n_products >= threshold 且非占位（Special Order 等）的厂家标记 has=True。
    """
    import csv as _csv

    path = ROOT / "data" / "maker_candidates.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in _csv.DictReader(fh):
            if (row.get("is_placeholder") or "") == "1":
                continue
            key = (row.get("maker_key") or "").strip()
            slug = (row.get("slug") or "").strip()
            if not key or not slug:
                continue
            try:
                n = int(row.get("n_products") or 0)
            except ValueError:
                n = 0
            out[key] = {"name": row.get("maker_name") or key, "slug": slug, "n": n,
                        "has": n >= threshold}
    return out


MAKER_I18N = {
    "en": {
        "maker.title": "Manufacturer / marketing-authorisation holder",
        "maker.intro": ('<p class="sub">{name} — {products} products across {markets} markets, '
                        '{brands} brand names. Products are grouped by country; brand names link '
                        'to their brand page and ingredients to the ingredient or combination '
                        'page. It is the marketing-authorisation holder recorded by the regulator, '
                        'not necessarily the factory.</p>'),
        "maker.stats": '<p class="sub">{products} products · {markets} markets · {brands} brand names</p>',
        "maker.by_country": "Products by country",
        "maker.brand": "Brand",
        "maker.ingredient": "Active ingredient(s)",
        "maker.source": "Source",
        "maker.capped": "Showing the first {shown} of {total} products (ordered by country).",
        "maker.no_page": "No separate brand page",
        "maker.no_page_count": "{n} more manufacturer(s) without a page",
        "maker.empty": "No products recorded for this manufacturer.",
        "maker.single_note": "No other products from this manufacturer recorded yet.",
        "maker.source_note": ('<b>Source &amp; licence</b>: product rows link to the regulator '
                              'record (openFDA, dm+d, CIMA, COFEPRIS, PBS/TGA, Health Canada DPD, '
                              'NHSA); facts only — see the '
                              '<a href="../about.html#licences">licence register</a>.'),
    },
    "es": {
        "maker.title": "Fabricante / titular de la autorización de comercialización",
        "maker.intro": ('<p class="sub">{name} — {products} productos en {markets} mercados, '
                        '{brands} nombres comerciales. Los productos se agrupan por país; los '
                        'nombres comerciales enlazan a su página de marca y los principios activos '
                        'a la página del principio o de la combinación. Es el titular registrado '
                        'por el regulador, no necesariamente la fábrica.</p>'),
        "maker.stats": '<p class="sub">{products} productos · {markets} mercados · {brands} marcas</p>',
        "maker.by_country": "Productos por país",
        "maker.brand": "Marca",
        "maker.ingredient": "Principio(s) activo(s)",
        "maker.source": "Fuente",
        "maker.capped": "Mostrando los primeros {shown} de {total} productos (orden por país).",
        "maker.no_page": "Sin página de marca propia",
        "maker.no_page_count": "{n} fabricante(s) más sin página",
        "maker.empty": "No hay productos registrados para este fabricante.",
        "maker.single_note": "Sin otros productos de este fabricante registrados todavía.",
        "maker.source_note": ('<b>Fuente y licencia</b>: cada fila enlaza al registro del '
                              'regulador (openFDA, dm+d, CIMA, COFEPRIS, PBS/TGA, Health Canada '
                              'DPD, NHSA); solo hechos — ver el '
                              '<a href="../about.html#licences">registro de licencias</a>.'),
    },
    "zh": {
        "maker.title": "厂家 / 上市许可持有人",
        "maker.intro": ('<p class="sub">{name} —— 共 {products} 个产品，覆盖 {markets} 个市场、'
                        '{brands} 个品牌名。产品按国家分组；品牌名链到品牌页，成分链到成分页/'
                        '组合页。这里记录的是监管数据里的「上市许可持有人」，不一定是生产工厂。</p>'),
        "maker.stats": '<p class="sub">{products} 个产品 · {markets} 个市场 · {brands} 个品牌名</p>',
        "maker.by_country": "各国产品",
        "maker.brand": "品牌",
        "maker.ingredient": "活性成分",
        "maker.source": "来源",
        "maker.capped": "仅显示前 {shown} / {total} 个产品（按国家排序）。",
        "maker.no_page": "没有独立品牌页",
        "maker.no_page_count": "另有 {n} 个厂家暂无页面",
        "maker.empty": "该厂家暂无已收录产品。",
        "maker.single_note": "目前未收录该厂家的其他产品。",
        "maker.source_note": ('<b>来源与许可</b>：产品行链到监管原始记录（openFDA、dm+d、CIMA、'
                              'COFEPRIS、PBS/TGA、Health Canada DPD、国家医保局）；只发布事实字段，'
                              '见 <a href="../about.html#licences">许可清单</a>。'),
    },
}


def _warn_badge(severity: str, lang: str) -> str:
    cls = {"high": "badge sev", "medium": "badge warn"}.get(severity, "tag")
    label = I18N[lang].get("warn.sev." + severity, severity)
    return f'<span class="{cls}">{esc(label)}</span>'


def _warn_meta_html(row: dict, lang: str, sub_names: dict[str, str],
                    prefix: str = "") -> str:
    """一条警示的来源/相关成分/市场（语言无关链接 + 本地化标签）。"""
    T = I18N[lang]
    parts = [f'<b>{esc(T["warn.source"])}</b>: '
             f'<a href="{esc(row["source_url"])}" target="_blank" rel="noopener">'
             f'{esc(row["source_url"].split("//")[-1].split("/")[0])}</a>']
    rel = []
    seen: set[str] = set()
    for key in ("substance_id", "related_substance_id"):
        sid = row.get(key)
        if sid and sid not in seen:
            seen.add(sid)
            name = sub_names.get(sid) or sid
            rel.append(f'<a href="{prefix}drug/{esc(sid)}.html">{esc(name)}</a>')
    if rel:
        parts.append(f'<b>{esc(T["warn.related"])}</b>: ' + " · ".join(rel))
    if row.get("country"):
        parts.append(f'<b>{esc(T["warn.countries"])}</b>: {esc(row["country"])}')
    if row.get("reviewed_by"):
        parts.append(f'<b>{esc(T["warn.reviewed"])}</b>: {esc(row["reviewed_by"])}')
    return '<p class="warn-meta">' + " · ".join(parts) + "</p>"


def _warn_lang_blocks(row: dict, sub_names: dict[str, str], *, prefix: str,
                      link: bool = False) -> str:
    """一条警示的 zh/en/es 三块正文（data-lang-block；数据缺 es 时回退英文并标注）。"""
    out = []
    for lang in ("en", "zh", "es"):
        title = row.get("title_" + lang) or row.get("title_en") or ""
        body = row.get("body_" + lang) or row.get("body_en") or ""
        fallback = "" if row.get("body_" + lang) else (
            ' <span class="meta">(EN)</span>' if lang != "en" else "")
        head = f'<h2>{_warn_badge(row["severity"], lang)} {esc(title)}{fallback}</h2>'
        if link:
            head = (f'<h2><a href="{prefix}warn.html#w-{esc(row["warning_id"])}">'
                    f'{esc(title)}{fallback}</a>{_warn_badge(row["severity"], lang)}</h3>')
        out.append(
            f'<div class="lang-block" data-lang-block="{lang}">'
            f'{head}<p class="warn-body">{esc(body)}</p>'
            f'{_warn_meta_html(row, lang, sub_names, prefix)}</div>')
    return "".join(out)


def _drug_warn_html(rows: list[dict]) -> str:
    """成分页顶部警示摘要（最多 3 条 + 链 /warn），按当前语言只显示一块。"""
    if not rows:
        return ""
    parts = ['<div class="notice warnbox drugwarn">']
    for lang in ("en", "zh", "es"):
        T = I18N[lang]
        items = "".join(
            f'<li><a href="../warn.html#w-{esc(r["warning_id"])}">{esc(r.get("title_" + lang) or r.get("title_en") or "")}</a></li>'
            for r in rows[:3])
        parts.append(
            f'<div class="lang-block" data-lang-block="{lang}">'
            f'<b>{esc(T["warn.drug_summary"])}</b><ul class="sub">{items}</ul>'
            f'<a href="../warn.html">{esc(T["warn.see_all"])}</a></div>')
    parts.append("</div>")
    return "".join(parts)


def build_warn(db: sqlite3.Connection) -> int:
    """/warn 页：只展示 dose_warning.status='published'，按 severity 分组（high→medium→info）。

    页面只做「同名不同药 / 不可互换」警示，不给用药建议；每条带监管来源链接。
    警示正文是数据行（zh/en/es 各一份），用 data-lang-block 在客户端按语言切换。
    """
    rows = [dict(r) for r in db.execute(
        """SELECT * FROM dose_warning WHERE status = 'published'
           ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    warning_id""")]
    sub_names: dict[str, str] = {}
    for sid, inn_zh, inn_en in db.execute(
            "SELECT substance_id, inn_zh, inn_en FROM substance"):
        sub_names[sid] = inn_en or inn_zh or sid  # v0.10.0 P1-4：英文界面不再混入中文成分名
    groups = {"high": [], "medium": [], "info": []}
    for row in rows:
        groups.setdefault(row["severity"], []).append(row)
    items_html = []
    for row in rows:
        items_html.append(
            f'<article class="warn-item" id="w-{esc(row["warning_id"])}" '
            f'data-sev="{esc(row["severity"])}">'
            + _warn_lang_blocks(row, sub_names, prefix="") + "</article>")
    # v0.6.7：客户端分页（10 条/页）。无 JS 时全部可见（优雅降级）；?page=N 刷新/分享保持。
    # 2026-11-12 v0.11.2（task-7）：分页脚本原来在 body 末尾同步跑，此时 window.T 还没来
    # （i18n 由 boot.js 在 window load 后才注入）→ T 回退成 identity，页面直接露出
    # 「warn.page_prev / warn.page_next」字面键。现在：① 文案在真正渲染时再取 T()（带英文兜底）；
    # ② DOMContentLoaded 先渲染一次；③ i18n 就绪后经 __DSH_APPLY_HOOKS 按当前语言重绘；
    # ④ 顺带把原来漏在 IIFE 外的 severity filter 收进闭包（它引用的 items/pager 属闭包，
    #    点击时会 ReferenceError，筛选后分页也不隐藏）。
    pager_js = """
(function(){
  var PAGE = 10;
  var list = document.getElementById('warnlist');
  var pager = document.getElementById('warnpager');
  if(!list || !pager) return;
  var items = Array.prototype.slice.call(list.querySelectorAll('article.warn-item'));
  var total = Math.ceil(items.length / PAGE);
  var fbox = document.querySelector('.warnfilters');
  var params = new URLSearchParams(location.search);
  var cur = parseInt(params.get('page') || '1', 10);
  if(!cur || cur < 1) cur = 1;
  if(cur > total) cur = total;
  if(params.get('page') && String(cur) !== params.get('page')){
    try{ params.set('page', String(cur)); history.replaceState(null, '', '?' + params.toString()); }catch(e){}
  }
  // 文案延迟到渲染时取，i18n 未就绪时用英文兜底（绝不把内部键名渲染到页面上）。
  function T(k, fallback){
    var v = (window.T || function(){ return ''; })(k);
    return (!v || v === k) ? fallback : v;
  }
  function pageHref(n){
    var p = new URLSearchParams(location.search);
    p.set('page', String(n));
    p.delete('lang');
    var q = p.toString();
    return '?' + q;
  }
  function link(n, label, cls, rel, disabled){
    if(disabled) return '<span class="' + cls + ' disabled" aria-disabled="true">' + label + '</span>';
    return '<a class="' + cls + '" href="' + pageHref(n) + '"' + (rel ? ' rel="' + rel + '"' : '') + '>' + label + '</a>';
  }
  function renderPager(){
    if(total <= 1){ pager.innerHTML = ''; return; }
    var html = '<span class="pg-status" aria-live="polite">' +
      T('warn.page_status', 'Page {n} of {total} · {count} warnings')
        .replace('{n}', cur).replace('{total}', total).replace('{count}', items.length) +
      '</span>';
    html += link(cur - 1, '‹ ' + T('warn.page_prev', 'Previous'), 'pg-prev', 'prev', cur <= 1);
    for(var n = 1; n <= total; n++){
      if(n === cur) html += '<span class="pg-num on" aria-current="page">' + n + '</span>';
      else html += link(n, String(n), 'pg-num', '', false);
    }
    html += link(cur + 1, T('warn.page_next', 'Next') + ' ›', 'pg-next', 'next', cur >= total);
    pager.innerHTML = html;
  }
  function showPage(){
    items.forEach(function(el, i){
      el.style.display = (i >= (cur - 1) * PAGE && i < cur * PAGE) ? '' : 'none';
    });
  }
  function init(){
    showPage();
    renderPager();
    pager.style.display = '';
  }
  if(fbox){
    fbox.addEventListener('click', function(ev){
      var b = ev.target && ev.target.closest ? ev.target.closest('[data-sev]') : null;
      if(!b) return;
      var sev = b.getAttribute('data-sev') || '';
      fbox.querySelectorAll('button').forEach(function(x){ x.classList.toggle('on', x === b); });
      items.forEach(function(el){
        var match = !sev || el.getAttribute('data-sev') === sev;
        el.style.display = match ? '' : 'none';
      });
      pager.style.display = sev ? 'none' : '';
    });
  }
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else { init(); }
  // i18n.js 由 boot.js 在 window load 后注入；它调用 apply() 时会跑这里注册的钩子，
  // 用当前语言重绘页码/上一页/下一页（切语言后也不会残留英文或键名）。
  (window.__DSH_APPLY_HOOKS = window.__DSH_APPLY_HOOKS || []).push(init);
})();
"""
    body = f"""<h1 data-i18n="warn.title">{esc(I18N["en"]["warn.title"])}</h1>
<div data-i18n-html="warn.intro">{I18N["en"]["warn.intro"]}</div>
<div class="notice" data-i18n="warn.no_advice">{esc(I18N["en"]["warn.no_advice"])}</div>
<div data-i18n-html="warn.count">{I18N["en"]["warn.count"]}</div>
<div class="warnfilters" role="group" aria-label="Severity filter">
<button type="button" data-sev="" class="on" data-i18n="warn.filter.all">All</button>
<button type="button" data-sev="high" data-i18n="warn.sev.high">High</button>
<button type="button" data-sev="medium" data-i18n="warn.sev.medium">Medium</button>
<button type="button" data-sev="info" data-i18n="warn.sev.info">Info</button></div>
<div id="warnlist">{''.join(items_html) if items_html else '<p class="empty" data-i18n="warn.empty">No published warnings yet.</p>'}</div>
<nav id="warnpager" class="warnpager" aria-label="Warning pages" data-i18n-aria="warn.pagination"></nav>
<div class="notice warnbox" data-i18n-html="warn.source_note">{I18N["en"]["warn.source_note"]}</div>
<script>{pager_js}</script>
"""
    html = page("Warnings", body, meta_key="warn", alternates=True,
                canonical_rel="warn.html", alt_rel="warn.html", nav_coverage=True)
    _write_with_copies("warn.html", html, "warn")
    return len(rows)


# 许可与署名：直接取自 reports/license-audit.md §4（三语并列的许可原文段落）。
LICENCE_HTML = f"""
<h2 id="licences">Data sources and licences 数据来源与许可 Fuentes y licencias</h2>
<p class="sub"><b>EN</b>: This site is a non-commercial public reference. We store only factual
fields (names, active ingredients, strengths, dosage forms, status) and link to the originals;
we do not republish full labels, CMI/SmPC texts or data dumps. Source-specific terms and
attribution are listed in the <a href="{DOCS_LICENCE_URL}">licence register</a>.
<br><b>中文</b>：本站为非商业公开参考站，只存事实字段（名称、成分、规格、剂型、状态）并链回原文，
不转载说明书 / CMI / SmPC 全文，也不提供原始数据批量下载。各来源许可与署名见
<a href="{DOCS_LICENCE_URL}">许可清单</a>。
<br><b>ES</b>: Este sitio es una referencia pública sin ánimo de lucro. Solo almacenamos campos
fácticos (nombres, principios activos, concentraciones, formas farmacéuticas, estado) y enlazamos
al original; no reproducimos prospectos, textos CMI/SmPC ni volcados de datos. Las condiciones y
atribuciones por fuente están en el <a href="{DOCS_LICENCE_URL}">registro de licencias</a>.</p>
<ul class="sub">
<li><b>EU 欧盟 / Unión Europea</b>: <b>European Commission — Union Register of medicinal
products</b> under <b>CC BY 4.0</b> (attribution: European Commission / Union Register), plus
<b>EMA Medicines</b> data for cross-checking (source: European Medicines Agency (EMA); no EMA
logo, no implied endorsement). Central authorisations (human medicines) only; the register
carries <b>no strength, dosage form or pack size</b>, and an EU authorisation is not a record of
sale in any single country. 中文：欧盟委员会 Union Register（CC BY 4.0，署名 European Commission /
Union Register）+ EMA 药品数据（署名 EMA，不用 logo、不暗示背书）；只收集中审批产品，不含规格 /
剂型 / 包装，「授权有效 ≠ 各国在售」。ES: Comisión Europea — Union Register (CC BY 4.0; atribución
Comisión Europea / Union Register) + datos de EMA (atribución EMA, sin logotipo); solo
autorizaciones centralizadas, sin dosis ni forma farmacéutica.
<a href="https://ec.europa.eu/health/documents/community-register/html/index_en.htm">Union Register</a> ·
<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a> ·
<a href="https://www.ema.europa.eu/en/about-us/about-website/legal-notice">EMA legal notice</a></li>
<li><b>China 中国 / China</b>: 医保药品分类与代码数据库由<b>国家医保局</b>公开；我们<b>未找到开放的再发布许可</b>，
只存事实字段并链回原文，不再发布原始数据表。EN: the NHSA catalogue is public but we found
<b>no open licence for redistribution</b>; factual fields only, with links, no bulk republication.
ES: el catálogo de la NHSA es público, pero <b>no hemos encontrado una licencia abierta de
redistribución</b>; solo campos fácticos y enlaces. 来源 Source: <a href="https://code.nhsa.gov.cn/yp/toPublicGoodsData.html">code.nhsa.gov.cn</a></li>
<li><b>Spain 西班牙 / España</b>: © <b>AEMPS</b> — CIMA (Centro de Información online de
Medicamentos). Reproduction of AEMPS website contents is authorised provided the source is
expressly cited and the <b>date of last update</b> is mentioned (Aviso legal). This is not an open
licence; we treat it as "conditional / pending confirmation". 中文：© AEMPS，引用须注明来源与文件最后更新日期，
非开放许可，按「待确认」处理。ES: © AEMPS — se autoriza la reproducción citando expresamente la
fuente y la fecha de última actualización (Aviso legal); no es una licencia abierta.
<a href="https://www.aemps.gob.es/aviso-legal/">Aviso legal</a> · <a href="https://cima.aemps.es/cima/publico/home.html">CIMA</a></li>
<li><b>Mexico 墨西哥 / México</b>: COFEPRIS registration lists published on gob.mx carry
<b>no stated open licence</b> (status: pending confirmation); we store factual fields only and
link to the source. Strengths were back-filled from <b>ISSSTE, PROFECO, HGMGG, INER, INPRFM and
SEMAR</b> procurement/price datasets published on <b>datos.gob.mx</b>, licensed <b>CC BY 4.0</b>
(attribution: Gobierno de México — datos.gob.mx, each dataset attributed to its publishing
institution). 中文：COFEPRIS 清单未标注开放许可，按「待确认」只存事实 + 链接；规格回填数据来自
datos.gob.mx 的 ISSSTE/PROFECO/HGMGG/INER/INPRFM/SEMAR 数据集（CC BY 4.0，署名发布机构）。
ES: las listas de COFEPRIS no declaran licencia abierta (pendiente de confirmación); solo campos
fácticos y enlaces. Los datos de concentración proceden de ISSSTE, PROFECO, HGMGG, INER, INPRFM y
SEMAR en datos.gob.mx, con licencia CC BY 4.0.
<a href="https://www.gob.mx/cofepris/documentos/registros-sanitarios-medicamentos">COFEPRIS</a> ·
<a href="https://datos.gob.mx/">datos.gob.mx</a> ·
<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a></li>
<li><b>Australia 澳洲 / Australia</b>: PBS Schedule data — <i>Copyright (c) 2024 Department of
Health, Commonwealth of Australia.</i> (copyright notice retained; content not modified).
TGA CMI repository and ARTG Public Summary entries — <b>© Commonwealth of Australia</b>; the TGA
copyright notice permits personal/internal non-commercial use of unaltered material and does not
permit re-transmission or redistribution without written permission, so we store <b>factual
fields only</b> (trade name, active ingredients, ARTG ID, status) with links and publish no
full-text CMI/ARTG content. 中文：PBS 保留版权声明且不修改内容；TGA CMI 与 ARTG 明细只取事实字段
（商品名/成分/ARTG ID/状态）并链回原文，不转载 CMI 全文、不再分发原始材料。
ES: datos PBS con aviso de copyright intacto y sin modificaciones; de TGA CMI y ARTG solo
almacenamos campos fácticos con enlaces, sin reproducir textos completos.
<a href="https://www.health.gov.au/using-our-websites/copyright">PBS copyright</a> ·
<a href="https://www.tga.gov.au/copyright">TGA copyright</a></li>
<li><b>Canada 加拿大 / Canadá</b>: Health Canada <b>Drug Product Database (DPD)</b> — re-use for
non-commercial purposes with source acknowledgement: <i>© His Majesty the King in Right of Canada,
as represented by the Minister of Health.</i> 中文：仅非商业再使用，须注明来源（加拿大卫生部）。
ES: reutilización no comercial con mención de la fuente. Terms: <a href="https://health-products.canada.ca/dpd-bdpp/">DPD</a></li>
<li><b>Taiwan 台灣 / Taiwán</b>: TFDA 「全部藥品許可證資料集」 (data.gov.tw dataset 9122) —
<b>Open Government Data Licence v1.0 (OGDL v1.0)</b>; attribution: 衛福部食藥署 TFDA
(<a href="https://data.gov.tw/license">data.gov.tw/license</a>); data as of <b>2026-10-22</b>
(weekly sync). 中文：依政府資料開放授權條款第1版釋出，須署名「衛福部食藥署 TFDA 全部藥品許可證
資料集」；只存事實欄位；規格由品名解析、置信度有限。ES: licencia OGDL v1.0 con atribución a la
TFDA; datos hasta 2026-10-22; concentraciones derivadas de los nombres de producto, con confianza
limitada.</li>
<li><b>Singapore 新加坡 / Singapur</b>: <b>Health Sciences Authority (HSA)</b> —
<b>Listing of Registered Therapeutic Products</b> (data.gov.sg dataset
d_767279312753558cbf19d48344577084) under the <b>Singapore Open Data Licence v1.0 (SODL)</b>;
attribution: Contains information from Listing of Registered Therapeutic Products accessed on
2026-10-28 from Health Sciences Authority (HSA), and made available under the Singapore Open Data
Licence v1.0 (<a href="https://data.gov.sg/open-data-licence">licence</a>); no government
endorsement implied. 中文：依新加坡開放資料授權條款第 1 版（SODL v1.0）釋出，須署名並鏈回授權頁；
資料截止 2026-08-07（每 6 個月更新）；在冊名單不代表在售；品牌名保留英文原文、不翻譯，中文僅
成分名可譯。ES: contiene información del registro de HSA bajo la SODL v1.0 con atribución;
datos hasta 2026-08-07; estar en el registro no implica comercialización.</li>
<li><b>WHO ATC/DDD Index</b>: ATC codes and hierarchy reference the <b>WHO Collaborating Centre
for Drug Statistics Methodology</b> ATC/DDD Index; the Index itself is copyrighted and is not
reproduced. Class/category names shown on ATC pages are editorial or AI-assisted translations,
not official WHO labels — the ATC code and WHO hierarchy are authoritative.
中文：ATC 码与层级引自 WHOCC ATC/DDD Index（版权归 WHOCC，不转载索引全文）；本站类别名是编辑/AI
辅助译名，不是 WHO 官方译名，以 ATC 码与 WHO 层级为准。
ES: los códigos y la jerarquía ATC remiten al ATC/DDD Index del WHOCC (con copyright, no se
reproduce); los nombres de clase son traducciones editoriales/asistidas por IA, no etiquetas
oficiales de la OMS.
<a href="https://atcddd.fhi.no/atc_ddd_index/">ATC/DDD Index</a></li>
<li><b>WHO INN / OMS</b>: Contains International Nonproprietary Names (INN) data from the
<b>World Health Organization</b>. WHO INN lists are licensed <b>CC BY-NC-SA 3.0 IGO</b>
(attribution + non-commercial + share-alike); this site is non-commercial, and any mapping table
derived from WHO INN lists is shared under the same licence. WHO does not endorse this site.
中文：含世界卫生组织 INN 数据；WHO INN 清单为 CC BY-NC-SA 3.0 IGO（署名 + 非商业 + 相同方式共享），
基于该清单的派生映射表以同许可共享；WHO 未背书本站。
ES: contiene datos de INN de la Organización Mundial de la Salud; las listas INN tienen licencia
CC BY-NC-SA 3.0 IGO (atribución + no comercial + compartir igual); los mapeos derivados se
comparten con la misma licencia. <a href="https://www.who.int/teams/health-product-and-policy-standards/inn">WHO INN</a> ·
<a href="https://creativecommons.org/licenses/by-nc-sa/3.0/igo/">CC BY-NC-SA 3.0 IGO</a></li>
<li><b>ChEMBL</b>: ATC mapping derived from <b>ChEMBL (EMBL-EBI)</b>, licensed <b>CC BY-SA 4.0</b>;
the derived ATC mapping table is available under the same licence. 中文：基于 ChEMBL 的 ATC 映射
须署名 EMBL-EBI 并按 CC BY-SA 4.0 相同方式共享。ES: mapeo ATC derivado de ChEMBL (EMBL-EBI),
licencia CC BY-SA 4.0; la tabla derivada se comparte con la misma licencia.
<a href="https://chembl.gitbook.io/chembl-interface-documentation/downloads">ChEMBL</a> ·
<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a></li>
<li><b>Other sources 其他来源</b>: openFDA (public domain / CC0), FDA tall-man list (US Government
work), NIDA (US Government work), DEA (Public Domain Mark 1.0), MedlinePlus/NLM (US Government
work), NHSBSA dm+d (Open Government Licence v3.0 — <i>Contains public sector information licensed
under the Open Government Licence v3.0.</i>), Wikidata P267 (CC0 1.0). ISMP/ECRI LASA lists and
WHOCC ATC/DDD index are copyrighted and are <b>not</b> reproduced. 中文：其余来源见许可清单；
ISMP/ECRI 与 WHOCC ATC/DDD 有版权，未使用。ES: el resto de fuentes figura en el registro de
licencias; las listas ISMP/ECRI y el índice WHOCC ATC/DDD no se reproducen.</li>
</ul>
<p class="sub"><b>Non-commercial notice 非商业声明</b>: this site is public, ad-free and offers no
paid data service; if that changes, the NC/conditional sources above must be re-evaluated.
本站公开、无广告、不提供付费数据服务；如未来商业化，上述标非商业/待确认的来源须重新评估。</p>
"""


CSS = """
:root{--bg:#fbfbf9;--fg:#1f2328;--muted:#4b5257;--line:#cfcabf;--line-soft:#e3e1da;
--card:#fff;--surface-2:#f6f5f0;--band:#f6f5f0;--accent:#0b6b53;--accent-weak:#f1f8f4;--warn:#b4471f;--warnbg:#fdf1ec;--sev:#a01b1b;--sevbg:#fdecec;
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;--s8:64px;
--fs-xs:12px;--fs-sm:14px;--fs-md:16px;--fs-lg:20px;--fs-xl:24px;
--lh-tight:1.3;--lh-heading:1.35;--lh-ui:1.5;--lh-body:1.6;
--r-sm:8px;--r-md:12px;--r-pill:999px;--prose:72ch;
/* v0.10.3 task-17：桌面内容带按视口比例取「中间 2/3」，而不是固定像素。
   ≥1280 用 66.67vw（1440→960 / 1920→1280 / 2560→1707，被 1680 封顶）；
   768–1279 保持 v0.10.2 的满宽手感（默认 100%；实测原值就是 100%，不是 100% - 48px，
   改成 -48px 会让 768 档与 v0.10.2 不逐像素一致，故不改）；<768 满宽 + 14px 内边距不变。 */
--band-w:100%;--wrap-pad:20px}
.wrap{width:var(--band-w);max-width:1680px;margin-inline:auto;padding:0 var(--wrap-pad)}
@media (min-width:1280px){:root{--band-w:66.67vw}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);min-height:100vh;
display:flex;flex-direction:column;
font:16px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
/* 2026-11-11 P1：`hidden` 属性的兜底。UA 样式表是 `[hidden]{display:none}`，任何作者样式
   里的 `display:grid/flex/block` 都会盖掉它 —— 成分页剂型筛选「点了没反应」就是这么来的
   （`.mkrow{display:grid}` 赢了 UA 规则）。这里给一条带 !important 的兜底，
   以后再加 display 组件也不会把 hidden 弄失效。 */
[hidden]{display:none!important}
header{border-bottom:1px solid var(--line);background:var(--bg)}
header .wrap{display:flex;align-items:center;gap:16px;height:60px;flex-wrap:nowrap}
.logo{font-weight:700;font-size:16px;color:var(--fg);white-space:nowrap}
.logo-zh{font-weight:400;font-size:14px;color:var(--muted);margin-left:8px;white-space:nowrap}
/* v0.6.5：logo 中文副标题只在简体中文界面显示（en/es/zh-Hant 隐藏，移动端仍隐藏） */
html:not([lang="zh"]) .logo-zh{display:none}
.langs{margin-left:6px;font-size:14px;display:flex;align-items:center;gap:6px;
  white-space:nowrap;flex-wrap:nowrap}
.langs a{color:var(--muted);padding:1px 5px;border-radius:8px;white-space:nowrap;
  display:inline-flex;align-items:center}
.langs a.on{background:var(--accent);color:#fff}
nav{display:flex;gap:14px;font-size:14px;flex-wrap:nowrap;white-space:nowrap;align-items:center}
nav a{white-space:nowrap}
/* v0.8.2 task-118：宽屏一行；768–1023 允许换行（禁止单字竖排）；<768 汉堡菜单 */
@media (max-width:1024px) and (min-width:768px){
  header .wrap{height:auto;flex-wrap:wrap;gap:6px 12px;padding-top:8px;padding-bottom:8px}
  nav{order:3;flex-basis:100%;flex-wrap:wrap;gap:8px 12px;font-size:14px}
  .langs{margin-left:auto;order:2;gap:4px}
}
.nav-toggle{display:none;align-items:center;justify-content:center;min-width:40px;min-height:40px;
  font-size:20px;background:#fff;color:var(--fg);border:1px solid var(--line);border-radius:8px;
  cursor:pointer}
@media (max-width:767px){
  header .wrap{height:auto;flex-wrap:wrap;gap:8px 12px}
  .nav-toggle{display:inline-flex;margin-left:auto}
  header nav{display:none;order:3;width:100%;flex-wrap:wrap;gap:6px 14px;padding:4px 0 2px;
    font-size:14px}
  header.nav-open nav{display:flex}
  header nav a{display:inline-flex;align-items:center;min-height:40px;white-space:nowrap}
  .langs{margin-left:0;gap:6px}
  .langs a{min-height:40px;padding:4px 6px}
  .logo{font-size:16px}
  .logo-zh{display:none}
}
main{padding:24px 0 64px;flex:1}
h1{font-size:var(--fs-xl);line-height:var(--lh-tight);margin:0 0 8px}
h2{font-size:var(--fs-lg);line-height:var(--lh-heading);margin:24px 0 12px}
.sub{color:var(--muted);font-size:var(--fs-sm);line-height:var(--lh-ui);margin:0 0 16px;max-width:var(--prose)}
/* 2026-11-11 UI：候选集单独一行 —— 16px 正常前景色（不是 muted 14px），
   因为「永远是候选集」是本站的口径而不是注脚。 */
.candidate-line{font-size:var(--fs-md);line-height:var(--lh-ui);color:var(--fg);
 margin:0 0 16px;max-width:var(--prose)}
/* 2026-11-12 v0.11.2（条目 8）：首页三步流程条（输名 → 确认产品 → 选目标市场）。
   只在「还没有查询」时出现；.has-q 后隐藏，结果页首屏不为它付高度。 */
.flow3{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;list-style:none;
 margin:0 0 12px;padding:0;font-size:var(--fs-md);line-height:1.35;color:var(--fg)}
.flow3 li{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.flow3 .n{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;
 border-radius:var(--r-pill);background:var(--accent-weak);color:var(--accent);font-size:13px;
 font-weight:700;line-height:1}
.flow3 li+li::before{content:"→";color:var(--muted);margin-right:2px}
html.has-q .flow3{display:none}
/* 2026-11-12 v0.11.2（条目 10）：来源市场（?src=）生效时的状态行，与目标市场分开显示。 */
.srcnote{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:8px 0 0;
 font-size:var(--fs-sm);color:var(--muted)}
.srcnote b{color:var(--fg);font-weight:600}
.srcnote button{padding:2px 0;border:0;background:none;color:var(--accent);font-size:var(--fs-sm);
 text-decoration:underline;min-height:auto}
.srcnote[hidden]{display:none!important}
#q{width:100%;padding:14px 16px;font-size:16px;border:1px solid var(--line);
border-radius:12px;background:#fff}
/* 2026-11-11 UI：搜索框内 44×44 可见提交按钮 + 右侧「按 / 聚焦」提示（13px 灰字）。
   按钮绝对定位于输入框右侧；提示只在输入框为空时显示（:placeholder-shown），
   有内容时自动隐藏，不会压住用户输入。输入框右侧留 56px 内边距给按钮。 */
.searchbar #q{padding-right:56px}
.sb-go{position:absolute;top:50%;right:6px;transform:translateY(-50%);width:44px;height:44px;
 padding:0;display:inline-flex;align-items:center;justify-content:center;
 border:1px solid var(--accent);border-radius:10px;background:var(--accent);color:#fff;
 font-size:18px;line-height:1;cursor:pointer}
.sb-go:hover{filter:brightness(1.08)}
.sb-hint{position:absolute;top:50%;right:58px;transform:translateY(-50%);font-size:13px;
 line-height:1;color:var(--muted);pointer-events:none;white-space:nowrap}
#q:not(:placeholder-shown) ~ .sb-hint{display:none}
@media (max-width:767px){
 /* 触屏没有 / 键，提示会白占一行宽度；按钮照留（= 移动端键盘的 search 键） */
 .sb-hint{display:none}
}
.row{display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap}
select,button{padding:8px 12px;border:1px solid var(--line);border-radius:8px;
background:#fff;font-size:14px}
button{cursor:pointer;background:var(--accent);color:#fff;border-color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin:10px 0}
.card h3{margin:0 0 4px;font-size:16px}
.card h2{margin:0 0 4px;font-size:16px}
.card .meta{color:var(--muted);font-size:14px}
.tag{display:inline-block;font-size:13px;padding:1px 7px;border-radius:999px;
border:1px solid var(--line);margin-left:6px;color:var(--muted)}
.tag.cn{color:#8a4b00;border-color:#e8c9a6}
.tag.gb{color:#1f4f8a;border-color:#b9cde6}
.tag.us{color:#0b6b53;border-color:#a9d3c5}
.tag.es{color:#8a2c1f;border-color:#e6bdb4}
.tag.au{color:#6b3b0b;border-color:#e0c9a6}
.tag.combo{color:#7a3b1f;border-color:#e6c3b3}
.tag.ca{color:#7a1420;border-color:#e7c3c7}
.tag.mx{color:#4b5b0b;border-color:#cdd6a6}
.tag.tw{color:#1f5c7a;border-color:#b7d5e3}
.tag.sg{color:#7a1f3d;border-color:#e3b7c5}
/* v0.8.1：双语对照开关/来源徽章/版本/原文 */
.bil-toggle{display:inline-flex;align-items:center;gap:4px;font-size:14px;
  color:var(--muted);margin:0 8px;cursor:pointer}
.bil-toggle input{width:14px;height:14px}
.tr-badge{display:inline-block;margin-left:6px;font-size:13px;padding:0 5px;
  border:1px solid var(--line);border-radius:8px;color:var(--muted);vertical-align:1px}
.tr-ver{font-size:14px;color:var(--muted);margin-left:4px}
.tr-orig{color:var(--muted);font-weight:400}
/* v0.7.x：ATC 类别 / 大类浏览 */
.atcgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));}
.catgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  gap:8px;margin:10px 0}
.atccard{display:block;padding:8px 10px;border:1px solid var(--line);border-radius:12px;
  background:#fff;color:var(--fg);font-size:14px}
.atccard:hover{border-color:var(--accent)}
.atccard code{font-weight:700;margin-right:4px}
.atclist{columns:2;column-gap:24px}
/* 2026-11-11 Batch 2：列表项是**内容**不是注脚 —— 外层 ul 带 .sub（14px）是历史写法，
   li 必须自己写回 16px，否则 first_screen_check 的「正文 ≥16px」会把 14px 的 ATC 子类
   列表当成正文最小值（atc/R06A.html 实测 14px 就是 `ul.sub.atclist > li`）。 */
.atclist li{break-inside:avoid;margin:2px 0;font-size:16px}
/* v0.10.2 task-3：ATC/大类页成分列表改自适应多列网格——宽屏（1440 / 2560）不再把内容
   挤在中间一列（旧 .wrap 920px + columns:2，2560 视口下列宽只有 268px）。
   2026-11-12 用户截图要求（task-6）：每个活性成分一个独立框 —— 1px 边框 + 圆角 + 10–12px
   内边距 + 与页面底色不同的面板底色（--card 白 vs --bg），不再连成一片。
   列数保持 3（≥1280）/ 2（768–1279）/ 1（<768）；卡片 align-self:start + break-inside:avoid
   防止跨列断裂。状态仍是纯文字（不恢复 v0.11.1 去掉的彩色底墙）。 */
.atcmembers{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
 column-gap:16px;row-gap:8px;columns:auto;padding-left:0;margin:6px 0 12px;max-width:none;
 list-style:none}
.atcmembers>li{display:grid;grid-template-rows:auto auto auto;align-content:start;
 align-items:stretch;align-self:stretch;row-gap:0;font-size:16px;line-height:1.3;
 break-inside:avoid;border:1px solid var(--line);border-radius:10px;background:var(--card);
 padding:10px 12px;margin:0;min-height:84px}
/* 2026-11-13 task-40：卡片固定 3 行（名+码 / 盐型 / 状态），每行 1 行、超长省略 + title；
   展开时 details 内容自然撑高（允许打破等高），不用 height/overflow 硬裁切。 */
.atc-nm{display:flex;flex-wrap:nowrap;align-items:baseline;gap:0 8px;min-width:0;overflow:hidden}
.atc-nm>a,.atc-nm>.brand-plain{min-width:0;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;display:block;flex:0 1 auto}
.atc-nm .atc-codes,.atc-nm .st-badge{flex:none}
/* 第 1 行：主名 + ATC 码；码用等宽数字 + 固定最小宽，1 码/2 码不会把下一行推歪 */
.atc-nm{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 8px;min-width:0}
.atc-codes{display:inline-flex;flex-wrap:wrap;gap:0 6px;min-width:5.4em;
 font-variant-numeric:tabular-nums}
.atc-codes code{font-size:13px;color:var(--muted);white-space:nowrap}
/* 第 3 行：状态 + 市场码。状态词只出现一次、市场码紧随其后用空格分隔，
   不同状态之间才用「·」（reports/2026-11-11-新UI-site-ui.md §B）。 */
.atc-strip{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 6px;margin-top:1px}
.atc-st-grp{display:inline-flex;flex-wrap:wrap;align-items:baseline;gap:0 5px;min-width:0}
.atc-st{font-size:13px;line-height:1.25;color:var(--fg);white-space:nowrap}
.atc-st.st-discontinued{color:var(--warn)}
.atc-st.st-withdrawn{color:var(--sev)}
.atc-st.st-unknown{color:var(--muted)}
.atc-mk{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums;
 letter-spacing:0;white-space:nowrap}
.atc-st-sep{color:var(--muted);font-size:13px;line-height:1.25}
@media (max-width:767px){ .atclist{columns:1} .atcmembers{display:block;padding-left:0}
 .atcmembers>li{font-size:16px;padding:10px;margin:0 0 8px} }
/* v0.8.5：ATC 类名 v2 来源小字 / 盐型附注 / 状态角标 / 查看更多 */
.atc-src{color:var(--muted);font-size:13px;margin-left:6px;white-space:nowrap}
.atccard .atc-src{display:block;margin:2px 0 0;white-space:normal}
.atc-src-line{margin:-8px 0 10px}
.atc-count{margin:-6px 0 10px}
.salt{color:var(--muted);font-size:14px;margin-left:6px}
/* v0.10.2 task-3：盐型独立成块级子行（左缩进对齐主名），文案「盐型：Name」。
   原来是内联 span，390px 下与主名/角标抢行，且每个盐型各带一次「暂无中文名」。
   2026-11-11 Batch 2：15px → 16px（盐型是内容，不是辅助文字；正文硬线 ≥16px）。 */
.salt-row{display:block;margin:1px 0 2px;color:var(--muted);font-size:16px;line-height:1.35}
.salt-row .salt-k{color:var(--muted)}
.salt-row .nm{color:var(--muted)}
.drug-name-src{min-height:18px;margin:2px 0 0;font-size:14px}
.drug-name-src [data-sub-src]:not(:empty){display:inline-block;padding:1px 7px;
  border:1px solid var(--line);border-radius:999px;background:#f6f5f0;color:var(--muted)}
.salt .nm{color:var(--muted)}
/* 2026-11-11 Batch 2：成分列表里的状态不再用「四色圆角底墙」。
   原来是 .st-badge 底色 + 0 竖向内边距（impeccable cramped-padding 在 atc/A.html 报了
   1630 条，全部指向这里）。现在状态词是纯文字（13px），只有「已停售 / 已撤市」保留警示色，
   「状态未知」用 muted；行内只剩「暂无中文名」这一种徽章，也去掉底色/描边（见下）。
   v0.10.2 的历史结论保留：不折 +N（触屏拿不到 title）、同一国家可以出现在多个状态里
   （3,599 个「成分×市场」格子本来就多状态）、字号 12px 是硬线。 */
.atcmembers .st-badge{margin:0 0 0 6px;padding:0;border:0;background:none;
  font-size:13px;line-height:1.25;color:var(--muted)}
.st-badge .mk{margin-left:3px;font-size:13px;letter-spacing:0;font-variant-numeric:tabular-nums}
.atc-mk-hint{margin:-4px 0 10px}
.atc-nolang-note{margin:-4px 0 10px}
/* 盐型子行不再逐个标「暂无中文名」：标记由 markAtcRowGaps() 每行只放一枚（链接外） */
.atcdetails{margin:8px 0 0}
.atcdetails summary{cursor:pointer;color:var(--accent);font-size:14px;margin:4px 0}
.atcdetails .atcmembers{margin-top:6px}
/* v0.9.6 task-145b：ATC4 页「按剂型看跨市场明细」（客户端懒加载 data/idx/atc4-forms.json） */
.atc4forms{margin:10px 0 0}
.atc4forms summary{cursor:pointer;color:var(--accent);font-size:14px;margin:4px 0}
.atc4forms table{font-size:14px}
.atc4forms th,.atc4forms td{padding:4px 6px;border-bottom:1px solid var(--line)}
.atc4forms thead th{white-space:nowrap;font-variant-numeric:tabular-nums}
.atc4forms tbody th{font-weight:600}
.atc4forms tbody td{text-align:right;font-variant-numeric:tabular-nums}
.atc4forms tbody td.z{color:var(--muted);text-align:center}
.atc4note{margin:4px 0 0;font-size:14px}
.cat-note .lang-block{margin:2px 0}
.catquick{margin:18px 0 6px}
.catquick h2{font-size:16px;margin:0 0 8px}
/* 2026-11-11（v0.11.1）：chip 是等宽栅格项（.catgrid 4 列），文字默认靠左，英文短标签
   （Antibiotics）右边会空一大片，看着像没对齐；中文标签长度接近列宽所以「显得居中」。
   这里只说 text-align:center —— 里面装的是四语 .lang-block span（非当前语言 display:none），
   改成 flex 会打乱多语块显隐，不要动。hover 也跟 .homeupd 一致：只变边框、不加下划线。 */
.catchip{display:inline-block;margin:0 8px 8px 0;padding:5px 10px;border:1px solid var(--line);
  border-radius:999px;background:var(--card);color:var(--fg);font-size:14px;text-align:center}
.catchip:hover{border-color:var(--accent);text-decoration:none}
/* v0.9.6 task-143：首页「最近更新」= 最近 3 个版本（版本号/日期是事实，不翻译） */
.homeupd{margin:18px 0 6px}
.homeupd h2{font-size:16px;margin:0 0 8px}
.homeupd .updlist{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px}
.homeupd .updlist a{display:inline-flex;align-items:center;gap:8px;padding:5px 10px;
  border:1px solid var(--line);border-radius:999px;background:#f6f5f0;color:var(--fg);
  font-size:14px;text-decoration:none}
.homeupd .updlist a:hover{border-color:var(--accent)}
.homeupd .upd-date{color:var(--muted);font-size:14px}
.homeupd .sub{margin:8px 0 0;font-size:14px}
.tag.warn{color:#8a4b12;border-color:#e6c9a2;background:#fff6e8}
/* v0.9.1 task-22：可访问性基础 */
.skip-link{position:absolute;left:-9999px;top:0;z-index:100;background:#0b6b53;color:#fff;
  padding:8px 12px;border-radius:0 0 8px 0;text-decoration:none}
.skip-link:focus{left:0}
:focus-visible{outline:3px solid #0b6b53;outline-offset:2px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
/* v0.9.1 task-29 P0/P1 */
.search-status{margin:8px 0 0;min-height:20px}
.match-name{display:inline-block;margin-left:6px;font-size:14px;color:var(--fg)}
.linkbtn,.detbtn,.rowreport,.mf-reset,.bil-toggle,.m-more summary{min-height:24px;
  display:inline-flex;align-items:center;justify-content:center}
#q,.mf-field select,.mf-field input[type=search]{border:2px solid #6f7c75}
header nav{flex-wrap:wrap;row-gap:6px}
.langs{margin-left:auto;flex-shrink:0}
@media (max-width:767px){
  .linkbtn,.detbtn,.rowreport,.mf-reset,.m-more summary{min-height:44px;min-width:44px}
}
.badge{display:inline-block;font-size:13px;padding:2px 8px;border-radius:8px;
margin-left:8px}
.badge.sev{background:var(--sevbg);color:var(--sev);border:1px solid #f0c4c4}
.badge.warn{background:var(--warnbg);color:var(--warn);border:1px solid #f0d3c4}
.badge.export{background:#eef4fb;color:#1f4f8a;border:1px solid #b9cde6}
.notice{background:var(--warnbg);border:1px solid #f0d3c4;border-radius:12px;
padding:12px 14px;font-size:14px;margin:14px 0}
.notice.nick{background:#f1f8f4;border-color:#cfe6da}
.notice.nick .nick-head{font-size:16px}
.notice.nick .nick-head b{font-size:16px}
.notice.nick .sub{margin:6px 0 0}
.notice.nick .sub a{white-space:nowrap}
.notice.nick .sub.src{font-size:14px;margin-top:4px}
.notice.warnbox{background:#fff8e8;border-color:#ecd9a8}
/* 2026-11-12 v0.11.2（条目 10）：同名不同药的家族说明可折叠 —— 390 上只留一行警示摘要，
   长注释放展开区；桌面端 summary 隐藏、默认展开（信息不丢）。 */
.famnotice{padding:8px 12px}
.famnotice>summary{list-style:none;cursor:pointer;display:flex;align-items:baseline;gap:8px}
.famnotice>summary::-webkit-details-marker{display:none}
.famnotice>summary::after{content:"＋";margin-left:auto;color:var(--accent);font-size:14px}
.famnotice[open]>summary::after{content:"－"}
.famnotice>.famnote{margin:6px 0 0}
@media (min-width:601px){
 .famnotice>summary{display:none}
 .famnotice>.famnote{margin:0}
}
table{width:100%;border-collapse:collapse;font-size:16px;line-height:1.5;margin-top:8px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:14px}
table.res{margin-top:12px;background:#fff;border:1px solid var(--line);
border-radius:12px;overflow:hidden;font-size:16px;line-height:1.5}
table.res th{background:#f6f5f0;font-size:14px;letter-spacing:.02em}
table.res td{vertical-align:top}
table.res tbody tr:hover{background:#fcfcfa}
.c-ing{font-weight:600;width:26%}
.c-dose{width:14%;white-space:nowrap;font-variant-numeric:tabular-nums}
.c-brand{width:38%}
.c-mah{width:22%;color:var(--muted);font-size:14px}
footer{border-top:1px solid var(--line);color:var(--muted);font-size:14px;
padding:18px 0 40px;background:#fff}
footer .wrap{display:flex;gap:16px;flex-wrap:wrap;align-items:baseline}
.foot-links{margin-left:auto;display:flex;gap:14px;white-space:nowrap}
.foot-links a{color:var(--accent)}
.report-line{margin-top:14px}
kbd{background:#eee;padding:1px 5px;border-radius:8px;font-size:14px}
.empty{color:var(--muted);padding:20px 0}
.release{border-top:1px solid var(--line);padding:18px 0 6px;margin-top:18px}
.release:first-of-type{border-top:0;margin-top:0;padding-top:4px}
.release h2{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin:0 0 8px}
.release .rel-date{font-size:13px;font-weight:400;color:var(--muted)}
.release table{font-size:14px}
.release ul{margin:6px 0 12px;padding-left:22px}
.release li{margin:4px 0}
.release-pending{color:var(--warn);font-size:14px;margin:6px 0 0}
/* ── UI P0：解析条 / 自动完成 / 分组折叠 / 加载更多 / 国家提示 ── */
.sel-label{color:var(--muted);font-size:14px;margin-right:2px}
.searchwrap{position:relative}
/* v0.10.2 M-4：#ac 的锚点从 .searchwrap 换成 .searchbar，方便把 #meta / 国家行
   一起放进 sticky 的 .searchwrap 里，而不让建议列表跟着往下挪两层。 */
.searchbar{position:relative}
/* 2026-11-12 v0.11.2（条目 26）：内容页常驻的简洁搜索栏（成分页 / 商品名页可续查）。
   顶层页静态渲染；长尾页（drug / name / combo / maker…）由 assets/boot.js 注入同一段，
   所以 121k 页不增加每页字节。首页不显示（大搜索框已承担）。 */
.hsearch-row{border-top:1px solid var(--line);background:transparent}
.hsearch-row .wrap{height:auto;display:block;padding-top:6px;padding-bottom:8px}
.hsearch{display:flex;gap:8px;align-items:center;max-width:600px}
.hsearch input{flex:1;min-width:0;padding:10px 12px;font-size:16px;border:1px solid var(--line);
 border-radius:10px;background:#fff}
.hsearch button{flex:none;min-width:44px;min-height:44px;padding:0 12px;border-radius:10px;
 font-size:16px;line-height:1}
#ac{position:absolute;left:0;right:0;top:calc(100% + 6px);z-index:30;display:none;
background:#fff;border:1px solid var(--line);border-radius:12px;
box-shadow:0 8px 24px rgba(31,35,40,.12);overflow:hidden;text-align:left}
#ac.open{display:block}
.ac-item{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
padding:9px 12px;cursor:pointer;font-size:14px;border-bottom:1px solid #f1efe9}
.ac-item:last-child{border-bottom:0}
.ac-item.on{background:#f1f8f4}
.ac-name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ac-meta{color:var(--muted);font-size:14px;white-space:nowrap;flex:none}
.parsebar{display:flex;flex-wrap:wrap;gap:6px 16px;background:#f4f6f4;
border:1px solid var(--line);border-radius:12px;padding:8px 12px;font-size:14px;margin:14px 0}
.parsebar b{color:var(--muted);font-weight:600;margin-right:4px}
.parsebar .pmatch{color:var(--accent)}
.grp-name{font-weight:600}
.grp-count{color:var(--muted);font-size:14px;font-weight:400;margin-left:6px}
.grp-tags{text-align:right}
.linkbtn{background:none;border:0;color:var(--accent);padding:2px 0;cursor:pointer;
font-size:14px;text-decoration:underline}
.fold-row td{padding:2px 8px 8px}
.loadmore{text-align:center;margin:10px 0 0}
.loadmore button{padding:8px 16px;font-size:14px}
.countrymiss .cm-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px}
.countrymiss .cm-actions a,.countrymiss .cm-actions button{font-size:14px}
/* v0.5.6：A1 详情 / A3 盐型释放上下文 / B6 行级报告 / B7 导出工具条 */
.ctxwrap{margin-left:4px}
.ctx{display:inline-block;font-size:14px;line-height:1.5;padding:1px 7px;border-radius:999px;
 border:1px solid var(--line);color:var(--muted);margin:1px 4px 1px 0;white-space:nowrap}
.ctx.warn{color:var(--warn);border-color:#f0d3c4;background:#fff6e8}
a.ctx:hover{text-decoration:none;border-color:var(--accent);color:var(--accent)}
.rowreport{display:inline-block;margin-left:6px;font-size:14px;color:var(--muted);text-decoration:none}
.rowreport:hover{color:var(--warn);text-decoration:none}
.detbtn{margin-left:6px;font-size:14px}
.restools{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:10px 0 0}
.restools .exportnote{color:var(--muted);font-size:14px}
/* v0.9.7 task-12 UI 批次 A-1：身份卡 / 结果分页 / 零结果三动作 / 粘性搜索 / 骨架 */
#identity:empty{display:none}
.idcard{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;
 background:#fff;padding:12px 14px;margin:14px 0 10px}
.idcard .idrow{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;margin:0 0 6px}
.idcard .idrow .idq{font-size:20px;font-weight:700}
.idcard .idrow .idarrow{color:var(--muted)}
.idcard .idrow .iding{font-size:16px;font-weight:600;color:var(--accent)}
.idbadge{background:var(--warnbg);color:var(--warn);border:1px solid #f0d3c4;border-radius:999px;
 padding:2px 10px;font-size:14px;white-space:nowrap}
.idfields{display:flex;flex-wrap:wrap;gap:3px 16px;font-size:14px;color:var(--muted);margin:0}
.idfields b{color:var(--fg);font-weight:600}
.idwarn{background:var(--warnbg);border:1px solid #f0d3c4;border-radius:12px;padding:9px 12px;
 font-size:14px;margin:9px 0 0}
.idacts{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.idacts a,.idacts button{min-height:40px;display:inline-flex;align-items:center;justify-content:center;
 padding:0 15px;border-radius:12px;border:1px solid var(--accent);background:var(--surface-2);color:var(--accent);
 font-size:14px;text-decoration:none;cursor:pointer;font-family:inherit}
.idacts .primary{background:var(--accent);color:#fff}
.idacts a:hover,.idacts button:hover{text-decoration:none;filter:brightness(.96)}
/* 2026-11-12 v0.11.2（条目 9）：身份卡标题写清「概括的是哪一条候选」——
   位置（第 1 条 / 共 N 条）+ 这一条自己的商品名（不是把整个品牌当答案）。
   390x844 下卡片折成紧凑头：只留标题 + 查询→成分一行，规格/市场/警示/动作进可展开区。 */
.idcard .idtitle{margin:0 0 6px;font-size:var(--fs-md);line-height:1.4;color:var(--muted)}
.idcard .idtitle b{color:var(--fg);font-size:var(--fs-md);font-weight:700}
.idcard .idtitle .idmake{color:var(--muted);font-weight:400}
.idmore{margin:0}
.idmore>summary{display:none}
.idmore>.idbody{margin:0}
@media (max-width:600px){
 .idmore>summary{display:flex;align-items:center;justify-content:space-between;gap:8px;
  min-height:44px;cursor:pointer;color:var(--accent);font-size:var(--fs-sm);list-style:none}
 .idmore>summary::-webkit-details-marker{display:none}
 .idmore>summary::after{content:"＋";font-size:16px;line-height:1}
 .idmore[open]>summary::after{content:"－"}
 .idmore[open]>.idbody{padding-top:8px;border-top:1px solid var(--line-soft);margin-top:4px}
}
.res-more{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;
 margin:10px 0 0}
.res-more .sub{margin:0;font-size:14px}
.res-more button{min-height:40px;padding:0 16px;border-radius:12px;border:1px solid var(--accent);
 background:#fff;color:var(--accent);font-size:14px;cursor:pointer;font-family:inherit}
.res-more button:hover{filter:brightness(.96)}
.res-samelist{margin:6px 0 10px;padding-left:20px}
.res-samelist li{margin:3px 0;font-size:14px}
table.res.rows td.c-det{text-align:right;white-space:nowrap}
table.res.rows .rowform{display:block;color:var(--muted);font-size:14px}
/* 2026-11-13 task-31（用户截图）：剂型在结果表「剂量」列里突出显示（只出现一次）。
   浅绿底 + accent 字，白底行上对比达标；inline-block 不额外占行高。 */
.form-tag{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:999px;
 background:var(--accent-weak);color:var(--accent);font-size:14px;font-weight:600;line-height:1.5;
 white-space:nowrap;vertical-align:1px}
.empty3{margin:12px 0 0}.empty3 .e3acts{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 0}
.empty3 .e3acts a,.empty3 .e3acts button{min-height:40px;display:inline-flex;align-items:center;
 padding:0 14px;border-radius:12px;border:1px solid var(--line);background:#fff;color:var(--fg);
 font-size:14px;text-decoration:none;cursor:pointer;font-family:inherit}
.empty3 .e3acts a:hover,.empty3 .e3acts button:hover{border-color:var(--accent);color:var(--accent)}
.res-skeleton .sk-row{height:36px;margin:8px 0;border-radius:8px;
 background:linear-gradient(90deg,#f1efe9 25%,#f8f6f1 37%,#f1efe9 63%);
 background-size:400% 100%;animation:skfade 1.2s ease-in-out infinite}
@keyframes skfade{0%{background-position:100% 50%}100%{background-position:0 50%}}
@media (prefers-reduced-motion:reduce){.res-skeleton .sk-row{animation:none}}
@media (max-width:767px){
  /* v0.10.2 M-4：sticky 区从「只有输入框」扩到「输入框 + 命中数 + 国家/地区」。
     手机滚到第 3 屏后仍能看到「共多少条」并直接换国家（原来要一路滚回顶部）。 */
  .has-q .searchwrap{position:sticky;top:0;z-index:20;background:var(--bg);padding:6px 0;
   border-bottom:1px solid var(--line)}
  .has-q .searchwrap #ac{top:calc(100% + 2px)}
  .has-q .searchwrap .search-status{margin:2px 0 0;min-height:0}
  /* 2026-11-11：国家/地区收进 details 后，sticky 区里那一行换成 44px summary（比原来
     「整行标签 + 下拉」矮，换国家的入口还在） */
  .has-q .searchwrap .ctry-details{margin-top:4px}
}
/* 2026-11-12 v0.11.2（条目 10）：结果区上方的重复说明在窄屏压缩 —— 手机首屏留给候选表，
   解析条 / 「国家/地区叫法」提示不各占一整行（警示文字已移进身份卡的展开区）。 */
@media (max-width:600px){
  .parsebar{padding:6px 10px;margin:8px 0;font-size:var(--fs-sm)}
  .u2bar{padding:8px 10px;margin:8px 0}
  .u2bar .u2head .sub{display:none}
  .u2chips{margin-top:6px}
  .idcard{padding:10px 12px;margin:10px 0 8px}
  .idcard .idrow .idq{font-size:18px}
}
table.det{margin:4px 0 8px;font-size:14px;background:#f6f5f0;border:1px solid var(--line);
 border-radius:8px;overflow:hidden}
table.det th{background:#f6f5f0;font-size:14px}
table.det td{padding:5px 8px;vertical-align:top}
tr.detrow>td.detcell{padding:4px 8px 10px;background:#f6f5f0}
tr.detrow table.det{margin:0}
/* v0.6.3 U1：首屏 3 步引导（v0.8.2 task-115：移到搜索框正下方、国家行之前；层级增强） */
.u1guide{border:1px solid var(--line);border-radius:12px;background:#fff;
 padding:16px 18px;margin:12px 0 2px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.u1head{display:flex;align-items:baseline;gap:10px}
.u1head h2{margin:0;font-size:20px;font-weight:700;letter-spacing:.01em}
.u1close{margin-left:auto;background:none;border:0;color:var(--muted);font-size:20px;
 line-height:1;padding:6px 8px;min-width:36px;min-height:36px;cursor:pointer}
.u1close:hover{color:var(--fg)}
.u1steps{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:12px 0 0;
 padding:0;list-style:none}
.u1step{border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:#f6f5f0}
.u1step b{display:block;font-size:16px;margin:0 0 3px}
.u1step .sub{margin:4px 0 0;font-size:14px}
.u1try{margin-top:6px;font-size:14px;color:var(--muted)}
.u1try button{padding:3px 8px;font-size:14px;margin:2px 4px 2px 0;border-radius:8px}
html.u1-off #u1guide{display:none!important}
/* v0.8.2 task-116：搜索后收起「按大类浏览」 */
.catquick.cat-hidden{display:none!important}
/* v0.6.3 U2：结果顶部各国叫法横排（单成分唯一锚定时才渲染） */
.u2bar{border:1px solid var(--line);border-radius:12px;background:#fff;
 padding:10px 12px;margin:12px 0}
.u2head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.u2head b{font-size:14px}
.u2head .sub{margin:0;font-size:14px}
.u2chips{display:flex;gap:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;
 margin-top:8px;padding-bottom:2px}
.u2chip{flex:0 0 auto;display:flex;flex-direction:column;align-items:flex-start;gap:1px;
 background:#f6f5f0;border:1px solid var(--line);color:var(--fg);border-radius:12px;
 padding:6px 10px;font-size:14px;cursor:pointer;text-align:left;min-width:0;max-width:220px}
.u2chip:hover{border-color:var(--accent)}
.u2chip.on{border-color:var(--accent);background:#f1f8f4}
.u2chip .u2c{font-weight:600;color:var(--muted);font-size:13px}
.u2chip .u2n{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}
.u2chip .u2n.empty{color:var(--muted);font-style:italic}
/* v0.6.6：成分页多国并排矩阵（行=规格/剂型/释放，列=国家；服务端默认 en 序，客户端按语言重排） */
.matwrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:10px 0}
table.matrix{width:100%;border-collapse:collapse;min-width:860px}
table.matrix th,table.matrix td{border:1px solid var(--line);padding:8px 12px;
  text-align:left;vertical-align:top;font-size:16px;line-height:1.5}
table.matrix thead th{white-space:nowrap;font-weight:650}
table.matrix td.m-spec{white-space:nowrap;background:#f6f5f0}
table.matrix .m-brand{display:-webkit-box;-webkit-box-orient:vertical;
  -webkit-line-clamp:2;overflow:hidden;max-width:220px;margin:0 6px 2px 0;
  vertical-align:top;line-height:1.35;min-height:24px;padding:3px 0;
  text-decoration:underline;text-underline-offset:2px}
/* v0.10.2 M-5：矩阵卡里的成分对照名是判断「这条到底是什么药」的关键信息，12px → 14px */
.m-en{display:inline-block;margin:0 6px 2px 0;font-size:14px;color:var(--muted)}
.m-zh{display:inline-block;margin:0 0 2px 0;font-size:14px;color:var(--muted)}
/* v0.9.0 task-19/6：无商品名占位 / 矩阵 +N 展开 */
.brand-none{color:var(--muted);font-weight:600}
/* v0.11.6 task-1（T12 C1/C2）：品牌页成分卡与配方差异表里的成分中文名（只在中文/繁体界面显示）。
   成分页的同名 span 在 .drug-name-src 里，靠 .sub 的样式；这里是 h2 / 表格单元格里，单独给一层。 */
.card h2 .name-zh,.famcmp .name-zh,.m-combo .name-zh{font-size:15px;font-weight:400;color:var(--muted);margin-left:.4em}
.m-none-ing{display:inline-block;font-size:14px;color:var(--muted);margin-left:4px}
.m-more{display:inline-block;margin-left:4px;font-size:14px}
/* v0.9.1 task-29/22：矩阵筛选器占位，避免 JS 插入时把表格整体推下去（CLS） */
.mf-slot{min-height:170px}
@media (max-width:767px){ .mf-slot{min-height:92px} }
.m-more summary{cursor:pointer;color:var(--accent);list-style:none}
.m-more summary::-webkit-details-marker{display:none}
.m-more summary:before{content:"+";font-weight:600}
.m-more[open] summary:before{content:"−"}
.m-rest{display:block;margin-top:4px;font-size:14px}
.m-orig{display:block;margin-top:2px;font-size:14px;color:var(--muted);font-weight:400;white-space:normal}
.name-single-note,.maker-single-note{margin:18px 0 0;color:var(--muted);font-size:14px}
/* v0.8.4 task-128：状态彩色角标（A1 明细等） */
.st-badge{display:inline-block;font-size:13px;padding:2px 6px;border-radius:999px;
  border:1px solid var(--line);margin-right:4px;white-space:nowrap}
.st-active{color:#0b6b53;border-color:#a9d3c5;background:#eef7f3}
.st-discontinued{color:#8a4b12;border-color:#e6c9a2;background:#fff6e8}
.st-withdrawn{color:#8a2c1f;border-color:#e6bdb4;background:#fdf0ee}
.st-unknown{color:var(--muted);background:#f6f5f2}
.c-brand{overflow-wrap:anywhere}
/* v0.10.2 task-5：成分页顶部精简悬浮条（滚过 H1 后仍知道「我在看哪个成分」）。
   纯 CSS sticky：不加自动隐藏动画、不改键盘/读屏顺序；高度 ≤56px；
   z-index 15 < 手机底栏 .tabbar 的 45，> 矩阵内容（行头 2）。 */
.drug-sticky{position:sticky;top:0;z-index:15;display:flex;align-items:center;gap:10px;
  min-height:44px;max-height:56px;margin:0 0 10px;padding:6px 10px;
  background:var(--bg);border:1px solid var(--line);border-radius:10px}
.drug-sticky .ds-name{flex:1 1 auto;min-width:0;font-weight:600;font-size:15px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.drug-sticky .ds-meta{flex:0 0 auto;color:var(--muted);font-size:13px;white-space:nowrap}
.drug-sticky .ds-filter{flex:0 0 auto;min-height:32px;display:inline-flex;align-items:center;
  padding:0 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);
  color:var(--fg);font-size:13px;text-decoration:none}
.drug-sticky .ds-filter:hover{border-color:var(--accent);color:var(--accent)}
#filters,table.matrix th[data-country],table.matrix td[data-country]{scroll-margin-top:64px}
@media (max-width:767px){ .drug-sticky{max-height:56px;padding:4px 8px} }
/* v0.10.3 task-16：成分页主视图 = 按国家分组清单（矩阵降级 ?view=table）。
   目标行高：1440 ≤72px / 390 ≤88px；零「未收录」格子；无 JS 也可读。 */
.formchips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 12px}
.formchip{display:inline-flex;align-items:center;gap:6px;min-height:36px;padding:0 12px;
 border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--fg);
 font-size:14px;text-decoration:none}
.formchip:hover{border-color:var(--accent);color:var(--accent);text-decoration:none}
.formchip.on{background:var(--accent-weak);border-color:var(--accent);color:var(--accent);
 font-weight:600}
.formchip .n{color:var(--muted);font-size:13px}
.mkblock{margin:0 0 14px;border:1px solid var(--line);border-radius:12px;background:var(--card);
 padding:10px 12px}
/* 2026-11-11 UI：成分页「按国家分组」的块头由 h3 提到 h2（原来 h1 → h3 跳级，
   impeccable skipped-heading）；字号/外边距保持原来的 16px / 6px，不动全局 h2 规则。 */
.mkblock>h2{margin:0 0 6px;font-size:16px}
.mkblock>h2 .sub{font-weight:400;margin-left:6px}
.mkspecs{list-style:none;margin:0;padding:0}
.mkrow{display:grid;grid-template-columns:minmax(120px,1.1fr) minmax(90px,.9fr) 3fr;
 align-items:baseline;gap:4px 10px;padding:6px 0;border-top:1px solid var(--line-soft);
 font-size:16px;line-height:1.35}
/* 剂型筛选靠 row.hidden 切换；`.mkrow{display:grid}` 会盖掉 UA 的 [hidden]，
   所以这里显式写一遍（全局 [hidden] 兜底之外的第二道保险）。 */
.mkrow[hidden]{display:none}
.mkrow:first-child{border-top:0}
.mkst{font-weight:600}
.mkf{color:var(--muted);font-size:14px}
.mkname-cell{display:flex;align-items:baseline;gap:6px;min-width:0;overflow:hidden;
 max-height:3em}
/* 名字最多两行（长中文/英文商品名在 390 下会占 3 行，把行高顶到 135） */
.mknames{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
 overflow:hidden;white-space:normal;min-width:0;line-height:1.35}
.mknames .m-brand{white-space:nowrap}
/* `+N`：纯 CSS 展开（checkbox + label），无 JS 可点。
   不用 <details>：它和矩阵遗留的 .m-brand/.m-rest 规则打架，390 下把行高从 71 顶到 95。 */
.mkname-cell .m-x{display:none}
.mkname-cell .m-more{display:inline-block;margin:0;cursor:pointer;color:var(--accent);
 border:1px solid var(--line);border-radius:999px;padding:0 6px;font-size:13px;line-height:20px}
.mkname-cell .m-rest{display:none}
.mkname-cell .m-x:checked ~ .m-rest{display:inline}
.mkname-cell .m-x:checked ~ .m-more{background:var(--accent-weak);border-color:var(--accent)}
/* 矩阵里的 .m-brand 是 -webkit-box 行夹（块级），清单里要行内排，否则每个名字独占一行 */
.mkname-cell .m-brand{display:inline;max-width:none;min-height:0;padding:0;
 text-decoration:none;-webkit-line-clamp:none}
.mkrowmeta{grid-column:1 / -1;display:flex;align-items:center;gap:8px;min-width:0}
.mkx{color:var(--muted);font-size:13px;white-space:nowrap;min-width:0;
 overflow:hidden;text-overflow:ellipsis}
.mkx a{margin:0 1px}
.mkundis{margin:8px 0 0;padding-top:8px;border-top:1px dashed var(--line);font-size:16px;
 color:var(--muted)}
.mkundis .uname{margin-right:8px}
/* T13（v0.11.7）：成分页「市场 / 单方·复方 / 规格」筛选条 + 块头来源行 + 可点开的「另 N 个市场」 */
/* T13（v0.11.7）：筛选条挂在成分页的 sticky 条里（z 常规流里的一个 chip，收起时零高度），
   展开时是浮层（absolute），不把正文往下推 —— 首屏条目零损失。 */
.listfilters{display:inline-flex;flex-direction:column;position:relative}
.listfilters>summary{list-style:none;cursor:pointer}
.listfilters>summary::-webkit-details-marker{display:none}
.listfilters>summary::after{content:" ▾";color:var(--muted);font-size:12px}
/* 与 `.ds-filter` 同高（32px），否则 sticky 条在 390 会多出一行（+12px → 首屏条目掉 0.5 条） */
.drug-sticky .listfilters>summary{display:inline-flex;align-items:center;min-height:32px;
 padding:0 4px;font-size:14px;line-height:1.2;white-space:nowrap}
.listfilters[open]>summary::after{content:" ▴"}
/* 面板用站点既有色阶 `--surface-2`（#f6f5f0，表头/色带同色），chip 仍是 #fff ——
   「框内颜色 ≠ 最近不透明祖先的填充色」是用户 2026-11-10 的硬规则，
   deploy/ui_surface_check.py 会拦；白底白底曾报 11 处 FAIL。 */
.lf-panel{position:absolute;top:calc(100% + 6px);left:0;z-index:30;background:var(--surface-2);
 border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;
 gap:6px;box-shadow:0 8px 24px rgba(0,0,0,.10);min-width:min(92vw,640px)}
.listfilters .lf-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.listfilters .lf-status{margin:0;font-size:13px;color:var(--muted)}
.listfilters .lf-none{margin:0;font-size:15px;color:var(--fg)}
.lf-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.lf-k{font-size:13px;color:var(--muted);min-width:3.5em}
.lf-chip{display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:0 10px;
 border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--fg);
 font-size:14px;cursor:pointer;text-decoration:none}
.lf-chip:hover{border-color:var(--accent);color:var(--accent);text-decoration:none}
.lf-chip.on{background:var(--accent-weak);border-color:var(--accent);color:var(--accent);font-weight:600}
.lf-chip .n{color:var(--muted);font-size:12px}
.lf-input{min-height:32px;padding:0 10px;border:1px solid var(--line);border-radius:8px;
 font-size:15px;min-width:12em;flex:0 1 18em}
.lf-status{margin:0;font-size:13px;color:var(--muted)}
.lf-none{margin:6px 0;font-size:15px;color:var(--fg)}
.mkmeta{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;color:var(--muted);font-size:13px;font-weight:400;vertical-align:baseline}
@media (max-width:767px){ .mkmeta{display:none} }
.mkx-more{display:inline;margin-left:4px}
.mkx-more>summary{display:inline;cursor:pointer;color:var(--accent);list-style:none}
.mkx-more>summary::-webkit-details-marker{display:none}
.mkx-more .mkx-links{display:inline;margin-left:4px}
/* `+N` 自己是一个叶子节点（atc4-ui D6 按「叶子文本 = +N」判可点），句子在旁边一格 */
.mkx-plus{font-weight:600;margin-right:2px}
.mkx-lbl{margin-left:0}
/* T13（v0.11.7）：分类页页内搜索 + 子类筛选 + 说明折叠
   v0.11.7 复审：子类 chip 收进 `<details>` 浮层（默认收起）、搜索框/子类入口/计数同一行，
   分类页首屏条目 9 → 回到 10.5 以上（−5% 线是阻塞项）。 */
.catfinder{display:flex;flex-direction:column;gap:4px;margin:6px 0 8px}
.catfinder .cf-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.catfinder .cf-input{min-height:34px;padding:0 10px;border:1px solid var(--line);
 border-radius:8px;font-size:16px;flex:1 1 14em}
.catfinder .cf-status{margin:0;font-size:13px;color:var(--muted);flex:0 0 auto}
.catfinder .cf-sub{position:relative;flex:0 0 auto}
.catfinder .cf-sub>summary{display:inline-flex;align-items:center;min-height:34px;padding:0 10px;
 border:1px solid var(--line);border-radius:8px;background:var(--card);cursor:pointer;
 font-size:14px;list-style:none;color:var(--fg)}
.catfinder .cf-sub>summary::-webkit-details-marker{display:none}
.catfinder .cf-sub>summary::after{content:" ▾";color:var(--muted);font-size:12px}
.catfinder .cf-sub[open]>summary::after{content:" ▴"}
/* 浮层用站点既有 `--surface-2`：chip 是 #fff，框内 ≠ 框外（ui_surface_check 硬规则） */
.catfinder .cf-chips{position:absolute;top:calc(100% + 4px);left:0;z-index:25;
 display:flex;flex-wrap:wrap;gap:6px;padding:10px 12px;background:var(--surface-2);
 border:1px solid var(--line);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.10);
 min-width:min(92vw,520px)}
.cat-help{margin:6px 0 10px;font-size:15px}
.cat-help>summary{cursor:pointer;color:var(--accent);list-style:none}
.cat-help>summary::-webkit-details-marker{display:none}
.cat-help>summary::before{content:"▸ ";font-size:13px}
.cat-help[open]>summary::before{content:"▾ "}
.atcmembers li[hidden],.mkrow[hidden],.mkblock[hidden],.mkseg[hidden]{display:none!important}
.src-asof{color:var(--muted);font-size:13px;white-space:normal}
.mkcmp{margin:6px 0 10px}
/* T11（v0.11.7）：sticky 里的「状态 + 目标市场 chips」同一行；pickbar 与对照块 */
.t11row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:2px 0 0}
.t11row .search-status{margin:0;flex:1 1 auto;min-width:0}
.mkchips{display:flex;gap:4px;overflow-x:auto;max-width:100%;padding:2px 0}
.mkchip{flex:0 0 auto;min-height:28px;padding:0 8px;border:1px solid var(--line);border-radius:999px;
 background:#fff;color:var(--fg);font-size:13px;cursor:pointer}
.mkchip.on{background:var(--accent-weak);border-color:var(--accent);color:var(--accent);font-weight:600}
.pickbar{margin:4px 0 0;padding:6px 10px;border:1px solid var(--line);border-left:4px solid var(--accent);
 border-radius:8px;background:#fff}
.pickbar .pickrow{display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:15px}
.pickbar .pickname{font-weight:600}
.pickbar .pickmeta{color:var(--muted);font-size:14px}
.pickbar .picknote{margin:2px 0 0;font-size:13px}
.cmpbox{margin:10px 0 4px;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#fff}
.cmpbox h2{margin:0 0 6px;font-size:var(--fs-md)}
table.res.cmp{font-size:15px}
table.res.cmp th:first-child{width:8em;color:var(--muted);font-weight:600}
.cmp-b{display:inline-block;font-size:13px;padding:0 8px;border-radius:999px;border:1px solid var(--line)}
.cmp-b.same{color:var(--accent);border-color:var(--accent);background:var(--accent-weak)}
.cmp-b.diff{color:var(--warn);border-color:var(--warn)}
.cmp-b.miss{color:var(--muted)}
.cmp-note{margin:6px 0 0;font-size:13px}
/* T11：桌面端结果行必须保持 ~42px（首屏条目靠它）——
   ① 「数据截止」小字在 ≥768 只留在身份卡里，不进窄的市场列（否则行高 42 → 138）；
   ② 手机端市场 chips 收进高级筛选，sticky 行里只留一行「目标市场 ▾」入口（高度 0 增量）。 */
@media (min-width:768px){ td.c-market .src-asof{display:none} }
.mkopen{display:none}
@media (max-width:767px){
  .mkchips{display:none}
  .mkopen{display:inline-block;font-size:13px;color:var(--accent);margin-left:6px;white-space:nowrap}
}
/* T11：行内「这条」按钮做成轻链接样式 —— 结果行高度必须保持 ~42px（首屏条目靠它） */
.pickbtn{border:0;background:none;color:var(--accent);font:inherit;font-size:13px;
 padding:0 6px 0 0;margin:0;cursor:pointer;white-space:nowrap;line-height:1.6}
.pickbtn:hover{text-decoration:underline}
/* 详情列不许换行：里面现在有「◎ / 详情 / ⚑」三件，换行会把行高从 42 撑到 65px。
   「◎ 这条」用绝对定位贴到行右缘：不参与表格布局 → 行高与 v0.11.6 完全一致（首屏条目靠它）。 */
td.c-det{white-space:nowrap}
tr.br{position:relative}
tr.br .pickbtn{position:absolute;right:2px;top:2px;min-height:0;height:auto;
 padding:0 2px;line-height:1.1;font-size:12px}
/* ↑ 不设 background：按钮浮在结果行（表底 #fff）上，白底=白底会被
   deploy/ui_surface_check.py 判「框内颜色 == 框外颜色」（用户 2026-11-10 硬规则）。 */
.advfilter{margin:6px 0 10px}
/* 「高级筛选」面板本身刷 `--surface-2`：里面的 `#country` / `#src` 是浏览器默认白底
   （rgb(255,255,255)），若面板沿用 `.mf-details` 的 #fff，就会被
   deploy/ui_surface_check.py 判「框内 == 框外」（home/results × 两个视口共 8 处）。
   只改填充，不动 padding / margin（首屏条目与 #mkchips 位置保持不变）。 */
details.advfilter{background:var(--surface-2)}
.advfilter>summary{cursor:pointer;color:var(--accent);font-size:15px;list-style:none}
.advfilter>summary::-webkit-details-marker{display:none}
.advfilter>summary::before{content:"▸ ";font-size:13px}
.advfilter[open]>summary::before{content:"▾ "}
.tableview[hidden]{display:none}
.mkblock.mkflash{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:no-preference){
 .mkblock{transition:outline-color .2s}
}
@media (max-width:767px){
 /* chips 单行横滑（24 个 chip 换成受控码后最多 8 个，仍不铺多行占首屏） */
 .formchips{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;
  padding-bottom:2px;margin-bottom:8px}
 .formchip{flex:0 0 auto}
 .mkrow{grid-template-columns:1fr auto;font-size:16px;padding:4px 0;line-height:1.25}
 .mkf{grid-column:2;text-align:right}
 .mknames{grid-column:1 / -1}
 /* 手机上省掉「也在」这两个字，只留市场码，避免行高被推到 100px+ */
 .mkx [data-i18n]{display:none}
 /* 手机只显示第一个名字（任务允许 ≤2），第二个及以后进 +N，保证行高 ≤88px */
}
.matrix-brand-note{margin:6px 0 0;font-size:14px}
/* v0.10.2 task-10：CN 无商品名 → 名称位显示「厂家：<MAH>」（弱化，不是品牌名） */
.m-mah{color:var(--fg);font-weight:600}
.m-mah .mah-k{color:var(--muted);font-weight:400;font-size:13px}
.m-mah .m-n{color:var(--muted);font-weight:400;font-size:13px}
/* v0.10.2 R1：剂型列里的「来源原文」小字（不翻译原文，只翻译这个标签） */
.m-orig{color:var(--muted);font-size:13px}
.m-orig-raw{color:var(--muted);font-size:13px}
/* v0.10.2 task-4：可见列全空的行（只在被隐藏市场有记录）默认不渲染，说明 + 一键加列在表下 */
.matrix-hidden-rows{margin:8px 0 0}
.matrix-hidden-rows .sub{margin:0 0 6px}
table.matrix tr[data-hide-empty="1"]{display:none}
.matrix-hk-note{margin:4px 0 0;font-size:14px;color:var(--warn)}
/* v0.11.0 P1：EU 区域层的口径说明（集中审批 ≠ 某国在售、无规格/剂型/包装）。
   与 .matrix-hk-note 同一档字号（14px，≥ 辅助 13px 底线），不新起一套字号。 */
.matrix-region-note,.mkregion{margin:4px 0 0;font-size:14px;line-height:1.55;
  color:var(--muted);max-width:var(--prose)}
.matrix-region-note{color:var(--warn)}
.mkregion{margin:0 0 10px}
.mkregion b{color:var(--fg);font-weight:600}
/* v0.8.3 task-119：矩阵筛选器 */
.matrix-filters{margin:10px 0 6px;border:1px solid var(--line);border-radius:12px;
  background:var(--surface-2);padding:10px 12px}
.mf-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.mf-title{font-weight:600;font-size:14px}
.mf-count{color:var(--muted);font-size:14px}
.mf-toggle{margin-left:auto}
.mf-panel{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
  gap:8px 14px;margin-top:10px}
.mf-field{display:flex;flex-direction:column;gap:4px;font-size:14px;color:var(--muted)}
.mf-field select,.mf-field input[type=search]{padding:6px 8px;border:1px solid var(--line);
  border-radius:8px;font-size:14px;background:#fff;color:var(--fg)}
.mf-countries{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:14px;color:var(--fg)}
.mf-countries label{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.m-reset{border:1px solid var(--line);background:#fff;color:var(--fg);border-radius:8px;
  padding:6px 12px;font-size:14px;cursor:pointer}
.mf-country-actions{display:flex;gap:6px;margin-top:4px}
.mf-country-actions .mf-reset{padding:2px 8px;font-size:14px}
.mf-count.mf-warn{color:var(--warn);font-weight:600}
/* v0.10.2 M-3：「横滑看更多市场」只对桌面（表格态）成立，手机是卡片态、没有横滑，不再显示 */
.matrix-scroll-hint{display:none;margin:2px 0 0;font-size:14px}
@media (min-width:768px){ .matrix-scroll-hint{display:block} }
/* v0.9.0 task-6：横滑 + 规格列 sticky + 移动端卡片 */
.matwrap{position:relative}
table.matrix thead th:first-child,
table.matrix td.m-spec{position:sticky;left:0;z-index:2}
table.matrix th[data-country]:not([data-defcol]),
table.matrix td[data-country]:not([data-defcol]){display:none}
.matrix-sort-note{margin:4px 0 0;font-size:14px}
@media (max-width:767px){
  .matrix-filters .mf-panel{display:none}
  .matrix-filters.mf-open .mf-panel{display:grid}
  .mf-toggle{display:inline-flex;min-height:40px;align-items:center}
  .mf-field select,.mf-field input[type=search]{min-height:40px}
  /* v0.10.2 M-3：筛选器复选框 36px → 44px 触控目标（WCAG 2.2 AA 推荐 44×44） */
  .mf-countries label{min-height:44px}
}
@media (min-width:768px){
  /* v0.9.1 P0-4：桌面筛选面板本来常显，隐藏无效的「筛选」按钮 */
  .mf-toggle{display:none}
}
@media (max-width:767px){
  /* 移动端：每规格一张卡，市场列纵向排列，不横向滚动 */
  .matwrap{overflow-x:visible;margin:8px 0}
  table.matrix{display:block;min-width:0;width:100%;border-collapse:separate;border-spacing:0}
  table.matrix thead{display:none}
  table.matrix tbody{display:block}
  table.matrix tr{display:block;background:#fff;border:1px solid var(--line);
    border-radius:12px;margin:8px 0;padding:6px 8px}
  table.matrix td{display:block;border:0;padding:3px 2px;white-space:normal;font-size:14px}
  table.matrix td.m-spec{position:static;background:transparent;border-bottom:1px solid var(--line);
    margin-bottom:4px;padding-bottom:6px}
  table.matrix td[data-country]:before{content:attr(data-country) " · ";color:var(--muted);
    font-weight:600;font-size:14px}
}
@media (max-width:767px){
  .u1steps{grid-template-columns:1fr}
  .u1close{min-width:44px;min-height:44px}
  .u2chip{max-width:70vw}
}
@media (max-width:767px){
  .wrap{padding:0 14px}
  header .wrap{height:auto;flex-wrap:wrap;padding:10px 14px;gap:8px 12px}
  .logo{font-size:16px}
  .logo-zh{display:none}
  nav{flex-wrap:wrap;gap:8px 12px;font-size:14px}
  .langs{margin-left:auto}
  #q{font-size:16px;padding:12px 14px}
  .row{gap:8px}
  .sel-label{display:block;width:100%;margin:2px 0 0}
  .parsebar{gap:4px 12px;font-size:14px}
  .card{padding:12px}
  footer .wrap{display:block}
  .foot-links{margin:8px 0 0;display:flex;flex-wrap:wrap;white-space:normal;gap:8px 14px}
  /* 结果表 → 卡片（ARTG / 同成分表一并生效，靠 data-label 带出列名） */
  table.res{display:block;border:0;border-radius:0;background:transparent;margin-top:8px}
  table.res thead{display:none}
  table.res tbody{display:block}
  table.res tr{display:block;background:#fff;border:1px solid var(--line);
    border-radius:12px;margin:8px 0;padding:8px 12px}
  table.res td{display:block;border:0;padding:8px 0;width:auto}
  table.res td.c-dose{white-space:normal}
  table.res td.c-empty{display:none}
  table.res td[data-label]:before{content:attr(data-label) " · ";color:var(--muted);font-size:14px}
  table.res tr.grp{background:#f7f8f5;border-color:#e7e5dc;padding:8px 12px}
  table.res tr.grp td{display:block;width:auto}
  table.res tr.grp .grp-tags{text-align:left;margin-top:2px}
  table.res tr.fold-row{background:transparent;border:0;padding:0;margin:0}
  table.res tr.fold-row td{padding:0 0 4px}
  table.res tr.detrow{background:#f6f5f0;border-color:#e7e5dc;padding:4px 8px}
  table.res tr.detrow>td.detcell{display:block;padding:0}
  table.det{display:block;overflow-x:auto;white-space:nowrap}
  .restools{margin-top:8px}
  table.res tbody tr:hover{background:#fff}
  .loadmore button{width:100%}
  /* v0.11.6 task-1（T12 C2）：品牌页「配方差异」表在手机上排两列——市场 / 注册名 同一行，
     完整活性成分与关系说明各占整行。四行逐格堆叠时整表 686 px，两列后 518 px（实测 390×844），
     首屏可见条目 2.5 → 3 条；字号仍是 16 px，不碰正文下限。 */
  table.res.famcmp tr{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);column-gap:12px}
  table.res.famcmp td{padding:4px 0}
  table.res.famcmp td[data-i18n-label="fam.cmp_ing"],
  table.res.famcmp td[data-i18n-label="fam.cmp_rel"]{grid-column:1 / -1}
}
/* i18n P1：静态页（About / What's new / Confused）移动端收尾 */
@media (max-width:767px){
  .tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  main table:not(.res){font-size:14px}
  .release table{display:block;overflow-x:auto}
  .release ul,.release li,p,li{overflow-wrap:anywhere}
}
/* /warn 页：数据行按语言只显示一块（无 JS 时默认英文） */
.lang-block{display:none}
.lang-block[data-lang-block="en"]{display:block}
/* v0.5.3：品牌无页 → 不可点文本（不是链接，禁止回退 drug 页） */
.brand-plain{font-weight:600;color:var(--fg)}
/* v0.6.0：组合页跨市场同组合区块 */
.xlist{margin:6px 0 0;padding-left:18px;font-size:14px}
.xlist li{margin:3px 0}
.xlist .x-mkt{font-weight:600;color:var(--fg)}
/* v0.6.4 B10：术语表 */
dl.glossary{margin:10px 0;border-top:1px solid var(--line)}
dl.glossary dt{font-weight:650;margin:10px 0 2px}
dl.glossary dd{margin:0 0 4px;color:var(--muted)}
.atcbar code{font-size:14px}
/* v0.5.4：厂家列（可点厂家 + 「+N」展开列表） */
.maker-link{color:var(--accent)}
.maker-plain{color:var(--fg)}
.mah-toggle{font-size:14px;margin-left:4px;padding:0;text-decoration:underline}
.mah-list{margin:6px 0 0;padding-left:18px;font-size:14px}
.mah-list[hidden]{display:none}
.mah-list li{margin:2px 0}
.maker-page table.res{margin-top:6px}
.grp-name{font-weight:600}
a.grp-name{color:var(--accent)}
.warn-item{border:1px solid var(--line);border-radius:12px;background:#fff;
  padding:12px 14px;margin:10px 0}
.warn-item h3{margin:0 0 6px;font-size:16px;line-height:1.45}
.warn-item .warn-body{margin:0 0 8px}
.warn-item .warn-meta{color:var(--muted);font-size:14px;margin:0;overflow-wrap:anywhere}
.warn-item .badge{vertical-align:2px}
/* v0.6.7：/warn 分页（10 条/页；移动端 ≥40px 可点） */
.warnpager{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:16px 0 4px;font-size:14px}
.warnpager .pg-status{color:var(--muted);font-size:14px;margin-right:6px}
.warnpager a,.warnpager span{min-width:36px;min-height:36px;display:inline-flex;
  align-items:center;justify-content:center;padding:4px 9px;border:1px solid var(--line);
  border-radius:8px;color:var(--fg);background:#fff}
.warnpager a:hover{border-color:var(--accent)}
.warnpager .pg-num.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.warnpager .disabled{color:var(--muted);opacity:.5;cursor:not-allowed}
.drugwarn ul{margin:6px 0 4px;padding-left:20px}
@media (max-width:767px){
  .warn-item .warn-meta{font-size:14px}
  .warnpager{gap:6px}
  .warnpager a,.warnpager span{min-width:40px;min-height:40px;font-size:16px}
}

/* ── v0.9.8 task-13（UI 批次 A-2）：统一外壳 / 44px 触控 / 名字页 / 成分页 ── */
.sn{display:flex;align-items:center;gap:2px;font-size:14px;white-space:nowrap;margin-left:8px}
.sn>a,.sn>details>summary{display:inline-flex;align-items:center;min-height:44px;padding:0 10px;
 border-radius:8px;color:var(--fg);cursor:pointer;list-style:none;white-space:nowrap}
.sn>a:hover,.sn>details>summary:hover{background:#f1f8f4;text-decoration:none}
.sn>a.on{color:var(--accent);font-weight:600}
.sn>details>summary::-webkit-details-marker{display:none}
.sn>details[open]>summary{background:#f1f8f4;color:var(--accent)}
.sn>details>summary:after{content:"▾";margin-left:6px;color:var(--muted);font-size:14px}
.sn-dd{position:relative}
.sn-panel{position:absolute;top:calc(100% + 8px);left:0;z-index:60;background:#fff;
 border:1px solid var(--line);border-radius:12px;box-shadow:0 8px 24px rgba(31,35,40,.12);
 padding:12px;min-width:300px}
.sn-cats,.sn-mkts{display:grid;grid-template-columns:repeat(2,minmax(170px,1fr));gap:2px 10px}
.sn-about{display:grid;grid-template-columns:1fr 1fr;gap:2px 10px}
.sn-cats a,.sn-mkts a,.sn-about a{display:flex;align-items:center;gap:8px;min-height:40px;
 padding:4px 8px;border-radius:8px;color:var(--fg);font-size:14px}
.sn-cats a:hover,.sn-mkts a:hover,.sn-about a:hover{background:#f1f8f4;text-decoration:none}
.sn-mkts .meta{color:var(--muted);font-size:14px;margin-left:auto}
.sn-foot{border-top:1px solid var(--line);margin-top:8px;padding-top:8px;display:flex;
 justify-content:space-between;gap:12px;font-size:14px}
.tabbar{display:none}
@media (max-width:767px){
  header.hdr-shell .wrap{height:56px;flex-wrap:nowrap;gap:8px;padding:0 12px}
  header.hdr-shell .logo{min-width:0;overflow:hidden;text-overflow:ellipsis;font-size:14px}
  header.hdr-shell .logo-zh{display:none}
  header.hdr-shell nav{display:none}
  header.hdr-shell .nav-toggle{display:none}
  header.hdr-shell .langs{margin-left:auto;flex-shrink:0;gap:2px}
  header.hdr-shell .langs a{min-width:44px;min-height:44px;display:inline-flex;
   align-items:center;justify-content:center;padding:0 4px;font-size:14px}
  body{padding-bottom:56px}
  .tabbar{display:flex;position:fixed;left:0;right:0;bottom:0;height:56px;background:#fff;
   border-top:1px solid var(--line);z-index:45;padding-bottom:env(safe-area-inset-bottom)}
  .tabbar a{flex:1;display:inline-flex;align-items:center;justify-content:center;
   min-height:44px;font-size:14px;color:var(--muted);position:relative}
  .tabbar a.on{color:var(--accent);font-weight:600}
  .tabbar a.on:before{content:"";position:absolute;top:0;left:26%;right:26%;height:3px;
   background:var(--accent);border-radius:0 0 3px 3px}
}
/* P0-7：六类触控目标 ≥44×44（min-height 扩张，视觉基本不变） */
nav a{min-height:44px;display:inline-flex;align-items:center}
.langs a{min-width:44px;min-height:44px;display:inline-flex;align-items:center;justify-content:center}
.catchip{min-height:44px}
.atccard{min-height:44px}
.u1try button{min-height:44px}
.homeupd .updlist a{min-height:44px}
/* P0-8：名字页「不可互换」警示 + 成分卡折叠 */
.name-notice{color:var(--warn);margin:6px 0 2px}
.name-more{margin:10px 0}
.name-more>summary{display:inline-flex;align-items:center;min-height:44px;padding:0 14px;
 border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer;font-size:14px}
.name-more>summary::-webkit-details-marker{display:none}
.name-more>summary:after{content:"▾";margin-left:6px;color:var(--muted);font-size:14px}
.name-more[open]>summary:after{content:"▴"}
/* P0-9：成分页筛选器默认收起（details 由 JS 包） */
.mf-slot{min-height:44px}
.mf-details{margin:10px 0 6px;border:1px solid var(--line);border-radius:12px;background:#fff}
.mf-details>summary{display:flex;align-items:center;gap:8px;min-height:44px;padding:8px 12px;
 cursor:pointer;font-size:14px;font-weight:600;list-style:none}
.mf-details>summary::-webkit-details-marker{display:none}
.mf-details>summary:after{content:"▾";margin-left:auto;color:var(--muted);font-size:14px}
.mf-details[open]>summary{border-bottom:1px solid var(--line)}
.mf-details .matrix-filters{margin:0;border:0;border-radius:0 0 12px 12px}
.mf-details .mf-toggle{display:none}
.mf-details .mf-panel{display:grid}
/* 2026-11-11 UI：首页「只看某个国家/地区」也走 .mf-details（44px summary + ▾），
   面板里竖排「说明 + 下拉」，触控高度 44px。 */
.ctry-panel{padding:10px 12px}
.ctry-panel .sel-label{display:block;margin:0 0 6px}
.ctry-panel select{min-height:44px;max-width:100%}
/* 2026-11-13 task-58（用户截图：目标/来源市场上下堆叠）：≥1024px 两列并排，
   左目标 #country、右来源 #src，等宽、顶部对齐、间距 20px；<1024（含 390）仍上下堆叠。 */
@media (min-width:1024px){
  #ctrydetails .ctry-panel{display:grid;
    grid-template-columns:minmax(0,1fr) minmax(0,1fr);
    grid-template-areas:"lc sc" "ls ss";
    column-gap:20px;row-gap:2px;align-items:end}
  #ctrydetails .sel-label[for="country"]{grid-area:lc}
  #ctrydetails #country{grid-area:ls}
  #ctrydetails .sel-label[for="src"]{grid-area:sc}
  #ctrydetails #src{grid-area:ss}
  #ctrydetails .ctry-panel select{width:100%}
  #ctrydetails .ctry-panel .sel-label{margin:0}
}
.drug-identity{margin:2px 0 10px}
.drug-identity b{color:var(--fg)}

/* A-2 fix：桌面壳单行（1280 下 5 项 nav 不再折行被 header 高度裁切） */
@media (min-width:1100px){
  header.hdr-shell .wrap{height:64px;flex-wrap:nowrap}
  header.hdr-shell .sn{flex-wrap:nowrap}
  header.hdr-shell .langs{margin-left:auto}
}
@media (min-width:768px) and (max-width:1024px){
  header.hdr-shell .wrap{height:auto;flex-wrap:wrap;
   padding-top:8px;padding-bottom:8px;gap:6px 12px}
  header.hdr-shell .sn{order:3;flex-basis:100%;flex-wrap:wrap;margin-left:0;gap:4px 8px}
  header.hdr-shell .langs{margin-left:auto}
}

/* A-2 fix2：头部双语开关单行（zh「显示原文对照」6 字，1280 下不折行） */
header.hdr-shell .bil-toggle{white-space:nowrap;margin:0 6px;flex:none}

/* ── v0.10.0 tokens 2.0 配套 ── */
.notice>div,.warn-item .warn-body,.idcard .notice div{max-width:var(--prose)}
table.res tbody tr:nth-child(even):not(.grp):not(.detrow):not(.fold-row){background:var(--surface-2)}
table.res tbody tr:hover{background:var(--surface-2)}
body.density-compact table.res td{padding:4px 8px;font-size:14px}
body.density-compact table.res th{padding:4px 8px;font-size:13px}
body.density-compact table.res{font-size:14px}
.warn-item h2{margin:0 0 6px;font-size:16px;line-height:1.4;font-weight:700}
.warn-item h3{margin:0 0 6px;font-size:16px;line-height:1.4;font-weight:700}
.warnfilters{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 4px}
.warnfilters button{min-height:44px;padding:0 14px;border-radius:var(--r-pill);border:1px solid var(--line);background:#fff;color:var(--fg);font-size:14px}
.warnfilters button.on{background:var(--accent);border-color:var(--accent);color:#fff}
.atc-notes{margin:14px 0}
.atc-notes>summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font-size:14px;color:var(--accent)}
.atc-notes .notice{margin:8px 0}
.covtools{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
.covtools button{min-height:44px;padding:0 14px;border-radius:var(--r-pill);border:1px solid var(--line);background:#fff;color:var(--fg);font-size:14px}
@media (max-width:767px){
  .coverage-table .covgap{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .tabbar{padding-bottom:env(safe-area-inset-bottom)}
  main{padding-bottom:80px}
}
@media (max-width:767px){.catgrid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:480px){.u1guide{padding:12px}.card{padding:12px}}

/* v0.10.0: neutral background bands + right-top category/language controls */
main .section,main .catquick{background:var(--band);border:1px solid var(--line);border-radius:12px;padding:16px}
/* v0.10.2 同色守卫 + 2026-11-13 task-29（用户截图）：两层要能分出层次 ——
   外层「按大类浏览」面板改浅绿（--accent-weak），内部类别 chip 改白（--card + --line 边框），
   框内/框外颜色不许一致（用户 2026-11-10 硬规则）。 */
main .catquick{background:var(--accent-weak)}
/* 2026-11-13 task-57（用户：大框绿色再深一点，小框保持白）：用现有色板混一档，
   目标 #e0efe6–#e6f2ea；chip 仍是 --card 白 + --line 边框。 */
main .catquick{background:color-mix(in srgb, var(--accent) 7%, var(--accent-weak))}
.u1guide{background:#fff}
.sn-right{display:flex;align-items:center;gap:2px;margin-left:auto}
.sn-right details{position:relative}
.sn-right summary{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 10px;border-radius:8px;cursor:pointer;list-style:none;font-size:14px;color:var(--fg)}
.sn-right summary::-webkit-details-marker{display:none}
.sn-right details[open]>summary{background:var(--accent-weak);color:var(--accent)}
.sn-panel-right{right:0;left:auto;min-width:210px}
.lang-menu a{display:flex;min-height:44px;align-items:center;padding:0 10px;border-radius:8px;color:var(--fg)}
.lang-menu a.on{background:var(--accent-weak);color:var(--accent);font-weight:600}
.sn-cats.compact{grid-template-columns:repeat(2,minmax(150px,1fr))}
.mmenu{display:none}
@media (max-width:767px){.sn-right .qcat,.sn-right .langdd{display:none}.mmenu{display:inline-flex}}
/* 2026-11-13 task-30（用户截图「还是竖着的」@1400）：
   v0.11.1 的 nowrap 只覆盖 .sn 与 .langs a；右侧「按类别」summary（w=34 h=67）与
   .lname「中文」（w=14 h=45）仍被挤成 min-content 竖排。这里：
   ① 页头所有含文字导航元素统一 nowrap（含 summary / .lname / 语言菜单）；
   ② 右侧组 flex:0 0 auto + min-width:max-content，不再被压缩；
   ③ 1100–1440 先隐藏 logo 副标题、再收窄间距；仍紧时 logo 省略号截断，绝不竖排/溢出。 */
header .sn a, header .sn summary, header .sn-right summary, header .sn-right .lname,
header .sn-right .langs, header .sn-right a, header .sn-right details > summary,
header .lang-menu a, header nav a, header .langs a, header .logo, header .logo-zh,
header .hdr-shell .sn, header .hdr-shell .sn-right{white-space:nowrap}
header .sn-right{flex:0 0 auto;min-width:max-content}
header .sn{flex:0 0 auto}
@media (min-width:1100px){
  header.hdr-shell .wrap{gap:8px}
  header.hdr-shell .logo{min-width:0;overflow:hidden;text-overflow:ellipsis}
  header.hdr-shell .sn{gap:0}
  header.hdr-shell .sn>a, header.hdr-shell .sn>details>summary{padding:0 8px}
  header.hdr-shell .sn-right summary{padding:0 8px}
}
/* 2026-11-13 task-62（用户：其余规格/未公开规格「这一坨」）：折叠摘要一行 +
   展开按组列 chip；不改数据、不丢条目。 */
.more-specs,.undis{margin:10px 0 0;border:1px solid var(--line);border-radius:10px;
 /* transparent：它们坐在 `.mkblock`（--card 白）里，再刷同色会被
    deploy/ui_surface_check.py 判「框内 == 框外」（24 处）；透明与白底视觉一致 */
 background:transparent;padding:8px 10px}
.more-specs>summary,.undis>summary{display:flex;align-items:center;gap:6px;list-style:none;
 cursor:pointer;font-size:14px;line-height:1.5;color:var(--muted);white-space:nowrap;overflow:hidden}
.more-specs>summary::-webkit-details-marker,.undis>summary::-webkit-details-marker{display:none}
.more-specs>summary .ln,.undis>summary .ln{flex:1 1 auto;min-width:0;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
.more-specs>summary::after,.undis>summary::after{content:"▾";flex:none;font-size:13px;
 line-height:1;color:var(--muted)}
.more-specs[open]>summary::after,.undis[open]>summary::after{content:"▴"}
.ms-body,.und-body{margin-top:8px;font-size:14px}
.ms-grp{margin:6px 0}
.ms-grp>summary{font-size:14px;line-height:1.5;color:var(--muted);cursor:pointer}
.ms-h,.und-h{display:block;color:var(--muted);font-size:14px;margin:0 0 4px}
.ms-list,.und-chips{display:flex;flex-wrap:wrap;gap:4px 8px}
.ms-spec,.uname{display:inline-block;padding:1px 8px;border:1px solid var(--line);
 border-radius:999px;background:var(--band);font-size:14px;line-height:1.6}
.uname .x{color:var(--muted);font-size:13px}
.ms-more,.und-more{color:var(--muted);font-size:14px}
.ms-more{margin-left:2px}
.und-more{margin:6px 0 0}
.full-list{margin:6px 0 0;font-size:14px}
.und-grp + .und-grp{margin-top:8px}
.und-grp{display:block}
@media (max-width:767px){
 .more-specs,.undis{padding:8px}
 .ms-spec,.uname{font-size:14px}
}
/* 2026-11-13 task-59（用户：「原来的字符大小、颜色等不要动」）：ATC 卡片只保留
   几何对齐（border/radius/padding/min-height/grid/details），文字排版与颜色全部回到
   v0.11.2 原值 —— 名称 16/1.3 muted、ATC 码 13 muted、盐型 16/1.35 muted、
   状态词 13/1.25（在售 fg、停售 warn、撤市 sev、未知 muted）、市场码 13 muted；
   折叠摘要与 ▾ 箭头也不超过原字号、不用 accent 色。 */
.atcmembers .atc-nm{font-size:16px;line-height:1.3;font-weight:400;letter-spacing:normal}
.atcmembers .atc-codes code{font-size:13px;line-height:1.3;color:var(--muted)}
.atcmembers .salt-details>summary{line-height:1.35}
.atcmembers .salt-details>summary .ln{font-size:16px;line-height:1.35;font-weight:400;
 color:var(--muted);letter-spacing:normal}
.atcmembers .salt-details .salt-k,.atcmembers .salt-details .nm{color:var(--muted)}
.atcmembers .salt-details>summary::after{font-size:13px;line-height:1.25;color:var(--muted)}
.atcmembers .salt-list{font-size:16px;line-height:1.35;color:var(--muted)}
.atcmembers .st-details>summary .ln{font-size:13px;line-height:1.25;font-weight:400;
 color:var(--muted);letter-spacing:normal}
.atcmembers .st-details .st-word{font-size:13px;line-height:1.25;font-weight:400;
 letter-spacing:0;color:var(--fg)}
.atcmembers .st-details .st-word.st-discontinued{color:var(--warn)}
.atcmembers .st-details .st-word.st-withdrawn{color:var(--sev)}
.atcmembers .st-details .st-word.st-unknown{color:var(--muted)}
.atcmembers .st-details .atc-mk{font-size:13px;line-height:1.25;color:var(--muted);
 letter-spacing:0;font-variant-numeric:tabular-nums}
.atcmembers .st-details>summary::after{font-size:13px;line-height:1.25;color:var(--muted)}
.atcmembers .st-list{font-size:13px;line-height:1.25;color:var(--muted)}
@media (min-width:1100px) and (max-width:1440px){
  header.hdr-shell .logo-zh{display:none}
}
/* task-59 收尾：折叠箭头必须在所有覆盖之后仍是 13px / muted（不得用 accent、不得大于原字号）。 */
.atcmembers .salt-details>summary::after,
.atcmembers .st-details>summary::after{font-size:13px;line-height:1.25;color:var(--muted)}
/* 2026-11-13 task-40 收尾：桌面卡片第 1 行必须真的 1 行（实测有卡片 .atc-nm 仍
   flex-wrap:wrap → 名称+码折成 2 行，高度极差 16.9px）。这里用更具体的选择器压住
   旧规则；390 不受影响（下面的 mobile 覆盖）。 */
@media (min-width:768px){
  .atcmembers .atc-nm{display:flex;flex-wrap:nowrap;white-space:nowrap;
   align-items:center;overflow:hidden}
  .atcmembers .atc-nm .atc-codes{flex-wrap:nowrap;flex:none}
  .atcmembers .atc-nm .st-badge,.atcmembers .atc-nm .nolang-badge{white-space:nowrap;flex:none}
}
/* 2026-11-13 task-37（用户截图：ATC 三列像多列流、同一行卡片上下边缘参差）：
   .atclist 的 multicol 与 li 的 align-self:start 是根因。清掉 columns，桌面走真正的
   行优先 grid；li 用默认 stretch → 同一行自动等高；ul align-content:start 让首行贴顶。
   长内容换行带动整行高度；390 仍是单列自然高度（现有 media query 的 display:block 保留）。 */
.atclist.atcmembers{columns:unset}
@media (min-width:768px){
  .atclist.atcmembers{display:grid;align-items:stretch;align-content:start}
}
.atcmembers>li{align-self:stretch}
/* 2026-11-13 task-39/40/41：盐型 / 状态都折成一行（原生 details，无 JS 可开、键盘可达）。
   摘要只显示第一个盐名/第一组状态 +「另有 N 个」，展开列全部；不丢信息、不硬裁切。 */
.atcmembers .salt-details,.atcmembers .st-details{margin:0;display:block;min-width:0}
.atcmembers .salt-details>summary,.atcmembers .st-details>summary{
 display:flex;align-items:center;gap:0;min-height:0;line-height:1.3;font-size:16px;
 cursor:pointer;list-style:none;color:var(--muted);white-space:nowrap;overflow:hidden}
.atcmembers .salt-details>summary::-webkit-details-marker,
.atcmembers .st-details>summary::-webkit-details-marker{display:none}
.atcmembers .salt-details>summary::after,.atcmembers .st-details>summary::after{
 content:"▾";flex:none;margin-left:auto;color:var(--accent);font-size:14px;line-height:1}
.atcmembers .salt-details[open]>summary::after,
.atcmembers .st-details[open]>summary::after{content:"▴"}
.atcmembers .salt-details>summary .ln,.atcmembers .st-details>summary .ln{
 flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.atcmembers .salt-list,.atcmembers .st-list{margin:2px 0 0;font-size:16px;line-height:1.35;
 color:var(--muted)}
.atcmembers .st-details .st-word{color:var(--fg);white-space:nowrap}
.atcmembers .st-details .st-line{display:block}
.atcmembers .st-details .st-line + .st-line{margin-top:2px}
.atcmembers .st-details .atc-mk{white-space:normal}
/* task-59 最终覆盖：必须排在 task-40 的 ▾ 规则之后（那里写了 14px/accent）。 */
.atcmembers .salt-details>summary::after,
.atcmembers .st-details>summary::after{font-size:13px;line-height:1.25;color:var(--muted)}
@media (max-width:767px){
 /* 390 单列：允许名称换行、卡片按内容自然高度（不裁切；展开自然变高） */
 .atcmembers>li{min-height:0}
 .atc-nm{flex-wrap:wrap}
 .atc-nm>a,.atc-nm>.brand-plain{white-space:normal;overflow:visible;text-overflow:clip}
 .atcmembers .salt-details>summary,.atcmembers .st-details>summary{white-space:normal;overflow:visible}
 .atcmembers .salt-details>summary .ln,.atcmembers .st-details>summary .ln{
   white-space:normal;overflow:visible;text-overflow:clip}
 .atcmembers .salt-details>summary,.atcmembers .st-details>summary{min-height:44px}
}
"""

def _detail_row_fields() -> list[str]:
    """读 etl/build_detail_buckets.py 的 ROW_FIELDS（明细行下标的唯一真相源）。

    v0.11.2 P0-2：``detPanelHTML()`` 曾把品牌列手写成 ``r[3]``，而 ROW_FIELDS[3] 是 pack →
    382,035 条明细行里 232,353 条（60.8%）的「品牌」列显示成包装原文。现在构建期把这份
    字段表注入 app.js，前端用 ``indexOf('brand')`` / ``indexOf('pack')`` 取名，不再写数字。
    """
    src = (ROOT / "etl" / "build_detail_buckets.py").read_text(encoding="utf-8")
    m = re.search(r"^ROW_FIELDS\s*=\s*\[(.*?)\]", src, re.S | re.M)
    if not m:
        raise SystemExit("etl/build_detail_buckets.py 里找不到 ROW_FIELDS，明细面板下标无法校验")
    return [part.strip().strip("\"'") for part in m.group(1).replace("\n", " ").split(",")
            if part.strip()]


DETAIL_ROW_FIELDS = _detail_row_fields()
if "brand" not in DETAIL_ROW_FIELDS or "pack" not in DETAIL_ROW_FIELDS:
    raise SystemExit(f"ROW_FIELDS 缺 brand/pack，明细面板列无法定位：{DETAIL_ROW_FIELDS}")

# v0.11.5 task-70 + task-5：共享静态资源一律「内容哈希文件名 + 全站同一 URL」，页面 HTML 不带 ?v=。
# （task-70 原先把「本页内容哈希」当 ?v= 加在 CSS/boot.js 上，浏览器按完整 URL 缓存 →
#   每换一页就重下 67 KB CSS + 18 KB boot.js，v0.11.4 是全站同一 URL；task-5 改回不可变文件名。）
# 效果：改一条文案只变命中页；改 CSS 只变引用该文件的页；改数据不再让 12 万页全变。
CSS_HASH = hashlib.sha256(CSS.encode("utf-8")).hexdigest()[:10]
CSS_FILE = "assets/style." + CSS_HASH + ".css"
# boot.js 里带 i18n 子资源的 ?v=BUILD_V，哈希要等 main() 定下 BUILD_V 后才能算，那里写定。
BOOT_JS_FILE = "assets/boot.js"


APP_JS = r"""
// v0.11.2 P0-2：明细行字段表由构建期从 etl/build_detail_buckets.py 的 ROW_FIELDS 注入，
// 明细面板的列下标一律从它取名（曾把品牌列写成 r[3]=pack，60.8% 明细行显示成包装）。
const DETAIL_ROW_FIELDS = __DETAIL_ROW_FIELDS__;
const DETAIL_COL = {brand: DETAIL_ROW_FIELDS.indexOf('brand'),
                    pack: DETAIL_ROW_FIELDS.indexOf('pack')};
const box = document.getElementById('q');
const out = document.getElementById('out');
const ctry = document.getElementById('country');
// v0.11.2（条目 10）：来源市场（?src=）与目标市场（?country=）是两个语义：
//   country = 目标市场（这个成分在该国叫什么）；src = 来源市场（只看这些登记库的记录）。
const srcEl = document.getElementById('src');
const srcNote = document.getElementById('srcnote');
const meta = document.getElementById('meta');
// v0.9.7 task-12：结果页 H1 改成查询名（清空查询时还原首页 H1）；身份卡挂在表前的 #identity。
const h1El = document.getElementById('h1');
const identityEl = document.getElementById('identity');
const H1_DEFAULT = h1El ? (h1El.textContent || '').trim() : '';
const TITLE_DEFAULT = document.title;
// v0.9.1 P0-3：结果计数/加载/零结果固定在搜索框下方（移动端不滚过引导卡）。
// v0.10.0 P1-13: #meta already sits below the search box in static HTML (no JS move => no CLS)
const acEl = document.getElementById('ac');
const ctryLabel = document.getElementById('ctrylabel');
// v0.6.3 U1：首屏引导关闭记忆（localStorage flag；隐私模式失败也不影响关闭）
const u1El = document.getElementById('u1guide');
const u1CloseEl = document.getElementById('u1close');
if(u1El && u1CloseEl){
  u1CloseEl.addEventListener('click', function(){
    try{ localStorage.setItem('u1.dismiss.v1', '1'); }catch(e){}
    u1El.hidden = true;
  });
}
// v0.8.2 task-116：搜索时收起首页「按大类浏览」（空查询/清空恢复）
function setCatsHidden(hide){
  const el = document.querySelector('.catquick');
  if(!el) return;
  el.classList.toggle('cat-hidden', !!hide);
  el.setAttribute('aria-hidden', hide ? 'true' : 'false');
}
// v0.6.2：繁体输入归一（OpenCC 常用字子集，构建期从 data/zh_hant_t2s.json 注入）。
// 只影响匹配前的归一化，不改变用户看到的输入/结果/页面文案。
const T2S = __T2S_JSON__;
function toSimp(s){
  if(!s || !T2S || !/[\u4e00-\u9fff]/.test(s)) return s;
  var out = '';
  for(var i=0;i<s.length;i++){ var c = s.charAt(i); out += (T2S[c] || c); }
  return out;
}
// 页面在 / 或 /es/ 或 /zh/ 下，资源与内容页都在站点根目录，按 app.js 的位置推根路径
const BASE = ((document.currentScript && document.currentScript.src) || location.href)
  .replace(/assets\/app\.js.*$/, '');
// 访问统计（GoatCounter，cookieless）。未配置 code 时页面不会注入脚本，这里静默无操作。
// 事件命名：search-<归一化词> / click-result / click-report / click-whatsnew / country-<US|…>。
function gcEvent(name){
  try{
    if(name && window.goatcounter && typeof window.goatcounter.count === 'function'){
      window.goatcounter.count({path: String(name).slice(0,120), event: true});
    }
  }catch(e){}
}
let SEARCH_SENT = [];
let SEARCH_SUBMIT_Q = '';
// v0.9.1 task-32：只在提交时记录一次搜索；同会话前缀合并；带 lang / q_len。
function trackSearchSubmit(q){
  const term = norm(splitDose(q)[0]);
  if(!term || term.length < 2) return;
  SEARCH_SUBMIT_Q = q;
  // 同会话内「盐酸」→「盐酸左旋西替利嗪」这类前缀中间态合并，避免逐字事件。
  for(const t of SEARCH_SENT){
    if(term.indexOf(t) === 0 || t.indexOf(term) === 0) return;
  }
  SEARCH_SENT.push(term);
  const lang = window.LANG || 'en';
  gcEvent('search-' + term.slice(0,40) + '?lang=' + encodeURIComponent(lang)
    + '&q_len=' + term.length);
}
// 保留旧函数名：render 内部不再上报，只有显式提交才走 trackSearchSubmit。
function scheduleSearchEvent(q){ return; }
// v0.8.2：零结果埋点（仅在提交查询后、确实零结果时发送；去重/≤64 字符）
let SEARCH0_EV = null, SEARCH0_SENT = new Set();
function scheduleSearch0(q){
  const term = norm(splitDose(q)[0]);
  if(!term || term.length < 2 || SEARCH0_SENT.has(term)) return;
  if(!SEARCH_SUBMIT_Q || norm(splitDose(SEARCH_SUBMIT_Q)[0]) !== term) return;
  clearTimeout(SEARCH0_EV);
  const box0 = document.getElementById('q');
  const want = box0 ? box0.value.trim() : '';
  SEARCH0_EV = setTimeout(()=>{
    const cur = document.getElementById('q');
    if(cur && cur.value.trim() !== want) return;
    if(SEARCH0_SENT.has(term)) return;
    SEARCH0_SENT.add(term);
    const lang = window.LANG || 'en';
    gcEvent('search0-' + term.slice(0,64) + '?lang=' + encodeURIComponent(lang)
      + '&q_len=' + term.length);
  }, 900);
}
let IDX = [], NICKS = [], CONF = [], CATS = null;
// v0.10.2：类别发现快车道（data/idx/cats.json + data/idx/cat-<id>.json + atc-ing.json）。
// 类别词 / ATC 码的首查不再等 core.json（41.5 MB raw / 9.9 MB gz）：先拉这 23 KB 的词表
// 和一份 30–57 KB 的切片出结果，core 在后台补全。产物由 site/build.py 构建期生成。
let CATX = null, CATX_P = null, ATCING = null, ATCING_P = null;
// 快车道已经渲染过结果：core 拉失败时保留切片视图（不把用户刚看到的结果换成错误框）。
let FAST_SHOWN = 0;
// 首屏这条路（快车道 → 分片）是否正在加载：acUpdate() 据此不抢跑 core。
let LANE_BUSY = false;
// 搜索增强（task-28）：运行时候选层 + 拼音表懒加载状态，见 collectHits()/pinyinFetch()。
let SEARCH_LAYERS = null, PY_MAP = null, PY_P = null;
// P2 分片（task-36）：manifest + 已加载分片池；分片先出结果，核心随后后台加载补全。
let MANIFEST = null, MANIFEST_P = null, SHARD_CACHE = new Map();
let POOL_READY = false, POOL_FILES = new Set(), SUPPORT_P = null, SHARD_P = null;
// P0 索引懒加载：页面加载时只下 app.js/css/i18n（约 16 KB），
// 全量索引（34.8 MB，gzip 约 6 MB）等用户真的要用搜索时再下。
let IDX_READY = false, IDX_P = null;
// ARTG 名称层：只在产品没命中时懒加载，避免每次搜索都多下 3 MB
let ARTG = null, artgLoading = false;
function artgPaint(nq){
  const box = document.getElementById('artgbox');
  if(!box || !ARTG) return;
  const T = window.T || (k=>k);
  const rows = ARTG.filter(r => r[0] === nq || r[0].startsWith(nq + ' '))
    .sort((a,b) => a[1].length - b[1].length).slice(0, 20);
  if(!rows.length){ box.innerHTML = ''; return; }
  const body = rows.map(r => `<tr><td data-label="${esc(T('col.brand'))}">${esc(r[1])}</td>
    <td data-label="${esc(T('artg.sponsor'))}">${esc(r[2]) || '—'}</td>
    <td data-label="${esc(T('artg.id'))}"><code>${esc(r[3])}</code></td></tr>`).join('');
  box.innerHTML = `<h2>${T('artg.title')}</h2><p class="sub">${T('artg.note')}</p>
    <table class="res"><thead><tr><th>${T('col.brand')}</th><th>${T('artg.sponsor')}</th>
    <th>${T('artg.id')}</th></tr></thead><tbody>${body}</tbody></table>`;
}
function artgFallback(nq){
  if(!nq || nq.length < 3 || !document.getElementById('artgbox')) return;
  if(ARTG){ artgPaint(nq); return; }
  if(artgLoading) return;
  artgLoading = true;
  fetch(BASE + 'data/artg.json').then(r => r.json()).then(d => {
    ARTG = d || []; artgLoading = false; artgPaint(nq);
  }).catch(() => { ARTG = []; artgLoading = false; });
}

function norm(s){
  return toSimp(s||'').normalize('NFKC').toLowerCase()
    .replace(/[®™©]/g,' ')
    .replace(/[\u0300-\u036f]/g,'')
    .replace(/\s+/g,' ').trim();
}
function splitDose(q){
  // 把「Lipitor 20mg」「两只青蛙 500mg」「875/125 mg」里的剂量切出来，
  // 名字部分才拿去和索引比对——不切的话带剂量的搜索会一个都命中不了。
  const ratio = q.match(/([\d.]+)\s*\/\s*([\d.]+)\s*(mg|mcg|µg|ug|g)\b/i);
  const single = q.match(/([\d.]+)\s*(mg|mcg|µg|ug|g|ml|iu|%|万单位)\b/i);
  const m = ratio || single;
  if(!m) return [q, null];
  const rest = (q.slice(0, m.index) + ' ' + q.slice(m.index + m[0].length))
    .replace(/\s+/g,' ').trim();
  return [rest, [m[1], (ratio ? m[3] : m[2]).toLowerCase()]];
}
function lev(a,b){
  if(Math.abs(a.length-b.length)>3) return 99;
  const d=Array.from({length:b.length+1},(_,i)=>i);
  for(let i=1;i<=a.length;i++){
    let prev=d[0]; d[0]=i;
    for(let j=1;j<=b.length;j++){
      const t=d[j];
      d[j]=Math.min(d[j]+1,d[j-1]+1,prev+(a[i-1]===b[j-1]?0:1));
      prev=t;
    }
  }
  return d[b.length];
}
function tier(nq,k){
  if(k===nq) return ['exact',1.0];
  if(k.replace(/ /g,'')===nq.replace(/ /g,'')) return ['compact',0.95];
  if(k.startsWith(nq)) return ['prefix',0.80];
  // 中文药名普遍很短：「利嗪」「头孢」「地平」这种两三个字就是有效线索，
  // 用英文的四字下限会把只记得一部分的人挡在门外。
  const cjk = /[\u4e00-\u9fff]/.test(nq);
  const minSub = cjk ? 2 : 4;
  if(nq.length>=minSub && k.includes(nq)) return ['contains',0.70];
  if(nq.length>=4 && lev(nq,k) <= (nq.length>=9 ? 3 : 2)) return ['fuzzy',0.55];
  return null;
}
function doseNum(s){ const m=(s||'').match(/[\d.]+/); return m?parseFloat(m[0]):0; }
// v0.6.4 A2：ATC 码/类前缀识别（C07 / C07A / C07AB02）。只接受字母开头+两位数字的形态，
// 不会把普通药名误判成 ATC；Dose 等后缀由 splitDose 先剥掉。
function atcQuery(raw){
  const s = String(raw || '').trim().toUpperCase();
  if(!/^[A-Z]\d{2}(?:[A-Z]{0,2}\d{0,2})?$/.test(s)) return '';
  return s.length >= 3 ? s : '';
}
function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
// v0.5.5：中文界面优先用索引里的中文成分名（xz 与 x 的 " + " 分段平行，
// 缺失/空串逐段回退英文；其它语言仍用英文 x）。
function ingredientLabel(e){
  const x = (e && (e.x || e.d)) || '—';
  // v0.8.2 task-120：优先当前语言译名（terms.json 由 bilingual.js 暴露；无则保留原名）
  if(window.LANG && window.LANG !== 'en' && window.BILINGUAL_TERMS
     && window.BILINGUAL_TERMS.sub && e && e.v){
    const ent = window.BILINGUAL_TERMS.sub[e.v];
    const tr = ent && ent[window.LANG];
    if(tr && tr.n) return tr.n;
  }
  // v0.11.5 task-71：中文/繁体界面优先用索引里的中文成分名（e.xz）；
  // 英文 INN 作为 name key 时 xz 可能缺失，由服务端从 substance.inn_zh 回填。
  const zhNames = (e && Array.isArray(e.xz)) ? e.xz.filter(function(z){
    return z && String(z).trim();
  }) : [];
  if((window.LANG === 'zh' || window.LANG === 'zh-Hant') && zhNames.length){
    const parts = String(x).split(' + ');
    if(zhNames.length === parts.length){
      return parts.map(function(p, i){
        return (zhNames[i] && String(zhNames[i]).trim()) ? zhNames[i] : p;
      }).join(' + ');
    }
    return zhNames.join(' + ');
  }
  return x;
}
// v0.5.3 点击目标规则（用户报 Excedrin 点品牌跳到 acetaminophen 页）：
//   品牌列 → name/<u>.html；没有品牌页就渲染成不可点文本，**绝不回退 drug 页**。
//   成分列 → 复方（索引 cu 字段）进 /combo/<slug>.html；单成分进 drug/<v>.html。
function brandHTML(e, withFormHint){
  let d = e && e.d != null ? String(e.d) : '';
  const T = window.T || (k=>k);
  if(e && e.t !== 1){
    // v0.9.0 task-19：没有 trade 名 → 商品名位置只显示「无商品名」纯文本，
    // 不链接、不放厂家；通用名/剂型作小字说明。
    const hint = [e.x || '',
                  // T10：e.f 可能是 "multi"（多剂型）→ 走 formLabelOf，显示「多剂型」而不是 `multi`
                  (withFormHint === false ? '' : formLabelOf(e))]
      .filter(Boolean).join(' · ');
    const matched = e.d ? ` <span class="match-name" title="${esc(T('res.matched_name'))}">`
      + `${esc(T('res.matched_name'))}: ${esc(e.d)}</span>` : '';
    // v0.10.2 task-10：CN 无商品名的产品 100% 有上市许可持有人 → 名称位显示「厂家：<MAH>」。
    // 只显示：厂家名不进 name_key / 索引，也不生成厂家页（避免假商品名污染检索）。
    // 2026-11-13 task-28（用户截图）：**不限国家** —— 任何国家只要无 trade 名且有 e.m，
    // 名称位都显示「厂家：<MAH>」；e.m 为空才回退「无商品名」。截断/title/样式沿用。
    // 2026-11-13 task-31：`withFormHint=false` 时 hint 只留成分（结果表把剂型移到剂量列，
    // 避免「Zopiclone · 片剂」+ 下一行「片剂」重复）。
    const mah = String(e.m || '').trim();
    if(mah){
      const short = mah.length > 28 ? mah.slice(0, 27) + '…' : mah;
      return `<span data-brand="0" class="m-brand m-mah" title="${esc(mah)}">`
        + `<span class="mah-k">${esc(T('brand.mah'))}</span> ${esc(short)}</span>`
        + matched + (hint ? ` <span class="m-none-ing">${esc(hint)}</span>` : '');
    }
    return `<span data-brand="0" class="st-badge st-unknown brand-none">${esc(T('brand.none'))}</span>`
      + matched + (hint ? ` <span class="m-none-ing">${esc(hint)}</span>` : '');
  }
  if(e && e.f){
    const f = labelOf('form', e.f, '');
    if(f && d.length > f.length && d.slice(-f.length) === f) d = d.slice(0, -f.length).trim();
  }
  const title = e && e.d != null ? e.d : '';
  if(e && e.u) return `<a data-brand="1" title="${esc(title)}" href="${BASE}name/${e.u}">${esc(d)}</a>`;
  return `<span data-brand="1" title="${esc(title)}" class="brand-plain">${esc(d)}</span>`;
}
function ingredientHTML(e, cls){
  const T = window.T || (k=>k);
  if(e && e.nc){
    return `<span class="st-badge st-unknown" data-i18n="ingredient.unrecorded">${esc(T('ingredient.unrecorded'))}</span>`;
  }
  const label = ingredientLabel(e);
  const orig = (e && (e.x || e.d)) || '';
  const cjk = /[\u3400-\u9fff]/.test(orig);
  const hasZh = !!(e && Array.isArray(e.xz)
    && e.xz.some(function(z){ return z && String(z).trim(); }));
  let badge = '';
  if(hasZh && (window.LANG === 'zh' || window.LANG === 'zh-Hant')){
    // v0.11.5 task-71：有中文成分名就绝不判「无中文名」。
    badge = '';
  }else if(cjk && (window.LANG === 'en' || window.LANG === 'es')){
    badge = ` <span class="st-badge st-unknown nolang-badge">${esc(T(window.LANG === 'en' ? 'name.no_en' : 'name.no_es'))}</span>`;
  }else if(!cjk && (window.LANG === 'zh' || window.LANG === 'zh-Hant')){
    badge = ` <span class="st-badge st-unknown nolang-badge">${esc(T(window.LANG === 'zh' ? 'name.no_zh' : 'name.no_zh_hant'))}</span>`;
  }
  if(e.cu) return `<a class="${cls || ''}" href="${BASE}${e.cu}">${label}</a>${badge}`;
  if(e.v) return `<a class="${cls || ''}" data-sub-ingredient="${esc(e.v)}" data-sub-orig="${esc(orig)}" href="${BASE}drug/${e.v}.html">${label}</a>${badge}`;
  return `<span class="${cls || ''}">${label}</span>${badge}`;
}
// v0.5.4 厂家列：第一个厂家可点（索引 mu），「+N」展开其它带页厂家（索引 ml）；
// 没页的厂家显示为纯文本 / 汇总成「另有 K 家暂无页面」，绝不产生 404。
function makerHTML(e, T){
  const name = e && e.m ? e.m : '';
  if(!name) return '—';
  const first = e.mu
    ? `<a class="maker-link" href="${BASE}maker/${e.mu}.html">${esc(name)}</a>`
    : `<span class="maker-plain">${esc(name)}</span>`;
  const extraTotal = (e.mn || 1) - 1;
  if(extraTotal <= 0) return first;
  const extras = (e.ml && e.ml.length) ? e.ml : [];
  const items = extras.map(([n, s]) =>
    `<li><a class="maker-link" href="${BASE}maker/${s}.html">${esc(n)}</a></li>`).join('');
  const unlinked = extraTotal - extras.length;
  const tail = unlinked > 0
    ? `<li class="sub">${esc(T('maker.no_page_count').replace('{n}', String(unlinked)))}</li>`
    : '';
  return `<span class="mah-wrap">${first}`
    + `<button type="button" class="linkbtn mah-toggle" data-mah="1" aria-expanded="false">+${extraTotal}</button>`
    + `<ul class="mah-list" hidden>${items}${tail}</ul></span>`;
}
function _flatAccents(s){
  // 西语别名里的 é/í/ó 是预组合字符，norm() 只删组合标记，这里再按 NFKD 折一次；
  // 只影响匹配（Bromelaina 也能命中 Bromelaína），显示名仍保留原写法。
  return String(s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
}
function aliasHits(nq){
  // 俗称只做精确 / 连写命中：昵称差一个字往往就是另一个梗，模糊匹配会闹笑话。
  // task-141c：同物异名（成分别名）也走这里，额外容忍重音差异。
  const fq = _flatAccents(nq);
  return NICKS.filter(a => a.n === nq || a.n.replace(/ /g,'') === nq.replace(/ /g,'')
    || _flatAccents(a.n).replace(/ /g,'') === fq.replace(/ /g,''));
}
function confHits(nq){
  // 易混淆药对也只做精确命中：这是「名字像」的提示，不做模糊扩展。
  return CONF.filter(p => p.n === nq);
}
// ── UI P0 ③④：自动完成 / 解析条 / 成分分组 + 品牌折叠 + 加载更多 ──────
// 一条「品牌行」= 一个索引条目（同成分下的一个品牌/写法），剂量合并展示，
// 不再按每个规格各占一行；分组头显示成分与品牌数。
// ── v0.5.6：A3 盐型/释放上下文 + B6 行级报告 + A1 明细桶 + B7 导出 ─────────
function a3HintHTML(e, T){
  // 不可互换只来自已发布 dose_warning（R1/R2）；多盐型只做中性提示，不写结论。
  const bits = [];
  if(e.wi) bits.push(`<a class="ctx warn" href="${BASE}warn.html#w-${esc(e.wi)}">${esc(T('a3.incompat'))}</a>`);
  if(e.sl) bits.push(`<span class="ctx" title="${esc(e.sl)}">${esc(T('a3.salt'))} ${esc(e.sl)}</span>`);
  if(e.rl) bits.push(`<span class="ctx">${esc(T('a3.release'))} ${esc(e.rl)}</span>`);
  return bits.length ? ` <span class="ctxwrap">${bits.join(' ')}</span>` : '';
}
function rowReportURL(e){
  // 行级报告：不带 template=（GitHub issue form 会忽略 URL 的 body 预填），
  // 用空白 issue + body 按表单字段顺序；只带查询词/当前页面/行信息，无隐私数据。
  const q = (box && box.value ? box.value : '').trim();
  const page = location.href.split('#')[0];
  const body = [
    '**' + Tr('report.field_query') + '**: ' + q,
    '**' + Tr('report.field_page') + '**: ' + page,
    '**' + Tr('report.field_row') + '**: ' + (e.d || '') + ' · ' + (e.x || '') +
      ' · ' + ((e.c || []).join(', ')),
    '**' + Tr('report.field_expected') + '**: ',
    '**' + Tr('report.field_actual') + '**: ',
    '**' + Tr('report.field_pack') + '**: ',
  ].join('\n');
  return 'REPORT_REPO_PLACEHOLDER' + '/issues/new?labels=data-error'
    + '&title=' + encodeURIComponent(Tr('report.issue_title') + (q || e.d || ''))
    + '&body=' + encodeURIComponent(body);
}
function detBucketOf(e){ return (e && e.db) ? e.db : 'other'; }
function loadDetailBucket(bucket){
  // 懒加载：只在用户点「详情」时拉一个桶（v0.11.0 实测最大 detail-a.json ~5.7 MB raw / ~1.2 MB gzip），并缓存。
  if(DET_CACHE.has(bucket)) return Promise.resolve(DET_CACHE.get(bucket));
  return fetchManifest().catch(()=>null).then(m => {
    const ver = (m && m.v) ? '?v=' + m.v : '';
    return fetchJSON(BASE + 'data/idx/detail-' + bucket + '.json' + ver);
  }).then(d => { DET_CACHE.set(bucket, d || {}); return d || {}; })
    .catch(() => { DET_CACHE.set(bucket, {}); return {}; });
}
function findEntryByKey(k){
  if(!RES_GROUPS) return null;
  for(const g of RES_GROUPS) for(const e of g.rows) if(e.k === k) return e;
  return null;
}
function labelOf(prefix, code, fallback){
  // v0.6.3 U3：受控词走 i18n key，未注册的长尾值原样显示（返回 fallback/code）。
  const c = (code == null ? '' : String(code));
  const k = prefix + '.' + c;
  const v = Tr(k);
  return (v === k) ? (fallback != null ? fallback : c) : v;
}
function detPanelHTML(payload, key, e, T){
  const rows = (payload && payload.k && payload.k[key]) || [];
  if(!rows.length){
    return `<span class="sub">${esc(T('a1.none'))}</span> `
      + (e && e.v ? `<a href="${BASE}drug/${encodeURIComponent(e.v)}.html">${esc(T('a1.goto'))}</a>` : '');
  }
  const body = rows.map(r => {
    const raw = (payload.p && payload.p[r[11]] != null) ? String(payload.p[r[11]]) : '';
    const url = raw + (r[10] || '');
    const status = (payload.t && payload.t[r[5]]) || r[5];
    const rel = (payload.r && payload.r[r[7]]) || '';
    const src = (payload.s && payload.s[r[11]]) || '';
    const strength = r[8] ? ' · ' + esc(r[8]) : '';
    // v0.11.2 P0-2：下标来自 ROW_FIELDS（构建期注入），别再手写数字。
    // 其它列（country=1 / approval=4 / status=5 / release=7 / strength=8 / mah=9 /
    // source_url=10 / source_idx=11）仍按 ROW_FIELDS 的既有契约读取。
    const brandCell = r[DETAIL_COL.brand] ? esc(r[DETAIL_COL.brand]) : esc(T('brand.none'));
    const exp = (EXPORT_ONLY && EXPORT_ONLY.has(r[0]))
      ? ` <span class="badge export">${esc(T('badge.export_only'))}</span>` : '';
    return `<tr><td>${esc(r[1])}</td><td>${brandCell}${exp}</td>`
      + `<td>${esc(r[DETAIL_COL.pack]) || '—'}${strength}</td>`
      + `<td><code>${esc(r[4]) || '—'}</code></td>`
      + `<td><span class="st-badge st-${esc(status)}">${esc(labelOf('drug.status', status, status))}</span>${r[6] ? ' · ' + esc(r[6]) : ''}${rel && rel !== 'none' ? ' · ' + esc(labelOf('release', rel, rel)) : ''}</td>`
      + `<td>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(src || T('a1.raw'))} ↗</a>` : '—'}</td>`
      + `<td>${makerLinkHTML(r[9], T)}</td></tr>`;
  }).join('');
  // 2026-11-13 task-34（用户截图）：明细面板底部「全部见成分页」要可点。
  // a1.more 四语文案里已带 <a href="{url}">；这里注入当前条目的成分页 URL。
  // e.v 为空（名称层/复方无单一成分）时退回纯文本，绝不输出占位符。
  let moreHTML = '';
  if(rows.length >= 12){
    const tpl = T('a1.more');
    if(e && e.v){
      const drugUrl = BASE + 'drug/' + encodeURIComponent(e.v) + '.html';
      moreHTML = `<p class="sub">${tpl.replace(/\{url\}/g, esc(drugUrl))}</p>`;
    }else{
      moreHTML = '<p class="sub">'
        + esc(tpl.replace(/<[^>]+>/g, '').replace(/\{url\}/g, '')) + '</p>';
    }
  }
  return `<table class="det"><thead><tr><th>${esc(T('a1.market'))}</th><th>${esc(T('col.brand'))}</th>`
    + `<th>${esc(T('a1.pack'))}</th><th>${esc(T('a1.approval'))}</th><th>${esc(T('a1.status'))}</th>`
    + `<th>${esc(T('a1.source'))}</th><th>${esc(T('col.mah'))}</th></tr></thead><tbody>${body}</tbody></table>`
    + moreHTML;
}
// B7：导出当前视图全部结果（含折叠/未加载更多的行），纯前端。
function exportRows(){
  const src = (LAST_DISPLAY && LAST_DISPLAY.length) ? LAST_DISPLAY : [];
  const out = [];
  for(const [, tier, e] of src){
    const link = e.u ? (BASE + 'name/' + e.u)
      : (e.v ? (BASE + 'drug/' + encodeURIComponent(e.v) + '.html') : '');
    out.push([e.x || e.d || '', e.d || '', (e.s || []).join(' / '),
              (e.c || []).join(', '), e.f || '', e.m || '', tier || '', link]);
  }
  return out;
}
function csvCell(v){
  const s = String(v == null ? '' : v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function toCSV(rows){ return '\ufeff' + rows.map(r => r.map(csvCell).join(',')).join('\r\n'); }
function toTSV(rows){ return rows.map(r => r.map(v => String(v == null ? '' : v)
  .replace(/[\t\r\n]/g, ' ')).join('\t')).join('\n'); }
function exportHeader(T){
  return [T('col.ing'), T('col.brand'), T('col.dose'), T('res.col_country'),
          T('res.col_form'), T('col.mah'), T('res.col_match'), T('res.col_link')];
}
function exportNote(msg){
  const el = document.getElementById('exportnote');
  if(!el) return;
  el.textContent = msg || '';
  if(msg) setTimeout(() => { if(el.textContent === msg) el.textContent = ''; }, 2500);
}
function downloadCSV(rows, T){
  const text = toCSV([exportHeader(T)].concat(rows));
  const blob = new Blob([text], {type: 'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  const d = new Date().toISOString().slice(0, 10);
  a.href = URL.createObjectURL(blob);
  a.download = 'drug-crossref-' + d + '.csv';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function fallbackCopy(text){
  const ta = document.createElement('textarea');
  ta.value = text; ta.setAttribute('readonly', '');
  ta.style.position = 'fixed'; ta.style.left = '-9999px'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch(e) { ok = false; }
  ta.remove();
  return ok;
}
function copyTSV(rows, T){
  const text = toTSV([exportHeader(T)].concat(rows));
  const done = ok => exportNote(ok ? T('res.copied') : T('res.copy_fail'));
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(() => done(true)).catch(() => done(fallbackCopy(text)));
  } else {
    done(fallbackCopy(text));
  }
}
function brandRowHTML(e, T){
  const badge = e.l==='severe' ? `<span class="badge sev">${T('badge.severe')}</span>` :
                e.l==='warning' ? `<span class="badge warn">${T('badge.warning')}</span>` : '';
  const tags = (e.c || []).map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
  const combo = (e.x || '').indexOf(' + ') >= 0
    ? `<span class="tag combo">${T('badge.combo')}</span>` : '';
  const exp = e.eo ? `<span class="badge export">${T('badge.export_only')}</span>` : '';
  const mah = makerHTML(e, T);
  const ds = (e.s && e.s.length) ? e.s.slice().sort((a,b)=>doseNum(a)-doseNum(b)) : [''];
  // v0.5.6：A3 上下文徽章、B6 行级报告、A1 明细展开按钮（e.n 条产品记录）
  const ctx = a3HintHTML(e, T);
  const det = (e.n ? `<button type="button" class="linkbtn detbtn" data-det="${esc(e.k)}" `
    + `aria-expanded="false">${esc(T('a1.expand'))}</button>` : '');
  // T11（v0.11.7）B1 第 2 步：行内「这条」——点击后把这行记成「你手里这条」，候选集不变。
  // 用**一个字符**的按钮（title/aria 带完整文案）：`.c-det` 列很窄，放整句会把行高
  // 从 42 撑到 138px，1440 首屏条目会从 4.5 掉到 1.5（首屏守卫的硬指标）。
  const pickBtn = `<button type="button" class="linkbtn pickbtn" data-pick="${esc(e.k)}|${esc((e.c && e.c[0]) || '')}" title="${esc(T('t11.pick_this'))}" aria-label="${esc(T('t11.pick_this'))}">◎</button> `;
  const rep = `<a class="rowreport" href="${esc(rowReportURL(e))}" target="_blank"`
    + ` rel="noopener" title="${esc(T('row.report'))}" aria-label="${esc(T('row.report'))}">⚑</a>`;
  return `<tr class="br" data-k="${esc(e.k)}">
    <td class="c-ing c-empty"></td>
    <td class="c-dose" data-label="${esc(T('col.dose'))}">${(function(){
      // T10：分组表（ATC/大类结果）同样按「剂型 + 规格」成对出，不再只拼规格
      const g = specPairsOf(e, 3);
      if(!g.hasFs) return esc(ds.join(' / ')) || '—';
      const bits = g.pairs.map(x => {
        const tx = esc(x.specs.join(' / '));
        return x.form ? `<span class="form-tag">${esc(x.form)}</span> ${tx}` : tx;
      });
      return bits.join(' · ') + (g.restGroups
        ? ` <span class="meta">+${g.restGroups} ${esc(T('matrix.multi_form'))}</span>` : '');
    })()}</td>
    <td class="c-brand" data-label="${esc(T('col.brand'))}">${brandHTML(e)}${tags}${combo}${exp}${badge}${ctx}${det}${rep}</td>
    <td class="c-mah" data-label="${esc(T('col.mah'))}">${mah || '—'}</td></tr>`;
}
// v0.10.2 M-4：手机上一条结果就是一张卡（≈190–220px），20 条要滚 5 屏多；
// 移动端首屏分页取 10（桌面仍是 20），「显示更多」每次仍按 RES_PAGE 增量。
const RES_PAGE = (window.matchMedia && window.matchMedia('(max-width:767px)').matches) ? 10 : 20;
let RES_LIMIT = RES_PAGE;
let RES_MODE = 'grouped';         // 'flat' = 普通查询的扁平表；'grouped' = ATC/大类结果（保持原样）
let RES_EXPANDED = new Set();     // 已展开的分组下标
let RES_GROUPS = null;            // [{ing, tags:Set, rows:[entry]}]
let LAST_DISPLAY = [];            // v0.5.6 B7：当前视图全部命中（[score,tier,entry]）
const DET_CACHE = new Map();      // v0.5.6 A1：明细桶缓存（bucket → payload）
// v0.9.0 task-20：明细面板的厂家名 → 厂家页 slug（懒加载一次；18k 条不进结果索引）
let MAKER_MAP = null;
function loadMakerMap(){
  if(MAKER_MAP) return Promise.resolve(MAKER_MAP);
  return fetchJSON(BASE + 'data/maker-map.json').then(m => { MAKER_MAP = m || {}; return MAKER_MAP; })
    .catch(() => { MAKER_MAP = {}; return MAKER_MAP; });
}
function makerLinkHTML(name, T){
  if(!name) return '—';
  const slug = MAKER_MAP && MAKER_MAP[name];
  if(slug){
    return `<a class="maker-link" href="${BASE}maker/${esc(slug)}.html">${esc(name)}</a>`;
  }
  return `<span class="maker-plain">${esc(name)}</span>`;
}
// v0.9.1 task-28：Export Only 产品 ID 集合（明细用；结果行已带 eo 标记）
let EXPORT_ONLY = null;
function loadExportOnly(){
  if(EXPORT_ONLY) return Promise.resolve(EXPORT_ONLY);
  return fetchJSON(BASE + 'data/export-only.json').then(a => {
    EXPORT_ONLY = new Set(a || []); return EXPORT_ONLY;
  }).catch(() => { EXPORT_ONLY = new Set(); return EXPORT_ONLY; });
}
function groupByIngredient(display){
  const order=[], map=new Map();
  for(const [, t, e] of display){
    const key = e.x || e.d || e.k;
    let g = map.get(key);
    if(!g){ g = {ing: e.x || e.d, tags:new Set(), rows:[], tier:t}; map.set(key, g); order.push(g); }
    (e.c || []).forEach(c => g.tags.add(c));
    g.rows.push(e);
  }
  return order;
}
function resultsHTML(T){
  if(!RES_GROUPS || !RES_GROUPS.length) return '';
  // 可见行数 = 展开组用全部品牌、折叠组只算前 2 个；「加载更多」按可见行分页，
  // 展开某个成分（品牌折叠）后才把该组的全部品牌计入分页。
  const visibleTotal = RES_GROUPS.reduce((n, g, gi) =>
    n + (RES_EXPANDED.has(gi) ? g.rows.length : Math.min(2, g.rows.length)), 0);
  let html='', count=0, cut=false;
  for(let gi=0; gi<RES_GROUPS.length; gi++){
    const g = RES_GROUPS[gi];
    if(count >= RES_LIMIT){ cut = true; break; }
    const expanded = RES_EXPANDED.has(gi);
    const vis = expanded ? g.rows : g.rows.slice(0, 2);
    const tags = [...g.tags].sort().map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
    html += `<tr class="grp"><td class="c-ing">${ingredientHTML(g.rows[0], 'grp-name')}`
      + `<span class="grp-count">${g.rows.length} ${esc(T('res.records_noun'))}</span></td>`
      + `<td colspan="3" class="grp-tags">${tags}</td></tr>`;
    for(let i=0; i<vis.length; i++){
      if(count >= RES_LIMIT){ cut = true; break; }
      html += brandRowHTML(vis[i], T); count++;
    }
    if(g.rows.length > vis.length){
      html += `<tr class="fold-row"><td colspan="4"><button type="button" class="linkbtn"`
        + ` data-gi="${gi}" data-fold="1">${esc(T('res.show_brands'))}`
        + ` +${g.rows.length - vis.length}</button></td></tr>`;
    } else if(expanded && g.rows.length > 2){
      html += `<tr class="fold-row"><td colspan="4"><button type="button" class="linkbtn"`
        + ` data-gi="${gi}" data-fold="0">${esc(T('res.fold'))}</button></td></tr>`;
    }
    if(cut) break;
  }
  if(count < visibleTotal){
    html += `<tr class="fold-row"><td colspan="4"><button type="button" class="linkbtn"`
      + ` data-loadmore="1">${esc(T('res.load_more'))}`
      + ` (+${Math.min(RES_PAGE, visibleTotal-count)})</button></td></tr>`;
  } else if(visibleTotal > RES_PAGE){
    html += `<tr class="fold-row"><td colspan="4"><span class="sub">`
      + `${esc(T('res.loaded_all'))}</span></td></tr>`;
  }
  return html;
}
function resultsTableHTML(T){
  return `<table class="res grouped"><thead><tr>
      <th>${T('col.ing')}</th><th>${T('col.dose')}</th>
      <th>${T('col.brand')}</th><th>${T('col.mah')}</th>
    </tr></thead><tbody>${resultsHTML(T)}</tbody></table>`;
}
// ── v0.9.7 task-12：普通结果 = 扁平表（规格 / 品牌(注册名) / 市场 / 详情）+ 「显示更多」──
// 只保留四列、默认 20 行；行按原命中顺序（不加排序/推荐）。ATC、大类结果仍走分组表。
function formLabelOf(e){
  const f = (e && e.f) ? String(e.f) : '';
  // T10（plan §3.4 ④）：多剂型时索引把 f 置为 "multi"，标签走 matrix.multi_form，
  // 不再用第一个剂型代表整个名字（「500 mg / 960 mg · 片剂」的根因之一）。
  if(f === 'multi') return window.T ? window.T('matrix.multi_form') : 'Multi-form';
  return f ? labelOf('form', f, f) : '';
}
// T10（plan §3.4 ④ / §7-A、B）：把 e.fs（紧凑串 `剂型|规格;规格`）渲染成
// 「片剂 500 mg · 液体 960 mg/30 mL」。旧索引 / 单剂型条目没有 fs → 回退到 e.s + e.f。
function specPairsOf(e, maxGroups){
  const fs = (e && Array.isArray(e.fs)) ? e.fs.filter(s => typeof s === 'string' && s) : [];
  const n = maxGroups || 3;
  const parsed = fs.map(s => {
    const i = s.indexOf('|');
    const fm = i >= 0 ? s.slice(0, i) : '';
    const specs = (i >= 0 ? s.slice(i + 1) : s).split(';').filter(Boolean);
    return { form: fm ? labelOf('form', fm, fm) : '', specs: specs.slice(0, 2) };
  });
  return { pairs: parsed.slice(0, n), restGroups: Math.max(0, parsed.length - n), hasFs: parsed.length > 0 };
}
function marketTags(list, max){
  const cs = [];
  for(const c of (list || [])) if(c && cs.indexOf(c) < 0) cs.push(c);
  cs.sort();
  const n = max || 6;
  const head = cs.slice(0, n)
    .map(c => `<span class="tag ${String(c).toLowerCase()}">${esc(c)}</span>`).join('');
  return head + (cs.length > n ? ` <span class="meta">+${cs.length - n}</span>` : '');
}
function flatRowHTML(e, T){
  const ds = (e.s && e.s.length) ? e.s.slice().sort((a,b)=>doseNum(a)-doseNum(b)) : [];
  // T11（v0.11.7）B1 第 2 步：行内「这条」——点击后把这行记成「你手里这条」，候选集不变。
  // 用**一个字符**的按钮（title/aria 带完整文案）：`.c-det` 列很窄，放整句会把行高
  // 从 42 撑到 138px，1440 首屏条目会从 4.5 掉到 1.5（首屏守卫的硬指标）。
  const pickBtn = `<button type="button" class="linkbtn pickbtn" data-pick="${esc(e.k)}|${esc((e.c && e.c[0]) || '')}" title="${esc(T('t11.pick_this'))}" aria-label="${esc(T('t11.pick_this'))}">◎</button> `;
  const badge = e.l==='severe' ? `<span class="badge sev">${esc(T('badge.severe'))}</span>` :
                e.l==='warning' ? `<span class="badge warn">${esc(T('badge.warning'))}</span>` : '';
  const combo = (e.x || '').indexOf(' + ') >= 0
    ? `<span class="tag combo">${esc(T('badge.combo'))}</span>` : '';
  const exp = e.eo ? `<span class="badge export">${esc(T('badge.export_only'))}</span>` : '';
  // 2026-11-13 task-31（用户截图）：剂型从品牌列移到「剂量」列并突出显示，
  // 品牌列不再追加 .rowform —— 否则无商品名行会「Zopiclone · 片剂」+「片剂」出现两次。
  const form = formLabelOf(e);
  const rel = (e.rl && e.rl !== 'none') ? ' · ' + labelOf('release', e.rl, e.rl) : '';
  // T10（plan §7-A）：有 fs 就出「剂型 + 规格」成对（片剂 500 mg · 液体 960 mg/30 mL），
  // 多出来的剂型用「+N 多剂型」；没有 fs（旧索引）才回退到旧的「规格 / 剂型」写法。
  const sp = specPairsOf(e, 3);
  let doseCell;
  if(sp.hasFs){
    const bits = sp.pairs.map(g => {
      const tx = esc(g.specs.join(' / '));
      return g.form ? `<span class="form-tag">${esc(g.form)}</span> ${tx}` : tx;
    });
    const moreG = sp.restGroups
      ? ` <span class="meta">+${sp.restGroups} ${esc(T('matrix.multi_form'))}</span>` : '';
    doseCell = bits.join(' · ') + moreG + (rel ? rel : '');
  } else {
    const formTag = form ? `<span class="form-tag">${esc(form + rel)}</span>` : '';
    const doseTxt = ds.length ? esc(ds.join(' / ')) : '';
    doseCell = doseTxt ? (doseTxt + (formTag ? ' ' + formTag : '')) : (formTag || '—');
  }
  let det;
  if(e.n){
    det = `<button type="button" class="linkbtn detbtn" data-det="${esc(e.k)}"`
      + ` aria-expanded="false">${esc(T('res.details'))}</button>`;
  } else if(e.u){
    det = `<a href="${BASE}name/${esc(e.u)}">${esc(T('res.details'))}</a>`;
  } else if(e.v){
    det = `<a href="${BASE}drug/${encodeURIComponent(e.v)}.html">${esc(T('res.details'))}</a>`;
  } else {
    det = '—';
  }
  return `<tr class="br" data-k="${esc(e.k)}">
    <td class="c-dose" data-label="${esc(T('col.dose'))}">${doseCell}</td>
    <td class="c-brand" data-label="${esc(T('col.brand'))}">${brandHTML(e, false)}${badge}${combo}${exp}</td>
    <td class="c-market" data-label="${esc(T('res.col_market'))}">${marketTags(e.c, 4) || '—'}</td>
    <td class="c-det">${pickBtn}${det}</td></tr>`;
}
function flatTableHTML(T){
  const disp = (LAST_DISPLAY && LAST_DISPLAY.length) ? LAST_DISPLAY : [];
  const total = disp.length;
  if(!total) return '';
  const shown = Math.min(RES_LIMIT, total);
  const body = disp.slice(0, shown).map(x => flatRowHTML(x[2], T)).join('');
  const count = T('res.showing').replace('{n}', String(shown)).replace('{total}', String(total));
  const more = shown < total
    ? `<button type="button" data-loadmore="1">${esc(T('res.load_more'))}`
      + ` (+${Math.min(RES_PAGE, total - shown)})</button>`
    : '';
  return `<table class="res rows"><thead><tr>
      <th>${esc(T('col.dose'))}</th><th>${esc(T('col.brand'))}</th>
      <th>${esc(T('res.col_market'))}</th><th>${esc(T('res.details'))}</th>
    </tr></thead><tbody>${body}</tbody></table>`
    + `<div class="res-more"><span class="sub">${esc(count)}</span>${more}</div>`;
}
function paintResultsOnly(){
  const wrap = document.getElementById('reswrap');
  if(!wrap) return;
  const T = window.T || (k=>k);
  if(RES_MODE === 'flat'){ wrap.innerHTML = flatTableHTML(T); return; }
  if(!RES_GROUPS) return;
  wrap.innerHTML = resultsTableHTML(T);
}
// ── v0.9.7 task-12：H1 / 骨架 / 身份卡 / 零结果三动作 / 复制标准名 ──────────
function setH1(text, key){
  if(!h1El) return;
  if(key){
    h1El.setAttribute('data-i18n', key);
    h1El.textContent = (window.T || function(k){ return k; })(key);
  } else {
    h1El.removeAttribute('data-i18n');
    h1El.textContent = text || H1_DEFAULT;
  }
  document.title = (text || H1_DEFAULT) + ' · Medicine Brand Cross-Reference';
}
function skeletonHTML(T){
  // P0-12：首搜用 3 行骨架占位（无 JS 时页面仍是静态首页，不受影响）
  return '<div class="res-skeleton" aria-hidden="true">'
    + '<div class="sk-row"></div><div class="sk-row"></div><div class="sk-row"></div>'
    + '</div><p class="sub">' + esc(T('home.loading')) + '</p>';
}
function suggestNames(nq, limit){
  // 零结果改写法建议：在已加载的索引里找编辑距离最近的 3 个名字（只读，不改结果）。
  // 找不到（乱敲的串/只加载了少量分片）时退回页面自带的 3 个示例名，保证动作永远可点。
  const res = [], seen = new Set();
  const push = v => { const s = String(v || '').trim(); if(!s || seen.has(s)) return; seen.add(s); res.push(s); };
  if(nq && IDX && IDX.length){
    const first = nq.charAt(0), cand = [];
    for(let i = 0; i < IDX.length; i++){
      const e = IDX[i], k = e && e.k;
      if(!k || !e.d || k.charAt(0) !== first) continue;
      if(Math.abs(k.length - nq.length) > 3) continue;
      const d = lev(nq, k);
      if(d <= 3) cand.push([d, e.d, k]);
    }
    cand.sort((a, b) => a[0] - b[0] || a[2].length - b[2].length);
    for(const c of cand){
      push(c[1]);
      if(res.length >= (limit || 3)) break;
    }
  }
  if(res.length < (limit || 3)){
    document.querySelectorAll('.u1try [data-q]').forEach(b => {
      if(res.length < (limit || 3)) push(b.getAttribute('data-q'));
    });
  }
  return res;
}
// v0.11.2（条目 9/10）：窄屏（390）判定——身份卡折成紧凑头、结果区上方说明可折叠。
function compactUI(){
  try{ return !!(window.matchMedia && matchMedia('(max-width:600px)').matches); }catch(e){ return false; }
}
function identityCardHTML(q, display, nicks, confs, T){
  if(!display || !display.length) return '';
  let first = null;
  for(const item of display){
    const e = item[2];
    if(e && (e.x || e.d)){ first = e; break; }
  }
  if(!first) return '';
  const ing = ingredientLabel(first);
  const zhName = (first.xz && first.xz.length) ? first.xz.join(' + ') : '';
  const other = (window.LANG === 'zh' || window.LANG === 'zh-Hant')
    ? (first.x || '') : zhName;
  const ingLine = `<span class="iding">${esc(ing)}</span>`;  let severe = !!(confs && confs.length) || first.l === 'severe';
  for(const item of display){ if(item[2] && item[2].l === 'severe'){ severe = true; break; } }
  const badge = severe ? ` <span class="idbadge">${esc(T('res.same_name'))}</span>` : '';
  const strengths = [];
  for(const s of (first.s || [])){ if(s && strengths.indexOf(s) < 0) strengths.push(s); }
  if(!strengths.length){
    for(const item of display.slice(0, 8)){
      for(const s of (item[2].s || [])){ if(s && strengths.indexOf(s) < 0) strengths.push(s); }
      if(strengths.length >= 3) break;
    }
  }
  const markets = [];
  for(const item of display) for(const c of (item[2].c || [])) if(c && markets.indexOf(c) < 0) markets.push(c);
  let recs = 0;
  for(const item of display) recs += (item[2].n || 1);
  const form = formLabelOf(first);
  const fields = [];
  // T10（plan §7-B）：身份卡也按「剂型 + 规格」成对给出；多剂型时写明「多剂型：片剂 / 液体…」
  const sp = specPairsOf(first, 3);
  if(sp.hasFs){
    const doseBits = sp.pairs.map(g => {
      const tx = esc(g.specs.join(' / '));
      return g.form ? `${esc(g.form)} ${tx}` : tx;
    });
    const moreG = sp.restGroups ? ` +${sp.restGroups}` : '';
    fields.push(`<span>${esc(T('col.dose'))} <b>${doseBits.join(' · ')}${moreG}</b></span>`);
    if(sp.pairs.length > 1){
      fields.push(`<span><b>${esc(T('matrix.multi_form'))}</b>: ${esc(sp.pairs.map(g => g.form || '—').join(' / '))}</span>`);
    } else if(sp.pairs[0] && sp.pairs[0].form){
      fields.push(`<span><b>${esc(sp.pairs[0].form)}</b></span>`);
    }
  } else {
    if(strengths.length){
      fields.push(`<span>${esc(T('col.dose'))} <b>${esc(strengths.join(' / '))}</b></span>`);
    }
    if(form) fields.push(`<span><b>${esc(form)}</b></span>`);
  }
  if(markets.length){
    fields.push(`<span>${esc(T('res.identity.markets'))} ${marketTags(markets, 6)}</span>`);
  }
  if(recs) fields.push(`<span>${esc(T('res.identity.records').replace('{n}', String(recs)))}</span>`);
  // v0.11.2（条目 10）：另一语言的成分名不再占卡片常显区（390 上会多 3 行），
  // 移进展开后的字段行；桌面端默认展开，信息不丢。
  if(other && other !== ing) fields.push(`<span>${esc(other)}</span>`);
  const drugHref = first.cu ? (BASE + first.cu)
    : (first.v ? (BASE + 'drug/' + encodeURIComponent(first.v) + '.html') : '');
  const std = String(first.x || first.d || '').trim();
  const acts = [];
  // T11（v0.11.7）B1 第 2 步的第二入口：身份卡上「我用的是这条」（默认取该条目的第一个市场）。
  acts.push(`<button type="button" class="pickbtn" data-pick="${esc(first.k)}|${esc((first.c && first.c[0]) || '')}">`
    + `${esc(T('t11.pick_mine'))}</button>`);
  if(drugHref){
    acts.push(`<a class="primary" href="${drugHref}">${esc(T('res.action_drug'))}</a>`);
  }
  if(std){
    acts.push(`<button type="button" data-copying="${esc(std)}">${esc(T('res.action_copy'))}</button>`);
  }
  acts.push(`<a href="${esc(reportURL(q))}" target="_blank" rel="noopener">`
    + `${esc(T('report.cta'))}</a>`);
  // v0.11.2（条目 9）：标题写清「概括的是哪一条候选」——位置 + 这一条自己的商品名/厂家，
  // 不让人把卡片当成整个品牌的结论（整个品牌/名称仍是候选集）。
  let candName = String(first.d || first.k || q);
  if(candName.length > 42) candName = candName.slice(0, 41) + '…';
  let maker = String(first.m || '');
  if(maker.length > 24) maker = maker.slice(0, 23) + '…';
  const candTitle = esc(T('res.identity_title').replace('{n}', String(display.length)))
    + ` · <b>${esc(candName)}</b>`
    + (maker ? ` <span class="idmake">· ${esc(maker)}</span>` : '');
  // v0.11.2（条目 10 / task-3）：390 宽下卡片折成紧凑头——标题 + 查询→成分一行常显，
  // 规格/市场/警示/动作收进可展开区；桌面端默认展开且不显示摘要行。
  const compactCard = compactUI();
  return `<section class="idcard" aria-label="${esc(T('res.identity.ingredient'))}">
    <p class="idtitle">${candTitle}</p>
    <div class="idrow"><span class="idq">${esc(q)}</span>
      <span class="idarrow">→</span>${ingLine}${badge}</div>
    <details class="idmore"${compactCard ? '' : ' open'}>
      <summary>${esc(T('res.more_detail'))}</summary>
      <div class="idbody">
        <p class="idfields">${fields.join('')}</p>
        <div class="idwarn">${esc(T('res.not_interchangeable'))} · ${esc(T('res.identity_note'))}</div>
        <div class="idacts">${acts.join('')}</div>
      </div>
    </details>
  </section>`;
}
function emptyActionsHTML(q, nq, T){
  // P0-2：零结果三个动作（改写法建议 / 按类别 / 看覆盖），文字始终可见，保留报告入口。
  // 分类 chip 不做：`.catchip` 里含四语文本块，直接搬文字会混语；类别入口用 /atc.html 链接。
  const sug = suggestNames(nq, 3);
  const chips = sug.map(s =>
    `<button type="button" data-q="${esc(s)}">${esc(s)}</button>`).join('');
  return `<div class="empty3">
    <p class="sub">${esc(T('res.empty_spelling'))}</p>
    <div class="e3acts">${chips}
      <a href="${BASE}atc.html">${esc(T('res.empty_browse'))}</a>
      <a href="${BASE}coverage.html">${esc(T('res.empty_coverage'))}</a>
    </div>
  </div>`;
}
function copyGenericName(text){
  const T = window.T || (k=>k);
  const done = ok => { if(meta) meta.textContent = T(ok ? 'res.copied' : 'res.copy_fail'); };
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(() => done(true))
      .catch(() => done(fallbackCopy(text)));
  } else {
    done(fallbackCopy(text));
  }
}
// ── 解析条：名称 / 剂量 / 剂型 / 匹配方式 ─────────────────────────
const FORM_TOKENS = ['片剂','片','胶囊','颗粒剂','颗粒','口服液','注射液','注射剂','软膏',
  '乳膏','凝胶','滴眼液','滴鼻液','喷雾剂','喷雾','吸入剂','缓释','控释','肠溶','糖浆',
  '混悬液','栓剂','贴剂','散剂','滴丸','丸','tablets','tablet','capsules','capsule',
  'syrup','injection','injectable','cream','ointment','gel','spray','inhaler','drops',
  'suspension','suppository','patch','powder','solution'];
function parseQuery(q){
  const [nameQ, st] = splitDose(q);
  const lower = String(nameQ || '').toLowerCase();
  let form = '';
  for(const w of FORM_TOKENS){ if(lower.indexOf(w) >= 0){ form = w; break; } }
  return {name: String(nameQ || '').trim(), dose: st ? (st[0] + ' ' + st[1]) : '', form};
}
function parseBarHTML(parsed, matchLabel){
  const T = window.T || (k=>k);
  const items = [];
  // v0.6.4 A2：ATC 码查询在解析条里明确说明「按 ATC 前缀匹配」，避免误读成药名匹配。
  if(parsed.atc) items.push(`<span class="pitem atcbar"><b>${esc(T('parse.atc'))}</b>`
    + `<code>${esc(parsed.atc)}</code> <span class="sub">${esc(T('atc.hint'))}</span></span>`);
  if(parsed.category) items.push(`<span class="pitem"><b>${esc(T('parse.category'))}</b>`
    + `${esc(parsed.category)} <span class="sub">${esc(T('parse.category_note'))}</span></span>`);
  if(parsed.name) items.push(`<span class="pitem"><b>${esc(T('parse.name'))}</b>${esc(parsed.name)}</span>`);
  if(parsed.dose) items.push(`<span class="pitem"><b>${esc(T('parse.dose'))}</b>${esc(parsed.dose)}</span>`);
  if(parsed.form) items.push(`<span class="pitem"><b>${esc(T('parse.form'))}</b>${esc(parsed.form)}</span>`);
  items.push(`<span class="pitem"><b>${esc(T('parse.match'))}</b><span class="pmatch">${esc(matchLabel)}</span></span>`);
  return `<div class="parsebar" role="status" aria-label="${esc(T('parse.label'))}">${items.join('')}</div>`;
}
// ── 自动完成（输入 ≥2 字，top 8；键盘 ↑↓/回车/Esc，点击可选）────────
let AC_ITEMS = [], AC_I = -1, AC_T = null, AC_WANT = false;
function acClose(){
  if(!acEl) return;
  acEl.classList.remove('open');
  acEl.innerHTML = '';
  AC_ITEMS = []; AC_I = -1;
  if(box.setAttribute) box.setAttribute('aria-expanded', 'false');
}
function acPaint(){
  const T = window.T || (k=>k);
  if(!acEl || !AC_ITEMS.length){ acClose(); return; }
  acEl.innerHTML = AC_ITEMS.map((it, i) => {
    if(it.atc){
      // v0.6.4 A2：ATC 码补全建议
      return `<div class="ac-item${i===AC_I?' on':''}" role="option" aria-selected="${i===AC_I}" data-i="${i}">`
        + `<span class="ac-name">${esc(it.atc)}</span>`
        + `<span class="ac-meta">${esc(T('atc.label'))} · ${it.count} ${esc(T('res.matched'))}</span></div>`;
    }
    const e = it.e;
    const tags = (e.c || []).slice(0, 3)
      .map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
    return `<div class="ac-item${i===AC_I?' on':''}" role="option" aria-selected="${i===AC_I}" data-i="${i}">`
      + `<span class="ac-name">${esc(e.d || e.k)}</span>`
      + `<span class="ac-meta">${esc(ingredientLabel(e))}${tags ? ' ' + tags : ''}</span></div>`;
  }).join('');
  acEl.classList.add('open');
  if(box.setAttribute) box.setAttribute('aria-expanded', 'true');
}
function acCompute(nq, rawName){
  if((!IDX_READY && !POOL_READY) || !nq || nq.length < 2) return [];
  // v0.6.4 A2：ATC 码/前缀补全（按 distinct 码聚合命中条目数）
  const atcQ = atcQuery(rawName || '');
  if(atcQ){
    const map = new Map();
    for(const e of IDX){
      const codes = e.atc;
      if(!codes) continue;
      for(const c of codes){
        if(c.indexOf(atcQ) !== 0) continue;
        const cur = map.get(c);
        if(cur) cur.count++;
        else map.set(c, {atc: c, count: 1});
      }
    }
    return Array.from(map.values())
      .sort((a,b)=> a.atc.length - b.atc.length || b.count - a.count)
      .slice(0, 8);
  }
  const cjk = /[\u4e00-\u9fff]/.test(nq);
  const minSub = cjk ? 2 : 4;
  const pool = [];
  const rankOf = (e) => {
    const k = e.k;
    if(k === nq) return 0;
    if(k.replace(/ /g,'') === nq.replace(/ /g,'')) return 1;
    if(k.indexOf(nq) === 0) return 2;
    if(nq.length >= minSub && k.indexOf(nq) >= 0) return 3;
    return -1;
  };
  const collect = (e) => {
    const rank = rankOf(e);
    if(rank < 0) return;
    pool.push([rank, -(e.n || 0), e.k.length, e]);
  };
  // 派生层就绪时只遍历候选（语义与全表扫描的 rank 0-3 一致）；否则退回全表。
  const cand = (!LEGACY && SEARCH_LAYERS && SEARCH_LAYERS.heavy) ? layerCandidates(nq) : null;
  if(cand){
    for(const pair of cand){
      collect(IDX[pair[0]]);
      if(pool.length >= 500) break;
    }
  }else{
    for(const e of IDX){
      collect(e);
      if(pool.length >= 500) break;
    }
  }
  pool.sort((a,b)=> a[0]-b[0] || a[1]-b[1] || a[2]-b[2]);
  const seen = new Set(), out = [];
  for(const item of pool){
    const e = item[3];
    if(seen.has(e.k)) continue;
    seen.add(e.k); out.push({e});
    if(out.length >= 8) break;
  }
  return out;
}
function acUpdate(){
  clearTimeout(AC_T);
  const raw = box.value.trim();
  const rawName = splitDose(raw)[0];
  const nq = norm(rawName);
  if(nq.length < 2 && atcQuery(rawName) === ''){ AC_WANT = false; acClose(); return; }
  if(!IDX_READY && !POOL_READY){
    AC_WANT = true; acClose();
    // v0.10.2：快车道/分片正在路上时不再抢跑 core（原来这里会为了补全提示立刻拉 9.9 MB，
    // 把「core 后台门控」整条抵消掉）。分片或 core 任一到位后都会回到这里重算补全。
    if(!SHARD_P && !LANE_BUSY) loadIndex();
    return;
  }
  AC_WANT = false;
  AC_T = setTimeout(()=>{ AC_ITEMS = acCompute(nq, rawName); AC_I = -1; acPaint(); }, 90);
}
function acSelect(i){
  const it = AC_ITEMS[i];
  if(!it) return;
  box.value = it.atc || it.e.d || it.e.k;
  acClose();
  trackSearchSubmit(box.value);
  render();
  try{ box.focus(); }catch(e){}
}
// ── 国家语义：标签随选择变化 / 该国无匹配时的显式提示 ────────────────
// 2026-11-11：国家/地区下拉收进 <details class="mf-details"> 后，这段话写的是 summary；
// 选了国家就把 details 展开（?country= 深链、back/forward 一样走这里）。
// 注意**不能** removeAttribute('data-i18n')：那会让切语言（含 ?lang= 补载）后这句不再翻译。
// 改成保留 data-i18n（apply() 先按字典重写基础文案），再由 __DSH_APPLY_HOOKS 在 apply()
// 结尾回填国家名，语言与选择两者都不丢。
function updateCtryLabel(){
  if(!ctryLabel) return;
  const T = window.T || (k=>k);
  const c = ctry.value;
  let name = '';
  try{
    for(const o of ctry.options){ if(o.value === c){ name = o.text; break; } }
  }catch(e){}
  if(c && ctry && ctry.closest){
    const d = ctry.closest('details');
    if(d && !d.open) d.open = true;
  }
  ctryLabel.textContent = c
    ? T('home.country_label_sel').replace('{country}', name)
    : T('home.country_summary');
}
(window.__DSH_APPLY_HOOKS = window.__DSH_APPLY_HOOKS || []).push(updateCtryLabel);
// v0.11.2（条目 10）：来源市场状态行（只在选了来源市场时出现；与目标市场分开显示）。
// 目标市场仍由 #country 的 summary 表示，两者互不改写对方的文案。
function updateSrcNote(){
  if(!srcNote) return;
  const T = window.T || (k=>k);
  const v = srcEl ? srcEl.value : '';
  if(!v){ srcNote.hidden = true; srcNote.innerHTML = ''; return; }
  srcNote.hidden = false;
  srcNote.innerHTML = esc(T('res.src_active').replace('{c}', v)) + ' · '
    + '<button type="button" data-clearsrc="1">' + esc(T('res.src_all')) + '</button>';
}
(window.__DSH_APPLY_HOOKS = window.__DSH_APPLY_HOOKS || []).push(updateSrcNote);
// ── URL 状态：q / country 可分享、可前进后退（history.replaceState，不新增历史项）──
let URL_T = null;
function syncURL(q){
  clearTimeout(URL_T);
  URL_T = setTimeout(()=>{
    try{
      if(!window.history || !window.history.replaceState) return;
      const u = new URL(location.href);
      if(q) u.searchParams.set('q', q); else u.searchParams.delete('q');
      const c = ctry.value;
      if(c) u.searchParams.set('country', c); else u.searchParams.delete('country');
      // v0.11.2（条目 10）：来源市场单独一个参数，不占用 country 的语义
      const s = srcEl ? srcEl.value : '';
      if(s) u.searchParams.set('src', s); else u.searchParams.delete('src');
      window.history.replaceState(null, '', u.pathname + (u.search || '') + (u.hash || ''));
    }catch(e){}
  }, 300);
}
if(window.addEventListener){
  window.addEventListener('popstate', ()=>{
    try{
      const p = new URLSearchParams(location.search);
      box.value = p.get('q') || '';
      ctry.value = (p.get('country') || '').toUpperCase();
      if(srcEl) srcEl.value = (p.get('src') || '').toUpperCase();
      updateCtryLabel();
      updateSrcNote();
      if(box.value.trim()) startSearch(); else render();
    }catch(e){}
  });
}
/* ── 搜索增强（task-28）：运行时派生匹配层 + 拼音懒加载 ──────────────────────
   在已下载的 IDX 上零新增下载派生 exact/连写 Map、前缀排序数组、CJK bigram、
   拉丁 trigram；拼音/首字母用 data/idx/pinyin.json（懒加载）。?legacy=1 不启用。
   collectHits() 与旧线性扫描共享同一套 addHit/tier/排序，保证候选集/碰撞/国家
   视图语义不变；派生层构建失败时自动退回旧路径。基准见 reports/search-engine-v2.md */
function searchLayersBuildLight(){
  try{
    const exact = new Map(), compact = new Map(), sorted = new Array(IDX.length);
    for(let i=0;i<IDX.length;i++){
      const k = IDX[i].k;
      let a = exact.get(k); if(!a){ a = []; exact.set(k, a); } a.push(i);
      const kc = k.replace(/ /g,'');
      if(kc !== k){ let b = compact.get(kc); if(!b){ b = []; compact.set(kc, b); } b.push(i); }
      sorted[i] = i;
    }
    sorted.sort((a,b)=> IDX[a].k < IDX[b].k ? -1 : IDX[a].k > IDX[b].k ? 1 : 0);
    SEARCH_LAYERS = {light:{exact: exact, compact: compact, sorted: sorted}, heavy: null};
  }catch(err){
    SEARCH_LAYERS = null;
    if(window.console && console.warn) console.warn('search layers (light) unavailable', err);
  }
}
function searchLayersBuildHeavy(){
  if(!SEARCH_LAYERS || SEARCH_LAYERS.heavy) return;
  try{
    const bigram = new Map(), trigram = new Map();
    const addTo = (m,k,id) => { let a = m.get(k); if(!a){ a = []; m.set(k, a); } a.push(id); };
    for(let i=0;i<IDX.length;i++){
      const k = IDX[i].k;
      // bigram：任何含汉字的键（CJK 查询的 contains 预筛）
      if(/[\u3400-\u9fff]/.test(k)){
        for(const run of k.match(/[\u3400-\u9fff]+/g) || []){
          if(run.length === 1) addTo(bigram, run, i);
          for(let j=0;j+1<run.length;j++) addTo(bigram, run.slice(j,j+2), i);
        }
      }
      // trigram：任何含拉丁字母/数字的键（含「格华止 glucophage」这类中拉混合名，
      // 旧 contains 用它做拉丁子串命中；只建纯拉丁会漏掉它们）
      if(k.length >= 4 && /[a-z0-9]/.test(k)){
        const t = ' ' + k.replace(/\s+/g,' ') + ' ';
        for(let j=0;j+3<=t.length;j++) addTo(trigram, t.slice(j,j+3), i);
      }
    }
    SEARCH_LAYERS.heavy = {bigram: bigram, trigram: trigram};
  }catch(err){
    if(window.console && console.warn) console.warn('search layers (heavy) unavailable', err);
  }
}
function searchLayersScheduleHeavy(){
  const run = () => searchLayersBuildHeavy();
  try{ setTimeout(run, 0); }catch(e){ /* ignore */ }
}
function pinyinFetch(){
  if(PY_MAP) return Promise.resolve(true);
  if(PY_P) return PY_P;
  PY_P = fetch(BASE + 'data/idx/pinyin.json').then(r=>{
    if(!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(d=>{
    const m = new Map();
    for(const pair of (d && d.tokens) || []) m.set(pair[0], pair[1]);
    PY_MAP = m;
    return true;
  }).catch(err=>{
    PY_P = null;
    if(window.console && console.warn) console.warn('pinyin table unavailable', err);
    return false;
  });
  return PY_P;
}
// 候选枚举：返回 Map(entryIndex -> 匹配档位)；未就绪/不需要派生时返回 null。
function layerCandidates(nq){
  const L = SEARCH_LAYERS;
  if(!L || !L.light || !nq) return null;
  const out = new Map();
  const ex = L.light.exact.get(nq);
  if(ex) for(const id of ex) out.set(id, 'exact');
  const kc = nq.replace(/ /g,'');
  const cp = L.light.compact.get(kc);
  if(cp) for(const id of cp) if(!out.has(id)) out.set(id, 'compact');
  const sorted = L.light.sorted;
  let lo = 0, hi = sorted.length;
  while(lo < hi){ const mid = (lo+hi) >> 1; if(IDX[sorted[mid]].k < nq) lo = mid+1; else hi = mid; }
  let nPre = 0;
  for(let i=lo;i<sorted.length && nPre<2000;i++){
    const k = IDX[sorted[i]].k;
    if(k.indexOf(nq) !== 0) break;
    nPre++;
    if(!out.has(sorted[i])) out.set(sorted[i], 'prefix');
  }
  const H = L.heavy;
  if(!H) return out;
  const cjk = /[\u4e00-\u9fff]/.test(nq);
  const minSub = cjk ? 2 : 4;
  if(nq.length >= minSub){
    if(cjk){
      const gramSet = new Set();
      for(const run of nq.match(/[\u3400-\u9fff]+/g) || []){
        if(run.length === 1) gramSet.add(run);
        for(let j=0;j+1<run.length;j++) gramSet.add(run.slice(j,j+2));
      }
      const cnt = new Map();
      for(const g of gramSet){
        const ids = H.bigram.get(g);
        if(!ids) continue;
        for(const id of ids) cnt.set(id, (cnt.get(id) || 0) + 1);
      }
      const need = Math.max(1, Math.min(2, gramSet.size));
      for(const pair of cnt){
        if(pair[1] >= need && !out.has(pair[0]) && IDX[pair[0]].k.indexOf(nq) >= 0) out.set(pair[0], 'contains');
      }
    }else{
      const t = ' ' + nq.replace(/\s+/g,' ') + ' ';
      const grams = [];
      for(let j=0;j+3<=t.length;j++) grams.push(t.slice(j,j+3));
      const cnt = new Map();
      for(const g of new Set(grams)){
        const ids = H.trigram.get(g);
        if(!ids) continue;
        for(const id of ids) cnt.set(id, (cnt.get(id) || 0) + 1);
      }
      const need = Math.max(1, grams.length - 1);
      for(const pair of cnt){
        if(pair[1] >= need && !out.has(pair[0]) && IDX[pair[0]].k.indexOf(nq) >= 0) out.set(pair[0], 'contains');
      }
    }
  }
  // 已有确定命中（exact/连写/前缀/包含）时不再做模糊/拼音候选：与旧「两遍扫描」语义一致。
  if(out.size) return out;
  // CJK 模糊候选：bigram 交集里“重叠高但不是子串”的名字；第二遍仍用 tier() 的
  // Levenshtein 阈值复核（旧实现第二遍扫全表，这里只缩小候选集）。
  if(cjk && nq.length >= 4){
    const gramSet2 = new Set();
    for(const run of nq.match(/[\u3400-\u9fff]+/g) || []){
      if(run.length === 1) gramSet2.add(run);
      for(let j=0;j+1<run.length;j++) gramSet2.add(run.slice(j,j+2));
    }
    const cnt2 = new Map();
    for(const g of gramSet2){
      const ids = H.bigram.get(g);
      if(!ids) continue;
      for(const id of ids) cnt2.set(id, (cnt2.get(id) || 0) + 1);
    }
    const pool = [];
    for(const pair of cnt2) if(!out.has(pair[0])) pool.push(pair);
    pool.sort((a,b)=> b[1] - a[1]);
    for(let r=0;r<pool.length && r<1000;r++) out.set(pool[r][0], 'fuzzy');
    if(out.size) return out;
  }
  // 拼音/首字母：查询串本身即 token（tainuo -> j:tainuo，tn -> i:tn）
  if(PY_MAP && /^[a-z0-9]+$/.test(nq)){
    const pyIds = PY_MAP.get('j:' + nq) || PY_MAP.get('i:' + nq) || PY_MAP.get('s:' + nq);
    if(pyIds) for(const id of pyIds) if(!out.has(id)) out.set(id, 'pinyin');
  }
  if(out.size) return out;
  // 拉丁 typo：trigram 短名单 + 编辑距离（阈值与 tier() 的 fuzzy 一致）
  if(/^[a-z0-9 .&+\/-]+$/.test(nq) && nq.length >= 4){
    const t = ' ' + nq.replace(/\s+/g,' ') + ' ';
    const grams = [];
    for(let j=0;j+3<=t.length;j++) grams.push(t.slice(j,j+3));
    const cnt = new Map();
    for(const g of new Set(grams)){
      const ids = H.trigram.get(g);
      if(!ids) continue;
      for(const id of ids) cnt.set(id, (cnt.get(id) || 0) + 1);
    }
    const shortlist = [];
    for(const pair of cnt) shortlist.push(pair);
    shortlist.sort((a,b)=> b[1] - a[1]);
    const limit = nq.length >= 9 ? 3 : 2;
    for(let r=0;r<shortlist.length && r<2000;r++){
      const id = shortlist[r][0];
      if(out.has(id)) continue;
      const k = IDX[id].k;
      if(Math.abs(k.length - nq.length) <= 3 && lev(nq, k) <= limit) out.set(id, 'fuzzy');
    }
  }
  return out;
}
// 统一匹配：派生路径与旧线性扫描共用 addHit / tier / 两遍语义。
function collectHits(nq, st, nicks, nickSids, onlyUnmapped, c){
  const hits = [], seen = new Set();
  const addHit = (e, t) => {
    if(seen.has(e.k)) return;
    seen.add(e.k);
    let score = 0.55*t[1] + 0.20*(c && e.c.includes(c) ? 1 : 0.5);
    score += 0.15*(st && e.s.some(x=>x.toLowerCase().startsWith(st[0]+' ')) ? 1 : 0.5);
    score += 0.05;
    hits.push([score, t[0], e]);
  };
  let fuzzyUsed = false;
  const cand = (!LEGACY && !onlyUnmapped && nicks.length === 0
    && SEARCH_LAYERS && SEARCH_LAYERS.heavy) ? layerCandidates(nq) : null;
  if(cand){
    // 候选按 IDX 下标升序处理：与旧全表扫描的插入顺序一致，保证同分命中的稳定排序不变。
    const ids = [];
    for(const pair of cand) ids.push(pair[0]);
    ids.sort((a,b)=> a-b);
    const fuzzyIds = [];
    for(const id of ids){
      const kind = cand.get(id);
      if(kind === 'fuzzy'){ fuzzyIds.push(id); continue; }
      const e = IDX[id];
      const t = kind === 'pinyin' ? ['pinyin', 0.90]
        : (tier(nq, e.k) || (kind === 'contains' ? ['contains', 0.70] : null));
      if(!t || t[0] === 'fuzzy') continue;
      addHit(e, t);
    }
    if(hits.length === 0 && fuzzyIds.length){
      for(const id of fuzzyIds){
        const tt = tier(nq, IDX[id].k);
        if(!tt || tt[0] !== 'fuzzy') continue;   // 与旧第二遍的 tier()==='fuzzy' 过滤一致
        // 模糊档内按编辑距离细排：距离越近分越高，否则同分时会被高 n 的远邻顶到前面
        const d = lev(nq, IDX[id].k);
        const before = hits.length;
        addHit(IDX[id], ['fuzzy', Math.max(0.1, 1 - 0.12 * d)]);
        if(hits.length > before) fuzzyUsed = true;
      }
    }
  }else{
    // 回退路径：?legacy=1 / 派生层未就绪 / 昵称查询 —— 与旧实现逐行等价。
    for(const e of IDX){
      if(onlyUnmapped) continue;
      const subs = (e.x || '').split(' + ');
      const byNick = (e.v && nickSids.has(e.v)) ||
        nicks.some(a => a.i && subs.includes(a.i));
      const t = byNick ? ['nickname', 1.0] : tier(nq, e.k);
      if(!t || t[0]==='fuzzy') continue;
      addHit(e, t);
    }
    if(hits.length === 0 && nicks.length === 0){
      for(const e of IDX){
        const t = tier(nq, e.k);
        if(!t || t[0]!=='fuzzy') continue;
        const before = hits.length;
        addHit(e, t);
        if(hits.length > before) fuzzyUsed = true;
      }
    }
  }
  return {hits: hits, fuzzyUsed: fuzzyUsed};
}
/* ── 搜索增强 end ─────────────────────────────────────────────────────────── */
// ── v0.6.3 U2：结果顶部「各国叫法」横排（仅在唯一单成分时显示）──────────────
const U2_COUNTRIES = ['US', 'GB', 'CN', 'ES', 'MX', 'AU', 'CA', 'TW', 'SG'];
function u2Order(){
  // v0.7.0：国家 chips 按界面语言顺序（i18n.js 在 apply() 里暴露 window.COUNTRY_ORDER）
  const order = (typeof window !== 'undefined' && window.COUNTRY_ORDER) || [];
  const rank = (c) => { const i = order.indexOf(c); return i < 0 ? 99 : i; };
  return U2_COUNTRIES.slice().sort((a, b) => rank(a) - rank(b));
}
function anchorSubstance(hits, nicks){
  // 只认 exact/compact/prefix 的最佳命中；fuzzy/contains 或复方/多成分一律不锚定。
  // （gaviscon / benadryl 这类多结果在这里返回 null → 不显示逐国叫法，避免误配。）
  let best = null;
  for(const h of hits){
    if(h[1] === 'exact' || h[1] === 'compact' || h[1] === 'prefix'){ best = h; break; }
  }
  if(!best && hits.length === 1 && hits[0][1] !== 'fuzzy') best = hits[0];
  if(best){
    const e = best[2];
    const sids = (e.vs && e.vs.length) ? e.vs : [e.v];
    if(sids.length !== 1) return null;         // 复方/多成分 → 降级隐藏
    const anchor = sids[0];
    // 「结果唯一」校验：其它单成分命中也必须指向同一成分；出现第二个成分即隐藏
    // （benadryl 跨国成分不同、tylenol vs tylenol pm 这类必须不显示逐国叫法）。
    for(const h of hits.slice(0, 20)){
      const s2 = (h[2].vs && h[2].vs.length) ? h[2].vs : [h[2].v];
      if(s2.length === 1 && s2[0] && s2[0] !== anchor) return null;
    }
    return {sid: anchor};
  }
  if(!hits.length && nicks.length === 1 && nicks[0].v) return {sid: nicks[0].v};
  return null;
}
function countryNamesHTML(anchor, selected, T){
  if(!anchor) return '';
  const best = {};
  for(const e of IDX){
    const sids = (e.vs && e.vs.length) ? e.vs : [e.v];
    if(sids.length !== 1 || sids[0] !== anchor.sid) continue;   // 只要单成分条目
    for(const code of (e.c || [])){
      const cur = best[code];
      const better = !cur || (!!e.u && !cur.u) ||
                     ((!!e.u === !!cur.u) && (e.n || 0) > (cur.n || 0));
      if(better) best[code] = e;
    }
  }
  if(!U2_COUNTRIES.some(code => best[code])) return '';
  const chips = u2Order().map(code => {
    const hit = best[code];
    const on = code === selected ? ' on' : '';
    const head = `<button type="button" class="u2chip${on}" data-u2country="${code}"`
      + ` aria-pressed="${code === selected ? 'true' : 'false'}">`
      + `<span class="u2c">${esc(T('home.' + code.toLowerCase()))}</span>`;
    if(!hit){
      return head + `<span class="u2n empty" title="${esc(T('u2.none_hint'))}">`
        + `${esc(T('u2.none'))}</span></button>`;
    }
    let name = hit.d || hit.k;
    if(name.length > 28) name = name.slice(0, 28) + '…';
    return head + `<span class="u2n">${esc(name)}</span></button>`;
  }).join('');
  return `<div class="u2bar"><div class="u2head"><b>${esc(T('u2.title'))}</b>`
    + `<span class="sub">${esc(T('u2.hint'))}</span></div>`
    + `<div class="u2chips">${chips}</div></div>`;
}
// v0.6.4 A2：ATC 码查询独立渲染（不参与名称/别名/模糊匹配，避免误当药名）
function renderATC(atcCode, q){
  const T = window.T || (k=>k);
  syncURL(q);
  scheduleSearchEvent(q);
  RES_LIMIT = RES_PAGE; RES_EXPANDED = new Set(); RES_GROUPS = null; RES_MODE = 'grouped';
  const bar = parseBarHTML({atc: atcCode}, T('parse.match.atc'));
  // 有对应类别页才链接（L1–L4）；L5 成分码（如 C07AB02）回退到其 L4 类别 C07AB
  let classCode = '';
  if(CATS && CATS.atc_codes){
    if(CATS.atc_codes.indexOf(atcCode) >= 0) classCode = atcCode;
    else if(atcCode.length === 7 && CATS.atc_codes.indexOf(atcCode.slice(0, 5)) >= 0)
      classCode = atcCode.slice(0, 5);
  }
  const classLink = classCode
    ? `<p class="sub"><a href="${BASE}atc/${esc(classCode)}.html">${esc(T('atc.view_class'))} (${esc(classCode)})</a></p>`
    : "";
  const repEl = document.getElementById('report');
  if(!IDX_READY){
    // ATC 聚合字段只在完整 core 里；分片阶段先显示加载提示，core 到位后重跑。
    out.innerHTML = bar + `<div class="notice">${esc(T('atc.loading'))}</div>`;
    loadIndex().then(ok => { if(ok && box.value.trim() === q) render(); });
    return;
  }
  const hits = [];
  for(const e of IDX){
    const codes = e.atc;
    if(codes && codes.some(c => c.indexOf(atcCode) === 0)) hits.push(e);
  }
  hits.sort((a,b)=> (b.n || 0) - (a.n || 0));
  // v0.10.2 F4a：与 lib/search.py 的「方案 H」同口径——先按成分在该码里的产品总数排，
  // 再按条目 n；否则复方大卡 + 命名碎片化会系统性占优（审计报告 §4）。
  sortBySid(hits, atcIngWeights(atcCode));
  const shown = hits.slice(0, 200);
  if(!shown.length){
    RES_GROUPS = null; LAST_DISPLAY = [];
    out.innerHTML = bar + `<div class="notice warnbox"><b>${esc(T('atc.none_meta').replace('{code}', atcCode))}</b> ${esc(T('atc.none'))}</div>` + classLink;
    meta.textContent = T('atc.none_meta').replace('{code}', atcCode);
    scheduleSearch0(q);
    if(repEl){ repEl.style.display = 'block'; const a = document.getElementById('reportLink'); if(a) a.href = reportURL(q); }
    return;
  }
  const display = shown.map(e => [1, 'atc', e]);
  RES_GROUPS = groupByIngredient(display);
  LAST_DISPLAY = display;
  out.innerHTML = bar
    + `<div class="notice atcbar">${esc(T('atc.hit').replace('{code}', atcCode).replace('{n}', String(hits.length)))}</div>`
    + `<div id="reswrap">${resultsTableHTML(T)}</div>` + classLink;
  meta.textContent = `${hits.length} ${T('res.matched')} · ${T('atc.label')} ${atcCode}`;
  if(repEl){ repEl.style.display = 'block'; const a = document.getElementById('reportLink'); if(a) a.href = reportURL(q); }
}
// v0.7.x：大类词匹配（中英西+繁中，精确/别名；不匹配药名）
// v0.7.x：大类词匹配（中英西+繁中，精确/别名；不匹配药名；忽略重音/空格）
function _catNorm(s){
  return String(s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, '').toLowerCase();
}
function catHit(nq){
  if(!nq) return null;
  const q = _catNorm(nq);
  if(q.length < 2) return null;
  // v0.10.2：先查构建期 word 表（cats.json，与 lib/categories.py 同源），
  // 再回退 data/categories.json 的 label/alias 循环——两条路认识的词集一致，
  // 差别只在「老缓存页面没有 cats.json 时也认识口令词」。
  const x = catxHit(nq);
  if(x && x.kind === 'cat'){
    const c = catxCat(x.id);
    if(c) return c;
  }
  if(!CATS || !CATS.categories) return null;
  for(const c of CATS.categories){
    const labels = [];
    const L = c.labels || {};
    for(const k in L){ if(L[k]) labels.push(L[k]); }
    for(const a of (c.aliases || [])){ if(a) labels.push(a); }
    for(const lb of labels){
      if(_catNorm(lb) === q) return c;
    }
  }
  return null;
}
function renderCategory(cat, q){
  const T = window.T || (k=>k);
  syncURL(q);
  scheduleSearchEvent(q);
  RES_LIMIT = RES_PAGE; RES_EXPANDED = new Set(); RES_GROUPS = null; RES_MODE = 'grouped';
  const label = (cat.labels && (cat.labels[window.LANG] || cat.labels.en)) || cat.id;
  const bar = parseBarHTML({category: label}, T('parse.match.category'));
  const catUrl = BASE + String(cat.url || '');
  if(!IDX_READY){
    out.innerHTML = bar + `<div class="notice">${esc(T('atc.loading'))}</div>`;
    loadIndex().then(ok => { if(ok && box.value.trim() === q) render(); });
    return;
  }
  const prefs = cat.prefixes || [];
  const hits = [];
  for(const e of IDX){
    const codes = e.atc;
    if(codes && codes.some(c => prefs.some(p => c.indexOf(p) === 0))) hits.push(e);
  }
  hits.sort((a,b)=> (b.n || 0) - (a.n || 0));
  sortByIngredient(hits, ingWeightMap(catxCat(cat.id)));
  const shown = hits.slice(0, 200);
  const link = `<p class="sub"><a href="${esc(catUrl)}">${esc(T('atc.view_class'))}</a> · `
    + `${esc(T('cat.disclaimer'))}</p>`;
  if(!shown.length){
    RES_GROUPS = null; LAST_DISPLAY = [];
    out.innerHTML = bar + `<div class="notice warnbox">${esc(T('cat.no_data'))}</div>` + link;
    meta.textContent = T('res.none');
    scheduleSearch0(q);
    return;
  }
  const display = shown.map(e => [1, 'category', e]);
  RES_GROUPS = groupByIngredient(display);
  LAST_DISPLAY = display;
  out.innerHTML = bar + `<div class="notice">${esc(T('parse.category_note'))}</div>` + link
    + `<div id="reswrap">${resultsTableHTML(T)}</div>`;
  meta.textContent = `${hits.length} ${T('res.matched')} · ${T('parse.category')} ${label}`;
}
// ── v0.10.2 快车道渲染（cats.json + 预生成切片，首查不等 core.json）──────────
// 与 renderCategory() 输出同构（解析条 + 说明 + 类目页链接 + 分组表），只是数据源换成
// 构建期切片；随后 loadIndex(true) 在后台补国家视图/同成分/分页，core 到位后 render() 重绘。
// 切片 404 / JSON 坏 / 用语改词 → 返回 false，调用方回退 loadShardedIndex / loadIndex。
function catxCat(id){
  return (CATX && CATX.cats || []).find(c => c.id === id) || null;
}
function renderCategoryFast(cx, id, q){
  const T = window.T || (k=>k);
  const cat = (cx && cx.cats || []).find(c => c.id === id);
  if(!cat || !cat.slice || !cat.slice.f) return Promise.resolve(false);
  const label = (cat.labels && (cat.labels[window.LANG] || cat.labels.en)) || cat.id;
  return fetchJSON(BASE + cat.slice.f + (cx.v ? '?v=' + cx.v : ''))
    .then(rows => {
      if(box.value.trim() !== q) return true;      // 用户已改词：丢弃这次切片
      syncURL(q);
      RES_LIMIT = RES_PAGE; RES_EXPANDED = new Set(); RES_MODE = 'grouped';
      const bar = parseBarHTML({category: label}, T('parse.match.category'));
      const link = `<p class="sub"><a href="${esc(BASE + String(cat.url || ''))}">`
        + `${esc(T('atc.view_class'))}</a> · ${esc(T('cat.disclaimer'))}</p>`;
      const display = (rows || []).map(e => [1, 'category', e]);
      RES_GROUPS = groupByIngredient(display);
      LAST_DISPLAY = display;
      out.innerHTML = bar + `<div class="notice">${esc(T('parse.category_note'))}</div>` + link
        + (display.length
            ? `<div id="reswrap">${resultsTableHTML(T)}</div>`
            : `<div class="notice warnbox">${esc(T('cat.no_data'))}</div>`)
        + (coreLoadPending() ? `<p class="sub">${esc(T('res.partial'))}</p>` : '');
      meta.textContent = `${display.length} ${T('res.matched')} · ${T('parse.category')} ${label}`;
      document.documentElement.classList.add('has-q');
      out.removeAttribute('aria-busy');
      const repEl = document.getElementById('report');
      if(repEl){ repEl.style.display = 'block'; const a = document.getElementById('reportLink');
                 if(a) a.href = reportURL(q); }
      FAST_SHOWN = 1;
      // 后台补全走与分片路径同一个门控（省流 / 2g-3g 不预取、空闲再拉、后台挂起），
      // 不在这里直接 loadIndex()——否则「类别词首查」又变成一次 9.9 MB 的强制下载。
      ensureCoreInBackground();
      return true;
    })
    .catch(() => false);
}
function renderATCFast(cx, code, q){
  const T = window.T || (k=>k);
  return loadAtcIng().then(d => {
    const rows = (d && d.codes) ? d.codes[code] : null;
    if(!rows || !rows.length) return false;       // 没有这个码的成分表 → 回退老路径
    if(box.value.trim() !== q) return true;
    syncURL(q);
    RES_GROUPS = null; LAST_DISPLAY = [];
    const bar = parseBarHTML({atc: code}, T('parse.match.atc'));
    const codes = (cx && cx.atc_codes) || (CATS && CATS.atc_codes) || [];
    let classCode = '';
    if(codes.indexOf(code) >= 0) classCode = code;
    else if(code.length === 7 && codes.indexOf(code.slice(0, 5)) >= 0) classCode = code.slice(0, 5);
    const classLink = classCode
      ? `<p class="sub"><a href="${BASE}atc/${esc(classCode)}.html">${esc(T('atc.view_class'))} (${esc(classCode)})</a></p>`
      : '';
    const zh = window.LANG === 'zh' || window.LANG === 'zh-Hant';
    const names = d.n || {}, totals = d.t || {};
    const lis = rows.map(r => {
      const nm = names[r[0]] || [];
      const label = (zh && nm[1]) ? nm[1] : (nm[0] || r[0]);
      return `<li><a href="${BASE}drug/${esc(r[0])}.html">${esc(label)}</a></li>`;
    }).join('');
    // 不静默截断：成分表只带前 N 个，页面必须说明「还有多少」，并且等 core 到位后
    // renderATC() 会用完整结果整块替换这一屏（不是追加，所以不会留下半截列表）。
    const total = totals[code] || rows.length;
    const more = (total > rows.length)
      ? `<p class="sub">${esc(T('atc.ing_more').replace('{n}', String(total - rows.length)))}</p>`
      : '';
    out.innerHTML = bar + `<div class="notice atcbar">${esc(T('atc.ing_overview'))}</div>`
      + `<ul class="sub atclist">${lis}</ul>` + more + classLink
      + (coreLoadPending() ? `<p class="sub">${esc(T('res.partial'))}</p>` : '');
    meta.textContent = `${T('atc.label')} ${code}`;
    document.documentElement.classList.add('has-q');
    out.removeAttribute('aria-busy');
    const repEl = document.getElementById('report');
    if(repEl){ repEl.style.display = 'block'; const a = document.getElementById('reportLink');
               if(a) a.href = reportURL(q); }
    FAST_SHOWN = 1;
    ensureCoreInBackground();   // 同上：补全走门控，不强制拉 core
    return true;
  }).catch(() => false);
}
// 快车道入口：类别词 → 切片；ATC 码 → 成分表。判定不了或产物缺失 → false（走老路径）。
function startFastLane(q){
  if(IDX_READY || LEGACY) return Promise.resolve(false);
  return loadCatx().then(cx => {
    if(!cx) return false;
    const atc = atcQuery(splitDose(q)[0]);
    if(atc) return renderATCFast(cx, atc, q);
    const hit = catxHit(norm(splitDose(q)[0])) || catxHit(q);
    if(!hit) return false;
    if(hit.kind === 'cat') return renderCategoryFast(cx, hit.id, q);
    return renderATCFast(cx, hit.id, q);
  }).catch(() => false);
}
// ── T11（v0.11.7）：三步确认 + 目标市场常驻 + 逐项对照 ───────────────────────
// 状态全在 URL：`pick=<key_id>`（第 2 步确认的那条）+ `pmk=<记录市场>`；第 3 步的
// `country=<目标市场>` 语义不变 —— **只有不带 pick 时 country 才走老的「整表替换」**。
// 红线：不判断能否互换、不给替代建议、不做剂量换算；「相同/不同」只是字段字面比较。
const T11 = {
  pick: '', pmk: '',
  parse(){
    try{
      const p = new URLSearchParams(location.search);
      this.pick = p.get('pick') || '';
      this.pmk = p.get('pmk') || '';
    }catch(e){ this.pick = ''; this.pmk = ''; }
  },
  set(key, mk){
    const p = new URLSearchParams(location.search);
    if(key){ p.set('pick', key); if(mk) p.set('pmk', mk); else p.delete('pmk'); }
    else { p.delete('pick'); p.delete('pmk'); }
    const qs = p.toString();
    try{ history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '')); }catch(e){}
    this.parse();
    render();
  },
  entry(){
    if(!this.pick) return null;
    return IDX.find(x => x.k === this.pick) || null;
  }
};
T11.parse();

function t11Subs(e){ return ((e && e.vs && e.vs.length) ? e.vs : [e && e.v]).filter(Boolean); }

function t11RenderChips(T){
  const box2 = document.getElementById('mkchips');
  const sel = document.getElementById('country');
  if(!box2 || !sel) return;
  const cur = sel.value || '';
  box2.innerHTML = [...sel.options].map(o => {
    const v = o.value || '';
    const label = v || T('t11.all_markets');
    const on = (v === cur) ? ' on' : '';
    return `<button type="button" class="mkchip${on}" data-mkchip="${esc(v)}" `
      + `aria-pressed="${v === cur ? 'true' : 'false'}">${esc(label)}</button>`;
  }).join('');
}

function t11CompareHTML(pe, mk, hits, T){
  const subs = t11Subs(pe);
  // 目标市场里「至少有同一个成分」的候选（不是「答案」，只是可比的登记记录）
  const others = IDX.filter(x => x !== pe && (x.c || []).includes(mk)
    && t11Subs(x).some(s => subs.indexOf(s) >= 0));
  const mineSpec = (pe.s || []).slice().sort().join(' / ');
  const theirSpec = [...new Set(others.flatMap(x => x.s || []))].sort().join(' / ');
  const mineRel = (pe.rl && pe.rl !== 'none') ? labelOf('release', pe.rl, pe.rl) : '';
  const theirRel = [...new Set(others.map(x => x.rl).filter(r => r && r !== 'none')
    .map(r => labelOf('release', r, r)))].join(' / ');
  const mineName = pe.d || pe.k;
  const theirName = others.slice(0, 3).map(x => x.d || x.k).join('、');
  function badge(a, b){
    if(!b) return `<span class="cmp-b miss">${esc(T('t11.missing'))}</span>`;
    return a === b ? `<span class="cmp-b same">${esc(T('t11.same'))}</span>`
                   : `<span class="cmp-b diff">${esc(T('t11.diff'))}</span>`;
  }
  function row(key, a, b){
    return `<tr><th>${esc(T(key))}</th><td>${esc(a) || '—'}</td><td>${esc(b) || '—'}</td>`
      + `<td>${badge(a, b)}</td></tr>`;
  }
  return `<div class="cmpbox" id="cmp"><h2>${esc(T('t11.cmp_title'))}</h2>`
    + `<div class="tablewrap"><table class="res cmp"><thead><tr><th></th>`
    + `<th>${esc(T('t11.cmp_you'))}</th>`
    + `<th>${esc(T('t11.cmp_target'))} ${esc(mk)}</th><th></th></tr></thead><tbody>`
    + row('t11.name', mineName, theirName)
    + row('t11.spec', mineSpec, theirSpec)
    + row('t11.release', mineRel, theirRel)
    + `</tbody></table></div><p class="sub cmp-note">${esc(T('t11.cmp_note'))}</p></div>`;
}

function t11AfterRender(hits, c, T){
  t11RenderChips(T);
  const bar = document.getElementById('pickbar');
  if(!bar) return;
  const old = document.getElementById('cmp');
  if(old) old.remove();
  const pe = T11.entry();
  if(!pe){
    bar.hidden = true;
    bar.innerHTML = '';
    return;
  }
  const mk = T11.pmk || (pe.c && pe.c[0]) || '';
  const subs = t11Subs(pe);
  const target = c || '';
  const drugHref = BASE + 'drug/' + encodeURIComponent(subs[0] || '') + '.html'
    + '?pick=' + encodeURIComponent(pe.k)
    + (target ? '&country=' + encodeURIComponent(target) : '')
    + '#mk-' + encodeURIComponent(target || mk);
  const sp = specPairsOf(pe, 2);
  const specs = sp.hasFs
    ? sp.pairs.map(g => (g.form ? g.form + ' ' : '') + g.specs.join(' / ')).join(' · ')
    : (pe.s || []).slice(0, 2).join(' / ');
  bar.hidden = false;
  bar.innerHTML = '<div class="pickrow">'
    + `<b>${esc(T('t11.picked'))}</b> `
    + `<span class="pickname">${esc(pe.d || pe.k)}</span> `
    + `<span class="tag">${esc(mk)}</span> `
    + `<span class="pickmeta">${esc(ingredientLabel(pe))}${specs ? ' · ' + esc(specs) : ''}</span> `
    + `<button type="button" class="linkbtn" data-pickset="0">${esc(T('t11.reselect'))}</button> `
    + `<a class="linkbtn" href="${drugHref}">${esc(T('t11.compare_link'))}</a></div>`
    + `<p class="sub picknote">${esc(T('t11.still_candidates').replace('{n}', String(hits.length)))}</p>`;
  if(target) out.insertAdjacentHTML('beforeend', t11CompareHTML(pe, target, hits, T));
}

document.addEventListener('click', function(ev){
  const t = (ev.target && ev.target.closest)
    ? ev.target.closest('[data-pick],[data-pickset],[data-mkchip]') : null;
  if(!t) return;
  if(t.hasAttribute('data-pick')){
    ev.preventDefault();
    const parts = String(t.getAttribute('data-pick') || '').split('|');
    T11.set(parts[0] || '', parts[1] || '');
  } else if(t.hasAttribute('data-pickset')){
    ev.preventDefault();
    T11.set('', '');
  } else {
    ev.preventDefault();
    const sel2 = document.getElementById('country');
    if(sel2){
      sel2.value = t.getAttribute('data-mkchip') || '';
      sel2.dispatchEvent(new Event('change', {bubbles: true}));
    }
  }
});

function render(){
  const q = box.value.trim();
  setCatsHidden(!!q);   // v0.8.2 task-116：有查询（结果/零结果）即收起大类块；清空恢复
  if(q && u1El){
    // v0.9.1 P0-3：首次搜索后自动收起「三步看懂」，移动端首屏直接看到结果/零结果。
    u1El.hidden = true;
    try{ localStorage.setItem('u1.dismiss.v1', '1'); }catch(e){}
  }
  if(!q){ out.innerHTML=''; meta.textContent=''; syncURL('');
    document.documentElement.classList.remove('has-q');
    if(identityEl) identityEl.innerHTML='';
    setH1('', 'home.h1');
    document.title = TITLE_DEFAULT;
    const r0 = document.getElementById('report'); if(r0) r0.style.display='none'; return; }
  document.documentElement.classList.add('has-q');   // task-12：移动端粘性搜索条
  // v0.6.4 A2：ATC 码/类前缀优先走独立路径（C07 / C07A / C07AB02 …）
  const atcCode = atcQuery(splitDose(q)[0]);
  if(atcCode){ renderATC(atcCode, q); return; }
  const [nameQ, st] = splitDose(q);
  const nq = norm(nameQ);
  // v0.7.x：大类词（降压药 / antibiotics / …）→ 主题合集过滤 + 解析条说明
  const cat = catHit(nq);
  if(cat){ renderCategory(cat, q); return; }
  const parsed = parseQuery(q);
  // 新一轮查询：重置分组/折叠/分页状态（「加载更多」「折叠」只在点击时增量重绘）
  RES_LIMIT = RES_PAGE;
  RES_EXPANDED = new Set();
  RES_GROUPS = null;
  RES_MODE = 'flat';        // v0.9.7 task-12：普通查询用扁平表（ATC/大类在各自入口另设）
  scheduleSearchEvent(q);
  syncURL(q);
  const c = ctry.value;
  const nicks = aliasHits(nq);
  const confs = confHits(nq);
  const nickSids = new Set(nicks.map(a=>a.v).filter(Boolean));
  // 只有「没有对应成分」的叫法（如海洛因的 Hammer）时，不要再拿商品名做包含匹配：
  // 否则会倒出一堆名字里刚好有 hammer 的保健品，和这个词没关系。
  const onlyUnmapped = nicks.length > 0 && nicks.every(a => !a.v);
  // P2：分片阶段先出结果；core 未到位时标记 partial，跨条目的区块延后到补全后
  const partial = !!(POOL_READY && !IDX_READY && !LEGACY);
  const matched = collectHits(nq, st, nicks, nickSids, onlyUnmapped, c);
  let hits = matched.hits;
  const fuzzyUsed = matched.fuzzyUsed;
  // 拼音兜底：拉丁查询零命中（或只有模糊命中）且拼音表未加载 → 懒加载 pinyin.json 后重跑一次。
  if(!nicks.length && !LEGACY && SEARCH_LAYERS && /^[a-z0-9 ]{2,}$/.test(nq) && !PY_MAP
     && (!hits.length || hits.every(h=>h[1]==='fuzzy'))){
    pinyinFetch().then(ok => { if(ok && box.value.trim() === q) render(); });
  }
  hits.sort((a,b)=> b[0]-a[0] || (a[2].q?1:0)-(b[2].q?1:0) ||
                     b[2].n-a[2].n || a[2].d.length-b[2].d.length);
  // v0.11.2（条目 10）：来源市场（?src=）只筛候选集——保留在该登记库有记录的条目。
  // 目标市场（c，?country=）在下面单独改变视图；两个语义不混。分片阶段字段未全时先不筛，
  // core 到位后 render 会重跑，届时再按来源市场过滤。
  const src = srcEl ? srcEl.value : '';
  if(src && !partial){
    hits = hits.filter(h => (h[2].c || []).indexOf(src) >= 0);
  }
  // UI P0 ④：不再 40 行/80 行硬截断——保留至多 200 条候选交给前端
  // 「成分聚合 + 品牌折叠 + 加载更多」分页展示（默认每页 25 行可见品牌）。
  const shown = hits.slice(0, 200);
  // 选了国家 = 「这个药在那个国家叫什么」，不是「只显示那个国家的搜索命中」。
  // 先用查询词定位成分（不受国家限制），再把这个成分在目标国的商品名列出来。
  let display = shown;
  let countryMiss = false;    // 选了国家但该国没有任何该成分产品（不再静默回退到各国列表）
  let countryView = false;    // 当前展示的是「该国该成分的商品名」
  // T11（v0.11.7）：**只有不带 pick 时才允许整表替换**（老深链 ?country= 行为不变）。
  if(c && hits.length && !partial && !T11.pick){
    try{
      const sids = new Set();
      for(const [, , e] of hits.slice(0,3)){
        const list = (e.vs && e.vs.length) ? e.vs : [e.v];
        list.filter(Boolean).forEach(s => sids.add(s));
      }
      const inCountry = IDX.filter(x => (x.c || []).includes(c) &&
        ((x.vs && x.vs.length) ? x.vs : [x.v]).filter(Boolean).some(s => sids.has(s)));
      // display 的每一项必须是 [score, tier, entry] 三元组，和 shown 同构，
      // 否则下面 for(const [, , e] of display) 会解构出 undefined。
      if(inCountry.length){
        display = inCountry.slice(0,200).map(e => [0, 'country', e]);
        countryView = true;
      } else {
        display = [];
        countryMiss = true;
      }
    }catch(err){
      console.error('country resolve failed', err);
    }
  }
  const T = window.T || (k=>k);
  // 解析条：匹配方式取首条命中/别名的档位（精确 / 连写 / 前缀 / 包含 / 模糊 / 别名）
  let matchKey = 'none';
  if(nicks.length) matchKey = 'nickname';
  else if(hits.length) matchKey = fuzzyUsed ? 'fuzzy' : hits[0][1];
  let matchLabel = T('parse.match.' + matchKey);
  if(countryView) matchLabel += ' · ' + T('parse.match.country');
  if(countryMiss){
    meta.textContent = `${T('res.none')} — ${T('res.notin')}. ${T('res.caveat')}.`;
  } else if(!hits.length && nicks.length){
    meta.textContent = `${nicks.length} ${T('res.alias')} · ${T('res.alias_no_products')}`;
  } else {
    meta.textContent = hits.length
      ? (fuzzyUsed
          ? `${T('res.fuzzy')} · ${hits.length} ${T(nicks.length ? 'res.brands' : 'res.matched')}`
          : `${hits.length} ${T(nicks.length ? 'res.brands' : 'res.matched')}`)
      : (c ? `${T('res.none')} — ${T('res.notin')}. ${T('res.caveat')}.`
           : `${T('res.none')} — ${T('res.caveat')}.`);
  }
  // v0.10.2：core 被省流/弱网门控时不再谎称「正在加载完整索引」，只有真的在拉才提示；
  // 用户换国家（聚合视图）时 ensureIndexOnDemand() 会按需加载并重绘。
  if(partial && coreLoadPending()) meta.textContent += ' · ' + T('res.partial');
  // 国家无匹配：显式提示 + 「看成分卡」/「换国家」，不再静默回退到各国列表。
  let countryMissHTML = '';
  if(countryMiss){
    const sids = [];
    for(const [, , e] of hits){
      for(const s of ((e.vs && e.vs.length) ? e.vs : [e.v])){
        if(s && sids.indexOf(s) < 0) sids.push(s);
        if(sids.length >= 3) break;
      }
      if(sids.length >= 3) break;
    }
    const cards = sids.map(s =>
      `<a href="${BASE}drug/${encodeURIComponent(s)}.html">${esc(T('country.open_card'))}</a>`).join('');
    countryMissHTML = `<div class="notice warnbox countrymiss"><b>${esc(T('country.missing'))}</b>`
      + ` ${esc(T('country.missing_note'))}`
      + `<div class="cm-actions">${cards}`
      + `<button type="button" data-clearcountry="1">${esc(T('country.change'))}</button></div></div>`;
  }
  // 俗称命中：先说清「这不是商品名，是某个成分的叫法」，再列该成分的商品名。
  // v0.6.3 U2：各国叫法横排——只在结果能唯一锚定单成分时显示；
  // 多成分/多结果（gaviscon、benadryl）与 partial/模糊一律不渲染，避免误配。
  let countryBarHTML = '';
  if(!partial && !countryMiss && display.length){
    const anchor = anchorSubstance(display, nicks);
    if(anchor) countryBarHTML = countryNamesHTML(anchor, c, T);
  }
  let nickHTML = '';
  if(nicks.length){
    nickHTML = nicks.slice(0,3).map(a=>{
      const target = a.v
        ? `<a href="${BASE}drug/${encodeURIComponent(a.v)}.html">${esc(a.x)}</a>`
        : `<b>${esc(a.x)}</b>`;
      const detail = window.LANG === 'zh' ? (a.hint || a.m) : (a.me || '');
      const hint = detail ? `<div class="sub">${esc(detail)}</div>` : '';
      const packs = a.np ? ` · ${a.np} ${T('card.packs')}` : '';
      const caveat = a.k === 'synonym' ? T('nick.synonym_caveat')
        : a.k === 'class' ? T('nick.class_caveat')
        : a.k === 'folk' ? T('nick.folk_caveat')
        : (a.v ? T('nick.caveat') : T('nick.nomap_caveat'));
      const unverified = a.cf && a.cf !== 'documented';
      const cfTag = !unverified ? ''
        : (a.cf === 'user'
            ? ` <span class="tag warn">${T('nick.unverified')}</span>`
            : ` <span class="tag">${T('nick.community')}</span>`);
      // 每条都显示出处；有 URL 的做成链接，没有 URL 的至少显示 provenance 文本。
      const srcText = a.src
        ? (a.su
            ? `<a href="${esc(a.su)}" target="_blank" rel="noopener">${esc(a.src)}</a>`
            : esc(a.src))
        : '—';
      const srcLine = `<div class="sub src">${T('nick.source')}: ${srcText}</div>`;
      // task-141c：同物异名卡（如 Dextrose → Glucose）与俗称卡共用一条渲染，
      // 只换标题；来源行仍打印 CSV 的 source，中文说明只在中文界面展开。
      const headKey = a.k === 'synonym' ? 'nick.synonym_hit' : 'nick.hit';
      return `<div class="notice nick"><div class="nick-head">${T(headKey)}：
        <b>${esc(a.a)}</b> → ${target}
        <span class="tag">${esc(T('nick.'+a.k))}</span>${cfTag}</div>
        <div class="sub">${caveat}${packs}</div>${hint}${srcLine}</div>`;
    }).join('');
    if(nicks.length > 1) nickHTML += `<div class="notice">${T('nick.ambiguous')}</div>`;
  }
  let confHTML = '';
  if(confs.length){
    const items = confs.slice(0,6).map(p=>{
      const label = p.sid
        ? `<a href="${BASE}drug/${encodeURIComponent(p.sid)}.html">${esc(p.x)}</a>`
        : `<b>${esc(p.x)}</b>`;
      const tml = p.tml ? ` <code>${esc(p.tml)}</code>` : '';
      return label + tml;
    }).join('、');
    confHTML = `<div class="notice warnbox"><b>${T('conf.search_hit')}：</b>${items}.
      <a href="${BASE}confused.html">${T('drug.confused_all')}</a></div>`;
  }
  const shownKeys = new Set(shown.map(x=>x[2].k));
  const byFam = new Map();
  for(const [, , e] of shown){
    if(!e.g) continue;
    if(!byFam.has(e.g)) byFam.set(e.g, {note:e.gn||'', comps:new Set()});
    byFam.get(e.g).comps.add(e.x);
  }
  let warnHTML = '';
  const T2 = window.T || (k=>k);
  // v0.11.2（条目 10）：同名不同药的家族说明在 390 上折成一行摘要（警示标签仍常显，
  // 长注释放展开区），桌面端默认展开——结果区上方不再被说明文字吃满首屏。
  const famCompact = compactUI();
  for(const [label, f] of byFam){
    if(f.comps.size > 1){
      // v0.11.6 task-1（T12 C3）：原来把 brand_family.note 原文贴出来（含「属严重碰撞」这种
      // collision 视图内部术语，且只有中文）。现在按数据推导一句人话：同一个名字挂了多种
      // 活性成分——同名不同药、不可互换；分级仍只在后台 collision 视图里。
      warnHTML += `<details class="notice famnotice"${famCompact ? '' : ' open'}>`
        + `<summary><b>${T2('fam.warn')}：${esc(label)}。</b></summary>`
        + `<div class="famnote">${esc(T2('name.severe'))}</div></details>`;
    }
  }
  let extraHTML = '';
  for(const [label, f] of byFam){
    const members = IDX.filter(x=>x.g===label && !shownKeys.has(x.k));
    if(!members.length) continue;
    // v0.11.6 task-1（T12 C2）：标题不再暗示「同一品牌在各国的写法」——这里是同族
    // 但配方可能不同的名字，只做身份对应。
    extraHTML += `<h2>${T2('fam.cmp_title')}</h2>` +
      members.map(e=>`<div class="card"><h3>${e.u ? `<a href="${BASE}name/${e.u}">${esc(e.d)}</a>` : `<b>${esc(e.d)}</b>`}</h3>
      <div class="meta">${esc(e.x)} · ${esc((e.s||[]).join(' / ')||'—')}</div></div>`).join('');
  }
  // 主结果：按成分聚合；同成分多品牌折叠（默认显示前 2 个品牌），
  // 超过 RES_PAGE 行时用「加载更多」分页，不再一刀切 40 行/80 行。
  // v0.10.0 P1-14：大表密度切换（紧凑/舒适，localStorage 记忆）
  try{ if(localStorage.getItem('dsh.density')==='compact') document.body.classList.add('density-compact'); }catch(e){}
  document.addEventListener('click', function(ev){
    var b = ev.target && ev.target.closest ? ev.target.closest('[data-density]') : null;
    if(!b) return;
    var on = document.body.classList.toggle('density-compact');
    try{ localStorage.setItem('dsh.density', on ? 'compact' : 'comfy'); }catch(e){}
  });
  let resHTML = '';
  if(!countryMiss && display.length){
    RES_GROUPS = groupByIngredient(display);
    LAST_DISPLAY = display;      // v0.5.6 B7：导出「当前视图全部行」，不受折叠/分页影响
    resHTML = `<div class="restools">`
      + `<button type="button" class="linkbtn" data-export="copy">${esc(T2('res.copy'))}</button>`
      + `<button type="button" class="linkbtn" data-export="csv">${esc(T2('res.csv'))}</button>`
      + `<button type="button" class="linkbtn" data-density="toggle">${esc(T2('res.density'))}</button>`
      + `<span class="exportnote" id="exportnote" role="status" aria-live="polite"></span>`
      + `</div>`
      + `<div id="reswrap">${RES_MODE === 'flat' ? flatTableHTML(T2) : resultsTableHTML(T2)}</div>`;
    const noBrand = shown.filter(x => x[2] && x[2].t !== 1).length;
    if(noBrand){
      resHTML += `<p class="sub res-nobrand">`
        + esc(T2('res.no_brand_note').replace('{n}', String(noBrand))) + `</p>`;
    }
  } else {
    LAST_DISPLAY = [];
  }

  // 精确命中某个品牌之后，再把「同一成分的其他商品」单独列一段：
  // v0.9.1 P0-1：只收成分集合**完全相同**的条目；成分集合不同但共享成分的另立
  // 「含相同成分之一（不是同一复方）」区块，绝不混进「同成分其他商品」。
  let sameHTML = '';
  const exactSubs = new Set();
  for(const [, t, e] of shown){
    if(t !== 'exact' && t !== 'compact') continue;
    (e.vs && e.vs.length ? e.vs : [e.v]).forEach(s => { if(s) exactSubs.add(s); });
  }
  if(exactSubs.size && exactSubs.size <= 6){
    const anchorSet = exactSubs;
    function sidSet(e){
      return new Set((e.vs && e.vs.length ? e.vs : [e.v]).filter(Boolean));
    }
    function sameSet(e){
      const s = sidSet(e);
      if(s.size !== anchorSet.size) return false;
      for(const x of s){ if(!anchorSet.has(x)) return false; }
      return true;
    }
    const others = IDX.filter(x => !shownKeys.has(x.k));
    const sameRows = [], relatedRows = [];
    for(const e of others){
      const s = sidSet(e);
      if(!s.size) continue;
      let hit = false;
      for(const x of s){ if(anchorSet.has(x)){ hit = true; break; } }
      if(!hit) continue;
      if(sameSet(e)) sameRows.push(e);
      else relatedRows.push(e);
    }
    // v0.9.7 task-12：这两组从「表格」改成紧凑列表 —— 结果页 <tr> 预算 ≤25，
    // 表格版（每行一个规格、上限 80 行）会一次塞进上百行；列表保留可点名、市场与规格。
    function listFor(rows2, limit){
      const list = rows2.slice(0, limit || 8);
      const lis = list.map(e => {
        const ds = (e.s && e.s.length)
          ? e.s.slice().sort((a,b)=>doseNum(a)-doseNum(b)).slice(0, 2).join(' / ') : '';
        const cs = (e.c || []).slice(0, 3)
          .map(c => `<span class="tag ${String(c).toLowerCase()}">${esc(c)}</span>`).join(' ');
        // 2026-11-12 task-18（用户截图）：有商品名的条目也显示厂家，和「无商品名」条目
        // 的「厂家：X 命中名：Y」对齐。>28 字截 27 + …，title 放全名；样式沿用 meta。
        let mah = '';
        if(e.t === 1 && e.m){
          const full = String(e.m);
          const short = full.length > 28 ? full.slice(0, 27) + '…' : full;
          mah = ` <span class="meta" title="${esc(full)}">${esc(T2('brand.mah'))} ${esc(short)}</span>`;
        }
        return `<li>${brandHTML(e)}${mah}${ds ? ' <span class="meta">' + esc(ds) + '</span>' : ''}`
          + `${cs ? ' ' + cs : ''}</li>`;
      }).join('');
      const rest = rows2.length - list.length;
      return `<ul class="sub res-samelist">${lis}</ul>`
        + (rest > 0 ? `<p class="sub">${esc(T2('atc.more').replace('{n}', String(rest)))}</p>` : '');
    }
    sameHTML = '';
    const parts = [];
    if(sameRows.length){
      parts.push(`<h2>${T2('same.ing')}</h2>`
        + `<p class="sub">${T2('same.note')}</p>` + listFor(sameRows, 8));
    }
    if(relatedRows.length){
      parts.push(`<h2>${T2('same.related')}</h2>`
        + `<p class="sub">${T2('same.related_note')}</p>` + listFor(relatedRows, 8));
    }
    if(parts.length){
      sameHTML = `<div class="notice" data-i18n="same.warning">${esc(T2('same.warning'))}</div>`
        + parts.join('');
    }
  }

  if(partial){ sameHTML = ''; extraHTML = ''; }   // 跨条目区块等 core 到位再补
  // v0.8.2：最终无结果 → search0-<q>（部分加载/国家缺失不提前发；去重防抖在 scheduleSearch0）
  if(!partial && !countryMiss && !display.length && !nicks.length && !confs.length){
    scheduleSearch0(q);
  }
  // ── v0.9.7 task-12：身份卡（表前）+ H1=查询名 + 零结果三动作 ──
  const hasResult = !!(display.length && !countryMiss);
  const isBlank = !hits.length && !nicks.length && !confs.length && !countryMiss && !partial;
  if(identityEl){
    identityEl.innerHTML = hasResult
      ? identityCardHTML(parsed.name || q, display, nicks, confs, T) : '';
  }
  if(hasResult || !isBlank){
    setH1(parsed.name || q);
  } else {
    setH1(T('res.empty_h1').replace('{q}', parsed.name || q));
  }
  const emptyHTML = isBlank ? emptyActionsHTML(parsed.name || q, nq, T) : '';
  out.innerHTML = parseBarHTML(parsed, matchLabel) + countryBarHTML + confHTML + nickHTML + warnHTML
    + countryMissHTML + resHTML + sameHTML + extraHTML + emptyHTML;
  out.setAttribute('aria-busy', 'false');
  // T11（v0.11.7）：三步确认的「已选」条 + 目标市场 chips + 逐项对照块（无 pick 时什么都不做，
  // 老深链 `?country=` 仍走上面的 countryView 老路径，行为逐字节不变）。
  t11AfterRender(hits, c, T);
  // 产品层没命中时，再去 ARTG 名称层找「登记存在、成分未收录」的条目；
  // 选了澳洲但澳洲产品为空时同样触发（很多 listed OTC 只有 ARTG 名字）。
  const hasAU = display.some(x => ((x[2].c) || []).includes('AU'));
  if(!partial && ((!display.length && !countryMiss) || (c === 'AU' && !hasAU))){
    out.insertAdjacentHTML('beforeend', '<div id="artgbox"></div>');
    artgFallback(nq);
  }
  const rep = document.getElementById('report');
  if(rep){
    rep.style.display = 'block';
    const a = document.getElementById('reportLink');
    if(a) a.href = reportURL(q);
  }
}
function reportURL(q){
  // issue 模板的字段名走 i18n，避免 es 用户在报告表单里看到中英混排。
  const body = [
    '**' + Tr('report.field_query') + '**: ' + (q || ''),
    '**' + Tr('report.field_page') + '**: ' + location.href,
    '**' + Tr('report.field_expected') + '**: ',
    '**' + Tr('report.field_actual') + '**: ',
    '**' + Tr('report.field_pack') + '**: ',
    ''
  ].join('\n');
  return 'REPORT_REPO_PLACEHOLDER' + '/issues/new?labels=data-error&template=data-error.yml'
    + '&title=' + encodeURIComponent(Tr('report.issue_title') + (q || ''))
    + '&body=' + encodeURIComponent(body);
}
// ── P0 索引懒加载 ──────────────────────────────────────────────────
// 页面加载时不请求完整索引；首次输入 / 聚焦搜索框 / 点示例按钮，或带 ?q= 深链
// 进来时才 loadIndex()。加载失败给出提示与「重试」按钮（不做静默失败）。
// ?legacy=1 一键回滚成旧行为（页面加载即拉全量索引）。
const LEGACY = new URLSearchParams(location.search).get('legacy') === '1';
// i18n.js 先于本脚本执行（<head>），window.T 可用；保留降级到原键名。
function Tr(k){ return (window.T || function(x){ return x; })(k); }
const hintEl = document.getElementById('loadhint');
const HINT_IDLE = Tr('home.hint_idle');
const HINT_LOADING = Tr('home.hint_loading');
function setHint(html, show){
  if(!hintEl) return;
  // 一旦由脚本接管提示文案，就摘掉 data-i18n，避免 i18n.js 的 apply() 把
  // 「正在加载…」又覆盖回静态 idle 文案。
  if(hintEl.removeAttribute) hintEl.removeAttribute('data-i18n');
  hintEl.innerHTML = html || '';
  hintEl.style.display = (show === false || !html) ? 'none' : '';
}
// 构建把 index.json 编成「版本头 + 列式数组 + 字符串字典」；这里解码回与旧 index.json
// 同字段（字段清单见 build.py 的 CORE_FIELDS；v0.11.2 起 t/nc/eo 也在 core 里）的 IDX 数组，
// render() 以下逻辑一行不改。
//   cols[f] = {d:[字典值...], i:[每行的字典下标...]}  字典列
//   cols[f] = [值...]                                普通列
//   d 与 k 只差 ASCII 大小写时 cols.d 存 ""，cols.dp 存大小写位置模式（'0-2,5'）；
//   q=1 的条目单独用稀疏下标数组存。
function applyCase(k, pat){
  const out = k.split('');
  for(const run of pat.split(',')){
    const p = run.split('-'), lo = +p[0], hi = p.length > 1 ? +p[1] : lo;
    for(let i = lo; i <= hi; i++) out[i] = out[i].toUpperCase();
  }
  return out.join('');
}
function decodeCore(c){
  if(!c || !Array.isArray(c.cols && c.cols.k) || typeof c.n !== 'number') throw new Error('bad core');
  const n = c.n, C = c.cols, out = new Array(n);
  const kcol = C.k, dcol = C.d || [], dpcol = C.dp || [];
  for(let i = 0; i < n; i++){
    const k = kcol[i];
    let d = dcol[i];
    if(!d) d = dpcol[i] ? applyCase(k, dpcol[i]) : k;
    out[i] = {k: k, d: d};
  }
  for(const f in C){
    if(f === 'k' || f === 'd' || f === 'dp') continue;
    const col = C[f];
    if(!col) continue;
    if(col.d && col.i){                       // 字典列
      const dict = col.d, idx = col.i;
      for(let i = 0; i < n; i++) out[i][f] = dict[idx[i]];
    } else if(Array.isArray(col)){            // 普通列
      for(let i = 0; i < n; i++) out[i][f] = col[i];
    }
  }
  for(const i of (c.q || [])) out[i].q = 1;
  return out;
}
function fetchJSON(url){
  return fetch(url).then(r=>{ if(!r.ok) throw new Error('HTTP '+r.status+' '+url); return r.json(); });
}
function loadMainIndex(){
  // v0.6.1：data/index.json 双写已停（过渡期可用 WRITE_LEGACY_INDEX=1 恢复）。
  // ?legacy=1（旧「启动即拉全量」行为）与默认路径都走 data/idx/core.json + decodeCore；
  // 失败时先尝试可选的 data/idx/legacy-mini.json（构建开关 WRITE_LEGACY_MINI=1），
  // 仍失败则抛出，交给 loadIndex() 的统一错误提示 + 重试按钮，不再请求 index.json。
  return fetchJSON(BASE + 'data/idx/core.json').then(decodeCore).catch(err=>{
    if(window.console && console.warn) console.warn('core index unavailable, try legacy-mini', err);
    return fetchJSON(BASE + 'data/idx/legacy-mini.json').then(decodeCore).catch(()=>{ throw err; });
  });
}

// ── P2 分片加载（task-36）───────────────────────────────────────────────
function fetchManifest(){
  if(MANIFEST) return Promise.resolve(MANIFEST);
  if(MANIFEST_P) return MANIFEST_P;
  MANIFEST_P = fetchJSON(BASE + 'data/idx/manifest.json').then(m=>{ MANIFEST = m; return m; })
    .catch(err=>{ MANIFEST_P = null; throw err; });
  return MANIFEST_P;
}
function loadSupport(){
  if(SUPPORT_P) return SUPPORT_P;
  SUPPORT_P = Promise.all([
    fetch(BASE + 'data/aliases.json').then(r=>r.json()).catch(()=>[]),
    fetch(BASE + 'data/confused.json').then(r=>r.json()).catch(()=>[]),
    fetch(BASE + 'data/categories.json').then(r=>r.json()).catch(()=>null)
  ]).then(([a,c,cat])=>{ NICKS = a || []; CONF = c || []; CATS = cat || null; return true; })
    .catch(()=>{ SUPPORT_P = null; return false; });
  return SUPPORT_P;
}
// ── v0.10.2 类别发现快车道：轻量词表 + 预生成切片 ─────────────────────────
// 审计：reports/search-discovery-audit-20261110.md §2。失败一律返回 null，调用方回退老路径
// （loadShardedIndex / loadIndex），行为与 v0.10.1 逐字节一致，不弹错、不白屏。
function loadCatx(){
  if(CATX) return Promise.resolve(CATX);
  if(CATX_P) return CATX_P;
  CATX_P = fetchJSON(BASE + 'data/idx/cats.json')
    .then(x => { CATX = x || null; return CATX; })
    .catch(() => { CATX = null; CATX_P = null; return null; });
  return CATX_P;
}
function loadAtcIng(){
  if(ATCING) return Promise.resolve(ATCING);
  if(ATCING_P) return ATCING_P;
  ATCING_P = fetchJSON(BASE + 'data/idx/atc-ing.json')
    .then(x => { ATCING = x || null; return ATCING; })
    .catch(() => { ATCING = null; ATCING_P = null; return null; });
  return ATCING_P;
}
// 类别词解释：先查 cats.json 的 words（快车道 + 老客户端都吃这一份），
// 查不到再回退 data/categories.json 的 label/alias 循环（catHit）。
function catxHit(nq){
  if(!CATX || !CATX.words) return null;
  const q = _catNorm(nq);
  if(q.length < 2) return null;
  const hit = CATX.words[q];
  if(!hit) return null;
  if(hit.indexOf('cat:') === 0) return {kind: 'cat', id: hit.slice(4)};
  return {kind: 'atc', id: hit.slice(4)};
}
// 成分在本类别的产品数（cats.json 的 cats[].ing），给 ATC/大类结果换排序键——
// 与 lib/search.py 的 _order_by_ingredient 同口径（审计报告 §4 方案 H）。
function ingWeightMap(cat){
  const m = new Map();
  if(!cat || !cat.ing) return m;
  for(const r of cat.ing) m.set(r[0], r[1]);
  return m;
}
function sortByIngredient(hits, weights){
  if(!weights || !weights.size) return;
  hits.sort((a, b)=>{
    const wa = Math.max(0, ...(String(a.x || '').split(' + ').map(s => weights.get(s) || 0)));
    const wb = Math.max(0, ...(String(b.x || '').split(' + ').map(s => weights.get(s) || 0)));
    return wb - wa || (b.n || 0) - (a.n || 0);
  });
}
// ATC 码的排序权重按 substance_id 存（atc-ing.json 的 [sid, 产品数]），与大类按名字不同。
// 权重表未就绪时先按 n 排（v0.10.1 行为），表到了再重排一次（同一查询才重排）。
function atcIngWeights(code){
  if(!ATCING || !ATCING.codes || !ATCING.codes[code]){
    loadAtcIng().then(d => {
      if(!d || !d.codes || !d.codes[code]) return;
      const q = box.value.trim();
      if(q && atcQuery(splitDose(q)[0]) === code) render();
    });
    return null;
  }
  const m = new Map();
  for(const r of ATCING.codes[code]) m.set(r[0], r[1]);
  return m;
}
function sortBySid(hits, weights){
  if(!weights || !weights.size) return;
  const weightOf = e => {
    const sids = (e.vs && e.vs.length) ? e.vs : [e.v];
    return Math.max(0, ...sids.filter(Boolean).map(s => weights.get(s) || 0));
  };
  hits.sort((a, b)=> weightOf(b) - weightOf(a) || (b.n || 0) - (a.n || 0));
}
function shardKeyOf(nq){
  const ch = nq && nq[0];
  if(!ch) return null;
  if(ch >= 'a' && ch <= 'z') return ch;
  if(ch >= '0' && ch <= '9') return 'digit';
  if(/[\u3400-\u9fff]/.test(ch)) return (MANIFEST && MANIFEST.cjkInitials && MANIFEST.cjkInitials[ch]) || null;
  return 'other';
}
function shardsForQuery(nq){
  const key = shardKeyOf(nq);
  if(!key || !MANIFEST || !MANIFEST.buckets || !MANIFEST.buckets[key]) return null;
  const files = MANIFEST.buckets[key];
  if(key.indexOf('cjk-') === 0) return files.slice(0, 3);
  const hi = nq + '\uffff';
  const picked = files.filter(f=> f.first <= hi && f.last >= nq);
  return picked.length ? picked.slice(0, 3) : null;
}
function loadShards(files){
  const ver = (MANIFEST && MANIFEST.v) ? '?v=' + MANIFEST.v : '';
  return Promise.all(files.map(f=>{
    if(SHARD_CACHE.has(f.f)) return Promise.resolve(SHARD_CACHE.get(f.f));
    return fetchJSON(BASE + f.f + ver).then(arr=>{ SHARD_CACHE.set(f.f, arr); return arr; });
  })).then(parts=>{
    // core 已先一步到达：丢弃分片追加，保持 IDX 为完整索引（避免 pool 覆盖 core 导致索引错位）
    if(IDX_READY){
      for(const f of files) POOL_FILES.add(f.f);
      return IDX;
    }
    const pool = POOL_READY ? IDX.slice() : [];
    for(const part of parts) for(const e of part) pool.push(e);
    IDX = pool;
    POOL_READY = true;
    for(const f of files) POOL_FILES.add(f.f);
    // v0.10.2：分片到位就能给补全提示（core 现在要等安静期才拉，别让补全一直空着）
    if(typeof AC_WANT !== 'undefined' && AC_WANT) acUpdate();
    return pool;
  });
}
function loadShardedIndex(q){
  const nq = norm(splitDose(q)[0]);
  return Promise.all([fetchManifest(), loadSupport()]).then(()=>{
    const files = shardsForQuery(nq);
    if(!files) throw new Error('no shard for query');
    return loadShards(files);
  });
}
// ── v0.10.2 M-2：core.json（≈9.9 MB gz）后台预取门控 ──────────────────────
// core 只补「国家视图 / 同成分 / 品牌家族 / 拼音重试」这些跨条目的聚合区块；
// identity 卡与命中表在分片阶段已经出来，所以搜完立刻白拉 9.9 MB 对手机是纯浪费：
//   1) 网络：saveData（省流）或 slow-2g / 2g / 3g 完全不预取；
//   2) 首屏：先让首屏安顿，用 requestIdleCallback(…, {timeout: 8000}) 空闲再拉
//      （Safari 没有 idle callback，退化成 3s setTimeout）；
//   3) 页面不可见（切到后台 tab）时挂起，回到前台再试一次。
// 用户主动要聚合视图（换国家下拉）时走 ensureIndexOnDemand()，按需加载并重绘，
// 失败降级保持原样（分片结果继续可用 + 「重试」按钮，见 loadIndex 的 catch）。
const CORE_BG = {pending: 0, timer: 0, waiting: 0};
const CORE_BG_DELAY = 9000;          // 首屏安静这么久之后才考虑拉 core（不抢首屏带宽）
const CORE_BG_IDLE_TIMEOUT = 8000;   // 安静期过后，空闲回调最长再等 8s
const CORE_BG_FALLBACK_DELAY = 3000; // 兼容位：无 requestIdleCallback 时的等价延后
function coreNetAllowsPrefetch(){
  const c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if(!c) return true;                // Safari 没有 connection API → 交给空闲/可见性门控
  if(c.saveData) return false;       // 用户开了省流模式：不预取
  const et = c.effectiveType || '';
  return et !== 'slow-2g' && et !== '2g' && et !== '3g';
}
function coreLoadPending(){ return !!(IDX_P || CORE_BG.pending); }
function ensureCoreInBackground(){
  if(IDX_READY || IDX_P || LEGACY) return;
  if(!coreNetAllowsPrefetch()) return;
  if(document.visibilityState === 'hidden'){
    if(CORE_BG.waiting) return;
    CORE_BG.waiting = 1;
    document.addEventListener('visibilitychange', function onVisible(){
      if(document.visibilityState === 'hidden') return;
      document.removeEventListener('visibilitychange', onVisible);
      CORE_BG.waiting = 0;
      ensureCoreInBackground();
    });
    return;
  }
  if(CORE_BG.pending) return;
  CORE_BG.pending = 1;
  const fire = function(){
    CORE_BG.pending = 0;
    if(CORE_BG.timer){ clearTimeout(CORE_BG.timer); CORE_BG.timer = 0; }
    if(IDX_READY || IDX_P) return;
    loadIndex(true);
  };
  // 先等一段「安静期」再排空闲回调：requestIdleCallback 在空闲页面里几乎立刻触发，
  // 只靠它等于「输入 2 个字就拉 9.9 MB」——那是 M-2 要修的问题本身。
  // CORE_BG_DELAY 之内用户还在打字/切词，就不该为补全抢带宽。
  try{
    CORE_BG.timer = setTimeout(function(){
      CORE_BG.timer = 0;
      try{
        if(window.requestIdleCallback){
          window.requestIdleCallback(fire, {timeout: CORE_BG_IDLE_TIMEOUT});
        }else{
          fire();
        }
      }catch(e){ fire(); }
    }, CORE_BG_DELAY);
  }catch(e){ fire(); }
}
// 用户明确要聚合视图（换国家/地区）：不等空闲，直接按需加载 core 后重绘。
function ensureIndexOnDemand(){
  if(IDX_READY || IDX_P || LEGACY) return;
  loadIndex().then(ok => { if(ok && box.value.trim()) render(); });
}
function loadIndex(quiet){
  if(IDX_READY) return Promise.resolve(true);
  if(IDX_P) return IDX_P;
  if(!LEGACY && !quiet) setHint(HINT_LOADING);
  IDX_P = Promise.all([loadMainIndex(), loadSupport()]).then(([d])=>{
    IDX=d||[]; IDX_READY=true; POOL_READY=false;
    setHint('');
    // 搜索增强（task-28）：索引到位后先派生轻量层（exact/前缀，~0.2s），
    // 重层（bigram/trigram）放到下一轮事件循环，避免阻塞首个结果渲染。
    if(!LEGACY){
      searchLayersBuildLight();
      searchLayersScheduleHeavy();
    }
    // 用户可能在索引加载期间已经输入了 ≥2 字：加载完成后补算自动完成。
    if(AC_WANT) acUpdate();
    // P2：分片已先出结果时，核心到位后自动补全（国家视图/同成分/模糊/拼音等）。
    if(quiet && box.value.trim()) render();
    return true;
  }).catch(err=>{
    // 失败后清掉缓存的 Promise，允许点「重试」重新发起。
    IDX_P = null;
    if(quiet && (POOL_READY || FAST_SHOWN)){
      // 分片 / 快车道切片已经出了结果：core 失败不推翻已显示的内容，只在控制台留痕。
      if(window.console && console.warn) console.warn('core index unavailable (partial view kept)', err);
      return false;
    }
    setHint(HINT_IDLE);
    out.innerHTML = '<div class="notice">' + esc(Tr('error.index_failed')) + ' '
      + esc(Tr('error.local_file'))
      + '<br>' + esc(String((err && err.message) || err || ''))
      + '<br><button type="button" data-retry="1">' + esc(Tr('error.retry')) + '</button></div>';
    return false;
  });
  return IDX_P;
}
function startSearch(){
  if(IDX_READY){ render(); return; }
  if(LEGACY){ loadIndex().then(ok => { if(ok) render(); }); return; }
  const q = box.value.trim();
  if(!q){ render(); return; }
  if(u1El){
    // v0.9.1 P0-3：输入即收起引导，加载态/结果计数在搜索框下方可见。
    u1El.hidden = true;
    try{ localStorage.setItem('u1.dismiss.v1', '1'); }catch(e){}
  }
  // v0.9.1 P0-3：加载态放在搜索框下方（同结果计数位置），移动端首屏可见。
  // v0.9.7 task-12 P0-12：首搜改成 3 行骨架占位（#meta 仍有 aria-live 文本给读屏）。
  if(meta && !POOL_READY){
    meta.textContent = (window.T || function(k){ return k; })('home.loading');
  }
  if(out && !POOL_READY && q){
    out.innerHTML = skeletonHTML(window.T || function(k){ return k; });
    out.setAttribute('aria-busy', 'true');
  }
  document.documentElement.classList.add('has-q');
  // v0.10.2：类别词 / ATC 码先走轻量索引（≈23 KB 词表 + 一份 30–57 KB 切片），
  // 命中就直接出结果，core.json 在后台补全；判定不了 / 产物缺失 → 回退下面的老路径。
  // LANE_BUSY 让 acUpdate() 知道「首屏这条路正在加载」，别为了补全提示抢跑 core。
  LANE_BUSY = true;
  startFastLane(q).then(taken => {
    LANE_BUSY = false;
    if(!taken) startSlowLane(q);
  });
}
// 老路径（v0.10.1 行为逐字节不变）：分片先出结果，core 后台补；ATC 码直接等 core。
function startSlowLane(q){
  FAST_SHOWN = 0;    // 这一轮不是快车道渲染的：core 失败要照常报错，别保留旧内容
  // v0.6.4 A2：ATC 码查询需要完整索引（分片里的条目不一定带 atc 聚合），先确保 core 到位。
  if(atcQuery(splitDose(q)[0])){ loadIndex().then(ok => { if(ok) render(); }); return; }
  const nq = norm(splitDose(q)[0]);
  if(POOL_READY){
    const files = shardsForQuery(nq);
    if(files && files.some(f=> !POOL_FILES.has(f.f))){
      // v0.10.2：先排后台预取（同步置 pending），再 render()——否则首帧算不出
      // 「partial 且 core 在拉」这个状态，#meta 会漏掉「部分结果」提示。
      loadShards(files).then(()=>{ ensureCoreInBackground(); render(); })
        .catch(()=>{ ensureCoreInBackground(); render(); });
    }else{
      ensureCoreInBackground();
      render();
    }
    return;
  }
  SHARD_P = loadShardedIndex(q).then(()=>{ ensureCoreInBackground(); render(); })
    .catch(()=> loadIndex().then(ok => { if(ok) render(); }));
}
// 结果区事件委托：失败重试 / 加载更多 / 品牌折叠展开 / 换国家。
out.addEventListener('click', ev => {
  const t = ev.target;
  if(!t || !t.closest) return;
  if(t.closest('[data-retry]')){
    out.innerHTML = '';
    loadIndex().then(ok => { if(ok) render(); });
    return;
  }
  if(t.closest('[data-loadmore]')){
    RES_LIMIT += RES_PAGE;
    paintResultsOnly();
    return;
  }
  // v0.9.7 task-12：零结果的「改写法建议」按钮（渲染后才存在，故在委托里处理）
  const qb = t.closest('[data-q]');
  if(qb){
    box.value = qb.getAttribute('data-q');
    acClose();
    trackSearchSubmit(box.value);
    startSearch();
    box.focus();
    return;
  }
  const fold = t.closest('[data-gi]');
  if(fold){
    const gi = +fold.getAttribute('data-gi');
    if(fold.getAttribute('data-fold') === '1') RES_EXPANDED.add(gi);
    else RES_EXPANDED.delete(gi);
    paintResultsOnly();
    return;
  }
  const mt = t.closest('[data-mah]');
  if(mt){
    // v0.5.4：厂家列「+N」展开/收起其它厂家（列表项都带厂家页链接）
    const wrap = mt.parentNode;
    const list = wrap && wrap.querySelector ? wrap.querySelector('.mah-list') : null;
    if(list){
      const willOpen = list.hasAttribute('hidden');
      if(willOpen) list.removeAttribute('hidden');
      else list.setAttribute('hidden', '');
      mt.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    }
    return;
  }
  // v0.5.6 B7：复制表格 / 下载 CSV（当前视图全部结果，含折叠与未加载行）
  const ex = t.closest('[data-export]');
  if(ex){
    const rows = exportRows();
    if(ex.getAttribute('data-export') === 'csv') downloadCSV(rows, Tr);
    else copyTSV(rows, Tr);
    gcEvent('export-' + ex.getAttribute('data-export'));
    return;
  }
  // v0.5.6 A1：行下展开产品级明细（懒加载 detail-<bucket>.json，再次点击折叠）
  const detBtn = t.closest('[data-det]');
  if(detBtn){
    const k = detBtn.getAttribute('data-det');
    const tr = detBtn.closest('tr');
    const next = tr && tr.nextElementSibling;
    if(next && next.classList && next.classList.contains('detrow')){
      const willOpen = next.style.display === 'none';
      next.style.display = willOpen ? '' : 'none';
      detBtn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
      return;
    }
    const e = findEntryByKey(k) || {k: k, v: ''};
    const row = document.createElement('tr');
    row.className = 'detrow';
    // task-12：扁平结果表是 4 列，分组表是 4 列（ATC/大类），按当前行实际列数取 colspan
    const ncol = tr ? tr.children.length : 4;
    row.innerHTML = `<td colspan="${ncol}" class="detcell">${esc(Tr('a1.loading'))}</td>`;
    tr.parentNode.insertBefore(row, tr.nextSibling);
    detBtn.setAttribute('aria-expanded', 'true');
    loadDetailBucket(detBucketOf(e)).then(payload => Promise.all([loadMakerMap(), loadExportOnly()]).then(() => {
      const cell = row.querySelector('.detcell');
      if(cell) cell.innerHTML = detPanelHTML(payload, k, e, Tr);
    }));
    return;
  }
  // v0.6.3 U2：点国家 chip = 切到该国国家视图（复用现有 ctry 状态 + URL + 统计）
  const u2c = t.closest('[data-u2country]');
  if(u2c){
    ctry.value = u2c.getAttribute('data-u2country');
    updateCtryLabel();
    render();
    gcEvent('country-' + ctry.value);
    return;
  }
  if(t.closest('[data-clearcountry]')){
    ctry.value = '';
    updateCtryLabel();
    render();
    return;
  }
  // v0.11.2（条目 10）：清掉来源市场过滤，候选集回到全部登记库
  if(t.closest('[data-clearsrc]')){
    if(srcEl) srcEl.value = '';
    updateSrcNote();
    render();
  }
});
// 点击事件：结果里的品牌/成分链接、报告入口、更新日志（只记事件，不记用户）。
document.addEventListener('click', ev => {
  // v0.9.7 task-12：身份卡「复制标准名」（卡片在 #out 之外，用文档级委托）
  const cp = ev.target && ev.target.closest ? ev.target.closest('[data-copying]') : null;
  if(cp){ copyGenericName(cp.getAttribute('data-copying')); return; }
  const a = ev.target && ev.target.closest ? ev.target.closest('a') : null;
  if(!a) return;
  const href = a.getAttribute('href') || '';
  if(href.indexOf('/issues/new') >= 0){ gcEvent('click-report'); return; }
  if(href.indexOf('/name/') >= 0 || href.indexOf('/drug/') >= 0){ gcEvent('click-result'); return; }
  if(href.indexOf('whats-new') >= 0){ gcEvent('click-whatsnew'); return; }
});
box.addEventListener('input', ()=>{ startSearch(); acUpdate(); });
// 2026-11-11 UI：搜索框里那个可见提交按钮（44×44，移动端键盘的 search 键同一条路径）。
// 输入时已经实时出结果，这里只负责「提交」这一下：收起建议、记一次提交、重渲染、回焦。
const goBtn = document.getElementById('qgo');
if(goBtn && box){
  goBtn.addEventListener('click', ()=>{
    acClose();
    if(!box.value.trim()){ try{ box.focus(); }catch(e){} return; }
    trackSearchSubmit(box.value);
    startSearch();
    try{ box.focus(); }catch(e){}
  });
}
ctry.addEventListener('change', ()=>{
  gcEvent('country-' + (ctry.value || 'ALL'));
  updateCtryLabel();
  acClose();
  // v0.10.2：选了国家/地区就是「要按国家看的聚合视图」，这需要完整 core；
  // 后台预取被省流/弱网门控时，这里按需加载（HINT_LOADING + 失败重试照旧）。
  if(ctry.value) ensureIndexOnDemand();
  startSearch();
});
// v0.11.2（条目 10）：来源市场只过滤候选集（登记库），不触发国家聚合视图。
if(srcEl){
  srcEl.addEventListener('change', ()=>{
    updateSrcNote();
    acClose();
    startSearch();
  });
}
document.querySelectorAll('[data-q]').forEach(b=>b.addEventListener('click',()=>{
  box.value=b.dataset.q; acClose(); trackSearchSubmit(box.value); startSearch(); box.focus();
}));
// 自动完成键盘操作：↑↓ 移动、回车选中、Esc 关闭；点击在 #ac 上委托。
box.addEventListener('keydown', ev => {
  const open = !!(acEl && acEl.classList.contains('open') && AC_ITEMS.length);
  if(ev.key === 'ArrowDown'){
    if(!open) return;
    ev.preventDefault();
    AC_I = (AC_I + 1) % AC_ITEMS.length;
    acPaint();
  } else if(ev.key === 'ArrowUp'){
    if(!open) return;
    ev.preventDefault();
    AC_I = (AC_I - 1 + AC_ITEMS.length) % AC_ITEMS.length;
    acPaint();
  } else if(ev.key === 'Enter'){
    if(open && AC_I >= 0){ ev.preventDefault(); acSelect(AC_I); }
    else { acClose(); trackSearchSubmit(box.value); }
  } else if(ev.key === 'Escape'){
    acClose();
  }
});
// v0.6.4 B9：`/` 聚焦搜索框、`Esc` 关闭建议/清空查询。
// 不拦截输入法 composition（isComposing / keyCode 229），也不在其它输入控件里抢键。
document.addEventListener('keydown', ev => {
  if(ev.defaultPrevented || ev.isComposing || ev.keyCode === 229) return;
  const t = ev.target || {};
  const tag = String(t.tagName || '').toLowerCase();
  const typing = tag === 'input' || tag === 'textarea' || tag === 'select' || t.isContentEditable;
  if(ev.key === '/' && !typing && !ev.ctrlKey && !ev.metaKey && !ev.altKey){
    ev.preventDefault();
    try{ box.focus(); box.select(); }catch(e){}
    return;
  }
  if(ev.key === 'Escape'){
    if(acEl && acEl.classList.contains('open')){ acClose(); ev.preventDefault(); return; }
    if(box.value){ box.value = ''; acClose(); render(); ev.preventDefault(); }
  }
});
if(acEl){
  // mousedown 阻止默认，避免输入框先失焦导致点击落空。
  acEl.addEventListener('mousedown', ev => { ev.preventDefault(); });
  acEl.addEventListener('click', ev => {
    const t = ev.target && ev.target.closest ? ev.target.closest('[data-i]') : null;
    if(!t) return;
    acSelect(+t.getAttribute('data-i'));
  });
}
document.addEventListener('click', ev => {
  if(!acEl || !acEl.classList.contains('open')) return;
  const t = ev.target;
  if(t === box || (t.closest && t.closest('#ac'))) return;
  acClose();
});
// 聚焦搜索框就先预取「分片支持文件」（manifest + 别名/易混淆），不预取 core。
box.addEventListener('focus', ()=>{ if(!IDX_READY && !POOL_READY && !LEGACY){ fetchManifest().catch(()=>{}); loadSupport(); } });
const initial = new URLSearchParams(location.search).get('q');
if(initial){ box.value = initial; }
const ctry0 = new URLSearchParams(location.search).get('country');
if(ctry0 && ctry){ ctry.value = ctry0.toUpperCase(); }
// v0.11.2（条目 10）：?src= 来源市场深链（与 ?country= 目标市场并列，互不覆盖）
const src0 = new URLSearchParams(location.search).get('src');
if(src0 && srcEl){ srcEl.value = src0.toUpperCase(); }
updateCtryLabel();   // 「看这个药在哪个国家叫什么」标签随 URL/选择初始化
updateSrcNote();     // 来源市场状态行（选了才出现）
if(LEGACY){
  // 回滚开关：?legacy=1 = 旧行为，页面一加载就拉全量索引。
  setHint('');
  out.innerHTML = '<div class="sub">' + esc(Tr('home.loading')) + '</div>';
  loadIndex().then(ok => { if(ok) render(); });
} else if(initial){
  // ?q= 深链：立即加载（加载完直接出结果）。
  trackSearchSubmit(initial);
  startSearch();
}
// v0.10.2：空闲时预热类别词表（≈7 KB gz），首次输入「退烧药」这类词时不用等。
if(!LEGACY){ try{ setTimeout(loadCatx, 0); }catch(e){} }
"""


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


# 2026-11-13 task-42：内部占位符/桶键绝不允许进渲染产物。
# 事故：成分页「未公开规格的记录」段直接 esc() 了桶键 → 页面显示 `__mah__:卫材…`。
_INTERNAL_TOKEN_RE = re.compile(r"__mah__:|__no_trade__|@@[A-Z_]+@@")


def _assert_no_internal_tokens(page_html: str, where: str) -> str:
    """构建期守卫：页面上出现内部占位符就中止构建（宁可失败，不发布脏文案）。"""
    m = _INTERNAL_TOKEN_RE.search(page_html or "")
    if m:
        ctx = (page_html or "")[max(0, m.start() - 90):m.start() + 90].replace("\n", " ")
        raise SystemExit(f"{where} 渲染产物含内部占位符 {m.group(0)!r}，构建中止"
                         f"（上下文：…{ctx}…）；检查 NO_TRADE/MAH_PREFIX 是否直接输出")
    return page_html


def _bucket_key_html(key: str, T: dict) -> str:
    """内部桶键 → 人话（task-42）：`__no_trade__` → 无商品名；`__mah__:X` → 厂家：X。"""
    if key == "__no_trade__":
        return ('<span class="m-brand st-badge st-unknown brand-none" data-brand="0" '
                f'data-i18n="brand.none">{esc(T.get("brand.none", "No trade name"))}</span>')
    if key.startswith("__mah__:"):
        name = key[len("__mah__:"):]
        shown = name if len(name) <= 28 else name[:27] + "…"
        return (f'<span class="m-brand m-mah" data-brand="0" title="{esc(name)}">'
                f'<span class="mah-k" data-i18n="brand.mah">'
                f'{esc(T.get("brand.mah", "Manufacturer:"))}</span> {esc(shown)}</span>')
    return esc(key)


def key_file(key: str) -> str:
    """文件名尽量保留可读性（含中文），只替换路径非法字符。

    NHSA 的 CSV 里混进了控制字符（例如「糠酸莫米松乳膏\\x02」），
    不剥掉会让 Windows 直接抛 OSError，整个建站中断。
    """
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", key or "")
    s = re.sub(r'[\\/:*?"<>|\s]+', "-", cleaned.strip()).strip("-.")
    if len(s) > 80:
        s = s[:60] + "-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
    if not s:
        s = "k-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:10]
    return s + ".html"


def _page_meta(lang: str, meta_key: str | None) -> tuple[str, str]:
    if not meta_key:
        return "", ""
    D = I18N.get(lang, I18N["en"])
    return (D.get(f"meta.{meta_key}.title", ""), D.get(f"meta.{meta_key}.desc", ""))


TERMS_SUB_IDS: set[str] = set()
SUB_NAME_LANG: dict[str, str] = {}   # v0.9.4 name_lang：base 名语言（仅展示，不改名）
# v0.11.6 task-1（T12 C5）：成分自己的中文名（substance.inn_zh）只在这里装一次，
# 成分页（H1 下方）/ 品牌页（成分卡、配方差异表）都读同一个映射，页面之间不许各写一套。
SUB_ZH: dict[str, str] = {}
BILINGUAL_TRANS: dict = {}


def _sub_zh_name(sid: str) -> str:
    """成分自己的中文名——品牌页与成分页共用的唯一入口（T12 C5）。

    用法边界（对应 2026-11-13 用户评审 C1）：
      · 只有 `substance.inn_zh` 里**真有 CJK** 才返回，绝不硬翻、不音译；
      · 返回值贴在**成分**旁（成分页 H1 下方、品牌页成分卡、配方差异表）；
      · 拿到非空值就说明「这个成分有中文名」，页面不得再给它贴「无中文名」徽标——
        那个徽标属于**名称**（商品名/通用名的写法），不属于成分。

    SUB_ZH 由 main() 用 load_substance_zh() 在入库后一次性填好。
    """
    zh = (SUB_ZH.get(sid) or "").strip()
    return zh if any("\u4e00" <= ch <= "\u9fff" for ch in zh) else ""


def load_substance_zh(db: sqlite3.Connection) -> dict[str, str]:
    """从 `substance.inn_zh` 装载成分中文名映射（唯一数据源，T12 C5）。"""
    SUB_ZH.clear()
    for sid, zh in db.execute("SELECT substance_id, inn_zh FROM substance"):
        zh = (zh or "").strip()
        if zh:
            SUB_ZH[sid] = zh
    return SUB_ZH

# v0.8.1：双语对照显示（独立脚本，避免改动 i18n.js 模板；所有页面 defer 加载）
BILINGUAL_JS = r"""
(function(){
  var T = window.T || function(k){ return k; };
  var TERMS = null, SHOW = true, OBS = null, OUT = null;
  try {
    var saved = localStorage.getItem('dsh.showOrig');
    SHOW = (saved === '0') ? false : (saved === '1') ? true : (window.LANG !== 'en');
  } catch(e) { SHOW = (window.LANG !== 'en'); }
  function url(){
    var pre = (typeof window.DSH_PREFIX === 'string') ? window.DSH_PREFIX : '';
    return pre + 'data/terms.json';
  }
  function load(){
    if(TERMS) return Promise.resolve(TERMS);
    return fetch(url()).then(function(r){ return r.json(); }).then(function(d){
      TERMS = d; expose(); return d;
    }).catch(function(){ return null; });
  }
  function expose(){ try { window.BILINGUAL_TERMS = TERMS; } catch(e) {} }
  function srcLabel(s){
    if(!s) return '';
    var k = 'bilingual.source.' + s;
    var v = T(k);
    return (v === k) ? s : v;
  }
  function applyOne(el){
    var sid = el.getAttribute('data-sub-ingredient');
    var orig = el.getAttribute('data-sub-orig');
    if(orig === null || orig === undefined){
      orig = el.textContent || '';
      el.setAttribute('data-sub-orig', orig);
    }
    el.querySelectorAll('.tr-badge,.tr-ver,.tr-orig').forEach(function(n){ n.remove(); });
    var inH1 = el.closest && el.closest('h1');
    var srcEl = inH1 ? document.querySelector('[data-sub-src="' + sid + '"]') : null;
    var ent = (TERMS && TERMS.sub && TERMS.sub[sid]) || null;
    var tr = ent && ent[window.LANG];
    if(!tr || !tr.n){
      el.textContent = orig;
      if(srcEl) srcEl.textContent = '';
      return;
    }
    el.textContent = tr.n;
    if(inH1){
      // v0.9.1 P1：H1 只留药名；来源/版本移到 H1 下方的 .sub，避免可访问名被污染。
      if(srcEl){
        srcEl.textContent = (tr.s ? srcLabel(tr.s) : '') + (tr.v ? ' · v' + tr.v : '');
      }
      return;
    }
    var badge = document.createElement('span');
    badge.className = 'tr-badge';
    badge.textContent = srcLabel(tr.s);
    if(tr.u) badge.title = tr.u;
    el.appendChild(badge);
    if(tr.v){
      var ver = document.createElement('span');
      ver.className = 'tr-ver';
      ver.textContent = 'v' + tr.v;
      el.appendChild(ver);
    }
    if(SHOW && orig && orig !== tr.n){
      var o = document.createElement('span');
      o.className = 'tr-orig';
      o.textContent = ' (' + orig + ')';
      el.appendChild(o);
    }
  }
  function renderNames(){
    document.querySelectorAll('.nm[data-n-en]').forEach(function(el){      var en = el.getAttribute('data-n-en') || '';
      var zh = el.getAttribute('data-n-zh') || '';
      var zhh = el.getAttribute('data-n-zhh') || '';
      var es = el.getAttribute('data-n-es') || '';
      var lang = window.LANG || 'en';
      // v0.10.2：缺当前语言名不再把「暂无中文名」拼进名字（会进链接可访问名，
      // 且每个盐型各出现一次）。改由 applyNameLangBadges() / markAtcRowGaps()
      // 在名字**之后**放一枚徽章，ATC/大类行每行只标一次，盐型不单独标。
      if(lang === 'zh') el.textContent = zh || en;
      else if(lang === 'zh-Hant') el.textContent = zhh || en;
      else if(lang === 'es') el.textContent = es || en;
      else el.textContent = en;
    });
  }
  window.renderBilingualNames = renderNames;
  function render(){
    if(!TERMS) { renderNames(); return; }
    if(OBS) OBS.disconnect();
    renderNames();
    document.querySelectorAll('[data-sub-ingredient]').forEach(applyOne);
    var note = T('bilingual.brand_note');
    document.querySelectorAll('[data-brand]').forEach(function(el){
      if(!note || note.indexOf('bilingual.') === 0) return;
      // v0.8.4：保留全名 title，把「非翻译」说明附加在后面（不覆盖）
      var full = el.getAttribute('data-title-full');
      if(full === null){
        full = el.getAttribute('title') || '';
        el.setAttribute('data-title-full', full);
      }
      el.setAttribute('title', full ? (full + ' — ' + note) : note);
    });
    var cb = document.getElementById('bilOrig');
    if(cb) cb.checked = SHOW;
    // task-114：英文副标题在英文界面隐藏（避免重复）
    document.querySelectorAll('.cat-en').forEach(function(el){
      el.style.display = (window.LANG === 'en' || !SHOW) ? 'none' : '';
    });
    if(OBS && OUT) OBS.observe(OUT, {childList: true, subtree: true});
  }
  function injectToggle(){
    if(document.getElementById('bilToggle')) return;
    var nav = document.querySelector('header nav');
    if(!nav) return;
    var lab = document.createElement('label');
    lab.id = 'bilToggle';
    lab.className = 'bil-toggle';
    lab.innerHTML = '<input type="checkbox" id="bilOrig"> <span></span>';
    lab.querySelector('span').textContent = T('bilingual.toggle');
    // v0.9.8 task-13：新壳把 .langs 放在 nav 外，开关改插到 header 里的 langs 之前，
    // 避免它变成第 6 个导航项（旧壳 langs 在 nav 内，行为不变）。
    var langs = nav.querySelector('.langs') || document.querySelector('header .langs');
    if(langs && langs.parentNode){ langs.parentNode.insertBefore(lab, langs); }
    else { nav.appendChild(lab); }
    var cb = lab.querySelector('input');
    cb.checked = SHOW;
    cb.addEventListener('change', function(){
      SHOW = cb.checked;
      try { localStorage.setItem('dsh.showOrig', SHOW ? '1' : '0'); } catch(e) {}
      render();
    });
  }
  function initNavToggle(){
    if(document.getElementById('navToggle')) return;
    var header = document.querySelector('header');
    var nav = header ? header.querySelector('nav') : null;
    if(!header || !nav) return;
    var b = document.createElement('button');
    b.id = 'navToggle';
    b.type = 'button';
    b.className = 'nav-toggle';
    b.setAttribute('aria-label', T('nav.menu'));
    b.setAttribute('aria-expanded', 'false');
    b.textContent = '\u2630';
    var wrap = header.querySelector('.wrap') || header;
    wrap.insertBefore(b, nav);
    b.addEventListener('click', function(){
      var open = header.classList.toggle('nav-open');
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  function initMatrixFilters(){
    document.querySelectorAll('.matwrap table.matrix').forEach(function(table){
      if(table.getAttribute('data-mf-init')) return;
      table.setAttribute('data-mf-init', '1');
      var wrap = table.closest('.matwrap');
      if(!wrap) return;
      var ths = Array.from(table.querySelectorAll('thead th[data-country]'));
      var rows = Array.from(table.querySelectorAll('tbody tr'));
      var countries = ths.map(function(th){ return th.getAttribute('data-country'); });
      // v0.9.0 task-6：默认只显示 3 个市场列（产品最多 + 当前语言市场 + 第二多）；
      // 其余市场由筛选器国家多选加入；mk=CN,TW 可分享，localStorage 记忆。
      var LANG_MARKET = {en: 'US', es: 'ES', zh: 'CN', 'zh-Hant': 'TW'};
      var colCount = {};
      rows.forEach(function(tr){
        countries.forEach(function(c){
          var td = tr.querySelector('td[data-country="' + c + '"]');
          if(td && (td.querySelector('.m-brand') || td.querySelector('.brand-none'))){
            colCount[c] = (colCount[c] || 0) + 1;
          }
        });
      });
      function defaultCols(){
        // v0.9.1 task-22：优先用服务端已渲染的默认列，避免 JS 再改列造成 CLS。
        var pre = Array.prototype.map.call(
          document.querySelectorAll('th[data-defcol="1"]'),
          function(th){ return th.getAttribute('data-country'); }
        ).filter(function(c){ return c && countries.indexOf(c) >= 0; });
        if(pre.length) return pre.slice(0, 3);
        var order = countries.slice().sort(function(a, b){
          return (colCount[b] || 0) - (colCount[a] || 0);
        });
        var out = [];
        [order[0], LANG_MARKET[window.LANG] || '', order[1]].forEach(function(c){
          if(c && countries.indexOf(c) >= 0 && out.indexOf(c) < 0) out.push(c);
        });
        return out.slice(0, 3);
      }
      var forms = {}, releases = {};
      rows.forEach(function(tr){
        var f = tr.getAttribute('data-form') || '';
        var r = tr.getAttribute('data-release') || '';
        if(f) forms[f] = 1;
        if(r && r !== 'none') releases[r] = 1;
      });
      var T = window.T || function(k){ return k; };
      function opt(v, label){ var o = document.createElement('option'); o.value = v; o.textContent = label; return o; }
      // v0.9.8 task-13（P0-9）：筛选器默认收起；details 在客户端包，长尾页静态 0 增量。
      var det = document.createElement('details');
      det.className = 'mf-details';
      var sumEl = document.createElement('summary');
      sumEl.textContent = T('matrix.filters');
      det.appendChild(sumEl);
      var box = document.createElement('section');
      box.className = 'matrix-filters';
      box.innerHTML = '<div class="mf-head"><span class="mf-title"></span>'
        + '<span class="mf-count" aria-live="polite"></span>'
        + '<button type="button" class="mf-toggle" aria-expanded="false"></button></div>'
        + '<div class="mf-panel"></div>';
      det.appendChild(box);
      box.querySelector('.mf-title').textContent = T('matrix.filters');
      box.querySelector('.mf-toggle').textContent = T('matrix.mobile_filters');
      var panel = box.querySelector('.mf-panel');
      // 国家多选
      var cf = document.createElement('div'); cf.className = 'mf-field';
      cf.innerHTML = '<span></span><div class="mf-countries"></div>';
      cf.querySelector('span').textContent = T('matrix.country');
      var cbox = cf.querySelector('.mf-countries');
      countries.forEach(function(c){
        var lab = document.createElement('label');
        var cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = true;
        cb.setAttribute('data-mf-country', c);
        lab.appendChild(cb); lab.appendChild(document.createTextNode(' ' + c));
        cbox.appendChild(lab);
      });
      var ctrl = document.createElement('div'); ctrl.className = 'mf-country-actions';
      var allBtn = document.createElement('button'); allBtn.type = 'button'; allBtn.className = 'mf-reset';
      allBtn.setAttribute('data-mf-all', '1'); allBtn.textContent = T('matrix.country_all');
      var clearBtn = document.createElement('button'); clearBtn.type = 'button'; clearBtn.className = 'mf-reset';
      clearBtn.setAttribute('data-mf-clear', '1'); clearBtn.textContent = T('matrix.country_clear');
      ctrl.appendChild(allBtn); ctrl.appendChild(clearBtn); cbox.appendChild(ctrl);
      panel.appendChild(cf);
      // 剂型
      var ff = document.createElement('label'); ff.className = 'mf-field';
      ff.innerHTML = '<span></span><select data-mf-form></select>';
      ff.querySelector('span').textContent = T('matrix.form');
      var fsel = ff.querySelector('select');
      fsel.appendChild(opt('', T('matrix.all')));
      Object.keys(forms).sort().forEach(function(f){
        // v0.10.2：剂型下拉显示四语标签（原来显示英文原码 effervescent / tablet）
        var lb = T('form.' + f);
        fsel.appendChild(opt(f, (lb && lb.indexOf('form.') !== 0) ? lb : f));
      });
      panel.appendChild(ff);
      // 释放
      var rf = document.createElement('label'); rf.className = 'mf-field';
      rf.innerHTML = '<span></span><select data-mf-rel></select>';
      rf.querySelector('span').textContent = T('matrix.release');
      var rsel = rf.querySelector('select');
      rsel.appendChild(opt('', T('matrix.all')));
      Object.keys(releases).sort().forEach(function(r){ rsel.appendChild(opt(r, r)); });
      panel.appendChild(rf);
      // 规格搜索
      var sf = document.createElement('label'); sf.className = 'mf-field';
      sf.innerHTML = '<span></span><input type="search" data-mf-spec>';
      sf.querySelector('span').textContent = T('matrix.spec_search');
      var sinp = sf.querySelector('input');
      panel.appendChild(sf);
      // 重置
      var resetWrap = document.createElement('div'); resetWrap.className = 'mf-field';
      var reset = document.createElement('button'); reset.type = 'button'; reset.className = 'mf-reset';
      reset.textContent = T('matrix.reset');
      resetWrap.appendChild(reset); panel.appendChild(resetWrap);
      var note = document.createElement('p'); note.className = 'sub matrix-sort-note';
      note.textContent = T('matrix.sort_note');
      var slot = wrap.previousElementSibling;
      if(slot && slot.classList.contains('mf-slot')){
        slot.appendChild(det);
        slot.appendChild(note);
      }else{
        wrap.parentNode.insertBefore(det, wrap);
        wrap.parentNode.insertBefore(note, wrap);
      }
      function current(){
        var cc = Array.from(cbox.querySelectorAll('input[type=checkbox]'));
        var sel = cc.filter(function(cb){ return cb.checked; })
                    .map(function(cb){ return cb.getAttribute('data-mf-country'); });
        return {countries: sel, form: fsel.value, rel: rsel.value,
                spec: sinp.value.trim().toLowerCase(), all: cc.map(function(cb){ return cb.getAttribute('data-mf-country'); })};
      }
      function apply(updateURL){
        var s = current();
        var visible = 0;
        rows.forEach(function(tr){
          var ok = true;
          if(s.form && (tr.getAttribute('data-form') || '') !== s.form) ok = false;
          if(s.rel && (tr.getAttribute('data-release') || '') !== s.rel) ok = false;
          if(s.spec && (tr.getAttribute('data-spec') || '').toLowerCase().indexOf(s.spec) < 0) ok = false;
          // v0.10.2 task-4：「首屏可见列全空」的行默认不渲染；一旦它所在的隐藏市场被
          // 加入列（?mk= 或下面的「加为一列」按钮），这一行就应当出现。
          // 注意：CSS 里 `tr[data-hide-empty]` 是 display:none，所以显示时必须写
          // 明确的 'table-row'（置空 '' 会退回 CSS 的 none）。
          if(tr.getAttribute('data-hide-empty') === '1'){
            var hid = (tr.getAttribute('data-hidden-mk') || '').split(',');
            var shownNow = hid.some(function(c){ return c && s.countries.indexOf(c) >= 0; });
            ok = ok && shownNow;
            tr.style.display = ok ? 'table-row' : 'none';
          }else{
            tr.style.display = ok ? '' : 'none';
          }
          if(ok) visible++;
        });
        // 「另有 N 个…」提示：全部显示出来后就不再提示（数字是构建期按默认列算的）
        var boxNR = document.querySelector('.matrix-hidden-rows');
        if(boxNR){
          var stillHidden = rows.some(function(tr){
            return tr.getAttribute('data-hide-empty') === '1' && tr.style.display === 'none';
          });
          boxNR.style.display = stillHidden ? '' : 'none';
        }
        var mobile = window.matchMedia && window.matchMedia('(max-width:719px)').matches;
        ths.forEach(function(th){
          var c = th.getAttribute('data-country');
          var show = s.countries.indexOf(c) >= 0;
          th.style.display = show ? (mobile ? '' : 'table-cell') : 'none';
          rows.forEach(function(tr){
            Array.from(tr.children).forEach(function(td){
              if(td.getAttribute('data-country') === c){
                td.style.display = show ? (mobile ? '' : 'table-cell') : 'none';
              }
            });
          });
        });
        var cnt = box.querySelector('.mf-count');
        if(!s.countries.length){
          cnt.textContent = T('matrix.empty_markets');
          cnt.classList.add('mf-warn');
          cnt.setAttribute('role', 'status');
        }else{
          cnt.classList.remove('mf-warn');
          cnt.textContent = T('matrix.showing').replace('{n}', visible).replace('{total}', rows.length)
            + ' · ' + T('matrix.market_count')
              .replace('{shown}', s.countries.length).replace('{total}', s.all.length);
          if(sumEl){
            sumEl.textContent = T('matrix.filters') + ' · ' + visible + '/' + rows.length
              + ' · ' + s.countries.length + '/' + s.all.length;
          }
        }
        if(updateURL){
          try{
            var p = new URLSearchParams(location.search);
            s.form ? p.set('mform', s.form) : p.delete('mform');
            s.rel ? p.set('mrel', s.rel) : p.delete('mrel');
            s.spec ? p.set('mspec', sinp.value.trim()) : p.delete('mspec');
            s.countries.length ? p.set('mk', s.countries.join(',')) : p.delete('mk');
            p.delete('mcountry');
            history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p.toString() : '') + location.hash);
            try{ localStorage.setItem('dsh.matrix.mk', s.countries.join(',')); }catch(e){}
          }catch(e){}
        }
      }
      // URL / localStorage / 默认 3 列初值
      var selected = [];
      try{
        var q = new URLSearchParams(location.search);
        var rawMk = q.get('mk') || q.get('mcountry') || '';
        selected = rawMk.split(',').filter(function(c){ return countries.indexOf(c) >= 0; });
        if(q.get('mform')) fsel.value = q.get('mform');
        if(q.get('mrel')) rsel.value = q.get('mrel');
        if(q.get('mspec')) sinp.value = q.get('mspec');
      }catch(e){}
      if(!selected.length){
        try{
          var stored = localStorage.getItem('dsh.matrix.mk') || '';
          selected = stored.split(',').filter(function(c){ return countries.indexOf(c) >= 0; });
        }catch(e){}
      }
      if(!selected.length) selected = defaultCols();
      cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){
        cb.checked = selected.indexOf(cb.getAttribute('data-mf-country')) >= 0;
      });
      fsel.addEventListener('change', function(){ apply(true); });
      rsel.addEventListener('change', function(){ apply(true); });
      sinp.addEventListener('input', function(){ apply(true); });
      cbox.addEventListener('change', function(){ apply(true); });
      allBtn.addEventListener('click', function(){
        cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){ cb.checked = true; });
        apply(true);
      });
      clearBtn.addEventListener('click', function(){
        cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){ cb.checked = false; });
        apply(true);
      });
      reset.addEventListener('click', function(){
        var defs = defaultCols();
        cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){
          cb.checked = defs.indexOf(cb.getAttribute('data-mf-country')) >= 0;
        });
        fsel.value = ''; rsel.value = ''; sinp.value = '';
        apply(true);
      });
      box.querySelector('.mf-toggle').addEventListener('click', function(){
        var open = box.classList.toggle('mf-open');
        this.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      // v0.10.2 task-4：「另有 N 个规格/剂型仅在 US · GB 有记录」后面的市场按钮 ——
      // 点一下就把该市场加进列（走同一套 ?mk= 机制，可分享），对应行随之出现。
      var noteHost = wrap.parentNode || document;
      Array.prototype.forEach.call(noteHost.querySelectorAll('[data-mk-add]'), function(btn){
        btn.addEventListener('click', function(){
          var c = btn.getAttribute('data-mk-add');
          var cb = cbox.querySelector('input[data-mf-country="' + c + '"]');
          if(!cb){ return; }
          cb.checked = true;
          apply(true);
          var nr = noteHost.querySelector('.matrix-hidden-rows');
          if(nr) nr.scrollIntoView ? nr.scrollIntoView({block: 'nearest'}) : null;
        });
      });
      apply(false);
    });
  }
  function start(){
    initNavToggle();
    injectToggle();
    initMatrixFilters();
    renderNames();
    load().then(render);
    OUT = document.getElementById('out');
    if(OUT && window.MutationObserver){
      OBS = new MutationObserver(function(){ if(TERMS) render(); });
      OBS.observe(OUT, {childList: true, subtree: true});
    }
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
  window.addEventListener('load', render);
  window.applyBilingualTerms = render;
})();
"""


def build_terms_json(db: sqlite3.Connection) -> dict[str, int]:
    """v0.8.1：从 ingredient_names_i18n.csv 生成客户端/页面用 data/terms.json。

    规则：只收 display_default_<lang>=1 且 machine_translated=0 的译名；无译名不写。
    """
    terms: dict = {"sub": {}, "meta": {"version": "", "counts": {}}}
    global TERMS_SUB_IDS
    path = ROOT / "data" / "ingredient_names_i18n.csv"
    counts: dict[str, int] = {}
    version = ""
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                sid = (row.get("substance_id") or "").strip()
                if not sid:
                    continue
                ent: dict = {"en": (row.get("inn_en") or "").strip()}
                for lang, nk, sk, uk, ck, dk in (
                        ("zh", "name_zh", "source_zh", "source_url_zh", "confidence_zh",
                         "display_default_zh"),
                        ("es", "name_es", "source_es", "source_url_es", "confidence_es",
                         "display_default_es"),
                        ("zh-Hant", "name_zh_hant", "source_zh_hant", "source_url_zh_hant",
                         "confidence_zh_hant", "display_default_zh_hant"),
                        ("pt", "name_pt", "source_pt", "source_url_pt", "confidence_pt",
                         "display_default_pt")):
                    if (row.get(dk) or "0").strip() != "1":
                        continue
                    if (row.get("machine_translated") or "0").strip() == "1":
                        continue
                    name = (row.get(nk) or "").strip()
                    if not name:
                        continue
                    ent[lang] = {"n": name, "s": (row.get(sk) or "").strip(),
                                 "u": (row.get(uk) or "").strip(),
                                 "c": (row.get(ck) or "").strip(),
                                 "v": (row.get("version") or "").strip()}
                    counts[lang] = counts.get(lang, 0) + 1
                if len(ent) > 1:
                    terms["sub"][sid] = ent
                    version = version or (ent.get("zh") or ent.get("es") or {}).get("v", "")
    terms["meta"]["version"] = version
    terms["meta"]["counts"] = counts
    TERMS_SUB_IDS = set(terms["sub"])
    global BILINGUAL_TRANS
    BILINGUAL_TRANS = terms
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    (OUT / "data" / "terms.json").write_text(
        json.dumps(terms, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return counts


# v0.9.6 task-149：长尾 name 页公共壳瘦身（77,058 页 × 782 B ≈ 57.5 MiB，实测）。
# 只处理「壳」，正文一个字节都不动；四条规则各自可逆，改回 slim=False 即恢复原样。
_SLIM_JSONLD_RE = re.compile(
    r'<script type="application/ld\+json">\{"@context":"https://schema\.org",'
    r'"@type":"WebSite".*?</script>', re.S)
_SLIM_DESC_RE = re.compile(r'<meta name="description" content="[^"]*">')
_SLIM_ICON_RE = re.compile(r'<link rel="icon" href="data:image/svg\+xml,[^"]*">')
_WS_BETWEEN_TAGS_RE = re.compile(r">[\r\n\t ]+<")
_WS_RUN_RE = re.compile(r"[\r\n\t ]{2,}")
_TAG_RE = re.compile(r"<[^>]+>")


def _collapse_tag_ws(html: str) -> str:
    """只压「标签内部」的连续空白（属性之间的换行/缩进）。

    文本节点一个空格都不动：站点里有商品名本身带双空格（如
    `ACETA TABLETS  "C.H."`），压了就等于改标题，SEO 与页面口径都会漂。
    """
    return _TAG_RE.sub(lambda m: _WS_RUN_RE.sub(" ", m.group(0)), html)


def _slim_shell(*chunks: str) -> tuple[str, ...]:
    """把一页的「壳」压瘦：head、<body>~正文 之间、正文~</body> 之间三段各自处理。

    - 去掉站点级 WebSite JSON-LD：站点级事实在首页/顶层页已声明，7.7 万长尾页重复声明无收益；
    - 去掉模板化 description：77k 页同构文案对搜索引擎无价值，交给它按正文生成摘要；
    - favicon 的 SVG data URI 换成空 data URI：省 205 B，同时避免长尾页每次访问都请求
      不存在的 /favicon.ico（负缓存之前每页一次 404）；
    - 压掉标签之间的换行缩进、标签内连续空白：header/footer 都是 flex + gap 排版，
      标签间空白不参与渲染，版式与无 JS 可读性不变。

    保留：title / canonical / hreflang / noindex / style.css / boot.js / DSH_PREFIX /
    分析脚本 / 导航 / 页脚署名与免责声明 —— 所以去掉公共壳后剩下的仍是完整可读页面。
    正文 chunk 不传进来，调用方只对首尾两段调用。
    """
    out: list[str] = []
    for idx, chunk in enumerate(chunks):
        if idx == 0:  # head：去掉三类可选块
            chunk = _SLIM_JSONLD_RE.sub("", chunk)
            chunk = _SLIM_DESC_RE.sub("", chunk, count=1)
            chunk = _SLIM_ICON_RE.sub('<link rel="icon" href="data:,">', chunk, count=1)
        chunk = _WS_BETWEEN_TAGS_RE.sub("><", chunk)
        # chunk 边界都落在标签边界上，首尾空白同样只是排版空白
        out.append(_collapse_tag_ws(chunk).strip())
    return tuple(out)


# ── v0.9.8 task-13（UI 批次 A-2）：统一外壳 ────────────────────────────────
# 顶层约 30 页静态输出新壳（5 项导航 + `<details>` 面板 + 移动底栏 + 语言常显）；
# 121k 长尾页保持原壳不动（每页静态增量 0 B），新壳由 assets/boot.js 运行时注入，
# 两边共用下面同一份模板（boot.js 里把根前缀写成 __R__ 占位）。
SHELL_MARKETS = (("US", "home.us"), ("CN", "home.cn"), ("GB", "home.gb"), ("CA", "home.ca"),
                 ("AU", "home.au"), ("ES", "home.es"), ("TW", "home.tw"), ("HK", "home.hk"),
                 ("MX", "home.mx"), ("SG", "home.sg"), ("EU", "home.eu"))
SHELL_LANGS = ("en", "es", "zh", "zh-Hant")


def _shell_cat_links(prefix: str, limit: int = 99) -> str:
    """类别面板：消费者大类（沿用 .lang-block 四语块，无 JS 也有英文）。"""
    return "".join(
        f'<a href="{prefix}cat/{cat["id"]}.html">' + "".join(
            f'<span class="lang-block" data-lang-block="{lbl}">{esc(cat["labels"][lbl])}</span>'
            for lbl in SHELL_LANGS) + "</a>"
        for cat in CONSUMER_CATEGORIES[:limit])


def _shell_market_links(prefix: str) -> str:
    """市场面板：10 个国别市场 + EU 区域层，锚到覆盖页对应行（覆盖页每行有 id="market-XX"）。"""
    return "".join(
        f'<a href="{prefix}coverage.html#market-{cc}">'
        f'<span data-i18n="{key}">{esc(I18N["en"].get(key, cc))}</span>'
        f'<span class="meta">{cc}</span></a>'
        for cc, key in SHELL_MARKETS)


def _nav_active(canonical_rel: str) -> str:
    """顶层页当前导航项：search / categories / coverage / about。"""
    rel = (canonical_rel or "").strip()
    if rel.startswith(("atc", "cat/")):
        return "categories"
    if rel.startswith("coverage"):
        return "coverage"
    if rel.startswith(("about", "glossary", "confused", "warn", "whats-new")):
        return "about"
    return "search"


def _shell_nav_html(prefix: str, active: str = "search", sw: str = "") -> str:
    """桌面 5 项导航（语言/类别快捷键在 _shell_right）。"""
    on = ' class="on" aria-current="page"'
    return f"""<nav class="sn" data-shell="1" aria-label="Primary navigation" data-i18n-aria="nav.primary">
    <a href="{prefix}index.html" data-i18n="nav.search"{on if active == 'search' else ''}>Search</a>
    <details class="sn-dd"><summary data-i18n="nav.categories">Categories</summary>
      <div class="sn-panel"><div class="sn-cats">{_shell_cat_links(prefix)}</div>
        <div class="sn-foot"><a href="{prefix}atc.html" data-i18n="nav.all_categories">All categories &amp; ATC</a></div></div>
    </details>
    <details class="sn-dd"><summary data-i18n="nav.markets">Markets</summary>
      <div class="sn-panel"><div class="sn-mkts">{_shell_market_links(prefix)}</div>
        <div class="sn-foot"><a href="{prefix}coverage.html" data-i18n="nav.coverage">Coverage &amp; freshness</a></div></div>
    </details>
    <a href="{prefix}coverage.html" data-i18n="nav.coverage" data-coverage="1"{on if active == 'coverage' else ''}>Coverage</a>
    <details class="sn-dd"><summary data-i18n="nav.about">About</summary>
      <div class="sn-panel"><div class="sn-about">
        <a href="{prefix}about.html" data-i18n="nav.about">About</a>
        <a href="{prefix}glossary.html" data-i18n="nav.glossary">Glossary</a>
        <a href="{prefix}whats-new.html" data-i18n="nav.whatsnew">What's new</a>
        <a href="{prefix}warn.html" data-i18n="nav.warn">Warnings</a>
        <a href="{prefix}confused.html" data-i18n="nav.confused">Confused names</a>
      </div></div>
    </details>
  </nav>"""


def _shell_right(prefix: str, sw: str, lang: str = "en") -> str:
    """右上角：类别入口 + 语言下拉；移动端收进「⋯」菜单（v0.10.0）。"""
    labels = {c: l for c, l, _ in LANGS}
    label = labels.get(lang, "EN")
    quick = _shell_cat_links(prefix, limit=8)
    all_link = (f'<div class="sn-foot"><a href="{prefix}atc.html" '
                f'data-i18n="cat.all_link">All categories →</a></div>')
    return f"""<span class="sn-right">
    <details class="qcat"><summary data-i18n="nav.categories">Categories</summary>
      <div class="sn-panel sn-panel-right"><div class="sn-cats compact">{quick}</div>{all_link}</div></details>
    <details class="langdd"><summary><span aria-hidden="true">🌐</span> <span class="lname">{label}</span> ▾</summary>
      <div class="sn-panel sn-panel-right"><div class="lang-menu">{sw}</div></div></details>
    <details class="mmenu"><summary aria-label="More" data-i18n-aria="nav.more">⋯</summary>
      <div class="sn-panel sn-panel-right"><div class="lang-menu">{sw}</div>{all_link}</div></details>
  </span>"""


def _shell_search_html(prefix: str) -> str:
    """2026-11-12 v0.11.2（条目 26）：内容页常驻的简洁搜索栏。

    首页由大搜索框承担，不渲染；其它页（成分 / 商品名 / 分类 / 覆盖 / 关于…）都给一条
    44px 续查入口，提交走 ``index.html?q=``，与首页 ``?q=`` 深链同一条路径（app.js 已有）。
    """
    return f"""<div class="hsearch-row" data-shell="1"><div class="wrap">
  <form class="hsearch" role="search" action="{prefix}index.html" method="get">
    <label class="sr-only" for="hq" data-i18n="nav.search_compact">Search a name</label>
    <input id="hq" name="q" type="search" autocomplete="off" enterkeyhint="search"
      placeholder="Search a name" data-ph="nav.search_compact"
      aria-label="Search a name" data-i18n-aria="nav.search_compact">
    <button type="submit" data-i18n-aria="home.submit" aria-label="Search">→</button>
  </form></div></div>"""


def _shell_tabbar(prefix: str, active: str = "search") -> str:
    """移动底栏：搜索 / 类别 / 覆盖 / 关于（44px 触控 + aria-current）。"""
    items = (("search", "index.html", "tab.search", "Search"),
             ("categories", "atc.html", "tab.categories", "Categories"),
             ("coverage", "coverage.html", "tab.coverage", "Coverage"),
             ("about", "about.html", "tab.about", "About"))
    parts = []
    for aid, href, key, label in items:
        flag = ' class="on" aria-current="page"' if aid == active else ""
        parts.append(f'<a href="{prefix}{href}" data-i18n="{key}"{flag}>{label}</a>')
    return ('<nav class="tabbar" data-shell="1" aria-label="Sections" '
            'data-i18n-aria="nav.sections">'
            + "".join(parts) + "</nav>")


def page(title: str, body: str, prefix: str = "", lang: str = "en",
         alternates: bool = False, meta_key: str | None = None,
         canonical_rel: str = "", alt_rel: str = "", head_js: str = "",
         noindex: bool = False, defer_i18n: bool = True,
         nav_coverage: bool = False, slim: bool = False) -> str:
    """渲染整页 HTML。

    slim=True 只给长尾 name 页用（77,058 页）：保留 title/canonical/hreflang 与导航、页脚，
    去掉重复的结构化数据、模板化 description 与 favicon data URI，并压掉壳里的空白。
    首页 / drug / atc 等 LCP 目标页继续走 slim=False 的原模板。
    """
    ver = f"{LATEST_VERSION} · {LATEST_DATE}" if LATEST_VERSION else "What's new"
    sw = "".join(
        f'<a data-lang="{code}" href="?lang={code}"'
        + (' aria-current="true"' if code == lang else "")
        + f'>{label}</a>' for code, label, _ in LANGS
    )
    alt = ""
    if alternates:
        # hreflang 必须带 GitHub Pages 的项目子路径（线上是 /drug-brand-crossref/），
        # 写 "/es/" 会指到域名根（404）。SITE_URL 已含末尾斜杠。
        alt = ("\n".join(
            f'<link rel="alternate" hreflang="{LANG_HREFLANG[code]}" '
            f'href="{SITE_URL}{LANG_PATH[code]}{alt_rel}">'
            for code, _l, _path in LANGS
        ) + f'\n<link rel="alternate" hreflang="x-default" href="{SITE_URL}{alt_rel}">'
          # v0.7.0：TW 市場的語言區別名（zh-TW → zh-hant 副本）
          + f'\n<link rel="alternate" hreflang="zh-TW" '
            f'href="{SITE_URL}{LANG_PATH["zh-Hant"]}{alt_rel}">')
    if meta_key:
        # v0.5.5：title / description / OG 本地化（根页用 data-i18n-*，副本构建期写死）
        loc_title, loc_desc = _page_meta(lang, meta_key)
        loc_title = loc_title or title
        locale = {"en": "en_US", "es": "es_ES", "zh": "zh_CN",
                  "zh-Hant": "zh_Hant"}.get(lang, "en_US")
        head_title = (f'<title data-i18n-title="meta.{meta_key}.title">'
                      f'{esc(loc_title)}</title>')
        head_extra = (
            f'\n<link rel="canonical" href="{SITE_URL}{canonical_rel}">'
            f'\n<meta name="description" content="{esc(loc_desc)}" '
            f'data-i18n-meta="meta.{meta_key}.desc">'
            f'\n<meta property="og:type" content="website">'
            f'\n<meta property="og:site_name" content="Medicine Brand Cross-Reference">'
            f'\n<meta property="og:title" content="{esc(loc_title)}" '
            f'data-i18n-meta="meta.{meta_key}.title">'
            f'\n<meta property="og:description" content="{esc(loc_desc)}" '
            f'data-i18n-meta="meta.{meta_key}.desc">'
            f'\n<meta property="og:url" content="{SITE_URL}{canonical_rel}">'
            f'\n<meta property="og:locale" content="{locale}">'
            f'\n<meta name="twitter:card" content="summary">')
    else:
        head_title = f'<title>{esc(title)} · Medicine Brand Cross-Reference</title>'
        desc = (f'{title} — Medicine Brand Cross-Reference: locate a medicine by brand '
                f'name, generic name or nickname and compare identity records across countries.')
        head_extra = ((f'\n<link rel="canonical" href="{SITE_URL}{canonical_rel}">'
                       f'\n<link rel="alternate" hreflang="x-default" '
                       f'href="{SITE_URL}{canonical_rel}">')
                      if canonical_rel else "")
        head_extra += f'\n<meta name="description" content="{esc(desc)}">'
    noindex_meta = ('\n<meta name="robots" content="noindex,follow">'
                    if noindex else "")
    favicon = ("""<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' """
               """viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3' fill='%230b6b53'/%3E"""
               """%3Cpath d='M8 3v10M3 8h10' stroke='white' stroke-width='2'/%3E%3C/svg%3E">""")
    site_ld = ('<script type="application/ld+json">'
               '{"@context":"https://schema.org","@type":"WebSite",'
               '"name":"Medicine Brand Cross-Reference",'
               '"alternateName":"药品商品名跨国定位","url":"' + SITE_URL + '"}</script>')
    dataset_link = (f'<link rel="alternate" type="application/ld+json" '
                    f'href="{prefix}dataset.jsonld">')
    head_scripts = (f'<script defer src="{prefix}{BOOT_JS_FILE}"></script>'
                    if defer_i18n else "")
    boot_scripts = ""
    # 壳拆三段（head / 正文前 / 正文后）：slim 只重排首尾两段，body 原样插入，绝不被压缩。
    head = f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{head_title}{alt}{head_extra}{noindex_meta}
{favicon}{site_ld}
<link rel="stylesheet" href="{prefix}{CSS_FILE}">
{head_scripts}
<script>window.DSH_PREFIX={prefix!r};</script>{GC_TAG}{head_js}</head>"""
    # v0.9.8 task-13（UI 批次 A-2）：nav_coverage 就是「顶层页」标记 → 静态新壳；
    # 长尾页仍走下面 else 分支的原壳，字节不变（壳由 boot.js 注入）。
    shell_top = nav_coverage
    if shell_top:
        top = f"""
<body>
<a class="skip-link" href="#main" data-i18n="a11y.skip">Skip to content</a>
<header class="hdr-shell"><div class="wrap">
  <a class="logo" href="{prefix}index.html">Medicine Brand Cross-Reference
    <span class="logo-zh">药品商品名跨国定位</span></a>
  {_shell_nav_html(prefix, _nav_active(canonical_rel))}{_shell_right(prefix, sw, lang)}
</div></header>
<main id="main"><div class="wrap">"""
    else:
        top = f"""
<body>
<a class="skip-link" href="#main" data-i18n="a11y.skip">Skip to content</a>
<header><div class="wrap">
  <a class="logo" href="{prefix}index.html">Medicine Brand Cross-Reference
    <span class="logo-zh">药品商品名跨国定位</span></a>
  <nav><a href="{prefix}index.html" data-i18n="nav.search">Search</a>
    <a href="{prefix}confused.html" data-i18n="nav.confused">Confused names</a>
    <a href="{prefix}warn.html" data-i18n="nav.warn">Warnings</a>
    <a href="{prefix}about.html" data-i18n="nav.about">About</a>
    <a href="{prefix}whats-new.html" data-i18n="nav.whatsnew">What's new</a>
    <a href="{prefix}glossary.html" data-i18n="nav.glossary">Glossary</a>
    <a href="{prefix}atc.html" data-i18n="nav.atc">ATC &amp; categories</a>
    <span class="langs">{sw}</span></nav>
</div></header>
<main id="main"><div class="wrap">"""
    tabbar = _shell_tabbar(prefix, _nav_active(canonical_rel)) if shell_top else ""
    bottom = f"""</div></main>
<footer><div class="wrap">
  <span data-i18n="footer">{esc(I18N['en']['footer'])}</span>
  <span class="foot-links">
    <a href="{prefix}whats-new.html">{ver}</a>
    <a href="{REPORT_REPO}/issues/new?labels=data-error&amp;template=data-error.yml"
       target="_blank" rel="noopener" data-i18n="report.link">Report a data error</a>
    <a href="{REPORT_REPO}/issues" target="_blank" rel="noopener"
       data-i18n="report.all">Known issues</a>
  </span>
</div></footer>
{tabbar}{boot_scripts}
</body></html>"""
    if slim:
        head, top, bottom = _slim_shell(head, top, bottom)
    html = head + top + body + bottom
    # v0.11.5 task-5：页面不再注入页级 ?v=（共享资源改用内容哈希文件名后已无引用者）；
    # 同一份输入两次构建的页面字节完全一致。
    return html


def _localize_copy(html: str, lang: str, meta_key: str, rel: str) -> str:
    """把根页面 HTML 变成 /es/、/zh/、/zh-hant/ 静态副本：本地化 head + 相对链接加 ../ 前缀。"""
    loc_title, loc_desc = _page_meta(lang, meta_key)
    html = re.sub(r'<html lang="[A-Za-z-]+">', f'<html lang="{lang}">', html, count=1)
    if loc_title:
        html = re.sub(r'<title[^>]*>.*?</title>',
                      f'<title data-i18n-title="meta.{meta_key}.title">'
                      f'{esc(loc_title)}</title>', html, count=1, flags=re.S)
    if loc_desc:
        html = re.sub(r'(<meta name="description"[^>]*content=")[^"]*(")',
                      lambda m: m.group(1) + esc(loc_desc) + m.group(2), html, count=1)
        html = re.sub(r'(<meta property="og:description"[^>]*content=")[^"]*(")',
                      lambda m: m.group(1) + esc(loc_desc) + m.group(2), html, count=1)
    if loc_title:
        html = re.sub(r'(<meta property="og:title"[^>]*content=")[^"]*(")',
                      lambda m: m.group(1) + esc(loc_title) + m.group(2), html, count=1)
    copy_url = SITE_URL + LANG_PATH.get(lang, lang + "/") + rel
    html = re.sub(r'(<link rel="canonical" href=")[^"]*(")',
                  lambda m: m.group(1) + copy_url + m.group(2), html, count=1)
    html = re.sub(r'(<meta property="og:url" content=")[^"]*(")',
                  lambda m: m.group(1) + copy_url + m.group(2), html, count=1)
    # 根页相对链接 → ../ 前缀（绝对 URL / #锚点 / ?参数 不改）
    html = re.sub(r'(?P<attr>href|src)="(?P<url>(?![a-zA-Z]+:|#|/|\?)[^"]*)"',
                  lambda m: f'{m.group("attr")}="../{m.group("url")}"', html)
    return html


def _write_with_copies(rel: str, html: str, meta_key: str) -> None:
    """写根页面 + /es/<rel>、/zh/<rel>、/zh-hant/<rel> 静态本地化副本（供 SEO/直接访问）。"""
    (OUT / rel).write_text(html, encoding="utf-8")
    for code, _label, path in LANGS:
        if not path:
            continue
        target = OUT / path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_localize_copy(html, code, meta_key, rel), encoding="utf-8")


# ------------------------------------------------------------ release notes
def _md_inline(text: str) -> str:
    s = esc(text)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)

    def _link(m):
        url = m.group(2)
        # v0.5.5：CHANGELOG 里的相对 docs/ 链接在站点产物里没有对应文件（会 404），
        # 统一改到仓库 blob；中文文件名 percent-encode（/es/、/zh/ 副本同样生效）。
        if url.startswith(("docs/", "../docs/", "./docs/")):
            from urllib.parse import quote
            url = REPORT_REPO + "/blob/main/" + quote(url.lstrip("./"))
        return f'<a href="{url}" target="_blank" rel="noopener">{m.group(1)}</a>'

    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, s)
    return s


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"


def _md_join(parts) -> str:
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and not (_is_cjk(out[-1]) and _is_cjk(p[0])):
            out += " "
        out += p
    return out


def _md_table(rows) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    if len(cells) >= 2 and all(re.fullmatch(r":?-{2,}:?", c) for c in cells[1]):
        head, body = cells[0], cells[2:]
    else:
        head, body = cells[0], cells[1:]
    html = ["<table><thead><tr>"]
    html += [f"<th>{_md_inline(c)}</th>" for c in head]
    html.append("</tr></thead><tbody>")
    for row in body:
        html.append("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in row) + "</tr>")
    html.append("</tbody></table>")
    return "".join(html)


def _md_list(lines, start):
    items = []  # [text, [subitems]]
    i = start
    while i < len(lines):
        m = re.match(r"^(\s*)-\s+(.*)$", lines[i])
        if not m or len(m.group(1)) > 0:
            break
        items.append([m.group(2), []])
        i += 1
        while i < len(lines) and lines[i].strip():
            m2 = re.match(r"^(\s*)-\s+(.*)$", lines[i])
            if m2 and len(m2.group(1)) >= 2:
                sub = [m2.group(2)]
                i += 1
                while (i < len(lines) and lines[i].strip()
                       and not re.match(r"^\s*-\s+", lines[i])):
                    sub.append(lines[i].strip())
                    i += 1
                items[-1][1].append(_md_join(sub))
            elif m2:
                break
            else:
                items[-1][0] = _md_join([items[-1][0], lines[i]])
                i += 1
    html = ["<ul>"]
    for text, subs in items:
        html.append("<li>" + _md_inline(text))
        if subs:
            html.append("<ul>" + "".join(f"<li>{_md_inline(s)}</li>" for s in subs) + "</ul>")
        html.append("</li>")
    html.append("</ul>")
    return "".join(html), i


def _md_block(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append("<p>" + _md_inline(_md_join(para)) + "</p>")
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if line.startswith("### "):
            flush()
            out.append("<h3>" + _md_inline(line[4:].strip()) + "</h3>")
            i += 1
            continue
        if line.lstrip().startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_md_table(rows))
            continue
        if re.match(r"^-\s+", line):
            flush()
            html, i = _md_list(lines, i)
            out.append(html)
            continue
        para.append(line)
        i += 1
    flush()
    return "\n".join(out)


def load_releases() -> list[dict]:
    try:
        text = CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return []
    releases = []
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        m = re.match(r"(v[0-9][^\s]*)\s*[—–-]\s*(\d{4}-\d{2}-\d{2})", head.strip())
        if not m:
            continue
        releases.append({"version": m.group(1), "date": m.group(2),
                         "html": _md_block(body.strip())})
    return releases


def build_whats_new() -> None:
    """v0.5.6：What's new **以 CHANGELOG.md 的全量版本为主列表**。

    data/release_notes_i18n.json 只覆盖到 v0.5.2，旧实现只遍历 JSON 导致
    v0.5.3/v0.5.4/v0.5.5 从正文消失（线上 smoke whats-new-version 失败）。
    现在的规则：
      1) 版本顺序永远以 CHANGELOG.md 为准（最新在上，含全部版本）；
      2) 有 JSON 译文的版本 → 渲染 zh/en/es/zh-Hant 四个语言块（按界面语言只显示一块）；
        （2026-11-13 task-44：原来只渲染三语，zh-Hant 界面按 data-lang-block 显隐会把正文
         全部隐藏；这里补 zh-Hant，缺值时回退 zh。）
      3) 没有译文的版本 → 显示 CHANGELOG 中文原文 + 「译文待补」提示。
    """
    parts = [f'<h1 data-i18n="whatsnew.title">{esc(I18N["en"]["whatsnew.title"])}</h1>',
             f'<div data-i18n-html="whatsnew.intro">{I18N["en"]["whatsnew.intro"]}</div>',
             f'<div class="notice" data-i18n="whatsnew.lang_note">'
             f'{esc(I18N["en"]["whatsnew.lang_note"])}</div>']
    data = None
    try:
        data = json.loads((ROOT / "data" / "release_notes_i18n.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    translations = {}
    if isinstance(data, dict):
        translations = {k: v for k, v in data.items()
                        if k != "_meta" and isinstance(v, dict)}
    pending_html = (f'<p class="sub release-pending" data-i18n="whatsnew.pending">'
                    f'{esc(I18N["en"]["whatsnew.pending"])}</p>')
    for r in load_releases():
        ver = r["version"]
        item = translations.get(ver)
        if item:
            blocks = []
            for lang in ("zh", "en", "es", "zh-Hant"):
                items = item.get(lang) or item.get("zh") or []
                lis = "".join(f"<li>{_md_inline(str(x))}</li>" for x in items)
                blocks.append(f'<div class="lang-block" data-lang-block="{lang}">'
                              f'<ul>{lis}</ul></div>')
            body_html = "".join(blocks)
        else:
            # 无 AI 译文的版本：中文原文 + 三语可见的「译文待补」提示
            body_html = r["html"] + pending_html
        parts.append(
            f'<section class="release"><h2>{esc(ver)}'
            f'<span class="rel-date">{esc(r["date"])}</span></h2>{body_html}</section>')
    html = page("What's new", "\n".join(parts), meta_key="whatsnew", alternates=True,
                canonical_rel="whats-new.html", alt_rel="whats-new.html", nav_coverage=True)
    _write_with_copies("whats-new.html", html, "whatsnew")


def _norm_name(s: str) -> str:
    """名字归一化，只用于比较 key 与成分 INN 是否同一个词。"""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def combo_slug(sids) -> str:
    """成分集合 → 组合页文件名（稳定、可读、长度受控）。"""
    return key_file("+".join(sorted(sids)))


# ── v0.8.3 伪复方 build 层归并：base+salt 视为同一 base 成分（不写 DB）────────
SALT_WORDS = {
    "hydrochloride", "hydrobromide", "sodium", "potassium", "calcium", "magnesium",
    "phosphate", "sulfate", "sulphate", "citrate", "tartrate", "maleate", "fumarate",
    "succinate", "malate", "glutamate", "aspartate", "lactate", "acetate", "carbonate",
    "bicarbonate", "chloride", "iodide", "bromide", "nitrate", "oxide", "hydroxide",
    "hydrate", "dihydrate", "trihydrate", "monohydrate", "sesquihydrate", "anhydrous",
    "mesilate", "mesylate", "besylate", "besilate", "benzoate", "trometamol",
    "tromethamine", "disodium", "dipotassium", "dicalcium", "magnesium",
    "monohydrochloride", "dihydrochloride", "lysine", "arginine", "gluconate",
    "digluconate", "heptanoate", "enantate", "decanoate", "palmitate", "stearate",
    "oleate", "laurate", "propionate", "butyrate", "valerate", "undecylenate",
    "cypionate", "phenylpropionate", "nitrite", "sulfite", "bisulfate", "edetate",
    "gluceptate", "glycinate", "asparto", "pamoate", "embonate", "hemihydrate",
    "dihydrate", "monohydrate", "hyclate", "tetrahydrate", "edisylate", "estolate",
    "taurate", "xinafoate", "furoate", "aceponate", "dipropionate", "diacetate",
    "dibenzoate", "pivalate", "tebutate", "sodium", "potassium",
}
_SALT_ELEMENTS = {"sodium", "potassium", "calcium", "magnesium", "lithium", "iron",
                  "zinc", "copper", "aluminium", "aluminum", "barium", "selenium"}


def _salt_base_of(name: str) -> str:
    toks = _norm_name(name).split()
    while toks and toks[-1] in SALT_WORDS:
        toks.pop()
    return " ".join(toks)


def _sub_base_map(db: sqlite3.Connection) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """v0.8.3 口径：substance_id → base substance_id（同名 canonical + 去盐/水合物，迭代到不动点）。

    返回 (base_of, sub_names)。检索索引与 ATC/大类页共用同一套盐型归并口径，
    避免两个页面把同一成分的盐型显示成多条。
    """
    sub_names: dict[str, tuple[str, str]] = {}
    for sid0, en0, zh0 in db.execute("SELECT substance_id, inn_en, inn_zh FROM substance"):
        sub_names[sid0] = (en0 or "", zh0 or "")
    by_norm: dict[str, str] = {}
    for sid0, (en0, _zh0) in sub_names.items():
        # v0.10.1 热修：_norm_name 只保留 [a-z0-9]，纯中文名会归一成空串；
        # 空串一旦进 by_norm，所有中文名成分都会被映射到同一个 sid
        # （表现为 ATC/大类页里「地喹氯铵」下挂几十个不相关抗生素名）。
        n0 = _norm_name(en0)
        if n0:
            by_norm.setdefault(n0, sid0)
    # 同名重复 substance（如 povidone-iodine / povidone-iodine-<hash>）→ 规范到同一 sid
    canon: dict[str, str] = {}
    for sid0, (en0, _zh0) in sub_names.items():
        n0 = _norm_name(en0)
        canon[sid0] = by_norm.get(n0, sid0) if n0 else sid0
    salt_to_base: dict[str, str] = {}
    for sid0, (en0, _zh0) in sub_names.items():
        if canon.get(sid0) != sid0:
            continue
        toks = _norm_name(en0).split()
        if len(toks) < 2:
            continue
        # 从末尾逐个去掉 salt/hydrate 词，找到存在的 base 即止
        # （不把 "Calcium Chloride" 剥成 "Calcium" 这类无机盐基；元素基跳过）
        while len(toks) > 1 and toks[-1] in SALT_WORDS:
            toks = toks[:-1]
            base = " ".join(toks)
            if base in SALT_WORDS or base in _SALT_ELEMENTS or len(base) < 4:
                continue
            b = by_norm.get(base)
            if b and b != sid0:
                salt_to_base[sid0] = b
                break
    base_of: dict[str, str] = {}
    for sid0 in sub_names:
        cur, seen = sid0, set()
        while cur not in seen:
            seen.add(cur)
            nxt = salt_to_base.get(cur) or canon.get(cur, cur)
            if nxt == cur:
                break
            cur = nxt
        base_of[sid0] = cur
    return base_of, sub_names


# ── v0.6.0：组合页跨市场同组合（输入 data/combo_match_candidates.csv，构建期只读）──
# 归一化规则必须与 etl/build_combo_matches.py 保持一致，否则页面的原始 substance_id
# 集合无法反查到 CSV 里的「归一名数签名」。
_COMBO_SYNONYMS = {
    "paracetamol": "acetaminophen", "glyburide": "glibenclamide",
    "salbutamol": "salbutamol", "albuterol": "salbutamol",
    "adrenaline": "epinephrine", "noradrenaline": "norepinephrine",
    "frusemide": "furosemide", "lignocaine": "lidocaine",
    "hyoscine": "scopolamine", "rifampicin": "rifampin",
    "pethidine": "meperidine", "oestradiol": "estradiol",
    "ethinyloestradiol": "ethinylestradiol", "levothyroxine": "levothyroxine",
    "thyroxine": "levothyroxine",
    "clavulanate": "clavulanic-acid", "clavulanic": "clavulanic-acid",
    "amoxycillin": "amoxicillin", "cefalexin": "cephalexin",
    "cefalotin": "cephalothin", "vitamin-c": "ascorbic-acid",
}
_COMBO_SALT_WORDS = {
    "hydrochloride", "hydrobromide", "bromide", "chloride", "sodium", "potassium",
    "calcium", "magnesium", "zinc", "iron", "ammonium", "sulfate", "sulphate",
    "phosphate", "acetate", "citrate", "tartrate", "maleate", "fumarate",
    "succinate", "malate", "lactate", "gluconate", "nitrate", "mesylate",
    "besylate", "tosylate", "pamoate", "stearate", "palmitate", "propionate",
    "dipropionate", "valerate", "butyrate", "benzoate", "carbonate", "bicarbonate",
    "hydroxide", "oxide", "trihydrate", "dihydrate", "monohydrate", "hemihydrate",
    "anhydrous", "hydrate", "dehydrate", "methyl", "ethyl", "ester", "acid",
    "trometamol", "tromethamine", "meglumine", "lysine", "arginine", "choline",
    "disodium", "dipotassium", "hemisuccinate", "furoate", "cipionate",
    "phenylacetate", "hyclate", "pivoxil", "axetil", "proxetil", "medoxomil",
}
_RE_NONALNUM = re.compile(r"[^a-z0-9]+")


def norm_ingredient(name: str) -> str:
    """英文 INN → 归一成分 key（去括号/盐/酯/水合物 → 同义词；与 ETL 一致）。"""
    s = unicodedata.normalize("NFKC", name or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("/", " ")
    toks = [t for t in _RE_NONALNUM.sub(" ", s).split() if t]
    out = [t for t in toks if t not in _COMBO_SALT_WORDS]
    if not out:
        out = toks
    key = "-".join(out) if out else (name or "").strip().lower()
    return _COMBO_SYNONYMS.get(key, key)


def load_combo_matches() -> dict[str, list[dict]]:
    """data/combo_match_candidates.csv → {signature: [country row, ...]}。"""
    import csv as _csv

    path = ROOT / "data" / "combo_match_candidates.csv"
    out: dict[str, list[dict]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in _csv.DictReader(fh):
            sig = (row.get("signature") or "").strip()
            if sig:
                out.setdefault(sig, []).append(row)
    return out


def load_index(db: sqlite3.Connection):
    """构建检索索引：只收有品牌名的 key。全量一次查询，避免 N+1。"""
    coll = {r[0]: r[1] for r in db.execute("SELECT key_id, level FROM collision")}
    displays: dict[str, str] = {}
    for key_id, raw in db.execute(
        "SELECT key_id, raw FROM name_variant ORDER BY key_id, v_id"
    ):
        displays.setdefault(key_id, raw)

    agg: dict[str, dict] = {}
    mixed_inn: set[str] = set()
    merged_keys: set[str] = set()
    # v0.8.3：base+salt 归并映射（与 ATC/大类页共用同一口径，见 _sub_base_map）
    base_of, sub_names = _sub_base_map(db)
    # 每个产品自己的成分名集合：复方产品在每个成分的通用名 key 下都有一行
    # name_type=inn，但当前这行不一定是那个成分（join 会展开所有成分），
    # 所以要用「产品级」的集合判断，而不是当前行的 inn_en。
    comp_keys: dict[str, set[str]] = {}
    for pid, inn in db.execute(
        """SELECT pc.product_id, s.inn_en
           FROM product_component pc
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN substance s ON s.substance_id = v.substance_id"""
    ):
        comp_keys.setdefault(pid, set()).add(_norm_name(inn))
    for (key_id, pid, country, form_base, dosage_form, sv, su, pv, pu,
         inn_en, inn_zh, atc, sid, mah, rel, ntype, n_ing, pnote, pcat, nl) in db.execute(
        """SELECT pn.key_id, p.product_id, COALESCE(p.country, p.region) AS mk, p.form_base, p.dosage_form,
                  pc.strength_value, pc.strength_unit, pc.per_volume_value, pc.per_volume_unit,
                  s.inn_en, s.inn_zh, s.atc, s.substance_id,
                  p.mah, p.release,
                  pn.name_type,
                  (SELECT COUNT(*) FROM product_component pc2
                   WHERE pc2.product_id = p.product_id) AS n_ing,
                  p.note, p.category, s.name_lang
           FROM product_name pn
           JOIN product p ON p.product_id = pn.product_id
           LEFT JOIN product_component pc ON pc.product_id = p.product_id
           LEFT JOIN variant v ON v.variant_id = pc.variant_id
           LEFT JOIN substance s ON s.substance_id = v.substance_id
           WHERE pn.name_type IN ('trade', 'inn')"""
    ):
        # 复方产品的「成分名」行（name_type=inn 且 key 就是其中一个成分）不能并进
        # 该成分的通用名条目，否则 acetaminophen 条目会把复方里的其他成分、剂量、
        # 厂家全并进来，看起来像一个六成分产品。复方仍按商品名 / 复方全名检索。
        if (ntype == "inn" and n_ing > 1
                and _norm_name(key_id) in comp_keys.get(pid, ())):
            mixed_inn.add(key_id)
            continue
        # v0.8.3：base+salt/canonical 递归归并（如 Alendronate Sodium Trihydrate →
        # Alendronate Sodium → Alendronate），直到不动点，避免只剥一层。
        orig_sid = sid
        sid = base_of.get(sid, sid)
        if sid != orig_sid:
            inn_en, inn_zh = sub_names.get(sid, (inn_en, inn_zh))
            merged_keys.add(key_id)
        a = agg.get(key_id)
        if a is None:
            a = agg[key_id] = {"pids": set(), "c": set(), "subs": [], "subs_zh": [], "s": [],
                               "f": [], "fs": {}, "v": sid, "mah": {}, "trade": False,
                               "sids": set(), "rels": set(), "atc": set(), "export": False,
                               "nl": ""}
        if ntype == "trade":
            a["trade"] = True
        if sid:
            a["sids"].add(sid)
        if a["v"] is None and sid:
            a["v"] = sid
        if not a.get("nl") and nl:
            a["nl"] = nl
        if (pnote and ("出口" in pnote or "Export" in pnote)) or \
                (pcat and "Export" in pcat):
            a["export"] = True
        if atc:
            # v0.6.4 A2：条目涉及的 ATC 码（多成分=数组；客户端按前缀过滤 ATC 搜索）
            a["atc"].add(atc.strip())
        if rel and rel != "none":
            # v0.5.6 A3：该名字下产品的释放机制集合（IR/ER/SR/DR/MR/GITS），空 = 全是常释
            a["rels"].add(rel)
        a["pids"].add(pid)
        a["c"].add(country)
        if inn_en and inn_en not in a["subs"]:
            a["subs"].append(inn_en)
            # v0.5.5：与 x 的分段一一对应的中文名；没有中文名留 ""（客户端逐段回退英文）
            a["subs_zh"].append(inn_zh or "")
        if sv is not None:
            # T10（plan §3.4 ④）：规格串收敛到 _spec_text（含 per_volume，如 960 mg/30 mL），
            # 并按剂型分桶 —— 原来「强度跨剂型拼一条 + f 只留第一个」是「500 mg / 960 mg + 片剂」的根因。
            st = _spec_text(sv, su, pv, pu)
            if st:
                if st not in a["s"]:
                    a["s"].append(st)
                fs = a["fs"].setdefault(form_base or dosage_form or "", [])
                if st not in fs:
                    fs.append(st)
        f = form_base or dosage_form
        if f and f not in a["f"]:
            a["f"].append(f)
        if mah:
            a["mah"][mah] = a["mah"].get(mah, 0) + 1

    # v0.5.6（A3/A1）：盐型上下文 + 已发布 R1/R2 警示 id + 明细桶名。
    # 只做「结果行提示」，不参与 collision 判定；多盐型仅提示，不写「不可互换」
    # （不可互换只来自 dose_warning 的已发布条目）。
    forms_by_sub: dict[str, list[str]] = {}
    has_salt_code = "salt_code" in {r[1] for r in db.execute("PRAGMA table_info(variant)")}
    variant_sql = ("SELECT substance_id, salt, hydrate, ester, salt_code FROM variant"
                   if has_salt_code else
                   "SELECT substance_id, salt, hydrate, ester, '' FROM variant")
    for sid, salt, hyd, est, code in db.execute(variant_sql):
        forms = forms_by_sub.setdefault(sid, [])
        label = (code or "").strip()
        if not label or label in ("mixed", "non_salt"):
            label = (salt or "").strip() or "base"
        if (hyd or "").strip():
            label += " " + hyd.strip()
        if (est or "").strip():
            label += " " + est.strip()
        if label not in forms:
            forms.append(label)
    warn_by_sub: dict[str, list[str]] = {}
    for sid, wid in db.execute(
            """SELECT substance_id, warning_id FROM dose_warning
               WHERE status='published' AND rule IN ('R1','R2')
                 AND substance_id IS NOT NULL
               ORDER BY CASE rule WHEN 'R2' THEN 0 ELSE 1 END, warning_id"""):
        warn_by_sub.setdefault(sid, []).append(wid)

    # v0.9.1 体积策略：组合页门槛（≥2 products 或 ≥2 markets）
    combo_pids: dict[str, set[str]] = defaultdict(set)
    combo_countries: dict[str, set[str]] = defaultdict(set)
    for a in agg.values():
        if len(a["sids"]) > 1:
            slug = combo_slug(a["sids"])
            combo_pids[slug].update(a["pids"])
            combo_countries[slug].update(a["c"])
    COMBO_PAGE_SLUGS.clear()
    COMBO_PAGE_SLUGS.update(
        slug for slug in combo_pids
        if len(combo_pids[slug]) >= 2 or len(combo_countries[slug]) >= 2)

    entries = []
    fam = {}
    for key_id, label, note in db.execute(
        "SELECT nf.key_id, bf.label, bf.note FROM name_family nf"
        " JOIN brand_family bf ON bf.family_id = nf.family_id"
    ):
        fam[key_id] = (label, note)
    for key_id, a in agg.items():
        n = len(a["pids"])
        level = coll.get(key_id, "info")
        # 只由单方产品组成的通用名条目：碰撞视图仍把复方的成分算进来，
        # 这里改回 info，并且不单独成页（直接链到成分页），避免「同名不同药 /
        # 释放机制不同」这类误导性警告。
        # v0.9.0 task-6：trade 名不再因「复方成分名」身份被排除出页面
        # （单包装 trade 名也应可点进轻量页）；只有纯 inn 行才保持原规则。
        pure_inn = ((not a["trade"]) and key_id in mixed_inn
                    and len(a["sids"]) == 1)
        if pure_inn:
            level = "info"
        # v0.8.3：伪复方（base+salt 被并成单 base）不再算多成分碰撞
        if key_id in merged_keys and len(a["sids"]) <= 1:
            level = "info"
        # v0.9.0 task-6：所有 trade 名（含单包装）都建轻量名字页；单包装页 noindex。
        # 体积守卫：默认单包装只收 CN/TW/ES/MX；无成分（名称层）名字页不受守卫限制
        # （v0.9.1 task-28：3,911 个名称层产品需要可点）。
        single_ok = (n >= 2 or not a["sids"] or SINGLE_NAME_PAGE_MARKETS is None
                     or bool(set(a["c"]) & SINGLE_NAME_PAGE_MARKETS))
        # v0.9.1 P0 回归修复：只排除 AU-only 的 name_key；AU+其他国家的名字页保留
        # （原逻辑 "AU" not in c 误杀 3,345 个多国名字，/name/lipitor.html 等旧 URL 404）。
        # v0.11.0：EU 区域层只在「搜索结果 + 成分页 + 覆盖页」出现，不建名字页
        # （647 个新 name_key 若都建页 ≈ +2.7 MB dist；EU 产品每个都能从成分页进）。
        region_only = set(a["c"]) <= {"EU"}
        worth_page = ((not pure_inn) and set(a["c"]) != {"AU"} and not region_only
                      and ((a["trade"] and single_ok) or level == "warning"))
        ordered_mah = sorted(a["mah"].items(), key=lambda kv: (-kv[1], kv[0]))
        first_maker = ordered_mah[0][0] if ordered_mah else ""
        first_info = MAKERS.get(norm_maker(first_maker)) if first_maker else None
        # v0.5.4：结果行「+N」展开用的其它厂家（只存有厂家页的，带 name+slug；
        # 没页的厂家不进索引，前端用 mn 差额显示「另有 K 家暂无页面」）。
        ml: list[list[str]] = []
        for mname, _cnt in ordered_mah[1:]:
            info = MAKERS.get(norm_maker(mname))
            if info and info["has"]:
                ml.append([mname, info["slug"]])
        # v0.5.6：单成分条目才有盐型/警示上下文；复方条目 sl/rl/wi 留空
        sid1 = next(iter(a["sids"])) if len(a["sids"]) == 1 else ""
        # v0.11.5 task-71：英文 INN 作为 name key 时 subs_zh 可能为空，
        # 但该 substance 的 inn_zh 有中文名 → 回填，避免中文界面误标「无中文名」。
        if sid1 and not any((z or "").strip() for z in (a["subs_zh"] or [])[:6]):
            _zh0 = (sub_names.get(sid1) or ("", ""))[1]
            if _zh0:
                a["subs_zh"] = [_zh0]
        forms = forms_by_sub.get(sid1, []) if sid1 else []
        sl_hint = "/".join(forms[:3]) if len(forms) > 1 else ""
        rl_hint = ",".join(sorted(a.get("rels") or [])) if a.get("rels") else ""
        wi_id = (warn_by_sub.get(sid1) or [""])[0] if sid1 else ""
        entry = {
            "k": key_id,
            "d": displays.get(key_id, key_id),
            "c": sorted(a["c"]),
            "x": " + ".join(a["subs"][:6]),
            # v0.5.5：中文成分名数组，与 x 的 " + " 分段平行；全空则不写（回退英文）
            "xz": ([zh for zh in a["subs_zh"][:6]]
                   if any(zh for zh in a["subs_zh"][:6]) else None),
            # v0.6.4 A2：ATC 码数组（最多 8 个；无 ATC 的条目为 None）
            "atc": sorted(a["atc"])[:8] or None,
            "s": a["s"][:6],
            # T10（plan §3.4 ④）：剂型 × 规格成对给出（紧凑串，≤3 组、每组 ≤3 个）。
            # 只有一个剂型的条目**不写** fs（客户端用 s + f 回退）—— 单剂型行行为不变，
            # core.json 少约 2.4 MB（实测 48.7 → 46.3 MB dec）。
            "fs": _fs_pack(a["fs"]),
            # 多剂型时 f = "multi"（客户端改用 matrix.multi_form），单剂型仍给剂型名
            "f": ("multi" if len([fm for fm in a["fs"] if fm]) > 1
                  else (a["f"][0] if a["f"] else "")),
            "l": level,
            "n": n,
            # v0.9.0 task-19：1=该名字是 trade 名；0=只有通用名 → 商品名位置显示「无商品名」
            "t": 1 if a["trade"] else 0,
            "v": a["v"] or "",
            "vs": sorted(a["sids"]) if len(a["sids"]) > 1 else None,
            # v0.9.1 task-28：无成分（名称层）/ Export Only 标记
            "nc": 1 if not a["sids"] else 0,
            "eo": 1 if a["export"] else 0,
            "u": key_file(key_id) if worth_page else "",
            # v0.5.3：复方 → 组合页 URL（成分列点击目标；单成分为空，走 drug 页）
            # combo_slug() 由 key_file() 生成、已含 .html 后缀。
            "cu": ("combo/" + combo_slug(a["sids"]))
                  if len(a["sids"]) > 1 and combo_slug(a["sids"]) in COMBO_PAGE_SLUGS else "",
            "g": fam[key_id][0] if key_id in fam else "",
            "gn": fam[key_id][1] if key_id in fam else "",
            "m": first_maker,
            # v0.5.4：主厂家页 slug（无页为空 → 结果行显示纯文本）
            "mu": first_info["slug"] if first_info and first_info["has"] else "",
            # v0.5.4：「+N」展开列表：[[name, slug], ...]（仅含可点的其它厂家）
            "ml": ml if ml else None,
            "mn": len(a["mah"]),
            # v0.5.6（A1/A3）：明细桶名（懒加载 data/idx/detail-<db>.json）+
            # 盐型提示（多盐型才写）+ 释放机制 + 已发布 R1/R2 警示 id。
            # sl/rl/wi 空值不写，避免 12.7 万条索引每行多背 3 个空串（约 +3 MB）。
            "db": _shard_bucket(key_id),
        }
        if sl_hint:
            entry["sl"] = sl_hint
        if rl_hint:
            entry["rl"] = rl_hint
        if wi_id:
            entry["wi"] = wi_id
        # 加拿大 DPD 的商品名里混着「222 AF EXTRA STRENGTH」这类以数字开头的名字
        # 和「+ SINUS COLD FORMULA」这种被削掉前缀的残名。它们在索引里查得到，
        # 但排到最前面会顶掉真正的品牌，所以打个标记降权（不影响纯字母开头的名字）。
        if "CA" in a["c"] and (key_id[:1].isdigit() or key_id[:1] in "+-/&"):
            entry["q"] = 1
        entries.append(entry)
    entries.sort(key=lambda e: -e["n"])
    return entries


def load_aliases(db: sqlite3.Connection) -> list[dict]:
    """俗称索引：单独一份 aliases.json。

    不塞进商品名索引，因为昵称属于「成分」，不属于某个名字键——塞进去会让
    「两只青蛙」变成一张挂着几千个包装的商品名。
    """
    counts: dict[str, tuple[int, set[str]]] = {}
    for sid, n, countries in db.execute(
        """SELECT v.substance_id, COUNT(DISTINCT p.product_id),
                  GROUP_CONCAT(DISTINCT COALESCE(p.country, p.region))
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           WHERE p.status = 'active'
           GROUP BY v.substance_id"""
    ):
        counts[sid] = (n, set((countries or "").split(",")))
    out = []
    for (alias, norm, sid, zh, label_en, kind, confidence, note, source, inn_en,
         inn_zh, meaning_zh, meaning_en, country, source_url) in db.execute(
        """SELECT a.alias, a.alias_norm, a.substance_id, a.label_zh, a.label_en,
                  a.kind, a.confidence, a.note, a.source, s.inn_en, s.inn_zh,
                  a.meaning_zh, a.meaning_en, a.country, a.source_url
           FROM alias_all a
           LEFT JOIN substance s ON s.substance_id = a.substance_id
           ORDER BY a.alias_id"""
    ):
        n_prod, countries = counts.get(sid, (0, set()))
        display = zh or inn_zh or label_en or inn_en or alias
        out.append({
            "a": alias,
            "n": norm,
            "v": sid,
            "i": inn_en or label_en or alias,
            "x": display,
            "k": kind,
            "cf": confidence or "",
            "hint": note or "",
            "src": source or "",
            "m": meaning_zh or meaning_en or "",
            "me": meaning_en or "",
            "ct": country or "",
            "su": source_url or "",
            "c": sorted(countries),
            "np": n_prod,
        })
    return out


# ── v0.9.6 task-141c：同物异名（data/substance_aliases.csv）──────────────
# 数据层在 CSV 里（24 组异名），站点只读它：成分页多一行「也称」，检索多一张
# 身份卡。名字一律保留原文、不翻译、不改成分页主名；只做身份对应，不判断可互换。
SUBSTANCE_ALIASES_CSV = ROOT / "data" / "substance_aliases.csv"
SUBSTANCE_ALIAS_CAP = 5   # 成分页「也称」每页最多列 5 个别的写法


def _norm_alias(s: str) -> str:
    """与 app.js 的 norm() 逐条同口径：NFKC → 小写 → 去组合音标 → 压空白。

    注意 JS 端同样是 NFKC（组合式）后才删 U+0300–U+036F，所以预组合重音（é/í）
    会保留：西语别名要按原写法命中，与既有俗称索引的匹配规则一致。
    """
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[\u0300-\u036f]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def load_substance_aliases(
        db: sqlite3.Connection) -> tuple[dict[str, list[dict[str, str]]], list[dict]]:
    """把同物异名表读成两份站内数据（只读 CSV，不改库、不改主名）。

    - `also`：成分页「也称」表，substance_id → [{"n": 显示名, "t": 可跳转成分 id}]，
      **成对双向**（glucose 页列 Dextrose，dextrose 页也列 Glucose），每页最多
      `SUBSTANCE_ALIAS_CAP` 条。显示名优先取库里 `substance.inn_en` 原文，没有
      该成分才回退 CSV 原文 —— 不翻译。
    - `hits`：追加进 `data/aliases.json` 的检索条目（字段与 `load_aliases()` 同构），
      只做 alias → canonical **单向**：搜 Dextrose 得到「Dextrose → Glucose」身份卡
      并链到 glucose 成分页；规范名本身已有名字索引，不反向加噪。规范成分没有
      产品页时不生成条目，避免链到 404。
    """
    also: dict[str, list[dict[str, str]]] = {}
    hits: list[dict] = []
    path = SUBSTANCE_ALIASES_CSV
    if not path.exists():
        return also, hits
    subs = {sid: (inn or "")
            for sid, inn in db.execute("SELECT substance_id, inn_en FROM substance")}
    page_sids = {r[0] for r in db.execute(
        """SELECT DISTINCT v.substance_id FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id""")}

    def _add_also(sid: str, name: str, target: str) -> None:
        bucket = also.setdefault(sid, [])
        if not name or len(bucket) >= SUBSTANCE_ALIAS_CAP:
            return
        if any((x["n"] or "").lower() == name.lower() for x in bucket):
            return
        bucket.append({"n": name, "t": target if target in page_sids else ""})

    seen_hits: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            csid = (row.get("canonical_id") or "").strip()
            asid = (row.get("alias_id") or "").strip()
            if not csid or not asid or csid == asid:
                continue
            cname = subs.get(csid) or (row.get("canonical_inn") or "").strip()
            aname = subs.get(asid) or (row.get("alias_inn") or "").strip()
            if not cname or not aname:
                continue
            _add_also(csid, aname, asid)
            _add_also(asid, cname, csid)
            norm = _norm_alias(aname)
            if csid not in page_sids or not norm or norm in seen_hits:
                continue
            seen_hits.add(norm)
            hits.append({
                "a": aname,
                "n": norm,
                "v": csid,
                "i": cname,
                "x": cname,          # 卡片显示「别名 → 规范名」，两边都不翻译
                "k": "synonym",
                "cf": "documented",
                "hint": (row.get("note") or "").strip(),
                "src": (row.get("source") or "").strip(),
                "su": "",
                "m": "", "me": "",
                "ct": "",
                "c": [],
                "np": 0,
            })
    return also, hits


def load_confusable(db: sqlite3.Connection) -> list[dict]:
    """易混淆药对的检索索引：一行 = 一个名字 → 它容易混的那个名字。"""
    out: list[dict] = []
    for r in db.execute(
        """SELECT cp.norm_a, cp.norm_b, cp.name_a, cp.name_b,
                  cp.tml_a, cp.tml_b, cp.a_substance_id, cp.b_substance_id,
                  sa.inn_en AS a_inn, sa.inn_zh AS a_zh,
                  sb.inn_en AS b_inn, sb.inn_zh AS b_zh
           FROM confusable_pair cp
           LEFT JOIN substance sa ON sa.substance_id = cp.a_substance_id
           LEFT JOIN substance sb ON sb.substance_id = cp.b_substance_id"""
    ):
        # 搜 A 时提示 B，搜 B 时提示 A；x 是「对方」的显示名。
        out.append({
            "n": r["norm_a"],
            "x": r["b_zh"] or r["b_inn"] or r["name_b"],
            "sid": r["b_substance_id"],
            "tml": r["tml_b"],
        })
        out.append({
            "n": r["norm_b"],
            "x": r["a_zh"] or r["a_inn"] or r["name_a"],
            "sid": r["a_substance_id"],
            "tml": r["tml_a"],
        })
    return out


# 药品身份页「状态」列的受控词：状态词与说明都走 I18N（data-i18n），
# HTML 里的英文默认文案供无 JS / 首帧使用，i18n.js 再按语言替换。
STATUS_WORDS = ("active", "discontinued", "withdrawn", "unknown")
STATUS_NOTES = {
    "discontinued": "drug.status_note.discontinued",
    "withdrawn": "drug.status_note.withdrawn",
    "unknown": "drug.status_note.unknown",
}
STATUS_NOTES_EN = {
    "discontinued": "expired",
    "withdrawn": "market authorisation withdrawn",
    "unknown": "validity unknown",
}


# ── v0.6.3 U3：标签本地化 helper（服务端；与客户端 T() 共用 i18n key） ──────
def _label_html(prefix: str, code: str, fallback: str | None = None) -> str:
    """受控词 → data-i18n span；长尾/杂项值原样显示（不造数据、不空）。"""
    code = (code or "").strip()
    if not code:
        return ""
    key = f"{prefix}.{code}"
    if key in I18N["en"]:
        return f'<span data-i18n="{key}">{esc(I18N["en"][key])}</span>'
    return esc(fallback if fallback is not None else code)


def _label_join(prefix: str, codes) -> str:
    return "、".join(_label_html(prefix, c) for c in codes if (c or "").strip())


_RE_UNIT = re.compile(r"(?<![\w])(万iu|microgram|unit|meq|mci|iu|ug)(?![\w])")


def _label_unit_html(text: str) -> str:
    """强度串里的非国际通用单位包成 data-i18n span；mg/g/ml/%/mcg 等保持原样。"""
    def repl(m):
        key = f"unit.{m.group(1)}"
        if key in I18N["en"]:
            return f'<span data-i18n="{key}">{esc(I18N["en"][key])}</span>'
        return m.group(1)
    return _RE_UNIT.sub(repl, esc(text))


# v0.6.6：成分页多国矩阵（行=规格/剂型/释放；列=国家；服务端默认 en 顺序，客户端按界面语言重排）
def _market_is_enabled(code: str) -> bool:
    """注册表里该市场是否 enabled（v0.11.4：FR 站点侧已注册但默认关闭）。"""
    try:
        reg = json.loads((ROOT / "data" / "markets.json").read_text(encoding="utf-8"))
        return any(m.get("code") == code and m.get("enabled")
                   for m in reg.get("markets", []))
    except (OSError, ValueError):
        return False


COUNTRY_PRIORITY = (("US", "GB", "CA", "AU", "SG", "CN", "ES", "MX", "TW", "HK", "EU")
                    + (("FR",) if _market_is_enabled("FR") else ()))
MATRIX_ROW_CAP = 120


def _strength_suspect(text: str) -> bool:
    """v0.8.4：明显错误的规格（如 400064g）→ 标「规格待核」并排最后；只标记不删数据。"""
    m = re.match(r"\s*([0-9][0-9,.]*)\s*([A-Za-z%μµ]*)", text or "")
    if not m:
        return False
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return False
    unit = (m.group(2) or "").lower()
    if val >= 1_000_000:
        return True
    if val > 10_000 and unit not in ("u", "iu", "unit", "units", "%", "ml"):
        return True
    return False


# ── v0.9.0 task-17：重量单位展示归一（DB 已由 task-16 归一，原文从审计 CSV 读）──
# 0.12 g 与 120 mg 在矩阵合并成一行「120 mg」，小字保留「原记录：0.12 g」。
_WEIGHT_TO_MG = {
    "g": Decimal("1000"), "kg": Decimal("1000000"),
    "mcg": Decimal("0.001"), "ug": Decimal("0.001"), "μg": Decimal("0.001"),
    "µg": Decimal("0.001"), "microgram": Decimal("0.001"), "micrograms": Decimal("0.001"),
    "ng": Decimal("0.000001"),
}
_STRENGTH_RAW_FILE = ROOT / "data" / "sources" / "unit_normalization_20261030.csv"
_STRENGTH_RAW_GZ = ROOT / "data" / "sources" / "unit_normalization_20261030.csv.gz"
_STRENGTH_RAW_FALLBACK = ROOT / ".tmp" / "unit-norm-mass" / "audit_real.csv"
_STRENGTH_RAW: dict[str, str] | None = None


def _fmt_decimal(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _fmt_qty(value) -> str:
    """数量定点显示（千分位），避免 `:g` 把 1000000 输出成 `1e+06`。

    v0.10.2 修：全库 372 行（强度 67 + 每剂量 311）原来会显示 `1e+06 IU/100 mL`，
    还让排序键 `_spec_num()` 把 1e+06 当成 1。
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f != f or f in (float("inf"), float("-inf")):      # NaN / inf：原样交回
        return str(value)
    out = f"{f:,.6f}".rstrip("0").rstrip(".")
    return out or "0"


def _snap_strength(v: Decimal) -> Decimal:
    """显示层归整（T10 / plan §4.1）：只把「换算残渣」贴回最近的整数，绝不抹平真实小数。

    窄口三条同时满足才归整：`v ≥ 1` ∧ `|偏差| ≤ 0.01` ∧ `|偏差| ≤ 2e-5 × 整数`。
      · 499.9996 → 500、500.0082 → 500（TGA 的 g↔mg 换算噪声，41 个 500.x 全在这里）
      · 0.00025 / 0.008 不动（`v ≥ 1` 硬门槛；否则会被抹成 0）
      · 469.01 / 790.02 / 100.008 不动（相对门槛挡掉，绝对门槛单独会放过 469.01）
    **数据层不动**：原始值仍在 `product_component.strength_value` 与数据包里，
    `_raw_strength()` 会把它显示成「原记录 499.9996 mg」（`_strength_origin_html`）。
    """
    if v is None or v < 1:
        return v
    r = v.to_integral_value(rounding=ROUND_HALF_UP)
    dev = abs(v - r)
    if dev <= Decimal("0.01") and dev <= Decimal("0.00002") * r:
        return r
    return v


def _normalized_strength(value, unit) -> str:
    """重量单位 → mg 显示串；>100,000 mg 的异常值保持原单位（task-16 未换算的不猜）。

    T10：无论走哪条分支都过一次 `_snap_strength` —— 但只在真的归整时才换写法，
    其余格式（`_fmt_qty` 的千分位）保持原样，避免「顺手改了 12 万页的数字写法」。
    """
    if value is None:
        return ""
    unit = (unit or "").strip()
    factor = _WEIGHT_TO_MG.get(unit.lower())
    if factor is not None:
        try:
            num = Decimal(str(value)) * factor
        except InvalidOperation:
            return f"{_fmt_qty(value)} {unit}".strip()
        if num <= Decimal("100000"):
            return f"{_fmt_decimal(_snap_strength(num))} mg"
        return f"{_fmt_qty(value)} {unit}".strip()
    # 非重量换算单位（本来就用 mg / IU / % …）：只做窄口归整，格式原样
    try:
        num = Decimal(str(value))
    except InvalidOperation:
        return f"{_fmt_qty(value)} {unit}".strip()
    snapped = _snap_strength(num)
    if snapped != num:
        return f"{_fmt_qty(snapped)} {unit}".strip()
    return f"{_fmt_qty(value)} {unit}".strip()


def _strength_raw_map() -> dict[str, str]:
    """task-16 审计的 old_value/old_unit → (pid|ord → 原记录)。

    优先读仓库内快照 `data/sources/unit_normalization_20261030.csv`
    （`.csv.gz` 兼容旧快照）；`.tmp/unit-norm-mass/audit_real.csv` 只作兜底。
    都缺时**抛错**，不允许静默丢掉 task-17 的「原记录」。
    """
    global _STRENGTH_RAW
    if _STRENGTH_RAW is not None:
        return _STRENGTH_RAW
    path = next((p for p in (_STRENGTH_RAW_FILE, _STRENGTH_RAW_GZ,
                             _STRENGTH_RAW_FALLBACK) if p.exists()), None)
    if path is None:
        raise RuntimeError(
            "缺少 task-17 原记录快照：expected " + str(_STRENGTH_RAW_FILE)
            + "（fallback " + str(_STRENGTH_RAW_FALLBACK) + "）")
    out: dict[str, str] = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            pid = (row.get("product_id") or "").strip()
            ord_ = (row.get("ord") or "").strip()
            old_v = (row.get("old_value") or "").strip()
            old_u = (row.get("old_unit") or "").strip()
            if pid and ord_ and old_v and old_u:
                try:
                    out[f"{pid}|{ord_}"] = f"{_fmt_qty(float(old_v))} {old_u}"
                except ValueError:
                    out[f"{pid}|{ord_}"] = f"{old_v} {old_u}".strip()
    _STRENGTH_RAW = out
    return out


def _raw_strength(pid, ord_, sv, su) -> str:
    raw = _strength_raw_map().get(f"{pid}|{ord_}")
    if raw:
        return raw
    return f"{_fmt_qty(sv)} {su}".strip() if sv is not None else ""


def _strength_origin_html(raws: set[str], display: str) -> str:
    """原记录小字：去重、去掉与归一显示相同的写法，最多 3 个 + N。"""
    others = sorted(r for r in raws if r and r != display)
    if not others:
        return ""
    shown = others[:3]
    more = f' +{len(others) - 3}' if len(others) > 3 else ""
    return (f'<span class="m-orig"><span data-i18n="matrix.original">Recorded as</span>: '
            f'{esc("、".join(shown))}{esc(more)}</span>')


# ── T10（2026-11-14）：全站唯一的规格串 ──────────────────────────────────────
# 用户评审 §1.2 的核心：`960 mg/30 mL` 不能被缩成 `960 mg`，也不能把「每片含量」
# 与「液体浓度」印成一个样子。全站 5 处各自手拼字符串（成分页 / 品牌页成分卡 /
# 品牌页明细表 / 搜索索引 / 明细桶）→ 收敛成这一个函数；第 5 处（明细桶）在 `etl/`，
# 不属本工位写权限，另记 T10b。
def _spec_text(sv, su, pv=None, pu=None) -> str:
    """强度 + 每单位基数 → 规格串（只做显示，不改数据、不做换算）。

    - 无 per_volume：`_normalized_strength()`（重量归一到 mg，含 `_snap_strength` 归整）；
    - 有 per_volume：`{强度}/{每基数} {单位}`，如 `960 mg/30 mL`、`0.4 mg/tablet`。
    """
    s = _normalized_strength(sv, su)
    if s and pv is not None:
        s += f"/{_fmt_qty(pv)} {(pu or '').strip()}".rstrip()
    return s


def _spec_kind(pu: str) -> str:
    """per_volume 单位分类（只用于 `data-spec-kind` 属性与排序，不改文案）。

    volume = 浓度（每 mL/L）；mass = 每份基质；count = 每片/每剂；time = 速率。
    现查 94,799 行有 per_volume：mL 79,554 / mg 13,666 / h 312 / tablet 140 …
    """
    u = (pu or "").strip().lower()
    if u in ("ml", "l", "cl", "dl"):
        return "volume"
    if u in ("mg", "g", "mcg", "ug", "μg", "µg", "kg"):
        return "mass"
    if u in ("h", "hours", "hr", "d", "day", "days"):
        return "time"
    return "count"


# ── 名称-规格冲突（T10 / plan §6）：只做机制，v0.11.6 默认关闭 ────────────────
# Lead 2026-11-14 决定：T15 清单 B（832 行）抽 40 条，约 9 成是基准/口径差
# （盐型 PRASUGREL 10↔12.17、元素量 CALCIUM 500↔2940、提取物 vs 原料、净重 24 G↔74.7 mg），
# 全量打标会成片误报，比不打更糟。所以：机制写好、开关默认关，构建时一条徽标都不渲染。
# 打开前缺的东西：`variant.base_fraction` 全是 1.0、`salt_code` 只有 15% 有值
# → 无法把「名称里的量」和「结构化含量」放到同一基准上比。
SPEC_CONFLICT_CSV = ROOT / "data" / "sources" / "name_spec_conflict_20261114.csv"
SPEC_CONFLICTS: dict[str, str] = {}


def load_spec_conflicts(enabled: bool | None = None) -> dict[str, str]:
    """装载「名称-规格冲突」清单（product_id → 名称里的规格原文）。

    默认 **不启用**；只有 `SPEC_CONFLICT=1` 且清单文件在位才加载。
    返回空 dict 时，页面一条徽标都不渲染（默认状态）。
    """
    global SPEC_CONFLICTS
    SPEC_CONFLICTS = {}
    on = (os.environ.get("SPEC_CONFLICT", "").strip() == "1") if enabled is None else enabled
    if not on or not SPEC_CONFLICT_CSV.exists():
        return SPEC_CONFLICTS
    with SPEC_CONFLICT_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            pid = (row.get("product_id") or "").strip()
            tok = (row.get("name_strength_token") or "").strip()
            if pid and tok:
                SPEC_CONFLICTS.setdefault(pid, tok)
    return SPEC_CONFLICTS


def _fs_pack(fs: dict[str, list[str]], max_groups: int = 3, max_specs: int = 3) -> list[str] | None:
    """剂型 → 规格分桶 → 索引里的紧凑串 `["tablet|500 mg;325 mg", ...]`（T10 / plan §3.4 ④）。

    取舍（实测 core.json 48.7 → 46.3 MB dec）：
      · 只有一个剂型（或没有）→ 返回 None：单剂型行用 `s` + `f` 就够，写进索引只涨体积；
      · 组上限 3、每组规格上限 3 —— 溢出部分在结果行里用「+N 多剂型」提示，不塞爆索引；
      · 扁平字符串比嵌套数组小约 0.6 MB，且字典化后重复值更多（体积 × 2 层红利）。
    """
    items = [(fm, specs) for fm, specs in fs.items() if fm and specs]
    if len(items) < 2:
        return None
    items.sort(key=lambda kv: (_FORM_RANK_OUTER(kv[0]), kv[0]))
    out = [f"{fm}|" + ";".join(specs[:max_specs]) for fm, specs in items[:max_groups]]
    return out or None


def _spec_conflict_badge(spec: tuple, conflicts: dict[tuple, str], T: dict) -> str:
    """规格单元格里的「规格待核实」徽标（默认不触发；开关打开后才可能出现）。

    只加标记、**不改数值、不改分组、不改排序**（plan §6.2-3）；`data-spec-conflict`
    与 title 放名称里的规格原文，便于抽检复核，不判断哪一侧对。
    """
    tok = conflicts.get(spec)
    if not tok:
        return ""
    return (' <span class="tag warn" data-i18n="matrix.spec_conflict" '
            f'data-spec-conflict="{esc(tok)}" title="{esc(tok)}">'
            f'{esc(T.get("matrix.spec_conflict", "strength unverified"))}</span>')


def _combo_line_html(comp_list: list[tuple[str, str]],
                     sub_label: dict[str, tuple[str, str]]) -> str:
    """复方行的「全部活性成分 + 各自含量」（T10 / plan §5.2、用户评审 §1.3）。

    只列事实：每个成分的名字 + **它自己**的含量（如「羟考酮 5 mg + 对乙酰氨基酚 325 mg」），
    不做换算、不求和、不判断能否互换。中文名走 `_sub_zh_name()`（与品牌页/成分页同一映射），
    默认 hidden，中文/繁体界面由 `applyInnZh()` 打开。
    """
    bits = []
    for cs, sx in comp_list:
        en, zh = sub_label.get(cs) or (cs, _sub_zh_name(cs))
        label = esc(en)
        if zh:
            label += (f'<span class="name-zh" data-inn-zh hidden style="display:none"> '
                      f'{esc(zh)}</span>')
        bits.append(f"{label} {esc(sx)}".strip() if sx else label)
    return " + ".join(bits)


_FORM_WORD_ZH = {
    "effervescent": ("泡腾", "泡騰"),
    "tablet": ("片", "片剂"), "capsule": ("胶囊",), "injection": ("注射液", "注射剂"),
    "solution": ("溶液", "口服液", "液"), "syrup": ("糖浆",), "suspension": ("混悬液",),
    "cream": ("乳膏", "霜"), "ointment": ("软膏",), "gel": ("凝胶", "凝胶剂"),
    "granule": ("颗粒",), "powder": ("散", "粉"), "spray": ("喷雾剂", "喷剂"),
    "drops": ("滴剂", "滴眼液", "滴耳液", "滴鼻液"), "inhaler": ("吸入剂",),
    "suppository": ("栓",), "patch": ("贴剂", "贴片"),
}


# v0.10.2：泡腾类（effervescent）是**一个** form_base（片/颗粒/溶液都在里面），
# 显示时若能从来来源原文分出亚型，就拼「泡腾剂·片 / ·颗粒 / ·溶液」——
# 既保住「泡腾片」这层信息，又不会把 84 行泡腾颗粒、28 行泡腾溶液硬说成片。
_EFF_SUBFORM_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tablet", ("tablet", "comprimido", "tableta", "片", "錠")),
    ("granule", ("granule", "granulado", "颗粒", "顆粒", "sachet")),
    ("solution", ("solution", "solución", "solucion", "溶液")),
)


def _form_display(form: str, dosage: str = "") -> str:
    """剂型显示（HTML）：受控词走 data-i18n 标签；effervescent 再按来源原文补亚型后缀。"""
    base = _label_html("form", form, form)
    if (form or "").strip().lower() != "effervescent":
        return base
    d = (dosage or "").strip().lower()
    for code, words in _EFF_SUBFORM_WORDS:
        if any(w and w in d for w in words):
            return base + "·" + _label_html("form", code, code)
    return base


def _label_plain(prefix: str, code: str) -> str:
    """受控词 → 纯文本标签（en 值；用于 <option> 这类不能放 span 的地方）。"""
    code = (code or "").strip()
    if not code:
        return ""
    return I18N["en"].get(f"{prefix}.{code}", code)


def _strip_form_from_label(label: str, form: str) -> str:
    """v0.8.4：通用名已含剂型词时不在显示里重复剂型（如「阿莫西林胶囊」+「胶囊」）。"""
    text = (label or "").strip()
    f = (form or "").lower()
    if not text or not f:
        return text
    en_word = f.split()[0] if f.split() else f
    suffix = en_word
    for key, words in _FORM_WORD_ZH.items():
        if key in f:
            suffix = words[0]
            break
    for cand in (suffix, en_word):
        if cand and len(text) > len(cand) and text.lower().endswith(cand.lower()):
            return text[: -len(cand)].strip()
    return text


def build_drug_pages(db: sqlite3.Connection, entries=None, also=None) -> int:
    T = I18N["en"]
    # task-141c：同物异名表（也传进来的话复用主流程那一份，避免重复读 CSV）
    if also is None:
        also = load_substance_aliases(db)[0]
    entry_by_k = {e["k"]: e for e in (entries or [])}
    # task-136：CN 中文注册名可附的英文原名（同 key 的拉丁写法；无则不造）
    cn_latin: dict[str, str] = {}
    for kid, raw in db.execute(
            """SELECT DISTINCT pn.key_id, nv.raw FROM product_name pn
               JOIN name_variant nv ON nv.key_id = pn.key_id
               JOIN product p ON p.product_id = pn.product_id
               WHERE p.country = 'CN' AND pn.name_type = 'trade'"""):
        txt = (raw or "").strip()
        if txt and any("a" <= ch.lower() <= "z" for ch in txt) \
                and not any("\u4e00" <= ch <= "\u9fff" for ch in txt):
            cn_latin.setdefault(kid, txt)
    products: dict[str, list] = {}
    # T13 / D7：块头要能写「来源 / 数据截止」——先把 source 表读成两张小表（一次查询）
    src_name = {r[0]: (r[1] or r[0]) for r in db.execute(
        "SELECT source_id, name FROM source")}
    src_asof = {r[0]: ((r[1] or "").strip() or (r[2] or "").strip())
                for r in db.execute("SELECT source_id, data_as_of, data_as_of_note FROM source")}
    for row in db.execute(
        """SELECT v.substance_id, COALESCE(p.country, p.region) AS mk, p.form_base, p.dosage_form, p.release,
                  p.status, pc.strength_value, pc.strength_unit,
                  pc.per_volume_value, pc.per_volume_unit, p.product_id, s.inn_zh, pc.ord,
                  p.mah, p.source_id
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN substance s ON s.substance_id = v.substance_id"""
    ):
        products.setdefault(row[0], []).append(row[1:])

    names: dict[str, list[tuple[str, str]]] = {}
    for pid, key_id, raw in db.execute(
        """SELECT pn.product_id, pn.key_id, nv.raw FROM product_name pn
           JOIN name_variant nv ON nv.key_id = pn.key_id
           WHERE pn.name_type = 'trade'"""
    ):
        bucket = names.setdefault(pid, [])
        item = (key_id, raw)
        if item not in bucket:
            bucket.append(item)

    subs = db.execute("SELECT substance_id, inn_en, inn_zh, atc FROM substance").fetchall()
    # T10（plan §2.1/§5.2）：一次预扫「每个产品的完整成分集合 + 各自含量」。
    # 用途：① 分组键的 others_sig（除本页成分以外的成分签名）；② 复方行显示「全部成分 + 各自含量」。
    # 650,358 行，构建期内只扫这一次，不逐行查库。
    comps: dict[str, list[tuple[str, str]]] = {}
    for _pid, _csid, _sv, _su, _pv, _pu in db.execute(
            """SELECT pc.product_id, v.substance_id, pc.strength_value, pc.strength_unit,
                      pc.per_volume_value, pc.per_volume_unit
               FROM product_component pc
               JOIN variant v ON v.variant_id = pc.variant_id
               ORDER BY pc.product_id, v.substance_id"""):
        comps.setdefault(_pid, []).append((_csid, _spec_text(_sv, _su, _pv, _pu)))
    sub_label = {_sid: (_en or _sid, _sub_zh_name(_sid)) for _sid, _en, _zh, _atc in subs}
    # 易混淆药对：成分页顶部给一条警告，链到对方成分页和 /confused.html。
    conflicts: dict[str, list[dict]] = defaultdict(list)
    for r in db.execute(
        """SELECT cp.name_a, cp.name_b, cp.tml_a, cp.tml_b,
                  cp.a_substance_id, cp.b_substance_id,
                  sa.inn_en AS a_inn, sa.inn_zh AS a_zh,
                  sb.inn_en AS b_inn, sb.inn_zh AS b_zh
           FROM confusable_pair cp
           LEFT JOIN substance sa ON sa.substance_id = cp.a_substance_id
           LEFT JOIN substance sb ON sb.substance_id = cp.b_substance_id"""
    ):
        a = {"sid": r["a_substance_id"], "name": r["a_zh"] or r["a_inn"] or r["name_a"],
             "en": r["a_inn"] or r["name_a"], "tml": r["tml_a"]}
        b = {"sid": r["b_substance_id"], "name": r["b_zh"] or r["b_inn"] or r["name_b"],
             "en": r["b_inn"] or r["name_b"], "tml": r["tml_b"]}
        if a["sid"]:
            conflicts[a["sid"]].append(b)
        if b["sid"]:
            conflicts[b["sid"]].append(a)

    # /warn：成分页顶部摘要只取已发布警示，按严重度排序（high→medium→info）。
    warnings_by_sub: dict[str, list[dict]] = defaultdict(list)
    for r in db.execute(
        """SELECT * FROM dose_warning WHERE status = 'published'
           ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    warning_id"""
    ):
        row = dict(r)
        seen_sids = set()
        for key in ("substance_id", "related_substance_id"):
            sid2 = row.get(key)
            if sid2 and sid2 not in seen_sids:
                seen_sids.add(sid2)
                warnings_by_sub[sid2].append(row)
    nicknames: dict[str, list[str]] = {}
    for sid, alias in db.execute(
        """SELECT substance_id, alias FROM alias_all
           WHERE substance_id IS NOT NULL ORDER BY alias_id"""
    ):
        nicknames.setdefault(sid, []).append(alias)
    made = 0
    DRUG_PAGE_IDS.clear()
    (OUT / "drug").mkdir(parents=True, exist_ok=True)
    for sid, inn_en, inn_zh, atc in subs:
        rows = products.get(sid)
        if not rows:
            continue

        # v0.6.6：按「规格 + 剂型 + 释放机制」聚合，国家并排；默认只显示 active。
        NO_TRADE = "__no_trade__"
        # task-10：厂家占位键（厂家名只用于这一格显示，不进任何索引/名称表）
        MAH_PREFIX = "__mah__:"
        mah_count: dict[tuple[str, str], int] = {}
        # v0.11.4 task-62：未公开规格段的计数（记录数 / 名字次数 / 厂家次数），
        # 供折叠摘要「N 个记录 · K 个厂家」与 chip 的 ×N 使用（不再用「、」拼段落）。
        und_meta: dict[str, dict] = {}
        spec_countries: dict[tuple, dict[str, dict[str, str]]] = {}
        spec_raws: dict[tuple, set[str]] = {}
        # T13 / D7：每国「来源库 + 是否含状态未知记录」，用于块头一句实话
        mk_sources: dict[str, set[str]] = {}
        mk_unknown: set[str] = set()
        # T10：每个分组键对应的「完整成分 + 各自含量」与 per_volume 类别（渲染用，一次算完）
        spec_comps: dict[tuple, list[tuple[str, str]]] = {}
        spec_kind: dict[tuple, str] = {}
        # T10/§6：名称-规格冲突（默认空字典 → 一条徽标都不渲染）
        spec_conflict: dict[tuple, str] = {}
        # task-16：清单视图要「每国记录数」与「每格状态」，一次遍历顺手收集
        rec_by_country: dict[str, int] = {}
        _pids_seen: dict[str, set[str]] = {}
        status_cell: dict[tuple, set[str]] = {}
        for (country, fb, df, rel, status, sv, su, pv, pu, pid, zh_sub, ord_, mah,
             src_id) in rows:
            # v0.9.0 task-9 / v0.9.1 task-28：HK 无 status、AU 导出无状态列，
            # 这些 unknown 记录不整批跳过；其他市场仍按原规则隐藏。
            if status != "active" and not (
                    status in ("unknown", "", None)
                    and country in ("HK", "AU", "EU")):
                continue
            # v0.9.0 task-17：显示按归一后 mg 聚合；原记录从 task-16 审计 CSV 取。
            # T10（plan §3.4 ①）：规格串改走 _spec_text（与 per_volume 的关系一起保留）。
            st = _spec_text(sv, su, pv, pu)
            raw_st = _raw_strength(pid, ord_, sv, su)
            if pv:
                raw_st += f"/{_fmt_qty(pv)} {pu}"
            # T10（plan §2.1）：分组键补上「除本页成分以外的成分签名」，
            # 单方产品 others_sig 为空 → 与旧 key 等价（纯单方页零回归）。
            _others = tuple(sorted((cs, sx) for cs, sx in (comps.get(pid) or [(sid, st)])
                                   if cs != sid))
            others_sig = "|".join(f"{cs}@{sx}" for cs, sx in _others)
            spec = (st.strip(), fb or df or "", rel, others_sig)
            spec_comps.setdefault(spec, list(comps.get(pid) or [(sid, st)]))
            spec_kind.setdefault(spec, _spec_kind(pu))
            # T10/§6：名称-规格冲突只在开关打开时才有内容（默认 SPEC_CONFLICTS 为空）
            if SPEC_CONFLICTS.get(pid):
                spec_conflict.setdefault(spec, SPEC_CONFLICTS[pid])
            if raw_st.strip():
                spec_raws.setdefault(spec, set()).add(raw_st.strip())
            bucket = spec_countries.setdefault(spec, {}).setdefault(country, {})
            # T13 / D7：按国家收「来源库 / 是否含状态未知记录」，块头用
            if src_id:
                mk_sources.setdefault(country, set()).add(src_id)
            if status in ("unknown", "", None):
                mk_unknown.add(country)
            # task-16：记录数按产品去重（同一产品多成分行只算一次）+ 每格状态集合
            seen = _pids_seen.setdefault(country, set())
            if pid not in seen:
                seen.add(pid)
                rec_by_country[country] = rec_by_country.get(country, 0) + 1
            status_cell.setdefault((spec, country), set()).add(status)
            traded = names.get(pid, [])
            und = None
            if not st.strip():
                und = und_meta.setdefault(country, {"records": 0, "names": {}, "mah": {},
                                                    "pids": set()})
                if pid not in und["pids"]:
                    und["pids"].add(pid)
                    und["records"] += 1
            if not traded:
                # v0.9.0 task-19：无 trade 名的产品也在矩阵里占位，不静默消失。
                # v0.10.2 task-10：CN 这 126,716 条 100% 有上市许可持有人，
                # 名称位改显示「厂家：<MAH>」（只显示，不入 name_key/检索，不生成厂家页）；
                # 同一厂家在同一格只出现一次并计 ×N（下面的 mah_count）。
                # 2026-11-13 task-28（用户截图）：**不限国家** —— 任何国家无 trade 名且有 MAH
                # 都按厂家分桶显示「厂家：X」；没有 MAH 的才落 NO_TRADE（「无商品名」）。
                if (mah or "").strip():
                    key = MAH_PREFIX + (mah or "").strip()
                    if key not in bucket:
                        bucket[key] = ("", "", "")
                    mah_count[(country, key)] = mah_count.get((country, key), 0) + 1
                    if und is not None:
                        und["mah"][key] = und["mah"].get(key, 0) + 1
                else:
                    bucket.setdefault(NO_TRADE, ("", "", ""))
                    if und is not None:
                        und["names"][NO_TRADE] = und["names"].get(NO_TRADE, 0) + 1
            for key_id, raw in traded:
                e = entry_by_k.get(key_id)
                label = (e or {}).get("d") or raw
                if label and label not in bucket:
                    en = cn_latin.get(key_id, "") if country == "CN" else ""
                    bucket[label] = (f'../name/{e["u"]}' if e and e.get("u") else "", en,
                                     (zh_sub or "") if country == "CN" else "")
                if und is not None and label:
                    und["names"][label] = und["names"].get(label, 0) + 1
        def _brand_bit(label, url, en, zh_sub, form, country=""):
            if label == NO_TRADE:
                return (f'<span class="m-brand st-badge st-unknown brand-none" data-brand="0" '
                        f'data-i18n="brand.none">{esc(T["brand.none"])}</span>')
            if label.startswith(MAH_PREFIX):
                # task-10：CN 无商品名 → 名称位显示「厂家：<MAH>」；前缀弱化、
                # 过长截断（title 放全称）、同厂家多条标 ×N。它不是品牌名。
                # 2026-11-13 task-25（用户截图）：删除原来的 data-i18n-title="brand.mah_note"。
                # i18n.js 的 apply() 对 [data-i18n-title] 是 `el.textContent = T(key)`（为 <title>
                # 设计的写法），挂在 <span> 上会把「厂家：X」整段替换成
                # 「该产品没有登记商品名，这里显示上市许可持有人。」——又长又占地方。
                # 现在名称位只留「厂家：<MAH>」，长句不再出现；I18N 里的 brand.mah_note 键保留
                # （不删键，避免四语键集/zh-Hant 生成器连锁改动），代码里不再引用。
                mah_name = label[len(MAH_PREFIX):]
                shown = mah_name if len(mah_name) <= 28 else mah_name[:27] + "…"
                n_same = mah_count.get((country, label), 1)
                times = f' <span class="m-n">×{n_same}</span>' if n_same > 1 else ""
                return (f'<span class="m-brand m-mah" data-brand="0" title="{esc(mah_name)}">'
                        f'<span class="mah-k" data-i18n="brand.mah">'
                        f'{esc(T.get("brand.mah", "Manufacturer:"))}</span> '
                        f'{esc(shown)}{times}</span>')
            display = _strip_form_from_label(label, form)
            if url:
                bit = (f'<a class="m-brand" data-brand="1" title="{esc(label)}" '
                       f'href="{esc(url)}">{esc(display)}</a>')
            else:
                bit = (f'<span class="m-brand" data-brand="1" '
                       f'title="{esc(label)}">{esc(display)}</span>')
            if en and en != label:
                bit += f'<span class="m-en">{esc(en)}</span>'
            if zh_sub and zh_sub != display:
                bit += f'<span class="m-zh">{esc(zh_sub)}</span>'
            return bit
        countries = [c for c in COUNTRY_PRIORITY
                     if any(c in by_c for by_c in spec_countries.values())]
        for by_c in spec_countries.values():
            for c in by_c:
                if c not in countries:
                    countries.append(c)
        # v0.9.1 task-29/22：服务端先渲染默认 3 列，CSS 先隐藏其余列，
        # 避免 JS 应用默认列时把整张矩阵高度改掉（CLS）。JS 仍可按语言/勾选重排。
        country_totals = {
            c: sum(len((by_c.get(c) or {})) for by_c in spec_countries.values())
            for c in countries
        }
        order = sorted(countries, key=lambda c: (-country_totals.get(c, 0), c))
        # v0.11.0：EU 区域层没有规格/剂型 → 默认 3 列不选它（可在筛选器里手动加列）
        order_pick = [c for c in order if c != "EU"] or order
        default_cols: list[str] = []
        for c in ([order_pick[0]] if order_pick else []) + ["US"] + order_pick[1:]:
            if c in countries and c not in default_cols:
                default_cols.append(c)
            if len(default_cols) >= 3:
                break
        default_cols_set = set(default_cols)

        def _defcol_attr(c: str) -> str:
            return ' data-defcol="1"' if c in default_cols_set else ""
        # v0.8.0：不再静默截断到 8 列——全部市场列都显示（US/GB/CA/AU/SG/CN/ES/MX/TW），
        # 移动端由 .matwrap 横向滚动；界面语言只决定列顺序（i18n.js MORDER）。
        # v0.8.3 task-119：常用度排序（跨国家产品/品牌记录数），「未公开」最后，空行隐藏。
        # T10：`_spec_num` 提到模块级（品牌页排序也用它，两处同一口径，见文件末尾定义）。
        def _form_rank(form: str) -> int:
            f = (form or "").lower()
            if "effervescent" in f:      # v0.10.2：泡腾类排在最前（原会落到 return 9 排最后）
                return 0
            if "tablet" in f:
                return 0
            if "capsule" in f:
                return 1
            if any(w in f for w in ("solution", "liquid", "syrup", "suspension",
                                    "elixir", "drops")):
                return 2
            if any(w in f for w in ("injection", "infusion", "injectable", "vial", "ampoule")):
                return 3
            if any(w in f for w in ("cream", "ointment", "gel", "lotion", "patch",
                                    "suppositor")):
                return 4
            if any(w in f for w in ("spray", "inhaler", "aerosol", "nebuli")):
                return 5
            if any(w in f for w in ("powder", "granule", "sachet")):
                return 6
            return 9

        freq_by_spec = {
            spec: sum(len(bucket) for bucket in by_c.values())
            for spec, by_c in spec_countries.items()
        }
        suspect_by_spec = {spec: _strength_suspect(spec[0]) for spec in spec_countries}
        spec_rows = [kv for kv in spec_countries.items()
                     if any(bucket for bucket in kv[1].values())]
        spec_rows.sort(key=lambda kv: (
            kv[0][0].strip() == "",                  # 未公开规格排最后
            suspect_by_spec.get(kv[0], False),        # 规格待核排最后
            kv[0][3] != "",                           # T10：单方在前、复方在后
            len(kv[0][3].split("|")) if kv[0][3] else 0,   # 复方内：成分少的在前
            -freq_by_spec.get(kv[0], 0),              # 常用度降序
            _form_rank(kv[0][1]),                     # 剂型标准顺序
            -_spec_num(kv[0][0]),                     # 同频按数值（大→小）
            # T10（plan §2.2）：末位补全序 —— key 现在是 4 元组，并列时不能退回 dict 迭代顺序
            # （受 PYTHONHASHSEED 影响，两次构建会逐字节不同；名字页有同类先例）。
            kv[0][1], kv[0][2], kv[0][3],
        ))
        shown = spec_rows[:MATRIX_ROW_CAP]
        head = (f'<th data-i18n="matrix.spec">{esc(T["matrix.spec"])}</th>'
                + "".join(f'<th data-country="{esc(c)}"{_defcol_attr(c)}'
                          f'{EU_TH_ATTR if c == "EU" else ""}>'
                          f'{esc(c)}</th>'
                          for c in countries))
        tbody = []
        # v0.10.2 task-4：可见列全「未收录」的行 = 纯噪音（用户截图那种整行空白）。
        # 判据只用「首屏可见列」= default_cols；被隐藏的市场里有记录 → 不渲染空行，
        # 但要计数并在矩阵下方给「另有 N 个…」+ 一键把该市场加入列（复用 ?mk= 机制）。
        # 若某行在所有市场（含隐藏）都没有记录（理论上不该发生）→ 同样计入未显示，
        # 便于发现渲染 bug，不静默丢信息。
        hide_empty: dict[int, list[str]] = {}      # 行序号 → 该行有记录的被隐藏市场
        for idx_row, (spec, by_c) in enumerate(shown):
            if any(by_c.get(c) for c in default_cols):
                continue
            hidden_mk = [c for c in countries if c not in default_cols_set and by_c.get(c)]
            hide_empty[idx_row] = hidden_mk
        for idx_row, (spec, by_c) in enumerate(shown):
            st, form, rel, others_sig = spec
            suspect = suspect_by_spec.get(spec, False)
            st_html = _label_unit_html(st) if st else (
                '<span class="meta" data-i18n="drug.nostrength">not disclosed</span>')
            st_html += _strength_origin_html(spec_raws.get(spec, set()), st)
            if suspect:
                st_html += (' <span class="tag warn" data-i18n="matrix.spec_check">'
                            'check strength</span>')
            st_html += _spec_conflict_badge(spec, spec_conflict, T)
            if others_sig:
                # T10（plan §5.2）：矩阵视图也要能看出这是复方，并列出其它成分与各自含量
                st_html += (' <span class="tag" data-i18n="badge.combo">'
                            + esc(T.get("badge.combo", "Association")) + '</span>'
                            + f'<br><span class="m-combo">'
                            + _combo_line_html(spec_comps.get(spec, []), sub_label)
                            + '</span>')
            form_html = (_label_html("form", form, form) if form
                         else '<span class="meta">—</span>')
            rel_html = (f' · {_label_html("release", rel, rel)}'
                        if rel not in ("", "none") else "")
            cells = [f'<td class="m-spec"><b>{st_html}</b><br>{form_html}{rel_html}</td>']
            for c in countries:
                cell_brands = by_c.get(c) or {}
                if not cell_brands:
                    # v0.8.2 task-136：无数据也输出固定 td（带 data-country），禁止整行错位
                    cells.append(f'<td data-country="{esc(c)}" data-label="{esc(c)}"'
                                 f'{_defcol_attr(c)}>'
                                 f'<span class="meta" data-i18n="matrix.none">not recorded</span></td>')
                    continue
                ordered = sorted(cell_brands.items(), key=lambda kv: kv[0].lower())
                bits = [_brand_bit(label, url, en, zh_sub, form, c)
                        for label, (url, en, zh_sub) in ordered[:3]]
                rest_html = ""
                if len(ordered) > 3:
                    # v0.9.0 task-6：+N 用原生 <details> 展开，无 JS 也可点开阅读
                    rest_bits = [_brand_bit(label, url, en, zh_sub, form, c)
                                 for label, (url, en, zh_sub) in ordered[3:]]
                    rest_html = (f'<details class="m-more"><summary>'
                                 f'+{len(ordered) - 3}</summary>'
                                 f'<span class="m-rest">{" ".join(rest_bits)}</span></details>')
                cells.append(f'<td data-country="{esc(c)}" data-label="{esc(c)}"'
                             f'{_defcol_attr(c)}>'
                             f'{" ".join(bits)}{rest_html}</td>')
            hid = hide_empty.get(idx_row)
            hid_attr = (f' data-hide-empty="1" data-hidden-mk="{esc(",".join(hid))}"'
                        if hid is not None else "")
            tbody.append(f'<tr data-form="{esc(form or "")}" data-release="{esc(rel or "")}" '
                         f'data-spec="{esc(st + " " + " ".join(sorted(spec_raws.get(spec, set()))))}" '
                         f'data-others="{esc(others_sig)}" data-spec-kind="{esc(spec_kind.get(spec, ""))}" '
                         f'data-combo="{1 if others_sig else 0}" '
                         f'data-suspect="{1 if suspect else 0}"{hid_attr} '
                         f'data-freq="{freq_by_spec.get(spec, 0)}">'
                         + "".join(cells) + "</tr>")
        capped_blocks = ""
        if len(spec_rows) > MATRIX_ROW_CAP:
            for lang in ("en", "es", "zh", "zh-Hant"):
                note = (I18N[lang].get("matrix.capped") or "")
                note = (note.replace("{shown}", str(len(shown)))
                            .replace("{total}", str(len(spec_rows))))
                capped_blocks += (f'<div class="lang-block" data-lang-block="{lang}">'
                                  f'<p class="sub">{esc(note)}</p></div>')
        if tbody:
            # v0.10.2 task-4：可见列全空的行的「不静默丢信息」说明 + 一键加列
            hidden_rows_html = ""
            undisclosed_note = ""
            if any((kv[0][0] or "").strip() == "" for kv in shown):
                undisclosed_note = ('<p class="sub" data-i18n="matrix.undisclosed_note">'
                                    '“not disclosed” means the source does not publish the '
                                    'strength — it does not mean the product has none.</p>')
            if hide_empty:
                mk_union: list[str] = []
                for hidden in hide_empty.values():
                    for c in hidden:
                        if c not in mk_union:
                            mk_union.append(c)
                mk_union.sort(key=lambda c: (COUNTRY_PRIORITY.index(c)
                                             if c in COUNTRY_PRIORITY
                                             else len(COUNTRY_PRIORITY), c))
                btns = "".join(
                    f'<button type="button" class="mf-reset" data-mk-add="{esc(c)}" '
                    f'data-i18n-aria="matrix.hidden_show">{esc(c)}</button>'
                    for c in mk_union)
                hidden_rows_html = (
                    f'<div class="matrix-hidden-rows" data-hidden-count="{len(hide_empty)}">'
                    f'<p class="sub">{_lang_block_text("matrix.hidden_rows", n=len(hide_empty), mk=" · ".join(mk_union) or "—")}</p>'
                    + (f'<p class="mf-country-actions">{btns}</p>' if mk_union else "")
                    + '</div>')
            hk_note = ""
            if "HK" in countries:
                hk_note = ('<p class="sub matrix-hk-note" data-i18n="matrix.hk_note">'
                           'Hong Kong records are name/ingredient-level only: no strength, '
                           'dosage form or registration status; on the register does not prove '
                           'current supply.</p>')
            au_note = ""
            if "AU" in countries:
                au_note = ('<p class="sub matrix-hk-note" data-i18n="matrix.au_note">'
                           'Australia ARTG data has no registration-status column, so status is '
                           'shown as unknown; being on the register does not mean currently '
                           'marketed.</p>')
            # v0.11.0 P1：矩阵里 EU 那一列不是国家列，是欧盟集中审批层（无规格/剂型/包装）。
            eu_note = _eu_region_note("sub matrix-region-note") if "EU" in countries else ""
            matrix_html = ('<div class="mf-slot" id="filters"></div>'
                           '<div class="matwrap"><table class="matrix"><thead><tr>'
                           + head + "</tr></thead><tbody>" + "".join(tbody)
                           + "</tbody></table></div>"
                           + '<p class="sub matrix-scroll-hint" data-i18n="matrix.scroll_hint">'
                             'Scroll horizontally for more markets →</p>'
                           + '<p class="sub matrix-brand-note" data-i18n="matrix.brand_note">'
                             'Each country column shows the locally registered trade names — '
                             'not translations.</p>'
                           + hidden_rows_html + undisclosed_note
                           + hk_note + au_note + eu_note + capped_blocks)
        else:
            matrix_html = ('<p class="empty" data-i18n="drug.empty">'
                           'No products recorded yet.</p>')
        # ── v0.10.3 task-16：主视图换成「按国家分组清单」，矩阵降级为 ?view=table ──
        # 清单永远渲染（默认可见）；矩阵只在「多市场密度高」的页面内嵌（实测 789 页），
        # 其余页面不内嵌 —— 否则 12k 页每页多背一整张矩阵，与「单页 ≤ 现页 60%」冲突。
        # T13 / D7：把「来源库 / 数据截止 / 缺字段 / 状态含义」按国家整理成块头一句实话。
        block_meta: dict[str, dict] = {}
        for _c in countries:
            _srcs = [src_name.get(s, s) for s in sorted(mk_sources.get(_c, ()))]
            # 一个市场常挂多个来源（如 AU 的 ARTG/PBS/TGA CMI）→ 最多列 2 个，其余「等 N 个」
            _src_txt = "、".join(s.split(" — ")[0].split(" – ")[0][:34] for s in _srcs[:2])
            if len(_srcs) > 2:
                _src_txt += f" +{len(_srcs) - 2}"
            _asofs = sorted({src_asof.get(s, "") for s in mk_sources.get(_c, ()) if src_asof.get(s)})
            block_meta[_c] = {
                "source": _src_txt,
                "asof": "、".join(a[:10] for a in _asofs[-2:]),   # 多来源取最新两个
                "undisclosed": bool((und_meta or {}).get(_c)),
                "unknown": _c in mk_unknown,
            }
        list_html, multi_ratio, lf_html = _drug_list_html(
            spec_rows, countries, rec_by_country, len(spec_rows),
            _brand_bit, status_cell, T, und_meta,
            spec_comps=spec_comps, sub_label=sub_label, spec_kind=spec_kind,
            spec_conflict=spec_conflict, block_meta=block_meta)
        table_block = ""
        compare_link = ""
        if tbody and multi_ratio >= 0.40:
            compare_link = (
                f'<p class="sub mkcmp"><a href="?view=table#tableview" '
                f'data-i18n="drug.compare_side">Side-by-side table</a></p>')
            table_block = (f'<div class="tableview" id="tableview" hidden>{matrix_html}'
                           f'<p class="sub"><a href="?view=list#list" '
                           f'data-i18n="drug.view_list">Back to the list</a></p></div>')
        hidden_note = ('<p class="sub" data-i18n="matrix.hidden_note">'
                       'Discontinued, withdrawn or unverified-status products are hidden by '
                       'default; Hong Kong and Australia records are shown as exceptions.</p>')
        # v0.10.3 task-16：没有内嵌并排对照表的页面（多市场占比 <40%）说明一句，
        # 免得用户以为「?view=table 没反应」是 bug。
        if not table_block:
            hidden_note += ('<p class="sub" data-i18n="drug.compare_note">A side-by-side table is '
                            'offered only when this ingredient has records in many markets; '
                            'otherwise this list is the whole picture.</p>')
        nick_line = ""
        if sid in nicknames:
            also_names = "、".join(esc(x) for x in nicknames[sid])
            nick_line = (f'<p class="sub"><span data-i18n="drug.also_called">Also called:</span> '
                         f'{also_names} <span class="tag" data-i18n="nick.tag">nickname</span></p>')
        # task-141c：同物异名（INN vs USAN / 拼写变体）——只列别的写法，最多 5 个；
        # 目标成分有产品页就链过去，名字保留原文、不翻译，主名（h1）不动。
        syn_line = ""
        if also.get(sid):
            bits = []
            for item in also[sid][:SUBSTANCE_ALIAS_CAP]:
                label = esc(item["n"])
                if item["t"]:
                    label = f'<a href="{esc(item["t"])}.html">{label}</a>'
                bits.append(label)
            syn_line = (f'<p class="sub drug-also"><span data-i18n="drug.also_known">'
                        f'Also known as:</span> ' + ", ".join(bits)
                        + ' <span class="tag" data-i18n="syn.tag">synonym</span></p>\n')
        conf_line = ""
        if conflicts.get(sid):
            items = []
            for other in conflicts[sid][:6]:
                label = esc(other["name"])
                if other["sid"]:
                    label = f'<a href="{other["sid"]}.html">{label}</a>'
                tml = (f' <code>{esc(other["tml"])}</code>' if other["tml"] else "")
                items.append(f"{label}（{esc(other['en'])}{tml}）")
            conf_line = (
                '<div class="notice warnbox"><b>'
                '<span data-i18n="drug.confused">Easily confused with</span>：</b>'
                + "、".join(items)
                + ' <span data-i18n="drug.confused_note">FDA recommends tall-man '
                  'lettering for this pair; check the ingredient, not the name.</span> '
                  f'<a href="../confused.html" data-i18n="drug.confused_all">All pairs</a></div>')
        warn_line = _drug_warn_html(warnings_by_sub.get(sid, []))
        _nl = SUB_NAME_LANG.get(sid, "")
        _nl_attr = f' data-nl="{esc(_nl)}"' if _nl else ""
        _zh_attr = f' data-zh="{1 if inn_zh else 0}"'
        h1_inner = (f'<span data-sub-ingredient="{esc(sid)}" '
                    f'data-sub-orig="{esc(inn_en or sid)}"{_nl_attr}{_zh_attr}>{esc(inn_en or sid)}</span>'
                    if sid in TERMS_SUB_IDS else
                    f'<span{_nl_attr}{_zh_attr}>{esc(inn_en or sid)}</span>')
        # v0.9.8 task-13（P0-9）：H1 → 一句话身份 → 矩阵 → 异名 → 不可互换警示；
        # 筛选器默认收起改在客户端（APP_JS 包 <details>），长尾页静态 0 增量。
        # v0.10.2 修：rows 是 (country, fb, df, rel, status, sv, su, pv, pu, pid, zh_sub, ord, mah)，
        # 市场是 r[0]、产品 id 是 r[9]。原来取 r[1]=剂型、r[10]=inn_zh，导致第一句就写错数字
        # （acetaminophen 显示「24 个市场 · 1 条记录」，实际 10 个市场 / 12,645 产品）。
        n_markets = len({r[0] for r in rows})
        n_records = len({r[9] for r in rows})
        # v0.11.4 task-63：数字加千分位（`12,645`），与页内块头 `{recs:,} records` 一致。
        identity = (f'<p class="sub drug-identity">ATC {esc(atc) or "—"} · '
                    f'<b>{n_markets:,}</b> <span data-i18n="drug.markets">markets</span> · '
                    f'<b>{n_records:,}</b> <span data-i18n="drug.records">records</span></p>')
        # v0.11.4 task-63：成分名的中文名（inn_zh）只在中文/繁体界面显示，且只在数据里
        # 真有中文名（含 CJK）时才输出 —— 不硬翻；英文/西语界面保持原来的纯英文 H1。
        # 默认 hidden + inline display:none，由 i18n.js 的 applyInnZh() 按语言开关。
        # v0.11.6 task-1（T12 C5）：改走 _sub_zh_name()，与品牌页同一份映射。
        _inn_zh = _sub_zh_name(sid)
        name_zh = (f'<span class="name-zh" data-inn-zh hidden style="display:none">'
                   f'{esc(_inn_zh)}</span>' if _inn_zh else "")
        body = f"""<h1>{h1_inner}</h1>
<p class="sub drug-name-src"><span data-sub-src="{esc(sid)}"></span>{name_zh}</p>
{identity}
<div class="drug-sticky" role="group">
  <span class="ds-name" title="{esc(inn_en or sid)}">{esc(inn_en or sid)}</span>
  <span class="ds-meta">{n_markets:,} <span data-i18n="drug.markets">markets</span> · {n_records:,} <span data-i18n="drug.records">records</span></span>
  <a class="ds-filter" href="#forms" data-i18n="drug.forms_short">Forms</a>{lf_html}
</div>
<div id="list" class="listview">{list_html}</div>{compare_link}{table_block}
{syn_line}{nick_line}
{conf_line}
<div class="notice" data-i18n="drug.notice">The same ingredient can carry completely different
brand names in different countries, and the same name can point to a different ingredient.
Listed by country — not interchangeable.</div>
{warn_line}
{hidden_note}"""
        (OUT / "drug").mkdir(parents=True, exist_ok=True)
        drug_ld = json.dumps({
            "@context": "https://schema.org", "@type": "MedicalWebPage",
            "name": inn_en or sid,
            "url": f"{SITE_URL}drug/{sid}.html",
            "about": {"@type": "Drug", "name": inn_en or sid},
        }, ensure_ascii=False)
        (OUT / "drug" / f"{sid}.html").write_text(
            _assert_no_internal_tokens(
                page(f"{inn_en}", body, "../", canonical_rel=f"drug/{sid}.html",
                     head_js=f'<script type="application/ld+json">{drug_ld}</script>'),
                f"drug/{sid}.html"),
            encoding="utf-8")
        DRUG_PAGE_IDS.add(sid)
        made += 1
    return made


def collect_name_data(db: sqlite3.Connection) -> dict:
    """一次性把名字页需要的全部数据取到内存，避免上万次逐条查询。"""
    data: dict[str, dict] = {}
    for (key_id, pid, inn_en, sid, country, form_base, dosage_form, rel,
         sv, su, pv, pu, nl) in db.execute(
        """SELECT pn.key_id, p.product_id, s.inn_en, s.substance_id, COALESCE(p.country, p.region) AS mk,
                  p.form_base,
                  p.dosage_form, p.release, pc.strength_value, pc.strength_unit,
                  pc.per_volume_value, pc.per_volume_unit, s.name_lang
           FROM product_name pn
           JOIN product p ON p.product_id = pn.product_id
           LEFT JOIN product_component pc ON pc.product_id = p.product_id
           LEFT JOIN variant v ON v.variant_id = pc.variant_id
           LEFT JOIN substance s ON s.substance_id = v.substance_id"""
    ):
        d = data.setdefault(key_id, {"subs": {}, "countries": set(), "name_only": set()})
        d["countries"].add(country)
        if not sid:
            # v0.9.1 task-28：无成分产品（名称层），名字页标注、不造卡片
            d["name_only"].add(pid)
            continue
        s = d["subs"].setdefault(
            sid, {"inn": inn_en, "nl": nl or "", "country": set(), "s": set(),
                  "f": set(), "fs": {}, "rel": set()})
        s["country"].add(country)
        # T10（plan §3.4 ②）：成分卡按「剂型 → 规格」分桶，规格串用 _spec_text
        # （含 per_volume，`960 mg/30 mL` 不再缩成 `960 mg`，也不再跨剂型拼成一条）。
        st = _spec_text(sv, su, pv, pu) if sv is not None else ""
        fm = form_base or dosage_form
        if st:
            s["s"].add(st)
            s["fs"].setdefault(fm or "", set()).add(st)
        s["f"].add(fm)
        s["rel"].add(rel)
    return data


def _name_product_table(rows: list, T: dict) -> str:
    """v0.9.0 task-6：单包装名字页的产品明细（市场/规格/剂型/状态/厂家/来源）。"""
    if not rows:
        return ""
    body = []
    for (country, dosage, form_base, rel, status, mah, src, approval,
         sv, su, pv, pu, zh, en, pnote, pcat) in rows:
        # T10（plan §3.4 ③）：明细行也用 _spec_text —— 浓度型规格保留「/30 mL」关系
        st = _spec_text(sv, su, pv, pu) if sv is not None else "—"
        # v0.10.2 R1：剂型列走四语标签（原来直接打印来源英文原码 tablet/efervescente），
        # 并把来源原文并列出来（「泡腾剂·片 · 来源原文：片剂(泡腾)」→ 不再是「看起来像错的数据」）。
        form_html = _form_display(form_base or "", dosage or "")
        if rel and rel != "none":
            form_html += f' · {_label_html("release", rel, rel)}'
        if dosage and (dosage or "").strip() != (form_base or "").strip():
            form_html += (f' <span class="m-orig" data-i18n="name.form_source">'
                          f'as recorded by source</span> <span class="m-orig-raw">'
                          f'{esc(dosage)}</span>')
        maker = ""
        if mah:
            info = MAKERS.get(norm_maker(mah))
            if info and info["has"]:
                maker = (f'<a class="maker-link" href="../maker/{esc(info["slug"])}.html">'
                         f'{esc(mah)}</a>')
            else:
                maker = f'<span class="maker-plain">{esc(mah)}</span>'
        else:
            maker = "—"
        src_html = (f'<a href="{esc(src)}" target="_blank" rel="noopener">'
                    f'{esc(src.split("//")[-1].split("/")[0])}</a>') if src else "—"
        extras = ""
        if not (zh or en):
            extras += (' <span class="st-badge st-unknown" data-i18n="ingredient.unrecorded">'
                       f'{esc(T["ingredient.unrecorded"])}</span>')
        if (pnote and ("出口" in pnote or "Export" in pnote)) or \
                (pcat and "Export" in pcat):
            extras += (f' <span class="badge export" data-i18n="badge.export_only">'
                       f'{esc(T["badge.export_only"])}</span>')
        body.append(
            f'<tr><td data-label="{esc(T["a1.market"])}" data-i18n-label="a1.market">'
            f'{esc(country)}</td>'
            f'<td data-label="{esc(T["col.dose"])}" data-i18n-label="col.dose">'
            f'{_label_unit_html(st)}{extras}</td>'
            f'<td data-label="{esc(T["name.form"])}" data-i18n-label="name.form">'
            f'{form_html}</td>'
            f'<td data-label="{esc(T["a1.status"])}" data-i18n-label="a1.status">'
            f'<span class="st-badge st-{esc(status)}" data-i18n="drug.status.{esc(status)}">'
            f'{esc(T.get("drug.status." + str(status), status))}</span></td>'
            f'<td data-label="{esc(T["col.mah"])}" data-i18n-label="col.mah">{maker}</td>'
            f'<td data-label="{esc(T["a1.source"])}" data-i18n-label="a1.source">{src_html}</td></tr>')
    return ('<div class="tablewrap"><table class="res"><thead><tr>'
            f'<th data-i18n="a1.market">{esc(T["a1.market"])}</th>'
            f'<th data-i18n="col.dose">{esc(T["col.dose"])}</th>'
            f'<th data-i18n="name.form">{esc(T["name.form"])}</th>'
            f'<th data-i18n="a1.status">{esc(T["a1.status"])}</th>'
            f'<th data-i18n="col.mah">{esc(T["col.mah"])}</th>'
            f'<th data-i18n="a1.source">{esc(T["a1.source"])}</th>'
            f'</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def build_name_pages(db: sqlite3.Connection, entries, data: dict,
                     families: dict | None = None, displays: dict | None = None) -> int:
    families = families or {}
    displays = displays or {e["k"]: e["d"] for e in entries}
    # v0.5.3：只有真实存在 name 页的 key 才允许在「同品牌其他市场」里做成链接。
    page_keys = {e["k"] for e in entries if e.get("u")}
    made = 0
    (OUT / "name").mkdir(parents=True, exist_ok=True)
    variants: dict[str, list[str]] = {}
    for key_id, raw in db.execute("SELECT key_id, raw FROM name_variant ORDER BY v_id"):
        variants.setdefault(key_id, []).append(raw)
    # v0.9.0 task-6：单包装名字页的产品明细一次查完，避免 10 万次逐页查询。
    single_rows: dict[str, list] = {}
    for r in db.execute(
            """SELECT pn.key_id, COALESCE(p.country, p.region) AS mk, p.dosage_form, p.form_base, p.release,
                      p.status, p.mah, p.source_url, p.approval_id,
                      pc.strength_value, pc.strength_unit,
                      pc.per_volume_value, pc.per_volume_unit, s.inn_zh, s.inn_en,
                      p.note, p.category
               FROM product_name pn
               JOIN product p ON p.product_id = pn.product_id
               LEFT JOIN product_component pc ON pc.product_id = p.product_id
               LEFT JOIN variant v ON v.variant_id = pc.variant_id
               LEFT JOIN substance s ON s.substance_id = v.substance_id
               WHERE pn.name_type = 'trade' AND pn.key_id IN (
                   SELECT key_id FROM product_name WHERE name_type = 'trade'
                   GROUP BY key_id HAVING COUNT(DISTINCT product_id) = 1)
               ORDER BY pn.key_id, p.country, p.product_id, pc.ord"""):
        single_rows.setdefault(r[0], []).append(tuple(r[1:]))

    for e in entries:
        if not e["u"]:
            continue
        d = data.get(e["k"])
        if not d:
            # v0.6.6：守住「u 有值 ⇒ name/<u> 页存在」的站内不变量；数据侧缺行时用索引
            # 条目自身信息生成最小页，避免品牌矩阵/索引出现 ../name/ 404。
            d = {"subs": {}, "countries": set(e.get("c") or [])}
        level = e["l"]
        banner = {
            "severe": '<div class="notice"><b data-i18n="badge.severe">Same name, different drug</b>'
                      '<span data-i18n="name.severe"> — this brand name points to different '
                      'active ingredients. Check the composition.</span></div>',
            "warning": '<div class="notice"><b data-i18n="badge.warning">Different release</b>'
                       '<span data-i18n="name.warning"> — not interchangeable.</span></div>',
        }.get(level, "")

        cards = []
        for sid, g in d["subs"].items():
            rel = g["rel"] - {"none"}
            # v0.9.9 task-14：g['s'] 是 set，_sort_strength 只比数值 → 「5 mg / 5 mL」
            # 「0.6 kg / 0.6 mL」这类同数值不同单位会并列，而 sorted 是稳定排序，
            # 并列顺序就退回 set 的迭代顺序（受 PYTHONHASHSEED 影响）→ 两次构建这 109 个
            # 名字页逐字节不同。补一个「原串码点」兜底键，让排序全序化。
            strengths = '、'.join(sorted(g['s'], key=lambda s: (_sort_strength(s), s)))
            # T10（plan §3.4 ② / §7-C）：多剂型时规格按剂型成对列出——
            # 「规格（按剂型）: 片剂 500 mg；液体 960 mg/30 mL」，不再把 500 mg 与 960 mg
            # 拼成一条、由单一剂型代表（用户评审 §1.2 的原始抱怨）。
            _fs = {fm: sorted(specs, key=lambda s: (_sort_strength(s), s))
                   for fm, specs in (g.get("fs") or {}).items() if specs}
            if len(_fs) > 1:
                _parts = []
                for fm, specs in sorted(_fs.items(), key=lambda kv: (_FORM_RANK_OUTER(kv[0]), kv[0])):
                    _sp = _label_unit_html('、'.join(specs))
                    _parts.append((_form_display(fm, "") + " " + _sp).strip() if fm else _sp)
                strength_key, strength_value = "name.form_spec", "；".join(_parts)
            else:
                strength_key, strength_value = "name.strength", (
                    _label_unit_html(strengths) if strengths else "")
            strength_bit = (f" · <span data-i18n='{strength_key}'>"
                            f"{esc(I18N['en'][strength_key])}</span>: {strength_value}"
                            if strength_value else "")
            # v0.11.6 task-1（T12 C1/C5）：成分卡显示成分**自己的**中文名（与成分页同一映射），
            # 并给链接打 data-zh="1" ——「无中文名」徽标只属于名称，不许再贴到有中文名的成分旁。
            _zh = _sub_zh_name(sid)
            zh_html = (f'<span class="name-zh" data-inn-zh hidden style="display:none">'
                       f'{esc(_zh)}</span>' if _zh else "")
            zh_attr = ' data-zh="1"' if _zh else ""
            cards.append(
                f"""<div class="card"><h2><a href="../drug/{sid}.html"{zh_attr}>{esc(g['inn'])}</a>{zh_html}</h2>
<div class="meta"><span data-i18n="name.countries">Countries</span>:
{esc('、'.join(sorted(g['country'])))} ·
<span data-i18n="name.form">Form</span>: {_label_join('form', sorted(g['f']))}{strength_bit}
{f" · <span data-i18n='name.release'>Release</span>: {_label_join('release', sorted(rel))}" if rel else ''}</div></div>"""
            )
        single = e.get("n") == 1 and e.get("t") == 1
        single_table = _name_product_table(single_rows.get(e["k"], []), I18N["en"]) if single else ""
        name_only = d.get("name_only") or set()
        none_ing = ""
        if name_only:
            none_ing = ('<p class="sub"><span class="st-badge st-unknown" '
                        'data-i18n="ingredient.unrecorded">'
                        + esc(I18N["en"]["ingredient.unrecorded"]) + '</span></p>')
        # v0.9.8 task-13（P0-8）：多成分名字页先给「不可互换」警示（四语），
        # 且首屏最多 3 张成分卡，其余收进 <details>「显示更多」。
        gen_notice = "" if banner else (
            '<p class="sub name-notice" data-i18n="name.notice">Same name — check the '
            'ingredient; names are not interchangeable.</p>' if len(cards) > 1 else "")
        if cards:
            cards_html = ''.join(cards[:3])
            rest = ''.join(cards[3:])
            if rest:
                cards_html += ('<details class="name-more"><summary data-i18n="name.show_more">'
                               'Show more</summary>' + rest + '</details>')
        else:
            cards_html = '' if name_only else (
                '<p class="empty" data-i18n="name.empty">No records</p>')
        # v0.10.2 R1：中国来源的剂型只记到大类（片剂/胶囊剂…），不细分泡腾、薄膜衣等子剂型。
        # 页面上说明一次，避免把「来源写片剂」读成「我们断定它不是泡腾片」。
        cn_granularity = ""
        if any("CN" in g["country"] for g in d["subs"].values()):
            cn_granularity = ('<p class="sub" data-i18n="name.form_granularity_cn">'
                              'Source records dose form only at class level (e.g. "tablet"); '
                              'effervescent/coated sub-forms are not distinguished.</p>')
        # v0.11.6 task-1（T12 C4）：写法列表先按「原文==译文（大小写 / 空格 / 全半角）+
        # 同一来源」去重，页面标题本身也在去重集合里 —— 不再出现「Tylenol Extra Strength、
        # TYLENOL EXTRA STRENGTH」这种只是大小写不同的两条。
        alts = _dedupe_variants(e["d"], variants.get(e["k"], []))
        also_bit = ('<span data-i18n="name.also">Also written as</span>: '
                    + esc('、'.join(alts)) + ' · ') if alts else ""
        body = f"""<h1>{esc(e['d'])}</h1>
<p class="sub">{('<span class="st-badge st-unknown brand-none" data-i18n="brand.none">'
                 + esc(I18N["en"]["brand.none"]) + '</span> · ') if e.get("t") != 1 else ''}{also_bit}<span data-i18n="name.found">Found in</span>: {esc('、'.join(sorted(d['countries'])))}</p>
{banner}{gen_notice}{cards_html}{none_ing}{cn_granularity}{_family_block(e, families, displays, variants, page_keys, data)}{single_table}"""
        if single:
            for lang in ("en", "es", "zh", "zh-Hant"):
                note = I18N[lang].get("name.single_note") or I18N["en"]["name.single_note"]
                body += (f'<div class="lang-block" data-lang-block="{lang}">'
                         f'<p class="sub name-single-note">{esc(note)}</p></div>')
            NOINDEX_RELS.add(f'name/{e["u"]}')
        # v0.9.6 task-149：name 页是长尾页（77,058 个，占全站 50.7% 体积），
        # 走 slim 壳：单页省 782 B，全站省 57.5 MiB；正文与 SEO 骨架不变。
        _name_html = _assert_no_internal_tokens(
            page(e["d"], body, "../", noindex=single, slim=True,
                 canonical_rel=f'name/{e["u"]}'),
            f"name/{e['u']}")
        # T12 C3：品牌页不出现「碰撞」这类 collision 视图内部术语（分级只在后台推导）。
        if "碰撞" in _name_html:
            raise SystemExit(f"name/{e['u']} 渲染产物出现内部术语「碰撞」，构建中止"
                             "（T12 C3：collision 视图只在后台推导，页面只说同名不同药 / 不可互换）")
        (OUT / "name" / e["u"]).write_text(_name_html, encoding="utf-8")
        made += 1
    return made


def _dedupe_variants(display: str, variants: list[str], cap: int = 6) -> list[str]:
    """名称写法去重（T12 C4）：原文==译文、同一写法的不同来源都只留一条。

    判重口径：NFKC 归一（全角→半角）+ 空白折叠 + casefold（大小写不敏感）。
    `Tylenol Extra Strength` / `TYLENOL EXTRA STRENGTH` 是同一个写法，算一条；
    页面标题 `display` 也进判重集合，所以「标题已经写着它」的那条不再重复列出来。
    """
    def _norm(v: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", v or "")).strip().casefold()

    seen = {_norm(display)}
    out: list[str] = []
    for raw in variants:
        text = (raw or "").strip()
        key = _norm(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= cap:
            break
    return out


def _key_subs(data: dict, key: str) -> dict:
    """一个商品名 key 下的成分聚合（品牌对照表的关系判定只看这里，不另查库）。"""
    return ((data or {}).get(key) or {}).get("subs") or {}


def _key_releases(subs: dict) -> set[str]:
    """该名字下出现过的释放机制集合（去掉 none）。"""
    return {x for g in subs.values() for x in (g.get("rel") or ()) if x and x != "none"}


def _family_relation(cur_subs: dict, sib_subs: dict) -> str:
    """品牌对照表「关系说明」列：只由成分集合与释放机制推导，不手工标注（§1.2）。

    四种结论各对应一个 i18n key；页面上只说人话（同一成分 / 成分不同 / 部分相同 /
    释放不同），不出现 collision 视图那套「碰撞」分级术语（T12 C3）。
    """
    a, b = set(cur_subs), set(sib_subs)
    if not a or not b:
        return "fam.rel.none"
    if a == b:
        return "fam.rel.release" if _key_releases(cur_subs) != _key_releases(sib_subs) else "fam.rel.same"
    return "fam.rel.partial" if a & b else "fam.rel.diff"


def _family_ing_html(subs: dict) -> str:
    """「完整活性成分」列：英文 INN + 成分自己的中文名（同一份 _sub_zh_name 映射）。"""
    if not subs:
        return "—"
    bits = []
    for sid in sorted(subs, key=lambda s: (subs[s].get("inn") or s).casefold()):
        en = subs[sid].get("inn") or sid
        cell = esc(en)
        cell = (f'<a href="../drug/{sid}.html">{cell}</a>'
                if sid in DRUG_PAGE_IDS else f"<b>{cell}</b>")
        zh = _sub_zh_name(sid)
        if zh:
            cell += (f'<span class="name-zh" data-inn-zh hidden style="display:none"> '
                     f'{esc(zh)}</span>')
        bits.append(cell)
    return "、".join(bits)


def _family_name_html(key: str, display: str, page_keys: set[str] | None) -> str:
    """「注册名」列：有品牌页的做成链接，没有的不可点（站内不出 404）。"""
    label = esc(display or key)
    if page_keys is None or key in page_keys:
        return f'<a href="{key_file(key)}">{label}</a>'
    return f"<b>{label}</b>"


def _family_block(e, families, displays, variants, page_keys=None, data=None) -> str:
    """相关品牌名称与配方差异（T12 C2）。

    背景（2026-11-13 用户评审 §1.6）：原来标题写「同一品牌在其他市场的写法」、
    正文却是「同名不同药」，读起来像「同一品牌在各国的翻译」，实际是不同配方。
    现在改成**配方差异表**：市场 / 注册名 / 完整活性成分 / 关系说明——
      · 关系说明由成分集合与释放机制自动推导（_family_relation），不手工标注；
      · 品牌关系只做身份对应，不写成翻译关系，也不承诺可互换；
      · 不带 `<span class="tag">key</span>`：名字已经写在「注册名」列，重复一次就是噪音
        （T12 C4：泰诺 / 泰诺林 各重复显示一次）。

    page_keys：有 name 页的 key 集合；没有品牌页的成员渲染成不可点文本。
    data：collect_name_data() 的结果（成分集合 / 覆盖市场都从这里取）。
    """
    fam = families.get(e["k"])
    if not fam:
        return ""
    members = [e["k"]] + [k for k in fam["members"] if k != e["k"]]
    if len(members) < 2:
        return ""
    T = I18N["en"]
    cur_subs = _key_subs(data, e["k"])
    rows = []
    for k in members:
        subs = _key_subs(data, k)
        name_cell = _family_name_html(k, displays.get(k) or "、".join(variants.get(k, [])[:2]), page_keys)
        if k == e["k"]:
            name_cell += f' <span class="tag" data-i18n="fam.cmp_this">{esc(T["fam.cmp_this"])}</span>'
        markets = "、".join(sorted(((data or {}).get(k) or {}).get("countries") or [])) or "—"
        rel_key = _family_relation(cur_subs, subs)
        rows.append(
            f'<tr><td data-label="{esc(T["fam.cmp_market"])}" data-i18n-label="fam.cmp_market">'
            f'{esc(markets)}</td>'
            f'<td data-label="{esc(T["fam.cmp_name"])}" data-i18n-label="fam.cmp_name">{name_cell}</td>'
            f'<td data-label="{esc(T["fam.cmp_ing"])}" data-i18n-label="fam.cmp_ing">{_family_ing_html(subs)}</td>'
            f'<td data-label="{esc(T["fam.cmp_rel"])}" data-i18n-label="fam.cmp_rel">'
            f'<span data-i18n="{rel_key}">{esc(T[rel_key])}</span></td></tr>')
    return (f'<h2 data-i18n="fam.cmp_title">{esc(T["fam.cmp_title"])}</h2>'
            f'<p class="sub" data-i18n="fam.cmp_intro">{esc(T["fam.cmp_intro"])}</p>'
            f'<div class="tablewrap"><table class="res famcmp"><thead><tr>'
            f'<th data-i18n="fam.cmp_market">{esc(T["fam.cmp_market"])}</th>'
            f'<th data-i18n="fam.cmp_name">{esc(T["fam.cmp_name"])}</th>'
            f'<th data-i18n="fam.cmp_ing">{esc(T["fam.cmp_ing"])}</th>'
            f'<th data-i18n="fam.cmp_rel">{esc(T["fam.cmp_rel"])}</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


COMBO_ROW_CAP = 200


def _combo_stub_html(names: str, stub_items: str) -> str:
    """被体积策略裁剪的组合页 stub（200 + noindex,follow，保留 v0.9.0 旧链接不 404）。

    v0.10.2 i18n：原来把四种语言塞进同一句（「Combination record · 组合记录」），四语用户
    都看到同一串中英混排。现在每种语言各写一份，用 8 行内联脚本按 ?lang= / localStorage /
    浏览器语言选一份——stub 不加载 assets/i18n.js（为了看一句提示拉 165 KB 不值得），
    所以语言判定在这里自带一份最小实现，与 i18n.js 的顺序一致（?lang= → 存储 → 浏览器）。
    无 JS 时显示英文那一份（默认可见，其余 hidden）。
    """
    langs = ("en", "es", "zh", "zh-Hant")

    def _pick(key: str) -> str:
        out = []
        for lang in langs:
            hidden = "" if lang == "en" else " hidden"
            out.append(f'<span class="lb" data-lb="{lang}" data-i18n="{key}"{hidden}>'
                       f'{esc(UI_I18N[lang][key])}</span>')
        return "".join(out)

    picker = """<script>
(function(){
  var L = '';
  try{ L = new URLSearchParams(location.search).get('lang') || localStorage.getItem('lang') || ''; }catch(e){}
  L = String(L || (navigator.language || 'en')).toLowerCase();
  var pick = 'en';
  if(L.indexOf('zh') === 0){ pick = (L === 'zh' || L.indexOf('zh-cn') === 0 || L.indexOf('zh-hans') === 0) ? 'zh' : 'zh-Hant'; }
  else if(L.indexOf('es') === 0){ pick = 'es'; }
  var all = document.querySelectorAll('[data-lb]');
  for(var i = 0; i < all.length; i++){
    all[i].style.display = (all[i].getAttribute('data-lb') === pick) ? 'inline' : 'none';
  }
})();
</script>"""
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex,follow\">"
            f"<title>{esc(names)}</title>"
            "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:48rem;margin:2rem auto;"
            "padding:0 1rem;color:#1f2328}a{color:#0b6b53}.meta{color:#5f6b64;font-size:.9rem}"
            ".lb[hidden]{display:none}</style>"
            "</head><body><main>"
            f"<p class=\"meta\">{_pick('combo.stub_badge')}</p>"
            f"<h1>{esc(names)}</h1>"
            f"<p>{_pick('combo.stub_note')}</p>"
            f"<ul>{stub_items}</ul>"
            f"<p><a href=\"../index.html\">{_pick('combo.stub_search')}</a></p>"
            f"{picker}</main></body></html>")


_FORM_CHIP_CODES = ("effervescent", "tablet", "capsule", "injection", "liquid", "topical",
                    "powder", "suppository", "inhalation", "pellet", "stick", "gas", "kit")


def _form_chip_key(form: str) -> str:
    """把任意 form_base/原文串折成受控剂型码（chips 与行过滤共用）。

    原始值可能是 `Tablet, film coated` / `comprimido recubierto` 这类长尾串，
    直接当 chips 会一页铺出 20+ 个（实测 708 px 高，首屏条目直接归零）。
    """
    f = (form or "").strip().lower()
    if not f:
        return "other"
    for code in _FORM_CHIP_CODES:
        if code in f:
            return code
    return "other"


LIST_ROWS_PER_BLOCK = 12      # 每国家块默认渲染的规格行数（其余一行文本）
# T10（plan §5.4）：复方行比单方行贵得多（每行要列「全部成分 + 各自含量」，实测 1.26 KB/行），
# 每国 × 复方段先给 6 行，其余进折叠 —— 12 行时 acetaminophen 页 299.6 KB，6 行实测 240 KB 以内。
COMBO_ROWS_PER_BLOCK = 5

# v0.11.0 P1：EU 是「区域层」而不是国家 —— 列头 / 块头都要能读出「欧盟集中审批（EMA）」，
# 不能只留两个字母。文案本体在 i18n 字典（eu.region_title / eu.region_note，四语齐），
# 这里只补一个无障碍标签；可见说明由 _eu_region_note() 负责。
EU_TH_ATTR = ' data-i18n-aria="eu.region_title"'


def _eu_region_note(cls: str = "mkregion") -> str:
    """EU 区域层的口径说明（成分页 EU 市场块 / 矩阵 EU 列下方共用一份）。

    语义要点（照 v0.11.0 数据纪律，不许改写成用药建议）：
    ① 这是**欧盟集中审批**（EMA / EC Union Register），不是某个国家的上市记录；
    ② 授权有效 ≠ 在某国在售；
    ③ EU 层**不含规格 / 剂型 / 包装**，所以 EU 列/行里没有规格可读。

    英文写在 HTML 里作服务端兜底（无 JS 也能读），其余三语由 i18n.js 按 `?lang=` 切换。
    """
    T = I18N["en"]
    return (f'<p class="{cls}"><b data-i18n="eu.region_title">'
            + esc(T.get("eu.region_title", "EU centralised authorisation (EMA)"))
            + '</b> — <span data-i18n="eu.region_note">'
            + esc(T.get("eu.region_note", ""))
            + "</span></p>")


def _drug_list_html(spec_rows: list, countries: list[str], rec_by_country: dict[str, int],
                    n_specs: int, name_bit, status_cell: dict[tuple, set[str]],
                    T: dict, und_meta: dict | None = None,
                    spec_comps: dict | None = None, sub_label: dict | None = None,
                    spec_kind: dict | None = None,
                    spec_conflict: dict | None = None,
                    block_meta: dict | None = None) -> tuple[str, float, str]:
    """成分页主视图：按国家分组的产品清单（v0.10.3 task-16）。

    设计依据 `reports/matrix-form-decision-20261110.md`：≥2 国同规格行只占 9.27%，
    矩阵当默认不划算；而矩阵 73.3% 的格子是「未收录」。清单里没有格子，只有「真有」。

    - 零「未收录」：只渲染该国家真实存在的规格行；
    - 未公开规格（HK/TW/MX 大量）单独成段，不混进规格行、不丢；
    - 名字 ≤2 + `<details>+N`（无 JS 可点开）；
    - 跨市场：行尾「也在 GB·US」锚点到对应国家块；
    - 返回 (html, multi_ratio)：multi_ratio = ≥2 国规格行占比，用于决定是否给「并排对照」。

    `name_bit(label, url, en, zh_sub, form, country)` 由调用方传入（与矩阵同一套名字渲染）。
    """
    order = sorted(countries,
                   key=lambda c: (-rec_by_country.get(c, 0),
                                  COUNTRY_PRIORITY.index(c) if c in COUNTRY_PRIORITY
                                  else len(COUNTRY_PRIORITY), c))
    spec_comps = spec_comps or {}
    sub_label = sub_label or {}
    spec_kind = spec_kind or {}
    spec_conflict = spec_conflict or {}
    block_meta = block_meta or {}
    # spec → 有记录的市场列表（一次算完，避免逐行重扫 spec_rows）
    markets_of: dict[tuple, list[str]] = {}
    forms: dict[str, int] = {}
    for spec, by_c in spec_rows:
        ms = [c for c in order if by_c.get(c)]
        if ms:
            markets_of[spec] = ms
        f = (spec[1] or "").strip()
        forms[f] = forms.get(f, 0) + 1
    multi = sum(1 for ms in markets_of.values() if len(ms) >= 2)
    multi_ratio = multi / len(markets_of) if markets_of else 0.0

    # 剂型 chips（按本成分实际存在的剂型，标准序）；无 JS 时是纯锚点
    # chips 按受控剂型码聚合（原始 form_base/原文串会有 20+ 种，手机上铺 700px 高）
    chip_counts: dict[str, int] = {}
    for spec, by_c in spec_rows:
        k = _form_chip_key(spec[1])
        chip_counts[k] = chip_counts.get(k, 0) + 1
    # v0.11.4 task-63（用户截图，简中界面）：chips 的标签原来写死英文（取 I18N["en"]），
    # 简中/繁中/西语界面全是 `All dosage forms` / `liquid 107` …，而旁边的「剂型」按钮
    # （服务端 data-i18n）却是中文。这里服务端仍输出英文（无 JS 兜底、体积 0 增量），
    # 由 i18n.js 的 initListView() → labelChips() 按 data-form-filter 的剂型码取字典改写
    # 标签文本节点（`.n` 计数不动），切换语言重跑 apply() 即时生效。
    chips = [f'<a class="formchip on" href="#list" data-form-filter="">'
             f'{esc(T.get("drug.forms_all", "All dosage forms"))}</a>']
    for k in sorted(chip_counts, key=lambda x: (-chip_counts[x], _FORM_RANK_OUTER(x), x)):
        label = I18N["en"].get(f"form.{k}", k if k != "other" else T.get("atc4.form_other", "other"))
        chips.append(f'<a class="formchip" href="#list" data-form-filter="{esc(k)}">'
                     f'{esc(label)} <span class="n">{chip_counts[k]}</span></a>')
    # T13 / D1：筛选条作为一个 chip 挂在 `.formchips` 里（lf_html 稍后构造，见下），
    # 收起时零高度、展开时铺满整行 —— 首屏条目不受影响。
    chip_head = ('<nav class="formchips" id="forms" aria-label="'
                 + esc(T.get("drug.forms_label", "Dosage forms")) + '">')

    blocks: list[str] = []
    n_uid = 0          # 每行 +N 的展开 checkbox 要唯一 id（确定性计数器，别用 hash）
    # T10（plan §5）：本页只要有复方行，就按「仅含此成分 / 含此成分的复方」两段渲染；
    # 纯单方页（6,311 个）不加任何段标题，避免凭空多出标题、也保证零回归。
    has_combo = any((s[3] or "") for s, _b in spec_rows)
    # T13 / D1（用户评审 §2）：清单顶部加「市场 / 单方·复方 / 规格」三个筛选。
    # 无 JS 时：市场 chip 是普通锚点（跳到该国家块），entire list 全可见；JS 只做渐进增强。
    lf_parts = [f'<div class="lf-row"><span class="lf-k" data-i18n="lf.market">'
                f'{esc(T.get("lf.market", "Market"))}</span>'
                f'<button type="button" class="lf-chip on" data-mk-filter="" '
                f'data-i18n="lf.all">{esc(T.get("lf.all", "All"))}</button>']
    for _c in order:
        lf_parts.append(f'<a class="lf-chip" href="#mk-{esc(_c)}" data-mk-filter="{esc(_c)}">'
                        f'{esc(_c)} <span class="n">{rec_by_country.get(_c, 0):,}</span></a>')
    lf_parts.append("</div>")
    if has_combo:
        lf_parts.append(
            f'<div class="lf-row"><span class="lf-k" data-i18n="lf.kind">'
            f'{esc(T.get("lf.kind", "Kind"))}</span>'
            f'<button type="button" class="lf-chip on" data-seg-filter="" '
            f'data-i18n="lf.all_kinds">{esc(T.get("lf.all_kinds", "All kinds"))}</button>'
            f'<button type="button" class="lf-chip" data-seg-filter="mono" '
            f'data-i18n="drug.mono_section">{esc(T.get("drug.mono_section", "Only this ingredient"))}</button>'
            f'<button type="button" class="lf-chip" data-seg-filter="combo" '
            f'data-i18n="drug.combo_section">'
            f'{esc(T.get("drug.combo_section", "Combination products"))}</button></div>')
    lf_parts.append(
        f'<div class="lf-row"><label class="lf-k" for="lf-spec" data-i18n="lf.spec">'
        f'{esc(T.get("lf.spec", "Strength"))}</label>'
        f'<input type="search" id="lf-spec" class="lf-input" autocomplete="off" '
        f'placeholder="{esc(T.get("lf.spec_ph", "Filter strengths, e.g. 500 mg"))}"></div>'
        f'<p class="lf-status" id="lf-status" role="status" aria-live="polite"></p>'
        f'<p class="lf-none" id="lf-none" hidden data-i18n="lf.none">'
        f'{esc(T.get("lf.none", "No row matches these filters."))}</p>')
    lf_html = ('<details class="listfilters" id="listfilters">'
               f'<summary class="formchip lf-toggle" data-i18n="lf.title">'
               f'{esc(T.get("lf.title", "Filters"))}</summary>'
               '<div class="lf-panel">' + "".join(lf_parts) + "</div></details>")

    def _seg_rows(rows_c: list, is_combo: bool | None) -> list:
        if is_combo is None:
            return rows_c
        return [(s, b) for s, b in rows_c if bool(s[3] or "") == is_combo]

    def _render_segment(seg_rows: list, c: str, is_combo: bool) -> str:
        """一段（单方或复方）的清单 + 折叠摘要；口径与 v0.10.3 原实现一致。"""
        nonlocal n_uid
        disclosed = [(s, b) for s, b in seg_rows if (s[0] or "").strip()]
        if not disclosed:
            return "", 0
        # v0.10.3：每段只渲染前 N 个规格（余下用一行紧凑文本），否则大成分页会从 300 KB
        # 涨到 900 KB（acetaminophen 实测）。复方段更贵 → 用更小的 COMBO_ROWS_PER_BLOCK。
        _cap = COMBO_ROWS_PER_BLOCK if is_combo else LIST_ROWS_PER_BLOCK
        head_rows = disclosed[:_cap]
        tail_rows = disclosed[_cap:]
        # T10（plan §5.4）：折叠会吃掉浓度型规格（v0.11.5 的 acetaminophen 页
        # `960 mg/30 mL` 出现 0 次）→ 本段有 volume 类规格却没进可见区时，用它替换
        # 可见区最后一个非 volume 行（不增加行数，不动 12 行护栏）。
        if (any(spec_kind.get(s, "") == "volume" for s, _b in disclosed)
                and not any(spec_kind.get(s, "") == "volume" for s, _b in head_rows)):
            cand = next((r for r in tail_rows if spec_kind.get(r[0], "") == "volume"), None)
            swap = next((i for i in range(len(head_rows) - 1, -1, -1)
                         if spec_kind.get(head_rows[i][0], "") != "volume"), None)
            if cand is not None and swap is not None:
                tail_rows.insert(0, head_rows[swap])
                head_rows[swap] = cand
                tail_rows = [r for r in tail_rows if r is not cand]
        lis: list[str] = []
        for spec, bucket in head_rows:
            n_uid += 1
            st, form, rel, others_sig = spec
            also = ""
            others = [o for o in markets_of.get(spec, []) if o != c]
            if others:
                shown_mk = others[:3]
                # T13 / D2（用户评审 §2）：「+6」这种纯计数改成能点开的「另 6 个市场」。
                # 无 JS 也能用（原生 <details>），链接仍锚到对应国家块。
                tail_mk = ""
                if len(others) > 3:
                    _rest_mk = "".join(
                        f'<a href="#mk-{esc(o)}">{esc(o)}</a>' for o in others[3:])
                    # v0.11.7 复审：可见文案必须是四语的「另 N 个市场」——用
                    # `data-i18n-tpl` 把数字从 data-total 注入模板（服务端先写英文兜底）；
                    # 另外在 summary 里放一个 **sr-only 的 `+N` 叶子**：atc4-ui 的 D6 断言按
                    # 「叶子文本 = +N 且 closest('a,button,label,summary') 命中」判可点，
                    # 这样「文案正确」与「计数可点」两个要求同时满足。
                    _n_more = len(others) - 3
                    _more_tpl = T.get("drug.mkx_more", "Other {n} markets")
                    _more_txt = _more_tpl.replace("{n}", str(_n_more))
                    tail_mk = (f' <details class="mkx-more"><summary>'
                               f'<span class="mkx-plus sr-only">+{_n_more}</span>'
                               f'<span class="mkx-lbl" data-i18n-tpl="drug.mkx_more" '
                               f'data-total="{_n_more}">{esc(_more_txt)}</span>'
                               f'</summary><span class="mkx-links">{_rest_mk}</span></details>')
                also = (' <span class="mkx"><span data-i18n="drug.also_in">also in</span> '
                        + "·".join(f'<a href="#mk-{esc(o)}">{esc(o)}</a>' for o in shown_mk)
                        + tail_mk + '</span>')
            names = sorted(bucket.keys(), key=lambda k: (k.startswith("__"), k.lower()))
            bits = [name_bit(k, *bucket[k], form, c) for k in names[:1]]
            more = ""
            if len(names) > 1:
                # 无 JS 展开：checkbox + label（纯 CSS）。用 <details> 会让行高从 71 涨到 95：
                # 它和矩阵遗留的 .m-brand/.m-rest 规则打架，在手机上把名字挤成两行。
                uid = f"mx-{n_uid}"
                rest_names = [k for k in names[1:]]
                # task-42：这里同样会把 __mah__:X / __no_trade__ 直接输出 → 用同一映射。
                rest = "、".join(_bucket_key_html(k, T) for k in rest_names[:8])
                if len(rest_names) > 8:
                    rest += f" +{len(rest_names) - 8}"
                # T13 / D2：`+218` **保持原样可见**（atc4-ui 报它是既有绿能力，改文案会动行高 →
                # 390 首屏条目掉 0.5）；说清楚的那句进 title / aria-label，功能与无障碍都保留。
                _more_lbl = T.get("drug.more_names", "Show the other {n}").replace(
                    "{n}", str(len(names) - 1))
                more = (f'<input type="checkbox" class="m-x" id="{uid}" hidden>'
                        f'<label class="m-more" for="{uid}" title="{esc(_more_lbl)}" '
                        f'aria-label="{esc(_more_lbl)}">+{len(names) - 1}</label>'
                        f'<span class="m-rest">{rest}</span>')
            st_html = _label_unit_html(st)
            st_html += _spec_conflict_badge(spec, spec_conflict, T)
            form_html = _form_display(form, "") if form else ""
            rel_html = (f' · {_label_html("release", rel, rel)}'
                        if rel not in ("", "none") else "")
            # T10（plan §5.2）：复方行给出「全部活性成分 + 各自含量」，只列事实
            combo_html = ""
            if others_sig:
                combo_html = (' <span class="tag" data-i18n="badge.combo">'
                              + esc(T.get("badge.combo", "Association")) + '</span>'
                              + '<span class="mkcombo">'
                              + _combo_line_html(spec_comps.get(spec, []), sub_label)
                              + '</span>')
            st_badge = ""
            if any(x in ("unknown", "", None) for x in status_cell.get((spec, c), set())):
                st_badge = (' <span class="st-badge st-unknown" '
                            'data-i18n="drug.status.unknown">unknown</span>')
            lis.append(f'<li class="mkrow" data-form="{esc(_form_chip_key(form))}" data-spec="{esc(st)}" '
                       f'data-mk="{esc(c)}" data-spec-kind="{esc(spec_kind.get(spec, ""))}"'
                       f' data-combo="{1 if others_sig else 0}">'
                       f'<span class="mkst">{st_html}</span>'
                       f'<span class="mkf">{form_html}{rel_html}{combo_html}</span>'
                       f'<span class="mkname-cell"><span class="mknames">'
                       f'{" ".join(bits)}</span>{more}</span>'
                       f'<span class="mkrowmeta">{also}{st_badge}</span></li>')
        rest_html = ""
        if tail_rows:
            # v0.11.4 task-62（用户：「这一坨」）：其余规格折叠成一行摘要
            # 「其余规格 N 个 · 涉及 M 种剂型」，展开按剂型分组；组内 >12 个再折叠。
            groups: dict[str, list] = {}
            for s0, _b in tail_rows:
                groups.setdefault((s0[1] or "").strip(), []).append(s0)

            def _spec_chip(s0) -> str:
                txt = esc(s0[0] or T.get("drug.nostrength", "not disclosed"))
                rel = s0[2] if len(s0) > 2 else ""
                if rel not in ("", "none", None):
                    txt += ' · ' + _label_html("release", rel, rel)
                return f'<span class="ms-spec">{txt}</span>'

            ghtml: list[str] = []
            for form in sorted(groups, key=lambda f: (_FORM_RANK_OUTER(f), f)):
                specs = groups[form]
                head = (_form_display(form, "") if form
                        else esc(T.get("matrix.none", "—")))
                shown = specs[:10]
                # T10（plan §5.4）：每个剂型至少露出一个浓度型规格（否则又被折叠吃掉）
                if (any(spec_kind.get(s, "") == "volume" for s in specs)
                        and not any(spec_kind.get(s, "") == "volume" for s in shown)):
                    cand = next(s for s in specs if spec_kind.get(s, "") == "volume")
                    shown = shown[:9] + [cand]
                chips = "".join(_spec_chip(s0) for s0 in shown)
                more = ""
                if len(specs) > 10:
                    more = (' <span class="ms-more">'
                            + _lang_block_text("drug.ms_more", n=len(specs) - 10)
                            + '</span>')
                ghtml.append(
                    f'<div class="ms-grp"><span class="ms-h">{head} · {len(specs)}</span>'
                    f'<span class="ms-list">{chips}{more}</span></div>')
            # T10（plan §5.4）：折叠内容默认隐藏（innerText 看不到），所以浓度型规格要**写在摘要里**：
            # 该段所有带 per_volume 的规格都列出来（多为 3–6 个），用户一眼看到「960 mg/30 mL」这类
            # 浓度规格确实存在，展开后每个剂型还各自带一个（见上面的 ms-grp 保底）。
            _vol_specs = [s[0] for s, _b in tail_rows if spec_kind.get(s, "") == "volume"]
            _vol_bit = ('<span class="ms-vol"> · ' + "、".join(esc(v) for v in _vol_specs)
                        + '</span>') if _vol_specs else ""
            rest_html = (
                f'<details class="more-specs"><summary><span class="ln">'
                f'{_lang_block_text("drug.more_specs_n", n=len(tail_rows), m=len(groups))}'
                + _vol_bit
                + '</span></summary><div class="ms-body">' + "".join(ghtml)
                + f'<p class="sub full-list"><a href="datapackage.json">'
                + _lang_block_text("drug.full_list") + '</a></p></div></details>')
        seg_head = ""
        if has_combo:
            key = "drug.combo_section" if is_combo else "drug.mono_section"
            label = T.get(key) or ("Combination products" if is_combo else "Only this ingredient")
            seg_head = (f'<h3 class="mkseg-h" data-i18n="{key}">{esc(label)}</h3>')
        return (f'<div class="mkseg" data-seg="{"combo" if is_combo else "mono"}">'
                f'{seg_head}<ul class="mkspecs">{"".join(lis)}</ul>{rest_html}</div>',
                len(head_rows))

    for c in order:
        rows_c = [(spec, by_c[c]) for spec, by_c in spec_rows if by_c.get(c)]
        if not rows_c:
            continue
        undisclosed = [(s, b) for s, b in rows_c if not (s[0] or "").strip()]
        seg_html = ""
        shown_n = 0          # T13 / D3：本块**已展示**的规格行数（各段 head 之和）
        if has_combo:
            _h, _n = _render_segment(_seg_rows(rows_c, False), c, False)
            seg_html += _h
            shown_n += _n
            _h, _n = _render_segment(_seg_rows(rows_c, True), c, True)
            seg_html += _h
            shown_n += _n
        else:
            _h, _n = _render_segment(_seg_rows(rows_c, None), c, False)
            seg_html += _h
            shown_n += _n
        n_head = len([1 for s, _b in rows_c if (s[0] or "").strip()])
        undis_html = ""
        if undisclosed:
            # v0.11.4 task-62：未公开规格不再用「、」拼段落 —— 折叠摘要
            # 「N 个记录 · K 个厂家」；展开分「有商品名（名字 ×N）」与「仅厂家（厂家：X ×N）」。
            meta = (und_meta or {}).get(c) or {}
            names: dict[str, int] = {}
            mahs: dict[str, int] = {}
            for _spec, bucket in undisclosed:
                for k in bucket.keys():
                    if k.startswith("__mah__:"):
                        mahs[k] = int((meta.get("mah") or {}).get(k) or 1)
                    else:
                        names[k] = int((meta.get("names") or {}).get(k) or 1)
            n_rec = int(meta.get("records") or (sum(names.values()) + sum(mahs.values())))
            k_mah = len(mahs)

            def _und_chips(d: dict[str, int]) -> str:
                out = []
                for k in sorted(d, key=lambda x: (x.startswith("__"), x.lower())):
                    out.append(f'<span class="uname">{_bucket_key_html(k, T)} '
                               f'<span class="x">×{d[k]}</span></span>')
                return "".join(out)

            # task-68（体积瘦身）：展开态只列前 8 个名字，其余用「还有 N 个（K 个厂家）」+
            # 数据包链接；折叠摘要仍给全量计数，完整清单在 datapackage.json 可取。
            body: list[str] = []
            named_keys = sorted(names, key=lambda x: (x.startswith("__"), x.lower()))
            mah_keys = sorted(mahs, key=lambda x: x.lower())
            shown_keys = named_keys[:8] or mah_keys[:8]
            shown_map = ({k: names[k] for k in shown_keys} if named_keys
                         else {k: mahs[k] for k in shown_keys})
            if shown_map:
                head_key = "drug.brand_group" if named_keys else "drug.mah_group"
                body.append(
                    '<div class="und-grp"><span class="und-h">'
                    + _lang_block_text(head_key)
                    + '</span><span class="und-chips">' + _und_chips(shown_map)
                    + '</span></div>')
            if named_keys:
                remaining = (len(named_keys) - len(shown_keys)) + len(mah_keys)
            else:
                remaining = len(mah_keys) - len(shown_keys)
            if remaining > 0:
                body.append('<p class="und-more">'
                            + _lang_block_text("drug.und_more", n=remaining,
                                               k=len(mah_keys))
                            + '</p>')
            body.append('<p class="sub full-list"><a href="datapackage.json">'
                        + _lang_block_text("drug.full_list") + '</a></p>')
            undis_html = (
                f'<details class="undis"><summary><span class="ln">'
                f'{_lang_block_text("drug.undisclosed_n", n=n_rec, k=k_mah)}'
                f'</span></summary><div class="und-body">' + "".join(body) + '</div></details>')
        # v0.11.0 P1：EU 块头给一句口径说明（集中审批 ≠ 某国在售、无规格/剂型/包装），
        # 否则用户只看到「EU」两个字（reports/v0110-verify-20261111 §3.3）。
        region_html = _eu_region_note("mkregion") if c == "EU" else ""
        # T13 / D7（用户评审 §2）：把「来源 / 数据截止 / 缺字段 / 状态含义」带到这一块里，
        # 不必离开本页去 coverage 才能看到限制。事实全部来自库（source / product），不改口径。
        _bm = block_meta.get(c) or {}
        meta_bits = []
        if _bm.get("source"):
            meta_bits.append(f'<span class="mkmeta-src"><span data-i18n="mkmeta.source">'
                             f'{esc(T.get("mkmeta.source", "Source"))}</span> '
                             f'{esc(_bm["source"])}</span>')
        if _bm.get("asof"):
            meta_bits.append(f'<span data-i18n="mkmeta.asof">'
                             f'{esc(T.get("mkmeta.asof", "Data as of"))}</span> '
                             f'{esc(_bm["asof"])}')
        if _bm.get("undisclosed"):
            meta_bits.append(f'<span data-i18n="mkmeta.undisclosed">'
                             f'{esc(T.get("mkmeta.undisclosed", "some records have no stated strength"))}'
                             f'</span>')
        if _bm.get("unknown"):
            meta_bits.append(f'<span data-i18n="mkmeta.unknown">'
                             f'{esc(T.get("mkmeta.unknown", "includes records with unknown status"))}'
                             f'</span>')
        # T13 / D7：来源 / 数据截止 / 缺字段 / 状态含义写在块头同一行（`nowrap + 省略号`，
        # 不换行、不撑高首屏；全文进 title）。手机（≤767px）隐藏，保住 390 的首屏条目。
        _meta_text = " · ".join(re.sub(r"<[^>]+>", "", b) for b in meta_bits)
        meta_html = (f'<span class="mkmeta" title="{esc(_meta_text)}">'
                     + " · ".join(meta_bits) + '</span>' if meta_bits else "")
        blocks.append(
            f'<section class="mkblock" id="mk-{esc(c)}" data-mk="{esc(c)}">'
            # T13 / D3（用户评审 §2）：「展示 X 个，共 Y 个」——X 是当前**展示**的行数
            # （受 LIST_ROWS_PER_BLOCK / COMBO_ROWS_PER_BLOCK 与 JS 筛选影响），Y 是该国**已公开**
            # 规格总数（未公开规格另有独立折叠段，不混进这个数；改前只有一个数字 `130 个规格`）。
            # 文案只写英文（无 JS 兜底），其余语言由 i18n.js 按 data-i18n-tpl 用同一模板替换数字
            # ——四语块（4 × 40 字符）会让 12,438 个成分页多背 ≈28 MiB，这一处改用轻量模板。
            # D7 的来源/截止/缺字段说明放在同一行（不额外占高度）。
            f'<h2>{esc(c)} <span class="sub">{rec_by_country.get(c, 0):,} '
            f'<span data-i18n="drug.records">records</span> · '
            f'<span class="mkspec" data-total="{n_head}" data-shown="{shown_n}" '
            f'data-i18n-tpl="drug.spec_count">'
            f'{esc(T.get("drug.spec_count", "{shown} shown of {n}").replace("{shown}", str(shown_n)).replace("{n}", str(n_head)))}'
            f'</span></span> {meta_html}</h2>'
            f'{region_html}'
            f'{seg_html}{undis_html}</section>')
    return (chip_head + "".join(chips) + "</nav>"
            + '<div class="mkblocks">' + "".join(blocks) + "</div>",
            multi_ratio, lf_html)


def _FORM_RANK_OUTER(form: str) -> int:
    """剂型标准序（与 `build_drug_pages` 内 `_form_rank` 同口径的模块级副本）。"""
    f = (form or "").lower()
    if "effervescent" in f or "tablet" in f:
        return 0
    if "capsule" in f:
        return 1
    if any(w in f for w in ("solution", "liquid", "syrup", "suspension",
                            "elixir", "drops")):
        return 2
    if any(w in f for w in ("injection", "infusion", "injectable", "vial", "ampoule")):
        return 3
    if any(w in f for w in ("cream", "ointment", "gel", "lotion", "patch", "suppositor")):
        return 4
    if any(w in f for w in ("spray", "inhaler", "aerosol", "nebuli")):
        return 5
    if any(w in f for w in ("powder", "granule", "sachet")):
        return 6
    return 9


def build_combo_pages(entries, db: sqlite3.Connection) -> int:
    """v0.5.3：按「活性成分集合」生成组合页 /combo/<slug>.html。

    背景：结果页「成分」列对复方（x 含 ' + '）必须点进组合页，而不是第一个成分的
    drug 页。组合页 slug 与索引里的 `cu` 字段共用 combo_slug()，保证一一对应。
    页面最小字段：成分集合（每个成分链成分页）、同组合的商品名/国家/规格/MAH、
    来源与许可；不写用药建议。
    """
    subs: dict[str, tuple[str, str]] = {}
    for sid, inn_zh, inn_en in db.execute(
            "SELECT substance_id, inn_zh, inn_en FROM substance"):
        subs[sid] = (inn_zh or inn_en or sid, inn_en or sid)
    groups: dict[tuple, list] = {}
    for e in entries:
        vs = e.get("vs")
        if not vs or len(vs) < 2:
            continue
        groups.setdefault(tuple(sorted(vs)), []).append(e)
    # v0.6.0：页面 sids 集合 → CSV 归一名数签名。
    # 组合页的 vs 是「同一 name_key 下所有产品的成分并集」，不一定等于单个产品的成分集合；
    # 先用「产品原始 sids 集合 == 页面集合」精确反查，再用页面归一并集兜底；
    # 仍对不上的分组名（合并了多个不同产品的名称）显示中性提示，不臆断 exact/none。
    combo_matches = load_combo_matches()
    sub_key = {sid: norm_ingredient(en) for sid, (_zh, en) in subs.items()}
    key_sid: dict[str, str] = {}
    key_display: dict[str, str] = {}
    for sid, key in sub_key.items():
        key_sid.setdefault(key, sid)
        key_display.setdefault(key, subs.get(sid, (sid, sid))[1])
    tuple_sig: dict[tuple, str] = {}
    if combo_matches:
        prod_sids: dict[str, list] = defaultdict(list)
        for pid, sid in db.execute(
                "SELECT pc.product_id, v.substance_id FROM product_component pc "
                "JOIN variant v ON v.variant_id = pc.variant_id"):
            prod_sids[pid].append(sid)
        seen_tuples: set[tuple] = set()
        for _pid, psids in prod_sids.items():
            if len(psids) < 2:
                continue
            t = tuple(sorted(psids))
            if t in seen_tuples:
                continue
            seen_tuples.add(t)
            sig = "|".join(sorted({sub_key.get(s, norm_ingredient(s)) for s in t}))
            if sig in combo_matches:
                tuple_sig[t] = sig
    page_sig: dict[str, str] = {}
    sig_pages: dict[str, list[str]] = defaultdict(list)
    for sids in groups:
        slug = combo_slug(sids)
        sig = tuple_sig.get(tuple(sids))
        if not sig:
            ukeys = sorted({sub_key.get(s, norm_ingredient(s)) for s in sids})
            cand = "|".join(ukeys)
            if len(ukeys) >= 2 and cand in combo_matches:
                sig = cand
        if sig:
            page_sig[slug] = sig
            sig_pages[sig].append(slug)
    entry_by_k = {e["k"]: e for e in entries}
    sample_pids = {row.get("sample_product_id") or "" for sig in set(page_sig.values())
                   for row in combo_matches.get(sig, [])}
    sample_pids.discard("")
    pid_key: dict[str, str] = {}
    for pid, key_id in db.execute(
            "SELECT product_id, key_id FROM product_name WHERE name_type = 'trade'"):
        if pid in sample_pids and pid not in pid_key:
            pid_key[pid] = key_id

    def _drug_ref(sid: str, inner: str) -> str:
        if sid and sid in DRUG_PAGE_IDS:
            return f'<a href="../drug/{esc(sid)}.html">{inner}</a>'
        return f'<span class="meta">{inner}</span>'

    def _record_link(pid: str, fallback_sid: str) -> str:
        k = pid_key.get(pid or "")
        u = (entry_by_k.get(k) or {}).get("u") if k else ""
        if u:
            return f'<a href="../name/{esc(u)}" data-i18n="combo.cross_record">record</a>'
        if fallback_sid and fallback_sid in DRUG_PAGE_IDS:
            return (f'<a href="../drug/{esc(fallback_sid)}.html" '
                    f'data-i18n="combo.cross_record">record</a>')
        return '<span data-i18n="combo.cross_record">record</span>'

    def cross_html(slug: str) -> str:
        title_html = (f'<h2 data-i18n="combo.cross_title">'
                      f'{esc(T["combo.cross_title"])}</h2>')
        sig = page_sig.get(slug)
        if not sig:
            return (title_html + f'<p class="sub" data-i18n="combo.cross_unmatched">'
                    f'{esc(T["combo.cross_unmatched"])}</p>')
        mrows = combo_matches.get(sig) or []
        strengths = {r.get("match_strength") for r in mrows}
        if "exact" in strengths:
            by_country = {r.get("country"): r for r in mrows if r.get("country")}
            markets: list[str] = []
            for r in mrows:
                for mk in (r.get("match_markets") or "").split("|"):
                    if mk and mk not in markets:
                        markets.append(mk)
            items = []
            for mk in markets[:8]:
                row = by_country.get(mk)
                if not row:
                    continue
                brands = "; ".join((row.get("brands") or "").split("; ")[:3])
                if not brands:
                    # 部分市场（如美国仿制药）商品名挂在 name_type=inn 下，brands 为空：
                    # 回退显示该市场的主成分/generic 名，而不是空白。
                    brands = key_display.get(row.get("primary_ingredient") or "") or "—"
                n = row.get("n_products") or "0"
                fb = key_sid.get(row.get("primary_ingredient") or "")
                items.append(
                    f'<li><span class="x-mkt">{esc(mk)}</span> · {esc(brands)} · '
                    f'<b>{esc(n)}</b> <span data-i18n="combo.cross_products">products</span> · '
                    f'{_record_link(row.get("sample_product_id") or "", fb or "")}</li>')
            return (title_html
                    + f'<div class="notice" data-i18n="combo.cross_exact">'
                      f'{esc(T["combo.cross_exact"])}</div>'
                    + f'<ul class="xlist">{"".join(items)}</ul>')
        if "overlap" in strengths:
            links: list[str] = []
            for r in mrows:
                if r.get("match_strength") != "overlap":
                    continue
                for msig in (r.get("matched_signatures") or "").split("|"):
                    if msig and msig not in links:
                        links.append(msig)
            items = []
            for msig in links[:5]:
                disp = " + ".join(key_display.get(k) or k for k in msig.split("|"))
                target = (sig_pages.get(msig) or [""])[0]
                if target and target != slug:
                    items.append(f'<li><a href="./{esc(target)}">{esc(disp)}</a></li>')
                else:
                    items.append(f'<li>{esc(disp)}</li>')
            return (title_html
                    + f'<div class="notice warnbox" data-i18n="combo.cross_overlap">'
                      f'{esc(T["combo.cross_overlap"])}</div>'
                    + (f'<ul class="xlist">{"".join(items)}</ul>' if items else ""))
        html = (title_html
                + f'<p class="sub" data-i18n="combo.cross_none">'
                  f'{esc(T["combo.cross_none"])}</p>')
        prim_row = next((r for r in mrows if r.get("primary_cross_market") == "yes"
                         and r.get("primary_ingredient")), None)
        if prim_row:
            psid = key_sid.get(prim_row.get("primary_ingredient") or "")
            if psid:
                link = (f'<a href="../drug/{esc(psid)}.html" '
                        f'data-i18n="combo.cross_primary_link">'
                        f'{esc(T["combo.cross_primary_link"])}</a>'
                        if psid in DRUG_PAGE_IDS else
                        f'<span class="meta">{esc(T["combo.cross_primary_link"])}</span>')
                html += (f'<p class="sub" data-i18n="combo.cross_primary">'
                         f'{esc(T["combo.cross_primary"])} {link}</p>')
        return html

    (OUT / "combo").mkdir(parents=True, exist_ok=True)
    T = I18N["en"]
    made = 0
    stub_made = 0
    for sids, rows in groups.items():
        slug = combo_slug(sids)
        if slug not in COMBO_PAGE_SLUGS:
            # v0.9.2 task-33：被体积策略裁剪的旧组合 URL 保留极简 stub（200/noindex），
            # 避免 v0.9.0 旧链接 404；不加入 sitemap。
            # 所有被裁剪的组合都补，覆盖 v0.9.0 可能存在的 AU-only 旧 URL。
            names = " + ".join(subs.get(s, (s, s))[1] for s in sids)
            stub_items = "".join(
                f'<li>{_drug_ref(s, esc(subs.get(s, (s, s))[1]))}</li>' for s in sids)
            stub = _combo_stub_html(names, stub_items)
            (OUT / "combo" / slug).write_text(stub, encoding="utf-8")
            NOINDEX_RELS.add(f"combo/{slug}")
            stub_made += 1
            continue
        ing_items = []
        for sid in sids:
            zh, en = subs.get(sid, (sid, sid))
            # v0.8.2 task-120：组合页成分名四语（中文优先，无中文名加提示）
            ing_items.append(
                f'<li>{_drug_ref(sid, _sub_name_spans(en, zh, sid))} '
                f'<code>{esc(sid)}</code></li>')
        title = " + ".join(subs.get(s, (s, s))[1] for s in sids)
        rows = sorted(rows, key=lambda e: -e["n"])
        total = len(rows)
        body_rows = []
        for e in rows[:COMBO_ROW_CAP]:
            if e.get("u"):
                brand = f'<a href="../name/{esc(e["u"])}">{esc(e["d"])}</a>'
            else:
                # 品牌列规则：没有品牌页 → 不可点文本；禁止回退 drug 页（无 404 / 不误导）
                brand = (f'<span class="brand-plain" title="{esc(T["combo.no_page"])}">'
                         f'{esc(e["d"])}</span>')
            tags = "".join(
                f'<span class="tag {c.lower()}">{esc(c)}</span>' for c in (e.get("c") or []))
            doses = " / ".join(e.get("s") or []) or "—"
            mah = e.get("m") or "—"
            body_rows.append(
                f'<tr><td class="c-brand" data-label="{esc(T["col.brand"])}" '
                f'data-i18n-label="col.brand">'
                f'{brand}{tags}</td>'
                f'<td data-label="{esc(T["col.dose"])}" data-i18n-label="col.dose">'
                f'{esc(doses)}</td>'
                f'<td data-label="{esc(T["col.mah"])}" data-i18n-label="col.mah">'
                f'{esc(mah)}</td></tr>')
        capped_html = ""
        if total > COMBO_ROW_CAP:
            capped = (T["combo.capped"].replace("{cap}", str(COMBO_ROW_CAP))
                      .replace("{total}", str(total)))
            capped_html = f'<p class="sub">{capped}</p>'
        # 2026-11-12（task-7 ②）：复方页表头四语 —— 旧 task-4③ 以为 v0.10.3 改版后已无表，
        # 现查 6,790 个真复方页仍有这张「Brand / Dose / Manufacturer」表；补 data-i18n /
        # data-i18n-label，界面语言切换后表头与移动端行标签都跟着翻（不再只有英文）。
        rows_html = (
            '<div class="tablewrap"><table class="res"><thead><tr>'
            f'<th data-i18n="col.brand">{T["col.brand"]}</th>'
            f'<th data-i18n="col.dose">{T["col.dose"]}</th>'
            f'<th data-i18n="col.mah">{T["col.mah"]}</th>'
            f'</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'
            if body_rows else
            '<p class="empty" data-i18n="combo.empty">No brand names recorded for this '
            'combination yet.</p>')
        body = f"""<h1>{esc(title)}</h1>
<p class="sub" data-i18n="combo.title">{esc(T["combo.title"])}</p>
<div data-i18n-html="combo.intro">{T["combo.intro"]}</div>
<div class="notice" data-i18n="combo.no_advice">{esc(T["combo.no_advice"])}</div>
<h2 data-i18n="combo.ingredients">{esc(T["combo.ingredients"])}</h2>
<ul class="sub">{''.join(ing_items)}</ul>
<h2 data-i18n="combo.products">{esc(T["combo.products"])}</h2>
{rows_html}
{capped_html}
{cross_html(slug)}
<p class="sub"><a href="../warn.html">{esc(T["combo.see_warnings"])}</a></p>
<div class="notice" data-i18n-html="combo.source_note">{T["combo.source_note"]}</div>"""
        # v0.10.0 P1-7: drop <code> when it repeats the ingredient label
        body = re.sub(r"([^\s<>]+)\s*<code>([^<]+)</code>",
                      lambda m: m.group(1) if m.group(1).lower() == m.group(2).lower() else m.group(0), body)
        (OUT / "combo" / slug).write_text(
            _assert_no_internal_tokens(
                page(title, body, "../", canonical_rel=f"combo/{slug}"),
                f"combo/{slug}"),
            encoding="utf-8")
        made += 1
    print(f"  combo stubs: {stub_made} (noindex, old URL compatibility)")
    return made


MAKER_PRODUCT_CAP = 60   # 每页产品行上限（按国家均摊）；控制 dist 体积（守卫 400MB）


def build_maker_pages(entries, db: sqlite3.Connection) -> int:
    """v0.5.4 / v0.9.0：生成 /maker/<slug>.html（厂家 / 上市许可持有人页）。

    - 数据：data/maker_candidates.csv（v0.9.0 起阈值 1：所有非占位厂家都有页）
    - 内容：厂家名、产品数/市场数/品牌数、按国家分组的品牌行（品牌→品牌页、成分→成分/组合页）、
      来源链接与许可说明；每页产品行最多 MAKER_PRODUCT_CAP（按国家均摊），多出的显示截断提示。
    - 单产品厂家页：底部注明「目前未收录该厂家的其他产品」，noindex,follow 且不进 sitemap。
    - 链接目标全部在构建期验证过（无 404）：combo 只在已经生成了组合页时使用，否则逐个成分链 drug。
    """
    if not MAKERS:
        return 0
    page_makers = {k: v for k, v in MAKERS.items() if v["has"]}
    if not page_makers:
        return 0
    T = I18N["en"]
    (OUT / "maker").mkdir(parents=True, exist_ok=True)
    entry_by_k = {e["k"]: e for e in entries}
    combo_files = {p.name for p in (OUT / "combo").glob("*.html")}
    sub_names: dict[str, tuple[str, str]] = {}
    for sid, inn_zh, inn_en in db.execute(
            "SELECT substance_id, inn_zh, inn_en FROM substance"):
        sub_names[sid] = (inn_zh or inn_en or sid, inn_en or sid)

    # 一次性取产品（只保留有页厂家），再补品牌名与成分
    prod: dict[str, dict] = {}
    for (pid, country, mah, form, base, rel, pack, appr, src) in db.execute(
        """SELECT product_id, COALESCE(country, region) AS mk, mah, dosage_form, form_base, release, pack,
                  approval_id, source_url
           FROM product WHERE mah IS NOT NULL AND mah <> ''"""
    ):
        info = page_makers.get(norm_maker(mah))
        if not info:
            continue
        prod[pid] = {"pid": pid, "country": country, "mah": mah, "mkey": norm_maker(mah),
                     "form": base or form or "", "release": rel if rel != "none" else "",
                     "pack": pack or "", "approval": appr or "", "src": src or "",
                     "keys": [], "sids": set()}
    for pid, key_id in db.execute(
            "SELECT product_id, key_id FROM product_name WHERE name_type = 'trade'"):
        p = prod.get(pid)
        if p is not None:
            p["keys"].append(key_id)
    for pid, sid in db.execute(
            """SELECT pc.product_id, v.substance_id
               FROM product_component pc JOIN variant v ON v.variant_id = pc.variant_id"""):
        p = prod.get(pid)
        if p is not None:
            p["sids"].add(sid)

    by_maker: dict[str, list] = defaultdict(list)
    for p in prod.values():
        by_maker[p["mkey"]].append(p)

    def brand_cell(p: dict, lang: str) -> str:
        if not p["keys"]:
            return '—'
        key_id = p["keys"][0]
        e = entry_by_k.get(key_id)
        label = esc((e or {}).get("d") or key_id)
        if e and e.get("u"):
            return f'<a href="../name/{esc(e["u"])}">{label}</a>'
        return (f'<span class="brand-plain" title="{esc(I18N[lang]["maker.no_page"])}">'
                f'{label}</span>')

    def ingredient_cell(p: dict, lang: str) -> str:
        sids = sorted(p["sids"])
        if not sids:
            # v0.9.1 task-28：无成分产品（名称层）
            return (f'<span class="st-badge st-unknown" data-i18n="ingredient.unrecorded">'
                    f'{esc(I18N[lang]["ingredient.unrecorded"])}</span>')
        labels = []
        for sid in sids[:3]:
            zh, en = sub_names.get(sid, (sid, sid))
            labels.append(esc(zh) if zh else esc(en))
        more = f' <span class="meta">+{len(sids) - 3}</span>' if len(sids) > 3 else ""
        if len(sids) == 1:
            return f'<a href="../drug/{esc(sids[0])}.html">{labels[0]}</a>' + more
        slug = combo_slug(sids)
        text = " + ".join(labels) + more
        if slug in combo_files:
            return f'<a href="../combo/{esc(slug)}">{text}</a>'
        parts = [f'<a href="../drug/{esc(sid)}.html">{lab}</a>'
                 for sid, lab in zip(sids[:3], labels)]
        return " · ".join(parts) + more

    made = 0
    for mkey, rows in by_maker.items():
        info = page_makers[mkey]
        rows.sort(key=lambda p: (p["country"], (entry_by_k.get(p["keys"][0]) or {}).get("d", "")
                                 if p["keys"] else "~"))
        countries = [c for c in COUNTRY_PRIORITY if c in {p["country"] for p in rows}]
        countries += sorted({p["country"] for p in rows} - set(countries))
        brands = {(entry_by_k.get(p["keys"][0]) or {}).get("k", p["keys"][0])
                  for p in rows if p["keys"]}
        n_products = len(rows)
        stats_vals = {"name": info["name"], "products": f"{n_products:,}",
                      "markets": str(len(countries)), "brands": f"{len(brands):,}"}
        intro_blocks = ""
        stats_blocks = ""
        for lang in ("en", "es", "zh"):
            li = I18N[lang]["maker.intro"]
            ls = I18N[lang]["maker.stats"]
            for k, v in stats_vals.items():
                li = li.replace("{" + k + "}", v)
                ls = ls.replace("{" + k + "}", v)
            intro_blocks += f'<div class="lang-block" data-lang-block="{lang}">{li}</div>'
            stats_blocks += f'<div class="lang-block" data-lang-block="{lang}">{ls}</div>'

        # 产品行：按国家均摊上限，保证每个国家都能露面
        per_country = max(1, (MAKER_PRODUCT_CAP + len(countries) - 1) // max(1, len(countries)))
        by_country: dict[str, list] = defaultdict(list)
        for p in rows:
            by_country[p["country"]].append(p)
        shown = 0
        sections = []
        for country in countries:
            items = by_country[country][:per_country]
            if shown + len(items) > MAKER_PRODUCT_CAP:
                items = items[:max(0, MAKER_PRODUCT_CAP - shown)]
            if not items:
                continue
            shown += len(items)
            body_rows = []
            for p in items:
                form = esc(p["form"]) if p["form"] else "—"
                body_rows.append(
                    f'<tr><td class="c-brand" data-i18n-label="maker.brand">'
                    f'{brand_cell(p, "en")}</td>'
                    f'<td data-i18n-label="maker.ingredient">{ingredient_cell(p, "en")}</td>'
                    f'<td data-i18n-label="name.form">{form}</td></tr>')
            src = next((p["src"] for p in items if p["src"]), "")
            src_html = (f'<p class="sub"><span data-i18n="maker.source">Source</span>: '
                        f'<a href="{esc(src)}" target="_blank" rel="noopener">'
                        f'{esc(src.split("//")[-1].split("/")[0])}</a></p>'
                        if src else "")
            sections.append(
                f'<h2>{esc(country)} <span class="meta">({len(by_country[country])} '
                f'<span data-i18n="drug.records">records</span>)</span></h2>{src_html}'
                '<div class="tablewrap"><table class="res"><thead><tr>'
                f'<th data-i18n="maker.brand">{esc(T["maker.brand"])}</th>'
                f'<th data-i18n="maker.ingredient">{esc(T["maker.ingredient"])}</th>'
                f'<th data-i18n="name.form">{esc(T["name.form"])}</th>'
                f'</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>')
        capped_blocks = ""
        if n_products > shown:
            for lang in ("en", "es", "zh"):
                note = (I18N[lang]["maker.capped"]
                        .replace("{shown}", f"{shown:,}").replace("{total}", f"{n_products:,}"))
                capped_blocks += (f'<div class="lang-block" data-lang-block="{lang}">'
                                  f'<p class="sub">{esc(note)}</p></div>')
        single_html = ""
        single = n_products == 1
        if single:
            for lang in ("en", "es", "zh", "zh-Hant"):
                note = I18N[lang].get("maker.single_note") or I18N["en"]["maker.single_note"]
                single_html += (f'<div class="lang-block" data-lang-block="{lang}">'
                                f'<p class="sub maker-single-note">{esc(note)}</p></div>')
        body = f"""<h1>{esc(info["name"])}</h1>
<p class="sub" data-i18n="maker.title">{esc(T["maker.title"])}</p>
{intro_blocks}
{stats_blocks}
<h2 data-i18n="maker.by_country">{esc(T["maker.by_country"])}</h2>
{''.join(sections) if sections else '<p class="empty" data-i18n="maker.empty">No products recorded.</p>'}
{capped_blocks}
<div class="notice" data-i18n-html="maker.source_note">{T["maker.source_note"]}</div>
{single_html}"""
        rel = f'maker/{info["slug"]}.html'
        if single:
            NOINDEX_RELS.add(rel)
        (OUT / "maker" / f'{info["slug"]}.html').write_text(
            page(info["name"], body, "../", noindex=single,
                 canonical_rel=f'maker/{info["slug"]}.html'), encoding="utf-8")
        made += 1
    # v0.9.0 task-20：明细面板按原始 MAH 名查厂家页 slug（懒加载，避免结果索引塞 18k 条）。
    maker_map = {p["mah"]: page_makers[p["mkey"]]["slug"]
                 for p in prod.values() if p["mkey"] in page_makers}
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    (OUT / "data" / "maker-map.json").write_text(
        json.dumps(maker_map, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return made


def _spec_num(st: str) -> float:
    """取规格里的首个数字（成分页分组排序 + 品牌页写法排序共用，T10 起提到模块级）。

    v0.10.2 修：`1,000,000` 是千分位、不是小数点；`1.23e+06` 也要认。
    旧实现把 `1,000,000` 读成 1.000000 → 大规格排到最后。
    """
    m2 = re.match(r"\s*([0-9][0-9.,]*(?:[eE][+-]?[0-9]+)?)", st or "")
    if not m2:
        return -1.0
    tok = m2.group(1).rstrip(".,")
    if re.fullmatch(r"[0-9]{1,3}(,[0-9]{3})+(\.[0-9]+)?([eE][+-]?[0-9]+)?", tok):
        tok = tok.replace(",", "")
    else:
        tok = tok.replace(",", ".")
    try:
        return float(tok)
    except ValueError:
        return -1.0


def _sort_strength(text: str) -> float:
    """旧接口保留（调用点多），统一走 `_spec_num`：`1,000 mg` / `1.23e+06` 都认。"""
    return _spec_num(text)


# v0.6.5：首页示例按钮按页面语言渲染（en/es/zh/zh-Hant；zh-Hant 用繁體示例）
# v0.9.6 task-143：去掉原「hero」一整排示例按钮（与 3 步引导里的 Try 重复），只留引导内示例。
HOME_EXAMPLES = {
    "en": {"try1": ["Lipitor 20mg", "Tylenol"], "try2": ["Paracetamol 500mg"],
           "try3": ["Benadryl", "Gaviscon"]},
    "es": {"try1": ["Paracetamol 500mg", "Omeprazol 20mg"],
           "try2": ["Ibuprofeno 600mg"], "try3": ["Loratadina 10mg", "Omeprazol 20mg"]},
    "zh": {"try1": ["泰诺", "Lipitor 20mg"], "try2": ["两只青蛙"],
           "try3": ["Benadryl", "Gaviscon"]},
    "zh-Hant": {"try1": ["泰諾", "Lipitor 20mg"], "try2": ["兩隻青蛙"],
                "try3": ["Benadryl", "Gaviscon"]},
}


def _sample_buttons(queries) -> str:
    return "".join(f'<button type="button" data-q="{esc(q)}">{esc(q)}</button>'
                   for q in queries)


def _app_boot(prefix: str) -> str:
    """v0.9.1 task-22：首屏先渲染，load 后再注入 app.js，降低 LCP render delay。

    v0.11.5 task-8：app.js 是稳定文件名、内容随 BUILD_V 变，这里也带 ?v=BUILD_V
    （README 口径：稳定名资源必须带版本参数）。注：当前首页模板里 `{APP_BOOT}` 占位已被
    `_optimize_home_html` 的注入取代，本函数在现有 5 个首页产物中不出现（见报告 §7），
    保留并按同口径加版本号，避免以后接回模板时再踩裸 URL 缓存坑。
    """
    return ('<script>window.addEventListener("load",function(){'
            'var s=document.createElement("script");'
            f's.src="{prefix}assets/app.js?v={BUILD_V}";'
            'document.body.appendChild(s);});</script>')


def _coverage_entry_js(root_expr: str) -> str:
    """v0.9.6 task-142：nav / footer 的「覆盖与新鲜度」入口注入（幂等）。

    顶层页已由 page(nav_coverage=True) 写好静态链接（带 data-coverage），约 121k 个
    长尾页仍靠这里补。除了 data-coverage 再按 href 判断一次：页面已有静态链接时
    不插第二次，脚本重复执行也安全。
    root_expr 是站点根 URL 的 JS 表达式（boot.js 用 'r'，首页内联用 '_r'）。
    """
    return (
        "(function(){var n=document.querySelector('header nav');"
        "function has(el){if(!el)return true;"
        "if(el.querySelector('[data-coverage]'))return true;"
        "var as=el.getElementsByTagName('a');"
        "for(var i=0;i<as.length;i++){var h=as[i].getAttribute('href')||'';"
        "if(h.indexOf('coverage.html')>=0)return true;}return false;}"
        "if(n&&!has(n)){var a=document.createElement('a');"
        "a.href=" + root_expr + "+'coverage.html';"
        "a.setAttribute('data-i18n','nav.coverage');"
        "a.setAttribute('data-coverage','1');a.textContent='Coverage';"
        "n.insertBefore(a,n.querySelector('.langs')||null);}"
        "var f=document.querySelector('.foot-links');"
        "if(f&&!has(f)){var b=document.createElement('a');"
        "b.href=" + root_expr + "+'coverage.html';"
        "b.setAttribute('data-i18n','nav.coverage');"
        "b.setAttribute('data-coverage','1');b.textContent='Coverage';f.appendChild(b);}})();"
    )


def _optimize_home_html(html: str, prefix: str, lang: str = "en") -> str:
    """v0.9.2 task-34：首页首屏优化（仅首页，避免全站 HTML 膨胀）。

    - CSS 内联，去掉 24KB 阻塞样式请求；
    - i18n 内联并在 body 末尾立即 apply()，避免 defer 脚本拖 LCP；
      v0.10.1 P2-2：只内联**当前语言**的字典（四语 128.8 KB → 22–42 KB）。
      语言切换走 /es/ /zh/ /zh-hant/ 静态副本的整页导航，首屏只需当前语言；
      v0.10.2：?lang= 深链或 localStorage 偏好与内联语言不一致时，只补载那一份
      assets/i18n.<lang>.js（≈14 KB gz，原先补四语全量 59 KB gz），拉不到再回落全量；
    - app.js / bilingual.js 在 load 后注入，保证搜索可用但不挡首屏。
    """
    css_inline = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    css_inline = re.sub(r"\s*([{};])\s*", r"\1", css_inline)
    css_inline = re.sub(r"\s+", " ", css_inline).strip()
    html = re.sub(
        rf'<link rel="stylesheet" href="{re.escape(prefix + CSS_FILE)}(?:\?v=[^"]*)?">',
        f"<style>{css_inline}</style>", html, count=1)
    for _name in ("i18n.js", "bilingual.js", "app.js"):
        html = re.sub(
            rf'<script defer src="{re.escape(prefix)}assets/{re.escape(_name)}(?:\?v=[^"]+)?"></script>',
            "", html)
    i18n_path = OUT / "assets" / "i18n.js"
    i18n_js = (i18n_path.read_text(encoding="utf-8") if i18n_path.exists() else "")
    i18n_js = i18n_js.replace(
        "window.addEventListener('load', apply);",
        "apply(); window.addEventListener('load', apply);")
    # task-70：内联字典不能带全局构建号，否则每次构建首页都变。
    i18n_js = i18n_js.replace(BUILD_V, "")
    # v0.10.1：i18n.js = "window.I18N=<四语字典>;\n<逻辑>"，只把字典换成当前语言子集，
    # 后面的 T()/apply()/语言链接逻辑原样保留，行为不变。
    m = re.match(r"window\.I18N=(\{.*?\});\n", i18n_js, re.S)
    if m:
        full = json.loads(m.group(1))
        keep = [lang] if lang in full else ["en"]
        subset = {code: full[code] for code in keep}
        i18n_js = ("window.I18N=" + json.dumps(subset, ensure_ascii=False,
                                               separators=(",", ":")) + ";\n"
                   + i18n_js[m.end():])
    # v0.9.7 task-10（用户报障「切换语言跳 404」）：这里必须用 Python 侧算好的前缀。
    # 原写法是 f'... new URL({prefix!r} || "../", location.href)' —— JS 里 '' 是 falsy，
    # 根级首页（prefix=''）会取到 "../"，于是 ROOT = new URL('../', '.../drug-brand-crossref/index.html')
    # = 域名根 https://<user>.github.io/（越过项目子路径一层）；langTarget() 再拼
    # ROOT + 'zh/index.html' 就落到域名根的 /zh/index.html，GitHub Pages 返回默认 404。
    # 改成 './'：根级首页解析到项目根，语言副本（prefix='../'）行为不变。
    root_prefix = prefix or "./"
    boot = (
        f'<script>window.__DSH_I18N_ROOT=new URL({root_prefix!r}, location.href).href;</script>'
        + f'<script>var _r=new URL({root_prefix!r}, location.href).href;'
        + _coverage_entry_js("_r")
        + "</script>"
        + f"<script>window.__I18N_PARTIAL={lang!r};{i18n_js}</script>"
        + "<script>window.addEventListener('load',function(){"
        # v0.11.5 task-8：app.js / bilingual.js 是**稳定文件名**（内容随 BUILD_V 变），
        # 必须带 ?v=BUILD_V，否则浏览器缓存旧版首页搜索逻辑（verify_live 的 homepage-appjs 守卫也查这个）。
        + f"var s=document.createElement('script');s.src='{prefix}assets/app.js?v={BUILD_V}';"
        + "document.body.appendChild(s);"
        + f"var b=document.createElement('script');b.src='{prefix}assets/bilingual.js?v={BUILD_V}';"
        + "document.body.appendChild(b);});</script>")
    return html.replace("</body>", boot + "</body>")


def _home_recent(prefix: str, limit: int = 3) -> str:
    """v0.9.6 task-143：首页「最近更新」= CHANGELOG 最近 N 个版本。

    版本号和日期是事实（四语共用，不做翻译）；摘要正文仍只在 whats-new 页，
    避免把只翻了三语的更新说明搬进首屏。
    """
    releases = load_releases()[:limit]
    if not releases:
        return ""
    items = "".join(
        f'<li><a href="{prefix}whats-new.html"><b>{esc(r["version"])}</b>'
        f'<span class="upd-date">{esc(r["date"])}</span></a></li>' for r in releases)
    return (f'<section class="homeupd" aria-labelledby="updtitle">'
            f'<h2 id="updtitle" data-i18n="home.recent">Recently updated</h2>'
            f'<ul class="updlist">{items}</ul>'
            f'<p class="sub"><a href="{prefix}whats-new.html" data-i18n="home.recent_all">'
            f'See all updates →</a></p></section>')


def build_index_page(entries, stats, coverage) -> None:
    """四份落地页：/ 、/es/ 、/zh/ 、/zh-hant/。内容相同，语言由脚本按路径/参数决定。"""
    covline = ", ".join(f"{r['country']} {r['n_products']:,}" for r in coverage)
    body = f"""<h1 id="h1" data-i18n="home.h1">Look up a medicine name — see what it is in each country</h1>
<p class="sub" data-i18n="home.sub">Brand name, generic name, nickname, or a line from the pack — Chinese, full-width and Cyrillic input all work.</p>
<p class="candidate-line" data-i18n="home.candidate">You always get a candidate set, never a single answer.</p>
<ol class="flow3">
  <li><span class="n" aria-hidden="true">1</span><span data-i18n="flow.s1">Name</span></li>
  <li><span class="n" aria-hidden="true">2</span><span data-i18n="flow.s2">Confirm product</span></li>
  <li><span class="n" aria-hidden="true">3</span><span data-i18n="flow.s3">Target market</span></li>
</ol>
<div class="searchwrap">
<div class="searchbar">
<label class="sr-only" for="q" data-i18n="home.ph">Brand name / generic name / nickname / a line from the pack</label>
<input id="q" data-ph="home.ph" placeholder="Brand name / generic name / nickname / a line from the pack" autocomplete="off" aria-autocomplete="list" aria-controls="ac" enterkeyhint="search">
<span class="sb-hint" data-i18n="home.slash_hint">Press / to focus</span>
<button type="button" id="qgo" class="sb-go" data-i18n-aria="home.submit" aria-label="Search"><span aria-hidden="true">→</span></button>
<div id="ac" role="listbox" aria-label="Suggestions" data-i18n-aria="home.suggestions"></div>
</div>
<div class="t11row">
<p class="sub search-status" id="meta" role="status" aria-live="polite" aria-atomic="true"></p>
<a class="mkopen" href="#ctrydetails" data-i18n="home.country_label">Target market</a>
<div class="mkchips" id="mkchips" role="group" data-i18n-aria="home.country_label"></div>
</div>
<div id="pickbar" class="pickbar" hidden></div>
</div>
<div id="srcnote" class="srcnote" hidden role="status" aria-live="polite"></div>
<div id="identity"></div>
<div id="out"></div>
<details class="mf-details advfilter ctry-details" id="ctrydetails">
  <summary data-i18n="t11.adv">Advanced filters</summary>
  <div class="ctry-panel">
  <label class="sel-label" for="country" data-i18n="home.country_label">Target market: show the names used there (optional)</label>
  <select id="country"><option value="" data-i18n="home.all">All countries and regions</option>
    <option value="US" data-i18n="home.us">United States</option>
    <option value="GB" data-i18n="home.gb">United Kingdom</option>
    <option value="CN" data-i18n="home.cn">China</option>
    <option value="ES" data-i18n="home.es">Spain</option>
    <option value="MX" data-i18n="home.mx">Mexico</option>
    <option value="AU" data-i18n="home.au">Australia</option>
    <option value="CA" data-i18n="home.ca">Canada</option>
    <option value="TW" data-i18n="home.tw">Taiwan</option>
    <option value="HK" data-i18n="home.hk">Hong Kong</option>
    <option value="SG" data-i18n="home.sg">Singapore</option>
    <option value="EU" data-i18n="home.eu">European Union (EU)</option><option value="FR" data-i18n="home.fr">France</option></select>
  <label class="sel-label src-label" for="src" data-i18n="res.src_label">Source market (only records from):</label>
  <select id="src"><option value="" data-i18n="res.src_all">All source markets</option>
    <option value="US" data-i18n="home.us">United States</option>
    <option value="GB" data-i18n="home.gb">United Kingdom</option>
    <option value="CN" data-i18n="home.cn">China</option>
    <option value="ES" data-i18n="home.es">Spain</option>
    <option value="MX" data-i18n="home.mx">Mexico</option>
    <option value="AU" data-i18n="home.au">Australia</option>
    <option value="CA" data-i18n="home.ca">Canada</option>
    <option value="TW" data-i18n="home.tw">Taiwan</option>
    <option value="HK" data-i18n="home.hk">Hong Kong</option>
    <option value="SG" data-i18n="home.sg">Singapore</option>
    <option value="EU" data-i18n="home.eu">European Union (EU)</option><option value="FR" data-i18n="home.fr">France</option></select>
  </div>
</div>
<p class="sub report-line" id="report" style="display:none">
  <span data-i18n="report.note">Wrong ingredient, wrong dose, or a drug we do not have? Tell us:</span>
  <a id="reportLink" href="{REPORT_REPO}/issues/new?labels=data-error&amp;template=data-error.yml"
     target="_blank" rel="noopener" data-i18n="report.cta">Report this result</a>
</p>
<section id="u1guide" class="u1guide" aria-labelledby="u1title" data-i18n-aria="u1.aria">
  <div class="u1head"><h2 id="u1title" data-i18n="u1.title">How to use it in 3 steps</h2>
    <button type="button" id="u1close" class="u1close" data-i18n-aria="u1.close"
      aria-label="Dismiss">×</button></div>
  <ol class="u1steps">
    <li class="u1step"><b data-i18n="u1.step1">Type the name from the pack</b>
      <p class="sub" data-i18n="u1.step1_hint">Brand, generic name, nickname, or a line from the pack — dose included is fine.</p>
      <div class="u1try"><span data-i18n="u1.try">Try:</span>
        {{try1}}</div></li>
    <li class="u1step"><b data-i18n="u1.step2">Check this candidate: ingredient, strength, dosage form</b>
      <p class="sub" data-i18n="u1.step2_hint">The card shows one candidate, never the answer — check its ingredient, strength and form against your pack.</p>
      <div class="u1try"><span data-i18n="u1.try">Try:</span>
        {{try2}}</div></li>
    <li class="u1step"><b data-i18n="u1.step3">Pick the target market</b>
      <p class="sub" data-i18n="u1.step3_hint">Pick a target market to see what the same ingredient is called there; the candidate list itself does not change.</p>
      <div class="u1try"><span data-i18n="u1.try">Try:</span>
        {{try3}}</div></li>
  </ol>
</section>
<section class="catquick"><h2 data-i18n="cat.quick_title">Browse by category</h2>
<div class="catgrid">{{cat_chips}}</div></section>
{{recent}}
<p class="sub" id="loadhint" data-i18n="home.hint_idle">First search loads one index shard (median ~1.0 MB, ~0.16 MB gzip); the full index (core ~42 MB raw, ~9–10 MB gzip) fills in the background — start typing, focus the search box, or pick a sample.</p>
<div class="notice"><span data-i18n="home.coverage">An empty result does not mean the medicine
does not exist. Coverage:</span> {covline}.</div>
<script defer src="{{prefix}}assets/app.js"></script>"""
    for code, _label, path in LANGS:
        prefix = "../" if path else ""
        ex = HOME_EXAMPLES.get(code) or HOME_EXAMPLES["en"]
        page_body = (body.replace("{prefix}", prefix)
                     .replace("{try1}", _sample_buttons(ex["try1"]))
                     .replace("{try2}", _sample_buttons(ex["try2"]))
                     .replace("{try3}", _sample_buttons(ex["try3"]))
                     .replace("{cat_chips}", _home_cat_chips(code, prefix))
                     .replace("{recent}", _home_recent(prefix))
                     .replace("{APP_BOOT}", _app_boot(prefix)))
        html = page("Medicine Brand Cross-Reference", page_body,
                    prefix=prefix, lang=code, alternates=True, meta_key="index",
                    canonical_rel=path, alt_rel="",
                    head_js=U1_HEAD_JS + '<link rel="alternate" type="application/ld+json" href="../dataset.jsonld">' if path else
                    U1_HEAD_JS + '<link rel="alternate" type="application/ld+json" href="dataset.jsonld">',
                    defer_i18n=False, nav_coverage=True)
        target = OUT / (path + "index.html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_optimize_home_html(html, prefix, code), encoding="utf-8")


SOURCE_SHORT = {
    "openfda_ndc": "openFDA",
    "dmd": "dm+d",
    "nhsa": "NHSA",
    "pbs": "PBS",
    "tga_cmi": "TGA CMI",
    "artg_index": "ARTG",
    "artg_enrich": "ARTG",
    "artg_detail": "ARTG",
    "cima": "CIMA",
    "cofepris_mx": "COFEPRIS",
    "hc_dpd": "Health Canada DPD",
    "manual_seed": "manual",
}


def _as_of_cell(rows) -> str:
    """覆盖表的「数据日期」：主源日期 + 其他有日期的源；实时源标 live，年度清单标 —。

    旧的第三列取 product.retrieved_at（我们的抓取时间），会把 2025-04-04 的
    中国快照显示成 2026-10-26，所以改成 source.data_as_of。
    """
    rows = [r for r in rows if (r["n_products"] or 0) >= 100] or list(rows)
    groups: list[list] = []
    for r in rows:
        label = SOURCE_SHORT.get(r["source_id"], r["source_id"])
        if r["data_as_of"]:
            text = str(r["data_as_of"])
            if len(text) > 10 and text[10] in "T ":
                text = text[:10]
        elif (r["data_as_of_note"] or "") == "live":
            text = "live"
        else:
            continue
        for g in groups:
            if g[0] == text:
                g[1].append(label)
                break
        else:
            groups.append([text, [label]])
    if not groups:
        return "—"
    first_text, first_labels = groups[0]
    out = f"{first_text} ({', '.join(dict.fromkeys(first_labels))})"
    for text, labels in groups[1:]:
        out += f" + {text} ({', '.join(dict.fromkeys(labels))})"
    return esc(out)


def build_about(stats, coverage, source_cover=()) -> None:
    """About：正文按块走 data-i18n-html（三语字典，占位符已在 main() 里替换成当前库统计）。

    许可/署名段为 reports/license-audit.md §4 的三语并列原文（LICENCE_HTML），
    ATC 覆盖用双口径（全部 substance / 药物实体 inn_drug），均为构建期动态计算。
    """
    T = I18N["en"]
    parts = [f'<h1 data-i18n="about.title">{esc(T["about.title"])}</h1>']
    for key in ("about.lead", "about.rules", "about.nick", "about.terms",
                "about.sources", "about.tw_source", "about.sg_source", "about.hk_source",
                "about.au_source", "about.eu_source", "about.fr_source"):
        parts.append(f'<div data-i18n-html="{key}">{T[key]}</div>')
    parts.append('<details class="lic-wrap"><summary data-i18n="about.licences_summary">'
                 'Data sources and licences</summary>' + LICENCE_HTML + '</details>')
    for key in ("about.samename", "about.gaps"):
        parts.append(f'<div data-i18n-html="{key}">{T[key]}</div>')
    if GOATCOUNTER_CODE:
        parts.append(f'<div data-i18n-html="about.analytics">{T["about.analytics"]}</div>')
    parts.append(f'<div data-i18n-html="about.stats">{T["about.stats"]}</div>')
    parts.append('<p class="sub"><a href="datapackage.json" data-i18n="about.data_package">'
                 'Data package</a> · '
                 '<a href="dataset.jsonld" data-i18n="about.dataset_jsonld">'
                 'Dataset metadata (schema.org)</a> · '
                 '<a href="checksums.txt" data-i18n="about.checksums">SHA-256 checksums</a> · '
                 '<a href="docs/data-dictionary.md" data-i18n="about.data_dictionary">'
                 'Data dictionary</a></p>')
    parts.append('<p class="sub"><a href="coverage.html" data-i18n="nav.coverage">Coverage &amp; freshness</a></p>')
    body = "\n".join(parts)
    # v0.10.0 P1-5：来源表补 thead/tbody（渲染期一次性修正，三语共用）
    body = re.sub(r'<table><tr><th>(.*?)</tr>',
                  r'<table><thead><tr><th>\1</tr></thead><tbody>', body, count=1, flags=re.S)
    body = body.replace('</table>', '</tbody></table>', 1)
    html = page("About", body, meta_key="about", alternates=True,
                canonical_rel="about.html", alt_rel="about.html",
                head_js='<link rel="alternate" type="application/ld+json" href="dataset.jsonld">',
                nav_coverage=True)
    _write_with_copies("about.html", html, "about")

COVERAGE_SORT_JS = """
<script>(function(){var t=document.getElementById('covtable');if(!t)return;
var tb=t.querySelector('tbody');var rows=Array.prototype.slice.call(tb.rows);
document.querySelectorAll('[data-covsort]').forEach(function(b){
  b.addEventListener('click',function(){
    var k=b.getAttribute('data-covsort');
    var sorted=rows.slice().sort(function(a,c){
      if(k==='products'){return parseInt(c.cells[1].textContent.replace(/[^0-9]/g,''),10)-parseInt(a.cells[1].textContent.replace(/[^0-9]/g,''),10);}
      return a.cells[0].textContent.localeCompare(c.cells[0].textContent);
    });
    sorted.forEach(function(r){tb.appendChild(r);});
    document.querySelectorAll('[data-covsort]').forEach(function(x){x.classList.remove('on');});
    b.classList.add('on');
  });
});})();</script>
"""


def build_coverage_page(db: sqlite3.Connection, coverage, source_cover=()) -> None:
    """v0.9.4 A4：每市场覆盖/新鲜度页（只列事实，不写数据口径）。"""
    stats = {}
    for r in db.execute(
            """SELECT COALESCE(p.country, p.region) AS country,
                      COUNT(DISTINCT CASE WHEN pc.product_id IS NOT NULL
                                          THEN p.product_id END) AS mapped,
                      COUNT(DISTINCT CASE WHEN pc.strength_value IS NOT NULL
                                          THEN p.product_id END) AS spec
               FROM product p
               LEFT JOIN product_component pc ON pc.product_id = p.product_id
               GROUP BY COALESCE(p.country, p.region)"""):
        stats[r["country"]] = dict(r)
    no_trade = {r[0]: r[1] for r in db.execute(
        """SELECT COALESCE(p.country, p.region) AS country, COUNT(*) FROM product p
           WHERE NOT EXISTS (SELECT 1 FROM product_name pn
                             WHERE pn.product_id=p.product_id AND pn.name_type='trade')
           GROUP BY COALESCE(p.country, p.region)""")}
    asof = {}
    for r in source_cover:
        c, d = r.get("country"), r.get("data_as_of")
        if c and d:
            asof[c] = max(asof.get(c, ""), d)
    T = I18N["en"]
    rows = []
    for r in coverage:
        c = r.get("country") or ""
        n = int(r.get("n_products") or 0)
        s = stats.get(c, {})
        mapped = int(s.get("mapped") or 0)
        spec = int(s.get("spec") or 0)
        nt = int(no_trade.get(c) or 0)
        mpct = (mapped / n * 100) if n else 0
        spct = (spec / n * 100) if n else 0
        gap_key = f"coverage.gap.{c.lower()}"
        gap = T.get(gap_key, "")
        note = f'<span data-i18n="{gap_key}">{esc(gap)}</span>'
        if nt and c == "CN":
            note += (f' <span class="meta">· {nt:,} ({nt / n * 100:.1f}%) '
                     f'<span data-i18n="coverage.no_brand">no trade-name records</span></span>')
        rows.append(
            f'<tr id="market-{c}"><td data-label="{esc(T["coverage.col.market"])}">'
            f'<span data-i18n="home.{c.lower()}">{esc(T.get("home." + c.lower(), c))}</span> '
            f'<span class="meta">{esc(c)}</span></td>'
            f'<td data-label="{esc(T["coverage.col.products"])}">{n:,}</td>'
            f'<td data-label="{esc(T["coverage.col.mapping"])}">{mpct:.1f}%'
            f' <span class="meta">({mapped:,}/{n:,})</span></td>'
            f'<td data-label="{esc(T["coverage.col.spec"])}">{spct:.1f}%'
            f' <span class="meta">({spec:,}/{n:,})</span></td>'
            f'<td data-label="{esc(T["coverage.col.last"])}" '
            f'title="{esc(r.get("last_synced") or "")}">{esc((r.get("last_synced") or "—")[:10])}</td>'
            f'<td data-label="{esc(T["coverage.col.asof"])}">{esc(asof.get(c) or "—")}</td>'
            f'<td data-label="{esc(T["coverage.col.notes"])}">{note}</td></tr>')
    body = f"""<h1 data-i18n="coverage.title">{esc(T["coverage.title"])}</h1>
<p class="sub" data-i18n="coverage.intro">{esc(T["coverage.intro"])}</p>
<div class="notice" data-i18n="coverage.notice">{esc(T["coverage.notice"])}</div>
<div class="covtools"><button type="button" data-covsort="products" data-i18n="coverage.sort_products">By products</button>
<button type="button" data-covsort="market" data-i18n="coverage.sort_market">By market</button></div>
<div class="tablewrap"><table class="res coverage-table" id="covtable"><thead><tr>
<th data-i18n="coverage.col.market">{esc(T["coverage.col.market"])}</th>
<th data-i18n="coverage.col.products">{esc(T["coverage.col.products"])}</th>
<th data-i18n="coverage.col.mapping">{esc(T["coverage.col.mapping"])}</th>
<th data-i18n="coverage.col.spec">{esc(T["coverage.col.spec"])}</th>
<th data-i18n="coverage.col.last">{esc(T["coverage.col.last"])}</th>
<th data-i18n="coverage.col.asof">{esc(T["coverage.col.asof"])}</th>
<th data-i18n="coverage.col.notes">{esc(T["coverage.col.notes"])}</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p class="sub" data-i18n="coverage.source_note">{esc(T["coverage.source_note"])}</p>""" + COVERAGE_SORT_JS
    html = page("Coverage & freshness", body, meta_key="coverage", alternates=True,
                canonical_rel="coverage.html", alt_rel="coverage.html", nav_coverage=True)
    _write_with_copies("coverage.html", html, "coverage")


def build_confused(db: sqlite3.Connection) -> int:
    """易混淆药对页：只列有官方出处的配对。"""
    rows = db.execute(
        """SELECT cp.*, sa.inn_en AS a_inn, sa.inn_zh AS a_zh,
                  sb.inn_en AS b_inn, sb.inn_zh AS b_zh
           FROM confusable_pair cp
           LEFT JOIN substance sa ON sa.substance_id = cp.a_substance_id
           LEFT JOIN substance sb ON sb.substance_id = cp.b_substance_id
           ORDER BY cp.norm_a, cp.norm_b"""
    ).fetchall()

    def cell(sid, zh, inn, name):
        label = esc(zh or inn or name)
        en = f' <span class="meta">{esc(inn or name)}</span>' if (inn or name) else ""
        if sid:
            return f'<a href="drug/{esc(sid)}.html">{label}</a>{en}'
        return f'{label}{en}'

    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{cell(r['a_substance_id'], r['a_zh'], r['a_inn'], r['name_a'])}</td>"
            f"<td>{cell(r['b_substance_id'], r['b_zh'], r['b_inn'], r['name_b'])}</td>"
            f"<td><code>{esc(r['tml_a'])}</code> / <code>{esc(r['tml_b'])}</code></td>"
            "</tr>"
        )
    body = f"""<h1 data-i18n="conf.title">Easily confused drug names</h1>
<p class="sub" data-i18n="conf.intro">Look-alike / sound-alike pairs from the FDA Name
Differentiation Project. This is the official tall-man list, not the full ISMP LASA list.</p>
<div class="notice" data-i18n="conf.note">A pair here means the names can be mistaken for each
other; it does not mean the drugs are interchangeable.</div>
<h2 data-i18n="conf.h2">FDA tall-man pairs</h2>
<div class="tablewrap"><table><thead><tr>
  <th data-i18n="conf.pair">Pair</th><th></th><th data-i18n="conf.tml">Tall-man spelling</th>
</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>
<p class="sub" data-i18n-html="conf.source_note">{I18N['en']['conf.source_note']}</p>"""
    html = page("Easily confused drug names", body, meta_key="confused", alternates=True,
                canonical_rel="confused.html", alt_rel="confused.html", nav_coverage=True)
    _write_with_copies("confused.html", html, "confused")
    return len(rows)


GLOSSARY_TERMS = ("inn", "ban", "usan", "atc", "mah", "din", "ndc", "artg",
                  "fdc", "lasa", "otc", "rx", "strength")


# ── v0.8.1 双语对照（成分原名 + 当前语言译名 + 来源/版本；品牌永不翻译）────────
# ── v0.8.3 task-119：矩阵筛选器文案（四语）──────────────────────────────────
FILTER_I18N = {
    "en": {"matrix.filters": "Filters", "matrix.mobile_filters": "Filters",
           "matrix.country": "Countries & regions", "matrix.form": "Form",
           "matrix.release": "Release", "matrix.spec_search": "Search strength",
           "matrix.reset": "Restore defaults", "matrix.all": "All",
           "matrix.showing": "{n} / {total} rows",
           "matrix.sort_note": "Common strengths first; undisclosed strength last.",
           "matrix.spec_check": "check strength",
           "matrix.close": "Close"},
    "es": {"matrix.filters": "Filtros", "matrix.mobile_filters": "Filtros",
           "matrix.country": "Países y regiones", "matrix.form": "Forma",
           "matrix.release": "Liberación", "matrix.spec_search": "Buscar concentración",
           "matrix.reset": "Restaurar valores", "matrix.all": "Todos",
           "matrix.showing": "{n} / {total} filas",
           "matrix.sort_note": "Concentraciones más comunes primero; sin datos al final.",
           "matrix.spec_check": "verificar concentración",
           "matrix.close": "Cerrar"},
    "zh": {"matrix.filters": "筛选", "matrix.mobile_filters": "筛选",
           "matrix.country": "国家/地区", "matrix.form": "剂型", "matrix.release": "释放",
           "matrix.spec_search": "搜索规格", "matrix.reset": "恢复默认",
           "matrix.all": "全部", "matrix.showing": "{n} / {total} 行",
           "matrix.sort_note": "常用规格在前；未公开规格排最后。",
           "matrix.spec_check": "规格待核",
           "matrix.close": "关闭"},
    "zh-Hant": {"matrix.filters": "篩選", "matrix.mobile_filters": "篩選",
                "matrix.country": "國家/地區", "matrix.form": "劑型", "matrix.release": "釋放",
                "matrix.spec_search": "搜尋規格", "matrix.reset": "回復預設",
                "matrix.all": "全部", "matrix.showing": "{n} / {total} 列",
                "matrix.sort_note": "常用規格在前；未公開規格排最後。",
                "matrix.spec_check": "規格待核",
                "matrix.close": "關閉"},
}


BILINGUAL_I18N = {
    "en": {
        "bilingual.toggle": "Show original",
        "bilingual.brand_note": "Name as registered in that market — not a translation.",
        "bilingual.source.official": "official",
        "bilingual.source.regulator": "regulator",
        "bilingual.source.pharmacopoeia": "pharmacopoeia",
        "bilingual.source.manual": "editorial",
        "nav.menu": "Menu",
        "matrix.brand_note": ("Each country/region column shows the locally registered trade "
                              "names — not translations."),
    },
    "es": {
        "bilingual.toggle": "Mostrar original",
        "bilingual.brand_note": "Nombre registrado en ese mercado — no es una traducción.",
        "bilingual.source.official": "oficial",
        "bilingual.source.regulator": "regulador",
        "bilingual.source.pharmacopoeia": "farmacopea",
        "bilingual.source.manual": "editorial",
        "nav.menu": "Menú",
        "matrix.brand_note": ("Cada columna de país/región muestra los nombres comerciales "
                              "registrados en ese mercado — no son traducciones."),
    },
    "zh": {
        "bilingual.toggle": "显示原文对照",
        "bilingual.brand_note": "该市场注册名，不是翻译。",
        "bilingual.source.official": "官方",
        "bilingual.source.regulator": "监管机构",
        "bilingual.source.pharmacopoeia": "药典",
        "bilingual.source.manual": "编辑整理",
        "nav.menu": "菜单",
        "matrix.brand_note": "各国家/地区列显示当地注册商品名，不是翻译；中英文名仅作对照。",
    },
    "zh-Hant": {
        "bilingual.toggle": "顯示原文對照",
        "bilingual.brand_note": "該市場註冊名，不是翻譯。",
        "bilingual.source.official": "官方",
        "bilingual.source.regulator": "監管機構",
        "bilingual.source.pharmacopoeia": "藥典",
        "bilingual.source.manual": "編輯整理",
        "nav.menu": "選單",
        "matrix.brand_note": "各國家/地區欄顯示當地註冊商品名，不是翻譯；中英文名僅作對照。",
        "about.analytics": (
            '<h2>訪問統計</h2><p class="sub">本站使用 '
            '<a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a> '
            '做匿名訪問統計：不使用 cookie、不記錄個人資料、不用於廣告；只統計頁面瀏覽、來源'
            '網站、國家/地區、瀏覽器與螢幕尺寸，以及站內搜尋詞和結果點擊，用於改進檢索品質。'
            '搜尋詞（含無結果的查詢）僅以聚合事件名發送——只含正規化查詢文字，不與帳號、IP 或'
            '裝置識別碼關聯。搜尋事件只在提交時送出（Enter、示例詞或自動完成選項），輸入過程中的'
            '中間態不會送出；僅附查詢長度與介面語言。'
            '詳見 <a href="https://www.goatcounter.com/privacy" target="_blank" '
            'rel="noopener">GoatCounter 隱私政策</a>。</p>'),
    },
}


# ── v0.7.x ATC 类别浏览 + 常见大类 ─────────────────────────────────────────
# ATC 码/层级是权威数据（WHO ATC/DDD Index 引用，不转载）；类别名是编辑/AI 译名，
# 页面明确标注「ATC 码为准」。DB 的 atc_name 是西语药名，不含类别名，故类别名内置。
ATC_I18N = {
    "en": {
        "nav.atc": "ATC & categories",
        "atc.browse_title": "Browse by ATC class",
        "atc.browse_intro": ("WHO ATC classes group medicines by organ/system and "
                             "pharmacological class. Start from a top-level group or a consumer "
                             "category; each page lists the active ingredients recorded here."),
        "atc.level": "ATC level", "atc.parent": "Parent class", "atc.children": "Child classes",
        "atc.ingredients": "Active ingredients in this class",
        "atc.count": "{n} active ingredients", "atc.more": "and {n} more",
        "atc.no_data": "No active ingredients recorded under this class yet.",
        "atc.unnamed": "Class name not reviewed yet — the ATC code is authoritative.",
        "atc.ai_note": ("Class and category names are editorial or AI-assisted translations; "
                        "only the ATC code and the WHO hierarchy are authoritative."),
        "atc.source_note": ("ATC codes and hierarchy reference the WHO Collaborating Centre for "
                            "Drug Statistics Methodology ATC/DDD Index (copyright WHOCC; the "
                            "index itself is not reproduced). Ingredient/strength facts come from "
                            "the regulator records listed on About."),
        "atc.show_all": "Show all {n} (currently showing {shown})",
        "atc.salt_label": "Salt form:",
        "atc.status_note": ("Status badges summarise the product records held for each "
                            "ingredient (active / discontinued / withdrawn / unknown), and the "
                            "market codes after each badge show where that status is recorded. "
                            "Only some registers publish a status column: CA, ES and MX do; AU "
                            "and HK have no status column and are recorded as unknown; CN, US, "
                            "GB, TW and SG records are on the register and marked active."),
        "atc.markets_hint": ("Each market now shows one aggregated status: a market counts "
                             "as on sale if it has any active record; individual record "
                             "statuses are shown in the details. The same market can also have "
                             "several registration records with different statuses, so each "
                             "market appears only once here; that is a record fact, not a "
                             "safety judgement."),
        "atc.ing_more": ("{n} more ingredients — the full list appears when the complete index "
                         "finishes loading."),
        # 2026-11-11 Batch 2：页级说明替代「每行一枚『无中文名』」的逐条噪音
        "atc.nolang_note": ("A missing name is marked in its row only when it is the "
                            "exception; when most names lack it, the list stays unmarked."),
        "atc.names_source_note": ("Class names are editorial translations or come from "
                                  "Wikipedia (CC BY-SA 4.0) / Wikidata (CC0); each ATC page lists "
                                  "the exact source, licence and link for every language. Only "
                                  "the ATC code and the WHO hierarchy are authoritative."),
        "atc.all_classes": "All ATC classes", "atc.search_link": "Search this class",
        "atc.view_class": "View this ATC class", "atc.categories_link": "Consumer categories",
        # v0.9.6 task-145b：L4 页「按剂型看跨市场明细」（事实表 JSON 懒加载；行=剂型/列=市场）
        "atc4.summary": "By dosage form, across markets",
        "atc4.loading": "Loading form detail…",
        "atc4.notice": ("An ATC class only groups medicines by similar pharmacology/chemistry — it "
                        "does not mean they are interchangeable. A different ingredient, dosage "
                        "form, release mechanism or strength is not interchangeable."),
        "atc4.scope": ("Only ingredients with a recorded ATC class are listed "
                       "(@@ATC_ALL@@ of @@ATC_ALL_N@@)."),
        "atc4.form_col": "Dosage form", "atc4.form_other": "other forms",
        "atc4.sort_note": ("Rows are alphabetical by dosage form and markets follow a fixed market "
                           "order; nothing here is ranked or recommended. Only ingredients with "
                           "product records have rows."),
        "atc4.empty": "No form-level product records for this class yet.",
        "atc4.error": "Could not load the form detail.",
        "cat.quick_title": "Browse by category", "cat.browse_title": "Common consumer categories",
        "cat.intro": ("Editorial topic collections: each category maps to ATC classes and active "
                      "ingredients. It is a way to browse, not evidence that the medicines are "
                      "equivalent."),
        "cat.disclaimer": "Theme collection — not a claim of equivalence or interchangeability.",
        "cat.count": "{n} active ingredients", "cat.related_atc": "Related ATC classes",
        "cat.no_data": "No active ingredients recorded for this category yet.",
        "cat.back": "All ATC classes & categories",
        "parse.category": "Category",
        "parse.category_note": ("Topic collection matched — not a name, and not a claim of "
                                "equivalence."),
        "parse.match.category": "Category / ATC class",
    },
    "es": {
        "nav.atc": "ATC y categorías",
        "atc.browse_title": "Explorar por clase ATC",
        "atc.browse_intro": ("Las clases ATC de la OMS agrupan medicamentos por órgano/sistema y "
                             "clase farmacológica. Empieza por un grupo superior o por una "
                             "categoría de consumidor; cada página lista los principios activos "
                             "registrados aquí."),
        "atc.level": "Nivel ATC", "atc.parent": "Clase superior",
        "atc.children": "Clases inferiores", "atc.ingredients": "Principios activos de esta clase",
        "atc.count": "{n} principios activos", "atc.more": "y {n} más",
        "atc.no_data": "Todavía no hay principios activos registrados en esta clase.",
        "atc.unnamed": "Nombre de clase sin revisar — el código ATC es la referencia.",
        "atc.ai_note": ("Los nombres de clase y categoría son traducciones editoriales o "
                        "asistidas por IA; solo el código ATC y la jerarquía de la OMS son "
                        "autoritativos."),
        "atc.source_note": ("Los códigos y la jerarquía ATC remiten al ATC/DDD Index del WHO "
                            "Collaborating Centre for Drug Statistics Methodology (copyright "
                            "WHOCC; no se reproduce el índice). Los datos de principios activos "
                            "proceden de los registros regulatorios listados en Acerca de."),
        "atc.show_all": "Mostrar los {n} (ahora se muestran {shown})",
        "atc.salt_label": "Forma sal:",
        "atc.status_note": ("Las insignias de estado resumen los registros de producto de cada "
                            "principio activo (activo / descatalogado / retirado / desconocido); "
                            "los códigos de mercado tras cada insignia indican dónde consta ese "
                            "estado. Solo algunos registros publican columna de estado: CA, ES y "
                            "MX sí; AU y HK no la tienen y figuran como desconocido; los "
                            "registros de CN, US, GB, TW y SG figuran como activos."),
        "atc.markets_hint": ("Cada mercado muestra ahora un estado agregado: cuenta como en "
                             "venta si tiene algún registro activo; los estados de cada registro "
                             "están en el detalle. Un mismo mercado también puede tener varios "
                             "registros con estados distintos, por eso cada mercado aparece una "
                             "sola vez aquí; es un hecho registral, no un juicio de seguridad."),
        "atc.ing_more": ("{n} principios activos más — la lista completa aparece cuando termine "
                         "de cargar el índice completo."),
        "atc.nolang_note": ("Un nombre ausente se marca en su fila solo cuando es la excepción; "
                            "si falta en la mayoría, la lista no se marca."),
        "atc.names_source_note": ("Los nombres de clase son traducciones editoriales o provienen "
                                  "de Wikipedia (CC BY-SA 4.0) / Wikidata (CC0); cada página ATC "
                                  "indica la fuente, la licencia y el enlace exactos de cada "
                                  "idioma. Solo el código ATC y la jerarquía de la OMS son "
                                  "autoritativos."),
        "atc.all_classes": "Todas las clases ATC", "atc.search_link": "Buscar en esta clase",
        "atc.view_class": "Ver esta clase ATC", "atc.categories_link": "Categorías de consumidor",
        # v0.9.6 task-145b
        "atc4.summary": "Por forma farmacéutica y mercado",
        "atc4.loading": "Cargando el detalle por forma…",
        "atc4.notice": ("Una clase ATC solo agrupa medicamentos de farmacología/química parecida — "
                        "no significa que sean intercambiables. Un principio activo, forma "
                        "farmacéutica, mecanismo de liberación o concentración distintos no son "
                        "intercambiables."),
        "atc4.scope": ("Solo se listan los principios activos con código ATC registrado "
                       "(@@ATC_ALL@@ de @@ATC_ALL_N@@)."),
        "atc4.form_col": "Forma farmacéutica", "atc4.form_other": "otras formas",
        "atc4.sort_note": ("Las filas van por orden alfabético de forma farmacéutica y los mercados "
                           "siguen un orden fijo; nada se clasifica ni se recomienda. Solo tienen "
                           "fila los principios activos con registros de producto."),
        "atc4.empty": "Todavía no hay registros de producto por forma en esta clase.",
        "atc4.error": "No se pudo cargar el detalle por forma.",
        "cat.quick_title": "Explorar por categoría",
        "cat.browse_title": "Categorías comunes de consumidor",
        "cat.intro": ("Colecciones temáticas editoriales: cada categoría se asigna a clases ATC "
                      "y principios activos. Es una forma de explorar, no una prueba de que los "
                      "medicamentos sean equivalentes."),
        "cat.disclaimer": "Colección temática — no implica equivalencia ni intercambiabilidad.",
        "cat.count": "{n} principios activos", "cat.related_atc": "Clases ATC relacionadas",
        "cat.no_data": "Todavía no hay principios activos registrados en esta categoría.",
        "cat.back": "Todas las clases y categorías", "parse.category": "Categoría",
        "parse.category_note": ("Colección temática — no es un nombre ni una afirmación de "
                                "equivalencia."),
        "parse.match.category": "Categoría / clase ATC",
    },
    "zh": {
        "nav.atc": "ATC / 大类", "atc.browse_title": "按 ATC 类别浏览",
        "atc.browse_intro": ("WHO ATC 按器官系统与药理类别给药物分类。可从一级大类或消费者大类开始；"
                             "每个页面列出本站收录的该类别活性成分。"),
        "atc.level": "ATC 层级", "atc.parent": "上级类目", "atc.children": "下级类目",
        "atc.ingredients": "该类别下的活性成分", "atc.count": "{n} 个活性成分",
        "atc.more": "另有 {n} 个", "atc.no_data": "该类别暂未收录活性成分。",
        "atc.unnamed": "类别名尚未校订——以 ATC 码为准。",
        "atc.ai_note": "类别名称为编辑或 AI 辅助译名；只有 ATC 码与 WHO 层级是权威依据。",
        "atc.source_note": ("ATC 码与层级引自 WHO Collaborating Centre for Drug Statistics "
                            "Methodology 的 ATC/DDD Index（版权归 WHOCC，本站不转载索引全文）。"
                            "成分/规格事实来自 About 页所列监管记录。"),
        "atc.show_all": "显示全部 {n} 个（当前显示前 {shown} 个）",
        "atc.salt_label": "盐型：",
        "atc.status_note": ("状态角标按每个成分的产品记录汇总（在售 / 已停售 / 已撤市 / 状态未知）；"
                            "每个角标后面的市场码表示该状态记录在哪些市场。只有部分市场的"
                            "登记库带状态列：CA、ES、MX 有；AU、HK 没有状态列，记为状态未知；"
                            "CN、US、GB、TW、SG 的记录按在售登记。"),
        "atc.markets_hint": ("每个市场只显示一个汇总状态：只要该市场有在售记录就算在售；"
                             "单条记录的状态见详情。同一市场也可能有多条注册记录、状态各不相同，"
                             "所以一个市场在这里只出现一次；这只是登记事实，不是安全性判断。"),
        "atc.ing_more": "另有 {n} 个成分，完整索引加载完成后显示。",
        "atc.nolang_note": "缺当前语言名属个别情况时才在该行标一次；多数都缺时整页不逐行标记。",
        "atc.names_source_note": ("类别名称为编辑译名，或来自 Wikipedia（CC BY-SA 4.0）/ "
                                  "Wikidata（CC0）；每个 ATC 页面逐语标注实际来源、许可与链接。"
                                  "只有 ATC 码与 WHO 层级是权威依据。"),
        "atc.all_classes": "全部 ATC 类别", "atc.search_link": "搜索该类别",
        "atc.view_class": "查看该 ATC 类别", "atc.categories_link": "消费者大类",
        # v0.9.6 task-145b
        "atc4.summary": "按剂型看跨市场明细",
        "atc4.loading": "正在加载剂型明细…",
        "atc4.notice": ("同一 ATC 类目只表示药理/化学分类相近，不代表可以互换；"
                        "成分、剂型、释放机制、规格不同不可互换。"),
        "atc4.scope": "仅含已收录 ATC 的成分（@@ATC_ALL@@/@@ATC_ALL_N@@）。",
        "atc4.form_col": "剂型", "atc4.form_other": "其他剂型",
        "atc4.sort_note": ("行按剂型字母序、市场按固定顺序排列，不排序推荐；"
                           "只有存在产品记录的成分才有行。"),
        "atc4.empty": "该类别暂无剂型级产品记录。",
        "atc4.error": "剂型明细加载失败。",
        "cat.quick_title": "按大类浏览", "cat.browse_title": "常见消费者大类",
        "cat.intro": ("编辑整理的主题合集：每个大类映射到 ATC 类别与活性成分。它只是浏览入口，"
                      "不代表这些药可以互相替代或等同。"),
        "cat.disclaimer": "主题合集——不代表同效或可互换。",
        "cat.count": "{n} 个活性成分", "cat.related_atc": "相关 ATC 类别",
        "cat.no_data": "该大类暂未收录活性成分。", "cat.back": "全部 ATC 类别与大类",
        "parse.category": "大类",
        "parse.category_note": "命中的是主题大类，不是药名；也不代表同效或可互换。",
        "parse.match.category": "大类 / ATC 类别",
    },
    "zh-Hant": {
        "nav.atc": "ATC / 大類", "atc.browse_title": "依 ATC 類別瀏覽",
        "atc.browse_intro": ("WHO ATC 依器官系統與藥理類別為藥物分類。可從一級大類或消費者大類開始；"
                             "每個頁面列出本站收錄的該類別有效成分。"),
        "atc.level": "ATC 層級", "atc.parent": "上級類目", "atc.children": "下級類目",
        "atc.ingredients": "該類別下的有效成分", "atc.count": "{n} 個有效成分",
        "atc.more": "另有 {n} 個", "atc.no_data": "該類別暫未收錄有效成分。",
        "atc.unnamed": "類別名尚未校訂——以 ATC 碼為準。",
        "atc.ai_note": "類別名稱為編輯或 AI 輔助譯名；只有 ATC 碼與 WHO 層級是權威依據。",
        "atc.source_note": ("ATC 碼與層級引自 WHO Collaborating Centre for Drug Statistics "
                            "Methodology 的 ATC/DDD Index（版權歸 WHOCC，本站不轉載索引全文）。"
                            "成分/規格事實來自 About 頁所列監管紀錄。"),
        "atc.show_all": "顯示全部 {n} 個（目前顯示前 {shown} 個）",
        "atc.salt_label": "鹽型：",
        "atc.status_note": ("狀態角標依每個成分的產品紀錄彙總（販售中 / 已停售 / 已下市 / 狀態未知）；"
                            "每個角標後面的市場碼表示該狀態記錄在哪些市場。只有部分市場的"
                            "登記庫帶狀態列：CA、ES、MX 有；AU、HK 沒有狀態列，記為狀態未知；"
                            "CN、US、GB、TW、SG 的紀錄按販售中登記。"),
        "atc.markets_hint": ("每個市場只顯示一個彙總狀態：只要該市場有販售中記錄就算販售中；"
                             "單條記錄的狀態見詳情。同一市場也可能有多條註冊記錄、狀態各不相同，"
                             "所以一個市場在這裡只出現一次；這只是登記事實，不是安全性判斷。"),
        "atc.ing_more": "另有 {n} 個成分，完整索引載入完成後顯示。",
        "atc.nolang_note": "缺中文名或英文名的條目會在該列標一次，不按鹽型逐個重複。",
        "atc.names_source_note": ("類別名稱為編輯譯名，或來自 Wikipedia（CC BY-SA 4.0）/ "
                                  "Wikidata（CC0）；每個 ATC 頁面逐語標註實際來源、授權與連結。"
                                  "只有 ATC 碼與 WHO 層級是權威依據。"),
        "atc.all_classes": "全部 ATC 類別", "atc.search_link": "搜尋該類別",
        "atc.view_class": "查看該 ATC 類別", "atc.categories_link": "消費者大類",
        # v0.9.6 task-145b
        "atc4.summary": "依劑型看跨市場明細",
        "atc4.loading": "正在載入劑型明細…",
        "atc4.notice": ("同一 ATC 類目只表示藥理/化學分類相近，不代表可以互換；"
                        "成分、劑型、釋放機制、規格不同不可互換。"),
        "atc4.scope": "僅含已收錄 ATC 的成分（@@ATC_ALL@@/@@ATC_ALL_N@@）。",
        "atc4.form_col": "劑型", "atc4.form_other": "其他劑型",
        "atc4.sort_note": ("列依劑型字母序、市場依固定順序排列，不排序推薦；"
                           "只有具產品紀錄的成分才有列。"),
        "atc4.empty": "該類別暫無劑型級產品紀錄。",
        "atc4.error": "劑型明細載入失敗。",
        "cat.quick_title": "依大類瀏覽", "cat.browse_title": "常見消費者大類",
        "cat.intro": ("編輯整理的主題合集：每個大類對應 ATC 類別與有效成分。它只是瀏覽入口，"
                      "不代表這些藥可以互相替代或等同。"),
        "cat.disclaimer": "主題合集——不代表同效或可互換。",
        "cat.count": "{n} 個有效成分", "cat.related_atc": "相關 ATC 類別",
        "cat.no_data": "該大類暫未收錄有效成分。", "cat.back": "全部 ATC 類別與大類",
        "parse.category": "大類",
        "parse.category_note": "命中的是主題大類，不是藥名；也不代表同效或可互換。",
        "parse.match.category": "大類 / ATC 類別",
    },
}

# WHO ATC level-1 groups（四语编辑译名；代码权威）
ATC_L1_I18N = {
    "en": {"A": "Alimentary tract and metabolism", "B": "Blood and blood forming organs",
           "C": "Cardiovascular system", "D": "Dermatologicals",
           "G": "Genito-urinary system and sex hormones", "H": "Systemic hormonal preparations",
           "J": "Antiinfectives for systemic use",
           "L": "Antineoplastic and immunomodulating agents", "M": "Musculo-skeletal system",
           "N": "Nervous system", "P": "Antiparasitic products", "R": "Respiratory system",
           "S": "Sensory organs", "V": "Various"},
    "es": {"A": "Tracto alimentario y metabolismo", "B": "Sangre y órganos hematopoyéticos",
           "C": "Sistema cardiovascular", "D": "Dermatológicos",
           "G": "Sistema genitourinario y hormonas sexuales",
           "H": "Preparados hormonales sistémicos", "J": "Antiinfecciosos de uso sistémico",
           "L": "Antineoplásicos e inmunomoduladores", "M": "Sistema musculoesquelético",
           "N": "Sistema nervioso", "P": "Productos antiparasitarios", "R": "Sistema respiratorio",
           "S": "Órganos de los sentidos", "V": "Varios"},
    "zh": {"A": "消化系统及代谢", "B": "血液及造血器官", "C": "心血管系统", "D": "皮肤科用药",
           "G": "泌尿生殖系统及性激素", "H": "全身用激素制剂", "J": "全身用抗感染药",
           "L": "抗肿瘤及免疫调节药", "M": "肌肉骨骼系统", "N": "神经系统", "P": "抗寄生虫药",
           "R": "呼吸系统", "S": "感觉器官", "V": "其他"},
    "zh-Hant": {"A": "消化系統及代謝", "B": "血液及造血器官", "C": "心血管系統", "D": "皮膚科用藥",
                "G": "泌尿生殖系統及性激素", "H": "全身用激素製劑", "J": "全身用抗感染藥",
                "L": "抗腫瘤及免疫調節藥", "M": "肌肉骨骼系統", "N": "神經系統", "P": "抗寄生蟲藥",
                "R": "呼吸系統", "S": "感覺器官", "V": "其他"},
}

# L2–L4 常见类别名（编辑/AI 译名；未收录的类目页以 ATC 码为标题并标注待校订）
ATC_CLASS_I18N = {
    "en": {"A02": "Drugs for acid related disorders", "A08": "Antiobesity preparations",
           "A10": "Drugs used in diabetes", "A10BA": "Biguanides",
           "B01": "Antithrombotic agents", "B01AA": "Vitamin K antagonists",
           "C07": "Beta blocking agents", "C07A": "Beta blocking agents",
           "C07AB": "Selective beta-1 blocking agents", "C08": "Calcium channel blockers",
           "C09": "Agents acting on the renin-angiotensin system", "C10": "Lipid modifying agents",
           "C10AA": "HMG-CoA reductase inhibitors (statins)", "D": "Dermatologicals",
           "G04": "Urologicals", "H02": "Corticosteroids for systemic use",
           "J01": "Antibacterials for systemic use", "J05": "Antivirals for systemic use",
           "M01": "Antiinflammatory and antirheumatic products", "N02": "Analgesics",
           "N02BE": "Anilides", "N06A": "Antidepressants",
           "R03": "Drugs for obstructive airway diseases", "R05": "Cough and cold preparations",
           "R06": "Antihistamines for systemic use"},
    "es": {"A02": "Fármacos para trastornos ácido-relacionados",
           "A08": "Preparados antiobesidad", "A10": "Fármacos usados en diabetes",
           "A10BA": "Biguanidas", "B01": "Agentes antitrombóticos",
           "B01AA": "Antagonistas de la vitamina K", "C07": "Betabloqueantes",
           "C07A": "Betabloqueantes", "C07AB": "Betabloqueantes selectivos beta-1",
           "C08": "Bloqueantes de los canales de calcio",
           "C09": "Agentes del sistema renina-angiotensina",
           "C10": "Fármacos modificadores de lípidos",
           "C10AA": "Inhibidores de la HMG-CoA reductasa (estatinas)", "D": "Dermatológicos",
           "G04": "Urológicos", "H02": "Corticosteroides de uso sistémico",
           "J01": "Antibacterianos de uso sistémico", "J05": "Antivirales de uso sistémico",
           "M01": "Antiinflamatorios y antirreumáticos", "N02": "Analgésicos",
           "N02BE": "Anilidas", "N06A": "Antidepresivos",
           "R03": "Fármacos para enfermedades obstructivas de las vías respiratorias",
           "R05": "Preparados para la tos y el resfriado",
           "R06": "Antihistamínicos de uso sistémico"},
    "zh": {"A02": "酸相关疾病用药", "A08": "减肥/抗肥胖药", "A10": "糖尿病用药",
           "A10BA": "双胍类", "B01": "抗血栓药", "B01AA": "维生素 K 拮抗剂",
           "C07": "β受体阻滞剂", "C07A": "β受体阻滞剂", "C07AB": "选择性 β1 受体阻滞剂",
           "C08": "钙通道阻滞剂", "C09": "肾素-血管紧张素系统药物", "C10": "调脂药",
           "C10AA": "HMG-CoA 还原酶抑制剂（他汀类）", "D": "皮肤科用药", "G04": "泌尿系统用药",
           "H02": "全身用糖皮质激素", "J01": "全身用抗菌药", "J05": "全身用抗病毒药",
           "M01": "抗炎抗风湿药", "N02": "镇痛药", "N02BE": "苯胺类", "N06A": "抗抑郁药",
           "R03": "阻塞性气道疾病用药", "R05": "咳嗽与感冒用药", "R06": "全身用抗组胺药"},
    "zh-Hant": {"A02": "酸相關疾病用藥", "A08": "減肥/抗肥胖藥", "A10": "糖尿病用藥",
                "A10BA": "雙胍類", "B01": "抗血栓藥", "B01AA": "維生素 K 拮抗劑",
                "C07": "β受體阻滯劑", "C07A": "β受體阻滯劑", "C07AB": "選擇性 β1 受體阻滯劑",
                "C08": "鈣通道阻滯劑", "C09": "腎素-血管緊張素系統藥物", "C10": "調脂藥",
                "C10AA": "HMG-CoA 還原酶抑制劑（他汀類）", "D": "皮膚科用藥", "G04": "泌尿系統用藥",
                "H02": "全身用糖皮質激素", "J01": "全身用抗菌藥", "J05": "全身用抗病毒藥",
                "M01": "抗炎抗風濕藥", "N02": "鎮痛藥", "N02BE": "苯胺類", "N06A": "抗抑鬱藥",
                "R03": "阻塞性氣道疾病用藥", "R05": "咳嗽與感冒用藥", "R06": "全身用抗組胺藥"},
}

# ── v0.8.5：ATC 类名 v2（构建期只读 data/atc_class_names_v2.csv）────────────
# 逐语 name/source/url/license；缺本语时回退链 本语 → en → zh → fallback_text。
# 数据来源：Wikipedia (CC BY-SA 4.0) / Wikidata (CC0) / 编辑译名；来源与许可逐条标注。
ATC_V2_LANGS = {"en": "en", "es": "es", "zh": "zh", "zh-Hant": "zh_hant"}
ATC_SOURCE_LABELS = {
    "en": {"wikipedia": "Wikipedia", "wikipedia-zh-converted": "Wikipedia (zh)",
           "wikidata": "Wikidata", "editorial": "Editorial translation"},
    "es": {"wikipedia": "Wikipedia", "wikipedia-zh-converted": "Wikipedia (zh)",
           "wikidata": "Wikidata", "editorial": "Traducción editorial"},
    "zh": {"wikipedia": "维基百科", "wikipedia-zh-converted": "维基百科（中文转繁体）",
           "wikidata": "维基数据", "editorial": "编辑译名"},
    "zh-Hant": {"wikipedia": "維基百科", "wikipedia-zh-converted": "維基百科（中文轉繁體）",
                "wikidata": "維基數據", "editorial": "編輯譯名"},
}
ATC_EDITORIAL_LICENSE = {
    "en": "editorial (project)", "es": "editorial (proyecto)",
    "zh": "编辑整理（项目）", "zh-Hant": "編輯整理（專案）",
}
ATC_FALLBACK_LABEL = {
    "en": "fallback name", "es": "nombre de respaldo",
    "zh": "回退名", "zh-Hant": "回退名",
}
ATC_SRC_PREFIX = {
    "en": "Source: ", "es": "Fuente: ", "zh": "来源：", "zh-Hant": "來源：",
}


def _load_atc_class_v2() -> tuple[dict[str, dict[str, dict[str, str]]], dict[str, str]]:
    """读 ATC 类名 v2 CSV → ({code: {lang: {name, source, url, license}}}, {code: fallback})。"""
    path = ROOT / "data" / "atc_class_names_v2.csv"
    names: dict[str, dict[str, dict[str, str]]] = {}
    fallback: dict[str, str] = {}
    if not path.exists():
        print(f"atc names v2: 缺少 {path}，回退内置 ATC_CLASS_I18N", flush=True)
        return names, fallback
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("code") or "").strip()
            if not code:
                continue
            fallback[code] = (row.get("fallback_text") or "").strip()
            entry: dict[str, dict[str, str]] = {}
            for lang, col in ATC_V2_LANGS.items():
                entry[lang] = {
                    "name": (row.get(f"name_{col}") or "").strip(),
                    "source": (row.get(f"source_{col}") or "").strip(),
                    "url": (row.get(f"url_{col}") or "").strip(),
                    "license": (row.get(f"license_{col}") or "").strip(),
                }
            names[code] = entry
    named = sum(1 for v in names.values() if v["en"]["name"])
    print(f"atc names v2: {len(names):,} codes ({named:,} with en name, "
          f"{sum(1 for v in names.values() if v['zh']['name']):,} zh, "
          f"{sum(1 for v in names.values() if v['es']['name']):,} es)", flush=True)
    return names, fallback


ATC_CLASS_V2, ATC_CLASS_FALLBACK = _load_atc_class_v2()

CONSUMER_CATEGORIES = [
    {"id": "antihypertensives", "prefixes": ["C02", "C03", "C07", "C08", "C09"],
     "labels": {"en": "Blood-pressure medicines", "es": "Medicamentos para la presión arterial",
                "zh": "降压药", "zh-Hant": "降血壓藥"},
     "desc": {"en": "ATC C02/C03/C07/C08/C09 — antihypertensives and related classes.",
              "es": "ATC C02/C03/C07/C08/C09 — antihipertensivos y clases relacionadas.",
              "zh": "ATC C02/C03/C07/C08/C09——降压及相关类别。",
              "zh-Hant": "ATC C02/C03/C07/C08/C09——降壓及相關類別。"}},
    {"id": "antibiotics", "prefixes": ["J01"],
     "labels": {"en": "Antibiotics", "es": "Antibióticos", "zh": "抗生素", "zh-Hant": "抗生素"},
     "desc": {"en": "ATC J01 — systemic antibacterials.",
              "es": "ATC J01 — antibacterianos sistémicos.", "zh": "ATC J01——全身用抗菌药。",
              "zh-Hant": "ATC J01——全身用抗菌藥。"}},
    {"id": "diabetes", "prefixes": ["A10"],
     "labels": {"en": "Diabetes medicines", "es": "Medicamentos para la diabetes",
                "zh": "降糖药", "zh-Hant": "降血糖藥"},
     "desc": {"en": "ATC A10 — drugs used in diabetes.",
              "es": "ATC A10 — fármacos para diabetes.", "zh": "ATC A10——糖尿病用药。",
              "zh-Hant": "ATC A10——糖尿病用藥。"}},
    {"id": "weight-loss", "prefixes": ["A08", "A10BJ", "A10BX16"],
     "labels": {"en": "Weight-loss medicines", "es": "Medicamentos para perder peso",
                "zh": "减肥药", "zh-Hant": "減重藥"},
     "desc": {"en": ("ATC A08 + A10BJ (GLP-1) + A10BX16 (tirzepatide) — antiobesity preparations "
                     "and GLP-1 weight-loss medicines. GLP-1s also belong to the diabetes class "
                     "A10; this is a browse-by-indication collection, not a claim of equivalence."),
              "es": ("ATC A08 + A10BJ (GLP-1) + A10BX16 (tirzepatida) — preparados antiobesidad "
                     "y medicamentos GLP-1 para perder peso. Los GLP-1 también pertenecen a la "
                     "clase de diabetes A10; es una colección por indicación, no una afirmación "
                     "de equivalencia."),
              "zh": ("ATC A08 + A10BJ（GLP-1）+ A10BX16（tirzepatide）——传统抗肥胖药与 GLP-1 "
                     "减重药。GLP-1 同属降糖大类 A10；这里按减重适应症浏览，不代表同效或可互换。"),
              "zh-Hant": ("ATC A08 + A10BJ（GLP-1）+ A10BX16（tirzepatide）——傳統抗肥胖藥與 "
                          "GLP-1 減重藥。GLP-1 同屬降糖大類 A10；這裡按減重適應症瀏覽，"
                          "不代表同效或可互換。")},
     "notes": {"en": ("GLP-1 medicines such as semaglutide, tirzepatide, liraglutide, "
                      "dulaglutide and exenatide are also listed under Diabetes medicines (A10). "
                      "The same ingredient appears in both categories by indication — not as an "
                      "interchangeable alternative."),
               "es": ("Los medicamentos GLP-1 (semaglutida, tirzepatida, liraglutida, dulaglutida, "
                      "exenatida) también figuran en Medicamentos para la diabetes (A10). El mismo "
                      "principio aparece en ambas categorías por indicación, no como alternativa "
                      "intercambiable."),
               "zh": ("司美格鲁肽（semaglutide）、替尔泊肽（tirzepatide）、利拉鲁肽（liraglutide）、"
                      "度拉糖肽（dulaglutide）、艾塞那肽（exenatide）等 GLP-1 也列在「降糖药"
                      "（A10）」大类。同一成分因适应症不同出现在两个大类，不代表可以互换。"),
               "zh-Hant": ("司美格魯肽（semaglutide）、替爾泊肽（tirzepatide）、利拉魯肽"
                           "（liraglutide）、度拉糖肽（dulaglutide）、艾塞那肽（exenatide）等 "
                           "GLP-1 也列在「降血糖藥（A10）」大類。同一成分因適應症不同出現在"
                           "兩個大類，不代表可以互換。")}},
    {"id": "cold-medicine", "prefixes": ["R05", "N02BE"],
     "labels": {"en": "Cold & cough medicines", "es": "Medicamentos para resfriado y tos",
                "zh": "感冒咳嗽药", "zh-Hant": "感冒咳嗽藥"},
     "desc": {"en": ("ATC R05 + N02BE — cough/cold preparations and anilides (paracetamol). "
                     "Consumer “cold medicine” is broader than one ATC class; systemic "
                     "antihistamines (R06) are listed under Allergy medicines."),
              "es": ("ATC R05 + N02BE — preparados para la tos/resfriado y anilidas "
                     "(paracetamol). El término popular es más amplio que una clase ATC; los "
                     "antihistamínicos sistémicos (R06) están en Medicamentos para la alergia."),
              "zh": ("ATC R05 + N02BE——咳嗽/感冒制剂与苯胺类（对乙酰氨基酚）。消费者说的"
                     "「感冒药」比单一 ATC 类别更宽；全身用抗组胺药（R06）归入抗过敏药。"),
              "zh-Hant": ("ATC R05 + N02BE——咳嗽/感冒製劑與苯胺類（對乙醯氨基酚）。消費者說的"
                          "「感冒藥」比單一 ATC 類別更寬；全身用抗組胺藥（R06）歸入抗過敏藥。")},
     "notes": {"en": ("Cross-over: some combination cold medicines contain R06 antihistamines. "
                      "This site lists all R06 under Allergy medicines, so the two categories "
                      "overlap — see the Allergy medicines page."),
               "es": ("Solapamiento: algunos antigripales combinados contienen antihistamínicos "
                      "R06. Este sitio incluye todo R06 en Medicamentos para la alergia; las dos "
                      "categorías se solapan."),
               "zh": ("有交叉：部分复方感冒药含 R06 抗组胺成分；本站把全部 R06 归入「抗过敏药」，"
                      "两个大类互有重叠，可互相对照。"),
               "zh-Hant": ("有交叉：部分複方感冒藥含 R06 抗組胺成分；本站把全部 R06 歸入"
                           "「抗過敏藥」，兩個大類互有重疊，可互相對照。")}},
    {"id": "analgesics", "prefixes": ["N02", "M01A"],
     "labels": {"en": "Pain & fever relief", "es": "Analgésicos y antitérmicos",
                "zh": "退烧止痛", "zh-Hant": "退燒止痛"},
     "desc": {"en": "ATC N02/M01A — analgesics and antipyretics.",
              "es": "ATC N02/M01A — analgésicos y antipiréticos.",
              "zh": "ATC N02/M01A——镇痛与退热药。", "zh-Hant": "ATC N02/M01A——鎮痛與退熱藥。"}},
    {"id": "allergy", "prefixes": ["R06"],
     "labels": {"en": "Allergy medicines", "es": "Medicamentos para la alergia",
                "zh": "抗过敏药", "zh-Hant": "抗過敏藥"},
     "desc": {"en": ("ATC R06 — systemic antihistamines. Some also appear in combination cold "
                     "medicines; see Cold & cough medicines."),
              "es": ("ATC R06 — antihistamínicos sistémicos. Algunos también aparecen en "
                     "antigripales combinados; ver Medicamentos para resfriado y tos."),
              "zh": "ATC R06——全身用抗组胺药。部分也出现在复方感冒药中；可与「感冒咳嗽药」对照。",
              "zh-Hant": "ATC R06——全身用抗組胺藥。部分也出現在複方感冒藥中；可與「感冒咳嗽藥」對照。"},
     "notes": {"en": ("Cross-over: R06 antihistamines may be components of combination cold "
                      "medicines. All R06 are listed here; Cold & cough medicines only covers "
                      "R05 + N02BE, so the two categories overlap."),
               "es": ("Solapamiento: los antihistamínicos R06 pueden formar parte de antigripales "
                      "combinados. Todo R06 está aquí; Medicamentos para resfriado y tos solo "
                      "cubre R05 + N02BE, por lo que las categorías se solapan."),
               "zh": ("有交叉：R06 抗组胺药可能是复方感冒药的成分。全部 R06 列在本大类；"
                      "「感冒咳嗽药」只含 R05 + N02BE，因此两个大类有重叠。"),
               "zh-Hant": ("有交叉：R06 抗組胺藥可能是複方感冒藥的成分。全部 R06 列在本大類；"
                           "「感冒咳嗽藥」只含 R05 + N02BE，因此兩個大類有重疊。")}},
    {"id": "acid-related", "prefixes": ["A02"],
     "labels": {"en": "Stomach / acid medicines", "es": "Medicamentos gástricos / de acidez",
                "zh": "胃药", "zh-Hant": "胃藥"},
     "desc": {"en": "ATC A02 — acid-related disorder drugs (antacids, PPIs, H2 blockers).",
              "es": "ATC A02 — antiácidos, IBP, antihistamínicos H2.",
              "zh": "ATC A02——抗酸、质子泵抑制剂、H2 受体拮抗剂等。",
              "zh-Hant": "ATC A02——抗酸、質子泵抑制劑、H2 受體拮抗劑等。"}},
    {"id": "anticoagulants", "prefixes": ["B01"],
     "labels": {"en": "Blood thinners / antithrombotics",
                "es": "Anticoagulantes / antitrombóticos", "zh": "抗凝药",
                "zh-Hant": "抗凝血藥"},
     "desc": {"en": "ATC B01 — antithrombotic agents. Not all are interchangeable.",
              "es": "ATC B01 — antitrombóticos; no todos son intercambiables.",
              "zh": "ATC B01——抗血栓药；彼此不都可互换。",
              "zh-Hant": "ATC B01——抗血栓藥；彼此不都可互換。"}},
    {"id": "statins", "prefixes": ["C10AA"], "exclude": ["cerivastatin"],
     "labels": {"en": "Statins", "es": "Estatinas", "zh": "他汀类", "zh-Hant": "他汀類"},
     "desc": {"en": ("ATC C10AA — HMG-CoA reductase inhibitors. Cerivastatin (withdrawn 2001) "
                     "is excluded from the member list; status badges show current product "
                     "records."),
              "es": ("ATC C10AA — inhibidores de la HMG-CoA reductasa. La cerivastatina "
                     "(retirada en 2001) se excluye de la lista; las insignias muestran el "
                     "estado de los registros."),
              "zh": ("ATC C10AA——HMG-CoA 还原酶抑制剂。已撤市的 cerivastatin（西立伐他汀，"
                     "2001 年撤市）从成员列表中排除；状态角标显示产品记录状态。"),
              "zh-Hant": ("ATC C10AA——HMG-CoA 還原酶抑制劑。已撤市的 cerivastatin"
                          "（西立伐他汀，2001 年撤市）從成員列表中排除；狀態角標顯示產品紀錄狀態。")},
     "notes": {"en": ("Cerivastatin (C10AA06) was withdrawn in 2001; it is excluded here rather "
                      "than listed as a current option."),
               "es": ("La cerivastatina (C10AA06) se retiró en 2001; se excluye de esta lista."),
               "zh": "cerivastatin（C10AA06）已于 2001 年撤市，本大类不将其列为现售选项。",
               "zh-Hant": "cerivastatin（C10AA06）已於 2001 年撤市，本大類不將其列為現售選項。"}},
    {"id": "beta-blockers", "prefixes": ["C07"],
     "labels": {"en": "Beta blockers", "es": "Betabloqueantes", "zh": "β受体阻滞剂",
                "zh-Hant": "β受體阻斷劑"},
     "desc": {"en": "ATC C07 — beta blocking agents.", "es": "ATC C07 — betabloqueantes.",
              "zh": "ATC C07——β受体阻滞剂。", "zh-Hant": "ATC C07——β受體阻滯劑。"}},
    {"id": "antidepressants", "prefixes": ["N06A"],
     "labels": {"en": "Antidepressants", "es": "Antidepresivos", "zh": "抗抑郁药",
                "zh-Hant": "抗憂鬱藥"},
     "desc": {"en": "ATC N06A — antidepressants.", "es": "ATC N06A — antidepresivos.",
              "zh": "ATC N06A——抗抑郁药。", "zh-Hant": "ATC N06A——抗抑鬱藥。"}},
    {"id": "asthma-copd", "prefixes": ["R03"],
     "labels": {"en": "Asthma / COPD inhalers", "es": "Inhaladores para asma / EPOC",
                "zh": "哮喘·慢阻肺吸入剂", "zh-Hant": "哮喘·慢阻肺吸入劑"},
     "desc": {"en": "ATC R03 — drugs for obstructive airway diseases.",
              "es": "ATC R03 — enfermedades obstructivas de las vías respiratorias.",
              "zh": "ATC R03——阻塞性气道疾病用药。", "zh-Hant": "ATC R03——阻塞性氣道疾病用藥。"}},
    {"id": "corticosteroids", "prefixes": ["H02"],
     "labels": {"en": "Steroid hormones", "es": "Hormonas esteroideas", "zh": "激素类",
                "zh-Hant": "荷爾蒙類"},
     "desc": {"en": "ATC H02 — corticosteroids for systemic use.",
              "es": "ATC H02 — corticosteroides sistémicos.", "zh": "ATC H02——全身用糖皮质激素。",
              "zh-Hant": "ATC H02——全身用糖皮質激素。"}},
    {"id": "antivirals", "prefixes": ["J05"],
     "labels": {"en": "Antivirals", "es": "Antivirales", "zh": "抗病毒药", "zh-Hant": "抗病毒藥"},
     "desc": {"en": "ATC J05 — antivirals for systemic use.",
              "es": "ATC J05 — antivirales sistémicos.", "zh": "ATC J05——全身用抗病毒药。",
              "zh-Hant": "ATC J05——全身用抗病毒藥。"}},
    {"id": "dermatologicals", "prefixes": ["D"],
     "labels": {"en": "Skin medicines", "es": "Medicamentos dermatológicos", "zh": "皮肤外用药",
                "zh-Hant": "皮膚外用藥"},
     "desc": {"en": "ATC D — dermatologicals (broad class).",
              "es": "ATC D — dermatológicos (clase amplia).", "zh": "ATC D——皮肤科用药（大类）。",
              "zh-Hant": "ATC D——皮膚科用藥（大類）。"}},
]


def build_glossary() -> None:
    """v0.6.4 B10：/glossary.html 术语表（四语，客户端按语言切块 + /es//zh//zh-hant/ 静态副本）。"""
    blocks = []
    for lang in ("en", "es", "zh", "zh-Hant"):
        D = I18N.get(lang) or I18N["en"]
        rows = "".join(
            f'<dt>{esc(D.get("glossary.t." + term, term))}</dt>'
            f'<dd>{esc(D.get("glossary.d." + term, ""))}</dd>'
            for term in GLOSSARY_TERMS)
        blocks.append(f'<div class="lang-block" data-lang-block="{lang}">'
                      f'<dl class="glossary">{rows}</dl></div>')
    body = (f'<h1 data-i18n="glossary.title">{esc(I18N["en"]["glossary.title"])}</h1>'
            f'<div data-i18n-html="glossary.intro">{I18N["en"]["glossary.intro"]}</div>'
            f'<h2 data-i18n="glossary.h2">Terms &amp; codes</h2>'
            + "".join(blocks)
            + f'<div class="notice" data-i18n="glossary.note">'
              f'{esc(I18N["en"]["glossary.note"])}</div>')
    html = page("Glossary", body, meta_key="glossary", alternates=True,
                canonical_rel="glossary.html", alt_rel="glossary.html", nav_coverage=True)
    _write_with_copies("glossary.html", html, "glossary")


# ── v0.7.x：ATC 类目页 / 大类页 / landing / 客户端 categories.json ──────────
ATC_MEMBER_CAP = 80
ATC_LEN_LEVEL = {1: 1, 3: 2, 4: 3, 5: 4}


def _atc_v2_entry(code: str, lang: str) -> dict[str, str] | None:
    """按 本语 → en → zh 回退取 v2 类名记录（source/license/url 跟随实际语种）。"""
    rec = ATC_CLASS_V2.get(code)
    if not rec:
        return None
    for src_lang in (lang, "en", "zh"):
        entry = rec.get(src_lang)
        if entry and entry.get("name"):
            return {**entry, "lang": src_lang, "fallback": "1" if src_lang != lang else ""}
    return None


def _atc_display_name(lang: str, code: str) -> str:
    entry = _atc_v2_entry(code, lang)
    if entry:
        return entry["name"]
    if code in ATC_CLASS_V2:
        return ATC_CLASS_FALLBACK.get(code, "")
    # CSV 缺行（或文件缺失）→ 旧内置表最后兜底
    if len(code) == 1:
        return ATC_L1_I18N.get(lang, {}).get(code, "")
    return ATC_CLASS_I18N.get(lang, {}).get(code, "")


def _atc_names(code: str) -> dict[str, str]:
    return {lang: _atc_display_name(lang, code) for lang in ("en", "es", "zh", "zh-Hant")}


def _atc_all_fallback(code: str) -> bool:
    return bool(code in ATC_CLASS_V2) and not any(
        _atc_v2_entry(code, lang) for lang in ("en", "es", "zh", "zh-Hant"))


def _atc_source_html(code: str, lang: str) -> str:
    """逐语来源小字：Wikipedia / Wikidata + 许可 + 链接；回退时标注。

    2026-11-11（v0.11.1 2b）：`source == "editorial"` 的条目不渲染可见来源行。
    「编辑译名 · 编辑整理（项目）」是同一件事说两遍，而且「（项目）」是内部措辞；
    编辑译名是本项目自己的产出，不需要给用户署名（没有第三方许可义务）。
    **第三方来源一律保留**：Wikipedia 的 CC BY-SA 4.0 要求署名 + 许可链接，
    Wikidata 的 CC0 保留来源也有价值 —— 这条是许可红线，不要为了让卡片变干净删掉。
    """
    entry = _atc_v2_entry(code, lang)
    if not entry:
        return ""
    source = entry.get("source") or ""
    if source == "editorial":
        return ""
    label = ATC_SOURCE_LABELS.get(lang, {}).get(source, source)
    url = entry.get("url") or ""
    label_html = (f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)}</a>'
                  if url else esc(label))
    license_text = entry.get("license") or ""
    if "editorial" in license_text.lower():
        license_text = ATC_EDITORIAL_LICENSE.get(lang, license_text)
    fallback = (f' · {esc(ATC_FALLBACK_LABEL.get(lang, ""))} ({esc(entry.get("lang", ""))})'
                if entry.get("fallback") else "")
    return f"{label_html} · {esc(license_text)}{fallback}"


def _lang_blocks(parts: dict[str, str]) -> str:
    """四语行内块；空值不输出（无值时不显示该语言）。"""
    return " ".join(
        f'<span class="lang-block" data-lang-block="{lang}" data-lang-inline="1">{html}</span>'
        for lang, html in parts.items() if html)


def _lang_block_text(key: str, **fmt: object) -> str:
    """同一句 UI 文案的四语块（数字占位在构建期替换）。"""
    out = {}
    for lang in ("en", "es", "zh", "zh-Hant"):
        text = (I18N.get(lang) or {}).get(key) or I18N["en"].get(key, "")
        for k, v in fmt.items():
            text = text.replace("{" + k + "}", str(v))
        out[lang] = esc(text)
    return _lang_blocks(out)


def _atc_source_line(code: str) -> str:
    """ATC 类目页标题下的逐语来源/许可/链接小字。"""
    parts = {lang: _atc_source_html(code, lang) for lang in ("en", "es", "zh", "zh-Hant")}
    if not any(parts.values()):
        return ""
    parts = {lang: ATC_SRC_PREFIX.get(lang, "") + html
             for lang, html in parts.items() if html}
    return f'<p class="sub atc-src-line">{_lang_blocks(parts)}</p>'


def _lang_inline(labels: dict[str, str]) -> str:
    """行内语言块（i18n.js 对 data-lang-inline=1 用 inline 显示）。"""
    return _lang_blocks({lang: esc(text) for lang, text in labels.items() if text})


def _atc_groups(db: sqlite3.Connection) -> dict[int, dict[str, list[dict]]]:
    rows = [dict(r) for r in db.execute(
        "SELECT substance_id, inn_en, inn_zh, atc FROM substance "
        "WHERE atc IS NOT NULL AND atc <> '' ORDER BY atc, inn_en")]
    groups: dict[int, dict[str, list[dict]]] = {1: {}, 3: {}, 4: {}, 5: {}}
    for r in rows:
        for ln in (1, 3, 4, 5):
            if len(r["atc"]) >= ln:
                groups[ln].setdefault(r["atc"][:ln], []).append(r)
    return groups


def _sub_name_spans(en: str, zh: str, sid: str) -> str:
    """v0.8.2 task-120：成分名紧凑多语标记（data-n-*；bilingual.js 按当前语言渲染，
    中文优先；无中文名 → 英文 + 暂无中文名）。比四个 lang-block 更省体积。"""
    entry = (BILINGUAL_TRANS.get("sub", {}) or {}).get(sid) or {}
    es = ((entry.get("es") or {}).get("n") or "")
    zhh = ((entry.get("zh-Hant") or {}).get("n") or "")
    # v0.9.4 name_lang：base 名语言（仅 H1/source 行使用；列表按原文 CJK 判断，省索引体积）
    en_txt = en or sid or ""
    return (f'<span class="nm" data-n-en="{esc(en_txt)}" data-n-zh="{esc(zh or "")}" '
            f'data-n-zhh="{esc(zhh)}" data-n-es="{esc(es)}">{esc(en_txt)}</span>')


def _sub_status_map(db: sqlite3.Connection,
                    base_of: dict[str, str]) -> dict[str, dict[str, dict[str, int]]]:
    """base substance_id → {status: {country: 产品记录数}}。

    v0.10.2：状态角标必须写清是哪些市场——同一个成分可能在一个市场在售、在另一个市场
    已撤市，一行四色其实是「几本登记簿各说各话」（reports/atc-status-aggregation-20261110.md）。
    计数只用来判断有无，不进 HTML（同一产品同时挂 base 与盐型时会重复计）。
    """
    out: dict[str, dict[str, dict[str, int]]] = {}
    for sid, status, country, n in db.execute(
            """SELECT v.substance_id, p.status, COALESCE(p.country, p.region) AS mk,
                      COUNT(DISTINCT p.product_id)
               FROM product p
               JOIN product_component pc ON pc.product_id = p.product_id
               JOIN variant v ON v.variant_id = pc.variant_id
               WHERE p.status IS NOT NULL AND p.status <> ''
                 AND COALESCE(p.country, p.region) IS NOT NULL
               GROUP BY v.substance_id, p.status, COALESCE(p.country, p.region)"""):
        per = out.setdefault(base_of.get(sid, sid), {}).setdefault(status, {})
        per[country] = per.get(country, 0) + int(n)
    return out


def _member_context(db: sqlite3.Connection):
    """ATC/大类页共用：盐型 base 映射 + 名称 + 产品状态聚合。"""
    base_of, sub_names = _sub_base_map(db)
    return base_of, sub_names, _sub_status_map(db, base_of)


def _collapse_members(subs: list[dict], base_of: dict[str, str],
                      sub_names: dict[str, tuple[str, str]],
                      status_by_base: dict[str, dict[str, dict[str, int]]],
                      drug_sids: set[str]) -> list[dict]:
    """同一 ATC 码/大类下，按 base 成分归并盐型与同名重复，一个 base 一行。"""
    grouped: dict[str, list[dict]] = {}
    for r in subs:
        base = base_of.get(r["substance_id"], r["substance_id"])
        grouped.setdefault(base, []).append(r)
    items: list[dict] = []
    for base, rows in grouped.items():
        base_en, base_zh = sub_names.get(base, ("", ""))
        if not base_en:
            base_en = rows[0].get("inn_en") or ""
        if not base_zh:
            base_zh = rows[0].get("inn_zh") or ""
        salts = sorted((r for r in rows if r["substance_id"] != base),
                       key=lambda r: (r.get("inn_en") or "").lower())
        codes = sorted({(r.get("atc") or "").strip() for r in rows
                        if (r.get("atc") or "").strip()})
        sid = base if base in drug_sids else next(
            (r["substance_id"] for r in rows if r["substance_id"] in drug_sids), base)
        items.append({"base": base, "en": base_en, "zh": base_zh, "sid": sid,
                      "codes": codes, "salts": salts,
                      "statuses": status_by_base.get(base, {})})
    return items


# 2026-11-11 Batch 2：状态排列改成「先看在售、异常在后」。
# released 是预留位：现库 product.status 只有 active / discontinued / withdrawn / unknown
# （db/schema.sql 的 CHECK），真出现新状态时按本表定位、定位不到就排在 unknown 之前。
ATC_STATUS_ORDER = ("active", "released", "discontinued", "withdrawn", "unknown")


def _status_summary_html(statuses: dict[str, dict[str, int]]) -> str:
    """ATC 卡片的状态行：**按国家聚合、每国只出现一次**（task-41）。

    - 优先级 active > released > discontinued > withdrawn > unknown：只要该市场有在售记录，
      这个国家就归「在售」，同国的已停售/已撤市/未知不再并列；没有在售才显示其最强状态。
    - 输出 `<details class="st-details">`：折叠态一行只显示第一组状态 + 前 5 个市场码 +
      「另有 N 个」；展开列全部「状态 → 市场码」。无 JS 可点、键盘可达，不丢信息。
    - 单条产品记录的状态仍在「详情」表的状态列（`detPanelHTML` 未改）。
    """
    if not statuses:
        return ""
    rank = {s: i for i, s in enumerate(ATC_STATUS_ORDER)}
    best: dict[str, str] = {}
    for st, per in statuses.items():
        r = rank.get(st, len(ATC_STATUS_ORDER) - 1)
        for c in (per or {}):
            cur = best.get(c)
            if cur is None or r < rank.get(cur, len(ATC_STATUS_ORDER) - 1):
                best[c] = st
    def _sort_codes(cs):
        return sorted(cs, key=lambda c: (COUNTRY_PRIORITY.index(c)
                                         if c in COUNTRY_PRIORITY else 99, c))
    groups: list[tuple[str, list[str]]] = []
    for st in ATC_STATUS_ORDER:
        cs = _sort_codes(c for c, s in best.items() if s == st)
        if cs:
            groups.append((st, cs))
    leftover = _sort_codes(c for c, s in best.items() if s not in rank)
    if leftover:
        groups.append(("unknown", leftover))
    if not groups:
        return ""
    def _word(st: str) -> str:
        return (f'<span class="st-word st-{esc(st)}" data-i18n="drug.status.{esc(st)}">'
                f'{esc(I18N["en"].get("drug.status." + st, st))}</span>')
    first_st, first_cs = groups[0]
    shown = first_cs[:5]
    total_codes = sum(len(cs) for _st, cs in groups)
    remaining = total_codes - len(shown) + max(0, len(groups) - 1)
    summary = (_word(first_st) + ' <span class="atc-mk">' + esc(" ".join(shown)) + '</span>')
    if remaining > 0:
        summary += ' · ' + _lang_block_text("atc.more", n=remaining)
    body = " · ".join(
        f'<span class="st-line">{_word(st)} '
        f'<span class="atc-mk">{esc(" ".join(cs))}</span></span>'
        for st, cs in groups)
    return (f'<details class="st-details"><summary><span class="ln">{summary}</span>'
            f'</summary><div class="st-list">{body}</div></details>')


def _status_badges_html(statuses: dict[str, dict[str, int]]) -> str:
    """状态行：`在售 CN US GB · 已撤市 ES MX`（状态词一次、市场码空格分隔）。

    - **先后次序按 ATC_STATUS_ORDER**：原来 withdrawn 排第一，用户第一眼看到的是「已撤市」，
      而真正想知道的是「哪里还有」。现在 active 先、异常后。
    - **不折 `+N`**：实测不截断时 390 px 下最长一行也只占 2 行；折叠后的完整清单只能塞进
      `title`，触屏用户拿不到 = 真丢信息（reports/atc-status-aggregation-20261110.md §2.5）。
    - **同一国家可以出现在多组里**：现库有 3,599 个「成分×市场」格子本来就同时有
      >1 种状态，按国家去重会伪造出一个不存在的「唯一状态」。
    - **不写 title 条数**（触屏拿不到；条数在成分页已有）。
    - 排序用现成的 COUNTRY_PRIORITY：市场码不是词，服务端固定序保证构建确定性；
      不用客户端 MORDER（那是按界面语言重排的）。
    - `·` 只用来分隔不同状态组，市场码之间是空格（2026-11-11 Batch 2）。
    """
    groups: list[str] = []
    for st in sorted(statuses, key=lambda s: (
            ATC_STATUS_ORDER.index(s) if s in ATC_STATUS_ORDER
            else len(ATC_STATUS_ORDER) - 1, s)):
        per = statuses.get(st) or {}
        if not per:
            continue
        markets = " ".join(sorted(
            per, key=lambda c: (COUNTRY_PRIORITY.index(c) if c in COUNTRY_PRIORITY
                                else len(COUNTRY_PRIORITY), c)))
        groups.append(
            f'<span class="atc-st-grp">'
            f'<span class="atc-st st-{esc(st)}" data-i18n="drug.status.{esc(st)}">'
            f'{esc(I18N["en"].get("drug.status." + st, st))}</span>'
            f'<span class="atc-mk">{esc(markets)}</span></span>')
    if not groups:
        return ""
    sep = '<span class="atc-st-sep" aria-hidden="true">·</span>'
    return '<span class="atc-strip">' + sep.join(groups) + '</span>'


CJK_NAME_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _missing_name_langs(items: list[dict]) -> list[str]:
    """构建期算「本页缺当前语言名的比例 ≥50%」的语言，写进 `data-nolang-mute`。

    2026-11-11（v0.11.1 2b）：中草药页几乎每个成分都没有英文名，逐行挂
    「No English name recorded」是把常态当异常（用户截图：「满屏都是」）。规则改成按页统计：

      missing_ratio = 该页缺「当前语言名」的成员数 / 成员总数
      ≥ 0.5 → 整页不再逐行挂徽章，只在页级 `atc.nolang_note` 说一句
      < 0.5 → 保留逐行徽章（这才是例外，标出来有价值）

    判定只依赖服务端数据（前端不猜）：en/es 页面看的是「英文名是不是拉丁文」，
    zh/zh-Hant 页面看的是「有没有中文名」。比例在 `_atc_members_html` 里用它，
    同时把结论原样写进 `<ul data-nolang-mute="…">`，`markAtcRowGaps()` 只照抄。
    """
    total = len(items)
    if not total:
        return []
    # en/es：`.nm` 的首选文本就是英文名；落在 CJK 区间说明「没有英文名」
    no_latin = sum(1 for it in items
                   if CJK_NAME_RE.search(it.get("en") or ""))
    # zh/zh-Hant：没有中文名（只有英文原文）
    no_zh = sum(1 for it in items if not (it.get("zh") or "").strip())
    mute: list[str] = []
    if no_latin / total >= 0.5:
        mute.extend(("en", "es"))
    if no_zh / total >= 0.5:
        mute.extend(("zh", "zh-Hant"))
    return mute


def _member_usage_key(r: dict) -> tuple:
    """成分列表的排序键：**常用到不常用**（用户 2026-11-11 明确要求）。

    原来的键是「有中文名的排前 + 按名字字母序」，于是只在一个市场收录的中草药
    （三嗪芦丁 / 丹参川芎嗪）排在最前，阿奇霉素反而靠后。新键四级，全部从
    `statuses`（= `_sub_status_map` 的 {status: {market: 记录数}}）现算，不改 SQL：

      ① 覆盖市场数 desc（`len({c for per in statuses.values() for c in per})`）
      ② 记录数 desc（`sum(sum(per.values()) for per in statuses.values())`）
      ③ 有中文名优先（只是 tie-break，方便中文用户）
      ④ base 成分 id 升序 —— 保证构建确定性，不用名字排最后一级

    没有状态记录的成分（markets=0）自然落到页尾，正合「未收录排后面」。
    """
    per_all = r.get("statuses") or {}
    markets = len({c for per in per_all.values() for c in per})
    records = sum(sum(per.values()) for per in per_all.values())
    return (-markets, -records, 0 if (r.get("zh") or "").strip() else 1,
            str(r.get("base") or r.get("sid") or ""))


def _atc_members_html(items: list[dict], cap: int = ATC_MEMBER_CAP,
                      drug_sids: set[str] | None = None) -> str:
    """成员列表：base 名 + ATC 码 + 盐型附注 + 状态行；超过 cap 用 <details> 展开（无 JS 也能点开）。

    2026-11-11 Batch 2（用户报「极大的可读性问题」）：每条固定成 3 个块级子元素
    （`.atc-nm` = 名 + 码、`.salt-row`、`.atc-strip` = 状态 + 市场），CSS 用
    `grid-template-rows:auto auto auto; align-content:start` 保证同一行相邻条目顶端对齐。
    状态词由 `_status_badges_html()` 渲染（在售先、异常后，市场码紧随）。
    """
    # 2026-11-11：排序换成「常用到不常用」（覆盖市场数 → 记录数 → 有中文名 → base id）
    ordered = sorted(items, key=_member_usage_key)
    lis: list[str] = []
    for it in ordered:
        name_html = _sub_name_spans(it.get("en", ""), it.get("zh", ""), it["sid"])
        if drug_sids is None or it["sid"] in drug_sids:
            label = f'<a href="../drug/{esc(it["sid"])}.html">{name_html}</a>'
        else:
            # 有 ATC 但没有 product 的成分没有 drug 页 → 纯文本，避免 ../drug/ 404
            label = f'<span class="brand-plain">{name_html}</span>'
        codes = "".join(f'<code>{esc(c)}</code>' for c in it["codes"])
        codes = f'<span class="atc-codes">{codes}</span>' if codes else ""
        full_name = it.get("en") or it.get("zh") or it["sid"]
        name_title = f' title="{esc(full_name)}"'
        salt = ""
        if it["salts"]:
            # 2026-11-13 task-39/40（用户截图）：盐型行固定 1 行 —— 摘要只显示第一个盐名
            # （+「另有 N 个」），用原生 <details> 展开列全部盐名；不藏信息、键盘可达。
            # 1 个盐型也走 details（摘要就是「盐型：Name」），保证卡片 3 行等高。
            salt_names = [
                _sub_name_spans(r.get("inn_en") or "", r.get("inn_zh") or "",
                                r["substance_id"]) for r in it["salts"]]
            salt_label = (f'<span class="salt-k" data-i18n="atc.salt_label">'
                          f'{esc(I18N["en"].get("atc.salt_label", "Salt form:"))}</span>')
            salt_more = (f' · {_lang_block_text("atc.more", n=len(salt_names) - 1)}'
                         if len(salt_names) > 1 else '')
            salt = (f'<details class="salt-details"><summary><span class="ln">'
                    f'{salt_label} {salt_names[0]}{salt_more}</span></summary>'
                    f'<div class="salt-list">{" · ".join(salt_names)}</div></details>')
        # 2026-11-13 task-40/41：状态行固定 1 行，按国家聚合（每国只出现一次；
        # 有在售记录就算在售），摘要「在售 US GB CA… · 另有 N 个」，展开列全部。
        strip = _status_summary_html(it["statuses"])
        lis.append(f'<li><span class="atc-nm"{name_title}>{label}{codes}</span>{salt}{strip}</li>')
    head = "".join(lis[:cap])
    rest = "".join(lis[cap:])
    # 2026-11-11 2b：整页缺名比例 ≥50% 的语言写进 data-nolang-mute，逐行徽章由
    # markAtcRowGaps() 照抄这里的结果（构建期算，前端不猜）。
    mute = _missing_name_langs(items)
    ul_open = '<ul class="sub atclist atcmembers"'
    if mute:
        ul_open += f' data-nolang-mute="{esc(" ".join(mute))}"'
    ul_open += ">"
    if rest:
        summary = _lang_block_text("atc.show_all", n=len(lis), shown=cap)
        return (f'{ul_open}{head}</ul>'
                f'<details class="atcdetails"><summary>{summary}</summary>'
                f'{ul_open}{rest}</ul></details>')
    return f'{ul_open}{head}</ul>'


# ── v0.9.6 task-145b：ATC4 页「按剂型看跨市场明细」────────────────────────────
# 事实表由 db/atc4_forms.py 预生成（ATC4 × 成分 × 剂型 × 市场 的产品数），构建时压缩
# 写出到 dist/data/idx/atc4-forms.json，只在用户展开折叠区时由客户端 fetch（懒加载）。
# 体积预算见 reports/task146-size-budget-20261031.md：798 个 L4 页每页只加折叠区与
# notice（实测 +608 B/页），明细表不进静态 HTML（28,378 行 × 多市场会直接超 900 MiB）。
ATC4_FORMS_SRC = ROOT / "data" / "sources" / "atc4_forms_20261031.json"
ATC4_FORMS_REL = "data/idx/atc4-forms.json"
# 构建期只读一次：payload（原样写 dist）+ {ATC4: 行数}（决定该页是否渲染折叠区）
ATC4_PAYLOAD: dict = {}
ATC4_CLASS_ROWS: dict[str, int] = {}

ATC4_JS = r"""(function(){
// v0.9.6 task-145b：ATC4 页「按剂型看跨市场明细」——展开才 fetch 事实表（懒加载）。
// 行=剂型（字母序）、列=市场（固定市场序），值=产品数；不排序推荐、不做替代判断。
var el = document.querySelector('details[data-atc4]');
if(!el || !window.fetch) return;
el.hidden = false;                       // 无 JS 时保持 hidden：折叠区不出现，页面其余照常
var code = el.getAttribute('data-atc4');
var body = el.querySelector('.atc4-body');
var prefix = window.DSH_PREFIX || '';
var url = prefix + 'data/idx/atc4-forms.json?v=__BUILD_V__';
var ORDER = ['US','GB','CA','AU','SG','CN','ES','MX','TW','HK','EU'];
function T(k, d){
  var t = window.T;
  if(!t) return d;
  var v = t(k);
  return (v === k || v === undefined) ? d : v;
}
function esc(x){
  return String(x).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
  });
}
function formLabel(f){
  if(f === 'other') return T('atc4.form_other', 'other forms');
  return T('form.' + f, f);
}
function render(rows){
  var markets = [], forms = {}, seen = {}, i;
  for(i = 0; i < rows.length; i++){
    var f = rows[i][2], c = rows[i][3];
    if(!seen[c]){ seen[c] = 1; markets.push(c); }
    if(!forms[f]) forms[f] = {};
    forms[f][c] = (forms[f][c] || 0) + rows[i][4];
  }
  markets.sort(function(a, b){
    var ia = ORDER.indexOf(a), ib = ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  var list = Object.keys(forms).sort();
  var h = ['<table class="atc4t"><thead><tr><th scope="col">'
           + esc(T('atc4.form_col', 'Dosage form')) + '</th>'];
  for(i = 0; i < markets.length; i++){
    h.push('<th scope="col" data-country="' + esc(markets[i]) + '">'
           + esc(markets[i]) + '</th>');
  }
  h.push('</tr></thead><tbody>');
  for(var r = 0; r < list.length; r++){
    h.push('<tr><th scope="row">' + esc(formLabel(list[r])) + '</th>');
    for(var m = 0; m < markets.length; m++){
      var n = forms[list[r]][markets[m]];
      h.push(n ? '<td>' + n + '</td>' : '<td class="z">·</td>');
    }
    h.push('</tr>');
  }
  h.push('</tbody></table><p class="sub atc4note">'
         + esc(T('atc4.sort_note', '')) + '</p>');
  body.innerHTML = h.join('');
}
var cache = null;
function show(){
  if(!cache){
    // 加载提示由 JS 写（静态 HTML 只留折叠入口，省 798 页的每页体积）。
    body.innerHTML = '<p class="sub">' + esc(T('atc4.loading', '…')) + '</p>';
    cache = fetch(url, {credentials: 'same-origin'}).then(function(r){
      if(!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  cache.then(function(d){
    var all = (d && d.rows) || [], rows = [];
    for(var i = 0; i < all.length; i++){
      if(all[i][0] === code) rows.push(all[i]);
    }
    if(rows.length) render(rows);
    else body.innerHTML = '<p class="sub">' + esc(T('atc4.empty', '')) + '</p>';
  }).catch(function(){
    body.innerHTML = '<p class="sub">' + esc(T('atc4.error', '')) + '</p>';
  });
}
el.addEventListener('toggle', function(){ if(el.open) show(); });
// v0.11.4 task-63：同一页内切界面语言（i18n.js 的 apply()）后重绘已展开的明细表，
// 否则表头与剂型列还停在上一种语言（数据已缓存在 cache，不会重复 fetch）。
if(window.__DSH_APPLY_HOOKS){
  window.__DSH_APPLY_HOOKS.push(function(){
    if(el.open && cache){ cache.then(function(d){
      var all = (d && d.rows) || [], rows = [];
      for(var i = 0; i < all.length; i++){ if(all[i][0] === code) rows.push(all[i]); }
      if(rows.length) render(rows);
    }).catch(function(){}); }
  });
}
})();
"""


def build_atc4_forms_json() -> int:
    """读入 ATC4 事实表快照 → 压缩写出 dist/data/idx/atc4-forms.json（客户端懒加载）。

    只复制事实（不重算、不排序推荐）；缺快照时跳过并打印，ATC 页自动不渲染折叠区。
    """
    global ATC4_PAYLOAD, ATC4_CLASS_ROWS
    if not ATC4_FORMS_SRC.exists():
        print(f"  atc4-forms.json 跳过：缺 {ATC4_FORMS_SRC.relative_to(ROOT)}", flush=True)
        return 0
    payload = json.loads(ATC4_FORMS_SRC.read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    counts: dict[str, int] = {}
    for r in rows:
        counts[r[0]] = counts.get(r[0], 0) + 1
    ATC4_PAYLOAD, ATC4_CLASS_ROWS = payload, counts
    (OUT / "data" / "idx").mkdir(parents=True, exist_ok=True)
    path = OUT / ATC4_FORMS_REL
    path.write_bytes(json.dumps(payload, ensure_ascii=False,
                                separators=(",", ":")).encode("utf-8"))
    print(f"  atc4-forms.json {path.stat().st_size / 1e6:.2f} MB ({len(rows):,} 行 / "
          f"{len(counts):,} 个 ATC4 类；展开时才加载)", flush=True)
    return path.stat().st_size


def _atc4_forms_html(code: str) -> str:
    """L4 类目页的折叠区 + 不可互换 notice + 覆盖边界（四语走 i18n 字典，静态仅 en 兜底）。"""
    if code not in ATC4_CLASS_ROWS:
        return ""
    T = I18N["en"]
    return (f'<details class="atc4forms" data-atc4="{esc(code)}" hidden>'
            f'<summary data-i18n="atc4.summary">{esc(T["atc4.summary"])}</summary>'
            f'<div class="atc4-body"></div></details>'
            f'<div class="notice" data-i18n="atc4.notice">{esc(T["atc4.notice"])}</div>'
            f'<p class="sub atc4-scope" data-i18n="atc4.scope">{esc(T["atc4.scope"])}</p>')


def build_atc_pages(db: sqlite3.Connection) -> int:
    """L1–L4 ATC 类目页 /atc/<prefix>.html（父/子类目可逐级浏览）。"""
    groups = _atc_groups(db)
    drug_sids = {p.stem for p in (OUT / "drug").glob("*.html")}
    base_of, sub_names, status_by_base = _member_context(db)
    (OUT / "atc").mkdir(parents=True, exist_ok=True)
    T = I18N["en"]
    made = 0
    for ln in (1, 3, 4, 5):
        child_ln = {1: 3, 3: 4, 4: 5}.get(ln)
        for code, subs in sorted(groups[ln].items()):
            level = ATC_LEN_LEVEL[len(code)]
            parent = {3: code[:1], 4: code[:3], 5: code[:4]}.get(len(code), "")
            names = _atc_names(code)
            fallback_only = _atc_all_fallback(code) or not any(names.values())
            name_html = _lang_inline(names)
            title_html = (name_html if fallback_only
                          else f'<code>{esc(code)}</code> {name_html}')
            unnamed = (f'<p class="sub" data-i18n="atc.unnamed">{esc(T["atc.unnamed"])}</p>'
                       if fallback_only else "")
            crumbs = (f'<a href="../atc.html" data-i18n="atc.all_classes">'
                      f'{esc(T["atc.all_classes"])}</a>')
            if parent:
                crumbs += f' · <a href="../atc/{esc(parent)}.html"><code>{esc(parent)}</code></a>'
            children = ""
            if child_ln:
                kids = sorted(groups[child_ln].items())
                kids = [(c, s) for c, s in kids if c.startswith(code)]
                if kids:
                    lis = []
                    for c, s in kids:
                        n_kid = len(_collapse_members(
                            s, base_of, sub_names, status_by_base, drug_sids))
                        lis.append(f'<li><a href="../atc/{esc(c)}.html"><code>{esc(c)}</code> '
                                   f'{_lang_inline(_atc_names(c))}</a> '
                                   f'<span class="meta">({n_kid})</span></li>')
                    children = (f'<h2 data-i18n="atc.children">{esc(T["atc.children"])}</h2>'
                                f'<ul class="sub atclist">{"".join(lis)}</ul>')
            members = _collapse_members(subs, base_of, sub_names, status_by_base, drug_sids)
            search_href = f'../index.html?q={esc(code)}'
            # task-145b：只有 L4（5 位 ATC 码，798 页）挂「按剂型看跨市场明细」折叠区；
            # 明细走客户端懒加载，静态 HTML 只留折叠入口 + 不可互换 notice + 覆盖边界。
            atc4_html = _atc4_forms_html(code) if level == 4 else ""
            body = f"""<p class="sub">{crumbs}</p>
<h1>{title_html} <span class="tag">L{level}</span></h1>
{unnamed}
{_atc_source_line(code)}
<p class="sub"><span data-i18n="atc.level">{esc(T["atc.level"])}</span> L{level} ·
<a class="linkbtn" href="{search_href}" data-i18n="atc.search_link">{esc(T["atc.search_link"])}</a>
· <a href="../atc.html" data-i18n="atc.categories_link">{esc(T["atc.categories_link"])}</a></p>
{children}
<h2 data-i18n="atc.ingredients">{esc(T["atc.ingredients"])}</h2>
<p class="sub atc-count">{_lang_block_text("atc.count", n=len(members))}</p>
<p class="sub atc-mk-hint" data-i18n="atc.markets_hint">{esc(T["atc.markets_hint"])}</p>
<p class="sub atc-nolang-note" data-i18n="atc.nolang_note">{esc(T["atc.nolang_note"])}</p>
{_atc_members_html(members, drug_sids=drug_sids)}
{atc4_html}
{_atc_notes_html(T)}"""
            atc_ld = json.dumps({
                "@context": "https://schema.org", "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "ATC",
                     "item": SITE_URL + "atc.html"},
                    {"@type": "ListItem", "position": 2, "name": code,
                     "item": f"{SITE_URL}atc/{code}.html"},
                ],
            }, ensure_ascii=False)
            # task-145b：折叠区的懒加载脚本只挂在 L4 页（约 57 B/页）。
            head_js = f'<script type="application/ld+json">{atc_ld}</script>'
            if atc4_html:
                head_js += '<script defer src="../assets/atc4.js"></script>'
            (OUT / "atc" / f"{code}.html").write_text(
                page(f"ATC {code}", body, "../", canonical_rel=f"atc/{code}.html",
                     head_js=head_js),
                encoding="utf-8")
            _assert_once(body, NAMES_SOURCE_MARK, f"atc/{code}.html")
            made += 1
    return made


def _cat_related_html(prefixes: list[str],
                      groups: dict[int, dict[str, list[dict]]]) -> str:
    """大类页「相关 ATC 类别」：v2 四语类名 + 逐语来源；无类目页的 L5 码给搜索链接。"""
    lis = []
    for code in prefixes:
        exists = code in groups.get(len(code), {})
        parts: dict[str, str] = {}
        for lang in ("en", "es", "zh", "zh-Hant"):
            display = _atc_display_name(lang, code) or f"ATC {code}"
            inner = f'<code>{esc(code)}</code> {esc(display)}'
            if exists:
                inner = f'<a href="../atc/{esc(code)}.html">{inner}</a>'
            else:
                inner = (f'<span class="brand-plain">{inner}</span> '
                         f'<a class="linkbtn" href="../index.html?q={esc(code)}" '
                         f'data-i18n="atc.search_link">Search this class</a>')
            src = _atc_source_html(code, lang)
            if src:
                inner += f' <span class="atc-src">{src}</span>'
            parts[lang] = inner
        lis.append(f'<li>{_lang_blocks(parts)}</li>')
    return f'<ul class="sub atclist">{"".join(lis)}</ul>'


def build_category_pages(db: sqlite3.Connection) -> int:
    """常见消费者大类 /cat/<id>.html（主题合集，非药效等同）。"""
    rows = [dict(r) for r in db.execute(
        "SELECT substance_id, inn_en, inn_zh, atc FROM substance "
        "WHERE atc IS NOT NULL AND atc <> '' ORDER BY atc, inn_en")]
    groups = _atc_groups(db)
    drug_sids = {p.stem for p in (OUT / "drug").glob("*.html")}
    base_of, sub_names, status_by_base = _member_context(db)
    (OUT / "cat").mkdir(parents=True, exist_ok=True)
    T = I18N["en"]
    made = 0
    for cat in CONSUMER_CATEGORIES:
        exclude = {_norm_name(x) for x in cat.get("exclude", [])}
        subs = []
        for r in rows:
            if not any(r["atc"].startswith(p) for p in cat["prefixes"]):
                continue
            base = base_of.get(r["substance_id"], r["substance_id"])
            base_en = sub_names.get(base, ("", ""))[0]
            if _norm_name(r.get("inn_en") or "") in exclude or _norm_name(base_en) in exclude:
                continue
            subs.append(r)
        members = _collapse_members(subs, base_of, sub_names, status_by_base, drug_sids)
        related = _cat_related_html(cat["prefixes"], groups)
        title_labels = cat["labels"]
        display_title = _lang_inline(title_labels)
        desc_blocks = "".join(
            f'<div class="lang-block" data-lang-block="{lang}">{esc(cat["desc"][lang])}</div>'
            for lang in ("en", "es", "zh", "zh-Hant"))
        notes = ""
        if cat.get("notes"):
            badge = ('<span class="st-badge st-withdrawn" data-i18n="drug.status.withdrawn">'
                     '已撤市</span> ' if cat.get("exclude") else "")
            note_blocks = "".join(
                f'<div class="lang-block" data-lang-block="{lang}">{badge}'
                f'{esc(cat["notes"][lang])}</div>'
                for lang in ("en", "es", "zh", "zh-Hant"))
            notes = f'<div class="notice cat-note">{note_blocks}</div>'
        # T13 / D4（用户评审 §2）：187 个成分需要页内搜索 + 子类筛选。
        # 子类 = 成员 ATC 码的前 4 位（N02B / M01A …），按命中成员数排序，最多 12 个。
        # v0.11.7 复审：**子类 chip 收进一个折叠浮层**（默认收起），搜索框与计数并成一行 ——
        # 分类页首屏条目 10.5 → 9（−14.3%，超 −5% 线）就是这两行（99px）占的位。
        sub_prefix: dict[str, int] = {}
        for _it in members:
            for _code in (_it.get("codes") or ()):
                _k = str(_code)[:4].upper()
                if _k:
                    sub_prefix[_k] = sub_prefix.get(_k, 0) + 1
        cf_chips = [f'<button type="button" class="lf-chip on" data-sub-filter="" '
                    f'data-i18n="lf.all">{esc(T.get("lf.all", "All"))}</button>']
        for _k in sorted(sub_prefix, key=lambda x: (-sub_prefix[x], x))[:12]:
            cf_chips.append(f'<button type="button" class="lf-chip" data-sub-filter="{esc(_k)}">'
                            f'<code>{esc(_k)}</code> <span class="n">{sub_prefix[_k]}</span></button>')
        cat_finder = (
            f'<div class="catfinder" id="catfinder">'
            f'<div class="cf-row"><input type="search" id="catq" class="cf-input" autocomplete="off" '
            f'aria-label="{esc(T.get("cat.search_ph", "Search an ingredient in this category"))}" '
            f'placeholder="{esc(T.get("cat.search_ph", "Search an ingredient in this category"))}">'
            f'<details class="cf-sub"><summary data-i18n="cat.subcat">'
            f'{esc(T.get("cat.subcat", "Subclass"))}</summary>'
            f'<div class="cf-chips">' + "".join(cf_chips) + '</div></details>'
            f'<p class="cf-status" id="cf-status" role="status" aria-live="polite"></p></div>'
            f'<p class="lf-none" id="cf-none" hidden data-i18n="cat.search_none">'
            f'{esc(T.get("cat.search_none", "No ingredient matches."))}</p></div>')
        # T13 / D5（用户评审 §2）+ v0.11.7 复审：**所有**说明都进同一个帮助折叠区
        # （市场口径 / 缺名规则 / 类名来源与许可 / 状态汇总 / AI 译名 / 数据来源），
        # 正文里不再留 `.notice`（复审量到 main .notice ×4）；红线句 `cat.disclaimer` 仍常显。
        cat_help = ('<details class="cat-help"><summary data-i18n="cat.help">'
                    + esc(T.get("cat.help", "How to read this list")) + '</summary>'
                    + f'<p class="sub atc-mk-hint" data-i18n="atc.markets_hint">'
                    + esc(T["atc.markets_hint"]) + '</p>'
                    + f'<p class="sub atc-nolang-note" data-i18n="atc.nolang_note">'
                    + esc(T["atc.nolang_note"]) + '</p>'
                    + f'<p class="sub atc-note" data-i18n="atc.names_source_note">'
                    + esc(T["atc.names_source_note"]) + '</p>'
                    + f'<p class="sub atc-note" data-i18n="atc.status_note">'
                    + esc(T["atc.status_note"]) + '</p>'
                    + f'<p class="sub atc-note" data-i18n="atc.ai_note">'
                    + esc(T["atc.ai_note"]) + '</p>'
                    + f'<p class="sub atc-note" data-i18n="atc.source_note">'
                    + esc(T["atc.source_note"]) + '</p></details>')
        body = f"""<p class="sub"><a href="../atc.html" data-i18n="cat.back">{esc(T["cat.back"])}</a></p>
<h1>{display_title}</h1>
<p class="sub cat-en">{esc(cat["labels"]["en"])}</p>
{desc_blocks}
{notes}
<p class="sub" data-i18n="cat.disclaimer">{esc(T["cat.disclaimer"])}</p>
<h2 data-i18n="cat.related_atc">{esc(T["cat.related_atc"])}</h2>
{related}
<h2 data-i18n="atc.ingredients">{esc(T["atc.ingredients"])}</h2>
<p class="sub atc-count">{_lang_block_text("atc.count", n=len(members))}</p>
{cat_finder}
{cat_help}
{_atc_members_html(members, cap=80, drug_sids=drug_sids)}"""
        (OUT / "cat" / f'{cat["id"]}.html').write_text(
            page(cat["labels"]["en"], body, "../", canonical_rel=f'cat/{cat["id"]}.html'),
            encoding="utf-8")
        _assert_once(body, NAMES_SOURCE_MARK, f'cat/{cat["id"]}.html')
        made += 1
    return made



def _atc_notes_html(T: dict, *, with_status: bool = True) -> str:
    """v0.10.0 P1-1：ATC/大类页把 3–4 条 notice 合成 1 条主提示 + details 折叠。"""
    main = (f'<div class="notice" data-i18n="atc.names_source_note">'
            f'{esc(T["atc.names_source_note"])}</div>')
    extra = []
    if with_status:
        extra.append(f'<div class="notice" data-i18n="atc.status_note">{esc(T["atc.status_note"])}</div>')
    extra.append(f'<div class="notice" data-i18n="atc.ai_note">{esc(T["atc.ai_note"])}</div>')
    extra.append(f'<div class="notice" data-i18n="atc.source_note">{esc(T["atc.source_note"])}</div>')
    return (main + '<details class="atc-notes"><summary data-i18n="atc.more_notes">'
            'Notes &amp; licences</summary>' + "".join(extra) + '</details>')


NAMES_SOURCE_MARK = 'data-i18n="atc.names_source_note"'


def _assert_once(html: str, marker: str, where: str) -> None:
    """同一页里同一段说明只许出现一次（v0.11.1 2b：/atc.html 曾把许可说明画了两遍）。

    `/atc.html` 原来在 `_atc_notes_html()` 之外又手写了一行
    `data-i18n="atc.names_source_note"`，而 `_atc_notes_html()` 第一句就是同一条，
    于是同一段「类名来源/许可」在页面上出现两次。这里在写文件前按标记计数，
    谁再手工加一遍构建就直接报出来（也顺便覆盖 atc/<code>.html 与 cat/*.html）。
    """
    n = html.count(marker)
    if n > 1:
        raise SystemExit(f"[build] {where} 里 {marker!r} 出现 {n} 次（同一页只许 1 次）")


def _atc_card_inline(code: str) -> str:
    """atc.html L1 卡片：v2 四语类名 + 逐语来源/许可小字。"""
    parts: dict[str, str] = {}
    for lang in ("en", "es", "zh", "zh-Hant"):
        inner = f'<code>{esc(code)}</code> {esc(_atc_display_name(lang, code))}'
        src = _atc_source_html(code, lang)
        if src:
            inner += f' <span class="atc-src">{src}</span>'
        parts[lang] = inner
    return _lang_blocks(parts)


def build_atc_index() -> None:
    """落地页 /atc.html：14 个 ATC L1 大类 + 16 个消费者大类入口（类名 v2）。"""
    T = I18N["en"]
    l1_codes = ("A", "B", "C", "D", "G", "H", "J", "L", "M", "N", "P", "R", "S", "V")
    l1_html = "".join(
        f'<a class="atccard" href="atc/{code}.html">{_atc_card_inline(code)}</a>'
        for code in l1_codes)
    cat_html = "".join(
        f'<a class="atccard" href="cat/{cat["id"]}.html">'
        f'<span class="lang-block" data-lang-block="en" data-lang-inline="1">'
        f'{esc(cat["labels"]["en"])}</span>'
        f'<span class="lang-block" data-lang-block="es" data-lang-inline="1">'
        f'{esc(cat["labels"]["es"])}</span>'
        f'<span class="lang-block" data-lang-block="zh" data-lang-inline="1">'
        f'{esc(cat["labels"]["zh"])}</span>'
        f'<span class="lang-block" data-lang-block="zh-Hant" data-lang-inline="1">'
        f'{esc(cat["labels"]["zh-Hant"])}</span>'
        f'<span class="meta cat-en"> · {esc(cat["labels"]["en"])}</span></a>'
        for cat in CONSUMER_CATEGORIES)
    body = f"""<h1 data-i18n="atc.browse_title">{esc(T["atc.browse_title"])}</h1>
<div data-i18n="atc.browse_intro">{esc(T["atc.browse_intro"])}</div>
<h2 data-i18n="atc.all_classes">{esc(T["atc.all_classes"])}</h2>
<div class="atcgrid">{l1_html}</div>
<h2 data-i18n="cat.browse_title">{esc(T["cat.browse_title"])}</h2>
<div data-i18n="cat.intro">{esc(T["cat.intro"])}</div>
<div class="catgrid">{cat_html}</div>
<p class="sub" data-i18n="cat.disclaimer">{esc(T["cat.disclaimer"])}</p>
{_atc_notes_html(T, with_status=False)}"""
    (OUT / "atc.html").write_text(
        page("ATC classes & categories", body, "", canonical_rel="atc.html",
             nav_coverage=True),
        encoding="utf-8")
    _assert_once(body, NAMES_SOURCE_MARK, "atc.html")

def build_categories_json(db: sqlite3.Connection) -> None:
    """客户端搜索用：大类/ATC 类别名 + 前缀 + 页面 URL + 已生成的 ATC 码集合。

    v0.10.2：16 个大类的 `aliases` 里并入 `lib/categories.py` 的口语词（`退烧药` / `painkiller`
    等 66 条里除遮蔽白名单外的口语词），客户端 `catHit()` 本来就遍历 aliases，所以老缓存页面
    也会立刻认识这些词，不必等新 JS。
    """
    colloquial = colloquial_aliases_by_category()
    items = []
    for cat in CONSUMER_CATEGORIES:
        labels = dict(cat["labels"])
        aliases = [labels.get("en", ""), cat["id"], *colloquial.get(cat["id"], [])]
        items.append({"kind": "cat", "id": cat["id"], "url": f'cat/{cat["id"]}.html',
                      "prefixes": list(cat["prefixes"]), "labels": labels,
                      "aliases": [a for a in aliases if a]})
    # atc_codes 用于客户端判断「该类目页是否存在」（全部 L1–L4 前缀，1,154 个）
    groups = _atc_groups(db)
    all_codes: set[str] = set()
    for ln in (1, 3, 4, 5):
        all_codes.update(groups[ln].keys())
    # v0.8.5：类名 v2 覆盖到的 ATC 码全部进客户端搜索（不再只收内置 25 个）
    codes = {c for c in all_codes
             if c in ATC_CLASS_V2 or c in ATC_CLASS_I18N["en"] or c in ATC_L1_I18N["en"]}
    for code in sorted(codes):
        items.append({"kind": "atc", "id": code, "url": f"atc/{code}.html",
                      "prefixes": [code], "labels": _atc_names(code), "aliases": [code.lower()]})
    (OUT / "data" / "categories.json").write_text(
        json.dumps({"categories": items, "atc_codes": sorted(all_codes)},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  categories : {len(items):,} items (colloquial aliases: "
          f"{sum(len(v) for v in colloquial.values())})", flush=True)


# ── v0.10.2：类别发现快车道（构建期预生成的紧凑索引） ────────────────────────
# 现状（v0.10.1）：客户端要认出一个大类词（`退烧药`）必须先 loadIndex() 拉完整个
# core.json（41.5 MB raw / 9.9 MB gz），8 Mbps 下首查 12.6 s。审计见
# reports/search-discovery-audit-20261110.md §2。这里把「类别词 → 大类/ATC」的判定
# 与 16 个大类的 top200 结果切片预先算好，客户端首查只拉 cats.json（≈23 KB raw）
# + 一份切片（30–57 KB raw）：8 Mbps 下 34 ms 出结果，core 在后台补全。
CAT_IDX_REL = "data/idx/cats.json"
CAT_ATC_ING_REL = "data/idx/atc-ing.json"
CAT_SLICE_TOP = 200          # 与客户端 hits.slice(0, 200) 同口径
CAT_ING_PREVIEW = 16         # cats.json 里每类带的成分预览条数
ATC_ING_TOP = 15             # atc-ing.json 每个码带的成分条数（首屏摘要，core 到位后补全）


def _cat_ing_totals(db: sqlite3.Connection, prefixes: list[str]) -> list[tuple[str, int]]:
    """成分在该大类里的 active 产品数（降序）；类别切片的排序键。"""
    prefixes = [p for p in prefixes if p]
    if not prefixes:
        return []
    cond = " OR ".join("s.atc LIKE ?" for _ in prefixes)
    rows = db.execute(
        f"""SELECT s.inn_en AS inn, COUNT(DISTINCT p.product_id) AS n
            FROM substance s JOIN variant v ON v.substance_id = s.substance_id
            JOIN product_component pc ON pc.variant_id = v.variant_id
            JOIN product p ON p.product_id = pc.product_id AND p.status = 'active'
            WHERE s.atc IS NOT NULL AND ({cond})
            GROUP BY s.substance_id ORDER BY n DESC""",
        tuple(p + "%" for p in prefixes)).fetchall()
    rows = sorted(((r[0], int(r[1])) for r in rows if r[0]),
                  key=lambda r: (-r[1], r[0].lower()))   # 同数按名字，保证构建确定性
    return rows


def _cat_atc4(db: sqlite3.Connection, prefixes: list[str]) -> list[str]:
    """该大类实际覆盖到的 ATC 4 位码（现查，不用手工表）。"""
    prefixes = [p for p in prefixes if p]
    if not prefixes:
        return []
    cond = " OR ".join("s.atc LIKE ?" for _ in prefixes)
    return sorted({(r[0] or "")[:4] for r in db.execute(
        f"SELECT DISTINCT s.atc FROM substance s WHERE s.atc IS NOT NULL AND ({cond})",
        tuple(p + "%" for p in prefixes)) if r[0] and len(r[0]) >= 4})


def _slice_entry(e: dict) -> dict:
    """切片里只留客户端渲染结果行需要的字段（体积优先，丢弃厂家/明细桶等）。

    `l` = collision 级别：快车道首屏也必须有「同名并列 / 不可互换」的碰撞警示——
    否则用户要等 core 到位（最长 9 s）才看到警示，等于把底线二藏起来 9 秒。
    """
    out = {k: e[k] for k in ("k", "d", "c", "x", "s", "f", "l", "n", "v") if e.get(k) is not None}
    if e.get("atc"):
        out["atc"] = e["atc"]
    if e.get("vs"):
        out["vs"] = e["vs"]
    if e.get("u"):
        out["u"] = e["u"]
    return out


def build_cat_word_index(db: sqlite3.Connection, entries: list[dict]) -> dict[str, int]:
    """生成「类别词 → 大类/ATC」索引 + 16 个大类 top200 切片（v0.10.2）。

    派生自 `CONSUMER_CATEGORIES` + `COLLOQUIAL_ALIASES` + 本次构建的检索条目，
    不引入任何人工标注；切片里同样只是候选条目，页面文案与「不可互换」警示不变。
    产物：`data/idx/cats.json` + `data/idx/cat-<id>.json` × 16。
    """
    idx_dir = OUT / "data" / "idx"
    idx_dir.mkdir(parents=True, exist_ok=True)
    words: dict[str, str] = {}
    cats: list[dict] = []
    for cat in CONSUMER_CATEGORIES:
        for label in cat["labels"].values():
            if label:
                words[cat_norm(label)] = "cat:" + cat["id"]
        words[cat_norm(cat["id"])] = "cat:" + cat["id"]
        totals = dict(_cat_ing_totals(db, cat["prefixes"]))
        prefixes = list(cat["prefixes"])
        hit = [e for e in entries
               if e.get("atc") and any(str(c).startswith(p) for c in e["atc"] for p in prefixes)]
        # 排序口径与 lib/search.py 的大类排序（方案 H）一致：成分在该类别的产品数，
        # 再按条目产品数 —— 否则复方/命名碎片化会系统性占优（审计报告 §4）。
        hit.sort(key=lambda e: (-max((totals.get(s, 0) for s in (e.get("x") or "").split(" + ")),
                                     default=0), -(e.get("n") or 0)))
        top = hit[:CAT_SLICE_TOP]
        name = f"cat-{cat['id']}.json"
        (idx_dir / name).write_bytes(json.dumps(
            [_slice_entry(e) for e in top], ensure_ascii=False,
            separators=(",", ":")).encode("utf-8"))
        cats.append({"id": cat["id"], "url": f'cat/{cat["id"]}.html',
                     "prefixes": prefixes, "labels": dict(cat["labels"]),
                     "atc4": _cat_atc4(db, prefixes),
                     "ing": [[inn, n] for inn, n in _cat_ing_totals(db, prefixes)[:CAT_ING_PREVIEW]],
                     "slice": {"f": "data/idx/" + name, "n": len(top)}})
    # 口语词：同一份词表 → 两处产物。已剔除 lib 的「全等撞真实商品名」白名单
    # （如 antibiotic），它们必须留给药名检索（AGENTS §1 先定位名字）。
    for cat_id, ws in colloquial_aliases_by_category().items():
        for word in ws:
            words.setdefault(cat_norm(word), "cat:" + cat_id)
    all_codes: set[str] = set()
    groups = _atc_groups(db)
    for ln in (1, 3, 4, 5):
        all_codes.update(groups[ln].keys())
    payload = {"v": BUILD_V, "words": words, "cats": cats, "atc_codes": sorted(all_codes)}
    (idx_dir / "cats.json").write_bytes(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return {"words": len(words), "cats": len(cats),
            "bytes": (idx_dir / "cats.json").stat().st_size}


def build_atc_ing_json(db: sqlite3.Connection) -> dict[str, int]:
    """ATC L1/L3/L4 码 → 成分（产品数降序，最多 ATC_ING_TOP 个；成分名单独一张表）。

    一次查询算完，不按码逐条查库；只给客户端「先出成分摘要、core 后台补商品名行」用，
    不做替代判断、不合并成分。名字按 substance 存一份（同一成分出现在多个码下不重复）。
    """
    idx_dir = OUT / "data" / "idx"
    idx_dir.mkdir(parents=True, exist_ok=True)
    by_code: dict[str, list[list]] = {}
    names: dict[str, list[str]] = {}
    for sid, inn, zh, atc, n in db.execute(
            """SELECT s.substance_id, s.inn_en, s.inn_zh, s.atc,
                      COUNT(DISTINCT p.product_id)
               FROM substance s
               JOIN variant v ON v.substance_id = s.substance_id
               JOIN product_component pc ON pc.variant_id = v.variant_id
               JOIN product p ON p.product_id = pc.product_id AND p.status = 'active'
               WHERE s.atc IS NOT NULL AND s.atc <> '' AND s.inn_en IS NOT NULL
               GROUP BY s.substance_id"""):
        names[sid] = [inn, zh or ""]
        for ln in (1, 3, 4):
            if len(atc or "") >= ln:
                by_code.setdefault(atc[:ln], []).append([sid, int(n)])
    out: dict[str, list[list]] = {}
    totals: dict[str, int] = {}
    used: set[str] = set()
    for code, rows in by_code.items():
        rows.sort(key=lambda r: (-r[1], names.get(r[0], [""])[0].lower()))
        top = rows[:ATC_ING_TOP]
        out[code] = top
        totals[code] = len(rows)          # 客户端要能说「还有 N 个成分」，不许静默截断
        for sid, _n in top:
            used.add(sid)
    payload = {"v": BUILD_V, "n": {sid: names[sid] for sid in sorted(used)},
               "codes": out, "t": totals}
    (idx_dir / "atc-ing.json").write_bytes(
        json.dumps(payload, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8"))
    return {"codes": len(out), "names": len(used),
            "bytes": (idx_dir / "atc-ing.json").stat().st_size}



def _home_cat_chips(lang: str, prefix: str, limit: int = 8) -> str:
    """v0.10.0：首页只放 8 个高频大类 chip（2×4）+ 「全部类别」链接；其余在导航面板。"""
    langs = ("en", "es", "zh", "zh-Hant")
    parts = []
    for cat in CONSUMER_CATEGORIES[:limit]:
        spans = "".join(
            f'<span class="lang-block" data-lang-block="{l}" data-lang-inline="1">'
            f'{esc(cat["labels"][l])}</span>' for l in langs)
        parts.append(f'<a class="catchip" href="{prefix}cat/{cat["id"]}.html">{spans}</a>')
    parts.append(f'<a class="catchip catchip-all" href="{prefix}atc.html" '
                 f'data-i18n="cat.all_link">All categories →</a>')
    return "".join(parts)


def build_404() -> None:
    """v0.10.0 P1-8：404 页补统一壳（skip-link + 5 项导航 + 语言切换 + 页脚 + 移动底栏）。

    404 会出现在任意子路径下，所有链接用绝对 URL（SITE_URL），不引用相对 assets。
    """
    t = I18N["en"]
    sw = "".join(f'<a href="{SITE_URL}?lang={code}">{label}</a>' for code, label, _ in LANGS)
    nav = (f'<nav class="sn" data-shell="1"><a href="{SITE_URL}">{esc(t["nav.search"])}</a>'
           f'<a href="{SITE_URL}atc.html">{esc(t["nav.atc"])}</a>'
           f'<a href="{SITE_URL}coverage.html">{esc(t["nav.coverage"])}</a>'
           f'<a href="{SITE_URL}about.html">{esc(t["nav.about"])}</a></nav>')
    tab = (f'<nav class="tabbar" data-shell="1" aria-label="Sections" '
           f'data-i18n-aria="nav.sections">'
           f'<a href="{SITE_URL}">{esc(t["tab.search"])}</a>'
           f'<a href="{SITE_URL}atc.html">{esc(t["tab.categories"])}</a>'
           f'<a href="{SITE_URL}coverage.html">{esc(t["tab.coverage"])}</a>'
           f'<a href="{SITE_URL}about.html">{esc(t["tab.about"])}</a></nav>')
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{esc(t["notfound.title"])} · {esc(t["site.name"])}</title>
<link rel="stylesheet" href="{SITE_URL}{CSS_FILE}">
</head><body>
<a class="skip-link" href="#main" data-i18n="a11y.skip">Skip to content</a>
<header class="hdr-shell"><div class="wrap">
  <a class="logo" href="{SITE_URL}">Medicine Brand Cross-Reference</a>
  {nav}<span class="langs">{sw}</span>
</div></header>
<main id="main"><div class="wrap">
<h1 data-i18n="notfound.title">{esc(t["notfound.title"])}</h1>
<p data-i18n="notfound.p1">{esc(t["notfound.p1"])}</p>
<p data-i18n="notfound.p2">{esc(t["notfound.p2"])}</p>
<p class="sub links"><a href="{SITE_URL}" data-i18n="notfound.search">{esc(t["notfound.search"])}</a>
<a href="{SITE_URL}about.html" data-i18n="notfound.about">{esc(t["notfound.about"])}</a>
<a href="{SITE_URL}confused.html" data-i18n="notfound.confused">{esc(t["notfound.confused"])}</a>
<a href="{SITE_URL}whats-new.html" data-i18n="notfound.whatsnew">{esc(t["notfound.whatsnew"])}</a></p>
<p class="sub" style="margin-top:24px" data-i18n-html="notfound.report">{t["notfound.report"]}</p>
</div></main>
<footer><div class="wrap"><span data-i18n="footer">{esc(t["footer"])}</span></div></footer>
{tab}
<script src="{SITE_URL}assets/i18n.js"></script>
</body></html>"""
    (OUT / "404.html").write_text(html, encoding="utf-8")

def build_data_package(db: sqlite3.Connection, stats: dict, coverage, source_cover) -> None:
    """v0.9.2 task-23：派生层数据包（聚合/覆盖/成分清单），不导出受限来源原始记录。"""
    exports = OUT / "data" / "exports"
    exports.mkdir(parents=True, exist_ok=True)

    def write_csv(name: str, fields: list[tuple[str, str]], rows) -> dict:
        path = exports / name
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([f[0] for f in fields])
            for row in rows:
                w.writerow(row)
        return {"path": f"data/exports/{name}", "bytes": path.stat().st_size,
                "hash": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                "fields": fields, "count": sum(1 for _ in path.open(encoding="utf-8")) - 1}

    coverage_fields = [
        ("country", "string"), ("n_products", "integer"), ("n_variants", "integer"),
        ("n_active", "integer"), ("last_synced", "date")]
    cov_rows = [[r.get("country"), r.get("n_products"), r.get("n_variants"),
                 r.get("n_active"), r.get("last_synced")] for r in coverage]
    coverage_res = write_csv("coverage.csv", coverage_fields, cov_rows)

    market_rows = db.execute(
        """SELECT COALESCE(p.country, p.region) AS country, COUNT(DISTINCT p.product_id) AS products,
                  COUNT(DISTINCT v.substance_id) AS substances,
                  COUNT(DISTINCT pn.key_id) AS name_keys
           FROM product p
           LEFT JOIN product_component pc ON pc.product_id=p.product_id
           LEFT JOIN variant v ON v.variant_id=pc.variant_id
           LEFT JOIN product_name pn ON pn.product_id=p.product_id
           GROUP BY COALESCE(p.country, p.region) ORDER BY 1""").fetchall()
    market_res = write_csv("market-summary.csv", [
        ("country", "string"), ("products", "integer"), ("substances", "integer"),
        ("name_keys", "integer")], [list(r) for r in market_rows])

    name_rows = db.execute(
        """SELECT COALESCE(p.country, p.region) AS country, name_type, COUNT(*) AS n
           FROM product_name pn JOIN product p USING(product_id)
           GROUP BY country, name_type ORDER BY country, name_type""").fetchall()
    name_res = write_csv("name-summary.csv", [
        ("country", "string"), ("name_type", "string"), ("n", "integer")],
        [list(r) for r in name_rows])

    sub_rows = db.execute(
        "SELECT substance_id, inn_en, inn_zh, atc, name_lang FROM substance ORDER BY substance_id").fetchall()
    sub_res = write_csv("substances.csv", [
        ("substance_id", "string"), ("inn_en", "string"), ("inn_zh", "string"),
        ("atc", "string"), ("name_lang", "string")], [list(r) for r in sub_rows])

    resources = []
    for res, name, title, desc in (
            (coverage_res, "coverage", "Coverage by market",
             "Aggregated product/variant/active counts and last sync date per country."),
            (market_res, "market-summary", "Market summary",
             "Aggregated products, substances and name keys per country."),
            (name_res, "name-summary", "Name-layer summary",
             "Aggregated product-name counts by country and name_type (trade/inn); no per-record export."),
            (sub_res, "substances", "Substance list",
             "INN identifiers and names with ATC codes; no product-level source rows.")):
        resources.append({
            "name": name, "title": title, "description": desc,
            "path": res["path"], "format": "csv", "mediatype": "text/csv",
            "bytes": res["bytes"], "hash": res["hash"], "count": res["count"],
            "schema": {"fields": [{"name": f, "type": t} for f, t in res["fields"]]},
        })

    # 来源分级：CN/AU/MX 等未确认或限制再发布的来源标 non_redistributable；
    # 数据包只发布聚合/事实层，不发布受限来源的原始记录。
    restricted = {"CN", "AU", "MX"}
    source_countries: dict[str, set[str]] = defaultdict(set)
    for r in source_cover:
        source_countries[r.get("source_id") or ""].add(r.get("country") or "")
    sources = []
    for r in db.execute("SELECT source_id, name, url, license, license_url, data_as_of FROM source ORDER BY source_id"):
        countries = sorted(c for c in source_countries.get(r["source_id"], set()) if c)
        non_redist = bool(set(countries) & restricted)
        sources.append({
            "id": r["source_id"], "name": r["name"], "url": r["url"],
            "license": r["license"], "license_url": r["license_url"],
            "data_as_of": r["data_as_of"], "countries": countries,
            "redistributable": not non_redist,
            "note": "non_redistributable: aggregate facts only; no raw-record export" if non_redist else "",
        })

    version = LATEST_VERSION or "v0.9.2"
    # v0.9.9 task-14：数据包时间戳以前取「构建时刻」（精确到秒）→ 两次构建必不同，
    # 还会经 checksums.txt 的 datapackage.json 哈希级联出第 2 个差异文件。
    # 改成 CHANGELOG 顶部那一版的日期：同一次发布的所有构建共用同一个值。
    pkg_date = LATEST_DATE or time.strftime("%Y-%m-%d", time.gmtime())
    pkg = {
        "profile": "tabular-data-package",
        "name": "drug-brand-crossref-derived",
        "title": "Medicine Brand Cross-Reference — derived data package",
        "description": ("Derived, aggregate-first data package for the cross-market medicine brand "
                        "reference. Product/name records are not redistributed from restricted sources; "
                        "only aggregates and a substance list are included."),
        "version": version,
        "created": f"{pkg_date}T00:00:00Z",
        "homepage": SITE_URL,
        "licenses": [{
            "name": "mixed-derived",
            "title": "Derived data — source licences apply; see docs/数据溯源与许可.md",
            "path": "https://github.com/fuarnos/drug-brand-crossref/blob/main/docs/数据溯源与许可.md",
        }],
        "sources": sources,
        "resources": resources,
        "counts": {"products": stats.get("products"), "substances": stats.get("substances"),
                   "name_keys": stats.get("keys"), "markets": len(coverage)},
    }
    pkg_path = OUT / "datapackage.json"
    pkg_path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dataset = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Medicine Brand Cross-Reference — derived data",
        "description": pkg["description"],
        "url": SITE_URL + "datapackage.json",
        "version": version,
        "dateModified": pkg_date,
        "license": pkg["licenses"][0]["path"],
        "creator": {"@type": "Organization", "name": "Medicine Brand Cross-Reference",
                    "url": SITE_URL},
        "isAccessibleForFree": True,
        "distribution": [
            {"@type": "DataDownload", "name": r["name"], "contentUrl": SITE_URL + r["path"],
             "encodingFormat": r["mediatype"], "contentSize": r["bytes"]} for r in resources
        ] + [{"@type": "DataDownload", "name": "datapackage.json",
              "contentUrl": SITE_URL + "datapackage.json",
              "encodingFormat": "application/json"}],
    }
    (OUT / "dataset.jsonld").write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    files = [("datapackage.json", pkg_path), ("dataset.jsonld", OUT / "dataset.jsonld")]
    docs_src = ROOT / "docs" / "data-dictionary.md"
    if docs_src.exists():
        docs_dir = OUT / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(docs_src, docs_dir / "data-dictionary.md")
        files.append(("docs/data-dictionary.md", docs_dir / "data-dictionary.md"))
    files += [(r["path"], OUT / r["path"]) for r in resources]
    checks = []
    for rel, path in files:
        checks.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")
    (OUT / "checksums.txt").write_text("\n".join(checks) + "\n", encoding="utf-8")
    print(f"  data package: {len(resources)} resources, checksums.txt", flush=True)


def build_export_only_json(db: sqlite3.Connection) -> None:
    """v0.9.1 task-28：Export Only 产品 ID 集合（明细面板懒加载）。"""
    ids = [r[0] for r in db.execute(
        """SELECT product_id FROM product
           WHERE (note LIKE '%出口%' OR note LIKE '%Export%'
                  OR category LIKE '%Export%')
           ORDER BY product_id""")]
    (OUT / "data" / "export-only.json").write_text(
        json.dumps(ids, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build_seo_files() -> None:
    """生成 robots.txt + sitemap.xml + .nojekyll（404.html 另由 build_404 生成）。

    sitemap 扫的是刚写出来的 HTML 文件，所以调用时机必须在所有页面之后。
    中文文件名百分号编码后写进 <loc>。
    """
    from urllib.parse import quote

    lastmod = LATEST_DATE or time.strftime("%Y-%m-%d")
    urls: list[str] = []
    for p in OUT.rglob("*.html"):
        rel = p.relative_to(OUT).as_posix()
        if rel == "404.html" or rel in NOINDEX_RELS:
            continue
        if rel == "index.html":
            urls.append(SITE_URL)
        elif rel.endswith("/index.html"):
            urls.append(SITE_URL + rel[: -len("index.html")])
        else:
            urls.append(SITE_URL + rel)
    urls.sort()

    with (OUT / "sitemap.xml").open("w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for url in urls:
            loc = quote(url, safe=":/?&=%#")
            fh.write(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>\n")
        fh.write("</urlset>\n")

    (OUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: " + SITE_URL + "sitemap.xml\n",
        encoding="utf-8")
    # 第三方部署验证文件：固定公开随机串，每次构建都写到站点根目录（不属于页面，不进 sitemap）。
    # 用二进制写入保证恰好是 40 字节哈希 + LF（Windows 文本模式会写成 CRLF）。
    (OUT / "e2fea3dfe91d65e7c4dc23106afa53e2.txt").write_bytes(
        b"50b080b3ad91dc61bc684f8cef65ce3bbb99e77c\n")
    # GitHub Pages 默认会跑 Jekyll；.nojekyll 让它直接当静态文件发。
    # 内容留一行说明：发布脚本会拒绝 0 字节文件（防止构建中断发布半成品）。
    (OUT / ".nojekyll").write_text(
        "# GitHub Pages: serve this directory as-is (skip Jekyll)\n", encoding="utf-8")
    print(f"  seo files  : 404 + robots + sitemap ({len(urls)} urls) + deploy verify", flush=True)


# ── P1 索引核心：列式 + 字典编码 ─────────────────────────────────────
# 目标：把 34.8 MB 的 data/index.json 编成 data/idx/core.json，客户端
#       decodeCore() 解码回与 index.json 完全同构（同字段、同顺序）的 IDX 数组，
#       render() 以下逻辑一行不改。旧 index.json 继续双写：?legacy=1 或核心
#       加载/解码失败时自动回退。设计与体积对比见 reports/index-p1-impl.md。
#
# 编码格式（v1）：
#   {"v":1,"n":条数,
#    "cols":{
#      "k":[str...],                     检索键（原样，不排序——保持 IDX 原有顺序，
#                                        下游 inCountry/同成分列表的顺序才不变）
#      "d":[str...],  "dp":[str...],     d 与 k 只差 ASCII 大小写时 d 存 ""、
#                                        dp 存大小写位置模式（"0-2,5" 表示把这些
#                                        位 toUpperCase 后还原 d）；否则 d 存原文
#      "c":{"d":[值...],"i":[下标...]}, 字典列：字符串字典 + 每行字典下标
#      ...（x/s/l/v/vs/g/gn/m 同字典列；c/s/vs 的值是数组，先 JSON 化再字典化）
#      "n":[int...], "mn":[int...], "u":[str...]   普通列
#    },
#    "q":[稀疏下标...]}                   q=1 的行下标（163 条，单独稀疏存）
#   f（剂型）v0.6.1 加入核心：B7 CSV 导出用 e.f，且 ?legacy=1 走 core 解码后需与旧
#   index.json 完全同构（除 f 外 19 字段已验证 0 差异；f 只有 ~9 种字典值，core +0.2–0.3 MB）。
CORE_DICT_COLS = ("c", "x", "s", "l", "v", "vs", "cu", "mu", "g", "gn", "m", "f",
                  "db", "sl", "rl", "wi")
CORE_ARRAY_COLS = ("c", "s", "vs", "ml", "xz", "atc", "fs")     # 值是数组：先 JSON 化再进字典
# v0.11.2 P0-1：core 必须逐行携带的列。t / nc / eo 是 v0.9.0–v0.9.1 才加进 load_index()
# 条目的字段，这里的手写清单曾漏掉它们 → core 解码后 e.t === undefined，客户端 166,846 /
# 196,200 行（85.0%）的品牌名被换成「无商品名 + 命中名」。新增条目字段时必须同步这份清单
# （encode_core() 里的构建期守卫会在漏列时直接中止构建）。
CORE_FIELDS = ("c", "x", "xz", "atc", "s", "l", "f", "n", "t", "v", "vs", "nc", "eo",
               "u", "cu", "mu", "ml", "g", "gn", "m", "mn", "db", "sl", "rl", "wi",
               # T10（plan §3.4 ④）：剂型 × 规格对；新增条目字段必须同步这份清单
               "fs")


def _d_case_pattern(d: str, k: str) -> str | None:
    """d 与 k 只差 ASCII 大小写时返回大小写位置模式（'0' / '0-2,5'），否则 None。

    模式里 'a-b' 是闭区间：把 k 的第 a..b 个字符 toUpperCase 后即得 d。
    只处理 ASCII：非 ASCII 的大小写映射（ß→SS、İ→i̇ 等）Python 与 JS 行为
    未必一致，这类条目一律让 d 存完整原文，解码端不做映射。
    """
    if len(d) != len(k):
        return None
    runs: list[str] = []
    i = 0
    while i < len(k):
        if d[i] == k[i]:
            i += 1
            continue
        if ord(k[i]) > 127 or d[i] != k[i].upper():
            return None
        j = i
        while (j + 1 < len(k) and d[j + 1] != k[j + 1]
               and ord(k[j + 1]) < 128 and d[j + 1] == k[j + 1].upper()):
            j += 1
        runs.append(f"{i}-{j}" if j > i else str(i))
        i = j + 1
    return ",".join(runs)


def encode_core(entries) -> dict:
    """entries（load_index 的结果）→ 列式 + 字典编码的 core 对象。"""
    n = len(entries)
    d_col: list[str] = []
    dp_col: list[str] = []
    for e in entries:
        d, k = e["d"], e["k"]
        if d == k:
            d_col.append("")
            dp_col.append("")
            continue
        pat = _d_case_pattern(d, k)
        if pat is None:
            d_col.append(d)          # 大小写差异超出 ASCII 规则：存完整 d
            dp_col.append("")
        else:
            d_col.append("")         # 可由 k + 模式还原
            dp_col.append(pat)
    cols: dict[str, object] = {"k": [e["k"] for e in entries], "d": d_col, "dp": dp_col}
    # P0-1 守卫：core 一旦漏列，decodeCore 后该字段是 undefined，前端静默渲染错位
    # （v0.9.0 的 t 就这样丢了 85% 的商品名）。宁可构建失败，不要发布缺列的 core。
    unknown = {f for e in entries for f in e} - set(CORE_FIELDS) - {"k", "d", "q"}
    if unknown:
        raise SystemExit(f"encode_core 漏字段 {sorted(unknown)}：core.json 会缺列，"
                         "客户端渲染错位（把新字段加进 CORE_FIELDS）")
    for f in CORE_FIELDS:
        vals = [e.get(f) for e in entries]
        if f in CORE_ARRAY_COLS:
            # 数组先序列化再字典化：客户端解码时把字典值直接给出（数组引用共享，
            # render 只读不写），不需要逐行 JSON.parse。
            raw = [json.dumps(v, ensure_ascii=False, separators=(",", ":")) for v in vals]
            uniq = list(dict.fromkeys(raw))
            pos = {u: i for i, u in enumerate(uniq)}
            cols[f] = {"d": [json.loads(u) for u in uniq],
                       "i": [pos[u] for u in raw]}
        elif f in CORE_DICT_COLS:
            uniq = list(dict.fromkeys(vals))
            pos = {u: i for i, u in enumerate(uniq)}
            cols[f] = {"d": uniq, "i": [pos[v] for v in vals]}
        else:
            cols[f] = vals
    return {"v": 1, "n": n, "cols": cols,
            "q": [i for i, e in enumerate(entries) if e.get("q")]}



# ── 搜索增强（task-28）：拼音字符表 + 拼音/首字母 token 编码 ──────────────────
# 1,582 个字 = 索引/别名里出现过的全部汉字（pinyin-pro 3.29.5，toneType=none，
# 取默认读音；多音字用默认读音即可，拼音只是 exact/prefix 之外的增量兜底路径）。
# 生成/校验方式见 reports/search-engine-v2.md；客户端不依赖拼音库：查询串本身就是
# token（tainuo -> j:tainuo，tn -> i:tn），只需按 token 精确查表。
_PINYIN_CHARS_TEXT = "䓬:zhuo 一:yi 丁:ding 七:qi 万:wan 三:san 上:shang 下:xia 不:bu 与:yu 专:zhuan 世:shi 丙:bing 业:ye 东:dong 丝:si 两:liang 严:yan 中:zhong 丰:feng 临:lin 丸:wan 丹:dan 为:wei 丽:li 乃:nai 久:jiu 之:zhi 乌:wu 乎:hu 乐:le 乙:yi 九:jiu 乱:luan 乳:ru 了:liao 予:yu 二:er 云:yun 五:wu 亚:ya 亢:kang 交:jiao 亦:yi 产:chan 京:jing 亭:ting 亮:liang 人:ren 亿:yi 仁:ren 今:jin 介:jie 仑:lun 仔:zai 仕:shi 他:ta 仙:xian 仟:qian 代:dai 令:ling 仪:yi 仲:zhong 价:jia 任:ren 伉:kang 伊:yi 伏:fu 伐:fa 休:xiu 众:zhong 优:you 伞:san 伟:wei 伤:shang 伦:lun 伪:wei 伯:bo 伲:ni 伴:ban 伶:ling 伸:shen 伽:jia 位:wei 低:di 佐:zuo 佑:you 体:ti 佛:fo 佩:pei 佰:bai 佳:jia 佶:ji 使:shi 侗:dong 供:gong 依:yi 侣:lü 侬:nong 便:bian 促:cu 俊:jun 保:bao 信:xin 俪:li 修:xiu 倍:bei 倡:chang 倩:qian 假:jia 停:ting 健:jian 催:cui 傲:ao 僖:xi 儒:ru 儿:er 允:yun 元:yuan 充:chong 兆:zhao 先:xian 光:guang 克:ke 免:mian 兔:tu 入:ru 全:quan 八:ba 公:gong 六:liu 兮:xi 兰:lan 关:guan 兴:xing 兵:bing 其:qi 典:dian 兹:zi 养:yang 内:nei 冉:ran 册:ce 再:zai 军:jun 农:nong 冠:guan 冬:dong 冰:bing 冲:chong 决:jue 冷:leng 冻:dong 净:jing 凌:ling 减:jian 凝:ning 凡:fan 凯:kai 出:chu 分:fen 切:qie 列:lie 则:ze 刚:gang 创:chuang 初:chu 利:li 别:bie 制:zhi 刹:cha 刺:ci 刻:ke 剂:ji 前:qian 剑:jian 力:li 功:gong 加:jia 动:dong 助:zhu 努:nu 劲:jin 劳:lao 勃:bo 勉:mian 勒:le 勤:qin 包:bao 化:hua 北:bei 匙:chi 匹:pi 区:qu 十:shi 千:qian 升:sheng 卉:hui 半:ban 华:hua 协:xie 卓:zhuo 单:dan 南:nan 博:bo 卜:bu 卟:bu 占:zhan 卡:ka 卢:lu 卤:lu 卫:wei 即:ji 卵:luan 卷:juan 厄:e 历:li 压:ya 原:yuan 去:qu 参:can 及:ji 友:you 双:shuang 反:fan 发:fa 叔:shu 取:qu 受:shou 变:bian 口:kou 古:gu 只:zhi 叮:ding 可:ke 台:tai 史:shi 右:you 叶:ye 号:hao 司:si 合:he 吉:ji 同:tong 名:ming 后:hou 吐:tu 吖:a 吗:ma 君:jun 吡:bi 吨:dun 吩:fen 含:han 启:qi 吲:yin 吸:xi 吻:wen 吾:wu 呋:fu 呗:bai 呤:ling 呫:tie 呱:gua 味:wei 呵:he 呼:hu 命:ming 咀:zui 和:he 咐:fu 咖:ka 咛:ning 咨:zi 咪:mi 咯:ge 咳:hai 品:pin 哈:ha 哌:pai 哒:da 哚:duo 哥:ge 哲:zhe 唐:tang 唑:zuo 唛:mai 唯:wei 唾:tuo 商:shang 啉:lin 啡:fei 啶:ding 喃:nan 善:shan 喉:hou 喏:nuo 喜:xi 喷:pen 喹:kui 嗉:su 嗜:shi 嗪:qin 嘉:jia 嘌:piao 嘧:mi 嘿:hei 噁:e 器:qi 噬:shi 噻:sai 嚼:jiao 囊:nang 囗:wei 四:si 因:yin 固:gu 国:guo 图:tu 土:tu 圣:sheng 在:zai 地:di 均:jun 坎:kan 坏:huai 坤:kun 坦:tan 垂:chui 型:xing 埃:ai 域:yu 培:pei 基:ji 堂:tang 塔:ta 塞:sai 增:zeng 墩:dun 壁:bi 士:shi 壬:ren 壮:zhuang 声:sheng 壹:yi 备:bei 复:fu 夏:xia 外:wai 多:duo 夜:ye 大:da 天:tian 太:tai 夫:fu 失:shi 头:tou 夷:yi 夸:kua 奇:qi 奈:nai 奉:feng 奋:fen 奎:kui 奕:yi 奥:ao 女:nü 奴:nu 好:hao 如:ru 妇:fu 妈:ma 妙:miao 妤:yu 妥:tuo 妮:ni 姆:mu 姜:jiang 威:wei 娜:na 婕:jie 婷:ting 媒:mei 子:zi 孕:yun 存:cun 孚:fu 孛:bei 孟:meng 孢:bao 学:xue 孩:hai 宁:ning 它:ta 宇:yu 安:an 宏:hong 宓:mi 宗:zong 定:ding 宜:yi 宝:bao 实:shi 宣:xuan 宫:gong 家:jia 容:rong 宾:bin 密:mi 富:fu 寒:han 对:dui 导:dao 封:feng 射:she 将:jiang 小:xiao 尓:er 尔:er 尖:jian 尘:chen 尚:shang 尤:you 尼:ni 尽:jin 尿:niao 层:ceng 屈:qu 屋:wu 屏:ping 屑:xie 山:shan 岁:sui 岚:lan 岛:dao 岩:yan 峰:feng 崩:beng 川:chuan 工:gong 左:zuo 巧:qiao 巨:ju 巯:qiu 己:ji 已:yi 巴:ba 布:bu 帅:shuai 帆:fan 希:xi 帕:pa 帝:di 带:dai 帮:bang 常:chang 幔:man 干:gan 平:ping 幸:xing 广:guang 庆:qing 库:ku 应:ying 庚:geng 度:du 康:kang 延:yan 廷:ting 廸:di 建:jian 廿:nian 开:kai 异:yi 式:shi 弗:fu 弘:hong 张:zhang 弥:mi 弹:tan 强:qiang 归:gui 当:dang 彤:tong 影:ying 彼:bi 征:zheng 待:dai 律:lü 得:de 御:yu 循:xun 微:wei 德:de 心:xin 必:bi 忆:yi 志:zhi 快:kuai 念:nian 忻:xin 忾:kai 思:si 怡:yi 性:xing 总:zong 恒:heng 恤:xu 恩:en 恪:ke 恬:tian 息:xi 恺:kai 悉:xi 悦:yue 悬:xuan 惟:wei 惠:hui 愈:yu 意:yi 感:gan 慢:man 慧:hui 慰:wei 慷:kang 戈:ge 戊:wu 成:cheng 戴:dai 扁:bian 手:shou 扎:zha 扑:pu 托:tuo 扬:yang 扰:rao 扶:fu 承:cheng 抑:yi 抒:shu 抗:kang 折:zhe 抚:fu 护:hu 拉:la 拓:tuo 拜:bai 择:ze 拿:na 挺:ting 换:huan 捷:jie 接:jie 控:kong 提:ti 握:wo 援:yuan 搏:bo 搽:cha 撒:sa 擎:qing 支:zhi 收:shou 攸:you 改:gai 放:fang 效:xiao 敌:di 敏:min 敖:ao 敢:gan 散:san 敦:dun 敬:jing 整:zheng 敷:fu 文:wen 斑:ban 断:duan 斯:si 新:xin 方:fang 施:shi 旁:pang 旋:xuan 无:wu 日:ri 旦:dan 旨:zhi 旭:xu 时:shi 旺:wang 昂:ang 昆:kun 昊:hao 昌:chang 明:ming 易:yi 昔:xi 昕:xin 昙:tan 星:xing 春:chun 显:xian 晋:jin 晓:xiao 晗:han 晟:sheng 晨:chen 普:pu 景:jing 晴:qing 晶:jing 智:zhi 暴:bao 曲:qu 更:geng 曼:man 曾:ceng 替:ti 月:yue 朋:peng 服:fu 朗:lang 望:wang 期:qi 朦:meng 木:mu 末:mo 本:ben 术:shu 朴:pu 朵:duo 机:ji 杆:gan 杉:shan 李:li 杏:xing 杖:zhang 杜:du 束:shu 来:lai 杨:yang 杭:hang 杰:jie 杷:pa 松:song 板:ban 极:ji 构:gou 枇:pi 析:xi 林:lin 果:guo 枝:zhi 枢:shu 枯:ku 架:jia 枸:gou 柏:bai 柑:gan 柔:rou 柠:ning 柯:ke 柳:liu 柴:chai 树:shu 栓:shuan 栢:bai 株:zhu 样:yang 核:he 根:gen 格:ge 桂:gui 桃:tao 桉:an 桑:sang 桔:ju 桦:hua 梅:mei 梗:geng 梨:li 梭:suo 检:jian 棉:mian 棒:bang 棓:bang 棕:zong 棘:ji 森:sen 植:zhi 椒:jiao 榄:lan 榈:lü 榔:lang 榕:rong 榭:xie 榴:liu 槐:huai 槟:bin 樟:zhang 橘:ju 橙:cheng 橼:yuan 檗:bo 檬:meng 次:ci 欢:huan 欣:xin 欧:ou 歌:ge 止:zhi 正:zheng 步:bu 武:wu 歧:qi 死:si 殊:shu 殷:yin 毅:yi 母:mu 每:mei 毒:du 毓:yu 比:bi 毕:bi 毛:mao 氏:shi 民:min 气:qi 氘:dao 氟:fu 氢:qing 氧:yang 氨:an 氮:dan 氯:lü 氰:qing 水:shui 永:yong 汀:ting 汁:zhi 汇:hui 汉:han 汕:shan 汝:ru 汞:gong 汰:tai 沁:qin 沂:yi 沃:wo 沐:mu 沙:sha 沛:pei 没:mei 沥:li 沫:mo 河:he 油:you 治:zhi 泉:quan 泊:bo 泌:mi 法:fa 泛:fan 泡:pao 波:bo 注:zhu 泪:lei 泮:pan 泯:min 泰:tai 泻:xie 泼:po 泽:ze 洁:jie 洋:yang 洗:xi 洛:luo 津:jin 洲:zhou 活:huo 派:pai 流:liu 浆:jiang 测:ce 济:ji 浓:nong 浙:zhe 浦:pu 浩:hao 浪:lang 海:hai 浸:jin 涂:tu 消:xiao 涓:juan 润:run 液:ye 涵:han 淀:dian 淑:shu 深:shen 淳:chun 混:hun 添:tian 清:qing 渗:shen 渠:qu 温:wen 渭:wei 港:gang 游:you 湖:hu 溉:gai 源:yuan 溢:yi 溴:xiu 溶:rong 滋:zi 滔:tao 滞:zhi 满:man 滤:lü 滨:bin 滴:di 漱:shu 潇:xiao 潘:pan 澜:lan 澳:ao 激:ji 瀚:han 灌:guan 火:huo 灭:mie 灰:hui 灵:ling 炉:lu 炎:yan 炔:que 炭:tan 点:dian 烃:ting 烟:yan 热:re 烯:xi 烷:wan 焦:jiao 然:ran 熊:xiong 熙:xi 熹:xi 爱:ai 爽:shuang 片:pian 牙:ya 牛:niu 牡:mu 物:wu 特:te 犀:xi 犬:quan 状:zhuang 狂:kuang 狄:di 狗:gou 独:du 猗:yi 猛:meng 猪:zhu 猫:mao 猴:hou 玄:xuan 玉:yu 王:wang 玖:jiu 玛:ma 玥:yue 玫:mei 环:huan 玻:bo 珀:po 珂:ke 珊:shan 珍:zhen 珐:fa 珑:long 珞:luo 珠:zhu 班:ban 珮:pei 球:qiu 琅:lang 理:li 琥:hu 琦:qi 琪:qi 琳:lin 琴:qin 琼:qiong 瑙:nao 瑚:hu 瑜:yu 瑞:rui 瑟:se 璃:li 璐:lu 璞:pu 瓜:gua 瓦:wa 甘:gan 甜:tian 生:sheng 用:yong 甫:fu 田:tian 由:you 甲:jia 申:shen 电:dian 甾:zai 畅:chang 留:liu 番:fan 疏:shu 疗:liao 疫:yi 疮:chuang 疱:pao 疹:zhen 病:bing 症:zheng 痔:zhi 痘:dou 痛:tong 痢:li 瘤:liu 癌:ai 癣:xuan 癸:gui 登:deng 白:bai 百:bai 皂:zao 的:de 皆:jie 皇:huang 皓:hao 皮:pi 皿:min 盈:ying 益:yi 盐:yan 盒:he 盖:gai 盘:pan 盛:sheng 盟:meng 目:mu 直:zhi 相:xiang 盼:pan 盾:dun 眉:mei 真:zhen 眩:xuan 眼:yan 睦:mu 睾:gao 睿:rui 矛:mao 知:zhi 短:duan 石:shi 矾:fan 砂:sha 研:yan 砜:feng 破:po 砷:shen 础:chu 硅:gui 硒:xi 硝:xiao 硫:liu 硬:ying 确:que 硼:peng 碇:ding 碘:dian 碧:bi 碱:jian 碳:tan 磊:lei 磷:lin 磺:huang 示:shi 社:she 祛:qu 祝:zhu 神:shen 祥:xiang 祺:qi 禄:lu 福:fu 离:li 禾:he 秀:xiu 秋:qiu 种:zhong 科:ke 秘:mi 秦:qin 积:ji 移:yi 稀:xi 稳:wen 穆:mu 穗:sui 穿:chuan 立:li 童:tong 端:duan 竹:zhu 笋:sun 笑:xiao 笔:bi 笛:di 符:fu 策:ce 简:jian 算:suan 管:guan 米:mi 类:lei 籽:zi 粉:fen 粒:li 粘:nian 粟:su 精:jing 糊:hu 糖:tang 糜:mi 糠:kang 系:xi 素:su 索:suo 紧:jin 紫:zi 累:lei 红:hong 纤:xian 纬:wei 纯:chun 纱:sha 纳:na 纷:fen 纽:niu 纾:shu 线:xian 组:zu 绅:shen 细:xi 织:zhi 绍:shao 经:jing 绒:rong 结:jie 给:gei 绛:jiang 络:luo 统:tong 绣:xiu 绥:sui 绪:xu 绮:qi 维:wei 绵:mian 综:zong 绿:lü 缇:ti 缌:si 缓:huan 缘:yuan 缩:suo 缬:xie 缺:que 罂:ying 罗:luo 置:zhi 羊:yang 美:mei 羔:gao 羚:ling 羟:qiang 群:qun 羧:suo 羽:yu 翁:weng 翔:xiang 翘:qiao 翰:han 考:kao 而:er 耐:nai 耳:er 联:lian 聚:ju 聪:cong 肉:rou 肌:ji 肖:xiao 肝:gan 肟:wo 肠:chang 肤:fu 肥:fei 肪:fang 肯:ken 育:yu 肺:fei 肼:jing 肽:tai 肾:shen 肿:zhong 胀:zhang 胂:shen 胃:wei 胆:dan 胍:gua 胎:tai 胚:pei 胜:sheng 胞:bao 胡:hu 胭:yan 胰:yi 胱:guang 胶:jiao 胸:xiong 胺:an 能:neng 脂:zhi 脉:mai 脊:ji 脑:nao 脒:mi 脯:pu 脱:tuo 脲:niao 脾:pi 腈:jing 腐:fu 腔:qiang 腙:zong 腥:xing 腮:sai 腹:fu 腺:xian 腾:teng 膏:gao 膜:mo 膦:lin 膨:peng 臣:chen 自:zi 至:zhi 致:zhi 臻:zhen 臼:jiu 舌:she 舍:she 舒:shu 良:liang 色:se 艾:ai 节:jie 芊:qian 芍:shao 芎:xiong 芙:fu 芝:zhi 芥:jie 芦:lu 芩:qin 芪:qi 芬:fen 芭:ba 芮:rui 芯:xin 花:hua 芳:fang 芷:zhi 芸:yun 芽:ya 苄:bian 苏:su 苓:ling 苗:miao 若:ruo 苦:ku 苧:zhu 苯:ben 英:ying 苷:gan 苹:ping 茁:zhuo 茄:qie 茉:mo 茚:yin 茛:gen 茜:qian 茴:hui 茵:yin 茶:cha 荃:quan 荆:jing 草:cao 荟:hui 荣:rong 荧:ying 药:yao 荷:he 荻:di 莎:sha 莨:lang 莪:e 莫:mo 莰:kan 莱:lai 莲:lian 获:huo 莹:ying 菁:jing 菇:gu 菊:ju 菌:jun 菏:he 菖:chang 菜:cai 菠:bo 菪:dang 菱:ling 菲:fei 萄:tao 萌:meng 萘:nai 萝:luo 营:ying 萨:sa 萩:qiu 落:luo 葆:bao 葎:lü 葛:ge 葡:pu 葵:kui 蒂:di 蒎:pai 蒙:meng 蒜:suan 蒲:pu 蒽:en 蒿:hao 蓉:rong 蓓:bei 蓝:lan 蓟:ji 蓣:yu 蔓:man 蔗:zhe 蔺:lin 蔻:kou 蕊:rui 蕲:qi 薁:yu 薄:bao 薇:wei 薯:shu 藤:teng 藻:zao 虎:hu 虑:lü 虫:chong 虹:hong 蚓:yin 蛇:she 蛋:dan 蛎:li 蛙:wa 蛹:yong 蜂:feng 蜚:fei 蜜:mi 蜡:la 蝎:xie 蝥:mao 蝮:fu 蝶:die 融:rong 螨:man 螺:luo 蠊:lian 血:xue 行:xing 衍:yan 衡:heng 衣:yi 补:bu 表:biao 袋:dai 裂:lie 装:zhuang 裕:yu 西:xi 见:jian 观:guan 视:shi 角:jiao 解:jie 言:yan 誉:yu 讯:xun 记:ji 设:she 诊:zhen 试:shi 诗:shi 诚:cheng 诺:nuo 谊:yi 谓:wei 谛:di 谱:pu 谷:gu 豆:dou 象:xiang 豪:hao 贝:bei 贞:zhen 质:zhi 贯:guan 贴:tie 贵:gui 费:fei 贺:he 贻:yi 赋:fu 赐:ci 赖:lai 赛:sai 赞:zan 赤:chi 赫:he 超:chao 越:yue 跃:yue 路:lu 踪:zong 蹄:ti 身:shen 车:che 轩:xuan 转:zhuan 轮:lun 软:ruan 轻:qing 载:zai 较:jiao 辅:fu 辉:hui 输:shu 辛:xin 辣:la 辰:chen 辽:liao 达:da 迁:qian 迅:xun 过:guo 迈:mai 运:yun 近:jin 返:fan 还:hai 远:yuan 连:lian 迦:jia 迪:di 迭:die 迷:mi 适:shi 选:xuan 逊:xun 透:tou 通:tong 速:su 造:zao 逸:yi 逻:luo 遇:yu 道:dao 那:na 邦:bang 邻:lin 郁:yu 郝:hao 都:dou 酊:ding 配:pei 酐:gan 酒:jiu 酚:fen 酞:tai 酪:lao 酮:tong 酯:zhi 酰:xian 酵:jiao 酶:mei 酸:suan 酿:niang 醇:chun 醋:cu 醌:kun 醑:xu 醚:mi 醛:quan 采:cai 释:shi 里:li 重:zhong 量:liang 金:jin 鑫:xin 钆:ga 钇:yi 钐:shan 钙:gai 钠:na 钡:bei 钦:qin 钩:gou 钰:yu 钴:gu 钾:jia 铁:tie 铂:bo 铃:ling 铊:ta 铋:bi 铜:tong 铝:lü 铭:ming 铵:an 银:yin 链:lian 铿:keng 锂:li 锆:gao 锋:feng 锌:xin 锐:rui 锑:ti 锝:de 锡:xi 锦:jin 锭:ding 锰:meng 锵:qiang 锶:si 镁:mei 镇:zhen 镜:jing 镧:lan 镭:lei 长:chang 门:men 闭:bi 闯:chuang 闲:xian 间:jian 阁:ge 阔:kuo 防:fang 阳:yang 阴:yin 阿:a 附:fu 陆:lu 降:jiang 陷:xian 隆:long 隐:yin 雄:xiong 雅:ya 集:ji 雌:ci 雨:yu 雪:xue 雷:lei 雾:wu 霁:ji 震:zhen 霉:mei 霍:huo 霖:lin 霜:shuang 霡:mai 露:lu 青:qing 靓:liang 靖:jing 静:jing 靛:dian 非:fei 面:mian 革:ge 鞘:qiao 鞣:rou 韦:wei 韬:tao 韵:yun 顶:ding 顺:shun 顿:dun 颂:song 预:yu 颅:lu 颇:po 颊:jia 颐:yi 颖:ying 颗:ke 颜:yan 颠:dian 风:feng 飒:sa 飞:fei 食:shi 饮:yin 馈:kui 首:shou 香:xiang 馨:xin 马:ma 骁:xiao 验:yan 骨:gu 髓:sui 高:gao 鬼:gui 魏:wei 鱼:yu 鲁:lu 鲑:gui 鲨:sha 鲸:jing 鸟:niao 鸡:ji 鸣:ming 鸿:hong 鹅:e 鹿:lu 麝:she 麟:lin 麦:mai 麸:fu 麻:ma 黄:huang 黏:nian 默:mo 黛:dai 鼎:ding 鼠:shu 鼻:bi 齐:qi 龄:ling 龙:long"
_PINYIN_DICT: dict[str, str] | None = None


def _pinyin_dict() -> dict[str, str]:
    """把「字:拼音」空格串解析成 dict（进程内只解析一次）。"""
    global _PINYIN_DICT
    if _PINYIN_DICT is None:
        out: dict[str, str] = {}
        for part in _PINYIN_CHARS_TEXT.split():
            ch, _, py = part.partition(":")
            if ch and py:
                out[ch] = py
        _PINYIN_DICT = out
    return _PINYIN_DICT


def _pinyin_tokens(text: str) -> list[str]:
    """汉字串 -> 拼音 token 集合：s:音节 / j:连写 / i:首字母；拉丁片段按词切。"""
    table = _pinyin_dict()
    syl: list[str] = []
    toks: set[str] = set()
    for ch in text or "":
        if "\u3400" <= ch <= "\u9fff":
            p = table.get(ch)
            if p:
                syl.append(p)
                toks.add("s:" + p)
        elif ch.isascii() and ch.isalnum():
            syl.append(ch.lower())
            toks.add("s:" + ch.lower())
    if len(syl) > 1:
        toks.add("j:" + "".join(syl))
        toks.add("i:" + "".join(x[0] for x in syl))
    return sorted(toks)


def encode_pinyin(entries, aliases) -> dict:
    """拼音/首字母别名表：token -> 条目下标数组（客户端懒加载，约 0.4 MB gzip）。

    - 名字键里含汉字的条目：按 k 生成 token；
    - 俗称/旧名：按显示名生成 token，指向该成分的条目（每个 token 最多 40 条，
      按 n 降序截断，控制懒加载体积；拼音只是增量路径，完整品牌列表仍由 result 页/中文俗称路径给出）。
    """
    toks: dict[str, set[int]] = {}
    for i, e in enumerate(entries):
        k = e.get("k") or ""
        if not re.search(r"[\u3400-\u9fff]", k):
            continue
        for tk in _pinyin_tokens(k):
            toks.setdefault(tk, set()).add(i)
    sid_ids: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        for sid in (e.get("vs") or [e.get("v")]):
            if sid:
                sid_ids.setdefault(sid, []).append(i)
    for a in aliases:
        sid = a.get("v")
        label = a.get("a") or a.get("n") or ""
        if not sid or not re.search(r"[\u3400-\u9fff]", label):
            continue
        ids = sid_ids.get(sid) or []
        if not ids:
            continue
        if len(ids) > 10:
            ids = sorted(ids, key=lambda i: -(entries[i].get("n") or 0))[:10]
        for tk in _pinyin_tokens(label):
            toks.setdefault(tk, set()).update(ids)
    return {"v": 1, "tokens": [[k, sorted(v)] for k, v in sorted(toks.items())]}



def _shard_bucket(key: str) -> str:
    """分片桶：首字符 A-Z / 数字 / CJK 按拼音首字母 / 其他符号。"""
    ch = (key or "")[:1]
    if not ch:
        return "other"
    if "a" <= ch <= "z":
        return ch
    if ch.isdigit():
        return "digit"
    if "\u3400" <= ch <= "\u9fff":
        py = _pinyin_dict().get(ch)
        return "cjk-" + (py[0] if py else "x")
    return "other"


def encode_shards(entries) -> dict:
    """P2：按首字母 A-Z/数字/CJK 拼音首字母分桶，再按原始字节切成 ~1.1 MB 的分片。

    每个分片是 index.json 同构的条目数组（客户端可直接渲染）；manifest 记录每片
    first/last 便于按查询前缀只取相交的 1-3 片；core.json 保留为一次加载的完整回退。
    """
    idx_dir = OUT / "data" / "idx"
    core_path = idx_dir / "core.json"
    buckets: dict[str, list] = {}
    for e in entries:
        buckets.setdefault(_shard_bucket(e["k"]), []).append(e)
    # v0.9.9 task-14：分片版本号跟 BUILD_V 走（客户端只拿它拼 ?v=，不解析内容），
    # 不用 time.time()，否则 manifest.json 每次构建都变。
    manifest = {"v": BUILD_V, "n": len(entries), "buckets": {},
                "cjkInitials": {},
                "core": {"f": "data/idx/core.json", "bytes": core_path.stat().st_size}}
    target = 1_100_000  # 原始字节/片（gzip 后约 150-220 KB）
    total_bytes = total_shards = 0
    for bucket in sorted(buckets):
        rows = sorted(buckets[bucket], key=lambda e: e["k"])
        sizes = [len(json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                 for e in rows]
        groups, cur, acc = [], [], 0
        for i, e in enumerate(rows):
            cur.append(e)
            acc += sizes[i] + 1
            if acc >= target:
                groups.append(cur)
                cur, acc = [], 0
        if cur:
            groups.append(cur)
        files = []
        for si, grp in enumerate(groups):
            fn = f"shard-{bucket}-{si}.json"
            data = json.dumps(grp, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            (idx_dir / fn).write_bytes(data)
            files.append({"f": "data/idx/" + fn, "first": grp[0]["k"], "last": grp[-1]["k"],
                          "n": len(grp), "bytes": len(data)})
            total_bytes += len(data)
            total_shards += 1
        manifest["buckets"][bucket] = files
        if bucket.startswith("cjk-"):
            for e in rows:
                manifest["cjkInitials"].setdefault(e["k"][0], bucket)
    manifest["shardCount"] = total_shards
    manifest["shardBytes"] = total_bytes
    return manifest


def main() -> None:
    global BUILD_V
    # task-14：版本号由输入内容决定（不是时间），必须在写任何产物之前定下来。
    BUILD_V = _compute_build_v()
    print(f"build version: {BUILD_V} (content hash)", flush=True)
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    # v0.11.5 task-5：CSS 文件名就是内容哈希，写盘前自检一次 ——
    # 防以后在 main() 里改 CSS 常量而文件名没跟着变（文件名与内容不一致会让缓存永远命中旧样式）。
    # 注意必须用 write_bytes：Windows 下 write_text 会把 \n 翻成 \r\n，文件名哈希就对不上实际字节。
    _css_bytes = CSS.encode("utf-8")
    _css_check = "assets/style." + hashlib.sha256(_css_bytes).hexdigest()[:10] + ".css"
    if _css_check != CSS_FILE:
        raise SystemExit(f"CSS 文件名与内容哈希不一致：{CSS_FILE} != {_css_check}")
    (OUT / "assets" / CSS_FILE.split("/")[-1]).write_bytes(_css_bytes)
    # 兼容旧缓存/旧引用：稳定名保留（内容可变）；新页面只引用上面的哈希文件。
    (OUT / "assets" / "style.css").write_bytes(_css_bytes)
    # v0.9.8 task-13：长尾页（121k）用 boot.js 注入与顶层页同一份壳；顶层页已有
    # [data-shell] 直接跳过（幂等）。模板里 __R__ 是站点根前缀占位。
    shell_nav_js = json.dumps(_shell_nav_html("__R__")
                               + _shell_right("__R__", "".join(
                                   f'<a data-lang="{code}" href="?lang={code}">{label}</a>'
                                   for code, label, _ in LANGS)))
    shell_tab_js = json.dumps(_shell_tabbar("__R__"))
    # v0.11.2（条目 26）：长尾页的常驻搜索栏也由 boot.js 注入（每页静态 0 B）。
    shell_search_js = json.dumps(_shell_search_html("__R__"))
    boot_js_src = (
        # v0.10.2：长尾页只拉当前语言的字典包。语言判定必须在插入 <script> 之前完成，
        # 所以 boot.js 里带一份 LANG_META_JS + LANG_PICK_JS（与 assets/i18n.js 同一段源码）。
        LANG_META_JS + LANG_PICK_JS +
        "var s=document.currentScript;"
        # v0.11.5 task-5：文件名改成 assets/boot.<hash>.js，剥「站点根」的正则要匹配任意 boot.*.js
        "var r=((s&&s.src)||location.href).replace(/assets\\/boot\\.[^\\/]*$/,'');"
        "var _rp='/';try{_rp=new URL(r).pathname||'/';}catch(e){}"
        "var LK=__dshPickLang(_rp);"
        "var SN=" + shell_nav_js + ",TB=" + shell_tab_js + ",HS=" + shell_search_js + ";"
        ";(function(){var h=document.querySelector('header');"
        "if(!h||h.querySelector('[data-shell]'))return;"
        "h.className=(h.className?h.className+' ':'')+'hdr-shell';"
        "var html=SN.replace(/__R__/g,r),nav=h.querySelector('nav'),w=h.querySelector('.wrap');"
        "if(nav){nav.outerHTML=html;}else if(w){w.insertAdjacentHTML('beforeend',html);}"
        # v0.11.2（条目 26）：常驻搜索栏只给「成分页 / 商品名页」这类可续查的内容页
        # （drug/name/combo/maker）。ATC/覆盖/关于等顶层页不加，避免把首屏内容压下去
        # （390 下多一行 57px 会让 atc/R06A 首屏条目少 1 条）。
        # 注意用 location.pathname 判断页面类型：_rp 是「站点根」的 pathname（boot.js 自己
        # 在 assets/ 下，r 去掉文件名后是根），在 /drug/ 页上它永远是 "/"。
        "if(!h.querySelector('.hsearch-row')&&/\\/(drug|name|combo|maker)\\//.test(location.pathname))"
        "{h.insertAdjacentHTML('beforeend',HS.replace(/__R__/g,r));}"
        "var box=document.createElement('div');box.innerHTML=TB.replace(/__R__/g,r);"
        "while(box.firstChild){document.body.appendChild(box.firstChild);}"
        "var p=location.pathname,t=document.querySelector('.tabbar');if(!t)return;"
        "var key=(p.indexOf('/atc')>=0||p.indexOf('/cat/')>=0)?'categories':"
        "p.indexOf('coverage')>=0?'coverage':"
        "((p.indexOf('/about')>=0||p.indexOf('warn')>=0||p.indexOf('glossary')>=0||"
        "p.indexOf('confused')>=0||p.indexOf('whats-new')>=0)?'about':'search');"
        "var as=t.querySelectorAll('a');"
        "for(var i=0;i<as.length;i++){var href=as[i].getAttribute('href')||'';"
        "var k=href.indexOf('atc')>=0?'categories':href.indexOf('coverage')>=0?'coverage':"
        "href.indexOf('about')>=0?'about':'search';"
        "if(k===key){as[i].className='on';as[i].setAttribute('aria-current','page');}}"
        "})();"
        + _coverage_entry_js("r")
        # v0.10.2：单语包缺失（老构建 / 网络抖动 / 语言码异常）时回落到四语全量 i18n.js，
        # 与 v0.10.1 的行为一致，不会出现「页面整片英文、语言链接失效」。
        + "window.addEventListener('load',function(){"
        "var a=document.createElement('script');"
        "a.src=r+'assets/i18n.'+LK+'.js?v=__BUILD_V__';"
        "a.onerror=function(){var f=document.createElement('script');"
        "f.src=r+'assets/i18n.js?v=__BUILD_V__';document.body.appendChild(f);};"
        "a.onload=function(){var b=document.createElement('script');"
        # v0.11.5 task-8：bilingual.js 同 app.js 一样是稳定名 + 内容随 BUILD_V 变，带 ?v 防旧缓存
        "b.src=r+'assets/bilingual.js?v=__BUILD_V__';document.body.appendChild(b);};"
        "document.body.appendChild(a);});\n")
    boot_js = boot_js_src.replace("__BUILD_V__", BUILD_V)
    # v0.11.5 task-5：boot.js 也改「内容哈希文件名 + 不带 ?v=」，同一构建内全站同一 URL、可跨页缓存；
    # 数据只变时字节不变 → 页面 HTML 也不用跟着变（增量构建前提）。
    # 哈希与写盘都按实际字节（write_bytes）：Windows 下 write_text 的 \n → \r\n 会让名字对不上内容。
    global BOOT_JS_FILE
    _boot_bytes = boot_js.encode("utf-8")
    BOOT_JS_FILE = "assets/boot." + hashlib.sha256(_boot_bytes).hexdigest()[:10] + ".js"
    (OUT / "assets" / BOOT_JS_FILE.split("/")[-1]).write_bytes(_boot_bytes)
    # 兼容旧缓存页面（v0.11.4 的 HTML 仍引用 assets/boot.js?v=<旧号>）：留稳定名副本，避免 404。
    (OUT / "assets" / "boot.js").write_bytes(_boot_bytes)
    # task-145b：ATC4 页折叠区的懒加载脚本（只被 atc/<CODE>.html 引用，版本参数同 BUILD_V）。
    (OUT / "assets" / "atc4.js").write_text(
        ATC4_JS.replace("__BUILD_V__", BUILD_V), encoding="utf-8")
    def _render_i18n_js(langs: list[str] | None = None) -> str:
        """渲染 i18n 脚本（v0.10.2：按语言拆包）。

        langs=None  → `assets/i18n.js`：四语全量字典 + 逻辑（404 页、老缓存页、单语包回落用）。
        langs=['zh'] → `assets/i18n.<lang>.js`：只含该语言字典的独立包，长尾页只拉这一份
                       （四语全量 165,747 B raw / 59,129 B gz → 单语 ≈50 KB raw / ≈14 KB gz）。

        单语包里把「该语言缺的键」预先算成 `window.I18N_FALLBACK`（zh-Hant 先回退简体，再回退
        英文），所以 T() 的回落顺序与四语全量文件一致，不需要为了缺键再下整包。
        """
        if langs:
            keep = {c: I18N[c] for c in langs if c in I18N} or {"en": I18N["en"]}
            fallback: dict[str, str] = {}
            for code, table in keep.items():
                for src in (("zh", "en") if code == "zh-Hant" else ("en",)):
                    if src == code or src not in I18N:
                        continue
                    for k, v in I18N[src].items():
                        if k not in table and k not in fallback:
                            fallback[k] = v
            head = ("window.I18N=" + json.dumps(keep, ensure_ascii=False,
                                                separators=(",", ":")) + ";\n")
            if fallback:
                head += ("window.I18N_FALLBACK=" + json.dumps(fallback, ensure_ascii=False,
                                                              separators=(",", ":")) + ";\n")
        else:
            # v0.10.1：紧凑分隔符（非首页的每页都会加载这份外部 i18n.js，省 ~4 KB）
            # v0.11.4：只导出启用的四语（fr 关闭时不得因 I18N["fr"] 存在而膨胀全量包）。
            enabled = {c: I18N[c] for c in I18N_REQUIRED_LANGS if c in I18N}
            head = ("window.I18N=" + json.dumps(enabled, ensure_ascii=False,
                                                separators=(",", ":")) + ";\n")
        return (head + LANG_META_JS + "\n" + LANG_PICK_JS + "\n" + r"""
(function(){
  var D = window.I18N;
  // 站点根路径：i18n.js 在 <head> 同步执行，currentScript 可用。
  // GitHub Pages 是项目子路径（/drug-brand-crossref/），不能假设语言目录在域名根。
  var scriptEl = document.currentScript;
  // v0.10.2：两种文件名都要能剥出站点根——四语全量 assets/i18n.js 与单语 assets/i18n.<lang>.js，
  // 否则 ROOT 会带上文件名，langTarget() 拼出来的语言链接就 404（v0.9.7 task-10 的同类坑）。
  var ROOT = window.__DSH_I18N_ROOT || ((scriptEl && scriptEl.src) || location.href).replace(/assets\/i18n(?:\.[A-Za-z-]+)?\.js.*$/, '');
  var rootPath = '/';
  try{ rootPath = new URL(ROOT).pathname || '/'; }catch(e){}
  // v0.10.2：语言判定（canon/pick/relPath）统一由 LANG_PICK_JS 提供，与 boot.js 里插入
  // 字典包之前用的是同一段源码，避免「boot 挑 zh、i18n 算 en」这种两处分叉。
  function relPath(){ return __dshRelPath(rootPath); }
  function canon(x){ return __dshCanonLang(x); }
  function pick(){ return __dshPickLang(rootPath); }
  window.LANG = pick();
  // v0.10.1/v0.10.2：首页为压首屏体积只内联了本页语言字典（window.__I18N_PARTIAL）。
  // 若 ?lang= / localStorage / 路径指定的语言不在内联字典里，只补载那一份
  // assets/i18n.<lang>.js（≈14 KB gz；v0.10.1 是补四语全量 59 KB gz）；
  // 单语包拉不到（老缓存 / 离线）再回落到四语全量 assets/i18n.js。
  if(window.__I18N_PARTIAL && !D[window.LANG]){
    var oneI18n = document.createElement('script');
    oneI18n.src = ROOT + 'assets/i18n.' + encodeURIComponent(window.LANG) + '.js?v=__BUILD_V__';
    oneI18n.onerror = function(){
      var fullI18n = document.createElement('script');
      fullI18n.src = ROOT + 'assets/i18n.js?v=__BUILD_V__';
      document.head.appendChild(fullI18n);
    };
    document.head.appendChild(oneI18n);
  }
  window.T = function(k){
    var L = D[window.LANG];
    var v = L ? L[k] : undefined;
    // v0.6.2：繁体字典缺键时回退简体（再回退英文），避免出现空文本
    if(v === undefined && window.LANG === 'zh-Hant' && D.zh) v = D.zh[k];
    // v0.10.2：单语包把缺键的 en/zh 值预置在 I18N_FALLBACK；D.en 在单语包里不存在，要判空
    if(v === undefined && window.I18N_FALLBACK) v = window.I18N_FALLBACK[k];
    if(v === undefined && D.en) v = D.en[k];
    return v === undefined ? k : v;
  };
  function nameLangBadge(nl, hasZh){
    var L = window.LANG || 'en';
    if(nl === 'zh' && (L === 'en' || L === 'es')){
      return window.T(L === 'en' ? 'name.no_en' : 'name.no_es');
    }
    if(nl && nl !== 'zh' && (L === 'zh' || L === 'zh-Hant') && hasZh !== true){
      return window.T(L === 'zh' ? 'name.no_zh' : 'name.no_zh_hant');
    }
    return '';
  }
  function applyNameLangBadges(){
    document.querySelectorAll('.nolang-badge').forEach(function(n){ n.remove(); });
    function badgeFor(text){
      var cjk = /[\u3400-\u9fff]/.test(text || '');
      if(cjk && (window.LANG === 'en' || window.LANG === 'es')){
        return window.T(window.LANG === 'en' ? 'name.no_en' : 'name.no_es');
      }
      if(!cjk && (window.LANG === 'zh' || window.LANG === 'zh-Hant')){
        return window.T(window.LANG === 'zh' ? 'name.no_zh' : 'name.no_zh_hant');
      }
      return '';
    }
    document.querySelectorAll('.nm, .card h2 a, [data-i18n-label="maker.ingredient"]').forEach(function(el){
      // v0.11.6 task-1（T12 C1）：「无中文名」徽标只属于**名称**。服务端在「成分自己有
      // inn_zh」的元素上打了 data-zh="1"（品牌页成分卡 / 配方差异表，与成分页同一映射），
      // 这里一律不再贴徽标 —— 用户评审看到的就是「Acetaminophen 旁边写着无中文名」。
      if(el.getAttribute('data-zh') === '1') return;
      var text = badgeFor(el.textContent || '');
      if(!text) return;
      var s = document.createElement('span');
      s.className = 'st-badge st-unknown nolang-badge';
      s.textContent = text;
      el.appendChild(s);
    });
    document.querySelectorAll('[data-nl]').forEach(function(el){
      var text = nameLangBadge(el.getAttribute('data-nl'),
                               el.getAttribute('data-zh') === '1');
      if(!text) return;
      var host = el;
      if(el.closest && el.closest('h1')) host = document.querySelector('.drug-name-src');
      if(!host) return;
      var s = document.createElement('span');
      s.className = 'st-badge st-unknown nolang-badge';
      s.textContent = text;
      host.appendChild(s);
    });
  }
  // v0.10.2 task-3：ATC/大类页「缺当前语言名」每行只标一次，且标在链接之外
  //（盐型在 .salt-row 里，不再逐个标）。必须晚于 applyNameLangBadges()（先铺非 ATC 场景）。
  // 2026-11-11 Batch 2：只有「这一行完全没有中文名」时才标。行里已经有任一中文名（主名或
  // 盐型）时，读者并不会缺信息，再标一次就是噪音（用户报的「极大的可读性」里有一半是它）。
  // v0.11.1 2b：再加一层按页阈值 —— 构建期算好 data-nolang-mute（该语言缺名比例 ≥50%），
  // 整页不逐行挂徽章，只在页级 atc.nolang_note 说一句。前端只读这个属性，不再自己判断比例。
  function markAtcRowGaps(){
    document.querySelectorAll('.atcmembers li').forEach(function(li){
      li.querySelectorAll('.nolang-badge').forEach(function(n){ n.remove(); });
      var ul = li.closest ? li.closest('.atcmembers') : null;
      var mute = ul ? (ul.getAttribute('data-nolang-mute') || '') : '';
      var L = window.LANG;
      if(mute && (' ' + mute + ' ').indexOf(' ' + L + ' ') >= 0) return;  // 整页缺名是常态
      var nm = li.querySelector('.nm');          // 只取主名；盐型不再单独标
      if(!nm) return;
      var hasZh = !!li.querySelector('.nm[data-n-zh]:not([data-n-zh=""])');
      var cjk = /[\u3400-\u9fff]/.test(nm.textContent || '');
      var key = '';
      if(cjk && (L === 'en' || L === 'es')) key = (L === 'en' ? 'name.no_en' : 'name.no_es');
      else if(!cjk && (L === 'zh' || L === 'zh-Hant')){
        if(hasZh) return;                        // 行里已有中文名 → 不标
        key = (L === 'zh' ? 'name.no_zh' : 'name.no_zh_hant');
      }
      if(!key) return;
      var s = document.createElement('span');
      s.className = 'st-badge st-unknown nolang-badge';
      s.textContent = window.T(key);
      var host = (nm.closest && nm.closest('a')) || nm;   // 徽章放链接之后，不污染链接文本
      host.parentNode.insertBefore(s, host.nextSibling);
    });
  }
  // v0.11.4 task-63：成分名的中文名（inn_zh）只在中文/繁体界面显示。
  // 服务端只在「该成分真有中文名」时才渲染 [data-inn-zh]（不硬翻），这里按界面语言开关。
  // 用 inline style 而不是只靠 [hidden] —— 作者样例会打败 [hidden]（v0.11.2 踩过这个坑）。
  function applyInnZh(){
    var L = window.LANG || 'en';
    var on = (L === 'zh' || L === 'zh-Hant');
    document.querySelectorAll('[data-inn-zh]').forEach(function(el){
      el.style.display = on ? 'inline' : 'none';
      el.hidden = !on;
    });
  }
  function apply(){
    document.documentElement.lang = window.LANG;
    document.querySelectorAll('[data-i18n]').forEach(function(el){ el.textContent = window.T(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach(function(el){ el.setAttribute('aria-label', window.T(el.dataset.i18nAria)); });
    // T13 / D3：「展示 X 个，共 Y 个」这类**带数字**的短句走轻量模板（省掉四语块体积）：
    // 数字放在 data-shown / data-total 上，只换句子模板；筛选后由 initListView/initListFilters
    // 更新 data-shown 并重跑这里，所以切语言与筛选互不打架。
    document.querySelectorAll('[data-i18n-tpl]').forEach(function(el){
      var t = window.T(el.dataset.i18nTpl);
      el.textContent = String(t)
        .replace('{shown}', el.getAttribute('data-shown') || '')
        .replace('{n}', el.getAttribute('data-total') || '');
    });
    // v0.5.5：<title> / description / OG 本地化（根页 head 带 data-i18n-title/meta）
    document.querySelectorAll('[data-i18n-title]').forEach(function(el){
      var t = window.T(el.dataset.i18nTitle);
      el.textContent = t;
      if(el.tagName === 'TITLE') document.title = t;
    });
    document.querySelectorAll('[data-i18n-meta]').forEach(function(el){
      el.setAttribute('content', window.T(el.dataset.i18nMeta));
    });
    // i18n P1：About / What's new / Confused / 404 的正文块允许内嵌链接与表格，
    // 用 data-i18n-html 走 innerHTML（内容全部来自构建期字典，非用户输入）。
    document.querySelectorAll('[data-i18n-html]').forEach(function(el){ el.innerHTML = window.T(el.dataset.i18nHtml); });
    // v0.5.4：移动端卡片列名（CSS content:attr(data-label)）也随语言切换（厂家页等）。
    document.querySelectorAll('[data-i18n-label]').forEach(function(el){
      el.setAttribute('data-label', window.T(el.dataset.i18nLabel));
    });
    // /warn 与成分页的警示正文是数据行（zh/en/es 各一份），按当前语言只显示对应块。
    document.querySelectorAll('[data-lang-block]').forEach(function(el){
      var on = (el.dataset.langBlock === window.LANG);
      var inline = el.getAttribute('data-lang-inline') === '1';
      el.style.display = on ? (inline ? 'inline' : 'block') : 'none';
    });
    // v0.6.6：成分页多国矩阵按界面语言排序列（服务端默认 en 序：US/GB/CA/AU/CN/ES/MX）。
    // v0.6.6/v0.7.0/v0.7.x：语言列序（含 TW/SG：zh → CN,TW,SG；zh-Hant → TW,CN,HK,SG；es → ES,MX…）
    var MORDER = {en: ['US','GB','CA','AU','SG','CN','ES','MX','TW','HK','EU'],
                  es: ['ES','MX','US','GB','CA','AU','SG','CN','TW','HK','EU'],
                  zh: ['CN','TW','HK','SG','US','GB','CA','AU','ES','MX','EU'],
                  'zh-Hant': ['TW','CN','HK','SG','US','GB','CA','AU','ES','MX','EU']};
    var morder = MORDER[window.LANG] || MORDER.en;
    window.COUNTRY_ORDER = morder;   // app.js 用它给国家 chips 排序
    document.querySelectorAll('table.matrix').forEach(function(tb){
      var rank = {};
      for(var i = 0; i < morder.length; i++) rank[morder[i]] = i;
      Array.prototype.forEach.call(tb.querySelectorAll('tr'), function(tr){
        var cells = Array.prototype.slice.call(tr.children);
        cells.sort(function(a, b){
          var ca = a.getAttribute('data-country'), cb = b.getAttribute('data-country');
          if(!ca && !cb) return 0;
          if(!ca) return -1;
          if(!cb) return 1;
          var ra = (rank[ca] === undefined) ? 99 : rank[ca];
          var rb = (rank[cb] === undefined) ? 99 : rank[cb];
          return ra - rb;
        });
        for(var c = 0; c < cells.length; c++) tr.appendChild(cells[c]);
      });
    });
    // v0.7.0：国家下拉按界面语言排序（TW 已接入；「All countries」保持第一项）
    var selC = document.getElementById('country');
    if(selC){
      var rankC = {};
      for(var ci = 0; ci < morder.length; ci++) rankC[morder[ci]] = ci;
      var opts = Array.prototype.slice.call(selC.querySelectorAll('option[value]'))
        .filter(function(o){ return !!o.getAttribute('value'); });
      opts.sort(function(a, b){
        var ra = (rankC[a.value] === undefined) ? 99 : rankC[a.value];
        var rb = (rankC[b.value] === undefined) ? 99 : rankC[b.value];
        return ra - rb;
      });
      opts.forEach(function(o){ selC.appendChild(o); });
    }
    document.querySelectorAll('[data-ph]').forEach(function(el){ el.placeholder = window.T(el.dataset.ph); });
    // v0.10.0: language label + aria-current follow the active language (dropdown + mobile menu)
    var LBL = {en:'EN', es:'ES', zh:'\u4e2d\u6587', 'zh-Hant':'\u7e41'};
    document.querySelectorAll('.langs a, .lang-menu a').forEach(function(a){
      var on = a.dataset.lang === window.LANG;
      a.classList.toggle('on', on);
      if(on){ a.setAttribute('aria-current', 'true'); } else { a.removeAttribute('aria-current'); }
    });
    document.querySelectorAll('.langdd .lname').forEach(function(n){
      if(LBL[window.LANG]) n.textContent = LBL[window.LANG];
    });
    // v0.8.2 task-120：语言确定后再渲染 ATC/组合页成分名（避免 defer 早于 ?lang 解析）
    if(window.renderBilingualNames) window.renderBilingualNames();
    // v0.9.4：name_lang 无译名角标（不翻译；H1 角标放来源行）
    applyNameLangBadges();
    // v0.11.4 task-63：中文/繁体界面补显示成分中文名（inn_zh），其余语言隐藏
    applyInnZh();
    // v0.10.2：ATC/大类页收口——每行最多一枚标签，且不进链接文本
    markAtcRowGaps();
    // v0.10.3 task-16：成分页清单视图（?view=table 切矩阵、剂型 chips 过滤、语言市场置顶）
    initListView();
    // T13 / D1（v0.11.7）：成分页清单的「市场 / 单方·复方 / 规格」筛选（渐进增强）
    initListFilters();
    // T13 / D4、D7：分类页页内搜索 + 子类筛选；结果行/身份卡补「数据截止」
    initCatFinder();
    initSourceMeta();
    // 2026-11-11 UI：apply() 末尾跑一次注册钩子。首页用它把「只看 XX」的国家名回填到
    // 国家/地区 details 的 summary 上（apply() 会先按 data-i18n 把 summary 重置成基础文案，
    // 而 ?lang= 补载语言包会在 load 之后再跑一次 apply()）。
    if(window.__DSH_APPLY_HOOKS){
      for(var hi = 0; hi < window.__DSH_APPLY_HOOKS.length; hi++){
        try{ window.__DSH_APPLY_HOOKS[hi](); }catch(e){}
      }
    }
  }
  // ── v0.10.3 task-16：成分页「按国家分组清单」的渐进增强 ────────────────────
  // 服务器已经渲染好清单（默认可见）与可选的矩阵（hidden）；这里只做三件事：
  //   ① ?view=table → 显示矩阵、隐藏清单（无 JS 时矩阵 hidden，清单照常可读）；
  //   ② 当前语言市场那一块置顶（服务器按记录数排，语言偏好只有浏览器知道）；
  //   ③ 剂型 chips 过滤（无 JS 时是纯锚点，行全部可见）。
  function initListView(){
    var list = document.getElementById('list');
    var table = document.getElementById('tableview');
    if(!list) return;
    var params = new URLSearchParams(location.search);
    if(table && params.get('view') === 'table'){
      table.hidden = false;
      list.hidden = true;
    }
    // ② 语言市场置顶
    var blocks = document.querySelector('.mkblocks');
    if(blocks){
      var prefer = {en:'US', es:'ES', zh:'CN', 'zh-Hant':'TW'}[window.LANG] || '';
      var first = prefer ? blocks.querySelector('.mkblock[data-mk="' + prefer + '"]') : null;
      if(first && first !== blocks.firstElementChild) blocks.insertBefore(first, blocks.firstElementChild);
    }
    // ③ 剂型 chips
    // 2026-11-11 P1（用户实测：点了 powder 列表没变）：
    //   ① `row.hidden = true` 对 `.mkrow{display:grid}` 无效 —— 作者样式的优先级高于
    //      UA 的 `[hidden]{display:none}`，而且全站没有兜底规则。CSS 已加
    //      `.mkrow[hidden]{display:none}` 与 `[hidden]{display:none!important}`；
    //   ② 块头「N 条记录 · 4 个规格」是服务端数字，筛完还得跟着变，否则数字骗人。
    var chips = document.querySelectorAll('[data-form-filter]');
    var rows = document.querySelectorAll('.mkrow');
    var blocksAll = document.querySelectorAll('.mkblock');
    function applyFormFilter(want){
      rows.forEach(function(row){
        row.hidden = !!(want && row.getAttribute('data-form') !== want);
      });
      blocksAll.forEach(function(bk){
        var all = bk.querySelectorAll('.mkrow');
        var shown = 0;
        all.forEach(function(r){ if(!r.hidden) shown++; });
        bk.hidden = (want !== '' && all.length > 0 && shown === 0);
        // 规格计数：没筛时就是原样「4 strengths」，筛后变「1 / 4 strengths」
        //（数字是语言无关的；「strengths / 个规格 / presentaciones」仍由 data-i18n 翻译）
        var n = bk.querySelector('.mkspec');
        if(n && window.T){
          // T13 / D3：块头是「展示 X 个，共 Y 个」（模板在 data-i18n-tpl，数字在 data-*）；
          // 筛完把 data-shown 与文本一起更新，切语言时 apply() 会按新数字重渲染同一模板。
          n.setAttribute('data-shown', String(shown));
          var tpl = window.T(n.getAttribute('data-i18n-tpl') || 'drug.spec_count');
          n.textContent = String(tpl).replace('{shown}', String(shown))
            .replace('{n}', n.getAttribute('data-total') || '');
        }
      });
    }
    // v0.11.4 task-63（用户截图）：剂型 chips 的标签原来是服务端写死的英文
    // （`All dosage forms` / `liquid 107` …），简中/繁中/西语界面也跟着显示英文，
    // 而旁边的「剂型」按钮却是中文。这里按 data-form-filter 的剂型码取字典值，
    // 只改**标签文本节点**（`.n` 里的计数不动）：静态 HTML 保持英文（无 JS 兜底、
    // 体积 0 增量），切换语言时 apply() 会重跑 initListView() → 即时换成当前语言。
    function labelChips(){
      if(!window.T) return;
      var nav = document.getElementById('forms');
      if(nav) nav.setAttribute('aria-label', window.T('drug.forms_label'));
      chips.forEach(function(chip){
        var k = chip.getAttribute('data-form-filter') || '';
        var key = k ? (k === 'other' ? 'atc4.form_other' : 'form.' + k) : 'drug.forms_all';
        var v = window.T(key);
        if(!v || v === key) return;          // 字典缺这个键 → 保留服务端英文，不渲染 key 字面量
        for(var i = 0; i < chip.childNodes.length; i++){
          var nd = chip.childNodes[i];
          if(nd.nodeType === 3 && (nd.nodeValue || '').trim()){
            nd.nodeValue = v + ' ';
            break;
          }
        }
      });
    }
    labelChips();
    chips.forEach(function(chip){
      chip.addEventListener('click', function(ev){
        var want = chip.getAttribute('data-form-filter') || '';
        chips.forEach(function(c){ c.classList.toggle('on', c === chip); });
        applyFormFilter(want);
        ev.preventDefault();
        var anchor = document.getElementById('list');
        if(anchor && anchor.scrollIntoView) anchor.scrollIntoView({block: 'start'});
      });
    });
    // 切语言会重跑 apply()（重写 data-i18n 文本 + 按当前语言重写 chips 标签），
    // 计数按当前筛选状态重算一次
    (window.__DSH_APPLY_HOOKS = window.__DSH_APPLY_HOOKS || []).push(function(){
      labelChips();
      if(!document.querySelector('.mkrow')) return;
      var on = document.querySelector('[data-form-filter].on');
      var want = on ? (on.getAttribute('data-form-filter') || '') : '';
      applyFormFilter(want);
    });
    // 跨市场锚点：跳到对应国家块并高亮一次
    document.querySelectorAll('.mkx a[href^="#mk-"], .mkx-more a[href^="#mk-"]').forEach(function(a){
      a.addEventListener('click', function(){
        var t = document.querySelector(a.getAttribute('href'));
        if(!t) return;
        t.classList.remove('mkflash');
        void t.offsetWidth;
        t.classList.add('mkflash');
      });
    });
  }
  // ── T13 / D1（v0.11.7）：成分页清单的「市场 / 单方·复方 / 规格」筛选 ──────────
  // 服务端已把清单渲染完整（无 JS 全可见，市场 chip 本身是锚点）；这里只做渐进增强：
  //   ① 点市场 chip → 只显示该国家块（`?mk=CN` / `#mk-CN` 分享同一状态）；
  //   ② 单方 / 复方切换（读 `.mkrow[data-combo]`）；
  //   ③ 规格搜索框（子串匹配 `.mkrow[data-spec]`，逗号/空格归一）。
  // 与 `.formchips` 的剂型过滤**组合**生效：剂型选中态由 initListView() 维护，这里只读。
  function initListFilters(){
    var box = document.getElementById('listfilters');
    if(!box) return;
    var rows = Array.prototype.slice.call(document.querySelectorAll('.mkrow'));
    if(!rows.length) return;
    var blocks = Array.prototype.slice.call(document.querySelectorAll('.mkblock'));
    var mkChips = Array.prototype.slice.call(box.querySelectorAll('[data-mk-filter]'));
    var segChips = Array.prototype.slice.call(box.querySelectorAll('[data-seg-filter]'));
    var specInp = document.getElementById('lf-spec');
    var status = document.getElementById('lf-status');
    var noneP = document.getElementById('lf-none');
    var state = {mk: '', seg: '', q: ''};
    function norm(s){ return String(s || '').toLowerCase().replace(/\s+/g, ' ').trim(); }
    function formWant(){
      var on = document.querySelector('[data-form-filter].on');
      return on ? (on.getAttribute('data-form-filter') || '') : '';
    }
    function sync(){
      var wantForm = formWant();
      var shown = 0;
      rows.forEach(function(r){
        var mkOk = !state.mk || r.getAttribute('data-mk') === state.mk;
        var segOk = !state.seg
          || r.getAttribute('data-combo') === (state.seg === 'combo' ? '1' : '0');
        var formOk = !wantForm || r.getAttribute('data-form') === wantForm;
        var qOk = !state.q || norm(r.getAttribute('data-spec')).indexOf(state.q) >= 0;
        r.hidden = !(mkOk && segOk && formOk && qOk);
        if(!r.hidden) shown++;
      });
      blocks.forEach(function(bk){
        var all = bk.querySelectorAll('.mkrow');
        var vis = 0;
        all.forEach(function(r){ if(!r.hidden) vis++; });
        bk.hidden = all.length > 0 && vis === 0;
        var n = bk.querySelector('.mkspec');
        if(n && window.T){
          n.setAttribute('data-shown', String(vis));
          var tpl2 = window.T(n.getAttribute('data-i18n-tpl') || 'drug.spec_count');
          n.textContent = String(tpl2).replace('{shown}', String(vis))
            .replace('{n}', n.getAttribute('data-total') || '');
        }
      });
      if(status && window.T){
        status.textContent = window.T('lf.count')
          .replace('{shown}', String(shown)).replace('{total}', String(rows.length));
      }
      if(noneP) noneP.hidden = shown > 0;
    }
    function pick(list, chip){
      list.forEach(function(c){ c.classList.toggle('on', c === chip); });
    }
    // 手机（≤767px）默认收起筛选条，首屏不多出一大块；桌面端常显（CSS 隐藏 summary）。
    if(box.tagName === 'DETAILS' && window.innerWidth < 768) box.open = false;
    mkChips.forEach(function(chip){
      chip.addEventListener('click', function(ev){
        ev.preventDefault();
        state.mk = chip.getAttribute('data-mk-filter') || '';
        pick(mkChips, chip);
        sync();
        var t = state.mk ? document.getElementById('mk-' + state.mk) : null;
        if(t && t.scrollIntoView) t.scrollIntoView({block: 'start'});
      });
    });
    segChips.forEach(function(chip){
      chip.addEventListener('click', function(ev){
        ev.preventDefault();
        state.seg = chip.getAttribute('data-seg-filter') || '';
        pick(segChips, chip);
        sync();
      });
    });
    if(specInp){
      var tmr = null;
      specInp.addEventListener('input', function(){
        clearTimeout(tmr);
        tmr = setTimeout(function(){ state.q = norm(specInp.value); sync(); }, 120);
      });
    }
    try{
      var params = new URLSearchParams(location.search);
      var mk0 = params.get('mk')
        || (location.hash.indexOf('#mk-') === 0 ? location.hash.slice(4) : '');
      if(mk0){
        var chip0 = box.querySelector('[data-mk-filter="' + mk0 + '"]');
        if(chip0){ state.mk = mk0; pick(mkChips, chip0); }
      }
    }catch(e){}
    sync();
    (window.__DSH_APPLY_HOOKS = window.__DSH_APPLY_HOOKS || []).push(function(){
      // 语言切换后重算状态行（data-i18n 会重写其他文本，但计数带占位符，由这里算）
      if(!window.T) return;
      var vis = rows.filter(function(r){ return !r.hidden; }).length;
      if(status) status.textContent = window.T('lf.count')
        .replace('{shown}', String(vis)).replace('{total}', String(rows.length));
    });
  }
  // ── T13 / D4（v0.11.7）：分类页页内搜索 + 子类筛选 ────────────────────────
  // 服务端已渲染完整列表（无 JS 全可见）；这里按「名字子串 + ATC 前 4 位」隐藏条目，
  // 命中若落在折叠区（`<details class="atcdetails">`）就自动展开，避免「明明有却不显示」。
  function initCatFinder(){
    var box = document.getElementById('catfinder');
    if(!box) return;
    var lists = Array.prototype.slice.call(document.querySelectorAll('ul.atcmembers'));
    if(!lists.length) return;
    var items = [];
    lists.forEach(function(ul){
      Array.prototype.slice.call(ul.children).forEach(function(li){ items.push(li); });
    });
    var inp = document.getElementById('catq');
    var chips = Array.prototype.slice.call(box.querySelectorAll('[data-sub-filter]'));
    var status = document.getElementById('cf-status');
    var noneP = document.getElementById('cf-none');
    var state = {q: '', sub: ''};
    function norm(s){ return String(s || '').toLowerCase().replace(/\s+/g, ''); }
    function codesOf(li){
      return Array.prototype.map.call(li.querySelectorAll('.atc-codes code'), function(c){
        return String(c.textContent || '').toUpperCase();
      });
    }
    function sync(){
      var shown = 0;
      items.forEach(function(li){
        var nm = li.querySelector('.atc-nm');
        var txt = norm(nm ? nm.textContent : li.textContent);
        var qOk = !state.q || txt.indexOf(state.q) >= 0;
        var cOk = !state.sub || codesOf(li).some(function(c){ return c.indexOf(state.sub) === 0; });
        li.hidden = !(qOk && cOk);
        if(!li.hidden) shown++;
      });
      lists.forEach(function(ul){
        var vis = 0;
        Array.prototype.forEach.call(ul.children, function(li){ if(!li.hidden) vis++; });
        ul.hidden = vis === 0;
        var d = (ul.closest ? ul.closest('details') : null);
        if(d && vis > 0 && (state.q || state.sub)) d.open = true;
      });
      if(status && window.T){
        status.textContent = window.T('lf.count')
          .replace('{shown}', String(shown)).replace('{total}', String(items.length));
      }
      if(noneP) noneP.hidden = shown > 0;
    }
    chips.forEach(function(chip){
      chip.addEventListener('click', function(ev){
        ev.preventDefault();
        state.sub = chip.getAttribute('data-sub-filter') || '';
        chips.forEach(function(c){ c.classList.toggle('on', c === chip); });
        sync();
      });
    });
    if(inp){
      var tmr = null;
      inp.addEventListener('input', function(){
        clearTimeout(tmr);
        tmr = setTimeout(function(){ state.q = norm(inp.value); sync(); }, 120);
      });
    }
    sync();
  }
  // ── T13 / D7（v0.11.7）：把「数据截止」带到结果行与身份卡 ────────────────────
  // 结果索引里没有来源日期（不为了这点信息把 core.json 撑大）；这里懒加载一次 1 KB 的
  // `data/sources.json`（国家 → 来源 + 截止日），再用观察器补到已渲染的行上。
  // 交互模型不动（不加控件、不改行结构），T11 重做结果页时可直接删掉这个函数与调用。
  var SRC_META = null, SRC_META_P = null;
  function loadSrcMeta(){
    if(SRC_META_P) return SRC_META_P;
    // 注意：这段在 i18n.js 里执行（不是 app.js），没有 fetchJSON/BASE —— 自己拼前缀。
    var pre = (typeof window.DSH_PREFIX === 'string') ? window.DSH_PREFIX : '';
    SRC_META_P = fetch(pre + 'data/sources.json')
      .then(function(r){ if(!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(d){ SRC_META = (d && d.markets) || {}; return SRC_META; })
      .catch(function(){ SRC_META = {}; return SRC_META; });
    return SRC_META_P;
  }
  function initSourceMeta(){
    // 结果表是**客户端渲染**的（apply() 跑时 #reswrap 还不存在），所以这里不早退：
    // 先拿 1 KB 的 sources.json，再观察整个 body（节流），行一出现就补「数据截止」。
    loadSrcMeta().then(function(meta){
      if(!meta || !Object.keys(meta).length) return;
      var pending = false;
      function asofFor(cs){
        var best = '';
        (cs || []).forEach(function(c){
          var a = (meta[c] || {}).as_of || '';
          // 只要真日期（`live` / `annual` 这类 note 不是日期，不往行里写）
          if(/^\d{4}-\d{2}-\d{2}/.test(a) && a > best) best = a;
        });
        return best;
      }
      function tagsOf(scope){
        return Array.prototype.map.call(scope.querySelectorAll('.tag'), function(t){
          return String(t.textContent || '').trim().toUpperCase();
        });
      }
      function addTo(host, a){
        var sp = document.createElement('span');
        sp.className = 'src-asof';
        sp.textContent = (window.T ? window.T('mkmeta.asof') : 'Data as of') + ' ' + a;
        host.appendChild(document.createTextNode(' '));
        host.appendChild(sp);
      }
      function annotate(){
        pending = false;
        var wrap = document.getElementById('reswrap');
        if(wrap){
          Array.prototype.slice.call(wrap.querySelectorAll('tr.br')).forEach(function(tr){
            if(tr.getAttribute('data-src-asof')) return;
            var cell = tr.querySelector('td.c-market');
            if(!cell) return;
            var a = asofFor(tagsOf(cell));
            tr.setAttribute('data-src-asof', a || '-');
            if(a) addTo(cell, a);
          });
        }
        var idf = document.querySelector('.idcard .idfields');
        if(idf && !idf.getAttribute('data-src-asof')){
          var a2 = asofFor(tagsOf(idf));
          idf.setAttribute('data-src-asof', a2 || '-');
          if(a2) addTo(idf, a2);
        }
      }
      function schedule(){
        if(pending) return;
        pending = true;
        (window.requestAnimationFrame || setTimeout)(annotate);
      }
      annotate();
      if(document.body && window.MutationObserver){
        try{ new MutationObserver(schedule).observe(document.body, {childList: true, subtree: true}); }
        catch(e){}
      }
    });
  }
  function langTarget(code){
    // v0.5.5/v0.6.2：有 /es/、/zh/、/zh-hant/ 静态副本的页面（首页/about/confused/
    // warn/whats-new/glossary/coverage）切到对应语言副本；其它子页面留在原页只换 lang 参数。
    // v0.9.7 task-10：glossary/coverage 也有副本（此前漏列 → 只能落 ?lang= 变体，虽不 404
    // 但 URL 与语言不一致），一并纳入。
    code = canon(code) || DEFAULT_LANG;
    var params = new URLSearchParams(location.search);
    params.delete('lang');
    var m = relPath().match(/(?:^|\/)(index\.html|about\.html|confused\.html|whats-new\.html|warn\.html|glossary\.html|coverage\.html)$/);
    var qs = params.toString();
    if(m){
      return ROOT + (LANG_PATH[code] || '') + m[1]
        + (qs ? '?' + qs : '') + (location.hash || '');
    }
    var landing = /(\/|index\.html)$/.test(location.pathname);
    var path;
    if(landing){ path = ROOT + (LANG_PATH[code] || ''); }
    else { params.set('lang', code); path = location.pathname; qs = params.toString(); }
    return path + (qs ? '?' + qs : '') + (location.hash || '');
  }
  window.setLang = function(l){
    try{ localStorage.setItem('lang', l); }catch(e){}
    location.assign(langTarget(l));
  };
  // 语言切换链接：保留 ?q= / ?country= 等查询参数（原先 ?lang= 会把它们清掉）。
  document.addEventListener('click', function(ev){
    var a = ev.target && ev.target.closest ? ev.target.closest('a[data-lang]') : null;
    if(!a) return;
    if(ev.defaultPrevented || ev.button || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    window.setLang(a.getAttribute('data-lang'));
  });
  if(document.readyState === 'loading'){ document.addEventListener('DOMContentLoaded', apply); }
  else { apply(); }
  window.addEventListener('load', apply);
})();
""").replace("__BUILD_V__", BUILD_V)
    def _write_i18n_assets(announce: bool = False) -> None:
        """写 i18n 资产：四语全量 `assets/i18n.js` + 每语言一份 `assets/i18n.<lang>.js`。

        v0.10.2：12 万长尾页原来每次都拉四语全量（165,747 B raw / 59,129 B gz，占该页首屏
        gz 的 57%），现在 boot.js 先判语言、只拉那一份（≈50 KB raw / ≈14 KB gz）。
        全量文件保留：404 页（路径未知，要按运行时语言挑）、发布前老缓存页面、
        单语包拉不到时的回落都用它。
        """
        (OUT / "assets" / "i18n.js").write_text(_render_i18n_js(), encoding="utf-8")
        for code, _label, _path in LANGS:
            (OUT / "assets" / f"i18n.{code}.js").write_text(
                _render_i18n_js([code]), encoding="utf-8")
        if announce:
            sizes = []
            for code, _label, _path in LANGS:
                p = OUT / "assets" / f"i18n.{code}.js"
                sizes.append(f"{code} {p.stat().st_size:,}")
            print(f"  i18n split : assets/i18n.js {(OUT / 'assets' / 'i18n.js').stat().st_size:,} B"
                  f" (+per-lang {' / '.join(sizes)})", flush=True)

    _write_i18n_assets()
    (OUT / "assets" / "bilingual.js").write_text(BILINGUAL_JS, encoding="utf-8")
    t2s = _load_zh_hant_t2s()
    print(f"i18n t2s    : {len(t2s):,} chars (zh-Hant input normalization)", flush=True)
    (OUT / "assets" / "app.js").write_text(
        APP_JS.replace("REPORT_REPO_PLACEHOLDER", REPORT_REPO)
        .replace("__DETAIL_ROW_FIELDS__", json.dumps(DETAIL_ROW_FIELDS, ensure_ascii=False))
        .replace("__T2S_JSON__", json.dumps(t2s, ensure_ascii=False, separators=(",", ":")))
        .replace("data/idx/core.json", f"data/idx/core.json?v={BUILD_V}")
        .replace("data/idx/pinyin.json", f"data/idx/pinyin.json?v={BUILD_V}")
        .replace("data/idx/manifest.json", f"data/idx/manifest.json?v={BUILD_V}"),
        encoding="utf-8")

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    SUB_NAME_LANG.clear()
    for _sid, _nl in db.execute("SELECT substance_id, name_lang FROM substance"):
        SUB_NAME_LANG[_sid] = _nl or ""
    # v0.11.6 task-1（T12 C5）：成分中文名映射在建成分页之前装好，品牌页后面复用同一份。
    print(f"ingredient zh: {len(load_substance_zh(db)):,} substances with inn_zh", flush=True)
    # T10/§6：名称-规格冲突清单（T15 产出）。默认关闭 → 页面不出现任何「规格待核实」徽标。
    _sc = load_spec_conflicts()
    print(f"spec conflict: {'ON · ' + format(len(_sc), ',') + ' products' if _sc else 'off (mechanism only, T15 list not enabled)'}",
          flush=True)
    tr_counts = build_terms_json(db)
    print(f"bilingual   : {tr_counts.get('zh', 0)} zh / {tr_counts.get('es', 0)} es "
          f"display-default ingredient translations", flush=True)
    coverage = [dict(r) for r in db.execute("SELECT * FROM coverage ORDER BY country")]
    source_cover = [dict(r) for r in db.execute(
        """SELECT COALESCE(p.country, p.region) AS country, p.source_id,
                  COUNT(DISTINCT p.product_id) AS n_products,
                  s.data_as_of, s.data_as_of_note
           FROM product p LEFT JOIN source s ON s.source_id = p.source_id
           GROUP BY country, p.source_id
           ORDER BY country, n_products DESC""")]
    stats = {
        "products": db.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "substances": db.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
        "atc": db.execute(
            "SELECT COUNT(*) FROM substance WHERE atc IS NOT NULL AND atc <> ''").fetchone()[0],
        "keys": db.execute("SELECT COUNT(*) FROM name_key").fetchone()[0],
        "nickname": db.execute("SELECT COUNT(*) FROM nickname").fetchone()[0],
        "aliases": db.execute("SELECT COUNT(*) FROM alias_all").fetchone()[0],
        "confusable": db.execute("SELECT COUNT(*) FROM confusable_pair").fetchone()[0],
        "severe": db.execute(
            "SELECT COUNT(*) FROM collision WHERE level='severe'").fetchone()[0],
    }
    stats["atc_pct"] = round(stats["atc"] / stats["substances"] * 100, 1) if stats["substances"] else 0
    # i18n P1：About 双口径 ATC（动态）+ drug_term 计数 + About/Confused 占位符替换。
    # i18n.js 里内嵌三语字典，所以必须在这批动态值算完后重写一次 i18n.js（前面那次是初版）。
    atc_cov = _atc_coverage(db)
    stats["drug_term"] = db.execute("SELECT COUNT(*) FROM drug_term").fetchone()[0]
    # /warn：只统计 published（draft/retracted 不展示，也不进页面计数）
    warn_by_sev = {"high": 0, "medium": 0, "info": 0}
    for sev, n in db.execute("SELECT severity, COUNT(*) FROM dose_warning "
                             "WHERE status = 'published' GROUP BY severity"):
        warn_by_sev[sev] = n
    stats["warn_high"] = warn_by_sev["high"]
    stats["warn_medium"] = warn_by_sev["medium"]
    stats["warn_info"] = warn_by_sev["info"]
    stats["warn_total"] = sum(warn_by_sev.values())
    _values = _i18n_placeholders(stats, atc_cov, coverage, source_cover)
    _merge_static_i18n(_values)
    _install_zh_hant(_values)
    # 四语不一致就别建站了：任何缺译都会在 i18n.js 里静默回落英文/简体
    _assert_i18n_complete()
    # 同一套规则的第二层：最新版 release notes 四语齐全 + LABEL_I18N 与术语表一致
    _assert_i18n_rules()
    _write_i18n_assets(announce=True)

    # v0.5.4：厂家页清单（必须在 load_index 之前载入，索引要用 mu/ml 字段）
    global MAKERS
    MAKERS = load_makers()
    print(f"maker list : {len(MAKERS):,} makers, "
          f"{sum(1 for v in MAKERS.values() if v['has']):,} with page "
          f"(>= {MAKER_MIN_PRODUCTS} products)", flush=True)

    print("building index ...", flush=True)
    entries = load_index(db)
    write_legacy_index = os.environ.get("WRITE_LEGACY_INDEX") == "1"
    if write_legacy_index:
        # v0.6.1 过渡开关：默认不再双写 data/index.json（dist -53 MB）。
        # 需要临时回滚线上旧客户端时：$env:WRITE_LEGACY_INDEX='1'; python site/build.py
        (OUT / "data" / "index.json").write_text(
            json.dumps(entries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # P1：entries 写一份列式 + 字典编码核心（客户端 decodeCore 解码回 IDX，唯一真相源）。
    core = encode_core(entries)
    (OUT / "data" / "idx").mkdir(parents=True, exist_ok=True)
    (OUT / "data" / "idx" / "core.json").write_bytes(
        json.dumps(core, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if os.environ.get("WRITE_LEGACY_MINI") == "1":
        # 可选二级兜底（默认关）：核心损坏时客户端尝试 legacy-mini（<13.1 MB raw）。
        mini_cols = {k: v for k, v in core["cols"].items()
                     if k in {"k", "d", "dp", "c", "x", "s", "l", "n", "v", "u"}}
        mini = {"v": 1, "n": core["n"], "cols": mini_cols, "q": core["q"]}
        (OUT / "data" / "idx" / "legacy-mini.json").write_bytes(
            json.dumps(mini, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"  {len(entries)} keys", flush=True)
    legacy_txt = (f" (index.json legacy "
                  f"{(OUT / 'data' / 'index.json').stat().st_size / 1e6:.1f} MB)"
                  if write_legacy_index else " (legacy index.json: off)")
    print(f"  core.json  { (OUT / 'data' / 'idx' / 'core.json').stat().st_size / 1e6:.1f} MB"
          f"{legacy_txt}", flush=True)

    # P2 分片（task-36）：manifest + shard-*.json；客户端先拉 manifest，再按查询
    # 首字符/拼音首字母取 1-3 片；core.json 保留为完整回退。
    shards = encode_shards(entries)
    (OUT / "data" / "idx" / "manifest.json").write_bytes(
        json.dumps(shards, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"  manifest.json ({shards['shardCount']} shards, "
          f"{shards['shardBytes'] / 1e6:.1f} MB) "
          f"{(OUT / 'data' / 'idx' / 'manifest.json').stat().st_size / 1e3:.1f} KB", flush=True)

    # A1（v0.5.6）：产品明细桶由 etl/build_detail_buckets.py（index-perf task-58）
    # 预生成到 data/idx/；构建时原样复制到 OUT（懒加载，不进主索引/首屏）。
    # 桶内 key 集合 = 上一版 index.json 的 k 列表；DB/索引变更后需先重跑该脚本。
    detail_src = ROOT / "data" / "idx"
    detail_files = sorted(detail_src.glob("detail-*.json")) if detail_src.exists() else []
    detail_bytes = 0
    for p in detail_files:
        (OUT / "data" / "idx" / p.name).write_bytes(p.read_bytes())
        detail_bytes += p.stat().st_size
    if detail_files:
        print(f"  detail buckets {len(detail_files)} ({detail_bytes / 1e6:.1f} MB, "
              f"lazy-load on expand)", flush=True)
    else:
        print("  detail buckets 0 (A1 details disabled: data/idx/detail-*.json missing)",
              flush=True)

    print("building nickname index ...", flush=True)
    aliases = load_aliases(db)
    # task-141c：同物异名也进检索索引（alias → canonical 身份卡），与人工俗称同构。
    sub_aliases, sub_alias_hits = load_substance_aliases(db)
    aliases += sub_alias_hits
    (OUT / "data" / "aliases.json").write_text(
        json.dumps(aliases, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {len(aliases)} nicknames ({len(sub_alias_hits)} substance synonyms)", flush=True)

    # 搜索增强（task-28）：拼音/首字母 token 表（客户端按需懒加载，见 APP_JS 的 pinyinFetch）
    piny = encode_pinyin(entries, aliases)
    (OUT / "data" / "idx" / "pinyin.json").write_bytes(
        json.dumps(piny, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"  pinyin.json { (OUT / 'data' / 'idx' / 'pinyin.json').stat().st_size / 1e6:.2f} MB",
          flush=True)

    print("building confused index ...", flush=True)
    confused = load_confusable(db)
    (OUT / "data" / "confused.json").write_text(
        json.dumps(confused, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {len(confused)} directions", flush=True)

    # ARTG 名称层：只有「品牌 + 申办方 + ARTG ID」，没有成分。
    # 检索时作为「登记存在、成分未收录」的兜底，不参与产品结果。
    print("building ARTG name index ...", flush=True)
    artg = [[r[0], r[1], r[2] or "", r[3]] for r in db.execute(
        "SELECT name_norm, name, sponsor, artg_id FROM artg_entry ORDER BY name")]
    (OUT / "data" / "artg.json").write_text(
        json.dumps(artg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {len(artg)} ARTG names", flush=True)

    # T13 / D7（v0.11.7）：结果行 / 身份卡要显示「数据截止」——把「国家 → 来源 + 截止日」
    # 做成 1 KB 的小 JSON，检索页懒加载一次（不进 core.json，不压索引体积）。
    print("building source meta ...", flush=True)
    mk_meta: dict[str, dict] = {}
    for _mk, _sid, _asof, _name, _n in db.execute(
            """SELECT COALESCE(p.country, p.region) AS mk, p.source_id,
                      COALESCE(s.data_as_of, '') AS asof,
                      COALESCE(s.name, p.source_id, '') AS name, COUNT(*) AS n
               FROM product p LEFT JOIN source s ON s.source_id = p.source_id
               GROUP BY mk, p.source_id ORDER BY n DESC"""):
        if not _mk:
            continue
        d = mk_meta.setdefault(_mk, {"source": "", "as_of": ""})
        if not d["source"]:
            d["source"] = _name
        if _asof and _asof > d["as_of"]:
            d["as_of"] = _asof
    (OUT / "data" / "sources.json").write_text(
        json.dumps({"markets": mk_meta}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    print(f"  {len(mk_meta)} markets (source + data_as_of)", flush=True)

    print("building drug pages ...", flush=True)
    n_drug = build_drug_pages(db, entries, sub_aliases)
    print("collecting name data ...", flush=True)
    data = collect_name_data(db)
    families: dict[str, dict] = {}
    members: dict[str, list[str]] = defaultdict(list)
    for key_id, fam_id, label, note in db.execute(
        "SELECT nf.key_id, bf.family_id, bf.label, bf.note FROM name_family nf"
        " JOIN brand_family bf ON bf.family_id = nf.family_id"
    ):
        families[key_id] = {"id": fam_id, "label": label, "note": note, "members": []}
        members[fam_id].append(key_id)
    for key_id, fam in families.items():
        fam["members"] = members[fam["id"]]
    displays = {e["k"]: e["d"] for e in entries}
    print("building name pages ...", flush=True)
    n_name = build_name_pages(db, entries, data, families, displays)
    print("building combo pages ...", flush=True)
    n_combo = build_combo_pages(entries, db)
    print("building maker pages ...", flush=True)
    n_maker = build_maker_pages(entries, db)
    build_index_page(entries, stats, coverage)
    n_conf = build_confused(db)
    n_warn = build_warn(db)
    build_about(stats, coverage, source_cover)
    build_coverage_page(db, coverage, source_cover)
    build_whats_new()
    build_glossary()
    print("building atc4 forms ...", flush=True)
    build_atc4_forms_json()
    print("building atc pages ...", flush=True)
    n_atc = build_atc_pages(db)
    n_cat = build_category_pages(db)
    build_atc_index()
    build_categories_json(db)
    # v0.10.2：类别发现快车道（cats.json + 16 类 top200 切片 + ATC 成分表）。
    # 防遮蔽：口语词若与真实商品名全等，必须已在 lib 的白名单里登记，否则构建中止
    # （AGENTS §1：先定位名字，不能把商品名结果整片换成大类候选集）。
    assert_no_unlisted_shadow(db)
    catx = build_cat_word_index(db, entries)
    atc_ing = build_atc_ing_json(db)
    print(f"  cats.json  : {catx['bytes']:,} B · {catx['words']:,} words · "
          f"{catx['cats']} slices", flush=True)
    print(f"  atc-ing    : {atc_ing['bytes']:,} B · {atc_ing['codes']:,} codes", flush=True)
    build_export_only_json(db)
    build_data_package(db, stats, coverage, source_cover)
    print("building 404 ...", flush=True)
    build_404()
    build_seo_files()

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"\n== done ==")
    print(f"  drug pages : {n_drug}")
    print(f"  name pages : {n_name}")
    print(f"  combo pages: {n_combo}")
    print(f"  maker pages: {n_maker} (threshold >= {MAKER_MIN_PRODUCTS} products)")
    print(f"  confused   : {n_conf} pairs")
    print(f"  warnings   : {n_warn} published")
    print(f"  core.json  : {(OUT / 'data' / 'idx' / 'core.json').stat().st_size / 1e6:.1f} MB"
          f" (legacy index.json: {'on' if os.environ.get('WRITE_LEGACY_INDEX') == '1' else 'off'})")
    print(f"  total size : {size / 1e6:.1f} MB")
    print(f"  open       : {OUT / 'index.html'}")
    db.close()


if __name__ == "__main__":
    main()
