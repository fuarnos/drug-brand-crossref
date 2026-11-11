# 法国 FR 数据质量提升（v0.11.5 准备）：成分映射 ≥92%、规格 ≥80%、剂型用结构化字段（task-68）

> 日期：2026-11-14（北京时间）· 工位：page-slim · 任务：`task-68`
> 结论先行：**三项指标全部达标**（before → after，全部在库副本 dry-run，**未写真库**）：
>
> | 指标（覆盖页口径：产品级 / 15,799） | before（v0.11.4 线上） | after（本次） | 目标 |
> |---|---:|---:|---:|
> | **成分映射**（有 ≥1 component 的产品） | 13,861（**87.7%**） | **14,543（92.1%）** | ≥92% ✅ |
> | **规格覆盖**（有 ≥1 有剂量 component 的产品） | 11,255（**71.2%**） | **13,754（87.1%）** | ≥80% ✅ |
> | **剂型覆盖**（`form_base` 非 other/unknown） | 15,232（**96.4%**） | **15,796（100.0%）** | 用结构化字段 ✅ |
>
> **是否建议 apply：建议 apply（v0.11.5）**，但需注意 3 点：① 成分映射只比目标高 0.1 个百分点（14,543/15,799），
> 后续不要再回退；② 规格里 **1,993 个产品** 的剂量来自「composition 为空 → 品名补足」，页面/说明须标「部分规格来自品名」；
> ③ 仍有 403 个非顺势产品没有 component（生物制品/植物药/法国独有 INN 不在库），建议后续单独补 8–10 个 substance。
> 本轮**只改 `etl/markets/fr.py`**：未写 `data/drugs.db`、未改 site / markets / languages、未 commit。

---

## 1. 做法（每条规则可解释、可抽检）

### 1.1 剂型：改用 BDPM 结构化字段 `forme pharmaceutique` + `voie d'administration`

- `fr_form_base(forme, voies)`：优先用 `forme` 结构化字段映射到**库内已有的 form_base 取值**
  （`tablet / capsule / liquid / injection / topical / powder / inhalation / suppository /
  effervescent / gas / gum / pastille / mouthwash / pad / stick / kit / device / film / implant /
  radiofarmaco / tea (herbal)`），**不新造枚举**；`forme` 认不出时才用 `voie` 兜底
  （`intraveineuse/intramusculaire/sous-cutanée` → injection；`ophtalmique/auriculaire` → liquid；
  `inhalation/nasale` → inhalation；`cutanée/transdermique` → topical；`rectale/vaginale` → suppository）。
- 结果：`other` 从 **567 → 3**（0.02%）；不再是「从品名猜剂型」。

### 1.2 规格：composition 的 dosage + 单位为主，品名补足仅限 composition 空值

- 继续用 `CIS_COMPO.dosage + référence de dosage`（法式小数逗号 `0,5 g`、`UI`/`µg`、`mg/5 ml`、
  `pour 1 comprimé`、`100 mg/1 mL`、`M UI` 等都已覆盖）。
- **新增补足规则**：当某产品 **只有 1 个 component、且 composition 完全没给剂量** 时，
  从 `dénomination` 抽规格（`parse_name_strengths()`：法语单位整形 → `normalize()`），
  该 component 标 `strength_source="name"`；**多成分产品不做品名补足**（避免把整方剂量挂到单个成分）。
- 结果：component 带剂量 **14,276 → 17,165**；产品级 **11,255 → 13,754**；
  其中 composition 来源 11,761 个产品、品名补足 **1,993** 个产品。

### 1.3 成分映射：法语盐名/语序/载体词/同义词/生物制品/植物药

新增（全部在 `etl/markets/fr.py`，命中与否仍由库里 `substance` 决定，**不新增 substance**）：

1. **盐/酯/水合物词表扩充**：`hydrogénotartrate`、`hydrogénosuccinate`、`hydrogénosulfate`、
   `dihydrogénophosphate`、`métasulfobenzoate`、`tétradécylsulfate`、`hyclate`、`lysinate`、
   `éthanolate`、`ditartrate`、`hémisuccinate`、`pivalate`、`tosilate/bésilate`、`benzoyle`、`cuivre`…
