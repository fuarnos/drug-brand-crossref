# EMA 集中審批數據（EU 層）入庫準備

> 日期：2026-10-28 ｜ 任務：`task-97` ｜ 依據：`reports/pt-audit.md`、`data/raw/pt/ema_medicines_report_en.xlsx`
> 產物：`etl/ingest_ema_medicines.py`（dry-run / apply / rollback / --allow-real）、本報告、`.tmp/ema-ingest/` 證據
> 邊界：**未寫真實 DB**、未改 `site/build.py` / `data/markets.json` / schema；未跑 git / 發布。真實 DB 僅以 `mode=ro` 讀取映射。

## 0. 結論（先看這段）

1. **可做、且許可在線上路徑上是最乾淨的**：EMA 集中審批數據可按 EMA Legal notice 免費再發布（含商業用途），只需在每份內容署名 EMA。對比葡萄牙 INFARMED 國別數據（無開放許可、需書面授權且 `€150+IVA/年`），EMA 是**現在就能合法公開展示的 EU 層數據**。
2. **但 EU 不是一個國家市場**：資料是「EU 號碼（centralised procedure）→ 品牌名/成分/MAH/ATC/狀態」，必須以 **region=EU** 建模；`product.country` 對 EU 層應為 NULL。當前 schema 的 `country` CHECK 沒有 EU（也不應加），接入前需要一次 **region/market 層的 schema 遷移**（本任務不寫 DB/schema，只在 staging 原型驗證）。
3. **EU XLSX 沒有規格（strength）與劑型（pharmaceutical form）欄位**，名稱也只是品牌名；因此 EU 層只能做「品牌名 → 活性成分 / ATC / MAH / 授權狀態」對照，**不能做 D1 劑量對應**。頁面必須明示此口徑。
4. 副本驗證（human 子集）：**2,357 個 EU 藥品、2,782 個成分組件、成分映射 85.6%（2,381）**；覆蓋 1,141 個現有 substance；其中 1,566 個為 Authorised；ATC 覆蓋 94.4%、MAH 覆蓋 99.1%；DB 增量 **+1.11 MB**（staging 原型）。18/18 斷言 PASS，可重放/回滾。
5. **建議**：優先級 **P1**（不依賴 INFARMED 授權），先做 region schema + EU 層頁面（1–2 人日 ETL + 0.5–1 人日 schema/build）。EU 層標籤口徑：「歐盟集中審批（EMA）· EU 層，非國別產品；EMA 數據不含規格/劑型」。

## 1. 數據源與字段（已核實）

| 項 | 值 |
|---|---|
| 官方下載頁 | https://www.ema.europa.eu/en/medicines/download-medicine-data |
| 本次檔案 | `data/raw/pt/ema_medicines_report_en.xlsx`（904,715 B；下載於 2026-10-28） |
| 生成時間（檔內） | `Output automatically generated from content on www.ema.europa.eu on: 28/10/2026 - 18:05` |
| 結構 | 1 sheet「Medicine」；表頭在第 9 行（0-based 8）；**39 個有效欄位**；資料 **2,754 行** |
| 行口徑 | **1 行 = 1 個 EMA product number（EU 號）**；2,754 個 EU 號、2,702 個不同品牌名 |
| 類別 | Human **2,357** / Veterinary 397 |
| 狀態 | Authorised **1,875**（含獸藥；human 1,566）、Withdrawn 429、Application withdrawn 286、Refused 69、Opinion 32、Lapsed 29、Expired 19、Revoked 10、Suspended 2、Opinion under re-examination 1、Withdrawn from rolling review 2 |
| 字段覆蓋（全 2,754 行） | Name of medicine / EMA product number / Medicine status / First published / Medicine URL **100%**；Last updated 96.8%、Active substance 96.6%、INN/common name 96.1%、MAH（developer/applicant/holder 單列）87.3%、Therapeutic area 83.2%、ATC code (human) 80.8%、Marketing authorisation date 73.8% |
| **缺失欄位** | **無 strength、無 dosage form、無包裝、無國別**；名稱僅品牌名（2,754 行中僅 1 行名稱含類似規格字樣、13 行含劑型詞）→ 規格/劑型無法從此數據集得到 |
| 其他可用欄位 | European Commission decision date、Opinion adopted date、Withdrawal/expiry/revocation/lapse date、Suspension date、Revision number、Medicine URL（EMA 官方頁） |

