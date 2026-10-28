# EU（EMA）层：region 建模 + 副本入库验证（task-102）

> 日期：2026-10-28 ｜ 真实库：`data/drugs.db` **只读未写** ｜ 未改 `site/build.py` / `data/markets.json` / git / 发布
> 依据：`reports/ema-ingest-prep.md`（task-97，EMA human 2,357 / 成分 2,782 / 映射 85.6%）、`etl/ingest_ema_medicines.py`（staging 原型）
> 本任务：**schema 建模（region 层）** + `db/schema.sql`/`db/init_db.py` 幂等迁移 + **DB 副本**写入 EMA 正式表 + check/quick/FK/coverage + 幂等/回滚验证；真实库 apply 待批准。
> 产物：`db/schema.sql`、`db/init_db.py`、本报告、`.tmp/eu-schema/`（副本/适配器/清单/验证证据）。

---

## 0. 结论

| 项 | 结果 |
|---|---|
| 建模选择 | **`product.region TEXT NULL`（'EU'）+ `country NULL`**，两者二选一（表级 CHECK 强制）；**不用 `country='EU'`**（EU 不是国家市场，也不进国家下拉） |
| schema 变更 | country 改为可空（保留 9 国枚举 + HK）、新增 region 列（CHECK `IN ('EU')`）、二选一 CHECK、新增 `idx_product_region`；`coverage` 视图改为 `COALESCE(country, region)` 分组（EU 单独一行，现有国别行不变） |
| init_db 迁移 | 老库（无 region 列 / country NOT NULL）自动重建 product 表（列拷贝、region 默认 NULL、重建索引、校验行数/hash/索引/视图/FK/quick）；空库按新 schema 建库 |
| 副本迁移结果 | 426,044 行 / 内容 hash **不变**；country 枚举 8→9（TW 已有 + **HK** 由当前 schema 引入）；2 个 product 索引；3 视图可查；FK 0 / quick ok；**现有 8 个国别 coverage 行逐值一致**；幂等重跑 0.04s |
| 副本 EMA 写入 | **2,357 human 产品**（active 1,566 / withdrawn 426 / unknown 364 / discontinued 1）；源 2,782 成分 → 映射 2,381（85.6%）→ **挂载 variant 2,354**（27 个映射成功但无 variant）；**product_component 2,354**；name_key +912、name_variant +1,612、product_name +2,357；**289 个产品无任何可挂成分**（仅名称/ATC/MAH/状态层） |
| 副本总量 | products **426,044 → 428,401**（+2,357）、components **527,166 → 529,520**（+2,354）、substances/variants 不变；coverage 9→**10 行**，EU 行 `(2357, 1137, 1566, 2026-10-28)` 独立；quick ok / FK 0；check_data 正常显示 EU 行 |
| 耗时/体积 | init_db 迁移 **9.79s**（重建 9.74s）；EMA 写入 **1.19s 事务 / 2.62s 墙钟**；VACUUM 后 DB **361.0 MB**（基线 351.4 MB，**+9.2 MB**） |
| 幂等/回滚 | 第二次 apply 行数不变（删旧 2,357、created_name_keys=0）；数据回滚 1.03s，与 pristine **delta 全 0**；整库回滚（恢复备份）→ **8 枚举、无 region、426,044 行**，quick/FK ok |
| 真实库 | ✅ 未写：426,044 products（TW 16,457）、枚举 8（无 HK/region）、无 EU 行 |

**一句话**：region 建模与迁移已通过副本全流程验证；EU/EMA 可作为「区域层」与国别产品共存（coverage 单独一行、不污染 9 国统计），真实库 apply 待 Lead 批准并与 HK/TW 窗口协调（见 §4）。

---

## 1. 设计：为什么用 region 而不是 country='EU'

| 方案 | 结论 |
|---|---|
| **A. `product.region='EU'`，`country=NULL`（采用）** | 语义正确（EU 是区域授权层，不是国家市场）；查国家仍按 country；coverage/页面可单列 EU；向后兼容（现有行 country 非空、region NULL） |
| B. `country='EU'` | ❌ EU 不是国家/地区代码意义上的「上市国家」；会污染国家下拉/国家统计/`markets.json` 的 country 概念；EMA 数据在 EU/EEA 全境有效、不隶属单一国家 |
| C. `market` 表 + `product.market_code`（region kind） | 更彻底但迁移成本高（所有查询改写）；本轮不做，保留为未来重构方向（与 `data/markets.json` 的 region 概念可对齐） |

