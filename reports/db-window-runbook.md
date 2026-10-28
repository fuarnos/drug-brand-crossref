# 下一 DB 窗口 runbook：HK + EMA（EU region）+ SG 顺序（task-107）

> 日期：2026-10-28 ｜ **不执行**：未写 `data/drugs.db`、未改 `site/build.py` / `data/markets.json` / git / 发布
> 写范围：本报告、`etl/ingest_ema_medicines.py`（EMA 适配器并入正式脚本 + 副本测试）、`.tmp/db-window/`
> 前置：TW 已在真实库（16,457），v0.7.0 已启用 TW/zh-Hant；HK/SG/EMA region 的 build 支持尚未完成；本 runbook 只描述**窗口方案**，等 Lead 拍板开窗。

---

## 0. 当前状态（2026-10-28，实测）

| 项 | 值 |
|---|---|
| 真实库 | `data/drugs.db` 351,391,744 B；products **426,044**；components 527,166；name_keys 165,619；names 601,806；quick ok / FK 0 |
| country 枚举（真实库） | **8**：US, GB, CN, ES, MX, AU, CA, TW（**无 HK / 无 region 列**；EU 行 0） |
| schema.sql（仓库） | country 枚举 **9**（含 HK，可空）+ region 列（EU，XOR CHECK）+ coverage `COALESCE(country, region)`；**无 SG** |
| markets/languages | enabled markets = **8**（含 TW）；enabled languages = **4**（含 zh-Hant）；HK/SG 未注册、EU region 不是市场条目 |
| 已就绪未落库 | HK：`etl/ingest_hk_druglist.py`（副本写入 13,832 产品已验证，task-88/93）；EMA：`etl/ingest_ema_medicines.py --apply-products`（**本次已并入**，副本验证见 §4）；SG：数据由 **task-104** 准备（审计见 `reports/sg-audit.md`：西药 5,511 条可批量，SODL 许可） |
| build 支持 | TW：✅ v0.7.0 已支持；**HK / SG 国家列/选择器/About、EU region 分组：尚未做** → 数据窗口可先行，但 markets 启用必须等 build |

---

## 1. 三种组合（按推荐度）

| 组合 | 场景 | 预计结果 |
|---|---|---|
| **A. HK only** | 只补香港国别数据 | products 426,044→**439,876**；components→**549,047**；coverage 9 国（无 EU） |
| **B. HK + EMA（推荐一次做完）** | 国别 + EU 区域层 | products→**442,233**；components→**551,401**；coverage **10 行**（9 国 + EU） |
| **C. HK + EMA + SG（后续）** | 再加新加坡国别 | SG 预计 +5,511 产品（task-104 数据）；products→~**447,744**；coverage 10 国 + EU = **11 行** |

> 为什么 HK only 也会顺带迁移 region：当前 `db/schema.sql` 已含 region/country 可空（EU 层），`db/init_db.py` 一次重建会同时完成 **country 8→9（HK）+ region 列/XOR/coverage**；无法只加 HK 不加 region（除非临时改 schema，不推荐）。

---

## 2. 窗口步骤（以组合 B 为例；A 可删除 EMA 步骤；C 见 §3）

### 2.0 开窗前决策（必须）
1. Lead 批准窗口时间；确认**无其它会话**在跑 build/ingest/publish。
2. 决定测试口径：窗口后 DB 会有 HK（且 EMA 后 country 集合会出现 NULL region 行）→ `tests.test_markets_registry` 的「enabled 市场 = DB countries」会临时红（HK/SG 未启用、EU 不是国家）。**推荐**：HK/SG build 完成后紧接启用窗口，再让该测试转绿；否则接受「已知红」并在启用窗口一并更新测试（见 §5）。
3. build 侧顺序：**数据窗口 → HK/SG build 支持 → markets 启用窗口 → publish**；EU region 页面需另开 build 任务（region 分组/徽章/About EMA 署名）。

