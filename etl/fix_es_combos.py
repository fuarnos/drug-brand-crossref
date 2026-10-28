# -*- coding: utf-8 -*-
"""ES CIMA 复方补全（task-38，默认 dry-run）。

背景（审计结论，见报告）
------------------------
CIMA 列表里有 208 条记录没有进入 `data/drugs.db`：
- 203 条 `vtm.nombre = "multicomponente"`（CIMA 对 ≥4 成分复方/血制品/造影剂/营养液的占位名），
  `etl/ingest_cima.py` 直接 skip；
- 5 条列表缺 nombre/vtm 字段。
它们**不是**「已入库但只挂 1 个成分」，而是整条产品缺失（25,501 − 25,293 = 208）。
CIMA 详情接口（`/cima/rest/medicamento?nregistro=`）返回 `principiosActivos[]`
（nombre/cantidad/unidad/orden），本脚本据此恢复产品 + 成分，但**只使用库内已存在的
substance**（不新建成分、不改已有产品身份）。

两个子命令
----------
1. `--build-candidates`：读 CIMA 列表缓存 + `.tmp/es-combos/detail/*.json`，用西语→英语
   规则映射生成 `data/es_combo_candidates.csv`（含 components_json，apply 可离线重放）。
2. 默认 dry-run / `--apply` / `--rollback`：按候选 CSV 恢复产品与 product_component 行；
   只在 `.tmp/es-combos/` 副本验证；`--apply` 默认拒绝写 `data/drugs.db`。

用法：
    python etl/fix_es_combos.py --build-candidates        # 生成/刷新候选 CSV
    python etl/fix_es_combos.py                           # dry-run（只读）
    python etl/fix_es_combos.py --apply --db .tmp/es-combos/drugs-test.db
    python etl/fix_es_combos.py --rollback --db .tmp/es-combos/drugs-test.db
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
import ingest_cima as ic  # noqa: E402  复用 CIMA 解析口径

DB = ROOT / "data" / "drugs.db"
CAND = ROOT / "data" / "es_combo_candidates.csv"
DETAIL = ROOT / ".tmp" / "es-combos" / "detail"
EVID = ROOT / ".tmp" / "es-combos"
APPLIED = EVID / "applied_es_combos.json"
TODAY = date.today().isoformat()
SOURCE_ID = "cima_combo_fix"

# ---------------------------------------------------------------------------
# 西语成分名 → 英语化学名（规则字典；只覆盖 208 条里出现的名字，未命中就留 missing）
# ---------------------------------------------------------------------------
PHRASES = {
    "acido acetilsalicilico": "aspirin", "acido ascorbico": "ascorbic acid",
    "ascorbico acido": "ascorbic acid", "acido aspartico": "aspartic acid",
    "aspartico acido": "aspartic acid", "acido glutamico": "glutamic acid",
    "glutamico acido": "glutamic acid", "acido folico": "folic acid",
    "folico acido": "folic acid", "acido citrico": "citric acid",
    "citrico acido": "citric acid", "acido clorhidrico": "hydrochloric acid",
    "acido lactico": "lactic acid", "acido malico": "malic acid",
    "acido acetico": "acetic acid", "acido oleico": "oleic acid",
    "pantotenato calcio": "calcium pantothenate",
    "pantotenato de calcio": "calcium pantothenate",
    "cloruro de potasio": "potassium chloride", "cloruro potasico": "potassium chloride",
    "cloruro de sodio": "sodium chloride", "cloruro sodico": "sodium chloride",
    "cloruro de calcio": "calcium chloride", "cloruro calcico": "calcium chloride",
    "cloruro de magnesio": "magnesium chloride", "magnesio cloruro": "magnesium chloride",
    "calcio cloruro": "calcium chloride", "sodio cloruro": "sodium chloride",
    "potasio cloruro": "potassium chloride",
    "acetato de sodio": "sodium acetate", "acetato sodico": "sodium acetate",
    "acetato de potasio": "potassium acetate", "acetato potasico": "potassium acetate",
    "acetato de magnesio": "magnesium acetate", "acetato magnesio": "magnesium acetate",
    "acetato de calcio": "calcium acetate",
    "lactato de sodio": "sodium lactate", "lactato sodico": "sodium lactate",
    "sulfato de magnesio": "magnesium sulfate", "magnesio sulfato": "magnesium sulfate",
    "sulfato de sodio": "sodium sulfate", "sodio sulfato": "sodium sulfate",
    "fosfato de sodio": "sodium phosphate", "fosfato sodico": "sodium phosphate",
    "fosfato de potasio": "potassium phosphate",
    "fosfato de calcio": "calcium phosphate", "fosforo": "phosphorus",
    "hidroxido de sodio": "sodium hydroxide", "sodio hidroxido": "sodium hydroxide",
    "citrato de sodio": "sodium citrate", "citrato sodico": "sodium citrate",
    "glicerofosfato de sodio": "sodium glycerophosphate",
    "glicerofosfato sodico": "sodium glycerophosphate",
    "glucosa": "glucose", "glucosa anhidra": "glucose", "dextrosa": "dextrose",
    "tiamina": "thiamine", "tiamina nitrato": "thiamine", "riboflavina": "riboflavin",
    "nicotinamida": "nicotinamide", "piridoxina": "pyridoxine", "biotina": "biotin",
    "cianocobalamina": "cyanocobalamin", "folico": "folic acid", "retinol": "retinol",
    "vitamina a": "retinol", "vitamina d": "colecalciferol", "vitamina e": "tocopherol",
    "tocoferol": "tocopherol", "alfa tocoferol": "alpha-tocopherol",
    "todo rac alfa tocoferol": "alpha-tocopherol",
    "todo rac alfa tocoferilo acetato de": "alpha-tocopherol",
    "colecalciferol": "colecalciferol", "fitomenadiona": "phytomenadione",
    "dexpantenol": "dexpanthenol", "alanina": "alanine", "arginina": "arginine",
    "treonina": "threonine", "metionina": "methionine",
    "fenilalanina": "phenylalanine", "prolina": "proline", "serina": "serine",
    "triptofano": "tryptophan", "glicina": "glycine", "tirosina": "tyrosine",
    "valina": "valine", "leucina": "leucine", "isoleucina": "isoleucine",
    "lisina": "lysine", "histidina": "histidine", "cisteina": "cysteine",
    "factor ii": "coagulation factor ii", "factor vii": "coagulation factor vii",
    "factor ix": "coagulation factor ix", "factor x": "coagulation factor x",
    "proteina c": "protein c", "proteina s": "protein s",
    "trigliceridos cadena media": "medium-chain triglycerides",
    "trigliceridos de cadena media": "medium-chain triglycerides",
    "aceite de soja": "soybean oil", "soja aceite de refinado": "soybean oil",
    "aceite soja purificado": "soybean oil", "aceite de oliva": "olive oil",
    "oliva aceite de refinado": "olive oil", "aceite de pescado": "fish oil",
    "aceite de pescado rico en omega 3": "fish oil",
    "iodo": "iodine", "yodo": "iodine", "ioduro": "iodide",
    "iopamidol": "iopamidol", "iohexol": "iohexol", "ioversol": "ioversol",
    "iobitridol": "iobitridol", "iomeprol": "iomeprol", "iopromida": "iopromide",
    "ioxaglato": "ioxaglate", "gadobutrol": "gadobutrol",
    "hierro": "iron", "zinc": "zinc", "cobre": "copper", "manganeso": "manganese",
    "selenio": "selenium", "cromo": "chromium", "molibdeno": "molybdenum",
    "floruro": "fluoride", "fluoruro": "fluoride",
}
DROP_WORDS = {
    "anhidro", "anhidra", "monohidrato", "monohidratado", "dihidrato", "dihidratado",
    "trihidrato", "trihidratado", "tetrahidrato", "tetrahidratado", "hexahidrato",
    "heptahidrato", "hidratado", "hidratada", "de", "del", "la", "el", "los", "las",
    "y", "con", "para", "en", "solucion", "polvo", "agua", "c s",
}
SALT_ALIASES = {
    "clorhidrato": "hydrochloride", "hidrocloruro": "hydrochloride",
    "sodico": "sodium", "sodica": "sodium", "sodio": "sodium",
    "potasico": "potassium", "potasica": "potassium",
    "calcico": "calcium", "calcica": "calcium", "magnesico": "magnesium",
    "nitrato": "nitrate", "sulfato": "sulfate", "fosfato": "phosphate",
    "citrato": "citrate", "lactato": "lactate", "acetato": "acetate",
    "maleato": "maleate", "fumarato": "fumarate", "tartrato": "tartrate",
    "mesilato": "mesylate", "besilato": "besylate", "tosilato": "tosylate",
    "succinato": "succinate", "gluconato": "gluconate", "carbonato": "carbonate",
    "bicarbonato": "bicarbonate", "cloruro": "chloride",
}


def deacc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def norm(s: str) -> str:
    s = deacc(s or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    words = [w for w in s.split() if w not in DROP_WORDS]
    return " ".join(words)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", deacc(s or "").lower()).strip("-")


# 短语表先按 norm() 归一（norm 会去掉 de/del/la/水合词），保证 "cloruro de potasio"
# 与 "cloruro potasio" 都能命中
PHRASES_N = {norm(k): v for k, v in PHRASES.items()}


class SubstanceIndex:
    """库内 substance 英文名索引；优先英文市场（US/GB/CN）在用、非 mx-es/cn 的 id。"""

    def __init__(self, db_path: Path):
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        self.by_norm: dict[str, str] = {}
        self.by_slug: dict[str, str] = {}
        english = {r[0] for r in con.execute("""
            SELECT DISTINCT v.substance_id FROM product p
            JOIN product_component pc ON pc.product_id=p.product_id
            JOIN variant v ON v.variant_id=pc.variant_id
            WHERE p.country IN ('US','GB','CN')""")}
        rows = list(con.execute("SELECT substance_id, inn_en FROM substance"))
        # 先英文市场成分，再其它（setdefault 保证优先）
        for sid, inn in [r for r in rows if r[0] in english]:
            self.by_norm.setdefault(norm(inn), sid)
            self.by_slug.setdefault(slug(inn), sid)
        for sid, inn in rows:
            if sid.startswith("mx-es-"):
                continue
            self.by_norm.setdefault(norm(inn), sid)
            self.by_slug.setdefault(slug(inn), sid)
        con.close()

    def lookup(self, name: str) -> tuple[str | None, str]:
        n = norm(name)
        if not n:
            return None, ""
        if n in self.by_norm:
            return self.by_norm[n], "norm_exact"
        if slug(n) in self.by_slug:
            return self.by_slug[slug(n)], "slug_exact"
        toks = n.split()
        if len(toks) == 2:
            n2 = " ".join(reversed(toks))
            if n2 in self.by_norm:
                return self.by_norm[n2], "reversed"
            if slug(n2) in self.by_slug:
                return self.by_slug[slug(n2)], "reversed_slug"
        return None, ""


def map_ingredient(name_es: str, idx: SubstanceIndex) -> tuple[str | None, str]:
    n = norm(name_es)
    if not n:
        return None, ""
    if n in PHRASES_N:
        sid, _ = idx.lookup(PHRASES_N[n])
        if sid:
            return sid, "phrase"
    sid, via = idx.lookup(n)
    if sid:
        return sid, via
    toks = n.split()
    for cut in (toks[:-1], toks[1:]):
        if not cut:
            continue
        cand = " ".join(cut)
        if cand in PHRASES_N:
            sid, _ = idx.lookup(PHRASES_N[cand])
            if sid:
                return sid, "phrase_trim"
        sid, via = idx.lookup(cand)
        if sid:
            return sid, via + "_trim"
    if toks and toks[0] in SALT_ALIASES:
        for order in (toks[1:] + [SALT_ALIASES[toks[0]]],
                      [SALT_ALIASES[toks[0]]] + toks[1:]):
            sid, via = idx.lookup(" ".join(order))
            if sid:
                return sid, "salt_" + via
    trans = []
    for w in toks:
        if w in PHRASES_N:
            trans.extend(PHRASES_N[w].split())
        elif w in SALT_ALIASES:
            trans.append(SALT_ALIASES[w])
        else:
            return None, ""
    sid, via = idx.lookup(" ".join(trans))
    if sid:
        return sid, "word_by_word"
    return None, ""


# ---------------------------------------------------------------------------
# 成分强度解析（principiosActivos 的 cantidad/unidad）
# ---------------------------------------------------------------------------
UNIT_MAP = {
    "mg": "mg", "miligramo": "mg", "miligramos": "mg", "g": "g", "gramo": "g",
    "gramos": "g", "mcg": "mcg", "µg": "mcg", "μg": "mcg", "ug": "mcg",
    "ui": "iu", "iu": "iu", "ml": "ml", "mililitro": "ml", "mililitros": "ml",
    "%": "%",
}


def parse_qty(cantidad, unidad):
    c = (cantidad or "").strip().replace(" ", "")
    u = (unidad or "").strip().lower()
    unit = UNIT_MAP.get(u)
    if not unit:
        return None, ""
    if re.fullmatch(r"\d+(?:[.,]\d+)?", c):
        return float(c.replace(",", ".")), unit
    return None, ""


# ---------------------------------------------------------------------------
# 候选构建
# ---------------------------------------------------------------------------
PUBLIC_URL = "https://cima.aemps.es/cima/publico/detalle.html?nregistro={nreg}"


def load_list_records() -> dict[str, dict]:
    out = {}
    for f in sorted(glob.glob(str(ROOT / "data/raw/cima/page-*.json"))):
        for r in json.load(open(f, encoding="utf-8")).get("resultados", []):
            out[str(r.get("nregistro") or "").strip()] = r
    return out


def build_candidates() -> int:
    records = load_list_records()
    multi = [n for n, r in records.items()
             if ((r.get("vtm") or {}).get("nombre") or "").strip().lower() == "multicomponente"]
    missing_fields = [n for n, r in records.items()
                      if not (r.get("nombre") or "").strip()
                      or not ((r.get("vtm") or {}).get("nombre") or "").strip()]
    todo = list(dict.fromkeys(multi + missing_fields))
    print(f"CIMA 列表 {len(records)} 条；待恢复 {len(todo)}（multicomponente {len(multi)}"
          f" + 缺字段 {len(missing_fields)}）")

    idx = SubstanceIndex(DB)
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    es_existing = {r[0] for r in con.execute("SELECT product_id FROM product WHERE country='ES'")}
    con.close()

    rows = []
    detail_missing = 0
    for nreg in todo:
        dpath = DETAIL / f"{nreg}.json"
        if not dpath.exists():
            detail_missing += 1
            continue
        detail = json.load(open(dpath, encoding="utf-8"))
        activos = detail.get("principiosActivos") or []
        nombre = (detail.get("nombre") or records.get(nreg, {}).get("nombre") or "").strip()
        if not nombre or not activos:
            continue
        comps = []
        for i, a in enumerate(activos):
            name_es = (a.get("nombre") or "").strip()
            sid, via = map_ingredient(name_es, idx)
            base, salt = ic.split_salt_es(name_es)
            val, unit = parse_qty(a.get("cantidad"), a.get("unidad"))
            comps.append({
                "orden": i, "name_es": name_es, "sid": sid or "", "salt": salt or "",
                "via": via, "value": val, "unit": unit, "mapped": bool(sid),
            })
        n = len(comps)
        n_ok = sum(1 for c in comps if c["mapped"])
        coverage = "all" if n_ok == n else ("none" if n_ok == 0 else "partial")

        # 产品元数据（按 ingest_cima 的口径）
        form_s = ((detail.get("formaFarmaceuticaSimplificada") or {}).get("nombre") or "").strip()
        form_f = ((detail.get("formaFarmaceutica") or {}).get("nombre") or "").strip()
        estado = detail.get("estado") or {}
        status, status_date, status_note = ic.status_of(detail)
        nombre_norm = ic.normalize(nombre).norm
        brand_display = ic.es_brand_display(nombre)
        brand_norm = " ".join(ic.es_brand_tokens(nombre_norm))
        ing_es = " + ".join(c["name_es"] for c in comps)
        ing_en = " + ".join(
            next(iter(ic.ALIASES.get(norm(c["name_es"]).split()[0], (c["sid"],))), c["sid"])
            if c["sid"] else "" for c in comps)
        # ing_en 直接用 mapped sid 的 inn_en 更好
        sid_names = {}
        if any(c["sid"] for c in comps):
            con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
            for c in comps:
                if c["sid"] and c["sid"] not in sid_names:
                    row = con.execute("SELECT inn_en FROM substance WHERE substance_id=?", (c["sid"],)).fetchone()
                    sid_names[c["sid"]] = row[0] if row else c["sid"]
            con.close()
        ing_en = " + ".join(sid_names.get(c["sid"], "") for c in comps if c["sid"])
        # 展示层去重（同一 substance 可能由不同盐/重复项指到）
        seen_sid = set()
        uniq_names = []
        for c in comps:
            if not c["sid"] or c["sid"] in seen_sid:
                continue
            seen_sid.add(c["sid"])
            uniq_names.append(sid_names.get(c["sid"], ""))
        ing_en = " + ".join(uniq_names)
        rows.append({
            "product_id": f"ES-{nreg}", "nregistro": nreg, "nombre": nombre,
            "pactivos": (detail.get("pactivos") or "").strip(),
            "cpresc": (detail.get("cpresc") or "").strip(),
            "generico": int(bool(detail.get("generico"))),
            "biosimilar": int(bool(detail.get("biosimilar"))),
            "triangulo": int(bool(detail.get("triangulo"))),
            "labtitular": (detail.get("labtitular") or "").strip(),
            "forma_simplificada": form_s, "forma_completa": form_f,
            "status": status, "status_date": status_date or "", "status_note": status_note or "",
            "brand_display": brand_display, "brand_norm": brand_norm,
            "ing_es": ing_es, "ing_en": ing_en,
            "is_branded": int(bool(brand_norm) and brand_norm != ic.normalize(ing_es).norm),
            "n_activos": n, "n_mapped": n_ok, "coverage": coverage,
            "confidence": "high" if coverage == "all" else ("medium" if coverage == "partial" else "low"),
            "missing": "; ".join(c["name_es"] for c in comps if not c["mapped"]),
            "components_json": json.dumps(comps, ensure_ascii=False),
            "evidence_url": PUBLIC_URL.format(nreg=nreg),
            "in_db": "yes" if f"ES-{nreg}" in es_existing else "no",
        })

    CAND.parent.mkdir(parents=True, exist_ok=True)
    with CAND.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"候选 {len(rows)} 条（详情缺失 {detail_missing}）→ {CAND.relative_to(ROOT)}")
    print("coverage:", dict(Counter(r["coverage"] for r in rows)),
          "| 已在库:", dict(Counter(r["in_db"] for r in rows)))
    print("成分总数:", sum(r["n_activos"] for r in rows),
          "| 已映射:", sum(r["n_mapped"] for r in rows))
    return 0


# ---------------------------------------------------------------------------
# dry-run / apply / rollback
# ---------------------------------------------------------------------------
def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def load_candidates(include_partial: bool) -> list[dict]:
    if not CAND.exists():
        raise SystemExit(f"候选不存在：{CAND.relative_to(ROOT)}（先跑 --build-candidates）")
    rows = list(csv.DictReader(CAND.open(encoding="utf-8-sig")))
    out = []
    for r in rows:
        if r["in_db"] == "yes":
            continue
        if r["coverage"] != "all" and not include_partial:
            continue
        comps = json.loads(r["components_json"])
        if r["coverage"] == "partial":
            comps = [c for c in comps if c["sid"]]
        # 同一 substance 出现多次（不同盐/重复项）只保留第一次，避免展示重复成分
        seen = set()
        dedup = []
        for c in comps:
            if c["sid"] in seen:
                continue
            seen.add(c["sid"])
            dedup.append(c)
        comps = dedup
        if len(comps) < 2:      # 单成分不是复方补全目标
            continue
        out.append({**r, "comps": comps})
    return out


def check_state(con: sqlite3.Connection, cands: list[dict]) -> tuple[list[dict], dict]:
    stats = Counter()
    ok = []
    subs = {r[0] for r in con.execute("SELECT substance_id FROM substance")}
    for c in cands:
        exists = con.execute("SELECT 1 FROM product WHERE product_id=?", (c["product_id"],)).fetchone()
        if exists:
            stats["already_product"] += 1
            continue
        miss = [x["sid"] for x in c["comps"] if x["sid"] not in subs]
        if miss:
            stats["missing_substance"] += 1
            continue
        ok.append(c)
    return ok, dict(stats)


def variant_of(con: sqlite3.Connection, sid: str, salt: str, created: list[str]) -> str:
    row = con.execute("SELECT variant_id FROM variant WHERE substance_id=? AND salt=?"
                      " ORDER BY variant_id LIMIT 1", (sid, salt)).fetchone()
    if row:
        return row[0]
    row = con.execute("SELECT variant_id FROM variant WHERE substance_id=? AND salt=''"
                      " ORDER BY variant_id LIMIT 1", (sid,)).fetchone()
    if row and not salt:
        return row[0]
    vid = f"{sid}-{slug(salt)}" if salt else sid
    con.execute("INSERT OR IGNORE INTO variant (variant_id, substance_id, salt, hydrate,"
                " ester, base_fraction, interchange) VALUES (?,?,?,'','',1.0,'unknown')",
                (vid, sid, salt))
    created.append(vid)
    return vid


def apply_candidates(con: sqlite3.Connection, cands: list[dict]) -> dict:
    written = Counter()
    applied = []
    created_variants: list[str] = []
    seen_key: set[str] = set()
    seen_nv: set[tuple[str, str]] = set()
    try:
        if not con.execute("SELECT 1 FROM source WHERE source_id='cima'").fetchone():
            raise SystemExit("source 表缺少 cima 行；请先在正式库跑过 etl/ingest_cima.py")
        for c in cands:
            comps = c["comps"]
            pid = c["product_id"]
            form_s = c["forma_simplificada"]
            note = " | ".join(x for x in (c["cpresc"], "genérico" if c["generico"] == "1" else "",
                                          "biosimilar" if c["biosimilar"] == "1" else "",
                                          "triángulo" if c["triangulo"] == "1" else "",
                                          c["status_note"]) if x)
            con.execute(
                "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
                " route, release, pack, mah, approval_id, category, is_branded, status,"
                " status_date, source_id, source_url, retrieved_at, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, "ES", (form_s.lower() or "unknown"), ic.form_base_es(form_s),
                 None, ic.release_of(form_s, c["nombre"]), None, c["labtitular"] or None,
                 c["nregistro"], "CIMA", int(c["is_branded"]), c["status"],
                 c["status_date"] or None, "cima", c["evidence_url"], TODAY, note or None))
            for i, comp in enumerate(comps):
                vid = variant_of(con, comp["sid"], comp["salt"] or "", created_variants)
                val = comp["value"]
                unit = comp["unit"] or ""
                con.execute(
                    "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                    " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                    " VALUES (?,?,?,?,?,?,?)", (pid, i, vid, val, unit or None, None, None))
            # 名字：品牌（trade）+ 西语成分组合（inn）+ 英文成分组合（inn 副名）
            if c["brand_display"]:
                ic._put_name(con, pid, c["brand_display"], "trade" if c["is_branded"] == "1" else "inn",
                             1, seen_key, seen_nv)
            if c["ing_es"]:
                ic._put_name(con, pid, c["ing_es"], "inn", 0 if c["is_branded"] == "1" else 1,
                             seen_key, seen_nv)
            if c["ing_en"]:
                ic._put_name(con, pid, c["ing_en"], "inn", 0, seen_key, seen_nv)
            written["products"] += 1
            written["components"] += len(comps)
            applied.append({"product_id": pid, "n_components": len(comps),
                            "component_sids": [x["sid"] for x in comps],
                            "created_variants": list(created_variants)})
        con.execute(
            "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
            " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY, len(cands),
             written["products"], 0, "ok", json.dumps({"written": dict(written)}, ensure_ascii=False)))
        con.commit()
        EVID.mkdir(parents=True, exist_ok=True)
        prev = []
        if APPLIED.exists():
            try:
                prev = json.loads(APPLIED.read_text(encoding="utf-8")).get("entries") or []
            except json.JSONDecodeError:
                prev = []
        merged = {e["product_id"]: e for e in prev + applied}
        APPLIED.write_text(json.dumps(
            {"applied_at": TODAY, "source_id": SOURCE_ID, "count": len(merged),
             "entries": list(merged.values())}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        con.rollback()
        raise
    return dict(written)


def rollback(con: sqlite3.Connection) -> dict:
    out = Counter()
    if not APPLIED.exists():
        raise SystemExit(f"找不到 {APPLIED.relative_to(ROOT)}：拒绝回滚。")
    payload = json.loads(APPLIED.read_text(encoding="utf-8"))
    entries = payload.get("entries") or []
    try:
        for e in entries:
            pid = e["product_id"]
            # 记录产品当前挂的 name_key（用于清理）
            keys = [r[0] for r in con.execute(
                "SELECT DISTINCT key_id FROM product_name WHERE product_id=?", (pid,))]
            # 显式删关联行（SQLite 连接默认 foreign_keys=OFF，不能指望 ON DELETE CASCADE）
            con.execute("DELETE FROM product_name WHERE product_id=?", (pid,))
            con.execute("DELETE FROM product_component WHERE product_id=?", (pid,))
            con.execute("DELETE FROM corroboration WHERE product_id=?", (pid,))
            con.execute("DELETE FROM product WHERE product_id=?", (pid,))
            out["products"] += 1
            for key in keys:
                left = con.execute("SELECT COUNT(*) FROM product_name WHERE key_id=?", (key,)).fetchone()[0]
                if left == 0:
                    con.execute("DELETE FROM name_variant WHERE key_id=?", (key,))
                    con.execute("DELETE FROM name_key WHERE key_id=?", (key,))
                    out["name_keys"] += 1
        for vid in {v for e in entries for v in e.get("created_variants") or []}:
            left = con.execute("SELECT COUNT(*) FROM product_component WHERE variant_id=?",
                               (vid,)).fetchone()[0]
            if left == 0:
                con.execute("DELETE FROM variant WHERE variant_id=?", (vid,))
                out["variants"] += 1
        con.execute("DELETE FROM ingest_run WHERE run_id=?", (f"{SOURCE_ID}-{TODAY}",))
        con.commit()
        APPLIED.write_text(json.dumps(
            {"applied_at": payload.get("applied_at"), "source_id": SOURCE_ID,
             "count": 0, "entries": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        con.rollback()
        raise
    out["listed"] = len(entries)
    return dict(out)


def coverage(con: sqlite3.Connection, n: int) -> dict:
    total = con.execute("SELECT COUNT(*) FROM product WHERE country='ES'").fetchone()[0]
    comps = con.execute("""SELECT COUNT(*) FROM product p
        JOIN product_component pc ON pc.product_id=p.product_id WHERE p.country='ES'""").fetchone()[0]
    return {"es_products_before": total, "es_products_after": total + n, "es_components_now": comps}


def main() -> int:
    ap = argparse.ArgumentParser(description="ES CIMA 复方补全（默认 dry-run）")
    ap.add_argument("--build-candidates", action="store_true")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--include-partial", action="store_true",
                    help="也恢复部分映射的复方（只写已映射成分，产品 note 不加标记，风险见报告）")
    ap.add_argument("--allow-real", action="store_true")
    ap.add_argument("--sample", type=int, default=20)
    args = ap.parse_args()
    if args.build_candidates:
        return build_candidates()
    if sum([args.apply, args.dry_run, args.rollback]) > 1:
        ap.error("--apply / --dry-run / --rollback 互斥")
    real = (ROOT / "data" / "drugs.db").resolve()
    if (args.apply or args.rollback) and args.db.resolve() == real and not args.allow_real:
        raise SystemExit("拒绝写 data/drugs.db：本任务要求只在 .tmp/es-combos/ 副本验证；"
                         "Lead 批准后加 --allow-real。")

    con = connect(args.db, readonly=not (args.apply or args.rollback))
    if args.rollback:
        out = rollback(con)
        print(f"已回滚：{out.get('products', 0)} 个产品 / {out.get('name_keys', 0)} 个 name_key"
              f" / {out.get('variants', 0)} 个 variant（清单 {out.get('listed', 0)} 条）")
        con.close()
        return 0
    cands = load_candidates(args.include_partial)
    ok, skipped = check_state(con, cands)
    cov = coverage(con, len(ok))
    print("=== ES CIMA 复方补全 [%s] ===" % ("apply" if args.apply else "dry-run"))
    print(f"候选（coverage=all）：{len(cands):,}；可写：{len(ok):,}；跳过：{skipped}")
    print("按成分数：", dict(Counter(len(c["comps"]) for c in ok)))
    print(f"ES 产品：{cov['es_products_before']:,} → {cov['es_products_after']:,}；"
          f"ES 组件：{cov['es_components_now']:,} → {cov['es_components_now'] + sum(len(c['comps']) for c in ok):,}")
    print(f"抽样 {min(args.sample, len(ok))} 条：")
    for c in ok[: args.sample]:
        print(f"  {c['product_id']:<12} {c['n_activos']:>2}→{c['n_mapped']:>2}  "
              f"{c['nombre'][:38]:<40} {c['ing_en'][:40]}")
    if args.apply:
        written = apply_candidates(con, ok)
        print(f"已写库：{written.get('products', 0)} 个产品 / {written.get('components', 0)} 个成分（事务提交）")
    else:
        EVID.mkdir(parents=True, exist_ok=True)
        result = {"generated_at": TODAY, "candidates": len(cands), "writable": len(ok),
                  "skipped": skipped, "coverage": cov,
                  "by_n": dict(Counter(len(c["comps"]) for c in ok)),
                  "samples": [{k: c[k] for k in ("product_id", "nombre", "n_activos",
                                                 "n_mapped", "ing_en", "evidence_url")} for c in ok[: args.sample]],
                  "all": [{k: c[k] for k in ("product_id", "nombre", "n_activos", "n_mapped",
                                              "ing_en", "components_json", "evidence_url")} for c in ok]}
        (EVID / "es_combos_dryrun.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"dry-run 报告：{(EVID / 'es_combos_dryrun.json').relative_to(ROOT)}")
        print("（未写库；正式执行用 --apply --db <副本>）")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
