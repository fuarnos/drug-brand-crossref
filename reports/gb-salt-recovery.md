# GB dm+d 盐型恢复（task-34）

> 日期：2026-10-27 ｜ 数据：`data/raw/dmd/extracted` 最新包 **10.2.0 / 后缀 3151026**（包 20261019）；DB 只读，验证在 `.tmp/dmd-salt/snapshot.db` 副本
> 产物：`etl/fix_dmd_salts.py`（dry-run / apply / rollback，全事务 + 幂等 + 撤销清单）· 本报告 · `.tmp/dmd-salt/`（计划 CSV、撤销清单、日志）
> 边界：**未写 `data/drugs.db`**（真实库 mtime 停在任务开始前 10:08:23）；未改 `etl/ingest_dmd.py`、`site/build.py`、git/发布。

---

## 1. 结论

| 指标 | 数值 |
|---|---:|
| 扫描 GB dm+d 产品 | 61,048（组件 65,614） |
| **可恢复盐型的产品/组件** | **15,083 / 15,083**（单组件产品；占 GB 组件 **23.0%**） |
| 涉及成分 | **514 个 substance** |
| 目标 variant | **新建 127 个 / 复用 400 个** |
| 盐+水合物证据 | 342 个组件 / 17 个新 variant（如 atorvastatin calcium trihydrate 228） |
| apply 后 GB 组件带盐信息 | 1,313（2.0%）→ **16,396（25.0%）** |
| 其中 D2 可立即解锁（已有碱基分子量） | 16 个成分 / **1,726 个组件**（quetiapine 290、metformin 230、atorvastatin 228、venlafaxine 199…） |
| 副本验证 | apply / 二次 apply（幂等 0 写入）/ rollback 全部通过，`integrity_check=ok` |

一句话：**dm+d 里的盐型证据（AMP→VMP→VPI→ISID→原料名）足够可靠地恢复 1.5 万个 GB 组件（约 23%），干跑/回滚全部验证通过；真实库未动，等 Lead 拍板 apply。**

---

## 2. 数据链路与判定口径（只读解析，证据可追溯）

dm+d v2 XML 里盐型不在 VMP 名字上（VMP `NM` 是 "Amlodipine 5mg tablets"，盐被丢掉），而在**原料名**里：

```
f_amp2_*.xml        AMP（APID, VPID, NM）                     ← DB 的 product_id = GB-<APID>
   │ APID → VPID
f_vmp2_*.xml        VMP（VPID, NM…） + 同级 VPI（VPID, ISID, 强度…）
   │ VPI.ISID
f_ingredient2_*.xml ING（ISID, NM）  ← 原料名："Amlodipine besilate"、"Atorvastatin calcium trihydrate"
```

**恢复规则（脚本 `etl/fix_dmd_salts.py`）**：

1. 只处理 `country='GB' AND source_id='dmd'`、**恰好 1 个 component** 的产品，且当前 variant 是 base（`salt`/`salt_code` 为空）；
2. AMP→VMP 存在、VMP **恰好 1 个 VPI**（复方跳过）；ISID 原料名存在且非 `INVALID`；
3. 原料名必须 =「该成分现有基名（`substance.inn_en` / `substance_id` 归一）」+「盐后缀」，**基名精确匹配**；盐后缀交给 `etl/normalize_salts.classify_salt` 归一；
4. 只接受 `kind='salt'`（单一盐）或 `kind='salt_hydrate'`（单一盐+水合物，水合物另存 `variant.hydrate`）；`mixed` / `non_salt` / 酯 / 溶剂化物 / 多盐一律跳过；
5. 目标 variant 优先**复用**同 (substance, salt_code, 水合物词集) 的现有 variant；同盐多个 variant → 跳过（歧义）；没有才新建；
6. **不删任何 variant/substance**，只改 `product_component.variant_id`；新 variant 只写 `salt / hydrate / salt_code`，`base_fraction` 保持默认 1.0、`strength_basis='unknown'`（D2 折算仍需专门的碱基分子量与强度基准，本轮不越级）；
7. 事务写入 + 撤销清单（JSON：新建 variant 全字段 + 每个被移动组件旧 variant），`--apply/--rollback` 对真实库强制 `--confirm-real-db`。

脚本解析规模：ING 4,532 / VMP 24,684 / AMP 167,533；单次运行 ~1–2 分钟（76 MB AMP 文件解析为主），dry-run/apply 都重新解析以保证与最新包一致。

