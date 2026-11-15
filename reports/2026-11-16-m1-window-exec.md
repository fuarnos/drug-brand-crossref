# M1 数据窗口执行报告（CZ + LV 入库 + route 回填）— 2026-11-16

- 任务：**task-1（工位 phaseb-data）**，唯一 DB 写窗口；执行时间 北京时间 2026-11-16 01:58–02:55
- 依据：`reports/2026-11-15-m1-window-dryrun.md` §E（执行清单 / 三事务 / 核对 SQL / 红线）
- 约束：不写 `site/`、不碰 `site/dist`、不 commit、不发布；不换算/不四舍五入；判不了的成分不写库并计数

## 0. 结论（先行）

| 项 | 结果 | 关键数字 |
|---|---|---|
| A 备份 | ✅ 可回滚 | `data/backups/drugs-20261115-095816.db` · 465,670,144 B · sha256 `4bcdbfaf…b6a575`（与写前库逐字节一致） |
| B 迁移（country CHECK + CZ） | ✅ | product 仍 **507,434**；FK 0；quick_check ok；`test_country_check_migration` **8/8 ok** |
| C CZ 入库 | ✅ | **68,581** 产品（=dry-run，偏差 0%）· 85,286 组件 · +908 成分 · source `sukl_dlp` |
| D LV 入库 | ✅ | **18,766** 产品（=dry-run，偏差 0%；40,600 包装按注册号聚合）· 21,033 组件 · source `zva_lv_register` |
| E route 回填 | ✅ | 空 **264,800 → 26,692**（覆盖率 44.4% → **95.5%**，验收线 ≤30,000）· 238,108 行 |
| F 写后核对 | ✅ | `check_data.py` **exit 0**、FK 0、**15 行市场**（14 国 + EU）、3 份 manifest 齐全 |
| T3 盐基表 | ⏸ 顺延 | 时间盒内优先 A–E；盐表未写库（原因见 §H） |
| 回滚 | ✅ 演练通过 | 三次写入的 `--rollback` 都在副本上跑过，逐表差异 0 |

## 1. 产物与清单

| 文件 | 说明 |
|---|---|
| `data/sources/cz_ingest_manifest_20261116.json` | CZ 撤销清单（68,581 product_id + 3,643 name_key + 4,449 name_variant + 908 新成分） |
| `data/sources/lv_ingest_manifest_20261116.json` | LV 撤销清单（18,766 product_id + 6,409 name_key + 11,720 name_variant） |
| `data/sources/route_backfill_manifest_20261116.json` | route 撤销清单（238,108 个 product_id，逐规则 old(NULL)→new） |
| `data/backups/drugs-20261115-095816.db` | 窗口前备份（文件名按系统本地时间 PST 2026-11-15 09:58 = 北京 11-16 00:58） |
| `etl/markets/cz.py` | 新增 `--apply / --rollback / --manifest`（三段式，照 `ingest_eu.py`） |
| `etl/markets/lv.py` | 同上；`--self-check` 断言改为「CLI 有 apply/rollback/allow-real」 |
| `etl/markets/_ingest_common.py` | CZ/LV 共用写库件（source/product/name/component/ingest_run/回滚） |
| `etl/route_backfill.py` | route 回填（`--dry-run` / `--apply` / `--rollback`，规则表驱动） |
| `db/schema.sql` | country CHECK 加 `'CZ'`（`'LV'` 早在 v0.11.3 枚举里） |
| `db/migrate_country_check.py` | `NEW_MARKETS` 同步加 `"CZ"`（回滚护栏一并覆盖 CZ 行） |
| `tests/test_country_check_migration.py` | `NEW_MARKETS` 加 `"CZ"`（枚举总数断言随之 15） |

## 2. A. 备份（写库前）

```powershell
Copy-Item data\drugs.db data\backups\drugs-20261115-095816.db
Get-FileHash data\drugs.db -Algorithm SHA256   # 与备份比对
```

