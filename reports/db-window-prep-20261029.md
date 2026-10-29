# DB 窗口只读准备（task-133 / task-3）— HK + CN v2 五项 + 单位归一

> 日期：2026-10-29 07:40–08:20（北京时间）｜**只读**：未写 `data/drugs.db`、未跑任何 ingest apply、未跑 `site/build.py`、未 git/发布
> 依据：`AGENTS.md` §4/§5/§7、`docs/谷段需求队列.md` task-133、`reports/db-window-runbook.md`、`reports/db-window-20261030.md`、`reports/hk-ingest-prep.md`、`reports/hk-ingest-apply.md`、`reports/inn-zh-backfill-v2.md`、`reports/cn-brand-apply.md`、`reports/cn-data-cleanup-prep.md`、`reports/strength-normalization-prep.md`、`reports/pseudo-combo-audit.md`
> 本期新做：用**只读** `mode=ro` + 各 ETL 的 `plan()/scan_*/build_plan()` 纯读函数把「现库基数 / 窗口增量」**全部重算一遍**（旧报告数字基于 SG 入库前的库），并修掉 3 处会误导验收的旧数字。
> 证据：`.tmp/db-window/prep-20261029/`（`probe.py|json`、`probe2.py|json`、`inn_zh_v2_plan.py|json`、`inn_zh_v2_as_v1.csv`、`corrections_rollback.sql`）

---

## 0. 结论（先看这段）

| 项 | 结论 |
|---|---|
| HK 数据缓存 | ✅ **齐**：`data/raw/hk_mo/hk_rpp_resource.xml` 4,297,930 B / `<drug>` **14,275** 条 / `lastUpdate=2026-10-23` / `permitNo` 14,275 全唯一 / 成分 token 23,835 / sha256 `0dacdfc40f0d188f…`；抓取时间 2026-10-28 12:10 |
| HK 字段口径 | 只有 **名称 / 持有人 / 注册号 / 活性成分**；**无规格、无剂型、无注册状态、无中文名、无包装、无释放机制** → 落库 `strength=NULL / dosage_form='unknown' / status='unknown' / release='none'`，D1 剂量对应不可用 |
| HK 可入库量（**按现库重算**） | products **+13,935 → 445,490**、components **+22,302 → 556,548**、product_name +13,935、name_key **+9,197**、name_variant **+13,363**；substance/variant **不变**；丢弃 **340**（321 无成分 + 19 无可用 variant）；token 映射 **93.8%**、产品级 **97.6%** |
| ⚠️ 旧数字更正 ① | 旧 runbook 的 HK `+13,832 / +21,881 / +9,596 / +13,461` 是 SG 入库前的库（变体 13,772）；现库变体 **14,249**，**103 个 HK 产品恢复了 variant** → 验收值请用本表 |
| ⚠️ 旧数字更正 ② | 伪复方产品级修复是 **214 产品 / 删 265 行 component**（不是 285）；`.tmp/pseudo-combo/dryrun.json` 同口径亦为 265 |
| ⚠️ 旧数字更正 ③ | **`etl/apply_inn_zh.py --csv data/inn_zh_backfill_v2.csv` 是空转**（0 条生效）：v2 CSV 列名是 `zh_name`，脚本读 `zh_candidate`。已转出 `inn_zh_v2_as_v1.csv`（236 行）并只读校验 **236 accepted / 0 skipped** |
| CN 五项 | inn_zh v2（+236 → 3,115）、商品名候选（净 +229 名）、CN 清洗（−1,286 产品 → 145,061）、伪复方（−265 components）、单位归一（102,988 行文本，131→97 种）**输入/脚本/基数均已核对齐全** |
| 许可 | ❌ `docs/许可清单.md` **没有** HK Drug Office / 註冊藥劑製品行（§2 只到 CA）；结论只写在 `reports/hk-mo-audit.md` §1.2 与 `hk-ingest-prep.md` §1 → **阻塞项**（本任务写范围外） |
| 窗口耗时 / 磁盘 | 机器时间 **~60–75s**（不含人工核验）；峰值 <1.5 GB（D 盘剩 237 GB）；窗口后 DB ≈ **385 MB（±10）**，VACUUM 后基本持平（当前 freelist=0） |
| 阻塞 / 待决策 | 4 条：HK 许可行缺文档、inn_zh apply 路径（已用转列 CSV 绕过）、**单位归一的显示口径**、商品名/清洗顺序（净额相同，仅记录顺序） |

---

