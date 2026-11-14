"""只读取证：UI 现状度量探针（L1–L17 重设计前的 before 数字）。

用法（仓库根目录）：
    $py = 'C:\\Users\\asus\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe'
    & $py reports/2026-11-15-ui-baseline-probe.py                      # 量 site/dist，落 .tmp/ui-baseline/probe.json
    & $py reports/2026-11-15-ui-baseline-probe.py --json .tmp/ui-baseline/after.json --shots docs/img
    & $py reports/2026-11-15-ui-baseline-probe.py --pages results,drug --viewports 390x844

量什么（每「页面 × 视口」一条）：
    页头四件套  h1 文字/字号/字重、h1 之上的返回链接、main 内搜索入口、一句话摘要行数
    边框        主内容区里 computed border 宽度 > 0 的元素数 + 按 class 归并的 Top 名单
    胶囊徽章    命中徽章类族的元素数，按「实际 class 串」分组；同时分 pill(圆角≥12px) / box
    details     main 内 <details> 数量 / 展开数 / summary 文案
    字号        主内容区可见文字的最小字号、<12px 计数、<14px 占比
    表格        首个 <table> 的 thead 文案与字号；结果页头 3 行逐格（文字/字号/字重）
    按钮        全部可见按钮文案（去重 + 次数）
    溢出        documentElement.scrollWidth > innerWidth
    重复说明    同一文案的多语 .lang-block 数量（maker/atc/cat 页的「重复说明」证据）

只读：被服务的文件只读打开，Chrome 用户目录放系统临时目录；不写 site/dist、不写库。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))

from ui_surface_check import CDP, Site, _page_ws, find_chrome, launch_chrome  # noqa: E402

# ── 页面清单（与 reports/2026-11-15-ui-baseline.md 的 6 类次级页一一对应）──
PAGES: list[dict] = [
    {"key": "home", "rel": "index.html", "shot": "home"},
    {"key": "results", "rel": "index.html?q=tylenol&lang=zh", "shot": "results-tylenol"},
    {"key": "drug", "rel": "drug/amlodipine.html", "shot": "drug-amlodipine"},
    {"key": "name", "rel": "name/tylenol-extra-strength.html", "shot": "name-tylenol-extra-strength"},
    {"key": "combo", "rel": "combo/ferric-oxide-red+pramoxine+zinc-oxide.html", "shot": "combo-ferric-oxide-red"},
    {"key": "maker", "rel": "maker/kenvue-brands-llc.html", "shot": "maker-kenvue-brands-llc"},
    {"key": "cat", "rel": "cat/analgesics.html", "shot": "cat-analgesics"},
    {"key": "atc", "rel": "atc/R06A.html", "shot": "atc-r06a"},
    {"key": "coverage", "rel": "coverage.html", "shot": "coverage"},
]

VIEWPORTS: list[tuple[int, int]] = [(390, 844), (1440, 900)]

# 徽章类族：命中任一 token 就算「一个徽章」；分组键用元素实际的 class 串。
BADGE_TOKENS = [
    "tag", "badge", "st-badge", "form-tag", "catchip", "formchip", "lf-chip",
    "mkchip", "cmp-b", "tr-badge", "nolang-badge", "brand-none", "atc-st",
    "st-word", "pill", "chip",
]

PROBE_JS = r"""(function(){
 try{
  var T = %(badge_tokens)s;
  var out = {};
  out.viewport = [window.innerWidth, window.innerHeight];
  out.doc_title = document.title;
  var main = document.querySelector('main#main, main') || document.body;
  var h1 = main.querySelector('h1');
  function st(el){ return el ? getComputedStyle(el) : null; }
  function fz(el){
    if(!el) return null;
    var s = st(el);
    return { size: Math.round(parseFloat(s.fontSize)*100)/100,
             weight: parseInt(s.fontWeight,10) || s.fontWeight,
             color: s.color,
             cls: (el.className && typeof el.className === 'string') ? el.className : '' };
  }
  function visible(el){
    if(!el) return false;
    var r = el.getBoundingClientRect();
    if(r.width <= 0 || r.height <= 0) return false;
    var s = st(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0.05;
  }
  function directText(el){
    var t = '';
    for(var i=0;i<el.childNodes.length;i++){
      var n = el.childNodes[i];
      if(n.nodeType === 3) t += n.nodeValue;
    }
    return t.replace(/\s+/g,' ').trim();
  }
  // ── 1) 页头四件套 ─────────────────────────────────────────────
  var h1r = h1 ? h1.getBoundingClientRect() : null;
  var above = [];
  if(h1r){
    Array.prototype.slice.call(main.querySelectorAll('a')).forEach(function(a){
      var r = a.getBoundingClientRect();
      if(r.height > 0 && r.bottom <= h1r.top + 2 && visible(a)){
        above.push((a.textContent||'').replace(/\s+/g,' ').trim().slice(0,60));
      }
    });
  }
  out.head = {
    h1: h1 ? { text: (h1.textContent||'').replace(/\s+/g,' ').trim().slice(0,160), font: fz(h1) } : null,
    back_links_above_h1: above,
    back_link_count: above.length,
    search_in_main: !!main.querySelector('#q, input[type=search]'),
    sub_lines: Array.prototype.slice.call(main.querySelectorAll('h1 ~ p.sub'))
      .filter(visible).map(function(p){ return (p.textContent||'').replace(/\s+/g,' ').trim().slice(0,90); }).slice(0,6),
    lang_blocks: main.querySelectorAll('.lang-block').length,
    lang_blocks_visible: Array.prototype.slice.call(main.querySelectorAll('.lang-block')).filter(visible).length
  };
  // ── 2) 边框 ───────────────────────────────────────────────────
  var borders = 0, byClass = {}, maxTop = 400;
  var all = main.querySelectorAll('*');
  for(var i=0;i<all.length;i++){
    var el = all[i];
    var s = st(el);
    if(!s) continue;
    var has = false;
    ['Top','Right','Bottom','Left'].forEach(function(sd){
      var w = parseFloat(s['border'+sd+'Width']) || 0;
      var sty = s['border'+sd+'Style'];
      if(w > 0 && sty !== 'none' && sty !== 'hidden') has = true;
    });
    if(!has) continue;
    borders++;
    if(!visible(el)) continue;
    var cls = (el.className && typeof el.className === 'string') ? el.className.trim() : '';
    var k = el.tagName.toLowerCase() + (cls ? '.' + cls.split(/\s+/).join('.') : '');
    byClass[k] = (byClass[k] || 0) + 1;
  }
  var top = Object.keys(byClass).sort(function(a,b){ return byClass[b]-byClass[a]; })
    .slice(0, 18).map(function(k){ return [k, byClass[k]]; });
  out.borders = { total_with_border: borders, top: top };
  // ── 3) 胶囊徽章 ───────────────────────────────────────────────
  var badges = 0, bGroup = {}, pill = 0, box = 0;
  Array.prototype.slice.call(main.querySelectorAll('[class]')).forEach(function(el){
    var cls = el.className && typeof el.className === 'string' ? el.className.trim() : '';
    if(!cls) return;
    var tokens = cls.split(/\s+/);
    var hit = tokens.some(function(t){ return T.indexOf(t) >= 0; });
    if(!hit) return;
    if(!visible(el)) return;
    badges++;
    var key = tokens.slice().sort().join('.');
    bGroup[key] = (bGroup[key] || 0) + 1;
    var radius = parseFloat(st(el).borderTopLeftRadius) || 0;
    if(radius >= 12) pill++; else box++;
  });
  out.badges = {
    total: badges, pill: pill, box: box,
    groups: Object.keys(bGroup).sort(function(a,b){ return bGroup[b]-bGroup[a]; })
      .map(function(k){ return [k, bGroup[k]]; })
  };
  // ── 4) details ────────────────────────────────────────────────
  var ds = Array.prototype.slice.call(main.querySelectorAll('details'));
  out.details = {
    total: ds.length,
    open: ds.filter(function(d){ return d.open; }).length,
    summaries: ds.slice(0, 12).map(function(d){
      var s = d.querySelector('summary');
      return s ? (s.textContent||'').replace(/\s+/g,' ').trim().slice(0,70) : '';
    })
  };
  // ── 5) 字号（主内容区可见文字）──────────────────────────────
  var sizes = [], lt12 = 0, lt14 = 0, n = 0, minWhere = '';
  var minSize = 999;
  for(var j=0;j<all.length;j++){
    var e2 = all[j];
    if(!directText(e2)) continue;
    if(!visible(e2)) continue;
    var fs = parseFloat(st(e2).fontSize);
    if(!fs || isNaN(fs)) continue;
    n++; sizes.push(fs);
    if(fs < 12) lt12++;
    if(fs < 14) lt14++;
    if(fs < minSize){
      minSize = fs;
      minWhere = e2.tagName.toLowerCase()
        + ((e2.className && typeof e2.className === 'string' && e2.className.trim())
            ? '.' + e2.className.trim().split(/\s+/).join('.') : '');
    }
  }
  out.fonts = {
    text_nodes: n, min: minSize === 999 ? null : minSize, min_where: minWhere,
    lt12: lt12, lt14: lt14,
    lt14_ratio: n ? Math.round((lt14 / n) * 1000) / 1000 : 0
  };
  // ── 6) 表格：表头 + 结果页前 3 行 ────────────────────────────
  var tbl = main.querySelector('table');
  out.table = null;
  if(tbl){
    var ths = Array.prototype.slice.call(tbl.querySelectorAll('thead th'));
    out.table = {
      cls: (tbl.className || '').trim(),
      headers: ths.map(function(th){
        return { text: (th.textContent||'').replace(/\s+/g,' ').trim(), font: fz(th) };
      })
    };
    var rows = Array.prototype.slice.call(tbl.querySelectorAll('tbody tr.br')).slice(0, 3);
    out.table.rows = rows.map(function(tr){
      return Array.prototype.slice.call(tr.children).map(function(td){
        return {
          cls: (td.className || '').trim(),
          label: td.getAttribute('data-label') || '',
          text: (td.textContent||'').replace(/\s+/g,' ').trim().slice(0,90),
          font: fz(td),
          brand_font: fz(td.querySelector('[data-brand]')),
          tag_font: fz(td.querySelector('.tag')),
          h: Math.round(td.getBoundingClientRect().height)
        };
      });
    });
  }
  // ── 7) 按钮文案 ───────────────────────────────────────────────
  var btns = {};
  Array.prototype.slice.call(main.querySelectorAll('button, .linkbtn, a[role=button]')).forEach(function(b){
    if(!visible(b)) return;
    var t = (b.textContent||'').replace(/\s+/g,' ').trim().slice(0,50) || ('[' + (b.getAttribute('aria-label')||b.className||'?') + ']');
    btns[t] = (btns[t] || 0) + 1;
  });
  out.buttons = Object.keys(btns).sort(function(a,b){ return btns[b]-btns[a]; })
    .map(function(k){ return [k, btns[k]]; }).slice(0, 24);
  // ── 8) 溢出 ──────────────────────────────────────────────────
  out.overflow = {
    doc_w: document.documentElement.scrollWidth,
    vw: window.innerWidth,
    over: document.documentElement.scrollWidth > window.innerWidth + 1
  };
  return JSON.stringify(out);
 }catch(e){ return JSON.stringify({error: String(e && e.stack || e)}); }
})()"""


def wait_ready(cdp: CDP, key: str, timeout: float = 25.0) -> None:
    """结果页是客户端渲染的：等结果表真的出现，别量到骨架屏。"""
    if key != "results":
        return
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cdp.eval("!!document.querySelector('#reswrap table tbody tr')"):
                time.sleep(0.6)
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)


def measure(cdp: CDP, base: str, page: dict, w: int, h: int) -> dict:
    url = base + page["rel"]
    cdp.call("Emulation.setDeviceMetricsOverride", width=w, height=h,
             deviceScaleFactor=1, mobile=False)
    cdp.events.clear()
    cdp.call("Page.navigate", url=url)
    cdp.wait_event("Page.loadEventFired", 60)
    time.sleep(0.8)
    wait_ready(cdp, page["key"])
    js = PROBE_JS % {"badge_tokens": json.dumps(BADGE_TOKENS)}
    raw = cdp.eval(js) or "{}"
    data = json.loads(raw)
    data["url"] = page["rel"]
    data["key"] = page["key"]
    return data


def shot(cdp: CDP, base: str, page: dict, w: int, h: int, png: Path) -> None:
    cdp.call("Emulation.setDeviceMetricsOverride", width=w, height=h,
             deviceScaleFactor=1, mobile=False)
    cdp.events.clear()
    cdp.call("Page.navigate", url=base + page["rel"])
    cdp.wait_event("Page.loadEventFired", 60)
    time.sleep(0.9)
    wait_ready(cdp, page["key"])
    png.parent.mkdir(parents=True, exist_ok=True)
    data = cdp.call("Page.captureScreenshot", format="png")["data"]
    png.write_bytes(base64.b64decode(data))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="UI 现状度量探针（只读）")
    ap.add_argument("--dist", default=str(ROOT / "site" / "dist"))
    ap.add_argument("--json", default=str(ROOT / ".tmp" / "ui-baseline" / "probe.json"))
    ap.add_argument("--shots", default=None, help="截图目录（给 390 档出图）")
    ap.add_argument("--shot-prefix", default="")
    ap.add_argument("--pages", default=None, help="只量这些 key（逗号分隔）")
    ap.add_argument("--viewports", default=None, help="390x844,1440x900")
    ap.add_argument("--no-shots", action="store_true")
    args = ap.parse_args(argv)

    dist = Path(args.dist)
    if not dist.is_dir():
        print(f"产物目录不存在：{dist}")
        return 2
    chrome = find_chrome()
    if chrome is None:
        print("找不到本机 Chrome —— SKIP")
        return 3
    only = set(args.pages.split(",")) if args.pages else None
    vps = [(int(v.split("x")[0]), int(v.split("x")[1]))
           for v in (args.viewports.split(",") if args.viewports else ["390x844", "1440x900"])]
    pages = [p for p in PAGES if (only is None or p["key"] in only)]

    site = Site(dist)
    srv = site.start(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    profile = Path(tempfile.mkdtemp(prefix="ui-probe-"))
    port = 9333
    proc = launch_chrome(chrome, port, profile)
    try:
        ws = _page_ws(port)
        cdp = CDP(ws)
        # 必须开 Page/Runtime 域，否则 `Page.loadEventFired` 事件根本不会下发，
        # wait_event 会白等满 60s 超时（本工位 2026-11-15 踩过：9 页共多花 25 分钟）。
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        out = {"dist": str(dist), "metric_script": "reports/2026-11-15-ui-baseline-probe.py",
               "runs": []}
        for page in pages:
            for (w, h) in vps:
                data = measure(cdp, base, page, w, h)
                data["viewport_tag"] = f"{w}x{h}"
                out["runs"].append(data)
                head = data.get("head") or {}
                br = data.get("borders") or {}
                bg = data.get("badges") or {}
                fo = data.get("fonts") or {}
                print(f"{page['key']:9s} {w}x{h}  h1={((head.get('h1') or {}).get('font') or {}).get('size')}"
                      f"  border={br.get('total_with_border')}  badge={bg.get('total')}"
                      f" (pill {bg.get('pill')}/box {bg.get('box')})  min_font={fo.get('min')}"
                      f"  lt12={fo.get('lt12')}  overflow={data.get('overflow', {}).get('over')}")
            if args.shots and not args.no_shots:
                # 手机档（390×844）出图：L16/L17 的「最新手机排版」证据
                png = Path(args.shots) / f"{args.shot_prefix}{page['shot']}-390.png"
                shot(cdp, base, page, 390, 844, png)
                print(f"          截图 {png}")
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"JSON {args.json}（{len(out['runs'])} 组）")
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
