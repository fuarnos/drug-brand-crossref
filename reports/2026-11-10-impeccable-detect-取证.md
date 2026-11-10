# impeccable detect 取证报告（Assessment B · 检测器 + 浏览器证据）

- 日期：2026-11-10
- 环境：Windows / PowerShell，impeccable **4.8.2**（`$env:USERPROFILE\.dsh\skills\impeccable\scripts\impeccable.cmd`）
- 站点：`site/dist/` 构建产物，本地 `serve.py` 起静态服务
- 性质：**只读取证**。未修改 `site/dist/`、`site/build.py`、`data/drugs.db`；未做设计评审，未给用药建议
- 原始输出：`.tmp/impeccable-b/`（json / err / dom dump，可复核）

## 0. 结论先行

1. **6 个构建产物的源码扫描全部为 `[]`（exit 0）**，包含任务里点名的 `index.html`，复现成功。
2. **URL 渲染扫描也不是「全干净」**：定点扫到 4 类 primary finding（`cramped-padding` 153 条、`side-tab` 3 条、`skipped-heading` 2 条、`nested-cards` 2 条）与 1 条 `line-length`；另有 3 条 advisory（`straggler`×2、`em-dash-overuse`×1，不计数、不改退出码）。
3. **「源码 0 findings」不能当成「页面没问题」**：首页是客户端渲染入口，`index.html` 静态态 `#out` 为空，结果表只有带 `?q=` 才生成；`side-tab` / `nested-cards` 只有在 `?q=泰诺` 的 URL 扫描里才出现。
4. 命中最多的是 `cramped-padding`，全部落在**成分页 `.atcmembers` 里的状态徽章**（`span.st-badge`），根因是 `site/build.py:3169` 的 `.atcmembers .st-badge{padding:0 5px;line-height:1.2}` 覆盖了基础 `.st-badge`（`build.py:3427`）的 `2px` 纵向内边距 → **真阳性**；而且 `build.py:3171-3174` 的注释显示这是当年为压高度做的取舍，注释还停在「12px」，**字号抬到 13px 后没人复核 padding** —— 检测器抓的就是这次遗漏。
5. 与内部规范冲突的两条：`line-length`（撞 `docs/设计原则-按人能看到的来.md` 的「内容带 = 2/3 视口」硬门禁，且目标元素是规格枚举不是正文）、`em-dash-overuse`（中文「——」不是拉丁 em-dash）→ **误报**。
6. 检测器的字号阈值（<12px / <11px）比本站规范（正文 ≥16px、辅助 ≥13px）**松得多**，所以「0 findings」不代表满足内部字号门禁。

---

## 1. 命令与 exit code 语义

```powershell
$engine = "$env:USERPROFILE\.dsh\skills\impeccable\scripts\impeccable.cmd"
& $engine detect --json "<file-or-url>"                 # 源码/URL 扫描
& $engine detect --json --viewport 390x844 "<url>"      # 指定视口
& $engine detect --list-rules --quiet                   # 规则 id 全集（62 条）
```

`detect --help` 原文的退出码语义：

| exit | 含义 |
|---:|---|
| **0** | 扫描完成、无 primary finding（advisory 仍可能列出） |
| **1** | 至少一个目标扫不了（操作失败在多目标扫描里优先） |
| **2** | 扫描完成、有 primary finding |

**实际观察**：0 和 2 都出现过，**未出现 1**。advisory-only 的页面（`/about.html`、`/warn.html` 390）都是 **exit 0**，与文档一致。全部 30 次左右扫描调用里 stderr 全为空（text 模式的 findings 才走 stderr；`--json` 时 stdout 是 JSON）。

---

## 2. 结果表

### 2.1 源码扫描（`site\dist\*.html`，无视口）

