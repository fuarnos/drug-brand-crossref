# UI 重设计规范：L1–L17 逐条落地口径（v1 · 2026-11-15）

> 工位：**phaseb-plan** ｜ 任务：task-7 ｜ 性质：**只读 + 规范**（本文不含实现代码，不改 `site/build.py`）
> 输入：用户 2026-11-15 整段 UI 设计建议（`docs/谷段需求队列.md` §L，L1–L17）、`docs/设计原则-按人能看到的来.md`（7 指标 + §2.4 桌面 2/3 硬条件）、`AGENTS.md` §1 / §5 / §9。
> 配套证据：`reports/2026-11-15-ui-baseline.md`（改前数字）、`reports/2026-11-15-ui-badge-convergence.md`（徽章与边框收敛清单）、`reports/2026-11-15-ui-baseline-probe.py` / `reports/2026-11-15-ui-badge-audit.py`（可复跑脚本）。
> 基线锚点：`site/dist` 在 12:15 是 **v0.11.9**（本文的「改前」），在 **12:47–12:51 被另一位工位重建为 v0.11.10**（=「改中」，已含 K1/T35 + L2 部分）；两类数字在 `reports/2026-11-15-ui-baseline.md` §0 分列，本文凡写「改中」的都是 12:52 现查。`site/build.py` 工作区当前比 v0.11.9 更靠前，别拿它当改前基线。

---

## 0. 一页版（给实现者的用法）

```text
0) 现成基线（本工位已跑好，直接当 before 用）：
   .tmp/first-screen/before-20261115.json     ← 7 指标 24 组（v0.11.9，干净）
   .tmp/ui-baseline/before-20261115.json      ← DOM 探针 18 组（12:52「改中」态）
   .tmp/ui-baseline/badge-audit-before.json / badge-audit-current.json  ← 全站徽章计数
   docs/img/v0119-before-*-390.png            ← 改前截图（守卫拍的，v0.11.9）
   docs/img/v01110-mid-*-390.png               ← 改中截图（12:52）

1) 改完（构建到 == done == 之后）：
   & $py deploy/first_screen_check.py --json .tmp/first-screen/after.json --baseline .tmp/first-screen/before-20261115.json
   & $py reports/2026-11-15-ui-baseline-probe.py --json .tmp/ui-baseline/after.json --shots docs/img --shot-prefix v01111-after-
   & $py reports/2026-11-15-ui-badge-audit.py --json .tmp/ui-baseline/badge-audit-after.json
   & $py deploy/ui_surface_check.py            # 同色守卫（框内≠框外）
   & $py deploy/check_build_determinism.py     # 构建确定性

2) 逐条对 §2 的 A1–A20，把数字写进报告（改前 / 改后两列，退化 >5% 要解释）。

3) 三语（zh / en / es）各抽 3 条检索，页数/索引大小/首屏体积回归，链接与 sitemap 抽检（AGENTS §5）。
```

**三条底线在 UI 里的落法（每个 L 项都要守）**：

1. **商品名不是主键** → 列表永远是「候选集」，不做「答案是它」的视觉等级；选中态只表示「你手里这条」，不表示唯一命中。
2. **碰撞自动推导** → 徽章/颜色只能由 `collision` / `release` / `status` 既有字段推导，**不许新增人工标注颜色表**。
3. **不给用药建议 / 不做剂量换算 / 不判断可互换** → 任何「相同 / 不同 / 更好 / 等价 / 替代」措辞只保留既有 `t11.same|diff|missing` 的中性表述；颜色只用于「需注意的差异」，不用于「推荐」。

**绿色主色保留**：`--accent:#0b6b53`（`--accent-weak:#f1f8f4`）不动；新样式一律引用现有 token，不新起色板。

---

## 1. 现有设计体系（实现时必须复用，不许另起一套）

### 1.1 CSS token（`CSS` 常量开头 `:root`）

| token | 值 | 用途（本文引用方式） |
|---|---|---|
| `--bg` | `#fbfbf9` | 页面底色 |
| `--card` | `#fff` | 主内容卡 / 表格底 |
| `--surface-2` | `#f6f5f0` | 辅助区 / 表头 / 折叠面板 |
| `--band` | `#f6f5f0` | 内容带（同 surface-2） |
| `--fg` | `#1f2328` | 主文字 |
| `--muted` | `#4b5257` | 次要文字 |
| `--line` | `#cfcabf` | 边框（唯一允许的框线色） |
| `--line-soft` | `#e3e1da` | 弱分隔线（表内分隔） |
| `--accent` | `#0b6b53` | 主操作 / 选中 / 链接 |
| `--accent-weak` | `#f1f8f4` | 浅绿选中底 |
| `--warn` / `--warnbg` | `#b4471f` / `#fdf1ec` | **橙红**：需注意的差异（规格冲突、释放机制不同、导出限定） |
| `--sev` / `--sevbg` | `#a01b1b` / `#fdecec` | 严重碰撞（既有 `collision='severe'`） |
| 间距 | `--s1..--s8` = 4/8/12/16/24/32/48/64px | 只用这 8 档，不写魔法数字 |
| 字号 | `--fs-xs/sm/md/lg/xl` = 12/14/16/20/24px | 见 §1.2 |
| 圆角 | `--r-sm 8px` / `--r-md 12px` / `--r-pill 999px` | 胶囊只给交互控件；**内容属性不用 pill** |
| 行高 | `--lh-tight 1.3` / `--lh-heading 1.35` / `--lh-ui 1.5` / `--lh-body 1.6` | |
| 内容带 | `--band-w`（≥1024px = `min(66.67vw,1680px)`，<1024 = 100%） | §2.4 硬条件，不能改 |

### 1.2 字号阶梯（全站唯一一套，L1–L17 都用它）