## 2. 許可結論（可再發布）

EMA **Legal notice**（`https://www.ema.europa.eu/en/about-us/about-website/legal-notice`，2026-10-28 快照存 `data/raw/pt/ema_legal_notice.html`）原文：

> "Information and documents made available on EMA's webpages are public and may be reproduced and/or distributed, totally or in part, irrespective of the means and/or the formats used, for non-commercial and commercial purposes, provided that **EMA is always acknowledged as the source** of the material. Such acknowledgement must be included in each copy of the material. Citations may be made from such material without prior permission, provided the source is always acknowledged."

- ✅ **可公開再發布**（含商業用途），義務 = 每份內容署名 EMA 為來源；不需逐次申請、無費用。
- 建議 `source` 行：`source_id=ema_medicines`、`name=European Medicines Agency — Medicines data`、`license=© European Medicines Agency; re-use permitted with acknowledgement (EMA legal notice)`、`license_url=https://www.ema.europa.eu/en/about-us/about-website/legal-notice`、`data_as_of=2026-10-28`。
- 頁面署名建議（四語可放 About/EU 區塊）：「資料來源：European Medicines Agency (EMA) · Source: EMA · Fuente: EMA」。

### 與 INFARMED（葡萄牙國別數據）的區別

| 維度 | **EMA（本任務）** | **INFARMED INFOMED（pt-audit）** |
|---|---|---|
| 性質 | **EU 集中審批（centralised procedure）**，EU/EEA 層 | 葡萄牙**國別**上市藥品/包裝（含 MRP/DCP/國家程序） |
| 許可 | ✅ 免費再發布，署名 EMA（Legal notice） | 🔴 無開放許可、禁爬；需書面授權；Cedência 公共部門免費、其他機構 €150（+IVA）/年 |
| 量級 | 2,754 EU 號（1,875 Authorised；human 2,357） | 1,692 DCI / 10,446 藥品 / 12,646 包裝（INFOMED，2026-10-28） |
| 字段 | 品牌名/成分/MAH/ATC/狀態/日期/EMA 連結；**無規格/劑型/包裝** | 名稱/成分/劑型/規格/包裝/價格等（若授權取得） |
| 用途 | EU 層名稱↔成分、ATC、MAH、授權狀態 | 葡萄牙國別市場（真正的 PT 產品層） |

→ **兩者互補、不可替代**：EMA 可先上（合法且便宜），PT 國別層等 INFARMED 書面授權（見 pt-audit 申請路徑）；`dados.gov.pt` 無藥品註冊庫（不採用）。

## 3. 成分映射（對現有 `substance`）

human 子集（2,357 EU 藥品 / 2,782 成分組件）：

| 指標 | 值 |
|---|---|
| 成分組件 | 2,782（平均 1.18 個/藥品；複方由 ` / `、` + `、`;`、` and ` 切分；疫苗株內緊湊斜線不切） |
| 映射成功組件 | **2,381 / 2,782 = 85.6%** |
| 不同成分 token | 1,533；映射 **1,190（77.6%）** |
| 覆蓋現有 substance | **1,141 個** |
| 有 ≥1 映射成分的藥品 | 2,079 / 2,357（88.2%）；全部成分都映射 2,035（86.3%） |
| 無 active substance 欄位 | 47 行（2.0%） |
| 映射方法 | slug 2,173、salt-strip 85、salt-normalize 74、cleanup 40、inn 4、salt-normalize-inn 5、**unmapped 401** |
| 未映射 | 343 個不同 token；主要是**疫苗株/多糖結合物、生物製劑/基因治療**（Pneumococcal polysaccharide、Neisseria meningitidis conjugate、HPV L1 protein、feline calicivirus…）與少量拼寫差異（`acetylsalicylic acid`、`colecalciferol`、`human fibrinogen`、`Masitinib mesilate`） |
| 可改善 | ① 加拼寫/別名表（acetylsalicylic acid→acetylsalicylic-acid、colecalciferol→cholecalciferol）；② 生物製劑/疫苗不需映射到小分子 substance（可保留原文）；③ 新增 substance 需另任務（FDA/EMA 新藥） |

