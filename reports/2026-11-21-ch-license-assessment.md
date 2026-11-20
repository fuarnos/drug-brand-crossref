# 瑞士（CH）Swissmedic OGD · 人用药品开放数据——再发布许可与字段可得性评估

- 日期：2026-11-21（北京时间）｜工位：data-scout｜任务：task-5（DATA1，REL2 发布期间只读调研）
- 队列依据：M5「产品记录 80 万」、M2「NO / CH 只读复核」；上一轮概览见 `reports/2026-11-20-data-source-scan.md` §4
- **只读声明**：未写 `data/drugs.db`、未跑 ingest / `run_all.py` / `site/build.py` / 任何测试、未改 `site/` `etl/` `deploy/`、未 commit、未发布。只把官方 ZIP 下到系统临时目录做计数与字段核对（`%TEMP%\data_scout_noch_20261121\`）。
- **结论：🟢 可再发布（opendata.swiss `terms_open` = Open use，商用/非商用均可，署名是「建议」而非强制；本站仍署名）**。字段最全（注册号 / 状态 / MAH / 剂型 / 成分+含量 / 包装规格全部结构化），**无阻塞项**；主要成本在 10 个 XML 的三层关联与多语码表。

## 0 需人（决策 / 邮箱）

- **无阻塞项**。条款属开放使用（`terms_open`），不需要申请、不需要账号、不需要发信。
- **可选确认（非阻塞，本轮不发）**：数据集级 `license_id` 为空、opendata.swiss 的 `isopen` 标志为 `false`（6 个 Swissmedic 数据集全部如此，属门户元数据惯例，许可写在**每个分发**上）。若以后要一份更硬的书面口径，可向 Swissmedic 的开放数据联系点（数据集 `contact_points`）问一句；**按现证据已够入库**。
- 本轮**不接 AIPS**（说明书/结构化药品信息平台，见 §7），故不涉及 refdata.ch 的账号/合同问题。

## 1 结论先行

| 问题 | 答案（证据见 §2、§4） |
|---|---|
| 有没有产品级批量入口？ | **有**。opendata.swiss 数据集 `daten-von-human-und-tierarzneimitteln`（CKAN id `ZL172@swissmedic`）→ 分发 `OGD.zip`；实测 HTTP 200、**2,899,947 B**、免账号 |
| 许可允许再发布吗？ | **允许**。5 个分发的 `dct:license` **和** `dct:rights` 均为 `http://dcat-ap.ch/vocabulary/licenses/terms_open`；opendata.swiss 条款页把 `terms_open` 定义为 **Open use**：可商用、可非商用，**建议**（recommended）署名 |
| 数据量（实测） | **7,984** 个制剂（**人用 HAM 7,223** / 兽用 TAM 761）；**12,683** 个序列（人用 **11,613**）；**20,112** 个包装（人用 **18,351**）；**125,365** 行成分声明（人用 WIRKS **20,750** 行） |
| 数据截止 | `OGD-Export-Datum.XML` = **2026-10-31**（数据集说明：「Each dataset is based on the last calendar day of the previous month」）；ZIP 内 10 个 XML 文件时间 2026-11-01 |
| 更新频率 | **每月**（DCAT `accrual_periodicity = …/frequency/MONTHLY`） |
| 字段：商品名 / 成分+含量 / 剂型 / MAH / 注册号 / 状态 | 商品名 `PRAEPARATENAME` 7,223/7,223；成分 `Deklarationen/STOFF_ID` → `Stoff-Synonyme/STOFFSYNONYM`（拉丁名，人用 3,784 个成分 **100% 有名字**）；含量 `MENGE`+`MENGEN_EINHEIT`；剂型 `ARZNEIFORM`（码，多语描述见 UDC `DF`）；MAH `ZULASSUNGSINHABERIN`（伙伴号 → `Adressen/FIRMENNAME`，335 家 **100% 可解析**）；**注册号 `ZULASSUNGSNUMMER`**；状态 `ZULASSUNGSSTATUS`（Z/B/D/S，UDC `MA_STATUS` 有定义） |
| 规格 | 包装规格 `PACKUNGSGROESSE` + `PACKUNGSEINHEIT`：人用 **18,264/18,351 = 99.5%** |
| 缺口 | ① **商品名只有德语**（`PRAEPARATENAME`/`SEQUENZNAME` 单语）；② 成分只有**拉丁名**（`SYNONYM_CODE=LN`，5,970 条全部），没有德语/法语/意大利语通用名；③ **无 GTIN/条码、无价格**；④ 含「已撤销」条目但只覆盖最近一个月窗口（详见 §6）；⑤ MAH 需 join 地址表 |
| 入库成本估算 | **8–10 人时**（10 个 XML、三层 join、多语码表、序列/包装/声明建模） |
| 对目标贡献 | 产品 **+7,223**（人用制剂）；商品名 **+约 7,164**（人用唯一制剂名） |

