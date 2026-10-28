#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""复方-复方跨市场匹配候选（task-59）。

只读 `data/drugs.db`，对复方产品（product_component 数 ≥2）按「活性成分集合」建签名，
再在跨市场（CN/ES/MX ↔ US/GB/CA/AU）之间配对：

  exact      同一成分集合（成分经同义名/盐型归一后）两边都有产品
  overlap    不同集合但成分重叠 Jaccard ≥ 0.80
  none       两边都没有同集合/高重叠复方 → 记录「主成分是否能在对面市场找到」
             作为后续页面降级展示依据（主成分 = ord 最小的成分，缺失时取排序第一）

产物：
  data/combo_match_candidates.csv   每个（成分集合 × 市场）一行
  .tmp/combo-match/stats.json       汇总统计
  .tmp/combo-match/samples.txt      样例（二甲双胍+格列本脲 / 阿莫西林+克拉维酸 / 复方氨酚烷胺）

用法：
    python etl/build_combo_matches.py            # 建 CSV（只读）
    python etl/build_combo_matches.py --dry-run  # 只打印统计
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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
OUT = ROOT / "data" / "combo_match_candidates.csv"
TMP = ROOT / ".tmp" / "combo-match"

EAST = {"CN", "ES", "MX"}       # 中文/西语市场
WEST = {"US", "GB", "CA", "AU"}  # 英语市场
OVERLAP_MIN = 0.80

