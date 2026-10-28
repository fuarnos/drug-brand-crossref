#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扩展评测集 cases_v2.json（320 例）的 minimal runner。

只读打开 `data/drugs.db`，直接复用站点检索层 `lib/search.py`（测的就是线上行为）；
期望值来自 `cases_v2.json`（由 gen_cases.py 从 DB 结构关系推导，**不**来自检索输出）。

统计口径（与 reports/search-eval-expansion.md 一致）：
    must_hit   ：Top-5 内出现全部期望成分 → 通过；另报 Top-1
    must_empty ：0 结果 → 通过；有结果即「零结果误命中」
    gap        ：当前基线预期 miss 的改造目标，单独统计「意外命中」，不计入通过率

用法：
    python tests/trilingual/run_cases_v2.py                 # 全量基线
    python tests/trilingual/run_cases_v2.py --category salt  # 单类
    python tests/trilingual/run_cases_v2.py --json out.json --quiet
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import lib.search as search_mod  # noqa: E402

DB = ROOT / "data" / "drugs.db"
CASES = ROOT / "tests" / "trilingual" / "cases_v2.json"
OUT_DEFAULT = ROOT / ".tmp" / "search-eval" / "baseline.json"

_REAL_CONNECT = sqlite3.connect


def _ro_connect(database, *args, **kwargs):
    """只读打开 + 长超时：其他 agent 正在写库时避免 database is locked。"""
    s = str(database)
    kwargs.setdefault("timeout", 60)
    if "mode=ro" not in s:
        return _REAL_CONNECT("file:" + s + "?mode=ro", uri=True, *args, **kwargs)
    return _REAL_CONNECT(database, *args, **kwargs)


def search_retry(idx, query, attempts: int = 5):
    last = None
    for i in range(attempts):
        try:
            return idx.search(query)
        except sqlite3.OperationalError as exc:  # 写锁：短暂等待后重试
            last = exc
            time.sleep(1.5 * (i + 1))
    raise last


def load_sub_inn(db_path: Path) -> dict[str, str]:
    con = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True)
    out = {sid: (inn or sid) for sid, inn in
           con.execute("SELECT substance_id, inn_en FROM substance")}
    con.close()
    return out


def evaluate_case(idx, case: dict, sub_inn: dict[str, str]) -> dict:
    t0 = time.time()
    res = search_retry(idx, case["query"])
    dt = time.time() - t0
    expected = case["expected"]
    policy = expected["policy"]
    exp_ids = expected.get("substance_ids") or []
    exp_inn = [sub_inn[s] for s in exp_ids if s in sub_inn]
    cards = res.cards
    top_cards = cards[:5]
    rank = None
    if exp_inn:
        for i, card in enumerate(top_cards):
            subs = [s for s in card.substances if s]
            if all(e in subs for e in exp_inn):
                rank = i
                break
        if rank is None:
            for i, card in enumerate(top_cards):
                subs = [s for s in card.substances if s]
                if sum(1 for e in exp_inn if e in subs) >= 2:
                    rank = i + 0.5  # 部分命中（≥2 成分），仅记录
                    break
    top1 = [s for s in (cards[0].substances if cards else []) if s]
    out = dict(
        case_id=case["case_id"], category=case["category"], lang=case["lang"],
        query=case["query"], query_type=case.get("query_type", ""),
        policy=policy, expected=exp_inn,
        n_cards=len(cards),
        top1=top1[:5],
        rank=rank,
        hit_top5=(rank is not None),
        hit_top1=(rank == 0),
        note=res.note,
        tier=(cards[0].tier if cards else ""),
        countries=sorted({c.country for c in cards}),
        seconds=round(dt, 3),
    )
    if policy == "must_empty":
        out["pass"] = (len(cards) == 0)
        out["false_hit"] = (len(cards) > 0)
    elif policy == "gap":
        out["pass"] = None
        out["would_hit"] = (rank is not None)
    else:
        out["pass"] = (rank is not None)
    return out


