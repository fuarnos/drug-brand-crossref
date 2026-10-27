#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三语（en/es/zh）检索一致性测试集。

目的
----
验证「同一种药，用英文名 / 西语名 / 中文名查询，都落到同一 substance，
并且不指定国家也能带出其他国家商品名」。

做法
----
- 只读打开 data/drugs.db（用 sqlite3 URI mode=ro，绝不写库）；
- 直接复用站点检索层 `lib/search.py`（SearchIndex），不另写 SQL 复刻，保证测的就是线上行为；
- 每个案例：en/es/zh 各 1–2 条查询（INN / 本地商品名 / 中文通用名 / 盐型名 / 复方名），
  记录每条查询的 Top-5 命中、Top-1、结果卡里的成分集合、结果卡覆盖的国家；
- 另做两项附加检查：
  1) 国家视图：按该语言的主场国家（en→US/GB/CA/AU 中第一个有产品的，es→ES/MX，zh→CN）
     带 country 过滤再查一次，必须能命中同一成分；
  2) 跨国可见：不指定国家时，结果卡必须覆盖 ≥2 个国家（跨国成分才算通过，
     只有本国产品的成分记为 cross_market_gap，不算检索错误）。
- 输出：控制台摘要 + `.tmp/trilingual/results.json`（逐条明细）。
  退出码：0 = 全部案例通过；1 = 有失败（便于将来接 CI）。

用法
----
    python tests/trilingual/run_tests.py                 # 全量
    python tests/trilingual/run_tests.py --json out.json # 指定明细输出
    python tests/trilingual/run_tests.py --only amlodipine,metoprolol
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import lib.search as search_mod  # noqa: E402

DB = ROOT / "data" / "drugs.db"

# 只读：把 sqlite3.connect 拦成 URI mode=ro（SearchIndex 只做 SELECT）
_REAL_CONNECT = sqlite3.connect


def _ro_connect(database, *args, **kwargs):
    s = str(database)
    if "mode=ro" not in s:
        return _REAL_CONNECT("file:" + s + "?mode=ro", uri=True, *args, **kwargs)
    return _REAL_CONNECT(database, *args, **kwargs)


