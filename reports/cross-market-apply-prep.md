# 合并候选 apply-prep（batch A 30 条 + merge 脚本副本验证，task-48）

> 日期：2026-10-28 ｜ 数据库：`data/drugs.db`（**只读**，本轮未写入）｜ 未跑 git / 发布 / `site/build.py`
> 输入：`data/cross_market_merge_candidates.csv`（178 mergeable）、`reports/cross-market-mapping.md`
> 产物：更新后的 `data/cn_inn_overrides.csv`（2,177 行）与 `data/es_inn_overrides.csv`（1,081 行）；`.tmp/cross-market/` 下的 30 条清单、副本 DB、dry-run/apply/rollback 日志与撤销清单；本报告。
> **真实库由 Lead 后续 apply；本轮只在副本 `.tmp/cross-market/drugs-test.db` 上验证。**

---

## 1. 结论

1. **batch A 30 条已写入 overrides CSV**（结构/列序/UTF-8 BOM 均保持不变）：
   - `cn_inn_overrides.csv`：2 条官方名（苯甲酸阿格列汀→alogliptin、人白介素-2→aldesleukin）+ **25 对同名重复**（原地更新，未新增行）→ `status=mergeable` 从 350 → **377**；
   - `es_inn_overrides.csv`：3 条（Bromuro Pinaverio→pinaverium-bromide、Gemifloxacino→gemifloxacin、Tesamorelina→tesamorelin）→ `mergeable` 185 → **186**（另 2 条原已 mergeable，本次刷新 evidence 为 WHO INN）。
   - 30 条完整清单（含路由）：`.tmp/cross-market/batch_a_30.csv`。
2. **副本验证实际可并 29/30**：
   - `merge_cn_substances.py` 归并 **2** 条（CN 官方名）；
   - `merge_es_substances.py` 归并 **2** 条（gemifloxacin / tesamorelin，需先补 base variant 前置，见 §4.2）；
   - 25 对 cn-* 同名重复走**等价 auto-merge 路径**归并 25 条（`merge_cn_substances.py` 设计上拒绝 cn- 目标，见 §4.1）；
   - **1 条被拦**：`mx-es-bromuro-pinaverio → pinaverium-bromide`，安全规则「受影响产品有 corroboration」（MX 浓度回填来源），未合并。
3. **副本计数（before → after）**：substance **12,790 → 12,761（−29）**；variant 13,886 → 13,884（−2，含 2 个前置 base variant 的创建）；product/component 不变（只移挂接）；跨市场（≥2 市场）成分 **2,953 → 2,954（+1，tesamorelin 获得 MX）**。
4. **rollback 全部验证通过**：撤销 25 重复 + 2 ES + 2 CN 合并、清理 2 个前置 variant 后，副本回到 **12,790 / 13,886 / 2,953**，与真实库逐项一致（delta 全 0）。
5. **apply 建议**：真实库 apply 按 §5 的顺序执行；建议先修两个小工具问题（merge_cn 不支持 cn- 目标、merge_es 的两类前置），再一次性 apply 30 条（实际 29 条 + 1 条待定）。

---

## 2. batch A 30 条清单与路由

路由依据：`data/cross_market_merge_candidates.csv` 中 evidence_type ∈ {duplicate_name, who_inn, cn2en, mx_inn_map} 的 30 条（重复对+官方名优先）。

| 路由 | 条数 | 说明 |
|---|---:|---|
| `merge_cn` | 2 | 苯甲酸阿格列汀→alogliptin、人白介素-2→aldesleukin（CN2EN 表） |
| `merge_es` | 3 | Bromuro Pinaverio→pinaverium-bromide（mx_inn_map）、Gemifloxacino→gemifloxacin、Tesamorelina→tesamorelin（WHO INN，high） |
| `auto_merge` | 25 | cn-* 同名重复（reports/substance_duplicates.csv），canonical 均为 cn-* |

