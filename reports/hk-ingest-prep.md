# HK 入库准备（名称/成分层，副本验证）— task-88

> 日期：2026-10-28 ｜ 真实库：`data/drugs.db` **只读未写** ｜ 未改 `site/build.py` / `data/markets.json` / git / 发布
> 任务：基于 `reports/hk-mo-audit.md` 与缓存 `data/raw/hk_mo/hk_rpp_resource.xml`，实现香港「衞生署藥物辦公室 註冊藥劑製品名單」的入库 ETL + country CHECK 加 HK 迁移脚本，并在 DB **副本**上验证「迁移 → 写库 → 统计 → check_data/quick_check → 幂等 → 回滚」。
> 产物：`etl/ingest_hk_druglist.py`（新）、`db/migrate_country_hk.py`（新）、`.tmp/hk-ingest/`（证据/副本/撤销清单）、本报告。

---

## 0. 结论摘要

| 项 | 结果 |
|---|---|
| 数据源 | 衞生署藥物辦公室 DrugList.xml（data.gov.hk 数据集 `hk-dh-dh_do-hk-dh-do-pharmaceutical-product`）；**14,275 条**，`lastUpdate=2026-10-23`；字段仅 `productName / regCertHolderName / permitNo / activeIngs`；**无规格、无剂型、无注册状态、无中文名**（English only） |
| 许可 | ✅ **可再发布**（data.gov.hk Terms and Conditions：免费商用/非商用浏览/下载/分发/复制；须注明来源并承认政府及原机构知识产权）；署名与 `data_as_of` 已进 source 行 |
| `etl/ingest_hk_druglist.py` | ✅ 解析 XML → `product` / `product_component` / `name_key` / `name_variant` / `product_name` / `ingest_run`；`--dry-run/--apply/--allow-real/--rollback`；默认拒绝写真实库；幂等（source_id='hk_dh' 先删后写）+ 事务 + 撤销清单 |
| `db/migrate_country_hk.py` | ✅ product.country 枚举加 `HK`（独立脚本，dry-run/apply/rollback；副本验证 9 枚举、行数/内容 hash/索引/视图/FK/quick_check 不变） |
| 成分映射 | **token 93.8%**（22,353/23,835；DB 直配 22,331 + TW 别名表 22 + HK-BAN 0）→ 产品级 **13,832/14,275 = 96.9%** 入库 |
| 副本写入 | **13,832 products**（`HK-<permitNo>`）、**21,881 product_component**、**13,832 product_name**、+9,596 name_key、+13,461 name_variant；substance/variant **不新增**（不硬造成分） |
| 丢弃 | **443 条**（321 条无任何可挂成分 + 122 条成分匹配到 substance 但无可用 variant） |
| **缺失字段（明示）** | 全部 13,832 行：`strength_value/unit=NULL`（21,881 组件全 NULL）、`dosage_form='unknown'`、`release='none'`、`status='unknown'`；note 写「HK DrugList: 無規格/劑型/狀態」 |
| 副本完整性 | quick_check **ok**、foreign_key_check **0**；coverage 9 市场（HK 行 active=0，因 status unknown，页面需明示） |
| DB 体积（副本） | 基线 351.4 MB → HK 迁移后 486.5 MB（旧表页）→ 写库 + VACUUM 后 **361.6 MB（净 +10.2 MB）** |
| 耗时（副本，本机） | 迁移重建 **3.2s**（wall 24s 含内容 hash/快照校验）；dry-run **1.6s**；写库 **2.8s txn / 4.2s wall**；幂等重跑 2.6s；VACUUM 6.0s；数据回滚 1.5s；迁移回滚 2.9s |
| 幂等/回滚 | ✅ 第二次 apply 计数不变（`removed_old_products=13,832`、`created_name_keys=0`）；数据回滚后与基线 **delta 全 0**；迁移回滚 9→8 枚举校验通过（随后为 check_data 证据重新 apply） |
| 真实库 | ✅ 未写：products 426,044（TW 16,457）、country 枚举 8（无 HK）、无 `hk_dh` source/ingest_run、quick ok / FK 0、DB 351.4 MB |