def summarize(rows: list[dict]) -> dict:
    by_cat: dict[str, dict] = defaultdict(
        lambda: dict(n=0, must_hit=0, top1=0, top5=0, must_empty=0,
                     zero_false_hit=0, gap=0, gap_hit=0))
    for r in rows:
        s = by_cat[r["category"]]
        s["n"] += 1
        if r["policy"] == "must_hit":
            s["must_hit"] += 1
            s["top5"] += int(r["hit_top5"])
            s["top1"] += int(r["hit_top1"])
        elif r["policy"] == "must_empty":
            s["must_empty"] += 1
            s["zero_false_hit"] += int(r.get("false_hit", False))
        elif r["policy"] == "gap":
            s["gap"] += 1
            s["gap_hit"] += int(bool(r.get("would_hit")))
    total_hit = sum(s["must_hit"] for s in by_cat.values())
    top1 = sum(s["top1"] for s in by_cat.values())
    top5 = sum(s["top5"] for s in by_cat.values())
    zero_n = sum(s["must_empty"] for s in by_cat.values())
    zero_bad = sum(s["zero_false_hit"] for s in by_cat.values())
    gap_n = sum(s["gap"] for s in by_cat.values())
    gap_hit = sum(s["gap_hit"] for s in by_cat.values())
    gate_n = total_hit + zero_n
    gate_pass = top5 + (zero_n - zero_bad)
    return dict(
        by_category={k: dict(v) for k, v in by_cat.items()},
        must_hit_cases=total_hit, top1=top1, top5=top5,
        top1_rate=round(top1 / total_hit, 4) if total_hit else 0.0,
        top5_rate=round(top5 / total_hit, 4) if total_hit else 0.0,
        must_empty_cases=zero_n, zero_false_hits=zero_bad,
        must_empty_rate=round((zero_n - zero_bad) / zero_n, 4) if zero_n else 1.0,
        gap_cases=gap_n, gap_unexpected_hits=gap_hit,
        gate_cases=gate_n, gate_pass=gate_pass,
        gate_rate=round(gate_pass / gate_n, 4) if gate_n else 1.0,
    )


def print_summary(summary: dict, rows: list[dict], quiet: bool) -> None:
    print("\n== 分类基线 ==")
    print(f"{'category':<14}{'n':>4}{'Top1':>7}{'Top5':>7}{'Top5%':>8}"
          f"{'empty':>7}{'误命中':>7}{'gap':>5}{'gap命中':>8}")
    for cat in ("en_typo", "es_typo", "zh_char_typo", "pinyin", "jianfan",
                "combo", "salt", "zero_result"):
        s = summary["by_category"].get(cat)
        if not s:
            continue
        pct = (s["top5"] / s["must_hit"] * 100) if s["must_hit"] else 0.0
        print(f"{cat:<14}{s['n']:>4}{s['top1']:>7}{s['top5']:>7}{pct:>7.1f}%"
              f"{s['must_empty']:>7}{s['zero_false_hit']:>7}{s['gap']:>5}"
              f"{s['gap_hit']:>8}")
    print(f"\nmust_hit：{summary['top5']}/{summary['must_hit_cases']} "
          f"Top-5（{summary['top5_rate']*100:.1f}%），Top-1 "
          f"{summary['top1']}/{summary['must_hit_cases']}"
          f"（{summary['top1_rate']*100:.1f}%）")
    print(f"must_empty：{summary['must_empty_cases'] - summary['zero_false_hits']}"
          f"/{summary['must_empty_cases']} 通过；零结果误命中 "
          f"{summary['zero_false_hits']}")
    print(f"gap（不计入通过率）：{summary['gap_cases']} 例，意外命中 "
          f"{summary['gap_unexpected_hits']}")
    print(f"综合通过（must_hit Top5 + must_empty）："
          f"{summary['gate_pass']}/{summary['gate_cases']}"
          f"（{summary['gate_rate']*100:.1f}%）")
    if not quiet:
        fails = [r for r in rows if r["policy"] == "must_hit" and not r["hit_top5"]]
        if fails:
            print(f"\n未命中样例（前 12 / 共 {len(fails)}）:")
            for r in fails[:12]:
                print(f"  [{r['category']}] {r['query']!r} 期望={r['expected']} "
                      f"cards={r['n_cards']} top1={r['top1']} note={r['note']!r}")
        zero_bad = [r for r in rows if r["policy"] == "must_empty" and r.get("false_hit")]
        if zero_bad:
            print(f"\n零结果误命中（前 12 / 共 {len(zero_bad)}）:")
            for r in zero_bad[:12]:
                print(f"  {r['query']!r} cards={r['n_cards']} top1={r['top1']}")


