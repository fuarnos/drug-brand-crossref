# 合并 batch B 核验 + overrides 更新（148 条，task-56）

> 日期：2026-10-28 ｜ 输入：`data/cross_market_merge_candidates.csv`（mergeable 178；batch A 已做 30）→ **batch B 148 条**（全部 `evidence_type=existing_override`；CN 14 / ES·MX 134）
> 写范围：`data/cross_market_batchB.csv`、`data/cn_inn_overrides.csv`、`data/es_inn_overrides.csv`、`.tmp/cross-market/`、本报告。
> **真实库 `data/drugs.db` 未写入**；merge dry-run/apply/rollback 全部在副本 `.tmp/cross-market/drugs-batchB.db` 上完成。未跑 git / 发布 / `site/build.py`。

## 1. 结论

| 项 | 数量 |
|---|---:|
| batch B 总条数 | **148** |
| **保留（通过二次核验，写入 mergeable）** | **119**（CN 9 / ES·MX 110） |
| **降级（证据不足，status=uncertain）** | **27**（CN 5 / ES 22） |
| **丢弃（盐型/目标不成立，status=uncertain）** | **2**（均 ES） |
| overrides 更新行数 | 148（cn 14 + es 134，原地更新，BOM/列序保持） |
| 副本实际可并 | **112 / 119**（CN 9/9 + ES 103/110；7 条被 merge_es 安全规则拦下） |
| 副本影响 | substance **12,790 → 12,678（−112）**；variant 13,886 → 13,774；产品/组件/名字不变；跨国（≥2 市场）成分 **2,953 → 2,976（+23）** |
| 回滚 | 按撤销清单逆序恢复，substance/variant/substance 表 sha256 **与 apply 前完全一致**；二次 apply 幂等（可并 0） |

overrides 状态变化：

| 文件 | 行数 | mergeable 前→后 | uncertain 前→后 | BOM/列 |
|---|---:|---|---|---|
| `data/cn_inn_overrides.csv` | 2,177（不变） | 377 → **386**（+9） | 1,663 → 1,654 | 保留 / 8 列不变 |
| `data/es_inn_overrides.csv` | 1,081（不变） | 186 → **296**（+110） | 158 → 48 | 保留 / 8 列不变 |

sha256（前 16）：cn `8a52cf38b9a7c11c → 4884903f682fb8e5`；es `809eb2f7c9f8687a → 74ab9afbdca89007`。

## 2. 二次核验规则（复用 data-depth / merge 工具口径）

逐条检查（实现：`.tmp/cross-market/verify_batch_b.py`；决策落 `data/cross_market_batchB.csv`）：

1. **存在性/目标合法性**：源成分存在（已合并不再处理）、目标存在且为英文成分（拒绝 `cn-*`/`mx-es-*` 目标，`inn_en` 须有拉丁字母）；override 行存在且 `en_substance_id` 为空或等于候选目标（冲突丢弃）。
2. **盐型/酯/水合物必须匹配**：从源名抽盐/酯 token（CN 用 `ingest_nhsa.SALT_PREFIX/SALT_SUFFIX`，ES 用 `merge_es_substances.SALT_ES_EN`），映射成英文盐名后必须在目标 `inn_en` 或目标 `variant.salt/hydrate/ester/salt_code` 中有对应；源为 base 而目标只有盐型名（无 base variant）→ 降级；水合物标记未在目标确认 → 降级。
3. **立体标记**：左旋/右旋/消旋（levo/dextro/racemic、S(-) 等）必须与目标一致；冲突 → 丢弃/降级。
4. **复方**：源名含 复方/compound/多成分 或 `+` → 丢弃（不能并到单一成分）。
5. **第二证据**（弱证据门槛）：原证据为「模糊/低置信/多个候选分数相同/弱证据」时，需至少一个第二证据才 mergeable：
   - CN：CN2EN 官方映射命中 / 目标 `inn_zh` 精确命中且该中文名只对应唯一成分 / 盐型精确匹配；
   - ES：WHO `inn_es` 官方映射 / `mx_inn_map` 官方映射 / 盐型精确匹配 / 名称包含关系 / 名称相似度 ≥0.85。
   - **ATC-4 弱证据规则**：batch B 无 `atc4` 证据行（0 条适用）；ATC 码不一致仅备注（归属常因适应证/来源错位，如 葡萄糖 V02DC vs B05BA03），不作降级依据。
