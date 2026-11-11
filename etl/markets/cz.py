# -*- coding: utf-8 -*-
"""捷克 SÚKL 药品数据库（DLP）ETL 骨架 —— **只做干跑，不写库**。

许可状态（这一页最重要）
------------------------
SÚKL 开放数据使用条款明示允许**复制 / 分发 / 公开传播 / 商用 / 引用**，条件三条：
  1. 必须注明数据来源是 SÚKL；
  2. 不得以任何方式改变或歪曲数据的含义（我们的归一化/拆分属「派生」，页面必须写明
     「派生自官方字段，原文见来源链接」，且不覆盖原文）；
  3. 再分发时须附条款链接。
**排除项**：上述条款**不覆盖含第三方知识产权的文档**（SPC / PIL / OBALY 三个 PDF/DOC 包）
→ 本站只取 DLP 的 CSV 事实表，**绝不入库 SPC/PIL/OBALY**（本脚本的白名单只读 8 张事实表）。

评估与证据：`reports/2026-11-12-eu-member-states-scan.md` §2.1 / §3.2、
`reports/2026-11-12-cz-sukl-acquisition.md`（本工位）、`docs/许可清单.md`（CZ 行由 Lead 统一落）。

因此本脚本**故意不提供 `--apply` / `--rollback`**：只有 `--fetch`（抓快照）、`--dry-run`
（读快照 → 解析 → 统计，只读开库）和 `--self-check`（离线断言）。写库路径等 Lead 在独立
DB 窗口开启后，按 `etl/ingest_eu.py` 的 `--apply` / `--rollback` / `--manifest` 三段式另补。

数据源
------
数据集页：https://opendata.sukl.gov.cz/katalog-otevrenych-dat/databaze-lecivych-pripravku-dlp
月度 ZIP：`https://opendata.sukl.gov.cz/soubory/SOD20261027/DLP20261027.zip`（9,551,535 B）
  - `dlp_lecivepripravky` **70,032 行 × 44 列**：一条 = 一个注册药品（含包装规格，不按成分拆行）
  - `dlp_slozeni` **811,168 行**：成分-含量（`S=L` 为活性成分 94,066 行；`S=X` 为辅料）
  - `dlp_latky` 21,587 行 / `dlp_lecivelatky` 3,390 行：成分码表（`NAZEV_INN` 拉丁学名、
    `NAZEV_EN` 英文名、`NAZEV` 捷克名）
  - `dlp_formy` 643 行（剂型 + EDQM 码）、`dlp_cesty` 178 行（途径 + EDQM）、`dlp_obaly` 83 行
  - `dlp_stavyreg` 16 行（注册状态码表）、`dlp_organizace` 3,606 行（MAH/生产商）
  - 编码 **CP1250**、分隔符 **`;`**、小数用**逗号**（`0,3MG`）；按 UTF-8 硬读会静默出乱码。

复用（不另起一套）
-----------------
- 剂型：`etl/ingest_openfda_ndc.py:form_base_of()`（吃码表里的英文剂型名）
- 单位：`etl/normalize_strength.py:norm_unit()`
- 成分：优先按库里 `substance.inn_en` 精确匹配；不命中时再去盐/去标点重试
- 重音折叠：本文件的 `fold_cs()`（捷克语专用，见 `--self-check` 的断言）

CLI：
    python etl/markets/cz.py --fetch        # 抓快照到 data/raw/cz_sukl_20261112/
    python etl/markets/cz.py --dry-run      # 默认：读快照 → 解析 → 统计（只读开库，不写库）
    python etl/markets/cz.py --self-check   # 离线断言：44 列 / CP1250 / 变音符号归一 / 样例行
    python etl/markets/cz.py --dry-run --db .tmp/cz-ingest/drugs-copy.db

产物：`.tmp/cz-ingest/cz_dry_run.json`（统计）+ 控制台摘要。`.tmp/`、`data/raw/` 都不入库。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
import time
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from ingest_openfda_ndc import form_base_of  # noqa: E402
from normalize_strength import norm_unit  # noqa: E402

UA = {"User-Agent": "drug-brand-crossref/0.2 (public-data research)"}
DATASET_PAGE = ("https://opendata.sukl.gov.cz/katalog-otevrenych-dat/"
                "databaze-lecivych-pripravku-dlp")
TERMS_PAGE = "https://opendata.sukl.gov.cz/podminky-uziti-otevrenych-dat"
ZIP_URL = "https://opendata.sukl.gov.cz/soubory/SOD20261027/DLP20261027.zip"
DICT_URL = "https://opendata.sukl.gov.cz/soubory/DLP_datove_rozhrani20260701.csv"
RAW = ROOT / "data" / "raw" / "cz_sukl_20261112"
ZIP_PATH = RAW / "DLP20261027.zip"
WORK = ROOT / ".tmp" / "cz-ingest"
LICENSE_DIR = RAW / "license"
CSV_ENCODING = "cp1250"          # 实测；按 UTF-8 读会出替换字符
DELIM = ";"
PRODUCT_TABLE = "dlp_lecivepripravky.csv"
EXPECTED_COLS = 44

# 只读事实表白名单：许可条款明确排除第三方 IP 文档（SPC/PIL/OBALY 的 zip），
# 所以这里**不**读 dlp_nazvydokumentu / dlp_splp / dlp_vpois 等说明书/文献表。
ALLOWED_TABLES = {
    PRODUCT_TABLE, "dlp_slozeni.csv", "dlp_latky.csv", "dlp_lecivelatky.csv",
    "dlp_formy.csv", "dlp_cesty.csv", "dlp_obaly.csv", "dlp_stavyreg.csv",
    "dlp_organizace.csv", "dlp_jednotky.csv", "dlp_atc.csv", "dlp_zeme.csv",
    "dlp_platnost.csv",
}

# 注册状态码 → 本站 status（值见 dlp_stavyreg.csv；映射理由写在报告 §3.3）
STATUS_MAP = {
    "R": "active",        # 已注册
    "B": "active",        # 变更后可上市 6 个月
    "F": "active",        # 特定治疗程序
    "I": "active",        # 卫生部长特别措施
    "G": "discontinued",  # 特定治疗程序结束
    "K": "discontinued",  # 集中审批决定暂停
    "M": "discontinued",  # 注册/使用暂停
    "C": "withdrawn",     # 注销，限期撤市
    "N": "withdrawn",     # 撤销或有效期届满
    "Y": "withdrawn",     # 失效，限期撤市
    "Z": "withdrawn",     # 失效/未续期/续期被拒
    "ZS": "withdrawn",    # SUNSET 注销
    "U": "withdrawn",     # 豁免被撤销
    "ZI": "withdrawn",    # 特别措施被撤销
    "J": "withdrawn",     # PZLÚ 从数据库移除
    "P": "excluded",      # 特殊医学用途食品（FSMP）：不是药品，不入库
}
EXCLUDED_REG = {"P", "J"}

# 捷克语变音符号 → 无重音写法（NFKD 折不掉的几个要手写：ď/ť 是带笔画的预组合字符）
CZ_FOLD = {
    "á": "a", "č": "c", "ď": "d", "é": "e", "ě": "e", "í": "i", "ň": "n",
    "ó": "o", "ř": "r", "š": "s", "ť": "t", "ú": "u", "ů": "u", "ý": "y",
    "ž": "z", "Á": "A", "Č": "C", "Ď": "D", "É": "E", "Ě": "E", "Í": "I",
    "Ň": "N", "Ó": "O", "Ř": "R", "Š": "S", "Ť": "T", "Ú": "U", "Ů": "U",
    "Ý": "Y", "Ž": "Z",
}
# 顺势疗法稀释度 / 计数型单位：不是可比较的「规格」，按 not_numeric 处理
HOMEOPATHIC_UNITS = {"CH", "DH", "D", "C", "H", "X", "MK", "K"}
# 顺式/盐名尾巴：匹配 substance.inn_en 时先去掉（只用于「生成候选」，不改数据）
SALT_TAIL = re.compile(
    r"\s+(HYDROCHLORIDE|HYDROBROMIDE|SULFATE|SULPHATE|SODIUM|POTASSIUM|CALCIUM|"
    r"MAGNESIUM|TARTRATE|CITRATE|MALEATE|FUMARATE|SUCCINATE|ACETATE|PHOSPHATE|"
    r"DIHYDRATE|MONOHYDRATE|TRIHYDRATE|ANHYDROUS|BESILATE|MESILATE|OXALATE)$")
# 「CZ 名 = 库里 INN + 盐/水合物尾巴」判定用的尾巴词表（`<base> TOSILATE MONOHYDRATE` 这类）
SALT_WORDS = {
    "HYDROCHLORIDE", "DIHYDROCHLORIDE", "HYDROBROMIDE", "SULFATE", "SULPHATE",
    "SULFONATE", "TOSILATE", "TOSYLATE", "BESILATE", "MESILATE", "MALEATE", "FUMARATE",
    "TARTRATE", "HYDROGEN", "DIHYDROGEN", "CITRATE", "SUCCINATE", "ACETATE",
    "PHOSPHATE", "DIPHOSPHATE", "NITRATE", "OXALATE", "LACTATE", "GLUCONATE",
    "CARBONATE", "BICARBONATE", "SODIUM", "POTASSIUM", "CALCIUM", "MAGNESIUM", "ZINC",
    "DIHYDRATE", "MONOHYDRATE", "TRIHYDRATE", "SESQUIHYDRATE", "HEMIHYDRATE",
    "ANHYDROUS", "HYDRATE", "PROPYLENE", "GLYCOL", "DISODIUM", "DIPOTASSIUM",
    "TERT", "BUTYLAMINE", "ERBUMINE", "ARGININE", "DIETHYLAMINE", "ETHYLENEDIAMINE",
    "MEGLUMINE", "TROMETAMOL", "LYSINE", "CHOLINE", "BROMIDE", "CHLORIDE", "IODIDE",
}
# INN 与 USAN（美国名）的固定异名对：库里只有其中一个时，按这张表对齐。
# 依据：本次快照的未命中 top（PARACETAMOL / ACETYLSALICYLIC ACID 等），
# 扩展时以 WHO INN 名单为准，不要凭感觉加。
INN_SYNONYMS = {
    "PARACETAMOL": "ACETAMINOPHEN",
    "ACETYLSALICYLIC ACID": "ASPIRIN",
    "SODIUM HYDROGEN CARBONATE": "SODIUM BICARBONATE",
    "ADRENALINE": "EPINEPHRINE",
    "NORADRENALINE": "NOREPINEPHRINE",
    "SALBUTAMOL": "ALBUTEROL",
    "FRUSEMIDE": "FUROSEMIDE",
    "AMOXYCILLIN": "AMOXICILLIN",
    "CICLOSPORIN": "CYCLOSPORINE",
    "GLYCERYL TRINITRATE": "NITROGLYCERIN",
    "HYOSCINE BUTYLBROMIDE": "SCOPOLAMINE BUTYLBROMIDE",
    "RIFAMPICIN": "RIFAMPIN",
    "MESALAZINE": "MESALAMINE",
    "LIDOCAINE": "LIDOCAINE",
    "BECLOMETASONE": "BECLOMETHASONE",
}


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def fold_cs(text: str) -> str:
    """捷克语变音符号折叠：先 NFKD 去组合音标，再补 CZ_FOLD 里折不掉的那几个。"""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return "".join(CZ_FOLD.get(ch, ch) for ch in s)


def norm_inn(text: str) -> str:
    """成分名归一：折叠 + 大写 + 空白压缩（用于和 substance.inn_en 比）。"""
    s = fold_cs(text).upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_salt(name: str) -> str:
    """迭代剥盐/水合物尾巴（`EDOXABAN TOSILATE MONOHYDRATE` → `EDOXABAN`）。"""
    prev = name
    for _ in range(4):
        cur = SALT_TAIL.sub("", prev).strip()
        if cur == prev or not cur:
            break
        prev = cur
    return prev


def map_inn(name_en: str, db_inn: dict[str, str]) -> tuple[str | None, str]:
    """成分名 → 库内 substance_id。返回 (substance_id, 命中层级)。

    层级：exact → salt（迭代剥盐）→ prefix（<INN> + 纯盐词尾巴）→ synonym（INN/USAN 异名）。
    只用于**生成候选映射**；不写库、不改原文。
    """
    key = norm_inn(name_en)
    if not key:
        return None, "empty"
    # 去括号补充说明：`CHOLECALCIFEROL CONCENTRATE (POWDER FORM)` → `CHOLECALCIFEROL CONCENTRATE`
    key = re.sub(r"\s*\([^)]*\)", "", key).strip()
    if key in db_inn:
        return db_inn[key], "exact"
    stripped = strip_salt(key)
    if stripped and stripped != key and stripped in db_inn:
        return db_inn[stripped], "salt"
    # prefix：CZ 名以某个库内 INN 开头，且剩下的词全是盐/水合物词（从最长前缀试起）
    toks = key.split()
    for n in range(len(toks) - 1, 0, -1):
        base = " ".join(toks[:n])
        if base not in db_inn:
            continue
        tail = toks[n:]
        if tail and all(t in SALT_WORDS or t.isdigit() for t in tail):
            return db_inn[base], "prefix"
        break
    syn = INN_SYNONYMS.get(key)
    if syn:
        for cand in (syn, strip_salt(syn)):
            if cand in db_inn:
                return db_inn[cand], "synonym"
    return None, "miss"


def split_strength(sila: str) -> list[dict]:
    """把 `SILA` 拆成若干 (数值, 单位[, 每 X]) 片段。

    覆盖：`500MG` / `0,3MG` / `300MCG` / `450MG/50MG`（两个成分）/ `1MG/ML`（浓度）/
    `20MG/G+10MG/G`（两个成分、各自按 g 计）。规则：
      * `+` 一律是成分分隔；
      * `/` 只有**后面紧跟数字**时才算第二个成分（`450MG/50MG`），否则是分母（`1MG/ML`）；
      * 顺势疗法稀释度（`5CH`/`30DH`）与计数型判为 not_numeric，不做数值解析。
    """
    out: list[dict] = []
    segments: list[str] = []
    for plus_part in (sila or "").split("+"):
        segments.extend(p.strip() for p in re.split(r"/(?=\s*\d)", plus_part) if p.strip())
    for seg in segments:
        m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*([A-Za-z%]+)?(?:\s*/\s*([A-Za-z%]+))?", seg)
        if not m:
            out.append({"raw": seg, "value": None, "unit": None,
                        "kind": "not_numeric"})
            continue
        value = float(m.group(1).replace(",", "."))
        unit_raw = (m.group(2) or "").upper()
        per_raw = (m.group(3) or "").upper()
        if unit_raw in HOMEOPATHIC_UNITS:
            out.append({"raw": seg, "value": None, "unit": None,
                        "unit_raw": unit_raw, "kind": "not_numeric"})
            continue
        unit, _kind = norm_unit(unit_raw)
        per_unit = norm_unit(per_raw)[0] if per_raw else None
        out.append({"raw": seg, "value": value, "unit": unit, "unit_raw": unit_raw,
                    "per_volume_unit": per_unit,
                    "kind": "numeric" if unit else "unit_unmapped"})
    return out


def classify_atc(atc: str) -> str:
    """ATC 粒度：substance（7 位）/ group（3–5 位）/ other / none。"""
    a = (atc or "").strip().upper()
    if not a:
        return "none"
    if re.fullmatch(r"[ABCDGHJLMNPRSV]\d{2}[A-Z]{2}\d{2}", a):
        return "substance"
    if re.fullmatch(r"[ABCDGHJLMNPRSV]\d{2}[A-Z]{0,2}", a):
        return "group"
    return "other"


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def read_table(zf: zipfile.ZipFile, name: str) -> list[dict]:
    if name not in ALLOWED_TABLES:
        raise ValueError(f"{name} 不在事实表白名单里（许可条款排除第三方 IP 文档表）")
    text = zf.read(name).decode(CSV_ENCODING)
    return list(csv.DictReader(io.StringIO(text), delimiter=DELIM))


def load_snapshot() -> dict:
    if not ZIP_PATH.exists():
        raise SystemExit(f"没有快照：{ZIP_PATH}（先跑 --fetch）")
    with zipfile.ZipFile(ZIP_PATH) as zf:
        tables = {n: read_table(zf, n) for n in sorted(ALLOWED_TABLES)
                  if n in zf.namelist()}
        names = zf.namelist()
    return dict(tables=tables, members=names)


def codebook(rows: list[dict], key: str, val: str) -> dict[str, str]:
    return {(r.get(key) or "").strip(): (r.get(val) or "").strip() for r in rows}


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------
def _get(url: str, timeout: int = 60) -> tuple[bytes, dict]:
    req = Request(url, headers=UA)
    with urlopen(req, timeout=timeout) as r:
        body = r.read()
        meta = {
            "url": url, "status": r.status, "bytes": len(body),
            "content_type": r.headers.get("Content-Type"),
            "content_length": r.headers.get("Content-Length"),
            "last_modified": r.headers.get("Last-Modified"),
            "etag": r.headers.get("ETag"),
            "sha256": hashlib.sha256(body).hexdigest(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    return body, meta


def fetch() -> int:
    """抓许可页 / 数据集页 / 字段说明 / DLP ZIP，写 fetch_meta.json。"""
    RAW.mkdir(parents=True, exist_ok=True)
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        (TERMS_PAGE, LICENSE_DIR / "podminky-uziti-otevrenych-dat.html"),
        (DATASET_PAGE, LICENSE_DIR / "dataset-dlp.html"),
        (DICT_URL, RAW / "DLP_datove_rozhrani20260701.csv"),
        (ZIP_URL, ZIP_PATH),
    ]
    meta = {"source_id": "sukl_dlp", "dataset_page": DATASET_PAGE,
            "terms_page": TERMS_PAGE, "fetched": []}
    for url, dest in items:
        t0 = time.time()
        body, m = _get(url, timeout=300)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        m["path"] = dest.relative_to(ROOT).as_posix()
        m["seconds"] = round(time.time() - t0, 2)
        meta["fetched"].append(m)
        print(f"  {dest.name:<46} {m['bytes']:>10,} B {m['seconds']:>6.1f}s  "
              f"sha256={m['sha256'][:16]}…")
    (RAW / "fetch_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n快照 -> {RAW.relative_to(ROOT)}（fetch_meta.json 已写）")
    return 0


# ---------------------------------------------------------------------------
# 干跑
# ---------------------------------------------------------------------------
def connect_ro(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def db_substances(con: sqlite3.Connection) -> dict[str, str]:
    """inn_en（归一后）→ substance_id。"""
    return {norm_inn(r["inn_en"]): r["substance_id"]
            for r in con.execute("SELECT substance_id, inn_en FROM substance")
            if r["inn_en"]}


def dry_run(db_path: Path) -> int:
    t0 = time.time()
    snap = load_snapshot()
    T = snap["tables"]
    prod = T[PRODUCT_TABLE]
    slozeni = T["dlp_slozeni.csv"]
    latky = {r["KOD_LATKY"]: r for r in T["dlp_latky.csv"]}
    formy = codebook(T["dlp_formy.csv"], "FORMA", "NAZEV_EN")
    cesty = codebook(T["dlp_cesty.csv"], "CESTA", "NAZEV_EN")
    orgs = codebook(T["dlp_organizace.csv"], "ZKR_ORG", "NAZEV")
    stavy = codebook(T["dlp_stavyreg.csv"], "REG", "NAZEV")
    platnost = T.get("dlp_platnost.csv") or [{}]

    stats: dict = {}
    stats["snapshot"] = {
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest(),
        "members": len(snap["members"]),
        "platnost_od": platnost[0].get("platnost_od") if platnost else None,
        "platnost_do": platnost[0].get("platnost_do") if platnost else None,
    }

    # ---- 产品层 ----
    cols = list(prod[0].keys())
    stats["product"] = {
        "rows": len(prod),
        "columns": len(cols),
        "distinct_name": len({r["NAZEV"].strip().upper() for r in prod}),
        "distinct_name_reg": len({r["NAZEV_REG"].strip().upper()
                                 for r in prod if r["NAZEV_REG"].strip()}),
    }
    status = Counter(STATUS_MAP.get((r["REG"] or "").strip(), "unknown") for r in prod)
    stats["status"] = dict(status)
    stats["status_raw"] = dict(Counter((r["REG"] or "").strip() for r in prod))
    stats["dodavky"] = dict(Counter((r["DODAVKY"] or "").strip() for r in prod))
    stats["fill"] = {
        col: sum(1 for r in prod if (r[col] or "").strip())
        for col in ("NAZEV", "NAZEV_REG", "SILA", "FORMA", "CESTA", "BALENI",
                    "DRZ", "AKT_DRZ", "ATC_WHO", "RC", "LL", "VYDEJ", "TYP_LP",
                    "DDDAMNT_WHO", "PRAVNI_ZAKLAD_REGISTRACE")
    }

    # ---- 规格 ----
    sila_tokens = Counter()
    sila_samples: list[dict] = []
    multi_part = 0
    for r in prod:
        sila = (r["SILA"] or "").strip()
        if not sila:
            sila_tokens["empty"] += 1
            continue
        parts = split_strength(sila)
        kinds = {p["kind"] for p in parts}
        if len(parts) > 1:
            multi_part += 1
        if "not_numeric" in kinds:
            sila_tokens["not_numeric"] += 1
            if len(sila_samples) < 12:
                sila_samples.append({"kod": r["KOD_SUKL"], "sila": sila,
                                     "parts": [p["raw"] for p in parts]})
        elif "unit_unmapped" in kinds:
            sila_tokens["unit_unmapped"] += 1
            if len(sila_samples) < 12:
                sila_samples.append({"kod": r["KOD_SUKL"], "sila": sila,
                                     "parts": [p["raw"] for p in parts]})
        else:
            sila_tokens["numeric"] += 1
    stats["strength"] = {"classes": dict(sila_tokens), "multi_part": multi_part,
                         "samples": sila_samples,
                         "parse_rate": round(sila_tokens["numeric"] / max(len(prod), 1), 4)}

    # ---- 剂型 / 途径 ----
    form_base = Counter()
    form_unmapped = Counter()
    for r in prod:
        code = (r["FORMA"] or "").strip()
        en = formy.get(code, "")
        base = form_base_of(en) if en else ""
        if base:
            form_base[base] += 1
        else:
            form_unmapped[code or "(空)"] += 1
    stats["form"] = {"base": dict(form_base.most_common()),
                     "unmapped_rows": sum(form_unmapped.values()),
                     "unmapped_codes": dict(form_unmapped.most_common(15))}
    route_ok = sum(1 for r in prod if (r["CESTA"] or "").strip() in cesty)
    stats["route"] = {"mapped": route_ok,
                      "unmapped": len(prod) - route_ok - sum(
                          1 for r in prod if not (r["CESTA"] or "").strip())}

    # ---- ATC ----
    atc_kind = Counter(classify_atc(r["ATC_WHO"]) for r in prod)
    stats["atc"] = {"classes": dict(atc_kind),
                    "coarse_samples": [r["ATC_WHO"] for r in prod
                                       if classify_atc(r["ATC_WHO"]) == "group"][:8]}

    # ---- 成分 ----
    active = [r for r in slozeni if (r["S"] or "").strip() == "L"]
    per_product = Counter(r["KOD_SUKL"] for r in active)
    amount_numeric = 0
    inn_missing = 0
    for r in active:
        m = re.fullmatch(r"\d+(?:[.,]\d+)?", (r["AMNT"] or "").strip())
        if m:
            amount_numeric += 1
        if r["KOD_LATKY"] not in latky:
            inn_missing += 1
    stats["composition"] = {
        "rows": len(slozeni), "active_rows": len(active),
        "products_with_active": len(per_product),
        "ingredient_count_dist": dict(Counter(per_product.values()).most_common(8)),
        "amount_numeric": amount_numeric,
        "amount_numeric_rate": round(amount_numeric / max(len(active), 1), 4),
        "latky_missing": inn_missing,
    }

    # ---- 与库内 substance 的匹配 ----
    con = connect_ro(db_path)
    db_inn = db_substances(con)
    db_products = {r[0] for r in con.execute("SELECT product_id FROM product")}
    eu_rows = con.execute(
        "SELECT pn.key_id FROM product_name pn JOIN product p ON p.product_id = pn.product_id "
        "WHERE p.region = 'EU' AND pn.name_type = 'trade'").fetchall()
    eu_keys = {r[0] for r in eu_rows}
    con.close()

    hit = strip_hit = miss = 0
    tiers: Counter = Counter()
    new_inn: Counter = Counter()
    used_latky: set[str] = set()
    for r in active:
        lk = latky.get(r["KOD_LATKY"])
        if not lk:
            continue
        name_en = (lk.get("NAZEV_EN") or "").strip() or (lk.get("NAZEV_INN") or "").strip()
        if not name_en:
            continue
        used_latky.add(r["KOD_LATKY"])
        sid, tier = map_inn(name_en, db_inn)
        tiers[tier] += 1
        if sid:
            hit += 1
        else:
            miss += 1
            new_inn[name_en] += 1
    stats["substance_map"] = {
        "active_rows": len(active),
        "exact_hit": tiers["exact"],
        "salt_stripped_hit": tiers["salt"],
        "prefix_hit": tiers["prefix"],
        "synonym_hit": tiers["synonym"],
        "miss": miss,
        "hit_rate": round(hit / max(hit + miss, 1), 4),
        "tiers": dict(tiers),
        "distinct_latky": len(used_latky),
        "new_inn_top": new_inn.most_common(20),
        "new_inn_count": len(new_inn),
        "synonym_pairs": len(INN_SYNONYMS),
    }

    # ---- 与 region='EU' 去重 ----
    eu_rc = [r for r in prod if (r["RC"] or "").upper().startswith("EU/")]
    stats["eu_overlap"] = {
        "rc_eu_prefix_rows": len(eu_rc),
        "rc_eu_prefix_pct": round(len(eu_rc) / max(len(prod), 1), 4),
        "note": "EU 集中审批产品在 DLP 里同样有记录；入库时必须按「名称×剂型×规格×成分」"
                "与 region='EU' 层比对，不能只按 RC 前缀丢行（部分 EU 产品同时有 CZ 包装）",
    }

    # ---- 预测入库量 ----
    ingestible = [r for r in prod if (r["REG"] or "").strip() not in EXCLUDED_REG]
    products_with_active = sum(1 for r in ingestible if per_product.get(r["KOD_SUKL"]))
    stats["projection"] = {
        "products": len(ingestible),
        "products_excluded_fsmp_pzlu": len(prod) - len(ingestible),
        "products_with_component": products_with_active,
        "components": sum(per_product[r["KOD_SUKL"]] for r in ingestible
                          if per_product.get(r["KOD_SUKL"])),
        "trade_names": len({r["NAZEV"].strip() for r in ingestible
                            if r["NAZEV"].strip()}),
        "name_keys_est": len({norm_inn(r["NAZEV"]) for r in ingestible
                              if r["NAZEV"].strip()}),
        "substances_new_est": stats["substance_map"]["new_inn_count"],
        "db_products": len(db_products),
        "db_eu_name_keys": len(eu_keys),
    }
    stats["elapsed_s"] = round(time.time() - t0, 1)

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "cz_dry_run.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 摘要 ----
    print(f"== 快照 == {stats['snapshot']['zip_bytes']:,} B  "
          f"sha256={stats['snapshot']['zip_sha256'][:16]}…  "
          f"platnost {stats['snapshot']['platnost_od']}–{stats['snapshot']['platnost_do']}")
    p = stats["product"]
    print(f"== 产品 == {p['rows']:,} 行 × {p['columns']} 列；"
          f"商品名去重 {p['distinct_name']:,}；注册名去重 {p['distinct_name_reg']:,}")
    print("   状态:", stats["status"])
    print("   供货标记 DODAVKY:", stats["dodavky"])
    print(f"== 规格 == 可数值解析 {stats['strength']['parse_rate']:.1%}  分类 {stats['strength']['classes']}")
    print(f"   多段（复方/浓度）行 {stats['strength']['multi_part']:,}")
    for s in stats["strength"]["samples"][:6]:
        print("   样例:", s)
    print(f"== 剂型 == form_base 覆盖 {sum(stats['form']['base'].values()):,} 行；"
          f"未映射 {stats['form']['unmapped_rows']:,} 行")
    print("   top:", list(stats["form"]["base"].items())[:8])
    print(f"== 途径 == 可映射 {stats['route']['mapped']:,}；未映射 {stats['route']['unmapped']:,}")
    print(f"== ATC == {stats['atc']['classes']}")
    c = stats["composition"]
    print(f"== 成分 == {c['active_rows']:,} 行活性成分，覆盖 {c['products_with_active']:,} 个产品；"
          f"含量可数值 {c['amount_numeric_rate']:.1%}")
    print(f"   每产品成分数:", c["ingredient_count_dist"])
    m = stats["substance_map"]
    print(f"== 成分映射 == 命中 {m['hit_rate']:.1%}（{m['tiers']}）；未命中 {m['miss']:,}；"
          f"新成分 {m['new_inn_count']:,}")
    print("   未命中 top:", m["new_inn_top"][:10])
    print(f"== EU 去重 == RC 以 EU/ 开头 {stats['eu_overlap']['rc_eu_prefix_rows']:,} 行"
          f"（{stats['eu_overlap']['rc_eu_prefix_pct']:.1%}）")
    pr = stats["projection"]
    print("== 预测入库 ==")
    for k in ("products", "products_excluded_fsmp_pzlu", "products_with_component",
              "components", "trade_names", "name_keys_est", "substances_new_est"):
        print(f"   {k:<28} {pr[k]:,}")
    print(f"\n耗时 {stats['elapsed_s']}s；明细 -> {(WORK / 'cz_dry_run.json').relative_to(ROOT)}")
    return 0


# ---------------------------------------------------------------------------
# 自检（离线，不读库）
# ---------------------------------------------------------------------------
def self_check() -> int:
    fails: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    # 1) 变音符号归一（本任务是硬要求：数据侧必须给出折叠规则）
    for raw, want in (("LÉČIVA", "LECIVA"), ("ŘEBŘÍČKOVÁ NAŤ", "REBRICKOVA NAT"),
                      ("ĎÁBEL", "DABEL"), ("ŤUKAT", "TUKAT"), ("ŮČET", "UCET"),
                      ("PŘÍPRAVEK", "PRIPRAVEK"), ("ŽLUŤOUČKÝ", "ZLUTOUCKY")):
        got = fold_cs(raw)
        check(got == want, f"fold_cs({raw!r}) = {got!r}，期望 {want!r}")
    # NFKD 本身就能折掉 ů/ď/ť（预组合字符有 canonical decomposition），CZ_FOLD 是显式兜底；
    # 这里断言「表里的 15 个字母确实覆盖了捷克语字母表」，改表时不会漏。
    cs_letters = "áčďéěíňóřšťúůýž"
    check(all(ch in CZ_FOLD for ch in cs_letters),
          "CZ_FOLD 没覆盖全部捷克语变音字母")
    check(not re.search(r"[^\x00-\x7f]", fold_cs(cs_letters.upper() + cs_letters)),
          "fold_cs 后仍含非 ASCII 字符")

    # 2) 规格解析
    cases = [
        ("500MG", [(500.0, "mg")]),
        ("0,3MG", [(0.3, "mg")]),
        ("300MCG", [(300.0, "mcg")]),
        ("450MG/50MG", [(450.0, "mg"), (50.0, "mg")]),
        ("1MG/ML", [(1.0, "mg")]),
        ("20MG/G+10MG/G", [(20.0, "mg"), (10.0, "mg")]),
    ]
    for sila, want in cases:
        got = [(p.get("value"), p.get("unit")) for p in split_strength(sila)]
        check(got == want, f"split_strength({sila!r}) = {got}，期望 {want}")
    check(split_strength("1MG/ML")[0]["per_volume_unit"] == "mL",
          "1MG/ML 应识别出「每 mL」")
    check(split_strength("5CH")[0]["kind"] == "not_numeric", "5CH 应判为 not_numeric")
    check(split_strength("") == [], "空串应返回 []")

    # 3) ATC 粒度
    check(classify_atc("N02BE01") == "substance", "N02BE01 应为 7 位")
    check(classify_atc("V06XX") == "group", "V06XX 应为组码")
    check(classify_atc("") == "none", "空应判 none")

    # 4) 剂型映射（复用 openFDA 词典）
    for en, want in (("Tablet", "tablet"), ("Solution for injection", "injection"),
                     ("Suppository", "suppository")):
        got = form_base_of(en)
        check(got == want, f"form_base_of({en!r}) = {got!r}，期望 {want!r}")

    # 5) 编码 / 表结构 / 行数（金值：快照 DLP20261027）
    check(ZIP_PATH.exists(), f"缺快照 {ZIP_PATH}（先 --fetch）")
    if ZIP_PATH.exists():
        with zipfile.ZipFile(ZIP_PATH) as zf:
            names = set(zf.namelist())
            check(PRODUCT_TABLE in names, "ZIP 里没有产品表")
            check(len(names) >= 25, f"ZIP 成员数异常：{len(names)}")
            raw = zf.read(PRODUCT_TABLE)
            try:
                text = raw.decode(CSV_ENCODING)
            except UnicodeDecodeError as exc:  # pragma: no cover
                fails.append(f"CP1250 解码失败：{exc}")
                text = ""
            check("LÉČIVÝ" in text or "PŘÍPRAVEK" in text or "Č" in text,
                  "CP1250 解码后没看到捷克语变音符号（编码可能变了）")
            rows = list(csv.DictReader(io.StringIO(text), delimiter=DELIM))
            check(len(rows[0]) == EXPECTED_COLS,
                  f"产品表列数 {len(rows[0])} != {EXPECTED_COLS}")
            check(len(rows) == 70032, f"产品行数 {len(rows)} != 70,032（快照换了就改金值）")
            check("NAZEV" in rows[0] and "SILA" in rows[0] and "ATC_WHO" in rows[0],
                  "产品表缺关键列")
            # 许可红线：只读事实表，说明书/文献表一律不读
            for bad in ("dlp_nazvydokumentu.csv", "dlp_splp.csv", "dlp_vpois.csv"):
                check(bad not in ALLOWED_TABLES, f"{bad} 不应在白名单里（第三方 IP 文档）")

    for f in fails:
        print(f"  !! {f}")
    print("自检通过" if not fails else f"自检失败 {len(fails)} 项")
    return 1 if fails else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="捷克 SÚKL DLP：抓快照 / 干跑 / 自检（不写库）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fetch", action="store_true", help="抓快照（写 data/raw）")
    g.add_argument("--dry-run", action="store_true", help="读快照 → 解析 → 统计（默认）")
    g.add_argument("--self-check", action="store_true", help="离线断言")
    ap.add_argument("--db", default=None, help="只读库（默认 data/drugs.db）")
    args = ap.parse_args()
    if args.fetch:
        raise SystemExit(fetch())
    if args.self_check:
        raise SystemExit(self_check())
    db = Path(args.db) if args.db else ROOT / "data" / "drugs.db"
    if not db.exists():
        raise SystemExit(f"库不存在：{db}")
    raise SystemExit(dry_run(db))


if __name__ == "__main__":
    main()
