# `product.country` CHECK 迁移就绪（FR / LV / JP / KR 一次补齐）—— 副本演练报告

- 日期：北京时间 2026-11-13（本机 PT 2026-11-11 13:45–13:55）
- 任务：**task-56** ・ 工位：phaseb-data
- 范围：**只改 schema/迁移代码 + 库副本演练**。**未写 `data/drugs.db`**、未改 `site/`、未改
  `data/markets.json` / `data/languages.json`、未 commit / 未发布。
- 一句话：四国已进枚举；`init_db.py` 的既有「枚举不一致→重建表」路径**自动**覆盖（幂等）；
  新增可回滚的独立迁移工具；副本上 479,193 行原样搬迁、`integrity ok` / `FK 0` / `check_data` 逐行一致、
  回滚验证通过。

---

## 0. 结论（先行）

| 项 | 结果 |
|---|---|
| `db/schema.sql` | `product.country` CHECK 由 10 国 → **14 国**（+ FR、LV、JP、KR），EU 仍是 `region`，未混入 country |
| `db/init_db.py` | **无需新逻辑**：`build()` 已有的「DB 枚举 ≠ schema 枚举 → `_rebuild_product()`」自动生效；文档补了四国与幂等说明 |
| `db/migrate_country_check.py` | 新增：`--db/--dry-run/--apply/--manifest/--rollback/--allow-real/--backup-dir/--vacuum` |
| 副本演练（409 MB / 479,193 行） | dry-run → apply（**3.46 s**）→ 独立核对 → 再 apply 幂等 → 回滚（**3.49 s**）全过 |
| 单测 | 新增 `tests/test_country_check_migration.py` **8 tests OK**；`etl` 55 tests OK；`tests.test_markets_registry` 47 tests OK |
| 真库 | **未动**（脚本默认拒绝写 `data/drugs.db`，需 `--allow-real`） |

---

## 1. 改动清单