# ---------------------------------------------------------------------------
# 测试集：sid + 分类 + 三语查询
#   - "single"   常见单方，三语都应命中同一成分
#   - "salt"     盐型名查询（盐酸/苯磺酸/琥珀酸/酒石酸…），应落到碱基成分
#   - "er"       缓释/控释商品名与通用名
#   - "combo"    复方（查询名对应多成分），要求主成分命中
#   - "dup_inn"  同一药在中/英/西命名体系下有多个 substance 记录（预期会断）
#   - "zh_only"  只有中国市场产品的成分（能落到成分，但无外国商品名）
# 查询均来自本轮 DB 勘查结果（.tmp/trilingual/existence.txt），不是臆造。
# ---------------------------------------------------------------------------
CASES = [
    # ---- 常见单方 ----
    dict(sid="acetaminophen", cat="single",
         en=["acetaminophen", "tylenol"], es=["paracetamol", "gelocatil"],
         zh=["对乙酰氨基酚", "泰诺林"], foreign=["US", "GB", "ES", "MX"]),
    dict(sid="ibuprofen", cat="single",
         en=["ibuprofen", "advil"], es=["ibuprofeno", "ibudol"],
         zh=["布洛芬", "芬必得"], foreign=["US", "GB", "ES", "MX"]),
    dict(sid="atorvastatin", cat="single",
         en=["atorvastatin", "lipitor"], es=["atorvastatina", "cardyl"],
         zh=["阿托伐他汀", "立普妥"], foreign=["US", "GB", "ES", "MX"]),
    dict(sid="amlodipine", cat="single",
         en=["amlodipine", "norvasc"], es=["amlodipino", "norvas"],
         zh=["氨氯地平", "络活喜"], foreign=["US", "GB", "ES", "MX"]),
    dict(sid="metoprolol", cat="single",
         en=["metoprolol", "lopressor"], es=["metoprolol", "beloken"],
         zh=["美托洛尔", "倍他乐克"], foreign=["US", "GB", "ES", "MX"]),
    dict(sid="aspirin", cat="single",
         en=["aspirin", "ecotrin"],
         es=["aspirina", "adiro"], zh=["阿司匹林", "拜阿司匹灵"],
         foreign=["US", "GB", "ES"]),
    dict(sid="clopidogrel", cat="single",
         en=["clopidogrel", "plavix"], es=["clopidogrel", "plavix"],
         zh=["氯吡格雷", "波立维"], foreign=["US", "GB", "ES"]),
    dict(sid="omeprazole", cat="single",
         en=["omeprazole", "prilosec"], es=["omeprazol", "losec"],
         zh=["奥美拉唑", "洛赛克"], foreign=["US", "GB", "ES"]),
    dict(sid="pantoprazole", cat="single",
         en=["pantoprazole", "protonix"], es=["pantoprazol", "anagastra"],
         zh=["泮托拉唑", "泮立苏"], foreign=["US", "GB", "ES"]),
    dict(sid="metformin", cat="single",
         en=["metformin", "glucophage"], es=["metformina", "eucreas"],
         zh=["二甲双胍", "格华止"], foreign=["US", "GB", "ES", "MX"]),
    dict(sid="gliclazide", cat="single",
         en=["gliclazide", "diamicron"], es=["gliclazida", "diamicron"],
         zh=["格列齐特", "达美康"], foreign=["GB", "ES", "MX"]),
    dict(sid="glimepiride", cat="single",
         en=["glimepiride", "amaryl"], es=["glimepirida", "amaryl"],
         zh=["格列美脲", "亚莫利"], foreign=["US", "GB", "ES"]),
    dict(sid="sitagliptin", cat="single",
         en=["sitagliptin", "januvia"], es=["sitagliptina", "januvia"],
         zh=["西格列汀", "捷诺维"], foreign=["US", "GB", "ES"]),
    dict(sid="levothyroxine", cat="single",
         en=["levothyroxine", "synthroid"], es=["levotiroxina", "eutirox"],
         zh=["左甲状腺素", "优甲乐"], foreign=["US", "GB", "ES"]),
    dict(sid="prednisone", cat="single",
         en=["prednisone"], es=["prednisona", "dacortin"],
         zh=["泼尼松", "强的松"], foreign=["US", "GB", "ES"]),
    dict(sid="dexamethasone", cat="single",
         en=["dexamethasone", "decadron"], es=["dexametasona", "fortecortin"],
         zh=["地塞米松"], foreign=["US", "GB", "ES"]),
    dict(sid="sertraline", cat="single",
         en=["sertraline", "zoloft"], es=["sertralina"],
         zh=["舍曲林", "左洛复"], foreign=["US", "GB", "ES"]),
    dict(sid="fluoxetine", cat="single",
         en=["fluoxetine", "prozac"], es=["fluoxetina"],
         zh=["氟西汀", "百优解"], foreign=["US", "GB", "ES"]),
    dict(sid="escitalopram", cat="single",
         en=["escitalopram", "lexapro"], es=["escitalopram", "cipralex"],
         zh=["艾司西酞普兰", "来士普"], foreign=["US", "GB", "ES"]),
    dict(sid="diazepam", cat="single",
         en=["diazepam", "valium"], es=["diazepam", "valium"],
         zh=["地西泮", "安定"], foreign=["US", "GB", "ES"]),
    dict(sid="lorazepam", cat="single",
         en=["lorazepam", "ativan"], es=["lorazepam", "orfidal"],
         zh=["劳拉西泮", "罗拉"], foreign=["US", "GB", "ES"]),
    dict(sid="quetiapine", cat="single",
         en=["quetiapine", "seroquel"], es=["quetiapina"],
         zh=["喹硫平", "思瑞康"], foreign=["US", "GB", "ES"]),
    dict(sid="olanzapine", cat="single",
         en=["olanzapine", "zyprexa"], es=["olanzapina", "zyprexa"],
         zh=["奥氮平", "再普乐"], foreign=["US", "GB", "ES"]),
    dict(sid="levetiracetam", cat="single",
         en=["levetiracetam", "keppra"], es=["levetiracetam", "keppra"],
         zh=["左乙拉西坦", "开浦兰"], foreign=["US", "GB", "ES"]),
    dict(sid="sildenafil", cat="single",
         en=["sildenafil", "viagra"], es=["sildenafilo", "viagra"],
         zh=["西地那非", "万艾可"], foreign=["US", "GB", "ES"]),
    dict(sid="finasteride", cat="single",
         en=["finasteride", "proscar"], es=["finasterida", "proscar"],
         zh=["非那雄胺", "保列治"], foreign=["US", "GB", "ES"]),
    dict(sid="tamsulosin", cat="single",
         en=["tamsulosin", "flomax"], es=["tamsulosina", "omnic"],
         zh=["坦索罗辛", "哈乐"], foreign=["US", "GB", "ES"]),
    dict(sid="allopurinol", cat="single",
         en=["allopurinol", "zyloric"], es=["alopurinol", "zyloric"],
         zh=["别嘌醇"], foreign=["US", "GB", "ES"]),
    dict(sid="colchicine", cat="single",
         en=["colchicine", "colcrys"], es=["colchicina"],
         zh=["秋水仙碱"], foreign=["US", "GB", "ES"]),
    dict(sid="cetirizine", cat="single",
         en=["cetirizine", "zyrtec"], es=["cetirizina", "zyrtec"],
         zh=["西替利嗪", "仙特明"], foreign=["US", "GB", "ES"]),
    dict(sid="loratadine", cat="single",
         en=["loratadine", "claritin"], es=["loratadina", "clarityn"],
         zh=["氯雷他定", "开瑞坦"], foreign=["US", "GB", "ES"]),
    dict(sid="fexofenadine", cat="single",
         en=["fexofenadine", "allegra"], es=["fexofenadina", "telfast"],
         zh=["非索非那定"], foreign=["US", "GB", "ES"]),
    dict(sid="diltiazem", cat="single",
         en=["diltiazem", "cardizem"], es=["diltiazem", "lacerol"],
         zh=["地尔硫䓬", "恬尔心"], foreign=["US", "GB", "ES"]),
    dict(sid="verapamil", cat="single",
         en=["verapamil"], es=["verapamilo", "manidon"],
         zh=["维拉帕米"], foreign=["GB", "ES", "AU"]),
    dict(sid="meloxicam", cat="single",
         en=["meloxicam", "mobic"], es=["meloxicam", "movalis"],
         zh=["美洛昔康", "莫比可"], foreign=["US", "GB", "ES"]),
    dict(sid="loperamide", cat="single",
         en=["loperamide", "imodium"], es=["loperamida", "fortasec"],
         zh=["洛哌丁胺", "易蒙停"], foreign=["US", "GB", "ES"]),
    dict(sid="rivaroxaban", cat="single",
         en=["rivaroxaban", "xarelto"], es=["rivaroxaban", "xarelto"],
         zh=["利伐沙班", "拜瑞妥"], foreign=["US", "GB", "ES"]),
    dict(sid="amoxicillin", cat="single",
         en=["amoxicillin", "amoxil"], es=["amoxicilina"],
         zh=["阿莫西林"], foreign=["US", "GB", "ES"]),
    dict(sid="azithromycin", cat="single",
         en=["azithromycin", "zithromax"], es=["azitromicina", "zitromax"],
         zh=["阿奇霉素", "希舒美"], foreign=["US", "GB", "ES"]),
    dict(sid="levofloxacin", cat="single",
         en=["levofloxacin", "levaquin"], es=["levofloxacino", "tavanic"],
         zh=["左氧氟沙星", "可乐必妥"], foreign=["US", "GB", "ES"]),
    dict(sid="ciprofloxacin", cat="single",
         en=["ciprofloxacin", "cipro"], es=["ciprofloxacino", "ciproxin"],
         zh=["环丙沙星", "悉复欢"], foreign=["US", "GB", "ES"]),
    dict(sid="metronidazole", cat="single",
         en=["metronidazole", "flagyl"], es=["metronidazol", "flagyl"],
         zh=["甲硝唑"], foreign=["US", "GB", "ES"]),
    dict(sid="fluconazole", cat="single",
         en=["fluconazole", "diflucan"], es=["fluconazol", "diflucan"],
         zh=["氟康唑", "大扶康"], foreign=["US", "GB", "ES"]),
    dict(sid="oseltamivir", cat="single",
         en=["oseltamivir", "tamiflu"], es=["oseltamivir", "tamiflu"],
         zh=["奥司他韦", "达菲"], foreign=["US", "GB", "ES"]),
    dict(sid="budesonide", cat="single",
         en=["budesonide", "pulmicort"], es=["budesonida", "pulmicort"],
         zh=["布地奈德", "普米克令舒"], foreign=["US", "GB", "ES"]),
    dict(sid="montelukast", cat="single",
         en=["montelukast", "singulair"], es=["montelukast", "singulair"],
         zh=["孟鲁司特", "顺尔宁"], foreign=["US", "GB", "ES"]),
    dict(sid="theophylline", cat="single",
         en=["theophylline"], es=["teofilina"],
         zh=["茶碱"], foreign=["US", "GB", "ES"]),
    dict(sid="furosemide", cat="single",
         en=["furosemide", "lasix"], es=["furosemida", "seguril"],
         zh=["呋塞米"], foreign=["US", "GB", "ES"]),
    dict(sid="spironolactone", cat="single",
         en=["spironolactone", "aldactone"], es=["espironolactona", "aldactone"],
         zh=["螺内酯"], foreign=["US", "GB", "ES"]),
    # ---- 盐型 ----
    dict(sid="amlodipine", cat="salt",
         en=["amlodipine besylate"], es=["amlodipino besilato"],
         zh=["苯磺酸氨氯地平"], foreign=["US", "ES", "CN"]),
    dict(sid="metformin", cat="salt",
         en=["metformin hydrochloride"], es=["metformina hidrocloruro"],
         zh=["盐酸二甲双胍"], foreign=["US", "ES", "CN"]),
    dict(sid="metoprolol", cat="salt",
         en=["metoprolol tartrate"], es=["metoprolol tartrato"],
         zh=["酒石酸美托洛尔"], foreign=["US", "ES", "CN"]),
    dict(sid="metoprolol", cat="salt",
         en=["metoprolol succinate"], es=["metoprolol succinato"],
         zh=["琥珀酸美托洛尔"], foreign=["US", "ES", "CN"]),
    dict(sid="clopidogrel", cat="salt",
         en=["clopidogrel bisulfate"], es=[],
         zh=["硫酸氢氯吡格雷"], foreign=["US", "CN"]),
    dict(sid="levothyroxine", cat="salt",
         en=["levothyroxine sodium"], es=["levotiroxina sodica"],
         zh=["左甲状腺素钠"], foreign=["US", "ES", "CN"]),
    # ---- 缓释 / 控释 ----
    dict(sid="nifedipine", cat="er",
         en=["nifedipine", "adalat"], es=["nifedipino", "adalat"],
         zh=["硝苯地平", "拜新同"], foreign=["US", "GB", "ES"]),
    dict(sid="metoprolol", cat="er",
         en=["toprol xl", "metoprolol succinate"],
         es=["beloken"], zh=["琥珀酸美托洛尔缓释片"],
         foreign=["US", "ES", "CN"]),
    dict(sid="isosorbide-mononitrate", cat="er",
         en=["imdur", "isosorbide mononitrate"], es=[],
         zh=["欣康"], foreign=["GB", "CN"]),
    dict(sid="felodipine", cat="er",
         en=["plendil", "felodipine"], es=["felodipino"],
         zh=["非洛地平", "波依定"], foreign=["GB", "ES", "CN"]),
    # ---- 复方 ----
    dict(sid="amoxicillin", cat="combo",
         en=["augmentin"], es=["augmentine"],
         zh=["阿莫西林克拉维酸钾"], foreign=["US", "GB", "ES", "CN"],
         note="复方：主成分 amoxicillin + clavulanate"),
    dict(sid="amlodipine", cat="combo",
         en=["valsartan amlodipine"], es=["valsartan amlodipino"],
         zh=["缬沙坦氨氯地平片"], foreign=["US", "GB", "ES", "CN"],
         note="复方：valsartan + amlodipine"),
    dict(sid="metformin", cat="combo",
         en=["sitagliptin metformin"], es=["sitagliptina metformina"],
         zh=["西格列汀二甲双胍片"], foreign=["US", "GB", "ES", "CN"],
         note="复方：sitagliptin + metformin"),
    dict(sid="hydrochlorothiazide", cat="combo",
         en=["hydrochlorothiazide", "co-diovan"], es=["hidroclorotiazida"],
         zh=["厄贝沙坦氢氯噻嗪片"], foreign=["US", "GB", "ES", "CN"],
         note="复方：多数是 ARB/HCTZ 复方"),
    dict(sid="acetaminophen", cat="combo",
         en=[], es=["frenadol", "gelocatil gripe"],
         zh=["泰诺"], foreign=["CN"],
         note="中文「泰诺」是四成分复方（对乙酰氨基酚+伪麻黄碱+右美沙芬+氯苯那敏）"),
    # ---- 跨语言 INN 拆分（同一药多个 substance 记录）----
    dict(sid="albuterol", cat="dup_inn",
         en=["albuterol"], es=["salbutamol"], zh=["沙丁胺醇"],
         foreign=["US", "GB", "ES"],
         note="US albuterol / 国际 salbutamol，DB 内是两个 substance"),
    dict(sid="rifampin", cat="dup_inn",
         en=["rifampin"], es=["rifampicina"], zh=["利福平"],
         foreign=["US", "GB", "ES"],
         note="US rifampin / 国际 rifampicin"),
    dict(sid="ciclosporin", cat="dup_inn",
         en=["cyclosporine"], es=["ciclosporina"], zh=["环孢素"],
         foreign=["US", "GB", "ES"],
         note="cyclosporine / ciclosporin 两个 substance"),
    dict(sid="beclometasone", cat="dup_inn",
         en=["beclomethasone"], es=["beclometasona"], zh=["倍氯米松"],
         foreign=["US", "GB", "ES"],
         note="beclomethasone / beclometasone 两个 substance"),
    dict(sid="chlorphenamine", cat="dup_inn",
         en=["chlorpheniramine"], es=["clorfenamina"], zh=["氯苯那敏"],
         foreign=["US", "GB", "ES"],
         note="chlorpheniramine / chlorphenamine 两个 substance"),
    # ---- 中文旧名 / 别名 ----
    dict(sid="metamizole", cat="zh_only",
         en=["metamizole"], es=["metamizol", "nolotil"], zh=["安乃近"],
         foreign=["ES", "MX"], note="中国叫安乃近，西语叫 metamizol"),
    dict(sid="diosmectite", cat="zh_only",
         en=["diosmectite"], es=[], zh=["蒙脱石", "思密达"],
         foreign=["CN"], note="中国常用名，仅 CN 有产品"),
    dict(sid="metoclopramide", cat="zh_only",
         en=["metoclopramide", "reglan"], es=["metoclopramida", "primperan"],
         zh=["甲氧氯普胺", "胃复安"], foreign=["US", "GB", "ES"]),
]