> 映射器：`slug()` → `substance.substance_id`；再 `_strip_salt_words()`（英式 besilate/mesilate、水合物、鹽）→ base；再 INN 正規化。接 production 後建議跑一次人工 alias 表補常見拼寫。

## 4. DB 副本驗證（只寫 staging 原型表）

命令（副本，真實庫未寫）：
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
copy data\drugs.db .tmp\ema-ingest\test.db
& $py etl/ingest_ema_medicines.py --dry-run
& $py etl/ingest_ema_medicines.py --apply --db .tmp\ema-ingest\test.db --category human
& $py etl/ingest_ema_medicines.py --rollback --db .tmp\ema-ingest\test.db
```
| 驗證項 | 結果 |
|---|---|
| staging 表 | `ema_medicine` 2,357 行（region='EU'、source_id='ema_medicines'、n_ingredients）<br>`ema_medicine_ingredient` 2,782 行（含 substance_id / mapping_method） |
| 映射 | 2,381/2,782（85.6%）；distinct substance 1,141 |
| 授權狀態 | human Authorised 1,566；其餘 withdrawn/refused 等如實保留原狀態 |
| 覆蓋 | ATC 2,224/2,357（94.4%）、MAH 2,335/2,357（99.1%） |
| DB 體積 | 351.39 → 352.50 MB（**+1.11 MB**；dbstat：ema_medicine 643 KB + ema_medicine_ingredient 184 KB + 索引） |
| 產能估算 | 正式表（product/name_key/name_variant/product_name/variant/product_component）加入約 **2.3k 產品、2.4k 名稱、2.8k 成分行**，預估 **+2～3 MB**（含索引） |
| 幂等 | 連跑 2 次 --apply：行數不變（2,357 / 2,782） |
| 回滾 | --rollback 刪除兩張 staging 表；重放恢復 |
| 完整性 | `integrity_check=ok`、`foreign_key_check` 無新增違規（歷史 `ingest_run→source` 問題與本任務無關） |
| 真實庫 | 無 `ema_*` 表、體積不變 351.39 MB（**未寫**） |
| 斷言 | **18/18 PASS**；日誌 `.tmp/ema-ingest/validation.log` |

## 5. EU 層模型與 build.py 接入建議（**不偽裝國別**）

### 5.1 schema（後續任務執行，不在本任務範圍）

- 推薦 **`product.region TEXT`（nullable）**：EU 層 `region='EU'`、`country=NULL`；`country CHECK` 不加 EU。查詢/`coverage` 視圖改成 `COALESCE(country, region)` 分組；API/頁面以 kind 區分 country vs region。
- 或新增 `market(code, kind, parent, name_key)` 表，EU 作 `kind='region'`（與 `data/markets.json` 的 region 概念一致），`product.market_code` 取代 country（遷移成本較高）。
- `source` 新增 `ema_medicines` 行（license/license_url/data_as_of 如 §2）；如 build.py 需要 EU 顯示名，四語放在 `data/i18n`/build 常量：`EU（EMA）` / `EU (EMA)` / `UE (EMA)` / `歐盟（EMA）`。
- `dose_warning`/collision 不需要 EU 國別參與；EU 只作「名稱/成分/AA」層。

### 5.2 build.py / 頁面口徑

1. **入口**：首頁國家下拉**不加 EU**；在覆蓋頁/A4 層加「EU · EMA 集中審批」分組（region badge），或在 About 覆蓋表加一行；搜尋結果可選「EU 區域」視圖（U2 各國叫法橫排不把 EU 當國家，或獨立 region chip，需產品設計確認）。
2. **頁面文案**（四語）：「EU 集中審批（EMA）——歐盟層面授權，非某一國家的產品；EMA 數據不含規格/劑型/包裝。」
3. **展示字段**：品牌名、活性成分（映射到 substance 的可點成分頁）、ATC、MAH（注意 EMA 單列混合 developer/applicant/holder，顯示時標「持有人/申請人（EMA 欄位）」）、授權狀態（Authorised 綠色 / Withdrawn 等灰）、EMA 連結、EU 號。
4. **不展示/不承諾**：規格、劑型、包裝、價格、國別可得性；不做 D1/D2 折算（EU 層無 strength）。
5. **搜尋索引**：EU 名稱加入 `name_key`/`name_variant`（source=ema_medicines），index entry 的 `c` 現在放國家 code；EU 需新字段 `rg='EU'`，或暫時 `c` 加 'EU'（不推薦，會混入國家 chips）。建議 index 增加 `rg` 字段、build 端 chip 過濾 country vs region。
6. **頁數/體積**：新增 ~2,357 個 name 頁（若給 brand 頁）或僅在成分頁/覆蓋頁列 EU 名稱（**建議先只做成分頁 EU 區塊 + 覆蓋頁，不新增 2,357 頁**），sitemap +0～2,357。
7. **更新頻率**：EMA 下載頁為「按需生成」的 XLSX（本次生成時間 2026-10-28 18:05）；建議 ETL 每月抓一次、`data_as_of` 記錄生成時間；無 API。

### 5.3 接入優先級

- **P1（可立即）**：region schema 遷移 + EMA ETL（本腳本 staging 邏輯升為正式表）+ 成分頁 EU 區塊 + 覆蓋頁 EU 行 + About 署名。工作量約 1.5–2.5 人日；不依賴 INFARMED。
- **P2（等授權）**：INFARMED 國別數據（pt-audit 已備申請信/授權路徑）→ PT 市場層；EU 層不必等。

## 6. 風險與缺口

1. **無規格/劑型**：EU 層不能做劑量對應；如日後要做，需從 EPAR/產品頁（Medicine URL）逐條解析 PDF/HTML（成本高、非本輪）。
2. **映射 85.6%**：401 個未映射成分主要是疫苗/生物製劑/基因治療（本站 substance 為小分子 INN 為主）+ 拼寫差異；頁面需允許「成分原文不可點」。
3. **品牌名重名**：2,754 EU 號 / 2,702 個不同名 → 少量同名不同 EU 號（無規格區分），頁面必須顯示 EU 號 + MAH 區分。
4. **狀態語義**：Authorised 只代表「集中審批有效」，不等於各國實際在售；EU 層頁面須寫明。
5. **schema 遷移**：country/region 是全局口徑變更，需同步 `coverage` 視圖、`db/init_db.py`、索引、About 覆蓋數字；建議單獨 task、先在副本驗證。
6. **EMA 數據更新**：XLSX 為按需生成、無固定 API/版本號；建議記錄 `generated_at` 與檔案 sha256（ETL 應做變更檢測）。
7. **獸藥**：本 ETL 默認 `--category human`；獸藥 397 行不進本站（如未來要，加 category 過濾與頁面標記）。

## 7. 證據

- `.tmp/ema-ingest/probe.json`（XLSX 字段覆蓋/行數/狀態/名稱模式）
- `.tmp/ema-ingest/stats.json`（human dry-run：映射率/方法/未映射 top）
- `.tmp/ema-ingest/validation.json` + `validation.log`（副本 apply/幂等/回滾/體積/integrity，18/18 PASS）
- `.tmp/ema-ingest/ema_preview.csv`（2,357 行預覽：EU 號/品牌/成分/映射/MAH/ATC/URL）
- `data/raw/pt/ema_legal_notice.html`、`ema_download_medicine_data.html`、`ema_medicines_report_en.xlsx`
- 腳本：`etl/ingest_ema_medicines.py`（--dry-run/--apply/--rollback/--allow-real；staging 原型）

_本報告為入庫準備：未寫 `data/drugs.db`、未改 `site/build.py`、未跑 git/發布；正式接入需另開 schema/region 任務。_
