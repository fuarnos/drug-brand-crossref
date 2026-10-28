#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""搜索评测 CI 门槛：cases_v3.json（500+ 例）→ Top-5 ≥ 95%、零结果误命中 = 0。

- 只读打开 `data/drugs.db`（sqlite3 URI `mode=ro`），直接复用站点检索层
  `lib/search.py::SearchIndex`（与 `tests/trilingual/run_cases_v2.py` 同一层），
  期望值全部来自 `cases_v3.json`（DB 结构 / RxNorm-RxNav oracle / WHO INN 官方名 /
  繁简反表），不来自检索输出反推。
- 门槛（可用参数覆盖）：
    Top-5 ≥ 95%（分母 = must_hit 用例）
    零结果误命中 = 0（must_empty 用例里任何非空结果即失败）
    gap 用例不计入通过率（记录「意外命中」作为将来目标）
- 输出：控制台摘要 + `.tmp/search-eval3/ci_results.json`（逐条明细）
- 退出码：0 = 门槛通过；1 = 未通过（可用于本地/谷段自动跑；当前无 GitHub Actions）。

用法：
    python tests/search_eval/run_ci.py                     # 默认门槛
    python tests/search_eval/run_ci.py --quiet
    python tests/search_eval/run_ci.py --json .tmp/search-eval3/ci_xxx.json
    python tests/search_eval/run_ci.py --top5-min 0.95 --category brand_alias
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import lib.search as search_mod  # noqa: E402

DB = ROOT / "data" / "drugs.db"
# task-139：优先 cases_v4（v3 + ATC/大类 37 例）；不存在时回退 v3（保持旧环境可跑）。
_CASES_V4 = ROOT / "tests" / "trilingual" / "cases_v4.json"
_CASES_V3 = ROOT / "tests" / "trilingual" / "cases_v3.json"
CASES = _CASES_V4 if _CASES_V4.exists() else _CASES_V3
OUT_DEFAULT = ROOT / ".tmp" / "search-eval3" / "ci_results.json"

try:  # Windows 控制台 GBK：避免中文/重音字符打印报错
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_REAL_CONNECT = sqlite3.connect


def _ro_connect(database, *args, **kwargs):
    """只读打开 + 长超时（库里可能同时有入库任务在写）。"""
    s = str(database)
    kwargs.setdefault("timeout", 60)
    if "mode=ro" not in s:
        return _REAL_CONNECT("file:" + s + "?mode=ro", uri=True, *args, **kwargs)
    return _REAL_CONNECT(database, *args, **kwargs)


def load_sub_inn(db_path: Path) -> dict[str, str]:
    con = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True)
    out = {sid: (inn or sid) for sid, inn in
           con.execute("SELECT substance_id, inn_en FROM substance")}
    con.close()
    return out


def search_retry(idx, query: str, attempts: int = 5):
    last = None
    for i in range(attempts):
        try:
            return idx.search(query)
        except sqlite3.OperationalError as exc:  # 写锁
            last = exc
            time.sleep(1.5 * (i + 1))
    raise last


