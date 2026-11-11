# 法国 BDPM 数据获取 + ETL dry-run + fr 站点接入清单（task-14）

> 日期：2026-11-12（北京时间）· 工位：page-slim · 任务：`task-14`
> 结论先行：**许可 = ✅ A 类（Licence Ouverte 2.0，书面条款允许再分发）**；快照 4 个整库文件 /
> **11,248,467 B** / 15,799 制剂 + 32,449 成分行 + 20,908 包装 + 10,614 仿制药组；
> dry-run（**只读库副本**）预测入库 **15,799 产品 / 19,171 组件 / 11,658 新 name_key / 0 新 substance**。
> **没有写 `data/drugs.db`、没有改 `site/build.py`、没有改 markets/languages 注册表、没有 commit**；
> `etl/markets/fr.py` 刻意**不提供 `--apply`**，等站点 fr 接入（§7）后再开写库窗口。
>
> 并行工位提示：`docs/许可清单.md`（§2.11 已含 `bdpm_fr` 行）与 `site/build.py` 在工作区里有
> **别人的在途修改**（`git status` 可见）；本工位没有触碰这两个文件，只在 §1.4 给校准建议。

---

## 0. 交付物与复现命令

| 产物 | 路径 | 说明 |
|---|---|---|
| ETL 骨架（fetch / dry-run / self-check） | `etl/markets/fr.py` | 无 `--apply` / `--rollback`（与 `nl.py` 同款纪律）；dry-run 拒绝真库 |
| 许可证据 | `data/raw/fr_bdpm_20261112/license/` | 下载页 HTML + 条款正文 + data.gouv.fr 数据集 JSON + Licence Ouverte 原文 |
| 快照 | `data/raw/fr_bdpm_20261112/*.txt` + `fetch_meta.json` | 不入 git（`data/raw/` 按 AGENTS §9） |
| dry-run 结果 | `.tmp/fr-ingest/fr_dry_run.json`、`fr_samples.json` | 只读库副本 `.tmp/fr-ingest/drugs_fr_copy.db` |
| 许可清单状态 | 见本文 §1.4 | **未改 `docs/许可清单.md`**（§2.11 已有 `bdpm_fr` 行，Lead/扫描工位写入；本工位只给 3 处校准建议） |

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/markets/fr.py --fetch          # 抓许可证据 + 4 个整库文件（可复用缓存）
& $py etl/markets/fr.py --self-check     # 离线断言：许可 / 列数 / 编码 / 状态 / 剂量 / 成分候选 / 无 --apply
& $py etl/markets/fr.py --prepare-copy   # data/drugs.db → .tmp/fr-ingest/drugs_fr_copy.db（只读复制）
& $py etl/markets/fr.py --dry-run        # 默认模式；只读库副本，拒绝在真库上跑
```

---

## 1. 许可（A 类，证据已存档）

### 1.1 结论

- **数据方**：ANSM / HAS / CNAM（BDPM 由 ANSM 维护，`base-donnees-publique.medicaments.gouv.fr`）。
- **条款**：下载页自带「Termes du contrat de licence」，依《社会保障法典》L.161-40-1 条
  （2011-2012 号法第 8 条修订）以「libre et gratuit」方式提供整库文件。
- **许可类型**：Licence Ouverte / Open Licence 2.0（Etalab）；
  data.gouv.fr 数据集 `53698f50a3a729239d2036f5` 元数据 `license = fr-lo`。
- **判定：✅ 可再发布**（可存结构化字段、可展示派生结果）；义务见 §1.2。
  与 NL（🟡「许可未知、不入库」）、IE（🔴 明确禁止再分发）形成对照。

### 1.2 条款原文关键句（逐字摘自 `license/bdpm_licence_terms.txt`）

> « Vous êtes libres de : **Reproduire, diffuser, redistribuer et exploiter les données** »
>
> « À condition de : **Ne pas altérer les données**, ne pas en dénaturer leur sens,
> **mentionner impérativement la source** de ces données (base de données publique des médicaments
> http://base-donnees-publique.medicaments.gouv.fr) **et la date de leur mise à jour**
> (Article 12 de la loi n°78-753 du 17 juillet 1978 - loi CADA). »
>
> « cette mention ne confère aucun caractère officiel à la réutilisation de ces données, et
> **ne doit pas suggérer une quelconque reconnaissance ou caution du "Réutilisateur" par l'ANSM,
> la HAS ou l'UNCAM**. »

义务落地：① 不篡改数据（只存事实字段，不改数值/不重写名称）；② 注明来源（BDPM 官方 URL）；
③ 注明**数据更新日期**（本次 = 2026-11-03）；④ 不暗示 ANSM/HAS/UNCAM 背书。

### 1.3 证据文件（`data/raw/fr_bdpm_20261112/license/`）

| 文件 | 字节 | 内容 |
|---|---|---|
| `bdpm_telechargement.html` | 48,732 | 下载页原文（HTTP 200，`text/html; charset=UTF-8`） |
| `bdpm_telechargement.txt` | 7,269 | 页面正文纯文本（去掉 script/style 后） |
| `bdpm_licence_terms.txt` | 4,201 | 条款段原文（`Termes du contrat de licence` 起到「数据格式说明」前） |
| `data_gouv_dataset.json` | 5,652 | data.gouv.fr 数据集元数据：`license=fr-lo`、`last_update=2026-11-10T23:19:07Z`、组织=Ministère des Solidarités et de la Santé |
| `licence_ouverte_2.0.html` / `.txt` | 178,986 / 97,397 | Etalab Licence Ouverte 原文（`https://www.etalab.gouv.fr/licence-ouverte-open-licence/`；data.gouv.fr `/fr/licences` 另存一份） |