25 对重复的 canonical 示例：`cn-1184c464cb(人凝血因子VIII) → cn-38d3b9ed4e`、`cn-984316b3cb(三维亚油酸胶丸Ⅰ) → cn-e38aca6dac`、`cn-1e1d2aee4c(氨酚伪麻美芬片Ⅲ/氨麻美敏) → cn-7c7beef94a` 等；完整清单见 `.tmp/cross-market/batch_a_30.csv`。

---

## 3. overrides CSV 变更（本任务唯一改动的两个文件）

| 文件 | 行数 | BOM | 列结构 | status 变化 |
|---|---:|---|---|---|
| `data/cn_inn_overrides.csv` | 2,177（不变） | 保留 | 8 列不变 | mergeable 350 → **377**（+27）；uncertain 1,683→1,663；combination 106→99 |
| `data/es_inn_overrides.csv` | 1,081（不变） | 保留 | 8 列不变 | mergeable 185 → **186**（+1）；no_english 672→671 |

- 变更前备份：`.tmp/cross-market/cn_inn_overrides.before.csv` / `es_inn_overrides.before.csv`。
- sha256（前 16）：cn `178c27da67393c4f → 8a52cf38b9a7c11c`；es `088891d82e7c3aee → 809eb2f7c9f8687a`。
- 每行 `reason` 均带「batch A（task-48）｜证据来源」，`evidence_url`/`evidence` 指向 CN2EN / WHO INN / mx_inn_map / substance_duplicates 来源。
- **注意**：25 对重复的 `en_substance_id` 是 **cn- 前缀 canonical**（不是英文 substance）。`merge_cn_substances.py` 会拒绝它们（见 §4.1），保留在 CSV 是为了「30 条清单可审计」；若不想让后续 dry-run 反复出现 25 条 reject，建议改为 `status=needs_rename` 或移入独立文件。

---

## 4. 副本 dry-run / apply 结果

副本：`Copy-Item data/drugs.db .tmp/cross-market/drugs-test.db`（初始与真实库一致：substance 12,790 / variants 13,886 / products 409,587 / components 498,445 / 多市场成分 2,953）。

### 4.1 CN：官方 2 条可并，25 条重复被 merge_cn 拒绝（设计约束）

```text
# python etl/merge_cn_substances.py --csv .tmp/cross-market/cn_batch_a_all.csv --db .tmp/cross-market/drugs-test.db
计划合并清单：
   产品  组件  cn 成分          中文名          英文目标
    19   19  cn-2f1c20e347  苯甲酸阿格列汀   alogliptin (alogliptin)
     2    2  cn-437270d2a0  人白介素－2     aldesleukin (aldesleukin)
25 条 reject：英文目标仍是 cn-* 成分（merge_cn_substances.py 规则：只删 cn-*、永不把产品挂到 cn-* 目标）
→ --apply（官方 2 条，--csv cn_batch_a_official.csv）：已合并 2 个 CN 成分
```

**25 对重复的验证**：`merge_cn_substances.py` 不支持 cn→cn；`etl/auto_merge_substances.py` 做的正是这类合并（`UPDATE variant.substance_id → DELETE substance`），但它**缺少 `--db` 参数**且会重算全库重复组。本任务在 `.tmp/cross-market/merge_cn_duplicates.py` 里用**完全相同的操作语义**、限定这 25 对，在副本上 dry-run + apply 验证：

```text
待合并重复对：25（预期 25）  → 已合并 25 对重复（事务提交）；撤销清单 cn_duplicates_manifest.json
```

> 建议（给 Lead/实现方）：给 `etl/auto_merge_substances.py` 加 `--db/--pairs/--apply/--rollback/--manifest`（约 30 行改动），把这条路径产品化，避免以后每个任务复制临时脚本。

### 4.2 ES：3 条里 2 条需前置，1 条被 corroboration 拦

```text
# 首次 dry-run：跳过 3 行
  2  英文目标没有 base variant 可挂（gemifloxacin / tesamorelin 只有 mesylate/acetate 盐 variant）
  1  受影响产品有 corroboration N 条（bromuro pinaverio 的 MX 产品有 ccby 浓度回填 corroboration）
```

