#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""core 索引字段守卫：`core.json` 必须携带 `t` / `nc` / `eo`，且体积落在护栏内。

背景（P0-1，2026-11-12）
------------------------
`site/build.py` 的 `encode_core()` 用**手写元组**挑列，v0.9.0 / v0.9.1 新增的
`t`（是否 trade 名）、`nc`（名称层/无成分）、`eo`（Export Only）从未被加进去。
分片走 `encode_shards()` 原样序列化（字段齐全），core 缺列 → 客户端 `decodeCore()`
之后 `e.t === undefined`，`brandHTML()` 的 `e.t !== 1` 判定让**每一行**都渲染成
「无商品名 + 命中名」，196,200 行里 166,846 行（85.0%）的品牌名被吞掉。

这类「写入侧加字段、读取侧忘同步」已经踩过两次（v0.6.1 补过 `f`），
本脚本把两件事固化成闸门：**必需列在不在** + **分片字段集是否被 core 全覆盖**。

用法
----
    # 1) 默认查 site/dist
    python deploy/check_core_fields.py

    # 2) 查某个构建暂存目录（发布前预检）
    python deploy/check_core_fields.py --dist .tmp/v0112-build

    # 3) 直接指定 core.json（此时 manifest / 分片按同目录推断）
    python deploy/check_core_fields.py --core .tmp/v0112-build/data/idx/core.json

    # 4) 落 JSON 摘要（报告 / CI artifact）
    python deploy/check_core_fields.py --dist site/dist --json .tmp/core-fields.json

    # 5) 跳过重活（大索引慢机器上先看字段）
    python deploy/check_core_fields.py --no-gzip --no-shards

退出码：0 = PASS；1 = FAIL（逐条打印实测值 vs 期望值）。
只读：只读 `core.json` / `manifest.json` / `shard-*.json`，不写任何产物。
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIST = ROOT / "site" / "dist"
CORE_REL = Path("data") / "idx" / "core.json"

# P0-1 必需列：缺任意一个都会让客户端静默错位（不是渲染报错，更难发现）。
REQUIRED_COLS = ("t", "nc", "eo")

# 体积护栏：与发布门槛（主域 R2 的 verify_live.py，备份 gh-pages 的 publish.ps1）
# 同一口径（gzip -9，2.5–12 MB）。v0.11.1 实测 9.773 MB；v0.11.2 补三列后
# 9.801 MB；留足余量给新市场入库。
GZIP_MIN_BYTES = 2_500_000
GZIP_MAX_BYTES = 12_000_000

# `t == 1` 的比例：v0.11.2 实测 166,846 / 196,200 = 85.0%。
# 用**比例**而不是绝对值：新市场入库后行数会涨，绝对值会误报，比例仍稳。
T1_RATIO = 0.85
T1_REL_TOL = 0.05          # 相对容差 ±5%（即 80.75%–89.25%）

SAMPLE_N = 200             # 抽样条数（决定 --seed 后结果可复现）
SAMPLE_T1_MIN = 0.70       # 抽样里 t==1 的粗护栏，比全量宽松，只防「整列错位」
SAMPLE_T1_MAX = 0.95

# core 独有 / 稀疏存储的列，不参与「分片字段 ⊆ core 字段」比较：
#   dp = d 的大小写补丁列（core 独有）；q = core 里是稀疏下标数组，分片里只写在被标记的行上。
CORE_ONLY_COLS = {"dp"}
SPARSE_COLS = {"q"}


class Check:
    """一条断言的执行结果（ok + 可读说明 + 机器可读数值）。"""

    __slots__ = ("name", "ok", "detail", "values", "ms")

    def __init__(self, name: str, ok: bool, detail: str, values: dict[str, Any] | None = None,
                 ms: float = 0.0) -> None:
        self.name = name
        self.ok = ok
        self.detail = detail
        self.values = values or {}
        self.ms = ms

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail,
                "values": self.values, "ms": round(self.ms, 1)}


def timed(fn, *args) -> Check:
    """跑一条检查并计时（异常也算 FAIL，不把脚本炸成 traceback）。"""
    t0 = time.perf_counter()
    try:
        chk = fn(*args)
    except Exception as exc:                       # noqa: BLE001 - 守卫脚本要给出结论，不能崩
        chk = Check(getattr(fn, "__name__", "check"), False, f"检查本身出错：{exc!r}")
    chk.ms = (time.perf_counter() - t0) * 1000
    return chk


