# TW（台湾）入库 runbook + markets.json 注册（task-69）

> 日期：2026-10-28 ｜ 真实库：`data/drugs.db` **只读未写** ｜ 未跑 `site/build.py` / git / 发布
> 本文件汇总已有：`reports/tw-tfda-audit.md`（task-45）、`reports/tw-ingest-skeleton.md`（task-54）、`reports/tw-country-migration.md`（task-62）、`data/raw/tw/` 样本、`etl/fetch_tw_tfda.py`、`etl/ingest_tw_tfda.py`；并登记 `data/markets.json` 的 TW 数据源。
> 产物：`data/markets.json`（TW 项更新）、本报告、`.tmp/tw-runbook/`（source SQL 草案、验证脚本与日志）。

---

## 0. 结论摘要

| 项 | 状态 |
|---|---|
| TFDA 数据源审计 / 许可 | ✅ 完成：data.gov.tw #9122「全部藥品許可證資料集」，**OGDL v1.0 可再发布（须「顯名聲明」署名）**，每 7 日更新，`data_as_of=2026-10-22`；72,096 行 / 28 列 / 44.5 MB CSV（已缓存） |
| 抓取脚本 | ✅ `etl/fetch_tw_tfda.py`（元数据+下载+解压+样本+sha256，不写 DB） |
| ingest 骨架 dry-run | ✅ `etl/ingest_tw_tfda.py`：全量 dry-run **17,892 张可入证**（去重/过滤后），成分 token 覆盖 **83.5%**，复方 28.2%，规格 medium 47.7% |
| schema `country` 加 TW | ✅ `db/schema.sql` 已加 `TW`；`db/init_db.py` 幂等重建迁移已修复并用副本验证（task-62） |
| 别名表 `data/tw_ingredient_aliases.csv` | ⏳ **未产出**（task-67 pending，未开工）；预计把 token 覆盖 83.5% → ~90% |
| `ingest_tw_tfda.py --write-db` | ❌ **未实现**（占位报错：「写库尚未实现：先完成 country CHECK 迁移…」） |
| `data/markets.json` TW 项 | ✅ 已更新：`source_id="tfda_tw"`、`data_as_of="2026-10-22"`、`enabled=false`（暂保持）、notes 写清数据源/许可/待办 |
| `source` 表登记 | ❌ 未执行（真实库无 `tfda_tw` 行）；**SQL 草案已备**并已在 DB 副本验证 → 见 §2.2 |
| 台湾成藥/中藥/植物提取物边界 | ⚠️ 待产品/法务拍板（草案排除 324 + 281 行） |
| zh-Hant 语言 | ⚠️ `data/languages.json` 仍 `enabled=false`；TW `default_lang=zh-Hant`，**启用 TW 前必须先启用 zh-Hant**（否则注册表校验失败） |
| 预计落地工作量 | 实现 `--write-db` + 别名表 + source 登记 ≈ **1 人日**；入库/迁移/建站机器时间 ≈ **1–2 小时**（含 build；不含发布上传） |
| 预计入库产出 | **~17.9k 产品**（TW 成为第 8 市场）、~3.9 万成分行、~3.5 万商品名、~1 万新 name_key；DB **+20–35 MB**（估算，实现后实测） |

**一句话**：数据、审计、dry-run 骨架、schema 迁移都已就绪；现在缺「3 个实现/登记动作 + 2 个决策」（`--write-db`、别名表、source 行；成藥/中藥边界、zh-Hant 启用），齐了就能按 §4 一次入库。

---

## 1. 已有资产一览

