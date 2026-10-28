#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""线上 smoke（发布后护栏）：检查 GitHub Pages 上的公开站点是否真的「发布成功」。

用法（在仓库根跑）：
    & $py deploy/verify_live.py                                  # 全量检查，打印 JSON
    & $py deploy/verify_live.py --expect-version v0.4.1          # 额外断言页脚版本
    & $py deploy/verify_live.py --json-out .tmp/guardrails/verify-live.json
    & $py deploy/verify_live.py --compare-dist                  # 顺带对比本地 site/dist 体积

检查项（见 reports/release-guardrails.md）：
  首页 200 / 标题 / 懒加载提示 / 无索引 preload / app.js 引用；
  页脚版本 + 日期（--expect-version 时断言一致），es/zh 落地页版本一致；
  whats-new 顶部版本 = 页脚版本；About 200 且含访问统计隐私说明；
  GoatCounter 脚本存在（首页 + 落地页；--allow-missing-analytics 可降级为 warning）；
  data/idx/core.json 可请求、Content-Type JSON、gzip 后体积在合理区间（可选 --compare-dist）；
  data/index.json（?legacy=1 / 解码失败回退）仍可请求；
  关键页面 drug/tirzepatide.html、drug/atorvastatin.html、name/lipitor.html、confused.html；
  sitemap.xml URL 数、robots.txt Sitemap 行、未知路径返回 404。

退出码：0 = 通过（可带 warning）；1 = 有失败或站点不可达；2 = 参数错误。
stdout 永远是一个 JSON 对象（便于 publish 流程/自动化解析）；人读摘要走 stderr（--quiet 关闭）。
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://fuarnos.github.io/drug-brand-crossref/"
UA = "drug-brand-crossref-verify-live/1.0 (release guardrail; read-only)"
FOOTER_RE = re.compile(
    r'<a href="(?:\.\./)?whats-new\.html">\s*(v\d+\.\d+\.\d+)\s*·\s*(\d{4}-\d{2}-\d{2})\s*</a>')
WHATS_NEW_H2_RE = re.compile(r"<h2[^>]*>\s*(v\d+\.\d+\.\d+)")
ANALYTICS_RE = re.compile(
    r'data-goatcounter="https://([A-Za-z0-9_-]+)\.goatcounter\.com/count"')
GC_SCRIPT_RE = re.compile(r'src="https://gc\.zgo\.at/count\.js"')
PRELOAD_IDX_RE = re.compile(r'<link[^>]+rel="preload"[^>]+(?:index|core)\.json')
VERSION_RE = re.compile(r"v\d+\.\d+\.\d+")

# gzip 传输体积合理区间（2026-10-27 线上实测 core 3,808,417 B / index 6,059,167 B；
# 本机 gzip -9 core 3.68 MB，Pages 动态压缩约 +3.4%）。
CORE_GZ_RANGE = (2_500_000, 9_000_000)
CORE_RAW_RANGE = (11_000_000, 30_000_000)
INDEX_GZ_RANGE = (4_500_000, 13_000_000)
INDEX_RAW_RANGE = (28_000_000, 60_000_000)
SITEMAP_MIN_URLS = 25_000


class Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "", ms: int = 0) -> bool:
        self.items.append({"name": name, "ok": bool(ok), "detail": detail, "ms": ms})
        return ok

    def warn(self, name: str, detail: str) -> None:
        self.items.append({"name": name, "ok": True, "warning": True,
                           "detail": detail, "ms": 0})

    @property
    def failures(self) -> list[dict]:
        return [c for c in self.items if not c["ok"]]

    @property
    def warnings(self) -> list[dict]:
        return [c for c in self.items if c.get("warning")]


def fetch(url: str, *, method: str = "GET", timeout: float = 25.0,
          retries: int = 2) -> dict:
    """单次 HTTP 请求（gzip 解压、网络错误/5xx 重试）。返回 status/headers/body/ms。"""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, method=method, headers={
            "User-Agent": UA,
            "Accept-Encoding": "gzip",
            "Cache-Control": "no-cache",
        })
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read() if method == "GET" else b""
                if body and resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return {"status": resp.status, "headers": headers, "body": body,
                        "ms": int((time.perf_counter() - t0) * 1000)}
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            if e.code >= 500 and attempt < retries:
                time.sleep(1.0 + attempt)
                continue
            return {"status": e.code, "headers": {}, "body": body,
                    "ms": int((time.perf_counter() - t0) * 1000), "error": f"HTTP {e.code}"}
        except Exception as e:                      # 网络层错误：超时/DNS/TLS
            last_err = e
            if attempt < retries:
                time.sleep(1.0 + attempt)
                continue
    raise RuntimeError(f"{url}: {last_err}")


