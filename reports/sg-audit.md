# 新加坡（SG）数据源审计（task-98）

> 日期：2026-10-28 ｜ 只调研/缓存：未写 `data/drugs.db`、未改 `site/build.py` / `data/markets.json`、未 git/发布
> 结论：**推荐接入 SG 西药注册名册（data.gov.sg 官方数据集，5,511 条、字段完整、SODL 许可可再发布）**；PRISM/InfoSearch/PI 说明书库仅做**链接层**（HSA 网站条款要求书面许可，不能批量再发布）。
> 缓存：`data/raw/sg/`（HTML/JSON/CSV 快照+条款页），证据：`.tmp/sg-audit/`（分析脚本与统计 JSON）。
> 另含 Lead 追加的「双语展示/双语对照数据可行性」与「中成药（CPM）名册」两节。

---

## 0. 结论速览

| 来源 | 可批量 | 关键字段 | 许可 | 建议 |
|---|---|---|---|---|
| **data.gov.sg — Listing of Registered Therapeutic Products**（HSA 管理） | ✅ 官方 CSV/旧版 datastore API：**5,511 行**，12 列（LicenceNo/Productname/Licenseholder/Approvaldate/Forensicclassification/**ATCCode**/Dosageform/RouteofAdministration/Manufacturer/Countryofmanufacturer/**Activeingredients**/**Strength**）；每 6 个月更新（lastUpdated **2026-08-07**） | 商品名、注册号、持有人、批准日期、处方分类（POM/GSL/P）、ATC、剂型、给药途径、**规格**、成分（英文）、生产商/国别 | **Singapore Open Data Licence v1.0（SODL）**：可商用/非商用使用、复制、分发、改编，须署名 + 链许可页；可再授权 | **推荐作为 SG 主数据源**（批量入库） |
| data.gov.sg — Listing of Licensed Chinese Proprietary Medicines | ✅ **11,977 行**，6 列（BrandName/ProductName/DosageForm/CompanyName/Manufacturer/CountryofManufacturer） | 中成药**商品名（98.3% 含中文）**、品牌（76.2% 含中文）、剂型、公司/厂商/产地；**无成分、无规格、无 ATC、无批准日期/状态** | 同 data.gov.sg SODL | **可选**：只能做「中成药名称/厂商目录」或链接层；**无法映射成现有 product_component 模型**（缺活性成分） |
| HSA PRISM 公开查询（`eservice.hsa.gov.sg/prism/common/enquirepublic/*`） | ❌ 无公开批量 API；页面要求 JS+Cookies（返回 "This site requires JavaScript and Cookies"），且为逐条查询界面 | 与西药名册同源（PRISM 是注册系统前端） | HSA 网站 Terms of Use：**允许版权法范围内的使用；其他复制/再发布（尤其商业用途）须 HSA 书面许可** | 仅**链接层**（链到 PRISM/InfoSearch 查询页），不抓取/不再发布 |
| HSA Product Information（PI）说明书库 | ❌ 无公开批量索引；PI PDF 通常由 PRISM/InfoSearch 结果逐条链接（需会话/JS） | PI 全文 PDF（含适应症/用法用量） | HSA Terms 同上（**不可再发布全文**；本站口径也不存说明书正文） | 仅**链接层**（深链到 PI/查询页）；不下载、不入库 |
| MOH / HealthHub | ❌ 未发现公开批量药品清单（HealthHub `/medicines` 404；只有消费者健康信息页） | 消费者说明/健康主题 | 政府网站版权（政府开放数据不涵盖） | 仅链接层（若有需要） |

**一句话**：SG 能批量做的只有 data.gov.sg 的西药注册名册（5,511 条，字段含规格/ATC/剂型，SODL 可再发布）；它足以支撑「名称/成分/规格/剂型/注册信息」层；PRISM/PI 只能链接。中成药名册可批量但缺成分（只能名称层）；双语方面西药商品名纯英文、中成药名内含中文。

---

## 1. 数据源核验（已验证可访问）

### 1.1 data.gov.sg 西药注册名册