6. **同名多成分歧义**：如「葡萄糖」同时对应 glucose/dextrose，目标不唯一 → 降级。
7. 全部条目写入 `data/cross_market_batchB.csv`（15 列：决策/理由/检查项/第二证据/route 等）：
   - 保留 → overrides `status=mergeable`、写入 `en_substance_id`/`inn_en`、confidence=medium、evidence 注明「batch B（task-56）二次核验」；
   - 降级/丢弃 → `status=uncertain`、confidence=low、reason 写明确原因（阻止 merge 工具误并）。

### 降级/丢弃明细

- **丢弃 2**：
  1. `mx-es-bromhidrato-de-glutamato-de → glutamato`：源名 hydrobromide 盐，目标 `glutamato`（西语名成分）无对应盐 variant/名 → 盐型不匹配（且目标本身是西语名，非英文 INN）。
  2. `mx-es-silicato-de-magnesio → silica`：源是硅酸镁（magnesio 盐），目标是 silica（二氧化硅）→ 不同物质/盐型不匹配。
- **降级 27**（例）：`cn-2db2538bfa 葡萄糖粉剂 → dextrose`（glucose/dextrose 同名歧义，无第二证据）、`cn-0d1c4f7573 → camphor`、`cn-cb8a75c2a6 → allantoin`、`mx-es-donepecilo → donepezil`、`hierro-dextran → iron-dextran`、`metionina → methionine`、`selenio → selenium-sulfide`、`acido-gadobenico → gadobenate-dimeglumine`、`mx-es-clodronato-disodico → clodronate-disodium`、`mx-es-quifamida → quinfamide`、`hexafluoruro-de-azufre → sulfur-hexafluoride` 等；原因均为原证据弱（模糊/低置信/多候选）且无第二证据（少数含 ATC 备注）。
- **保留 119**：例 `condroitin→chondroitin`、`cn-55bfea1cce 氟伐他汀钠→fluvastatin`（盐型匹配 target sodium variant）、`cn-f1b9d21d85 米卡芬净钠→micafungin`、`cn-5bd9217c34 达肝素钠→dalteparin`、`amilmetacresol→amylmetacresol`、`fibrinogeno-humano→fibrinogen-human`、`tetanos→tetanus`、`mx-es-bromuro-de-vecuronio→vecuronium`、`patiromero→patiromer`、`proteina-c-humana→protein-c-human` 等（盐型/水合/立体匹配 + 名称包含/相似或官方映射）。

## 3. 副本 dry-run / apply / rollback（`.tmp/cross-market/`）

副本：`data/drugs.db` → `.tmp/cross-market/drugs-batchB.db`（初始与真实库一致）。

| 步骤 | 结果 |
|---|---|
| CN dry-run（`merge_cn_substances.py --csv cn_batch_b.csv`） | 可并 **9**；影响产品 99；删除 9 variant/substance；目标 variant：base 7 / base_fallback 1 / salt_variant 1 |
| CN apply | 合并 9 个 cn 成分；substance 12,790→12,781 |
| ES dry-run/apply（`merge_es_substances.py --csv es_batch_b.csv --include-unprefixed`） | 可并 **103/110**；影响产品 287；7 条被安全规则拦下（6 条「受影响产品有 corroboration」+ 1 条「ES 侧不是 base variant：condroitin salt=sulfato」） |
| 汇总 after | substance **12,678**（−112）、variant **13,774**（−112）、product/component/name 不变、多市场成分 **2,976**（+23） |
| 二次 apply（幂等） | CN 9「already_merged」、ES 103「already_merged」（另 6 corroboration+1 base 仍拦），可并 0，未写库 |
| rollback（ES→CN 逆序） | 恢复 103+9 个合并；计数回到 12,790 / 13,886 / 2,953；substance/variant/product_component 全表 sha256 **完全一致** |

被拦下的 7 条（保留在 overrides 的 mergeable，等工具改进后再并）：`condroitin`（源 salt=sulfato 非 base）、`nimodipino`（corroboration 9）、`amfotericina-b`（1）、`mx-es-isoconazol`（7）、`propafenona`（1）、`tiamazol`（4）、`mx-es-bromuro-de-piridostigmina`（3）。

