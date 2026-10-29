# 数据源漂移基线（drift_check）— task-25

> 日期：2026-10-30（北京 05:0x）｜ 状态：**只读监控已就绪**：10/10 来源基线已生成、无漂移、模拟漂移自测 PASS
> 产物：`etl/drift_check.py`（新）、`data/sources/drift-baseline.json`（入仓库，**55,875 B**）、本报告；证据 `.tmp/drift/`（基线输出）、`.tmp/drift-test/`（自测）
> 边界：**不写 `data/drugs.db`、不改 schema、不改任何原始数据**；基线更新需 Lead 批准（`--force`）。task-26 溯源字段未动。

---

## 0. 结论

| 项 | 结果 |
|---|---|
| 覆盖来源 | **10 / 10**：us_ndc、gb_dmd、ca_dpd、au_artg（导出+索引）、es_cima、mx_cofepris、cn_nhsa、tw_tfda、sg_hsa、hk_dh |
| 监控粒度 | 每来源按 **part** 记录：行数 / 字段集合 / 关键枚举分布 / 数据截止日 / 文件 mtime / sha256 |
| 当前基线 | `data/sources/drift-baseline.json`（55,875 B，10 来源 29 个 part 有数据、0 个 SKIP） |
| 首次对比 | **0 告警 / 0 提示 / 0 SKIP**（基线即当前状态，符合预期） |
| 模拟漂移自测 | 构造「行数 +25% / 新增字段 / 枚举新值」→ 检出 **3 条告警（rows / field_added / enum_new）→ PASS** |
| 输出约定 | 有告警才写 `reports/drift-YYYYMMDD.md`；退出码 **1 = 有告警**、0 = 正常；不自动改数据 |
| 运行耗时 | 全量扫描 + sha256 **4.9s**（~1.4 GB 缓存，含 243 MB NDC JSON、227 MB dm+d XML、236 MB NHSA CSV） |

---

## 1. 各来源基线（2026-10-30 实测）

| source_id | 来源 | parts（行数） | 字段数 | 枚举监控 | 数据截止 | 最近抓取 | 文件数 |
|---|---|---|---:|---|---|---|---:|
| `us_ndc` | US openFDA NDC | `ndc_json` **138,032**（`"product_ndc"` 标记计数） | 3 | — | 2026-10-23 | 2026-10-25 12:12 | 3 |
| `gb_dmd` | GB NHSBSA dm+d | `amp` **167,533**、`ampp` **187,403**、`vmp` 24,684、`vmpp` 37,428、`vtm` 3,257 | 4–9 | — | — | 2026-10-25 19:22 | 5 |
| `ca_dpd` | CA Health Canada DPD | `drugproduct` 58,379、`status` 58,379、`activeingredient` **120,931**、`packaging` 58,379、`route` 67,170 | 7–9 | `class_name`、`status` | — | 2026-10-26 13:57 | 5 |
| `au_artg` | AU TGA ARTG（导出+索引） | `export_1991_2020` 21,333、`export_2021_2026` 15,764；`index_medicine` 34,594、`index_entries` 34,612、`index_details` 1,594 | 4–32 | `ARTG Category`、`Product Type`、`Therapeutic Type` | **2026-10-28** | 2026-10-28 18:31 | 5 |
| `es_cima` | ES AEMPS CIMA | `pages` **25,501**（129 页）、`atc_files` 1,808 | 25 | `cpresc` | — | 2026-10-25 20:17 | 129 |
| `mx_cofepris` | MX COFEPRIS | `alopaticos` 9,838、`prorrogas` 2,612、`status` 2,033、`profeco` **150,876**、`profeco_all` 1,007 | 5–11 | — | — | 2026-10-25 20:57 | 5 |
| `cn_nhsa` | CN 医保局 NHSA | `codes_20250404` **252,097**、`codes_20240105` 234,370 | 20 | `甲乙类` | — | 2026-10-25 20:14 | 2 |
| `tw_tfda` | TW TFDA | `tfda_36_csv` **72,096** | 28 | `註銷狀態`、`藥品類別` | — | 2026-10-28 09:46 | 1 |
| `sg_hsa` | SG HSA | `registered` **5,511**、`cpm_products` 11,977 | 7–13 | `Forensicclassification` | — | 2026-10-28 12:32 | 2 |
| `hk_dh` | HK 衞生署藥物辦公室 | `druglist` **14,275** | 4 | — | **2026-10-23** | 2026-10-28 12:10 | 1 |

