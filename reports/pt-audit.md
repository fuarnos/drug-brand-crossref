# 葡萄牙（EU 首站）数据源审计 + pt-PT 可行性

> 日期：2026-10-28 ｜ 任务：`task-92`（Lead 口述 task-93）｜ 性质：**免费只读审计**，未写 DB、未改 `site/build.py`、未 git/发布。
> 只写 `reports/pt-audit.md`、`data/raw/pt/`（缓存）、`.tmp/pt-audit/`。
> 用户问题：「葡萄牙语有的话，澳门做完能开葡萄牙吗？」→ **能，但要分两步：pt-PT 界面/EU 架构可以先做；葡萄牙市场数据必须先拿 INFARMED 书面授权（当前无开放许可、且明确禁止爬取）。**

---

## 0. 结论（先看这里）

| 维度 | 结论 |
|---|---|
| **数据可得性** | INFOMED 公开可查：**1,692 个 DCI / 10,446 个药品 / 12,646 个包装（apresentações）**，数据更新至 **2026-10-28**；但**没有开放许可**，Guia 明确「未经 Infarmed 书面许可不得利用/出版/复制/分发/出售/出租」；`extranet.infarmed.pt/robots.txt` 为 **`Disallow: /`** → **禁止爬取**。 |
| **合法数据路径** | INFARMED 有「Cedência de base de dados」（CITS/SATS 协议）：**公共行政部门免费，其他机构 €150（+IVA）/年**，访问期 1 年，需签协议（`cimi@infarmed.pt`）。→ 建议走**书面授权/协议**，不要抓取。 |
| **替代/补充来源** | EMA 集中审批数据**可再发布**（EMA legal notice：非商业/商业均可复制分发，须注明 EMA 为来源）：XLSX 2,754 行（Human 2,357 / Authorised 1,875 / 带 ATC 2,225），但只覆盖 **EU 层面集中审批产品**，不是葡萄牙本国商品名/包装。 |
| **dados.gov.pt** | INFARMED 组织共 **36 个数据集**，全部是支出/抗生素/生物类似药/临床试验统计，**没有药品注册库/产品清单**；搜 `INFOMED` 命中 0；不能作为产品数据源。 |
| **pt-PT 界面** | 架构可行：`data/languages.json` 已有 **pt 占位**（disabled，`hreflang=pt`、`path=pt/`、`region=EU`、default_country=PT）；当前 i18n **328 键 ×4 语言**（任务口述 332，实测构建产物为 328，以 dist 为准），pt-PT 需补 328 键 + 静态页（About/What's new/Confused/Warn/404/术语表）+ hreflang/切换/副本。 |
| **葡语输入归一** | 服务端 `etl/normalize_name.py` 用 NFD 去重音（`name_key.norm` 无重音）；但**客户端 `app.js norm()` 是 NFKC + combining 字符删除，不对预组合重音做分解** → `Ácido` 这类带重音输入可能与无重音索引键不匹配（对 ES 同样有影响）。**这是 pt-PT 上线前置修复项**。 |
| **预计接入规模** | 商业流通口径 **10,446 个药品 / 12,646 个包装**（可映射为约 1.0–1.3 万 product 行）；完整 AIM（含未流通）会更大，需向 INFARMED 确认。对比 ES 25,293 / MX 10,878，PT 属中等市场。 |
| **推荐接入方式** | **INFOMED（授权协议导出/数据库）为唯一主源**；EMA 作 EU 区域层；dados.gov.pt 不采用。 |
| **工期** | 语言/EU 架构 **2–3 谷段**（可立即开始）；授权后 ETL+DB+页面 **4–6 谷段**；法律/授权等待时间未知（数周）。总计 **6–9 谷段 + 等待**。 |
| **风险等级** | 数据许可=**高**（无开放许可+禁爬）；工程=中；pt-PT=低-中（与现有语言机制兼容）。 |

---

## 1. 数据源审计（2026-10-28 抽样验证）

### 1.1 INFOMED（INFARMED 国家药品数据库）— 主源候选

