"""排序冒烟：客户端检索结果的**基名优先**规则（G3 方案 b）仍然成立 —— 与 `lib/search.py` 同一条规则。

为什么要有这个脚本
------------------
v0.13.2 把「同名下基名条目优先于盐型条目」在两端**各实现了一遍**：服务端
`lib/search.py::SearchIndex._prefer_base_ingredient`，客户端 `site/build.py` 的 APP_JS
`g3PreferBase()`。本机没有 node，客户端那一半过去只能人工开浏览器点 5 条
（plavix / glucophage / cipralex / viagra / imodium）看首行 —— 人工冒烟不可复跑、换个人就漏一项。
本脚本把那次人工冒烟变成可重复门禁，两层断言：

**① 规则层（合成用例，直接调页面里的 `g3PreferBase`）**
   在真浏览器里给客户端函数喂固定的合成 hits，断言换位结果。这一层不依赖数据，
   规则被改坏 / 被删 / 与 `lib/search.py` 语义分叉时立刻红（见 `RULE_CASES`）。

**② 数据层（8 条真实查询，读渲染后的结果表）**
   `index.html?lang=en` → 页内提交查询（等同用户输入）→ 读 `#reswrap table.res.rows tbody tr.br`
   的「成分」列（`td.c-ing`）→ 断言**首条候选卡的基名**是期望成分（5 条盐型/基名对照 + 3 条反例）。

**③ 词表一致性（页面 `G3_SALT_WORDS` vs `lib/search.py::SALT_WORDS`）**
   「两端同一口径」要求去盐词表是同一套；客户端少一个盐型词，那条记录在页面上就不会被换位
   （服务端会）。本项默认只 WARN（词表归 `site/build.py` 的负责工位改），`--strict-words` 才判红。

判定口径（**别按整串相等判**）
----------------------------
客户端索引是**一个名字 key 一条**，`x`（成分列）是该名字下所有产品的成分**并集**，例如
plavix 首行是 `Clopidogrel + Clopidogrel Hydrogen Sulfate`（有的市场登记基名、有的登记盐型）；
而且 `site/build.py::_sub_base_map()` 在构建期已经把大部分盐型折成了基名（所以 glucophage 的 9 行
全叫 `Metformin`，盐型条目根本不再单独出现）。因此判定按客户端 `g3BaseKey()` 的同一口径把成分串
**折成基名集合**再比：`Clopidogrel + Clopidogrel Hydrogen Sulfate` → `{clopidogrel}` == 期望 → 过。
另外两条结构性断言/观察保护「只换位、不合并、不丢条目」的语义：
   · 组内不变量：同一基名组内，「是盐型」标记在行序里只能 非盐 → 盐，不许回退（= 稳定分区语义）；
   · 盐型可见性：盐型字样在这条查询的候选集里完全消失时记 WARN（构建期折名是设计选择，不判红）；
   · 误报警示：首行是「同一成分基名+盐型」并集却挂了 severe「同名不同药」徽章时记 WARN
     （2026-11-17 实测 Plavix / Cipralex 就是，根因见报告 §5.2，归 `site/build.py` 工位）。

查询集（`CASES`）
----------------
1. 盐型/基名对照 5 条（v0.13.2 人工冒烟过的那 5 条）：plavix → clopidogrel、glucophage → metformin、
   cipralex → escitalopram、viagra → sildenafil、imodium → loperamide。
2. 反例 3 条（本来没有盐型/基名之争，规则不许改动顺序）：tylenol → acetaminophen、
   amlodipine → amlodipine、泰诺 → 复方 Acetaminophen + Pseudoephedrine + Dextromethorphan + Chlorphenamine。
   期望值不是从页面抄的：成分按 `data/drugs.db` 现查、排序与 `lib/search.py` 服务端结果对齐，
   命令与输出写在 reports/2026-11-17-q10-ui-sort-smoke.md。

退出码
------
    0 = 全部通过，或 SKIP（找不到本机 Chrome / `site/dist` 不存在 / 浏览器·CDP 起不来 ——
        照 `ui_surface_check.py` 的惯例，环境缺失不判红）；词表漂移默认只 WARN，不影响退出码；
    1 = 有 FAIL（打印「哪条查询、哪一项、期望什么、实测什么」；`--strict-words` 时词表漂移也算）；
    2 = 采集异常（core 索引等不到 / 页面没有结果表 / CDP 中途掉线）—— 不是排序结论，需重跑。

用法
----
    python deploy/ui_sort_smoke.py                                    # 扫 site/dist（内置静态服务）
    python deploy/ui_sort_smoke.py --dist .tmp/dist-r1r2              # 扫别的产物目录
    python deploy/ui_sort_smoke.py --base-url http://127.0.0.1:8000/  # 扫已起的服务
    python deploy/ui_sort_smoke.py --only plavix,tylenol              # 只跑数据层指定查询（规则层照跑）
    python deploy/ui_sort_smoke.py --no-data                          # 只跑规则层（秒级）
    python deploy/ui_sort_smoke.py --no-rules                         # 只跑数据层
    python deploy/ui_sort_smoke.py --strict-words                     # 两端去盐词表不一致也判红
    python deploy/ui_sort_smoke.py --deep-link                        # 数据层每条查询各自导航（慢，排查用）
    python deploy/ui_sort_smoke.py --override index.html=.tmp/x.html   # 用补丁页验证「门禁会不会红」
    python deploy/ui_sort_smoke.py --json .tmp/q10/ui-sort.json       # 结果落 JSON（留证）
    python deploy/ui_sort_smoke.py --list                             # 只列查询集，不跑

只读：产物一律只读打开（复用 `ui_surface_check.Site`），Chrome 用户目录放系统临时目录；
不改 `site/dist`、不碰 `site/build.py`、不连 `data/drugs.db`（CI 无库也能跑）。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 复用现成的静态服务 / CDP / 浏览器启动（同目录脚本，无第三方依赖）：
#   ui_surface_check      —— Site（只读静态服务，支持 --override 补丁页）、CDP、launch_chrome、_page_ws
#   ui_interaction_smoke  —— pick_browsers（Chrome 起不来时退 Edge，同为 CDP）
from ui_interaction_smoke import pick_browsers  # noqa: E402
from ui_surface_check import CDP, Site, _page_ws, launch_chrome  # noqa: E402

DEFAULT_DIST = ROOT / "site" / "dist"

# 去盐词表：**原样照抄** `lib/search.py::SALT_WORDS`（= `site/build.py` APP_JS 里 `G3_SALT_WORDS`
# 的同一口径）。注意 `site/build.py` 构建期的 `_sub_base_map()` 用的是另一份**较窄**的词表
# （不含 hydrogen / oxalate），所以页面上仍会看到「… Hydrogen Sulfate」这类条目 —— 这正是客户端
# 规则要换位的对象。跑起来会再和 `lib.search` 比对一次，漂移就打印警告。
SALT_WORDS = frozenset({
    "hydrochloride", "hydrobromide", "sodium", "potassium", "calcium", "magnesium",
    "phosphate", "sulfate", "sulphate", "citrate", "tartrate", "maleate", "fumarate",
    "oxalate", "succinate", "malate", "glutamate", "aspartate", "lactate", "acetate", "carbonate",
    "bicarbonate", "chloride", "iodide", "bromide", "nitrate", "oxide", "hydroxide",
    "hydrate", "dihydrate", "trihydrate", "monohydrate", "sesquihydrate", "hemihydrate",
    "tetrahydrate", "anhydrous", "hydrogen",
    "mesilate", "mesylate", "besylate", "besilate", "benzoate", "trometamol",
    "tromethamine", "disodium", "dipotassium", "dicalcium",
    "monohydrochloride", "dihydrochloride", "lysine", "arginine", "gluconate",
    "digluconate", "heptanoate", "enantate", "decanoate", "palmitate", "stearate",
    "oleate", "laurate", "propionate", "butyrate", "valerate", "undecylenate",
    "cypionate", "phenylpropionate", "nitrite", "sulfite", "bisulfate", "edetate",
    "gluceptate", "glycinate", "asparto", "pamoate", "embonate", "hyclate",
    "edisylate", "estolate", "taurate", "xinafoate", "furoate", "aceponate",
    "dipropionate", "diacetate", "dibenzoate", "pivalate", "tebutate",
})
# g3BaseKey() 的「单字短词 / 元素名」护栏：这类分段算不出可靠基名，拆组时跳过。
SALT_ELEMENTS = frozenset({"sodium", "potassium", "calcium", "magnesium", "lithium",
                           "iron", "zinc", "copper", "aluminium", "aluminum", "barium",
                           "selenium"})
_RE_NONALNUM = re.compile(r"[^a-z0-9]+")

# ① 规则层：直接喂给页面里的 `g3PreferBase(hits)`，断言换位结果。
#    hits 元素形状 = [score, tier, entry]，只有 entry.x（成分串）参与规则。
#    盐型词专门选**两端词表都有**的（hydrochloride / sulfate / citrate / oxalate），
#    这样这条用例只验「换位逻辑」；两端词表本身的差异由 ③ 词表一致性单独报告。
RULE_CASES: list[dict] = [
    {
        "name": "盐型在前 → 换位成基名在前（组外不动）",
        "hits": ["Clopidogrel Hydrochloride", "Clopidogrel", "Ibuprofen"],
        "expect": ["Clopidogrel", "Clopidogrel Hydrochloride", "Ibuprofen"],
    },
    {
        "name": "全是盐型 → 顺序不变（没有基名条目可比）",
        "hits": ["Clopidogrel Hydrochloride", "Clopidogrel Sulfate"],
        "expect": ["Clopidogrel Hydrochloride", "Clopidogrel Sulfate"],
    },
    {
        "name": "不同基名组不跨组重排",
        "hits": ["Sildenafil Citrate", "Metformin", "Sildenafil"],
        "expect": ["Sildenafil", "Metformin", "Sildenafil Citrate"],
    },
    {
        "name": "复方：基名组合优先于盐型组合（只比对应成分）",
        "hits": ["Clopidogrel Hydrochloride + Aspirin", "Clopidogrel + Aspirin"],
        "expect": ["Clopidogrel + Aspirin", "Clopidogrel Hydrochloride + Aspirin"],
    },
    {
        "name": "组内换位不影响别的行的相对顺序",
        "hits": ["Aspirin", "Clopidogrel Hydrochloride", "Clopidogrel", "Ibuprofen"],
        "expect": ["Aspirin", "Clopidogrel", "Clopidogrel Hydrochloride", "Ibuprofen"],
    },
    {
        "name": "只有基名条目 → 顺序不变",
        "hits": ["Metformin", "Sildenafil"],
        "expect": ["Metformin", "Sildenafil"],
    },
    {
        "name": "基名+盐型并集条目单独成组（与 lib/search.py 的 tuple 口径一致，不换位）",
        "hits": ["Clopidogrel + Clopidogrel Hydrogen Sulfate", "Clopidogrel"],
        "expect": ["Clopidogrel + Clopidogrel Hydrogen Sulfate", "Clopidogrel"],
    },
]

# ② 数据层：`first` = 首条候选卡折成基名后应有的成分组；`salt_seen` 只用于 WARN 观察
#    （盐型字样在这条查询里彻底消失 → 记一句观察，不判红）。
CASES: list[dict] = [
    {
        "q": "plavix", "kind": "salt-base", "first": "clopidogrel",
        "salt_seen": ["clopidogrel bisulfate", "clopidogrel hydrogen sulfate"],
        "note": "同名下基名与两种盐型并存，首行基名必须是 clopidogrel",
    },
    {
        "q": "glucophage", "kind": "salt-base", "first": "metformin",
        "salt_seen": ["metformin hydrochloride"],
        "note": "盐酸二甲双胍条目不占多数 → 首行基名必须是 metformin",
    },
    {
        "q": "cipralex", "kind": "salt-base", "first": "escitalopram",
        "salt_seen": ["escitalopram oxalate"],
        "note": "草酸艾司西酞普兰 → 首行基名必须是 escitalopram",
    },
    {
        "q": "viagra", "kind": "salt-base", "first": "sildenafil",
        "salt_seen": ["sildenafil citrate"],
        "note": "枸橼酸西地那非 → 首行基名必须是 sildenafil",
    },
    {
        "q": "imodium", "kind": "salt-base", "first": "loperamide",
        "salt_seen": ["loperamide hydrochloride"],
        "note": "盐酸洛哌丁胺 → 首行基名必须是 loperamide",
    },
    {
        "q": "tylenol", "kind": "control", "first": "acetaminophen",
        "salt_seen": [],
        "note": "反例：只有基名成分，规则不许改动顺序",
    },
    {
        "q": "amlodipine", "kind": "control", "first": "amlodipine",
        "salt_seen": [],
        "note": "反例：通用名查询，首行基名仍是 amlodipine",
    },
    {
        "q": "泰诺", "kind": "control",
        "first": "acetaminophen + pseudoephedrine + dextromethorphan + chlorphenamine",
        "salt_seen": [],
        "note": "反例：中文复方名（4 段成分），首行必须是这一组、不许被盐型规则改顺序",
    },
]

# 规则层探针：在页面里跑 `g3PreferBase`，返回每个用例的实测顺序。
RULE_PROBE_JS = r"""(function(cases){
  if(typeof g3PreferBase !== 'function') return JSON.stringify({missing: true});
  function run(ings){
    var hits = ings.map(function(s, i){ return [1, 'exact', {x: s, k: 'synthetic-' + i}]; });
    g3PreferBase(hits);
    return hits.map(function(h){ return h[2].x; });
  }
  return JSON.stringify({missing: false, results: cases.map(function(c){
    return {name: c.name, expect: c.expect, got: run(c.hits)};
  })});
})(%s)"""

# 数据层探针：普通名字查询走扁平表（`flatTableHTML`），一行 = 一个名字 key；
# 行序就是 hits 排序后的顺序（`g3PreferBase` 在 render() 里刚换过位）。
PROBE_JS = r"""(function(){
  var rows = Array.prototype.slice.call(
    document.querySelectorAll('#reswrap table.res.rows tbody tr.br'));
  function txt(el){ return el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : ''; }
  var all = rows.map(function(r){
    var ing = r.querySelector('td.c-ing');
    var brand = r.querySelector('td.c-brand');
    var badges = Array.prototype.slice.call(r.querySelectorAll('.badge,.tag')).map(
      function(b){ return {cls: b.className || '', txt: txt(b)}; });
    return {ing: txt(ing), brand: txt(brand).slice(0, 44),
            k: r.getAttribute('data-k') || '', badges: badges};
  });
  var meta = document.getElementById('meta');
  var h1 = document.getElementById('h1');
  var q = document.getElementById('q');
  return JSON.stringify({
    rows: rows.length,
    all: all.slice(0, 40),
    meta: txt(meta).slice(0, 140),
    h1: txt(h1),
    box: q ? String(q.value || '') : '',
    idx_ready: (typeof IDX_READY !== 'undefined') ? IDX_READY : null,
    idx_len: (typeof IDX !== 'undefined' && IDX) ? IDX.length : null
  });
})()"""

# core 索引是否已解码完成（`let IDX_READY` 是脚本顶层词法变量，Runtime.evaluate 里能按名访问）。
READY_JS = "typeof IDX_READY !== 'undefined' && IDX_READY === true"

# ③ 词表一致性：页面里的 `G3_SALT_WORDS`（客户端去盐词表）与 lib/search.py 的 `SALT_WORDS` 比。
WORDLIST_JS = ("JSON.stringify(typeof G3_SALT_WORDS !== 'undefined' ? G3_SALT_WORDS : null)")

# 页内提交查询（等同用户输入后点「搜索」）：走客户端真实入口，不伪造 DOM。
SUBMIT_JS = r"""(function(q){
  var box = document.getElementById('q');
  var go = document.getElementById('qgo');
  if(!box) return 'NO_INPUT';
  box.value = q;
  box.dispatchEvent(new Event('input', {bubbles: true}));
  if(go){ go.click(); return 'CLICK'; }
  box.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
  return 'ENTER';
})"""


# ── 基名（与客户端 g3BaseName / g3BaseKey 同口径）─────────────────────────────
def _toks(text: str) -> list[str]:
    return [t for t in _RE_NONALNUM.split((text or "").lower()) if t]


def base_parts(ing: str) -> list[str]:
    """成分串按 ` + ` 拆段，每段去掉尾部盐型/水合物词，返回基名分段。"""
    out: list[str] = []
    for seg in re.split(r"\s*\+\s*", (ing or "")):
        toks = _toks(seg)
        while len(toks) > 1 and toks[-1] in SALT_WORDS:
            toks.pop()
        out.append(" ".join(toks))
    return out


def base_key(ing: str) -> frozenset[str]:
    """基名组合（去重、无序）—— 数据层判定用的是这个集合，不是原始成分串。"""
    return frozenset(p for p in base_parts(ing) if p)


def group_key(ing: str) -> str:
    """复刻 g3BaseKey：拆段基名排序后拼串；单字短词 / 元素名分段 → 空串（算不出可靠基名）。"""
    parts = base_parts(ing)
    for p in parts:
        one = p.split(" ")
        if len(one) == 1 and p and (len(one[0]) < 4 or one[0] in SALT_ELEMENTS):
            return ""
    return "|".join(sorted(p for p in parts if p))


def is_salt(ing: str) -> bool:
    """该行成分里是否含盐型/水合物词（复刻 g3IsSalt）。"""
    return any(t in SALT_WORDS for t in _toks(ing))


# ── 浏览器驱动 ─────────────────────────────────────────────────────────────
def goto(cdp: CDP, url: str) -> None:
    """导航并等 load 事件；先 `1` 探活（浏览器死了这里会抛，由调用方判采集异常）。"""
    cdp.eval("1")
    cdp.events.clear()
    cdp.call("Page.navigate", url=url)
    cdp.wait_event("Page.loadEventFired", 60)


def wait_for(cdp: CDP, expr: str, timeout: float, interval: float = 0.2) -> bool:
    """轮询一段 JS 表达式直到为真；超时返回 False（不抛）。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cdp.eval(expr):
                return True
        except Exception:  # noqa: BLE001 —— 页面切换中途求值失败，下一轮再试
            pass
        time.sleep(interval)
    return False


