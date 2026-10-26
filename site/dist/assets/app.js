
const box = document.getElementById('q');
const out = document.getElementById('out');
const ctry = document.getElementById('country');
const meta = document.getElementById('meta');
// 页面在 / 或 /es/ 或 /zh/ 下，资源与内容页都在站点根目录，按 app.js 的位置推根路径
const BASE = ((document.currentScript && document.currentScript.src) || location.href)
  .replace(/assets\/app\.js.*$/, '');
let IDX = [], NICKS = [], CONF = [];

function norm(s){
  return (s||'').normalize('NFKC').toLowerCase()
    .replace(/[®™©]/g,' ')
    .replace(/[\u0300-\u036f]/g,'')
    .replace(/\s+/g,' ').trim();
}
function splitDose(q){
  // 把「Lipitor 20mg」「两只青蛙 500mg」「875/125 mg」里的剂量切出来，
  // 名字部分才拿去和索引比对——不切的话带剂量的搜索会一个都命中不了。
  const ratio = q.match(/([\d.]+)\s*\/\s*([\d.]+)\s*(mg|mcg|µg|ug|g)\b/i);
  const single = q.match(/([\d.]+)\s*(mg|mcg|µg|ug|g|ml|iu|%|万单位)\b/i);
  const m = ratio || single;
  if(!m) return [q, null];
  const rest = (q.slice(0, m.index) + ' ' + q.slice(m.index + m[0].length))
    .replace(/\s+/g,' ').trim();
  return [rest, [m[1], (ratio ? m[3] : m[2]).toLowerCase()]];
}
function lev(a,b){
  if(Math.abs(a.length-b.length)>3) return 99;
  const d=Array.from({length:b.length+1},(_,i)=>i);
  for(let i=1;i<=a.length;i++){
    let prev=d[0]; d[0]=i;
    for(let j=1;j<=b.length;j++){
      const t=d[j];
      d[j]=Math.min(d[j]+1,d[j-1]+1,prev+(a[i-1]===b[j-1]?0:1));
      prev=t;
    }
  }
  return d[b.length];
}
function tier(nq,k){
  if(k===nq) return ['exact',1.0];
  if(k.replace(/ /g,'')===nq.replace(/ /g,'')) return ['compact',0.95];
  if(k.startsWith(nq)) return ['prefix',0.80];
  // 中文药名普遍很短：「利嗪」「头孢」「地平」这种两三个字就是有效线索，
  // 用英文的四字下限会把只记得一部分的人挡在门外。
  const cjk = /[\u4e00-\u9fff]/.test(nq);
  const minSub = cjk ? 2 : 4;
  if(nq.length>=minSub && k.includes(nq)) return ['contains',0.70];
  if(nq.length>=4 && lev(nq,k) <= (nq.length>=9 ? 3 : 2)) return ['fuzzy',0.55];
  return null;
}
function doseNum(s){ const m=(s||'').match(/[\d.]+/); return m?parseFloat(m[0]):0; }
function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function aliasHits(nq){
  // 俗称只做精确 / 连写命中：昵称差一个字往往就是另一个梗，模糊匹配会闹笑话。
  return NICKS.filter(a => a.n === nq || a.n.replace(/ /g,'') === nq.replace(/ /g,''));
}
function confHits(nq){
  // 易混淆药对也只做精确命中：这是「名字像」的提示，不做模糊扩展。
  return CONF.filter(p => p.n === nq);
}
function rowHTML(r){
  const T = window.T || (k=>k);
  const badge = r.l==='severe' ? `<span class="badge sev">${T('badge.severe')}</span>` :
                r.l==='warning' ? `<span class="badge warn">${T('badge.warning')}</span>` : '';
  const tags = r.c.map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
  const link = r.u ? `${BASE}name/${r.u}` : `${BASE}drug/${r.v}.html`;
  const mah = r.m ? (r.mn > 1 ? `${r.m} <span class="more">+${r.mn-1}</span>` : r.m) : '';
  return `<tr>
    <td class="c-ing">${r.x || '—'}</td>
    <td class="c-dose">${r.d || '—'}</td>
    <td class="c-brand"><a href="${link}">${r.b}</a>${tags}${badge}</td>
    <td class="c-mah">${mah || '—'}</td></tr>`;
}
function render(){
  const q = box.value.trim();
  if(!q){ out.innerHTML=''; meta.textContent='';
    const r0 = document.getElementById('report'); if(r0) r0.style.display='none'; return; }
  const [nameQ, st] = splitDose(q);
  const nq = norm(nameQ);
  const c = ctry.value;
  const nicks = aliasHits(nq);
  const confs = confHits(nq);
  const nickSids = new Set(nicks.map(a=>a.v).filter(Boolean));
  let hits=[];
  const seen = new Set();
  const addHit = (e, t) => {
    if(seen.has(e.k)) return;
    seen.add(e.k);
    let score = 0.55*t[1] + 0.20*(c && e.c.includes(c) ? 1 : 0.5);
    score += 0.15*(st && e.s.some(x=>x.toLowerCase().startsWith(st[0]+' ')) ? 1 : 0.5);
    score += 0.05;
    hits.push([score, t[0], e]);
  };
  // 第一遍只认确切的几种匹配；模糊匹配要等确定命中太少时才补，
  // 否则搜 Lipitor 会把 Zifitor、Dipifor 这些隔壁牌子一起倒出来。
  for(const e of IDX){
    // 复方产品：e.x 是这条名字下成分的中文/英文展示串（最多 6 个），
    // 直接按成分名 tokens 比对，比在每个索引条目里再存一份 vs 数组省 4 MB。
    const subs = (e.x || '').split(' + ');
    const byNick = (e.v && nickSids.has(e.v)) ||
      nicks.some(a => a.i && subs.includes(a.i));
    const t = byNick ? ['nickname', 1.0] : tier(nq, e.k);
    if(!t || t[0]==='fuzzy') continue;
    if(c && !e.c.includes(c)) continue;
    addHit(e, t);
  }
  let fuzzyUsed = false;
  if(hits.length === 0 && nicks.length === 0){
    for(const e of IDX){
      const t = tier(nq, e.k);
      if(!t || t[0]!=='fuzzy') continue;
      if(c && !e.c.includes(c)) continue;
      const before = hits.length;
      addHit(e, t);
      if(hits.length > before) fuzzyUsed = true;
    }
  }
  hits.sort((a,b)=> b[0]-a[0] || b[2].n-a[2].n || a[2].d.length-b[2].d.length);
  const shown = hits.slice(0,40);
  const T = window.T || (k=>k);
  if(!hits.length && nicks.length){
    meta.textContent = `${nicks.length} ${T('res.alias')} · ${T('res.alias_no_products')}`;
  } else {
    meta.textContent = hits.length
      ? (fuzzyUsed
          ? `${T('res.fuzzy')} · ${hits.length} ${T(nicks.length ? 'res.brands' : 'res.matched')}`
          : `${hits.length} ${T(nicks.length ? 'res.brands' : 'res.matched')}`)
      : (c ? `${T('res.none')} — ${T('res.notin')}. ${T('res.caveat')}.`
           : `${T('res.none')} — ${T('res.caveat')}.`);
  }
  // 俗称命中：先说清「这不是商品名，是某个成分的叫法」，再列该成分的商品名。
  let nickHTML = '';
  if(nicks.length){
    nickHTML = nicks.slice(0,3).map(a=>{
      const target = a.v
        ? `<a href="${BASE}drug/${encodeURIComponent(a.v)}.html">${esc(a.x)}</a>`
        : `<b>${esc(a.x)}</b>`;
      const detail = window.LANG === 'zh' ? (a.hint || a.m) : (a.me || '');
      const hint = detail ? `<div class="sub">${esc(detail)}</div>` : '';
      const packs = a.np ? ` · ${a.np} ${T('card.packs')}` : '';
      const caveat = a.k === 'class' ? T('nick.class_caveat')
        : a.k === 'folk' ? T('nick.folk_caveat')
        : (a.v ? T('nick.caveat') : T('nick.nomap_caveat'));
      return `<div class="notice nick"><div class="nick-head">${T('nick.hit')}：
        <b>${esc(a.a)}</b> → ${target}
        <span class="tag">${esc(T('nick.'+a.k))}</span></div>
        <div class="sub">${caveat}${packs}</div>${hint}</div>`;
    }).join('');
    if(nicks.length > 1) nickHTML += `<div class="notice">${T('nick.ambiguous')}</div>`;
  }
  let confHTML = '';
  if(confs.length){
    const items = confs.slice(0,6).map(p=>{
      const label = p.sid
        ? `<a href="${BASE}drug/${encodeURIComponent(p.sid)}.html">${esc(p.x)}</a>`
        : `<b>${esc(p.x)}</b>`;
      const tml = p.tml ? ` <code>${esc(p.tml)}</code>` : '';
      return label + tml;
    }).join('、');
    confHTML = `<div class="notice warnbox"><b>${T('conf.search_hit')}：</b>${items}.
      <a href="${BASE}confused.html">${T('drug.confused_all')}</a></div>`;
  }
  const shownKeys = new Set(shown.map(x=>x[2].k));
  const byFam = new Map();
  for(const [, , e] of shown){
    if(!e.g) continue;
    if(!byFam.has(e.g)) byFam.set(e.g, {note:e.gn||'', comps:new Set()});
    byFam.get(e.g).comps.add(e.x);
  }
  let warnHTML = '';
  const T2 = window.T || (k=>k);
  for(const [label, f] of byFam){
    if(f.comps.size > 1){
      warnHTML += `<div class="notice"><b>${T2('fam.warn')}：${label}。</b>${f.note||''}</div>`;
    }
  }
  let extraHTML = '';
  for(const [label, f] of byFam){
    const members = IDX.filter(x=>x.g===label && !shownKeys.has(x.k));
    if(!members.length) continue;
    extraHTML += `<h2>${T2('fam.title')}</h2>` +
      members.map(e=>`<div class="card"><h3><a href="${e.u?BASE+'name/'+e.u:BASE+'drug/'+e.v+'.html'}">${e.d}</a></h3>
      <div class="meta">${e.x} · ${e.s.join(' / ')||'—'}</div></div>`).join('');
  }
  // 主结果：保留相关度顺序（精确命中在前），每一行内部再按剂量数字排序。
  // 这样"成分-剂量"始终是最左两列，但不会被无关的模糊命中顶到前面。
  let rows=[];
  for(const [, , e] of shown){
    const ds = (e.s && e.s.length) ? e.s.slice().sort((a,b)=>doseNum(a)-doseNum(b)) : [''];
    for(const d of ds) rows.push({x:e.x, d:d, b:e.d, m:e.m, mn:e.mn, c:e.c, l:e.l, u:e.u, v:e.v});
  }
  const capped = rows.slice(0, 80);

  // 精确命中某个品牌之后，再把「同一成分的其他商品」单独列一段：
  // 用户搜的是牌子，但真正想知道的往往是这个成分还有哪些选择。
  let sameHTML = '';
  const exactSubs = new Set();
  for(const [, t, e] of shown){
    if(t !== 'exact' && t !== 'compact') continue;
    (e.vs && e.vs.length ? e.vs : [e.v]).forEach(s => exactSubs.add(s));
  }
  if(exactSubs.size && exactSubs.size <= 6){
    const others = IDX.filter(x => !shownKeys.has(x.k) &&
      (x.vs && x.vs.length ? x.vs : [x.v]).some(s => exactSubs.has(s)));
    if(others.length){
      const oRows = [];
      for(const e of others.slice(0, 40)){
        const ds = (e.s && e.s.length) ? e.s.slice().sort((a,b)=>doseNum(a)-doseNum(b)) : [''];
        for(const d of ds) oRows.push({x:e.x, d:d, b:e.d, m:e.m, mn:e.mn, c:e.c, l:e.l, u:e.u, v:e.v});
      }
      sameHTML = `<h2>${T2('same.ing')}</h2>` +
        `<p class="sub">${T2('same.note')}</p>` +
        `<table class="res"><thead><tr>
          <th>${T2('col.ing')}</th><th>${T2('col.dose')}</th>
          <th>${T2('col.brand')}</th><th>${T2('col.mah')}</th>
        </tr></thead><tbody>${oRows.slice(0,80).map(rowHTML).join('')}</tbody></table>`;
    }
  }

  out.innerHTML = confHTML + nickHTML + warnHTML + (capped.length ? `<table class="res"><thead><tr>
      <th>${T2('col.ing')}</th><th>${T2('col.dose')}</th>
      <th>${T2('col.brand')}</th><th>${T2('col.mah')}</th>
    </tr></thead><tbody>${capped.map(rowHTML).join('')}</tbody></table>` : '') + sameHTML + extraHTML;
  const rep = document.getElementById('report');
  if(rep){
    rep.style.display = 'block';
    const a = document.getElementById('reportLink');
    if(a) a.href = reportURL(q);
  }
}
function reportURL(q){
  const body = [
    '**查询词 / query**: ' + (q || ''),
    '**页面 / page**: ' + location.href,
    '**期望结果 / expected**: ',
    '**实际结果 / actual**: ',
    '**包装或批号 / pack or lot**: ',
    ''
  ].join('\n');
  return 'https://github.com/fuarnos/drug-brand-crossref' + '/issues/new?labels=data-error&template=data-error.yml'
    + '&title=' + encodeURIComponent('数据错误: ' + (q || ''))
    + '&body=' + encodeURIComponent(body);
}
box.addEventListener('input', render);
ctry.addEventListener('change', render);
document.querySelectorAll('[data-q]').forEach(b=>b.addEventListener('click',()=>{
  box.value=b.dataset.q; render(); box.focus();
}));
const initial = new URLSearchParams(location.search).get('q');
if(initial){ box.value = initial; }
out.innerHTML = '<div class="sub">Loading index… 正在加载索引（第一次会慢一点）</div>';
Promise.all([
  fetch(BASE + 'data/index.json').then(r=>r.json()),
  fetch(BASE + 'data/aliases.json').then(r=>r.json()).catch(()=>[]),
  fetch(BASE + 'data/confused.json').then(r=>r.json()).catch(()=>[])
]).then(([d,a,c])=>{IDX=d||[]; NICKS=a||[]; CONF=c||[]; render();})
  .catch(()=>{ out.innerHTML='<div class="notice">索引没加载成功：'
    +'如果是在本地双击打开，浏览器会拦截本地文件读取。<br>'
    +'请用 <kbd>python -m http.server</kbd> 起一个本地服务，再访问 '
    +'<kbd>http://localhost:8000/</kbd>。</div>'; });
