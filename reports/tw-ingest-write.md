# TW 入库 `--write-db` 实现（副本验证）— task-76

> 日期：2026-10-28 ｜ 真实库：`data/drugs.db` **只读未写** ｜ 未跑 `site/build.py` / git / 发布
> 目标：解除 TW 入库最大阻塞——在 `etl/ingest_tw_tfda.py` 实现 `--write-db`（product / component / name / ingest_run），并在 DB **副本**上跑通「schema 加 TW → 写全量 → 统计 → check_data/quick_check → 幂等 → 回滚」。
> 产物：`etl/ingest_tw_tfda.py`（写库实现）、`data/tw_ingest_dryrun.csv`（按新映射/新 product_id 重生成）、`.tmp/tw-write/`（证据）、本报告。

---

## 1. 结论

| 项 | 结果 |
|---|---|
| `--write-db` 实现 | ✅ 全量 CSV → `product`/`product_component`/`name_key`/`name_variant`/`product_name`/`ingest_run`；默认 dry-run，`--apply` 才提交；默认**拒绝写 `data/drugs.db`**（`--allow-real` 才允许） |
| 全量 dry-run（写入前的计划） | 72,096 行 → 产品类候选 21,312 → **17,892 张证**；成分 token 覆盖 **87.8%**（34,273/39,045；别名表贡献 1,675），未匹配 distinct 714，suggested 43，复方 5,048 |
| **副本写入结果** | **16,457 个 TW 产品**（= 17,892 行的 92.0%）、**28,721 条 product_component**、**32,899 条 product_name**、新增 30,368 个 name_key / 32,762 条 name_variant；substance/variant **不新增**（不硬造成分） |
| 被丢弃产品 | **1,435 个**（8.0%）：无任何可挂接成分（714 个未匹配 token + 43 个 suggested 不在库 + 442 条匹配到 substance 但无 variant）；明细见 §3 |
| 副本完整性 | quick_check **ok**、foreign_key_check **0**、8 个市场 coverage；TW coverage = (16,457 产品, 2,010 variants, 16,457 active, 2026-10-28) |
| DB 体积（副本） | 基线 325,398,528 B → 写库后（含 schema 重建页）453,234,688 B → **VACUUM 后 351,391,744 B（+25,993,216 B = +24.8 MiB / +26.0 MB）** |
| 耗时（副本，本机） | schema 迁移 **8.7s**；全量写库 **11.7s 墙钟 / 6.6s 写事务**；幂等重跑 **11.5s**；VACUUM **5.5s**；回滚 **3.1s** |
| 幂等 | ✅ 第二次 `--apply`：产品/组件/名称数不变（`removed_old_products=16,457`，`created_name_keys=0`） |
| 回滚 | ✅ `--rollback` 后与真实库逐项 **delta 全 0**（products/components/name_keys/name_variants/names/substances/variants/TW/ingest_runs/quick_check/FK） |
| 真实库 | ✅ 未写：大小 325,398,528 B、mtime 与任务开始一致、TW 产品 0；`source.tfda_tw` 行（Lead 已按 task-71 登记）在位 |

**一句话**：`--write-db` 已可用并在副本上全流程通过（幂等 + 精确回滚 + 完整性 OK）；真实库执行一条命令即可入库 16,457 个 TW 产品（+28.7k 组件、+26 MB），**但需先决定 1,435 个无成分产品是否接受丢弃**（见 §6 风险）。

---

## 2. 实现说明（`etl/ingest_tw_tfda.py`）

### 2.1 写库 CLI

```text
python etl/ingest_tw_tfda.py                       # dry-run 样本（2000 候选，不写 DB）
python etl/ingest_tw_tfda.py --limit 0 --out ...   # 全量 dry-run（不写 DB）
python etl/ingest_tw_tfda.py --write-db --limit 0 --db <副本> --apply [--manifest PATH]
python etl/ingest_tw_tfda.py --rollback <manifest> --db <副本>
python etl/ingest_tw_tfda.py --write-db --limit 0 --apply --allow-real   # 真实库（Lead 用）
```

