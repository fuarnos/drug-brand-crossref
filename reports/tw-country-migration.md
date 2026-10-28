# TW 市场 schema 迁移（country CHECK 加 TW，task-62）

> 日期：2026-10-28 ｜ 真实库：`data/drugs.db`（**只读**，本轮未写入）｜ 未跑 git / 发布 / `site/build.py`
> 产出：`db/schema.sql`（country CHECK 加 TW）、`db/init_db.py`（修迁移 bug + 自校验）、`db/migrate_country_tw.py`（独立 dry-run/apply/rollback）、本报告；副本验证证据在 `.tmp/tw-schema/`。
> 目标：解除 `product.country` CHECK 无 TW 的阻塞，为台湾市场数据接入做准备。

---

## 1. 结论

1. **schema 已加 TW**：`product.country CHECK` = US/GB/CN/ES/MX/AU/CA/**TW**；注释写明「新增市场 = 加 ISO 代码 + `data/markets.json` 注册」，未来 HK/MO 同理。
2. **`db/init_db.py` 的自动迁移可用，但原来有个索引丢失 bug，已修**：
   - 旧流程 `RENAME product→product_old` 后，`CREATE INDEX IF NOT EXISTS idx_product_country` 因**旧表还占着索引名**被静默跳过；随后 `DROP TABLE product_old` 把索引带走 → 新表**没有** `idx_product_country`（build 的 country 查询会退化）。
   - 新流程：用 `schema.sql` 的 product DDL 建新表 → 搬数据 → 删旧表 → **显式重建 product 索引**；并新增迁移后校验（行数/索引集合/视图可查/FK/quick_check）。
3. **新增 `db/migrate_country_tw.py`**：默认 dry-run；`--apply` / `--rollback` / `--manifest` / `--backup-dir` / `--vacuum`；**默认拒绝写 `data/drugs.db`**（须 `--allow-real`，本任务未用）。
4. **副本实测（真实库 409,587 行）**：
   - init_db 自动迁移 7→8：重建 **8.8s**（总 9.0s）；幂等重跑 **0.03s**；
   - migrate.py apply：重建 **2.2–2.8s**，+VACUUM 回收 4.5s，脚本墙钟合计约 **20s**；幂等第二次 **0s**；
   - rollback：**2.1–2.3s**，+VACUUM 5.0s；
   - **行数 409,587 不变、product_id 内容 hash 不变、`idx_product_country` 保留、3 个视图可查、`foreign_key_check` 0、`quick_check` ok**；TW 枚举生效；TW 行数为 0 时 rollback 通过。
   - 磁盘：325.4 MB → 迁移后 453.2 MB（旧表页未回收）→ `--vacuum` 后 325.3 MB；备份复制 0.1s。
5. **真实库未写**（mtime/大小/行数/枚举均与任务开始时一致）；迁移由 Lead 按 §5 执行。

---

## 2. 现状基线（真实库，只读）

| 项 | 值 |
|---|---|
| product 行数 | **409,587** |
| country 分布 | CN 146,347 · US 110,179 · GB 61,051 · CA 43,847 · ES 25,395 · AU 11,890 · MX 10,878 |
| product 索引 | `sqlite_autoindex_product_1`（PK）+ `idx_product_country (country, status)` |
| 引用 product 的子表（FK） | `product_component.product_id`、`product_name.product_id`、`corroboration.product_id` |
| 视图 | `alias_all`（1,119 行）、`collision`（127,098 行）、`coverage`（7 行=7 市场） |
| `PRAGMA foreign_key_check` | 0 违规 |
| `PRAGMA quick_check` | ok |
| DB 大小 | 325.4 MB |

---

## 3. 改动

### 3.1 `db/schema.sql`
- `country TEXT NOT NULL CHECK (country IN ('US','GB','CN','ES','MX','AU','CA','TW'))`
- 注释：新增市场 = CHECK 加代码 + `data/markets.json` 注册（enabled 先 false）；老库由 `db/init_db.py` / `db/migrate_country_tw.py` 幂等重建；未来 HK/MO 同理。
- 头部市场列表补 TW（台湾，预留）。

### 3.2 `db/init_db.py`
- 新增 `product_ddl()` / `product_index_ddls()`：从 schema.sql 提取 product 建表与 product 索引 DDL。
- 新增 `_rebuild_product()`：原子重建（`BEGIN IMMEDIATE` → RENAME → 新 DDL → `INSERT INTO product(公共列) SELECT …` → DROP 旧表 → **显式重建 product 索引**）；`try/finally` 恢复 `legacy_alter_table=OFF`、`foreign_keys=ON`。
- 新增 `snapshot()` / `verify_migration()`：迁移后校验 product 行数、索引集合、视图可查、`foreign_key_check`、`quick_check`，失败即 `SystemExit`（不静默）。
- `build()` 打印重建耗时；原有 `_ensure_variant_columns` / `_ensure_source_columns` / `_ensure_indexes` 行为不变。

### 3.3 `db/migrate_country_tw.py`（新）
```text
python db/migrate_country_tw.py --db <副本>                      # dry-run（默认）：枚举/行数/索引/视图/FK/size + 计划
python db/migrate_country_tw.py --db <副本> --apply [--backup-dir DIR] [--vacuum] [--manifest PATH]
python db/migrate_country_tw.py --db <副本> --rollback --manifest PATH [--vacuum]
```
- 只重建 product 表：数据原样搬、保留 `idx_product_country`；外键与视图不动（`legacy_alter_table=ON`）。
- apply 生成撤销清单（含迁移前 country 枚举、行数、内容 hash、索引/视图、quick_check）；rollback 校验「无 TW 行 + hash 与迁移前一致 + 枚举回到旧集合」。
- 安全：`--apply/--rollback` 默认拒绝 `data/drugs.db`（需 `--allow-real`）；`BEGIN IMMEDIATE` 独占写锁；可选备份 + 可选 VACUUM。

---

## 4. 副本验证记录

副本：`.tmp/tw-schema/`（每次从 `data/drugs.db` 复制；真实库只读）。

| 场景 | 命令 | 结果 | 耗时 |
|---|---|---|---|
| init_db 自动迁移 7→8 | `db/init_db.py --db init-test.db` | 枚举 8、409,587 行、索引保留、3 视图可查、FK 0、quick ok | 重建 **8.80s**（总 9.03s） |
| init_db 幂等重跑 | 同上第二次 | 无迁移、输出一致 | **0.03s**（墙钟 0.11s） |
| migrate dry-run | `--db migrate-test.db` | 正确列出 7 枚举/行数/分布/索引/视图/FK/目标 8 枚举/执行计划 | — |
| migrate apply | `--apply --backup-dir .tmp/tw-schema/backups` | 枚举 8；行数/hash/索引/视图/FK/quick 全一致；备份 325.4MB | 重建 **2.25s** |
| migrate 幂等第二次 | 同上 | 「已是目标枚举，无需迁移」 | ~0s |
| migrate rollback | `--rollback --manifest` | 枚举回 7；hash=迁移前；索引/视图/FK/quick 一致；TW 行 0 | 重建 **2.08s** |
| apply + vacuum | `--apply --vacuum`（副本3） | 重建 2.78s + VACUUM 4.46s；DB 325.4→453.2→**325.3 MB** | 脚本墙钟 **20.5s** |
| rollback + vacuum | `--rollback --vacuum` | 重建 2.34s + VACUUM 5.00s；hash/索引/视图/FK 一致 | 墙钟 **20.0s** |
| 备份 | `Copy-Item data/drugs.db …` | 325.4MB 备份 | 0.1s |

校验细节（apply 后）：`product_rows 409,587`；`product_id 内容 SHA-256` 与迁移前一致；`idx_product_country` SQL 一致；`alias_all/collision/coverage` 可查；`foreign_key_check` 0；`quick_check` ok；country 分布不变。

> 真实库未被改动（最终校验：mtime/大小/行数/7 市场/索引/视图/FK/quick 均与开始时一致）。

---

## 5. 真实库迁移步骤（Lead 执行；本轮不执行）

**顺序总原则：先注册 markets.json（已存在，enabled=false）→ schema 迁移 → 数据入库 → 启用 TW → 建站/发布。** 因为 ingest 需要 schema 先接受 `TW` 行，而站点只渲染 `enabled=true` 的市场。

1. **确认 markets.json**：`data/markets.json` 已有 TW 条目（`enabled:false`、`source_id:null`、`default_lang:zh-Hant`）——**本轮不改**；后续启用时再改 `enabled:true` 并跑 `tests/test_markets_registry.py`。
2. **备份**：`run_all.py` 会自动备份到 `data/backups/`；手动迁移则先 `Copy-Item data/drugs.db data/backups/drugs-<日期>.db`（约 325 MB → 预留 ≥ 2×325 MB 空闲；重建峰值约 +128 MB）。
3. **停写**：确保没有其它会话在跑 `site/build.py` / ingest / `run_all.py`（product 表重建期间 `BEGIN IMMEDIATE` 独占写锁）。
4. **执行迁移（二选一）**：
   - A. `& $py db/init_db.py`（按 schema.sql 自动识别 7→8 并重建，已修复索引丢失 bug，自带校验）；
   - B. `& $py db/migrate_country_tw.py --apply --backup-dir data/backups --vacuum`（显式迁移 + 撤销清单；真实库需 `--allow-real`）。
5. **验数**：`& $py db/check_data.py`；`PRAGMA quick_check`=ok、`foreign_key_check`=0；`country` 枚举含 TW、行数仍 409,587；`idx_product_country` 存在（见 §3.2）。
6. **启用 TW**：改 `data/markets.json` `enabled:true` + 指定 `source_id`（TFDA 数据源入库后），跑 `tests/test_markets_registry.py`。
7. **入库 TW 数据**（另任务）：ingest 脚本需处理 `country='TW'`；随后 `db/check_data.py`、README/About/coverage 数字同步（发布轮）。
8. **回滚预案**：保留迁移前备份；或 `db/migrate_country_tw.py --rollback --manifest <清单> --allow-real`（要求 TW 行数为 0，且内容 hash 与迁移前一致）。
9. 建站/发布属于后续任务（本任务禁止 `site/build.py`）。

---

## 6. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 重建期间锁库 | product 表约 2–9s 写锁；并行 build/ingest 会失败或阻塞 | 先停写；`BEGIN IMMEDIATE`；失败自动回滚（事务） |
| 中途崩溃/断电 | 事务未提交则回滚；已提交则需备份恢复 | 迁移前备份；脚本 try/except/finally 恢复 PRAGMA |
| 索引丢失（历史 bug） | build 按 country 查询退化（旧 `idx_product_country` 被跳过） | **已修复**并在 init_db 迁移后校验索引集合 |
| 磁盘峰值 | 重建时 DB 文件 ~1 份 product 表 + 备份：峰值约 780 MB 占用 | 预留 ≥ 2× 空间；`--vacuum` 回收（4–5s，325 MB） |
| WAL/并发读者 | 迁移时其他连接读到旧快照/被锁；迁移后旧连接需重开 | 停写并重启相关进程 |
| 视图/外键 | RENAME 可能改写子表 FK/视图定义 | `legacy_alter_table=ON`（不重写）+ 迁移后 FK/视图校验 |
| 真实库误写 | 本任务禁止写真实库 | 脚本默认拒绝 `data/drugs.db`，需 `--allow-real`；本轮未用 |
| 枚举扩展维护 | 每次加市场都要重建 product 表 | 已写进 schema 注释与 init_db docstring；HK/MO 同流程 |

---

## 7. 未来扩展（HK/MO/EU 等）

1. `db/schema.sql` 的 `country CHECK` 追加 ISO 代码（如 `'HK'`、`'MO'`）——**只加真正会生成产品国家页的 country**；EU 这类 region 用 `kind=region`，不直接进 product.country。
2. `data/markets.json` 注册（enabled 先 false、source_id 待定）。
3. 老库跑 `db/init_db.py`（或 `db/migrate_country_tw.py` 泛化版）自动重建，校验同上。
4. 数据源入库 → 启用 → 建站；更新 `docs/市场扩展接口.md` 清单（本报告 §5 可并入该文档）。

---

## 8. 证据文件（`.tmp/tw-schema/`）

| 文件 | 内容 |
|---|---|
| `probe.py` / `probe.out.txt` | 真实库基线（行数/分布/索引/视图/FK/size） |
| `init_db1.out.txt` / `init_db2.out.txt` | init_db 首次迁移 + 幂等重跑输出 |
| `migrate_dryrun.out.txt` | migrate dry-run 计划 |
| `migrate_apply.out.txt` / `migrate_apply2.out.txt` | apply（含备份）+ 幂等第二次 |
| `migrate_rollback.out.txt` / `migrate_apply_vacuum.out.txt` / `migrate_rollback_vacuum.out.txt` | rollback 与 vacuum 实测 |
| `country_tw_manifest*.json` / `migrate_manifest*.json` | 撤销清单（含迁移前枚举/hash/快照） |
| `backups/*.db` | 迁移前备份（325.4 MB × 2，可删） |
| `init-test.db` / `migrate-test*.db` | 副本（init-test 迁移后 453 MB 未 VACUUM；其余已回滚到 7 枚举） |
| `final_check.py` / 输出 | 收尾校验：真实库未变 + 各副本状态 |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Copy-Item data/drugs.db .tmp/tw-schema/demo.db -Force
& $py db/migrate_country_tw.py --db .tmp/tw-schema/demo.db                      # dry-run
& $py db/migrate_country_tw.py --db .tmp/tw-schema/demo.db --apply --vacuum --manifest .tmp/tw-schema/demo_manifest.json
& $py db/migrate_country_tw.py --db .tmp/tw-schema/demo.db --rollback --manifest .tmp/tw-schema/demo_manifest.json
& $py db/init_db.py --db .tmp/tw-schema/demo.db                                  # 也可用 init_db 自动迁移
```

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 git / 发布 / `site/build.py`。_
