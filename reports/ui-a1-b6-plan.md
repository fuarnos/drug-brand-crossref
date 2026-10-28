# A1 / A3 / B6 / B7 实现方案（只读，v0.5.6 前准备）

> 日期：2026-10-28 ｜ 任务：`task-49` ｜ 目标版本：**v0.5.6**（见 `docs/谷段需求队列.md` L117）
> 依据代码快照：`site/build.py` 4,051 行（2026-10-28 09:42 快照，当前 v0.5.2）；行号会随其它任务漂移，**按锚点函数名定位**。
> 边界：本任务**未改** `site/build.py`、**未写** `data/drugs.db`、未跑 git / 发布；只产出本方案 + `.tmp/ui-plan/` 证据。
> 索引/数据库口径：`site/dist/data/index.json` 127,085 条；`product` 409,587；`product_name` 568,907 行（distinct key×product 567,795）；`name_key` 135,251；`variant` 13,886（salt 非空 1,694）；`dose_warning` published 40（其中 R1/R2 24）。**以上为 2026-10-28 09:44 探测时点**；DB 正被并行优化任务写入，实施时以现库 `db/q.py` 现查为准（`product_name`/`product` 数会小幅漂移，不影响方案结论）。

## 0. 结论

1. **A1 详情展开必须走「懒加载明细文件」**，不能塞进主索引：product 级字段（pack/approval/status/date/source_url）不在索引里；按 key 截断 12 条约 **297k 行 / ~51 MB raw**，只能按 `_shard_bucket` 桶拆成几十个文件、点击「详情」时按 `db` 字段拉单桶（约 1.3 MB raw、gzip ~200–350 KB），并缓存。
2. **A3 可在索引里加 3 个短字段解决**（`sl` 盐型列表、`rl` 释放机制、`wi` 已发布 R1/R2 warning id）；受影响条目约 2.6 万 / 12.7 万，体积增量 <1.5 MB raw（core 字典编码后更小）。行内徽章 + 链到 `/warn.html#w-<id>` 或成分页，不改碰撞判定。
3. **B6 每行报告入口**：`reportURL()` 已有页面级实现（`build.py:2285-2298`）。每行复用同一 prefill 逻辑，但 **GitHub issue form（`.github/ISSUE_TEMPLATE/data-error.yml` 是 YAML form）会忽略 URL 的 `body` 预填**；建议行级链接**不带 `template=`**、改用 `title`+`body`+`labels=data-error` 的空白 issue（说明见 §3.2），页面级入口保持现状。
4. **B7 纯前端导出**：结果数据在 `RES_GROUPS`（`build.py:1618-1628`）里，导出/复制不需要索引或后端改动；新增一个 2 按钮工具条（复制 TSV / 下载 CSV），CSV 带 UTF-8 BOM、字段取自当前视图；注意 iOS 下载与剪贴板权限降级。
5. 四项都可以**独立开关/回退**：A1 明细文件 404 时降级为链到成分页；B6/B7 按钮只在有结果时渲染；索引字段为空时 A3 不渲染徽章。`?legacy=1` 路径不受影响（index.json 同样会带新字段）。

## 1. 现状事实（核对过代码/生成物/DB）

