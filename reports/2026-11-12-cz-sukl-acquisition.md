# 捷克 SÚKL DLP：取数 + ETL 干跑 + `cs` 接入清单（**不写库**）

- 日期：2026-11-12（北京时间窗口）
- 任务：**task-15** ・ 工位：phaseb-data
- 结论：**A 类落地可行**。许可条款允许商用/再分发；70,032 行产品、44 列，规格可解析 91.6%、
  剂型归一 99.997%、ATC 100%（7 位占 94.2%）、成分映射 90.9%；预计入库 **68,581 产品 / 94,066 组件 /
  6,434 商品名**。**只做到干跑**：未写 `data/drugs.db`、未改 `data/markets.json` / `data/languages.json` /
  `docs/许可清单.md` / `site/build.py`，未 commit。

---

## 0. 结论（先行）

1. **许可**：SÚKL 开放数据条款原文允许「šířit – kopírovat, distribuovat a sdělovat veřejnosti」「využívat
   a citovat」「**využívat komerčně**」，三个条件：署名 SÚKL（且不得暗示 SÚKL 背书）、不得改变或歪曲含义、
   再分发时附条款链接；**并明确排除第三方 IP 文档**（SPC/PIL/OBALY 包）→ 我们只取 CSV 事实表。
2. **快照**：`DLP20261027.zip` **9,551,535 B**（站点写 8,6 MB，实为 MiB），HTTP 200，
   `Last-Modified: Tue, 27 Oct 2026 12:37:12 GMT`，`sha256=7a1d8432…`；有效期
   `01.11.2026–30.11.2026`（`dlp_platnost.csv`）。ZIP 内 30 个成员，本工位只读 **13 张事实表**，
   说明书/文献表（`dlp_nazvydokumentu`/`dlp_splp`/`dlp_vpois`）**一律不读**（白名单在代码里强制）。
3. **字段质量高于现有市场**：产品表 **44 列**，商品名（`NAZEV`/`NAZEV_REG`）、规格（`SILA`）、剂型（`FORMA`
   → EDQM 码）、途径（`CESTA` → EDQM）、成分（`dlp_slozeni.S='L'` + `dlp_latky.NAZEV_EN`）、MAH（`DRZ`→
   `dlp_organizace`）、状态（`REG`→`dlp_stavyreg` 16 种码）、ATC（100% 有值）、包装量（`BALENI`）全在。
4. **干跑数字**（库副本、只读真库）：
   | 指标 | 数值 |
   |---|---|
   | 产品行 | **70,032**（状态：active 68,547 / withdrawn 6 / discontinued 28 / FSMP 排除 1,451） |
   | 商品名去重 / 注册名去重 | 7,317 / 6,445 |
   | `SILA` 可数值解析 | **91.6%**（64,140；空 3,500、顺势疗法等不可比 2,390、单位未识别 2） |
   | 剂型 → `form_base` | **70,030 / 70,032**（99.997%） |
   | 途径 → 英文名 | **69,869 / 69,869**（100%） |
   | ATC | 100% 有值；7 位成分级 **65,940（94.2%）**、组码 4,092 |
   | 活性成分行 / 覆盖产品 | **94,066 / 68,578**；含量可数值 94.0% |
   | 成分映射到库内 substance | **90.9%**（exact 78,009 + salt 3,296 + prefix 3,201 + synonym 961） |
   | 与 `region='EU'` 重合 | RC `EU/` 13,385 行（19.1%）；名字 1,630 个，其中 **1,516 已在 EU 层** |
   | 预测入库 | **产品 68,581 / 组件 94,066 / 商品名 6,434 / 新成分 1,082** |
5. **接入顺序有硬约束**（实测，不是推测）：`lib/markets.py` 要求 `source_id` **先**在 DB `source` 表登记，
   且 `tests/test_markets_registry.py` 要求「启用市场集合 = DB `product.country` 集合」→
   **DB 窗口与 `markets.json` 改动必须同批**；而 `cs` 语言与 CZ 市场互相依赖（见 §7.2），
   **只启用数据时 CZ 不要引用 `cs`**（否则 `validate()` 报「启用了未启用的语言 cs」）。
