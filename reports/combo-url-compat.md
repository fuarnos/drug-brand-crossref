# 旧 combo URL 兼容（v0.9.2 task-33）

> 2026-10-30 ｜ `site/build.py` ｜ **正式 `site/dist` 已构建（v0.9.2，121,286 文件 / 897.662 MiB / sitemap 63,359）** ｜ 未写 DB、未发布。

## 0. 结论

- 对 v0.9.1 体积策略裁剪掉的**全部 8,455 个**旧组合页生成极简 noindex stub；v0.9.0 的 combo URL（含 AU-only 旧组合）不再 404。
- stub 返回 **200**，含成分页链接、`noindex,follow`，**不进入 sitemap**。
- 正式构建：**121,286 文件 / 897.662 MiB / sitemap 63,359**；≤900 MiB。

## 1. 逻辑

`build_combo_pages` 对 `COMBO_PAGE_SLUGS` 之外的旧组合统一写 `combo/<slug>.html`：
- 标题、成分列表（有 drug 页则链接，否则纯文本）、中英文「组合页暂未展开」、搜索入口；
- `<meta name="robots" content="noindex,follow">`；`NOINDEX_RELS.add()`；
- 不调用 `page()`，避免每页带 header/footer/JS；stub 约 1KB。

## 2. 覆盖验证

- v0.9.1 pre-strategy 构建（`.tmp/dist-v091`，15,191 combo）与 v0.9.2 对比：**0 缺失**。
  - 当前正式 combo 6,736 + stub 8,455 = 15,191；全部旧组合 URL 有页。
- 抽查 AU-only 旧组合 stub `13c-urea+urea+urea-13c.html` → HTTP **200**；`noindex,follow`；sitemap 中不存在。
- 内部链接：索引 `cu` 仍只指向正式 combo（6,736）；stub 不参与内部链接，只做旧 URL 兼容。

## 3. 数量/体积

| 项 | v0.9.1 正式 | v0.9.2 正式 |
|---|---:|---:|
| 文件数 | 112,822 | 121,286 |
| combo 页 | 6,736 | 15,191（6,736 正式 + 8,455 stub） |
| sitemap | 63,359 | 63,359（stub 不进） |
| 体积 | 893.6 MiB | 897.662 MiB |

> 体积仍 ≤900 MiB；stub 8,455 个约 9.5MB；docs/data-dictionary.md 另复制进 dist。全局 dataset link 只放 About/首页，抵消了部分增量。

## 4. 验收

- [x] 旧 combo URL（含 AU-only）返回 200
- [x] stub noindex,follow
- [x] stub 不进 sitemap
- [x] ≤900 MiB
- [x] 未写 DB / 未发布
- [x] 报告完成

已知：所有 8,455 个被裁剪组合均已补 stub；若后续新增组合，仍按 `COMBO_PAGE_SLUGS` 规则决定正式页/stub。