| 层级 | 字号 / 字重 | 用在什么 |
|---|---|---|
| 页面标题 h1 | `--fs-xl` 24px / 700 | 每页唯一 h1 |
| 区块标题 h2 | `--fs-lg` 20px / 700 | 市场块、区块 |
| **列表主名（药名/产品名）** | **18px / 700**（`--fs-md`+2px，新增语义类 `.t-name`） | 结果行、名字页品牌、复方行产品名 |
| 正文 / 表格单元 | `--fs-md` 16px / 400 | 成分、规格、市场、说明 |
| 次要文字 | `--fs-sm` 14px / 400 `--muted` | 厂家、来源、日期、计数 |
| 辅助徽标 | `--fs-xs`→**13px**（现有 `.tag/.badge/.st-badge` 已从 12 提到 13） | 徽章、计数、状态 |
| **禁用** | 任何可见文字 **<12px**（硬违规）；`<14px` 占比 ≤50% | `deploy/first_screen_check.py` 指标 6 |

### 1.3 颜色语义（L8 的核心，也是验收口径）

| 语义 | 视觉 | 允许用在哪 |
|---|---|---|
| 主内容 | 白底 `--card` + 无边框（靠留白分组） | 列表行、卡片 |
| 辅助区 | `--surface-2` 底 + 无边框 | 表头、说明块、折叠面板 |
| 主操作 | 实心 `--accent` + 白字 | **每区域最多 1 个** |
| 选中 | `--accent-weak` 底 + 左侧 4px `--accent` | 结果行 / 选项 |
| 需注意的差异 | `--warn` 文字 + `--warnbg` 底（或仅文字色） | 释放机制不同、规格冲突、export-only |
| 严重 | `--sev` | `collision='severe'` |
| 普通状态（active / 未收录 / 无中文名） | `--muted` 纯文字 | **不做胶囊、不占底色** |

---

## 2. 验收数字总表（改完逐条打勾，全部可脚本复算）

> 工具代号：**G** = `deploy/first_screen_check.py`（7 指标）｜**P** = `reports/2026-11-15-ui-baseline-probe.py`（DOM/字号/边框/徽章）｜**B** = `reports/2026-11-15-ui-badge-audit.py`（全站徽章计数）｜**grep** = 产物字符串计数。

| # | 验收项 | 工具 | 改前（v0.11.9） | 目标 |
|--:|---|---|---|---|
| A1 | 结果页药名字号 = 行内最大且 ≥18px、字重 ≥600 | P | 16px / 400–600（v0.11.9）→ 17px / 700（改中） | **≥18 / ≥600，且比行内第二大字号 ≥ +2px** |
| A2 | 结果页列序 = 产品名称 / 成分 / 规格与剂型 / 市场 / 操作 | P | 剂量 / 品牌 / 市场 / 详情（4 列） | **5 列，顺序一致（4 语言）** |
| A3 | 结果行自身边框（`tr.br` border） | P | 390 档 10 条 | **0** |
| A4 | 结果页首屏胶囊徽章数（390） | P | **64**（v0.11.9）/ 39（改中） | **≤ 24**（设计目标 3） |
| A5 | 结果页首屏条目（G） | G | 390 **0.5** / 1440 **3.0** | 390 **≥3.0**、1440 **≥5.0** |
| A6 | 结果页 chrome 占比（G） | G | 390 0.18 / 768 0.19 / 1440 0.13 | ≤0.40（结果页档） |
| A7 | 结果页辅助最小字号（G） | G | 390 / 1440 / 2560 = **12px** | **≥13px** |
| A8 | 结果页 768 横向溢出（G） | G | **是** | **否** |
| A9 | 首页搜索框上缘（G，`#q`） | G | 可见、上缘约 35% 屏（改前 ≈295px） | ≤0.40×视口高（390 ≤338px） |
| A10 | 首页可点示例数 | P | `.tryrow` 3 + `#u1guide` 5 = **8** | **恰好 3** |
| A11 | 首页类别入口等宽等高 | P | 4 列网格 | 8 个卡片，宽/高两两差 **≤1px** |
| A12 | 次级页页头四件套 | P | 返回路径 **1/6 类有**（只有 cat；atc 作为第 7 类也有）；「继续搜索入口」若按**站头**口径算 6/6（≥768 才有输入框）、按**页头块内 + 390 可用**口径算 **1/6** | **6/6 类齐全**（按页头块内口径，见 §3-L7） |
| A13 | 每区域实心绿主按钮数 | P | 首页 1（`#qgo`）、结果页 0、次级页 0–2 | **≤1** |
| A14 | 全站状态胶囊（B） | B | **150,651**（50,939 页） | **≤60,000**（设计目标 **16,512** = −89%） |
| A15 | 全站国家胶囊（B） | B | **48,315**（6,896 页） | **≤6,000**（设计目标 **0**，交互 chip 另计） |
| A16 | 结果行内的剂型胶囊 `.form-tag` | P | 14/首屏 | **0**（剂型回到规格列文字；`.formchip` 筛选控件保留） |
| A17 | 全站每页边框数（P，逐页上限见 §3-L8） | P | 结果页 131（改前）/ 117（改中）；成分页 317、厂商页 104、分类页 195（改中） | 每页 **≤ 改前 ×0.55**，且 `td` 无边框、列表行不套框 |
| A18 | 390 首屏条目（全页型，G） | G | home 0 / results 0.5 / drug 5 / name 1 / atc 7.5 / coverage 1.5 | 内容页 ≥5、结果页 ≥3、名字页 ≥1 |
| A19 | 三语 + 繁体文案同步 | grep | — | zh/en/es 同步，zh-Hant 跟随 |
| A20 | 构建确定性 | `deploy/check_build_determinism.py` | — | 同输入两次构建逐字节一致 |

---

## 3. L1–L17 逐条

> 每条格式：**改成什么样** → **验收数字** → **实现位置**（`site/build.py` 的函数/常量/选择器；行号是 2026-11-15 12:5x 快照，**会漂移，按名字搜**）→ **风险**。

### L1 [P1] 首页三层结构

**改成什么样**
1. 第一层（唯一视觉中心）：h1（≤ 24px，允许两行）+ `#q` 搜索框 + **带文字的实心绿按钮**（`home.submit`），三者构成一个视觉块；占位文案缩到一句（zh `输入商品名、通用名或包装文字`，en `Brand, generic or a line from the pack`，es `Marca, genérico o una línea del envase`）。
2. 第二层：**恰好 3 个**可点击示例（现有 `HOME_EXAMPLES["quick"]` 已是 3 个），紧跟搜索框；三步教学 `#u1guide` 压成**一句话 + `<details>「怎么用」`**（折叠态 ≤44px 高）。
3. 第三层：8 个**统一尺寸**类别小卡片（同宽同高、2 行文字，卡片内文字 ≥14px）；`最近更新`（`.homeupd`）移到 `main` 末尾（页脚之前）。

