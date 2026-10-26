"""dm+d（英国）→ SQLite。

数据源：NHS TRUD 的 NHSBSA dm+d Release（XML v2.3）。许可 OGL，需署名。
结构：
    f_vmp2_*.xml  VMP   = 通用名级产品（"Atorvastatin 20mg tablets"）
    f_amp2_*.xml  AMP   = 实际产品（"Lipitor 20mg tablets"）——商品名在这里
    f_lookup2_*.xml     供应商代码 → 名称

dm+d 的强度不单独成字段，写在名字里（"Zocor 10mg tablets"），
正好复用我们的归一化器切分。

用法：python etl/ingest_dmd.py
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import zipfile
from datetime import date
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from ingest_openfda_ndc import form_base_of  # noqa: E402
from normalize_name import normalize  # noqa: E402

CACHE = ROOT / "data" / "raw" / "dmd"
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "dmd"
TODAY = date.today().isoformat()

# 英国 BAN ↔ 美国 USAN：不统一就永远合不到同一张身份卡上
ALIASES = {
    "paracetamol": "acetaminophen",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "salbutamol": "albuterol",
    "isoprenaline": "isoproterenol",
    "frusemide": "furosemide",
    "lignocaine": "lidocaine",
    "glyceryl trinitrate": "nitroglycerin",
    "chlorphenamine": "chlorpheniramine",
    "colecalciferol": "cholecalciferol",
    "oestradiol": "estradiol",
    "oestriol": "estriol",
    "norethisterone": "norethindrone",
    "ciclosporin": "cyclosporine",
    "mesalazine": "mesalamine",
    "rifampicin": "rifampin",
    "suxamethonium": "succinylcholine",
    "hyoscine butylbromide": "scopolamine butylbromide",
    "hyoscine hydrobromide": "scopolamine hydrobromide",
    "benzylpenicillin": "penicillin g",
    "phenoxymethylpenicillin": "penicillin v",
    "levothyroxine sodium": "levothyroxine",
    "thyroxine": "levothyroxine",
    "ethinylestradiol": "ethinyl estradiol",
    "amoxycillin": "amoxicillin",
    "sulphamethoxazole": "sulfamethoxazole",
    "sulphasalazine": "sulfasalazine",
    "aluminium hydroxide": "aluminum hydroxide",
}


# dm+d 的这个条目包含大量「器械/耗材」（造口袋、弹力袜、敷料、支具）。
# 它们几乎都不带剂量，用"名字里有没有剂量"这一条就能滤掉绝大部分。
RE_STRENGTH = re.compile(
    r"\d\s*(?:mg|mcg|microgram|gram|g\b|ml|litre|liter|units?|iu|%|mmol|meq)",
    re.IGNORECASE,
)


def slug(text: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


def iter_records(path: Path, tag: str):
    for _, elem in etree.iterparse(str(path), events=("end",), tag=tag, huge_tree=True,
                                   recover=True):
        yield elem
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]


def text(elem, tag: str) -> str:
    node = elem.find(tag)
    return (node.text or "").strip() if node is not None else ""


def load_suppliers(path: Path) -> dict[str, str]:
    tree = etree.parse(str(path), etree.XMLParser(huge_tree=True, recover=True))
    root = tree.getroot()
    out: dict[str, str] = {}
    for section in root:
        tag = section.tag
        if not isinstance(tag, str) or "SUPPL" not in tag:
            continue
        for info in section:
            cd, desc = info.find("CD"), info.find("DESC")
            if cd is not None and desc is not None and cd.text:
                out[cd.text.strip()] = (desc.text or "").strip()
    return out


def find_latest(pattern: str) -> Path:
    files = sorted(CACHE.glob(pattern))
    if not files:
        raise SystemExit(f"没找到 {pattern}，先跑 python etl/trud_fetch.py")
    return files[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    zip_path = find_latest("nhsbsa_dmd_*.zip")
    extract_dir = CACHE / "extracted"
    if not (extract_dir / "f_amp2_3151026.xml").exists() and not list(
            extract_dir.glob("f_amp2_*.xml")):
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
    amp_file = next(extract_dir.glob("f_amp2_*.xml"))
    vmp_file = next(extract_dir.glob("f_vmp2_*.xml"))
    vtm_file = next(extract_dir.glob("f_vtm2_*.xml"))
    lookup_file = next(extract_dir.glob("f_lookup2_*.xml"))
    print(f"release: {zip_path.name}")

    suppliers = load_suppliers(lookup_file)
    print(f"suppliers: {len(suppliers)}")

    # VTM 是干净的通用名（"Paracetamol"、"Acebutolol + Hydrochlorothiazide"），
    # 比从 VMP 名字里剥剂型词可靠得多。
    vtms: dict[str, str] = {}
    for el in iter_records(vtm_file, "VTM"):
        vid = text(el, "VTMID")
        if vid:
            vtms[vid] = text(el, "NM")
    print(f"VTMs: {len(vtms)}")

    vmps: dict[str, dict] = {}
    for el in iter_records(vmp_file, "VMP"):
        vpid = text(el, "VPID")
        if vpid:
            vmps[vpid] = {"nm": text(el, "NM"), "vtm": text(el, "VTMID")}
    print(f"VMPs: {len(vmps)}")

    db = sqlite3.connect(DB)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        (SOURCE_ID, "NHSBSA dm+d", "https://isd.digital.nhs.uk/trud/users/guest/filters/0/categories/6",
         "Open Government Licence v3.0", "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
         TODAY, f"release {zip_path.stem}；含 SNOMED CT 码，SNOMED 另有许可"),
    )

    seen_sub: set[str] = set()
    seen_var: set[str] = set()
    seen_key: set[str] = set()
    counts = {"amp": 0, "kept": 0, "skip": 0, "branded": 0}

    for el in iter_records(amp_file, "AMP"):
        counts["amp"] += 1
        if args.limit and counts["amp"] > args.limit:
            break
        apid = text(el, "APID")
        vpid = text(el, "VPID")
        nm = text(el, "NM")
        desc = text(el, "DESC")
        supp = text(el, "SUPPCD")
        vmp = vmps.get(vpid)
        if not (apid and vmp and nm):
            counts["skip"] += 1
            continue
        if not RE_STRENGTH.search(vmp["nm"]):
            counts["skip_device"] = counts.get("skip_device", 0) + 1
            continue
        counts["kept"] += 1

        brand_n = normalize(nm)
        gen_n = normalize(vmp["nm"])
        is_branded = int(bool(brand_n.norm) and brand_n.norm != gen_n.norm)
        counts["branded"] += is_branded

        release = "ER" if re.search(r"prolonged|modified|sustained|slow", vmp["nm"], re.I) else (
            "DR" if re.search(r"gastro-resistant|enteric|delayed", vmp["nm"], re.I) else "none")
        form_base = form_base_of(vmp["nm"])
        pid = f"GB-{apid}"

        db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
            " route, release, pack, mah, approval_id, category, is_branded, status,"
            " source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "GB", vmp["nm"][:120], form_base, None, release, None,
             suppliers.get(supp, supp or None), apid, "dm+d", is_branded, "active",
             SOURCE_ID, "https://isd.digital.nhs.uk/trud/users/guest/filters/0/categories/6",
             TODAY, desc or None),
        )

        # 成分取 VTM（干净通用名）；拿不到才退回从名字里剥词
        vtm_name = vtms.get(vmp.get("vtm", ""), "")
        if vtm_name:
            ingredients = [x.strip() for x in vtm_name.split(" + ") if x.strip()]
        else:
            parts = [p for p in re.split(r"\s+/\s+", vmp["nm"])
                     if re.match(r"[A-Za-z]{3,}", p.strip())] or [vmp["nm"]]
            ingredients = []
            for p in parts:
                pn_ = normalize(p)
                if pn_.norm:
                    ingredients.append(pn_.norm)

        strengths = normalize(vmp["nm"]).strengths
        for ord_, ing in enumerate(ingredients):
            base = ing.lower().strip()
            canonical = ALIASES.get(base, base)
            sid = slug(canonical)
            strength = strengths[ord_] if ord_ < len(strengths) else (None, None)
            vid = sid
            if sid not in seen_sub:
                seen_sub.add(sid)
                db.execute("INSERT OR IGNORE INTO substance (substance_id, inn_en) VALUES (?,?)",
                           (sid, canonical.title()))
            if vid not in seen_var:
                seen_var.add(vid)
                db.execute("INSERT OR IGNORE INTO variant (variant_id, substance_id) VALUES (?,?)",
                           (vid, sid))
            # 浓度写法 "250mg/5ml" 归一化后是 ("250/5", "mg/ml")，要拆成数值 + 每容积
            sval = pv = None
            unit = strength[1]
            raw_val = strength[0] or ""
            if "/" in raw_val:
                num, _, den = raw_val.partition("/")
                try:
                    sval, pv = float(num), float(den)
                except ValueError:
                    sval = pv = None
            else:
                try:
                    sval = float(raw_val) if raw_val else None
                except ValueError:
                    sval = None
            per_unit = unit.split("/")[1] if unit and "/" in unit else None
            unit = unit.split("/")[0] if unit else None
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)",
                (pid, ord_, vid, sval, unit, pv, per_unit))

        for raw, ntype, primary in ((nm, "trade", 1), (vmp["nm"], "inn", 0)):
            n = normalize(raw)
            if n.is_empty:
                continue
            if ntype == "trade" and not is_branded:
                ntype = "inn"
            if n.norm not in seen_key:
                seen_key.add(n.norm)
                db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                           " VALUES (?,?,?,?)", (n.norm, n.norm, n.compact, n.script))
                db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                           " VALUES (?,?,?)", (n.norm, raw, SOURCE_ID))
            db.execute(
                "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type, is_primary)"
                " VALUES (?,?,?,?)", (pid, n.norm, ntype, primary))

        if counts["kept"] % 20000 == 0:
            db.commit()
            print(f"  ... {counts['kept']} products")

    db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY,
         counts["amp"], counts["kept"], counts["skip"], "ok", f"{counts['branded']} branded"))
    db.commit()

    print("\n== done ==")
    for row in db.execute("SELECT * FROM coverage"):
        print("coverage:", row)
    print("counts:", counts)
    db.close()


if __name__ == "__main__":
    main()