| 项 | 结果 |
|---|---|
| 入口 | https://extranet.infarmed.pt/INFOMED-fo/ （HTTP 200，首页 43,146 B；高级搜索页 1.18 MB） |
| 计数（首页） | **Substâncias Ativas/DCI = 1,692**；**Medicamentos = 10,446**；**Apresentações = 12,646**；Atualizado a **28/10/2026**（首页注明「dados referentes a medicamentos e apresentações comercializados」，即**商业流通口径**） |
| 字段 | 名称、活性成分（DCI/通用名）、**dosagem（规格）**、**forma farmacêutica（剂型）**、**apresentações（包装）**、**PVP（零售价）**、**AIM 状态/商业化状态**、**titular de AIM（MAH）**、注册号、FI/RCM 文档链接；详页/搜索页为 JSF（PrimeFaces） |
| 批量性 | 仅网页查询（general + advanced search，JSF POST/ViewState），**无公开 API/批量导出**；robots.txt `User-agent: * Disallow: /` |
| 更新频率 | 首页显示每日更新（Atualizado a 当日）；官方 AIM 变更后同步 |
| 许可 | **🔴 仅事实+书面许可**：Guia e condições de utilização 原文「O utilizador não pode, sem autorização escrita do Infarmed, total ou parcialmente, explorar, publicar, reproduzir, distribuir, vender ou alugar, ou por qualquer outra forma ceder...」；无 CC/OGL 类许可 |
| 结论 | 字段与覆盖率都够（PT 唯一权威源），但**不能直接抓取/再发布**；必须走 INFARMED 授权。 |

### 1.2 INFARMED「Cedência de base de dados」（CITS / SATS）— 合法获取路径

| 项 | 结果 |
|---|---|
| 入口 | https://www.infarmed.pt/web/infarmed/profissionais-de-saude/prescricao-e-dispensa/cedencia-de-base-de-dados-de-medicamentos （HTTP 200，316 KB） |
| 机制 | Portal CITS（Cedência de Informação de Tecnologias de Saúde）/ SATS；访问前需**申请+付款**、签**协议（protocolo de cedência）**；提供药品数据库（Infomed）及电子处方等信息的标准化访问 |
| 费用 | **Administração pública: Gratuito**；**Outras entidades: €150,00 (+IVA) / Ano**；**Duração do acesso: 1 ano** |
| 联系方式 | `cimi@infarmed.pt`（页面明示） |
| 许可含义 | 付费访问≠自动获得公开再发布权：协议通常限定内部使用/合作范围；**必须在申请中明确「公开非商业网站展示/再发布」并取得书面同意**（用户站点为公开、非商业，可争取） |
| 结论 | **推荐路径**：先发正式申请（说明用途、字段、公开再发布方式），拿到书面许可后由 INFARMED 提供导出（Access/CSV）或数据库访问，再写 ETL；不要先爬。 |

### 1.3 dados.gov.pt（葡萄牙开放数据门户）

| 项 | 结果 |
|---|---|
| API | https://dados.gov.pt/api/1/organizations/infarmed/datasets/?page_size=100 （HTTP 200；INFARMED 共 **36 个数据集**） |
| 内容 | 支出、抗生素使用、生物类似药、临床试验、药品平均价格、库存/战略储备等**统计类**数据；**没有药品注册/产品清单** |
| 搜索 | `q=medicamentos` 命中 61（含 INFARMED 的支出类），`q=INFOMED` **0**，`q=DCI` 4（均为处方/采购统计） |
| 许可 | 数据集许可为「Licença não especificada」（未指定）或 CC BY 4.0（可再发布），但**与药品身份数据无关** |
| 结论 | ❌ 不能作为 PT 产品主源；个别 CC BY 数据集将来可作为价格/使用量补充，但非必需。 |

### 1.4 EMA（欧盟集中审批数据）— 可合法再发布的 EU 层

| 项 | 结果 |
|---|---|
| 入口 | https://www.ema.europa.eu/en/medicines/download-medicine-data （HTTP 200） |
| 下载 | `medicines-output-medicines-report_en.xlsx`（**904,715 B**，本地已缓存） |
| 结构/条数 | 表头含 Category、Name of medicine、EMA product number、Medicine status、Opinion status、**INN/common name**、**Active substance**、Therapeutic area、**ATC code (human)**、Therapeutic indication、Biosimilar/Orphan 等；**2,754 行**（Human **2,357** / Veterinary 397；Medicine status **Authorised 1,875**；唯一药名 2,701；带 active substance 2,661；带 ATC 2,225） |
| 许可 | ✅ EMA Legal notice：材料「may be reproduced and/or distributed, totally or in part, ... for non-commercial and commercial purposes, provided that EMA is always acknowledged as the source」 |
| 局限 | 仅 **EU 集中审批**产品（欧盟层面名称/MAH/ATC），**不是葡萄牙本国注册商品名、包装、价格**；不能替代 INFOMED 做 PT 市场 |
| 结论 | 适合先做 **EU region 层 / 集中审批产品**（合法、免费、可展示 + 署名），或作为 PT DCI/ATC 映射的辅助数据；不作为 PT 国家主源。 |

