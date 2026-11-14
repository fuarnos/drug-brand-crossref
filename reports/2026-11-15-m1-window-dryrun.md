# M1 数据窗口 dry-run（CZ + LV + route 派生 + 盐基表）— 只读，不写库

- 任务：task-11（工位 **phaseb-data**）；约束：只写 `reports/`、`data/sources/*.csv`，**`data/drugs.db` 零写入**
- 现库：**507,434 产品 / 660,761 组件 / 12,740 成分 / 13 市场**（含 JP）
- 产物：`data/sources/route_rules_20261115.csv`、`data/sources/salt_map_20261115.csv`
- 明细：CZ `.tmp/cz-ingest/cz_dry_run.json`、LV `.tmp/lv-ingest/lv_dry_run.json`、route `.tmp/m1/route_plan.txt`

---

## 0. 结论（能否开窗口）

| 项 | 结论 | 关键数字 |
|---|---|---|
| **CZ** | ✅ 可入，但**要先迁移 `country` CHECK 加 CZ** | 解析 **70,032** 行；成分映射 **90.9%**；预计 **68,581 产品 / 94,066 组件**；新成分 1,079 |
| **LV** | ✅ 可入（同一次迁移顺带加 LV） | 包装级 **40,600** 行 → 注册号 18,766；成分映射 **92.3%**；ATC 100% |
| **route 派生** | ✅ 规则可填 **89.2%** 的空值，全库 route 覆盖 **49.6% → 94.8%**（差 0.2pp 到 95%） | 空 245,480 → 可填 219,069，留空 26,411 |
| **盐基表** | 🟡 40 → **68**（37 已核 + 31 有出处推算）；到 200 还差 132 个，需按 WHOCC 逐条核 | `salt_map_20261115.csv`（含折算公式/反离子 MW/WHO 出现频次） |
| **事务边界** | 建议 **3 个事务**：① CZ+LV 入库（同一次 check 迁移后）② route 回填 ③ 盐表+折算因子 | 见 §5 |
| **窗口时长（预估）** | 迁移 2-3 min · CZ 4-6 min · LV 2-3 min · route 2 min · 盐表 1 min | 合计 ~15 min + 备份/演练 |

---

## A. CZ（SÚKL DLP）dry-run

```powershell
& $py etl/markets/cz.py --dry-run      # 4.9s，只读；明细 .tmp/cz-ingest/cz_dry_run.json
```

| 指标 | 数 |
|---|---|
| 解析行数 | **70,032** 行 × 44 列（商品名去重 7,317 / 注册名去重 6,445） |
| 状态 | active 68,547 · excluded（FSMP/PZLU 非药品）1,451 · discontinued 28 · withdrawn 6 |
| 规格可数值解析 | **91.6%**（numeric 64,140 / empty 3,500 / not_numeric 2,390 / unit_unmapped 2） |
| 剂型 | form_base 覆盖 **70,030 / 70,032**（未映射 2）；top：tablet 42,372 · injection 10,542 · capsule 8,002 |
| 途径（源字段） | 可映射 **69,869 / 70,032** |
| ATC | 有 ATC **70,032**（substance 级 65,940 / group 级 4,092），覆盖 100% |
| 成分行 | **94,066** 行活性成分，覆盖 68,578 个产品；含量可数值 **94.0%** |
| **INN → substance 映射** | **90.9%**（exact 78,015 · salt 3,302 · prefix 3,202 · synonym 961 · **miss 8,586**）；**新成分 1,079** |
| EU 去重 | RC 以 `EU/` 开头 **13,385（19.1%）** → 与 EU 区域层对账后再入 |
| 预计入库 | products **68,581**（excl. 1,451）· components **94,066** · name_key 6,429 · substances_new 1,079 |