def text_of(res: dict) -> str:
    return res.get("body", b"").decode("utf-8", "replace")


def gz_len(data: bytes) -> int:
    return len(gzip.compress(data, 9, mtime=0))


def local_core_gz() -> int | None:
    p = ROOT / "site" / "dist" / "data" / "idx" / "core.json"
    if not p.is_file():
        return None
    return gz_len(p.read_bytes())


def fmt_bytes(n: int) -> str:
    return f"{n:,} B ({n / 1e6:.2f} MB)"


def main() -> int:
    ap = argparse.ArgumentParser(description="线上 smoke 测试（发布后护栏）")
    ap.add_argument("--base", default=DEFAULT_BASE, help="站点根 URL（默认线上）")
    ap.add_argument("--expect-version", default="",
                    help="断言页脚/whats-new 版本，如 v0.4.1（可省略 v）")
    ap.add_argument("--timeout", type=float, default=25.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--json-out", default="", help="把 JSON 结果也写到该文件")
    ap.add_argument("--compare-dist", action="store_true",
                    help="对比本地 site/dist/data/idx/core.json 的 gzip -9 体积（发布后应立即运行）")
    ap.add_argument("--allow-missing-analytics", action="store_true",
                    help="GoatCounter 脚本缺失只记 warning（默认算失败）")
    ap.add_argument("--quiet", action="store_true", help="不打印人读摘要（stderr）")
    args = ap.parse_args()

    base = args.base.rstrip("/") + "/"
    expect = args.expect_version.strip()
    if expect and not expect.startswith("v"):
        expect = "v" + expect
    stamp = int(time.time())
    started = time.perf_counter()
    checks = Checks()
    live_version = ""

    def get(path: str, *, method: str = "GET") -> dict:
        sep = "&" if "?" in path else "?"
        return fetch(f"{base}{path}{sep}v={stamp}", method=method,
                     timeout=args.timeout, retries=args.retries)

    # ── 1. 首页 ─────────────────────────────────────────────────────
    try:
        home = get("")
    except Exception as e:                          # 站点整体不可达
        checks.add("homepage", False, f"站点不可达: {e}")
        return _finish(args, base, expect, live_version, checks, started)
    home_text = text_of(home)
    checks.add("homepage-status", home["status"] == 200,
               f"HTTP {home['status']}, {len(home['body']):,} B", home["ms"])
    checks.add("homepage-title", "Medicine Brand Cross-Reference" in home_text,
               "标题缺失" if "Medicine Brand Cross-Reference" not in home_text else "ok")
    # v0.4.1 起 loadhint 的静态文本改由 data-i18n 提供（英文兜底 + i18n.js 换语言），
    # 所以同时接受两种形态：旧版中英静态文案 / 新版 data-i18n="home.hint_idle"。
    hint_ok = 'id="loadhint"' in home_text and (
        "hint_idle" in home_text or "首次搜索" in home_text
        or "First search needs to load the index" in home_text)
    checks.add("homepage-loadhint", hint_ok,
               "首搜加载提示存在（data-i18n=home.hint_idle）" if hint_ok
               else "缺少首搜加载提示（P0 懒加载回归）")
    checks.add("homepage-no-index-preload", not PRELOAD_IDX_RE.search(home_text),
               "首页不应 preload index/core.json")
    has_appjs = bool(re.search(r"assets/app\.js\?v=\d+", home_text))
    checks.add("homepage-appjs", has_appjs,
               "assets/app.js?v= 引用存在" if has_appjs else "缺少 assets/app.js?v= 引用")

    # ── 2. 页脚版本 ──────────────────────────────────────────────────
    fm = FOOTER_RE.search(home_text)
    if not fm:
        checks.add("footer-version", False, "首页页脚找不到 whats-new.html 版本链接")
    else:
        live_version, live_date = fm.group(1), fm.group(2)
        try:
            datetime.strptime(live_date, "%Y-%m-%d")
            date_ok = True
        except ValueError:
            date_ok = False
        checks.add("footer-version", date_ok,
                   f"页脚 = {live_version} · {live_date}" if date_ok
                   else f"页脚日期格式异常: {live_date}")
        if expect:
            checks.add("expect-version", live_version == expect,
                       f"期望 {expect}，线上 {live_version}")

    # ── 3. 三语落地页 / whats-new / About ───────────────────────────
    pages = {"/es/": get("es/"), "/zh/": get("zh/"),
             "whats-new.html": get("whats-new.html"),
             "about.html": get("about.html")}
    for name, res in pages.items():
        checks.add(f"{name}-status", res["status"] == 200,
                   f"HTTP {res['status']}", res["ms"])
    for name in ("/es/", "/zh/"):
        txt = text_of(pages[name])
        m = FOOTER_RE.search(txt)
        checks.add(f"{name}-version", bool(m) and (not live_version or m.group(1) == live_version),
                   f"落地页页脚 {m.group(1) if m else '缺失'}（应 = {live_version}）")

    wn = text_of(pages["whats-new.html"])
    wm = WHATS_NEW_H2_RE.search(wn)
    checks.add("whats-new-version",
               bool(wm) and (not live_version or wm.group(1) == live_version),
               f"whats-new 顶部 {wm.group(1) if wm else '缺失'}（应 = {live_version}）")
    if live_version:
        checks.add("whats-new-has-live-version", live_version in wn,
                   f"whats-new.html 含 {live_version}")

    ab = text_of(pages["about.html"])
    am = FOOTER_RE.search(ab)
    checks.add("about-version", bool(am) and (not live_version or am.group(1) == live_version),
               f"About 页脚 {am.group(1) if am else '缺失'}（应 = {live_version}）")

    # ── 4. GoatCounter 访问统计（v0.4.1 起） ────────────────────────
    gm = ANALYTICS_RE.search(home_text)
    gc_ok = bool(gm) and bool(GC_SCRIPT_RE.search(home_text))
    detail = (f"code={gm.group(1)}; 脚本 + count.js 存在" if gc_ok
              else "首页缺 data-goatcounter / gc.zgo.at/count.js")
    if gc_ok:
        checks.add("analytics-script", True, detail)
    elif args.allow_missing_analytics:
        checks.warn("analytics-script", detail + "（--allow-missing-analytics 降级为 warning）")
    else:
        checks.add("analytics-script", False, detail)
    if gc_ok:
        about_an_ok = "GoatCounter" in ab and "goatcounter.com/privacy" in ab
        checks.add("about-analytics-privacy", about_an_ok,
                   "About 含 GoatCounter 说明 + 隐私政策链接" if about_an_ok
                   else "About 缺少访问统计/隐私说明（三语段落）")
    for name in ("/es/", "/zh/"):
        txt = text_of(pages[name])
        page_an_ok = bool(ANALYTICS_RE.search(txt))
        checks.add(f"{name}-analytics", page_an_ok,
                   f"{name} 含 GoatCounter 脚本" if page_an_ok
                   else f"{name} 缺 GoatCounter 脚本")

    # ── 5. 索引文件：P1 核心 + 旧 index.json 回退 ───────────────────
    core = get("data/idx/core.json", method="HEAD")
    ctype = core["headers"].get("content-type", "")
    clen = int(core["headers"].get("content-length") or 0)
    cenc = core["headers"].get("content-encoding", "")
    core_ok = core["status"] == 200 and "json" in ctype.lower()
    checks.add("core-json-http", core_ok,
               f"HTTP {core['status']}, content-type={ctype or '缺'}", core["ms"])
    if core_ok and clen:
        if cenc == "gzip":
            lo, hi = CORE_GZ_RANGE
            checks.add("core-json-size", lo <= clen <= hi,
                       f"gzip {fmt_bytes(clen)}（合理区间 {lo:,}–{hi:,} B）")
        else:
            lo, hi = CORE_RAW_RANGE
            checks.add("core-json-size", lo <= clen <= hi,
                       f"未 gzip，明文 {fmt_bytes(clen)}（合理区间 {lo:,}–{hi:,} B）")
            checks.warn("core-json-gzip", "core.json 未按 gzip 传输（首搜 15 MB 明文，检查 Pages 压缩）")
        if args.compare_dist:
            local = local_core_gz()
            if local is None:
                checks.warn("core-size-vs-dist", "本地 site/dist/data/idx/core.json 不存在，跳过体积对比")
            else:
                ratio = clen / local if cenc == "gzip" else 0
                ok = cenc == "gzip" and 0.85 <= ratio <= 1.25
                checks.add("core-size-vs-dist", ok,
                           f"线上 {fmt_bytes(clen)} / 本地 gzip -9 {fmt_bytes(local)} = {ratio:.2f}×")
    else:
        checks.add("core-json-size", False, "core.json 缺 Content-Length")

    idx = get("data/index.json", method="HEAD")
    iclen = int(idx["headers"].get("content-length") or 0)
    icenc = idx["headers"].get("content-encoding", "")
    idx_ok = idx["status"] == 200 and "json" in idx["headers"].get("content-type", "").lower()
    checks.add("legacy-index-http", idx_ok,
               f"HTTP {idx['status']}（?legacy=1 / 解码失败回退）", idx["ms"])
    if idx_ok and iclen:
        lo, hi = INDEX_GZ_RANGE if icenc == "gzip" else INDEX_RAW_RANGE
        checks.add("legacy-index-size", lo <= iclen <= hi,
                   f"{'gzip ' if icenc == 'gzip' else '明文 '}{fmt_bytes(iclen)}")

    # ── 6. 关键页面 ─────────────────────────────────────────────────
    key_pages = [
        ("drug/tirzepatide.html", "tirzepatide"),
        ("drug/atorvastatin.html", "atorvastatin"),
        ("name/lipitor.html", "lipitor"),
        ("confused.html", ""),
    ]
    for path, marker in key_pages:
        res = get(path)
        txt = text_of(res)
        ok = res["status"] == 200 and len(txt) > 800
        if marker:
            ok = ok and marker in txt.lower()
        if live_version:
            ok = ok and live_version in txt
        checks.add(f"page-{path}", ok,
                   f"HTTP {res['status']}, {len(txt):,} 字符"
                   + ("" if not marker else f", 含 '{marker}'"), res["ms"])

    # ── 7. sitemap / robots / 404 ───────────────────────────────────
    sm = get("sitemap.xml")
    sm_text = text_of(sm)
    n_urls = sm_text.count("<url>")
    checks.add("sitemap-status", sm["status"] == 200, f"HTTP {sm['status']}", sm["ms"])
    checks.add("sitemap-urls", n_urls >= SITEMAP_MIN_URLS,
               f"{n_urls:,} 个 URL（下限 {SITEMAP_MIN_URLS:,}）")
    rb = get("robots.txt")
    rb_text = text_of(rb)
    checks.add("robots", rb["status"] == 200
               and f"{base}sitemap.xml" in rb_text,
               f"HTTP {rb['status']}, Sitemap 行 {'有' if 'Sitemap:' in rb_text else '缺'}", rb["ms"])
    missing = get(f"verify-live-404-{stamp}.html")
    checks.add("404-status", missing["status"] == 404,
               f"未知路径 HTTP {missing['status']}（应为 404）", missing["ms"])

    return _finish(args, base, expect, live_version, checks, started)


def _finish(args, base: str, expect: str, live_version: str,
            checks: Checks, started: float) -> int:
    failures = [c["name"] for c in checks.failures]
    warnings = [c["name"] for c in checks.warnings]
    ok = not failures
    result = {
        "ok": ok,
        "base_url": base,
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "expect_version": expect or None,
        "live_version": live_version or None,
        "elapsed_s": round(time.perf_counter() - started, 2),
        "checks": checks.items,
        "failures": failures,
        "warnings": warnings,
    }
    if not args.quiet:
        for c in checks.items:
            mark = "WARN" if c.get("warning") else ("PASS" if c["ok"] else "FAIL")
            detail = f" — {c['detail']}" if c.get("detail") else ""
            print(f"[{mark}] {c['name']}{detail}", file=sys.stderr)
        print(f"\n==> live {live_version or '?'}; "
              f"{len(checks.items) - len(failures) - len(warnings)} passed, "
              f"{len(failures)} failed, {len(warnings)} warnings", file=sys.stderr)
        if failures:
            print("FAILURES: " + ", ".join(failures), file=sys.stderr)
    out = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(out)
    if args.json_out:
        p = Path(args.json_out)
        if not p.is_absolute():
            p = ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out + "\n", encoding="utf-8")
        if not args.quiet:
            print(f"JSON: {p}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