`fetch_meta.json` 记录每个 URL 的 HTTP 状态 / Content-Type / 响应头 / 字节 / sha256 / 抓取时间。
**如实记录**：BDPM 文件响应没有 `Last-Modified` / `ETag`（服务端未给），数据新鲜度只能以下载页
「Dernière mise à jour le **03/11/2026**」为准；`self-check` 会校验这一日期有值。

### 1.4 `docs/许可清单.md` FR 行：**已存在**（§2.11，Lead/扫描工位写入），以下是实测校准建议

> 本工位按要求**没有改 `docs/许可清单.md`**。检查时 §2.11 已有 `bdpm_fr` 行（与 `sukl_cz_dlp` /
> `zva_lv_register` 同一批写入），结论与本次实测一致：**✅ 可再发布**；实测数字
> 15,799 制剂 / 20,908 包装 / 32,449 成分行**完全吻合**。建议只补三处（Lead 决定是否改）：

1. **补数据更新日期**：`… + 必须署名来源与更新日期（本次 = **2026-11-03**，下载页「Dernière mise à jour le 03/11/2026」）`。
   —— 这是条款义务（loi CADA 第 12 条），也是 About 必须写的字段。
2. **补证据路径**：证据栏追加 `；证据 data/raw/fr_bdpm_20261112/license/`（含条款正文与 data.gouv.fr 数据集 JSON）。
3. **「月度全量 11 文件」措辞**：页面上确实提供多个整库文件；本工位确认并取用其中 4 个
   （`CIS_bdpm` / `CIS_COMPO_bdpm` / `CIS_CIP_bdpm` / `CIS_GENER_bdpm`），其余文件**未下载**；
   建议写成「整库文件（本次取 4 个：CIS/COMPO/CIP/GENER）」以避免读者以为已取全 11 个。

（`license` 字段口径：data.gouv.fr 数据集 `53698f50a3a729239d2036f5` 的 `license=fr-lo` =
Licence Ouverte 2.0；与清单里的「Licence Ouverte / etalab-2.0」同义，无需改。）

配套（About 文案草案，§7.5 给三/五语落点）：

> 数据来源：Base de données publique des médicaments（BDPM），ANSM / Ministère de la Santé，
> 许可 **Licence Ouverte 2.0**，数据更新日期 **2026-11-03**。本站只存储结构化事实字段，
> 不转载说明书；不暗示 ANSM/HAS/UNCAM 对本站的认可或背书。

---

## 2. 数据快照（`data/raw/fr_bdpm_20261112/`，不入 git）

| 文件 | URL | 字节 | 行数 | 编码 | 列数 | sha256（前 16） |
|---|---|---|---|---|---|---|
| `CIS_bdpm.txt` | `…/download/file/CIS_bdpm.txt` | 3,149,903 | 15,799 | **cp1252** | **12** | `df02c528b92b1ce3…` |
| `CIS_COMPO_bdpm.txt` | 同上 | 2,741,312 | 32,449 | **cp1252** | **8** | `8684fa036f76e845…` |
| `CIS_CIP_bdpm.txt` | 同上 | 4,151,945 | 20,908 | **utf-8** | **13** | `2a222047e75724e3…` |
| `CIS_GENER_bdpm.txt` | 同上 | 1,205,307 | 10,614 | **cp1252** | **5** | `22db002d5a3297e9…` |

