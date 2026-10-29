# Lighthouse 基线（v0.9.0，2026-10-30）

> 作用：task-22 优化前基线。原始 JSON：`.tmp/lighthouse-home.json`、`-drug.json`、`-name.json`、`-atc.json`（本地 8124，v0.9.0 `site/dist`；Lighthouse 12，移动端默认节流）。
> 修复后见 `reports/lighthouse-optimization.md`。

| 页面 | Performance | Accessibility | Best Practices | SEO | LCP | CLS | TBT |
|---|---:|---:|---:|---:|---:|---:|---:|
| 首页 | 69 | 93 | 96 | 100 | 3.9s | 0.309 | 80ms |
| 成分页 orlistat | 73 | 100 | 96 | 91 | 2.1s | 0.688 | 30ms |
| 名字页 xyzal | 93 | 97 | 96 | 91 | 2.9s | 0.082 | — |
| ATC | 93 | 100 | 96 | 91 | 3.0s | 0.021 | — |

主要失败：
- 首页 A11y：`aria-allowed-attr`（`input#q` 的 `aria-expanded`）；Perf：render-blocking JS（i18n.js/app.js）+ CLS 0.309。
- 成分页：CLS 0.688（矩阵筛选器/默认列 JS 加载后改布局）；SEO `meta-description`；BP favicon 404。
- 名字页：`heading-order`（卡片 h3 跳过 h2）；SEO `meta-description`。
- ATC：SEO `meta-description`；BP favicon 404。

结论：优化前只有名字页/ATC 的 Performance ≥90；成分页 CLS、首页 A11y/Perf、四页 SEO/BP 是主差距。
