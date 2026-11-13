# T13：次级页筛选与计数文案（task-9，v0.11.7 第一批）

> 工位：**site-ui** ｜ 时间：2026-11-14（北京谷段·第二批）｜ 任务：`task-9`（用户评审 D1–D7，triage §2）
> 状态：**实现 + 自验完成**（与 T11 同落 `.tmp/dist-v0117`，本报告只写 T13 这批的改动）。
> 未 commit、未发布、未写 `site/dist`、未改 `data/drugs.db`、未改 `collision` 语义；写作用域：`site/build.py` + 本报告。
> **不改结果页交互模型**（T11 另做）：本批在结果页只加了「数据截止」小字，没有任何新控件。

## 0. 结论先行（逐条 D1–D7）

| # | 要求 | 落地 | 证据（浏览器实测，`?lang=zh`） |
|---|---|---|---|
| **D1** | 成分页加「市场 / 单方·复方 / 规格」筛选，`?mk=` 可分享 | 清单顶部新增 `<details class="listfilters">`（桌面常显、手机默认收起）+ 12 个市场 chip + 3 个「成分类型」chip + 规格搜索框；JS 只做渐进增强，无 JS 时市场 chip 是锚点、列表全可见 | `main` 内 `<button>` **0 → 4**；市场 chip 12 / 类型 chip 3 / `input#lf-spec` 1；点 `CN` → 可见 17 行、只留 CN 块；选「含此成分的复方」→ 40 行且 `data-combo` 全为 1；搜 `500` → 49 行全部含 500；`?mk=CN` / `#mk-CN` 进页自动选中 |
| **D2** | 「＋218」「＋6」改成可点击 | **`+218` 的可见文案保持 `+218`**（atc4-ui 报它是既有绿能力；改成「查看其余 218 项」会让 390 首屏条目掉 0.5 → 说清楚的那句改放 `title` / `aria-label`，功能与无障碍都不丢）；市场尾巴的裸 `+6` → `<details class="mkx-more">另 6 个市场</details>`，内含其余市场锚点 | `.mkx-more` **52 处**、旧式裸 `+N` **0 处**；`label.m-more` **115** + `title`/`aria-label` 带「查看其余 218 项」、`.m-rest` **115** 全部保留（绿断言未受影响） |
| **D3** | 「12 个规格」口径 | 块头改 `N 条记录 · 展示 X 个，共 Y 个`（X=本块当前展示行数，Y=该国**已公开**规格数；未公开规格另有独立折叠段，不混进来） | `CN 4,299 条记录 · 展示 17 个，共 130 个`（改前 `… · 130 个规格`）；筛选后 X 跟着变（`data-shown` + `data-i18n-tpl`，切语言不打架） |
| **D4** | 分类页页内搜索 + 子类筛选 | 新增 `#catfinder`：搜索框 + 5 个 ATC4 子类 chip + 命中计数；命中落在折叠区自动展开；盐型/状态本来就在 `<details>` 里 | 187 个成分：搜 `ibuprof` → **1/187**；子类 `M01A` → **63/187** 且每行确有该前缀；`main` 内 input **0 → 1** |
| **D5** | 说明移进帮助区 | 「市场口径」「缺名标记规则」两句从正文移入 `<details class="cat-help">怎么看这份清单</details>`；红线句 `cat.disclaimer` 仍常显 | 正文里 `atc-mk-hint` **0 处**，`.cat-help` 1 个且默认收起 |
| **D6** | 覆盖页「产品数」→「记录数」 | `coverage.col.products` 五语改值（zh 记录数 / zh-Hant 紀錄數 / en Records / es Registros / fr Enregistrements） | `#covtable` 表头（zh）：`市场 / 记录数 / 成分已映射 / 规格覆盖 / 最后同步 / 数据截止 / 已知缺口` |
| **D7** | 来源日期 / 缺失字段 / 状态含义带到结果里 | ① 成分页每国块头新增 `.mkmeta`：`来源 … · 数据截止 … · 部分记录未公开规格 · 含状态未知记录（不等于在售）`（只在确有该情况时才出后两句）；② 结果行/身份卡懒加载 `data/sources.json`（1.1 KB，12 个市场）后补 `.src-asof` 小字 | 成分页 `.mkmeta` **11** 处（例：`来源 openFDA NDC Directory · 数据截止 2026-10-23`）；`data/sources.json` 1129 B / 12 市场；结果页见 §2.2 |

