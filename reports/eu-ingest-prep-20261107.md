# EU 区域层 ETL 准备（task-20，2026-11-07）

> 范围：新增 `etl/ingest_eu.py` + 快照 `data/raw/ema_20261107/` + 本报告。
> **未写 `data/drugs.db`**（`--apply` 本期一次都没跑）、未改 `site/` `lib/` `db/schema.sql` `docs/` `deploy/`、
> 未改 `data/markets.json`、未 commit、未发布。
> 依据：`reports/ema-evaluation-20261107.md`（task-17 许可/口径）、`reports/ema-ingest-prep.md`（task-97 映射实测）、
> `reports/eu-layer-schema.md`（task-102 region 建模 + 副本验证）。
> 底线不变：只做身份对应；EU 层没有规格/剂型/包装，**页面按「规格未收录」**，不换算、不猜。

## 0. 结论

| 项 | 结果 |
|---|---|
| 主源 / 补源 | **EC Union Register ODS 为主**（2,095 行 Human + Centrally authorised）、**EMA medicines JSON 补名字/状态/EMA 号** |
| 快照 | `data/raw/ema_20261107/ods_products.json` 16,768,535 B + `ema_medicines.json` 6,804,166 B（含 `fetch_meta.json` 溯源） |
| 关键发现 | **两源 ID 体系不同**：UR `EU/1/13/882` ↔ EMA `EMEA/H/C/005600`，**交集 0** → 连接键改用 **EPAR URL**（UR `EMALink` ↔ EMA `medicine_url`），URL 不中再用「两侧都唯一」的药名兜底 |
| dry-run 实际计数 | **产品 2,095** / **成分 2,138** / **product_name 2,095**；name_key 新建 **647**、name_variant 新建 **1,319**；corroboration 2,072；无成分子产品 **195**（见 §6） |
| 成分映射 | 2,372 个成分 token → **2,155 映射成功（90.8%）**，涉及 **1,042 个现有 substance**；未映射 217 个 token（184 个唯一串，主要是疫苗/生物制品/复方缺项） |
| 写库语句自检 | 在**内存库**按 `db/schema.sql` 建表灌全量数据：**FK 0 违规 / integrity ok / country-region XOR 0 / strength 全 NULL**，行数与 dry-run 完全一致 |
| 体积 | 内存库实测 EU 层数据占 **2.72 MB**（page_count×page_size 增量）；整库实测参考 +3~9 MB（task-102 曾测 +9.2 MB，含索引/VACUUM 效应），预算按 ≤9 MB 报 |
| 本期不做的 | `--apply` 写入真实库；`substance.atc` 补缺；EU 名字页策略；`markets.json` 改动——都留给 v0.10.0 后的写入窗口 |

## 1. 源快照（2026-11-07 抓取，`data/raw/` 不入库）

| 文件 | 来源 | 字节 | 发布时点 | 许可 |
|---|---|---:|---|---|
| `ods_products.json` | `https://ec.europa.eu/health/documents/community-register/ods/ods_products.json` | 16,768,535 | 2026-11-03T08:24Z（HTTP Last-Modified） | **CC BY 4.0** |
| `ema_medicines.json` | `https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json` | 6,804,166 | 2026-11-06T18:02:08Z（JSON `meta.timestamp`） | EMA Legal notice（**署名即可，含商业用途**） |

- sha256：`ods_products.json` = `84abdd66…f15782d7d`，`ema_medicines.json` = `bc5385a2…a85e9519`（完整值见同目录 `fetch_meta.json`）。
- 两源都可再发布；落地时 `source` 表写许可原文 + 许可链接，页面/About 四语署名「European Commission / Union Register」「European Medicines Agency」，**不使用 EMA logo**。

## 2. 过滤口径（UR 6,476 行 → 2,095 行）

