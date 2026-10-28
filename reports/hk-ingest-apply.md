# HK 入库收尾：schema 加 HK + init_db 副本验证（task-93，阶段一）

> 日期：2026-10-28 ｜ 真实库：`data/drugs.db` **只读未写**（待 Lead 批准同一窗口 apply）
> 阶段一（本报告）：`db/schema.sql` 加 `HK` + `db/init_db.py` 文档同步 + **副本**验证（空库建库 / 老库 8→9 升级 / HK 写入 / 幂等 / 回滚）。
> 阶段二（待批准，不晚于 build.py HK 支持窗口）：真实库 apply + check_data + 可选 VACUUM + 线上验收。
> 依据：task-88 副本结果（`reports/hk-ingest-prep.md`：13,832 产品、成分映射 93.8%、DB +10.2 MB）。

---

## 0. 当前状态

| 项 | 状态 |
|---|---|
| `db/schema.sql` country CHECK 加 `HK` | ✅ 完成（`US, GB, CN, ES, MX, AU, CA, TW, **HK**`；头注释/注释同步） |
| `db/init_db.py` | ✅ 无需改逻辑（本就按 schema.sql 目标枚举自动重建迁移）；已更新 docstring（市场序列 + HK、`migrate_country_hk.py` 引用） |
| 空库建库验证 | ✅ 0.36s；product 枚举含 HK（9 值）、表/视图/索引齐全、0 行、quick ok |
| 老库升级验证（副本，426,044 行含 TW 数据） | ✅ 10.07s（重建 9.59s）：枚举 8→9；行数/内容 hash/索引/视图/FK/quick_check **不变**；幂等重跑 0.12s |
| HK 写入（init_db 升级后的副本） | ✅ 13,832 products / 21,881 components；products 426,044→**439,876**、components 527,166→**549,047**、substances 12,649 **不变**；check_data/quick/FK OK |
| 回滚验证 | ✅ 数据回滚（ingest `--rollback`）后与 pristine **delta 全 0**；整库回滚（恢复备份）后枚举回 8、行数/hash/大小回基线 |
| **真实库** | ⏸ **未写**：仍 426,044 products（TW 16,457）、枚举 8（无 HK）、无 `hk_dh` source/ingest_run、351.4 MB |
| 真实 apply 触发条件 | 等 Lead 批准，与 build.py HK 支持同一窗口（markets.json HK 注册/启用与 tests 断言的启用窗口属另一任务） |

---

## 1. 改动

### 1.1 `db/schema.sql`

```diff
-    country        TEXT NOT NULL CHECK (country IN ('US', 'GB', 'CN', 'ES', 'MX', 'AU', 'CA', 'TW')),
+    country        TEXT NOT NULL CHECK (country IN ('US', 'GB', 'CN', 'ES', 'MX', 'AU', 'CA', 'TW', 'HK')),
     -- 新增市场 = 往上面 CHECK 里加一个 ISO 代码 + data/markets.json 注册（enabled 先 false），
-    -- 老库由 db/init_db.py / db/migrate_country_tw.py 幂等重建 product 表；未来 HK/MO 同理。
+    -- 老库由 db/init_db.py / db/migrate_country_tw.py / db/migrate_country_hk.py 幂等重建
+    -- product 表；未来 MO 同理。
```

- 头注释市场列表加：`HK（香港衞生署藥物辦公室 DrugList，名称/成分层，无规格/剂型/状态）`。

### 1.2 `db/init_db.py`
- 仅 docstring 更新（迁移逻辑不变，本来就从 schema.sql 读取目标枚举、自动重建）：
  - 市场序列 `… → TW → HK`；
  - 说明 `migrate_country_hk.py` 同逻辑可回滚版本；init_db 路径无撤销清单，回滚走 DB 备份恢复。

### 1.3 说明：为什么必须改 schema.sql
task-88 用 `db/migrate_country_hk.py` 在副本上加了 HK 枚举，但 `db/schema.sql` 仍是 8 值。若真实库先加 HK 数据、之后任何会话再跑 `db/init_db.py`，init_db 会发现「DB 枚举(9) ≠ schema 目标(8)」→ 重建 product 为 8 值枚举 → 存在 HK 行时 INSERT 会失败（或回退 8 枚举）。**现在 schema.sql 已同步为 9 值，init_db 与 HK 数据可以共存**。

---

## 2. 副本验证（阶段一）

副本目录：`.tmp/hk-apply/`；真实库只读复制（`.tmp/hk-apply/drugs-hk.pristine.db` 为 pristine 基线 426,044 行 / 351.4 MB / 枚举 8）。

