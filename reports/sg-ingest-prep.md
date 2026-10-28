# 新加坡（SG）HSA 名冊入庫準備（副本驗證）

> 日期：2026-10-28 ｜ 任務：`task-104` ｜ 依據：`reports/sg-audit.md`、`data/raw/sg/hsa_registered_therapeutic_products.json`
> 產物：`etl/ingest_sg_hsa.py`、`db/migrate_country_sg.py`、本報告、`.tmp/sg-ingest/`（統計/驗證日誌）
> 邊界：**真實 DB 未寫**、未改 `site/build.py` / `data/markets.json`；未 git/發布。真實庫僅 `mode=ro` 讀取映射。

## 0. 結論（先看這段）

1. **可以接入，且是成本最低的英語市場**：data.gov.sg / HSA 名冊 5,511 條、12 欄，含**規格（Strength）**、劑型、ATC、MAH，SODL 可再發布（署名 + 鏈許可）。與 HK（無規格）相比，SG 可直接支撐「名稱 → 成分 + 規格 + 劑型」層。
2. **解析與映射已達標**：複方 `&&` 拆分 + EQV 註釋清理 + BAN/英式拼寫別名 + 無 `&&` 複方最長匹配；**成分映射 7,080/7,474 = 94.7%**，全成分匹配產品 **95.4%**（高於 70–85% 目標，因復用 DB `alias_all` + BAN 表 + longest-match）。
3. **副本驗證 23/23 PASS**：加 SG 遷移保留 426,044 行；寫入 SG 產品 5,511 / 成分 7,080 / 名稱 5,511；strength 解析 90.1% 組件（100% 產品至少一組規格）；冪等、回滾、重放、`integrity_check=ok`；真實庫未動。
4. **真實 apply 前還差兩件事**（不在本任務寫範圍）：① `db/schema.sql` / `db/init_db.py` 需加 SG（當前 live DB 的 product 表比 schema.sql 舊：無 `region`、無 HK，所以本任務用 `db/migrate_country_sg.py` 直接在副本加 SG；正式接入建議先讓 init_db 重建到最新 schema 再加 SG）；② 遷移重建 product 表會令 DB 檔案 +135 MB（freelist），**遷移後跑 `VACUUM` 回收**。
5. **建議**：**P1 接入 SG**（ETL + 頁面約 2–3 人日，英文市場不需新語言）；頁面口徑「新加坡註冊名冊（HSA）· 在冊名單，不代表在售」；品牌名不翻譯、中文成分經 `inn_zh`。

## 1. 數據源與許可

| 項 | 值 |
|---|---|
| 數據集 | data.gov.sg — **Listing of Registered Therapeutic Products**（HSA 管理），datasetId `d_767279312753558cbf19d48344577084` |
| 數據集頁 | https://data.gov.sg/datasets/d_767279312753558cbf19d48344577084/view |
| 快照 | `data/raw/sg/hsa_registered_therapeutic_products.json`（舊版 datastore API 全量 5,511 條；total=5,511） |
| 行數/欄位 | 5,511 行 × 12 欄（+`_id`）：LicenceNo / Productname / Licenseholder / Approvaldate / Forensicclassification / ATCCode / Dosageform / RouteofAdministration / Manufacturer / Countryofmanufacturer / Activeingredients / Strength |
| 更新 | **每 6 個月**；本次 data.gov.sg 顯示 last updated **2026-08-07**；ETL 應記錄 `data_as_of=2026-08-07` |
| 許可 | **Singapore Open Data Licence v1.0（SODL）**：可商用/非商用使用、複製、分發、改編，須**署名 + 鏈許可頁**，不得暗示政府背書 |
| 署名（頁面 About/覆蓋頁用） | `Contains information from Listing of Registered Therapeutic Products accessed on 2026-10-28 from Health Sciences Authority (HSA) / data.gov.sg, made available under the Singapore Open Data Licence v1.0.` |

> 注：HSA PRISM / InfoSearch / PI 說明書庫**不在**本數據集許可內（HSA Terms 要求書面許可），只做鏈接層，不批量再發布（見 sg-audit §4）。

## 2. 字段映射（source → 現有 schema）