| 目标文件 | 大小 | findings | 规则 id | exit |
|---|---:|---:|---|---:|
| `site/dist/index.html` | 119.8 KB | **0** | — | 0 |
| `site/dist/about.html` | 37.8 KB | **0** | — | 0 |
| `site/dist/coverage.html` | 23.4 KB | **0** | — | 0 |
| `site/dist/warn.html` | 103.9 KB | **0** | — | 0 |
| `site/dist/confused.html` | 21.8 KB | **0** | — | 0 |
| `site/dist/glossary.html` | 21.9 KB | **0** | — | 0 |

`index.html` 返回 `[]` 复现成功（JSON 10 字节 = `[]` + 换行）。**未**手工写 ignore：仓库里 `Test-Path .impeccable` = False、无 `DESIGN.md`、`site/dist` 与 `site/build.py` 里 grep `impeccable-disable` 均 0 命中 → 结果不是被项目配置或内联注释豁免掉的。

### 2.2 URL 渲染扫描（`& $py serve.py 8000` → `http://127.0.0.1:8000`）

任务指定 + 我补充的代表页（补的用 ★ 标出，用于把「入口页」和「结果页 / 内容页」分开看）：

| # | 目标 URL | viewport | findings | 规则 id（计数） | exit |
|--:|---|---|---:|---|---:|
| 1 | `/`（首页） | 1280x800 | **0** | — | 0 |
| 2 | `/`（首页） | 390x844 | **0** | — | 0 |
| 3 | `/warn.html` | 1280x800 | **0** | — | 0 |
| 4 | `/about.html` | 1280x800 | **1** | `em-dash-overuse`×1（**advisory**） | 0 |
| 5 | `/zh/`（中文入口） | 1280x800 | **0** | — | 0 |
| 6 | ★ `/warn.html` | 390x844 | **1** | `straggler`×1（**advisory**） | 0 |
| 7 | ★ `/zh/` | 390x844 | **0** | — | 0 |
| 8 | ★ `/coverage.html` | 1280x800 | **0** | — | 0 |
| 9 | ★ `/coverage.html` | 390x844 | **0** | — | 0 |
| 10 | ★ `/atc/A.html` | 1280x800 | **40** | `cramped-padding`×40 | **2** |
| 11 | ★ `/atc/A.html` | 390x844 | **40** | `cramped-padding`×40 | **2** |
| 12 | ★ `/atc/L.html` | 1280x800 | **73** | `cramped-padding`×73 | **2** |
| 13 | ★ `/drug/pregabalin.html` | 1280x800 | **2** | `line-length`×1, `skipped-heading`×1 | **2** |
| 14 | ★ `/drug/pregabalin.html` | 390x844 | **2** | `straggler`×1（advisory）, `skipped-heading`×1 | **2** |
| 15 | ★ `/?q=泰诺`（结果页） | 1280x800 | **1** | `side-tab`×1 | **2** |
| 16 | ★ `/?q=泰诺` | 390x844 | **2** | `side-tab`×1, `nested-cards`×1 | **2** |
| 17 | ★ `/?q=Advil` | 390x844 | **2** | `side-tab`×1, `nested-cards`×1 | **2** |
| 18 | ★ `/name/泰诺.html` | 1280x800 | **0** | — | 0 |
| 19 | ★ `/name/泰诺.html` | 390x844 | **0** | — | 0 |

`/zh/` 是真实路径（`site/dist/zh/index.html`，119.2 KB，DOM 里 72 个 `tr/li/td`）；`zh/`、`es/` 目录下只有 7 个静态页（about/confused/coverage/glossary/index/warn/whats-new），**没有**语言子目录的内容页——内容页（`drug/` 12431 个、`name/` 77147 个、`atc/` 1154 个）都在根下，语言靠 `?lang=` 切。

### 2.3 finding 定位信息（JSON 字段原样摘录）

`cramped-padding`（代表条目，40/73 条同文案、selector 各不相同）：

