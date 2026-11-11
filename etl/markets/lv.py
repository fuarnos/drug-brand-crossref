# -*- coding: utf-8 -*-
"""拉脱维亚 ZVA 国家药品注册库（Latvijas Zāļu reģistrs）ETL 骨架 —— **只做干跑，不写库**。

许可（已取证，✅ 可再发布）
--------------------------
`data.gov.lv` 数据集 `latvijas-zalu-registrs`（发布者 **Zāļu valsts aģentūra, ZVA**）的元数据写：
`license_title = "CC0 1.0"`、`license_url = https://creativecommons.org/publicdomain/zero/1.0/`。
→ **CC0 1.0（公有领域贡献，无署名义务、无 share-alike）**，是本项目目前许可条件最宽的一个源。
本站仍按全站统一口径署名「Zāļu valsts aģentūra (ZVA) · Latvijas Zāļu reģistrs」+ 数据截止日。

评估依据：`reports/2026-11-12-eu-member-states-scan.md` §12.1 / §14③。

本阶段为什么不写库
------------------
许可没问题，**但 UI 改版未完成（用户 2026-11-12 定「先取数，等 UI 改完再上线」）**，且
`product.country` 的 CHECK 枚举还没有 LV（要 `db/migrate_country_lv.py` 重建表）。因此本脚本
**故意不提供 `--apply` / `--rollback`**，只有 `--fetch` / `--dry-run` / `--self-check`。
写库路径等上线窗口另开任务，按 `etl/ingest_eu.py` 的 `--apply` / `--rollback` / `--manifest` 三段式补。

数据源与形状
------------
`https://dati.zva.gov.lv/zalu-registrs/export/HumanProducts.xml.zip`（3.0 MB，解包 125 MB，**每日**）
  - 根 `human_product_export` → `<products>` → 每行一个 `<product>` 平铺元素（**无嵌套、无属性**）。
  - 实测 **40,600 个 `<product>`**，每行 49 个固定子元素（见 `REQUIRED_TAGS`）。
  - 一条 `<product>` = **一个包装/规格级条目**（`product_id` 形如 `00-0003-01` 或 `EU/1/00/129/001`），
    **不是药**：40,600 行只对应 18,766 个 `authorisation_no`、6,261 个 `medicine_name`、
    2,053 个 `active_substance` 串。商品名不是主键这条底线在这里同样是硬约束。
  - 名字是**双语**：`original_name`（英文原名）+ `medicine_name`（拉脱维亚语，`original_name` 的拉语版，
    两者不是独立来源，**不要当成两个市场名**）。
`https://dati.zva.gov.lv/zalu-registrs/export/zr-prd-status.csv`（1.4 MB）
  - 列：`product_id, stock_status, stock_wholesalers, stock_total, stock_status_pharm,
    stock_total_pharm, mah_status, mah_avail_date, mah_withdraw_date, mah_next_avail_date`
  - 40,600 行，与 XML `product_id` **1:1** 对应（实测 0 缺失、0 重复）。

状态三开关（这一节最重要，页面口径必须照做）
------------------------------------------
XML 里有三个日期/标记开关，**必须联合判**，任何一个单独用都会把撤回药算成在售：

| 开关 | 取值（实测） | 含义 |
|---|---|---|
| `status` | `1` = 39,856 / `0` = 737 / `2` = 7 | 注册有效性。**实测 `status='0'` 的 737 行全部带 `sell_stop_date`** |
| `prd_removed` | `0` = 40,310 / `1` = 290 | 是否已从注册库移除 |
| `sell_stop_date` | 空 = 39,836 / 有日期 = 764 | 停售日期 |

CSV 侧还有两个**更接近「在不在市」**的信号，容易和上面三个混淆：

| 字段 | 取值（实测） | 含义 |
|---|---|---|
| `mah_status` | `1` = 5,076 / `0` = 1,605 / `2` = 33,919 | MAH 侧上市状态：1 可供、0 已撤回、**2 = 注册了但没在拉脱维亚上市** |
| `stock_status` / `stock_status_pharm` | 1 = 3,904 / 3,954 | 当下是否有库存（批发/药房） |

**结论（本脚本采用的口径）**：

- `active`（在售，进 `coverage.active`）= `status=='1'` ∧ `prd_removed=='0'` ∧ 无 `sell_stop_date`
  ∧ `mah_status=='1'` ∧ 程序**不是**平行进口 / 平行分销 / 未注册药品 → **4,551 行**。
- `registered_ok`（注册有效但未必在售）≈ 39,8xx 行 —— **不得**当成在售上报。
- **平行进口（`Paralēlais imports`，733 行）与未注册药品（`Nereģistrētas zāles`，12 行）单独计数，
  不计入 `active`**（平行分销 62 行同理）：这些行说的是「从别国进口来卖」，不是拉脱维亚自己的上市记录。
- 只按 `status`/`prd_removed` 判会得到 38,759 行「active」，比真实在售高 **8.5 倍**——这就是本节存在的理由。

与 EU 层的去重（写库前必须知道）
--------------------------------
`authorisation_procedure = "Eiropas centralizētā reģistrācijas procedūra"` 有 **13,574 行**，
去掉包装段（`EU/1/00/129/001` → `EU/1/00/129`）后是 **1,562 个 EU 药号**；本库 `region='EU'` 那层有
2,019 个唯一 `approval_id`，**交集 1,561 个药号 / 覆盖 13,571 行**。
→ LV 的集中审批行**几乎全部**是 EU 层已有的药，只是包装级细节 + 拉语名 + 价格。
`coverage` 与页面必须分组呈现（区域层 vs 国家层），不要把同一支药算两次。

复用（不另起一套）
------------------
- 规格：`etl/normalize_name.py:normalize()` + `etl/normalize_strength.py:norm_unit()`；
  本脚本只做输入预整形（`SV`/`IU`/`IE` → `iu`、`microgram` → `mcg`、缺省分母补 `1`），**不做剂量换算**。
- 成分：`etl/ingest_sg_hsa.py:SgMapper.map_basic()`；前面加一层拉丁语词尾候选（`-um` / `-i` 去尾），
  只用于生成候选写法，命中与否仍由库里 `substance` 决定。
- 剂型：`etl/ingest_openfda_ndc.py:form_base_of()`。

CLI
---
    python etl/markets/lv.py --fetch        # 抓 ZIP + 状态表 + CC0 元数据到 data/raw/lv_zalu_20261112/
    python etl/markets/lv.py --dry-run      # 默认：读缓存 → 解析 → 统计（只读开库，不写库）
    python etl/markets/lv.py --self-check   # 离线断言：49 标签 / 状态规则 / 变音折叠 / 无 --apply
    python etl/markets/lv.py --dry-run --db .tmp/lv-ingest/lv.db

产物：`.tmp/lv-ingest/lv_dry_run.json`（统计）。`data/raw/`、`.tmp/` 都不入库。
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from ingest_openfda_ndc import form_base_of, slug  # noqa: E402
from ingest_sg_hsa import SgMapper  # noqa: E402
from normalize_name import normalize  # noqa: E402
from normalize_strength import norm_unit  # noqa: E402

# Windows 控制台默认 GBK，拉脱维亚语 ā/č/ē/ģ/ī/ķ/ļ/ņ/š/ū/ž 会让 print 抛 UnicodeEncodeError。
try:  # pragma: no cover - 只影响终端显示
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

URL_ZIP = "https://dati.zva.gov.lv/zalu-registrs/export/HumanProducts.xml.zip"
URL_STATUS = "https://dati.zva.gov.lv/zalu-registrs/export/zr-prd-status.csv"
URL_DATASET = "https://data.gov.lv/dati/lv/dataset/latvijas-zalu-registrs"
URL_CKAN = ("https://data.gov.lv/api/3/action/package_search"
            "?q=Latvijas%20Z%C4%81%C4%BCu%20re%C4%A3istrs")
RAW = ROOT / "data" / "raw" / "lv_zalu_20261112"
ZIP_PATH = RAW / "HumanProducts.xml.zip"
STATUS_PATH = RAW / "zr-prd-status.csv"
FETCH_META = RAW / "fetch_meta.json"
LICENSE_DIR = RAW / "license"
LICENSE_JSON = LICENSE_DIR / "data.gov.lv_package_search.json"
DEFAULT_DB = ROOT / "data" / "drugs.db"
WORK = ROOT / ".tmp" / "lv-ingest"
XML_ENTRY = "HumanProducts.xml"

SOURCE_ID = "zva_lv_register"
LICENCE = {
    "spdx": "CC0-1.0",
    "title": "CC0 1.0 Universal (Public Domain Dedication)",
    "url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "declared_in": URL_DATASET,
    "attribution_required": False,
    # 本站口径：CC0 不强制署名，但 About 仍按全站统一格式署名 + 数据截止日。
    "site_attribution": "Zāļu valsts aģentūra (ZVA) · Latvijas Zāļu reģistrs · CC0 1.0",
}
UA = "drug-brand-crossref/0.1 (dry-run only; +https://github.com/fuarnos/drug-brand-crossref)"

# 49 个固定子元素（2026-11-12 实测，每个 product 都有）。
REQUIRED_TAGS = (
    "product_id", "original_name", "medicine_name", "short_name", "authorisation_no",
    "date_of_authorisation", "authorisation_validity_ttl", "inter_code", "legal_status",
    "legal_bases_code", "legal_bases_text", "strength", "strength_lv", "pharmaceutical_form",
    "pharmaceutical_form_lv", "is_approved_for_kids", "active_substance",
    "marketing_authorisation_holder", "manufacturer", "parallel_importer", "parallel_importer_lv",
    "parallel_importer_en", "parallel_distributor", "parallel_distributor_lv",
    "parallel_distributor_en", "exp_country_lv", "exp_country_en", "status", "remove_date",
    "sell_stop_date", "prd_removed", "prd_sell_stop_date", "atc_code", "authorisation_procedure",
    "package_leaflet", "pil_file_hash", "summary_of_product_characteristics", "smpc_file_hash",
    "product_strength", "package", "package_en", "package_size", "store_conditions", "labels",
    "package_labels", "container_labels", "product_price_without_vat_eur",
    "product_price_with_vat_eur", "info_risk_minimisation",
)
EXPECTED_PRODUCTS = 40_600  # 2026-11-12 快照实测；变了说明数据方改了行结构，self-check 会报

# 程序类型：这三类「不是本国上市记录」，单独计数、不进 active。
PROC_PARALLEL_IMPORT = "Paralēlais imports"          # 平行进口
PROC_PARALLEL_DIST = "Paralēlā izplatīšana"          # 平行分销
PROC_UNREGISTERED = "Nereģistrētas zāles"            # 未注册药品
NON_DOMESTIC_PROCS = frozenset({PROC_PARALLEL_IMPORT, PROC_PARALLEL_DIST, PROC_UNREGISTERED})
PROC_CENTRALISED = "Eiropas centralizētā reģistrācijas procedūra"


# ---------------------------------------------------------------- 小工具
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """只读开库（`mode=ro`）：本脚本没有任何写库路径。"""
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    return db


# 拉脱维亚语字母 → ASCII（检索用；库里的原文一律不动）。
_LV_FOLD = str.maketrans({
    "ā": "a", "č": "c", "ē": "e", "ģ": "g", "ī": "i", "ķ": "k",
    "ļ": "l", "ņ": "n", "š": "s", "ū": "u", "ž": "z",
    "Ā": "A", "Č": "C", "Ē": "E", "Ģ": "G", "Ī": "I", "Ķ": "K",
    "Ļ": "L", "Ņ": "N", "Š": "S", "Ū": "U", "Ž": "Z",
})


def fold_lv(text: str) -> str:
    """拉脱维亚语变音折叠 + 小写：`Šķīdums` → `skidums`。

    先查表（ā/č/ē/ģ/ī/ķ/ļ/ņ/š/ū/ž 是「带符字母」，NFKD 拆不出基字母），
    再走 NFKD 兜住西欧重音（é/ü…）。只用于比较与检索，不写库。
    """
    s = (text or "").translate(_LV_FOLD)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- 抓取
def _grab(url: str, dest: Path, accept: str = "*/*") -> dict:
    """单文件抓取（带 UA、timeout）。返回 url/bytes/sha256/头/时间。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": UA, "Accept": accept})
    t0 = time.perf_counter()
    with urlopen(req, timeout=300) as resp:  # noqa: S310 - 固定官方 URL
        status = getattr(resp, "status", None)
        headers = {k.lower(): v for k, v in resp.headers.items()}
        blob = resp.read()
    if not blob:
        raise SystemExit(f"抓取返回 0 字节：{url}")
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(blob)
    tmp.replace(dest)
    return {
        "url": url, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
        "http_status": status, "last_modified": headers.get("last-modified"),
        "etag": headers.get("etag"), "content_type": headers.get("content-type"),
        "fetched_at": _now(), "secs": round(time.perf_counter() - t0, 1),
    }


