# FR 数据质量写库（v0.11.5 窗口：把 task-68 新规则应用到真库）

> 日期：2026-11-13（北京时间）· 工位：page-slim · 任务：`task-1`（= task-68 apply）+ `task-6`（v2 修正）
> **本报告分两段**：§0 = **v2（task-6 修正后，发布口径）**；§1–§7 = v1（task-1 首次写库）的过程证据与背景。
>
> **发布口径（v3，现查）**：FR **14,503 / 15,799 = 91.80%** 有成分（严格口径：已剔除全部粗略映射）、
> **13,733 / 15,799 = 86.92%** 有剂量（其中 composition 来源 11,746、品名补足 **1,987**）、`form_base=other` **3**（99.98% 结构化）。
> **不要再引用 v1 的 92.06%。** 仍差 32 个产品才到 92%（0.92×15,799 = 14,535）。
>
> v1 结论（留档）：apply 成功（9.5 s，exit 0，before/after 与 dry-run 逐项一致），成分映射 13,861 → 14,543（92.06%）、
> 规格 11,255 → 13,754（87.06%）、`form_base=other` 567 → 3；但 v1 的 682 个新映射里有 81 个是「粗略/不精确映射」
> （泛称离子 `Sodium`/`Calcium`/… + `cn-*` 中文物质），严格口径只有 91.58%，Lead 决定**发布前修**，遂有 v2。

---

## 0. v2：FR 粗略映射修正（task-6，发布口径）

### 0.1 改了什么（只动 `etl/markets/fr.py` 解析层）

| # | 改动 | 位置 |
|---|---|---|
| ① | **黑名单**：泛称离子 `Sodium/Calcium/Potassium/Sulfate/Ferric/Sulfur/Water` **无条件**不予映射；`cn-*` 中文命名物质**只在残串命中时**挡（完整 token / 显式同义词命中的保留，如 `VALPROMIDE` → 库内 cn 行的丙戊酰胺） | `FR_BLOCKED_SUBSTANCES` + `FrMapper._load_blocked()` / `push()` |
| ② | **残串闸门**：候选串里一个实词都没有（`a 3 pour cent`、`b pour preparations homeopathiques`、`solution de`）或整体 ≤2 字符的碎片，不再送进 `SgMapper.map_basic()` 的低特异性层 | `_RESIDUAL_WORDS` + `_is_residual_candidate()`，在 `map_candidates()` 里先挡 |
| ③ | **丢弃并计数**：被挡掉的候选 / token 计入 `FrMapper.stats`，dry-run 打印并写进 `fr_dry_run.json` 的 `substance.guard` | `_collect()` + `cmd_dry_run()` |

> 说明：① 采用「泛称离子全挡、`cn-*` 只挡残串」的口径——实测全挡会顺带删掉身份本来就正确的
> `VALPROMIDE`（depamide）、`ALUMINIUM PHOSPHATE`（phosphalugel/moxydar）等；只挡残串既清掉 `a 3 pour cent → A型肉毒毒素`
> 这类误命中，又保住完整 token 的正确对应。**其它市场、schema、站点代码一个字没动。**

### 0.2 数字（before = v1 库，after = v2 库，全部现查 SQL）

| 指标（FR 层） | v1（task-1） | **v2（本次 / 发布口径）** | v1→v2 |
|---|---:|---:|---:|
| FR 产品 | 15,799 | **15,799** | 0 |
| FR component | 20,448 | **20,141** | −307 |
| 有 ≥1 component 的产品 | 14,543（92.06%） | **14,437（91.38%）** | −106 |
| 有 ≥1 有剂量 component 的产品 | 13,754（87.06%） | **13,667（86.51%）** | −87 |
| `form_base=other` | 3 | **3** | 0 |
| 泛称离子 component | 682 | **2**（均为 potassium gluconate，身份正确） | −680 |
| `cn-*` component | 127 | **6**（valpromide 1 + aluminium phosphate 5，身份正确） | −121 |
| 无 component 的产品 | 1,146 | **1,362** | +216 |

**给 CHANGELOG 的两个口径（别混用）**：

| 口径 | 分子/分母 | 比例 |
|---|---|---:|
| **全量（严格）** | 14,437 / 15,799 | **91.38%**（未达 ≥92%，差 0.62pp） |
| **非顺势**（BDPM 顺势产品 1,477 个按设计不映射：无 INN、只有 4CH 稀释度） | 13,904 / 14,322 | **97.08%** |

