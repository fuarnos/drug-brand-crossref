"""FDA tall-man 易混淆药对入库。

数据源：FDA Name Differentiation Project
  https://www.fda.gov/drugs/medication-errors-related-cder-regulated-drug-products/fda-name-differentiation-project
  Content current as of 2026-06-12；美国政府作品（public domain）。

范围说明：
  这是 FDA 官方「建议 tall-man 拼写」的 22 对，不是 ISMP 全量 LASA 清单。
  ISMP/ECRI 的 List of Confused Drug Names 有版权，未整表复制；本站只收
  官方可再发布的配对。算法候选另出 CSV，不自动入库。

运行：
    python etl/ingest_fda_confusable.py --dry-run
    python etl/ingest_fda_confusable.py
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import normalize  # noqa: E402

DB = ROOT / "data" / "drugs.db"
CSV_PATH = ROOT / "data" / "sources" / "fda-tall-man-pairs.csv"
URL = ("https://www.fda.gov/drugs/medication-errors-related-cder-regulated-drug-products/"
       "fda-name-differentiation-project")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    # 成分名 -> substance_id。先按 inn_en 精确匹配，再按 substance_id 匹配。
    by_name: dict[str, str] = {}
    for sid, inn in db.execute("SELECT substance_id, inn_en FROM substance"):
        by_name.setdefault((inn or "").casefold(), sid)
        by_name.setdefault(sid.casefold(), sid)

    rows = []
    missing: list[str] = []
    for r in csv.DictReader(CSV_PATH.read_text(encoding="utf-8-sig").splitlines()):
        a, b = r["name_a"].strip(), r["name_b"].strip()
        na, nb = normalize(a), normalize(b)
        if not na.norm or not nb.norm or na.norm == nb.norm:
            print(f"跳过：{a} / {b}（归一化后为空或相同）")
            continue
        # 固定顺序，保证同一对不会因为正反写两次而重复。
        if na.norm > nb.norm:
            a, b = b, a
            na, nb = nb, na
            r["tml_a"], r["tml_b"] = r["tml_b"], r["tml_a"]
        sa = by_name.get(a.casefold())
        sb = by_name.get(b.casefold())
        if not sa:
            missing.append(a)
        if not sb:
            missing.append(b)
        rows.append({
            "name_a": a,
            "name_b": b,
            "norm_a": na.norm,
            "norm_b": nb.norm,
            "a_substance_id": sa,
            "b_substance_id": sb,
            "tml_a": r["tml_a"].strip(),
            "tml_b": r["tml_b"].strip(),
            "reason": r["reason"].strip() or "both",
            "note": r["note"].strip(),
        })

    print(f"FDA 配对 {len(rows)} 对；未映射成分 {len(set(missing))} 个："
          f"{', '.join(sorted(set(missing))) or '无'}")
    if args.dry_run:
        for r in rows:
            print(f"  {r['name_a']:18} ↔ {r['name_b']:18} "
                  f"{r['a_substance_id'] or '-':18} {r['b_substance_id'] or '-'}")
        db.close()
        return

    today = date.today().isoformat()
    db.execute(
        """INSERT INTO source (source_id, name, url, license, license_url,
                               retrieved_at, notes)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT (source_id) DO UPDATE SET
               name=excluded.name, url=excluded.url, license=excluded.license,
               license_url=excluded.license_url, retrieved_at=excluded.retrieved_at,
               notes=excluded.notes""",
        ("fda_tml", "FDA Name Differentiation Project (tall-man list)", URL,
         "US Government work (public domain)", None, today,
         "FDA 官方建议 tall-man 拼写的药对；不是 ISMP 全量 LASA 清单。"))
    db.execute("DELETE FROM confusable_pair WHERE source_id = 'fda_tml'")
    db.executemany(
        """INSERT INTO confusable_pair
           (name_a, name_b, norm_a, norm_b, a_substance_id, b_substance_id,
            tml_a, tml_b, reason, severity, source_id, source_url, note, created_at)
           VALUES (:name_a, :name_b, :norm_a, :norm_b, :a_substance_id,
                   :b_substance_id, :tml_a, :tml_b, :reason, 'high',
                   'fda_tml', :source_url, :note, :created_at)""",
        [{**r, "source_url": URL, "created_at": today} for r in rows],
    )
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM confusable_pair").fetchone()[0]
    print(f"confusable_pair: 写入 {len(rows)} 对；表内共 {total} 对")
    db.close()


if __name__ == "__main__":
    main()
