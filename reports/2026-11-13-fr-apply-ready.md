# FR 上线前置：`fr.py` 三段式（apply / manifest / rollback）+ 副本全链路验证（task-54）

> 日期：2026-11-13（北京时间）· 工位：page-slim · 任务：`task-54`
> 结论先行：`etl/markets/fr.py` 已补 **`--apply` / `--manifest` / `--rollback` / `--allow-real`** 护栏；
> 在库副本 `.tmp/fr-ingest/drugs_fr_copy.db` 上跑通完整链路：
> **apply → 15,799 产品 / 19,171 组件 / 11,658 新 name_key / 15,545 name_variant / 0 新 substance**
> （与 dry-run 预测逐项一致）；**重复 apply 幂等**（第二次 name_key/name_variant 新增 0、总计数不变）；
> **rollback 后逐表差异 0**（product / component / product_name / name_key / name_variant / source / ingest_run 全部回到写前，FK 空、integrity ok）。
> **今天没有写 `data/drugs.db`**（sha256 仍 `d6e4d088…`）、未改 `site/` / markets / languages、未 commit；
> 真库窗口排下一会话，前置是 `product.country` CHECK 加 `FR` 的 schema 迁移。

---

## 1. 代码改动（只改 `etl/markets/fr.py`）

### 1.1 新增 CLI

| 参数 | 作用 |
|---|---|
| `--apply` | 事务写库：`source`（`bdpm_fr`）+ `product`（country=FR、region=NULL）+ `product_component` + `product_name` + `name_key`/`name_variant` + `ingest_run`。**幂等**：写前先删 `WHERE country='FR' AND source_id='bdpm_fr'` 再写 |
| `--manifest PATH` | 撤销清单（默认 `.tmp/fr-ingest/fr_manifest.json`）：`product_ids` 全量 15,799、`created_name_keys` 11,658、`created_name_variants` 15,545、写前/写后**逐表计数**、库文件 **sha256 before/after**、source 行写前快照、`counts_planned` |
| `--rollback` | 按 manifest **只删本次写入的行**（product_id 必须在 manifest 里且 `country='FR' AND source_id='bdpm_fr'`）；name_key 仅在无 `product_name` 引用时删除；source 行按写前快照恢复或删除；最后逐表对比 `counts_before`，有差即非 0 退出 |
| `--allow-real` | 沿用 `etl/ingest_eu.py`：没有它时 `--apply` / `--rollback` **拒绝真库** `data/drugs.db`；只有副本能直接写 |

### 1.2 护栏与自检

- **真库护栏**：`_guard_real()` —— 真库 + `--allow-real` 缺失 → `SystemExit`（实测真库 sha 未变，见 §4.3）。
- **schema 护栏**：`_require_country_schema()` —— `product.country` CHECK 没有 `'FR'` 时拒绝写入，并提示
  「db/schema.sql 加 FR + db/init_db.py 幂等重建 product 表」；副本上用 `.tmp/migrate_fr_copy.py` 演练同一迁移。
- **manifest 可回滚性**：`_rollback_targets()` 是纯函数，`--rollback` 与 `--self-check` 共用；
  `--self-check` 新增：CLI 四参数齐全、默认库/默认 manifest 都在 `.tmp/`、护栏拒绝/放行、
  `product_id` 确定性、manifest 的 product_ids 全量、sha256 记录、**manifest 计数与 dry-run 预测一致**、回滚计划只含 manifest 里的键。
- `--dry-run` 与 `--apply` 共用同一段解析/映射（`_collect_for`），保证「预测的就是要写的」。
- 文档/口径：docstring 更新（12/8/13/5 列实测、写库三段式、真库迁移前置）；`product.pack` 取首个包装描述（`+N` 标注多包装）、
  `route` 取 BDPM 给药途径、`approval_id`=CIS、`category`=授权程序、note 记录 AMM/EU 号/MAH/平行进口/顺势/包装数。

> 本工位写权限不含 `db/`，因此 **`db/schema.sql` / `db/init_db.py` 未改**；副本迁移脚本只是演练，
> 真库窗口仍要按仓库纪律在 `db/` 做正式迁移（见 §5）。

---

## 2. 副本全链路（命令按执行顺序）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/markets/fr.py --prepare-copy --force                       # 真库 → .tmp/fr-ingest/drugs_fr_copy.db
& $py .tmp/migrate_fr_copy.py                                        # 副本演练 schema：product.country 加 'FR'
& $py etl/markets/fr.py --dry-run                                    # 预测（写前基线口径）
& $py etl/markets/fr.py --apply   --db .tmp/fr-ingest/drugs_fr_copy.db --manifest .tmp/fr-ingest/fr_manifest.json
& $py etl/markets/fr.py --apply   --db .tmp/fr-ingest/drugs_fr_copy.db --manifest .tmp/fr-ingest/fr_manifest_run2.json   # 幂等复跑
& $py etl/markets/fr.py --self-check                                 # manifest 检查启用后全通过
& $py etl/markets/fr.py --rollback --db .tmp/fr-ingest/drugs_fr_copy.db --manifest .tmp/fr-ingest/fr_manifest.json
```

副本迁移（`.tmp/migrate_fr_copy.py`）：`product` 表重建（CHECK 加 `'FR'`，`legacy_alter_table=ON` 防视图改名报错），
行数 479,193 不变、FK 空、integrity ok；迁移前自动备份 `drugs_fr_copy.db.pre-migrate`。

---

## 3. 计数核对（副本实测，与 dry-run 预测逐项一致）

| 表 | 写前（基线） | apply 后 | 增量 | 预测 |
|---|---:|---:|---:|---:|
| `product` | 479,193 | 494,992 | **+15,799** | 15,799 |
| `product`（FR） | 0 | 15,799 | +15,799 | 15,799 |
| `product_component` | 630,151 | 649,322 | **+19,171** | 19,171 |
| `product_name` | 655,004 | 670,803 | +15,799 | 15,799 |
| `name_key` | 202,739 | 214,397 | **+11,658** | 11,658 |
| `name_variant` | 231,105 | 246,650 | **+15,545** | 15,545 |
| `source` | 41 | 42 | +1（`bdpm_fr`） | 1 行 |
| `ingest_run` | 19 | 20 | +1 | 1 行 |
| `substance` | 12,637 | 12,637 | **0** | 0 |

- apply 第二次（幂等复跑）：`counts_before == counts_after`（494,992 / 649,322 / 670,803 / 214,397 / 246,650 / 42 / 20），
  旧 FR 行删除 15,799 后重写；**name_key / name_variant 新增 0**（manifest_run2.written 为 0）。
- 写后完整性：`PRAGMA foreign_key_check` 空、`integrity_check` ok、无孤儿 `product_component` / `product_name`。
- apply 耗时 6.3–6.7 s；manifest 大小 2.83 MB（含 15,799 product_ids + 11,658 keys + 15,545 pairs）。

---

## 4. 回滚与护栏验证

### 4.1 rollback 结果（按 run1 manifest，即原始基线）

```
removed: product 15,799 · name_variant 15,545 · name_key 11,658 · source 1 · ingest_run 1
counts_after: product 479,193 · product_fr 0 · component 630,151 · product_name 655,004
              name_key 202,739 · name_variant 231,105 · source 41 · ingest_run 19
