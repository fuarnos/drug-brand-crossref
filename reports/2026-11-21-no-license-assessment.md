# 挪威（NO）FEST 2.5.1 · Direktoratet for medisinske produkter（DMP）——再发布许可与字段可得性评估

- 日期：2026-11-21（北京时间）｜工位：data-scout｜任务：task-5（DATA1，REL2 发布期间只读调研）
- 队列依据：M5「产品记录 80 万」、M2「NO / CH 只读复核」；上一轮概览见 `reports/2026-11-20-data-source-scan.md` §3
- 机构名对照（避免下游混淆）：站点现名 **Direktoratet for medisinske produkter（DMP）**，英文站名 *Norwegian Medical Products Agency*，页内自用缩写 **NOMA**；即任务里的旧称 **Statens legemiddelverk**。署名统一写 `DMP`（可并列 NOMA）。
- **只读声明**：未写 `data/drugs.db`、未跑 ingest / `run_all.py` / `site/build.py` / 任何测试、未改 `site/` `etl/` `deploy/`、未 commit、未发布。只把官方 ZIP 下到系统临时目录做计数与字段核对（`%TEMP%\data_scout_noch_20261121\`）。
- **结论：🟢 可再发布（NLOD 2.0）**。产品级批量入口公开、免账号、免费；字段够做「商品名 → 成分+含量 → 剂型 → 包装规格 → MAH」的身份对应；**无阻塞项**，只差排写库窗口。

## 0 需人（决策 / 邮箱）

- **无阻塞项**：NLOD 2.0 明文允许复制、修改、再分发与商用，无需向 DMP 发信申请。
- 可选（非阻塞、本轮不发）：DMP 页面把 NLOD 的适用对象写作「**system providers**」。若以后想要一封「面向公众的参考站同样适用 NLOD」的书面确认，可发 `fest@dmp.no`（页面上的运营信箱）；按 `docs/数据源调研清单.md` §5 模板，1 周 / 1 月跟进。**按现证据已够入库，不以此为由阻塞。**

## 1 结论先行

| 问题 | 答案（证据见 §2、§4） |
|---|---|
| 有没有产品级批量入口？ | **有**。DMP 公开下载页列出「Rekvirent-uttrekk（处方端全量提取）v2.5.1」ZIP；`fest251.zip` 实测 HTTP 200、**14,550,258 B**、免账号 |
| 许可允许再发布吗？ | **允许**。DMP 明写 FEST 按 **NLOD** 提供（「System providers can freely use the information in FEST within their systems according to the Norwegian License for Public Data (NLOD)」）；NLOD 2.0 §2 授予复制/修改/分发权，§5 要求署名+标明修改，§9 与 CC BY 4.0 / OGL 兼容 |
| 数据量（实测） | **8,985** 个品牌条目（`LegemiddelMerkevare`）/ **10,867** 个包装（`Legemiddelpakning`）；唯一商品名 **5,136**（上轮另记唯一「名+剂型+规格」串 8,123，本轮未重算） |
| 数据截止 | XML 根节点 `<HentetDato>2026-11-10T10:24:32</HentetDato>`；ZIP 内文件时间 2026-11-11 08:43 |
| 更新频率 | **每月 1 日与 15 日**（页面原文：手动下载者须在每月 1 日和 15 日之前更新；另有非常规紧急发布） |
| 字段：商品名 / 成分+含量 / 剂型 / MAH / 规格 | 商品名 `Varenavn` 8,985/8,985；成分 `Virkestoff/Navn`（挪威语）+ `NavnEngelsk`（英文）；含量 `VirkestoffMedStyrke/Styrke`（7,652 条，覆盖 **8,709/8,985 = 96.9%** 品牌）；剂型 `LegemiddelformKort` 8,985/8,985；MAH `ProduktInfo/Produsent` **8,908/8,985 = 99.1%**；包装规格 `Pakningsinfo/Pakningsstr` **10,964** 条 |
| 缺口 | **没有注册号（MT 号）字段**（只有订货号 `Varenr` 与条码 `Ean`）；**状态只有「Aktiv oppføring」一个值**，下线只能由包装级标记推断；品牌与包装两层、需引用解析 |
| ATC | `Atc` 8,722/8,985（**97.1%**），带 `DN` 成分名显示值 |
| 入库成本估算 | **6–8 人时**（118 MB XML、引用解析、挪威语/英语成分名归一、品牌/包装两层建模） |
| 对目标贡献 | 产品 **+8,985**；商品名 **+约 5,136**（去重后；若按「名+剂型+规格」口径约 8.1k） |

## 2 许可证据（2026-11-21 抓取）

| # | 证据 | 原文短引 | 判定 |
|---|---|---|---|
| 1 | DMP 英文页 *Responsibility when using FEST*：<https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest/responsibility-when-using-fest> | 「The Norwegian Medical Products Agency (NOMA) makes pharmaceutical information publicly available through the FEST service. **System providers can freely use the information in FEST within their systems according to the Norwegian License for Public Data (NLOD).**」 | **许可来源** |
| 2 | 同页挪威语版：<https://www.dmp.no/om-oss/distribusjon-av-legemiddeldata/fest/ansvar-ved-bruk-av-fest> | 「**Systemleverandører kan fritt benytte informasjonen i FEST i sine systemer i henhold til Norsk lisens for offentlige data (NLOD).**」；页首：「Norsk lisens for offentlige data erstatter tidligere avtaler med systemleverandører.」 | 挪威语原文一致 |
| 3 | NLOD 2.0 全文：<https://data.norge.no/nlod/en/2.0>（最后更新 2023-03-07） | §2「the **licensee** … may **use** the **information** for any purpose and in all contexts, by: **copying** … and **distributing** …; modifying …; **copying** and **distributing** such changed or combined information.」 | **可再发布（含演绎）** |
| 4 | 同上 §5 Attribution | 「If the **licensor** has not specified how attributions shall be made, the **licensee** shall normally state the following: «Contains data under the Norwegian licence for Open Government Data **(NLOD)** distributed by [name of **licensor**]»」；「If the **information** has been changed, the **licensee** must clearly indicate that changes have been made」 | **署名 + 标明修改** |
| 5 | 同上 §6 Proper use | 「shall not **use** the **information** in a manner that appears misleading nor present the **information** in a distorted or incorrect manner」；「Neither the **licensor's** nor other contributors' names or trademarks must be used to support, recommend or market the **licensee**」 | 不得歪曲、不得暗示背书 |
| 6 | 同上 §9 Licence compatibility | 与 **OGL 1.0/2.0/3.0、CC BY 4.0** 等兼容（「for all **information**: Open Government Licence (version 1.0, 2.0 and 3.0), Creative Commons Attribution Licence (international version 4.0 …)」） | 可与本站其他 CC BY 来源合并发布 |
| 7 | DMP 下载页 *Downloading FEST and SAFEST*：<https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest/downloading-fest-and-safest> | 「If FEST is downloaded manually, it should be updated **before the 1st and 15th of each month**… there may be extraordinary publications」；「As of August 30, 2023, FEST files for Farmalogg and NAV/HELFO will no longer be available for open download … contain confidential H-prescription refund prices」「**The other extracts will not be affected by this change and can be downloaded as before.**」 | 更新节奏 + 只有部分提取被关闭 |
| 8 | DMP FEST 概览页：<https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest> | 「FEST is offered as an information service to expose common pharmaceutical data to all members of the prescription chain; physicians, hospitals, pharmacies and other healthcare professionals …」 | **口径提示：处方链数据服务，不等于「全部获批上市药品」** |

**允许**：复制、修改、再分发、商用、与其他数据合并（NLOD §2、§9）。
**义务**：① 署名许可方（DMP / NOMA）+ 许可名 + 链接；② 明确标出「本站做过修改（归一化）」；③ 不得歪曲、不得用 NOMA/DMP 名义背书（§5、§6）。
**限制**：不得转授许可（§2 末句「shall not sub-license or transfer this licence」）；不覆盖第三方权利（§3），故**不转售 FEST 原文件**、不转载 SmPC 正文（只存链接与事实字段）。
**建议署名文字**（三语，写进 About / 覆盖页 / datapackage）：

- 英：`Contains data under the Norwegian Licence for Open Government Data (NLOD 2.0) distributed by the Norwegian Medical Products Agency (DMP). Changes have been made by DrugCrossRef (normalisation of ingredient names, strengths and dosage forms).`
- 挪：`Inneholder data under Norsk lisens for offentlige data (NLOD 2.0) tilgjengeliggjort av Direktoratet for medisinske produkter (DMP). Endringer er gjort av DrugCrossRef.`
- 中：`含挪威药品管理局（DMP）FEST 数据，按挪威政府开放数据许可 NLOD 2.0 提供；本站已做归一化修改（成分名 / 规格 / 剂型），原始文件不转载。`

## 3 必查 12 项（`docs/数据源调研清单.md` §3）

| # | 项 | 结论与证据 |
|---|---|---|
| 1 | 官方入口 URL | 下载页 <https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest/downloading-fest-and-safest>；文件直链 `https://www.dmp.no/globalassets/documents/om-oss/distribusjon-av-legemiddeldata/fest/festfiler/fest251.zip` |
| 2 | 许可原文 + 名称 | **NLOD 2.0**（Norwegian Licence for Open Government Data）；条款 <https://data.norge.no/nlod/en/2.0>；DMP 适用声明见 §2 #1/#2 |
| 3 | 再发布限制 | 允许商用 ✅、允许演绎 ✅（须标明修改）；要求署名 ✅；**未见他处禁止批量下载**（robots 只禁 `/episerver/`、`/utils/`）；不得转授、不得暗示背书 |
| 4 | 是否需账号 | **免账号、免注册、免费**（ZIP 直链匿名可下；`farmalogg` / `NAV/HELFO` 提取自 2023-08-30 起需证书，**与本文件无关**） |
| 5 | 批量入口形态 | ZIP（内含单个 `fest251.xml`，118,252,386 B）；另有 WCF SOAP 服务（`FestService251.svc`）与 FHIR 并行服务，本站用 ZIP 即可 |
| 6 | 字段清单 | 商品名 ✅、活性成分 ✅（挪威语 + 英文）、含量 ✅、剂型 ✅、包装规格 ✅、MAH ✅、**注册号 ❌**、状态 ⚠️（仅「活动条目」，下线用包装级标记）、日期 ✅（上市日/下线日） |
| 7 | 条数（实测） | 品牌 **8,985** / 包装 **10,867** / 成分-规格引用 **7,652** / 成分主档 **8,645** |
| 8 | 更新频率 / 截止 | 每月 **1 日与 15 日**；本轮 `HentetDato=2026-11-10T10:24:32` |
| 9 | 规格与剂型可得性 | 剂型 **结构化 100%**（`LegemiddelformKort` 码 + 显示名）；含量 **结构化 96.9%**（品牌至少 1 条 `VirkestoffMedStyrke`）；包装规格 **结构化**（`Pakningsstr` + `EnhetPakning`，10,964 条）；无需从名称解析 |
| 10 | 署名要求原文 | NLOD §5（见 §2 #4）；默认句式「Contains data under the Norwegian licence for Open Government Data (NLOD) distributed by [licensor]」 |
| 11 | 抓取礼貌 | `robots.txt`：`User-agent: *` 仅 `Disallow: /episerver/`、`/utils/`（<https://www.dmp.no/robots.txt>）；无频率限制条款；本站按「每个写库窗口下一次 ZIP」执行，带可识别 UA |
| 12 | 入库成本 / 风险 | **6–8 人时**；风险：① 品牌/包装两层 + 引用解析；② 挪威语成分名需与 INN 对齐（有英文名兜底）；③ 口径风险（处方链数据，不是注册库）；④ 无注册号、无显式在售状态 |