**未映射 8,586 的原因分类（按 token 频次）**：辅料/溶剂（`SODIUM (S)-LACTATE SOLUTION` 309、`SOYA-BEAN OIL` 138、
`OLIVE OIL` 108、`TRIGLYCERIDES, MEDIUM-CHAIN` 104）约 4 成；血液制品/免疫球蛋白 84；
疫苗株（`POLIOMYELITIS VIRUS TYPE 1/2, INACTIVATED` 各 80）约 1 成；维生素/原料药拼写变体（`COLECALCIFEROL` 80）；
其余为少见 INN（需新成分）。**判不了的一律不填**（辅料/溶剂/疫苗株应走 `non-substance` 或新成分两条路，窗口里二选一）。

**许可**：SÚKL 开放数据条款（可商用、须署名、不改含义），**SPC/PIL 一律不取不发布**（脚本已按此实现）。

---

## B. LV（ZVA）dry-run

```powershell
& $py etl/markets/lv.py --dry-run      # 8.1s，只读；明细 .tmp/lv-ingest/lv_dry_run.json
```

| 指标 | 数 |
|---|---|
| 源 | `HumanProducts.xml.zip` 3,034,682 B（sha256 `290dbb90c5c7…`）+ 状态码表 1,416,331 B |
| 包装级条目 | **40,600** → 注册号 **18,766**（拉语名 6,261 / 英文原名 6,266 / 成分 token 2,227） |
| 状态 | active **4,551** · 注册有效但状态未知 39,545（`unknown`，源无状态码）· 已移除 290 · 已停售 764 |
| 平行进口 | **795**（按同规则会算 active 0）· 未注册 12 |
| 成分映射 | **51,506 / 55,826 = 92.3%** |
| 规格解析 | 38,522 / 40,600 = **94.9%** · ATC 覆盖 **100%** |
| EU 去重 | LV 集中审批 1,562 个药号，与 EU 层重合 **1,561**，LV 独有 1 |

**署名文案（CC0 1.0 也照样署名）**：

> zh：数据来源：Zāļu valsts aģentūra（ZVA，拉脱维亚药品管理局）「HumanProducts」公开数据集，
> 以 **CC0 1.0** 公有领域贡献发布；本站在此致谢并按惯例署名，加工后的结果由本站负责。
> 数据截止以快照 `fetch_meta.json` 为准。en 同义。

---

## C. route 派生（最大单笔收益）

**现状**：`route` 空 **245,480 行（49.6%）**；按国家：CN 145,048 · GB 61,048 · TW 16,457 · HK 13,935 ·
AU 4,811 · EU 2,095 · US 1,922 · ES 102 · MX 62。

**做法**（`data/sources/route_rules_20261115.csv`，规则 + 命中数 + 依据 + `verdict`）：

1. `dosage_form` 文本优先（各市场 regulator 原始剂型字段，中文/英文词）；
2. `form_base` 兜底（我们自己的 ingest 口径）；
3. 商品名尾缀兜底（**只在 1/2 都给不出信号时**，标 `fill_low_confidence`）；
4. 目标词表只用库里已有写法（oral / topical / injection / ophthalmic / inhalation / rectal / nasal / dental / transdermal），**不新造枚举**；
5. 没有信号的一律不填（留空 26,411）。

**覆盖率预估**：

| 指标 | 值 |
|---|---|
| 空 route 可填 | **219,069 / 245,480 = 89.2%** |
| 全库 route 覆盖 | 261,954 → **481,023 / 507,434 = 94.8%**（差 0.2pp 到 95%） |
| 分国家可填率 | CN **99.5%** · GB **96.5%** · TW **94.7%** · ES 52.9% · MX 37.1% · US 8.9% · **AU 0.0%** |

**为什么到不了 95%**：AU 4,811 行（form_base=`unknown`、品名无剂型词）与 US 1,750 行（NDC 只有 dosage_form 泛词）
没有可信信号。**补齐路径**：AU 从 PBS/TGA 的剂型字段二次派生（另一个小任务，约 30 分钟），US 用 NDC `dosage_form` 词表映射。