## 2 许可证据（2026-11-21 抓取）

| # | 证据 | 原文短引 | 判定 |
|---|---|---|---|
| 1 | 数据集页（英）：<https://opendata.swiss/en/dataset/daten-von-human-und-tierarzneimitteln> | 标题「Data relating to human and veterinary medicines」；发布者「Swissmedic Swiss Agency for Therapeutic Products」；`modified: 2025-06-13`、`metadata_modified: 2026-11-20T08:13:22Z` | 官方数据集 |
| 2 | CKAN API（同一数据集）：`/api/3/action/package_show?id=daten-von-human-und-tierarzneimitteln` | 5 个分发（4 份说明 PDF + `OGD.zip`）**每个**都带 `license/rights = https://opendata.swiss/terms-of-use#terms_open`；数据集级 `license_id = null`、`isopen = false` | **许可在分发级** |
| 3 | DCAT-AP CH 导出（`.ttl` / `.rdf`）：<https://opendata.swiss/en/dataset/daten-von-human-und-tierarzneimitteln.ttl> | 每个分发同时给出 `dct:license <http://dcat-ap.ch/vocabulary/licenses/terms_open>` 与 `dct:rights <…terms_open>`；并声明 `<…terms_open> a dct:LicenseDocument, dct:RightsStatement` | **机器可读的许可声明** |
| 4 | 使用条款页：<https://opendata.swiss/en/terms-of-use#terms_open> | 「**Open use**」：「You may use this dataset for non-commercial purposes. You may use this dataset for commercial purposes. **You are *recommended* to provide the source (author, title and link to the dataset).**」 | **🟢 可再发布 / 商用** |
| 5 | 数据集说明（CKAN `description`） | 「The following details are published: authorised medicines / dosage strengths / packs at the cut-off date, and medicines / dosage strengths / packs that are no longer authorised, with **revocation date** … >= final cut-off date. **Each dataset is based on the last calendar day of the previous month.**」 | 口径：含最近撤销条目，**不是**全历史库 |
| 6 | 同组织其他数据集的元数据模式（对照） | `package_search?fq=organization:swissmedic` → **6/6** 数据集 `isopen=false`、`license_id=null`；许可写在**分发**上（`terms_open` 出现在 4 个数据集的 6 个分发上，另 1 个数据集 3 个分发为 `terms_by`） | `isopen=false` 是**门户元数据惯例**，不是权利限制 |
| 7 | 版本勘误（写给下游） | 队列旧记录把 CH 记成 `terms_by`（「可商用 + 须署名」）；**实测 DCAT 为 `terms_open`**（署名属「建议」非强制）。本站仍按惯例署名，但**不因为「必须署名」去发申请信** | 口径修正 |

**允许**：商业与非商业使用、复制、再分发、演绎（无 share-alike）。
**义务**：署名是**建议**（推荐给出「作者 / 标题 / 数据集链接」）。本站仍按「署名 + 数据截止 + 许可链接 + 标明修改」执行。
**限制**：不得暗示 Swissmedic 背书；不转售/不转载原始 ZIP；不复制非事实的受版权文本（本站只存事实字段）。
**建议署名文字**（四语 + 中文，写进 About / 覆盖页 / datapackage）：