### 2.1 空库建库

```text
& $py db/init_db.py --db .tmp/hk-apply/empty.db     # 0.36s
enum: 'US', 'GB', 'CN', 'ES', 'MX', 'AU', 'CA', 'TW', 'HK'
表 17 个 / 视图 3 个 / idx_product_country / products=0 / quick_check ok / size 233 KB
```

### 2.2 老库升级（8→9，含 TW 数据）

```text
& $py db/init_db.py --db .tmp/hk-apply/drugs-hk.db  # 10.07s（重建 product 9.59s）
迁移 product 表：country 8 值 → 9 值（新增 HK）
迁移校验 OK：426,044 行、1 个 product 索引、3 个视图可查、foreign_key_check 0、quick_check ok
```

| 指标 | pristine（8 枚举） | upgrade 后（9 枚举） | 变化 |
|---|---:|---:|---|
| products / components | 426,044 / 527,166 | 426,044 / 527,166 | 不变 |
| product_id 内容 hash | `4bdd19e4edb426c3` | `4bdd19e4edb426c3` | 不变 |
| name_keys / names / name_variants | 165,619 / 601,806 / 179,306 | 同 | 不变 |
| product 索引 / 视图 | idx_product_country / 3 视图 | 同 | 不变 |
| quick / FK | ok / 0 | ok / 0 | 不变 |
| DB 文件 | 351.4 MB | 486.5 MB（旧表页未回收） | +135 MB（VACUUM 可回收） |

**幂等重跑**：第二次 `init_db` 0.12s，无迁移输出。

### 2.3 HK 写入（init_db 升级后的副本，验证真实 apply 路径）

```text
& $py etl/ingest_hk_druglist.py --apply --db .tmp/hk-apply/drugs-hk.db \
    --manifest .tmp/hk-apply/hk_write_manifest.json
→ products 13,832 / components 21,881 / created_name_keys 9,596 / created_name_variants 13,461
   写事务 2.48s（wall 3.79s）；components_no_variant 472
```

**check_data（副本）**：

```text
coverage 9 行（含 HK 13,832 / active 0（status=unknown）/ 2026-10-28）
products 439,876 | components 549,047 | substances 12,649（不变）| variants 13,772（不变）
name_keys 175,215 | names 615,638
collisions(severe) 20,170 / warning 859（HK 名称归一后增加，启用窗口评估）
quick_check ok；foreign_key_check 0
```

**幂等重跑**：第二次 apply 计数不变（`removed_old_products=13,832`、`created_name_keys=0`），2.65s。

### 2.4 回滚验证

| 层 | 命令 | 结果 |
|---|---|---|
| 数据回滚（只删 HK） | `etl/ingest_hk_druglist.py --rollback .tmp/hk-apply/hk_write_manifest.json --db ...` | 1.69s；删 13,832 products / 9,596 keys / 13,461 variants；与 pristine **delta 全 0**（products/components/name_keys/name_variants/names/substances/variants/hk/ingest_runs/FK）；枚举保持 9 |
| 整库回滚（init_db 路径推荐） | `Copy-Item .tmp/hk-apply/drugs-hk.pristine.db .tmp/hk-apply/drugs-hk.db`（真实库对应 `data/backups/…` 备份） | 枚举回 **8**（'US','GB','CN','ES','MX','AU','CA','TW'）；products 426,044 / TW 16,457 / HK 0；quick ok / FK 0 / size 351.4 MB |

> `db/init_db.py` 路径**没有撤销清单**；真实库若要精确回滚枚举，两种选择：
> ① 恢复 apply 前备份（最简单，推荐；真实 apply 前必须备份）；
> ② 用 `db/migrate_country_hk.py` 做真实迁移（有 manifest，可 `--rollback`），但注意它把 `HK` 加进**当前 DB DDL**，与 schema.sql 现在一致，二者等价。

---

## 3. 真实库 apply 步骤（待 Lead 批准；本阶段未执行）

> 前置：Lead 批准 + 与 build.py HK 支持同一窗口；确认没有其它会话并行写库；`markets.json` **不改**（HK 注册/启用属另一任务）。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$ts  = Get-Date -Format yyyyMMdd-HHmm

# 1) 备份（必须；回滚依赖它）
Copy-Item data\drugs.db "data\backups\drugs-before-hk-schema-$ts.db"

# 2) schema 迁移（8→9；约 10s；包含 product 表重建）
& $py db\init_db.py
#   或 & $py db\migrate_country_hk.py --apply --allow-real --backup-dir data/backups --vacuum
#   （后者有撤销清单，可 --rollback；两者结果一致）

