# 首屏与移动端性能审计（v0.10.1 构建 · 2026-11-10）

> **性质**：只读审计。没有改代码、没有改 `site/dist`、没有写 `data/drugs.db`、没有跑 `site/build.py`、没有 commit / 发布。
> 临时脚本在 `.tmp/perf-audit/`（`measure.py` / `structure.py` / `medians.py` / `shell.py` / `anatomy.py` / `compute.py`，可复跑）。
> **快照**：`site/dist` = v0.10.1 构建产物，**121,293 文件 / 880,156,959 B（880.2 MB / 839.4 MiB）**，构建时间 2026-11-09 11:47–11:50（北京 11-10 03:47）。
> **线上仍是 v0.10.0**（`Last-Modified` 2026-11-07，首页 196,055 B / **71,624 B gz**，无 `__I18N_PARTIAL`）——本文 dist 数字是待发布的 v0.10.1，线上实测只用来校准传输字节。
> 依据：`docs/网站优化流程.md` §2.1 预算表 + `AGENTS.md` §1/§9 底线（本文不涉及任何用药建议、剂量换算或可替代判断）。

---

## 0. 结论速览

| # | 结论 | 关键数字 | 级别 |
|---|---|---|---|
| 1 | **首屏预算按「首页 en」看是过的，按「非英语用户」看是超的**：同一次访问，页面语言和内联字典不一致（`?lang=`、`localStorage`、`navigator.language` 指向 zh/es/繁）时，额外拉 165,747 B raw / 59,129 B gz 的四语 `i18n.js` | 首页 en 84,790 B gz（75.3% 预算）→ 非 en **143,919 B gz（127.8%）**；长尾页（12 万页）**102,970 B gz（91.4%，已含 `terms.json`）/ 427,223 B raw（126.4%）**，字典一项占该页首屏 gz 的 **57.4%** | **P1** |
| 2 | **首屏最大的一块是 JS 字典/应用脚本，不是 HTML**：首页 HTML 已降到 108,992 B（v0.10.0 是 196 KB），现在最大单项是 `app.js` 134,261 B（en）或 `i18n.js` 165,747 B（非 en） | app.js 49,652 gz = 首屏 gz 的 **58.6%**；i18n.js 59,129 gz = 非 en 首屏的 **41.1%** | **P1** |
| 3 | **搜索结果页真正的开销在「首搜数据 + 后台全量索引」**：首条结果前要 250–350 KB gz 数据（`aliases.json` 占 94 KB），结果一出又在后台无条件拉 `core.json` **9.89 MB gz**（线上实测 10,029,880 B） | 泰诺首搜 334,222 B gz；搜完后台 +9.89 MB gz，无 `saveData` / 弱网判断 | **P1** |
| 4 | **手机端仍难受的 3 处主体**：①长尾页「先英文后中文」、100.6 KiB 首屏里 57% 是字典；②成分页手机只显示 3/10 个市场、筛选器还是 JS 注入的 36px 复选框；③结果页 sticky 只包住输入框，计数/国家选择滚没了，20 张卡一屏 3.5 张 | 见 §3 的 M-1～M-5，每条都有 dist 行号/字节 | **P1** |
| 5 | **体积不是本批瓶颈**：880.2 MB 距 900 MiB 还 63.6 MB，距 Pages 1 GB 还 119.8 MB；全站 **0 组重复文件**（按 sha1 全量比对） | 唯一真·无损项是「noindex 页壳外置」≈ **75.7 MB**，但有 no-JS/内链代价 | P2 |
| 6 | **两处文档漂移要顺手改**：§2.1 的 `site/dist ≤ 810 MB` 早已被 880 MB 突破（v0.10.0 报告用的是 888.7 MB）；`core.json gz ≤ 9.5 MB` 现已 **9.89 MB（线上 10.03 MB）** | 首屏那一行（311 KB raw / 104 KB gz）也需要拆成「首页 / 非 en / 长尾」三档 | P1（口径） |

---

## 1. 方法与口径

- **字节口径**：`raw` = 文件字节；`gz` = 本地 `gzip.compress(data, 6)`（可复跑、可比较）。线上 GitHub Pages 用 gzip 传输，实测比本地 −6 大约 **+0.6%～+0.9%**（`app.js` 49,957 vs 49,652；`shard-cjk-t-0` 90,599 vs 89,776），所以本表 gz 只略偏乐观，不影响排序。
- **「首屏」定义**（本文两张表都用它）：一张页面从 HTML 到「可读、可交互」必须拿到的字节 = HTML（含内联 CSS/JS）+ 该页额外加载的 CSS/JS/字典；**不含**用户真的开始搜索后才拉的数据。
  - 另外单列「+ `terms.json`」：`bilingual.js`（每页都会加载）在 `start()` 里**无条件** `load().then(render)` 拉 `data/terms.json`（`site/dist/assets/bilingual.js` 尾部 `if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start)`），所以它虽然不是渲染阻塞，但每个页面首次访问都一定会下。
- **预算**（`docs/网站优化流程.md` §2.1）：首屏 ≤ **330 KB raw**（337,920 B）/ ≤ **110 KB gz**（112,640 B）；`core.json` gz ≤ 9.5 MB；分片单文件 ≤ 1.2 MB raw；dist ≤ 900 MiB（内部护栏）。
- **阻塞判定**：`<link rel="stylesheet">` = 阻塞渲染；`defer` 脚本 = 不阻塞但晚一拍；`window.addEventListener('load')` 里再插 `<script>` = 完全不阻塞；`document.head.appendChild(script)`（动态插入）= 默认 `async`，不阻塞解析，但会让文本二次改写。

