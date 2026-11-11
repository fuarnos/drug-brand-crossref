"""交互冒烟：抓「静态检查 / detect / 首屏守卫都看不见、必须点一下才暴露」的 bug。

为什么要有这个脚本
------------------
2026-11-11 已发生两起静态检查全绿、用户一点就中的事故：

1. 成分页剂型筛选点 `powder` 列表不变 —— 根因是 `row.hidden = true` 被作者样式
   `.mkrow{display:grid}` 盖掉（`[hidden]` 被作者样式打败）。源码里 `hidden = true` 写得好好的，
   HTML 静态扫描、`impeccable detect`、`first_screen_check` 都抓不到；只有「点一下数可见行」能抓到。
2. 分类 chip 在英文下看着不居中 + hover 下划线（纯视觉，人眼/截图才看得出）。

所以本脚本只做一件事：**在真浏览器里点，然后数**。每项给「过/不过 + 失败根因一句话 + 证据数字」。

覆盖项（与 `reports/2026-11-11-交互冒烟清单.md` 一一对应）
-------------------------------------------------------
1. 成分页：点每个 `[data-form-filter]` → 断言「筛选真的生效」：`hidden` 设了不得再渲染、
   可见行必须全属该剂型、点「全部」回到全量。chip 数字与可见行数的差额作为口径观察（WARN）。
   注：chip 数字是**该剂型的规格数**，`.mkrow` 是「规格 × 市场」行且每国块只渲染前 12 个规格，
   所以「可见行数 = chip 数字」在数学上不成立（实测 `powder 44` → 11 行、`injection 17` → 0 行）。
2. 成分页：`?view=table` → `#tableview`（矩阵）可见、`#list`（清单）隐藏；不带参数时相反。
3. 首页：填 `#q` → 点 `#qgo` → `#meta` 从空闲/加载态变成带命中数的结果态。
4. 首页：`?country=CN` → `#ctrydetails` 自动展开，且 `#country.value == "CN"`。
5. 首页：`?lang=zh` / `?lang=es` → `#h1`、`.candidate-line`、国家/地区 summary 标签都换语言。
6. ATC 页：`[data-i18n="atc.names_source_note"]` 每个页面 ≤1 次（防重复渲染回归）。
7. 通用：每个 `<details>` 点开后内容高度 > 0（折叠组件「点了没反应」的通用判据）。

用法
----
    python deploy/ui_interaction_smoke.py                      # 扫 site/dist
    python deploy/ui_interaction_smoke.py --only 1,3           # 只跑第 1、3 项
    python deploy/ui_interaction_smoke.py --json .tmp/ui-smoke/results.json
    python deploy/ui_interaction_smoke.py --dist .tmp/dist-x   # 扫别的产物
    python deploy/ui_interaction_smoke.py --base-url http://127.0.0.1:8123/   # 已起的服务

退出码：0 = 全过；1 = 有 FAIL；2 = CDP 不可用（浏览器起不来，此时不判定任何项）。

只读：被服务的文件一律只读打开（复用 `ui_surface_check.Site`），浏览器用户目录放系统临时目录，
不改 `site/dist`、不改任何产物；`site/build.py` 完全不碰。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui_surface_check import (  # noqa: E402 —— 复用现成的静态服务 / CDP / 浏览器启动
    CDP,
    Site,
    _page_ws,
    find_chrome,
    launch_chrome,
)

DEFAULT_DIST = ROOT / "site" / "dist"
DEVTOOLS_PORT = 9451

# 浏览器候选：本机 Chrome 的 --remote-debugging-port 偶发起不来，按顺序退到 Edge（同为 Chromium/CDP）。
BROWSER_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)

# 成分页样本：默认页（无矩阵）+ 有矩阵的页（?view=table 用）
DRUG_LIST_PAGES = ("drug/acetaminophen.html", "drug/abacavir.html")
DRUG_MATRIX_PAGE = "drug/abacavir.html"
ATC_PAGES = ("atc.html", "atc/A.html", "atc/R06A.html", "atc/N02BE01.html")
DETAILS_PAGES = ("index.html", "drug/acetaminophen.html", "coverage.html", "atc.html")


# ── 浏览器 / 页面驱动 ───────────────────────────────────────────────────────
def pick_browsers() -> list[Path]:
    """返回按优先级排好的浏览器可执行文件列表（去重、只留存在的）。"""
    out: list[Path] = []
    chrome = find_chrome()
    if chrome is not None:
        out.append(chrome)
    out += [p for p in BROWSER_CANDIDATES if p.is_file()]
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def start_browser(browsers: list[Path]) -> tuple[object, CDP, Path]:
    """起第一个能起来的 Chromium 系浏览器；全失败抛 RuntimeError（→ 退出码 2）。"""
    errors: list[str] = []
    for exe in browsers:
        profile = Path(tempfile.mkdtemp(prefix="ui-smoke-"))
        try:
            proc = launch_chrome(exe, DEVTOOLS_PORT, profile)
        except Exception as exc:  # noqa: BLE001 —— 换下一个浏览器
            errors.append(f"{exe.name}: {str(exc)[:120]}")
            shutil.rmtree(profile, ignore_errors=True)
            continue
        cdp = CDP(_page_ws(DEVTOOLS_PORT))
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        return proc, cdp, profile
    raise RuntimeError("CDP 不可用：" + "；".join(errors or ["找不到 Chrome / Edge"]))


def js(cdp: CDP, expr: str):
    """求值一段表达式，返回 JS 值（对象请用 JSON.stringify 包一层）。"""
    return cdp.eval(expr)


def js_obj(cdp: CDP, expr: str) -> dict:
    raw = js(cdp, expr)
    if not raw:
        return {}
    return json.loads(raw)


def goto(cdp: CDP, url: str, wait_js: str | None = None, timeout: float = 30.0) -> None:
    """导航到 url；可选再等一段 JS 条件为真（超时也继续，由检查自己判）。"""
    js(cdp, "1")  # 探活：浏览器死了这里会先抛
    cdp.events.clear()
    cdp.call("Page.navigate", url=url)
    cdp.wait_event("Page.loadEventFired", 60)
    end = time.time() + 20
    while time.time() < end:
        try:
            if js(cdp, "document.readyState") == "complete":
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.1)
    if wait_js:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if js(cdp, wait_js):
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.2)
    time.sleep(0.15)


# 可见性判据统一口径：hidden 属性能否真的不渲染 —— 三档都给出来，
# 「hidden 设了但仍在渲染」= 事故 1 的形状，单独计数。
VISIBLE_MKROW_JS = r"""(function(){
  var rows = Array.prototype.slice.call(document.querySelectorAll('.mkrow'));
  function shown(el){
    if(el.hidden) return false;
    var cs = getComputedStyle(el);
    if(cs.display === 'none' || cs.visibility === 'hidden') return false;
    var b = el.getBoundingClientRect();
    return b.width > 0 && b.height > 0;
  }
  var visible = 0, hidden_attr = 0, hidden_but_shown = 0, wrong_form = 0;
  var want = (window.__SMOKE_WANT === undefined) ? null : window.__SMOKE_WANT;
  rows.forEach(function(r){
    if(r.hidden){
      hidden_attr++;
      var cs = getComputedStyle(r);
      if(cs.display !== 'none' && r.getBoundingClientRect().height > 0) hidden_but_shown++;
    }
    if(shown(r)){
      visible++;
      if(want !== null && want !== '' && (r.getAttribute('data-form') || '') !== want) wrong_form++;
    }
  });
  var blocks = document.querySelectorAll('.mkblock');
  var blocks_hidden = 0;
  blocks.forEach(function(b){ if(b.hidden) blocks_hidden++; });
  return JSON.stringify({total: rows.length, visible: visible, hidden_attr: hidden_attr,
                         hidden_but_shown: hidden_but_shown, wrong_form: wrong_form,
                         blocks: blocks.length, blocks_hidden: blocks_hidden});
})()"""

CHIP_LIST_JS = r"""(function(){
  var chips = Array.prototype.slice.call(document.querySelectorAll('[data-form-filter]'));
  var rows = document.querySelectorAll('.mkrow').length;
  return JSON.stringify(chips.map(function(c, i){
    var n = c.querySelector('.n');
    var cnt = n ? parseInt((n.textContent||'').replace(/[^0-9]/g, ''), 10) : null;
    return {i: i, want: c.getAttribute('data-form-filter') || '',
            label: (c.textContent||'').replace(/\s+/g, ' ').trim().slice(0, 40),
            count: isNaN(cnt) ? null : cnt, rows: rows};
  }));
})()"""

CLICK_CHIP_JS = r"""(function(i){
  var chips = document.querySelectorAll('[data-form-filter]');
  if(!chips[i]) return 'missing';
  chips[i].click();
  return 'clicked';
})"""


# ── 断言小工具 ─────────────────────────────────────────────────────────────
def record(results: list[dict], cid: str, title: str, ok: bool, detail: str,
           cause: str = "", data: dict | None = None) -> None:
    rec = {"id": cid, "title": title, "pass": bool(ok), "detail": detail,
           "root_cause": cause, "data": data or {}}
    results.append(rec)
    flag = "PASS" if ok else "FAIL"
    print(f"  [{flag}] {cid} {title}")
    print(f"         {detail}" + (f" ← {cause}" if cause else ""))


# ── 各项检查 ───────────────────────────────────────────────────────────────
def check_1_form_filter(cdp: CDP, base: str) -> list[dict]:
    """① 剂型 chip → 可见行只剩该剂型（且 hidden 不被样式打败）；「全部」恢复全量。

    判定口径（2026-11-11 实测确定）：chip 上的数字是**该剂型的规格数**，而 `.mkrow`
    是「规格 × 市场」行、且每国块只渲染前 `LIST_ROWS_PER_BLOCK` 个规格，所以
    「可见行数 = chip 数字」在数学上不成立（实测 `powder 44` → 11 行）。
    因此本项判「可见性正确性」：可见行必须全部属于该剂型、没有别的剂型混进来、
    `hidden` 设了不能再渲染；chip 数字与可见行数的差额单独作为口径观察（WARN，不算 FAIL）。
    """
    out: list[dict] = []
    for rel in DRUG_LIST_PAGES:
        url = base + rel
        goto(cdp, url, "document.querySelectorAll('.mkrow').length > 0")
        chips = js_obj(cdp, CHIP_LIST_JS)
        if not chips:
            out.append({"id": "1", "title": f"剂型筛选 {rel}", "pass": False,
                        "detail": "选择器缺失：页面上没有 [data-form-filter]",
                        "root_cause": "chip 未渲染或选择器改名", "data": {}})
            continue
        total = chips[0]["rows"]
        bad: list[str] = []
        warn: list[str] = []
        cases: list[dict] = []
        for ch in chips:
            want = ch["want"]
            js(cdp, f"window.__SMOKE_WANT = {json.dumps(want)}; 1")
            js(cdp, CLICK_CHIP_JS + f"({ch['i']})")
            time.sleep(0.12)
            st = js_obj(cdp, VISIBLE_MKROW_JS)
            visible = st.get("visible", 0)
            # 判定只看「筛选是否真的生效」：hidden 必须真的不渲染、不许混进别的剂型、
            # 「全部」必须回到全量。点开后可见 0 行 / 数字与行数不等，属于口径与 UX 观察（WARN）。
            ok_case = (st.get("hidden_but_shown", 0) == 0 and st.get("wrong_form", 0) == 0
                       and (visible == total if want == "" else True))
            cases.append({"chip": ch["label"], "want": want, "chip_count": ch["count"],
                          "visible": visible,
                          "hidden_but_shown": st.get("hidden_but_shown"),
                          "wrong_form": st.get("wrong_form"), "ok": ok_case})
            if not ok_case:
                if st.get("hidden_but_shown"):
                    bad.append(f"`{ch['label']}`：{st.get('hidden_but_shown')} 行 hidden 被作者样式"
                               f"打败仍在渲染（可见 {visible} 行）")
                elif st.get("wrong_form"):
                    bad.append(f"`{ch['label']}`：可见行里混进 {st.get('wrong_form')} 行别的剂型")
                else:
                    bad.append(f"`{ch['label']}`：点「全部」后可见 {visible} 行 ≠ 全量 {total} 行")
            elif want:
                if ch["count"] is not None and visible != ch["count"]:
                    warn.append(f"`{ch['label']}` 数字 {ch['count']} → 可见 {visible} 行")
                if visible == 0:
                    warn.append(f"`{ch['label']}` 点开后**可见 0 行**（该剂型的规格全被"
                                f"「其余规格」折行收走）")
        all_idx = next((c["i"] for c in chips if c["want"] == ""), None)
        restored = None
        if all_idx is not None:
            js(cdp, "window.__SMOKE_WANT = ''; 1")
            js(cdp, CLICK_CHIP_JS + f"({all_idx})")
            time.sleep(0.12)
            restored = js_obj(cdp, VISIBLE_MKROW_JS).get("visible")
        ok_all = not bad and restored == total
        cause = ""
        if bad:
            cause = "`[hidden]` 被作者样式覆盖（`.mkrow{display:grid}`）或缺 `.mkrow[hidden]{display:none}` 兜底"
        elif restored != total:
            cause = "点「全部」没有恢复全量（filter 状态没重置）"
        detail = (f"{len(cases)} 个 chip：筛选生效性"
                  f"{'全部正确' if not bad else '有 ' + str(len(bad)) + ' 个不符'}；"
                  f"全量 {total} 行；点「全部」后可见 {restored} 行"
                  + ("；" + "；".join(bad[:3]) if bad else ""))
        if warn:
            detail += f"｜观察（非 FAIL）：{len(warn)} 条，例：{'；'.join(warn[:3])}"
        out.append({"id": "1", "title": f"剂型筛选 {rel}", "pass": ok_all,
                    "detail": detail, "root_cause": cause,
                    "warnings": warn,
                    "data": {"cases": cases, "total": total, "restored": restored,
                             "warnings": warn}})
    return out


def check_2_view_table(cdp: CDP, base: str) -> list[dict]:
    """② ?view=table → 矩阵可见、清单隐藏；不带参数时相反。"""
    probe = r"""(function(){
      function st(sel){
        var el = document.querySelector(sel);
        if(!el) return null;
        var cs = getComputedStyle(el), b = el.getBoundingClientRect();
        return {hidden: !!el.hidden, display: cs.display, h: Math.round(b.height),
                visible: !el.hidden && cs.display !== 'none' && b.height > 0};
      }
      return JSON.stringify({table: st('#tableview'), list: st('#list'),
                             matrix: st('#tableview table.matrix')});
    })()"""
    url_t = base + DRUG_MATRIX_PAGE + "?view=table"
    goto(cdp, url_t, "document.getElementById('tableview') || document.getElementById('list')")
    a = js_obj(cdp, probe)
    url_plain = base + DRUG_MATRIX_PAGE
    goto(cdp, url_plain, "document.getElementById('list')")
    b = js_obj(cdp, probe)
    if not a.get("table") or not a.get("list"):
        return [{"id": "2", "title": "?view=table 切换", "pass": False,
                 "detail": f"选择器缺失：{DRUG_MATRIX_PAGE} 里没有 #tableview 或 #list",
                 "root_cause": "该页没有内嵌矩阵（multi_ratio < 0.40），矩阵视图本就不存在",
                 "data": {"table": a.get("table"), "list": a.get("list")}}]
    ok = (a["table"]["visible"] and not a["list"]["visible"]
          and not b["table"]["visible"] and b["list"]["visible"])
    cause = ""
    if not ok:
        if a["table"]["visible"] and a["list"]["visible"]:
            cause = "清单与矩阵同时可见（initListView 没把 #list 隐藏）"
        elif not a["table"]["visible"]:
            cause = "?view=table 没把矩阵显示出来（tableview.hidden 未解除）"
        else:
            cause = "不带参数时矩阵仍可见（默认状态不对）"
    return [{"id": "2", "title": f"?view=table 切换（{DRUG_MATRIX_PAGE}）", "pass": ok,
             "detail": (f"带参数：矩阵 visible={a['table']['visible']}（h={a['table']['h']}px）、"
                        f"清单 visible={a['list']['visible']}；"
                        f"不带参数：矩阵 visible={b['table']['visible']}、清单 visible={b['list']['visible']}"),
             "root_cause": cause, "data": {"with_param": a, "plain": b}}]


def check_3_submit(cdp: CDP, base: str) -> list[dict]:
    """③ 首页 #qgo 提交 → #meta 从加载态变结果态。"""
    goto(cdp, base + "index.html?lang=zh", "document.getElementById('qgo')")
    has = js_obj(cdp, r"""(function(){
      return JSON.stringify({qgo: !!document.getElementById('qgo'),
                             q: !!document.getElementById('q'),
                             meta: !!document.getElementById('meta')});
    })()""")
    if not (has.get("qgo") and has.get("q")):
        return [{"id": "3", "title": "#qgo 提交", "pass": False,
                 "detail": f"选择器缺失：qgo={has.get('qgo')} q={has.get('q')}",
                 "root_cause": "产物里没有可见提交按钮（v0.11.0 及更早没有 #qgo）",
                 "data": has}]
    before = js(cdp, "(document.getElementById('meta')||{}).textContent || ''")
    js(cdp, r"""(function(){
      var q = document.getElementById('q');
      q.value = '泰诺';
      q.dispatchEvent(new Event('input', {bubbles: true}));
      document.getElementById('qgo').click();
      return 1;
    })()""")
    after = before
    rows = 0
    end = time.time() + 30
    while time.time() < end:
        after = js(cdp, "(document.getElementById('meta')||{}).textContent || ''")
        rows = js(cdp, "document.querySelectorAll('#reswrap tbody tr').length") or 0
        if rows > 0 and any(ch.isdigit() for ch in (after or "")):
            break
        time.sleep(0.25)
    ok = rows > 0 or any(ch.isdigit() for ch in (after or ""))
    cause = "" if ok else "点提交后 #meta 30s 内没出现命中数、结果表也没有行（提交绑定丢失或索引未就绪）"
    return [{"id": "3", "title": "#qgo 提交 → #meta 出结果", "pass": ok,
             "detail": f"提交前 #meta={before.strip()[:40]!r} → 提交后 {after.strip()[:60]!r}；"
                       f"结果行 {rows} 行",
             "root_cause": cause, "data": {"before": before, "after": after, "rows": rows}}]


