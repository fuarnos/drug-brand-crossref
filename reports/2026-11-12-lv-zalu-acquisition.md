# 拉脱维亚 ZVA 国家药品注册库：取数 + 干跑 + `lv` 接入清单

日期：2026-11-12 ｜ 工位：phaseb-plan ｜ 任务：task-17
前置：`reports/2026-11-12-eu-member-states-scan.md` §12.1 / §14③（LV 判 A 类，CC0 1.0）
范围：**只到 dry-run**。未写 `data/drugs.db`、未改 `site/build.py`、未改 `data/markets.json` / `data/languages.json`、未 commit / publish。

---

## 0. 一句话

拉脱维亚是**目前许可最干净的一个源**（CC0 1.0，连署名都不强制），取数只有 **3.0 MB 一个 ZIP**，每天更新；
干跑已跑通：**40,600 个包装级条目 → 18,766 个注册号、6,261 个拉语商品名**，ATC 覆盖 **100%**、规格解析 **94.9%**、成分映射 **92.2%**。
**但「在售」只有 4,551 行**——如果只按 `status`/`prd_removed` 判，会得到 38,759 行，**高估 8.5 倍**，这是本任务最重要的一条结论。

| 项 | 结果 |
|---|---|
| 许可 | ✅ **CC0 1.0**（`data.gov.lv` 数据集元数据自证） |
| 快照 | ZIP **3,034,682 B** / sha256 `290dbb90…c59e50`；状态表 **1,416,333 B** / sha256 `6cde5cd3…d9f110` |
| ETL | `etl/markets/lv.py`：`--fetch` / `--dry-run` / `--self-check`，**无 `--apply`** |
| self-check | **17/17 通过**（49 标签齐全、`product_id` 无重复、状态规则自洽、变音折叠、CLI 无 `--apply`） |
| dry-run | 7.9 s（库副本 `.tmp/lv-ingest/lv.db`，`mode=ro`） |
| active | **4,551**（严格口径）；注册有效 39,545；已移除 290；已停售 764 |
| 与 EU 层 | LV 集中审批 1,562 个药号，**1,561 个与 EU 层重合**（覆盖 13,571 行）→ LV 几乎不带来新药，只带来**包装级细节 + 拉语名 + 价格** |

---

## 1. 许可（✅ 可入库可再发布，无义务）

- **许可**：**CC0 1.0 Universal（Public Domain Dedication）**
- **证据（官方元数据自证，`--fetch` 每次都会重新抓一份存证）**：
  `data.gov.lv` 数据集 `latvijas-zalu-registrs`（发布者 **Zāļu valsts aģentūra**）：
  `license_title = "CC0 1.0"`、`license_url = https://creativecommons.org/publicdomain/zero/1.0/`
  - 数据集页：`https://data.gov.lv/dati/lv/dataset/latvijas-zalu-registrs`
  - 元数据 API：`https://data.gov.lv/api/3/action/package_search?q=Latvijas%20Z%C4%81%C4%BCu%20re%C4%A3istrs`
  - 存证文件：`data/raw/lv_zalu_20261112/license/data.gov.lv_package_search.json`（46,833 B）
- **CC0 意味着**：无署名义务、无 share-alike、可商用、可再发布。
- **本站仍照全站统一口径署名**（避免出现「没有来源」的行）：
  「Zāļu valsts aģentūra (ZVA) · Latvijas Zāļu reģistrs · CC0 1.0」+ 数据截止日 + 数据集链接。
- **未改 `docs/许可清单.md`**（Lead 统一写）。建议行见 §10。

---

## 2. 快照（`data/raw/lv_zalu_20261112/`，不入 git）

| 文件 | 字节 | sha256 | Last-Modified | Content-Type |
|---|---|---|---|---|
| `HumanProducts.xml.zip` | **3,034,682** | `290dbb90c5c7407208bd326d27ed33c30bda3b27f75d8614ea4cddbc02c59e50` | Wed, 11 Nov 2026 **06:40:11 GMT** | `application/zip` |
| `zr-prd-status.csv` | **1,416,333** | `6cde5cd3695e1667c18bca9a53eebc954f3b3173fa96b2deaa1a2e7001d9f110` | Wed, 11 Nov 2026 **18:31:13 GMT** | `text/csv;charset=UTF-8` |
| `license/data.gov.lv_package_search.json` | 46,833 | — | — | `application/json` |
| `fetch_meta.json` | 1,967 | — | — | 抓取元数据（url/头/sha256/时间/许可） |

