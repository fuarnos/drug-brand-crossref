// v0.11.7 12 项测点 + 截图（口径同 reports/2026-11-14-before-baseline.measure.js）
// 用法：由 8010 端口静态服务 reports/ 后，用 browser_run_code_unsafe fetch 本文件并 new Function 执行。
// 差异：截图落到浏览器允许写入的 _tmp\browser-out\，再拷进 docs/img/v0117-after-*。
async (page) => {
  const BASE = 'http://127.0.0.1:8000/';
  const OUT = 'C:\\Users\\asus\\Documents\\deepseek-harness\\default-workspace\\_tmp\\browser-out\\';
  const SHOTS = [
    { id: 'home', url: 'index.html?lang=zh', ready: 'main h1', items: ['.catgrid a', '.updlist li'] },
    { id: 'results-tylenol', url: 'index.html?q=Tylenol&lang=zh', ready: '#reswrap tbody tr', items: ['#reswrap tbody tr.br', '#reswrap tbody tr.grp'] },
    { id: 'drug-acetaminophen', url: 'drug/acetaminophen.html?lang=zh', ready: '.mkrow', items: ['.mkrow'], itemsMode: 'first-match' },
    { id: 'name-tylenol-extra-strength', url: 'name/tylenol-extra-strength.html?lang=zh', ready: 'main h1', items: ['main .card', 'main ul.sub li', 'main table tbody tr'] },
    { id: 'coverage', url: 'coverage.html?lang=zh', ready: '#covtable tbody tr', items: ['#covtable tbody tr'] },
    { id: 'cat-analgesics', url: 'cat/analgesics.html?lang=zh', ready: 'ul.atcmembers li', items: ['ul.atcmembers li'] }
  ];
  const measure = (cfg) => {
    const STEP = 16;
    const vw = window.innerWidth, vh = window.innerHeight;
    const clip = (r) => { const x1 = Math.max(r.x, 0), y1 = Math.max(r.y, 0), x2 = Math.min(r.x + r.w, vw), y2 = Math.min(r.y + r.h, vh); if (x2 <= x1 || y2 <= y1) return null; return { x: x1, y: y1, w: x2 - x1, h: y2 - y1, area: (x2 - x1) * (y2 - y1) }; };
    const rect = (el) => { const b = el.getBoundingClientRect(); return { x: b.left, y: b.top, w: b.width, h: b.height }; };
    const qa = (s) => { try { return Array.prototype.slice.call(document.querySelectorAll(s)); } catch (e) { return []; } };
    const q1 = (s) => { try { return document.querySelector(s); } catch (e) { return null; } };
    const hidden = (el) => { const cs = getComputedStyle(el); if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse') return true; if (parseFloat(cs.opacity) <= 0.01) return true; if (el.tagName.toLowerCase() !== 'summary' && el.closest && el.closest('details:not([open])')) return true; return false; };
    const inside = (r, x, y) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;
    const mainEl = q1('main#main, main, #main') || document.body;
    const mainR = clip(rect(mainEl));
    const contentRects = [];
    qa('main h1, main h2, main h3, main p, main li, main td, main th, main tr, main .card, main .catchip, main .wrap, main table, main input').slice(0, 4000).forEach((el) => {
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
      if (isFinite(bx1) && bx2 > bx1) { const x1 = Math.max(bx1, mainR.x), x2 = Math.min(bx2, mainR.x + mainR.w); if (x2 - x1 > 0) band = { x: x1, y: mainR.y, w: x2 - x1, h: mainR.h, area: (x2 - x1) * mainR.h }; }
    }
    // 两套 chrome 口径：A = 官方列表；B = A + v0.11.7 新增的 .drug-sticky/.listfilters/.pickbar/.lf-panel
    const chromeA = ['header', 'footer', '.tabbar', '.matrix-filters', '.mf-slot', '.notice', '.restools', '.covtools', '.res-nobrand', '#ac', '.lang-menu', '.sn-panel'];
    const chromeB = chromeA.concat(['.drug-sticky', '.listfilters', '.pickbar', '.lf-panel', '.searchwrap']);
    const sample = (list) => {
      const rects = [];
      list.forEach((s) => qa(s).forEach((el) => { if (el.closest && el !== mainEl && el.contains(mainEl)) return; if (hidden(el)) return; const c = clip(rect(el)); if (c) rects.push(c); }));
      let cells = 0, effective = 0, chromeCells = 0;
      if (band) {
        for (let y = 0; y < vh; y += STEP) {
          for (let x = 0; x < vw; x += STEP) {
            const px = x + STEP / 2, py = y + STEP / 2; cells++;
            let ic = false;
            for (let k = 0; k < rects.length; k++) { if (inside(rects[k], px, py)) { ic = true; break; } }
            if (ic) chromeCells++;
            if (!ic && inside(band, px, py)) effective++;
          }
        }
      }
      const ca = STEP * STEP;
      return { chrome: cells ? Math.round((chromeCells * ca) / (vw * vh) * 1000) / 1000 : null, afcr: band ? Math.round((effective * ca) / Math.max(1, band.w * band.h) * 1000) / 1000 : null };
    };
    const sA = sample(chromeA), sB = sample(chromeB);
    let itemsCount = 0, selUsed = null;
    const seen = [];
    for (const s of cfg.items) {
      const list = qa(s);
      if (!list.length) continue;
      if (cfg.itemsMode === 'first-match' && selUsed !== null) break;
      let sub = 0;
      list.slice(0, 600).forEach((el) => {
        if (seen.indexOf(el) >= 0) return;
        seen.push(el);
        if (selUsed === null) selUsed = s;
        const b = el.getBoundingClientRect();
        if (b.width < 4 || b.height < 4) return;
        const c = clip({ x: b.left, y: b.top, w: b.width, h: b.height });
        if (!c) return;
        const frac = c.area / (b.width * b.height);
        if (frac >= 0.9) sub += 1; else if (frac >= 0.25) sub += 0.5;
      });
      itemsCount += sub;
    }
    const docW = document.documentElement.scrollWidth;
    let lt12 = 0, minFont = null;
    qa('main *').slice(0, 6000).forEach((el) => {
      const tag = el.tagName.toLowerCase();
      if (['script', 'style', 'noscript', 'template', 'svg', 'path', 'option'].indexOf(tag) >= 0) return;
      if (!(el.textContent || '').trim()) return;
      if (hidden(el)) return;
      const b = el.getBoundingClientRect();
      if (b.width < 2 || b.height < 2) return;
      if (b.bottom < 0 || b.top > vh || b.right < 0 || b.left > vw) return;
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (!fs || isNaN(fs)) return;
      if (fs < 12) lt12++;
      if (minFont === null || fs < minFont) minFont = fs;
    });
    return {
      vw, vh, docH: document.documentElement.scrollHeight, scrollW: docW, overflow: docW > vw + 1,
      items: itemsCount, itemsSel: selUsed,
      chrome: sA.chrome, chromeB: sB.chrome, afcr: sA.afcr,
      bandRatio: Math.round((band ? band.w / vw : 0) * 1000) / 1000,
      lt12, minFont
    };
  };
  const out = [];
  for (const vp of [[1440, 900, '1440'], [390, 844, '390']]) {
    await page.setViewportSize({ width: vp[0], height: vp[1] });
    for (const s of SHOTS) {
      const rec = { page: s.id, vp: vp[2] };
      try {
        await page.goto(BASE + s.url, { waitUntil: 'load', timeout: 40000 });
        try { await page.waitForSelector(s.ready, { timeout: 15000 }); } catch (e) { rec.readyTimeout = true; }
        await page.waitForTimeout(800);
        Object.assign(rec, await page.evaluate(measure, { items: s.items, itemsMode: s.itemsMode || null }));
        await page.screenshot({ path: OUT + 'v0117-after-' + s.id + '-' + vp[2] + '.png', fullPage: false });
        rec.shot = 'v0117-after-' + s.id + '-' + vp[2] + '.png';
      } catch (e) { rec.error = String(e && e.message ? e.message : e); }
      out.push(rec);
    }
  }
  return out;
}
