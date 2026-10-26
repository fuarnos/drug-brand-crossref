# 索引 P0 懒加载实现报告

> 任务：task-4（索引 P0 懒加载）。依据：`reports/index-perf-plan.md` §0 / §4.1 / §5。
> 实现：`site/build.py` 内嵌 `APP_JS` + 首页 HTML 提示；行为等价性用「旧 v0.3.3 app.js 对拍」验证。
> 本任务未跑 git、未发布、未跑 deploy/publish.ps1、未改 `site/dist`、`data/drugs.db` 或其他跟踪文件。
> 验证产物在 `.tmp/dist-lazyload/`（SITE_OUT 构建）与 `.tmp/dist-lazyload/_verify/`（验证脚本）。

---

## 0. 结论

| 指标 | 现状 v0.3.3 | 本次 P0 | 依据 |
|---|---:|---:|---|
| 首屏（用户未输入）传输 | ≈6.08 MB | **≈17.0 KB（gzip -9 本地估算）** | §3 体积测量 |
| 页面加载时请求 index/aliases/confused | 是（`Promise.all`） | **否（0 个 fetch）** | Node 行为测试 A2 |
| 首次输入/聚焦/点示例、或 `?q=` | 已下载完 | 才开始下载 6 MB 索引 | 行为测试 B/C/D |
| 检索数据 / 匹配逻辑 | — | **逐字节未变，render 输出逐查询一致** | 对拍测试 G + 构建产物对拍 |

首屏 = `index.html` + `assets/app.js` + `assets/i18n.js` + `assets/style.css`，本地 gzip -9 合计 **17,030 B**（raw 43,609 B）；对 6.06 MB 的 index.json 只在实际搜索/聚焦时请求。

## 1. 改动点（只改了 `site/build.py`）

### 1.1 `APP_JS` 状态（L418–420）

```js
// P0 索引懒加载：页面加载时只下 app.js/css/i18n（约 16 KB），
// 全量索引（34.8 MB，gzip 约 6 MB）等用户真的要用搜索时再下。
let IDX_READY = false, IDX_P = null;
```

`render()` 及其以下所有逻辑（`tier`、`aliasHits`、`confHits`、国家视图、同成分、品牌族、
`rowHTML` 徽标、ARTG 兜底）**一行未改**；`IDX/NICKS/CONF` 的数据结构和加载后的渲染路径也不变。

### 1.2 新增懒加载段，替换原结尾「页面加载即 `Promise.all`」（L727–797）

- `loadIndex()`：幂等加载器（`IDX_P` 缓存 Promise，`IDX_READY` 标记完成），一次 `Promise.all`
  拉 `data/index.json`（`?v=` 缓存破坏仍由构建时 replace 注入）+ aliases + confused；成功清提示并 `render`。
- `startSearch()`：未加载 → `loadIndex().then(ok => render())`；已加载 → 直接 `render()`（原路径）。
- 触发时机：`box.addEventListener('input', startSearch)`、`ctry.addEventListener('change', startSearch)`、
  示例按钮 click、`box.addEventListener('focus', …)` 预取、`?q=` 深链立即 `startSearch()`。
- 失败回退：catch 中把 `IDX_P = null`（允许重试），在 `#out` 显示中英错误 + `<button data-retry>重试 / Retry</button>`，
  点重试重新 `loadIndex()` 后按当前输入渲染；同时保留「本地双击打开需 `python -m http.server`」提示。
- `?legacy=1`：跳过懒加载，页面加载即拉全量索引 + 旧「Loading index…」提示，一键回滚旧行为。
- 页面加载时唯一执行的 fetch 相关代码都在函数体内（静态测试 A 断言：全文 `data/index.json` 只出现 1 次且位于
  `function loadIndex` 之后；无顶层 `Promise.all`）。

### 1.3 首页提示（`build_index_page`，L1469–1470）

`<p class="sub" id="loadhint">首次搜索需要加载索引，约 6 MB（gzip 压缩后，之后浏览器会缓存）。First search needs to load the index (~6 MB gzipped; cached after the first time) — start typing, focus the search box, or pick a sample.</p>`

三份落地页（`/`、`/es/`、`/zh/`）共用该 body，提示随构建生成；加载开始时文案改为「正在加载索引…」，
加载完成后隐藏；`?legacy=1` 时隐藏。输入框、国家下拉、示例按钮、页脚与报告链接均保持可用。