# 同义 INN（不同市场习惯名）→ 统一 ingredient key。只用于「成分集合比较」，不改 DB。
SYNONYMS = {
    "paracetamol": "acetaminophen",
    "acetaminophen": "acetaminophen",
    "glyburide": "glibenclamide",
    "glibenclamide": "glibenclamide",
    "salbutamol": "salbutamol",
    "albuterol": "salbutamol",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "frusemide": "furosemide",
    "lignocaine": "lidocaine",
    "hyoscine": "scopolamine",
    "rifampicin": "rifampin",
    "pethidine": "meperidine",
    "oestradiol": "estradiol",
    "ethinyloestradiol": "ethinylestradiol",
    "levothyroxine": "levothyroxine",
    "thyroxine": "levothyroxine",
    "clavulanate": "clavulanic-acid",
    "clavulanic": "clavulanic-acid",
    "clavulanic-acid": "clavulanic-acid",
    "amoxicillin": "amoxicillin",
    "amoxycillin": "amoxicillin",
    "cefalexin": "cephalexin",
    "cefalotin": "cephalothin",
    "cefazolin": "cefazolin",
    "sulbactam": "sulbactam",
    "tazobactam": "tazobactam",
    "vitamin-c": "ascorbic-acid",
    "ascorbic-acid": "ascorbic-acid",
}
# 盐/酯/水合物/剂型词（从成分名里剥掉后再比较）
SALT_WORDS = {
    "hydrochloride", "hydrobromide", "bromide", "chloride", "sodium", "potassium",
    "calcium", "magnesium", "zinc", "iron", "ammonium", "sulfate", "sulphate",
    "phosphate", "acetate", "citrate", "tartrate", "maleate", "fumarate",
    "succinate", "malate", "lactate", "gluconate", "nitrate", "mesylate",
    "besylate", "tosylate", "pamoate", "stearate", "palmitate", "propionate",
    "dipropionate", "valerate", "butyrate", "benzoate", "carbonate", "bicarbonate",
    "hydroxide", "oxide", "trihydrate", "dihydrate", "monohydrate", "hemihydrate",
    "anhydrous", "hydrate", "dehydrate", "methyl", "ethyl", "ester", "acid",
    "trometamol", "tromethamine", "meglumine", "lysine", "arginine", "choline",
    "disodium", "dipotassium", "hemisuccinate", "furoate", "cipionate",
    "phenylacetate", "hyclate", "pivoxil", "axetil", "proxetil", "medoxomil",
}
RE_NONALNUM = re.compile(r"[^a-z0-9]+")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def norm_inn(name: str) -> str:
    """英文 INN → ingredient key：去括号/盐/剂型/酯，再查同义表。"""
    s = unicodedata.normalize("NFKC", name or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("/", " ")
    toks = [t for t in RE_NONALNUM.sub(" ", s).split() if t]
    out: list[str] = []
    for t in toks:
        if t in SALT_WORDS:
            continue
        out.append(t)
    if not out:
        out = toks
    key = "-".join(out) if out else (name or "").strip().lower()
    return SYNONYMS.get(key, key)


def combo_slug(keys: list[str]) -> str:
    """与 site/build.py combo_slug 的「可读 slug」同风格（近似）。"""
    raw = "+".join(sorted(keys))
    s = re.sub(r"[\x00-\x1f\x7f]+", "", raw)
    s = re.sub(r'[\\/:*?"<>|\s]+', "-", s).strip("-")
    return s[:80] if s else "combo"


def load(con: sqlite3.Connection) -> dict:
    # substance → inn_en / atc；variant → substance
    sub_inn = {r["substance_id"]: (r["inn_en"] or "") for r in
               con.execute("SELECT substance_id, inn_en FROM substance")}
    sub_zh = {r["substance_id"]: (r["inn_zh"] or "") for r in
              con.execute("SELECT substance_id, inn_zh FROM substance")}
    var_sub = {r["variant_id"]: r["substance_id"] for r in
               con.execute("SELECT variant_id, substance_id FROM variant")}
    # 原始复方（>=2 行）产品数 & 原始 sid 集合（= site combo 页面数口径）
    raw_combo = [r[0] for r in con.execute(
        "SELECT product_id FROM product_component GROUP BY product_id"
        " HAVING COUNT(*) >= 2")]
    raw_sid_sets = set()
    for pid in raw_combo:
        sids = tuple(sorted(r[0] for r in con.execute(
            "SELECT v.substance_id FROM product_component pc"
            " JOIN variant v ON v.variant_id=pc.variant_id WHERE pc.product_id=?", (pid,))))
        raw_sid_sets.add(sids)
    # 复方产品的成分（含 ord / 强度）
    comps: dict[str, list[dict]] = defaultdict(list)
    for r in con.execute("""
        SELECT pc.product_id, pc.ord, pc.strength_value, pc.strength_unit,
               v.substance_id
        FROM product_component pc
        JOIN variant v ON v.variant_id = pc.variant_id
        JOIN (SELECT product_id FROM product_component GROUP BY product_id
              HAVING COUNT(*) >= 2) combo ON combo.product_id = pc.product_id
        ORDER BY pc.product_id, pc.ord"""):
        sid = r["substance_id"]
        comps[r["product_id"]].append(dict(
            ord=r["ord"], sid=sid, inn=sub_inn.get(sid, sid),
            key=norm_inn(sub_inn.get(sid) or sub_zh.get(sid) or sid),
            strength=(f"{r['strength_value']:g} {r['strength_unit'] or ''}".strip()
                      if r["strength_value"] is not None else "")))
    # 产品信息 + 国家 + 品牌名
    prod = {}
    for r in con.execute("SELECT product_id, country, form_base, dosage_form, release,"
                         " status FROM product WHERE status='active'"):
        prod[r["product_id"]] = dict(country=r["country"],
                                     form=(r["form_base"] or r["dosage_form"] or ""),
                                     release=(r["release"] or "none"),
                                     brands=[])
    for r in con.execute("""
        SELECT pn.product_id, nv.raw
        FROM product_name pn JOIN name_key nk ON nk.key_id = pn.key_id
        LEFT JOIN name_variant nv ON nv.key_id = pn.key_id
        WHERE pn.name_type = 'trade'"""):
        p = prod.get(r["product_id"])
        if p is not None and r["raw"]:
            p["brands"].append(r["raw"])
    return dict(sub_inn=sub_inn, sub_zh=sub_zh, comps=comps, prod=prod,
                raw_combo=len(raw_combo), raw_sid_sets=len(raw_sid_sets))


def build_groups(d: dict) -> dict:
    """product → (ingredient_sig, keys, strength_sig, form_sig)；按签名聚合。"""
    groups: dict[str, dict] = {}
    for pid, items in d["comps"].items():
        p = d["prod"].get(pid)
        if not p:
            continue
        keys = []
        for it in items:
            if it["key"] not in keys:
                keys.append(it["key"])
        if len(keys) < 2:
            continue  # 盐型拆分后只剩 1 个成分 → 不算复方
        sig = "|".join(sorted(keys))
        strength_sig = " + ".join(sorted({it["strength"] for it in items if it["strength"]}))
        g = groups.setdefault(sig, dict(keys=sorted(keys), countries=Counter(),
                                        products=defaultdict(list),
                                        brands=defaultdict(Counter),
                                        forms=Counter(), strengths=Counter(),
                                        primary=Counter(), n=0))
        g["n"] += 1
        g["countries"][p["country"]] += 1
        g["products"][p["country"]].append(pid)
        g["forms"][f"{p['form']}/{p['release']}"] += 1
        g["strengths"][strength_sig] += 1
        for b in p["brands"][:1]:
            g["brands"][p["country"]][b] += 1
        # 主成分：ord 最小
        prim = min(items, key=lambda it: (it["ord"] if it["ord"] is not None else 99,
                                          it["sid"]))
        g["primary"][prim["key"]] += 1
    # combos 有产品的国家集合（用于跨市场检索）
    return groups


def market_sets(groups: dict) -> dict:
    out = {}
    for sig, g in groups.items():
        cs = set(g["countries"])
        out[sig] = dict(east=cs & EAST, west=cs & WEST)
    return out


def match(groups: dict, ms: dict) -> tuple[dict, dict]:
    """每个签名找对面市场的 exact / overlap 候选。"""
    # 同区域签名索引（提升效率）
    east_sigs = {s for s, v in ms.items() if v["east"]}
    west_sigs = {s for s, v in ms.items() if v["west"]}
    key_cache = {s: set(groups[s]["keys"]) for s in groups}
    result = {}
    for sig, g in groups.items():
        opp = west_sigs if ms[sig]["east"] else (east_sigs if ms[sig]["west"] else set())
        if not opp:
            result[sig] = dict(strength="none", markets=[], matched=[], overlap=0.0)
            continue
        if sig in opp:
            # exact：对面市场里同签名
            markets = sorted((ms[sig]["west"] | ms[sig]["east"]))
            result[sig] = dict(strength="exact", markets=markets, matched=[sig],
                               overlap=1.0)
            continue
        own = key_cache[sig]
        best = None
        best_ratio = 0.0
        for osig in opp:
            other = key_cache[osig]
            inter = len(own & other)
            union = len(own | other)
            if union and inter / union >= OVERLAP_MIN:
                if inter / union > best_ratio:
                    best_ratio = inter / union
                    best = osig
        if best:
            result[sig] = dict(strength="overlap", markets=sorted(ms[best]["west"] | ms[best]["east"]),
                               matched=[best], overlap=round(best_ratio, 3))
        else:
            result[sig] = dict(strength="none", markets=[], matched=[], overlap=0.0)
    return result, ms


def primary_markets(groups: dict, d: dict) -> dict:
    """ingredient key → 出现在哪些市场的复方里（用于主成分降级判断）。"""
    key_markets: dict[str, set[str]] = defaultdict(set)
    for sig, g in groups.items():
        for k in g["keys"]:
            key_markets[k] |= set(g["countries"])
    return key_markets


def main() -> int:
    global DB
    ap = argparse.ArgumentParser(description="复方跨市场匹配候选（只读 DB）")
    ap.add_argument("--db", default=str(DB), help="只读 DB")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计")
    args = ap.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FATAL: DB 不存在: {db_path}", file=sys.stderr)
        return 2
    DB = db_path
    con = connect()
    d = load(con)
    groups = build_groups(d)
    ms = market_sets(groups)
    matches, _ = match(groups, ms)
    key_markets = primary_markets(groups, d)
    # 统计
    total_combo_products = sum(g["n"] for g in groups.values())
    all_sigs = set(groups)
    exact = [s for s in all_sigs if matches[s]["strength"] == "exact"]
    overlap = [s for s in all_sigs if matches[s]["strength"] == "overlap"]
    none = [s for s in all_sigs if matches[s]["strength"] == "none"]
    # 只在单一区域出现的签名（没有对面市场，天然 none）
    def region(s):
        e = bool(ms[s]["east"])
        w = bool(ms[s]["west"])
        return "both" if e and w else ("east" if e else ("west" if w else "?"))
    cross_sigs = [s for s in all_sigs if region(s) == "both"]
    # 匹配率口径（避免「两边都有=exact 恒为 100%」的循环定义）：
    #   - 集合口径：exact / 全部集合
    #   - 产品口径：exact 产品 / 全部规范化复方产品
    #   - 东侧覆盖：exact / (exact + east_only)；西侧同理
    n_east = len([s for s in all_sigs if ms[s]["east"]])
    n_west = len([s for s in all_sigs if ms[s]["west"]])
    rate_sig = len(exact) / len(all_sigs) if all_sigs else 0.0
    rate_prod = (sum(groups[s]["n"] for s in exact) / total_combo_products
                 if total_combo_products else 0.0)
    east_cover = len([s for s in exact if ms[s]["east"]]) / n_east if n_east else 0.0
    west_cover = len([s for s in exact if ms[s]["west"]]) / n_west if n_west else 0.0
    # 降级主成分可用：none 集合里主成分在对面市场也有产品（任意复方/单方里出现）
    downgrade = []
    for sig in none:
        g = groups[sig]
        prim = g["primary"].most_common(1)[0][0] if g["primary"] else ""
        opp = WEST if ms[sig]["east"] else (EAST if ms[sig]["west"] else set())
        prim_ok = bool(key_markets.get(prim, set()) & opp)
        downgrade.append(dict(sig=sig, primary=prim, primary_ok=prim_ok,
                              markets=sorted(g["countries"])))
    stats = dict(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db=str(db_path),
        combo_products=total_combo_products,
        combo_signatures=len(all_sigs),
        signatures_in_both_regions=len(cross_sigs),
        exact_signatures=len(exact),
        exact_products=sum(groups[s]["n"] for s in exact),
        overlap_signatures=len(overlap),
        overlap_products=sum(groups[s]["n"] for s in overlap),
        none_signatures=len(none),
        none_products=sum(groups[s]["n"] for s in none),
        raw_combo_products=d["raw_combo"],
        canonical_dedupe_dropped=d["raw_combo"] - total_combo_products,
        site_combo_pages_raw_sids=d["raw_sid_sets"],
        exact_rate_signatures=round(rate_sig, 4),
        exact_rate_products=round(rate_prod, 4),
        east_side_coverage=round(east_cover, 4),
        west_side_coverage=round(west_cover, 4),
        none_with_primary_available=sum(1 for x in downgrade if x["primary_ok"]),
        none_primary_unavailable=sum(1 for x in downgrade if not x["primary_ok"]),
        east_only=sum(1 for s in all_sigs if region(s) == "east"),
        west_only=sum(1 for s in all_sigs if region(s) == "west"),
        by_market={c: sum(1 for s in all_sigs if ms[s]["east"] and c in ms[s]["east"])
                   + sum(1 for s in all_sigs if ms[s]["west"] and c in ms[s]["west"])
                   for c in sorted(EAST | WEST)},
    )
    # 写 CSV：每个（签名 × 国家）一行
    rows = []
    for sig in sorted(all_sigs, key=lambda x: (-groups[x]["n"], x)):
        g = groups[sig]
        mt = matches[sig]
        prim = g["primary"].most_common(1)[0][0] if g["primary"] else ""
        for country in sorted(g["countries"]):
            pid_list = g["products"][country]
            brands = [b for b, _ in g["brands"][country].most_common(3)]
            forms = [f for f, _ in g["forms"].most_common(1)]
            strength = [s for s, _ in g["strengths"].most_common(1)]
            match_markets = [c for c in mt["markets"] if c != country]
            match_products = sum(g["countries"].get(c, 0) for c in match_markets)
            rows.append(dict(
                signature=sig,
                combo_slug=combo_slug(g["keys"]),
                country=country,
                n_products=len(pid_list),
                brands="; ".join(brands),
                form_release=forms[0] if forms else "",
                strength_sig=strength[0] if strength else "",
                match_strength=mt["strength"],
                match_markets="|".join(match_markets),
                match_products=match_products,
                matched_signatures="|".join(mt["matched"]),
                overlap_ratio=mt["overlap"],
                primary_ingredient=prim,
                primary_cross_market="yes" if (key_markets.get(prim, set()) &
                                               (WEST if country in EAST else EAST)) else "no",
                sample_product_id=pid_list[0] if pid_list else "",
            ))
    if not args.dry_run:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        TMP.mkdir(parents=True, exist_ok=True)
        (TMP / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
        # 样例
        want = {
            "metformin+glibenclamide": ("metformin", "glibenclamide"),
            "amoxicillin+clavulanic": ("amoxicillin", "clavulanic-acid"),
            "acetaminophen+amantadine": ("acetaminophen", "amantadine"),
        }
        lines = []
        for label, keys in want.items():
            hits = [s for s in all_sigs if set(keys).issubset(set(groups[s]["keys"]))]
            hits.sort(key=lambda s: -groups[s]["n"])
            lines.append(f"== {label}: {len(hits)} 个集合")
            for s in hits[:4]:
                mt = matches[s]
                lines.append(f"  {s}  products={groups[s]['n']}  markets={sorted(groups[s]['countries'])}"
                             f"  match={mt['strength']} {mt['markets']} overlap={mt['overlap']}")
        ov = sorted([s for s in all_sigs if matches[s]["strength"] == "overlap"],
                    key=lambda x: -groups[x]["n"])
        lines.append("== overlap 样例（Jaccard>=0.8）")
        for s in ov[:5]:
            mt = matches[s]
            lines.append(f"  {s}  products={groups[s]['n']}  markets={sorted(groups[s]['countries'])}"
                         f"  ↔ {mt['matched'][0]}  overlap={mt['overlap']}")
            lines.append(f"      matched markets={mt['markets']}")
        (TMP / "samples.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"DB: {db_path}")
    for k, v in stats.items():
        if k not in ("generated_at", "db", "by_market"):
            print(f"  {k}: {v}")
    print("  按市场签名数:", stats["by_market"])
    print("\n样例（二甲双胍+格列本脲 / 阿莫西林+克拉维酸 / 复方氨酚烷胺）:")
    print((TMP / "samples.txt").read_text(encoding="utf-8")
          if (TMP / "samples.txt").exists() else "")
    print(f"\n输出: {OUT}（{len(rows)} 行）" if not args.dry_run else "\n(dry-run，未写文件)")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
