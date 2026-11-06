(function(){
// v0.9.6 task-145b：ATC4 页「按剂型看跨市场明细」——展开才 fetch 事实表（懒加载）。
// 行=剂型（字母序）、列=市场（固定市场序），值=产品数；不排序推荐、不做替代判断。
var el = document.querySelector('details[data-atc4]');
if(!el || !window.fetch) return;
el.hidden = false;                       // 无 JS 时保持 hidden：折叠区不出现，页面其余照常
var code = el.getAttribute('data-atc4');
var body = el.querySelector('.atc4-body');
var prefix = window.DSH_PREFIX || '';
var url = prefix + 'data/idx/atc4-forms.json?v=1793384980';
var ORDER = ['US','GB','CA','AU','SG','CN','ES','MX','TW','HK'];
function T(k, d){
  var t = window.T;
  if(!t) return d;
  var v = t(k);
  return (v === k || v === undefined) ? d : v;
}
function esc(x){
  return String(x).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
  });
}
function formLabel(f){
  if(f === 'other') return T('atc4.form_other', 'other forms');
  return T('form.' + f, f);
}
function render(rows){
  var markets = [], forms = {}, seen = {}, i;
  for(i = 0; i < rows.length; i++){
    var f = rows[i][2], c = rows[i][3];
    if(!seen[c]){ seen[c] = 1; markets.push(c); }
    if(!forms[f]) forms[f] = {};
    forms[f][c] = (forms[f][c] || 0) + rows[i][4];
  }
  markets.sort(function(a, b){
    var ia = ORDER.indexOf(a), ib = ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  var list = Object.keys(forms).sort();
  var h = ['<table class="atc4t"><thead><tr><th scope="col">'
           + esc(T('atc4.form_col', 'Dosage form')) + '</th>'];
  for(i = 0; i < markets.length; i++){
    h.push('<th scope="col" data-country="' + esc(markets[i]) + '">'
           + esc(markets[i]) + '</th>');
  }
  h.push('</tr></thead><tbody>');
  for(var r = 0; r < list.length; r++){
    h.push('<tr><th scope="row">' + esc(formLabel(list[r])) + '</th>');
    for(var m = 0; m < markets.length; m++){
      var n = forms[list[r]][markets[m]];
      h.push(n ? '<td>' + n + '</td>' : '<td class="z">·</td>');
    }
    h.push('</tr>');
  }
  h.push('</tbody></table><p class="sub atc4note">'
         + esc(T('atc4.sort_note', '')) + '</p>');
  body.innerHTML = h.join('');
}
var cache = null;
function show(){
  if(!cache){
    // 加载提示由 JS 写（静态 HTML 只留折叠入口，省 798 页的每页体积）。
    body.innerHTML = '<p class="sub">' + esc(T('atc4.loading', '…')) + '</p>';
    cache = fetch(url, {credentials: 'same-origin'}).then(function(r){
      if(!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  cache.then(function(d){
    var all = (d && d.rows) || [], rows = [];
    for(var i = 0; i < all.length; i++){
      if(all[i][0] === code) rows.push(all[i]);
    }
    if(rows.length) render(rows);
    else body.innerHTML = '<p class="sub">' + esc(T('atc4.empty', '')) + '</p>';
  }).catch(function(){
    body.innerHTML = '<p class="sub">' + esc(T('atc4.error', '')) + '</p>';
  });
}
el.addEventListener('toggle', function(){ if(el.open) show(); });
})();
