# V4 首页跨国查名示例 + V6 覆盖页 0.0% 可点开原因（v0.14.0）— 阶段 1 调研

> task-8（site-ui）。**阶段 1 只读**：本文件只做现状取证、外部方案检索与实施草案，**未改 `site/build.py`**
> （Lead 正在跑 v0.13.8 全量构建）。阶段 2 等在 `BUILD-FREE` 后落代码。
> 行号均为现查（2026-11-18 08:5x），并行工位改 `build.py` 后可能漂移，落码前重读锚点。

## 1. 结论先行

| 项 | 现状（现查） | 结论 |
|---|---|---|
| V4 首页示例 | 搜索框下 `tryrow` 只有 3 个 `data-q` 按钮：`Tylenol Extra Strength` / `Metformin` / `960 mg/30 mL`，**只填药名、不带市场**；fr/ko 没有 `HOME_EXAMPLES`，回落英文 | 可行：URL 已支持 `?q=&src=&country=` 且 `?q=` 加载即搜 → 用**原生链接**做跨市场示例，零新 JS、天然可分享 |
| V4 死示例 | `cli.py "960 mg/30 mL"` → **0 候选**（提示「只给了剂量，没有药名」） | 现「960 mg/30 mL」按钮点了是空结果；「按包装文字」示例建议用真实包装行 `Tylenol Extra Strength 960 mg/30 mL`（现查 5 候选） |
| V4 目标查询 | `Tylenol Extra Strength` → 5+ 候选（US 500 mg 片 ×21、CA 500 mg 片 ×2、US 960 mg/30 mL 液 ×1、US 500 mg 胶囊 ×1、US 500 mg/950 mg 粉 ×1） | 跨市场示例**不会落空页**；来源市场/目标市场参数分别有真实语义 |
| V6 0.0% 行 | HK **22,302** 产品 / 规格 0；EU **2,333** / 规格 0 → 覆盖页两行 `0.0%` | 两行都要内联「来源未提供规格」；其余市场原因改成可点开的「查看原因」 |
| V6 原因文案 | `coverage.gap.hk` / `coverage.gap.eu` 六语**都已存在**，但只进 `title` 悬停 + 手机 2 行截断 | 文案可复用，不用新翻译长句；只需新增 2 个短 UI 键 + 1 个 summary 标签（见 §6） |
| 外部方案 | 原生 `<details>/<summary>`（0 KB、可搜索、触屏可点）为推荐；Popover API / a11y-dialog / details-dialog / tippy 均不采用 | 见 §5；符合「无 npm / 静态构建 / 内联资源」 |
| 首屏门槛 | 首页（entry）：搜索框完整可见且上缘 ≤40% 视口、chrome ≤35%、AFCR ≥30%；覆盖页（content）：首屏 ≥5 行、AFCR ≥50% | 示例行在搜索框**下方**，不动主操作位置；覆盖页改 details 后行高只会更小 |

## 2. V4 现状证据（代码 + 现查数字）

**代码位置**

- `HOME_EXAMPLES`：`site/build.py:14020-14035`（只有 en/es/zh/zh-Hant 四份；`fr`/`ko` 由 `build_index_page` 的
  `HOME_EXAMPLES.get(code) or HOME_EXAMPLES["en"]`（14314 行）回落英文）。
- 示例按钮渲染：`_sample_buttons()`（14038-14040）→ `<button type="button" data-q="…">`。
- 首页模板：`tryrow` 一行（14244）：`<div class="tryrow"><span class="try-lbl" data-i18n="u1.try">Try:</span>{{examples}}</div>`；
  结果出来后整行隐藏（`html.has-q .tryrow{display:none}`，5601 行）。
- 点击行为：全站 `[data-q]` 按钮统一处理（9434-9436）→ 填搜索框 + `startSearch()`；**不读 src/country**。
- URL 状态：`syncURL()`（7759-7771）写 `q` / `country` / `src`；页面初始化读 `?q=`（9491-9492）、`?country=`（9493-9494）、
  `?src=`（9496-9497），`?q=` 存在时直接 `startSearch()`（9505-9509）→ **深链=一次点击即出候选**。