---

## 3. 可恢复清单（15,083 组件）

### 3.1 盐型分布（前 27 类，全量）

| salt_code | 组件 | salt_code | 组件 | salt_code | 组件 |
|---|---:|---|---:|---|---:|
| hydrochloride | 8,419 | sodium | 1,273 | acetate | 659 |
| fumarate | 594 | sulfate | 570 | mesylate | 477 |
| maleate | 463 | calcium | 442 | citrate | 402 |
| tartrate | 359 | succinate | 261 | phosphate | 248 |
| bromide | 202 | potassium | 181 | benzoate | 94 |
| gluconate | 81 | chloride | 70 | tromethamine | 65 |
| magnesium | 56 | xinafoate | 37 | nitrate | 36 |
| besylate | 31 | tosylate | 25 | pamoate | 22 |
| lactate | 12 | meglumine | 3 | hydrobromide | 1 |

### 3.2 成分 Top（按组件数）

`Tramadol 333、Quetiapine 290、Oxycodone 271、Propranolol 250、Morphine 245、Bisoprolol 238、Metformin 230、Atorvastatin 228、Methylphenidate 210、Ranitidine 201、Venlafaxine 199、Ropinirole 188、Losartan 181、Enalapril 177、Fluoxetine 164`

### 3.3 样例（含新建 variant / 复用 variant / 水合物）

| GB 产品 | 成分 | 原 variant | 目标 variant | 盐 | 水合物 | dm+d 原料名 |
|---|---|---|---|---|---|---|
| GB-10292611000001107 | Metformin | `metformin` | `metformin-hydrochloride`（复用） | hydrochloride | — | Metformin hydrochloride |
| GB-10494711000001109 | Vardenafil | `vardenafil` | `vardenafil-hydrochloride-trihydrate`（新建） | hydrochloride | trihydrate | Vardenafil hydrochloride trihydrate |
| GB-13831111000001108 | Atorvastatin | `atorvastatin` | `atorvastatin-calcium-trihydrate`（复用） | calcium | trihydrate | Atorvastatin calcium trihydrate |
| GB-36807311000001103 | Abacavir | `abacavir` | `abacavir-sulfate`（新建） | sulfate | — | Abacavir sulfate |
| GB-10472611000001101 | Quetiapine | `quetiapine` | `quetiapine-fumarate`（复用） | fumarate | — | Quetiapine fumarate |
| GB-11929411000001103 | Oxycodone | `oxycodone` | `oxycodone-hydrochloride`（复用） | hydrochloride | — | Oxycodone hydrochloride |
| GB-10065911000001103 | Morphine | `morphine` | `morphine-sulfate`（复用） | sulfate | — | Morphine sulfate |
| GB-36807311000001103 | Abacavir | `abacavir` | `abacavir-sulfate`（新建） | sulfate | — | Abacavir sulfate |

完整 15,083 行在 `.tmp/dmd-salt/dryrun_plan.csv`（列：product_id / from_variant / to_variant / salt_code / salt / hydrate / ingredient / vmp / action…，可直接复核）。

---

## 4. dry-run 与跳过分析

**计划**：15,083 组件（15,083 个产品）→ 127 个新 variant + 400 个复用 variant（新建覆盖 1,138 组件，复用覆盖 13,945 组件），0 行级错误。

**跳过 44,839 个产品**（61,048 − 15,083 − 1,126 已处理/非候选 = 44,839），原因分布：

| 原因 | 产品数 | 说明 / 下一步 |
|---|---:|---|
| 原料名无盐后缀 | 34,568 | 真·base 药（"Pregabalin"），符合预期。另有少量**可恢复但基名不一致**：`Benzylpenicillin sodium` vs 成分 Penicillin G、`Rifampicin` vs Rifampin、`Sodium valproate`（盐名 substance）——需成分别名表，留后续 |
| DB 多组件产品（复方） | 4,214 | 复方按多成分拆分后逐成分恢复，留后续 |
| VMP 多成分（复方） | 3,017 | 同上 |
| 同盐 variant 歧义 | 1,305 | 库里同成分存在**多个同 salt_code variant**（如 `x-hydrochloride` + `x-hcl`），脚本拒绝猜；需先做 salt variant 去重（见 §6.2） |
| **variant_id 冲突** | **约 1,722** | 库里存在「**盐名 substance**」（如 `flucloxacillin-sodium` 是一个独立 substance，其 base variant_id 恰好占用 `flucloxacillin-sodium`），目标 id 被占；需先合并/重命名这些 substance（见 §6.1） |
| 原料名 INVALID / 过敏原提取物等 | ~10 | dm+d 自身标记无效或非小分子，跳过 |