> 1,362 个无成分产品 = 顺势 944 + 非顺势 418。建议发布说明写「FR 有成分 14,437（91.4%；非顺势 97.1%）」，
> 不要写「92.1%」。

### 0.3 验证（每一步都留了证据）

| 验证 | 结果 |
|---|---|
| `--self-check`（改后） | **0 项失败**（exit 0） |
| 副本预演 | 从真库新拷副本 → `--dry-run` → `--apply`（manifest `fr_manifest_v0115b_copy.json`）→ 逐项核对，**泛称离子 682 → 2、`cn-*` 127 → 6**，残留 8 条逐条人工核对为正确身份 |
| 真库 apply | exit 0，**北京 2026-11-13 01:15:45 → 01:15:55**（10.9 s，事务提交），`written`：product 15,799 / component 20,141 / name_key 0 / name_variant 0 |
| 备份（写前） | `data/backups/drugs-before-fr-v2-20261113.db` · **452,517,888 B** · sha256 **`c6b0483d71c524abf63c4a17ae4bcd809b647cd03408d3a3acb5339bedeca4be`**（= v1 写后库，逐字节一致） |
| 撤销清单 | `.tmp/fr-ingest/fr_manifest_v0115b.json` · 287,279 B · sha256 `e9e23d0264c28d12…` · `db_sha256_before` = 备份 sha256 · `db_sha256_after` = **`0fdd44424a6e69758dd85e7daae69ba473c9e0759b51af934373910275dc3e50`**（= 现库现查，说明写后无第二写者） |
| 全局计数 | `product` **494,992 不变** · `product_component` 650,599 → **650,292** · `name_key` 214,397 · `name_variant` 246,650 · `substance` **12,637** · `product_name` 670,803 · `ingest_run` 21（同 `run_id` 覆盖写） |
| `coverage` FR 行 | `(FR, 15799, **2011**, 13559, '2026-11-12')` |
| `PRAGMA foreign_key_check` | **0 行** ✅ |
| 其他市场 | product 分组计数逐行不变（CN 145,051 / US 110,179 / GB 61,051 / … / EU 2,095） |
| `db/check_data.py` | **exit 0**；实质差异只有 3 行：`components 650,292` · `collisions(severe) 25,088`（v1 24,954，**自动推导副作用** +134）· FR coverage 行 |
| 残留「黑名单类」8 条 | 已逐条核对：`FR-63737879 Valpromide`、5 条 `Aluminium Phosphate`（phosphalugel / moxydar / neutricid）、2 条 `Potassium`（potassium gluconate 糖浆/滴剂）——**身份正确**，不是粗略映射 |
| `deploy/ci_checks.py --fast` | **exit 0 · 12 项：PASS 8 / FAIL 0 / SKIP 4**（14.2 s；unittest etl 55 / lib 61 / mobile 29 / atc 4 全 OK） |
| 检索抽检（只读 CLI） | `cli.py "doliprane"` 命中 18 个 FR 键、成分 Acetaminophen、规格/剂型正常；`cli.py "paracétamol"` 命中 60 键、跨 GB/ES/MX/AU 正常 |

### 0.4 回滚（三条路，语义不同）

```powershell
# ① 回 v1（task-1 状态；期望 component 650,599 / 有成分 14,543 / 有剂量 13,754）
Copy-Item -LiteralPath data\backups\drugs-before-fr-v2-20261113.db -Destination data\drugs.db -Force

# ② 回 v0.11.4（写库前；期望 component 649,322 / 有成分 13,861 / 有剂量 11,255 / form_base=other 567）
Copy-Item -LiteralPath data\backups\drugs-before-fr-quality-20261113.db -Destination data\drugs.db -Force

# ③ 按 manifest 只删本次写入（会把 FR 层删成 0 行，不是回 v1，只在「不要 FR 层」时用）
& $py etl/markets/fr.py --rollback --allow-real --db data/drugs.db --manifest .tmp/fr-ingest/fr_manifest_v0115b.json
```

### 0.5 v2 仍未做的（已知缺口，v0.11.6 建议）

1. **10 个法国独有 INN 未补**（oxomémazine / métopimazine / thiocolchicoside / biclotymol / cyamémazine / propériciazine /
   brétovaméran / josamycine / promestriène / omoconazole）：需要逐个核 INN + ATC 出处并新增 substance/variant/映射，
   时间盒内做不踏实；且按 dry-run §4 估计只 +0.4–0.5pp（≈91.8%），仍到不了 92%，性价比低——建议单开任务补。