# 3) HK 写库（约 2.5s 事务；自动登记 source=hk_dh + ingest_run）
& $py etl\ingest_hk_druglist.py --apply --allow-real --db data\drugs.db `
    --manifest .tmp\hk-ingest\hk_write_manifest.json

# 4) 验数
& $py db\check_data.py
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');print(c.execute('pragma quick_check').fetchone()[0])"
#   期望：products 426,044→439,876；components 527,166→549,047；
#        substances 12,649 不变；coverage 9 行（HK 13,832 / active 0）；
#        DB 486.5MB（未 VACUUM）

# 5)（可选）VACUUM 回收旧表页：486.5MB → ~362MB（约 6s）
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');c.execute('VACUUM');c.close()"
```

**回滚（任一）**：

```powershell
# A. 只删 HK 数据（保留 schema 9 枚举）
& $py etl\ingest_hk_druglist.py --rollback .tmp\hk-ingest\hk_write_manifest.json --allow-real --db data\drugs.db
# B. 整库恢复备份（schema 也回 8 枚举）
Copy-Item "data\backups\drugs-before-hk-schema-$ts.db" data\drugs.db
```

- 真实 apply 后 **不要** 立刻启用 `data/markets.json` 的 HK：build.py 尚未支持 HK 国家列/选择器/i18n（另任务）；HK 数据在 DB 中静默存在不影响现有 8 市场构建。
- 线上 smoke 通过前保留备份与撤销清单。

---

## 4. 风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | `init_db.py` 迁移期间 `BEGIN IMMEDIATE` 独占写锁（~10s） | 停 build/ingest 后再跑；失败自动回滚；先备份 |
| 2 | DB 文件 351.4→486.5 MB（旧表页），VACUUM 前磁盘占用高 | 预留 ≥2× 空间；apply 后可选 VACUUM（~6s → ~362 MB） |
| 3 | init_db 路径无撤销清单 | **apply 前备份**（步骤 1）；或改用 `migrate_country_hk.py`（带 manifest） |
| 4 | schema.sql 与真实库不一致窗口（本次已修：schema 已含 HK） | 本任务后二者一致；后续任何 schema 变更需同步真实库迁移 |
| 5 | HK 无规格/剂型/状态（源限制），coverage active=0 | 见 task-88 报告 §6 页面口径；启用窗口由 build 任务处理文案 |
| 6 | markets.json HK 未注册/未启用，构建不会出现 HK | 属后续「build.py HK 支持 + 启用窗口」任务，与 DB apply 解耦 |
| 7 | 与 TW 启用窗口（task-87）并行写 markets/languages 冲突 | 本任务不改 markets/languages；由 Lead 排期串行 |

---

## 5. 证据（`.tmp/hk-apply/`）

| 文件 | 内容 |
|---|---|
| `empty.db` / `empty_init.out.txt` | 空库建库产物与日志（9 枚举） |
| `drugs-hk.pristine.db` | 升级前真实库副本（8 枚举 / 426,044 行 / 351.4 MB） |
| `drugs-hk.db` | 升级 + HK 写入 + 回滚演练用副本（当前已恢复为 pristine 状态） |
| `upgrade_init.out.txt` / `upgrade_init2.out.txt` | 老库 8→9 升级 + 幂等重跑日志 |
| `write.out.txt` / `write_idem.out.txt` | HK 写库 / 幂等日志 |
| `hk_write_manifest.json` | HK 写库撤销清单（product_ids / created keys / variants） |
| `rollback.out.txt` | 数据回滚日志 |
| `check_data.out.txt` | check_data（副本 HK 写入后）+ 恢复备份验证（枚举 8） |
| `verify.py` / `check_and_restore.py` | 计数/hash/完整性对比脚本 |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Copy-Item data\drugs.db .tmp\hk-apply\pristine.db -Force
& $py db\init_db.py --db .tmp\hk-apply\drugs-hk.db         # 8→9
& $py etl\ingest_hk_druglist.py --apply --db .tmp\hk-apply\drugs-hk.db --manifest .tmp\hk-apply\hk_write_manifest.json
& $py .tmp\hk-apply\check_and_restore.py                    # check_data + 恢复验证
```

---

_本报告由并行子智能体 data-depth 生成；阶段一未写 `data/drugs.db`、未改 `site/build.py` / `data/markets.json`、未跑 git/发布。阶段二（真实 apply）待 Lead 批准后执行并追加结果。_
