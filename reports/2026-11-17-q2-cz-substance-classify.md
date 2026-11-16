# Q2 CZ 908 新成分：分类落地 + 3 个确定性合并候选 + 192 疑似 INN 的 WHO 复核（零写库）

- 任务：**task-3**（工位 **phaseb-data**）；时间 北京时间 2026-11-17 00:40–01:10
- 依据：`reports/2026-11-16-cz-substance-quality.md`（Q2 方案 A / C 最小集）
- 纪律：**零写库**（`data/drugs.db` 全程 `mode=ro`，未 ALTER / INSERT / UPDATE / VACUUM）、
  **未 commit / 未发布 / 未改 `site/build.py`·`lib/`·`deploy/`·`etl/`**
- 复现脚本：`db/cz_substance_classify.py`（只读库，写 `data/sources/` 的派生 CSV）

## 0. 结论（先行）

1. **908 个新成分的分类已落表**：`data/entity_type.csv` 覆盖 **0/908 → 908/908**（+908 行，diff 0 删除）。
   其中 **519 行有明确类型**（409 顺势 / 47 生药 / 42 疫苗 / 10 辅料 / 11 真实 INN），
   **389 行按「判不了就留空 + 计数」留空**（183 疑似 INN 未确认 + 183 规则未命中 + 23 词表误命中）。
2. **3 个确定性合并候选**（去性状限定词后同名同物）：`Acetic Acid Glacial`、`Ethinylestradiol Micronized`、
   `Ferrous Sulfate Dried`，合计影响 **6 / 20 / 4 个 product** 与 **6 / 20 / 4 行 product_component**，
   每条都带可直接跑通的复现 SQL。**本任务不执行合并**（要写库窗口）。
3. **192 个「疑似 INN」用现有 WHO 名录（1,737 条）只能确认 9 个**（母体 INN 命中 + 尾词是盐/酯/水合物），
   **183 个标「未确认」**——原因不是「不是 INN」，而是**名录快照覆盖不足**（见 §5.3）。
4. **About「药物实体」ATC 分母会 +11**（8,447 → 8,458，覆盖率 67.4% → 67.3%）：因为 11 个成分新标为
   `inn_drug`。这是数据驱动、build 时自动重算的数字；若不希望本版动这个口径，回退方法见 §6。
5. 23 条「词表误命中」（`Fludeoxyglucose 18F` 被辅料词表当辅料、`Freeze Dried Escherichia Coli` 被当生药…）
   已按「不猜」留空并逐条列在 §3.3，供人工定类型。
6. **写库窗口的前置条件**有 7 条（§8），其中最关键一条：`data/entity_type.csv` 是
   `etl/classify_entity_type.py` 的**生成物**，重跑那个脚本会整表重写、把本次 908 行覆盖掉。

## 1. 交付物

| 产物 | 行数 | 内容 |
|---|---|---|
| `data/sources/entity_type_cz_20261117.csv` | 908 | 每条成分一行：`entity_type` / `rule` / `confidence` / `evidence` / `cz_report_category` / `n_products` / `n_components` / `markets` |
| `data/sources/cz_substance_merge_20261117.csv` | 3 | `from_substance` / `to_substance` / `依据` / 影响 product、product_component、variant 行数 / 复现 SQL |
| `data/sources/cz_likely_inn_who_review_20261117.csv` | 192 | 疑似 INN 逐条复核：`verdict`（确认 9 / 未确认 183）、WHO 母体、尾词、库内母体提示 |
| `data/entity_type.csv` | 12,793 → **13,701** | 追加 908 行（`git diff`：+908 / −0），原有 12,793 行逐字节未动 |
| `db/cz_substance_classify.py` | — | 只读脚本（`mode=ro`）；`--merge-into-entity-type` 才写 `data/entity_type.csv`，`--check` 只核对 |
| `data/sources/README.md` | +19 | 三个 CSV 的来源 / 依据 / 重跑方式 |