def cmd_fetch(_args: argparse.Namespace) -> int:
    """抓 ZIP + 状态码表 + CC0 元数据到 `data/raw/lv_zalu_20261112/`。"""
    print("=== LV ZVA 抓取 ===")
    meta: dict[str, dict] = {}
    meta["zip"] = _grab(URL_ZIP, ZIP_PATH)
    meta["status_csv"] = _grab(URL_STATUS, STATUS_PATH)
    meta["ckan"] = _grab(URL_CKAN, LICENSE_JSON, "application/json")

    # 许可自证：从 CKAN 元数据里把该数据集的 licence 字段抓出来，写进 fetch_meta。
    lic_seen = {}
    with contextlib.suppress(Exception):
        payload = json.loads(LICENSE_JSON.read_text(encoding="utf-8"))
        for pkg in payload["result"]["results"]:
            if pkg.get("name") == "latvijas-zalu-registrs":
                lic_seen = {
                    "name": pkg.get("name"), "title": pkg.get("title"),
                    "license_title": pkg.get("license_title"),
                    "license_url": pkg.get("license_url"),
                    "organization": (pkg.get("organization") or {}).get("title"),
                    "metadata_modified": pkg.get("metadata_modified"),
                }
                break
    if not lic_seen:
        raise SystemExit("CKAN 元数据里没找到 latvijas-zalu-registrs——许可自证失败，先人工核对。")

    meta["license"] = {**LICENCE, "ckan_dataset": lic_seen, "dataset_page": URL_DATASET}
    FETCH_META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    for key in ("zip", "status_csv"):
        m = meta[key]
        print(f"  {key:11s} HTTP {m['http_status']} · {m['bytes']:,} B · sha256 {m['sha256'][:16]}…"
              f" · Last-Modified {m['last_modified']}")
    print(f"  许可        {lic_seen['license_title']}（{lic_seen['license_url']}）")
    print(f"  元数据      {FETCH_META.relative_to(ROOT)}")
    return 0


