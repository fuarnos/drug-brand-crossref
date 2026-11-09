
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
    var inH1 = el.closest && el.closest('h1');
    var srcEl = inH1 ? document.querySelector('[data-sub-src="' + sid + '"]') : null;
    var ent = (TERMS && TERMS.sub && TERMS.sub[sid]) || null;
    var tr = ent && ent[window.LANG];
    if(!tr || !tr.n){
      el.textContent = orig;
      if(srcEl) srcEl.textContent = '';
      return;
    }
    el.textContent = tr.n;
    if(inH1){
      // v0.9.1 P1：H1 只留药名；来源/版本移到 H1 下方的 .sub，避免可访问名被污染。
      if(srcEl){
        srcEl.textContent = (tr.s ? srcLabel(tr.s) : '') + (tr.v ? ' · v' + tr.v : '');
      }
      return;
    }
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
      // v0.10.2：缺当前语言名不再把「暂无中文名」拼进名字（会进链接可访问名，
      // 且每个盐型各出现一次）。改由 applyNameLangBadges() / markAtcRowGaps()
      // 在名字**之后**放一枚徽章，ATC/大类行每行只标一次，盐型不单独标。
      if(lang === 'zh') el.textContent = zh || en;
      else if(lang === 'zh-Hant') el.textContent = zhh || en;
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
      if(!note || note.indexOf('bilingual.') === 0) return;
      // v0.8.4：保留全名 title，把「非翻译」说明附加在后面（不覆盖）
      var full = el.getAttribute('data-title-full');
      if(full === null){
        full = el.getAttribute('title') || '';
        el.setAttribute('data-title-full', full);
      }
      el.setAttribute('title', full ? (full + ' — ' + note) : note);
    });
    var cb = document.getElementById('bilOrig');
    if(cb) cb.checked = SHOW;
    // task-114：英文副标题在英文界面隐藏（避免重复）
    document.querySelectorAll('.cat-en').forEach(function(el){
      el.style.display = (window.LANG === 'en' || !SHOW) ? 'none' : '';
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
    // v0.9.8 task-13：新壳把 .langs 放在 nav 外，开关改插到 header 里的 langs 之前，
    // 避免它变成第 6 个导航项（旧壳 langs 在 nav 内，行为不变）。
    var langs = nav.querySelector('.langs') || document.querySelector('header .langs');
    if(langs && langs.parentNode){ langs.parentNode.insertBefore(lab, langs); }
    else { nav.appendChild(lab); }
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
      // v0.9.0 task-6：默认只显示 3 个市场列（产品最多 + 当前语言市场 + 第二多）；
      // 其余市场由筛选器国家多选加入；mk=CN,TW 可分享，localStorage 记忆。
      var LANG_MARKET = {en: 'US', es: 'ES', zh: 'CN', 'zh-Hant': 'TW'};
      var colCount = {};
      rows.forEach(function(tr){
        countries.forEach(function(c){
          var td = tr.querySelector('td[data-country="' + c + '"]');
          if(td && (td.querySelector('.m-brand') || td.querySelector('.brand-none'))){
            colCount[c] = (colCount[c] || 0) + 1;
          }
        });
      });
      function defaultCols(){
        // v0.9.1 task-22：优先用服务端已渲染的默认列，避免 JS 再改列造成 CLS。
        var pre = Array.prototype.map.call(
          document.querySelectorAll('th[data-defcol="1"]'),
          function(th){ return th.getAttribute('data-country'); }
        ).filter(function(c){ return c && countries.indexOf(c) >= 0; });
        if(pre.length) return pre.slice(0, 3);
        var order = countries.slice().sort(function(a, b){
          return (colCount[b] || 0) - (colCount[a] || 0);
        });
        var out = [];
        [order[0], LANG_MARKET[window.LANG] || '', order[1]].forEach(function(c){
          if(c && countries.indexOf(c) >= 0 && out.indexOf(c) < 0) out.push(c);
        });
        return out.slice(0, 3);
      }
      var forms = {}, releases = {};
      rows.forEach(function(tr){
        var f = tr.getAttribute('data-form') || '';
        var r = tr.getAttribute('data-release') || '';
        if(f) forms[f] = 1;
        if(r && r !== 'none') releases[r] = 1;
      });
      var T = window.T || function(k){ return k; };
      function opt(v, label){ var o = document.createElement('option'); o.value = v; o.textContent = label; return o; }
      // v0.9.8 task-13（P0-9）：筛选器默认收起；details 在客户端包，长尾页静态 0 增量。
      var det = document.createElement('details');
      det.className = 'mf-details';
      var sumEl = document.createElement('summary');
      sumEl.textContent = T('matrix.filters');
      det.appendChild(sumEl);
      var box = document.createElement('section');
      box.className = 'matrix-filters';
      box.innerHTML = '<div class="mf-head"><span class="mf-title"></span>'
        + '<span class="mf-count" aria-live="polite"></span>'
        + '<button type="button" class="mf-toggle" aria-expanded="false"></button></div>'
        + '<div class="mf-panel"></div>';
      det.appendChild(box);
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
      var ctrl = document.createElement('div'); ctrl.className = 'mf-country-actions';
      var allBtn = document.createElement('button'); allBtn.type = 'button'; allBtn.className = 'mf-reset';
      allBtn.setAttribute('data-mf-all', '1'); allBtn.textContent = T('matrix.country_all');
      var clearBtn = document.createElement('button'); clearBtn.type = 'button'; clearBtn.className = 'mf-reset';
      clearBtn.setAttribute('data-mf-clear', '1'); clearBtn.textContent = T('matrix.country_clear');
      ctrl.appendChild(allBtn); ctrl.appendChild(clearBtn); cbox.appendChild(ctrl);
      panel.appendChild(cf);
      // 剂型
      var ff = document.createElement('label'); ff.className = 'mf-field';
      ff.innerHTML = '<span></span><select data-mf-form></select>';
      ff.querySelector('span').textContent = T('matrix.form');
      var fsel = ff.querySelector('select');
      fsel.appendChild(opt('', T('matrix.all')));
      Object.keys(forms).sort().forEach(function(f){
        // v0.10.2：剂型下拉显示四语标签（原来显示英文原码 effervescent / tablet）
        var lb = T('form.' + f);
        fsel.appendChild(opt(f, (lb && lb.indexOf('form.') !== 0) ? lb : f));
      });
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
      var note = document.createElement('p'); note.className = 'sub matrix-sort-note';
      note.textContent = T('matrix.sort_note');
      var slot = wrap.previousElementSibling;
      if(slot && slot.classList.contains('mf-slot')){
        slot.appendChild(det);
        slot.appendChild(note);
      }else{
        wrap.parentNode.insertBefore(det, wrap);
        wrap.parentNode.insertBefore(note, wrap);
      }
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
          // v0.10.2 task-4：「首屏可见列全空」的行默认不渲染；一旦它所在的隐藏市场被
          // 加入列（?mk= 或下面的「加为一列」按钮），这一行就应当出现。
          // 注意：CSS 里 `tr[data-hide-empty]` 是 display:none，所以显示时必须写
          // 明确的 'table-row'（置空 '' 会退回 CSS 的 none）。
          if(tr.getAttribute('data-hide-empty') === '1'){
            var hid = (tr.getAttribute('data-hidden-mk') || '').split(',');
            var shownNow = hid.some(function(c){ return c && s.countries.indexOf(c) >= 0; });
            ok = ok && shownNow;
            tr.style.display = ok ? 'table-row' : 'none';
          }else{
            tr.style.display = ok ? '' : 'none';
          }
          if(ok) visible++;
        });
        // 「另有 N 个…」提示：全部显示出来后就不再提示（数字是构建期按默认列算的）
        var boxNR = document.querySelector('.matrix-hidden-rows');
        if(boxNR){
          var stillHidden = rows.some(function(tr){
            return tr.getAttribute('data-hide-empty') === '1' && tr.style.display === 'none';
          });
          boxNR.style.display = stillHidden ? '' : 'none';
        }
        var mobile = window.matchMedia && window.matchMedia('(max-width:719px)').matches;
        ths.forEach(function(th){
          var c = th.getAttribute('data-country');
          var show = s.countries.indexOf(c) >= 0;
          th.style.display = show ? (mobile ? '' : 'table-cell') : 'none';
          rows.forEach(function(tr){
            Array.from(tr.children).forEach(function(td){
              if(td.getAttribute('data-country') === c){
                td.style.display = show ? (mobile ? '' : 'table-cell') : 'none';
              }
            });
          });
        });
        var cnt = box.querySelector('.mf-count');
        if(!s.countries.length){
          cnt.textContent = T('matrix.empty_markets');
          cnt.classList.add('mf-warn');
          cnt.setAttribute('role', 'status');
        }else{
          cnt.classList.remove('mf-warn');
          cnt.textContent = T('matrix.showing').replace('{n}', visible).replace('{total}', rows.length)
            + ' · ' + T('matrix.market_count')
              .replace('{shown}', s.countries.length).replace('{total}', s.all.length);
          if(sumEl){
            sumEl.textContent = T('matrix.filters') + ' · ' + visible + '/' + rows.length
              + ' · ' + s.countries.length + '/' + s.all.length;
          }
        }
        if(updateURL){
          try{
            var p = new URLSearchParams(location.search);
            s.form ? p.set('mform', s.form) : p.delete('mform');
            s.rel ? p.set('mrel', s.rel) : p.delete('mrel');
            s.spec ? p.set('mspec', sinp.value.trim()) : p.delete('mspec');
            s.countries.length ? p.set('mk', s.countries.join(',')) : p.delete('mk');
            p.delete('mcountry');
            history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p.toString() : '') + location.hash);
            try{ localStorage.setItem('dsh.matrix.mk', s.countries.join(',')); }catch(e){}
          }catch(e){}
        }
      }
      // URL / localStorage / 默认 3 列初值
      var selected = [];
      try{
        var q = new URLSearchParams(location.search);
        var rawMk = q.get('mk') || q.get('mcountry') || '';
        selected = rawMk.split(',').filter(function(c){ return countries.indexOf(c) >= 0; });
        if(q.get('mform')) fsel.value = q.get('mform');
        if(q.get('mrel')) rsel.value = q.get('mrel');
        if(q.get('mspec')) sinp.value = q.get('mspec');
      }catch(e){}
      if(!selected.length){
        try{
          var stored = localStorage.getItem('dsh.matrix.mk') || '';
          selected = stored.split(',').filter(function(c){ return countries.indexOf(c) >= 0; });
        }catch(e){}
      }
      if(!selected.length) selected = defaultCols();
      cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){
        cb.checked = selected.indexOf(cb.getAttribute('data-mf-country')) >= 0;
      });
      fsel.addEventListener('change', function(){ apply(true); });
      rsel.addEventListener('change', function(){ apply(true); });
      sinp.addEventListener('input', function(){ apply(true); });
      cbox.addEventListener('change', function(){ apply(true); });
      allBtn.addEventListener('click', function(){
        cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){ cb.checked = true; });
        apply(true);
      });
      clearBtn.addEventListener('click', function(){
        cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){ cb.checked = false; });
        apply(true);
      });
      reset.addEventListener('click', function(){
        var defs = defaultCols();
        cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){
          cb.checked = defs.indexOf(cb.getAttribute('data-mf-country')) >= 0;
        });
        fsel.value = ''; rsel.value = ''; sinp.value = '';
        apply(true);
      });
      box.querySelector('.mf-toggle').addEventListener('click', function(){
        var open = box.classList.toggle('mf-open');
        this.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      // v0.10.2 task-4：「另有 N 个规格/剂型仅在 US · GB 有记录」后面的市场按钮 ——
      // 点一下就把该市场加进列（走同一套 ?mk= 机制，可分享），对应行随之出现。
      var noteHost = wrap.parentNode || document;
      Array.prototype.forEach.call(noteHost.querySelectorAll('[data-mk-add]'), function(btn){
        btn.addEventListener('click', function(){
          var c = btn.getAttribute('data-mk-add');
          var cb = cbox.querySelector('input[data-mf-country="' + c + '"]');
          if(!cb){ return; }
          cb.checked = true;
          apply(true);
          var nr = noteHost.querySelector('.matrix-hidden-rows');
          if(nr) nr.scrollIntoView ? nr.scrollIntoView({block: 'nearest'}) : null;
        });
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