```json
{
  "antipattern": "cramped-padding",
  "severity": "warning", "category": "quality",
  "file": "http://127.0.0.1:8000/atc/A.html",
  "line": 0,
  "snippet": "<span> \"st-badge\": children flush against border+bg on top/bottom (no inset)",
  "selector": "ul.sub.atclist:nth-of-type(2) > li:nth-of-type(59) > span.st-badge.st-discontinued"
}
```

`side-tab`（结果页，桌面与手机都命中）：

```json
{
  "antipattern": "side-tab", "severity": "warning", "category": "slop",
  "snippet": "border-left: 4px + border-radius: 12px",
  "selector": "section.idcard"
}
```

`nested-cards`（**只在 390 出现**）：

```json
{
  "antipattern": "nested-cards", "severity": "warning", "category": "slop",
  "snippet": "Card inside card",
  "selector": "div.idwarn"
}
```

`line-length`（只出现在 1280）：

```json
{
  "antipattern": "line-length", "severity": "warning", "category": "quality",
  "snippet": "~96 chars on 2 of 3 rendered lines (aim for <80)",
  "selector": "#mk-GB > p.mkrest"
}
```

`skipped-heading`（两个视口都命中）：

```json
{
  "antipattern": "skipped-heading", "severity": "warning", "category": "quality",
  "snippet": "<h1> \"普瑞巴林\" followed by <h3> \"CN 186 条记录 · 15 个规格\" (missing h2)",
  "selector": "body"
}
```

advisory 三条：

```json
{ "antipattern": "em-dash-overuse", "severity": "advisory", "line": 0, "advisory": true,
  "snippet": "9 em-dashes in body text", "selector": "body",
  "file": "http://127.0.0.1:8000/about.html" }

{ "antipattern": "straggler", "severity": "advisory", "advisory": true,
  "snippet": "\"dose-mapping（审计）;dose-impl（录入）\" alone on the last of 3 lines (18% of the measure)",
  "selector": "#w-gaviscon-us-vs-uk > div.lang-block:nth-of-type(2) > p.warn-meta",
  "file": "http://127.0.0.1:8000/warn.html" }

{ "antipattern": "straggler", "severity": "advisory", "advisory": true,
  "snippet": "\"+19\" alone on the last of 5 lines (8% of the measure)",
  "selector": "#mk-AU > p.mkundis", "file": "http://127.0.0.1:8000/drug/pregabalin.html" }
```

**定位字段的实测限制**：所有 finding 的 `line` 都是 **0**，文件扫描也一样。真正能定位的是 `snippet` + `selector`；URL 扫描才有 `selector`，源码扫描没有。要落到源码行只能自己反向 grep。

---

## 3. 按规则聚合

| 规则 | 次数 | 类别 / 级别 | 出现位置 |
|---|---:|---|---|
| `cramped-padding` | **153** | quality / warning | `/atc/A.html` 40 + 40（1280+390）、`/atc/L.html` 73 |
| `side-tab` | **3** | slop / warning | `/?q=泰诺` 1280、`/?q=泰诺` 390、`/?q=Advil` 390 |
| `skipped-heading` | **2** | quality / warning | `/drug/pregabalin.html` 1280 + 390 |
| `nested-cards` | **2** | slop / warning | 结果页 390 两个 query |
| `line-length` | **1** | quality / warning | `/drug/pregabalin.html` 1280 |
| `straggler` | 2 | quality / **advisory** | `/warn.html` 390、`/drug/pregabalin.html` 390 |
| `em-dash-overuse` | 1 | slop / **advisory** | `/about.html` 1280 |

**只出现在移动端（390x844）**：`nested-cards`（2/2）、`straggler`（2/2）。两者在 1280 的同 DOM 页面都不触发 → 视口相关，规则对窄屏更敏感。
**只出现在桌面（1280x800）**：`line-length`（1/1，窄屏自然不超 80 字符）。

---

## 4. 误报判断（逐条）

