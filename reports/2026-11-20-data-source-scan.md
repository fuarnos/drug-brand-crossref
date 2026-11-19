# M8 新数据源自主检索与许可评估（MY / NO / CH 优先；JP / KR / NL 复核；DE / IT / IN / BR 初判）

- 日期：2026-11-20（北京时间）｜工位：phaseb-data｜任务：task-3
- 用户原话（2026-11-20）：「数据部分你自己找」「马来西亚也可以做」。
- 范围：**只读评估 + 写报告/许可清单**。未写 `data/drugs.db`、未跑 ingest、未改 `site/build.py`/`site/dist`/`CHANGELOG.md`、未发布、未付费、未注册任何账号、未绕 WAF。
- 方法：官方页面 + 官方批量文件（只下到系统临时目录做计数/字段核对），每个结论附官方 URL 与抓取日期；**只看产品级清单本身的许可**，不用「统计汇总有许可」代替。
- 外部工具：没有引入第三方镜像、爬虫框架或商业数据；全部用官方 CSV/XML + Python 标准库，避免许可与来源不可追溯。

## 0. 结论先行

| 市场 | 判定 | 一句话结论 | 产品级条数（实测） | 对 M5/M6 贡献 |
|---|---|---|---|---|
| **马来西亚 MY** | **🟢 可入库** | `data.gov.my` 收录 NPRA/QUEST3+「已批准产品」全量，**CC BY 4.0**，无需账号/申请；16 字段含商品名、成分+含量、通用名、ATC 线索 | **28,333** 已批准 + **1,623** 已注销 | 产品 +28,333；商品名 +约 28,135 |
| **挪威 NO** | **🟢 可入库** | FEST 2.5.1 公开 ZIP，**NLOD 2.0**（允许商用/再分发，须署名）；品牌级 + 包装级 | **8,985** 品牌条目 / **10,867** 包装 / 5,082 个唯一品牌名 | 产品 +8,985；商品名 +约 5,082 |
| **瑞士 CH** | **🟢 可入库** | Swissmedic OGD 月度 ZIP，资源标 **opendata.swiss `terms_open`**（自由商用，建议署名）；人用制剂 + 包装 + 成分声明 | **7,223** 人用制剂 / 11,613 序列 / **18,351** 人用包装 | 产品 +7,223；商品名 +约 7,900 |
| **日本 JP** | **✅ 已入库，无新增** | 厚労省薬価リスト 12,442 品目已入库；PDL 1.0。PMDA 添付文書虽也标 PDL 1.0，但站点政策**禁止批量/自动抓取**，只能做链接层 | 12,442（现库） | 0（已计入） |
| **韩国 KR** | **🟡 需人一句话** | `data.go.kr` 产品许可 API 免费但必须登录/申请 key；无「免账号 + 可批量 + 许可允许」的第二入口；HIRA 明确禁止再发布 | — | 0（等人） |
| **荷兰 NL** | **🟡 未获批（不变）** | GIP `metadata.csv` 仍公开可下（2026-11-18 更新），但无许可声明、国家目录仍「许可未知」；请求信无回音 | — | 0（等许可） |
| **德国 DE** | **🔴 当前不可批量** | BfArM AMIce 公共模块可查商品名/批准号/状态，但**无批量下载、无开放许可**；只能事实+链接 | — | 0 |
| **意大利 IT** | **🟡 需下一轮确认** | AIFA Open Data 明确 **CC BY 4.0、无需登录**，但目录所见为透明度/药物警戒/消费类数据，**未确认有 AIC 级全量产品清单** | 未确认 | 0（先花 2h 确认） |
| **印度 IN** | **⚪ 未查得** | CDSCO 官网/India.gov.in 只有查询与审批 PDF，未找到官方全量产品级批量包；不猜、不爬 | — | 0 |
| **巴西 BR** | **🟡 待确认许可** | ANVISA `DADOS_ABERTOS_MEDICAMENTOS.csv` 可下（229,708 行），但**无规格/剂型**，站点版权为 CC BY-ND 3.0、数据集级许可未写明 → 派生库风险 | 229,708 行（含重复流程） | 0（不建议先做） |

> **一句话建议：下一写库窗口先做马来西亚（MY）。** 单 MY 一国：M5 产品 594,781 → **623,114**；M6 商品名 780,843 → **约 808,978**，**直接越过 80 万商品名目标**。若窗口有余量，再按 **NO → CH** 顺序加 8,985 + 7,223 个产品。