# ---------------------------------------------------------------- 解析：状态表
def load_status(path: Path = STATUS_PATH) -> dict[str, dict]:
    """`zr-prd-status.csv` → {product_id: row}。缺文件直接报错，不静默降级。"""
    if not path.exists():
        raise SystemExit(f"缺状态表：{path}（先跑 `python etl/markets/lv.py --fetch`）")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    out: dict[str, dict] = {}
    for row in csv.DictReader(text.splitlines()):
        pid = (row.get("product_id") or "").strip()
        if pid:
            out[pid] = row
    if not out:
        raise SystemExit(f"状态表是空的：{path}")
    return out


# ---------------------------------------------------------------- 解析：XML 流
def iter_products(zip_path: Path = ZIP_PATH):
    """流式读 ZIP 里的 `HumanProducts.xml`，逐个 yield `{tag: text}`。

    125 MB 解包后不能整棵读进内存：边解析边 `clear()`，峰值只跟单个 `<product>` 走。
    """
    if not zip_path.exists():
        raise SystemExit(f"缺快照：{zip_path}（先跑 `python etl/markets/lv.py --fetch`）")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if XML_ENTRY not in names:
            raise SystemExit(f"ZIP 里没有 {XML_ENTRY}，实际：{names}")
        with zf.open(XML_ENTRY) as fh:
            for _event, el in ET.iterparse(fh, events=("end",)):
                if el.tag != "product":
                    continue
                row = {child.tag: (child.text or "").strip() for child in el}
                el.clear()
                yield row


# ---------------------------------------------------------------- 状态判定
def classify(row: dict, status_row: dict | None) -> dict:
    """三开关 + CSV 上市/库存信号 → 统一的判定字典（**唯一的在售口径来源**）。"""
    s = status_row or {}
    proc = row.get("authorisation_procedure", "")
    registered = row.get("status") == "1"            # 注册有效性
    removed = row.get("prd_removed") == "1"          # 已移除
    sell_stopped = bool(row.get("sell_stop_date"))   # 有停售日期
    mah_status = s.get("mah_status", "")
    in_stock_wh = s.get("stock_status") == "1"
    in_stock_ph = s.get("stock_status_pharm") == "1"
    is_parallel = proc in (PROC_PARALLEL_IMPORT, PROC_PARALLEL_DIST)
    is_unregistered = proc == PROC_UNREGISTERED
    registered_ok = registered and not removed and not sell_stopped
    # 在售 = 注册有效 ∧ 未被移除 ∧ 未停售 ∧ MAH 说可供 ∧ 不是平行进口/未注册
    active = (registered_ok and mah_status == "1"
              and not is_parallel and not is_unregistered)
    return {
        "registered": registered, "removed": removed, "sell_stopped": sell_stopped,
        "mah_status": mah_status, "in_stock_wholesale": in_stock_wh, "in_stock_pharmacy": in_stock_ph,
        "procedure": proc, "is_parallel": is_parallel, "is_unregistered": is_unregistered,
        "is_centralised": proc == PROC_CENTRALISED,
        "registered_ok": registered_ok, "active": active,
        # 状态枚举：页面只需要这一个词
        "status": _status_word(active, registered_ok, removed, sell_stopped),
    }