### 4.1 `cramped-padding` × 153 —— **真阳性**，不是误报

- 根因可定位到 CSS：`site/build.py:3427` 基础徽章 `.st-badge{...;padding:2px 6px;...}`，但 `site/build.py:3169-3170` 的 `.atcmembers .st-badge{margin-left:4px;padding:0 5px;margin-right:3px;font-size:13px;line-height:1.2}`（**全局规则，不在媒体查询里**）把**纵向内边距清成 0**。成分页 `ul.sub.atclist.atcmembers` 里的每个徽章都吃这条覆盖（DOM dump：`atc/A.html` 有 `class="sub atclist atcmembers"` 列表 2 个、`<span class="st-badge` 元素 **2226** 个）。13px × line-height 1.2 下文字墨迹到边框只有不到 1px，规则要求的 4.8px inset 必然不满足。
- **这不是手滑，是写进注释的取舍**：`site/build.py:3171-3174` 原文 —— *"12px + padding:0 5px + line-height 1.2 时 4 徽章行平均 48px（v0.10.1 无市场码时 52px），仍然比原来矮"*。作者当时为了在 390px 下把 4 枚徽章行压进 2 行，明确选了「挤内边距 + 压行高」而不是缩字号（注释还写了「12px 是硬线」）。
- 附带发现：**注释已经过期**。注释写的是「12px + padding:0 5px」，而 3169 行现状是 `font-size:13px`（12→13 是 `docs/设计原则` §1 task-3 的改动），3175 行也是 13px。也就是说「padding:0 为 12px 撑高度」的前提在字号抬到 13px 后没人复核，**检测器抓到的正是这次遗漏**：徽章变高了、纵向 inset 仍然是 0。
- 对照同页 `.atcmembers li{font-size:16px;line-height:1.3}`（`build.py:3151`）—— 1.3 正好压在 `tight-leading` 的阈值上（规则要求 ≥1.3），所以这条**没**命中；如果谁把行高改到 1.25，会立刻多出成百条 `tight-leading`。
- 检测器口径（`--list-rules --json` 原文）：*"an element with its own text where the space between the rendered text and the border box is too small for the font size … Add at least 8px (ideally 12–16px) of space inside bordered, outlined, or colored containers."* 徽章是「有边框 + 有色底 + 圆角」的容器，纵向 0 inset → 命中成立。
- **但计数要打折看**：A 页 2226 个徽章只报 40 条，L 页报 73 条（>40，说明不是「每页每规则上限 40」），40 条 selector 互不重复。所以「40」是检测器自己的聚合抽样，**不能读成「只有 40 处」**。要改就改 `.atcmembers .st-badge` 的 `padding` 那一处，不是改 40 个元素。
- 与内部规范的关系：`docs/设计原则-按人能看到的来.md` 三条「不许」里写了「不许靠缩字号解决拥挤」，代码确实没缩字号（守住了 13px），但把拥挤转移到了内边距和行高上 —— 规范没管 padding，所以**不算违规**；不过「文字贴着胶囊边框」正是该文 §1 那张「人看不见」的现场表想消灭的形态。判定：**真阳性、且是规范未覆盖的盲区**。

### 4.2 `side-tab` × 3 —— **风格判断，不是缺陷**（不建议按规则改）

- CSS 原文：`site/build.py:3311` `.idcard{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;background:#fff;padding:12px 14px}` —— 与规则 snippet `border-left: 4px + border-radius: 12px` 逐字对上。
- 规则描述：*"Thick colored border on one side of a card — the most recognizable tell of AI-generated UIs."* 这是**风格/“AI 味”**规则（category `slop`），不是可访问性或可读性缺陷。
- 本站这张卡的语义是「识别结果身份卡」（`#identity` 区块，`#identity:empty{display:none}`），左侧 4px accent 起的是“这是本次查询的身份结论”的标记作用；改成图标/小标题也能达到同样目的，但**当前形态不构成质量问题**。→ 归为「规则命中但与内部设计意图一致」，critique 若要动，属于优先级最低的装饰层。