2. **关键词匹配仍是子串**：`THYM` 会命中 `THYMOCYTE`（16 个 FR 产品被映射成 `thymus vulgaris leaf`），v1/v0.11.4 同样存在，
   本轮未改（不在 task-6 范围）；v0.11.6 应改成词边界匹配。
3. **两次 apply 之间 component 计数有 ±1 抖动**（dry-run 20,141 / 副本 apply 20,142 / 真库 apply 20,141）：
   来自候选解析的哈希序，建议 v0.11.6 固定候选排序，避免构建确定性报告出现 ±1。
4. **三语回归未在窗口内跑完**（见 §6.4），由 Lead 的全量 `ci_checks.py` 覆盖。

---

## 0.6 v3：FR 独有 INN 补种（7 个有可核 ATC 出处，发布口径）

Lead 给的 40 分钟加时段，按「**只有能拿到可核 INN 名 + ATC 出处才做**」执行：查 WHOCC ATC/DDD Index 2026
（按 INN 名逐条检索）后，**7 个有唯一 ATC 码的补进库**，3 个查不到、按纪律不猜。

| INN | ATC | 出处（WHOCC 按名检索） | FR 产品数（现查） |
|---|---|---|---:|
| Oxomemazine | R06AD08 | `?name=oxomemazine` | 25 |
| Metopimazine | A04AD05 | `?name=metopimazine` | 12 |
| Thiocolchicoside | M03BX05 | `?name=thiocolchicoside` | 10 |
| Cyamemazine | N05AA06 | `?name=cyamemazine` | 9 |
| Josamycin | J01FA07 | `?name=josamycin` | 5 |
| Omoconazole | D01AC13（另有妇科用 G01AF16，表只有一列，存 D01AC13） | `?name=omoconazole` | 3 |
| Promestriene | G03CA09 | `?name=promestriene` | 2 |
| **合计** | | | **66** |
| ~~Biclotymol / Propericiazine / Bretovameran~~ | **WHOCC 2026 无条目 → 不补** | — | 14（挂 v0.11.6） |

- **新增文件** `etl/markets/fr_inns.py`：三段式（`--dry-run` / `--apply` / `--rollback`），幂等（已存在跳过）、事务写库、
  写 manifest；只插 `substance` + 一条同名 `variant`（salt/hydrate/ester 空、`base_fraction=1.0`、`interchange='unknown'`），
  `source_id/method/confidence` 留空（与库里 12,637 行现状一致；新数据源要先过许可，故不建 `source` 行）。
- **不影响其他市场**：只做 INSERT，不改任何既有行；其他市场 product/component 计数不变（见下）。

| 指标 | v2 | **v3（发布口径）** |
|---|---:|---:|
| FR 有成分 | 14,437（91.38%） | **14,503（91.80%）** |
| FR 有剂量 | 13,667（86.51%） | **13,733（86.92%）** |
| FR component | 20,141 | **20,207** |
| `substance` / `variant` | 12,637 / 14,237 | **12,644 / 14,244**（+7 / +7） |
| `product` / `name_key` / `name_variant` | 494,992 / 214,397 / 246,650 | **不变** |
| `coverage` FR 行 | (15799, 2011, 13559, 2026-11-12) | **(15799, 2018, 13559, 2026-11-12)** |
| FK / `check_data.py` | 0 / exit 0 | **0 / exit 0**（v2→v3 只差 4 行：coverage、components、substances、variants） |

**关键：`品名补足` 的最终口径（回答覆盖页文案）**

| 项（产品级，分母 15,799） | 数量 | 占比 |
|---|---:|---:|
| 有 ≥1 有剂量 component（合计） | **13,733** | 86.92% |
| └ 剂量来自 composition（成分表 dosage） | **11,746** | 74.38% |
| └ 剂量来自**品名补足**（单成分且 composition 无剂量时从 dénomination 抽） | **1,987** | 12.58% |

> 口径说明：库里 `product_component` **没有** `strength_source` 列，所以这个拆分不能直接 SQL 出来，而是用**最终解析器**
> 在最终库副本上重跑 dry-run（`.tmp/fr-ingest/fr_dry_run.json` 的 `strength` 段）得到的；它与库里现查的
> 有规格产品数 **13,733 完全一致**、component 20,207 也一致，可以当作发布口径用。
> 覆盖页那句「1,993 / 15,799 品名补足」应改成 **「1,987 / 15,799 = 12.6%」**；composition 来源 **11,746（74.4%）**。
> （v1 的 1,993 已作废；v2 的 1,982 也作废。）