**验收数字**
- `#q` 宽度 ≥ 0.80 × 内容带宽度（390 档 `#q` 宽 ≥ 0.9×视口 − 按钮宽）；`#qgo` 可见文字 == `home.submit`，高 ≥44px，背景 == `rgb(11,107,83)`。
- `main [data-q]` 元素数 **== 3**（改前 8）；`#u1guide` 折叠态高度 **≤44px**，`details` 展开后才渲染 3 步。
- `.catgrid > a` **== 8**，`getBoundingClientRect()` 宽/高两两差 ≤1px，单卡片文字 ≥14px。
- `.homeupd` 是 `main` 内最后一个 `<section>`（DOM 顺序断言）。
- G：home 390 `#q` 上缘 ≤338px；AFCR ≥0.30；chrome ≤0.35；横向溢出 0。

**实现位置**
- `build_index_page()`（body 模板，≈12545–12637）：调整 `flow3` / `tryrow` / `u1guide` / `catquick` / `recent` 的顺序与层级。
- `HOME_EXAMPLES`（≈12364）、`_sample_buttons()`（≈12382）、`_home_recent()`（≈12516）、`_home_cat_chips()`（≈14534）、`U1_HEAD_JS`（≈2667，折叠态用 localStorage 记住）。
- CSS：`.flow3`（≈4209）、`.searchbar/.sb-go`（≈4229–4240）、`.tryrow`（≈4261）、`.catgrid`（≈4307）、`.homeupd`（≈4407–4415）、`.u1guide/.u1try`（≈4668–4677）。
- i18n：`home.ph`、`home.submit`、`u1.*`（四语言块 ≈209 / 454 / 695 / 917）。

**风险**：`#u1guide` 折叠会改变首页首个 `.catgrid` 的 y 位置 → 首屏条目数上涨（好事），但要防 `chrome` 反升（summary 自身算 chrome）。

---

### L2 [P0 · v0.11.11] 结果列表重排：药名成为主角

**改成什么样**
- **列序 5 列**：`产品名称` / `成分` / `规格与剂型` / `市场` / `操作`。
  - 产品名：18px / 700，`--fg`，超长省略（`title` 保留全名）；有名字页时仍是链接。
  - 成分：16px / 400 `--muted`（单市场行可省，见 L2 备注）。
  - 规格与剂型：`片剂 500 mg · 液体 960 mg/30 mL` 纯文字；**不套 `.form-tag`**。
  - 市场：纯文字 `US` / `CA US`（13px `--muted`，tabular-nums），**不做胶囊**；来源/日期降到行的第二行小字（≤14px）。
  - 操作：`res.pick`（选择此产品）+ `res.reg`（查看登记详情）两个**文字按钮**，不占行高。
- **不套边框**：行与行靠 8–12px 间距 + 字号分层；表格只用一条外框（`table.res` 已有的 1px `--line`）。
- 手机（<768px）：卡片式，**沿用同序**（产品名 → 成分 → 规格 → 市场 → 操作），卡片之间用 1px `--line-soft` 分隔、**无阴影无圆角外框**。

**验收数字**
- thead `th` 文本顺序 == `[res.col_product, col.ing, res.col_spec, res.col_market, res.actions]`（四语言都一样）。
- 首行产品名 computed `font-size ≥ 18`、`font-weight ≥ 600`，且 `产品名字号 − 行内第二大字号 ≥ 2`。
- `tr.br` 边框数 **== 0**（改前 390 档 10 条）；`td` 边框数 0。
- 行高产线：1440 行高 ≤56px（改前 40–64）；390 每屏条目 ≥3。
- 徽章：结果行内 `.tag`（市场）数 **== 0**；`.form-tag` **== 0**；每行徽章 ≤3（状态 1 + 组合 1 + 已选择 1）。
- G：390 items ≥3、1440 items ≥5；chrome ≤0.40；辅助最小字号 ≥13px（把 `.pickbtn` 的 12px 提上去）。

**实现位置**
- `flatRowHTML()`（≈6070–6115，5 列版本）+ `flatTableHTML()`（≈6116+）+ `resultsTableHTML()/resultsHTML()`（分组表，≈6000–6045）+ `brandRowHTML()`（≈5915–5960）。
- `marketTags()`（≈6060，现输出 `.tag` 胶囊）、`specPairsOf()`（≈6050）、`formLabelOf()`（≈6040）。
- CSS：`table.res.rows .c-brand/.c-ing/.c-dose/.c-market/.c-det`（≈4477–4485）、`.c-ing/.c-dose/.c-brand/.c-mah`（≈4469–4510）、`tr.br`/`td.c-det`/`.pickbtn`（≈4919–4922）、手机卡片段（`@media (max-width:767px){ table.res thead{display:none} … }` ≈5045–5060）。
- i18n：`res.col_product`、`res.col_spec`、`res.actions`（四语言已存在，≈1163/1862/2034/2179/2408 附近）；`res.col_market`、`col.ing`。

**风险**
1. 加一列会把桌面行高压到 40px 以下 → 首屏条目反而变多但可读性下降；行高下限 40px。
2. 市场列改文字会减少「一眼看到多市场」的信息量 → 多市场时保留 `US CA +2`（`+N` 用 `--muted` 小字）。
3. 手机卡片重排最容易踩「横向溢出」，390 必须 0。

---

### L3 [P1] 按钮语义具体化

**改成什么样（四语言文案表，key 已存在，只改值/换 key）**

| 现在 | 改成 | 用哪个 key |
|---|---|---|
| 「这条」`t11.pick_this` | **选择此产品** | `res.pick`（en `Pick this product` / es `Elegir este producto` / fr `Choisir ce produit`） |
| 「详情」`res.details` | **查看登记详情** | `res.reg`（en `Registry details` / es `Ficha del registro`） |
| 「逐项对照 →」`t11.compare_link` | **与目标市场产品对照** | `t11.compare_link` 改值（四语言） |
| 「+218」`res.show_brands + N` | **查看其余 218 个产品** | `res.more_n`（`Show the other {n} products`） |