- 数据集：`Listing of Registered Therapeutic Products`，datasetId **`d_767279312753558cbf19d48344577084`**，管理方 **Health Sciences Authority (HSA)**；[data.gov.sg 数据集页](https://data.gov.sg/datasets/d_767279312753558cbf19d48344577084/view)；数据集页显示：**Updated every 6 months**、last updated **07 Aug 2026**、Download CSV **1.3 MB / 5.5K rows**、12 列。
- **实际拉取**（旧版 datastore API，见 §7 可复现）：
  `https://data.gov.sg/api/action/datastore_search?resource_id=d_767279312753558cbf19d48344577084&limit=100000`
  → `success=true`，**5,511 条**（total=5,511），12 列 + `_id`。
- **字段/覆盖**（5,511 行）：

| 字段 | 非空 | distinct | 说明 |
|---|---:|---:|---|
| LicenceNo | 100% | **5,511（唯一）** | 注册号，如 `SIN00230P` → product_id 天然主键 |
| Productname | 100% | 5,501 | 商品名（英文；部分含规格文本，如 `... 500 mg/2 ml`） |
| Licenseholder | 100% | 223 | MAH/持证人 |
| Approvaldate | 100% | 2,671 | 批准日期（`5/4/1988` 等混合格式） |
| Forensicclassification | 100% | 3 | Prescription Only 4,717 / General Sale List 486 / Pharmacy Only 308 |
| ATCCode | 99.5% | 1,426 | ATC（5,366/5,511 为合法 4/5 级格式） |
| Dosageform | 100% | 89 | 如 TABLET, FILM COATED / INJECTION, SOLUTION |
| RouteofAdministration | 100% | 85 | 如 ORAL / AURICULAR (OTIC) |
| Manufacturer | 100% | 2,164 | 生产商 |
| Countryofmanufacturer | 100% | 322 | 生产国 |
| Activeingredients | 100% | 2,968 | 英文成分；**复方用 `&&` 连接**，也有 `EQV/AS/…` 说明 |
| Strength | 100% | 2,307 | 如 `10 mg`、`5% w/v`；**复方用 `&&` 连接多个强度**（见 §3） |

- **无**中文名/本地语言名（5,511 行 Productname CJK **0**、Activeingredients CJK **0**）。
- **无**包装（pack）、**无**注册状态（在册清单，默认在售/有效）、**无**剂型/释放的结构化枚举（需映射）。
- 更新频率：**每 6 个月**（数据集页）；当前快照 2026-08-07。许可：数据集页链接 **Singapore Open Data Licence**（见 §4）。

### 1.2 data.gov.sg 中成药（CPM）名册

- 数据集：`Listing of Licensed Chinese Proprietary Medicine Products`，datasetId **`d_2ae2e6beb458d059318c1c14ad899f98`**；同样由 HSA 管理、data.gov.sg SODL。
- **实际拉取 11,977 条**，6 列：

| 字段 | 非空 | distinct | 说明 |
|---|---:|---:|---|
| BrandName | 97.2% | 612 | 品牌，**76.2% 行含中文**（如 `SANJIN(三金)`） |
| ProductName | 100% | 9,135 | 商品名，**98.3% 行含中文**（如 `BANLANGEN KELI(板蓝根颗粒)`） |
| DosageForm | 100% | 16 | Granules/Powders/Capsules/Liquid/Tablets/Pills/Tea… |
| CompanyName | 100% | 140 | 本地公司 |
| Manufacturer | 100% | 363 | 生产商 |
| CountryofManufacturer | 99.99% | 15 | 中国为主 |

- **无活性成分字段、无规格、无 ATC、无批准日期/状态** → 无法映射成现有 `product_component`（成分行）模型；只能做名称/厂商目录或链接层。
- 中成药属传统药范畴，是否纳入站点需产品/合规拍板（与 CN 中成药口径一致时再考虑）。

### 1.3 HSA PRISM / InfoSearch / PI 说明书库

- InfoSearch 页面（[hsa.gov.sg/e-services/infosearch](https://www.hsa.gov.sg/e-services/infosearch)）公开链接到 PRISM 公共查询：
  `eservice.hsa.gov.sg/prism/common/enquirepublic/SearchDRBProduct.do?action=load`（西药）、`SearchCPProduct.do`（中成药）、`SearchCompany.do` 等；以及 `share.hsa.gov.sg/approvedproducts`。
- **反爬/访问限制**：直接抓取这些 `.do` 端点只返回 `This site requires JavaScript and Cookies to be enabled`（1,557 字节占位页）；实际查询需浏览器会话，**无公开批量 API**。
- **HSA 网站 Terms of Use**（2026-03-13 版）§4.3 原文要点：
  > "The reproduction of any information or material from this Website, in any form or medium, for purposes other than those permitted under the Copyright Act, can only be done with **written permission** from the Health Sciences Authority. In particular, the reproduction or use of information or material from this Website for **commercial purposes** … is **prohibited**."
  → PRISM/InfoSearch/PI 内容**不用于再发布**；只能深链（链接层）。
- robots.txt：`Allow: /`，`Disallow: /search`（HSA 站内搜索禁止抓取）。
- PI（Product Information）PDF 库：Sitemap 2,562 条中未发现独立「PI library」入口；PI 通过 PRISM/InfoSearch 逐产品链接（会话内），**无可批量下载的索引**。且 PI 全文含适应症/用法用量，按本站现有口径也不入库（不展示说明书正文）。

### 1.4 MOH / HealthHub

- `moh.gov.sg` 200（内容为政策/健康主题页）；`healthhub.sg/medicines` **404**，HealthHub 首页 200（消费者健康内容）。
- 未发现公开批量药品清单/接口；无再发布明确开放许可 → 仅链接层（可选）。

---

## 2. 与现有 10 国模型映射（SG 为英文市场，无需新语言）

当前 DB 市场（9）：US/GB/CN/ES/MX/AU/CA/TW/HK；SG 将为**第 10 个市场**，`country='SG'`，UI 只需现有 **en**（无需新语言/新 i18n 字典）。

| SG 字段 | DB 目标 | 处理/映射 |
|---|---|---|
| LicenceNo（`SIN00230P`，唯一 5,511） | `product.product_id` / `approval_id` | `product_id = "SG-" + LicenceNo`（如 `SG-SIN00230P`） |
| Productname（英文，含规格文本） | name_key + name_variant + product_name(trade) | 走项目 `normalize_name.normalize()`（英文小写键）；原文进 name_variant；不从品名解析成分 |
| Licenseholder | `product.mah` | 原样 |
| Approvaldate | `product.status_date` 或 note | 批准日期非状态日期；建议 note "Approvaldate: …"，status_date 留 NULL（或单独字段后续） |
| Forensicclassification | `product.category`（或 note） | Prescription Only / Pharmacy Only / General Sale List（事实标签，不是用药建议） |
| ATCCode（99.5%） | substance.atc（单成分唯一时）或 note | 单成分产品可补 substance.atc；复方/不一致时只进 note，不覆盖 |
| Dosageform（89 种） | `dosage_form` + `form_base` + `release` | 89 种 → 项目 form_base 枚举（tablet/capsule/injection/liquid/topical/powder/suppository/inhalation/other/unknown）；release 从剂型字符串推断（"EXTENDED RELEASE"/"GASTRO-RESISTANT" 等） |
| RouteofAdministration | `product.route` | 小写化（oral/auricular…）；schema 有 route 字段 |
| Manufacturer / Countryofmanufacturer | note | schema 无 manufacturer 字段：写 `note`（如 `Manufacturer: …; Country: …`） |
| Activeingredients（英文、复方 `&&` 连接） | `product_component`（多行） | **需要复方拆分器**：按 `&&` 拆；再处理 `EQV/AS/…`、盐型；用 DB inn_en+盐/别名匹配到 variant；未匹配成分丢弃计数（不硬造） |
| Strength（100%，复方 `&&` 多值） | `product_component.strength_*` | **按 `&&` 顺序与成分对齐**；支持 `10 mg`、`5% w/v`、`500 mg/5 ml`（per_volume）、`&&` 多值；无法对齐/解析的留 NULL + 置信度（页面显示「未载」） |
| （无 pack） | `pack`=NULL | 页面不展示包装 |
| （无状态字段） | `status='active'`（注册名册默认在售；不臆造 withdrawn） | 页面说明「SG 为注册名册，非在售状态承诺」 |
| （无中文名） | 无 name_zh | — |
| （无 ATC 的 28 行 / 无规格/无效值） | 留空 | — |

- 预计产出：**5,511 products**（+~1.2% 现有 426k）、components ~**6–10k**（复方拆分后）、name_keys ~5.5k；DB 约 +**5–8 MB**（估算）。
- 市场层：需 `db/schema.sql` country CHECK 加 `SG`（与 TW/HK 同一 init_db 重建迁移模式）+ `data/markets.json` 注册/启用（enabled 先 false）+ 构建参数（国家列/选择器；en 已支持）。属后续任务，不在本审计内改。

---

## 3. 字段质量与映射可行性（5,511 行实测）

| 指标 | 结果 |
|---|---|
| LicenceNo 唯一性 | 5,511/5,511 唯一（无重复行） |
| ATC 合法 4/5 级格式 | **5,366 / 5,511 = 97.4%** |
| 剂型 → form_base 映射 | 89 种剂型可映射约 **97.5%**（estimated：tablet 2,397 / injection 1,544 / capsule 550 / liquid 437 / topical 333 / powder 58 / suppository 29 / inhalation 26 / unknown 137） |
| Strength 可解析（数字+单位） | **5,124 / 5,511 = 93.0%** |
| Strength 含多个数值（复方/多值） | 767 行 |
| Strength 含 per_volume 形态（`/ml`、`% w/v`、`% w/w`） | 907 行 |
| Strength 不可解析典型 | `5% w/v`、`25% v/v`、`100000 units`、`1%`、`5% w/w&&2% w/w`（需在 ETL 里补 `%`/单位/`&&` 规则） |
| 成分字符串复方率（`&&` 或匹配到 ≥2 成分） | **约 40.2%**（2,218 行） |
| 成分匹配（DB inn_en/别名，贪婪切分） | 全部成分匹配 **2,805/5,511 = 50.9%**；匹配到的成分共 9,644 个 |
| 成分级 inn_zh 覆盖（用于中文展示） | **4,589 / 9,644 = 47.6%**；至少一个成分有中文名的行 **3,471/5,511 = 63.0%** |
| 匹配失败主因 | ① 复方串无分隔（如 `SULPHAMETHOXAZOLE TRIMETHOPRIM`）需按 DB 名做最长匹配/组合表；② 生物制品/疫苗/血制品（HUMAN ALBUMIN、COAGULATION FACTOR VIII、mRNA 疫苗）；③ BAN 拼写（GUAIPHENESIN、HYOSCINE N-BUTYLBROMIDE） |

> 结论：西药名册「字段层面」几乎完整（规格/ATC/剂型都有结构化值），**ETL 主要工作量在复方拆分、成分名匹配、`&&` 强度对齐**；预计实现后成分行映射率可从 50.9% 提升到 **~70–85%**（补别名表/复方组合表后）。

---

## 4. 许可结论（关键）

| 内容 | 许可 | 可否再发布到本站 | 义务 |
|---|---|---|---|
| **data.gov.sg 两个 HSA 数据集（西药名册 + 中成药名册）** | **Singapore Open Data Licence v1.0**（数据集页默认许可，[许可页](https://data.gov.sg/open-data-licence)） | ✅ **可以**（商用/非商用均可） | ① 明确署名来源（HSA / data.gov.sg）；② 链到许可页；③ 不暗示政府背书；示例署名："Contains information from Listing of Registered Therapeutic Products accessed on <date> from HSA / data.gov.sg, made available under the Singapore Open Data Licence v1.0." |
| **HSA 网站（PRISM / InfoSearch / PI 说明书）** | HSA Terms of Use §4.3：版权法范围外复制/再发布（尤其商业用途）需**书面许可** | ❌ **不可**批量再发布（可做链接层） | 深链到官方查询/说明书页，不复制正文/PDF |
| MOH / HealthHub | 政府网站版权（未声明开放许可） | ❌（仅链接） | — |

> **重要区别**：同一份「西药注册名册」在 data.gov.sg 上以 **SODL** 发布（可再发布），而 HSA 自己网站上的查询界面/说明书按 **HSA Terms** 限制。**本项目应只使用 data.gov.sg 数据集**，不要抓 PRISM/PI；页面 About 里分别署名 data.gov.sg（数据）+ HSA（来源机构），并链许可页。

---

## 5. 双语展示 / 双语对照数据可行性（Lead 追加）

### 5.1 各字段能否中英对照

| 字段 | 西药名册（English only） | 中成药名册（CPM） | 本站可提供的双语 |
|---|---|---|---|
| **商品名（品牌名）** | ❌ 纯英文（5,511 行 CJK=0）；**品牌名不翻译** | ✅ **中文就在名里**（ProductName 98.3% 含中文；BrandName 76.2%） | 西药：只显示英文原名（+可选「中文成分」旁注）；中成药：`BANLANGEN KELI(板蓝根颗粒)` 可拆成英文名 + 中文名并排 |
| **活性成分** | 英文（Activeingredients）；无中文 | 无成分字段 | ✅ 可用本站 `substance.inn_zh`（DB 内 2,591/12,790 有中文名）做**英文成分 → 中文成分**对照；SG 匹配成分覆盖率 **47.6%**（至少一个成分有中文名的行 **63.0%**），缺的显示「—」并标注来源缺失 |
| **剂型 / 给药途径** | 英文枚举（89/85 种） | 英文剂型（16 种） | ✅ UI 层翻译（现有 en/zh i18n 的剂型/途径词表可直接复用；数据值本身不翻译） |
| **规格** | 结构化（`10 mg`、`5% w/v`、`&&` 多值） | 无 | ✅ 数值+单位不需翻译；页面用 zh i18n 标签显示「规格」；缺失显示「未载」 |
| **状态** | 无状态字段（在册默认 active） | 无 | ✅ 状态词 UI 翻译（「在册/有效」等），但**不虚构 withdrawn** |
| **厂商 / 产地** | 英文 | 英文+中文公司名部分 | 保持原文（不翻译公司名） |
| **批准日期 / 注册号** | 有（日期/编号） | 无 | 原样显示（数字无需翻译） |

### 5.2 「本市场原名 + 中文/已选语言翻译并排」最小实现方案

1. **数据层（SG ingest 时）**：
   - 西药：`product_name` 存英文原名（name_key/norm 走英文归一）；product_component 存英文 INN + `substance_id`；**不翻译品牌名**。
   - 渲染层需要：`substance.inn_zh`（现库已有；缺的留空并标 `source_missing`）。
   - 中成药（若上线）：从 `ProductName/BrandName` 的括号解析（`英文(中文)`）→ 双字段 `name_en`, `name_zh`，标注 source=`HSA CPM register`。
2. **索引字段（build 任务）**：SG 产品可在索引条目加 `xz`（中文成分名数组，现 v0.5.5 已有该机制）与 `nz`（中文商品名，仅 CPM）；西药商品名保持 `n`=英文原名。
3. **页面呈现**：结果行/详情页「原名 + 中文成分」并排：
   - 例：`CHLORAMPHENICOL EAR DROPS 5% w/v`（**SG 原名**） → 成分：`CHLORAMPHENICOL` / **氯霉素**（来源：DB inn_zh / WHO INN）；
   - 无中文成分时显示 `—` + tooltip「该成分暂无中文名（可提交翻译）」；品牌名固定不翻译并标注「品牌名不译」。
4. **翻译来源标注（必须）**：`inn_zh` 来源 = 本站成分表（含 WHO INN 中文名，CC BY-NC-SA 3.0 IGO；站点非商业）；CPM 中文名来源 = HSA 名册原文；机器翻译只用于 UI 标签，**不用于药名**。
5. **缺口**：
   - 西药商品名无中文（源就没有）→ 不能提供「SG 英文商品名 ↔ 中文商品名」，只能「英文商品名 ↔ 中文成分」；
   - 37% 的 SG 匹配行没有任何中文成分名（覆盖率受 DB inn_zh 限制；可后续补 inn_zh/药典中文名）；
   - 37% 成分行未匹配（生物制品/复方拆分）→ 这些行连中文成分都无从显示；
   - 中成药有中文名但无成分/规格/ATC → 不能做「成分/剂量」对照，只能名称目录（且是否纳入站点需产品决策）。
6. **若用户坚持「同一页并排中英全字段」**：可实现的是 **原名(EN) + 成分中文 + UI 中文标签**；**不可能**实现「英文商品名 ↔ 中文商品名」对照（西药源数据没有中文名）。建议产品上明确「品牌名不译、成分名有中文才译」。

---

## 6. 推荐接入方式 / 工期

| 阶段 | 内容 | 估算 |
|---|---|---|
| P0（推荐先做） | 西药名册 ingest：`etl/fetch_sg_datagov.py`（datastore API 拉全量 5,511 行 → data/raw/sg/）+ `etl/ingest_sg_hsa.py`（transform/复方拆分/强度解析/别名表/幂等/撤销） | **0.5–1 人日** |
| P1 | 复方拆分器 + `&&` 强度对齐 + BAN/生物制品别名（映射率 50.9% → ~80%）；SOURCES/About 署名 + 数字口径 | **+0.5–1 人日** |
| P2 | schema `SG` 枚举迁移 + markets.json 注册（enabled 后置）+ build.py 国家列（英文，无新语言） | +0.5–1 人日 |
| P3（可选） | CPM 中成药「名称目录」/链接层；PI/PRISM 链接入口；双语 UI 开关（成分中文并排） | +1–1.5 人日（CPM 需产品决策） |
| **合计** | 西药层上线 | **约 2–3 人日**（不含发布）；CPM/双语 UI 另计 |

**结论**：**值得做**——西药名册是少见的高质量英文批量数据（规格/剂型/ATC 全有、SODL 可再发布、半年更新、5,511 条），能一次性补上 SG 市场（第 10 国）且不需要新语言；PRISM/PI 只做链接层，规避 HSA 书面许可要求。双语方面：**西药只能做到「英文原名 + 中文成分」对照，不能翻译品牌名**；中成药名册可提供中文商品名，但缺成分/规格，需产品决策是否作为独立目录上线。

---

## 7. 风险 / 限制

| # | 风险 | 缓解 |
|---|---|---|
| 1 | data.gov.sg 旧版 datastore API 可能限流/改版（新 v2 API 需 API key；旧 API 文档写着可用但未来可能下线） | 缓存全量 JSON/CSV 到 `data/raw/sg/`；ETL 优先本地缓存；定期核对 total 行数与 lastUpdated（每 6 个月） |
| 2 | 用错许可（把 HSA 网站 PRISM/PI 内容当 data.gov.sg 数据再发布） | **只用 data.gov.sg 数据集**；页面 About 分列「数据来源 data.gov.sg（SODL）/ 原机构 HSA」，并链许可页；PRISM/PI 只做链接 |
| 3 | 复方成分串无分隔（40.2% 复方）、`&&` 强度对齐、BAN/生物制品拼写 | 专门写 `split_ingredients_sg()` + 最长匹配 + 别名表；映射失败的成分丢弃并计数，不硬造 |
| 4 | 批准日期格式混杂（`5/4/1988`、`dd/mm/yyyy`） | 只存原文/NULL，不解析为日期；页面显示原文 |
| 5 | 无在售/停用状态字段（注册名册≠在售） | status='active' 仅表示在册；页面明示；不输出用药建议 |
| 6 | 产品名夹带规格/剂型文本（`... 500 mg/2 ml`） | 名称层保留原文；规格从 Strength 列取，不从品名解析 |
| 7 | 本次审计未逐条人工核对 5,511 行 | 入库前抽检 50 行（尤其复方/生物制品/外用药）+ 覆盖统计 |
| 8 | 中成药无成分，无法进现有成分模型 | 单独目录/链接层；需产品（是否上线传统药）与合规拍板 |

---

## 8. 证据（data/raw/sg/ 与 .tmp/sg-audit/）

| 文件 | 内容 |
|---|---|
| `data/raw/sg/hsa_registered_therapeutic_products.json` | 西药名册全量（5,511 条，旧 datastore API 拉取） |
| `data/raw/sg/hsa_cpm_products.json` | 中成药名册全量（11,977 条） |
| `data/raw/sg/hsa_prism_therapeutic_products.html` / `hsa_infosearch.html` / `hsa_terms_of_use.html` | PRISM/InfoSearch/条款页面快照 |
| `data/raw/sg/datagov_dataset_page.html` / `datagov_open_data_licence.html` | data.gov.sg 数据集页（更新频率/许可/API 示例）、SODL 许可全文 |
| `data/raw/sg/hsa_sitemap.xml` | HSA sitemap（2,562 URL；无独立 PI library 入口） |
| `.tmp/sg-audit/csv_stats.json` / `analyze_sg.out.txt` / `analyze2.out.txt` | 字段覆盖、成分映射、inn_zh 覆盖、剂型/规格分析、双语可行性统计 |
| `.tmp/sg-audit/fetch*.py` / `download*.py` / `analyze*.py` / `summarize.py` / `extract_page.py` | 抓取与审计脚本 |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\sg-audit\fetch_data.py      # 拉 data.gov.sg 两个数据集（西药/中成药）→ data/raw/sg/
& $py .tmp\sg-audit\analyze_sg.py      # 字段覆盖 + DB 映射 + 许可文本
& $py .tmp\sg-audit\analyze2.py        # PI/PRISM/InfoSearch/MOH + 剂型/规格/双语可行性
```

---

_本报告由并行子智能体 data-depth 生成；未写 `data/drugs.db`、未改 `site/build.py` / `data/markets.json`、未跑 git/发布。_
