"""CI 与本地发布共用的检查入口（只读：不发布、不写库、不访问网络）。

用法：
    python deploy/ci_checks.py                       # 全量（分层 + 并行，约 3–4 分钟）
    python deploy/ci_checks.py --fast                # 静态与快检查（约 15–25 秒）
    python deploy/ci_checks.py --dist .tmp/dist-v0102  # 验「待发布产物」（默认验 site/dist）
    python deploy/ci_checks.py --jobs 8 --verbose    # trilingual 并行线程数 / 明细

分层（v0.10.3 提速：**一条检查都不删、判定不放松**，只做「分层 + 缓存 + 并行」）：

    fast（≤25 s）   i18n · py_compile(缓存) · unittest:etl/lib/mobile ·
                    dist-integrity(抽样) · workflow
    全量（≤4 min）  fast 的全部（dist 全扫 0 字节）+ unittest:lib-atc-category（重，47 s）·
                    trilingual（8 线程）· check_data · ui-surface ∥ first-screen（并行）

    被挪出 fast 的项仍然出现在输出里（记 SKIP），只是不在 fast 真跑；判定逻辑完全不变。

检查项：i18n 四语一致性（纯静态，fast 也跑）→ py_compile → unittest →
trilingual → check_data → dist 完整性 → 同色守卫 / 首屏守卫 → CI 配置自检。

GitHub Actions（.github/workflows/ci.yml）与本机发布前跑的是同一个脚本，
所以「CI 与本地门槛一致」；唯一差异是 CI 里没有 data/drugs.db，
依赖库的检查（trilingual / db/check_data.py）会 SKIP，需在本地发布前跑。

退出码：0 = 全部通过（含 SKIP）；1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
DB = ROOT / "data" / "drugs.db"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# 产物目录：默认 site/dist，`--dist PATH` 可指向待发布产物（.tmp/dist-vXXXX）。
# 所有用到产物的检查都走 DIST_PATH，不再各自写死 site/dist。
DIST_PATH: Path = ROOT / "site" / "dist"

# trilingual 已知缺口（词表覆盖类，2026-10-30 基线）：允许失败，其余任何失败一律红。
# 每个元组 =（案例名, 类别），与 run_tests.py 的 [FAIL] 行一致；清零后请从本表移除。
ALLOWED_TRILINGUAL_FAILURES = {
    ("metformin", "combo"),
    ("ciclosporin", "dup_inn"),
    ("beclometasone", "dup_inn"),
    ("chlorphenamine", "dup_inn"),
}
TRILINGUAL_MIN_CASES = 72
TRILINGUAL_MIN_PASS = 68

SITEMAP_MIN_URLS = 25_000
CORE_MIN_BYTES = 10_000_000
DIST_MIN_FILES = 24_000
REQUIRED_DIST_FILES = [
    "index.html",
    "404.html",
    "robots.txt",
    "sitemap.xml",
    ".nojekyll",
    "assets/app.js",
    "data/idx/core.json",
]
COMPILE_DIRS = ["etl", "lib", "site", "db", "mobile", "deploy", "tests"]
COMPILE_SKIP_DIRS = {"__pycache__", ".tmp", "tools", "site/dist", ".pylibs"}

# py_compile 缓存：按（路径, mtime_ns, size）判是否需要重新编译（语法检查结果与 pyc 无关）
PYC_CACHE_DIR = ROOT / ".tmp" / "pyc-cache"
PYC_JSON = ROOT / ".tmp" / "pycache-ci"

# 每项耗时（打印耗时表用；并行时也各记各的）
TIMINGS: list[dict] = []

# 汇总打印顺序（并行跑的三项按这个顺序排版，不受完成先后影响）
SUMMARY_ORDER = [
    "i18n", "py_compile", "unittest:etl", "unittest:lib", "unittest:mobile",
    "unittest:lib-atc-category", "trilingual", "check_data", "dist-integrity",
    "ui-surface", "first-screen", "workflow",
]

results: list[tuple[str, str, str]] = []  # (状态, 名称, 明细)


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))


def timed(name: str) -> Callable:
    """给检查函数记耗时（并行安全：TIMINGS.append 是原子操作）。"""
    def deco(fn: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            t0 = time.time()
            try:
                return fn(*args, **kwargs)
            finally:
                TIMINGS.append({"name": name, "seconds": round(time.time() - t0, 1),
                                "thread": threading.current_thread().name})
        return wrapper
    return deco


def _run(cmd: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        cmd, cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def _tail(text: str, n: int = 3) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return " | ".join(lines[-n:])


def _rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


# ── 0. 四语 i18n 一致性（纯静态、毫秒级，fast 与全量都跑）────────────────
# 用户规则（2026-11-10）：多语言翻译必须同步更新、写进底层逻辑，四语键集一致、
# 缺译不许静默回落英文。守卫是 deploy/i18n_check.py，这里是 CI 接线。
I18N_JSON = ROOT / ".tmp" / "ci" / "i18n_check.json"


@timed("i18n")
def check_i18n(verbose: bool) -> None:
    proc = _run([PY, "deploy/i18n_check.py", "--json", str(I18N_JSON)], timeout=300)
    out = (proc.stdout or "") + (proc.stderr or "")
    payload: dict = {}
    try:
        payload = json.loads(I18N_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if proc.returncode == 0 and payload.get("ok"):
        counts = payload.get("counts") or {}
        rel = (payload.get("stats") or {}).get("release") or {}
        record("PASS", "i18n", f"四语键集一致；WARN {counts.get('warn', 0)}；"
                               f"最新版 {rel.get('latest', '?')} 译文{'齐' if rel.get('latest_ok') else '缺'}")
    else:
        fails = payload.get("fail") or []
        detail = "; ".join(f"{r.get('rule')}: {r.get('detail')}" for r in fails[:4]) \
            or _tail(out, 4)
        record("FAIL", "i18n", f"exit {proc.returncode}，FAIL {len(fails)} 项：{detail}")
    if verbose:
        print("  i18n: done")


# ── 1. 静态检查：py_compile（按 mtime+size 缓存，只编变更文件）───────────
def _py_files() -> list[Path]:
    files: list[Path] = []
    for name in COMPILE_DIRS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if any(skip in rel.split("/")[:2] or rel.startswith(skip + "/")
                   for skip in COMPILE_SKIP_DIRS):
                continue
            files.append(path)
    for path in ROOT.glob("*.py"):
        files.append(path)
    return files


def _load_pyc_cache() -> dict:
    try:
        data = json.loads((PYC_CACHE_DIR / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("python") != f"{sys.version_info.major}.{sys.version_info.minor}":
        return {}   # 解释器变了，缓存作废
    return data.get("files") or {}


def _save_pyc_cache(files: dict) -> None:
    PYC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"python": f"{sys.version_info.major}.{sys.version_info.minor}",
               "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": files}
    (PYC_CACHE_DIR / "state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


@timed("py_compile")
def check_py_compile(verbose: bool) -> None:
    files = _py_files()
    cache = _load_pyc_cache()
    errors: list[str] = []
    todo: list[tuple[Path, str, str]] = []
    seen: dict[str, dict] = {}
    for path in files:
        rel = _rel(path)
        try:
            st = path.stat()
            sig = f"{st.st_mtime_ns}:{st.st_size}"
        except OSError:
            continue
        hit = cache.get(rel) or {}
        cached_ok = hit.get("sig") == sig and hit.get("ok") is True
        seen[rel] = {"sig": sig, "ok": bool(cached_ok)}
        if not cached_ok:
            todo.append((path, rel, sig))
    PYC_JSON.mkdir(parents=True, exist_ok=True)
    for path, rel, sig in todo:
        try:
            py_compile.compile(str(path), doraise=True,
                               cfile=str(PYC_JSON / (path.stem + ".pyc")))
            seen[rel]["ok"] = True
        except py_compile.PyCompileError as exc:  # noqa: PERF203
            seen[rel]["ok"] = False
            errors.append(f"{rel}: {exc.msg.strip().splitlines()[-1]}")
    _save_pyc_cache(seen)
    reused = len(files) - len(todo)
    if errors:
        record("FAIL", "py_compile",
               f"{len(errors)} 个文件编译失败（本次编译 {len(todo)} 个，缓存复用 {reused} 个）: "
               + "; ".join(errors[:5]))
    else:
        record("PASS", "py_compile",
               f"{len(files)} 个 Python 文件编译通过（本次编译 {len(todo)} 个，缓存复用 {reused} 个）")
    if verbose:
        print(f"  py_compile: {len(files)} files, compiled {len(todo)}, cached {reused}, "
              f"errors {len(errors)}")


# ── 2. 单元测试（etl / lib / mobile；atc-category 只在全量跑）──────────────
def _run_unittest(name: str, args: list[str]) -> None:
    started = time.time()
    proc = _run([PY, "-m", "unittest", *args])
    out = (proc.stdout or "") + (proc.stderr or "")
    summary = _tail(out, 2)
    if proc.returncode == 0:
        record("PASS", name, f"{summary}（{time.time() - started:.1f}s）")
    else:
        record("FAIL", name, f"exit {proc.returncode}: {_tail(out, 6)}")


@timed("unittest")
def check_unittests(fast: bool) -> None:
    _run_unittest("unittest:etl", ["discover", "-s", "etl", "-t", "etl"])
    _run_unittest("unittest:lib", ["discover", "-s", "lib", "-t", "lib"])
    _run_unittest("unittest:mobile", ["tests.test_mobile_inbox"])
    # v0.10.3：#3 之前 tests/ 下这条用例只存在、没进 CI，lib 快照漂了 9/16 个大类也没人发现
    # （审计报告 §3.3 / §3.5 风险 C）。`-s lib` 的 discover 只收 lib/ 目录内的文件，收不到它。
    # 无 data/drugs.db / site/dist 时用例自己 skip，CI 不会因此变红。
    # 2026-11-10 提速：这条要 47 s（占 fast 的 65%），挪到全量模式；判定逻辑没动。
    if fast:
        record("SKIP", "unittest:lib-atc-category", "--fast 跳过（47 s，全量才跑）")
    else:
        _run_unittest("unittest:lib-atc-category", ["tests.test_lib_atc_category"])


# ── 3. trilingual（需要 data/drugs.db；CI 无库则 SKIP；8 线程并行）────────
@timed("trilingual")
def check_trilingual(verbose: bool, jobs: int = 8) -> None:
    if not DB.exists():
        record("SKIP", "trilingual", "缺 data/drugs.db（CI 无库；发布前请在本地跑）")
        return
    started = time.time()
    cmd = [PY, "tests/trilingual/run_tests.py"]
    if jobs and jobs > 1:
        cmd += ["--jobs", str(jobs)]
    proc = _run(cmd, timeout=1800)
    out = (proc.stdout or "") + (proc.stderr or "")
    fails = [(m.group(1), m.group(2)) for m in re.finditer(r"^\[FAIL\]\s+(\S+)\s+(\S+)", out, re.M)]
    cases_m = re.search(r"案例\s*(\d+)（通过\s*(\d+)）", out)
    cross_m = re.search(r"跨国可见\s*(\d+)/(\d+)", out)
    if not cases_m:
        record("FAIL", "trilingual", f"未解析到汇总行（exit {proc.returncode}）：{_tail(out, 4)}")
        return
    cases, passed = int(cases_m.group(1)), int(cases_m.group(2))
    cross = f"{cross_m.group(1)}/{cross_m.group(2)}" if cross_m else "?"
    unknown = [f for f in fails if f not in ALLOWED_TRILINGUAL_FAILURES]
    detail = (f"{cases} 例通过 {passed}，跨国 {cross}，已知缺口 {len(fails)}："
              + ", ".join(f"{a}/{b}" for a, b in fails))
    if unknown:
        record("FAIL", "trilingual", f"出现未登记的失败 {unknown}；" + detail)
    elif cases < TRILINGUAL_MIN_CASES or passed < TRILINGUAL_MIN_PASS:
        record("FAIL", "trilingual", f"低于基线（≥{TRILINGUAL_MIN_CASES} 例/≥{TRILINGUAL_MIN_PASS} 通过）；" + detail)
    else:
        record("PASS", "trilingual",
               f"{detail}（{time.time() - started:.1f}s；jobs={max(1, jobs)}；allowlist 见脚本常量）")
    if verbose:
        print("  trilingual:", detail)


# ── 4. 数据体检（需要 data/drugs.db）────────────────────────────────────
@timed("check_data")
def check_database() -> None:
    if not DB.exists():
        record("SKIP", "check_data", "缺 data/drugs.db（CI 无库；发布前请在本地跑）")
        return
    proc = _run([PY, "db/check_data.py"], timeout=600)
    if proc.returncode == 0:
        record("PASS", "check_data", _tail(proc.stdout, 1) or "exit 0")
    else:
        record("FAIL", "check_data", f"exit {proc.returncode}: {_tail(proc.stdout + proc.stderr, 4)}")


# ── 5. 站点产物完整性（分层：fast 抽样 / 全量全扫）──────────────────────
def _scan_dist(root: Path, *, full_zero: bool, sample: int = 500) -> dict:
    """流式遍历产物（不建全量 Path 列表）：返回文件数 / 0 字节数 / 抽样数。

    fast: 只对前 sample 个文件做 size 检查（0 字节抽样）；文件总数仍然全量走一遍
    （os.scandir 只 stat 目录项，约 1 s，比 rglob+is_file 快得多）。
    全量: 每个文件都查 size。
    """
    count = 0
    zero = 0
    checked = 0
    zero_sample: list[str] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(Path(e.path))
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    count += 1
                    if full_zero or checked < sample:
                        checked += 1
                        if e.stat(follow_symlinks=False).st_size == 0:
                            zero += 1
                            if len(zero_sample) < 5:
                                zero_sample.append(_rel(Path(e.path)))
                except OSError:
                    continue
    return {"files": count, "zero": zero, "checked": checked,
            "zero_sample": zero_sample, "full_zero": full_zero}


@timed("dist-integrity")
def check_dist(verbose: bool, fast: bool) -> None:
    dist = DIST_PATH
    tier = "fast-抽样" if fast else "全量"
    if not dist.is_dir():
        record("SKIP", "dist-integrity",
               f"无 {_rel(dist)}（生成物不入库；CI 跳过，发布前本地必跑）")
        return
    problems: list[str] = []
    for rel in REQUIRED_DIST_FILES:
        path = dist / rel
        if not path.exists():
            problems.append(f"缺 {rel}")
        elif path.is_file() and path.stat().st_size == 0:
            problems.append(f"{rel} 为 0 字节")
    core = dist / "data" / "idx" / "core.json"
    if core.exists() and core.stat().st_size < CORE_MIN_BYTES:
        problems.append(f"core.json 仅 {core.stat().st_size:,} B（< {CORE_MIN_BYTES:,}）")
    locs = 0
    sitemap = dist / "sitemap.xml"
    if sitemap.exists():
        locs = len(re.findall(r"<loc>", sitemap.read_text(encoding="utf-8", errors="replace")))
        if locs < SITEMAP_MIN_URLS:
            problems.append(f"sitemap 仅 {locs} URL（< {SITEMAP_MIN_URLS:,}）")
    scan = _scan_dist(dist, full_zero=not fast)
    if scan["files"] < DIST_MIN_FILES:
        problems.append(f"仅 {scan['files']:,} 文件（< {DIST_MIN_FILES:,}）")
    if scan["zero"]:
        problems.append(f"{scan['zero']} 个 0 字节文件（如 {scan['zero_sample'][:3]}）")
    node = shutil.which("node")
    if node and (dist / "assets" / "app.js").is_file():
        proc = _run([node, "--check", str(dist / "assets" / "app.js")], timeout=120)
        if proc.returncode != 0:
            problems.append("node --check assets/app.js 失败: " + _tail(proc.stderr, 2))
    detail_scan = (f"{scan['files']:,} 文件 / 0 字节 {scan['zero']}（{tier}：抽查 {scan['checked']:,} 个）"
                   f" / sitemap {locs:,} URL / node {'已检查' if node else '未安装跳过'}")
    # 两种口径都落 JSON，便于 fast 与全量对比
    try:
        (ROOT / ".tmp" / "ci").mkdir(parents=True, exist_ok=True)
        (ROOT / ".tmp" / "ci" / f"dist-integrity-{'fast' if fast else 'full'}.json").write_text(
            json.dumps({"dist": _rel(dist), **scan, "sitemap": locs, "problems": problems},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    if problems:
        record("FAIL", "dist-integrity", "; ".join(problems[:6]))
    else:
        record("PASS", "dist-integrity", detail_scan)
    if verbose:
        print("  dist:", detail_scan)


# ── 6. 同色守卫（真浏览器；需要 Chrome + 产物，缺一个就 SKIP）──────────────
UI_SURFACE_JSON = ROOT / ".tmp" / "ui-surface" / "ci.json"


@timed("ui-surface")
def check_ui_surface(verbose: bool) -> None:
    """嵌套表面填充色 == 容器填充色 即 FAIL（用户 2026-11-10 硬规则）。

    全量模式才跑：要拉起无头 Chrome 扫 6 页 × 2 视口，约 20 秒。
    """
    script = ROOT / "deploy" / "ui_surface_check.py"
    if not script.exists():
        record("SKIP", "ui-surface", "缺 deploy/ui_surface_check.py")
        return
    if not DIST_PATH.is_dir():
        record("SKIP", "ui-surface", f"无 {_rel(DIST_PATH)}（发布前本地必跑）")
        return
    proc = _run([PY, str(script), "--dist", str(DIST_PATH), "--json", str(UI_SURFACE_JSON)],
                timeout=900)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0 and "[SKIP]" in out:
        reason = next((ln.strip() for ln in out.splitlines() if "[SKIP]" in ln), "SKIP")
        record("SKIP", "ui-surface", reason.replace("[SKIP]", "").strip())
        return
    m = re.search(r"同色 (\d+) 处", out)
    if m is None:
        record("FAIL", "ui-surface", f"未解析到汇总行（exit {proc.returncode}）：{_tail(out, 4)}")
        return
    bad = int(m.group(1))
    detail = (f"{out.count('[FAIL]')} 组同色 / {m.group(0)}"
              f"（明细 {_rel(UI_SURFACE_JSON)}）")
    if bad:
        fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("[FAIL]")]
        record("FAIL", "ui-surface", "; ".join(fails[:3]) + f" …共 {bad} 处")
    else:
        record("PASS", "ui-surface", detail)
    if verbose:
        print("  ui-surface:", detail)


# ── 6b. 首屏守卫（真浏览器；报告模式：出数字，不阻塞发布）─────────────────
# 规则来源：用户 2026-11-10「之后你要改成按照人能看到什么来设计」。
# v0.10.2 只出基线数字（见 docs/设计原则-按人能看到的来.md 的「分阶段收紧」）：
# 指标未达标**不**算 FAIL，避免把全站存量缺口变成发布阻断；脚本本身崩溃才算 FAIL。
# v0.10.3 起把最差 3 处修掉后，这里改成加 `--gate` 真阻塞。
FIRST_SCREEN_JSON = ROOT / ".tmp" / "first-screen" / "ci.json"


@timed("first-screen")
def check_first_screen(verbose: bool) -> None:
    script = ROOT / "deploy" / "first_screen_check.py"
    if not script.exists():
        record("SKIP", "first-screen", "缺 deploy/first_screen_check.py")
        return
    if not DIST_PATH.is_dir():
        record("SKIP", "first-screen", f"无 {_rel(DIST_PATH)}（发布前本地必跑）")
        return
    proc = _run([PY, str(script), "--dist", str(DIST_PATH), "--json", str(FIRST_SCREEN_JSON)],
                timeout=1800)
    out = (proc.stdout or "") + (proc.stderr or "")
    if "[SKIP]" in out:
        reason = next((ln.strip() for ln in out.splitlines() if "[SKIP]" in ln), "SKIP")
        record("SKIP", "first-screen", reason.replace("[SKIP]", "").strip())
        return
    if "[report]" not in out:
        record("FAIL", "first-screen", f"脚本异常（exit {proc.returncode}）：{_tail(out, 4)}")
        return
    m = re.search(r"(\d+) 次扫描：(\d+) 组不达标、共 (\d+) 项未达", out)
    if not m:
        record("FAIL", "first-screen", f"未解析到汇总行（exit {proc.returncode}）：{_tail(out, 4)}")
        return
    scans, fail_scans, fail_items = (int(m.group(i)) for i in (1, 2, 3))
    worst = "?"
    try:
        payload = json.loads(FIRST_SCREEN_JSON.read_text(encoding="utf-8"))
        rows = sorted(payload.get("pages") or [],
                      key=lambda r: (-len(r.get("fails") or []),
                                     (r.get("metrics") or {}).get("items", 0)))
        if rows and rows[0].get("fails"):
            w = rows[0]
            worst = f"{w['page']}@{w['viewport']}（{len(w['fails'])} 项：{w['fails'][0]['metric']}）"
    except (OSError, ValueError):
        pass
    detail = (f"报告模式（不阻塞）：{scans} 次扫描，{fail_scans} 组未达标、{fail_items} 项；"
              f"最差 {worst}（明细 {_rel(FIRST_SCREEN_JSON)}）")
    record("PASS", "first-screen", detail)
    if verbose:
        print("  first-screen:", detail)


# ── 7. CI 配置自检（防止 workflow 被误删/改名）──────────────────────────
@timed("workflow")
def check_workflow() -> None:
    if not WORKFLOW.exists():
        record("FAIL", "workflow", "缺 .github/workflows/ci.yml")
        return
    text = WORKFLOW.read_text(encoding="utf-8")
    missing = [k for k in ("python-version", "ci_checks.py", "pull_request") if k not in text]
    if missing:
        record("FAIL", "workflow", f"ci.yml 缺少关键内容: {missing}")
    else:
        record("PASS", "workflow", "ci.yml 存在且引用同一入口 deploy/ci_checks.py")


# ── 8. 并行组：互不依赖的检查同时跑 ──────────────────────────────────────
def _run_parallel(tasks: list[tuple[str, Callable[[], None]]]) -> None:
    """i18n / ui-surface / first-screen 互不依赖，线程并行；各自 record 自己那一行。

    每一组都独立进程 + 独立 Chrome 实例/端口，不共享状态。record 只做 list.append，
    并行安全；汇总时按 SUMMARY_ORDER 排版。
    """
    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="ci") as ex:
        futures = [(name, ex.submit(fn)) for name, fn in tasks]
        for name, fut in futures:
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001 —— 单组崩了要红，但不能带走整轮
                record("FAIL", name, f"并行执行异常：{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    global DIST_PATH
    ap = argparse.ArgumentParser(description="CI / 本地发布共用的检查入口（只读）")
    ap.add_argument("--fast", action="store_true",
                    help="只跑静态与快检查（≤25 s）；重检查记 SKIP，全量才跑")
    ap.add_argument("--dist", default=None,
                    help="产物目录（默认 site/dist；发布前请指向待发布产物，如 .tmp/dist-v0102）")
    ap.add_argument("--jobs", type=int, default=8,
                    help="trilingual 并行线程数（默认 8；--jobs 1 = 串行，用于逐条对照）")
    ap.add_argument("--verbose", action="store_true", help="打印每项明细")
    args = ap.parse_args(argv)

    if args.dist:
        DIST_PATH = Path(args.dist)
        if not DIST_PATH.is_absolute():
            DIST_PATH = (ROOT / DIST_PATH)
        DIST_PATH = DIST_PATH.resolve()
    mode = "fast" if args.fast else "full"

    started = time.time()
    print(f"== CI checks ==  repo={ROOT}")
    print(f"   mode={mode}  dist={_rel(DIST_PATH)}  jobs={args.jobs}  "
          f"python={sys.version.split()[0]}")

    team: list[tuple[str, Callable[[], None]]] = [
        ("i18n", lambda: check_i18n(args.verbose)),
        ("ui-surface", lambda: check_ui_surface(args.verbose)),
        ("first-screen", lambda: check_first_screen(args.verbose)),
    ]
    if args.fast:
        check_i18n(args.verbose)
        check_py_compile(args.verbose)
        check_unittests(fast=True)
        record("SKIP", "trilingual", "--fast 跳过（全量才跑）")
        record("SKIP", "check_data", "--fast 跳过")
        check_dist(args.verbose, fast=True)
        record("SKIP", "ui-surface", "--fast 跳过（要拉无头 Chrome，全量才跑）")
        record("SKIP", "first-screen", "--fast 跳过（要拉无头 Chrome，全量才跑）")
        check_workflow()
    else:
        # 全量：先跑串行的（单测 → trilingual → check_data → dist），
        # 最后把互不依赖的 ui-surface / first-screen 并行跑（i18n 也顺手丢进去，几毫秒）
        check_py_compile(args.verbose)
        check_unittests(fast=False)
        check_trilingual(args.verbose, jobs=max(1, args.jobs))
        check_database()
        check_dist(args.verbose, fast=False)
        _run_parallel([("i18n", lambda: check_i18n(args.verbose)),
                       ("ui-surface", lambda: check_ui_surface(args.verbose)),
                       ("first-screen", lambda: check_first_screen(args.verbose))])
        check_workflow()

    # 汇总：按固定顺序排版（并行项完成顺序不定），时间表按耗时降序
    order = {name: i for i, name in enumerate(SUMMARY_ORDER)}
    for status, name, detail in sorted(results, key=lambda r: order.get(r[1], 99)):
        print(f"[{status:4}] {name:18} {detail}")
    failed = [r for r in results if r[0] == "FAIL"]
    total_s = time.time() - started
    print("\n== 耗时（降序）==")
    for t in sorted(TIMINGS, key=lambda x: -x["seconds"]):
        print(f"  {t['seconds']:>6.1f}s  {t['name']}")
    print(f"\n{len(results)} 项：PASS {sum(1 for r in results if r[0] == 'PASS')} / "
          f"FAIL {len(failed)} / SKIP {sum(1 for r in results if r[0] == 'SKIP')}"
          f"（总 {total_s:.1f}s · mode={mode} · dist={_rel(DIST_PATH)}）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