## 1. 对照目标（现查 `data/drugs.db`，只读）

| 指标 | 目标 | 现状（2026-11-20 只读查询） | 加 MY 后 | 加 MY+NO+CH 后 |
|---|---|---|---|---|
| M5 产品 | 800,000 | **594,781** | **623,114**（77.9%） | **639,322**（79.9%） |
| M6 商品名 | 800,000 | **780,843** | **约 808,978**（101.1%） | **约 821,984**（102.7%，未计跨市场去重） |

> 复现：`& $py db/q.py "SELECT COUNT(*) FROM product"` / `"SELECT COUNT(*) FROM product_name"`（`mode=ro`，本轮未写库）。

## 2. 马来西亚 MY（NPRA / QUEST 3+）——🟢 本轮最大发现

**详细评估见 `reports/2026-11-20-my-license-assessment.md`**（对应需求队列 M7/T46）。要点：

- 官方数据集：<https://data.gov.my/data-catalogue/pharmaceutical_products>（2026-11-20 抓取）
  - 「Complete list of pharmaceutical products approved by the Drug Control Authority」；
  - 数据源 NPRA / MOH；QUEST3+ 行政记录，排除个人数据；每日更新。
- 许可：同页 **CC BY 4.0**；文件 <https://storage.data.gov.my/healthcare/pharmaceutical_products.csv> 实测 10,661,861 B / **28,333 行**。
- 字段：`reg_no, ref_no, product, status, description, holder, holder_osa, manufacturer, manufacturer_osa, importer, importer_osa, date_reg, date_end, active_ingredient, mdc_code, generic_name`。
- 缺口：**无独立剂型列**（剂型从商品名派生，76.7% 可派生）；规格在 `active_ingredient` 的 `[数量;单位;…]` 编码里；天然产品/保健品占 64%，不宜强行映射西药 INN。
- 成本：4–6 人时；风险主要是成分串解析与剂型词表，不涉及许可风险。

## 3. 挪威 NO（FEST / Direktoratet for medisinske produkter）——🟢

| 项 | 内容 |
|---|---|
| 官方入口 | 下载说明：<https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest/downloading-fest-and-safest>（2026-11-20 抓取） |
| 批量文件 | 公开 ZIP：`https://www.dmp.no/globalassets/documents/om-oss/distribusjon-av-legemiddeldata/fest/festfiler/fest251.zip`（实测 14,550,258 B；解压 `fest251.xml` 118,252,386 B） |
| 许可 | `responsibility-when-using-fest` 页明写 **NLOD**；许可原文 <https://data.norge.no/nlod/en/2.0>：可复制/使用/分发、可商用、须署名、须标明修改、不得暗示背书；与 CC BY 4.0 兼容 |
| 数据日期 | XML `HentetDato = 2026-11-10T10:24:32`；每月 1 日/15 日发布 |
| 条数（实测） | **8,985** 个 `LegemiddelMerkevare`（品牌条目）；**10,867** 个 `Legemiddelpakning`（包装）；`NavnFormStyrke` 8,985 条（含剂型+规格）；ATC 8,722（97.1%）；剂型 8,985；唯一 `Varenavn` **5,082**；唯一 `NavnFormStyrke` 8,123 |
| 字段 | 商品名 `Varenavn`、剂型 `LegemiddelformKort/Lang`、ATC `Atc`、成分+规格 `SortertVirkestoffMedStyrke`（引用 `VirkestoffMedStyrke`）、MAH `Produsent`；包装级有 `Varenr`/`Ean`/`Pakningsstr` |
| 成本 | 6–8 人时（118 MB XML、引用解析、挪威语成分名归一、品牌/包装两层建模） |
| 风险 | FEST 是处方支持库，含部分非在售/历史条目；页面口径写「挪威 FEST 收录」，不写「挪威全部上市药品」 |

## 4. 瑞士 CH（Swissmedic OGD）——🟢