---

## 2. 首屏资源实测

### 2.1 页面类型与数量（dist 现查）

| 页型 | 文件数 | 说明 |
|---|---:|---|
| 首页 `/index.html` + `/es/` `/zh/` `/zh-hant/` | 4 | 顶层壳：CSS 内联、`app.js`/`bilingual.js` 在 `load` 后注入 |
| 搜索结果页 | — | **没有独立文件**：`/index.html?q=…` 由 `assets/app.js` 客户端渲染 |
| 名字页 `name/*.html` | 77,059 | boot.js 壳，无 app.js |
| 厂家页 `maker/*.html` | 15,213 | 同上 |
| 组合页 `combo/*.html` | 15,202 | 同上 |
| 成分页 `drug/*.html` | 12,431 | 同上（矩阵服务端渲染、筛选器 JS 注入） |
| ATC 类目 `atc/*.html` + `atc.html` | 1,155 | L4 页额外 `atc4.js` |
| 大类页 `cat/*.html` | 16 | 同上 |
| 参考页（about/warn/confused/glossary/coverage/whats-new/404） | 25 | 7 个根页 + es/zh/zh-hant 各 6 个副本 |
| **HTML 合计** | **121,105** | 679,773,596 B（中位 4,256 B） |

### 2.2 每类页面首屏拆解（本地 gzip -6）

固定资源（所有非首页页面共用）：

| 资源 | raw | gz | 加载方式 | 阻塞 |
|---|---:|---:|---|---|
| `assets/style.css` | 37,694 | 9,643 | `<link rel=stylesheet>` in `<head>` | **是**（唯一阻塞项，1 个 RTT） |
| `assets/boot.js` | 15,316 | 2,650 | `defer` in `<head>` | 否 |
| `assets/i18n.js`（四语字典 153,871 + 代码 ≈11,876） | 165,747 | **59,129** | boot.js 在 `load` 后插入 | 否，但决定文本语言 |
| `assets/bilingual.js` | 18,366 | 5,242 | i18n.js `onload` 后插入 | 否 |
| `data/terms.json` | 185,921 | 24,669 | bilingual.js `DOMContentLoaded` 无条件拉 | 否 |
| `assets/atc4.js`（仅 ATC L4） | 3,211 | 1,609 | `defer` | 否 |
| 字体 | **0** | 0 | 系统字体栈（`@font-face` 计数 0） | — |
| GoatCounter `count.js`（第三方，跨域） | — | 未测 | `async` | 否（多一个 DNS+TLS） |

首页专用（内联壳）：

| 页 | HTML raw | HTML gz | 其中内联 CSS | 其中内联 JS（单语字典+壳） | 额外加载 |
|---|---:|---:|---:|---:|---|
| `/index.html` | 108,992 | 29,896 | 33,067 | 52,785（en 字典 39,344 + 13,441 壳） | `app.js` 134,261/49,652、`bilingual.js` 18,366/5,242 |
| `/zh/index.html` | 105,881 | 30,938 | 33,067 | 49,257 | 同上 |
| `/es/index.html` | 112,593 | 31,076 | 33,067 | 55,791 | 同上 |
| `/zh-hant/index.html` | 105,619 | 30,978 | 33,067 | 48,981 | 同上 |

**首屏合计（gz，含 `terms.json` 一列单列）**：

| 页型 | HTML gz | 额外资源 gz（style+boot+i18n+bilingual） | 首屏 gz（不含 terms） | 占 110 KB | + terms.json（24,669） | 占 110 KB |
|---|---:|---:|---:|---:|---:|---:|
| 首页 en | 29,896 | 54,894 | **84,790** | 75.3% | 109,459 | 97.2% |
| 首页 非 en（补载 i18n.js） | 29,896 | 114,023 | **143,919** | **127.8%** | 168,588 | **149.7%** |
| 名字页中位 | 1,637 | 76,664 | 78,301 | 69.5% | **102,970** | 91.4% |
| 成分页中位 | 2,063 | 76,664 | 78,727 | 69.9% | 103,396 | 91.8% |
| 厂家页中位 | 2,558 | 76,664 | 79,222 | 70.3% | 103,891 | 92.2% |
| 组合页中位 | 761 | 76,664 | 77,425 | 68.7% | 102,094 | 90.6% |
| ATC 类目中位 | 3,032 | 76,664 | 79,696 | 70.7% | 104,365 | 92.7% |
| ATC L4（+atc4.js） | 3,032 | 78,273 | 81,305 | 72.2% | 105,974 | 94.1% |
| 大类页中位 | 6,551 | 76,664 | 83,215 | 73.9% | 107,884 | 95.8% |

> 表内 HTML gz 为各页型抽样（400 页）中位数；`raw` 同理：名字页 4,179、成分页 5,329、厂家页 6,580、组合页 1,747、ATC 10,164、大类 43,522 B。
> 读法：**gz 口径下 12 万长尾页都在 90–94%（含 terms.json），没有超 110 KB**；超预算的是 raw 口径（427,223 B = 126.4%）和「非英语首页」（gz 127.8%）。raw 不是传输指标，所以真正要修的是「非英首页 + 字典体积」，不是「长尾页总数」。

### 2.3 首页 vs 预算：现查结论

