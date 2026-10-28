# U1 / U2 / U3 使用向改进实现方案（只读，v0.6.1 前准备）

> 日期：2026-10-28 ｜ 任务：`task-65` ｜ 目标版本：**v0.6.1**（`docs/谷段需求队列.md`「使用者向改进池」U1/U2/U3）
> 依据代码快照：`site/build.py` **4,920 行**（2026-10-28 10:38，含 v0.5.5 `xz`/`meta`、v0.5.6 A1/A3/B6/B7）
> 边界：本任务**只读分析**——未改 `site/build.py`、未写 `data/drugs.db`、未跑 git / 发布。
> **行号会随其它任务漂移，patch 前按「锚点片段」重新定位**。
> 对照：`reports/ui-a1-b6-plan.md`（A1/A3/B6/B7 已实现的原方案）、`reports/i18n-v055.md`（xz/meta 机制）、
> `reports/zh-hant-i18n.md`（zh-Hant 字典 203 键 + 台湾用词）、`reports/i18n-audit-20261026.md`（key 完整性）。

---

## 0. 结论（一张表）

| 项 | 目标 | 主要插入点（当前快照） | 数据/文案依赖 | 建议版本 | 风险 |
|---|---|---|---|---|---|
| **U1** 首屏 3 步引导 | 首次访问展示「输入包装名 → 看成分/规格 → 切国家看叫法」，3 张步骤卡 + 真实示例；`×` 关闭后 localStorage 记住、不再出现；移动端堆叠 | `build_index_page` 的 body（L4193–4228，建议插在 L4217 示例行之后 / L4218 前）；CSS 在 `CSS=` L1518 的 `@media` 前（L1644 前）；关闭逻辑在 `APP_JS` L1714 起；防闪烁用 `page()`（L3095）新增 `head_js` 参数 + 首页内联脚本 | 10 个 `u1.*` i18n key ×4 语言；复用现有 `data-q` 示例（L4212–4216、点击处理 L3012） | v0.6.1-a（小改动、可先发） | 首屏 CLS / 打扰；无 JS 降级；四语文案 |
| **U2** 结果顶部「各国叫法」横排 | 结果区顶部一行 7 国（US/GB/CN/ES/MX/AU/CA）：各国名称 + 「未收录」；点击 = 切到该国国家视图；选中高亮；移动端横滚 | `render()`（L2493）：在 hits/国家视图计算后（L2554 后）计算 `countryBarHTML`，拼进 `out.innerHTML`（L2703–2704，放在 `parseBarHTML` 之后、预警之前）；点击复用 `out` 事件委托（L2923）+ `ctry`/`render()`/`syncURL`；CSS 在 L1518 后加 | **零新增索引字段**：用现有 `c/v/vs/d/s/n/u/x/xz`（L3399 `load_index`），国家名用 `home.*`；5 个 `u2.*` key ×4 | v0.6.1-b | 语义：多成分/模糊时不能误导；未收录 ≠ 该国无此药；性能 |
| **U3** 界面标签本地化 | 剂型（`form_base` 枚举）、状态（已有 3 语）、释放机制（IR/ER…）、单位（iu/unit/mcg…）、国家名 → zh/en/es/**zh-Hant** 四语统一 | `I18N` L96 加 `LABEL_I18N`（并入 `_merge_static_i18n` L1045 的合并列表）；`name` 页 L3902–3905；`drug` 页 L3782–3805；A1 明细 JS L1937–1958；`page()` locale L3114；`data/i18n_zh_hant.json` 重生成 | 已有：status 4 词、国家名 `home.*`、zh-Hant 字典 203 键；**新增约 35 个 key ×4 语言** | v0.6.1-a（先做，纯字典） | form_base 长尾值；zh-Hant 字典漂移；A1 明细同步 |

> 顺序建议：**U3 → U1 → U2**。U3 只动字典/渲染 helper，风险最低且是 U1/U2 文案的基础；U1 是静态 HTML/CSS；
> U2 动 `render()` 核心逻辑，必须有 DOM 测试 + 性能/边界验收，放最后。
> 三项都改 `site/build.py`（并行热点文件），**必须串行**；每项独立 CHANGELOG/build/publish/smoke。

---

## 1. 现状与「不要重复造轮子」清单

当前 `build.py` 已有三套可复用机制：

| 机制 | 位置 | U1/U2/U3 怎么复用 |
|---|---|---|
| **I18N 运行期字典**（base + 6 个合并字典 ≈225 key/语言；脚本按 ast 提取，`PAGE_I18N` 里 f-string 形态的键未计入，实际以构建后 `i18n.js` 为准） | `I18N` L96；`META_I18N` L920；`_merge_static_i18n` L1045（合并 ABOUT/PAGE/WARN/COMBO/MAKER/META） | U1/U2/U3 的文案**全部加进 I18N 体系**（U3 新增 `LABEL_I18N` 并加入 L1048 合并列表）；不新建 per-feature JSON 文案文件 |
| **`xz` 索引中文字段 + `ingredientLabel()`** | `load_index` L3399（`xz` 字段）；JS `ingredientLabel` L1824 | U2 显示成分中文名时直接用 `ingredientLabel(e)`；**不需要新增索引字段**（国家名不在索引里） |
| **`meta`/静态本地化副本** | `page(meta_key/canonical_rel/alt_rel)` L3095；`_page_meta` L3088；`_write_with_copies` L3191；`_localize_copy` L3164 | U1 只在首页 `<body>` 加 HTML；`/es/`、`/zh/` 首页本来由 `build_index_page` 的 `LANGS` 循环生成（L4229–4236），**guide HTML 同一份、由 i18n.js 本地化**，不需要新副本；U3 标签走 `data-i18n` 运行时替换，也不改副本 |
| **结果渲染函数**（v0.5.6 已含 A1/A3/B6/B7） | `brandRowHTML` L2018、`groupByIngredient` L2044、`resultsHTML` L2055、`resultsTableHTML` L2095、`detPanelHTML` L1937、`RES_GROUPS` L2041、`LAST_DISPLAY` L2042 | U2 只在外层加一段「各国叫法」HTML，**不改结果表结构/排序/折叠**；U3 的 form/release/status 标签接入 `brandRowHTML`/`detPanelHTML` 的现有 `T()` 调用 |
| **国家视图/URL/统计** | `updateCtryLabel` L2211；`ctry` 事件 L3006；`syncURL`（render 内 L2505）；`gcEvent('country-…')`（L3010 附近） | U2 点击国家 chip → `ctry.value=code; updateCtryLabel(); render();` 完全复用现有国家视图与 URL 状态，**不新增路由/参数** |
| **示例按钮** | 首页 `data-q` L4212–4216；点击处理 L3012 | U1 的「真实示例」直接复用这批按钮（同一批词跨语言可搜），不新增示例数据 |

**明确不做（避免重复造轮子）**：
- U2 不新增索引字段、不新增构建产物、不请求新数据文件（体积守卫：`index.json` 52.9 MB / core 25.7 MB 已接近上限）。
- U1 不引入第三方引导库/图标库（纯 HTML+CSS+少量 JS，离线可用）。
- U3 不在 JS 侧另写一套映射表：**服务端 `data-i18n` 与客户端 `T()` 共用同一批 i18n key**。
- 不与 task-55「注册表接入 build.py」重复改 `LANGS`/国家列表：U1/U2 用现有 `ctry` 与 `LANGS`/7 国（等注册表 Phase 1/2 落地后自动受益）。

---

## 2. U1 首屏 3 步引导

### 2.1 交互设计（版本 v0.6.1-a）

- **位置**：首页搜索框 + 国家选择行**下方**（当前 `build_index_page` body 的 L4217 `</div>` 之后、L4218 `loadhint` 之前）。
  理由：搜索框仍是首屏第一视觉焦点；3 步卡紧贴操作区，不挤到结果区；关闭后不占空间。
- **内容**（3 张卡，横向 3 列 → 移动端纵向堆叠）：

| # | 标题 | 说明 | 真实示例按钮（复用 `data-q`） |
|---|---|---|---|
| 1 | 输入包装上的名字 | 商品名 / 通用名 / 俗称 / 包装上一行字都能搜；可合并剂量如 `Lipitor 20mg` | `泰诺`、`Lipitor 20mg` |
| 2 | 看成分和规格 | 结果先给「成分 + 规格 + 品牌」候选集，不唯一断言 | `两只青蛙` |
| 3 | 切国家看对应叫法 | 选国家 = 看这个成分在该国上架的名字；也可直接看 U2 的各国叫法横排 | `Benadryl`、`Gaviscon` |

- **关闭**：右上角 `×`（按钮，`aria-label` 本地化）；点击后 `localStorage.setItem('u1.dismiss.v1','1')`，`#u1guide` 隐藏（`hidden`/`.u1-off`）。
- **首次判定**：`localStorage.getItem('u1.dismiss.v1')==='1'` → 不显示；**失败/无 localStorage（隐私模式）→ 默认显示**（可点关闭）。
- **防闪烁（CLS）**：`page()` 增加可选参数 `head_js: str = ""`，首页构建时传入极小内联脚本（在 `</head>` 前、`i18n.js` 后）：

```js
try{if(localStorage.getItem('u1.dismiss.v1')==='1')document.documentElement.className+=' u1-off';}catch(e){}
```

CSS：`html.u1-off #u1guide{display:none}` —— 类在 body 解析前设置，无「先显示后隐藏」跳动。
（不放到所有 5 万页：`head_js` 默认空，只有 `build_index_page` 传；避免 dist 体积无谓 +5 MB。）

### 2.2 插入点（当前行号）

| 改动 | 文件:行（锚点） | 替换逻辑 |
|---|---|---|
| 首页 3 步卡 HTML | `build_index_page` L4196–4228；插在 L4217 `</div>` 后、L4218 `loadhint` 前 | 新增 `<section id="u1guide" class="u1guide" aria-labelledby="u1title">…</section>`；标题用 `<h2 id="u1title" data-i18n="u1.title">`；示例按钮直接 `<button data-q="泰诺">`（现有委托 L3012 自动生效） |
| CSS | `CSS = """` L1518；插在 L1644 第一个 `@media` 前 | `.u1guide{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0 6px;}` `.u1step{...}` `.u1close{...}`；`@media (max-width:719px){.u1guide{grid-template-columns:1fr;}}`；`html.u1-off #u1guide{display:none!important}` |
| 关闭逻辑 | `APP_JS` L1714（DOM refs 区，L1717 `const ctry` 附近） | `const u1=document.getElementById('u1guide'); const u1c=document.getElementById('u1close'); if(u1c){u1c.addEventListener('click',()=>{try{localStorage.setItem('u1.dismiss.v1','1');}catch(e){}; u1.hidden=true;});}` 纯原生、无依赖 |
| 防闪烁内联脚本 | `page()` L3095 签名 + head 拼接 L3133–3138；`build_index_page` L4229–4236 调用处 | `page(..., head_js=U1_HEAD_JS)`，`head_js` 插到 L3138 i18n.js 之后、`</head>` 之前 |
| 文案 key | `I18N` 三段（en L96 起 / es L~226 起 / zh L~358 起），各加 10 个 `u1.*` | 见 §2.3 |

### 2.3 文案 key（建议值；zh-Hant 按 `reports/zh-hant-i18n.md` 的台湾用词：載入→載入、快取、支援）

| key | en | es | zh | zh-Hant |
|---|---|---|---|---|
| `u1.title` | How to use it in 3 steps | Cómo funciona en 3 pasos | 三步看懂 | 三步看懂 |
| `u1.step1` | Type the name from the pack | Escribe el nombre del envase | 输入包装上的名字 | 輸入包裝上的名字 |
| `u1.step1_hint` | Brand, generic name, nickname, or a line from the pack — dose included is fine. | Marca, genérico, apodo o una línea del envase; la dosis puede ir incluida. | 商品名、通用名、俗称或包装上一行字；可连剂量一起输入。 | 商品名、通用名、俗稱或包裝上一行字；可連劑量一起輸入。 |
| `u1.step2` | See the ingredient and strength | Mira el principio activo y la concentración | 看成分和规格 | 看成分和規格 |
| `u1.step2_hint` | You always get a candidate set — never a single answer. | Siempre obtienes un conjunto de candidatos, nunca una única respuesta. | 结果永远是候选集，不保证唯一。 | 結果永遠是候選集，不保證唯一。 |
| `u1.step3` | Switch to a country | Cambia a un país | 切国家看叫法 | 切國家看叫法 |
| `u1.step3_hint` | Pick a market to see the names it is sold under there. | Elige un mercado para ver los nombres con los que se vende allí. | 选一个国家，看这个成分在当地叫什么。 | 選一個國家，看這個成分在當地叫什麼。 |
| `u1.try` | Try: | Prueba: | 试试： | 試試： |
| `u1.close` | Dismiss | Cerrar | 关闭 | 關閉 |
| `u1.aria` | Getting-started guide | Guía de inicio | 使用引导 | 使用引導 |

### 2.4 移动端 / 可访问性 / 验收

- 移动端：3 卡纵向堆叠；示例按钮换行不溢出；关闭按钮 ≥44×44 px；`@media (max-width:719px)` 验证 375 px。
- 可访问性：`<section aria-labelledby>`；关闭按钮 `aria-label=T('u1.close')`；无 JS 时引导仍显示（CSS 默认显示），关闭按钮失效但不影响使用。
- **验收**：① 首次访问（清 localStorage）→ 引导可见；② 关闭 → 立即消失 + localStorage 有 flag；③ 刷新 → 不出现；④ 清理 localStorage 后再次出现；⑤ `/es/`、`/zh/` 首页文案随语言切换（i18n.js 渲染）；⑥ 375 px 无横向溢出；⑦ 引导不改变搜索结果行为（回归 3 条查询）；⑧ dist 仅首页 HTML + 小量 CSS/JS 增长（<2 KB gzip）。

---

## 3. U2 结果顶部「各国叫法」横排

### 3.1 交互设计（v0.6.1-b）

结果区顶部（解析条下方、碰撞/俗称提示之前）新增一行 7 国 chips：

```
各国叫法  [🇺🇸 ACETAMINOPHEN] [🇬🇧 Paracetamol 500mg tablets] [🇨🇳 对乙酰氨基酚片] …
           [🇪🇸 ACETAMINOPHEN] [🇲🇽 Paracetamol 500mg tablets] [🇦🇺 …] [🇨🇦 …]
```

- 每国显示：`country name（本地化）+ 该国该成分的展示名 d（截断 ~28 字符）`，无数据 → `未收录`（灰）。
- **点击 = 切到国家视图**：`ctry.value=code; updateCtryLabel(); render();` → 复用现有国家视图（该成分在该国的全部商品名 + 无数据提示）。
- 当前已选国家高亮（`.u2chip.on`）；移动端单行横向滚动（`overflow-x:auto; -webkit-overflow-scrolling:touch`），不换行挤压。
- 仅在查询命中的成分**能唯一锚定**时显示；否则降级（见 §3.3）。
- 文案：「未收录 ≠ 该国没有这个药」的 caveat 放 chip 行末尾/`title`，避免误导（与站内「候选集」原则一致）。

### 3.2 数据算法（**不新增索引字段**，一次 IDX 扫描）

复用现有索引字段（`load_index` L3399 → entry：`k,d,c,x,xz,s,f,l,n,v,vs,u,cu,g,m,…`）：

```js
// render() 内、hits 排序后：
function anchorSubstance(hits, nicks){
  // 1) 取「最佳命中」：优先 exact/compact/prefix 的非 fuzzy 命中；否则单个别名映射
  const best = hits.find(h => ['exact','compact','prefix'].includes(h[1])) || hits[0];
  let sids = best ? ((best[2].vs && best[2].vs.length) ? best[2].vs : [best[2].v]).filter(Boolean) : [];
  if(!sids.length && nicks.length === 1 && nicks[0].v) sids = [nicks[0].v];
  // 2) 只有「单成分」才做横排；多成分/复方 → 返回 null（降级）
  if(sids.length !== 1) return null;
  return {sid: sids[0], key: best[2].k, fuzzy: best[1] === 'fuzzy'};
}
function countryNamesHTML(anchor, selected, T){
  if(!anchor) return '';
  // 3) 一次扫描：该国该成分「单成分优先、其次复方」的最佳条目
  const best = {};   // code -> entry
  for(const e of IDX){
    const sids = (e.vs && e.vs.length) ? e.vs : [e.v];
    if(!sids || sids.indexOf(anchor.sid) < 0) continue;
    const isCombo = (e.x || '').indexOf(' + ') >= 0;
    for(const c of (e.c || [])){
      const cur = best[c];
      // 排序：单成分优先 → 有品牌页优先 → n 大优先 → d 字典序
      if(!cur || (isCombo < cur.isCombo) ||
         (isCombo === cur.isCombo && (e.n || 0) > (cur.e.n || 0))){
        best[c] = {e, isCombo};
      }
    }
  }
  // 4) 渲染 7 国（顺序同首页 select：US,GB,CN,ES,MX,AU,CA —— 与现有 ctry options 一致）
  return COUNTRIES.map(c => {
    const hit = best[c];
    if(!hit) return `<button class="u2chip empty" data-u2country="${c}" title="${esc(T('u2.none_hint'))}">${esc(T('home.'+c.toLowerCase()))}<span class="sub">${esc(T('u2.none'))}</span></button>`;
    const name = hit.e.d || hit.e.k;
    const comboTag = hit.isCombo ? `<span class="tag combo">${esc(T('badge.combo'))}</span>` : '';
    return `<button class="u2chip${c===selected?' on':''}" data-u2country="${c}">` +
      `<span class="u2c">${esc(T('home.'+c.toLowerCase()))}</span>` +
      `<span class="u2n">${esc(name.length>28?name.slice(0,28)+'…':name)}</span>${comboTag}</button>`;
  }).join('');
}
```

- 显示名 `d` 是「该名字在某国的展示写法」（**不是**重新翻译），正好满足「一眼看完各国叫法」；成分中文名只在需要时用 `ingredientLabel(e)`（`xz` 机制，L1824）。
- **国家顺序**与首页 `<select>` 完全一致（L4204–4211：US,GB,CN,ES,MX,AU,CA），不引入第二套顺序。
- 点击委托：`out` 已有事件委托（L2923），加一个分支：

```js
if(t.closest('[data-u2country]')){
  const code = t.closest('[data-u2country]').getAttribute('data-u2country');
  ctry.value = code; updateCtryLabel(); render();
  try{gcEvent('country-' + code);}catch(e){}
  return;
}
```

- **性能**：`IDX` 127,085 条，单次 `for` 扫描 ≈ 3–8 ms（同现有 `inCountry` filter 量级）；只在新查询 `render()` 时算一次，折叠/加载更多（`paintResultsOnly`）不重算。可用 `LAST_ANCHOR` 缓存同一查询的 bar。

### 3.3 边界与降级（**关键**，已用现网 index 实测）

| 场景 | 处理 | 实测依据（`.tmp/ui-u-plan/u2_matrix2.json`） |
|---|---|---|
| 单成分查询（`acetaminophen`/`lipitor`/`对乙酰氨基酚`） | 正常横排：US `ACETAMINOPHEN`、GB `Paracetamol 500mg tablets`、CN `对乙酰氨基酚片`、ES `ACETAMINOPHEN`、MX `Paracetamol 500mg tablets`… | 与 `xz`/国家视图一致 |
| 品牌查询（`tylenol`、`泰诺`） | 先取最佳命中（`tylenol extra strength` → acetaminophen），再按单成分算法 | 注意：不能取 top-3 的并集（会把 `tylenol pm` 的 diphenhydramine 混进来） |
| **多成分/复方命中**（`gaviscon`、`benadryl`） | **不显示逐国叫法**（返回 null），改为一行提示「多成分/多结果，点国家查看全部」+ 链接到结果区/成分卡 | 实测会误配（如 gaviscon 的 AU 命中 NeisVac-C），必须禁止 |
| 命中含不相关成分（`benadryl` 的 US 组合 vs MX 单方） | 同上：多 sid → 降级 | 用户搜品牌时跨国同名成分不同，属 collision 语义，横排会误导 |
| 模糊命中（`fuzzyUsed`） | 仍可显示但 chip 行加注「模糊匹配」；若最佳命中只有 fuzzy → 降级 | 与解析条 `parse.match.fuzzy` 一致 |
| 昵称命中（`nicks`，无商品） | 若昵称唯一映射 sid 且 hits 为空 → 可显示（bar 用该 sid）；否则不显示 | 与 `nick.nomap_caveat` 一致 |
| `partial`（分片未就绪）/ `?legacy=1` | 与 `sameHTML` 同策略：`partial` 时先不渲染，索引就绪后再补；legacy 时正常（index.json 字段一致） | 复用现有 `partial` 机制 |
| 已选国家时 | 横排仍显示（高亮选中），点击其他国家直接切 | 与「国家视图」互补 |
| 无数据国家 | 显示「未收录」+ `title` 说明「未收录 ≠ 该国没有此药」 | 避免误导 |

### 3.4 i18n key（5 个 ×4 语言）

| key | en | es | zh | zh-Hant |
|---|---|---|---|---|
| `u2.title` | Names by country | Nombres por país | 各国叫法 | 各國叫法 |
| `u2.hint` | Same ingredient, local name — click a country to see its products. | Mismo principio, nombre local: haz clic en un país. | 同一成分在当地叫什么；点国家看该国商品 | 同一成分在當地叫什麼；點國家看該國商品 |
| `u2.none` | Not listed | Sin datos | 未收录 | 未收錄 |
| `u2.none_hint` | No product under this ingredient in this market's public data. This does not prove it is unavailable there. | Sin datos públicos para este principio en ese mercado; no prueba que no exista allí. | 公开数据里暂无该国该成分的产品；不等于该国没有这个药。 | 公開資料裡暫無該國該成分的產品；不等於該國沒有這個藥。 |
| `u2.multi` | Multiple ingredients — switch country to see the full list | Varios principios: cambia de país para ver la lista | 多成分/多结果，切国家查看全部 | 多成分/多結果，切國家查看全部 |

国家名复用现有 `home.us…home.ca`（zh-Hant 值见 `data/i18n_zh_hant.json`：美國/英國/中國/西班牙/墨西哥/澳大利亞/加拿大）。

### 3.5 验收

- **数据矩阵**（DOM 测试，固定期望，取自实测）：`acetaminophen` → US/ES/AU/CA `ACETAMINOPHEN`，GB/MX `Paracetamol 500mg tablets`，CN `对乙酰氨基酚片`；`lipitor` → 各国 `Atorvastatin…/阿托伐他汀钙片`；`gaviscon`/`benadryl` → 不出现逐国误配，显示多成分提示。
- 点击 `CN` chip → 国家视图 + `?country=CN` + 结果表为该成分中国商品；点击「未收录」国家 → 现有「该国无此名字产品」提示（不静默回退）。
- 性能：`render()` 增加 <15 ms（P50）；无新增网络请求；`index.json`/core 体积不变。
- 移动端 375 px：chip 行横向滚动、无页面横向溢出；键盘 Tab 可达、Enter 触发。
- 回归：现有 72 例三语测试 + 三条关键查询（泰诺/立普妥/替尔泊肽）+ `?legacy=1`。

---

## 4. U3 界面标签本地化（zh/en/es/zh-Hant）

### 4.1 现状盘点

| 标签 | 现状 | 缺口 |
|---|---|---|
| 状态 active/discontinued/withdrawn/unknown | **已本地化**：`I18N` `drug.status.*` + `drug.status_note.*`（en L143–148 / es L287–292 / zh L428–433）；zh-Hant 字典已有「販售中/已停售/已下市/狀態未知」 | 无（仅 A1 明细行里的 status 需要接入同一 key，见 §4.4） |
| 国家名 | `home.us…home.ca` 三语；zh-Hant 字典已有 7 国值 | TW/EU 名称等注册表接入（task-55）；U3 只定义映射位置 |
| **剂型 `form_base`** | **显示原码**：`name` 页 `g['f']` → `tablet / liquid / injection / 片剂 / comprimido …`（L3902） | 需要 `form.*` key + helper |
| **释放机制 release** | **显示原码** `IR/ER/DR/MR/none`（drug 页 L3800 列 + L3905） | 需要 `release.*` key |
| **单位 strength_unit** | **显示原码**：`mg/g/ml/%/mcg/iu/unit/ug/microgram/l/万iu/meq/mci…`（drug 页 L3782 前拼 `st`、name 页 L3903–3904） | 需要 `unit.*` 显示映射（仅非国际通用单位） |
| A1 明细（v0.5.6） | `detPanelHTML` L1937–1958 直接显示 `status`、`dosage_form`、`release` 原值 | 接入同一套 `T('status.*'/'form.*'/'release.*')` |
| `og:locale` | `page()` L3114 硬编码 3 语 `{"en":"en_US","es":"es_ES","zh":"zh_CN"}` | 加 `zh-Hant → zh_Hant/zh_TW` |

**真实数据分布（2026-10-28 现库，只读）**：
- `form_base` top：tablet 158,343 / liquid 64,804 / injection 63,872 / capsule 45,395 / topical 38,954 / powder 8,627 / pellet 7,337 / unknown 4,741 / inhalation 2,543 / stick 2,490 / kit 2,247 / suppository 1,549 / gas 986 / cloth 602 / soap 416 / swab 370 / mouthwash 325 / gum, chewing 316 / globule 290 / oil 278 / rinse 194 / jelly 193 + 长尾（含中文/西语原值如「灌肠剂」「体外诊断试剂」「comprimido」）→ **映射高频词 + 原值兜底**。
- `release`：none 385,732 / ER 15,350 / DR 8,314 / MR 191 → 只需 4 个 key。
- `strength_unit`：mg 279,300 / g 101,237 / % 26,363 / ml 18,523 / mcg 4,415 / iu 3,174 / unit 2,790 / ug 2,120 / microgram 1,398 / l 435 / 万iu 255 / kg 172 / meq 151 / u 135 / mci 101 → **只本地化非国际通用单位**（iu/unit/meq/mci/万iu/ug/microgram），mg/g/ml/%/mcg/kg 保持。
- `status`：active 357,058 / discontinued 38,424 / unknown 9,093 / withdrawn 5,012（4 词已覆盖）。

### 4.2 设计：单一数据源（I18N 体系），服务端与 JS 共用

新增 `LABEL_I18N`（与 `ABOUT_I18N` 同级），并加入 `_merge_static_i18n` 的合并列表（L1045–1052）：

```python
LABEL_I18N = {
  "en": {"form.tablet": "tablet", "form.capsule": "capsule", "form.liquid": "liquid",
         "form.injection": "injection", "form.topical": "topical", "form.powder": "powder",
         "form.suppository": "suppository", "form.inhalation": "inhalation",
         "form.pellet": "pellet", "form.stick": "stick", "form.kit": "kit",
         "form.gas": "gas", "form.unknown": "unknown",
         "release.ER": "extended-release", "release.DR": "delayed-release",
         "release.MR": "modified-release", "release.none": "—",
         "unit.iu": "IU", "unit.unit": "unit", "unit.meq": "mEq", "unit.mci": "mCi",
         "unit.ug": "mcg", "unit.microgram": "mcg", "unit.万iu": "10k IU",
         "form.other": "other"},
  "es": {...},
  "zh": {...},        # 可见值：片剂/胶囊/液体/注射剂/外用/粉末/栓剂/吸入剂/…
  "zh-Hant": {...},   # 由 data/i18n_zh_hant.json 流水线生成（片劑/膠囊/液體/注射劑/外用/粉末/栓劑/吸入劑/緩釋/延遲釋放/修飾釋放/國際單位…）
}
```

渲染 helper（服务端，供 name/drug 页用）：

```python
def label_html(prefix: str, code: str, fallback: str) -> str:
    code = (code or "").strip()
    if not code: return ""
    key = f"{prefix}.{code}"
    if key in I18N["en"]:                       # 已注册的受控词
        return f'<span data-i18n="{key}">{esc(I18N["en"][key])}</span>'
    return esc(fallback)                        # 长尾/杂项值：原样显示（数据事实）
```

JS 侧（A1 明细、未来结果行）：`T('status.'+s)` / `T('form.'+f)` / `T('release.'+r)` / `T('unit.'+u)`，**同一批 key**，无需第二张表。

### 4.3 四语映射表（建议值）

**剂型 form_base（高频 14 个 + 兜底）**

| form_base | en | es | zh | zh-Hant |
|---|---|---|---|---|
| tablet | tablet | comprimido | 片剂 | 錠劑 |
| capsule | capsule | cápsula | 胶囊 | 膠囊 |
| liquid | liquid | líquido | 液体 | 液體 |
| injection | injection | inyectable | 注射剂 | 注射劑 |
| topical | topical | tópico | 外用 | 外用 |
| powder | powder | polvo | 粉末 | 粉末 |
| suppository | suppository | supositorio | 栓剂 | 栓劑 |
| inhalation | inhalation | inhalado | 吸入剂 | 吸入劑 |
| pellet | pellet | pellet | 微丸 | 微丸 |
| stick | stick | stick | 棒剂 | 棒劑 |
| kit | kit | kit | 套装 | 套組 |
| gas | gas | gas | 气体 | 氣體 |
| unknown | unknown | desconocido | 未知 | 未知 |
| other（长尾兜底） | 原值 | 原值 | 原值 | 原值 |

> 原则：只映射「受控词 + 高频」；`form_base` 长尾（含中文/西语原值）**原样显示**，不在 UI 层做数据归一；
> 构建期输出未映射 form_base 计数（见 §4.5），供后续 ETL 清理。

**释放机制 release**：`ER` → extended-release / liberación prolongada / 缓释 / 緩釋；`DR` → delayed-release / liberación retardada / 肠溶（延迟释放）/ 延遲釋放；`MR` → modified-release / liberación modificada / 改良释放 / 修飾釋放；`none` → `—`（不显示）。

**单位 unit**：`mg/g/ml/%/mcg/kg` 保持国际写法（不改）；`iu` → IU / UI / 国际单位 / 國際單位；`unit` → unit(s) / unidad / 单位 / 單位；`meq` → mEq / meq / 毫当量 / 毫當量；`mci` → mCi；`ug`、`microgram` → mcg（显示归一，数据值不改）；`万iu` → 10k IU / 10 000 UI / 10 万 IU / 10 萬 IU。

**状态 status**：已有 4 语（见 §4.1），U3 不改语义，只接入 A1 明细。

**国家名 country**：复用 `home.*`（7 国 ×4 语已就绪）；TW/EU 上线时由注册表 `data/markets.json` 扩展名称（task-55 Phase 1/2），U3 不硬编码。

### 4.4 插入点清单（当前行号）

| # | 位置（锚点） | 改动 |
|---|---|---|
| 1 | `I18N` L96 / `LABEL_I18N` 新增在 `META_I18N` L920 附近 | 新增 4 语 `LABEL_I18N`；`_merge_static_i18n` L1048 的 tuple 加 `LABEL_I18N[lang]` |
| 2 | `name` 页 `build_name_pages` L3902：`{esc('、'.join(sorted(g['f'])))}` | 改为 `、`.join(`label_html('form', form_base, form_base)` for …)；`g['f']` 需在 `collect_name_data`（L~3840）保留原始枚举 → 目前 `s["f"].add(form_base or dosage_form)`（L3863）已按原值集合，足够 |
| 3 | `name` 页 strength/release L3903–3905 | strength：把数值与单位拆开，单位走 `label_html('unit', unit, unit)`；release 值走 `label_html('release', rel, rel)` |
| 4 | `drug` 页表格 `build_drug_pages` L3758–3805：`st = f"{sv:g} {su}"`（L3755/L3782 前）、release 列 L3800 | 同上：数值 + `<span data-i18n="unit.X">`；release 列改 helper；status 已走 `SPAN data-i18n` 不变 |
| 5 | A1 明细 JS `detPanelHTML` L1937–1958（payload 字段：[3]status [5]dosage_form [6]release） | 用 `T('status.'+r[3])`、`T('form.'+r[5])`、`T('release.'+r[6])`；缺失/未知回退原值 |
| 6 | `page()` L3114 locale 映射 | `+ "zh-Hant": "zh_Hant"`（或 `zh_TW`）；同时 `_page_meta`/`i18n_zh_hant.json` 的 `meta.*` 需补齐 |
| 7 | `data/i18n_zh_hant.json` | **重生成**：当前 203 键，运行时合并后 225 键（缺 v0.5.6 `a1.*`/`a3.*`/`meta.*`/`res.*` 等）；再用同一 OpenCC+TW_TERMS 流水线把 U3 新 key 转繁体 |
| 8 | 构建期守卫（`main()` L4799 `_merge_static_i18n` 之后） | 统计 form/release/unit 未映射值（`Counter`）打印 top N + 覆盖率；不阻塞构建（与 v0.5.5 xz 覆盖率报告同风格） |

### 4.5 验收

- 四语 key 完整性：en/es/zh 各 +≈35 key，zh-Hant 同步（`data/i18n_zh_hant.json` 键集合 == 运行时 zh 键集合，含 U3 新键；沿用 zh-Hant 报告的 6 类校验：键/空值/占位符/HTML/ASCII/简体残留）。
- 页面抽检：`/drug/atorvastatin.html` 的 Release 列显示「缓释/Extended-release/…」随语言切换；`/name/<brand>.html` 的 Form 显示本地化剂型；`/drug/<sid>.html` strength 中 `iu`→「国际单位/IU」；A1 明细行 status/form/release 四语正确。
- 回退：未映射 form_base/未知单位显示原值（不空、不报错）；构建日志有覆盖率。
- 无回归：三语抽检、`tests/trilingual/run_tests.py`、v0.5.6 A1 明细 DOM 测试。
- 体积：i18n.js 增量 <6 KB raw（≈35 key ×4 语 ×平均 12 字 ≈ 2 KB + 引号/JSON；远小于索引变化）。

---

## 5. 风险与决策点

| # | 风险 | 说明与建议 |
|---|---|---|
| R1 | **并行修改冲突（最高）** | `build.py` 正被 v0.6.1 其他项（A2/A4/B8/B10/B11）、`task-55` 注册表接入、`zh-Hant P1` 并行改。U1/U2/U3 必须**串行**；建议先做 U3（字典）→ U1（HTML/CSS）→ U2（JS 核心），各自独立小版本；patch 前 rebase 到最新并将快照行号改锚点 |
| R2 | **U2 语义误导** | 实测「结果命中多个成分」时（gaviscon/benadryl/tylenol 多结果）朴素并集算法会把不相关产品当成「该国叫法」（如 gaviscon→NeisVac-C）。**必须**按 §3.3 单成分锚定 + 多成分降级 + 「未收录≠没有」文案；这是 U2 的第一验收项 |
| R3 | U2 性能/体积 | 单次 IDX 扫描（127k）≈3–8 ms，需实测 P50/P95；不新增字段/请求；`partial`/`legacy` 路径都要跑 |
| R4 | U3 form_base 长尾 | 60+ 值含中/西/杂项（pellet/stick/kit/gas/soap/灌肠剂/comprimido…）：只映射高频 + 原值兜底 + 构建期覆盖率日志；**不在 UI 做数据归一**（归一属 ETL 任务） |
| R5 | zh-Hant 字典漂移 | 现有 `data/i18n_zh_hant.json` 203 键 vs 运行时 225 键（缺 v0.5.6 新增）；zh-Hant P1 前必须重生成，U3 新键走同一流水线，否则回退 en/zh 导致四语不一致 |
| R6 | U1 打扰/CLS | 首次展示 + 可关闭 + localStorage 记住；`html.u1-off` 在 head 内联脚本中预置类，无闪烁；只首页加脚本（不污染 5 万页）；无 localStorage 环境默认显示 |
| R7 | 移动端 | U2 横滚不能撑破页面（`overflow-x:auto` + `min-width:0`）；U1 3 卡堆叠；U3 繁中长词（已下市/國際單位）在 375 px 表格不溢出 |
| R8 | 文案一致性 | U1/U2 新 key 必须同步 4 语；zh-Hant 用台湾用词（載入/快取/支援/販售中/已下市/國際單位），参考 `reports/zh-hant-i18n.md` |
| R9 | 发布纪律 | 每项独立 CHANGELOG + build 到 `== done ==` + publish + smoke；同时间一个 build/publish；失败回滚按 `DEPLOY.md` |
| R10 | 可访问性 | U2 用 `<button>`（非 div），`aria-pressed`/高亮；U1 关闭按钮 aria-label；键盘 Tab/Enter；对比度与既有 notice 一致 |

---

## 6. 版本/顺序/工作量/验收清单

| 顺序 | 内容 | 依赖 | 工作量 | 版本建议 |
|---|---|---|---|---|
| 1 | **U3** LABEL_I18N + 渲染 helper + zh-Hant 重生成 + 覆盖率守卫 | zh-Hant P1 字典流水线（可并行准备） | 0.5–0.8 天 | v0.6.1-a |
| 2 | **U1** 首页 3 步引导 + head 内联脚本 + CSS + 4 语文案 | U3 文案 key 就绪 | 0.5 天 | v0.6.1-b |
| 3 | **U2** 各国叫法横排 + 点击复用国家视图 + DOM/性能测试 | U3 的 `u2.*` key；U1 无强依赖 | 1–1.5 天（含测试） | v0.6.1-c |

每个版本验收清单：
- [ ] `python site/build.py` 到 `== done ==`（SITE_OUT 先跑临时目录；发布由串行 owner 执行）
- [ ] `node --check assets/app.js` / `i18n.js`；DOM 测试（U1 localStorage/关闭；U2 矩阵/点击）
- [ ] 三语 + zh-Hant 抽检（首页引导、结果横排、drug/name 页标签、A1 明细）
- [ ] 375 px / 768 px 截图无溢出；键盘可达
- [ ] 体积回归：`index.json`/core 不变，`i18n.js` 增量 <6 KB，首屏请求数不变
- [ ] `tests/trilingual/run_tests.py` 不回归；`?legacy=1` 正常
- [ ] README/About/CHANGELOG 同步（只在用户可感知时）

---

## 7. 证据文件（`.tmp/ui-u-plan/`，只读分析产物）

| 文件 | 内容 |
|---|---|
| `anchors.py` / `mech.py` / `anchors2.py` | 当前 build.py 锚点扫描（函数/行号/i18n/localStorage/CSS/事件委托/示例按钮） |
| `sections.txt` / `sections2.txt` | 关键函数原文：结果渲染（brandRowHTML/groupByIngredient/resultsHTML/detPanelHTML）、render()、drug/name 页标签、首页 body、page() head |
| `i18n_merge.py` / `i18n_diff.py` | 运行期合并 I18N key 统计（225/语言）与 `data/i18n_zh_hant.json`（203 键）差异 |
| `u3_labels.py` / `u3_existing_labels.json` | U3 现有 4 语值：status 4 词、国家名 7 国、Form/Release/Strength 标签（zh-Hant 字典抽取） |
| `labels_db.py` | U3 数据分布：form_base / release / status / strength_unit / country（只读 DB） |
| `u2_matrix.py` / `u2_matrix2.py` / `u2_matrix2.json` | U2 算法实测矩阵（单成分/品牌/多成分反例）——证明「多成分必须降级」 |

## 8. 参考
- `reports/ui-a1-b6-plan.md`（A1/A3/B6/B7 已实现方案与现有函数）
- `reports/i18n-v055.md`（xz 索引、META_I18N、静态副本机制）
- `reports/zh-hant-i18n.md`、`data/i18n_zh_hant.json`（zh-Hant 203 键与台湾用词）
- `reports/i18n-audit-20261026.md`（i18n key 完整性审计）
- `docs/谷段需求队列.md`（U 池原文）、`AGENTS.md`（并行/发布纪律）、`DEPLOY.md`