日志/清单：`batchB_cn_dryrun.out.txt`、`batchB_cn_apply.out.txt`、`batchB_es_dryrun.out.txt`、`batchB_es_apply.out.txt`、`batchB_*_apply2.out.txt`、`batchB_*_rollback.out.txt`、`batchB_cn_manifest.json`、`batchB_es_manifest.json`、`batchB_pipeline_stats.json`、测试用 `cn_batch_b.csv`（9 行）/`es_batch_b.csv`（110 行）。

## 4. 风险

1. **1 条 CN base_fallback**：中文名带盐/酯但目标无对应 variant 时按 base variant 合并（工具既有行为）；建议人工复核该条（`batchB_cn_dryrun.out.txt` 中「其中 1 条…按 base variant 合并」）。其余 2 条 salt/base 选择均有目标同名盐对应。
2. **7 条 ES 被拦**（见上）：安全规则不放行；overrides 已是 mergeable，未来工具支持 salt variant 匹配/人工确认 corroboration 后可再并。
3. **降级 27 条**：保守处理（原证据弱+无第二证据），需人工核后才应提升；其中多数看起来名字对应（如 metionina→methionine），但没有第二证据故不进 mergeable。
4. **目标非英文 INN 风险**：`mx-es-bromhidrato-de-glutamato-de → glutamato` 已丢弃；其余保留行的目标均为英文 INN/生物制品名（`--include-unprefixed` 的 ES 源要求产品只在 ES/MX 市场生效，见 merge_es 规则）。
5. **并发写入**：本轮构建/验证期间真实库可能被其他 agent 写入；overrides 文件与 DB 副本均按本轮开始时状态处理；apply 前请用最新库重跑 dry-run 并对齐 batch A 状态（batch A 30 条尚未 apply 到真实库）。
6. **回滚**：撤销清单已记录（cn/es 各一份）；重复 apply 幂等；回滚只按清单精确恢复，异常时按 `--rollback <manifest>` 逆序执行。

## 5. apply 建议（真实库由 Lead 执行）

1. 备份：`Copy-Item data/drugs.db data/backups/drugs_$(Get-Date -Format yyyyMMdd_HHmmss).db`（或走 `run_all.py` 备份）。
2. 先 dry-run：用**最新** `data/cn_inn_overrides.csv` / `data/es_inn_overrides.csv` 对真实库跑
   `merge_cn_substances.py --dry-run` 与 `merge_es_substances.py --include-unprefixed --dry-run`；
   注意 batch A 30 条也在 mergeable 中（真实库尚未 apply），实际可并 = batch A 29 + batch B 112（重叠项按幂等 already_merged 跳过）。
3. apply 顺序：CN → ES（各自事务 + manifest），记录 before/after 计数；确认 substance 减少数 = 合并数，product/component/name 不变。
4. 验证：`db/check_data.py`、`coverage` 表、三语检索抽检；如异常按 manifest 逆序 rollback。
5. 后续（可选）：修复 merge_cn 对 cn-* 目标/盐型 base_fallback 的支持、merge_es 支持 source salt variant 与 corroboration 放行，可再收 7 条。

## 6. 产物与复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp/cross-market/verify_batch_b.py           # dry-run 核验（输出决策）
& $py .tmp/cross-market/verify_batch_b.py --apply   # 更新 overrides CSV（本轮已执行）
& $py .tmp/cross-market/batchB_pipeline.py          # 副本 dry-run/apply/rollback（本轮已执行）
```

| 文件 | 内容 |
|---|---|
| `data/cross_market_batchB.csv` | 148 行核验结果（决策/理由/检查项/第二证据/route） |
| `data/cn_inn_overrides.csv` / `data/es_inn_overrides.csv` | 原地更新 148 行（保留 BOM/列序） |
| `.tmp/cross-market/verify_batch_b.py` | 二次核验 + overrides 更新脚本 |
| `.tmp/cross-market/batchB_pipeline.py` | 副本 merge 流水线 |
| `.tmp/cross-market/batchB_pipeline_stats.json` | 副本 before/after/rollback 计数与 sha 校验 |
| `.tmp/cross-market/batchB_*.out.txt` / `*_manifest.json` / `cn_batch_b.csv` / `es_batch_b.csv` | 日志、撤销清单、测试 CSV |
| `reports/cross-market-batchB.md` | 本报告 |
