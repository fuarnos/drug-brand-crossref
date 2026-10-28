# 澳門數據申請材料：聯絡方式、流程與申請信（可直接發送）

> 日期：2026-10-28 ｜ 任務：`task-89` ｜ 背景：`reports/hk-mo-audit.md`（MO 無公開批量文件、無公開再發布許可）
> 使用者決定：**若申請不收費，本人願意親自申請**。本文件把「查誰、怎麼問、問什麼、怎麼寫」整理成可直接使用的材料。
> 邊界：只讀調研 + 報告；未寫 `data/drugs.db`、未改 `site/build.py`、未跑 git / 發布。
> 隱私：**公開倉庫版保留 `【姓名】【電郵】` 等佔位符**（不寫真實姓名/郵箱）；已填好、可直接發送的版本在本地 `.tmp/mo-request/application-filled.md`（`.tmp/` 已 gitignore，不進倉庫）。

## 0. 結論（先看這段）

1. **對口單位**：藥物監督管理局（ISAF，Instituto para a Supervisão e Administração Farmacêutica）**註冊廳**（藥品註冊職能）；gov.mo 服務頁列出的執行單位是「註冊廳－化藥生物藥及醫療器械處」。
2. **受理方式**：官方沒有「數據申請」專用表格 → 以**書面申請（電郵／親臨／郵寄）**為主，先電話確認受理單位與費用，再發正式信。
3. **是否收費**：**官方網站未找到「名錄數據」的收費條款**；歷史上（2014/2020）衛生局《澳門特區藥物名錄》以光碟/索取制**免費**提供予藥業與專業人士（2020 新聞原文「aceder ao conteúdo de forma gratuita」）。**本次信中明確詢問是否收費與公益豁免；若回覆要收費，依使用者意願停止申請**。正式答覆為準。
4. **要什麼**：現行已註冊藥物名錄的**機器可讀導出（CSV/Excel，最好 API）**+ **可再發布許可**（公益非商業網站、事實字段、署名 ISAF、鏈回官網）；欄位見 §3。
5. **若只給光碟/紙本**：接受，但同時請求「以事實字段在公開非商業網站展示」的書面許可；若連許可也不給 → 退回**鏈接層**（保留 ISAF 查詢頁入口），不強求。

## 1. 官方聯絡方式（已核實，附 URL）

| 用途 | 單位 | 地址 / 電話 / 傳真 / 電郵 |
|---|---|---|
| **藥品名錄／註冊資料（首選）** | ISAF **註冊廳** | 澳門何賢紳士大馬路政府（青茂）辦公大樓 19 樓；電話 **(853) 8598 3263**（產品分類查詢 **8598 3281**）；傳真 2883 1905；電郵 **dreg@isaf.gov.mo** |
| 藥品註冊（gov.mo 服務頁列的執行單位） | 註冊廳－**化藥生物藥及醫療器械處** | 同上地址；電話 **(853) 2883 1906**；傳真 2852 4016；電郵 **dmqbdm@isaf.gov.mo**（服務頁另列 info@isaf.gov.mo）；最後更新 2026-06-26 |
| 總局／總機 | ISAF | 澳門何賢紳士大馬路政府（青茂）辦公大樓 19 樓；電話 **(853) 2852 4708**；傳真 2883 1919；電郵 **info@isaf.gov.mo** |
| 中藥／天然藥物 | 註冊廳－中藥處 | dmtc@isaf.gov.mo；2883 1908 |
| 查詢／投訴／異議（線上表單，可作書面申請備用渠道） | ISAF | https://www.isaf.gov.mo/cn/contact/complaints（45 日內回覆；亦可電話 8598 3522） |
| 官方查詢入口（公開資料查詢） | ISAF 資料查詢 | https://www.isaf.gov.mo/cn/services/query ；「澳門特區藥品」子頁： https://www.isaf.gov.mo/services/query/澳門特區藥品 |