diff_vs_counts_before: 全 0 → 「逐表差异 0（已回到写前基线）」
```

回滚后复核：FK 空、integrity ok、`source bdpm_fr` 0、`ingest_run bdpm_fr` 0、`substance` 12,637 不变。
**注意**：回滚后库文件 sha256 与 apply 前不同（`bc46547e…` vs `010f5113…`），但文件反而变大（428 MB → 582 MB）——
这是 SQLite 删除后**空闲页不归还**的预期行为；回滚验收以**逐表计数 + FK + integrity** 为准，不以文件 sha 为准
（如需缩体积可 `VACUUM`，不在本任务范围）。

### 4.2 幂等

第二次 apply 前后计数完全相同；name_key/name_variant 新增 0；`source_existed=True`、旧 FR 行删除 15,799。
（run1 manifest 的 `source_existed=False`，rollback 时因此删除了 source 行。）

### 4.3 护栏实测

| 场景 | 结果 |
|---|---|
| `--apply --db data/drugs.db`（无 `--allow-real`） | **拒绝**，提示「DB 窗口未开（排下一会话）」；真库 sha256 前后均 `d6e4d088…`（未写） |
| `--apply --db .tmp/fr-ingest/drugs_fr_copy.db.pre-migrate`（未迁移 schema） | **拒绝**，提示先做 `product.country` 加 FR 的 schema 迁移 |
| 副本（已迁移）`--apply` | 成功；`--rollback` 成功后逐表差异 0 |
| `--self-check` | 全部通过（0 失败），含 manifest/护栏/预测一致性检查 |

---

## 5. 仍需 Lead 拍板 / 下一会话的 DB 窗口

1. **schema 迁移（前置，必须在真库写之前）**：`db/schema.sql` 的 `product.country` CHECK 加 `'FR'`，
   并在 `db/init_db.py` 加幂等重建路径（product 表重建 = 删表/改名：**索引要重建、视图要复核**
   （`collision` / `coverage`）、`foreign_key_check` + `integrity_check` 必须空/ok）。
   本次副本演练脚本 `.tmp/migrate_fr_copy.py` 可作参考实现（含 `legacy_alter_table=ON` 的坑）。
2. **真库备份**：`Copy-Item data/drugs.db data/backups/drugs-pre-fr-<YYYYMMDD>.db`，记录 sha256 + 逐表计数（口径同 §3）。
3. **真库 apply**：`--apply --allow-real --db data/drugs.db --manifest .tmp/fr-ingest/fr_manifest_real.json`；
   然后 `db/check_data.py`、`coverage` 视图应多 FR 行、`SELECT COUNT(*) FROM product WHERE country='FR'` = 15,799。
4. **回滚预案**：manifest 保留；失败则 `--rollback --allow-real` 或从备份恢复。
5. **站点/注册表**：`data/markets.json` FR + `data/languages.json` fr 仍 `enabled:false`（本任务未改），
   ETL 入库后按 `reports/2026-11-12-fr-bdpm-acquisition.md` §7 的顺序改注册表 → 建站 → 首屏/体积回归。
6. **决策点**：全量 15,799（含顺势 1,477 / 平行进口 255 / 无成分 1,938）是否照单全收；schema 是否顺便加 price 列（BDPM 有价格/报销列，目前不入库）。

---

## 6. 复现与可复核

```powershell
& $py etl/markets/fr.py --self-check        # 0 失败（含 manifest/护栏检查）
& $py etl/markets/fr.py --dry-run           # 预测 = .tmp/fr-ingest/fr_dry_run.json
& $py db/q.py "SELECT COUNT(*) FROM product WHERE country='FR'"   # 真库仍 0
Get-FileHash data/drugs.db -Algorithm SHA256                       # d6e4d088…（未写）
```
副本与 manifest：`.tmp/fr-ingest/drugs_fr_copy.db`（回滚后基线）、`drugs_fr_copy.db.pre-migrate`（迁移前备份）、
`fr_manifest.json`（run1，可回滚到原始基线）、`fr_manifest_run2.json`（幂等复跑证据）、`fr_dry_run.json`。

_本报告为代码 + 副本验证产物；真实库、站点与注册表均未改动，未 commit / publish。_
