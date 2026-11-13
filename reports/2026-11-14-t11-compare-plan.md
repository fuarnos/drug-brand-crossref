# T11 对照流程方案与现状梳理（v0.11.7 输入，只读）

> 任务：task-10。对象：用户评审三件事里的第二件（B1 三步流程 / B2 目标市场常驻 / B3 概念拆分，triage §2）。
> 只读：不改 `site/build.py`、不构建、不写 `site/dist`、不写库、不 commit。
> 基线：v0.11.6 线上产物（`site/dist`，构建于 2026-11-14 09:53–09:54）+ 工作区源码。
> **行号会漂**，本文一律给 **grep 锚点**；引用的实测数字都带命令口径。
> 取样时刻：`site/build.py` 14,921 行（10:55），**T13 正在并行落实现**（已看到 `initListFilters` 的成分页市场/单方复方/规格筛选）→ 凡涉及成分页的复用点，以 §6.4 的「与 T13 的边界」为准。

---

## 0. 结论先行

1. **三步里第 2 步是空的、第 3 步的入口在结果下面、连三步指引条在结果页都被藏了**。身份卡（`identityCardHTML`）只有「看成分页 / 复制通用名 / 报告」三个动作，**没有「确认这条」**；目标/来源市场面板 `#ctrydetails` 在 DOM 上排在 `#out`（结果表）**之后**，结果页要滚过 20 行才够得着（实测：`site/dist/index.html` 里 `searchwrap` 偏移 65,299、`#ctrydetails` 偏移 66,260，中间夹着 `#identity` + `#out`）。
2. **`?country=` 现在不是筛选，是整表替换**：选了国家就把候选集换成「该国该成分的全部商品名」（最多 200 条，`render()` 里 `countryView`）。这正是「点一下国家，候选集就没了」的由来——**它已经踩到底线①**（看起来像答案）。T11 要改成「筛选 + 对照块」，并且**只在 `?pick=` 存在时**启用新行为，老深链 100% 不变。
3. **B3 的文案 bug 是逐字可指的**：`res.src_label` 中文写「来源市场（**只看这些登记库的记录**）」——把「来源市场」和「登记库来源」塞进同一句；而 `?src=` 实际筛的是**市场**（`hits.filter(h => h.c.includes(src))`），跟登记库（openFDA/dm+d/ARTG…）无关。拆分方案见 §4。
4. **B2 要「常驻」，但不能再花首屏高度**。现查结果页首屏条目 1440=**4.5**、390=**1.0**（结果页阈值是 ≥5），已经**双双不达标**。方案：把选择器**并进现有 sticky 搜索条的一行**（`#meta` 同行 chips），**首屏高度净增 0**（1440）/ **0～24px**（390）；做成独立面板（+52px）会把 1440 压到 4.2、390 压到 0.8 → **不建议**。见 §3。
5. **「逐项相同/不同」的成分与剂型数据不在索引里**：`core.json` 有 `c/x/xz/s/f/fs/n/v/vs/atc/l/u/cu/db` 等列，**没有 per-market 成分/剂型**（`fs`/`s` 是「该名字跨市场并集」）。两条路：
   - **A（推荐）**：结果页只做「名称 / 规格 / 释放 / 状态」对照（明细桶 `detail-*.json` 已有），成分+剂型对照**落到成分页**（`.mkrow` 已有 `data-form` / `data-spec` / `data-combo`，只缺 `data-release` 与清单行的 `data-others`，各补 1 行）。
   - B：往索引加 per-market 摘要 → 223,663 个「key×市场」对 × 20–30 B ≈ **+4.5–6.7 MB**，而发布护栏余量只有 **3.7 MB**（`core.json` 现 46,295,974 B / 上限 50 MB）→ **不可行**。
6. **atc4-ui 的 37 条断言**：1 条按设计失效（`P3` 页脚版本），4 条有风险（`A6` + `D5`×3 依赖「候选集」文案且要求在**首 4000 字符**内），3 条**不许动**（`A1/A2/A3` 依赖 `.c-dose` 内容与 `#reswrap table.res.rows`）。见 §6.2。

---

## 1. 现状定位（grep 锚点，不写行号）

### 1.1 结果页 / 身份卡 / 筛选器