**一句话**：HK 名称/成分层的 ETL 与 schema 迁移都已在副本验证通过（13,832 产品、成分映射 93.8%、幂等+精确回滚）；**但 HK 只有名称/成分，无规格/剂型/状态，D1 剂量对应不可用**，真实库 apply 待下一谷段批准，且真实 apply 前需同步把 `HK` 写进 `db/schema.sql`（见 §5 第 0 步，本任务写范围外）。

---

## 1. 数据源与许可

- **入口**：`http://www.drugoffice.gov.hk/eps/psi/DrugList.xml`（官方单文件；data.gov.hk 资源，4,297,930 B；仅 http）。
- **结构**（`data/raw/hk_mo/hk_rpp_resource.xml`）：
  ```xml
  <drugs>
    <lastUpdate>2026-10-23</lastUpdate>
    <drug>
      <productName>"S.T." NATURAL TEARS EYE DROPS</productName>
      <regCertHolderName>WAI LUN TRADING CO</regCertHolderName>
      <permitNo>HK-58956</permitNo>
      <activeIngs><activeIng>hypromellose</activeIng><activeIng>sodium chloride</activeIng></activeIngs>
    </drug>
    ... 14,275 条 ...
  </drugs>
  ```
- **字段覆盖**：`productName/regCertHolderName/permitNo` 100%；`activeIngs` 100%（平均 1.67 个，最多 35 个；共 23,835 个成分 token；permitNo **14,275 个全唯一**、无空值）。
- **许可结论**（详见 `reports/hk-mo-audit.md` §1.2）：data.gov.hk T&C 允许商用/非商用 **浏览、下载、分发、复制**，条件 = **注明数据来源 + 承认政府及相关机构的知识产权**；CKAN `license_title=null` 与门户 T&C 不一致，**以 T&C 为准**。
  - 本任务写入 source 行：`source_id='hk_dh'`、`license='DATA.GOV.HK Terms and Conditions（free reuse, attribution required）'`、`license_url=https://data.gov.hk/en/terms-and-conditions`、`url=数据集页(https)`、`data_as_of=2026-10-23`。
  - 站点 About/覆盖页需加署名段（build 任务）：来源 data.gov.hk / Department of Health；不暗示政府背书；原 XML 是 http，不在页面直接外链（用 data.gov.hk https 数据集页）。

---

## 2. 字段映射

| DrugList.xml | DB 目标 | 处理 |
|---|---|---|
| `permitNo`（如 `HK-58956`） | `product.product_id` / `approval_id` | `product_id = permitNo`（已含 HK- 前缀）；**14,275 个全唯一**，天然幂等键 |
| `productName`（英文全大写，可能带厂牌引号/百分比） | `name_key` + `name_variant` + `product_name(trade, primary)` | 走项目 `normalize_name.normalize()`（英文小写键；原始名保留在 name_variant.raw）；**不做中文名**（源无中文） |
| `regCertHolderName` | `product.mah` | 原文（持有人/MAH） |
| `activeIngs/activeIng` | `product_component`（每成分一行，ord=0..） | 复用 TW 的 `match_component`：DB `inn_en`(+盐) → TW 别名表（`data/tw_ingredient_aliases.csv`）→ PBS/dm+d BAN 别名 → **本脚本 HK BAN→INN 表**（paracetamol→acetaminophen、frusemide→furosemide、lignocaine→lidocaine、adrenaline→epinephrine 等 27 条）；盐/水合物拆到 variant |
| （无规格字段） | `product_component.strength_value/unit` = **NULL** | 品名里夹带的 `1%`/`500mg` 文本**不解析**（不可靠；本谷段只做名称/成分层） |
| （无剂型字段） | `product.dosage_form` = **'unknown'**，`form_base`=NULL，`route`=NULL | 页面必须明示「香港不提供剂型」 |
| （无状态字段） | `product.status` = **'unknown'**，`status_date`=NULL | 名单为「现行注册」但文件无状态列；**不假定 active/withdrawn**，note 说明；coverage view 的 active 计数会显示 0（页面用 products 计数 + 说明） |
| （无包装字段） | `pack`=NULL | — |
| （无释放机制） | `release='none'` | 无信息，不代表普通释放，页面不展示 release |
| `lastUpdate` | `source.data_as_of` / `ingest_run.note` | 2026-10-23 |

