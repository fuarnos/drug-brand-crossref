# v0.11.7 改前基线 + T13/T11 断言（在 v0.11.6 产物上实测）

> 工位：atc4-ui ｜ 时间：2026-11-14 谷段 ｜ 只读：未改 `site/build.py`、未构建、未写 `site/dist`、未写库、未 commit、未发布。
> 配套：`reports/2026-11-14-before-baseline.md`（v0.11.5 基线）、`reports/2026-11-14-after-compare.md`（v0.11.6 验收）、`reports/2026-11-14-after-compare.checklist.md`（T10/T12 断言）。
> 本文作用：把 **v0.11.6 当作 v0.11.7 的改前基线**，并给出 T13 / T11 的**可判定断言 + 改前实测值**（现在应当全红）。

## 结论

1. **T13 五条需求在 v0.11.6 全部未落地**：成分页无「市场 / 单方复方 / 规格」筛选器（只有剂型 chips），计数文案仍是「N 条记录 · N 个规格」，市场覆盖 `+N` 不可点，「`+218`」已可点（改前已达标，见 D7），分类页无页内搜索/子类筛选、说明还在正文，覆盖页表头仍是「产品数」。→ 断言 D1–D6、C1–C3、V1、R1–R2 改前**全红**，D7 改前**已绿**。
2. **T11 三条需求也全部未落地**：目标市场选择器**在结果表下方**（不是常驻上方），无「确认这条候选」动作，「来源市场（只看这些登记库的记录）」把两个概念揉在同一句里。→ T1/T2/T3/T4 改前**全红**。
3. **✅ 产物漂移已澄清（Lead 2026-11-14 确认，此项已关闭）**：当前 `site/dist` **就是线上 v0.11.6 产物** ——
   - 我验收时：mtime `2026-11-13 09:54:16`，`index.html` sha256(16) = `33D80F6C36C023B9`，总字节 992,410,495；
   - 现在（= 线上）：mtime `2026-11-13 10:13:26`，sha256(16) = **`D609F3639EF2FFE2`**，总字节 **992,411,405**（+910 B），`name/tylenol-extra-strength.html` gzip 1,883→1,880。
   - 原因：Lead 在首轮构建后发现 CHANGELOG / `release_notes_i18n` 里「原记录小字」的说法与实际不符（`_strength_origin_html` 只挂在矩阵行，归整行所在的 45 页默认不渲矩阵），改文案后**重新构建**，`whats-new` 多 910 B、资产 hash 随之变化；`verify_live` 42/42 通过、live v0.11.6 发布的就是这一版。
   - 结论：**`D609F363…` = 线上产物，本文基线直接用它，不需要回退**；12 项测点/截图与该版逐项一致（见 §1.3 注）。

---

## 1. 回归锚点（v0.11.7 改后要跟这一版比，不是 v0.11.5）

### 1.1 规模 7 项（当前 dist 现查）

| 指标 | 值（v0.11.6 基线） | 护栏 |
|---|---:|---|
| `site/dist` 文件数 | **125,515** | ≥ 24,000 |
| 总字节 | **992,411,405（946.4 MiB）** | — |
| HTML 页数 | **125,290** | 下跌 >5%（<119,026）要报 |
| 0 字节文件 | **0** | = 0 |
| `data/idx/core.json` raw | **46,295,974（44.15 MiB）** | 11–50 MB |
| `data/idx/core.json` gzip(9) | **10,300,950（9.82 MiB）** | 2.5–12 MB |
| `sitemap.xml` URL | **66,300** | ≥ 62,985 |

### 1.2 页面文档体积（raw / gzip(9)）

| 页面 | raw | gzip |
|---|---:|---:|
| `index.html`（首页 + 结果页） | 145,919 | 38,973 |
| `drug/acetaminophen.html`（成分页） | **238,208** | 24,331 |
| `name/tylenol-extra-strength.html`（品牌页） | 6,026 | 1,880 |
| `coverage.html`（覆盖页） | 24,679 | 5,158 |
| `cat/analgesics.html`（分类页） | **173,738** | 12,399 |

