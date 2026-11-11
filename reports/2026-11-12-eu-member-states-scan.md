# 欧盟成员国药品数据源扫描（27 国）· 第一版

日期：2026-11-12 ｜ 工位：phaseb-plan ｜ 任务：task-12
范围：用户 2026-11-12 问「按欧盟成员国抓取，哪些能抓」→ 一张可决策的 27 国矩阵（A / B / C / D）
纪律：只查官方页面与官方许可页；**不登录、不绕 WAF、不下载受限数据、不碰第三方爬库**；判不了标「待确认」并写清缺哪条证据。所有结论带证据 URL。
前置结论直接引用、不重复查：NL（`licentieonbekend` → C，已发信）、IE（HPRA 条款禁止 → D）、ES（AEMPS CIMA 已在库，许可待确认）、EU 区域层（CC BY 4.0 → A）。

---

## 0. 一句话结论

**欧盟 27 国里，现在就能「入库 + 再发布」的只有 2 个成员国：法国（FR）和捷克（CZ）。**
法国是最优试点（开放许可最硬、字段最全、月度全量、实测 15,799 个制剂 / 20,908 个包装 / 32,449 条成分），
捷克是第二个（条款明示允许商用与再分发、44 列 CSV 含规格/剂型/ATC/MAH/状态）。
德国被普遍误判为「可抓」——GovData 上 BfArM 的药品数据集**只有统计计数**（dl-de/by-2.0），产品清单在 AMIS 里只有网页查询，没有批量。
比利时 SAM 是隐藏的高价值源（实时全量 XML 公开可下载），但**再利用许可原文没找到**，按本站纪律只能先发信、不能先入库。

| 结论 | 数量 | 国家 |
|---|---|---|
| **A（可入库 + 可再发布）** | 2 成员国 + 1 区域层 | **FR、CZ**；EU 区域层（已入库） |
| **B（事实字段 + 链回原文 + 署名）** | 2 | ES（已在库）、SE（CC BY 4.0 但只有检索页） |
| **C（需许可 / 需申请）** | 5 | **BE**（A 候选）、NL（已发信）、DE、IT、PT |
| **D（不可 / 不绕）** | 1 | IE（HPRA 明令禁止） |
| **待确认（缺证据，未查完）** | 4 | DK、FI（WAF 403）、AT、EE |
| **pending（未取证）** | 13 | PL、HU、RO、BG、HR、SK、SI、LV、LT、LU、MT、CY、EL |

> **推荐首批 3 个试点：① 法国 FR ② 捷克 CZ ③ 比利时 BE（先发许可信，同时干跑）**。理由见 §4。

---

## 1. 分级门槛（本站口径，照 task-12 判定规则）

| 级 | 含义 | 硬条件 |
|---|---|---|
| **A** | 可入库 + 可再发布 | 官方源 **＋** 明确开放许可（CC BY / CC0 / OGL / Licence Ouverte / dl-de-by 等）**＋** 可批量（文件或 API）**＋** 字段含商品名/规格/剂型/状态/成分或 ATC/MAH 中 ≥5 项 |
| **B** | 只能「事实字段 + 链回原文 + 署名」 | 官方源可批量（或可稳定取），但**无开放再发布许可**；入库前须 Lead 拍板公开口径 |
| **C** | 需许可 | 有数据，许可未知或需申请 → 写申请信 + 跟进日期，**获批前不入库** |
| **D** | 不可 | 无批量 / 明令禁止再发布与大规模采集 / WAF 反爬（**不绕过**） |

补充：许可未知 **≠** 开放数据（NL 教训，见 `reports/2026-11-11-nl-license-assessment.md`）。**法规公开义务 ≠ 再发布许可**。
「统计/汇总数据有开放许可」**不等于**「产品清单有开放许可」——DE / PT 都栽在这一条上。

---

## 2. 27 国矩阵

### 2.1 已取证国家（12 行，逐条带 URL）