| 符号 | 作用 | grep 锚点 | 关键行为 |
|---|---|---|---|
| `flatRowHTML` | 结果页默认行（扁平表） | `function flatRowHTML` | 4 列：剂量 / 品牌 / 市场 / 详情；`.c-dose` 由 `specPairsOf` 出「剂型 + 规格」对 |
| `brandRowHTML` | ATC / 大类结果的分组表行 | `function brandRowHTML` | 同类 `.c-dose`，外层 `tr.grp` 分组 |
| `flatTableHTML` | 扁平表壳 | `function flatTableHTML` | `<table class="res rows">`，表头键 `col.dose` / `col.brand` / `res.col_market` / `res.details` |
| `identityCardHTML` | 身份卡（第一步候选摘要） | `function identityCardHTML` | 标题 `res.identity_title` =「candidate 1 of {n}」；动作只有 `res.action_drug` / `res.action_copy` / `report.cta` |
| `formLabelOf` | 剂型标签 | `function formLabelOf` | T10 起 `f==='multi'` → `matrix.multi_form` |
| `specPairsOf` | `fs` 紧凑串 → 剂型×规格对 | `function specPairsOf` | 3 组上限，超出给 `+N 多剂型` |
| `countryNamesHTML` | **已有的「国家/地区叫法」chips（第 3 步原型）** | `function countryNamesHTML` | 仅当结果能锚定**单一成分**（`anchorSubstance`）才出；点 chip → 设 `#country` + `render()` |
| `U2_COUNTRIES` / `u2Order` | 该 chips 的国家清单与排序 | `const U2_COUNTRIES` | 9 个市场硬编码（US GB CN ES MX AU CA TW SG），**不含 HK/EU/FR** |
| `anchorSubstance` | 单成分锚定判定 | `function anchorSubstance` | 多成分/模糊一律不出 chips |
| `render()` | 搜索主渲染 | `function render(){` | 内含 `const c = ctry.value` → `countryView` **整表替换** |
| `syncURL` | URL 状态写入 | `function syncURL` | 写 `q` / `country` / `src`（300 ms 防抖，`replaceState`） |
| `popstate` | 前进后退恢复 | `addEventListener('popstate'` | 恢复 `q` / `country` / `src` 后重渲染 |
| `updateCtryLabel` | 市场面板 summary 文案 | `function updateCtryLabel` | 选了国家就把 `closest('details')` 打开 → **但 `#ctrydetails` 是 `<div>`，`closest('details')` 恒为 null，这段是死代码** |
| `updateSrcNote` | 来源市场状态行 | `function updateSrcNote` | `#srcnote` 只在选了 `?src=` 时出现 |

**两处直接影响 B1 的现查事实**：

1. **三步指引条在结果页被 CSS 藏了**：`html.has-q .flow3{display:none}`（grep `.has-q .flow3`）→ 首页那条「1 输入 → 2 确认这条 → 3 选目标市场」的 `<ol class="flow3">`，**恰好在用户进入结果页时消失**。第 2/3 步在结果页没有任何路标。
2. **底线①那句话在结果页仍可见**：`.candidate-line`（`home.candidate`：「结果永远是候选集，不是唯一答案。」）**没有** has-q 隐藏规则，且 DOM 在搜索框上方 → 它是 atc4-ui `A6`/`D5` 断言的落点。**T11 不许把它藏掉**，建议在 `#pickbar` 里再复述一次（新增，不删原件）。

### 1.2 市场面板与 DOM 顺序（现查片段）

静态模板（`site/build.py` 首页模板，grep `<div id="srcnote"` 一带）：

```html
<div class="searchwrap">
  <div class="searchbar">…<input id="q">…<div id="ac"></div></div>
  <p class="sub search-status" id="meta" role="status"></p>
</div>
<div id="srcnote" class="srcnote" hidden></div>
<div id="identity"></div>
<div id="out"></div>                                  ← 结果表由 JS 注入 #reswrap
<div class="mf-details ctry-visible ctry-details" id="ctrydetails" data-always-open="1">
  <div class="ctry-panel">
    <label for="country" data-i18n="home.country_label">Target market: show the names used there (optional)</label>
    <select id="country">…12 个市场（US GB CN ES MX AU CA TW HK SG EU FR）…</select>
    <label for="src" data-i18n="res.src_label">Source market (only records from):</label>
    <select id="src">…同 12 个市场…</select>
  </div>
</div>
```

实测（`site/dist/index.html`，145,919 B）：