| 事实 | 值/位置 |
|---|---|
| 结果行渲染 | `brandRowHTML(e,T)` `build.py:1601-1614`；分组循环 `resultsHTML` `1630-1668`；表格 `resultsTableHTML` `1670-1675` |
| 结果数据 | `display` = `[score,tier,entry]` 数组；`RES_GROUPS = groupByIngredient(display)` `build.py:2236-2239` |
| 索引条目字段 | `k,d,c,x,s,f,l,n,v,vs,u,cu,g,gn,m,mn`（生成物实测 + `load_index` `build.py:2900-2921`） |
| **索引没有** product 级字段 | product_id / pack / approval_id / status / status_date / source_id / source_url 都不在索引；`product.source_url` 409,585/409,587 非空，`pack` 294,821（72%），`status_date` 40,728（10%），`approval_id` 409,575 |
| 索引编码 | core：`CORE_DICT_COLS/CORE_ARRAY_COLS` `build.py:3624-3625`、`encode_core` `3654-3690`、客户端 `decodeCore` `2332-2354`（通用列自动解码，**加标量字段无需改 decode**）；分片 `encode_shards` `3786-3830`（分片是完整条目 JSON） |
| 索引体积 | `index.json` 34.91 MB、`core.json` 15.33 MB；分片 ~60 个（最大 1.10 MB/片，target 1.1 MB）；`manifest.json` 有 `buckets/cjkInitials/v` |
| 报告入口 | 页面级 `#reportLink` `build.py:3403-3407`；`reportURL(q)` `2285-2298`；点击事件 `2517-2524`（`click-report`）；issue form `.github/ISSUE_TEMPLATE/data-error.yml`（YAML **form**：query/page/expected/actual/source 等字段） |
| 警示数据 | `/warn` 条目带锚点 `id="w-<warning_id>"`（`build_warn` `build.py:1166-1199`，article `1190`）；成分页已有 `../warn.html#w-…` 链（`1148-1161`） |
| 相关 DB 规模 | 盐型多 variant 的成分 982 个（salt 非空 variant 1,694）；`release<>none` 产品 23,855；含 published R1/R2 warning 的成分见 `dose_warning` 24 条 |
| CSS | `CSS = """` `build.py:1289`；`table.res` `1346-1354`；`.fold-row` `1392`；移动端覆盖 `1412-1426` |
| i18n | `I18N` 三个子字典：en `96-225`、es `226-357`、zh `358-472`（新增 key 三处都要加） |

## 2. A1 产品详情展开行

### 2.1 目标

结果里每个品牌行（`brandRowHTML`）加「详情 ▸」按钮；点击**在行下方插入一行动态面板**（折叠行，不是新页面、不是 40 万页），显示该名字下的产品记录（每条 = 一个包装/注册）：

- 商品名（本行名字）· 市场（c 列第一项）· 剂型/释放（form/release）
- **包装 pack**、**批准号/NDC/DIN/ARTG approval_id**、**状态 status + status_date**、**来源 source_id + 原始记录链接 source_url**
- 默认展示前 **12** 条；超过时显示「共 N 条，全部见成分页」链接；无数据时显示「—」
- 数据缺失字段显示 `—`（pack 在 ES/GB/MX 全空，见 §1；这是源事实，不造数据）

### 2.2 索引字段变化（小）

`load_index()` 的 entry 字典（`build.py:2900-2921`）增加 1 个短标量：

```python
"db": _shard_bucket(key_id),   # A1 明细文件桶名（40 种取值，字典编码后几乎不增体积）
```

> 不把 product_id/pack/approval/status/url 放进索引：会把 `index.json` 再涨 ~50 MB（`Σ min(n,12)=297,260` 行 × 实测 172 B ≈ 51 MB raw），与「首搜体积优先」冲突。

### 2.3 明细文件（新构建产物，懒加载）

构建侧（`main()` 里紧跟 `encode_shards(entries)` 之后，约 `build.py:3975-3980`）：

```python
# 建议新函数 build_details(entries) → 写 OUT/data/idx/detail-<bucket>.json
# 数据来源 SQL（一次全量，按 key 分组；只取索引里存在的 key）：
SELECT pn.key_id, p.product_id, p.pack, p.approval_id, p.status, p.status_date,
       p.dosage_form, p.release, p.source_id, p.source_url
FROM product_name pn JOIN product p ON p.product_id = pn.product_id
WHERE pn.name_type IN ('trade','inn')
```

- 分组：`key_id → 记录数组`，每条 `[product_id, pack, approval_id, status, status_date, dosage_form, release, source_id, source_url]`；
- 每个 key 取前 12 条（按 country, status, product_id 排序，优先 active；`pack=''` 保留占位）；记录总量 `Σmin(n,12)=297,260`，估 **~51 MB raw / 全站 gzip 约 7–9 MB**；按桶拆（`_shard_bucket` → 约 40 个文件，单桶 ~1.3 MB raw，gzip ~200–350 KB）；
- 详情文件**不带**进首屏；客户端在用户点「详情」时才请求。
- 422/缺失兜底：detail 文件 404 时前端降级为链到成分页 `drug/<v>.html`。

### 2.4 JS 草案（插在 `brandRowHTML` 与结果事件委托处）