6. **今天没做**：写库、改注册表、改 `docs/许可清单.md`（Lead 统一写）、建站、发布。

---

## 1. 许可存档（`data/raw/cz_sukl_20261112/license/`）

| 文件 | URL | bytes | sha256（前 16） |
|---|---|---:|---|
| `podminky-uziti-otevrenych-dat.html` | https://opendata.sukl.gov.cz/podminky-uziti-otevrenych-dat | 15,310 | `4d32ece4e3d02564` |
| `dataset-dlp.html` | https://opendata.sukl.gov.cz/katalog-otevrenych-dat/databaze-lecivych-pripravku-dlp | 18,611 | `7164e149b75d17bf` |

### 1.1 条款原文（关键句，逐字抄自存档页）

> „Data … smí uživatel: **šířit – kopírovat, distribuovat a sdělovat veřejnosti**, • **využívat a citovat**,
> • **využívat komerčně**, a to při dodržení následujících podmínek: • **jako zdroj dat musí být uveden SÚKL**
> (nikoli však takovým způsobem, aby vznikl dojem, že SÚKL podporuje uživatele dat nebo způsob, jakým jsou
> otevřená data SÚKL využita), • otevřená data SÚKL **mohou být použita pouze takovým způsobem, který nijak
> nemění nebo neupravuje jejich význam/smysl**. … v případě dalšího šíření … **je uživatel povinen uvést znění
> těchto podmínek užití, nejlépe přímým odkazem na tuto webovou stránku**, • **tyto podmínky užití neplatí pro
> dokumenty, na něž se vztahují práva duševního vlastnictví třetích stran**.“

中文要点（我们据此执行）：

1. 可复制、可分发、可公开传播、**可商用**、可引用；
2. **必须注明来源是 SÚKL**，且不能让人误以为 SÚKL 为本站背书；
3. **不得改变或歪曲数据含义** → 我们的规格归一/成分拆分属「派生」，页面必须写「派生自 SÚKL 官方字段，
   原文与日期见来源链接」，**不覆盖原文**；
4. **再分发须附条款全文/直链**；
5. **第三方 IP 文档不在许可范围**（SPC/PIL/OBALY）→ 本 ETL 白名单强制排除，只读 CSV 事实表。

### 1.2 `docs/许可清单.md` CZ 行 —— **建议 diff（本工位未落盘，按 Lead 指示由你统一写）**

> 位置：§2「按市场」的 EU 段（`cima`/`eu_union_register` 附近，按现有排序放 ES 之后）。

```diff
 | 来源ID | 数据 / 用途 | 许可结论 | 再发布 | 义务 | 风险 | About | 证据 |
 |---|---|---|---|---|---|---|---|
+| `sukl_dlp` | SÚKL 药品数据库 DLP（`dlp_lecivepripravky` 70,032 行 × 44 列；含商品名/规格/剂型/ATC/MAH/状态/包装；月度 ZIP） | ✅ **SÚKL 开放数据使用条款**：明示允许复制/分发/公开传播/**商用**/引用 | 可以（只取 CSV 事实表） | ① 署名 SÚKL 且不得暗示背书；② 不得改变/歪曲含义（派生结果须注明「派生自官方字段」）；③ 再分发附条款链接；④ **SPC/PIL/OBALY 属第三方 IP，不得再发布** | 低-中（条款清晰，但「不得歪曲」要求页面写清派生口径） | ✅（SÚKL + 条款链接 + 数据日期） | https://opendata.sukl.gov.cz/podminky-uziti-otevrenych-dat |
```

同时建议在 §0 的「A 类」表格里把 CZ 从「A（待接入）」改为「A（已取数，干跑通过）」。

---

## 2. 数据快照

```powershell
& $py etl\markets\cz.py --fetch     # 本工位已跑，产物在 data/raw/cz_sukl_20261112/
```