def check_4_country(cdp: CDP, base: str) -> list[dict]:
    """④ ?country=CN → #ctrydetails 自动展开且 #country.value == "CN"。"""
    goto(cdp, base + "index.html?country=CN&lang=zh", "document.getElementById('ctrydetails')")
    st = js_obj(cdp, r"""(function(){
      var d = document.getElementById('ctrydetails');
      var c = document.getElementById('country');
      var s = d ? d.querySelector('summary') : null;
      return JSON.stringify({
        has_details: !!d, open: !!(d && d.open),
        value: c ? c.value : null,
        summary: s ? (s.textContent||'').replace(/\s+/g,' ').trim().slice(0,60) : null,
        panel_h: d ? Math.round((d.scrollHeight||0) - (s ? s.getBoundingClientRect().height : 0)) : 0
      });
    })()""")
    if not st.get("has_details"):
        return [{"id": "4", "title": "?country=CN 自动展开", "pass": False,
                 "detail": "选择器缺失：没有 #ctrydetails",
                 "root_cause": "首页国家筛选还没收进 <details>（v0.11.0 及更早）", "data": st}]
    ok = st.get("open") is True and st.get("value") == "CN"
    cause = ""
    if st.get("value") != "CN":
        cause = "#country 没回填 CN（URL 参数没进选择器）"
    elif not st.get("open"):
        cause = "#ctrydetails 没自动展开（参数存在时缺 open 逻辑）"
    return [{"id": "4", "title": "?country=CN 自动展开", "pass": ok,
             "detail": f"#ctrydetails.open={st.get('open')}、#country.value={st.get('value')!r}、"
                       f"summary={st.get('summary')!r}、面板高 {st.get('panel_h')}px",
             "root_cause": cause, "data": st}]


