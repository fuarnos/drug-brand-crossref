
(function(){
  var T = window.T || function(k){ return k; };
  var TERMS = null, SHOW = true, OBS = null, OUT = null;
  try {
    var saved = localStorage.getItem('dsh.showOrig');
    SHOW = (saved === '0') ? false : (saved === '1') ? true : (window.LANG !== 'en');
  } catch(e) { SHOW = (window.LANG !== 'en'); }
  function url(){
    var pre = (typeof window.DSH_PREFIX === 'string') ? window.DSH_PREFIX : '';
    return pre + 'data/terms.json';
  }
  function load(){
    if(TERMS) return Promise.resolve(TERMS);
    return fetch(url()).then(function(r){ return r.json(); }).then(function(d){
      TERMS = d; expose(); return d;
    }).catch(function(){ return null; });
  }
  function expose(){ try { window.BILINGUAL_TERMS = TERMS; } catch(e) {} }
  function srcLabel(s){
    if(!s) return '';
    var k = 'bilingual.source.' + s;
    var v = T(k);
    return (v === k) ? s : v;
  }
  function applyOne(el){
    var sid = el.getAttribute('data-sub-ingredient');
    var orig = el.getAttribute('data-sub-orig');
    if(orig === null || orig === undefined){
      orig = el.textContent || '';
      el.setAttribute('data-sub-orig', orig);
    }
    el.querySelectorAll('.tr-badge,.tr-ver,.tr-orig').forEach(function(n){ n.remove(); });
    var ent = (TERMS && TERMS.sub && TERMS.sub[sid]) || null;
    var tr = ent && ent[window.LANG];
    if(!tr || !tr.n){ el.textContent = orig; return; }
    el.textContent = tr.n;
    var badge = document.createElement('span');
    badge.className = 'tr-badge';
    badge.textContent = srcLabel(tr.s);
    if(tr.u) badge.title = tr.u;
    el.appendChild(badge);
    if(tr.v){
      var ver = document.createElement('span');
      ver.className = 'tr-ver';
      ver.textContent = 'v' + tr.v;
      el.appendChild(ver);
    }
    if(SHOW && orig && orig !== tr.n){
      var o = document.createElement('span');
      o.className = 'tr-orig';
      o.textContent = ' (' + orig + ')';
      el.appendChild(o);
    }
  }
  function renderNames(){
    document.querySelectorAll('.nm[data-n-en]').forEach(function(el){      var en = el.getAttribute('data-n-en') || '';
      var zh = el.getAttribute('data-n-zh') || '';
      var zhh = el.getAttribute('data-n-zhh') || '';
      var es = el.getAttribute('data-n-es') || '';
      var lang = window.LANG || 'en';
      if(lang === 'zh') el.textContent = zh || (en + ' 暂无中文名');
      else if(lang === 'zh-Hant') el.textContent = zhh || (en + ' 暫無中文名');
      else if(lang === 'es') el.textContent = es || en;
      else el.textContent = en;
    });
  }
  window.renderBilingualNames = renderNames;
  function render(){
    if(!TERMS) { renderNames(); return; }
    if(OBS) OBS.disconnect();
    renderNames();
    document.querySelectorAll('[data-sub-ingredient]').forEach(applyOne);
    var note = T('bilingual.brand_note');
    document.querySelectorAll('[data-brand]').forEach(function(el){
      if(note && note.indexOf('bilingual.') !== 0) el.setAttribute('title', note);
    });
    var cb = document.getElementById('bilOrig');
    if(cb) cb.checked = SHOW;
    // task-114：英文副标题在英文界面隐藏（避免重复）
    document.querySelectorAll('.cat-en').forEach(function(el){
      el.style.display = (window.LANG === 'en') ? 'none' : '';
    });
    if(OBS && OUT) OBS.observe(OUT, {childList: true, subtree: true});
  }
  function injectToggle(){
    if(document.getElementById('bilToggle')) return;
    var nav = document.querySelector('header nav');
    if(!nav) return;
    var lab = document.createElement('label');
    lab.id = 'bilToggle';
    lab.className = 'bil-toggle';
    lab.innerHTML = '<input type="checkbox" id="bilOrig"> <span></span>';
    lab.querySelector('span').textContent = T('bilingual.toggle');
    var langs = nav.querySelector('.langs');
    nav.insertBefore(lab, langs || null);
    var cb = lab.querySelector('input');
    cb.checked = SHOW;
    cb.addEventListener('change', function(){
      SHOW = cb.checked;
      try { localStorage.setItem('dsh.showOrig', SHOW ? '1' : '0'); } catch(e) {}
      render();
    });
  }
  function initNavToggle(){
    if(document.getElementById('navToggle')) return;
    var header = document.querySelector('header');
    var nav = header ? header.querySelector('nav') : null;
    if(!header || !nav) return;
    var b = document.createElement('button');
    b.id = 'navToggle';
    b.type = 'button';
    b.className = 'nav-toggle';
    b.setAttribute('aria-label', T('nav.menu'));
    b.setAttribute('aria-expanded', 'false');
    b.textContent = '\u2630';
    var wrap = header.querySelector('.wrap') || header;
    wrap.insertBefore(b, nav);
    b.addEventListener('click', function(){
      var open = header.classList.toggle('nav-open');
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  function start(){
    initNavToggle();
    injectToggle();
    renderNames();
    load().then(render);
    OUT = document.getElementById('out');
    if(OUT && window.MutationObserver){
      OBS = new MutationObserver(function(){ if(TERMS) render(); });
      OBS.observe(OUT, {childList: true, subtree: true});
    }
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
  window.addEventListener('load', render);
  window.applyBilingualTerms = render;
})();
