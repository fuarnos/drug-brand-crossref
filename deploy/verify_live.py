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
  **语言根路径全部 200（/、/es/、/zh/、/zh-hant/、/fr/、/ko/）且首页 hreflang 每个目标可达**；
  whats-new 顶部版本 = 页脚版本；About 200 且含访问统计隐私说明；
  GoatCounter 脚本存在（首页 + 落地页；--allow-missing-analytics 可降级为 warning）；
  data/idx/core.json 可请求、Content-Type JSON、gzip 后体积在合理区间（可选 --compare-dist）；
  data/index.json（?legacy=1 / 解码失败回退）仍可请求；
  关键页面 drug/tirzepatide.html、drug/atorvastatin.html、name/lipitor.html、confused.html；
  **REL2 增量发布契约（v1.0.0 起）**：assets/style.css 带 `Cache-Control: public, max-age=300`；
  长尾页用稳定名 assets/style.css / assets/boot.js + whats-new 链接，不含 hashed 资源、不含页脚版本号；
  **H1（v1.2.7 起）**：9 语首页 + 长尾页 boot.js 的语言包 URL 必须带非空数字 `?v=`（防「新 HTML + 旧语言包」显示键名）；
  9 语首页 hero 文案必须是直出文本，不得出现 `hero.title` 这类裸露键名；
  sitemap.xml URL 数（v1.2.3 起支持 **sitemap index + 分片**：逐片 200/可解析后求和；旧版单文件 urlset 仍按旧逻辑）、
  robots.txt Sitemap 行、未知路径返回 404。

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

# REL2（2026-11-20）增量发布契约：长尾页（name/drug/combo/maker/atc）改用稳定名资源
# （assets/style.css / assets/boot.js），页脚不再逐页写版本号；assets/ 由
# deploy/sync_r2.ps1 在上传后单独 copy 一遍并带 5 分钟缓存头。
# 这两条门禁在 v1.0.0 上线前**必然 FAIL**（旧产物仍是 hashed 资源 + 逐页版本号），属预期；
# v1.0.0 上线后必须 PASS，否则下一次发版又会退化成近全量上传。
# 证据见 reports/2026-11-20-v100-release.md。
ASSETS_CACHE_MAX_AGE = 300
CACHE_CONTROL_ASSET = "assets/style.css"
LONGTAIL_SAMPLE = "name/tylenol-8-hr-arthritis-pain.html"
LONGTAIL_STABLE_REFS = ("assets/style.css", "assets/boot.js", "whats-new.html")
LONGTAIL_HASHED_RE = re.compile(r"assets/(?:style|boot)\.[0-9a-f]{8,}\.(?:css|js)")
# 方案原文正则 `v\d+\.\d+\.\d+ · \d{4}-\d{2}-\d{2}`；\s* 只是容忍空白变体，语义不变。
LONGTAIL_VER_RE = re.compile(r"v\d+\.\d+\.\d+\s*·\s*\d{4}-\d{2}-\d{2}")
# H1（v1.2.7）：语言包 URL 的构建号必须是**非空数字**。
# 事故（用户 2026-11-26 截图「hero.title 裸露」）：首页内联的 i18n 引导脚本里
# `assets/i18n.<lang>.js?v=__BUILD_V__` 被「剥版本号」一起剥成 `?v=` → 语言包 URL 不随版本变，
# 旧语言包（≤5 分钟边缘缓存）配新页面新增的 hero.* 键，首屏就显示键名。
# 首页/语言副本把引导脚本内联在 HTML 里，长尾页写在 assets/boot.js 里，两处都查。
I18N_PACK_VER_RE = re.compile(r"assets/i18n[\s\S]{0,200}?\.js\?v=(\d+)")
EMPTY_JS_V_RE = re.compile(r"\.js\?v=(?!\d)")
HERO_H1_RE = re.compile(r'<h1\b[^>]*\bid="h1"[^>]*>(.*?)</h1>', re.S)
HERO_KEY_RE = re.compile(r"\bhero\.(?:title|label|try|sub|cta|howto|sources|about)\b")