**验收数字**
- zh 产物 grep：`>这条<` == 0、`>详情<` == 0、`>逐项对照` == 0、`>\+\d+<` == 0（结果页与 pickbar；次级页若保留旧文案必须写进报告豁免清单）。
- 每个按钮 `aria-label` 与可见文本一致（或包含可见文本）；按钮文本 CJK 长度 ≥4 字符（不含 `→`）。
- 390：按钮不换行；行高 ≤88px；点击热区高 ≥44px（`min-height:44px`，现有移动端 `.linkbtn` 规则已给）。

**实现位置**：`UI_I18N` 各语言块（en ≈1891–1905 / es ≈2063–2074 / zh ≈2208–2219 / zh-Hant ≈2437–2448 / fr ≈1192–1203）；`flatRowHTML()`、`resultsHTML()`（`res.show_brands`/`res.load_more`）、pickbar JS（≈7061–7200）。

**风险**：「查看其余 N 个产品」比「+218」长 4 倍，`fold-row` 会变高 → 用 `colspan` 整行按钮，不进窄列。

---

### L4 [P1] 选中态与摘要条

**改成什么样**
- 选中行：`--accent-weak` 底 + **左侧 4px `--accent` 竖条**（`box-shadow: inset 4px 0 0 var(--accent)`）+ 行内 `res.picked`（已选择）小字（13px，`--accent`）。
- 顶部 `#pickbar` 摘要条：`产品名（600）· 市场 · 规格` + `t11.reselect`（重新选择）；**不重复**候选集提示（那句保留在表格上方一行）。高度：390 ≤56px、1440 ≤48px。

**验收数字**
- 选中行背景 == `rgb(241,248,244)`，inset 竖条宽 4px，`aria-selected="true"`（或 `aria-current`）存在。
- `#pickbar` 不出现在未选中时（`hidden`），选中后高度 ≤56px 且 `top+height ≤ 0.30×vh`。
- 选中前后：首屏条目差 ≤0.5，`items ≥` 阈值不变。
- 颜色必须是 token（不得硬编码十六进制）。

**实现位置**：`.pickbar` CSS（≈4870–4875）、`#pickbar` 容器（首页 ≈12566、结果页由 JS 写）、`t11.picked/reselect`、`data-pick` 事件（≈7189）、`picked-tag`（L2 已在 `flatRowHTML` 里预留）。

---

### L5 [P1] 每区域只有一个实心绿主按钮

**改成什么样**
- 每个「区域」（页面首屏 / 每个面板 / 每个市场块）**最多 1 个** `background: --accent` 的按钮；候选：首页 `#qgo`、结果页「重新选择」、成分页「应用筛选」。
- 复制 / 导出 / 纠错 / 加载更多 / 折叠 全部改**文字按钮**（`.linkbtn`：透明底、`--accent` 文字、无边框），或收进 `details`「更多」。

**验收数字**
- P：逐页统计 `main button` 中 `background-color == rgb(11,107,83)` 的个数 → **≤1**（6 类次级页 + 首页 + 结果页各一次）。
- 复制/导出/纠错按钮 `background-color` 必须是 `transparent`（`rgba(0,0,0,0)`）。
- 不得靠「变灰」伪装：`--accent` 系按钮的对比度仍需 ≥4.5:1（白字在 `#0b6b53` 上 = 5.9:1，OK）。

**实现位置**：`button{...}` 基础规则（≈4249–4251，注意它是全站默认绿底 —— 新写按钮务必显式覆盖）、`.sb-go`（≈4232）、`.covtools button`（≈5239）、`.mkctl button`（≈4253）、`.linkbtn/.detbtn`（≈4399）。

**风险**：基础 `button{}` 是绿底，任何新 `<button>` 忘了加类就会冒出第 2 个主按钮 —— 建议在 CSS 末尾加一条「`.linkbtn, .pickbtn, .detbtn, .rowreport, .mf-reset { background:transparent }`」的兜底。

---

### L6 [P1] 搜索后的页面压缩

**改成什么样**
- 结果态（`?q=`）时把「引导层」压到最小：h1 从 24px 降到 20px 单行（或直接显示 `搜索「x」`），删掉 `.flow3`、`.candidate-line`，`.sub` 只留一行状态；高级筛选仍是折叠（`details.advfilter`）。
- 目标：查询后 **第一屏第 1 条结果的上缘 ≤ 45% 视口**（390）。

**验收数字**
- G results 390：`items ≥3`、`first-result` 完整可见（守卫的 primary 项）、chrome ≤0.40、AFCR ≥0.35。
- 结果页 h1 之上/之下的引导块（`.flow3`、`.candidate-line`、`.sub`）在结果态**不出现**（P：`#reswrap` 之前的 `main` 子元素高度总和 ≤0.35×vh）。
- 桌面 1440：首条结果上缘 ≤ 0.40×900 = 360px（改前见 baseline）。

**实现位置**：`build_index_page()` 的静态骨架（≈12545–12637），结果态切换在 `app.js`（`APP_JS` 常量 ≈5374 起，`apply()`/`paintResultsOnly()`）；CSS `.flow3`、`.candidate-line`、`h1#h1`。

**风险**：h1 承载 SEO 关键词，不能删；改成 20px 单行即可，别整块移除。

---

### L7 [P0 · v0.11.11] 次级页统一页头

**改成什么样**（一个共用函数 `_page_head()`，所有次级页调用）

```html
<nav class="crumbs" aria-label="…"><a href="../index.html">返回搜索</a> · <a href="../atc.html">…</a></nav>
<h1>页面标题</h1>
<p class="sub page-summary">一句话摘要（≤1 行，说明这页是什么，不含结论）</p>
<form class="page-search" role="search"><input type="search"><button>搜索</button></form>  <!-- 或 a.linkbtn 回首页 -->
```