## 4 字段与覆盖率（实测）

XML 结构（三层包裹，`Oppf*` 是「追踪/状态」层，业务对象在里层）：

```
<FEST>
  <HentetDato>2026-11-10T10:24:32</HentetDato>
  <KatLegemiddelMerkevare><OppfLegemiddelMerkevare>
      <Id/><Tidspunkt/><Status V="A" DN="Aktiv oppføring"/>
      <LegemiddelMerkevare> … </LegemiddelMerkevare>
  </OppfLegemiddelMerkevare></KatLegemiddelMerkevare>
  <KatVirkestoff>…</KatVirkestoff> <KatVirkestoffMedStyrke>…</KatVirkestoffMedStyrke>
  <KatLegemiddelpakning><OppfLegemiddelpakning>…</OppfLegemiddelpakning></KatLegemiddelpakning>
</FEST>
```

品牌级 `LegemiddelMerkevare` 字段（覆盖率均以 8,985 为分母）：

| 字段 | 含义 | 覆盖 |
|---|---|---|
| `Varenavn` | 商品名（品牌名） | 8,985（100%） |
| `NavnFormStyrke` | 「名 + 剂型缩写 + 含量」显示串，如 `Thylip kaps 200 mg` | 8,985 |
| `Atc` | ATC 码（属性 `V`）+ 显示名 `DN`，如 `C10AB05 / Fenofibrat` | 8,722（97.1%） |
| `LegemiddelformKort` / `LegemiddelformLang` | 剂型（码 + 显示名，如 `Kapsel, hard`） | 8,985（100%） |
| `Preparattype` | 制剂类别（如 `Legemiddel`、`Krever godkj. Fritak`） | 8,985 |
| `Reseptgruppe` | 处方组（A/B/C） | 8,985 |
| `SortertVirkestoffMedStyrke/RefVirkestoffMedStyrke` | 指向成分-含量记录（可多条） | 8,709 品牌≥1 条（96.9%）；276 个品牌 0 条 |
| `ProduktInfo/Produsent` | **MAH 名称**（如 `2care4 Generics ApS`） | 8,908（99.1%） |
| `ProduktInfo/Varseltrekant` | 警示三角标 | 2,818 |
| `Preparatomtaleavsnitt/Lenke/Www` | SmPC（preparatomtale）PDF 链接 | 有（只存链接，不转载正文） |
| `SvartTrekant` / `Opioidsoknad` / `Smak` | 黑三角 / 阿片类申请 / 口味 | 373 / 284 / 188 |