# ── 列取值的通用读法：普通列是 list，字典列是 {"d": 字典, "i": 下标} ──────────
def col_values(cols: dict[str, Any], field: str) -> list[Any] | None:
    """把某一列还原成「每行一个值」的数组；列不存在返回 None。

    与客户端 decodeCore() 同一套规则，所以不管编码侧把 t 写成普通列还是字典列，
    守卫都能读（避免守卫自己成为下一个「两套映射」）。
    """
    col = cols.get(field)
    if isinstance(col, list):
        return col
    if isinstance(col, dict) and isinstance(col.get("d"), list) and isinstance(col.get("i"), list):
        table, idx = col["d"], col["i"]
        try:
            return [table[i] for i in idx]
        except (IndexError, TypeError):
            return None
    return None


# ── 各条检查 ──────────────────────────────────────────────────────────
def check_shape(core: dict[str, Any]) -> Check:
    """n 与各列长度必须自洽：截断的 core 会让客户端渲染错位，比缺列更隐蔽。"""
    n = core.get("n")
    cols = core.get("cols") or {}
    if not isinstance(n, int) or n <= 0:
        return Check("shape", False, f"n 非法：{n!r}", {"n": n})
    if not isinstance(cols, dict) or not cols:
        return Check("shape", False, "cols 缺失或为空", {"n": n})
    k = cols.get("k")
    if not isinstance(k, list) or len(k) != n:
        return Check("shape", False,
                     f"cols.k 长度 {len(k) if isinstance(k, list) else '缺失'} ≠ n {n}",
                     {"n": n})
    ragged = [f for f in ("t", "nc", "eo")
              if isinstance(col_values(cols, f), list) and len(col_values(cols, f)) != n]
    if ragged:
        return Check("shape", False, f"列长度 ≠ n：{ragged}", {"n": n})
    return Check("shape", True, f"n={n:,}，cols.k 长度一致（{len(cols)} 列）", {"n": n, "cols": len(cols)})


def check_required_cols(core: dict[str, Any]) -> Check:
    """P0-1 正题：t / nc / eo 三列必须在。"""
    cols = core.get("cols") or {}
    missing = [f for f in REQUIRED_COLS if not isinstance(col_values(cols, f), list)]
    present = [f for f in REQUIRED_COLS if f not in missing]
    if missing:
        return Check("required-cols", False,
                     f"core.cols 缺 {missing}（客户端 decodeCore 后为 undefined → 渲染错位）",
                     {"missing": missing, "present": present})
    return Check("required-cols", True, f"core.cols 含 {list(REQUIRED_COLS)}", {"present": present})


def check_values(core: dict[str, Any], sample_n: int, seed: int) -> Check:
    """取值域 + 分布：t/nc/eo 只能是 0/1；t==1 比例要落在 85%±5%。"""
    cols = core.get("cols") or {}
    n = core.get("n") or 0
    problems: list[str] = []
    values: dict[str, Any] = {}

    for f in REQUIRED_COLS:
        vals = col_values(cols, f)
        if vals is None:
            problems.append(f"{f}: 列缺失")
            continue
        bad = {v for v in set(vals) if v not in (0, 1)}
        if bad:
            problems.append(f"{f}: 非法取值 {sorted(bad)[:5]}")
        values[f"ones_{f}"] = sum(1 for v in vals if v == 1)

    tvals = col_values(cols, "t")
    if tvals is None:
        return Check("values", False, "；".join(problems), values)

    # 全量分布
    t1 = values["ones_t"]
    ratio = (t1 / n) if n else 0.0
    lo, hi = T1_RATIO * (1 - T1_REL_TOL), T1_RATIO * (1 + T1_REL_TOL)
    values.update({"n": n, "t1": t1, "t1_ratio": round(ratio, 4),
                   "t1_band": [round(lo * n), round(hi * n)]})
    if not (lo <= ratio <= hi):
        problems.append(f"t==1 比例 {ratio:.1%}（{t1:,}/{n:,}）超出 {lo:.1%}–{hi:.1%}"
                        f"（期望 {T1_RATIO:.0%}±{T1_REL_TOL:.0%}）")

    # 随机抽样：任何一行 t 为 None 都是 P0-1 复发的直接指纹
    rnd = random.Random(seed)
    picks = rnd.sample(range(n), min(sample_n, n))
    sample = [tvals[i] for i in picks]
    none_cnt = sum(1 for v in sample if v is None)
    s_ratio = (sum(1 for v in sample if v == 1) / len(sample)) if sample else 0.0
    values.update({"sample_n": len(sample), "sample_t_none": none_cnt,
                   "sample_t1_ratio": round(s_ratio, 4), "seed": seed})
    if none_cnt:
        problems.append(f"抽样 {len(sample)} 条里有 {none_cnt} 条 t 为空")
    if not (SAMPLE_T1_MIN <= s_ratio <= SAMPLE_T1_MAX):
        problems.append(f"抽样 t==1 比例 {s_ratio:.1%} 超出 "
                        f"{SAMPLE_T1_MIN:.0%}–{SAMPLE_T1_MAX:.0%}（可能整列错位）")

    if problems:
        return Check("values", False, "；".join(problems), values)
    return Check("values", True,
                 f"t==1 {t1:,}/{n:,} = {ratio:.1%}（区间 {lo:.1%}–{hi:.1%}）；"
                 f"抽样 {len(sample)} 条无空值、t==1 {s_ratio:.1%}",
                 values)


