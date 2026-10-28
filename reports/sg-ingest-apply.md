# SG 真实库落库记录（task-113）

> 日期：2026-10-28 ｜ **真实库已写**（Lead 批准 GO；发布经理 v0.7.1 构建完成后执行）
> 写范围：`db/schema.sql`、`db/init_db.py`、本报告、`.tmp/sg-apply/`；未改 `site/build.py` / `data/markets.json`、未 git/发布、窗口期间未跑 build。
> 依据：`reports/sg-ingest-prep.md`（task-104 副本验证：5,511 产品 / 7,080 成分 / 映射 94.7% / 规格 90.1%）、`reports/sg-audit.md`（task-98，SODL 许可）。

---

## 0. 结果

| 指标 | before | after | 变化 |
|---|---:|---:|---:|
| products | 426,044 | **431,555** | **+5,511（SG）** |
| product_component | 527,166 | **534,246** | **+7,080** |
| substances | 12,649 | **12,649** | 不变（不硬造成分） |
| variants | 13,772 | **14,249** | +477（SG 盐型/base variant 补建） |
| product_name | 601,806 | **607,317** | +5,511 |
| name_key | 165,619 | **168,943** | +3,324 |
| coverage | 8 行 | **9 行**（+SG `(5511, 1672, 5511, 2026-10-28)`） | +1 |
| country 枚举 | 8（US…TW） | **10**（+HK、+SG） | schema 同步（HK 仍无数据） |
| region 列 | 无 | **有**（EU 层 schema 就绪，EU 行 0） | schema 迁移 |
| quick_check / FK | ok / 0 | **ok / 0** | 不变 |
| DB 文件 | 351,391,744 B | **364,195,840 B**（VACUUM 后） | 净 **+12,804,096 B（+12.2 MiB）** |

- SG 数据：5,511 产品（在册名册）、7,080 成分（全部有 variant FK）、1,672 个 variant 被引用、映射 **94.7%**（全成分匹配产品 95.4%）、规格 **90.1%** 组件有值；source `hsa_sg`（SODL v1.0，data_as_of=2026-08-07）已登记。
- `check_data` 通过；coverage 9 行（8 国 + SG；EU region 尚无数据，HK 枚举已加但无 HK 行）。
- **现有 8 国 coverage 数字逐值不变**（TW 16,457 / US 110,179 等）。

---