> **数据口径**：HK 产品可用于「同成分在 HK 的叫法」、U2 国家横排、同成分跨市场链接；**不能做 D1 规格对应/剂量比较**，也不能据此判断在售状态。

---

## 3. 实现说明

### 3.1 `etl/ingest_hk_druglist.py`

```text
python etl/ingest_hk_druglist.py                        # dry-run（默认全量）→ .tmp/hk-ingest/hk_drugs_dryrun.csv
python etl/ingest_hk_druglist.py --limit 500            # 小样本 dry-run
python etl/ingest_hk_druglist.py --apply --db .tmp/hk-ingest/drugs-hk.db            # 写副本
python etl/ingest_hk_druglist.py --apply --allow-real --db data/drugs.db            # Lead 正式写库
python etl/ingest_hk_druglist.py --rollback .tmp/hk-ingest/hk_write_manifest.json --db ...
```

- XML 解析：`ElementTree.iterparse` 流式（14,275 条，4.3 MB，1.6s 全量 dry-run）。
- 映射：`load_substance_map()`（DB `substance.inn_en` + `variant.salt_code`，12,573 组合）→ TW `match_component` → HK BAN 别名兜底；盐型落 variant。
- 丢弃规则：单条产品**没有任何可挂成分** → 整条丢弃计数；部分成分未匹配 → 只丢该成分，产品保留（components 只写已匹配）。
- 写库：单事务 `DELETE FROM product WHERE source_id='hk_dh'`（FK 级联）→ 插 product/product_component/名称 → 写 `ingest_run('hk_dh-<date>')`；撤销清单记录 `product_ids / created_name_keys / created_name_variants / run_id`。
- 安全：`--apply` 目标解析为 `data/drugs.db` 且无 `--allow-real` → 拒绝；写前校验 `product.country` 枚举含 `HK`；source 行自动登记（已存在则补 data_as_of）。

### 3.2 `db/migrate_country_hk.py`

- 与 `db/migrate_country_tw.py` 同构：默认 dry-run；`--apply/--rollback/--allow-real/--backup-dir/--vacuum/--manifest`。
- 从**当前 DB 的 product DDL** 派生新 DDL（country 枚举 + 'HK'），重建 product 表并保留索引/视图/FK（`legacy_alter_table=ON`）。
- 校验：行数、`product_id` 内容 SHA-256、country 分布、product 索引、视图可查、FK、quick_check；rollback 要求「无 HK 行」并把枚举还原。
- 副本实测：426,044 行重建 **3.22s**；行数/hash/索引/视图/FK/quick 全一致；9 枚举 `US/GB/CN/ES/MX/AU/CA/TW/HK`。

---

## 4. 副本验证结果

副本：`.tmp/hk-ingest/drugs-hk.db`（从**已含 TW 数据**的真实库复制：426,044 products / 351.4 MB）。

### 4.1 数量

| 指标 | 基线（真实库，TW 已在） | 副本 HK 写库后 | 变化 |
|---|---:|---:|---:|
| products | 426,044 | **439,876** | **+13,832（HK）** |
| product_component | 527,166 | **549,047** | +21,881 |
| product_name | 601,806 | **615,638** | +13,832 |
| name_key | 165,619 | **175,215** | +9,596 |
| name_variant | 179,306 | **192,767** | +13,461 |
| substance / variant | 12,649 / 13,772 | 12,649 / 13,772 | 不变（不硬造成分） |
| countries（coverage） | 8（含 TW） | **9（+HK）** | +1 |
| quick_check / FK 违规 | ok / 0 | **ok / 0** | 不变 |