| UR 字段 | 取值 | 行数 | 处置 |
|---|---|---:|---|
| `Type` | Human | 2,646 | 保留 |
| | Veterinary | 502 | 丢弃（EU 层本期只接人用） |
| | Orphan designation | 3,328 | 丢弃（孤儿药登记不是上市授权） |
| `Category`（在 Human 内） | Centrally authorised | **2,095** | **保留** |
| | Nationally authorised | 551 | 丢弃（那是成员国数据，不是 EU 层） |

（`Type` 与 `Category` 是交叉的两维，上表分行列出便于核对；最终保留 = Human ∧ Centrally authorised = **2,095**。）

## 3. 两源怎么连（本节是本期最关键的发现）

| 连接键 | 结果 |
|---|---|
| `EUNumber`（UR）↔ `ema_product_number`（EMA） | ❌ **不可用**：EU/1/13/882 与 EMEA/H/C/002755 是两套号，2,019 个 UR EU 号与 2,357 个 EMA 号**交集 0** |
| `EMALink`（UR）↔ `medicine_url`（EMA） | ✅ **主键：1,906 行**（UR 2,018 个非空 EMALink 中 1,906 命中） |
| 归一药名（去重音/小写/去标点） | ✅ **兜底 166 行**（要求 UR 侧该名只出现 1 次 **且** EMA 侧只有 1 条；UR 有 12 个名字各挂 2 个 EU 号，这类直接跳过，记 `name_ambiguous`，不猜） |
| 无 EMA 记录 | 23 行（UR 有、EMA 还没有，照写，只是没有 EMA 号/状态对照） |

→ 最终 **2,072 行（98.9%）有 EMA 对账记录**（写入 `corroboration`），23 行只有 UR 单一来源。

## 4. 字段映射表

### 4.1 Union Register → 库（主）

| UR 字段 | 目标 | 说明 |
|---|---|---|
| `Name[LanguageCode=EN].Text` | `name_key` + `name_variant.raw` + `product_name(name_type='trade')` | 法律注册表名，权威；清洗内嵌 HTML（如 `<sup>177</sup>`） |
| `EUNumber` | `product.approval_id`；也进 `product_id` | 2,019/2,095 有号；76 行无号 → `product_id` 用 `EU-urn-<slug(名)>` |
| `ActiveSubstance[EN].Text` | `product_component`（拆复方 → 多条） | 见 §6 |
| `MAH.Name` | `product.mah` | 2,094/2,095（100%） |
| `ATC[].Code/Description` | `product.note`（`ATC: N05AX12 aripiprazole`） | 2,058/2,095 有码（98.2%）；优先 5 级码，无 5 级取最长码；**不写 `substance.atc`**（本期不改成分表） |
| `Status` | `product.status` + note 原文 | 映射见 §5 |
| `AuthorisationDate` | `product.status_date` | 1,997/2,095（95.3%）；语义是**授权日**不是在售日，note 里写「Authorisation date」 |
| `LastDecisionDate` | `status_date` 兜底 | 无授权日时用最后决定日 |
| `EMALink` | `product.source_url` | 有则优先；无则用 `URI`（UR 页面） |
| `URI` | `product.note`/兜底 source_url | UR 记录页 |
| `Indication` / `TotalProcedures` / `TotalDecisions` / `CurrentAnnexLink` / `AssociatedNames` | 不写 | 本期不用（Indication 是长文本、许可无碍但不是身份信息） |

### 4.2 EMA → 库（补）

| EMA 字段 | 目标 | 说明 |
|---|---|---|
| `ema_product_number` | `product.note` + `corroboration.note` | 与 EU 号并列写清，不混用 |
| `medicine_status` | `product.note`（**不覆盖** UR 状态） | UR 是法律注册表，EMA 只做对照 |
| `medicine_url` | `corroboration.url`（`source_type='regulator'`） | 2,072 行 |
| `international_non_proprietary_name_common_name` / `atc_code_human` / MAH / dates | 不写 | UR 侧已够；不引入第二套口径 |