| 项 | 值 |
|---|---|
| ZIP URL | `https://opendata.sukl.gov.cz/soubory/SOD20261027/DLP20261027.zip` |
| 字节 | **9,551,535**（站点页面写 8,6 MB） |
| HTTP | 200 · `application/octet-stream` · `Last-Modified: Tue, 27 Oct 2026 12:37:12 GMT` |
| sha256 | `7a1d8432c7f62afb76c7fd11a21dfbd8f1b896964af846b9c7661d2b22f4bc7b` |
| 字段说明 CSV | `DLP_datove_rozhrani20260701.csv` 13,356 B · sha256 `cd1f0d18…` · `Last-Modified: Tue, 25 Aug 2026 10:56:36 GMT` |
| 有效期 | `dlp_platnost.csv`：**01.11.2026 – 30.11.2026**（月度快照） |
| 元数据 | `data/raw/cz_sukl_20261112/fetch_meta.json`（每个文件的 URL/status/bytes/headers/sha256/retrieved_at） |

ZIP 内 **30 个成员**，本工位读 13 张事实表（白名单 `etl/markets/cz.py::ALLOWED_TABLES`）：

| 表 | 行数 | 列数 | 用途 |
|---|---:|---:|---|
| `dlp_lecivepripravky` | **70,032** | 44 | 产品主表 |
| `dlp_slozeni` | **811,168** | 7 | 成分-含量（`S=L` 活性 94,066 行） |
| `dlp_latky` | 21,587 | 8 | 成分码表（`NAZEV_INN` 拉丁 / `NAZEV_EN` 英文 / `NAZEV` 捷克） |
| `dlp_lecivelatky` | 3,390 | 5 | 药品成分（INN 优先名） |
| `dlp_formy` | 643 | 6 | 剂型 + EDQM 码 |
| `dlp_cesty` | 178 | 5 | 途径 + EDQM 码 |
| `dlp_obaly` | 83 | 4 | 包装类型码 |
| `dlp_stavyreg` | 16 | 2 | 注册状态码表 |
| `dlp_organizace` | 3,606 | 5 | MAH / 生产商 |
| `dlp_jednotky` | 73 | 2 | 单位 |
| `dlp_atc` | 6,999 | 4 | ATC 捷克/英文名 |
| `dlp_zeme` | 259 | 4 | 国家 |
| `dlp_platnost` | 1 | 2 | 快照有效期 |

**编码/格式（坑，已写进代码与自检）**：`CP1250`、分隔符 **`;`**、小数用**逗号**（`0,3MG`）。
按 UTF-8 硬读会静默出乱码药名（`LÉČIVA` → 替换字符）。

---

## 3. 字段 → 本库模型

### 3.1 44 列（`dlp_lecivepripravky`）

```
KOD_SUKL, H, NAZEV, SILA, FORMA, BALENI, CESTA, DOPLNEK, OBAL, DRZ, ZEMDRZ, AKT_DRZ, AKT_ZEM,
REG, V_PLATDO, NEOMEZ, UVADENIDO, IS_, ATC_WHO, RC, SDOV, SDOV_DOD, SDOV_ZEM, REG_PROC,
DDDAMNT_WHO, DDDUN_WHO, DDDP_WHO, ZDROJ_WHO, LL, VYDEJ, ZAV, DOPING, NARVLA, DODAVKY, EAN,
BRAILLOVO_PISMO, EXP, EXP_T, NAZEV_REG, MRP_CISLO, PRAVNI_ZAKLAD_REGISTRACE, OCHRANNY_PRVEK,
OMEZENI_PRESKRIPCE_SMP, TYP_LP
```

| 本库字段 | CZ 来源 | 说明 |
|---|---|---|
| `product.product_id` | `KOD_SUKL` | 7 位零填充码，稳定主键 |
| 商品名（`product_name` trade） | `NAZEV`（+`NAZEV_REG` 作变体名） | 7,317 / 6,445 去重 |
| `product_component.strength_value/unit` | `SILA` + `dlp_slozeni.AMNT/UN` | `SILA` 用于校验；结构化的 `AMNT` 更可靠 |
| 成分（`variant.substance_id`） | `dlp_slozeni.KOD_LATKY`（`S=L`）→ `dlp_latky.NAZEV_EN` | 复方天然多行，**不用拆 `LL` 字符串** |
| `product.dosage_form` / `form_base` | `FORMA` → `dlp_formy.NAZEV_EN` → `form_base_of()` | 643 码全覆盖 |
| `product.route` | `CESTA` → `dlp_cesty.NAZEV_EN` | 108 码 |
| `product.pack` | `BALENI`（+`OBAL`/`DOPLNEK` 描述） | 例：`10` / `24 II` |
| `product.mah` | `DRZ`/`AKT_DRZ` → `dlp_organizace.NAZEV` | 3,606 机构 |
| `product.status` | `REG` → 见 §3.2 | 16 种码 |
| `product.category` | `PRAVNI_ZAKLAD_REGISTRACE` + `TYP_LP` | 审批程序/特殊类型 |
| ATC | `ATC_WHO` | 100% 有值；7 位 94.2% |
| 包装日期线索 | `V_PLATDO`、`EXP` | 可用于 About 的「数据截至」 |

