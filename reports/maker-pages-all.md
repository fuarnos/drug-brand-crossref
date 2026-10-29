# task-20：全量厂家页（含单产品厂家，代码完成，构建待 DB 窗口）

> 2026-10-29 ｜ `site/build.py` ｜ 未写 DB、未改数据、未构建。

## 0. 结论

- 阈值从 ≥5 产品降为 **1**：`data/maker_candidates.csv` 中所有非占位厂家都生成独立页（slug 沿用现有逻辑，旧 URL 不破坏）。
- 实测 **15,213 个厂家页**（原 6,997，新增 8,216）；其中 **4,238 个单产品厂家页**：`noindex,follow`、不进 sitemap，底部四语标注「目前未收录该厂家的其他产品」。
- 结果行 `mu/ml` 现在覆盖全部有页厂家；明细面板新增厂家列，按 `data/maker-map.json` 懒加载映射为可点链接。
- 未建页的 DB MAH 815 个（如 `70541`、`801576526`、`S+`）为占位/编号类脏值，CSV 已排除；不违背「占位/未知厂家不建页」。

## 1. 改动

| 项 | 实现 |
|---|---|
| 页数 | `MAKER_MIN_PRODUCTS = 1`；`load_makers` has 全开；页面循环覆盖 15,213 |
| 单产品页 | `n_products==1` → 底部 `maker.single_note` 四语；`NOINDEX_RELS.add("maker/<slug>.html")`；`page(noindex=True)` |
| sitemap | `build_seo_files` 跳过 `NOINDEX_RELS` |
| 明细 | `build_maker_pages` 写 `data/maker-map.json`（原始 MAH→slug）；结果明细新增 Maker 列，`loadMakerMap()` 懒加载后渲染 `<a class="maker-link">` |
| 文案 | en/es/zh + zh-Hant（UI_I18N）：No other products from this manufacturer recorded yet / Sin otros productos... / 目前未收录该厂家的其他产品。 |

## 2. 复核

```powershell
& $py .tmp/cat2/task6_smoke.py           # 单产品厂家页：noindex=True、maker-single-note=True、maker-map 生成
& $py .tmp/cat2/maker_counts.py          # 15,213 厂家 / 4,238 单产品 / 815 DB MAH 不在 CSV
```

## 3. 缺口 / 待办

- 全量构建后核对：maker 页总数、单产品页 noindex、sitemap 不增、抽样单产品页底部文案、旧 URL 可访问。
- 体积/构建耗时待最终 build 记录（预计 +~25–40MB；单页 ~5.7KB，多产品页沿用原模板）。