- 德：`Quelle: Swissmedic, «Daten von Human- und Tierarzneimitteln», opendata.swiss (Open use / terms_open), Stand 2026-10-31. Änderungen durch DrugCrossRef (Normalisierung).`
- 英：`Source: Swissmedic, "Data relating to human and veterinary medicines", opendata.swiss (Open use / terms_open), as of 2026-10-31. Changes made by DrugCrossRef.`
- 法：`Source : Swissmedic, « Données sur les médicaments à usage humain et vétérinaire », opendata.swiss (Open use / terms_open), état au 2026-10-31.`
- 意：`Fonte: Swissmedic, «Dati sui medicamenti per uso umano e per uso veterinario», opendata.swiss (Open use / terms_open), stato al 2026-10-31.`
- 中：`数据来自瑞士药品管理局（Swissmedic）开放数据「人用与兽用药品数据」，按 opendata.swiss「Open use（terms_open）」提供，数据截止 2026-10-31；本站已做归一化修改，原始文件不转载。`

## 3 必查 12 项（`docs/数据源调研清单.md` §3）

| # | 项 | 结论与证据 |
|---|---|---|
| 1 | 官方入口 URL | 数据集 <https://opendata.swiss/en/dataset/daten-von-human-und-tierarzneimitteln>；文件直链 <https://ogd.swissmedic.cloud/ogd-arzneimittel/Daten/OGD.zip> |
| 2 | 许可原文 + 名称 | **opendata.swiss `terms_open`（Open use）**；条款 <https://opendata.swiss/en/terms-of-use#terms_open>；DCAT 词汇表 `http://dcat-ap.ch/vocabulary/licenses/terms_open` |
| 3 | 再发布限制 | 允许商用 ✅、允许演绎 ✅、署名「建议」；未见禁止批量抓取；不得暗示背书 |
| 4 | 是否需账号 | **免账号、免注册、免费**（ZIP 直链匿名可下） |
| 5 | 批量入口形态 | ZIP（内含 **10 个 XML**，合计约 72 MB；`OGD-Praeparate / Sequenzen / Packungen / Deklarationen / ATC-Codes / Stoff-Synonyme / Adressen / Applikationsarten pro Sequenz / User-Defined-Codes / Export-Datum`） |
| 6 | 字段清单 | 商品名 ✅、成分 ✅（拉丁名）、含量 ✅、剂型 ✅（码+多语描述）、包装规格 ✅、MAH ✅（join 地址表）、**注册号 ✅**、状态 ✅、日期 ✅（首次批准/截止/撤销放弃日） |
| 7 | 条数（实测） | 制剂 **7,984**（人用 7,223）/ 序列 **12,683**（人用 11,613）/ 包装 **20,112**（人用 18,351）/ 成分声明 **125,365** 行 / ATC 码 **2,223** / 地址 **352** / 成分同义词 **5,970** / 代码表 **7,174** 行 |
| 8 | 更新频率 / 截止 | **每月**（上月最后一天为截止）；本轮 `EXPORT_DATUM = 2026-10-31` |
| 9 | 规格与剂型可得性 | 剂型 **结构化 100%**（`ARZNEIFORM` 308 种码，UDC `DF` 945 码带 D/E/F/I 描述）；含量：**11,503/11,603 人用序列 = 99.1%** 有 `MENGE`；包装规格 **99.5%**；无需从名称解析 |
| 10 | 署名要求原文 | 条款页「You are **recommended** to provide the source (author, title and link to the dataset)」；本站升级为强制署名（§2 文字） |
| 11 | 抓取礼貌 | `https://ogd.swissmedic.cloud/robots.txt` → **404（未声明限制）**；`https://www.swissmedic.ch/robots.txt` → 404；按「每个写库窗口下一次 OGD.zip（2.9 MB）」执行，带可识别 UA |
| 12 | 入库成本 / 风险 | **8–10 人时**；风险：① 三层 join（制剂→序列→包装/声明）；② 商品名只有德语；③ 成分只有拉丁名，INN 对齐要走拉丁词尾规则；④ 「已撤销」只覆盖最近一个月窗口，文案不能写「历史全库」 |

## 4 字段与实测覆盖率

关系模型（全部以 `ZULASSUNGSNUMMER` / `SEQUENZNUMMER` / `PACKUNGSCODE` 串联）：