- 入口：`https://dati.zva.gov.lv/zalu-registrs/export/HumanProducts.xml.zip`（免登录、无 WAF、**无鉴权**）
- ZIP 内只有 1 个条目：`HumanProducts.xml`，**解包 124,930,581 B（125 MB）** → 必须流式解析，别整棵读进内存。
- 状态表：`https://dati.zva.gov.lv/zalu-registrs/export/zr-prd-status.csv`，**40,600 行**、10 列，与 XML `product_id` **1:1**（0 缺失、0 重复）。
- 更新频率：**每日**（ZIP 与状态表时间戳不同步，ZIP 06:40 UTC / 状态表 18:31 UTC，页面口径要写「每日，两个文件可能不同时刻」）。

---

## 3. ETL：`etl/markets/lv.py`

```
python etl/markets/lv.py --fetch        # 抓 ZIP + 状态表 + CC0 元数据（含许可自证）
python etl/markets/lv.py --dry-run      # 默认：读缓存 → 解析 → 统计（只读开库，不写库）
python etl/markets/lv.py --self-check   # 离线断言：49 标签 / 状态规则 / 变音折叠 / 无 --apply
```

- **故意不提供 `--apply` / `--rollback`**：许可没问题，但 ① UI 改版未完成（用户定「先取数、等 UI 改完再上线」）② `product.country` 的 CHECK 枚举还没有 LV。写库按 `etl/ingest_eu.py` 的三段式另开任务。
- 结构沿用 `etl/markets/nl.py`（同目录既有干跑骨架）：`cmd_fetch` / `iter_products` / `classify` / `_collect` / `cmd_dry_run` / `self_check`。
- **复用而不另起一套**：
  - 规格：`normalize_name.normalize()` + `normalize_strength.norm_unit()`（只做输入预整形 `SV/IU/IE/UI`→`iu`、`microgram`→`mcg`、`50 mg/ml`→`50 mg/1 ml`，**不做剂量换算**）
  - 成分：`ingest_sg_hsa.SgMapper.map_basic()`；前面加一层**拉丁语词形映射**（见 §6）
  - 剂型：`ingest_openfda_ndc.form_base_of()`
- 产物：`.tmp/lv-ingest/lv_dry_run.json`（7,707 B，全量统计）

---

## 4. 状态三开关（**重点章节**，页面口径必须照做）

### 4.1 三个 XML 开关 + 两个 CSV 信号

| 来源 | 字段 | 实测取值 | 含义 |
|---|---|---|---|
| XML | `status` | `1` 39,856 / `0` 737 / `2` 7 | 注册有效性。**实测 `status='0'` 的 737 行全部带 `sell_stop_date`** |
| XML | `prd_removed` | `0` 40,310 / `1` 290 | 是否已从注册库移除 |
| XML | `sell_stop_date` | 空 39,836 / 有日期 764 | 停售日期 |
| CSV | `mah_status` | `1` 5,076 / `0` 1,605 / `2` 33,919 | MAH 侧上市状态：1 可供、0 已撤回、**2 = 注册了但没在拉脱维亚上市** |
| CSV | `stock_status` / `stock_status_pharm` | 1 = 3,904 / 3,954 | 当下是否有库存（批发 / 药房） |

库存交叉（`stock_status`/`stock_status_pharm`）：`wh & ph` 3,381 · 仅药房 573 · 仅批发 523 · 都没有 36,123。

### 4.2 采用的口径

```
active（在售，进 coverage.active）=
    status == '1'
  ∧ prd_removed == '0'
  ∧ sell_stop_date 为空
  ∧ mah_status == '1'
  ∧ 程序 ∉ {平行进口 Paralēlais imports, 平行分销 Paralēlā izplatīšana, 未注册药品 Nereģistrētas zāles}
  → 4,551 行

registered_ok（注册有效但未必在售）= 前三项 ∧ 非移除/停售 → 39,545 行（不得当在售上报）
```