## 1. 窗口起点基线（2026-10-29 08:0x 只读实测）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\db-window\prep-20261029\probe.py     # 只读：mode=ro + ETL plan/scan 纯读函数
```

| 项 | 值 |
|---|---|
| DB | `data/drugs.db` **364,195,840 B（364.2 MB）**，`journal_mode=delete`，`page_size=4096`，`freelist=0` |
| products / components | **431,555 / 534,246** |
| product_name / name_key / name_variant | 607,317 / 168,943 / 184,766 |
| substance / variant / source | 12,649 / 14,249 / 36 |
| country 分布 | CN 146,347 · US 110,179 · GB 61,051 · CA 43,847 · ES 25,395 · TW 16,457 · AU 11,890 · MX 10,878 · SG 5,511；**HK 0** |
| region | 列已就绪（`EU`），**EU 行 0** |
| coverage | **9 行** |
| 完整性 | `quick_check=ok`、`foreign_key_check=0` |
| schema | `product.country` CHECK 含 `HK`+`SG`（10 值）、`region` 列 + XOR CHECK 已在库 → **`db/init_db.py` 应无重建**（窗口只做幂等确认） |

---

## 2. HK（衞生署藥物辦公室 註冊藥劑製品名單）

### 2.1 缓存清单（文件 / 行数 / 大小 / 抓取日期）

| 文件 | 大小 | 抓取时间 | 内容 / 用途 |
|---|---:|---|---|
| `data/raw/hk_mo/hk_rpp_resource.xml` | 4,297,930 B | 2026-10-28 12:10 | **唯一入库源**；`<lastUpdate>2026-10-23</lastUpdate>`，`<drug>` **14,275** 条；每行 `productName / regCertHolderName / permitNo / activeIngs` |
| `data/raw/hk_mo/hkgov_terms.txt` | 9,362 B | 2026-10-28 12:11 | data.gov.hk 条款正文（许可结论证据） |
| `data/raw/hk_mo/hkgov_ckan_en.json` | 2,521 B | 2026-10-28 12:09 | CKAN 元数据（`license_title=null`，与门户 T&C 不一致，**以 T&C 为准**） |
| `data/raw/hk_mo/hk_rpp_sample20.csv` | 1,671 B | 2026-10-28 12:11 | 抽样 20 行人工对照 |
| `data/raw/hk_mo/hk_do_*.err.html` | 3,519 B×2 | 2026-10-28 12:09 | 药办网页抓取失败留档（**不影响 XML**，XML 是 data.gov.hk 资源直链） |

复制/重抓校验（本报告已跑）：

```powershell
& $py -c "import xml.etree.ElementTree as ET;r=ET.parse('data/raw/hk_mo/hk_rpp_resource.xml').getroot();print(r.findtext('lastUpdate'), len(r.findall('drug')))"
# → 2026-10-23 14275
Get-FileHash data\raw\hk_mo\hk_rpp_resource.xml -Algorithm SHA256   # 0dacdfc40f0d188f…（前 16 位）
```

> 缓存新鲜度：数据截止 **2026-10-23**（抓取时 5 天前）；XML 是 http 直链但缓存已落盘，窗口不需要联网。

### 2.2 字段口径（名称 / 成分层）

| DrugList 字段 | DB | 现库事实 |
|---|---|---|
| `permitNo`（`HK-58956`） | `product.product_id` / `approval_id` | 14,275 全唯一，天然幂等键 |
| `productName`（英文全大写） | `name_key.norm` + `name_variant.raw` + `product_name(trade,is_primary=1)` | 走 `normalize_name.normalize()`；**不做中文名**（源无中文） |
| `regCertHolderName` | `product.mah` | 原文 |
| `activeIngs/activeIng`（23,835 token） | `product_component`（每成分一行，ord 0..） | 映射 `substance`+`variant`；盐/水合物拆 variant |
| **无**规格 | `strength_value/unit`、`per_volume_*` = **NULL** | 品名里的 `500mg/1%` **不解析**（不可靠） |
| **无**剂型/给药途径 | `dosage_form='unknown'`、`form_base=NULL`、`route=NULL` | 页面必须明示「香港不提供剂型」 |
| **无**注册状态 | `status='unknown'`、`status_date=NULL` | **coverage.active=0 是「状态未提供」，不是「0 在售」** |
| **无**包装/释放 | `pack=NULL`、`release='none'` | 不展示 release |
| `lastUpdate` | `source.data_as_of` / `ingest_run.note` | 2026-10-23；`source_id='hk_dh'` 自动登记 |

### 2.3 ETL 与映射率（本次重算，非照抄旧报告）

脚本：`etl/ingest_hk_druglist.py`（520 行，`py_compile` 通过；`--apply/--allow-real/--rollback/--manifest`）

| 指标 | 本次实测（现库） | 旧报告（task-88，变体 13,772） |
|---|---:|---:|
| XML 产品行 | 14,275 | 14,275 |
| 成分 token 匹配 | **22,353 / 23,835 = 93.8%**（DB 22,331 + TW 别名 22 + HK-BAN 0） | 同 |
| 未匹配 distinct | 286（NOSCAPINE 174、SQUILL 173、SENEGA 162、COCILLANA 158…植物提取物/疫苗/兽药） | 同 |
| dry-run 可写产品 | 13,954 | 13,954 |
| **可落库 products** | **13,935（97.6%）** | 13,832 |
| **可落库 components** | **22,302** | 21,881 |
| 无可用 variant 丢弃 | 19 产品 / 51 component | 122 产品 / 472 component |
| 丢弃合计 | **340**（321 无任何可挂成分 + 19 无 variant） | 443 |
| 复方（≥2 成分） | 3,567 | 3,567 |

> 差异根因：SG 入库新增 **477 个 variant**（13,772→14,249），HK 里 103 个产品原本「匹配到 substance 但无 variant」现在能挂上。**这是真实改善，不是口径漂移** —— 验收请按 13,935。

### 2.4 预计增量与体积

| 表 | 基线 | HK 后 | 增量 |
|---|---:|---:|---:|
| product | 431,555 | **445,490** | +13,935 |
| product_component | 534,246 | **556,548** | +22,302 |
| product_name | 607,317 | 621,252 | +13,935 |
| name_key | 168,943 | 178,140 | +9,197 |
| name_variant | 184,766 | 198,129 | +13,363 |
| substance / variant | 12,649 / 14,249 | 不变 | 0（不硬造成分） |
| source | 36 | 37 | +`hk_dh` |
| coverage | 9 行 | **10 行** | HK 行（13,935 / active 0 / 状态未提供） |

- **体积**：按 task-88 副本实测「13,832 产品 → 净 +10.2 MB（VACUUM 后）」等比 → **HK 净 +≈10.3 MB**；窗口全程（HK+EMA+CN 五项）预计 **364.2 → 385 MB（±10）**；当前 `freelist=0`，VACUUM 主要回收清洗删除的 ~1 MB。
- **耗时**：事务 ~2.5–4s（426k 行库实测 2.8s）；dry-run 1.6s。

### 2.5 许可结论

- **结论（已在 `reports/` 落定，但不在 `docs/`）**：data.gov.hk Terms and Conditions 允许**免费商用/非商用浏览、下载、分发、复制**，条件 = **注明数据来源 + 承认政府及相关机构知识产权**；CKAN `license_title=null` 与门户 T&C 冲突时**以 T&C 为准**。ETL 会写 `source(hk_dh)`：`license='DATA.GOV.HK Terms and Conditions（free reuse, attribution required）'`、`license_url=https://data.gov.hk/en/terms-and-conditions`、`data_as_of=2026-10-23`。
- **缺口**：`docs/许可清单.md` §2 只到 CA（且标题仍写「27 行」，现 `source` 已 36 行）；**HK 行缺失** → 见 §4 阻塞项 ①。
- 页面义务（HK build 任务）：About/覆盖页四语署名「資料來源：DATA.GOV.HK / Department of Health（香港衞生署藥物辦公室）註冊藥劑製品名單」+ 不暗示政府背书 + 外链用 data.gov.hk **https 数据集页**（不用 http XML 直链）。