成分-含量 `VirkestoffMedStyrke`（7,652 条，全部可解析到成分主档）与成分主档 `Virkestoff`（8,645 条）：

- `Styrke`（属性 `V` + 单位 `U`）：单位分布 `mg 5,644 / mikrog 824 / IE 239 / g 216 / % 145 / % w/v 121 / RI 70 …`；
- `RefVirkestoff` → `Virkestoff/Navn`（挪威语，8,645 条全部有值）+ `Virkestoff/NavnEngelsk`（8,644 条）。

包装级 `Legemiddelpakning`（10,867 条）：

| 字段 | 含义 | 覆盖 |
|---|---|---|
| `Varenr` | 订货号（**不是注册号**） | 10,867（100%） |
| `Ean` | 条码 | 10,531（96.9%） |
| `Pakningsinfo/RefLegemiddelMerkevare` | 指回品牌 | 10,964（含一包多条包装信息） |
| `Pakningsinfo/Pakningsstr` + `EnhetPakning` | **包装规格 + 单位**（如 `100` + `stykk`） | 10,964 |
| `Markedsforingsinfo/Markedsforingsdato` | 上市/上架日期 | 10,867（100%） |
| `Markedsforingsinfo/VarenrUtgaende` / `MidlUtgattDato` / `AvregDato` | 下线标记 / 临时停售日 / 注销日 | 338 / 246 / 36 |
| `PrisVare` | 价格记录 | 38,801（**本站不存价格**） |

