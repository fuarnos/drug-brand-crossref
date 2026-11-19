# -*- coding: utf-8 -*-
"""马来西亚 NPRA / QUEST3+ 产品级数据 ETL（阶段 A：可干跑 / 可写副本库）。

许可（2026-11-20 取证，✅ 可再发布）
------------------------------------
`data.gov.my` 数据集 `pharmaceutical_products`（发布者 **NPRA / Ministry of Health
Malaysia**）明确写 **CC BY 4.0**：
  - 数据集页：https://data.gov.my/data-catalogue/pharmaceutical_products
  - 许可：https://creativecommons.org/licenses/by/4.0/
  - 义务：署名 NPRA / data.gov.my、附许可链接、标明本站做过修改；不暗示背书。
  - **不写「已获 NPRA 逐项许可」**——这是 CC BY 4.0 开放许可，直接按许可再发布。

数据形状
--------
`data/raw/my/pharmaceutical_products.csv`（28,333 行，10.6 MB，每日更新）：
  `reg_no, ref_no, product, status, description, holder, holder_osa, manufacturer,
   manufacturer_osa, importer, importer_osa, date_reg, date_end, active_ingredient,
   mdc_code, generic_name`
`data/raw/my/pharmaceutical_products_cancelled.csv`（1,623 行，7 列）：
  `reg_no, product, description, holder, manufacturer, date_reg, date_end`

口径（不猜、不换算）
--------------------
- **商品名不是主键**：`product_id` 只由 `reg_no` 派生；重号加后缀，名字只进
  `name_key / name_variant / product_name`。
- **剂型没有独立列**：只从商品名 + 通用名派生；派生不了写 `unknown` 并计数，不硬猜。
- **规格**：只解析 `active_ingredient` 的 `[数量;单位;…]` 原文；有 `mL/L` 基数才写
  `per_volume_*`；不换算、不四舍五入。
- **成分**：只映射库里已有 `substance`（`SgMapper.map_basic`）；天然产品/保健品
  映射不了就**不写 component**、计数；**不建新成分**。产品行仍保留（名字可查）。
- **不写使用建议 / 不做剂量换算**（AGENTS §1.3）。

CLI
---
    python etl/markets/my.py --fetch        # 下载 CSV + 数据集页到 data/raw/my/
    python etl/markets/my.py --dry-run      # 默认：只读库 → 计划 → 统计（不写库）
    python etl/markets/my.py --apply --db .tmp/my_dryrun.db
    python etl/markets/my.py --rollback --db .tmp/my_dryrun.db --manifest ...
    python etl/markets/my.py --apply --allow-real   # 仅写库窗口，Lead 明确说「写库窗口开」后

真实库写保护沿用 `_ingest_common.guard_real()`：没有 `--allow-real` 只能写副本。
"""

from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))

from ingest_openfda_ndc import form_base_of, release_of  # noqa: E402
from ingest_sg_hsa import SgMapper  # noqa: E402
from normalize_name import normalize  # noqa: E402
import _ingest_common as common  # noqa: E402

try:  # Windows 控制台 GBK；马来文/拉丁学名可能带重音
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