合计 **11,248,467 B**，HTTP 200、`Content-Type: application/octet-stream`、无 `Last-Modified`/`ETag`。
完整 sha256 / 响应头 / 抓取时间见 `fetch_meta.json`。

**与旧文档的差异（重要）**：现行文件的列数与 2023 版 readme 不同（旧 readme 是 23/9/9/4，
实测 **12/8/13/5**）。本 ETL 一律**按列序写死映射 + 每行列数校验**（异常行单独计数、不静默串列），
`self-check` 会断言列数；BDPM 若再改格式，`self-check` 会先红，不会静默污染。

### 2.1 字段映射（实测列序）

`CIS_bdpm.txt`（12 列）：
`cis · denomination · forme · voies · statut_autorisation · procedure · etat_commercialisation ·
date_amm · dispo_status · eu_number · titulaires · surveillance_renforcee`
- `col9 = 欧盟号`（`EU/1/01/185`），只有「Procédure centralisée」的 **2,261 行**有值 → 见 §5。
- `col8 = 供应预警`（`Warning disponibilité` 2,219 / `Alerte` 20），不是规格。

`CIS_COMPO_bdpm.txt`（8 列）：`cis · forme · code_substance · designation · dosage ·
reference_dosage · nature · num_liaison`；`nature ∈ {SA 26,951, FT 5,498}`（FT = 治疗分组分，本轮不入 component）。

`CIS_CIP_bdpm.txt`（13 列）：`cis · cip7 · libelle · statut_presentation · etat_commercialisation ·
date_declaration · cip13 · agrement_collectivites · taux_remboursement · prix · prix_honoraires ·
frais · note_remboursement`（价格/报销 5 列**不入库**，只记存在）。

`CIS_GENER_bdpm.txt`（5 列）：`groupe · libelle_groupe · cis · type · ordre`；
`type` 取值为 `1`（6,680 行）/`0`（1,356）/`4`（50）/`2`（12）——**0=princeps 的口径未在官方文件里确认**，
本轮只当「同组事实」线索，不做替代推荐；`ordre` 语义未确认，不使用。

---

## 3. ETL（`etl/markets/fr.py`）与纪律

- **CLI**：`--fetch` / `--prepare-copy` / `--dry-run`（默认）/ `--self-check`；**没有 `--apply` / `--rollback`**。
  `self-check` 用探针断言 `--apply` 会被 argparse 拒绝、且 `--dry-run` 默认库是 `.tmp/` 副本。
- **库纪律**：dry-run 显式拒绝 `data/drugs.db`（真库）；默认打开 `.tmp/fr-ingest/drugs_fr_copy.db`
  （`mode=ro`）。本次运行前后真库未变：字节 428,699,648 / mtime `2026-11-10 8:35:11` /
  sha256 `972e17e997964ad2…`。**未跑 `check_data.py`**（没有写库，无需体检；写库窗口再跑 before/after）。
- **复用**（不另起一套）：`normalize_name.normalize()` 抽名称侧规格；`normalize_strength.norm_unit()`
  规范单位；`ingest_openfda_ndc.form_base_of()/slug()` 归一剂型与 id；`ingest_sg_hsa.SgMapper`
  做 substance 四级匹配；`ingest_ema_medicines._variant_resolver()` 解析 variant。
- **新增的只有法语层**：法语盐名/水合物词表、法语→英语词序与拼写（`-ique→-ic`、`f↔ph`、
  `acide X`→`X acid`、`CHLORURE DE X`→`X chloride`）、法语 INN 同义词（`PARACÉTAMOL→acetaminophen`、
  `ACIDE ACÉTYLSALICYLIQUE→aspirin`…）、WHO INN 法语名桥接（`data/who_inn_names.csv` 的
  `inn_fr → inn_en`，1,737 行，命中后仍由库里 `substance` 决定）。
- **不新增 substance**：映射不上的成分空着（产品照写名称/剂型/状态），候选缺口见 §4.4。

---

## 4. dry-run 结果（`.tmp/fr-ingest/fr_dry_run.json`）

运行环境：库副本 428,699,648 B；解析 + 映射 + 重叠估计共 **3.4 s**；控制台摘要与 JSON 一致。

### 4.1 体量与状态