def check_gzip(raw: bytes) -> Check:
    """gzip -9 体积护栏：与 publish.ps1 / verify_live.py 同口径，防索引悄悄膨胀。"""
    gz = len(gzip.compress(raw, 9))
    values = {"raw_bytes": len(raw), "gzip_bytes": gz,
              "raw_mb": round(len(raw) / 1e6, 2), "gzip_mb": round(gz / 1e6, 3),
              "gzip_band_bytes": [GZIP_MIN_BYTES, GZIP_MAX_BYTES]}
    if not (GZIP_MIN_BYTES <= gz <= GZIP_MAX_BYTES):
        return Check("gzip-size", False,
                     f"gzip -9 {gz / 1e6:.3f} MB 超出护栏 "
                     f"{GZIP_MIN_BYTES / 1e6:.1f}–{GZIP_MAX_BYTES / 1e6:.1f} MB",
                     values)
    return Check("gzip-size", True,
                 f"gzip -9 {gz / 1e6:.3f} MB（raw {len(raw) / 1e6:.2f} MB），"
                 f"护栏 {GZIP_MIN_BYTES / 1e6:.1f}–{GZIP_MAX_BYTES / 1e6:.1f} MB", values)


def check_shard_coverage(core: dict[str, Any], idx_dir: Path) -> Check:
    """根因级守卫：分片条目出现过的字段，core 必须都有。

    这条不针对 t/nc/eo，而是覆盖**下一次**有人往 load_index() 加字段却忘了加白名单：
    分片永远原样序列化，所以「分片有、core 没有」就是缺列的直接证据。
    没有 manifest / 分片时 SKIP（返回 ok=True 并在 detail 里说明）。
    """
    manifest_path = idx_dir / "manifest.json"
    if not manifest_path.is_file():
        return Check("shard-coverage", True, "SKIP：无 manifest.json（只查 core 本身）",
                     {"skipped": True})
    manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    buckets = manifest.get("buckets") or {}
    files = [f for bucket in buckets.values() for f in bucket]
    if not files:
        return Check("shard-coverage", True, "SKIP：manifest 里没有分片", {"skipped": True})

    core_cols = set((core.get("cols") or {})) - CORE_ONLY_COLS
    shard_fields: set[str] = set()
    rows = 0
    for item in files:
        path = idx_dir / Path(str(item.get("f", ""))).name
        arr = json.loads(path.read_bytes().decode("utf-8"))
        rows += len(arr)
        for entry in arr:
            shard_fields.update(entry)

    missing = sorted(shard_fields - core_cols - SPARSE_COLS)
    values = {"shards": len(files), "shard_rows": rows, "core_n": core.get("n"),
              "shard_fields": len(shard_fields), "missing": missing}
    if missing:
        return Check("shard-coverage", False,
                     f"分片有、core 没有的字段：{missing}（core 会缺列 → 客户端渲染错位）",
                     values)
    if rows != core.get("n"):
        return Check("shard-coverage", False,
                     f"分片行数合计 {rows:,} ≠ core.n {core.get('n'):,}（有丢行）", values)
    return Check("shard-coverage", True,
                 f"{len(files)} 个分片的 {len(shard_fields)} 个字段全被 core 覆盖；"
                 f"行数 {rows:,} 与 core.n 一致", values)