### 3.2 `REG` 16 种码 → `product.status`（本地映射，代码常量 `STATUS_MAP`）

| REG | 含义（捷克语摘要） | 本站 status |
|---|---|---|
| `R` | registrovaný léčivý přípravek（已注册） | active |
| `B` | 变更后可上市 6 个月 | active |
| `F` | 特定治疗程序 | active |
| `I` | 卫生部长特别措施 | active |
| `G` | 特定治疗程序结束 | discontinued |
| `K` / `M` | 集中审批决定暂停 / 注册或使用暂停 | discontinued |
| `C` / `N` / `Y` / `Z` / `ZS` / `U` / `ZI` / `J` | 注销 / 失效 / 未续期 / SUNSET / 豁免撤销 / 移出数据库 | withdrawn |
| `P` | 特殊医学用途食品（FSMP） | **excluded（不入库）** |

⚠️ **`DODAVKY`（近 6 个月是否供货）**：`1`=9,696、`0`=60,336 → **注册 ≠ 在售**。覆盖页必须按
`status=active` 报数并在 About 明示「在册≠在售」，不能把 70,032 直接当「在售」。

---

## 4. 映射率与未命中（可复核）

```powershell
& $py etl\markets\cz.py --dry-run --db .tmp\cz-ingest\drugs-copy.db
# 或自检：& $py etl\markets\cz.py --self-check   → 自检通过（exit 0）
```

### 4.1 规格 `SILA`

| 分类 | 行数 | 说明 |
|---|---:|---|
| numeric（可数值解析） | **64,140（91.6%）** | `500MG`、`0,3MG`、`300MCG`、`450MG/50MG`、`1MG/ML`、`20MG/G+10MG/G` |
| empty | 3,500（5.0%） | 无规格（多为疫苗/血液制品/敷料） |
| not_numeric | 2,390（3.4%） | 顺势疗法 `5CH`/`31CH-200CH`、`6K-10MK` 等（**不做数值解析**，也不当规格渲染） |
| unit_unmapped | 2 | 例：`0,02MG/0,05MG/DÁV`（`DÁV`=剂量的捷克语，需补单位词） |

规则（`split_strength()`，已在 `--self-check` 里逐条断言）：`+` 一律成分分隔；`/` **后面紧跟数字**
才算第二个成分（`450MG/50MG`），否则是分母（`1MG/ML` → 每 mL）；逗号小数先转点。

### 4.2 成分映射（`map_inn()` 四层）

| 层 | 行数 | 说明 |
|---|---:|---|
| exact | 78,009 | `NAZEV_EN` 归一后命中库 `substance.inn_en` |
| salt（迭代剥盐） | 3,296 | `EDOXABAN TOSILATE MONOHYDRATE` → `edoxaban` |
| prefix（`<INN>`+纯盐词尾巴） | 3,201 | `PERINDOPRIL TERT-BUTYLAMINE` → `perindopril` |
| synonym（INN/USAN 异名） | 961 | **`PARACETAMOL` → `acetaminophen`（676）、`ACETYLSALICYLIC ACID` → `aspirin`（189）** 等 |
| **命中率** | **90.9%** | 未命中 8,599 行 / 1,082 个不同名 |