| 指标 | 数值 |
|---|---|
| 制剂（CIS） | **15,799** |
| 成分行（COMPO） | 32,449，其中 SA **26,951** / FT **5,498** |
| 包装（CIP，能对上 CIS） | **20,351**（孤儿 557 行 / 478 个 CIS，见 §4.5） |
| 仿制药组行 | 10,614（1,492 组，覆盖 8,098 个产品） |
| 列数异常行 | 0（4 个文件全部行 = 固定列数） |
| 状态 `active / discontinued / withdrawn / unknown` | **13,559 / 1,217 / 1,017 / 6** |
| 授权程序 | nationale 7,173 · décentralisée 3,214 · **centralisée 2,261** · reconnaissance mutuelle 1,501 · homéo 1,323 · 其余（含**平行进口 255**） |
| 上市状态 | Commercialisée 13,559 · Non commercialisée 2,240 |

状态映射规则（页面文案要对）：`Autorisation active + Commercialisée → active`；
`Autorisation active + Non commercialisée → discontinued`（**有授权、不在售**，不是 withdrawn）；
`abrogée / retirée / archivée → withdrawn`；其余 `unknown`（6 行，不猜）。

### 4.2 剂型 / 途径 / 包装

- 剂型原文 **369 种**；`form_base` 认出 **15,232 / 15,799 = 96.4%**
  （top：tablet 6,979 · injection 3,063 · powder 1,904 · capsule 1,482 · liquid 931 · other 567）。
- 给药途径 69 种（orale 10,718 · intraveineuse 2,092 · cutanée 1,697 · sublinguale 1,529 · sous-cutanée 968）。
- 包装：20,351 个 presentation 挂在 14,149 个 CIS 上（1,650 个 CIS 无包装行）；多包装产品 3,687。

### 4.3 剂量（规格）

- 来源：`CIS_COMPO` 的 `dosage` + `référence de dosage`（不换算、不猜密度）。
- SA 行 26,951：**有数值剂量 16,273（60.4%）** · dosage 空 2,764 · 解析不出 7,914。
  - 「解析不出」里约 **7,500 行是顺势疗法稀释度**（`2CH à 30CH et 4DH à 60DH`），不是数值剂量。
  - **非顺势口径**：16,273 /（26,951 − 8,195 顺势 SA 行）= **86.7%**；若再排除 2,764 个空 dosage →
    **97.5%**。剩余 413 条是非数值写法（`qsp 300 IR`、`≥ 20 UI`、`2,2 microgrammes de polyoside…`、
    `31,25 × 10^9 bactéries`），**保持 NULL**。
- 挂到 component 上：**14,276 / 19,171（74.5%）**；单位 top：mg 11,383 · g 3,187 · mL 348 · IU 339 ·
  unit 74 · MBq 39 · % 26 · mcg 15；浓度分母 per_volume_unit：mL 4,394 · g 957 · mg 33 · L 11。
- **剂量基准（不可自动折算）**：BDPM 不提供「盐型 / 游离碱」基准字段；`variant.strength_basis`
  只能 `unknown`。COMPO 里 `FT`（治疗分组分）行是**分组/换算说明**，本轮**不进** `product_component`，
  避免把「分组分剂量」写成独立成分。页面必须继续写「不判断两种药能否互换」。

### 4.4 成分映射（法语 → INN）

| 口径 | 映射 / 总数 | 比例 |
|---|---|---|
| 全部 token（含顺势） | 19,197 / 26,974 | 71.2% |
| **非顺势 token** | **16,816 / 18,748** | **89.7%** |
| 顺势 token（`… HOMÉOPATHIQUES`，无 INN） | 8,226 行；其中 2,381 命中、**5,845 不映射**（合法缺口） | 不做硬映射 |
| 唯一未映射写法 | 1,524 种 | — |

- 产品级：全部成分映射上 **13,295**；部分映射 **583**；一个都没映射 **1,919**（另有 19 个映射上但
  variant 未解析）→ **无 component 产品合计 1,938**（产品照写名称/剂型/状态，见 §6）。
- 主要缺口（合法缺口）：顺势成分（BRYONIA/NUX VOMICA…）、疫苗/生物制品（病毒、类毒素、凝血因子）、
  植物油/辅料型成分（HUILE DE SOJA RAFFINÉE、VASELINE）、法国专有复方（`SOLUTION DE DIGLUCONATE
  DE CHLORHEXIDINE`、`OXOMÉMAZINE`、`MÉTOPIMAZINE`、`THIOCOLCHICOSIDE` 库里没有对应 substance）。
- **ATC：BDPM 无 ATC 列** → 不新增 ATC；站上成分页的 ATC 只能沿用库内已有 `substance.atc`。

### 4.5 数据质量发现（写页面/写库都要知道）

