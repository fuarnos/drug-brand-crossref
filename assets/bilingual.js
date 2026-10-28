
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
  function initMatrixFilters(){
    document.querySelectorAll('.matwrap table.matrix').forEach(function(table){
      if(table.getAttribute('data-mf-init')) return;
      table.setAttribute('data-mf-init', '1');
      var wrap = table.closest('.matwrap');
      if(!wrap) return;
      var ths = Array.from(table.querySelectorAll('thead th[data-country]'));
      var rows = Array.from(table.querySelectorAll('tbody tr'));
      var countries = ths.map(function(th){ return th.getAttribute('data-country'); });
      var forms = {}, releases = {};
      rows.forEach(function(tr){
        var f = tr.getAttribute('data-form') || '';
        var r = tr.getAttribute('data-release') || '';
        if(f) forms[f] = 1;
        if(r && r !== 'none') releases[r] = 1;
      });
      var T = window.T || function(k){ return k; };
      function opt(v, label){ var o = document.createElement('option'); o.value = v; o.textContent = label; return o; }
      var box = document.createElement('section');
      box.className = 'matrix-filters';
      box.innerHTML = '<div class="mf-head"><span class="mf-title"></span>'
        + '<span class="mf-count" aria-live="polite"></span>'
        + '<button type="button" class="mf-toggle" aria-expanded="false"></button></div>'
        + '<div class="mf-panel"></div>';
      box.querySelector('.mf-title').textContent = T('matrix.filters');
      box.querySelector('.mf-toggle').textContent = T('matrix.mobile_filters');
      var panel = box.querySelector('.mf-panel');
      // 国家多选
      var cf = document.createElement('div'); cf.className = 'mf-field';
      cf.innerHTML = '<span></span><div class="mf-countries"></div>';
      cf.querySelector('span').textContent = T('matrix.country');
      var cbox = cf.querySelector('.mf-countries');
      countries.forEach(function(c){
        var lab = document.createElement('label');
        var cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = true;
        cb.setAttribute('data-mf-country', c);
        lab.appendChild(cb); lab.appendChild(document.createTextNode(' ' + c));
        cbox.appendChild(lab);
      });
      panel.appendChild(cf);
      // 剂型
      var ff = document.createElement('label'); ff.className = 'mf-field';
      ff.innerHTML = '<span></span><select data-mf-form></select>';
      ff.querySelector('span').textContent = T('matrix.form');
      var fsel = ff.querySelector('select');
      fsel.appendChild(opt('', T('matrix.all')));
      Object.keys(forms).sort().forEach(function(f){ fsel.appendChild(opt(f, f)); });
      panel.appendChild(ff);
      // 释放
      var rf = document.createElement('label'); rf.className = 'mf-field';
      rf.innerHTML = '<span></span><select data-mf-rel></select>';
      rf.querySelector('span').textContent = T('matrix.release');
      var rsel = rf.querySelector('select');
      rsel.appendChild(opt('', T('matrix.all')));
      Object.keys(releases).sort().forEach(function(r){ rsel.appendChild(opt(r, r)); });
      panel.appendChild(rf);
      // 规格搜索
      var sf = document.createElement('label'); sf.className = 'mf-field';
      sf.innerHTML = '<span></span><input type="search" data-mf-spec>';
      sf.querySelector('span').textContent = T('matrix.spec_search');
      var sinp = sf.querySelector('input');
      panel.appendChild(sf);
      // 重置
      var resetWrap = document.createElement('div'); resetWrap.className = 'mf-field';
      var reset = document.createElement('button'); reset.type = 'button'; reset.className = 'mf-reset';
      reset.textContent = T('matrix.reset');
      resetWrap.appendChild(reset); panel.appendChild(resetWrap);
      wrap.parentNode.insertBefore(box, wrap);
      var note = document.createElement('p'); note.className = 'sub matrix-sort-note';
      note.textContent = T('matrix.sort_note');
      box.parentNode.insertBefore(note, wrap);
      function current(){
        var cc = Array.from(cbox.querySelectorAll('input[type=checkbox]'));
        var sel = cc.filter(function(cb){ return cb.checked; })
                    .map(function(cb){ return cb.getAttribute('data-mf-country'); });
        return {countries: sel, form: fsel.value, rel: rsel.value,
                spec: sinp.value.trim().toLowerCase(), all: cc.map(function(cb){ return cb.getAttribute('data-mf-country'); })};
      }
      function apply(updateURL){
        var s = current();
        var visible = 0;
        rows.forEach(function(tr){
          var ok = true;
          if(s.form && (tr.getAttribute('data-form') || '') !== s.form) ok = false;
          if(s.rel && (tr.getAttribute('data-release') || '') !== s.rel) ok = false;
          if(s.spec && (tr.getAttribute('data-spec') || '').toLowerCase().indexOf(s.spec) < 0) ok = false;
          tr.style.display = ok ? '' : 'none';
          if(ok) visible++;
        });
        ths.forEach(function(th){
          var c = th.getAttribute('data-country');
          var show = s.countries.indexOf(c) >= 0;
          th.style.display = show ? '' : 'none';
          rows.forEach(function(tr){
            Array.from(tr.children).forEach(function(td){
              if(td.getAttribute('data-country') === c) td.style.display = show ? '' : 'none';
            });
          });
        });
        var cnt = box.querySelector('.mf-count');
        cnt.textContent = T('matrix.showing').replace('{n}', visible).replace('{total}', rows.length);
        if(updateURL){
          try{
            var p = new URLSearchParams(location.search);
            s.form ? p.set('mform', s.form) : p.delete('mform');
            s.rel ? p.set('mrel', s.rel) : p.delete('mrel');
            s.spec ? p.set('mspec', sinp.value.trim()) : p.delete('mspec');
            (s.countries.length === s.all.length) ? p.delete('mcountry') : p.set('mcountry', s.countries.join(','));
            history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p.toString() : '') + location.hash);
          }catch(e){}
        }
      }
      // URL 初值
      try{
        var q = new URLSearchParams(location.search);
        var mc = (q.get('mcountry') || '').split(',').filter(Boolean);
        if(mc.length){
          cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){
            cb.checked = mc.indexOf(cb.getAttribute('data-mf-country')) >= 0;
          });
        }
        if(q.get('mform')) fsel.value = q.get('mform');
        if(q.get('mrel')) rsel.value = q.get('mrel');
        if(q.get('mspec')) sinp.value = q.get('mspec');
      }catch(e){}
      fsel.addEventListener('change', function(){ apply(true); });
      rsel.addEventListener('change', function(){ apply(true); });
      sinp.addEventListener('input', function(){ apply(true); });
      cbox.addEventListener('change', function(){ apply(true); });
      reset.addEventListener('click', function(){
        cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){ cb.checked = true; });
        fsel.value = ''; rsel.value = ''; sinp.value = '';
        apply(true);
      });
      box.querySelector('.mf-toggle').addEventListener('click', function(){
        var open = box.classList.toggle('mf-open');
        this.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      apply(false);
    });
  }
  function start(){
    initNavToggle();
    injectToggle();
    initMatrixFilters();
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