### 2.1 备份（约 0.2–1s / 351 MB）
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$ts = Get-Date -Format yyyyMMdd-HHmm
Copy-Item data\drugs.db "data\backups\drugs-before-hk-ema-window-$ts.db"
Get-FileHash "data\backups\drugs-before-hk-ema-window-$ts.db" -Algorithm SHA256   # 记入窗口记录
```
- `init_db` 路径**没有 schema 撤销清单** → 备份是唯一 schema 回滚手段；保留到线上 smoke 通过。
- 磁盘：备份 351 MB + 重建峰值 ~+135 MB（486.9 MB）+ 最终 ~371 MB → **预留 ≥1.5 GB**。

### 2.2 schema 迁移（一次重建：country 8→9 + region）
```powershell
Measure-Command { & $py db\init_db.py }   # 约 9.8–10s；product 重建 9.74s（426k 行）
```
- 期望输出：`迁移 product 表：country 8 值 → 9 值（新增 HK）；region 列/country 可空: 需要`
  `迁移校验 OK：426,044 行、2 个 product 索引、3 个视图可查、foreign_key_check 0、quick_check ok`
- 迁移后立即验：
  1. `products` 仍 426,044、`product_id` 内容 hash 不变（用 `verify.py` 同口径）；
  2. `country` 枚举 9、`region` 列存在、`country` 可空；
  3. coverage 仍 **8 行**且每行数值与开窗前一致（EU/HK 尚未写）；
  4. quick ok / FK 0；
  5. DB 文件 ~486.9 MB（旧表页未回收，正常）。
- 幂等：再跑一次 `init_db` 应 0.04s 无变化（可验后继续）。

### 2.3 HK 写入（约 2.5s 事务 / 3.8s 墙钟）
```powershell
& $py etl\ingest_hk_druglist.py --apply --allow-real --db data\drugs.db `
    --manifest .tmp\hk-ingest\hk_write_manifest.json
```
- 期望：`products 13,832`、`components 21,881`、name_keys +9,596、names +13,832；`products 426,044→439,876`、`components 527,166→549,047`；quick ok / FK 0。
- coverage 变 **9 行**（HK 行 `(HK, 13832, 1641, 0, 2026-10-28)`；注意 `active=0` 因为 HK 源无 status → status='unknown'，页面需明示，不是 0 在售）。
- 备份清单：`.tmp/hk-ingest/hk_write_manifest.json`（1.6 MB）。
- 幂等：重复 `--apply` 计数不变（removed_old_products=13,832、created_name_keys=0）。

### 2.4 EMA（EU region）写入（约 2.2s 事务 / 2.7s 墙钟）
```powershell
& $py etl\ingest_ema_medicines.py --apply-products --allow-real --db data\drugs.db `
    --manifest .tmp\ema-ingest\ema_products_manifest.json
