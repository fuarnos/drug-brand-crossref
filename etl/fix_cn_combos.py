"""P0 修复：把中国「复方」产品缺失的成分补回去。

背景：NHSA 的注册名称把复方的两个成分连写（二甲双胍格列本脲片），原导入器只映射了
第一个成分，第二个被吞掉 —— 4,411 行受影响，属于「隐藏成分」，必须修。

做法（保守优先，宁可少拆也不拆错）：
  1. 只在两类情况下判定为复方：
     a. 规格里出现两个质量剂量（`500mg:2.5mg`、`0.5g:2.5mg`），且剂型是口服固体；
     b. 名字命中人工维护的强复方列表（二甲双胍格列本脲、缬沙坦氨氯地平…）。
  2. 名字用「最长匹配」切成成分 token，要求 ≥2 个、每个 ≥3 字。
  3. 剂量只在「规格段数 == 成分数」时一一对应；对不上就把剂量留空，
     但**成分必须补全** —— 隐藏成分比缺一个数字危险得多。
  4. 幂等：先删该产品的全部 component，再按新结果重建。

用法：
    python etl/fix_cn_combos.py --dry-run   # 只看统计
    python etl/fix_cn_combos.py             # 写库
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from ingest_openfda_ndc import form_base_of  # noqa: E402
from normalize_name import normalize  # noqa: E402

DB = ROOT / "data" / "drugs.db"
CSV = ROOT / "data" / "raw" / "nhsa" / "nhsa_codes_20250404.csv"

# 名字里明显是复方的（人工维护，只收不会误判的）
STRONG_COMBOS = [
    "二甲双胍格列本脲", "二甲双胍格列齐特", "二甲双胍格列吡嗪", "二甲双胍罗格列酮",
    "二甲双胍吡格列酮", "二甲双胍西格列汀", "二甲双胍维格列汀", "二甲双胍沙格列汀",
    "二甲双胍利格列汀", "二甲双胍达格列净", "二甲双胍恩格列净",
    "缬沙坦氨氯地平", "氨氯地平缬沙坦", "氨氯地平阿托伐他汀", "氨氯地平贝那普利",
    "氨氯地平培哚普利", "氨氯地平氯沙坦", "氯沙坦钾氢氯噻嗪", "厄贝沙坦氢氯噻嗪",
    "缬沙坦氢氯噻嗪", "替米沙坦氢氯噻嗪", "奥美沙坦酯氢氯噻嗪", "卡托普利氢氯噻嗪",
    "贝那普利氢氯噻嗪", "赖诺普利氢氯噻嗪", "美托洛尔氢氯噻嗪", "比索洛尔氢氯噻嗪",
    "阿莫西林克拉维酸", "氨苄西林舒巴坦", "头孢哌酮舒巴坦", "哌拉西林他唑巴坦",
    "替卡西林克拉维酸", "亚胺培南西司他丁", "美洛西林舒巴坦", "头孢曲松舒巴坦",
    "头孢噻肟舒巴坦", "左炔诺孕酮炔雌醇", "去氧孕烯炔雌醇", "炔雌醇环丙孕酮",
    "屈螺酮炔雌醇", "复方氨酚烷胺", "氨酚黄那敏", "酚麻美敏", "对乙酰氨基酚维生素C",
]

# 人工确认过的复方组成：名字片段 → [(substance_id, 中文名), ...]
# 这些不靠分词猜，直接查表，避免把「甲砜霉素甘氨酸酯」这种酯类当成复方。
COMBO_MAP: dict[str, list[tuple[str, str]]] = {
    "二甲双胍格列本脲": [("metformin", "二甲双胍"), ("glibenclamide", "格列本脲")],
    "二甲双胍格列齐特": [("metformin", "二甲双胍"), ("gliclazide", "格列齐特")],
    "二甲双胍格列吡嗪": [("metformin", "二甲双胍"), ("glipizide", "格列吡嗪")],
    "二甲双胍罗格列酮": [("metformin", "二甲双胍"), ("rosiglitazone", "罗格列酮")],
    "二甲双胍吡格列酮": [("metformin", "二甲双胍"), ("pioglitazone", "吡格列酮")],
    "二甲双胍西格列汀": [("metformin", "二甲双胍"), ("sitagliptin", "西格列汀")],
    "二甲双胍维格列汀": [("metformin", "二甲双胍"), ("vildagliptin", "维格列汀")],
    "二甲双胍沙格列汀": [("metformin", "二甲双胍"), ("saxagliptin", "沙格列汀")],
    "二甲双胍利格列汀": [("metformin", "二甲双胍"), ("linagliptin", "利格列汀")],
    "二甲双胍达格列净": [("metformin", "二甲双胍"), ("dapagliflozin", "达格列净")],
    "二甲双胍恩格列净": [("metformin", "二甲双胍"), ("empagliflozin", "恩格列净")],
    "缬沙坦氨氯地平": [("valsartan", "缬沙坦"), ("amlodipine", "氨氯地平")],
    "氨氯地平缬沙坦": [("amlodipine", "氨氯地平"), ("valsartan", "缬沙坦")],
    "氨氯地平阿托伐他汀": [("amlodipine", "氨氯地平"), ("atorvastatin", "阿托伐他汀")],
    "氨氯地平贝那普利": [("amlodipine", "氨氯地平"), ("benazepril", "贝那普利")],
    "氨氯地平培哚普利": [("amlodipine", "氨氯地平"), ("perindopril", "培哚普利")],
    "氨氯地平氯沙坦": [("amlodipine", "氨氯地平"), ("losartan", "氯沙坦")],
    "氯沙坦钾氢氯噻嗪": [("losartan", "氯沙坦"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "厄贝沙坦氢氯噻嗪": [("irbesartan", "厄贝沙坦"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "缬沙坦氢氯噻嗪": [("valsartan", "缬沙坦"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "替米沙坦氢氯噻嗪": [("telmisartan", "替米沙坦"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "奥美沙坦酯氢氯噻嗪": [("olmesartan", "奥美沙坦"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "卡托普利氢氯噻嗪": [("captopril", "卡托普利"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "贝那普利氢氯噻嗪": [("benazepril", "贝那普利"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "赖诺普利氢氯噻嗪": [("lisinopril", "赖诺普利"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "美托洛尔氢氯噻嗪": [("metoprolol", "美托洛尔"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "比索洛尔氢氯噻嗪": [("bisoprolol", "比索洛尔"), ("hydrochlorothiazide", "氢氯噻嗪")],
    "阿莫西林克拉维酸": [("amoxicillin", "阿莫西林"), ("clavulanate", "克拉维酸")],
    "氨苄西林舒巴坦": [("ampicillin", "氨苄西林"), ("sulbactam", "舒巴坦")],
    "头孢哌酮舒巴坦": [("cefoperazone", "头孢哌酮"), ("sulbactam", "舒巴坦")],
    "哌拉西林他唑巴坦": [("piperacillin", "哌拉西林"), ("tazobactam", "他唑巴坦")],
    "替卡西林克拉维酸": [("ticarcillin", "替卡西林"), ("clavulanate", "克拉维酸")],
    "亚胺培南西司他丁": [("imipenem", "亚胺培南"), ("cilastatin", "西司他丁")],
    "美洛西林舒巴坦": [("mezlocillin", "美洛西林"), ("sulbactam", "舒巴坦")],
    "头孢曲松舒巴坦": [("ceftriaxone", "头孢曲松"), ("sulbactam", "舒巴坦")],
    "头孢噻肟舒巴坦": [("cefotaxime", "头孢噻肟"), ("sulbactam", "舒巴坦")],
    "左炔诺孕酮炔雌醇": [("levonorgestrel", "左炔诺孕酮"), ("ethinylestradiol", "炔雌醇")],
    "去氧孕烯炔雌醇": [("desogestrel", "去氧孕烯"), ("ethinylestradiol", "炔雌醇")],
    "炔雌醇环丙孕酮": [("ethinylestradiol", "炔雌醇"), ("cyproterone", "环丙孕酮")],
    "屈螺酮炔雌醇": [("drospirenone", "屈螺酮"), ("ethinylestradiol", "炔雌醇")],
    "氨酚黄那敏": [("acetaminophen", "对乙酰氨基酚"), ("chlorphenamine", "氯苯那敏"),
                   ("pseudoephedrine", "伪麻黄碱")],
    "复方氨酚烷胺": [("acetaminophen", "对乙酰氨基酚"), ("amantadine", "金刚烷胺")],
    "酚麻美敏": [("acetaminophen", "对乙酰氨基酚"), ("pseudoephedrine", "伪麻黄碱"),
                 ("dextromethorphan", "右美沙芬"), ("chlorphenamine", "氯苯那敏")],
    "对乙酰氨基酚维生素C": [("acetaminophen", "对乙酰氨基酚"), ("ascorbic-acid", "维生素C")],
}

# 规格里的人话写法很多：
#   500mg:2.5mg / 5mg/10mg(以A/B计) / 每片含盐酸二甲双胍250mg与格列吡嗪2.5mg
# 统一处理成「按出现顺序的质量剂量列表」。
MASS_ANY = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|g|μg|ug)(?![a-zA-Z])", re.I)


def dose_list(spec: str) -> list[tuple[float, str]]:
    return [(float(v), u.lower()) for v, u in MASS_ANY.findall(spec or "")]
# 名字里的剂型尾巴
FORM_TAIL = re.compile(
    r"(片|胶囊|颗粒|散|丸|注射液|注射剂|输液|软膏|乳膏|凝胶|滴眼液|滴耳液|滴鼻液|"
    r"搽剂|洗剂|喷雾剂|气雾剂|贴剂|栓|膜|糖浆|口服液|混悬液|干混悬剂|溶液|酊|"
    r"胶浆|糊剂|乳剂|涂剂|含漱液|含片|分散片|缓释片|控释片|肠溶片|咀嚼片|泡腾片|"
    r"阴道片|眼膏|吸入剂|粉雾剂|注射用|冻干|组合包装)+$")
ORAL_SOLID = {"tablet", "capsule", "powder"}


def product_id_of(row: dict) -> str:
    key = "|".join(
        (row.get(c) or "").strip()
        for c in ("规格", "包装材质", "最小包装数量", "最小包装单位", "批准文号", "药品企业")
    )
    return f"CN-{row['药品代码'].strip()}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]}"


def build_vocab(db: sqlite3.Connection) -> dict[str, str]:
    vocab: dict[str, str] = {}
    for sid, zh, en in db.execute("SELECT substance_id, inn_zh, inn_en FROM substance"):
        for name in (zh, en):
            if name and len(name) >= 3 and re.search(r"[\u4e00-\u9fff]", name):
                vocab.setdefault(name, sid)
    # 复方常见搭档，库里未必单独建过
    extra = {
        "格列本脲": "glibenclamide", "格列齐特": "gliclazide", "格列吡嗪": "glipizide",
        "罗格列酮": "rosiglitazone", "吡格列酮": "pioglitazone",
        "氢氯噻嗪": "hydrochlorothiazide", "氨氯地平": "amlodipine",
        "缬沙坦": "valsartan", "厄贝沙坦": "irbesartan", "氯沙坦": "losartan",
        "克拉维酸": "clavulanate", "舒巴坦": "sulbactam", "他唑巴坦": "tazobactam",
        "西司他丁": "cilastatin", "金刚烷胺": "amantadine",
        "伪麻黄碱": "pseudoephedrine", "氯苯那敏": "chlorphenamine",
        "右美沙芬": "dextromethorphan", "咖啡因": "caffeine",
    }
    for k, v in extra.items():
        vocab.setdefault(k, v)
    return vocab


def split_name(name: str, vocab: dict[str, str], maxlen: int) -> list[tuple[str, str]]:
    s = name.strip()
    prev = None
    while s != prev:
        prev = s
        s = FORM_TAIL.sub("", s).strip()
    out, i = [], 0
    while i < len(s):
        hit = None
        for L in range(min(maxlen, len(s) - i), 2, -1):
            cand = s[i:i + L]
            if cand in vocab:
                hit = (cand, vocab[cand])
                break
        if hit:
            out.append(hit)
            i += len(hit[0])
        else:
            i += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--csv", default=str(CSV))
    args = ap.parse_args()

    db = sqlite3.connect(DB, timeout=120)
    vocab = build_vocab(db)
    maxlen = max(len(k) for k in vocab)
    existing = {r[0] for r in db.execute("SELECT product_id FROM product WHERE country='CN'")}
    print(f"词典 {len(vocab)} 条；库里 CN 产品 {len(existing)}")

    rows: list[dict] = []
    with open(args.csv, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("药品代码") or "").startswith("X"):
                continue
            rows.append(row)
    print(f"CSV 化药行 {len(rows)}")

    hits, matched_pid, written, no_dose = 0, 0, 0, 0
    samples: list[str] = []
    skipped_no_token: list[str] = []

    for row in rows:
        pid = product_id_of(row)
        if pid not in existing:
            continue
        matched_pid += 1
        name = (row.get("注册名称") or "").strip()
        spec = (row.get("规格") or "").strip()
        form = form_base_of(row.get("注册剂型") or row.get("剂型") or "")

        masses = dose_list(spec)
        strong = next((h for h in STRONG_COMBOS if h in name), None)
        two = len(masses) >= 2 and form in ORAL_SOLID
        if not (strong or two):
            continue

        if strong and strong in COMBO_MAP:
            # 查表：组成是人工确认的，不靠分词。表里存的是 (substance_id, 中文名)，这里转成 (中文名, sid)
            uniq = [(zh, sid) for sid, zh in COMBO_MAP[strong]]
        else:
            parts = split_name(name, vocab, maxlen)
            parts = [(t, s) for t, s in parts if len(t) >= 3]
            seen, uniq = set(), []
            for t, s in parts:
                if t not in seen:
                    seen.add(t)
                    uniq.append((t, s))
        if len(uniq) < 2:
            skipped_no_token.append(name)
            continue

        hits += 1
        if len(masses) >= len(uniq):
            doses = masses[:len(uniq)]
        else:
            no_dose += 1
            doses = [None] * len(uniq)

        if args.dry_run:
            if len(samples) < 15:
                samples.append(f"{name} | {spec} -> " +
                               " + ".join(t for t, _ in uniq) +
                               (f"  ({', '.join(f'{d[0]}{d[1]}' for d in doses if d)})"
                                if doses and doses[0] else "  (剂量留空)"))
            continue

        db.execute("DELETE FROM product_component WHERE product_id = ?", (pid,))
        for i, (tok, sid) in enumerate(uniq):
            db.execute("INSERT OR IGNORE INTO substance (substance_id, inn_en)"
                       " VALUES (?,?)", (sid, sid))
            db.execute("INSERT OR IGNORE INTO variant (variant_id, substance_id)"
                       " VALUES (?,?)", (sid, sid))
            d = doses[i]
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit) VALUES (?,?,?,?,?)",
                (pid, i, sid, d[0] if d else None, d[1] if d else None))
        written += 1

    if not args.dry_run:
        db.commit()

    print(f"\n指纹对上的产品: {matched_pid}")
    print(f"判定为复方: {hits}")
    print(f"  其中剂量无法一一对应（只补成分）: {no_dose}")
    print(f"  切不出 ≥2 个成分而跳过: {len(skipped_no_token)}")
    if args.dry_run:
        print("\n样例：")
        for s in samples:
            print("  " + s)
        if skipped_no_token:
            print("\n跳过的名字（前 8）：", Counter(skipped_no_token).most_common(8))
    else:
        print(f"写库产品数: {written}")
    db.close()


if __name__ == "__main__":
    main()