### 1.3 一屏 12 项测点（改后对照门槛）

| 页型 | 视口 | 首屏条目 | 溢出 | chrome | AFCR | 文档高 | v0.11.7 改后下限（−5%） |
|---|---|---:|---:|---:|---:|---:|---:|
| 首页 | 1440 | 12 | 0 | 0.093 | 0.960 | 1,096 | **11.4** |
| 首页 | 390 | 8.5 | 0 | 0.143 | 0.898 | 1,596 | **8.075** |
| 结果页 `?q=Tylenol` | 1440 | 4.5 | 0 | 0.093 | 0.960 | 2,272 | **4.275** |
| 结果页 | 390 | 1 | 0 | 0.177 | 0.860 | 3,831 | **0.95** |
| 成分页 | 1440 | 8.5 | 0 | 0.141 | 0.997 | 14,691 | **8.075** |
| 成分页 | 390 | 5 | 0 | 0.197 | 0.903 | 20,363 | **4.75** |
| 品牌页 | 1440 | 4 | 0 | 0.231 | 0.998 | 900 | **3.8** |
| 品牌页 | 390 | 3 | 0 | 0.197 | 0.903 | 1,300 | **2.85** |
| 覆盖页 | 1440 | 6.5 | 0 | 0.138 | 0.887 | 1,443 | **6.175** |
| 覆盖页 | 390 | 1.5 | 0 | 0.263 | 0.764 | 4,667 | **1.425** |
| 分类页 | 1440 | 10.5 | 0 | 0.070 | 0.996 | 3,408 | **9.975** |
| 分类页 | 390 | 1.5 | 0 | 0.143 | 0.898 | 9,429 | **1.425** |

- 口径同 `reports/2026-11-14-before-baseline.measure.js`（AFCR v2 / 网格步长 16 / chrome 选择器表一致）。
- 在**当前**产物上复测：条目数、文档高、横向溢出 12/12 与上表逐项一致（布局未变）；AFCR/chrome 沿用同一布局的全脚本结果。
- 额外门槛：`<12px` 文字节点 12/12 = 0；最小字号 13–14 px。

---

## 2. T13 断言（成分页 / 分类页 / 覆盖页 / 结果页行内）

取证方式：浏览器（客户端渲染页面）+ 静态 grep。改前值均为**本轮实测**。

### 2.1 成分页 `/drug/acetaminophen.html`

| # | 判定表达式 | 期望 | 改前实测（v0.11.6） |
|---|---|---|---|
| **D1** | `document.querySelectorAll('.matrix-filters, details.mf-details, .mf-slot').length` | **≥1**（存在筛选面板） | **0** → 🔴 |
| **D2** | 面板内市场控件：`main select[name*="mk"], main [data-mf-country]` 命中 ≥1，且选项数 ≥ 已收录市场数（11） | **≥1** | **0** → 🔴 |
| **D3** | 单方/复方切换：`main [data-combo-filter], main [name="combo"], main input[value="combo"]` | **≥1** | **0** → 🔴（数据侧已有 `[data-combo="1"]` 40 / `[data-combo="0"]` 110，缺 UI） |
| **D4** | 规格筛选/搜索：`main input[type="search"], main input[name*="spec"]` | **≥1** | **0** → 🔴 |
| **D5** | 计数文案：`/展示\s*\d+\s*个[，,]\s*共\s*[\d,]+\s*个/` 命中 | 命中 | **0** → 🔴（现为块头 `CN 4,299 条记录 · 130 个规格`） |
| **D6** | 市场覆盖 `+N`（`也在 US·TW·AU +6`）可点：该 `+N` 的最近可交互祖先（`a/button/label/summary`）非空 | 可点 | **不可点** → 🔴（全页 115 个 `+N` 叶子全是 `label.m-more` 品牌折叠，市场 `+6` 是纯文本） |
| **D7** | 「`+218`」折叠可展开：勾选后 `.m-rest` 由 `display:none` → `block` 且高度 > 0 | 可展开 | **已达标** → 🟢（实测 none/h=0 → block/h=70px） |
| **D8** | 筛选生效且计数同步：切「片剂」后 `main .mkrow` 数 < 全量 150 且 ≥1，同时 D5 文案随之变化 | 行为断言 | 待实现（现有 `.formchips` 只有剂型 10 个 chip，无市场/单方复方/规格，也没有计数文案） |
| **D9** | 筛选不改动红线：筛选后页面仍显示「不代表可以互换」类提示 | 命中 | 现有提示在（`下方按国家列出，不代表可以互换。`），改后不得删 |