状态与在售推断（§6 详述）：8,985 个品牌与 10,867 个包装的 `Status` **全部为** `V="A" DN="Aktiv oppføring"`；下线信息只在包装级（429 个品牌的**全部**包装带下线标记，531 个品牌至少 1 个包装带标记）。

样例（原文，2026-11-21 从 `fest251.xml` 抽录）：

```xml
<LegemiddelMerkevare>
  <Atc V="C10AB05" S="2.16.578.1.12.4.1.1.7180" DN="Fenofibrat" />
  <NavnFormStyrke>Thylip kaps 200 mg</NavnFormStyrke>
  <LegemiddelformKort V="891" DN="Kapsel, hard" />
  <Preparattype V="7" DN="Legemiddel" />
  <Varenavn>Thylip</Varenavn>
  <SortertVirkestoffMedStyrke><RefVirkestoffMedStyrke>ID_73E87E2C-…</RefVirkestoffMedStyrke></SortertVirkestoffMedStyrke>
  <ProduktInfo><Produsent>2care4 Generics ApS</Produsent></ProduktInfo>
</LegemiddelMerkevare>
<Legemiddelpakning>
  <NavnFormStyrke>Propranolol dak tab uten laktose 40 mg</NavnFormStyrke>
  <Varenr>224948</Varenr><Ean>5711313003231</Ean>
  <Pakningsinfo><RefLegemiddelMerkevare>ID_D08875D3-…</RefLegemiddelMerkevare>
    <Pakningsstr>100</Pakningsstr><EnhetPakning V="stk" DN="stykk" /></Pakningsinfo>
  <Markedsforingsinfo><Markedsforingsdato>2021-04-15</Markedsforingsdato></Markedsforingsinfo>
</Legemiddelpakning>
```

