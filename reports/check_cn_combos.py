"""复查 CN 复方塌陷：注册名称里含 2 个及以上已知成分名，但库里只有 1 个成分。"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "raw" / "nhsa" / "nhsa_codes_20250404.csv"
DB = ROOT / "data" / "drugs.db"


def main() -> None:
    db = sqlite3.connect(DB)
    zh = [r[0] for r in db.execute(
        "SELECT inn_zh FROM substance WHERE inn_zh IS NOT NULL AND length(inn_zh) >= 2")]
    # 长名优先，避免"格列本脲"被"格列"之类短词误命中
    zh.sort(key=len, reverse=True)
    print(f"用于检测的成分中文名: {len(zh)}")

    df = pd.read_csv(CSV, dtype=str, keep_default_na=False)
    x = df[df["药品代码"].str.startswith("X")]
    print(f"化药行数: {len(x)}")

    def hits(name: str) -> list[str]:
        found, rest = [], name
        for z in zh:
            if z in rest and len(z) >= 3:      # 只认 3 字以上，减少误判
                found.append(z)
                rest = rest.replace(z, "·")
        return found

    names = x["注册名称"].unique()
    combo = {}
    for n in names:
        h = hits(n)
        if len(h) >= 2:
            combo[n] = h
    rows = x[x["注册名称"].isin(combo)]
    print(f"疑似复方注册名称: {len(combo)} 个，涉及行数 {len(rows)}")

    # 这些名字在库里挂到几个成分
    multi = 0
    for n in list(combo)[:0]:
        pass
    q = """SELECT COUNT(DISTINCT v.substance_id) FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN product_name pn ON pn.product_id = p.product_id
           JOIN name_variant nv ON nv.key_id = pn.key_id
           WHERE p.country = 'CN' AND nv.raw = ?"""
    single = 0
    for n in combo:
        c = db.execute(q, (n,)).fetchone()[0]
        if c <= 1:
            single += 1
    print(f"其中库里只挂 1 个成分的注册名称: {single} / {len(combo)}")

    top = Counter()
    for n in rows["注册名称"]:
        top[n] += 1
    print("\n受影响最大的 12 个注册名称（行数）：")
    for n, c in top.most_common(12):
        print(f"  {c:>5}  {n}   ← {' + '.join(combo[n][:4])}")

    print("\n规格里带两个剂量的行数：")
    two = x["规格"].str.contains(r"\d\s*(?:mg|g|ml|μg|ug)\s*[:：/]", regex=True, na=False)
    print(f"  {int(two.sum())} 行")
    print("样例：")
    for _, r in x[two].head(6).iterrows():
        print(f"  {r['注册名称']} | 规格={r['规格']}")


if __name__ == "__main__":
    main()