- `class="searchwrap"` 偏移 **65,299**；`id="ctrydetails"` 偏移 **66,260**；`id="meta"` 在前、`#srcnote`/`#identity`/`#out` 居中 → **市场面板在结果之后**。
- `#ctrydetails` 是 **`<div>`**，不是 `<details>`；`ctry-visible` / `ctry-details` / `data-always-open` 三个钩子**全站只出现这一次**（无 CSS、无 JS 引用）→ 目前是**惰性标记**。
- 但 CSS 里有一条 `.has-q .searchwrap .ctry-details{margin-top:4px}`（grep `.has-q .searchwrap .ctry-details`）→ **要求面板在 `.searchwrap` 内**，而 DOM 里不在 → **死规则**。也就是说「把市场面板搬进 sticky 搜索条」这个设计**当初写进了 CSS，没写进 DOM/JS**。T11 把它补完即可，不用另造机制。
- 桌面 CSS 已按双列排（grep `#ctrydetails .ctry-panel{display:grid`，≥1024px：左目标市场、右来源市场）；<1024（含 390）上下堆叠。

### 1.3 当前 URL 参数语义表

| 参数 | 现状语义 | 谁写 | 谁读 | 是否深链 |
|---|---|---|---|---|
| `q` | 查询词 | `syncURL` | `render()` / `popstate` | 是（`/index.html?q=Tylenol`） |
| `country` | **目标市场**：把候选集**整表替换**成「该国该成分的全部商品名」 | `syncURL`、`data-u2country` 点击、`data-clearcountry` | `#country` → `render()` | 是 |
| `src` | **来源市场**：把候选集**过滤**成「在这些市场有记录」的条目 | `syncURL` | `#src` → `render()` | 是 |
| `lang` | 界面语言 | i18n 内联脚本 | i18n | 是 |
| `view` | 成分页视图（`table`=矩阵 / 默认清单） | — | `initListView` | 是 |
| `mk`（旧别名 `mcountry`） | 成分页**矩阵列**（逗号分隔，另存 `localStorage['dsh.matrix.mk']`）；**T13 起**同一参数也作为清单「只看某市场块」的初值（`#mk-CN` 锚点同状态） | 成分页筛选器 JS | 成分页 JS | 是 |
| `page` | 厂商页分页 | — | 厂商页 JS | 是 |
| `legacy` | `=1` 走旧搜索路径 | — | `render()` | 是（调试用） |

**结论**：`country` / `src` 两个名字都在讲「市场」，但一个是「看哪里」，一个是「记录来自哪里」；而页面上把 `src` 解释成「登记库」——**三个概念（目标市场 / 记录市场 / 登记库）挤在两个参数、两个下拉里**。

### 1.4 localStorage 现状（T11 可复用/需新增）

| 键 | 作用 | 出处锚点 |
|---|---|---|
| `lang` | 界面语言偏好 | `localStorage.setItem('lang'` |
| `u1.dismiss.v1` | 三步引导关闭记忆 | `u1.dismiss.v1` |
| `dsh.density` | 紧凑/舒适行距 | `dsh.density` |
| `dsh.showOrig` | 是否显示来源原文 | `dsh.showOrig` |
| `dsh.matrix.mk` | 成分页矩阵列选择 | `dsh.matrix.mk` |

→ T11 建议新增 1 个键：`dsh.cmp.v1`（记住上次的目标市场，**不记**用户确认过的具体候选，避免"你以为我记得你手里那条"的误导）。

---

## 2. 三步流程方案（B1）

### 2.1 总原则

- **三步全在同一页**（结果页），不跳页、不加向导；URL 承载全部状态，可分享、可后退。
- **底线①**：第 2 步的措辞永远是「你手里这条疑似是**这条候选**」，第 3 步永远是「**该市场里还有 N 条候选**」。**没有"答案"，没有"就是它"**。
- 红线：不判断能否互换、不给替代建议、不做剂量换算；「相同/不同」只是**字段字面比较**。

### 2.2 状态与参数（新增 2 个，旧的全不动）

| 参数 | 语义 | 例 |
|---|---|---|
| `q` | 输入（不变） | `?q=tylenol+extra+strength` |
| **`pick`** | 第 2 步确认的候选（= `key_id`） | `&pick=tylenol-extra-strength` |
| **`pmk`** | 该候选**在哪个市场**的那张包装（记录市场） | `&pmk=US` |
| `country` | 第 3 步目标市场（**语义不变**，行为新增） | `&country=CN` |
| `src` | 记录市场筛选（下沉到高级筛选，**语义不变**） | `&src=GB` |