### 2.6 「下一次 DB 窗口可立即执行」的最小命令序列

> 前置：Lead 放行；`site/build.py` / `publish.ps1` / 其它 ingest **全部结束**（串行）；Windows PowerShell 根目录。每步后核对「预期」列，不符即停并回滚。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$ts = Get-Date -Format yyyyMMdd-HHmm

# 0) 备份 + 记录 sha256（唯一 schema 回滚手段）
Copy-Item data\drugs.db "data\backups\drugs-before-window-20261029-$ts.db"
Get-FileHash "data\backups\drugs-before-window-20261029-$ts.db" -Algorithm SHA256

# 1) schema 幂等确认（期望：无「迁移 product 表」，≤1s，431,555 行不变）
& $py db\init_db.py

# 2) HK（期望 products 445,490 / components 556,548 / source+hk_dh / coverage 10 行）
& $py etl\ingest_hk_druglist.py --apply --allow-real --db data\drugs.db `
    --manifest .tmp\hk-ingest\hk_write_manifest.json

# 3) EMA / EU region（可选，按 Lead 决定；期望 products 447,847 / coverage 11 行）
& $py etl\ingest_ema_medicines.py --apply-products --allow-real --db data\drugs.db `
    --manifest .tmp\ema-ingest\ema_products_manifest.json