- **en 用户（浏览器语言与页面内联字典一致）**
  - raw **261,619 B**（255.5 KiB）= 预算 330 KB 的 **77.4%** → 余量 **76,301 B（22.6%）**
  - gz **84,790 B**（82.8 KiB）= 预算 110 KB 的 **75.3%** → 余量 **27,850 B（24.7%）**
  - 把 `bilingual.js` 自动拉的 `terms.json` 算进「首屏必须」：raw 447,540 B（**132.4%，超 109,620 B**）、gz 109,459 B（**97.2%，只剩 3,181 B**）。
- **非英语用户（页面语言 ≠ 浏览器/`?lang=` 语言）**
  - raw **427,366 B（417.3 KiB）= 126.5%（超预算 89,446 B）**
  - gz **143,919 B = 127.8%（超 31,279 B）**；再加 `terms.json` 是 168,588 B（**149.7%**）。
  - 触发路径：`site/build.py:10304-10308`（`window.__I18N_PARTIAL && !D[window.LANG]` → 动态插入 `assets/i18n.js`）。中文用户打开 `/`（Google/Baidu 常见入口）就走这条。
- **首屏最大的一块**
  - en：`app.js` **134,261 B raw / 49,652 B gz**，占首屏 gz 的 **58.6%**（HTML 含内联 CSS/JS 总共才 108,992 B）。
  - 非 en：`i18n.js` **165,747 B raw / 59,129 B gz**，占非 en 首屏 gz 的 **41.1%**，单项超过 `app.js`。
  - 长尾页（12 万页）同理：一页 HTML 只有 4 KB，却要下 165,747 B 的字典 + 18,366 B 的 bilingual + 185,921 B 的 terms。

### 2.4 搜索链路（`?q=` 冷启动 → 首条结果）

`startSearch()`（`site/build.py:5123`）走分片：`manifest.json` + `loadSupport()`（`aliases.json` / `confused.json` / `categories.json`，`build.py:5031`）+ 1 个分片，**然后** `ensureCoreInBackground()`（`build.py:5085`）在后台拉全量 `core.json`。

| 查询 | 分片 | 首条结果前数据 raw / gz | + HTML + app + bilingual 后 raw / gz | 之后后台 |
|---|---|---:|---:|---|
| 泰诺 | `shard-cjk-t-0`（487,187 B） | 1,717,995 / 249,432 | 1,979,614 / **334,222** | +9,892,346 gz |
| 阿司匹林 | `shard-cjk-a-0`（742,425 B） | 1,973,233 / 302,946 | 2,234,852 / 387,736 | +9,892,346 gz |
| tylenol | `shard-t-3` | 1,939,364 / 277,731 | 2,200,983 / 362,521 | +9,892,346 gz |
| atorvastatin | `shard-a-6` | 2,331,013 / 329,926 | 2,592,632 / 414,716 | +9,892,346 gz |
| paracetamol | `shard-p-0` | 2,330,858 / 337,047 | 2,592,477 / 421,837 | +9,892,346 gz |
| ozempic | `shard-o-1` | 2,301,502 / 348,666 | 2,563,121 / 433,456 | +9,892,346 gz |

- 数据侧构成：`aliases.json` 892,886/94,123 + `categories.json` 299,356/54,846 + `manifest.json` 34,906/9,525 + `confused.json` 3,660/1,162 + 分片 89,776–185,022 gz。
- **`aliases.json` 是首搜第一大项（94 KB gz，约 1/3）**，而它只有命中「俗称/旧名」时才用得到。
- 输入框一聚焦就预取：`build.py:5330`（`box.addEventListener('focus', … fetchManifest(); loadSupport())`）→ 没输入任何字已经下了 **159,656 B gz**（manifest 9,525 + aliases 94,123 + categories 54,846 + confused 1,162）。
- `core.json` 只有聚合类区块需要（`const partial = !!(POOL_READY && !IDX_READY && !LEGACY)` → identity 卡/命中表在分片阶段已经出来，core 到位只是补国家视图/同成分/模糊/拼音）。

### 2.5 线上传输实测（HEAD，`Accept-Encoding: gzip`，v0.10.0）

| 资源 | 线上 Content-Length（gz） | 本地 gz -6 | `Cache-Control` |
|---|---:|---:|---|
| `index.html` | 71,624 | 29,896（v0.10.1 产物） | max-age=600 |
| `assets/i18n.js` | 59,343 | 59,129 | max-age=600 |
| `assets/app.js` | 49,957 | 49,652 | max-age=600 |
| `assets/bilingual.js` | 5,263 | 5,242 | max-age=600 |
| `assets/boot.js` | 2,711 | 2,650 | max-age=600 |
| `assets/style.css` | 9,820 | 9,643 | max-age=600 |
| `data/idx/core.json` | **10,029,880** | 9,892,346 | max-age=600 |
| `data/idx/shard-t-0.json` | 185,022 | 165,553（中位） | max-age=600 |
| `data/idx/shard-cjk-t-0.json` | 90,599 | 89,776 | max-age=600 |
| `data/aliases.json` | 97,453 | 94,123 | max-age=600 |
| `data/categories.json` | 55,252 | 54,846 | max-age=600 |
| `data/idx/pinyin.json` | 1,052,167 | 1,046,114 | max-age=600 |
| `data/artg.json` | 868,901 | 857,208 | max-age=600 |
| `data/idx/detail-f.json` | 276,456 | — | max-age=600 |
| `drug/orlistat.html` | 4,963 | 2,063（中位） | max-age=600 |
| `atc/A10.html` | 6,513 | 3,032（中位） | max-age=600 |

