# v0.11.5 · 增量构建（task-70）

- 日期：2026-11-14（北京时间）· 工位：**site-ui**
- 范围：只改源码 + 临时构建；**未写 `site/dist`、未 commit/publish**
- 结论：**连续两次构建逐文件 diff 0**；共享 CSS 内容哈希命名、页面级 `?v=`；数据变化不再让 12 万页全变。

## 0. 结论与数字

| 项 | 结果 |
|---|---|
| 两次构建 | `.tmp/v0115-build` vs `.tmp/v0115-build2b` |
| 文件数 | **125,969 / 125,969**（集合完全一致） |
| 总字节 | **977,029,571 B**（两次完全相同） |
| 逐文件 diff | **0** |
| `i18n_check` | **FAIL 0** / WARN 2 / INFO 21 |
| `tests.test_markets_registry` | **47/47 OK** |

## 1. 改了什么

1. **共享 CSS 内容哈希文件名**：`site/build.py` 生成
   `assets/style.<sha256前10位>.css`（同时保留 `assets/style.css` 兼容旧缓存）；
   页面引用哈希文件，CSS 变 → 文件名变，只有引用它的页面变。
2. **页面级内容哈希**：`page()` 渲染完（含语言副本）后，对 HTML 取
   `sha256(html)[:10]`，注入 `?v=<pagehash>`（CSS / boot.js 引用）；
   内容不变的页面字节不变，不再带全局 `BUILD_V`。
3. **不再全局版本号**：页面 HTML 中去掉 `?v=BUILD_V`（CSS/JS/首页在线脚本）；
   `BUILD_V` 仅保留在 `assets/boot.js`、`assets/app.js`、`assets/atc4.js` 内部
   用于数据 JSON 的缓存参数；这些 JS 文件名稳定，页面不引用其内容哈希。
4. **首页**：保留首屏内联 CSS（构建期从 `CSS` 常量生成，不随数据变化）；
   `app.js` / `bilingual.js` 仍 load 后注入，但去掉全局版本号。
5. **空 CSS/JS 外置**：非首页统一 `<link rel=stylesheet href="assets/style.<hash>.css">` +
   `<script defer src="assets/boot.js?v=<pagehash>">`。

## 2. 三种改动场景的预计上传量（按本构建统计）

| 场景 | 预计上传 | 说明 |
|---|---|---|
| **改一条文案**（如 `about.lead`） | **15 个文件** | 5 个 About 语言页 + 5 个 `assets/i18n.*.js`（字典变）+ 5 个首页（首页内联当前语言字典） |
| 只改某一成分页的**局部说明**（不碰 i18n 字典） | **1 个文件** | 该 drug 页页级哈希变，其余页字节不变 |
| **改样式** | **125,751 个文件** | 125,750 个 HTML 引用 CSS（含 8,652 个内联首屏页）+ 1 个新 `style.<hash>.css`；旧 CSS 不再被引用 |
| **改数据**（DB/index） | **202 个文件 ≈ 218.5 MB** | 199 个 `data/**` + `boot.js`/`app.js`/`atc4.js`（内部含数据版本）；**HTML 页面 0** |

> 说明：JS 仍是稳定文件名（`boot.js`/`app.js`/…），内容变时上传 JS 但不改变页面 HTML；
> 因此数据变化不会造成全站 12 万页重传（这是本任务的主要收益）。
> CSS 变化仍会命中所有页面，因为所有页面共享同一张样式表；要做到「只传局部样式」需按组件拆 CSS（后续可做）。

## 3. 首屏 / FOUC

- 非首页 CSS 在 `<head>` 同步 `<link>`，**先在样式表加载后渲染**，不会出现无样式闪烁；
- 真实浏览器（Chromium，1440×900，`drug/acetaminophen.html?lang=zh`）：
  - `DOMContentLoaded` 时 `document.styleSheets` 已含 `assets/style.<hash>.css`；
  - `first-contentful-paint` ≈ **116 ms**（本地 127.0.0.1，无网络延迟）；
  - 背景色在 DCL 与 load 均为 `rgb(251,251,249)`，无样式跳变；
- 截图：`docs/img/v0115-fouc-drug-dcl-1440.png`（DCL 时）、`docs/img/v0115-drug-1440.png`（load 后）、`docs/img/v0115-home-1440.png`（首页内联 CSS）。

## 4. 未完成 / 注意

1. **JS 文件名仍是稳定名**（不是 immutable hash）：数据/代码变化时 `boot.js` / `app.js` / `atc4.js` 会更新字节；页面不重传，但这些 JS 的 CDN 缓存依赖 TTL。要完全 immutable，可下一轮把 JS 也改成内容哈希文件名 + 在 boot 中引用。
2. 首页仍内联整张 CSS（约 60 KB raw），CSS 变化会让 5 个首页变化；可进一步拆「首屏 critical CSS」。
3. 未跑 `deploy/first_screen_check.py` / `ui_interaction_smoke.py`（Chrome sandbox 限制）；上述 FCP 为 MCP Chromium 实测，非正式首屏守卫。
4. 构建目录 `.tmp/v0115-build` / `.tmp/v0115-build2b` 仅临时产物；`site/dist` 未动。
