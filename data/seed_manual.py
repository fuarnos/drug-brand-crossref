"""人工核对种子：英国 / 中国。

规则（写死在这里，避免以后图省事走捷径）：
1. 只收有原始来源的条目；来源存 URL，抓取日期存库。
2. 跨语言必须落到同一个 substance_id，否则"跨国对应"根本查不出来
   （中国的「对乙酰氨基酚」和美国 openFDA 的 Acetaminophen 是同一个 substance）。
3. 拿不到一手来源的，corroboration.note 标「待复核」，页面上必须显示这个标记。

用法：python data/seed_manual.py
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import normalize  # noqa: E402

DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "manual_seed"
TODAY = date.today().isoformat()

# (country, brand, inn_en, inn_zh, strength, unit, per_v, per_u, form, release,
#  mah, approval_id, source_type, url, note)
# 复方用 components 列表单独表达。
SEED = [
    # ---------- 英国（emc 说明书，已核对） ----------
    dict(country="GB", brand="Benadryl Allergy Relief",
         components=[("acrivastine", "阿伐斯汀", 8, "mg")],
         form="capsule", release="none", mah="McNeil Products Ltd",
         approval_id="PL 15513/0128", salt="",
         source_type="regulator",
         url="https://www.medicines.org.uk/emc/product/1473/smpc",
         note="UK 是阿伐斯汀 8 mg（不嗜睡），与美国苯海拉明完全不同"),
    dict(country="GB", brand="Gaviscon Original Aniseed Relief",
         components=[("sodium alginate", "海藻酸钠", 250, "mg"),
                     ("sodium bicarbonate", "碳酸氢钠", 133.5, "mg"),
                     ("calcium carbonate", "碳酸钙", 80, "mg")],
         form="oral suspension", release="none", mah="Reckitt Benckiser",
         approval_id="PL 00063/0126", per_v=5, per_u="ml",
         source_type="regulator",
         url="https://www.medicines.org.uk/emc/product/623/smpc",
         note="藻酸盐 raft 机制；美国 Gaviscon 是铝/镁抗酸，成分集合不相交"),
    # ---------- 中国（说明书 PDF，已核对） ----------
    dict(country="CN", brand="泰诺",
         components=[("acetaminophen", "对乙酰氨基酚", 325, "mg"),
                     ("pseudoephedrine", "盐酸伪麻黄碱", 30, "mg"),
                     ("dextromethorphan", "氢溴酸右美沙芬", 15, "mg"),
                     ("chlorphenamine", "马来酸氯苯那敏", 2, "mg")],
         form="tablet", release="none", mah="上海强生制药有限公司",
         approval_id="国药准字H20010115",
         source_type="mah_pdf",
         url="https://www.xian-janssen.com.cn/sites/default/files/PDF/8_tai_nuo_20210319_fen_ma_mei_min_pian_shuo_ming_shu_.pdf",
         note="复方感冒药；美国 Tylenol 是单方对乙酰氨基酚"),
    dict(country="CN", brand="泰诺林",
         components=[("acetaminophen", "对乙酰氨基酚", 650, "mg")],
         form="tablet", release="ER", mah="上海强生制药有限公司",
         approval_id="国药准字H20010394",
         source_type="regulator",
         url="https://ypk.39.net/compare/506346,786890,507549",
         note="缓释片 650 mg；这才是中国的单方对乙酰氨基酚商品名"),
    # ---------- 待复核（有一手线索但尚未核到说明书原文） ----------
    dict(country="CN", brand="立普妥",
         components=[("atorvastatin", "阿托伐他汀", 20, "mg")],
         form="tablet", release="none", mah="辉瑞制药有限公司",
         approval_id="", salt="calcium",
         source_type="manual", url="", note="待复核"),
    dict(country="GB", brand="Lipitor",
         components=[("atorvastatin", "阿托伐他汀", 20, "mg")],
         form="tablet", release="none", mah="Pfizer Limited",
         approval_id="", salt="calcium",
         source_type="manual", url="", note="待复核"),
]


def slug(text: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


def main() -> None:
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, retrieved_at, notes)"
        " VALUES (?,?,?,?,?,?)",
        (SOURCE_ID, "人工核对种子（说明书/药监页面）", "", "逐条标注来源", TODAY,
         "仅收录已核对条目；待复核条目在 corroboration.note 标注"),
    )

    for i, row in enumerate(SEED, 1):
        pid = f"{row['country']}-seed-{i:02d}-{slug(row['brand'])}"
        db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
            " route, release, pack, mah, approval_id, category, is_branded, status,"
            " source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, row["country"], row["form"], "", "oral", row["release"], None,
             row["mah"], row["approval_id"] or None, "SEED", 1, "active",
             SOURCE_ID, row["url"] or None, TODAY, row.get("note")),
        )
        db.execute(
            "INSERT OR REPLACE INTO corroboration (product_id, source_type, url,"
            " retrieved_at, note) VALUES (?,?,?,?,?)",
            (pid, row["source_type"], row["url"], TODAY, row.get("note")),
        )

        for ord_, (inn, zh, strength, unit) in enumerate(row["components"]):
            sid = slug(inn)
            salt = row.get("salt", "") if ord_ == 0 else ""
            vid = f"{sid}-{salt}" if salt else sid
            db.execute(
                "INSERT OR IGNORE INTO substance (substance_id, inn_en, inn_zh)"
                " VALUES (?,?,?)", (sid, inn.title(), zh))
            db.execute(
                "UPDATE substance SET inn_zh = COALESCE(inn_zh, ?) WHERE substance_id = ?",
                (zh, sid))
            db.execute(
                "INSERT OR IGNORE INTO variant (variant_id, substance_id, salt) VALUES (?,?,?)",
                (vid, sid, salt))
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)",
                (pid, ord_, vid, strength, unit,
                 row.get("per_v"), row.get("per_u")))

        n = normalize(row["brand"])
        db.execute(
            "INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
            " VALUES (?,?,?,?)", (n.norm, n.norm, n.compact, n.script))
        db.execute(
            "INSERT OR IGNORE INTO name_variant (key_id, raw, source_id) VALUES (?,?,?)",
            (n.norm, row["brand"], SOURCE_ID))
        db.execute(
            "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type, is_primary)"
            " VALUES (?,?,?,?)", (pid, n.norm, "trade", 1))

    db.commit()
    print(f"seeded {len(SEED)} products")
    for r in db.execute("SELECT * FROM coverage"):
        print("coverage:", r)
    db.close()


if __name__ == "__main__":
    main()