### 4.3 产品字段固定值

```
country = NULL            region = 'EU'           dosage_form = 'unknown'
form_base = NULL          route  = NULL           release = 'none'
pack = NULL               category = 'EU centralised (human)'    is_branded = 1
source_id = 'eu_union_register'                   retrieved_at = 抓取日
strength_value / strength_unit / per_volume_* = NULL（两源都无）
```

## 5. 状态映射（不臆造）

| UR `Status` | 行数 | `product.status` |
|---|---:|---|
| Active | 1,547 | `active` |
| Withdrawn | 394 | `withdrawn` |
| Revoked | 11 | `withdrawn` |
| Annulled | 1 | `withdrawn` |
| Refused | 85 | `unknown` |
| Expired / Sunset clause | 30 | `unknown` |
| Not renewed | 26 | `unknown` |
| Suspended | 1 | `unknown` |

→ 合计 `active 1,547 / withdrawn 406 / unknown 142`。UR 原文一律写进 `product.note`（`UR status: …`），页面按原文显示；schema 枚举只有 4 值，`unknown` 表示「已决定但不是在用/停用」，**不推断在售状态**。

## 6. 成分（规范活性成分）映射

**只精确映射，不新增 substance、不模糊匹配。** 复用 `etl/ingest_ema_medicines.py:SubstanceMapper` 的四级规则（task-102 已在副本上验证）：
`substance_id slug → inn_en 归一 → 拆盐 base → 去括号/剂量后 slug`。

复方处理（新增，本期实测很关键）：UR 每个产品只给一条 `ActiveSubstance` 文本，复方串必须拆开，否则整串映射不上。
拆分规则：` / `、`+`、`;`、` and ` 一定切；**紧凑斜杠只在每段都像药名时才切**（避免把疫苗株名 `A/California/7/2009` 拆散）。

| 口径 | 数量 |
|---|---:|
| 成分 token 总数（拆后） | 2,372 |
| 映射成功 | **2,155（90.8%）** |
| 映射方法 | slug 2,068 / cleanup 33 / salt-normalize 26 / salt-strip 25 / inn 3 / **unmapped 217** |
| 涉及现有 substance | 1,042 个（**不新增**） |
| 产品「全部成分映射成功」 | **1,900** ← 只有这些写 `product_component` |
| 产品「部分映射」 | 17（复方缺一个成分 → **整条不写组件**，避免把复方显示成单方） |
| 产品「全未映射」 | 176（疫苗/生物制品/植物提取物等） |
| 无成分串 | 2 |
| 写入组件行数 | **2,138** |
| 有组件但解析不到 variant | 0 |

未映射 top（唯一串，共 184 个）：`acetylsalicylic acid`(4) · 多种流感/COVID 疫苗长串(3) · `human fibrinogen`(3) · `masitinib`(3) · `Yttrium (90Y) Chloride`(3) · `Colecalciferol`(2，库内写法为 cholecalciferol) · `birch bark extract`(2) · `ferric citrate coordination complex`(2)。

> 处理建议：这些**不进库**（产品仍以名称/MAH/ATC/状态存在）。`substance` 补充是另一个数据任务（需要中文名/ATC/来源三件套），不在本窗口。

## 7. dry-run 实际计数（只读开库，1.22 s）

```powershell
& $py etl/ingest_eu.py            # 默认 dry-run，只读打开 data/drugs.db
```

| 将写入 | 行数 |
|---|---:|
| `product`（region='EU'） | **2,095** |
| `product_component` | **2,138** |
| `product_name`（trade） | **2,095** |
| `name_key` 新建 | **647**（其余 1,431 个名已存在） |
| `name_variant` 新建 | **1,319** |
| `corroboration`（EMA 对账） | **2,072** |
| `ingest_run` | 1 |
| `source` | 2（`eu_union_register` / `ema_medicines`，均缺失） |
| `product_id` 与现有库冲突 | **0** |