```
- **正式脚本已并入**（task-107）：`--apply-products` 写 product（`country=NULL, region='EU'`）/product_component/name；`--rollback-products` 撤销；默认拒绝真实库（`--allow-real` 才写）。
- 期望：`products 2,357`（human；active 1,566 / withdrawn 426 / unknown 364 / discontinued 1）；`components_written 2,354`（源 2,782 组件，映射 2,381，27 个无 variant）；`products_without_component 289`（仅名称/ATC/MAH/状态层）；name_keys +912、names +2,357。
- 总量：`products 439,876→442,233`、`components 549,047→551,401`；quick ok / FK 0。
- coverage 变 **10 行**：新增 `(EU, 2357, 1137, 1566, 2026-10-28)`，9 个国别行数值不变。
- 备份清单：`.tmp/ema-ingest/ema_products_manifest.json`。
- 幂等：重复 apply 计数不变（removed_old_products=2,357、created_name_keys=0）。

### 2.5 收尾检查 + VACUUM（约 7s）
```powershell
& $py db\check_data.py
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');print(c.execute('pragma quick_check').fetchone()[0]);print(len(c.execute('pragma foreign_key_check').fetchall()))"
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');c.execute('VACUUM');c.close()"   # 486.9→~370.8 MB
```
- 期望：products **442,233**、components **551,401**、substances 12,649 不变、coverage **10 行**（9 国 + EU）、DB **~370.8 MB**（估算：351.4 + HK 10.2 + EMA 9.2）。
- 记录（窗口记录/报告）：耗时、DB 大小、backup sha256、两个 manifest 路径、每步计数。
- **不要**在数据窗口内启用 markets（HK/SG/EU build 未完成）。

---

## 3. 未来 SG（组合 C）的顺序

**前置**：task-104 完成 SG 数据准备/ETL（审计：5,511 西药产品，SODL 许可，字段含规格/ATC/剂型；成分映射需复方拆分器）。

顺序（必须在同一 build/发布窗口内协调）：
1. **schema 先加 SG**：`db/schema.sql` country CHECK 9→**10**（`..., 'HK', 'SG'`）+ 头注释；`db/init_db.py` 无需改逻辑（自动按 schema 目标枚举重建）。
2. **窗口备份**（同 §2.1，文件名带 sg）。
3. **`db/init_db.py`**：重建一次（9→10，约 10s；**不会**碰 region 语义；若前一步窗口已做 region，这里只加 SG 枚举）。
4. **HK / EMA（若尚未做）** 按 §2.3/§2.4 顺序写入；若已做则跳过（幂等）。
5. **SG 写入**（ETL 就绪后）：`etl/ingest_sg_hsa.py --apply --allow-real`（预计 +5,511 products；components 视复方拆分，预估 +6–9k）；coverage 变 **11 行**（10 国 + EU）。
6. 验数/quick/FK；VACUUM；记录。
7. **markets 启用**（build.py 支持 HK/SG 后，另任务）：markets.json 加 HK/SG（enabled 按发布计划）、tests 更新（country set 10 国 + `_db_countries()` 过滤 region 行）；`lib/markets --check` + tests 全绿；再发布。
8. 注意顺序：**schema 枚举 → 数据 → build 支持 → markets 启用 → publish**；不要先启用 markets 再加数据（测试红）。

---

## 4. EMA 适配器并入正式脚本（本次完成）

### 4.1 改动
`etl/ingest_ema_medicines.py`（写范围内）新增正式模式，staging/--dry-run 行为保留：

| CLI | 行为 |
|---|---|
| `--dry-run`（默认） | 解析+映射+统计（不变） |
| `--apply` / `--rollback` | staging 原型表（不变，向后兼容） |
| **`--apply-products`** | 正式写 product/product_component/name_key/name_variant/product_name/ingest_run（region=EU、country=NULL）；单事务 + 撤销清单；需 region schema（自动检测，缺则报错）；默认拒绝真实库 |
| **`--rollback-products`** | 按 `--manifest` 撤销量（删 region=EU & source=ema_medicines 产品 + ingest_run + 本次创建的 keys/variants） |
| `--manifest` | 默认 `.tmp/ema-ingest/ema_products_manifest.json` |

- 写入细节：`product_id="EU-"+slug(EU号)`（重复自动加哈希）；`dosage_form='unknown'`、`release='none'`、strength NULL、`status` 用 EMA 状态映射（active/withdrawn/discontinued/unknown）；note 含 EMA 状态/ATC/治疗领域/授权日期/「無規格/劑型/包裝」；`source_id='ema_medicines'` 自动登记（license=EMA legal notice，data_as_of=2026-10-28）；`ingest_run` 一行。
- 组件：只写映射到现有 substance 且能找到 variant 的组件（salt-orphan 兜底逻辑与 TW/HK 同）；289 个产品无任何可挂成分（名称/ATC/MAH/状态层，build 需支持）。
- **真实库守卫**：目标为 `data/drugs.db` 且未 `--allow-real` → 拒绝（staging 与 products 模式同）。

### 4.2 副本测试（`.tmp/db-window/`）

```text
副本 = 真实库复制（426,044 / 351.4 MB / 8 枚举 / 无 region）
→ db/init_db.py：9.93s（country 8→9 + region；426,044 行/hash/索引/FK/quick 不变）
→ --apply-products：2.23s；products 2,357 / components 2,354 / 289 无成分 / name_keys +912
   coverage 10 行（EU 行 2357,1137,1566）；products 428,401、components 529,520；quick ok / FK 0
→ 幂等第二次：2.09s；removed_old_products=2,357、created_name_keys=0，计数不变
→ --rollback-products：1.44s；删 2,357 products / 912 keys / 1,612 variants；
   与迁移后基线 delta 全 0；quick ok / FK 0
