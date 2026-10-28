# 数据库优化审计：PRAGMA / 索引 / 重复成分（2026-10-28）

> 任务：task-41（DB 优化：PRAGMA/索引/重复成分审计）。交付：`db/optimize_indexes.py`（dry-run 默认 / --apply / --rollback，仅在副本上执行）+ 本报告。
> 约束：**真实库 `data/drugs.db` 只读**（本任务全部连接用 `mode=ro`，未执行任何写语句；审计期间 DB mtime 被其他并发任务更新到 09:46:22，不是本任务写入）；未改 `site/build.py`、未跑 git / 发布。所有 apply/rollback/VACUUM 都在 `.tmp/db-opt/work.db` 副本上验证。

---

## 0. 结论（TL;DR）

| 项 | 结果 |
|---|---|
| 完整性 | `PRAGMA quick_check` = **ok**（0.76 s；`--full-integrity` 可跑 integrity_check） |
| 外键 | **2 条 FK 违规**，全部是历史 `ingest_run → source`：rowid 32 `mx_ccby_pervolume`、33 `cima_combo_fix` 在 `source` 表没有对应行（§2.3） |
| 现有索引 | 33 个（含 12 个 autoindex）；**关键查询不缺索引**，瓶颈是 40–57 万行大表的全表聚合 |
| 建议索引 | **2 个**（`idx_artg_name`、`idx_variant_substance`）+ 1 个可选（`idx_name_variant_kvr`）；实测**否决** 4 类写法（§3） |
| ANALYZE | **不要跑**：实测全库 ANALYZE 后 `load_index` 2.99 s→**7.29 s（+144%）**、成分页产品查询 1.13 s→**3.97 s（+252%）**；当前无 `sqlite_stat1` 是「最优状态」（§5） |
| VACUUM | 空闲页 **25,126 页 = 102.9 MB（22.85%）**；副本实测 **450,396,160 → 325,328,896 B（-125.1 MB / -27.8%），4.97 s，quick_check ok**，查询不变慢 → **建议在维护窗口对真实库执行**（§2.4） |
| 重复成分 | **27 对 / 51 个 id 可自动合并**（同 ATC-4 + 归一化名相同或中文名相同，判据同 `etl/auto_merge_substances.py`）；另有 928 对「名字相近但不可自动合并」需人工（§4.1） |
| 同盐 variant | 歧义 **100 组 / 336 个 variant**；其中 **15 组 / 30 个 / 3,832 组件可合并**，**85 组必须保留**（generic salt_code，如 fluticasone propionate vs furoate）；GB-dmd 现存暴露已从历史报告的 1,305 组件降到 **14**（§4.2） |
| 索引收益 | 小：ARTG 构建查询 50→32 ms（-39%）；variant 查询 0.6→0.1 ms；可选覆盖索引让 displays 131→68 ms（每次构建省 ~63 ms）。**构建总收益 <0.5%**；真正的收益是 VACUUM 体积 −28%（§3.4） |
| 脚本验证 | dry-run / apply / rollback 全部在副本上跑通（exit 0）；apply 建 2 索引 + VACUUM，rollback 删索引后 quick_check=ok（§6） |

---

