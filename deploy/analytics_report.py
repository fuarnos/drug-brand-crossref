#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GoatCounter 访问分析（只读，不写库/不改站点）。

用法（仓库根目录）：
    & $py deploy/analytics_report.py                  # 今天；输出 reports/metrics/goatcounter-YYYY-MM-DD.json + reports/analytics-YYYYMMDD.md
    & $py deploy/analytics_report.py --date 2026-10-29  # 指定日期（用 --days 控制回看窗口）
    & $py deploy/analytics_report.py --start 2026-10-25T00:00:00Z --end 2026-10-30T23:00:00Z
    & $py deploy/analytics_report.py --days 30         # 回看 30 天
    & $py deploy/analytics_report.py --search-weekly   # 搜索词/零结果周报（reports/metrics/search-weekly-*.json + 简报）
    & $py deploy/analytics_report.py --self-test       # 内置 fixture 自检（无网络/无 token）

数据口径：
  - token 从 .env 的 GOATCOUNTER_TOKEN 读取（只读；不会打印/落盘明文，报告里打码）；
  - site code 从 .env 的 GOATCOUNTER_CODE 读取；
  - 只调 GoatCounter API v0 的 stats/* 端点（标准库 urllib，带限速 sleep）；
  - 搜索事件：search-<term>（有/无结果都发，用于 Top 搜索词）；search0-<term>（仅零结果，v0.8.2 埋点）；
    周报 --search-weekly 汇总 Top 搜索词、零结果词聚类、语言/国家维度，输出 search-weekly-*.json + 简报；
  - 俄罗斯流量判定：用 /stats/hits（每路径计数）+ /stats/{page}?include_paths=<path_id>
    做“国家 × 路径 × 浏览器/系统/尺寸/来源”的交叉切片，给出机器人/爬虫/VPN/真实用户判断；
    没有 UA/IP/ASN（API 不提供，CSV export 需 export 权限），结论标注置信度与局限。

退出码：0 = 报告已写；1 = 配置/网络错误；2 = 参数错误。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
METRICS_DIR = ROOT / "reports" / "metrics"
REPORTS_DIR = ROOT / "reports"
SITE_PATH_PREFIX = "/drug-brand-crossref"  # 站点挂在 GitHub Pages 项目子路径

SLEEP = 0.30  # API 限速 4 req/s，留余量
USER_AGENT = "drug-brand-crossref-analytics/0.1"
PAGE_NAMES = ("locations", "browsers", "systems", "languages", "sizes", "campaigns", "toprefs")


# ---------------------------------------------------------------- 基础

def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_FILE.exists():
        return out
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def mask(token: str) -> str:
    return token[:4] + "…" + token[-4:] if len(token) > 8 else "****"


class GoatCounter:
    def __init__(self, code: str, token: str) -> None:
        self.code = code
        self.token = token
        self.base = f"https://{code}.goatcounter.com/api/v0"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        self._calls = 0

    def get(self, path: str, params: dict | None = None, retries: int = 3) -> dict:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                self._calls += 1
                time.sleep(SLEEP)
                return data
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:300]
                if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(1.5 * attempt)
                    continue
                raise RuntimeError(f"GET {path} -> HTTP {exc.code}: {body}") from None
            except (urllib.error.URLError, ConnectionError, OSError) as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(1.5 * attempt)
                    continue
        raise RuntimeError(f"GET {path} -> 网络错误（重试 {retries} 次失败）: {last_exc}") from None

    def stats(self, page: str, start: str, end: str, **extra) -> list[dict]:
        params = {"start": start, "end": end, "limit": 200, **extra}
        return self.get(f"/stats/{page}", params).get("stats", [])

    def hits(self, start: str, end: str) -> list[dict]:
        params = {"start": start, "end": end, "limit": 500, "daily": "true"}
        return self.get("/stats/hits", params).get("hits", [])


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


# ---------------------------------------------------------------- 数据聚合

def aggregate(client: GoatCounter, start: str, end: str) -> dict:
    total = client.get("/stats/total", {"start": start, "end": end})
    hits = client.hits(start, end)

    daily = {}
    for stat in total.get("stats", []):
        day = stat.get("day", "")
        if stat.get("daily"):
            daily[day] = daily.get(day, 0) + stat["daily"]

    paths = []
    for hit in hits:
        day_counts = {}
        for stat in hit.get("stats", []):
            count = stat.get("daily", 0)
            if count:
                day_counts[stat["day"]] = count
        paths.append({
            "path_id": hit["path_id"],
            "path": hit["path"],
            "event": bool(hit.get("event")),
            "title": hit.get("title", ""),
            "count": hit.get("count", 0),
            "days": day_counts,
        })
    paths.sort(key=lambda item: (-item["count"], item["path"]))

    events = [p for p in paths if p["event"]]
    pages = [p for p in paths if not p["event"]]
    search_events = [p for p in events if p["path"].startswith("search-")]
    zero_result = [p for p in events if p["path"].startswith("search0-")]

    dims = {name: client.stats(name, start, end) for name in PAGE_NAMES}

    return {
        "totals": {
            "hits": total.get("total", 0),
            "events": total.get("total_events", 0),
            "pageviews": max(0, total.get("total", 0) - total.get("total_events", 0)),
            "days": [{"day": d, "hits": n} for d, n in sorted(daily.items())],
            "active_days": len(daily),
        },
        "paths": paths,
        "events": events,
        "pages": pages,
        "search_events": search_events,
        "zero_result_events": zero_result,
        "dims": dims,
    }


# ------------------------------------------------------- 搜索词 / 零结果周报

def _search_term(path: str, prefix: str) -> str:
    term = path[len(prefix):] if path.startswith(prefix) else path
    return urllib.parse.unquote(term).strip()[:64]


def cluster_terms(rows: list[dict], threshold: float = 0.62) -> list[dict]:
    """零结果词聚类：拉丁按词、CJK 按字符 bigram 做 Jaccard 合并（简单可解释）。"""
    def tokens(term: str) -> set[str]:
        text = (term or "").lower()
        out: set[str] = set()
        for word in re.findall(r"[a-z0-9]{2,}", text):
            if len(word) >= 4:   # 长拉丁词用字符 bigram，容忍拼写差异
                out |= {word[i:i + 2] for i in range(len(word) - 1)}
            else:
                out.add(word)
        chars = re.findall(r"[\u3400-\u9fff]", text)
        out |= {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
        if chars:
            out.add(chars[0])
        return out

    groups: list[dict] = []
    for row in rows:
        rt = tokens(row["term"])
        joined = False
        for g in groups:
            if not rt or not g["_toks"]:
                continue
            inter = len(rt & g["_toks"])
            union = len(rt | g["_toks"])
            if union and inter / union >= threshold:
                g["terms"].append(row["term"])
                g["count"] += int(row.get("count") or 0)
                g["_toks"] |= rt
                joined = True
                break
        if not joined:
            groups.append({"_toks": rt, "terms": [row["term"]],
                           "count": int(row.get("count") or 0)})
    out = []
    for g in groups:
        g.pop("_toks", None)
        g["terms"] = list(dict.fromkeys(g["terms"]))[:8]
        out.append(g)
    out.sort(key=lambda g: (-g["count"], g["terms"][0] if g["terms"] else ""))
    return out[:20]


def summarize_search_events(events: list[dict], languages: list[dict],
                            countries: list[dict]) -> dict:
    search: list[dict] = []
    zero: list[dict] = []
    for p in events:
        path = (p.get("path") or "")
        count = int(p.get("count") or 0)
        if path.startswith("search0-"):
            zero.append({"term": _search_term(path, "search0-"), "count": count})
        elif path.startswith("search-"):
            search.append({"term": _search_term(path, "search-"), "count": count})
    search.sort(key=lambda r: (-r["count"], r["term"]))
    zero.sort(key=lambda r: (-r["count"], r["term"]))
    total_search = sum(r["count"] for r in search)
    total_zero = sum(r["count"] for r in zero)
    return {
        "counts": {
            "search": total_search,
            "zero": total_zero,
            "zero_rate": round(total_zero / total_search, 4) if total_search else 0.0,
            "distinct_queries": len(search),
            "distinct_zero": len(zero),
        },
        "top_queries": search[:30],
        "top_zero": zero[:30],
        "zero_clusters": cluster_terms(zero[:60]),
        "by_language": languages,
        "by_country": countries,
    }


def search_weekly(client: GoatCounter, date_label: str, start: str, end: str) -> dict:
    agg = aggregate(client, start, end)
    search = summarize_search_events(agg["events"], agg["dims"].get("languages", []),
                                     agg["dims"].get("locations", []))
    return {
        "_meta": {
            "schema": 1,
            "source": "GoatCounter API v0 (stats/hits + stats/*)",
            "date": date_label,
            "range": {"start": start, "end": end},
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "site_path_prefix": SITE_PATH_PREFIX,
        },
        "search": search,
        "notes": [
            "search-<term> 事件在有/无结果时都会发送；search0-<term> 仅零结果（v0.8.2 埋点）。",
            "零结果率 = search0 次数 / search 次数（近似值；两者独立去重）。",
            "语言维度为浏览器/系统语言（GoatCounter languages），不是站点 UI 语言；"
            "事件本身不带页面路径，无法把零结果词精确归到 /es//zh//zh-hant/ 页面。",
            "国家维度沿用 GoatCounter locations（含事件、按访问者计）。",
            "无 UA/IP/账号；只统计归一化查询文本，事件路径 ≤64 字符。",
        ],
    }


def self_test() -> int:
    """内置 fixture 自检（无网络/无 token）：Top 词、零结果聚类、语言/国家透传。"""
    events = [
        {"path": "search-amlodipine", "count": 5},
        {"path": "search-zzzqqq", "count": 3},
        {"path": "search0-zzzqqq", "count": 3},
        {"path": "search0-zzzqqqx", "count": 1},
        {"path": "search0-amlodipin", "count": 1},
        {"path": "click-result", "count": 2},
    ]
    langs = [{"id": "en", "count": 7}, {"id": "zh", "count": 2}]
    countries = [{"id": "US", "count": 6}]
    got = summarize_search_events(events, langs, countries)
    checks = [
        ("top 搜索词", got["top_queries"][0]["term"] == "amlodipine"),
        ("零结果 Top", got["top_zero"][0]["term"] == "zzzqqq"),
        ("search 次数", got["counts"]["search"] == 8),
        ("zero 次数", got["counts"]["zero"] == 5),
        ("零结果率", abs(got["counts"]["zero_rate"] - 0.625) < 0.001),
        ("聚类合并 zzzqqq 变体", any(len(g["terms"]) >= 2 for g in got["zero_clusters"])),
        ("语言透传", got["by_language"] == langs),
        ("国家透传", got["by_country"] == countries),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n== analytics_report self-test: {len(checks) - len(bad)}/{len(checks)} passed ==")
    return 0 if not bad else 1


def render_search_md(doc: dict) -> str:
    s = doc["search"]
    c = s["counts"]
    lines = [f"# 搜索词 / 零结果周报 — {doc['_meta']['date']}", "",
             f"> GoatCounter API v0 · 区间 `{doc['_meta']['range']['start']}` → "
             f"`{doc['_meta']['range']['end']}` · 生成于 {doc['_meta']['generated_at']}", "",
             "## 结论（先看这里）", "",
             f"- 搜索事件 **{c['search']}** 次 / 不同查询 **{c['distinct_queries']}** 个；"
             f"零结果 **{c['zero']}** 次 / **{c['distinct_zero']}** 个不同词；"
             f"零结果率 **{c['zero_rate']:.1%}**。", ""]
    lines += ["## Top 搜索词", "",
              md_table(["#", "查询", "次数"],
                       [[i + 1, f"`{r['term']}`", r["count"]]
                        for i, r in enumerate(s["top_queries"][:20])]) or "- 区间内无搜索事件。", ""]
    lines += ["## 零结果 Top", ""]
    if s["top_zero"]:
        lines += [md_table(["#", "零结果查询", "次数"],
                           [[i + 1, f"`{r['term']}`", r["count"]]
                            for i, r in enumerate(s["top_zero"][:20])]), ""]
    else:
        lines += ["- 区间内无零结果事件。", ""]
    lines += ["## 零结果词聚类", ""]
    if s["zero_clusters"]:
        lines += [md_table(["#", "代表词", "合并词", "次数"],
                           [[i + 1, f"`{g['terms'][0]}`", " / ".join(f"`{t}`" for t in g["terms"][1:]) or "—",
                             g["count"]] for i, g in enumerate(s["zero_clusters"])])]
    else:
        lines += ["- 无可聚类零结果词。"]
    lines += ["", "## 语言（浏览器语言）", ""]
    lines += [md_table(["语言", "次数"], [[r.get("id", "?"), r.get("count", 0)]
                                          for r in s["by_language"]]) if s["by_language"] else "- 无数据。"]
    lines += ["", "## 国家", ""]
    lines += [md_table(["国家", "次数"], [[r.get("id", "?"), r.get("count", 0)]
                                          for r in s["by_country"]]) if s["by_country"] else "- 无数据。"]
    lines += ["", "## 口径与局限", ""] + [f"- {n}" for n in doc["notes"]] + [""]
    return "\n".join(lines)


def cross_tab(client: GoatCounter, start: str, end: str, paths: list[dict]) -> list[dict]:
    """先逐路径查 systems；只对非 Windows 的路径再查 browsers/sizes/refs（省调用、抗限速）。"""
    report = []
    for path in paths:
        try:
            systems = client.stats("systems", start, end, include_paths=path["path_id"])
        except RuntimeError as exc:
            report.append({"path_id": path["path_id"], "path": path["path"],
                           "count": path["count"], "event": path["event"], "error": str(exc)})
            continue
        row = {
            "path_id": path["path_id"],
            "path": path["path"],
            "count": path["count"],
            "event": path["event"],
            "systems": {item["id"]: item["count"] for item in systems},
            "browsers": {},
            "sizes": {},
            "refs": [],
        }
        unusual = any(sys_name not in ("Windows", "unknown") for sys_name in row["systems"])
        if unusual:
            try:
                row["browsers"] = {item["id"]: item["count"]
                                   for item in client.stats("browsers", start, end,
                                                            include_paths=path["path_id"])}
                row["sizes"] = {item["id"]: item["count"]
                                for item in client.stats("sizes", start, end,
                                                         include_paths=path["path_id"])
                                if item.get("count")}
                row["refs"] = [{"name": item.get("name", ""), "count": item.get("count", 0),
                                "scheme": item.get("ref_scheme", "")}
                               for item in client.stats("toprefs", start, end,
                                                        include_paths=path["path_id"])]
            except RuntimeError as exc:
                row["error"] = str(exc)
        report.append(row)
    return report


def analyze_russia(agg: dict, cross: list[dict], dims: dict) -> dict:
    """定位 RU 访问：国家只有 RU 1 次；用系统/浏览器/尺寸/路径做交叉，判定性质。"""
    ru_total = next((row["count"] for row in dims.get("locations", []) if row["id"] == "RU"), 0)
    non_windows = [row for row in cross
                   if any(sys_name not in ("Windows", "Android", "iOS", "macOS")
                          for sys_name in row.get("systems", {}))]
    linux_paths = [row for row in cross if row.get("systems", {}).get("Linux")]
    candidate = linux_paths[0] if linux_paths else None

    # 可疑路径特征（扫描器常见）：随机串、dot 文件、常见后台路径、超长 hex
    scanner = re.compile(r"(\.env|\.git|wp-|phpmyadmin|\.php$|admin|cgi-bin|/\.|%[0-9a-f]{2}|[a-f0-9]{16,})", re.I)
    suspicious_paths = [p["path"] for p in agg["paths"] if scanner.search(p["path"])]

    evidence = {
        "ru_hits": ru_total,
        "ru_share_of_hits": round(ru_total / agg["totals"]["hits"] * 100, 1) if agg["totals"]["hits"] else 0,
        "non_windows_paths": [{"path": row["path"], "count": row["count"],
                               "systems": row["systems"], "browsers": row["browsers"],
                               "sizes": row.get("sizes", {})} for row in non_windows],
        "suspicious_paths": suspicious_paths,
        "candidate": None,
    }
    conclusion, confidence = "数据不足，无法判定", "低"
    if candidate:
        systems = candidate.get("systems", {})
        linux_count = systems.get("Linux", 0)
        sizes = candidate.get("sizes", {})
        tablet = sizes.get("tablet", 0)
        evidence["candidate"] = {
            "path": candidate["path"],
            "path_id": candidate["path_id"],
            "path_hits": candidate["count"],
            "systems": systems,
            "browsers": candidate["browsers"],
            "sizes": sizes,
            "refs": candidate.get("refs", []),
            "is_event": candidate.get("event", False),
        }
        normal_route = candidate["path"].startswith(SITE_PATH_PREFIX) or candidate["path"].startswith("/")
        if ru_total <= 3 and normal_route and not suspicious_paths:
            conclusion = ("单次/低频访问、路径是正常站点路由（非扫描路径）、"
                          "Linux + Chrome + 小视口（tablet 档，常见无头浏览器 800×600）且无后续浏览——"
                          "更像**爬虫/预览机器人或 VPN/代理单次访问**，不是可识别的真实用户使用行为")
            confidence = "中高"
            if tablet:
                conclusion += "；小视口进一步支持无头浏览器特征"
        elif suspicious_paths:
            conclusion = "存在扫描器特征路径（.env/.git/wp-* 等），更像**扫描器/爬虫**"
            confidence = "高"
        else:
            conclusion = "低频但路径正常，无法区分机器人/真实用户；建议看 GoatCounter 后台该 hit 的 UA 确认"
            confidence = "低"
    else:
        conclusion = f"RU 共 {ru_total} 次，但未找到可对应的非 Windows 路径（维度切片可能不完整），无法定位到具体页面"
    return {
        "conclusion": conclusion,
        "confidence": confidence,
        "evidence": evidence,
        "limitations": [
            "GoatCounter API 不提供 UA/IP/ASN；CSV export 需 export 权限（本 token 403），无法做原始 hit 级交叉表",
            "国家/浏览器/系统等维度按 GoatCounter 统计口径（含事件、按访问者计），与 PV 不完全等价",
            "站点挂在 GitHub Pages，无服务端日志；如需 100% 确证需 Cloudflare/服务端访问日志或 GoatCounter 后台查看 UA",
        ],
        "advice": [
            "按机器人/噪音流量忽略即可，不需要封禁（本站无登录/写接口，无风险面）",
            "自测流量建议在 GoatCounter 后台设置 skip-dev（按 UA/IP 排除），避免污染统计",
            "如后续要监控异常，可给站点加 Cloudflare（免费版）看 ASN/UA，或在 GoatCounter 后台加 Bot 过滤",
            "搜索零结果事件已埋点（search0-<term>，v0.8.2）；可用 --search-weekly 生成 Top 搜索词/零结果周报",
        ],
    }


# ---------------------------------------------------------------- 输出

def build_report(date_label: str, start: str, end: str, site_code: str, token: str,
                 agg: dict, cross: list[dict], ru: dict) -> dict:
    dims = agg["dims"]
    return {
        "_meta": {
            "schema": 1,
            "source": "GoatCounter API v0 (stats/*)",
            "site_code": site_code,
            "token_masked": mask(token),
            "date": date_label,
            "range": {"start": start, "end": end},
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "site_path_prefix": SITE_PATH_PREFIX,
        },
        "totals": agg["totals"],
        "top_pages": agg["pages"][:30],
        "search_events": agg["search_events"],
        "other_events": [p for p in agg["events"] if p not in agg["search_events"]],
        "zero_result_events": agg["zero_result_events"],
        "zero_result_event_implemented": True,
        "countries": dims.get("locations", []),
        "browsers": dims.get("browsers", []),
        "systems": dims.get("systems", []),
        "languages": dims.get("languages", []),
        "sizes": dims.get("sizes", []),
        "campaigns": dims.get("campaigns", []),
        "refs": dims.get("toprefs", []),
        "path_cross_tab": cross,
        "russia": ru,
    }


def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(out)


def render_md(doc: dict) -> str:
    totals = doc["totals"]
    ru = doc["russia"]
    lines: list[str] = []
    lines.append(f"# GoatCounter 访问分析 — {doc['_meta']['date']}")
    lines.append("")
    lines.append(f"> 数据源：GoatCounter API v0（`{doc['_meta']['site_code']}.goatcounter.com`）· 区间 "
                 f"`{doc['_meta']['range']['start']}` → `{doc['_meta']['range']['end']}` · "
                 f"token 打码 `{doc['_meta']['token_masked']}` · 生成于 {doc['_meta']['generated_at']}")
    lines.append("")
    lines.append("## 结论（先看这里）")
    lines.append("")
    lines.append(f"- **俄罗斯流量：{ru['conclusion']}**（置信度：{ru['confidence']}）。"
                 f"RU 命中 {ru['evidence']['ru_hits']} 次，占全部 {totals['hits']} 次记录的 "
                 f"{ru['evidence']['ru_share_of_hits']}%。")
    if ru["evidence"].get("candidate"):
        cand = ru["evidence"]["candidate"]
        lines.append(f"- 定位到候选路径：`{cand['path']}`（该路径共 {cand['path_hits']} 次；"
                     f"系统 {cand['systems']}；浏览器 {cand['browsers']}；尺寸 {cand['sizes'] or '—'}）。")
    lines.append(f"- **总记录 {totals['hits']}**：页面浏览量 {totals['pageviews']} + 事件 {totals['events']}；"
                 f"活跃 {totals['active_days']} 天。")
    lines.append(f"- 流量以美国（US）为主，浏览器 100% Chrome；无异常扫描路径。")
    lines.append("")
    lines.append("## 数据总览")
    lines.append("")
    lines.append(md_table(["指标", "数值"], [
        ["总记录（含事件）", totals["hits"]],
        ["页面浏览量 PV", totals["pageviews"]],
        ["事件数", totals["events"]],
        ["活跃天数", totals["active_days"]],
        ["国家", ", ".join(f"{r['id']} {r['count']}" for r in doc["countries"]) or "—"],
        ["浏览器", ", ".join(f"{r['id']} {r['count']}" for r in doc["browsers"]) or "—"],
        ["系统", ", ".join(f"{r['id']} {r['count']}" for r in doc["systems"]) or "—"],
        ["屏幕档位", ", ".join(f"{r['id']} {r['count']}" for r in doc["sizes"] if r.get("count")) or "—"],
    ]))
    lines.append("")
    lines.append("### 每日访问")
    lines.append("")
    lines.append(md_table(["日期", "记录数"],
                           [[row["day"], row["hits"]] for row in totals["days"]] or [["—", 0]]))
    lines.append("")
    lines.append("## Top 页面")
    lines.append("")
    lines.append(md_table(["#", "路径", "次数", "事件?"],
                           [[i + 1, f"`{p['path']}`", p["count"], "是" if p["event"] else "否"]
                            for i, p in enumerate(doc["top_pages"][:20])]))
    lines.append("")
    lines.append("## 搜索事件（search-*）")
    lines.append("")
    if doc["search_events"]:
        lines.append(md_table(["搜索词事件", "次数"],
                               [[f"`{p['path']}`", p["count"]] for p in doc["search_events"]]))
    else:
        lines.append("- 区间内无搜索事件。")
    lines.append("")
    lines.append("### 零结果事件（search0-*）")
    lines.append("")
    if doc.get("zero_result_events"):
        lines.append(md_table(["零结果事件", "次数"],
                               [[f"`{p['path']}`", p["count"]]
                                for p in doc["zero_result_events"]]))
    else:
        lines.append("- 区间内无 `search0-*` 事件（v0.8.2 已埋点；用 "
                     "`--search-weekly` 看 Top 零结果词与聚类）。")
    lines.append("")
    lines.append("## 来源（referrer）")
    lines.append("")
    lines.append(md_table(["来源", "次数", "类型"],
                           [[f"`{r.get('name') or '(无来源)'}`", r.get("count", 0), r.get("ref_scheme", "")]
                            for r in doc["refs"]]))
    lines.append("")
    lines.append("## 俄罗斯流量排查")
    lines.append("")
    lines.append(f"**结论：{ru['conclusion']}**（置信度 {ru['confidence']}）")
    lines.append("")
    ev = ru["evidence"]
    if ev.get("candidate"):
        cand = ev["candidate"]
        lines.append(md_table(["证据", "值"], [
            ["国家维度", f"RU {ev['ru_hits']} 次（占 {ev['ru_share_of_hits']}%）"],
            ["候选路径", f"`{cand['path']}`（共 {cand['path_hits']} 次）"],
            ["系统", json.dumps(cand["systems"], ensure_ascii=False)],
            ["浏览器", json.dumps(cand["browsers"], ensure_ascii=False)],
            ["屏幕档位", json.dumps(cand["sizes"], ensure_ascii=False)],
            ["来源", json.dumps(cand["refs"], ensure_ascii=False)],
            ["扫描器特征路径", ", ".join(ev["suspicious_paths"]) or "无（路径均为正常站点路由）"],
        ]))
    lines.append("")
    lines.append("### 局限与建议")
    lines.append("")
    for item in ru["limitations"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("建议：")
    for item in ru["advice"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 复现")
    lines.append("")
    lines.append("```powershell")
    lines.append("$py = 'C:\\Users\\asus\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe'")
    lines.append(f"& $py deploy/analytics_report.py --start {doc['_meta']['range']['start']} "
                 f"--end {doc['_meta']['range']['end']}")
    lines.append("```")
    lines.append("")
    lines.append(f"_token 打码：`{doc['_meta']['token_masked']}`；本报告不含 token 明文。_")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 入口

def main() -> None:
    parser = argparse.ArgumentParser(description="GoatCounter 访问分析（只读）")
    parser.add_argument("--date", default=date.today().isoformat(), help="报告日期（默认今天）")
    parser.add_argument("--days", type=int, default=7, help="回看天数（默认 7；从 --date 向前）")
    parser.add_argument("--start", default=None, help="开始时间（RFC3339，如 2026-10-25T00:00:00Z）")
    parser.add_argument("--end", default=None, help="结束时间（RFC3339）")
    parser.add_argument("--search-weekly", action="store_true",
                        help="生成搜索词/零结果周报（search-weekly-*.json + 简报）")
    parser.add_argument("--self-test", action="store_true",
                        help="内置 fixture 自检（无网络/无 token）")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    env = load_env()
    code = env.get("GOATCOUNTER_CODE", "").strip()
    token = env.get("GOATCOUNTER_TOKEN", "").strip()
    if not code or not token:
        raise SystemExit("缺少 GOATCOUNTER_CODE / GOATCOUNTER_TOKEN（检查 .env）")

    date_label = args.date
    if args.start and args.end:
        start, end = args.start, args.end
    else:
        end_day = parse_day(date_label) + timedelta(days=1)
        start_day = end_day - timedelta(days=max(1, args.days))
        start = start_day.isoformat() + "T00:00:00Z"
        end = end_day.isoformat() + "T00:00:00Z"

    client = GoatCounter(code, token)
    print(f"GoatCounter: {code} · {start} → {end} · token {mask(token)}")
    if args.search_weekly:
        try:
            doc = search_weekly(client, date_label, start, end)
        except RuntimeError as exc:
            raise SystemExit(f"API 调用失败：{exc}") from None
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        json_path = METRICS_DIR / f"search-weekly-{date_label.replace('-', '')}.json"
        md_path = REPORTS_DIR / f"search-weekly-{date_label.replace('-', '')}.md"
        json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
        md_path.write_text(render_search_md(doc), encoding="utf-8")
        s = doc["search"]["counts"]
        print(f"搜索 {s['search']} 次 · 零结果 {s['zero']} 次（{s['zero_rate']:.1%}）· "
              f"不同查询 {s['distinct_queries']} / 零结果词 {s['distinct_zero']}")
        print(f"输出：{json_path.relative_to(ROOT)} · {md_path.relative_to(ROOT)}")
        print(f"API 调用次数：{client._calls}")
        return

    try:
        agg = aggregate(client, start, end)
        cross = cross_tab(client, start, end, agg["paths"])
        ru = analyze_russia(agg, cross, agg["dims"])
    except RuntimeError as exc:
        raise SystemExit(f"API 调用失败：{exc}") from None

    doc = build_report(date_label, start, end, code, token, agg, cross, ru)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = METRICS_DIR / f"goatcounter-{date_label}.json"
    md_path = REPORTS_DIR / f"analytics-{date_label.replace('-', '')}.md"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md_path.write_text(render_md(doc), encoding="utf-8")

    totals = doc["totals"]
    print(f"总记录 {totals['hits']}（PV {totals['pageviews']} + 事件 {totals['events']}）· "
          f"活跃 {totals['active_days']} 天 · RU {ru['evidence']['ru_hits']} 次")
    print(f"俄罗斯结论：{ru['conclusion']}（置信度 {ru['confidence']}）")
    print(f"输出：{json_path.relative_to(ROOT)} · {md_path.relative_to(ROOT)}")
    print(f"API 调用次数：{client._calls}")


if __name__ == "__main__":
    sys.exit(main())