def _lang_probe(cdp: CDP) -> dict:
    return js_obj(cdp, r"""(function(){
      function tx(sel){ var e = document.querySelector(sel); return e ? (e.textContent||'').replace(/\s+/g,' ').trim() : null; }
      var sum = document.getElementById('ctrydetails');
      var sumLab = sum ? sum.querySelector('summary') : null;
      return JSON.stringify({
        h1: tx('#h1'),
        candidate: tx('.candidate-line'),
        ctry: sumLab ? (sumLab.textContent||'').replace(/\s+/g,' ').trim() : tx('#ctrylabel'),
        ctry_sel_summary_id: !!document.querySelector('summary#ctrylabel'),
        ctry_sel_inner: !!document.querySelector('#ctrylabel')
      });
    })()""")


def check_5_lang(cdp: CDP, base: str) -> list[dict]:
    """⑤ ?lang=zh / ?lang=es → #h1 / .candidate-line / 国家 summary 都换语言。"""
    out: list[dict] = []
    got: dict[str, dict] = {}
    for lang in ("en", "zh", "es"):
        goto(cdp, base + f"index.html?lang={lang}", "document.getElementById('h1')")
        # 语言包可能在 load 后才应用，给 apply() 一点时间
        end = time.time() + 12
        prev = None
        while time.time() < end:
            cur = _lang_probe(cdp)
            if prev is not None and cur == prev:
                break
            prev = cur
            time.sleep(0.3)
        got[lang] = _lang_probe(cdp)
    fields = (("h1", "#h1"), ("candidate", ".candidate-line"), ("ctry", "国家/地区 summary 标签"))
    missing = [n for n in ("h1", "candidate", "ctry") if not got["en"].get(n)]
    if missing:
        out.append({"id": "5", "title": "语言切换", "pass": False,
                    "detail": "选择器缺失：" + "、".join(missing),
                    "root_cause": "产物里没有该元素（v0.11.0 及更早没有 .candidate-line）",
                    "data": {"en": got["en"]}})
        return out
    def cjk(s: str | None) -> bool:
        return bool(s) and any("\u4e00" <= ch <= "\u9fff" for ch in s)
    zh_ok = cjk(got["zh"]["h1"]) and got["zh"]["h1"] != got["en"]["h1"]
    es_ok = got["es"]["h1"] != got["en"]["h1"] and not cjk(got["es"]["h1"])
    same = [n for n, _ in fields if got["zh"].get(n) == got["en"].get(n)]
    ok = zh_ok and es_ok and not same
    cause = ""
    if same:
        cause = f"这些元素 {same} 在 zh 下与 en 相同（i18n 键缺失或 data-i18n 没挂上）"
    elif not zh_ok:
        cause = "#h1 在 ?lang=zh 下没有变成中文"
    elif not es_ok:
        cause = "#h1 在 ?lang=es 下没有变成西语"
    out.append({
        "id": "5", "title": "语言切换 zh/en/es（#h1 / .candidate-line / summary）", "pass": ok,
        "detail": (f"en={got['en']['h1']!r}｜zh={got['zh']['h1']!r}｜es={got['es']['h1']!r}；"
                   f"候选集行 zh={got['zh']['candidate']!r}；summary zh={got['zh']['ctry']!r}；"
                   f"`summary#ctrylabel` 命中={got['en']['ctry_sel_summary_id']}（实际 id 在内层 span，"
                   f"`#ctrylabel` 命中={got['en']['ctry_sel_inner']}）"),
        "root_cause": cause, "data": got})
    return out