來源 URL：
- ISAF 地址及電話：https://www.isaf.gov.mo/cn/contact/address （核實時間 2026-10-28）
- gov.mo 服務頁（查詢途徑，2026-06-26 更新）：https://www.gov.mo/zh-hant/services/ps-1568/
- gov.mo FAQ「如何查閱已登記藥物資料」：https://www.gov.mo/zh-hant/services/ps-1568/faqs/ （答：資料已上載至 ISAF 網站，市民可查閱）
- ISAF 資料查詢（藥品資料）：https://www.isaf.gov.mo/services/query/澳門特區藥品
- 2020 年《澳門特區藥物名錄》免費索取公告（葡文）：https://www.gov.mo/pt/noticias/244998/ （原文：「aceder ao conteúdo de forma gratuita」；名錄含商品名、劑型、治療分類、給藥途徑、活性成分及含量）

> 備註：2014/2020 名錄由衛生局（SSM）藥物事務廳發放；2022 年起藥物註冊職能歸 ISAF。現行名錄/數據的提交方式需向 ISAF 確認；上表以 ISAF 官方頁面為準。

## 2. 建議申請流程（不花錢路線）

1. **先電話確認（10 分鐘）**：致電註冊廳 **8598 3263** 或化藥生物藥及醫療器械處 **2883 1906**，說明：非商業公益網站、想索取「現行註冊藥物名錄」機器可讀數據 + 再發布許可，問三件事：①受理單位/收件人；②是否收費（是否有行政費/數據費）；③可提供什麼格式（CSV/Excel/API/光碟）。
2. **發正式書面申請**（同日或次日）：按 §4 範本，電郵至 **dreg@isaf.gov.mo**，副本 **dmqbdm@isaf.gov.mo**、**info@isaf.gov.mo**；主旨固定，便於追蹤。附件可加一頁「資料字段清單」（§3）與網站 About 頁截圖/連結。
3. **親臨/郵寄（可選）**：地址見 §1；建議先電話預約並帶身份證明文件；可當面遞交並索取收件回執。
4. **跟進**：7 個工作天無回覆 → 電話跟進；14 個工作天再無書面回覆 → 用 §6 跟進信；全程保留電郵與回執（供更新 `docs/许可清单.md` 用）。
5. **結果分流**：
   - 免費 + 給數據 + 給再發布許可 → 立項 ETL（見 hk-mo-audit §2），HK/MO 一起排 v0.7。
   - 免費但只給光碟/紙本 + 許可 → 用 CSV/Excel 落庫，頁面標「來源：ISAF、更新日期」。
   - 免費但**不給再發布許可** → 只做鏈接層（ISAF 查詢入口），不複製數據。
   - **要收費** → 依使用者意願**停止**（回覆對方致謝即可）。

## 3. 要向官方索取的數據（寫進信裡的清單）

**範圍**：澳門現行已註冊藥物（西藥；如可，另附中成藥/天然藥物分表）；含註冊狀態（有效/失效/取消）。若只能給「現行有效」也可接受，請註明。

| # | 欄位 | 說明/用途 |
|---|---|---|
| 1 | 註冊編號 | 主鍵（如 MAC-xxxxx） |
| 2 | 商品名（中文／葡文／英文） | 品牌名，跨語言對照核心 |
| 3 | 通用名／活性成分（含鹽型） | 對齊本站 substance INN |
| 4 | 含量／規格（value + unit） | 劑量對照前提；如按鹼基/鹽計請註明基準 |
| 5 | 劑型（dosage form） | 片劑/膠囊/注射液… |
| 6 | 給藥途徑（route） | 口服/注射/外用… |
| 7 | 註冊持有人／持牌公司（MAH） | 廠家頁與身份核對 |
| 8 | 註冊狀態 + 首次批准日期 / 續期日期 | 狀態與新鮮度 |
| 9 | 包裝規格（pack） | 包裝對照（可選） |
| 10 | ATC 碼／治療分類（如有） | 類別檢索（可選） |

**格式**：CSV（UTF-8）或 Excel 為首選；如可行 JSON 或 API 更好；請附**欄位說明/數據字典**與**編碼**。**更新頻率**：希望每月或每季，並提供「資料截止日期」；交付方式：電郵附件或下載連結。

## 4. 申請信（繁體中文 · 可直接複製發送）

> 使用前替換：【姓名】【聯絡電話】【電郵】【網站網址】【日期】。若電話確認到具體收件人，把「敬啟者」改為「[姓名] 先生/女士 台鑒」。
> **已填好的本地版**：`.tmp/mo-request/application-filled.md`（姓名/電郵/網站/日期已填，直接複製即可；不在公開倉庫）。
> 同一身份也用於未來 HK 數據確認、NMPA 說明等申請場景（統一指引見本地 `.tmp/mo-request/identity-for-applications.md`）。

