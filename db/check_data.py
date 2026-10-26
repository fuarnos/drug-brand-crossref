"""数据体检：入库后快速看一眼质量。python db/check_data.py"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "drugs.db"


def main() -> None:
    db = sqlite3.connect(DB)
    print("== coverage ==")
    for row in db.execute("SELECT * FROM coverage"):
        print("  ", row)

    print("== counts ==")
    for label, sql in (
        ("products", "SELECT COUNT(*) FROM product"),
        ("components", "SELECT COUNT(*) FROM product_component"),
        ("substances", "SELECT COUNT(*) FROM substance"),
        ("variants", "SELECT COUNT(*) FROM variant"),
        ("name_keys", "SELECT COUNT(*) FROM name_key"),
        ("names", "SELECT COUNT(*) FROM product_name"),
        ("collisions(severe)", "SELECT COUNT(*) FROM collision WHERE level='severe'"),
        ("collisions(warning)", "SELECT COUNT(*) FROM collision WHERE level='warning'"),
        ("nickname", "SELECT COUNT(*) FROM nickname"),
        ("drug_term", "SELECT COUNT(*) FROM drug_term"),
        ("aliases(total)", "SELECT COUNT(*) FROM alias_all"),
        ("confusable_pairs", "SELECT COUNT(*) FROM confusable_pair"),
    ):
        print(f"   {label:20} {db.execute(sql).fetchone()[0]}")

    print("== top trade names ==")
    for raw, n in db.execute(
        """SELECT nv.raw, COUNT(DISTINCT pn.product_id) c
           FROM product_name pn
           JOIN name_variant nv ON nv.key_id = pn.key_id
           JOIN product p ON p.product_id = pn.product_id
           WHERE pn.name_type = 'trade' AND p.country = 'US'
           GROUP BY nv.raw ORDER BY c DESC LIMIT 12"""
    ):
        print(f"   {raw:32} {n}")

    print("== atorvastatin ==")
    for row in db.execute(
        """SELECT p.product_id, nv.raw, pc.strength_value, pc.strength_unit, p.dosage_form
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           LEFT JOIN product_name pn ON pn.product_id = p.product_id AND pn.is_primary = 1
           LEFT JOIN name_variant nv ON nv.key_id = pn.key_id
           WHERE v.substance_id = 'atorvastatin' LIMIT 6"""
    ):
        print("  ", row)

    print("== US terms (sample) ==")
    for row in db.execute(
        """SELECT term, term_type, substance_id, label_zh
           FROM drug_term ORDER BY term_id LIMIT 12"""
    ):
        print("  ", row)

    print("== confusable pairs (sample) ==")
    for row in db.execute(
        """SELECT name_a, name_b, a_substance_id, b_substance_id
           FROM confusable_pair ORDER BY pair_id LIMIT 12"""
    ):
        print("  ", row)

    print("== severe collisions (sample) ==")
    for row in db.execute(
        """SELECT c.key_id, c.n_substances, c.n_products
           FROM collision c WHERE c.level = 'severe'
           ORDER BY c.n_substances DESC, c.n_products DESC LIMIT 10"""
    ):
        print("  ", row)

    db.close()


if __name__ == "__main__":
    main()
