
const box = document.getElementById('q');
const out = document.getElementById('out');
const ctry = document.getElementById('country');
const meta = document.getElementById('meta');
// 页面在 / 或 /es/ 或 /zh/ 下，资源与内容页都在站点根目录，按 app.js 的位置推根路径
const BASE = ((document.currentScript && document.currentScript.src) || location.href)
  .replace(/assets\/app\.js.*$/, '');
let IDX = [];

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
function cardHTML(e){
  const T = window.T || (k=>k);
  const badge = e.l==='severe' ? `<span class="badge sev">${T('badge.severe')}</span>` :
                e.l==='warning' ? `<span class="badge warn">${T('badge.warning')}</span>` : '';
  const tags = e.c.map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
  const link = e.u ? `${BASE}name/${e.u}` : `${BASE}drug/${e.v}.html`;
  return `<div class="card">
    <h3><a href="${link}">${e.d}</a>${tags}${badge}</h3>
    <div class="meta">${e.x} · ${e.s.join(' / ')||'—'} · ${e.f}
    ${e.n>1?` · ${e.n} ${T('card.packs')}`:''}</div></div>`;
}
function render(){
  const q = box.value.trim();
  if(!q){ out.innerHTML=''; meta.textContent=''; return; }
  const nq = norm(q);
  const st = strengthOf(q);
  const c = ctry.value;
  let hits=[];
  for(const e of IDX){
    const t = tier(nq, e.k);
    if(!t) continue;
    if(c && !e.c.includes(c)) continue;
    let score = 0.55*t[1] + 0.20*(c && e.c.includes(c) ? 1 : 0.5);
    score += 0.15*(st && e.s.some(x=>x.toLowerCase().startsWith(st[0]+' ')) ? 1 : 0.5);
    score += 0.05;
    hits.push([score, t[0], e]);
  }
  hits.sort((a,b)=> b[0]-a[0] || b[2].n-a[2].n || a[2].d.length-b[2].d.length);
  const shown = hits.slice(0,40);
  const T = window.T || (k=>k);
  meta.textContent = hits.length ? `${hits.length} ${T('res.matched')}` :
    (c ? `${T('res.none')} — ${T('res.notin')}. ${T('res.caveat')}.`
       : `${T('res.none')} — ${T('res.caveat')}.`);
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
    extraHTML += `<h2>${T2('fam.title')}</h2>` + members.map(cardHTML).join('');
  }
  out.innerHTML = warnHTML + shown.map(([score, t, e])=>cardHTML(e)).join('') + extraHTML;
}
box.addEventListener('input', render);
ctry.addEventListener('change', render);
document.querySelectorAll('[data-q]').forEach(b=>b.addEventListener('click',()=>{
  box.value=b.dataset.q; render(); box.focus();
}));
const initial = new URLSearchParams(location.search).get('q');
if(initial){ box.value = initial; }
out.innerHTML = '<div class="sub">Loading index… 正在加载索引（约 10 MB，第一次会慢一点）</div>';
fetch(BASE + 'data/index.json').then(r=>r.json()).then(d=>{IDX=d; render();})
  .catch(()=>{ out.innerHTML='<div class="notice">索引没加载成功：'
    +'如果是在本地双击打开，浏览器会拦截本地文件读取。<br>'
    +'请用 <kbd>python -m http.server</kbd> 起一个本地服务，再访问 '
    +'<kbd>http://localhost:8000/</kbd>。</div>'; });
