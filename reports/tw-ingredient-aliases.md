# TW TFDA 未匹配成分 token → INN 别名映射（task-67）

> 日期：2026-10-28 ｜ 数据：`data/drugs.db`（**只读**，未写库）、`data/raw/tw/tfda_36.csv`（TFDA data_as_of 2026-10-22）、task-54 dry-run 产物
> 产物：`data/tw_ingredient_aliases.csv`（893 行）、`etl/build_tw_aliases.py`、本报告；统计/清单在 `.tmp/tw-alias/`。
> 未写 `data/drugs.db`、未改 `site/build.py`、未跑 git/发布。

## 1. 结论

| 指标 | 样本 dry-run | 全量 dry-run |
|---|---:|---:|
| 成分 token 总数 | 2,289 | 39,045 |
| 映射前已匹配 | 2,090（**91.3%**） | 32,598（**83.5%**） |
| 本轮新映射到库内 substance | 59 次 | **1,664 次 / 132 个 distinct token** |
| **映射后 token 覆盖率** | **93.9%**（+2.6pp） | **87.8%**（+4.3pp） |
| 全匹配行（token 全命中） | 1,373/1,535 = 89.4% → **1,389 = 90.5%** | 14,344/17,892 = 80.2% → **14,623 = 81.7%** |

未匹配 893 个 distinct token（样本 121 个）的处置：

| 处置 | distinct | 说明 |
|---|---:|---|
| ✅ mapped（写入 substance_id） | **132**（high 18 / medium 114） | 同义名/盐型/词序/相似度命中库内成分 |
| 📝 suggested_inn_not_in_db | **42** | 能确认 INN 但库内没有该成分（旧药/植物药等），作为「建议新增成分」清单，不硬造 id |
| ❔ uncertain | **40** | 有相似候选但低于自动映射门槛（0.86–0.90），不写 substance_id，留人工 |
| ❌ unresolved | **679** | 生物制品/疫苗、植物提取物、乱码/缩写、库内完全没有的成分 |

## 2. 输入与匹配规则（`etl/build_tw_aliases.py`，只读 DB，可重跑）

输入：`.tmp/tw-ingest/full_dryrun-unmatched.csv`（893 token×次数）、`unmatched_tokens.csv`（样本 121）、
`full_dryrun.csv` / `data/tw_ingest_dryrun.csv`（算行级覆盖）、两份 dry-run stats（算分母）。

匹配顺序（每步记录 evidence/confidence）：

1. **归一精确**：NFKC → 大写 → 去括号/标点/空格，与 `substance.inn_en` 归一值比较（如 `FISH-OIL RICH IN OMEGA-3 ACIDS`）；
2. **盐/酯/水合物/立体前缀剥离**：`HCL/HBR/HYDROCHLORIDE/SODIUM/…`、`FUMARICACID→fumarate`、`DL-/L-/D-` 前缀；剥后与库内成分比对，并到 `variant.salt/salt_code` 校验盐型（如 `CETIRIZINE DIHYDROCHLORIDE → cetirizine`，high）；
3. **人工同义表**（TW/BAN/USAN/旧名，约 70 条）：`GUAIACOL GLYCERYL ETHER→guaifenesin`、`IODOCHLORHYDROXYQUIN→clioquinol`、`RETINOIC ACID→tretinoin`、`METAPROTERENOL→orciprenaline`、`PANTOTHENATE CALCIUM→calcium pantothenate`、`GLYCYRRHIZINIC ACID→glycyrrhizin`、`SENNOSIDE→sennosides`、`ESTRADIOL ETHINYL→ethinylestradiol` 等；
4. **名称相似度**：与库内 inn 做 difflib，≥0.90 且唯一 → medium（如 `LYSINE L- HCL→lysine` 0.92）；0.86–0.90 → 只记 uncertain 候选；**数字/血清型守卫**（`PNEUMOCOCCAL … SEROTYPE 7F ≠ 19F/6B` 不做模糊映射）；
5. **库内只有西语/中文重复成分时**（`mx-es-*`/`cn-*`）→ 记 `suggested_inn_not_in_db`，不把 TW 成分挂到西语重复 id（如 `MEQUITAZINE` 只有 `mx-es-mequitazina`）；
6. 仍无候选 → 按关键词分类：生物制品/疫苗（VIRUS/VACCINE/TOXOID/ANTIBODY/CARRIER PROTEIN…）、植物/中药（EXTRACT/SILYMARIN/SENNOSIDE/…）、乱码/缩写（无元音/太短，如 `RFIXFC`）→ `unresolved`，不硬造。

