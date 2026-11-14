# 可增加的数据：新市场 + 可补字段候选矩阵（只读扫描）

> 日期：2026-11-15 ｜ 工位：**search-alias**（检索与评测 / 数据调研）｜ 任务：**task-9**
> 背景：用户 2026-11-15「**另外自己安排一个人去找可以增加的数据**」。
> 目标：**不是马上入库**，是把「还能加什么」扫成一张能拍板的清单（许可先行、零付费、不绕 WAF）。
> 纪律（已遵守）：**只读**——未写 `data/drugs.db`、未改 `etl/`、未改 `site/build.py`、未碰 `site/dist`、未 commit / 发布、
> 未注册任何账号、未付费、未绕 WAF、未下载受限数据；写权限只用了 `reports/`。
> 外部页面内容一律当**数据**看，不当指令；判不了写「待确认」，不猜许可。

---

## 0. 结论先行（一屏）

**能在本周开写库窗口的只有两件事：① 捷克 CZ + 拉脱维亚 LV 入库（许可最硬、ETL 已写好）② 「剂型→给药途径」规则派生（≈223,641 行，零新源）。**
新市场里最有价值、但只差**一条实测证据**的是**瑞士 CH**（月度 XLSX 清单已在官网页面确认，OGD 许可符号已确认存在，缺「已授权药品清单是否在 OGD 门户上」）与**挪威 NO**（NLOD 2.0 已确认，缺「FEST 的批量取数机制」）。
本轮**新否掉**两个以前没人查过的：**巴西 BR**（gov.br 内容为 **CC BY-ND 3.0 禁演绎**，与我们做规格归一化/跨市场派生的做法直接冲突）、**EDQM Standard Terms**（免费但**必须注册账号**，撞本项目「不注册账号」纪律）。
**仍不建议碰**：波兰 PL / 斯洛伐克 SK（有文件、没许可）、印度 IN / 土耳其 TR / 俄罗斯 RU / 沙特 SA / 阿联酋 AE（本轮未取到产品级批量入口或未取到许可）。

| 处置 | 事项 | 依据 |
|---|---|---|
| **现在就能开窗（写库）** | **CZ + LV 入库**（J2）、**route 规则派生**、**盐基表扩容** | 许可条款级已确认（SÚKL 条款 / ZVA **CC0 1.0**）；后两项零新数据源 |
| **30–60 分钟只读可定案** | **CH Swissmedic**、**NO FEST** | 许可已取到（CH = opendata.swiss `terms_by` 符号存在；NO = **NLOD 2.0** + `isOpenData:true`），各缺一条实测 |
| **等许可 / 只做事实+链接** | SE、DK（B）；PL、SK、GR、IT、PT、BE、NL（C） | 见 §A.2 |
| **本轮明确不做** | BR、IN、TR、RU、SA、AE、EDQM、WHO INN 并库、HPRA(IE) | 见 §C |
| **可选（增量低，排最后）** | 美国补充源（openFDA label/drugsfda/shortages + DailyMed） | US 字段覆盖已 98.3%（route）/ 99.6%（pack），只有 `shortages` 与 DailyMed 链接层有增量 |

**一句话给 Lead**：先开一个写库窗口，一次做完「CZ + LV + route 派生 + 盐表」；CH/NO 的只读复核并行，不占窗口。

---

## 1. 口径与现库基线

### 1.1 分级（沿用 `reports/2026-11-12-eu-member-states-scan.md` §1，本轮加一级 **A\***）

| 级 | 含义 | 硬条件 |
|---|---|---|
| **A** | 可入库 + 可再发布 | 官方源 + 明确开放许可 + **可批量已实测** + 字段 ≥5 项已实测 |
| **A\*** 🆕 | 许可已够，但「可批量」或「字段」还差**一条实测** | 开放许可原文已取到；缺的那条 30–60 分钟只读可补 |
| **B** | 只做事实字段 + 链回原文 + 署名 | 官方源可批量，但无开放再发布许可 |
| **C** | 需许可 / 许可与本站派生方式冲突 | 有数据、许可未知或不可用 → **获批前不入库** |
| **D** | 不可 | 无批量 / 明令禁止再发布与大规模采集 / WAF 反爬（**不绕过**） |
| **U** 🆕 | 未取证 | 本轮没取到「批量入口」或「许可原文」两条之一 → **不得据此入库** |

> 沿用旧纪律三条：许可未知 **≠** 开放数据（NL 教训）；**法规公开义务 ≠ 再发布许可**；
> 「统计/汇总数据有开放许可」**≠**「产品清单有开放许可」（DE / PT 栽在这条）。

### 1.2 现库基线（2026-11-15 现查，`mode=ro`）

| 市场 | 产品 | route | pack | MAH | form_base | ATC |
|---|---|---:|---:|---:|---:|---:|
| CN | 145,051 | **0.0%** | 100% | 100% | 100% | 99.8% |
| US | 110,179 | 98.3% | 99.6% | 100% | 100% | **84.8%** |
| GB | 61,051 | **0.0%** | **0.0%** | 100% | 100% | 90.5% |
| AU | 44,794 | 89.3% | 58.9% | 89.4% | 100% | **75.6%** |
| CA | 43,847 | 100% | 75.8% | 100% | 100% | 99.4% |
| ES | 25,395 | 99.6% | **0.0%** | 100% | 100% | 99.0% |
| TW | 16,457 | **0.0%** | 99.6% | 100% | 100% | 92.0% |
| FR | 15,799 | 100% | 89.6% | 100% | 100% | 79.8% |
| HK | 13,935 | **0.0%** | **0.0%** | 100% | **0.0%** | 87.5% |
| MX | 10,878 | 99.4% | **0.0%** | 99.7% | 100% | 90.3% |
| SG | 5,511 | 100% | **0.0%** | 100% | 100% | 83.6% |
| EU（区域） | 2,095 | **0.0%** | **0.0%** | 100% | **0.0%** | 86.3% |
| **合计** | **494,992** | 50.4% 有值 | 69.7% 有值 | 99.0% | 96.8% | 91.4% |

