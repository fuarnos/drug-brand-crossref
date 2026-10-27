# 中文俗名入库 drug_term（Tier B）报告

日期：2026-10-27 ・ 任务：task-31 ・ 站点版本：v0.3.5
产物：`etl/ingest_cn_slang.py`、本报告；撤销清单目录 `.tmp/cn-slang-ingest/`
本轮**未写真实 `data/drugs.db`**（Lead 审后再 apply）；apply/回滚验证只在 `.tmp/cn-slang-ingest/drugs-test.db` 副本上做。

---

## 1. 摘要

| 指标 | 结果 |
|---|---|
| 输入候选（`data/cn_slang_candidates.csv`） | 1,108 行（Tier B） |
| **可入库 `drug_term`** | **1,034 行** |
| 跳过 | 74 行（全部是 `substance_id` 为 `cn-*`，等成分合并后另跑） |
| kind（term_type） | folk 1,022 / class 12 |
| 来源（source_id） | wikipedia_zh 961 / community_web_cn 71 / wikidata 2 |
| confidence | documented 426 / community 608（按来源族重算；与 CSV 差异 5 行，见 §4） |
| 新增 source 行 | 4：`wikipedia_zh`、`wikidata`、`alihealth_cn`、`community_web_cn` |
| `nickname` 变化 | **0**（本轮只写 `drug_term`） |
| 预计入库后 | `drug_term` 365 → 1,399；`alias_all` 视图 422 → 1,456 |

---

## 2. 字段对齐（`db/schema.sql` → 本脚本）

| drug_term 列 | 来源 |
|---|---|
| `term` / `term_norm` | CSV `term` / `normalized`（候选已做 NFKC、去标点、人工繁简归一） |
| `term_type` | CSV `term_type`（folk/class；本轮无 street/brand_generic） |
| `country` | `CN` |
| `label_zh` / `label_en` | CSV `label_zh`，缺失时用 `substance.inn_zh/inn_en` 补；`label_en` 取 `inn_en` |
| `meaning_zh` | 自动模板（俗名/别名指向成分；类别词举例；歧义说明） |
| `meaning_en` | 留空（当前库同类中文行均未填英文解释） |
| `substance_id` | CSV `substance_id`；类别/歧义词为 NULL |
| `examples` | CSV `examples`（`;` 分隔）→ JSON 数组（仅类别词/歧义） |
| `confidence` | 来源族 ≥2 → documented；1 → community |
| `source_id` | 由 CSV `platform` 映射到 4 个来源族（见 §3） |
| `source_url` | CSV 逐条 URL（已校验 0 空值） |
| `note` | 候选平台 + snippet 摘要 + 许可说明（≤500 字） |
| `created_at` | 运行当天日期（与现有行一致用 `YYYY-MM-DD`） |

`term_norm` 与现有 `community_cn` 行一致（中文保持、小写、去空格标点），与站内
`alias_all`/`normalize` 的检索键对齐。

---

## 3. 过滤与来源映射

**跳过（74 行）**：`substance_id LIKE 'cn-%'` 的候选——这些目标成分在 2026-10-26 的
CN→INN 合并后仍只有中文名，引用它可能被后续合并删除，故按任务要求**不入库**，
等成分合并完成后再跑一次（脚本可增量重跑）。

**去重（本批 0 行命中）**：候选 CSV 在生成时已做过 `nickname`+`drug_term`+`product_name`
去重，脚本运行时再校验一次：
- `(term_norm, term_type, COALESCE(substance_id,''))` 与现有 `drug_term` 完全一致 → 跳过（保证幂等）；
- `term_norm` 命中 `nickname.alias_norm` → 跳过；
- `term_norm` 命中任意 `name_key.norm`（product_name）→ 跳过；
- 批内键重复 → 跳过。

**来源族映射**（独立来源用于 confidence）：

| CSV platform | source_id | 许可 |
|---|---|---|
| `wikipedia_zh` / `wiki`（raw 维基） | `wikipedia_zh` | CC BY-SA 4.0（署名+相同方式共享） |
| `wikidata` | `wikidata` | CC0 1.0 |
| `alihealth_cn` | `alihealth_cn` | 待确认（公开健康平台页面；仅存短名+链接） |
| `bing` / `toutiao` / 小红书 / 知乎 / 微博 / 贴吧 | `community_web_cn` | 用户/社区内容（仅存叫法事实+原链接） |

- 每行按 platform 中出现的族计数；≥2 族 → documented，1 族 → community；
- source_id 取行内最高优先族（wikipedia_zh > wikidata > alihealth_cn > community_web_cn），
  note 里保留该行全部平台与许可，便于署名。

---

## 4. 与候选 CSV 的 confidence 差异（5 行）

候选 CSV 计算「独立来源」时把「raw 抓取的 wiki」与「仓库维基别名表」算作两个来源；
入库脚本视为同一来源族（都是 zh.wikipedia），因此 5 行由 documented 降为 community。
这与「2 个独立来源」的严格定义一致，属预期修正。