def check_6_atc_note(cdp: CDP, base: str) -> list[dict]:
    """⑥ ATC 页 atc.names_source_note 每页 ≤1 次。"""
    out: list[dict] = []
    probe = r"""(function(){
      var n = document.querySelectorAll('[data-i18n="atc.names_source_note"]').length;
      var texts = [];
      document.querySelectorAll('[data-i18n="atc.names_source_note"]').forEach(function(e){
        texts.push((e.textContent||'').replace(/\s+/g,' ').trim().slice(0, 50));
      });
      return JSON.stringify({count: n, texts: texts});
    })()"""
    for rel in ATC_PAGES:
        p = DEFAULT_DIST / rel
        if not p.is_file():
            continue
        goto(cdp, base + rel, "document.body")
        st = js_obj(cdp, probe)
        cnt = st.get("count", 0)
        out.append({"id": "6", "title": f"ATC 说明行去重 {rel}", "pass": cnt <= 1,
                    "detail": f"命中 {cnt} 处（要求 ≤1）"
                              + (f"；重复文案 {st.get('texts')}" if cnt > 1 else ""),
                    "root_cause": "" if cnt <= 1 else
                    "同一条 atc.names_source_note 被渲染两次（页头 notice + notes 段重复）",
                    "data": st})
    if not out:
        out.append({"id": "6", "title": "ATC 说明行去重", "pass": False,
                    "detail": "成品的 atc.html 不存在，无法检查", "root_cause": "产物缺失"})
    return out