```js
// brandRowHTML：在 brand 单元格尾部插按钮（仅当 e.n>0）
const det = `<button type="button" class="linkbtn detbtn" data-det="${esc(e.k)}" data-v="${esc(e.v||'')}"
  aria-expanded="false">${esc(T('a1.expand'))}</button>`;
// ...
<td class="c-brand">${brandHTML(e)}${tags}${combo}${badge} ${det}</td>

// 全局：明细桶缓存 + 渲染
const DET_CACHE = new Map();
function detBucketOf(e){ return e.db || 'other'; }
function loadDetailBucket(bucket){
  if(DET_CACHE.has(bucket)) return Promise.resolve(DET_CACHE.get(bucket));
  const ver = (MANIFEST && MANIFEST.v) ? '?v=' + MANIFEST.v : '';
  return fetchJSON(BASE + 'data/idx/detail-' + bucket + '.json' + ver)
    .then(d => { DET_CACHE.set(bucket, d); return d; })
    .catch(() => { DET_CACHE.set(bucket, {}); return {}; });
}
function detPanelHTML(rows, e, T){
  // 行内字段顺序：[0]product_id [1]pack [2]approval_id [3]status [4]status_date
  //               [5]dosage_form [6]release [7]source_id [8]source_url
  const cols = [T('a1.source'), T('a1.pack'), T('a1.approval'), T('a1.status'), T('a1.raw')];
  const body = rows.slice(0, 12).map(r => `<tr>
    <td>${esc(r[7])}</td>
    <td>${esc(r[1]) || '—'}</td>
    <td><code>${esc(r[2]) || '—'}</code></td>
    <td>${esc(r[3])}${r[4] ? ' · ' + esc(r[4]) : ''}</td>
    <td>${r[8] ? `<a href="${esc(r[8])}" target="_blank" rel="noopener">${esc(T('a1.raw'))}</a>` : '—'}</td>
  </tr>`).join('');
  return `<table class="det"><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead>`
    + `<tbody>${body}</tbody></table>`
    + (rows.length > 12 ? `<p class="sub">${esc(T('a1.more'))}</p>` : '');
}
// resultsHTML 里：每个 brandRowHTML 后按需插入 <tr class="detrow" data-fork="...">（默认 display:none）

// out 事件委托（build.py:2489-2515 内追加）
if(t.closest('[data-det]')){
  const btn = t.closest('[data-det]'), k = btn.dataset.det;
  const tr = btn.closest('tr'), next = tr.nextElementSibling;
  if(next && next.classList.contains('detrow') && next.dataset.fork === k){
    next.style.display = next.style.display === 'none' ? '' : 'none';
    btn.setAttribute('aria-expanded', next.style.display !== 'none');
    return;
  }
  const e = (RES_GROUPS || []).flatMap(g=>g.rows).find(x=>x.k===k) || {k, v: btn.dataset.v};
  const row = document.createElement('tr');
  row.className = 'detrow'; row.dataset.fork = k;
  row.innerHTML = `<td colspan="4" class="detcell">${esc(T('a1.loading'))}</td>`;
  tr.after(row);
  loadDetailBucket(detBucketOf(e)).then(d => {
    const rows = (d && d[k]) || [];
    row.querySelector('.detcell').innerHTML = rows.length
      ? detPanelHTML(rows, e, T)
      : `<span class="sub">${esc(T('a1.none'))} <a href="${BASE}${e.v ? 'drug/' + e.v + '.html' : ''}">${esc(T('a1.goto'))}</a></span>`;
  });
  return;
}
```

### 2.5 插入点 / 风险 / 验收

| 项 | 位置（锚点） |
|---|---|
| entry 加 `db` | `load_index()` entry dict（`2810` 函数内，`2900-2921`） |
| 明细构建函数 | 新函数放 `encode_shards` 前（`3786` 附近），`main()` 在 `encode_shards(entries)` 后调用（`3975`） |
| 客户端按钮 | `brandRowHTML`（`1601-1614`） |
| 面板行 | `resultsHTML` 行循环（`1646-1649`） |
| 事件 | `out.addEventListener('click', …)`（`2489-2515`） |
| CSS | `CSS` 块 `1289` 内、`.fold-row` 附近（`1392`）+ 移动端（`1412-1426`）补充 `.detrow/.detcell/.det`；`.linkbtn` 已有可复用 |
| i18n | en/es/zh 三块（`96-225 / 226-357 / 358-472`）加 `a1.*`（expand/loading/none/goto/pack/approval/status/source/raw/more） |

