
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
      TERMS = d; return d;
    }).catch(function(){ return null; });
  }
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
  function render(){
    if(!TERMS) return;
    if(OBS) OBS.disconnect();
    document.querySelectorAll('[data-sub-ingredient]').forEach(applyOne);
    var note = T('bilingual.brand_note');
    document.querySelectorAll('[data-brand]').forEach(function(el){
      if(note && note.indexOf('bilingual.') !== 0) el.setAttribute('title', note);
    });
    var cb = document.getElementById('bilOrig');
    if(cb) cb.checked = SHOW;
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
  function start(){
    injectToggle();
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
