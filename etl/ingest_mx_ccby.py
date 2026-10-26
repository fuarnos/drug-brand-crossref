# -*- coding: utf-8 -*-
"""datos.gob.mx 4 个 CC-BY-4.0 采购数据集 → MX 浓度回填（默认 dry-run）。

背景
----
COFEPRIS 注册清单没有浓度列；现有 MX 浓度来自 ISSSTE 目录 + PROFECO 价格，
10,878 个 MX 产品里 3,123 个有浓度（28.7%）。本脚本把 fetch_mx_ccby.py 拉下来的
4 份公立机构采购明细解析成「(西语通用名归一, 剂型) → 浓度集合」字典，只给
**浓度为空的 MX 产品** 回填，规则保守：

  规则 1（严格）：通用名归一后前 2 个实词相同 + form_base 相同 + 该组浓度唯一。
  规则 2（放宽）：只看通用名（前 2 个实词），且仅限固体制剂 + 质量单位 + 浓度唯一。
                  液体制剂不套用（mg 与 mg/ml 不可比），与 ingest_mx.py 现有口径一致。

任何冲突（同组出现 >1 个浓度）一律不写；只填**单成分产品**（多成分产品无法把
同一个浓度安全分给每个成分）。已填过的组件跳过 → 可重复执行（幂等）。

来源怎么写
----------
`product.source_id` 是产品身份出处（COFEPRIS），不能覆盖；浓度出处按现有设计写
`corroboration`（source_type='provincial_list'，url=数据集页，verified_by=本脚本），
并在每轮写 `ingest_run` 一行统计。这四个数据集都是 CC-BY-4.0，需署名 + 修改声明。

用法：
    python etl/ingest_mx_ccby.py                     # 默认 dry-run，只读库
    python etl/ingest_mx_ccby.py --dry-run --sample 30
    python etl/ingest_mx_ccby.py --apply             # 真正写库（事务）
    python etl/ingest_mx_ccby.py --rollback          # 撤销本 ETL 写过的回填

dry-run 报告同时写到 .tmp/mx-atc/（JSON + TXT），供报告与人工核对引用。
"""

from __future__ import annotations

import argparse
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
from ingest_mx import SOLID_BASES, form_base_es, parse_strength  # noqa: E402  复用现有口径

DB = ROOT / "data" / "drugs.db"
CACHE = ROOT / "data" / "raw" / "mx" / "ccby"
EVID = ROOT / ".tmp" / "mx-atc"
TODAY = date.today().isoformat()
VERIFIED_BY = "etl/ingest_mx_ccby.py"

# 4 个数据集 → 落缓存的文件名。fetch 脚本会写 <key>.json（含 meta+records）。
DATASETS = {
    "inprfm": "INPRFM adquisicion_medicamentos_demanda",
    "hgmgg": "HGMGG medicamentos_productos_farmaceuticos_adquiridos_hgmgg",
    "iner": "INER entrada_medicamentos",
    "semar": "SEMAR adquisicion_insumos_salud",
}

# --- 名称归一 ---------------------------------------------------------------
FILLERS = {"de", "del", "la", "el", "los", "las", "y", "con", "para", "en"}
SALT_WORDS = {
    # 盐/酯/水合物/常见缩写：两边都去掉，才能让「Clorhidrato de ranitidina」对上「Ranitidina」
    "clorhidrato", "clor", "clorh", "hidrocloruro", "bromhidrato", "bromuro",
    "sodico", "sodica", "sodio", "potasico", "potasica", "potasio",
    "calcico", "calcica", "calcio", "magnesico", "magnesica", "magnesio",
    "citrato", "tartrato", "maleato", "fumarato", "mesilato", "besilato", "tosilato",
    "acetato", "propionato", "valerato", "succinato", "lactato", "gluconato",
    "carbonato", "bicarbonato", "nitrato", "cloruro", "fosfato", "sulfato",
    "dihidrato", "trihidratado", "hemihidratado", "monohidrato", "anhidro", "hidratado",
    "acido", "sal", "base", "rac", "levogiro", "levogira",
}
RE_NONALNUM = re.compile(r"[^a-z0-9]+")
RE_TRAILING_FORM = re.compile(
    r"\b(sol|solucion|solucion\s+inyectable|tableta|tabletas|comprimido|comprimidos|"
    r"capsula|capsulas|ampolleta|ampolletas|inyectable|suspension|susp|jarabe|gotas|"
    r"polvo|crema|unguento|pomada|parche|supositorio|ovulo|inhalador|aerosol|"
    r"tab|tabs|caps|cap|amp|iv|i\.v|im|i\.m)\b.*$", re.I)