产物（`.tmp/eu-ingest/`，会话临时目录）：`eu_dry_run.json`（全部统计）、`eu_dry_run_samples.json`、`eu_products_preview.csv`（2,095 行逐产品预览）、`eu_source_rows.sql`、`eu_check_sql.json`。

## 8. 写库语句自检（不碰任何库文件）

`--check-sql` 把 `db/schema.sql` 建到 `:memory:`，灌入真实的 stub `substance`/`variant`（1,049 / 1,045 条），
再跑**与 `--apply` 完全同一段** `_write_rows()`：

| 项 | 结果 |
|---|---|
| 写入行数 | product 2,095 / component 2,138 / product_name 2,095 / name_key 2,078 / name_variant 2,083 / corroboration 2,072 / ingest_run 1 |
| `PRAGMA foreign_key_check` | **ok（0 违规）** |
| `PRAGMA integrity_check` | **ok** |
| `country`/`region` XOR 违规 | **0** |
| `product_component` 强度全 NULL | 2,138 / 2,138 |
| 区域层数据体积 | **2,719,744 B = 2.72 MB**（页面增量；整库预算按 3~9 MB 报） |

> 内存库是空库，所以 `name_key`/`name_variant` 是**全部** 2,078 / 2,083 行；对真实库的**新增**只有 647 / 1,319（§7）。其余表的行数与真实库将要写入的完全一致。

## 9. `source` 表 SQL 草案（写库窗口照抄）

```sql
INSERT INTO source (source_id, name, url, license, license_url, retrieved_at,
                    data_as_of, data_as_of_note, notes)
VALUES ('eu_union_register',
        'European Commission — Union Register of medicinal products',
        'https://ec.europa.eu/health/documents/community-register/html/index_en.htm',
        'CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/',
        '2026-11-06', '2026-11-03',
        'snapshot：ods_products.json 的 HTTP Last-Modified（2026-11-03 08:24 UTC）',
        'EU 中心审批（Centralised procedure）法律注册表；本 ETL 的产品主源。再发布须署名 European Commission / Union Register 并链 CC BY 4.0。')
ON CONFLICT(source_id) DO UPDATE SET retrieved_at=excluded.retrieved_at,
  data_as_of=excluded.data_as_of, notes=excluded.notes;

INSERT INTO source (source_id, name, url, license, license_url, retrieved_at,
                    data_as_of, data_as_of_note, notes)
VALUES ('ema_medicines',
        'European Medicines Agency — Medicines data (JSON)',
        'https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format',
        '© European Medicines Agency; re-use permitted with acknowledgement (EMA legal notice)',
        'https://www.ema.europa.eu/en/about-us/about-website/legal-notice',
        '2026-11-06', '2026-11-06',
        'snapshot：JSON meta.timestamp = 2026-11-06T18:02:08Z（每日 2 次重生成）',
        '对账/补充源（EMA 号、INN、medicine_status）；可再发布，须每份内容署名 EMA，不得使用 EMA logo。')
ON CONFLICT(source_id) DO UPDATE SET retrieved_at=excluded.retrieved_at,
  data_as_of=excluded.data_as_of, notes=excluded.notes;
```

> 注意：`tests/test_markets_registry.py` 会校验「`enabled` 市场的 `source_id` 必须在 DB `source` 表」。
> 所以窗口顺序必须是 **① 写 source 行 → ② 再改 `markets.json`**（如果同期要改）。

## 10. `data/markets.json` 的 EU 配置片段（本期只准备，不改文件）

把现有 EU 占位（`source_id: null`、`languages: []`）改成「disabled 的 region 层」：