1. **欧盟号**：2,261 个 CIS 带 `EU/…` 号（1,074 个不同号），与 `region='EU'` 层可**等值对齐**（§5）。
2. **平行进口**：255 个 CIS 是 `Autorisation d'importation parallèle`（同一产品由不同进口商注册），
   会让同名同成分出现多条 CIS（如 `PERMIXON 160 mg, gélule` 14 条、`COVERAM 10 mg/10 mg, comprimé` 4 条）。
   **不合并**（CIS 是注册事实），站上按 name_key 出候选集即可（§1.1 商品名不是主键）。
3. **同身份多 CIS**：2,456 组 / 6,540 行（最大 15 条/组）；换成「身份」口径 = **11,717 组**。
4. **CIP 孤儿**：557 行包装对应的 CIS 已不在 `CIS_bdpm`（旧注册残留）→ **不入库**。
5. **无成分产品**：**1,938 个**（1,919 个成分全未映射 + 19 个 variant 未解析；顺势为主）→ 只能进
   「名称层」，没有 `product_component`，不会出现在成分页/碰撞视图；是否入库要产品决策（§8）。
6. 2 个制剂没有成分行、1,650 个制剂没有包装行（BDPM 本身缺，不补）。

---

## 5. 与 `region='EU'` 层去重估计（**注册号精确对齐，不是模糊匹配**）

`CIS_bdpm` 第 9 列就是欧盟号（`EU/1/xx/xxx`），与 EU 层 `product.approval_id` 同一写法：

| 指标 | 数值 |
|---|---|
| EU 层产品 / 有 approval_id | 2,095 / 2,019 |
| FR 带欧盟号的 CIS | **2,261 行 / 1,074 个号** |
| FR 欧盟号命中 EU 层 | **1,072 个号（2,258 行，99.8%）** |
| FR 有、EU 层没有的号 | 3 个（`EU/1/15/1124`、`EU/1/17/1235/`（数据里带尾斜杠）、`EU/1/24/180`） |
| EU 层有、FR 没有的号 | **944 个**（EU 集中审批但 BDPM 未收录 → 多为法国未上市/已撤，页面别写「EU 有=法国有」） |
| 名称归一相同（辅助口径） | 2 个（名称+成分 0 个） |

**结论**：名称匹配在 FR 基本无效（BDPM 商品名自带规格/剂型，如 `ABILIFY 10 mg, comprimé`，
EU 层只有 `Abilify`），**必须用欧盟号**；EU 层与 FR 层是两层（授权记录 vs 上市记录），
**都保留、不合并、不去重入库**。

---

## 6. 预测入库条数（仅预测，本脚本无写库路径）

| 表 | 预测 | 说明 |
|---|---|---|
| `product` | **15,799** | 一行 = 一个 CIS（`FR-<CIS>`），与 ES `ES-<nregistro>` 同构；`country='FR'`、`region=NULL` |
| `product_component` | **19,171** | 其中带数值剂量 14,276；`FT` 行不计；**26 个成分映射上了但 variant 未解析**（不写 component） |
| `product_name` | **15,799** | `name_type='trade'`，一行一名 |
| `name_key` | 新建 **11,658** / 复用 16 | 全部可搜名 11,674 |
| `name_variant` | 新建 **15,545** | `source_id='bdpm_fr'` |
| `substance` | **0 新增** | 映射不上不新增（候选见 §4.4） |
| `source` / `ingest_run` | 各 1 行 | `bdpm_fr`，license/license_url/retrieved_at |
| 仿制药组 | **0**（不入库） | schema 无对应表；只作事实线索，若要用另开 schema 任务 |

**场景对照（写库窗口要拍板的范围）**：

| 方案 | 产品 | component | 有成分产品 | active |
|---|---|---|---|---|
| A 全量 | 15,799 | 19,171 | 13,861 | 13,559 |
| B 排除顺势（`HOMÉOPATHIQUES` / `Enreg homéo`） | 14,322 | 16,786 | 13,331 | 12,104 |
| C 排除顺势 + 平行进口 | 14,067 | 16,482 | 13,096 | 11,948 |

> 建议：**A 全量**（保留注册事实，含历史/顺势力），站上对「无成分/顺势/平行进口」用文案标注边界；
> 若体积或噪声不可接受，退回 B（顺势单独一档、页面明确「不含顺势」）。

### 6.1 回滚清单草案（写库窗口用，本次未执行）

1. **写前备份**：`Copy-Item data/drugs.db data/backups/drugs-pre-fr-<YYYYMMDD>.db`，
   记录 sha256 + `product` / `product_component` / `name_key` / `name_variant` 计数。