### 2.2 分类页 `/cat/analgesics.html`

| # | 判定表达式 | 期望 | 改前实测 |
|---|---|---|---|
| **C1** | 页内搜索：`main input[type="search"], main [data-cat-search]` | **≥1** | **0** → 🔴（`main` 内 input/select 总数 = 0） |
| **C2** | 子类筛选：`main [data-subclass], main [class*="subfilter"], main .cat-sub select` | **≥1** | **0** → 🔴 |
| **C3** | 说明移出正文：`main .notice` 数 = 0，且帮助区可达（`a[href*="help"]` 或 `/help.html` 存在） | 0 且 ≥1 | **main .notice = 1** → 🔴（说明仍在正文：`类别名称为编辑译名，或来自 Wikipedia…`） |
| **C4** | 搜索可用（行为）：输入「布洛芬」后 `ul.atcmembers li` 可见数 ≥1 且 < 全量 187 | 行为断言 | 无搜索控件，不适用 |
| **C5** | 规模不变：`ul.atcmembers li` 总数 | **187**（2 个列表 80 + 107） | 187 → 保持 |

### 2.3 覆盖页 `/coverage.html`

| # | 判定表达式 | 期望 | 改前实测 |
|---|---|---|---|
| **V1** | `#covtable thead th` 第 2 列文本 | `记录数` | **`产品数`** → 🔴 |
| **V2** | 其余 6 列表头不变 | `市场 / 成分已映射 / 规格覆盖 / 最后同步 / 数据截止 / 已知缺口` | 一致 → 保持 |

### 2.4 结果页行内（来源日期 / 缺失字段 / 计数文案）

| # | 判定表达式 | 期望 | 改前实测 |
|---|---|---|---|
| **R1** | 结果行内出现来源日期：`/\d{4}-\d{2}-\d{2}/` 命中行数 | ≥1 | **0** → 🔴（`Tylenol Extra Strength` 行无日期） |
| **R2** | 缺失字段标记：`/缺失\|未收录\|待补/` 命中 | ≥1（有缺失时） | **0** → 🔴 |
| **R3** | 计数/分页文案统一成「展示 N 个，共 X 个」 | 命中 | 现为 **`显示 20 / 86`（1440）/ `显示 10 / 86`（390）** → 🔴 |

---

## 3. T11 断言（结果页对照流程）

| # | 判定表达式 | 期望 | 改前实测（v0.11.6） |
|---|---|---|---|
| **T1** | 目标市场选择器**常驻在结果表之上**：DOM 顺序 `选择器容器.compareDocumentPosition(#reswrap)` 判 先后，且容器 `top < vh` | 在结果之前 | **在结果之后** → 🔴（实测 1440：`#ctrydetails`/`.ctry-panel` 的 `getBoundingClientRect().top = 1734`，`#reswrap` top = 620；`precedes = false`。文本顺序 `… 详情 显示 20 / 86 加载更多 (+10) 目标市场：看当地用什么名字（可选）…`） |
| **T2** | 「确认这条候选」动作：`/确认这条\|就是这条\|确认此候选/` 命中，且该控件可点 | ≥1 | **0** → 🔴（身份卡 `.idcard` = `共 86 条候选，这是第 1 条 · TYLENOL FILM COATED TABLETS 500MG …`，只有「更多同规格 / 更多记录」两个链接） |
| **T3** | 「来源市场」与「登记库来源」分开：`label[for="src"]` 文案不再混「登记库」 | 不含「登记库」 | **含** → 🔴（原文 `来源市场（只看这些登记库的记录）：`） |
| **T4** | 身份卡可推进：`/上一条\|下一条/` 且存在可点控件 | ≥1 | 有文案「共 86 条候选，这是第 1 条」但**无推进控件** → 🔴（部分） |
| **T5** | 选定目标市场后出现「当地名字」对照块（行为）：`?country=US` 后 `main` 出现新增对照区且非空 | 行为断言 | 未测（现 `select#country` 可过滤结果，但没有「对照」块）→ 待实现 |
| **T6** | 红线：新流程不得出现推荐/替代/换算话术 | 0 命中 | 现有文案 0 命中 → 改后必须保持 |
| **T7** | 现有筛选控件不被破坏：`select#country` 与 `select#src` 仍在，各 **13 个选项**（1 个「全部」+ 12 市场/地区：US GB CN ES MX AU CA TW HK SG EU FR） | 2 个控件 13/13 | **在，13/13** → 🟢（改后必须保持） |

