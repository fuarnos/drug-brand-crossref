"""PBS 官方 API（澳洲）→ SQLite。

数据源：data/raw/pbs/api/{items,organisations,schedule}.json（etl/fetch_pbs.py 抓）。
`/items` 一行 = PBS 编码 × 品牌 × 包装，字段：
    brand_name        商品名（"Xifaxan" / "Sevikar HCT 20/5/12.5"）
    drug_name         通用名（复方用 " + " 连接，套装用 " (&) "）
    schedule_form     剂型+规格+包装（"rifaximin 550 mg tablet, 56"）
    organisation_id   申办方（/organisations 里换名称）
    pbs_code          PBS 编码
    benefit_type_code U/R/A/S（不受限 / 受限 / 授权 / 简化授权）
    non_effective_date 停效日期（有值 = 已撤/将撤）

许可：API 的 `_meta` 明确 "Permission is granted to use and redistribute this
content, as long as all copyright statements are retained."，所以站点必须保留
版权声明（见 source.license 与 About 页）。

用法：python etl/ingest_pbs.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from ingest_openfda_ndc import form_base_of, slug  # noqa: E402
from ingest_dmd import ALIASES  # noqa: E402
from normalize_name import normalize  # noqa: E402

CACHE = ROOT / "data" / "raw" / "pbs" / "api"
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "pbs"
TODAY = date.today().isoformat()

# 澳洲写法独有的几个 BAN → USAN
EXTRA_ALIASES = {
    "ethinyloestradiol": "ethinylestradiol",
    "oestradiol": "estradiol",
    "oestriol": "estriol",
    "pethidine": "meperidine",
    "glibenclamide": "glyburide",
    "colestyramine": "cholestyramine",
    "sodium cromoglycate": "cromolyn sodium",
    "oxpentifylline": "pentoxifylline",
    "sodium valproate": "valproate sodium",
    "sodium fusidate": "fusidate sodium",
}

# --- 强度解析（与网页版同一套规则） -----------------------------------------
_UNIT = r"(mg|milligrams?|mcg|micrograms?|µg|μg|g|grams?|units?|iu|%)"
_PER = r"(ml|millilitres?|milliliters?|l|litres?|liters?|g|actuations?|doses?|units?)"
_NB = r"(?![A-Za-z])"

RE_PACK = re.compile(r",\s*([^,]*\d[^,]*)$")
RE_BRACKET = re.compile(r"\[[^\]]*\]")
RE_PAREN_NUM = re.compile(r"\([^)]*\d[^)]*\)")
RE_THOUSANDS = re.compile(r"(?<=\d)[ \u00a0](?=\d{3}(?!\d))")
RE_IN = re.compile(r"\b1\s+in\s+(\d+)\b", re.I)
RE_RATIO = re.compile(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\s*" + _UNIT + _NB, re.I)
RE_MILLION = re.compile(r"(\d+(?:[.,]\d+)?)\s*million\s*units?" + _NB, re.I)
RE_CONC = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*" + _UNIT + r"\s*/\s*(?:(\d+(?:[.,]\d+)?)\s*)?" + _PER + _NB,
    re.I)
RE_SINGLE = re.compile(r"(\d+(?:[.,]\d+)?)\s*" + _UNIT + _NB, re.I)
RELEASE_WORDS = re.compile(
    r"modified release|extended release|sustained release|prolonged release|"
    r"\b(xr|sr|cr|mr|er|dr)\b", re.I)


def parse_strengths(core: str) -> list[tuple[str, str, str | None, str | None]]:
    s = RE_THOUSANDS.sub("", core)          # "600 000 units" → "600000 units"
    s = RE_BRACKET.sub(" ", s)
    out: list[tuple[str, str, str | None, str | None]] = []

    # "1 in 1000" = 1 mg/mL（w/v），先换算再删掉，否则会被当成普通数字
    def in_dilution(m: re.Match) -> str:
        try:
            val = 1000.0 / float(m.group(1))
        except (ValueError, ZeroDivisionError):
            return " "
        out.append((f"{val:g}", "mg", "1", "ml"))
        return " "

    s = RE_IN.sub(in_dilution, s)
    s = RE_PAREN_NUM.sub(" ", s)

    def ratio(m: re.Match) -> str:
        u = m.group(3).lower()
        out.append((m.group(1).replace(",", "."), u, None, None))
        out.append((m.group(2).replace(",", "."), u, None, None))
        return " "

    def million(m: re.Match) -> str:
        out.append((m.group(1).replace(",", "."), "million units", None, None))
        return " "

    def conc(m: re.Match) -> str:
        out.append((m.group(1).replace(",", "."), m.group(2).lower(),
                    (m.group(3) or "1").replace(",", "."), m.group(4).lower()))
        return " "

    def single(m: re.Match) -> str:
        u = m.group(2).lower()
        u = "unit" if u.startswith("unit") else u
        out.append((m.group(1).replace(",", "."), u, None, None))
        return " "

    s = RE_RATIO.sub(ratio, s)
    s = RE_MILLION.sub(million, s)
    s = RE_CONC.sub(conc, s)
    s = RE_SINGLE.sub(single, s)
    return out


def split_pack(form: str) -> tuple[str, str | None]:
    m = RE_PACK.search(form)
    if not m:
        return form.strip(), None
    return form[:m.start()].strip(), m.group(1).strip()


def strip_synonym(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def canonical_ingredient(name: str) -> str:
    base = re.sub(r"\s+", " ", strip_synonym(name).lower()).strip()
    return EXTRA_ALIASES.get(base) or ALIASES.get(base) or base


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    meta = json.loads((CACHE / "meta.json").read_text(encoding="utf-8"))
    items = json.loads((CACHE / "items.json").read_text(encoding="utf-8"))
    orgs = {o["organisation_id"]: o["name"]
            for o in json.loads((CACHE / "organisations.json").read_text(encoding="utf-8"))}
    schedule_code = meta["schedule_code"]
    print(f"schedule {schedule_code} ({meta['effective_date']})：{len(items)} 行 / "
          f"{len(orgs)} 个申办方")

    db = sqlite3.connect(DB, timeout=60)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.execute("PRAGMA foreign_keys=ON")
    for table in ("product_component", "product_name"):
        db.execute(f"DELETE FROM {table} WHERE product_id IN "
                   f"(SELECT product_id FROM product WHERE country='AU')")
    db.execute("DELETE FROM product WHERE country='AU'")

    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        (SOURCE_ID, "PBS Schedule API v3 (Department of Health)",
         "https://data-api.health.gov.au/pbs/api/v3/",
         meta.get("copyright", "© Commonwealth of Australia"),
         "https://www.health.gov.au/using-our-websites/copyright",
         meta["retrieved_at"],
         f"schedule_code {schedule_code}，生效 {meta['effective_date']}；"
         f"官方公开 API（20 秒/次限速）"))

    seen_sub: set[str] = set()
    seen_var: set[str] = set()
    seen_key: set[str] = set()
    products: set[tuple] = set()
    counts = {"rows": 0, "products": 0, "dups": 0, "skip_no_form": 0,
              "skip_no_brand": 0, "skip_device": 0, "no_strength": 0}
    n = 0

    for it in items:
        n += 1
        if args.limit and n > args.limit:
            break
        counts["rows"] += 1
        # R1 = 造口/失禁用品（敷料、绷带、胶带），不是药，和 dm+d 里滤器械同理
        if it.get("program_code") == "R1":
            counts["skip_device"] += 1
            continue

        form = (it.get("schedule_form") or "").strip()
        brand = (it.get("brand_name") or "").strip()
        drug = (it.get("drug_name") or "").strip()
        if not form:
            counts["skip_no_form"] += 1
            continue
        if not brand or not drug:
            counts["skip_no_brand"] += 1
            continue

        core, pack = split_pack(form)
        comps_raw = [c for c in re.split(r"\+|\(&\)", drug) if strip_synonym(c)]
        comps = [canonical_ingredient(c) for c in comps_raw]
        strengths = parse_strengths(core)
        if not strengths:
            counts["no_strength"] += 1

        form_base = form_base_of(core)
        release = "none"
        if RELEASE_WORDS.search(core):
            release = "DR" if re.search(r"delayed|enteric|gastro", core, re.I) else "ER"
        dosage_form = core[:120]

        bn = normalize(brand).norm
        sig = (bn, tuple(comps), tuple(strengths), form_base, (pack or "").lower())
        if sig in products:
            counts["dups"] += 1
            continue
        products.add(sig)

        code = it["pbs_code"]
        # 同一个 pbs_code + 品牌 可能对应不同包装，id 里带签名短哈希避免主键打架
        pid = (f"AU-{code}-{slug(brand)}-"
               f"{hashlib.md5(json.dumps(sig, ensure_ascii=False).encode()).hexdigest()[:6]}")
        # PBS 允许「没有商品名时用申办方名」，这类不是真正的品牌
        is_branded = 0 if re.search(r"\b(Pty|Ltd|Limited|Inc)\b", brand) else 1
        mah = orgs.get(it.get("organisation_id"))
        status = "active"
        status_date = None
        non_eff = it.get("non_effective_date")
        if non_eff and non_eff <= TODAY:
            status = "discontinued"
            status_date = non_eff
        note_bits = [
            f"PBS {code}",
            {"U": "Unrestricted", "R": "Restricted", "A": "Authority",
             "S": "Authority streamlined"}.get(it.get("benefit_type_code"), ""),
            f"program {it['program_code']}" if it.get("program_code") else "",
            f"max qty {it['maximum_quantity_units']}" if it.get("maximum_quantity_units") else "",
            f"first listed {it['first_listed_date']}" if it.get("first_listed_date") else "",
        ]
        note = " · ".join(x for x in note_bits if x) or None

        db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
            " route, release, pack, mah, approval_id, category, is_branded, status,"
            " status_date, source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "AU", dosage_form, form_base, it.get("moa_preferred_term"), release, pack,
             mah, code, "PBS item", is_branded, status, status_date, SOURCE_ID,
             meta["source_url"], meta["retrieved_at"], note))

        for ord_, ing in enumerate(comps):
            sid = slug(ing)
            vid = sid
            st = strengths[ord_] if ord_ < len(strengths) else (None, None, None, None)
            sval, unit, pv, pu = st
            sval_f = float(sval) if sval not in (None, "") else None
            pv_f = float(pv) if pv not in (None, "") else None
            if sid not in seen_sub:
                seen_sub.add(sid)
                db.execute("INSERT OR IGNORE INTO substance (substance_id, inn_en)"
                           " VALUES (?,?)", (sid, ing.title()))
            if vid not in seen_var:
                seen_var.add(vid)
                db.execute("INSERT OR IGNORE INTO variant (variant_id, substance_id)"
                           " VALUES (?,?)", (vid, sid))
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)",
                (pid, ord_, vid, sval_f, unit, pv_f, pu))

        names = [(drug, "inn", 0)]
        if is_branded:
            names.insert(0, (brand, "trade", 1))
        for raw, ntype, primary in names:
            key = normalize(raw).norm
            if not key:
                continue
            if key not in seen_key:
                seen_key.add(key)
                db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                           " VALUES (?,?,?,?)", (key, key, key.replace(" ", ""), "latin"))
                db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                           " VALUES (?,?,?)", (key, raw, SOURCE_ID))
            db.execute(
                "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                " is_primary) VALUES (?,?,?,?)", (pid, key, ntype, primary))

        counts["products"] += 1
        if counts["products"] % 3000 == 0:
            db.commit()
            print(f"  ... {counts['products']} products", flush=True)

    db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY, counts["rows"],
         counts["products"], counts["dups"], "ok",
         f"schedule {schedule_code}；{counts['skip_no_form']} 行无剂型；"
         f"{counts['no_strength']} 行无强度"))
    db.commit()

    print("\n== done ==")
    for row in db.execute("SELECT * FROM coverage ORDER BY country"):
        print("coverage:", row)
    print("counts:", counts)
    db.close()


if __name__ == "__main__":
    main()