def fix_mojibake(s: str) -> str:
    """HGMGG 的 CKAN 字符串是双重编码（UTF-8 字节被当 Latin-1 解码）。"""
    if not s or ("Ã" not in s and "Â" not in s):
        return s or ""
    try:
        return s.encode("latin-1", "strict").decode("utf-8", "strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def norm_text(s: str) -> str:
    """去重音、小写、标点→空格（与 ingest_mx.key 同口径）。"""
    s = "".join(c for c in unicodedata.normalize("NFD", fix_mojibake(s))
                if not unicodedata.combining(c)).lower()
    s = RE_NONALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def base_tokens(generic: str) -> list[str]:
    toks = [t for t in norm_text(generic).split() if t not in FILLERS]
    stripped = [t for t in toks if t not in SALT_WORDS]
    return stripped if stripped else toks


def name_key(generic: str) -> str:
    """通用名归一后取前 2 个实词（去盐/去填充词后）。"""
    return " ".join(base_tokens(generic)[:2])


# --- 浓度解析 ---------------------------------------------------------------
NUM = r"\d{1,3}(?:[ .]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
# µg / μg 在源数据里大量出现（U+00B5 / U+03BC），统一按 mcg 处理。
RE_CONC = re.compile(
    rf"({NUM})\s*(mcg|mg|kg|g|gr|ml|l|ui|iu|%|µg|μg|ug)(?![a-z])", re.I)
UNIT_FIX = {"ui": "iu", "iu": "iu", "l": "ml", "ug": "mcg", "µg": "mcg",
            "μg": "mcg", "gr": "g"}


def parse_conc(text: str) -> tuple[float, str] | None:
    if not text:
        return None
    m = RE_CONC.search(fix_mojibake(text))
    if not m:
        return None
    raw = m.group(1).strip()
    if re.search(r"[ .]\d{3}", raw):          # 千分位：600 000 → 600000
        raw = raw.replace(" ", "").replace(".", "")
    try:
        val = float(raw.replace(",", "."))
    except ValueError:
        return None
    if val <= 0:
        return None
    unit = UNIT_FIX.get(m.group(2).lower(), m.group(2).lower())
    return val, unit


def canonical(st: tuple[float, str]) -> tuple[float, str]:
    """唯一性判定用规范单位：质量统一到 mg，其余原样。"""
    val, unit = st
    if unit == "g":
        return round(val * 1000.0, 6), "mg"
    if unit == "kg":
        return round(val * 1_000_000.0, 6), "mg"
    if unit == "mcg":
        return round(val / 1000.0, 6), "mg"
    return round(val, 6), unit


def represent(canon: tuple[float, str]) -> tuple[float, str]:
    """回写用表示：整数克写成 g（与现有 MX 数据 174 条 g 一致），其余 mg。"""
    val, unit = canon
    if unit == "mg" and val >= 1000 and val % 1000 == 0:
        return val / 1000.0, "g"
    return val, unit


# --- 各数据集解析 -----------------------------------------------------------
FORM_ABBREV = (
    ("injection", r"\b(i\.?v|i\.?m|inyect|amp|ampolleta|infusion|intravenos)"),
    ("tablet", r"\b(tab|tabs|tableta|comprimido|gragea)"),
    ("capsule", r"\b(caps|capsula)"),
    ("powder", r"\b(polvo|granulado|sobre|sachet)"),
    ("topical", r"\b(crema|ung|pomada|gel|locion|parche)"),
    ("suppository", r"\b(supos|ovulo)"),
    ("inhalation", r"\b(inhal|aerosol)"),
    ("liquid", r"\b(sol|solucion|susp|jarabe|gotas|elixir|emulsion|liquido)"),
)


def form_of(text: str) -> str:
    f = form_base_es(fix_mojibake(text))
    known = {"tablet", "capsule", "injection", "topical", "inhalation",
             "suppository", "powder", "liquid"}
    if f in known:
        return f
    low = norm_text(text)
    for base, pat in FORM_ABBREV:
        if re.search(pat, low):
            return base
    return "unknown"


def clean_generic(generic: str) -> str:
    """去掉通用名里混进来的剂型短语；复方（y / 、 / 中点）在调用处过滤。"""
    g = fix_mojibake(generic or "").strip(" .;,-")
    parts = [p.strip() for p in re.split(r"[.;]", g) if p.strip()]
    g = parts[0] if parts else g
    g = RE_TRAILING_FORM.sub("", g).strip(" .;,-")
    return g


def is_combo(generic: str) -> bool:
    t = norm_text(generic)
    return bool(re.search(r"\s+y\s+|\s+con\s+|\+", t)) or "/" in (generic or "")


def parse_inprfm(rec: dict) -> tuple[str, str, tuple[float, str]] | None:
    """最规整的一份：sus_activ / forma_farma / cntcn 都是独立字段。"""
    generic = clean_generic(rec.get("sus_activ") or rec.get("cncpt") or "")
    st = parse_conc(rec.get("cntcn") or "")
    if not generic or not st:
        return None
    return generic, form_of(rec.get("forma_farma") or ""), st


def parse_iner(rec: dict) -> tuple[str, str, tuple[float, str]] | None:
    """descripcion 形如「clorhidrato de ranitidina 150 mg. tab.」/「paracetamol 500 mg.」。"""
    desc = fix_mojibake(rec.get("descripcion") or "")
    m = re.search(rf"{NUM}\s*(mg|mcg|g|kg|ml|l|ui|iu|%)", desc, re.I)
    if not m:
        return None
    generic = clean_generic(desc[: m.start()])
    st = parse_conc(desc)
    if not generic or not st:
        return None
    return generic, form_of(desc), st


def parse_semar(rec: dict) -> tuple[str, str, tuple[float, str]] | None:
    """「GENERIC. FORM. CADA ... CONTIENE: ... X MG ...」全大写描述。"""
    desc = fix_mojibake(rec.get("descripcion_insumo") or "")
    parts = [p.strip() for p in desc.split(".") if p.strip()]
    if not parts:
        return None
    generic = clean_generic(parts[0])
    form = form_of(desc)                      # 剂型可能写在第 1 句（"X solución inyectable."）
    # 浓度优先取「CONTIENE:」之后的第一处（避免把包装数量当浓度）
    idx = desc.upper().find("CONTIENE")
    st = parse_conc(desc[idx:] if idx >= 0 else desc)
    if not generic or not st:
        return None
    return generic, form, st


def parse_hgmgg(rec: dict) -> tuple[str, str, tuple[float, str]] | None:
    """「Caseinato de calcio. Polvo. cada ... contiene: ... X g. Envase...」。"""
    desc = fix_mojibake(rec.get("descripcion") or "")
    parts = [p.strip() for p in desc.split(".") if p.strip()]
    if len(parts) < 2:
        return None
    generic = clean_generic(parts[0])
    form = form_of(parts[1])
    idx = desc.lower().find("contiene")
    st = parse_conc(desc[idx:] if idx >= 0 else ".".join(parts[2:]))
    if not generic or not st:
        return None
    return generic, form, st


PARSERS = {"inprfm": parse_inprfm, "iner": parse_iner,
           "semar": parse_semar, "hgmgg": parse_hgmgg}


def load_entries() -> tuple[list[dict], dict]:
    """读 4 个缓存 → 解析后的条目列表 + 每集统计。"""
    entries: list[dict] = []
    stats: dict[str, dict] = {}
    for key in DATASETS:
        path = CACHE / f"{key}.json"
        st = {"rows": 0, "parsed": 0, "skip_noconc": 0, "skip_nogeneric": 0,
              "skip_combo": 0, "file": path.name}
        if not path.exists():
            st["missing"] = True
            stats[key] = st
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("meta") or {}
        st.update({"title": meta.get("title"), "license": meta.get("license"),
                   "dataset_url": meta.get("dataset_url"),
                   "retrieved_at": meta.get("retrieved_at")})
        for rec in payload.get("records") or []:
            st["rows"] += 1
            parsed = PARSERS[key](rec)
            if parsed is None:
                if not parse_conc(json.dumps(rec, ensure_ascii=False)):
                    st["skip_noconc"] += 1
                else:
                    st["skip_nogeneric"] += 1
                continue
            generic, form, strength = parsed
            if is_combo(generic):
                st["skip_combo"] += 1
                continue
            nk = name_key(generic)
            if len(nk) < 3:
                st["skip_nogeneric"] += 1
                continue
            st["parsed"] += 1
            entries.append({"dataset": key, "generic": generic, "name_key": nk,
                            "form": form, "strength": strength})
        stats[key] = st
    return entries, stats


# --- 字典 -------------------------------------------------------------------
class StrengthDict:
    def __init__(self) -> None:
        # (name_key, form) -> canon -> {dataset,...}
        self.strict: dict[tuple[str, str], dict[tuple[float, str], set[str]]] = \
            defaultdict(lambda: defaultdict(set))
        self.relaxed: dict[str, dict[tuple[float, str], set[str]]] = \
            defaultdict(lambda: defaultdict(set))
        self.forms_by_name: dict[str, set[str]] = defaultdict(set)

    def add(self, e: dict) -> None:
        c = canonical(e["strength"])
        self.strict[(e["name_key"], e["form"])][c].add(e["dataset"])
        self.relaxed[e["name_key"]][c].add(e["dataset"])
        self.forms_by_name[e["name_key"]].add(e["form"])

    def strict_hit(self, nk: str, form: str):
        cand = self.strict.get((nk, form))
        if not cand or len(cand) != 1:
            return None, (len(cand) if cand else 0)
        return next(iter(cand)), 1

    def relaxed_hit(self, nk: str):
        cand = self.relaxed.get(nk)
        if not cand or len(cand) != 1:
            return None, (len(cand) if cand else 0)
        return next(iter(cand)), 1


# --- 数据库 -----------------------------------------------------------------
def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def load_mx_gaps(db: sqlite3.Connection) -> tuple[list[dict], dict]:
    """浓度全空的 MX 单成分产品 + 其西语通用名（name_type='inn'）。"""
    base = dict(db.execute(
        "SELECT COUNT(*) AS products,"
        " SUM(CASE WHEN EXISTS(SELECT 1 FROM product_component pc WHERE"
        "   pc.product_id=p.product_id AND pc.strength_value IS NOT NULL)"
        "   THEN 1 ELSE 0 END) AS with_strength,"
        " SUM(CASE WHEN NOT EXISTS(SELECT 1 FROM product_component pc WHERE"
        "   pc.product_id=p.product_id AND pc.strength_value IS NOT NULL)"
        "   THEN 1 ELSE 0 END) AS gap_products"
        " FROM product p WHERE p.country='MX'").fetchone())
    comp = dict(db.execute(
        "SELECT COUNT(*) AS components,"
        " SUM(CASE WHEN pc.strength_value IS NOT NULL THEN 1 ELSE 0 END) AS with_strength"
        " FROM product_component pc JOIN product p ON p.product_id=pc.product_id"
        " WHERE p.country='MX'").fetchone())

    rows = db.execute("""
        SELECT p.product_id, p.dosage_form, p.form_base, p.dosage_form AS form_raw,
               nv.raw AS inn_raw
        FROM product p
        JOIN product_component pc ON pc.product_id = p.product_id
        JOIN product_name pn ON pn.product_id = p.product_id AND pn.name_type = 'inn'
        JOIN name_variant nv ON nv.key_id = pn.key_id
        WHERE p.country = 'MX'
          AND pc.strength_value IS NULL
          AND (SELECT COUNT(*) FROM product_component pc2
               WHERE pc2.product_id = p.product_id) = 1
        """).fetchall()
    by_product: dict[str, dict] = {}
    for r in rows:
        p = by_product.setdefault(r["product_id"], {
            "product_id": r["product_id"], "dosage_form": r["dosage_form"],
            "form_base": r["form_base"], "names": [],
        })
        if r["inn_raw"] not in p["names"]:
            p["names"].append(r["inn_raw"])
    return list(by_product.values()), {"products": base, "components": comp,
                                      "gap_candidates": len(by_product)}


# --- 匹配 -------------------------------------------------------------------
def match_products(candidates: list[dict], sd: StrengthDict) -> tuple[list[dict], dict]:
    fills: list[dict] = []
    stats: Counter = Counter()
    conflicts: list[dict] = []
    for p in candidates:
        keys = {name_key(n) for n in p["names"] if n}
        keys = {k for k in keys if len(k) >= 3}
        if not keys:
            stats["skip_noname"] += 1
            continue
        hit = None
        nk_hit = None
        for nk in sorted(keys):
            cand, n = sd.strict_hit(nk, p["form_base"])
            if cand is not None:
                hit, nk_hit = cand, nk
                break
            if n > 1:
                stats["conflict_strict"] += 1
                if len(conflicts) < 40:
                    conflicts.append({"product_id": p["product_id"], "inn": p["names"][0],
                                      "name_key": nk, "form": p["form_base"], "rule": "strict",
                                      "strengths": sorted(str(represent(c))
                                                          for c in sd.strict[(nk, p["form_base"])])})
        if hit is not None:
            fills.append({"product_id": p["product_id"], "inn": p["names"][0],
                          "dosage_form": p["dosage_form"], "form_base": p["form_base"],
                          "name_key": nk_hit, "strength": represent(hit),
                          "datasets": sorted(sd.strict[(nk_hit, p["form_base"])][hit]),
                          "rule": "name2+form"})
            stats["fill_strict"] += 1
            continue

        # 放宽：只看通用名 + 唯一；仅固体制剂 + 质量单位（与 ingest_mx 现有口径一致）
        if p["form_base"] not in SOLID_BASES:
            stats["skip_relaxed_non_solid"] += 1
            continue
        for nk in sorted(keys):
            cand, n = sd.relaxed_hit(nk)
            if cand is None:
                if n > 1:
                    stats["conflict_relaxed"] += 1
                continue
            if cand[1] not in {"mg", "g", "mcg"}:
                stats["skip_relaxed_unit"] += 1
                continue
            hit, nk_hit = cand, nk
            break
        if hit is not None:
            fills.append({"product_id": p["product_id"], "inn": p["names"][0],
                          "dosage_form": p["dosage_form"], "form_base": p["form_base"],
                          "name_key": nk_hit, "strength": represent(hit),
                          "datasets": sorted(sd.relaxed[nk_hit][hit]),
                          "rule": "name2"})
            stats["fill_relaxed"] += 1
        else:
            stats["no_match"] += 1
    return fills, {"stats": dict(stats), "conflicts": conflicts}


# --- dry-run 报告 -----------------------------------------------------------
def coverage_rows(db: sqlite3.Connection, n_fill: int) -> dict:
    base = db.execute(
        "SELECT COUNT(*) AS products,"
        " SUM(CASE WHEN EXISTS(SELECT 1 FROM product_component pc WHERE"
        "   pc.product_id=p.product_id AND pc.strength_value IS NOT NULL)"
        "   THEN 1 ELSE 0 END) AS with_strength"
        " FROM product p WHERE p.country='MX'").fetchone()
    comp = db.execute(
        "SELECT COUNT(*) AS components,"
        " SUM(CASE WHEN pc.strength_value IS NOT NULL THEN 1 ELSE 0 END) AS with_strength"
        " FROM product_component pc JOIN product p ON p.product_id=pc.product_id"
        " WHERE p.country='MX'").fetchone()
    total_p, with_p = base["products"], base["with_strength"] or 0
    total_c, with_c = comp["components"], comp["with_strength"] or 0
    return {
        "products_total": total_p, "products_with_strength": with_p,
        "products_after": with_p + n_fill,
        "product_coverage_before": round(100.0 * with_p / max(1, total_p), 1),
        "product_coverage_after": round(100.0 * (with_p + n_fill) / max(1, total_p), 1),
        "components_total": total_c, "components_with_strength": with_c,
        "components_after": with_c + n_fill,
        "component_coverage_before": round(100.0 * with_c / max(1, total_c), 1),
        "component_coverage_after": round(100.0 * (with_c + n_fill) / max(1, total_c), 1),
    }


def write_dryrun_report(result: dict, outdir: Path) -> tuple[Path, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    js = outdir / "mx_ccby_dryrun.json"
    js.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines: list[str] = []
    w = lines.append
    w("# MX 浓度回填 dry-run（etl/ingest_mx_ccby.py）")
    w(f"\n生成时间：{result['generated_at']}   数据库：{result['db']}")
    w("\n## 数据集解析")
    w("| 数据集 | 行数 | 解析出浓度条目 | 无浓度 | 复方跳过 | 缓存 |")
    w("|---|---:|---:|---:|---:|---|")
    for key, st in result["datasets"].items():
        w(f"| {key} | {st['rows']:,} | {st['parsed']:,} | {st['skip_noconc']:,} | "
          f"{st['skip_combo']:,} | {'缺' if st.get('missing') else '有'} |")
    w("\n## 字典")
    for k, v in result["dict"].items():
        w(f"- {k}: {v:,}")
    w("\n## MX 缺口与可回填")
    g = result["gap"]
    w(f"- MX 产品 {g['products']['products']:,}，有浓度 {g['products']['with_strength']:,}"
      f"（{result['coverage']['product_coverage_before']}%），缺口产品 {g['products']['gap_products']:,}")
    w(f"- 单成分 + 全空 + 有西语通用名候选：{g['gap_candidates']:,}")
    s = result["match"]["stats"]
    w(f"- 严格规则可回填：{s.get('fill_strict', 0):,}")
    w(f"- 放宽规则可回填：{s.get('fill_relaxed', 0):,}")
    w(f"- **合计可回填产品/组件：{result['totals']['fills']:,}**"
      f"（本轮 dry-run 不写库）")
    w(f"- 冲突未写：strict {s.get('conflict_strict', 0):,} / relaxed {s.get('conflict_relaxed', 0):,}")
    w("\n## 覆盖率预估")
    c = result["coverage"]
    w(f"- 产品级：{c['product_coverage_before']}% → **{c['product_coverage_after']}%**"
      f"（{c['products_with_strength']:,} → {c['products_after']:,} / {c['products_total']:,}）")
    w(f"- 组件级：{c['component_coverage_before']}% → **{c['component_coverage_after']}%**"
      f"（{c['components_with_strength']:,} → {c['components_after']:,} / {c['components_total']:,}）")
    w("\n## 抽样 20 条待回填")
    w("| # | product_id | 西语通用名 | 剂型 | 回填浓度 | 来源数据集 | 规则 |")
    w("|---:|---|---|---|---|---|---|")
    for i, f in enumerate(result["samples"], 1):
        v, u = f["strength"]
        w(f"| {i} | {f['product_id']} | {f['inn']} | {f['dosage_form']} | {v:g} {u} | "
          f"{','.join(f['datasets'])} | {f['rule']} |")
    w("\n## 冲突样例（未写入）")
    for cf in result["conflicts"][:10]:
        w(f"- {cf['product_id']} {cf['inn']} → {cf['rule']} 组 {cf['name_key']}"
          f"/{cf['form']}: {', '.join(cf['strengths'])}")
    txt = outdir / "mx_ccby_dryrun.txt"
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return js, txt


# --- apply / rollback -------------------------------------------------------
def register_sources(db: sqlite3.Connection, stats: dict) -> None:
    for key, st in stats.items():
        if st.get("missing"):
            continue
        db.execute(
            "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
            " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
            (f"{key}_ccby", f"{st.get('title') or DATASETS[key]}",
             st.get("dataset_url"), "CC BY 4.0",
             "https://creativecommons.org/licenses/by/4.0/",
             TODAY, "datos.gob.mx CKAN 采购明细；用于通用名级浓度回填（改编）。"))


def apply_fills(db: sqlite3.Connection, fills: list[dict], stats: dict,
                dict_stats: dict) -> dict:
    written = Counter()
    try:
        register_sources(db, stats)
        for f in fills:
            v, u = f["strength"]
            cur = db.execute(
                "UPDATE product_component SET strength_value=?, strength_unit=?"
                " WHERE product_id=? AND ord=0 AND strength_value IS NULL", (v, u, f["product_id"]))
            if cur.rowcount != 1:
                written["skip_race"] += 1
                continue
            written["components"] += 1
            for key in f["datasets"]:
                db.execute(
                    "INSERT OR IGNORE INTO corroboration (product_id, source_type, url,"
                    " retrieved_at, verified_by, note) VALUES (?,?,?,?,?,?)",
                    (f["product_id"], "provincial_list", f"ccby:{key}", TODAY,
                     VERIFIED_BY, f"浓度回填自 mx_ccby:{key}"))
            written["products"] += 1
        note = json.dumps({"fills": len(fills), "written": dict(written),
                           "rule": dict(Counter(f["rule"] for f in fills)),
                           "stats": dict_stats}, ensure_ascii=False)
        db.execute(
            "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
            " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"mx_ccby-{TODAY}", "inprfm_ccby", TODAY, TODAY,
             sum(s["rows"] for s in stats.values()), written["components"], 0, "ok", note))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return dict(written)


def rollback(db: sqlite3.Connection) -> dict:
    pids = [r[0] for r in db.execute(
        "SELECT DISTINCT product_id FROM corroboration WHERE verified_by=?", (VERIFIED_BY,))]
    n_comp = 0
    try:
        for pid in pids:
            cur = db.execute(
                "UPDATE product_component SET strength_value=NULL, strength_unit=NULL"
                " WHERE product_id=? AND strength_value IS NOT NULL AND ord=0", (pid,))
            n_comp += cur.rowcount
        n_corr = db.execute("DELETE FROM corroboration WHERE verified_by=?", (VERIFIED_BY,)).rowcount
        db.execute("DELETE FROM ingest_run WHERE run_id=?", (f"mx_ccby-{TODAY}",))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"products": len(pids), "components": n_comp, "corroboration_rows": n_corr}