# 4) CN inn_zh v2：236 填补（用转好的 v1 列 CSV，带 manifest/回滚；期望 inn_zh 2,879→3,115）
& $py etl\apply_inn_zh.py --csv .tmp\db-window\prep-20261029\inn_zh_v2_as_v1.csv `
    --min-confidence medium --apply --allow-real --manifest .tmp\inn-zh2\manifest_v2.json

# 5) CN inn_zh 旧值修正 9 条（条件更新，只改仍是旧品牌名的行；期望 9 行）
& $py -c "import sqlite3,io;c=sqlite3.connect('data/drugs.db');c.executescript(io.open('.tmp/inn-zh2/corrections.sql',encoding='utf-8').read());c.commit();print('corrections ok');c.close()"

# 6) CN 清洗（期望 CN 146,347→145,061；form 非规范 0；异常规格 0；删 1,286 产品）
& $py etl\cleanup_cn_data.py --apply --allow-real --run-id cn-cleanup-v1

# 7) 伪复方产品级修复（期望 components −265；products 不变）
& $py etl\fix_pseudo_combos.py --apply --allow-real --manifest .tmp\pseudo-combo\fix_manifest.json

# 8) CN 商品名候选（high 再 all；期望净 +229 名 / +12 key / +13 variant / +1 source beijing_ybj）
& $py etl\apply_cn_brand_candidates.py --apply --allow-real --min-confidence high --manifest .tmp\cn-brand-apply\manifest.json
& $py etl\apply_cn_brand_candidates.py --apply --allow-real --min-confidence all  --manifest .tmp\cn-brand-apply\manifest.json

# 9) 单位归一（期望 102,988 行文本；products/components 不变；distinct strength_unit 131→97）
& $py etl\normalize_strength.py --apply --allow-real --manifest .tmp\strength-norm\normalize_manifest.json

# 10) 验数
& $py db\check_data.py
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');print(c.execute('pragma quick_check').fetchone()[0], len(c.execute('pragma foreign_key_check').fetchall()))"
& $py db/q.py "SELECT (SELECT COUNT(*) FROM product) p,(SELECT COUNT(*) FROM product_component) c,(SELECT COUNT(*) FROM product WHERE country='HK') hk,(SELECT COUNT(*) FROM product WHERE region='EU') eu"
#   期望：446,561 / 557,343 / 13,935 / 2,357；quick ok / FK 0；coverage 11 行

# 11) VACUUM（可选；回收清洗删除的页）
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');c.execute('VACUUM');c.close()"
```

**逐步预期总量（本报告重算；EMA 用 task-107 旧实测，见风险 5）**

| # | 步骤 | products | components | product_name | name_key | name_variant | sources |
|---|---|---:|---:|---:|---:|---:|---:|
| — | 基线 | 431,555 | 534,246 | 607,317 | 168,943 | 184,766 | 36 |
| 2 | HK | 445,490 | 556,548 | 621,252 | 178,140 | 198,129 | 37 |
| 3 | EMA | 447,847 | 558,902* | 623,609 | 179,052 | 198,129 | 38 |
| 6 | CN 清洗（−1,286 产品 / −1,294 成分 / −1,463 名） | 446,561 | 557,608 | 622,146 | 179,052 | 198,129 | 38 |
| 7 | 伪复方（−265 成分） | 446,561 | 557,343 | 622,146 | 179,052 | 198,129 | 38 |
| 8 | CN 商品名（净 +229 名 / +12 key / +13 variant） | 446,561 | 557,343 | **622,375** | 179,064 | 198,142 | 39 |
| 10 | 单位归一（文本） | 446,561 | 557,343 | 622,375 | 179,064 | 198,142 | 39 |

\* EMA components 2,354 为变体 13,772 时点的实测；现变体集更大，可能小幅上修（不影响 products）。

**回滚（按逆序，任一步异常即停）**