## 1. 方法与命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py -X utf8 db\optimize_indexes.py                     # dry-run（只读真实库）+ 生成 .tmp/db-opt 审计明细
& $py -X utf8 db\optimize_indexes.py --full-integrity    # 慢速 integrity_check
& $py -X utf8 db\optimize_indexes.py --apply --vacuum    # 复制真实库到 .tmp/db-opt/work.db → 建索引 + VACUUM → 前后基准
& $py -X utf8 db\optimize_indexes.py --rollback          # 按 manifest 删除副本上建的索引
& $py -X utf8 db\optimize_indexes.py --apply --include-optional   # 连可选索引一起建
```

- 真实库只读：dry-run 用 `file:data/drugs.db?mode=ro`；apply/rollback 的 `_guard_copy_path()` 在副本路径等于 `data/drugs.db` 时直接拒绝。
- 不变更数据行：重复成分/同盐 variant 只输出「可合并清单」CSV，不执行合并（合并是独立任务，见 §7）。
- 实验记录：`.tmp/db-opt/bench-probe.json`（全库 ANALYZE 实验）、`bench2.json`（逐个索引/PRAGMA/VACUUM 实验）、`audit-2026-10-28.json`（本次 dry-run 全量结果）。

---

## 2. PRAGMA / 完整性 / FK / VACUUM

### 2.1 PRAGMA 现状（DB 450,396,160 B）

| PRAGMA | 值 | 说明 |
|---|---|---|
| page_size / page_count | 4,096 / 109,960 | — |
| freelist_count | **25,126 页** | = 102,916,096 B（22.85% 是空闲页，删除/更新后未回收） |
| journal_mode | delete | 单写者模式；ingest 并发写会锁库 |
| auto_vacuum | 0 | 未启用自动回收（不建议改：切换需 VACUUM 重建） |
| foreign_keys | 0 | SQLite 默认按连接关闭——**建议所有写入连接显式 `PRAGMA foreign_keys=ON`** |
| cache_size | -2000（2 MB） | 对 450 MB 库偏小，见 §5.2 |
| sqlite_stat1 | **不存在** | 从未 ANALYZE 过 = 当前查询计划最优（见 §5.1） |

大表行数：`product` 409,587 · `product_component` 498,445 · `product_name` 568,907 · `name_variant` 146,544 · `name_key` 135,251 · `variant` 13,886 · `substance` 12,790 · `artg_entry` 34,594 · `dose_warning` 41 · `ingest_run` 14 · `source` 32。

### 2.2 完整性

`PRAGMA quick_check` = **ok**（0.76 s）。建议保留「入库后跑一次 quick_check」的习惯；`--full-integrity` 用于发布前深度检查。

### 2.3 外键违规（历史 ingest_run → source）

`PRAGMA foreign_key_check` 只有 2 行，全部是 `ingest_run` 表：

| ingest_run.rowid | run_id | source_id | 状态 | 问题 |
|---:|---|---|---|---|
| 32 | `mx_ccby_pervolume-2026-10-27` | `mx_ccby_pervolume` | ok | `source` 表无此 source_id |
| 33 | `cima_combo_fix-2026-10-27` | `cima_combo_fix` | ok | `source` 表无此 source_id |

修法（数据补录，独立小任务）：把这两个历史 ingest 的 source 元数据补进 `source`（名称/许可见对应报告），或把 `ingest_run.source_id` 映射到已有 source（如 `inprfm_ccby` / `cima`）。脚本 dry-run 会给出 `fix_sql` 模板。**不影响站点/检索**（`ingest_run` 只做入库审计轨迹）。

### 2.4 VACUUM 评估

| 指标 | 值 |
|---|---:|
| 当前 DB | 450,396,160 B |
| 空闲页 | 25,126 × 4,096 = 102,916,096 B（**22.85%**） |
| 副本 VACUUM 后 | **325,328,896 B（-125,067,264 B，-27.8%）** |
| VACUUM 耗时 | **4.97 s**（副本，SSD/NTFS） |
| 完整性 / 查询 | quick_check ok；基准查询无变慢（负载噪声范围内） |
| 前置条件 | 需 ≈DB 大小空闲磁盘（本机 292 GB free）+ 独占锁 → **在无 ingest/建站的维护窗口执行，先备份** |

> 本次只对副本执行；真实库的 VACUUM 由 Lead 在空闲窗口决定（`run_all.py` 会先备份库，或手动复制一份）。

---

## 3. EXPLAIN 抽样与索引建议

### 3.1 基线（真实库只读，dry-run 计时）

| 代表查询（来源） | 行数 | 耗时 | 计划要点 |
|---|---:|---:|---|
| load_index_main（`site/build.py` 检索索引主查询） | 704,372 | 3,338 ms | `SCAN pc` → product/variant 主键回查；全表聚合 |
| drug_names_trade（成分页商品名） | 255,319 | 636 ms | `SCAN pn` + name_variant 覆盖索引 |
| load_index_displays（`ORDER BY key_id, v_id`） | 146,544 | 154 ms | `SCAN name_variant`（覆盖索引）+ **temp b-tree** |
| top_trade_us（`db/check_data.py`） | 12 | 476 ms | 先按 country 索引再聚合 |
| artg_list（`site/build.py` ARTG 列表 `ORDER BY name`） | 34,594 | 55 ms | `SCAN artg_entry` + **temp b-tree** |
| variant_by_sid（`lib/search.py`/成分页） | 4 | 0.8 ms | `SCAN variant`（13.9k 行，小） |

结论：大查询都是「大表全表聚合」，**加普通索引帮不上**；只有 ARTG 排序和 variant 点查有低成本索引收益。

### 3.2 建议索引（默认 `--apply` 会建）

| 索引 | SQL | 实测收益 | 代价 | 风险 |
|---|---|---|---|---|
| `idx_artg_name` | `CREATE INDEX idx_artg_name ON artg_entry (name)` | ARTG 列表 **50.0 → 30.6 ms（-39%）**，免 temp b-tree | 建 0.357 s，~1.5 MB | 低 |
| `idx_variant_substance` | `CREATE INDEX idx_variant_substance ON variant (substance_id)` | 成分→variant 点查 **0.6 → 0.1 ms** | 建 0.015 s，~0.3 MB | 低 |

### 3.3 可选索引（`--include-optional` 才建）

| 索引 | SQL | 实测收益 | 代价 | 判断 |
|---|---|---|---|---|
| `idx_name_variant_kvr` | `CREATE INDEX idx_name_variant_kvr ON name_variant (key_id, v_id, raw)` | load_index displays **131.4 → 68.1 ms（-48%）** | ~10 MB；建 ~0.3 s | 收益小（每次构建省 ~63 ms），列为**可选** |

### 3.4 实测否决（避免后人重复踩坑）

| 方案 | 实测 |
|---|---|
| **全库 ANALYZE** | load_index **3,017 → 7,292 ms（+142%）**；drug 产品查询 **1,120 → 3,968 ms（+252%）**；规划器改走「SCAN variant + 索引回查 product_component」坏计划 |
| `idx_product_name_cover (name_type, key_id, product_id)` | 成分页商品名 655→182 ms（-72%），但 load_index **2,990 → 8,752 ms（+193%）**、check_data top trade **478 → 1,157 ms（+142%）** → 整体得不偿失 |
| `idx_name_variant_key_vid (key_id, v_id)`（不含 raw） | displays **131 → 443 ms（+237%）**：非覆盖索引，逐行回表取 raw；要建就建上面 3.3 的覆盖版 |
| `idx_product_source (source_id)` | 所有基准查询无变化（2,990→2,991 ms）；现有 SQL 无按 source 过滤的慢查询 |

### 3.5 构建收益结论

- 默认 2 个索引合计约 **-18 ms/build**（ARTG），远小于构建总时长（分钟级）；**不要期望用索引解决 build 慢**——大头是 `load_index`/`collision` 的全表聚合（合计约 6 s，由数据量决定）。
- 更有效的连接级优化（需要改 `site/build.py`，本任务禁改）：`PRAGMA cache_size=-65536`（64 MB）+ `PRAGMA temp_store=MEMORY` 实测 load_index **2,990 → 2,660 ms（-11%）**，与 §3.3 可选覆盖索引一起约可省 **0.4–0.5 s/build**；建议列为后续单独小任务（改 build.py 需完整重建验收）。

---

## 4. 重复成分 / 同盐 variant 审计（只读）

### 4.1 27 对重复成分（可自动合并）

判据复刻 `etl/auto_merge_substances.py`：同 ATC 前 5 位 +（`inn_en` 归一化后相同 **或** `inn_zh` 相同）。
结果：**27 对 / 51 个 id**（明细 `duplicate_substances_merge.csv`；canonical = 产品成分数较多的一方）。典型：

| canonical | 重复 id | 说明 |
|---|---|---|
| `ethinyl-estradiol` | `ethinylestradiol` | 拼写变体 |
| `cn-aaed64f319` | `cn-f6f546ab34` | CN 重复 id，归一化名相同 |
| `cn-2adea44598` | `cn-e414e3b684` | 同上 |
| …（完整 27 行见 CSV） | | |

另有 **928 对「同 ATC-4 名字相近但不可自动合并」**（`duplicate_substances_keep_similar.csv`，编辑距离 ≤2；含盐名 substance、不同酯/盐等），**必须保留/人工判断**，不能批量脚本合并。

合并动作（独立任务，需人确认）：把重复 id 的 `variant.substance_id` 改为 canonical → 删除重复 `substance` 行；`collision` 视图会自动重算，不要手工改。

### 4.2 同盐 variant 歧义（`reports/gb-salt-recovery.md` §6.2 的 1,305 那类）

判据：同 `substance_id` + 同 `salt_code`（`classify_salt` 兜底）+ 同水合物词集（**anhydrous 单独区分**）+ 同 ester/base_fraction。当前库：

| 分类 | 组 | variant | 涉及组件 | 处理 |
|---|---:|---:|---:|---|
| **可合并** | **15** | **30** | **3,832**（GB-dmd 14） | 合并计划 `salt_variant_merge.csv`：保留组件最多的 canonical，其余 variant 的 `product_component` 改指后删除 |
| 必须保留：generic salt_code | 85 | 306 | 3,200 | `''`/`non_salt`/`mixed` 共享编码不代表同盐（如 fluticasone **propionate** vs **furoate**、维生素/疫苗株），**不能合并**；明细 `salt_variant_keep.csv` |
| 必须保留：anhydrous / ester 差异 | （并入上表判定） | | | 无水 vs 未注明水合物语义不同（D2 折算基准），保守不合并 |

可合并示例（完整 15 组见 CSV）：`diphenhydramine hydrochloride ← diphenhydramine-hcl`（1,085 组件）、`lidocaine hydrochloride ← lidocaine-hcl`（850）、`naproxen sodium ← naproxen-sodico`（431）、`diltiazem hydrochloride ← diltiazem-hcl`（313）、`pramoxine hydrochloride ← pramoxine-hcl`（290）。

> 历史 1,305 组件 = 当时 `etl/fix_dmd_salts.py` 在 GB-dmd 侧被「同盐多 variant」拒绝恢复的量；该脚本随后已 apply（GB 盐型恢复），本库现存 GB-dmd 暴露已降到 14 组件。合并这些 variant 后可再跑一次 GB 盐恢复（幂等）把剩余组件补齐。

**合并风险**：variant 的 `salt` 原文字段会随重复行删除而丢失来源写法（合并后 canonical 只保留一种）。建议合并脚本把被删 variant 的 `salt/hydrate/来源` 记进 canonical 的 `interchange_note` 或审计 CSV，再删除；且必须先改引用、后删行。

---

## 5. ANALYZE 与连接 PRAGMA 建议

### 5.1 不要 ANALYZE（实测有害）

| 查询 | 无统计（现状） | 全库 ANALYZE 后 | 变化 |
|---|---:|---:|---:|
| load_index_main | 3,017 ms | **7,292 ms** | **+142%** |
| comp_keys（成分名集合） | 632 ms | 1,229 ms | +94% |
| drug_products（成分页产品） | 1,120 ms | **3,968 ms** | **+252%** |

计划详情：统计让规划器从「SCAN product_component + 主键回查」改成「SCAN variant + `idx_component_variant` 逐 variant 回查」，对 49.8 万组件行是灾难。
- 当前库 **没有 `sqlite_stat1`**，保持现状即可（`db/optimize_indexes.py` 会检查并告警）。
- 若未来某任务跑了 ANALYZE：可 `DELETE FROM sqlite_stat1;` 恢复原计划（bench2 实验 E 验证过删除后计划回到基线）。**不要**用 `PRAGMA optimize` 在长连接里自动生成统计（风险同 ANALYZE）。

### 5.2 连接级 PRAGMA（建议写进 build/ingest 连接，属未来任务）

| PRAGMA | 建议 | 实测/理由 |
|---|---|---|
| `cache_size` | `-65536`（64 MB） | load_index 2,990→2,660 ms（**-11%**）；现在默认 2 MB 对 450 MB 库偏小 |
| `temp_store` | `MEMORY` | 消除 displays/ARTG 的 temp b-tree 磁盘 IO（小收益） |
| `foreign_keys` | `ON`（写入连接） | 默认 OFF，历史 FK 违规就是这么进来的；ingest 写入前开启可在写入时拦截 |
| `journal_mode` | 保持 `delete`（或评估 WAL） | WAL 可改善 ingest 并发读写，但会改变文件布局/备份方式，需单独评审 |

---

## 6. `db/optimize_indexes.py` apply / rollback 验证（副本）

`--apply --vacuum` 实跑（真实库只读复制 → 副本操作）：

```
复制 drugs.db (450,396,160 B) → .tmp/db-opt/work.db
基准（before）…
  建索引 idx_artg_name: 0.357s
  建索引 idx_variant_substance: 0.015s
  VACUUM: 4.97s，450,396,160 → 325,328,896 B