**向后兼容策略（关键）**：
- **无 `pick` 时，`country` 保持 v0.11.6 的旧行为**（整表替换成该国该成分名字）。所有历史深链、以及 atc4-ui 的 `data-u2country` 断言路径，**行为逐字节不变**。
- 有 `pick` 时，`country` 改为「对照模式」：候选集**不替换**，只在 `#pickbar` 下方插一个 `#cmp` 对照块 + 把列表里目标市场的行高亮。
- `src` 依旧筛候选集；只是从主面板挪到高级筛选（`<details>` 收起），深链不变。

### 2.3 第 2 步：「确认这条候选」

**落点**：两处入口，同一状态。

1. **结果行**：`flatRowHTML` 的「详情」列最前面加一个小按钮 `data-pick="<key>|<mk>"`（**不加新列**，避免动 `<thead>`、避免 390 挤爆）。文案：`这条` / `This one`。
2. **身份卡**：在主行动作前加一个次级按钮 `data-pick="<key>|<mk>"`（默认用该条目的第一个市场），文案：`我用的是这条` / `This is mine`。

**确认后 `#pickbar`（sticky 区内，紧跟 `#meta`）**：

```
[已选] Tylenol Extra Strength · US · 对乙酰氨基酚 500 mg 片剂      [重选] [逐项对照 →]
候选集仍是 26 条，这条只是其中一条 —— 看全部候选 ↓
```

- 「已选」块**不带**任何"确定/正确/答案"字样；第二行**必须**同时出现「候选集仍是 N 条」与「只是其中一条」（把底线①写在用户眼前）。
- `重选` = 清 `pick`/`pmk`，回到纯候选集（列表不变）。
- 点 `逐项对照 →` = 展开 `#cmp`（§5）。

**before / after（文字版）**

| | 步骤 |
|---|---|
| before | ① 输入 `tylenol extra strength` → ② 看到身份卡「candidate 1 of 26」+ 20 行表，**没有"这条就是我的"动作** → ③ 往下滚过 20 行找到「目标市场」下拉 → 选 CN → **整张表被换成"中国该成分的商品名"**，26 条候选消失，页面也没有"我在对照"的任何标记 |
| after | ① 输入 → ② 行内点「这条」→ 顶部出现「已选 … · 候选集仍是 26 条」→ ③ 在顶部 chips 选 CN → 候选集**仍在**，下面多一块「逐项对照」：名称/规格/释放/状态 逐项 相同·不同·未收录；点「逐项对照 →」进成分页看成分与剂型的逐行差异 |

### 2.4 第 3 步：目标市场 + 对照

- chips 常驻（见 §3），顺序按现有 `u2Order()`（界面语言市场置顶），但**要补 HK / EU / FR**（现 `U2_COUNTRIES` 只有 9 个）。
- 选中后：`#cmp` 展开（§5），列表加 `data-cmp-on="1"`，目标市场行加 `.cmp-hit` 高亮。
- **无该市场记录**时：显式说「该市场没有以这个名字登记的记录」+ 给「看该市场的该成分」链接（复用现有 `country.missing` / `country.open_card` 文案），**不静默回退**（这条 v0.11.6 已经做到，别退化）。

---

## 3. B2 目标市场选择器常驻（含首屏预估与取舍）

### 3.1 现状为什么"不常驻"

- 面板在 `#out` 之后（§1.2），结果页要滚过 20 行；它在 `<1024px` 还是**上下堆叠两个下拉**（目标 + 来源），高约 120px。
- 站点唯一的 sticky 区是 `.has-q .searchwrap`（grep `.has-q .searchwrap{position:sticky`），里面只有搜索框 + `#meta`。

### 3.2 方案：并进 sticky 搜索条，一行放完

```html
<div class="searchwrap">                     <!-- 已 sticky（has-q） -->
  <div class="searchbar">…</div>
  <div class="t11row">                       <!-- 新增：一行，高度=现有 #meta 行 -->
    <p class="sub search-status" id="meta"></p>
    <div class="mkchips" id="mkchips" role="group" aria-label="Target market">…</div>
  </div>
</div>
```

- **1440**：`#meta`（左）+ 目标市场 chips（右，12 个市场，横向可滚）**同一行**，行高 36px = 现在 `#meta` 行高 → **首屏净增 0**。
- **390**：同一行改成一个 `<select>`（36–44px，触控友好）+ `#meta` 只留「20 条」；若 `#meta` 文本必须换行，则**先删**行首「/ 提示」再换行 → 最坏 **+24px**。
- `.has-q .searchwrap .ctry-details{margin-top:4px}` 这条死规则正好复用：把 `#ctrydetails` 真搬进 `.searchwrap`（或直接删掉它，把两个下拉改成一个 `<select>` + 一个高级筛选链接）。