## 5 规格与剂型可得性（入库关键）

- **剂型**：结构化列（码 + 挪威语显示名），8,985/8,985，**不需要解析名称**；码表可在 `LegemiddelformKort@V` 上做本地词表（页面可显示原文 + 英文/中文映射）。
- **含量**：`VirkestoffMedStyrke/Styrke@V` + `@U` 结构化；品牌覆盖 **96.9%**，剩余 276 个品牌多为「无含量」的老制剂/替代制剂（`NavnFormStyrke` 里仍可能写含量，**不要**用文本猜）。
- **包装规格**：`Pakningsstr` + `EnhetPakning` 结构化，10,964 条；同一包装可有多个 `Pakningsinfo`（如多盒装），入库要按「包装 → 多条包装信息」建模或取主包装并保留计数。
- **多成分**：`SortertVirkestoffMedStyrke` 可多条（实测每品牌：1 条 7,665 / 2 条 701 / ≥3 条 343，合计 8,709 个品牌至少 1 条，276 个品牌 0 条），复方药能正确表达。

## 6 状态与日期语义（页面口径必须写清）

| 事实 | 说明 |
|---|---|
| `OppfLegemiddelMerkevare/Status` = `A / Aktiv oppføring`（8,985 条全同） | FEST 只导出**活动条目**；**不能**据此说「挪威全部在售药品」，也不能说「含历史库」 |
| 包装级 `AvregDato` / `MidlUtgattDato` / `VarenrUtgaende` | 才是「已注销 / 临时停售 / 订货号停用」的事实；品牌级在售状态需按包装聚合（429 个品牌全部包装带标记） |
| 无 MT 注册号 | FEST 不含 `MT-nummer`；只有 `Varenr`（订货号）与 `Ean`。SmPC 链接形如 `…/preparatomtaler/21-14293.pdf`，其中的编号**形似** MT 号，但不作为字段依赖 |
| 价格 | `PrisVare` 存在（38,801 条），**本站不存价格**（与三条底线一致：不做剂量换算、不做价格比较） |
| 覆盖口径 | FEST 是**处方链/药房系统数据服务**（页面原文），院内制剂与兽医在**另外两个提取**里；页面写「挪威 FEST 收录（处方链）」而不是「挪威全部上市药品」 |

## 7 建议入库口径（下一写库窗口，本轮不实施）

1. `source` 行：`fest_no`，`license='NLOD 2.0'`，`license_url='https://data.norge.no/nlod/en/2.0'`，`source_url=下载页`，`data_cutoff='2026-11-10'`。
2. 产品层：以 `LegemiddelMerkevare` 为 product（8,985），`Varenavn` 进 `product_name`（不唯一，按三条底线一路返回候选集）；`LegemiddelformKort`、`Atc`、`ProduktInfo/Produsent`、`Reseptgruppe` 进对应列。
3. 成分层：`VirkestoffMedStyrke` → `Virkestoff/Navn`（挪威语）+ `NavnEngelsk`（英文）双写，INN 对齐优先英文名；含量原文 + 单位原样存，**不做单位换算**。
4. 包装层：`Varenr` / `Ean` / `Pakningsstr` + `EnhetPakning` 存为包装规格；`AvregDato` / `MidlUtgattDato` / `VarenrUtgaende` 派生 `status`（`active` / `discontinued` / `unknown`），**不把缺失当在售**。
5. 不入库：价格、SmPC 正文（只存链接）、`ProduktInfoVare` 的批发信息。
6. ETL 需要单元测试的点：XML 命名空间（`m30` / `forskrivning` 两套 ns）、`Oppf*` 包裹层、引用解析（`RefVirkestoffMedStyrke` / `RefVirkestoff` / `RefLegemiddelMerkevare`）、多 `Pakningsinfo`。
7. 页面署名 + 覆盖页写「数据截止 2026-11-10 / 每月 1·15 日更新 / NLOD 2.0」；About 九语按 §2 的署名文字扩展。