基准（after）…
== apply 结果（副本）==
  DB: 450,396,160 → 325,328,896 B（-125,067,264 B）
  quick_check: ok → ok；FK 违规 2（历史数据，与索引无关）
  load_index_displays   157.1 → 140.8 ms (-16.3)   ← 含 OS page-cache 预热噪声，真实收益见 §3
  artg_list              50.2 →  32.4 ms (-17.8)   ← 与隔离实验 -39% 一致
  variant_by_sid          0.7 →   0.1 ms (-0.6)
```

`--rollback`：按 `.tmp/db-opt/applied.json` 删除 2 个索引 → `quick_check=ok`，DB 保持 VACUUM 后的 325 MB（**VACUUM 不可回滚**，索引可回滚；这是故意设计——rollback 只负责撤销会改查询计划的部分）。

安全设计：manifest 记录源库大小/mtime/sha256、副本路径、创建的索引 SQL、前后基准；rollback 只对 manifest 里的副本生效，且路径守卫拒绝真实库。

---

## 7. 风险与下一步（建议顺序）

| 优先级 | 动作 | 谁/怎么验 | 风险 |
|---|---|---|---|
| P1 | **真实库 VACUUM**（空闲窗口、先备份） | `run_all.py` 前备份或手动 copy → `sqlite3 COPIED` 验证后执行；验收：DB ≈325 MB、quick_check ok、`db/check_data.py` + build 正常 | 需独占锁 ~5 s；磁盘 ≥450 MB；期间禁止 ingest/建站 |
| P1 | **补 2 条历史 source 行**（FK 违规） | 小数据任务：INSERT source（名称/许可参照对应报告）→ `foreign_key_check`=0 | 低 |
| P2 | **把 2 个建议索引落进 `db/schema.sql` + `db/init_db.py` 幂等迁移** | 改 schema 需按 §4 纪律；用副本验证 + `init_db` 老库升级 | 低（索引小）；注意 build 无回归 |
| P2 | **重复成分 27 对合并** | 独立脚本：canonical 化 `variant.substance_id` → 删重复 substance → collision 重算；先 dry-run 清单 | 中（数据语义；保留 928 对人工清单） |
| P2 | **同盐 variant 15 组合并** | 先改 `product_component.variant_id` 指向 canonical → 删重复 variant → 记 raw salt 来源；重跑 GB 盐恢复（幂等） | 中（盐原文来源丢失需记录） |
| P3 | build/ingest 连接加 `cache_size=64MB`/`temp_store=MEMORY`/`foreign_keys=ON` | 改 `site/build.py`/ETL 连接处（**本任务禁改**），全量重建验收 | 低，需 build 回归 |
| P3 | 每次入库/建站后跑 `db/optimize_indexes.py` dry-run | 观察 freelist/i检查/查询计划漂移 | 只读，安全 |

**明确不做**：不跑 ANALYZE；不改 auto_vacuum；不动 `collision` 视图定义；不批量合并 928 对相似成分；本任务不写真实库。

---

## 8. 交付物

| 路径 | 说明 |
|---|---|
| `db/optimize_indexes.py` | 审计 + 索引建议 + 副本 apply/rollback（dry-run 默认；真实库只读；ANALYZE 默认禁用） |
| `.tmp/db-opt/audit-2026-10-28.json` / `audit-latest.json` | 本次 dry-run 全量审计（PRAGMA/FK/EXPLAIN/表计数/索引/清单） |
| `.tmp/db-opt/bench-probe.json` / `bench-probe.py` | 全库 ANALYZE 前后基准（证明有害） |
| `.tmp/db-opt/bench2.json` / `bench2.log` / `probe_bench2.py` | 逐索引 / 连接 PRAGMA / 小表 ANALYZE / VACUUM 实验 |
| `.tmp/db-opt/duplicate_substances_merge.csv` | 27 对可合并清单（canonical/dup/组件数/原因） |
| `.tmp/db-opt/duplicate_substances_keep_similar.csv` | 928 对需保留/人工清单 |
| `.tmp/db-opt/salt_variant_merge.csv` | 15 组 / 30 variant 合并计划（含组件数） |
| `.tmp/db-opt/salt_variant_keep.csv` | 85 组必须保留（generic/anhydrous/ester 差异） |
| `.tmp/db-opt/applied.json` / `apply.log` / `rollback.log` | 副本 apply+rollback 记录（当前副本 325 MB、索引已回滚） |
| `reports/db-optimization.md` | 本报告 |