### 3.3 首屏条目与 chrome 预估（算式写明，待 atc4-ui 复测）

现查基线（`reports/2026-11-14-before-baseline.md` §2.2，官方计量口径 `deploy/first_screen_check.py`）：

| 视口 | 首屏条目 | chrome | 文档高 | 阈值 |
|---|---:|---:|---:|---|
| 1440×900 结果页 | **4.5** | 0.093 | 2,197 | 首屏 ≥5 · chrome ≤40% · AFCR ≥35% |
| 390×844 结果页 | **1** | 0.177 | 3,807 | 同上 |

推算每行/每卡高度：1440 有效内容高 ≈ 900×(1−0.093) ≈ 816px，4.5 行 → **≈181px/行（含身份卡摊分，属上界）**；390 有效内容 ≈ 844×(1−0.177) ≈ 695px，1 卡 → **≤695px**（实际卡片 ≈200–220px，`RES_PAGE` 移动端取 10 也是按此估的）。

| 方案 | 1440 首屏条目 | 390 首屏条目 | 结论 |
|---|---:|---:|---|
| 不动（现状） | 4.5 | 1.0 | 已不达标（<5） |
| **并进 sticky 一行（推荐，净增 0）** | **4.5** | **1.0** | 不退化；且选择器**始终可见**（sticky） |
| 并进 sticky 但 390 换行（+24px） | 4.5 | 0.87 | 可接受（−0.13 卡） |
| 独立面板（+52px，含 margin） | 4.2 | 0.76 | **不建议**：把本来不达标的 390 再压低 1/4 |
| 只在滚动后浮现（浮层，首屏 0） | 4.5 | 1.0 | 不满足「常驻结果上方」，且浮层挡内容（现有 `docs/设计原则` 对悬浮有约束） |

**取舍建议**：宁可**删**现有 `#ctrydetails`（目标+来源两个下拉，桌面 2×44px + 标签，390 高约 120px），把它拆成「目标市场 = sticky 一行 chips」+「记录市场（原来源市场）= 高级筛选里的一个下拉」；这样**总高度是减少的**，同时满足 B2 与 B3。首屏条目**至少不变**（4.5 / 1.0），要做「≥5」是另一个更大的课题（需要压 chrome 或改行高），不该压在 T11 上。

---

## 4. B3 概念拆分：登记库来源 vs 记录市场

### 4.1 三个概念，现在挤成两个

| 概念 | 用户的话 | 现有实现 | 问题 |
|---|---|---|---|
| **目标市场** | 「我要看这个药在**中国**叫什么」 | `?country=` + `#country` | 位置在结果下面；且会**替换候选集** |
| **记录市场** | 「这条记录是**哪个国家**登记的」 | `?src=` + `#src` | 标签叫「来源市场（只看这些登记库的记录）」→ 混进「登记库」 |
| **登记库来源** | 「这个数据从**哪个库**来」 | 只出现在**明细行**的「来源」列（`SOURCE_SHORT`：openFDA / dm+d / NHSA / PBS / TGA CMI / ARTG / CIMA / COFEPRIS / Health Canada DPD / BDPM） | **完全没有筛选入口** |

### 4.2 方案

1. `#src` 从主面板下沉到「高级筛选」（`<details>` 收起，默认折叠），标签改为**记录市场**，去掉"登记库"字样。
2. **登记库来源**新增为高级筛选里的第二个控件。**数据可行性（重要）**：
   - `core.json` 目前 **没有** source 字段（列：`c x xz atc s l f n t v vs nc eo u cu mu ml g gn m mn db sl rl wi fs`）→ 结果层无法按登记库筛。
   - 两条路：
     - **A（推荐，v0.11.7 先做文案与位置）**：高级筛选里先只放「记录市场」；登记库来源以**逐条标注**呈现（明细面板「来源」列已有），不做过滤。零数据改动。
     - **B（下一版，体积可接受）**：索引加一列 `reg`（该 key 涉及的登记库位掩码；`SOURCE_SHORT` 现为 **12 个 source_id → 10 个显示名**（openFDA / dm+d / NHSA / PBS / TGA CMI / ARTG / CIMA / COFEPRIS / Health Canada DPD / manual）→ 10 位 → 1 个小整数）。207,858 个 key、绝大多数只有 1 个来源 → 字典化后约 **+0.3–0.4 MB**（现 46.30 MB，护栏 50 MB，余量 3.7 MB）→ **可行**，但要同步 `CORE_FIELDS` / `CORE_ARRAY_COLS` 与构建期守卫。