> T1/T3 的文案以 site-ui 最终落地为准：若选择器改到「结果上方一条工具栏」，断言按「DOM 顺序 + 首屏可见」判，不认具体类名。

### 3.1 老深链守卫（Lead 2026-11-14 要求「保留、证明没改坏」）—— 已实测

`?country=` 现在有**两条不同路径**，两层都要守：

| 路径 | 触发条件 | 实测行为（v0.11.6） |
|---|---|---|
| **A 默认**（不拉完整索引） | `?q=Tylenol&country=US` | `core.json` **未被请求**；只把值灌进 `select#country`（`countryVal=US`），结果表不变：共 86 条、首行同基线 |
| **B 整表替换** | `?q=Tylenol&country=US&legacy=1`（`legacy=1` = 旧行为，页面一加载就拉全量索引，build.py L7525） | `core.json` 被请求；**整表替换**：共 **200 条**（正好命中 200 上限）、首行变成 `泡腾剂 1,000 mg / 500 mg · 片剂 500 mg / 650 mg …`；`?country=CN` → 共 **183 条** |

| # | 判定表达式 | 期望 | 改前实测 |
|---|---|---|---|
| **T8** | `?q=Tylenol&legacy=1`：`.br` 行数 >0 且 `core.json` 在 resource 列表里 | 真 | 20 行 / 共 187 条 / core 已请求 → 🟢 |
| **T9** | `?q=Tylenol&country=US&legacy=1`：非空 且 命中数 ≤200 且 首行 ≠ 基线首行 | 真 | 共 **200** 条、首行不同 → 🟢 |
| **T10** | `?q=Tylenol&country=CN&legacy=1`：非空 且 ≤200 且 首行 ≠ US 视图首行 | 真 | 共 **183** 条、首行不同 → 🟢 |
| **T11** | `?q=Tylenol&country=US`（默认）：`select#country.value=US` 且 首行 = 基线首行（不误替换） | 真 | 真 → 🟢 |
| **T12** | `?q=Tylenol&src=CN`：`select#src.value=CN` 且 行数 >0 | 真 | 真 → 🟢 |

### 3.2 B2 判据（Lead 2026-11-14 定的改后验收线）

| # | 判定表达式 | 期望 | 改前实测 |
|---|---|---|---|
| **B2a** | `select#country` 在 sticky 搜索条内：`closest('.searchbar, .searchwrap, .sticky-bar, .resfilter')` 非空，或祖先 `position: sticky/fixed` | 真 | **假**（两条都不满足）→ 🔴 |
| **B2b** | `#reswrap.getBoundingClientRect().top` ≤ **620**（净增 0px） | ≤620 | **620** → 🟢（改后不许涨） |
| **B2c** | 结果页 1440 首屏条目 ≥ **4.275**（4.5 × 95%） | ≥4.275 | **4.5** → 🟢（改后不许降） |

---

## 4. 给 site-ui 的选择器 / i18n 依赖（新增部分，切勿改名）