2. **语序修正**：
   - 阴离子 + 盐形容词：`PHOSPHATE SODIQUE DE DEXAMÉTHASONE` → `dexamethasone sodium phosphate`；
   - 金属不算「盐名前缀」（修复 `CHLORURE DE CALCIUM` 被倒装成 `dihydrate calcium chloride`）；
   - `PEROXYDE DE BENZOLE` → `benzoyl peroxide`；`ACIDE X` → `X acid`；`X (ACIDE)` → `X acid`。
3. **载体词剥离**：`SOLUTION DE …`、`CO-CRISTAL D'…`、`COMPLEXE …`、`FRACTION …`、`SEL …` 先剥，再匹配。
4. **同义词表**（`FR_INN_SYNONYMS`）：`PARACÉTAMOL→acetaminophen`、`ACIDE ACÉTYLSALICYLIQUE→aspirin`、
   `ACÉTYLLEUCINE→levacetylleucine`、`SOMATOTROPINE→somatropin`、`FLUDÉSOXYGLUCOSE→fludeoxyglucose f 18`、
   `DIACÉRÉINE→diacerein` 等（含法/西拼写桥：词尾 `e↔a`、`œ→oe`、双写辅音简化）。
5. **关键词级同义词**（植物/生物制品/特殊词序，31→45 条）：`AUBÉPINE→hawthorn`、`ARTICHAUT→artichoke`、
   `PASSIFLORE→passiflora incarnata top`、`THYM→thymus vulgaris leaf`、`NIAOULI→niaouli oil`、
   `SÉNÉ (FRUIT)→senna pods`、`ISPAGHUL→ispaghula husk`、`SERENOA REPENS→serenoa repens`、
   `VIRUS DE LA GRIPPE→influenza virus vaccine`、`ANTIGÈNE HBs→hepatitis b surface antigen`、
   `VRS/GLYCOPROTÉINE F→RSV pre-fusion F protein`、`VENIN D'ABEILLE→apis mellifera venom`、
   `VENIN DE GUÊPE (VESPULA/POLISTE)→vespula spp / polistes spp venom`、`RIFAMPICINE→rifampin`、
   `IOFLUPANE→ioflupane i 123`、`FLUCICLOVINE→fluciclovine f 18` 等。
6. **候选链重试 + 变体对齐**：库里有些 substance **没有 variant 行**（如 `esomeprazole-magnesium-dihydrate`），
   直接映射会让 component 被 `_variant_resolver` 丢弃；现在返回整条候选链，按顺序挑**第一个有 variant** 的
   （盐型无 variant 时回退到基名，如 `beclomethasone dipropionate → beclomethasone`），并用品名候选串解析 variant。
7. **不硬对**：未命中一律空着；不做编辑距离/模糊匹配；新增规则逐条可在 §3 抽检。

---

## 2. Before / After（本次 dry-run 实测）

| 指标 | before（线上 FR 行） | after（新解析） | 变化 |
|---|---:|---:|---:|
| 产品 | 15,799 | 15,799 | 0 |
| 有 ≥1 component 的产品 | 13,861（87.7%） | **14,543（92.1%）** | **+682** |
| component 总数 | 19,171 | **20,448** | +1,277 |
| component 带剂量 | 14,276（74.5%） | **17,165（83.9%）** | +2,889 |
| 产品有 ≥1 剂量 | 11,255（71.2%） | **13,754（87.1%）** | **+2,499** |
| └ 来自 composition | 11,255 | 11,761 | +506 |
| └ 来自品名补足 | 0 | 1,993 | +1,993 |
| `form_base` 非 other/unknown | 15,232（96.4%） | **15,796（100.0%）** | +564 |
| `form_base=other` | 567 | **3** | −564 |
| 未映射 token 写法 | 1,524 | **1,126** | −398 |
| 非顺势 token 映射率 | 89.7% | **95.6%** | +5.9pp |
| name_key / name_variant 新增 | — | **0 / 0**（FR 名字已在库） | 无变化 |
| substance 新增 | 0 | **0** | 不新增 |

> 注：`name_keys_new=0` 是因为 v0.11.4 已把 11,658 个 FR 名字写进库；本次 apply 只会替换 FR 的
> product / component 行，不会新增名字或 substance。

---

## 3. 误配抽检（20 条，人工核对）