| 项 | 值 |
|---|---|
| 备份路径 | `data\backups\drugs-20261115-095816.db` |
| 字节数 | **465,670,144** |
| sha256（写前 DB = 备份） | `4bcdbfafd8807bdf4b436fe4194e3b207162caa9e67d3e934ebe08c332b6a575` |
| 校验 | 备份与写前库同哈希（MATCH=True） |

## 3. B. 迁移（country CHECK 加 CZ）

`db/schema.sql` 的 `product.country` CHECK 加 `'CZ'`（LV 已在 v0.11.3 枚举中）→ `& $py db/init_db.py`。
SQLite 改不了 CHECK，走 `_rebuild_product()` 重建表（幂等，老库可直接升级）。

```text
迁移 product 表：country [...14 国] → [...15 国]（新增 CZ）；status 新增 (none)；region 列/country 可空: 已就绪
  迁移校验 OK：507,434 行、2 个 product 索引、3 个视图可查、foreign_key_check 0、quick_check ok
  重建 product 表耗时 11.00s
回填 substance.name_lang：7 行（zh 0 / en 7）      # 既有幂等迁移的顺带效果，只补 NULL 行
```

| 指标 | 迁移前 | 迁移后（重建） | 迁移后（VACUUM） |
|---|---|---|---|
| `product` 行数 | 507,434 | **507,434** | 507,434 |
| `product` WHERE country IN ('CZ','LV') | 0 | 0 | 0 |
| `PRAGMA foreign_key_check` | — | 0 条 | 0 条 |
| `PRAGMA quick_check` | ok | ok | ok |
| `data/drugs.db` 字节 | **465,670,144** | 631,947,264 | **455,770,112** |
| sha256 | `4bcdbfaf…b6a575` | — | `a8784306…7d0d41`（CZ manifest 的 before） |

**字节数为什么变**（回应 Lead 对账）：重建表的实现是「建新表 → 搬 50 万行 → 删旧表」，SQLite 先追加新页、
旧页进 freelist，所以提交后文件暂时涨到 631,947,264 B；随后 `VACUUM` 去碎片，落到 455,770,112 B
（比迁移前还小，因为迁移前库里已有空闲页）。行数、内容未变，sha256 变化只来自页布局重排。
**没有整库 VACUUM 以外的写入**；迁移本身不加任何数据行。

## 4. C. CZ 入库（SÚKL DLP）

### 4.1 副本演练 → 正式写

```powershell
Copy-Item data\drugs.db .tmp\m1\drugs-copy.db
& $py etl/markets/cz.py --apply --db .tmp/m1/drugs-copy.db            # 演练 19.1s
& $py etl/markets/cz.py --rollback --db .tmp/m1/drugs-copy.db --manifest .tmp/m1/cz_manifest_rehearsal.json
# → 逐表 diff 0（product 回到 507,434）
& $py etl/markets/cz.py --apply --allow-real --db data/drugs.db `
        --manifest data/sources/cz_ingest_manifest_20261116.json      # 正式 18.8s
