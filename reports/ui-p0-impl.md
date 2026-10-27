# UI P0 五项实现报告

> 任务：task-21（UI P0）。依据 `docs/谷段需求队列.md`「UI 逻辑改进 P0」五条 + `reports/i18n-audit-20261026.md`。
> 改动文件：**仅 `site/build.py`**（CSS / 首页 HTML / I18N / 内嵌 APP_JS）。未改数据语义（候选集/碰撞/国家视图逻辑）、
> 未跑 git/发布、未改 `site/dist`、`data/drugs.db` 或其他跟踪文件。
> 构建：`SITE_OUT=.tmp/dist-ui`，产物目录 `.tmp/dist-ui/`；验收脚本在 `.tmp/dist-ui/_verify/`。

---

## 0. 结论（五项状态）

| # | P0 项 | 状态 | 关键实现 |
|---|---|---|---|
| 1 | 国家选择器语义 + 无匹配显式提示 | ✅ | 标签「看这个药在 X 叫什么」随选择变化；该国无该成分产品时显示警示 + 「看成分卡」×3 + 「换国家」按钮，不再静默回退各国列表 |
| 2 | 搜索解析条 | ✅ | 结果顶部显示 名称 / 剂量 / 剂型 / 匹配方式（精确·连写·前缀·包含·模糊·别名·国家视图） |
| 3 | 自动完成 top 8 | ✅ | ≥2 字、90ms debounce、top 8（名称+成分+国家标签）、↑↓/回车/Esc/点击；索引未就绪时加载完成后补算；`?q=` 深链不自动弹 |
| 4 | 结果按成分聚合 + 品牌折叠 + 加载更多 | ✅ | 按 `x`（成分）分组、组头显示品牌数；默认每组前 2 个品牌，可「展开全部品牌/折叠」；每页 25 行可见品牌，「加载更多」+25（候选池 40→200 条） |
| 5 | 移动端 <720px 卡片化 / nav 换行 / 页脚不 nowrap | ✅ | 新增首个 `@media (max-width:719px)`：表格转卡片（`data-label` 列名）、header 自适应、nav 折行、页脚折行、语言栏右移、字号调整 |

另顺带完成验收清单第 ④ 条：`?q=`/`?country=` 用 `history.replaceState` 同步到 URL（可分享），`popstate` 可前进后退。

三语文案：I18N **112 → 137 keys × en/es/zh**（新增 25 键，0 缺失）。

## 1. 改动清单（`site/build.py` file:line）

### 1.1 CSS（L412 起；移动端 L579–）

- 新组件：`.sel-label`、`.searchwrap`/`#ac`/`.ac-item`（L551–570）、`.parsebar`（L565）、
  `.grp-name/.grp-count/.grp-tags`、`.linkbtn`、`.loadmore`、`.countrymiss .cm-actions`。
- `@media (max-width:719px)`（L579）：`header .wrap{height:auto;flex-wrap:wrap}`、`nav{flex-wrap:wrap}`、
  `.logo-zh` 隐藏、`.foot-links{white-space:normal;flex-wrap:wrap}`、`table.res` 转卡片
  （`thead` 隐藏、`tr/td{display:block}`、`td[data-label]:before{content:attr(data-label)}`、
  `td.c-dose{white-space:normal}`、`.grp` 组头卡片样式）。

### 1.2 首页 HTML（`build_index_page`，L2076–2086）

- 搜索框外包 `.searchwrap`，新增 `<div id="ac" role="listbox">`（L2078–2081）。
- 国家选择器前加 `<label class="sel-label" for="country" id="ctrylabel" data-i18n="home.country_label">`
  （L2082–2083）。

### 1.3 I18N 新键（en L203–225 / es L333–355 / zh L447–469）

`home.country_label`、`home.country_label_sel`、`country.missing`、`country.missing_note`、
`country.open_card`、`country.change`、`parse.label/name/dose/form/match`、
`parse.match.{exact,compact,prefix,contains,fuzzy,nickname,country,none}`、`ac.suggestions`、
`res.brands_noun`、`res.show_brands`、`res.fold`、`res.load_more`、`res.loaded_all`。