**风险**：① 单桶明细 1.3 MB raw（gzip ~200–350 KB），弱网首次展开有等待 → 要 loading 态 + 失败降级；② 明细文件数量 +~40（发布文件数从 2.4 万+到 2.4 万+，`publish.ps1` 门槛 24,000 已满足，但构建耗时略增）；③ `product.pack` 在 ES/GB/MX 为空，面板会出现大量 `—`，需在验收中接受为源事实；④ 组合页/成分页不需要 A1（只做结果行）。
**验收**：US/GB/CN/CA 各抽 1 品牌行展开，行前后 DOM 顺序正确、再次点击折叠；`Σ` 抽查 `product_id` 与 `db/q.py` 一致；断网/404 时降级链接可用；移动端（<720px）面板按 block/card 样式显示不溢出；`index.json` 体积增幅 <1 MB、`core.json` <0.5 MB。

## 3. B6 结果行「报告错误」快捷入口

### 3.1 现状

- 页面级报告链：`#reportLink`（`build.py:3403-3407`），`reportURL(q)`（`2285-2298`）已按 i18n 生成 body 字段（query/page/expected/actual/pack），点击事件 `2517-2524` 记 `click-report`。
- `.github/ISSUE_TEMPLATE/data-error.yml` 是 GitHub **issue form（YAML `body:` 字段）**。

### 3.2 可行方式与关键坑

GitHub 新 issue URL 支持 `title/body/labels/assignees/template`。**issue form 模板会忽略 `body` 预填**（form 的字段由 YAML 定义，body 参数不注入表单）；因此：

- **行级链接（推荐）**：不带 `template=`，用 `labels=data-error&title=…&body=…` 创建空白 issue，body 按模板字段顺序手写（query/page/row/expected/actual/source），维护者仍能按 `data-error` 标签分流；
- 页面级入口保持现状（带 template，用户手填 form）；
- 风险：仓库若强制要求 form 模板/必填项，空白 issue 可能绕过模板 → 在报告里注明，若维护者不接受可改为「行级只预填 title，body 留空」的保守方案。

每行在 `brandRowHTML` 的品牌单元格（`1601-1614`）加一个轻量链接/按钮（⚑ 图标或文字），context 取当前行 entry：

```js
function rowReportURL(e, t){
  const q = (box.value || '').trim();
  const page = location.href.split('#')[0];
  const body = [
    '**' + Tr('report.field_query') + '**: ' + q,
    '**' + Tr('report.field_page') + '**: ' + page,
    '**' + Tr('report.field_row') + '**: ' + (e.d || '') + ' · ' + (e.x || '') +
      ' · ' + ((e.c || []).join(', ')),
    '**' + Tr('report.field_expected') + '**: ',
    '**' + Tr('report.field_actual') + '**: ',
    '**' + Tr('report.field_pack') + '**: ',
  ].join('\n');
  return REPORT_REPO + '/issues/new?labels=data-error'
    + '&title=' + encodeURIComponent(Tr('report.issue_title') + (q || e.d || ''))
    + '&body=' + encodeURIComponent(body);
}
// brandRowHTML: + `<a class="rowreport" href="${esc(rowReportURL(e,T))}" target="_blank"
//   rel="noopener" title="${esc(T('row.report'))}" aria-label="${esc(T('row.report'))}">⚑</a>`
```

- **隐私**：只带当前查询词、当前页面 URL（可能含 `?q=`）、行名（本站公开数据），**不带** localStorage/UA/历史；用户提交到 GitHub 是主动公开行为，页面提示沿用现有 report 区文案即可。
- 事件：在 `document` 事件委托（`2517-2524`）里加 `href.indexOf('/issues/new')` 已有 `click-report`；行级可再加 `click-report-row`（可选，用 `data-rowreport` 判断）。
- 插入点：`reportURL` 旁新增 `rowReportURL`（`2298` 后）；`brandRowHTML`（`1601-1614`）；i18n 加 `row.report` + `report.field_row`（`report.field_*` 已有，en 189-196 / es 320-327 / zh 437-444）。
- **验收**：US/GB/CN 三行点 ⚑ → 新标签打开 GitHub issue，title/body 预填、`data-error` 标签正确、body 无 PII；与页面级报告入口并存不冲突；移动端图标点击区域 ≥32px。

## 4. B7 结果导出 CSV / 复制表格

### 4.1 数据来源与显隐

- 当前结果都在 `RES_GROUPS`（`build.py:1618-1628`）：`[{ing, tags, rows:[entry]}]`；`entry` 有 `k,d,x,s,c,f,m,n,v,u,l`。
- 导出范围建议取**当前视图全部结果**（`LAST_DISPLAY`），而不是只导出「已展开/已加载更多」的可见行；在 `render()` 里 `RES_GROUPS = groupByIngredient(display)` 之后存 `LAST_DISPLAY = display`（约 `2236-2239`）。国家视图（`countryView`）下导出该国结果，符合用户预期。
- 列（三语表头，导出时用当前语言）：成分、品牌、剂量、国家、剂型、厂家、匹配方式、站点链接；每行 = 一个品牌条目（同 `brandRowHTML` 行）。

### 4.2 工具条 + CSV/TSV 草案

在 `resHTML`（`build.py:2236-2239`）里 `#reswrap` 前插入：