| 层 | 命令 |
|---|---|
| 单位归一 | `& $py etl\normalize_strength.py --rollback --allow-real --manifest .tmp\strength-norm\normalize_manifest.json` |
| CN 商品名 | `& $py etl\apply_cn_brand_candidates.py --rollback --allow-real --manifest .tmp\cn-brand-apply\manifest.json` |
| 伪复方 | `& $py etl\fix_pseudo_combos.py --rollback --allow-real --manifest .tmp\pseudo-combo\fix_manifest.json` |
| CN 清洗 | `& $py etl\cleanup_cn_data.py --rollback --allow-real --run-id cn-cleanup-v1`（journal + 删除快照） |
| inn_zh 修正 9 条 | `& $py -c "import sqlite3,io;c=sqlite3.connect('data/drugs.db');c.executescript(io.open('.tmp/db-window/prep-20261029/corrections_rollback.sql',encoding='utf-8').read());c.commit();c.close()"` |
| inn_zh 填补 | `& $py etl\apply_inn_zh.py --rollback --allow-real --manifest .tmp\inn-zh2\manifest_v2.json` |
| EMA | `& $py etl\ingest_ema_medicines.py --rollback-products --allow-real --manifest .tmp\ema-ingest\ema_products_manifest.json` |
| HK | `& $py etl\ingest_hk_druglist.py --rollback .tmp\hk-ingest\hk_write_manifest.json --allow-real --db data\drugs.db` |
| 整库 | `Copy-Item "data\backups\drugs-before-window-20261029-$ts.db" data\drugs.db`，再 `db/check_data.py` + quick/FK |

> 注：`.tmp/hk-ingest/hk_write_manifest.json`（1.6 MB）现是**副本演练**生成的清单；真实 apply 会按同一路径**覆盖重写**，不要拿旧清单回滚真实库（product_id 相同但 created keys 集合可能不同）。

---

## 3. CN v2 批（5 项，逐项 输入 / 脚本 / 基数 / 影响 / 回滚 / 风险）

### 3.1 CN inn_zh v2（236 个缺中文名成分）— task-127

| 项 | 内容 |
|---|---|
| 输入 | `data/inn_zh_backfill_v2.csv` 258 行 = **fill 236**（high 196 / medium 40）+ **correction 22**（9 条 DB 待改 + 13 条仅 CSV） |
| 脚本 | `etl/apply_inn_zh.py`（不兼容 v2 列）→ **本报告转出** `.tmp/db-window/prep-20261029/inn_zh_v2_as_v1.csv`（236 行 v1 列）；修正用 `.tmp/inn-zh2/corrections.sql`（9 条）/ `corrections_rollback.sql`（反写 9 条） |
| 现库基数 | `substance.inn_zh` 非空 **2,879**；CN 在用但缺中文名的成分 **236** 个 / 覆盖 **31,055** 个 CN 产品（21.2%） |
| 预计影响 | `inn_zh` **2,879 → 3,115（+236）**；CN 用到的 3,065 个成分全部有中文名 → 英文通用名显示 21.2%→**0**；products/components **不变**；修正 9 行（只读核对：9/9 当前仍是旧品牌名，会生效） |
| 只读校验 | `inn_zh_v2_plan.py`：**236 accepted / 0 skipped**（`expected_after=3115`） |
| 回滚点 | `apply_inn_zh` 撤销清单 `.tmp/inn-zh2/manifest_v2.json`；修正 9 条用 `corrections_rollback.sql`；兜底整库备份 |
| 风险 | 40 个 medium（生物制品/疫苗/复方，如克拉维酸、非格司亭、锝[99mTc] 标记物）；14 个「映射可疑」成分（dinoprostona 等 155 产品）**只补名、不改映射**，另开审计 |
| 断言 | `SELECT COUNT(*) FROM substance WHERE inn_zh IS NOT NULL AND trim(inn_zh)<>''` → **3,115** |

### 3.2 CN 商品名候选 — task-108

| 项 | 内容 |
|---|---|
| 输入 | `data/cn_brand_candidates.csv` **542** 行（confidence high **31** / medium **511**；nhsa_snapshot 465 / jiangsu 49 / beijing 19 / nhsa_public_batch 6 / qinghai 2 / zhejiang 1） |
| 脚本 | `etl/apply_cn_brand_candidates.py`（`--dry-run/--apply/--rollback/--min-confidence/--manifest`） |
| 现库基数 | CN `product_name(trade)` **18,287**；CN 无任何 trade 名的产品 **128,060**（87.5%） |
| 预计影响（本次重算一致） | high：50 产品 / 17 候选 / 10 新 key；all：**232 产品 / 84 候选 / 12 新 key / 13 新 variant / 1 新 source（`beijing_ybj`）**；skip：无匹配产品 391、无批文 52、已有不同 trade 30（conflict 不覆盖）；**products/components 不变**。CN 清洗会删掉其中 **3** 个产品 → **净 +229 名**（两种顺序净额相同，见 §3.3） |
| 回滚点 | `.tmp/cn-brand-apply/manifest.json`（232 链接 + 12 key + 13 variant + source） |
| 风险 | 511 个 medium 来源滞后；391 个候选批文不在库（等未来入库重跑）；30 个 conflict 不覆盖（可能是现有通用名/旧名） |

