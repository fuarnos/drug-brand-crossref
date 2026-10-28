# 香港 / 澳门 数据源审计（HK/MO）

> 日期：2026-10-28 ｜ 任务：`task-86` ｜ 结论：**HK 可上线（名称/成分层，无规格）；MO 建议链接层/暂缓入库**
> 范围：只读审计 + 低频抽样；未写 `data/drugs.db`、未改 `site/build.py`、未跑 git/发布。
> 证据缓存：`data/raw/hk_mo/`（HK 注册名单 XML 4.3 MB + 条款页 + 抽样 CSV）；探针脚本/日志：`.tmp/hk-mo/`。

## 0. 结论速览

| 市场 | 可批量性 | 关键字段 | 许可 | 入库难度 | 建议 |
|---|---|---|---|---|---|
| **香港 HK** | ✅ 官方单一 XML（`http://www.drugoffice.gov.hk/eps/psi/DrugList.xml`，4.30 MB，14,275 条，`lastUpdate=2026-10-23`） | 商品名、注册证书持有人、HK 注册号（permitNo）、活性成分（平均 1.67 个，最多 35，去重 2,085 个）；**无规格、无剂型、无状态、无中文名** | data.gov.hk 条款：可商用/非商用免费浏览/下载/分发/复制，须注明来源并承认政府及原机构知识产权；无标准 ODbL/CC 名称（CKAN `license_title=null`、`isopen=false`，以 T&C 为准） | 低–中：1 个 XML + 成分名归一（盐/同义词）→ 可做「商品名→成分」层；**无法做 D1 规格对应** | **上线（名称/成分层）**，页面标「HK 不提供规格」；先补 schema `country` 枚举 `HK` 迁移 |
| **澳门 MO** | ❌ 未发现公开批量文件：ISAF「资料查询」为 Next.js 动态检索（未发现公开 API）；SSM 网站对脚本返回 403；官方「澳門特區藥品名錄」以光盘/向药房与专业人士索取为主（2013/2020 公告） | 名录含商品名/剂型/治疗分类/给药途径/活性成分及含量（公告描述），但无公开机器可读导出 | 未找到开放再发布许可；政府网站版权保留 | 高（需浏览器会话/索取制/BO 逐条） | **链接层**（链 ISAF 查询页）；如要入库，先解决许可 + 批量来源，否则**暂缓** |

## 1. 香港：衞生署藥物辦公室 註冊藥劑製品名單

### 1.1 来源与批量性（已验证）

- **data.gov.hk 数据集**：`hk-dh-dh_do-hk-dh-do-pharmaceutical-product`
  - CKAN API：`https://data.gov.hk/en-data/api/3/action/package_show?id=hk-dh-dh_do-hk-dh-do-pharmaceutical-product` → **200 JSON**（已存 `hkgov_ckan_en.json`）；
  - 数据集元数据：provider = Department of Health；update_frequency = “As and when necessary”；**`metadata_modified=2021-07-02`（元数据陈旧）**；`num_resources=1`；`license_id=null`、`isopen=false`；
  - 唯一资源：format = **XML**，name = “List of Registered Pharmaceutical Products (English Only)”，URL = **`http://www.drugoffice.gov.hk/eps/psi/DrugList.xml`**（注意是 **http**，非 https）。
- **实测下载**：HTTP 200，`application/xml`，**4,297,930 B**；XML 结构：

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

- **数据量/覆盖**（`hk_rpp_resource.xml` 全量解析，`.tmp/hk-mo/hk_xml_stats2.json`）：
  - 记录 **14,275** 条；`activeIngs` 缺失 **0** 条；平均 **1.67** 个活性成分；最多 **35** 个（大型复方/电解质）；去重活性成分串 **2,085** 个；
  - 字段：`productName / regCertHolderName / permitNo / activeIngs` **4 个字段，覆盖率 100%**；
  - **无** strength（规格/浓度）字段、**无** dosage form（剂型）字段、**无** 注册状态字段、**无** 中文名（前 2,000 条商品名 CJK=0；数据集描述 “English Only”）；
  - 商品名里会夹带浓度/百分比文本（如 `... CREAM 1%`），但不可结构化抽取；平均 1.67 成分意味着复方也可按多行 product_component 处理；
  - 注册号格式 `HK-58956`（`permitNo`，即 HK registration number），持有人即 MAH。
- **更新频率**：数据文件 `lastUpdate=2026-10-23`（审计日 5 天前）→ 实际接近「随时更新」；但 data.gov.hk 元数据停在 2021，**不能以元数据日期判断新鲜度**。
- **反爬**：data.gov.hk API 与 drugoffice XML 直连均 200，无验证码/登录；drugoffice 旧的 `eps/do/...html` 路径返回 404（站点改版），XML 直链仍是权威入口。建议抓取时低频（单文件 <5 MB）+ 本地缓存，不做逐条页面抓取。