def _status_word(active: bool, registered_ok: bool, removed: bool, sell_stopped: bool) -> str:
    """映到 `product.status` 的枚举（`active`/`discontinued`/`withdrawn`/`unknown`）。

    - 在售 → `active`
    - 注册有效但 MAH 未上市 → `unknown`（**不是 active**，也不是 discontinued）
    - 有停售日期 → `discontinued`
    - 已从注册库移除 → `withdrawn`
    """
    if active:
        return "active"
    if removed:
        return "withdrawn"
    if sell_stopped:
        return "discontinued"
    if registered_ok:
        return "unknown"
    return "unknown"


# ---------------------------------------------------------------- 解析：成分
_LATIN_SALT_HINT = re.compile(
    r"\b(tartras|hydrochloridum|dihydrochloridum|natricum|kalium|calcium|magnesium|"
    r"sulfas|sulfatum|nitras|acetas|citras|phosphatum|maleas|fumaras|succinas|"
    r"mesylas|tosylas|besylas|bromidum|chloridum|iodidum|hydrate?)\b", re.I)

# 拉丁词 → 英文对应词（**只处理词形与盐/阳离子名**，不做任何成分语义替换）。
# 实测拉脱维亚注册库的 `active_substance` 是拉丁学名：`Natrii chloridum`（钠的属格）、
# `Perindoprili argininum`、`Olmesartanum medoxomilum`、`Calcii chloridum dihydricum`。
_LATIN_WORD = {
    # 阳离子（属格 -i）
    "natrii": "sodium", "natrium": "sodium", "kalii": "potassium", "kalium": "potassium",
    "calcii": "calcium", "calcium": "calcium", "magnesii": "magnesium",
    "ammonii": "ammonium", "lithii": "lithium", "zinci": "zinc", "aluminii": "aluminium",
    "ferrosi": "ferrous", "ferri": "ferric",
    # 阴离子 / 盐（-as / -um）
    "chloridum": "chloride", "hydrochloridum": "hydrochloride",
    "dihydrochloridum": "dihydrochloride", "bromidum": "bromide", "iodidum": "iodide",
    "tartras": "tartrate", "bitartras": "bitartrate", "sulfas": "sulfate", "sulfatum": "sulfate",
    "nitras": "nitrate", "acetas": "acetate", "citras": "citrate", "phosphatum": "phosphate",
    "maleas": "maleate", "fumaras": "fumarate", "succinas": "succinate",
    "mesylas": "mesylate", "tosylas": "tosylate", "besylas": "besylate", "besilatum": "besylate",
    # 结晶水 / 常见盐名词
    "dihydricum": "dihydrate", "hexahydricum": "hexahydrate", "monohydricum": "monohydrate",
    "trihydricum": "trihydrate", "argininum": "arginine", "medoxomilum": "medoxomil",
    "etexilatum": "etexilate",
}


def _latin_word_variants(w: str) -> list[str]:
    """单个拉丁词 → 1–2 个英文候选（词尾规则有歧义时两个都试，让 `SgMapper` 定）。

    歧义举例：`-olum` 既可能是 `pantoprazolum → pantoprazole`，也可能是
    `colecalciferolum → colecalciferol`；`-ini` 既可能是 `memantini → memantine`
    也可能是 `abirateroni → abiraterone`。**只生成写法，不替成分做判断。**
    """
    lw = w.lower()
    if lw in _LATIN_WORD:
        return [_LATIN_WORD[lw]]
    if lw.endswith("tanum") and len(lw) > 6:          # olmesartanum → olmesartan
        return [lw[:-5] + "tan"]
    if lw.endswith("is") and len(lw) > 4:             # dimethylis → dimethyl
        return [lw[:-2]]
    if lw.endswith("as") and len(lw) > 4:             # 未列入表的 -as 盐
        return [lw[:-2] + "ate"]
    if lw.endswith("um") and len(lw) > 4:             # amlodipinum → amlodipine / amlodipin / levodopa
        stem = lw[:-2]
        return [stem + "e", stem, stem + "a"]
    if lw.endswith("i") and len(lw) > 3:              # perindoprili → perindopril / memantine
        stem = lw[:-1]
        return [stem + "e", stem]
    return [lw]


def latin_to_english_all(token: str) -> list[str]:
    """整串拉丁名 → 若干英文候选（逐词映射 + `acidum` 前置改成后置 `acid`）。

    `Acidum acetylsalicylicum` → `acetylsalicylic acid`；
    `Natrii chloridum` → `sodium chloride`；`Insulinum humanum` → `insulin human`。
    """
    words = [w for w in re.split(r"\s+", (token or "").strip()) if w]
    if not words:
        return []
    acid_first = words[0].lower() == "acidum"
    body = words[1:] if acid_first else words
    combos = [""]
    for w in body:
        opts = _latin_word_variants(w)
        combos = [(c + (" " if c else "") + o) for c in combos for o in opts][:4]
        if not combos:
            break
    if acid_first:
        combos = [c + " acid" for c in combos]
    return [c for c in combos if c]