- 四件套顺序固定：**返回路径 → 标题 → 一句话摘要 → 继续搜索入口**；摘要只允许 **1 行**（390 最多 2 行）。
- 适用范围（6 类）：`drug/`（成分页）、`name/`（商品名页）、`combo/`（复方页）、`maker/`（厂商页）、`cat/`（分类页）、`coverage.html`；`atc/` 作为第 7 类同类处理（它已有返回路径与「搜索该类别」入口，按同一模板统一即可）；`about/warn/confused/glossary/whats-new` 同批（L15 另加页内目录）。
- **改前实测**（v0.11.9 静态源码）：这 6 类里**只有 `cat/` 有返回路径**（`全部 ATC 类别与大类`），**没有一类有独立的「继续搜索」入口**；`maker/cat/atc` 另有四语并排造成的重复说明（`lang-block` 数：maker 9 / cat 332 / atc 140）。

**验收数字**
- P：6 类页面 `head.back_links_above_h1 ≥1`、`head.search_in_main == true`、`h1` 数量 ==1、`h1 ~ p.sub` 可见行 ≤2（摘要 + 计数）。
- 页头高度（crumb + h1 + summary）在 390 ≤0.35×vh = 295px；1440 ≤200px。
- 每页 `main` 内「返回」类链接 ≥1 且指向非自身（不 404）。
- 语言：四语言 + fr 全覆盖（`nav.page.back` 等新 key 四语言齐）。

**「继续搜索入口」的口径（与 atc4-ui 独立验收探头对齐）**：站头（shell）在 ≥768 档确实有搜索输入框（`atc4-ui` 的 `reports/2026-11-15-ui-probe-before.md` 把这算作「有」→ 四件套 3/4）；但 **390 档站头只剩 logo + `⋯`**，手机上一屏之内拿不到搜索。所以本规范的验收口径是：**"页头块内（`main` 里 h1 上下 200px）能直接输入或一键回首页搜索"**，二者取其一即可 —— 满足者写 `head.search_in_main == true`，或 390 首屏内可见 `input[type=search]` / 回搜索链接。**不要**把「站头那个在 ≥768 才出现的输入框」当成已满足。

**实现位置**
- 新增 `def _page_head(lang, *, crumb, title, summary, back_href, back_label) -> str`，放在 `page()`（≈8862）附近。
- 调用点：`build_drug_pages()`（≈10200）、`build_name_pages()`（≈10930）、`build_combo_pages()`（≈11790）、`build_maker_pages()`（≈12140）、`build_category_pages()`（≈14175）、`build_coverage_page()`（≈12730）、`build_about()`（≈12680）、`build_warn()`（≈3839）、`build_confused()`（≈12810）。
- CSS 新增 `.crumbs`（13px `--muted`，`a` 用 `--accent`）、`.page-summary`（14px `--muted`）、`.page-search`（与 `.searchbar` 同宽，高 ≤44px）。

**风险**：77k+ 名字页都加页头 → dist 体积与构建时间上涨；名字页用 slim 模板（`page(..., slim=True)`），页头必须 ≤ 300 B/页。

---

### L8 [P0 · v0.11.11] 减少框套框与徽章堆积

**改成什么样**
- **白 = 主内容、浅灰/浅绿 = 辅助区**：列表与卡片默认无边框；只有 `<table>` 和「独立卡片（`.card`）」允许 1px `--line`。卡片内部**不许再套 border 容器**（`.card > .card`、`.card > .notice` 视为违规）。
- **绿 = 主操作与选中**；**橙红只给需注意的差异**（见 §1.3）。
- **国家 / 剂型 / 状态不再统一做胶囊徽章**：
  - 国家：结果行与表格里改**纯文字**（`US`、`CA US +2`），只有「目标市场」筛选控件保留 chip；
  - 剂型：结果行改文字（「片剂 500 mg」），只有筛选控件保留 chip；
  - 状态：`active` / `unknown` / `无中文名` / `无商品名` 改 `--muted` 文字；**保留胶囊/底色**的只有需注意差异：`withdrawn`、`discontinued`、`export-only`、`severe`、`warning`、规格冲突 `tag.warn`、`combo`（组合药身份）、`picked`（选中）。
- 具体「保留 / 降级 / 只保留差异色」逐个清单与计数见 `reports/2026-11-15-ui-badge-convergence.md`。

**验收数字（逐页边框上限，P 现查改前值 → 目标 = 改前 ×0.55）**

| 页面 | 边框数（实测） | 目标上限 |
|---|---:|---:|
| 结果页 `index.html?q=tylenol` | **131**（v0.11.9 改前）/ 117（12:52 改中） | **72** |
| 成分页 `drug/amlodipine.html` | 317（改中） | **174** |
| 商品名页 `name/tylenol-extra-strength.html` | 10（改中） | **6** |
| 复方页 `combo/…` | 24（改中） | **13** |
| 厂商页 `maker/kenvue-brands-llc.html` | 104（改中） | **57** |
| 分类页 `cat/analgesics.html` | 195（改中） | **107** |
| 覆盖页 `coverage.html` | 23（改中） | **13** |
| 首页 `index.html` | 33（改中） | **18** |

> 「改中」= 2026-11-15 12:52 的 dist（**v0.11.10**，含 K1/T35 + L2 部分实现）。改前 v0.11.9 的次级页 HTML 已被重建覆盖，逐页数字见 `reports/2026-11-15-ui-baseline.md` §0/§3-B 与补救办法。

- 全站徽章（B）：状态 **150,651 → ≤60,000**（设计 16,512）；国家 **48,315 → ≤6,000**（设计 0）；结果行内 `.form-tag` → **0**；`.tag` 非国家非警示（ATC 级别等）**17,435 → 0**；`tag.warn` 警示 **15,559 保留**。
- `td` 边框 == 0；`tr.br` 边框 == 0；`.card` 内 border 元素 ≤1。
- 390 首屏胶囊 ≤24（改前 64，设计目标 3）。
- **改中态回归必修**：结果页 390 卡片模式的列标签被截断（「产品名称 · …」「成分 · 对…」「规格与剂…」）、值被省略号吃掉 —— 见 [v01110-mid-results-tylenol-390.png](../docs/img/v01110-mid-results-tylenol-390.png)。改完必须 390 卡片标签完整、值不截断。