**抽检 30 条**（随机，`.tmp/m1/route_plan.txt` 全文）：**29/30 正确**，唯一可疑是
`CN-XD01ACY162L00… [CN] topical | 喷雾剂 → inhalation`——`喷雾剂` 可能是外用喷雾或吸入，**属歧义**；
规则应加约束：`喷雾` 只有在 form_base=inhalation 或品名含「吸入」时才映射 inhalation，否则留空。
**修正后预计 30/30（唯一歧义条改为留空）**。

---

## D. 盐基表 40 → 68（到 200 还差 132）

`data/sources/salt_map_20261115.csv`：**68 行 = 37 已核（沿用 `salt_base_fraction.csv`）+ 31 有出处推算**。

每行字段：`salt_code / salt_en / salt_zh / category / n_counterions / counterion_mw /
fraction_rule / who_inn_hits / evidence / status / existing_in_db`。

- 折算因子公式统一写死：`f = M(base) / (M(base) + n × M(反离子))`，反离子 MW 用 **IUPAC 2021 原子量**（可由增量重算，不抄别人结果）；
- `who_inn_hits` = 该盐名在 `data/who_inn_names.csv`（WHO INN 名录快照）里出现的 INN 条数 → 作为「这个盐真实存在」的出处；
- **没有出处的不进表**：例如只在某国商品名里见过的拼写，一律不猜。

**到 200 的剩余步骤（约 1.5-2h）**：
① 从 WHO INN 名录的盐名集合补 ~80 个（`inn_en` 里带 `-ate/-ide/-ium` 的词根），逐个核对反离子 MW；
② 从 EMA 集中审批名单的 `active_substance` 里的 `(as xxx)` 补 ~30 个；
③ 从 CKD/JP 已有的 15 个 `salt_code`（`non_salt/mixed` 除外）反查 5 个缺项；④ 全部标 `status=verified` 前需 2 人复核。

**`name_spec_conflict` 832 行的误报预估**：该文件 `reason` 字段是机器规则串
（`name_token_not_in_key_spec; key_specs=…`），**没有直接标「盐型基准」**。按商品名里的盐词
（HCL/SODIUM/SULFATE/MESYLATE/DIPROPIONATE…）粗筛可判定的部分；精确数字要等盐表补到 200 后重跑
`db/consistency_audit_identity.py` 的 `name_spec_conflict` 段（**本轮不写库、不重算，避免与窗口混在一起**）。
本轮先给**方法**：盐表 → `variant.base_fraction` 非 1.0 → `strength_basis='salt'` → name/spec 比对时按
折算因子换算后再比，即可把「同一药不同盐」的假冲突摘掉。

---

## E. 窗口执行清单（等你批）

### E.1 备份 + 迁移

```powershell
# ① 备份（命名沿用现有习惯）
Copy-Item data\drugs.db data\backups\drugs-<yyyyMMdd-HHmmss>.db    # 记 sha256
# ② country CHECK 迁移：SQLite 不能 ALTER CHECK → 只能按 init_db._rebuild_product() 重建 product 表
#    幂等做法（老库直接升）：db/init_db.py 里把 CHECK 枚举加 'CZ','LV'，重跑 init_db 即触发重建
& $py db/init_db.py        # 重建 product（列拷贝 + 索引重建），老库可升、重复跑无副作用
```

**迁移方案（推荐 = 重建表，不推荐 ALTER）**：

- `ALTER TABLE` 改不了 CHECK 约束（SQLite 限制）；`db/init_db.py` 已有 `_rebuild_product()` 的成熟路径
  （拷贝数据 → 删旧表 → 改名 → 重建索引），**幂等**：只需在 `db/schema.sql` 的 `country IN (...)` 里加 `'CZ','LV'`，
  然后跑 `& $py db/init_db.py`；重跑不会丢数据（该路径 v0.4.3 起在用，TW/HK/FR 都是这么加的）。
- 迁移验收：`PRAGMA foreign_key_check` 空、`SELECT COUNT(*) FROM product` 前后一致（507,434）、
  `SELECT COUNT(*) FROM product WHERE country IN ('CZ','LV')` = 0（迁移本身不加数据）。