```json
{
  "code": "EU",
  "kind": "region",
  "parent": null,
  "group": "EUROPE",
  "name": { "en": "European Union", "es": "Unión Europea", "zh": "欧盟" },
  "i18n_key": "home.eu",
  "flag": "🇪🇺",
  "source_id": "eu_union_register",
  "extra_source_ids": ["ema_medicines"],
  "default_lang": "en",
  "languages": ["en"],
  "enabled": false,
  "order": 90,
  "data_as_of": "2026-11-03",
  "notes": "区域层（kind=region，非国别）：EU 集中审批 = product.region='EU' + country=NULL（EC Union Register 主源 + EMA 补充）。授权有效 ≠ 各国在售；EMA/EC 数据不含规格/剂型/包装。启用（enabled=true）前必须：① UI 支持 region 行（国家下拉/矩阵按 country，暂无 region）；② 至少 1 个 enabled 成员国挂 parent='EU'（现成员国 parent=null，不满足校验）；③ 同步改 tests/test_markets_registry.py 与计数口径。"
}
```

**为什么本期必须 `enabled: false`**：`lib/markets.py` 校验「enabled region 至少一个 enabled 子市场」，而现有成员国 `parent` 都是 `null`；
`tests/test_markets_registry.py` 还硬断言 `region_codes == ("EU",)`、`eu.enabled is False`、成员国 `parent is None`。
启用是一个**独立的三件套改动**（markets.json + 测试 + UI region 渲染），不属于本窗口。

## 11. 写入窗口步骤（v0.10.0 发布后单独开）

| # | 步骤 | 判定 |
|---|---|---|
| 1 | 备份：`Copy-Item data/drugs.db data/backups/drugs-<日期>-pre-eu.db`（`run_all.py` 只留 5 份，手动再备一份） | 文件存在、字节一致 |
| 2 | 重抓快照（或复用 `data/raw/ema_20261107/`），`sha256` 与 `fetch_meta.json` 对得上 | 两文件 sha256 命中 |
| 3 | `& $py etl/ingest_eu.py --dry-run` | 计数与本报告 §7 同数量级（±3%，数据会随时间变） |
| 4 | `& $py etl/ingest_eu.py --check-sql` | FK 0 / integrity ok / XOR 0 |
| 5 | 副本演练：`Copy-Item data/drugs.db .tmp/eu-apply/test.db` → `--apply --db .tmp/eu-apply/test.db --manifest .tmp/eu-apply/manifest.json` → `db/check_data.py --db …`（若支持）→ `--rollback --manifest …` 验证回滚 | 副本 quick ok、FK 0、回滚后 `region='EU'` 行数 0 |
| 6 | 真实库：`& $py etl/ingest_eu.py --apply --allow-real --manifest .tmp/eu-apply/manifest-real.json` | 一次事务；输出 written 行数 = §7 |
| 7 | 校验：`SELECT COUNT(*) FROM product WHERE region='EU'` = 2,095；`SELECT * FROM coverage` 多出 EU 一行（≈2,095 产品 / 1,042 成分 / active 1,547）；`PRAGMA foreign_key_check` 空；`& $py db/check_data.py` | 全部符合 |
| 8 | 站内：`site/build.py` 到 `== done ==`（EU 不产生名字页时 dist +≈0.1 MB；若按新 key 建页则 +≈2.7 MB / +647 页）→ `publish.ps1` | 见 §13 |

**回滚**：`& $py etl/ingest_eu.py --rollback --manifest <manifest-real.json> --db data/drugs.db`
（删 `region='EU'` 产品 + 本 run 的 ingest_run + 本次新建的 name_key/name_variant；`corroboration`/`product_component`/`product_name` 由 `ON DELETE CASCADE` 跟着走）；
或直接从第 1 步备份恢复。回滚后必须复核：`product` 行数回到 477,098、`coverage` 回到 10 行、`PRAGMA foreign_key_check` 空。

## 12. 回滚清单 JSON 结构（`--apply` 自动写）

