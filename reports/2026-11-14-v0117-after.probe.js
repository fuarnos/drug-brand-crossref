// v0.11.7 改后对照断言（T13 + T11）— 可执行版
// 配套：reports/2026-11-14-v0117-before-baseline.md（改前基线 + 断言定义）
//
// 用法：把本文件从 `async (page) => {` 起全文粘进 mcp__browser__browser_run_code_unsafe 的 code 参数
//      （浏览器工具只允许读写 …\default-workspace\_tmp\browser-out\ 与 …\.dsh\profiles\desktop\，
//       不能直接加载仓库文件 → 只能内联）。
// 前置：site/dist 已换成 v0.11.7 产物；& $py serve.py 8000 在跑。
// 输出：[{id, status:'pass'|'fail'|'na', expect, got}]；na 一律人工复核，不许判绿。
//
// 改前（v0.11.6 / D609F363…）预期：25 红 / 1 绿（D7 是守卫项）/ T5 na。
async (page) => {
  const BASE = 'http://127.0.0.1:8000/';
  const out = [];
  const rec = (id, expect, got, ok) => out.push({ id, status: ok === null ? 'na' : (ok ? 'pass' : 'fail'), expect, got });
  const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
  // 锁定 1440 桌面档：T11/T13 的断言按桌面的 DOM 顺序与首屏可见性判（390 档表格行数/RES_LIMIT 不同，
  // 分页文案会从「显示 20 / 86」变「显示 10 / 86」）。注意 `#country` / `#src` 是**服务端渲染**的，
  // 两种档位都在 DOM 里；选它是 `select#country`（没有 name 属性），别用 `[name="country"]`。
  await page.setViewportSize({ width: 1440, height: 900 });

  // ══ T13-A 成分页 ═══════════════════════════════════════════════════════
  await page.goto(BASE + 'drug/acetaminophen.html?lang=zh', { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForSelector('.mkrow', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(900);
  const D = await page.evaluate(() => {
    const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const main = document.querySelector('main');
    const mainText = flat(main ? main.innerText : '');
    const q = (s) => { try { return Array.prototype.slice.call(document.querySelectorAll(s)); } catch (e) { return []; } };
    // 市场控件
    const mkSel = q('main select[name*="mk"], main [data-mf-country]');
    const mkOpts = mkSel.length && mkSel[0].tagName === 'SELECT' ? mkSel[0].options.length : 0;
    // 市场覆盖 +N：叶子节点里「纯 +数字」且不是品牌折叠 .m-more
    const marketPlus = [];
    main.querySelectorAll('*').forEach((el) => {
      if (el.children.length) return;
      if (!/^\+\d+$/.test(flat(el.innerText))) return;
      if (el.classList && el.classList.contains('m-more')) return;
      marketPlus.push({ text: flat(el.innerText), tag: el.tagName.toLowerCase(), cls: el.className || '', clickable: !!el.closest('a, button, label, summary') });
    });
    return {
      filters: q('.listfilters, details#listfilters, .lf-panel').length,
      mkSel: q('main .lf-chip[data-mk-filter]').length,
      mkOpts: q('main .lf-chip[data-mk-filter]').length,
      combo: q('main .lf-chip[data-seg-filter]').length,
      comboKinds: q('main .lf-chip[data-seg-filter="mono"], main .lf-chip[data-seg-filter="combo"]').length,
      spec: q('main #lf-spec, main input.lf-input[type="search"], main input[type="search"]').length,
      countCopy: /展示\s*\d+\s*个[，,]\s*共\s*[\d,]+\s*个/.test(mainText),
      countText: (mainText.match(/[\d,]+\s*条记录\s*·\s*\d+\s*个规格/) || [null])[0],
      marketPlusN: marketPlus.length,
      otherEnSample: (mainText.match(/Other \d+ markets?/g) || []).slice(0, 3),
      leiCount: (mainText.match(/另\s*\d+\s*个市场/g) || []).length,
      marketPlusClickable: marketPlus.filter((x) => x.clickable).length,
      marketPlusSample: marketPlus.slice(0, 2),
      comboSeg: document.querySelectorAll('[data-combo="1"]').length,
      monoSeg: document.querySelectorAll('[data-combo="0"]').length,
      totalRows: document.querySelectorAll('.mkrow').length,
      chipTexts: Array.prototype.map.call(document.querySelectorAll('.formchips *'), (c) => flat(c.innerText)).filter(Boolean).slice(0, 12),
      noInterchange: /不代表可以互换|不可互换/.test(mainText)
    };
  });
  rec('D1 成分页筛选面板存在', '>=1', { filters: D.filters }, D.filters >= 1);
  rec('D2 市场筛选控件（≥11 个市场 chip，含「全部」）', '>=11', { chips: D.mkSel }, D.mkSel >= 11);
  rec('D3 单方/复方切换控件（mono+combo 两个 chip）', '>=2 且含 mono+combo', { chips: D.combo, kinds: D.comboKinds, comboSeg: D.comboSeg, monoSeg: D.monoSeg }, D.combo >= 2 && D.comboKinds >= 2);
  rec('D4 规格筛选/搜索', '>=1', { controls: D.spec }, D.spec >= 1);
  rec('D5 计数文案「展示 N 个，共 X 个」', '命中', { hit: D.countCopy, still: D.countText }, D.countCopy);
  rec('D6 市场覆盖 +N 可点', '存在且全部可点', { n: D.marketPlusN, clickable: D.marketPlusClickable, sample: D.marketPlusSample },
    D.marketPlusN === 0 ? false : D.marketPlusClickable === D.marketPlusN);
  rec('D6b 市场覆盖文案本地化（zh 页不得出现 "Other N markets"）', '0 命中',
    { otherEn: D.otherEnSample, leiCount: D.leiCount },
    D.otherEnSample.length === 0 && D.leiCount >= 1);
  // D7 守卫项：+218 折叠必须仍可展开
  const D7 = await page.evaluate(() => {
    const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const row = document.querySelector('.mkrow');
    const more = row ? row.querySelector('.m-more') : null;
    const cb = more ? document.getElementById(more.getAttribute('for') || '') : null;
    const rest = row ? row.querySelector('.m-rest') : null;
    if (!more || !cb || !rest) return { ok: false, why: 'no .m-more/.m-rest' };
    const h0 = Math.round(rest.getBoundingClientRect().height);
    cb.checked = true;
    const h1 = Math.round(rest.getBoundingClientRect().height);
    cb.checked = false;
    return { ok: h1 > h0, before: h0, after: h1, label: flat(more.innerText) };
  });
  rec('D7 守卫：+218 仍可展开', '展开后高度>前', D7, D7.ok === true);
  // D8 筛选生效（行为）：点「片剂」chip 后行数下降
  let D8 = null;
  try {
    const chip = await page.evaluate(() => {
      const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
      const el = Array.prototype.find.call(document.querySelectorAll('.formchips button, .formchips a, .formchips label, .formchips span'), (c) => /^片剂/.test(flat(c.innerText)));
      if (!el) return null;
      el.click();
      return flat(el.innerText);
    });
    if (chip) {
      await page.waitForTimeout(600);
      const afterCount = await page.evaluate(() => document.querySelectorAll('.mkrow').length);
      D8 = { chip, rowsAfter: afterCount, rowsBefore: D.totalRows };
    }
  } catch (e) { D8 = { error: String(e && e.message ? e.message : e) }; }
  // D8 只取证据、不自动判定：2026-11-14 自检发现 v0.11.6 的 `.formchips` 元素 click() 不改变行数，
  // 无法区分「筛选没做」与「脚本没驱动对」，故记 na，留人工确认（改动后的 DOM 形态未知，先不写死）。
  rec('D8 剂型筛选生效且计数同步（人工确认）', '0 < rowsAfter < rowsBefore', D8, null);
  rec('D9 筛选后仍保留不可互换提示', '命中', D.noInterchange, D.noInterchange);

  // ══ T13-B 分类页 ═══════════════════════════════════════════════════════
  await page.goto(BASE + 'cat/analgesics.html?lang=zh', { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForSelector('ul.atcmembers li', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(2600);   // 分类页渐进渲染：1s 时只出 5 条，会把 CAT1 测成假红（2026-11-14 实测）
  const C = await page.evaluate(() => {
    const main = document.querySelector('main');
    return {
      search: main.querySelectorAll('input[type="search"], [data-cat-search]').length,
      sub: main.querySelectorAll('.lf-chip, [data-subclass], .cat-sub select').length,
      noticeInMain: main.querySelectorAll('.notice').length,
      helpLinks: document.querySelectorAll('a[href*="help"], a[href*="guide"]').length,
      members: main.querySelectorAll('ul.atcmembers li').length,
      helpFold: Array.prototype.some.call(main.querySelectorAll('details'), (d) => /怎么看这份清单|how to read/i.test((d.querySelector('summary') || {}).innerText || '')),
      redline: /不可互换|不代表.{0,6}互换|不声称.{0,6}互换/.test(main.innerText)
    };
  });
  rec('C1 分类页页内搜索控件', '>=1', C.search, C.search >= 1);
  rec('C2 子类筛选控件', '>=1', C.sub, C.sub >= 1);
  // Lead 2026-11-14 澄清：4 个 .notice 是 v0.10.0 的 _atc_notes_html（许可/状态/译名/署名），
  // 现在应装进「怎么看这份清单」折叠；红线句仍常显 → 判定改为 notice=0 && 折叠在，红线句另判
  rec('C3 说明移出正文、装进「怎么看这份清单」折叠', 'notice=0 且 折叠存在',
    { notice: C.noticeInMain, helpFold: C.helpFold, helpLinks: C.helpLinks },
    C.noticeInMain === 0 && C.helpFold);
  rec('C3b 分类页红线句仍常显', '命中', { redline: C.redline }, C.redline);
  // C4 搜索可用（行为）：有搜索框才判
  let C4 = null;
  if (C.search >= 1) {
    try {
      await page.evaluate(() => {
        const el = document.querySelector('input[type="search"], [data-cat-search]');
        if (!el) return;
        el.focus();
        el.value = '布洛芬';
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      });
      await page.waitForTimeout(700);
      const r = await page.evaluate(() => {
        const lis = Array.prototype.slice.call(document.querySelectorAll('ul.atcmembers li'));
        const vis = lis.filter((li) => li.getBoundingClientRect().height > 0 && getComputedStyle(li).display !== 'none').length;
        return { vis, total: lis.length };
      });
      C4 = r;
    } catch (e) { C4 = { error: String(e && e.message ? e.message : e) }; }
  }
  rec('C4 搜「布洛芬」后成员列表缩小且非空', '0 < vis < 187', C4, C4 && C4.vis > 0 && C4.vis < C4.total);
  rec('C5 守卫：分类页成员总数不变', '187', C.members, C.members === 187);
  // CAT1：分类页 1440 首屏条目必须回到 ≥10.5（Lead 2026-11-14 定：首屏条目自 v0.10.3 起阻塞）
  // ⚠ 必须在「干净页面」上量：C4 刚在页内搜索框里输入过「布洛芬」，筛选状态会留在 DOM 里，
  //   直接量会把 10.5 测成 5（2026-11-14 实测踩过）。所以先重新加载一次。
  await page.goto(BASE + 'cat/analgesics.html?lang=zh', { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForSelector('ul.atcmembers li', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(2600);
  const CAT1 = await page.evaluate(() => {
    const vh = window.innerHeight;
    let items = 0;
    document.querySelectorAll('ul.atcmembers li').forEach((li) => {
      const b = li.getBoundingClientRect();
      if (b.width < 4 || b.height < 4) return;
      const y1 = Math.max(b.top, 0), y2 = Math.min(b.bottom, vh);
      if (y2 <= y1) return;
      const frac = (y2 - y1) / b.height;
      if (frac >= 0.9) items += 1; else if (frac >= 0.25) items += 0.5;
    });
    return { items, vh };
  });
  rec('CAT1 分类页 1440 首屏条目 ≥10.5（阻塞项）', '>=10.5', CAT1, CAT1.items >= 10.5);

  // ══ T13-C 覆盖页 ═══════════════════════════════════════════════════════
  await page.goto(BASE + 'coverage.html?lang=zh', { waitUntil: 'load', timeout: 30000 });
  await page.waitForTimeout(700);
  const V = await page.evaluate(() => Array.prototype.map.call(document.querySelectorAll('#covtable thead th'), (t) => t.innerText.replace(/\s+/g, ' ').trim()));
  rec('V1 覆盖页第 2 列 = 记录数', '记录数', V, V[1] === '记录数');
  const tail = (V.slice(2) || []).join('|');
  rec('V2 其余表头不变（第 1 列 + 第 3–7 列）', '市场 / 成分已映射 / 规格覆盖 / 最后同步 / 数据截止 / 已知缺口',
    { first: V[0], tail }, V[0] === '市场' && tail === '成分已映射|规格覆盖|最后同步|数据截止|已知缺口');

  // ══ T13-D 结果页行内 + T11 流程 ════════════════════════════════════════
  await page.goto(BASE + 'index.html?q=Tylenol&lang=zh', { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForSelector('#reswrap tbody tr', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(900);
  const R = await page.evaluate(() => {
    const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const main = document.querySelector('main');
    const mainText = flat(main ? main.innerText : '');
    const rows = Array.prototype.slice.call(document.querySelectorAll('#reswrap tbody tr.br'));
    const selCountry = document.querySelector('select#country, #country');
    const selSrc = document.querySelector('select#src, #src');
    const wrap = document.querySelector('#reswrap');
    // T1 DOM 顺序：选择器容器 vs 结果表
    const selBox = selCountry ? selCountry.closest('.ctry-panel, .restools, .resfilter, form, div') : null;
    let precedes = null, selTop = null;
    if (selBox && wrap) {
      const pos = selBox.compareDocumentPosition(wrap);
      precedes = !!(pos & Node.DOCUMENT_POSITION_FOLLOWING);
      selTop = Math.round(selBox.getBoundingClientRect().top);
    }
    // T3 「来源市场」标签里是否混入「登记库」
    const srcLabelEl = selSrc ? selSrc.closest('label, .ctry-item, div') : null;
    const srcLabel = srcLabelEl ? flat(srcLabelEl.innerText).slice(0, 60) : null;
    // 红线
    const compliant = mainText
      .replace(/本站只做标识对应，不构成用药建议，不能替代医师或药师。/g, '')
      .replace(/不建议替换药品/g, '').replace(/不做剂量换算/g, '').replace(/不给用药建议/g, '');
    return {
      rowDate: rows.filter((r) => /\d{4}-\d{2}-\d{2}/.test(flat(r.innerText))).length,
      detHasDate: false,
      rowMissing: rows.filter((r) => /缺失|未收录|待补/.test(flat(r.innerText))).length,
      countCopy: /展示\s*\d+\s*个[，,]\s*共/.test(mainText),
      countNow: (mainText.match(/显示\s*\d+\s*\/\s*\d+/) || [null])[0],
      confirmAction: /确认这条|就是这条|确认此候选/.test(mainText),
      idCard: flat((document.querySelector('.idcard') || {}).innerText || '').slice(0, 120),
      hasPrevNext: /上一条|下一条/.test(mainText),
      precedes, selTop, vh: window.innerHeight,
      srcLabel,
      nCountryOpts: selCountry ? selCountry.options.length : 0,
      nSrcOpts: selSrc ? selSrc.options.length : 0,
      advice: (compliant.match(/(可以|可)替代|换药|应服用|recommended dose|equivalent dose|剂量换算/gi) || []).length
    };
  });
  // R1/R2：v0.11.7 把来源日期放进了「详情」展开面板，所以先展开再判
  await page.evaluate(() => { document.querySelectorAll('#reswrap .detbtn').forEach((b) => b.click()); });
  await page.waitForTimeout(1300);
  const RD = await page.evaluate(() => {
    const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const t = flat((document.querySelector('main') || document.body).innerText);
    return {
      hasDate: /\d{4}-\d{2}-\d{2}/.test(t),
      dates: (t.match(/\d{4}-\d{2}-\d{2}/g) || []).slice(0, 3),
      hasMissing: /缺失|未收录|待补/.test(t),
      sample: (t.match(/.{0,14}(缺失|未收录|待补).{0,18}/) || [null])[0]
    };
  });
  rec('R1 结果行（展开详情后）带来源日期', '>=1 个日期', RD, RD.hasDate);
  rec('R2 结果行（展开详情后）标缺失字段', '命中即绿；无缺失样本记 na', RD, RD.hasMissing ? true : null);
  // Lead 2026-11-14：该条不在 v0.11.7 范围（D3 指「12 个规格」口径）→ 下一版，不判定
  rec('R3 结果页计数文案', '下一版（不计入本版）', { still: R.countNow }, null);
  // T1 已并入 B2a（常驻入口 = #mkchips，Lead 2026-11-14 定）；此处只留旧口径记录，不判定
  rec('T1 旧口径（select#country 在结果前）——已被 B2a/T16 取代', '不判定', { precedes: R.precedes, selTop: R.selTop }, null);
  // Lead 2026-11-14：实际实现是 button.pickbtn「我用的是这条」+ ◎ 单选钮，措辞不同不算问题 → 不判定
  rec('T2 「确认这条候选」动作（实际措辞：我用的是这条 / ◎）', '不判定（措辞差异）', { hit: R.confirmAction }, null);
  rec('T3 「来源市场」标签不再混「登记库」', '标签不含登记库', R.srcLabel, R.srcLabel === null ? null : !/登记库/.test(R.srcLabel));
  // Lead 2026-11-14：不要求「上一条/下一条」，有「重选 / 看全部候选 ↓」即满足三步流程 → 不判定
  rec('T4 身份卡可推进（上一条/下一条）', '不要求', { hasPrevNext: R.hasPrevNext }, null);
  rec('T5 选定目标市场后出现对照块', '行为断言（方案未定稿）', '需人工看 dsh 方案落地形态', null);
  rec('T6 红线：无推荐/替代/换算话术', '0', R.advice, R.advice === 0);
  rec('T7 守卫：country/src 两个 select 与选项保留', '各 ≥12 个真实选项（含「全部」共 13）',
    { country: R.nCountryOpts, src: R.nSrcOpts }, R.nCountryOpts >= 13 && R.nSrcOpts >= 13);

  // ══ T13–T15 候选集红线 + 逐项对照（2026-11-14 复测口径：#pickbar / #cmp 是条件渲染，
  //   只在带 pick 的深链出现；不带 pick 时静态 HTML 里就是 hidden 空壳）══════════════
  await page.goto(BASE + 'index.html?q=Tylenol&pick=tylenol+extra+strength&pmk=US&country=CN&lang=zh', { waitUntil: 'load', timeout: 45000 });
  await page.waitForTimeout(2200);
  const PB = await page.evaluate(() => {
    const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const main = document.querySelector('main');
    const t = flat(main ? main.innerText : '');
    const pick = document.querySelector('#pickbar, .pickbar, [class*="pickbar"]');
    const pickText = pick ? flat(pick.innerText) : null;
    const pickVisible = !!(pick && pick.getBoundingClientRect().height > 0);
    const head4000 = t.slice(0, 4000);
    const cmp = document.querySelector('#cmp');
    const cmpRows = cmp ? cmp.querySelectorAll('tbody tr').length : 0;
    const cmpHeads = cmp ? Array.prototype.map.call(cmp.querySelectorAll('tbody th'), (x) => flat(x.innerText)) : [];
    // 对照块：优先 pickbar 之后的容器，退到全文
    const vocab = { same: /相同/.test(t), diff: /不同/.test(t), none: /未收录/.test(t) };
    const noInterchange = /不代表这些产品可以互换|不可互换/.test(t);
    const clean = t.replace(/不代表这些产品可以互换/g, '').replace(/不可互换/g, '');
    const forbidden = (clean.match(/等价|可替代|推荐使用|建议服用|等剂量|可以互换/g) || []).length;
    return {
      pickbar: { exists: !!pick, visible: pickVisible, text: pickText ? pickText.slice(0, 160) : null },
      headHasCandidateSet: /结果永远是候选集/.test(head4000),
      vocab, noInterchange, forbidden, cmpRows, cmpHeads,
      tailSample: t.slice(Math.max(0, t.length - 400))
    };
  });
  rec('T13 #pickbar 存在可见且带「候选集 N 条」', '存在 且 含候选+N条',
    PB.pickbar, PB.pickbar.exists && PB.pickbar.visible && /候选/.test(PB.pickbar.text || '') && /\d/.test(PB.pickbar.text || ''));
  rec('T14 「结果永远是候选集」在首 4000 字符内', 'true', PB.headHasCandidateSet, PB.headHasCandidateSet);
  rec('T15 对照块只用 相同/不同/未收录 + 不代表可以互换，且无推荐话术', 'vocab 命中 且 noInterchange 且 forbidden=0',
    { vocab: PB.vocab, noInterchange: PB.noInterchange, forbidden: PB.forbidden },
    (PB.vocab.same || PB.vocab.diff || PB.vocab.none) && PB.noInterchange && PB.forbidden === 0);
  rec('T15b #cmp 三行（注册名/规格/释放）+ 末句不代表可以互换', 'rows=3 且 表头含三字段',
    { rows: PB.cmpRows, heads: PB.cmpHeads }, PB.cmpRows === 3 && PB.cmpHeads.length === 3);

  // ══ T11-B 老深链守卫（?country= / ?src= / ?legacy=1 整表替换）═══════════
  // 改前实测（v0.11.6）：默认路径（不拉完整索引）下 ?country= 只把值灌进 select#country，
  // 结果表与基线一致；带 ?legacy=1（加载完整索引）时 ?country= 才会「整表替换」——
  // US 命中上限 200 条、CN 183 条。T11 用 if(!pick) 保留老行为，所以两层都要守。
  const readList = () => {
    const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();   // 必须在页面上下文里自带，不能闭包外层
    const main = document.querySelector('main');
    const t = flat(main ? main.innerText : '');
    const rows = Array.prototype.slice.call(document.querySelectorAll('#reswrap tbody tr.br'));
    return {
      rows: rows.length,
      hit: (t.match(/共\s*[\d,]+\s*条/) || [null])[0],
      hitNum: (function () { const m = t.match(/共\s*([\d,]+)\s*条/); return m ? parseInt(m[1].replace(/,/g, ''), 10) : null; })(),
      firstRow: rows.length ? flat(rows[0].innerText).slice(0, 80) : null,
      countryVal: (document.querySelector('#country') || {}).value || null,
      srcVal: (document.querySelector('#src') || {}).value || null,
      coreRequested: performance.getEntriesByType('resource').some((e) => /core\.json/.test(e.name))
    };
  };

  await page.goto(BASE + 'index.html?q=Tylenol&legacy=1&lang=zh', { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(5000);
  const L0 = await page.evaluate(readList);

  await page.goto(BASE + 'index.html?q=Tylenol&country=US&legacy=1&lang=zh', { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(5000);
  const LUS = await page.evaluate(readList);

  await page.goto(BASE + 'index.html?q=Tylenol&country=CN&legacy=1&lang=zh', { waitUntil: 'load', timeout: 60000 });
  await page.waitForTimeout(5000);
  const LCN = await page.evaluate(readList);

  rec('T8 legacy 基线（?legacy=1，拉完整索引）', 'rows>0 且 core.json 被请求',
    { rows: L0.rows, hit: L0.hit, core: L0.coreRequested }, L0.rows > 0 && L0.coreRequested);
  rec('T9 老深链 ?country=US 仍整表替换（≤200 条）', '非空 且 命中≤200 且 首行≠基线',
    { hit: LUS.hit, hitNum: LUS.hitNum, firstRow: LUS.firstRow, base: L0.firstRow },
    LUS.rows > 0 && LUS.hitNum !== null && LUS.hitNum <= 200 && LUS.firstRow !== L0.firstRow);
  rec('T10 老深链 ?country=CN 仍整表替换且与 US 不同', '非空 且 命中≤200 且 首行≠US',
    { hit: LCN.hit, hitNum: LCN.hitNum, firstRow: LCN.firstRow, us: LUS.firstRow },
    LCN.rows > 0 && LCN.hitNum !== null && LCN.hitNum <= 200 && LCN.firstRow !== LUS.firstRow);

  // 默认路径（不拉完整索引）：?country= 只灌选择器，不动结果表
  await page.goto(BASE + 'index.html?q=Tylenol&country=US&lang=zh', { waitUntil: 'load', timeout: 40000 });
  try { await page.waitForSelector('#reswrap tbody tr', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(1200);
  const LDef = await page.evaluate(readList);
  await page.goto(BASE + 'index.html?q=Tylenol&lang=zh', { waitUntil: 'load', timeout: 40000 });
  try { await page.waitForSelector('#reswrap tbody tr', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(1200);
  const LBase = await page.evaluate(readList);
  rec('T11 默认路径 ?country= 只灌选择器、不改结果表', 'countryVal=US 且 首行与基线一致',
    { countryVal: LDef.countryVal, firstRow: LDef.firstRow, base: LBase.firstRow },
    LDef.countryVal === 'US' && LDef.firstRow === LBase.firstRow);
  await page.goto(BASE + 'index.html?q=Tylenol&src=CN&lang=zh', { waitUntil: 'load', timeout: 40000 });
  try { await page.waitForSelector('#reswrap tbody tr', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(1200);
  const LSrc = await page.evaluate(readList);
  rec('T12 守卫：?src= 深链仍灌入 select#src', 'srcVal=CN 且 rows>0',
    { srcVal: LSrc.srcVal, rows: LSrc.rows }, LSrc.srcVal === 'CN' && LSrc.rows > 0);

  // ══ B2 判据（Lead 2026-11-14）：选择器搬进 sticky 搜索条 / 净增 0px / 首屏条目不降 ══
  await page.goto(BASE + 'index.html?q=Tylenol&lang=zh', { waitUntil: 'load', timeout: 40000 });
  try { await page.waitForSelector('#reswrap tbody tr', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(1200);
  const B2 = await page.evaluate(() => {
    const sel = document.querySelector('select#country, #country');
    const wrap = document.querySelector('#reswrap');
    const mkchips = document.querySelector('#mkchips, .mkchips');
    const inBar = mkchips ? true : (sel ? !!sel.closest('.searchbar, .searchwrap, .sticky-bar, .resfilter') : false);
    // 目标市场常驻入口改判 #mkchips：只要它在结果表之前、且在首屏内即视为常驻
    const mkTop = mkchips ? Math.round(mkchips.getBoundingClientRect().top) : null;
    const mkChips = mkchips ? mkchips.querySelectorAll('button, a').length : 0;
    const mkPrecedes = mkchips && wrap ? !!(mkchips.compareDocumentPosition(wrap) & Node.DOCUMENT_POSITION_FOLLOWING) : null;
    let stickyAnc = false;
    let n = sel;
    while (n && n !== document.body) {
      const cs = getComputedStyle(n);
      if (cs.position === 'sticky' || cs.position === 'fixed') { stickyAnc = true; break; }
      n = n.parentElement;
    }
    // 首屏条目（半条=0.5，口径同 measure.js）
    const vh = window.innerHeight;
    let items = 0;
    document.querySelectorAll('#reswrap tbody tr.br').forEach((r) => {
      const b = r.getBoundingClientRect();
      if (b.width < 4 || b.height < 4) return;
      const y1 = Math.max(b.top, 0), y2 = Math.min(b.bottom, vh);
      if (y2 <= y1) return;
      const frac = (y2 - y1) / b.height;
      if (frac >= 0.9) items += 1; else if (frac >= 0.25) items += 0.5;
    });
    return {
      inSearchBar: inBar, stickyAncestor: stickyAnc,
      wrapTop: wrap ? Math.round(wrap.getBoundingClientRect().top) : null,
      mkTop, mkChips, mkPrecedes, items, vh
    };
  });
  rec('B2a 目标市场常驻入口在结果表之上且首屏内（#mkchips）', '#mkchips 可见 + precedes + top<vh',
    { mkTop: B2.mkTop, chips: B2.mkChips, precedes: B2.mkPrecedes, sticky: B2.stickyAncestor },
    B2.mkTop !== null && B2.mkPrecedes === true && B2.mkTop < B2.vh && B2.mkChips >= 12);
  // Lead 2026-11-14：+5px 属噪声且首屏条目未变，已接受 → 只记录不判定
  rec('B2b 净增 px（#reswrap top，基线 620；Lead 已接受 +5px）', '记录值', { wrapTop: B2.wrapTop }, null);
  // 390 档首屏条目（改前 1）：单列一套，避免只测桌面
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(BASE + 'index.html?q=Tylenol&lang=zh', { waitUntil: 'load', timeout: 40000 });
  try { await page.waitForSelector('#reswrap tbody tr', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(1200);
  B2.items390 = await page.evaluate(() => {
    const vh = window.innerHeight;
    let items = 0;
    document.querySelectorAll('#reswrap tbody tr.br').forEach((r) => {
      const b = r.getBoundingClientRect();
      if (b.width < 4 || b.height < 4) return;
      const y1 = Math.max(b.top, 0), y2 = Math.min(b.bottom, vh);
      if (y2 <= y1) return;
      const frac = (y2 - y1) / b.height;
      if (frac >= 0.9) items += 1; else if (frac >= 0.25) items += 0.5;
    });
    return items;
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  rec('B2c 首屏条目不降（1440 ≥4.275 / 390 ≥0.95，改前 4.5 / 1）', '1440>=4.275 且 390>=0.95',
    { items1440: B2.items, items390: B2.items390 },
    B2.items >= 4.275 && B2.items390 !== null && B2.items390 >= 0.95);

  // ══ T16 「目标市场常驻入口」定位（Lead 2026-11-14 指定必答：.ctry-panel 还是 #mkchips 承载、在不在结果上方）══
  await page.goto(BASE + 'index.html?q=Tylenol&lang=zh', { waitUntil: 'load', timeout: 40000 });
  try { await page.waitForSelector('#reswrap tbody tr', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(1200);
  const MK = await page.evaluate(() => {
    const wrap = document.querySelector('#reswrap');
    const cands = ['#mkchips', '.mkchips', '.ctry-panel', '#country', '.pickbar', '[data-target-market]', '[data-mk-chips]'];
    const rows = [];
    cands.forEach((sel) => {
      document.querySelectorAll(sel).forEach((el) => {
        const b = el.getBoundingClientRect();
        let sticky = false, n = el;
        while (n && n !== document.body) { const cs = getComputedStyle(n); if (cs.position === 'sticky' || cs.position === 'fixed') { sticky = true; break; } n = n.parentElement; }
        rows.push({
          sel, tag: el.tagName.toLowerCase(), id: el.id || null,
          cls: (typeof el.className === 'string' ? el.className : '').slice(0, 40),
          visible: b.height > 0 && b.width > 0,
          top: Math.round(b.top), h: Math.round(b.height),
          precedesReswrap: wrap ? !!(el.compareDocumentPosition(wrap) & Node.DOCUMENT_POSITION_FOLLOWING) : null,
          sticky
        });
      });
    });
    return { vh: window.innerHeight, wrapTop: wrap ? Math.round(wrap.getBoundingClientRect().top) : null, rows };
  });
  rec('T16 目标市场常驻入口：存在可见 + 在结果上方 + 首屏内',
    '至少 1 个候选 visible && precedesReswrap && top<vh', MK,
    MK.rows.some((r) => r.visible && r.precedesReswrap === true && r.top < MK.vh));

  // ══ 页脚版本 ═══════════════════════════════════════════════════════════
  const footer = await page.evaluate(() => {
    const f = document.querySelector('footer');
    return f ? f.innerText.replace(/\s+/g, ' ').trim().slice(0, 160) : null;
  });
  rec('P v0.11.7 页脚', 'true', footer, footer ? /v0\.11\.7/.test(footer) : null);

  return {
    summary: {
      pass: out.filter((x) => x.status === 'pass').length,
      fail: out.filter((x) => x.status === 'fail').length,
      na: out.filter((x) => x.status === 'na').length
    },
    results: out
  };
}
