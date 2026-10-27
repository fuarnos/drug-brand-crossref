# 三语（en / es / zh）P0 修复报告

> 任务：task-16。依据 `reports/i18n-audit-20261026.md` §3/§4/§7 的 P0 清单。
> 范围：只做 P0（APP/首页/药品页受控词三语化、语言状态持久化、hreflang 子路径、i18n.js 单次加载、
> #loadhint 三语）。**不改** About / What's new / Confused / 404 整页内容（P1）。
> 约束遵守：未跑 git、未发布、未改 `site/dist`、`data/drugs.db` 或其他跟踪文件。
> 构建产物：`.tmp/dist-i18n/`；验证脚本：`.tmp/dist-i18n/_verify/`。

---

## 0. 结论

| # | 要求 | 状态 | 证据 |
|---|---|---|---|
| 1 | APP_JS 受控文案三语（懒加载提示/加载中/失败/重试/报告 issue 模板） | ✅ | `app-p0.test.mjs` 5/5；app.js 旧混排字符串静态检查通过 |
| 2 | 药品页受控词三语（状态词 + 状态说明 + 无商品名 + 也叫/俗称） | ✅ | 12,864 个 drug 页全量扫描：0 处旧中英混排；4 种状态样本断言通过 |
| 3 | `pick()` 路径命中写 localStorage；切语言保留 `?q=`；i18n.js 每页 1 次 | ✅ | `i18n-p0.test.mjs` 4/4（含 8 场景语言矩阵）；所有页面 i18n.js 计数 = 1 |
| 4 | hreflang 用 GitHub Pages 项目子路径 | ✅ | 3 个入口 `href="https://fuarnos.github.io/drug-brand-crossref/{es,zh}/"`，无 `/es/` 根路径 |
| 5 | `#loadhint` 三语 | ✅ | `data-i18n="home.hint_idle"`，es 文案含 "índice"，zh 含「首次搜索需要加载索引」 |

I18N 字典：**112 keys × en/es/zh**（原 91 + 新增 21），0 缺失、0 空值。

---

## 1. 改动清单（只改了 `site/build.py`）

### 1.1 I18N 字典：新增 21 键 × 3 语言

| 键 | en | es | zh |
|---|---|---|---|
| `home.hint_idle` | L83 | L191 | L299 |
| `home.hint_loading` | L86 | L194 | L301 |
| `error.index_failed` / `error.local_file` / `error.retry` | L87–90 | L195–198 | L302–305 |
| `drug.status.active/discontinued/withdrawn/unknown` | L115–117 | L223–225 | L330–332 |
| `drug.status_note.discontinued/withdrawn/unknown` | L117–119 | L225–227 | L330–332 |
| `drug.no_brand` / `drug.also_called` | L120 | L228 | L333 |
| `nick.tag` | L146 | L255 | L356 |
| `report.issue_title` / `report.field_query/page/expected/actual/pack` | L165–170 | L273–278 | L368–373 |

（en 行号 L83–170、es L191–278、zh L299–373；同一顺序。）

### 1.2 `APP_JS`（内嵌页面脚本）

- **报告 issue 模板三语**（L773–787）：`reportURL()` 的标题与 5 个字段名改为
  `Tr('report.issue_title')` / `Tr('report.field_*')`，不再硬编码「查询词 / query」「数据错误:」。
- **`Tr()` + 提示常量三语**（L790–802）：新增 `function Tr(k)`（`window.T` 的降级包装）；
  `HINT_IDLE = Tr('home.hint_idle')`、`HINT_LOADING = Tr('home.hint_loading')`。
  `setHint()` 首次由脚本接管时 `removeAttribute('data-i18n')`，避免 i18n.js 的 `apply()`
  把「正在加载…」覆盖回静态 idle 文案。
- **失败提示三语**（L866–878）：`Tr('error.index_failed')` + `Tr('error.local_file')` +
  重试按钮 `Tr('error.retry')`，失败后恢复 idle 提示。
- **`?legacy=1` 加载提示**（L905）：复用已有但此前未用的 `home.loading`（三语）。

### 1.3 首页 `#loadhint`（L1603）

`<p class="sub" id="loadhint" data-i18n="home.hint_idle">…</p>`：静态英文 fallback + `data-i18n`，
由 i18n.js 按语言替换为 es/zh；`/`、`/es/`、`/zh/` 三份落地页共用。

