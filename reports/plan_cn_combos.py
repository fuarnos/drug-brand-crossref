"""P0 干跑：把中国复方的「注册名称」拆成多个成分，先看看可行性和命中率。

不写库，只统计。确认拆分质量后再写正式修复脚本。
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"

# 剂型尾巴，先剥掉再匹配
FORM_TAIL = re.compile(
    r"(片|胶囊|颗粒|散|丸|注射液|注射剂|输液|软膏|乳膏|凝胶|滴眼液|滴耳液|滴鼻液|"
    r"搽剂|洗剂|喷雾剂|气雾剂|贴剂|栓|膜|糖浆|口服液|混悬液|干混悬剂|溶液|酊|"
    r"胶浆|糊剂|乳剂|涂剂|含漱液|含片|分散片|缓释片|控释片|肠溶片|咀嚼片|泡腾片|"
    r"阴道片|眼膏|鼻用喷雾剂|吸入剂|粉雾剂|注射用|冻干|组合包装|（Ⅰ）|\(I\)|Ⅰ|Ⅱ|\(II\)|（Ⅱ）)+$")

# 剂量分隔：500mg:2.5mg / 0.5g:2.5mg / 500mg/125mg
DOSE_SPLIT = re.compile(r"\s*[:：/]\s*")
MASS = re.compile(r"^[\d.]+\s*(?:mg|g|μg|ug|ml|IU|万单位|%)$", re.I)


def dict_entries(db: sqlite3.Connection) -> dict[str, str]:
    """中文名 → substance_id。宁可少收，也不要收进会把名字切错的短词。"""
    d: dict[str, str] = {}
    for sid, zh, en in db.execute(
        "SELECT substance_id, inn_zh, inn_en FROM substance"):
        for name in (zh, en):
            if not name or len(name) < 3:
                continue
            if not re.search(r"[\u4e00-\u9fff]", name):
                continue
            d.setdefault(name, sid)
    return d


def strip_form(name: str) -> str:
    prev = None
    s = name.strip()
    while s != prev:
        prev = s
        s = FORM_TAIL.sub("", s).strip()
    return s


def split_name(name: str, vocab: dict[str, str], maxlen: int):
    """最长匹配切分，返回 [(token, sid)]；切不动就返回一个 token。"""
    s = strip_form(name)
    out, i = [], 0
    while i < len(s):
        hit = None
        for L in range(min(maxlen, len(s) - i), 2, -1):
            cand = s[i:i + L]
            if cand in vocab:
                hit = (cand, vocab[cand])
                break
        if hit:
            out.append(hit)
            i += len(hit[0])
        else:
            i += 1
    return out


def main() -> None:
    db = sqlite3.connect(DB)
    vocab = dict_entries(db)
    maxlen = max(len(k) for k in vocab)
    print(f"词典条目 {len(vocab)}，最长 {maxlen} 字")

    rows = db.execute(
        """SELECT p.product_id, pv.raw, pc.strength_value, pc.strength_unit
           FROM product p
           JOIN product_name pn ON pn.product_id = p.product_id
           JOIN name_variant pv ON pv.key_id = pn.key_id
           LEFT JOIN product_component pc ON pc.product_id = p.product_id
           WHERE p.country = 'CN' AND pn.name_type = 'inn'""").fetchall()
    print(f"产品行 {len(rows)}")

    seen = set()
    multi, examples = 0, []
    for pid, raw, sv, su in rows:
        if pid in seen:
            continue
        seen.add(pid)
        parts = split_name(raw, vocab, maxlen)
        if len(parts) >= 2:
            multi += 1
            if len(examples) < 25:
                examples.append((raw, [p[0] for p in parts], [p[1] for p in parts]))
    print(f"可拆出 ≥2 个成分的产品: {multi} / {len(seen)}")

    print("\n样例：")
    for raw, toks, sids in examples:
        print(f"  {raw}\n     -> {' + '.join(toks)}")

    # 长度分布：切出的 token 有几个是“短词碎片”
    frag = Counter()
    for raw, toks, _ in examples:
        for t in toks:
            if len(t) <= 3:
                frag[t] += 1
    print("\n可疑短碎片（<=3 字）:", frag.most_common(10))


if __name__ == "__main__":
    main()