### 3.3 CN 数据清洗 — task-129

| 项 | 内容 |
|---|---|
| 输入 | 现库 CN **146,347** 产品（只读扫描）；规则常量在 `etl/cleanup_cn_data.py` |
| 脚本 | `etl/cleanup_cn_data.py`（journal 字段级 old/new + 去重快照；`--apply --allow-real --run-id`） |
| 现库基数（本次扫描） | form_base 非规范 **1,214 行 / 67 类**（其中检测/试剂 **218 行**）；规格异常 **30 行**（>100,000 / ≤0）；无规格 **5,230 产品**；精确重复 **756 组 / 2,042 行**；近重复 **14,499 行 / 14,242 产品**；批文待规范化 **1,331 行** |
| 预计影响 | form_base → canonical（检测类 `other`+note）；异常规格 30 行 → 4 列置 NULL + note；无规格只加 note；**删 1,286 产品**（每组留最小 product_id）→ CN **145,061**，连带 **1,294 product_component / 1,463 product_name**；近重复只写 `cleanup_cn_dup_review`（14,242）不删；批文：339 去「(参照)」、912 标 import、76 补「国药准字」、3 多文号、1 无需改 |
| 新表 | `cleanup_cn_journal`（~9,473 行）、`cleanup_cn_deleted_product`（1,286）、`cleanup_cn_dup_review`（14,242）——**窗口后留存**，供回滚/审计 |
| 回滚点 | `--rollback --allow-real --run-id cn-cleanup-v1`（恢复字段/产品/note，指纹与基线一致）；兜底整库备份 |
| 风险 | ① 76 行「补国药准字」是启发式（脚本一处开关可改为只标记）；② 检测试剂仍在产品表（隐藏属 build 任务）；③ 异常规格不纠正（不猜值）；④ 近重复未合并（14,242 产品仍重复计数） |
| 顺序建议 | **cleanup 放在商品名候选之前**：否则 3 条新名随产品 cascade 消失，净额相同但少一次困惑；两序都安全 |

### 3.4 伪复方 214 产品删重复 salt 成分 — task-137

| 项 | 内容 |
|---|---|
| 输入 | `data/pseudo_combo_issues.csv` **9,012 行**（product_level 214 + key_level 8,798）；判定用 `fix_pseudo_combos.py` 的严格盐词表 |
| 脚本 | `etl/fix_pseudo_combos.py`（`--dry-run/--apply/--rollback`；产品级只删重复 salt、保留 base、重排 ord） |
| 现库基数 | 产品级 **214 产品**；市场分布 AU 157 / TW 19 / SG 15 / CA 13 / MX 6 / US 4；key 级 **545 key / 8,798 产品**（留给 build 层 base 归并，v0.8.3 已上线） |
| 预计影响 | **删除 265 行 component**（旧 runbook 写 285，**以 265 为准**；`.tmp/pseudo-combo/dryrun.json` 同为 265）；products **不变**，components −265 |
| 回滚点 | `.tmp/pseudo-combo/fix_manifest.json`（apply 时生成）；副本验证时 component 内容 hash 可回到原值 |
| 风险 | 214 产品中 base/salt **强度不一致**的情况未自动校验（脚本不比对 strength）→ 建议 apply 后抽 5 个 TPN/多电解质样例看成分表；key 级 545 假复方仍要靠 build 归并 |

### 3.5 单位归一 + 液体浓度语义 — task-135