```

证据：`.tmp/db-window/{init,apply_products,apply_idem,rollback,ema_dryrun}.out.txt`、`verify.py`、`verify_after_apply.out.txt`、`ema_products_manifest.json`。

---

## 5. 测试 / 启用窗口的先后（重要）

- 当前（TW 已启用、DB 8 国）→ `tests.test_markets_registry` **47/47 绿**。
- 数据窗口后（HK 写入）：DB country set = 9 国（+HK）；markets 仍只有 8 个 enabled（HK 未注册/未启用）→ `test_enabled_markets_match_db_countries` **红**（预期，非 bug）。
- EMA 写入后：`_db_countries()` 会把 region 行的 `country=NULL` 也读进集合 → 该测试还会因 `None` 红；启用窗口需同步改测试：`SELECT DISTINCT country ... WHERE country IS NOT NULL`，并在 HK/SG markets 启用后把期望国家集合更新。
- 结论：**数据窗口与 markets 启用窗口尽量相邻**；若必须先跑数据窗口，需接受短暂红并把该测试修复放进启用窗口 commit（与 task-87 同类处理）。

---

## 6. 回滚（窗口内按逆序）

| 步骤 | 命令/操作 |
|---|---|
| EMA 数据 | `& $py etl\ingest_ema_medicines.py --rollback-products --manifest .tmp\ema-ingest\ema_products_manifest.json --allow-real --db data\drugs.db` |
| HK 数据 | `& $py etl\ingest_hk_druglist.py --rollback .tmp\hk-ingest\hk_write_manifest.json --allow-real --db data\drugs.db` |
| schema（HK 枚举 + region） | **恢复开窗备份**：`Copy-Item "data\backups\drugs-before-hk-ema-window-$ts.db" data\drugs.db`（init_db 无撤销清单）；或用 `db/migrate_country_hk.py` 做本次迁移（有 manifest，可精确回滚到 8 枚举；但该脚本需与新 schema 的 CHECK 正则同步，见 §7） |
| 数据级回滚后 | 可选 VACUUM；重新跑 `db/check_data.py` / quick / FK；markets/tests 状态按 §5 处理 |

> 每一步都已单独在副本验证 delta 0；真实库按顺序执行即可。

---

## 7. 风险 / 注意

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 窗口后 `tests.test_markets_registry` 临时红（HK/SG 未启用、region NULL） | 按 §5 与启用窗口相邻执行，或接受已知红并同窗口修测试 |
| 2 | init_db 重建期间独占写锁 ~10s | 停 build/ingest/publish；失败自动回滚；先备份 |
| 3 | schema 无撤销清单 | 备份是唯一 schema 回滚；备份 sha256 记录 |
| 4 | 磁盘峰值（备份+重建 ~487MB+351MB） | 预留 ≥1.5 GB；窗口后 VACUUM 回收 |
| 5 | HK 289→? 无成分产品 / EMA 289 无成分产品 | build 任务需支持「无成分产品」展示；否则页面空行 |
| 6 | `db/migrate_country_tw.py` / `migrate_country_hk.py` 的 `CHECK_RE` 仍假设 country NOT NULL | 新 schema 下这两个旧脚本会解析失败；窗口只用 `db/init_db.py`；后续统一更新/退休旧脚本（非本任务写范围） |
| 7 | SG 数据未就绪（task-104） | C 组合等 task-104；schema 先加 SG 也可与 HK/EMA 同窗口 |
| 8 | EU region 与 HK/SG 国家混在 coverage 行 | build 需分列「国家 10 + 区域 EU」；数字口径在发布前统一（README/About） |

---

## 8. 证据

| 文件 | 内容 |
|---|---|
| `.tmp/db-window/init.out.txt` | 副本 init_db（HK 枚举 + region）日志 |
| `.tmp/db-window/apply_products.out.txt` / `apply_idem.out.txt` / `rollback.out.txt` | EMA 正式模式写入/幂等/回滚 |
| `.tmp/db-window/ema_dryrun.out.txt` | EMA dry-run（2,357 / 2,782 / 85.6%） |
| `.tmp/db-window/verify.py` / `verify_after_apply.out.txt` | 计数/coverage/FK/quick 对比 |
| `.tmp/db-window/ema_products_manifest.json` | 撤销清单（2,357 ids / 912 keys / 1,612 variants） |
| `.tmp/db-window/drugs.pristine.db` / `drugs.db` | 基线/演练副本（当前 drugs.db = 迁移+EMA 已写状态） |
| `reports/ema-ingest-prep.md` / `reports/hk-ingest-prep.md` / `reports/hk-ingest-apply.md` / `reports/eu-layer-schema.md` | 上游准备与验证 |
| `reports/sg-audit.md` | SG 审计（task-98） |

---

_本报告由并行子智能体 data-depth 生成；**未执行真实库窗口**、未改 `site/build.py` / `data/markets.json` / git / 发布。等 Lead 决定开窗时间。_