### 4.3 `nested-cards` × 2 —— **半个误报**（视口不稳定）

- 真实嵌套：`site/build.py:3321` `.idwarn{background:var(--warnbg);border:1px solid #f0d3c4;border-radius:12px;padding:9px 12px;...}` 放在 `.idcard{background:#fff;border:1px;radius:12px;padding:12px 14px}` 内 → 「卡中卡」在几何上确实成立。
- 问题在于**同一份 DOM，1280 不报、390 报**（我重跑 1280 结果页一次，仍然只有 `side-tab`）。同一个「告警块」在窄屏变成了带边框的盒子就命中、宽屏不算卡片。这说明规则依赖渲染几何而非结构，**不能当硬缺陷**。
- 语义上 `.idwarn` 承载的是「同名不同药 / 释放机制不同」这类**不可互换**提示（本站红线信息），视觉强调有正当理由；按规则「压平层级」反而会削弱警示。→ 判为误报（可接受当前形态），若要写进报告请标「规则不稳定 + 语义必要」。

### 4.4 `skipped-heading` × 2 —— **真阳性**，结构性 a11y 问题

- DOM 实测（`/drug/pregabalin.html`）：`<h1>`×1、**`<h2>`×0**、`<h3>`×11。h1 之后直接 h3（`<h3>CN <span class="sub">186 条记录 · 15 个规格</span></h3>` 是每个市场区块的标题）。
- 这不是语言/文案问题，是标题层级缺一级；屏幕阅读器按 heading 导航会少一层。内部规范没规定层级，不构成冲突。

### 4.5 `line-length` × 1 —— **误报 / 与本站规范直接冲突**

- 目标元素是 `#mk-GB > p.mkrest`，DOM 内容：`<p class="mkrest" data-n="3">其余规格: 2,000 mg/100 mL liquid、9,460 mg/473 mL liquid、100 mL liquid</p>` —— **规格枚举**，不是正文段落。规则描述限定 *"Add a max-width (65ch to 75ch) to text containers"*，语义针对 prose。
- 规范冲突：`docs/设计原则-按人能看到的来.md` §2.1/§2.2 把「带宽比」列为硬门禁 —— 视口 ≥1280 时内容带宽度必须是 **0.652–0.682 × 视口**；`site/build.py:3061` 正是 `@media (min-width:1280px){:root{--band-w:66.67vw}}`。1280 下 `.wrap` ≈ 853px（减 `--wrap-pad:20px` 后 ≈ 813px），96 个混排字符正好一行放得下。**想让这条消失只有两条路**：给 `.mkrest` 单独加 `--prose:72ch` 限宽、或改两列；而「把内容带收窄」会直接打破 0.652–0.682 门禁。
- 另外检测器按「字符数」计，中文/英文/数字混排的实际视觉行长差异大（`2,000 mg/100 mL` 这类串宽度远小于 96 个中文字）→ 计数口径本身对混合语言偏保守。→ 判为误报，**不要按规则动 `.wrap`**。

### 4.6 advisory `straggler` × 2 —— **误报（不可操作）**

- `warn.html` 的末行 `dose-mapping（审计）;dose-impl（录入）`、`pregabalin.html` 的末行 `+19`（`mkundis` 里「另有 19 个规格未显示」的折叠计数）。这两处都是**生成式数据串**，末行剩几个字符随数据变化，不是可编辑文案。
- 规则建议 `text-wrap: pretty` 会落在 `body` 上影响全站断行，代价大于收益；advisory 本来不计数、不改 exit code（实测 exit 0）。→ 记录，不处理。

### 4.7 advisory `em-dash-overuse` × 1 —— **中文场景误报**