**前置（仅副本，已记录 `.tmp/cross-market/es_variant_prep.json`）**：给 `gemifloxacin`、`tesamorelin` 各补一个 base variant（`variant_id=substance_id, salt='', base_fraction=1.0`）——这是给「WHO INN 建了 substance 但没有 variant」的靶子补可挂接点，属安全操作，但**真实库 apply 前需要同样执行**（否则这 2 条永远合并不了）。

```text
# 前置后 dry-run：可合并 2 个 ES 成分（gemifloxacin、tesamorelin）；bromuro 仍跳过（corroboration）
# --apply：已合并 2 个 ES 成分；撤销清单 es_manifest.json
```

> `bromuro pinaverio`：MX-064M2022 有 2 条 `corroboration`（`ccby:hgmgg`/`ccby:inprfm`，per_volume 浓度回填来源）。`merge_es_substances.py` 的规则是不动有 corroboration 的产品（防止丢失人工/来源核验）。**本轮不合并**；若 Lead 认为该 corroboration 只是浓度来源、可随产品迁移，可在 B 批单独处理（需给合并脚本加「保留 corroboration 一起搬家」的能力）。

### 4.3 汇总与回滚

| 指标 | 真实库（基准） | 副本 apply 后 | 回滚后 |
|---|---:|---:|---:|
| substance | 12,790 | **12,761（−29）** | 12,790 |
| variant | 13,886 | **13,884（−2）** | 13,886 |
| product / components | 409,587 / 498,445 | 不变 | 不变 |
| ≥2 市场成分 | 2,953 | **2,954（+1）** | 2,953 |

- 跨市场变化：`tesamorelin` 由 CA 单市场 → **CA+MX**（唯一新增多市场成分）；`alogliptin` 合并前已覆盖 7 市场、`aldesleukin` 已 5 市场、`gemifloxacin` 已 CN+CA，故不再新增。
- 回滚：`merge_cn --rollback`、`merge_es --rollback`、`merge_cn_duplicates --rollback` 三份清单全部成功；再删除 2 个前置 base variant 后副本 delta 全 0（与真实库逐项一致）。

---

## 5. 真实库 apply 建议（Lead 执行）

1. **先做两个小前置**（各 ~10 行）：
   - `etl/auto_merge_substances.py` 加 `--db/--pairs/--apply/--rollback/--manifest`，或把 `.tmp/cross-market/merge_cn_duplicates.py` 的逻辑并进去（推荐，长期用）；
   - 真实库给 `gemifloxacin`、`tesamorelin` 补 base variant（同 §4.2；或给 `merge_es` 加「目标仅有盐 variant 时自动建 base variant」选项）。
2. **备份库** → 按顺序 apply：
   ```powershell
   & $py etl/merge_cn_substances.py --apply                     # 应先只对 batch A 官方 2 条（可用 --csv cn_batch_a_official.csv）
   & $py etl/merge_es_substances.py --apply                     # 2 条（bromuro 会被 skip）
   & $py etl/auto_merge_substances.py --apply                   # 25 对重复（修好 --db 后）
   ```
   预期：substance 12,790 → 12,761、多市场成分 2,953 → 2,954、product/component 不变。
3. `db/check_data.py` 复核；三语检索抽查（alogliptin / aldesleukin / gemifloxacin / tesamorelin / 人凝血因子VIII）。
4. 若想连 `bromuro` 一起并（+1 多市场），需先决定 corroboration 迁移策略，不建议本轮做。
5. **B/C 批待办**：B = existing_override 148 条（cn 14 / es 134）需 20% 人工抽核；C = needs_target 52 条需先补英文 substance。详见 `reports/cross-market-mapping.md` §7。

---

## 6. 风险