**实现位置**：CSS `.tag`（≈4257–4268）、`.badge`（≈4407–4411）、`.st-badge`（≈4659–4672）、`.form-tag`（≈4618）、`.catchip`（≈4403）、`.card`（≈4280）、`.notice`（≈4440）、`.mkblock`（≈4753）、`.pickbar`（≈4870）、`.cmpbox`（≈4880）；生成点：`brandRowHTML`/`flatRowHTML`/`marketTags`、`_drug_list_html()`（≈11360）、`_atc_members_html()`（≈13800）、`_combo_line_html()`（≈10101）、`_warn_badge()`（≈3771）。

**风险**：`.st-badge` 也被「无商品名 / 无此成分」用（语义是「没有」不是「状态」）→ 降级时要保留可读性（改 `--muted` 文字，不要隐藏）。

---

### L9 [P1] 成分页（与 K1 合并验收）

**改成什么样**
- 中文名与原文层级：h1 用**原文名**（英文 INN）为主，中文名跟在后面同字号或小一档（16px），不加括号堆叠；
- 筛选集中在顶部（`details.formchips` + `details.listfilters` 保持折叠），**已选条件显示为可取消的小标签**（`--accent-weak` 底 + `×` 按钮，高 28–32px）；
- 各市场分块：块头 `市场名 + 记录数`（h2 20px，数量 14px `--muted`）；K1 已把块变成 `<details>`，**首个市场默认展开**。

**验收数字**
- 390：`h1` 与中文名同一视觉块（间距 ≤8px）；区块头字号 20px / 700，计数 14px。
- 已选条件 bar：有筛选时可见，每项高 ≤32px、带可点 `×`（`aria-label` 含「清除」语义），清除后 URL 参数同步消失。
- 筛选入口（`.matrix-filters` 或 `.formchips` 的 summary）上缘 ≤0.50×vh（守卫指标 2）。
- G drug：items ≥5（390）、chrome ≤0.35、AFCR ≥0.50、横向溢出 0（K1 展开/收起两种状态都要测）。
- 市场块数量与 `coverage` 一致（现查 12 个 market，含 EU）。

**实现位置**：`build_drug_pages()`（≈10200–10900）、`_drug_list_html()`（≈11360）、`_combo_line_html()`（≈10101）、`details.mkblock>summary.mkhead`（CSS ≈4243–4259）、`.mkctl`（≈4251）、`initListView()` 的 `#mkchips`/`#mkfilters` JS（≈7088–7200）。

**风险**：块折叠会改变 `first_screen_check.py` 的 `.mkrow` 计数（K1 已注意）；改完必须跑 `--expand` 一次看展开态 chrome。

---

### L10 [P1] 商品名页

**改成什么样**
- 首屏顺序固定为：**产品概览（身份卡）→ 具体制剂 → 市场差异 → 登记详情**；每段有 h2。
- 身份卡内容（≤6 行）：产品名（18/700）、成分、剂型+规格、覆盖市场数、记录数、`name.notice`（同名不代表可互换，中性陈述）。
- 「不能几行摘要就结束」：至少要有「具体制剂」表 + 「市场差异」表 + 「登记详情」折叠区三段；无数据的段要写明「未收录」而不是整段消失。

**验收数字**
- `name` 页 `main h2` 数量 ≥3（概览/制剂/差异 …）；首屏（390）能看到身份卡 + 至少 1 个 h2。
- 身份卡高度 390 ≤0.45×vh；G name：items ≥1、chrome ≤0.35（改前 390 **0.40 未达标**）、AFCR ≥0.50。
- 四语言 h2 文案齐全（zh/en/es/zh-Hant）。

**实现位置**：`build_name_pages()`（≈10930–11220）、身份卡模板（`main .card` 段）、`page(..., slim=True)` 长尾分支（77k 页要控字节）。

**风险**：name 页 77,058 页，任何新增静态块都会放大 dist（预算见 `docs/网站优化流程.md`）；长尾页只能用 slim 变体。

---

### L11 [P1] 复方页（与 H3/T18 合并验收）

**改成什么样**
- 每个成分**单独一行**，与含量对齐（两列：成分 / 含量，`<dl>` 或两列表格，宽度自适应）；
- 长配方（>4 个成分）默认折叠，`details`「展开全部 N 个成分」；
- **不用斜杠串**当唯一剂量信息（现 `table.res .cspec` 已是列表，保持并统一到所有复方页）。

**验收数字**
- 复方页每个产品行里成分条目数 == 该产品成分数（DOM 断言），且每个 `<li>` 内含 `成分名 + 含量` 两个可分辨文本段。
- 390：成分列表不产生横向滚动（`.tablewrap` 外层 `scrollWidth ≤ clientWidth`）；行高 ≤120px。
- 无斜杠串剂量：grep 产品行内 `\d+\s*(mg|g|mcg)\s*/\s*\d` 形式出现在「成分-含量」列的次数 == 0（规格里的 `mg/mL` 不算）。
- G：复方页归入内容页门槛 items ≥5（缺数字则先登记页型到 `first_screen_check.py` 的 `PAGES`）。

**实现位置**：`build_combo_pages()`（≈11790）、`_combo_stub_html()`（≈11230）、`_combo_line_html()`（≈10101）、`table.res .cspec` CSS（≈4883–4888）、`COMBO_COMP_CAP=4`（≈11227）。

**风险**：`COMBO_COMP_CAP` 现在是 4，超过就截断；L11 要求「长配方可展开」→ 折叠而不是丢弃。

---

### L12 [P1] 厂商页（与 H4/T19 合并验收）

**改成什么样**
- 顶部：**页内搜索框**（按品牌名/成分过滤当前页 60 行）+ **分页或「加载更多」**（每页 60 行不变，提供翻页）；
- 同一页面内重复名称下要有**可区分记录的信息**（国家、剂型、规格、批准号），不允许两行看起来一模一样。

**验收数字**
- `maker` 页 `main input[type=search]` 存在（顶部，h1 之后 ≤200px）；输入后行数按过滤实时变化（DOM 断言：过滤前 60 → 过滤后 <60）。
- 分页控件存在且可用（`n_products > 60` 的厂商页）；URL 带 `?p=2` 或按钮可点。
- 任意两行的「品牌+成分+剂型」三元组相同的行，必须至少有一列不同（国家/规格/批号）；否则合并成一行并给 `+N`。
- G：maker 页未进守卫 `PAGES` —— 本轮**必须加**进 `PAGES`（type=content, items=`tbody tr`, items_min=5）。