未命中 top（多为配方性成分/疫苗株，本库没有也不该有）：
`SODIUM (S)-LACTATE SOLUTION` 309、`SOYA-BEAN OIL, REFINED` 138、`2,4-DICHLOROBENZYL ALCOHOL` 109、
`CHOLECALCIFEROL CONCENTRATE (POWDER FORM)` 109、`OLIVE OIL, REFINED` 108、`TRIGLYCERIDES, MEDIUM-CHAIN` 104、
`HUMAN NORMAL IMMUNOGLOBULIN FOR INTRAVENOUS ADMINISTRATION` 84、`COLECALCIFEROL` 80、脊髓灰质炎病毒 1/2 型各 80。

> **重要结论**：CZ 用的是 INN（欧洲名），本库主键 `inn_en` 混用 USAN（美国名）。
> 若直接「按未命中新增 substance」，会凭空造出 1,082 个重复成分（paracetamol/acetaminophen 就是例子）。
> 正确做法：**先把异名补进 `INN_SYNONYMS`（或更好的 WHO INN 异名表），再考虑新增**。
> 本轮已把实测 top 异名落地（16 对），先把 90.9% 拿到手；剩余 1,082 个里估计 <10% 是真新成分。

### 4.3 与 `region='EU'` 层的去重估计

| 指标 | 值 |
|---|---:|
| `RC` 以 `EU/` 开头（集中审批） | **13,385 行（19.1%）** |
| 这些行的商品名去重 | 1,630 |
| 其中名字已在 EU 层（`product.region='EU'` + trade 名） | **1,516（93%）** |
| 非 `EU/` 但名字在 EU 层 | 2 |

处理建议（写库时）：
- **不按 `RC` 前缀丢行**——集中审批药在 CZ 也有本地包装/规格，是合法的 `country='CZ'` 产品行；
- 但覆盖页/About 要说明「CZ 的 13,385 行里有 19.1% 是欧盟集中审批产品，与区域层同一活性物质」；
- 身份判定仍走「名称 × 剂型 × 规格 × 成分」，**不新增按注册号的去重规则**。

---