### 1.4 内嵌 APP_JS

| 功能 | 位置 |
|---|---|
| 品牌行 + `data-label`（移动端卡片列名） | `rowHTML` L735–756、`brandRowHTML` L742–756 |
| 成分聚合 / 折叠 / 加载更多 | `RES_PAGE`/`RES_LIMIT`/`RES_EXPANDED`/`RES_GROUPS` L757–771、`groupByIngredient` L761、`resultsHTML` L772、`paintResultsOnly`；结果容器 `#reswrap` |
| 解析条 | `parseQuery` L830、`parseBarHTML` L837；`render()` 内计算名称/剂量/剂型/匹配方式并置顶输出（L952 起） |
| 自动完成 | `acCompute` L869、`acPaint`、`acUpdate`（90ms debounce + 加载中 AC_WANT 补算）、`acSelect`；键盘/点击绑定 L1230 起 |
| 国家语义 + 无匹配提示 | `updateCtryLabel` L913、`syncURL` L928、`render()` 内 `countryMiss` 分支（提示+成分卡+换国家）、ARTG 触发条件改为 `(!display.length && !countryMiss)` |
| 事件委托 | L1300–1330：`data-retry` / `data-loadmore` / `data-gi`(折叠) / `data-clearcountry` |
| URL 状态 | `syncURL`（300ms debounce `replaceState`）+ `popstate` 恢复 q/country |
| 候选池 | `shown = hits.slice(0, 200)`（原 40），`inCountry.slice(0, 200)`（原 40） |

三语音频：`Tr()/T()` 全部受控文案；无新增硬编码。

## 2. 验收证据

```powershell
$py  = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$node= 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$env:SITE_OUT='D:\同种药物商品名剂量对应网站\.tmp\dist-ui'
& $py -X utf8 site/build.py          # == done ==，exit 0
& $node --check .tmp\dist-ui\assets\app.js    # exit 0
& $node --check .tmp\dist-ui\assets\i18n.js   # exit 0
& $node --max-old-space-size=4096 .tmp\dist-ui\_verify\ui-p0.test.mjs   # 9/9 PASS
& $py -X utf8 .tmp\dist-ui\_verify\static_check.py                      # 39/39 PASS
```

- 构建：`drug pages 12377 / name pages 17861 / index.json 34.8 MB / total 158.5 MB`，产物 30,258 个文件；
  `site/dist` 未被改动（app.js mtime 仍为 2026/10/26 20:46）。
  > 注：本轮期间其他任务两次更新了 `data/drugs.db`（drug 页 12,864→12,377、sitemap 30,738→30,244），
  > 不是本任务改动；索引仍 126,915 键、aliases 422 / confused 44 / ARTG 34,594。
- **ui-p0.test.mjs 9/9**（Node vm + 真实索引 + DOM 桩）：
  1 解析条名称/剂量/剂型/匹配方式；2 国家标签随选择变化；3 成分聚合+折叠+加载更多
  （aspirin 初始 25 行 → 加载更多 50 行）；4 国家无匹配显式提示（样本 `chloroxylenol` @ CN：
  出现 `countrymiss`、无分组表、`data-clearcountry` 清除后消失）；5 国家视图命中不回归；
  6 自动完成 top8+国家标签+↓/回车选中；7 URL q/country 同步 + popstate 恢复；
  8 既有语义回归（碰撞徽标/别名/易混淆/同成分/ARTG）；9 `?q=` 深链不自动弹建议。
- **static_check.py 39/39**：CSS 媒体查询/卡片化/nav/页脚、首页骨架（`#q`+`#ac`+`#ctrylabel`+hreflang）、
  APP 逻辑点、I18N 137×3 一致且 25 个新键三语齐全、产物完整性（≥24k 文件、0 字节=0、index≥5MB、drug/name/sitemap/404）。
- **HTTP 冒烟**（临时 `python -m http.server 8793`）：`/`、`/es/`、`/zh/`、`drug/ibuprofen.html` 均 200，
  三入口含 `#ctrylabel`+`#ac` 且 i18n.js 单次；`assets/app.js` 33,015 B、`style.css` 7,623 B 可访问。