```text
主旨：申請提供「澳門特區藥品名錄」機器可讀數據及公開再發布許可（非商業公益用途）

敬啟者：

本人【姓名】，聯絡電話【聯絡電話】，電郵【電郵】，現正營運一個非商業、無廣告的公益參考網站【網站網址】，用於把藥品商品名對應到活性成分，並比較同一成分在不同國家/地區的名稱與規格。網站只展示事實字段（成分、劑型、規格、註冊信息等），不提供用藥建議、不做劑量換算建議、不售賣任何商品或數據。

為把澳門納入上述對照，現依據貴局公開資料及政府服務資訊，謹申請如下：

一、請求提供的數據
「澳門特別行政區現行已註冊藥物名錄」的機器可讀導出（CSV／Excel，如可行 JSON/API），範圍與欄位包括：
1. 註冊編號；
2. 商品名（中文／葡文／英文）；
3. 通用名／活性成分（含鹽型）；
4. 含量／規格（並請註明強度按鹼基或鹽計的基準，如適用）；
5. 劑型；6. 給藥途徑；
7. 註冊持有人／持牌公司；
8. 註冊狀態、首次批准日期、續期日期；
9. 包裝規格；10. ATC 碼／治療分類（如有）。
如部分欄位不便提供，懇請提供其餘可用欄位；並請附欄位說明（數據字典）。

二、請求再發布許可
懇請書面確認：本人可在上述非商業公益網站，以事實字段形式展示上述數據（例如商品名、成分、劑型、規格、註冊編號、持有人、狀態），並：
1. 在網站及每個相關頁面註明「資料來源：澳門特別行政區政府藥物監督管理局（ISAF）」並鏈回貴局官方網站；
2. 不轉售、不再授權第三方、不轉載說明書或任何全文內容；
3. 如貴局要求特定署名格式或免責聲明，本人願意照辦；
4. 如貴局有標準許可條款（例如 CC BY 4.0 或政府指定條款），懇請提供文本，本人願意遵守。

三、費用
本人屬非商業公益項目，沒有商業收入。懇請告知上述申請**是否收取任何費用**（包括行政費、數據費或工本費）；如收費，請先提供報價及收費依據，本人會在收費前暫停申請；如可豁免，萬分感謝。

四、格式與更新
如蒙提供，懇請以 CSV（UTF-8）或 Excel 交付（電郵附件或下載連結均可），並告知更新頻率與資料截止日期（希望每月或每季更新，如不可行，年度亦可）。

五、個人資料
本人僅提供上述聯絡方式作申請及跟進之用，不會公開。

懇請於 14 個工作天內書面回覆（電郵即可）。如需補充資料或改用貴局指定表格，請隨時通知，本人樂意配合。感謝貴局對公共健康資訊的支持。

祝 工作順利

【姓名】
【聯絡電話】｜【電郵】
【網站網址】
【日期】
```

## 5. 葡文版（可選 · 短信版本）

```text
Assunto: Pedido de dados legíveis por máquina da «Lista de Medicamentos Registados na RAEM» e autorização de republicação (fins não comerciais)

Exmos. Senhores,

Sou 【nome】, contacto 【telefone】 / 【email】. Disponibilizo um sítio informativo sem fins comerciais 【URL】 que associa nomes comerciais de medicamentos aos respetivos princípios ativos e compara denominações entre países/regiões, apenas com dados factuais e sem aconselhamento terapêutico.

Venho solicitar: (1) a lista dos medicamentos atualmente registados na RAEM em formato legível por máquina (CSV/Excel ou JSON/API), com os campos: número de registo, nome comercial (chinês/português/inglês), substância ativa (incluindo forma salina), dosagem/apresentação, forma farmacêutica, via de administração, titular do registo, estado e datas de registo, embalagem e código ATC (se disponível); (2) autorização escrita para publicar esses dados factuais no referido sítio não comercial, com a menção «Fonte: Instituto para a Supervisão e Administração Farmacêutica (ISAF)» e ligação ao sítio oficial, sem revenda nem reprodução integral de textos.

Agradeço que me informem se o pedido está sujeito a taxas; caso afirmativo, solicito orçamento antes de prosseguir. Pretendo uma resposta por escrito no prazo de 14 dias úteis.

Com os melhores cumprimentos,
【nome】｜【telefone】｜【email】｜【data】
```