**实现位置**：`build_maker_pages()`（≈12140–12360）、`MAKER_PRODUCT_CAP=60`（≈12140 前）、`maker.brand/ingredient/form` i18n、`per_country` 均摊逻辑（≈12263）。

**风险**：厂商页 18k+，加页内搜索用内联 JSON 会放大体积 → 复用 `data/idx` 或直接 DOM 过滤（60 行足够）。

---

### L13 [P2] 分类页

**改成什么样**
- 卡片**突出成分名**（成分名 18px/700 作卡片标题）；
- 状态与市场数放**第二行**（14px `--muted`）；
- 完整状态明细**展开后才显示**（`<details>`），默认收起。

**验收数字**
- 分类页卡片里成分名字号 ≥18px 且为卡片内最大字号；第二行（状态/市场数）≤14px。
- 每张卡片默认高度差 ≤8px（网格对齐）；展开 `details` 后才出现明细行。
- G cat 页纳入守卫（type=content, items=`.catgrid a`/行卡, items_min=5）——现未纳入。

**实现位置**：`build_category_pages()`（≈14175–14300）、`_cat_related_html()`（≈14147）、`.catgrid`（≈4307）、`.atcgrid`（≈4306）、`.catcard` 若新增则沿用 `--card/--line`。

---

### L14 [P2] 覆盖页

**改成什么样**
- **固定表头**（`thead` sticky，`--surface-2` 底）；
- **数字右对齐**、tabular-nums；
- 完整度加**细进度条**（4px 高，`--accent` 填充 + `--surface-2` 轨道，宽度 = 百分比）；
- 长篇「已知缺口」说明**点击展开**（`details` / 行内 `+`）。

**验收数字**
- `#covtable thead` `getBoundingClientRect().top` 在滚动 300px 后仍在视口内（sticky 生效）。
- 所有百分比/计数字段（`td` 含 `%` 或 `,` 数字）`text-align:right`。
- 进度条元素存在（`.covbar`），宽度误差 ≤1%。缺口列默认折叠（`details` 未 open），展开后可见。
- G coverage 390：items ≥5（**改前 1.5 未达标**）、chrome ≤0.35、AFCR ≥0.50、纵向表头固定后 390 仍无横向溢出。

**实现位置**：`build_coverage_page()`（≈12730–12800）、`COVERAGE_SORT_JS`（≈12800）、`.covtools`（≈5239）、`#covtable` 样式、`_coverage_entry_js()`（≈12401）。

---

### L15 [P2] 关于页 / 警示页

**改成什么样**
- **页内目录**（`<nav class="toc">`，锚点列表，390 折叠进 `<details>`）；
- 长内容分段（每段一个 h2，段间 `--s5` 间距）；
- **来源与核验信息放每条内容末尾**（统一 `p.sub.src-line`：来源名 + 许可 + 数据截止）。

**验收数字**
- `about/warn/confused/glossary` 四页都有 `nav.toc`，锚点数 == h2 数；点锚点滚动到位（`scroll-behavior` 或 `scroll-margin-top`）。
- 每页 h2 数 ≥3 时必须有目录。
- 每条来源行统一 class（`src-line`），字号 13–14px，含「来源 + 许可 + 截止」。

**实现位置**：`build_about()`（≈12680）、`build_warn()`（≈3839）、`build_confused()`（≈12810）、词汇表页、`LICENCE_HTML`（≈3967）、`_atc_source_line()`（≈14113 附近）、`.notice`/`.lang-block` CSS。

**风险**：警示页是「不可互换」声明的落点，改版时**不许删既有声明句**，只允许折叠。

---

### L16 [P1] 手机端三项（用户未实测，本轮必须补测）

**改成什么样**
1. **搜索框与主操作易触达**：搜索框固定首屏（不 sticky 也必须在首屏内），查询后**第一条具体结果**尽快出现（删掉结果页引导层，见 L6）。
2. **筛选收进「筛选 · 已选 2 项」**：`<details class="formchips">` 的 summary 文案动态显示已选数（`筛选 · 已选 {n} 项`），展开后底部有「统一修改 / 全部清除」两个按钮。
3. **结果卡片纵向阅读**：结果卡片直接纵向读；**只有**需要跨产品比较的表格（如 `?view=table` 矩阵）保留横向滚动 + 滚动提示（`:after` 渐隐或「← 左右滑动 →」小字）。

**验收数字**
- 390×844：`#q` 完整在首屏且上缘 ≤338px；查询后首条结果上缘 ≤0.55×vh（464px）。
- summary 文案匹配 `筛选 · 已选 \d+ 项`（`filter` 计数 == 实际已选条件数）；展开后面板高度 ≤0.45×vh。
- 结果页 390：**横向溢出 0**（改前 results@768 溢出为「是」→ 一并修）。
- 底部导航（`.tabbar`）高度 ≤56px；顶部 `.pickbar` + 底部 tabbar 合计占视口 ≤15%。
- 截图：390×844 全 6 类页面 + 真机实测（用户要求真机，agent 至少要给 390 产物图 + 说明）。
- G：`--viewports 390x844,768x1024` 全页型通过率 ≥ 改前；`items` 目标见 A18。

**实现位置**：`@media (max-width:767px)` 各段（CSS ≈4900–5200 分散）、`.tabbar`、`.pickbar`、`.formchips` 移动端段（≈5050）、`initListView()` 的已选计数 JS（≈7100）。

---

### L17 [P2] 手机排版整体重新实测

**改成什么样**（不是改代码，是**出报告**）
- 用 `deploy/first_screen_check.py --viewports 390x844,768x1024` 跑全页型，抄 7 指标（AFCR / 带宽比 / 条目 / chrome / 悬浮 / 字号 / 溢出）；
- 抽 6 类页面（home / results / drug / name / combo 或 maker / cat 或 coverage）各 1 张 390 截图，落 `docs/img/`（kebab-case）；
- 结论写进报告：哪一档哪一项未达标、比改前好/坏多少、下一版修什么。