# gzip 传输体积合理区间（2026-10-27 线上实测 core 3,808,417 B / index 6,059,167 B；
# 本机 gzip -9 core 3.68 MB，Pages 动态压缩约 +3.4%）。
# 2026-10-30 v0.9.1：AU 全量入库后 core.json 增至 41.3 MB raw / 9.67 MB gzip（本机 gzip -9），
# 旧上限 9 MB 会误报，故 gzip 上限 9 MB → 12 MB、raw 上限 30 MB → 50 MB（内容增长属预期，非回归）。
# 2026-11-22 v1.2.0 韩国入库：KR +97,356 产品使 core 到 67.96 MB raw / 13.32 MB gzip（同属内容增长，
# 非回归），故 gzip 上限 12 → 16 MB、raw 上限 50 → 80 MB。下一次接近上限前必须先做
# 「索引按文字系统分片」而不是继续调高（否则首屏体积会先崩）。
CORE_GZ_RANGE = (2_500_000, 16_000_000)
CORE_RAW_RANGE = (11_000_000, 80_000_000)
INDEX_GZ_RANGE = (4_500_000, 13_000_000)
INDEX_RAW_RANGE = (28_000_000, 60_000_000)
SITEMAP_MIN_URLS = 25_000
# v1.2.3 起 sitemap.xml 改为 **sitemap index + 分片**（每片 ≤50,000 URL，sitemaps.org 协议上限）；
# 旧版线上仍是单文件 <urlset>。下面两个常量/正则在两种结构间切换：index 逐片 GET 后求和，
# urlset 按旧逻辑数 `<url>`（判定口径与检查项名不变，历史报告可比）。
SITEMAP_MAX_URLS_PER_FILE = 50_000
SITEMAP_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
# 启用的语言根路径（英文在根）。**新增语言时必须同步这里**：发布门槛要求全部 200。
# 背景：v0.11.4 法语上线时 `/fr/` 因 Cloudflare Transform Rules 未加 fr 而 404
#（`/fr/index.html` 200），verify 当时没有语言根/hreflang 检查，0 failures 漏掉了它。
# v0.13.8 韩语上线：`/ko/` 同一坑（规则仍只有 4 条语言根），这里补第 6 条；
# `/fr/`、`/ko/` 由 deploy/fix_fr_root.py 写「对象键 fr/ / ko/」兜底（见 sync_r2.ps1）。
# v0.16.0 日语上线：`/ja/` 同一坑（hreflang-target-ja 失败），补第 7 条并写 `ja/` 兜底对象。
# v0.17.0 捷克语/拉脱维亚语上线：`/cs/` `/lv/` 同一坑，补第 8、9 条。
LANG_ROOTS = (("", "/"), ("es/", "/es/"), ("zh/", "/zh/"),
              ("zh-hant/", "/zh-hant/"), ("fr/", "/fr/"), ("ko/", "/ko/"),
              ("ja/", "/ja/"), ("cs/", "/cs/"), ("lv/", "/lv/"))


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
                wire_bytes = len(body)          # gzip 解压前的传输字节数（chunked 时没有 Content-Length）
                if body and resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return {"status": resp.status, "headers": headers, "body": body,
                        "wire_bytes": wire_bytes,
                        "ms": int((time.perf_counter() - t0) * 1000)}
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            if e.code >= 500 and attempt < retries:
                time.sleep(1.0 + attempt)
                continue
            return {"status": e.code, "headers": {}, "body": body, "wire_bytes": len(body),
                    "ms": int((time.perf_counter() - t0) * 1000), "error": f"HTTP {e.code}"}
        except Exception as e:                      # 网络层错误：超时/DNS/TLS
            last_err = e
            if attempt < retries:
                time.sleep(1.0 + attempt)
                continue
    raise RuntimeError(f"{url}: {last_err}")


def text_of(res: dict) -> str:
    return res.get("body", b"").decode("utf-8", "replace")


def visible_text(html: str) -> str:
    """去掉 <script>/<style> 块和全部标签后的可见文本（用来查「裸露键名」）。

    首页把语言字典与引导脚本内联在 HTML 里，`.hero.title` 这类字符串会出现在 JS 字典键上，
    所以必须先整块剔除再查正文，否则会误报。
    """
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", s)