| 项 | 内容 |
|---|---|
| 官方入口 | <https://opendata.swiss/en/dataset/daten-von-human-und-tierarzneimitteln>（2026-11-20 抓取；CKAN 元数据 `ZL172@swissmedic`） |
| 批量文件 | <https://ogd.swissmedic.cloud/ogd-arzneimittel/Daten/OGD.zip>（实测 2,899,947 B） |
| 许可 | 资源 `license = https://opendata.swiss/terms-of-use#terms_open`；条款页：`terms_open` = **Open use**（非商业/商业均可，**建议**署名，非强制；本站仍署名）<https://opendata.swiss/en/terms-of-use#terms_open> |
| 数据日期 | `OGD-Export-Datum.XML` = **2026-10-31**；月度更新（上月最后一天） |
| 条数（实测） | **7,984** 个制剂（**人用 7,223** / 兽用 761）；**12,683** 个序列（人用 11,613）；**20,112** 个包装（人用 18,351）；**125,365** 行成分声明（人用 116,592） |
| 字段 | `ZULASSUNGSNUMMER`、`PRAEPARATENAME`、`ARZNEIFORM`、`ATC_CODE`、`ZULASSUNGSSTATUS`、`ZULASSUNGSINHABERIN`、`ABGABEKATEGORIE`、`ERSTZULASSUNGSDATUM`、`ABLAUFDATUM`；序列有 `SEQUENZNAME`；声明有 `STOFF_ID` + `MENGE` + `MENGEN_EINHEIT`；包装有 `PACKUNGSGROESSE`/`PACKUNGSEINHEIT` |
| 覆盖 | 人用制剂 ATC 6,325/7,223（87.5%）；人用序列中 **11,503/11,611** 有「活性成分 + 含量」声明（99.1%） |
| 成本 | 8–10 人时（多 XML 关联、德/法/意成分名、序列/包装/声明三层 join） |
| 风险 | 含已撤销/历史制剂（status Z/B/D/S）；页面口径写「Swissmedic 授权制剂」，不写「瑞士全部在售」；`terms_open` 虽不强制署名，仍按本站惯例署名 |

## 5. 日本 JP——✅ 已入库，PMDA 只做链接层

- 现库 **12,442** 个 JP 产品（`SELECT COUNT(*) FROM product WHERE country='JP'`，2026-11-20 只读查询），来自厚労省「薬価基準収載品目リスト」；许可 **PDL 1.0**（与 CC BY 4.0 兼容）：
  - <https://www.mhlw.go.jp/chosakuken/index.html>（2026-11-20 抓取，原文「公共データ利用規約（第1.0版）…に準拠」）。
- PMDA 添付文書：站点政策 <https://www.pmda.go.jp/english/0013.html>（2026-11-20 抓取）明确 **PDL 1.0 适用**，但同页「Notes on Downloading Information」写明：
  > 「Bulk, excessive, or frequent downloads that place excessive load on the server are strictly prohibited. Automated crawling or download applications are also not permitted.」
  → **不能批量抓取**；只能做「薬価リスト品名 → PMDA 检索」的链接层。JP 无需新增批量源，也不建议扩 PMDA 抓取。

## 6. 韩国 KR——🟡 仍需人一句话

- 官方产品级 API：`식품의약품안전처_의약품 제품 허가정보` <https://www.data.go.kr/data/15095677/openapi.do>（2026-11-20 抓取；页面要求登录，`data.go.kr` 会员需韩国手机实名）。
- 许可写作「이용허락범위 제한 없음」（限制范围：无），**许可不是卡点、账号是**。
- 2026-11-19 已逐项实测的「免账号」替代源（`reports/2026-11-19-kr-account-free-sources.md`）：
  - nedrug 公开页可读但 `robots.txt` 全站 `Disallow: /`，无批量许可；
  - `data.mfds.go.kr` 文件版匿名下载被导错误页，登录同样要实名；
  - HIRA 条款明确禁止复制/加工/再发布/自动抓取。
- 结论：**维持「只做链接层、不入库」**；要推进只能由人完成一次 `data.go.kr` key 申请（约 5 分钟）或提供韩国实名账号。**不需要再花 agent 时间。**

## 7. 荷兰 NL（CBG-MEB）——🟡 许可未变

- 数据文件仍可下：`https://www.geneesmiddeleninformatiebank.nl/metadata.csv` → HTTP **200**，**16,456,324 B**，`Last-Modified: 2026-11-18 05:32:35 GMT`（2026-11-20 复核）。
- 许可仍未解决：GIP 页面无版权/许可声明；`data.overheid.nl` 数据集条目仍 404（2026-11-20 复核，与 2026-11-11 相同）；国家目录 `licentieonbekend` 口径不变（<https://data.overheid.nl/en/node/70>）。
- 2026-11-11 请求信无回音；**NL 继续不入库、不上线、不开 `nl` 语言**。本轮不重复发信（发信属人的决定）。

