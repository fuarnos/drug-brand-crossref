"""ARTG 名称层 → SQLite（artg_entry 表）。

数据：data/raw/artg/medicine_index.jsonl（etl/fetch_artg_index.py 抓的 eBS 目录）。
一行 = 商品名 + 申办方 + ARTG ID；没有成分、没有状态字段，所以：
- 不建 product（product 必须有活性成分）；
- 只进 artg_entry，检索时作为「登记存在、成分未收录」的兜底。

用法：python etl/ingest_artg_index.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import normalize  # noqa: E402

CACHE = ROOT / "data" / "raw" / "artg"
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "artg_index"
TODAY = date.today().isoformat()
LISTING = "https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    src = CACHE / "medicine_index.jsonl"
    if not src.exists():
        raise SystemExit(f"没有 {src}，先跑 python etl/fetch_artg_index.py")

    rows = []
    seen = set()
    for line in src.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        aid = r.get("artg_id")
        if not aid or aid in seen or not r.get("name"):
            continue
        seen.add(aid)
        rows.append(r)
    print(f"medicine_index.jsonl：{len(rows)} 条唯一 ARTG 条目")

    db = sqlite3.connect(DB, timeout=60)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.execute("DELETE FROM artg_entry WHERE source_id=?", (SOURCE_ID,))
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        (SOURCE_ID, "TGA eBS — Australian Register of Current Medicines (index)",
         LISTING, "TGA public register（事实字段：名称/申办方/ARTG ID）",
         "https://www.tga.gov.au/copyright", TODAY,
         "eBS 目录 30 条/页翻页抓取；只有名称层，无成分/规格"))

    n = 0
    for r in rows:
        if args.limit and n >= args.limit:
            break
        norm = normalize(r["name"]).norm
        if not norm:
            continue
        db.execute(
            "INSERT OR REPLACE INTO artg_entry (artg_id, name, name_norm, sponsor,"
            " retrieved_at, source_id) VALUES (?,?,?,?,?,?)",
            (r["artg_id"], r["name"], norm, r.get("sponsor"), r.get("retrieved_at"), SOURCE_ID))
        n += 1
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM artg_entry").fetchone()[0]
    print(f"artg_entry：{total} 条")
    for row in db.execute(
            "SELECT COUNT(*) FROM artg_entry WHERE name LIKE '%gaviscon%'"):
        print(f"  gaviscon 条目：{row[0]}")
    db.close()


if __name__ == "__main__":
    main()
