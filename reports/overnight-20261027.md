# 谷段自动工作汇报 — 2026-10-27（北京时间 00:35–08:20）

## 结论

- **v0.5.0 已发布上线并打 tag/Release**：https://fuarnos.github.io/drug-brand-crossref/（tag `v0.5.0`，Release 已建）
- 线上 smoke **33/33 通过**（deploy/verify_live.py --expect-version v0.5.0），/warn 40 条、About 许可/ATC 双口径、pinyin 索引、GoatCounter 均验证
- 8 个 teammate 全部复用：搜索、UI P0、i18n P1、/warn、中文俗名、ATC/ChEMBL、GB 盐型、MX per_volume、WHO INN、许可、发布护栏、指标

## 数据变化（before → after）

| 指标 | 数值 |
|---|---|
| 产品 / 成分 / variant | 409,485 / 12,790（-3 WHO INN 合并）/ 13,869（GB 盐型 +127） |
| ATC 覆盖 | 全部 46.0% → **47.5%**；药物实体 64.9% → **67.0%**（ChEMBL +192） |
| MX 浓度 | 34.1% → **35.2%**（per_volume +125） |
| GB 盐型组件 | 1,313 → **16,396**（2.0% → 25.0%） |
| `nickname` / `drug_term` / `alias_all` | 57 / 365 → **1,062** / 422 → **1,119**（+1,034 俗名，-337 毒品黑话） |
| `dose_warning` | 41 条（published 5 → **40**；draft 1 保留） |
| 页面 | 30,246 HTML / 30,258 文件；drug 12,377 / name 17,861 / sitemap 30,245 |
| 首搜 / 首屏体积 | 3.78 MB gz / 41 KB gz（+拼音 0.41 MB 懒加载） |

## 上线内容（v0.5.0）

1. **搜索增强**：exact Map + 前缀 + CJK bigram 倒排 + 拉丁 trigram/Levenshtein + 拼音/首字母；难例 24/28→28/28，匹配 P50 94→1.1 ms，`?legacy=1` 可回退。
2. **UI P0**：国家选择器无匹配显式提示、搜索解析条、自动完成、成分聚合/品牌折叠/加载更多、<720px 卡片化。
3. **三语 P1**：About / What's new / Confused / 404 全页三语；About 逐源许可署名与 ATC 双口径（构建期动态）。
4. **/warn 页**：40 条 AI 核验警示 + 34 个成分页摘要；不给用药建议。
5. **数据**：ATC/ChEMBL、GB 盐型、MX per_volume、WHO INN 3 条、中文俗名 1,034 条、清理毒品/娱乐黑话 337 行、schema v0.4 迁移。

## 测试与验证

- `etl` 25 项 OK；`lib` 29 项 OK；`mobile` OK；`db/check_data.py` 通过；integrity/FK 检查 ok
- 发布后 smoke 33/33：首页/页脚 v0.5.0、whats-new、core.json（gzip 3.79 MB）、About、4 关键页、sitemap、404、GoatCounter
- 线上额外验证：/warn 40 条、About 许可段 + 47.5%/67.0%、pinyin 1.23 MB、成分页警示链
- 三语回归（354 查询）：**72 例通过 67；Top-5 97.5%、Top-1 95.8%、跨国可见 72/72**（与 v0.4.1 基线持平，无回归；明细 `.tmp/trilingual/results_v050.json`，用时 824.6s）

## 未完成 / 下一步

- 搜索评测集 300+（模板已备）与零结果事件；索引 P2 分片（首搜 → ~0.1 MB）；UI P1 余项（身份卡/筛选/骨架屏）
- 数据长尾：ES 208 复方、CN 剩余合并、dose_warning 西语正文、AU ARTG FOI（需用户本人递交）
- 发布护栏尚未自动接进 `deploy/publish.ps1`（脚本已就绪，建议下一版接入自动回滚）

## 报告索引

reports/search-engine-bench.md、search-engine-v2.md、ui-p0-impl.md、i18n-p1-impl.md、warn-page-impl.md、warn-verify.md、cn-slang-*.md、drug-term-cleanup.md、atc-chembl.md、gb-salt-recovery.md、mx-pervolume.md、who-inn-merge.md、license-audit.md、release-guardrails.md、metrics/2026-10-27.json