- 目标市场选中会自动展开高级筛选（`updateCtryLabel()` 7736-7739）→ 预填后用户看得到筛选状态。
- 来源市场状态行：`updateSrcNote()`（7747-7755 行），选 `src` 才出现。

**现查结果（`& $py cli.py "<q>"`，只读）**

| 查询 | 结果 |
|---|---|
| `Tylenol Extra Strength` | 5 条主候选 + 3 条前缀候选（US/CA，见 §1） |
| `960 mg/30 mL` | **0 条**；`note = 只给了剂量，没有药名` |
| `Tylenol Extra Strength 960 mg/30 mL` | 5 条（与纯药名同集，规格 960/30 mg/mL 被识别） |
| `Tylenol Extra Strength 500 mg tablet` | 5 条（500 mg 片剂排前，score 0.90） |

**六语缺口**：`HOME_EXAMPLES` 无 `fr` / `ko` → 这两个语言的首页示例目前是英文（`_sample_buttons` 的按钮文案也是英文）。
V4 验收要求「五语（含 ko）」→ 实际站点现有 **6 个 UI 语言**（zh/en/es/zh-Hant/fr/ko），草案按 6 语补齐。

**首屏口径**（`deploy/first_screen_check.py`）：home = `entry`，primary `#q` 必须完整可见且上缘 ≤40% 视口，
`must_not_cover` 含 `main h1`/`#q`；阈值 `afcr_min 0.30 / chrome_max 0.35`（147-150 行）。
示例行在 `.searchwrap` 之后，改它不会移动 `#q`。

## 3. V6 现状证据（代码 + 现查数字）

**覆盖页数据（与 `build_coverage_page` 同 SQL，现查 `db/q.py` 只读）**

| 市场 | 产品数 | 有规格记录 | 规格覆盖 |
|---|---:|---:|---:|
| AU | 93,909 | 38,367 | 40.9% |
| CA | 72,651 | 43,776 | 60.3% |
| CN | 148,889 | 139,950 | 94.0% |
| CZ | 92,405 | 63,231 | 68.4% |
| ES | 30,863 | 24,889 | 80.6% |
| **EU** | **2,333** | **0** | **0.0%** |
| FR | 21,503 | 13,733 | 63.9% |
| GB | 65,619 | 51,307 | 78.2% |
| **HK** | **22,302** | **0** | **0.0%** |
| JP | 13,025 | 8,945 | 68.7% |
| LV | 22,293 | 16,573 | 74.3% |
| MX | 13,747 | 3,832 | 27.9% |
| SG | 7,123 | 5,038 | 70.7% |
| TW | 28,644 | 7,786 | 27.2% |
| US | 148,177 | 96,648 | 65.2% |

（SQL 见 §7 复现命令；0.0% 只有 HK / EU 两行，MX/TW 低但不是 0，本次不动。）

**代码位置**

- 行数据：`build_coverage_page()`（14445-14547）；规格格 14508-14513（`spct` / `spec`），缺口格 14524-14526：
  `f'<span class="covgap" title="{note_plain}">{note}</span>'` —— **全文只在 title 悬停**。
- 原因文案：`COVERAGE_I18N` 的 `coverage.gap.hk`（1735 行 en）/ `coverage.gap.eu`（233 行 en；zh 721 行；zh-Hant 2573 行；
  fr 1300 行附近；ko 3813 行附近），语义已包含「无规格/无剂型」。
- CSS：桌面 `#covtable .covgap{display:inline;overflow:visible;...}`（5315 行）；≤1279px 收 2 行
  `-webkit-line-clamp:2`（6433-6438 行，Q4 v0.13.6 的紧凑卡片）；手机卡片化 `table.coverage-table{display:block}`
  + `td::before` 读 `data-label`（5293-5297 行起）。