| 国 | 归口机构 | 官方入口（证据） | 批量能力 | 字段（名/规/型/态/成/MAH） | 语言 | 体量 | 许可（原文关键句 + URL） | 级 |
|---|---|---|---|---|---|---|---|---|
| **FR** | ANSM / HAS / CNAM（BDPM 联合发布） | `https://base-donnees-publique.medicaments.gouv.fr/telechargement` | **✅ 月度全量 TXT（TAB 分隔，无表头）**，11 个文件 | 名✅ 规✅（`CIS_COMPO` 的 `dosage` + `CIS_CIP` 包装描述）型✅ 态✅ 成分✅ MAH✅（**无 ATC**） | 法语 | **实测：15,799 制剂 / 20,908 包装 / 32,449 成分行** | ✅ **Licence Ouverte（etalab-2.0）**：「Vous êtes libres de : Reproduire, diffuser, redistribuer et exploiter les données」，条件为「不改变数据含义 + 必须注明来源与更新日期」；页脚「Sauf mention contraire, tous les contenus de ce site sont sous licence etalab-2.0」 | **A** |
| **CZ** | SÚKL | `https://opendata.sukl.gov.cz/katalog-otevrenych-dat/databaze-lecivych-pripravku-dlp` | **✅ 月度 ZIP（CSV 多表）**，`DLP20261027.zip` 8,6 MB | 名✅（`NAZEV`/`NAZEV_REG`）规✅（`SILA`）型✅（`FORMA`）态✅（`REG`/`DODAVKY`）成分✅（`LL`/`dlp_latky.NAZEV_INN`）MAH✅（`DRZ`）**+ ATC_WHO✅ + 包装 `BALENI`** | 捷克语 | 8.6 MB zip；44 列产品表（`dlp_lecivepripravky`），**行数未数**（含 SLP/PZLÚ） | ✅ **开放数据使用条款**：「šířit – kopírovat, distribuovat a sdělovat veřejnosti」「využívat komerčně」，条件「必须注明 SÚKL 为来源」「不得改变或歪曲数据含义」；**但明确排除第三方知识产权文档** | **A** |
| **SE** | Läkemedelsverket | `https://www.lakemedelsverket.se/sv/sok-lakemedelsfakta?activeTab=3`（登记于 data.europa.eu，数据集名 *A Completed Search With all Medicines*） | ⚠️ **弱**：只有检索页（可导出 Excel），**无批量文件/API** | 名✅ 型✅ 态✅（含批准/注册/暂时撤回/注销）成分✅ MAH 待核 | 瑞典语 | 全量注册库，**每晚更新** | ✅ **CC BY 4.0**（data.europa.eu 该数据集 distribution 声明 `CC_BY_4_0`） | **B**（许可够、批量不够） |
| **ES** | AEMPS | `https://www.aemps.gob.es/aviso-legal/`（CIMA 已入库 25,395 条） | ⚠️ 结构化查询（CIMA 内部接口），无官方批量导出条款 | 名✅ 规✅ 型✅ 态✅ 成分✅ MAH✅ | 西语 | **已在库 25,395** | 🟡 **Aviso legal**：允许「全部或部分复制，须明确引用出处并注明文件最后更新日期」——**非开放许可、无批量授权条款** | **B**（现状，待法务确认可升 A） |
| **BE** | FAMHP / eHealth / SMALS（SAM） | `https://www.samportal.be/fr/sam/access`（导出）＋`https://www.faag.be/en/human_use/medicines/medicines/information_about_medicines/authentic_source_of_medicines_sam`（说明） | **✅ 全量 XML 导出**，每天多次；Webservice 需 eHealth 证书（**不用**） | 名✅ 规✅ 型✅ 态✅（可及性）成分✅（INN 簇）MAH✅ + 价格/报销 | 法语 / 荷兰语 | 全量，实时同步 | 🟡 **矛盾**：FAMHP 页称 SAM 是「open source database」「made available as **open data**」、导出「librement (sans contrôle d'accès) accessibles au public」；**但未找到任何再利用许可条款原文**（无 CC、无 OGL、无 smals/FAMHP 使用条款命中） | **C**（A 候选，就差许可原文） |
| **NL** | CBG-MEB | `https://www.geneesmiddeleninformatiebank.nl/metadata.csv` | ✅ 每周 CSV（竖线分隔，16.4 MB） | 名✅ 规✅ 型✅ 态✅ 成分✅ MAH✅ | 荷兰语 | 16,416,087 B / 每周 | 🟡 **许可未知**：国家目录 `dct:license = licentieonbekend`，口径页定义「许可未知 = 无再利用许可，Open Data? Nee」；法定依据仅公开义务 | **C**（已发信 2026-11-11） |
| **DE** | BfArM（AMIS / PharmNet.Bund） | `https://www.govdata.de/ckan/api/3/action/package_search?q=Verkehrsfähige Arzneimittel` → 数据集 *Verkehrsfähige Arzneimittel im Zuständigkeitsbereich des BfArM* | ❌ **产品清单无批量**；GovData 上的 BfArM 药品数据集**只有按月统计计数**（`verkehrsfaehigearzneimittel.csv`、`abgabestatusverkehrsfaehigearzneimittel.csv`） | 统计表只有「按审批程序类型分的数量」——**0 个产品字段** | 德语 | 无产品级数据 | ✅ **dl-de/by-2.0**（署名）——**但只覆盖统计表**，不覆盖产品清单 | **C**（需向 BfArM 申请 AMIS 批量） |
| **IT** | AIFA | `https://www.aifa.gov.it/en/open-data`（Open Data 栏）；`https://dati.gov.it/opendata/api/3/action/package_search?fq=organization:aifa` → **count = 0** | ❌ 无产品级开放数据集；Banca Dati Farmaci 为检索式 | — | 意大利语 | — | 待确认：AIFA Open Data 页存在，但正文未能自动提取；国家目录（dati.gov.it）**无 AIFA 发布的产品级数据集** | **C** |
| **PT** | INFARMED | `https://dados.gov.pt/api/1/datasets/?q=medicamentos`（API，61 条命中） | ⚠️ 只有**汇总/统计**数据集（支出、生物类似药、战略储备），**无产品清单** | 汇总数据无产品字段 | 葡萄牙语 | — | ✅ 汇总数据集标 `cc-by`——**不覆盖 Infomed 产品库**；产品库下载需登录/授权 | **C** |
| **DK** | Lægemiddelstyrelsen | `https://laegemiddelstyrelsen.dk/da/tilskud/priser/medicinpriser-for-erhverv/`（对企业的价格文件）＋`.../eksempel-paa-medicinprisfiler/` | ✅ 价格文件成批下载（示例页公开） | 名✅ 规✅ 型✅ ATC✅ 价✅ 态⚠️ MAH⚠️ | 丹麦语 | 全量包装级，定期 | 🟡 **待确认**：站内有版权页 `https://laegemiddelstyrelsen.dk/da/om/ophavsret-og-logo/`（HTTP 200），但**正文未能提取**；缺「再利用许可原文」这一条证据 | **待确认** |
| **FI** | Fimea | `https://fimea.fi/tietoa_fimeasta/avoin-data`；`https://avoindata.fi/data/api/3/action/package_search` | ? | ? | 芬兰语 | ? | ❌ **取不到**：`fimea.fi` 返回 **HTTP 403（Cloudflare 挑战）**、`avoindata.fi` 同样 403 → **不绕过**；data.europa.eu 上有 1 个 Fimea 数据集标 `CC_BY_4_0`（标题未解析） | **待确认**（需人不带自动化地打开） |
| **AT** | BASG / AGES | `https://www.basg.gv.at`（Arzneimittelsuche 检索） | ❌ 未见批量入口 | ? | 德语 | ? | 未取证：data.europa.eu 按 BASG/AGES 过滤**0 命中**；缺「官方数据下载页是否存在」的证据 | **待确认** |
| **EE** | Ravimiamet（国家药品局） | `https://www.ravimiregister.ee/publichomepage.aspx?pv=PublicDownloads` | **疑似 ✅**（页面名叫 PublicDownloads，HTTP 200），但为 JS 应用，**文件清单未取到** | ? | 爱沙尼亚语 | ? | 🟡 未声明：data.europa.eu 登记了 *Register of Medicinal Products* 但 `license` 为空；缺「下载文件清单 + 许可声明」两条证据 | **待确认**（潜力大，优先补查） |
| **IE** | HPRA | `https://assets.hpra.ie/products/xml/latestHumanlist.xml` | ✅ 每日 XML 13.5 MB | 名✅ 型✅ 态✅ 成分✅ MAH✅ 规❌ | 英语 | 13,506,775 B / 每日 | 🔴 **明确禁止**：Terms of use 禁止 reproduce/republish/redistribute 及「large scale collecting or harvesting of data」 | **D** |

### 2.2 pending 国家（未取证，只列归口机构与预计入口，**不得据此入库**）

| 国 | 归口机构 | 预计入口 | 下一步 |
|---|---|---|---|
| PL | URPL / eZdrowie | `rejestrymedyczne.ezdrowie.gov.pl`（RPL 注册库） | 查 RPL 有无 API/导出 + 国家目录 `dane.gov.pl` 许可（本次 API 连接失败） |
| HU | OGYÉI | `ogyei.gov.hu` 药品数据库 | 查批量与许可 |
| RO | ANMDM | `anm.ro` Nomenclatorul medicamentelor | 同上 |
| BG | BDA（Изпълнителна агенция по лекарствата） | `bda.bg` 药品注册库 | 同上 |
| HR | HALMED | `halmed.hr` Baza lijekova | 同上 |
| SK | ŠÚKL（斯洛伐克） | `sukl.sk` Databáza liekov | 同上 |
| SI | JAZMP | `jazmp.si` Register zdravil | 同上 |
| LV | ZVA | `zva.gov.lv` Zāļu reģistrs | 同上 |
| LT | VVKT | `vvkt.lt` Registruotų vaistų sąrašas | 同上 |
| LU | Ministère de la Santé | `sante.lu` 药品注册 | 同上（体量小） |
| MT | Medicines Authority | `medicinesauthority.gov.mt` 产品列表 | 同上（体量小） |
| CY | Pharmaceutical Services | `moh.gov.cy/phs` | 同上（体量小） |
| EL | EOF（ΕΟΦ） | `eof.gr` 国家药品目录 | 同上 |

---

## 3. 逐国证据链（只写取到的原文与实测，不写推测）

### 3.1 FR — ANSM「Base publique des médicaments」（BDPM）→ **A，第一优先**

- **许可原文（决定性）**：下载页写明 *«Vous êtes libres de : Reproduire, diffuser, redistribuer et exploiter les données»*，条件两条：①「Ne pas altérer les données, ne pas en dénaturer leur sens, mentionner impérativement la source … et la date de leur mise à jour」（《CADA 法》第 12 条）；② 必须持续跟进更新，否则 ANSM/HAS/CNAMTS 不担责。并给出「texte complet de la licence ouverte (pdf)」。
  页脚：*«Sauf mention contraire, tous les contenus de ce site sont sous licence etalab-2.0»*。
  → 证据：`https://base-donnees-publique.medicaments.gouv.fr/telechargement`、`https://base-donnees-publique.medicaments.gouv.fr/docs/telechargement/licence_bdpm.pdf`、`https://github.com/etalab/licence-ouverte/blob/master/LO.md`
- **实测（2026-11-12 下载到 `.tmp/eu-scan/`，只读清点）**：

  | 文件 | 字节 | 行数（含数据行，**无表头**） | 用途 |
  |---|---|---|---|
  | `CIS_bdpm.txt` | 3,149,903 | **15,799** | 制剂主表：名称、剂型、给药途径、授权状态、程序类型、上市状态、授权日期、MAH、强化监测 |
  | `CIS_CIP_bdpm.txt` | 4,151,945 | **20,908** | 包装/规格：包装描述、CIP13、报销率、价格 |
  | `CIS_COMPO_bdpm.txt` | 2,741,312 | **32,449** | 成分与剂量：物质名、`dosage`、参照单位、成分性质（SA/FT）、CAS |

  首行样例（`CIS_bdpm`）：`61266250 ⇥ A 313 200 000 UI POUR CENT, pommade ⇥ pommade ⇥ cutanée ⇥ Autorisation active ⇥ Procédure nationale ⇥ Commercialisée ⇥ 12/03/1998 ⇥ [空] ⇥ [空] ⇥ PHARMA DEVELOPPEMENT ⇥ Non`
  更新时间：页首「Dernière mise à jour le **03/11/2026**」，月度全量。
- **ETL 注意（必须写进实现）**：文件是 **TAB 分隔、无表头行、非 UTF-8**（按 UTF-8 读首行出现替换字符，必须按 **latin-1 / Windows-1252** 解码）；`CIS_bdpm` 的 9/10 列实测为空，不要按「列数对不上」直接丢弃。
- **缺口**：BDPM **不含 ATC**（ATC 要从别处补或留空）；也不含「是否在售于药房」之外的库存级信息。

### 3.2 CZ — SÚKL 开放数据「DLP」→ **A，第二优先**

- **许可原文（决定性）**：*«Data … smí uživatel: šířit – kopírovat, distribuovat a sdělovat veřejnosti, využívat a citovat, **využívat komerčně**»*，条件：*«jako zdroj dat musí být uveden SÚKL»*、*«mohou být použita pouze takovým způsobem, který nijak nemění nebo neupravuje jejich význam/smysl»*、再分发须附条款链接。
  **排除项（重要）**：*«tyto podmínky užití neplatí pro dokumenty, na něž se vztahují práva duševního vlastnictví třetích stran»* → **SPC / PIL / OBALY 三个 zip（PDF/DOC 原文）不可再发布**，只能取 DLP 的 CSV 事实表。
  证据：`https://opendata.sukl.gov.cz/podminky-uziti-otevrenych-dat`
- **实测**：`DLP20261027.zip` **8,6 MB**，月度更新（发布日 27.10.2026）；字段说明 `DLP_datove_rozhrani20260701.csv` **13,356 B**，逐列读到：
  - `dlp_lecivepripravky`（44 列）：`KOD_SUKL`、`NAZEV`（名称）、`SILA`（**规格**，按剂型折算的定量）、`FORMA`（剂型）、`BALENI`（包装量）、`CESTA`（途径）、`DRZ`/`AKT_DRZ`（**MAH**）、`REG`（注册状态）、`RC`（注册号）、**`ATC_WHO`**、`LL`（成分列表）、`VYDEJ`（处方分类）、`DDDAMNT_WHO`/`DDDUN_WHO`（DDD）、`TYP_LP`、`PRAVNI_ZAKLAD_REGISTRACE`（审批程序）
  - 配套码表：`dlp_atc`（ATC 捷克语/英语名）、`dlp_formy`（剂型+EDQM 码）、`dlp_cesty`（途径+EDQM 码）、`dlp_latky`/`dlp_lecivelatky`（**INN** 优先名 + 英/捷名）、`dlp_jednotky`（单位）
- **判定**：商品名/规格/剂型/状态/成分/MAH 六项全中，另有 ATC 与 EDQM 码 → 字段质量**高于**现有 10 个市场的大部分。
- **缺口**：产品表**不按成分拆行**（成分在 `LL` 逗号串 + 码表里），复方药的成分-剂量配对要在 `dlp_latky` 层再拼；行数未数（待干跑统计）。

### 3.3 SE — Läkemedelsverket → **B**

- data.europa.eu 数据集 *A Completed Search With all Medicines*（publisher `Läkemedelsverket`）：*«A list of all medicines … in Sök läkemedelsfakta. … all approved, registered, temporarily withdrawn, and deregistered medicines … updated every night»*，distribution 许可 **`CC_BY_4_0`**，但 access URL 是**检索页** `https://www.lakemedelsverket.se/sv/sok-lakemedelsfakta?activeTab=3`，**无文件/API**。
- 同机构另有 *Substitutable Medicinal Products*（CC BY 4.0）——**注意**：那是可替换组清单，涉及§1.3 红线（不做替代推荐），只能作为「同成分同规格」的事实证据，**不得**用于推荐替换。
- 判定：许可 ✅、批量 ❌ → **B**（只能事实字段 + 链回原文）。若日后找到官方 XML/JSON 全量导出，可直接升 A。

### 3.4 DE — BfArM → **C（被误判最多的一国）**

- GovData 上 BfArM 的药品数据集只有：*Verkehrsfähige Arzneimittel im Zuständigkeitsbereich des BfArM*，描述 = *«**Anzahl** der verkehrsfähigen Arzneimittel … geordnet nach der Art des Zulassungsverfahrens. Die Zahlen werden monatlich aktualisiert.»*
  → 资源只有两个 CSV：`verkehrsfaehigearzneimittel.csv`、`abgabestatusverkehrsfaehigearzneimittel.csv`，**是计数表，不含任何产品行**。
  许可：`dl-de/by-2-0`（Datenlizenz Deutschland – Namensnennung 2.0），**只覆盖这两个统计文件**。
  证据：`https://www.govdata.de/ckan/api/3/action/package_search?q=Verkehrsfähige Arzneimittel`
- 产品级注册数据在 **AMIS / PharmNet.Bund**，公开侧只有检索界面；批量属 AMIS-Institut（收费/签约）范畴 → 按 §12「不付费买数据」**不推进**，只写申请/问询。
- 判定：**C**。**明确否掉「德国可批量」的假设**——这一条要写进给用户的答复，避免后续工位重复踩。

### 3.5 BE — SAM（Source authentique des médicaments）→ **C，A 候选，价值最高**

- FAMHP 官方说明：*«…is the reference database … made available as an **open source** database by medicines competent authorities»*、*«The information stored in SAM is made available as **open data** through the eHealth platform»*。
  导出：*«Les exports … **librement (sans contrôle d'accès) accessibles au public** et peuvent être téléchargés sur `https://www.vas.ehealth.fgov.be/websamcivics/samcivics/`»*，每天多次生成 full 导出（XML）。
  Web service（DICS v5）需 eHealth 证书、限比利时境内服务方 → **不用**。
  证据：`https://www.faag.be/en/human_use/medicines/medicines/information_about_medicines/authentic_source_of_medicines_sam`、`https://www.samportal.be/fr/sam/access`
- **缺的证据**：**再利用许可原文**。「open data」是页面形容词，不是许可条款；SAM 由 FAMHP + RIJZIV + CBIP + FOD Economie + APB 多方供数，**各方权利未在页面上说明**（CBIP 的 INN 簇、FOD 的价格尤其可能带第三方权利）。→ 与 NL 同类风险，**先发信**。
- 判定：**C**。一旦拿到书面/条款级许可，直接升 **A**（字段、更新频率、体量都是第一梯队）。

### 3.6 IT / PT — **C（有门户，没产品清单）**

- IT：`https://dati.gov.it/opendata/api/3/action/package_search?fq=organization:aifa` → **count = 0**（国家开放数据目录里 AIFA 没有作为发布者）。`q=medicinali` 的 17 条命中全是**药店名录 / 消费价格指数 / 地方 ASL 数据**，无产品注册库。AIFA 自己 `/en/open-data` 页存在（HTTP 200）但正文是导航壳，未能提取。
- PT：`https://dados.gov.pt/api/1/datasets/?q=medicamentos` → 61 条，INFARMED 发布的全部是**统计/汇总**（医院支出、生物类似药、战略储备库存），许可 `cc-by`；**产品清单（Infomed）不在开放目录里**，其下载入口带登录/授权控制。

### 3.7 其余

- **FI**：`fimea.fi/tietoa_fimeasta/avoin-data` 与 `avoindata.fi` 的 CKAN API **均 403**（Cloudflare 挑战）→ 按纪律不绕，标待确认。
- **AT**：data.europa.eu 按 BASG/AGES 过滤 0 命中；BASG 药品查询是检索式，未见下载页。
- **EE**：`ravimiregister.ee/...PublicDownloads` 存在但是 JS 应用，取不到文件清单；data.europa.eu 登记的 *Register of Medicinal Products* 许可为空。**这是 pending 里最值得先补的一国**（页面名直接叫 PublicDownloads）。

---

## 4. 推荐首批 3 个试点

| # | 试点 | 为什么是它 | 干跑（不写库）要产出的数字 | 预计 |
|---|---|---|---|---|
| **1** | **FR** | 唯一「许可最硬 + 字段最全（除 ATC）+ 月度全量 + 体量适中」的 A 类；法语是新语言，但 `name_key` 归一化可复用现有管线 | 15,799 制剂 → 去重后 `name` 数；`CIS_COMPO` 到成分的映射率；`CIS_CIP` 规格解析率（`libellé` 里剂量+包装，需按现有 `strength` 归一化器试）；latin-1 解码校验 0 乱码 | 1.5 天 |
| **2** | **CZ** | 第二个 A 类，字段比 FR 还多（自带 ATC + EDQM 剂型/途径码）；**捷克语**是新语言，但 EDQM 码可跨市场对齐剂型 | DLP 行数、`SILA` 可解析率、`LL` 复方拆行后的成分-剂量配对率、`ATC_WHO` 覆盖率 | 1.5 天 |
| **3** | **BE（SAM）** | 数据质量最高（实时、含规格/剂型/INN 簇/可及性/价格），**导出公开无需登录**；法语+荷兰语正好复用 1 的 fr | **先干跑**：XML 结构与体量、字段命中率；**同时发许可信**，未获批前不写库 | 0.5 天干跑 + 等信 |

**不推荐进首批**：
- **SE**（B，只有检索页）——收益/风险比差，且「可替换组」数据集碰 §1.3 红线，容易做歪。
- **DE**（C，无产品批量）——需要走商务/机构申请，且与 §12「不付费」冲突，只写不推。
- **NL / IE**——已定案（C 等信 / D 不做）。

**排序逻辑**：A 类先做（FR、CZ），第三席给「许可只差一封信、但数据最好」的 BE，而不是给「许可没问题、数据拿不到」的 SE。

---

## 5. 需发许可信清单（获批前一律不写库）

| 优先 | 对象 | 收件切入点 | 要问的三件事（同一封信模板，换语言） | 跟进 |
|---|---|---|---|---|
| **P0** | **BE · FAMHP / eHealth（SAM）** | SAM portal 的 contact 表单 + `samportal.be` 上公开的联系方式；抄送 FOD Economie（价格数据方） | ① SAM 全量 XML 导出可否用于公开非商业参考站？② 适用哪份许可（若能给 CC BY 4.0 或等效书面声明最好）？③ CBIP 的 INN 簇与 FOD 价格属第三方权利，是否可从 SAM 派生再发布，或需剔除？ | 发出后 14 天首查、30 天复审 |
| **P1** | **CZ · SÚKL** | 已有明确条款，**不必发信**；只需一封「确认 DLP 的 CSV 属开放数据条款覆盖、SPC/PIL/OBALY 属第三方文档」的一行确认（降低解释风险） | ① 确认 `DLP` 的 CSV 受开放数据条款覆盖；② 确认 `SPC/PIL/OBALY` 三包不在覆盖范围 | 可与干跑并行 |
| **P2** | **DK · Lægemiddelstyrelsen** | `laegemiddelstyrelsen.dk` 联系页 | ① `medicinpriser-for-erhverv` 价格文件可否公开再发布？② 适用许可（CC BY 4.0？）；③ 是否含 MAH 字段 | 待确认转正前 |
| **P2** | **EE · Ravimiamet** | `ravimiregister.ee` PublicDownloads 联系方式 | ① 下载包格式与字段；② 许可 | 优先补查（潜力大） |
| **P3** | **IT · AIFA** | AIFA Open Data 联系 | ① Banca Dati Farmaci 有无批量导出/API；② 可否给研究用途许可 | 低 |
| **P3** | **PT · INFARMED** | Infarmed 数据授权 | ① Infomed 全量导出条件（是否收费）；② 许可 | 低 |
| **P3** | **DE · BfArM** | AMIS 联系 | ① 公开侧有无产品级下载；② AMIS-Institut 是否有免费学术/非商业通道 | **低（不付费）** |

> ES 不在此表：已在库且现有做法（事实字段 + 署名 + 更新日期）符合 Aviso legal；若要升 A 需 AEMPS 书面确认，属「锦上添花」，排 P3。

---

## 6. 最大风险（按杀伤力排序）

1. **把「官方说 open data」当成许可（BE 会重演 NL）。** FAMHP 页面的「open data / open source database」是形容词，不是许可条款；SAM 是多机构联合供数，CBIP 的 INN 簇与 FOD 的价格可能带第三方权利。**处理：先发信，只做干跑。**
2. **把「统计算放数据」当成「产品清单放数据」（DE / PT 都踩）。** DE 的 `dl-de/by-2.0` 只覆盖两张计数表；PT 的 `cc-by` 只覆盖汇总。**处理：判 A 前必须点开 distribution 看文件里有没有产品行，而不是看目录的许可字段。**
3. **FR 的「不得改变数据含义」+ CZ 的「不得歪曲」= 不能自己重算规格。** 我们的 `strength` 归一化、成分拆分、复方配对都属于「派生」，必须在页面明确「派生自官方字段，原文见来源链接」，且**不覆盖**原文。
4. **CZ 的第三方 IP 排除条款 + FR 的第三方文档** 意味着两国的 **SPC / PIL / 说明书原文**一律不能进站；只能取事实表。误把 `SPC-PIL-obaly` zip 一起入库会直接违约。
5. **「注册 ≠ 在售」的口径漂移。** FR（`état de commercialisation`）、CZ（`REG` + `DODAVKY` 近 6 个月是否供货）、SE（含 deregistered）都同时含「已撤市/未上市」。`coverage.active` 若直接用总行数上报，会把站点现有「在售」口径搞坏；必须按状态列过滤并在 About 明示。
6. **编码与解析坑**：FR 是 latin-1 + 无表头 TAB；CZ 是 CP1250 编码的码表（本次读 schema 需 `[Encoding]::GetEncoding(1250)`）。按 UTF-8 硬读会静默产生乱码药名。

---

## 7. 未完成 / 下一步（写清楚缺哪条证据）

| 项 | 缺什么证据 | 怎么补（不绕过 WAF） |
|---|---|---|
| FI（Fimea） | 数据集清单 + 许可原文（Cloudflare 403） | 由人在浏览器手动打开 `fimea.fi/tietoa_fimeasta/avoin-data` 截图/复制正文；或用 data.europa.eu 上 Fimea 那 1 条 `CC_BY_4_0` 数据集的 distribution URL 反查 |
| SE（全量） | 是否有官方批量文件 | 看 `sok-lakemedelsfakta` 是否有「导出全部」按钮；或问 Läkemedelsverket |
| AT（BASG/AGES） | 是否存在下载页 | 手动核对 `basg.gv.at` 的「Daten / Open Data」栏目 |
| EE（Ravimiamet） | PublicDownloads 的文件清单与许可 | 手动下载一次看文件结构与首页许可声明 |
| DK（Lægemiddelstyrelsen） | 版权页正文 + 价格文件字段 | 手动打开 `.../om/ophavsret-og-logo/`（本次抓取被导航截断） |
| PL（URPL） | RPL 有无 API/导出 | `api.dane.gov.pl` 本次连接失败，换网络重试或手动查 `dane.gov.pl` |
| 其余 12 国 | 全部 | 每个国家 20 分钟：官方注册库页 + 站内「open data/terms」两页 |

---

## 8. 复现命令（本次实测用的）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 现有覆盖率基线（本次读数：10 国 + EU 区域 2,095）
& $py db/q.py "SELECT country, COUNT(*) n FROM product WHERE country IS NOT NULL GROUP BY country ORDER BY n DESC"
& $py db/q.py "SELECT region, COUNT(*) n FROM product WHERE region IS NOT NULL GROUP BY region"

# FR 体量实测（下载到 .tmp，不入库）
$base='https://base-donnees-publique.medicaments.gouv.fr/download/file/'
foreach ($f in @('CIS_bdpm.txt','CIS_CIP_bdpm.txt','CIS_COMPO_bdpm.txt')) {
  Invoke-WebRequest -Uri ($base+$f) -OutFile ".tmp/eu-scan/$f" -UseBasicParsing
  "$f lines=" + (Get-Content ".tmp/eu-scan/$f" -Encoding UTF8).Count   # 生产用 latin-1
}

# CZ 字段表（CP1250 解码）
$r = Invoke-WebRequest -Uri 'https://opendata.sukl.gov.cz/soubory/DLP_datove_rozhrani20260701.csv' -UseBasicParsing
[System.Text.Encoding]::GetEncoding(1250).GetString($r.Content)

# 开放数据目录取证（官方 API，只看不抓数据）
Invoke-WebRequest 'https://dati.gov.it/opendata/api/3/action/package_search?fq=organization:aifa' -UseBasicParsing
Invoke-WebRequest 'https://dados.gov.pt/api/1/datasets/?q=medicamentos&page_size=8' -UseBasicParsing
Invoke-WebRequest 'https://www.govdata.de/ckan/api/3/action/package_search?q=Verkehrsfähige Arzneimittel' -UseBasicParsing
Invoke-WebRequest ('https://data.europa.eu/api/hub/search/search?q=' + [uri]::EscapeDataString('Läkemedelsverket läkemedel') + '&limit=25') -UseBasicParsing
```

---

## 9. 本次没做 / 需要人拍板的

- **没有改 `docs/许可清单.md`**：FR / CZ / BE / DE / IT / PT 的新结论需要按 §5 维护流程登记（含 `license_url` 必填），但那是共享文件且与其他工位有写权重叠 → 交 Lead 决定何时落。
- **没有写库、没有改 `site/build.py`、没有 commit / publish**（按任务写权限）。
- **BE 的许可信需要人决定是否以本站名义发出**（同 NL 的处理方式：起草交人）。
- 第二版（补齐 FI / SE / AT / EE / DK 与 12 个 pending 国）预计还需 4–6 小时；**建议在 FR/CZ 干跑启动后再补**，因为「A 类只有 2 个 + BE 等信」这个结论已经足够驱动下一步排期。

---

# 第二版（task-16，2026-11-12）

> v2 补了 18 国（FI/SE/AT/EE/DK + PL/HU/RO/BG/HR/SK/SI/LV/LT/LU/MT/CY/EL）。**v1 结论除 DK 外全部维持**；
> **新发现一个 A 类：拉脱维亚（LV）**——CC0 1.0 + 全量 XML + 字段 7/7 全中（含 ATC 与 MAH），体积比 FR 还小。
> 仍然：**不绕 WAF**（FI 两个官方域对自动化均 403，标待确认）；所有判定带证据 URL。

## 10. v2 一句话结论

**A 类变成 3 个成员国：法国 FR、捷克 CZ、拉脱维亚 LV。** LV 是这批里性价比最高的一个：
国民目录 `data.gov.lv` 直接给数据集标 **CC0 1.0**，导出**无需登录**，全量 **125 MB XML / 3.0 MB ZIP**，每天更新，
字段 `medicine_name`(LV) + `original_name`(EN) + `strength` + `pharmaceutical_form` + `active_substance`(INN 拉丁) + `atc_code` + `marketing_authorisation_holder` + `status`。
丹麦（DK）从「待确认」升到 **B**（拿到许可原文：可引用+须注明来源，但图片需事先许可）。
希腊（EL）从 pending 升到 **C**（国家目录有药品目录 xlsx/zip，但 `License not specified`）。
**其余 12 国这一轮没打出可入库的源**——多数是国家目录里没有产品级数据集，或入口是 JS 检索页。

## 11. 27 国矩阵 v2（最终表）

| 国 | 归口机构 | 官方入口 | 批量 | 字段≥5 | 许可 | 级 | 变化 |
|---|---|---|---|---|---|---|---|
| **FR** | ANSM/HAS/CNAM | `base-donnees-publique.medicaments.gouv.fr/telechargement` | ✅ 月度 TXT | ✅ 6/6（无 ATC） | Licence Ouverte / etalab-2.0 | **A** | — |
| **CZ** | SÚKL | `opendata.sukl.gov.cz/.../databaze-lecivych-pripravku-dlp` | ✅ 月度 ZIP 8.6 MB | ✅ 7/7 | SÚKL 开放数据条款（等价 CC BY） | **A** | — |
| **LV** | Zāļu valsts aģentūra | `https://data.gov.lv/dati/lv/dataset/latvijas-zalu-registrs` → `dati.zva.gov.lv/zalu-registrs/export/` | ✅ **全量 XML/ZIP/CSV/JSON，每日** | ✅ **7/7（含 ATC + MAH + INN）** | ✅ **CC0 1.0** | **A** | 🆕 **新** |
| **ES** | AEMPS | `aemps.gob.es/aviso-legal/`（CIMA 已在库 25,395） | ⚠️ 无批量条款 | ✅ | Aviso legal（署名+更新日期） | B | — |
| **SE** | Läkemedelsverket | `lakemedelsverket.se/sv/sok-lakemedelsfakta?activeTab=3` | ⚠️ 仅检索页 | ✅ | CC BY 4.0（data.europa.eu 声明） | B | — |
| **DK** | Lægemiddelstyrelsen | `laegemiddelstyrelsen.dk/da/tilskud/priser/medicinpriser-for-erhverv/` | ✅ 价格文件成批 | ✅ 名/规/型/ATC/价 | 「可引用+须注明来源」，图片需事先许可 | **B** | 🔼 待确认→B |
| **BE** | FAMHP/eHealth(SAM) | `samportal.be/fr/sam/access` | ✅ 全量 XML（免登录） | ✅ 7/7 | ❓ 无条款原文（页面自称 open data） | C | — |
| **NL** | CBG-MEB | `geneesmiddeleninformatiebank.nl/metadata.csv` | ✅ 周 CSV 16.4 MB | ✅ | 许可未知（licentieonbekend） | C | — |
| **DE** | BfArM | GovData：*Verkehrsfähige Arzneimittel…* | ❌ 只有统计计数 | ❌ 0/6 | dl-de/by-2.0（仅覆盖统计表） | C | — |
| **IT** | AIFA | `aifa.gov.it/en/open-data` | ❌ 无产品级数据集 | — | 未声明 | C | — |
| **PT** | INFARMED | `dados.gov.pt`（仅汇总集） | ⚠️ 仅统计 | ❌ | cc-by（不覆盖产品库） | C | — |
| **EL** | Υπ. Υγείας / ΕΟΦ | `data.gov.gr/dataset/56dcd10c-68f7-4d8b-9118-66843864f771`（ΚΑΤΑΛΟΓΟΙ ΦΑΡΜΑΚΩΝ，.xlsx + zip） | ✅ 文件可下 | 待核 | **License not specified** | **C** | 🆕 pending→C |
| **IE** | HPRA | `assets.hpra.ie/products/xml/latestHumanlist.xml` | ✅ 每日 XML | ✅ | 🔴 明令禁止再发布/大规模采集 | D | — |
| **FI** | Fimea | `fimea.fi/tietoa_fimeasta/avoin-data` | ? | ? | data.europa.eu 收录 1 条 Fimea 数据集标 CC BY 4.0，资源托管在 `avoindata.suomi.fi` | 待确认 | — |
| **AT** | BASG / AGES | `basg.gv.at`（Arzneimittelsuche） | ? | ? | 无证据 | 待确认 | — |
| **EE** | Ravimiamet | `ravimiregister.ee/publichomepage.aspx?pv=PublicDownloads` | 疑似 ✅（页面名叫 PublicDownloads，JS 应用） | ? | 未声明 | 待确认 | — |
| **LU** | Ministère de la Santé | `data.public.lu` | ❌ 目录里没有药品注册库（只有社保卡等） | — | — | 待确认 | — |
| **PL / HU / RO / BG / HR / SK / SI / LT / MT / CY** | URPL / OGYÉI / ANMDM / BDA / HALMED / ŠÚKL-SK / JAZMP / VVKT / Medicines Authority / Pharm. Services | 见 §13.3 | 未取证 | 未取证 | 未取证 | pending | — |

统计：**A 3（成员国）+ EU 区域层 · B 3 · C 6 · D 1 · 待确认 4 · pending 10 = 27**。

## 12. 新证据链（v2 新增/升级的四个国家 + 三个仍未定的）

### 12.1 LV — 拉脱维亚国家药品注册库 → **A（新，性价比最高）**

- **许可**：`data.gov.lv` 数据集 `latvijas-zalu-registrs`（发布者 `Zāļu valsts aģentūra`）元数据：
  `license_title = "CC0 1.0"`、`license_url = https://creativecommons.org/publicdomain/zero/1.0/`
  → **CC0 1.0（公有领域贡献，无署名义务）**，是本轮唯一一个 **CC0** 而非 CC BY 的源。
  证据：`https://data.gov.lv/dati/lv/dataset/latvijas-zalu-registrs`；
  元数据 API：`https://data.gov.lv/api/3/action/package_search?q=Latvijas%20Z%C4%81%C4%BCu%20re%C4%A3istrs`
- **数据集自述（拉脱维亚语）**：*«Zāļu reģistra elektroniskā versija ietver zāļu nosaukumus, zāļu formas, aktīvo vielu starptautiskos nosaukumus, stiprumu/koncentrāciju, anatomiski terapeitiski ķīmiski klasifikācijas (ATĶ) kodus, zāļu reģistrācij…»*
  （电子版含：药品名称、剂型、活性物质国际非专利名、规格/浓度、ATC 码、注册信息…）
- **实测（2026-11-12，HTTP 头 + 抽样前几 KB，未下全量）**：
  | 资源 | 字节 | 说明 |
  |---|---|---|
  | `HumanProducts.xml` | **124,930,581**（125 MB，`text/xml;charset=UTF-8`） | 全量主文件，`Last-Modified: Wed, 11 Nov 2026 03:25:59 GMT`（每日） |
  | `HumanProducts.xml.zip` | **3,034,682**（3.0 MB） | **实际取数用这个** |
  | `zr-prd-status.csv` | 1,416,333 | 产品状态码表（CSV/JSON/XML 三格式） |
  入口：`https://dati.zva.gov.lv/zalu-registrs/export/HumanProducts.xml`（免登录、无 WAF）
- **字段（实测 XML 元素名，逐条 `<product>` 一层平铺）**：
  `product_id`、`original_name`（**英文原名**）、`medicine_name`（**拉脱维亚语名**）、`short_name`、`authorisation_no`、
  `date_of_authorisation`、`legal_status`（处方/非处方）、`legal_bases_code`/`legal_bases_text`、`strength`/`strength_lv`、
  `pharmaceutical_form`（英文）/`pharmaceutical_form_lv`、`active_substance`（**INN 拉丁名**，如 `Dexpanthenolum`）、
  `marketing_authorisation_holder`、`manufacturer`、`parallel_importer`、`exp_country`、**`atc_code`**、`status`、`prd_removed`、
  `remove_date`、`sell_stop_date`、`package`/`package_en`/`package_size`、`product_strength`（包装级规格）……
  → **名/规/型/态/成分/ATC/MAH 七项全中**，另有英-拉双语名与剂型，跨市场匹配成本比 FR 低。
- **ETL 注意**：① 含 `authorisation_procedure = "Paralēlais imports"`（平行进口）与 `"Nereģistrētas zāles"`（未注册药品）两类行，须按状态列过滤；
  ② 125 MB XML 必须**流式解析**（`iterparse`），不要一次性 `read()`；③ 拉脱维亚语变音（ā/č/ē/ģ/ī/ķ/ļ/ņ/š/ū/ž）要做折叠，`original_name` 可缓解。

### 12.2 DK — 丹麦 → **B（拿到许可原文，从「待确认」升级）**

- **许可原文（决定性，英文版页，Updated 21 August 2025）**：
  *«You are welcome to **use and quote content** from our website and publications, etc., **provided that you explicitly state the Danish Medicines Agency as the source**. You may also use our images and illustrations in your own texts and publications, provided that you explicitly state the Danish Medicines Agency as the source **and have obtained prior permission from the Agency**. Only the Danish Medicines Agency is permitted to use its logo.»*
  证据：`https://laegemiddelstyrelsen.dk/en/about/copyright-and-logo/`
- 判定：**B**。允许「使用并引用」+ 强制署名，**未禁止再分发、未限制商用**；但 ① 不是命名许可（无 CC/OGL 标识）；② 图片与插图须事先许可 → **只取事实字段，不用任何图片/logo**。
- 批量：`Medicinpriser for erhverv` 对企业开放成批价格文件（示例页公开）；`Varenumre`（商品号）+ 价格，包装级。字段：名/规格/剂型/ATC/价格/商品号。**MAH 与在售状态待核**（缺这一条才没上 A）。

### 12.3 EL — 希腊 → **C（新）**

- `data.gov.gr` 数据集 **ΚΑΤΑΛΟΓΟΙ ΦΑΡΜΑΚΩΝ**（药品目录），发布者 `Υπουργείο Υγείας`（卫生部），成员含 `.xlsx` 与 `.zip`，
  许可字段 = **`License not specified`**。同门户另有 ΕΟΦ 的「Πωλήσεις Φαρμάκων」（销量，非注册库）。
  证据：`https://data.gov.gr/dataset/56dcd10c-68f7-4d8b-9118-66843864f771`
- 判定：**C**（有文件可下，但许可未声明 = 未授权，按 NL 口径不入库）。缺的证据：**许可声明**。

### 12.4 FI / AT / EE — 仍未定（写清卡在哪）

| 国 | 卡点 | 现有最好证据 | 怎么解 |
|---|---|---|---|
| **FI** | `fimea.fi` **403（Cloudflare）**、`avoindata.suomi.fi` CKAN API 也 **403** → 不绕 | data.europa.eu 收录 1 条 Fimea 数据集，`license = CC_BY_4_0`，资源 URL 指向 `avoindata.suomi.fi/data/dataset/3aed5044-325b-4e41-ac12-2f86bd265a63` | 人在浏览器打开该 dataset 页，复制标题+资源清单；若确认是「Lääkevalmisteet 全量」，FI 直接冲 A |
| **AT** | 欧盟门户按 BASG/AGES 过滤 **0 命中**；`data.gv.at/katalog/api` 路径 **404** | BASG 只有 Arzneimittelsuche 检索页 | 手动看 `basg.gv.at` 有无「Open Data / Daten」栏目；或问 BASG |
| **EE** | `ravimiregister.ee/...PublicDownloads` **HTTP 200 但为 JS 应用**，取不到文件清单 | 欧盟门户登记了 *Register of Medicinal Products* 但 `license` 为空 | 人在浏览器点开 PublicDownloads，看导出格式与页脚许可；EE 潜力大（页面名直译「公开下载」） |
| **LU** | `data.public.lu` 目录里**没有**药品注册库（只有社保卡、地址等） | 目录检索结果 | 查 `sante.lu` 是否有国家药品清单；体量小，优先级低 |

### 12.5 13 个 pending 国 —— 这轮查到什么、还缺什么

| 国 | 归口 | 这轮实测 | 结论/缺什么 |
|---|---|---|---|
| **PL** | URPL / eZdrowie（RPL） | `rejestrymedyczne.ezdrowie.gov.pl/rpl/search/public` HTTP 200 但正文只有 "RPL"（JS 应用）；`api.dane.gov.pl` **连接失败** | pending；缺「RPL 有无批量 API/导出 + 国家目录许可」 |
| **HU** | OGYÉI | 欧盟门户无该发布者药品数据集 | pending；缺「Gyógyszeradatbázis 有无导出」 |
| **RO** | ANMDM | `anm.ro/nomenclator/` HTTP 200，正文只有 cookie 声明（JS 应用） | pending；缺「Nomenclator 文件/许可」 |
| **BG** | BDA | `opendata.government.bg` CKAN **连接失败/超时** | pending；缺「国家目录里有无药品数据集」 |
| **HR** | HALMED | `halmed.hr/Lijekovi/Baza-lijekova/` HTTP 200，是**网页检索**（无下载入口） | pending→倾向 C；缺「是否有导出/许可」 |
| **SK** | ŠÚKL（SK） | `data.gov.sk` CKAN 返回非 JSON（接口不可用） | pending；缺「Databáza liekov 批量+许可」 |
| **SI** | JAZMP | `jazmp.si/zdravila/` HTTP 200，可见**月度「进口许可清单」**（`Seznam dovoljenj…`，PDF/列表），非全量注册库 | pending→倾向 C；缺「是否有产品级批量」 |
| **LT** | VVKT | `data.gov.lt` CKAN **500**；`vvkt.lt/registruojamieji-vaistiniai-preparatai` **403** | pending；缺「注册库批量+许可」 |
| **MT** | Medicines Authority | 欧盟门户无命中 | pending；体量小，低优先 |
| **CY** | Pharmaceutical Services | 欧盟门户无命中 | pending；体量小，低优先 |
| **EL** | — | 见 §12.3 | **已定 C** |

## 13. 推荐是否变？——**变，LV 插到第三位**

| 顺位 | 市场 | 理由 | 成本 |
|---|---|---|---|
| 1 | **FR** | 已在取数（task 并行中）；字段 6/6、月度全量 | 已完成评估 |
| 2 | **CZ** | 已在取数（task-15）；字段 7/7、自带 ATC/EDQM 码 | 已完成评估 |
| **3** | **LV（新插队）** | **CC0（无署名义务）+ 3 MB ZIP 一天一版 + 字段 7/7 + 英拉双语名**；比 BE 更省事，且比 FR 多 ATC/MAH | **0.5 天可干跑** |
| 4 | **BE（SAM）** | 数据最好但**许可只在等信**；信到即升 A | 等信 |
| — | DK | B，可做「事实+署名」，但要 Lead 拍板公开口径；缺 MAH/在售状态（补上可冲 A） | 0.5 天补查 |
| — | FI / EE | 一旦人工确认批量+许可，都可能直接是 A，值得 15 分钟人工看一眼 | 人工 |

> 结论：**FR → CZ → LV → BE**。LV 建议单独开一个小任务（取数 + `etl/markets/lv.py` 干跑），不要塞进 FR/CZ 窗口。

## 14. `docs/许可清单.md` 待加行（原文 + URL，交 Lead 统一写；我未改该文件）

> 格式对齐现有表格：`来源ID | 数据/用途 | 许可结论 | 再发布 | 义务 | 风险 | About | 证据`

**① `bdpm_fr`（法国 BDPM）→ ✅ 可再发布**
- 许可结论：**Licence Ouverte / etalab-2.0**
- 原文：*«Vous êtes libres de : Reproduire, diffuser, redistribuer et exploiter les données»*；条件 *«Ne pas altérer les données, ne pas en dénaturer leur sens, mentionner impérativement la source … et la date de leur mise à jour»*
- 证据：`https://base-donnees-publique.medicaments.gouv.fr/telechargement` ；许可 PDF `https://base-donnees-publique.medicaments.gouv.fr/docs/telechargement/licence_bdpm.pdf` ；`https://github.com/etalab/licence-ouverte/blob/master/LO.md`
- 义务：署名「Base de données publique des médicaments（ANSM/HAS/CNAM）」+ 更新日期 + **不改变数据含义**；不得暗示 ANSM/HAS/CNAM 背书
- 风险：**中**（「不得改变含义」对本站的规格归一化/成分拆分有约束，页面须标「派生自官方字段」）

**② `sukl_cz_dlp`（捷克 SÚKL DLP）→ ✅ 可再发布**
- 许可结论：**SÚKL 开放数据使用条款**（无 SPDX 名，功能等价 CC BY；允许商用）
- 原文：*«šířit – kopírovat, distribuovat a sdělovat veřejnosti»*、*«využívat komerčně»*；条件 *«jako zdroj dat musí být uveden SÚKL»*、*«pouze takovým způsobem, který nijak nemění nebo neupravuje jejich význam/smysl»*；再分发须附条款链接；**明确排除第三方知识产权文档**
- 证据：`https://opendata.sukl.gov.cz/podminky-uziti-otevrenych-dat` ；数据集 `https://opendata.sukl.gov.cz/katalog-otevrenych-dat/databaze-lecivych-pripravku-dlp`
- 义务：署名 SÚKL + 附条款链接 + 不改含义；**不得发布 SPC / PIL / OBALY 三包**
- 风险：**中**

**③ `zva_lv_register`（拉脱维亚国家药品注册库）→ ✅ 可再发布（CC0，最强）**
- 许可结论：**CC0 1.0**（国家目录数据集元数据 `license_title = "CC0 1.0"`、`license_url = https://creativecommons.org/publicdomain/zero/1.0/`）
- 证据：`https://data.gov.lv/dati/lv/dataset/latvijas-zalu-registrs` ；数据 `https://dati.zva.gov.lv/zalu-registrs/export/HumanProducts.xml.zip`（3.0 MB，每日）
- 义务：CC0 **无强制义务**；本站仍按惯例署名「Zāļu valsts aģentūra（ZVA）, Latvijas Zāļu reģistrs」
- 风险：**低**

**④ `laegemiddelstyrelsen_dk`（丹麦药品局价格/商品文件）→ 🟡 事实+署名（B）**
- 许可结论：**「可引用+强制署名」，非命名开放许可；图片/插图需事先许可**
- 原文：*«You are welcome to use and quote content from our website and publications, etc., provided that you explicitly state the Danish Medicines Agency as the source.»*；*«…images and illustrations … provided that you explicitly state the Danish Medicines Agency as the source and have obtained prior permission from the Agency»*；*«Only the Danish Medicines Agency is permitted to use its logo.»*
- 证据：`https://laegemiddelstyrelsen.dk/en/about/copyright-and-logo/`
- 义务：署名 + **不用其 logo / 不用其图片**；只存事实字段
- 风险：**中**

**⑤ `data_gov_gr_catalogues`（希腊药品目录）→ ⚪ 不入库（C）**
- 许可结论：**License not specified**（未授权，按 NL 口径处理）
- 证据：`https://data.gov.gr/dataset/56dcd10c-68f7-4d8b-9118-66843864f771`
- 义务：获批前**不入库、不上线**；下一步发信确认（或放弃，希腊体量小）

> 其余不变：`eu_union_register` / `ema_medicines` ✅（v1 已登记）；`cbg_meb_nl` 🟡（已发信）；`hpra_ie` 🔴；`cima` 🟡；SAM（BE）**暂不建行**，等许可信回复后再登记，避免出现「已登记但无许可依据」的行。

## 15. v2 新增风险

1. **LV 的「在售」判定有三个开关**：`status`、`prd_removed`、`sell_stop_date` 必须联合使用；且库里混着「平行进口」与「未注册药品（Nereģistrētas zāles）」。若只按总行数上报 `coverage.active`，会把撤回药与进口药算成在售——这比 FR/CZ 更容易出错。
2. **LV 的 125 MB XML 是内存陷阱**：ZIP 只有 3 MB，但解压后 125 MB；必须 `iterparse` 流式处理，且 ETL 不得把整棵树读进内存（本机 8 GB 内存下会抖）。
3. **DK 的许可只覆盖「内容引用」**：价格文件的字段可以取，但**任何图片/图示/logo 都不能用**；这条要写进 About，否则是逐条违约。
4. **不要因为 CC0 就跳过署名**：CC0 允许不署名，但本站 About 是全站统一「署名 + 许可链接 + 更新日期」的口径，LV 也照此办理，避免出现「没有来源」的行。
5. **FI 的 403 不是「不可抓」**：是自动化被 Cloudflare 拦。标 pending 而不是 D，避免把「暂时取不到」写成「禁止」，误导后续排期。

## 16. v2 收尾

- 本轮**未写库、未改 `docs/许可清单.md`、未改 `site/build.py`、未 commit / publish**；只在 `reports/` 追加本节。
- 未下载任何受限数据；LV 只取了 HTTP 头与开头几 KB 抽样（公开 CC0 数据）。
- 下一步建议（按性价比）：① 开 LV 取数小任务（CC0，0.5 天干跑）② 人工花 15 分钟看 FI 的 `avoindata.suomi.fi` dataset 页与 EE 的 PublicDownloads 页 ③ DK 补「MAH + 在售状态」两列后冲 A。