**evidence/confidence 口径**：high = 归一精确命中，或盐型剥离后 salt variant 也对上；medium = 同义表/词序/盐型 base 匹配/相似度≥0.90；uncertain = 仅相似候选（0.86–0.90）不写 id；suggested = 识别出 INN 但库内无成分。

## 3. 映射结果（132 个 mapped token）

Top（按全量出现次数）：

| token | 次数 | → substance（inn_en） | 依据 |
|---|---:|---|---|
| GUAIACOL GLYCERYL ETHER | 257 | Guaifenesin | 同义（glyceryl guaiacolate） |
| PANTOTHENATE CALCIUM | 94 | Calcium Pantothenate | 同义/词序 |
| GLYCYRRHIZINIC ACID | 86 | Glycyrrhizin | 同义 |
| GUAIACOL GLYCOLATE | 78 | Guaifenesin | 同义 |
| IODOCHLORHYDROXYQUIN | 63 | Clioquinol | 同义 |
| METHIONINE DL- | 56 | Methionine | 立体前缀剥离 |
| METAPROTERENOL SULFATE | 46 | Orciprenaline | 同义 |
| RETINOIC ACID | 36 | Tretinoin | 同义 |
| LYSINE L- HCL | 36 | Lysine | 盐/立体剥离（similarity 0.92） |
| CLOBETASOL-17-PROPIONATE | 35 | Clobetasol Propionate | 同义 |
| TRIGLYCERIDES MEDIUM CHAIN | 33 | Medium Chain Triglycerides | 词序 |
| CARBOCYSTEINE | 32 | Carbocisteine | 同义（BAN→INN） |
| FISH-OIL RICH IN OMEGA-3 ACIDS | 31 | Fish Oil - Rich In Omega-3 Acids | 精确 |
| ACETAMIDOCAPROIC ACID -EPSILON | 30 | Aminocaproic Acid | 同义 |
| BUTYLSCOPOLAMINE BROMIDE | 30 | Scopolamine Butylbromide | 同义 |
| ESTRADIOL ETHINYL | 28 | Ethinylestradiol | 词序/同义 |
| CHLOROPHYLL SODIUM COPPER | 28 | Chlorophyllins | 同义 |
| GLYCYRRHIZINATE DIPOTASSIUM | 26 | Glycyrrhizin | 同义/盐剥离 |
| SENNOSIDE | 25 | Sennosides | 同义 |
| CETIRIZINE DIHYDROCHLORIDE | 25 | Cetirizine | 盐型剥离（high） |
| MEQUITAZINE / PANTHENOL D- / … | 20–24 | （见 CSV） | 相似度/同义 |

## 4. 剩余缺口（679 unresolved + 42 suggested + 40 uncertain）

**Top unresolved（按次数）**：`RFIXFC(32)`、`PNEUMOCOCCAL POLYSACCHARIDE SEROTYPE 7F(29)` / `3`/`5`/`6A`/`1`/`19A`/`22F`/`33F`（各 18–23）、`CRM197 CARRIER PROTEIN(23)`、`CARRIER PROTEIN(18)`、`INACTIVATED POLIO VIRUS TYPE 1/2/3(21)`、`RECOMBINANT FUSION PROTEIN…FACTOR IX…ALBUMIN(20)`、`OXAZOLAM(21)`、`NEWLASE(21)`、`ASPARTATE POTASSIUM L-(20)`、`UNDECYLENATE ZINC(19)`、`RIBOFLAVIN BUTYRATE(19)`。

分类与原因：