| 文件 | 改动 |
|---|---|
| `db/schema.sql` | `country ... IN ('US','GB','CN','ES','MX','AU','CA','TW','HK','SG',**'FR','LV','JP','KR'**)`；文件头「市场」注释补 FR/LV/JP/KR 与「枚举先行、数据后到」说明 |
| `db/init_db.py` | 仅文档：迁移列表补四国 + 说明判断依据是「枚举不一致」故幂等；尾部说明三个独立迁移脚本（tw/hk/**country_check**） |
| `db/migrate_country_check.py` | **新增**（~380 行）：目标枚举**从 schema.sql 读**（单一真相源，不硬编码）；重建 product 并校验；写撤销清单；回滚护栏 |
| `tests/test_country_check_migration.py` | **新增** 8 条断言（见 §4） |

### 1.1 迁移做了什么（与既有 `_rebuild_product` 同构）

```
BEGIN IMMEDIATE
ALTER TABLE product RENAME TO product_old          （legacy_alter_table=ON，子表 FK 不跟着改）
CREATE TABLE product ( ... 新 DDL，来自 schema.sql ... )
INSERT INTO product (公共列) SELECT 公共列 FROM product_old
DROP TABLE product_old
CREATE INDEX idx_product_country / idx_product_region   （表删了索引名才空出）
COMMIT
校验：行数 / product_id 内容 hash / country 分布 / 索引 / 视图可查 / FK / quick_check / 枚举
```

只重建 `product` 一张表；`product_component` / `product_name` / `corroboration` 的外键与数据不动，
`alias_all` / `collision` / `coverage` 三个视图仍按名字引用 `product`，迁移后逐个 `SELECT 1 ... LIMIT 1` 验证可查。

---

## 2. 副本演练（数字全部现查）

演练对象：`data/drugs.db` 的复制（`.tmp/country-mig/drugs-copy.db`，409 MB）。
**真库只被复制、从未打开写入。**

### 2.1 dry-run（`.tmp/country-mig` 前的现状）

```
当前枚举: ['US','GB','CN','ES','MX','AU','CA','TW','HK','SG']
目标枚举: [... ,'FR','LV','JP','KR']        待新增 ['FR','LV','JP','KR']
product : 479,193 行 | 分布 {None:2095, AU:44794, CA:43847, CN:145051, ES:25395,
                             GB:61051, HK:13935, MX:10878, SG:5511, TW:16457, US:110179}
索引 2 个 | 视图 3 个 | FK 违规 0 | quick_check ok
（未写库、未写 manifest）
```

### 2.2 apply（副本）

| 指标 | 迁移前 | 迁移后 |
|---|---:|---:|
| `product` 行数 | 479,193 | **479,193**（不变） |
| `product_id` 内容 hash | `a2732878dcdfff33…` | **同**（逐行一致） |
| country 分布 | 10 国 + EU 2,095 | **同**（未新增任何行） |
| country 枚举 | 10 | **14**（+FR/LV/JP/KR） |
| product 索引 | 2 | **2**（`idx_product_country` / `idx_product_region`，定义不变） |
| 视图 | 3 | **3**（均可查） |
| 重建耗时 | — | **3.46 s** |
| DB 体积（不 VACUUM） | 422.1 MB | **575.4 MB**（+153 MB ≈ 一份 product 表副本） |
| VACUUM | — | **5.60–6.21 s** → 回到 **402.6 MB**（比迁移前 422.1 MB 更小，回收了旧页） |

### 2.3 独立核对（换一个脚本，只读 + 事务内写入回滚）

```
integrity_check : ok
foreign_key_check: 0 条
product rows    : 479,193
country 枚举    : [..., 'SG', 'FR', 'LV', 'JP', 'KR']（14 个）
插入 country='FR' : OK（新枚举可用）
插入 country='XX' : 被 CHECK 拒绝 ✓  CHECK constraint failed: country IS NULL OR country IN (...)
（事务 ROLLBACK，副本行数仍 479,193）
```

### 2.4 `db/check_data.py` 前后对照

对「原始副本」与「迁移后副本」各跑一次同款体检（模块级 `DB` 指向副本，脚本零改动）：

```
check_data diff 行数: 0
（逐行完全一致）
```

→ 迁移只改 `product` 的 CHECK 约束，不改任何业务数字。

### 2.5 幂等

对已迁移副本再跑 `--apply`：`已是目标枚举（幂等）：无需迁移。`（exit 0、不重建、不写新 manifest）。
再跑一次 dry-run：`待新增 无（已是目标枚举）`。

### 2.6 回滚

| 场景 | 结果 |
|---|---|
| 库里有 1 条 `country='FR'` 行时执行 `--rollback` | **被拒绝**：`库里有新枚举市场的产品行 [('FR', 1)]，拒绝回滚（先迁走/删除这些数据，否则重建会静默丢行）`，库未被改动 ✓ |
| 删掉该行后 `--rollback` | **3.49 s**，枚举回到 10 国，行数 479,193（不变），**hash 与迁移前一致**，`integrity ok` / `FK 0` ✓ |

### 2.7 manifest 结构（撤销清单）

`.tmp/country-mig/country_check_manifest.json`：

```json
{
 "tool": "db/migrate_country_check.py",
 "db": "...\\.tmp\\country-mig\\drugs-copy.db",
 "created_at": "2026-11-11T13:46:18-08:00",
 "schema_sha256": "77460151…",
 "markets_added": ["FR", "LV", "JP", "KR"],
 "before": {"markets": [10 国], "product_rows": 479193, "product_hash": "a2732878…",
            "country_counts": {...}, "indexes": [...], "views": [...],
            "fk_violations": 0, "quick_check": "ok", "db_size": 428699648},
 "after":  {"markets": [14 国], ... "db_size": ...},
 "apply_seconds": 3.46,
 "rolled_back_at": "2026-11-11T13:48:31-08:00",
 "rollback_seconds": 3.49
}
```

回滚目标枚举取自 `manifest.before.markets`（**不依赖当时的 schema.sql**，避免“schema 又改过”导致回错）。

---

## 3. 真库窗口执行步骤（给 Lead 照抄）

> 前置：① 无 build / ingest 在跑；② 已确认 FR/LV/JP/KR 数据入库脚本就绪（FR 已过副本）；
> ③ 知道迁移会临时把 DB 写到约 **575 MB**（不 VACUUM）或 **+6 s / 回到 ~403 MB**（VACUUM）。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'; [Console]::OutputEncoding=[Text.Encoding]::UTF8

# 0) 备份 + 改前体检（AGENTS §4：单独跑迁移不自动备份）
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item data\drugs.db "data\backups\drugs-$stamp.db"
& $py db\check_data.py > ".tmp\country-mig\check_data-before-$stamp.txt"

# 1) dry-run（必须显示「待新增 ['FR','LV','JP','KR']」、行数 479,193、FK 0）
& $py db\migrate_country_check.py --allow-real

# 2) 执行（--vacuum 可选：不 VACUUM 时 DB 临时 +约一份 product 表）
& $py db\migrate_country_check.py --allow-real --backup-dir data\backups --vacuum

# 3) 核对（三条都必须过）
& $py db\check_data.py > ".tmp\country-mig\check_data-after-$stamp.txt"
#    → 与 before 逐行对比应 0 差异（迁移不改业务数字）
& $py -m unittest tests.test_country_check_migration -v
& $py db\q.py "SELECT sql FROM sqlite_master WHERE name='product'"
#    → country IN (... 'FR','LV','JP','KR')

# 4) 回滚（只在核对不过时用；要求库里没有 FR/LV/JP/KR 行）
& $py db\migrate_country_check.py --allow-real --rollback `
      --manifest .tmp\country-mig\country_check_manifest.json
```

### 3.1 窗口里的**顺序**（重要，跨任务）

1. **先迁移枚举**（本任务）→ 2. 再跑 `etl/markets/fr.py --apply` 写 FR 数据 → 3. **同批**改
   `data/markets.json`（加 FR）与 `data/languages.json`。
   理由：`tests/test_markets_registry.py::test_enabled_markets_match_db_countries` 断言
   「启用国家集合 == DB `product.country` 集合」，所以**注册表必须在数据入库的同一批改**，否则 CI 红。
   枚举先行不会让该测试变红（它比对的是 DB 行，不是 schema 枚举）。

2. 若窗口只做枚举、不写 FR 数据：DB 仍是 10 国 → 测试照常通过；本次迁移**不产生任何产品行**。

---

## 4. 单测覆盖（8 条，全绿）

`& $py -m unittest tests.test_country_check_migration -v` → **Ran 8 tests … OK**

| # | 断言 | 结果 |
|---|---|---|
| 1 | schema 枚举含 10 国 + 四国、无重复、总数 14 | ok |
| 2 | EU 不在 country 枚举里（区域层口径不变） | ok |
| 3 | `target_markets()` == schema 枚举（单一真相源） | ok |
| 4 | 全新库按 schema 建出后含四国，**第二次 build 不重建**（DDL 逐字相同） | ok |
| 5 | 老库（10 国枚举）跑 `init_db.build()` → 触发一次迁移、行集合完全保留、FK 0、integrity ok | ok |
| 6 | `migrate`：dry-run 不写库/不写 manifest → apply 生效 → 再 apply 幂等 → rollback 回 10 国、行数不变 | ok |
| 7 | 回滚护栏：有 `country='FR'` 行时 `--rollback` 必须被拒绝且不改库 | ok |
| 8 | 写 `data/drugs.db` 必须 `--allow-real`（不带时在建连之前退出，不碰真库） | ok |

回归：`etl` **55 tests OK**；`tests.test_markets_registry` **47 tests OK**（schema 变化不影响注册表测试）。

> 测试临时文件放在 `.tmp/tests-country-check/`（平铺文件）：受限沙箱里「新建子目录 + 在其中建 SQLite 文件」
> 会 `sqlite3.OperationalError: unable to open database file`，这跟迁移逻辑无关。

---

## 5. 已知缺口 / 交由 Lead 决定

| # | 事项 | 说明 |
|---|---|---|
| 1 | **未写真库** | 按任务要求；脚本默认拒绝，需 `--allow-real`（§3 给了完整步骤） |
| 2 | 迁移不写 `data/markets.json` | 越权（任务禁止），且注册表必须与数据同批；§3.1 给了顺序 |
| 3 | `country` 枚举里 FR/LV/JP/KR 目前**无数据** | 属预期（枚举先行）。`coverage` 视图不会出现空行（按 product 分组） |
| 4 | `db/migrate_country_tw.py` / `migrate_country_hk.py` 与本次工具重复 | 三个脚本共存；TW/HK 那两个是历史版本（正则只认旧的非空 CHECK）。**建议**：以后新增市场统一走 `migrate_country_check.py`（它从 schema 读目标枚举），老脚本保留不动 |
| 5 | VACUUM 期间需要独占 | 真库 400+ MB，VACUUM 实测 5.6–6.2 s，窗口内别跑 build / ingest |

---

## 6. 复现命令（全部只读或只写 `.tmp`）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'; [Console]::OutputEncoding=[Text.Encoding]::UTF8

Copy-Item data\drugs.db .tmp\country-mig\drugs-copy.db -Force
& $py db\migrate_country_check.py --db .tmp\country-mig\drugs-copy.db            # dry-run
& $py db\migrate_country_check.py --db .tmp\country-mig\drugs-copy.db --apply --vacuum
& $py .tmp\country_mig_verify.py .tmp\country-mig\drugs-copy.db                  # integrity/FK/CHECK 生效
& $py db\migrate_country_check.py --db .tmp\country-mig\drugs-copy.db --apply    # 幂等
& $py db\migrate_country_check.py --db .tmp\country-mig\drugs-copy.db --rollback --vacuum
& $py -m unittest tests.test_country_check_migration -v
```

### 附：本工位产物

| 文件 | 说明 |
|---|---|
| `db/schema.sql` | 枚举 14 国 + 注释 |
| `db/init_db.py` | 仅文档 |
| `db/migrate_country_check.py` | 新增可回滚迁移工具 |
| `tests/test_country_check_migration.py` | 新增 8 条断言 |
| `.tmp/country_mig_verify.py`、`.tmp/del_fr_row.py` | 演练辅助（不入库） |
| `.tmp/country-mig/` | 副本 / 备份 / manifest / check_data 前后快照（演练后已删副本，manifest 保留） |