### 1.2 许可结论（HK）

- data.gov.hk **Terms and Conditions**（`https://data.gov.hk/en/terms-and-conditions`，已存全文 txt）：
  > “You are allowed to browse, download, distribute, reproduce, hyperlink to, and print the Data for both commercial and non-commercial purposes on a free-of-charge basis on condition that … you shall identify clearly the source of the Data and acknowledge the Government and the Relevant Organisations’ ownership of the intellectual property rights in the Data … you shall also give proper attribution to the Government, the Relevant Organisations and DATA.GOV.HK.”
- 结论：✅ **可再发布**（商用+非商用），义务 = 注明来源（data.gov.hk / Department of Health）+ 承认政府与原机构知识产权 + 保留归属；条款含 indemnity（用户自担侵权索赔）——按站点现有「事实字段 + 署名 + 链原文」口径可满足。
- 注意：CKAN 元数据 `license_title=null`、`isopen=false` 与门户 T&C 不一致；**以 T&C 为准**，并在 `source.license` 写「DATA.GOV.HK Terms and Conditions（free reuse, attribution）」、`license_url` 指向 T&C 页。

### 1.3 入库难度与映射建议（HK）

| 项 | 评估 |
|---|---|
| ETL 工作量 | **低–中（约 0.5–1 人日）**：单 XML 下载+解析；成分串归一（盐型/同义词，可复用 `etl/normalize_salts.py` 的盐名规则：`hydrochloride/hcl`、`sodium/sodio` 等，但 HK 为英文串，需额外处理 `chlorphenamine maleate` 这类 BAN 名 → INN 映射） |
| schema 前置 | **必须**：`product.country` CHECK 当前为 US/GB/CN/ES/MX/AU/CA/**TW**（TW 已由台湾 P2 任务加入，审计时现库 7 国 + TW），新增 `HK` 按同一 `init_db.py` 重建迁移模式；`dosage_form` NOT NULL → HK 无剂型，只能写 `unknown`（或从商品名关键词粗判，需标注推断）；`release` 固定 `none`（不可靠，HK 无释放机制字段）；`status` 只能假定 `active`（名单为现行注册；**不写 withdrawn**，在 note 说明）；`pack` 空 |
| 字段映射 | product: `product_id=HK-<permitNo>`、`country=HK`、`dosage_form=unknown`、`mah=regCertHolderName`、`approval_id=permitNo`、`status=active`、`source_url=https://www.drugoffice.gov.hk/...（或登记号查询页）`；variant: 从 activeIng 串拆盐（`... hydrochloride`）→ salt/hydrate/ester，`source=hk_dh`；product_component: 每成分一行，`strength_value/unit=NULL` |
| 与现有市场连接 | 商品名英文全大写、无中文名 → **与 CN 中文名无法直接连**；成分名可与现有 substance.inn_en 对齐（需映射 2,085 个串，预计 top 常见成分 70–90% 可命中；审计本轮未逐条量测，须在 ETL dry-run 统计命中率）。HK 名称可点亮「同成分在 HK 的叫法」和 U2 横排，但**不能做 D1 规格对应**（无 strength）。 |
| 风险 | ① 无规格/剂型/状态 → 页面必须明示「HK 只到名称/成分层」，不能与其它市场做剂量比较；② 商品名夹带浓度文本，不解析；③ http 直链（非 TLS）需缓存后发布，不把 http 作为页面外链；④ 归属/免责条款（indemnity）需 About 署名条目；⑤ 数据为「现行注册」，不等于市面在售。 |

### 1.4 HK 建议

**上线（v0.7.x）：名称/成分层。** 具体：新增 `source=hk_dh` + ETL（`etl/fetch_hk_dh.py` + `etl/ingest_hk_dh.py`，仿 MX/CA 的 fetch/ingest 拆分）；schema 加 `HK`；About 加 data.gov.hk 署名；页面与 U2/A4 覆盖自动受益；**产品表不填 strength/form/release**，并在 market 说明中写「HK：只提供注册名/成分/持有人，无规格」。若时间紧，可先做「链接层」：在 About/未来 A4 覆盖页给 DH 注册查询入口，不建产品行。

## 2. 澳门：藥物事務廳 / 藥物監督管理局（ISAF）

### 2.1 来源与批量性（已验证）

- **ISAF「资料查询」** `https://www.isaf.gov.mo/cn/services/query`：HTTP 200，Next.js 动态应用（19 个 JS chunk），页面无 `__NEXT_DATA__` 内嵌数据、无 `/api` 检索端点（chunk 中仅见 `/api/wordpress/search` 新闻搜索）；**未发现可脚本化的公开查询 API**；查询结果需浏览器会话（推测走 server action/RSC）。→ **不可批量**。
- **SSM（衛生局）网站**：`https://www.ssm.gov.mo/...` 直连 **HTTP 403**（反爬/ WAF，Python UA 被拒）；卫生局 2013 公告《澳門特區藥品名錄接受業界索取》PDF 与 2020 年新闻均说明：**「Listas de Medicamentos existentes no Mercado na RAEM」以光盘/向藥物事務廳索取**（药房、药厂、批发商、药剂师等），并未提供公开下载。
- **data.gov.mo（澳門政府數據開放平台）**：首页 200（SPA，4.7 KB 壳）；本轮按 CKAN 惯例探测 `package_list/package_search` 均返回 HTML 壳而非 JSON，**未找到「注册药物名单」数据集**；需后续用浏览器会话/站内搜索继续确认（本轮时间盒内未找到公开批量数据）。
- **Boletim Oficial（澳門公報）**：每期「extracto de despacho」逐条公布新注册药物（注册号、商品名、剂型、活性成分/含量等），官方且可查，但为**逐条 PDF/HTML 公告**，无「现行全量」批量清单；可作后备来源（高成本，需逐期抓取+解析，且无法保证覆盖全部历史注册）。
- 官方公告描述的名录字段：商品名、剂型、治疗/分类、给药途径、活性成分及含量（**字段本身够用**，但缺公开可再发布载体）。

### 2.2 许可结论（MO）

- 未找到**开放再发布许可**：ISAF/SSM 网站版权保留、无 CC/ODbL 之类条款；data.gov.mo 即便存在数据集也需逐个确认许可；官方名录为索取制（CD），发布权未明示。
- 结论：🔴 **无许可 → 只能链接层**（链 ISAF 查询页/SSM 公告页，不复制名录内容），与 CN 口径一致；如需入库，先书面确认再发布许可 + 批量文件可得性。

### 2.3 入库难度与建议（MO）

- 难度：**高**。① 无批量文件；② 站点 403 反爬；③ 逐条 BO 解析成本高且覆盖不完整；④ 无许可。
- 建议：**暂缓入库，先做链接层**：在 About/未来 A4「已知缺口」写「澳門：官方名录为索取制，本站暂不收录，提供 ISAF 资料查询入口」；若用户强需求，下一步优先级 = ① 向 ISAF 发函确认名录数据再发布许可与批量格式；② 评估 BO 公报抓取（先做 200 条抽样证明字段可解析）；③ 两者都过再做 ETL。**不建议**用第三方转载/商业库绕过许可。

## 3. 建议动作（给 Lead）

1. **HK 立项（P1，约 0.5–1 人日）**：ETL + schema HK 迁移 + source 条目 + About 署名；验收：14,275 条入库、成分映射命中率报告（目标 ≥70%）、HK 页面/搜索/U2 横排可用、明确标注无规格。
2. **MO 暂缓（P2）**：链接层 + 缺口说明；发函 ISAF 确认许可/批量（用户授权后再动）。
3. 本轮审计未改任何跟踪文件/DB；如 HK 立项，需要：`db/schema.sql`/`init_db.py` country 枚举、`etl/fetch_hk_dh.py`、`etl/ingest_hk_dh.py`、`docs/许可清单.md` 增一行、About/README 计数同步。

## 4. 证据索引

| 文件（`data/raw/hk_mo/`） | 内容 |
|---|---|
| `hkgov_ckan_en.json` | data.gov.hk `package_show` 完整元数据（资源 URL/format/license 字段、更新频率） |
| `hk_rpp_resource.xml` | HK 官方注册药制品 XML 全量（4.30 MB / 14,275 条 / lastUpdate 2026-10-23） |
| `hk_rpp_sample20.csv` | 前 20 条抽样（字段结构可视化） |
| `hkgov_terms.html/.txt` | data.gov.hk 使用条款全文（许可/归属/免责条款） |
| `hkgov_about_open_data.txt` | DATA.GOV.HK 开放数据政策页文本 |
| `mo_isaf_query.html` + `mo_isaf_chunk_*.js` | ISAF 查询页与 JS chunk（证明动态检索、无公开 API） |
| `mo_datagov_home.html` | data.gov.mo 首页壳（非 CKAN JSON 响应） |
| `mo_isaf_post.html` | ISAF 资讯页（备用链接层） |

探针/分析脚本与统计：`.tmp/hk-mo/probe_hk.py`、`probe_hk2.py`、`analyze_hk.py`、`probe_mo.py`、`final_probe.py`、`hk_xml_stats2.json`、`probe_mo_log.json`。

_本报告只读审计：未写 `data/drugs.db`、未改 `site/build.py`、未跑 git/发布；XML/PDF 仅作审计缓存，未入库。_