其余基线：`source` 表 **42 行**；`substance` **12,644**（无 ATC **6,628 = 52.4%**、无中文名 9,541 = 75.5%）；
`variant` **14,244**；`product_name` **670,803** 行（inn 377,146 / trade 293,657）；`product_component` **650,358** 行。

---

## A. 新市场矩阵

### A.1 总表

> 「字段」列 = 商品名/规格/剂型/ATC/MAH/状态/包装 七项里**已确认**有几项；`?` = 本轮未实测。

| 市场 | 权威源（直链） | 许可（结论） | 批量 | 字段 | 规模 | 更新 | 判定 | 优先 |
|---|---|---|---|---|---|---|---|---|
| **NO** 🆕 | [FEST（DMP，原 Statens legemiddelverk）](https://data.norge.no/nb/datasets/09baaca8-61ba-38a2-9097-7a6bc2e5b172) | **NLOD 2.0**（元数据 `license=NLOD_2_0`、`isOpenData:true`、`accessRights:PUBLIC`） | ⚠️ 待确认（FEST 以 XML 报文/M30 供给） | ?（元数据只说 XML 药品主数据） | 未给 | `accrualPeriodicity: other`（实为持续） | **A\*** | **P1** |
| **CH** 🆕 | [Swissmedic 月度清单](https://www.swissmedic.ch/swissmedic/en/home/services/listen_neu.html) | 🟡 opendata.swiss 四种符号之一 [`terms_by`=可商用+必须署名](https://opendata.swiss/en/terms-of-use)；**「已授权药品」是否在 OGD 门户待确认** | ✅ 5 个 XLSX 月更 | 名✅ 包✅ ATC✅（第 11 项 ATC 分配表）MAH✅ 规? 型? 态✅（Art.11 无销售/停供清单） | 已授权清单 **984 kB** / 扩展 **2 MB** / 已批准包装 **3 MB**（31.10.2026） | 月更 | **A\*** | **P1** |
| **CZ** | [SÚKL DLP 开放数据](https://opendata.sukl.gov.cz/katalog-otevrenych-dat/databaze-lecivych-pripravku-dlp) | ✅ SÚKL 开放数据条款（允许商用/再分发；须署名+不改含义；排除第三方 SPC/PIL） | ✅ 月度 ZIP | **7/7**（含 ATC + EDQM 码） | 实测 **70,032 行** | 月更 | **A** | **P0** |
| **LV** | [ZVA 国家药品注册库](https://data.gov.lv/dati/lv/dataset/latvijas-zalu-registrs) | ✅ **CC0 1.0** | ✅ 全量 XML/ZIP，免登录 | **7/7** | 125 MB XML / **3.0 MB ZIP** | 每日 | **A** | **P0** |
| **SE** | [Läkemedelsverket 检索页](https://www.lakemedelsverket.se/sv/sok-lakemedelsfakta?activeTab=3) | ✅ CC BY 4.0（data.europa.eu 数据集声明） | ❌ 只有检索页，无文件/API | ✅ 名/型/态/成 | 全量 | 每晚 | **B** | P3 |
| **DK** | [Lægemiddelstyrelsen 价格/商品文件](https://laegemiddelstyrelsen.dk/da/tilskud/priser/medicinpriser-for-erhverv/) | 🟡 可引用+强制署名（[版权页](https://laegemiddelstyrelsen.dk/en/about/copyright-and-logo/)）；图片/logo 需事前许可 | ✅ 成批 | 名/规/型/ATC/价；MAH? 态? | 全量包装级 | 定期 | **B** | P3 |
| **PL** 🆕 | [RPL 每日导出](https://rejestry.ezdrowie.gov.pl/registry/rpl)（[停用增量 XML 公告](https://ezdrowie.gov.pl/portal/artykul/zmiany-w-zakresie-udostepniania-danych-z-rejestru-produktow-leczniczych-21-10)） | ❌ **未找到再利用许可**；站脚「© 2026 Centrum e-Zdrowia. **Wszystkie prawa zastrzeżone**」 | ✅ 每日 xml/xlsx/csv | ? | 全量 | 每日 | **C** | P2（发信） |
| **SK** 🆕 | [ŠÚKL 公开数据仓库 `Zoznam_liekov`](https://www.sukl.sk/verejne/Zoznam_liekov/) | ❌ **许可未声明**（页面只写「machine-readable」） | ✅ `zoznam_liekov_aktualny.zip` **5.9 MB** | ? | 全量 | 月更（2026-11-02） | **C** | P2（发信） |
| **GR/EL** | [data.gov.gr 药品目录](https://data.gov.gr/dataset/56dcd10c-68f7-4d8b-9118-66843864f771) | ⚪ **License not specified** | ✅ xlsx/zip | ? | — | — | **C** | P3 |
| **IT** | [AIFA Open Data](https://www.aifa.gov.it/en/open-data) | 未声明；`dati.gov.it` 中 AIFA **产品级数据集 count=0** | ❌ | — | — | — | **C** | P3 |
| **PT** | [dados.gov.pt](https://dados.gov.pt/api/1/datasets/?q=medicamentos) | 仅汇总集 `cc-by`，**不覆盖产品库** | ⚠️ 仅统计 | — | — | — | **C** | P3 |
| **IE** | [HPRA XML](https://assets.hpra.ie/products/xml/latestHumanlist.xml) | 🔴 明令禁止 reproduce/republish/redistribute + 禁止大规模采集 | ✅ 每日 13.5 MB | ✅（无规格） | 全量 | 每日 | **D** | 不做 |
| **BR** 🆕 | [ANVISA Dados Abertos](https://www.gov.br/anvisa/pt-br/acessoainformacao/dadosabertos/dadosabertos)（数据集 `dados.anvisa.gov.br`「Registros Válidos – Medicamento」） | 🟡 **CC BY-ND 3.0（禁演绎）**：站脚原文 *«Todo o conteúdo deste site está publicado sob a licença Creative Commons Atribuição-SemDerivações 3.0»* | ✅ 文件 | 名/规?/型?/MAH?/态? | 未实测 | 定期 | **C（ND 冲突）** | 不做（见 §C） |
| **AT** 🆕 | [BASG All-in-One Register](https://www.basg.gv.at/marktbeobachtung/amtliche-nachrichten/detail/basg-all-in-one-register-liefert-kompakte-medikamenten-information-in-einem-neuen-design) | 未见许可页；未见下载入口 | ❌ 检索式 | ? | — | — | **U** | P3 |
| **HU** 🆕 | OGYÉI 公开药库（[使用说明 PDF](http://www.ogyi.hu/dynamic/Hasznalati_utmutato.pdf)） | 未见许可 | ❌ 检索式 | ? | — | — | **U** | 不做 |
| **IN** 🆕 | CDSCO 门户 | 本轮未取到产品级批量入口 | ? | ? | — | — | **U** | 不做 |
| **TR** 🆕 | TİTCK 授权产品清单 | 本轮未取到批量入口与许可 | ? | ? | — | — | **U** | 不做 |
| **RU** 🆕 | [Минздрав 开放数据列表](https://minzdrav.gov.ru/special/opendata/list) | 本轮**连接失败**，许可未取 | ? | ? | — | — | **U** | 不做 |
| **SA** 🆕 | [SFDA 注册中药品清单](https://sfda.gov.sa/ar/node/17904) | 未取到许可 | ? | ? | — | — | **U** | 不做 |
| **AE** 🆕 | [MOHAP 开放数据](https://mohap.gov.ae/ar/open-data) | 页面存在，**许可未读** | ? | ? | — | — | **U** | 不做 |

统计：**A 2（CZ、LV）+ A\* 2（NO、CH）+ B 2（SE、DK）+ C 6（PL、SK、GR、IT、PT、BR）+ D 1（IE）+ U 6（AT、HU、IN、TR、RU、SA、AE 中的 7 个，其中 HU 建议直接不做）**。

### A.2 逐条证据（只写取到的原文与实测）

#### A.2.1 NO — FEST（**A\***，本轮新发现，北欧最高性价比）

- **许可（决定性）**：`data.norge.no` 数据集元数据里 distribution 的 `license` = `http://publications.europa.eu/resource/authority/licence/NLOD_2_0`，
  且 `isOpenData: true`、`accessRights: {code: PUBLIC}`、`format: text/xml`、`accessURL: https://legemiddelverket.no/andre-temaer/fest/ansvar-ved-bruk-av-fest`。
  发布者 `DIREKTORET FOR MEDISINSKE PRODUKTER`（原 Statens legemiddelverk，2024 年改组）。
  证据：<https://data.norge.no/nb/datasets/09baaca8-61ba-38a2-9097-7a6bc2e5b172>
- **数据集自述（挪威语原文要点）**：*«Legemiddelverket forvalter strukturert informasjon om legemidler gjennom FEST … den primære kilden til informasjon om legemidler og refusjonsinformasjon … presentert i XML-format og forutsetter at du har et program som kan settes opp til å laste ned FEST-meldingen (M30)»*
  → **FEST 是「药品主数据」的权威源**（处方/调剂/电子处方/核心病历都用它），但**取数机制是报文订阅（M30）**，不是网页下载。
- **缺的那一条**：`legemiddelverket.no`→`dmp.no` 迁移后 `andre-temaer/fest` 与 `ansvar-ved-bruk-av-fest` 均返回 **404**（本轮实测），
  → **「个人/非商业主体能否自助订阅 FEST、是否需要协议或费用」未确认**。这决定它是 A 还是 B。
  **下一步一个动作**：人用浏览器打开 <https://www.dmp.no> 搜「FEST」，读订阅条款（≈15 分钟）。
- **为免误判，明确否掉一个诱饵**：`data.norge.no` 上另一个「Legemiddelregisteret」数据集是**处方发放登记（含患者/开方人）**，
  `accessRights: NON_PUBLIC`、许可指向 lovdata 的《helseregisterloven》——**那是个人健康数据，不是药品主数据，永远不做**。

#### A.2.2 CH — Swissmedic（**A\***，字段最全的欧洲单国之二）

- **可批量（已实测存在）**：[Lists and directories](https://www.swissmedic.ch/swissmedic/en/home/services/listen_neu.html) 页明写
  *«The medicines lists provided on the Swissmedic website will be updated monthly»*，且逐个给出 XLSX：
  `Authorised medicinal products (XLSX, 984 kB, 31.10.2026)`、`Extended list (2 MB)`、`List of authorised packaging (3 MB)`、
  `Notifications … No marketing/Interruption to distribution (278 kB)`，另有第 **11 项「Allocation of IT groups / ATC codes」**。
  → 名/包装/ATC/MAH/上市中断 **五项直接可得**，规格与剂型多半在「扩展清单/包装清单」列里（本轮未开文件，标 `?`）。
- **许可（符号级已确认，数据集级待确认）**：同一页面第 **12 项**写 *«Swissmedic publishes public data on the Swiss administration's Open Government Data (OGD) portal»*。
  opendata.swiss 的[使用条款](https://opendata.swiss/en/terms-of-use)只有四种符号，Swissmedic 组织已登记 **6 个数据集**，其资源 `license` 实测为
  `https://opendata.swiss/terms-of-use#terms_by`（= **可商用 + 必须署名**）或 `#terms_open`（可商用 + 建议署名）。
  **但那 6 个是**：医疗器械经济运营商、移植产品许可、微生物实验室许可、麻醉品数据、及四类许可持有人清单——
  **「已授权药品清单」不在其中**（本轮 CKAN `package_search?q=swissmedic` 命中 7 条，逐条看过标题）。
- **缺的那一条**：直连 `swissmedic.ch` 的 XLSX 是否同样适用 `terms_by` 符号 → **待确认**。
  **下一步一个动作**：在 opendata.swiss 上按组织 `swissmedic` 再看一次「Arzneimittel/medicinal products」是否被新登记（≈10 分钟）；若仍没有，就发一封一行确认信（不阻塞，先做 NO）。
- **口径提醒**：Swissmedic 清单是**瑞士批准**（含临时批准、顺势疗法无适应症品、co-marketing）——比 JP 的「医保收载」更接近注册库，但**仍不等于「在售」**；在售要看 Art.11「无销售/停供」清单反向扣。

#### A.2.3 CZ / LV（**A**，已确认，只是还没写库）

结论直接引用 `reports/2026-11-12-eu-member-states-scan.md` §3.2 / §12.1，本轮**只补一个落地事实**：
**两国的 ETL 代码已经写好了**——`etl/markets/cz.py`（32 KB）、`etl/markets/lv.py`（45 KB），
且 `data/raw/cz_sukl_20261112/`、`data/raw/lv_zalu_20261112/` 缓存都在（2026-11-11）。
→ **J2 的成本不是「写 ETL」，是「许可登记 + 注册表 + 写库 + 验收」**。

`product.country` 的 CHECK 枚举（`db/schema.sql:99`）**已含 LV / JP / KR**（v0.11.3 一次性扩过），
但**不含 CZ** → CZ 需要一次 `db/migrate_country_*.py` 重建表；LV 不需要。

#### A.2.4 SE / DK（**B**，结论维持）

- SE：许可 **CC BY 4.0**（data.europa.eu 数据集 *A Completed Search With all Medicines*），但 distribution 的 access URL 是**检索页**，无文件/API。
  另注：同机构 *Substitutable Medicinal Products*（可替换组）**碰 §1.3 红线**，只能当「同成分同规格」的事实证据，**不得**用于推荐替换。
- DK：许可原文 *«You are welcome to use and quote content … provided that you explicitly state the Danish Medicines Agency as the source»*；
  **图片/插图须事先许可、logo 仅丹麦局可用** → 只取事实字段，任何图片/logo 不用。缺 MAH 与在售状态这两列，补上可冲 A。

#### A.2.5 本轮新否掉的三个（以前没人查过）

- **PL**：RPL **每天**在 <https://rejestry.ezdrowie.gov.pl/registry/rpl> 发布 **xml / xlsx / csv**（[公告原文](https://ezdrowie.gov.pl/portal/artykul/zmiany-w-zakresie-udostepniania-danych-z-rejestru-produktow-leczniczych-21-10)，
  2026-11 起停用增量 XML、改发全量）。**但全站没有再利用许可**，页脚是 *«© 2026 Centrum e-Zdrowia. Wszystkie prawa zastrzeżone»*（保留所有权利）。
  → **C**：可发信，不可入库。**这是典型「公开≠开放」**，与 NL 同类。
- **SK**：ŠÚKL 有**正规公开数据仓库** <https://www.sukl.sk/verejne/Zoznam_liekov/>，`zoznam_liekov_aktualny.zip` **5.9 MB**（2026-11-02），
  上游页自述 *«pravidelne aktualizované databázy registrovaných liekov … v strojovo spracovateľných formátoch»*。
  但**页面上没有任何许可声明**（无 CC、无 ODbL、无「open data terms」）→ **C**：有文件、缺许可，**比 CZ 差一整条**（CZ 有专门条款页）。
- **BR**：ANVISA 的开放数据做得挺正规（有开放数据计划 PDF、有数据字典 PDF），**但许可踩在 ND 上**：
  gov.br 全站声明 **CC BY-ND 3.0（署名-禁演绎）**。本站的核心动作是**规格归一化 + 成分拆分 + 跨市场派生**，
  这在 ND 条款下就是「演绎作品」→ **不能发布**。若只用原始事实字段（不派生）也和现有站的数据模型冲突（我们的 `product` 天生是派生层）。
  → **C（ND 冲突）**，进 §C 不做清单；除非 Lead 愿意只用「官方原文链接 + 原名」做一层只读展示（收益低，不建议）。

#### A.2.6 美国补充源（**A，但增量低**）

[openFDA Drug API](https://open.fda.gov/apis/drug/) 现有 7 个端点：Adverse events / Product labeling / **NDC Directory**（已入库）/ Recall enforcement / **Orange Book** / **Drugs@FDA** / **Drug shortages**。
许可统一为 **CC0 1.0**（[open.fda.gov/license](https://open.fda.gov/license/)，已在 `docs/许可清单.md` §2.1 登记）。

| 端点 | 能补什么 | 现库缺口 | 判断 |
|---|---|---|---|
| `/drug/label`（SPL 结构化标签） | route、剂型原文、包装描述、MAH、`set_id`→DailyMed 链接 | US route 已 98.3%、pack 99.6% | **增量低** |
| `/drug/drugsfda` | 申请号（NDA/ANDA）、申请人与产品对应 | `approval_id` 已有部分 | 低 |
| `/drug/shortages` | **短缺/停供**（在售状态的负向信号） | US status 全 `active`（110,179）→ 这是**唯一有增量**的 | 中（但只影响 US） |
| `/drug/orangebook` | 治疗等价评级（TE code） | — | **不做**：TE 评级天然是「可替换」判断，撞 §1.3 红线 |
| DailyMed（[catalog.data.gov](https://catalog.data.gov/dataset/dailymed)） | SPL 全文/结构化字段 | — | 只做**确定性链接层**；正文版权归各厂家，不转载 |

#### A.2.7 WHO INN（**P3，只做内部匹配**）

`docs/许可清单.md` §3 已登记：**CC BY-NC-SA 3.0 IGO**（署名 + **非商业** + **相同方式共享**）。
`data/who_inn_names.csv` **1,738 行**（含表头）已随仓库公开但**未并库**。
性质变了：站一旦商业化（广告/赞助/收费 API），这一行必须重评；且 **SA 会传染**——用 WHO INN 生成的「映射表」须以同许可公开。
→ **结论：只做内部 INN 名称匹配（不对外发布映射表），不合并进 `substance` 的对外字段**。与 task-5（1,791 条 CJK 主名）的映射优先级让位给 Wikidata（CC0）。

#### A.2.8 EDQM Standard Terms（**不做，撞纪律**）

[standardterms.edqm.eu](https://standardterms.edqm.eu/) 自述：*«In order to access Standard Terms, you will first need to have an account with the EDQM Publications registration website»*，
2014 年起 *«making access available free of charge»*，**35 种语言**（含中/日/韩之外的欧盟语），页面版权 *«© 2005-2026 Council of Europe»*。
→ **免费但要注册账号** = 撞本项目「不注册账号」纪律；且再发布许可未声明（只有 © 声明）。**判定：不做。**
**替代路径（更好）**：捷克 DLP **自带 EDQM 剂型/途径码表**（`dlp_formy` / `dlp_cesty`），
即「用 CZ 的 EDQM 码做跨市场剂型对齐」，**不需要注册 EDQM**。这条要写进 J2 的实现说明。

---

## B. 现有市场可补的字段与数据质量项（更省钱的优先）

> 「需写窗口」= 需要一次 `data/drugs.db` 写库窗口（按 §7 并行纪律，一次只能一个会话写）。
> **排序原则：零新数据源 > 已有源可补 > 需新市场 > 需许可**。

### B.1 字段缺口

| # | 缺口 | 现查规模 | 来源 / 补法 | 许可 | 落点层 | 需写窗口 |
|---|---|---|---|---|---|---|
| **B1** | **`product.route` 空** | **245,480（49.6%）**：CN 145,048 / GB 61,048 / TW 16,457 / HK 13,935 / AU 4,811 / EU 2,095 / US 1,922 / ES 102 / MX 62 | **规则派生**：`form_base` → route（约 15 个类别：tablet/capsule→oral、injection→parenteral…）。现库**有 form_base 但无 route 的产品 = 229,450**，其中 `unknown`/`other` 5,809 → **可派生 ≈ 223,641** | 无（自有数据） | 新 `etl/derive_route.py` + `product.route`，`note` 标「派生」 | ✅ |
| **B2** | **`product.pack` 空** | **150,008（30.3%）**：GB 61,051 / ES 25,395 / AU 18,422 / HK 13,935 / MX 10,878 / CA 10,605 / SG 5,511 / EU 2,095 / FR 1,650 / US 396 / TW 70 | GB：dm+d 的 AMPP 包装层（**OGL v3.0，已入库许可够**，≈61k 最大单笔）；ES：CIMA 包装字段（🟡 待确认）；AU：ARTG 导出带包装列（可试）；HK/EU：源无 | GB ✅ / ES 🟡 / AU 🟡 | `etl/ingest_dmd.py`、`etl/markets/*` 的 pack 解析 | ✅ |
| **B3** | **ATC 缺** | 产品加权 **42,681（8.6%）**：US 16,696 / AU 10,925 / GB 5,781 / FR 3,189 / HK 1,736 / TW 1,320 / MX 1,060；**成分层 6,628/12,644 = 52.4%** | ① **CZ/LV/NO/CH 新市场自带 ATC**（一次窗口顺带补共同成分）② Wikidata P267（**CC0**，已在库）③ EMA 已有 | ✅ | `substance.atc` 回填（走 `etl/provenance.py` 记来源，不覆盖人工值） | ✅ |
| **B4** | **`status='unknown'`** | **56,080（11.3%）**：AU 37,634 / HK 13,935 / MX 4,363 / EU 142 / FR 6 | AU 导出**无状态列**（已定案）；HK 名称层无状态；MX/EU 部分可判。US 可用 `/drug/shortages` 做「已知短缺」标记 | — | 只做**页面明示**（coverage 的「已知缺口」列），不硬造状态 | ❌（除非新增源） |
| **B5** | **MAH 缺** | 4,761（1.0%）：AU 4,748 / MX 33 / 其余满 | 低优先（AU 导出缺 MAH 列） | — | — | ❌ |
| **B6** | **说明书原文链接层** | 现库只有 `source_url`（逐产品 1 条） | 只放**确定性 URL**，不存正文：US→`https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=<SPL set_id>`；JP→PMDA 检索 URL；EU→EPAR。**FR/CZ 明确禁止再发布 SPC/PIL 原文**，只允许链接 | ✅ 链接 / ❌ 正文 | `product.source_url` 生成规则 + About 说明 | ✅ |
| **B7** | **`data_as_of`（数据截止日）** | `coverage` 视图靠 `MAX(retrieved_at)`，缺源侧截止日 | 每个新市场入库时**必须**填 `source.data_as_of` + `data_as_of_note` | — | `source` 表 | ✅（随新市场） |

> B5 说明：我按「MAH 覆盖率」现查，AU 是唯一有量级缺口的市场（4,749 条），其余市场 ≥99.7%，**不值得单开任务**。

### B.2 数据质量项（这三项直接卡住了两个已排期功能）

| # | 质量项 | 现查规模 | 影响 | 补法 | 落点层 | 需写窗口 |
|---|---|---|---|---|---|---|
| **B8** | **盐型 / 碱基比**（`variant.salt_code` / `base_fraction`） | `variant` **14,244** 行：`salt_code` 空 **12,562（88.2%）**、`non_salt` 465、`mixed` 145、**有盐码 1,072（7.5%）**；`salt` 原文有值但无码 **481 行可立即匹配**；`base_fraction < 1.0` **0 行**（全 1.0 占位）；折算表 `data/salt_base_fraction.csv` **只有 40 个盐** | **卡住 T17**：T15 名称-规格冲突清单 832 行里约 **7 成**是盐型/元素量/提取物基准差 → 「规格待核实」徽标不敢开 | ① 扩折算表 40→**150–200 个常见盐**（化学计量，无版权）② 481 行原文盐名→code 直接匹配 ③ 补 `strength_basis`（base/salt/salt_equivalent） | `data/salt_base_fraction.csv` + `etl/`（`variant` 写入处）+ 回填脚本 | ✅ |
| **B9** | **名称层「一件多 presentation 共用 name key」** | **74,828 行（占名称行 17.0%）**：AU 18,159 / GB 16,005 / CA 12,583 / FR 9,144 / US 7,129 | 250 mg 组里出现名称写 1000 mg（T15 §5） | ETL 名称层**拆 presentation / 按强度拆 key**——不新增源 | `etl/ingest_*.py` 的 `mark_name()` + `name_key` | ✅ |
| **B10** | **计量基准 `per_volume` 缺** | `product_component` **555,559/650,358 空（85.4%）**；**H6 口径**（注射/液体、有强度、无 per_volume）= **80,845 成分行 / 4,176 个成分页**（与 v0.11.9 现查一致） | 规格无法跨市场比较，页面已标「原记录未明确基准」并退出等价链接 | 从 `pack` / `dosage_form` / 规格原文解析「300 mg/10 mL」这类**同一条记录内**的基准 → 规则派生 | `product_component.per_volume_*` + 新 `etl/derive_per_volume.py` | ✅ |
| **B11** | **`form_base` 不收口** | 空 **16,038（3.2%）**；取值 **876 个**（AU 导出夹带自由文本） | 剂型展示口径漂移；B1 的派生质量依赖它 | 归一化到 ~30 个标准剂型 + other（**只改展示口径，不动产品身份**，= 队列 task-148 / G4） | `etl/normalize_form.py` | ✅ |
| **B12** | **无成分产品** | **5,402**：US 2,229 / AU 1,495 / FR 1,296 / EU 195 / MX 121 / SG 66 | 这些产品不参与 collision，页面要标「成分未记录」 | 部分可回填（US 可由 `drugsfda` 补；FR 由 `CIS_COMPO` 补未匹配部分） | `etl/` 匹配层 | ✅ |

### B.3 B 段的优先级（按「省 token / 收益」）

1. **B1 route 派生**（≈223,641 行、零新源、1 天）——**最划算**；
2. **B8 盐基表 40→200**（解 T17 前置，0.5–1 天）；
3. **B3 ATC**（跟着 CZ/LV 同窗口，边际成本≈0）；
4. **B9 名称层拆 presentation**（74,828 行，但属 ETL 结构性改动，1.5–2 天，风险中）；
5. B2 pack（GB 可补 61,051）／B10 per_volume（80,845 成分行）／B11 form 归一 —— 次批；
6. B4/B5/B6/B12 —— 只做口径与链接，不追数据。

---

## C. 明确「不做」清单（也要写清为什么）

| # | 不做 | 为什么（不是懒，是纪律） |
|---|---|---|
| **C1** | **付费数据**：DrugBank / WHODrug / MedNet INN / AMIS（BfArM 产品级批量）/ Infomed（PT 产品库）/ 各类商业 API | §12「默认零新增支出」；§9 不付费买数据 |
| **C2** | **需注册账号 / 需 key 才能取的源**：**EDQM Standard Terms**（须 EDQM 账号）、**KR data.go.kr**（须人申请 key） | §9「不做 login / 不注册账号」；KR 只能由人来做（队列 J3 已记） |
| **C3** | **绕 WAF / 反爬**：FI（fimea.fi、avoindata.suomi.fi 对自动化 **403 Cloudflare**）、LT（vvkt.lt 403） | 403 是**取不到**，不是**禁止** → 标 U/待确认，**不换 IP、不带 cookie 绕** |
| **C4** | **明令禁止再发布**：IE HPRA（terms 禁止 reproduce/republish/redistribute + 禁止大规模采集） | §A 判定 D |
| **C5** | **许可与本站派生方式冲突**：**BR ANVISA（CC BY-ND 3.0 禁演绎）** | 本站 `product`/`strength` 天生是派生层，ND 下不能发 |
| **C6** | **许可不明的源在本轮一律不入库**：PL、SK、GR、AT、HU、IN、TR、RU、SA、AE | 许可未知 ≠ 开放数据（NL 教训）；只登记、只发信 |
| **C7** | **药品以外品类**：保健品/膳食补充剂（含 NO FEST 里的「Kosttilskudd」、CH 的补充剂）、化妆品、兽药（CH/NO 清单里都有兽药表）、医疗器械 | 站定位是「药品商品名定位」，扩品类会污染 collision 与成分表 |
| **C8** | **价格 / 医保支付 / 报销数据**：DK 价格文件里的价格列、CZ 的 `VYDEJ`/报销、MX PROFECO 价格、AU PBS 补贴价、BR 价格 | 项目红线：不做价格；价格数据会诱导「哪个便宜」→ 滑向用药建议 |
| **C9** | **治疗可替换性数据**：openFDA **Orange Book TE code**、SE *Substitutable Medicinal Products* | §1.3：不判断可互换 / 不做替代推荐 |
| **C10** | **WHO INN 对外发布映射表**（本轮） | 🟡 CC BY-NC-SA 3.0 IGO：NC + **SA 传染**；只内部匹配 |
| **C11** | **个人健康数据**：NO `Legemiddelregisteret`（处方发放、含患者/开方人，`NON_PUBLIC`） | 隐私；与本站无关 |

---

## D. Top-5 推荐

> 排序键 = **许可确定性 × 字段价值 × 接入成本**；每条给「下一步一个动作 / 工时 / 风险 / 能否本周开写库窗口」。

### 🥇 D1. 捷克 CZ + 拉脱维亚 LV 入库（队列 J2）

- **为什么第一**：唯一两个**条款级**确认的 A 类，而且 **ETL 已写好**（`etl/markets/cz.py` 32 KB、`lv.py` 45 KB，raw 缓存都在），
  `country` CHECK **已含 LV**（省一次重建表）；字段 **7/7**，含 **ATC + EDQM 剂型/途径码 + MAH + 状态**。
- **能加多少**：+**70,032**（CZ 实测）+ LV 待测（XML 全量，估同量级）→ 预计 **+130k–150k 产品**，并**顺带补掉 B3 的一大块 ATC**。
- **下一步一个动作**：`db/migrate_country_cz.py`（照 `migrate_country_sg.py`）→ 在 `docs/许可清单.md` §2.11 把两行从「未接入」改成「已接入」→ smoke 干跑 cz/lv 出「行数 + 映射率 + 规格解析率 + 状态分布」四张表 → 进窗口写库。
- **工时**：**1.5–2 天**（含验收；其中「写 ETL」≈0，这是它便宜的原因）。
- **风险**：中低。① CZ 是 **CP1250** 编码（按 UTF-8 读会静默乱码）；② LV 的**在售三开关**（`status`/`prd_removed`/`sell_stop_date`）+ 平行进口/未注册药混行 → `coverage.active` 容易算高；③ CZ 的 **SPC/PIL/OBALY 三包严禁入库**（第三方 IP 排除条款）。
- **本周开写库窗口：✅ 能**（建议与 D2/D4 同一个窗口，一次做完省 token）。

### 🥈 D2. 「剂型 → 给药途径」规则派生（B1）

- **为什么第二**：**零新数据源、零许可、零付费**，一次改 ETL 直接补 **≈223,641 行**（route 覆盖率 50.4% → **约 95.6%**）。
- **下一步一个动作**：写 `etl/derive_route.py`（约 15 类映射 + 未知落 `NULL` 并计数），先在副本/dry-run 出「每类命中数 + route 分布」，抽检 30 条。
- **工时**：**1 天**（含抽检与 `check_data.py`）。
- **风险**：低，但有两条硬约束——① 页面/字段必须标「**派生自剂型**」，不能冒充来源原文；② **派生 route 不得参与「可互换/等价」判断**（只作路径提示），否则撞 §1.3。
- **本周开写库窗口：✅ 能**。

### 🥉 D3. 瑞士 CH（Swissmedic）+ 挪威 NO（FEST）双 A\* 复核 —— 只读，不占窗口

- **为什么第三**：这是本轮**唯一新找出来的两个潜在 A 类**，且都是「月度/持续全量 + 字段含 ATC/MAH」的第一梯队源；
  差的那条证据都只要 **10–30 分钟只读**。
- **下一步一个动作**：**同一个只读任务**里做两件事——① opendata.swiss 按组织 `swissmedic` 复核「已授权药品清单」是否已登记 + 许可符号；② `dmp.no` 读 FEST 订阅条款（是否自助、是否免费）。
- **工时**：**0.5 天只读**（两源各 15–30 分钟取证 + 15 分钟写入报告）；**若两条都过**，排 v0.13：CH 或 NO 各 1 天 ETL（CH 的 XLSX 要处理「批准≠在售」；NO 要处理 M30 报文）。
- **风险**：**CH 中**（许可符号只在其他 6 个数据集上验证过，不能外推）；**NO 中**（FEST 若是「协议/收费供给」，直接降级为 B，只做事实+链接）。
- **本周开写库窗口：❌ 不写库**（只读复核）。这是有意为之——A\* 不落库。

### 4️⃣ D4. 盐基表扩容 40 → 150–200 + `salt_code` 回填（B8）

- **为什么第四**：它是 **T17「规格待核实」徽标**的**前置条件**（Lead 2026-11-14 定：抽样误报降到 <3 成才开）；
  且**零许可风险**（化学计量 + 文献分子量），481 行「原文盐名有值、无 salt_code」可**当天回填**。
- **下一步一个动作**：把 `data/salt_base_fraction.csv` 从 40 扩到 150–200（常见盐酸盐/钠盐/硫酸盐/马来酸盐/甲磺酸盐/水合物），先用它跑 T15 的 832 行冲突清单，出「误报率 before/after」。
- **工时**：**0.5–1 天**。
- **风险**：低-中。误配一个盐的分子量会**静默**放大 `base_fraction` 误差 → 必须给每个盐配 CAS/分子式出处，且**判不了就留 `unknown`**（宁可不出结论）。
- **本周开写库窗口：✅ 能**（与 D1/D2 同窗口）。

### 5️⃣ D5. 美国补充源（openFDA `label` / `drugsfda` / `shortages` + DailyMed 链接层）

- **为什么第五**：许可最干净（**CC0 1.0**），但**增量最低**——US 的 route 98.3%、pack 99.6%、ATC 84.8% 已经是全库最好的市场之一。
- **唯一有增量的是 `/drug/shortages`**（US `status` 现在**全 110,179 条 active**，一个「已知短缺」标记能救几个页面）+ `set_id → DailyMed` 的确定性链接（B6）。
- **下一步一个动作**：只做两件事——① 拉 shortages 出「与库内 NDC 交集」的行数（≈1 小时）；② 给 US 产品补 `dailymed` 链接（模板化，无正文）。
- **工时**：**1 天**；**风险**：低（但**别碰 Orange Book TE code**，那是可替换判断）。
- **本周开写库窗口：⚠️ 可以但建议顺延**——如果本周窗口只够一件事，让给 D1+D2+D4。

### 备选（本轮不进 Top-5 的理由）

| 候选 | 不进的理由 |
|---|---|
| PL / SK | 有文件、没许可 → 只能发信，**排不进本周** |
| BR | CC BY-ND 禁演绎，与我们派生冲突 |
| WHO INN 并库 | NC + SA 传染，要先决定商业化口径 |
| EDQM | 必须注册账号，撞纪律；**CZ 的 EDQM 码表可替代** |
| SE / DK | SE 无批量；DK 只到 B（且缺 MAH/在售） |

---

## E. 复现命令（本次全部读数的来源）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 现库基线
& $py db/q.py "SELECT country, COUNT(*) n FROM product WHERE country IS NOT NULL GROUP BY country ORDER BY n DESC"
& $py db/q.py "SELECT region, COUNT(*) n FROM product WHERE region IS NOT NULL GROUP BY region"

# 2) 每市场字段覆盖率（route / pack / MAH / form_base / ATC）
& $py db/q.py "SELECT COALESCE(p.country,p.region) mk, COUNT(*) n,
  ROUND(100.0*SUM(CASE WHEN p.route IS NOT NULL AND p.route<>'' THEN 1 ELSE 0 END)/COUNT(*),1) route_pct,
  ROUND(100.0*SUM(CASE WHEN p.pack  IS NOT NULL AND p.pack <>'' THEN 1 ELSE 0 END)/COUNT(*),1) pack_pct,
  ROUND(100.0*SUM(CASE WHEN p.mah   IS NOT NULL AND p.mah  <>'' THEN 1 ELSE 0 END)/COUNT(*),1) mah_pct,
  ROUND(100.0*SUM(CASE WHEN p.form_base IS NOT NULL AND p.form_base<>'' THEN 1 ELSE 0 END)/COUNT(*),1) formbase_pct,
  ROUND(100.0*SUM(CASE WHEN s.atc IS NOT NULL AND s.atc<>'' THEN 1 ELSE 0 END)/COUNT(*),1) atc_pct
FROM product p
LEFT JOIN product_component pc ON pc.product_id=p.product_id AND pc.ord=0
LEFT JOIN variant v ON v.variant_id=pc.variant_id
LEFT JOIN substance s ON s.substance_id=v.substance_id
GROUP BY COALESCE(p.country,p.region) ORDER BY n DESC"

# 3) route 派生潜力（B1）
& $py db/q.py "SELECT COUNT(*) FROM product WHERE (route IS NULL OR route='') AND form_base IS NOT NULL AND form_base<>''"

# 4) H6 计量基准（B10，应与 v0.11.9 的 80,845 一致）
& $py db/q.py "SELECT COUNT(*) FROM product p JOIN product_component pc ON pc.product_id=p.product_id
 WHERE p.form_base IN ('injection','liquid') AND pc.strength_value IS NOT NULL AND pc.per_volume_value IS NULL"

# 5) 盐型 / 碱基比（B8）
& $py db/q.py "SELECT COUNT(*) n, SUM(CASE WHEN salt_code='' THEN 1 ELSE 0 END) salt_empty,
  SUM(CASE WHEN salt_code='non_salt' THEN 1 ELSE 0 END) non_salt,
  SUM(CASE WHEN base_fraction<1.0 THEN 1 ELSE 0 END) frac_lt1 FROM variant"
(Get-Content data\salt_base_fraction.csv).Count   # 41 = 40 个盐 + 表头

# 6) 注册表现状（新市场前置）
& $py -X utf8 -c "import json;d=json.load(open('data/markets.json',encoding='utf-8'));print([(m['code'],m.get('enabled')) for m in d['markets']])"
& $py -X utf8 -c "import json;d=json.load(open('data/languages.json',encoding='utf-8'));print(d['planned_markets'])"
Select-String -Path db\schema.sql -Pattern "country        TEXT NULL CHECK"   # 现枚举含 LV/JP/KR，不含 CZ

# 7) 外部取证（只读；不登录、不绕）
#  NO  https://data.norge.no/nb/datasets/09baaca8-61ba-38a2-9097-7a6bc2e5b172   (NLOD_2_0 / isOpenData:true)
#  CH  https://opendata.swiss/api/3/action/package_search?q=swissmedic&rows=5    (资源 license=terms_by)
#      https://www.swissmedic.ch/swissmedic/en/home/services/listen_neu.html     (XLSX 清单 + 日期)
#  SK  https://www.sukl.sk/verejne/Zoznam_liekov/                                (zoznam_liekov_aktualny.zip 5.9M)
#  PL  https://ezdrowie.gov.pl/portal/artykul/zmiany-w-zakresie-udostepniania-danych-z-rejestru-produktow-leczniczych-21-10
#  BR  https://www.gov.br/anvisa/pt-br/acessoainformacao/dadosabertos/dadosabertos (页脚 CC BY-ND 3.0)
#  EDQM https://standardterms.edqm.eu/                                           (需账号)
#  US  https://open.fda.gov/apis/drug/
```

---

## F. 本次没做 / 需人拍板 / 已知缺口

### F.1 本次没做（按写权限）

- **没写库**、**没改 `etl/`**、**没改 `site/build.py`**、**没碰 `site/dist`**、**没 commit / 发布**。
- **没改 `docs/许可清单.md`**（共享文件，与其他工位写权重叠）：本轮新结论（NO / CH / PL / SK / BR / EDQM / WHO INN）
  的登记行写在本文 §A.2，交 Lead 决定何时落 §2.11 / §3。
- **没发任何许可信**（BE、DK、EE、SK、PL 的信都只有草稿要点，见 §A.2 与旧报告 §5）。
- **没注册任何账号** → 因此 **KR 仍停在「等人给 key」**、**EDQM 直接判不做**。
- **没下载任何受限数据**：CH 的 XLSX **只看页面上的文件名/字节数/日期**，没下载；NO 的 FEST **没取报文**。

### F.2 需人拍板（4 条）

1. **BR（ANVISA）**：CC BY-ND 3.0 是否接受「只发原名字段、不做任何派生」的窄口径？我建议**不接受**（收益低、模型冲突）。
2. **WHO INN**：如果站有商业化可能，`CC BY-NC-SA` 的 NC 条款现在就要定口径（只内部用 vs 对外发布映射表 + SA 公开）。
3. **CH 许可**：若 opendata.swiss 上确实没有「已授权药品」，要不要**以站名义发一封一行确认信**给 Swissmedic？
4. **PL / SK 发信**：两国都是「有文件、没许可」，与 BE 同一类；要不要一起进本轮发信批次（P2）。

### F.3 已知缺口（下一轮补，不阻塞）

| 项 | 缺什么 | 怎么补 |
|---|---|---|
| **IN / TR / SA / AE / RU** | 产品级批量入口 + 许可原文，一条都没取到 | 每国 20 分钟：官方注册库页 + 站内 terms 两页；RU 的连接失败要换网络重试 |
| **AT / HU** | 是否有下载入口 | AT 看 `basg.gv.at` 的 Daten/Open Data 栏；HU 判「检索式」→ 建议直接不做 |
| **FI / LT / EE** | 403 与 JS 应用，无法自动化 | **必须人来**：浏览器打开看文件清单 + 页脚许可（FI 一旦确认直接冲 A） |
| **CH 字段细节** | 「已授权药品 XLSX」的列名、行数、规格/剂型是否有独立列 | 下载 3 个 XLSX（984 kB / 2 MB / 3 MB）读表头，**属 A\* 复核的一部分** |
| **NO 字段细节** | FEST varekort 的字段清单（varenummer/ATC/styrke/form/MAH） | 同 FEST 订阅条款一起确认 |
| **CZ 行数与 LV 行数** | CZ 70,032 已有；**LV 行数未数** | 干跑 `etl/markets/lv.py --dry-run` 出数（只读，0.5 小时） |

---

_本文件为只读扫描产物：不含任何已执行的数据发布、写库或建站动作。_