| 项 | 内容 |
|---|---|
| 输入 | 现库 `product_component` 全表（只读扫描）；规则 `UNIT_MAP` 131 种 → 97 种 |
| 脚本 | `etl/normalize_strength.py`（`--dry-run/--apply/--rollback/--flags/--manifest`） |
| 现库基数 | 将变更 **102,988 行**（strength_unit 27,567 + per_volume_unit 75,421）；`distinct strength_unit` **131**、`per_volume_unit` 22；无法识别 **665 行**（`h` 312 / `actuation` 167 / `tablet` 140…）保留原文 |
| 口径对账（重要） | 任务/审计说的 **11,880** 是「**非白名单单位**」口径；本机按同族（`iu/ug/μg/unit(s)/u/vg/vp/ffu/cfu/pfu/genome copies/cells/meq/mci/uci/kiu/miu/万iu…`）重算 = **10,426 行**（+ per_volume 58 行），差 1,396 因审计族定义更宽/时点不同。**102,988 的大头是 `ml→mL` 93,381 行（纯大小写）**，真正同义变体约 8–9k（`iu→IU` 3,208、`ug/μg/µg→mcg` 3,526、`unit/u→unit` 255 级、`meq→mEq` 151、`mci→mCi` 101、`vg→VG` 等） |
| 预计影响 | 只改单位文本、**不换算数值**；products/components 不变；`distinct strength_unit` **131→97**；`ml/iu/ug` 小写残留 **0** |
| flags（build 输入） | `liquid_no_concentration` 38,522 / `liquid_no_strength_no_concentration` 19,987 / `invalid_strength` 44 / `extreme_strength` 324 / `trade_name_contains_dose` 55,100（`.tmp/strength-norm/flags.csv` 5.6 MB 已存在） |
| 回滚点 | `.tmp/strength-norm/normalize_manifest.json`（102,988 行 old/new，29.7 MB）；二次 apply 幂等（0 行） |
| **前端风险（需 Lead 决策）** | `site/build.py` 的 `_RE_UNIT = (?<![\w])(万iu\|microgram\|unit\|meq\|mci\|iu\|ug)(?![\w])` **只匹配小写**；归一成 `IU/mEq/mCi` 后不再包 `data-i18n` span → zh-Hant 会从「國際單位」变「IU」、es 从「UI」变「IU」。**建议数据窗口照跑**，紧接着一个 build 小改动：`_RE_UNIT` 加 `(?i)` + 补 `unit.IU/unit.mEq/unit.mCi` 四语键（不改则只是少一层本地化，不影响数值/排序） |

---

## 4. 阻塞项 / 需 Lead 拍板（明确：**不做人工审核**）

| # | 类型 | 事项 | 现状 | 需要什么 |
|---:|---|---|---|---|
| 1 | 缺文档（阻塞许可先行） | `docs/许可清单.md` 无 HK Drug Office / 註冊藥劑製品行；§2 仍写「27 行」（现 36 行） | 结论已在 `reports/hk-mo-audit.md` §1.2、`hk-ingest-prep.md` §1；ETL 会写 `source.license/license_url` | **Lead 授权一个 docs 任务**（本任务写范围外）补 HK 行 + 计数口径；不阻塞数据窗口本身 |
| 2 | 缺脚本（已给绕行） | `etl/apply_inn_zh.py --csv data/inn_zh_backfill_v2.csv` **空转 0 条**（列名 `zh_name` vs `zh_candidate`） | 已转 v1 列 CSV：`.tmp/db-window/prep-20261029/inn_zh_v2_as_v1.csv`（236/236 accepted） | 直接用它（**推荐，有 manifest**）；或另开任务给 `apply_inn_zh.py` 加 `--v2` 读原生 CSV |
| 3 | **需 Lead 决策** | 单位归一的**前端显示口径**：`iu/meq/mci` 大写化后失去 i18n（zh-Hant「國際單位」→「IU」、es「UI」→「IU」） | 数据侧已就绪；build 侧未改（禁改） | 拍板：①接受英文缩写（零改动）②下一版 build 放宽 `_RE_UNIT` + 补 3 个键（推荐，1 处 regex + 12 条文案） |
| 4 | 顺序（低风险） | 商品名候选 vs CN 清洗先后 | 净额同为 **+229 名**（3 个产品是精确重复，删后 cascade） | 只需确认按「cleanup → brand」执行（本报告 §2.6 已按此排序） |
| 5 | 数字更正（无需决策） | HK 13,832→**13,935**；components 21,881→**22,302**；keys 9,596→**9,197**；variants 13,461→**13,363**；伪复方 285→**265**；EMA components 2,354 可能小幅上修 | 均已写入本报告 §2.4 / §3.4 | 验收表/`db-window-20261030.md` §8 回填时用本报告数字 |
| 6 | 预期红测试 | `tests.test_markets_registry::test_enabled_markets_match_db_countries`：窗口后 DB 10 国（含 HK）+ EU region 行（country NULL）vs enabled 9（无 HK） | 已知过渡态 | 等 HK build（task-132）+ markets 启用窗口一并修；窗口内**不要**改 `markets.json`/测试 |
| 7 | 数据缺口（不在本窗口） | HK 无规格/剂型/状态；EMA 289 产品无成分；CN 391 候选批文不在库、52 无批文；近重复 14,242 产品；14 个 CN 映射可疑成分 | 均已按规则处理（跳过/标记/丢弃计数） | **不设人工审核**：不写库的不写、可疑的标 note、映射问题另开审计 |
| 8 | 窗口后 | HK build 支持（国家列/选择器/i18n/About 署名）未做 → HK 数据入库后不会出现在站点 | 数据与展示解耦 | 窗口后紧跟 task-132；发布顺序：数据 → build → markets 启用 → publish |