def latin_variants(token: str) -> list[str]:
    """拉丁 INN → 候选写法（只为让 `SgMapper` 命中，命中与否仍由库里 `substance` 决定）。

    实测写法是「拉丁主格/属格 + 盐」：`Dexpanthenolum`、`Metoprololi tartras`、`Natrii chloridum`。
    候选顺序 = 原样 → 逐词英译 → 去盐母体 → 词尾整形，**只做词形，不做语义替换**。
    """
    t = (token or "").strip()
    if not t:
        return []
    out = [t]
    out.extend(latin_to_english_all(t))
    base = _LATIN_SALT_HINT.sub("", t).strip()      # 去盐词 → 只要母体
    if base and base != t:
        out.append(base)
        out.extend(latin_to_english_all(base))
    for cand in (t, base):
        low = cand.lower()
        if low.endswith("um"):
            out.append(cand[:-2])
        if low.endswith("i"):
            out.append(cand[:-1])
    seen, uniq = set(), []
    for c in out:
        c = c.strip()
        for form in (c, c[:1].upper() + c[1:]):    # 库里 inn_en 是 Title Case
            k = form.lower()
            if form and k not in seen:
                seen.add(k)
                uniq.append(form)
    return uniq


def split_substances(value: str) -> list[str]:
    """`active_substance` → token 列表（实测是单个拉丁 INN，复方会带 `+` / `;` / ` un `）。"""
    text = (value or "").strip()
    if not text:
        return []
    parts = re.split(r"\s*(?:\+|;|,|\bun\b|&)\s*", text)
    return [p.strip() for p in parts if p.strip()]


def map_substance(mapper: SgMapper, token: str) -> tuple[str, str]:
    """token → (substance_id, method)；映射不上返回 ("", "unmapped")。"""
    for idx, cand in enumerate(latin_variants(token)):
        sid, _salt, method = mapper.map_basic(cand)
        if sid:
            return sid, ("raw" if idx == 0 else f"lv-{method}")
    return "", "unmapped"


# ---------------------------------------------------------------- 解析：规格
_RE_SV = re.compile(r"\b(SV|IU|IE|UI)\b", re.I)
_RE_MICRO = re.compile(r"\bmicrogram(?:s|i|as|u|ų)?\b", re.I)
_RE_CONC_NO_DENOM = re.compile(
    r"(\d+(?:[.,]\d+)?\s*(?:mg|mcg|µg|μg|g|iu|ml))(\s*/\s*)(ml|l)\b", re.I)


def _strength_input(value: str) -> str:
    """规格预整形（**不改数值**）：`SV/IU/IE/UI` → `iu`、`microgram…` → `mcg`、`50 mg/ml` → `50 mg/1 ml`。"""
    s = _RE_SV.sub("iu", value or "")
    s = _RE_MICRO.sub("mcg", s)
    return _RE_CONC_NO_DENOM.sub(r"\g<1>\g<2>1 \g<3>", s)


def parse_strength_field(value: str) -> list[dict]:
    """`strength` 列 → [{value, unit, per_volume_value, per_volume_unit}]（数值不换算）。"""
    out: list[dict] = []
    for raw_value, raw_unit in normalize(_strength_input(value)).strengths:
        values = str(raw_value).split("/")
        units = str(raw_unit).split("/")
        try:
            num = float(values[0])
        except ValueError:
            continue
        unit, _rule = norm_unit(units[0])
        per_v: float | None = None
        per_u: str | None = None
        if len(values) > 1 or len(units) > 1:
            try:
                per_v = float(values[1]) if len(values) > 1 else 1.0
            except ValueError:
                per_v = None
            if len(units) > 1:
                per_u, _ = norm_unit(units[1])
            if per_v is None:
                per_u = None
        out.append({"value": num, "unit": unit,
                    "per_volume_value": per_v, "per_volume_unit": per_u})
    return out


# ---------------------------------------------------------------- 主键与名字
def make_product_id(row: dict) -> str:
    """`product_id`（`00-0003-01` / `EU/1/00/129/001`）→ 库内主键 `LV-…`。

    原始 `product_id` 在快照内唯一（40,600/40,600），所以不加摘要也不会撞；
    仍按 `nl.py` 的做法拼前缀 + slug，保证跨市场不会与别国 id 冲突。
    """
    raw = row.get("product_id", "")
    return f"LV-{slug(raw) or 'urn'}"[:60]


def name_pairs(row: dict) -> list[tuple[str, str]]:
    """(原文名, name_type)。**拉语名与英文原名同属一条产品**，不当作两个市场。"""
    out: list[tuple[str, str]] = []
    lv = (row.get("medicine_name") or "").strip()
    en = (row.get("original_name") or "").strip()
    short = (row.get("short_name") or "").strip()
    if lv:
        out.append((lv, "trade"))
    if en and en != lv:
        out.append((en, "trade"))
    if short and short not in {lv, en}:
        out.append((short, "colloquial"))
    return out