def evaluate_case(idx, case: dict, sub_inn: dict[str, str]) -> dict:
    t0 = time.time()
    res = search_retry(idx, case["query"])
    dt = time.time() - t0
    expected = case["expected"]
    policy = expected["policy"]
    exp_ids = expected.get("substance_ids") or []
    exp_inn = [sub_inn[s] for s in exp_ids if s in sub_inn]
    cards = res.cards
    rank = None
    if exp_inn:
        for i, card in enumerate(cards[:5]):
            subs = [s for s in card.substances if s]
            if all(e in subs for e in exp_inn):
                rank = i
                break
        if rank is None:
            for i, card in enumerate(cards[:5]):
                subs = [s for s in card.substances if s]
                if sum(1 for e in exp_inn if e in subs) >= 2:
                    rank = i + 0.5
                    break
    top1 = [s for s in (cards[0].substances if cards else []) if s]
    out = {
        "case_id": case["case_id"], "category": case["category"], "lang": case["lang"],
        "query": case["query"], "query_type": case.get("query_type", ""),
        "policy": policy, "expected": exp_inn, "n_cards": len(cards),
        "top1": top1[:5], "rank": rank, "hit_top5": rank is not None,
        "hit_top1": rank == 0, "note": res.note,
        "tier": cards[0].tier if cards else "", "seconds": round(dt, 3),
    }
    if policy == "must_empty":
        out["pass"] = len(cards) == 0
        out["false_hit"] = len(cards) > 0
    elif policy == "gap":
        out["pass"] = None
        out["would_hit"] = rank is not None
    else:
        out["pass"] = rank is not None
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
    must_hit = sum(s["must_hit"] for s in by_cat.values())
    top1 = sum(s["top1"] for s in by_cat.values())
    top5 = sum(s["top5"] for s in by_cat.values())
    zero_n = sum(s["must_empty"] for s in by_cat.values())
    zero_bad = sum(s["zero_false_hit"] for s in by_cat.values())
    gap_n = sum(s["gap"] for s in by_cat.values())
    gap_hit = sum(s["gap_hit"] for s in by_cat.values())
    gate_n = must_hit + zero_n
    gate_pass = top5 + (zero_n - zero_bad)
    return dict(
        by_category={k: dict(v) for k, v in sorted(by_cat.items())},
        must_hit_cases=must_hit, top1=top1, top5=top5,
        top1_rate=round(top1 / must_hit, 4) if must_hit else 0.0,
        top5_rate=round(top5 / must_hit, 4) if must_hit else 0.0,
        must_empty_cases=zero_n, zero_false_hits=zero_bad,
        must_empty_rate=round((zero_n - zero_bad) / zero_n, 4) if zero_n else 1.0,
        gap_cases=gap_n, gap_unexpected_hits=gap_hit,
        gate_cases=gate_n, gate_pass=gate_pass,
        gate_rate=round(gate_pass / gate_n, 4) if gate_n else 1.0,
    )


def print_summary(summary: dict, rows: list[dict], quiet: bool, top5_min: float) -> None:
    print("\n== 分类结果 ==")
    print(f"{'category':<18}{'n':>4}{'must_hit':>9}{'Top1':>7}{'Top5':>7}"
          f"{'Top5%':>8}{'empty':>7}{'误命中':>7}{'gap':>5}{'gap命中':>8}")
    for cat, s in summary["by_category"].items():
        pct = (s["top5"] / s["must_hit"] * 100) if s["must_hit"] else 0.0
        print(f"{cat:<18}{s['n']:>4}{s['must_hit']:>9}{s['top1']:>7}{s['top5']:>7}"
              f"{pct:>7.1f}%{s['must_empty']:>7}{s['zero_false_hit']:>7}"
              f"{s['gap']:>5}{s['gap_hit']:>8}")
    print(f"\nmust_hit：Top-5 {summary['top5']}/{summary['must_hit_cases']} "
          f"({summary['top5_rate']*100:.1f}%，门槛 ≥{top5_min*100:.0f}%)，"
          f"Top-1 {summary['top1']}/{summary['must_hit_cases']}"
          f"（{summary['top1_rate']*100:.1f}%）")
    print(f"must_empty：{summary['must_empty_cases'] - summary['zero_false_hits']}"
          f"/{summary['must_empty_cases']} 通过；零结果误命中 "
          f"{summary['zero_false_hits']}（门槛 = 0）")
    print(f"gap（不计入）：{summary['gap_cases']} 例，意外命中 {summary['gap_unexpected_hits']}")
    print(f"综合：{summary['gate_pass']}/{summary['gate_cases']}"
          f"（{summary['gate_rate']*100:.1f}%）")
    if not quiet:
        fails = [r for r in rows if r["policy"] == "must_hit" and not r["hit_top5"]]
        if fails:
            print(f"\n未命中（{len(fails)} 例，前 20）:")
            for r in fails[:20]:
                print(f"  [{r['category']}] {r['query']!r} 期望={r['expected']} "
                      f"cards={r['n_cards']} top1={r['top1']}")
        zero_bad = [r for r in rows if r["policy"] == "must_empty" and r.get("false_hit")]
        if zero_bad:
            print(f"\n零结果误命中（{len(zero_bad)} 例）:")
            for r in zero_bad[:20]:
                print(f"  {r['query']!r} cards={r['n_cards']} top1={r['top1']}")


