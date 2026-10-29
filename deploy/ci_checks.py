"""CI 与本地发布共用的检查入口（只读：不发布、不写库、不访问网络）。

用法：
    python deploy/ci_checks.py            # 全量（含 trilingual，约 10 分钟）
    python deploy/ci_checks.py --fast     # 跳过 trilingual 与全量 0 字节扫描（改代码时用）
    python deploy/ci_checks.py --verbose  # 打印每项明细

GitHub Actions（.github/workflows/ci.yml）与本机发布前跑的是同一个脚本，
所以「CI 与本地门槛一致」；唯一差异是 CI 里没有 data/drugs.db，
依赖库的检查（trilingual / db/check_data.py）会 SKIP，需在本地发布前跑。

退出码：0 = 全部通过（含 SKIP）；1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import os
import py_compile
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
DIST = ROOT / "site" / "dist"
CORE_JSON = DIST / "data" / "idx" / "core.json"
DB = ROOT / "data" / "drugs.db"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

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

results: list[tuple[str, str, str]] = []  # (状态, 名称, 明细)


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))


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


# ── 1. 静态检查：py_compile ──────────────────────────────────────────────
def check_py_compile(verbose: bool) -> None:
    files: list[Path] = []
    for name in COMPILE_DIRS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if any(skip in rel.split("/")[:2] or rel.startswith(skip + "/") for skip in COMPILE_SKIP_DIRS):
                continue
            files.append(path)
    for path in ROOT.glob("*.py"):
        files.append(path)
    errors: list[str] = []
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True, cfile=str(ROOT / ".tmp" / "pycache-ci" / (path.stem + ".pyc")))
        except py_compile.PyCompileError as exc:  # noqa: PERF203
            errors.append(f"{path.relative_to(ROOT)}: {exc.msg.strip().splitlines()[-1]}")
    if errors:
        record("FAIL", "py_compile", f"{len(errors)} 个文件编译失败: " + "; ".join(errors[:5]))
    else:
        record("PASS", "py_compile", f"{len(files)} 个 Python 文件编译通过")
    if verbose:
        print(f"  py_compile: {len(files)} files, {len(errors)} errors")


# ── 2. 单元测试（etl / lib / mobile）──────────────────────────────────────
def _run_unittest(name: str, args: list[str]) -> None:
    started = time.time()
    proc = _run([PY, "-m", "unittest", *args])
    out = (proc.stdout or "") + (proc.stderr or "")
    summary = _tail(out, 2)
    if proc.returncode == 0:
        record("PASS", name, f"{summary}（{time.time() - started:.1f}s）")
    else:
        record("FAIL", name, f"exit {proc.returncode}: {_tail(out, 6)}")


def check_unittests() -> None:
    _run_unittest("unittest:etl", ["discover", "-s", "etl", "-t", "etl"])
    _run_unittest("unittest:lib", ["discover", "-s", "lib", "-t", "lib"])
    _run_unittest("unittest:mobile", ["tests.test_mobile_inbox"])


# ── 3. trilingual（需要 data/drugs.db；CI 无库则 SKIP）───────────────────
def check_trilingual(verbose: bool) -> None:
    if not DB.exists():
        record("SKIP", "trilingual", "缺 data/drugs.db（CI 无库；发布前请在本地跑）")
        return
    started = time.time()
    proc = _run([PY, "tests/trilingual/run_tests.py"], timeout=1800)
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
        record("PASS", "trilingual", f"{detail}（{time.time() - started:.1f}s；allowlist 见脚本常量）")
    if verbose:
        print("  trilingual:", detail)


# ── 4. 数据体检（需要 data/drugs.db）────────────────────────────────────
def check_database() -> None:
    if not DB.exists():
        record("SKIP", "check_data", "缺 data/drugs.db（CI 无库；发布前请在本地跑）")
        return
    proc = _run([PY, "db/check_data.py"], timeout=600)
    if proc.returncode == 0:
        record("PASS", "check_data", _tail(proc.stdout, 1) or "exit 0")
    else:
        record("FAIL", "check_data", f"exit {proc.returncode}: {_tail(proc.stdout + proc.stderr, 4)}")


# ── 5. 站点产物完整性（site/dist 存在才跑）─────────────────────────────
def check_dist(verbose: bool, fast: bool) -> None:
    if not DIST.is_dir():
        record("SKIP", "dist-integrity", "无 site/dist（生成物不入库；CI 跳过，发布前本地必跑）")
        return
    problems: list[str] = []
    for rel in REQUIRED_DIST_FILES:
        path = DIST / rel
        if not path.exists():
            problems.append(f"缺 {rel}")
        elif path.is_file() and path.stat().st_size == 0:
            problems.append(f"{rel} 为 0 字节")
    if CORE_JSON.exists() and CORE_JSON.stat().st_size < CORE_MIN_BYTES:
        problems.append(f"core.json 仅 {CORE_JSON.stat().st_size:,} B（< {CORE_MIN_BYTES:,}）")
    locs = 0
    sitemap = DIST / "sitemap.xml"
    if sitemap.exists():
        locs = len(re.findall(r"<loc>", sitemap.read_text(encoding="utf-8", errors="replace")))
        if locs < SITEMAP_MIN_URLS:
            problems.append(f"sitemap 仅 {locs} URL（< {SITEMAP_MIN_URLS:,}）")
    all_files = list(DIST.rglob("*"))
    files = [p for p in all_files if p.is_file()]
    if len(files) < DIST_MIN_FILES:
        problems.append(f"仅 {len(files)} 文件（< {DIST_MIN_FILES:,}）")
    zero = 0 if fast else sum(1 for p in files if p.stat().st_size == 0)
    if zero:
        problems.append(f"{zero} 个 0 字节文件")
    node = shutil.which("node")
    if node:
        proc = _run([node, "--check", str(DIST / "assets" / "app.js")], timeout=120)
        if proc.returncode != 0:
            problems.append("node --check assets/app.js 失败: " + _tail(proc.stderr, 2))
    if problems:
        record("FAIL", "dist-integrity", "; ".join(problems[:6]))
    else:
        record("PASS", "dist-integrity",
               f"{len(files):,} 文件 / sitemap {locs:,} URL / 0 字节 {zero} / node {'已检查' if node else '未安装跳过'}")
    if verbose:
        print(f"  dist: {len(files)} files, sitemap {locs}, zero {zero}")


# ── 6. CI 配置自检（防止 workflow 被误删/改名）──────────────────────────
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CI / 本地发布共用的检查入口（只读）")
    ap.add_argument("--fast", action="store_true", help="跳过 trilingual 与全量 0 字节扫描")
    ap.add_argument("--verbose", action="store_true", help="打印每项明细")
    args = ap.parse_args(argv)

    started = time.time()
    print(f"== CI checks ==  repo={ROOT}")
    check_py_compile(args.verbose)
    check_unittests()
    if not args.fast:
        check_trilingual(args.verbose)
    else:
        record("SKIP", "trilingual", "--fast 跳过")
    if not args.fast:
        check_database()
    else:
        record("SKIP", "check_data", "--fast 跳过")
    check_dist(args.verbose, args.fast)
    check_workflow()

    failed = [r for r in results if r[0] == "FAIL"]
    print("\n== 汇总 ==")
    for status, name, detail in results:
        print(f"[{status:4}] {name:18} {detail}")
    print(f"\n{len(results)} 项：PASS {sum(1 for r in results if r[0] == 'PASS')} / "
          f"FAIL {len(failed)} / SKIP {sum(1 for r in results if r[0] == 'SKIP')}"
          f"（{time.time() - started:.1f}s）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