### 1.4 药品身份页受控词（`build_drug_pages`）

- 新增常量（L1322–1333）：`STATUS_WORDS`、`STATUS_NOTES`、`STATUS_NOTES_EN`。
- 状态列（L1420–1433）：状态词改为
  `<span data-i18n="drug.status.{status}">{status}</span>`；discontinued/withdrawn/unknown
  追加 `<span data-i18n="drug.status_note.{status}">…</span>`（三语）。
- 无商品名（L1421–1422）：`<span class="meta" data-i18n="drug.no_brand">(no brand name)</span>`
  （取代「（无商品名）」）。
- 昵称行（L1449–1451）：`Also called:` → `data-i18n="drug.also_called"`；
  `nickname` 标签 → `data-i18n="nick.tag"`（取代「Also called 也叫：」「nickname 俗称」）。

### 1.5 `page()`：hreflang 子路径 + i18n.js 单次加载

- hreflang（L939–946）：`href="/{path}"` → `href="{SITE_URL}{path}"`
  （`SITE_URL = https://fuarnos.github.io/drug-brand-crossref/`），`x-default` → `SITE_URL`。
  修复线上项目子路径下 `/es/` 指向域名根 404。
- 删除 `<footer>` 之后重复的 `<script src="…assets/i18n.js">`（L952 保留 `<head>` 内唯一一次），
  `page()` 生成的 30,738 个页面不再重复执行 i18n IIFE/apply。

### 1.6 `i18n.js`（main() 生成段，L2087–2151）

- `pick()` 路径命中写 `localStorage`（L2104–2107）：直入 `/es/`、`/zh/` 后点导航不再掉回 en。
- **额外发现并修复**：原 `seg[0]` 判断在 GitHub Pages 项目子路径下恒为 `drug-brand-crossref`，
  即线上 `/es/` 的路径语言识别实际失效；现改为按站点根（由 `document.currentScript.src`
  反推 `rootPath`）相对路径识别（L2091–2101）。本地 http.server 根路径下审计未暴露此问题。
- `langTarget()` + `setLang()`（L2123–2138）：启用原死代码；切换时
  **入口页**（`/`、`/es/`、`/zh/`）跳到对应语言入口并合并保留 `?q=`/`?country=` 等全部参数；
  **子页面**（drug/、name/ 等）留在原页、仅加/改 `lang` 参数，查询参数不丢。
- 语言切换链接拦截（L2140–2145）：`document` 委托点击 `a[data-lang]` → `setLang()`；
  带 `ctrl/meta/shift/alt` 或非左键时不拦截（保留新标签页打开）。无 JS 时仍保留原 `?lang=` 链接。

---