覆盖盐名、酸、植物、生物制品、关键词、变体回退六类；结论：**20/20 身份对应正确**，
其中 3 条是「盐型 substance 无 variant → 回退基名」、1 条是「病毒抗原 → 疫苗物质」的**宽化**，均已在备注标注。

| # | 法语成分原文（截断） | 映射到 | 规则 | 判断 |
|---:|---|---|---|---|
| 1 | `PHOSPHATE SODIQUE DE DEXAMÉTHASONE` | Dexamethasone Sodium Phosphate | 阴离子+形容词语序 | ✅ 精确 |
| 2 | `HYDROGÉNOTARTRATE DE RIVASTIGMINE` | Rivastigmine Hydrogen Tartrate | 盐名词表 | ✅ 精确 |
| 3 | `SOLUTION DE DIGLUCONATE DE CHLORHEXIDINE` | Chlorhexidine Digluconate | 载体词+盐名 | ✅ 精确 |
| 4 | `PIVALATE DE TIXOCORTOL` | Tixocortol Pivalate | 盐名前置 | ✅ 精确 |
| 5 | `TOSILATE DE PÉRINDOPRIL` | Perindopril（基名） | 盐型无 variant→回退基名 | ⚠️ 盐型宽化 |
| 6 | `DIPROPIONATE DE BÉCLOMÉTHASONE` | Beclomethasone（基名） | 同上 | ⚠️ 盐型宽化 |
| 7 | `ÉSOMÉPRAZOLE MAGNÉSIQUE DIHYDRATÉ` | Esomeprazole Magnesium | 候选链回退 | ✅（盐型近似） |
| 8 | `ACÉTYLSALICYLIQUE (ACIDE)` | Aspirin | `(ACIDE)` + 同义词 | ✅ |
| 9 | `FUSIDIQUE (ACIDE)` | Fusidic Acid | `(ACIDE)` + `-ique→-ic` | ✅ |
| 10 | `PEROXYDE DE BENZOLE HYDRATÉ` | Benzoyl Peroxide | 词序 + 关键词 | ✅ |
| 11 | `FLUDÉSOXYGLUCOSE [18F]` | Fludeoxyglucose F 18 | 关键词 | ✅ |
| 12 | `VIRUS DE LA GRIPPE INACTIVÉ, FRAGMENTÉ` | Influenza Virus Vaccine | 关键词 | ⚠️ 抗原→疫苗（宽化） |
| 13 | `ANTIGÈNE DE SURFACE DE L'HÉPATITE B RECOMBINANT` | Hepatitis B Surface Antigen | 关键词（去标点后） | ✅ |
| 14 | `GLYCOPROTÉINE F … VRS … PRÉ-FUSION` | Recombinant RSV Pre-Fusion F Protein | 关键词 | ✅ |
| 15 | `ABEILLE (VENIN D')` | Apis Mellifera Venom | 关键词（词序） | ✅ |
| 16 | `GUÊPE VESPULA (VENIN DE)` | Vespula Spp Venom | 关键词 | ✅ |
| 17 | `PALMIER DE FLORIDE (SERENOA REPENS…)` | Serenoa Repens | 关键词 | ✅ |
| 18 | `AUBÉPINE (SOMMITÉ FLEURIE D')` | Hawthorn | 关键词（植物） | ✅ |
| 19 | `SÉNÉ DE L'INDE … (FRUIT DE)` | Senna Pods | 关键词（植物部位=果实） | ✅ |
| 20 | `ISPAGHUL (GRAINE D'), TÉGUMENT DE LA` | Ispaghula Husk | 关键词（种皮=husk） | ✅ |

> 已**主动放弃**两条「同种植物但部位不同」的映射（lierre 叶 vs flowering twig、vigne rouge 叶 vs flowering top），
> 宁可不映射也不写错部位——这两条合计 11 个产品，放弃后映射率仍为 92.06%。

---

## 4. 剩余不可映射原因（top 类别 + 样例 30）

当前仍有 **403 个非顺势产品**没有 component（另有 922 个顺势产品，按设计不映射）：