def check_7_details(cdp: CDP, base: str) -> list[dict]:
    """⑦ 每个 <details> 点开后内容高度 > 0（两个视口各测一遍）。

    当前视口不渲染的 details（例如桌面端隐藏的手机「⋯」菜单）跳过并单列，
    否则会把「按断点隐藏」误判成「点了没反应」。
    """
    out: list[dict] = []
    # 先清一次 localStorage：前面几项会用 ?lang= 写语言偏好，不清会把后面的页面文案带成西语，
    # 让「点开后的标签」在两次运行之间不可复现。
    goto(cdp, base + "index.html", "document.body")
    js(cdp, "try{localStorage.clear();}catch(e){}; 1")
    for width, height, vp in ((1280, 900, "1280x900"), (390, 844, "390x844")):
        cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                 deviceScaleFactor=1, mobile=False)
        for rel in DETAILS_PAGES:
            if not (DEFAULT_DIST / rel).is_file():
                continue
            goto(cdp, base + rel, "document.body")
            info = js_obj(cdp, r"""(function(){
              var ds = Array.prototype.slice.call(document.querySelectorAll('details'));
              var rendered = 0;
              ds.forEach(function(d){
                var cs = getComputedStyle(d), b = d.getBoundingClientRect();
                if(cs.display !== 'none' && b.height > 0) rendered++;
              });
              return JSON.stringify({n: ds.length, rendered: rendered});
            })()""")
            n = info.get("n", 0)
            if not n:
                continue
            bad: list[dict] = []
            skipped: list[str] = []
            tested = 0
            for i in range(min(n, 60)):
                st = js_obj(cdp, r"""(function(i){
                  var d = document.querySelectorAll('details')[i];
                  if(!d) return JSON.stringify({missing: true});
                  var s = d.querySelector('summary');
                  if(!s) return JSON.stringify({no_summary: true});
                  var cs = getComputedStyle(d), b0 = d.getBoundingClientRect();
                  var lab = (s.textContent||'').replace(/\s+/g,' ').trim().slice(0, 30);
                  if(cs.display === 'none' || b0.height === 0)
                    return JSON.stringify({skip: true, label: lab});
                  var was = d.open;
                  if(!was) s.click();
                  var h = (d.scrollHeight||0) - Math.round(s.getBoundingClientRect().height);
                  var res = {label: lab, was_open: was, open: d.open, content_h: h};
                  if(!was){ s.click(); }
                  return JSON.stringify(res);
                })""" + f"({i})")
                if st.get("missing") or st.get("no_summary"):
                    continue
                if st.get("skip"):
                    skipped.append(st.get("label") or "?")
                    continue
                tested += 1
                if not st.get("open") or st.get("content_h", 0) <= 0:
                    bad.append(st)
            out.append({"id": "7", "title": f"<details> 展开 {rel} @{vp}", "pass": not bad,
                        "detail": (f"共 {n} 个 details（当前视口渲染 {info.get('rendered')} 个），"
                                   f"抽测 {tested} 个，展开后内容高 ≤0 的 {len(bad)} 个"
                                   + (f"：{[b.get('label') for b in bad[:4]]}" if bad else "")
                                   + (f"；跳过（本视口不显示）{len(skipped)} 个：{skipped[:4]}"
                                      if skipped else "")),
                        "root_cause": "" if not bad else
                        "summary 点击没生效 / 面板 display:none / 内容为空（点了没反应）",
                        "data": {"n": n, "tested": tested, "bad": bad[:10], "skipped": skipped}})
    cdp.call("Emulation.setDeviceMetricsOverride", width=1280, height=900,
             deviceScaleFactor=1, mobile=False)
    return out


