# -*- coding: utf-8 -*-
"""挪威 DMP FEST 2.5.1 → SQLite（第 16 个市场 country='NO'）。

许可（先看这一页）
------------------
Direktoratet for medisinske produkter（DMP，英文页旧缩写 NOMA；旧称 Statens legemiddelverk）
把 FEST 按 **NLOD 2.0**（Norsk lisens for offentlige data）提供：可复制 / 修改 / 再分发 / 商用，
义务是①署名许可方 + 许可名 + 链接、②标明做过修改、③不得歪曲或暗示背书。
评估与证据：`reports/2026-11-21-no-license-assessment.md`（data-scout，2026-11-21）。
本站只做「身份对应」：不转载 SmPC 正文、不存价格、不做剂量换算。

数据源
------
下载页：https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest/downloading-fest-and-safest
直链  ：https://www.dmp.no/globalassets/documents/om-oss/distribusjon-av-legemiddeldata/fest/festfiler/fest251.zip
快照  ：ZIP 14,550,258 B（sha256 cfca96f2…5c66f3）→ 内含单个 `fest251.xml` 118,252,386 B
数据截止：XML 根节点 `<HentetDato>2026-11-10T10:24:32</HentetDato>`
更新节奏：每月 1 日与 15 日（DMP 页面）；本站每个写库窗口只下一次 ZIP。

XML 结构（三层包裹，`Oppf*` 是追踪/状态层，业务对象在里层）
------------------------------------------------------------
    <FEST xmlns="…/m30/2014-12-01">
      <HentetDato/>
      <KatLegemiddelMerkevare><OppfLegemiddelMerkevare>
          <Id/><Tidspunkt/><Status V="A" DN="Aktiv oppføring"/>
          <LegemiddelMerkevare xmlns="…/forskrivning/2014-12-01"> … </LegemiddelMerkevare>
      </OppfLegemiddelMerkevare></KatLegemiddelMerkevare>
      <KatLegemiddelpakning><OppfLegemiddelpakning> … </OppfLegemiddelpakning></KatLegemiddelpakning>
      <KatVirkestoff><OppfVirkestoff>
          <Virkestoff/> 或 <VirkestoffMedStyrke/>     ← 成分主档与「成分+含量」同一个 Kat
      </OppfVirkestoff></KatVirkestoff>
    </FEST>

引用解析（实测 100% 可解析，2026-11-21）：
  - `Legemiddelpakning/Pakningsinfo/RefLegemiddelMerkevare` → 品牌**内层** `LegemiddelMerkevare/Id`
  - `LegemiddelMerkevare/SortertVirkestoffMedStyrke/RefVirkestoffMedStyrke` → `VirkestoffMedStyrke/Id`
  - `VirkestoffMedStyrke/RefVirkestoff` 与 `SortertVirkestoffUtenStyrke/RefVirkestoff` → `Virkestoff/Id`

建模口径（为什么不按包装建 product 行）
----------------------------------------
FEST 的 `LegemiddelMerkevare` 已经 = 「商品名 + 剂型 + 含量 + 成分」这一个身份，
`Legemiddelpakning` 只是它的包装规格（同品牌常有 1–37 个包装，含多盒装）。
本站 L2 的判定键是「国家 × 剂型 × 规格 × 活性成分」，所以一行 product = 一个品牌条目：
  - 8,985 个品牌 → 8,985 个 product；
  - 包装规格（`Pakningsstr` + `EnhetPakning`）聚合进 `product.pack`（多包装用「 · 」连接）；
  - 状态**只能**由包装级**日期**标记聚合推断：`AvregDato`（注销）/ `MidlUtgattDato`（临时停售）；
    `VarenrUtgaende` 的文本是另一个订货号（新旧订货号替换链接），**不是**状态标记，不入状态判定；
    FEST 自身 `Status` 全部是 `A / Aktiv oppføring`，**不得**据此写成「挪威全部在售」。
产品 id：`NO-<商品名 slug>-<品牌内层 Id sha1 前 8 位>`，重跑稳定（不依赖包装增删）。

字段映射
--------
| FEST | DB |
|---|---|
| `Varenavn` | `product_name.raw`（name_type='trade'，is_primary=1） |
| `LegemiddelformKort@DN` / `@V` | `product.dosage_form`（挪威语原文）/ `form_base`（本文件词表） |
| `AdministreringLegemiddel/Administrasjonsvei@DN` | `product.route`（结构化途径，不从名称猜） |
| `LegemiddelformKort@DN` 里的 depot/enter/modifisert | `product.release`（ER / DR / MR，其余 none） |
| `Pakningsinfo/Pakningsstr` + `EnhetPakning@DN` | `product.pack`（多个包装连接） |
| `ProduktInfo/Produsent` | `product.mah` |
| `Preparattype@DN` | `product.category`（Legemiddel / Vaksine / Kosttilskudd …） |
| `SortertVirkestoffMedStyrke/RefVirkestoffMedStyrke` | `product_component`（可多条 = 复方） |
| `VirkestoffMedStyrke/Styrke@V/@U` | `strength_value` / `strength_unit`（原文，单位只做文本归一） |
| `VirkestoffMedStyrke/StyrkeNevner@V/@U` | `per_volume_value` / `per_volume_unit`（如 mg/ml） |
| `Virkestoff/Navn`（挪）+ `NavnEngelsk`（英） | `substance.inn_en`（优先英文）+ name_type='inn' 名字键 |
| `Atc@V/@DN`（仅单方产品） | `substance.atc` / `atc_name`，只在空值时回填，不覆盖 |
| `OppfLegemiddelMerkevare/Status@V` | 不单独入列（全部 A，见上） |

不写库的字段：`PrisVare`（价格）、`Preparatomtaleavsnitt` 正文（只把 PDF 链接放 `product.source_url`）、
订货号 `Varenr` / 条码 `Ean`（不是注册号；FEST 无 MT 号，`approval_id` 留空）、
`Refusjon`（医保报销）、`Interaksjon`（相互作用）。

CLI
---
    python etl/ingest_no.py --fetch                 # 抓 ZIP → data/raw/no/（已存在且非空则跳过）
    python etl/ingest_no.py --dry-run               # 默认：解析 + 统计，只读开库，不写
    python etl/ingest_no.py --self-check            # 离线断言（映射/解析/状态，不联网不读库）
    python etl/ingest_no.py --apply --db .tmp/no-ingest/drugs-copy.db          # 副本演练
    python etl/ingest_no.py --apply --allow-real --db data/drugs.db            # 写库窗口
    python etl/ingest_no.py --rollback --allow-real --manifest data/sources/no_ingest_manifest_<日期>.json

写库前必须手动备份 `data/drugs.db` → `data/backups/drugs-YYYYMMDD-HHMMSS-no.db`（AGENTS.md §4）；
同一时间只有本脚本的写库窗口可以动 `data/drugs.db`。`--apply` 会先 `require_country('NO')`，
所以必须先跑 `python db/init_db.py` 让 schema 的 CHECK 枚举生效。重跑幂等：先清本 source 的 NO 行再写。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))

from ingest_ema_medicines import _variant_resolver  # noqa: E402
from ingest_openfda_ndc import form_base_of, slug  # noqa: E402
from normalize_name import normalize  # noqa: E402
from normalize_salts import ANHYDROUS_TOKENS, SALT_ALIASES, SOLVATE_TOKENS, WATER_TOKENS  # noqa: E402
from normalize_strength import norm_unit  # noqa: E402
import _ingest_common as common  # noqa: E402

CODE = "NO"
SOURCE_ID = "dmp_fest"
ZIP_URL = ("https://www.dmp.no/globalassets/documents/om-oss/"
           "distribusjon-av-legemiddeldata/fest/festfiler/fest251.zip")
DOWNLOAD_PAGE = ("https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/"
                 "electronic-prescription-support-system-fest/downloading-fest-and-safest")
FEST_PAGE = ("https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/"
             "electronic-prescription-support-system-fest")
LICENSE_URL = "https://data.norge.no/nlod/en/2.0"
LICENSE_NAME = "NLOD 2.0"
UA = ("drug-brand-crossref/0.2 (public-data research; +https://drugcrossref.com/; "
      "FEST ingest, one ZIP per DB window)")

RAW = ROOT / "data" / "raw" / "no"
ZIP_PATH = RAW / "fest251.zip"
FETCH_META = RAW / "fetch_meta.json"
WORK = ROOT / ".tmp" / "no-ingest"
DB = ROOT / "data" / "drugs.db"
REAL_DB = DB
MANIFEST_DIR = ROOT / "data" / "sources"

SOURCE_META = {
    "name": "DMP FEST 2.5.1 (Norwegian Medical Products Agency)",
    "url": DOWNLOAD_PAGE,
    "license": "NLOD 2.0",
    "license_url": LICENSE_URL,
    "data_as_of_note": "FEST 快照 HentetDato；DMP 每月 1 日与 15 日更新",
    "notes": ("处方链数据服务（医生/医院/药房/系统商）；只有活动条目（Status A），无注册号；"
              "本站已归一化（成分名/单位/剂型），不转载 SmPC 正文、不存价格"),
}

RE_ID = re.compile(r"[^a-z0-9]+")
RE_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------------------
# 单位：挪威语写法 → 站内规范单位（只做文本归一，不换算数值）
# ---------------------------------------------------------------------------
# `norm_unit()` 认识 iu/ml/µg/% w/v 等，但不认识挪威语 `mikrog`（微克）与 `IE`（国际单位）。
# 其余生物制品单位（RI / E / SQ-E / DAgE / HEP / CCID50 …）**原样保留**：不认识就别猜。
NO_UNIT_FIX = {
    "mikrog": "mcg",
    "mikroliter": "uL",
    "IE": "iu",
    "mill IE": "million IU",
    "mill E": "million E",
    "U": "unit",
}

# 含量分母（StyrkeNevner）：体积/质量单位归一，其他给药单位保留挪威语原文。
NO_DENOM_FIX = {"ml": "ml", "l": "l", "g": "g", "mg": "mg", "mikroliter": "uL"}


def fold_no(text: str) -> str:
    """挪威语折叠：小写 + å/ø/æ 先转写，再去重音与标点（`Øyedråper` → `oyedraper`）。"""
    s = (text or "").strip().lower()
    s = s.translate(str.maketrans({"å": "a", "ø": "o", "æ": "ae", "Å": "a", "Ø": "o", "Æ": "ae"}))
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = RE_ID.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def unit_of(raw: str | None) -> tuple[str | None, str]:
    """FEST 单位 → 站内单位 + 规则标签（exact/fix/keep/empty）。"""
    if raw is None or not str(raw).strip():
        return None, "empty"
    s = re.sub(r"\s+", " ", str(raw)).strip()
    if s in NO_UNIT_FIX:
        mapped = NO_UNIT_FIX[s]
        if mapped.startswith("million "):
            return mapped, "fix"
        unit, _rule = norm_unit(mapped)
        return unit, "fix"
    unit, rule = norm_unit(s)
    return unit, rule


def denom_of(value: str | None, raw_unit: str | None) -> tuple[float | None, str | None]:
    """StyrkeNevner（每 X 单位）→ (数量, 单位)；数量解析不了就整条留空，不猜。"""
    if value is None or not str(value).strip():
        return None, None
    try:
        num = float(str(value).replace(",", "."))
    except ValueError:
        return None, None
    unit = None
    if raw_unit:
        key = str(raw_unit).strip()
        unit = NO_DENOM_FIX.get(key, key)
        if unit in ("ml", "l"):
            unit = norm_unit(unit)[0]
    return num, unit


def strength_value_of(raw: str | None) -> float | None:
    """`Styrke@V` → float（原文小数点是 `.`；解析不了返回 None，不改写数值）。"""
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(str(raw).strip().replace(",", "."))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 剂型：挪威语 `LegemiddelformKort@DN` → form_base（词表顺序有意义，先命中先返回）
# ---------------------------------------------------------------------------
# 只映射到站内既有 form_base 取值（9 个主类 + PLAIN_BASES 里的单值名）；
# 命中不了的落 `other` 并计数，绝不把整串挪威语原文塞进 form_base（同 ingest_openfda_ndc R2 口径）。
FORM_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("effervescent", ("bruse",)),
    ("injection", ("injeksjon", "infusjon", "parenteral", "dialyse", "hemofiltrering",
                   "kardioplegi", "intravesikal", "intravitreal", "intraokulaer",
                   "blodfraksjonsmodifisering")),
    ("inhalation", ("inhalasjon",)),
    ("tablet", ("tablett", "pastill", "lyofilisat")),
    ("film", ("sublingvalfilm", "munnsmeltende film")),
    ("capsule", ("kapsel",)),
    ("suppository", ("stikkpille", "suppositor")),
    ("pessary", ("vagitorie", "vaginalinnlegg")),
    ("nasal", ("nese",)),
    ("ophthalmic", ("oye",)),
    ("gas", ("gass",)),
    ("implant", ("implantat", "intrauterint innlegg")),
    ("kit", ("preparasjonssett",)),
    ("cord", ("medisinert trad",)),
    ("gum", ("tyggegummi",)),
    ("topical", ("krem", "salve", "gel", "liniment", "plaster", "sjampo", "pudder",
                 "pasta", "kollodium", "skum", "neglelakk", "hudstift", "hudspray",
                 "transdermal", "kompress", "svamp", "tannpasta", "tannkjott",
                 "badevann", "stift")),
    ("powder", ("pulver", "granulat", "granuler")),
    ("liquid", ("vaeske", "opplosning", "suspensjon", "emulsjon", "dispersjon", "mikstur",
                "draper", "sirup", "munnvann", "munnskylle", "skylle", "spray", "urtete",
                "konsentrat")),
)
# 这些词只出现在「粉/颗粒/溶液」的定语里，不该改变主剂型判定；保留清单便于测试回溯。
FORM_DEVICES = {"medisinsk blodigle": "device", "matriks til vevslim": "other"}


def form_base_no(form: str) -> str:
    """挪威语剂型原文 → form_base（9 主类 / 单值名 / other / unknown）。"""
    f = fold_no(form)
    if not f:
        return "unknown"
    if f in FORM_DEVICES:
        return FORM_DEVICES[f]
    for base, keys in FORM_RULES:
        if any(k in f for k in keys):
            return base
    return form_base_of(f)


def release_no(form: str) -> str:
    """挪威语剂型里的释放机制：depot→ER / enter→DR / modifisert frisetting→MR，其余 none。"""
    f = fold_no(form)
    if not f:
        return "none"
    if "enterodepot" in f:
        return "DR"
    if "enter" in f:
        return "DR"
    if "modifisert" in f:
        return "MR"
    if "depot" in f or "forlenget" in f:
        return "ER"
    return "none"


# ---------------------------------------------------------------------------
# 途径：`Administrasjonsvei@DN` 是结构化字段，不从名称猜
# ---------------------------------------------------------------------------
ROUTE_MAP = {
    "oral bruk": "oral",
    "intravenøs bruk": "intravenous",
    "subkutan bruk": "subcutaneous",
    "bruk på hud": "topical",
    "intramuskulær bruk": "intramuscular",
    "okulær bruk": "ophthalmic",
    "bruk til inhalasjon": "inhalation",
    "transdermal bruk": "transdermal",
    "nasal bruk": "nasal",
    "rektal bruk": "rectal",
    "sublingval bruk": "sublingual",
    "bruk i munnhulen": "buccal",
    "epidural bruk": "epidural",
    "vaginal bruk": "vaginal",
    "intraperitoneal bruk": "intraperitoneal",
    "administrasjonsvei ikke spesifisert": None,
    "dental bruk": "dental",
    "bruk i øret": "otic",
    "intravitreal bruk": "intravitreal",
    "intravesikal bruk": "intravesical",
    "intratekal bruk": "intrathecal",
    "intrakavernøs bruk": "intracavernous",
    "bruk på tannkjøttet": "gingival",
    "hemodialyse": "hemodialysis",
    "intraokulær bruk": "intraocular",
    "intraartikulær bruk": "intraarticular",
    "bruk på skadet område": "topical",
    "infiltrasjon": "infiltration",
    "intradermal bruk": "intradermal",
    "intrauterin bruk": "intrauterine",
    "urethral bruk": "urethral",
    "intraarteriell bruk": "intraarterial",
    "bruk inni skadet område": "topical",
    "intrakameral bruk": "intracameral",
    "intestinal bruk": "intestinal",
    "ekstrakorporal bruk": "extracorporeal",
    "intrakoronar bruk": "intracoronary",
    "subretinal bruk": "subretinal",
    "bukkal bruk": "buccal",
    "implantering": "implantation",
    "perinevral bruk": "perineural",
    "periodontal bruk": "periodontal",
    "bading": "immersion",
    "endotrakeopulmonal bruk": "endotracheopulmonary",
    "intralymfatisk bruk": "intralymphatic",
}


def route_no(dn: str | None) -> str | None:
    """`Administrasjonsvei@DN` → route；未登记的值返回 None（计数后写进报告，不猜）。"""
    if not dn:
        return None
    key = fold_no(dn)
    for known, value in ROUTE_MAP.items():
        if fold_no(known) == key:
            return value
    return None


# ---------------------------------------------------------------------------
# 成分名对齐：FEST 英文名 → 库内 substance.inn_en
# ---------------------------------------------------------------------------
# FEST 用 INN/BAN 写法，本库 canonical 多为 USAN（US 先入库）。只收「同一物质的不同官方名」，
# 逐条可核；不写盐/水合物（交给 split_salt + variant 解析），也不做剂量/等效判断。
INN_ALIAS = {
    "paracetamol": "acetaminophen",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "mesalazine": "mesalamine",
    "acetylsalicylic acid": "aspirin",
    "phenoxymethylpenicillin": "penicillin v",
    "norethisterone": "norethindrone",
    "glyceryl trinitrate": "nitroglycerin",
    "cromoglicic acid": "cromolyn",
    "theophylline ethylenediamine": "aminophylline",
    "choriogonadotrophin alfa": "choriogonadotropin alfa",
    "thyroid gland": "thyroid",
    # 同一物质的另一个官方/惯用写法（逐条可在库内 substance.inn_en 复核）
    "sodium hydrogen carbonate": "sodium bicarbonate",
    "triglycerides medium chain": "medium chain triglycerides",
    "amino acids unspecified": "amino acids",
    "carbohydrates": "carbohydrate",
    "immunoglobulin human normal": "normal immunoglobulin",
    "lanthan": "lanthanum",
    "misteltoe": "mistletoe",          # FEST 原文拼写；库内规范名 mistletoe
}
# 不是成分名的占位值（顺势疗法类别词）：不建成分、不挂 product_component，只计数。
NON_SUBSTANCE = {
    "homeopatic composed drug": "FEST 用「顺势疗法复方」类别词代替成分名",
    "homeopatic singel drug": "FEST 用「顺势疗法单方」类别词代替成分名",
}
RE_PAREN = re.compile(r"\s*\([^()]*\)\s*")
SPELLING_PAIRS = (("alfa", "alpha"), ("alpha", "alfa"))

# 盐/水合物尾词（只用于「去掉尾部盐词再找母体」，不参与任何折算判断）。
# 词表来自 normalize_salts（与盐基折算同一套 token），额外的多盐/多水词是 FEST 常见写法。
SALT_TRAIL = ({alias for aliases in SALT_ALIASES.values() for alias in aliases}
              | set(WATER_TOKENS) | set(ANHYDROUS_TOKENS) | set(SOLVATE_TOKENS)
              | {"dihydrochloride", "trihydrochloride", "dibromide", "dihydrate",
                 "trihydrate", "hemihydrate", "sesquihydrate"})
# 这些「母体」本身是元素/电解质：去掉后面的盐词会把另一种物质当成它（KCl≠K），
# 所以只允许整名/去 `ion` 命中，不做去盐母体匹配。
ELEMENT_BASE = frozenset({
    "sodium", "potassium", "calcium", "magnesium", "chloride", "iodide", "bromide",
    "phosphate", "citrate", "lactate", "acetate", "gluconate", "carbonate",
    "bicarbonate", "sulfate", "sulphate", "nitrate", "ferrous", "ferric", "copper",
    "zinc", "manganese", "chromium", "molybdenum", "selenium", "lithium", "lanthanum",
    "iodine", "fluoride", "ammonium", "aluminium", "aluminum", "silver", "gold",
})


def norm_key(text: str) -> str:
    """成分名比较键：小写 ASCII、去标点（`Copper(II) ion` → `copper ii ion`）。"""
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def salt_base(name: str) -> str:
    """去掉尾部盐/水合物词 → 母体名（去不掉或母体是元素时返回空串）。"""
    words = norm_key(name).split()
    while len(words) > 1 and words[-1] in SALT_TRAIL:
        words.pop()
    base = " ".join(words)
    if base and base != norm_key(name) and base not in ELEMENT_BASE:
        return base
    return ""


def name_candidates(name: str) -> list[tuple[str, str]]:
    """一个成分名 → 依次尝试的 (候选键, 命中方式)。

    命中方式用于报告里的映射率拆解：exact 原名 / paren 去括号 / ion 去 `ion` /
    salt 去盐母体 / inn_alias 官方别名。顺序即优先级，先命中先返回。
    """
    out: list[tuple[str, str]] = []

    def add(key: str, kind: str) -> None:
        key = re.sub(r"\s+", " ", key).strip()
        if key and key not in (k for k, _kind in out):
            out.append((key, kind))

    add(norm_key(name), "exact")
    add(norm_key(RE_PAREN.sub(" ", name or "")), "paren")
    for key, _kind in list(out):
        for no_spelling, en_spelling in SPELLING_PAIRS:
            if no_spelling in key.split():
                add(" ".join(en_spelling if w == no_spelling else w for w in key.split()),
                    "spelling")
    for key, _kind in list(out):
        if key.endswith(" ion"):
            add(key[: -len(" ion")], "ion")
    for key, _kind in list(out):
        add(salt_base(key), "salt")
    for key, _kind in list(out):
        if key in INN_ALIAS:
            add(norm_key(INN_ALIAS[key]), "inn_alias")
    return out


def candidate_keys(name: str) -> list[str]:
    """只取候选键（测试/自检用）。"""
    return [key for key, _kind in name_candidates(name)]


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(force: bool = False) -> dict:
    """下载 FEST ZIP 到 data/raw/no/ 并写 fetch_meta.json（幂等：已存在且非空就跳过）。"""
    RAW.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists() and ZIP_PATH.stat().st_size > 0 and not force:
        meta = json.loads(FETCH_META.read_text(encoding="utf-8")) if FETCH_META.exists() else {}
        print(f"快照已存在，跳过下载：{ZIP_PATH.relative_to(ROOT)} "
              f"({ZIP_PATH.stat().st_size:,} B, sha256={sha256_file(ZIP_PATH)[:16]}…)；"
              "一个写库窗口只下一次 ZIP（要重下加 --force）")
        return meta
    req = Request(ZIP_URL, headers={"User-Agent": UA})
    t0 = time.time()
    with urlopen(req, timeout=600) as resp:
        body = resp.read()
        meta = {
            "source_id": SOURCE_ID,
            "requested_url": ZIP_URL,
            "status": resp.status,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "headers": {k: resp.headers.get(k) for k in
                        ("Content-Type", "Content-Length", "Last-Modified", "ETag")},
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "seconds": round(time.time() - t0, 2),
            "note": "FEST 2.5.1 Rekvirent-uttrekk；只下一次，解压后的 XML 不入库",
        }
    tmp = ZIP_PATH.with_suffix(".zip.part")
    tmp.write_bytes(body)
    tmp.replace(ZIP_PATH)
    FETCH_META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"下载完成：{ZIP_PATH.relative_to(ROOT)} {meta['bytes']:,} B "
          f"sha256={meta['sha256'][:16]}…（{meta['seconds']}s）")
    return meta


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _attr(el: ET.Element | None, name: str) -> str:
    return (el.attrib.get(name) or "").strip() if el is not None else ""


def _refs(brand_el: ET.Element, tag: str, ref_tag: str) -> list[str]:
    """按 `Sortering` 排序取引用 Id（同一块里可多条 = 复方）。"""
    pairs: list[tuple[int, str]] = []
    for block in brand_el.findall("{*}" + tag):
        sort = _text(block.find("{*}Sortering"))
        try:
            ord_ = int(sort)
        except ValueError:
            ord_ = 999
        for ref in block.findall("{*}" + ref_tag):
            rid = _text(ref)
            if rid:
                pairs.append((ord_, rid))
    return [rid for _ord, rid in sorted(pairs, key=lambda x: x[0])]


def load_snapshot(zip_path: Path = ZIP_PATH) -> dict:
    """流式解析 fest251.xml → {brands, packages, vms, virk, hentet, members}。

    内存可控：只在 `Kat*` 层 clear（子元素此时已处理完，引用不会被提前清空）。
    """
    if not zip_path.exists():
        raise SystemExit(f"没有快照：{zip_path}（先跑 python etl/ingest_no.py --fetch）")
    brands: dict[str, dict] = {}
    packages: list[dict] = []
    vms: dict[str, dict] = {}
    virk: dict[str, dict] = {}
    hentet = ""
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.namelist()
        inner = next((m for m in members if m.lower().endswith(".xml")), None)
        if not inner:
            raise SystemExit(f"ZIP 里没有 XML：{members}")
        with zf.open(inner) as fh:
            for _event, el in ET.iterparse(fh, events=("end",)):
                name = _local(el.tag)
                if name == "HentetDato":
                    hentet = _text(el)
                elif name == "KatLegemiddelMerkevare":
                    for oppf in el:
                        if _local(oppf.tag) != "OppfLegemiddelMerkevare":
                            continue
                        obj = oppf.find("{*}LegemiddelMerkevare")
                        if obj is None:
                            continue
                        bid = _text(obj.find("{*}Id"))
                        if not bid:
                            continue
                        admin = obj.find("{*}AdministreringLegemiddel/{*}Administrasjonsvei")
                        smpc = _attr(obj.find("{*}Preparatomtaleavsnitt/{*}Lenke/{*}Www"), "V")
                        brands[bid] = {
                            "id": bid,
                            "status": _attr(oppf.find("{*}Status"), "V"),
                            "varenavn": _text(obj.find("{*}Varenavn")),
                            "navn_form_styrke": _text(obj.find("{*}NavnFormStyrke")),
                            "atc": _attr(obj.find("{*}Atc"), "V"),
                            "atc_name": _attr(obj.find("{*}Atc"), "DN"),
                            "form": _attr(obj.find("{*}LegemiddelformKort"), "DN"),
                            "form_lang": _text(obj.find("{*}LegemiddelformLang")),
                            "preparattype": _attr(obj.find("{*}Preparattype"), "DN"),
                            "reseptgruppe": _attr(obj.find("{*}Reseptgruppe"), "V"),
                            "produsent": _text(obj.find("{*}ProduktInfo/{*}Produsent")),
                            "route_dn": _attr(admin, "DN"),
                            "smpc": smpc,
                            "refs": _refs(obj, "SortertVirkestoffMedStyrke",
                                          "RefVirkestoffMedStyrke"),
                            "refs_no_strength": _refs(obj, "SortertVirkestoffUtenStyrke",
                                                      "RefVirkestoff"),
                        }
                    el.clear()
                elif name == "KatLegemiddelpakning":
                    for oppf in el:
                        if _local(oppf.tag) != "OppfLegemiddelpakning":
                            continue
                        obj = oppf.find("{*}Legemiddelpakning")
                        if obj is None:
                            continue
                        pk: dict = {
                            "id": _text(obj.find("{*}Id")),
                            "status": _attr(oppf.find("{*}Status"), "V"),
                            "varenr": _text(obj.find("{*}Varenr")),
                            "ean": _text(obj.find("{*}Ean")),
                            "infos": [],
                        }
                        for info in obj.findall("{*}Pakningsinfo"):
                            enhet = info.find("{*}EnhetPakning")
                            pk["infos"].append({
                                "brand_ref": _text(info.find("{*}RefLegemiddelMerkevare")),
                                "pakningsstr": _text(info.find("{*}Pakningsstr")),
                                "enhet": _attr(enhet, "V"),
                                "enhet_dn": _attr(enhet, "DN"),
                            })
                        mi = obj.find("{*}Markedsforingsinfo")
                        if mi is not None:
                            # VarenrUtgaende 是「另一个订货号」（替换链接），不是状态日期，
                            # 故不入 pk；状态只看 AvregDato / MidlUtgattDato。
                            for key, tag in (("marked", "Markedsforingsdato"),
                                             ("midl", "MidlUtgattDato"),
                                             ("avreg", "AvregDato")):
                                value = _text(mi.find("{*}" + tag))
                                pk[key] = value if RE_ISO_DATE.match(value) else ""
                        packages.append(pk)
                    el.clear()
                elif name == "KatVirkestoff":
                    for oppf in el:
                        if _local(oppf.tag) != "OppfVirkestoff":
                            continue
                        master = oppf.find("{*}Virkestoff")
                        if master is not None:
                            kid = _text(master.find("{*}Id"))
                            if kid:
                                virk[kid] = {"id": kid,
                                             "navn": _text(master.find("{*}Navn")),
                                             "navn_en": _text(master.find("{*}NavnEngelsk"))}
                        strength = oppf.find("{*}VirkestoffMedStyrke")
                        if strength is not None:
                            vid = _text(strength.find("{*}Id"))
                            if vid:
                                st = strength.find("{*}Styrke")
                                sn = strength.find("{*}StyrkeNevner")
                                vms[vid] = {"id": vid,
                                            "styrke": _attr(st, "V"),
                                            "unit": _attr(st, "U"),
                                            "nevner": _attr(sn, "V"),
                                            "nevner_u": _attr(sn, "U"),
                                            "ref": _text(strength.find("{*}RefVirkestoff"))}
                    el.clear()
    if not brands or not packages or not virk:
        raise SystemExit(f"快照解析结果异常：brands={len(brands)} packages={len(packages)} "
                         f"virkestoff={len(virk)}")
    return {"brands": brands, "packages": packages, "vms": vms, "virk": virk,
            "hentet": hentet, "members": members, "inner": inner}


# ---------------------------------------------------------------------------
# 聚合：品牌 → 包装 / 状态 / pack 文本
# ---------------------------------------------------------------------------
def packages_by_brand(packages: list[dict]) -> dict[str, list[dict]]:
    """品牌内层 Id → 引用它的包装（一个包装可含多条 Pakningsinfo）。"""
    out: dict[str, list[dict]] = defaultdict(list)
    for pk in packages:
        seen: set[str] = set()
        for info in pk["infos"]:
            ref = info["brand_ref"]
            if ref and ref not in seen:
                seen.add(ref)
                out[ref].append(pk)
    return out


def pack_text(brand_id: str, pkgs: list[dict]) -> tuple[str | None, int]:
    """品牌自己的包装规格（按 Pakningsinfo 去重）→ ("100 stykk · 3 x 1 stykk", 规格数)。"""
    specs: list[str] = []
    for pk in pkgs:
        for info in pk["infos"]:
            if info["brand_ref"] != brand_id:
                continue
            size = info["pakningsstr"]
            unit = info["enhet_dn"] or info["enhet"]
            spec = (f"{size} {unit}".strip()) if size else unit
            if spec and spec not in specs:
                specs.append(spec)
    if not specs:
        return None, 0
    text = " · ".join(specs)
    if len(text) > 600:                       # 极端多包装品牌（最多 37 个）截断，计数保留
        text = text[:597].rstrip(" ·") + "…"
    return text, len(specs)


def brand_status(pkgs: list[dict]) -> tuple[str, str | None, list[str]]:
    """包装级日期标记 → (status, status_date, note 片段)。

    FEST 的 Status 只有 `A / Aktiv oppføring`，所以品牌「在售」只能由包装聚合：
      - 全部包装带注销日 `AvregDato` → withdrawn；
      - 全部包装带临时停售日 `MidlUtgattDato` → discontinued；
      - 至少一个包装没有任何标记 → active（其余标记写 note，不改结论）；
      - 没有任何包装 → unknown（不把缺失当在售）。

    注意：`Markedsforingsinfo/VarenrUtgaende` **不是**状态标记——它的文本是另一个订货号
    （实测：包装 Varenr=577074 的 VarenrUtgaende=119988），是「新旧订货号」替换链接。
    本函数不用它判状态（评估报告 §4/§6 把它写作下线标记，入库时已按实测更正）。
    """
    if not pkgs:
        return "unknown", None, ["FEST 品牌条目无包装记录（不能据此判在售）"]
    down = [p for p in pkgs if p.get("avreg") or p.get("midl")]
    if not down:
        return "active", None, []
    dates = sorted({p.get("avreg") or p.get("midl") or ""
                    for p in down if (p.get("avreg") or p.get("midl"))})
    last = dates[-1] if dates else None
    notes: list[str] = []
    if len(down) == len(pkgs):
        if all(p.get("avreg") for p in pkgs):
            notes.append(f"全部 {len(pkgs)} 个包装已注销（AvregDato {last}）")
            return "withdrawn", last, notes
        notes.append(f"全部 {len(pkgs)} 个包装临时停售（MidlUtgattDato，最近 {last}）")
        return "discontinued", last, notes
    notes.append(f"{len(down)}/{len(pkgs)} 个包装有下线标记（品牌仍在 FEST 活动条目）")
    return "active", None, notes


def brand_product_id(brand_id: str, varenavn: str) -> str:
    """`NO-<slug>-<sha1(品牌 Id) 前 8 位>`：重跑稳定，不随包装增删变化。"""
    h = hashlib.sha1(brand_id.encode("utf-8")).hexdigest()[:8]
    return f"{CODE}-{slug(varenavn)[:40]}-{h}"


# ---------------------------------------------------------------------------
# 计划（只读库）
# ---------------------------------------------------------------------------
def db_substances(db: sqlite3.Connection) -> dict[str, str]:
    """norm_key(inn_en) → substance_id（精确键表）。"""
    return {norm_key(inn_en): sid for sid, inn_en in
            db.execute("SELECT substance_id, inn_en FROM substance") if inn_en}


def ingredient_name(rec_virk: dict | None, fallback: str = "") -> tuple[str, str]:
    """(英文名, 挪威语名)；英文缺失退回挪威语。"""
    if not rec_virk:
        return fallback, fallback
    no = (rec_virk.get("navn") or "").strip()
    en = (rec_virk.get("navn_en") or "").strip()
    return (en or no or fallback), (no or en or fallback)


def resolve_component(rec_virk: dict | None, fallback: str,
                      index: dict[str, str]) -> dict:
    """成分 → {method, sid 或 new_key, name_en, name_no}；解析不了的进 pending。"""
    name_en, name_no = ingredient_name(rec_virk, fallback)
    if norm_key(name_en) in NON_SUBSTANCE or norm_key(name_no) in NON_SUBSTANCE:
        return {"method": "non-substance", "sid": None, "name_en": name_en,
                "name_no": name_no}
    for cand, kind in name_candidates(name_en):
        sid = index.get(cand)
        if sid:
            return {"method": kind, "sid": sid, "name_en": name_en, "name_no": name_no}
    for cand, kind in name_candidates(name_no):
        sid = index.get(cand)
        if sid:
            return {"method": f"{kind}-no", "sid": sid, "name_en": name_en,
                    "name_no": name_no}
    return {"method": "new", "sid": None, "new_key": norm_key(name_en),
            "name_en": name_en, "name_no": name_no}


def build_plan(db: sqlite3.Connection, snap: dict, new_map: dict[str, list[str]] | None = None,
               limit: int = 0) -> dict:
    """FEST 快照 + 库内成分索引 → 待写产品列表与统计（只读，不写库）。"""
    new_map = new_map or {}
    index = db_substances(db)
    by_brand = packages_by_brand(snap["packages"])
    resolve_variant = _variant_resolver(db)

    stats: Counter = Counter()
    pending: dict[str, list[str]] = {}
    products: list[dict] = []

    brands = list(snap["brands"].values())
    if limit:
        brands = brands[:limit]
    for b in brands:
        bid = b["id"]
        name = b["varenavn"]
        if not name:
            stats["skip_no_name"] += 1
            continue
        pkgs = by_brand.get(bid, [])
        status, status_date, status_notes = brand_status(pkgs)
        stats[f"status_{status}"] += 1
        pack, n_specs = pack_text(bid, pkgs)
        if n_specs > 1:
            stats["multi_pack"] += 1

        # --- 成分 ---
        comps: list[dict] = []

        def add_component(ref: str, rec_vms: dict | None, with_strength: bool) -> None:
            """解析一个引用 → comps；pending/不可识别只计数，不猜。"""
            rec_virk = snap["virk"].get(rec_vms["ref"] if rec_vms else ref)
            res = resolve_component(rec_virk, rec_vms["ref"] if rec_vms else ref, index)
            if res["method"] == "non-substance":
                stats["skip_non_substance"] += 1
                return
            if res["method"] == "new":
                pending.setdefault(res["new_key"], [res["name_en"], res["name_no"]])
                mapped = new_map.get(res["new_key"])
                if not mapped:
                    stats["pending_new_components"] += 1
                    return
                vid = mapped[1]
                stats["method_new"] += 1
            else:
                vid = resolve_variant(res["sid"], res["name_en"])
                if not vid:
                    stats["skip_no_variant"] += 1
                    return
                stats[f"method_{res['method']}"] += 1
            if with_strength and rec_vms:
                value = strength_value_of(rec_vms["styrke"])
                unit, _rule = unit_of(rec_vms["unit"])
                per_v, per_u = denom_of(rec_vms["nevner"], rec_vms["nevner_u"])
            else:
                value = unit = per_v = per_u = None
                stats["components_without_strength"] += 1
            comps.append({"variant_id": vid, "strength_value": value, "strength_unit": unit,
                          "per_volume_value": per_v, "per_volume_unit": per_u,
                          "name_en": res["name_en"], "name_no": res["name_no"]})

        for ref in b["refs"]:
            rec_vms = snap["vms"].get(ref)
            if not rec_vms:
                stats["skip_missing_vms"] += 1
                continue
            add_component(ref, rec_vms, with_strength=True)
        for ref in b["refs_no_strength"]:
            if ref not in snap["virk"]:
                stats["skip_missing_virk"] += 1
                continue
            add_component(ref, None, with_strength=False)
        if not comps:
            stats["products_without_component"] += 1

        # --- 名字 ---
        names: list[tuple[str, str, int]] = [(name, "trade", 1)]
        if len(comps) == 1:
            # 单方产品挂通用名（挪/英各一条），搜 "Paracetamol"/"Kodein" 能命中；
            # 复方不挂：否则每个成分名都会把整张复方算进去，凭空造「同名不同药」。
            for raw in (comps[0]["name_no"], comps[0]["name_en"]):
                if raw and norm_key(raw) != norm_key(name):
                    names.append((raw, "inn", 0))

        notes = list(status_notes)
        if n_specs > 1:
            notes.append(f"含 {n_specs} 种包装规格")
        if not comps:
            notes.append("FEST 未给成分引用（仅品牌条目）")
        elif all(c["strength_value"] is None for c in comps):
            notes.append("无含量记录（FEST 仅成分名）")
        if b["preparattype"] and b["preparattype"] != "Legemiddel":
            notes.append(f"Preparattype: {b['preparattype']}")
        if b["status"] != "A":
            notes.append(f"FEST Status={b['status'] or '?'}")

        products.append({
            "product_id": brand_product_id(bid, name),
            "country": CODE,
            "dosage_form": b["form"] or "unknown",
            "form_base": form_base_no(b["form"]),
            "route": route_no(b["route_dn"]),
            "release": release_no(b["form"]),
            "pack": pack,
            "mah": b["produsent"] or None,
            "approval_id": None,          # FEST 无注册号（MT），订货号不是注册号
            "category": b["preparattype"] or None,
            "is_branded": 1,
            "status": status,
            "status_date": status_date,
            "source_id": SOURCE_ID,
            "source_url": b["smpc"] or DOWNLOAD_PAGE,
            "retrieved_at": "",
            "note": "; ".join(notes) or None,
            "names": names,
            "components": comps,
            "atc": b["atc"] if len(comps) == 1 else "",
            "atc_name": b["atc_name"] if len(comps) == 1 else "",
            "brand_id": bid,
            "varenr_count": len({p["varenr"] for p in pkgs if p.get("varenr")}),
        })
        stats["products"] += 1
        stats["components"] += len(comps)
        if b["atc"]:
            stats["products_atc"] += 1
        if pack:
            stats["products_with_pack"] += 1
        if b["produsent"]:
            stats["products_with_mah"] += 1
        if comps:
            if any(c["strength_value"] is not None for c in comps):
                stats["products_with_strength"] += 1
            else:
                stats["products_strength_missing"] += 1

    stats["packages"] = len(snap["packages"])
    stats["brands_in_snapshot"] = len(snap["brands"])
    stats["brands_planned"] = len(products)
    stats["pending_new_substances"] = len(pending)
    return {"products": products, "stats": dict(stats), "pending_new": pending,
            "hentet": snap["hentet"]}


# ---------------------------------------------------------------------------
# 写库
# ---------------------------------------------------------------------------
def write_plan(db: sqlite3.Connection, plan: dict) -> dict:
    """把计划写进正式表（调用方管事务）；返回按表统计的写入行数。"""
    written: Counter = Counter()
    for p in plan["products"]:
        written["product"] += common.write_product(db, p)
        for raw, ntype, primary in p["names"]:
            for key, value in common.write_name(
                    db, p["product_id"], raw, ntype, primary, SOURCE_ID, normalize).items():
                written[key] += value
        for ord_, comp in enumerate(p["components"]):
            written["product_component"] += common.write_component(
                db, p["product_id"], ord_, comp["variant_id"],
                {"value": comp["strength_value"], "unit": comp["strength_unit"],
                 "per_volume_value": comp["per_volume_value"],
                 "per_volume_unit": comp["per_volume_unit"]})
        # ATC 只给单方产品、且只回填空值（不覆盖别国已有 ATC）
        if p.get("atc"):
            written["substance_atc"] += db.execute(
                "UPDATE substance SET atc=?, atc_name=COALESCE(NULLIF(atc_name,''), ?)"
                " WHERE substance_id=(SELECT v.substance_id FROM variant v WHERE v.variant_id=?)"
                " AND (atc IS NULL OR atc='')",
                (p["atc"], p.get("atc_name") or None, p["components"][0]["variant_id"])).rowcount
    return dict(written)


def _created_names(plan: dict, existing_keys: set[str],
                   existing_pairs: set[tuple[str, str]]) -> tuple[list[str], list[list[str]]]:
    keys: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for p in plan["products"]:
        for raw, _ntype, _primary in p["names"]:
            nm = normalize(raw)
            if not nm or not nm.norm:
                continue
            if nm.norm not in existing_keys:
                keys.add(nm.norm)
            if (nm.norm, raw) not in existing_pairs:
                pairs.add((nm.norm, raw))
    return sorted(keys), [list(x) for x in sorted(pairs)]


def cmd_dry_run(args: argparse.Namespace) -> int:
    """解析快照 + 只读库出计划，打印统计（不写库）。"""
    t0 = time.perf_counter()
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    snap = load_snapshot()
    db = common.connect(db_path, write=False)
    try:
        first = build_plan(db, snap)
        # 两段式演练：真实 apply 会先建 pending 新成分再重跑计划；干跑用假 id 模拟，
        # 这样成分行数/无成分产品数与正式写库口径一致（不写库）。
        fake = {key: [f"sim-sub-{i}", f"sim-var-{i}"]
                for i, key in enumerate(sorted(first["pending_new"]))}
        plan = build_plan(db, snap, fake)
        countries = db.execute(
            "SELECT COUNT(*) FROM product WHERE country=?", (CODE,)).fetchone()[0]
    finally:
        db.close()
    stats = plan["stats"]
    stats["pending_new_substances"] = len(first["pending_new"])
    products = plan["products"]
    forms = Counter(p["form_base"] for p in products)
    releases = Counter(p["release"] for p in products)
    routes = Counter(p["route"] for p in products)
    coverage = {
        "form_base": dict(forms.most_common()),
        "form_other": forms.get("other", 0) + forms.get("unknown", 0),
        "release": dict(releases.most_common()),
        "route_missing": routes.get(None, 0),
    }
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "no_dry_run.json"
    out.write_text(json.dumps({"hentet": plan["hentet"], "stats": stats, "coverage": coverage,
                               "pending_new": plan["pending_new"]},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("== 挪威 FEST 2.5.1 干跑 ==")
    print(f"  快照数据截止（HentetDato）：{plan['hentet'] or '?'}")
    print(f"  现有 NO 产品 {countries:,} 条；本次计划 {stats['brands_planned']:,} 个品牌 / "
          f"{stats['packages']:,} 个包装 → {stats['components']:,} 个成分行")
    print(f"  待新建成分 {stats['pending_new_substances']:,}（只收 FEST 英文/挪威语名，来源可核）")
    for key in ("status_active", "status_discontinued", "status_withdrawn", "status_unknown",
                "products_with_pack", "multi_pack", "products_with_mah", "products_atc",
                "products_with_strength", "products_strength_missing",
                "products_without_component", "components_without_strength",
                "method_exact", "method_paren", "method_ion", "method_salt",
                "method_inn_alias", "method_exact-no", "method_new",
                "skip_missing_vms", "skip_missing_virk", "skip_no_variant"):
        if stats.get(key):
            print(f"    {key:<28}{stats[key]:>8,}")
    print(f"  剂型 form_base：{', '.join(f'{k}={v}' for k, v in forms.most_common(8))}"
          f"（other/unknown {coverage['form_other']}）")
    print(f"  释放机制：" + ", ".join(f"{k}={v}" for k, v in releases.most_common())
          + f"；途径缺失 {routes.get(None, 0)}")
    print(f"  明细 → {out.relative_to(ROOT)}（{time.perf_counter() - t0:.1f}s）")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """写 NO 国别层（真实库需 --allow-real）：source + product/name/component + ingest_run。"""
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    common.guard_real(db_path, REAL_DB, "apply", args.allow_real)
    if not db_path.exists():
        raise SystemExit(f"库不存在：{db_path}（先复制一份副本演练）")
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    t0 = time.perf_counter()
    sha_before = common.sha256_file(db_path)
    snap = load_snapshot()
    hentet = (snap["hentet"] or "")[:10] or None
    fetched = _retrieved_at()

    db = common.connect(db_path, write=False)
    try:
        common.require_country(db, CODE)
        before = common.table_counts(db, CODE, SOURCE_ID)
        existing_keys = {r[0] for r in db.execute("SELECT key_id FROM name_key")}
        existing_pairs = {(r[0], r[1]) for r in db.execute("SELECT key_id, raw FROM name_variant")}
        first = build_plan(db, snap)
    finally:
        db.close()
    pending = first["pending_new"]

    db = common.connect(db_path, write=True)
    created_substances: list[str] = []
    new_map: dict[str, list[str]] = {}
    try:
        db.execute("BEGIN IMMEDIATE")
        source_meta = dict(SOURCE_META, retrieved_at=fetched, data_as_of=hentet)
        source_existed, source_before = common.insert_source(db, SOURCE_ID, source_meta)
        removed = db.execute("DELETE FROM product WHERE country=? AND source_id=?",
                             (CODE, SOURCE_ID)).rowcount
        for key, (name_en, _name_no) in sorted(pending.items()):
            sid, vid, created_sub, _created_var = common.ensure_substance(
                db, name_en, SOURCE_ID, fetched, confidence="high")
            new_map[key] = [sid, vid]
            if created_sub:
                created_substances.append(sid)
        plan = build_plan(db, snap, new_map)
        for p in plan["products"]:
            p["retrieved_at"] = fetched
        written = write_plan(db, plan)
        common.write_ingest_run(
            db, f"{SOURCE_ID}-{fetched}", SOURCE_ID, fetched,
            plan["stats"].get("brands_in_snapshot", 0), plan["stats"].get("products", 0),
            {"country": CODE, "layer": "country", "source_id": SOURCE_ID,
             "data_as_of": hentet, "packages": plan["stats"].get("packages"),
             "components": written.get("product_component", 0),
             "new_substances": len(created_substances),
             "note": "FEST 处方链数据服务；只有活动条目；无注册号；不存价格/SmPC 正文"})
        db.commit()
        after = common.table_counts(db, CODE, SOURCE_ID)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    created_keys, created_pairs = _created_names(plan, existing_keys, existing_pairs)
    manifest = {
        "tool": "etl/ingest_no.py",
        "db": str(db_path),
        "country": CODE,
        "source_id": SOURCE_ID,
        "run_id": f"{SOURCE_ID}-{fetched}",
        "created_at": common.now(),
        "data_as_of": hentet,
        "snapshot": {
            "zip_bytes": ZIP_PATH.stat().st_size,
            "zip_sha256": sha256_file(ZIP_PATH),
            "xml_bytes": _inner_bytes(),
            "hentet": snap["hentet"],
            "brands": len(snap["brands"]),
            "packages": len(snap["packages"]),
        },
        "db_sha256_before": sha_before,
        "db_sha256_after": common.sha256_file(db_path),
        "product_ids": [p["product_id"] for p in plan["products"]],
        "created_name_keys": created_keys,
        "created_name_variants": created_pairs,
        "created_substances": created_substances,
        "source_existed": source_existed,
        "source_before": source_before,
        "counts_before": before,
        "counts_after": after,
        "counts_planned": plan["stats"],
        "written": written,
        "removed_products_before_write": removed,
        "rollback_hint": (
            "python etl/ingest_no.py --rollback --allow-real --db <同一个库> --manifest <本文件>；"
            "或从 data/backups/drugs-*-no.db 恢复。校验：SELECT COUNT(*) FROM product"
            " WHERE country='NO' AND source_id='dmp_fest' 应为 0。"),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== NO（DMP FEST 2.5.1）写入完成 ===")
    print(json.dumps({"written": written, "counts_before": before, "counts_after": after},
                     ensure_ascii=False, indent=1))
    print(f"  数据截止 {hentet} · 新成分 {len(created_substances):,} · 旧 NO 行删除 {removed}")
    print(f"  撤销清单 {manifest_path.relative_to(ROOT)}")
    print(f"  db sha256 {sha_before[:16]}… → {manifest['db_sha256_after'][:16]}… · "
          f"耗时 {time.perf_counter() - t0:.1f}s")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    """按 manifest 只删本次写入的行，并核对是否回到写前计数。"""
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    common.guard_real(db_path, REAL_DB, "rollback", args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单：{manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed, after, diff = common.rollback(db_path, manifest, CODE, SOURCE_ID)
    nonzero = {k: v for k, v in diff.items() if v}
    print("=== NO（DMP FEST）回滚完成 ===")
    print(json.dumps({"removed": removed, "counts_after": after,
                      "diff_vs_counts_before": diff}, ensure_ascii=False, indent=1))
    if nonzero:
        print(f"  !! 与写前计数不一致：{nonzero}")
        return 1
    print("  逐表差异 0（已回到写前基线）")
    return 0


def _retrieved_at() -> str:
    """抓取日（fetch_meta.retrieved_at 的日期部分）；没有 manifest 就用今天。"""
    if FETCH_META.exists():
        meta = json.loads(FETCH_META.read_text(encoding="utf-8"))
        value = (meta.get("retrieved_at") or "")[:10]
        if RE_ISO_DATE.match(value):
            return value
    return datetime.now(timezone.utc).date().isoformat()


def _inner_bytes() -> int | None:
    if not ZIP_PATH.exists():
        return None
    with zipfile.ZipFile(ZIP_PATH) as zf:
        info = next((i for i in zf.infolist() if i.filename.lower().endswith(".xml")), None)
    return info.file_size if info else None


# ---------------------------------------------------------------------------
# 自检（离线：不联网、不读库）
# ---------------------------------------------------------------------------
def self_check() -> int:
    """断言映射与解析口径（CI 无快照/无库也能跑）。"""
    checks: list[tuple[str, object, object]] = [
        ("fold_no Øyedråper", fold_no("Øyedråper, oppløsning"), "oyedraper opplosning"),
        ("form Tablett", form_base_no("Tablett"), "tablet"),
        ("form Depottablett", form_base_no("Depottablett"), "tablet"),
        ("form Brusetablett", form_base_no("Brusetablett"), "effervescent"),
        ("form Kapsel, hard", form_base_no("Kapsel, hard"), "capsule"),
        ("form Injeksjonsvæske", form_base_no("Injeksjonsvæske, oppløsning"), "injection"),
        ("form Pulver til injeksjonsvæske",
         form_base_no("Pulver til injeksjonsvæske, oppløsning"), "injection"),
        ("form Inhalasjonspulver", form_base_no("Inhalasjonspulver"), "inhalation"),
        ("form Stikkpille", form_base_no("Stikkpille"), "suppository"),
        ("form Vagitorie", form_base_no("Vagitorie"), "pessary"),
        ("form Medisinsk gass", form_base_no("Medisinsk gass, komprimert"), "gas"),
        ("form Mikstur", form_base_no("Mikstur, oppløsning"), "liquid"),
        ("form Granulat", form_base_no("Granulat til mikstur, suspensjon"), "powder"),
        ("release Depot", release_no("Depottablett"), "ER"),
        ("release Entero", release_no("Enterotablett"), "DR"),
        ("release Modifisert", release_no("Tablett med modifisert frisetting"), "MR"),
        ("release none", release_no("Tablett"), "none"),
        ("route Oral", route_no("Oral bruk"), "oral"),
        ("route IV", route_no("Intravenøs bruk"), "intravenous"),
        ("route 未指定", route_no("Administrasjonsvei ikke spesifisert"), None),
        ("unit mikrog", unit_of("mikrog")[0], "mcg"),
        ("unit IE", unit_of("IE")[0], "IU"),
        ("unit mg", unit_of("mg")[0], "mg"),
        ("strength value dot", strength_value_of("40"), 40.0),
        ("strength value comma", strength_value_of("0,5"), 0.5),
        ("strength value junk", strength_value_of("n/a"), None),
        ("form lyofilisat", form_base_no("Sublingvalt lyofilisat"), "tablet"),
        ("form sublingualfilm", form_base_no("Sublingvalfilm"), "film"),
        ("form leech", form_base_no("Medisinsk blodigle"), "device"),
        ("route Urethral", route_no("Urethral bruk"), "urethral"),
        ("denom ml", denom_of("5", "ml"), (5.0, "mL")),
        ("name candidate ion", "copper" in candidate_keys("Copper(II) ion"), True),
        ("name candidate salt",
         "cetirizine" in candidate_keys("Cetirizine dihydrochloride"), True),
        ("name candidate salt hydrate",
         "pramipexole" in candidate_keys("Pramipexole dihydrochloride monohydrate"), True),
        ("name candidate element guard", salt_base("Potassium chloride"), ""),
        ("alias paracetamol", "acetaminophen" in candidate_keys("Paracetamol"), True),
        ("alias acetylsalicylic", "aspirin" in candidate_keys("Acetylsalicylic acid"), True),
        ("status all avreg",
         brand_status([{"avreg": "2026-10-12", "midl": ""}])[0], "withdrawn"),
        ("status tmp stop",
         brand_status([{"avreg": "", "midl": "2026-10-12"}])[0], "discontinued"),
        ("status mixed",
         brand_status([{"avreg": "", "midl": ""},
                       {"avreg": "", "midl": "2026-10-12"}])[0], "active"),
        ("status no package", brand_status([])[0], "unknown"),
        ("pack text", pack_text("B1", [{"infos": [
            {"brand_ref": "B1", "pakningsstr": "100", "enhet_dn": "stykk", "enhet": "stk"}]}]),
         ("100 stykk", 1)),
        ("product id stable", brand_product_id("ID_X", "Thylip") ==
         brand_product_id("ID_X", "Thylip"), True),
    ]
    failed = 0
    for label, got, want in checks:
        ok = got == want
        failed += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'} {label}: {got!r}")
    print(f"self-check：{len(checks) - failed}/{len(checks)} 通过")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="挪威 DMP FEST 2.5.1 → data/drugs.db")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fetch", action="store_true", help="抓快照到 data/raw/no/（幂等）")
    mode.add_argument("--dry-run", action="store_true", help="解析 + 统计，不写库（默认）")
    mode.add_argument("--apply", action="store_true", help="事务写库（真实库需 --allow-real）")
    mode.add_argument("--rollback", action="store_true", help="按 manifest 回滚")
    mode.add_argument("--self-check", action="store_true", help="离线断言，不联网不读库")
    ap.add_argument("--force", action="store_true", help="--fetch 时重下（默认已存在就跳过）")
    ap.add_argument("--allow-real", action="store_true",
                    help="允许对 data/drugs.db 写入/回滚（写库窗口；先备份）")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--manifest", type=Path,
                    default=MANIFEST_DIR / f"no_ingest_manifest_{datetime.now().date():%Y%m%d}.json")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个品牌（试跑用）")
    args = ap.parse_args(argv)

    if args.self_check:
        return self_check()
    if args.fetch:
        fetch(force=args.force)
        return 0
    if args.apply:
        return cmd_apply(args)
    if args.rollback:
        return cmd_rollback(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