## 8. DE / IT / IN / BR 初判（只做可行性，不深挖）

| 市场 | 官方入口（2026-11-20 抓取） | 产品级批量 | 许可 | 初判 |
|---|---|---|---|---|
| **DE 德国** | BfArM AMIce 公共模块：<https://www.bfarm.de/DE/Arzneimittel/Arzneimittelinformationen/Arzneimittel-recherchieren/AMIce/_node.html> | ❌ 只有检索库；公共模块含 Handelsname / Zulassungsnummer/-datum / Zulassungsstatus，但未见 CSV/API/批量包 | 未见开放数据许可 | **🔴 当前不可批量**；若做只能事实+链接（像 TGA 明细层），不优先 |
| **IT 意大利** | AIFA Open Data：<https://www.aifa.gov.it/en/open-data> | ⚠️ 明确「无需登录、CSV/XML、可下载」，但目录所见为 `liste-dei-farmaci`（A/H 类）、`farmacovigilanza-open-data`、`spesa-e-consumo`；**未确认有 AIC 级全量产品清单** | **CC BY 4.0**（页面原文） | **🟡 需下一轮确认**：先花 2h 找 AIC 级数据集；若只有透明度/消费数据则不做 |
| **IN 印度** | CDSCO / India.gov.in「Drug Approval Information Service」；CDSCO 官网 | ❌ 未找到官方全量产品级批量包（只有查询与审批 PDF） | 未取证 | **⚪ 未查得**（不绕、不爬、不买第三方镜像） |
| **BR 巴西** | ANVISA 开放数据：<https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv>；说明页 <https://www.gov.br/anvisa/pt-br/acessoainformacao/dadosabertos> | ✅ 文件可下（46,098,918 B / **229,708 行**），但只有商品名、注册号、持有人、状态、活性成分、治疗类别；**无规格、无剂型** | ⚠️ 站点页脚 **CC BY-ND 3.0**（禁止演绎）；数据集级许可未写明 → 派生库有风险 | **🟡 待确认许可 + 字段不够**；不建议先做 |

## 9. 推荐顺序与成本

| 顺序 | 市场 | 许可 | 产品 + | 商品名 + | 人时 | 阻塞 |
|---|---|---|---|---|---|---|
| **1** | **MY** | 🟢 CC BY 4.0 | **28,333** | **约 28,135** | 4–6h | 无 |
| **2** | **NO** | 🟢 NLOD 2.0 | **8,985** | 约 5,082 | 6–8h | 无 |
| **3** | **CH** | 🟢 terms_open | **7,223** | 约 7,900 | 8–10h | 无 |
| 4 | JP | ✅ 已入 | 0 | 0 | 0 | 无（PMDA 只链接） |
| 5 | KR | 🟡 | — | — | 2h（拿到 key 后） | **需人申请 key** |
| 6 | IT | 🟡 | 未知 | 未知 | 2h 先确认 | 需确认数据集 |
| — | NL | 🟡 | — | — | — | 等许可回信 |
| — | DE / IN / BR | 🔴/⚪/🟡 | — | — | — | 当前不做 |

**排期建议**：下一写库窗口只做 MY（先把 M6 推过 80 万，风险最低）；若同一窗口有余量，接 NO；CH 放再下一个窗口（XML 关联最重，但字段最全）。

## 10. 还剩什么 / 需要人决定

1. **MY 入库窗口**：需要分配一次写库窗口（`etl/markets/my.py` + `source` 行 + About 三语署名 + `db/check_data.py`）。本轮只出许可结论，未写实现。
2. **NO / CH 入库**：许可已够，等排期；两源都是 XML，建议各写一个独立 ingest + 单元测试。
3. **KR**：**需人一句话**——由人完成 `data.go.kr` 实名/key（`15095677`），或提供已实名账号；agent 不注册。
4. **NL**：等 CBG-MEB 回信；11-25 / 12-09 跟进节点已在 `docs/跟进提醒.md`。
5. **IT**：下一轮 2h 确认是否存在 AIC 级全量数据集；若无，不做。
6. **DE / IN / BR**：本轮初判不做；BR 若要做，先解决「CC BY-ND + 无规格/剂型」两件事。

