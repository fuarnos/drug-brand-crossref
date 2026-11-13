// 改后核对断言（T10 + T12 / v0.11.6）— 可执行版，配套 reports/2026-11-14-after-compare.checklist.md
//
// 用法：把本文件全文粘进 mcp__browser__browser_run_code_unsafe 的 code 参数
//      （浏览器工具只允许读写 …\default-workspace\_tmp\browser-out\ 与 …\.dsh\profiles\desktop\，
//       不能直接加载仓库里的文件 → 只能内联）。
// 前置：site/dist 已重建（页脚 v0.11.6），& $py serve.py 8000 在跑。
// 输出：[{id, status:'pass'|'fail'|'na', expect, got}]，status 为 na 的一律人工复核，不许判绿。
async (page) => {
  const BASE = 'http://127.0.0.1:8000/';
  const out = [];
  const rec = (id, expect, got, ok) => out.push({ id, status: ok === null ? 'na' : (ok ? 'pass' : 'fail'), expect, got });
  const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const count = (hay, re) => (hay.match(re) || []).length;

  // ── A. 结果页 ?q=Tylenol ────────────────────────────────────────────────
  await page.goto(BASE + 'index.html?q=Tylenol', { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForSelector('#reswrap tbody tr', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(800);
  const A = await page.evaluate(() => {
    const rows = Array.prototype.slice.call(document.querySelectorAll('#reswrap tbody tr.br'));
    const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const row = rows.find((r) => /Tylenol Extra Strength/.test(r.innerText));
    const dose = row ? flat((row.querySelector('.c-dose') || {}).innerText) : null;
    const bodyText = flat(document.body.innerText);
    const FORMS = ['片剂', '胶囊', '液体', '粉末', '颗粒', '栓剂', '泡腾剂', '注射剂', '外用', '口服溶液'];
    return {
      rowCount: rows.length,
      dose,
      doseHtml: row ? (row.querySelector('.c-dose') || {}).innerHTML || null : null,
      hasPerVolume: /960\s*mg\s*\/\s*30\s*mL/.test(bodyText),
      nFormsInDose: dose ? FORMS.filter((f) => dose.indexOf(f) >= 0).length : 0,
      isCandidateSet: /候选/.test(bodyText) && /结果永远是候选集/.test(bodyText.slice(0, 4000)),
      tableClass: (document.querySelector('#reswrap table') || {}).className || null,
      grpRows: document.querySelectorAll('#reswrap tbody tr.grp').length
    };
  });
  rec('A1 不再「500mg/960mg + 单一剂型」并存',
    'true',
    A.dose,
    A.dose === null ? null : !(/500\s*mg\s*\/\s*960\s*mg/.test(A.dose) && /片剂/.test(A.dose) && !/多剂型/.test(A.dose)));
  rec('A2 出现 960 mg/30 mL', 'true', A.hasPerVolume ? 'present' : 'absent', A.hasPerVolume);
  rec('A3 多剂型显示「多剂型」或 ≥2 个剂型词', 'true',
    { dose: A.dose, nForms: A.nFormsInDose },
    A.dose === null ? null : (/多剂型/.test(A.dose) || A.nFormsInDose >= 2));
  rec('A6 候选集语义仍在', 'true', A.isCandidateSet, A.isCandidateSet);

  // ── B. 品牌页 ───────────────────────────────────────────────────────────
  await page.goto(BASE + 'name/tylenol-extra-strength.html', { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForSelector('main h1', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(800);
  const B = await page.evaluate(() => {
    const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const main = document.querySelector('main');
    const mainText = flat(main ? main.innerText : '');
    const h2s = Array.prototype.map.call(document.querySelectorAll('main h2'), (h) => flat(h.innerText));
    const badges = document.querySelectorAll('.nolang-badge').length;
    const firstH2 = document.querySelector('main h2');
    const badgeInFirstH2 = firstH2 ? firstH2.querySelectorAll('.nolang-badge').length : 0;
    const cmpLabels = ['市场', '注册名', '完整活性成分', '关系说明']
      .filter((t) => mainText.indexOf(t) >= 0).length;
    return {
      h1: flat((document.querySelector('main h1') || {}).innerText),
      h2s, badges, badgeInFirstH2, cmpLabels,
      collide: (mainText.match(/碰撞/g) || []).length,
      // 「泰诺泰诺林重复」的真实形态：列表里 <a>泰诺</a><span class="tag">泰诺</span> → 同一名字连排两次。
      // 注意警示句/家族表里合法提一次名字是允许的，所以这里判「连排重复」而不是「总次数」。
      dupPairs: (mainText.match(/泰诺\s*泰诺(?!林)/g) || []).length + (mainText.match(/泰诺林\s*泰诺林/g) || []).length,
      liDup: Array.prototype.filter.call(document.querySelectorAll('main ul.sub li'), (li) => {
        const a = li.querySelector('a');
        const name = a ? (a.innerText || '').trim() : '';
        if (!name) return false;
        return (li.innerText || '').split(name).length - 1 >= 2; // 同一个名字在一条 li 里出现 ≥2 次
      }).length,
      taiNuo: (mainText.match(/泰诺(?!林)/g) || []).length,
      taiNuoLin: (mainText.match(/泰诺林/g) || []).length,
      forbidden: (mainText.match(/等价|可替代|效果相同|等同|可以互换/g) || []).length,
      noInterchange: /不可互换|不代表可以互换/.test(mainText),
      mainTextLen: mainText.length,
      mainText: mainText.slice(0, 600)
    };
  });
  rec('B1 成分标题旁无「无中文名」徽标', '0', B.badgeInFirstH2, B.badgeInFirstH2 === 0);
  rec('B2 全页「无中文名」徽标数', '0', B.badges, B.badges === 0);
  rec('B3 H2 = 相关品牌名称与配方差异', 'true',
    B.h2s, B.h2s.some((t) => /相关品牌名称与配方差异/.test(t)));
  rec('B4 品牌页「碰撞」计数', '0', B.collide, B.collide === 0);
  rec('B5 名称不再连排重复（泰诺泰诺 / 泰诺林泰诺林）', 'dupPairs=0, liDup=0',
    { dupPairs: B.dupPairs, liDup: B.liDup },
    B.dupPairs === 0 && B.liDup === 0);
  rec('B6 泰诺/泰诺林 各自次数不超标（列表 1 + 家族表 ≤1）', '泰诺≤2 且 泰诺林≤2',
    { taiNuo: B.taiNuo, taiNuoLin: B.taiNuoLin },
    B.taiNuo <= 2 && B.taiNuoLin <= 2);
  rec('B7 家族对比 4 个标签齐全', '4', B.cmpLabels, B.cmpLabels === 4);
  rec('B8 无「等价/可替代/效果相同」话术', '0', B.forbidden, B.forbidden === 0);
  rec('B9 「不可互换」类提示仍在', 'true', B.noInterchange, B.noInterchange);

  // ── C. 成分页 ───────────────────────────────────────────────────────────
  await page.goto(BASE + 'drug/acetaminophen.html', { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForSelector('.mkrow', { timeout: 15000 }); } catch (e) {}
  await page.waitForTimeout(800);
  const C = await page.evaluate(() => {
    const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const main = document.querySelector('main');
    const mainText = flat(main ? main.innerText : '');
    const heads = Array.prototype.map.call(document.querySelectorAll('main h2, main h3'), (h) => flat(h.innerText));
    const monoHead = heads.findIndex((t) => /仅含此成分|只含此成分/.test(t));
    const comboHead = heads.findIndex((t) => /含此成分的复方|复方制品/.test(t));
    // 段内文本：从段标题开始，沿兄弟节点往后收集，直到下一个段标题为止（不依赖固定标签名）
    let monoText = '', comboText = '';
    const allHeads = Array.prototype.slice.call(document.querySelectorAll('main h2, main h3'));
    allHeads.forEach((h, i) => {
      const t = flat(h.innerText);
      const until = allHeads[i + 1] || null;
      let buf = '';
      let n = h.parentElement ? h.nextElementSibling : null;
      while (n && n !== until) { buf += ' ' + flat(n.innerText); n = n.nextElementSibling; }
      if (/仅含此成分|只含此成分/.test(t)) monoText += ' ' + buf;
      if (/含此成分的复方|复方制品/.test(t)) comboText += ' ' + buf;
    });
    // 499.9996 出现位置
    const nodes = [];
    const walk = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    let tn;
    while ((tn = walk.nextNode())) {
      if (tn.nodeValue && tn.nodeValue.indexOf('499.9996') >= 0) nodes.push(tn.parentElement);
    }
    const badOrig = nodes.filter((el) => !el.closest('small, .m-orig, .sub, .meta, [data-i18n="matrix.original"]')).length;
    return {
      h1: flat((document.querySelector('main h1') || {}).innerText),
      heads: heads.slice(0, 12),
      hasMono: monoHead >= 0,
      hasCombo: comboHead >= 0,
      monoText: flat(monoText).slice(0, 300),
      comboText: flat(comboText).slice(0, 300),
      comboBad: /tramacet|zaldiar|oxycodone|tramadol/i.test(monoText),
      comboIngs: (/tramadol/i.test(comboText) ? 1 : 0) + (/acetaminophen|paracetamol/i.test(comboText) ? 1 : 0),
      comboNums: (comboText.match(/\d+(\.\d+)?\s*mg/gi) || []).length,
      perVolume: (mainText.match(/960\s*mg\s*\/\s*30\s*mL/g) || []).length,
      n499: nodes.length,
      badOrig,
      blocks: document.querySelectorAll('.mkblock').length,
      rows: document.querySelectorAll('.mkrow').length,
      noInterchange: /不可互换|不代表可以互换/.test(mainText),
      mainTextLen: mainText.length
    };
  });
  rec('C1 单方段/复方段标题都在', '2/2', { heads: C.heads, hasMono: C.hasMono, hasCombo: C.hasCombo }, C.hasMono && C.hasCombo);
  rec('C2 单方段不含复方名', '0（且必须真有单方段）', { hit: C.comboBad, hasMono: C.hasMono, monoText: C.monoText }, C.hasMono ? !C.comboBad : null);
  rec('C3 复方行含 2 个成分 + ≥2 个含量', 'true', { ings: C.comboIngs, nums: C.comboNums, comboText: C.comboText }, C.comboIngs >= 2 && C.comboNums >= 2);
  rec('C4 「960 mg/30 mL」出现 ≥1', '>=1', C.perVolume, C.perVolume >= 1);
  rec('C5 499.9996 只在原记录小字里', 'badOrig=0', { n499: C.n499, badOrig: C.badOrig }, C.n499 === 0 ? null : C.badOrig === 0);
  rec('C6 归整显示 500 mg（原始值仍在原记录里）', 'true',
    { n499: C.n499, has500: /500 mg/.test(C.monoText) },
    C.n499 === 0 ? null : (/500 mg/.test(C.monoText) && C.badOrig === 0));
  rec('C7 结构没塌（h1/块/行）', 'h1=Acetaminophen, blocks>=11, rows>=100', { h1: C.h1, blocks: C.blocks, rows: C.rows }, C.h1 === 'Acetaminophen' && C.blocks >= 11 && C.rows >= 100);
  rec('C8 「不可互换」提示仍在', 'true', C.noInterchange, C.noInterchange);

  // ── D. 红线（三页可见文本）─────────────────────────────────────────────
  const pagesForRedline = [
    ['results', 'index.html?q=Tylenol', '#reswrap tbody tr'],
    ['brand', 'name/tylenol-extra-strength.html', 'main h1'],
    ['drug', 'drug/acetaminophen.html', '.mkrow']
  ];
  for (const [id, url, ready] of pagesForRedline) {
    await page.goto(BASE + url, { waitUntil: 'load', timeout: 30000 });
    try { await page.waitForSelector(ready, { timeout: 15000 }); } catch (e) {}
    await page.waitForTimeout(700);
    const R = await page.evaluate(() => {
      const flat = (s) => (s || '').replace(/\s+/g, ' ').trim();
      const main = document.querySelector('main');
      let t = flat(main ? main.innerText : '');
      const raw = t;
      // 先剥掉「合规的反向声明」：它们含「替代 / 换药 / 剂量换算」，但正是红线要求保留的话术。
      // 注意「不建议替换药品」本身就含「换药」——不剥会把合规句判成违规（静态扫描已踩过这个坑）。
      const compliant = t
        .replace(/本站只做标识对应，不构成用药建议，不能替代医师或药师。/g, '')
        .replace(/不建议替换药品/g, '')
        .replace(/不做剂量换算/g, '')
        .replace(/不给用药建议/g, '')
        .replace(/这不是医疗建议。换药前请核对实际包装与成分，并咨询药师。/g, '');
      return {
        advice: (compliant.match(/(可以|可)替代|换药|应服用|recommended dose|equivalent dose|剂量换算|equivalent to/gi) || []).length,
        collision: (raw.match(/collision/gi) || []).length,
        collisionDom: document.querySelectorAll('[class*="collision"], [data-collision]').length,
        penzhuang: (raw.match(/碰撞/g) || []).length,
        dosing: (compliant.match(/mg\/kg|按体重|等剂量|换算成/gi) || []).length,
        hasBottomLine: /候选|不可互换|不代表可以互换/.test(raw),
        len: raw.length
      };
    });
    rec(`D1[${id}] 无用药建议话术`, '0', R.advice, R.advice === 0);
    rec(`D2[${id}] 无 collision 术语`, '0', { text: R.collision, dom: R.collisionDom }, R.collision === 0 && R.collisionDom === 0);
    rec(`D3[${id}] 无「碰撞」`, '0', R.penzhuang, R.penzhuang === 0);
    rec(`D4[${id}] 无剂量换算/按体重`, '0', R.dosing, R.dosing === 0);
    rec(`D5[${id}] 底线提示仍在`, 'true', R.hasBottomLine, R.hasBottomLine);
  }

  // ── P. 版本 ─────────────────────────────────────────────────────────────
  const footer = await page.evaluate(() => {
    const f = document.querySelector('footer');
    return f ? f.innerText.replace(/\s+/g, ' ').trim().slice(0, 200) : null;
  });
  rec('P3 页脚版本 v0.11.6', 'true', footer, footer ? /v0\.11\.6/.test(footer) : null);

  return out;
}