# ── 主流程 ────────────────────────────────────────────────────────────
def resolve_core(args: argparse.Namespace) -> Path:
    """core.json 路径：--core 优先，其次 --dist/data/idx/core.json。"""
    if args.core:
        return args.core
    dist = args.dist or DEFAULT_DIST
    return dist / CORE_REL


def main() -> int:
    # Windows 控制台默认 GBK：中文摘要要能原样打印，也和 deploy/ 其它脚本一致。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    ap = argparse.ArgumentParser(description="core 索引字段守卫（只读，P0-1 防回归）")
    ap.add_argument("--dist", type=Path,
                    help=f"站点产物目录（默认 {DEFAULT_DIST.relative_to(ROOT)}）")
    ap.add_argument("--core", type=Path, help="直接指定 core.json（覆盖 --dist）")
    ap.add_argument("--json", type=Path, help="把摘要写成 JSON（报告 / CI artifact）")
    ap.add_argument("--sample", type=int, default=SAMPLE_N, help=f"抽样条数（默认 {SAMPLE_N}）")
    ap.add_argument("--seed", type=int, default=20261112, help="抽样随机种子（默认 20261112）")
    ap.add_argument("--no-gzip", action="store_true", help="跳过 gzip -9 体积检查（慢机器）")
    ap.add_argument("--no-shards", action="store_true", help="跳过分片字段覆盖检查（读 109 个分片）")
    args = ap.parse_args()

    core_path = resolve_core(args)
    print(f"core 索引字段守卫 · {core_path}")
    if not core_path.is_file():
        print(f"! core.json 不存在：{core_path}")
        print("\n== FAIL：找不到产物 ==")
        return 1

    raw = core_path.read_bytes()
    t0 = time.perf_counter()
    try:
        core = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"! core.json 无法解析：{exc!r}")
        print("\n== FAIL：产物损坏 ==")
        return 1

    checks: list[Check] = [
        timed(check_shape, core),
        timed(check_required_cols, core),
        timed(check_values, core, args.sample, args.seed),
    ]
    if not args.no_gzip:
        checks.append(timed(check_gzip, raw))
    if not args.no_shards:
        checks.append(timed(check_shard_coverage, core, core_path.parent))

    for chk in checks:
        mark = "OK  " if chk.ok else "FAIL"
        print(f"  [{mark}] {chk.name:<15} {chk.detail}  ({chk.ms:.0f} ms)")

    failed = [c for c in checks if not c.ok]
    n = core.get("n") or 0
    t1 = next((c.values.get("t1") for c in checks if c.name == "values"), None)
    t1_txt = f"{t1:,}" if isinstance(t1, int) else "n/a（列缺失）"
    elapsed = (time.perf_counter() - t0) * 1000

    print()
    print(f"行数 {n:,} · 列 {len(core.get('cols') or {})} · "
          f"raw {len(raw) / 1e6:.2f} MB · t==1 {t1_txt} · {len(checks)} 项检查 "
          f"· {elapsed / 1000:.2f} s")
    verdict = "PASS" if not failed else "FAIL"
    print(f"== {verdict} ==" + ("" if not failed else
                                f"（{len(failed)} 项未过：{[c.name for c in failed]}）"))

    if args.json:
        manifest = core_path.parent / "manifest.json"
        version = None
        if manifest.is_file():
            try:
                version = json.loads(manifest.read_bytes().decode("utf-8")).get("v")
            except (UnicodeDecodeError, json.JSONDecodeError):
                version = None
        payload = {
            "check": "core-fields",
            "verdict": verdict,
            "core": str(core_path),
            "build_version": version,
            "n": n,
            "raw_bytes": len(raw),
            "cols": sorted(core.get("cols") or {}),
            "checks": [c.as_dict() for c in checks],
            "failed": [c.name for c in failed],
            "elapsed_ms": round(elapsed, 1),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        print(f"JSON → {args.json}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