# ---------------------------------------------------------------- 统计
def _collect(rows, status_map, mapper, eu_ids: set[str], norm_set: set[str]) -> dict:
    """全量遍历一遍 → 统计（不写库、不落临时表）。"""
    st: collections.Counter = collections.Counter()
    proc_all: collections.Counter = collections.Counter()
    proc_active: collections.Counter = collections.Counter()
    proc_registered_ok: collections.Counter = collections.Counter()
    status_word: collections.Counter = collections.Counter()
    mah_dist: collections.Counter = collections.Counter()
    stock = collections.Counter()
    forms: collections.Counter = collections.Counter()
    form_base: collections.Counter = collections.Counter()
    atc_prefix: collections.Counter = collections.Counter()
    unmapped: collections.Counter = collections.Counter()
    subs_seen: set[str] = set()
    names_seen: set[str] = set()
    lv_names_seen: set[str] = set()
    en_names_seen: set[str] = set()
    names_folded_seen: set[str] = set()
    name_hit_existing = 0
    name_total = 0
    auth_seen: set[str] = set()
    eu_prefix: set[str] = set()
    eu_prefix_active: set[str] = set()
    strength_rows = 0
    strength_parsed = 0
    per_vol_rows = 0
    samples: list[dict] = []

    for row in rows:
        st["rows"] += 1
        pid = row.get("product_id", "")
        cls = classify(row, status_map.get(pid))
        proc_all[cls["procedure"]] += 1
        status_word[cls["status"]] += 1
        mah_dist[cls["mah_status"] or "(missing)"] += 1
        stock[("wh" if cls["in_stock_wholesale"] else "-") + ("/ph" if cls["in_stock_pharmacy"] else "/-")] += 1
        if cls["active"]:
            st["active"] += 1
            proc_active[cls["procedure"]] += 1
        if cls["registered_ok"]:
            st["registered_ok"] += 1
            proc_registered_ok[cls["procedure"]] += 1
        if cls["removed"]:
            st["removed"] += 1
        if cls["sell_stopped"]:
            st["sell_stopped"] += 1
        if cls["is_parallel"]:
            st["parallel_rows"] += 1
            if cls["active"]:
                st["parallel_would_be_active"] += 1
        if cls["is_unregistered"]:
            st["unregistered_rows"] += 1
            if cls["active"]:
                st["unregistered_would_be_active"] += 1
        if cls["is_centralised"]:
            st["centralised_rows"] += 1
            pfx = re.sub(r"/\d+$", "", row.get("authorisation_no", ""))
            eu_prefix.add(pfx)
            if cls["active"]:
                eu_prefix_active.add(pfx)
                st["centralised_active"] += 1

        # 名字（拉语名与英文原名同属一条产品，分别计数；不是两个市场）
        lv_name = (row.get("medicine_name") or "").strip()
        en_name = (row.get("original_name") or "").strip()
        if lv_name:
            lv_names_seen.add(lv_name)
        if en_name:
            en_names_seen.add(en_name)
        for name, ntype in name_pairs(row):
            st[f"name_{ntype}"] += 1
            names_seen.add(name)
            folded = fold_lv(name)
            names_folded_seen.add(folded)
            name_total += 1
            if folded in norm_set:
                name_hit_existing += 1

        # 成分
        for token in split_substances(row.get("active_substance", "")):
            subs_seen.add(token)
            sid, method = map_substance(mapper, token)
            st["substance_tokens"] += 1
            if sid:
                st["substance_mapped"] += 1
            else:
                st["substance_unmapped"] += 1
                unmapped[token] += 1

        # 规格 / 剂型 / ATC
        strength_rows += 1
        parsed = parse_strength_field(row.get("strength", ""))
        if parsed:
            strength_parsed += 1
            if any(p["per_volume_value"] is not None for p in parsed):
                per_vol_rows += 1
        form = (row.get("pharmaceutical_form") or "").strip()
        if form:
            forms[form] += 1
            form_base[form_base_of(form) or "?"] += 1
        else:
            st["form_empty"] += 1
        atc = (row.get("atc_code") or "").strip()
        if atc:
            st["atc_present"] += 1
            atc_prefix[atc[:1]] += 1
        else:
            st["atc_empty"] += 1
        if row.get("authorisation_no"):
            auth_seen.add(row["authorisation_no"])
        if not (row.get("marketing_authorisation_holder") or "").strip():
            st["mah_empty"] += 1
        if len(samples) < 3 and cls["active"]:
            samples.append({
                "product_id": pid, "medicine_name": row.get("medicine_name"),
                "original_name": row.get("original_name"), "strength": row.get("strength"),
                "form": form, "atc": atc, "mah": row.get("marketing_authorisation_holder"),
                "procedure": cls["procedure"], "status": cls["status"],
                "status_raw": f"status={row.get('status')} prd_removed={row.get('prd_removed')} "
                              f"sell_stop_date='{row.get('sell_stop_date')}' mah_status={cls['mah_status']}",
            })

    st["unique_authorisation_no"] = len(auth_seen)
    st["unique_medicine_name"] = len(lv_names_seen)
    st["unique_original_name"] = len(en_names_seen)
    st["unique_name_all"] = len(names_seen)
    st["unique_name_folded"] = len(names_folded_seen)
    st["unique_active_substance"] = len(subs_seen)
    st["name_existing_hit"] = name_hit_existing if name_total else 0
    st["name_total"] = name_total
    st["eu_prefix_unique"] = len(eu_prefix)
    st["eu_prefix_in_eu_layer"] = len(eu_prefix & eu_ids)
    st["eu_prefix_new"] = len(eu_prefix - eu_ids)
    st["eu_active_prefix"] = len(eu_prefix_active)

    return {
        "stats": st,
        "proc_all": proc_all, "proc_active": proc_active, "proc_registered_ok": proc_registered_ok,
        "status_word": status_word, "mah": mah_dist, "stock": stock,
        "forms": forms, "form_base": form_base, "atc_prefix": atc_prefix,
        "unmapped": unmapped, "samples": samples,
        "strength": {"rows": strength_rows, "parsed": strength_parsed, "per_volume": per_vol_rows},
    }


