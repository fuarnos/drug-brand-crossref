"""体检 NHSA 全量 CSV：字段可用性、商品名覆盖、药品代码里的 ATC。"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "raw" / "nhsa" / "nhsa_codes_20240105.csv"


def main() -> None:
    df = pd.read_csv(CSV, dtype=str, keep_default_na=False)
    print("rows", len(df))
    print("cols", list(df.columns))

    brand = df["商品名称"].str.strip()
    empty = brand.isin(["", "无", "无商品名", "-"])
    print("商品名非空:", int((~empty).sum()), f"({(~empty).mean():.1%})")

    # 药品代码：X + ATC(7) + 序号 + 剂型/规格码
    codes = df["药品代码"].str.strip()
    print("\n代码样式:", Counter(c[0] for c in codes.head(5000)).most_common(5))
    lens = Counter(len(c) for c in codes)
    print("代码长度分布:", lens.most_common(6))

    m = codes.str.match(r"^[A-Z]?([A-Z]\d{2}[A-Z]{0,2})")
    atc4 = codes.str.extract(r"^X?([A-Z]\d{2}[A-Z]{0,2})")[0]
    print("可抽出的 ATC 4-5 级前缀示例:", atc4.dropna().drop_duplicates().head(8).tolist())
    print("可抽出 ATC 的行数:", int(atc4.notna().sum()))

    # 化药 vs 中成药：用代码首字母区分（X 开头多为化药）
    print("\n首字母分布:", Counter(c[0] if c else "" for c in codes).most_common(8))

    nonempty = df[~empty]
    print("\n有商品名行数按代码首字母:", Counter(
        c[0] if c else "" for c in nonempty["药品代码"]).most_common(6))
    print("有商品名样例:")
    for _, r in nonempty.head(6).iterrows():
        print("   ", r["商品名称"], "|", r["注册名称"], "|", r["规格"], "|", r["药品企业"][:14])

    print("\n注册名称唯一数:", df["注册名称"].nunique())
    print("企业唯一数:", df["药品企业"].nunique())
    print("批准文号唯一数:", df["批准文号"].replace("", pd.NA).nunique())
    print("规格唯一数:", df["规格"].nunique())


if __name__ == "__main__":
    main()