- `--write-db`：建计划 + 生成 full dry-run CSV/统计；**不提交**；`--apply` 才在**单事务**内写入。
- `--db`（默认 `data/drugs.db`）、`--manifest`（默认 `<work-dir>/tw_write_manifest.json`）、`--work-dir`、`--allow-real`。
- **真实库守卫**：目标解析为 `data/drugs.db` 且无 `--allow-real` → 直接拒绝。
- 前置校验：`product.country` CHECK 必须含 `TW`；`source` 行必须存在（缺失则自动补，建议用 `db/source_tfda_tw.sql`）。

### 2.2 字段映射

| TFDA | DB | 处理 |
|---|---|---|
| 許可證字號 | `product.approval_id` / `product_id` | product_id = `TW-TFDA-<slug>-<md5(approval_id)[:8]>`（见 §5 bug 修复） |
| 中文品名 / 英文品名 | name_key + name_variant + product_name(trade) | 中文 primary=1（zh-Hant raw 原文进 name_variant，norm 走项目 `normalize_name` 繁→简）；英文 primary=0 |
| 主成分略述 | product_component | 英文 token → DB substance/variant；再查 `data/tw_ingredient_aliases.csv`（mapped 用 substance_id+salt；suggested 只计 `new_substance_candidate` 不建成分；unresolved 丢弃计数） |
| 劑型 | dosage_form + form_base + release | 205 种原始剂型 → 9 个 base（unknown 仅 7 行） |
| 申請商名稱 / 包裝 | mah / pack | 原样（pack 截 120 字） |
| 藥品類別 / 製造商 / 製造國 / 效期 | category / note | 事实字段进 note（不存適應症/用法用量） |
| （无结构化规格） | product_component.strength_* | 仅品名单成分 + medium 才挂（7,786 行）；复方/低置信留空（页面显示「未载」） |
| 状态 | active/discontinued | 只写 active（注销/过期的行按 dry-run 口径已过滤） |
| 来源 | source_id='tfda_tw'、source_url、retrieved_at | 另写 `ingest_run`（rows_in 72,096 / kept 17,892 / rejected 54,204 / status ok） |

### 2.3 幂等 / 回滚

- 幂等键：`source_id='tfda_tw'`（每次 apply 先 `DELETE FROM product WHERE source_id='tfda_tw'`，FK 级联清 component/name/corroboration，再重建；approval_id 唯一）。
- 撤销清单记录：`product_ids`、`created_name_keys`、`created_name_variants`、`run_id`、统计；重跑时**合并保留**首次创建的 keys/variants（第二次 `created_name_keys=0` 不会丢回滚信息）。
- rollback：删本 source 产品 + ingest_run + 本次创建且无引用的 name_key/name_variant（**只删自己创建的**，不误删其它来源共用键）。

---

## 3. 副本结果明细

### 3.1 数量

| 指标 | 真实库（基线） | 副本写库后 | 变化 |
|---|---:|---:|---:|
| products | 409,587 | **426,044** | **+16,457** |
| product_component | 498,445 | **527,166** | **+28,721** |
| name_key | 135,251 | **165,619** | +30,368 |
| name_variant | 146,544 | **179,306** | +32,762 |
| product_name | 568,907 | **601,806** | +32,899 |
| substance / variant | 12,649 / 13,772 | 12,649 / 13,772 | 不变（不硬造成分） |
| countries（coverage） | 7 | **8（TW）** | +1 |
| quick_check / FK 违规 | ok / 0 | ok / 0 | 不变 |

TW coverage：`('TW', 16457, 2010, 16457, '2026-10-28')`（产品/使用 variant 数/active/日期）。

### 3.2 成分映射（写入前 dry-run 全量）