---

## 5. 副本验证（`.tmp/dmd-salt/snapshot.db`，SQLite backup API 快照，450 MB）

| 步骤 | variant 总数 | salt_code 非空 | GB 组件挂盐 variant | GB 组件挂 base | integrity |
|---|---:|---:|---:|---:|---|
| 快照（before） | 13,742 | 1,555 | 1,313 | 64,301 | ok |
| `--apply` | **13,869（+127）** | **1,682（+127）** | **16,396（+15,083）** | 49,218 | ok |
| 二次 `--apply` | 13,869 | 1,682 | 16,396 | 49,218 | **幂等：0 写入** |
| `--rollback` | **13,742（−127）** | **1,555（−127）** | **1,313（−15,083）** | 64,301 | ok |
| 再 `--apply`（可重放） | 13,869 | 1,682 | 16,396 | 49,218 | ok |

- `product_component` 总数全程 **不变**（只改 `variant_id` 指向，不丢行）；`PRAGMA foreign_keys=ON`、`integrity_check=ok`。
- 撤销清单：`.tmp/dmd-salt/undo_*.json`（约 2.2 MB，含 127 个 variant 全字段 + 15,083 个组件的旧 variant；重复回滚幂等）。
- 真实库 `data/drugs.db` 全程只读（`mode=ro`），mtime 未变。

---

## 6. 风险与下一步

### 6.1 高风险：盐名 substance 占用 variant_id（约 1,722 组件，2.6%）

库里有一批「盐名 substance」：`flucloxacillin-sodium`、`citalopram-hydrobromide`、`oxybutynin-hydrochloride`、`galantamine-hydrobromide`、`ondansetron-hydrochloride-dihydrate`、`pantoprazole-sodium-sesquihydrate`、`dosulepin-hydrochloride`…它们本身是 substance（base variant=sid），把目标 `variant_id` 占住了。本轮**不覆盖、不合并**，直接跳过。建议下一步：
1. 先跑 substance 去重（把盐名 substance 并入 base substance，参考 ES/CN 合并工具）；
2. 再重跑本脚本 → 这 ~1,722 个组件可一并恢复。

### 6.2 中风险：同盐 variant 歧义（1,305 组件）

同成分已有多个 `salt_code` 相同的 variant（典型：`x-hydrochloride` 与 `x-hcl`，来自不同 ETL 的写法；或 `x-hydrochloride` 与 `x-hydrochloride-monohydrate` 的水合物差异）。脚本拒绝猜。建议：
- 一次性 variant 去重（同 substance + 同 salt_code + 同 hydrate 词集合并/删冗余），合并后重跑可再恢复 1,305 组件；
- 合并前先把引用这些 variant 的 `product_component` 一并改指（与 merge 工具同语义）。

### 6.3 其他风险

| 风险 | 说明 / 缓解 |
|---|---|
| **强度基准不明** | 恢复了盐型 ≠ 能算 D2：dm+d 的 strength 是 VMP 名字里的数值（如 "Atorvastatin 10mg"），基准是 base 还是盐需逐药核说明书；新 variant 的 `base_fraction=1.0`、`strength_basis='unknown'` 是刻意的，D2 展示必须等基准字段补齐 |
| **水合物** | 342 个组件（17 个 variant）带 hydrate；D2 折算要按「无水/含水」两种基准分别处理（与 dose-mapping-plan §2.1 一致），本轮只记录事实 |
| **复方** | 7,231 个产品（4,214 DB 多组件 + 3,017 VMP 多成分）未处理；需要「VTM 成分序 ↔ VPI 序」逐成分对齐，建议单独任务 |
| **同名不同盐** | 本轮要求「原料名基名精确匹配成分基名」，避免把 `Benzylpenicillin sodium` 硬塞给 `Penicillin G`；宁可漏（34,568 跳过的尾部）也不误配 |
| **并发写库** | apply 前确认无并行入库/建站；脚本对真实库强制 `--confirm-real-db` 且自带撤销清单，回滚可复现 |
| **许可** | dm+d 为 OGL v3.0（source 表已记录），页面/报告需署名 NHSBSA；本报告只引用事实字段 |