> 全部资源 `Cache-Control: max-age=600`（10 分钟）。这意味着**手机换页超过 10 分钟后，style/boot/i18n/bilingual 会整包重下**（9.6+2.7+59.1+5.2 = 76.6 KB gz），Pages 这一层改不了（不能自定义头）。

---

## 3. 移动端体验缺口（对照 `reports/ux-audit-20261030.md` / `ui-batch-b-20261107.md` 已做的）

> 已做、不再重复提的：首屏结果反馈（v0.9.1 P0-3）、移动端结果表/矩阵转卡片、底栏 56px + `main` 80px padding、按钮 ≥44px（`build.py:2833`、`3225-3230`）、`.has-q` 粘性搜索框（`2955-2958`）、语言下拉与 `aria-current`、字号 token 收敛（12/14/16/20/24）。
> 下面 5 条都是**现查仍存在**的，按「手机上的痛感 × 修起来的值」排序。

### M-1 12 万长尾页：手机先看英文，再闪成中文；字典占该页首屏 57%

- **证据**
  - `site/build.py:10248-10252`：`boot.js` 在 **`window load` 之后**才插 `assets/i18n.js`，`onload` 再插 `bilingual.js`。
  - `dist/name/feiba.html:5-8`：静态正文是英文（`<span data-i18n="name.found">Found in</span>`），中文靠 JS 二次改写。
  - `dist/assets/i18n.js` 165,747 B / **59,129 B gz**（四语：en 39,344 / es 42,627 / zh 36,093 / zh-Hant 35,807 B），线上 59,343 B gz。
  - `dist/assets/bilingual.js` 尾部 `DOMContentLoaded → start() → load()` 必拉 `data/terms.json`（24,669 B gz）。
- **影响**：中文用户从搜索结果点进名字页/成分页，第一眼是英文标题与表头；4G 上约 0.5–1.5 s 后整页文本翻成中文（视觉抖动）。名字页首屏 **102,970 B gz（91.4%，含 terms）**，其中字典一项 **59,129 B = 57.4%**；raw 口径 427,223 B（126.4%）。按 `max-age=600`，换页间隔超过 10 分钟就整包重下。121,101 个页面全部如此。
- **修法**
  - `_render_i18n_js()`（`build.py:10256-10316`）改成**按语言出文件**：`assets/i18n.<lang>.js`（每份 ≈14 KB gz：en 13,729 / es 14,439 / zh 14,397 / zh-Hant 14,294）+ 一份极小的 `i18n-meta.js`（`LANG_META_JS`/`pick()`/`canon()`，约 1.5 KB gz）。
  - `boot.js` 生成处（`10218-10252`）先跑 `pick()`（把 `i18n.js` 里的 `pick/canon/relPath` 抽成 `LANG_META_JS` 复用），**`en` 直接不加载**（页面本来就是英文），其它语言只拉自己那份。
  - 首页的补载分支（`10304-10308`）同样改成按 `window.LANG` 取包；`page()` 的 `head_scripts`（`6036-6049`）保持 `defer`。
- **预估**：名字页首屏 **102,970 → ≈59.7 KB gz（中文，58,238 B + ≈1.5 KB `i18n-meta.js`，51.7%）/ 43,841 B（英文，38.9%）**；非英首页 **143,919 → ≈100.7 KB gz（88.0%，回到 110 KB 以内）**。工作量 **1 天**（含 v0.10.1 那套 16/16 语言切换真浏览器回归）。

### M-2 搜一次就在后台吃掉 9.89 MB gz

- **证据**：`build.py:5085-5090` `ensureCoreInBackground()` = `setTimeout(()=>loadIndex(true),0)`，**没有任何网络/设备判断**；`startSearch()` 分片路径末尾必调（`build.py:5123` 起）。线上 `data/idx/core.json` gz **10,029,880 B**。`core.json` 只补「国家视图 / 同成分 / 模糊 / 拼音」等聚合区块，identity 卡与命中表在分片阶段已经渲染。
- **影响**：手机按 10 次查询算 ≈ **100 MB 流量**；弱网下这次 9.9 MB 会和下一次查询的分片抢带宽（第二次搜索反而变慢）；`saveData` 用户毫无办法。
- **修法**：`ensureCoreInBackground()` 加门控——`navigator.connection.saveData` 为真或 `effectiveType` 是 `slow-2g/2g/3g` 时**不预取**；否则用 `requestIdleCallback(…, {timeout: 8000})`；用户真的点「按国家看 / 同成分 / 拼音重试」时再 `loadIndex()`（这些入口已存在，只需在点击处补 `loadIndex()`）。
- **预估**：移动端 −9.89 MB gz/会话（弱网/省流完全不拉）；4G 下也只是把 9.9 MB 从「搜完立刻」挪到「空闲」。工作量 **0.5 天**，回归面小（分片路径不变）。

### M-3 成分页手机只看到 3/10 个市场，筛选器是 JS 后注入的 36px 复选框