1. **merge_cn 与重复对的口径差**：25 条 cn→cn 不能走 `merge_cn_substances.py`；若误跑 apply 会被逐行跳过（不阻塞其它行，但会留 25 条 reject 噪音）。建议把重复路径独立。
2. **前置 base variant** 会让目标 substance 多一个空盐 variant；对站点语义无影响（产品挂接后显示规格取自产品行），但 `variant` 计数会变，需要在 CHANGELOG/README 口径里说明。
3. **corroboration 安全规则**让 bromuro 少了 1 条合并；若强行迁移 corroboration，需保证来源 URL/verified_by 一起搬（否则丢失 MX per_volume 的出处）。
4. **25 对重复的 en_substance_id 仍是 cn-**：若未来 `merge_cn_substances.py` 放宽目标规则，这些行会直接生效；若不放宽，应改为 `status=needs_rename` 免得误导。
5. 合并只改 substance/variant 挂接，**不改产品名/规格**；站点「跨市场对应」在合并后才会显示同一成分下的多国产品——发布前需抽查 5 个成分页。
6. 25 对重复里有 5 对是放射性药盒/血型试剂（V04CW 等），合并后中文名以 canonical 为准；若两者其实有细微差异（如不同检测项），需人工确认（本批按「同名重复」自动判定，建议抽 5 对核对）。
7. 本轮只改了 2 个 overrides CSV；**真实 DB 未被写**（mtime/计数未变）。

---

## 7. 证据索引（`.tmp/cross-market/`）

| 文件 | 内容 |
|---|---|
| `batch_a_30.csv` | 30 条清单（route/source/target/evidence/confidence） |
| `cn_inn_overrides.before.csv` / `es_inn_overrides.before.csv` | 改动前备份 |
| `cn_batch_a_official.csv` / `cn_batch_a_all.csv` / `es_batch_a.csv` | 副本测试用过滤 CSV（27/2/3 行） |
| `merge_cn_dryrun_all.out.txt` / `merge_cn_apply.out.txt` / `merge_cn_rollback.out.txt` + `cn_manifest.json` | CN 2 条 dry-run/apply/rollback |
| `merge_es_dryrun*.out.txt` / `merge_es_apply*.out.txt` / `es_rollback.out.txt` + `es_manifest.json` | ES 3 条（含前置）dry-run/apply/rollback |
| `dup_dryrun.out.txt` / `dup_apply.out.txt` / `dup_rollback.out.txt` + `cn_duplicates_manifest.json` | 25 对重复 dry-run/apply/rollback |
| `es_variant_prep.json` | 前置创建的 2 个 base variant |
| `merge_cn_duplicates.py` / `prep_es_variants.py` / `counts.py` | 副本验证辅助脚本 |
| `drugs-test.db` | 副本（回滚后与真实库一致；450 MB，可删） |
| `apply_batch_a.py` / `apply_batch_a*.out.txt` | overrides CSV 更新脚本与日志 |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp/cross-market/apply_batch_a.py                 # 更新 2 个 overrides CSV（已执行，幂等更新同值）
Copy-Item data/drugs.db .tmp/cross-market/drugs-test.db -Force
& $py etl/merge_cn_substances.py --csv .tmp/cross-market/cn_batch_a_official.csv --db .tmp/cross-market/drugs-test.db --apply --manifest .tmp/cross-market/cn_manifest.json
& $py .tmp/cross-market/prep_es_variants.py --db .tmp/cross-market/drugs-test.db
& $py etl/merge_es_substances.py --csv .tmp/cross-market/es_batch_a.csv --db .tmp/cross-market/drugs-test.db --apply --manifest .tmp/cross-market/es_manifest.json
& $py .tmp/cross-market/merge_cn_duplicates.py --db .tmp/cross-market/drugs-test.db --apply --manifest .tmp/cross-market/cn_duplicates_manifest.json
& $py .tmp/cross-market/counts.py --label after
```

---

## 8. §batchA-runbook（task-52：可落地的参数化工具 + base variant 迁移 + 一键 runbook）

> 2026-10-28 追加。目标：把 batch A 的 29 条合并从「临时脚本」变成**可复用、可回滚、可评审**的流程。
> 新增/改动：`etl/auto_merge_substances.py`（参数化）、`.tmp/cross-market/base_variant_migration.py`（base variant 迁移草案）、`.tmp/cross-market/apply_batchA.py`（按序执行器）。
> 全部验证在 `.tmp/cross-market/drugs-test.db` 副本（从 `data/drugs.db` 新复制）上完成；**真实库未写**。

### 8.1 `etl/auto_merge_substances.py` 新增参数（向后兼容）

原用法 `python etl/auto_merge_substances.py [--apply]` **保持不变**（全库扫描 + 报告到 `reports/substance_duplicates.csv`，`--apply` 才写库）。新增：

| 参数 | 说明 |
|---|---|
| `--db PATH` | 数据库（默认 `data/drugs.db`）；**只在副本上验证时必须传** |
| `--pairs CSV` | pair 列表（兼容 `batch_a_30.csv` 的 `route=auto_merge` 行，或候选 CSV 的 `source_id/target_id/status`） |
| `--dry-run` | 默认行为；只列计划不写库 |
| `--apply` | 事务写库 + 撤销清单（含 substance 原始行 + variant ids） |
| `--rollback [MANIFEST]` | 按撤销清单逆序恢复（默认取 `--manifest`） |
| `--manifest PATH` | 撤销清单路径 |
| `--report PATH` | dry-run 报告写哪里（避免误改跟踪文件 `reports/substance_duplicates.csv`） |
| `--allow-non-cn` | `--pairs` 模式默认只允许 cn-→cn-；需要时放开 |

安全约束：`--pairs` 模式只删 `cn-*` 成分；dup/canonical 必须存在；`--apply` 单事务，任何一行失败整体回滚。实测：

```text
python etl/auto_merge_substances.py --report .tmp/cross-market/legacy_report.csv   # 全库兼容：27 疑似对/25 组，只读
python etl/auto_merge_substances.py --db .tmp/cross-market/drugs-test.db \
  --pairs .tmp/cross-market/batch_a_30.csv --dry-run                              # 25 对可合并