| 资产 | 路径 | 说明 |
|---|---|---|
| 审计报告 | `reports/tw-tfda-audit.md` | 数据量/字段覆盖/许可/入库建议/风险（22 KB） |
| 抓取脚本 | `etl/fetch_tw_tfda.py` | 下载缓存/解压/样本/元数据（不写 DB） |
| 原始数据缓存 | `data/raw/tw/tfda_36.csv`（44.5 MB）、`.json`（79.3 MB）、`.zip`（10.1/11.8 MB）、`meta_9122.json`、`sample_500.csv`、`sample_active_500.csv` | 含 `data_as_of`、许可元数据；`data/raw/` 不入库 |
| 入库骨架 | `etl/ingest_tw_tfda.py` | dry-run 默认；`--limit/--out/--csv`；`--write-db` 占位 |
| dry-run 样本 | `data/tw_ingest_dryrun.csv`（1,535 行 × 32 列） | 前 2,000 候选；审阅用 |
| 全量 dry-run 证据 | `.tmp/tw-ingest/full_dryrun.csv`（17,892 行）、`full_dryrun-stats.json`、`unmatched_tokens.csv` | 统计见 §3 |
| schema 迁移 | `db/schema.sql`（已含 TW）、`db/init_db.py`（幂等重建）、`db/migrate_country_tw.py`（独立 dry-run/apply/rollback）、`reports/tw-country-migration.md` | 副本实测通过 |
| 市场注册 | `data/markets.json` TW 项（本次更新）、`data/languages.json` zh-Hant（disabled）、`lib/markets.py`、`tests/test_markets_registry.py` | 见 §2 |
| 别名表（待产） | `data/tw_ingredient_aliases.csv`（task-67） | 列建议 `tw_token,inn_en,substance_id,evidence,confidence` |
| 繁中字典（待用） | `data/i18n_zh_hant.json`（task-53）、`reports/zh-hant-i18n.md` | 供启用 zh-Hant 时接入 build |

---

## 2. `data/markets.json` 变更 + `source` 表登记

### 2.1 变更内容（TW 项）

```jsonc
{
  "code": "TW", "kind": "country", "parent": null, "group": "ASIA",
  "name": { "en": "Taiwan", "es": "Taiwán", "zh": "台湾" },
  "i18n_key": "home.tw", "flag": "🇹🇼",
  "source_id": "tfda_tw",            // 新增：主数据源（原 null）
  "extra_source_ids": [],
  "default_lang": "zh-Hant", "languages": ["zh-Hant"],
  "enabled": false,                   // 暂保持 false（不生成页面/不进国家选择器）
  "order": 80,
  "data_as_of": "2026-10-22",        // 新增：TFDA 快照日期（每 7 日更新）
  "notes": "……数据源/许可/待办（含 6 项）……"
}
```

- **为什么 disabled 也填 source_id**：市场注册表是「唯一真相源」，先把数据源钉住；`lib/markets.py` 的校验对**非空** `source_id` 一律要求在 DB `source` 表存在（不区分 enabled），所以这次更新后 **必须尽快登记 source 行**，否则注册表校验/测试会失败（见 §2.3）。
- **命名冲突（需拍板）**：本任务指定 `source_id=tfda_tw`；而 `etl/ingest_tw_tfda.py` 里常量是 `SOURCE_ID="tw_tfda"`，`data/tw_ingest_dryrun.csv` 的 source_id 列也是 `tw_tfda`。**建议统一为 `tfda_tw`**（org+地区，和 `cofepris_mx` 一致），实现 `--write-db` 时改脚本常量；已写进阻塞项 B3。

### 2.2 `source` 表登记 SQL 草案（**未执行**）

文件：`.tmp/tw-runbook/tfda_tw_source.sql`（已在 DB 副本上验证：执行后 `lib/markets.py` 校验 0 错误）。

```sql
INSERT OR REPLACE INTO source
    (source_id, name, url, license, license_url, retrieved_at,
     data_as_of, data_as_of_note, notes)
VALUES (
    'tfda_tw',
    '衛生福利部食品藥物管理署（TFDA）全部藥品許可證資料集',
    'https://data.gov.tw/dataset/9122',
    '政府資料開放授權條款－第1版 (OGDL v1.0)',
    'https://data.gov.tw/license',
    '2026-10-28', '2026-10-22',
    'weekly（每 7 日與藥證業務管理系統同步）',
    '可再发布（OGDL v1.0，须按「顯名聲明」署名）；本站只存事实字段，不存適應症/用法用量正文。'
);
```