3. 目标市场 chips 与「记录市场」**视觉分离**：前者在 sticky 行（常驻、带"我要看这里"语感），后者在高级筛选里（带"这条记录来自哪里"语感）。

### 4.3 四语文案键（en / es / zh / zh-Hant；`fr` 若 enabled 必须同步，构建期有键集硬拦）

| 键 | 现状 | 新文案（zh / en） |
|---|---|---|
| `res.src_label` | 「来源市场（只看这些登记库的记录）」/ "Source market (only records from):" | **改**：「记录市场（这条记录登记在）」/ "Recorded in market (registration of this record):" |
| `res.src_all` | 「全部来源市场」 | **改**：「不限记录市场」/ "Any recorded market" |
| `res.src_active` | 「来源市场 {c}」 | **改**：「记录市场 {c}」/ "recorded in {c}" |
| `res.adv_title` | — | 新：「高级筛选」/ "Advanced filters" |
| `res.adv_registry` | — | 新：「登记库来源」/ "Registry source"（B 方案才启用） |
| `res.adv_registry_all` | — | 新：「全部登记库」/ "All registries" |
| `t11.pick` | — | 新：「这条」/ "This one" |
| `t11.pick_mine` | — | 新：「我用的是这条」/ "This is the one I have" |
| `t11.picked` | — | 新：「已选」/ "Selected" |
| `t11.pick_keep_candidates` | — | 新：「候选集仍是 {n} 条，这条只是其中一条」/ "Still {n} candidates — this is one of them" |
| `t11.reselect` | — | 新：「重选」/ "Choose again" |
| `t11.cmp_open` | — | 新：「逐项对照」/ "Field-by-field" |
| `t11.cmp_same` / `t11.cmp_diff` / `t11.cmp_missing` | — | 新：「相同」/「不同」/「未收录」 · "Same" / "Different" / "Not listed" |
| `t11.cmp_note` | — | 新：「只逐项比对登记字段；不代表两种药可以互换」/ "Field-by-field comparison only — this does not mean the products are interchangeable" |
| `t11.mk_label` | — | 新：「目标市场」/ "Target market"（若不复用 `home.country_summary`） |

> 每条都要进 `I18N` 的五语字典（en/es/zh/zh-Hant + fr），并走 `_lang_block_text` 的四语内联块（注意该函数目前只出 4 语，fr 走 i18n 字典）。

---

## 5. 对照结果呈现（第 3 步，红线）

### 5.1 字段与数据来源（**决定实现方案**）

| 对照字段 | 你这条（picked） | 目标市场 | 来源层 | 可行性 |
|---|---|---|---|---|
| 名称（注册名） | `detail-*.json` 行的 `brand` | 目标市场同名 key 的 `d`/`k` | 索引/明细桶 | ✅ |
| 规格（含 per_volume） | 明细行 `strength`（`"960 mg 30 mL"`/`"500 mg + 5 mg"`） | 目标市场条目的 `s`/`fs` | 明细桶 + 索引 | ✅（注意明细桶分隔符仍是空格，T10b 未做） |
| 释放 | 明细行 `release` | 索引 `rl` | 明细桶 + 索引 | ✅ |
| 状态 | 明细行 `status` | 索引无 → 需明细桶 | 明细桶 | ✅（懒加载后） |
| **剂型** | **明细行没有 form** | 索引 `f`/`fs`（是跨市场并集） | — | ⚠️ 只能靠成分页 |
| **成分集合** | **索引/明细桶都没有 per-market 成分** | 同上 | — | ⚠️ 只能靠成分页 |

### 5.2 两段式呈现（推荐，A 方案）

1. **结果页 `#cmp`（轻量，无新数据）**：4 行——名称 / 规格 / 释放 / 状态，两列（你这条 · 目标市场），每行右侧一个徽标 `相同|不同|未收录`。所有比较是**字符串等值**（规格先做 `_spec_text` 同构化，避免 `960 mg 30 mL` vs `960 mg/30 mL` 误判"不同"）。
2. **「逐项对照 →」= 成分页**：`/drug/<sid>.html?pick=<product_id>&country=<目标市场>#mk-<目标市场>`。成分页现状（v0.11.6 产物实测，`drug/acetaminophen.html`）：`.mkrow` 上已有 **`data-form` / `data-spec` / `data-mk` / `data-spec-kind` / `data-combo`**（各 150 处）；**`data-others` 只在矩阵 `tr` 上**（本页 0 处，因为该页无矩阵）、**`data-release` 目前没有**（释放只作为可见文本）。
   → T11 要在成分页补两件小事：① `.mkrow` 加 `data-release`；② `.mkrow` 加 `data-others`（把矩阵行已有的成分签名同步到清单行）。两处各 1 行，然后**成分 + 剂型 + 释放 + 规格**的逐行 diff 全部可在客户端完成，无需新索引字段。
   → 成分页的「只看某市场 / 单方·复方 / 规格」筛选**已由 T13 的 `initListFilters` 提供**（见 §6.4），T11 只读它的状态，不重写。

