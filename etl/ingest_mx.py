# -*- coding: utf-8 -*-
"""COFEPRIS（墨西哥）→ SQLite。

三份输入：
  data/raw/mx/cofepris_alopaticos.csv   26 个 PDF 抽出的 9,8xx 个注册（2001–2026）
  data/raw/mx/cofepris_status.csv       revocados / cancelados 清单（给主表打状态）
  data/raw/mx/issste_catalogo.csv       公共采购目录（通用名 + 剂型 + 浓度）
  data/raw/mx/profeco_medicamentos.csv  零售价格调查（商品名 + 包装含浓度）

关键取舍
--------
1. COFEPRIS 清单**没有浓度列**。所以规格要么来自 ISSSTE（通用名级，唯一值才敢填），
   要么来自 PROFECO（商品名级，同名同剂型唯一值才敢填），两条都填不上就留空。
   任何一条填上了，都在 product.note 里写明来源，不假装是监管原始字段。
2. 英文 INN 靠 etl/build_mx_inn_map.py 的映射；映射不上的建成「只在墨西哥出现」的
   substance（inn_en 用西语名），保证引用完整性，也不谎称跨国对上。
3. product_id = MX-<registro>，registration 本身是墨西哥的产品身份。

用法：
    python etl/ingest_mx.py
    python etl/ingest_mx.py --limit 200      # 先小样本试跑
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import normalize  # noqa: E402

RAW = ROOT / "data" / "raw" / "mx"
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
INN_MAP = ROOT / "data" / "mx_inn_map.json"
MANIFEST = RAW / "manifest.json"
SOURCE_ID = "cofepris_mx"
TODAY = date.today().isoformat()

RE_NONALNUM = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return RE_NONALNUM.sub("-", s.lower()).strip("-") or "unknown"


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def key(s: str) -> str:
    s = strip_acc(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# --- 剂型：西语 → form_base ------------------------------------------------
FORM_BASES = (
    ("tablet", ("tableta", "comprimido", "gragea", "caplet", "pastilla")),
    ("capsule", ("capsula", "cap ") ),
    ("injection", ("inyectable", "inyeccion", "ampolleta", "infusion", "intravenosa",
                   "solucion inyectable", "concentrado para solucion")),
    ("topical", ("crema", "unguento", "pomada", "gel", "locion", "parche", "shampoo",
                 "espuma", "pasta", "pomad")),
    ("inhalation", ("inhalador", "aerosol", "inhalacion", "nebuliz", "gas medicinal")),
    ("suppository", ("supositorio", "ovulo", "enema")),
    ("powder", ("polvo", "granulado", "sobre", "sachet")),
    ("liquid", ("solucion", "suspension", "jarabe", "elixir", "emulsion", "gotas",
                "liquido", "jalea", "concentrado")),
)


def form_base_es(form: str) -> str:
    f = strip_acc(form or "").lower()
    for base, keys in FORM_BASES:
        if any(k in f for k in keys):
            return base
    return f or "unknown"


# 固体制剂：放宽浓度匹配时只对这几类生效（mg 与 mg/ml 不可比）
SOLID_BASES = {"tablet", "capsule", "powder"}


def release_es(form: str) -> str:
    f = strip_acc(form or "").lower()
    if "liberacion prolongada" in f or "liberacion modificada" in f or "retard" in f \
            or re.search(r"\blp\b|\bmr\b|\ber\b", f):
        return "ER"
    return "none"


def route_es(form: str, base: str) -> str | None:
    f = strip_acc(form or "").lower()
    if "oftalm" in f or "colirio" in f:
        return "ophthalmic"
    if "oido" in f or "otico" in f:
        return "otic"
    if "nasal" in f:
        return "nasal"
    if "rectal" in f or "supositorio" in f:
        return "rectal"
    if "vaginal" in f or "ovulo" in f:
        return "vaginal"
    if "inhal" in f or "aerosol" in f:
        return "inhalation"
    if "topico" in f or base == "topical":
        return "topical"
    if base in ("injection",):
        return "injection"
    if base in ("tablet", "capsule", "liquid", "powder"):
        return "oral"
    return None


RE_STRENGTH = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg|mcg|g|kg|ml|l|ui|iu|%)\b", re.I)
UNIT_FIX = {"ui": "iu", "iu": "iu", "l": "ml"}

# 西语月份缩写 → 数字。COFEPRIS 的有效期写法是 "02-ene-2028"。
ES_MONTHS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
             "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}
_RE_VIG = re.compile(r"(\d{1,2})\s*[-/]\s*([a-záéíóú]{3,4})\s*[-/]\s*(\d{2,4})", re.I)
_RE_VIG_NUM = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def parse_vigencia(text: str) -> date | None:
    """有效期 → date。解析不了就返回 None，绝不猜。"""
    t = (text or "").strip().lower()
    if not t:
        return None
    m = _RE_VIG.search(t)
    if m:
        mon = ES_MONTHS.get(strip_acc(m.group(2)).lower())
        if mon:
            year = int(m.group(3))
            if year < 100:                     # "11-jun-18" → 2018
                year += 2000
            try:
                return date(year, mon, int(m.group(1)))
            except ValueError:
                return None
    m = _RE_VIG_NUM.search(t)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None

# 文本兜底解析（2011–2013）会把「Estatus」列的值或表格序号漏进商品名，
# 这些不是品牌，直接清空，产品本体仍然保留（is_branded=0）。
JUNK_NAMES = {
    "cancelado", "revocado", "aprobado", "vigente", "suspendido", "negado", "vencido",
    "n a", "na", "n/a", "s n", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "no se otorgo", "sin nombre", "sin denominacion",
}


def clean_brand(brand: str) -> str:
    b = " ".join((brand or "").split()).strip(" .-*")
    if not b or key(b) in JUNK_NAMES or b.isdigit() or len(b) < 2:
        return ""
    return b


def clean_generic(generic: str) -> str:
    g = " ".join((generic or "").split()).strip(" .-*")
    if key(g) in JUNK_NAMES or len(g) < 3:
        return ""
    # 页脚/表头/状态列漏进来的整句
    if re.search(r"informaci[oó]n contenida|car[aá]cter informativo|este documento|no legal|"
                 r"s\.a\. de c\.v|contenido de esta", g, re.I):
        return ""
    # 罗马数字（分类列）、日期（有效期列）被当成成分
    if re.fullmatch(r"(i{1,3}|iv|v|vi|vii|viii|ix|x)", g, re.I):
        return ""
    if re.fullmatch(r"\d{1,2}[-/][a-záéíóú]{3}[-/]\d{4}", g, re.I):
        return ""
    return g


def parse_strength(text: str) -> tuple[float, str] | None:
    m = RE_STRENGTH.search(text or "")
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    unit = m.group(2).lower()
    unit = UNIT_FIX.get(unit, unit)
    return val, unit


# --- 库存目录 --------------------------------------------------------------
def load_issste() -> dict[tuple[str, str], set[tuple[float, str]]]:
    """(通用名归一, form_base) → {(浓度, 单位)}"""
    out: dict[tuple[str, str], set[tuple[float, str]]] = defaultdict(set)
    path = RAW / "issste_catalogo.csv"
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            desc = row["descripcion"] or ""
            parts = [p.strip() for p in desc.split(".")]
            if len(parts) < 2:
                continue
            generic = parts[0]
            form = parts[1]
            st = parse_strength(desc)
            if not st:
                continue
            out[(key(generic), form_base_es(form))].add(st)
    return out


def load_prorrogas() -> dict[str, dict]:
    """续期清单：注册号 → 该注册号最新一次续期的到期日与产品字段。

    续期清单里有 2001 年前批的老注册号（3790、0136M79），
    这些在「expedidos 2001–2026」里根本没有，是唯一的补录入口。
    """
    path = RAW / "cofepris_prorrogas.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            reg = (row["registro"] or "").strip()
            if not reg:
                continue
            d = parse_vigencia(row["vigencia"])
            old = out.get(reg)
            if old and (old["date"] or date.min) >= (d or date.min):
                continue
            out[reg] = {
                "date": d, "raw": row["vigencia"], "brand": row["brand"],
                "generic": row["generic"], "form": row["form"], "holder": row["holder"],
                "class226": row["class226"], "src_year": row["src_year"],
                "src_file": row["src_file"],
            }
    return out


def load_profeco() -> dict[str, set[tuple[float, str, str]]]:
    """商品名归一 → {(浓度, 单位, form_base)}。

    优先用 profeco_all.csv（2024–2026 三年并集，412 个商品名），
    没有就退回单年的 profeco_medicamentos.csv（378 个）。
    """
    path = RAW / "profeco_all.csv"
    if not path.exists():
        path = RAW / "profeco_medicamentos.csv"
    out: dict[str, set[tuple[float, str, str]]] = defaultdict(set)
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = key(row["producto"])
            pres = row["presentacion"] or ""
            st = parse_strength(pres)
            if not name or not st:
                continue
            out[name].add((st[0], st[1], form_base_es(pres)))
    return out


def ensure_variant(db: sqlite3.Connection, inn: str, want_id: str) -> str:
    """保证 (substance, variant) 存在，返回可挂 product_component 的 variant_id。

    substance.inn_en 是 UNIQUE，substance_id / variant_id 是主键：三者都可能撞。
    所以先按 inn_en 找，找不到再按 id 找，最后才插入，插入前把 id 让开。
    """
    row = db.execute("SELECT substance_id FROM substance WHERE inn_en=?", (inn,)).fetchone()
    if row:
        sid = row[0]
    else:
        sid, n = want_id, 1
        while db.execute("SELECT 1 FROM substance WHERE substance_id=?", (sid,)).fetchone():
            n += 1
            sid = f"{want_id}-{n}"
        db.execute("INSERT INTO substance (substance_id, inn_en) VALUES (?,?)", (sid, inn))

    var = db.execute("SELECT variant_id FROM variant WHERE substance_id=? LIMIT 1",
                     (sid,)).fetchone()
    if var:
        return var[0]
    vid, n = sid, 1
    while db.execute("SELECT 1 FROM variant WHERE variant_id=?", (vid,)).fetchone():
        n += 1
        vid = f"{sid}-{n}"
    db.execute("INSERT INTO variant (variant_id, substance_id) VALUES (?,?)", (vid, sid))
    return vid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--clean", action="store_true",
                    help="只清掉墨西哥数据与孤儿 substance/variant 后退出（重建映射前用）")
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.execute("PRAGMA foreign_keys = ON")

    # --- source ---
    files = {f["name"]: f for f in json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]}
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        (SOURCE_ID, "COFEPRIS – Registros Sanitarios de Medicamentos Alopáticos",
         "https://www.gob.mx/cofepris/documentos/registros-sanitarios-medicamentos",
         "Gobierno de México · uso con atribución（未标注开放许可）",
         "https://www.gob.mx/terminos", TODAY,
         "26 个按年 PDF（2001–2026）+ revocados/cancelados。原始清单无浓度列。"),
    )
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        ("issste_catalogo", "ISSSTE – Catálogo Institucional de Insumos",
         "https://datos.gob.mx/dataset/catalogo_institucional_insumos",
         "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/", TODAY,
         "公共采购目录；只用于给通用名级回填浓度。"),
    )
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        ("profeco_precios", "PROFECO – Quién es quién en los precios (Medicamentos)",
         "https://datos.gob.mx/dataset/programa_quien_es_quien_precios_2026",
         "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/", TODAY,
         "零售价格调查；只用于给商品名级回填浓度。"),
    )

    # --- 状态 ---
    status: dict[str, tuple[str, str, str]] = {}
    spath = RAW / "cofepris_status.csv"
    if spath.exists():
        with spath.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                status[row["registro"]] = (row["kind"], row["src_year"], row["cause"])

    issste = load_issste()
    issste_by_generic: dict[str, set[tuple[float, str]]] = defaultdict(set)
    for (_g, _fb), _vals in issste.items():
        issste_by_generic[_g] |= _vals
    profeco = load_profeco()
    prorrogas = load_prorrogas()
    inn_map = json.loads(INN_MAP.read_text(encoding="utf-8"))["terms"] if INN_MAP.exists() else {}
    print(f"issste 组合键 {len(issste):,}；profeco 商品名 {len(profeco):,}；"
          f"续期 {len(prorrogas):,}；西语映射 {len(inn_map):,}")

    rows = list(csv.DictReader((RAW / "cofepris_alopaticos.csv").open(encoding="utf-8-sig")))
    if args.limit:
        rows = rows[: args.limit]

    # 续期清单里那些 2001 年前批的注册号，在 expedidos 里完全没有，单独补录
    known = {r["registro"].strip() for r in rows}
    extra = 0
    for reg, p in prorrogas.items():
        if reg in known:
            continue
        rows.append({"registro": reg, "brand": p["brand"] or "", "generic": p["generic"] or "",
                     "form": p["form"] or "", "holder": p["holder"] or "",
                     "class226": p["class226"] or "", "vigencia": p["raw"] or "",
                     "src_year": p["src_year"] or "", "src_file": p["src_file"] or ""})
        extra += 1
    print(f"待入库 {len(rows):,} 条注册（其中续期清单补录 {extra:,} 条旧注册号）")

    stats: Counter = Counter()
    seen_sub: set[str] = set()
    seen_var: set[str] = set()
    seen_key: set[str] = set()

    # 重跑时先清掉墨西哥段，避免上一版的 product_name 残留（INSERT OR IGNORE 不会删）
    old = [r[0] for r in db.execute("SELECT product_id FROM product WHERE country='MX'")]
    if old:
        print(f"清理上一版 MX 数据 {len(old):,} 条")
        db.execute("DELETE FROM product_name WHERE product_id IN"
                   " (SELECT product_id FROM product WHERE country='MX')")
        db.execute("DELETE FROM product_component WHERE product_id IN"
                   " (SELECT product_id FROM product WHERE country='MX')")
        db.execute("DELETE FROM corroboration WHERE product_id IN"
                   " (SELECT product_id FROM product WHERE country='MX')")
        db.execute("DELETE FROM product WHERE country='MX'")
        db.commit()

    # 孤儿清理：上一版造的 substance/variant 不再被任何产品引用就删掉
    n_var = db.execute(
        "DELETE FROM variant WHERE variant_id NOT IN"
        " (SELECT variant_id FROM product_component)").rowcount
    n_sub = db.execute(
        "DELETE FROM substance WHERE substance_id NOT IN"
        " (SELECT substance_id FROM variant)").rowcount
    if n_var or n_sub:
        print(f"清理孤儿 variant {n_var:,} / substance {n_sub:,}")
    db.commit()
    if args.clean:
        print("已清理，退出。下一步：python etl/build_mx_inn_map.py 然后重跑本脚本")
        db.close()
        return 0

    for row in rows:
        reg = row["registro"].strip()
        if not reg:
            stats["skip_noreg"] += 1
            continue
        pid = f"MX-{reg}"
        brand = clean_brand(row["brand"])
        generic = clean_generic(row["generic"])
        form = (row["form"] or "").strip().lower() or "unknown"
        holder = (row["holder"] or "").strip()
        base = form_base_es(form)
        class226 = (row["class226"] or "").strip()
        vigencia = (row["vigencia"] or "").strip()

        kind, year, cause = status.get(reg, ("", "", ""))
        vig_date = parse_vigencia(vigencia)
        renewed = ""
        pro = prorrogas.get(reg)
        if pro and pro["date"] and (vig_date is None or pro["date"] > vig_date):
            vig_date, renewed = pro["date"], (pro["src_year"] or "?")
        if kind in ("revocado", "cancelado"):
            p_status, status_date = "withdrawn", (year or None)
            status_basis = f"{kind} {year}"
        elif vig_date:
            if vig_date < date.today():
                p_status, status_date = "discontinued", vig_date.isoformat()
                status_basis = f"有效期 {vig_date.isoformat()} 已过" + \
                               (f"（{renewed} 年续期）" if renewed else "")
            else:
                p_status, status_date = "active", None
                status_basis = f"有效期至 {vig_date.isoformat()}" + \
                               (f"（{renewed} 年续期）" if renewed else "")
        else:
            # 2001–2010 的文件没有有效期列：不假装在册，也不假装停售
            p_status, status_date = "unknown", None
            status_basis = "有效期未在原始清单中列出"

        # --- 规格回填 ---
        strength = None
        strength_src = ""
        if brand and key(brand) in profeco:
            cand = {(v, u) for v, u, fb in profeco[key(brand)] if fb == base}
            if len(cand) == 1:
                strength = next(iter(cand))
                strength_src = "profeco"
        if strength is None and len([g for g in re.split(r"\s*[/,]\s*", generic) if g]) == 1:
            cand = issste.get((key(generic), base), set())
            if len(cand) == 1:
                strength = next(iter(cand))
                strength_src = "issste"
            elif base in SOLID_BASES:
                # 固体制剂放宽到「只看通用名」：500 mg 的片剂和胶囊是同一个规格，
                # 但液体制剂不能这么推（mg 与 mg/ml 不可比），所以只对固体生效。
                allv = issste_by_generic.get(key(generic), set())
                if len(allv) == 1 and next(iter(allv))[1] in {"mg", "mcg", "g"}:
                    strength = next(iter(allv))
                    strength_src = "issste_generic"

        notes = []
        if class226:
            notes.append(f"Art.226 {class226}")
        if vigencia:
            notes.append(f"vigencia {vigencia}")
        if "rorrog" in (row.get("src_file") or ""):
            notes.append(f"仅见于 {row.get('src_year') or '?'} 年续期清单"
                         "（原始批准年份早于 2001）")
            stats["from_prorroga"] += 1
        if kind:
            notes.append(f"{kind} {year}" + (f": {cause}" if cause else ""))
        if strength_src:
            notes.append(f"浓度回填自 {strength_src}")
        if p_status != "active":
            notes.append(f"状态依据：{status_basis}")
        note = "; ".join(notes) or None

        src_file = row["src_file"]
        src_url = files.get(src_file, {}).get("url")

        db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
            " route, release, pack, mah, approval_id, category, is_branded, status,"
            " status_date, source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "MX", form, base, route_es(form, base), release_es(form), None, holder,
             reg, "Registro Sanitario", 1 if brand else 0, p_status, status_date,
             SOURCE_ID, src_url, TODAY, note),
        )
        stats["products"] += 1
        stats[f"status_{p_status}"] += 1
        if strength_src:
            stats[f"strength_{strength_src}"] += 1

        # --- 成分 ---
        parts = [p.strip() for p in re.split(r"\s*[/,]\s*", generic) if p.strip()]
        if not parts:
            stats["no_generic"] += 1
        for ord_, part in enumerate(parts[:6]):
            k = key(part)
            info = inn_map.get(k) or {}
            inn = info.get("inn") or ""
            if inn:
                stats[f"inn_{info.get('via', '?')}"] += 1
            else:
                # 只在墨西哥出现的通用名：用西语名当 INN，但 id 加 mx-es- 前缀，
                # 免得下一轮 build_mx_inn_map 把它们当成英文 INN 精确命中自己。
                inn = " ".join(w.capitalize() for w in part.lower().split())
                stats["inn_mx_only"] += 1
            sid = slug(inn) if info.get("inn") else f"mx-es-{slug(inn)}"
            sid = ensure_variant(db, inn, sid)
            sv = strength[0] if strength else None
            su = strength[1] if strength else None
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit) VALUES (?,?,?,?,?)",
                (pid, ord_, sid, sv, su),
            )
            if strength_src:
                db.execute(
                    "INSERT OR IGNORE INTO corroboration (product_id, source_type, url,"
                    " retrieved_at, verified_by, note) VALUES (?,?,?,?,?,?)",
                    (pid, "provincial_list" if strength_src == "issste" else "commercial",
                     "https://datos.gob.mx/dataset/"
                     + ("catalogo_institucional_insumos" if strength_src == "issste"
                        else "programa_quien_es_quien_precios_2026"),
                     TODAY, "etl/ingest_mx.py", f"浓度来自 {strength_src}"),
                )

        # --- 名字 ---
        for raw_name, ntype, primary in ((brand, "trade", 1),):
            if not raw_name:
                continue
            n = normalize(raw_name)
            if n.is_empty:
                continue
            if n.norm not in seen_key:
                seen_key.add(n.norm)
                db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                           " VALUES (?,?,?,?)", (n.norm, n.norm, n.compact, n.script))
                db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                           " VALUES (?,?,?)", (n.norm, raw_name, SOURCE_ID))
            db.execute("INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                       " is_primary) VALUES (?,?,?,?)", (pid, n.norm, ntype, primary))

        # 西语通用名也进名字键（name_type=inn），这样搜 "Paracetamol" 能命中墨西哥条目。
        # 复方不挂：collision 视图按「这个名字下的产品涉及几个成分」判严重，
        # 复方会把 3 个成分都算进每个成分名下，凭空造出「同名不同药」。品牌名照挂。
        if len(parts) == 1:
            for part in parts:
                n = normalize(part)
                if n.is_empty:
                    continue
                if n.norm not in seen_key:
                    seen_key.add(n.norm)
                    db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                               " VALUES (?,?,?,?)", (n.norm, n.norm, n.compact, n.script))
                    db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                               " VALUES (?,?,?)", (n.norm, part, SOURCE_ID))
                db.execute("INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                           " is_primary) VALUES (?,?,?,?)", (pid, n.norm, "inn", 0))

    db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY, len(rows), stats["products"],
         len(rows) - stats["products"], "ok", json.dumps(stats)),
    )
    db.commit()

    print("\n== 统计 ==")
    for k, v in sorted(stats.items()):
        print(f"  {k:<22}{v:>8,}")
    print("\n== coverage ==")
    for r in db.execute("SELECT country, n_products, n_variants, n_active, last_synced"
                        " FROM coverage ORDER BY country"):
        print("  ", r)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