# ---------------------------------------------------------------- dry-run
def cmd_dry_run(args: argparse.Namespace) -> int:
    """读缓存 → 解析 → 统计；**只读开库，不写任何库**。"""
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    zip_path = args.src if args.src.is_absolute() else (ROOT / args.src)
    if not db_path.exists():
        raise SystemExit(f"库不存在：{db_path}（本脚本只读，不建库）")
    t0 = time.perf_counter()
    status_map = load_status(args.status)
    db = _connect_ro(db_path)
    try:
        mapper = SgMapper(db)
        eu_ids = {r[0] for r in db.execute(
            "SELECT approval_id FROM product WHERE region='EU' AND approval_id IS NOT NULL")}
        norm_set = {fold_lv(r[0]) for r in db.execute("SELECT norm FROM name_key")}
        db_products = db.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        db_countries = [r[0] for r in db.execute(
            "SELECT DISTINCT country FROM product WHERE country IS NOT NULL ORDER BY 1")]
        result = _collect(iter_products(zip_path), status_map, mapper, eu_ids, norm_set)
    finally:
        db.close()
    elapsed = round(time.perf_counter() - t0, 1)

    st = result["stats"]
    n_rows = max(1, st["rows"])
    sst = result["strength"]
    summary = {
        "generated_at": _now(),
        "tool": "etl/markets/lv.py",
        "mode": "dry-run（只读，不写库；本脚本无 --apply）",
        "source": {"source_id": SOURCE_ID, "dataset": URL_DATASET, "xml_zip": URL_ZIP,
                   "status_csv": URL_STATUS, "licence": LICENCE},
        "db": {"path": str(db_path), "mode": "read-only(mode=ro)", "products": db_products,
               "countries": db_countries, "lv_in_country_check": "LV" in db_countries},
        "snapshot": {
            "zip": {"path": str(zip_path), "bytes": zip_path.stat().st_size,
                    "sha256": _sha256_file(zip_path)},
            "rows": st["rows"], "products": st["rows"],
            "missing_status_rows": st["rows"] - sum(1 for _ in status_map),
        },
        "counts": {
            "products": st["rows"],
            "unique_authorisation_no": st["unique_authorisation_no"],
            "unique_medicine_name": st["unique_medicine_name"],
            "unique_original_name": st["unique_original_name"],
            "unique_name_all": st["unique_name_all"],
            "unique_name_folded": st["unique_name_folded"],
            "unique_active_substance": st["unique_active_substance"],
            "active": st["active"],
            "registered_ok": st["registered_ok"],
            "removed": st["removed"],
            "sell_stopped": st["sell_stopped"],
            "parallel_rows": st["parallel_rows"],
            "parallel_would_be_active": st["parallel_would_be_active"],
            "unregistered_rows": st["unregistered_rows"],
            "unregistered_would_be_active": st["unregistered_would_be_active"],
            "centralised_rows": st["centralised_rows"],
            "centralised_active": st["centralised_active"],
        },
        "status_logic": {
            "active_rule": "status=='1' ∧ prd_removed=='0' ∧ sell_stop_date 空 ∧ "
                           "mah_status=='1' ∧ 程序∉{平行进口, 平行分销, 未注册药品}",
            "registered_ok_rule": "status=='1' ∧ prd_removed=='0' ∧ sell_stop_date 空（注册有效，未必在售）",
            "warn": "只按 status/prd_removed 判会把 38,759 行算成 active（真实在售 4,551）——不得这样上报",
            "status_word": dict(result["status_word"]),
            "mah_status_dist": dict(result["mah"]),
            "stock_dist": dict(result["stock"]),
            "by_procedure_all": dict(result["proc_all"]),
            "by_procedure_active": dict(result["proc_active"]),
            "by_procedure_registered_ok": dict(result["proc_registered_ok"]),
        },
        "mapping": {
            "substance_tokens": st["substance_tokens"],
            "substance_mapped": st["substance_mapped"],
            "substance_unmapped": st["substance_unmapped"],
            "substance_map_rate": round(st["substance_mapped"] / max(1, st["substance_tokens"]), 4),
            "unmapped_top": result["unmapped"].most_common(15),
            "strength_rows": sst["rows"],
            "strength_parsed": sst["parsed"],
            "strength_rate": round(sst["parsed"] / max(1, sst["rows"]), 4),
            "strength_per_volume_rows": sst["per_volume"],
            "atc_present": st["atc_present"],
            "atc_rate": round(st["atc_present"] / n_rows, 4),
            "form_empty": st["form_empty"],
            "mah_empty": st["mah_empty"],
            "name_existing_hit": st["name_existing_hit"],
            "name_total": st["name_total"],
            "name_existing_hit_rate": round(st["name_existing_hit"] / max(1, st["name_total"]), 4),
        },
        "forms_top": result["forms"].most_common(12),
        "form_base_top": result["form_base"].most_common(10),
        "atc_letter_top": result["atc_prefix"].most_common(8),
        "eu_dedup": {
            "eu_layer_ids": len(eu_ids),
            "lv_centralised_prefix": st["eu_prefix_unique"],
            "overlap_prefix": st["eu_prefix_in_eu_layer"],
            "overlap_rows": st["centralised_rows"],
            "lv_only_prefix": st["eu_prefix_new"],
        },
        "samples": result["samples"],
        "elapsed_sec": elapsed,
    }

    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "lv_dry_run.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 控制台摘要（结论先行）
    c = summary["counts"]
    m = summary["mapping"]
    print("=== LV ZVA 干跑（只读，不写库）===")
    print(f"  快照 {zip_path.name} · {zip_path.stat().st_size:,} B · sha256 "
          f"{summary['snapshot']['zip']['sha256'][:16]}…")
    print(f"  包装级条目 {c['products']:,} → 注册号 {c['unique_authorisation_no']:,} · "
          f"拉语名 {c['unique_medicine_name']:,} · 英文原名 {c['unique_original_name']:,} · "
          f"成分 token {c['unique_active_substance']:,}")
    print(f"  在售(active) {c['active']:,} · 注册有效 {c['registered_ok']:,} · "
          f"已移除 {c['removed']:,} · 已停售 {c['sell_stopped']:,}")
    print(f"  平行进口 {c['parallel_rows']:,} 行（其中若按同规则会算 active {c['parallel_would_be_active']:,}）"
          f" · 未注册 {c['unregistered_rows']:,} 行")
    print(f"  状态枚举 {dict(result['status_word'])}")
    print(f"  成分映射 {m['substance_mapped']:,}/{m['substance_tokens']:,} = {m['substance_map_rate']:.1%}"
          f" · 规格解析 {m['strength_parsed']:,}/{m['strength_rows']:,} = {m['strength_rate']:.1%}"
          f" · ATC 覆盖 {m['atc_rate']:.1%}")
    print(f"  EU 去重：LV 集中审批 {summary['eu_dedup']['lv_centralised_prefix']:,} 个药号，"
          f"与 EU 层重合 {summary['eu_dedup']['overlap_prefix']:,}，LV 独有 {summary['eu_dedup']['lv_only_prefix']:,}")
    print(f"  耗时 {elapsed}s · 产物 {out.relative_to(ROOT)}")
    return 0