**不变量（schema CHECK）**：
```sql
CHECK ((country IS NOT NULL AND region IS NULL) OR (country IS NULL AND region IS NOT NULL))
```
- 国别产品：`country='US'/'GB'/…`、`region=NULL`（现有 426,044 行全部满足）；
- 区域层：`country=NULL`、`region='EU'`；
- 不允许两者都空或都非空（防歧义/漏填）。
- `region` 仅允许 `'EU'`（新区域需加 CHECK 代码 + 一次重建迁移，与新增国家同流程）。

**coverage 视图**（唯一需要改的视图/查询）：
```sql
SELECT COALESCE(p.country, p.region) AS country, …
FROM product p LEFT JOIN product_component pc …
GROUP BY COALESCE(p.country, p.region);
```
→ 现有国别行完全不变（`COALESCE(country, NULL)=country`），EU 单独一行；国家统计脚本若按 `country IN (...)` 过滤天然排除 EU，不受污染。

---

## 2. 改动

### 2.1 `db/schema.sql`

1. product DDL：
   - `country TEXT NULL CHECK (country IS NULL OR country IN ('US','GB','CN','ES','MX','AU','CA','TW','HK'))`（原 NOT NULL）；
   - 新增 `region TEXT NULL CHECK (region IS NULL OR region IN ('EU'))`；
   - 表级 `CHECK ((country IS NOT NULL AND region IS NULL) OR (country IS NULL AND region IS NOT NULL))`；
   - 新增 `idx_product_region ON product(region, status)`（区域层查询用）；
   - 头注释补「区域层（region，非国别）：EU = EMA 集中审批」说明。
2. `coverage` 视图：`DROP VIEW IF EXISTS coverage` + `COALESCE(p.country, p.region)` 分组（如上）。

### 2.2 `db/init_db.py`

- `CHECK_RE` 放宽：兼容 `country TEXT NULL CHECK (… )` 与旧版 `TEXT NOT NULL CHECK`（否则新 schema 下 `markets()` 解析为空导致迁移误判）。
- 新增 `_product_region_needed(db)`：`region` 列缺失 或 `country` 仍 NOT NULL → 需要重建。
- `build()` 调整顺序：**先做 product 迁移再 `executescript(schema_text)`**（新版 coverage 视图引用 `p.region`，老库必须先有 region 列）；迁移条件 = country/status 枚举差异 **OR** region 需要；复用 `_rebuild_product()`（列拷贝、索引重建、校验），之后执行 schema 刷新视图。
- docstring 补第 5 项迁移说明。
- 空库：`executescript` 直接按新 schema 建表（含 region/CHECK/coverage），无重建。

### 2.3 说明
- **未改** `data/markets.json`/`languages.json`/`build.py`/`etl/*`（按写范围）。
- EMA 正式表写入的**原型适配器**在 `.tmp/eu-schema/promote_ema.py`（不属于仓库跟踪文件）：复用 `etl/ingest_ema_medicines.py` 的 `parse_xlsx/build_records/SubstanceMapper`，把 staging 数据提升为 product/component/name/ingest_run；正式落地时建议把这部分并入 `etl/ingest_ema_medicines.py`（加 `--write-products`/region 支持，属后续任务）。
- EMA 许可：可再发布（须署名 EMA，见 `reports/ema-ingest-prep.md` §2）；source 行 `source_id='ema_medicines'`、`data_as_of=2026-10-28`、license/license_url 按 EMA Legal notice。

---

## 3. 副本验证（`data/drugs.db` 只读复制 → `.tmp/eu-schema/drugs-eu.db`）

基线副本：426,044 products / 527,166 components / name_keys 165,619 / names 601,806 / 8 国枚举（TW 已写、**HK 数据未写**）/ 351,391,744 B / product_id 内容 hash `4bdd19e4edb426c3`。

### 3.1 迁移

| 步骤 | 结果 |
|---|---|
| 空库建库 `init_db --db empty.db` | 0.20s；`country` 可空、`region` 列、二选一 CHECK、`idx_product_region`、`coverage` 视图；products 0、quick ok |
| 老库副本升级 `init_db --db drugs-eu.db` | **9.79s**（product 重建 9.74s）：country 8→9（新增 HK）、status 无新增、region 列/country 可空需要重建；**迁移校验 OK：426,044 行、2 个 product 索引、3 视图可查、FK 0、quick ok** |
| 迁移后逐项对比 | products/components/name_keys/name_variants/names/substances/variants 全不变；product_id hash 不变；8 个国别 coverage 行**逐值一致**；filesize 351.4 → 486.9 MB（旧表页未回收） |
| 幂等重跑 | **0.04s**，无迁移、无变化 |

