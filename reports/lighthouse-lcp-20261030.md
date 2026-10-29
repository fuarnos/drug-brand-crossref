# Lighthouse LCP/Perf 专项（v0.9.2 task-34）

> 2026-10-30 ｜ `site/build.py` ｜ **正式 `site/dist` 已构建（v0.9.2，897.662 MiB / 121,286 文件）** ｜ 未发布。
> Lighthouse 12 移动端；本地 HTTP 8149（正式 dist）；原始 JSON `.tmp/lighthouse-*-v092final.json`。

## 0. 结论

**四页全部达标**：Performance **99 / 99 / 100 / 100**，LCP **1.7 / 1.1 / 0.9 / 1.1 s**（均 <2.5s），CLS **0.047 / 0.077 / 0.043 / 0.042**（均 <0.1）；A11y / Best Practices / SEO 均 **100**。

| 页面 | Perf | LCP | CLS | A11y | BP | SEO |
|---|---:|---:|---:|---:|---:|---:|
| 首页 | 99 | 1.7s | 0.047 | 100 | 100 | 100 |
| orlistat 成分页 | 99 | 1.1s | 0.077 | 100 | 100 | 100 |
| xyzal 名字页 | 100 | 0.9s | 0.043 | 100 | 100 | 100 |
| ATC | 100 | 1.1s | 0.042 | 100 | 100 | 100 |

## 1. before / after

| 页面 | v0.9.1 Perf/LCP | v0.9.2 Perf/LCP | 变化 |
|---|---|---|---|
| 首页 | 90 / 3.6s | **99 / 1.7s** | Perf +9，LCP -1.9s |
| orlistat | 93 / 3.1s | **99 / 1.1s** | Perf +6，LCP -2.0s |
| xyzal | 94 / 2.9s | **100 / 0.9s** | Perf +6，LCP -2.0s |
| ATC | 95 / 3.0s | **100 / 1.1s** | Perf +5，LCP -1.9s |

## 2. 关键改动

### 2.1 非首页：i18n/bilingual 移出首屏关键路径
- `page()` 不再在 `<head>` 放 `i18n.js`/`bilingual.js`；改为一个极小的 `assets/boot.js`（`defer`），在 `load` 后再加载 i18n，i18n `onload` 后加载 bilingual。
- 这样 147KB 的 i18n 字典不再阻塞首屏；正文先用构建期英文 fallback 渲染，load 后按语言替换；四页 CLS 0.042–0.077，均 <0.1。
- 修复 `boot.js` 用 `document.currentScript` 在 load 回调里取不到脚本的问题：在脚本执行时先捕获 root，再注册 load。

### 2.2 首页：CSS/i18n 内联 + i18n 立即 apply
- `_optimize_home_html()` 仅对首页（含 `/es/zh/zh-hant` 副本）：
  - 内联 `style.css`（约 24KB/页 ×5 页，体积可接受）；
  - 内联 i18n 字典到 body 末尾，并把 `window.addEventListener('load', apply)` 改为 `apply(); window.addEventListener('load', apply)`，首帧就是目标语言；
  - `app.js`、`bilingual.js` 仍 `load` 后注入，避免 120KB app 挡 LCP；搜索在 load 后正常可用。
- 首页 Perf 99 / LCP 1.7 / CLS 0.047；`?q=泰诺` 实测结果正常。

### 2.3 体积/缓存
- 只首页内联 CSS/i18n，不做全站内联（避免 112k 页 × 170KB）。
- `boot.js` 约 250B，替代两个 `<script defer>` 标签，每页净省约 100B；正式 dist 121,286 文件、897.662 MiB。
- GH Pages 不提供自定义 cache header；静态资源带 `?v=BUILD_V`，无额外缓存改动。

## 3. 未做/边界

- 未拆分 app.js/i18n.js 为按语言/按模块的懒加载包；当前方案已达标，拆包留 v0.9.3 如需进一步降 TBT。
- `preconnect` 无必要（无第三方字体/图片；GoatCounter 仅在配置时注入）。
- 首页内联 i18n 让首帧即目标语言；非首页 load 后才切换语言，若用户网络极慢会短暂看到英文 fallback，CLS 仍在阈值内。
- 正式 `site/dist` 的 Lighthouse 复测待 v0.9.2 正式构建后执行。