CHECKS = {
    "1": ("成分页剂型筛选：筛选生效（hidden 生效 / 无混入 / 全部可恢复）+ 数字口径观察",
          check_1_form_filter),
    "2": ("?view=table：矩阵可见 / 清单隐藏", check_2_view_table),
    "3": "首页 #qgo 提交 → #meta 出结果",
    "4": "?country=CN → #ctrydetails 展开 + #country=CN",
    "5": "语言切换 zh/es → #h1 / .candidate-line / summary",
    "6": "ATC 说明行 atc.names_source_note ≤1",
    "7": "<details> 展开后内容高度 > 0",
}


def run(dist: Path, base_url: str | None, only: list[str] | None) -> dict:
    site = Site(dist) if base_url is None else None
    srv = site.start(0) if site is not None else None
    base = (f"http://127.0.0.1:{srv.server_address[1]}/" if srv is not None
            else (base_url or ""))
    if not base.endswith("/"):
        base += "/"
    browsers = pick_browsers()
    out: dict = {"dist": str(dist), "base": base, "browser": None, "checks": [],
                 "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "unavailable": None,
                 "restarts": 0}
    state: dict = {"proc": None, "cdp": None, "profile": None}

    def shutdown_browser() -> None:
        if state["proc"] is not None:
            try:
                state["proc"].terminate()
                state["proc"].wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass
        if state["profile"] is not None:
            shutil.rmtree(state["profile"], ignore_errors=True)
        state.update({"proc": None, "cdp": None, "profile": None})

    def boot() -> CDP:
        shutdown_browser()
        proc, cdp, profile = start_browser(browsers)
        state.update({"proc": proc, "cdp": cdp, "profile": profile})
        cdp.call("Emulation.setDeviceMetricsOverride", width=1280, height=900,
                 deviceScaleFactor=1, mobile=False)
        return cdp

    def alive_or_boot() -> CDP:
        if state["cdp"] is not None:
            try:
                state["cdp"].eval("1")
                return state["cdp"]
            except Exception:  # noqa: BLE001 —— 浏览器死了就重开一个
                pass
        out["restarts"] += 1
        print("  （浏览器连接中断，重启一个再继续）")
        return boot()

    plan = [
        ("1", check_1_form_filter),
        ("2", check_2_view_table),
        ("3", check_3_submit),
        ("4", check_4_country),
        ("5", check_5_lang),
        ("6", check_6_atc_note),
        ("7", check_7_details),
    ]
    try:
        cdp = boot()
        out["browser"] = str(browsers[0]) if browsers else None
        for cid, fn in plan:
            if only and cid not in only:
                continue
            title = CHECKS[cid] if isinstance(CHECKS[cid], str) else CHECKS[cid][0]
            print(f"\n== {cid}. {title}")
            got: list[dict] | None = None
            last_exc: Exception | None = None
            for _attempt in (1, 2):
                try:
                    got = fn(alive_or_boot(), base)
                    break
                except Exception as exc:  # noqa: BLE001 —— 连接断了就重开再试一次
                    last_exc = exc
                    shutdown_browser()
            if got is None:
                out["checks"].append({
                    "id": cid, "title": str(title), "pass": False,
                    "detail": f"采集异常（已重试并重启浏览器）：{str(last_exc)[:200]}",
                    "root_cause": "本项脚本/浏览器异常（不是页面 bug，需重跑）",
                    "error": True, "data": {}})
                print(f"  [ERR ] {cid} 采集异常：{str(last_exc)[:160]}")
            else:
                out["checks"] += got
                for c in got:
                    if c["pass"]:
                        print(f"  [PASS] {c['title']}")
                        print(f"         {c['detail'][:400]}")
                    else:
                        print(f"  [FAIL] {c['title']}")
                        print(f"         {c['detail'][:400]}"
                              + (f" ← {c['root_cause']}" if c.get("root_cause") else ""))
                    for w in c.get("warnings") or []:
                        print(f"         [WARN] {w}")
    except RuntimeError as exc:
        out["unavailable"] = str(exc)
        print(f"\n!! {exc}")
    finally:
        shutdown_browser()
        if srv is not None:
            srv.shutdown()
    fails = [c for c in out["checks"] if not c["pass"] and not c.get("error")]
    errs = [c for c in out["checks"] if c.get("error")]
    warns = sum(len(c.get("warnings") or []) for c in out["checks"])
    out["summary"] = {"total": len(out["checks"]), "fail": len(fails),
                      "pass": len(out["checks"]) - len(fails) - len(errs),
                      "error": len(errs), "restarts": out["restarts"], "warn": warns}
    return out


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="交互冒烟：点一下才暴露的 bug（只读）")
    ap.add_argument("--dist", default=str(DEFAULT_DIST), help="产物目录（默认 site/dist）")
    ap.add_argument("--base-url", default=None, help="改用已起的服务（给了就不起内置服务）")
    ap.add_argument("--only", default=None, help="只跑这些项（逗号分隔，如 1,3）")
    ap.add_argument("--json", default=None, help="结果 JSON 落盘路径")
    ap.add_argument("--list", action="store_true", help="只列检查项，不跑")
    args = ap.parse_args(argv)

    if args.list:
        for cid, fn in CHECKS.items():
            print(f"{cid}. {fn if isinstance(fn, str) else fn[0]}")
        return 0

    dist = Path(args.dist)
    if args.base_url is None and not dist.is_dir():
        print(f"产物目录不存在：{dist}")
        return 2
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    print(f"== 交互冒烟 == dist={dist} 浏览器候选={[p.name for p in pick_browsers()]}")
    out = run(dist, args.base_url, only)
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {p}")
    s = out["summary"]
    print(f"\n== 汇总：{s['total']} 项检查，PASS {s['pass']} / FAIL {s['fail']}"
          + (f" / 采集异常 {s['error']}" if s.get("error") else "")
          + (f"；观察 WARN {s['warn']} 条（不阻塞）" if s.get("warn") else "")
          + (f"；浏览器重启 {s['restarts']} 次" if s.get("restarts") else ""))
    for c in out["checks"]:
        if not c["pass"]:
            tag = "ERR " if c.get("error") else "FAIL"
            print(f"  - {tag} [{c['id']}] {c['title']}：{c['root_cause'] or c['detail'][:80]}")
    if out["unavailable"]:
        print("  CDP 不可用，本轮不判定。")
        return 2
    if s.get("error"):
        return 2
    return 0 if s["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