执行时机：**与 `--write-db` 首次写库同一事务/同一发布窗口**（单独先登记也安全，source 表允许多余来源；但启用 TW 前必须已登记）。执行方式：写进 ingest 脚本（推荐，幂等 + `ingest_run` 一起提交），或 `sqlite3 data/drugs.db < .tmp/tw-runbook/tfda_tw_source.sql`。

### 2.3 ⚠️ 本次变更的已知副作用（必须先处理）

`data/markets.json` 改完后、`source` 行登记前：

- `python lib/markets.py --check` → **1 项失败**：`市场 TW: source_id=tfda_tw 不在 DB source 表（先登记数据来源）`；
- `python -m unittest tests.test_markets_registry` → **7 个失败**：
  - 6 个是上述 source 未登记（`test_registry_is_valid`、`test_cli_check_passes`、`test_dummy_region_with_child`、`test_dummy_market_*` 等）→ **执行 §2.2 SQL 即恢复**；
  - 1 个是测试断言本身要改：`test_tw_is_planned_placeholder` 里 `assertIsNone(tw.source_id)`，现在是 `'tfda_tw'` → **需要把该断言改为 `assertEqual("tfda_tw", tw.source_id)`**（测试文件不在本任务写范围，交下一任务/Lead）。
- 已验证：在 DB **副本**执行 §2.2 SQL 后，`MarketsRegistry(source_ids=copy)` 校验 **PASS（0 errors）**，TW 保持 disabled、`source_id=tfda_tw`（证据 `.tmp/tw-runbook/verify_source_sql.out.txt`）。

> 若 Lead 不希望仓库暂时带 7 个失败测试，可二选一：① 尽快执行 source 登记（写真实库的小任务）+ 改测试断言；② 暂时把 `source_id` 回退为 `null`（本任务要求填 `tfda_tw`，故未回退）。

---

## 3. 入库口径与预计产出（dry-run 证据）

全量 dry-run（`.tmp/tw-ingest/full_dryrun-stats.json`、`data/raw/tw/tfda_36.csv` 72,096 行）：

| 指标 | 数值 |
|---|---:|
| 总行数 / 扫描 | 72,096 |
| 拒绝：注销 / 非产品类 / 过期 / 成藥草案 / 中藥植物药草案 / 无成分 | 35,556 / 13,457 / 1,095 / 324 / 281 / 71 |
| **可入产品（去重后许可证）** | **17,892**（多行变体 1,969） |
| 成分 token 总数 / 命中 / 覆盖率 | 39,045 / 32,598 / **83.5%** |
| 成分全匹配行 | 14,344 / 17,892 = 80.2% |
| 未匹配 token（distinct/次数） | 893 / 3,548 行（别名表 target，task-67） |
| 复方行 | 5,048（28.2%） |
| 规格置信度 medium / none / low | 8,541 / 9,316 / 35 |
| 剂型 unknown | 7 行（映射覆盖 99.96%） |
| release ER / DR | 417 / 258 |

> 预计写库：**product +17,892（+4.4%）**、product_component **+~39k（+7.8%）**、product_name **+~35k**、新 name_key ~1–1.5 万、新 substance 数百（未匹配 token 中能定案的）、variant 数百；DB **+20–35 MB（估算）**。TW 成为第 8 个市场。

---

## 4. 完整 runbook（备份 → schema → 别名 → ingest → check → 启用 → build）

> 前置决策：D1 成藥/中藥边界（B2）、D2 zh-Hant 启用方式（B5）、D3 source_id 命名统一（B3）。
> 顺序原则：**source 登记 → schema 迁移 → 别名表 → `--write-db` → check_data → 启用 markets + zh-Hant → build/publish**；`markets.json` 的 `enabled=true` 与 DB 首次含 TW 行必须在**同一发布窗口**，否则 `tests.test_markets_registry` 的「enabled 市场 = DB countries」断言失败。

