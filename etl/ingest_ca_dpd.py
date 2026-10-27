"""加拿大：Health Canada DPD → SQLite。

数据源：data/raw/ca/dpd/*.json（etl/fetch_ca_dpd.py 抓的 DPD Open API 全量）。
一行 = 一个 DIN（Drug Identification Number，加拿大的药品识别号），正好对应 L2 product。

字段映射
--------
    drugproduct.brand_name          商品名（"ADVIL LIQUI-GELS"）
    drugproduct.descriptor          剂型/包装补充（"SINGLE-USE VIAL"）
    drugproduct.company_name        公司（≈ 上市许可持有人）
    activeingredient               成分 + 强度；括号里是盐/酯形式（"ATORVASTATIN (ATORVASTATIN CALCIUM)"）
    activeingredient.dosage_value   复方按「每 N 片/每 N mL」给强度时，分母在这里（"4 TAB" / "30 ML"）
    form / route / schedule         剂型 / 给药途径 / 处方类别
    therapeuticclass.tc_atc_number  ATC（4 位）
    status                          Marketed / Approved / Dormant / Cancelled …

数据现实（决定了这个脚本的样子）
--------------------------------
1. **DPD 只有「已批准」这一层**：商品名 + 成分 + 强度 + 剂型 + 状态，没有包装数量和价格。
2. **成分名是加拿大写法**：`ACETYLSALICYLIC ACID`（不是 aspirin）、`PARACETAMOL` 不出现、
   `ADRENALINE`、`GLYCERYL TRINITRATE`、`FRUSEMIDE` 少数旧名，统一映射到其他市场用的 INN。
3. **盐在括号里**：和 openFDA 一样的 U.S. 惯例要反过来做——取括号外的主名做 substance，
   括号里能识别出的盐做 variant.salt，否则单独建成分（`acetylsalicylic-acid` 这个先例已有）。
4. **复方剂量按每 N 片/每 N mL 给**：`strength / dosage_value` 换算成「每片 / 每 mL」，
   否则一盒「每 4 片含 1 g」的配方会显示成 1 g/片。
5. **顺势疗法（SCHEDULE=HOMEOPATHIC）整条排除**：强度是 `CH/DH/X` 稀释度，不是剂量，
   混进来会把「剂量对应」这层彻底搞乱（US 侧同理只收 Human OTC/Rx）。

状态映射
--------
    Marketed            → active
    Approved            → active（已批准、尚未上市；note 里写明）
    Dormant             → discontinued（厂家停售 ≥12 个月）
    Cancelled*          → discontinued
    Authorization by IO*→ withdrawn
    Restricted Access   → active（限院用）

用法：python etl/ingest_ca_dpd.py
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from ingest_openfda_ndc import form_base_of, slug, split_salt  # noqa: E402
from normalize_salts import insert_variant  # noqa: E402
from normalize_name import normalize  # noqa: E402

CACHE = ROOT / "data" / "raw" / "ca" / "dpd"
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "hc_dpd"
TODAY = date.today().isoformat()

# 加拿大的老式英文名 → 美国 USAN（不统一就永远合不到同一张成分卡上）
CA_ALIASES = {
    "acetylsalicylic acid": "aspirin",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "glyceryl trinitrate": "nitroglycerin",
    "frusemide": "furosemide",
    "lignocaine": "lidocaine",
    "chlorphenamine": "chlorpheniramine",
    "suxamethonium": "succinylcholine",
    "methicillin sodium": "methicillin",
    "rifampicin": "rifampin",
    "glibenclamide": "glyburide",
    "phenobarbitone": "phenobarbital",
    "liquorice": "licorice",
    "salbutamol": "albuterol",
    "oestradiol": "estradiol",
    "oestriol": "estriol",
    "ethinyloestradiol": "ethinylestradiol",
    "norethisterone": "norethindrone",
    "cyclosporin": "cyclosporine",
    "mesalazine": "mesalamine",
    "sodium cromoglycate": "cromolyn sodium",
    "sodium valproate": "valproate sodium",
    "colecalciferol": "cholecalciferol",
    "hyoscine butylbromide": "scopolamine butylbromide",
    "hyoscine hydrobromide": "scopolamine hydrobromide",
    "benzylpenicillin": "penicillin g",
    "phenoxymethylpenicillin": "penicillin v",
    "ethyl alcohol": "alcohol",
    "ethanol": "alcohol",
    "mineral oil": "paraffin oil",
    "glycerin": "glycerol",
    "ascorbic acid": "ascorbic acid",
    "diphenhydramine hydrochloride": "diphenhydramine",
    "lactulose": "lactulose",
    "sulphamethoxazole": "sulfamethoxazole",
    "sulphasalazine": "sulfasalazine",
    "aluminium hydroxide": "aluminum hydroxide",
    "aluminium": "aluminum",
    "aluminium chloride": "aluminum chloride",
    "amoxycillin": "amoxicillin",
    "thyroxine": "levothyroxine",
    "levothyroxine sodium": "levothyroxine",
    "sodium fluoride": "fluoride",
    "stannous fluoride": "fluoride",
    "sodium monofluorophosphate": "fluoride",
    "menthol": "menthol",
    "camphor": "camphor",
    "methyl salicylate": "methyl salicylate",
    "dimethicone": "simethicone",
    "activate dimethicone": "simethicone",
    "activated dimethicone": "simethicone",
    "calcium gluconate": "calcium gluconate",
    "colchicine": "colchicine",
    "dexamethasone sodium phosphate": "dexamethasone",
    "dexamethasone phosphate": "dexamethasone",
    "betamethasone sodium phosphate": "betamethasone",
    "betamethasone valerate": "betamethasone",
    "prednisolone sodium phosphate": "prednisolone",
    "methylprednisolone sodium succinate": "methylprednisolone",
    "hydrocortisone acetate": "hydrocortisone",
    "hydrocortisone sodium succinate": "hydrocortisone",
    "insulin human": "insulin human",
    "sodium": "sodium",
}

# 强度单位（DPD 写法）→ 本库口径
UNIT_MAP = {
    "MG": "mg", "G": "g", "MCG": "mcg", "KG": "kg",
    "UNIT": "unit", "IU": "iu", "U": "unit",
    "%": "%", "MG/ML": "mg/ml", "MEQ": "meq", "MMOL": "mmol",
    "MCI": "mci", "MBQ": "mbq", "GBQ": "gbq", "LF": "lf",
    "ML": "ml", "L": "l",
}

# 顺势疗法的强度是稀释度，不是剂量
HOMEOPATHIC_UNITS = {"CH", "DH", "C", "D", "LM", "Q", "X"}

# DPD 里被登记成 ACTIVE_INGREDIENT、实际是辅料/保存剂/溶剂的成分（原件大小写）
PRESERVATIVES_EXCIPIENTS = {
    "HYPROMELLOSE", "BENZYL ALCOHOL", "BENZALKONIUM CHLORIDE", "PROPYLPARABEN",
    "METHYLPARABEN", "PHENOXYETHANOL", "SODIUM METABISULFITE", "SODIUM BISULFITE",
    "WATER FOR INJECTION", "STERILE WATER FOR INJECTION", "BACTERIOSTATIC WATER",
    "STERILE WATER", "PURIFIED WATER", "SODIUM HYDROXIDE", "HYDROCHLORIC ACID",
    "CITRIC ACID MONOHYDRATE", "SODIUM CITRATE", "NITROGEN", "ARGON",
}

# 商品名里的剂型缩写：不剥掉的话「TYLENOL EXTRA STRENGTH CAPLETS」和
# 「TYLENOL EXTRA STRENGTH」会变成两个名字。
# 只收真剂型词 + 紧挨剂型才成立的缩写（AUTO-INJ / SOLN / LIQUI-GELS），
# 不收 er/sr/cr/pen/cap 这类会把「RAPID RELEASE」「EPIPEN JR」切坏的短词。
RE_FORM_TOKENS = re.compile(
    r"\b(tabs?|tablets?|caplets?|capsules?|caps?|gelcaps?|softgels?|"
    r"liq|liquid|liqui-gels?|soln?|solution|susp|suspension|syrup|elixir|drops?|"
    r"cream|crm|ointment|oint|gel|lotion|spray|aerosol|inhalation|inh|"
    r"patch|patches|suppositor(?:y|ies)|supps?|"
    r"inj|injection|auto-inj|auto-injector|sterile|intravenous|intramuscular|"
    r"vial|vials|ampoules?|prefilled|syringe|"
    r"powder|pwd|granules|sachets?|lozenges?|loz|mouthwash|rinse|shampoo|foam|paste|"
    r"emulsion|fct|chewable|chewables|dispersible|effervescent|"
    r"ophthalmic|otic|nasal|rectal|vaginal|topical|oral|"
    r"i\.v\.|i\.m\.|s\.c\.|film|coated|enteric)\b\.?",
    re.I,
)
# 只在做名字键时再剥的弱词：加拿大会有整条名字就是剂型的条目
# （"Sunscreen Spray"、"Antiseptic Rinse"）。显示名保留原文，键里去掉，
# 否则「1% TRICLOSAN FOAMING SKIN CLEANSER」会剩半截。
KEY_NOISE = re.compile(
    r"\b(sunscreen|sunblock|lotion|cream|spray|foam|cleanser|cleanse|rinse|wash|"
    r"swabs?|wipes?|sticks?|stk|top|balm|serum|solution|gel|liquid|drops?|"
    r"treatment|shampoo|conditioner|masks?|ointment)\b\.?",
    re.I,
)
# 「Extra Strength」「Regular Strength」是产品线的一部分，不是剂型词，保留
RE_KEEP_PHRASE = re.compile(r"(extra|regular|maximum|junior|children'?s?)\s+strength", re.I)

RE_DESC_PAREN = re.compile(r"\s*\(([^()]*)\)\s*")
# 名字末尾的规格：'200MG'、'6MG/ML'、'0.005%'、'1000MCG'、'250 IU'
RE_STRENGTH_TAIL = re.compile(
    r"[\s,]*\d+(?:[.,]\d+)?\s*(?:mg|mcg|g|ml|iu|un|units?|%|vl)(?:\s*/\s*(?:\d+(?:[.,]\d+)?\s*)?"
    r"(?:mg|mcg|g|ml|l|iu|units?|%|dose|actuation|vl))*\.?\s*$",
    re.I,
)
RE_STRENGTH_BARE_TAIL = re.compile(r"\s+\d{2,5}\s*$")   # 'ERYTHROCIN LIQUID 125'
RE_MULTI_SPACE = re.compile(r"\s+")


def clean_brand(raw: str) -> tuple[str, str | None, str]:
    """商品名 → (显示名, 括号里的补充说明, 检索键)。

    "TYLENOL EXTRA STRENGTH CAPLETS"      → "TYLENOL EXTRA STRENGTH"
    "APO-AMOXI CAP 500MG"                 → "APO-AMOXI"（规格取自已结构化字段）
    "1% TRICLOSAN SKIN CLEANSER"          → 显示原文，检索键 "1% triclosan skin"
    "SOMNOTOL (PENTOBARBITAL … INJECTION)" → "SOMNOTOL" + 括号内容

    显示名和键分开：DPD 里很多名字整条就是产品描述（防晒剂、洗剂），
    为了能搜到「Sunscreen」这类词，键里再剥一层，但页面上仍显示原样。
    """
    raw = (raw or "").strip()
    extra = None
    m = RE_DESC_PAREN.search(raw)
    if m:
        extra = m.group(1).strip() or None
        raw = (raw[:m.start()] + " " + raw[m.end():]).strip()
    name = RE_KEEP_PHRASE.sub(lambda x: " " + x.group(0).replace(" ", "__") + " ", raw)
    name = RE_FORM_TOKENS.sub(" ", name)
    name = name.replace("__", " ")
    name = RE_STRENGTH_TAIL.sub("", name)
    name = RE_STRENGTH_BARE_TAIL.sub("", name)
    name = RE_MULTI_SPACE.sub(" ", name).strip(" -.,;:/")
    name = re.sub(r"\bfor\s*$", "", name, flags=re.I).strip(" -.,;:/")
    if not name or len(name) < 2:
        # 名字只剩剂型说明（"Sunscreen Spray"）：显示原文，键 = 原键去弱词
        name = RE_MULTI_SPACE.sub(" ", raw).strip(" -.,;:")
        key = KEY_NOISE.sub(" ", name)
        key = RE_MULTI_SPACE.sub(" ", key).strip(" -.,;:/") or name
        return name, extra, key
    key = KEY_NOISE.sub(" ", name)
    key = RE_STRENGTH_TAIL.sub("", key)
    key = RE_MULTI_SPACE.sub(" ", key).strip(" -.,;:/") or name
    return name, extra, key


def strip_salt_paren(name: str) -> tuple[str, str]:
    """'ATORVASTATIN (ATORVASTATIN CALCIUM)' → ('ATORVASTATIN', 'ATORVASTATIN CALCIUM')"""
    name = (name or "").strip()
    m = re.search(r"\(([^)]*)\)", name)
    if not m:
        return name, ""
    return name[:m.start()].strip(), m.group(1).strip()


def canonical_base(name: str) -> tuple[str, str, str, str]:
    """成分名 → (substance_id, 显示名, variant_id, salt)。

    先去掉 DPD 的括号；括号里若是同一主名的盐，做 variant；否则按 openFDA 的
    「末尾盐词」规则拆。
    """
    base, inner = strip_salt_paren(name)
    base = RE_MULTI_SPACE.sub(" ", base).strip(" ,.;")
    inner = RE_MULTI_SPACE.sub(" ", inner).strip(" ,.;")
    low = base.lower()
    low = CA_ALIASES.get(low, low)
    if inner:
        inner_low = inner.lower()
        if inner_low == low:
            salt = ""                      # EPOETIN ALFA (EPOETIN ALFA)：括号只是重复
        elif inner_low.startswith(low):
            salt = inner_low[len(low):].strip()
        else:
            salt = inner_low
        # 括号里是另一个药/载体（大分子结合疫苗的载体蛋白），不当作盐
        if len(salt.split()) > 4 or any(
                w in salt for w in ("toxoid", "protein", "carrier", "complex")):
            salt = ""
    else:
        salt = ""
    sid = slug(low)
    if not salt:
        base_low, salt = split_salt(low)
        if salt and base_low != low:
            sid = slug(base_low)
            return sid, base_low.title(), sid, ""
    vid = f"{sid}-{slug(salt)}" if salt else sid
    return sid, low.title(), vid, salt


RE_NUM = re.compile(r"^\d+(?:\.\d+)?$|^\.\d+$")


def parse_number(text: str) -> float | None:
    """DPD 的数字写法：'500'、'.0114'、'.25'、'1.0'、'2 000'。不是纯数字就返回 None。"""
    s = (text or "").strip().replace("\u00a0", "").replace(" ", "")
    if not RE_NUM.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalise_strength(strength: str, unit: str) -> tuple[float | None, str | None]:
    u = (unit or "").strip().upper()
    val = parse_number(strength)
    if val is None:
        return None, None
    return val, UNIT_MAP.get(u, u.lower() or None)


def release_of(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"extended|sustained|prolonged|modified|controlled|\b(er|sr|xr|mr|cr)\b", t):
        return "ER"
    if re.search(r"delayed|enteric|gastro-?resistant", t):
        return "DR"
    return "none"


def status_of(raw: str, history_date: str | None) -> tuple[str, str | None]:
    s = (raw or "").strip().lower()
    if s == "marketed":
        return "active", None
    if s == "approved":
        return "active", None
    if s == "dormant":
        return "discontinued", history_date
    if s.startswith("cancelled"):
        return "discontinued", history_date
    if s.startswith("authorization by interim order"):
        return "withdrawn", history_date
    if s == "restricted access":
        return "active", None
    return "unknown", None


def load(name: str) -> list[dict]:
    path = CACHE / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"没有 {path.relative_to(ROOT)}，先跑 python etl/fetch_ca_dpd.py")
    rows = json.loads(path.read_text(encoding="utf-8"))
    print(f"  {name:18s} {len(rows):7d}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    meta_path = CACHE / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    retrieved_at = meta.get("retrieved_at", TODAY)

    print("读 DPD 端点：")
    products = load("drugproduct")
    ingredients = load("activeingredient")
    forms = load("form")
    routes = load("route")
    statuses = load("status")
    schedules = load("schedule")
    classes = load("therapeuticclass")
    packages = load("packaging")

    by_code: dict[int, dict] = defaultdict(lambda: {"ing": [], "form": [], "route": [],
                                                    "sched": [], "atc": [], "pack": []})
    for r in ingredients:
        # DPD 把「保存液/渗透压调节」也算成 ACTIVE_INGREDIENT（NAVSTEL 的 HYPROMELLOSE、
        # BACTERIOSTATIC WATER 的苯甲醇…）。不排除的话，角膜保存液会把 4 万个产品
        # 挂到 hypromellose 名下，成分页和同名碰撞全失真。
        nm = (r.get("ingredient_name") or "").strip().upper().split("(")[0].strip()
        if nm in PRESERVATIVES_EXCIPIENTS:
            continue
        by_code[r["drug_code"]]["ing"].append(r)
    for r in forms:
        by_code[r["drug_code"]]["form"].append(r.get("pharmaceutical_form_name") or "")
    for r in routes:
        by_code[r["drug_code"]]["route"].append(r.get("route_of_administration_name") or "")
    for r in schedules:
        by_code[r["drug_code"]]["sched"].append(r.get("schedule_name") or "")
    for r in classes:
        by_code[r["drug_code"]]["atc"].append(r.get("tc_atc_number") or "")
    for r in packages:
        by_code[r["drug_code"]]["pack"].append(r.get("product_information") or "")
    status_by_code = {r["drug_code"]: r for r in statuses}

    db = sqlite3.connect(DB, timeout=60)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    # schema.sql 开了 foreign_keys；这个脚本按 country='CA' 自己先删后插，不依赖级联。
    # 关掉约束是为了能吃下 DPD 里奇特的名字/单位，而不是为了掩盖外键错误。
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("DELETE FROM product_component WHERE product_id IN "
               "(SELECT product_id FROM product WHERE country='CA')")
    db.execute("DELETE FROM product_name WHERE product_id IN "
               "(SELECT product_id FROM product WHERE country='CA')")
    db.execute("DELETE FROM product WHERE country='CA'")

    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, data_as_of, data_as_of_note, notes) VALUES (?,?,?,?,?,?,?,?,?)",
        (SOURCE_ID, "Health Canada Drug Product Database (DPD)",
         "https://health-products.canada.ca/api/drug/drugproduct/?lang=en&type=json",
         "© His Majesty the King in Right of Canada; DPD terms permit non-commercial "
         "re-use with source acknowledgement",
         "https://healthycanadians.gc.ca/important-eng.php#a6",
         TODAY, retrieved_at, "live",
         "DPD Open API 全量（9 个端点）；一行 = 一个 DIN。商品名为加拿大包装上的写法，"
         "顺势疗法（SCHEDULE=HOMEOPATHIC）已排除"))

    seen_sub: set[str] = set()
    seen_var: set[str] = set()
    seen_key: set[str] = set()
    counts: dict[str, int] = defaultdict(int)
    n = 0

    for rec in products:
        n += 1
        if args.limit and n > args.limit:
            break
        counts["rows"] += 1
        code = rec["drug_code"]
        cls = (rec.get("class_name") or "").strip()
        if cls != "Human":
            counts["skip_class"] += 1
            continue
        extra = by_code.get(code, {})
        sched = extra.get("sched") or []
        if any(s.upper() == "HOMEOPATHIC" for s in sched):
            counts["skip_homeopathic"] += 1
            continue

        ing_rows = extra.get("ing") or []
        if not ing_rows:
            counts["skip_no_ingredient"] += 1
            continue
        if len(ing_rows) > 8:                  # 维生素/矿物质复合片：几十种"成分"，不成产品身份
            counts["skip_extract"] += 1
            continue

        raw_brand = (rec.get("brand_name") or "").strip()
        if not raw_brand:
            counts["skip_no_brand"] += 1
            continue
        brand, brand_extra, brand_key = clean_brand(raw_brand)
        descriptor = (rec.get("descriptor") or "").strip()
        form_names = [f for f in (extra.get("form") or []) if f]
        dosage_form = "; ".join(dict.fromkeys(form_names)) or descriptor or "unknown"
        text_for_release = " ".join([dosage_form, descriptor, raw_brand, brand_extra or ""])
        form_base = form_base_of(dosage_form if form_names else
                                 (descriptor or brand_extra or raw_brand))

        comps: list[tuple] = []
        for r in ing_rows:
            sval, sunit = normalise_strength(r.get("strength") or "",
                                             r.get("strength_unit") or "")
            if (r.get("strength_unit") or "").upper() in HOMEOPATHIC_UNITS:
                sval, sunit = None, None      # 稀释度不当作剂量
            pv = pu = None
            dval = parse_number(r.get("dosage_value") or "")
            dunit = (r.get("dosage_unit") or "").strip().upper()
            if dval and dval > 1 and sval is not None and sunit:
                # "每 4 片含 1 g" → 每片 250 mg；"每 30 mL 含 355 mg" → 每 mL 355/30 mg
                sval = sval / dval
                if dunit in ("ML", "L"):
                    pv, pu = 1.0, dunit.lower()
                elif dunit in ("TAB", "CAP"):
                    pv, pu = 1.0, "unit"
                if sval >= 1000 and sunit == "mg":
                    sval, sunit = sval / 1000, "g"
            elif dval and dval > 1 and sval is not None:
                sval = sval / dval
            rid, disp, vid, salt = canonical_base(r.get("ingredient_name") or "")
            # 别的市场可能已经有同名 variant（例如 levothyroxine 在 GB 是
            # 'levothyroxine' + salt='sodium'）。以库里既有的为准，否则外键会指向不存在的成分。
            if vid not in seen_var:
                row = db.execute("SELECT substance_id FROM variant WHERE variant_id=?",
                                 (vid,)).fetchone()
                if row:
                    seen_var.add(vid)
                    rid = row[0]
                    disp = None
            if vid not in seen_var:
                seen_var.add(vid)
                # substance 可能已存在但被 INSERT OR IGNORE 挡掉（UNIQUE inn_en：
                # 墨西哥的 mx-es-asunaprevir 已经叫 Asunaprevir），所以用「库里实际
                # 落地的 substance_id」去插 variant，否则外键会指向不存在的成分。
                db.execute("INSERT OR IGNORE INTO substance (substance_id, inn_en) VALUES (?,?)",
                           (rid, disp or rid.replace("-", " ").title()))
                row = db.execute("SELECT substance_id FROM substance WHERE substance_id=?",
                                 (rid,)).fetchone()
                if not row:
                    row = db.execute("SELECT substance_id FROM substance WHERE inn_en=?",
                                     ((disp or rid.replace("-", " ").title()),)).fetchone()
                if row and row[0] != rid:
                    rid = row[0]
                # salt_code 由 normalize_salts 统一分类（老库未迁移时自动退回旧 SQL）
                insert_variant(db, vid, rid, salt or "")
                row = db.execute("SELECT substance_id FROM variant WHERE variant_id=?",
                                 (vid,)).fetchone()
                if row:
                    rid = row[0]
            comps.append((vid, sval, sunit, pv, pu))

        if not comps:
            counts["skip_no_component"] += 1
            continue

        st = status_by_code.get(code, {})
        status, status_date = status_of(st.get("status") or "", st.get("history_date"))
        if status == "unknown":
            counts["status_unknown"] += 1

        din = (rec.get("drug_identification_number") or "").strip()
        pid = f"CA-{din or code}"
        route = ", ".join(dict.fromkeys(r.lower() for r in (extra.get("route") or []) if r)) or None
        pack = next((p for p in (extra.get("pack") or []) if p), None)
        atc = next((a for a in (extra.get("atc") or []) if a), None)
        cat = "; ".join(dict.fromkeys(s for s in sched if s)) or None
        note_bits = [st.get("status") or "", f"ATC {atc}" if atc else "",
                     "original market " + st["original_market_date"]
                     if st.get("original_market_date") else "",
                     brand_extra or ""]
        note = " · ".join(x for x in note_bits if x) or None
        is_branded = int(bool(brand))
        first = comps[0]

        db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
            " route, release, pack, mah, approval_id, category, is_branded, status,"
            " status_date, source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "CA", dosage_form[:120], form_base, route, release_of(text_for_release),
             pack, (rec.get("company_name") or "").strip() or None, din or None, cat,
             is_branded, status, status_date, SOURCE_ID,
             f"https://health-products.canada.ca/dpd-bdpp/info?lang=eng&code={code}",
             retrieved_at, note))
        for ord_, (vid, sval, sunit, pv, pu) in enumerate(comps):
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)", (pid, ord_, vid, sval, sunit, pv, pu))

        nm = normalize(brand)
        key = normalize(brand_key).norm or nm.norm
        if key:
            if key not in seen_key:
                seen_key.add(key)
                db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                           " VALUES (?,?,?,?)", (key, key, key.replace(" ", ""), "latin"))
                db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                           " VALUES (?,?,?)", (key, brand, SOURCE_ID))
            db.execute(
                "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type, is_primary)"
                " VALUES (?,?,?,?)", (pid, key, "trade", 1))
        # 原料药级的 ATC / 强度记在 substance 上，其他市场补 ATC 时能用
        if atc:
            db.execute("UPDATE substance SET atc = COALESCE(atc, ?) "
                       "WHERE substance_id = (SELECT v.substance_id FROM variant v "
                       "WHERE v.variant_id = ?)", (atc, first[0]))

        counts["kept"] += 1
        if counts["kept"] % 10000 == 0:
            db.commit()
            print(f"  ... {counts['kept']} products", flush=True)

    db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY, counts["rows"], counts["kept"],
         counts["rows"] - counts["kept"], "ok", json.dumps(counts, ensure_ascii=False)))
    db.commit()

    print("\n== done ==")
    for row in db.execute("SELECT * FROM coverage ORDER BY country"):
        print("coverage:", row)
    print("counts:", dict(counts))
    db.close()


if __name__ == "__main__":
    main()