```

### 4.2 before → after

| 表/指标 | 写前 | 写后 | 变化 |
|---|---|---|---|
| `product` | 507,434 | **576,015** | +68,581 |
| `product_component` | 660,761 | 746,047 | +85,286 |
| `product_name` | 683,245 | 751,864 | +68,619 |
| `name_key` | 223,950 | 227,593 | +3,643 |
| `name_variant` | 256,203 | 260,652 | +4,449 |
| `substance` | 12,740 | **13,648** | +908 |
| `variant` | 14,340 | 15,248 | +908（新成分的 base variant） |
| `source` / `ingest_run` | 43 / 21 | 44 / 22 | +1 / +1 |
| CZ 产品 | 0 | **68,581** | 与 dry-run 预估 68,581 **偏差 0%** |
| CZ 状态 | — | active 68,547 · discontinued 28 · withdrawn 6 | 同 dry-run |
| CZ route（CESTA 派生） | — | 68,455 / 68,581 = **99.8%** | 多义途径留空 184 行 |

写入口径（不猜）：

- 产品 = DLP 一行（`KOD_SUKL` 唯一）；排除 `REG ∈ {P,J}`（FSMP/PZLÚ 非药品，1,451 行）→ 70,032−1,451 = **68,581**；
- 名称：`NAZEV`（trade，primary）+ `NAZEV_REG`（不同才写，trade）；商品名不参与主键；
- 成分 = `dlp_slozeni.S='L'`，**复方缺一味就整条不写**（同 EU 层口径）；
- 强度 = `dlp_slozeni.AMNT × UN` 原文落库（`450` → `450.0 mg`，不换算、不四舍五入）；可数值 80,304 / 85,286 = 94.2%；
- 途径 = `dlp_cesty.NAZEV_EN`（EDQM）派生，**只有单一含义才填**；多义（如 Auricular/ocular、Cutaneous/inhalation）留空 184 行；
- 规格/剂型/ATC/注册号/MAH 全部按来源原文进 `note`（≤500 字），页面可溯源。

### 4.3 组件为什么是 85,286 而不是 dry-run 的 94,066（−8,780，−9.3%）

dry-run 的 94,066 是「快照里 S='L' 的**全部**活性成分行」；写库按「复方缺一味整条不写」口径后差额全部可拆：

```sql
-- 已写入（复现口径）
SELECT COUNT(*) FROM product_component pc JOIN product p ON p.product_id = pc.product_id
 WHERE p.country = 'CZ';                                  -- 85,286
SELECT COUNT(DISTINCT pc.product_id) FROM product_component pc
  JOIN product p ON p.product_id = pc.product_id WHERE p.country = 'CZ';   -- 66,473
SELECT COUNT(*) FROM product WHERE country = 'CZ';        -- 68,581（2,108 个产品无组件行）
```

| 拆项 | 行数 |
|---|---|
| 快照活性成分行合计 | 94,066 |
| 被排除产品（FSMP/PZLÚ）的活性成分行 | 0（这 1,451 行没有 S='L' 行） |
| **未写组件产品的活性成分行** | **8,780** |
| ├ 其中「判不了的非成分名」行（辅料/溶剂/疫苗株/混合物，167 个名字） | 2,376 |
| ├ 其中成分已映射但库内无可用 variant 的行 | 655 |
| ├ 其中重算时仍判不了（pending 边界）的行 | 24 |
| └ 其中同一产品里已映射的兄弟成分行（整条不写被连带） | 5,725 |
| 已写入组件行 | **85,286（= 94,066 − 8,780）** |

可复现脚本：`.tmp/m1/cz_component_gap.py`（只读快照 + 只读库，输出与上表一致）。
> 另：`.tmp/` 不入库；报告里的口径可用一次 `python etl/markets/cz.py --apply --db <副本>` 复算。

### 4.4 新成分为什么是 908 而不是 dry-run 的 1,079（−171）

| 拆项 | 数量 |
|---|---|
| dry-run 的「未映射成分英文名」去重数 | **1,079** |
| 判不了的非成分名（`SODIUM (S)-LACTATE SOLUTION` 309 行、`SOYA-BEAN OIL, REFINED` 138 行、`POLIOMYELITIS VIRUS TYPE 1/2/3` 各 80 行…） | **−167**（2,376 行，不写库并计数） |
| 去盐/水合物尾巴后与已有名字合并 | −1 |
| 与库里已有 substance 同 slug/inn_en（复用，不新建） | −3 |
| **实际新建** | **908** |

出处不是猜的：**WHO INN 名录**（`data/who_inn_names.csv`）精确命中 18 行 → 用名录写法（`confidence=high`）；
其余用 SÚKL 自己发布的英文成分名（`dlp_latky.NAZEV_EN`）去盐后建（`confidence=medium`）。
两者都写 `source_id='sukl_dlp'`、`method='imported'`、`decided_at='2026-11-11'`（`etl/markets/_ingest_common.py:ensure_substance`）。
**判不了的一律不写库**（详见 §4.3 的 2,376 行）。

### 4.5 EU 层去重口径（CZ 的 EU/ 前缀行）

- DLP 里 `RC` 以 `EU/` 开头的 **13,385 行**（19.1%）是欧盟集中审批产品在 CZ 的包装记录；
- 本窗口**保留**这些行（产品身份是「CZ 国家层包装」，与 `region='EU'` 区域层不是同一行），
  `approval_id` 存来源 `RC`（如 `07/049/69-S/C`），EU 层自身 `approval_id=EU/1/13/882`；
- **同一药号不会在生产品表里重复计**：`KOD_SUKL` 唯一（70,032/70,032），一行 = 一个注册产品+包装；
- 页面/覆盖度按「区域层 vs 国家层」分组展示（site-ui 负责），`coverage` 会把 EU 与 CZ 各算一行——
  这是**分层**，不是重复计数；报告口径以 `DISTINCT product_id` 为准。

## 5. D. LV 入库（ZVA 注册库）

### 5.1 副本演练 → 正式写

```powershell
Copy-Item data\drugs.db .tmp\m1\drugs-copy2.db
& $py etl/markets/lv.py --apply --db .tmp\m1\drugs-copy2.db          # 演练 10.5s
& $py etl/markets/lv.py --rollback --db .tmp\m1\drugs-copy2.db --manifest .tmp\m1\lv_manifest_rehearsal.json
# → 逐表 diff 0
& $py etl/markets/lv.py --apply --allow-real --db data\drugs.db `
        --manifest data\sources\lv_ingest_manifest_20261116.json     # 正式 9.1s
```

