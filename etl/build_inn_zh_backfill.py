#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中文成分名（substance.inn_zh）回填数据构建器。

数据来源（全部只读）：
  1. **CN 市场单成分产品的中文通用名**：`product(country='CN')`
     → `product_component`(单成分) → `variant` → `substance`；取 `product_name` 里
     `name_key.script='han'` 的名字，用 `ingest_nhsa.canonical_name` 剥掉剂型/限定词
     得到候选中文成分名（盐基保留，与现有 inn_zh 约定一致）。
  2. `data/cn_inn_overrides.csv` 中 `status=mergeable` 且 `en_substance_id` 即为目标
     成分的行：CN 中文名是人工确认的映射证据，优先采纳。
  3. 辅助词典（用于复方切分，避免把复方名当成分名）：
     - `substance.inn_zh` 现有值；
     - `data/cn_name_map.json` 的键（注册名）；
     - `reports/cn_aliases.csv` / `data/cn_aliases_final.csv` 的目标中文名；
     - `drug_term.label_zh`。

判定规则：
  * 只处理 **inn_zh 为空** 的 substance（不覆盖已有值）；
  * 只从 **单成分产品** 取候选（复方产品的名字不能当成分名；另用拆分词典兜底）；
  * 同成分多候选：多数派（share≥0.6）→ 采纳；否则用「去盐基聚合」回退（share≥0.6）；
    仍判不了 → 不采纳（记为 ambiguous）；
  * overrides 候选优先；若 overrides 的中文名带剂型/规格尾巴（如「紫杉醇聚合物胶束」），
    会按词表清洗/回退到产品候选；
  * 同一中文名被推荐给多个 substance（如 mannitol / manitol 西语重复）或与现有
    inn_zh 重名 → 全部丢弃（记 conflict）；
  * confidence：override→沿用人工文件 confidence；产品多数派 share≥0.8 且 ≥3 产品 → high，
    ≥3 产品 → medium，其余 low；去盐基回退最多 medium。

产物：`data/inn_zh_backfill.csv`
    substance_id,inn_en,zh_candidate,confidence,method,count,share,variants,evidence
统计：`.tmp/inn-zh/build_stats.json`

用法：
    python etl/build_inn_zh_backfill.py            # 生成 CSV（只读 DB）
    python etl/build_inn_zh_backfill.py --dry-run  # 只打印统计不落盘
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
sys.path.insert(0, str(ROOT / "etl"))
from ingest_nhsa import canonical_name, reduction_chain  # noqa: E402

DB = ROOT / "data" / "drugs.db"
OUT = ROOT / "data" / "inn_zh_backfill.csv"
STATS = ROOT / ".tmp" / "inn-zh" / "build_stats.json"
OVERRIDES = ROOT / "data" / "cn_inn_overrides.csv"
CN_NAME_MAP = ROOT / "data" / "cn_name_map.json"
CN_ALIASES = ROOT / "reports" / "cn_aliases.csv"
CN_ALIASES_FINAL = ROOT / "data" / "cn_aliases_final.csv"

RE_HAN = re.compile(r"^[\u4e00-\u9fff]+$")
# 复方/多成分/营养类字样（整词命中即不当成分名）
COMBO_WORDS = ("复方", "多维", "五维", "四维", "三维", "二维", "复合", "元素", "电解质",
               "维D", "维生素", "氨基酸", "葡萄糖", "氯化钠", "人工牛黄", "曲咪新",
               "双唑泰", "小儿", "儿童", "多种", "聚合物", "胶束", "脂质体", "微球",
               "纳米", "阴道", "膨胀", "缓释", "控释", "肠溶", "分散", "咀嚼")
# 清洗 overrides / 候选名时，从尾部剥掉的剂型/规格/包装词（长词优先）
TAIL_JUNK = ("聚合物胶束", "脂质体", "微球", "纳米", "阴道膨胀", "阴道泡腾", "阴道片",
             "肠溶胶囊", "肠溶片", "缓释胶囊", "缓释片", "控释片", "分散片", "咀嚼片",
             "含漱液", "含片", "泡腾片", "注射液", "滴眼液", "乳膏", "软膏", "凝胶",
             "喷雾剂", "鼻喷雾剂", "贴膏", "贴片", "栓", "洗剂", "溶液", "颗粒",
             "胶囊", "片", "丸", "散", "膏", "膜", "贴", "滴", "喷", "擦", "涂")