> 任务书写的是「补 `data/sources/entity_type.csv`」，但仓库里实际的分类表是 **`data/entity_type.csv`**
> （`data/sources/` 下没有同名文件）。本窗的处理：**真实表** `data/entity_type.csv` 追加 908 行，
> 同时在 `data/sources/` 留一份**带 provenance 的派生快照** `entity_type_cz_20261117.csv`（可复跑、可回滚）。

`entity_type` 取值**只用现有词表**（`etl/classify_entity_type.py` 的 8 值），细分信息放 `rule`，
报告建议的新值按下表映射，站点若按类型渲染可直接用 `rule` 或这份映射：

| 报告 §4 建议值 | 本窗落表 | 取值方式 |
|---|---|---|
| `homeopathic` | `homeopathic` | `entity_type='homeopathic'` |
| `herbal` | `herbal` | `entity_type='herbal'` |
| `vaccine_antigen` | `biologic` | `rule='cz_vaccine_antigen'`（42 条） |
| `excipient` | `material` | `rule='cz_excipient'`（10 条） |
| `inn_drug` | `inn_drug` | 直接（11 条） |
| `unknown` | **留空** | `entity_type=''`（389 条，见 §3.2） |

## 2. before / after（SQL 现查，可复跑）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/q.py "SELECT COUNT(*) AS n_sukl FROM substance WHERE source_id='sukl_dlp'"    # 908
& $py db/cz_substance_classify.py --check                                     # 现盘覆盖 + 分布 + About 分母
& $py db/cz_substance_classify.py --check --entity-csv "git:HEAD:data/entity_type.csv"  # before 快照
```

| 指标 | before（HEAD） | after（工作区） |
|---|---|---|
| `data/entity_type.csv` 行数 | 12,793 | **13,701** |
| 908 个新成分被覆盖 | **0 / 908** | **908 / 908** |
| 其中 `entity_type` 有值 | 0 | **519**（57.2%） |
| 其中 `entity_type` 留空 | — | **389**（42.8%） |
| 库内 `substance` 总数 | 13,648 | 13,648（**未变**） |
| `product` / `product_component` / `variant` | 594,781 / 767,080 / 15,248 | 同上（**未变**） |

> 908 个成分覆盖 **4,350 个 distinct product**（`markets`：CZ 870 + CZ,LV 31 + **7 个孤儿成分无产品**）。

## 3. 分类计数（报告口径 vs 本窗落表）

### 3.1 对照表

| 类别（报告 §1） | 报告数 | 本窗落表 | `entity_type` | `rule` |
|---|---|---|---|---|
| 顺势/稀释写法·`Dilutio` 字样 | 222 | **222** | `homeopathic` | `cz_homeopathic_dilutio_word` |
| 顺势/稀释写法·数字稀释度 | 187 | **187** | `homeopathic` | `cz_homeopathic_dilution_number` |
| 疫苗株/生物抗原 | 42 | **42** | `biologic` | `cz_vaccine_antigen` |
| 真实 INN（WHO 名录精确命中） | 2 | **2** | `inn_drug` | `cz_who_inn_exact` |
| 疑似 INN·WHO 母体 + 盐/酯尾词确认 | —（报告未拆） | **9** | `inn_drug` | `cz_who_inn_salt_form` |
| 生药/植物（含提取物） | 60 | **47** | `herbal` | `cz_botanical` |
| 　└ 词表误命中 → 留空 | — | **13** | 留空 | `cz_botanical_ambiguous` |
| 辅料/溶剂/化学品 | 20 | **10** | `material` | `cz_excipient` |
| 　└ 词表误命中 → 留空 | — | **10** | 留空 | `cz_excipient_ambiguous` |
| 疑似 INN·词形规则（WHO 未确认） | 192 | **183** | 留空 | `cz_inn_shape_unconfirmed` |
| 判不了（规则未命中） | 183 | **183** | 留空 | `cz_unknown_no_rule` |
| **合计** | **908** | **908** | — | — |

`--check` 现查（2026-11-17 01:0x）：

```
覆盖行 entity_type 分布：{'homeopathic': 409, '(留空)': 389, 'herbal': 47,
                          'biologic': 42, 'inn_drug': 11, 'material': 10}