- 排序：`COVERAGE_SORT_JS`（14427 行起）只重排 `<tr>`，单元格里放 `<details>` 不受影响。
- 首屏口径：coverage = `content`，`items=["#covtable tbody tr"]`、`items_min 5`，primary `.covtools button`。

**为什么 0.0%**：HK 源只有名称/成分层（`coverage.gap.hk`：无规格、无剂型、无注册状态）；EU 区域层是集中审批
（`coverage.gap.eu`：不含规格、剂型、包装）。这两条正是需求要「旁直接写出来」的原因。

## 4. 外部方案检索（AGENTS §12「先找现成工具」）

| 候选 | 许可 / 体积 | 浏览器 | 与本仓兼容性 | 结论 |
|---|---|---|---|---|
| 原生 `<details>/<summary>` 披露 | HTML 标准，**0 KB** | 全绿（Chrome 12+/Edge 79+/FF 49+/Safari 6+ 起） | 无 npm、无 JS、内联 CSS 即可；文本仍可被页内查找/读屏读到（Modern Web Guidance `search-hidden-content` 明确推荐 details 优先） | **采用**（V6） |
| 原生 Popover API（`popover` + `popovertarget`，light dismiss） | HTML 标准，**0 KB** | 2024-04 起 Baseline（Chrome 114+/Safari 17+/FF 125+） | 表格单元格里要算 top-layer 定位、旧浏览器需要回落 | 不采用：短原因用弹层过重；触屏 + 横向滚动的表格里定位风险高 |
| [a11y-dialog](https://github.com/KittyGiraudel/a11y-dialog) | MIT，约 5 KB min | 主流浏览器（JS + ARIA） | 成熟、可访问模态框，但要引第三方 JS、加 aria 样板 | 不采用：为 1–2 句原因开模态框过重 |
| [@github/details-dialog-element](https://github.com/github/details-dialog-element) | MIT，约 2 KB | 依赖 `<details>` + dialog polyfill | 渐进增强 details→dialog；仓库已不活跃（npm 上停更） | 不采用：原生 details 已够，且不想引维护停滞依赖 |
| [tippy.js](https://github.com/atomiks/tippyjs) | MIT，约 14 KB | 主流 | 悬浮/点击提示库 | 不采用：需求明确要**取代悬停**；手机无 hover |
| V4：原生 `<a href="?q=…&src=…&country=…">` | HTML 标准，0 KB | 全绿 | 复用现有 URL 状态（7759/9491-9509），可中键新开、可复制链接 | **采用**（V4） |
| V4 备选：`<form method=get>` | 0 KB | 全绿 | 会带一个额外提交按钮/语义，样式要改 | 不采用：链接更简单 |

参考：Modern Web Guidance 本地存档 `vendor/modern-web-guidance`（Apache-2.0）的 `accordion`（details 组、summary 内不要放标题、
不要加方向键/roving tabindex）与 `search-hidden-content`（details 隐藏内容仍可被「页内查找」和读屏访问、支持 `#fragment` 深链）。
Popover baseline 见 [web.dev: Popover API 进入 Baseline](https://web.dev/blog/popover-api)。

## 5. 实施草案（阶段 2，**未落码**）

### V4（首页示例）

1. `HOME_EXAMPLES` 补 `fr` / `ko`；`quick` 改成结构化条目，新增 `pack` 组：

```python
"zh": {"try1": ["泰诺", "Lipitor 20mg"], "try2": ["两只青蛙"], "try3": ["Benadryl", "Gaviscon"],
       "quick": [{"q": "Tylenol Extra Strength", "src": "US", "country": "CN"}],
       "pack": ["Tylenol Extra Strength 960 mg/30 mL"]},
```

2. `_sample_buttons()` 兼容 dict 条目 → 生成原生链接（普通字符串仍是旧 button）：

```python
<a class="try-cross" data-i18n="home.try_cross" href="?q=Tylenol%20Extra%20Strength&amp;src=US&amp;country=CN">
  美国的 Tylenol Extra Strength，在中国有哪些相关商品名？</a>
```

3. 模板 14244 行：`Try:` 后放跨市场链接 + 新增 `<span class="try-lbl" data-i18n="home.try_pack">按包装文字搜索：</span>{{pack_examples}}`。
4. 点击即 `?q=…&src=US&country=CN` 整页导航 → 初始化读参（9491-9497）+ 直接 `startSearch()`（9505）→ 候选；
   URL 天生可分享；`updateCtryLabel()` 自动展开筛选面板，用户看得到「来源=美国 / 目标=中国」。
5. CSS：`.tryrow a` 与 `.tryrow button` 同外观（`min-height:36px;border-radius:999px`）；行仍在搜索框下方、`has-q` 后隐藏。
   **备选**（若 Lead 不想整页刷新）：保留 button，改 `[data-q]` 处理器读 `data-src`/`data-country`，设 `#src`/`#country` 后
   `startSearch()`；两者都无需新依赖。

### V6（覆盖页原因）

1. 规格格（14508-14513）：`spec == 0` 时在 `0.0%` 旁加
   `<span class="covspec-none" data-i18n="coverage.spec.no_spec">来源未提供规格</span>`。
2. 缺口格（14524-14526）：`<span class="covgap" title=…>` 改成
   `<details class="covgap"><summary data-i18n="coverage.gap.why">查看原因</summary><span data-i18n="coverage.gap.hk">…</span></details>`，
   **删掉 title**（不再只能悬停）；原因长句复用现有六语文案，不新翻译。
3. CSS：`#covtable .covgap summary{cursor:pointer;color:var(--accent);list-style:none}` + 手机 `min-height:44px;display:flex;align-items:center`
   （触屏可点、文字 ≥16px）；桌面保持紧凑（1 行）。关闭态只剩「查看原因」→ 行高比现在 2 行截断更小。
4. 可访问性：details 原生键盘/触屏；文本仍在 DOM，页内查找能命中（MWG `search-hidden-content`）；summary 内不放标题（MWG `accordion`）。
5. 不碰排序 JS（只移动 `<tr>`）、不碰其他市场文案（MX/TW 27% 非 0，不动）。

## 6. i18n 新键草案（6 语，**只写报告，未落 build.py**）

| 键 | en | es | zh | zh-Hant | fr | ko |
|---|---|---|---|---|---|---|
| `home.try_cross` | US Tylenol Extra Strength — what is it called in China? | Tylenol Extra Strength (EE. UU.) — ¿cómo se llama en China? | 美国的 Tylenol Extra Strength，在中国有哪些相关商品名？ | 美國的 Tylenol Extra Strength，在中國有哪些相關商品名？ | Tylenol Extra Strength (États-Unis) — quel nom en Chine ? | 미국 Tylenol Extra Strength — 중국에서는 어떤 이름일까요? |
| `home.try_pack` | By pack text: | Por texto del envase: | 按包装文字搜索： | 按包裝文字搜尋： | Par texte de l'emballage : | 포장 문구로 검색: |
| `coverage.spec.no_spec` | Source does not publish strength | La fuente no publica la concentración | 来源未提供规格 | 來源未提供規格 | La source ne publie pas le dosage | 출처가 함량을 제공하지 않음 |
| `coverage.gap.why` | Why | Por qué | 查看原因 | 查看原因 | Pourquoi | 이유 |

落点（全部在 `site/build.py`，不碰 `data/i18n_zh_hant.json`）：
`home.*` → `UI_I18N` 的 en/es/zh/zh-Hant + `FR_I18N`（fr 扁平表）+ `KO_I18N`（ko 扁平表）；
`coverage.*` → `COVERAGE_I18N` 的 en/es/zh/zh-Hant + `FR_I18N` + `KO_I18N`。
**硬约束**：`_assert_i18n_complete()` 要求 6 语键集与 en **完全相等**（缺/多都会中断构建），
`deploy/i18n_check.py` 的 `zh-Hant` 缺键与扁平表 orphan 也会 FAIL → 4 个键必须六语一次补齐；
`fr` 扁平表当前 663/667 覆盖率，加键后维持；`ko` 全键 667/667（V6 加键后为 668+，属预期）。

## 7. 验收与测量计划（阶段 2）

| 验收项 | 做法 |
|---|---|
| 首屏**改前/改后** | `deploy/first_screen_check.py` 各跑一次：home 390/768/1440/2560 + coverage 390/1440；贴 AFCR / chrome / items / 搜索框上缘比例 |
| 一次点击即候选 | 临时构建（`SITE_OUT=.tmp/dist-v4v6`）+浏览器 390：点示例 → URL 带 `q/src/country` → 出现候选；`?q=` 深链直接开也出候选 |
| 六语 | 6 个首页各点一次（链接参数一致、文案为各自语言）；覆盖页 6 语各看 HK/EU 行内联标记 + 「查看原因」可点开 |
| 触屏可点 | 390 用 `browser` 点开 `<details>`、截图 `docs/img/v4-home-cross-market.png`、`docs/img/v6-coverage-reason.png` |
| i18n | `& $py deploy/i18n_check.py` → FAIL 0（六语键集一致，无 orphan） |
| 不写 dist | 只 `SITE_OUT=.tmp/dist-v4v6`；`git diff --stat` 只 `site/build.py` + 报告/截图 |
| 链接/404/体积 | 抽 `/ko/`、`/fr/` 首页与 `coverage.html` 的示例/原因链接 200；`whats-new.html` 体积不再变（本任务不碰） |

复现现查数字：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/q.py "SELECT COALESCE(p.country, p.region) AS c, COUNT(*) AS n, COUNT(DISTINCT CASE WHEN pc.strength_value IS NOT NULL THEN p.product_id END) AS spec, ROUND(100.0*COUNT(DISTINCT CASE WHEN pc.strength_value IS NOT NULL THEN p.product_id END)/COUNT(*),1) AS spec_pct FROM product p LEFT JOIN product_component pc ON pc.product_id=p.product_id GROUP BY c ORDER BY c"
& $py cli.py "Tylenol Extra Strength"
& $py cli.py "960 mg/30 mL"
& $py cli.py "Tylenol Extra Strength 960 mg/30 mL"
```

## 8. 风险 / 待确认

- **并行改 `build.py`**：另 3 个工位（page-slim / atc4-ui / alias-site）阶段 2 也会动同一文件 → 我只 `edit` 唯一锚点、
  不 `write` 整文件；`FS_STALE_VERSION` 就重读锚点再试；不碰 whats-new/liners/名字页/分类页区段。
- **示例文字**：需求原文的「试试看：美国的 … 在中国有哪些相关商品名？」是问句，草案把它做**链接文案**（不新增长句以外的解释）；
  若 Lead 想保留现在的 `Try:` 前缀 + 三个按钮形态，可退化为「第 1 个按钮加 `data-src/data-country`」的 JS 方案。
- **`960 mg/30 mL` 单独搜是 0 结果**（现查）：草案用含药名的包装行，否则示例本身会落空；若必须保留裸规格字符串，
  需接受「点了显示『只给了剂量，没有药名』」的现状（结果页已有该提示）。
- **whats-new 体积**：LG1 追加把 whats-new.html 从 406 KB 涨到 533 KB（77 版 × 6 块），本任务不动；若要压体积另开一条。
- **`fr` 首页示例**：`Doliprane` 等法国商品名是否在库、检索是否落空，落码前用 `cli.py` 逐条验（本报告不预设）。

## 9. 一句话交接

改了什么：阶段 1 只读调研，未动代码 —— 查清 V4 首页示例可走原生 `?q=&src=&country=` 链接（现查 `Tylenol Extra Strength` 5 候选、裸 `960 mg/30 mL` 0 候选），V6 的 HK/EU 规格 0.0%（22,302 / 2,333 条）原因文案六语已存在但只在 `title` 悬停。
怎么验的：`db/q.py` 同 SQL 现查 15 市场覆盖、`cli.py` 三条示例查询、读 `build.py` 区段与 `first_screen_check.py` 阈值。
还剩什么：BUILD-FREE 后按 §5 落 4 个 i18n 键 + 首页链接示例 + 覆盖页 `<details>`，出改前/改后首屏数字与 390 截图。

---

## 10. 阶段 2：实施结果（2026-11-18，BUILD-FREE 后已落码）

### 10.1 改了什么（全部 `site/build.py`，`edit` 唯一锚点）

**V4（首页跨国查名示例）**

- `HOME_EXAMPLES`：四语 → **六语**（补 fr/ko；fr 的 3 步引导示例用法国商品名 `Doliprane 1000mg` / `Paracétamol 500mg`，已用 `cli.py` 验证有候选；ko 沿用国际商品名，避免落空）。
- `quick` 从 3 个药名按钮 → **结构化跨市场条目** `{"q": "Tylenol Extra Strength", "src": "US", "country": "CN"}`；
  新增 `pack` 组放「按包装文字搜索」示例。`960 mg/30 mL` 从 `quick` 移除（裸规格单独搜 **0 候选**，见 §1/§3），
  改用带药名的真实包装行 `Tylenol Extra Strength 960 mg/30 mL`（现查 5 候选）。
- `_sample_buttons(queries, lang="en")`：普通字符串仍出 `data-q` 按钮（旧行为不变）；dict 条目出**原生链接**
  `<a class="try-cross" data-i18n="home.try_cross" href="?q=…&amp;src=US&amp;country=CN">`。
  链接是**同目录相对参数**：`/`、`/es/`、`/zh/`、`/zh-hant/`、`/fr/`、`/ko/` 各落自己目录，语言由路径决定（`/ko/` 下即 ko，无需再拼 `lang`）。
- 首页模板 `tryrow`：`Try:` 后放跨市场链接 + `按包装文字搜索：` 分组标签；`build_index_page` 传入页面语言并把 `{pack_examples}` 一起替换。
- CSS：`.tryrow a` 与示例按钮同外观（36px 高、pill 边框、hover/focus 高亮），行仍在搜索框**下方**，`has-q` 后整行隐藏。
- 新增 i18n 键 `home.try_cross` / `home.try_pack`（六语）。

**V6（覆盖页 0.0% 可点开原因）**

- 新增 i18n 键 `coverage.spec.no_spec` / `coverage.gap.why`（六语）。
- 规格格：`spec == 0` 且该市场有产品时，`0.0%` 旁直接加 `<span class="covspec-none" data-i18n="coverage.spec.no_spec">来源未提供规格</span>`
  （现查只有 **HK 22,302 / EU 2,333** 两行命中；US 等非 0 行不加）。
- 缺口列：`<span class="covgap" title="…">` → **原生 `<details class="covgap"><summary>查看原因</summary>…</details>`**，**删掉 title**（不再只能悬停）；原因长句复用现有 `coverage.gap.<cc>` 六语文案。
- CSS：桌面 details 内联紧凑（summary 32px、▾/▴ 指示）；≤1279px summary **44px 触屏高度**，不再用 `-webkit-line-clamp` 截断长文。
- 未碰排序 JS（只重排 `<tr>`）、未碰其它市场文案（MX/TW 27% 非 0，不动）。

### 10.2 自检（`.tmp/check_v4_v6.py`，不写 `site/dist`）

```
V4  HOME_EXAMPLES 六语都有 quick/pack ✓
    ko 链接: ?q=Tylenol+Extra+Strength&src=US&country=CN，文案「미국 Tylenol Extra Strength — 중국에서는 어떤 이름일까요?」✓
    渲染 6 份首页到 .tmp/v4v6-mini（/、/es/、/zh/、/zh-hant/、/fr/、/ko/）：
    每份都有 try-cross 链接 + 包装示例 + 各自语言文案，无 {examples}/{pack_examples} 残留 ✓
    /ko/ index 的 href 是相对参数（落在 /ko/ 下）✓
V6  15 市场行 ✓；HK/EU 行有 covspec-none + details + 「查看原因」，无 title 悬停 ✓；US 行不出现 covspec-none ✓
    terms.json / sources.json 均为根绝对路径 ✓；/ko/coverage.html 副本 details 仍在 ✓
i18n  en/es/zh/zh-Hant/fr/ko 键集一致（686 keys，含本任务 4 键）；_assert_i18n_complete 通过 ✓
      & $py deploy/i18n_check.py → FAIL 0 / WARN 2 / INFO 26 ✓
```

`py_compile site/build.py` OK。**未跑全量 temp 构建**（Lead 正在收 R2 同步，按约定先报备再起；构建级验收留给 Lead 重建后）。

### 10.3 尚未出的证据（需构建产物）

- 390/768/1440/2560 首屏守卫改前/改后数字（首页 + 覆盖页）；`/ko/` 首页点示例后出候选的 390 截图；
- 覆盖页 390 触屏点开「查看原因」的截图；
- 全站链接/404/sitemap 抽检（构建后按 AGENTS §5 跑）。

> 说明：当前工作区 `site/build.py` 的 `git diff --numstat` 同时含其它工位改动（V3/V5/V7 同文件），
> 本任务区段 = 首页示例（HOME_EXAMPLES / `_sample_buttons` / tryrow / `.tryrow a`）+ 覆盖页（spec 格 / notes 格 / `.covgap` CSS）
> + 4 个 i18n 键 × 6 语 + P0 热修 `_lang_block_text`（六语）。

---

## 11. 发布前回归修复：results@768 首屏条目 10.5 → 9.5

**根因**：`html.has-q .tryrow{display:none}` 原来只在 `@media (max-width:767px)` 里；V4 给示例行加了第二组
「按包装文字搜索：」后，**768 宽**下 `.tryrow` 换成 2 行 **80px**，结果页仍渲染它，`#reswrap` 被推到 **597px**，首屏少 1 条。

**修法**（只改一处 CSS，`site/build.py` 全局 has-q 区）：新增

```css
/* V4（v0.14.0）：结果页隐藏首页示例区 … 首页无查询时示例照常显示 */
html.has-q .tryrow{display:none}
```

沿用现有 `html.has-q` 类（不自造状态类）；≤767 那条旧规则保留（同一效果，无害）。

**验证**（当前 dist v0.14.0 + 浏览器 768×1024；dist 里还没有这条新 CSS，用注入同一条规则模拟重建后效果）：

| 页面 | `#reswrap` top（改前→改后） | 首屏条目（改前→改后） |
|---|---|---|
| `/index.html?q=tylenol`（en/zh 共用壳） | 597 → **507** | 9.5 → **11.5** |
| `/es/` | 575 → **485** | 9.5 → **11.5** |
| `/zh/` | 597 → **507** | 9.5 → **11.5** |
| `/zh-hant/` | 597 → **507** | 9.5 → **11.5** |
| `/fr/` | 575 → **485** | 9.5 → **11.5** |
| `/ko/` | 575 → **485** | 10 → **12** |

- 改前实测：`.tryrow top=288 / h=80 / display=flex`，`#reswrap top=597`，header h=111，items 9.5（与 Lead 定位一致）。
- 改后：`.tryrow display=none / h=0`；items 全部 **≥11.5**（高于 V4 前基线 10.5）。
- 六语结果页是同一份 shell/CSS，六个副本逐页实测同样生效。
- **首页无查询不受影响**：`/index.html`（无 q）`has-q=false`，`.tryrow display=flex h=80`，跨市场链接可见且 `href="?q=Tylenol+Extra+Strength&src=US&country=CN"`。
- Lead 预期的「~560」是按「一行 40px」估的；实际整行 80px + 间距约 90px 一起移除，所以回到 **485–507**（比基线更好）。
- `py_compile site/build.py` OK；未跑全量构建（按 Lead 统一重建）。重建后建议用 `deploy/first_screen_check.py` 复量 results@768 落报告。

---

## 12. 发布前回归修复 2：coverage@390 首屏条目 3.5 → 2.5 → **3.5**

**只读定位**（当前 dist v0.14.0，390×844）：15 行**全部**有原因文本（`noReason=[]`），也全部渲染了
`<details>`；每张卡 **154px**、summary **44px**（移动端 CSS 的 `min-height:44px`），#covtable 第一行 top=389。
首屏 = US(1) + GB(1) + CA(0.5) = **2.5**。

**修法（标记层，未改任何全局 CSS）**：

1. 新增 `_cov_notes_html(note, has_reason, T)`：**只有真有原因的行**才渲染 `<details>`；无原因行返回空串
   （回到原来的一行紧凑结构）。`has_reason = gap 非空 or CN 无商品名记录`。
2. 有原因行的 `<summary>` 加**行内** `style="min-height:22px"`，压过覆盖页 CSS 的 44px（手机）/32px（桌面），
   卡片高 154 → **132px**；`<details>`/`summary` 的展开、颜色、▾ 指示、触屏可点全部保留。
3. 只改 coverage 页生成的 markup（6 个副本），**不触碰 `site/build.py` 的 CSS 常量** → 不会让其它 13.7 万页多一次变化。

**验证**（`deploy/first_screen_check.py --pages coverage --viewports 390x844`，用 `.tmp/dist-cov` 复测，
改前跑 `site/dist`）：

| 轮次 | items | #covtable 首行 top | 卡片高 | summary 高 | 横向溢出 |
|---|---|---|---|---|---|
| 改前（site/dist） | **2.5** | 389 | 154 | 44 | 否 |
| 改后（.tmp/dist-cov） | **3.5** ✅ | 389 | 132 | 22 | 否 |

- JSON：`.tmp/fs-cov-before.json`（2.5）/ `.tmp/fs-cov-after.json`（3.5）；截图
  `.tmp/fs-cov-shots-before/fs-coverage-390x844.png` / `.tmp/fs-cov-shots-after/fs-coverage-390x844.png`。
- 改后 chrome 0.27、AFCR 0.79、正文 16px、辅助 14px、<14px 8%、**溢出 否**（与改前同级，无新退化）。
- **六语不变**：`coverage.html`、`/es/`、`/zh/`、`/zh-hant/`、`/fr/`、`/ko/` 六个副本都是 15 个 details + 2 个
  `covspec-none`，summary 均 22px；运行时文案随语言切换正确（`查看原因/Why/Porqué/Pourquoi/이유`、
  `来源未提供规格/…/이유`），`docW=375 < 390` 无横向溢出。
- 逐语 items：zh / zh-Hant / fr = **3.5**；es / ko = **3.0**（这两语导语换行多，表格首行 top=433，比 zh 低 44px；
  仍高于改前 2.5，且不低于「至少回到 3」的下限）。
- `deploy/i18n_check.py` **FAIL 0**（WARN 2 / INFO 26，未新增键）；`py_compile` OK。

**说明**：Lead 原方案「无原因行不渲染 details」在当前数据下不会减少行高（15/15 都有原因），真正根因是
summary 的 44px 触屏高度；因此保留 details 语义、改用行内 22px（仍可点、宽度足够），只影响 coverage 页产物。
R2 增量同步的页面集合不因本修复扩大（CSS 常量未改）。