在 `reports/2026-11-14-after-compare.checklist.md` §6 之外，本轮新增依赖：

| 选择器 / 键 | 页面 | 谁依赖 | 用途 |
|---|---|---|---|
| `.mkblock` / `.mkrow` / `[data-mk]` / `[data-spec]` / `[data-form]` / **`[data-combo]`** / **`[data-spec-kind]`** | 成分页 | 断言 D2–D8 | 筛选与单/复方分段 |
| `.m-more`（`label` + 隐藏 `input[type=checkbox]`） / `.m-rest` | 成分页 | 断言 D7 | 品牌折叠展开 |
| `.formchips` | 成分页 | 断言 D8 | 既有剂型 chips（**保持**，别被新筛选器取代） |
| `ul.atcmembers li` | 分类页 | 断言 C2/C5 | 成员条目（187） |
| `#covtable thead th` | 覆盖页 | 断言 V1/V2 | 表头文案 |
| `#reswrap tbody tr.br` / `.c-dose` | 结果页 | 断言 R1/R2 | 行内日期 / 缺失字段 |
| `.idcard` | 结果页 | 断言 T2/T4 | 候选身份卡 |
| `.ctry-panel` / **`select#country`** / **`select#src`** | 结果页 | 断言 T1/T3/T7 | 目标市场 / 来源市场（**服务端渲染在 `index.html`（build.py L11636–11665），在 `#reswrap` 之后、`#report` 之前；没有 `name` 属性，选择器请写 `#country`/`#src`；各 13 个选项**）。改位置可以，id 与选项请保留 |
| `.restools` | 结果页 | chrome 采样 | 复制/下载工具栏 |
| `main .notice` | 全站 | 断言 C3 + chrome | 说明区（若移走请告知，chrome 占比会变） |

i18n 键：沿用 T10/T12 已就位的一批；T13 新增建议键名（避免与现有冲突）：`matrix.filter_market`、`matrix.filter_combo`、`matrix.filter_spec`、`cat.search_ph`、`cov.col_records`；T11 建议：`res.confirm_cand`、`res.target_market`、`res.src_registry`。**四语（zh / zh-Hant / en / es）必须齐全**，v0.11.6 已实测 `matrix.multi_form` 落地为 5 语（含 fr）。

---

## 5. 截图（12 张，`v0117-before-*`）

| 页 | 桌面 1440 | 手机 390 |
|---|---|---|
| 首页 | [v0117-before-home-1440.png](img/v0117-before-home-1440.png) | [v0117-before-home-390.png](img/v0117-before-home-390.png) |
| 结果页 `?q=Tylenol` | [v0117-before-results-tylenol-1440.png](img/v0117-before-results-tylenol-1440.png) | [v0117-before-results-tylenol-390.png](img/v0117-before-results-tylenol-390.png) |
| 成分页 | [v0117-before-drug-acetaminophen-1440.png](img/v0117-before-drug-acetaminophen-1440.png) | [v0117-before-drug-acetaminophen-390.png](img/v0117-before-drug-acetaminophen-390.png) |
| 品牌页 | [v0117-before-name-tylenol-extra-strength-1440.png](img/v0117-before-name-tylenol-extra-strength-1440.png) | [v0117-before-name-tylenol-extra-strength-390.png](img/v0117-before-name-tylenol-extra-strength-390.png) |
| 覆盖页 | [v0117-before-coverage-1440.png](img/v0117-before-coverage-1440.png) | [v0117-before-coverage-390.png](img/v0117-before-coverage-390.png) |
| 分类页 | [v0117-before-cat-analgesics-1440.png](img/v0117-before-cat-analgesics-1440.png) | [v0117-before-cat-analgesics-390.png](img/v0117-before-cat-analgesics-390.png) |

- 统一带 `&lang=zh` 拍摄（避免 localStorage 语言残留，v0.11.6 验收时踩过）。
- 与 `docs/img/v0116-after-*` 是同一版内容（逐张字节数相同或差 <10 B），可互为交叉核对。

---

