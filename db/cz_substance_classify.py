# -*- coding: utf-8 -*-
"""CZ 908 个新成分（`substance.source_id='sukl_dlp'`）的实体类型分类落地 + 合并候选 + WHO 复核。

只读
----
`data/drugs.db` 一律用 sqlite3 URI `mode=ro` 打开；脚本**不写库**（不 ALTER / 不 INSERT /
不 UPDATE / 不 VACUUM）。只读 `data/entity_type.csv`、`data/who_inn_names.csv`；
只写 `data/sources/` 下的派生 CSV，以及（加 `--merge-into-entity-type` 时）把 908 行
并入 `data/entity_type.csv`。

产物
----
1. `data/sources/entity_type_cz_20261117.csv` — 908 行分类，每条带 rule / confidence /
   evidence（命中的词或稀释度、命中的 WHO 名录项），判不了的 entity_type 留空并计数；
2. `data/sources/cz_substance_merge_20261117.csv` — 3 条**确定性**合并候选（去性状限定词后
   与库内既有成分同名），列含影响 product / product_component / variant 行数与可复现 SQL；
3. `data/sources/cz_likely_inn_who_review_20261117.csv` — 192 个「疑似 INN」逐条 WHO 复核
   （精确 / 去盐 / 去酯 / 母体 INN + 盐酯尾词四档），确认不了的标「未确认」。

口径
----
分类规则沿用 `reports/2026-11-16-cz-substance-quality.md` §5（有序，先命中先生效）：
顺势稀释度 → 顺势字样 → 疫苗词 → WHO 名录 → 库内同名 → 生药词 → 辅料词 → INN 词形 → 其余。
`entity_type` 取值只用 `etl/classify_entity_type.py` 的现有词表
（inn_drug / biologic / herbal / homeopathic / material / other），细分信息放 `rule`。

用法
----
    python db/cz_substance_classify.py                      # 只出 3 个派生 CSV + 统计
    python db/cz_substance_classify.py --merge-into-entity-type   # 再并入 data/entity_type.csv（幂等）
    python db/cz_substance_classify.py --check                    # 只核对覆盖/分布，不写文件
    python db/cz_substance_classify.py --check --entity-csv "git:HEAD:data/entity_type.csv"  # 追加前快照
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))
import cz  # noqa: E402  （复用 norm_inn / strip_salt / load_who_inn，保证与入库同一套归一）

DB = ROOT / "data" / "drugs.db"
ENTITY_CSV = ROOT / "data" / "entity_type.csv"
WHO_CSV = ROOT / "data" / "who_inn_names.csv"
SOURCES = ROOT / "data" / "sources"
OUT_ENTITY = SOURCES / "entity_type_cz_20261117.csv"
OUT_MERGE = SOURCES / "cz_substance_merge_20261117.csv"
OUT_REVIEW = SOURCES / "cz_likely_inn_who_review_20261117.csv"

# entity_type.csv 的固定列（与 etl/classify_entity_type.py 写出的表头一致）
ENTITY_FIELDS = ["substance_id", "entity_type", "rule", "confidence", "evidence",
                 "n_products", "markets", "with_atc"]

# ---- 分类规则（与报告 §5 同序，先命中先生效）----------------------------------
RE_HOMEOPATHIC_DILUTION = re.compile(r"\b\d{1,3}\s*(?:C|CH|D|DH|LM|LMK|MK|X)\b", re.I)
HOMEOPATHIC_WORDS = ("DILUTIO", "HOMEOPATH", "DILUTION")
VACCINE_WORDS = ("VIRUS", "VACCINE", "VACCINUM", "TOXOID", "INACTIVATED", "SEROTYPE",
                 "POLYSACCHARIDE", "ANTIGEN", "ANATOXIN", "BACTERIN")
HERBAL_WORDS = ("HERBA", "RADIX", "FOLIUM", "FLOS", "FRUCTUS", "SEMEN", "CORTEX",
                "RHIZOMA", "TINCTURA", "EXTRACT", "LEAF", "ROOT", "FRUIT", "HERB",
                "FLOWER", "BARK", "SEED", "POLLEN", "RESINA", "SUCCUS", "OLEUM",
                "DRIED", "POWDER", "PLANT", "LACTUCA", "PULSATILLA", "ARNICA",
                "BELLADONNA", "CHAMOMILLA")
EXCIPIENT_WORDS = ("OIL", "SOLUTION", "WATER", "ALCOHOL", "PARAFFIN", "GLYCOL", "WAX",
                   "GELATIN", "LACTOSE", "STARCH", "CELLULOSE", "TALC", "SILICA",
                   "GLACIAL", "ANHYDROUS", "PURIFIED", "CONCENTRATE", "MEDIUM-CHAIN",
                   "TRIGLYCERID", "REFINED", "EMULSION", "SUSPENSION", "SYRUP", "SUGAR",
                   "SODIUM CHLORIDE", "GLUCOSE", "MALTODEXTRIN", "SORBITOL", "ETHANOL")
# 词形启发（**不是**权威判定，只用来把「其它」再拆一层，结论一律「未确认」）
RE_INN_SHAPE = re.compile(
    r"(INE|OL|MYCIN|CIN|STAT|MAB|NIB|TINIB|PRIL|SARTAN|OLOL|AZEPAM|PRAZOLE|CILLIN|"
    r"CYCLINE|OXACIN|CONAZOLE|VIR|ADREN|AMINE|AMIDE|ACID|ATE|IDE|IUM|ANE|ENE|ONE|OSE|"
    r"ASE|LIN|GEL|TIDINE|TRIPTAN|GLIPTIN|GLIFLOZIN|PARIN|POIETIN|KIN|ALPHA|BETA)$")

# 盐 / 酯 / 水合物 / 溶剂化物 / 成盐酸（用于「母体 INN + 尾词」复核，可逐条复核）
SALT_TAILS = set("""
acetate acetylsalicylate adipate alginate amsonate aspartate benzoate besilate
bicarbonate bisulfate bitartrate bromide butyrate carbonate chloride citrate
clathrate cypionate decanoate diacetate dichloride dihydrochloride dihydrate
dinitrate diphosphate dipropionate disodium disulfate ditartrate ditosilate
dodecahydrate edisylate enantate enanthate esylate ethanedisulfonate ethylsuccinate
fendizoate fumarate furoate gluconate glutamate glutarate glycolate hemifumarate
hemihydrate hemiheptahydrate hemitartrate heptahydrate hexahydrate hippurate
hyclate hydrobromide hydrochloride hydroiodide hydroxide iodide isethionate
isopropylcarbonate lactobionate lactate laurate malate maleate malonate mandelate
mesilate mesylate methanesulfonate methylsulfate monofumarate monohydrate
monohydrochloride monosodium naphthalenedisulfonate napsilate nitrate octahydrate
oleate orotate oxalate oxide palmitate pamoate pantothenate pentahydrate
phenpropionate phenylpropionate phosphate pidolate pivalate potassium probenecid
propionate salicylate sesquihydrate sodium solvate stearate succinate sulfate
sulphate sulphide sulphite tartrate tebutate terephthalate tetrahydrate thiocyanate
tosilate tosylate trichloride trihemihydrate trihydrate trinitrate undecylenate
valerate xinafoate zinc ammonium lithium calcium magnesium trometamol meglumine
""".split())
SALT_MULTIPLIERS = ("di", "tri", "tetra", "penta", "hexa", "hepta", "octa", "deca",
                    "hemi", "mono", "sesqui", "per")
SALT_ACIDS = set("acid pidolic fumaric maleic succinic citric tartaric malic lactic "
                 "benzoic acetic salicylic phosphoric sulfuric nitric hydrochloric".split())
COMBO_WORDS = {"and", "with", "plus"}

# 词表误命中复核：命中词是「状态 / 剂型 / 复方 / 同位素」写法而不是实体类别时，
# **留空 + 计数**，不硬套类别（生药桶 60、辅料桶 20 里各有若干这种）。
HERBAL_FALSE_POSITIVE = (
    (re.compile(r"ESCHERICHIA|LACTOBACILLUS|SACCHAROMYCES|BACTERIAL|LYSATE|PROBIOTIC", re.I),
     "微生物/益生菌写法"),
    (re.compile(r"^\s*(?:FERROUS|FERRIC|CALCIUM|SODIUM|POTASSIUM|MAGNESIUM|ZINC)\b", re.I),
     "矿物/金属盐写法"),
    (re.compile(r"\bALLERGEN", re.I), "变应原提取物写法"),
    (re.compile(r"PANCREAS|ENZYME", re.I), "酶/脏器粉写法"),
    (re.compile(r"\b(?:C|CH|D|DH|LM|MK|X)\s+\d{1,3}\b"), "顺势度标写法（字母在数字前）"),
)
EXCIPIENT_FALSE_POSITIVE = (
    (re.compile(r"\b\d{1,3}m?(?:F|Ga|Y|Lu|In|Tc|Tl|Sm|Ra|Ge|C|N|O|Rb|Zr|I|Cu|Ac|Pb|Bi|"
                r"Cr|Co|Se|Pd|Yb|Ir|Au|P|Sr|Re|Ho|Dy|Ru)\b"), "放射性核素标记"),
    (re.compile(r"\bAND\b", re.I), "复方/共处理连接词"),
    (re.compile(r"COATED WITH", re.I), "包衣写法"),
    (re.compile(r"\bSOLVATE\b|\bETHANOLATE\b|\bCLATHRATE\b", re.I), "溶剂化物/包合物写法"),
    (re.compile(r"TRITURATION", re.I), "研磨稀释写法"),
    (re.compile(r"WITH STARCH|WITH CELLULOSE", re.I), "共处理写法"),
    (re.compile(r"\bSYRUP\b", re.I), "剂型词 Syrup"),
    (re.compile(r"PURIFIED PROTEIN DERIVATIVE", re.I), "诊断用蛋白衍生物"),
)

# 合并候选：能去掉的「性状/剂型」限定词（**不含**盐/酯词，避免把 ferrous sulfate 削成 ferrous）
QUALIFIER_SUFFIXES = (" glaciale", " glacial", " anhydrous", " refined", " dried",
                      " purified", " powder", " micronized", " concentrate", " solution",
                      " oil", " bases", " base")

REPORT_CATEGORY = {
    "homeopathic_dilution_number": "顺势/稀释写法·数字稀释度",
    "homeopathic_dilutio_word": "顺势/稀释写法·Dilutio 字样",
    "vaccine_antigen": "疫苗株/生物抗原",
    "who_inn_exact": "真实 INN（WHO 名录命中）",
    "existing_inn": "真实 INN（库内已有同名实体）",
    "botanical": "生药/植物（含提取物）",
    "botanical_ambiguous": "生药/植物·词表误命中（留空待人工）",
    "excipient": "辅料/溶剂/化学品",
    "excipient_ambiguous": "辅料/溶剂·词表误命中（留空待人工）",
    "inn_who_salt_confirmed": "疑似 INN·WHO 母体+盐酯尾词复核确认",
    "inn_shape_unconfirmed": "疑似 INN·词形规则（WHO 未确认）",
    "unknown_no_rule": "判不了（规则未命中）",
}
# 走「疑似 INN」复核的口径（报告 §5 第 7 条）
INN_REVIEW_CATEGORIES = {"inn_who_salt_confirmed", "inn_shape_unconfirmed"}


def connect_ro(path: Path) -> sqlite3.Connection:
    """只读打开（mode=ro），写库操作会直接抛错。"""
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_entity_rows(spec: str | Path | None = None) -> list[dict]:
    """读 entity_type.csv（保持原有行序，便于追加式 diff）。

    `spec` 可以是路径，也可以是 `git:HEAD:data/entity_type.csv`——用于把「追加前」的快照
    与现盘做 before/after 对账（避免手工复制文件）。
    """
    text = str(spec or ENTITY_CSV)
    if text.startswith("git:"):
        git = ROOT / "tools" / "git" / "cmd" / "git.exe"
        cmd = [str(git) if git.exists() else "git", "show", text[4:]]
        raw = subprocess.run(cmd, cwd=ROOT, capture_output=True, check=True).stdout
        return [dict(r) for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))]
    path = Path(text)
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def atc_coverage(db_path: Path, drug_ids: set[str]) -> dict:
    """复刻 `site/build.py::_atc_coverage` 的口径（About 页「药物实体」分母 = entity_type=inn_drug）。"""
    con = connect_ro(db_path)
    rows = con.execute("SELECT substance_id, atc FROM substance").fetchall()
    con.close()
    all_n = len(rows)
    all_atc = sum(1 for r in rows if (r["atc"] or "").strip())
    drug = [(r["substance_id"], r["atc"]) for r in rows if r["substance_id"] in drug_ids]
    drug_n = len(drug)
    drug_atc = sum(1 for _sid, atc in drug if (atc or "").strip())

    def pct(a: int, n: int) -> float:
        return round(a / n * 100, 1) if n else 0.0

    return {"all_atc": all_atc, "all_n": all_n, "all_pct": pct(all_atc, all_n),
            "drug_atc": drug_atc, "drug_n": drug_n, "drug_pct": pct(drug_atc, drug_n)}


def strip_qualifiers(name: str) -> str:
    """去掉尾部性状/剂型限定词（glacial / micronized / dried …），用于生成合并候选。"""
    s = re.sub(r"\s+", " ", (name or "").lower()).strip()
    changed = True
    while changed:
        changed = False
        for suf in QUALIFIER_SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf) + 3:
                s = s[: -len(suf)].strip()
                changed = True
    return s


def tail_is_salt(words: list[str]) -> tuple[bool, str]:
    """尾词是否**全部**是盐/酯/水合物/溶剂化物/成盐酸；任一词不是就返回 False。"""
    if not words:
        return False, "无尾词（整名即 WHO INN）"
    for w in words:
        if w in COMBO_WORDS:
            return False, "复方/共处理词：%s" % w
        if w in SALT_TAILS or w in SALT_ACIDS:
            continue
        ok = False
        for m in SALT_MULTIPLIERS:
            if w.startswith(m) and len(w) > len(m) + 2 and w[len(m):] in SALT_TAILS:
                ok = True
                break
        if ok:
            continue
        return False, "非盐/酯尾词：%s" % w
    return True, "盐/酯/水合物尾词"


def classify(name: str, who: dict[str, str], existing: dict[str, str],
             demote: bool = True) -> tuple[str, str, str, str, str]:
    """返回 (entity_type, rule, confidence, evidence, report_category)。

    `demote=True` 时对「生药/辅料词表命中、但名称是状态/剂型/复方/同位素写法」的条目
    留空 entity_type（不猜），并在 evidence 写明命中的标记；`demote=False` 只用于
    统计「报告规则原样口径」，便于与 reports/2026-11-16 的 60 / 20 对账。
    """
    up = (name or "").upper()
    n = cz.norm_inn(name)
    base = cz.strip_salt(n) or n

    m = RE_HOMEOPATHIC_DILUTION.search(name or "")
    if m:
        return ("homeopathic", "cz_homeopathic_dilution_number", "high",
                "名称含数字稀释度 %r" % m.group(0).strip(),
                "homeopathic_dilution_number")
    for w in HOMEOPATHIC_WORDS:
        if w in up:
            return ("homeopathic", "cz_homeopathic_dilutio_word", "high",
                    "名称含 %r" % w, "homeopathic_dilutio_word")
    for w in VACCINE_WORDS:
        if w in up:
            return ("biologic", "cz_vaccine_antigen", "high",
                    "名称含疫苗/抗原词 %r" % w, "vaccine_antigen")
    if n in who or base in who:
        hit = who.get(n) or who.get(base)
        return ("inn_drug", "cz_who_inn_exact", "high",
                "WHO INN 名录命中：%s（%s；列表见 data/who_inn_names.csv）" % (hit, n),
                "who_inn_exact")
    if n in existing or base in existing:
        return ("inn_drug", "cz_existing_inn", "medium",
                "库内已有同名成分：%s" % (existing.get(n) or existing.get(base)),
                "existing_inn")
    for w in HERBAL_WORDS:
        if w in up:
            if demote:
                for rx, why in HERBAL_FALSE_POSITIVE:
                    fp = rx.search(name or "")
                    if fp:
                        return ("", "cz_botanical_ambiguous", "low",
                                "生药词 %r 命中，但名称是%s（%r），不是植物类别：留空待人工"
                                % (w, why, fp.group(0).strip()), "botanical_ambiguous")
            return ("herbal", "cz_botanical", "medium",
                    "名称含植物部位/提取物词 %r" % w, "botanical")
    for w in EXCIPIENT_WORDS:
        if w in up:
            if demote:
                for rx, why in EXCIPIENT_FALSE_POSITIVE:
                    fp = rx.search(name or "")
                    if fp:
                        return ("", "cz_excipient_ambiguous", "low",
                                "辅料词 %r 命中，但名称是%s（%r），不是辅料本体：留空待人工"
                                % (w, why, fp.group(0).strip()), "excipient_ambiguous")
            return ("material", "cz_excipient", "low",
                    "名称含辅料/溶剂词 %r（词表口径，需人工抽检）" % w, "excipient")
    if RE_INN_SHAPE.search(n) and len(n.split()) <= 4:
        suffix = RE_INN_SHAPE.search(n).group(1)
        # 复核：WHO 名录里是否有「母体 INN + 全是盐/酯尾词」的写法
        words = n.split()
        for k in range(len(words) - 1, 0, -1):
            parent = " ".join(words[:k])
            if parent in who:
                ok, why = tail_is_salt([w.lower() for w in words[k:]])
                if ok:
                    return ("inn_drug", "cz_who_inn_salt_form", "medium",
                            "WHO INN 母体命中：%s；尾词 %r 为%s"
                            % (who[parent], " ".join(words[k:]).lower(), why),
                            "inn_who_salt_confirmed")
                return ("", "cz_inn_shape_unconfirmed", "low",
                        "INN 词尾 %r；WHO 母体 %s 命中但尾词不合盐/酯规则（%s）"
                        % (suffix, who[parent], why), "inn_shape_unconfirmed")
        return ("", "cz_inn_shape_unconfirmed", "low",
                "INN 词尾 %r；WHO 名录（%d 条）与库内成分名均未命中"
                % (suffix, len(who)), "inn_shape_unconfirmed")
    return ("", "cz_unknown_no_rule", "low",
            "规则未命中（非顺势/生药/疫苗/辅料词，也非 INN 词形）", "unknown_no_rule")


def main() -> int:
    ap = argparse.ArgumentParser(description="CZ 908 新成分分类 + 合并候选 + WHO 复核（只读库）")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--merge-into-entity-type", action="store_true",
                    help="把 908 行并入 data/entity_type.csv（先删同 substance_id 旧行，幂等）")
    ap.add_argument("--check", action="store_true",
                    help="只核对 data/entity_type.csv 的 908 覆盖与分布，不写任何文件")
    ap.add_argument("--entity-csv", default=str(ENTITY_CSV),
                    help="--check 核对哪个快照：路径，或 git:HEAD:data/entity_type.csv")
    args = ap.parse_args()

    con = connect_ro(args.db)
    subs = [dict(r) for r in con.execute(
        "SELECT substance_id, inn_en, atc, confidence, name_lang FROM substance"
        " WHERE source_id='sukl_dlp' ORDER BY substance_id")]
    target_ids = {r["substance_id"] for r in subs}
    if not subs:
        print("!! 库里没有 source_id='sukl_dlp' 的成分，先确认 CZ 入库是否跑过")
        return 2

    # 影响面：每个成分的 variant / product_component / product 行数 + 市场
    impact: dict[str, dict] = {r["substance_id"]: {"n_variant": 0, "n_component": 0,
                                                  "n_products": 0, "markets": set()}
                               for r in subs}
    for r in con.execute("""
        SELECT v.substance_id AS sid, COUNT(*) AS n_component,
               COUNT(DISTINCT pc.product_id) AS n_products
        FROM variant v JOIN product_component pc ON pc.variant_id = v.variant_id
        WHERE v.substance_id IN (SELECT substance_id FROM substance WHERE source_id='sukl_dlp')
        GROUP BY v.substance_id"""):
        impact[r["sid"]]["n_component"] = r["n_component"]
        impact[r["sid"]]["n_products"] = r["n_products"]
    for r in con.execute("""
        SELECT DISTINCT v.substance_id AS sid, p.country AS country
        FROM variant v JOIN product_component pc ON pc.variant_id = v.variant_id
        JOIN product p ON p.product_id = pc.product_id
        WHERE v.substance_id IN (SELECT substance_id FROM substance WHERE source_id='sukl_dlp')"""):
        impact[r["sid"]]["markets"].add(r["country"] or "")
    for r in con.execute("""
        SELECT substance_id AS sid, COUNT(*) AS n
        FROM variant
        WHERE substance_id IN (SELECT substance_id FROM substance WHERE source_id='sukl_dlp')
        GROUP BY substance_id"""):
        impact[r["sid"]]["n_variant"] = r["n"]

    # 库内既有成分（排除本轮 908）与 WHO 名录
    existing: dict[str, str] = {}
    for r in con.execute("SELECT substance_id, inn_en FROM substance"):
        if r["substance_id"] in target_ids:
            continue
        key = cz.norm_inn(r["inn_en"] or "")
        if key:
            existing.setdefault(key, r["substance_id"])
    who = cz.load_who_inn()

    # ---- 分类 908 ----
    rows_out: list[dict] = []
    rule_counts: collections.Counter = collections.Counter()
    category_counts: collections.Counter = collections.Counter()
    raw_counts: collections.Counter = collections.Counter()   # 报告规则原样口径（demote=False）
    type_counts: collections.Counter = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)
    for r in subs:
        et, rule, conf, ev, cat = classify(r["inn_en"], who, existing)
        raw_counts[classify(r["inn_en"], who, existing, demote=False)[4]] += 1
        imp = impact[r["substance_id"]]
        rule_counts[rule] += 1
        category_counts[cat] += 1
        type_counts[et or "(留空)"] += 1
        if len(examples[cat]) < 3:
            examples[cat].append(r["inn_en"])
        rows_out.append({
            "substance_id": r["substance_id"], "inn_en": r["inn_en"],
            "entity_type": et, "rule": rule, "confidence": conf, "evidence": ev,
            "cz_report_category": REPORT_CATEGORY[cat],
            "who_review": "", "n_products": imp["n_products"],
            "n_components": imp["n_component"], "n_variants": imp["n_variant"],
            "markets": ",".join(sorted(m for m in imp["markets"] if m)),
            "with_atc": 1 if (r["atc"] or "").strip() else 0,
            "source_id": "sukl_dlp",
        })

    # ---- --check：只核对现有 data/entity_type.csv 对 908 的覆盖（不写文件）----
    if args.check:
        all_ids = {r[0] for r in con.execute("SELECT substance_id FROM substance")}
        on_disk = load_entity_rows(args.entity_csv)
        cov_ids = {r["substance_id"] for r in on_disk}
        cz_rows = [r for r in on_disk if r["substance_id"] in target_ids]
        print("== entity_type 快照覆盖核对（只读，未写任何文件）：%s ==" % args.entity_csv)
        print("  库内 sukl_dlp 成分：%d" % len(target_ids))
        print("  entity_type.csv 总行数：%d（唯一 id %d）" % (len(on_disk), len(cov_ids)))
        print("  908 覆盖：%d / %d" % (len(target_ids & cov_ids), len(target_ids)))
        print("  覆盖行 entity_type 分布：", dict(collections.Counter(
            r["entity_type"] or "(留空)" for r in cz_rows).most_common()))
        print("  覆盖行 rule 分布：", dict(collections.Counter(
            r["rule"] for r in cz_rows).most_common()))
        print("  CSV 里有、库里已无的 id：%d（历史遗留，本次未变）" % len(cov_ids - all_ids))
        # Q17 口径：只统计 2026-11-18 Q2 合并掉的那 3 个 substance（读 manifest，不硬编码）；
        # 其余悬空是更早历史快照的遗留行，按「不删历史行」保留，单独计数。
        q2_manifest = SOURCES / "q2_merge_manifest_20261118.json"
        q2_from: set[str] = set()
        if q2_manifest.exists():
            q2_from = {m["from"] for m in json.loads(
                q2_manifest.read_text(encoding="utf-8")).get("merges", [])}
        q2_dangling = (cov_ids - all_ids) & q2_from
        print("  其中 Q2 合并后已不存在的 id（Q17 口径）：%d 条%s"
              % (len(q2_dangling),
                 "" if not q2_dangling else "：" + "、".join(sorted(q2_dangling))))
        print("  About「药物实体」ATC 分母：%s"
              % atc_coverage(args.db, {r["substance_id"] for r in on_disk
                                       if (r.get("entity_type") or "").strip() == "inn_drug"}))
        return 0

    # ---- 合并候选（去性状限定词后与库内既有成分同名 = 确定性重复）----
    merge_rows: list[dict] = []
    for r in subs:
        n = cz.norm_inn(r["inn_en"])
        base = cz.strip_salt(n) or n
        target_id = None
        basis = ""
        certain = ""
        for cand, why, tier in (
                (n, "归一后与库内成分同名", "是（归一后完全同名）"),
                (base, "去掉盐/水合物尾型后与库内成分同名",
                 "否（去盐后同名，可能是盐型/元素歧义，需人工确认）"),
                (cz.norm_inn(strip_qualifiers(r["inn_en"])),
                 "去掉性状/剂型限定词后与库内成分同名",
                 "是（去掉性状/剂型限定词后同名，同名同物）")):
            sid = existing.get(cand)
            if sid:
                target_id = sid
                basis = "%s（%s → %s）" % (why, r["inn_en"], cand)
                certain = tier
                break
        if not target_id:
            continue
        imp = impact[r["substance_id"]]
        tgt = con.execute("SELECT inn_en FROM substance WHERE substance_id=?",
                          (target_id,)).fetchone()
        merge_rows.append({
            "from_substance": r["substance_id"],
            "to_substance": target_id,
            "依据": basis,
            "影响 product 行数": imp["n_products"],
            "影响 product_component 行数": imp["n_component"],
            "确定性": certain,
            "from_inn_en": r["inn_en"],
            "to_inn_en": tgt["inn_en"] if tgt else "",
            "影响 variant 行数": imp["n_variant"],
            # 复现：两条 SQL 都能直接跑（只读），第二条给 re-point 的影响面
            "复现SQL": ("SELECT s.substance_id, s.inn_en, t.substance_id, t.inn_en FROM substance s"
                        " JOIN substance t ON t.substance_id='%s' WHERE s.substance_id='%s';"
                        % (target_id, r["substance_id"])),
            "repoint影响SQL": ("SELECT COUNT(*) AS variant_rows,"
                               " (SELECT COUNT(*) FROM product_component pc WHERE pc.variant_id IN"
                               " (SELECT variant_id FROM variant WHERE substance_id='%s'))"
                               " AS component_rows FROM variant WHERE substance_id='%s';"
                               % (r["substance_id"], r["substance_id"])),
        })
    # 确定性候选排前面；「去盐后同名」这种可能是盐型/元素歧义的排后面并标记需人工
    merge_rows.sort(key=lambda m: (0 if m["确定性"].startswith("是") else 1,
                                   m["from_substance"]))

    # ---- 192 个疑似 INN 的 WHO 复核（明细 CSV；与分类行一一对应）----
    review_rows: list[dict] = []
    for row in rows_out:
        cat = next(k for k, v in REPORT_CATEGORY.items() if v == row["cz_report_category"])
        if cat not in INN_REVIEW_CATEGORIES:
            continue
        n = cz.norm_inn(row["inn_en"])
        base = cz.strip_salt(n) or n
        words = n.split()
        parent, parent_who, tail, tail_ok, why = "", "", "", False, "无 WHO 母体"
        for k in range(len(words) - 1, 0, -1):
            p = " ".join(words[:k])
            if p in who:
                parent, parent_who = p, who[p]
                tail = " ".join(words[k:]).lower()
                tail_ok, why = tail_is_salt([w.lower() for w in words[k:]])
                break
        db_parent = ""
        for k in range(len(words) - 1, 0, -1):
            p = " ".join(words[:k])
            if p in existing:
                db_parent = "%s（%s）" % (p, existing[p])
                break
        verdict = "确认（母体 INN 在 WHO + 盐/酯尾词）" if tail_ok else "未确认"
        if not tail_ok and parent and parent_who:
            note = "WHO 母体 %s 命中，但尾词不合盐/酯规则（%s）" % (parent_who, why)
        elif not parent:
            note = "WHO 名录（%d 条）无母体命中" % len(who)
        else:
            note = why
        row["who_review"] = verdict
        review_rows.append({
            "substance_id": row["substance_id"], "inn_en": row["inn_en"],
            "verdict": verdict,
            "who_parent": parent_who,
            "who_tail": tail,
            "detail": note,
            "db_parent_hint": db_parent,
            "in_main_entity_type_review": "是" if row["entity_type"] == "inn_drug" else "否",
        })

    con.close()

    # ---- 写 CSV（LF；派生快照用 utf-8 无 BOM，与其他 data/sources 一致）----
    SOURCES.mkdir(parents=True, exist_ok=True)
    out_fields = ["substance_id", "inn_en", "entity_type", "rule", "confidence", "evidence",
                  "cz_report_category", "who_review", "n_products", "n_components",
                  "n_variants", "markets", "with_atc", "source_id"]
    with OUT_ENTITY.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows_out)
    merge_fields = ["from_substance", "to_substance", "依据", "影响 product 行数",
                    "影响 product_component 行数", "确定性", "from_inn_en", "to_inn_en",
                    "影响 variant 行数", "复现SQL", "repoint影响SQL"]
    with OUT_MERGE.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=merge_fields, lineterminator="\n")
        w.writeheader()
        w.writerows(merge_rows)
    review_fields = ["substance_id", "inn_en", "verdict", "who_parent", "who_tail",
                     "detail", "db_parent_hint", "in_main_entity_type_review"]
    with OUT_REVIEW.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=review_fields, lineterminator="\n")
        w.writeheader()
        w.writerows(review_rows)

    # ---- 统计 ----
    n_typed = sum(1 for r in rows_out if r["entity_type"])
    print("== CZ 908 个新成分分类（只读库，未写 data/drugs.db）==")
    print("  成分数 %d；有 entity_type %d；留空 %d" % (len(rows_out), n_typed,
                                                  len(rows_out) - n_typed))
    print("  entity_type 分布：", dict(type_counts.most_common()))
    print("  报告 §1 口径分布：")
    for cat, label in REPORT_CATEGORY.items():
        if category_counts.get(cat):
            print("    %-28s %4d  %s" % (cat, category_counts[cat],
                                         "、".join(examples[cat][:3])))
    print("  报告规则原样口径（demote=False，用于与 2026-11-16 报告的 60 / 20 对账）：")
    for cat, n in raw_counts.most_common():
        print("    %-28s %4d" % (cat, n))
    ambiguous = [x for x in rows_out if x["rule"].endswith("_ambiguous")]
    print("  词表误命中 → 留空待人工：%d 条" % len(ambiguous))
    for x in ambiguous:
        print("    %-30s %-48s %3s 产品" % (x["rule"], x["inn_en"], x["n_products"]))
    print("  rule 分布：", dict(rule_counts.most_common()))
    print("  合并候选：%d 条（确定性 %d / 需人工 %d）"
          % (len(merge_rows),
             sum(1 for m in merge_rows if m["确定性"].startswith("是")),
             sum(1 for m in merge_rows if not m["确定性"].startswith("是"))))
    for m in merge_rows:
        print("    [%s] %-30s → %-24s product %d / component %d"
              % (m["确定性"][:1], m["from_substance"], m["to_substance"],
                 m["影响 product 行数"], m["影响 product_component 行数"]))
    n_yes = sum(1 for r in review_rows if r["verdict"].startswith("确认"))
    print("  疑似 INN 复核：%d 条 → 确认 %d / 未确认 %d"
          % (len(review_rows), n_yes, len(review_rows) - n_yes))
    print("  → %s" % OUT_ENTITY.relative_to(ROOT))
    print("  → %s" % OUT_MERGE.relative_to(ROOT))
    print("  → %s" % OUT_REVIEW.relative_to(ROOT))

    # ---- 并入 data/entity_type.csv（幂等：先删同 id 旧行，再追加）----
    if args.merge_into_entity_type:
        before = load_entity_rows()
        keep = [r for r in before if r["substance_id"] not in target_ids]
        added: list[dict] = []
        for src in sorted(rows_out, key=lambda x: x["substance_id"]):
            added.append({
                "substance_id": src["substance_id"],
                "entity_type": src["entity_type"],
                "rule": src["rule"],
                "confidence": src["confidence"],
                "evidence": src["evidence"],
                "n_products": str(src["n_products"]),
                "markets": src["markets"],
                "with_atc": str(src["with_atc"]),
            })
        cov_before = atc_coverage(args.db, {
            r["substance_id"] for r in before
            if (r.get("entity_type") or "").strip() == "inn_drug"})
        cov_after = atc_coverage(args.db, {
            r["substance_id"] for r in keep + added
            if (r.get("entity_type") or "").strip() == "inn_drug"})
        # 与 etl/classify_entity_type.py 同格式（utf-8-sig + CRLF），原有行序不动、只追加
        with ENTITY_CSV.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=ENTITY_FIELDS)
            w.writeheader()
            w.writerows(keep + added)
        print("\n== data/entity_type.csv 已更新 ==")
        print("  原有 %d 行 → 保留 %d + 追加 %d = %d 行"
              % (len(before), len(keep), len(added), len(keep) + len(added)))
        print("  其中 inn_drug：%d → %d"
              % (sum(1 for r in before if r["entity_type"] == "inn_drug"),
                 sum(1 for r in keep + added if r["entity_type"] == "inn_drug")))
        print("  About「药物实体」ATC 分母：%d → %d（有 ATC %d → %d，%s%% → %s%%）"
              % (cov_before["drug_n"], cov_after["drug_n"],
                 cov_before["drug_atc"], cov_after["drug_atc"],
                 cov_before["drug_pct"], cov_after["drug_pct"]))
        print("  全部 substance：%d → %d（有 ATC %d → %d）"
              % (cov_before["all_n"], cov_after["all_n"],
                 cov_before["all_atc"], cov_after["all_atc"]))
        print("  （注意：重跑 etl/classify_entity_type.py 会整表重写，本追加会被覆盖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