| 指标 | 数值 |
|---|---:|
| 成分 token 总数 | 39,045 |
| 直接映射 DB / 经别名表 | 32,598 / **1,675**（合计 34,273 = **87.8%**；骨架版 83.5%，别名表 +4.3pp） |
| 全匹配行 / 有未匹配行 | 15,169 / 2,723 |
| 未匹配 distinct token | 714（top 为 TW 老药：DL-METHYLEPHEDRINE HCL、GUAIACOL GLYCERYL ETHER、ETHENZAMIDE、POTASSIUM GUAIACOLSULFONATE、NOSCAPINE…） |
| suggested_new_substance_candidate（不建） | 43 distinct（如 ETHENZAMIDE、OXETHAZAINE、MEPHENOXALONE） |
| 复方行 | 5,048（28.2%） |
| 规格置信度 | medium 8,541 / none 9,316 / low 35 |

### 3.3 写入结果 / 丢弃原因

- 写好 **16,457** 个产品（17,892 的 92.0%）；**1,435 个丢弃**（8.0%）：
  - 1,222 行：所有成分都未匹配（单方老药为主；token 不在 DB/别名表，按口径不硬造）；
  - 约 213 行：匹配到 substance 但无可用 variant（最后剩 `components_no_variant=442` 条分量；这些产品若还有其它可挂成分则仍写入）。
- 组件总数 28,721：`components_no_variant=442`；`components_variant_fallback=2,597`（见 §5：DB 把盐型做成 orphan substance 时回退到 base substance 的同盐 variant）。
- 规格：`strength_rows_written=7,786`（单成分 medium）；medium 总量 8,541（其余是复方/多值被 decide_strength 标 none）。
- 名称：每个 TW 产品平均 ~2.0 个 product_name（中文 primary + 英文）；新 name_key 30,368 个。

### 3.4 耗时 / 体积（副本，本机 SSD）

| 步骤 | 结果 |
|---|---|
| 复制真实库 → 副本 | 325,398,528 B（~0.2s） |
| schema 迁移（`db/init_db.py --db 副本`） | 重建 product 7.5s / 总 **8.7s**；country 7→8；快速校验 OK |
| 全量写库（`--write-db --limit 0 --apply`，含 dry-run 构建） | 墙钟 **11.7s**；写事务 **6.6s**；DB 453,234,688 B（旧表页未回收） |
| 幂等第二次 apply | 墙钟 **11.5s**；写事务 6.35s；`removed_old_products=16,457`、`created_name_keys=0`；计数不变 |
| VACUUM | **5.5s**；DB **351,391,744 B**（净 +26.0 MB） |
| rollback | **3.1s**；`removed_products=16,457`、`removed_name_keys=30,368`、`removed_name_variants=32,762` |
| 回滚后 delta vs 真实库 | **0**（全指标，含 quick_check ok / FK 0） |

---

## 4. 真实库 apply 步骤（Lead 执行）

> 前置：schema 已加 TW（本任务未写真实库；需 Lead 先做 schema 迁移）；`source.tfda_tw` 已登记（task-71 已 apply）；确认无其它会话并行写库。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 备份（run_all 也会自动备份到 data/backups/，只留最近 5 份）
Copy-Item data\drugs.db data\backups\drugs-before-tw-ingest-$(Get-Date -Format yyyyMMdd-HHmm).db

# 2) schema 迁移（country CHECK 加 TW；约 8–9s，重建 product 表）
& $py db\init_db.py
#   或： & $py db\migrate_country_tw.py --apply --allow-real --backup-dir data/backups --vacuum

# 3) 确认 source 行（Lead 已 apply；缺失则执行）
& $py db\q.py "SELECT source_id,data_as_of FROM source WHERE source_id='tfda_tw'"