HK coverage 行：`('HK', 13832, 1641, 0, '2026-10-28')` —— **active=0 是因为 status='unknown'**（源无状态字段）；构建/覆盖页需用 products 计数并明示「状态未提供」。

### 4.2 成分映射（全量 dry-run）

| 指标 | 数值 |
|---|---:|
| 产品行 / 可写 products | 14,275 / **13,954**（dry-run），最终写 **13,832** |
| 成分 token 总数 / 匹配 | 23,835 / **22,353 = 93.8%** |
| 其中 DB 直配 / TW 别名表 / HK-BAN 别名 | 22,331 / 22 / **0**（BAN 表 27 条已被既有映射/别名覆盖，未新增命中） |
| 未匹配 token（distinct / 次数） | **286** / 1,482 |
| 全部成分匹配的产品 / 有未匹配的产品 | 13,397 / 557 |
| 复方（≥2 匹配成分） | 3,567 |
| 丢弃 | 443 = 321（无任何可挂成分）+ 122（匹配到 substance 但无 variant） |

**未匹配 Top**（多为植物提取物/疫苗/兽药/外用老药，非硬造）：
`NOSCAPINE(174)`、`SQUILL LIQUID EXTRACT(173)`、`SENEGA LIQUID EXTRACT(162)`、`COCILLANA LIQUID EXTRACT(158)`、`IPECACUANHA LIQUID EXTRACT(35)`、`EUPHORBIA LIQUID EXTRACT(31)`、`BUTETAMATE CITRATE(22)`、`ENOXOLONE(20)`、`CYCLOSPORIN A(19)`、`HUMAN COAGULATION FACTOR VIII(13)`、`OXETHAZAINE(13)`、`MEGLUMINE GADOTERATE(11)`、`ACELLULAR PERTUSSIS TOXOID(10)`、`FILAMENTOUS HEMAGGLUTININ(10)`、`HUMAN FIBRINOGEN(10)`…（完整 `.tmp/hk-ingest/hk_unmatched.csv`）

**HK 产品成分 Top**：`chlorphenamine-maleate 787`、`acetaminophen 693`、`phenylephrine 557`、`caffeine 408`、`ephedrine 402`、`clotrimazole 396`、`neomycin 391`、`bromhexine-hydrochloride 369`、`codeine 331`、`diphenhydramine 277`。

### 4.3 check_data（副本）

```text
coverage: 9 行（AU/CA/CN/ES/GB/HK/MX/TW/US；HK 13832 产品 / 0 active / 2026-10-28）
products 439,876 | components 549,047 | substances 12,649（不变）| variants 13,772（不变）
name_keys 175,215 | names 615,638
collisions(severe) 18,917 → 20,170（+1,253；HK 英文名/复方名归一后碰撞增加，待 build/启用时评估）
collisions(warning) 819 → 859（+40）
quick_check ok；foreign_key_check 0
```

### 4.4 耗时 / 体积（副本，本机 SSD）

| 步骤 | 结果 |
|---|---|
| 复制真实库 → 副本 | 351.4 MB（~0.2s） |
| `db/migrate_country_hk.py --apply` | 重建 **3.22s**（wall 24.2s，含 426k 行内容 hash/快照校验）；DB 351.4 → 486.5 MB（旧表页） |
| 全量 dry-run | **1.57s**（14,275 条 → 13,954 行 CSV/统计） |
| HK 写库（`--apply`） | **2.78s txn / 4.16s wall**；DB 486.5 MB（写后，未回收） |
| 幂等第二次 apply | **2.55s txn / 3.74s wall**；`removed_old_products=13,832`、`created_name_keys=0`，计数不变 |
| VACUUM（写后） | **6.03s**；DB **361.6 MB**（相对 351.4 MB 基线净 **+10.2 MB**） |
| 数据回滚 | **1.53s**；删 13,832 products / 9,596 keys / 13,461 variants → 与基线 **delta 全 0** |
| 迁移回滚 | **2.91s**（wall 9.96s）；枚举 9→8，行数/hash/索引/视图/FK/quick 一致（随后重新 apply 以取 check_data 证据） |