### 4.3 为什么不能用「简化口径」

| 口径 | 行数 | 相对真实在售 |
|---|---|---|
| 只按 `status='1' ∧ prd_removed='0' ∧ 无停售` | **38,759** | **×8.5（高估）** |
| 加上 `mah_status='1'` | 4,551 + 平行 505 = 5,056 | ×1.11（含平行进口） |
| **再加「排除平行/未注册」（本脚本口径）** | **4,551** | 基准 |

> **一句话给页面**：拉脱维亚注册库有 40,600 个包装条目，但**真正在拉脱维亚上市的只有 4,551 个**；
> 33,919 个是「注册了、MAH 没在拉脱维亚上市」，290 个已移除，764 个已停售。

状态枚举落库（`product.status`）：

| 判定 | 落库值 | 行数 |
|---|---|---|
| 在售 | `active` | 4,551 |
| 注册有效但 MAH 未上市 | `unknown` | 34,995 |
| 有停售日期 | `discontinued` | 764 |
| 已从注册库移除 | `withdrawn` | 290 |

---

## 5. 平行进口 / 未注册药品：单独计数，**不计入 active**

| 程序类型（`authorisation_procedure`） | 全部行数 | 其中在售 | 处理 |
|---|---|---|---|
| `Paralēlais imports`（平行进口） | **733** | **0** | 单独计数；不入 active |
| `Paralēlā izplatīšana`（平行分销） | **62** | **0** | 单独计数；不入 active |
| `Nereģistrētas zāles`（未注册药品） | **12** | **0** | 单独计数；不入 active |
| 合计 | **795**（+12 未注册） | 0 | — |

- 平行进口行**都带 `parallel_importer` / `exp_country_lv`**（从哪里进口），说的是「从别国进口来卖」，**不是拉脱维亚自己的上市记录** → 若入库，`note` 必须写明来源国，且页面**不当作 LV 的上市产品**。
- 未注册药品（`RN…` 编号，如 `RN005`）是特殊/临时进口通道，`strength` 字段**全部为空**（12/12），更不该进 active。
- 交叉验证（`--self-check` 断言）：`active ∧ (平行 ∨ 未注册)` 的行数 = **0**。

---

## 6. 映射质量（干跑实测）

| 指标 | 数值 | 说明 |
|---|---|---|
| 成分映射 | **51,483 / 55,826 = 92.2%** | 3 轮调优：46.5% → 81.4% → 91.4% → **92.2%** |
| 规格解析 | **38,522 / 40,600 = 94.9%** | 未解析的 2,078 行主要是顺势疗法稀释度、`Nereģistrētas zāles`（strength 空） |
| ATC 覆盖 | **40,600 / 40,600 = 100.0%** | 全库唯一 ATC 零缺失的源；首字母分布 C 7,764 / N 7,162 / A 5,753 / B 5,373 / L 5,198 |
| 剂型非空 | **100%** | `form_base` 分布：tablet 25,366 / injection 7,221 / capsule 4,529 / liquid 1,176 / topical 1,038 / powder 482 / inhalation 329 |
| MAH 非空 | **100%** | `marketing_authorisation_holder` 无空值 |
| 名称折叠命中现有 `name_key` | 20,658 / 94,393 次名出现 = **21.9%** | 说明大部分拉语名是新的（预期内） |

**成分映射的做法（这是本任务新加的一块，值得复用）**：
拉脱维亚给的是**拉丁学名**（`Natrii chloridum`、`Perindoprili argininum`、`Acetylsalicylcum`），
库里 `substance.inn_en` 是英文 INN。中间加了一层**纯词形映射**（`latin_variants()`）：

1. 原样 → 2. 逐词英译（`_LATIN_WORD` 表：`natrii→sodium`、`chloridum→chloride`、`argininum→arginine`…）
3. 词尾规则：`-um` → 试 `-e` / 去尾 / `-a`（`levodopum→levodopa`、`amlodipinum→amlodipine`）；`-i` 属格去尾（`perindoprili→perindopril`）；`-as` → `-ate`；`-tanum` → `-tan`（沙坦类）
4. `Acidum X` 语序反转 → `X acid`
5. 去盐母体再试一遍