2. **manifest**：`--apply` 写 `.tmp/fr-ingest/fr_manifest_<run_id>.json`，含
   `product_ids=15,799`、`name_variant_ids`、`name_key_ids_created`、`source_id`、`run_id`、`applied_at`。
3. **撤销顺序**（单一事务）：
   `product` 删除会级联 `product_component` / `product_name`（`ON DELETE CASCADE`），
   再删 `name_variant WHERE source_id='bdpm_fr'`；
   `name_key` 只删 manifest 里**且无任何 `product_name`/`name_variant` 引用**的；
   最后删 `source WHERE source_id='bdpm_fr'`、`ingest_run WHERE run_id=...`。
4. **验证**：计数回到备份值；`PRAGMA foreign_key_check` 空；`PRAGMA integrity_check` = ok；
   `db/check_data.py` 通过；`coverage` 无 FR 行。
5. **schema 回滚**（如果 FR 国家枚举已迁移）：`product.country` CHECK 需重建表（`db/init_db.py` 的
   迁移路径只做前进）→ 从备份恢复是唯一稳妥做法。

---

## 7. 站点接入清单（**只写方案，本轮不改 `site/`**）

现状基线（`site/dist` 实测，2026-11-12）：**121,450 文件 / 903.6 MB / 121,239 HTML**
（name 77,147 · drug 12,431 · combo 15,248 · maker 15,213 · atc 1,154 · cat 16 · es/zh/zh-hant 各 7）；
sitemap **63,685** 条；`data/idx/core.json` **41.6 MB raw / 9.92 MB gzip**（发布护栏 12 MB gzip，余量 2.08 MB）。

### 7.1 `data/markets.json`（加 FR，先 `enabled:false`）

```json
{
  "code": "FR", "kind": "country", "parent": "EU", "group": "EUROPE",
  "name": {"en": "France", "es": "Francia", "zh": "法国"},
  "i18n_key": "home.fr", "flag": "🇫🇷",
  "source_id": "bdpm_fr", "extra_source_ids": [],
  "default_lang": "fr", "languages": ["fr"],
  "enabled": false, "order": 55, "data_as_of": "2026-11-03",
  "notes": "BDPM（Licence Ouverte 2.0，ANSM）：15,799 个法国注册制剂（含 1,477 顺势、255 平行进口）；规格来自 CIS_COMPO dosage+référence；无 ATC；页面须署名 BDPM + 数据更新日期 2026-11-03。"
}
```
- `order` 建议 55（ES 50 之后）；`kind=country`、`parent=EU`（与「成员国用 country + parent=EU 注册」一致）。
- 校验：`& $py lib/markets.py --check`（会拿 `source_id` 对 DB `source` 表，**必须先入库 source 行**）、
  `& $py -m unittest tests.test_markets_registry -v`。

### 7.2 `data/languages.json`

`fr` 已存在（`enabled:false`，`path:"fr/"`、`hreflang:"fr"`、`default_country:"FR"`、`region:"EU"`）。
上线时只需：`enabled:true` + 更新 `updated` + notes 写「UI 法语；数据语言=法语原文」。
**先决条件**：`site/build.py` 已有 `I18N['fr']`，否则 `_assert_i18n_complete()` 会红。

### 7.3 `I18N` fr 键集（与 en 完全一致，不允许静默回退）

- 主字典 `I18N`：en/es/zh 各 **237 键**；页面级字典另有 `PAGE_I18N`(27)、`COVERAGE_I18N`(25)、
  `WARN_I18N`(54/115)、`COMBO_I18N`(18)、`MAKER_I18N`(31)、`META_I18N`(15)、`GLOSSARY_I18N`(13)、
  `ABOUT_I18N`(19)、`WHATS_I18N`(20)、`A1/结果页` 等，**每个字典的 en 键集都要有 fr**（合计约 596 条）。
- zh-Hant 走 `data/i18n_zh_hant.json` 兜底覆盖的机制；**fr 建议照 es/zh 在 build.py 里加整段字典**
  （键集与 en 一一对应），不要走 machine JSON。
- 文案要求：法语正文（About / 覆盖页 / what's new / 404）都要有；`fr` 用 `lang="fr"`。
- 校验：`_assert_i18n_complete()` / `_assert_i18n_rules()`（build 时自动跑）+ i18n 缺口测试。

### 7.4 路由 / SEO / 站点结构

1. `LANGS`（`site/build.py:879`）加 `("fr", "FR", "fr/")`；`LANG_HREFLANG` 自动 = `fr`；
   生成 `/fr/` 入口 7 页（同 es/zh 结构）；`<html lang="fr">`；语言切换按钮显示 `FR`。