URL_DATASET = "https://data.gov.my/data-catalogue/pharmaceutical_products"
URL_DATASET_CANCELLED = "https://data.gov.my/data-catalogue/pharmaceutical_products_cancelled"
URL_CSV = "https://storage.data.gov.my/healthcare/pharmaceutical_products.csv"
URL_CSV_CANCELLED = (
    "https://storage.data.gov.my/healthcare/pharmaceutical_products_cancelled.csv")
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
RAW = ROOT / "data" / "raw" / "my"
SOURCES = ROOT / "data" / "sources"
DEFAULT_DB = ROOT / "data" / "drugs.db"
REAL_DB = DEFAULT_DB
WORK = ROOT / ".tmp" / "my-ingest"
DEFAULT_MANIFEST = SOURCES / "my_npra_ingest_manifest_20261120.json"
SOURCE_ID = "my_npra_products"
RETRIEVED_AT = "2026-11-20"
DATA_AS_OF = "2026-11-18"
LICENSE = {
    "spdx": "CC-BY-4.0",
    "title": "Creative Commons Attribution 4.0 International",
    "url": LICENSE_URL,
    "declared_in": URL_DATASET,
    "attribution_required": True,
    "site_attribution": (
        "National Pharmaceutical Regulatory Agency (NPRA), Malaysia / data.gov.my · CC BY 4.0"),
}
SOURCE_META = {
    "name": "National Pharmaceutical Regulatory Agency (NPRA), Malaysia — "
            "Approved / Cancelled Pharmaceutical Products (QUEST3+ via data.gov.my)",
    "url": URL_DATASET,
    "license": "CC BY 4.0",
    "license_url": LICENSE_URL,
    "retrieved_at": RETRIEVED_AT,
    "data_as_of": DATA_AS_OF,
    "data_as_of_note": "data.gov.my 数据集页 Last updated 2026-11-19 03:00；"
                       "数据截止 2026-11-18；每日更新",
    "notes": "马来西亚 NPRA QUEST3+ 行政记录，经 data.gov.my 开放数据门户发布；"
             "商品名/注册号/活性成分+含量/通用名；CC BY 4.0（署名 NPRA/data.gov.my、"
             "标明修改）；行政记录不得作为法律行动依据；剂型无独立列，按品名派生。",
}
UA = "drug-brand-crossref/0.1 (research; +https://github.com/fuarnos/drug-brand-crossref)"

# 来源单位 → 本站 product_component 单位口径（不换算，仅统一拼写）
UNIT_MAP = {
    "mg": "mg", "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "mcg": "mcg", "ug": "mcg", "µg": "mcg", "μg": "mcg", "microgram": "mcg",
    "iu": "IU", "me": "IU",
    "ml": "mL", "l": "L",
    "%": "%",
}
FORM_LABEL = {
    "tablet": "Tablet", "capsule": "Capsule", "liquid": "Liquid",
    "injection": "Injection", "topical": "Topical", "inhalation": "Inhalation",
    "suppository": "Suppository", "powder": "Powder", "effervescent": "Effervescent",
    "pellet": "Pellet", "stick": "Stick", "kit": "Kit", "gas": "Gas",
    "mouthwash": "Mouthwash", "oil": "Oil", "jelly": "Jelly", "nasal": "Nasal",
    "implant": "Implant", "film": "Film", "plaster": "Plaster", "gum": "Gum",
    "device": "Device", "cream": "Cream", "ointment": "Ointment", "gel": "Gel",
    "patch": "Patch", "drops": "Drops", "pessary": "Pessary", "enema": "Enema",
    "pill": "Pill", "other": "Other", "unknown": "Unknown",
}
STATUS_MAP = {
    "PRODUCT APPROVED": "active",
    "CONDITIONAL REGISTRATION": "active",
}


@dataclass
class Ingredient:
    raw: str
    strength: dict | None = None


@dataclass
class ProductPlan:
    product_id: str
    country: str
    dosage_form: str
    form_base: str
    release: str
    mah: str | None
    approval_id: str
    category: str | None
    status: str
    status_date: str | None
    source_url: str
    note: str
    names: list[tuple[str, str, int]] = field(default_factory=list)
    components: list[dict] = field(default_factory=list)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, force: bool = False) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size and not force:
        return {"url": url, "path": str(dest), "bytes": dest.stat().st_size,
                "sha256": sha256_file(dest), "cached": True}
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp, tmp.open("wb") as fh:
        last_modified = resp.headers.get("Last-Modified")
        content_length = resp.headers.get("Content-Length")
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    tmp.replace(dest)
    return {"url": url, "path": str(dest), "bytes": dest.stat().st_size,
            "sha256": sha256_file(dest), "cached": False,
            "last_modified": last_modified,
            "content_length_header": content_length,
            "elapsed_s": round(time.perf_counter() - t0, 1)}


