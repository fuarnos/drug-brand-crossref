"""命令行查询：python cli.py "Sortis 20mg" [--country CN] [--json]

先用它验证检索质量，再去建站。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib"))

from search import SearchIndex  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--country", default=None)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    idx = SearchIndex()
    res = idx.search(args.query, country=args.country, limit=args.limit)

    if args.json:
        print(json.dumps(
            {
                "query": res.query, "norm": res.norm,
                "strengths": list(res.strengths), "note": res.note,
                "alias": res.alias, "aliases": res.aliases,
                "cards": [c.__dict__ for c in res.cards],
            }, ensure_ascii=False, indent=2))
        return

    print(f'query = {res.query!r}  ->  norm = {res.norm!r}  '
          f'strengths={list(res.strengths)}  keys={res.total_keys}')
    if res.note:
        print(f"note  = {res.note}")
    for a in res.aliases:
        target = (a.get("label_zh") or a.get("inn_zh") or a.get("label_en")
                  or a.get("inn_en") or "—")
        print(f"alias = {a['alias']} -> {target} "
              f"({a['kind']}, {a['confidence']}; {a['source']})")
    if not res.cards:
        print("(no results)")
        return
    for i, c in enumerate(res.cards, 1):
        flag = {"severe": "!! 严重碰撞", "warning": "!  配方不同",
                "info": ""}.get(c.collision, "")
        print(f"{i:>2}. {c.brand}  [{c.country}]  {c.composition}  "
              f"{c.strength_text}  {c.dosage_form}  ×{c.n_products}  "
              f"score={c.score} ({c.tier}) {flag}")


if __name__ == "__main__":
    main()