| HSA 欄位 | 入庫去向 | 說明 |
|---|---|---|
| LicenceNo | `product.product_id = 'SG-' + LicenceNo`；`approval_id` | 5,511 個唯一註冊號，天然主鍵 |
| Productname | `name_key` / `name_variant` / `product_name(name_type='trade')` | 保留原文（英文，可能含規格文本）；品牌名不翻譯 |
| Licenseholder | `product.mah` | 100% 覆蓋 |
| Approvaldate | `product.note`（原文） | 混合格式（`5/4/1988` 等），**不解析為日期**，頁面顯示原文 |
| Forensicclassification | `product.category`：Prescription Only→`POM`、Pharmacy Only→`P`、General Sale List→`GSL` | 處方分類，不是註冊狀態 |
| ATCCode | `product.note`（`atc=...`）+ 統計 | **當前 schema/product 無 ATC 列、live DB 無 atc 表**；先寫 note（99.5% 行有值），日後 ATC 接入任務再規整化 |
| Dosageform | `product.dosage_form`（原文）、`form_base`（`form_base_of`）、`release`（`release_of`） | 89 種劑型；100% 有值 |
| RouteofAdministration | `product.route`（小寫） | 85 種途徑 |
| Manufacturer / Countryofmanufacturer | `product.note` | 不建廠家表 |
| Activeingredients | `product_component`（經 mapping） | `&&` 複方；見 §3 |
| Strength | `product_component.strength_value/unit`、`per_volume_value/unit` | `&&` 對齊成分；複方按位置配對；179 行數量不齊時只配前 N 個（記錄 partial） |
| （無狀態欄位） | `status='active'` | **在冊名單 ≠ 在售**；頁面必須明示；不虛構 discontinued/withdrawn |

其他：`country='SG'`、`region=NULL`（國家市場）；`source_id='hsa_sg'`；`source_url=數據集頁`；`retrieved_at=2026-10-28`；`is_branded=1`；`pack=NULL`（無包裝欄位）。

## 3. 解析規則（ETL 核心）

1. **複方拆分**：`Activeingredients` 按 `&&` 切；無 `&&` 的複方（如 `SULPHAMETHOXAZOLE TRIMETHOPRIM`）用**最長匹配**在 DB substance/alias 詞表上貪心切分。
2. **EQV/AS 註釋**：先取 EQV/AS 前的標稱成分（`LINCOMYCIN HCl EQV LINCOMYCIN` → `LINCOMYCIN HCl`），保留鹽型。
3. **BAN/英式拼寫**：`PARACETAMOL→acetaminophen`、`FRUSEMIDE→furosemide`、`LIGNOCAINE→lidocaine`、`MESALAZINE→mesalamine`、`GUAIPHENESIN→guaifenesin`、`AMOXYCILLIN→amoxicillin`、`ALUMINIUM→aluminum`、`sulph→sulf`、`oest→est`、`haem→hem` 等（僅在目標 substance 存在時啟用）。
4. **鹽型**：`split_salt` + 尾部鹽/水合物詞逐層剝離；有鹽時 variant_id = `{substance}-{salt slug}`，無鹽時用 base variant（若不存在則創建，避免 FK 失敗）。
5. **強度**：`&&` 按成分順序對齊；`mg/1.8 g` 拆成 value+unit 與 per_volume；`5% w/v` 存 `%`；解析失敗留 NULL（不猜）。
6. **名稱**：`normalize()` 生成 key（latin script）；Productname 保留原文（含規格文本）；不做機器翻譯。

## 4. 映射率（dry-run，`--category` 未設，全量 5,511）

| 指標 | 值 |
|---|---|
| 產品 | 5,511 |
| 成分組件（含未映射） | 7,474 |
| **成分映射成功** | **7,080（94.7%）** |
| **全成分匹配產品** | **5,256（95.4%）**；至少一個映射 98.8% |
| 未映射 | 394 組件 / 234 種 token（5.3%），主要是疫苗株/多糖結合物/生物製劑詞組片段（`Protein`、`Conjugate of`、`Pneumococcal polysaccharide serotype…`、`mRNA` 等）+ 少數拼寫 |
| distinct substances | 1,542；variants（含鹽型）1,672 |
| 規格 | 5,332 行按序完全對齊 + 179 行部分；**6,379/7,080 = 90.1% 組件有規格值**；100% 產品至少一組規格 |
| 覆蓋 | ATC 99.5%、劑型 100%、MAH 100% |

> 任務目標 70–85% 屬「補別名表後可達」的下限估算；本實現因復用 DB `alias_all`（1,081 別名）+ BAN 表 + longest-match，實際 94.7%。剩餘 5.3% 多為疫苗/生物製劑（本站 substance 以小分子 INN 為主），不建議硬映射。

## 5. DB 副本驗證（23/23 PASS）