**写库与回滚（v3）**

```powershell
# 备份（写前）：data/backups/drugs-before-fr-v3-20261113.db · 452,517,888 B · sha256 0fdd44424a6e6975…（= v2 库）
# ① 补种 7 个 INN（北京 01:19:58）：manifest .tmp/fr-inns/manifest_real.json（inserted_substances 7 / inserted_variants 7）
& $py etl/markets/fr_inns.py --apply --allow-real --db data/drugs.db --manifest .tmp/fr-inns/manifest_real.json
# ② 重写 FR 层（北京 01:20:09，9.99 s，exit 0）：manifest .tmp/fr-ingest/fr_manifest_v0115c.json
& $py etl/markets/fr.py --apply --allow-real --db data/drugs.db --manifest .tmp/fr-ingest/fr_manifest_v0115c.json
# 现库 sha256 3f0ae738d6d766e9…（452,550,656 B）
```

回滚顺序（先撤 FR 层、再撤 INN）：
`fr.py --rollback --manifest fr_manifest_v0115c.json` → 再 `fr.py --apply` 用 v2 manifest？**不建议**；
最简是直接还原备份：`Copy-Item data\backups\drugs-before-fr-v3-20261113.db data\drugs.db -Force`（回到 v2），
或 `drugs-before-fr-quality-20261113.db`（回到 v0.11.4）。

**v3 后验证**：`check_data.py` exit 0（v2→v3 只差 coverage / components / substances / variants 四处计数）；
`PRAGMA foreign_key_check` 0 行；其他市场 product 计数不变；`deploy/ci_checks.py --fast` **PASS 8 / FAIL 0 / SKIP 4**（13.5 s）；
`cli.py "oxomemazine"` 命中 23 键、成分显示 `Oxomemazine`（新 substance 已进检索链路）。
`trilingual` 全量本轮**未跑**（v1 那次在窗口内跑 >10 分钟未结束已停），交 Lead 的全量 `ci_checks.py`。

---

## 1. 备份与回滚（v1：先备份，后写库）

| 项 | 值 |
|---|---|
| 备份文件 | `data/backups/drugs-before-fr-quality-20261113.db` |
| 字节数 | **452,247,552**（= 写前 `data/drugs.db` 同尺寸） |
| sha256 | **`5deee24cee6b3512cf005719e97445e88d8926b8965d76ce4c504c669cefdcec`** |
| 核对 | 备份与写前库 sha256 **完全一致**（`match=True`） |
| 写后库 | 452,517,888 B（+270,336 B）· sha256 **`c6b0483d71c524abf63c4a17ae4bcd809b647cd03408d3a3acb5339bedeca4be`** |
| 撤销清单 | `.tmp/fr-ingest/fr_manifest_v0115.json`（287,279 B · sha256 `5925afcf…4742eb4e`） |

**回滚有两条路，语义不同，别混**：

1. **回到 v0.11.4 的 FR 层（推荐）**——用备份文件覆盖：
   ```powershell
   Copy-Item -LiteralPath data\backups\drugs-before-fr-quality-20261113.db -Destination data\drugs.db -Force
   ```
   覆盖后应回到：`product_component` 649,322 · FR 有成分 13,861 · FR 有剂量 11,255 · `form_base=other` 567 ·
   `name_key` 214,397 · `ingest_run` 20。
2. **按 manifest 撤销本次写入**——`--rollback` **只删本次写入的行**，会把 FR 层删成 **0 行**（不是回到 v0.11.4），
   因为 apply 先 `DELETE` 了旧 FR 行（15,799）再重写。仅在「不要 FR 层了」时用：
   ```powershell
   & $py etl/markets/fr.py --rollback --allow-real --db data/drugs.db --manifest .tmp/fr-ingest/fr_manifest_v0115.json
   ```
   manifest 自带的校验口径：`SELECT COUNT(*) FROM product WHERE country='FR' AND source_id='bdpm_fr'` 应为 0。

---

## 2. 命令与时间线（都在仓库根目录跑）