---

## 5. 真实库 apply 步骤（下一谷段批准后；本任务未执行）

> **前置（重要，本任务写范围外）**：把 `'HK'` 加进 `db/schema.sql` 的 `product.country` CHECK（并让 `db/init_db.py` 的自动迁移一致），否则后续跑 `db/init_db.py` 会按旧 schema 枚举重建、在有 HK 行时失败/把枚举改回 8。建议下一任务同时改 `schema.sql` + 迁移脚本 + （未来）markets 注册。

1. **备份**：`Copy-Item data\drugs.db data\backups\drugs-before-hk-ingest-<日期>.db`（当前 351.4 MB）。
2. **schema 迁移**：`& $py db\migrate_country_hk.py --apply --allow-real --backup-dir data/backups --vacuum`
   - 约 3s 重建 + ~6s VACUUM；DB 351→486→~362 MB；9 枚举。
3. **写库**：`& $py etl\ingest_hk_druglist.py --apply --allow-real --db data/drugs.db --manifest .tmp/hk-ingest/hk_write_manifest.json`
   - 约 2.8s 事务；自动登记 `source(hk_dh)` + `ingest_run`。
4. **验数**：`& $py db\check_data.py`；`PRAGMA quick_check` / `foreign_key_check`。
   - 期望：products **426,044→439,876（+13,832）**、components **527,166→549,047（+21,881）**、substances 12,649 不变、coverage 9 行（HK 行 active=0）、DB ~362 MB。
5. **回滚**（如需要）：
   ```powershell
   & $py etl\ingest_hk_druglist.py --rollback .tmp/hk-ingest/hk_write_manifest.json --allow-real --db data/drugs.db
   & $py db\migrate_country_hk.py --rollback --allow-real --db data/drugs.db --manifest .tmp/hk-ingest/country_hk_manifest.json
   ```
   或直接恢复第 1 步备份。
6. **市场启用**：本任务不改 `data/markets.json`（禁止）；HK 的 market 注册 + build.py 支持（国家列/选择器/i18n/About 署名）属后续任务，启用时与 zh-Hant（已有）/HK 语言支持一起做。

---

## 6. 页面口径建议（给 build 任务）

1. **明示数据层**：HK 市场页/覆盖页文案固定写「香港：只提供註冊名、活性成分、持有人與註冊號；**不提供規格、劑型、註冊狀態**」；不由页面推断。
2. **D1 不可用**：HK 产品不参与「同成分剂量对应/规格比较」；TW 页已有「规格来自品名解析」提示，HK 需更强提示「无规格数据」。
3. **status=unknown**：不要显示为 withdrawn；覆盖页 HK 的「active」用 products 数（或显示「状态未提供」），避免 `coverage.active=0` 造成误解。
4. **英文名 only**：HK 无中文名，繁中/中文用户看到的是英文注册名；可链到同成分中文名（drug 页成分卡）但**不要把英文名当中文名**。
5. **署名**：About/覆盖页加「資料來源：DATA.GOV.HK / Department of Health（香港衞生署藥物辦公室）註冊藥劑製品名單；依 DATA.GOV.HK Terms and Conditions 使用，須註明來源並承認政府及相關機構知識產權；data_as_of=2026-10-23」。
6. **链接**：页面外链用 `https://data.gov.hk/en-data/dataset/hk-dh-dh_do-hk-dh-do-pharmaceutical-product`（https），不要用 http XML 直链。
7. **同名/碰撞**：HK 英文名与 US/GB 英文名归一后 severe collision +1,253；启用前抽检 Top 碰撞，必要时在结果页显示「同名不同药」徽章（沿用 collision 视图）。