---

## 2. 入库难度与字段映射（INFOMED → 现有 schema）

现有 schema 关键列（只读核对）：`product(country, dosage_form, form_base, route, release, pack, mah, approval_id, category, is_branded, status, status_date, source_id, source_url, retrieved_at, note)`；`variant(substance_id, salt, hydrate, ester, base_fraction, interchange, salt_code, strength_basis)`；`product_component(product_id, ord, variant_id, strength_value, strength_unit, per_volume_value, per_volume_unit)`；`source(source_id, name, url, license, license_url, data_as_of, …)`。

| INFOMED 字段 | 目标 | 说明/难度 |
|---|---|---|
| Nome do medicamento | `name_key` + `name_variant`（原始名） | 低；保留葡萄牙语重音原文，`name_key.norm` 走现有 NFD 归一 |
| DCI / substância ativa | `substance`/`variant`（英文 INN 归并） | 中：PT DCI 多数与 INN 同名（paracetamol、ibuprofeno、atorvastatina…），少数需映射（ácido acetilsalicílico→acetylsalicylic acid、metamizol→metamizole）；盐型在 DCI/名称里（cálcico/sódico/besilato/maleato/hidrocloreto）→ 用现有 `normalize_salts` 规则 |
| Dosagem | `strength_value/unit`（+per_volume 如适用） | 中：葡萄牙语格式「500 mg」「5 mg/5 ml」需解析；液体/每 mL 口径沿用 MX per-volume 经验 |
| Forma farmacêutica | `dosage_form/form_base` | 低-中：PT 剂型词表（comprimido、cápsula、xarope、suspensão、solução injetável、creme、pomada、supositório、gotas、inalador…）→ 建 ~30 词映射 |
| Apresentações | `pack`（包装/数量） | 中：10,446 药品 vs 12,646 包装；若产品粒度=包装则 ~12.6k 行；否则按药品聚合、包装存 `note/pack` |
| Titular de AIM | `mah` | 低 |
| AIM 编号/状态/商业化 | `approval_id/status/status_date` | 中：状态枚举（autorizado/comercializado/revogado/suspenso…）需映射到站点 active/withdrawn/unknown |
| PVP（价格） | 暂不需要 | 站点不展示价格；可忽略 |
| ATC | 无（INFOMED 公开字段不含 ATC） | 缺口：可从 EMA（集中审批）、Wikidata/ChEMBL 或 DCI 映射补；优先级低（PT 的 ATC 覆盖率会低于 US/GB） |
| FI/RCM 文档 | 不用（不转载正文） | 只链原文 |
| 来源/许可 | `source` 表新增 `infarmed_infomed`（license 写「书面许可/协议」、数据截止、署名） | 需 Lead/法务确认后填 |

**预计规模**：10,446 药品（商业流通）→ 若按药品粒度约 1.0 万 row；若按包装约 1.26 万 row。完整授权名单可能 1.2–1.5 万；以 INFARMED 导出为准。

**关联风险**：INFOMED 是「商业流通」口径（首页注明），已撤市/未流通产品可能不在其中；站点状态字段要区分「未收录 ≠ 不存在」（与现有文案一致）。

---

## 3. pt-PT 界面与葡语输入可行性

### 3.1 现有语言/市场注册表状态

- `data/languages.json`：已有 **pt 占位**（`code: pt`，`hreflang: pt`，`path: pt/`，`region: EU`，`default_country: PT`，`enabled: false`，order 100，notes「EU 语言占位（disabled）」）；`planned_markets` 含 **PT**。
- `data/markets.json`：已有 **EU region 占位**（`kind: region`，`parent: null`，`group: EUROPE`，`enabled: false`，order 90，source_id null）；ES/GB 为 country（GB 已非 EU）；**没有 PT country 条目**。
- `db/schema.sql`：country CHECK 为 `('US','GB','CN','ES','MX','AU','CA','TW')`；新增 PT 需重建 product 表迁移（已有 TW 迁移先例 `db/migrate_country_tw.py`）。
- i18n：`site/dist/assets/i18n.js` 当前 **4 语言 × 328 键**；`pt` 需新增完整字典（可由 en 机翻 + 术语表校对，同 zh-Hant 模式）。

### 3.2 pt-PT 文案工作量

