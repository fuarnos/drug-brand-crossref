
const box = document.getElementById('q');
const out = document.getElementById('out');
const ctry = document.getElementById('country');
const meta = document.getElementById('meta');
// 页面在 / 或 /es/ 或 /zh/ 下，资源与内容页都在站点根目录，按 app.js 的位置推根路径
const BASE = ((document.currentScript && document.currentScript.src) || location.href)
  .replace(/assets\/app\.js.*$/, '');
let IDX = [], NICKS = [];

function norm(s){
  return (s||'').normalize('NFKC').toLowerCase()
    .replace(/[®™©]/g,' ')
    .replace(/[\u0300-\u036f]/g,'')
    .replace(/\s+/g,' ').trim();
}
function strengthOf(q){
  const m = q.match(/([\d.]+)\s*(mg|mcg|g|ml|iu|%|万单位)/i);
  return m ? [m[1], m[2].toLowerCase()] : null;
}
function lev(a,b){
  if(Math.abs(a.length-b.length)>2) return 99;
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
  if(nq.length>=4 && k.includes(nq)) return ['contains',0.70];
  if(nq.length>=4 && lev(nq,k)<=2) return ['fuzzy',0.55];
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
  if(!q){ out.innerHTML=''; meta.textContent=''; return; }
  const nq = norm(q);
  const st = strengthOf(q);
  const c = ctry.value;
  const nicks = aliasHits(nq);
  const nickSids = new Set(nicks.map(a=>a.v));
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
    const byNick = nickSids.has(e.v) || nicks.some(a => subs.includes(a.i));
    const t = byNick ? ['nickname', 1.0] : tier(nq, e.k);
    if(!t || t[0]==='fuzzy') continue;
    if(c && !e.c.includes(c)) continue;
    addHit(e, t);
  }
  if(hits.length === 0){
    for(const e of IDX){
      const t = tier(nq, e.k);
      if(!t || t[0]!=='fuzzy') continue;
      if(c && !e.c.includes(c)) continue;
      addHit(e, t);
    }
  }
  hits.sort((a,b)=> b[0]-a[0] || b[2].n-a[2].n || a[2].d.length-b[2].d.length);
  const shown = hits.slice(0,40);
  const T = window.T || (k=>k);
  meta.textContent = hits.length
    ? `${hits.length} ${T(nicks.length ? 'res.brands' : 'res.matched')}`
    : (c ? `${T('res.none')} — ${T('res.notin')}. ${T('res.caveat')}.`
         : `${T('res.none')} — ${T('res.caveat')}.`);
  // 俗称命中：先说清「这不是商品名，是某个成分的叫法」，再列该成分的商品名。
  let nickHTML = '';
  if(nicks.length){
    nickHTML = nicks.slice(0,3).map(a=>{
      const href = `${BASE}drug/${encodeURIComponent(a.v)}.html`;
      const hint = (window.LANG === 'zh' && a.hint)
        ? `<div class="sub">${esc(a.hint)}</div>` : '';
      const packs = a.np ? ` · ${a.np} ${T('card.packs')}` : '';
      return `<div class="notice nick"><div class="nick-head">${T('nick.hit')}：
        <b>${esc(a.a)}</b> → <a href="${href}">${esc(a.x)}</a>
        <span class="tag">${esc(T('nick.'+a.k))}</span></div>
        <div class="sub">${T('nick.caveat')}${packs}</div>${hint}</div>`;
    }).join('');
    if(nicks.length > 1) nickHTML += `<div class="notice">${T('nick.ambiguous')}</div>`;
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
  out.innerHTML = nickHTML + warnHTML + `<table class="res"><thead><tr>
      <th>${T2('col.ing')}</th><th>${T2('col.dose')}</th>
      <th>${T2('col.brand')}</th><th>${T2('col.mah')}</th>
    </tr></thead><tbody>${capped.map(rowHTML).join('')}</tbody></table>` + extraHTML;
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
  fetch(BASE + 'data/aliases.json').then(r=>r.json()).catch(()=>[])
]).then(([d,a])=>{IDX=d||[]; NICKS=a||[]; render();})
  .catch(()=>{ out.innerHTML='<div class="notice">索引没加载成功：'
    +'如果是在本地双击打开，浏览器会拦截本地文件读取。<br>'
    +'请用 <kbd>python -m http.server</kbd> 起一个本地服务，再访问 '
    +'<kbd>http://localhost:8000/</kbd>。</div>'; });