### 5.3 文案与红线（硬约束）

- 徽标只用 `相同 / 不同 / 未收录`；**禁止**出现：等价、可替代、可互换、建议、应服用、换算、等效剂量。
- 每块对照底部固定一行 `t11.cmp_note`（身份对照，不代表可互换）。
- 「不同」不附带任何处置建议（不写"请咨询药师选哪个"，只写"两边登记字段不同"）。
- 目标市场无记录 → 用 `未收录` + 现有 `country.missing_note` 口径（"未收录不等于该市场没有这个药"）。

---

## 6. 影响面与风险

### 6.1 深链向后兼容

| 旧链接 | 新行为 | 兼容策略 |
|---|---|---|
| `?q=X` | 不变 | — |
| `?q=X&country=CN`（**无 pick**） | **保持旧行为**（整表替换成该国名字） | 显式分支：`if(!pick) 走 countryView` |
| `?q=X&country=CN&pick=K&pmk=US` | 新增对照模式 | 新参数，无冲突 |
| `?q=X&src=GB` | 仍筛候选集（下沉到高级筛选，参数不变） | — |
| `?view=table`、`?mk=`、`?mcountry=`、`?page=`、`?legacy=` | 全不变 | 不碰成分页/厂商页 |

**风险点**：若把 `country` 改成"永远不替换列表"，`data-u2country` chips 的老路径与 atc4-ui 的 `countryView` 相关断言会一起变；用「无 `pick` 走旧路径」可以规避。

### 6.2 atc4-ui 37 条断言（`reports/2026-11-14-after-compare.probe.js`）

构成：**22 条静态**（A1–A3、A6、B1–B9、C1–C8、P3）+ **D1–D5 × 3 页 = 15 条** = **37**。

| 断言 | 依赖 | T11 影响 |
|---|---|---|
| `P3 页脚版本 v0.11.6` | 页脚文本 | **必失效**（版本升 v0.11.7）→ atc4-ui 改断言即可 |
| `A6 候选集语义仍在` | `body.innerText` 含「候选」且**首 4000 字符**含「结果永远是候选集」 | **有风险**：该句是 `.candidate-line`（`home.candidate`，搜索结果页**可见**且位于搜索框上方）。改动只有两种安全做法：①**不藏它**；②若为省高度要藏，必须先把同句搬进 `#pickbar`。新增文案也要带「候选」字样 |
| `D5 底线提示仍在`（×3 页） | 正文含 `候选|不可互换|不代表可以互换` | 同上，风险低（只要 `t11.cmp_note` 带「不可互换」） |
| `A1/A2/A3` | `.c-dose` 的 innerText/innerHTML、`#reswrap table` 的 class、`tr.grp` 计数、`tr.br` 计数 | **不许动**：`.c-dose` 内容、`table.res.rows`、保持扁平（`tr.grp`=0）、`tr.br` 仍是 20 行 |
| `B1–B9`（品牌页）/ `C1–C8`（成分页） | 各自的 H2 / 段标题 / 徽标 | 不受影响；但若在成分页加 `?pick` 高亮，`C7 结构没塌（h1/blocks/rows）` 需复跑确认 block 数不变 |
| `D1–D4`（×3 页） | 无用药建议/collision 术语/碰撞/剂量换算 | 新文案必须过这一关（§4.3、§5.3 已按此写） |

### 6.3 体积影响

| 项 | 现值 | T11 预估 |
|---|---|---|
| `assets/app.js`（外置，全站共用） | 163,258 B | **+3～4 KB**（对照块 + pick 状态 ≈ +2.0%）→ 走外置 |
| `site/dist/index.html`（首页文档，内联 64,600 字符 i18n 字典） | 145,919 B（内联 JS 合计 66,017 字符 / 7 块） | **+0**（**不要把 T11 的 JS 内联**，否则每个入口页 +3 KB 文档） |
| `core.json` raw | 46,295,974 B | **+0**（A 方案零新字段）；B 方案「登记库位掩码」≈ +0.3–0.4 MB，per-market 摘要 ≈ +4.5–6.7 MB（**不可行**） |
| DOM | — | 每页 +~40 节点（chips + `#cmp`），小于现有 `#ctr`y 面板 |