def _gzip_copy(src: Path, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fh, gzip.open(dest, "wb", compresslevel=9) as out:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    return {"path": str(dest), "bytes": dest.stat().st_size,
            "sha256": sha256_file(dest), "source": str(src)}


def _count_csv(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def cmd_fetch(args: argparse.Namespace) -> int:
    """下载官方 CSV + 数据集页，落 data/raw/my；许可说明/压缩快照落 data/sources。"""
    RAW.mkdir(parents=True, exist_ok=True)
    license_dir = RAW / "license"
    license_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "source_id": SOURCE_ID,
        "fetched_at": now(),
        "data_as_of": DATA_AS_OF,
        "license": LICENSE,
        "dataset_page": URL_DATASET,
        "dataset_page_cancelled": URL_DATASET_CANCELLED,
        "files": {},
    }
    for key, url, name in (
        ("products", URL_CSV, "pharmaceutical_products.csv"),
        ("cancelled", URL_CSV_CANCELLED, "pharmaceutical_products_cancelled.csv"),
        ("dataset_page", URL_DATASET, "license/dataset_pharmaceutical_products.html"),
        ("dataset_page_cancelled", URL_DATASET_CANCELLED,
         "license/dataset_pharmaceutical_products_cancelled.html"),
    ):
        info = _download(url, RAW / name, force=args.force)
        info["role"] = key
        meta["files"][key] = info
        print(f"  {key}: {info['bytes']:,} B · {info['sha256'][:16]}…")
    meta["approved_rows"] = _count_csv(RAW / "pharmaceutical_products.csv")
    meta["cancelled_rows"] = _count_csv(RAW / "pharmaceutical_products_cancelled.csv")
    (RAW / "fetch_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    gz_approved = _gzip_copy(
        RAW / "pharmaceutical_products.csv",
        SOURCES / "my_npra_products_20261120.csv.gz")
    gz_cancelled = _gzip_copy(
        RAW / "pharmaceutical_products_cancelled.csv",
        SOURCES / "my_npra_products_cancelled_20261120.csv.gz")
    licence_md = f"""# 马来西亚 NPRA / QUEST3+ 开放数据快照（2026-11-20）

- 来源：National Pharmaceutical Regulatory Agency (NPRA), Ministry of Health Malaysia
- 数据集：Approved Pharmaceutical Products / Cancelled Pharmaceutical Products（QUEST3+ 行政记录）
- 门户：<{URL_DATASET}> / <{URL_DATASET_CANCELLED}>
- 数据文件：<{URL_CSV}> / <{URL_CSV_CANCELLED}>
- 许可：**CC BY 4.0** <{LICENSE_URL}>
- 抓取日期：2026-11-20；数据截止：2026-11-18（数据集页 Last updated 2026-11-19 03:00，每日更新）
- 条数：已批准 **{meta['approved_rows']:,}**；已注销 **{meta['cancelled_rows']:,}**
- 已批准 CSV sha256：`{meta['files']['products']['sha256']}`
- 已注销 CSV sha256：`{meta['files']['cancelled']['sha256']}`

## 署名口径（页面 / About 必须照写）

Source: National Pharmaceutical Regulatory Agency (NPRA), Malaysia / data.gov.my — CC BY 4.0.
本站对字段做了归一化/派生（剂型、规格、成分映射），不改动来源含义。

> 这是 **CC BY 4.0 开放许可**，直接按许可再发布；不要写成「已获 NPRA 逐项许可」。
> 官方说明：数据为行政记录，不得作为法律行动依据；本站只做身份对应，不给用药建议。
"""
    (SOURCES / "my_npra_products_20261120.license.md").write_text(
        licence_md, encoding="utf-8")
    print(f"  快照：{gz_approved['path']} ({gz_approved['bytes']:,} B)")
    print(f"  快照：{gz_cancelled['path']} ({gz_cancelled['bytes']:,} B)")
    print(f"  许可说明：{SOURCES / 'my_npra_products_20261120.license.md'}")
    return 0


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"找不到快照 {path}；先跑 `python etl/markets/my.py --fetch`")
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _iso_date(value: str) -> str | None:
    s = (value or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return s


def _clean_unit(unit: str) -> str | None:
    u = (unit or "").strip().lower().replace("μ", "µ")
    if not u:
        return None
    return UNIT_MAP.get(u) or UNIT_MAP.get(u.rstrip("s")) or None


def _split_value_unit(text: str) -> tuple[float, str | None] | None:
    """`200mg` / `281.250` / `0.5` → (value, unit_or_None)。"""
    s = (text or "").strip().replace(",", ".")
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([A-Za-zµμ%]+)?$", s)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    return value, _clean_unit(m.group(2) or "")


def parse_strength(content: str) -> dict | None:
    """`[281.250;mg;;0]` / `[200mg;250mg]` / `[0.5;g;5;ml]` → strength dict。

    只取第一个「数量+单位」为 strength；只有明确 `mL/L` 基数时才写 per_volume。
    第二个同单位值（如 `200mg;250mg` 的 250mg）不猜测为包装量，留空。
    """
    raw = (content or "").strip()
    if not raw:
        return None
    fields = [f.strip() for f in raw.split(";")]
    first = _split_value_unit(fields[0]) if fields else None
    if first is None:
        return None
    value, unit = first
    rest = 1
    if unit is None and len(fields) > 1:
        unit = _clean_unit(fields[1])
        rest = 2
    per_v = None
    per_u = None
    if len(fields) >= rest + 2:
        v2 = _split_value_unit(fields[rest])
        u2 = _clean_unit(fields[rest + 1])
        if v2 and u2 in ("mL", "L"):
            per_v, per_u = v2[0], u2
    if per_v is None and rest < len(fields):
        v2 = _split_value_unit(fields[rest])
        if v2 and v2[1] in ("mL", "L"):
            per_v, per_u = v2[0], v2[1]
    return {"value": value, "unit": unit,
            "per_volume_value": per_v, "per_volume_unit": per_u}


def parse_ingredients(text: str) -> list[Ingredient]:
    """`NAME[281.250;mg;;0],NAME2[...]` → Ingredient 列表；不拆名称里的括号。"""
    raw = (text or "").strip()
    if not raw:
        return []
    out: list[Ingredient] = []
    for m in re.finditer(r"([^,\[\]]+)\[([^\]]*)\]", raw):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" ,;")
        if name:
            out.append(Ingredient(raw=name, strength=parse_strength(m.group(2))))
    if out:
        return out
    # 兜底：没有方括号的纯名称
    for part in raw.split(","):
        name = re.sub(r"\s+", " ", part).strip(" ,;")
        if name and "[" not in name:
            out.append(Ingredient(raw=name))
    return out