## 6. 英文版（可選 · 短信版本）

```text
Subject: Request for machine-readable "Registered Pharmaceutical Products of Macao" data and permission to republish (non-commercial public-interest use)

Dear Sir/Madam,

I am 【name】 (tel 【phone】, email 【email】), operating a non-commercial, ad-free public reference site 【URL】 that maps medicine brand names to active ingredients and compares local names across countries/regions. We publish factual fields only and give no medical advice.

I request: (1) the current list of registered medicinal products in Macao in a machine-readable format (CSV/Excel, ideally JSON/API), with fields: registration number, product name (Chinese/Portuguese/English), active ingredient (including salt form), strength, dosage form, route, registration holder, status and registration/renewal dates, pack, ATC (if available); (2) written permission to display these factual fields on the non-commercial site, with the attribution "Source: Pharmaceutical Supervision and Administration Bureau (ISAF), Macao SAR" and a link to the official website, without resale or full-text reproduction.

Please confirm whether any fee applies; if so, kindly provide a quotation before I proceed. I would appreciate a written reply within 14 working days.

Yours faithfully,
【name】｜【phone】｜【email】｜【date】
```

## 7. 跟進信（14 個工作天後 · 可選）

```text
主旨：跟進—申請提供「澳門特區藥品名錄」數據及再發布許可（【日期】已提交）

敬啟者：

本人於【原申請日期】電郵申請上述數據及許可（見下方原文），至今未收到回覆。為免遺漏，現禮貌跟進，並可提供任何補充資料或按貴局指定格式重新提交。如申請需轉介其他部門，懇請告知聯絡單位。謝謝。

【姓名】【電話】【電郵】
——（附上原申請全文）——
```

## 8. 後續與回退

| 官方回覆 | 動作 |
|---|---|
| 免費 + 給數據 + 給許可 | 更新 `docs/许可清单.md`（MO 行：可再發布/署名 ISAF）、`source` 表新增 `isaf_mo`、ETL 立項（CSV/Excel → product/variant/component，`country=MO` schema 遷移）、頁面標「資料截止日」 |
| 免費 + 只給光碟/紙本 + 許可 | 同上，先人工/OCR 轉 CSV（一次性），再按季度索取更新 |
| 免費 + 不給再發布許可 | 只做鏈接層：About/覆蓋頁放 ISAF 資料查詢入口 + 「官方名錄為索取制」說明 |
| 要收費 | 依使用者意願**停止**，回覆致謝；本站維持鏈接層 |
| 只給公開查詢頁（無批量） | 維持鏈接層；不爬取（避免違反站點條款/反爬） |

## 9. 未核實事項（以官方書面回覆為準）

- 現行是否仍發放《澳門特區藥物名錄》光碟/紙本、是否收費（2014/2020 公告為免費索取，現行安排未在官網明示）。
- 是否已有「機器可讀/API」形式；ISAF 網站「資料查詢」為動態頁面，未發現公開 API。
- 再發布許可條件（署名格式、是否要求許可證/協議）。
- 受理單位是否為註冊廳或需轉規劃及質量管理廳（pqm@isaf.gov.mo）。

## 10. 證據與文件

- **本地已填好、可直接發送的申請信**：`.tmp/mo-request/application-filled.md`（繁中主信 + 葡文/英文短版 + 寄件 checklist；含真實姓名/電郵，**不進公開倉庫**）
- **統一申請身份/User-Agent 指引**：`.tmp/mo-request/identity-for-applications.md`（本地私有；公開倉庫只用佔位符）
- 聯絡方式與服務頁存檔：`.tmp/mo-request/isaf_procedures.txt`、`isaf_download.txt`、`isaf_roles.txt`、`isaf_contact_pt.html`、`govmo_ps1568.html`、`govmo_ps1568_faq.html`、`ps1568_query_route.txt`
- 2020 名錄公告（已存 HTML）：`.tmp/mo-request/`；PDF 直連被 WAF 403（僅引用 gov.mo 新聞頁）
- HK/MO 來源審計：`reports/hk-mo-audit.md`

_本文件為申請材料與流程調研，未寫入任何資料庫；發送前請替換【】佔位符，並保留官方回覆作許可依據。_
