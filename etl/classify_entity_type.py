# -*- coding: utf-8 -*-
"""substance.entity_type 规则分类（只读 DB，写 data/entity_type.csv）。

目的
----
ATC 覆盖率的分母不应该是「全部 substance」。DB 里 6,903 个缺 ATC 的成分里，
有大量不是 INN 药物实体：生药、顺势药、医疗气体、营养配方、ARTG 解析残留、
复方名。这个脚本用**可解释的规则**给每个 substance 打 entity_type，并输出
`data/entity_type.csv`（substance_id, entity_type, rule, confidence, evidence）。

分类口径（按规则顺序，命中即停）
--------------------------------
  combination  名称是复方（含 " and " / " + " / " / " / " y " / ^co-）
  homeopathic  产品 ≥80% 来自 openFDA "UNAPPROVED HOMEOPATHIC"
  food         肠内营养 / 氨基酸配方 / 蛋白配方 / 维生素矿物质复合物 / 食材
  herbal       植物名（根/叶/种子/花/树皮/提取物…）
  biologic     生物制品（-mab/-cept/-fusp/-plase、疫苗、免疫球蛋白、胰岛素…）
  material     医疗气体 / 元素 / 金属 / 矿物 / 辅料 / 检验指示物 / ARTG 残留
  other        名称残缺或无法判断
  inn_drug     其余（默认：有 INN 形态的药物实体）

只读：DB 以 mode=ro 打开；输出只写 data/entity_type.csv。
用法：
    python etl/classify_entity_type.py            # 分类 + 统计 + 写 CSV
    python etl/classify_entity_type.py --sample 30
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
OUT = ROOT / "data" / "entity_type.csv"
TODAY = date.today().isoformat()

ENTITY_TYPES = ("inn_drug", "biologic", "herbal", "homeopathic", "material",
                "combination", "food", "other")

# --- 名称规则 -----------------------------------------------------------------
RE_COMBO = re.compile(r"(\s\+\s|\s/\s|\band\b|^co-|\sy\s)", re.I)

HOMEOPATHIC_NAME = re.compile(r"(homeopath|nosode|tincture|dilution|potency)", re.I)
FOOD_NAME = re.compile(
    r"(enteral|amino acid formula|protein formula|whey|soy protein|milk protein|"
    r"carbohydrate|fat formula|triglycerides|glycomacropeptide|nutrition|"
    r"vitamins?,? minerals|trace elements|oatmeal|honey|coffee|tea\b|chocolate|"
    r"casein|\begg\b|\bmilk\b|soy\b|wheat|rice\b|fruit|vegetable|sports drink|"
    r"oral rehydration|electrolyte|infant formula|follow-on formula|meal replacement)", re.I)
HERBAL_NAME = re.compile(
    r"(root|rhizome|stolon|leaf|leaves|seed|flower|flowering|bark|twig|whole|berry|"
    r"pollen|resin|juice|semen|folium|radix|herba|extract|blade|stem|wood|aerial|"
    r"ginkgo|ginseng|valerian|echinacea|ginger|garlic|turmeric|milk thistle|"
    r"saw palmetto|cranberry|evening primrose|black cohosh|horse chestnut|"
    r"grapeseed|green tea|chamomile|lavender|peppermint|st john)", re.I)
BIOLOGIC_NAME = re.compile(
    r"(-mab|-cept|-fusp|-plase|-tropin|-poetin|vaccin|toxoid|immunoglobulin|"
    r"antibody|interferon|interleukin|insulin|erythropoietin|antithrombin|"
    r"coagulation factor|factor (vii|viii|ix|xi|x|iib|i)\b|allergen extract|"
    r"\b(blood|plasma|serum)\b|\bcells?\b|\btissues?\b|antivenom|"
    r"immunosuppressive globulin|botulinum|thrombin|fibrin|hyaluronidase|collagenase)", re.I)
MATERIAL_NAME = re.compile(
    r"(^equivalent\b|^tribasic\b|\bunspecified\b|not stated|^medical air\b|"
    r"^oxygen\b|^nitrogen\b|^carbon dioxide\b|^helium\b|^argon\b|^hydrogen\b|"
    r"^water\b|mineral oil|silicone|dimethicone|petrolatum|paraffin|talc|kaolin|"
    r"nickel|titanium|silver|gold\b|mercury|mercuric|ferrosoferric|"
    r"indicator|reagent|diagnostic|contrast media|gadolinium|barium|"
    r"calcium sulfide|oyster shell|activated charcoal|charcoal)", re.I)
ARTIFACT_NAME = re.compile(
    r"(^equivalent\b|^tribasic\b|\bunspecified\b|not stated|"
    r"indicator urine|ketone indicator|glucose and ketone|"
    r"^(?:unknown|none|n/?a|other)\b)", re.I)

CAT_HOMEOPATHIC = "UNAPPROVED HOMEOPATHIC"
CAT_MEDICAL_GAS = "UNAPPROVED MEDICAL GAS"
CAT_BLA = "BLA"
CAT_MARKET = {"dm+d", "CIMA", "化学药", "Registro Sanitario", "PBS item", "TGA CMI",
              "ARTG", "Listed Medicines", "Export only Medicines"}


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if not unicodedata.combining(c))


def norm(s: str) -> str:
    s = strip_acc(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def connect_ro(db_path: Path) -> sqlite3.Connection:
    uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def load_substances(con: sqlite3.Connection) -> list[dict]:
    """每个 substance 的产品统计：产品数、市场、category 分布、剂型、来源。"""
    subs = {r["substance_id"]: dict(r) for r in con.execute(
        "SELECT substance_id, inn_en, inn_zh, atc FROM substance")}
    stats: dict[str, dict] = defaultdict(
        lambda: {"n_products": set(), "markets": set(), "categories": Counter(),
                 "forms": set(), "sources": set()})
    for r in con.execute("""
        SELECT DISTINCT s.substance_id, p.product_id, p.country, p.category,
               p.dosage_form, p.source_id
        FROM substance s
        JOIN variant v ON v.substance_id = s.substance_id
        JOIN product_component pc ON pc.variant_id = v.variant_id
        JOIN product p ON p.product_id = pc.product_id"""):
        st = stats[r["substance_id"]]
        st["n_products"].add(r["product_id"])
        st["markets"].add(r["country"])
        st["categories"][r["category"] or ""] += 1
        if r["dosage_form"]:
            st["forms"].add(norm(r["dosage_form"]))
        st["sources"].add(r["source_id"] or "")
    for sid, sub in subs.items():
        st = stats.get(sid, {"n_products": set(), "markets": set(), "categories": Counter(),
                             "forms": set(), "sources": set()})
        sub["n_products"] = len(st["n_products"])
        sub["markets"] = sorted(st["markets"])
        sub["categories"] = dict(st["categories"])
        sub["forms"] = sorted(st["forms"])
        sub["sources"] = sorted(st["sources"])
        sub["missing_atc"] = not (sub["atc"] or "").strip()
    return list(subs.values())


def cat_share(categories: dict, cat: str) -> float:
    total = sum(categories.values())
    if not total:
        return 0.0
    return categories.get(cat, 0) / total


def classify(sub: dict) -> dict:
    name = (sub["inn_en"] or "").strip()
    n = norm(name)
    cats = sub["categories"]
    np = sub["n_products"]
    ev: list[str] = []

    def out(etype: str, rule: str, conf: str, evidence: str) -> dict:
        return {"substance_id": sub["substance_id"], "entity_type": etype, "rule": rule,
                "confidence": conf, "evidence": evidence,
                "n_products": np, "markets": ",".join(sub["markets"]),
                "with_atc": 0 if sub["missing_atc"] else 1}

    # 1) 复方
    if RE_COMBO.search(name):
        ev.append("name_combo=%r" % name[:60])
        return out("combination", "name_combo", "high", " | ".join(ev))

    # 2) 顺势（产品 category 证据最强）
    if cat_share(cats, CAT_HOMEOPATHIC) >= 0.8 and np > 0:
        return out("homeopathic", "category_homeopathic", "high",
                   "UNAPPROVED HOMEOPATHIC %.0f%%（%d/%d 产品）" % (
                       100 * cat_share(cats, CAT_HOMEOPATHIC),
                       cats.get(CAT_HOMEOPATHIC, 0), sum(cats.values())))
    if HOMEOPATHIC_NAME.search(name):
        return out("homeopathic", "name_homeopathic", "medium", "name=%r" % name)

    # 3) 医疗气体 / 材料（category）
    if cat_share(cats, CAT_MEDICAL_GAS) >= 0.5 and np > 0:
        return out("material", "category_medical_gas", "high",
                   "UNAPPROVED MEDICAL GAS %.0f%%（%d 产品）" % (
                       100 * cat_share(cats, CAT_MEDICAL_GAS), cats.get(CAT_MEDICAL_GAS, 0)))

    # 4) 名称残缺 / ARTG 解析残留
    if ARTIFACT_NAME.search(name):
        return out("other", "name_artifact", "high", "artifact pattern: %r" % name[:60])

    # 4b) 中文名（CN 专属成分：NHSA 化学药，中成药入库时已排除）
    if re.search(r"[\u4e00-\u9fff]", name):
        if "复方" in name or "复方" in (sub.get("inn_zh") or ""):
            return out("combination", "name_han_fufang", "medium", "中文名含「复方」: %r" % name[:40])
        return out("inn_drug", "name_han_cn", "medium",
                   "中文通用名（NHSA 化学药；cn- 前缀 %s）" % sub["substance_id"].startswith("cn-"))

    # 5) 营养 / 食品
    if FOOD_NAME.search(name):
        return out("food", "name_food", "medium", "food/nutrition pattern: %r" % name[:60])

    # 6) 生药
    if HERBAL_NAME.search(name):
        return out("herbal", "name_herbal", "medium", "botanical pattern: %r" % name[:60])

    # 7) 生物制品
    if cat_share(cats, CAT_BLA) >= 0.5 and np > 0:
        return out("biologic", "category_bla", "high",
                   "BLA %.0f%%（%d 产品）" % (100 * cat_share(cats, CAT_BLA),
                                             cats.get(CAT_BLA, 0)))
    if BIOLOGIC_NAME.search(name):
        return out("biologic", "name_biologic", "medium", "biologic pattern: %r" % name[:60])

    # 8) 材料 / 元素 / 矿物 / 辅料
    if MATERIAL_NAME.search(name):
        return out("material", "name_material", "medium", "material pattern: %r" % name[:60])

    # 9) INN 药物实体（默认）：名称像拉丁 INN（1–4 词、字母）
    if n and re.match(r"^[a-z][a-z0-9 -]{2,60}$", n) and len(n.split()) <= 5:
        return out("inn_drug", "default_inn", "medium",
                   "INN-like name; categories=%s" % dict(list(cats.items())[:4]))

    return out("other", "fallback_other", "low", "unclassifiable name=%r" % name[:60])


def main() -> int:
    ap = argparse.ArgumentParser(description="substance entity_type 规则分类（只读 + 写 CSV）")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--sample", type=int, default=25, help="每个类型打印多少条样例")
    args = ap.parse_args()

    con = connect_ro(args.db)
    subs = load_substances(con)
    con.close()
    rows = [classify(s) for s in subs]

    # 写 CSV
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["substance_id", "entity_type", "rule",
                                           "confidence", "evidence", "n_products",
                                           "markets", "with_atc"])
        w.writeheader()
        w.writerows(rows)

    # 统计
    total = len(rows)
    by_type = Counter(r["entity_type"] for r in rows)
    atc_by_type = Counter(r["entity_type"] for r in rows if r["with_atc"])
    print("=== substance entity_type 分类（%d 个）===" % total)
    print("%-14s %7s %7s %8s %8s" % ("entity_type", "count", "withATC", "ATC%", "share%"))
    for t in ENTITY_TYPES:
        c = by_type.get(t, 0)
        a = atc_by_type.get(t, 0)
        print("%-14s %7d %7d %7.1f%% %7.1f%%" % (
            t, c, a, 100 * a / c if c else 0, 100 * c / total if total else 0))
    print("%-14s %7d %7d %7.1f%%" % ("TOTAL", total,
                                     sum(atc_by_type.values()),
                                     100 * sum(atc_by_type.values()) / total))

    print("\n=== 新分母 ATC 覆盖率 ===")
    for label, types in (
            ("全部 substance", ENTITY_TYPES),
            ("inn_drug", ("inn_drug",)),
            ("inn_drug + biologic", ("inn_drug", "biologic")),
            ("drug-like（inn_drug+biologic+food）", ("inn_drug", "biologic", "food"))):
        cc = [r for r in rows if r["entity_type"] in types]
        a = sum(1 for r in cc if r["with_atc"])
        print("  %-38s %7d 中 %7d 有 ATC = %.1f%%" % (label, len(cc), a,
                                                      100 * a / len(cc) if cc else 0))

    print("\n=== 缺 ATC 的成分按 entity_type ===")
    miss = Counter(r["entity_type"] for r in rows if not r["with_atc"])
    for t in ENTITY_TYPES:
        print("  %-14s %d" % (t, miss.get(t, 0)))

    print("\n=== 每类抽样（--sample %d，供人工抽验）===" % args.sample)
    import random
    random.seed(24)
    for t in ENTITY_TYPES:
        subset = [r for r in rows if r["entity_type"] == t]
        if not subset:
            continue
        print("\n[%s] %d 个" % (t, len(subset)))
        for r in random.sample(subset, min(args.sample, len(subset))):
            sub = next(s for s in subs if s["substance_id"] == r["substance_id"])
            print("  %-36s %-40s np=%-4d %s" % (
                r["substance_id"][:36], (sub["inn_en"] or "")[:40], r["n_products"],
                r["rule"]))
    print("\n→ %s" % args.out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