## 2. 构建命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:SITE_OUT='D:\同种药物商品名剂量对应网站\.tmp\dist-lazyload'
& $py -X utf8 site/build.py
```

构建结果（退出码 0）：

```
building index ... 126915 keys
building nickname index ... 422 nicknames
building confused index ... 44 directions
building ARTG name index ... 34594 ARTG names
...
== done ==
  drug pages : 12870   name pages : 17868   confused : 22 pairs
  index.json : 34.8 MB  total size : 134.2 MB
```

`site/dist` 未被改动：构建前后 `assets/app.js`、`index.html`、`data/index.json` 的 SHA256 完全一致
（`A27D0E50…`、`2A64F824…`、`D1735CD2…`）。

## 3. 验证证据

验证脚本都在 `.tmp/dist-lazyload/_verify/`，可复跑：

```powershell
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
& $node --check .tmp\dist-lazyload\assets\app.js
& $node --max-old-space-size=4096 .tmp\dist-lazyload\_verify\lazyload.test.mjs
& $py -X utf8 .tmp\dist-lazyload\_verify\parity_check.py
# HTTP 冒烟（临时端口）：
& $py -X utf8 -m http.server 8791 --bind 127.0.0.1 --directory .tmp\dist-lazyload
& $node .tmp\dist-lazyload\_verify\http_check.mjs http://127.0.0.1:8791/
```

### 3.1 `node --check` 与静态检索

- `node --check .tmp/dist-lazyload/assets/app.js` → 通过（无输出，exit 0）。
- 构建产物 `assets/app.js` 中 `data/index.json` 只出现 **1 处**，在 `function loadIndex` 内：
  `fetch(BASE + 'data/index.json?v=1793055301')`；顶层无 `Promise.all`/fetch。
- 三份 `index.html` 均含 `id="loadhint"`、中英提示、`assets/app.js?v=`，无 `preload index.json`。

### 3.2 Node 行为测试（DOM 桩 + 真实数据，8 项全过）

```
PASS  A. 静态：加载期零请求路径 — 唯一 index fetch 在 loadIndex() 内；HTML 有中英提示；无 preload
PASS  A2. 页面加载零 fetch，中英提示可见，input 可用
PASS  B. focus 预取索引（含 aliases/confused），未输入不渲染
PASS  C. 首次 input 触发加载，完成后按现有 render 出结果
PASS  D. ?q= 深链立即加载并渲染
PASS  E. ?legacy=1 一键回滚为页面加载即拉全量索引
PASS  F. 索引失败提示 + 重试，重试成功后正常渲染
PASS  G. 旧/新 app.js 逐查询输出完全一致（18 查询 + 3 国家视图）
== ALL 8 CHECKS PASSED ==
```

G 项把 `site/dist/assets/app.js`（v0.3.3 旧版）与构建产物放在同一 DOM 桩里，用**真实**
`data/index.json`（126,915 条）、`aliases.json`、`confused.json`、`artg.json` 逐查询比对
`out.innerHTML`、`meta.textContent`、ARTG 区域，**18 个查询 + 3 个国家视图全部逐字节相同**；
覆盖精确命中、模糊、昵称/俗称、易混淆药对、同成分、品牌族、ARTG 兜底、CJK contains、
SEV/WARN 碰撞徽标、国家选择（例：`Lipitor 20mg`/`Lipitor`/`泰诺`/`两只青蛙`/`利嗪`/
`acetazolamide`/`aspirin`/`Gaviscon`/`Benadryl`/`Metformin 500mg`/`盐酸西替利嗪片`/`Lipit0r`/
`amoxicillin`/`ibuprofen` 等）。

### 3.3 HTTP 冒烟（`python -m http.server` 临时端口 8791，用后即停）

```
PASS  index.html HTTP 200 — 200, 3862 chars
PASS  index.html 有懒加载提示元素 / 中英提示可见（UTF-8 解码正常）
PASS  index.html 引用 app.js 且带版本号 / 无 index.json 预加载
PASS  es/index.html、zh/index.html 同上（各 6 项）
PASS  app.js HTTP 200 — 200, 16709 chars
PASS  app.js 含 loadIndex() / 只引用一次 data/index.json / 含 ?legacy=1 / 含失败重试按钮
PASS  未知路径 404
== HTTP: 24/24 checks passed ==
```

### 3.4 全量构建产物对拍（vs 现有 `site/dist`，30,755 个文件）

```
旧构建文件: 30,755  新构建文件: 30,757  逐字节一致: 9
代码改动（预期）: ['assets/app.js', 'es/index.html', 'index.html', 'zh/index.html']
换行符差异（既有，非本次改动）: ['.nojekyll']
仅 ?v= 版本号不同的 HTML: 30,500
仅「规格列表」同数字排序抖动（既有 PYTHONHASHSEED 随机）: 241 个 name 页
data/index.json / aliases.json / confused.json / artg.json: 逐字节一致
== PASS ==
```

- 差异只有：`assets/app.js`（本次改动）、3 个落地页（新增 `#loadhint`）、
  所有 HTML 的 `?v=BUILD_V`（每次构建必变）、`.nojekyll` 换行符、241 个 name 页的规格排序抖动。
