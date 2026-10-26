"""数一数 CN 里「名字明显是复方、但库里只有 1 个成分」的产品有多少。"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"

HINTS = [
    "二甲双胍格列本脲", "二甲双胍格列齐特", "二甲双胍罗格列酮", "二甲双胍吡格列酮",
    "二甲双胍西格列汀", "二甲双胍维格列汀", "二甲双胍沙格列汀", "二甲双胍利格列汀",
    "二甲双胍达格列净", "二甲双胍恩格列净", "二甲双胍格列吡嗪",
    "氨氯地平阿托伐他汀", "氨氯地平缬沙坦", "氨氯地平贝那普利", "氨氯地平培哚普利",
    "氨氯地平氯沙坦", "缬沙坦氨氯地平", "氯沙坦钾氢氯噻嗪", "厄贝沙坦氢氯噻嗪",
    "缬沙坦氢氯噻嗪", "替米沙坦氢氯噻嗪", "奥美沙坦酯氢氯噻嗪", "卡托普利氢氯噻嗪",
    "贝那普利氢氯噻嗪", "赖诺普利氢氯噻嗪", "美托洛尔氢氯噻嗪", "比索洛尔氢氯噻嗪",
    "阿莫西林克拉维酸", "氨苄西林舒巴坦", "头孢哌酮舒巴坦", "哌拉西林他唑巴坦",
    "替卡西林克拉维酸", "亚胺培南西司他丁", "美洛西林舒巴坦", "头孢曲松舒巴坦",
    "头孢噻肟舒巴坦", "阿莫西林双氯西林", "对乙酰氨基酚伪麻黄碱",
    "布洛芬伪麻黄碱", "氨酚咖匹林", "复方氨酚烷胺", "氨酚黄那敏", "酚麻美敏",
    "左炔诺孕酮炔雌醇", "去氧孕烯炔雌醇", "炔雌醇环丙孕酮", "屈螺酮炔雌醇",
    "格列吡嗪二甲双胍", "瑞格列奈二甲双胍",
]


def main() -> None:
    db = sqlite3.connect(DB)
    rows = db.execute(
        """SELECT pv.raw, p.product_id,
                  (SELECT COUNT(*) FROM product_component x WHERE x.product_id = p.product_id),
                  (SELECT GROUP_CONCAT(DISTINCT s.inn_en) FROM product_component pc
                     JOIN variant v ON v.variant_id = pc.variant_id
                     JOIN substance s ON s.substance_id = v.substance_id
                    WHERE pc.product_id = p.product_id)
           FROM product p
           JOIN product_name pn ON pn.product_id = p.product_id
           JOIN name_variant pv ON pv.key_id = pn.key_id
           WHERE p.country = 'CN'""").fetchall()

    hit = [r for r in rows if any(h in r[0] for h in HINTS)]
    single = [r for r in hit if r[2] <= 1]
    print(f"名字命中复方词的产品行: {len(hit)}")
    print(f"其中只有一个成分的    : {len(single)}")
    print(f"每行平均成分数        : {sum(r[2] for r in hit)/max(len(hit),1):.2f}")

    names = Counter(r[0] for r in single)
    print("\n受影响最多的注册名称：")
    for n, c in names.most_common(15):
        subs = next((r[3] for r in single if r[0] == n), "")
        print(f"  {c:>4}  {n}   现有成分: {subs}")


if __name__ == "__main__":
    main()