---

## 7. apply 建议（Lead 执行，本任务不写真实库）

前置：`data/backups/` 备份当前库；确认无并行写库 / 建站（AGENTS.md §7）。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 先看计划（只读，约 1–2 分钟，输出落在 .tmp/dmd-salt/dryrun_plan.csv）
& $py etl/fix_dmd_salts.py --dry-run

# 2) 真实库 apply（事务 + 撤销清单）
& $py etl/fix_dmd_salts.py --apply --confirm-real-db

# 3) 验收（预期：variant 13,742→13,869；GB 组件挂盐 1,313→16,396；integrity ok）
& $py etl/fix_dmd_salts.py --verify

# 4) 幂等复跑（应输出「没有可恢复项」）
& $py etl/fix_dmd_salts.py --apply --confirm-real-db

# 5) 如需回滚（需加 --confirm-real-db；缺省取 .tmp/dmd-salt 最新清单）
& $py etl/fix_dmd_salts.py --rollback --confirm-real-db
```

apply 后由 Lead 决定 rebuild/publish（本任务未跑 `site/build.py`）。建议 apply 后把 §6.1/§6.2 的 substance/variant 去重列为下一批任务，再重跑本脚本把 1,722 + 1,305 个组件补齐。

---

## 8. 对 D2 折算的解锁意义（为什么值得 apply）

- GB 组件盐型覆盖：**2.0% → 25.0%**（1,313 → 16,396 / 65,614），dm+d 从「只能 D1」变成 D2 的可用数据源之一；
- 与 `reports/dose-mapping-plan.md` 的 D2 候选直接对接：**16 个已有碱基分子量的成分 / 1,726 个组件**可立即进入折算回填（Quetiapine 290、Metformin 230、Atorvastatin 228、Venlafaxine 199、Sildenafil 160、Rosuvastatin 160、Sertraline 139、Clindamycin 98、Metoprolol 80、Omeprazole 45…）；
- 剩余 13,357 个组件的折算只差「碱基分子量 + 强度基准」两类数据，salt 元数据已经就位；
- 对三语检索/身份卡也有正向影响：GB 商品名页/成分页能显示真实盐型（如 Metformin hydrochloride），与 US/CA/ES 的盐 variant 对齐。

---

## 9. 复现与产物

```powershell
# 生成 DB 副本（SQLite backup API，1–2 秒）
& $py .tmp/dmd-salt/make_snapshot.py
# dry-run（真实库只读）
& $py etl/fix_dmd_salts.py --dry-run
# 副本 apply / 幂等 / rollback
& $py etl/fix_dmd_salts.py --apply --db .tmp/dmd-salt/snapshot.db
& $py etl/fix_dmd_salts.py --apply --db .tmp/dmd-salt/snapshot.db   # 幂等
& $py etl/fix_dmd_salts.py --rollback --db .tmp/dmd-salt/snapshot.db
& $py etl/fix_dmd_salts.py --verify --db .tmp/dmd-salt/snapshot.db
```

| 产物 | 内容 |
|---|---|
| `etl/fix_dmd_salts.py` | 解析 + 计划 + apply/rollback（事务、幂等、真实库 guard、撤销清单） |
| `.tmp/dmd-salt/dryrun_plan.csv` | 15,083 行可恢复清单（5.3 MB，可逐行复核） |
| `.tmp/dmd-salt/dryrun_real.log` / `dryrun_copy.log` | dry-run 日志（真实库 / 副本一致） |
| `.tmp/dmd-salt/apply.log` / `apply2.log` / `apply_idempotent.log` | apply、可重放、幂等证据 |
| `.tmp/dmd-salt/rollback.log` + `verify_after_*.log` / `verify_final.log` | 回滚与前后计数、integrity |
| `.tmp/dmd-salt/undo_*.json` | 撤销清单（127 variant + 15,083 组件映射） |
| `.tmp/dmd-salt/snapshot.db` | 副本（apply/rollback 验证载体，非项目数据） |
| `.tmp/dmd-salt/stats.json` / `stats2.py` | 可恢复/跳过/盐型分布/D2 覆盖统计 |

边界：未写 `data/drugs.db`（只读 + 副本 apply）、未改 `etl/ingest_dmd.py`、`site/build.py`、未跑 git/发布；写范围仅 `etl/fix_dmd_salts.py`、`.tmp/dmd-salt/`、本报告。