```html
<div class="restools">
  <button type="button" class="linkbtn" data-export="csv">复制表格</button>
  <button type="button" class="linkbtn" data-export="csvfile">下载 CSV</button>
</div>
```

```js
let LAST_DISPLAY = [];
function exportRows(){
  const rows = [];
  for(const [, tier, e] of (LAST_DISPLAY || [])){
    rows.push([e.x || e.d, e.d, (e.s || []).join(' / '), (e.c || []).join(', '),
               e.f || '', e.m || '', tier, e.u ? BASE + 'name/' + e.u : '' ]);
  }
  return rows;
}
function csvCell(v){
  const s = String(v == null ? '' : v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function toCSV(rows){
  return '\ufeff' + rows.map(r => r.map(csvCell).join(',')).join('\r\n');
}
function toTSV(rows){ return rows.map(r => r.map(v => String(v==null?'':v).replace(/\t/g,' ')).join('\t')).join('\n'); }
function download(name, text){
  const blob = new Blob([text], {type: 'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function copyText(text){
  if(navigator.clipboard && navigator.clipboard.writeText){
    return navigator.clipboard.writeText(text).then(() => true).catch(() => fallbackCopy(text));
  }
  return Promise.resolve(fallbackCopy(text));
}
function fallbackCopy(text){       // iOS/旧浏览器降级
  const ta = document.createElement('textarea'); ta.value = text;
  ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  let ok = false; try{ ok = document.execCommand('copy'); }catch(e){}
  ta.remove(); return ok;
}
// 事件：out.addEventListener('click', …)（2489-2515）
if(t.closest('[data-export]')){
  const rows = exportRows();
  const mode = t.closest('[data-export]').dataset.export;
  if(mode === 'csv'){ download('drug-crossref-' + new Date().toISOString().slice(0,10) + '.csv', toCSV(rows)); }
  else { copyText(toTSV(rows)).then(ok => { /* toast via #meta 或临时 span，ok 时 i18n 提示「已复制」 */ }); }
  gcEvent('export-' + mode); return;
}
```

- 头行：可在 CSV 里加 3 行元信息（`# query / page / date`，以 `#` 开头不影响 Excel 阅读）——建议保持纯表格 + 文件名带日期，避免解析器踩坑。
- i18n：`res.csv` / `res.copy` / `res.copied` / `res.csv_note`（三处字典）。工具条仅在 `RES_GROUPS.length` 时渲染。
- 风险：① 结果可能 200 条上限 → 导出为当前视图上限，报告里注明；② iOS Safari 对 `download` 属性支持有限 → 复制 TSV 作为主路径、下载为次；③ 剪贴板需 user gesture（按钮点击满足）与 https（站点满足）；④ CSV 用 BOM + CRLF 兼容 Excel；⑤ 隐私：导出仅当前公开结果，不写 cookie/统计。
- **验收**：en/es/zh 三语下表头正确；`Lipitor` 查询导出 CSV 行数与结果行一致（含折叠未展示行）；Excel/LibreOffice 打开无乱码；移动端复制成功提示；无结果时工具条不出现；`gcEvent('export-*')` 可在 GoatCounter 看到。