### 5.2 before → after

| 表/指标 | 写前（CZ 后） | 写后 | 变化 |
|---|---|---|---|
| `product` | 576,015 | **594,781** | +18,766 |
| `product_component` | 746,047 | 767,080 | +21,033 |
| `product_name` | 751,864 | 780,843 | +28,979 |
| `name_key` | 227,593 | 234,002 | +6,409 |
| `name_variant` | 260,652 | 272,372 | +11,720 |
| `source` / `ingest_run` | 44 / 22 | 45 / 23 | +1 / +1 |
| LV 产品 | 0 | **18,766** | 与 dry-run「注册号 18,766」**偏差 0%** |
| LV 状态 | — | active 3,832 · unknown 14,651 · discontinued 258 · withdrawn 25 | 见下 |

口径（不猜）：

- **一条 XML `<product>` 是包装级条目**：40,600 行按 `authorisation_no` 聚合 → **18,766 个产品**
  （同一药号不重复计产品；包装数写进 `note`）；
- 名称：`medicine_name`（拉语，trade/primary）+ `original_name`（英文原名，trade）+ `short_name`（colloquial）；
- 状态：**组内任一包装 active 即为 active**（其余取代表行状态词）；active 3,832 是**产品级**，
  dry-run 的 4,551 是**包装级**，两者不是同一口径（dry-run 的 38,759「只按 status 判」警告也已避开）；
- 成分：只做库里已有成分的精确映射（本轮不建新成分）；复方缺一味整条不写；
- 强度：来源 `strength` 原文解析，段数与成分数对不上就留空（19,656/21,033 = 93.5% 有强度）；
- 平行进口/未注册药品（757 个注册号）不进 active，单独在 `note` 保留程序原文。

### 5.3 组件/成分口径说明

| 指标 | 值 |
|---|---|
| 包装级成分 token（dry-run 口径） | 51,506 / 55,826 命中（92.3%） |
| 注册号聚合后 token | 24,408 · 命中 22,334（91.5%） |
| 写出组件 | 21,033（17,506 个产品；1,260 个产品因「缺一味」不写） |
| EU 重合 | LV 集中审批 1,562 个药号，与 `region='EU'` 重合 **1,561**；两层都保留，页面分组展示 |