```
Praeparate (7,984)  ──1:N──▶ Sequenzen (12,683) ──1:N──▶ Packungen (20,112)
      │                            │
      │                            └── Deklarationen (125,365 行：STOFF_ID + MENGE + MENGEN_EINHEIT)
      ├── ZULASSUNGSINHABERIN ──▶ Adressen (352 家：FIRMENNAME / LAND_CODE / PLZ / ORT / KANTON)
      ├── ATC_CODE ──▶ ATC-Codes (2,223)
      └── STOFF_ID ──▶ Stoff-Synonyme (5,970；SYNONYM_CODE=LN 拉丁名)
            ARZNEIFORM / PACKUNGSEINHEIT / ZULASSUNGSSTATUS / ABGABEKATEGORIE ──▶ User-Defined-Codes (7,174 行，含 D/E/F/I 描述)
```

制剂级 `PRAEPARAT`（7,984；下列覆盖率以**人用 7,223** 为分母）：

| 字段 | 含义 | 覆盖（人用） |
|---|---|---|
| `PRAEPARATENAME` | 商品名（**德语**，含剂型说明，如 `Zeller Herz und Nerven Classic, Tropfen zum Einnehmen`） | 7,223（100%）；唯一名 **7,164** |
| `ZULASSUNGSNUMMER` | **注册号**（5 位数字，如 `10029`） | 7,223（100%） |
| `ARZNEIFORM` | 剂型码（`TAB` / `FILM` / `TROF` …，308 种） | 7,223（100%） |
| `ATC_CODE` | ATC（含 4 位码，如 `C01EX`） | **6,325（87.6%）** |
| `ZULASSUNGSSTATUS` | 状态（Z/B/D/S，见 §6） | 7,223（100%） |
| `ZULASSUNGSINHABERIN` | **MAH 伙伴号** → `Adressen` 名称 | 7,223（100%）；335 家全部解析成功 |
| `ERSTZULASSUNGSDATUM` | 首次批准日（最早 1933-09-13，最新 2026-10-30） | 有值 |
| `ABLAUFDATUM` | 授权截止/结束日（`9999-12-31` = 无到期） | 有值 |
| `ABGABEKATEGORIE` | 发放类别（A / A+ / B / B/D / D / E） | 7,223（100%）：`B 3,593 / D 1,818 / A 1,522 / E 133 / A+ 98 / B/D 59` |
| `HEILMITTEL_CODE` / `ZULASSUNGSKATEGORIE` / `IT_NUMMER` / `ANWENDUNGSGEBIET` | 药品类别 / 授权类别 / IT 号 / 适应症（德文短句） | 有值（适应症只做事实展示，不转正文） |

序列级 `SEQUENZ` / 包装级 `PACKUNG`（人用 11,613 / 18,351）：

| 字段 | 含义 | 覆盖（人用） |
|---|---|---|
| `SEQUENZNAME` | 序列名（德语，通常=商品名+剂型/规格） | 11,613；唯一 **11,548** |
| `ZULASSUNGSART` | 授权类型（`H` = Hauptzulassung 主批准等，UDC `MA_TYPE`） | 11,613 |
| `PACKUNGSGROESSE` + `PACKUNGSEINHEIT` | **包装规格 + 单位**（如 `200 / ML`；单位码 `TABL 8,111 / ML 2,314 / KAP 1,781 / DUR 1,370 / G 923 / AMP 751 …`） | **18,264 / 18,351 = 99.5%** |
| `PACKUNGSCODE` | 包装码（与注册号/序列号组合定位包装） | 18,351 |
| `ABGABEKATEGORIE` | 包装级发放类别 | 18,351（`B 11,201 / A 3,491 / D 2,678 / A+ 595 / E 386`） |
| `WIDERRUF_VERZICHT_DATUM` | 放弃撤销日（少量：制剂 19 / 序列 19 / 包装 58） | 少量 |
| `BTM_CODE` / `PACKUNGSTYP` | 麻醉品表 / 包装类型（`K` 组合包、`SE` Set …） | 841 / 530 |

成分声明 `DEKLARATION`（125,365 行；人用 WIRKS 20,750 行）：