```

### 8.2 base variant 迁移草案（`gemifloxacin` / `tesamorelin`）

**为什么需要**：`merge_es_substances.py` 要求「英文目标有 base variant 可挂」；但 `gemifloxacin` 只有 `gemifloxacin-mesylate`、`tesamorelin` 只有 `tesamorelin-acetate`（WHO INN 建 substance 时没有建空盐 base variant），而 ES 源名 `Gemifloxacino/Tesamorelina` 不含盐名，只能挂 base → 不补就永远被 skip。

**迁移草案**：`.tmp/cross-market/base_variant_migration.py`，等价 SQL：

```sql
INSERT INTO variant (variant_id, substance_id, salt, hydrate, ester, base_fraction,
                     interchange, salt_code, strength_basis)
VALUES ('gemifloxacin','gemifloxacin','','','',1.0,'unknown','','unknown');
INSERT INTO variant (variant_id, substance_id, salt, hydrate, ester, base_fraction,
                     interchange, salt_code, strength_basis)
VALUES ('tesamorelin','tesamorelin','','','',1.0,'unknown','','unknown');
```

```powershell
& $py .tmp/cross-market/base_variant_migration.py --db <DB>                        # dry-run
& $py .tmp/cross-market/base_variant_migration.py --db <DB> --apply --manifest <M> # 创建
& $py .tmp/cross-market/base_variant_migration.py --db <DB> --rollback --manifest <M> # 回滚（有组件引用则保留）
```

**影响**：只新增 2 行 `variant`；不新增 substance/product；合并后 ES 产品挂到 base variant（ES 源名未标盐，属「按名对齐」的已知限制，站点显示规格取自产品行，不受影响）。

### 8.3 一键 runbook（`.tmp/cross-market/apply_batchA.py`）

顺序（与 task 要求一致）：**base variant（2）→ merge_cn（2）→ merge_es（2，bromuro 跳过）→ auto_merge（25）**，随后打印 before/after 计数；`--rollback` 逆序回滚并核对真实库。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp/cross-market/apply_batchA.py --db .tmp/cross-market/drugs-test.db --fresh --apply
& $py .tmp/cross-market/apply_batchA.py --db .tmp/cross-market/drugs-test.db --rollback
```