## 1. 执行步骤 / 耗时（真实库，本机实测）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 1) 备份（351,391,744 B）
Copy-Item data\drugs.db data\backups\drugs-before-sg-20261028-1334.db
# 2) schema 加 SG（db/schema.sql country CHECK：…TW, HK, SG）+ init_db 一次重建（8→10 枚举 + region）
& $py db\init_db.py
# 3) SG 写入
& $py etl\ingest_sg_hsa.py --apply --allow-real
# 4) 核对
& $py db\check_data.py
# 5) VACUUM 回收迁移重建产生的 freelist（+135 MB）
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');c.execute('VACUUM');c.close()"
```

| 步骤 | 结果/耗时 |
|---|---|
| 备份 | 351,391,744 B（`data/backups/drugs-before-sg-20261028-1334.db`） |
| `db/init_db.py` | **9.21s 墙钟**（product 重建 9.10s）：country 8→**10**（新增 HK, SG）+ region 列/country 可空；426,044 行、2 product 索引、3 视图可查、FK 0、quick ok；DB 486,920,192 B（freelist） |
| `etl/ingest_sg_hsa.py --apply --allow-real` | **1.76s**：写入 SG 产品 **5,511** / 成分 **7,080** / variants 1,672；映射 94.7%，全匹配 95.4% |
| `db/check_data.py` | 9.33s；products 431,555 / components 534,246 / substances 12,649 不变 / coverage 9 行 |
| VACUUM | **5.41s**；DB **486.9 MB → 364,195,840 B（364.2 MB）**，回收约 122.7 MB（净 +12.8 MB vs 原库） |

总机器耗时约 **16s**（不含备份/check_data），加核验约 25s。

---

## 2. 备份 / 回滚

| 项 | 路径 |
|---|---|
| 窗口前完整备份 | `data/backups/drugs-before-sg-20261028-1334.db`（351,391,744 B） |
| SG 写入撤销清单 | `.tmp/sg-ingest/apply_manifest.json`（146,828 B；含 product_ids / created_variants） |

回滚（二选一）：
1. **数据级（推荐，保留 schema）**：
   ```powershell
   & $py etl\ingest_sg_hsa.py --rollback --db data\drugs.db --allow-real
   # → SG 产品 0；products 431,555→426,044；source hsa_sg 行清除（脚本按 manifest/脚本内逻辑）
   ```
   副本已由 task-104 验证 23/23 PASS（幂等/回滚/重放）。
2. **整库恢复**：`Copy-Item data\backups\drugs-before-sg-20261028-1334.db data\drugs.db`（同时回退 schema：枚举回 8、region 列移除）。**schema 回退只能靠此备份**（init_db 无撤销清单）。
- 备份保留到 v0.7.1 线上 smoke + SG 启用窗口完成后再议。

---

## 3. 与 build/markets 的先后（未做）

- 本任务**未改** `data/markets.json`（SG 未注册）与 `site/build.py`；SG 页面/UI 需 build.py SG 支持任务。
- 当前状态：DB country set = 9（8 国 + SG；HK 枚举已加但无 HK 行）vs enabled markets 8 → `tests.test_markets_registry` 的 `test_enabled_markets_match_db_countries` **会红**（预期过渡态，与 TW/HK 启用窗口同处理：build 支持后注册 SG + 启用 + 更新测试断言）。
- 发布经理 v0.7.1 构建已完成、读取的是已构建 dist，不受本次 DB 写入影响；窗口期间未跑 build。

---

## 4. 已知事项 / 风险

| # | 事项 | 说明 |
|---|---|---|
| 1 | `ingest_run` 无 `hsa_sg` 行 | task-104 脚本未写 ingest_run（source 行已写）；不影响产品数据，后续补或由 run_all 统一记录 |
| 2 | HK 枚举已加但无 HK 数据 | 本次 init_db 按 schema 同时加 HK；HK 数据 apply 仍待 Lead 的 DB 窗口（task-107 runbook） |
| 3 | region 列已加、EU 行 0 | EMA 数据未落真实库（备选，Lead 已降级）；coverage 仍 9 行 |
| 4 | variants +477 | SG 成分盐型/base variant 补建（1,672 个被引用，其中部分复用已有 variant）；substance 不新增 |
| 5 | 测试过渡态 | DB country 9 vs markets enabled 8 → markets 测试红，需 build/启用窗口处理 |
| 6 | 数据口径 | SG 为「在冊名册 ≠ 在售」，页面必须明示；无包装；ATC 在 note；批准日期存原文 |
| 7 | 磁盘 | 备份 351 MB + 当前 364 MB；VACUUM 时临时空间约等于 DB 大小，已预留 |

---

## 5. 证据（`.tmp/sg-apply/`）

| 文件 | 内容 |
|---|---|
| `init.out.txt` | init_db 8→10 + region 迁移日志 |
| `ingest.out.txt` | SG apply 输出（5,511/7,080/94.7%/95.4%） |
| `check.py` / `check_data.out.txt` | 计数/coverage/quick/FK/source/ingest_run 核验 |
| `data/backups/drugs-before-sg-20261028-1334.db` | 窗口前备份 |
| `.tmp/sg-ingest/apply_manifest.json` | 撤销清单（product_ids/created_variants） |

---

_本报告由并行子智能体 data-depth 生成；已获 Lead 明确 GO；未改 build.py/markets、未 git/发布、窗口期间未跑 build。_