- **证据**
  - `dist/drug/orlistat.html`：`th data-country` **10 个**，其中 `data-defcol` **只有 3 个**（US/ES/TW 按语言）；`mf-slot` 是空 `<div>`，`matrix-filters` 出现 **0 次** → 筛选器根本不是静态 HTML。
  - `build.py:7209-7215`：`default_cols` = 「本语言首选 + US + 次多」，最多 3 列；`build.py:3062-3063`：`table.matrix th/td[data-country]:not([data-defcol]){display:none}` **没有媒体查询**，手机卡片态一样生效。
  - 筛选器由 `bilingual.js:initMatrixFilters()` 注入（`build.py:5579-5586`），而 `bilingual.js` 要等 `i18n.js`（59 KB gz）加载完才动 → **换市场按钮的出现被 59 KB 字典阻塞**。
  - `build.py:3070`：`@media (max-width:767px){ .mf-countries label{min-height:36px} }` → 国家复选框 36px（< 44px）。
  - `build.py:3056-3057` + `7336`：`matrix-scroll-hint`（"Scroll horizontally for more markets →"）在 ≤767 显示，可手机上是卡片态、**根本没有横滑**。
- **影响**：手机看扑热息痛/布洛芬这种 10 市场成分，第一眼只看到 3 列，很容易得出「只有 3 国有货」的错误结论；要换市场得等字典下完 → 展开筛选 → 点 36px 小方块；提示文案还在讲横滑。
- **修法**
  - 卡片态放开全部市场：把 `3062-3063` 挪进 `@media (min-width:768px)`（或 ≤767 加 `table.matrix td[data-country]{display:block}` 覆盖），桌面默认 3 列的行为不变。
  - 卡片顶部加一行「显示 3/10 个市场 · 展开全部」（`_defcol_attr` 旁边就能拿到 `len(countries)` 与 `len(default_cols)`，`7204-7218`）。
  - `.mf-countries label` 36px → 44px；`matrix-scroll-hint` 只在 ≥768 显示。
- **预估**：手机成分页「换国家」从 4 步（滚动→等 JS→展开→点 7 次）降到 0–1 步。工作量 **0.5–1 天**。

### M-4 结果页 sticky 只包住输入框：命中数和「按国家看」滚两屏就没了

- **证据**
  - `dist/index.html:60-64`：`.searchwrap` 只包 `<label>`+`#q`+`#ac`；`:65-79` 的 `#meta`（命中数）与 `#country`（国家选择）在它**外面**。
  - `build.py:2955-2958`：`@media (max-width:767px){ .has-q .searchwrap{position:sticky;top:0} }` → 只有输入框吸顶。
  - `build.py:3746`：`const RES_PAGE = 20`（默认 20 行，「显示更多」每次 +20）；`build.py:3110-3125` 手机每行变一张卡（4 个字段 × 8px padding）。
  - 手机可视高度 844 − 底栏 56 − 吸顶搜索 ~60 ≈ **728 px**；一张卡 4 个字段 + padding 估算 **190–220 px** → 一屏约 **3.5 张卡**。
- **影响**：`paracetamol` 命中 314 条 → 要看到全部得点 **≈15 次「显示更多」**；滚到第 3 屏后看不见「共多少条」、也不能换国家（要一路滚回顶部）。
- **修法**：把 `#meta` 与 `#country` 一并放进 `.searchwrap`（`build.py` 首页模板 + `_optimize_home_html` 的包裹范围）；移动端 `RES_PAGE` 取 10（`matchMedia('(max-width:767px)')` 分支）；`.res-more{position:sticky;bottom:56px}`（避让底栏）。
- **预估**：手机结果页有效内容高度 +15%，改国家从「滚 N 屏」变 0 步。工作量 **0.5 天**。

### M-5 矩阵卡里最关键的字是 12px；大成分页一次渲染 120 张卡

- **证据**
  - `build.py:3011-3012`：`.m-en{font-size:12px}` / `.m-zh{font-size:12px}` —— 这是矩阵卡里「成分英文名 / 中文对照名」，也就是用户判断「这条到底是什么药」的信息（`7191-7194` 渲染）。
  - `build.py:6923`：`MATRIX_ROW_CAP = 120`；`dist/drug/acetaminophen.html` **635,933 B / 66,104 B gz**、121 行、3,278 处 `m-brand`；`dist/drug/octisalate.html` 559,337 B、`drug/ibuprofen.html` 366,580 B。ATC 顶层 `atc/A.html` 344,506 B / 35,127 gz。
  - 全站 ≥64 KB 的 HTML 有 **398 个（51.8 MB）**。
- **影响**：手机上「这个规格是什么成分」是全页最小的字；120 行 × 10 国的卡片态一次进 DOM，中低端机滚动掉帧、点按延迟（INP）；单页 66 KB gz 已吃掉首屏预算的 60%。
- **修法**：`.m-en/.m-zh` 提到 `--fs-sm`(14px)；`7264` 的 `shown = spec_rows[:MATRIX_ROW_CAP]` 改 20 行 + 服务端 `<details>` 续页（复用结果页 `RES_PAGE` 的交互），或在手机卡片态先只渲染前 20 行。
- **预估**：手机大成分页首屏渲染量 −83%（120→20 行），12px 信息可读。工作量 **1 天**（要同步 `mf`/`matrix` 的 JS 重排逻辑）。

**另有一条小项（顺手做）**：底栏「检索」永远 `href="index.html"`（`build.py:5954-5961`），从成分页/名字页点回检索会**丢掉 `?q=` 和结果状态**（移动端 header nav 在 ≤767 被隐藏，`3210`，所以底栏是唯一导航）。修法：`_shell_tabbar` 的 search 项读 `location.search` 或改成 `history.back()` 语义。0.2 天。

---

## 4. 体积余量

### 4.1 dist 结构（现查）