**验收数字**
- 报告里 7 指标两列（改前 / 改后）+ 6 张截图链接；
- `390x844` 与 `768x1024` 两档 24 组数字齐全（6 页型 × 2 视口 + 其他页型若有）；
- 未达标项逐条写原因（不许只写「优化了」）。

**实现位置**：不需要改 `build.py`；用 `deploy/first_screen_check.py` 与 `reports/2026-11-15-ui-baseline-probe.py`（本工位脚本，可直接复跑）。

---

## 4. 串行顺序与冲突（`site/build.py` 单文件）

| 顺序 | 谁 | 做什么 | 为什么这个顺序 |
|---:|---|---|---|
| 1 | site-ui（串行占有 build.py） | **L7 页头函数** + **L2 结果表** + **L8 徽章/边框收敛**（三件事同批，一次构建） | L7/L2/L8 都是 P0 且互相依赖（页头样式、结果行、徽章列）；一次构建省 30 分钟发布窗口 |
| 2 | site-ui（同批） | L3 按钮文案、L4 选中态、L5 主按钮、L6 压缩 | 都在结果页/首页同一批模板，跟着上一条改 |
| 3 | site-ui（同批或下一版） | L1 首页三层、L9 成分页、L10 名字页 | 首页与成分页改动大，可与上一批同一次构建但**分开验收** |
| 4 | atc4-ui / page-slim | L11 复方、L12 厂商、L13 分类、L14 覆盖、L15 关于/警示 | 各自独立页面，可与 1–3 并行设计，但**写 build.py 必须排在同一串行队列** |
| 5 | phaseb-plan（本工位） | L16/L17 的**度量与报告**（只读） | 等构建完成再量，避免量到中间态 |

**冲突点（必须提前说清）**

1. `table.res` 与 `.c-brand` 被结果页、名字页、复方页、厂商页、覆盖页**共用** —— 改 L2 会同时改 6 类页面，L7/L8 验收要在同一次构建里一起看。
2. `.st-badge` / `.tag` 被 ~50k 页共用 —— L8 降级必须一次性改 CSS，不能一页一页改。
3. 首屏守卫 `PAGES` 里的选择器是**契约**：L2 改列名/类名时必须同步改 `deploy/first_screen_check.py` 的 `PAGES`（items 选择器、primary 选择器），否则守卫静默失效（v0.11.1 踩过）。
4. `docs/设计原则-按人能看到的来.md` §2.4 桌面 2/3 是**发布阻塞项**：任何让 `band_ratio` 越界的改动都不许发。

---

## 5. 一次构建后的验收命令清单

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py site/build.py                                     # 必须到 == done ==
& $py deploy/first_screen_check.py --json .tmp/first-screen/after.json `
      --baseline .tmp/first-screen/before.json          # 7 指标 + 退化 >5% 判定
& $py deploy/first_screen_check.py --viewports 390x844,768x1024 --json .tmp/first-screen/after-mobile.json   # L16/L17
& $py reports/2026-11-15-ui-baseline-probe.py --json .tmp/ui-baseline/after.json `
      --shots docs/img --shot-prefix v0119-after-        # 边框/徽章/字号/页头四件套
& $py reports/2026-11-15-ui-badge-audit.py --json .tmp/ui-baseline/badge-audit-after.json   # 全站徽章对账
& $py deploy/check_build_determinism.py                  # 构建确定性
& $py deploy/ui_surface_check.py                         # 同色守卫（框内≠框外）
& $py tests/trilingual/run_tests.py                      # 三语检索不退化（基线 69/72）
```

**三语抽检（AGENTS §5）**：zh / en / es 各抽 3 条（建议 `泰诺` / `Tylenol` / `Paracetamol 500mg`），确认结果页 5 列文案、按钮文案、页头四件套在三种语言下都完整不截断。

---

## 6. 不能自动验 / 需要人拍板

1. **真机实测**：L16 用户明确要求「390×844 + 真机实测截图」，agent 只能给无头 Chrome 产物；真机需人拿手机看一遍（或接受 390 产物图 + 说明）。
2. **「药名成为主角」的观感**：字号/字重可量化，但「看起来像主角」要人看一眼（改前/改后 390+1440 截图对比已在 baseline 报告）。
3. **颜色语义是否够用**：L8 把国家/剂型/状态降到文字后，某些页会「素」很多；这是用户明确要求，若要回退必须写进队列（谁在何时定 + 原因）。
4. **公开计数口径**：本轮 UI 改版不改计数，若顺手改了计数（如徽章统计写进 About），按 AGENTS §4「计数口径统一」要同步 README/coverage/CHANGELOG。

---

## 附录 A：L 项 ↔ 需求队列 ↔ 目标版本

| L | 队列优先级 | 目标版本 | 主线任务 |
|---|---|---|---|
| L2 / L7 / L8 | P0 | v0.11.11 | 三件事（用户点名） |
| L1 / L3 / L4 / L5 / L6 / L9 / L10 / L11 / L12 / L16 | P1 | v0.11.11–v0.11.12 | 分批 |
| L13 / L14 / L15 / L17 | P2 | v0.11.12+ | backlog |

## 附录 B：现有 CSS token 速查（改样式前先搜这些）

```
:root{--bg --fg --muted --line --line-soft --card --surface-2 --band
      --accent --accent-weak --warn --warnbg --sev --sevbg
      --s1..--s8 --fs-xs..--fs-xl --lh-tight/heading/ui/body --r-sm/md/pill --prose
      --band-w --wrap-pad}
```

## 附录 C：本文数字的取数命令（可复核）

```powershell
& $py deploy/first_screen_check.py --json .tmp/first-screen/before.json      # G 的 24 组
& $py reports/2026-11-15-ui-baseline-probe.py --json .tmp/ui-baseline/before.json   # P 的 18 组
& $py reports/2026-11-15-ui-badge-audit.py --json .tmp/ui-baseline/badge-audit-before.json  # B 的 6 类
```

改前数字的完整表在 `reports/2026-11-15-ui-baseline.md`；徽章逐项清单在 `reports/2026-11-15-ui-badge-convergence.md`。