### 3.2 EMA EU 层写入（原型适配器）

```text
$$py .tmp/eu-schema/promote_ema.py --db .tmp/eu-schema/drugs-eu.db --apply --manifest .tmp/eu-schema/ema_manifest.json
```

| 指标 | 值 |
|---|---:|
| human 产品（EU 号唯一） | **2,357** |
| 授权状态（映射到 schema） | active **1,566** / withdrawn 426 / unknown 364 / discontinued 1 |
| 源成分组件 | 2,782（映射 2,381 = 85.6%） |
| 写入 product_component（有 variant 可挂） | **2,354**（27 个映射成功但无 variant） |
| 无任何可挂成分的产品 | **289**（12.3%；仅名称/ATC/MAH/状态层） |
| name_key / name_variant / product_name | +912 / +1,612 / +2,357 |
| ATC 覆盖 / MAH 覆盖（源） | 94.4% / 99.1% |
| 写库耗时 | 1.19s 事务 / 2.62s 墙钟 |
| 幂等第二次 apply | 行数不变（removed_old_products=2,357、created_name_keys=0） |
| VACUUM 后 DB | **361.0 MB**（净 +9.2 MB vs 基线） |

**写入后总量（副本）**：products **428,401**、components **529,520**、name_keys 166,531、names 604,163，substances/variants 不变；quick ok / FK 0。

**coverage（10 行，EU 独立一行，国别不变）**：

```text
('AU', 11890, 2779, 7160, …) … ('EU', 2357, 1137, 1566, 2026-10-28) …
('TW', 16457, 2010, 16457, …) ('US', 110179, 4803, 110179, …)
```

`check_data`（副本）正常输出 EU 行与总数（products 428,401 / components 529,520 / substances 12,649 不变）。

### 3.3 回滚

| 层 | 操作 | 结果 |
|---|---|---|
| 数据回滚（只删 EU 数据） | `.tmp/eu-schema/promote_ema.py --rollback .tmp/eu-schema/ema_manifest.json --db …` | 1.03s；删 2,357 products / 912 name_keys / 1,612 name_variants；与迁移后基线 **delta 全 0**（products/components/name_keys/name_variants/names/EU 行/ingest_run）；quick ok / FK 0；**region 列保留**（schema 不回退） |
| 整库回滚（schema 也回退） | 恢复 `drugs-eu.pristine.db`（真实库对应 apply 前备份） | 枚举回 **8**、无 region 列、426,044 行、TW 16,457、无 EU 行、quick ok / FK 0 / 351.4 MB |

> `db/init_db.py` 路径没有撤销清单：**真实 apply 前必须备份**；schema 回退只能靠备份恢复。数据级回滚可用 EMA 适配器/生产 ETL 的 `--rollback`。

---

## 4. 真实库 apply 步骤（待 Lead 批准；与 HK/TW 窗口协调）

> 当前真实库：426,044 products（TW 16,457）、country 枚举 **8**（无 HK/region）、351.4 MB。**不动 markets.json/build.py。**

1. **备份**：`Copy-Item data\drugs.db data\backups\drugs-before-eu-region-<date>.db`（325…→351 MB；run_all 也会自动备份）。
2. **schema 迁移**：`& $py db\init_db.py`
   - 会把 **country 8→9（+HK 枚举）** 与 **region 列/country 可空** 一次重建完成（约 10s；426k 行；**HK 数据未写也能加枚举**）。
   - 若 HK 真实 apply（task-93 阶段二）先做，则这里只做 region 重建；两者共用同一 `init_db` 逻辑，无冲突。TW 启用窗口（task-87）只改 markets/languages，与此无关。
3. **EMA 写入**：先决定实现归属：
   - 推荐：把 `.tmp/eu-schema/promote_ema.py` 的逻辑并入 `etl/ingest_ema_medicines.py`（加 `--write-products`，region 支持）后再 apply（可跟踪、可复跑）；
   - 过渡：Lead 批准后直接 `& $py .tmp\eu-schema\promote_ema.py --db data\drugs.db --apply --allow-real`（原型脚本；不建议作为长期入口）。
   - 约 1.2s 事务；自动写 source(ema_medicines)+ingest_run。
4. **验数**：`& $py db\check_data.py`；`PRAGMA quick_check` / `foreign_key_check`。
   - 期望：products **426,044→428,401**（+2,357）、components **527,166→529,520**（+2,354）、substances 12,649 不变、coverage **10 行**（EU 行 2,357 / active 1,566）、DB ~361 MB（VACUUM 后）。