---

## 5. 验证（`.tmp/cn-slang-ingest/drugs-test.db` 副本）

| 步骤 | 结果 |
|---|---|
| 副本基线 | `drug_term` 365 行（sha256 `3d5d32…`）、`source` 28 行、`nickname` 57、`alias_all` 422 |
| `--apply` | 写入 **1,034** 行；`drug_term` 365→1,399；`source` 28→32（+4 新建）；`alias_all` 422→1,456；`nickname` 不变；无 `cn-*` 引用；无重复键；无非法 confidence |
| 幂等（再 `--apply`） | 输出「没有可入库的行」，写 0 行；`drug_term`/`source` 表 sha256 不变 |
| `--rollback` | 删除本次 1,034 行 + 新建的 4 个 source；`drug_term`、`source` 两表 **sha256 与合并前完全一致**；`alias_all` 回到 422；`nickname` 不变 |
| 再 `--rollback` | 幂等成功（0 行可删，退出码 0） |

撤销清单：`.tmp/cn-slang-ingest/undo_20261027T165622Z.json`（含每条 `term_id`、term、
term_type、substance_id，以及 source 新增/覆盖前快照）。

---

## 6. 样例 20（将入库）

| term | term_type | substance_id | label | source | confidence |
|---|---|---|---|---|---|
| 万乃洛韦 | folk | valacyclovir | Valacyclovir | wikipedia_zh | documented |
| 三苯氧胺 | folk | tamoxifen | Tamoxifen | wikipedia_zh | documented |
| 丙硫咪唑 | folk | albendazole | Albendazole | wikipedia_zh | documented |
| 东青 | folk | aspirin | Aspirin | wikipedia_zh | documented |
| 乐衡 | folk | gemfibrozil | Gemfibrozil | wikipedia_zh | documented |
| 义美仁 | folk | azathioprine | Azathioprine | wikipedia_zh | documented |
| 乃柏欣 | folk | tobramycin | Tobramycin | wikipedia_zh | documented |
| 乙醯柳酸 | folk | aspirin | Aspirin | wikipedia_zh | documented |
| 乙醯胺酚 | folk | acetaminophen | 对乙酰氨基酚 | wikipedia_zh | community |
| 争光霉素 | folk | bleomycin | Bleomycin | wikipedia_zh | documented |
| 无环鸟苷 | folk | acyclovir | Acyclovir | wikipedia_zh | community |
| 必理痛 | folk | acetaminophen | 对乙酰氨基酚 | wikipedia_zh | documented |
| 百服宁 | folk | acetaminophen | 对乙酰氨基酚 | wikipedia_zh | documented |
| 康泰克 | folk | pseudoephedrine | 盐酸伪麻黄碱 | wikipedia_zh | documented |
| 乐比克 | folk | zopiclone | Zopiclone | wikipedia_zh | community |
| 胃达喜 | folk | hydrotalcite | Hydrotalcite | community_web_cn | community |
| 普拿疼 | folk | （歧义，NULL） | — | wikipedia_zh | documented |
| 减肥针 | class | （NULL，examples: semaglutide） | — | community_web_cn | documented |
| 瘦瘦针 | class | （NULL，examples: semaglutide/tirzepatide） | — | community_web_cn | community |
| 白加黑 | folk | （NULL，复方） | — | community_web_cn | community |

（完整 1,034 行由脚本 dry-run 打印；`examples` 仅 12+ 类别/歧义行有值。）

---

## 7. 如何 apply / 回滚（Lead 操作）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 正式库 dry-run（只读，看计数与样例；建议对比本报告的 1,034/74）
& $py etl/ingest_cn_slang.py

# 2) 审核后 apply（事务 + 撤销清单 .tmp/cn-slang-ingest/undo_*.json）
& $py etl/ingest_cn_slang.py --apply

# 3) 如需回滚（缺省取最新清单）
& $py etl/ingest_cn_slang.py --rollback
```

- 幂等：同一 CSV 重复 apply 写 0 行；`raw_terms` 增长后重跑
  `etl/extract_cn_slang.py` 生成新 CSV，再 `--apply` 即只增量写入新词；
- `--db` 可指向副本用于演练；真实库默认 `data/drugs.db`（由 Lead 决定何时 apply）；
- 入库后需同步 README/About/CHANGELOG 的 `drug_term` 计数（365→1,399 为预期值，
  以 apply 后实际查询为准），**`nickname` 保持 57 不变**。

---

## 8. 许可与署名

- `wikipedia_zh`：CC BY-SA 4.0 —— 站上需署名「维基百科」并链回条目，衍生数据同许可；
- `wikidata`：CC0 1.0；`community_web_cn`：用户/社区内容，只存叫法事实+链接；
- `alihealth_cn`：**许可待确认**（本次可入库 1,034 行中未用到该来源；后续扩容前请人拍板）。
- 所有来源 URL 逐条写入 `drug_term.source_url`，`note` 保留许可证信息。