- 328 个 key（含 About/What's new/Confused/Warn/404/术语表/分页等静态页文案）→ AI 翻译 + 术语校对；
- pt-PT vs pt-BR 用词差异（按欧洲葡语）：
  `medicamento`、`princípio ativo`、`dosagem`、`forma farmacêutica`、`comprimido`、`cápsula`、`xarope`、`pomada`、`creme`、`supositório`、`gotas`、`genérico`、`receita médica`、`farmacêutico`、`doente`（PT 常用，非 `paciente`）、`folheto informativo`（PT；BR 用 `bula`）、`não sujeito a receita médica`（MNSRM=OTC）；
- 数字/单位沿用现有 i18n 机制（逗号小数、mg/ml 不变）。

### 3.3 葡语输入归一（关键修复项）

- 服务端 `etl/normalize_name.py`：`_strip_diacritics` = **NFD + 去 combining** → `name_key.norm` 无重音（如 `paracetamol` 正常）；
- 客户端 `app.js norm()` 当前是 **NFKC + 删除 U+0300–U+036F**；NFKC **不会把预组合字符（á/ç/ê…）分解**，所以用户输入「Ácido」得到 `ácido`，与无重音键 `acido` 不匹配——**对 ES 与 PT 都是隐患**（现有 ES 品牌/成分带重音时也会受影响；可能靠别名/包含匹配部分掩盖）。
- 建议（pt-PT 上线前）：客户端查询归一改为 `.normalize('NFD')` 去 combining（或显式 pt/ES 重音折叠表），并在 `tests/trilingual` 增加 PT 例：`Ácido acetilsalicílico`、`Paracetamol`、`Ben-u-ron`、`Cêgripe`、`Brufen`、`Voltaren`、`Metamizol`、`Sinvastatina`、`Atorvastatina cálcica`。
- 该修复在 `site/build.py`/`app.js`，不在本审计写范围；**列为 pt-PT 前置任务**（建议与 U3 标签本地化一起做）。

### 3.4 EU region / 注册表接入建议

1. **先加 PT country**（`kind: country`，`group: EUROPE`，`source_id: infarmed_infomed`，`enabled: false` 等授权；`order` 建议 100+），schema CHECK 加 `'PT'`（重建 product 表，走 TW 先例）；
2. **pt 语言条目**：建议改成 `code: "pt-PT"`（或保留 `pt` 但 `hreflang: "pt-PT"`、`native_name: "Português (Portugal)"`、`ui_label: "PT"`、`path: "pt/"`、`default_country: "PT"`、`region: "EU"`；`enabled` 在 UI 上线时 true）；需同步 `tests/test_markets_registry.py` 断言；
3. **EU region**：EU region 保留 `kind: region`，后续把 ES/PT/DE/FR/IT/NL/PL 作为 children（parent=EU），GB 单独；首个 EU 国家只有 PT 时可以先不开 region 页，等 ≥2 个 EU 市场再启用；
4. 页面：`/pt/` 入口 + about/confused/warn/whats-new/404 静态副本（复用 zh-Hant 的 `_write_with_copies`/i18n.js 机制）；hreflang `pt-PT`；语言切换「PT」；
5. 搜索/索引：`country=PT` 自动进索引；`xz` 中文名机制不适用；PT 的 DCI→INN 映射与盐型归一另建小表（如 `data/pt_inn_overrides.csv`，参考 es_inn_overrides）。
6. 许可/About：若获授权，About 增加「INFARMED/INFOMED + 授权协议编号/日期 + 数据截止 + 非官方转载声明」；LICENSE 行按 `docs/许可清单.md` 流程登记（不得写 CC BY，因为不是开放许可）。

---

## 4. 推荐路线（分阶段）

| 阶段 | 内容 | 工期（谷段） | 阻塞 |
|---|---|---|---|
| **P0 立即** | ① 给 INFARMED（cimi@infarmed.pt）发数据授权申请：说明公开非商业站点用途、所需字段（名称/DCI/规格/剂型/包装/MAH/AIM 状态）、引用与署名方式；申请 CITS/SATS 协议或书面许可；② 明确询问「是否允许公开再发布（非商业、署名、不转载 FI/RCM 全文）」 | 0.5 | 等待回复（数天–数周） |
| **P1 并行** | pt-PT UI 骨架：i18n 328 键翻译、`/pt/` 路由/静态副本/hreflang、语言切换、重音归一修复；**PT market 保持 disabled，不生成空市场页面** | 2–3 | 无（不依赖数据） |
| **P2 并行** | EU region 结构 + EMA 集中审批层（合法可再发布，2.7k 行/1.9k authorised；署名 EMA）——作为 EU 层，不是 PT 国家清单 | 1–2 | 无 |
| **P3 授权后** | INFOMED ETL：授权导出（Access/CSV）→ 字段映射、DCI→INN、盐型/剂型/状态词表、去重、dry-run 抽样；PT country 开量、覆盖表、About 授权行；`--dry-run` → apply（Lead 执行） | 2–3 | INFARMED 授权 |
| **P4 上线** | 四语回归（en/es/zh+pt-PT）、hreflang/sitemap、许可证页、smoke；发布 | 1–2 | P3 |