# 4) 全量写库（唯一会写 product 的命令；单事务；默认拒绝真实库 → --allow-real）
& $py etl\ingest_tw_tfda.py --write-db --limit 0 --apply --allow-real `
    --manifest .tmp\tw-ingest\tw_write_manifest.json

# 5) 校验
& $py db\check_data.py        # TW coverage 行出现；products 409,587→426,044、components→527,166
& $py db\q.py "PRAGMA quick_check"
& $py db\q.py "SELECT country, COUNT(*) FROM product GROUP BY country ORDER BY country"

# 6)（可选）回收旧表页：DB 453MB → ~351MB
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');c.execute('VACUUM');c.close()"
```

- 预期：**+16,457 products / +28,721 components / +32,899 names / +26 MB（VACUUM 后）**。
- 之后按 `reports/tw-ingest-runbook.md`：启用 `markets.json` TW + zh-Hant（**与 DB 含 TW 行同一窗口**，否则 `tests.test_markets_registry` 的「enabled 市场 = DB countries」断言失败）→ build/publish（另任务）。
- 回滚：`& $py etl\ingest_tw_tfda.py --rollback .tmp\tw-ingest\tw_write_manifest.json --allow-real`（副本实测 delta 全 0）；或恢复备份。
- 磁盘：备份 325MB + 重建峰值 ~+450MB + 写库后 ~453MB → 建议预留 **≥1.5GB** 空闲。

---

## 5. 实现中修掉的两个坑（值得记录）

1. **product_id 撞车（会导致静默丢产品）**：第一版 `TW-TFDA-<slug(證號)>` 在「衛署罕菌疫輸字第000001號」与「衛署罕藥製字第000001號」等不同證號類別間 slug 相同（中文类别被 slug 丢弃，只剩流水号）→ `INSERT OR REPLACE` 把不同产品覆盖：写 16,457、实际只剩 15,785（672 个丢失）。已改成 **始终附加 `md5(approval_id)[:8]`**（`TW-TFDA-000001-65739378`），保证 approval_id→product_id 双射；修复后副本 16,457 个 id 全唯一。
2. **回滚不干净（FK 级联未开）**：`sqlite3.connect` 默认 `foreign_keys=OFF`，`DELETE FROM product` 不级联 → 第一版 rollback 后 component/name 残留（components 527,166 不回落）。现在 write/rollback 连接均 `PRAGMA foreign_keys=ON`；并用「created_name_keys / created_name_variants」精确回删（不误删其它来源共用的 name_key）。副本回滚后与真实库 delta 全 0。

另：variant 解析加了兜底（DB 把盐型做成 orphan substance，如 `diclofenac-sodium`（无 variant）↔ `diclofenac` 的 salt_code='sodium' variant）→ `components_variant_fallback=2,597`，否则会多丢 1,700+ 产品。

---

## 6. 风险 / 待决策

| # | 风险 | 影响 | 建议 |
|---|---|---|---|
| 1 | **1,435 个产品被丢弃（8%）**：TW 老药/复方成分不在库（714 个未匹配 token、43 个 suggested、442 条无 variant） | TW 覆盖 92%（16,457/17,892）；用户可能搜不到这些老药 | ① 接受（推荐先上线）；② 扩别名表/建高频新成分（etanamide 210、methylephedrine 527、guaiacol 257、noscapine 115…）后重跑（幂等） |
| 2 | **成藥/中藥边界**：324（成藥）+281（中藥草稿）行被草案规则排除 | 口径未拍板可能多/少 | 产品/法务确认；放开时改常量重跑 |
| 3 | **规格只到 47.7% medium**（品名解析），复方不猜 | 剂量列 `未载` 较多 | 页面显示「未载」；P2 再接处方/成分数据集 |
| 4 | **證號重复/多包装变体**：1,969 张证多行合并为 1 产品（`variant_count` 进 note，未拆 product.pack 变体） | 包装细节丢失 | 可接受；后续需要时拆 pack |
| 5 | **product_id 格式变化**：由 `TW-TFDA-<slug>` 改为 `TW-TFDA-<slug>-<hash8>` | 若有下游/文档引用旧 dry-run id 会失效 | dry-run CSV 已重生成；生产无旧引用 |
| 6 | **写库顺序依赖**：写完后 DB 有 TW 行，而 `markets.json` TW 仍 disabled → `tests.test_markets_registry` 的 enabled=DB countries 断言会红 | 仓库短暂红 | 与「启用 TW + zh-Hant」同一窗口执行（runbook §4） |
| 7 | 真实库写事务 ~6s 会锁库 | 并行 build/ingest 失败 | 按纪律停写后再 apply |
| 8 | DB 体积：写后 453MB（含空闲页），VACUUM 后 351MB | 备份/磁盘 | Lead apply 后跑一次 VACUUM（5.5s） |