## 8 成本与风险

| 项 | 评估 |
|---|---|
| 人时 | **6–8 人时**（含 XML 解析、引用解析、成分名归一、包装层、单元测试、覆盖页文案） |
| 体量 | ZIP 14.5 MB → XML 118.3 MB（解压后不入库；只留小快照 + 许可说明到 `data/sources/`） |
| 风险 | **低-中**：许可清晰；风险集中在①挪威语成分名与 INN 对齐（有英文名兜底）；②无注册号 → 页面不能做「按注册号查」；③状态需聚合推断 → 文案必须写「含历史/停售标记的条目」而不是「在售」 |
| 不可做 | 不转载 SmPC 正文、不存价格、不做剂量换算 |

## 9 证据清单（全部官方 URL；抓取日 2026-11-21 北京时间）

| # | URL | 用途 |
|---|---|---|
| 1 | <https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest/downloading-fest-and-safest> | 下载入口 / 版本 2.5.0·2.5.1 / 每月 1·15 日 / 关闭提取说明 |
| 2 | <https://www.dmp.no/om-oss/distribusjon-av-legemiddeldata/fest/nedlasting-av-fest-og-safest> | 挪威语下载页（「Rekvirent-uttrekk」措辞、院内/兽医分开） |
| 3 | <https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest/responsibility-when-using-fest> | **NLOD 适用声明**（英文） |
| 4 | <https://www.dmp.no/om-oss/distribusjon-av-legemiddeldata/fest/ansvar-ved-bruk-av-fest> | NLOD 适用声明（挪威语原文） |
| 5 | <https://data.norge.no/nlod/en/2.0> | NLOD 2.0 全文（§2 权利 / §5 署名 / §6 正当使用 / §9 兼容） |
| 6 | <https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest> | 「FEST 是什么」口径（处方链数据服务） |
| 7 | `https://www.dmp.no/globalassets/documents/om-oss/distribusjon-av-legemiddeldata/fest/festfiler/fest251.zip` | 本轮实测 HTTP 200 / **14,550,258 B** / sha256 `CFCA96F2…5C66F3` |
| 8 | <https://www.dmp.no/robots.txt> | 抓取礼貌（仅禁 `/episerver/`、`/utils/`） |
| 9 | <https://data.norge.no/nb/datasets?q=fest> | 国家数据目录检索入口（本轮页面为 SPA，未取到条目 JSON；**许可证据以 #3/#4/#5 为准**） |

## 10 复现命令（只读，不写库）

```powershell
$py  = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$tmp = Join-Path $env:TEMP 'data_scout_noch_20261121'; New-Item -ItemType Directory -Force $tmp | Out-Null
Invoke-WebRequest 'https://www.dmp.no/globalassets/documents/om-oss/distribusjon-av-legemiddeldata/fest/festfiler/fest251.zip' -OutFile (Join-Path $tmp 'fest251.zip') -UseBasicParsing
Get-FileHash (Join-Path $tmp 'fest251.zip') -Algorithm SHA256     # 应为本报告的 CFCA96F2…
# 计数（命名空间无关；品牌/包装/成分-规格/成分主档）
& $py -c "import zipfile,xml.etree.ElementTree as ET,collections;z=zipfile.ZipFile(r'$tmp\fest251.zip');n=[i for i in z.namelist() if i.endswith('.xml')][0];c=collections.Counter();[c.update([e.tag.split('}')[-1]]) for _,e in ET.iterparse(z.open(n),events=('end',))];print(c['LegemiddelMerkevare'],c['Legemiddelpakning'],c['VirkestoffMedStyrke'],c['Virkestoff'])"
```

_本报告只做评估，不含任何写库、ingest、建站、测试或发布动作。_