**只生成候选写法，命中与否仍由库里 `substance` 决定**——不做任何「这个拉丁名等于那个成分」的硬编码判断。

**剩余 4,343 次未命中（8.6%）的性质**：多数**不是解析问题，是 `substance` 表没有该 INN**。抽样核实：
`Acidum acetylsalicylicum`（库里无 Acetylsalicylic Acid 行）、`Colecalciferolum`（库里只有 `Equivalent: Colecalciferol`）、
`Benfotiaminum`（库里是西语 `Benfotiamina`）、`Soiae oleum raffinatum`（库里是 `Soya Oil`）。
→ 写库时按现有 `auto_merge_substances` / 人工补名流程处理，**不要**在 ETL 里硬映射。

---

## 7. 与 `region='EU'` 层去重（写库前必须知道）

| 项 | 数值 |
|---|---|
| LV 集中审批（`Eiropas centralizētā reģistrācijas procedūra`）行数 | 13,574 |
| 去掉包装段后的唯一 EU 药号（`EU/1/00/129/001` → `EU/1/00/129`） | **1,562** |
| 本库 `region='EU'` 唯一 `approval_id` | 2,019 |
| **交集（药号）** | **1,561** |
| 交集覆盖的 LV 行数 | **13,571** |
| LV 独有集中审批药号 | **1** |

**含义**：LV 的集中审批行**几乎全部**是 EU 层已有的药（只是包装级 + 拉语名 + 价格 + 可及性）。
- `coverage` 与页面必须分组（区域层 vs 国家层），**不要把同一支药算两次**。
- LV 对「新增唯一药」的贡献 ≈ 0；它的价值是**把 EU 层的 1,561 支药落到拉脱维亚的具体包装、价格与在售状态**，并给出拉语名。
- 458 个 EU 药号在 LV 注册库里没有（未在拉脱维亚上市）→ 页面「该国无记录」不能写成「该药不存在」。

---

## 8. 预测入库条数（写库窗口用；现在只是估算）

| 对象 | 预测 | 依据 |
|---|---|---|
| `product` | **40,600**（其中 `status='active'` 4,551） | 包装级一行 = 一条 product |
| `product_name` | ~94,393 条（拉语名 + 英文原名 + 简称） | `name_pairs()` 实测 |
| 新增 `name_key` | **约 1.0–1.1 万** | 唯一名 13,475，其中 21.9% 折叠后与现有 `name_key.norm` 相同 |
| `product_component` | **约 5.1 万行** | 成分 token 55,826 × 映射率 92.2% |
| `variant` 新增 | 待算（估 数百–1,500） | 按 (substance, salt) 组合去重 |
| `substance` 新增 | 少量（未映射里的「库内真没有」那部分） | 抽样见 §6 |
| `coverage` 新增 1 行 | `n_products=40600`, `n_active=4551` | 现库 `product` 479,193 → 写后 519,793（+8.5%） |

---

## 9. 站点接入清单（**只写方案，未改任何站点文件**）

### 9.1 `data/markets.json`（现有 11 条：US/GB/CA/AU/ES/MX/CN/TW/SG/HK/EU）

新增一条 LV，字段对齐现有条目：`code: "LV"`、`name`/`name_zh`、`currency: "EUR"`、`languages: ["lv"]`、
`coverage_note`（**必须写**）：「拉脱维亚注册库含 40,600 个包装条目，其中在售 4,551；注册 ≠ 在售」、
`status_vocab`（active/unknown/discontinued/withdrawn 四值映射见 §4.3）、`source_ids: ["zva_lv_register"]`。

### 9.2 `data/languages.json`（现有 en/es/zh/zh-Hant 启用；de/fr/it/nl/pl/pt 占位 disabled）

新增 `lv` 条目：`code: "lv"`、`native_name: "Latviešu"`、`ui_label: "LV"`、`script: "latin"`、`dir: "ltr"`、
`hreflang: "lv"`、`path: "lv/"`、`i18n_key_prefix: "lv"`、`default_country: "LV"`、`enabled: false`（先占位，随数据上线一起开）。
`planned_markets` 现为 `["DE","FR","IT","NL","PL","PT"]` → 建议改为 `["DE","FR","IT","NL","PL","PT","LV","CZ"]`（CZ 同理）。