> dry-run 的 51,506 是**包装级**累计，写库按注册号聚合后自然减少（同一药号多个包装共享同一成分串），
> 不是映射率下降（91.5% vs 92.3%，差 0.8pp 来自聚合后权重变化）。

## 6. E. route 回填（T2）

```powershell
& $py etl/route_backfill.py --dry-run                                  # 81 条规则，只读
& $py etl/route_backfill.py --apply --db .tmp\m1\drugs-copy3.db --manifest .tmp\m1\route_manifest_rehearsal.json
& $py etl/route_backfill.py --rollback --db .tmp\m1\drugs-copy3.db --manifest .tmp\m1\route_manifest_rehearsal.json
# → cleared 238,108，空值回到 264,800（逐表差异 0）
& $py etl/route_backfill.py --apply --allow-real --db data\drugs.db `
        --manifest data\sources\route_backfill_manifest_20261116.json   # 正式 17.1s
```

| 指标 | 写前 | 写后 |
|---|---|---|
| `route` 空值 | **264,800**（245,480 旧市场 + CZ 554 + LV 18,766） | **26,692**（验收线 ≤30,000） |
| 全库覆盖率 | 329,981 / 594,781 = 55.5% | **568,089 / 594,781 = 95.5%** |
| 本次回填行数 | — | **238,108** |
| 规则数 | — | 81 条（`verdict=fill/fill_low_confidence`） |

**优先级与「喷雾」歧义修正**（`etl/route_backfill.py`）：

1. `dosage_form` 文本 > `form_base` > 商品名尾缀（低置信）；
2. 只更新空值，已有 route 不动；
3. **「喷雾/噴霧 → inhalation」加条件**：仅 `form_base='inhalation'` 或品名含「吸入」才填；
4. 目标词表只用库里已有写法（oral / topical / injection / ophthalmic / inhalation / rectal / nasal / dental / transdermal）。

「喷雾」实际分布（`SELECT dosage_form, form_base, route` 核对）：

| 情形 | 行数 |
|---|---|
| 含「喷雾/噴霧」的剂型行合计 | 217 |
| 其中落 `inhalation`（21 行 form_base=inhalation + 3 行品名含「吸入」） | **24** |
| 其中落 `topical`（由 `form_base=topical` 这条独立证据填，不是按「喷雾」猜的） | 164 |
| 其中落 `nasal`（剂型含鼻喷/鼻用） | 28 |
| **光凭「喷雾」二字被猜成 inhalation 的** | **0** |
| 因该规则留空（无其它信号） | 0 |

### 6.1 抽检 30 条（随机种子 20261116，全部来自本次回填清单）

| # | 市场 | 剂型原文 | form_base | 命中规则 | route |
|---|---|---|---|---|---|
| 1 | TW | 注射劑 | injection | dosage_form~注射 | injection |
| 2 | TW | 注射劑 | injection | dosage_form~注射 | injection |
| 3 | GB | Bendroflumethiazide 3.75mg/5ml oral solu… | liquid | dosage_form~oral | oral |
| 4 | CN | 片剂 | tablet | dosage_form~片 | oral |
| 5 | TW | 內服液劑 | liquid | dosage_form~內服 | oral |
| 6 | CN | 片剂(分散片) | tablet | dosage_form~片 | oral |
| 7 | GB | Sitagliptin 50mg tablets | tablet | dosage_form~tablet | oral |
| 8 | GB | Diazepam 5mg/5ml oral solution | liquid | dosage_form~oral | oral |
| 9 | CN | 片剂 | tablet | dosage_form~片 | oral |
| 10 | CN | 胶囊剂 | capsule | dosage_form~胶囊 | oral |
| 11 | CN | 注射剂 | injection | dosage_form~注射 | injection |
| 12 | GB | Cinacalcet 60mg tablets | tablet | dosage_form~tablet | oral |
| 13 | CN | 注射剂 | injection | dosage_form~注射 | injection |
| 14 | LV | Prolonged-release capsule, hard | capsule | dosage_form~capsule | oral |
| 15 | CN | 注射剂 | injection | dosage_form~注射 | injection |
| 16 | CN | 口服混悬剂 | liquid | dosage_form~口服 | oral |
| 17 | LV | Film-coated tablet | tablet | dosage_form~tablet | oral |
| 18 | GB | Deferiprone 500mg tablets | tablet | dosage_form~tablet | oral |
| 19 | GB | Diazoxide 100mg/5ml oral solution | liquid | dosage_form~oral | oral |
| 20 | CN | 胶囊剂 | capsule | dosage_form~胶囊 | oral |
| 21 | CN | 片剂 | tablet | dosage_form~片 | oral |
| 22 | GB | Oxycodone 40mg modified-release tablets | tablet | dosage_form~tablet | oral |
| 23 | CN | 片剂 | tablet | dosage_form~片 | oral |
| 24 | CN | 胶囊剂 | capsule | dosage_form~胶囊 | oral |
| 25 | LV | Prolonged-release tablet | tablet | dosage_form~tablet | oral |
| 26 | GB | Lisinopril 20mg / Hydrochlorothiazide 12… | tablet | dosage_form~tablet | oral |
| 27 | CN | 胶囊剂 | capsule | dosage_form~胶囊 | oral |
| 28 | CN | 片剂 | tablet | dosage_form~片 | oral |
| 29 | CN | 胶囊剂 | capsule | dosage_form~胶囊 | oral |
| 30 | CN | 片剂 | tablet | dosage_form~片 | oral |

**30/30 与剂型原文一致**（本次样本落在 oral / injection 两个大类，明细全文见 `.tmp/m1/summary.json`）。
route 只做「给药途径」事实派生，**不涉及剂量、不涉及可替代性判断**。

## 7. F. 写后核对

```text
& $py db/check_data.py        → exit 0
PRAGMA foreign_key_check      → 0 行
PRAGMA quick_check            → ok
SELECT COALESCE(country,region), COUNT(*) FROM product GROUP BY 1  → 15 行
```

| 市场 | 产品数 | 市场 | 产品数 |
|---|---|---|---|
| CN | 145,051 | FR | 15,799 |
| US | 110,179 | **CZ（新）** | **68,581** |
| GB | 61,051 | HK | 13,935 |
| AU | 44,794 | JP | 12,442 |
| CA | 43,847 | **LV（新）** | **18,766** |
| ES | 25,395 | MX | 10,878 |
| TW | 16,457 | SG | 5,511 |
| EU（区域层） | 2,095 | **合计** | **594,781** |

| 核对项 | 结果 |
|---|---|
| `check_data.py` | **exit 0** |
| `foreign_key_check` / `quick_check` | 0 / ok |
| 市场行数 | **15**（14 国 + EU） |
| route 空值 | 26,692（≤30,000） |
| `data/drugs.db` 字节 | 455,770,112（迁移后）→ **558,039,040**（+CZ/LV/route） |
| 库 sha256 | CZ 后 `3e6dae9a…` · LV 后 `c711b2a1…` · route 后 **`b6182140b4546524eb37f98d06bd937bd9313e945ec7bd1b73fb8e3dd76a3c0d`** |
| 测试 | `tests.test_country_check_migration` **8/8 ok**（NEW_MARKETS 加 CZ 后枚举 15）· `etl` 55 tests ok · `lib` 61 tests ok |

## 8. T3 盐基表：本轮**未写库**（顺延）

- 时间盒优先 A–D（备份→迁移→CZ+LV→route）已在 05:00 前完成；T3 在派单里标注「有余力才做」；
- `data/sources/salt_map_20261115.csv`（68 行 = 37 已核 + 31 有出处推算）已就绪，但**只写 `variant.base_fraction`/
  `strength_basis` 且必须有出处**，dry-run 报告要求 `verified` 前两人复核——单人工位窗口内不冒险写；
- 下一窗口执行：`etl/apply_salt_fractions.py` 的既有路径 + 盐表 68 行，manifest 记 `(variant_id, old, new)`；
- 红线不变：盐表只服务「含量基准」展示，**不输出等效剂量、不做剂量换算**。

## 9. 回滚手册（任一步出问题）

```powershell
# ① 按 manifest 精确回滚（推荐；只删本次写入的行）
& $py etl/route_backfill.py --rollback --allow-real --db data\drugs.db `
      --manifest data\sources\route_backfill_manifest_20261116.json
& $py etl/markets/lv.py --rollback --allow-real --db data\drugs.db `
      --manifest data\sources\lv_ingest_manifest_20261116.json