- 后三者都不是本次改动：`.nojekyll` 在旧 `site/dist` 里的 mtime 是 15:32:44（该次构建 15:31:50 结束后被其他脚本改成 LF，
  而当前 build.py 在 Windows 上写 CRLF）；name 页规格列表用 `sorted(集合, key=只取数字)` 输出
  （`build.py` L1365/L1409），数字相同的「4 %/4 g/4 mg」随 `PYTHONHASHSEED` 换序，实测：
  `seed=1 → ['2 %','4 g','4 mg','4 %']`，`seed=2 → ['2 %','4 %','4 g','4 mg']`，属既有行为。

### 3.5 首屏体积（本地 gzip -9；线上 Pages 动态 gzip 会有 ±4% 校准差）

| 资源 | raw | gzip -9 |
|---|---:|---:|
| `index.html` | 3,968 B | 1,652 B |
| `assets/app.js` | 18,995 B | 7,835 B |
| `assets/i18n.js` | 16,133 B | 6,076 B |
| `assets/style.css` | 4,513 B | 1,467 B |
| **首屏合计** | **43,609 B** | **17,030 B** |

对比旧版首屏另加 `index.json`（raw 34,795,787 / gzip -9 5,823,313）+ aliases（gzip 17,725）+ confused（gzip 881）。
首搜仍是一次 6 MB 下载（P0 的目标只是「没输入不下载」，首搜字节由 P1/P2 再降）。

## 4. 残余风险

1. **focus 预取**：用户点进搜索框但没输入也会开始下 6 MB。这是任务要求的触发时机；若更在意流量，
   删掉 `box.addEventListener('focus', …)` 一行即可改为「仅 input/示例/?q= 才加载」。
2. **`?q=`/国家深链、点示例按钮**仍会立刻下载 6 MB（本来就需要出结果），只是发生在用户动作之后。
3. **加载中重复输入**：加载未完成时每次 input 都会挂一个 `then(render)`，完成后可能多渲染 1–3 次
   （结果始终取当前输入，无功能影响）；P0 未加 debounce 以保持行为最小改动。
4. **失败重试只重试一次**：网络持续失败会停在错误+重试提示；不会静默降级（索引未到时无法搜索）。
5. **浏览器缓存**：`index.json` 带 `?v=BUILD_V`，每次发版后首次搜索仍重新下 6 MB；aliases/confused 无 `?v=`
   （既有行为，未改变）。
6. **未在真机浏览器里点过**：本任务用 Node DOM 桩 + 真实数据对拍旧版输出，并做了 HTTP 冒烟；
   真机验证建议发布前用手机/桌面 Chrome 各点一次（输入、focus、`?q=`、`?legacy=1`、断网重试）。
7. **验证脚本在输出目录内**：`.tmp/dist-lazyload/_verify/` 的 3 个脚本每次重新构建会被清空；
   该目录只用于验证，正式发布仍走 `site/dist` + 既有发布流程（本任务未发布）。

## 5. 回滚方法

| 层次 | 操作 | 生效范围 |
|---|---|---|
| ① 免发布（最快） | URL 加 `?legacy=1`，如 `…/?legacy=1` | 当前浏览器立即恢复「页面加载即拉全量索引」旧行为 |
| ② 恢复源码 | `git checkout -- site/build.py` 后重新构建/发布（由 Lead 执行；本子智能体未跑 git） | 回到 v0.3.3 行为 |
| ③ 发布后回滚 | gh-pages revert 上一提交（涉及 `assets/app.js` + 3 个 `index.html`，数据文件未变，无需重建数据） | 线上恢复旧版 |
| ④ 只去掉预取 | 删 `site/build.py` L784 的 `focus` 监听后重新构建 | 保留懒加载，点输入框不再预取 |

## 6. 交付物 / 写范围

- `site/build.py`：3 处改动（L418–420 状态、L727–797 懒加载段、L1469–1470 首页提示）。
- `.tmp/dist-lazyload/`：SITE_OUT 构建产物（30,755 个构建文件 + `_verify/` 3 个验证脚本）。
- `.tmp/dist-lazyload/_verify/{lazyload.test.mjs, parity_check.py, http_check.mjs}`：可复跑的验证脚本。
- `reports/lazyload-implementation.md`：本报告。