与现库入库记录交叉核对（基线行数 = 当时 ingest `rows_in`）：NDC 138,032 ✓、dm+d AMP 167,533 ✓、CA DPD 58,379 ✓、CIMA 25,501 ✓、NHSA 234,370（2024-01-05）✓、TFDA 72,096 ✓、HSA 5,511 ✓、HK 14,275 ✓、ARTG 21,333+15,764 ✓。

**枚举基线抽样**（完整分布见基线 JSON，每枚举保留 top 20）：
- `au_artg.ARTG Category`（2021-26 导出）：Listed 8,071 / Registered 6,322 / **Listed (Export Only) 1,319** / provisional 49 / Assessed Listed 3
- `ca_dpd.status`：Cancelled Post Market 33,298 / Marketed 13,374 / Cancelled Pre Market 4,113 / Approved 3,706 / Dormant 2,439 …
- `es_cima.cpresc`：处方药 14,558 / 医院用药 4,169 / 诊断用 2,395 / OTC 1,625 …
- `tw_tfda.註銷狀態`：已註銷 45,705 / 空 26,230 / 已廢止 161
- `cn_nhsa.甲乙类`：空 90,483 / 乙 84,133 / 甲 77,481
- `sg_hsa.Forensicclassification`：Prescription Only 4,717 / General Sale List 486 / Pharmacy Only 308

---

## 2. 告警规则与阈值

| 规则 | 判定 | 说明 |
|---|---|---|
| 行数漂移 | 变化 > **±10%** | 基线 ≥20 行时按百分比；<20 行时按「绝对变化 ≥5 行」避免小来源噪声 |
| 字段增删 | 字段集合差集非空 | 新增/删除字段各一条告警（最多列 12 个） |
| 枚举新增 | 当前枚举值不在基线 top 20 内 | 每条 part/枚举一条，最多列 8 个新值 |
| 文件缺失 | 基线有、现在找不到 | 告警（缓存被清理/抓取失败） |
| part 缺失 | 基线有该 part、现在没有 | 告警 |
| 文件 sha256 变化 | — | **只记「提示」，不告警**（正常刷新） |
| 数据截止日变化 | — | 提示（`data_as_of` 能解析的来源：NDC/dm+d 元数据、ARTG validation、HK `lastUpdate`） |
| SKIP | `data/raw/` 下无匹配文件 | 记 SKIP 并计数，不告警（例如只读审计环境没抓缓存） |

> 设计原则：**漂移只提示、不自动动作**。脚本不写 DB、不重跑 ingest、不改基线；是否重跑入库由 Lead 决定。

---

## 3. 模拟漂移自测（PASS）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl\drift_check.py --self-test
# [self-test] 基线来源 10 个；模拟漂移：us_ndc.ndc_json 行数、gb_dmd.amp 新字段、ca_dpd.drugproduct.class_name 新枚举
# [self-test] 检出告警 3 条，类型 ['enum_new', 'field_added', 'rows'] → PASS
# [self-test] 输出：.tmp/drift-test/{drift-test-report.md,drift-test-alerts.json}
```

自测结果（`.tmp/drift-test/`，未触碰 `data/sources/drift-baseline.json`）：

| # | 来源.part | 类型 | 明细 |
|---:|---|---|---|
| 1 | `us_ndc.ndc_json` | rows | 138,032 → 172,541（+25.0%，阈值 ±10%） |
| 2 | `gb_dmd.amp` | field_added | 新增字段：`DRIFT_TEST_FIELD` |
| 3 | `ca_dpd.drugproduct` | enum_new | 枚举 `class_name` 新增值：`DRIFT_TEST_VALUE` |

---

## 4. 运行方式

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 首次生成基线（已存在会拒绝，避免误覆盖）
& $py etl\drift_check.py --write-baseline

# 日常检查：对比基线；有告警 → 写 reports/drift-YYYYMMDD.md；退出码 1
& $py etl\drift_check.py

# 只想看某几个来源 / 导出机器可读快照
& $py etl\drift_check.py --source us_ndc,au_artg --json-out .tmp\drift\snapshot.json

# 基线更新（**必须 Lead 批准**；数据源正常更新后执行）
& $py etl\drift_check.py --write-baseline --force
```

