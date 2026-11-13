// 改前/改后同一口径取证脚本（MCP Playwright 替身方案）
// 用法：mcp__browser__browser_run_code_unsafe({ "filename": "reports/2026-11-14-before-baseline.measure.js" })
// 说明：本机沙箱里 deploy/first_screen_check.py（CDP）起不来，这里用 Playwright 复刻同一套口径的
//      子集：首屏可见条目数（半条=0.5）、横向溢出、chrome 占比、AFCR(v2)、字号硬线。
//      与官方守卫的差别写在报告「已知限制」里：网格步长、字体统计做了精简，不能与官方 JSON 直接比。
// 输出：逐页逐视口的 JSON；截图落到 docs/img/（绝对路径）。
async (page) => {
  const REPO = 'D:\\同种药物商品名剂量对应网站';
  const BASE = 'http://127.0.0.1:8000/';
  const SHOTS = [
    {
      id: 'home', url: 'index.html', ready: 'main h1',
      type: 'entry', items: ['.catgrid a', '.updlist li'], itemsMin: 0
    },
    {
      id: 'results-tylenol', url: 'index.html?q=Tylenol', ready: '#reswrap tbody tr',
      type: 'results', items: ['#reswrap tbody tr.br', '#reswrap tbody tr.grp'], itemsMin: 5
    },
    {
      id: 'drug-acetaminophen', url: 'drug/acetaminophen.html', ready: '.mkrow',
      type: 'content', items: ['.mkrow', 'table.matrix tbody tr'], itemsMin: 5, itemsMode: 'first-match'
    },
    {
      id: 'name-tylenol-extra-strength', url: 'name/tylenol-extra-strength.html', ready: 'main h1',
      type: 'content', items: ['main .card', 'main ul.sub li', 'main table tbody tr'], itemsMin: 1
    },
    {
      id: 'coverage', url: 'coverage.html', ready: '#covtable tbody tr',
      type: 'content', items: ['#covtable tbody tr'], itemsMin: 5
    },
    {
      id: 'cat-analgesics', url: 'cat/analgesics.html', ready: 'ul.atcmembers li',
      type: 'content', items: ['ul.atcmembers li'], itemsMin: 5
    }
  ];
  const VPS = [[1440, 900, '1440'], [390, 844, '390']];

  const measure = (cfg) => {
    const STEP = 16;
    const vw = window.innerWidth, vh = window.innerHeight;
    const clip = (r) => {
      const x1 = Math.max(r.x, 0), y1 = Math.max(r.y, 0);
      const x2 = Math.min(r.x + r.w, vw), y2 = Math.min(r.y + r.h, vh);
      if (x2 <= x1 || y2 <= y1) return null;
      return { x: x1, y: y1, w: x2 - x1, h: y2 - y1, area: (x2 - x1) * (y2 - y1) };
    };
    const rect = (el) => {
      const b = el.getBoundingClientRect();
      return { x: b.left, y: b.top, w: b.width, h: b.height };
    };
    const qa = (s) => { try { return Array.prototype.slice.call(document.querySelectorAll(s)); } catch (e) { return []; } };
    const q1 = (s) => { try { return document.querySelector(s); } catch (e) { return null; } };
    const hidden = (el) => {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse') return true;
      if (parseFloat(cs.opacity) <= 0.01) return true;
      if (el.tagName.toLowerCase() !== 'summary' && el.closest && el.closest('details:not([open])')) return true;
      return false;
    };
    const inside = (r, x, y) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;

    // ── 1. 内容带 / chrome / AFCR(v2) ─────────────────────────────────────
    const mainEl = q1('main#main, main, #main') || document.body;
    const mainR = clip(rect(mainEl));
    const CONTENT_SEL = 'main h1, main h2, main h3, main p, main li, main td, main th, main tr,'
      + ' main .card, main .catchip, main .wrap, main table, main input';
    const contentRects = [];
    qa(CONTENT_SEL).slice(0, 4000).forEach((el) => {
      if (el.closest && el.closest('details:not([open])')) return;
      const b = el.getBoundingClientRect();
      if (b.width < 4 || b.height < 4) return;
      if (hidden(el)) return;
      const c = clip({ x: b.left, y: b.top, w: b.width, h: b.height });
      if (c) contentRects.push(c);
    });
    let band = mainR;
    if (mainR && contentRects.length) {
      let bx1 = Infinity, bx2 = -Infinity;
      contentRects.forEach((r) => { bx1 = Math.min(bx1, r.x); bx2 = Math.max(bx2, r.x + r.w); });
      if (isFinite(bx1) && bx2 > bx1) {
        const x1 = Math.max(bx1, mainR.x), x2 = Math.min(bx2, mainR.x + mainR.w);
        if (x2 - x1 > 0) band = { x: x1, y: mainR.y, w: x2 - x1, h: mainR.h, area: (x2 - x1) * mainR.h };
      }
    }
    const CHROME_SEL = ['header', 'footer', '.tabbar', '.matrix-filters', '.mf-slot', '.notice',
      '.restools', '.covtools', '.res-nobrand', '#ac', '.lang-menu', '.sn-panel'];
    const chromeRects = [], chromeHits = [];
    CHROME_SEL.forEach((s) => {
      const list = qa(s);
      let hit = 0;
      list.forEach((el) => {
        if (el.closest && el !== mainEl && el.contains(mainEl)) return;
        if (hidden(el)) return;
        const c = clip(rect(el));
        if (!c) return;
        chromeRects.push(c); hit++;
      });
      if (hit) chromeHits.push(s + '×' + hit);
    });
    let cells = 0, effective = 0, chromeCells = 0;
    if (band) {
      for (let y = 0; y < vh; y += STEP) {
        for (let x = 0; x < vw; x += STEP) {
          const px = x + STEP / 2, py = y + STEP / 2;
          cells++;
          let inChrome = false;
          for (let k = 0; k < chromeRects.length; k++) { if (inside(chromeRects[k], px, py)) { inChrome = true; break; } }
          if (inChrome) chromeCells++;
          if (!inChrome && inside(band, px, py)) effective++;
        }
      }
    }
    const cellArea = STEP * STEP;
    const bandArea = band ? Math.max(1, band.w * band.h) : 1;
    const afcr = (effective * cellArea) / bandArea;
    const bandRatio = vw ? (band ? band.w / vw : 0) : 0;
    const chromeRatio = cells ? (chromeCells * cellArea) / (vw * vh) : 0;

    // ── 2. 首屏可见条目数（半条 = 0.5，口径同 first_screen_check）──────────
    // 与官方 PAGES 对齐：默认「多选择器求和」（home 的 .catgrid a + .updlist li、name 的三组都算），
    // 只有 cfg.itemsMode === 'first-match' 的页型（成分页矩阵→国家清单换过模板）才「首个有命中的选择器生效」。
    let itemsCount = 0, available = 0, selUsed = null;
    const seenSet = [];
    cfg.items.forEach((s) => {
      if (cfg.itemsMode === 'first-match' && selUsed !== null) return;
      const list = qa(s);
      let sub = 0;
      list.slice(0, 600).forEach((el) => {
        if (seenSet.indexOf(el) >= 0) return;
        seenSet.push(el);
        available++;
        if (selUsed === null) selUsed = s;
        const b = el.getBoundingClientRect();
        if (b.width < 4 || b.height < 4) return;
        const c = clip({ x: b.left, y: b.top, w: b.width, h: b.height });
        if (!c) return;
        const frac = c.area / (b.width * b.height);
        if (frac >= 0.90) sub += 1; else if (frac >= 0.25) sub += 0.5;
      });
      itemsCount += sub;
    });

    // ── 3. 横向溢出 ───────────────────────────────────────────────────────
    const docW = document.documentElement.scrollWidth;
    const overflow = docW > vw + 1;
    const offenders = [];
    if (overflow) {
      qa('body *').slice(0, 6000).forEach((el) => {
        if (offenders.length >= 6) return;
        const b = el.getBoundingClientRect();
        if (b.width < 8 || b.height < 8) return;
        if (b.right <= vw + 1 && b.left >= -1) return;
        if (hidden(el)) return;
        let anc = el.parentElement, scrolled = false;
        while (anc && anc !== document.body) {
          const acs = getComputedStyle(anc);
          if (acs.overflowX === 'auto' || acs.overflowX === 'scroll' || acs.overflowX === 'hidden') { scrolled = true; break; }
          anc = anc.parentElement;
        }
        if (scrolled) return;
        offenders.push((el.tagName.toLowerCase() + (el.className && typeof el.className === 'string'
          ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '')) + ' right=' + Math.round(b.right));
      });
    }

    // ── 4. 字号（首屏可见文字节点，主内容区）────────────────────────────────
    let nodes = 0, lt12 = 0, lt14 = 0, minFont = null, minFontWhere = '';
    Array.prototype.slice.call(mainEl.querySelectorAll('*')).slice(0, 6000).forEach((el) => {
      const tag = el.tagName.toLowerCase();
      if (['script', 'style', 'noscript', 'template', 'svg', 'path', 'option'].indexOf(tag) >= 0) return;
      if (!(el.textContent || '').trim()) return;
      if (hidden(el)) return;
      const b = el.getBoundingClientRect();
      if (b.width < 2 || b.height < 2) return;
      if (b.bottom < 0 || b.top > vh || b.right < 0 || b.left > vw) return;
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (!fs || isNaN(fs)) return;
      nodes++;
      if (fs < 12) lt12++;
      if (fs < 14) lt14++;
      if (minFont === null || fs < minFont) {
        minFont = fs;
        minFontWhere = tag + ' «' + (el.textContent || '').trim().slice(0, 28) + '»';
      }
    });

    const h1 = q1('main h1');
    return {
      vw, vh,
      title: document.title,
      h1: h1 ? h1.innerText.replace(/\s+/g, ' ').trim().slice(0, 80) : null,
      viewportH: vh,
      docH: document.documentElement.scrollHeight,
      scrollW: docW,
      overflow,
      overflowOffenders: offenders,
      items: itemsCount,
      itemsAvailable: available,
      itemsSel: selUsed,
      bandRatio: Math.round(bandRatio * 1000) / 1000,
      chromeRatio: Math.round(chromeRatio * 1000) / 1000,
      chromeHits,
      afcr: Math.round(afcr * 1000) / 1000,
      fonts: { nodes, lt12, lt14, lt14Ratio: nodes ? Math.round((lt14 / nodes) * 1000) / 1000 : 0, min: minFont, minWhere: minFontWhere }
    };
  };

  // 逐页文字证据（供 T10/T12 前后对照）
  const extract = (id) => {
    const txt = (s) => { const e = document.querySelector(s); return e ? e.innerText.replace(/\s+/g, ' ').trim() : null; };
    if (id === 'results-tylenol') {
      const thead = Array.prototype.map.call(document.querySelectorAll('#reswrap thead th'), (t) => t.innerText.trim());
      const rows = Array.prototype.slice.call(document.querySelectorAll('#reswrap tbody tr.br'));
      const tesRow = rows.find((r) => /Tylenol Extra Strength/.test(r.innerText));
      const doseCell = tesRow ? tesRow.querySelector('.c-dose') : null;
      return {
        tableClass: (document.querySelector('#reswrap table') || {}).className || null,
        thead, rowCount: rows.length,
        grpRows: document.querySelectorAll('#reswrap tbody tr.grp').length,
        tylenolExtraStrengthRow: tesRow ? tesRow.innerText.replace(/\s+/g, ' ').trim() : null,
        doseCellText: doseCell ? doseCell.innerText.replace(/\s+/g, ' ').trim() : null,
        doseCellHtml: doseCell ? doseCell.innerHTML.slice(0, 400) : null,
        firstFourRows: rows.slice(0, 4).map((r) => r.innerText.replace(/\s+/g, ' ').trim())
      };
    }
    if (id === 'name-tylenol-extra-strength') {
      const nb = document.querySelector('.nolang-badge');
      return {
        h1: txt('main h1'),
        lead: txt('main p.sub'),
        h2: Array.prototype.map.call(document.querySelectorAll('main h2'), (h) => h.innerText.replace(/\s+/g, ' ').trim()),
        cards: Array.prototype.map.call(document.querySelectorAll('main .card'), (c) => c.innerText.replace(/\s+/g, ' ').trim().slice(0, 240)),
        notices: Array.prototype.map.call(document.querySelectorAll('main .notice'), (n) => n.innerText.replace(/\s+/g, ' ').trim()),
        nolangBadge: nb ? { text: nb.innerText.trim(), parent: nb.parentElement ? nb.parentElement.outerHTML.slice(0, 240) : null } : null,
        nameList: Array.prototype.map.call(document.querySelectorAll('main ul li'), (li) => li.outerHTML.slice(0, 200)),
        mainLen: (document.querySelector('main') || {}).innerText ? document.querySelector('main').innerText.trim().length : null
      };
    }
    if (id === 'drug-acetaminophen') {
      const heads = Array.prototype.map.call(document.querySelectorAll('.mkblock h2, .mkblock h3'), (h) => h.innerText.replace(/\s+/g, ' ').trim());
      const rows = Array.prototype.slice.call(document.querySelectorAll('.mkrow'));
      const t325 = rows.filter((r) => /325 mg\s*片剂/.test(r.innerText.replace(/\s+/g, ' ')));
      return {
        blocks: document.querySelectorAll('.mkblock').length,
        rows: rows.length,
        heads,
        formChips: txt('.formchips'),
        count325Tablet: t325.length,
        rows325: t325.slice(0, 6).map((r) => ({
          mk: r.getAttribute('data-mk'),
          spec: r.getAttribute('data-spec'),
          form: r.getAttribute('data-form'),
          txt: r.innerText.replace(/\s+/g, ' ').trim().slice(0, 150)
        })),
        notice: txt('main .notice')
      };
    }
    if (id === 'coverage') {
      return {
        h1: txt('main h1'),
        tableHead: Array.prototype.map.call(document.querySelectorAll('#covtable thead th'), (t) => t.innerText.trim()),
        firstRows: Array.prototype.slice.call(document.querySelectorAll('#covtable tbody tr')).slice(0, 3)
          .map((r) => r.innerText.replace(/\s+/g, ' ').trim()),
        totalRows: document.querySelectorAll('#covtable tbody tr').length
      };
    }
    if (id === 'cat-analgesics') {
      return {
        h1: txt('main h1'),
        h2: Array.prototype.map.call(document.querySelectorAll('main h2'), (h) => h.innerText.replace(/\s+/g, ' ').trim()),
        lists: Array.prototype.map.call(document.querySelectorAll('ul.atcmembers'), (u) => u.querySelectorAll('li').length),
        firstIngredient: txt('ul.atcmembers li'),
        notice: txt('main .notice')
      };
    }
    if (id === 'home') {
      return {
        h1: txt('main h1'),
        catLinks: document.querySelectorAll('.catgrid a').length,
        updItems: document.querySelectorAll('.updlist li').length,
        mainLen: (document.querySelector('main') || {}).innerText ? document.querySelector('main').innerText.trim().length : null
      };
    }
    return null;
  };

  const out = [];
  for (const vp of VPS) {
    await page.setViewportSize({ width: vp[0], height: vp[1] });
    for (const s of SHOTS) {
      const rec = { page: s.id, vp: vp[2] };
      try {
        await page.goto(BASE + s.url, { waitUntil: 'load', timeout: 30000 });
        try { await page.waitForSelector(s.ready, { timeout: 15000 }); } catch (e) { rec.readyTimeout = true; }
        await page.waitForTimeout(500);
        const m = await page.evaluate(measure, { items: s.items });
        Object.assign(rec, m);
        if (vp[2] === '1440') rec.evidence = extract(s.id);
        const file = REPO + '\\docs\\img\\v0115-before-' + s.id + '-' + vp[2] + '.png';
        await page.screenshot({ path: file, fullPage: false });
        rec.shot = 'docs/img/v0115-before-' + s.id + '-' + vp[2] + '.png';
      } catch (e) {
        rec.error = String(e && e.message ? e.message : e);
      }
      out.push(rec);
    }
  }
  return out;
}