---

## 7. 风险 / 缺口

| # | 风险/缺口 | 影响 | 缓解 |
|---|---|---|---|
| 1 | **无规格/剂型/状态**（源决定） | 只能做名称/成分层；D1 剂量对应不可用 | 页面明示；等未来 NHI/处方数据源再补 |
| 2 | **status=unknown → coverage active=0** | 覆盖页/统计若按 active 过滤会显示 HK 空白 | build 用 products 计数 + 明示「状态未提供」 |
| 3 | **443 条丢弃（3.1%）**：286 个未匹配 token（植物提取物/疫苗/兽药/外用老药） | 少部分产品搜不到 | 下一轮别名表可补 Top（SQUILL/SENEGA/COCILLANA 等植物提取物属合理排除；NOSCAPINE/BUTETAMATE 等可人工映射）；接受现状则注明 |
| 4 | 名称碰撞 +1,253 severe | 启用后同名不同药结果需标注 | 沿用 `collision` 视图；build 显示徽章；抽检 |
| 5 | data.gov.hk 元数据陈旧（2021） | 不能以元数据判断新鲜度 | 以 XML `lastUpdate` 为准（2026-10-23）；定期重抓 |
| 6 | http XML 源 | 页面外链不宜用 http | 用 data.gov.hk https 数据集页；本地缓存 |
| 7 | **真实库 apply 前 schema.sql 需同步加 HK**（本任务写范围外） | 旧 `init_db.py` 在有 HK 行时会失败/回退枚举 | 下一任务同时改 `db/schema.sql`；或只用 `migrate_country_hk.py` 且不再跑旧 init_db |
| 8 | 商品名夹带浓度文本（`1%`/`500mg`）不解析 | 不能当规格 | 本谷段口径就不解析；页面不展示规格 |

---

## 8. 证据 / 复现

| 文件 | 内容 |
|---|---|
| `.tmp/hk-ingest/hk_dryrun-stats.json` | 全量 dry-run 统计（映射率/未匹配 top/丢弃） |
| `.tmp/hk-ingest/hk_drugs_dryrun.csv` | 13,954 行 dry-run CSV（含 components 映射明细） |
| `.tmp/hk-ingest/hk_unmatched.csv` | 286 个未匹配成分及次数 |
| `.tmp/hk-ingest/migrate_hk*.out.txt` | country 迁移 apply/回滚日志 |
| `.tmp/hk-ingest/country_hk_manifest.json` | 迁移撤销清单（迁移前枚举/hash/快照） |
| `.tmp/hk-ingest/write_hk*.out.txt` | HK 写库/幂等日志 |
| `.tmp/hk-ingest/hk_write_manifest.json` | 写库撤销清单（product_ids/created keys/variants） |
| `.tmp/hk-ingest/verify*.out.txt` / `verify.py` | 计数/覆盖率/check_data 验证 |
| `.tmp/hk-ingest/drugs-hk.db` | DB 副本（含 HK 数据，~490 MB，可删） |
| `.tmp/hk-ingest/real_check.py` | 真实库未变确认 |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Copy-Item data\drugs.db .tmp\hk-ingest\drugs-hk.db -Force
& $py db\migrate_country_hk.py --db .tmp\hk-ingest\drugs-hk.db --apply --manifest .tmp\hk-ingest\country_hk_manifest.json
& $py etl\ingest_hk_druglist.py --apply --db .tmp\hk-ingest\drugs-hk.db --manifest .tmp\hk-ingest\hk_write_manifest.json
& $py .tmp\hk-ingest\verify.py
```

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 git / 发布 / `site/build.py`，未改 `data/markets.json`。_