& $py etl/markets/cz.py --rollback --allow-real --db data\drugs.db `
      --manifest data\sources\cz_ingest_manifest_20261116.json
# ② 或整库恢复备份（回滚到窗口前）
Copy-Item data\backups\drugs-20261115-095816.db data\drugs.db
# 校验：product 应为 507,434 / CZ+LV 0 行 / route 空值 245,480 / FK 0
```

三次 `--rollback` 都已在副本上实测：CZ 删 68,581 产品 + 908 成分，LV 删 18,766 产品，
route 清 238,108 行 → 逐表计数全部回到写前基线（diff 0）。

## 10. 已知缺口 / 下一步

1. **T3 盐基表**（§8）顺延；`name_spec_conflict` 误报降幅要等盐表回填后重算。
2. **CZ 2,108 个产品暂无组件行**（§4.3）：其中 167 个非成分名需要「excipient/non-substance 规则」或人工复核，
   才能把 2,376 行活性成分接上；这是一次代码/规则改动，适合单独任务。
3. **CZ route 184 行多义途径留空**、LV route 188 行无信号留空；AU 4,811 行与 US 1,750 行仍无 route（旧缺口）。
4. **站点侧**：CZ/LV 的市场名、覆盖行、`data/markets.json` 校验、三语页面由 site-ui / phaseb-plan 接；
   本工位未写 `site/`、未跑 build。
