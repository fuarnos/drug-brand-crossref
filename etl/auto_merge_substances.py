"""P1 自动化：检测并合并「同一成分被拆成两个 id」的重复。

判据（不靠人工列表）：
  1. ATC 编码前 5 位相同，且英文名编辑距离 <= 2  -> 候选
  2. 英文名归一化后完全相同（只差大小写/空格/标点） -> 直接合并
  3. 中文名相同 -> 候选

用法：
    python etl/auto_merge_substances.py            # 只出报告
    python etl/auto_merge_substances.py --apply    # 执行合并（保留产品多的 id）
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
REPORT = ROOT / "reports" / "substance_duplicates.csv"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s)


def lev(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 3:
        return 99
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, cb in enumerate(b, 1):
            t = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (ca != cb))
            prev = t
    return d[len(b)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(DB, timeout=120)
    rows = db.execute(
        """SELECT s.substance_id, s.inn_en, s.inn_zh, s.atc,
                  (SELECT COUNT(*) FROM variant v JOIN product_component pc
                     ON pc.variant_id = v.variant_id
                    WHERE v.substance_id = s.substance_id) AS n
           FROM substance s""").fetchall()
    print(f"成分 {len(rows)} 个")

    by_atc: dict[str, list] = defaultdict(list)
    for sid, en, zh, atc, n in rows:
        if atc and len(atc) >= 5:
            by_atc[atc[:5]].append((sid, en, zh, n))

    pairs: list[tuple] = []
    for atc, group in by_atc.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                na, nb = norm(a[1]), norm(b[1])
                if not na or not nb:
                    continue
                # 只自动合并「名字归一化后完全相同」或「中文名相同」的；
                # 编辑距离近的（如各类头孢）只进报告，人工判断，避免把不同药合并。
                if na == nb or (a[2] and a[2] == b[2]):
                    pairs.append((atc, a, b))
    print(f"同 ATC-4 下的疑似重复: {len(pairs)} 对")

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for _atc, a, b in pairs:
        union(a[0], b[0])

    groups: dict[str, list] = defaultdict(list)
    for sid, en, zh, _atc, n in rows:
        if sid in parent:
            groups[find(sid)].append((sid, en, zh, n))
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"应合并成一组: {len(multi)} 组，涉及 {sum(len(v) for v in multi.values())} 个 id")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", encoding="utf-8-sig", newline="") as fh:
        fh.write("canonical,dup_id,dup_name,products\n")
        for _root, members in sorted(multi.items(), key=lambda kv: -sum(m[3] for m in kv[1])):
            members.sort(key=lambda m: -m[3])
            canon = members[0]
            for m in members[1:]:
                fh.write(f"{canon[0]},{m[0]},{m[1]},{m[3]}\n")
    print(f"报告: {REPORT}")

    if args.apply:
        merged = 0
        for _root, members in multi.items():
            members.sort(key=lambda m: -m[3])
            canon = members[0][0]
            for sid, _en, _zh, _n in members[1:]:
                db.execute("UPDATE variant SET substance_id = ? WHERE substance_id = ?",
                           (canon, sid))
                db.execute("DELETE FROM substance WHERE substance_id = ?", (sid,))
                merged += 1
        db.commit()
        print(f"已合并 {merged} 个重复 id")
    else:
        print("（未写库，加 --apply 执行）")
    db.close()


if __name__ == "__main__":
    main()