| 分区 | 文件数 | 字节 | 占比 |
|---|---:|---:|---:|
| 名字页 `name/` | 77,059 | 310,715,995 | 35.3% |
| 成分页 `drug/` | 12,431 | 148,940,652 | 16.9% |
| 厂家页 `maker/` | 15,213 | 138,664,850 | 15.8% |
| 组合页 `combo/` | 15,202 | 61,276,225 | 7.0% |
| ATC `atc/` | 1,154 | 17,420,243 | 2.0% |
| 大类 `cat/` | 16 | 824,689 | 0.1% |
| 顶层参考页 + 4 语言首页 | 30 | ≈2.0 MB | 0.2% |
| `data/` | 174 | 191,526,761 | 21.8% |
| `sitemap.xml` | 1 | 8,454,783 | 1.0% |
| `assets/` | 6 | 374,595 | 0.04% |
| **合计** | **121,293** | **880,156,959** | 100% |

`data/` 内部：shard 108 个 **90,779,761**、detail 51 个 **46,932,192**、`core.json` **41,492,440**、`artg.json` 4,866,373、`pinyin.json` 3,081,933、`atc4-forms.json` 1,206,924、`maker-map.json` 962,290、`aliases.json` 892,886、`exports/*.csv` 743,631、`categories.json` 299,356、`terms.json` 185,921、`export-only.json` 44,488、`manifest.json` 34,906、`confused.json` 3,660。

### 4.2 有没有「可无损压缩」的

- **重复文件：0 组**（121,105 个 HTML 全量 sha1 比对，`dup_groups = 0`）。没有可删的重复 HTML/JSON。
- **JSON 已经是字典编码 + 紧凑分隔符**（core 用 `cols` 字符串表；v0.10.1 已把 `i18n.js` 的 `separators` 收紧省 ~4 KB）。
- **同一批 195,553 行被编码了三份**：`core.json`（全量字典编码，41.5 MB）+ `shard-*`（按首字母切片，90.8 MB）+ `detail-*`（产品级明细，46.9 MB）。三者是**运行时的三种粒度**，谁都删不得（删 shard = 每次搜索重下 9.9 MB；删 detail = 行内「+N」打不开）。
- **真正可做的只有「壳外置」**：每页 `<header>`+`<footer>` 静态壳约 **1,401 B**（名字页抽样：header 817 + footer 557，占页面 35%）。boot.js 已经把 tabbar/nav 注入这条路铺好了（`10218-10252`）。

### 4.3 可省 MB 估算

| 方案 | 可省 | 代价 / 前提 | 建议 |
|---|---:|---|---|
| 只对 **noindex** 页外置壳（名字页 59.7% noindex、组合页 57%、厂家页 25.7%） | **≈75.7 MB**（64.4 + 5.5 + 5.8） | no-JS 用户没有导航；noindex 页不参与排名，内链损失可接受 | 逼近 900 MiB 时再做 |
| 全站外置壳（含 12,431 成分页、1,154 ATC 页） | ≈160.3 MB | **伤 SEO**（12 万页的内链是爬虫路径）+ 无 JS 不可用 | **不做** |
| `i18n.js` 按语言拆包 | dist **+0**（多 4 个小文件 ≈+150 KB） | 传输 −44.7～59.1 KB gz/页 | **做（v0.10.2）** |
| `aliases.json` 按首字母分片 | dist **+0**（拆成 ~30 个小文件） | 首搜 −85 KB gz | 做（v0.10.3） |
| `terms.json` 只在「显示原名」时拉 | dist **+0** | −24.7 KB gz/页 | 做（v0.10.3，注意默认 `SHOW=true`） |
| `core.json` 后台门控 | dist **+0** | 移动端 −9.89 MB gz/会话 | **做（v0.10.2）** |
| 重编码 core/shard/detail | 未知（乐观 15–25%，≈27–45 MB） | 要同时改 build.py 编码器 + app.js 解码器 + 分片协议；回归面最大 | **不做** |

**余量结论**：880.2 MB，距内部 900 MiB（943,718,400 B）**还 63,561,441 B**，距 Pages 1 GB **还 119,843,041 B**。v0.9.8 → v0.10.1 净 **−5 MB**，没有增长趋势 → **体积不是本批的瓶颈，传输字节才是**。

---

## 5. 排序

### 5.1 进 v0.10.2（本批就做：0.5–2 天，低风险，用户可感知）

| # | 改动 | 改哪儿（build.py） | 省多少 / 收益 | 工作量 | 验收 |
|---|---|---|---|---|---|
| 1 | `core.json` 后台拉取门控（saveData / 3G 不拉；空闲再拉） | `5085-5090`（`ensureCoreInBackground`）、`5123` 起的 `startSearch` 调用点 | 移动端 **−9.89 MB gz/会话**；4G 上首搜不再被 9.9 MB 抢带宽 | 0.5 天 | 分片结果不变；`?legacy=1` 路径不变；Chrome 网络面板确认 3G 模拟下无 core 请求 |
| 2 | `i18n.js` 按语言拆包 + en 跳过 | `10256-10316`（`_render_i18n_js`）、`10218-10252`（boot.js 生成）、`10304-10308`（首页补载）、`6036-6049`（`head_scripts`） | 长尾页 102,970 → **58,238 B gz（中文）/ 43,841 B（英文）**；非 en 首页 143,919 → **99,187 B gz（88.0%，回预算内）** | 1 天 | 4 入口 × 4 语言 16/16、`?lang=` 4/4、localStorage 3/3（复用 `.tmp/qa-v0101/` 的浏览器脚本）；三语抽查 |
| 3 | 移动端 sticky 区补 `#meta` + `#country`；`RES_PAGE` 手机取 10 | 首页模板 + `_optimize_home_html`（`8137`）、`3746`、CSS `2955-2958` | 一屏看到命中数与「按国家看」；长列表点击次数 −50% | 0.5 天 | 390×844 下滚 3 屏仍能看到 `#meta`；20 行→10 行不破 `显示更多` |
| 4 | CSS 三处小修：`.mf-countries label` 44px、`.m-en/.m-zh` 14px、`matrix-scroll-hint` 只在桌面 | CSS `3070`、`3011-3012`、`3056-3057` | 触控目标合规；矩阵卡关键信息可读；提示文案不再误导 | 0.2 天 | 390 宽截图对照 + 计算样式抽查 |
| 5 | 口径更新：§2.1 首屏行拆「首页 en / 非 en / 长尾」；`core.json gz` 预算 9.5 → 10.5 MB 或写明现状；dist 行改 900 MiB | `docs/网站优化流程.md` §2.1 | 预算表和现实对齐，避免下次审计拿旧数字 | 0.2 天 | 数字与本文一致 |