| 步骤 | 命令 | 结果 |
|---|---|---|
| 备份 | `Copy-Item data\drugs.db data\backups\drugs-before-fr-quality-20261113.db` + `Get-FileHash` | sha256 一致（§1） |
| 自检 | `& $py etl/markets/fr.py --self-check` | **exit 0，0 项失败**（`.tmp/fr-apply/self_check.txt`） |
| 写前体检 | `& $py db/check_data.py` | exit 0（`.tmp/fr-apply/check_data_before.txt`） |
| **写库** | `& $py etl/markets/fr.py --apply --allow-real --db data/drugs.db --manifest .tmp/fr-ingest/fr_manifest_v0115.json` | **exit 0**（`.tmp/fr-apply/apply_stdout.txt`） |
| 写后体检 | `& $py db/check_data.py` | exit 0（`.tmp/fr-apply/check_data_after.txt`） |

- **apply 开始** 2026-11-12T09:00:31 -08:00 = 北京 **2026-11-13 01:00:31**
- **apply 结束** 2026-11-12T09:00:40 -08:00 = 北京 **2026-11-13 01:00:40**（脚本自报 8.95 s；墙钟 9.5 s）
- 写库事务：`BEGIN IMMEDIATE` → 删旧 FR 行 → 写 15,799 product / 20,448 component / 15,799 product_name / 1 ingest_run → `COMMIT`（失败自动 `rollback`）
- 新 `ingest_run` = **`bdpm_fr-2026-11-12`**（脚本按 **UTC 日期**命名，故比北京日期小一天）· `status=ok` · `rows_in=15,799` · `rows_rejected=0`
- 写后库 sha256 = manifest 里的 `db_sha256_after`（**说明写完到现在没有第二个写入者**，可放心解冻）

---

## 3. Before / After（全部现查 SQL，`db/q.py`）

### 3.1 全局表计数（口径：整库）

| 表 | before | after | 变化 |
|---|---:|---:|---:|
| `product` | 494,992 | **494,992** | 0 ✅ |
| `product_component` | 649,322 | **650,599** | **+1,277**（= FR 19,171→20,448 的差值，逐字节对上） |
| `product_name` | 670,803 | **670,803** | 0 |
| `name_key` | 214,397 | **214,397** | 0 ✅ |
| `name_variant` | 246,650 | **246,650** | 0 ✅ |
| `substance` | 12,637 | **12,637** | 0 ✅ |
| `source` | 42 | 42 | 0（`bdpm_fr` 行原地更新 `retrieved_at=2026-11-12`） |
| `ingest_run` | 20 | 21 | +1 |

### 3.2 FR 层（口径：`product.country='FR' AND source_id='bdpm_fr'`）

| 指标 | before | after | 目标 |
|---|---:|---:|---:|
| FR 产品 | 15,799 | **15,799** | 不变 |
| 有 ≥1 component 的产品 | 13,861（87.73%） | **14,543（92.06%）** | ≥92% ✅ |
| component 总数 | 19,171 | **20,448** | — |
| component 带剂量 | 14,276（74.47%） | **17,165（83.95%）** | — |
| 有 ≥1 有剂量 component 的产品 | 11,255（71.24%） | **13,754（87.06%）** | ≥80% ✅ |
| `form_base` 非 other | 15,232（96.41%） | **15,796（99.98%）** | 结构化 ✅ |
| └ `form_base='other'` | 567 | **3** | — |
| `coverage` 的 FR 行 | `(FR, 15799, 1869, 13559, '2026-11-11')` | `(FR, 15799, **1984**, 13559, '**2026-11-12**')` | n_variants 随新成分上升 |

`form_base=other` 剩下的 3 条（不再猜剂型，保留 BDPM 原文）：

| product_id | dosage_form | route |
|---|---|---|
| FR-61695844 | matrice | intralésionnelle |
| FR-69739292 | pâte pour usage dentaire | dentaire |
| FR-67644148 | pâte pour usage dentaire | dentaire |

### 3.3 其他市场（`SELECT country, COUNT(*) FROM product GROUP BY country`）

CN 145,051 / US 110,179 / GB 61,051 / AU 44,794 / CA 43,847 / ES 25,395 / TW 16,457 / **FR 15,799** /
HK 13,935 / MX 10,878 / SG 5,511 / EU（`country IS NULL`, 2,095）——**写前写后逐行相同**，只有 FR 行内容变了。

### 3.4 `db/check_data.py` 前后差异（全量 diff 只有 6 行）

