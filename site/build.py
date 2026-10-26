"""静态站生成：SQLite → site/dist/

产物：
    index.html          搜索（客户端匹配，返回候选集与碰撞提示）
    drug/<id>.html      成分身份卡（各国商品名对照）
    name/<id>.html      名字页（这个名字下挂了哪些药——碰撞页）
    about.html          数据来源、覆盖率、免责
    data/index.json     检索索引
    data/aliases.json   俗称 / 网络别名索引
    assets/             css + js

用法：python site/build.py
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
OUT = ROOT / "site" / "dist"

DISEASE_NOTE = (
    "本站只做「名字 → 成分」的标识对应，不提供用药建议、"
    "不换算服药剂量、不建议替换药品。"
)

# 三语界面文案。英文是默认、也是 HTML 里的兜底文本；
# 页面加载后 i18n.js 按 ?lang= / localStorage / 浏览器语言替换带 data-i18n 的元素。
I18N = {
    "en": {
        "nav.search": "Search", "nav.about": "About",
        "home.h1": "Find out what a medicine really is",
        "home.sub": ("Type a brand name, a generic name, a nickname (try 两只青蛙), or a line "
                     "from the pack. Chinese, full-width and Cyrillic input all work, and you can "
                     "include the dose — e.g. Lipitor 20mg, 泰诺, СОРТИС."),
        "home.ph": "Brand name / generic name / nickname / a line from the pack",
        "home.all": "All countries", "home.us": "United States",
        "home.gb": "United Kingdom", "home.cn": "China", "home.es": "Spain",
        "home.mx": "Mexico", "home.au": "Australia",
        "home.coverage": ("An empty result does not mean the medicine does not exist. "
                          "Coverage:"),
        "home.loading": "Loading index…",
        "res.matched": "names matched", "res.none": "No match",
        "res.brands": "brand names found",
        "res.notin": "Not covered in this country",
        "res.caveat": "an empty result does not mean the drug does not exist",
        "card.packs": "packs",
        "col.ing": "Ingredient", "col.dose": "Dose",
        "col.brand": "Brand", "col.mah": "Manufacturer",
        "same.ing": "Other products with the same ingredient",
        "same.note": "You searched a brand name — this is what else contains the same active ingredient.",
        "badge.severe": "Same name, different drug",
        "badge.warning": "Different release",
        "fam.title": "The same brand in other markets",
        "fam.warn": "Same brand, different drug",
        "drug.brand": "Brand", "drug.strength": "Strength", "drug.nostrength": "not disclosed",
        "drug.release": "Release", "drug.status": "Status",
        "drug.records": "records", "drug.showing": "showing first 40 of",
        "drug.sid": "Substance ID",
        "drug.notice": ("The same ingredient can carry completely different brand names in "
                        "different countries, and the same name can point to a different "
                        "ingredient. Listed by country — not interchangeable."),
        "drug.empty": "No products recorded yet.",
        "name.countries": "Countries", "name.form": "Form",
        "name.strength": "Strength", "name.release": "Release",
        "name.also": "Also written as", "name.found": "Found in",
        "name.empty": "No records",
        "name.severe": ("This brand name points to different active ingredients in different "
                        "countries or variants. Check the composition, never treat the names "
                        "as equivalent."),
        "name.warning": ("Same name, but immediate vs modified release — not interchangeable."),
        "nick.hit": "Nickname",
        "nick.slang": "internet nickname", "nick.legacy": "older name",
        "nick.translit": "transliterated old name", "nick.abbrev": "abbreviation",
        "nick.misnomer": "common misnomer",
        "nick.ambiguous": ("This nickname may point to more than one ingredient — "
                           "check the composition."),
        "nick.caveat": ("Nicknames point to an ingredient, not to a specific pack: the same "
                        "ingredient is sold under different brand names in each country."),
        "footer": ("Information only — not medical advice, and no substitute for a pharmacist."),
    },
    "es": {
        "nav.search": "Buscar", "nav.about": "Acerca de",
        "home.h1": "Descubre qué es realmente un medicamento",
        "home.sub": ("Escribe un nombre comercial, un nombre genérico, un apodo (prueba 两只青蛙) "
                     "o una línea del envase. También funciona en chino, en ancho completo y en "
                     "cirílico; puedes incluir la dosis — p. ej. Lipitor 20mg, 泰诺, СОРТИС."),
        "home.ph": "Nombre comercial / genérico / apodo / una línea del envase",
        "home.all": "Todos los países", "home.us": "Estados Unidos",
        "home.gb": "Reino Unido", "home.cn": "China", "home.es": "España",
        "home.mx": "México", "home.au": "Australia",
        "home.coverage": ("Un resultado vacío no significa que el medicamento no exista. "
                          "Cobertura:"),
        "home.loading": "Cargando el índice…",
        "res.matched": "nombres encontrados", "res.none": "Sin resultados",
        "res.brands": "nombres comerciales encontrados",
        "res.notin": "No incluido en este país",
        "res.caveat": "un resultado vacío no significa que el medicamento no exista",
        "card.packs": "envases",
        "col.ing": "Principio activo", "col.dose": "Dosis",
        "col.brand": "Marca", "col.mah": "Fabricante",
        "same.ing": "Mismo principio activo, otros productos",
        "same.note": "Buscaste una marca: esto es lo demás que contiene el mismo principio activo.",
        "badge.severe": "Mismo nombre, otro medicamento",
        "badge.warning": "Liberación diferente",
        "fam.title": "La misma marca en otros mercados",
        "fam.warn": "Misma marca, otro medicamento",
        "drug.brand": "Marca", "drug.strength": "Concentración", "drug.nostrength": "no publicado",
        "drug.release": "Liberación", "drug.status": "Estado",
        "drug.records": "registros", "drug.showing": "mostrando 40 de",
        "drug.sid": "ID de sustancia",
        "drug.notice": ("Un mismo principio activo puede tener nombres comerciales totalmente "
                        "distintos según el país, y un mismo nombre puede corresponder a otro "
                        "principio activo. Listado por país — no son intercambiables."),
        "drug.empty": "Todavía no hay productos registrados.",
        "name.countries": "Países", "name.form": "Forma",
        "name.strength": "Concentración", "name.release": "Liberación",
        "name.also": "También escrito como", "name.found": "Presente en",
        "name.empty": "Sin registros",
        "name.severe": ("Este nombre comercial corresponde a principios activos distintos "
                        "según el país o la variante. Comprueba la composición; nunca trates "
                        "los nombres como equivalentes."),
        "name.warning": ("Mismo nombre, pero liberación inmediata frente a modificada — "
                         "no son intercambiables."),
        "nick.hit": "Apodo",
        "nick.slang": "apodo de internet", "nick.legacy": "nombre antiguo",
        "nick.translit": "nombre antiguo transliterado", "nick.abbrev": "abreviatura",
        "nick.misnomer": "denominación errónea habitual",
        "nick.ambiguous": ("Este apodo puede corresponder a más de un principio activo — "
                           "comprueba la composición."),
        "nick.caveat": ("Los apodos señalan un principio activo, no un envase concreto: el mismo "
                        "principio se vende con marcas distintas en cada país."),
        "footer": ("Solo información — no es consejo médico ni sustituye a un farmacéutico."),
    },
    "zh": {
        "nav.search": "检索", "nav.about": "关于",
        "home.h1": "查一个药名，看它在各国是什么",
        "home.sub": ("商品名、通用名、俗称都能搜（比如「两只青蛙」）；支持中英文、全角、"
                     "西里尔字母，也可以连剂量一起输入，例如 Lipitor 20mg、泰诺、СОРТИС。"),
        "home.ph": "商品名 / 通用名 / 俗称 / 包装上的一行字",
        "home.all": "全部国家", "home.us": "美国",
        "home.gb": "英国", "home.cn": "中国", "home.es": "西班牙",
        "home.mx": "墨西哥", "home.au": "澳大利亚",
        "home.coverage": "查不到不代表这个药不存在。当前覆盖：",
        "home.loading": "正在加载索引…",
        "res.matched": "个名字命中", "res.none": "没有匹配的名字",
        "res.brands": "个商品名命中",
        "res.notin": "所选国家没有收录这个名字",
        "res.caveat": "查不到不代表这个药不存在",
        "card.packs": "个包装",
        "col.ing": "成分", "col.dose": "剂量",
        "col.brand": "品牌", "col.mah": "厂家",
        "same.ing": "同成分的其他商品",
        "same.note": "你搜的是商品名 —— 下面是同一活性成分的其他商品。",
        "badge.severe": "同名不同药",
        "badge.warning": "释放机制不同",
        "fam.title": "同一品牌在其他市场的写法",
        "fam.warn": "同名不同药",
        "drug.brand": "商品名", "drug.strength": "规格", "drug.nostrength": "未公开",
        "drug.release": "释放", "drug.status": "状态",
        "drug.records": "条记录", "drug.showing": "仅显示前 40 条，共",
        "drug.sid": "规范成分",
        "drug.notice": ("同一成分在不同国家可能用完全不同的商品名；同名也可能指向不同成分。"
                        "下方按国家列出，不代表可以互换。"),
        "drug.empty": "暂无已收录产品。",
        "name.countries": "国家", "name.form": "剂型",
        "name.strength": "规格", "name.release": "释放",
        "name.also": "写法", "name.found": "覆盖",
        "name.empty": "无记录",
        "name.severe": ("这个商品名在不同国家或不同变体下指向不同活性成分，"
                        "选药前必须核对成分，不能按名字等同。"),
        "name.warning": "同名产品存在缓释/速释差异，不能直接互换。",
        "nick.hit": "俗称命中",
        "nick.slang": "网络俗称", "nick.legacy": "旧名",
        "nick.translit": "音译旧名", "nick.abbrev": "简称",
        "nick.misnomer": "常见误称",
        "nick.ambiguous": "这个叫法可能对应不止一个成分，请按成分核对。",
        "nick.caveat": "俗称指向成分，不指向某个包装；同一成分在各国的商品名不同。",
        "footer": "本站只做标识对应，不构成用药建议，不能替代医师或药师。",
    },
}

LANGS = [("en", "EN", ""), ("es", "ES", "es/"), ("zh", "中文", "zh/")]

CSS = """
:root{--bg:#fbfbf9;--fg:#1f2328;--muted:#646b73;--line:#e3e1da;--card:#fff;
--accent:#0b6b53;--warn:#b4471f;--warnbg:#fdf1ec;--sev:#a01b1b;--sevbg:#fdecec}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);min-height:100vh;
display:flex;flex-direction:column;
font:16px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{border-bottom:1px solid var(--line);background:#fff}
.wrap{max-width:920px;margin:0 auto;padding:0 20px}
header .wrap{display:flex;align-items:center;gap:16px;height:60px}
.logo{font-weight:700;font-size:16px;color:var(--fg)}
.logo-zh{font-weight:400;font-size:13px;color:var(--muted);margin-left:8px}
.langs{margin-left:6px;font-size:13px}
.langs a{color:var(--muted);padding:1px 5px;border-radius:5px}
.langs a.on{background:var(--accent);color:#fff}
nav{display:flex;gap:14px;font-size:14px}
main{padding:28px 0 60px;flex:1}
h1{font-size:24px;margin:0 0 6px}h2{font-size:18px;margin:28px 0 10px}
.sub{color:var(--muted);font-size:14px;margin:0 0 18px}
#q{width:100%;padding:14px 16px;font-size:17px;border:1px solid var(--line);
border-radius:10px;background:#fff}
.row{display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap}
select,button{padding:8px 12px;border:1px solid var(--line);border-radius:8px;
background:#fff;font-size:14px}
button{cursor:pointer;background:var(--accent);color:#fff;border-color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin:10px 0}
.card h3{margin:0 0 4px;font-size:16px}
.card .meta{color:var(--muted);font-size:13px}
.tag{display:inline-block;font-size:12px;padding:1px 7px;border-radius:999px;
border:1px solid var(--line);margin-left:6px;color:var(--muted)}
.tag.cn{color:#8a4b00;border-color:#e8c9a6}
.tag.gb{color:#1f4f8a;border-color:#b9cde6}
.tag.us{color:#0b6b53;border-color:#a9d3c5}
.tag.es{color:#8a2c1f;border-color:#e6bdb4}
.tag.au{color:#6b3b0b;border-color:#e0c9a6}
.badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:6px;
margin-left:8px}
.badge.sev{background:var(--sevbg);color:var(--sev);border:1px solid #f0c4c4}
.badge.warn{background:var(--warnbg);color:var(--warn);border:1px solid #f0d3c4}
.notice{background:var(--warnbg);border:1px solid #f0d3c4;border-radius:10px;
padding:12px 14px;font-size:14px;margin:14px 0}
.notice.nick{background:#f1f8f4;border-color:#cfe6da}
.notice.nick .nick-head{font-size:15px}
.notice.nick .nick-head b{font-size:17px}
.notice.nick .sub{margin:6px 0 0}
.notice.nick .sub a{white-space:nowrap}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:13px}
table.res{margin-top:12px;background:#fff;border:1px solid var(--line);
border-radius:12px;overflow:hidden}
table.res th{background:#faf9f6;font-size:12px;letter-spacing:.02em}
table.res td{vertical-align:top}
table.res tbody tr:hover{background:#fcfcfa}
.c-ing{font-weight:600;width:26%}
.c-dose{width:14%;white-space:nowrap;font-variant-numeric:tabular-nums}
.c-brand{width:38%}
.c-mah{width:22%;color:var(--muted);font-size:13px}
footer{border-top:1px solid var(--line);color:var(--muted);font-size:13px;
padding:18px 0 40px;background:#fff}
kbd{background:#eee;padding:1px 5px;border-radius:4px;font-size:13px}
.empty{color:var(--muted);padding:20px 0}
"""

APP_JS = r"""
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
  const [nameQ, st] = splitDose(q);
  const nq = norm(nameQ);
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

  out.innerHTML = nickHTML + warnHTML + `<table class="res"><thead><tr>
      <th>${T2('col.ing')}</th><th>${T2('col.dose')}</th>
      <th>${T2('col.brand')}</th><th>${T2('col.mah')}</th>
    </tr></thead><tbody>${capped.map(rowHTML).join('')}</tbody></table>` + sameHTML + extraHTML;
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
"""


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def key_file(key: str) -> str:
    """文件名尽量保留可读性（含中文），只替换路径非法字符。

    NHSA 的 CSV 里混进了控制字符（例如「糠酸莫米松乳膏\\x02」），
    不剥掉会让 Windows 直接抛 OSError，整个建站中断。
    """
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", key or "")
    s = re.sub(r'[\\/:*?"<>|\s]+', "-", cleaned.strip()).strip("-.")
    if len(s) > 80:
        s = s[:60] + "-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
    if not s:
        s = "k-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:10]
    return s + ".html"


def page(title: str, body: str, prefix: str = "", lang: str = "en",
         alternates: bool = False) -> str:
    sw = "".join(
        f'<a data-lang="{code}" href="?lang={code}">{label}</a>' for code, label, _ in LANGS
    )
    alt = ""
    if alternates:
        alt = ("\n".join(
            f'<link rel="alternate" hreflang="{code}" href="/{path}">'
            for code, _l, path in LANGS
        ) + '\n<link rel="alternate" hreflang="x-default" href="/">')
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · Medicine Brand Cross-Reference</title>{alt}
<link rel="stylesheet" href="{prefix}assets/style.css">
<script src="{prefix}assets/i18n.js"></script></head>
<body>
<header><div class="wrap">
  <a class="logo" href="{prefix}index.html">Medicine Brand Cross-Reference
    <span class="logo-zh">药品商品名跨国定位</span></a>
  <nav><a href="{prefix}index.html" data-i18n="nav.search">Search</a>
    <a href="{prefix}about.html" data-i18n="nav.about">About</a>
    <span class="langs">{sw}</span></nav>
</div></header>
<main><div class="wrap">{body}</div></main>
<footer><div class="wrap">
  <span data-i18n="footer">{esc(I18N['en']['footer'])}</span>
</div></footer>
<script src="{prefix}assets/i18n.js"></script>
</body></html>"""


def load_index(db: sqlite3.Connection):
    """构建检索索引：只收有品牌名的 key。全量一次查询，避免 N+1。"""
    coll = {r[0]: r[1] for r in db.execute("SELECT key_id, level FROM collision")}
    displays: dict[str, str] = {}
    for key_id, raw in db.execute(
        "SELECT key_id, raw FROM name_variant ORDER BY key_id, v_id"
    ):
        displays.setdefault(key_id, raw)

    agg: dict[str, dict] = {}
    for (key_id, pid, country, form_base, dosage_form, sv, su,
         inn_en, sid, mah, ntype) in db.execute(
        """SELECT pn.key_id, p.product_id, p.country, p.form_base, p.dosage_form,
                  pc.strength_value, pc.strength_unit, s.inn_en, s.substance_id, p.mah,
                  pn.name_type
           FROM product_name pn
           JOIN product p ON p.product_id = pn.product_id
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN substance s ON s.substance_id = v.substance_id
           WHERE pn.name_type IN ('trade', 'inn')"""
    ):
        a = agg.get(key_id)
        if a is None:
            a = agg[key_id] = {"pids": set(), "c": set(), "subs": [], "s": [],
                               "f": [], "v": sid, "mah": {}, "trade": False,
                               "sids": set()}
        if ntype == "trade":
            a["trade"] = True
        a["sids"].add(sid)
        a["pids"].add(pid)
        a["c"].add(country)
        if inn_en not in a["subs"]:
            a["subs"].append(inn_en)
        if sv is not None:
            st = f"{sv:g} {su or ''}".strip()
            if st not in a["s"]:
                a["s"].append(st)
        f = form_base or dosage_form
        if f and f not in a["f"]:
            a["f"].append(f)
        if mah:
            a["mah"][mah] = a["mah"].get(mah, 0) + 1

    entries = []
    fam = {}
    for key_id, label, note in db.execute(
        "SELECT nf.key_id, bf.label, bf.note FROM name_family nf"
        " JOIN brand_family bf ON bf.family_id = nf.family_id"
    ):
        fam[key_id] = (label, note)
    for key_id, a in agg.items():
        n = len(a["pids"])
        level = coll.get(key_id, "info")
        # 只有这些名字值得单独成页：有碰撞的、或包装数够多的。
        # 其余名字仍能被搜到，卡片直接链到成分页——不为只有一个包装的冷门名字生成几万张页。
        # 通用名照样能搜到，但只有「有品牌名」或碰撞/多包装的名字才单独成页，
        # 否则光中国就会多出上万张价值很低的页面。
        worth_page = (a["trade"] or level == "warning") and (
            level == "warning" or (level == "severe" and n >= 2) or n >= 3)
        entry = {
            "k": key_id,
            "d": displays.get(key_id, key_id),
            "c": sorted(a["c"]),
            "x": " + ".join(a["subs"][:6]),
            "s": a["s"][:6],
            "f": a["f"][0] if a["f"] else "",
            "l": level,
            "n": n,
            "v": a["v"],
            "vs": sorted(a["sids"]) if len(a["sids"]) > 1 else None,
            "u": key_file(key_id) if worth_page else "",
            "g": fam[key_id][0] if key_id in fam else "",
            "gn": fam[key_id][1] if key_id in fam else "",
            "m": (max(a["mah"].items(), key=lambda kv: kv[1])[0]
                  if a["mah"] else ""),
            "mn": len(a["mah"]),
        }
        entries.append(entry)
    entries.sort(key=lambda e: -e["n"])
    return entries


def load_aliases(db: sqlite3.Connection) -> list[dict]:
    """俗称索引：单独一份 aliases.json。

    不塞进商品名索引，因为昵称属于「成分」，不属于某个名字键——塞进去会让
    「两只青蛙」变成一张挂着几千个包装的商品名。
    """
    counts: dict[str, tuple[int, set[str]]] = {}
    for sid, n, countries in db.execute(
        """SELECT v.substance_id, COUNT(DISTINCT p.product_id),
                  GROUP_CONCAT(DISTINCT p.country)
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           WHERE p.status = 'active'
           GROUP BY v.substance_id"""
    ):
        counts[sid] = (n, set((countries or "").split(",")))
    out = []
    for alias, norm, sid, zh, kind, note, source, inn_en in db.execute(
        """SELECT n.alias, n.alias_norm, n.substance_id, n.label_zh, n.kind,
                  n.note, n.source, s.inn_en
           FROM nickname n JOIN substance s ON s.substance_id = n.substance_id
           ORDER BY n.nickname_id"""
    ):
        n_prod, countries = counts.get(sid, (0, set()))
        out.append({
            "a": alias,
            "n": norm,
            "v": sid,
            "i": inn_en,
            "x": inn_en + (f" · {zh}" if zh else ""),
            "k": kind,
            "hint": note or "",
            "src": source or "",
            "c": sorted(countries),
            "np": n_prod,
        })
    return out


def build_drug_pages(db: sqlite3.Connection) -> int:
    # 一次性取全量，按成分分组；逐个成分查询会退化成正表全扫 × 4445 次
    products: dict[str, list] = {}
    for row in db.execute(
        """SELECT v.substance_id, p.country, p.form_base, p.dosage_form, p.release,
                  p.status, pc.strength_value, pc.strength_unit,
                  pc.per_volume_value, pc.per_volume_unit, p.product_id
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id"""
    ):
        products.setdefault(row[0], []).append(row[1:])

    names: dict[str, list[str]] = {}
    for pid, raw in db.execute(
        """SELECT pn.product_id, nv.raw FROM product_name pn
           JOIN name_variant nv ON nv.key_id = pn.key_id
           WHERE pn.name_type = 'trade'"""
    ):
        bucket = names.setdefault(pid, [])
        if raw not in bucket:
            bucket.append(raw)

    subs = db.execute("SELECT substance_id, inn_en, inn_zh, atc FROM substance").fetchall()
    nicknames: dict[str, list[str]] = {}
    for sid, alias in db.execute(
        "SELECT substance_id, alias FROM nickname ORDER BY nickname_id"
    ):
        nicknames.setdefault(sid, []).append(alias)
    made = 0
    (OUT / "drug").mkdir(parents=True, exist_ok=True)
    for sid, inn_en, inn_zh, atc in subs:
        rows = products.get(sid)
        if not rows:
            continue

        brands = defaultdict(lambda: defaultdict(int))
        by_country = defaultdict(list)
        for (country, fb, df, rel, status, sv, su, pv, pu, pid) in rows:
            b = names.get(pid, [])
            for x in b:
                brands[country][x] += 1
            st = f"{sv:g} {su}" if sv is not None else ""
            if pv:
                st += f"/{pv:g} {pu}"
            by_country[country].append((st.strip(), rel, status, b[0] if b else ""))

        blocks = []
        for country in ("US", "GB", "CN", "ES", "MX", "AU"):
            if country not in by_country:
                continue
            uniq = {}
            for st, rel, status, brand in by_country[country]:
                k = (brand, st, rel)
                if k not in uniq:
                    uniq[k] = (brand, st, rel, status)
            ordered = sorted(uniq.values(),
                             key=lambda t: (t[0] == "", t[0].lower(), _sort_strength(t[1])))
            lis = []
            for brand, st, rel, status in ordered[:40]:
                name = esc(brand) if brand else '<span class="meta">（无商品名）</span>'
                st_html = esc(st) if st else (
                    '<span class="meta" data-i18n="drug.nostrength">not disclosed</span>')
                flag = {
                    "withdrawn": " <em>(withdrawn 已撤市)</em>",
                    "discontinued": " <em>(expired 有效期已过)</em>",
                    "unknown": " <em>(validity unknown 有效期待确认)</em>",
                }.get(status, "")
                lis.append(f"<tr><td>{name}</td><td>{st_html}</td>"
                           f"<td>{esc(rel) if rel != 'none' else '—'}</td>"
                           f"<td>{esc(status)}{flag}</td></tr>")
            more = (f'<p class="sub"><span data-i18n="drug.showing">showing first 40 of</span> '
                    f'{len(ordered)}</p>' if len(ordered) > 40 else "")
            blocks.append(
                f"<h2>{country} <span class='meta'>({len(ordered)} "
                f"<span data-i18n='drug.records'>records</span>)</span></h2>"
                f"<table><tr><th data-i18n='drug.brand'>Brand</th>"
                f"<th data-i18n='drug.strength'>Strength</th>"
                f"<th data-i18n='drug.release'>Release</th>"
                f"<th data-i18n='drug.status'>Status</th></tr>"
                + "".join(lis) + "</table>" + more
            )
        nick_line = ""
        if sid in nicknames:
            also = "、".join(esc(x) for x in nicknames[sid])
            nick_line = (f'<p class="sub">Also called 也叫：{also} '
                         f'<span class="tag">nickname 俗称</span></p>')
        body = f"""<h1>{esc(inn_zh) or esc(inn_en)} <span class="meta">{esc(inn_en)}</span></h1>
<p class="sub">ATC {esc(atc) or '—'} · <span data-i18n="drug.sid">Substance ID</span>
<code>{esc(sid)}</code></p>
{nick_line}
<div class="notice" data-i18n="drug.notice">The same ingredient can carry completely different
brand names in different countries, and the same name can point to a different ingredient.
Listed by country — not interchangeable.</div>
{''.join(blocks) if blocks else '<p class="empty" data-i18n="drug.empty">No products recorded yet.</p>'}"""
        (OUT / "drug").mkdir(parents=True, exist_ok=True)
        (OUT / "drug" / f"{sid}.html").write_text(page(f"{inn_en}", body, "../"), encoding="utf-8")
        made += 1
    return made


def collect_name_data(db: sqlite3.Connection) -> dict:
    """一次性把名字页需要的全部数据取到内存，避免上万次逐条查询。"""
    data: dict[str, dict] = {}
    for (key_id, inn_en, sid, country, form_base, dosage_form, rel,
         sv, su) in db.execute(
        """SELECT pn.key_id, s.inn_en, s.substance_id, p.country, p.form_base,
                  p.dosage_form, p.release, pc.strength_value, pc.strength_unit
           FROM product_name pn
           JOIN product p ON p.product_id = pn.product_id
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN substance s ON s.substance_id = v.substance_id"""
    ):
        d = data.setdefault(key_id, {"subs": {}, "countries": set()})
        d["countries"].add(country)
        s = d["subs"].setdefault(
            sid, {"inn": inn_en, "country": set(), "s": set(), "f": set(), "rel": set()})
        s["country"].add(country)
        st = f"{sv:g} {su or ''}".strip() if sv is not None else ""
        if st:
            s["s"].add(st)
        s["f"].add(form_base or dosage_form)
        s["rel"].add(rel)
    return data


def build_name_pages(db: sqlite3.Connection, entries, data: dict,
                     families: dict | None = None, displays: dict | None = None) -> int:
    families = families or {}
    displays = displays or {e["k"]: e["d"] for e in entries}
    made = 0
    (OUT / "name").mkdir(parents=True, exist_ok=True)
    variants: dict[str, list[str]] = {}
    for key_id, raw in db.execute("SELECT key_id, raw FROM name_variant ORDER BY v_id"):
        variants.setdefault(key_id, []).append(raw)

    for e in entries:
        if not e["u"]:
            continue
        d = data.get(e["k"])
        if not d:
            continue
        level = e["l"]
        banner = {
            "severe": '<div class="notice"><b data-i18n="badge.severe">Same name, different drug</b>'
                      '<span data-i18n="name.severe"> — this brand name points to different '
                      'active ingredients. Check the composition.</span></div>',
            "warning": '<div class="notice"><b data-i18n="badge.warning">Different release</b>'
                       '<span data-i18n="name.warning"> — not interchangeable.</span></div>',
        }.get(level, "")

        cards = []
        for sid, g in d["subs"].items():
            rel = g["rel"] - {"none"}
            cards.append(
                f"""<div class="card"><h3><a href="../drug/{sid}.html">{esc(g['inn'])}</a></h3>
<div class="meta"><span data-i18n="name.countries">Countries</span>:
{esc('、'.join(sorted(g['country'])))} ·
<span data-i18n="name.form">Form</span>: {esc('、'.join(sorted(g['f'])))} ·
<span data-i18n="name.strength">Strength</span>:
{esc('、'.join(sorted(g['s'], key=_sort_strength)) or '—')}
{f" · <span data-i18n='name.release'>Release</span>: {esc('、'.join(sorted(rel)))}" if rel else ''}</div></div>"""
            )
        body = f"""<h1>{esc(e['d'])}</h1>
<p class="sub"><span data-i18n="name.also">Also written as</span>:
{esc('、'.join(variants.get(e['k'], [])[:6]))} ·
<span data-i18n="name.found">Found in</span>: {esc('、'.join(sorted(d['countries'])))}</p>
{banner}{''.join(cards) if cards else '<p class="empty" data-i18n="name.empty">No records</p>'}{_family_block(e, families, displays, variants)}"""
        (OUT / "name" / e["u"]).write_text(page(e["d"], body, "../"), encoding="utf-8")
        made += 1
    return made


def _family_block(e, families, displays, variants) -> str:
    """同一品牌在其他市场的写法——这是跨语言碰撞唯一能落地的地方。"""
    fam = families.get(e["k"])
    if not fam:
        return ""
    fam_id, label, note = fam["id"], fam["label"], fam["note"]
    siblings = [k for k in fam["members"] if k != e["k"]]
    if not siblings:
        return ""
    items = []
    for k in siblings:
        siblings_names = "、".join(variants.get(k, [])[:2])
        fname = key_file(k)
        items.append(
            f'<li><a href="{fname}">{esc(displays.get(k, siblings_names))}</a>'
            f'<span class="tag">{esc(k)}</span></li>')
    return (f'<h2 data-i18n="fam.title">The same brand in other markets</h2>'
            f'<div class="notice">{esc(note or "")}</div>'
            f'<ul class="sub">{"".join(items)}</ul>')


def _sort_strength(text: str) -> float:
    m = re.match(r"([\d.]+)", text)
    return float(m.group(1)) if m else 0.0


def build_index_page(entries, stats, coverage) -> None:
    """三份落地页：/ 、/es/ 、/zh/。内容相同，语言由脚本按路径/参数决定。"""
    covline = ", ".join(f"{r['country']} {r['n_products']:,}" for r in coverage)
    body = f"""<h1 data-i18n="home.h1">Find out what a medicine really is</h1>
<p class="sub" data-i18n="home.sub">Type a brand name, a generic name, a nickname, or a line from the pack.</p>
<input id="q" data-ph="home.ph" placeholder="Brand name / generic name / nickname / a line from the pack" autocomplete="off">
<div class="row">
  <select id="country"><option value="" data-i18n="home.all">All countries</option>
    <option value="US" data-i18n="home.us">United States</option>
    <option value="GB" data-i18n="home.gb">United Kingdom</option>
    <option value="CN" data-i18n="home.cn">China</option>
    <option value="ES" data-i18n="home.es">Spain</option>
    <option value="MX" data-i18n="home.mx">Mexico</option>
    <option value="AU" data-i18n="home.au">Australia</option></select>
  <button data-q="泰诺">泰诺</button>
  <button data-q="两只青蛙">两只青蛙</button>
  <button data-q="Lipitor 20mg">Lipitor 20mg</button>
  <button data-q="Benadryl">Benadryl</button>
  <button data-q="Gaviscon">Gaviscon</button>
</div>
<p class="sub" id="meta" style="margin-top:14px"></p>
<div id="out"></div>
<div class="notice"><span data-i18n="home.coverage">An empty result does not mean the medicine
does not exist. Coverage:</span> {covline}.</div>
<script src="{{prefix}}assets/app.js"></script>"""
    for code, _label, path in LANGS:
        prefix = "../" if path else ""
        html = page("Medicine Brand Cross-Reference", body.replace("{prefix}", prefix),
                    prefix=prefix, lang=code, alternates=True)
        target = OUT / (path + "index.html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")


def build_about(stats, coverage) -> None:
    cov = "".join(
        f"<tr><td>{esc(r['country'])}</td><td>{r['n_products']:,}</td>"
        f"<td>{esc(r['last_synced'])}</td></tr>" for r in coverage)
    body = f"""<h1>About 关于本站</h1>
<p class="sub"><b>One job:</b> turn a brand name into the actual substance, and say how sure
we are. 这里只有一件事：把商品名定位到成分，并说明它到底有多可信。</p>

<h2>Three rules 三条底线</h2>
<ol>
<li><b>A brand name is not a primary key. 商品名不是主键。</b>
Every query returns a set of candidates; identity is pinned by country × form × strength ×
active ingredient. 唯一性由「国家 × 剂型 × 规格 × 活性成分」锁定。</li>
<li><b>Collisions are derived, not annotated. 碰撞自动推导。</b>
When one name hangs off different ingredients, the site flags
“same name, different drug” automatically.</li>
<li><b>No dosing advice. 不给用药建议。</b>
Identification and “not interchangeable” warnings only — no dose conversion, no substitution
recommendations.</li>
</ol>

<h2>Nicknames, old names, internet slang 俗称、旧名与网络别名</h2>
<p>“两只青蛙” is not a brand name and is never stored as one: it points to an ingredient,
metformin (二甲双胍). Nicknames are a separate, hand-maintained table — searchable, but kept out
of the brand-name tables on purpose.</p>
<ul>
<li>When a nickname matches, the page says so (<i>internet nickname / older name</i>) and then
lists that ingredient’s brand names. It is never presented as a name printed on a pack.
<br>命中时先标注「网络俗称 / 旧名」，再列该成分的商品名；不把它说成包装上的名字。</li>
<li>Every entry carries a source (user-provided / common usage / older pharmacopoeial name).
<br>每条都写出处；没有出处的叫法不收。</li>
<li>Nicknames never enter collision detection and never get a “same name” page — a nickname is
not an identity, the ingredient is.
<br>不参与同名碰撞推导，也不生成同名页——昵称不是身份，成分才是。</li>
<li>To add one, edit <code>data/seed_nicknames.py</code> and rebuild. It is curated by hand,
not scraped.
<br>要补一条：改 <code>data/seed_nicknames.py</code> 再重建；人工维护，不自动抓。</li>
</ul>
<p class="sub">This layer started as a joke: the <i>guā</i> in 二甲双胍 sounds like a frog’s
<i>guā</i> (呱), so it got called “two frogs”. The point of the site is to connect exactly this
kind of name back to the substance.<br>
这一层最初来自一个笑话：二甲双胍的「胍」和青蛙的「呱」同音，于是被叫成「两只青蛙」。这个站想
做的，就是把这类叫法接回它真正的成分。</p>

<h2>Sources and coverage 数据来源与覆盖</h2>
<table><tr><th>Market 市场</th><th>Products 已收录</th><th>Synced 同步</th></tr>{cov}</table>
<p class="sub"><b>US 美国</b>: openFDA NDC Directory (US Government public data;
<code>brand_name</code> + <code>active_ingredients</code>).<br>
<b>UK 英国</b>: NHSBSA dm+d, Release 10.2.0, under the Open Government Licence v3.0 —
attribution: <i>Contains public sector information licensed under the Open Government Licence
v3.0.</i> Appliance/device entries were filtered out.<br>
<b>Spain 西班牙</b>: AEMPS CIMA (Centro de Información online de Medicamentos),
<code>nregistro</code> + <code>vtm</code> + <code>dosis</code> + <code>atcs</code>; Spanish
generic names carry the manufacturer (e.g. “Omeprazol Cinfa”), which is how the pack is
labelled. 西班牙按 VTM 归成分，西语名与英文 INN 共用同一 substance_id。<br>
<b>Mexico 墨西哥</b>: COFEPRIS «Registros Sanitarios de Medicamentos Alopáticos Expedidos»,
26 annual PDFs 2001–2026, plus the <i>prórrogas</i> (renewal) lists that carry 1,040 older
registrations granted before 2001 — 10,878 records in total. Status is derived, not given:
<i>revocados / cancelados</i> → withdrawn; an expiry date in the past → discontinued; no expiry
column at all (the 2001–2010 files) → <b>unknown</b>, we do not pretend either way. The lists
carry <b>no strength column</b>: strengths are back-filled from the ISSSTE procurement catalogue
and the PROFECO price survey (both CC BY 4.0), only where the value is unambiguous — so a blank
strength in Mexico is expected, not a bug.<br>
<b>Australia 澳洲</b>: PBS Schedule API v3 (Department of Health), schedule 4751 effective
1 October 2026 — 15,073 item × brand rows, 5,452 products after collapsing the same
brand/strength/pack that appears under several restriction codes. The API's copyright
notice explicitly permits use and redistribution as long as the statement is retained:
<i>Copyright (c) 2024 Department of Health, Commonwealth of Australia.</i> PBS lists only
<b>subsidised</b> medicines, so OTC brands (Panadol, Nurofen, Gaviscon) are absent by
design; the full register (TGA ARTG) publishes no bulk extract and blocks automated access.
Stoma/incontinence appliances (program R1) are filtered out.
<br>澳洲走 PBS 官方 API，不是抓网页：PBS 网页的版权只允许个人参考，API 才明确允许再发布。
覆盖面只到「享受补贴的药品」，所以 OTC 品牌查不到；TGA 的 ARTG 才是全量在册，但没有批量文件。
R1 造口/失禁用品（敷料、绷带）已按 dm+d 滤器械的同一逻辑排除。<br>
<b>China 中国</b>: 国家医保局「医保药品分类与代码数据库」, 2024-01-05 snapshot — 234,370
catalogue rows (the same batch is a 19,531-page PDF), of which the 135,667 chemical-drug rows
load as 135,348 products. Chinese generic names are mapped onto the same English
<code>substance_id</code>s the other markets use, through a hand-built 中文→INN table (~1,080
entries) plus an ATC-4 lookup that only fires when that ATC class is unambiguous; the residue
sits on China-only substances that a later pass can map. 中成药 (98,703 rows, 42 real brand
names) is excluded on purpose. 商品名 exists for only 13% of rows, so most Chinese products are
reachable by generic name rather than by brand.</p>

<h2>Why “same name, different drug” happens 为什么会有同名不同药</h2>
<p class="sub">The same trademark is held by different companies in different markets, and the
formula can differ completely. Verified examples: US <b>Tylenol</b> is single-ingredient
acetaminophen 500 mg, while China <b>泰诺</b> is a four-ingredient cold medicine and the
single-ingredient product is <b>泰诺林</b>; US <b>Benadryl</b> is diphenhydramine, UK
<b>Benadryl</b> is acrivastine; US <b>Gaviscon</b> is an aluminium/magnesium antacid, UK
Gaviscon is an alginate raft.</p>

<h2>Known gaps 已知缺口</h2>
<ul class="sub">
<li>China now carries 135,348 chemical-drug registrations, but ~9% of them resolve only to a
China-only substance (no English INN yet), and China's ATC is stored at level 4 — these
products carry ATC-4, not ATC-5. 中成药 is not loaded.<br>
中国已入库 13.5 万条化学药，但约 9% 只能落到 CN 专属成分（暂无英文 INN），
ATC 只到第 4 级；中成药未收录。</li>
<li>Strength equivalence stops at level D1 (same salt form). Salt-base conversion (D2) and
bioavailability judgement (D3) are not implemented.<br>
剂量只做到同型对应，盐基折算与生物利用度判定未做。</li>
<li>Mexico has no strength in the regulator's bulk lists; only 29% of products could be
back-filled from public catalogues, and no brand-level bulk source exists.
<br>墨西哥官方清单没有浓度列，只有 29% 的产品能从公开目录回填。</li>
<li>The Mexican files only list registrations issued from 2001 onward; the renewal lists recover
1,040 older ones, but anything never renewed is still missing.
<br>墨西哥清单只含 2001 年起新批的注册，续期清单补回 1,040 条老药，其余仍缺。</li>
<li>ATC codes are mostly missing.<br>ATC 编码大部分缺失。</li>
</ul>
<p class="sub">Stats 统计：{stats['products']:,} products · {stats['substances']:,} substances ·
{stats['keys']:,} name keys · {stats['nickname']:,} nicknames ·
{stats['severe']:,} names flagged “same name, different drug”.</p>"""
    (OUT / "about.html").write_text(page("About", body), encoding="utf-8")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    (OUT / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    i18n_js = (
        "window.I18N=" + json.dumps(I18N, ensure_ascii=False) + ";\n" + r"""
(function(){
  var D = window.I18N, seg = location.pathname.split('/').filter(Boolean);
  function pick(){
    var q = new URLSearchParams(location.search).get('lang');
    if(q && D[q]){ try{localStorage.setItem('lang',q);}catch(e){} return q; }
    var first = seg[0] || '';
    if(D[first]) return first;
    try{ var s = localStorage.getItem('lang'); if(s && D[s]) return s; }catch(e){}
    var n = (navigator.language || 'en').slice(0,2);
    return D[n] ? n : 'en';
  }
  window.LANG = pick();
  window.T = function(k){ return (D[window.LANG] && D[window.LANG][k]) || D.en[k] || k; };
  function apply(){
    document.documentElement.lang = window.LANG;
    document.querySelectorAll('[data-i18n]').forEach(function(el){ el.textContent = window.T(el.dataset.i18n); });
    document.querySelectorAll('[data-ph]').forEach(function(el){ el.placeholder = window.T(el.dataset.ph); });
    document.querySelectorAll('.langs a').forEach(function(a){
      a.classList.toggle('on', a.dataset.lang === window.LANG);
    });
  }
  window.setLang = function(l){ try{localStorage.setItem('lang',l);}catch(e){}
    location.search = '?lang=' + encodeURIComponent(l); };
  if(document.readyState === 'loading'){ document.addEventListener('DOMContentLoaded', apply); }
  else { apply(); }
  window.addEventListener('load', apply);
})();
"""
    )
    (OUT / "assets" / "i18n.js").write_text(i18n_js, encoding="utf-8")
    (OUT / "assets" / "app.js").write_text(APP_JS, encoding="utf-8")

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    coverage = [dict(r) for r in db.execute("SELECT * FROM coverage ORDER BY country")]
    stats = {
        "products": db.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "substances": db.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
        "keys": db.execute("SELECT COUNT(*) FROM name_key").fetchone()[0],
        "nickname": db.execute("SELECT COUNT(*) FROM nickname").fetchone()[0],
        "severe": db.execute(
            "SELECT COUNT(*) FROM collision WHERE level='severe'").fetchone()[0],
    }

    print("building index ...", flush=True)
    entries = load_index(db)
    (OUT / "data" / "index.json").write_text(
        json.dumps(entries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {len(entries)} keys", flush=True)

    print("building nickname index ...", flush=True)
    aliases = load_aliases(db)
    (OUT / "data" / "aliases.json").write_text(
        json.dumps(aliases, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {len(aliases)} nicknames", flush=True)

    print("building drug pages ...", flush=True)
    n_drug = build_drug_pages(db)
    print("collecting name data ...", flush=True)
    data = collect_name_data(db)
    families: dict[str, dict] = {}
    members: dict[str, list[str]] = defaultdict(list)
    for key_id, fam_id, label, note in db.execute(
        "SELECT nf.key_id, bf.family_id, bf.label, bf.note FROM name_family nf"
        " JOIN brand_family bf ON bf.family_id = nf.family_id"
    ):
        families[key_id] = {"id": fam_id, "label": label, "note": note, "members": []}
        members[fam_id].append(key_id)
    for key_id, fam in families.items():
        fam["members"] = members[fam["id"]]
    displays = {e["k"]: e["d"] for e in entries}
    print("building name pages ...", flush=True)
    n_name = build_name_pages(db, entries, data, families, displays)
    build_index_page(entries, stats, coverage)
    build_about(stats, coverage)

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"\n== done ==")
    print(f"  drug pages : {n_drug}")
    print(f"  name pages : {n_name}")
    print(f"  index.json : {(OUT / 'data' / 'index.json').stat().st_size / 1e6:.1f} MB")
    print(f"  total size : {size / 1e6:.1f} MB")
    print(f"  open       : {OUT / 'index.html'}")
    db.close()


if __name__ == "__main__":
    main()