## 5. 索引字段与体积影响（A1/A3 汇总）

| 改动 | 字段/产物 | 体积估算 | 是否进首屏 |
|---|---|---|---|
| A1 bucket | entry 加 `db`（40 种值） | 字典列几乎 0，index.json +~0.1 MB | 是（小） |
| A1 明细 | `data/idx/detail-<bucket>.json`（约 40 个） | Σmin(n,12)=297,260 行 × ~172 B ≈ **51 MB raw / gzip ~7–9 MB 全站**；单桶 ~1.3 MB raw | **否**（点击懒加载） |
| A3 盐型 | `sl`（≤64 字符，仅 2 万余条非空） | +~1–1.5 MB raw；core 字典编码后更小 | 是 |
| A3 释放 | `rl`（"IR"/"ER"/"IR,ER"，约 4.8k 条） | 可忽略 | 是 |
| A3 警示 | `wi`（warning_id，≤48 字符，约 4.3k 条） | 可忽略 | 是 |
| 编码改动 | `encode_core` 的 `CORE_DICT_COLS`（`build.py:3624`）加 `sl/rl/wi/db`；`encode_shards` 自动带字段；`index.json` 双写自动带 | core.json 预计 +0.3–0.8 MB | — |

> 注意：`decodeCore` 对未知列是通用的（`build.py:2342-2352`），所以**标量字段不用改 JS 解码**；若日后加数组字段，必须同步 `CORE_ARRAY_COLS`（`3625`）。

## 6. 实施顺序（交给能改 build.py 的会话）

1. **A3（最小、先做）**：`load_index` 聚合时算 `sl/rl/wi` → `encode_core` 列表加字段 → `brandRowHTML` 徽章 + 事件 → i18n → 构建验收。
2. **B7**：`LAST_DISPLAY` + 工具条 + CSV/TSV + i18n → 三语/移动端验收。
3. **B6**：`rowReportURL` + 行内 ⚑ + i18n → 三语验收（含 issue 预填实测）。
4. **A1（最大）**：`db` 字段 + `build_details()` + `detail-*.json` → 前端懒加载/面板/折叠 → 断网降级 → 体积与页面数回归。
5. 每步单独 commit 主题；v0.5.6 发版：CHANGELOG → `python site/build.py` 到 `== done ==` → 三语抽查 + 320 例评测不回归 → `deploy/publish.ps1` 由发布会话执行；回滚 = `?legacy=1`（索引路径）+ revert build.py（A1/A3/B6/B7 都是增量）。

## 7. 验收清单（v0.5.6 合并后）

- [ ] `python site/build.py` 到 `== done ==`，`index.json` 体积增幅 <1 MB、`core.json` <1 MB、分片数 +0（detail 文件另计）；
- [ ] A1：US/GB/CN/CA 各 1 行展开/折叠；明细字段与 DB 抽查一致；404 降级；移动端不溢出；
- [ ] A3：metoprolol（盐型）、nifedipine（缓释）、warfarin（R6）三类行分别出现预期徽章；无 warning 的盐型只提示「多盐型」不写「不可互换」；
- [ ] B6：三语行级 ⚑ 预填 title/body/labels；无 PII；页面级入口不变；
- [ ] B7：三语 CSV 表头、行数一致、Excel 无乱码、复制成功提示、空结果无工具条；
- [ ] 三语检索评测 320 例不回归；About/CHANGELOG 计数不变（无数据变化）；
- [ ] `?legacy=1` 回退路径正常（index.json 带新字段也不影响旧 render）。

## 8. 证据索引（`.tmp/ui-plan/`）

| 文件 | 内容 |
|---|---|
| `probe.py` / `probe.out.txt` | dist 数据文件体积、index 字段实测、DB 字段非空率/分布 |
| `estimates.py` | A1/A3 规模与体积估算（Σmin(n,20/12)、受影响 key 数） |
| `line_index.py` | build.py 所有插入点行号索引（2026-10-28 快照；锚点函数名见本报告） |

_本方案为只读准备：未改 `site/build.py`、未写 `data/drugs.db`、未跑 git / 发布；JS/HTML 片段为草案，落地时以当时 build.py 行号为准。_