2. hreflang：每页 5 个 alternate（en/es/zh/zh-Hant/fr）+ `x-default` → 全站 12 万页各 +1 条
   （约 +80–120 B/页）。`?lang=fr` 深链与 localStorage 行为要和现有 i18n.js 一致。
3. **硬编码国家顺序要改**：`COUNTRY_PRIORITY`（`build.py:8119`）加 `"FR"`；
   前端 `U2_COUNTRIES`（`build.py:5276`）按需加 `FR`；`window.COUNTRY_ORDER` 由注册表生成（已就绪）。
4. **名字页体积守卫**：`SINGLE_NAME_PAGE_MARKETS = {CN, TW, ES, MX}`（`build.py:2689`）。
   FR 默认**不进**该集合 → 只给「≥2 产品」或「无成分」的名字键建页 = **4,227 个新名字页**；
   若把 FR 加进去 → **11,674 页**（+49 MB dist）。**建议先不加**，上线后按体积数据再定。
5. 覆盖页：`coverage` 视图自动多一行 FR；需加 `coverage.gap.fr` 文案（4 语）：
   「BDPM 整库（15,799 制剂）；含顺势疗法与平行进口注册；规格来自成分表 dosage+référence；
   无 ATC；在册/授权 ≠ 当前在售；授权状态分 active/discontinued/withdrawn。」
6. About：「数据来源与覆盖」加 BDPM/ANSM + Licence Ouverte 2.0 链接 + 数据更新日期 2026-11-03
   + 不背书声明（§1.4 文案）；`source.license_url` 写 BDPM 下载页。
7. sitemap：新名字页进 sitemap（单包装 noindex 页不进，与现有规则一致）；`/fr/` 入口进 sitemap。

### 7.5 测试与验收（站点窗口）

```powershell
& $py lib/markets.py --check
& $py -m unittest tests.test_markets_registry -v
& $py -m unittest discover -s etl -t etl          # 新增 etl/markets/test_fr.py（固定小样本，不联网）
& $py tests/trilingual/run_tests.py               # 加 FR 样本：DOLIPRANE→paracetamol/acetaminophen 等
& $py site/build.py                               # 等 == done ==（串行 owner）
& $py deploy/first_screen_check.py                # 改前/改后各一次，写前后数字
& $py deploy/ci_checks.py                         # 全量
```
另需：三语（上线后五语）各抽 3 条检索；`/fr/` 200 + hreflang 正确；sitemap 含 FR 名字页；
链接/404 抽检；页数/索引大小/首屏体积回归。FR 查询样本建议：`DOLIPRANE`（acetaminophen）、
`EFFERALGAN`（acetaminophen）、`SPASFON`（phloroglucinol）、`PERMIXON`（saw palmetto）、
`COVERAM`（amlodipine/perindopril，复方候选集）。

### 7.6 体积预估（相对当前 dist）

| 项 | 增量 | 依据 |
|---|---|---|
| 名字页 | **+≈4,227 页 ≈ +17.7 MB**（FR 加入守卫则 +≈11,658 新页 ≈ +49 MB） | 名字页均 4,189 B（当前实测 77,147 页/323.1 MB）；FR 11,674 个名字键里 16 个已有页 |
| 成分页（drug/） | **0 新页**（1,868 个已有 substance 添 FR 行）≈ +2–4 MB | 成分页均 9.6 KB，FR 无新 substance |
| 厂家页（maker/） | +约 200–400 页 ≈ +2–4 MB | 671 个 MAH、651 个新字符串（多为已有大厂的分支名） |
| 组合页（combo/） | +约 561 页 ≈ +2.8 MB | FR 复方组合 561 种；组合页均 5.0 KB |
| 覆盖页/About/入口 | +约 1 MB | 覆盖页 +1 行、`/fr/` 7 页 |
| **第 5 种 UI 语言的 hreflang/切换器** | **+12–17 MB**（全站 12 万页各 +100–140 B） | 当前每页已有 4 个 alternate |
| `core.json` | raw +≈2.4 MB（→44 MB）/ **gzip +≈0.55 MB（→10.5 MB）** | 11,658 新名字键；**护栏 12 MB，余量降到 ≈1.5 MB** |
| sitemap | +4,227 条（→67,912） | 每 URL 约 130 B |
| **合计** | **≈ +40 MB（+4.4%）→ ≈ 945 MB**；若 FR 进单包装守卫 ≈ +71 MB（→975 MB） | — |