## 11. 证据清单（全部为官方 URL；抓取日期 2026-11-20，KR 为 2026-11-19 复核）

| # | 市场 | URL | 用途 |
|---|---|---|---|
| 1 | MY | <https://data.gov.my/data-catalogue/pharmaceutical_products> | 数据集页 / 字段 / CC BY 4.0 / 更新日期 |
| 2 | MY | <https://storage.data.gov.my/healthcare/pharmaceutical_products.csv> | 28,333 行，10,661,861 B |
| 3 | MY | <https://data.gov.my/data-catalogue/pharmaceutical_products_cancelled> | 1,623 行注销清单，CC BY 4.0 |
| 4 | NO | <https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest/downloading-fest-and-safest> | FEST 下载入口 |
| 5 | NO | <https://www.dmp.no/en/about-us/distribution-of-data-on-medicinal-products/electronic-prescription-support-system-fest/responsibility-when-using-fest> | NLOD 适用声明 |
| 6 | NO | <https://data.norge.no/nlod/en/2.0> | NLOD 2.0 原文 |
| 7 | NO | `https://www.dmp.no/globalassets/documents/om-oss/distribusjon-av-legemiddeldata/fest/festfiler/fest251.zip` | 14,550,258 B；8,985 品牌 / 10,867 包装 |
| 8 | CH | <https://opendata.swiss/en/dataset/daten-von-human-und-tierarzneimitteln> | 数据集元数据 / `terms_open` |
| 9 | CH | <https://ogd.swissmedic.cloud/ogd-arzneimittel/Daten/OGD.zip> | 2,899,947 B；7,223 人用制剂 |
| 10 | CH | <https://opendata.swiss/en/terms-of-use#terms_open> | 使用条款 |
| 11 | JP | <https://www.mhlw.go.jp/chosakuken/index.html> | PDL 1.0 |
| 12 | JP | <https://www.pmda.go.jp/english/0013.html> | PMDA PDL 1.0 + 禁止批量抓取 |
| 13 | KR | <https://www.data.go.kr/data/15095677/openapi.do> | 产品许可 API（需登录/key） |
| 14 | KR | `reports/2026-11-19-kr-account-free-sources.md` | 免账号源实测（nedrug/HIRA/data.mfds） |
| 15 | NL | <https://www.geneesmiddeleninformatiebank.nl/metadata.csv> | HEAD 200 / 16,456,324 B / 2026-11-18 |
| 16 | NL | <https://data.overheid.nl/en/node/70> | 「许可未知 = 非开放数据」口径 |
| 17 | DE | <https://www.bfarm.de/DE/Arzneimittel/Arzneimittelinformationen/Arzneimittel-recherchieren/AMIce/_node.html> | AMIce 公共模块（无批量） |
| 18 | IT | <https://www.aifa.gov.it/en/open-data> | CC BY 4.0 / 无需登录 |
| 19 | BR | <https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv> | 229,708 行 / 46,098,918 B |
| 20 | BR | <https://www.gov.br/anvisa/pt-br/acessoainformacao/dadosabertos> | 站点页脚 CC BY-ND 3.0 |

## 12. 复现命令（只读、不写库）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'

# 现查 M5/M6
& $py db/q.py "SELECT COUNT(*) FROM product"
& $py db/q.py "SELECT COUNT(*) FROM product_name"
& $py db/q.py "SELECT country, COUNT(*) FROM product GROUP BY country ORDER BY 2 DESC"

# MY：下载到临时目录并计数
$tmp = Join-Path $env:TEMP 'my_check'; New-Item -ItemType Directory -Force $tmp | Out-Null
Invoke-WebRequest 'https://storage.data.gov.my/healthcare/pharmaceutical_products.csv' -OutFile (Join-Path $tmp 'products.csv') -UseBasicParsing
& $py -c "import csv; rows=list(csv.DictReader(open(r'$tmp\products.csv',encoding='utf-8'))); print(len(rows), rows[0]['product'])"

# NO / CH：下载 ZIP 到临时目录后解压计数（命令见各节入口页）
```

_本报告只做评估与建议，不含任何写库、ingest、建站或发布动作。_