```json
{
  "tool": "etl/ingest_eu.py",
  "db": "data/drugs.db",
  "region": "EU",
  "source_id": "eu_union_register",
  "supplement_source_id": "ema_medicines",
  "run_id": "eu_union_register-2026-11-07",
  "created_at": "2026-11-07",
  "product_ids": ["EU-eu-1-13-882", "..."],
  "created_name_keys": ["abilify maintena", "..."],
  "created_name_variants": [["abilify maintena", "ABILIFY MAINTENA"], "..."],
  "counts": {"products": 2095, "components": 2138, "name_keys_new": 647,
             "name_variants_new": 1319, "product_names": 2095, "corroboration": 2072},
  "written": {"product": 2095, "corroboration": 2072, "name_key": 2078,
              "name_variant": 2083, "product_name": 2095,
              "product_component": 2138, "ingest_run": 1},
  "rollback_hint": "1) --rollback --manifest <本文件> --db <同一个库>；2) 或从备份恢复；3) 校验 SELECT COUNT(*) FROM product WHERE region='EU' 应为 0；coverage 只剩 10 国行。"
}
```

## 13. 风险 / 未决

1. **没有规格/剂型/包装**（两源都没有）：`dosage_form='unknown'`、`form_base=NULL`、强度全 NULL → 页面必须写「规格未收录」，**EU 层无法参与 D1 剂量对应**（与 task-97 结论一致）。
2. **口径**：「EU 授权有效 ≠ 各国在售」。页面文案必须带这句；`coverage` 里 EU 单独一行（`COALESCE(country, region)`），不进国家下拉/国家统计。
3. **计数口径**：库里多一层 region 后，README/About/首页「10 国」要同步成「10 国 + EU 区域」（AGENTS §4）；这是窗口期改动，本期不动。
4. **名字页策略未定**：647 个新 name_key 若都建页 → +647 页 / ≈+2.7 MB dist / sitemap +647；若走「不建 EU 名字页、只在成分页列 EU 名称」，dist +≈0.1 MB。属 site 侧决策，留给 v0.10.0。
5. **成分缺口**：176 个产品全无成分（疫苗/生物制品为主），17 个复方缺一成分。这两类在站内只出现在「名称/状态/MAH/ATC」层，需在页面标「成分未收录」，不做成分推断。
6. **快照会过期**：UR 是快照式（BETA，定期发布），EMA 每天 2 次。窗口重跑前重抓，别用 11-03 的快照当新数据。
7. **两源状态可能不一致**（EMA 的 Authorised vs UR 的 Active/Withdrawn 时间差）：本 ETL 以 UR 为准，EMA 只做对照写 note；不做两源合并计数。

## 14. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 快照（两份都在 data/raw/ema_20261107/，含 fetch_meta.json 的 sha256）
Invoke-WebRequest 'https://ec.europa.eu/health/documents/community-register/ods/ods_products.json' `
  -OutFile 'data/raw/ema_20261107/ods_products.json'
Invoke-WebRequest 'https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json' `
  -OutFile 'data/raw/ema_20261107/ema_medicines.json'

& $py etl/ingest_eu.py             # dry-run（只读）：计数 + 样例 + source SQL + 预览 CSV
& $py etl/ingest_eu.py --check-sql # 内存 schema 自检：写入行数 / FK / XOR / 体积，不碰库文件
# 写入窗口（本期不执行）：
# & $py etl/ingest_eu.py --apply --db .tmp/eu-apply/test.db --manifest .tmp/eu-apply/manifest.json
# & $py etl/ingest_eu.py --rollback --manifest .tmp/eu-apply/manifest.json --db .tmp/eu-apply/test.db
```

**本次交付的三条硬事实**（可复核）：
① 产品 2,095 / 成分 2,138 / name_key 新建 647（§7）；② 两源 ID 交集 0，靠 EPAR URL + 唯一药名连接 2,072 行（§3）；
③ 写库语句在真实 schema 上 FK 0 / XOR 0 / 强度全 NULL（§8）。