- **退出码**：0 = 无告警；1 = 有告警（便于夜间脚本/CI 判断）；2 = 用法/基线缺失等错误。
- **报告路径**：`reports/drift-YYYYMMDD.md`（仅告警时生成；`--always-report` 可强制）。
- **接入夜间收尾（待 Lead 批准，不在本任务写范围）**：建议在 `db/nightly_metrics.py` 末尾或谷段收尾脚本加一行
  `& $py etl\drift_check.py`，失败（退出码 1）则在夜报/手机看板提示；本次**未改**该文件。

---

## 5. 已知局限（如实记录）

| # | 局限 | 影响 / 处理 |
|---|---|---|
| 1 | US NDC 用 `"product_ndc"` **标记计数**（243 MB JSON 不整体解析） | rows 是记录数代理，与 ingest `rows_in` 对齐；若 FDA 改字段名会同时触发「行数骤降 + 字段变化」，属可解释告警 |
| 2 | dm+d 用 `<AMP>`/`<AMPP>` 等**标签计数**（regex） | 标签名稳定；字段集合取首条记录子标签 |
| 3 | TW 以 **CSV** 为计数口径（`tfda_36.json` 79 MB 只做哈希） | CSV/JSON 同源，行数一致；JSON 变更仍会通过 sha256 提示 |
| 4 | CIMA 只监控 **129 个索引页**（25,501 行）+ ATC 文件数（1,808） | ATC 明细内容变化不逐文件哈希，只比数量 |
| 5 | `data/raw/` 被清理时 → SKIP | 脚本记 SKIP 并计数，不误报告警；恢复缓存后自动回到对比 |
| 6 | 枚举只保 top 20 | 新增**长尾值**（不在 top 20）可能漏告警；top 20 之外的值若消失也不告警 |
| 7 | 抓取时间用文件 mtime | 复制/迁移会改变 mtime → 只影响「提示」，不告警 |

---

## 6. 不做的事（边界）

- **不写 `data/drugs.db`**、不改 `db/schema.sql`、不改 `db/init_db.py`；
- 不自动重跑 ingest、不自动改基线、不改 `data/raw/`；
- **task-26 溯源字段（source_url/retrieved_at/data_as_of 等 schema 变更）未动**，等 Lead 下一窗口批准；
- 未跑 build/publish（v0.9.2 已上线，本轮不涉及站点）。

---

## 7. 证据

| 文件 | 内容 |
|---|---|
| `etl/drift_check.py` | 监控脚本（10 来源配置、4 类 kind、对比、自测、报告渲染） |
| `data/sources/drift-baseline.json` | 基线（55,875 B，入仓库）：每来源 parts/rows/fields/enums/data_as_of/fetched_at，每文件 bytes/mtime/sha256 |
| `.tmp/drift/baseline_run.txt` | 基线生成输出（各来源 part 行数/字段/枚举数） |
| `.tmp/drift-test/drift-test-report.md` / `drift-test-alerts.json` | 模拟漂移自测输出（3 告警 PASS） |
| `reports/drift-YYYYMMDD.md` | 未来告警报告路径（本次无告警，未生成） |

_本报告为 task-25 只读监控交付：基线已生成、自测通过；未写库、未改 schema、未跑 build。_