- `STOFF_ID` → `Stoff-Synonyme`：**人用 3,784 个成分 100% 有名字**（全部 `SYNONYM_CODE=LN` 拉丁名，来源标注 `DCI` / `IUP`，如 `capecitabinum`）；
- `MENGE` + `MENGEN_EINHEIT`：人用 WIRKS 行 **20,291/20,750 = 97.8%** 有含量；按序列算 **11,503/11,603 = 99.1%**；
- `DEKLARATIONSART`（UDC `DECLA_FORMAT`：1 定量 / 2 定性）人用 `1 = 20,505`、`2 = 245`；
- **复方**：人用 **2,438** 个序列含 ≥2 种成分（最多 59 种）；189 个序列同一成分多行（含量区间/多组分）。

样例（原文，2026-11-21 从 `OGD-*.XML` 抽录）：

```xml
<PRAEPARAT><VERWENDUNG>HAM</VERWENDUNG><ZULASSUNGSNUMMER>10029</ZULASSUNGSNUMMER>
  <PRAEPARATENAME>Zeller Herz und Nerven Classic, Tropfen zum Einnehmen</PRAEPARATENAME>
  <ARZNEIFORM>TROF</ARZNEIFORM><ATC_CODE>C01EX</ATC_CODE><HEILMITTEL_CODE>P</HEILMITTEL_CODE>
  <ZULASSUNGSSTATUS>Z</ZULASSUNGSSTATUS><ZULASSUNGSINHABERIN>1000324</ZULASSUNGSINHABERIN>
  <ERSTZULASSUNGSDATUM>1966-02-04</ERSTZULASSUNGSDATUM><ABGABEKATEGORIE>D</ABGABEKATEGORIE>
  <ABLAUFDATUM>9999-12-31</ABLAUFDATUM></PRAEPARAT>

<DEKLARATION><ZULASSUNGSNUMMER>10029</ZULASSUNGSNUMMER><SEQUENZNUMMER>2</SEQUENZNUMMER>
  <STOFF_ID>001F295B…</STOFF_ID><STOFFKATEGORIE>WIRKS</STOFFKATEGORIE>
  <MENGE>31</MENGE><MENGEN_EINHEIT>MG</MENGEN_EINHEIT><DEKLARATIONSART>1</DEKLARATIONSART></DEKLARATION>

<SYNONYME><STOFF_ID>001F295B…</STOFF_ID><SYNONYM_CODE>LN</SYNONYM_CODE>
  <STOFFSYNONYM>capecitabinum</STOFFSYNONYM><QUELLE>DCI</QUELLE></SYNONYME>
```

## 5 规格与剂型可得性 / 多语情况

- **剂型**：`ARZNEIFORM` 码 308 种，`User-Defined-Codes` 的 `DF` 分组（945 码）给出**德/英/法/意**四语描述，例如 `TAB` → `Tablette / tablet / comprimé / compressa`。**不需要自己翻译剂型**。
- **包装单位**：UDC `PACKAGE_UNIT`（140 码）同样四语，如 `DUR` → `Durchstechflasche(n) / vial(s) / flacon(s) / flaconcino`。
- **含量**：`MENGE` 数值 + `MENGEN_EINHEIT`（`MG` / `G` / `ML` / `IU` …）结构化；按序列 99.1% 覆盖；**不做单位换算**（原样存）。
- **商品名**：只有德语。瑞士实际包装分德/法/意三语区，品牌名多数跨语一致但不保证（如 `Zeller Herz und Nerven Classic`）；页面要写清「商品名为 Swissmedic 登记的德语名」。
- **成分名**：只有拉丁名（INN 词干完整，如 `capecitabinum`）。做 INN 对齐需拉丁→英文词尾规则（`-um→-e`、`-inum→-ine` 等）+ 词表兜底；**不要**用商品名猜成分。
- **多语显示**：剂型/单位/给药途径/状态这些**码值**有四语描述；商品名与适应症只有德语 → 页面多语化时只翻译 UI 与码值，不翻译商品名。

## 6 状态与日期语义（页面口径必须写清）