def main() -> int:
    ap = argparse.ArgumentParser(description="MX 浓度回填 ETL（default dry-run）")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--apply", action="store_true", help="写库（默认只 dry-run）")
    ap.add_argument("--dry-run", action="store_true", help="显式 dry-run（默认行为）")
    ap.add_argument("--rollback", action="store_true", help="撤销本 ETL 写过的回填")
    ap.add_argument("--sample", type=int, default=20)
    args = ap.parse_args()
    if args.apply and args.dry_run:
        ap.error("--apply 与 --dry-run 互斥")

    db = connect(args.db, readonly=not (args.apply or args.rollback))
    if args.rollback:
        out = rollback(db)
        print(f"已回滚：产品 {out['products']:,} 个，组件 {out['components']:,} 个，"
              f"corroboration {out['corroboration_rows']:,} 行")
        db.close()
        return 0

    entries, dstats = load_entries()
    if not entries:
        print("缓存为空：先运行 python etl/fetch_mx_ccby.py --download")
        db.close()
        return 1
    sd = StrengthDict()
    for e in entries:
        sd.add(e)

    candidates, gap = load_mx_gaps(db)
    fills, mres = match_products(candidates, sd)
    cover = coverage_rows(db, len(fills))
    rules = Counter(f["rule"] for f in fills)
    ds_count = Counter(d for f in fills for d in f["datasets"])
    result = {
        "generated_at": TODAY, "db": str(args.db), "mode": "apply" if args.apply else "dry-run",
        "datasets": dstats,
        "dict": {"strict_groups": len(sd.strict), "relaxed_names": len(sd.relaxed),
                 "parsed_entries": len(entries)},
        "gap": gap,
        "match": mres,
        "totals": {"fills": len(fills), "by_rule": dict(rules),
                   "by_dataset": dict(ds_count)},
        "coverage": cover,
        "samples": [dict(f) for f in fills[: args.sample]],
        "all_fills": [dict(f) for f in fills],
        "conflicts": mres["conflicts"],
    }

    # 缓存元信息
    meta_path = CACHE / "meta.json"
    if meta_path.exists():
        result["cache_meta"] = json.loads(meta_path.read_text(encoding="utf-8"))

    print(f"=== MX CC-BY 浓度回填 [{result['mode']}] ===")
    for key, st in dstats.items():
        print(f"  {key:<7} 行 {st['rows']:>5,}  解析 {st['parsed']:>5,}  "
              f"无浓度 {st['skip_noconc']:>3,}  复方跳过 {st['skip_combo']:>3,}"
              f"  {'[缺缓存]' if st.get('missing') else ''}")
    print(f"字典：strict 组 {len(sd.strict):,}，通用名 {len(sd.relaxed):,}")
    print(f"单成分空浓度候选 {gap['gap_candidates']:,}；"
          f"严格 {rules.get('name2+form', 0):,} + 放宽 {rules.get('name2', 0):,}"
          f" = 可回填 {len(fills):,} 个产品/组件")
    print(f"覆盖率：产品 {cover['product_coverage_before']}% → "
          f"{cover['product_coverage_after']}%；组件 {cover['component_coverage_before']}% → "
          f"{cover['component_coverage_after']}%")
    print("抽样 20 条：")
    for f in fills[:20]:
        v, u = f["strength"]
        print(f"  {f['product_id']:<14} {f['inn'][:32]:<34} {f['dosage_form'][:18]:<20} "
              f"{v:g} {u:<4} [{f['rule']}] {','.join(f['datasets'])}")
    for cf in mres["conflicts"][:5]:
        print(f"  冲突 {cf['product_id']} {cf['inn']} → {cf['rule']} "
              f"{cf['name_key']}/{cf['form']}: {', '.join(cf['strengths'])}")

    if args.apply:
        written = apply_fills(db, fills, dstats, {"fills": len(fills), "rules": dict(rules)})
        print(f"已写库：产品 {written.get('products', 0):,}，组件 "
              f"{written.get('components', 0):,}（事务提交）")
    else:
        js, txt = write_dryrun_report(result, EVID)
        print(f"dry-run 报告：{js.relative_to(ROOT)}  {txt.relative_to(ROOT)}")
        print("（未写 data/drugs.db；正式执行用 --apply）")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
