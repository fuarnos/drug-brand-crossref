# EMA（EU 层）数据源与许可评估（task-17）

> 日期：2026-11-07（北京）｜状态：**只读研究**，未写 `data/drugs.db`、未改代码/site、未 commit、未发布
> 范围：评估把「欧盟集中审批（EMA/EC）」作为**区域层**接进本站的可行性；10 个现有市场（US/GB/CA/AU/ES/MX/CN/TW/SG/HK）不动
> 前置事实（本仓库已有）：`reports/ema-ingest-prep.md`（task-97：数据/许可/映射实测）、`reports/eu-layer-schema.md`（task-102：region 建模 + 副本入库验证）——本报告不复算，只做**当轮复核 + 拍板**
> 基线（现查）：477,098 产品 / 628,013 组件 / 12,649 成分 / 202,092 name_key / dist 121,280 文件 885.6 MB / sitemap 63,351 URL / 单次构建 178.7 s

## 0. 结论（先看这段）

**建议接入，但按「区域层 `region='EU'`」接入，不当作第 11 个国家市场。** 分两步走：

| 步 | 内容 | 改库？ | 工作量 |
|---|---|---|---|
| 第一步（低风险） | EU 只做**只读事实层**：覆盖页 1 行 + 成分页「EU 集中审批」名称区；数据来自 `data/sources/ema-*.csv` 小快照 | 否 | 0.5–1 人日 |
| 第二步（正式层） | 写 `product.region='EU'`（schema 已就绪）+ build/UI 的 region 渲染 + 计数口径 | 是（+2,357 产品级，副本已验证） | 1.5–2.5 人日 |

四条前置条件（缺一条不进第二步）：

1. **许可登记先行**：`docs/许可清单.md` 加 2 行（EMA ✅ 署名即可 / EC Union Register CC BY 4.0），About 四语署名同步——按仓库纪律先改登记再上线。
2. **口径拍板**：只取 `Centrally authorised` + `Human`；「授权有效 ≠ 各国在售」必须写进页面；**不生成 2,357 个名字页**（只做覆盖页 + 成分页区）。
3. **markets.json 路线拍板**：现校验规则是「enabled 的 region 至少要有 1 个 enabled 子市场（`parent:"EU"`）」，而 ES 等成员国目前 `parent:null`。要么给成员国挂 `parent:"EU"`，要么把 EU 只当**数据层**（`markets.json` 保持 disabled）——这条必须先定，否则后台校验会挡住。
4. **构建口径同步**：`coverage` 多一行 EU 后，About/README/CHANGELOG 的「10 国」要改成「10 国 + EU 区域」（AGENTS §4 计数口径统一）。

**不建议**：把 EU 写进 `product.country`（会污染国家下拉/国家统计）；把 EMA 的 annex PDF（SmPC 正文）当数据源抓规格；把 Union Register 里 551 行 `Nationally authorised` 混进 EU 层。

## 1. 数据源：有机器可读批量，且有两条互补路径（2026-11-07 复核）

