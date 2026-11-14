"""T16 计数探针 ②（只读）：warning 页按「已知释放码数 × 有未标注记录」分组。

用法：$py .tmp/t16-count2.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
db = sqlite3.connect(f"file:{ROOT / 'data' / 'drugs.db'}?mode=ro", uri=True)
db.row_factory = sqlite3.Row

sql = """
WITH rel AS (
  SELECT pn.key_id,
         COUNT(DISTINCT CASE WHEN p.release <> 'none' THEN p.release END) AS n_known,
         SUM(CASE WHEN p.release = 'none' THEN 1 ELSE 0 END) AS n_unknown,
         COUNT(DISTINCT p.product_id) AS n_prod
  FROM product_name pn JOIN product p ON p.product_id = pn.product_id
  GROUP BY pn.key_id
)
SELECT r.n_known, CASE WHEN r.n_unknown > 0 THEN 1 ELSE 0 END AS has_unknown,
       COUNT(*) AS pages, SUM(r.n_unknown) AS unknown_rows
FROM rel r JOIN collision c ON c.key_id = r.key_id AND c.level = 'warning'
GROUP BY 1, 2 ORDER BY 1, 2
"""
print("warning 页分组（已知释放码数 × 是否有未标注记录 → 页数 / 未标注行数）")
total = 0
for row in db.execute(sql):
    total += row["pages"]
    print(f"  n_known={row['n_known']} has_unknown={row['has_unknown']}: "
          f"{row['pages']:,} 页 / {row['unknown_rows']:,} 行未标注")
print(f"  合计 {total:,} 页")

print("\n所有名字页（不只是 warning）按同样口径：")
sql2 = sql.replace("JOIN collision c ON c.key_id = r.key_id AND c.level = 'warning'", "")
sql2 = sql2.replace("FROM rel r \n", "FROM rel r ")
for row in db.execute(sql2):
    print(f"  n_known={row['n_known']} has_unknown={row['has_unknown']}: {row['pages']:,} key")