| 类别 | 估计产品数 | 说明 / 样例 |
|---|---:|---|
| 顺势疗法（设计上不映射） | 922 | `BRYONIA POUR PRÉPARATIONS HOMÉOPATHIQUES` 43、`BELLADONA …` 41、`NUX VOMICA …` 37 |
| 库内没有该 INN | ~70 | `OXOMÉMAZINE` 25、`MÉTOPIMAZINE` 12、`THIOCOLCHICOSIDE` 10、`TARTRATE DE CYAMÉMAZINE` 7、`BICLOTYMOL` 6、`PROPÉRICIAZINE` 4、`BRÉTOVAMÉRAN` 3、`JOSAMYCINE` 3、`PROMESTRIÈNE` 2、`OMOCONAZOLE` 3 |
| 生物制品/疫苗无精确对应 | ~150 | 肺炎链球菌血清型（库里只有 7 个血清型，FR 是 3/6A/19A/7F/22F/33F）、`PANCRÉAS`、`ADAMTS13R`、`ARNM SRAS-CoV-2`、`VIRUS HÉPATITE A` 等 |
| 植物药/提取物（部位或物种不匹配） | ~100 | `LIERRE GRIMPANT`（叶）、`VIGNE ROUGE`（叶）、`MÉLISSE`、`HARPAGOPHYTON`、`FUMETERRE`、`REINE DES PRÉS`、`BUSSEROLE`、`MILLEPERTUIS`、`ESCHSCHOLTZIA`、`ORTHOSIPHON`、`PETIT HOUX` |
| 溶液/电解质/造影剂/其他 | ~80 | `IBANDRONIQUE (ACIDE), SEL MONOSODIQUE…`、`TÉTRAKIS CUIVRE…`（已映射部分）、`SOJA/AVOCAT (FRACTION INSAPONIFIABLE)` |

**建议后续（v0.11.6 或单独小任务）**：补 8–10 个法国独有 INN substance（oxomémazine / métopimazine /
thiocolchicoside / biclotymol / cyamémazine / propériciazine / brétovaméran / josamycine / promestriène /
omoconazole），每个都有 INN/ATC 可查；预计可再 +0.4–0.5pp（到 ~96%），并减少「无成分」产品噪声。

---

## 5. 是否建议 apply（结论）

**建议 apply（v0.11.5），但有条件**：

1. **先复核本报告 §3 的 3 条「盐型→基名」宽化**：如果希望保留盐型身份，可在同一窗口创建缺失的 variant 行
   （如 `perindopril-tosilate`、`beclomethasone-dipropionate` 目前无 variant），否则接受「基名 + 成分原文在快照」。
2. **apply 顺序**：库副本已跑过 full chain（task-54）；真库窗口：备份 → `--apply --allow-real` →
   `db/check_data.py` → 覆盖页 FR 行复核（应显示 92.1% / 87.1% / 100%）→ 建站/发布。**本轮未写真库**。
3. **页面口径补一句**：「FR 的 1,993 个产品规格来自品名补足（composition 未给剂量）」，避免读者误以为
  全部规格来自成分表；同时保留「BDPM 是 État de commercialisation 上市状态，不等于在售」的既有说明。
4. **回滚**：沿用 `fr_manifest`（task-54 已有）；本次 apply 后 manifest 会含新的 component 计数，回滚到
   v0.11.4 基线即可。

---

## 6. 验证与边界

```powershell
& $py etl/markets/fr.py --self-check        # 全部通过（0 失败）
& $py etl/markets/fr.py --dry-run           # 本次 before/after 数字 = .tmp/fr-ingest/fr_dry_run.json
& $py etl/markets/fr.py --dry-run --db .tmp/fr-ingest/drugs_fr_copy.db
```

- 全程 **dry-run**：库副本只读；`data/drugs.db` 未写（sha256 与 task-54 结束时一致）。
- 未改 `site/build.py`、`data/markets.json`、`data/languages.json`、未 commit。
- 自测覆盖：CLI/护栏/manifest、NFKC、規格样例、盐名/语序、植物/生物关键词、候选链回退、manifest 一致性。
- 已知边界：① 品名补足的规格精度低于 composition（只对单成分产品启用）；② 盐型 substance 无 variant 时回退基名；
  ③ 生物制品/植物药的物种/部位不精确对应时宁可不映射（已放弃 11 个产品，不影响达标）。

_本报告为质量提升的干跑产物；真库 apply 与站点更新排在 v0.11.5 窗口，由 Lead 决定。_