def i18n_pack_version(html: str) -> str:
    """取页面（或 boot.js）里语言包 URL 的构建号 `assets/i18n…js?v=<数字>`；取不到返回空串。

    首页/语言副本把引导脚本内联在 HTML 里（`assets/i18n.' + LANG + '.js?v=…`），
    长尾页只在 assets/boot.js 里；这里在全文上找「assets/i18n 之后 200 字符内出现
    `.js?v=<数字>`」，不解析 JS 语法。空 `?v=`（历史事故）与非数字占位符都返回空串 → 门禁 FAIL。
    """
    m = I18N_PACK_VER_RE.search(html or "")
    return m.group(1) if m else ""


def sitemap_kind(text: str) -> str:
    """判断 sitemap.xml 结构：'index'（v1.2.3 起）/ 'urlset'（旧单文件）/ ''（无法识别）。"""
    if "<sitemapindex" in (text or ""):
        return "index"
    if "<urlset" in (text or ""):
        return "urlset"
    return ""


def sitemap_shards(text: str) -> list[str]:
    """从 sitemap index 里取分片 `<loc>` 列表（去首尾空白，保持原顺序）。"""
    return [m.group(1).strip() for m in SITEMAP_LOC_RE.finditer(text or "")]


def gz_len(data: bytes) -> int:
    return len(gzip.compress(data, 9, mtime=0))


def local_core_gz() -> int | None:
    p = ROOT / "site" / "dist" / "data" / "idx" / "core.json"
    if not p.is_file():
        return None
    return gz_len(p.read_bytes())


def core_size_bytes(headers: dict, body: bytes, wire_bytes: int) -> tuple[int, str, str]:
    """core.json 的判定字节数与口径：优先 Content-Length，缺头时用实测 body 兜底。

    R2 自定义域对 core.json 走 gzip + Transfer-Encoding: chunked，不返回
    Content-Length；此时用实际读到的字节数判定（gzip 用压缩后的 wire 字节，
    明文用解压后的 body 字节）。护栏 CORE_GZ_RANGE / CORE_RAW_RANGE 不变。

    返回 (字节数, "gzip" | "raw", 兜底说明)；取不到任何长度时返回 0。
    """
    cenc = (headers.get("content-encoding") or "").lower()
    clen = int(headers.get("content-length") or 0)
    if clen:
        return clen, ("gzip" if "gzip" in cenc else "raw"), ""
    if "gzip" in cenc and wire_bytes:
        return wire_bytes, "gzip", "（无 Content-Length，用 gzip 实测字节数）"
    if body:
        return len(body), "raw", "（无 Content-Length，用实测 body 字节数）"
    return 0, ("gzip" if "gzip" in cenc else "raw"), ""