命令（全部只寫副本）：
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
copy data\drugs.db .tmp\sg-ingest\test.db
& $py db/migrate_country_sg.py --db .tmp\sg-ingest\test.db --dry-run
& $py db/migrate_country_sg.py --db .tmp\sg-ingest\test.db
& $py etl/ingest_sg_hsa.py --dry-run
& $py etl/ingest_sg_hsa.py --apply --db .tmp\sg-ingest\test.db
& $py etl/ingest_sg_hsa.py --rollback --db .tmp\sg-ingest\test.db
```

| 驗證項 | 結果 |
|---|---|
| 遷移 | product **426,044 → 426,044 行**；country CHECK 加入 `'SG'`；region 列若不存在自動適配；索引重建；`integrity=ok`、FK 違規 0 |
| 寫入 | SG 產品 **5,511**、成分 **7,080**（全部有 variant FK）、名稱 **5,511**、variants 1,672 |
| 映射 | 組件 100% 有 variant（未映射的不寫 component）；產品全匹配 95.4% |
| 規格 | 6,379/7,080 = 90.1% 組件有 strength；100% 產品至少一組 |
| 幂等 | 連跑 2 次 apply：5,511 / 7,080 不變 |
| 回滾 | SG 產品=0；product 回到 426,044；source 行清除；重放恢復 5,511 |
| 完整性 | `integrity_check=ok`、`foreign_key_check` 無新增違規 |
| DB 體積 | 基線 351.39 MB → 遷移後 486.46 MB（**+135.07 MB，freelist 32,680 頁 ≈134 MB**）；apply 本身 Δ0（复用 freelist）→ **遷移後 VACUUM 可回收約 134 MB**（預計回到 ~353 MB） |
| 真實庫 | country CHECK 未改、無 SG 產品（**未寫**） |
| 日誌 | `.tmp/sg-ingest/validation.log` / `validation.json` / `stats.json` / `sg_preview.csv` |

## 6. 真實 apply 步驟（待批准；本任務未執行）

1. **備份**：`copy data\drugs.db data\backups\drugs-before-sg-20261028.db`（或跑 `run_all.py` 會自動備份）。
2. **schema 同步（建議一起做）**：`db/schema.sql` 的 country CHECK 加 `'SG'`，並在 `db/init_db.py` 的產品表重建遷移裡保留它；若暫不改 schema，可直接 `& $py db/migrate_country_sg.py --allow-real`（會改真實庫結構，需批准）。
3. **VACUUM**：`& $py -c "import sqlite3;db=sqlite3.connect('data/drugs.db');db.execute('VACUUM');db.close()"`（或 `run_all.py --no-ingest` 流程中重建）——回收遷移造成的 ~134 MB。
4. **入庫**：`& $py etl/ingest_sg_hsa.py --apply --allow-real`。
5. **核對**：SG 產品 5,511、component 7,080、`db/check_data.py` 通過、`collision`/搜尋三語回歸（英文資料，抽 CHLORAMPHENICOL EAR DROPS、INON GRANULES 複方、GLUCOPHAGE 等）。
6. **同步計數/文案**：README / About / coverage / CHANGELOG 的國家數與產品數（build 任務執行）；`data/markets.json` 加 SG（enabled 由註冊/發佈任務決定）；build.py 國家下拉/chips/U2 加 SG。
7. 頁面口徑（build 任務）：SG→English market，不新增語言；品牌名保留英文；成分中文走 `inn_zh`；標「在冊名單，不代表在售」；About 加 SODL 署名。

## 7. 風險與缺口

1. **DB 版本漂移**：live DB 的 product 表**沒有 `region` 列、沒有 HK**（`db/schema.sql` 已領先），本任務的 migration 以「實際 DB 的 DDL」為準只加 SG；正式接入前建議先 `db/init_db.py` 重建到最新 schema，再跑 SG 遷移（腳本已對「無 region」自動適配）。
2. **檔案體積**：重建 product 表使 DB +135 MB（freelist），**必須 VACUUM**；VACUUM 需要臨時磁碟空間（約等於 DB 大小）。
3. **未映射 5.3%**：疫苗/生物製劑詞組被 longest-match 切成碎片（`Protein`/`Conjugate of`…），只影響未映射統計美觀，不影響已映射 94.7%。
4. **無註冊狀態/包裝**：`status='active'` 是在冊假設，頁面必須寫明；無 pack。
5. **ATC 無處落庫**：當前 schema 無 product-level ATC 列；已存入 note，待 ATC 任務規整。
6. **批准日期不解析**：混合格式只存原文，避免時區/格式誤判。
7. **重名**：5,511 行中 Productname 去重 5,501（10 個同名不同 LicenceNo）→ 頁面以註冊號/MAH 區分。

## 8. 證據

- `.tmp/sg-ingest/probe.json`（映射基線/註釋樣本）
- `.tmp/sg-ingest/stats.json`（dry-run：94.7%/95.4%/規格 90.1%/ATC 99.5%）
- `.tmp/sg-ingest/validation.json` + `validation.log`（23/23 PASS、體積、幂等、回滾）
- `.tmp/sg-ingest/sg_preview.csv`（5,511 行預覽）
- `data/raw/sg/hsa_registered_therapeutic_products.json`（5,511 條全量）、`datagov_dataset_page.html`、`datagov_open_data_licence.html`
- 腳本：`etl/ingest_sg_hsa.py`（--dry-run/--apply/--rollback/--allow-real）、`db/migrate_country_sg.py`

_本報告為入庫準備：未寫 `data/drugs.db`、未改 `site/build.py` / `data/markets.json`、未跑 git/發布；真實 apply 待批准。_