5. **回滚**：数据级 `--rollback`（delta 已验证 0）或恢复第 1 步备份；**schema 回退 = 备份恢复**。
6. **build/页面**（后续任务，本任务不改）：EU 作为 region 分组出现，不进国家下拉/国家统计；页面文案「EU 集中審批（EMA）——歐盟層授權，非某一國家產品；EMA 數據不含規格/劑型/包裝」；搜索索引建议加 `rg='EU'` 字段区分 country vs region；About 署名 EMA（四语：Source: EMA / Fuente: EMA / 來源：EMA）。

---

## 5. 风险 / 缺口

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| 1 | **289 个 EU 产品无任何可挂成分**（名称/ATC/MAH/状态层） | 成分页/剂量层无法展示；coverage products 有但 components 少 | build 任务需支持「region 产品无成分」展示；或未来补生物制品 substance（另任务） |
| 2 | 27 个映射成功但无 variant、401 个成分未映射 | 成分覆盖 85.6%（组件）/ 2,354 挂载 | 页面允许「成分原文不可点」；补别名/生物制品表（后续） |
| 3 | **country NULL** 语义变更 | 任何 `country NOT NULL` 假设的查询/build 逻辑需检查（site/build.py 未改，真实 apply 前需 build 任务确认） | 迁移后先跑 build/check；国家统计按 `COALESCE` 或显式 `country IS NOT NULL` |
| 4 | coverage 视图改为 COALESCE | 现有 About/README 数字若按 view 全量求和会把 EU 算进「国家」 | build 任务分列「国家 9 + 区域 EU」；数字口径同步（发布前） |
| 5 | `db/migrate_country_tw.py` / `migrate_country_hk.py` 的 CHECK_RE 仍匹配旧 `NOT NULL` DDL | 新 schema 下这两个旧脚本可能解析失败 | 后续统一改用 `db/init_db.py` 迁移（或同步更新脚本正则）；本任务写范围外 |
| 6 | 真实 apply 与 HK/TW 窗口交叉 | schema 重建一次完成；顺序不同结果一致，但避免并行写库 | Lead 排窗口；apply 期间停 build/ingest |
| 7 | EMA 品牌名重名（2,754 EU 号 / 2,702 名） | 同名不同 EU 号需区分 | 页面必须显示 EU 号 + MAH；名称键共享但 product 行独立 |
| 8 | init_db 路径无 schema 撤销清单 | schema 回退只能备份恢复 | apply 前强制备份（§4 第 1 步） |

---

## 6. 证据（`.tmp/eu-schema/`）

| 文件 | 内容 |
|---|---|
| `empty.db` / `empty.out.txt` | 空库建库（region schema） |
| `drugs-eu.pristine.db` | 迁移前真实库副本（8 枚举 / 无 region / 426,044 行） |
| `drugs-eu.db` | 迁移 + EMA 写入 + 回滚演练副本（当前已恢复 pristine） |
| `upgrade.out.txt` / `upgrade2.out.txt` | init_db 8→9 + region 迁移 / 幂等重跑日志 |
| `verify.py` / `verify*.out.txt` | 计数/hash/coverage/FK/quick 对比 |
| `promote_ema.py` / `ema_apply*.out.txt` / `ema_idem.out.txt` / `ema_rollback.out.txt` | EMA EU 层原型适配器、写入/幂等/回滚日志 |
| `ema_manifest.json` | 撤销清单（product_ids / created keys / variants / run_id） |
| `check_data.out.txt` | check_data（含 EU 行）+ 恢复 pristine 验证 |
| `check_and_restore.py` | check_data + 整库回滚验证脚本 |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Copy-Item data\drugs.db .tmp\eu-schema\drugs-eu.db -Force
& $py db\init_db.py --db .tmp\eu-schema\drugs-eu.db
& $py .tmp\eu-schema\promote_ema.py --db .tmp\eu-schema\drugs-eu.db --apply --manifest .tmp\eu-schema\ema_manifest.json
& $py .tmp\eu-schema\verify.py
& $py .tmp\eu-schema\promote_ema.py --db .tmp\eu-schema\drugs-eu.db --rollback .tmp\eu-schema\ema_manifest.json
```

---

_本报告由并行子智能体 data-depth 生成；真实库未写、`site/build.py`/`data/markets.json` 未改、未跑 git/发布。真实 apply 待 Lead 批准。_