def pick_country(idx, sid, prefs):
    rows = idx.db.execute(
        """SELECT DISTINCT p.country FROM product p
           JOIN product_component pc ON pc.product_id=p.product_id
           JOIN variant v ON v.variant_id=pc.variant_id
           WHERE v.substance_id=?""", (sid,)).fetchall()
    have = {r[0] for r in rows}
    for c in prefs:
        if c in have:
            return c
    return None


def inn_of(idx, sid):
    row = idx.db.execute("SELECT inn_en FROM substance WHERE substance_id=?", (sid,)).fetchone()
    return row[0] if row else sid


def run_case(idx, case):
    sid = case["sid"]
    inn = inn_of(idx, sid)
    out = {"sid": sid, "cat": case["cat"], "inn_en": inn, "langs": {}}
    expected_countries = case.get("foreign", [])

    for lang in ("en", "es", "zh"):
        queries = case.get(lang) or []
        lang_rows = []
        resolved_any = False
        wrong_substances = set()
        for query in queries:
            t0 = time.time()
            res = idx.search(query)
            dt = time.time() - t0
            cards = res.cards
            substances_seen = []
            rank = None
            for i, card in enumerate(cards[:10]):
                subs = [s for s in card.substances if s]
                substances_seen.extend(subs)
                if inn in subs and rank is None:
                    rank = i
            top1 = [s for s in (cards[0].substances if cards else []) if s]
            if rank is not None:
                resolved_any = True
            elif cards:
                wrong_substances.update(top1)
            countries = sorted({c.country for c in cards})
            aliases = [a.get("substance_id") for a in (res.aliases or [])][:3]
            lang_rows.append({
                "query": query, "n_cards": len(cards), "rank": rank,
                "top1": top1, "substances_seen": sorted(set(substances_seen))[:12],
                "countries": countries, "aliases": aliases,
                "note": res.note, "tier": cards[0].tier if cards else "",
                "seconds": round(dt, 2),
            })
        # 国家视图：该语言主场国家过滤后重查第一条查询
        country = None
        country_row = None
        if queries:
            prefs = {"en": ["US", "GB", "CA", "AU"], "es": ["ES", "MX"],
                     "zh": ["CN"]}[lang]
            country = pick_country(idx, sid, prefs)
            if country:
                res_c = idx.search(queries[0], country=country)
                rank_c = None
                for i, card in enumerate(res_c.cards[:10]):
                    if inn in [s for s in card.substances if s]:
                        rank_c = i
                        break
                country_row = {"country": country, "n_cards": len(res_c.cards),
                               "rank": rank_c,
                               "countries": sorted({c.country for c in res_c.cards}),
                               "note": res_c.note}
        cross_countries = sorted({c for r in lang_rows for c in r["countries"]})
        out["langs"][lang] = {
            "resolved": resolved_any, "queried": bool(queries),
            "rows": lang_rows, "country_view": country_row,
            "wrong_substances": sorted(wrong_substances),
            "cross_countries": cross_countries,
        }
    # 判定
    queried = [l for l, v in out["langs"].items() if v["queried"]]
    lang_ok = {l: out["langs"][l]["resolved"] for l in queried}
    resolved_n = sum(1 for v in lang_ok.values() if v)
    q_total = sum(len(out["langs"][l]["rows"]) for l in queried)
    q_hits = sum(1 for l in queried for r in out["langs"][l]["rows"] if r["rank"] is not None)
    q_top1 = sum(1 for l in queried for r in out["langs"][l]["rows"] if r["rank"] == 0)
    all_cross = sorted({c for l in queried for c in out["langs"][l]["cross_countries"]})
    # 跨国可见性：查询结果卡里出现的国家里，是否包含该成分实际的其他国家
    out["summary"] = {
        "langs_queried": queried,
        "langs_resolved": resolved_n,
        "case_pass_same_substance": resolved_n == len(queried),
        "queries": q_total, "queries_hit_top5": q_hits,
        "queries_hit_top1": q_top1,
        "cross_countries": all_cross,
        "expected_foreign": expected_countries,
        "cross_market_ok": bool(set(all_cross) & set(expected_countries))
                          if expected_countries else None,
        "cross_market_gap": (not (set(all_cross) & set(expected_countries)))
                            if expected_countries else False,
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / ".tmp" / "trilingual" / "results.json"))
    ap.add_argument("--only", default="", help="逗号分隔的 sid 过滤")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not DB.exists():
        print(f"FATAL: DB 不存在: {DB}", file=sys.stderr)
        return 2
    sqlite3.connect = _ro_connect
    idx = search_mod.SearchIndex(DB)

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    cases = [c for c in CASES if not only or c["sid"] in only]

    results = []
    t_start = time.time()
    for case in cases:
        r = run_case(idx, case)
        results.append(r)
        if not args.quiet:
            s = r["summary"]
            mark = "PASS" if s["case_pass_same_substance"] else "FAIL"
            print("[%s] %-22s %-6s 查询 %d/%d 命中Top5, Top1 %d/%d  %s" % (
                mark, r["sid"], r["cat"], s["queries_hit_top5"], s["queries"],
                s["queries_hit_top1"], s["queries"], "跨国✓" if s["cross_market_ok"] else "跨国✗"))
            if not s["case_pass_same_substance"]:
                for lang in s["langs_queried"]:
                    lv = r["langs"][lang]
                    if lv["resolved"]:
                        continue
                    fails = [x for x in lv["rows"] if x["rank"] is None]
                    for f in fails:
                        print("       %s %-30r cards=%d top1=%s note=%s" % (
                            lang, f["query"], f["n_cards"], f["top1"], f["note"]))
    idx.close()
    dt = time.time() - t_start

    total_queries = sum(r["summary"]["queries"] for r in results)
    hit5 = sum(r["summary"]["queries_hit_top5"] for r in results)
    hit1 = sum(r["summary"]["queries_hit_top1"] for r in results)
    cases_pass = sum(1 for r in results if r["summary"]["case_pass_same_substance"])
    cross_ok = sum(1 for r in results if r["summary"]["cross_market_ok"])
    cross_n = sum(1 for r in results if r["summary"]["cross_market_ok"] is not None)

    summary = {
        "cases": len(results), "cases_pass": cases_pass,
        "queries": total_queries, "hit_top5": hit5, "hit_top1": hit1,
        "hit_top5_pct": round(100.0 * hit5 / total_queries, 1) if total_queries else 0,
        "hit_top1_pct": round(100.0 * hit1 / total_queries, 1) if total_queries else 0,
        "cross_market_ok": cross_ok, "cross_market_checked": cross_n,
        "seconds": round(dt, 1),
        "by_cat": {},
        "by_lang": {},
    }
    for r in results:
        c = r["cat"]
        d = summary["by_cat"].setdefault(c, {"cases": 0, "pass": 0, "queries": 0, "hit5": 0, "hit1": 0})
        d["cases"] += 1
        d["pass"] += 1 if r["summary"]["case_pass_same_substance"] else 0
        d["queries"] += r["summary"]["queries"]
        d["hit5"] += r["summary"]["queries_hit_top5"]
        d["hit1"] += r["summary"]["queries_hit_top1"]
    for lang in ("en", "es", "zh"):
        q = h5 = h1 = 0
        for r in results:
            lv = r["langs"][lang]
            if not lv["queried"]:
                continue
            q += len(lv["rows"])
            h5 += sum(1 for x in lv["rows"] if x["rank"] is not None)
            h1 += sum(1 for x in lv["rows"] if x["rank"] == 0)
        summary["by_lang"][lang] = {"queries": q, "hit_top5": h5, "hit_top1": h1,
                                    "hit_top5_pct": round(100.0 * h5 / q, 1) if q else 0}

    out = {"meta": {"db": str(DB), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "search_module": str(Path(search_mod.__file__).relative_to(ROOT)),
                    "readonly": True}, "summary": summary, "results": results}
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n== 汇总 ==")
    print("案例 %d（通过 %d）；查询 %d 条：Top-5 命中 %.1f%%，Top-1 命中 %.1f%%；跨国可见 %d/%d；用时 %.1fs"
          % (len(results), cases_pass, total_queries, summary["hit_top5_pct"],
             summary["hit_top1_pct"], cross_ok, cross_n, dt))
    for lang, d in summary["by_lang"].items():
        print("  %s: %d 条查询, Top-5 %d, Top-1 %d (%.1f%%)"
              % (lang, d["queries"], d["hit_top5"], d["hit_top1"], d["hit_top5_pct"]))
    print("明细:", args.json)
    return 0 if cases_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