- `about.html` 正文 9 个破折号，中文文案里的「——」是标准标点，不是拉丁 em-dash 的 AI cadence。
- 附带证据价值：`site/dist/about.html` **源码扫描 0 条、URL 扫描 1 条** → advisory 走渲染文本（HTML 实体 / 脚本内文案在 file scan 不计），说明**file 扫描与 URL 扫描不等价**。

### 4.8 与内部规范的「松紧错位」（比误报更值得写进结论）

`docs/设计原则-按人能看到的来.md` §2.2 指标 6：正文 **≥16px**、辅助 **≥13px**、任何可见文字 **<12px 直接违规**。
检测器：`tiny-text` 阈值 **<12px**，`undersized-ui-text` 阈值 **<11px**（`--list-rules --json` 原文）。

本站徽章/标签都是 13px（`build.py:3116` `.tag{font-size:13px}`、`build.py:3427` `.st-badge{font-size:13px}`），刚好卡在检测器两条规则之下、内部规范的辅助下限上。后果：

- 检测器对这两条规则**永远不会对本站开口**，`0 findings` 完全不等于「满足 16/13 门禁」；
- 首屏小字（`<14px` 占比 >50%）这类问题检测器没有对应规则，只有 `deploy/first_screen_check.py` 能量；
- 所以本报告不能用来替代 `first_screen_check.py` 的 AFCR / 字号 / chrome 判定，两者口径不同，结论必须分开写。

---

## 5. 我做的可信度校验（避免把「检测器没跑」当「干净」）

源码扫描 6 个文件全是 `[]` 时，先怀疑引擎/沙箱，于是造了控制组：

| 控制组 | 命令 | 结果 |
|---|---|---|
| 故意违规的静态 HTML（`.tmp/impeccable-b/sanity-bad.html`，9px 灰字灰底、渐变文字、12px h1、line-height 1.05、脉动点…） | `detect --json .tmp\impeccable-b\sanity-bad.html` | **12 条 primary + 1 条 advisory，exit 2**；命中 `low-contrast`×3、`gradient-text`×2、`tiny-text`、`tight-leading`×2、`overused-font`、`skipped-heading`、`ai-color-palette`、`pulsing-dot`、`repeating-stripes-gradient`(advisory) |
| 同一文件走 HTTP（另起 8123 临时服务） | `detect --json --viewport 1280x800 http://127.0.0.1:8123/sanity-bad.html` | **15 条 primary + 1 条 advisory，exit 2**，且多出**只有渲染才可能命中**的 `cramped-padding`、`body-text-viewport-edge`×3、`straggler`(advisory)；每条都带 `selector` |

结论：引擎与两条管道（file / URL）都正常，六个文件 `[]` 是检测器对该源码的真实判断，`index.html` 的 `[]` 不是空跑。

另外用 headless Chrome 核对「扫描时页面是有内容的」，不是空壳：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu `
  --virtual-time-budget=8000 --window-size=1280,800 --dump-dom "http://127.0.0.1:8000/"
```

- 首页：DOM 122→126 KB，`#q` 搜索框、国家下拉、`data-i18n` 文案齐全，`#out` **空**（结果表按需生成）→ 首页扫描的是「入口页静态态」，这解释了首页与 `/zh/` 为什么 0 findings。
- `/?q=泰诺`：`#out` 里生成了 `parsebar` + `notice`（「同名不同药：Tylenol / 泰诺…」）+ 结果表 `<tr class="br">` + `span.tag` / `span.badge` → 结果页扫描确实扫到了真实结果行。
- `/atc/A.html`、`/drug/pregabalin.html`、`/warn.html`、`/zh/` 都有实质 DOM（ATCR A 页 `st-badge` 2226 个）。

---

## 6. 失败 / 跳过 / 限制

没有出错的扫描（没有 exit 1）。以下是刻意跳过或口径限制：

