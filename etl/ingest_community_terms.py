"""社区叫法 / 各国街头叫法：人工策展，写入 drug_term。

和 NIDA/DEA 那批的区别：
  - 这些是「社区/消费者文章里的叫法」，不是药监官方命名；
  - confidence='community'，公开页标「社区叫法」，保留检索、不冒充 documented；
  - 每条都带 source_url，只存叫法这一事实，不转载原文。

来源：
  CN  小红书/知乎/丁香园/科普中国/药监科普等公开页面（逐条 URL）
  GB  Talk to FRANK（英国公共药物信息站）的 Also called
  AU  Alcohol and Drug Foundation 的 Other names
  ES  PNSD（西班牙国家毒品计划）公开 PDF 中的俗称

运行：
    python etl/ingest_community_terms.py --dry-run
    python etl/ingest_community_terms.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import normalize  # noqa: E402

DB = ROOT / "data" / "drugs.db"

SOURCES = {
    "community_cn": dict(
        name="Community / consumer health pages (CN)",
        url="https://www.xiaohongshu.com/",
        license="User-generated / consumer content; short factual nicknames with link only",
        notes="小红书/知乎/丁香园/科普中国/药监科普等；只取叫法，不转载正文。",
    ),
    "frank_uk": dict(
        name="Talk to FRANK (UK)",
        url="https://www.talktofrank.com/",
        license="Crown copyright; short factual names with attribution",
        notes="英国公共药物信息站的 Also called 列表；只取叫法。",
    ),
    "adf_au": dict(
        name="Alcohol and Drug Foundation (Australia)",
        url="https://adf.org.au/drug-facts/",
        license="© Alcohol and Drug Foundation; short factual names with attribution",
        notes="ADF Drug Facts 的 Other names 列表；只取叫法。",
    ),
    "pnsd_es": dict(
        name="PNSD — Plan Nacional sobre Drogas (Spain)",
        url=("https://pnsd.sanidad.gob.es/en/profesionales/publicaciones/catalogo/"
             "bibliotecaDigital/publicaciones/pdf/2017_FSG_Manual_Prevencion_de_drogas_para_familias.pdf"),
        license="Spanish government public document; short factual names with attribution",
        notes="西班牙 PNSD 家庭预防手册中的俗称；只取叫法。",
    ),
}

# (term, country, term_type, label_zh, label_en, sids, source_id, source_url,
#  meaning_zh, meaning_en)
TERMS = [
    # --- 中国：功效型社区叫法 ------------------------------------------------
    ("闭口神器", "CN", "folk", "阿达帕林", "Adapalene", ["adapalene"],
     "community_cn", "https://m.dxy.com/article/28245",
     "社区把阿达帕林叫「闭口神器」，用于闭口粉刺；它是外用维A酸类处方药，不是普通护肤品。",
     "Community nickname for adapalene, used for closed comedones; a topical retinoid, not a cosmetic."),
    ("祛痘神药", "CN", "folk", "异维A酸", "Isotretinoin", ["isotretinoin"],
     "community_cn", "https://www.163.com/dy/article/KLOVAOK5052583KJ.html",
     "社区把异维A酸叫「祛痘神药」；处方药，有抑郁、性功能障碍、出生缺陷等风险。",
     "Community nickname for isotretinoin; a prescription drug with serious risks."),
    ("生发神药", "CN", "folk", "米诺地尔", "Minoxidil", ["minoxidil"],
     "community_cn", "http://news.miaoshou.com/news/8wvGy1E6vNJN6lPd.html",
     "社区把米诺地尔叫「生发神药」；外用/口服用法不同，不是对所有人都有效。",
     "Community nickname for minoxidil; not effective for everyone."),
    ("聪明药", "CN", "folk", "哌甲酯 / 莫达非尼", "Methylphenidate / modafinil",
     ["methylphenidate", "modafinil"],
     "community_cn", "https://mpa.gd.gov.cn/xwdt/xwfbpt/mtzx/content/post_4716856.html",
     "社区把哌甲酯、莫达非尼等促智/兴奋药叫「聪明药」；处方药，滥用有心血管和精神风险。",
     "Community term for prescription stimulants/wakefulness drugs; misuse carries risks."),
    ("P药", "CN", "folk", "奈玛特韦/利托那韦", "Nirmatrelvir/ritonavir",
     ["nirmatrelvir", "ritonavir"],
     "community_cn", "https://www.psmchina.cn/safe_medicines_information/safe_medicines_knowledge/jbcs/9217",
     "新冠口服药奈玛特韦/利托那韦的社区简称；不是「特效药」，有药物相互作用。",
     "Community shorthand for nirmatrelvir/ritonavir; not a miracle cure and has interactions."),
    ("便秘神器", "CN", "folk", "甘油（开塞露）", "Glycerin (enema)", ["glycerin"],
     "community_cn", "https://h5.kepuchina.cn/scientificwebsite/article?id=92464",
     "社区把开塞露（甘油制剂）叫「便秘神器」；还有把开塞露当护肤品的误用。",
     "Community nickname for glycerin enemas; also misused as skincare."),
    ("美白丸", "CN", "folk", "氨甲环酸 / 谷胱甘肽", "Tranexamic acid / glutathione",
     ["tranexamic-acid", "glutathione"],
     "community_cn", "https://wsjkw.gd.gov.cn/jkkp/kpzs/content/post_4882985.html",
     "社区把氨甲环酸、谷胱甘肽等口服产品叫「美白丸」；不是都获批，注意不良反应。",
     "Community term for oral whitening products; not all are approved."),
    ("减肥神药", "CN", "folk", "司美格鲁肽", "Semaglutide", ["semaglutide"],
     "community_cn", "https://www.jkb.com.cn/news/view/2021/0526/481914.html",
     "社区把司美格鲁肽等 GLP-1 叫「减肥神药」；处方药，有胃肠反应等风险。",
     "Community nickname for GLP-1 drugs such as semaglutide; prescription only."),
    ("长效伟哥", "CN", "folk", "他达拉非", "Tadalafil", ["tadalafil"],
     "community_cn", "https://health.ifeng.com/c/82OBBZ0Cdf1",
     "社区把他达拉非叫「长效伟哥」；处方药，不是保健品。",
     "Community nickname for tadalafil; prescription only."),
    ("延时药", "CN", "folk", "达泊西汀", "Dapoxetine", ["dapoxetine"],
     "community_cn", "https://jbk.39.net/zx/231030/j7instg.html",
     "社区把达泊西汀等叫「延时药」；处方药，不是保健品。",
     "Community term for dapoxetine and similar prescription drugs."),

    # --- 英国：FRANK 的 Also called -----------------------------------------
    ("Charlie", "GB", "street", "可卡因", "Cocaine", ["cocaine"],
     "frank_uk", "https://www.talktofrank.com/drug/cocaine",
     "英国 FRANK 列为可卡因的街头叫法。",
     "UK street name for cocaine (FRANK)."),
    ("rocks", "GB", "street", "可卡因（快克）", "Crack cocaine", ["cocaine"],
     "frank_uk", "https://www.talktofrank.com/drug/cocaine",
     "英国 FRANK 列为可卡因/快克的街头叫法。",
     "UK street name for crack/cocaine (FRANK)."),
    ("Freebase", "GB", "street", "可卡因（游离碱）", "Freebase cocaine", ["cocaine"],
     "frank_uk", "https://www.talktofrank.com/drug/cocaine",
     "英国 FRANK 列为可卡因的街头叫法。",
     "UK street name for freebase cocaine (FRANK)."),
    ("Draw", "GB", "street", "大麻", "Cannabis", [None],
     "frank_uk", "https://www.talktofrank.com/drug/cannabis",
     "英国 FRANK 列为大麻的街头叫法。",
     "UK street name for cannabis (FRANK)."),
    ("Pollen", "GB", "street", "大麻（花粉/树脂）", "Cannabis pollen/resin", [None],
     "frank_uk", "https://www.talktofrank.com/drug/cannabis",
     "英国 FRANK 列为大麻的街头叫法，常指花粉/树脂形态。",
     "UK street name for cannabis pollen/resin (FRANK)."),
    ("Resin", "GB", "street", "大麻树脂", "Cannabis resin", [None],
     "frank_uk", "https://www.talktofrank.com/drug/cannabis",
     "英国 FRANK 列为大麻树脂的街头叫法。",
     "UK street name for cannabis resin (FRANK)."),
    ("Sensi", "GB", "street", "大麻", "Cannabis", [None],
     "frank_uk", "https://www.talktofrank.com/drug/cannabis",
     "英国 FRANK 列为大麻的街头叫法。",
     "UK street name for cannabis (FRANK)."),
    ("Hashish", "GB", "street", "大麻树脂", "Hashish", [None],
     "frank_uk", "https://www.talktofrank.com/drug/cannabis",
     "英国 FRANK 列为大麻树脂的街头叫法。",
     "UK street name for hashish (FRANK)."),
    ("Bhang", "GB", "street", "大麻（食用/饮品）", "Cannabis (bhang)", [None],
     "frank_uk", "https://www.talktofrank.com/drug/cannabis",
     "英国 FRANK 列为大麻的街头叫法；南亚语境常指大麻饮品。",
     "UK street name for cannabis, especially a drink (FRANK)."),
    ("Brown", "GB", "street", "海洛因（棕色粉末）", "Heroin (brown powder)", [None],
     "frank_uk", "https://www.talktofrank.com/drug/heroin",
     "英国 FRANK 列为海洛因的街头叫法。",
     "UK street name for brown heroin (FRANK)."),
    ("Gear", "GB", "street", "海洛因", "Heroin", [None],
     "frank_uk", "https://www.talktofrank.com/drug/heroin",
     "英国 FRANK 列为海洛因的街头叫法。",
     "UK street name for heroin (FRANK)."),
    ("Skag", "GB", "street", "海洛因", "Heroin", [None],
     "frank_uk", "https://www.talktofrank.com/drug/heroin",
     "英国 FRANK 列为海洛因的街头叫法。",
     "UK street name for heroin (FRANK)."),

    # --- 澳洲：ADF 的 Other names -------------------------------------------
    ("Hammer", "AU", "street", "海洛因", "Heroin", [None],
     "adf_au", "https://adf.org.au/drug-facts/heroin/",
     "澳洲 ADF 列为海洛因的街头叫法。",
     "Australian street name for heroin (ADF)."),
    ("The Dragon", "AU", "street", "海洛因", "Heroin", [None],
     "adf_au", "https://adf.org.au/drug-facts/heroin/",
     "澳洲 ADF 列为海洛因的街头叫法；也指追逐龙（ chasing the dragon）的用法。",
     "Australian street name for heroin (ADF)."),
    ("White Dynamite", "AU", "street", "海洛因（白色粉末）", "Heroin (white powder)", [None],
     "adf_au", "https://adf.org.au/drug-facts/heroin/",
     "澳洲 ADF 列为海洛因的街头叫法。",
     "Australian street name for white heroin (ADF)."),
    ("Homebake", "AU", "street", "海洛因（自制）", "Homebake heroin", [None],
     "adf_au", "https://adf.org.au/drug-facts/heroin/",
     "澳洲 ADF 列为海洛因的街头叫法，特指本地自制。",
     "Australian term for homebake heroin (ADF)."),
    ("Dr Harry", "AU", "street", "海洛因", "Heroin", [None],
     "adf_au", "https://adf.org.au/drug-facts/heroin/",
     "澳洲 ADF 列为海洛因的街头叫法。",
     "Australian street name for heroin (ADF)."),

    # --- 西班牙：PNSD 手册里的俗称 -----------------------------------------
    ("Nieve", "ES", "street", "可卡因", "Cocaine", ["cocaine"],
     "pnsd_es", "https://pnsd.sanidad.gob.es/en/profesionales/publicaciones/catalogo/bibliotecaDigital/publicaciones/pdf/2017_FSG_Manual_Prevencion_de_drogas_para_familias.pdf",
     "西班牙 PNSD 手册列出的可卡因俗称（nieve = 雪）。",
     "Spanish street name for cocaine (PNSD)."),
    ("Blanca", "ES", "street", "可卡因", "Cocaine", ["cocaine"],
     "pnsd_es", "https://pnsd.sanidad.gob.es/en/profesionales/publicaciones/catalogo/bibliotecaDigital/publicaciones/pdf/2017_FSG_Manual_Prevencion_de_drogas_para_familias.pdf",
     "西班牙 PNSD 手册列出的可卡因俗称（blanca = 白色）。",
     "Spanish street name for cocaine (PNSD)."),
    ("Farlopa", "ES", "street", "可卡因", "Cocaine", ["cocaine"],
     "pnsd_es", "https://pnsd.sanidad.gob.es/en/profesionales/publicaciones/catalogo/bibliotecaDigital/publicaciones/pdf/2017_FSG_Manual_Prevencion_de_drogas_para_familias.pdf",
     "西班牙 PNSD 手册列出的可卡因俗称。",
     "Spanish street name for cocaine (PNSD)."),
    ("Perico", "ES", "street", "可卡因", "Cocaine", ["cocaine"],
     "pnsd_es", "https://pnsd.sanidad.gob.es/en/profesionales/publicaciones/catalogo/bibliotecaDigital/publicaciones/pdf/2017_FSG_Manual_Prevencion_de_drogas_para_familias.pdf",
     "西班牙/墨西哥常用的可卡因俗称。",
     "Spanish/Mexican street name for cocaine (PNSD)."),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=60)
    db.execute("PRAGMA foreign_keys = ON")
    existing = {r[0] for r in db.execute("SELECT substance_id FROM substance")}
    seen = {
        (r[0], r[1], r[2] or "")
        for r in db.execute(
            "SELECT term_norm, term_type, substance_id FROM drug_term")
    }
    rows = []
    skipped = []

    for (term, country, term_type, zh, en, sids, source_id, url, mzh, men) in TERMS:
        n = normalize(term)
        if not n.norm:
            skipped.append(f"{term}（归一化后为空）")
            continue
        for sid in sids:
            if sid and sid not in existing:
                skipped.append(f"{term} → {sid}（库里没有）")
                continue
            key = (n.norm, term_type, sid or "")
            if key in seen:
                skipped.append(f"{term}（已存在同名/同成分）")
                continue
            seen.add(key)
            rows.append({
                "term": term, "term_norm": n.norm, "term_type": term_type,
                "country": country, "label_zh": zh, "label_en": en,
                "meaning_zh": mzh, "meaning_en": men, "substance_id": sid,
                "confidence": "community", "source_id": source_id,
                "source_url": url,
                "note": "社区/公开药物信息站用法；只存叫法，不转载正文。",
            })

    print(f"候选 {len(rows)} 行；跳过 {len(skipped)}")
    for s in skipped:
        print("  跳过", s)
    if args.dry_run:
        for r in rows:
            print(f"  {r['country']} {r['term']:16} {r['term_type']:6} "
                  f"{r['substance_id'] or '-':18} {r['label_zh']}")
        db.close()
        return

    today = date.today().isoformat()
    for source_id, meta in SOURCES.items():
        db.execute(
            """INSERT INTO source (source_id, name, url, license, license_url,
                                   retrieved_at, notes)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT (source_id) DO UPDATE SET
                   name=excluded.name, url=excluded.url, license=excluded.license,
                   license_url=excluded.license_url, retrieved_at=excluded.retrieved_at,
                   notes=excluded.notes""",
            (source_id, meta["name"], meta["url"], meta["license"], None,
             today, meta["notes"]))
    db.execute("DELETE FROM drug_term WHERE source_id IN "
               "('community_cn','frank_uk','adf_au','pnsd_es')")
    db.executemany(
        """INSERT INTO drug_term
           (term, term_norm, term_type, country, label_zh, label_en,
            meaning_en, meaning_zh, substance_id, confidence, source_id,
            source_url, note, created_at)
           VALUES (:term, :term_norm, :term_type, :country, :label_zh, :label_en,
                   :meaning_en, :meaning_zh, :substance_id, :confidence, :source_id,
                   :source_url, :note, :created_at)""",
        [{**r, "created_at": today} for r in rows],
    )
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM drug_term").fetchone()[0]
    print(f"drug_term: 写入 {len(rows)} 行；表内共 {total} 行")
    db.close()


if __name__ == "__main__":
    main()