---

## 7. 证据（`.tmp/tw-write/`）

| 文件 | 内容 |
|---|---|
| `write_final.out.txt` / `final_write.out.txt` | 最终全量写库输出（16,457 产品等） |
| `final_idem.out.txt` | 幂等第二次（removed 16,457、created_keys 0） |
| `final_rollback.out.txt` / `verify_rollback.py` | 回滚输出 + 与真实库逐项对比（delta 0） |
| `full_dryrun.csv` / `work/full_dryrun-stats.json` | 全量 dry-run 计划与统计（映射率/未匹配 top） |
| `work-sample/` | 样本 dry-run（limit 2000，token 覆盖 93.9%） |
| `tw_write_manifest.json` | 撤销清单（product_ids / created_keys / created_variants / run_id） |
| `probe*.py` / `analyze_dropped.py` / `analyze_variants.py` / `counts.py` / `verify.py` | 调研/审计脚本 |
| `drugs-tw.db` | 副本（已回滚到基线，351MB，可删） |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Copy-Item data\drugs.db .tmp\tw-write\db.db -Force
& $py db\init_db.py --db .tmp\tw-write\db.db
& $py etl\ingest_tw_tfda.py --write-db --limit 0 --db .tmp\tw-write\db.db --apply `
    --work-dir .tmp\tw-write\work --manifest .tmp\tw-write\tw_write_manifest.json
& $py etl\ingest_tw_tfda.py --rollback .tmp\tw-write\tw_write_manifest.json --db .tmp\tw-write\db.db
& $py .tmp\tw-write\verify_rollback.py
```

---

## 8. 真实库 apply 记录（2026-10-28 执行，Lead 授权）

> 本节为**真实库**（`data/drugs.db`）执行记录；此前 §1–§7 均为副本验证。
> 执行前提：user/Lead 已授权数据写入；**按要求未启用** `data/markets.json` TW 与 `data/languages.json` zh-Hant（build.py 尚未支持 TW 国家列/选择器/i18n，等 v0.7.0 build 任务后再一起启用；当前两处仍为 `enabled:false`）。

### 8.1 结果

| 指标 | before（备份时） | after（apply + VACUUM） | 变化 |
|---|---:|---:|---:|
| products | 409,587 | **426,044** | **+16,457** |
| TW products（coverage） | 0 | **16,457**（active 16,457；使用 2,010 个 variant） | +16,457 |
| product_component | 498,445 | **527,166** | +28,721（其中 TW 28,721） |
| product_name | 568,907 | **601,806** | +32,899（其中 TW 32,899） |
| name_key | 135,251 | **165,619** | +30,368 |
| substance / variant | 12,649 / 13,772 | **12,649 / 13,772** | 不变（未硬造成分） |
| DB 文件 | 325,398,528 B | **351,391,744 B**（VACUUM 后；写后峰值 453,234,688） | **+25,993,216 B（+24.8 MiB / +26.0 MB）** |
| quick_check / FK | ok / 0 | **ok / 0** | 不变 |
| ingest_run | — | `tfda_tw-2026-10-28`：rows_in 72,096 / kept 17,892 / rejected 54,204 / status ok | 新增 1 行 |
| collision（数据层） | severe 15,495 / warning 810 | severe **18,917** / warning **819** | +3,422 / +9（TW 繁中/英文名与现有市场名归一后碰撞增加，属预期；站点暂不展示 TW 页面，待启用前评估） |