- **风险**：重建表期间要独占库（不能有别的会话在写）；备份先行；失败就从备份还原。

### E.2 事务边界（建议 3 个事务，各自可回滚）

| 事务 | 内容 | 预估 | 回滚 |
|---|---|---|---|
| **T1 CZ+LV 入库** | CZ 68,581 产品 + 94,066 组件 + 1,079 新成分；LV 18,766 产品 + 其组件 | 4-6 min | 按 manifest 删 product/component/substance（父→子顺序） |
| **T2 route 回填** | `UPDATE product SET route=? WHERE product_id=?`（只更新 route 为空的行；按规则表） | 1-2 min | manifest 记 old（空）→ new；回滚 `SET route=NULL` |
| **T3 盐表 + 折算因子** | `variant.base_fraction` / `strength_basis` 回填（只在有盐型依据时） | <1 min | manifest 记 (variant_id, old, new) |

理由：CZ/LV 是「新增」，route/盐表是「就地更新」——分开做，任一步失败不影响前一步的已提交结果；
**不要合成一个事务**（CZ 一旦有问题会把 route/盐表一起回滚掉，重跑成本高）。

### E.3 写后核对 SQL（before → after）

```sql
-- 产品/组件/成分
SELECT COUNT(*) FROM product;                     -- 507,434 → 594,781（+68,581 CZ +18,766 LV，减去 EU 去重）
SELECT COUNT(*) FROM product_component;           -- 660,761 → 755,xxx
SELECT COUNT(*) FROM substance;                   -- 12,740 → 13,8xx（+1,079 CZ 新成分）
-- route 覆盖
SELECT COUNT(*) FROM product WHERE route IS NULL OR route='';   -- 245,480 → 26,411
-- 字段覆盖
SELECT country, COUNT(*) FROM product GROUP BY 1;               -- 新增 CZ / LV 两行
-- 体检
PRAGMA foreign_key_check;                                       -- 必须空
& $py db/check_data.py                                          -- exit 0
```

### E.4 manifest

- `data/sources/cz_ingest_manifest_<date>.json`、`data/sources/lv_ingest_manifest_<date>.json`、
  `data/sources/route_backfill_manifest_<date>.json`、`data/sources/salt_manifest_<date>.json`
- 每个都含：tool / db / sha256_before / created_at / committed / rows（old→new 或新增 id 列表）/ counts

---

## F. 风险与红线

1. **CZ SPC/PIL 不取不发布**：脚本只读 DLP 注册数据；任何说明书文本不进库、不进站点。
2. **不改来源含义**：剂量/规格按原文存，不换算、不四舍五入；`route` 只做「给药途径」事实派生，不做剂量建议。
3. **LV CC0 仍署名**（惯例），CC0 不要求但署名更安全。
4. **route/盐型没有依据不填**：26,411 行留空 + 盐表只收有出处的 68 个；「喷雾剂」这类歧义规则改为留空。
5. **不做剂量换算、不做替代判断**：盐表只服务 `base_fraction` 的**含量基准**展示，不输出「等效剂量」。
6. **不改 `site/`**（page-slim 在做 core.json 瘦身），站点侧 JP/CZ/LV 的市场名与覆盖行由 site-ui 接。

---

## G. 本轮没做完 / 下一步

1. **盐表 68 → 200**（约 1.5-2h）：按 §D 三步补，全部标 `verified` 前两人复核。
2. **`name_spec_conflict` 误报精确降幅**：要等盐表补完 + `base_fraction` 回填后重算（本轮只给方法与公式）。
3. **AU 4,811 行的 route**：从 PBS/TGA 剂型字段二次派生（约 30 min），可把全库 route 覆盖从 94.8% 推到 ≥97%。
4. **CZ 未映射 8,586 的处置**：辅料/溶剂/疫苗株建议进 `non-substance` 规则（代码改动需批准），其余走新成分。
5. **CZ 的 EU 去重 13,385 行**：入窗前先跑一次与 EU 区域层的对账（同一药号不要重复计产品）。
