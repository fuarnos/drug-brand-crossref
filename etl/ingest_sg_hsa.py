# -*- coding: utf-8 -*-
"""新加坡 HSA 註冊西藥名冊（data.gov.sg）入庫準備。

數據：`data/raw/sg/hsa_registered_therapeutic_products.json`（舊版 datastore API 全量快照）
  - 5,511 行 / 12 欄：LicenceNo、Productname、Licenseholder、Approvaldate、
    Forensicclassification、ATCCode、Dosageform、RouteofAdministration、Manufacturer、
    Countryofmanufacturer、Activeingredients、Strength。
  - 複方：`Activeingredients` 用 `&&` 連接；也有 `EQV/AS` 註釋、BAN 拼法
    （PARACETAMOL/FRUSEMIDE/LIGNOCAINE/ALUMINIUM…）、無 `&&` 的複方（靠最長匹配切）。
  - `Strength` 用 `&&` 對齊成分（如 `525 mg/1.8 g&&350 mg/1.8 g`）。
  - 無註冊狀態欄位（在冊名單，默認 active）、無包裝、無中文名。

許可：**Singapore Open Data Licence v1.0（SODL）** — 可商用/非商用使用、複製、分發、
改編，須署名 + 鏈許可頁；不得暗示政府背書。署名示例：
  "Contains information from Listing of Registered Therapeutic Products accessed on
   2026-10-28 from Health Sciences Authority (HSA) / data.gov.sg, made available under
   the Singapore Open Data Licence v1.0."

本任務只寫 DB 副本（staging→真實表在副本驗證）；真實庫需 `--allow-real`。
schema 需先由 `db/migrate_country_sg.py` 把 SG 加入 product.country CHECK。

CLI：
    python etl/ingest_sg_hsa.py --dry-run
    python etl/ingest_sg_hsa.py --apply --db .tmp/sg-ingest/test.db
    python etl/ingest_sg_hsa.py --rollback --db .tmp/sg-ingest/test.db
    python etl/ingest_sg_hsa.py --apply --db data/drugs.db --allow-real
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from ingest_openfda_ndc import (  # noqa: E402
    form_base_of, release_of, slug, split_salt)
from normalize_name import normalize  # noqa: E402

DEFAULT_SRC = ROOT / "data" / "raw" / "sg" / "hsa_registered_therapeutic_products.json"
DEFAULT_DB = ROOT / "data" / "drugs.db"
WORK = ROOT / ".tmp" / "sg-ingest"
SOURCE_ID = "hsa_sg"
DATASET_URL = "https://data.gov.sg/datasets/d_767279312753558cbf19d48344577084/view"
LICENSE_URL = "https://data.gov.sg/open-data-licence"
DATA_AS_OF = "2026-08-07"
RETRIEVED_AT = date.today().isoformat()

# 英式/BP 名 → 美式/USAN（DB 以美式 inn_en 為主；僅在目標存在時使用）
BAN_TO_USAN = {
    "paracetamol": "acetaminophen",
    "frusemide": "furosemide",
    "lignocaine": "lidocaine",
    "mesalazine": "mesalamine",
    "guaiphenesin": "guaifenesin",
    "amoxycillin": "amoxicillin",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "isoprenaline": "isoproterenol",
    "pethidine": "meperidine",
    "phenobarbitone": "phenobarbital",
    "amylobarbitone": "amobarbital",
    "quinalbarbitone": "secobarbital",
    "chlorphenamine": "chlorpheniramine",
    "hyoscine": "scopolamine",
    "thyroxine": "levothyroxine",
    "ciclosporin": "cyclosporine",
    "oestradiol": "estradiol",
    "ethinyloestradiol": "ethinylestradiol",
    "norethisterone": "norethindrone",
    "dimethylpolysiloxane": "simethicone",
    "aluminium hydroxide": "aluminum hydroxide",
    "methisoprinol": "inosine pranobex",
    "sulphasalazine": "sulfasalazine",
    "sodium cromoglycate": "cromolyn sodium",
    "beclomethasone": "beclometasone",
}
BRITISH_REPLACEMENTS = (
    ("sulph", "sulf"), ("oest", "est"), ("aem", "em"), ("haem", "hem"),
    ("aluminium", "aluminum"), ("amoxycillin", "amoxicillin"),
    ("lignocaine", "lidocaine"), ("frusemide", "furosemide"),
    ("mesalazine", "mesalamine"), ("guaiphenesin", "guaifenesin"),
    ("paracetamol", "acetaminophen"),
)
SALT_WORDS = {
    "hydrochloride", "hcl", "sodium", "potassium", "calcium", "magnesium",
    "sulfate", "sulphate", "phosphate", "nitrate", "acetate", "bromide",
    "chloride", "iodide", "citrate", "maleate", "fumarate", "succinate",
    "tartrate", "mesylate", "mesilate", "besylate", "besilate", "tosylate",
    "gluconate", "benzoate", "aspartate", "pamoate", "embonate",
    "tromethamine", "meglumine", "xinafoate", "furoate", "propionate",
    "valerate", "palmitate", "decanoate", "enanthate", "cypionate",
    "undecanoate", "estolate", "monohydrate", "dihydrate", "trihydrate",
    "hemihydrate", "hydrate", "anhydrous", "decanedioate",
}
FORM_CATEGORY = {
    "Prescription Only": "POM",
    "Pharmacy Only": "P",
    "General Sale List": "GSL",
}
RE_STRENGTH = re.compile(
    r"^\s*([\d.]+)\s*([%a-zA-Zµμ]+(?:\s*/\s*[a-zA-Z]+)?)"
    r"(?:\s*/\s*([\d.]+)\s*([a-zA-Z]+))?\s*$")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def clean_ingredient_token(raw: str) -> str:
    """去掉 EQV/AS 註釋、括號說明、末尾百分比等，保留鹽型詞彙。"""
    t = (raw or "").strip()
    # 先取 EQV 之前的「標稱成分」（如 "LINCOMYCIN HCl EQV LINCOMYCIN" → LINCOMYCIN HCl）
    t = re.split(r"\s+\bEQV\b\.?|\s+\bEQUIV\b|\s+\bAS\b\s+", t, maxsplit=1, flags=re.I)[0]
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:mg|g|mcg|µg|μg|iu|ml|%)\b.*$", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" .,;")


class SgMapper:
    def __init__(self, db: sqlite3.Connection):
        self.sub_ids = {r[0] for r in db.execute("SELECT substance_id FROM substance")}
        self.inn = {}
        for sid, inn in db.execute("SELECT substance_id, inn_en FROM substance"):
            self.inn.setdefault(norm(inn), sid)
        self.inn_by_sid = {}
        for sid, inn in db.execute("SELECT substance_id, inn_en FROM substance"):
            self.inn_by_sid[sid] = inn
        self.alias = {}
        for alias, anorm, sid in db.execute(
                "SELECT alias, alias_norm, substance_id FROM alias_all "
                "WHERE substance_id IS NOT NULL"):
            if anorm:
                self.alias.setdefault(anorm, sid)

    # -- 候選寫法 -------------------------------------------------------
    def _variants(self, token: str) -> list[str]:
        base = token.lower().replace("-", " ").strip()
        out = [base]
        sq = re.sub(r"\s+", " ", base)
        out.append(sq)
        for a, b in BRITISH_REPLACEMENTS:
            out.append(sq.replace(a, b))
        # 逐詞替換（先做名詞級）
        words = sq.split()
        for i, w in enumerate(words):
            for a, b in BRITISH_REPLACEMENTS:
                if w == a:
                    ww = words[:i] + [b] + words[i + 1:]
                    out.append(" ".join(ww))
        # 去尾部鹽詞（最多 3 層）
        w2 = words[:]
        for _ in range(3):
            if not w2:
                break
            w2 = w2[:-1]
            if w2:
                out.append(" ".join(w2))
        return list(dict.fromkeys(x for x in out if x))

    def map_basic(self, token: str, allow_ban: bool = True) -> tuple[str, str, str]:
        """→ (substance_id, salt, method)；未匹配 ('', '', 'unmapped')。"""
        cleaned = clean_ingredient_token(token)
        if not cleaned:
            return "", "", "empty"
        for cand in self._variants(cleaned):
            sid = slug(cand)
            if sid in self.sub_ids:
                return sid, self._salt_of(cleaned), "slug"
            n = norm(cand)
            if n in self.inn:
                return self.inn[n], self._salt_of(cleaned), "inn"
            if n in self.alias:
                return self.alias[n], self._salt_of(cleaned), "alias"
            if allow_ban and n in BAN_TO_USAN:
                target = BAN_TO_USAN[n]
                if target in self.sub_ids:
                    return target, self._salt_of(cleaned), "ban"
                tn = norm(target)
                if tn in self.inn:
                    return self.inn[tn], self._salt_of(cleaned), "ban-inn"
        # 尾部逐詞去鹽
        words = cleaned.lower().replace("-", " ").split()
        for _ in range(3):
            if len(words) <= 1:
                break
            words = words[:-1]
            cand = " ".join(words)
            sid = slug(cand)
            if sid in self.sub_ids:
                return sid, self._salt_of(cleaned), "salt-strip"
            if norm(cand) in self.inn:
                return self.inn[norm(cand)], self._salt_of(cleaned), "inn-strip"
            if norm(cand) in self.alias:
                return self.alias[norm(cand)], self._salt_of(cleaned), "alias-strip"
        return "", "", "unmapped"

    @staticmethod
    def _salt_of(token: str) -> str:
        cleaned = clean_ingredient_token(token).lower().replace("-", " ")
        words = cleaned.split()
        tail = []
        while words and words[-1] in SALT_WORDS:
            tail.insert(0, words.pop())
        if not words:
            return ""
        return " ".join(tail)

    def split_ingredients(self, text: str) -> list[dict]:
        """活性成分串 → [{raw, sid, salt, method}]；優先按 &&，否則最長匹配切複方。"""
        text = (text or "").strip()
        if not text:
            return []
        parts = [p.strip() for p in text.split("&&") if p.strip()] if "&&" in text \
            else [text]
        out: list[dict] = []
        for part in parts:
            sid, salt, method = self.map_basic(part)
            if sid or len(part.split()) == 1:
                out.append({"raw": clean_ingredient_token(part) or part, "sid": sid,
                            "salt": salt, "method": method})
                continue
            # 無 && 的複方：最長匹配切分
            out.extend(self._segment(part))
        return out

    def _segment(self, text: str) -> list[dict]:
        toks = text.split()
        res: list[dict] = []
        buf: list[str] = []
        i = 0

        def flush():
            if buf:
                raw = " ".join(buf)
                res.append({"raw": raw, "sid": "", "salt": "", "method": "unmapped"})
                buf.clear()

        while i < len(toks):
            found = None
            for n in range(min(6, len(toks) - i), 0, -1):
                cand = " ".join(toks[i:i + n])
                sid, salt, method = self.map_basic(cand)
                if sid:
                    found = (sid, salt, method, cand, n)
                    break
            if found:
                flush()
                sid, salt, method, cand, n = found
                res.append({"raw": cand, "sid": sid, "salt": salt,
                            "method": "combo-" + method})
                i += n
            else:
                buf.append(toks[i])
                i += 1
        flush()
        return res


def parse_strength(s: str):
    """'5% w/v' / '500 mg/5 ml' / '525 mg/1.8 g' → (val, unit, per_v, per_u)。"""
    s = (s or "").strip().replace("µg", "mcg").replace("μg", "mcg")
    m = RE_STRENGTH.match(s)
    if not m:
        return None, None, None, None
    val = float(m.group(1))
    unit = re.sub(r"\s+", " ", m.group(2).lower())
    if unit == "% w/v":
        unit = "%"
    pv = float(m.group(3)) if m.group(3) else None
    pu = m.group(4).lower() if m.group(4) else None
    return val, unit, pv, pu


def load_records(path: Path) -> list[dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    recs = d.get("result", {}).get("records", [])
    if not recs:
        raise SystemExit(f"沒有 records：{path}")
    return recs


def ensure_source(db: sqlite3.Connection) -> None:
    db.execute(
        """INSERT INTO source (source_id, name, url, license, license_url,
                               retrieved_at, notes, data_as_of, data_as_of_note)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source_id) DO UPDATE SET
             name=excluded.name, url=excluded.url, license=excluded.license,
             license_url=excluded.license_url, retrieved_at=excluded.retrieved_at,
             notes=excluded.notes, data_as_of=excluded.data_as_of,
             data_as_of_note=excluded.data_as_of_note""",
        (SOURCE_ID,
         "Health Sciences Authority (HSA) — Listing of Registered Therapeutic Products",
         DATASET_URL,
         "Singapore Open Data Licence v1.0 (SODL): reuse permitted with attribution "
         "and link to licence; no government endorsement implied.",
         LICENSE_URL, RETRIEVED_AT, "Contains information from data.gov.sg / HSA.",
         DATA_AS_OF, "half-yearly (dataset page: updated every 6 months)"))


def build_rows(recs: list[dict], mapper: SgMapper) -> tuple[list[dict], list[dict], list[dict], dict]:
    """→ (products, components, variants, stats)。"""
    products, components, variants = [], [], []
    stats = Counter()
    used_sids: set[str] = set()
    see_variants: dict[str, dict] = {}
    for r in recs:
        licence = (r.get("LicenceNo") or "").strip()
        name = (r.get("Productname") or "").strip()
        if not licence or not name:
            stats["skip_no_key"] += 1
            continue
        form = (r.get("Dosageform") or "").strip()
        route = (r.get("RouteofAdministration") or "").strip()
        cls = (r.get("Forensicclassification") or "").strip()
        ingredients = mapper.split_ingredients(r.get("Activeingredients") or "")
        strengths_raw = [s.strip() for s in (r.get("Strength") or "").split("&&")
                         if s.strip()]
        # 強度對齊：數量相等按序；否則按序取前 min 個；單成分單強度直接配
        strength_by_ord: dict[int, str] = {}
        if strengths_raw:
            if len(ingredients) == len(strengths_raw):
                strength_by_ord = dict(enumerate(strengths_raw))
                stats["strength_aligned"] += 1
            elif len(ingredients) == 1 and len(strengths_raw) >= 1:
                strength_by_ord = {0: strengths_raw[0]}
                stats["strength_single"] += 1
            else:
                strength_by_ord = {i: s for i, s in enumerate(strengths_raw[:len(ingredients)])}
                stats["strength_partial"] += 1
        pid = f"SG-{licence}"
        product = {
            "product_id": pid, "country": "SG", "region": None,
            "dosage_form": form or "UNKNOWN",
            "form_base": form_base_of(form) if form else "unknown",
            "route": route.lower() or None,
            "release": release_of(form),
            "pack": None,
            "mah": (r.get("Licenseholder") or "").strip() or None,
            "approval_id": licence,
            "category": FORM_CATEGORY.get(cls, None),
            "is_branded": 1,
            "status": "active",  # 在冊名單，不等於在售
            "status_date": None,
            "source_id": SOURCE_ID,
            "source_url": DATASET_URL,
            "retrieved_at": RETRIEVED_AT,
            "note": (f"manufacturer={(r.get('Manufacturer') or '').strip()}; "
                     f"country_of_manufacturer={(r.get('Countryofmanufacturer') or '').strip()}; "
                     f"approval_date={(r.get('Approvaldate') or '').strip()}; "
                     f"class={cls}; atc={(r.get('ATCCode') or '').strip()}; "
                     f"source=data.gov.sg/HSA"),
        }
        products.append(product)
        # name_key / name_variant
        nm = normalize(name)
        if not nm.is_empty:
            products[-1]["_name"] = nm
        # components
        n_mapped = 0
        for ord_, ing in enumerate(ingredients):
            sid = ing["sid"]
            stats["components_total"] += 1
            if not sid:
                stats["components_unmapped"] += 1
                stats["unmapped:" + ing["raw"]] += 1
                continue
            n_mapped += 1
            stats["components_mapped"] += 1
            used_sids.add(sid)
            salt = ing["salt"]
            if salt:
                vid = f"{sid}-{slug(salt)}"
                if vid not in see_variants:
                    see_variants[vid] = {"variant_id": vid, "substance_id": sid,
                                         "salt": salt}
            else:
                vid = sid
                # 必須保證 base variant 行存在（部分 substance 只有鹽型 variant）
                if vid not in see_variants:
                    see_variants[vid] = {"variant_id": vid, "substance_id": sid,
                                         "salt": ""}
            val, unit, pv, pu = parse_strength(strength_by_ord.get(ord_, ""))
            if val is not None:
                stats["strength_parsed"] += 1
            components.append({
                "product_id": pid, "ord": ord_, "variant_id": vid,
                "strength_value": val, "strength_unit": unit,
                "per_volume_value": pv, "per_volume_unit": pu})
        if ingredients and n_mapped == len(ingredients):
            stats["products_full_match"] += 1
        if n_mapped:
            stats["products_with_mapped"] += 1
        stats["products"] += 1
        products[-1]["_n_ingredients"] = len(ingredients)
        products[-1]["_n_mapped"] = n_mapped
        if strength_by_ord and any(v for v in strength_by_ord.values()):
            stats["rows_with_any_strength"] += 1
        if (r.get("ATCCode") or "").strip():
            stats["rows_atc"] += 1
        if form:
            stats["rows_form"] += 1
        if (r.get("Licenseholder") or "").strip():
            stats["rows_mah"] += 1
    variants = list(see_variants.values())
    stats["distinct_substances"] = str(len(used_sids))
    return products, components, variants, stats


def _write_preview(products, components, path: Path) -> None:
    import csv
    by_pid: dict[str, list[dict]] = {}
    for c in components:
        by_pid.setdefault(c["product_id"], []).append(c)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["product_id", "product_name", "dosage_form", "form_base", "route",
                    "release", "mah", "category", "components", "strengths"])
        for p in products:
            cs = by_pid.get(p["product_id"], [])
            w.writerow([p["product_id"], p.get("_name").raw if p.get("_name") else "",
                        p["dosage_form"], p["form_base"], p["route"], p["release"],
                        p["mah"], p["category"],
                        " | ".join(c["variant_id"] for c in cs),
                        " | ".join(
                            f"{c['strength_value'] or ''} {c['strength_unit'] or ''}"
                            f"{('/' + str(c['per_volume_value']) + ' ' + (c['per_volume_unit'] or '')) if c['per_volume_value'] else ''}"
                            for c in cs)])


def summarize(products, components, variants, stats: Counter) -> dict:
    n = max(1, stats["products"])
    n_cmp = max(1, stats["components_total"])
    unmapped = Counter()
    for k, v in stats.items():
        if k.startswith("unmapped:"):
            unmapped[k.split(":", 1)[1]] += v
    return {
        "products": stats["products"],
        "components_total": stats["components_total"],
        "components_mapped": stats["components_mapped"],
        "component_rate_pct": round(stats["components_mapped"] / n_cmp * 100, 1),
        "products_full_match": stats["products_full_match"],
        "product_full_match_pct": round(stats["products_full_match"] / n * 100, 1),
        "products_with_mapped": stats["products_with_mapped"],
        "products_with_mapped_pct": round(stats["products_with_mapped"] / n * 100, 1),
        "strength_aligned": stats["strength_aligned"],
        "strength_single": stats["strength_single"],
        "strength_partial": stats["strength_partial"],
        "strength_parsed": stats["strength_parsed"],
        "strength_parsed_pct": round(stats["strength_parsed"] / n_cmp * 100, 1),
        "rows_with_any_strength": stats.get("rows_with_any_strength", 0),
        "rows_with_any_strength_pct": round(
            stats.get("rows_with_any_strength", 0) / n * 100, 1),
        "rows_atc_pct": round(stats.get("rows_atc", 0) / n * 100, 1),
        "rows_form_pct": round(stats.get("rows_form", 0) / n * 100, 1),
        "rows_mah_pct": round(stats.get("rows_mah", 0) / n * 100, 1),
        "distinct_variants": len({c["variant_id"] for c in components}),
        "distinct_substances": int(stats.get("distinct_substances", "0")),
        "unmapped_top": unmapped.most_common(40),
        "unmapped_unique": len(unmapped),
        "skip_no_key": stats.get("skip_no_key", 0),
    }


def _connect(db_path: Path, write: bool) -> sqlite3.Connection:
    if write:
        return sqlite3.connect(db_path, timeout=120)
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)


def _guard_real(db_path: Path, allow_real: bool) -> None:
    if db_path.resolve() == DEFAULT_DB.resolve() and not allow_real:
        raise SystemExit(
            f"拒絕在真實庫 {db_path} 寫入 SG 數據：本任務只允許 DB 副本。\n"
            "確需寫真實庫時加 --allow-real（先備份；並先跑 db/migrate_country_sg.py）。")


def cmd_dry_run(args: argparse.Namespace) -> int:
    recs = load_records(args.src)
    db = _connect(args.db, write=False)
    try:
        mapper = SgMapper(db)
    finally:
        db.close()
    products, components, variants, stats = build_rows(recs, mapper)
    summary = summarize(products, components, variants, stats)
    summary["source"] = str(args.src)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "stats.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    _write_preview(products, components, args.csv)
    print("=== SG HSA dry-run ===")
    print(f"產品 {summary['products']:,}；成分組件 {summary['components_total']:,}"
          f"（映射 {summary['components_mapped']:,} = {summary['component_rate_pct']}%）")
    print(f"全成分匹配產品 {summary['products_full_match']:,} "
          f"= {summary['product_full_match_pct']}%；至少一個映射 "
          f"{summary['products_with_mapped_pct']}%")
    print(f"強度：對齊 {summary['strength_aligned']:,} / 單成分 "
          f"{summary['strength_single']:,} / 部分 {summary['strength_partial']:,}；"
          f"已解析 {summary['strength_parsed_pct']}% 組件")
    print(f"distinct substances {summary['distinct_substances']:,} / variants "
          f"{summary['distinct_variants']:,}")
    print(f"unmapped top {summary['unmapped_unique']} 種："
          f"{[x[0] for x in summary['unmapped_top'][:15]]}")
    print(f"CSV {args.csv}；stats {WORK / 'stats.json'}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    _guard_real(args.db, args.allow_real)
    if not args.db.exists():
        raise SystemExit(f"DB 不存在：{args.db}")
    recs = load_records(args.src)
    db = sqlite3.connect(args.db, timeout=120)
    try:
        # 檢查 country CHECK 是否已含 SG
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name='product'").fetchone()
        if not sql or "'SG'" not in (sql[0] or ""):
            raise SystemExit("product.country CHECK 還沒有 SG：先跑 db/migrate_country_sg.py")
        db.execute("PRAGMA foreign_keys=ON")
        with db:
            ensure_source(db)
            # 冪等：清掉舊 SG 數據（product 級聯 product_name/product_component）
            old_pids = [r[0] for r in db.execute(
                "SELECT product_id FROM product WHERE country='SG'")]
            if old_pids:
                db.executemany("DELETE FROM product WHERE product_id=?",
                               [(p,) for p in old_pids])
            db.execute("DELETE FROM name_variant WHERE source_id=?", (SOURCE_ID,))
            mapper = SgMapper(db)
            products, components, variants, stats = build_rows(recs, mapper)
            db.executemany(
                """INSERT OR IGNORE INTO variant
                   (variant_id, substance_id, salt, hydrate, ester, salt_code,
                    strength_basis, base_fraction, interchange, interchange_note)
                   VALUES (?,?,?,'','','','unknown',1.0,'unknown',NULL)""",
                [(v["variant_id"], v["substance_id"], v["salt"]) for v in variants])
            keys = {}
            for p in products:
                nm = p.get("_name")
                if nm and not nm.is_empty:
                    keys[p["product_id"]] = nm
            db.executemany(
                """INSERT OR IGNORE INTO name_key (key_id, norm, compact, script, lang)
                   VALUES (?,?,?,?,NULL)""",
                [(nm.norm, nm.norm, nm.compact, nm.script) for nm in keys.values()])
            db.executemany(
                """INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)
                   VALUES (?,?,?)""",
                [(nm.norm, nm.raw, SOURCE_ID) for nm in keys.values()])
            # 注意：老庫 product 可能還沒有 region 列（EMA region 遷移前的庫），
            # 按實際列動態組 INSERT，避免對老庫報 "no column named region"。
            prod_cols = [r[1] for r in db.execute("PRAGMA table_info(product)")]
            use_region = "region" in prod_cols
            insert_cols = ["product_id", "country"] + (["region"] if use_region else []) + [
                "dosage_form", "form_base", "route", "release", "pack", "mah",
                "approval_id", "category", "is_branded", "status", "status_date",
                "source_id", "source_url", "retrieved_at", "note"]
            insert_sql = (f"INSERT INTO product ({', '.join(insert_cols)}) VALUES "
                          f"({', '.join('?' * len(insert_cols))})")

            def prod_values(p: dict) -> tuple:
                vals = [p["product_id"], p["country"]]
                if use_region:
                    vals.append(p["region"])
                vals += [p["dosage_form"], p["form_base"], p["route"], p["release"],
                         p["pack"], p["mah"], p["approval_id"], p["category"],
                         p["is_branded"], p["status"], p["status_date"],
                         p["source_id"], p["source_url"], p["retrieved_at"], p["note"]]
                return tuple(vals)

            db.executemany(insert_sql, [prod_values(p) for p in products])
            db.executemany(
                """INSERT INTO product_name (product_id, key_id, name_type, is_primary)
                   VALUES (?,?,'trade',1)""",
                [(pid, nm.norm) for pid, nm in keys.items()])
            db.executemany(
                """INSERT INTO product_component
                   (product_id, ord, variant_id, strength_value, strength_unit,
                    per_volume_value, per_volume_unit)
                   VALUES (?,?,?,?,?,?,?)""",
                [(c["product_id"], c["ord"], c["variant_id"], c["strength_value"],
                  c["strength_unit"], c["per_volume_value"], c["per_volume_unit"])
                 for c in components])
        n_prod = db.execute("SELECT COUNT(*) FROM product WHERE country='SG'").fetchone()[0]
        n_cmp = db.execute("""SELECT COUNT(*) FROM product_component c
                              JOIN product p ON p.product_id=c.product_id
                              WHERE p.country='SG'""").fetchone()[0]
        summary = summarize(products, components, variants, stats)
        summary.update({"db": str(args.db), "applied_at": RETRIEVED_AT,
                        "inserted_products": n_prod, "inserted_components": n_cmp,
                        "created_variants": [v["variant_id"] for v in variants]})
        (WORK / "apply_manifest.json").write_text(
            json.dumps({"db": str(args.db), "source_id": SOURCE_ID,
                        "product_ids": [p["product_id"] for p in products],
                        "created_variants": [v["variant_id"] for v in variants]},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        (WORK / "apply_stats.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"=== SG apply（{args.db}）===")
        print(f"寫入 SG 產品 {n_prod:,} / 成分 {n_cmp:,}；variants {len(variants):,}；"
              f"映射 {summary['component_rate_pct']}%，全匹配產品 "
              f"{summary['product_full_match_pct']}%")
        return 0
    finally:
        db.close()


def cmd_rollback(args: argparse.Namespace) -> int:
    if not args.db.exists():
        raise SystemExit(f"DB 不存在：{args.db}")
    db = sqlite3.connect(args.db, timeout=120)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        with db:
            db.execute("DELETE FROM product WHERE country='SG'")
            db.execute("DELETE FROM name_variant WHERE source_id=?", (SOURCE_ID,))
            man = WORK / "apply_manifest.json"
            created = []
            if man.exists():
                try:
                    created = json.loads(man.read_text(encoding="utf-8")).get(
                        "created_variants", [])
                except Exception:
                    created = []
            if created:
                # 只刪仍未被任何產品引用的 SG 新建 variant
                db.executemany(
                    """DELETE FROM variant WHERE variant_id=?
                       AND variant_id NOT IN (SELECT variant_id FROM product_component)""",
                    [(v,) for v in created])
            db.execute("DELETE FROM source WHERE source_id=?", (SOURCE_ID,))
        print(f"已撤銷 SG：product/name_variant/source 清理完成（{args.db}）")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="新加坡 HSA 註冊西藥名冊入庫準備")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="解析+映射+統計（默認）")
    mode.add_argument("--apply", action="store_true", help="寫 DB（默認限副本）")
    mode.add_argument("--rollback", action="store_true", help="撤銷 SG 數據")
    ap.add_argument("--csv", type=Path, default=WORK / "sg_preview.csv")
    ap.add_argument("--allow-real", action="store_true",
                    help="允許寫 data/drugs.db（需先 migrate_country_sg.py）")
    args = ap.parse_args(argv)
    if not args.src.exists():
        raise SystemExit(f"源文件不存在：{args.src}")
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