## 2. 构建

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:SITE_OUT='D:\同种药物商品名剂量对应网站\.tmp\dist-i18n'
& $py -X utf8 site/build.py
```

退出码 0，产物：`drug pages 12864 / name pages 17868 / index.json 34.8 MB / total 155.8 MB`。
`site/dist` 未被改动（app.js/i18n.js/index.html/data/index.json 的 mtime 仍为 18:17–18:18 那次构建）。

## 3. 验收证据（全部可复跑）

```powershell
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
& $node --check .tmp\dist-i18n\assets\app.js      # exit 0
& $node --check .tmp\dist-i18n\assets\i18n.js     # exit 0
& $node .tmp\dist-i18n\_verify\i18n-p0.test.mjs   # 4/4 PASS
& $node .tmp\dist-i18n\_verify\app-p0.test.mjs    # 5/5 PASS
& $py -X utf8 .tmp\dist-i18n\_verify\static_check.py   # 61/61 PASS
# 临时 http.server 冒烟（用后即停）：
& $py -X utf8 -m http.server 8792 --bind 127.0.0.1 --directory .tmp\dist-i18n
& $node .tmp\dist-i18n\_verify\http_check.mjs http://127.0.0.1:8792/   # 21/21 PASS
```

关键结论摘录：

- **i18n-p0.test.mjs**：I18N 112 keys ×3 一致；语言矩阵 8/8
  （含 `/es/`、`/zh/` 直入写 localStorage；子页 localStorage/navigator 回退；`?lang=` 覆盖）；
  切换 URL 断言：`/index.html?q=Lipitor&country=US` → `…/es/?q=Lipitor&country=US`、
  `/es/index.html?q=…` → `…/?q=…`、`/drug/ibuprofen.html?q=…` → 原页 `?q=…&lang=zh`；
  ctrl+click 不拦截。
- **app-p0.test.mjs**：es 失败提示为「No se pudo cargar el índice / Reintentar」且无中英混排；
  zh/en 各自正确；加载中提示为 es 且摘掉 `data-i18n`；`?legacy=1` 用 `home.loading` es；
  GitHub issue 标题/字段 en/es/zh 三语。
- **static_check.py（61/61）**：3 个入口 hreflang 全部绝对子路径、4 类齐全、x-default 正确、
  i18n.js 仅 1 次且在 `<head>`；about/confused/whats-new/name/drug 页 i18n.js 均 1 次；
  drug 页 4 种状态 data-i18n 断言 + 全量 12,864 页扫描旧混排受控词 0 命中；
  找到昵称行/无商品名样本并断言；`app.js` 受控文案全部 `T()`、旧混排字符串 0 残留；
  `i18n.js` 的 pick/切换/拦截逻辑静态断言全部通过。
- **数据未动**：aliases/confused/artg 与索引 P1 构建（`.tmp/dist-p1`）逐字节一致；
  index.json 条目数与键集合一致，578 条差异**仅为 `s`（规格）字段** —— 因 `data/drugs.db`
  在 P1 构建（18:42）之后被数据任务更新（mtime 18:45:30），与本次 i18n 改动无关；
  core.json 可解析、n=126,915、列结构与 P1 一致。
- **HTTP 21/21**：`/`、`/es/`、`/zh/` 200 + 正确 `html lang` + 绝对 hreflang + i18n.js 单次 +
  loadhint 键；drug 页状态词 data-i18n；assets 正常。

## 4. 残余风险 / 未做（按审计优先级）

1. **未在真机浏览器点过**：验收为 Node vm（真实 DOM/事件桩）+ http.server 冒烟；发布前建议手机/桌面
   Chrome 各点一次「直入 /es/ → 点 About 是否保持 es」「切换语言后 ?q= 是否保留」。
2. **数据层 es 缺失**（审计 §6，P2）：昵称解释有中文 hint 422 条、英文 me 197 条、西语 0 条；
   es 用户看到的昵称详情仍会是英文（或空），不是字典能修的。
3. **About / What's new / Confused / 404 的整页正文**仍按审计 P1 范围未动：es 用户在这些页面仍见
   中英混排（如 Confused 的 Source 段、404 页）。
4. **SEO/布局仍属 P2/P1**：`<title>` 三入口仍相同且站名重复、无 meta description；
   CSS 仍无 `@media`，es 长导航在窄屏可能溢出（审计 §5）。
5. **无 JS 降级**：静态 HTML 里药品页受控词 fallback 为英文；语言切换无 JS 时仍走旧的 `?lang=`
   相对链接（会丢 q），但页面仍可读。
6. **子页 `<html lang>`** 静态仍为 en，靠 i18n.js 在 DOMContentLoaded 修正（P2）。
7. **hreflang 仍只有 3 个入口**；About/What's new/Confused 无静态 es/zh 副本（P3）。

## 5. 回滚方法

| 层次 | 操作 |
|---|---|
| 源码回滚 | `git checkout -- site/build.py` 后重新构建/发布（由 Lead 执行；本子智能体未跑 git） |
| 免发布降级 | 单页可用 `?lang=en|es|zh` 覆盖语言；语言切换是纯前端行为，旧 `?lang=` 链接仍有效 |
| 发布后回滚 | gh-pages revert 上一提交（改动集中在 `assets/app.js`、`assets/i18n.js` 与全部 HTML 的受控词/hreflang） |

## 6. 交付物

- `site/build.py`：I18N +21 键 ×3、APP_JS 4 处受控文案、首页 loadhint、药品页 4 类受控词、
  hreflang、i18n.js 生成逻辑（pick/切换/单次加载）。
- `.tmp/dist-i18n/`：SITE_OUT 构建产物（30,750 个构建文件，含 30,739 个 HTML 页面 + `_verify/` 验证脚本）。
- `.tmp/dist-i18n/_verify/{i18n-p0.test.mjs, app-p0.test.mjs, static_check.py, http_check.mjs}`：可复跑验收脚本。
- `reports/i18n-p0-fix.md`：本报告。