## 5. 干跑怎么跑的（不写库证据）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Copy-Item data\drugs.db .tmp\cz-ingest\drugs-copy.db -Force        # 409 MB 副本
& $py etl\markets\cz.py --self-check                               # exit 0
& $py etl\markets\cz.py --dry-run --db .tmp\cz-ingest\drugs-copy.db  # 只读开副本，写 .tmp/cz-ingest/cz_dry_run.json
```

- 脚本**没有 `--apply`/`--rollback`**（许可与流程双重原因；与 `etl/markets/nl.py` 同款约定）。
- 真库全程 `mode=ro`；副本只用于 `substance`/`product` 映射查询，**未写过任何 DB**。
- 产物：`.tmp/cz-ingest/cz_dry_run.json`（全部统计）+ `data/raw/cz_sukl_20261112/`（快照，不入 git）。
- 自检覆盖（`--self-check`，exit 0）：44 列金值、70,032 行金值、CP1250 解码可见变音符号、
  **变音符号折叠 7 例 + 15 字母覆盖断言**、规格解析 6 例 + 顺势疗法判负、ATC 三级粒度、
  剂型映射 3 例、以及「说明书/文献表不得进白名单」的许可红线断言。

### 5.1 捷克语变音符号归一（数据侧规则）

`fold_cs()`：NFKD → 去组合音标 → 补 `CZ_FOLD` 表。实测 NFKD 已能折掉大部分（`á č ď ě í ň ó ř š ť ú ů ý ž`），
显式表是兜底 + 可读性。断言样例：

| 原文 | 归一 |
|---|---|
| `LÉČIVA` | `LECIVA` |
| `ŘEBŘÍČKOVÁ NAŤ` | `REBRICKOVA NAT` |
| `ĎÁBEL` / `ŤUKAT` / `ŮČET` | `DABEL` / `TUKAT` / `UCET` |
| `ŽLUŤOUČKÝ` | `ZLUTOUCKY` |

> 站内 `lib/search.py` 已有重音折叠；这边的 `fold_cs()` 只用于**生成 name_key 的候选写法**
> （捷克语商品名带变音符号，去重/匹配前必须先折），不改原文、不改库。

---

## 6. 预测入库条数

| 项 | 数量 | 口径 |
|---|---:|---|
| products | **68,581** | 70,032 − FSMP/PZLÚ 1,451 |
| product_component | **94,066** | `dlp_slozeni.S='L'`，且挂在入库产品上的行 |
| 新 name_key（商品名） | **≈6,429** | 按归一后去重（`NAZEV`） |
| 商品名原文（trade 变体） | 6,434 | 保留大小写/变音符原文 |
| substance 新增（**上限**） | **1,082** | 未命中名；补异名后应显著下降 |
| 与 EU 层同名的商品名 | 1,516 | 不影响入库，只影响覆盖页口径说明 |

体量对比：现有库 479,193 产品 / 202,739 name_key → CZ 加入后约 **+14.3% 产品、+3.2% 名称**。

---

## 7. `cs` 站点接入清单（**只写方案，未改任何注册表/站点文件**）

### 7.1 注册表片段（建议落盘内容）

`data/markets.json` → `markets` 数组末尾（EU 之前插，`order=55`）：

```json
{
  "code": "CZ", "kind": "country", "parent": "EU", "group": "EUROPE",
  "name": {"en": "Czechia", "es": "Chequia", "zh": "捷克"},
  "i18n_key": "home.cz", "flag": "🇨🇿",
  "source_id": "sukl_dlp", "extra_source_ids": [],
  "default_lang": "en", "languages": ["en"],
  "enabled": true, "order": 55,
  "data_as_of": "2026-11-01",
  "notes": "SÚKL DLP 月度开放数据（44 列含规格/剂型/ATC/MAH/状态）；开放数据条款允许商用与再分发，须署名 SÚKL 且不得歪曲含义；SPC/PIL/OBALY 属第三方 IP，不入库；在册≠在售（DODAVKY 仅 13.8% 在供货）。"
}
```

`data/languages.json` → `languages` 数组（`cs` 先 disabled，等 UI 就绪）：

```json
{
  "code": "cs", "name": {"en": "Czech", "es": "Checo", "zh": "捷克语"},
  "native_name": "Čeština", "ui_label": "CS", "script": "latin", "dir": "ltr",
  "hreflang": "cs", "path": "cs/", "i18n_key_prefix": "cs",
  "default_country": "CZ", "region": "EU", "enabled": false, "order": 45,
  "notes": "捷克语；DLP 数据语言。UI 翻译未就绪前保持 disabled。"
}
```

### 7.2 顺序硬约束（**实测**，`.tmp/cz_registry_probe.py`）

| 阶段 | 内容 | `validate()` |
|---|---|---|
| 现状 ① | 只加 CZ 市场 | ❌ `source_id=sukl_dlp 不在 DB source 表` |
| 现状 ② | 只加 cs 语言 | ❌ `default_country=CZ 既不在 markets 也不在 planned_markets` |
| 阶段 1 | CZ disabled + cs disabled（成对改两个 JSON） | ✅ OK |
| 阶段 2a | CZ enabled，但 `languages` 仍含 disabled 的 `cs` | ❌ `启用了未启用的语言 cs` |
| **阶段 2a′** | **CZ enabled 且 `languages: ["en"]`（不引用 cs）** | ✅ **OK ← 数据窗口用这个** |
| 阶段 2b | CZ + cs 都 enabled（成对改） | ✅ OK |
| 阶段 2c | 再把 `CZ.default_lang` 改 `cs`、`languages: ["cs","en"]` | ✅ OK |

结论：
1. **`sukl_dlp` 必须先在 DB `source` 表登记**（由写库窗口的 ingest 完成）→ 注册表改动**不能早于**写库；
2. **CZ 与 cs 是循环依赖**（语言要求市场的 `languages` 含它；市场要求语言已注册）→ `lib/markets.py` 的
   `with_market/with_language` 增量 API 表达不了，**必须一次改两个 JSON**；
3. **「先获取数据，等 UI 改完再上线」= 阶段 2a′**：CZ 启用、`languages: ["en"]`、默认英文，
   完全不碰 `cs`；`cs` 作为独立任务在 UI 就绪后一次性加（阶段 2b/2c）。

### 7.3 需要同步改的测试（否则 CI 红）

| 测试 | 现状断言 | 需改 |
|---|---|---|
| `tests/test_markets_registry.py::test_registered_market_set` | 市场集合 = 10 国 + EU | 加 `CZ`；`country_order` 加 `CZ` |
| `SITE_COUNTRY_I18N`（文件顶部常量） | `{US,GB,CN,ES,MX,AU,CA,TW,SG,HK}` | 加 `CZ` |
| `test_registered_language_set` | 语言集合 = `{en,es,zh,zh-Hant,de,fr,it,nl,pl,pt}` | 加 `cs` |
| `test_cli_json_output` | `markets == 11`、`languages == 10` | 12 / 11 |
| `test_enabled_markets_match_db_countries` | `country_order == DB product.country` | **与写库同批**（否则必红） |
| `test_i18n_keys_unique_and_match_existing_site_keys` | 启用市场的 `i18n_key` 必须存在 | `site/build.py` I18N 加 `home.cz` |

### 7.4 站点侧工作量（估算）

| 项 | 工作量 / 体积 | 备注 |
|---|---|---|
| `I18N["cs"]` 字典 | **553 个键**（实测 `i18n.en.js` 去重键数）· **1.5–2 人日** | `_assert_i18n_complete()` 缺一个键就构建失败；还要按捷克语复数/格变化复核数字文案 |
| `assets/i18n.cs.js` | ≈ 60 KB raw（比 en 63 KB 略小） | 构建期自动生成 |
| `/cs/` 路由 + hreflang | `_write_with_copies()` + `LANGS` 扩一项 | 静态页 ×~30 份副本 ≈ +1 MB |
| 名字页 | **+6,429 页**（每页 ≈3.4 KB raw） | **≈ +22 MB raw / +7 MB gzip** |
| 检索索引 `core.json` | +6.4k 条目 | ≈ +1.4 MB raw / +0.3 MB gzip |
| 明细桶 `detail-*.json` | CZ 行进桶（每 key 上限 12 行） | 预计 +2–4 MB raw |
| 覆盖页 / About | CZ 行 + 署名 + 口径 | 文案三语同步（zh/en/es）+ cs |
| **合计体积** | **≈ +25–30 MB raw / +8–10 MB gzip** | 在现有 `verify_live` 护栏内（gzip 2.5–12 MB 的总量里 +0.3 MB 级） |

> 注：`tests/trilingual/run_tests.py` 目前只跑 en/es/zh；`cs` 上线后要决定是否纳入
> （建议先按「数据市场」上，语言后置，避免一次改三件大事）。

### 7.5 About 页署名文案（草稿，供 site-ui 用）

> 捷克：SÚKL 药品数据库（DLP），月度开放数据，数据截至 2026-11-01。
> 依 SÚKL 开放数据使用条款使用（允许商用与再分发）；**来源：SÚKL**，
> 条款：https://opendata.sukl.gov.cz/podminky-uziti-otevrenych-dat 。
> 本站的规格归一与成分拆分**派生自**官方字段，原文与日期见每条记录的来源链接；
> 我们不改写、不覆盖原文。SPC/PIL/包装说明（第三方知识产权文档）未收录。
> 在册 ≠ 在售：DLP 的 `DODAVKY` 显示仅约 13.8% 的记录近 6 个月有供货。

---

## 8. 回滚清单草案（给未来的 DB 写库窗口）

1. **备份**（AGENTS §4：单独跑 ingest 不自动备份）：
   ```powershell
   $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
   Copy-Item data\drugs.db "data\backups\drugs-$stamp.db"
   ```
2. **写入范围**：`source`（`sukl_dlp` 一行）+ `product`（68,581）+ `product_component`（94,066）+
   `name_key`/`name_variant`/`product_name` + 可能的 `substance`（新成分）。**只有 `country='CZ'` 的行**。
3. **单点回滚（推荐）**：按 `source_id` 反删，外键级联清掉组件/名称：
   ```sql
   DELETE FROM product_component WHERE product_id IN
     (SELECT product_id FROM product WHERE country='CZ' AND source_id='sukl_dlp');
   DELETE FROM product_name WHERE product_id IN
     (SELECT product_id FROM product WHERE country='CZ' AND source_id='sukl_dlp');
   DELETE FROM product WHERE country='CZ' AND source_id='sukl_dlp';
   -- substance 若本轮新增：按 manifest 的 substance_id 列表逐个删（先确认没有别的市场引用）
   ```
4. **撤销 manifest**：与 `etl/ingest_eu.py` 三段式一致——apply 时写
   `.tmp/cz-ingest/undo_<UTC>.json`（`{source_id, data_as_of, zip_sha256, products:[...], substances_new:[...]}`），
   `--rollback` 用它对拍删除并校验「删掉的行数 = 写入行数」。
5. **核对项**：`PRAGMA integrity_check`、`PRAGMA foreign_key_check`、`db/check_data.py` 前后 diff
   （预期只有 CZ 相关表与 coverage 的 CZ 行变化）、`tests/test_markets_registry.py` 全绿。
6. **注册表回滚**：`data/markets.json` / `data/languages.json` 与写库同批提交，回滚时一起 revert。

---

## 9. 未做 / 风险 / 待决策

| # | 事项 | 状态 |
|---|---|---|
| 1 | 写 `data/drugs.db`（`--apply`） | ❌ 未做，脚本**没有 apply 路径**；等 Lead 开窗口 |
| 2 | `docs/许可清单.md` CZ 行 | ❌ 未落盘（按 Lead 指示），§1.2 给了可直接套的 diff |
| 3 | `data/markets.json` / `data/languages.json` | ❌ 未改；§7.1 给了片段 + §7.2 给了顺序证据 |
| 4 | 1,082 个未命中成分 | ⚠️ 其中多数是同物异名/配方成分；**不要直接新增**，先扩 `INN_SYNONYMS`（或接 WHO INN 异名表） |
| 5 | 顺势疗法 2,390 行 | ⚠️ `SILA` 不可数值解析；入库时 `strength_value` 留空并加 note，**不要**按 0 或猜测填 |
| 6 | `DODAVKY` 在售口径 | ⚠️ 覆盖页需按 active 报数 + About 说明；CST 窗口里要同步 README/About 口径 |
| 7 | 疫苗/血液制品/造影剂 | ⚠️ 规格单位是 `IU`/`MBQ`/`MMOL` 等，`norm_unit` 已能识别 `IU`；`MBQ` 本次归为 numeric（需确认是否要在页面展示） |
| 8 | `cs` UI（553 键） | ⏸ 独立任务；建议数据先上、语言后置（阶段 2a′） |
| 9 | 逐月更新 | ⏸ 需一个 `--fetch` 月度任务 + 变更 diff（`dlp_zruseneregistrace` 可作状态变更来源，本轮未用） |

---

## 10. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'; [Console]::OutputEncoding=[Text.Encoding]::UTF8

& $py etl\markets\cz.py --fetch                                  # 抓快照（写 data/raw）
& $py etl\markets\cz.py --self-check                             # 离线断言，exit 0
Copy-Item data\drugs.db .tmp\cz-ingest\drugs-copy.db -Force      # 库副本
& $py etl\markets\cz.py --dry-run --db .tmp\cz-ingest\drugs-copy.db
& $py .tmp\cz_eu_overlap.py                                      # 与 EU 层重合
& $py .tmp\cz_registry_probe.py                                  # 注册表顺序约束
```

### 附：本工位产物

| 文件 | 说明 |
|---|---|
| `etl/markets/cz.py` | **新增**：`--fetch` / `--dry-run` / `--self-check`；无 apply |
| `data/raw/cz_sukl_20261112/` | 快照（ZIP + 字段说明 + 许可页 + `fetch_meta.json`），**不入 git** |
| `.tmp/cz-ingest/cz_dry_run.json` | 干跑全部统计 |
| `.tmp/cz-ingest/drugs-copy.db` | 库副本（409 MB）——**已删**，§10 的一条 `Copy-Item` 可再生 |
| `.tmp/cz_eu_overlap.py` / `.tmp/cz_registry_probe.py` | EU 去重估计 / 注册表顺序验证 |
| `reports/2026-11-12-cz-sukl-acquisition.md` | 本报告 |
