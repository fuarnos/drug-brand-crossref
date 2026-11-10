"""首屏守卫：页面按「人一屏能看到、能操作什么」来验收，不按「数据塞得下」来验收。

规则来源（用户 2026-11-10 长期原则）：
    「之后你要改成按照人能看到什么来设计」—— 一屏之内必须看得到主操作和够用的条目，
    页头/筛选/提示/悬浮不许吃掉半屏，字不许小到看不清，宽屏不许把正文挤成一条。

做了什么：真浏览器（本机 Chrome + CDP，无 Playwright 依赖，复用 deploy/ui_surface_check.py
的 Chrome 启动 / 静态服务 / WS 客户端），4 个视口 × 6 个页型，每个「页面 × 视口」量 7 个指标：

    sig 指标                         口径
    1   AFCR 首屏有效内容比           主内容区可见面积 ÷ 视口面积（扣掉页头/页脚/筛选/提示/悬浮）
    2   primary 主操作可见性          搜索框 / 筛选入口 / 首个结果操作：在不在首屏、是否完整、上缘位置
    3   items 首屏可见条目数          结果行 / 矩阵行 / 卡片；≥90% 记 1 条，≥25% 记 0.5 条
    4   chrome 占比                   页头+页脚+筛选+提示+悬浮（可见部分并集）÷ 视口
    5   overlay sticky/fixed          覆盖面积占比 + 是否压住「不许遮」的东西（正文标题/表头/搜索框）
    6   font 字号                     正文最小字号 ≥16、辅助 ≥13、<12 直接违规、<14 占比（WARN 线）
    7   overflow 横向溢出             document.scrollWidth > innerWidth（手机最常见的整页 bug）

阈值（页面类型分档，见 docs/设计原则-按人能看到的来.md）：
    内容页（成分/名字/ATC/coverage）   AFCR ≥50% · 首屏 ≥5 条 · chrome ≤35%
    入口页（首页）                     搜索框完整可见且上缘 ≤40% 视口 · chrome ≤35% · AFCR ≥30%
    结果页（?q=）                      首屏 ≥5 条 · chrome ≤40% · AFCR ≥35% · 搜索框可见
    全站                               overlay ≤20% · 正文 ≥16px · 辅助 ≥13px · 无 <12px · 无横向溢出

用法：
    python deploy/first_screen_check.py                       # 扫 site/dist，全部页型 × 4 视口
    python deploy/first_screen_check.py --dist .tmp/dist-v0102
    python deploy/first_screen_check.py --base-url http://127.0.0.1:8000/
    python deploy/first_screen_check.py --viewports 390x844,1440x900
    python deploy/first_screen_check.py --json .tmp/first-screen/before.json --shots .tmp/first-screen/shots
    python deploy/first_screen_check.py --baseline .tmp/first-screen/before.json   # 退化 >5% 也 FAIL
    python deploy/first_screen_check.py --scroll-probe       # 额外量「滚到中部」时的悬浮条状态

退出码：0 = 全过（含 SKIP）；1 = 有 FAIL（含 baseline 退化）。
SKIP 的两种情况（都返回 0，只在输出里写明）：找不到本机 Chrome、产物目录不存在。

只读：被服务的文件一律只读打开，Chrome 用户目录放系统临时目录。
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui_surface_check import (  # noqa: E402  —— 复用 Chrome 启动 / WS-CDP / 只读静态服务
    CDP,
    Site,
    _page_ws,
    find_chrome,
    launch_chrome,
)

# 展开态脚本：只展开「筛选面板 / 类别条」，刻意不碰页头导航（导航 dropdown 是另一层交互，
# 展开后会盖住整页，会把「页面布局吃屏」的量测带偏）。
EXPAND_JS = r"""(function(){
  var n=0;
  // 成分页的筛选面板就是 <details class="mf-details"><summary>筛选 · 120/120 · 3/10</summary>…
  document.querySelectorAll('details.mf-details, .mf-slot details, .matrix-filters details').forEach(function(d){
    if(!d.open){ d.open = true; n++; }
  });
  document.querySelectorAll('.matrix-filters').forEach(function(f){ f.classList.add('mf-open'); n++; });
  document.querySelectorAll('.catquick.cat-hidden').forEach(function(f){ f.classList.remove('cat-hidden'); n++; });
  document.querySelectorAll('.res-skeleton').forEach(function(f){ f.remove(); });
  return n;
})()"""

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "site" / "dist"

# ── 视口 ────────────────────────────────────────────────────────────────────
# 手机（iPhone 12/13 逻辑像素）、平板、笔记本、2K 桌面：四档各覆盖一套 CSS 断点。
VIEWPORTS: list[tuple[int, int, str]] = [
    (390, 844, "390x844"),
    (768, 1024, "768x1024"),
    (1440, 900, "1440x900"),
    (2560, 1440, "2560x1440"),
]

# ── 页面类型与阈值 ──────────────────────────────────────────────────────────
# 阈值不是拍脑袋：内容页 50% 对应「一屏里至少一半是内容」；chrome 35% 对应
# 「页头+筛选+提示+悬浮最多吃掉三分之一屏」；首屏 5 条对应「一眼能比较」。
TYPE_THRESHOLDS: dict[str, dict] = {
    "content": {"afcr_min": 0.50, "items_min": 5.0, "chrome_max": 0.35},
    "entry": {"afcr_min": 0.30, "items_min": 0.0, "chrome_max": 0.35},
    "results": {"afcr_min": 0.35, "items_min": 5.0, "chrome_max": 0.40},
}
GLOBAL_THRESHOLDS = {
    # 带宽比（Lead 2026-11-10）：≥1280 视口内容带要占 66.7%（中间 2/3），<1280 要占满。
    # 容差 ±0.015（0.652–0.682）：桌面用 max-width:1680 兜住过长行，2560 视口下带宽比 = 65.6%；
    # 精确 2/3（1707px）会把单行拉到过长，为 0.1 pt 改宽度不划算，所以把容差写清并注明原因。
    "band_ratio_wide": 0.667,
    "band_ratio_wide_tol": 0.015,
    "band_ratio_narrow": 0.99,
    "overlay_max": 0.20,      # sticky/fixed 覆盖 ≤20% 视口
    "body_font_min": 16,      # 正文最小字号
    "aux_font_min": 13,       # 辅助文字最小字号
    "hard_font_min": 12,      # 低于 12px = 硬违规（不必看上下限）
    "lt14_ratio_warn": 0.50,  # <14px 文本占比超 50% 记 WARN（写进报告，不阻断）
    "cover_ratio": 0.25,      # 悬浮压住「不许遮」目标 ≥25% 面积 = 遮挡
}

# 指标口径版本：AFCR v2（分母 = 内容带面积）+ 新增 band_ratio。
# v0.10.1/v0.10.2 的基线是 v1 口径（分母 = 视口），**不可跨版本直接比**；
# compare_baseline 遇到口径不同会跳过 AFCR/band_ratio 并出一条说明。
METRIC_VERSION = "afcr-band-v2"

# 页面清单。primary = (标签, 选择器, 必须完整可见, 上缘上限占视口比 or None)
PAGES: list[dict] = [
    {
        "name": "home",
        "type": "entry",
        "paths": ["index.html"],
        "primary": [("search", "#q", True, 0.40)],
        "items": [".catgrid a", ".updlist li"],
        "items_min": 0,
        "must_not_cover": ["main h1", "#q", "main table thead"],
    },
    {
        "name": "results",
        "type": "results",
        "paths": ["index.html?q=%E6%B3%B0%E8%AF%BA&lang=zh"],
        "primary": [
            ("search", "#q", True, 0.45),
            ("first-result", "#reswrap tbody tr.br a, #reswrap tbody tr.br button", True, None),
        ],
        "items": ["#reswrap tbody tr.br", "#reswrap tbody tr.grp"],
        "items_min": 5,
        "must_not_cover": ["main h1", "#q", "main table thead"],
    },
    {
        # v0.10.3（task-16）：主视图 = 按国家分组清单，一行 `.mkrow` = 国家 × 规格；
        # 矩阵降级到 `?view=table`（只在内嵌矩阵的多市场页出现）。
        # items 用 items_mode=first-match：优先 .mkrow，老产物（矩阵页）回退 table.matrix tbody tr，
        # 两者不会同时计数（也就不会「首屏条目 0」假绿）。
        "name": "drug",
        "type": "content",
        "paths": ["drug/acetaminophen.html"],
        "primary": [("form-chips", ".formchips", False, 0.50),
                    ("filter-entry", ".matrix-filters", False, 0.50)],
        "items": [".mkrow", "table.matrix tbody tr"],
        "items_mode": "first-match",
        "items_min": 5,
        # 2026-11-11：成分页块头由 h3 提到 h2（修 h1→h3 跳级），选择器两种都留，
        # 否则新产物里 `.mkblock h3` 恒空 → 「不许遮」检查静默失效。
        "must_not_cover": ["main h1", ".mkblock h2, .mkblock h3", ".drug-sticky",
                           "table.matrix thead"],
    },
    {
        "name": "name",
        "type": "content",
        "paths": ["name/tylenol.html", "name/tylenol-8-hr-arthritis-pain.html"],
        "primary": [("first-action", "main a[href*='drug/']", False, None)],
        "items": ["main .card", "main ul.sub li", "main table tbody tr"],
        "items_min": 1,
        "must_not_cover": ["main h1", "main .card"],
    },
    {
        "name": "atc",
        "type": "content",
        "paths": ["atc/R06A.html", "atc/N02BE01.html", "atc/N02BE.html"],
        "primary": [("first-action", "main a[href*='drug/']", False, None)],
        "items": ["ul.atcmembers li", "ul.atclist li"],
        "items_min": 5,
        "must_not_cover": ["main h1", "main h2"],
    },
    {
        "name": "coverage",
        "type": "content",
        "paths": ["coverage.html"],
        "primary": [("sort-entry", ".covtools button", False, None)],
        "items": ["#covtable tbody tr"],
        "items_min": 5,
        "must_not_cover": ["main h1", "#covtable thead"],
    },
]

# 主内容区：优先 <main id="main">，退到 main/#main，再退到 body。
# 成分页「首屏条目」的默认选择器（矩阵页）。换模板时用 --rows-selector 覆盖，
# 不改脚本：python deploy/first_screen_check.py --rows-selector ".country-block .prow"
DRUG_ROWS_SEL = "table.matrix tbody tr"

MAIN_SEL = "main#main, main, #main"
# 「内容块」= 真正承载文字/数据的元素：用来求首屏内容带宽度，也用来判悬浮遮挡。
CONTENT_SEL = ("main h1, main h2, main h3, main p, main li, main td, main th, main tr,"
               " main .card, main .catchip, main .wrap, main table, main input")
# 判遮挡用的「正文块」：只认叶子级文本块，不含 .wrap / table 这种铺满整页的容器——
# 否则 sticky 搜索区会和 main .wrap 相交，被误判成「压住正文」（v0.10.2 实测踩过）。
OVERLAY_SEL = ("main h1, main h2, main h3, main p, main li, main td, main .card,"
               " main .catchip, main input")
# 「chrome」= 不算人要看的内容：页头、页脚、筛选、提示、工具栏、悬浮（含自动完成下拉）。
CHROME_SEL = [
    "header",
    "footer",
    ".tabbar",
    ".matrix-filters",
    ".mf-slot",
    ".notice",
    ".restools",
    ".covtools",
    ".res-nobrand",
    "#ac",
    ".lang-menu",
    ".sn-panel",
]
# 辅助文字：自身带这些 class/标签 = 辅助（≥13px 即可）；
# 向上只认「可以直接包住一段文字」的辅助容器（p.sub / div.sub / span.sub / footer / .notice…）。
# 特意不认 ul.sub / table.sub：成分页 ul.sub.atclist 里的 <li> 是**内容**（要 ≥16px），
# 不能因为外层 ul 带了 .sub 就整列降级成辅助文字。
AUX_SELF = ("small", "sup", "time", "label", "button", "summary", "select",
            ".sub", ".meta", ".tag", ".badge", ".st-badge", ".notice", ".exportnote",
            ".grp-count", ".res-more", ".atc-count", ".atc-src-line", ".date", ".stamp",
            ".count", ".c-det span", ".m-orig", ".rowform", ".idfields", "th")
# 正文块级元素（字号要 ≥16px）。内联标签不参与「正文字号」统计（见采集 JS 注释）。
BLOCK_TAGS = ("p", "li", "td", "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6",
              "blockquote", "figcaption")
AUX_ANC = ("footer", "small", "sup", ".notice", ".tag", ".badge", ".st-badge",
           "p.sub", "div.sub", "span.sub", "label", "button", "summary",
           ".meta", ".exportnote", ".res-more", ".atc-count", ".atc-src-line", ".date")

# ── 采集 JS ─────────────────────────────────────────────────────────────────
# 全部在页面里算完再返回 JSON：一次 round-trip，不靠 Python 拉 DOM。
MEASURE_JS = r"""(function(){
 try{
  var CFG = %(cfg)s;
  var vw = window.innerWidth, vh = window.innerHeight;
  var vpArea = vw * vh;
  var STEP = CFG.grid;                       // 面积用网格采样，天然处理矩形互相重叠
  function isHidden(cs){
    return cs.display==='none' || cs.visibility==='hidden' || cs.visibility==='collapse';
  }
  // 下拉面板 / 语言菜单靠 opacity:0 + pointer-events:none 藏起来，几何上仍占位，
  // 不排除就会把透明层算成「chrome」，把 chrome 占比虚高。
  function effOpacity(el){
    var op = 1, n = el, d = 0;
    while(n && n.nodeType===1 && d<12){
      var o = parseFloat(getComputedStyle(n).opacity);
      if(!isNaN(o)) op *= o;
      if(op <= 0.01) return 0;
      n = n.parentElement; d++;
    }
    return op;
  }
  function hidden(el, cs){
    if(isHidden(cs) || effOpacity(el) <= 0.01) return true;
    // 折叠的 <details> 里的面板 Chrome 仍会给出几何矩形（content-visibility:hidden），
    // 但人根本看不见：导航下拉/语言菜单就藏在这里，不排除会把 chrome 占比算虚高。
    if(el.tagName && el.tagName.toLowerCase() !== 'summary'
       && el.closest && el.closest('details:not([open])')) return true;
    return false;
  }
  function rect(el){
    if(!el) return {x:0, y:0, w:0, h:0};
    var b = el.getBoundingClientRect();
    return {x:b.left, y:b.top, w:b.width, h:b.height};
  }
  function clip(r){
    var x1=Math.max(r.x,0), y1=Math.max(r.y,0);
    var x2=Math.min(r.x+r.w,vw), y2=Math.min(r.y+r.h,vh);
    if(x2<=x1||y2<=y1) return null;
    return {x:x1,y:y1,w:x2-x1,h:y2-y1,area:(x2-x1)*(y2-y1)};
  }
  function inter(a,b){
    var x1=Math.max(a.x,b.x), y1=Math.max(a.y,b.y);
    var x2=Math.min(a.x+a.w,b.x+b.w), y2=Math.min(a.y+a.h,b.y+b.h);
    if(x2<=x1||y2<=y1) return {x:x1,y:y1,w:0,h:0,area:0};
    return {x:x1,y:y1,w:x2-x1,h:y2-y1,area:(x2-x1)*(y2-y1)};
  }
  function q1(sel){ try{ return document.querySelector(sel); }catch(e){ return null; } }
  function qa(sel, root){
    try{ return Array.prototype.slice.call((root||document).querySelectorAll(sel)); }
    catch(e){ return []; }
  }
  function sel(el){
    var t = el.tagName.toLowerCase();
    if(el.id) return t+'#'+el.id;
    var raw = (typeof el.className==='string') ? el.className : '';
    var cls = raw.trim() ? raw.trim().split(/\s+/).slice(0,3) : [];
    return t + (cls.length ? '.'+cls.join('.') : '');
  }
  function inside(r, x, y){ return x>=r.x && x<r.x+r.w && y>=r.y && y<r.y+r.h; }

  // ── 1+4. AFCR / chrome：网格采样 ─────────────────────────────────────────
  // 「主内容区」不是 main 的外框：宽屏下 main 会被 flex 撑满 2560，而真正有字的
  // 内容带只有 920（ATC 页的 268px 列表就是这么被掩盖的）。所以内容区 = main 的可见矩形
  // ∩ 真正有内容的水平带（首屏内所有内容块的 x 范围并集）。
  var mainEl = q1(CFG.main_sel) || document.body;
  var mainR = clip(rect(mainEl));
  var contentProbe = qa(CFG.content_sel);
  var contentRects = [];
  var overlayRectsProbe = [];
  for(var cp=0; cp<contentProbe.length && cp<4000; cp++){
    var ce = contentProbe[cp];
    if(ce.closest && ce.closest('details:not([open])')) continue;
    var ccs = getComputedStyle(ce);
    if(isHidden(ccs)) continue;
    var cb = ce.getBoundingClientRect();
    if(cb.width < 4 || cb.height < 4) continue;
    var cc2 = clip({x:cb.left,y:cb.top,w:cb.width,h:cb.height});
    if(cc2) contentRects.push({el:ce, rect:cc2});
  }
  // 遮挡判定专用（叶子块）
  qa(CFG.overlay_sel).forEach(function(el){
    if(el.closest && el.closest('details:not([open])')) return;
    var cs = getComputedStyle(el);
    if(isHidden(cs)) return;
    var b = el.getBoundingClientRect();
    if(b.width < 4 || b.height < 4) return;
    var c = clip({x:b.left,y:b.top,w:b.width,h:b.height});
    if(c) overlayRectsProbe.push({el:el, rect:c});
  });
  var band = mainR;
  if(mainR && contentRects.length){
    var bx1 = Infinity, bx2 = -Infinity;
    for(var bi=0; bi<contentRects.length; bi++){
      bx1 = Math.min(bx1, contentRects[bi].rect.x);
      bx2 = Math.max(bx2, contentRects[bi].rect.x + contentRects[bi].rect.w);
    }
    if(isFinite(bx1) && bx2 > bx1){
      band = {x:Math.max(bx1, mainR.x), y:mainR.y,
              w:Math.min(bx2, mainR.x+mainR.w) - Math.max(bx1, mainR.x),
              h:mainR.h};
      if(band.w <= 0) band = mainR;
      band.area = band.w * band.h;
    }
  }
  var chromeRects = [], chromeHits = [];
  for(var i=0;i<CFG.chrome_sel.length;i++){
    var list = qa(CFG.chrome_sel[i]);
    var hit = 0;
    for(var j=0;j<list.length;j++){
      var el = list[j];
      if(el.closest && mainEl !== el && el.contains(mainEl)) continue;
      var cs = getComputedStyle(el);
      if(hidden(el, cs)) continue;
      var c = clip(rect(el));
      if(!c) continue;
      chromeRects.push(c); hit++;
    }
    if(hit) chromeHits.push(CFG.chrome_sel[i]+'×'+hit);
  }
  var cells = 0, effective = 0, chromeCells = 0;
  if(band){
    for(var y=0;y<vh;y+=STEP){
      for(var x=0;x<vw;x+=STEP){
        var px = x + STEP/2, py = y + STEP/2;
        cells++;
        var inChrome = false;
        for(var k=0;k<chromeRects.length;k++){ if(inside(chromeRects[k],px,py)){ inChrome = true; break; } }
        if(inChrome) chromeCells++;
        if(!inChrome && inside(band,px,py)) effective++;
      }
    }
  }
  var cellArea = STEP*STEP;
  // AFCR 口径 v2（Lead 2026-11-10）：分母是**内容带**面积，不是视口面积。
  // 理由：用户要求桌面内容带收窄到中间 2/3，用视口当分母会把「按要求收窄」判成退化。
  // 绝对量（首屏条目 / 字号 / 横向溢出）另有独立判定，不会因此放松。
  var bandArea = band ? Math.max(1, band.w * band.h) : 1;
  var afcr = (effective*cellArea)/bandArea;
  var afcrVp = cells ? (effective*cellArea)/vpArea : 0;   // 旧口径，仅留档，跨版本不可比
  var bandRatio = vw ? (band ? band.w/vw : 0) : 0;         // 带宽比
  var chromeRatio = cells ? (chromeCells*cellArea)/vpArea : 0;
  var chromeOverflow = chromeRatio > 1 ? 1 : 0;   // chrome 互相重叠时的兜底

  // ── 2. 主操作可见性 ────────────────────────────────────────────────────
  var primary = [];
  for(var p=0;p<CFG.primary.length;p++){
    var spec = CFG.primary[p];
    var el = q1(spec.sel);
    var rec = {label:spec.label, sel:spec.sel, found:!!el};
    if(el){
      var b = rect(el), c = clip(b);
      rec.w = Math.round(b.w); rec.h = Math.round(b.h);
      rec.visible = !!c;
      rec.vis_ratio = (b.w*b.h) > 0 ? (c ? c.area/(b.w*b.h) : 0) : 0;
      rec.top_ratio = vh ? Math.max(0, Math.min(1, b.y/vh)) : null;
      rec.full = !!c && rec.vis_ratio >= 0.98 && b.y >= -1;
    }
    primary.push(rec);
  }

  // ── 3. 首屏可见条目数（半条 = 0.5）──────────────────────────────────────
  var items = {count:0, seen:0, available:0, by_sel:[], rows:[], sel_used:null};
  var seenSet = [];
  for(var s=0;s<CFG.items.length;s++){
    var list = qa(CFG.items[s]);
    // first-match：模板换过一次（矩阵 → 国家分组清单）时，用第一个真有命中的选择器，
    // 避免「新选择器 0 命中 → 首屏条目 0」这种假绿/假红交错。
    if(CFG.items_mode === 'first-match' && items.sel_used !== null && list.length === 0) continue;
    if(CFG.items_mode === 'first-match' && items.sel_used === null && list.length === 0) continue;
    var sub = 0;
    for(var q=0;q<list.length && q<600;q++){
      var el = list[q];
      if(seenSet.indexOf(el)>=0) continue;
      seenSet.push(el);
      items.available++;
      if(items.sel_used === null) items.sel_used = CFG.items[s];
      var bb = el.getBoundingClientRect();
      if(bb.width < 4 || bb.height < 4) continue;
      var cc = clip({x:bb.left,y:bb.top,w:bb.width,h:bb.height});
      if(!cc) continue;
      var frac = cc.area / (bb.width*bb.height);
      if(frac >= 0.90) sub += 1;
      else if(frac >= 0.25) sub += 0.5;
      items.seen++;
      if(items.rows.length < 8) items.rows.push({sel:sel(el), frac:Math.round(frac*100)/100});
    }
    if(sub) items.by_sel.push(CFG.items[s]+'='+sub);
    items.count += sub;
  }

  // ── 5. sticky/fixed 覆盖 + 遮挡 ────────────────────────────────────────
  var all = qa(CFG.sticky_scan_sel).slice(0, CFG.sticky_max_scan);
  var overlays = [], overlayRects = [];
  for(var o=0;o<all.length;o++){
    var el = all[o];
    var cs = getComputedStyle(el);
    var pos = cs.position;
    if(pos!=='sticky' && pos!=='fixed') continue;
    // 表格行头/表头是「横向固定列」（sticky left，top:auto），不是竖向悬浮条：
    // 它们压住的是同一行的其他单元格，不参与悬浮占比与遮挡判定。
    if(pos==='sticky' && cs.top==='auto' && cs.left!=='auto') continue;
    if(hidden(el, cs)) continue;
    var ob = el.getBoundingClientRect();
    if(ob.width < 8 || ob.height < 8) continue;
    var oc = clip({x:ob.left,y:ob.top,w:ob.width,h:ob.height});
    if(!oc) continue;
    overlays.push({el:el, rect:oc, pos:pos, sel:sel(el), z:cs.zIndex,
                   w:Math.round(ob.width), h:Math.round(ob.height)});
  }
  // 「覆盖面积」只算真的压在正文上的 sticky/fixed：position:sticky 在滚动顶部时还在流里，
  // 压在正文上才计入（否则和 chrome 重复计数）。contentRects 上面已经采好。
  var overlayArea = 0, overlayList = [], coveredTargets = [];
  var targets = [];
  for(var t=0;t<CFG.must_not_cover.length;t++){
    qa(CFG.must_not_cover[t]).forEach(function(el){
      var b = el.getBoundingClientRect();
      if(b.width < 4 || b.height < 4) return;
      var c = clip({x:b.left,y:b.top,w:b.width,h:b.height});
      if(!c) return;
      if(c.area < (b.width*b.height)*0.98) return;   // 只判「完整在首屏里」的目标
      targets.push({el:el, rect:c, sel:sel(el)});
    });
  }
  var g = Math.max(2, Math.round(STEP/2));   // 覆盖面积用更细的网格求并集
  var covered = {};
  for(var oi=0; oi<overlays.length; oi++){
    var ov = overlays[oi];
    var hitsContent = false;
    for(var ci=0; ci<overlayRectsProbe.length; ci++){
      var it = inter(ov.rect, overlayRectsProbe[ci].rect);
      if(it.area > 0 && !ov.el.contains(overlayRectsProbe[ci].el)){ hitsContent = true; break; }
    }
    var floating = ov.pos === 'fixed' || hitsContent;
    if(floating){
      for(var yy=Math.floor(ov.rect.y); yy<ov.rect.y+ov.rect.h; yy+=g){
        for(var xx=Math.floor(ov.rect.x); xx<ov.rect.x+ov.rect.w; xx+=g){
          covered[xx+','+yy] = 1;
        }
      }
      overlayList.push({sel:ov.sel, pos:ov.pos, w:ov.w, h:ov.h,
                        x:Math.round(ov.rect.x), y:Math.round(ov.rect.y),
                        area_ratio:Math.round(ov.rect.area/vpArea*1000)/1000,
                        z:ov.z, covers_content:hitsContent});
    }
    for(var ti=0; ti<targets.length; ti++){
      var tg = targets[ti];
      if(ov.el.contains(tg.el) || tg.el.contains(ov.el)) continue;
      var iv = inter(ov.rect, tg.rect);
      if(iv.area >= tg.rect.area * CFG.cover_ratio){
        coveredTargets.push({target:tg.sel, overlay:ov.sel, pos:ov.pos,
                             cover_ratio:Math.round(iv.area/tg.rect.area*100)/100});
      }
    }
  }
  var overlayRatio = Object.keys(covered).length * (g*g) / vpArea;

  // ── 6. 字号（只量主内容区、只量首屏可见的文字节点）──────────────────────
  var F = {nodes:0, lt14:0, body_min:null, aux_min:null, hard_min:null,
           body_min_where:'', aux_min_where:'', hard_where:'', size_hist:{}};
  var mainNodes = mainEl.querySelectorAll('*');
  var maxNodes = Math.min(mainNodes.length, CFG.font_max_nodes);
  for(var n=0;n<maxNodes;n++){
    var el = mainNodes[n];
    var tag = el.tagName.toLowerCase();
    if(tag==='script'||tag==='style'||tag==='noscript'||tag==='template'
       ||tag==='svg'||tag==='path'||tag==='option') continue;
    // 带文字就算（含包在 <span>/<b> 里的文字：<h1><span>名</span></h1> 这种很常见，
    // 只认直系文本节点会漏掉整块正文）。内联子元素本身不参与最小值，不会重复计数。
    if(!(el.textContent||'').trim().length) continue;
    var cs = getComputedStyle(el);
    if(hidden(el, cs)) continue;
    var b = el.getBoundingClientRect();
    if(b.width<2 || b.height<2) continue;
    if(b.bottom<0 || b.top>vh || b.right<0 || b.left>vw) continue;   // 只算首屏可见
    var fs = parseFloat(cs.fontSize);
    if(!fs || isNaN(fs)) continue;
    F.nodes++;
    var key = String(Math.round(fs));
    F.size_hist[key] = (F.size_hist[key]||0) + 1;
    if(fs < 14) F.lt14++;
    if(F.hard_min===null || fs < F.hard_min){ F.hard_min = fs; F.hard_where = sel(el)+' «'+(el.textContent||'').trim().slice(0,36)+'»'; }
    // 分类：aux = 自身/近祖先是辅助（≥13px）；body = 块级内容元素（≥16px）；
    // 其余内联小标签（span/code/b/em…）只进 <12px 硬门槛与 <14px 占比，不进两边的最小值——
    // 它们的字号是继承来的，拿去当「正文字号」只会把结论带偏。
    var aux = false, inAux = false;
    var cur = el, depth = 0;
    while(cur && cur!==mainEl && depth<4){
      var list = (depth===0) ? CFG.aux_self : CFG.aux_anc;
      for(var a=0;a<list.length;a++){
        try{ if(cur.matches(list[a])){ aux = true; break; } }catch(e){}
      }
      if(aux) break;
      cur = cur.parentElement; depth++;
    }
    inAux = aux;
    var isBlock = !!CFG.block_tags[tag];
    if(isBlock && !inAux){
      if(F.body_min===null || fs < F.body_min){
        F.body_min = fs;
        F.body_min_where = sel(el)+' «'+(el.textContent||'').trim().slice(0,36)+'»';
      }
    }else if(inAux){
      if(F.aux_min===null || fs < F.aux_min){
        F.aux_min = fs;
        F.aux_min_where = sel(el)+' «'+(el.textContent||'').trim().slice(0,36)+'»';
      }
    }else{
      F.inline_nodes = (F.inline_nodes||0) + 1;
    }
  }
  F.lt14_ratio = F.nodes ? F.lt14/F.nodes : 0;

  // ── 7. 横向溢出 ────────────────────────────────────────────────────────
  var docW = document.documentElement.scrollWidth;
  var overflow = docW > vw + 1;
  var offenders = [];
  if(overflow){
    var cand = qa('body *').slice(0, CFG.sticky_max_scan);
    for(var of=0; of<cand.length && offenders.length<6; of++){
      var el = cand[of];
      var ob2 = el.getBoundingClientRect();
      if(ob2.width < 8 || ob2.height < 8) continue;
      if(ob2.right <= vw+1 && ob2.left >= -1) continue;
      var cs2 = getComputedStyle(el);
      if(hidden(el, cs2)) continue;
      // 自己就在横向滚动容器里的不算（那是设计内的横向滚动）
      var anc = el.parentElement, scrolled = false;
      while(anc && anc!==document.body){
        var acs = getComputedStyle(anc);
        if((acs.overflowX==='auto'||acs.overflowX==='scroll'||acs.overflowX==='hidden')){ scrolled = true; break; }
        anc = anc.parentElement;
      }
      if(scrolled) continue;
      offenders.push({sel:sel(el), left:Math.round(ob2.left), right:Math.round(ob2.right),
                      w:Math.round(ob2.width)});
    }
  }

  return JSON.stringify({
    vw:vw, vh:vh, doc_h:Math.round(document.documentElement.scrollHeight),
    href: location.href, ready_state: document.readyState,
    main_sel: mainEl===document.body ? 'body' : (mainEl.id ? '#'+mainEl.id : mainEl.tagName.toLowerCase()),
    main_h: mainR ? Math.round(mainR.h) : 0,
    main_w: mainR ? Math.round(mainR.w) : 0,
    band_w: band ? Math.round(band.w) : 0,
    content_blocks: contentRects.length,
    metrics: {afcr: afcr, afcr_vp: afcrVp, band_ratio: bandRatio,
              chrome_ratio: chromeRatio, items: items.count,
              overlay_ratio: overlayRatio, overflow: overflow?1:0},
    primary: primary,
    items_detail: {by_sel: items.by_sel, visible_elements: items.seen,
                   available: items.available, sel_used: items.sel_used,
                   samples: items.rows},
    chrome_hits: chromeHits,
    overlays: overlayList,
    overlay_covered_targets: coveredTargets,
    fonts: F,
    overflow_offenders: offenders,
    scroll_y: Math.round(window.scrollY||0)
  });
 }catch(e){
  return JSON.stringify({__error: String(e && e.message || e),
                         __stack: String(e && e.stack || '').split('\n').slice(0,4).join(' | '),
                         href: location.href, ready: document.readyState,
                         has_body: !!document.body});
 }
})()"""

# 滚动探针：滚到文档中部，量「悬浮条还在不在、压没压住表头」。
# 只做证据采集（不参与 7 指标判定），task-2 的「成分页滚动中悬浮条可见且不遮表头」用它。
SCROLL_JS = r"""(function(){
  var vw = window.innerWidth, vh = window.innerHeight;
  function sel(el){
    var t = el.tagName.toLowerCase();
    if(el.id) return t+'#'+el.id;
    var raw = (typeof el.className==='string') ? el.className : '';
    var cls = raw.trim() ? raw.trim().split(/\s+/).slice(0,3) : [];
    return t + (cls.length ? '.'+cls.join('.') : '');
  }
  function clip(r){
    var x1=Math.max(r.x,0), y1=Math.max(r.y,0);
    var x2=Math.min(r.x+r.w,vw), y2=Math.min(r.y+r.h,vh);
    if(x2<=x1||y2<=y1) return null;
    return {x:x1,y:y1,w:x2-x1,h:y2-y1,area:(x2-x1)*(y2-y1)};
  }
  function inter(a,b){
    var x1=Math.max(a.x,b.x), y1=Math.max(a.y,b.y);
    var x2=Math.min(a.x+a.w,b.x+b.w), y2=Math.min(a.y+a.h,b.y+b.h);
    if(x2<=x1||y2<=y1) return {w:0,h:0,area:0};
    return {x:x1,y:y1,w:x2-x1,h:y2-y1,area:(x2-x1)*(y2-y1)};
  }
  var out = {scroll_y: Math.round(window.scrollY||0), doc_h: document.documentElement.scrollHeight,
             overlays: [], covered: []};
  var all = document.querySelectorAll('body *');
  var limit = %(limit)d;
  var targets = [];
  [['thead','table.matrix thead, main table thead'], ['h1','main h1'],
   ['search','#q'], ['filter','.matrix-filters'], ['rowhead','table.matrix tbody tr .m-spec']
  ].forEach(function(pair){
    document.querySelectorAll(pair[1]).forEach(function(el){
      var b = el.getBoundingClientRect();
      if(b.width<4||b.height<4) return;
      var c = clip({x:b.left,y:b.top,w:b.width,h:b.height});
      if(!c) return;
      targets.push({kind:pair[0], el:el, rect:c, sel:sel(el)});
    });
  });
  for(var i=0;i<Math.min(all.length, limit);i++){
    var el = all[i], cs = getComputedStyle(el);
    if(cs.position!=='sticky' && cs.position!=='fixed') continue;
    if(cs.display==='none'||cs.visibility==='hidden') continue;
    var b = el.getBoundingClientRect();
    if(b.width<8||b.height<8) continue;
    var c = clip({x:b.left,y:b.top,w:b.width,h:b.height});
    if(!c) continue;
    out.overlays.push({sel:sel(el), pos:cs.position, x:Math.round(b.left), y:Math.round(b.top),
                       w:Math.round(b.width), h:Math.round(b.height), z:cs.zIndex,
                       text:(el.innerText||'').trim().slice(0,40)});
    for(var t=0;t<targets.length;t++){
      var tg = targets[t];
      if(el.contains(tg.el) || tg.el.contains(el)) continue;
      var iv = inter(c, tg.rect);
      if(iv.area >= tg.rect.area*0.25){
        out.covered.push({target:tg.kind, target_sel:tg.sel, overlay:sel(el),
                          cover_ratio: Math.round(iv.area/tg.rect.area*100)/100});
      }
    }
  }
  return JSON.stringify(out);
})()"""

# 等待页面进入「可测状态」：JS 渲染的筛选器 / 结果行到位，骨架屏消失。
READY_JS = r"""(function(){
  var need = %(need)s;
  if(need==='results'){
    if(document.querySelector('.res-skeleton')) return 'loading';
    if(document.querySelector('#reswrap tbody tr')) return 'ready';
    if(document.querySelector('#out .notice, #out .card, #identity')) return 'ready';
    return 'loading';
  }
  if(need==='filters'){
    if(document.querySelector('.matrix-filters')) return 'ready';
    return 'loading';
  }
  return 'ready';
})()"""

READY_NEED = {"home": "none", "results": "results", "drug": "filters",
              "name": "none", "atc": "none", "coverage": "none"}


def _cfg(page: dict) -> dict:
    """把 Python 侧配置塞进页面 JS。"""
    return {
        "main_sel": MAIN_SEL,
        "content_sel": CONTENT_SEL,
        "overlay_sel": OVERLAY_SEL,
        "chrome_sel": CHROME_SEL,
        "primary": [{"label": p[0], "sel": p[1]} for p in page["primary"]],
        "items": page["items"],
        "items_mode": page.get("items_mode", "union"),
        "must_not_cover": page["must_not_cover"],
        "aux_self": list(AUX_SELF),
        "aux_anc": list(AUX_ANC),
        "block_tags": {k: 1 for k in BLOCK_TAGS},
        "grid": 6,
        "cover_ratio": GLOBAL_THRESHOLDS["cover_ratio"],
        "sticky_scan_sel": "body *",
        "sticky_max_scan": 30000,
        "font_max_nodes": 20000,
    }


def _eval_js(cdp: CDP, expr: str, *, await_promise: bool = False, timeout: float = 120):
    res = cdp.call("Runtime.evaluate", timeout=timeout, expression=expr,
                   returnByValue=True, awaitPromise=await_promise)
    if res.get("exceptionDetails"):
        raise RuntimeError(f"页面 JS 抛错：{json.dumps(res['exceptionDetails'])[:300]}")
    return (res.get("result") or {}).get("value")


def _wait_ready(cdp: CDP, page: str, timeout: float = 15.0) -> bool:
    """等 JS 把筛选器 / 结果行渲染出来；超时也继续（后续指标会把「没内容」量出来）。"""
    need = READY_NEED.get(page, "none")
    if need == "none":
        time.sleep(0.45)
        return True
    js = READY_JS % {"need": json.dumps(need)}
    end = time.time() + timeout
    while time.time() < end:
        try:
            if _eval_js(cdp, js) == "ready":
                time.sleep(0.35)   # 让最后一帧布局稳定（字体/图片高度）
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.25)
    return False


def _wait_document(cdp: CDP, timeout: float = 20.0) -> str:
    """等 document.readyState 到 complete（loadEventFired 偶发抢跑时兜底）。"""
    end = time.time() + timeout
    state = "?"
    while time.time() < end:
        try:
            state = _eval_js(cdp, "document.readyState") or "?"
        except Exception:  # noqa: BLE001
            state = "?"
        if state == "complete":
            return state
        time.sleep(0.1)
    return state


def scan(cdp: CDP, url: str, width: int, height: int, page: dict,
         scroll_probe: bool, expand: bool = False) -> dict:
    cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
             deviceScaleFactor=1, mobile=False)
    cdp.events.clear()
    cdp.call("Page.navigate", url=url)
    cdp.wait_event("Page.loadEventFired", 60)
    _wait_document(cdp)
    ready = _wait_ready(cdp, page["name"])
    if expand:
        # 展开态：把 <details> / 筛选面板 / 被折叠的类别全部打开，量「点开之后」吃多少屏。
        # 这是证据（反例数字的来源），不参与判定。
        _eval_js(cdp, EXPAND_JS)
        time.sleep(0.45)
    js = MEASURE_JS % {"cfg": json.dumps(_cfg(page), ensure_ascii=False)}
    data = json.loads(_eval_js(cdp, js) or "{}")
    if data.get("__error"):
        raise RuntimeError(f"采集失败：{data.get('__error')} @ {data.get('href')} "
                           f"({data.get('__stack')})")
    data["ready"] = ready
    if scroll_probe:
        _eval_js(cdp, "(function(){window.scrollTo(0, Math.round(document.documentElement.scrollHeight*0.5)); return 1;})()")
        time.sleep(0.45)
        try:
            data["scrolled"] = json.loads(_eval_js(cdp, SCROLL_JS % {"limit": 30000}) or "{}")
        except Exception as exc:  # noqa: BLE001
            data["scrolled"] = {"error": str(exc)[:200]}
        _eval_js(cdp, "(function(){window.scrollTo(0,0); return 1;})()")
        time.sleep(0.15)
    return data


def judge(page: dict, viewport: str, data: dict) -> tuple[list[dict], list[dict]]:
    """按页面类型阈值判定，返回 (fails, warns)。"""
    th = TYPE_THRESHOLDS[page["type"]]
    m = data.get("metrics") or {}
    fonts = data.get("fonts") or {}
    fails: list[dict] = []
    warns: list[dict] = []

    def bad(metric: str, value, limit, unit: str = "") -> None:
        fails.append({"metric": metric, "value": value, "limit": limit,
                      "msg": f"{metric} {value}{unit} 未达 {limit}{unit}"})

    afcr = float(m.get("afcr") or 0)
    if afcr < th["afcr_min"]:
        bad("afcr", round(afcr, 3), th["afcr_min"])
    # 带宽比：宽屏要中间 2/3，窄屏要占满（收窄内容带是产品决定，但比例得守住）
    bw = float(m.get("band_ratio") or 0)
    vw = int(data.get("vw") or 0)
    target = GLOBAL_THRESHOLDS["band_ratio_wide"]
    tol = GLOBAL_THRESHOLDS["band_ratio_wide_tol"]
    if vw >= 1280:
        if abs(bw - target) > tol:
            bad("band_ratio", round(bw, 3), f"{target}±{tol}")
    elif bw < GLOBAL_THRESHOLDS["band_ratio_narrow"]:
        bad("band_ratio", round(bw, 3), GLOBAL_THRESHOLDS["band_ratio_narrow"])
    items = float(m.get("items") or 0)
    items_min = page.get("items_min", th["items_min"])
    available = float((data.get("items_detail") or {}).get("available") or 0)
    # 页面本来就没有那么多条（如「泰诺」只命中 3 条）时，不要求首屏 ≥5——
    # 门槛按「实际有多少条」收敛，避免用不可能达标的标准制造假红。
    need = min(items_min, available) if available else items_min
    if need and items < need:
        bad("items", items, need)
    chrome = float(m.get("chrome_ratio") or 0)
    if chrome > th["chrome_max"]:
        bad("chrome_ratio", round(chrome, 3), th["chrome_max"])
    overlay = float(m.get("overlay_ratio") or 0)
    if overlay > GLOBAL_THRESHOLDS["overlay_max"]:
        bad("overlay_ratio", round(overlay, 3), GLOBAL_THRESHOLDS["overlay_max"])
    if data.get("overlay_covered_targets"):
        bad("overlay_blocks", len(data["overlay_covered_targets"]), 0)
    if m.get("overflow"):
        bad("overflow", 1, 0)

    # 主操作：required（第三个字段）→ 必须完整可见；带 top_max 的还要看位置。
    for spec, rec in zip(page["primary"], data.get("primary") or []):
        label, _sel, must_full, top_max = spec
        if not rec.get("found"):
            if must_full:
                bad(f"primary:{label}", "missing", "found")
            continue
        if must_full and not rec.get("full"):
            bad(f"primary:{label}", "not-full", "fully-visible")
        if top_max is not None and rec.get("top_ratio") is not None:
            if rec["top_ratio"] > top_max:
                bad(f"primary:{label}:top", round(rec["top_ratio"], 3), top_max)

    body_min = fonts.get("body_min")
    aux_min = fonts.get("aux_min")
    hard_min = fonts.get("hard_min")
    if body_min is not None and body_min < GLOBAL_THRESHOLDS["body_font_min"]:
        bad("min_body_font", body_min, GLOBAL_THRESHOLDS["body_font_min"], "px")
    if aux_min is not None and aux_min < GLOBAL_THRESHOLDS["aux_font_min"]:
        bad("min_aux_font", aux_min, GLOBAL_THRESHOLDS["aux_font_min"], "px")
    if hard_min is not None and hard_min < GLOBAL_THRESHOLDS["hard_font_min"]:
        bad("min_font", hard_min, GLOBAL_THRESHOLDS["hard_font_min"], "px")
    if body_min is None and fonts.get("nodes"):
        warns.append({"metric": "min_body_font", "value": None,
                      "limit": GLOBAL_THRESHOLDS["body_font_min"],
                      "msg": "首屏没有块级正文元素（可能整屏都是 chrome），需人工看一眼"})
    lt14 = float(fonts.get("lt14_ratio") or 0)
    if lt14 > GLOBAL_THRESHOLDS["lt14_ratio_warn"]:
        warns.append({"metric": "lt14_ratio", "value": round(lt14, 3),
                      "limit": GLOBAL_THRESHOLDS["lt14_ratio_warn"],
                      "msg": f"<14px 文本占比 {lt14:.0%}（>50%，写进报告，不阻断）"})
    return fails, warns


# ── baseline 对比 ───────────────────────────────────────────────────────────
HIGHER_BETTER = ("afcr", "items")
LOWER_BETTER = ("chrome_ratio", "overlay_ratio", "lt14_ratio", "overflow")
REGRESSION_TOLERANCE = 0.05     # 退化 >5%（相对）即 FAIL


def compare_baseline(cur: dict, base: dict) -> list[dict]:
    """逐 (页面, 视口, 指标) 比；退化 >5% 或 baseline 有的项这次缺了 → FAIL。"""
    def index(payload: dict) -> dict[tuple[str, str], dict]:
        out = {}
        for rec in payload.get("pages") or []:
            out[(rec.get("page"), rec.get("viewport"))] = rec
        return out

    b, c = index(base), index(cur)
    regressions: list[dict] = []
    base_ver = base.get("metric_version") or "afcr-viewport-v1"
    cur_ver = cur.get("metric_version") or "afcr-viewport-v1"
    skip_metrics: set[str] = set()
    if base_ver != cur_ver:
        skip_metrics = {"afcr", "band_ratio"}
        regressions.append({
            "page": "*", "viewport": "*", "metric": "metric_version",
            "before": base_ver, "after": cur_ver, "note": True,
            "msg": f"口径变了（{base_ver} → {cur_ver}）：AFCR / band_ratio 不参与跨口径对比，"
                   f"其余指标照常比",
        })
    for key, brec in b.items():
        crec = c.get(key)
        if crec is None:
            regressions.append({"page": key[0], "viewport": key[1], "metric": "scan",
                                "before": "present", "after": "missing",
                                "msg": "baseline 有这一组（页面×视口），本轮没扫到"})
            continue
        bm = dict(brec.get("metrics") or {})
        bm.update({k: v for k, v in (brec.get("fonts") or {}).items() if k in
                   ("body_min", "aux_min", "hard_min")})
        cm = dict(crec.get("metrics") or {})
        cm.update({k: v for k, v in (crec.get("fonts") or {}).items() if k in
                   ("body_min", "aux_min", "hard_min")})
        for metric in HIGHER_BETTER:
            if metric in skip_metrics:
                continue
            bv, cv = bm.get(metric), cm.get(metric)
            if bv is None or cv is None or not isinstance(bv, (int, float)):
                continue
            if float(bv) <= 0:
                continue
            drop = (float(bv) - float(cv)) / float(bv)
            if drop > REGRESSION_TOLERANCE:
                regressions.append({"page": key[0], "viewport": key[1], "metric": metric,
                                    "before": bv, "after": cv,
                                    "delta_pct": round(-drop * 100, 1),
                                    "msg": f"{metric} 从 {bv} 退到 {cv}（-{drop:.1%}）"})
        for metric in LOWER_BETTER:
            if metric in skip_metrics:
                continue
            bv, cv = bm.get(metric), cm.get(metric)
            if bv is None or cv is None or not isinstance(bv, (int, float)):
                continue
            if float(bv) <= 0:
                if float(cv) > 0:
                    regressions.append({"page": key[0], "viewport": key[1], "metric": metric,
                                        "before": bv, "after": cv,
                                        "msg": f"{metric} 从 {bv} 变成 {cv}（baseline 为 0）"})
                continue
            rise = (float(cv) - float(bv)) / float(bv)
            if rise > REGRESSION_TOLERANCE:
                regressions.append({"page": key[0], "viewport": key[1], "metric": metric,
                                    "before": bv, "after": cv,
                                    "delta_pct": round(rise * 100, 1),
                                    "msg": f"{metric} 从 {bv} 涨到 {cv}（+{rise:.1%}）"})
        for metric in ("body_min", "aux_min", "hard_min"):
            bv, cv = bm.get(metric), cm.get(metric)
            if bv is None or cv is None or not isinstance(bv, (int, float)):
                continue
            if float(bv) <= 0:
                continue
            drop = (float(bv) - float(cv)) / float(bv)
            if drop > REGRESSION_TOLERANCE:
                regressions.append({"page": key[0], "viewport": key[1], "metric": metric,
                                    "before": bv, "after": cv,
                                    "delta_pct": round(-drop * 100, 1),
                                    "msg": f"{metric} 从 {bv}px 变到 {cv}px（-{drop:.1%}）"})
    return [r for r in regressions if not r.get("note")], \
        [r for r in regressions if r.get("note")]


def _resolve(page: dict, dist: Path | None) -> str | None:
    if dist is None:
        return page["paths"][0]
    for rel in page["paths"]:
        if (dist / rel.split("?")[0]).is_file():
            return rel
    return None


def run_checks(dist: Path | None, base_url: str | None, chrome: Path,
               viewports: list[tuple[int, int, str]], scroll_probe: bool,
               shots: Path | None, only: list[str] | None,
               expand: bool = False, gate: bool = False,
               rows_selector: str | None = None,
               table_view_probe: bool = False) -> dict:
    site = Site(dist) if dist is not None else None
    srv = site.start(0) if site is not None else None
    base = f"http://127.0.0.1:{srv.server_address[1]}/" if srv is not None else (base_url or "")
    port = 9431
    profile = Path(tempfile.mkdtemp(prefix="first-screen-chrome-"))
    out: dict = {
        "dist": str(dist) if dist else None,
        "base": base,
        "chrome": str(chrome),
        "viewports": [v[2] for v in viewports],
        # 口径版本：AFCR v2 = 带内占比（v0.10.3 起）。跨口径的 baseline 不比 AFCR。
        "metric_version": METRIC_VERSION,
        "thresholds": {"types": TYPE_THRESHOLDS, "global": GLOBAL_THRESHOLDS},
        "pages": [],
        "expanded": [],
        "table_view": [],
        "skipped": [],
        "shots": [],
    }
    pages = [p for p in PAGES if not only or p["name"] in only]
    if rows_selector:
        # 成分页换了模板时，条目选择器从这里覆盖（其余页型不动）
        pages = [dict(p, items=[rows_selector]) if p["name"] == "drug" else p
                 for p in pages]
    proc: subprocess.Popen | None = None
    profile_root = profile

    def start_chrome() -> tuple[subprocess.Popen, CDP]:
        nonlocal profile
        p = launch_chrome(chrome, port, profile)
        c = CDP(_page_ws(port))
        c.call("Page.enable")
        c.call("Runtime.enable")
        try:
            c.call("Storage.clearDataForOrigin", origin=base.rstrip("/"),
                   storageTypes="local_storage")
        except Exception:  # noqa: BLE001
            pass
        return p, c

    def stop_chrome(p: subprocess.Popen | None) -> None:
        if p is None:
            return
        try:
            p.terminate()
            p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    try:
        proc, cdp = start_chrome()
        for page in pages:
            rel = _resolve(page, dist)
            if rel is None:
                out["skipped"].append({"page": page["name"], "reason": "产物里没有该页",
                                       "tried": page["paths"]})
                print(f"  [SKIP] {page['name']}: 产物里没有该页（试过 {', '.join(page['paths'])}）")
                continue
            url = base + rel
            for width, height, vp in viewports:
                data: dict = {}
                last_err = ""
                for attempt in (1, 2):
                    try:
                        data = scan(cdp, url, width, height, page, scroll_probe)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_err = str(exc)[:300]
                        # 浏览器/连接死了就重开一个（长跑时偶发，不能让整轮中断）
                        stop_chrome(proc)
                        time.sleep(0.6)
                        proc, cdp = start_chrome()
                        time.sleep(0.3)
                if not data:
                    rec = {"page": page["name"], "type": page["type"], "viewport": vp,
                           "url": rel, "error": last_err, "metrics": {}, "fonts": {},
                           "primary": [], "fails": [{"metric": "scan", "value": "error",
                                                     "limit": "ok", "msg": f"采集失败：{last_err}"}],
                           "warns": []}
                    out["pages"].append(rec)
                    print(f"  [FAIL] {page['name']:8} {vp:10} 采集失败：{last_err}")
                    continue
                fails, warns = judge(page, vp, data)
                rec = {
                    "page": page["name"],
                    "type": page["type"],
                    "viewport": vp,
                    "vw": data.get("vw"),
                    "url": rel,
                    "href": data.get("href"),
                    "metrics": data.get("metrics") or {},
                    "fonts": data.get("fonts") or {},
                    "primary": data.get("primary") or [],
                    "items_detail": data.get("items_detail") or {},
                    "chrome_hits": data.get("chrome_hits") or [],
                    "overlays": data.get("overlays") or [],
                    "overlay_covered_targets": data.get("overlay_covered_targets") or [],
                    "overflow_offenders": data.get("overflow_offenders") or [],
                    "main_sel": data.get("main_sel"),
                    "main_h": data.get("main_h"),
                    "main_w": data.get("main_w"),
                    "band_w": data.get("band_w"),
                    "content_blocks": data.get("content_blocks"),
                    "doc_h": data.get("doc_h"),
                    "ready": data.get("ready"),
                    "fails": fails,
                    "warns": warns,
                }
                if "scrolled" in data:
                    rec["scrolled"] = data["scrolled"]
                out["pages"].append(rec)
                if expand:
                    try:
                        edata = scan(cdp, url, width, height, page, False, expand=True)
                        em = edata.get("metrics") or {}
                        ef = edata.get("fonts") or {}
                        out["expanded"].append({
                            "page": page["name"], "viewport": vp, "url": rel,
                            "metrics": em, "fonts": ef,
                            "chrome_hits": edata.get("chrome_hits") or [],
                            "items_detail": edata.get("items_detail") or {},
                        })
                        print(f"         展开态：AFCR {em.get('afcr', 0):.2f} "
                              f"chrome {em.get('chrome_ratio', 0):.2f} "
                              f"条目 {em.get('items', 0):.1f} "
                              f"文档高 {edata.get('doc_h')}px")
                    except Exception as exc:  # noqa: BLE001
                        print(f"         展开态采集失败：{str(exc)[:120]}")
                m, f = rec["metrics"], rec["fonts"]
                flag = ("FAIL" if gate else "未达") if fails else "ok  "
                print(f"  [{flag}] {page['name']:8} {vp:10} AFCR {m.get('afcr', 0):.2f} "
                      f"带宽 {m.get('band_ratio', 0):.2f} "
                      f"条目 {m.get('items', 0):4.1f} chrome {m.get('chrome_ratio', 0):.2f} "
                      f"悬浮 {m.get('overlay_ratio', 0):.3f} "
                      f"正文 {f.get('body_min')}px 辅助 {f.get('aux_min')}px "
                      f"<14 {f.get('lt14_ratio', 0):.0%} 溢出 {'是' if m.get('overflow') else '否'}"
                      + (f"  ← {len(fails)} 项未达" if fails else ""))
                for item in fails:
                    print(f"         · {item['msg']}")
                if table_view_probe and page["name"] == "drug":
                    tv_page = dict(page, items=[DRUG_ROWS_SEL])
                    tv_url = url + ("&view=table" if "?" in url else "?view=table")
                    try:
                        tdata = scan(cdp, tv_url, width, height, tv_page, False)
                        tm = tdata.get("metrics") or {}
                        tv_items = tdata.get("items_detail") or {}
                        out["table_view"].append({
                            "page": page["name"], "viewport": vp, "url": rel + "?view=table",
                            "metrics": tm,
                            "items_detail": tv_items,
                            # True = 该页内嵌矩阵（multi_ratio ≥ 0.40 的 789 页）；
                            # False = 只有清单视图，?view=table 应回落到清单并给出说明
                            "has_matrix": bool(tv_items.get("available")),
                        })
                        print(f"         ?view=table：AFCR {tm.get('afcr', 0):.2f} "
                              f"条目 {tm.get('items', 0):.1f}（兼容视图，不参与判定）")
                    except Exception as exc:  # noqa: BLE001
                        print(f"         ?view=table 采集失败：{str(exc)[:120]}")
                if shots is not None:
                    png = shots / f"fs-{page['name']}-{width}x{height}.png"
                    try:
                        capture(cdp, url, width, height, page, png)
                        out["shots"].append(str(png.relative_to(ROOT)) if png.is_relative_to(ROOT)
                                            else str(png))
                    except Exception as exc:  # noqa: BLE001
                        print(f"         截图失败：{str(exc)[:120]}")
    finally:
        stop_chrome(proc)
        if srv is not None:
            srv.shutdown()
        shutil.rmtree(profile_root, ignore_errors=True)
    return out


def capture(cdp: CDP, url: str, width: int, height: int, page: dict, png: Path) -> None:
    """留证截图（干净状态，滚动回到顶部）。"""
    cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
             deviceScaleFactor=1, mobile=False)
    cdp.events.clear()
    cdp.call("Page.navigate", url=url)
    cdp.wait_event("Page.loadEventFired", 60)
    _wait_ready(cdp, page["name"])
    png.parent.mkdir(parents=True, exist_ok=True)
    data = cdp.call("Page.captureScreenshot", format="png")["data"]
    png.write_bytes(base64.b64decode(data))


def parse_viewports(spec: str | None) -> list[tuple[int, int, str]]:
    if not spec:
        return VIEWPORTS
    out: list[tuple[int, int, str]] = []
    for chunk in spec.split(","):
        chunk = chunk.strip().lower()
        if not chunk:
            continue
        w, _, h = chunk.partition("x")
        try:
            out.append((int(w), int(h), f"{int(w)}x{int(h)}"))
        except ValueError:
            raise SystemExit(f"--viewports 里 {chunk!r} 不是 WxH（如 390x844）")
    return out or VIEWPORTS


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(
        description="首屏守卫：AFCR / 主操作 / 条目数 / chrome / 悬浮 / 字号 / 横向溢出")
    ap.add_argument("--dist", default=str(DEFAULT_DIST), help="产物目录（默认 site/dist）")
    ap.add_argument("--base-url", default=None, help="改用已起的服务（给了就不起内置服务）")
    ap.add_argument("--viewports", default=None, help="逗号分隔的 WxH，默认 4 档全量")
    ap.add_argument("--json", default=None, help="结果 JSON 落盘路径（同时可当 --baseline）")
    ap.add_argument("--shots", default=None, help="截图目录")
    ap.add_argument("--baseline", default=None, help="上一轮 JSON：任一指标退化超过 5%% 也 FAIL")
    ap.add_argument("--scroll-probe", action="store_true",
                    help="额外量「滚到文档中部」的悬浮条（证据用，不参与判定）")
    ap.add_argument("--expand", action="store_true",
                    help="额外量「展开筛选/类别之后」的一屏（证据用，不参与判定）")
    ap.add_argument("--gate", action="store_true",
                    help="阻塞模式：未达标 → 退出码 1。默认是报告模式（只出数字，不阻塞发布）")
    ap.add_argument("--pages", default=None, help="只扫这些页型（逗号分隔，如 drug,atc）")
    ap.add_argument("--rows-selector", default=None,
                    help="成分页「首屏条目」选择器（默认 table.matrix tbody tr；换模板时覆盖）")
    ap.add_argument("--table-view-probe", action="store_true",
                    help="额外量一次 drug/...?view=table（矩阵降级视图），只作兼容证据")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    chrome = find_chrome()
    if chrome is None:
        print("[SKIP] 没找到本机 Chrome（试过注册表 / PATH / Program Files / LOCALAPPDATA）。")
        print("       装 Chrome 后重跑，或用 --base-url 配合已有的真浏览器环境。")
        return 0
    dist = None if args.base_url else Path(args.dist)
    if dist is not None and not dist.is_dir():
        print(f"[SKIP] 产物目录不存在：{dist}（先跑 site/build.py）")
        return 0
    viewports = parse_viewports(args.viewports)
    only = [s.strip() for s in args.pages.split(",") if s.strip()] if args.pages else None
    shots = Path(args.shots) if args.shots else None

    started = time.time()
    print(f"== 首屏守卫 == dist={dist or '(用 --base-url)'} 视口 {len(viewports)} 档 "
          f"页型 {len(only) if only else len(PAGES)} 种 chrome={chrome}")
    if args.rows_selector:
        print(f"   成分页行选择器：{args.rows_selector}（默认 {DRUG_ROWS_SEL}）")
    if args.table_view_probe:
        print(f"   兼容测量：?view=table 也会量一次（选择器 {DRUG_ROWS_SEL}）")
    out = run_checks(dist, args.base_url, chrome, viewports, args.scroll_probe, shots, only,
                     args.expand, args.gate, args.rows_selector, args.table_view_probe)
    out["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out["rows_selector"] = args.rows_selector or DRUG_ROWS_SEL
    out["elapsed_s"] = round(time.time() - started, 1)

    all_fails = [(rec["page"], rec["viewport"], item) for rec in out["pages"]
                 for item in rec["fails"]]
    all_warns = [(rec["page"], rec["viewport"], item) for rec in out["pages"]
                 for item in rec["warns"]]

    # ── 汇总表：一屏能看懂的「页面 × 视口」矩阵 ──────────────────────────────
    print("\n== 汇总（AFCR / 条目 / chrome / 悬浮 / 正文px / 辅助px / <14px / 溢出 / 判定）==")
    print(f"  {'页面':8} {'视口':10} {'AFCR':>6} {'带宽':>6} {'条目':>6} {'chrome':>7} {'悬浮':>6} "
          f"{'正文':>5} {'辅助':>5} {'<14px':>6} {'溢出':>4}  判定")
    for rec in out["pages"]:
        m, f = rec["metrics"], rec["fonts"]
        verdict = ("FAIL" if args.gate else "未达") if rec["fails"] else "ok"
        print(f"  {rec['page']:8} {rec['viewport']:10} {m.get('afcr', 0):6.2f} "
              f"{m.get('band_ratio', 0):6.2f} "
              f"{m.get('items', 0):6.1f} {m.get('chrome_ratio', 0):7.2f} "
              f"{m.get('overlay_ratio', 0):6.3f} {str(f.get('body_min')):>5} "
              f"{str(f.get('aux_min')):>5} {f.get('lt14_ratio', 0):6.0%} "
              f"{'是' if m.get('overflow') else '否':>4}  {verdict}")
    if not out["pages"]:
        for sk in out["skipped"]:
            print(f"  [SKIP] {sk['page']}: {sk['reason']}（试过 {', '.join(sk['tried'])}）")

    regressions: list[dict] = []
    if args.baseline:
        bpath = Path(args.baseline)
        if not bpath.is_file():
            print(f"\n[WARN] baseline 文件不存在：{bpath}（本轮不比对）")
        else:
            base = json.loads(bpath.read_text(encoding="utf-8"))
            regressions, notes = compare_baseline(out, base)
            for n in notes:
                print(f"  [注意] {n['msg']}")
            out["baseline"] = {"path": str(bpath), "regressions": regressions}
            print(f"\n== baseline 对比（{bpath}）==" +
                  (f" 退化 {len(regressions)} 项" if regressions else " 无退化"))
            for r in regressions:
                print(f"  [FAIL] {r['page']:8} {r['viewport']:10} {r['msg']}")

    by_metric: dict[str, int] = {}
    for _p, _v, item in all_fails:
        key = item["metric"].split(":")[0]
        by_metric[key] = by_metric.get(key, 0) + 1
    out["summary"] = {
        "scans": len(out["pages"]),
        "fail_scans": len({(r["page"], r["viewport"]) for r in out["pages"] if r["fails"]}),
        "fail_items": len(all_fails),
        "warn_items": len(all_warns),
        "fails_by_metric": by_metric,
        "regressions": len(regressions),
        "mode": "gate" if args.gate else "report",
        "ok": not all_fails and not regressions,
    }
    s = out["summary"]
    mode_note = ("阻塞模式：未达标 → 退出码 1" if args.gate
                 else "报告模式：只出数字，不影响发布（v0.10.3 起改为阻塞）")
    print(f"\n[{s['mode']}] {mode_note}")
    print(f"{s['scans']} 次扫描：{s['fail_scans']} 组不达标、共 {s['fail_items']} 项未达"
          f"（WARN {s['warn_items']}），baseline 退化 {s['regressions']} 项，{out['elapsed_s']}s")
    if by_metric:
        print("  按指标：" + "、".join(f"{k} {v}" for k, v in sorted(by_metric.items())))
    if out["shots"]:
        print(f"截图 {len(out['shots'])} 张：{out['shots'][0]} …")
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"JSON: {p}")
    if args.gate and not s["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