| 行 | before | after | 说明 |
|---|---|---|---|
| `components` | 649,322 | 650,599 | FR +1,277 |
| `collisions(severe)` | 24,954 | **25,092（+138）** | **自动推导的副作用**：新映射把更多「名字 × 成分」组合带进 `collision` 视图；不是手工标注（§1.2 底线不变），发布说明里建议提一句 |
| `('FR', …)` coverage 行 | `15799, 1869, 13559, 2026-11-11` | `15799, 1984, 13559, 2026-11-12` | 新成分带来的 variant 数 +115 |

---

## 4. 与 dry-run（`reports/2026-11-14-fr-quality.md`）的差异

**零差异**，逐项对上：

| 项 | dry-run 预测 | 真库 after |
|---|---:|---:|
| 有成分产品 | 14,543 | 14,543 ✅ |
| component 总数 | 20,448 | 20,448 ✅ |
| component 带剂量 | 17,165 | 17,165 ✅ |
| 有剂量产品 | 13,754 | 13,754 ✅ |
| `form_base=other` | 3 | 3 ✅ |
| name_key / name_variant 新增 | 0 / 0 | 0 / 0 ✅（manifest `written.name_key/name_variant = 0`） |
| substance 新增 | 0 | 0 ✅ |

两点口径说明：
1. dry-run 报告里的「1,993 个产品规格来自品名补足」是**解析期统计**，库里 `product_component` 没有 `strength_source` 列，
   **入库后无法按来源区分**（只能看到「有剂量 13,754」）。要页面标「部分规格来自品名」，得靠报告/SQL 口径，不能从库现查。
2. `ingest_run` 用 UTC 日期 → `bdpm_fr-2026-11-12`（北京 2026-11-13 01:00 写的），与 task 名 `20261113` 不冲突，但不是笔误。

---

## 5. 写库后一致性核对（用备份库做写前快照，只读比对）

脚本：`.tmp/fr-apply/diff_fr.py`、`coarse_breakdown.py`、`quality_before_after.py`（都在 `.tmp/`，不入库）。

| 核对 | 结果 |
|---|---|
| FR `product_id` 集合 | 写前写后 **完全相同**（15,799，无增无删） |
| 新增 component 的产品 / 丢掉 component 的产品 | **+682 / 0** |
| 新增有剂量的产品 / 丢掉剂量的产品 | **+2,499 / 0**（没有产品因重写而失去剂量） |
| `form_base` 发生变化的产品 | 1,814（`other` 之外还有 tablet/powder/liquid 等重分类，来自结构化 `forme` 字段） |
| `PRAGMA foreign_key_check` | **0 行** ✅ |
| manifest 内部一致性 | `counts_planned`（15,799/20,448/0/0/0）= `written`（同）· `counts_after` = 现库现查 · `product_ids` 15,799 条 · `db_sha256_before` = 备份 sha256 · `db_sha256_after` = 现库 sha256 ✅ |
| 再跑一次是否幂等 | 由 `--self-check` 的 manifest 断言覆盖（planned == written）；本次未重复 apply（避免二次改写 `ingest_run`） |
| 三语检索回归 | 见 §6.4（只读测试，写库后跑一次） |

抽样（新获得 component 的产品，20 条，身份对应正确，节选）：

| product（FR 商品名） | 映射到 | 剂量 |
|---|---|---|
| perindopril tosilate teva comprime pellicule | Perindopril（盐型无 variant → 回退基名，dry-run §3 已声明） | 10 mg |
| doxylamine cristers comprime pellicule secable | Doxylamine | 15 mg |
| daflon comprime pellicule | Bioflavonoids | 500 mg |
| permixon gelule | Serenoa Repens | 160 mg |
| clopidogrel zf comprime pellicule | Clopidogrel Hydrogen Sulfate | 75 mg |
| lanthane viatris comprime a croquer | Lanthanum Carbonate Hydrate | 1000 mg |
| cabazitaxel teva pharma ml a diluer pour perfusion | Cabazitaxel | 10 mg |
| kaloba comprime pellicule | Pelargonium Sidoides Root | 20 mg |
| palforzia poudre orale en | Arachis Hypogaea | 300 mg |
| ravicti ml liquide | Glycerol | 1.1 g / 1 mL |

---

## 6. 已知问题与边界（**发布前请 Lead 看一眼 §6.1**）

### 6.1 P1：81 个新映射产品的成分是「粗略/不精确」映射（74 个全粗略）