## 1. 改了什么（`site/build.py`）

1. **成分页清单（`_drug_list_html`）**
   - 新增筛选条 `details.listfilters`（`data-mk-filter` 市场、`data-seg-filter` 单/复方、`#lf-spec` 规格搜索、`#lf-status` 状态行、`#lf-none` 空提示）。
   - 块头计数改成 `drug.spec_count` 模板（`data-total` / `data-shown` / `data-i18n-tpl`）。
   - 新增块头 `.mkmeta`（来源 / 数据截止 / 未公开规格 / 状态未知），数据由 `build_drug_pages` 汇总（`p.source_id` + `source.data_as_of`）。
   - `label.m-more` 文案改「查看其余 N 项」；市场尾巴 `+N` 改 `details.mkx-more`。
   - `_render_segment` 返回 `(html, 展示行数)`，供块头计数用。
2. **i18n.js**
   - 新增 `[data-i18n-tpl]` 支持（带数字的短句走模板，省掉四语块体积：实测 12,438 个成分页少背 ≈9 MiB）。
   - `initListView()` 的计数更新改用同一模板；新增 `initListFilters()`（市场/类型/规格三合一筛选 + `?mk=` 分享）、`initCatFinder()`（分类页搜索/子类）、`initSourceMeta()`（结果行/身份卡补「数据截止」，body 级观察器 + rAF 节流，不改结果页交互）。
3. **分类页（`build_category_pages`）**：`#catfinder` + `.cat-help` 折叠 + ATC4 子类 chip（按命中成员数排序，≤12 个）。
4. **覆盖页**：`coverage.col.products` 五语改值（放在 `UI_I18N`，这样 zh-Hant 也能覆盖 `data/i18n_zh_hant.json` 的旧值）。
5. **新数据资产**：`data/sources.json`（国家 → 来源名 + 数据截止），1129 B。
6. **样式**：`.listfilters/.lf-*`、`.mkmeta`、`.mkx-more`、`.catfinder`、`.cat-help`、`.src-asof`，以及 `[hidden]` 兜底（`.mkrow/.mkblock/.mkseg/.atcmembers li`）。
7. **新增 i18n 键**（五语齐）：`lf.market / lf.kind / lf.all / lf.title / lf.all_kinds / lf.spec / lf.spec_ph / lf.none / lf.count`、`drug.more_names`、`drug.mkx_more`、`drug.spec_count`、`mkmeta.source / mkmeta.asof / mkmeta.undisclosed / mkmeta.unknown`、`cat.help / cat.subcat / cat.search_ph / cat.search_none`，以及改写 `coverage.col.products`。

## 2. 验收

### 2.1 数字

| 项 | 改前（v0.11.6） | 改后 | 门槛 |
|---|---:|---:|---|
| `/drug/acetaminophen.html` | 238,208 B | **259,876 B（253.8 KiB，占 260 KiB 的 99.1%）** | ≤260 KiB ✅（**余量只剩 2.3 KiB**，后续再加内容要先瘦身） |
| `/cat/analgesics.html` | 173,738 B | **174,867 B（170.8 KiB）** | ≤200 KiB ✅ |
| `/coverage.html` | 24,679 B | 24,666 B（-13） | — |
| `data/idx/core.json` raw | 46,295,974 | **46,295,974（未变）** | ≤48 MB ✅ |
| dist 总字节 | 992,410,495（946.4 MiB） | **1,018,677,317（971.5 MiB，+2.6%）** | 无硬门槛（成分页 +1.7 KB/页：筛选条 chip + 块头来源行 + 计数模板） |
| 文件数 / HTML / sitemap | 125,515 / 125,290 / 66,300 | **125,516（+`data/sources.json`）/ 125,290 / 66,300** | HTML 不退化 ✅ |
| **首屏条目（`.mkrow`，同口径实测）** | 1440 = **8.5** / 390 = **5** | **8.5 / 5（完全不变）** | 不得退化 >5% ✅ |
| 成分页平均 | 12.8 KB | **≈14.6 KB** | — |