> 结论：默认方案可控；但 `core.json` gzip 已接近发布护栏（10.5/12 MB），**FR 上线前要实测一次
> `data/idx/core.json` gzip**，若超 11.5 MB 需先做索引瘦身（或在 CHANGELOG 前调护栏并说明）。

### 7.7 顺序（与 `docs/市场扩展接口.md` §3/§4 对齐）

1. 许可清单 FR 行（Lead 提交）→ 2. schema `product.country` 加 `FR`（`db/init_db.py` 幂等迁移，
   重建 product 表；**老库可升级**）→ 3. `etl/markets/fr.py` 补 `--apply/--rollback/--manifest`
   三段式（照 `ingest_eu.py`）→ 4. 备份库 → 写库窗口（source + 产品/组件/名称）→ `check_data.py`
   → 5. `data/markets.json` FR（先 false）+ `languages.json` fr（先 false）→ 6. `site/build.py`
   加 `I18N['fr']` / `LANGS` / `COUNTRY_PRIORITY` / `coverage.gap.fr` / About 署名 →
   7. 注册表 `enabled:true`（market + language）→ 8. 建站到 `== done ==` + 首屏守卫 + 体积回归 →
   9. CHANGELOG / README / About / coverage 计数同步 → 10. R2 主域 + gh-pages 备份 + verify_live。

---

## 8. 风险与未决

| # | 风险 / 未决 | 影响 | 处置建议 |
|---|---|---|---|
| 1 | **只到 dry-run**，没有 `--apply` | 站点还不能上线 FR | 等 UI 接入（§7）后另开写库窗口；用户 2026-11-12 已授权「先取数、UI 改完再上线」 |
| 2 | `product.country` CHECK 无 `FR` | 现在硬入库会 CHECK 失败、`coverage`/建站红 | 写库窗口第一步做 schema 迁移（§7.7 步骤 2） |
| 3 | 1,938 个产品无成分（顺势 1,477 为主） | 站上只有名字层，成分页不可达 | 建议入库 + 页面标「成分未收录/顺势」；或按方案 B 排除顺势 |
| 4 | 顺势疗法 1,477 产品、8,226 行成分 | 无 INN/无剂量，会拉低映射率 | 文案明确「顺势单独一档」，不硬映射 |
| 5 | 平行进口 255 CIS / 同身份 2,456 组 | 同名候选多（PERMIXON 14 条） | 不合并；结果页候选集 + 「平行进口」标注 |
| 6 | 无 ATC、无剂量基准字段 | 无法做新 ATC 归类/盐基折算 | 沿用库内 ATC；`strength_basis='unknown'`，继续「不判断可互换」 |
| 7 | 非顺势成分映射 89.7%（1,524 种未映射） | **1,938 个产品无 component**（名称层） | 缺口清单在 dry_run.json；常见缺口可补法语同义词（另开小任务），生物制品/顺势保持缺口 |
| 8 | 剂型 `other` 567 个 | 成分页/筛选少了剂型标签 | 抽查 top other，补法语词形（不影响入库） |
| 9 | BDPM 文件格式变更（列数 12/8/13/5） | 换版会全表串列 | `self-check` 断言列数 + 每行列数校验；每次 `--force` 重抓后先跑 `--self-check` |
| 10 | 编码不统一（cp1252 / utf-8） | 读错会掉字 | 按文件解码 + 替换字符计数为 0（self-check 断言） |
| 11 | `core.json` gzip 10.5 MB 接近 12 MB 护栏 | 发布 `sync_r2`/`verify_live` 可能触线 | 上线前实测；必要时索引瘦身或调护栏（写进发布报告） |
| 12 | 仿制药组无 schema 表 | 10,614 行组信息浪费 | 本轮不入库；若页面要用「同组」事实，另开 schema 任务（不涉及替代推荐） |

---

## 9. 命令与数字可复核

```powershell
& $py etl/markets/fr.py --self-check        # 全部 ok（0 失败）
& $py etl/markets/fr.py --dry-run           # 控制台摘要 = .tmp/fr-ingest/fr_dry_run.json
& $py db/q.py "SELECT COUNT(*) FROM product WHERE country='FR'"   # 0（真库未写）
```

关键数字均来自 `.tmp/fr-ingest/fr_dry_run.json`（`rows` / `status` / `dosage_form` / `strength` /
`substance` / `eu_overlap` / `dedupe` / `would_write`）与 §2 的 `fetch_meta.json`；
快照 sha256 与字节数可用 `Get-FileHash data/raw/fr_bdpm_20261112/*.txt -Algorithm SHA256` 复核。

_本报告为取数与干跑产物，不含任何写库、建站或发布动作。_