### Step 0 · 决策与实现（阻塞项，见 §7）
- B1 实现 `etl/ingest_tw_tfda.py --write-db`（规格见 §4.1），预计 0.5–1 人日；
- B2 成藥/中藥/植物提取物边界（324+281 行）拍板；
- B3 统一 `source_id = tfda_tw`（改 ingest 常量）；
- B5 决定 zh-Hant：启用语言（build 接入 task-53 字典）或临时把 TW `default_lang` 改 `en`（不推荐，失繁体语义）。

### Step 1 · 备份（~1 s / 325 MB）
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Copy-Item data\drugs.db data\backups\drugs-before-tw-$(Get-Date -Format yyyyMMdd-HHmm).db
# run_all.py 也会自动备份到 data/backups/（只留最近 5 份）
```

### Step 2 · schema 迁移（加 TW 枚举；重建 product 表）
```powershell
& $py db\init_db.py                      # 自动识别 7→8 并重建（自带校验；实测重建 8.8s / 总 9.0s）
# 或显式：& $py db\migrate_country_tw.py --apply --allow-real --backup-dir data/backups --vacuum
```
- 机器时间：**2.2–9 s**（409,587 行重建）+ 可选 VACUUM 4–5 s；磁盘峰值 **+~128 MB**。
- 验证：`PRAGMA quick_check`=ok、`foreign_key_check`=0、行数不变、`idx_product_country` 存在、`country` 枚举含 TW。
- ⚠️ 迁移期间 `BEGIN IMMEDIATE` 独占写锁：先停掉 build/ingest/其它会话；详见 `reports/tw-country-migration.md`。

### Step 3 · 别名表（task-67，待产出）
```powershell
# 产出 data/tw_ingredient_aliases.csv（tw_token,inn_en,substance_id,evidence,confidence）
# 预期 token 覆盖 83.5% → ~90%+；未匹配的疫苗/生物制剂/植物提取物保留 unmapped
```

### Step 4 · 首次写库（建议先在 DB 副本演练）
```powershell
Copy-Item data\drugs.db .tmp\tw-runbook\db-copy.db
& $py etl\ingest_tw_tfda.py --write-db --db .tmp\tw-runbook\db-copy.db   # 实现后可用
& $py db\check_data.py ...                                               # 核对计数
```
- 实现规格（§4.1）：source/ingest_run upsert → 幂等删旧 TW 行 → 分批插 product/product_name/name_key/name_variant/product_component（复用现有 variant）→ 单事务提交 → 打印 rows_in/kept/rejected/耗时。
- 预计写库 **10–60 s**（17.9k 产品 / 39k 成分行，本地 SSD；实现后实测）。
- 副本核对：TW 产品数 17,892、country 分布出现 TW、`check_data` 无异常、5 个抽样品牌可检索。

### Step 5 · 真实库写库 + 数据体检（~1–2 min）
```powershell
& $py etl\ingest_tw_tfda.py --write-db            # 真实库（先确认 markets/source 已就绪）
& $py db\check_data.py                            # 实测 8.2 s；counts/coverage 加 TW 行
```
- 验收数字：products 409,587 → **427,479（+17,892）**；components 498,445 → **~537,490**；substances 12,649 → **+数百**；countries **7→8**。

### Step 6 · 启用 TW + zh-Hant（同一提交/窗口）
```powershell
# data/markets.json: TW.enabled=true（source_id=tfda_tw 保持）
# data/languages.json: zh-Hant.enabled=true（若走繁体 UI；需 build 接入 /zh-Hant/ 路由）
& $py lib\markets.py --check
& $py -m unittest tests.test_markets_registry -v
```
- 必须同时：source 行已登记、DB 已有 TW 行、测试断言 `test_tw_is_planned_placeholder` 已更新（B4）。
- 若暂不上 zh-Hant UI：把 TW `default_lang` 改为 `en` 并 `languages:["en"]`（临时方案，需产品确认）。

### Step 7 · 站点构建（分钟级；必须先测 SITE_OUT）
```powershell
$env:SITE_OUT='.tmp\dist-tw'; & $py site\build.py      # 等 == done ==
```
- 预计新增页面：新 name/品牌页 ~1–1.5 万、厂家页 ~1–2 千、组合页 +1–2 千；`dist` 体积 **+80–150 MB（估算，待实测）**；首搜索引 core 体积 +5–8 MB。
- 验收：页数/体积/索引大小记录；三语（+zh-Hant）各 3 条检索；TW 产品页/品牌页/厂家页/组合页抽样；链接 404 抽检；移动端抽查。
- 风险：dist 已 ~430 MB / 57.8k 文件（v0.6.0 后）；TW 会让发布上传时间与 GitHub Pages 体积压力上升，若超预算先只发检索层/降页数策略（与 Lead 定）。

### Step 8 · 发布（唯一入口 `deploy/publish.ps1`）
- 顺序：CHANGELOG 加节（V0.6.x）→ `site/build.py` 完成 → `deploy/publish.ps1` → tag/Release；发布后 `deploy/verify_live.py` smoke。
- 回滚见 §6。

### 4.1 `--write-db` 实现规格（给下一任务）

```text
CLI：保留 dry-run 默认；新增 --write-db / --db PATH（默认 data/drugs.db）；--out 仅 dry-run 用
前置校验：
  1) PRAGMA 查 product.country CHECK 含 'TW'，否则报错退出（指向 db/init_db.py / migrate_country_tw.py）
  2) markets.json 的 TW.source_id 与脚本 SOURCE_ID 一致（tfda_tw）；不一致给 warning