量化（`coarse_breakdown.py`，备份库 vs 现库）：

| 项 | 值 |
|---|---:|
| 新获得 component 的产品 | 682 |
| └ 成分**全部**是粗略映射（泛称离子 / `cn-*` 中文物质） | **74** |
| └ 至少 1 个粗略映射 | 81 |
| 严格口径（去掉 74 个全粗略）= 成分映射率 | **14,469 / 15,799 = 91.58%**（< 92%） |
| 粗略映射的 component 增量 | 泛称离子物质 **+556**（126→682）· `cn-*` 物质 **+96**（31→127） |
| 顺势产品里被映射出成分的 | 530 → **556**（+26，与「顺势按设计不映射」相悖的残留） |

明细 top（substance / 命中 component 数）：`Sodium` 28、`三维B(cn-)` 20、`Sulfur` 15、`A型肉毒毒素(cn-)` 12、
`Calcium` 10、`Sulfate` 9、`输血用1号抗凝(cn-)` 7、`Ferric` 5、`尿素[13C]呼气试验诊断试剂盒(cn-)` 3、`人凝血因子Ⅸ(cn-)` 2。

根因（已复现，`FrMapper.map_candidates` 追一次即可）：

```
TÉTRADÉCYL SULFATE DE SODIUM
  → 截断候选 'sulfate sodium' / 'sodium' → substance=Sulfate / Sodium（method fr-slug）
HYDROGÈNE (PEROXYDE D'), SOLUTION DE, À 3 POUR CENT   （双氧水！）
  → 截断候选 'a 3 pour cent' → substance=cn-e07218390b = A型肉毒毒素（method fr-inn）  ❌
PARATYPHOIDINUM B POUR PRÉPARATIONS HOMÉOPATHIQUES     （顺势）
  → 截断候选 'b pour preparations homeopathiques' → substance=cn-76b2ff5fae = 三维B（method fr-inn）  ❌
HEPAR SULFUR POUR PRÉPARATIONS HOMÉOPATHIQUES          （顺势）
  → 截断候选 'hepar sulfur pour preparations homeopathiques' → substance=Sulfur（method fr-slug）
```

即：`_collect` 的「候选串逐级截断」（task-68 为救 `esomeprazole-magnesium-dihydrate` 这类无 variant 物质而加的链）
把 `'a 3 pour cent'`、`'b pour …'` 这种**无意义残串**交给 `SgMapper.map_basic`，后者的低特异性层再把它匹配到
首字母相同的 `cn-*` 物质或泛称离子物质；命中后 component 被当成「已映射」，于是放大了映射率。

**建议（v0.11.6，不在本窗口做，因为改规则 = 数字偏离 dry-run = 方案决定）**：
1. 候选链只保留「≥2 个实词」的候选，丢掉 `'a 3 pour cent'` 这类纯虚词残串；
2. 泛称离子物质（`Sodium`/`Calcium`/`Potassium`/`Sulfate`/`Ferric`/`Sulfur`/`Water`）与 `cn-*` 物质 **FR 层不映射**（黑名单）；
3. `POUR PRÉPARATIONS HOMÉOPATHIQUES` 的 token 直接判 `homeo` 跳过（当前 `is_homeopathic()` 只管品名，不管成分串）；
4. 上述修完预计成分映射率 −81 产品（92.06% → 91.5%），**与 dry-run §3 建议的「补 10 个法国独有 INN substance」一起做**才能回到 ≥92% 且严格口径达标。
5. 在修完前，**覆盖页/说明不要宣称「成分映射 92.1% 精确」**；可写「14,543（92.06%）有成分，其中 74 个为成分类别级对应」。

> **Lead 决策（北京 2026-11-13 01:05 收到）**：「发布前修，不把粗略映射带上线」——项目规则「判不了的不写库、丢弃并计数」
> 优先于覆盖率数字。已建 **task-6**（黑名单 + 残串截断，可选补 10 个法国独有 INN）接手；
> **最终发布口径以严格口径（无粗略映射）为准**，CHANGELOG 由 Lead 据此改。
> **task-6 已在本窗口完成**（见 **§0**）：v2 修完泛称离子 682 → 2、`cn-*` 127 → 6（残留 8 条均身份正确），
> 严格口径 **14,437/15,799 = 91.38%**、非顺势 97.08%；本 §6.1 的 v1 数字只作历史证据。