> 这批的净效果：**12 万长尾页首屏 gz 从 102,970 → 58,238 B（中文，−43%）/ 43,841 B（英文，−57%）**，非英首页从 143,919 → 99,187 B（回到预算内），移动端每次搜索不再白吃 9.9 MB，手机结果页与成分页的 3 个具体卡点消失。全部改动都在 `site/build.py` 内，不动数据、不动 DB、不碰 §1 底线。

### 5.2 进 v0.10.3（要动渲染结构或索引协议，1–3 天/项）

| # | 改动 | 改哪儿 | 收益 | 工作量 |
|---|---|---|---|---|
| 6 | 成分页手机放开全部市场 + 「显示 3/10 · 展开全部」 | CSS `3062-3063`、`7209-7218`、`7332-7336` | 手机不再误判覆盖市场 | 1 天 |
| 7 | 矩阵分页（20 行 + `<details>` 续页），替代 `MATRIX_ROW_CAP=120` 一次渲染 | `6923`、`7264`、`7300-7320` | 大成分页首屏 DOM −83%；`acetaminophen` 66,104 gz → **约 14 KB 量级（估）** | 1.5 天 |
| 8 | `aliases.json` 按首字母分片（`aliases-<key>.json` + `cjk-*`） | `5031` `loadSupport`、别名输出函数、`shardsForQuery` 同款协议 | 首搜 **−85 KB gz**（泰诺 334,222 → ≈249 KB） | 1 天 |
| 9 | `terms.json` 只在「显示原文对照」开启时拉（默认关，或首次切换才拉） | `bilingual.js` 的 `load()` 调用点、`SHOW` 默认值 | −24.7 KB gz/页 | 0.5 天 |
| 10 | Lighthouse 移动端基线（v0.9.2 之后就没再跑，§2.1 四项 ≥90 一直未复验） | 无代码改动；用 DevTools/PSI 跑首页/成分页/名字页/atc | 把「预算」从字节口径扩到 LCP/CLS/INP | 0.5 天 |
| 11 | 底栏「检索」保留 `?q=`（或 `history.back()`） | `5954-5961` `_shell_tabbar` | 手机从详情页回结果不再重打 | 0.2 天 |

### 5.3 不做（附理由）

| 不做的事 | 理由 |
|---|---|
| 重编码 `core.json` / shard / detail（179.2 MB） | 运行时收益已被分片解决；改编码要同步 build + app 解码 + 分片协议，回归面最大，收益（估 27–45 MB）只影响 dist 体积，而体积还有 63.6 MB 余量 |
| 121k 页静态壳全部外置（≈160 MB） | 12 万页内链是爬虫主路径；无 JS 直接不可用。只在逼近 900 MiB 时对 noindex 子集做（75.7 MB） |
| 引入 web font / 图片 / 第三方脚本 / Service Worker | 字体 0 B 是优点；SW 在 Pages 上收益不确定且易出缓存事故；`docs/网站优化流程.md` §2.4（安全/隐私）明确不引第三方脚本 |
| 把 `app.js`（134 KB）再拆 | 它已经在 `load` 后注入，不占 LCP；拆了只省 4G 上的空闲带宽，回归面（搜索/导出/自动完成/筛选）却很大 |
| 登录 / 账号 / 收藏 / 付费 / 任何「剂量换算」「能不能互换」 | `AGENTS.md` §1.3 + §9 红线，本报告的所有建议都只动字节与交互，不碰身份语义 |
| 为体积删 `detail-*`（46.9 MB） | 行内「+N」产品明细是「同一成分哪些产品」的唯一入口，删了等于砍功能 |

---

## 6. 复跑命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 0) 总量 / 文件数 / 0 字节 / HTML 数（§4.1）
(Get-ChildItem site/dist -Recurse -File).Count
[math]::Round((Get-ChildItem site/dist -Recurse -File | Measure-Object Length -Sum).Sum/1MB,1)
(Get-ChildItem site/dist -Recurse -File | Where-Object Length -eq 0).Count
& $py -c "import pathlib; p=pathlib.Path('site/dist'); print(sum(f.stat().st_size for f in p.rglob('*') if f.is_file()))"

# 1) 按目录 / 扩展名 / data 明细（§4.1）
Get-ChildItem site/dist -Directory | ForEach-Object {
  $s = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum)
  [pscustomobject]@{Dir=$_.Name; Files=$s.Count; MB=[math]::Round($s.Sum/1MB,1)}
} | Sort-Object MB -Descending