_WORKER: dict = {}


def _worker_init(db_path: str) -> None:
    """spawn 子进程只建一次 SearchIndex。"""
    sqlite3.connect = _ro_connect
    _WORKER["idx"] = search_mod.SearchIndex(Path(db_path))
    _WORKER["sub_inn"] = load_sub_inn(Path(db_path))


def _work_one(case: dict) -> dict:
    return evaluate_case(_WORKER["idx"], case, _WORKER["sub_inn"])


def main() -> int:
    ap = argparse.ArgumentParser(description="搜索评测 CI 门槛（cases_v3）")
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument("--json", default=str(OUT_DEFAULT))
    ap.add_argument("--db", default=str(DB), help="评测用 DB（默认 data/drugs.db）")
    ap.add_argument("--jobs", type=int, default=0, help="并行进程数（0=自动，1=串行）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--top5-min", type=float, default=0.95, help="must_hit Top-5 门槛")
    ap.add_argument("--gate-pinyin", action="store_true",
                    help="把 pinyin/pinyin_polyphone 从 gap 改为 must_hit 参与门槛"
                         "（task-111 拼音层下沉后的可选严格模式；默认关）")
    ap.add_argument("--category", default="", help="只跑某类（调试）")
    args = ap.parse_args()

    cases_path = Path(args.cases)
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload["cases"] if isinstance(payload, dict) else payload
    if args.gate_pinyin:
        for c in cases:
            if c["category"] in ("pinyin", "pinyin_polyphone") and \
                    c["expected"]["policy"] == "gap":
                c["expected"] = dict(c["expected"], policy="must_hit", min_tier="top5")
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
    if not cases:
        print("没有用例")
        return 1
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    jobs = args.jobs
    if jobs <= 0:
        jobs = max(2, min(6, (os.cpu_count() or 2)))

    sqlite3.connect = _ro_connect  # SearchIndex 内部连接也强制只读
    t0 = time.time()
    rows: list[dict] = []
    if jobs > 1:
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=jobs, initializer=_worker_init,
                      initargs=(str(db_path),)) as pool:
            rows = list(pool.imap(_work_one, cases, chunksize=2))
        load_s = 0.0
    else:
        idx = search_mod.SearchIndex(db_path)
        sub_inn = load_sub_inn(db_path)
        load_s = time.time() - t0
        for i, case in enumerate(cases, 1):
            rows.append(evaluate_case(idx, case, sub_inn))
            if not args.quiet and i % 100 == 0:
                print(f"  ... {i}/{len(cases)}", flush=True)
        idx.close()
    elapsed = time.time() - t0

    summary = summarize(rows)
    top5_ok = summary["top5_rate"] >= args.top5_min
    zero_ok = summary["zero_false_hits"] == 0
    thresholds = {"top5_min": args.top5_min, "top5_rate": summary["top5_rate"],
                  "gate_pinyin": args.gate_pinyin,
                  "top5_ok": top5_ok, "zero_false_hits": summary["zero_false_hits"],
                  "zero_ok": zero_ok}
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases_file": str(cases_path.relative_to(ROOT)),
        "n_cases": len(cases),
        "db": {"path": "data/drugs.db", "sha256_prefix": None},
        "load_seconds": round(load_s, 1),
        "eval_seconds": round(elapsed, 1),
        "thresholds": thresholds,
        "summary": summary,
        "categories_meta": payload.get("meta", {}) if isinstance(payload, dict) else {},
        "rows": rows,
    }
    out_path = Path(args.json)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print_summary(summary, rows, args.quiet, args.top5_min)
    print(f"\n写入：{out_path.relative_to(ROOT)}；耗时 {elapsed:.1f}s（载入 {load_s:.1f}s）")
    ok = top5_ok and zero_ok
    print(("✅ CI 门槛通过" if ok else "❌ CI 门槛未通过")
          + f"（Top-5 {summary['top5_rate']*100:.1f}% / 零误命中 {summary['zero_false_hits']}）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