| 事实 | 说明 |
|---|---|
| `ZULASSUNGSSTATUS`（UDC `MA_STATUS`） | `Z = zugelassen`（已批准）、`B = befristet`（有期限）、`D = nicht mehr zugelassen`（已不再批准）、`S = sistiert`（中止）；码表另有 `A / N / U / BA`（本轮数据未出现） |
| 人用分布 | 制剂 `Z 7,192 / B 18 / D 12 / S 1`；包装 `Z 18,284 / D 39 / B 27 / S 1` |
| `ABLAUFDATUM` 语义 | `9999-12-31` = 无到期日（人用 **6,111** 条）；其余为**授权有效期截止/结束日**：人用 **1,112** 条有具体日期，范围 **2026-10-01 – 2031-10-29**（未来 1,093 / 已过 19） |
| 「含撤销条目」的窗口 | 数据集说明写「不再批准的制剂…撤销日 ≥ 本轮截止日」；实测全库最早 `ABLAUFDATUM = 2026-10-01` → **只覆盖最近约一个月内撤销的条目**，不是历史全库 |
| 需注意的脏点 | 有 **7 条**人用制剂 `ZULASSUNGSSTATUS=Z` 但 `ABLAUFDATUM=2026-10-31`（已过期）→ 入库按「日期优先，冲突标 `unknown`」，不要二选一硬判 |
| 覆盖口径 | 页面写「Swissmedic 授权制剂（人用）」，**不写**「瑞士全部在售药品」；兽用（TAM 761）本轮不入 |

## 7 AIPS（Swissmedic 药品信息发布系统）——不接，只登记

- AIPS = 官方说明书/患者信息（FI/PI）+ 结构化药品信息（SAI）的发布系统，由 **Stiftung Refdata**（HCI Solutions）运营；条款页：<https://refdata.ch/de/nutzungsbestimmungen-aips-sai>（法文 <https://refdata.ch/fr/terms-of-use-aips-sai>；「Letzte Änderung: 1. März 2021」；「Der deutsche Text gilt als Originaltext」）。
- 条款 §5 原文：「Sämtliche Eigentums- und Schutzrechte an den INFORMATIONEN stehen Refdata oder den Zulassungsinhaberinnen zu. … **Zulässig sind der Export der INFORMATIONEN (XML-Download) zur Nutzung der Daten ausserhalb dieser Applikation, die Weiterverwendung und das Bearbeiten der INFORMATIONEN sowie die Verwendung für öffentliche oder kommerzielle Zwecke.**」
- 判定：**AIPS 对本任务不是必需**——它是说明书/结构化信息，**不是注册清单**；注册清单（注册号/状态/MAH/包装规格）在 OGD 里已齐。AIPS 的 XML/SOAP 导出通道是否需合同/账号**本轮未确认**（不视为许可问题，属接入成本问题）。
- 结论：**AIPS = 🟡 可复用但本轮不接**；若以后要做「说明书链接层」，再单独评估（只链回原文、不转载正文）。

## 8 建议入库口径（下一写库窗口，本轮不实施）

1. `source` 行：`swissmedic_ogd`，`license='opendata.swiss terms_open (Open use)'`，`license_url='https://opendata.swiss/en/terms-of-use#terms_open'`，`source_url=数据集页`，`data_cutoff='2026-10-31'`。
2. 产品层：人用 `PRAEPARAT`（7,223）为 product；`PRAEPARATENAME` 进 `product_name`（不唯一，返回候选集）；`ZULASSUNGSNUMMER` / `ZULASSUNGSSTATUS` / `ATC_CODE` / `ARZNEIFORM` / `ABGABEKATEGORIE` / `ERSTZULASSUNGSDATUM` / `ABLAUFDATUM` 进对应列。
3. 序列/包装层：`SEQUENZ`（11,613）与 `PACKUNG`（18,351）→ 规格（`PACKUNGSGROESSE` + `PACKUNGSEINHEIT`）与包装码；同一制剂多序列/多包装**不合并**。
4. 成分层：`DEKLARATION`（`STOFFKATEGORIE=WIRKS`）→ `Stoff-Synonyme`（LN）取拉丁名；`MENGE` + `MENGEN_EINHEIT` 原样存，**不做单位换算**。
5. 码表：把 UDC 的 `DF` / `PACKAGE_UNIT` / `ROUTE_ADMIN` / `MA_STATUS` / `SUPL_CATEGORY` 落成本地多语词表（D/E/F/I），页面按语言取描述。
6. 不入库：说明书正文、适应症长文本（只做短事实）、兽用制剂、`IT_NUMMER` 等内部号。
7. ETL 需要单元测试的点：10 个 XML 的命名空间（`http://ccsap.bit.admin.ch/SWISSMEDIC/LIMS_HMIT_KHZ`）、四层 join 的键组合、拉丁名→INN 规则、状态与日期冲突处理、`PACKUNGSGROESSE` 为空（87 条）。
8. 页面署名 + 覆盖页写「数据截止 2026-10-31 / 每月更新 / Swissmedic + terms_open」；About 九语按 §2 的文字扩展（含法/意/德）。

