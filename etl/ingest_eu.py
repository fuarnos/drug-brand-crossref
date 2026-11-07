# -*- coding: utf-8 -*-
"""EU 区域层 ETL（EC Union Register 为主 + EMA medicines JSON 补名字/状态）。

背景（task-20，依据 `reports/ema-evaluation-20261107.md`）：
  EU 集中审批是**区域层**，不是第 11 个国家市场：写 `product.region='EU'` + `country=NULL`
  （`db/schema.sql` 已有 XOR CHECK），不污染国家下拉/国别统计；`coverage` 视图用
  `COALESCE(country, region)` 给 EU 单独一行。

数据源（快照都在 `data/raw/ema_20261107/`，`data/raw/` 不入库）：
  1. **EC Union Register ODS**（主源，`ods_products.json`，CC BY 4.0）
     `https://ec.europa.eu/health/documents/community-register/ods/ods_products.json`
     6,476 行；本 ETL 只取 `Type='Human'` + `Category='Centrally authorised'` → **2,095 行**。
     提供：药名（EN）、活性成分、EU 号、ATC、MAH（100%）、授权日期、状态、EMA 链接。
  2. **EMA medicines JSON**（补名字/状态/INN/EMA 号）
     `https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json`
     2,757 行（Human 2,357）；提供 `ema_product_number`（EMEA/H/C/…）、INN、`medicine_status`、
     `medicine_url`、MAH。**两源 ID 体系不同**（`EU/1/13/882` ↔ `EMEA/H/C/005600`，交集 0），
     所以连接键用 **EPAR URL**（UR `EMALink` ↔ EMA `medicine_url`），URL 对不上时用
     「药名归一后唯一且两侧都唯一」兜底；不做模糊/猜测匹配。

字段缺口（两源都没有，绝不猜）：
  - **没有规格（strength）、没有剂型（pharmaceutical form）、没有包装** →
    `product.dosage_form='unknown'`、`form_base=NULL`、`route=NULL`、`release='none'`、`pack=NULL`，
    `product_component.strength_value/strength_unit` 留空；页面按「规格未收录」渲染。
  - **不新增 `substance`**：活性成分只做**精确映射**（slug / INN 归一 / 拆盐 base，复用
    `etl/ingest_ema_medicines.py:SubstanceMapper` 已验证的四级规则），映射不上的产品照写
    （名称 + MAH + ATC + 状态 + EU 号仍在），只是没有 `product_component`。

许可：两源都可再发布（EMA Legal notice 要求每份内容署名 EMA；Union Register 是 CC BY 4.0）。
`source` 表写入两条行（`eu_union_register` 为产品主源，`ema_medicines` 为对账/补充源）。

CLI：
    python etl/ingest_eu.py                      # 默认 dry-run：只读开库，打印将写入的行数与样例
    python etl/ingest_eu.py --dry-run --db <db>  # 指定库（只读）
    python etl/ingest_eu.py --apply --db <副本库> # 写正式表（本期不执行；真实库需 --allow-real）
    python etl/ingest_eu.py --rollback --manifest <json> --db <副本库>

本期纪律（task-20）：**不写 `data/drugs.db`**，只准备 ETL 与 dry-run 证据；写入窗口等 v0.10.0
发布后单独开（见 `reports/eu-ingest-prep-20261107.md` §执行窗口）。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from ingest_ema_medicines import SubstanceMapper, _variant_resolver  # noqa: E402
from ingest_openfda_ndc import slug  # noqa: E402
from normalize_name import normalize  # noqa: E402

# Windows 控制台默认 GBK，许可文本里的 © / 中文会让 print 抛 UnicodeEncodeError；统一按 UTF-8 输出。
try:  # pragma: no cover - 只影响终端显示
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

RAW = ROOT / "data" / "raw" / "ema_20261107"
UR_JSON = RAW / "ods_products.json"
EMA_JSON = RAW / "ema_medicines.json"
DEFAULT_DB = ROOT / "data" / "drugs.db"
WORK = ROOT / ".tmp" / "eu-ingest"

REGION = "EU"
SOURCE_UR = "eu_union_register"
SOURCE_EMA = "ema_medicines"
TODAY = date.today().isoformat()

# 只取「人用 + 中心审批」；UR 的 551 行 Nationally authorised 属于成员国数据，不进 EU 层。
UR_TYPE_HUMAN = "Human"
UR_CATEGORY_CENTRAL = "Centrally authorised"

# UR 状态 → schema 的 product.status 枚举（active/discontinued/withdrawn/unknown）。
# 不在枚举里的（Refused / Suspended / Expired / Not renewed …）一律 unknown，原文写进 note，
# 页面按原文显示状态——不臆造「在售/停用」。
STATUS_MAP = {
    "Active": "active",
    "Withdrawn": "withdrawn",
    "Revoked": "withdrawn",
    "Annulled": "withdrawn",
    "Refused": "unknown",
    "Expired / Sunset clause": "unknown",
    "Not renewed": "unknown",
    "Suspended": "unknown",
}

SOURCES = {
    SOURCE_UR: {
        "name": "European Commission — Union Register of medicinal products",
        "url": "https://ec.europa.eu/health/documents/community-register/html/index_en.htm",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "data_as_of": "2026-11-03",
        "data_as_of_note": "snapshot：ods_products.json 的 HTTP Last-Modified（2026-11-03 08:24 UTC）",
        "notes": "EU 中心审批（Centralised procedure）法律注册表；本 ETL 的产品主源。"
                 "再发布须署名 European Commission / Union Register 并链 CC BY 4.0。",
    },
    SOURCE_EMA: {
        "name": "European Medicines Agency — Medicines data (JSON)",
        "url": "https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format",
        "license": "© European Medicines Agency; re-use permitted with acknowledgement "
                   "(EMA legal notice)",
        "license_url": "https://www.ema.europa.eu/en/about-us/about-website/legal-notice",
        "data_as_of": "2026-11-06",
        "data_as_of_note": "snapshot：JSON meta.timestamp = 2026-11-06T18:02:08Z（每日 2 次重生成）",
        "notes": "对账/补充源（EMA 号、INN、medicine_status）；可再发布，须每份内容署名 EMA，"
                 "不得使用 EMA logo。",
    },
}


# ---------------------------------------------------------------- 小工具
def _norm_text(text: str) -> str:
    """名称归一键：去重音 + 小写 + 非字母数字收成单空格（只用于比较，不写库）。"""
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _url_key(url: str) -> str:
    """EPAR 链接归一：去协议/查询/锚点/末尾斜杠，统一小写。"""
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = u.split("#")[0].split("?")[0].rstrip("/")
    return u


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _first_text(items, lang: str = "EN") -> str:
    """UR 的多语言数组（Name / ActiveSubstance / Indication）取指定语言的第一条。"""
    for item in items or []:
        if (item or {}).get("LanguageCode") == lang and (item.get("Text") or "").strip():
            return (item["Text"] or "").strip()
    for item in items or []:
        if (item or {}).get("Text") or "":
            return (item["Text"] or "").strip()
    return ""


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(text: str) -> str:
    """UR 文本清洗：去内嵌 HTML（如 `<sup>177</sup>`）、去多余空白。"""
    s = _TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", s).strip()


# 复方切分：` / `、`+`、`;`、` and ` 一定切；紧凑斜杠只在「每段都像药名」时才切
# （避免把疫苗株名 A/California/7/2009 拆散——EMEA 数据里这类串必须整体保留）。
_SPLIT_SOFT_RE = re.compile(r"\s+/\s+|\s*\+\s*|\s*;\s*|\s+and\s+")
_PLAIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z \-]{2,}")


def _split_substances(text: str) -> list[str]:
    """活性成分串 → 成分 token 列表（复方拆成多条，单成分就是 1 条）。

    UR 每个产品只给一条 `ActiveSubstance` 文本，复方（如 `salmeterol/fluticasone
    propionate`、`emtricitabine / tenofovir disoproxil`）必须拆开才能挂多个
    product_component，否则整串映射不上、复方产品会变成「无成分」。
    """
    text = _clean_text(text)
    if not text:
        return []
    out: list[str] = []
    for part in _SPLIT_SOFT_RE.split(text):
        part = part.strip(" .,;")
        if not part:
            continue
        if "/" in part:
            segs = [x.strip() for x in part.split("/") if x.strip()]
            if len(segs) > 1 and all(_PLAIN_WORD_RE.fullmatch(x) for x in segs):
                out.extend(segs)
                continue
        out.append(part)
    return out


def pick_atc(atc_items) -> tuple[str, str]:
    """UR 的 ATC 数组 → (code, description)。优先 5 级码；没有就取最长的合法码。

    UR 里 37 行无 ATC、1 行有两个 5 级码（复方）；不猜归属，只取一个码做产品级标注。
    """
    codes = [(str(a.get("Code") or "").strip(), str(a.get("Description") or "").strip(),
              str(a.get("Level") or "").strip())
             for a in atc_items or []]
    codes = [c for c in codes if re.fullmatch(r"[A-Z]\d{2}[A-Z]{0,2}\d{0,2}", c[0] or "")]
    if not codes:
        return "", ""
    for code, desc, level in codes:
        if level == "5":
            return code, desc
    code, desc, _lvl = max(codes, key=lambda c: len(c[0]))
    return code, desc


def _strip_previously(name: str) -> tuple[str, str]:
    """EMA 药名里的 `X (previously Y)` → (X, Y)；没有就是 (name, '')。"""
    m = re.match(r"^(.*?)\s*\(previously\s+(.*?)\)\s*$", name or "", flags=re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return (name or "").strip(), ""


# ---------------------------------------------------------------- 解析
def load_union_register(path: Path = UR_JSON) -> tuple[list[dict], dict]:
    """读 Union Register ODS，只保留 Human + Centrally authorised。"""
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("data") or []
    kept: list[dict] = []
    stats: Counter = Counter()
    for row in rows:
        stats["rows_total"] += 1
        stats[f"type:{row.get('Type') or '(empty)'}"] += 1
        stats[f"category:{row.get('Category') or '(empty)'}"] += 1
        if row.get("Type") != UR_TYPE_HUMAN or row.get("Category") != UR_CATEGORY_CENTRAL:
            continue
        name = _clean_text(_first_text(row.get("Name")))
        if not name:
            stats["skip_no_name"] += 1
            continue
        atc_code, atc_desc = pick_atc(row.get("ATC"))
        substances = _split_substances(_first_text(row.get("ActiveSubstance")))
        kept.append({
            "eu_number": (row.get("EUNumber") or "").strip(),
            "name": name,
            "status_raw": (row.get("Status") or "").strip(),
            "authorisation_date": (row.get("AuthorisationDate") or "").strip(),
            "last_decision_date": (row.get("LastDecisionDate") or "").strip(),
            "mah": ((row.get("MAH") or {}).get("Name") or "").strip(),
            "mah_address": ((row.get("MAH") or {}).get("Address") or "").strip(),
            "atc": atc_code,
            "atc_desc": atc_desc,
            "substances": substances,
            "ur_url": (row.get("URI") or "").strip(),
            "ema_url": (row.get("EMALink") or "").strip(),
        })
        stats["rows_kept"] += 1
    return kept, dict(stats)


def load_ema(path: Path = EMA_JSON) -> tuple[dict, dict]:
    """读 EMA medicines JSON，建两个索引：EPAR URL → 行、归一药名 → 行列表。"""
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("data") or []
    meta = doc.get("meta") or {}
    by_url: dict[str, dict] = {}
    by_name: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("category") != "Human":
            continue
        name, previous = _strip_previously(row.get("name_of_medicine") or "")
        rec = {
            "ema_number": (row.get("ema_product_number") or "").strip(),
            "name": name,
            "previous_name": previous,
            "status_raw": (row.get("medicine_status") or "").strip(),
            "inn": (row.get("international_non_proprietary_name_common_name") or "").strip(),
            "atc": (row.get("atc_code_human") or "").strip(),
            "mah": (row.get("marketing_authorisation_developer_applicant_holder") or "").strip(),
            "url": (row.get("medicine_url") or "").strip(),
            "auth_date": (row.get("marketing_authorisation_date") or "").strip(),
            "decision_date": (row.get("european_commission_decision_date") or "").strip(),
            "last_updated": (row.get("last_updated_date") or "").strip(),
        }
        key = _url_key(rec["url"])
        if key:
            by_url.setdefault(key, rec)
        nk = _norm_text(rec["name"])
        if nk:
            by_name.setdefault(nk, []).append(rec)
    return {"by_url": by_url, "by_name": by_name, "meta": meta}, {"rows_total": len(rows)}


def merge(ur_rows: list[dict], ema_idx: dict) -> tuple[list[dict], dict]:
    """UR 为主，EMA 按 EPAR URL → 药名（两侧都唯一）补名字/状态/EMA 号。

    药名兜底只在「UR 侧这个名字只出现 1 次、EMA 侧也只有 1 条」时使用：UR 里有 12 个
    商品名各自对应 2 个 EU 号（不同包装/规格），按名兜底会把同一条 EMA 记录挂到两行上，
    那是猜，所以直接跳过（记为 name_ambiguous）。
    """
    stats: Counter = Counter()
    by_url = ema_idx["by_url"]
    by_name = ema_idx["by_name"]
    ur_name_counts = Counter(_norm_text(r["name"]) for r in ur_rows)
    out: list[dict] = []
    for row in ur_rows:
        ema = by_url.get(_url_key(row["ema_url"])) if row.get("ema_url") else None
        method = "url" if ema else ""
        nk = _norm_text(row["name"])
        if not ema:
            cands = by_name.get(nk) or []
            if len(cands) == 1 and ur_name_counts[nk] == 1:
                ema, method = cands[0], "name"
            elif len(cands) == 1:
                stats["name_ambiguous"] += 1
        if not ema and row.get("eu_number") and not row.get("ema_url"):
            stats["ur_no_ema_link"] += 1
        stats[f"match:{method or 'none'}"] += 1
        merged = dict(row)
        merged["ema"] = ema
        merged["match"] = method or "none"
        # 名字：UR 是法律注册表的名（权威）；EMA 名带 "(previously …)"，只用来对账。
        merged["display_name"] = row["name"]
        out.append(merged)
    return out, dict(stats)


def build_records(products: list[dict], mapper: SubstanceMapper) -> tuple[list[dict], list[dict], dict]:
    """归一化 + 成分映射（只精确映射，不新增 substance）。

    口径（不猜）：
      - 单成分：映射成功则写 1 条 product_component；
      - 复方：**全部成分都映射成功**才写（缺一个就整条不写，避免把复方显示成单方）；
      - 映射不上：产品照写（名称/MAH/ATC/状态/EU 号仍在），只是没有成分。
    """
    stats: Counter = Counter()
    comps: list[dict] = []
    for idx, p in enumerate(products):
        p["row_key"] = f"p{idx:05d}"
        p["status"] = STATUS_MAP.get(p["status_raw"], "unknown")
        stats[f"status_raw:{p['status_raw'] or '(empty)'}"] += 1
        stats[f"status:{p['status']}"] += 1
        stats["products"] += 1
        tokens = p.get("substances") or []
        if not tokens:
            stats["products_no_substance"] += 1
        mapped = [(t, *mapper.map(t)) for t in tokens]
        p["n_ingredients"] = len(mapped)
        p["mapping_methods"] = sorted({m for _t, _s, m in mapped if _s})
        p["unmapped_tokens"] = [t for t, sid, _m in mapped if not sid]
        n_map = sum(1 for _t, sid, _m in mapped if sid)
        stats["ingredient_tokens"] += len(mapped)
        stats["ingredient_tokens_mapped"] += n_map
        p["components_planned"]: list[dict] = []
        if mapped and n_map == len(mapped):
            stats["products_all_mapped"] += 1
            for ord_, (token, sid, method) in enumerate(mapped):
                row = {"row_key": p["row_key"], "ord": ord_, "token": token,
                       "substance_id": sid, "method": method}
                comps.append(row)
                p["components_planned"].append(row)
        elif mapped:
            stats["products_none_mapped" if n_map == 0 else "products_partial_mapped"] += 1
        for _t, _sid, method in mapped:
            stats[f"map_method:{method}"] += 1
    return products, comps, dict(stats)


# ---------------------------------------------------------------- 库访问
def _connect(db_path: Path, write: bool) -> sqlite3.Connection:
    if write:
        db = sqlite3.connect(db_path, timeout=120)
        db.execute("PRAGMA foreign_keys=ON")
    else:
        db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    return db


def _require_region_schema(db: sqlite3.Connection) -> None:
    row = db.execute("SELECT sql FROM sqlite_master WHERE name='product'").fetchone()
    if not row or "region" not in (row["sql"] or ""):
        raise SystemExit("product.region 不存在：先跑 `python db/init_db.py` 完成 region schema 迁移"
                         "（country 可空 + region 列 + XOR CHECK + coverage COALESCE）。")


def _guard_real(db_path: Path, action: str, allow_real: bool) -> None:
    """真实库写保护：EU 写入窗口未开（等 v0.10.0 发布），本任务只允许副本。"""
    try:
        is_real = db_path.resolve() == DEFAULT_DB.resolve()
    except OSError:
        is_real = False
    if is_real and action == "apply" and not allow_real:
        raise SystemExit(
            f"拒绝在真实库 {db_path} 写入 EU 层：写入窗口未开（等 v0.10.0 发布后单独执行）。\n"
            "先在副本上 --apply 验证；确需写真实库时加 --allow-real，并按报告 §执行窗口 备份+清单。")
    if is_real and action == "apply":
        print(f"!! 警告：正在写真实库 {db_path}（--allow-real），请确认已备份并持有回滚清单。")


def _source_sql() -> str:
    """`source` 表两条行的 INSERT SQL 草案（dry-run 打印，写库窗口照抄）。"""
    lines = []
    for sid, meta in SOURCES.items():
        vals = [sid, meta["name"], meta["url"], meta["license"], meta["license_url"],
                TODAY, meta["data_as_of"], meta["data_as_of_note"], meta["notes"]]
        quoted = ", ".join("NULL" if v is None else "'" + str(v).replace("'", "''") + "'"
                           for v in vals)
        lines.append(
            "INSERT INTO source (source_id, name, url, license, license_url, retrieved_at,"
            " data_as_of, data_as_of_note, notes)\nVALUES (" + quoted + ")\n"
            "ON CONFLICT(source_id) DO UPDATE SET retrieved_at=excluded.retrieved_at,"
            " data_as_of=excluded.data_as_of, notes=excluded.notes;")
    return "\n\n".join(lines)


# 写库窗口要执行的 6 条语句；dry-run 用 EXPLAIN 逐条编译一遍（不写库），提前抓列名/语法错误。
_WRITE_STATEMENTS = (
    ("source", "INSERT INTO source (source_id, name, url, license, license_url, retrieved_at,"
               " data_as_of, data_as_of_note, notes) VALUES (?,?,?,?,?,?,?,?,?)"),
    ("product", "INSERT OR REPLACE INTO product (product_id, country, region, dosage_form,"
                " form_base, route, release, pack, mah, approval_id, category, is_branded,"
                " status, status_date, source_id, source_url, retrieved_at, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"),
    ("corroboration", "INSERT OR IGNORE INTO corroboration (product_id, source_type, url,"
                      " retrieved_at, verified_by, note) VALUES (?,?,?,?,?,?)"),
    ("name_key", "INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                 " VALUES (?,?,?,?)"),
    ("name_variant", "INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                     " VALUES (?,?,?)"),
    ("product_name", "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                     " is_primary) VALUES (?,?,?,?)"),
    ("product_component", "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                          " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                          " VALUES (?,?,?,?,?,?,?)"),
    ("ingest_run", "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
                   " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)"),
)


def _check_write_statements(db: sqlite3.Connection) -> list[str]:
    """用 EXPLAIN 编译写库语句（不执行、不写库），返回编译失败的表名列表。"""
    bad: list[str] = []
    for table, sql in _WRITE_STATEMENTS:
        try:
            db.execute("EXPLAIN " + sql, tuple([None] * sql.count("?"))).fetchall()
        except sqlite3.Error:
            bad.append(table)
    return bad


# ---------------------------------------------------------------- dry-run
def _product_id(row: dict, used: set[str]) -> str:
    """产品主键：EU 号优先；没有 EU 号（76 行）用 UR 药名散列，保证确定性且唯一。

    不用 Python 内置 hash()（按进程加盐，不可复现），用 sha1 前 8 位。
    """
    eu = row.get("eu_number") or ""
    base = f"EU-{slug(eu)}" if eu else "EU-urn-" + slug(row["name"])[:40]
    pid = base[:64]
    if pid not in used:
        used.add(pid)
        return pid
    digest = hashlib.sha1(f"{eu}|{row['name']}".encode()).hexdigest()[:8]
    pid = f"{base[:54]}-{digest}"
    used.add(pid)
    return pid


def _dry_run_counts(db: sqlite3.Connection, products: list[dict], comps: list[dict]) -> dict:
    """在只读库上算「将要写入」的行数（name_key/name_variant 是否已存在等）。"""
    resolve = _variant_resolver(db)
    existing_keys = {r[0] for r in db.execute("SELECT key_id FROM name_key")}
    existing_pids = {r[0] for r in db.execute("SELECT product_id FROM product")}

    comps_by_row: dict[str, list[dict]] = {}
    for c in comps:
        comps_by_row.setdefault(c["row_key"], []).append(c)

    used_pids: set[str] = set()
    new_keys: list[str] = []
    new_variants: list[tuple[str, str]] = []
    n_components = n_no_variant = n_products_no_component = 0
    pid_collisions = 0
    samples: list[dict] = []
    for p in products:
        pid = _product_id(p, used_pids)
        p["product_id"] = pid
        if pid in existing_pids:
            pid_collisions += 1
        key = (normalize(p["display_name"]).norm or "").strip()
        p["key_id"] = key
        if key and key not in existing_keys and key not in new_keys:
            new_keys.append(key)
        raw_name = p["display_name"]
        if key and raw_name:
            if not db.execute("SELECT 1 FROM name_variant WHERE key_id=? AND raw=?",
                              (key, raw_name)).fetchone():
                new_variants.append((key, raw_name))
        written: list[dict] = []
        for c in comps_by_row.get(p["row_key"], []):
            vid = resolve(c["substance_id"], c["token"])
            if not vid:
                n_no_variant += 1
                continue
            written.append({"ord": len(written), "token": c["token"],
                            "substance_id": c["substance_id"], "variant_id": vid,
                            "method": c["method"]})
            n_components += 1
        p["components"] = written
        if not written:
            n_products_no_component += 1
        if len(samples) < 5:
            samples.append({
                "product_id": pid, "name": p["display_name"], "eu_number": p["eu_number"],
                "status_raw": p["status_raw"], "status": p["status"], "atc": p["atc"],
                "mah": p["mah"], "match": p["match"],
                "ema_number": (p.get("ema") or {}).get("ema_number", ""),
                "components": [f"{w['token']} → {w['substance_id']}/{w['variant_id']}"
                               for w in written],
            })
    return {
        "products": len(products),
        "components": n_components,
        "components_no_variant": n_no_variant,
        "products_without_component": n_products_no_component,
        "name_keys_new": len(new_keys),
        "name_variants_new": len(new_variants),
        "product_names": len(products),
        "product_id_collisions_with_db": pid_collisions,
        "samples": samples,
        "_new_keys": new_keys,
        "_new_variants": new_variants,
    }


def cmd_dry_run(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    if not UR_JSON.exists() or not EMA_JSON.exists():
        raise SystemExit(f"缺快照：{UR_JSON} / {EMA_JSON}（先按报告 §源快照 下载）")
    t0 = time.perf_counter()
    ur_rows, ur_stats = load_union_register(args.ur)
    ema_idx, ema_stats = load_ema(args.ema)
    merged, match_stats = merge(ur_rows, ema_idx)
    db = _connect(db_path, write=False)
    try:
        _require_region_schema(db)
        mapper = SubstanceMapper(db)
        products, comps, build_stats = build_records(merged, mapper)
        counts = _dry_run_counts(db, products, comps)
        unmapped = Counter(t for p in products for t in p.get("unmapped_tokens") or [])
        mapped_subs = {c["substance_id"] for c in comps}
        n_tokens = len({t for p in products for t in (p.get("substances") or [])})
        n_tokens_mapped = n_tokens - len(unmapped)
        bad_statements = _check_write_statements(db)
        source_rows = {r["source_id"] for r in db.execute("SELECT source_id FROM source")}
    finally:
        db.close()
    elapsed = round(time.perf_counter() - t0, 2)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db": str(db_path),
        "db_mode": "read-only",
        "snapshot": {
            "union_register": {"path": str(UR_JSON.relative_to(ROOT)), "bytes": UR_JSON.stat().st_size,
                               "sha256": _sha256(UR_JSON),
                               "rows_total": ur_stats.get("rows_total"),
                               "rows_kept": ur_stats.get("rows_kept"),
                               "filter": f"Type={UR_TYPE_HUMAN} & Category={UR_CATEGORY_CENTRAL}"},
            "ema": {"path": str(EMA_JSON.relative_to(ROOT)), "bytes": EMA_JSON.stat().st_size,
                    "sha256": _sha256(EMA_JSON),
                    "rows_total": ema_stats["rows_total"],
                    "meta_timestamp": (ema_idx.get("meta") or {}).get("timestamp")},
        },
        "join": {k.split(":", 1)[1]: v for k, v in match_stats.items() if k.startswith("match:")},
        "ur_stats": ur_stats,
        "build_stats": build_stats,
        "substance": {
            "tokens": n_tokens,
            "tokens_mapped": n_tokens_mapped,
            "token_rate": round(n_tokens_mapped / max(1, n_tokens) * 100, 1),
            "components_per_product": build_stats.get("ingredient_tokens", 0),
            "distinct_substances": len(mapped_subs),
            "unmapped_unique": len(unmapped),
            "unmapped_top": unmapped.most_common(25),
        },
        "would_write": {k: v for k, v in counts.items() if not k.startswith("_")},
        "write_statement_check_failed": bad_statements,
        "samples": counts["samples"],
        "sources_existing": sorted(source_rows & set(SOURCES)),
        "sources_missing": sorted(set(SOURCES) - source_rows),
        "elapsed_s": elapsed,
    }
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "eu_dry_run.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "samples"},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (WORK / "eu_dry_run_samples.json").write_text(
        json.dumps(summary["samples"], ensure_ascii=False, indent=1), encoding="utf-8")
    (WORK / "eu_source_rows.sql").write_text(_source_sql() + "\n", encoding="utf-8")
    preview = WORK / "eu_products_preview.csv"
    with preview.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["product_id", "name", "eu_number", "status_raw", "status", "atc", "mah",
                    "match", "ema_number", "ema_url", "ur_url", "substances", "substance_ids",
                    "variant_ids", "mapping_methods"])
        for p in products:
            w.writerow([p["product_id"], p["display_name"], p["eu_number"], p["status_raw"],
                        p["status"], p["atc"], p["mah"], p["match"],
                        (p.get("ema") or {}).get("ema_number", ""),
                        (p.get("ema") or {}).get("url", ""), p["ur_url"],
                        " | ".join(p.get("substances") or []),
                        " | ".join(w2["substance_id"] for w2 in p.get("components") or []),
                        " | ".join(w2["variant_id"] for w2 in p.get("components") or []),
                        " | ".join(w2["method"] for w2 in p.get("components") or [])])

    print("=== EU 区域层 dry-run（只读，不写库）===")
    print(f"  快照 UR : {UR_JSON.stat().st_size:,} B · {ur_stats.get('rows_total'):,} 行"
          f" → 保留 {ur_stats.get('rows_kept'):,}（{UR_TYPE_HUMAN} + {UR_CATEGORY_CENTRAL}）")
    print(f"  快照 EMA: {EMA_JSON.stat().st_size:,} B · {ema_stats['rows_total']:,} 行"
          f" · meta.timestamp={(ema_idx.get('meta') or {}).get('timestamp')}")
    print(f"  两源连接: " + " / ".join(f"{k}={v}" for k, v in summary["join"].items()))
    print(f"  状态映射: " + json.dumps({k.split(':')[1]: v for k, v in build_stats.items()
                                   if k.startswith("status:")}, ensure_ascii=False))
    print(f"  将写入产品     : {counts['products']:,}")
    print(f"  将写入成分     : {counts['components']:,}"
          f"（无成分产品 {counts['products_without_component']:,}：复方缺一成分整条不写 / "
          f"成分未收录；映射成功但无 variant {counts['components_no_variant']:,}）")
    print(f"  名称           : name_key 新建 {counts['name_keys_new']:,}"
          f" · name_variant 新建 {counts['name_variants_new']:,}"
          f" · product_name {counts['product_names']:,}")
    print(f"  成分映射       : {n_tokens_mapped}/{n_tokens} 个成分 token"
          f"（{summary['substance']['token_rate']}%）· 涉及 {len(mapped_subs):,} 个现有 substance"
          f" · 未映射 {len(unmapped):,} 个 token")
    print(f"  产品口径       : 全部成分映射上 {build_stats.get('products_all_mapped', 0):,}"
          f" / 部分映射 {build_stats.get('products_partial_mapped', 0):,}"
          f" / 全未映射 {build_stats.get('products_none_mapped', 0):,}"
          f" / 无成分串 {build_stats.get('products_no_substance', 0):,}")
    print(f"  product_id 冲突: {counts['product_id_collisions_with_db']}")
    print(f"  写库语句编译   : {'全部通过（EXPLAIN，未写库）' if not bad_statements else bad_statements}")
    print(f"  source 行      : 缺 {summary['sources_missing']}（SQL 见 "
          f"{(WORK / 'eu_source_rows.sql').relative_to(ROOT)}）")
    print(f"  预览 CSV       : {preview.relative_to(ROOT)}")
    print(f"  耗时 {elapsed}s · 汇总 {(WORK / 'eu_dry_run.json').relative_to(ROOT)}")
    print("\n  样例 3 条：")
    for s in summary["samples"][:3]:
        print("   " + json.dumps(s, ensure_ascii=False))
    print("\n  source 表 SQL 草案：\n" + _source_sql())
    return 0


# ---------------------------------------------------------------- 写库 / 回滚
def _insert_source_rows(db: sqlite3.Connection) -> None:
    """写/更新两条 source 行（eu_union_register 主源 + ema_medicines 补充源）。"""
    for sid, meta in SOURCES.items():
        db.execute(
            "INSERT INTO source (source_id, name, url, license, license_url, retrieved_at,"
            " data_as_of, data_as_of_note, notes) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(source_id) DO UPDATE SET name=excluded.name, url=excluded.url,"
            " license=excluded.license, license_url=excluded.license_url,"
            " retrieved_at=excluded.retrieved_at, data_as_of=excluded.data_as_of,"
            " data_as_of_note=excluded.data_as_of_note, notes=excluded.notes",
            (sid, meta["name"], meta["url"], meta["license"], meta["license_url"], TODAY,
             meta["data_as_of"], meta["data_as_of_note"], meta["notes"]))


def _write_rows(db: sqlite3.Connection, products: list[dict], counts: dict,
                run_id: str, rows_in: int) -> dict:
    """把 EU 层写进正式表（调用方管事务）。返回按表统计的写入行数。

    `--apply` 与 `--check-sql`（内存 schema 校验）共用这一段，保证「验证的就是要跑的」。
    """
    written: Counter = Counter()
    for p in products:
        pid = p["product_id"]
        ema = p.get("ema") or {}
        note_bits = [
            "EU 区域层（EC Union Register；非国别产品，不表示某国在售）",
            f"UR status: {p['status_raw'] or '?'}",
            f"EMA status: {ema['status_raw']}" if ema.get("status_raw") else "",
            f"EMA product number: {ema['ema_number']}" if ema.get("ema_number") else "",
            f"ATC: {p['atc']} {p['atc_desc']}".strip() if p.get("atc") else "",
            f"MAH: {p['mah']}" if p.get("mah") else "",
            f"Authorisation date: {p['authorisation_date']}" if p.get("authorisation_date") else "",
            "无规格/剂型/包装（两源均不含）",
        ]
        written["product"] += db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, region, dosage_form,"
            " form_base, route, release, pack, mah, approval_id, category, is_branded,"
            " status, status_date, source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, None, REGION, "unknown", None, None, "none", None,
             p.get("mah") or None, p.get("eu_number") or None, "EU centralised (human)", 1,
             p["status"], p.get("authorisation_date") or p.get("last_decision_date") or None,
             SOURCE_UR, p.get("ema_url") or p.get("ur_url") or SOURCES[SOURCE_UR]["url"],
             TODAY, " · ".join(b for b in note_bits if b)[:500])).rowcount
        if ema.get("url"):
            written["corroboration"] += db.execute(
                "INSERT OR IGNORE INTO corroboration (product_id, source_type, url,"
                " retrieved_at, verified_by, note) VALUES (?,?,?,?,?,?)",
                (pid, "regulator", ema["url"], TODAY, SOURCE_EMA,
                 f"EMA medicine record {ema.get('ema_number', '')}".strip())).rowcount
        key = p["key_id"]
        if key:
            written["name_key"] += db.execute(
                "INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                " VALUES (?,?,?,?)",
                (key, key, key.replace(" ", ""), normalize(p["display_name"]).script)).rowcount
            written["name_variant"] += db.execute(
                "INSERT OR IGNORE INTO name_variant (key_id, raw, source_id) VALUES (?,?,?)",
                (key, p["display_name"], SOURCE_UR)).rowcount
            written["product_name"] += db.execute(
                "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type, is_primary)"
                " VALUES (?,?,?,?)", (pid, key, "trade", 1)).rowcount
        for comp in p.get("components") or []:
            written["product_component"] += db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)",
                (pid, comp["ord"], comp["variant_id"], None, None, None, None)).rowcount
    written["ingest_run"] += db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, SOURCE_UR, TODAY, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         rows_in, counts["products"], rows_in - counts["products"], "ok",
         json.dumps({"region": REGION, "layer": "product-region",
                     "sources": [SOURCE_UR, SOURCE_EMA],
                     "counts": {k: v for k, v in counts.items() if not k.startswith("_")}},
                    ensure_ascii=False))).rowcount
    return dict(written)


def cmd_apply(args: argparse.Namespace) -> int:
    """把 EU 层写进正式表（本期不执行；必须先在有备份的库副本上验证）。"""
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    _guard_real(db_path, "apply", args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    ur_rows, _ur_stats = load_union_register(args.ur)
    ema_idx, _ = load_ema(args.ema)
    merged, _ = merge(ur_rows, ema_idx)
    db = _connect(db_path, write=True)
    t0 = time.perf_counter()
    try:
        _require_region_schema(db)
        _insert_source_rows(db)
        db.commit()
        mapper = SubstanceMapper(db)
        products, comps, _stats = build_records(merged, mapper)
        counts = _dry_run_counts(db, products, comps)
        run_id = f"{SOURCE_UR}-{TODAY}"
        db.execute("BEGIN IMMEDIATE")
        removed = db.execute("DELETE FROM product WHERE region=? AND source_id=?",
                             (REGION, SOURCE_UR)).rowcount
        written = _write_rows(db, products, counts, run_id, len(merged))
        db.commit()
        elapsed = round(time.perf_counter() - t0, 2)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    manifest = {
        "tool": "etl/ingest_eu.py",
        "db": str(db_path),
        "region": REGION,
        "source_id": SOURCE_UR,
        "supplement_source_id": SOURCE_EMA,
        "run_id": run_id,
        "created_at": TODAY,
        "product_ids": [p["product_id"] for p in products],
        "created_name_keys": counts["_new_keys"],
        "created_name_variants": [list(x) for x in counts["_new_variants"]],
        "counts": {k: v for k, v in counts.items() if not k.startswith("_")},
        "written": written,
        "rollback_hint": (
            "1) python etl/ingest_eu.py --rollback --manifest <本文件> --db <同一个库>；"
            "2) 或从备份恢复 data/drugs.db（窗口前必做备份）；"
            "3) 校验：SELECT COUNT(*) FROM product WHERE region='EU' 应为 0；"
            "coverage 视图应只剩 10 个国家行。"),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== EU 区域层写入完成 ===")
    print(json.dumps({"counts": manifest["counts"], "written": written},
                     ensure_ascii=False, indent=1))
    print(f"  撤销清单：{manifest_path}")
    print(f"  耗时 {elapsed}s · 旧 EU 行删除 {removed}")
    return 0


def cmd_check_sql(args: argparse.Namespace) -> int:
    """在**内存库**上按 `db/schema.sql` 建表 → 灌 source/product/name/component → 校验约束。

    这是写入窗口前的最后一道自检：跑的是 `_write_rows`（与 `--apply` 同一段代码），
    但目标库是 `:memory:`，**不碰任何库文件**。能提前抓出 CHECK/NOT NULL/FK/PK 问题。
    """
    db_path = (args.db if args.db.is_absolute() else (ROOT / args.db))
    ur_rows, ur_stats = load_union_register(args.ur)
    ema_idx, _ = load_ema(args.ema)
    merged, match_stats = merge(ur_rows, ema_idx)
    src = _connect(db_path, write=False)
    try:
        _require_region_schema(src)
        mapper = SubstanceMapper(src)
        products, comps, build_stats = build_records(merged, mapper)
        counts = _dry_run_counts(src, products, comps)
        sub_ids = sorted({c["substance_id"] for p in products for c in p.get("components") or []})
        var_ids = sorted({c["variant_id"] for p in products for c in p.get("components") or []})
        variants = []
        for i in range(0, len(var_ids), 500):
            chunk = var_ids[i:i + 500]
            variants += src.execute(
                "SELECT variant_id, substance_id FROM variant WHERE variant_id IN (%s)"
                % ",".join("?" * len(chunk)), chunk).fetchall()
        # 拆盐兜底可能把成分挂到「另一条 substance」的 variant 上（salt-orphan），
        # 所以 stub substance 要把 variant 自己的 substance_id 也并进来，否则内存库 FK 不过。
        all_sub_ids = sorted(set(sub_ids) | {r["substance_id"] for r in variants})
        subs = []
        for i in range(0, len(all_sub_ids), 500):
            chunk = all_sub_ids[i:i + 500]
            subs += src.execute(
                "SELECT substance_id, inn_en FROM substance WHERE substance_id IN (%s)"
                % ",".join("?" * len(chunk)), chunk).fetchall()
    finally:
        src.close()

    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    problems: list[str] = []
    try:
        mem.executescript(schema)
        mem.execute("PRAGMA foreign_keys=ON")
        for r in subs:
            mem.execute("INSERT INTO substance (substance_id, inn_en) VALUES (?,?)",
                        (r["substance_id"], r["inn_en"]))
        for r in variants:
            mem.execute("INSERT INTO variant (variant_id, substance_id) VALUES (?,?)",
                        (r["variant_id"], r["substance_id"]))
        mem.commit()  # 先清掉 stub 插入的事务，下面显式开一个（与 --apply 一致）
        base_bytes = mem.execute("SELECT page_count * page_size FROM pragma_page_count(),"
                                 " pragma_page_size()").fetchone()[0]
        run_id = f"{SOURCE_UR}-{TODAY}"
        mem.execute("BEGIN IMMEDIATE")
        _insert_source_rows(mem)
        written = _write_rows(mem, products, counts, run_id, len(merged))
        mem.commit()
        grown_bytes = mem.execute("SELECT page_count * page_size FROM pragma_page_count(),"
                                  " pragma_page_size()").fetchone()[0] - base_bytes
        fk = mem.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            problems.append(f"FK 违规 {len(fk)} 条：{[tuple(x)[:3] for x in fk[:5]]}")
        integrity = mem.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"integrity_check={integrity}")
        bad_xor = mem.execute(
            "SELECT COUNT(*) FROM product WHERE (country IS NOT NULL AND region IS NOT NULL)"
            " OR (country IS NULL AND region IS NULL)").fetchone()[0]
        if bad_xor:
            problems.append(f"country/region XOR 违规 {bad_xor} 行")
        if mem.execute("SELECT COUNT(*) FROM product WHERE region='EU' AND country IS NULL"
                       ).fetchone()[0] != counts["products"]:
            problems.append("EU 行数与 dry-run 不一致")
        if written.get("product", 0) != counts["products"]:
            problems.append(f"product 写入行数 {written.get('product')} ≠ {counts['products']}")
        if written.get("product_component", 0) != counts["components"]:
            problems.append(f"component 写入行数 {written.get('product_component')} ≠ "
                            f"{counts['components']}")
        nullable_strength = mem.execute(
            "SELECT COUNT(*) FROM product_component WHERE strength_value IS NULL"
            " AND strength_unit IS NULL").fetchone()[0]
        checks = {
            "schema": str((ROOT / "db" / "schema.sql").relative_to(ROOT)),
            "stub_substances": len(subs), "stub_variants": len(variants),
            "written": written,
            "eu_layer_bytes_estimate": grown_bytes,
            "products_region_eu": counts["products"],
            "components": counts["components"],
            "components_null_strength": nullable_strength,
            "foreign_key_check": "ok" if not fk else f"{len(fk)} 违规",
            "integrity_check": integrity,
            "join": {k.split(":", 1)[1]: v for k, v in match_stats.items() if k.startswith("match:")},
            "build_stats": build_stats,
            "problems": problems,
        }
    finally:
        mem.close()
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "eu_check_sql.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== EU 写库语句自检（内存 schema，不碰任何库文件）===")
    print(f"  schema: {checks['schema']} · stub substance {len(subs):,} / variant {len(variants):,}")
    print(f"  写入行数: " + json.dumps(written, ensure_ascii=False))
    print(f"  EU 产品 {counts['products']:,} · 成分 {counts['components']:,}"
          f"（strength 全 NULL {nullable_strength:,}）")
    print(f"  区域层数据体积（内存库 page_count×page_size 增量）: "
          f"{grown_bytes:,} B = {grown_bytes / 1e6:.2f} MB")
    print(f"  foreign_key_check={checks['foreign_key_check']} · integrity={integrity}")
    if problems:
        print("  !! 问题：")
        for p in problems:
            print("    - " + p)
        return 1
    print("  ✅ 全部通过（无 FK/CHECK/XOR 违规，行数与 dry-run 一致）")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    _guard_real(db_path, "apply", args.allow_real)
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单：{manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = _connect(db_path, write=True)
    try:
        db.execute("BEGIN IMMEDIATE")
        n = db.execute("DELETE FROM product WHERE region=? AND source_id=?",
                       (REGION, SOURCE_UR)).rowcount
        db.execute("DELETE FROM ingest_run WHERE run_id=?", (data.get("run_id") or "",))
        removed_variants = 0
        for key, raw in (data.get("created_name_variants") or []):
            cur = db.execute("DELETE FROM name_variant WHERE key_id=? AND raw=?", (key, raw))
            removed_variants += cur.rowcount
        removed_keys = 0
        for key in data.get("created_name_keys") or []:
            if not db.execute("SELECT 1 FROM product_name WHERE key_id=? LIMIT 1",
                              (key,)).fetchone():
                cur = db.execute("DELETE FROM name_variant WHERE key_id=?", (key,))
                removed_variants += cur.rowcount
                db.execute("DELETE FROM name_key WHERE key_id=?", (key,))
                removed_keys += 1
        db.commit()
    finally:
        db.close()
    print("=== EU 区域层回滚完成 ===")
    print(json.dumps({"db": str(db_path), "removed_products": n,
                      "removed_name_keys": removed_keys,
                      "removed_name_variants": removed_variants}, ensure_ascii=False, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EU 区域层（Union Register + EMA）ETL：默认 dry-run")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="目标库（dry-run 只读打开）")
    ap.add_argument("--ur", type=Path, default=UR_JSON, help="Union Register ODS 快照")
    ap.add_argument("--ema", type=Path, default=EMA_JSON, help="EMA medicines JSON 快照")
    ap.add_argument("--dry-run", action="store_true", help="只算不写（默认）")
    ap.add_argument("--check-sql", action="store_true",
                    help="在内存 schema 上跑写库语句自检（不碰任何库文件）")
    ap.add_argument("--apply", action="store_true", help="写正式表（本期不执行）")
    ap.add_argument("--rollback", action="store_true", help="按撤销清单回滚")
    ap.add_argument("--manifest", type=Path, default=WORK / "eu_manifest.json",
                    help="撤销清单路径（apply 时写、rollback 时读）")
    ap.add_argument("--allow-real", action="store_true",
                    help="允许写真实库 data/drugs.db（默认拒绝）")
    args = ap.parse_args(argv)
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    if args.check_sql:
        return cmd_check_sql(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