5. **计数口径**（README / About / CHANGELOG / coverage）需要按 §7 的新数字统一更新（product 594,781、15 市场、成分 13,648）——
   这是发布前的事，归 Lead 的发布流程。

## 11. 复现命令清单

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 备份
Copy-Item data\drugs.db data\backups\drugs-<yyyyMMdd-HHmmss>.db
# 迁移（幂等）
& $py db/init_db.py
# CZ / LV（副本演练加 --db，正式写加 --allow-real）
& $py etl/markets/cz.py --apply --allow-real --db data\drugs.db --manifest data\sources\cz_ingest_manifest_20261116.json
& $py etl/markets/lv.py --apply --allow-real --db data\drugs.db --manifest data\sources\lv_ingest_manifest_20261116.json
# route
& $py etl/route_backfill.py --dry-run
& $py etl/route_backfill.py --apply --allow-real --db data\drugs.db --manifest data\sources\route_backfill_manifest_20261116.json
# 验收
& $py db/check_data.py
& $py -m unittest tests.test_country_check_migration -v
```

## 12. 红线确认

- ✅ 未写 `site/`、未碰 `site/dist`、未 commit、未发布；
- ✅ 商品名只进 `name_key`/`name_variant`/`product_name`，产品唯一性仍是「国家 × 剂型 × 规格 × 成分」；
- ✅ 规格/强度全部按来源原文落库（不换算、不四舍五入）；
- ✅ 判不了的成分不写库并计数（CZ 167 个名字 / 2,376 行；LV 未建新成分）；
- ✅ 不给用药建议、不做剂量换算、不判断可互换；route 只做「给药途径」事实派生；
- ✅ 唯一 DB 写窗口：三次写入串行，未与其它入库并行。