def hreflang_targets(html: str) -> list[tuple[str, str]]:
    """从页面 head 解析 `<link rel="alternate" hreflang=... href=...>`（属性顺序无关）。"""
    out: list[tuple[str, str]] = []
    for tag in re.findall(r"<link\b[^>]*>", html or "", re.I):
        if 'rel="alternate"' not in tag.lower():
            continue
        mh = re.search(r'hreflang="([^"]+)"', tag, re.I)
        mu = re.search(r'href="([^"]+)"', tag, re.I)
        if mh and mu:
            out.append((mh.group(1), mu.group(1)))
    return out


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

    # ── 3b. 语言根路径 + hreflang 目标可达（v0.11.4 起）────────────
    # R2 自定义域不会把 `/xx/` 自动映射到 `/xx/index.html`，靠 Cloudflare Transform Rules；
    # 新增语言必须同时加规则（v0.11.4 的 /fr/ 就是这么漏的）。这里逐语言根 + hreflang 目标验 200。
    root_res = {"": home, "/es/": pages["/es/"], "/zh/": pages["/zh/"]}
    for prefix, label in LANG_ROOTS:
        if label in root_res:
            res = root_res[label]
        else:
            try:
                res = get(prefix)
            except Exception as e:
                checks.add(f"lang-root-{label}", False, f"{label} 不可达: {e}")
                continue
        checks.add(f"lang-root-{label}", res["status"] == 200 and len(res["body"]) > 500,
                   f"{label} HTTP {res['status']}, {len(res['body']):,} B")

    targets = hreflang_targets(home_text)
    by_url: dict[str, list[str]] = {}
    for lang, url in targets:
        if url.startswith("/"):
            url = base.rstrip("/") + url
        by_url.setdefault(url, []).append(lang)
    lang_home_text: dict[str, str] = {}   # H1 门禁复用这批已抓取的 9 语首页
    if not targets:
        checks.add("hreflang-links", False, "首页没有 hreflang alternate 链接")
    else:
        checks.add("hreflang-links", len(by_url) >= len(LANG_ROOTS),
                   f"{len(targets)} 条 hreflang / {len(by_url)} 个唯一目标（应 ≥ {len(LANG_ROOTS)}）")
        for url, langs in by_url.items():
            label = ",".join(sorted(set(langs)))
            try:
                res = fetch(url, timeout=args.timeout, retries=args.retries)
            except Exception as e:
                checks.add(f"hreflang-target-{label}", False, f"{url} 不可达: {e}")
                continue
            checks.add(f"hreflang-target-{label}", res["status"] == 200 and len(res["body"]) > 500,
                       f"{url} HTTP {res['status']}, {len(res['body']):,} B")
            if res["status"] == 200:
                lang_home_text[url] = text_of(res)

    # ── 3c. H1（v1.2.7）：语言包 URL 带真实构建号 + 9 语首页 hero 文案无裸露键名 ──
    # 两条门禁对准同一事故：新页面 + 旧语言包（或字典缺键）→ 首屏出现 `hero.title` 这类键名。
    # 数据复用 3b 已抓的 9 个 hreflang 目标页；长尾页另取一次 boot.js（语言包 URL 写在里面）。
    no_ver = [u for u, txt in lang_home_text.items() if not i18n_pack_version(txt)]
    empty_ver = [u for u, txt in lang_home_text.items() if EMPTY_JS_V_RE.search(txt)]
    if not lang_home_text:
        no_ver.append("9 语首页（hreflang 目标全不可达）")
    try:
        boot = get("assets/boot.js")
    except Exception as e:
        boot = {"status": 0, "body": b"", "ms": 0}
        no_ver.append(f"assets/boot.js 不可达: {e}")
    boot_txt = text_of(boot)
    if boot.get("status") == 200:
        if not i18n_pack_version(boot_txt):
            no_ver.append("assets/boot.js")
        if EMPTY_JS_V_RE.search(boot_txt):
            empty_ver.append("assets/boot.js")
    elif boot.get("status") != 0:
        no_ver.append(f"assets/boot.js HTTP {boot['status']}")
    pack_detail: list[str] = []
    if no_ver:
        pack_detail.append("缺非空 ?v=: " + ", ".join(no_ver[:5]))
    if empty_ver:
        pack_detail.append("出现空 ?v=: " + ", ".join(empty_ver[:5]))
    checks.add("i18n-pack-version", not no_ver and not empty_ver,
               ("; ".join(pack_detail) if pack_detail else
                f"{len(lang_home_text)} 语首页 + 长尾 boot.js 的语言包 URL 均带非空数字 ?v="))

    naked: list[str] = []
    empty_h1: list[str] = []
    for url, txt in lang_home_text.items():
        label = ",".join(sorted(set(by_url.get(url, []))))
        if HERO_KEY_RE.search(visible_text(txt)):
            naked.append(label)
        mh = HERO_H1_RE.search(txt)
        if not mh or len(visible_text(mh.group(1)).strip()) < 3:
            empty_h1.append(label)
    if not lang_home_text:
        naked.append("9 语首页不可达")
    hero_detail: list[str] = []
    if naked:
        hero_detail.append("裸露 hero.* 键名: " + ", ".join(naked[:6]))
    if empty_h1:
        hero_detail.append("h1 为空: " + ", ".join(empty_h1[:6]))
    checks.add("hero-direct-text", not naked and not empty_h1,
               ("; ".join(hero_detail) if hero_detail else
                f"{len(lang_home_text)} 语首页 hero 文案均为直出文本（无 hero.* 键名、h1 非空）"))

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
    # R2 自定义域对 core.json 走 gzip + chunked，不返回 Content-Length；
    # HEAD 拿不到大小时补一次 GET，用实测 body 字节数判定（护栏不变）。
    if core["status"] == 200 and not int(core["headers"].get("content-length") or 0):
        core = get("data/idx/core.json")
    ctype = core["headers"].get("content-type", "")
    core_ok = core["status"] == 200 and "json" in ctype.lower()
    checks.add("core-json-http", core_ok,
               f"HTTP {core['status']}, content-type={ctype or '缺'}", core["ms"])
    clen, cenc, size_note = core_size_bytes(
        core["headers"], core.get("body") or b"", int(core.get("wire_bytes") or 0))
    if core_ok and clen:
        if cenc == "gzip":
            lo, hi = CORE_GZ_RANGE
            checks.add("core-json-size", lo <= clen <= hi,
                       f"gzip {fmt_bytes(clen)}{size_note}（合理区间 {lo:,}–{hi:,} B）")
        else:
            lo, hi = CORE_RAW_RANGE
            checks.add("core-json-size", lo <= clen <= hi,
                       f"未 gzip，明文 {fmt_bytes(clen)}{size_note}（合理区间 {lo:,}–{hi:,} B）")
            checks.warn("core-json-gzip", "core.json 未按 gzip 传输（首搜 15 MB 明文，检查 Pages 压缩）"
                        + size_note)
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
        checks.add("core-json-size", False, "core.json 缺 Content-Length 且无实测 body")

    idx = get("data/index.json", method="HEAD")
    iclen = int(idx["headers"].get("content-length") or 0)
    icenc = idx["headers"].get("content-encoding", "")
    if idx["status"] == 404:
        # v0.6.1+ 默认停写 index.json：legacy 走 core+decodeCore，404 属预期
        checks.add("legacy-index-http", True,
                   "HTTP 404（预期：core-only 构建，legacy 走 core 解码）", idx["ms"])
    else:
        idx_ok = idx["status"] == 200 and "json" in idx["headers"].get("content-type", "").lower()
        checks.add("legacy-index-http", idx_ok,
                   f"HTTP {idx['status']}（?legacy=1 / 解码失败回退）", idx["ms"])
        if idx_ok and iclen:
            lo, hi = INDEX_GZ_RANGE if icenc == "gzip" else INDEX_RAW_RANGE
            checks.add("legacy-index-size", lo <= iclen <= hi,
                       f"{'gzip ' if icenc == 'gzip' else '明文 '}{fmt_bytes(iclen)}")

    # ── 6. 关键页面 ─────────────────────────────────────────────────
    # REL2（v1.0.0）起 name/drug 是长尾页：页脚不再写版本号、改用稳定名资源（契约由下面
    # 6b 的 longtail-footer 门禁覆盖），这里不再断言 live_version 出现在这些页面正文里；
    # 版本号仍由首页 / es / zh 落地页 / whats-new / About / 顶层页 confused.html 断言。
    key_pages = [
        ("drug/tirzepatide.html", "tirzepatide", False),
        ("drug/atorvastatin.html", "atorvastatin", False),
        ("name/lipitor.html", "lipitor", False),
        ("confused.html", "", True),
    ]
    for path, marker, wants_version in key_pages:
        res = get(path)
        txt = text_of(res)
        ok = res["status"] == 200 and len(txt) > 800
        if marker:
            ok = ok and marker in txt.lower()
        if live_version and wants_version:
            ok = ok and live_version in txt
        checks.add(f"page-{path}", ok,
                   f"HTTP {res['status']}, {len(txt):,} 字符"
                   + ("" if not marker else f", 含 '{marker}'"), res["ms"])

    # ── 6b. REL2 增量发布契约（v1.0.0 起常驻）──────────────────────
    # assets 5 分钟缓存：sync_r2.ps1 在主 sync 后单独 `rclone copy assets/` 带
    # `Cache-Control: public, max-age=300`；没有这一遍，稳定名资源永远没有缓存头。
    asset = get(CACHE_CONTROL_ASSET, method="HEAD")
    cc = asset["headers"].get("cache-control", "")
    checks.add("assets-cache-control",
               asset["status"] == 200 and f"max-age={ASSETS_CACHE_MAX_AGE}" in cc,
               f"HTTP {asset['status']}, Cache-Control={cc or '缺失'}（应为 public, max-age=300）",
               asset["ms"])

    # 长尾页契约：稳定名资源 + whats-new 链接，且不再内联页脚版本号 / hashed 资源名。
    # 版本号逐页写死会让 CHANGELOG 升级一次 = 15 万页全部重传（REL2 根因 A）；
    # 引用 hashed 资源会在改 CSS/JS 时让全部页面改名（根因 B）。
    lt = get(LONGTAIL_SAMPLE)
    lt_text = text_of(lt)
    missing = [m for m in LONGTAIL_STABLE_REFS if m not in lt_text]
    hashed = LONGTAIL_HASHED_RE.search(lt_text)
    ver_hit = LONGTAIL_VER_RE.search(lt_text)
    lt_ok = lt["status"] == 200 and not missing and not hashed and not ver_hit
    detail = f"/{LONGTAIL_SAMPLE} HTTP {lt['status']}"
    if missing:
        detail += f"; 缺稳定名引用 {','.join(missing)}"
    if hashed:
        detail += f"; 仍引用 hashed 资源 {hashed.group(0)}"
    if ver_hit:
        detail += f"; 仍含页脚版本号 {ver_hit.group(0)}"
    if lt_ok:
        detail += "; 稳定名 3/3 + 无 hashed 资源 + 无版本号"
    checks.add("longtail-footer", lt_ok, detail, lt["ms"])

    # ── 7. sitemap / robots / 404 ───────────────────────────────────
    # v1.2.3 起 sitemap.xml 是 <sitemapindex>（分片 sitemap-1.xml…，每片 ≤50,000 URL）：
    # 逐个分片 GET 200 + 可解析后求和；旧版线上仍是单文件 <urlset>，按旧逻辑数 `<url>`。
    sm = get("sitemap.xml")
    sm_text = text_of(sm)
    kind = sitemap_kind(sm_text)
    checks.add("sitemap-status", sm["status"] == 200, f"HTTP {sm['status']}", sm["ms"])
    if kind == "index":
        refs = sitemap_shards(sm_text)
        n_urls = 0
        per_shard: list[str] = []
        bad: list[str] = []
        for ref in refs:
            name = ref.rsplit("/", 1)[-1] or ref
            # 同源 → 走 get()（带 cache-buster）；异源只做兜底直连（sitemap 协议要求同源）
            if ref.startswith(base):
                res = get(ref[len(base):])
            elif ref.startswith("/"):
                res = get(ref.lstrip("/"))
            else:
                res = fetch(ref if "?" in ref else f"{ref}?v={stamp}",
                            timeout=args.timeout, retries=args.retries)
            text = text_of(res)
            cnt = text.count("<loc>")
            n_urls += cnt
            if res["status"] != 200:
                bad.append(f"{name} HTTP {res['status']}")
            elif "<urlset" not in text:
                bad.append(f"{name} 不是 urlset")
            elif cnt > SITEMAP_MAX_URLS_PER_FILE:
                bad.append(f"{name} {cnt:,} URL（> {SITEMAP_MAX_URLS_PER_FILE:,} 协议上限）")
            else:
                per_shard.append(f"{name} {cnt:,}")
        shards_ok = bool(refs) and not bad
        if not refs:
            shard_detail = "索引里没有分片 <loc>"
        elif bad:
            shard_detail = "分片异常：" + "; ".join(bad[:4])
        else:
            shard_detail = f"{len(refs)} 片全部 200 且可解析（" + " / ".join(per_shard) + "）"
        checks.add("sitemap-shards", shards_ok, shard_detail)
        checks.add("sitemap-urls", n_urls >= SITEMAP_MIN_URLS,
                   f"{len(refs)} shards / {n_urls:,} urls（下限 {SITEMAP_MIN_URLS:,}）")
    else:
        n_urls = sm_text.count("<url>")
        checks.add("sitemap-urls", n_urls >= SITEMAP_MIN_URLS,
                   f"{n_urls:,} 个 URL（单文件 / 下限 {SITEMAP_MIN_URLS:,}）")
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