# 候选结尾单字（剥不干净时出现「硫软」「克霉唑阴道膨胀」这类残片 → 拒绝）
BAD_TAIL = "软硬凝喷滴注含洗搽贴栓膜散丸粉袋支瓶膏胀"
SUSPECT_ANY = ("复方", "多维", "复合", "维生", "氨基", "葡萄", "氯化", "聚合物",
               "胶束", "脂质体", "微球", "纳米", "阴道", "膨胀", "缓释", "控释",
               "肠溶", "分散", "咀嚼", "含漱", "泡腾")


def clean(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def strip_tail(name: str) -> str:
    """反复剥掉结尾的剂型/规格词（overrides 的中文名可能残留剂型）。"""
    s = clean(name)
    changed = True
    while changed:
        changed = False
        for t in TAIL_JUNK:
            if s.endswith(t) and len(s) > len(t) + 1:
                s = s[: -len(t)].strip()
                changed = True
                break
    return s


def valid_candidate(c: str) -> bool:
    if not (2 <= len(c) <= 9):
        return False
    if not RE_HAN.fullmatch(c):
        return False
    if c[-1] in BAD_TAIL:
        return False
    if any(w in c for w in SUSPECT_ANY):
        return False
    if c.startswith(("复方", "多维", "小儿", "儿童")):
        return False
    return True


def base_of(name: str) -> str:
    """去盐/酯，得到碱基中文名（仅在多数派不够时回退用）。"""
    c = canonical_name(name)
    chain = [x for x in reduction_chain(c) if 3 <= len(x) <= 9 and x != c]
    return chain[-1] if chain else c


# ---------------------------------------------------------------------------
# 读取 DB 与辅助词典
# ---------------------------------------------------------------------------
def load_known(db: sqlite3.Connection) -> set[str]:
    known: set[str] = set()

    def add(z: str) -> None:
        z = clean(z)
        if not z:
            return
        known.add(z)
        try:
            known.add(canonical_name(z))
            known.add(base_of(z))
        except Exception:  # noqa: BLE001
            pass

    for (z,) in db.execute("SELECT inn_zh FROM substance WHERE inn_zh IS NOT NULL"
                           " AND trim(inn_zh)<>''"):
        add(z)
    for (z,) in db.execute("SELECT label_zh FROM drug_term WHERE label_zh IS NOT NULL"
                           " AND trim(label_zh)<>''"):
        add(z)
    for path, field in ((OVERRIDES, "zh_name"), (CN_ALIASES, "target_cn"),
                        (CN_ALIASES_FINAL, "name")):
        if not path.exists():
            continue
        for row in csv.DictReader(open(path, encoding="utf-8-sig")):
            add(row.get(field) or "")
    if CN_NAME_MAP.exists():
        data = json.load(open(CN_NAME_MAP, encoding="utf-8"))
        for key in (data.get("map") or {}):
            add(strip_tail(key))
    return known


def looks_combo(name: str, known: set[str]) -> bool:
    n = canonical_name(name)
    if any(w in n for w in COMBO_WORDS):
        return True
    parts, i, L = [], 0, len(n)
    while i < L:
        hit = None
        for ln in range(min(20, L - i), 1, -1):
            cand = n[i:i + ln]
            if cand in known:
                hit = cand
                break
        if hit:
            parts.append(hit)
            i += len(hit)
        else:
            i += 1
    return len(set(parts)) >= 2


def load(db: sqlite3.Connection) -> dict:
    known = load_known(db)
    empty: dict[str, str] = {}
    for sid, inn_en in db.execute(
            "SELECT substance_id, inn_en FROM substance WHERE"
            " (inn_zh IS NULL OR trim(inn_zh)='')"):
        # cn-* 已有 inn_zh；mx-es-* 是西语重复成分；inn_en 非 ASCII（Ácido… 等
        # 西语残留名）也跳过：中文名回填容易串到别的成分。
        if sid.startswith(("cn-", "mx-es-")):
            continue
        if not re.fullmatch(r"[A-Za-z0-9 ()\-,'/]+", inn_en or ""):
            continue
        empty[sid] = inn_en or ""
    # 现有 inn_zh（冲突检测）
    existing: dict[str, set[str]] = defaultdict(set)
    for sid, z in db.execute("SELECT substance_id, inn_zh FROM substance WHERE"
                             " inn_zh IS NOT NULL AND trim(inn_zh)<>''"):
        existing[clean(z)].add(sid)
    # 单成分 CN 产品中文名 → 候选
    cand: dict[str, Counter] = defaultdict(Counter)
    sample_pids: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    skipped = Counter()
    for r in db.execute(
            """SELECT v.substance_id AS sid, nk.norm AS name, p.product_id AS pid
               FROM product p
               JOIN product_component pc ON pc.product_id=p.product_id
               JOIN variant v ON v.variant_id=pc.variant_id
               JOIN (SELECT product_id FROM product_component
                     GROUP BY product_id HAVING COUNT(*)=1) s
                 ON s.product_id=p.product_id
               JOIN product_name pn ON pn.product_id=p.product_id
               JOIN name_key nk ON nk.key_id=pn.key_id
               WHERE p.country='CN' AND nk.script='han'"""):
        sid = r["sid"]
        if sid not in empty:
            continue
        name = clean(r["name"])
        if not name:
            continue
        if looks_combo(name, known):
            skipped["复方/多成分名"] += 1
            continue
        c = canonical_name(name)
        if not valid_candidate(c):
            skipped["剂型/规格残留或非法字符"] += 1
            continue
        cand[sid][c] += 1
        if len(sample_pids[sid][c]) < 3:
            sample_pids[sid][c].append(r["pid"])
    # overrides
    over: dict[str, list[dict]] = defaultdict(list)
    if OVERRIDES.exists():
        for row in csv.DictReader(open(OVERRIDES, encoding="utf-8-sig")):
            sid = (row.get("en_substance_id") or "").strip()
            if row.get("status") != "mergeable" or sid not in empty:
                continue
            over[sid].append(dict(zh=clean(row.get("zh_name") or ""),
                                  cn=row.get("cn_substance_id") or "",
                                  conf=(row.get("confidence") or "").strip(),
                                  ev=row.get("evidence_url") or ""))
    return dict(empty=empty, existing=existing, cand=cand, over=over,
                sample_pids=sample_pids, known=known, skipped=skipped)


# ---------------------------------------------------------------------------
# 决策
# ---------------------------------------------------------------------------
def decide(d: dict) -> tuple[dict, dict]:
    empty, cand, over = d["empty"], d["cand"], d["over"]
    decisions: dict[str, dict] = {}
    stats = Counter()
    for sid in empty:
        counter: Counter = cand.get(sid) or Counter()
        chosen = None
        if counter:
            total = sum(counter.values())
            top, n = counter.most_common(1)[0]
            share = n / total
            stats[f"候选变体数_{min(len(counter), 5)}"] += 1
            if share >= 0.6:
                chosen = dict(zh=top, method="product_majority", count=n, total=total,
                              share=round(share, 3), variants=len(counter),
                              pids=d["sample_pids"][sid].get(top, []))
            else:
                agg: Counter = Counter()
                for c, k in counter.items():
                    agg[base_of(c)] += k
                b, bn = agg.most_common(1)[0]
                bshare = bn / total
                if bshare >= 0.6 and valid_candidate(b):
                    chosen = dict(zh=b, method="product_base_aggregate", count=bn,
                                  total=total, share=round(bshare, 3),
                                  variants=len(counter), pids=[])
                    stats["base_aggregate"] += 1
                else:
                    stats["ambiguous"] += 1
        if over.get(sid):
            o = over[sid][0]
            o_zh = None
            sanitized = strip_tail(o["zh"])
            if counter and sanitized in counter:
                o_zh = sanitized
            elif counter:
                pref = [c for c in counter
                        if sanitized.startswith(c) and len(c) >= 2]
                pref.sort(key=len, reverse=True)
                if pref:
                    o_zh = pref[0]
            if o_zh is None and valid_candidate(sanitized):
                o_zh = sanitized
            if o_zh:
                chosen = dict(zh=o_zh, method="override",
                              count=len(counter) and sum(counter.values()) or 0,
                              total=sum(counter.values()) if counter else 0,
                              share=1.0, variants=len(counter), pids=[],
                              override_conf=o["conf"] or "medium",
                              override_ev=o["ev"], override_cn=o["cn"])
                stats["override_used"] += 1
        if chosen:
            decisions[sid] = chosen
    return decisions, stats


def resolve_conflicts(decisions: dict, existing: dict[str, set[str]]) -> tuple[dict, dict]:
    stats = Counter()
    by_zh: dict[str, set[str]] = defaultdict(set)
    for sid, x in decisions.items():
        by_zh[x["zh"]].add(sid)
    final: dict[str, dict] = {}
    for zh, sids in by_zh.items():
        if zh in existing:
            stats["与现有 inn_zh 重名（丢弃）"] += len(sids)
            continue
        if len(sids) > 1:
            # 优先非 mx-es 的英文 id；唯一才保留，否则视为歧义
            en = [s for s in sids if not s.startswith(("mx-es-", "cn-"))]
            if len(en) == 1:
                sid = en[0]
                final[sid] = decisions[sid]
                stats["同名多成分_保留英文id"] += 1
                stats["同名多成分_丢弃西语重复"] += len(sids) - 1
            else:
                stats["同形异义（多成分同名，丢弃）"] += len(sids)
            continue
        sid = next(iter(sids))
        final[sid] = decisions[sid]
    return final, stats


def confidence_of(x: dict) -> str:
    if x["method"] == "override":
        return x.get("override_conf") or "medium"
    if x["method"] == "product_majority":
        if x["share"] >= 0.8 and x["count"] >= 3:
            return "high"
        if x["count"] >= 3:
            return "medium"
        return "low"
    if x["method"] == "product_base_aggregate":
        return "medium" if x["share"] >= 0.8 else "low"
    return "low"




# ---------------------------------------------------------------------------
# task-127：v2 —— 236 个缺 inn_zh 成分补齐 + 旧回填可疑行修正（只读 DB，产出 CSV/SQL）
# ---------------------------------------------------------------------------
V2_OUT = ROOT / "data" / "inn_zh_backfill_v2.csv"
V2_TMP = ROOT / ".tmp" / "inn-zh2"
NHSA_URL = "https://code.nhsa.gov.cn/yp/toPublicGoodsData.html"
# 官方/药典中文名（人工核对；优先中国药典/INN 中文名，其次 NMPA/NHSA 注册名）
V2_OVERRIDES = {
    "glucose": "葡萄糖", "sodium-chloride": "氯化钠", "levofloxacin": "左氧氟沙星",
    "ascorbic-acid": "维生素C", "erythromycin": "红霉素", "aspirin": "阿司匹林",
    "diclofenac": "双氯芬酸", "cefuroxime": "头孢呋辛", "pyridoxine": "维生素B6",
    "thiamine": "维生素B1", "telmisartan": "替米沙坦", "ampicillin": "氨苄西林",
    "amino-acids": "氨基酸", "cyanocobalamin": "维生素B12", "potassium-chloride": "氯化钾",
    "riboflavin": "维生素B2", "ciprofloxacin": "环丙沙星", "zinc": "锌",
    "tocopherol": "维生素E", "retinol": "维生素A", "manitol": "甘露醇",
    "glucosamine": "氨基葡萄糖", "clavulanate": "克拉维酸", "triamcinolone": "曲安西龙",
    "vitamin-b-complex": "复合维生素B", "pentoxifilina": "己酮可可碱", "olmesartan": "奥美沙坦",
    "dextran-40": "右旋糖酐40", "ropivacaine": "罗哌卡因", "epoetin-alfa": "促红素",
    "theophylline": "茶碱", "gatifloxacin": "加替沙星", "valacyclovir": "伐昔洛韦",
    "calcium-phosphate": "磷酸钙", "methionine": "甲硫氨酸", "chlorhexidine": "氯己定",
    "heparin": "肝素", "sodium-iodide-i-131": "碘[131I]化钠", "penicillin-v": "青霉素V",
    "filgrastim": "非格司亭", "tramadol": "曲马多", "mx-es-cerebrolysin": "脑蛋白水解物",
    "ferrous": "亚铁", "macrogol": "聚乙二醇", "oral-rehydration-salts": "口服补液盐",
    "glimepiride": "格列美脲", "meloxicam": "美洛昔康", "cefpodoxime": "头孢泊肟",
    "phytonadione": "维生素K1", "tegafur": "替加氟", "iohexol": "碘海醇",
    "mx-es-levosalbutamol": "左沙丁胺醇", "cholecalciferol": "维生素D3",
    "inositol-nicotinate": "肌醇烟酸酯", "perindopril": "培哚普利",
    "ergocalciferol": "维生素D2", "interferon-alfa-2b": "干扰素α2b",
    "ticarcillin": "替卡西林", "calcium-chloride": "氯化钙", "sertraline": "舍曲林",
    "beclometasone": "倍氯米松", "aldesleukin": "阿地白介素",
    "technetium-tc-99m-sodium-pertechnetate": "高锝[99mTc]酸钠",
    "ferrous-gluconate": "葡萄糖酸亚铁", "trimebutine": "曲美布汀", "levodopa": "左旋多巴",
    "aminocaproic-acid": "氨基己酸", "phenobarbital": "苯巴比妥",
    "rosiglitazone": "罗格列酮", "mx-es-nifuratel": "硝呋太尔", "buprenorphine": "丁丙诺啡",
    "technetium-tc-99m-medronate": "锝[99mTc]亚甲基二膦酸盐",
    "technetium-tc-99m-sestamibi": "锝[99mTc]甲氧异腈", "morphine": "吗啡",
    "chlortetracycline": "金霉素", "tenofovir": "替诺福韦", "tiotropium": "噻托溴铵",
    "zoledronic-acid": "唑来膦酸", "hepatitis-b-immunoglobulin": "乙型肝炎人免疫球蛋白",
    "fructose": "果糖", "mx-es-difenidol": "地芬尼多", "sulfur": "硫",
    "dinoprostona": "地诺前列酮", "aceclofenac": "醋氯芬酸", "phenoxybenzamine": "酚苄明",
    "paliperidone": "帕利哌酮", "iomeprol": "碘美普尔", "calcitonina-salmon-sintetica": "鲑降钙素",
    "testosterone": "睾酮", "etoposido": "依托泊苷", "isotretinoin": "异维A酸",
    "glutamine": "谷氨酰胺", "insulina-isofana-nph": "精蛋白人胰岛素",
    "vardenafil": "伐地那非", "minocycline": "米诺环素", "carbenoxolona": "甘珀酸",
    "otilonio": "奥替溴铵", "mifepristone": "米非司酮", "mebrofenin": "依替菲宁",
    "fusidic-acid": "夫西地酸", "mx-es-pidotimod": "匹多莫德", "danazol": "达那唑",
    "sargramostim": "沙格司亭", "vacuna-anti-rabia": "狂犬病疫苗", "tetracaine": "丁卡因",
    "mycophenolate": "麦考酚", "levothyroxine": "左甲状腺素", "imipenem": "亚胺培南",
    "azelastine": "氮䓬斯汀", "cilastatin": "西司他丁", "aminosalicylic-acid": "对氨基水杨酸",
    "triptorelin": "曲普瑞林", "tolterodine": "托特罗定", "fluvastatin": "氟伐他汀",
    "sufentanil": "舒芬太尼", "micafungin": "米卡芬净", "foscarnet": "膦甲酸",
    "etomidate": "依托咪酯", "dalteparin": "达肝素", "clobetasona": "氯倍他松",
    "benzbromarone": "苯溴马隆", "alogliptin": "阿格列汀", "ziprasidone": "齐拉西酮",
    "vacuna-anti-virus-papiloma-humano": "人乳头瘤病毒疫苗", "clomifeno": "氯米芬",
    "sotalol": "索他洛尔", "magnesio-hidroxido": "氢氧化镁", "fentanyl": "芬太尼",
    "bario": "钡", "tuberculina-ppd": "结核菌素纯蛋白衍生物", "remifentanil": "瑞芬太尼",
    "polystyrene-sulfonate-calcium": "聚苯乙烯磺酸钙", "ginkgo-biloba": "银杏叶提取物",
    "amphotericin-b": "两性霉素B", "salmeterol": "沙美特罗", "indacaterol": "茚达特罗",
    "fluorescein": "荧光素", "decualinio": "地喹氯铵", "xylometazoline": "赛洛唑啉",
    "tirzepatide": "替尔泊肽", "salicilato-de-trolamina": "水杨酸三乙醇胺",
    "oxibuprocaina": "奥布卡因", "estradiol": "雌二醇",
    "vacuna-anti-h-influenzae-b": "b型流感嗜血杆菌疫苗", "carbon-activado": "药用炭",
    "vacuna-anti-polio": "脊髓灰质炎疫苗", "semaglutide": "司美格鲁肽", "ketamine": "氯胺酮",
    "ivermectin": "伊维菌素", "fludeoxyglucose-f-18": "氟[18F]脱氧葡糖",
    "entacapone": "恩他卡朋", "drospirenone": "屈螺酮", "vacuna-anti-bcg": "卡介苗",
    "suxametonio": "琥珀胆碱", "strontium-chloride": "氯化锶[89Sr]", "ropinirole": "罗匹尼罗",
    "osimertinib": "奥希替尼", "desogestrel": "去氧孕烯", "clomifene": "氯米芬",
    "zinc-oxido": "氧化锌", "spiramycin": "螺旋霉素", "pentosano-polisulfato": "多磺酸粘多糖",
    "oxybutynin": "奥昔布宁", "noretisterona": "炔诺酮", "bromelaina": "菠萝蛋白酶",
    "aliskireno": "阿利吉仑", "vacuna-anti-encefalitis-japonesa": "乙型脑炎疫苗",
    "potasio-ioduro": "碘化钾", "mizolastine": "咪唑斯汀", "liraglutide": "利拉鲁肽",
    "leuprorelin": "亮丙瑞林", "gadodiamide": "钆双胺", "dulaglutide": "度拉糖肽",
    "ammonium": "铵", "acido-mefenamico": "甲芬那酸", "tensioactivo-pulmonar-porcino": "猪肺磷脂",
    "ramipril": "雷米普利", "polymyxin-b": "多黏菌素B", "plata": "银",
    "nicotinamide-adenine-dinucleotide": "辅酶I", "mannitol": "甘露醇",
    "daunorubicin": "柔红霉素", "cyproterone": "环丙孕酮", "colistimethate": "多黏菌素E甲磺酸钠",
    "vacuna-anti-rotavirus": "轮状病毒疫苗", "periciazina": "哌泊塞嗪",
    "parafina-liquida": "液状石蜡", "lixisenatide": "利司那肽", "dolasetron": "多拉司琼",
    "crizotinib": "克唑替尼", "ciclesonide": "环索奈德", "benzbromarona": "苯溴马隆",
    "glucagon": "高血糖素", "dolutegravir": "多替拉韦", "brinzolamide": "布林佐胺",
    "alverine": "阿尔维林", "acitretin": "阿维A", "vacuna-anti-tifoidea": "伤寒疫苗",
    "vacuna-anti-colera": "霍乱疫苗", "panobinostat": "帕比司他", "metildopa": "甲基多巴",
    "lopinavir": "洛匹那韦", "insulin-glulisine": "谷赖胰岛素", "ibrutinib": "伊布替尼",
    "flutamide": "氟他胺", "fludrocortisona": "氟氢可的松", "colestyramine": "考来烯胺",
    "ciproterona": "环丙孕酮", "chlordiazepoxide": "氯氮䓬", "carmin-de-indigo": "靛胭脂",
    "carbidopa": "卡比多巴", "amitriptyline": "阿米替林", "alteplase": "阿替普酶",
    "alglucosidase-alfa": "阿糖苷酶α",
    "agua-esteril-para-preparaciones-inyectables": "灭菌注射用水",
    "acido-para-aminosalicilico": "对氨基水杨酸", "zonisamide": "唑尼沙胺",
    "zanamivir": "扎那米韦", "ytrio-citrato-90y": "枸橼酸钇[90Y]", "vernakalant": "维纳卡兰",
    "vacuna-anti-fiebre-amarilla": "黄热病疫苗", "telbivudine": "替比夫定",
    "sulfur-hexafluoride": "六氟化硫", "setmelanotida": "司美诺肽", "raltegravir": "拉替拉韦",
    "procarbazine": "丙卡巴肼", "osilodrostat": "奥唑司他", "mx-es-nimotuzumab": "尼妥珠单抗",
    "magnesium-gluconate": "葡萄糖酸镁", "inotuzumab-ozogamicin": "奥加伊妥珠单抗",
    "hyaluronic-acid": "透明质酸", "folinic-acid": "亚叶酸", "florbetaben-f-18": "氟[18F]贝他苯",
    "butilescopolamina": "丁溴东莨菪碱", "bezlotoxumab": "贝洛托舒单抗",
    "antimoniato": "葡萄糖酸锑钠",
}
# 旧 CSV 已应用/未应用的可疑“品牌名当通用名”修正（旧值 → 新值）
V2_CORRECTIONS = {
    "dextran-70": ("润齐", "右旋糖酐70"),
    "dopamine": ("阿斯克丁", "多巴胺"),
    "goserelin": ("诺雷得", "戈舍瑞林"),
    "methylphenidate": ("专注达", "哌甲酯"),
    "calcium-gluconate": ("弘泰", "葡萄糖酸钙"),
    "fluoxetine": ("百优解", "氟西汀"),
    "paroxetine": ("乐友", "帕罗西汀"),
    "tretinoin": ("艾力可", "维A酸"),
    "vacuna-anti-neumococo": ("纽莫法", "肺炎球菌疫苗"),
    "alglucosidase-alfa": ("美而赞", "阿糖苷酶α"),
    "aminocaproic-acid": ("凯乃银", "氨基己酸"),
    "amphotericin-b": ("锋克松", "两性霉素B"),
    "clomifene": ("法地兰", "氯米芬"),
    "dextran-40": ("福他乐", "右旋糖酐40"),
    "fludeoxyglucose-f-18": ("弗唐派特", "氟[18F]脱氧葡糖"),
    "leuprorelin": ("抑那通", "亮丙瑞林"),
    "magnesium-gluconate": ("包乐", "葡萄糖酸镁"),
    "sodium-chloride": ("乐敦清", "氯化钠"),
    "strontium-chloride": ("思通宁", "氯化锶[89Sr]"),
    "sufentanil": ("舒芬尼", "舒芬太尼"),
    "tocopherol": ("清之维", "维生素E"),
    "vitamin-b-complex": ("水乐维他", "复合维生素B"),
}
# 产品映射本身可疑（官方名与库内产品名不一致）——仅提示，不阻断
V2_MAPPING_WARN = {"dinoprostona", "carbenoxolona", "clomifeno", "otilonio",
                   "periciazina", "parafina-liquida", "setmelanotida", "vernakalant",
                   "panobinostat", "acido-mefenamico", "butilescopolamina",
                   "benzbromarona", "bromelaina", "colistimethate"}


def build_v2() -> int:
    import csv
    V2_TMP.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    # 236 目标
    missing = [dict(r) for r in con.execute("""
        SELECT s.substance_id, s.inn_en, COUNT(DISTINCT p.product_id) n_products
        FROM product p JOIN product_component pc ON pc.product_id=p.product_id
        JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id
        WHERE p.country='CN' AND (s.inn_zh IS NULL OR trim(s.inn_zh)='')
        GROUP BY s.substance_id ORDER BY n_products DESC""")]
    db_zh = {r["substance_id"]: (r["inn_zh"] or "") for r in
             con.execute("SELECT substance_id, inn_zh FROM substance")}
    rows = []
    filled_products = 0
    total_products = sum(m["n_products"] for m in missing)
    for m in missing:
        sid = m["substance_id"]
        names = con.execute("""
          SELECT nv.raw, COUNT(DISTINCT p.product_id) c FROM product p
          JOIN product_component pc ON pc.product_id=p.product_id
          JOIN variant v ON v.variant_id=pc.variant_id
          JOIN product_name pn ON pn.product_id=p.product_id AND pn.name_type='inn'
          JOIN name_key nk ON nk.key_id=pn.key_id
          LEFT JOIN name_variant nv ON nv.key_id=nk.key_id
          WHERE p.country='CN' AND v.substance_id=?
            AND (SELECT COUNT(*) FROM product_component x WHERE x.product_id=p.product_id)=1
          GROUP BY nk.key_id ORDER BY c DESC LIMIT 3""", (sid,)).fetchall()
        top_names = [[(r["raw"] or ""), r["c"]] for r in names if r["raw"]]
        zh = V2_OVERRIDES.get(sid, "")
        evidence = "；".join(f"{n}({c})" for n, c in top_names[:3]) or "（无单成分 CN 品名，组合/生物制品）"
        # 置信度：产品名命中 → high；官方名但产品名不含 → medium（映射可疑单独标记）
        hit = bool(zh) and any(zh in n or n.replace(" ", "").startswith(zh) for n, _ in top_names)
        conf = "high" if hit else ("medium" if zh else "")
        note = ""
        if sid in V2_MAPPING_WARN:
            note = "官方中文名与库内 CN 产品名不一致（成分映射可疑），建议复核"
        row = dict(row_type="fill", substance_id=sid, inn_en=m["inn_en"],
                   zh_name=zh, confidence=conf, evidence=f"NHSA 注册名: {evidence}",
                   source_url=NHSA_URL, affected_products=m["n_products"],
                   old_zh="", db_current_zh=db_zh.get(sid, ""), status=("fill" if zh else "keep_empty"),
                   note=note or ("官方/药典名（人工核对）" if zh else "判不了，留空不盲写"))
        rows.append(row)
        if zh:
            filled_products += m["n_products"]
    # 修正行（旧 CSV 可疑；其中部分可能已应用 DB）
    for sid, (old, new) in V2_CORRECTIONS.items():
        rows.append(dict(row_type="correction", substance_id=sid,
                         inn_en=(db_zh and ""), zh_name=new, confidence="high",
                         evidence="旧回填 CSV 行被判定为品牌名误用（与 CN trade 名同形）",
                         source_url=NHSA_URL, affected_products=0, old_zh=old,
                         db_current_zh=db_zh.get(sid, ""),
                         status=("db_update" if db_zh.get(sid, "") == old else "csv_only"),
                         note="DB 若已写入旧值需 UPDATE（见 corrections.sql）"))
    cols = ["row_type", "substance_id", "inn_en", "zh_name", "confidence", "evidence",
            "source_url", "affected_products", "old_zh", "db_current_zh", "status", "note"]
    with open(V2_OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    # UPDATE 草案
    sql = ["-- task-127 旧回填可疑值修正草案（只在窗口 apply；先备份）"]
    for r in rows:
        if r["row_type"] != "correction":
            continue
        if r["db_current_zh"] == r["old_zh"]:
            sql.append(f"UPDATE substance SET inn_zh='{r['zh_name']}' "
                       f"WHERE substance_id='{r['substance_id']}' AND inn_zh='{r['old_zh']}';")
    (V2_TMP / "corrections.sql").write_text("\n".join(sql) + "\n", encoding="utf-8")
    # 统计
    after_products = total_products - filled_products
    stats = dict(generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 missing_substances=len(missing), affected_products_before=total_products,
                 filled_substances=sum(1 for r in rows if r["row_type"] == "fill" and r["zh_name"]),
                 kept_empty=sum(1 for r in rows if r["row_type"] == "fill" and not r["zh_name"]),
                 filled_products=filled_products,
                 affected_products_after=after_products,
                 text_coverage_after=round(1 - after_products / total_products, 4),
                 corrections=sum(1 for r in rows if r["row_type"] == "correction"),
                 corrections_applied=sum(1 for r in rows if r["row_type"] == "correction"
                                         and r["db_current_zh"] == r["old_zh"]),
                 rows=len(rows))
    (V2_TMP / "v2_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print("写入", V2_OUT, "；修正 SQL", V2_TMP / "corrections.sql")
    con.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 inn_zh 回填 CSV（只读 DB）")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--dry-run", action="store_true", help="只打印统计")
    ap.add_argument("--v2", action="store_true", help="task-127：236 缺中文补齐 + 旧回填修正")
    args = ap.parse_args()
    if args.v2:
        return build_v2()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FATAL: DB 不存在: {db_path}", file=sys.stderr)
        return 2
    con = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    d = load(con)
    decisions, stats = decide(d)
    final, cstats = resolve_conflicts(decisions, d["existing"])
    total_sub = con.execute("SELECT COUNT(*) FROM substance").fetchone()[0]
    existing_n = con.execute(
        "SELECT COUNT(*) FROM substance WHERE inn_zh IS NOT NULL"
        " AND trim(inn_zh)<>''").fetchone()[0]
    rows = []
    for sid, x in final.items():
        conf = confidence_of(x)
        if x["method"] == "override":
            evidence = (f"cn_inn_overrides.csv 显式映射：zh_name={clean(x['zh'])}；"
                        f"cn_substance_id={x.get('override_cn', '')}；"
                        f"evidence_url={x.get('override_ev', '')}")
        else:
            ev = x.get("pids") or []
            evidence = (f"CN 单成分产品中文名（{x['count']}/{x['total']} 个产品，"
                        f"share={x['share']}，候选变体 {x['variants']} 个）；"
                        f"示例 product_id={','.join(ev[:3])}")
        rows.append(dict(substance_id=sid, inn_en=d["empty"][sid],
                         zh_candidate=x["zh"], confidence=conf,
                         method=x["method"], count=x["count"],
                         share=x["share"], variants=x["variants"],
                         evidence=evidence))
    rows.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}.get(r["confidence"], 3),
                             r["substance_id"]))
    conf_dist = Counter(r["confidence"] for r in rows)
    method_dist = Counter(r["method"] for r in rows)
    print(f"DB: {db_path}")
    print(f"substance 总数 {total_sub}；已有 inn_zh {existing_n}；待回填候选基数 {len(d['empty'])}")
    print(f"有 CN 单成分产品候选的成分: {len(d['cand'])}；overrides 命中: {len(d['over'])}")
    print("候选跳过:", dict(d["skipped"]))
    print(f"决策: {len(decisions)}（{dict(stats)}）")
    print(f"冲突处理: {dict(cstats)}")
    print(f"最终可回填: {len(rows)}  confidence={dict(conf_dist)}  method={dict(method_dist)}")
    print(f"覆盖率: {existing_n}/{total_sub} → {existing_n + len(rows)}/{total_sub}"
          f"（{existing_n / total_sub * 100:.1f}% → "
          f"{(existing_n + len(rows)) / total_sub * 100:.1f}%）")
    print("\n样例（前 30）:")
    for r in rows[:30]:
        print(f"  {r['inn_en']:<28} -> {r['zh_candidate']:<10} {r['confidence']:<6}"
              f" {r['method']}")
    if not args.dry_run:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        cols = ["substance_id", "inn_en", "zh_candidate", "confidence", "method",
                "count", "share", "variants", "evidence"]
        with open(OUT, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        STATS.parent.mkdir(parents=True, exist_ok=True)
        STATS.write_text(json.dumps(dict(
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            db=str(db_path), total_substances=total_sub,
            existing_inn_zh_before=existing_n, rows=len(rows),
            coverage_before=f"{existing_n}/{total_sub}",
            coverage_after=f"{existing_n + len(rows)}/{total_sub}",
            confidence=dict(conf_dist), method=dict(method_dist),
            candidate_skipped=dict(d["skipped"]), decide_stats=dict(stats),
            conflict_stats=dict(cstats),
            by_confidence=dict(conf_dist),
        ), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n写入 {OUT}（{OUT.stat().st_size / 1024:.1f} KB）；统计 {STATS}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