---

## 5. 风险清单

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | **INFOMED 无开放许可 + robots 禁爬 + ToS 禁止复制** | 未经授权抓取/展示=侵权风险，可能被要求下架 | 只走书面授权/协议；不抓取；申请中写明公开非商业转载 |
| R2 | 付费访问≠再发布权 | €150+VAT/年只解决访问，公开转载需单独同意 | 申请时明确「public non-commercial website」，保留书面回复 |
| R3 | PT 数据仅有商业流通口径 | 未流通/已撤市产品缺，且「未收录≠不存在」 | 文案沿用现有 caveat；状态字段标注口径；向 INFARMED 确认完整 AIM 清单 |
| R4 | INFOMED 无 ATC、包装/条码粒度不一 | ATC 覆盖率低于其他市场；product 行数口径需定 | ATC 从 EMA/Wikidata 补（可空）；product 粒度按 10,446 药品，包装进 `pack/note` |
| R5 | DCI→INN/盐型映射（PT 葡语 vs 英文） | 成分身份断链，跨国对应变差 | 建 `pt_inn_overrides` + `normalize_salts`；先 dry-run 抽样 200 条核对 |
| R6 | **客户端重音归一 bug** | 用户输入「Ácido/Paracetamol」带重音可能搜不到 | 上线前修 NFD 归一 + PT 测试集（影响 ES，建议一起修） |
| R7 | pt-PT vs pt-BR | 未来巴西（pt-BR）不能共用同一 UI 文案 | 语言注册表用 BCP47（pt-PT 现在，pt-BR 后续独立），共享翻译记忆但分文件 |
| R8 | EU region 设计未定稿 | 与 task-55 注册表接入冲突 | 本审计建议：PT 先作 country（group EUROPE），EU region 等 ≥2 个 EU 国家再启用；与 task-55 对齐 parent/children 字段 |
| R9 | 法律/授权时间不可控 | 排期不确定 | P0 先发申请；P1/P2 不等授权先做；PD 数据上线前 PT 保持 disabled |

---

## 6. 证据与缓存

| 路径 | 内容 |
|---|---|
| `data/raw/pt/infomed_home.html` | INFOMED 首页（1,692/10,446/12,646，更新 28/10/2026） |
| `data/raw/pt/infomed_guia.html` | Guia e condições de utilização（禁止复制/再发布条款） |
| `data/raw/pt/infomed_pesquisa_avancada.html` | 高级搜索页（JSF 表单字段：medicamento/dci/dosagem/ff/generico/taim…） |
| `data/raw/pt/infarmed_cedencia_db.html` | Cedência CITS/SATS（免费/€150+VAT/年、协议、cimi@infarmed.pt） |
| `data/raw/pt/ema_download_medicine_data.html`、`ema_legal_notice.html`、`ema_medicines_report_en.xlsx`、`ema_parse_summary.json` | EMA 数据表与许可（可再发布、须署名）；XLSX 2,754 行结构 |
| `data/raw/pt/dados_gov_pt_org_infarmed_datasets.json`、`dados_gov_pt_q_*.json` | dados.gov.pt INFARMED 36 数据集（无产品注册库） |
| `data/raw/pt/infarmed_robots.txt` | `User-agent: * / Disallow: /` |
| `data/raw/pt/fetch_meta.json` | 首次抓取状态/大小/SHA256/时间 |
| `.tmp/pt-audit/evidence.json` | 结构化审计结论（URL/状态/许可/条数） |
| `.tmp/pt-audit/fetch_pt.py`、`fetch_more.py`、`parse_*.py` | 可复现抓取/解析脚本（只读） |

> 说明：本轮所有联网请求均为**单次 GET 抽样**（未批量/未登录/未绕反爬）；缓存仅供审计复核，未写 DB、未发布。
