# -*- coding: utf-8 -*-
"""中文互联网药品俗名抓取器（阶段 A：中文网络叫法）。

背景
----
docs/谷段需求队列.md「俗名/街头叫法抓取」条目：只收**合法药品**（处方药/OTC/中成药/生物药）
的中文网络叫法、旧称、简称、地区名、品牌别名、民间俗称；**排除毒品、无医疗用途管制物质、
娱乐性用药及其黑话**。本脚本只做「抓取 + 短事实落盘」，不做抽取/入库：
抽取由 etl/extract_cn_slang.py（另一个管线）读 data/raw/cn_slang/raw_terms.jsonl 完成。

抓取纪律（用户已授权尝试平台，ToS 风险自担）
--------------------------------------------
1. 限速：每个请求之间 sleep 随机 3–5 秒（--min-delay/--max-delay 可调），不做并发。
2. 缓存：原始页落 data/raw/cn_slang/raw/<platform>/<sha1>.html（data/raw 不进仓库）。
3. 断点续跑：state.json 记录 done 查询 + 平台状态；重跑默认跳过已完成项。
4. 遇 403 / 验证码 / 安全验证 / 封禁：该平台**立即停用**并记 events.jsonl，降级到搜索摘要；
   搜索引擎也全被封则整体停止（不重试、不绕验证码、不登录、不破解签名）。
5. 只存短事实：term / platform / url / title(≤120) / snippet(≤200) / fetched_at / lang，
   不存用户名、头像、主页、大段正文。命中「毒品/娱乐性用药」关键词的结果直接丢弃并计数。
6. 请求带清楚 UA + 项目地址说明；UA 里不留个人联系人。

来源适配器
----------
直接平台：xiaohongshu（小红书）、zhihu（知乎）、weibo（微博）、tieba（贴吧）
搜索兜底：bing（必应）、baidu（百度）、sogou（搜狗）、toutiao（头条搜索，额外兜底）
百科：zh.wikipedia（中文维基 API）、baike（百度百科）

产物（均在 data/raw/cn_slang/，不进仓库）
-----------------------------------------
  raw_terms.jsonl   统一中间格式，每行一条短事实（extractor 的输入）
  state.json        断点续跑状态 + 每平台统计
  events.jsonl      封禁/验证码/异常事件（审计用）
  raw/<platform>/   原始 HTML/JSON 缓存（sha1 命名）
  meta.json         本轮参数、限速、许可与风险说明

用法
----
    python etl/fetch_cn_slang.py --dry-run        # 只看种子与计划，不联网
    python etl/fetch_cn_slang.py --status         # 看已有进度/统计
    python etl/fetch_cn_slang.py                  # 正式抓取（可重复执行，断点续跑）
    python etl/fetch_cn_slang.py --max-seeds 20   # 小样本
    python etl/fetch_cn_slang.py --only wiki,bing --reset-state
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import http.cookiejar
import json
import random
import re
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "cn_slang"
RAW = OUT / "raw"
TERMS = OUT / "raw_terms.jsonl"
STATE = OUT / "state.json"
EVENTS = OUT / "events.jsonl"
META = OUT / "meta.json"

UA = ("drug-brand-crossref-research/0.1 (cn slang research; "
      "+https://github.com/fuarnos/drug-brand-crossref; contact: project repo)")
LANG = "zh"
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

# 平台封禁/验证码特征（命中即停用该平台）
BLOCK_MARKERS = (
    "验证码", "安全验证", "滑动验证", "访问过于频繁", "异常流量", "操作频繁",
    "请稍后再试", "拒绝访问", "Access Denied", "403 Forbidden", "captcha",
    "人机验证", "环境异常", "网络环境异常", "账号异常", "禁止访问",
)

# 毒品 / 娱乐性用药及其黑话：命中就丢弃（只统计，不落盘）
DRUG_SLANG = (
    "海洛因", "冰毒", "甲基苯丙胺", "可卡因", "cocaine", "MDMA", "摇头丸", "LSD",
    "麦角酸", "大麻", "大麻素", "四氢大麻酚", "THC", "GHB", "笑气", "一氧化二氮",
    "神仙水", "听话水", "迷奸水", "乖乖水", "开心水", "邮票", "糖果", "k粉", "K粉",
    "氯胺酮", "ketamine", "芬太尼", "fentanyl", "冰妹", "溜冰", "嗑药", "上头电子烟",
    "依托咪酯", "nps", "新精神活性物质", "罂粟", "鸦片", "吗啡", "methamphetamine",
    "heroin", "crack", "快克", "麻古", "麻果", "浴盐", "喵喵", "死藤水", "毒蘑菇",
    "迷幻蘑菇", "致幻剂", "兴奋剂滥用", "药物滥用", "成瘾性滥用", "吸食",
)

# 种子：docs/谷段需求队列.md 的覆盖目标（通用名 + 商品名/繁体品牌），
# 全部是合法药品；不加入任何毒品名。
SEEDS = [
    # --- GLP-1 / 减肥 ---
    "司美格鲁肽", "替尔泊肽", "利拉鲁肽", "减肥针", "瘦瘦针",
    # --- 退烧止痛 / 感冒 ---
    "对乙酰氨基酚", "布洛芬", "阿司匹林", "双氯芬酸", "塞来昔布",
    "泰诺", "芬必得", "美林", "白加黑", "康泰克", "999感冒灵", "连花清瘟",
    "扑热息痛", "必理通", "普拿疼", "必理痛",
    # --- 抗过敏 ---
    "氯雷他定", "西替利嗪", "开瑞坦", "扑尔敏",
    # --- 心血管 / 代谢 ---
    "氨氯地平", "缬沙坦", "氯吡格雷", "阿托伐他汀", "瑞舒伐他汀",
    "二甲双胍", "美托洛尔", "络活喜", "立普妥", "波立维",
    # --- 消化 ---
    "奥美拉唑", "铝碳酸镁", "多潘立酮", "蒙脱石散", "达喜", "吗丁啉", "思密达",
    # --- 抗感染 ---
    "阿莫西林", "头孢克肟", "阿奇霉素", "左氧氟沙星", "奥司他韦",
    "拜复乐", "达菲",
    # --- 呼吸 ---
    "氨溴索", "右美沙芬", "孟鲁司特", "布地奈德", "沙丁胺醇",
    # --- 皮肤/其他常见 ---
    "米诺地尔", "阿达帕林", "异维A酸", "地塞米松", "左甲状腺素",
    # --- 男科 / 神经 / 精神 ---
    "西地那非", "他达拉非", "达泊西汀", "万艾可", "希爱力",
    "地西泮", "安定", "哌甲酯", "莫达非尼", "佐匹克隆",
    # --- 中药/外用常见 ---
    "云南白药", "藿香正气", "阿莫西林克拉维酸",
]

# 每个种子用哪类查询模板（轮换，覆盖「俗称/外号/别名/别称/网络叫法」）
QUERY_TEMPLATES = [
    "{seed} 俗称",
    "{seed} 外号",
    "{seed} 别名 别称",
    "{seed} 又叫什么",
    "{seed} 网络叫法",
    "{seed} 民间叫法",
]

PLATFORMS = {
    # 直连平台（无登录尝试；被封即停用）
    "xiaohongshu": "小红书",
    "zhihu": "知乎",
    "weibo": "微博",
    "tieba": "贴吧",
    # 搜索兜底
    "bing": "必应搜索",
    "baidu": "百度搜索",
    "sogou": "搜狗搜索",
    "toutiao": "头条搜索",
    # 百科
    "wiki": "中文维基",
    "baike": "百度百科",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def clean_text(s: str, limit: int) -> str:
    """HTML → 纯文本；去标签/实体/压缩空白；截断到 limit（只保留短事实）。"""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?is)<br\s*/?>", " ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


# 搜索结果相关度：搜索引擎在反爬模式下会返回与查询无关的「购物清单/字典/翻译」类结果，
# 这些不是我们要的短事实，直接丢弃（不落盘、计入 irrelevant）。
JUNK_WORDS = ("购物清单", "翻译", "字典", "汉字", "笔画", "汉语字典", "好物", "优惠券",
              "淘宝", "京东优惠", "小说", "游戏", "彩票")
DRUG_HINTS = ("药", "片", "胶囊", "颗粒", "注射液", "注射剂", "口服液", "糖浆", "软膏",
              "乳膏", "栓", "喷雾", "滴眼", "适应症", "功效", "作用", "说明书", "处方",
              "OTC", "治疗", "临床", "成分", "别名", "俗称", "外号", "剂量", "用法")


def is_relevant(term: str, title: str, snippet: str) -> bool:
    blob = title + " " + snippet
    if any(w in blob for w in JUNK_WORDS):
        return False
    if term and term in blob:
        return True
    return any(w in blob for w in DRUG_HINTS)


def has_drug_slang(row: dict) -> str | None:
    """命中毒品/娱乐性用语则返回命中的词（调用方丢弃并计数）。"""
    blob = (row.get("title", "") + " " + row.get("snippet", "")).lower()
    for w in DRUG_SLANG:
        if w.lower() in blob:
            return w
    return None


# ---------------------------------------------------------------------------
# HTTP + 限速 + 缓存 + 封禁检测
# ---------------------------------------------------------------------------
class Crawler:
    def __init__(self, args: argparse.Namespace, state: dict) -> None:
        self.args = args
        self.state = state
        self.ctx = ssl.create_default_context()
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.warmed: set[str] = set()
        self.last_request = 0.0
        self.stats = state.setdefault("stats", {})
        self.done: set[str] = set(state.get("done", []))
        self.banned: dict[str, str] = state.setdefault("banned", {})
        self.dropped_drug = int(state.get("dropped_drug", 0))
        self.requests = int(state.get("requests", 0))
        self.stop_all = False
        for p in PLATFORMS:
            self.stats.setdefault(p, {"requests": 0, "http_ok": 0, "results": 0,
                                      "blocked": 0, "errors": 0, "no_result": 0})

    # --- 统计/事件 ---
    def event(self, platform: str, kind: str, detail: str) -> None:
        EVENTS.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now_iso(), "platform": platform,
                                "kind": kind, "detail": detail[:300]},
                               ensure_ascii=False) + "\n")

    def ban(self, platform: str, detail: str) -> None:
        if platform not in self.banned:
            self.banned[platform] = detail[:300]
            self.stats[platform]["blocked"] += 1
            self.event(platform, "blocked", detail)
            print(f"  !! {platform} 被封禁/验证码，停用该来源：{detail[:120]}", flush=True)
            self.save_state()
            if all(p in self.banned for p in PLATFORMS):
                self.stop_all = True
                self.event("all", "stop", "所有来源均被封禁，整体停止")
                print("  !! 所有来源均被封禁，整体停止抓取。", flush=True)

    # --- 限速 ---
    def wait(self) -> None:
        gap = random.uniform(self.args.min_delay, self.args.max_delay)
        elapsed = time.time() - self.last_request
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self.last_request = time.time()

    # --- 单次请求 ---
    def get(self, platform: str, url: str, referer: str | None = None,
            want_json: bool = False) -> tuple[int, str] | None:
        """返回 (status, text)；被封返回 None；出错记 errors 但不抛。"""
        if platform in self.banned or self.stop_all:
            return None
        if self.requests >= self.args.max_requests:
            return None
        self.wait()
        st = self.stats[platform]
        st["requests"] += 1
        self.requests += 1
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        try:
            with self.opener.open(req, timeout=self.args.timeout) as r:
                raw = r.read(self.args.max_bytes)
                text = raw.decode("utf-8", "replace")
                status = r.status
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read(2000).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            st["errors"] += 1
            if e.code in (403, 429) or any(m in body for m in BLOCK_MARKERS):
                self.ban(platform, f"HTTP {e.code}: {clean_text(body, 160)}")
                return None
            self.event(platform, "http_error", f"{e.code} {url[:180]}")
            return (e.code, body)
        except Exception as e:  # noqa: BLE001
            st["errors"] += 1
            self.event(platform, "error", f"{type(e).__name__}: {str(e)[:160]} {url[:160]}")
            return (0, "")

        # 200 也可能返回验证码/安全页：按特征识别
        probe = text[:6000]
        hit = next((m for m in BLOCK_MARKERS if m in probe), None)
        if hit and len(text) < 30000:      # 正常搜索结果页也偶含「验证码」字样，用体积+特征双判
            self.ban(platform, f"页面特征 {hit!r} (len={len(text)})")
            return None
        st["http_ok"] += 1
        # 缓存原始页（只缓存短事实抓取所需的页面，不无限增长）
        RAW.mkdir(parents=True, exist_ok=True)
        pdir = RAW / platform
        pdir.mkdir(parents=True, exist_ok=True)
        suffix = ".json" if want_json else ".html"
        (pdir / (sha1(url) + suffix)).write_text(text, encoding="utf-8")
        return status, text

    # --- 结果落盘 ---
    def emit(self, rows: list[dict]) -> int:
        kept = 0
        TERMS.parent.mkdir(parents=True, exist_ok=True)
        with TERMS.open("a", encoding="utf-8") as f:
            for row in rows:
                bad = has_drug_slang(row)
                if bad:
                    self.dropped_drug += 1
                    self.event(row.get("platform", "?"), "dropped_drug",
                               f"命中毒品/娱乐性用语 {bad!r}"[:300])
                    continue
                row["fetched_at"] = now_iso()
                row["lang"] = LANG
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                kept += 1
                self.stats[row["platform"]]["results"] += 1
        return kept

    def mark_done(self, key: str) -> None:
        self.done.add(key)
        self.state["done"] = sorted(self.done)

    def save_state(self) -> None:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        self.state.update({"stats": self.stats, "banned": self.banned,
                           "dropped_drug": self.dropped_drug,
                           "requests": self.requests,
                           "updated_at": now_iso()})
        STATE.write_text(json.dumps(self.state, ensure_ascii=False, indent=1),
                         encoding="utf-8")


# ---------------------------------------------------------------------------
# 各来源适配器：返回 [(term, url, title, snippet)]，不含 platform/fetched_at
# ---------------------------------------------------------------------------
RE_H2 = re.compile(r"(?is)<h2[^>]*>.*?</h2>")
RE_B_ALGO = re.compile(r'(?is)<li class="b_algo".*?</li>')


def parse_bing(html: str) -> list[tuple[str, str, str, str]]:
    out = []
    for m in RE_B_ALGO.finditer(html):
        block = m.group(0)
        tm = re.search(r"(?is)<h2[^>]*>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", block)
        if not tm:
            continue
        url = html_mod.unescape(tm.group(1))
        title = clean_text(tm.group(2), 120)
        sm = (re.search(r'(?is)<p class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', block)
              or re.search(r'(?is)<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>', block)
              or re.search(r"(?is)<p[^>]*>(.*?)</p>", block))
        snippet = clean_text(sm.group(1), 220) if sm else ""
        if title and url.startswith("http"):
            out.append((title, url, title, snippet))
    return out


def parse_toutiao(html: str) -> list[tuple[str, str, str, str]]:
    """头条搜索：结果以转义 JSON 内嵌（emphasized.title/summary）。"""
    out = []
    for m in re.finditer(r'"emphasized":\{"title":"(.*?)","summary":"(.*?)"\}', html):
        title = clean_text(m.group(1).replace("\\u003c", "<").replace("\\u003e", ">"), 120)
        snippet = clean_text(m.group(2).replace("\\u003c", "<").replace("\\u003e", ">"), 220)
        if title:
            out.append((title, "", title, snippet))
    # 去重保序
    seen, uniq = set(), []
    for row in out:
        if row[2] not in seen:
            seen.add(row[2])
            uniq.append(row)
    return uniq


def parse_wiki(term: str, data: dict) -> list[tuple[str, str, str, str]]:
    """中文维基 extracts：抓「又称/俗称/别名/又名/旧称/商品名/英文名」句。"""
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for pid, page in pages.items():
        if not isinstance(page, dict) or "missing" in page:
            continue
        title = page.get("title") or term
        url = "https://zh.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        extract = page.get("extract") or ""
        for sent in re.split(r"(?<=[。；;！!？?])", extract):
            if re.search(r"又称|俗称|别名|又名|旧称|曾用名|俗名|商品名|英文名|通用名|音译", sent):
                out.append((term, url, title, clean_text(sent, 220)))
        if not out and extract:
            out.append((term, url, title, clean_text(extract, 160)))
    return out[:4]


RE_JSON_FRAG = re.compile(r'\{[^{}]{0,400}\}|\{"[^"]+".{0,300}')


def parse_baidu(page: str) -> list[tuple[str, str, str, str]]:
    """百度搜索页解析（结果容器 class=result / h3+a）。

    百度 2026 版页面把大量水合 JSON 混进摘要，需先剥 JSON 片段再取句子；
    只保留含药品提示词或检索词的短句，拿不到就退化为标题。
    """
    out = []
    for m in re.finditer(r'(?is)<div[^>]+class="result[^"]*"[^>]*>(.*?)'
                         r'(?=<div[^>]+class="result|<div[^>]+id="page")', page):
        block = m.group(1)
        tm = re.search(r'(?is)<h3[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not tm:
            continue
        url = html_mod.unescape(tm.group(1))
        title = clean_text(tm.group(2), 120)
        if not title or not url.startswith("http"):
            continue
        txt = clean_text(block, 3000)
        txt = RE_JSON_FRAG.sub(" ", txt)
        txt = re.sub(r'["{}\[\],:]+', " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        parts = [p.strip() for p in re.split(r"(?<=[。；;！!？?])", txt) if len(p.strip()) >= 12]
        snippet = ""
        for cand in sorted(parts, key=len, reverse=True):
            if any(w in cand for w in DRUG_HINTS) and not cand.startswith(("它是", "这是")):
                snippet = cand[:220]
                break
        out.append((title, url, title, snippet))
    seen, uniq = set(), []
    for r in out:
        if r[1] not in seen:
            seen.add(r[1])
            uniq.append(r)
    return uniq


def parse_baike(html: str, term: str) -> list[tuple[str, str, str, str]]:
    title = term
    m = re.search(r"(?is)<title>(.*?)</title>", html)
    if m:
        title = clean_text(m.group(1), 80).replace("_百度百科", "")
    out = []
    for sent in re.split(r"(?<=[。；;])", clean_text(html, 8000)):
        if re.search(r"又称|俗称|别名|又名|旧称|曾用名|俗名|商品名", sent):
            out.append((term, "https://baike.baidu.com/item/" + urllib.parse.quote(term),
                        title, clean_text(sent, 220)))
    return out[:3]


def parse_weibo(data: dict) -> list[tuple[str, str, str, str]]:
    out = []
    cards = ((data.get("data") or {}).get("cards") or [])
    for card in cards:
        for mb in (card.get("card_group") or [card]):
            mblog = mb.get("mblog") or {}
            text = clean_text(mblog.get("text") or "", 200)
            if not text:
                continue
            mid = mblog.get("id") or ""
            url = f"https://m.weibo.cn/detail/{mid}" if mid else ""
            out.append((text, url, text[:80], text))
    return out[:10]


# ---------------------------------------------------------------------------
# 抓取主流程
# ---------------------------------------------------------------------------
def crawl_wiki(cw: Crawler, seeds: list[str]) -> None:
    """中文维基 API，一次最多 20 个 titles（批量，省请求）。"""
    batch = 20
    for i in range(0, len(seeds), batch):
        group = seeds[i:i + batch]
        key = "wiki:" + "|".join(group)
        if key in cw.done or "wiki" in cw.banned:
            continue
        params = {
            "action": "query", "prop": "extracts|redirects", "exintro": 1,
            "explaintext": 1, "titles": "|".join(group), "format": "json",
            "redirects": 1, "maxlag": 5,
        }
        url = "https://zh.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
        res = cw.get("wiki", url, want_json=True)
        if not res:
            continue
        try:
            data = json.loads(res[1])
        except json.JSONDecodeError:
            cw.event("wiki", "parse_error", key[:180])
            cw.mark_done(key)
            continue
        pages = (data.get("query") or {}).get("pages") or {}
        tmp = list(pages.keys())[:1]
        target_seed = group[0] if group else ""
        n = 0
        # extracts 批量返回时用 title→seed 近似映射（title 即条目名，通常等于种子）
        for pid, page in pages.items():
            if not isinstance(page, dict) or "missing" in page:
                continue
            title = page.get("title") or ""
            seed = next((s for s in group if s == title or s in title or title in s), title)
            rows = parse_wiki(seed, {"query": {"pages": {pid: page}}})
            n += cw.emit([{"term": r[0], "platform": "wiki", "url": r[1],
                          "title": r[2], "snippet": r[3]} for r in rows])
        if n == 0:
            cw.stats["wiki"]["no_result"] += 1
        cw.mark_done(key)
        cw.save_state()
        print(f"  [wiki] {len(group)} 个种子 → {n} 条短事实", flush=True)


def crawl_search(cw: Crawler, platform: str, term: str, template: str) -> int:
    query = template.format(seed=term)
    key = f"{platform}:{query}"
    if key in cw.done or platform in cw.banned:
        return 0
    enc = urllib.parse.quote(query)
    url = {
        "bing": f"https://www.bing.com/search?q={enc}&setlang=zh-Hans",
        "baidu": f"https://www.baidu.com/s?wd={enc}",
        "sogou": f"https://www.sogou.com/web?query={enc}",
        "toutiao": f"https://so.toutiao.com/search?keyword={enc}",
    }[platform]
    if platform == "bing" and platform not in cw.warmed and not cw.banned:
        cw.warmed.add(platform)
        cw.get("bing", "https://www.bing.com/?setlang=zh-Hans")   # 取 cookie，失败不致命
    res = cw.get(platform, url,
                 referer={"bing": "https://www.bing.com/", "baidu": "https://www.baidu.com/",
                          "sogou": "https://www.sogou.com/",
                          "toutiao": "https://so.toutiao.com/"}[platform])
    if not res:
        cw.mark_done(key)
        return 0
    status, text = res
    parser = {"bing": parse_bing, "toutiao": parse_toutiao}.get(platform)
    if parser is None:     # baidu / sogou 的解析只有兜底意义；命中验证码时上面已停用
        parser = lambda h: parse_bing(h)  # noqa: E731
    rows = parser(text)
    kept_rows = [(u, t, sn) for (_t, u, t, sn) in rows
                 if is_relevant(term, t, sn)]
    stats_p = cw.stats[platform]
    stats_p["irrelevant"] = stats_p.get("irrelevant", 0) + (len(rows) - len(kept_rows))
    if not kept_rows:
        cw.stats[platform]["no_result"] += 1
        cw.event(platform, "no_result", f"{query} len={len(text)} rows={len(rows)}")
        cw.mark_done(key)
        return 0
    n = cw.emit([{"term": term, "platform": platform, "url": u,
                  "title": t, "snippet": sn} for (u, t, sn) in kept_rows])
    cw.mark_done(key)
    cw.save_state()
    print(f"  [{platform}] {query!r} → {n} 条", flush=True)
    return n


def crawl_platform(cw: Crawler, platform: str, term: str) -> int:
    """直连平台：每个平台只用 1 个种子尝试一次，成功才继续多试（被封即停）。"""
    key = f"{platform}:{term}"
    if key in cw.done or platform in cw.banned:
        return 0
    enc = urllib.parse.quote(term)
    if platform == "xiaohongshu":
        url = f"https://www.xiaohongshu.com/search_result?keyword={enc}"
    elif platform == "zhihu":
        url = f"https://www.zhihu.com/search?type=content&q={enc}"
    elif platform == "weibo":
        url = ("https://m.weibo.cn/api/container/getIndex?containerid="
               + urllib.parse.quote(f"100103type=1&q={term}", safe=""))
    elif platform == "tieba":
        url = f"https://tieba.baidu.com/f/search/res?ie=utf-8&qw={enc}"
    else:
        return 0
    res = cw.get(platform, url,
                 referer={"xiaohongshu": "https://www.xiaohongshu.com/",
                          "zhihu": "https://www.zhihu.com/",
                          "weibo": "https://m.weibo.cn/",
                          "tieba": "https://tieba.baidu.com/"}[platform],
                 want_json=(platform == "weibo"))
    if not res:
        cw.mark_done(key)
        return 0
    status, text = res
    n = 0
    if platform == "weibo":
        try:
            data = json.loads(text)
            rows = parse_weibo(data)
            n = cw.emit([{"term": term, "platform": "weibo", "url": u,
                          "title": t, "snippet": s} for (_t, u, t, s) in rows])
        except json.JSONDecodeError:
            cw.stats["weibo"]["no_result"] += 1
    elif platform == "zhihu":
        rows = []
        for m in re.finditer(r"(?is)<h2[^>]*>(.*?)</h2>", text):
            t = clean_text(m.group(1), 120)
            if t:
                rows.append(t)
        n = cw.emit([{"term": term, "platform": "zhihu",
                      "url": f"https://www.zhihu.com/search?type=content&q={enc}",
                      "title": t, "snippet": ""} for t in rows[:10]])
    else:
        # 小红书/贴吧页面需 JS 或登录：只有能解析出结果时才计数
        rows = parse_bing(text) if platform == "tieba" else []
        n = cw.emit([{"term": term, "platform": platform, "url": u,
                      "title": t, "snippet": s} for (_t, u, t, s) in rows])
        if n == 0:
            cw.stats[platform]["no_result"] += 1
            cw.event(platform, "no_result", f"{term} len={len(text)}")
    cw.mark_done(key)
    cw.save_state()
    print(f"  [{platform}] {term} → {n} 条", flush=True)
    return n


def crawl_baike(cw: Crawler, term: str) -> int:
    key = f"baike:{term}"
    if key in cw.done or "baike" in cw.banned:
        return 0
    url = "https://baike.baidu.com/item/" + urllib.parse.quote(term)
    res = cw.get("baike", url, referer="https://baike.baidu.com/")
    if not res:
        cw.mark_done(key)
        return 0
    rows = parse_baike(res[1], term)
    n = cw.emit([{"term": term, "platform": "baike", "url": u, "title": t,
                  "snippet": s} for (_t, u, t, s) in rows])
    if n == 0:
        cw.stats["baike"]["no_result"] += 1
    cw.mark_done(key)
    cw.save_state()
    print(f"  [baike] {term} → {n} 条", flush=True)
    return n


def reparse_cached(args: argparse.Namespace, state: dict) -> int:
    """离线重解析 data/raw/cn_slang/raw/baidu/*.html → 补写 raw_terms（不联网）。"""
    files = sorted((RAW / "baidu").glob("*.html"))
    if not files:
        print("没有百度缓存页可重解析")
        return 1
    existing: set[tuple[str, str]] = set()
    if TERMS.exists():
        for line in TERMS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing.add((r.get("platform", ""), r.get("url", "")))
    st = state.setdefault("stats", {}).setdefault(
        "baidu", {"requests": 0, "http_ok": 0, "results": 0, "blocked": 0,
                  "errors": 0, "no_result": 0})
    kept_total = 0
    for f in files:
        page = f.read_text(encoding="utf-8")
        tm = re.search(r"<title>(.*?)</title>", page)
        title = clean_text(tm.group(1), 120).replace("_百度搜索", "") if tm else ""
        seed = re.split(r"[\s　]", title.strip())[0] if title else ""
        rows = parse_baidu(page)
        kept = []
        for (t, u, ttl, sn) in rows:
            if (u in {x[1] for x in existing}):
                continue
            if not is_relevant(seed, ttl, sn):
                continue
            kept.append({"term": seed, "platform": "baidu", "url": u,
                         "title": ttl, "snippet": sn})
        for row in kept:
            if has_drug_slang(row):
                state["dropped_drug"] = int(state.get("dropped_drug", 0)) + 1
                continue
            row["fetched_at"] = now_iso()
            row["lang"] = LANG
            with TERMS.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            existing.add(("baidu", row["url"]))
            st["results"] += 1
            kept_total += 1
        print(f"  [reparse] {f.name} ({title or '?'}) → {len(kept)} 条")
    st["http_ok"] = max(st.get("http_ok", 0), len(files))
    state["updated_at"] = now_iso()
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"重解析完成：新增 {kept_total} 条；raw_terms 总行数 "
          f"{sum(1 for _ in TERMS.open(encoding='utf-8'))}")
    return 0


def load_state(reset: bool) -> dict:
    if reset or not STATE.exists():
        return {"done": [], "stats": {}, "banned": {}, "dropped_drug": 0, "requests": 0}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"done": [], "stats": {}, "banned": {}, "dropped_drug": 0, "requests": 0}


def print_status(state: dict) -> None:
    print("== 抓取状态 ==")
    print(f"已完成查询 {len(state.get('done') or []):,}；累计请求 {state.get('requests', 0):,}；"
          f"丢弃(毒品/娱乐性) {state.get('dropped_drug', 0):,}")
    if EVENTS.exists():
        lines = EVENTS.read_text(encoding="utf-8").strip().splitlines()
        print(f"事件 {len(lines):,} 条（{EVENTS.relative_to(ROOT)}）")
    for p, st in (state.get("stats") or {}).items():
        print(f"  {PLATFORMS.get(p, p):<8} req={st.get('requests', 0):<4} ok={st.get('http_ok', 0):<4} "
              f"results={st.get('results', 0):<5} blocked={st.get('blocked', 0):<2} "
              f"errors={st.get('errors', 0)}")
    banned = state.get("banned") or {}
    if banned:
        print("封禁/验证码来源:")
        for p, why in banned.items():
            print(f"  - {PLATFORMS.get(p, p)}: {why[:120]}")
    if TERMS.exists():
        print(f"raw_terms.jsonl: {sum(1 for _ in TERMS.open(encoding='utf-8')):,} 行")


def main() -> int:
    ap = argparse.ArgumentParser(description="中文互联网药品俗名抓取器（合法药品；毒品黑话丢弃）")
    ap.add_argument("--dry-run", action="store_true", help="只打印种子与计划，不联网")
    ap.add_argument("--status", action="store_true", help="查看进度/统计后退出")
    ap.add_argument("--max-seeds", type=int, default=0, help="最多处理多少个种子（0=全部）")
    ap.add_argument("--max-requests", type=int, default=170, help="本轮请求上限（默认 170）")
    ap.add_argument("--min-delay", type=float, default=3.0)
    ap.add_argument("--max-delay", type=float, default=5.0)
    ap.add_argument("--timeout", type=int, default=25)
    ap.add_argument("--max-bytes", type=int, default=3_000_000)
    ap.add_argument("--only", default="", help="只跑这些来源，逗号分隔：wiki,bing,toutiao,platforms,baike")
    ap.add_argument("--reset-state", action="store_true", help="清空断点状态（重头抓）")
    ap.add_argument("--no-platforms", action="store_true", help="跳过小红书/知乎/微博/贴吧直连尝试")
    ap.add_argument("--reparse", action="store_true",
                    help="离线重解析已缓存页面（补解析器结构变化漏掉的结果），不联网")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    state = load_state(args.reset_state)
    if args.reparse:
        return reparse_cached(args, state)
    if args.status:
        print_status(state)
        return 0

    seeds = SEEDS[: args.max_seeds] if args.max_seeds else SEEDS
    if args.reset_state and TERMS.exists():
        backup = TERMS.with_suffix(".jsonl.bak")
        TERMS.replace(backup)
        print(f"已把旧 raw_terms 移到 {backup.name}")
    if args.dry_run:
        print(f"种子 {len(seeds)} 个；来源 {len(PLATFORMS)} 个；"
              f"限速 {args.min_delay}–{args.max_delay}s；请求上限 {args.max_requests}")
        print("来源计划：wiki(批量 20/请求) → bing(每种子 1 查) → toutiao(每种子 1 查，可选)"
              " → xiaohongshu/zhihu/weibo/tieba(各试 1 次，封禁即停) → baibu/sogou/百度百科(尝试即记录)")
        print("种子样例：", "、".join(seeds[:12]), "…")
        print(f"输出：{TERMS.relative_to(ROOT)} / {STATE.relative_to(ROOT)} / {RAW.relative_to(ROOT)}/")
        state.update({"stats": {}, "done": [], "banned": {}, "dropped_drug": 0, "requests": 0})
        print_status(state)
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    META.write_text(json.dumps({
        "purpose": "中文互联网药品俗名抓取（只收合法药品；毒品/娱乐性用药丢弃）",
        "authorization": "用户 2026-10-26 明确授权尝试小红书/知乎/微博/贴吧；ToS 风险由用户承担。",
        "discipline": "限速 3–5s 随机抖动；不登录、不绕验证码、不破解签名；403/验证码即停该来源并记事件。",
        "license_note": "只存短事实（叫法/标题/摘要片段/URL/日期）；平台内容版权归原平台与作者，"
                        "站外再发布只使用「叫法」这一事实并链回原页，不转载正文。",
        "raw_dir": str(OUT.relative_to(ROOT)),
        "started_at": now_iso(),
        "args": vars(args),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    cw = Crawler(args, state)
    print(f"开始抓取：种子 {len(seeds)}，限速 {args.min_delay}–{args.max_delay}s，"
          f"本轮请求上限 {args.max_requests}（已用 {cw.requests}）", flush=True)
    try:
        only = {s.strip() for s in args.only.split(",") if s.strip()}
        if not only or "wiki" in only:
            crawl_wiki(cw, seeds)
        search_targets = [p for p in ("bing", "toutiao") if not only or p in only]
        for term in seeds:
            if cw.stop_all or cw.requests >= args.max_requests:
                break
            tmpl = QUERY_TEMPLATES[seeds.index(term) % len(QUERY_TEMPLATES)]
            for platform in search_targets:
                if platform in cw.banned:
                    continue
                crawl_search(cw, platform, term, tmpl)
                if cw.stop_all or cw.requests >= args.max_requests:
                    break
        if not only or "baidu" in only or "sogou" in only:
            for platform in [p for p in ("baidu", "sogou") if not only or p in only]:
                for term in seeds[:3]:      # 尝试量控制在 3 个种子内，封禁即停
                    if cw.stop_all:
                        break
                    crawl_search(cw, platform, term, QUERY_TEMPLATES[0])
        if not only or "baike" in only:
            for term in seeds[:3]:
                if cw.stop_all:
                    break
                crawl_baike(cw, term)
        platforms = [p for p in ("xiaohongshu", "zhihu", "weibo", "tieba")
                     if not only or "platforms" in only or p in only]
        if not args.no_platforms:
            for platform in platforms:
                if cw.stop_all:
                    break
                crawl_platform(cw, platform, seeds[0] if seeds else "布洛芬")
                if platform in cw.banned:
                    continue
                crawl_platform(cw, platform, seeds[1] if len(seeds) > 1 else "布洛芬")
    finally:
        cw.save_state()
        print_status({**cw.state, "stats": cw.stats, "banned": cw.banned,
                      "dropped_drug": cw.dropped_drug, "requests": cw.requests})
        print(f"本轮结束；raw_terms: {TERMS.relative_to(ROOT) if TERMS.exists() else '(空)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