## 9 成本与风险

| 项 | 评估 |
|---|---|
| 人时 | **8–10 人时**（10 个 XML、三层 join、多语码表、拉丁名映射、单元测试、覆盖页文案） |
| 体量 | ZIP 2.9 MB → 解压约 72 MB（`OGD-Deklarationen.XML` 55 MB 最大；只留小快照 + 许可说明到 `data/sources/`） |
| 风险 | **低-中**：许可清晰（唯一注意：署名是「建议」，本站仍署名）；风险在①商品名单语德语；②成分只有拉丁名；③「撤销条目」窗口很窄，文案不得写成历史库；④状态/日期有 7 条冲突 |
| 不可做 | 不转载说明书正文、不存价格（OGD 无价格）、不做剂量换算、不做替代推荐 |

## 10 证据清单（全部官方 URL；抓取日 2026-11-21 北京时间）

| # | URL | 用途 |
|---|---|---|
| 1 | <https://opendata.swiss/en/dataset/daten-von-human-und-tierarzneimitteln> | 数据集页（发布者 / 更新 / 字段说明 / 分发） |
| 2 | <https://opendata.swiss/api/3/action/package_show?id=daten-von-human-und-tierarzneimitteln> | CKAN 元数据（分发级 license/rights、isopen、联系人） |
| 3 | <https://opendata.swiss/en/dataset/daten-von-human-und-tierarzneimitteln.ttl> | DCAT-AP CH（`dct:license` / `dct:rights` = terms_open） |
| 4 | <https://opendata.swiss/en/terms-of-use#terms_open> | 条款原文（Open use，署名「建议」） |
| 5 | <http://dcat-ap.ch/vocabulary/licenses/terms_open> | 许可词表里的 terms_open 定义 |
| 6 | <https://ogd.swissmedic.cloud/ogd-arzneimittel/Daten/OGD.zip> | 本轮实测 HTTP 200 / **2,899,947 B** / sha256 `DF9D2C22…B9F73` |
| 7 | <https://ogd.swissmedic.cloud/ogd-arzneimittel/Beschreibungen/Beschreibungen_OGD_EN.pdf> | 官方字段说明（英；另有 DE/FR/IT 三份；**本轮未能解析 PDF 正文，只登记链接**） |
| 8 | <https://refdata.ch/de/nutzungsbestimmungen-aips-sai> | AIPS/SAI 使用条款（§5 允许复用与商用） |
| 9 | `https://opendata.swiss/api/3/action/package_search?fq=organization:swissmedic&rows=30` | 6 个 Swissmedic 数据集的 `isopen` / 许可模式对照 |
| 10 | <https://www.swissmedic.ch/>（robots.txt 404） | 抓取礼貌（OGD 主机未声明限制） |

## 11 复现命令（只读，不写库）

```powershell
$py  = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$tmp = Join-Path $env:TEMP 'data_scout_noch_20261121'; New-Item -ItemType Directory -Force $tmp | Out-Null
Invoke-WebRequest 'https://ogd.swissmedic.cloud/ogd-arzneimittel/Daten/OGD.zip' -OutFile (Join-Path $tmp 'OGD.zip') -UseBasicParsing
Get-FileHash (Join-Path $tmp 'OGD.zip') -Algorithm SHA256          # 应为本报告的 DF9D2C22…
& $py -c "import zipfile; z=zipfile.ZipFile(r'$tmp\OGD.zip'); print(len(z.namelist())); print(z.read('OGD-Export-Datum.XML')[:200])"
```

_本报告只做评估，不含任何写库、ingest、建站、测试或发布动作。_