## 6. 限制与待办

1. **dist 漂移未澄清**（§结论 3）：请 Lead 确认 10:13 那次重建是谁跑的；若含未发布改动，改用线上 v0.11.6 做改前基线。
2. **T11 方案未定稿**：T1/T3 的具体 DOM 形态未知，断言按「行为 + DOM 顺序」写，文案以落地为准；T5（选定目标市场后出现对照块）目前只能给行为断言，无法给静态表达式。
3. **官方 CDP 首屏守卫仍不可用**（`Chrome 未就绪（--remote-debugging-port 没起来）`），本文件的一屏数字仍是替身口径；改后仍需在能开 CDP 的环境补跑官方 7 项。
4. 分类页「说明进帮助区」需要先确定帮助区落点（`help.html` 不存在，需 T13 一并决定），否则 C3 无法判定为绿。
5. 本文件不判定任何疗效/替代性结论（红线）；文中「不可互换」均为站点既有文案转录。

---

## 7. 改后怎么跑（v0.11.7）

1. 构建到 `== done ==` 后先核锚点：`index.html` sha ≠ `D609F3639EF2FFE2`、页脚 `v0.11.7`、`core.json` raw 在 11–50 MB。
2. 起 `& $py serve.py 8000`（旧进程先关）。
3. 逐条跑 §2/§3 断言（浏览器），把「改前 🔴」变成「改后 🟢」；D7/T7 这类「改前已绿」的必须**保持绿**。
4. 复用 `reports/2026-11-14-before-baseline.measure.js` 测 12 项，与 §1.3 的「改后下限」逐项比，掉 >5% 写原因。
5. 截图存 `docs/img/v0117-after-*`，报告 `reports/2026-11-14-v0117-after-compare.md`，结论写「可发布 / 不可发布」。

---

## 8. 改后对照脚本已备好 + 自检记录

脚本：`reports/2026-11-14-v0117-after.probe.js`（**35 条断言**，把全文从 `async (page) => {` 起粘进 `browser_run_code_unsafe` 即可；整轮约 3–4 分钟，其中 legacy 三条各要拉一次 46 MB 的 core.json）。

**改前预期：19 红 / 13 绿（全是守卫项）/ 3 na**（na = D8 筛选行为、C4 分类页搜索行为、T5 目标市场对照块，都需人工确认或等方案落地）。

自检两轮（对着当前 v0.11.6 产物跑），修掉 4 处**脚本自身**的缺陷：

| # | 毛病 | 后果 | 已修 |
|---|---|---|---|
| 1 | 用 `select[name="country"]` 选控件 | 该 select **没有 `name` 属性**（是 `id="country"`），选择器恒空 → T1/T3/T7 全部**假红** | 改 `select#country` / `select#src`，实测拿到 13/13 选项 |
| 2 | V2 表头比较写错（拿 `产品数` 去比 `成分已映射`） | 改后也会恒红 | 改为「首列 = 市场」+「尾 5 列不变」 |
| 3 | D8 用 `.formchips` 元素 `click()` 看行数变化 | v0.11.6 上点击不改变行数，无法区分「没做筛选」与「脚本没驱动对」 | 降级为 na + 人工确认，不自动判绿 |
| 4 | `readList()` 里用了外层闭包的 `flat` 函数 | 传进 `page.evaluate` 后 `flat is not defined`，整段 T8–T12 崩掉 | 把 `flat` 定义搬进页面上下文函数体内 |

已实测确认的改前值（供对照）：`#reswrap` top=620 / `.ctry-panel` top=1734（**选择器在结果下方 1114 px**）、`label[for=src]` = `来源市场（只看这些登记库的记录）：`、`#country`/`#src` 各 13 选项、`显示 20 / 86`（1440）、`.m-more` 点击后 `.m-rest` 高度 0→70 px、`.formchips` 点击后 `.mkrow` 仍 150 行、覆盖页第 2 列 `产品数`、legacy 路径 `country=US` 共 200 条 / `country=CN` 共 183 条、结果页首屏条目 4.5。