def derive_form(product: str, generic_name: str) -> tuple[str, str, bool]:
    """商品名 + 通用名 → (dosage_form 文本, form_base, 是否派生)。"""
    text = " ".join(x for x in (product, generic_name) if x)
    base = form_base_of(text)
    if base in ("", "other", "unknown"):
        return "Unknown", "unknown", False
    return FORM_LABEL.get(base, base.title()), base, True


def _product_id(reg_no: str, suffix: str = "") -> str:
    base = re.sub(r"[^A-Za-z0-9-]+", "-", (reg_no or "").strip()).strip("-")
    return f"MY-{base}{suffix}"


def _next_id(base: str, used: set[str]) -> str:
    pid = base
    n = 2
    while pid in used:
        pid = f"{base}-{n}"
        n += 1
    used.add(pid)
    return pid


def _safe_note(bits: list[str]) -> str:
    return " · ".join(b for b in bits if b)[:500]


def _map_variants(db: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for sid, vid, salt in db.execute(
            "SELECT substance_id, variant_id, COALESCE(salt, '') FROM variant"):
        out.setdefault(sid, []).append((vid, salt.lower()))
    return out


def _resolve_variant(variants: dict[str, list[tuple[str, str]]], sid: str,
                     salt: str) -> str | None:
    rows = variants.get(sid) or []
    if not rows:
        return None
    want = (salt or "").lower().strip()
    if want:
        for vid, salt_db in rows:
            if salt_db == want:
                return vid
    return rows[0][0]


def build_plan(db: sqlite3.Connection) -> dict:
    """只读库：把 CSV 变成待写产品计划 + 统计；不写库。"""
    approved = _load_csv(RAW / "pharmaceutical_products.csv")
    cancelled = _load_csv(RAW / "pharmaceutical_products_cancelled.csv")
    mapper = SgMapper(db)
    variants = _map_variants(db)
    used_ids: set[str] = set()
    products: list[ProductPlan] = []
    stats: collections.Counter = collections.Counter()
    unmapped: collections.Counter = collections.Counter()
    descriptions: collections.Counter = collections.Counter()
    statuses: collections.Counter = collections.Counter()
    by_desc: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    for row in approved:
        stats["rows_approved"] += 1
        reg_no = (row.get("reg_no") or "").strip()
        raw_name = (row.get("product") or "").strip()
        nm = normalize(raw_name)
        if not reg_no or not nm.norm:
            stats["rows_rejected"] += 1
            continue
        desc = (row.get("description") or "").strip()
        descriptions[desc] += 1
        dstat = by_desc[desc]
        dstat["products"] += 1
        status = STATUS_MAP.get((row.get("status") or "").strip(), "unknown")
        statuses[status] += 1
        form, form_base, form_ok = derive_form(raw_name, row.get("generic_name") or "")
        if form_ok:
            stats["form_derived"] += 1
            dstat["form_derived"] += 1
        else:
            stats["form_unknown"] += 1
            dstat["form_unknown"] += 1
        release = release_of("", raw_name, row.get("generic_name") or "")
        ingredients = parse_ingredients(row.get("active_ingredient") or "")
        comps: list[dict] = []
        if ingredients:
            stats["ingredient_tokens"] += len(ingredients)
            dstat["tokens"] += len(ingredients)
            resolved: list[tuple[str, dict | None]] = []
            all_ok = True
            for ing in ingredients:
                sid, salt, _method = mapper.map_basic(ing.raw)
                if not sid:
                    stats["substance_unmapped"] += 1
                    dstat["unmapped"] += 1
                    unmapped[ing.raw] += 1
                    all_ok = False
                    continue
                stats["substance_mapped"] += 1
                dstat["mapped"] += 1
                vid = _resolve_variant(variants, sid, salt)
                if not vid:
                    stats["component_no_variant"] += 1
                    dstat["no_variant"] += 1
                    all_ok = False
                    continue
                resolved.append((vid, ing.strength))
            if all_ok and resolved:
                strengths = [s for _, s in resolved if s]
                if len(strengths) == len(resolved):
                    stats["strength_count_matched"] += 1
                elif strengths:
                    stats["strength_count_mismatch"] += 1
                for idx, (vid, strength) in enumerate(resolved):
                    comps.append({"variant_id": vid,
                                  "strength": strength if strength else None})
                stats["products_with_components"] += 1
                dstat["with_components"] += 1
                stats["components"] += len(comps)
                if strengths:
                    stats["products_strength_parsed"] += 1
                    dstat["strength_parsed"] += 1
            else:
                stats["products_components_skipped"] += 1
                dstat["skipped"] += 1
        else:
            stats["products_without_ingredient"] += 1
            dstat["without_ingredient"] += 1
        pid = _next_id(_product_id(reg_no), used_ids)
        note = _safe_note([
            f"MY NPRA/QUEST3+ 注册号={reg_no}",
            f"类别={desc}" if desc else "",
            f"ATC={row.get('mdc_code')}" if row.get("mdc_code") else "",
            f"通用名={row.get('generic_name')}" if row.get("generic_name") else "",
            f"原文成分={row.get('active_ingredient')}" if row.get("active_ingredient") else "",
            f"注册日={row.get('date_reg')}" if row.get("date_reg") else "",
            f"到期日={row.get('date_end')}" if row.get("date_end") else "",
            "行政记录；注册 ≠ 当前在售；剂型由品名派生",
        ])
        products.append(ProductPlan(
            product_id=pid, country="MY", dosage_form=form, form_base=form_base,
            release=release, mah=(row.get("holder") or "").strip() or None,
            approval_id=reg_no, category=desc or None, status=status,
            status_date=None, source_url=URL_DATASET, note=note,
            names=[(raw_name, "trade", 1)], components=comps,
        ))

    for row in cancelled:
        stats["rows_cancelled"] += 1
        reg_no = (row.get("reg_no") or "").strip()
        raw_name = (row.get("product") or "").strip()
        nm = normalize(raw_name)
        if not reg_no or not nm.norm:
            stats["rows_rejected"] += 1
            continue
        desc = (row.get("description") or "").strip()
        descriptions[desc] += 1
        statuses["withdrawn"] += 1
        pid = _next_id(_product_id(reg_no, "-C"), used_ids)
        note = _safe_note([
            f"MY NPRA/QUEST3+ 注册号={reg_no}",
            f"类别={desc}" if desc else "",
            f"注销生效={row.get('date_end')}" if row.get("date_end") else "",
            "已注销注册（Cancelled Pharmaceutical Products 数据集）",
        ])
        products.append(ProductPlan(
            product_id=pid, country="MY", dosage_form="Unknown", form_base="unknown",
            release="none", mah=(row.get("holder") or "").strip() or None,
            approval_id=reg_no, category=desc or None, status="withdrawn",
            status_date=_iso_date(row.get("date_end") or ""),
            source_url=URL_DATASET_CANCELLED, note=note,
            names=[(raw_name, "trade", 1)], components=[],
        ))

    stats["products"] = len(products)
    stats["products_approved"] = sum(1 for p in products if p.status != "withdrawn")
    stats["products_cancelled"] = sum(1 for p in products if p.status == "withdrawn")
    stats["unique_name_keys"] = len({normalize(p.names[0][0]).norm for p in products
                                     if p.names and normalize(p.names[0][0]).norm})
    stats["rows_in"] = stats["rows_approved"] + stats["rows_cancelled"]
    stats["rows_kept"] = len(products)
    return {
        "products": products,
        "stats": dict(stats),
        "unmapped_top": unmapped.most_common(20),
        "descriptions": dict(descriptions),
        "by_description": {k: dict(v) for k, v in by_desc.items()},
        "statuses": dict(statuses),
        "snapshot": {
            "approved_csv": str(RAW / "pharmaceutical_products.csv"),
            "cancelled_csv": str(RAW / "pharmaceutical_products_cancelled.csv"),
            "approved_sha256": sha256_file(RAW / "pharmaceutical_products.csv"),
            "cancelled_sha256": sha256_file(RAW / "pharmaceutical_products_cancelled.csv"),
            "approved_rows": stats["rows_approved"],
            "cancelled_rows": stats["rows_cancelled"],
        },
    }


def write_plan(db: sqlite3.Connection, plan: dict) -> dict:
    written: collections.Counter = collections.Counter()
    for p in plan["products"]:
        written["product"] += common.write_product(db, {
            "product_id": p.product_id, "country": p.country,
            "dosage_form": p.dosage_form, "form_base": p.form_base,
            "release": p.release, "pack": None, "mah": p.mah,
            "approval_id": p.approval_id, "category": p.category,
            "is_branded": 1, "status": p.status, "status_date": p.status_date,
            "source_id": SOURCE_ID, "source_url": p.source_url,
            "retrieved_at": RETRIEVED_AT, "note": p.note,
        })
        for raw, name_type, is_primary in p.names:
            for key, value in common.write_name(
                    db, p.product_id, raw, name_type, is_primary, SOURCE_ID,
                    normalize).items():
                written[key] += value
        for ord_, comp in enumerate(p.components):
            written["product_component"] += common.write_component(
                db, p.product_id, ord_, comp["variant_id"], comp.get("strength"))
    return dict(written)


def _existing_names(db: sqlite3.Connection) -> tuple[set[str], set[tuple[str, str]]]:
    return (
        {r[0] for r in db.execute("SELECT key_id FROM name_key")},
        {(r[0], r[1]) for r in db.execute("SELECT key_id, raw FROM name_variant")},
    )


def _created_names(plan: dict, existing_keys: set[str],
                   existing_pairs: set[tuple[str, str]]) -> tuple[list[str], list[list[str]]]:
    keys: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for p in plan["products"]:
        for raw, _ntype, _primary in p.names:
            nm = normalize(raw)
            if not nm or not nm.norm:
                continue
            if nm.norm not in existing_keys:
                keys.add(nm.norm)
            if (nm.norm, raw) not in existing_pairs:
                pairs.add((nm.norm, raw))
    return sorted(keys), [list(x) for x in sorted(pairs)]


def _summary(plan: dict, db_path: Path, before: dict, after: dict | None = None) -> dict:
    st = plan["stats"]
    return {
        "generated_at": now(),
        "tool": "etl/markets/my.py",
        "source_id": SOURCE_ID,
        "dataset": URL_DATASET,
        "dataset_cancelled": URL_DATASET_CANCELLED,
        "license": LICENSE,
        "db": str(db_path),
        "snapshot": plan["snapshot"],
        "counts": {
            "rows_in": st["rows_in"],
            "products": st["products"],
            "products_approved": st["products_approved"],
            "products_cancelled": st["products_cancelled"],
            "unique_name_keys": st["unique_name_keys"],
            "rows_rejected": st.get("rows_rejected", 0),
        },
        "mapping": {
            "ingredient_tokens": st.get("ingredient_tokens", 0),
            "substance_mapped": st.get("substance_mapped", 0),
            "substance_unmapped": st.get("substance_unmapped", 0),
            "substance_map_rate": round(
                st.get("substance_mapped", 0) / max(1, st.get("ingredient_tokens", 0)), 4),
            "unmapped_top": plan["unmapped_top"],
            "products_with_components": st.get("products_with_components", 0),
            "products_components_skipped": st.get("products_components_skipped", 0),
            "products_without_ingredient": st.get("products_without_ingredient", 0),
            "components": st.get("components", 0),
            "component_no_variant": st.get("component_no_variant", 0),
        },
        "strength": {
            "products_strength_parsed": st.get("products_strength_parsed", 0),
            "products_strength_rate": round(
                st.get("products_strength_parsed", 0) / max(1, st["products"]), 4),
            "count_matched": st.get("strength_count_matched", 0),
            "count_mismatch": st.get("strength_count_mismatch", 0),
        },
        "form": {
            "derived": st.get("form_derived", 0),
            "unknown": st.get("form_unknown", 0),
            "rate": round(st.get("form_derived", 0) / max(1, st["products"]), 4),
        },
        "descriptions": plan["descriptions"],
        "by_description": plan["by_description"],
        "statuses": plan["statuses"],
        "before": before,
        "after": after,
    }


def cmd_dry_run(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    if not db_path.exists():
        raise SystemExit(f"库不存在：{db_path}")
    t0 = time.perf_counter()
    db = common.connect(db_path, write=False)
    try:
        before = common.table_counts(db, "MY", SOURCE_ID)
        plan = build_plan(db)
    finally:
        db.close()
    summary = _summary(plan, db_path, before)
    summary["mode"] = "dry-run（只读库，不写库）"
    summary["elapsed_s"] = round(time.perf_counter() - t0, 1)
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "my_dry_run.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    st = summary["counts"]
    print(f"== MY dry-run（未写库）==")
    print(f"  CSV：已批准 {st['products_approved']:,} + 已注销 {st['products_cancelled']:,}"
          f" → 产品 {st['products']:,}；名称键 {st['unique_name_keys']:,}")
    print(f"  成分映射 {summary['mapping']['substance_mapped']:,}/"
          f"{summary['mapping']['ingredient_tokens']:,} "
          f"({summary['mapping']['substance_map_rate']:.1%})；"
          f"有成分产品 {summary['mapping']['products_with_components']:,}；"
          f"跳过成分 {summary['mapping']['products_components_skipped']:,}")
    print(f"  规格覆盖 {summary['strength']['products_strength_parsed']:,} "
          f"({summary['strength']['products_strength_rate']:.1%})；"
          f"剂型派生 {summary['form']['derived']:,} ({summary['form']['rate']:.1%})")
    print(f"  统计：{out}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    common.guard_real(db_path, REAL_DB, "apply", args.allow_real)
    if not db_path.exists():
        raise SystemExit(f"库不存在：{db_path}（先复制一份副本演练）")
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    t0 = time.perf_counter()
    sha_before = sha256_file(db_path)
    db = common.connect(db_path, write=False)
    try:
        common.require_country(db, "MY")
        before = common.table_counts(db, "MY", SOURCE_ID)
        existing_keys, existing_pairs = _existing_names(db)
        plan = build_plan(db)
    finally:
        db.close()

    db = common.connect(db_path, write=True)
    try:
        db.execute("BEGIN IMMEDIATE")
        source_existed, source_before = common.insert_source(db, SOURCE_ID, SOURCE_META)
        removed = db.execute("DELETE FROM product WHERE country='MY' AND source_id=?",
                             (SOURCE_ID,)).rowcount
        written = write_plan(db, plan)
        common.write_ingest_run(
            db, f"{SOURCE_ID}-{RETRIEVED_AT}", SOURCE_ID, RETRIEVED_AT,
            plan["stats"]["rows_in"], len(plan["products"]),
            {"country": "MY", "layer": "country", "source_id": SOURCE_ID,
             "components": written.get("product_component", 0),
             "approved_rows": plan["stats"]["rows_approved"],
             "cancelled_rows": plan["stats"]["rows_cancelled"],
             "note": "NPRA/QUEST3+ 行政记录；不建新成分；剂型由品名派生"})
        db.commit()
        after = common.table_counts(db, "MY", SOURCE_ID)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    created_keys, created_pairs = _created_names(plan, existing_keys, existing_pairs)
    manifest = {
        "tool": "etl/markets/my.py",
        "db": str(db_path),
        "country": "MY",
        "source_id": SOURCE_ID,
        "run_id": f"{SOURCE_ID}-{RETRIEVED_AT}",
        "created_at": common.now(),
        "data_as_of": DATA_AS_OF,
        "snapshot": plan["snapshot"],
        "db_sha256_before": sha_before,
        "db_sha256_after": sha256_file(db_path),
        "product_ids": [p.product_id for p in plan["products"]],
        "created_name_keys": created_keys,
        "created_name_variants": created_pairs,
        "created_substances": [],
        "source_existed": source_existed,
        "source_before": source_before,
        "counts_before": before,
        "counts_after": after,
        "counts_planned": plan["stats"],
        "written": written,
        "removed_products_before_write": removed,
        "summary": _summary(plan, db_path, before, after),
        "rollback_hint": (
            "python etl/markets/my.py --rollback --allow-real --db <同一个库> "
            "--manifest <本文件>；或从备份恢复 data/drugs.db。"),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print("=== MY（NPRA/QUEST3+）写入完成 ===")
    print(f"  db: {db_path}")
    print(f"  product: {before['product']:,} → {after['product']:,} "
          f"(+{after['product'] - before['product']:,})")
    print(f"  product_name: {before['product_name']:,} → {after['product_name']:,} "
          f"(+{after['product_name'] - before['product_name']:,})")
    print(f"  MY 产品: {before['product_market']:,} → {after['product_market']:,}")
    print(f"  written: {written}")
    print(f"  manifest: {manifest_path}")
    print(f"  elapsed: {time.perf_counter() - t0:.1f}s")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    common.guard_real(db_path, REAL_DB, "rollback", args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单：{manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed, after, diff = common.rollback(db_path, manifest, "MY", SOURCE_ID)
    print(f"回滚完成；删除 {removed}；diff={diff}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="马来西亚 NPRA/QUEST3+ ETL（MY）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fetch", action="store_true", help="下载官方 CSV / 数据集页")
    mode.add_argument("--dry-run", action="store_true", help="只读库，出计划与统计（默认）")
    mode.add_argument("--apply", action="store_true", help="写库（副本默认允许，真实库需 --allow-real）")
    mode.add_argument("--rollback", action="store_true", help="按 manifest 回滚")
    ap.add_argument("--force", action="store_true", help="--fetch 时强制重下")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="库路径")
    ap.add_argument("--allow-real", action="store_true", help="允许写真实库 data/drugs.db")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="撤销清单路径")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.fetch:
        return cmd_fetch(args)
    if args.apply:
        return cmd_apply(args)
    if args.rollback:
        return cmd_rollback(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