### 6.4 与 T13 的边界（**先看这一节再动手**）

site-ui 在做 T13，且**已经落到工作区源码里**（10:55 现查：`site/build.py` 14,921 行，新增 `initListFilters()`，注释写着「T13 / D1（v0.11.7）：成分页清单的『市场 / 单方·复方 / 规格』筛选」）。已占用的**共用面**：

| 已被 T13 占用 | grep 锚点 | T11 只能怎么用 |
|---|---|---|
| 成分页筛选栏 | `function initListFilters` / `#listfilters` / `#lf-spec` | **只读状态**，不重写、不加自己的筛选 UI |
| 市场筛选 chip | `[data-mk-filter]`、`?mk=` 初值、`#mk-<市场>` 锚点 | T11 的「对照」深链直接复用 `#mk-<市场>`，不改 `?mk=` |
| 单方/复方段切换 | `[data-seg-filter]`、`.mkrow[data-combo]`、`state.seg` | 复用；T11 的复用点只需 `data-others` 在清单行可见 |
| 剂型 chips | `[data-form-filter]`、`initListView()` | 复用，别改 |

**串行要求**：T13 先落并构建验收；T11 之后单独一个 build。两边都不能碰 `#reswrap` 的表格结构与 `.c-dose`（§6.2 的 A1/A2/A3）。若同一版本里并行，`site/build.py` 会互踩（T13 这半小时内已把文件从 14,569 行改到 14,921 行）。

---

## 7. 证据附录

### 7.1 `index.html` 的 JS 分布（现查）

```
index.html 总字节 145,919
内联 <script> 7 块，合计 66,017 字符
  └ 其中 64,600 字符 = 当前语言的 i18n 字典（_optimize_home_html 内联）
外置 script 引用 1 个 = GoatCounter（https://gc.zgo.at/count.js）
app.js / boot.js / bilingual.js 在 load 后被注入（不挡首屏）
assets/app.js 163,258 B · boot.js 18,432 B · i18n.js 240,689 B · i18n.en.js 68,252 B
```

### 7.2 索引能力边界（决定 §5 方案）

```powershell
& $py -c "import json;C=json.load(open('site/dist/data/idx/core.json',encoding='utf-8'))['cols'];print(sorted(C))"
# ['atc','c','cu','d','db','dp','eo','f','g','gn','k','l','m','ml','mn','mu','n','nc','rl','s','sl','t','u','v','vs','wi','x','xz','fs']
# → 无 source（登记库）、无 per-market 成分/剂型

& $py -c "...统计..."
# keys 207,858 · key×市场对 223,663（均值 1.08、中位 1）
# 出现在 ≥2 个市场的 key = 8,211（3.95%）← 「对照」真正的受众规模
# 多成分 key = 59,138（28.5%）← 成分对比会经常"不同"
```

### 7.3 首屏基线出处

- 结果页 1440：首屏条目 **4.5**、chrome **0.093**、AFCR 0.960、文档高 2,197
- 结果页 390：首屏条目 **1**、chrome **0.177**、AFCR 0.860、文档高 3,807
- 阈值（结果页）：首屏 ≥5 条 · chrome ≤40% · AFCR ≥35% · 搜索框可见
- 出处：`reports/2026-11-14-before-baseline.md` §2.2（口径 `deploy/first_screen_check.py`，条目选择器 `#reswrap tbody tr.br`）

### 7.4 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
# DOM 顺序：市场面板在结果之后
$t = Get-Content site/dist/index.html -Raw -Encoding UTF8
$t.IndexOf('class="searchwrap"'); $t.IndexOf('id="reswrap"'); $t.IndexOf('id="ctrydetails"')
# 惰性钩子只出现一次
(Select-String -Path site/build.py -Pattern 'ctry-visible|ctry-details|data-always-open' | Measure-Object).Count
# 死规则
Select-String -Path site/build.py -Pattern 'has-q .searchwrap .ctry-details'
# 文案混用
Select-String -Path site/build.py -Pattern '"res\.src_label"'      # 中文那句「只看这些登记库的记录」
# 索引能力
& $py -c "import json;print(sorted(json.load(open('site/dist/data/idx/core.json',encoding='utf-8'))['cols']))"
# 37 条断言清单
Select-String -Path reports/2026-11-14-after-compare.probe.js -Pattern "rec\("
```