_WORKER: dict = {}


def _worker_init(db_path: str) -> None:
    """每个进程只建一次 SearchIndex（加载 135k name_key + 别名表）。"""
    sqlite3.connect = _ro_connect
    _WORKER["idx"] = search_mod.SearchIndex(Path(db_path))
    _WORKER["sub_inn"] = load_sub_inn(Path(db_path))


def _work_one(case: dict) -> dict:
    return evaluate_case(_WORKER["idx"], case, _WORKER["sub_inn"])


def run_parallel(cases: list[dict], db_path: Path, jobs: int) -> list[dict]:
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=jobs, initializer=_worker_init,
                  initargs=(str(db_path),)) as pool:
        rows = list(pool.imap(_work_one, cases, chunksize=4))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="cases_v2.json 扩展评测集 runner")
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument("--db", default=str(DB), help="只读 DB（可用快照副本）")
    ap.add_argument("--json", default=str(OUT_DEFAULT))
    ap.add_argument("--category", default="", help="逗号分隔类别过滤")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（调试）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--jobs", type=int, default=1,
                    help="并行进程数（>1 时用 multiprocessing；建议 4–8）")
    args = ap.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"FATAL: 用例不存在: {cases_path}", file=sys.stderr)
        return 2
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    meta = payload.get("meta", {})
    cases = payload["cases"]
    cats = {c.strip() for c in args.category.split(",") if c.strip()}
    if cats:
        cases = [c for c in cases if c["category"] in cats]
    if args.limit:
        cases = cases[: args.limit]

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FATAL: DB 不存在: {db_path}", file=sys.stderr)
        return 2

    t_start = time.time()
    sqlite3.connect = _ro_connect
    db_sha = meta.get("db", {}).get("sha256", "")
    if args.jobs > 1:
        rows = run_parallel(cases, db_path, args.jobs)
    else:
        last = None
        for attempt in range(5):
            try:
                idx = search_mod.SearchIndex(db_path)
                break
            except sqlite3.OperationalError as exc:
                last = exc
                time.sleep(1.5 * (attempt + 1))
        else:
            raise last
        sub_inn = load_sub_inn(db_path)
        rows = [evaluate_case(idx, case, sub_inn) for case in cases]
        idx.close()
    summary = summarize(rows)
    elapsed = time.time() - t_start
    result = dict(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        cases_file=str(cases_path), cases_meta=meta,
        db_sha256_cases=db_sha, elapsed_seconds=round(elapsed, 1),
        summary=summary, rows=rows,
    )
    out_path = Path(args.json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"cases: {len(rows)}  类别: {dict(Counter(r['category'] for r in rows))}")
    print(f"DB sha256（用例绑定）: {db_sha[:16]}…  用时 {elapsed:.1f}s")
    if db_sha and meta.get("db", {}).get("sha256"):
        # 只提示，不阻断（基线可跑在更新后的库上，但需在报告注明漂移）
        print("注：用例期望绑定生成时的 DB 快照；当前库如有变更应在报告记录 data drift。")
    print_summary(summary, rows, args.quiet)
    print(f"\n明细: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