| 源 | 形式 | 实测体积 | 数据规模 | 更新频率 | 可用性 |
|---|---|---:|---|---|---|
| **EMA medicines XLSX**（[下载页](https://www.ema.europa.eu/en/medicines/download-medicine-data)） | `.xlsx`，39 个有效字段 | 906,336 B | **2,757 行**（Human 2,357 / Vet 400；Authorised 1,872 含兽药，human 1,564） | **每晚重生成**（本文件生成时间 `06/11/2026 - 18:00`，HTTP Last-Modified `2026-11-06 17:00 GMT`） | ✅ 已实现 ETL（`etl/ingest_ema_medicines.py`），映射率实测 85.6% |
| **EMA medicines JSON**（[JSON 数据页](https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format)） | `.json`，字段同 XLSX + 更新时间头 | 6,804,166 B | 同上 | **每天 2 次，06:00 / 18:00 CET** | ✅ 自动抓取首选，无需解析 xlsx |
| **EC Union Register ODS**（[注册表首页](https://ec.europa.eu/health/documents/community-register/html/index_en.htm) → [`ods_products.json`](https://ec.europa.eu/health/documents/community-register/ods/ods_products.json)） | `.json`，18 个顶层字段（含多语言数组） | 16,768,535 B | **6,476 行**：Human 中心授权 **2,095**、Human 国家授权 551、Vet 中心 375、Vet 国家 127、孤儿药登记 3,328 | 快照式（本份 **2026-11-03**），页面注明「定期发布」，BETA | ✅ 官方**法律**注册表；许可最干净（CC BY 4.0） |
| Union Register HTML（`reg_hum_act.htm` 等） | HTML 表 | — | 同上 | 实时 | ❌ 不抓；有 JSON 就不必解析 HTML |
| EU Open Data Portal（data.europa.eu） | 数据集 | — | — | Union Register 页注明「BETA 结束后同步到欧洲数据门户」 | ⏳ 可用 Union Register ODS 先顶上 |
| EPAR 页（`/en/medicines/human/EPAR/<slug>`） | 页面/PDF | — | = XLSX 的 `medicine_url` | 随药品更新 | ❌ 只做「链回原文」，不解析 PDF 正文 |

**两个源的差**（同一时点，Human）：

| 指标 | EMA XLSX（2026-11-06，human 2,357 行） | Union Register ODS（2026-11-03，human 中心授权 2,095 行） |
|---|---:|---:|
| Human 行数 | 2,357（含申请中/意见/撤回申请） | 2,095（只含已作决定的） |
| 状态 | Authorised 1,564 / Withdrawn 375 / Application withdrawn 268 / Refused 65 / Lapsed 27 / Opinion 26 / Expired 17 / Revoked 10 / Opinion under re-examination 2 / Withdrawn from rolling review 2 / Suspended 1 | Active 1,547 / Withdrawn 394 / Refused 85 / Expired 30 / Not renewed 26 / Revoked 11 / Annulled 1 / Suspended 1 |
| 两源行数差 262 | — | EMA 侧 298 行「未决申请/意见」（Application withdrawn 268 + Opinion 26 + Opinion under re-examination 2 + rolling review 2）UR 本来就不收；UR 侧把 Lapsed/Expired/Not renewed 拆得更细（合计 56 行 vs EMA 的 44 行）。→ **ETL 以单源为准，不做两源合并计数** |
| EU 号 | `EMA product number` 100% | 96.4% |
| ATC | human 2,224/2,357 = **94.4%** | **98.2%** |
| MAH | 87.3%（developer/applicant/holder 混在一列） | **100%**（单列 + 地址） |
| 成分 | `active_substance` 2,278/2,357 = 96.6% | 99.9% |
| INN / 治疗领域 | 有（INN、MeSH） | 无 INN；有 Indication 全文 |
| 规格 / 剂型 | **无** | **无** |

结论：**EMA JSON 当主源**（最新、有 INN、ETL 已通），**Union Register ODS 当对账/补漏**（EU 号、ATC、MAH 覆盖更高，且 CC BY 4.0）。两源都**没有 strength / pharmaceutical form**——EU 层天生做不了 D1 剂量对应（与 task-97 结论一致，本轮复核确认）。

## 2. 字段映射到 `product / product_component / variant / substance`

| 源字段（EMA / UR） | 目标字段 | 结论 |
|---|---|---|
| `name_of_medicine` / `Name` | `product_name(name_type='trade')` + `name_key`/`name_variant` | ✅ 直接建（2,357 品牌名，重名 12 个需靠 EU 号区分） |
| `ema_product_number` / `EUNumber` | `product.approval_id` | ✅ 唯一键（EU/1/13/882 形式） |
| `active_substance` / `ActiveSubstance` | `product_component → variant → substance` | ⚠️ 映射率 **85.6%**（task-97 实测：2,381/2,782 组件；401 未映射主要是疫苗/生物制品/基因治疗）；剩 289 个产品无任何可挂成分 |
| `atc_code_human` / `ATC[].Code` | `substance.atc`（仅补空缺，不覆盖现有） | ✅ 98.2%（UR）；ATC 只到成分层，EU 行自身不新增 ATC 口径 |
| `marketing_authorisation_developer_applicant_holder` / `MAH.Name` | `product.mah` | ✅ 99–100%；注意 EMA 那列混了 developer/applicant/holder，页面要标「持有人/申请人（EMA 字段）」 |
| `medicine_status` / `Status` | `product.status` | ⚠️ 枚举只到 `active / discontinued / withdrawn / unknown`：Authorised·Active→`active`；Withdrawn/Revoked/Annulled→`withdrawn`；Refused/Application withdrawn/Opinion/Lapsed/Expired/Not renewed→`unknown`（**不臆造**，页面按原文显示状态） |
| `european_commission_decision_date` / `AuthorisationDate` | `product.status_date` | ✅ 95–100%（用授权日期，语义要写清「授权日」不是「在售日」） |
| `medicine_url` / `EMALink` / `URI` | `product.source_url` | ✅ 必须保留（链回原文，站点纪律） |
| — （两源都无） | `product.dosage_form`（NOT NULL） | 🔴 **只能写 `'unknown'`**，页面显示「剂型未收录」 |
| — | `variant.strength_value / strength_unit` | 🔴 **没有**：EU 行不产生规格，矩阵里显示「not disclosed」 |
| — | `product.country` | ✅ 必须 NULL；`region='EU'`（schema 已加 XOR CHECK） |
| `Type/Category` | （过滤条件） | ✅ 只收 `Type='Human'` + `Category='Centrally authorised'`；UR 的 551 行国家授权是**成员国**数据，不进 EU 层 |

口径行（建议直接作为页面文案，四语）：
> 「EU 集中审批（EMA）· 欧盟层授权，非某一国家的在售记录；EMA/EC 数据不含规格、剂型、包装。」

## 3. 许可：属于**第一档 ✅ 可再发布**，和那 8 个 `non_redistributable` 完全不同

### 3.1 EMA（本轮复核原文）

[EMA Legal notice](https://www.ema.europa.eu/en/about-us/about-website/legal-notice)（2026-11-07 抓取）：

> "Information and documents made available on EMA's webpages are public and may be reproduced and / or distributed, totally or in part, irrespective of the means and / or the formats used, **for non-commercial and commercial purposes**, provided that **EMA is always acknowledged as the source** of the material. Such acknowledgement must be included in each copy of the material."
> "Citations may be made from such material without prior permission, provided the source is always acknowledged."

例外（必须遵守）：第三方版权内容、非 EMA 版权的照片/材料不在此许可内；**EMA 标志属 EMA 专有，未经书面许可不得使用**；不得暗示 EMA 背书。

### 3.2 EC Union Register（本轮复核）

[Union Register 首页](https://ec.europa.eu/health/documents/community-register/html/index_en.htm) 明写：数据集 **Licence: Creative Commons Attribution 4.0 International（CC BY 4.0）**，当前 BETA，定期发布。

### 3.3 与 `docs/许可清单.md` 对照

`docs/许可清单.md` 的 4 档：✅ 可再发布（CC0/CC BY/OGL/美国政府作品，须署名+许可链接）／🟡 条件性待确认（只发事实字段）／🔴 仅事实+链接／⚪ 未接入。

| 对照对象 | 档位 | 意味着 |
|---|---|---|
| **EMA medicines（legal notice）** | **✅ 可再发布**（署名即可，商用/非商用都行；无 NC、无 SA） | 可存结构化字段 + 页面展示派生结果；义务 = 每份内容署名 EMA + 许可链接；不转载 PDF 正文、不用 logo |
| **EC Union Register（CC BY 4.0）** | **✅ 可再发布**（最干净） | 同上，署名 EC/Union Register + CC BY 4.0 链接 |
| 现有 8 个 `non_redistributable`（build.py 数据包口径：`artg_detail`/`artg_enrich`/`artg_export`/`cofepris_mx`/`manual_seed`/`nhsa`/`pbs`/`tga_cmi`） | 🔴/🟡 | 只能发事实字段 + 链回原文，不发原表 |
| `openfda_ndc`（美国政府作品）、`dmd`（OGL v3.0）、`hsa_sg`（SODL）、`tfda_tw`（OGDL） | ✅ | 与 EMA/EC **同档** |

→ **EMA/EC 是本轮所有候选里许可最干净的一档**；不需要逐次申请、无费用、无 NC/SA 传染。

### 3.4 落地时该加的东西

- `source` 行：`source_id=ema_medicines`，`license="© European Medicines Agency; re-use permitted with acknowledgement (EMA legal notice)"`，`license_url=https://www.ema.europa.eu/en/about-us/about-website/legal-notice`，`data_as_of=<抓取日>`；若同时用 UR：`source_id=ec_union_register`，`license="CC BY 4.0"`，`license_url=https://creativecommons.org/licenses/by/4.0/`。
- About「数据来源与覆盖」四语署名（en/es/zh/zh-Hant）：「Source: European Medicines Agency (EMA) / Fuente: EMA / 来源：欧洲药品管理局（EMA）」+ 许可链接；不得使用 EMA logo。
- 页脚/成分页 EU 区块各给一次署名（「每份内容都要有」）。

## 4. 规模与构建影响（按现网基线估算）

| 项 | 数值 | 说明 |
|---|---|---|
| 新 products | **+2,095 ~ +2,357** | UR 2,095（只算已决定）/ EMA human 2,357；占现有 477,098 的 **0.44%–0.49%** |
| 新 components | **+~2,354** | 映射成功的组件（task-102 副本实测） |
| 新 name_key / 名字页 | **+912** | task-102 实测；若每个新 key 都建页 → +912 页 |
| dist 体积 | **+~3.8 MB（+0.42%）** | 名字页均值 **4,126 B**（77,058 页 / 317.9 MB）；912 × 4.1 KB ≈ 3.8 MB |
| core.json（检索索引） | +~0.2 MB（+0.5%） | 195,553 条 → +~912 条 |
| sitemap | +~912 URL（63,351 → ~64,263，+1.4%） | 单包装名字页是 noindex，实际增量可能更少 |
| 构建时间 | +1~2 s（178.7 s → ~180 s，+1%） | 名字页占构建大头；912 页 ≈ 名字页总量的 1.2% |
| **DB 体积** | **+9.2 MB**（351.4 → 361.0 MB，VACUUM 后） | task-102 副本实测（当时库 426k 产品；现 477k，比例不变） |

**页面策略会显著改变体积**：若**不建** EU 名字页（只在成分页列出 EU 名称 + 覆盖页一行），dist 增量 ≈ **+0.1 MB**（只有覆盖页/成分页变大），sitemap 不变。→ 推荐先走这条。

## 5. 接入方案：`region='EU'` 怎么用，选择器怎么显示

### 5.1 库里已经就绪（现查，0 行 EU 数据）

| 现状 | 说明 |
|---|---|
| `product.region` 列 + `CHECK (region IS NULL OR region IN ('EU'))` + XOR CHECK（country/region 二选一） | ✅ 已迁移，`SUM(region IS NOT NULL)=0` |
| `coverage` 视图 `GROUP BY COALESCE(country, region)` | ✅ EU 会单独一行，10 国行不变 |
| `market` 表（`code/kind/parent`） | ❌ 尚未建（`docs/市场扩展接口.md` §5 的远景方案） |
| `markets.json` EU 占位 | ✅ `{"code":"EU","kind":"region","parent":null,"enabled":false,"source_id":null,"order":90}` |
| `languages.json` | ✅ de/fr/it/nl/pl/pt 全 disabled（`region:"EU"`）；EMA 名称是英文，**接入 EU 层不需要动语言** |

### 5.2 页面/选择器口径（建议）

- **国家下拉（首页/结果页）只放 `kind='country'`**：`site/build.py` 现有 `COUNTRY_PRIORITY = (US,GB,CA,AU,SG,CN,ES,MX,TW,HK)` 与 `SHELL_MARKETS`，EU **不加入**。
- **EU 出现在三个地方**：① 覆盖页新增一行「EU · EMA 集中审批（region）」；② 成分页（drug 页）新增「EU 集中审批」名称区（品牌名 + EU 号 + MAH + 状态 + 链 EMA）；③ 结果页该成分的 chip 加 `data-region="EU"` 标记（不混进国家 chips）。
- **文案已经是 region-ready**：站内 i18n 现有键 `home.all = "All countries and regions"`、`Coverage (countries and regions)`、`Countries & regions`——不用新造词。
- **不承诺**：规格、剂型、包装、价格、各国在售状态；不进矩阵首屏的剂量比较。

### 5.3 markets.json 的两条路线（需拍板）

| 路线 | 做法 | 代价 |
|---|---|---|
| **A（推荐先做）** | EU 在 `markets.json` 保持 `enabled:false`，只当**数据层**（`product.region='EU'`）+ 覆盖页/成分页展示 | 不动校验规则；`lib/markets.py` 的「enabled region 需有 enabled 子市场」不触发 |
| B（未来） | 给 ES（及未来 DE/FR/IT…）加 `"parent":"EU"`，再把 EU `enabled:true`、`source_id:"ema_medicines"` | 要同时改 `markets.json` 校验、`lib/markets.py`、build 的国家列表；适合真正做「EU 导航页」时 |

## 6. 风险（按影响排序）

| # | 风险 | 影响 | 缓解 |
|---:|---|---|---|
| 1 | **EU 与国家层重复**：ES 的 25,395 条 CIMA 产品里不少就是集中审批药（Keytruda 等），同一药会出现「ES 行 + EU 行」 | 结果页看起来像重复；用户可能以为 EU 是一个国家 | 页面标 `region`；结果页分组「国家 / 区域」；文档写清「EU 是授权层，不是市场」 |
| 2 | **中心授权 ≠ 在售** | 用户以为 EU 有货 | 页面文案固定句；状态列只显示授权状态原文 |
| 3 | **UR 混入国家授权（551 Human + 127 Vet）** | 口径污染，EU 层变成「欧盟各国」大杂烩 | ETL 只收 `Type='Human' AND Category='Centrally authorised'`；加断言。**互认/分散程序（MRP/DCP）授权也属成员国授权**，在 UR 里同样落在 `Nationally authorised`——要接它们只能按国家逐个接（未来 DE/FR/IT 国家库），不进 EU 层 |
| 4 | **无规格/剂型** | 不能做剂量对应；矩阵空 | `dosage_form='unknown'`、strength NULL；页面明示；不臆造 |
| 5 | **成分映射 85.6%**（401 组件未映射，289 产品无成分） | 成分页无法挂 EU 名称 | 允许「成分原文不可点」；生物制品/疫苗另建 substance（另任务） |
| 6 | **计数口径漂移**：coverage 多一行 | About/README「10 国」「477,098 产品」会不一致 | 上线同窗口改文案：国家 10 + 区域 1，产品数写清含 EU |
| 7 | **许可误用**：annex PDF / EMA logo | 侵权风险 | 只存事实字段 + 链接；不用 logo；每份内容署名 |
| 8 | **数据源漂移**：UR 是 BETA，快照不定期；EMA XLSX 每晚重生 | 版本不可追溯 | 记录 `data_as_of` + 文件 sha256（本报告已存：ODS `84ABDD66…`、XLSX `35770DA9…`）；ETL 做变更检测 |
| 9 | **状态枚举丢失**：`Refused/Opinion/Lapsed` 等映射到 `unknown` | 页面显示「未收录状态」 | 页面按源原文显示状态徽标；`unknown` 只表示「本站未映射」 |
| 10 | **markets.json 校验规则**（enabled region 需 enabled 子市场）与「EU 只做数据层」冲突 | 启用 EU 时被后台校验挡住 | 走 §5.3 路线 A；真要启用按 B 一并改校验 |
| 11 | **地理范围误读**：EMA 中心授权覆盖 EU/EEA，**不含英国（GB）**；GB 现有 dm+d 数据独立 | 用户以为「EU 层」= 欧洲含英国 | 页面写「EU/EEA（不含 GB，英国见 GB 数据）」；GB 的 EU 药可能另有 UK 授权记录，属不同批次 |

## 7. 三条可执行下一步

1. **定口径 + 真数据 dry-run（只读，0.5 人日）**
   `python etl/ingest_ema_medicines.py --dry-run`（用今天抓的 `2026-11-06` XLSX 或 JSON）→ 产出 human/authorised 的产品数、成分映射率、状态分布到 `.tmp/ema/`；再与 Union Register ODS 的 2,095 行对账，写清「262 行差」构成（申请中/意见/撤回申请）。产出 `reports/ema-scope-20261108.md`。
2. **许可登记 + 署名草案（0.5 人日，先于任何写库）**
   `docs/许可清单.md` 增 `ema_medicines`（✅ 署名即可）与 `ec_union_register`（CC BY 4.0）两行；给出 `source` 行参数、About 四语署名与页面级署名位置（覆盖页 / 成分页 EU 区 / 页脚）；按 AGENTS §6 先问人再改公开口径。
3. **build/UI 接入任务（1.5–2.5 人日，需先拍 §5.3 路线）**
   覆盖页 EU 行 + 成分页 EU 名称区 + 结果页 region chip；**默认不建 EU 名字页**；同步 About/README 计数口径（10 国 + EU 区域、产品数含 EU）与 `db/check_data.py` 输出；验收按 AGENTS §5：全量建站到 `== done ==` + 三语抽查 + 页数/体积回归。

## 8. 来源（2026-11-07 抓取/复核）

- EMA · Download medicine data（XLSX 表 + 每晚重生成说明）<https://www.ema.europa.eu/en/medicines/download-medicine-data>
- EMA · Download website data in JSON data format（每天 06:00/18:00 CET 更新，字段清单）<https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format>
- EMA · Legal notice（可复制/再分发 + 署名义务 + 例外/logo）<https://www.ema.europa.eu/en/about-us/about-website/legal-notice>
- EMA medicines JSON 文件本体（6,804,166 B，Last-Modified 2026-11-06 17:00 GMT）<https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json>
- EMA medicines XLSX 文件本体（906,336 B，生成时间 06/11/2026 18:00）<https://www.ema.europa.eu/en/documents/report/medicines-output-medicines-report_en.xlsx>
- EC · Union Register of medicinal products（数据集入口 + **CC BY 4.0** + BETA 说明）<https://ec.europa.eu/health/documents/community-register/html/index_en.htm>
- EC · Union Register 数据集本体（16,768,535 B，2026-11-03 快照）<https://ec.europa.eu/health/documents/community-register/ods/ods_products.json>
- 仓库内证据：`reports/ema-ingest-prep.md`（task-97 数据/许可/映射）、`reports/eu-layer-schema.md`（task-102 region 建模与副本入库）、`docs/许可清单.md`、`docs/市场扩展接口.md` §7、`data/markets.json`、`data/languages.json`、`etl/ingest_ema_medicines.py`

_本报告只做评估：未写库、未改代码、未建站、未发布；原始数据文件仅落在 `.tmp/ema/`（不入库），报告里的数字可用 §8 链接 + 仓库证据复算。_
