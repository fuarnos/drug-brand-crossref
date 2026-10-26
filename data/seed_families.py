"""品牌家族：同一个商标在不同市场的写法。

为什么必须人工维护：没有任何数据源写着「泰诺和 Tylenol 是同一个牌子」。
这张表是全站唯一的人工映射，所以每条都要有依据。

用法：python data/seed_families.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"

FAMILIES = [
    dict(
        family_id="tylenol",
        label="Tylenol / 泰诺",
        note="强生同一商标；美国是单方对乙酰氨基酚，中国「泰诺」是复方感冒药，"
             "中国单方叫「泰诺林」。三家不同成分，属严重碰撞。",
        keys=["tylenol extra strength", "tylenol", "泰诺", "泰诺林"],
    ),
    dict(
        family_id="benadryl",
        label="Benadryl",
        note="美国是苯海拉明（第一代、嗜睡），英国是阿伐斯汀（第二代、不嗜睡），"
             "同名不同分子。",
        keys=["benadryl", "benadryl allergy relief"],
    ),
    dict(
        family_id="gaviscon",
        label="Gaviscon",
        note="美国是铝/镁抗酸，英国是海藻酸钠 raft 体系，活性成分集合不相交。",
        keys=["gaviscon", "gaviscon original aniseed relief"],
    ),
    dict(
        family_id="lipitor",
        label="Lipitor / 立普妥",
        note="同一成分（阿托伐他汀钙），跨国同名的正常情况，无碰撞。",
        keys=["lipitor", "立普妥"],
    ),
]


def main() -> None:
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    missing: list[str] = []
    for fam in FAMILIES:
        db.execute(
            "INSERT OR REPLACE INTO brand_family (family_id, label, note) VALUES (?,?,?)",
            (fam["family_id"], fam["label"], fam["note"]),
        )
        for key in fam["keys"]:
            exists = db.execute(
                "SELECT 1 FROM name_key WHERE key_id = ?", (key,)).fetchone()
            if not exists:
                missing.append(key)
                continue
            db.execute(
                "INSERT OR IGNORE INTO name_family (key_id, family_id) VALUES (?, ?)",
                (key, fam["family_id"]),
            )
    db.commit()
    print(f"families: {len(FAMILIES)}")
    for r in db.execute(
        """SELECT bf.label, COUNT(nf.key_id) FROM brand_family bf
           LEFT JOIN name_family nf USING (family_id) GROUP BY bf.family_id"""
    ):
        print("  ", r)
    if missing:
        print("未入库的 key（可能是当前数据里没有这个名字）:", ", ".join(missing))
    db.close()


if __name__ == "__main__":
    main()