### 2.2 选择器 / 属性保留（atc4-ui 守卫依赖，逐项核过）

`#country` 与 `#src` 各 **13 个选项**不变；`.idcard`（客户端渲染）、`.ctry-panel`、`.c-dose`、`.form-tag`、`.mkrow`、`.mkblock`、`.nolang-badge`、`.formchips`、`main .notice`、`[data-combo]`、`[data-spec-kind]`、`#covtable`、`ul.atcmembers li` 全部原样；`main .card` 仍是名字页的成分卡（本批未动）。**新增**的类名都是新的（`.listfilters/.lf-*/.mkmeta/.mkx-more/.catfinder/.cat-help/.src-asof`）。

### 2.3 无 JS 仍可读

- 成分页：筛选条是 `<details open>`（无 JS 展开、市场 chip 是锚点），清单全量可见。
- 分类页：列表全量可见；搜索框/子类 chip 无 JS 时是纯装饰（不隐藏任何条目）。
- 结果页：`.src-asof` 只是追加小字，无 JS 时不显示（功能不受影响）。

### 2.4 横向溢出

1440 / 390 实测 `document.documentElement.scrollWidth == innerWidth`（无溢出）；手机端筛选条默认收起（`<details>` 关闭），首屏不被吃。

## 3. 取舍与已知缺口

1. **手机端筛选条默认收起**：筛选入口是 sticky 条里的一个 chip（与「Forms」同高 32 px），展开是**浮层**（absolute），不把正文往下推 —— 桌面/手机首屏条目实测 **1440 = 8.5、390 = 5，与改前完全一致**。390 展开后浮层高约 194 px，收起时零成本。
2. **块头「共 Y 个」用「已公开规格数」**（130），不把未公开规格算进去（未公开另有独立折叠段），与改前 `130 个规格` 口径一致。
3. **`.mkmeta` 在 ≤767px 隐藏**（避免 390 首屏条目掉 0.5），桌面端 `nowrap + 省略号`（全文进 `title`）；手机上「来源/截止」仍可从覆盖页看。
4. **D7 只覆盖「组级」信息**：结果行给的是该行所涉市场里**最新**的一个数据截止日（只认 `YYYY-MM-DD` 形式的真日期，`live` 这类 note 不写），不逐产品列；逐条来源仍在数据包 `datapackage.json`。
5. **分类页子类是 ATC4 前 4 位**（N02B / M01A），不带类名文本（类名四语需要 4 × 名称块，体积不划算）；`/atc/<code>.html` 里仍能看到类名。
6. **dist 体积 +2%**：筛选条（12 chip）与每国来源行是主要成本；若后续要紧体积，先把 `.mkmeta` 的「来源名」改成只保留首个来源的短名。

## 4. 复跑命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
$env:SITE_OUT='.tmp/dist-v0117'; & $py site/build.py            # == done ==
& $py deploy/ci_checks.py --fast --dist .tmp/dist-v0117          # 期望 FAIL 0
& $py deploy/i18n_check.py                                       # 期望 FAIL 0 / WARN 2（未新增）
& $py .tmp/t13_verify.py                                         # 本报告的静态断言
& $py -m http.server 8013 --directory .tmp/dist-v0117            # 浏览器复查 D1/D4/D6/D7
```