---

## 5. 复核命令与证据

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\db-window\prep-20261029\probe.py           # 基线 + HK 映射 + CN 四项 + 单位（只读，43.7s）
& $py .tmp\db-window\prep-20261029\probe2.py          # 删除影响面 / 单位口径对账 / 逐步总量推演
& $py .tmp\db-window\prep-20261029\inn_zh_v2_plan.py  # 生成 v1 列 CSV + 236/236 校验 + 9 条修正现状
```

| 证据 | 内容 |
|---|---|
| `prep-20261029/probe.json` | 基线计数、coverage、HK dry-run+落库重算、inn_zh/brand/cleanup/pseudo/strength 计划 |
| `prep-20261029/probe2.json` | 清洗删除带走的 1,294 成分/1,463 名、单位族对账、逐步总量表 |
| `prep-20261029/inn_zh_v2_as_v1.csv` / `inn_zh_v2_plan.json` | 236 行 v1 列 CSV + 只读计划（236/0）+ corrections 9/9 |
| `prep-20261029/corrections_rollback.sql` | 9 条修正的反写 SQL（条件匹配新值才回滚） |
| 既有证据 | `.tmp/hk-ingest/`（dryrun/manifest/副本库）、`.tmp/cn-brand-apply/`、`.tmp/cn-cleanup/`、`.tmp/pseudo-combo/`、`.tmp/strength-norm/`、`.tmp/inn-zh2/` |

---

## 6. 给 Lead 的摘要（≤15 行）

1. **可立即执行（窗口 GO 后）**：HK（+13,935 产品 / +22,302 成分）→ EMA（可选，+2,357）→ CN inn_zh v2（+236 名，2,879→3,115）→ CN 清洗（−1,286 产品 → 145,061）→ 伪复方（−265 成分）→ CN 商品名（净 +229 名）→ 单位归一（102,988 行）→ check/VACUUM。终值 **products 446,561 / components 557,343 / coverage 11 行 / DB ≈385 MB**。
2. **机器耗时 ~60–75s**；峰值磁盘 <1.5 GB；D 盘剩 237 GB；每步都有 manifest/journal，整库回滚靠开窗备份。
3. **三处旧数字必须换**：HK 13,832→**13,935**（SG 新增 477 variant 让 103 个 HK 产品可挂）、its 21,881→**22,302**、伪复方 285→**265**。
4. **`apply_inn_zh.py --csv inn_zh_backfill_v2.csv` 是空转**（0 条）；我已转好 `.tmp/db-window/prep-20261029/inn_zh_v2_as_v1.csv`（只读校验 236/236），窗口直接用这个。
5. **需你拍板 1 件**：单位归一后 `IU/mEq/mCi` 大写会丢 i18n（zh-Hant「國際單位」→「IU」、es「UI」→「IU」）——建议数据窗口照跑、下一版 build 放宽 `_RE_UNIT` 大小写并补 3 个四语键。
6. **需你授权 1 件**：`docs/许可清单.md` 没有 HK 行（结论只在 reports/），补文档属另一任务，不阻塞数据窗口。
7. **顺序**：商品名候选放 CN 清洗**之后**（净额同为 +229，避免 3 条新名被 cascade）。
8. **预期 1 红**：`test_enabled_markets_match_db_countries`（DB 10 国 + EU region vs enabled 9），等 HK build + 启用窗口修。
9. **不做人工审核**：不写库的（391 无产品 / 52 无批文 / 30 conflict）跳过并计数，可疑的标 note，映射问题另开审计。
10. 全部只读完成：**未写 DB、未跑 apply、未 build/publish**；证据在 `.tmp/db-window/prep-20261029/`。

_本报告由 data-depth（task-3）生成；写范围：本文件 + `.tmp/db-window/`。未改 `data/*.csv`、未建 `data/db`、未提交。_