```

> 与报告的两处差异，都是**新增证据后的收紧**，不是口径漂移：
> ① 报告 60 生药 / 20 辅料里各有若干条是**词表误命中**（§3.3），按「判不了就留空、不猜」留空；
> ② 报告写「192 待名录复核后定」→ 本窗复核出 9 条 WHO 母体 + 盐/酯尾词，标 `inn_drug`（明细 §5）。
> 复算报告原样口径：`classify(..., demote=False)` 打印仍为 60 / 20，见脚本输出「报告规则原样口径」。

### 3.2 389 条留空的构成（全部计数、不猜）

| 原因 | 条数 | 说明 |
|---|---|---|
| 疑似 INN 词形、WHO 名录未确认 | 183 | 其中 82 条库内存在同名母体（如 `Ademetionine Busilate`→`ademetionine`），101 条无任何母体 |
| 规则未命中（非顺势/生药/疫苗/辅料/INN 词形） | 183 | 含免疫球蛋白 4 条（84+70+18+2 产品）、mRNA 疫苗 2 条（40+6 产品）、`18F` 放射药 8 条、变应原 4 条 → 可用 `etl/classify_entity_type.py` 现成的 `BIOLOGIC_NAME` 词表补判（§8-5） |
| 生药词表误命中 | 13 | §3.3 |
| 辅料词表误命中 | 10 | §3.3 |

### 3.3 23 条「词表误命中」→ 留空待人工（按产品数排序）

| 名称 | 产品 | 报告规则命中 | 误命中原因（机械标记） |
|---|---|---|---|
| `Fludeoxyglucose 18F` | 74 | 辅料（GLUCOSE） | 放射性核素标记 `18F` |
| `Potassium Clavulanate And Microcristalline Cellulose` | 47 | 辅料（CELLULOSE） | 复方/共处理连接词 `And` |
| `Ascorbic Acid Coated With Ethylcellulose` | 43 | 辅料（CELLULOSE） | 包衣写法 `Coated With` |
| `Pancreas Powder` | 34 | 生药（POWDER） | 酶/脏器粉 `Pancreas` |
| `Vortioxetine Hydrobromide Benzyl Alcohol Hemi Solvate` | 16 | 辅料（ALCOHOL） | 溶剂化物 `Solvate` |
| `Darunavir Ethanolate` | 13 | 辅料（ETHANOL） | 溶剂化物 `Ethanolate` |
| `Freeze Dried Bacterial Lysate Om 85` | 13 | 生药（DRIED） | 微生物/益生菌 `Bacterial` |
| `Dried Saccharomyces Boulardii` | 8 | 生药（DRIED） | 微生物 `Saccharomyces` |
| `Pulsatilla Pratensis C 99` | 8 | 生药（PULSATILLA） | 顺势度标 `C 99`（字母在数字前，报告的数字稀释度规则没覆盖） |
| `Grass Pollen Allergens` | 6 | 生药（POLLEN） | 变应原提取物 `Allergen` |
| `Tree Pollen Allergens` | 6 | 生药（POLLEN） | 同上 |
| `Lactose With Cyanocobalamine Trituration 0 5 Per Cent` | 6 | 辅料（LACTOSE） | 研磨稀释 `Trituration` |
| `Ferric Sucrose With Starch` | 5 | 辅料（STARCH） | 共处理 `With Starch` |
| `Freeze Dried Saccharomyces Boulardii` | 5 | 生药（DRIED） | 微生物 `Saccharomyces` |
| `Ferrous Sulfate Dried` | 4 | 生药（DRIED） | 矿物/金属盐 `Ferrous`（也是合并候选，见 §4） |
| `Freeze Dried Escherichia Coli Lysate` | 4 | 生药（DRIED） | 微生物 `Escherichia` |
| `Weed Pollen Allergens` | 4 | 生药（POLLEN） | 变应原 `Allergen` |
| `Pollen Allergens` | 4 | 生药（POLLEN） | 变应原 `Allergen` |
| `Freeze Dried Lactobacillus Acidophilus` | 2 | 生药（DRIED） | 微生物 `Lactobacillus` |
| `Polygala Senega Syrup` | 2 | 辅料（SYRUP） | 剂型词 `Syrup`（实为生药糖浆） |
| `Tolu Balsam Syrup` | 2 | 辅料（SYRUP） | 剂型词 `Syrup` |
| `Freeze Dried Escherichia Coli` | 1 | 生药（DRIED） | 微生物 `Escherichia` |
| `Tuberculin Purified Protein Derivative For Human Use` | 1 | 辅料（PURIFIED） | 诊断用蛋白衍生物 `PPD` |

> 剩下的 10 条 `material` 里仍有 1 条需人工留意：`2 4 Dichlorobenzyl Alcohol`（109 产品，是含片里的**活性**
> 抗菌成分，也能当防腐剂）——机械规则判不了「活性 vs 辅料」，本窗保留 `material` + `confidence=low`，
> 下一窗口人工定。

## 4. 3 个确定性合并候选（方案 C 最小集，本任务只出清单）

| from | to | 依据 | 影响 product | 影响 product_component | 影响 variant |
|---|---|---|---|---|---|
| `acetic-acid-glacial`（Acetic Acid Glacial） | `acetic-acid`（Acetic Acid） | 去性状限定词后同名同物 | **6** | **6** | 1 |
| `ethinylestradiol-micronized`（Ethinylestradiol Micronized） | `ethinylestradiol`（Ethinylestradiol） | 同上 | **20** | **20** | 1 |
| `ferrous-sulfate-dried`（Ferrous Sulfate Dried） | `ferrous-sulfate`（Ferrous Sulfate） | 同上 | **4** | **4** | 1 |

复现（CSV 里也有这两条 SQL，已逐条实跑验证）：

```powershell
& $py db/q.py "SELECT s.substance_id, s.inn_en, t.substance_id, t.inn_en FROM substance s JOIN substance t ON t.substance_id='acetic-acid' WHERE s.substance_id='acetic-acid-glacial';"
& $py db/q.py "SELECT COUNT(*) AS variant_rows, (SELECT COUNT(*) FROM product_component pc WHERE pc.variant_id IN (SELECT variant_id FROM variant WHERE substance_id='acetic-acid-glacial')) AS component_rows FROM variant WHERE substance_id='acetic-acid-glacial';"
# → 1 | 6（另两条同理：1|20、1|4）
```

被引用面（写库前已查，全为 0 可直接删 from 行）：

```
variant 3（各 1，re-point 后归到 to）｜nickname 0｜drug_term 0｜confusable_pair 0｜dose_warning 0
ferrous-sulfate 侧已有 2 个 variant（ferrous-sulfate-2、ferrous-sulfate-sulphate），
variant 表只有主键、无 (substance_id,salt,hydrate,ester) 唯一约束 → re-point 不会撞键。
```

**不做合并的 2 个「像但不并」候选**（列证据，交 editorial 决策）：

| from | 母体 | 产品 | 不并的理由 |
|---|---|---|---|
| `alclometasone-dipropionate` | `alclometasone` | 4 | 酯型 → 母体涉及盐/酯基准（`base_fraction`）与等效判断，属 §1.3 红线外的人工/编辑决策 |
| `estradiol-benzoate` | `estradiol` | 1 | 同上 |

## 5. 192 个「疑似 INN」的 WHO 复核

### 5.1 结论

| 判定 | 条数 | 依据 |
|---|---|---|
| **确认**（WHO 母体 INN 命中 + 尾词全是盐/酯/水合物/成盐酸） | **9** | 见 5.2 |
| **未确认** | **183** | WHO 名录（1,737 条）无母体命中；其中 82 条库内存在同名母体（仅作二手提示，不作结论） |

复核分档（脚本内逐条落 `verdict` / `who_parent` / `who_tail` / `detail`）：
精确命中 **0** → 去盐命中 **0** → 去酯/去限定词命中 **0** → 母体 INN + 盐/酯尾词 **9** → 未确认 **183**。
（前两档为 0 是必然：分类规则里 WHO 命中会先被 `cz_who_inn_exact` 拿走。）

### 5.2 确认的 9 条（可逐条查 WHO 名录）

| 名称 | WHO 母体（`data/who_inn_names.csv`） | 尾词 | 产品 |
|---|---|---|---|
| `Ceftaroline Fosamil Acetate Solvate` | Ceftaroline fosamil | acetate solvate | 1 |
| `Ertugliflozin Pidolic Acid` | Ertugliflozin | pidolic acid | 60 |
| `Fostamatinib Disodium Hexahydrate` | Fostamatinib | disodium hexahydrate | 2 |
| `Lapatinib Ditosilate` | Lapatinib | ditosilate | 7 |
| `Lenalidomide Ammonium Chloride` | Lenalidomide | ammonium chloride | 14 |
| `Padeliporfin Dipotassium` | Padeliporfin | dipotassium | 2 |
| `Ruxolitinib Hemifumarate` | Ruxolitinib | hemifumarate | 12 |
| `Siponimod Fumaric Acid` | Siponimod | fumaric acid | 8 |
| `Sitagliptin Malate` | Sitagliptin | malate | 62 |

（另 2 条 WHO 精确命中：`Melphalan flufenamide` 1 产品、`Trimecaine` 17 产品 → `inn_drug`。）

### 5.3 为什么 183 条确认不了：名录快照不够，不是「不是 INN」

- 现快照 **1,737 条**（proposed 1,149 / recommended 588，覆盖 list 41–108 的**部分**条目），
  INN 全量约 6,000+；连 `SULFASALAZINE` 这种常用 INN 都不在快照里
  （证据：`Sulfasalazine With Povidone` 只能靠库内母体命中，WHO 无命中）。
- 因此这 183 条的正确状态是**「未确认」= 待名录**，不能反推成「不是 INN」；
  `etl/` 侧的 `map_inn` 已有「exact → salt → prefix」层级，补全名录后可批量重跑本复核。
- **未改 `substance` 表**（DB 哈希见 §7）。

## 6. 对 About 口径的影响（需要 Lead 知情）

`site/build.py::_atc_coverage` 在 build 时读 `data/entity_type.csv` 的 `inn_drug`：

| 指标 | before | after |
|---|---|---|
| 「药物实体」分母（`inn_drug` ∩ 库） | 8,447 | **8,458**（+11） |
| 其中有 ATC | 5,690 | 5,690 |
| 药物实体 ATC 覆盖率 | 67.4% | **67.3%** |
| 全部 substance / 有 ATC | 13,648 / 6,029（44.2%） | 不变 |

**若本版不想动这个公开数字**（一行回退，零风险）：把 `data/sources/entity_type_cz_20261117.csv` 里
11 条 `inn_drug`（`rule IN ('cz_who_inn_exact','cz_who_inn_salt_form')`）的 `entity_type` 改空，
再跑 `& $py db/cz_substance_classify.py --merge-into-entity-type`，About 分母即回到 8,447；
分类证据仍完整保留在 CSV 与 §5。

## 7. 验收（逐条给证据，全部实跑）

| # | 检查 | 结果 |
|---|---|---|
| 1 | 908 覆盖 | `--check` → **908 / 908**（before `git HEAD:data/entity_type.csv` → **0 / 908**） |
| 2 | 覆盖集合与库对账 | 908 行全部命中 `source_id='sukl_dlp'`；CSV 无重复 id（13,701 唯一）；无空 `rule` / 空 `evidence` |
| 3 | 未写库 | `data/drugs.db` SHA256 = `B6182140…D76A3C0D`（开工时与结束时一致），mtime 仍 `2026-11-15 10:04` |
| 4 | 数据体检 | `& $py db/check_data.py` → **exit 0**；products 594,781 / components 767,080 / substances 13,648 / variants 15,248（与改动前一致） |
| 5 | 快速 CI | `& $py deploy/ci_checks.py --fast` → **PASS 8 / FAIL 0 / SKIP 4，exit 0**（14.5s） |
| 6 | 脚本可编译 | `& $py -m py_compile db/cz_substance_classify.py` → exit 0 |
| 7 | 幂等 | 连跑两次 `--merge-into-entity-type`，`data/entity_type.csv` 哈希一致（`36DC185F…2452E7`） |
| 8 | diff 不越界 | `git diff --stat`：`data/entity_type.csv` +908 / −0；`data/sources/README.md` +19；本任务未改 `site/build.py`（该文件改动属 site-ui 的 task-1） |
| 9 | SQL 可复现 | §4 的 6 条 SQL 全部实跑，输出与 CSV 的 6/20/4、1/1/1 一致 |

## 8. 下一步（写库窗口）前置清单

1. **备份 + manifest**：窗口前复制 `data/drugs.db`（`run_all.py` 才自动备份，单独窗口要手动）；
   manifest 就用本任务两份 CSV（3 条 re-point + 908 条 `(substance_id, entity_type)`）。
2. **合并 3 条**（一个事务内，顺序固定）：
   `UPDATE variant SET substance_id='<to>' WHERE substance_id='<from>'` ×3 →
   `DELETE FROM substance WHERE substance_id IN ('acetic-acid-glacial','ethinylestradiol-micronized','ferrous-sulfate-dried')`；
   验收：`substance` 13,648 → **13,645**、`product_component` 仍 **767,080**、`variant` 仍 **15,248**、
   `PRAGMA foreign_key_check` 空、`db/check_data.py` exit 0、`collision`/`dose_warning` 不新增异常。
3. **`entity_type.csv` 的生成权**：该文件由 `etl/classify_entity_type.py` 整表重写，重跑会**丢掉本次 908 行**。
   下一窗口二选一：① 把 CZ 规则并入 `etl/classify_entity_type.py`；② 让该脚本读
   `data/sources/entity_type_cz_20261117.csv` 作为覆盖层。（本任务无权改 `etl/`，故只留清单。）
4. **补完整 INN 名录**（WHO IRIS/MedNet 全量，与现快照同源 CC BY-NC-SA 3.0 IGO），重跑
   `& $py db/cz_substance_classify.py --check` 与 §5 复核 → 183 条里应能再确认一批。
5. **183 条「判不了」补判**：用 `etl/classify_entity_type.py` 现成的 `BIOLOGIC_NAME`（免疫球蛋白 /
   mRNA / 细胞 / 血浆 / 变应原）与医疗气体/材料词表再跑一遍，预计能收掉约 18 条
   （免疫球蛋白 4、mRNA 疫苗 2、变应原 4、`18F` 放射药 8）。
6. **23 条词表误命中**（§3.3）人工定类型；`2 4 Dichlorobenzyl Alcohol` 活性 vs 辅料单独拍板。
7. **站点侧（不属于本任务）**：成分页按 `entity_type`/`rule` 显示类型说明 + 检索降权（报告 §7 任务 4），
   顺势/生药/疫苗/辅料页不得出现「可互换/等效剂量/换算」字样。

## 9. 已知缺口 / 未做

- **未做合并、未改 `substance` 表**：本任务零写库（队列要求今天不开写窗口）。
- **未改 `etl/classify_entity_type.py`**：不在本任务写权限内，只把「重跑会覆盖 §1 追加行」写进清单。
- **未扩 WHO 名录**：属新数据源接入（许可 + 抓取），按 §8-4 排下一窗口；本报告不下「不是 INN」的结论。
- **未做站点/文案/检索排序**：归 site-ui；本任务只保证数据层可被读。
- 红线遵守：不判断两药可互换、不做剂量换算、不手工标注 `collision`；
  `Alclometasone Dipropionate`/`Estradiol Benzoate` 因涉及盐/酯基准判定而未并入。
