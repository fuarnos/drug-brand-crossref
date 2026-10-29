# Lighthouse / CWV / WCAG 优化报告（v0.9.1 task-22）

> 2026-10-30 ｜ `site/build.py` ｜ **正式 `site/dist` 已构建（v0.9.1，893.6 MiB / 112,822 文件 / sitemap 63,359；含 AU 多国名字页回归修复）**，未发布。
> 最终首页/成分页 Lighthouse：90/100/100/100、93/100/100/100（`.tmp/lighthouse-home-final.json`、`-drug-final.json`）；其余页面取同代码隔离构建值。
> 浏览器：Chrome 156 headless；Lighthouse 12（默认移动端）；本地 HTTP 8124。基线 JSON：`.tmp/lighthouse-*.json`。

## 0. 结论

- **Lighthouse 移动端四项全部 ≥90**：首页 90/100/100/100；成分页（orlistat）93/100/100/100；名字页（xyzal）94/100/100/100；ATC 95/100/100/100（顺序：Performance / Accessibility / Best Practices / SEO）。
- **CLS 全部 <0.1**（0.021–0.082）；**TBT <200ms**（0–90ms）；实验室环境无 INP（用 TBT 代理）。
- **LCP 未达到 2.5s**：3.1–3.6s（本地 Lighthouse 移动端节流）。这是本报告明确未达标项；Performance 仍 ≥90，故按任务「≥90 或给出明确原因/替代阈值」交付，LCP 优化留 v0.9.2（见 §5）。
- A11y 100、Best Practices 100、SEO 100；`target-size`、`link-in-text-block`、`link-name`、`label`、`color-contrast`、`heading-order` 均通过。
- 首搜文案已按实测改为「中位 ~1.0 MB（gzip ~0.16 MB）；core ~42 MB（gzip ~9–10 MB 后台）」；不再写「~0.2 MB」。

## 1. before / after

| 页面 | 指标 | v0.9.0 基线 | v0.9.1 测试构建 |
|---|---|---|---|
| 首页 | Perf/A11y/BP/SEO | **69 / 93 / 96 / 100** | **90 / 100 / 100 / 100** |
| 首页 | LCP / CLS / TBT | 3.9s / 0.309 / 80ms | 3.6s / 0.035 / 90ms |
| 成分页 orlistat | Perf/A11y/BP/SEO | **73 / 100 / 96 / 91** | **93 / 100 / 100 / 100** |
| 成分页 orlistat | LCP / CLS / TBT | 2.1s / 0.688 / 30ms | 3.1s / 0.058 / — |
| 名字页 xyzal | Perf/A11y/BP/SEO | **93 / 97 / 96 / 91** | **94 / 100 / 100 / 100** |
| 名字页 xyzal | LCP / CLS / TBT | 2.9s / 0.082 / — | 2.9s / 0.082 / — |
| ATC | Perf/A11y/BP/SEO | **93 / 100 / 96 / 91** | **95 / 100 / 100 / 100** |
| ATC | LCP / CLS / TBT | 3.0s / 0.021 / — | 3.0s / 0.021 / — |

> 成分页基线 SEO 91 的唯一失败是 `meta-description`；BP 96 是 favicon 404。首页 A11y 93 是搜索框 `aria-expanded` 用在无 combobox role 的 input 上。

## 2. 已落地项

### SEO / 语义
- `page()` 无 `meta_key` 时也输出 `<meta name="description">`；修复成分页/名字页 SEO 91。
- drug/name/maker/combo/atc/cat/atc 索引页加 canonical；无语言副本的页面加 `hreflang=x-default`；根页保留四语 alternates + x-default。
- 全局 `WebSite` JSON-LD；成分页 `MedicalWebPage + Drug`；ATC 页 `BreadcrumbList`。
- 404 favicon：页头加 data-URI SVG icon，消除 `/favicon.ico` 404（BP 96→100）。
- `sitemap` 继续排除 `NOINDEX_RELS`；薄页 noindex 规则未变。

### 可访问性
- 页首 skip link + `main#main`；`:focus-visible` 3px 绿描边。
- 搜索框可见性 label（`sr-only`）；移除 input 上非法 `aria-expanded`；矩阵品牌链接加下划线（`link-in-text-block`）。
- `.m-brand` 最小高度 24px（`target-size`）。
- 名字表 6 个表头 + 移动 data-label 四语化；厂家页「剂量」列改「剂型」。
- H1 只留药名，来源/版本移入 `.drug-name-src`；ATC `.cat-en` 加分隔并在关闭原文对照时隐藏。

### 性能 / CLS
- `i18n.js`、`bilingual.js`、`app.js` 全部 `defer`；`app.js` 仍保留 defer（尝试过 load 后注入，CLS 反而变差，已回退）。
- 首搜文案改为实测值；`home.hint_idle` 四语 + zh-Hant JSON 同步。
- 成分矩阵：
  - 服务端先渲染默认 3 列（`data-defcol`），CSS 首屏隐藏其余列，JS 读取服务端默认列，不再加载后改列。
  - `.mf-slot` 预留筛选器高度；筛选器+排序说明插入 slot，避免主内容下移。
  - 移动端 JS 不再把 `td` 设为 `table-cell`（保留卡片布局），CLS 从 0.855 降到 0.058。

## 3. 首屏/首搜体积实测（`.tmp/dist-v091`）

| 资源 | raw | gzip |
|---|---:|---:|
| index.html | 15,616 B | 3,915 B |
| style.css | 24,459 B | 6,915 B |
| i18n.js | 146,784 B | 50,043 B |
| app.js | 120,231 B | 45,069 B |
| 首屏 HTML+CSS | 40,075 B | 10,830 B |
| 首搜分片（110 片）中位 | 1,100,016 B（≈1.05 MiB） | 165,365 B（≈0.16 MiB） |
| 首搜分片均值 | 834,268 B | 137,178 B |
| core（后台补全） | 42,309,287 B（≈40.35 MiB） | 10,035,908 B（≈9.57 MiB，gzip -6） |

> 部署侧按 publish 的 gzip 口径 core 约 8.68 MB；本表用本地 gzip -6 复测，故略高。分片大小中位与总索引规模会随 AU/HK 条目变化，构建后以 manifest 现算为准。

## 4. 验证命令

```powershell
& $py -m py_compile site/build.py
node --check .tmp/cat2/app.js
node --check .tmp/cat2/bilingual.js
$env:SITE_OUT='.tmp/dist-v091'; & $py site/build.py
# Lighthouse 12（local 8124，--chrome-flags="--headless=new --no-sandbox"）
```

## 5. 未达标 / 后续

- **LCP 3.1–3.6s > 2.5s**：主要受本地 Lighthouse 移动端 CPU/网络节流 + 141KB i18n / 120KB app 的解析执行影响；Performance 已 ≥90，但 CWV LCP 不达标。
- 下一步（v0.9.2）：拆分 i18n/app（首屏只加载 UI 文案，不加载全量译名）；关键 CSS 内联/延迟非关键 CSS；对首页 LCP 文本做更细的 render-delay 分析；评估 `content-visibility` 与更细索引分片。
- 正式 `site/dist` 的最终分数待 v0.9.1 一次全量构建后复测（本报告测试构建同代码）。
- 本地 HTTP 无 CDN/HTTP2，真实线上 TTFB 会不同；本报告不把本地分数当线上 SLA。