# 2) raw + gzip 双口径（§2.2，本次所有 gz 数字都是这个口径）
& $py .tmp/perf-audit/measure.py        # 页型抽样 + assets/idx 体积 → .tmp/perf-audit/measure.json
& $py .tmp/perf-audit/structure.py      # HTML 体积直方图 / noindex / 重复 sha1 / 首搜分片 → structure.json
& $py .tmp/perf-audit/medians.py        # 各页型 raw/gz 中位数（400 页抽样）
& $py .tmp/perf-audit/shell.py          # 各目录 noindex 占比 + 壳字节占比（体积余量）
& $py .tmp/perf-audit/anatomy.py        # i18n 四语字典体积 / 长尾页解剖
& $py .tmp/perf-audit/compute.py        # 首屏/首搜组合总字节 vs 预算

# 3) 单文件 gz（示例：core.json / i18n.js）
& $py -c "import gzip,pathlib; p=pathlib.Path('site/dist/data/idx/core.json'); b=p.read_bytes(); print(len(b), len(gzip.compress(b,6)))"

# 4) 线上传输实测（§2.5；HEAD 带 Accept-Encoding: gzip）
$ProgressPreference='SilentlyContinue'
Invoke-WebRequest -Uri 'https://fuarnos.github.io/drug-brand-crossref/assets/i18n.js' `
  -Method Head -Headers @{'Accept-Encoding'='gzip'} -UseBasicParsing |
  ForEach-Object { $_.Headers['Content-Length']; $_.Headers['Cache-Control'] }
```

---

## 7. 未测 / 已知缺口

1. **没跑 Lighthouse / 没上真机**：§2.1 的 `四项 ≥ 90`、`LCP < 2.5s / CLS < 0.1 / INP < 200ms` 从 v0.9.2（2026-10-30）之后就没复验过；v0.10.0 改过整套 CSS/布局。本文只有字节口径，**不能替代 lab 数据**（第 5.2 节第 10 项）。
2. **线上不是本次构建**：线上 `v0.10.0`（`Last-Modified` 2026-11-07，首页 71,624 B gz），dist 是 v0.10.1 待发布产物（首页 29,896 B gz）。§2.5 的线上字节只用来校准 gzip 差（+0.6%～0.9%），不代表 v0.10.1 上线后的表现。
3. **`?q=` 首搜的 gz 是「理论值」**：等于 manifest+aliases+categories+confused+1 分片的本地 gzip 之和；实际浏览器还会并行拉 `style.css`/`boot.js`（长尾页）或 `app.js`/`bilingual.js`（首页），已按首页口径计入。
4. **`navigator.connection` 覆盖率**：Safari 不支持 `connection.saveData/effectiveType`，M-2 的门控在 iOS 上会退化成「总是预取」——需要 `requestIdleCallback(timeout)` 兜底（iOS 也不支持 idle callback，用 `setTimeout(…, 3000)` 等价）。
5. **未验证 `gzip` 之外的压缩**：Pages 实测只给 gzip（`Content-Encoding: gzip`），brotli 不可控；如果将来上 Cloudflare 之类的前置，`core.json` 9.89 → 约 8 MB（估算，未实测）。
6. `data/idx/atc4-forms.json`（1.2 MB）只在部分 ATC L4 页按需拉，未计入首屏表；`maker-map.json`（962 KB）只在搜索结果渲染厂家时用。
7. 本文所有 gz 用本地 zlib −6；线上实测比本地大 0.6%～0.9%（gzip 级别差异），排序不变。

---

## 8. 五句话回答

1. **现在首屏最大的一块是 `app.js` 134,261 B raw / 49,652 B gz**（首页 en，占首屏 gz 58.6%）；非英语用户和 12 万长尾页上更重的一块是 `i18n.js` **165,747 B raw / 59,129 B gz**（四语字典全量，占非 en 首屏 41.1%）。
2. 首页 en 首屏 **261,619 B raw / 84,790 B gz**，比 330 KB / 110 KB 预算还剩 76,301 B raw（22.6%）与 27,850 B gz（24.7%）；但**非 en 是 427,366 B / 143,919 B gz，超预算 26.5% / 27.8%**；12 万长尾页 gz 102,970 B（91.4%，含 terms）但 raw 427,223 B（126.4%）——**预算事实上只在「en + 首页」这一种组合里全过**。
3. 移动端最该修的 **1 件事**：把 `i18n.js` 按语言拆包（en 干脆不加载），长尾页首屏从 **102,970 B gz 降到 58,238 B（中文）/ 43,841 B（英文）**，非英首页从 143,919 B 降回 99,187 B，同时消掉 12 万页上「先英文后中文」的闪烁——改 3 处 `build.py`，1 天，风险最低、用户最容易感知。
4. 第二值得做的是 `ensureCoreInBackground()` 的弱网/省流门控：移动端每次搜索后台白拉 **9.89 MB gz**，加上「输入框聚焦就预取 **159,656 B gz**」这条隐形成本，手机上搜 10 个名字约 100 MB。
5. **这一批值得做**：5 项合计约 2.5 天（`site/build.py` 单文件 + 一次 `docs` 口径更新），换来 12 万长尾页首屏 gz **−43%（中文）/ −57%（英文）**、非英首页回到预算内、移动端流量 −90%、手机结果页/成分页 3 个具体卡点消失；体积侧不急（距 900 MiB 还有 63.6 MB），所以不做重编码索引这类大手术，把 75.7 MB 的壳外置留作逼近上限时的预案。
