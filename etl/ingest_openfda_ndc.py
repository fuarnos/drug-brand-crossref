"""openFDA NDC 目录 → SQLite（美国数据）。

数据源：https://api.fda.gov/download.json → drug/ndc 分区文件（无需账号，公开数据）。
粒度：openFDA 的「product」= 一个 product_ndc + 若干包装，正好对应我们的 L2 product。

用法：
    python etl/ingest_openfda_ndc.py            # 全量
    python etl/ingest_openfda_ndc.py --limit 1  # 只跑第一个分区，用于验证
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
import zipfile
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import normalize  # noqa: E402
from normalize_salts import insert_variant  # noqa: E402

CACHE = ROOT / "data" / "raw" / "openfda"
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "openfda_ndc"
UA = "drug-brand-crossref/0.2 (public-data research)"
KEEP_TYPES = {"HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG"}

# 盐/水合物后缀：只在前面还有实义词时才拆（sodium chloride 不拆）
SALTS = {
    "hydrochloride", "hcl", "sodium", "potassium", "calcium", "magnesium",
    "besylate", "mesylate", "tosylate", "maleate", "tartrate", "succinate",
    "fumarate", "citrate", "sulfate", "sulphate", "phosphate", "nitrate",
    "acetate", "bromide", "chloride", "iodide", "hydrate", "dihydrate",
    "monohydrate", "trihydrate", "anhydrous", "disodium", "dipropionate",
    "propionate", "valerate", "pamoate", "embonate", "stearate", "palmitate",
    "decanoate", "enanthate", "cypionate", "undecanoate", "benzoate",
    "lactate", "gluconate", "aspartate", "tromethamine", "meglumine",
    "xinafoate", "furoate", "aceponate", "buteprate", "nitrate", "succinate",
    # 溶剂化物 / 水合物：atorvastatin calcium propylene glycol solvate 这类
    "solvate", "hemihydrate", "sesquihydrate", "ethanolate", "methanolate",
    "propylene", "glycol", "calcium", "sodium",
}

RE_STRENGTH = re.compile(
    r"([\d.]+)\s*([a-zA-Z%µμ]+)\s*(?:/\s*([\d.]+)\s*([a-zA-Z]+))?"
)
RE_NONALNUM = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return RE_NONALNUM.sub("-", s.lower()).strip("-") or "unknown"


def split_salt(ingredient: str) -> tuple[str, str]:
    words = ingredient.lower().replace("-", " ").split()
    tail: list[str] = []
    while words and words[-1] in SALTS:
        tail.insert(0, words.pop())
    if not words:
        return ingredient.lower(), ""
    return " ".join(words), " ".join(tail)


def parse_strength(text: str | None):
    if not text:
        return None, None, None, None
    m = RE_STRENGTH.match(text.strip())
    if not m:
        return None, None, None, None
    val = float(m.group(1))
    unit = m.group(2).lower()
    per_v = float(m.group(3)) if m.group(3) else None
    per_u = m.group(4).lower() if m.group(4) else None
    return val, unit, per_v, per_u


# 释放机制（ER 缓控释 / DR 肠溶迟释）。词表与 db/consistency_audit_form.py 的
# RE_ER / RE_DR 同口径：那边是审计的判定真相源，这边是入库与迁移用的可执行版本，
# 新增词两边一起加（迁移脚本会拿审计谓词复核，见 etl/normalize_form_v2.py）。
# 早先只认 extended/sustained/", er"/delayed/", dr"，于是 AU 的
# `Tablet, controlled release`(1,176) 与 `Tablet, enteric coated`(644)、SG 的
# enteric(54) 全被算成 none —— 见 reports/consistency-audit-form-20261110.md R3。
RELEASE_ER_KEYS = (
    "extended release", "extended-release", "sustained release", "sustained-release",
    "prolonged release", "prolonged-release", "controlled release", "controlled-release",
    "modified release", "modified-release", "slow release", "slow-release",
    "long acting", "long-acting", "retard", "chrono", "orops", "ocas", "gits",
    # 西语（CIMA / COFEPRIS 原文；ingest_cima 的 release_of 另有独立词表）
    "liberacion prolongada", "liberacion controlada", "liberacion modificada",
    "prolongada", "prolongado", "retardada", "retardado",
    # 中文（CN 医保库 / TW）
    "缓释", "緩釋", "控释", "控釋", "长效", "長效", "持续释放", "持續釋放",
    "延释", "延釋", "迟释", "遲釋",
)
RELEASE_DR_KEYS = (
    "delayed release", "delayed-release", "enteric", "gastro-resistant",
    "gastro resistant", "gastrorresist", "resistente al jugo", "gastric juice",
    "肠溶", "腸溶",
)
# 短码（`Tablet, ER` / `(CR)` / `XR` …）；与审计的 \b(xr|er|sr|mr|cr)\b 同口径。
RE_RELEASE_CODE = re.compile(
    r"(?:^|[\s,;:()\[\]/.+\-])(er|xr|sr|mr|cr)(?:$|[\s,;:()\[\]/.+\-])")


def release_of(form: str, *texts: str) -> str:
    """剂型（及可选的商品名等文本）→ ER / DR / none。

    ER 优先于 DR：`Tablet, enteric coated, extended release` 这类同时带两族的写法极少
    （现库 0 行），保持旧行为不变。
    """
    blob = " ".join([x or "" for x in (form,) + texts]).lower()
    if not blob.strip():
        return "none"
    if any(k in blob for k in RELEASE_ER_KEYS) or RE_RELEASE_CODE.search(blob):
        return "ER"
    if any(k in blob for k in RELEASE_DR_KEYS):
        return "DR"
    return "none"


# 泡腾：来源原文的 7 种拼写（与 db/consistency_audit_form.py 的 effervescent 族同口径）。
# 繁体 `發泡錠` / `發泡顆粒劑`（TW 28 行）必须在这里认出来，否则 TW 的 `錠`/`顆粒` 先命中。
EFFERVESCENT_KEYS = ("effervesc", "efervesc", "泡腾", "泡騰", "發泡", "发泡", "fizzy")

# 顺序即优先级：越具体越前。`liquid` **必须排最后** —— `injection, solution` 要先命中
# injection、`Powder For Solution` 要先命中 powder，否则剂型被降级成液体
# （reports/consistency-audit-form-20261110.md R1：注射剂误判 15,570、粉剂误判 3,304）。
# 词表里的复数/西语是补 R2 的「回退成原文整串」（2,187 行）：GB 的 VMP 名是
# 「通用名 + 强度 + 剂型(复数)」，`suppositories` / `pessaries` / `plasters` 原先都不命中。
FORM_BASES = (
    ("effervescent", EFFERVESCENT_KEYS),
    ("tablet", ("tablet", "caplet", "lozenge", "troche",
                "comprimid", "tableta", "gragea", "pastilla", "trocisc")),
    ("capsule", ("capsule", "gelcap", "softgel", "perlas", "capsula")),
    ("injection", ("injection", "injectable", "vial", "syringe", "infusion", "intravenous",
                   "ampoule", "ampul", "prefilled", "pre-filled", "parenteral",
                   "inyect", "ampolleta", "intravenosa", "intravesical")),
    ("topical", ("cream", "ointment", "gel", "lotion", "paste", "patch", "shampoo",
                 "foam", "spray", "dressing", "collodion",
                 "nail lacquer", "scalp application",
                 "pomada", "crema", "unguento", "parche", "barniz",
                 "laca", "semisolido", "adhesivo")),
    ("inhalation", ("inhalation", "aerosol", "inhaler", "nebulizer", "inhalador", "nebuliz")),
    ("suppository", ("suppositor", "enema", "pessar", "ovul", "supositori", "uretral")),
    ("powder", ("powder", "granule", "packet", "polvo", "granulado", "sachet", "sobre")),
    ("liquid", ("solution", "suspension", "syrup", "elixir", "liquid", "emulsion",
                "concentrate", "drops", "linctus", "gotas", "jarabe", "liquido",
                "solucion", "irrigant", "irrigacion", "dialisis", "hemofiltracion")),
)

# 来源自己给的「单值剂型名」（不在上面的关键词表里、但本身就是合法 form_base 取值）。
# 与 db/consistency_audit_form.py 的 KNOWN_BASES 同口径；**不在表内的整串原文一律 other**，
# 绝不把原文塞进 form_base（R2 的修法，见 reports/normalization-prep-20261107.md §2.3）。
PLAIN_BASES = frozenset({
    "tablet", "capsule", "liquid", "injection", "topical", "inhalation", "suppository",
    "powder", "effervescent", "pellet", "stick", "kit", "gas", "cloth", "soap", "swab",
    "mouthwash", "globule", "oil", "rinse", "jelly", "lipstick", "nasal", "inhalant",
    "pastille", "salve", "radiofarmaco", "implant", "cord", "tincture", "sponge", "strip",
    "film", "wipe", "pad", "aposito", "plaster", "gum", "device",
    "cream", "ointment", "gel", "patch", "drops", "pessary", "enema", "liquidampoule",
    "pill", "gum, chewing", "soap bar", "tea (herbal)",
})
# 占位值：来源写了「不知道/已取消」这类词，落 unknown 而不是 other
PLACEHOLDER_VALUES = frozenset({
    "", "unknown", "not stated", "n/a", "na", "-", "/", "none", "null", "cancelado",
    "cancelada", "unassigned", "不适用", "未知", "未确认", "其他",
})
RE_TOKEN = re.compile(r"[^a-z]+")


def _fold(text: str) -> str:
    """小写 + 去重音（`suspensión` → `suspension`），中文/繁体原样保留。"""
    s = (text or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _plain_base(f: str) -> str:
    """整串 → 里面出现的「单值剂型名」；没有就返回空串。

    只认整词（`medicated plasters` → plaster，`chlorhexidine … mouthwash` → mouthwash），
    不做子串匹配，避免 `ingelheim`/`antibiotic` 这类误命中。
    """
    if f in PLAIN_BASES:
        return f
    for tok in RE_TOKEN.split(f):
        if not tok:
            continue
        if tok in PLAIN_BASES:
            return tok
        for cut in ("s", "es"):
            if tok.endswith(cut) and tok[:-len(cut)] in PLAIN_BASES:
                return tok[:-len(cut)]
    return ""


def form_base_of(form: str) -> str:
    """来源剂型原文 → form_base（canonical 9 类 / 单值剂型名 / unknown / other）。

    兜底不再是「原样返回原文」：命不中关键词与单值词表的整串原文一律落 `other` 并计入
    迁移报告的计数（R2 的 2,187 行就是这么消掉的）；空值与占位词落 `unknown`。
    """
    f = _fold(form)
    for base, keys in FORM_BASES:
        if any(k in f for k in keys):
            return base
    if f in PLACEHOLDER_VALUES:
        return "unknown"
    return _plain_base(f) or "other"


def download(url: str, dest: Path) -> Path:
    """带缓存下载；若拿到的是 zip（download.open.fda.gov 只发 zip），就地解压成 dest。"""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=300) as resp, tmp.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    if zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as zf:
            inner = zf.namelist()[0]
            with zf.open(inner) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
        tmp.unlink()
    else:
        tmp.replace(dest)
    return dest


def ensure_source(db: sqlite3.Connection, today: str) -> None:
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        (SOURCE_ID, "openFDA NDC Directory",
         "https://open.fda.gov/apis/drug/ndc/", "US Government work (public domain)",
         "https://open.fda.gov/license/", today,
         "品牌名字段为 brand_name；成分与强度取 active_ingredients"),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个分区")
    args = ap.parse_args()

    today = date.today().isoformat()
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    ensure_source(db, today)

    idx_path = download("https://api.fda.gov/download.json", CACHE / "download.json")
    meta = json.loads(idx_path.read_text(encoding="utf-8"))
    parts = meta["results"]["drug"]["ndc"]["partitions"]
    if args.limit:
        parts = parts[: args.limit]
    total_mb = sum(float(p.get("size_mb") or 0) for p in parts)
    print(f"partitions: {len(parts)}  ~{total_mb:.0f} MB")

    seen_products: set[str] = set()
    seen_substances: set[str] = set()
    seen_variants: set[str] = set()
    seen_keys: set[str] = set()
    counts = {"in": 0, "kept": 0, "skip_type": 0, "skip_dup": 0}

    for i, part in enumerate(parts, 1):
        path = download(part["file"], CACHE / f"ndc-{i:02d}.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("results", [])
        print(f"  [{i}/{len(parts)}] {len(rows):>6} records  {path.name}")

        for rec in rows:
            counts["in"] += 1
            if rec.get("product_type") not in KEEP_TYPES:
                counts["skip_type"] += 1
                continue
            pndc = rec.get("product_ndc") or rec.get("product_id")
            if not pndc:
                counts["skip_type"] += 1
                continue
            if pndc in seen_products:
                counts["skip_dup"] += 1
                continue
            ing_list = rec.get("active_ingredients") or []
            # 顺势疗法/植物提取物动辄几十个"成分"，会把碰撞库和检索全污染掉
            if len(ing_list) > 8:
                counts["skip_extract"] = counts.get("skip_extract", 0) + 1
                continue
            seen_products.add(pndc)
            counts["kept"] += 1

            brand = (rec.get("brand_name") or "").strip()
            generic = (rec.get("generic_name") or "").strip()
            form = rec.get("dosage_form") or "unknown"
            form = (", ".join(form) if isinstance(form, list) else str(form)).strip().lower()
            raw_route = rec.get("route")
            if isinstance(raw_route, list):
                route = ",".join(str(x).lower() for x in raw_route) or None
            else:
                route = (raw_route or "").strip().lower() or None
            pack = None
            for p in rec.get("packaging") or []:
                if p.get("description"):
                    pack = p["description"]
                    break
            expiry = rec.get("listing_expiration_date")
            status = "active"
            if expiry and expiry < today:
                status = "discontinued"
            app_no = rec.get("application_number") or ""
            cat = (rec.get("marketing_category") or "")
            note = f"{cat}; {app_no}".strip("; ") or None
            is_branded = int(bool(brand) and brand.lower() != generic.lower())

            db.execute(
                "INSERT OR REPLACE INTO product (product_id, country, dosage_form,"
                " form_base, route, release, pack, mah, approval_id, category,"
                " is_branded, status, status_date, source_id, source_url, retrieved_at,"
                " note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"US-{pndc}", "US", form, form_base_of(form), route, release_of(form),
                 pack, rec.get("labeler_name"), pndc, cat, is_branded, status,
                 expiry if status != "active" else None,
                 SOURCE_ID, f"https://api.fda.gov/drug/ndc.json?search=product_ndc:\"{pndc}\"",
                 today, note),
            )

            for ord_, ing in enumerate(ing_list):
                name = (ing.get("name") or "").strip()
                if not name:
                    continue
                base, salt = split_salt(name)
                sid = slug(base)
                vid = f"{sid}-{slug(salt)}" if salt else sid
                if sid not in seen_substances:
                    seen_substances.add(sid)
                    db.execute(
                        "INSERT OR IGNORE INTO substance (substance_id, inn_en) VALUES (?,?)",
                        (sid, base.title()),
                    )
                if vid not in seen_variants:
                    seen_variants.add(vid)
                    # salt_code 由 normalize_salts 统一分类（老库未迁移时自动退回旧 SQL）
                    insert_variant(db, vid, sid, salt)
                v, u, pv, pu = parse_strength(ing.get("strength"))
                db.execute(
                    "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                    " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (f"US-{pndc}", ord_, vid, v, u, pv, pu),
                )

            for raw_name, ntype, primary in (
                (brand, "trade", 1),
                (generic, "inn", 0),
            ):
                if not raw_name:
                    continue
                n = normalize(raw_name)
                if n.is_empty:
                    continue
                key = n.norm
                if key not in seen_keys:
                    seen_keys.add(key)
                    db.execute(
                        "INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                        " VALUES (?,?,?,?)",
                        (key, key, n.compact, n.script),
                    )
                    db.execute(
                        "INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                        " VALUES (?,?,?)",
                        (key, raw_name, SOURCE_ID),
                    )
                if ntype == "trade" and brand.lower() == generic.lower():
                    ntype_use = "inn"
                else:
                    ntype_use = ntype
                db.execute(
                    "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                    " is_primary) VALUES (?,?,?,?)",
                    (f"US-{pndc}", key, ntype_use, primary),
                )

        db.commit()

    db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{SOURCE_ID}-{today}", SOURCE_ID, today, today, counts["in"], counts["kept"],
         counts["skip_type"] + counts["skip_dup"], "ok", json.dumps(counts)),
    )
    db.commit()

    print("\n== done ==")
    for row in db.execute(
        "SELECT country, n_products, n_variants, n_active, last_synced FROM coverage"
    ):
        print("coverage:", row)
    print("counts:", counts)
    db.close()


if __name__ == "__main__":
    main()
