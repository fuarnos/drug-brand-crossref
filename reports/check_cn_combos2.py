"""复查 CN 复方塌陷 v2：用「规格里出现两个质量剂量」和已知复方名做双重检测。"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "raw" / "nhsa" / "nhsa_codes_20250404.csv"
DB = ROOT / "data" / "drugs.db"

# 两个质量剂量用 : 或 / 连接，例如 500mg:2.5mg、5mg/10mg
TWO_MASS = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|g|μg|ug|mg)\s*[:：/]\s*\d+(?:\.\d+)?\s*(?:mg|g|μg|ug|mg)",
    re.IGNORECASE)

# 常见复方前缀（人工列的，宁可少列也不误伤）
COMBO_HINTS = [
    "二甲双胍格列本脲", "格列本脲二甲双胍", "二甲双胍格列齐特", "二甲双胍罗格列酮",
    "二甲双胍吡格列酮", "二甲双胍西格列汀", "二甲双胍维格列汀", "二甲双胍沙格列汀",
    "二甲双胍利格列汀", "二甲双胍达格列净", "二甲双胍恩格列净",
    "氨氯地平阿托伐他汀", "氨氯地平缬沙坦", "氨氯地平贝那普利", "氨氯地平培哚普利",
    "缬沙坦氨氯地平", "氯沙坦钾氢氯噻嗪", "厄贝沙坦氢氯噻嗪", "缬沙坦氢氯噻嗪",
    "替米沙坦氢氯噻嗪", "奥美沙坦酯氢氯噻嗪", "卡托普利氢氯噻嗪", "贝那普利氢氯噻嗪",
    "赖诺普利氢氯噻嗪", "美托洛尔氢氯噻嗪", "比索洛尔氢氯噻嗪",
    "阿莫西林克拉维酸", "氨苄西林舒巴坦", "头孢哌酮舒巴坦", "哌拉西林他唑巴坦",
    "替卡西林克拉维酸", "亚胺培南西司他丁", "美洛西林舒巴坦", "头孢曲松舒巴坦",
    "左氧氟沙星", "莫西沙星", "对乙酰氨基酚伪麻黄碱", "布洛芬伪麻黄碱",
    "氨酚咖匹林", "复方氨酚烷胺", "氨酚黄那敏", "酚麻美敏",
]


def main() -> None:
    df = pd.read_csv(CSV, dtype=str, keep_default_na=False)
    x = df[df["药品代码"].str.startswith("X")].copy()

    spec2 = x["规格"].str.contains(TWO_MASS, regex=True, na=False)
    hint = x["注册名称"].apply(lambda n: any(h in n for h in COMBO_HINTS))
    print(f"化药行数 {len(x)}")
    print(f"  规格含两个质量剂量 : {int(spec2.sum())} 行 / {x[spec2]['注册名称'].nunique()} 个名字")
    print(f"  名字命中常见复方前缀: {int(hint.sum())} 行 / {x[hint]['注册名称'].nunique()} 个名字")
    print(f"  两者任一           : {int((spec2 | hint).sum())} 行 / {x[spec2 | hint]['注册名称'].nunique()} 个名字")

    db = sqlite3.connect(DB)
    q = """SELECT COUNT(DISTINCT v.substance_id) FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN product_name pn ON pn.product_id = p.product_id
           JOIN name_variant nv ON nv.key_id = pn.key_id
           WHERE p.country='CN' AND nv.raw = ?"""
    names = sorted(set(x[spec2 | hint]["注册名称"]))
    single = [n for n in names if db.execute(q, (n,)).fetchone()[0] <= 1]
    print(f"\n这些名字里，库里只挂 1 个成分的: {len(single)} / {len(names)}")

    print("\n受影响的例子（规格 → 库里成分）：")
    shown = 0
    for n in single:
        if shown >= 12:
            break
        row = x[x["注册名称"] == n].iloc[0]
        subs = [r[0] for r in db.execute(
            """SELECT DISTINCT s.inn_en FROM product p
               JOIN product_component pc ON pc.product_id=p.product_id
               JOIN variant v ON v.variant_id=pc.variant_id
               JOIN substance s ON s.substance_id=v.substance_id
               JOIN product_name pn ON pn.product_id=p.product_id
               JOIN name_variant nv ON nv.key_id=pn.key_id
               WHERE p.country='CN' AND nv.raw=? LIMIT 3""", (n,))]
        print(f"  {n}\n     规格={row['规格']}  库里={subs}")
        shown += 1

    print("\n规格里出现两个质量剂量的样例：")
    for _, r in x[spec2].head(8).iterrows():
        print(f"  {r['注册名称']} | {r['规格']}")


if __name__ == "__main__":
    main()