- **Chrome headless 视口截图/CDP 测量**（脚本在 `%TEMP%\ui-cdp-shots.mjs`，视口真实 375/768/1200）：

  | 页面 | innerWidth | scrollWidth | 横向溢出 | 观察 |
  |---|---:|---:|---|---|
  | 375px `?q=aspirin` | 375 | 375 | 否 | 17 个成分组 / 25 张品牌卡片 / nav 折行=true |
  | 784px `?q=aspirin` | 784 | 784 | 否 | 同上 |
  | 1200px `?q=aspirin` | 1200 | 1200 | 否 | 桌面表格，nav 单行 |
  | 375px `/es/?q=Lipitor&country=US` | 375 | 375 | 否 | 西语界面、3 组/5 卡 |
  | 375px `chloroxylenol@CN` | 375 | 375 | 否 | `countryMiss=true`、无回退分组 |
  | 375px `/zh/` 首页 | 375 | 375 | 否 | nav 折行、页脚折行 |

  > 截图文件曾放在 `.tmp/dist-ui/_shots/`，被最后一次全量重建（仅移动端 `.c-dose` 换行 1 行 CSS 修正）
  > 随产物目录清空；按 Lead 指示不再重拍，上表为重建前同一 JS/HTML 版本的 CDP 实测数据。

## 3. 已知问题 / 风险（P0 边界内）

1. **截图未最终重建后重拍**：最后一次重建只改了移动端 `.c-dose{white-space:normal}`（防止长剂量串横向顶出卡片），
   不改变布局宽度与媒体查询；如需留档可重跑 `%TEMP%\ui-cdp-shots.mjs`（需先起 8793 服务）。
2. **解析条剂型识别是词表匹配**（中/英常见剂型词），未覆盖全部剂型写法；剂型词仍保留在名称中参与匹配
   （不改变既有检索语义，带剂型的查询命中率与改前一致）。
3. **自动完成扫描全表**（每次输入去抖后扫 126,915 条，上限 500 条候选）：桌面 ~100ms、移动端更慢；
   索引 P2 分片/搜索库接入后应改为分片内建议。
4. **候选池 200 条上限**：极端查询（如 2 字中文）超出的候选仍不展示；分页只在候选池内翻页。
5. **国家无匹配的「看成分卡」取前 3 个成分**（与旧国家视图同源 sids），不保证覆盖全部命中成分。
6. 移动端卡片化以 `data-label` 显示列名；ARTG 表、同成分表同样生效（已补 data-label）。
7. URL 同步用 `replaceState`（不新增历史项）；浏览器前进/后退只在有历史项时触发恢复。

## 4. 回滚方法

| 层次 | 操作 |
|---|---|
| 源码回滚 | `git checkout -- site/build.py` 后重新构建/发布（由 Lead 执行；本子智能体未跑 git） |
| 特性级回滚 | ① 移动端样式：删除 `@media (max-width:719px)` 整段（L579 起）即恢复旧布局；② 国家无匹配：把 `render()` 中 `countryMiss` 分支删掉、恢复 `if(inCountry.length) display=...` 静默回退；③ 自动完成：不渲染 `#ac`（app.js 的 `acUpdate()` 调用可注释）；④ 聚合/加载更多：把 `resultsTableHTML()` 换回原 `capped.map(rowHTML)` 表；⑤ 解析条：不输出 `parseBarHTML(...)` |
| 发布后回滚 | gh-pages revert 上一提交（改动集中在 `assets/app.js`、`assets/style.css`、3 个 `index.html`；数据文件未变） |

## 5. 产物

- `site/build.py`：CSS + 首页骨架 + I18N 25 键 ×3 + APP_JS（解析条/自动完成/聚合折叠/加载更多/国家提示/URL）。
- `.tmp/dist-ui/`：SITE_OUT 构建产物（30,258 个文件）；`.tmp/dist-ui/_verify/{ui-p0.test.mjs,static_check.py}` 可复跑验收。
- `reports/ui-p0-impl.md`：本报告。