| 项 | 状态 | 原因 |
|---|---|---|
| 整棵 `site/dist` 扫描 | **跳过** | 按指示；`site/dist` 文件数 ≥ 24,000（`name/` 77147 + `drug/` 12431），扫目录不可行 |
| `es/` 页面单独扫 | **跳过** | `es/` 与 `zh/` 同为 7 个静态页、结构同源；已用 `/zh/` 代表语言入口，未重复消耗 |
| 语言目录下的内容页 | **不存在** | `zh/`、`es/` 下只有 7 个静态页；内容页在根 `drug/`、`name/`、`atc/`，语言用 `?lang=` 切换 |
| 元素级 computed style / 尺寸复核 | **未做** | 沙箱内无 puppeteer/playwright，`detect` 也不输出元素尺寸；CSS 结论来自 `site/build.py` 源码对读 + DOM dump，不是实测像素 |
| `Get-NetTCPConnection` 探端口 | **受限** | 约束模式下返回 `[exit code: 1]`，改用 `Invoke-WebRequest` HTTP 探测确认服务在/不在 |
| finding 的 `line` 字段 | **全部为 0** | 引擎当前版本对 file/URL 都不给行号；只能靠 `snippet` + `selector` 反查 |

---

## 7. 服务启停记录

| 用途 | 启动 | 停止 | 确认 |
|---|---|---|---|
| 站点静态服务 8000 | `& $py serve.py 8000`（后台 job `pwsh-043db417fcef4105`） | `job_kill`（请求取消后进程退出） | `Invoke-WebRequest http://127.0.0.1:8000/` → **无法连接到远程服务器** |
| 控制组临时服务 8123 | `& $py .tmp\impeccable-b\serve_tmp.py`（后台 job `pwsh-f14de686989c4be7`，root = `.tmp/impeccable-b`） | `job_kill` | `Invoke-WebRequest http://127.0.0.1:8123/` → **无法连接到远程服务器** |

停止方式：`job_kill`（等价于 Ctrl+C 掉 `serve.py` 的 `serve_forever()`）。两个 job 状态均为 `killed`。
收尾核查发现仍有 2 个 python 进程（`.tmp\probe_results.py`、`python -`），**命令行不属于我这次起的服务**（我的两个服务已无监听端口），按并行工位纪律未动。

## 8. 复现清单（按顺序）

```powershell
$py     = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$engine = "$env:USERPROFILE\.dsh\skills\impeccable\scripts\impeccable.cmd"

& $engine detect --list-rules --quiet                      # 62 条规则 id
foreach ($f in 'index','about','coverage','warn','confused','glossary') {
  & $engine detect --json "site\dist\$f.html"              # 全部 [] / exit 0
}

& $py serve.py 8000                                        # 后台起服务
& $engine detect --json --viewport 1280x800 "http://127.0.0.1:8000/"
& $engine detect --json --viewport 390x844  "http://127.0.0.1:8000/"
& $engine detect --json --viewport 1280x800 "http://127.0.0.1:8000/warn.html"
& $engine detect --json --viewport 1280x800 "http://127.0.0.1:8000/about.html"
& $engine detect --json --viewport 1280x800 "http://127.0.0.1:8000/zh/"
& $engine detect --json --viewport 1280x800 "http://127.0.0.1:8000/atc/A.html"
& $engine detect --json --viewport 1280x800 "http://127.0.0.1:8000/drug/pregabalin.html"
& $engine detect --json --viewport 1280x800 "http://127.0.0.1:8000/?q=%E6%B3%B0%E8%AF%BA"
& $engine detect --json --viewport 390x844  "http://127.0.0.1:8000/?q=%E6%B3%B0%E8%AF%BA"
# 停服务：job_kill 对应后台 job，或 Ctrl+C
```

原始 JSON / stderr / DOM dump 全在 `.tmp/impeccable-b/`（`file-*.json`、`url-*.json`、`dom-*.html`、`rules.json`、`sanity-bad.*`）。