def probe(cdp: CDP) -> dict:
    raw = cdp.eval(PROBE_JS)
    return json.loads(raw) if raw else {}


def _free_port() -> int:
    """要一个当前空闲的本机端口给 Chrome DevTools（ci_checks 并行跑三个浏览器时不抢固定端口）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def boot(browsers: list[Path]) -> tuple[object, CDP, Path]:
    """起第一个能起来的 Chromium 系浏览器（Chrome → Edge），返回 (进程, CDP, 用户目录)。

    与 `ui_interaction_smoke.start_browser` 同一套路，差别只有「每个浏览器现取一个空闲端口」：
    全量 `ci_checks` 会把 ui-surface(9427) / first-screen(9431) / 本脚本 并行跑，写死端口会互相抢。
    """
    errors: list[str] = []
    for exe in browsers:
        profile = Path(tempfile.mkdtemp(prefix="ui-sort-"))
        port = _free_port()
        proc = None
        try:
            proc = launch_chrome(exe, port, profile)
            cdp = CDP(_page_ws(port))
            cdp.call("Page.enable")
            cdp.call("Runtime.enable")
            return proc, cdp, profile
        except Exception as exc:  # noqa: BLE001 —— 换下一个浏览器
            errors.append(f"{exe.name}: {str(exc)[:120]}")
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    pass
            shutil.rmtree(profile, ignore_errors=True)
            continue
    raise RuntimeError("CDP 不可用：" + "；".join(errors or ["找不到 Chrome / Edge"]))


# ── ① 规则层 ───────────────────────────────────────────────────────────────
def check_rules(cdp: CDP) -> list[dict]:
    """在真浏览器里调客户端的 `g3PreferBase`，逐条比对合成用例的换位结果。"""
    raw = cdp.eval(RULE_PROBE_JS % json.dumps(RULE_CASES, ensure_ascii=False))
    data = json.loads(raw) if raw else {}
    if data.get("missing"):
        return [{"id": "rule", "name": "页面里有 g3PreferBase()", "ok": False,
                 "expect": "v0.13.2 起的产物应导出该函数",
                 "got": "未定义",
                 "detail": "页面里没有 g3PreferBase()（产物太旧或规则被删）"}]
    out: list[dict] = []
    for item in data.get("results") or []:
        ok = item.get("got") == item.get("expect")
        out.append({
            "id": "rule", "name": item.get("name"), "ok": ok,
            "expect": item.get("expect"), "got": item.get("got"),
            "detail": (f"{item.get('name')}：{item.get('got')}" if ok else
                       f"{item.get('name')}：期望 {item.get('expect')}，实测 {item.get('got')}"),
        })
    return out


# ── ③ 词表一致性 ───────────────────────────────────────────────────────────
def check_wordlist(cdp: CDP) -> dict:
    """比「页面里的去盐词表」和「lib/search.py 的去盐词表」。

    两端规则要「同一口径」，词表就得是同一套：客户端少了某个盐型词，那条记录在页面上就不会被
    换位（服务端会）。本项默认只报 WARN（词表对齐归 `site/build.py` 的负责工位），
    加 `--strict-words` 才阻塞。
    """
    raw = cdp.eval(WORDLIST_JS)
    page_words = json.loads(raw) if raw else None
    server_words = set(SALT_WORDS)
    rec: dict = {"page": sorted(page_words or []), "server": sorted(server_words),
                 "missing_in_page": [], "extra_in_page": [], "ok": True, "detail": ""}
    if not page_words:
        rec.update({"ok": False, "skipped": True,
                    "detail": "页面里没有 G3_SALT_WORDS（产物太旧 / 变量改名），词表一致性跳过"})
        return rec
    page_set = set(page_words)
    rec["missing_in_page"] = sorted(server_words - page_set)
    rec["extra_in_page"] = sorted(page_set - server_words)
    if rec["missing_in_page"] or rec["extra_in_page"]:
        rec["ok"] = False
        parts = []
        if rec["missing_in_page"]:
            parts.append(f"客户端缺 {len(rec['missing_in_page'])} 词 {rec['missing_in_page']}")
        if rec["extra_in_page"]:
            parts.append(f"客户端多 {len(rec['extra_in_page'])} 词 {rec['extra_in_page']}")
        rec["detail"] = ("页面 G3_SALT_WORDS %d 词 vs lib/search.py %d 词；"
                         % (len(page_set), len(server_words))) + "；".join(parts)
    else:
        rec["detail"] = f"两端词表一致（{len(page_set)} 词）"
    return rec


# ── ② 数据层 ───────────────────────────────────────────────────────────────
def validate_rows(case: dict, rows: list[dict]) -> dict:
    """对一条查询的行数据做断言，返回 {status, checks, warnings, detail}。"""
    checks: list[dict] = []
    first_ing = rows[0]["ing"] if rows else ""
    got_base = base_key(first_ing)
    want_base = base_key(case["first"])
    checks.append({
        "id": "first-base", "ok": bool(got_base) and got_base == want_base,
        "expect": sorted(want_base), "got": sorted(got_base),
        "detail": f"首行成分={first_ing!r}（基名 {sorted(got_base)}，期望 {sorted(want_base)}）",
    })

    # 组内不变量：同一基名组的「盐型」标记在行序里只能 非盐 → 盐，不许回退。
    bad: list[str] = []
    groups: dict[str, list[bool]] = {}
    for i, r in enumerate(rows):
        g = group_key(r["ing"])
        if not g:
            continue
        salt = is_salt(r["ing"])
        flags = groups.setdefault(g, [])
        if flags and flags[-1] and not salt:
            bad.append(f"第 {i + 1} 行「{r['ing']}」是非盐型，却排在盐型行之后（组 {g}）")
        flags.append(salt)
    checks.append({
        "id": "salt-order", "ok": not bad, "expect": "非盐型行在盐型行之前",
        "got": bad[:3],
        "detail": "组内盐型/基名顺序未回退" if not bad else "；".join(bad[:3]),
    })

    warnings: list[str] = []
    joined = " | ".join(r["ing"].lower() for r in rows)
    for s in case.get("salt_seen") or []:
        if s.lower() not in joined:
            warnings.append(f"候选集里看不到盐型字样「{s}」（构建期 _sub_base_map 已折成基名，"
                            "属设计选择；数据变动后这条会重新出现）")
    # 误报警示观察：首行成分是「同一成分的基名 + 盐型」并集，却挂了 severe「同名不同药」徽章。
    # 2026-11-16 实测 Plavix / Cipralex 就是这样：构建期去盐词表缺 hydrogen / oxalate
    # （site/build.py::SALT_WORDS），盐型没折成基名 → 条目被当复方 → 页面对单成分品牌
    # 打出「同名不同药 / Combination」。这是展示层的过度警示，归 site/build.py 工位修，
    # 本脚本只记 WARN，不阻塞（改成阻塞只需把这条搬进 checks）。
    parts0 = base_parts(rows[0]["ing"])
    if len(set(parts0)) < len(parts0):
        sev = [b for b in (rows[0].get("badges") or []) if "sev" in (b.get("cls") or "")]
        if sev:
            warnings.append(
                f"首行成分 {rows[0]['ing']!r} 是「同一成分基名+盐型」并集，却挂了 "
                f"{[b['txt'] for b in sev]} severe 徽章 + 组合标签 —— 疑似构建期去盐词表缺词"
                "（build.py::SALT_WORDS 缺 hydrogen/oxalate）导致的「同名不同药」误报")

    failed = [c for c in checks if not c["ok"]]
    return {
        "status": "FAIL" if failed else "PASS",
        "checks": checks,
        "warnings": warnings,
        "detail": "；".join(c["detail"] for c in (failed or checks[:1])),
    }


def check_case(cdp: CDP, base: str, case: dict, *, deep_link: bool,
               index_timeout: float) -> dict:
    """跑一条查询：打开页面（或页内提交）→ 等 core 就绪 → 读行 → 断言。"""
    started = time.time()
    q = case["q"]
    if deep_link:
        goto(cdp, f"{base}index.html?q={quote(q)}&lang=en")
        wait_for(cdp, READY_JS, index_timeout)
    else:
        mode = cdp.eval(SUBMIT_JS + f"({json.dumps(q)})")
        if mode == "NO_INPUT":
            raise RuntimeError("页面上没有 #q（不是首页结构？）")
        # 首次搜索才会拉 core；分片阶段的「部分结果」不算，等 IDX_READY 再读。
        wait_for(cdp, READY_JS, index_timeout)
    has_rows = wait_for(
        cdp,
        "document.querySelectorAll('#reswrap table.res.rows tbody tr.br').length > 0 "
        f"&& (document.getElementById('q')||{{}}).value === {json.dumps(q)}",
        40)
    time.sleep(0.2)                       # core 到位后那次 render() 收尾
    p = probe(cdp) if has_rows else {}
    rows = p.get("all") or []
    rec = {
        "q": q, "kind": case["kind"], "expect_first": case["first"],
        "rows": p.get("rows", 0), "top": rows[:6], "all_rows": rows,
        "meta": p.get("meta", ""), "h1": p.get("h1", ""), "idx_len": p.get("idx_len"),
        "elapsed_s": round(time.time() - started, 2), "note": case.get("note", ""),
    }
    if not p.get("idx_ready"):
        rec.update({"status": "ERROR", "ok": False, "checks": [], "warnings": [],
                    "detail": f"core 索引 {index_timeout:.0f}s 内没就绪（IDX_READY 仍为假）—— "
                              "采集异常，不是排序结论"})
    elif not rows:
        rec.update({"status": "ERROR", "ok": False, "checks": [], "warnings": [],
                    "detail": "页面上没有结果表（`#reswrap table.res.rows tbody tr.br` 为空）；"
                              f"#meta={p.get('meta')!r}、h1={p.get('h1')!r}"})
    else:
        res = validate_rows(case, rows)
        rec.update({"status": res["status"], "ok": res["status"] == "PASS",
                    "checks": res["checks"], "warnings": res["warnings"],
                    "detail": res["detail"]})
    return rec


# ── 主流程 ─────────────────────────────────────────────────────────────────
def run(dist: Path | None, base_url: str | None, browsers: list[Path],
        cases: list[dict], *, deep_link: bool, index_timeout: float, rules: bool,
        overrides: dict[str, Path] | None) -> dict:
    site = Site(dist, overrides) if dist is not None else None
    srv = site.start(0) if site is not None else None
    base = (f"http://127.0.0.1:{srv.server_address[1]}/" if srv is not None
            else (base_url or ""))
    if not base.endswith("/"):
        base += "/"

    out: dict = {"dist": str(dist) if dist else None, "base": base, "browser": None,
                 "rules": [], "cases": [], "unavailable": None,
                 "overrides": {k: str(v) for k, v in (overrides or {}).items()},
                 "generated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    state: dict = {"proc": None, "cdp": None, "profile": None}

    def shutdown() -> None:
        if state["proc"] is not None:
            try:
                state["proc"].terminate()
                state["proc"].wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass
        if state["profile"] is not None:
            shutil.rmtree(state["profile"], ignore_errors=True)
        state.update({"proc": None, "cdp": None, "profile": None})

    try:
        try:
            proc, cdp, profile = boot(browsers)
        except RuntimeError as exc:          # 浏览器 / CDP 起不来 → SKIP（环境问题）
            out["unavailable"] = str(exc)
            print(f"[SKIP] {exc}")
            return out
        state.update({"proc": proc, "cdp": cdp, "profile": profile})
        out["browser"] = str(browsers[0]) if browsers else None
        cdp.call("Emulation.setDeviceMetricsOverride", width=1280, height=900,
                 deviceScaleFactor=1, mobile=False)
        if not deep_link:                    # 只加载一次首页，后面都走页内提交（快 8 倍）
            goto(cdp, base + "index.html?lang=en")
        if rules:
            print("\n== ① 规则层：直接调页面里的 g3PreferBase()（合成用例，不依赖数据）")
            try:
                out["rules"] = check_rules(cdp)
            except Exception as exc:         # noqa: BLE001
                out["rules"] = [{"id": "rule", "name": "规则层探针", "ok": False,
                                 "expect": "可执行", "got": str(exc)[:120],
                                 "detail": f"规则层探针执行失败：{str(exc)[:200]}"}]
            for it in out["rules"]:
                flag = "PASS" if it["ok"] else "FAIL"
                print(f"  [{flag}] {it['name']}")
                if not it["ok"]:
                    print(f"         {it['detail']}")
            print("\n== ③ 词表一致性：页面 G3_SALT_WORDS vs lib/search.py SALT_WORDS")
            try:
                out["wordlist"] = check_wordlist(cdp)
            except Exception as exc:         # noqa: BLE001
                out["wordlist"] = {"ok": False, "skipped": True,
                                   "detail": f"词表探测失败：{str(exc)[:200]}"}
            wl = out["wordlist"]
            if wl.get("skipped"):
                print(f"  [SKIP] {wl['detail']}")
            else:
                print(f"  [{'PASS' if wl['ok'] else 'WARN'}] {wl['detail']}")
        if cases:
            print(f"\n== ② 数据层：{len(cases)} 条真实查询")
        for case in cases:
            print(f"\n== q={case['q']}（{case['kind']}）{case['note']}")
            try:
                rec = check_case(cdp, base, case, deep_link=deep_link,
                                 index_timeout=index_timeout)
            except Exception as exc:         # noqa: BLE001 —— 中途掉线也别把整轮丢掉
                rec = {"q": case["q"], "kind": case["kind"], "expect_first": case["first"],
                       "status": "ERROR", "ok": False, "checks": [], "warnings": [],
                       "rows": 0, "top": [], "all_rows": [], "meta": "", "h1": "",
                       "idx_len": None, "elapsed_s": 0.0, "note": case.get("note", ""),
                       "detail": f"采集异常（CDP 求值失败）：{str(exc)[:200]}"}
            out["cases"].append(rec)
            flag = {"PASS": "PASS", "FAIL": "FAIL", "ERROR": "ERR "}[rec["status"]]
            print(f"  [{flag}] {rec['detail']}")
            if rec["top"]:
                shown = " / ".join(f"{t['ing'] or '—'}（{t['brand'] or '—'}）"
                                   for t in rec["top"][:4])
                print(f"         候选前 {min(4, len(rec['top']))} 行：{shown}"
                      f"（共 {rec['rows']} 行，{rec['elapsed_s']}s）")
            for chk in rec.get("checks") or []:
                if not chk["ok"]:
                    print(f"         ↳ 未过 {chk['id']}：{chk['detail']}")
            for w in rec.get("warnings") or []:
                print(f"         [WARN] {w}")
    finally:
        shutdown()
        if srv is not None:
            srv.shutdown()

    rule_fail = [r for r in out["rules"] if not r["ok"]]
    fails = [c for c in out["cases"] if c["status"] == "FAIL"]
    errs = [c for c in out["cases"] if c["status"] == "ERROR"]
    wl = out.get("wordlist") or {}
    out["summary"] = {
        "rules": len(out["rules"]), "rule_fail": len(rule_fail),
        "total": len(out["cases"]),
        "pass": len(out["cases"]) - len(fails) - len(errs),
        "fail": len(fails), "error": len(errs),
        "warn": sum(len(c.get("warnings") or []) for c in out["cases"]),
        "word_drift": bool(wl.get("ok") is False and not wl.get("skipped")),
    }
    return out


def _salt_words_drift() -> str | None:
    """SALT_WORDS 与本仓 `lib/search.py` 是否漂移（只读 import，不连库）；漂移返回说明。"""
    try:
        sys.path.insert(0, str(ROOT))
        import lib.search as search_mod  # noqa: PLC0415 —— 可选自检，缺库不报错

        theirs = frozenset(getattr(search_mod, "SALT_WORDS", ()) or ())
        if theirs and theirs != SALT_WORDS:
            only_here = sorted(SALT_WORDS - theirs)[:6]
            only_there = sorted(theirs - SALT_WORDS)[:6]
            return (f"去盐词表与 lib/search.py 漂移：本地多 {only_here}、库里多 {only_there}"
                    "（本脚本按 lib/search.py 口径判，出现漂移就该同步）")
    except Exception:  # noqa: BLE001 —— 自检失败不影响门禁
        return None
    return None


def load_overrides(specs: list[str]) -> dict[str, Path] | None:
    """`REL=PATH` → 静态服务用 PATH 顶替产物里的 REL（只用于验证门禁本身会不会红）。"""
    out: dict[str, Path] = {}
    for spec in specs:
        if "=" not in spec:
            print(f"[SKIP] --override 要写成 REL=PATH，收到 {spec!r}")
            return None
        rel, _, p = spec.partition("=")
        path = Path(p.strip())
        if not path.is_file():
            print(f"[SKIP] --override 指向的文件不存在：{rel.strip()}={path}")
            return None
        out[rel.strip().lstrip("/")] = path
    return out


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，中文与箭头会炸；统一 UTF-8 输出（CI 里也一样）。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(
        description="排序冒烟：客户端的基名优先（G3 方案 b）仍成立，且首条候选卡的基名符合期望")
    ap.add_argument("--dist", default=str(DEFAULT_DIST), help="产物目录（默认 site/dist）")
    ap.add_argument("--base-url", default=None, help="改用已起的服务（给了就不起内置服务）")
    ap.add_argument("--only", default=None, help="只跑这些数据层查询（逗号分隔，如 plavix,tylenol）")
    ap.add_argument("--no-data", action="store_true", help="只跑规则层（秒级，不拉 core 索引）")
    ap.add_argument("--no-rules", action="store_true", help="只跑数据层")
    ap.add_argument("--strict-words", action="store_true",
                    help="词表不一致也判红（默认只 WARN；对齐词表归 site/build.py 负责工位）")
    ap.add_argument("--deep-link", action="store_true",
                    help="数据层每条查询各自导航到 ?q= 深链（慢；排查深链行为时用）")
    ap.add_argument("--override", action="append", default=[], metavar="REL=PATH",
                    help="用补丁页验证门禁会不会红（如 index.html=.tmp/x.html）；正式验收别用")
    ap.add_argument("--json", default=None, help="结果 JSON 落盘路径")
    ap.add_argument("--index-timeout", type=float, default=90.0,
                    help="等 core 索引解码完成的上限秒数（默认 90）")
    ap.add_argument("--list", action="store_true", help="只列查询集，不跑")
    args = ap.parse_args(argv)

    if args.list:
        print("== ① 规则层合成用例（直接调页面里的 g3PreferBase）")
        for c in RULE_CASES:
            print(f"  {c['hits']} → 期望 {c['expect']}")
            print(f"    （{c['name']}）")
        print("\n== ② 数据层查询")
        for c in CASES:
            print(f"  {c['q']:12} [{c['kind']:9}] 期望首行基名 = {c['first']}")
            print(f"  {'':12} {c['note']}")
        return 0

    base_url = args.base_url
    dist = None if base_url else Path(args.dist)
    if dist is not None and not dist.is_dir():
        print(f"[SKIP] 产物目录不存在：{dist}（先跑 site/build.py）")
        return 0
    if dist is not None and not (dist / "data" / "idx" / "core.json").is_file():
        print(f"[SKIP] 产物里没有 data/idx/core.json：{dist}（不是完整产物，先重新构建）")
        return 0
    if dist is not None and not (dist / "index.html").is_file():
        # 有 core.json 却没有首页 = 构建还在跑 / 被中断（如 .tmp/dist-r1r2 这种半成品），
        # 这时打开的是 404 页，判「没有 #q」会被误读成页面 bug —— 直接 SKIP。
        print(f"[SKIP] 产物里没有 index.html：{dist}（构建可能还在跑或未完成，等 == done == 再验）")
        return 0
    browsers = pick_browsers()
    if not browsers:
        print("[SKIP] 没找到本机 Chrome / Edge（试过注册表 / PATH / Program Files / LOCALAPPDATA）。")
        print("       装 Chrome 后重跑，或用 --base-url 配合已有的真浏览器环境。")
        return 0
    overrides = load_overrides(args.override)
    if overrides is None:
        return 0

    only = [x.strip() for x in args.only.split(",")] if args.only else None
    cases = [] if args.no_data else [c for c in CASES if not only or c["q"] in only]
    if not args.no_data and not cases:
        print(f"[SKIP] --only {args.only} 没对上任何查询（可用：{[c['q'] for c in CASES]}）")
        return 0

    drift = _salt_words_drift()
    if drift:
        print(f"[WARN] {drift}")
    if overrides:
        print("⚠ 预览模式：" + "、".join(f"{k} ← {v}" for k, v in overrides.items())
              + "（只用于验证门禁本身会不会红，正式验收请扫构建产物）")
    started = time.time()
    print(f"== 客户端排序冒烟 == dist={dist or '(用 --base-url)'} "
          f"浏览器候选={[p.name for p in browsers]} "
          f"规则 {0 if args.no_rules else len(RULE_CASES)} 条 / 数据 {len(cases)} 条 "
          f"模式={'deep-link' if args.deep_link else 'page-submit'}")
    out = run(dist, base_url, browsers, cases, deep_link=args.deep_link,
              index_timeout=args.index_timeout, rules=not args.no_rules,
              overrides=overrides or None)
    out["elapsed_s"] = round(time.time() - started, 1)
    out["salt_words_drift"] = drift
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {p}")

    if out.get("unavailable"):
        print("[SKIP] 浏览器 / CDP 不可用，本轮不判定（退出码 0）。")
        return 0
    s = out["summary"]
    print(f"\n== 汇总：规则层 {s['rules'] - s['rule_fail']}/{s['rules']} PASS；"
          f"数据层 PASS {s['pass']} / FAIL {s['fail']}"
          + (f" / 采集异常 {s['error']}" if s["error"] else "")
          + (f"；观察 WARN {s['warn']} 条（不阻塞）" if s["warn"] else "")
          + (f"；词表漂移{'（--strict-words 判红）' if args.strict_words else '（WARN，不阻塞）'}"
             if s["word_drift"] else "")
          + f"，耗时 {out['elapsed_s']}s")
    for it in out["rules"]:
        if not it["ok"]:
            print(f"  - FAIL  [rule] {it['detail']}")
    for c in out["cases"]:
        if not c["ok"]:
            print(f"  - {c['status']:5} [{c['q']}] {c['detail']}")
    if s["word_drift"] and args.strict_words:
        print(f"  - FAIL  [words] {(out.get('wordlist') or {}).get('detail')}")
    if s["error"]:
        return 2
    bad = s["fail"] or s["rule_fail"] or (args.strict_words and s["word_drift"])
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