### 9.3 I18N 工作量（**实测，不是估**）

`site/build.py` 的 `I18N` 字典实测：**`en` 237 键 / `es` 237 键 / `zh` 243 键**（`zh-Hant` 由生成器产出，不用手翻）。
→ **`lv` 需要 237 个键**（拉脱维亚语），加上 LV 专属文案（覆盖页口径、About 署名）约 **10–15 键**。
拉脱维亚语排版注意：长词（`apvalkotās tabletes`）、变音符号行高、`ā/ē/ī/ū` 在标题里的基线。

### 9.4 路由与页面

- `/lv/` 路由 + `hreflang="lv"` + 语言切换器（4 → 5 个启用语言）。
- 覆盖页新增 **LV 行**：`40,600` 条 / `4,551` 在售 / 每日更新 / CC0 / ZVA 署名。
- About「数据来源与覆盖」段（zh/en/es 三语，随站点语言）新增署名：
  「Zāļu valsts aģentūra (ZVA) · Latvijas Zāļu reģistrs · **CC0 1.0** · https://data.gov.lv/dati/lv/dataset/latvijas-zalu-registrs」
- 页面必须写的**三条口径**：
  1. 「包装级条目 40,600，在售 4,551；注册 ≠ 在售」
  2. 「拉语名 `medicine_name` 与英文原名 `original_name` 同属一条产品，不是两个产品」
  3. 「平行进口（795 行）与未注册药品（12 行）不计入在售」

### 9.5 体积预估（基于现站实测：`product` 479,193、`name_key` 202,739、`site/dist` 121,239 个 html、`core.json` 39.7 MB）

| 项 | 预估 |
|---|---|
| `core.json`（39.7 MB raw） | +40,600/479,193 ≈ **+3.4 MB raw（+8.5%）** |
| `detail-*.json`（合计 ≈ 42 MB） | 名字 +13,475/202,739 ≈ **+2.8 MB raw** |
| 页面数（121,239 html） | 新增名字页估 **+8,000–13,000 页**（现「name_key : html」≈ 1.67:1，按比例折算） |
| 文件数 | 现 ≥ 24,000 护栏仍成立；**构建时间会上升（页面 +8% 量级）** |

> 站点侧最大的一次性成本不是数据量，是 **`lv` 语言的 237 个键 + 1.3 万新名字页的构建时间**。

---

## 10. `docs/许可清单.md` 建议行（我未改该文件，交 Lead 统一写）

`zva_lv_register` 行，按现有表格格式：

| 列 | 内容 |
|---|---|
| 数据 / 用途 | 拉脱维亚 ZVA 国家药品注册库（`HumanProducts.xml.zip` 3.0 MB，每日；40,600 包装级条目；含拉/英双语名、规格、剂型、INN 拉丁名、ATC、MAH、状态、价格） |
| 许可结论 | ✅ **CC0 1.0**（`data.gov.lv` 数据集 `latvijas-zalu-registrs`：`license_title = "CC0 1.0"`、`license_url = https://creativecommons.org/publicdomain/zero/1.0/`；发布者 Zāļu valsts aģentūra） |
| 再发布 | **可以**（无署名义务、无 share-alike、可商用） |
| 义务 | 技术上无；本站惯例仍署名「Zāļu valsts aģentūra (ZVA) · Latvijas Zāļu reģistrs」+ 数据截止日 |
| 风险 | **低** |
| About | ❌ 待接入 |
| 证据 | `https://data.gov.lv/dati/lv/dataset/latvijas-zalu-registrs`；`https://dati.zva.gov.lv/zalu-registrs/export/HumanProducts.xml.zip`；`https://creativecommons.org/publicdomain/zero/1.0/`；评估 `reports/2026-11-12-lv-zalu-acquisition.md` |

---

## 11. 写库前置条件与回滚清单草案（**现在没执行**）

**前置**：
1. `db/migrate_country_lv.py`（照 `db/migrate_country_sg.py` / `_hk` / `_tw` 的既有迁移路径，重建 `product` 表把 `LV` 加进 `country` CHECK）——**这是写库的第一个闸门**，没它写不进去。
2. 手动备份 `data/drugs.db`（408.8 MB）到 `data/backups/`。
3. `etl/markets/lv.py` 补 `--apply` / `--rollback` / `--manifest`（照 `etl/ingest_eu.py` 三段式）。