1. **疫苗/生物制品（最大缺口）**：肺炎球菌血清型（DB 只有 4/6B/9V/14/18C/19F/23F，缺 7F/3/5/6A/1/19A/22F/33F）、CRM197 载体蛋白、灭活脊灰病毒、凝血因子-白蛋白融合蛋白、免疫球蛋白等——**不应硬造映射**，应随 TW 入库新建 vaccine/biologic substance（或按「疫苗组合」整体处理）。
2. **库内没有的旧药（42 个 suggested）**：`DL-METHYLEPHEDRINE HCL`、`ETHENZAMIDE`、`POTASSIUM GUAIACOLSULFONATE`、`NOSCAPINE`、`BROMISOVALUM`、`SILYMARIN`、`OROTIC ACID`、`THIAMINE DISULFIDE`、`OXETHAZAINE`、`ISOCONAZOLE NITRATE`、`CEPHRADINE`、`CHLORMEZANONE`、`DIPHENIDOL`、`ALUMINUM SILICATE`、`BUTAMIRATE`、`TIPEPIDINE`、`ETOFENAMATE`、`OXOLAMINE`、`MEPHENOXALONE`、`NITROFURAZONE`、`EPRAZINONE`、`PROSULTIAMINE` 等（TW 复方感冒/胃肠老药为主）——需要新增 substance 或人工确认后可回填。
3. **植物/中药边界**：`SILYMARIN`、`SCOPOLIA EXTRACT`、`GLYCYRRHIZINATE DIPOTASSIUM`（部分已映射）等，需与中藥/植物药产品边界一起定标。
4. **乱码/缩写**：`RFIXFC`、`NEWLASE` 等疑似打错/内部词，保留 unmapped。
5. **uncertain 40 个**（相似度 0.86–0.90 的候选）：如 `SELUMETINIB HYD-SULFATE→Selumetinib`、`MECLOFENAMIC ACID→Mefenamic Acid`、`HOMOCHLORCYCLIZINE HCL→Chlorcyclizine`、`MENTHA OIL→Menthol` 等，建议人工复核后加入同义表。

## 5. 接入建议（下一步）

1. `etl/ingest_tw_tfda.py:match_component()` 在现有「整段→拆盐→DL-/L- 去前缀」都不命中后，加载
   `data/tw_ingredient_aliases.csv`（`status=mapped`）做别名查表：hit → `(substance_id, salt)`；
   `suggested_inn_not_in_db` → 在 dry-run 的 `note` 里标 `new_substance_candidate:<INN>`，**不写库**；
   `uncertain`/`unresolved` 保持现状（unmapped 计数）。
2. 重跑 dry-run 验收：预期全量 token 覆盖 **87.8%**、样本 **93.9%**、行级全匹配 **81.7% / 90.5%**；
   与 ingest 现有统计对比；差异写进下一轮报告。
3. 建议新增 substance（42 个 suggested 中的常用药）+ 补肺炎球菌血清型/生物制品建模，然后再做
   `product.country='TW'` 枚举迁移与 `--write-db`（task-54 §7 的阻塞项）。
4. `data/tw_ingredient_aliases.csv` 是**数据文件**（非产品成分表），只供 ingest 查表；接入前建议人工抽检
   medium 映射（尤其相似度来源的 `LYSINE L- HCL`、`PANTHENOL D-`）与同义表条目。
5. 来源/许可：映射均来自仓库内 DB（openFDA/dm+d/CIMA/NHSA 等）+ WHO INN 表 + 人工同义表，不新增外部数据源；
   在 ingest 报告/About 里说明「别名表为站内归并数据」，沿用 TFDA OGDL v1.0 署名（数据本身未变）。

## 6. 风险与限制

- **人工同义表仍需复核**：medium 映射里词序/盐型来源较可靠，相似度来源可能有误（已设 0.90 门槛 + 唯一候选 + 数字/血清型守卫）；建议抽检 top 20 再批量使用。
- **盐型选择**：剥离盐后若库内无对应 salt variant，按 base 成分记录（`salt` 列留空、evidence 注明），写库时仍需决定 variant 归属。
- **库内重复成分**：`mx-es-*`/`cn-*` 重复 id 不作为 TW 映射目标（避免 TW 产品挂到西语重复成分），只记 suggested。
- **生物制品/疫苗**保持 unmapped（不硬造），等建模决策。
- **数据漂移**：映射基于 2026-10-28 的 DB 快照；DB 更新后重跑脚本即可（只读、无副作用）。

## 7. 复现与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 前置：task-54 的 dry-run 产物（.tmp/tw-ingest/）
& $py etl/build_tw_aliases.py            # 生成 data/tw_ingredient_aliases.csv + 统计
& $py etl/build_tw_aliases.py --dry-run  # 只看统计
```

| 文件 | 内容 |
|---|---|
| `data/tw_ingredient_aliases.csv` | 893 行：tw_token/status/inn_en/substance_id/salt/confidence/evidence/occ_full/occ_sample |
| `etl/build_tw_aliases.py` | 只读 DB 的构建器（归一/盐剥离/同义/相似度/分类） |
| `.tmp/tw-alias/stats.json` | 覆盖率 before-after、映射类型/置信度分布、top 缺口 |
| `.tmp/tw-alias/top_unmapped.txt` | 全量未匹配 token 次数清单（前 120） |
| `reports/tw-ingredient-aliases.md` | 本报告 |