附带发现（同源问题，不单列）：**同一产品里重复同一成分的 component 行** v0.11.4 404 → v1 450 → **v2 431**（顺势复方，
如 `HEPAR SULFUR` 多行同成分）；v2 的黑名单顺手清掉一部分，剩余需 v0.11.6 在成分串层面按「顺势跳过」处理。

复现命令（只读）：
```powershell
& $py .tmp/fr-apply\coarse_breakdown.py data\backups\drugs-before-fr-quality-20261113.db data\drugs.db
& $py db/q.py "SELECT p.product_id, s.inn_en FROM product_component pc JOIN product p ON p.product_id=pc.product_id JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id WHERE p.country='FR' AND s.substance_id LIKE 'cn-%' LIMIT 20"
```

### 6.2 `product_component` 无 `strength_source` 列

品名补足的 1,993 个产品入库后与 composition 来源不可区分（见 §4-1）。若要页面标注，需要 schema 加列（**本轮不改 schema**）。

### 6.3 `collisions(severe)` +138

自动推导结果变化，非手工标注。建议发布说明/交接里提一句，避免下个会话误判为数据回退。

### 6.4 三语检索回归（只读，写库后跑一次）：**窗口内未跑完**

`& $py tests/trilingual/run_tests.py` 于 09:02:48 启动，跑到 09:10 仍未结束（CPU 340 s 以上，管道缓冲导致无中间输出），
为守住 45 分钟写库窗口把进程停掉；**结论：未在窗口内完成，不能算已验**。三语回归与全量 CI 由 Lead 在发布前统一跑
（`deploy/ci_checks.py` 含 trilingual），写库本身不依赖它。

### 6.5 本轮明确没做（守纪律）

- 未 commit、未发布、未跑 `site/build.py`、未写 `site/dist`；
- 未改 `site/`、`db/schema.sql`、`db/init_db.py`、`data/markets.json`、`data/languages.json`；
- **未改 `etl/markets/fr.py` 一个字符**（规则 bug 只做定位与建议，见 §6.1；时间盒内不动语义）；
- 未与其他写库任务并行（写窗口开始到结束只有本工位对库有写连接）。

---

## 7. 附：可复核 SQL 清单

```powershell
# 全局表计数
& $py db/q.py "SELECT (SELECT COUNT(*) FROM product), (SELECT COUNT(*) FROM product_component), (SELECT COUNT(*) FROM name_key), (SELECT COUNT(*) FROM name_variant), (SELECT COUNT(*) FROM substance), (SELECT COUNT(*) FROM product_name), (SELECT COUNT(*) FROM source), (SELECT COUNT(*) FROM ingest_run)"
# FR 层
& $py db/q.py "SELECT COUNT(*) FROM product WHERE country='FR' AND source_id='bdpm_fr'"
& $py db/q.py "SELECT COUNT(*) FROM product_component pc JOIN product p ON p.product_id=pc.product_id WHERE p.country='FR' AND p.source_id='bdpm_fr'"
& $py db/q.py "SELECT COUNT(*) FROM product_component pc JOIN product p ON p.product_id=pc.product_id WHERE p.country='FR' AND p.source_id='bdpm_fr' AND pc.strength_value IS NOT NULL"
& $py db/q.py "SELECT COUNT(*) FROM product p WHERE p.country='FR' AND EXISTS (SELECT 1 FROM product_component pc WHERE pc.product_id=p.product_id)"
& $py db/q.py "SELECT COUNT(*) FROM product p WHERE p.country='FR' AND EXISTS (SELECT 1 FROM product_component pc WHERE pc.product_id=p.product_id AND pc.strength_value IS NOT NULL)"
& $py db/q.py "SELECT form_base, COUNT(*) FROM product WHERE country='FR' GROUP BY form_base ORDER BY 2 DESC"
& $py db/q.py "SELECT * FROM coverage WHERE country='FR'"
& $py db/q.py "SELECT country, COUNT(*) FROM product GROUP BY country ORDER BY 2 DESC"
& $py db/q.py "PRAGMA foreign_key_check"
& $py db/q.py "SELECT run_id, status, rows_in, rows_kept, rows_rejected FROM ingest_run ORDER BY finished_at DESC LIMIT 2"
```

**_本报告为 v0.11.5 真库写窗口证据；DB 已写、已备份、manifest 可回滚。站点重建与发布由 Lead 按 §6 处理。_**