**副本实测（2026-10-28）：**

| 阶段 | substance | variant | product | components | ≥2 市场成分 |
|---|---:|---:|---:|---:|---:|
| before（= 真实库） | 12,790 | 13,886 | 409,587 | 498,445 | 2,953 |
| batch A apply 后 | **12,761（−29）** | **13,884（−2）** | 409,587 | 498,445 | **2,954（+1）** |
| rollback 后 | 12,790 | 13,886 | 409,587 | 498,445 | 2,953 |
| delta vs 真实库 | **0** | **0** | 0 | 0 | 0 |

- 29 = CN 官方 2（阿格列汀、阿地白介素）+ ES 2（吉米沙星、替莫瑞林）+ 25 对 cn-* 重复；
- 1 条未并：`Bromuro Pinaverio → pinaverium-bromide`（受影响产品有 corroboration，merge_es 安全规则）；
- variant −2：CN 合并删 2 个 cn variant、ES 合并删 2 个 es variant，同时前置新建 2 个 base variant，净 −2；
- ≥2 市场 +1：`tesamorelin` 由 CA → CA+MX（其余 3 个目标合并前已是多市场）。

### 8.4 真实库 apply 步骤（Lead 执行；本轮未执行）

1. **备份**：`Copy-Item data/drugs.db data/backups/drugs-<日期>.db`（或按 run_all 备份机制）。
2. **base variant 迁移**：`base_variant_migration.py` 对真实 DB `--apply`（先干跑看 2 条）。
3. **CN 2 条**：`etl/merge_cn_substances.py --csv .tmp/cross-market/cn_batch_a_official.csv --apply`。
4. **ES 2 条**：`etl/merge_es_substances.py --csv .tmp/cross-market/es_batch_a.csv --apply`（bromuro 会 skip，属预期）。
5. **auto_merge 25 条**：`etl/auto_merge_substances.py --pairs .tmp/cross-market/batch_a_30.csv --apply --manifest .tmp/cross-market/real_auto_manifest.json`（默认 DB）。
6. **核数**：期望 substance 12,790→12,761、variant 13,886→13,884、product/components 不变、≥2 市场 2,953→2,954；跑 `db/check_data.py`；抽 5 个成分页（阿格列汀/阿地白介素/吉米沙星/替莫瑞林/人凝血因子VIII）确认跨市场产品可见。
7. **回滚预案**：4 份清单（base/cn/es/auto）齐备，逆序回滚可恢复（副本已验证 delta=0）。
8. **发布口径**：合并会改 substance 总数 → 需同步 README/About/CHANGELOG（属发布轮）。

### 8.5 已知事项 / 风险

1. `bromuro pinaverio` 仍待定：若要并，需给 merge_es 加「corroboration 随产品迁移」能力（否则丢 MX per_volume 来源）；不建议本轮做。
2. 25 对重复在 `cn_inn_overrides.csv` 里 `status=mergeable` 但 `en_substance_id` 是 cn- canonical；`merge_cn_substances.py` 会 reject 这 25 行。若以后不再用 auto-merge 路径，建议改成 `status=needs_rename`。
3. 批量 apply 前后务必核对 `reports/substance_duplicates.csv` 是否被全库模式覆盖（本轮用 `--report .tmp/...` 避免）。
4. `auto_merge_substances.py` 的 legacy 全库模式默认仍写 `reports/substance_duplicates.csv`（保持旧行为）；脚本/CI 里跑请显式 `--report` 到 `.tmp/`。

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 git / 发布 / `site/build.py`。_