**回滚清单**（按此顺序，全部限定 `LV-` 前缀或该 source）：

```sql
DELETE FROM product_component WHERE product_id LIKE 'LV-%';
DELETE FROM product_name      WHERE product_id LIKE 'LV-%';
DELETE FROM product           WHERE product_id LIKE 'LV-%';
DELETE FROM name_variant      WHERE source_id = 'zva_lv_register';
-- 只删「LV 新建且已无引用」的 name_key，避免误删其他市场在用的键
DELETE FROM name_key WHERE key_id NOT LIKE '%' AND key_id NOT IN (SELECT key_id FROM product_name)
   AND key_id NOT IN (SELECT key_id FROM name_variant)
   AND rowid IN (SELECT rowid FROM name_key WHERE key_id IN (
         SELECT key_id FROM name_key WHERE key_id NOT IN (SELECT key_id FROM product_name)));
DELETE FROM coverage WHERE country = 'LV';
DELETE FROM source   WHERE source_id = 'zva_lv_register';
```

> 实际执行时 `name_key` 的删除要用**写库时落盘的 manifest**（新增 key_id 清单）来做，别用「没有引用就删」这种启发式——`name_key` 是跨市场共享的。

---

## 12. 风险与缺口

1. **「注册 ≠ 在售」是最大的口径陷阱**（§4）。若站点沿用「有记录就算覆盖」的旧逻辑，LV 会把在售数字放大 8.5 倍，且与 ES/DE 等国的口径不可比。
2. **集中审批重复**：13,571 行与 EU 层同一支药。分组呈现没做好，用户会看到「同一支药在拉脱维亚出现 9 次」（9 个包装），误以为是不同药。
3. **ZIP 与状态表时间戳不同步**（06:40 vs 18:31 UTC）：同一天抓的两个文件可能差半天，页面写「每日更新」要加「两个文件可能不同时刻」。
4. **125 MB 解包 + 全量 XML 解析**：ETL 必须流式；本机 8 GB 内存下整棵读入会抖。干跑实测流式 7.9 s，可接受。
5. **成分映射剩 8.6%**：属 `substance` 表缺口（如 Acetylsalicylic Acid 库里没有），不是解析 bug。**不要在 ETL 里硬编码补名**，走既有 `auto_merge_substances` / 人工流程。
6. **新增 1.3 万名字页**会拉长构建时间；发布前要按 `docs/网站优化流程.md` 重跑首屏与体积回归。

---

## 13. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py etl/markets/lv.py --fetch        # 抓快照（3.0 MB + 1.4 MB）+ CC0 许可自证
& $py etl/markets/lv.py --self-check   # 17 项断言，应「全部通过」
Copy-Item data/drugs.db .tmp/lv-ingest/lv.db -Force
& $py etl/markets/lv.py --dry-run --db .tmp/lv-ingest/lv.db   # 只读开库；产物 .tmp/lv-ingest/lv_dry_run.json
```

实测输出（2026-11-12）：

```
  包装级条目 40,600 → 注册号 18,766 · 拉语名 6,261 · 英文原名 6,266 · 成分 token 2,227
  在售(active) 4,551 · 注册有效 39,545 · 已移除 290 · 已停售 764
  平行进口 795 行（其中若按同规则会算 active 0） · 未注册 12 行
  成分映射 51,483/55,826 = 92.2% · 规格解析 38,522/40,600 = 94.9% · ATC 覆盖 100.0%
  EU 去重：LV 集中审批 1,562 个药号，与 EU 层重合 1,561，LV 独有 1
```

---

## 14. 本次没做（明确列出）

- **没有写 `data/drugs.db`**（含副本：副本只被只读打开）。
- **没有改 `docs/许可清单.md`**（Lead 统一写；建议行见 §10）。
- **没有改** `data/markets.json` / `data/languages.json` / `site/build.py` / `site/dist`。
- **没有 commit / publish**。
- **没有写 `db/migrate_country_lv.py`**（不在本任务写权限内；写库窗口第一步）。