### 8.2 命令与耗时（本机实测）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Copy-Item data\drugs.db data\backups\drugs-before-tw-ingest-20261029.db   # 0.1s（325,398,528 B）
& $py db\init_db.py                                                        # 8.06s（country 7→8；product 重建 7.86s）
& $py etl\ingest_tw_tfda.py --write-db --limit 0 --apply --allow-real `
    --manifest .tmp\tw-ingest\tw_write_manifest.json                      # 11.17s 墙钟（写事务 6.15s）
& $py db\check_data.py                                                     # 9.32s（TW coverage 行出现）
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');c.execute('VACUUM');c.close()"  # 5.41s（453→351 MB）
```

- 机器总耗时约 **34s**（备份→迁移→写库→check_data→VACUUM）。
- 写库参数：`removed_old_products=0`、`product_id_conflicts=0`、`components=28,721`、`components_variant_fallback=2,597`、`strength_rows_written=7,786`、`created_name_keys=30,368`（明细见 `.tmp/tw-write/real_write.out.txt`）。

### 8.3 备份 / 回滚

| 项 | 路径 |
|---|---|
| 迁移前完整备份 | `data/backups/drugs-before-tw-ingest-20261029.db`（325,398,528 B） |
| 撤销清单（本次写库） | `.tmp/tw-ingest/tw_write_manifest.json`（5,048,009 B；含 product_ids / created_name_keys / created_name_variants / run_id） |

回滚方式（二选一）：
1. 精准回滚（只删 TW 数据，保留其它会话后续写入）：
   ```powershell
   & $py etl\ingest_tw_tfda.py --rollback .tmp\tw-ingest\tw_write_manifest.json --allow-real
   # → 预期：products 426,044→409,587、TW 16,457→0、components→498,445、names→568,907；
   #   已在副本验证 delta 全 0；回滚后可 VACUUM 回收（~5s）
   ```
2. 整体恢复备份（会覆盖备份后其它会话的写入，需确认）：`Copy-Item data/backups/drugs-before-tw-ingest-20261029.db data/drugs.db`（然后重新跑需要的 ETL）。

### 8.4 未做/后续

- **未启用** `markets.json` TW、`languages.json` zh-Hant（按要求）；两文件本轮未改（仍 `enabled:false`）。
- **未跑** `site/build.py` / git / 发布；TW 页面暂不会出现在站点（build 仍按 7 市场生成）。
- 当前校验状态（刻意过渡态）：`lib/markets.py --check` **通过**（source 行存在、TW disabled 允许）；`tests.test_markets_registry` **47 项中 1 项红** = `test_enabled_markets_match_db_countries`（DB 已有 TW 行、markets 尚未启用）——这正是 Lead 要求的「暂不启用」，等 build 支持后启用 TW + zh-Hant 时一并转绿。
- 等 v0.7.0 build.py 支持 TW 国家列/选择器/i18n 后：同一窗口启用 TW + zh-Hant → `lib/markets.py --check` + `tests.test_markets_registry`（需把「enabled 市场 = DB countries」断言与 `test_tw_is_planned_placeholder` 一起更新）→ build/publish。
- 1,435 个「无任何可挂成分」的 TW 产品仍未入库（8.0%，见 §6）；建议下一轮扩别名/补高频成分后幂等重跑补入。

---

_本报告由并行子智能体 data-depth 生成；§1–§7 副本验证时 `data/drugs.db` 只读；§8 为 Lead 授权后的真实库执行记录，未跑 git / 发布 / `site/build.py`。_