写入（单事务 BEGIN IMMEDIATE）：
  3) INSERT OR REPLACE source（§2.2 内容）+ ingest_run(status='ok', rows_in=72096, rows_kept=17892, rows_rejected=54204)
  4) 幂等清理：DELETE FROM product WHERE source_id='tfda_tw'（cascade 清组件/商品名/佐证；name_key 孤儿按 fix_es_combos 方式清）
  5) 分批插入（每 500–1000 行）：
     product(product_id='TW-'+證號slug, country='TW', dosage_form, form_base, route, release, pack, mah,
             approval_id, category=藥品類別, is_branded, status, status_date=有效日期, source_id='tfda_tw',
             source_url='https://data.gov.tw/dataset/9122', retrieved_at, note=製造廠國別/製造商)
     name_key/name_variant（中文品名繁中原样、英文品名）+ product_name(trade, is_primary)
     product_component（ord, variant_id 匹配现有成分/盐 variant；未匹配的进 unmapped 清单）
     variant（新成分/新盐型才建；优先复用）
  6) commit + 打印计数/耗时；7) 失败 rollback all
验收：db/check_data.py；SELECT country,count(*) GROUP BY country；抽查 5 个品牌可检索；TW 产品无 NULL 必填字段。
```

---

## 5. 预计耗时 / 磁盘汇总

| 步骤 | 机器时间（预计/实测） | 磁盘 |
|---|---|---|
| 备份 DB | ~1 s（325 MB 复制 0.1–1 s） | +325 MB（data/backups，保留 5 份） |
| schema 迁移（init_db / migrate） | **2.2–9 s** 重建 +（可选 VACUUM 4–5 s） | 峰值 +128 MB；VACUUM 后回 325 MB |
| 别名表（task-67） | 0.5 人日（离线） | CSV <1 MB |
| `--write-db`（实现后） | **10–60 s**（17.9k 产品/39k 组件，单事务） | DB **+20–35 MB** |
| `db/check_data.py` | **8.2 s**（实测） | — |
| 启用 markets + tests | <1 s | — |
| `site/build.py` | **分钟级**（现状 57.8k 文件 / 429.5 MB dist；TW 后 +80–150 MB 估算） | dist 峰值 +~150 MB |
| `deploy/publish.ps1` | 上传 430→~550 MB，预计 **+数分钟~10 分钟**（GitHub Pages 推送，估算） | 临时 dist.zip ~数百 MB |
| **合计（不含实现与发布等待）** | **~1–2 小时**（含 build） | 预留 **≥2 GB** 空闲（备份+重建峰值+dist） |

---

## 6. 回滚

| 层 | 回滚方式 |
|---|---|
| DB | **首选**：恢复 Step 1 备份 `Copy-Item data/backups/drugs-before-tw-*.db data/drugs.db`；或用 `run_all.py` 的自动备份 |
| DB（无法恢复备份时） | 按来源清理 SQL 草案（`.tmp/tw-runbook/rollback_source_scoped.sql`，见下），需先 `markets.json TW.enabled=false` |
| markets.json | TW 改回 `enabled=false`（source_id 可保留）；若测试/校验要回到旧状态，source_id 改回 `null` 并跑 `tests.test_markets_registry` |
| site/dist | 重新 build（或发布回滚上一个 tag 的产物；发布回滚要人拍板，见 `release` 技能） |
| 发布 | `deploy/publish.ps1` 回滚流程（先 `-DryRun` 检查） |

来源级清理 SQL（草案，**未执行**；真实库优先用备份）：

```sql
BEGIN;
DELETE FROM product WHERE source_id='tfda_tw';   -- product_component/product_name/corroboration 级联删除
DELETE FROM ingest_run WHERE source_id='tfda_tw';
-- 可选：删孤儿 name_key（name_variant 先删，避免 FK）
DELETE FROM name_variant WHERE key_id NOT IN (SELECT key_id FROM product_name);
DELETE FROM name_key WHERE key_id NOT IN (SELECT key_id FROM product_name);
-- 可选：DELETE FROM source WHERE source_id='tfda_tw';
COMMIT;
-- 之后建议 VACUUM（409k 行级 DB 实测约 4.2–5 s）再全量重建站点
```

---

## 7. 阻塞项 / 待决策

| # | 阻塞/决策 | 影响 | 需要谁 |
|---|---|---|---|
| B1 | **`ingest_tw_tfda.py --write-db` 未实现**（占位报错） | 无法写库（其余都就绪） | 实现任务（~0.5–1 人日，规格见 §4.1） |
| B2 | **台湾成藥/中藥/植物提取物边界未拍板**（324 成藥 + 281 中藥草稿） | 入库口径/合规；先排除 vs 放开 | 产品/法务（Lead 决策） |
| B3 | **source_id 命名冲突** `tfda_tw`（markets.json/本任务）vs `tw_tfda`（ingest 常量/dry-run CSV） | 写库 source_id 不一致会导致 markets 校验失败 | 实现时统一 `tfda_tw`（推荐） |
| B4 | **`source` 行未登记**（SQL 草案已备，副本验证通过） | 注册表校验/测试 6 项失败；启用 TW 前必须登记 | Lead 批一个小 DB 写任务或随 `--write-db` 一起执行 |
| B5 | **`tests/test_markets_registry.py::test_tw_is_planned_placeholder` 断言过时**（`assertIsNone(tw.source_id)`） | 改 markets.json 后有 1 个测试永久失败 | 测试维护任务（本任务写范围外） |
| B6 | **zh-Hant 语言未启用**（languages.json `enabled=false`，build 路由/i18n 未接） | TW `default_lang=zh-Hant`，启用 TW 前必须先启用语言或临时改 default_lang | 产品 + i18n/build 任务 |
| B7 | 启用时序：`markets TW.enabled=true` 必须与 DB 首次含 TW 行同一窗口 | 否则 `test_enabled_markets_match_db_countries` 失败 | Lead 排期 |
| B8 | 合规文案：`docs/许可清单.md` 加 TFDA 行 + About 三语署名段（OGDL 顯名聲明） | 许可义务（未署名视为未授权） | docs/i18n/build 任务 |
| B9 | 无 ATC 字段 / 规格无结构化字段（52% none） | 跨市场匹配仅靠成分；剂量列显示「未载」 | 后续 P2（INN→ATC 补、规格解析器） |
| B10 | dist 体积/页数增长（TW 后估算 +80–150 MB） | 发布上传时间/GitHub Pages 容量 | build 前实测，Lead 定页数策略 |

---

## 8. 验收清单（复制到任务）

```text
[ ] source: SELECT * FROM source WHERE source_id='tfda_tw'; 存在且 license/data_as_of 正确
[ ] schema: PRAGMA quick_check=ok, foreign_key_check=0, country CHECK 含 TW, idx_product_country 存在
[ ] ingest: rows_in=72096, rows_kept=17892, rows_rejected=54204；check_data 无异常
[ ] DB: products 409,587→427,479；components →~537,490；countries 7→8；TW 产品可检索
[ ] markets: lib/markets.py --check 通过；tests.test_markets_registry 47/47 通过（含更新后的 TW 断言）
[ ] zh-Hant: languages.json enabled=true（或 TW default_lang 已改）；/zh-Hant/ 入口/文案抽检
[ ] build: == done ==；页数/体积/索引大小记录；三语+繁中各 3 条检索；404/链接抽检
[ ] 发布: CHANGELOG 节 + publish.ps1 成功 + verify_live smoke
[ ] 回滚: 备份存在、rollback SQL 草案已评审
```

---

## 9. 风险

| 风险 | 缓解 |
|---|---|
| source 未登记导致注册表/测试红 | 本报告 §2.2 SQL 先执行（或临时回退 source_id，但不推荐）；CI/验收前必跑 tests |
| 许可证号不唯一（1,969 多行变体） | 去重口径：証號 + variant_count；多包装合并不拆 variant（用 product.pack） |
| 繁中名归一（name_key 简繁）与 CN 同名不同药 | 原文入 name_variant；name_key 照旧归一（繁→简），碰撞交给 `collision` 视图 |
| 成分 83.5% 覆盖→16.5% unmapped 误挂 | 未匹配不硬造：进 unmapped 清单/别名表；新 substance 需人工复核 |
| 规格仅品名解析（52% none） | 标 confidence；页面显示「未载」；P2 再接处方/成分数据集 |
| schema 重建锁库 | 停写、备份、`BEGIN IMMEDIATE`；失败自动回滚；副本先演练 |
| 成藥/中藥误入/漏入 | 先按草案排除，产品/法务确认后再放开（单独重跑 ingest） |
| dist 体积膨胀影响发布 | build 到 SITE_OUT 实测；必要时先发数据/检索层，页面分批 |

---

## 10. 参考

- `reports/tw-tfda-audit.md`（task-45）、`reports/tw-ingest-skeleton.md`（task-54）、`reports/tw-country-migration.md`（task-62）
- `etl/fetch_tw_tfda.py`、`etl/ingest_tw_tfda.py`、`db/init_db.py`、`db/migrate_country_tw.py`
- `data/markets.json`、`data/languages.json`、`lib/markets.py`、`tests/test_markets_registry.py`、`docs/市场扩展接口.md` §6
- 证据：`.tmp/tw-runbook/`（`tfda_tw_source.sql`、`verify_source_sql.py/.out.txt`、`markets_check.out.txt`、`unittest_markets.out.txt`、`check_data.out.txt`）
- 数据：`data/raw/tw/`、`data/tw_ingest_dryrun.csv`、`.tmp/tw-ingest/full_dryrun-stats.json`

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 `site/build.py` / git / 发布。_