# ---------------------------------------------------------------- 自测
def self_check(src: Path = ZIP_PATH, status: Path = STATUS_PATH) -> int:
    """离线断言：标签齐全 / 状态规则自洽 / 变音折叠 / 无 --apply。返回 0 = 全过。"""
    fails: list[str] = []

    def ok(cond: bool, msg: str) -> None:
        print(("  ✅ " if cond else "  ❌ ") + msg)
        if not cond:
            fails.append(msg)

    print("=== LV self-check ===")
    ok(src.exists(), f"快照存在：{src.relative_to(ROOT) if src.is_relative_to(ROOT) else src}")
    ok(status.exists(), "状态表存在")
    st = load_status(status)
    ok(len(st) > 1000, f"状态表行数 {len(st):,} > 1000")

    n = 0
    bad_tags = collections.Counter()
    bad_status = 0
    dup_ids: set[str] = set()
    seen_ids: set[str] = set()
    active_ok = 0
    for row in iter_products(src):
        n += 1
        missing = [t for t in REQUIRED_TAGS if t not in row]
        if missing:
            bad_tags.update(missing)
        pid = row.get("product_id", "")
        if pid in seen_ids:
            dup_ids.add(pid)
        seen_ids.add(pid)
        # 规则自洽：status='0' 必须带停售日期（实测 737/737）
        if row.get("status") == "0" and not row.get("sell_stop_date"):
            bad_status += 1
        cls = classify(row, st.get(pid))
        if cls["active"] and (cls["is_parallel"] or cls["is_unregistered"]):
            active_ok += 1
        # 平行进口/未注册不得进 active
    ok(n == EXPECTED_PRODUCTS, f"产品数 {n:,} == 预期 {EXPECTED_PRODUCTS:,}")
    ok(not bad_tags, f"49 个标签齐全（缺：{dict(bad_tags) or '无'}）")
    ok(not dup_ids, f"product_id 无重复（重复 {len(dup_ids)}）")
    ok(bad_status == 0, f"`status='0'` 必带 sell_stop_date（违反 {bad_status}）")
    ok(active_ok == 0, f"平行进口/未注册不计入 active（违反 {active_ok}）")

    # 变音折叠
    cases = [("Šķīdums injekcijām", "skidums injekcijam"),
             ("Āboliņš", "abolins"), ("Zāļu reģistrs", "zalu registrs")]
    for src_s, want in cases:
        got = fold_lv(src_s)
        ok(got == want, f"折叠 {src_s!r} → {got!r}（期望 {want!r}）")

    # 状态判定：三条合成行
    fake = {"status": "1", "prd_removed": "0", "sell_stop_date": "",
            "authorisation_procedure": "Nacionālā reģistrācijas procedūra"}
    ok(classify(fake, {"mah_status": "1"})["active"], "注册+可供+未停售 → active")
    ok(not classify(fake, {"mah_status": "2"})["active"], "mah_status=2（没上市）→ 不是 active")
    ok(not classify({**fake, "sell_stop_date": "2026-01-01"}, {"mah_status": "1"})["active"],
       "有停售日期 → 不是 active")
    ok(not classify({**fake, "authorisation_procedure": PROC_PARALLEL_IMPORT}, {"mah_status": "1"})["active"],
       "平行进口 → 不是 active")
    ok(not classify({**fake, "authorisation_procedure": PROC_UNREGISTERED}, {"mah_status": "1"})["active"],
       "未注册药品 → 不是 active")

    # 无 --apply
    ap = build_parser()
    opts = {a for a in ap._option_string_actions}  # noqa: SLF001 - 断言用
    ok("--apply" not in opts and "--rollback" not in opts,
       f"CLI 无 --apply / --rollback（实际开关：{sorted(o for o in opts if o.startswith('--'))}）")

    print(f"=== {'全部通过' if not fails else f'失败 {len(fails)} 项'} ===")
    return 0 if not fails else 1


def cmd_self_check(args: argparse.Namespace) -> int:
    src = args.src if args.src.is_absolute() else (ROOT / args.src)
    status = args.status if args.status.is_absolute() else (ROOT / args.status)
    return self_check(src, status)


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="拉脱维亚 ZVA 国家药品注册库 ETL 骨架（CC0 1.0）：只做干跑，**不写库**。"
                    "许可已获批，但 UI 未改完 + country CHECK 未迁移，故本脚本不提供 --apply。",
        epilog="例：--fetch 抓快照；--dry-run 出统计（默认）；--self-check 跑离线断言。")
    ap.add_argument("--fetch", action="store_true",
                    help=f"抓 {URL_ZIP} + 状态表 + CC0 元数据到 data/raw/lv_zalu_20261112/")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="读缓存 → 解析 → 统计（默认；只读开库，不写库）")
    mode.add_argument("--self-check", action="store_true",
                      help="离线断言：49 标签 / 状态规则 / 变音折叠 / 无 --apply")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="只读打开的库（默认 data/drugs.db）")
    ap.add_argument("--src", type=Path, default=ZIP_PATH, help="ZIP 快照路径")
    ap.add_argument("--status", type=Path, default=STATUS_PATH, help="状态码表 CSV 路径")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    # 本脚本刻意不实现 --apply / --rollback：UI 未改完 + country CHECK 未迁移，写库路径另开任务。
    if args.fetch:
        return cmd_fetch(args)
    if args.self_check:
        return cmd_self_check(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
