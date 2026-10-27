# ATC 口径修正 + ChEMBL 补 ATC（task-24，dry-run）

> 日期：2026-10-27 ｜ 站点版本：v0.3.5（未改站） ｜ 数据库：`data/drugs.db`（**只读**，本轮未写入）
> 产物：`etl/classify_entity_type.py`、`etl/fetch_chembl_atc.py`、`etl/ingest_chembl_atc.py`、`data/entity_type.csv`、本报告；证据 `.tmp/atc/`。
> apply / 幂等 / rollback 只在 `.tmp/atc/drugs-test.db` 副本上验证；真实库 mtime 未变、ATC 计数未变（5,890）。
>
> **并发提示**：本报告数字是 **2026-10-27 09:37–09:44 的只读快照**（substance 12,793 / ATC 5,890）。
> 09:45 复核时真实库已被其它任务更新为 substance 12,790 / ATC 5,889（`data/entity_type.csv` 与
> dry-run 均按快照生成）。正式 apply 前必须重跑 `classify_entity_type.py` + `ingest_chembl_atc.py`，
> 让 CSV/匹配与新快照对齐；本报告结论（比例与量级）不受 ±3 个成分影响。

---

## 1. 结论

1. **旧的 ATC 覆盖率分母不对**：`5,890 / 12,793 = 46.0%` 把生药、顺势药、医疗气体、营养配方、ARTG 解析残留都算进分母了。
   按 `data/entity_type.csv` 的新口径：**药物实体（inn_drug）ATC 覆盖 64.9%（5,579 / 8,595）**；含生物制品为 **63.9%（5,733/8,976）**；全部 substance 仍报 46.0%（两个口径同时公布，分母透明）。
2. **6,903 个缺 ATC 的 substance 里 3,887 个不是 INN 药物实体**：homeopathic 1,776、other 1,001、herbal 447、biologic 227、food 179、combination 159、material 98；真正的 `inn_drug` 缺口只有 **3,016 个**（任务原估 4,094 非药物实体，实测 3,887，同量级）。
3. **ChEMBL 可补 192 个成分（已 dry-run + 副本 apply 验证）**：ATC 全部 substance 46.0%→47.5%；**药物实体分母 62.7%→64.8%**；inn_drug 64.9%→67.1%。192 条全部来自 `atc_class`（name_exact 122、name_base 61、name_paren 8、name_spelling 1）；另有 129 个多码歧义跳过（含 molecule 端点查出的 Sodium Fluoride 3 码、Glycerin 2 码等，按「宁可缺不可错」不写）。
4. 结论：**ATC 缺口的大头（3,887/6,903 = 56%）不是「数据没抓到」，是「本来就没有 ATC 的非药物实体」**。剩下的 3,016 个 inn_drug 缺口，ChEMBL 只能补 192（6.4%），其余需要 WHO MedNet INN / RxNorm / 商业库（见 `reports/opensource-drug-data-20261026.md`）。
5. 建议对外口径改为双指标：**「药物实体 ATC 覆盖 64.9%（补 ChEMBL 后 67.1%）」+「全部 substance 46.0%」**，并在 About 说明分母含义。

---

## 2. 口径与数据

### 2.1 分类方法（`etl/classify_entity_type.py`）

只读 `data/drugs.db`，按**可解释规则**给 12,793 个 substance 打 8 类之一（命中即停，写 `rule` + `evidence` + `confidence`）：

| 顺序 | entity_type | 规则 | 证据 |
|---|---|---|---|
| 1 | combination | 名称含 ` + ` / ` / ` / ` and ` / ` y ` / `^co-` | 名称 |
| 2 | homeopathic | 产品 ≥80% 来自 openFDA `UNAPPROVED HOMEOPATHIC`；或名称含 homeopath/nosode | product.category |
| 3 | material | 产品 ≥50% 来自 `UNAPPROVED MEDICAL GAS`；或名称是气体/元素/矿物/辅料/残留 | category/name |
| 4 | other | ARTG 解析残留：`Equivalent: …`、`tribasic`、`unspecified`、`not stated` | 名称 |
| 4b | inn_drug / combination | 中文名（NHSA 化学药；含「复方」→combination） | 名称 |
| 5 | food | 肠内营养/氨基酸配方/蛋白配方/维生素矿物质复合物/食材 | 名称 |
| 6 | herbal | 植物部位词（root/leaf/seed/flower/bark/extract…） | 名称 |
| 7 | biologic | 产品 ≥50% 是 `BLA`；或名称含 -mab/-cept/-fusp/vaccine/immunoglobulin/insulin… | category/name |
| 8 | material | 气体/元素/辅料关键词（oxygen/silver/petrolatum/water for injection…） | 名称 |
| 9 | inn_drug | 默认（INN 形态名称） | 名称 |
| 10 | other | 无法判断 | 兜底 |

输出 `data/entity_type.csv`（12,793 行）：`substance_id, entity_type, rule, confidence, evidence, n_products, markets, with_atc`。

### 2.2 分类结果与 ATC 覆盖率

| entity_type | 数量 | 有 ATC | ATC% | 占全库 | 缺 ATC |
|---|---:|---:|---:|---:|---:|
| inn_drug | 8,595 | 5,579 | **64.9%** | 67.2% | 3,016 |
| biologic | 381 | 154 | 40.4% | 3.0% | 227 |
| herbal | 496 | 49 | 9.9% | 3.9% | 447 |
| homeopathic | 1,796 | 20 | 1.1% | 14.0% | 1,776 |
| material | 120 | 22 | 18.3% | 0.9% | 98 |
| combination | 169 | 10 | 5.9% | 1.3% | 159 |
| food | 188 | 9 | 4.8% | 1.5% | 179 |
| other | 1,048 | 47 | 4.5% | 8.2% | 1,001 |
| **合计** | **12,793** | **5,890** | 46.0% | 100% | 6,903 |

**新分母覆盖率：**

| 分母 | 补 ChEMBL 前 | 补 ChEMBL 后 |
|---|---:|---:|
| 全部 substance | 5,890/12,793 = **46.0%** | 6,082/12,793 = **47.5%** |
| 药物实体（inn_drug+biologic+food） | 5,742/9,164 = **62.7%** | 5,934/9,164 = **64.8%** |
| 仅 inn_drug | 5,579/8,595 = **64.9%** | 5,771/8,595 = **67.1%** |

### 2.3 分类质量抽验（.tmp/atc/validate.out.txt）

- `homeopathic` 规则命中 1,796 个，**98.9%** 的产品 category 确实是 `UNAPPROVED HOMEOPATHIC`。
- `cn-` 前缀 1,827 个全部归 `inn_drug`（NHSA 化学药；ATC 5,890 里 CN 贡献 1,827），无一漏分。
- `other` 1,048 个里 216 个是 `Equivalent: …` ARTG 解析残留、828 个是 dm+d `Generic …` 名称残留 —— 都是**入库层 artifact**，不应有 ATC。
- 抽样肉眼核对（每类 12 条，见 `.tmp/atc/validate.out.txt`）：herbal/food/other/biologic 基本正确；`inn_drug` 里有少量误收（如 `Marsdenia Cundurango`、`Didecyldimethylammonium Chloride`），属启发式误差（**抽验估计精度 ~95%，未做严格双人标注**）。
- 待改进（下一轮）：single-word 生药名（Arnica/Stillingia 等）、消毒剂/器械清洗剂归 material；dm+d `Generic …` 前缀统一标 artifact。

---

## 3. ChEMBL 补 ATC

### 3.1 来源与许可

- 来源：**ChEMBL（EMBL-EBI）ATC classification** — `https://www.ebi.ac.uk/chembl/api/data/atc_class.json`
- 抓取：`etl/fetch_chembl_atc.py --download`，分页 6 次（limit=1000，限速 1s），**5,579 行 / 5,579 个 ATC 码 / 4,841 个 WHO 名**，缓存 `data/raw/chembl/atc_class.json`（meta 里带许可/抓取时间/行数）。
- **许可：CC BY-SA 4.0**（`https://creativecommons.org/licenses/by-sa/4.0/`）。可再发布/改编，**须署名 + 以相同方式共享**。本站只取「7 位 ATC 码 + WHO INN 名」做对齐，**不复制 WHOCC 的 DDD 文本**；`atc_name` 用 ChEMBL 的 `who_name`（INN），不是 WHOCC 官方 ATC 文本。
- 说明：ATC 码本身源自 WHOCC；ChEMBL 以 CC BY-SA 4.0 再分发这些分类。对外展示按 ChEMBL 署名 + CC BY-SA 处理（风险与 Wikidata 路线同级，见 §6）。

### 3.2 匹配结果（`etl/ingest_chembl_atc.py` dry-run）

```text
候选：atc 为空 且 entity_type ∈ {inn_drug, biologic, food} = 3,422 个
命中：name_exact 122 · name_base 61 · name_paren 8 · name_spelling 1 = 192
      歧义跳过 129（多码且无唯一 7 位码）· 未匹配 3,101
molecule 端点查漏（--molecule-check 25）：25 个高产品数未命中成分中 5 个查到 ATC，
      但都是多码（Sodium Fluoride 3 码 / Glycerin 2 码 / Glycopyrronium 2 码 /
      Sodium Monofluorophosphate 2 码 / Calcium Pantothenate 2 码）→ 按规则跳过
```

**抽样 20 条（按产品数降序）：**

| # | substance_id | inn_en | 类型 | 路径 | ATC | atc_name | 产品数 |
|---:|---|---|---|---|---|---|---:|
| 1 | stannous-fluoride | Stannous Fluoride | inn_drug | name_exact | A01AA04 | stannous fluoride | 180 |
| 2 | dosulepin | Dosulepin | inn_drug | name_exact | N06AA16 | dosulepin | 78 |
| 3 | valaciclovir | Valaciclovir | inn_drug | name_exact | J05AB11 | valaciclovir | 77 |
| 4 | glucosamine-hydrochloride | Glucosamine Hydrochloride | inn_drug | name_base | M01AX05 | glucosamine | 60 |
| 5 | dexamfetamine | Dexamfetamine | inn_drug | name_exact | N06BA02 | dexamfetamine | 54 |
| 6 | pizotifen | Pizotifen | inn_drug | name_exact | N02CX01 | pizotifen | 46 |
| 7 | dicycloverine | Dicycloverine | inn_drug | name_exact | A03AA07 | dicycloverine | 44 |
| 8 | conjugated-oestrogens | Conjugated Oestrogens | inn_drug | name_spelling | G03CA57 | conjugated estrogens | 32 |
| 9 | phytomenadione | Phytomenadione | inn_drug | name_exact | B02BA01 | phytomenadione | 32 |
| 10 | glucosamine-sulfate-sodium-chloride | Glucosamine Sulfate Sodium Chloride | inn_drug | name_base | M01AX05 | glucosamine | 30 |
| 11 | hyaluronidase-human-recombinant | Hyaluronidase (Human Recombinant) | biologic | name_paren | B06AA03 | hyaluronidase | 23 |
| 12 | naftidrofuryl | Naftidrofuryl | inn_drug | name_exact | C04AX21 | naftidrofuryl | 21 |
| 13 | methylcellulose-4000-mpa-s | Methylcellulose (4000 Mpa.S) | inn_drug | name_paren | A06AC06 | methylcellulose | 18 |
| 14 | chlortalidone | Chlortalidone | inn_drug | name_exact | C03BA04 | chlortalidone | 18 |
| 15 | chlorphenamine-maleate | Chlorphenamine Maleate | inn_drug | name_base | R06AB04 | chlorphenamine | 16 |
| 16 | lonapegsomatropin | Lonapegsomatropin | biologic | name_exact | H01AC09 | lonapegsomatropin | 15 |
| 17 | nisoldipine | Nisoldipine | inn_drug | name_exact | C08CA07 | nisoldipine | 14 |
| 18 | fludroxycortide | Fludroxycortide | inn_drug | name_exact | D07AC07 | fludroxycortide | 14 |
| 19 | lysine-hydrochloride | Lysine Hydrochloride | inn_drug | name_base | B05XB03 | lysine | 13 |
| 20 | toremifene | Toremifene | inn_drug | name_exact | L02BA02 | toremifene | 12 |

> `name_base`/`name_paren` 例：Glucosamine Hydrochloride → glucosamine（同一母体 ATC）、
> Methylcellulose (4000 Mpa.S) → methylcellulose。只补「ATC 唯一」的，不猜。

### 3.3 apply / 幂等 / rollback 实测（副本，未写真实库）

| 步骤 | 副本 ATC 计数 | 结果 |
|---|---:|---|
| 初始（`data/drugs.db` 副本） | 5,890 | 与真实库一致 |
| `--apply --db .tmp/atc/drugs-test.db` | **6,082** | 写 192（事务提交），`source` +1、`ingest_run` +1 |
| 再跑一次 `--apply` | 6,082 | **写 0**（幂等；不清空 apply 清单） |
| `--rollback` | **5,890** | 192 条按清单还原（`ingest_run` 删除；`source` 行保留作历史） |
| 真实库 `data/drugs.db` | 5,890 | mtime 未变，**未被写入** |

- `--apply`/`--rollback` 有硬保护：目标解析为 `data/drugs.db` 时直接拒绝（任务要求只在副本验证）。
- 副本 `PRAGMA integrity_check` = ok（见 .tmp/atc/apply1.out.txt 等），回滚后计数与初始一致。

---

## 4. 接入 About 文案建议（zh / en / es，待 Lead 决定，本轮未改站）

> zh：`ATC 分类：Wikidata P267（CC0）与 ChEMBL（EMBL-EBI，CC BY-SA 4.0）派生的 ATC 码；本站只做码值对齐，不复制 WHOCC 的 ATC/DDD 文本。ATC 覆盖率按「药物实体」计（生药/顺势/材料/营养配方不计入分母）。`
>
> en: `ATC codes: derived from Wikidata P267 (CC0) and ChEMBL (EMBL-EBI, CC BY-SA 4.0); we align code values only and do not copy WHOCC ATC/DDD text. ATC coverage is measured against drug entities (herbals, homeopathics, materials and nutrition formulas are excluded from the denominator).`
>
> es: `Códigos ATC: derivados de Wikidata P267 (CC0) y ChEMBL (EMBL-EBI, CC BY-SA 4.0); solo alineamos los códigos y no copiamos el texto ATC/DDD de WHOCC. La cobertura ATC se calcula sobre «entidades farmacológicas» (se excluyen hierbas, homeopatía, materiales y fórmulas nutricionales del denominador).`

同时建议覆盖度数字改成双指标（`coverage` 视图/README/About 同步，属 Lead 的发布动作）：
`ATC（药物实体）64.9% → 67.1%（ChEMBL） ｜ ATC（全部成分）46.0% → 47.5%`。

> 本文件不写 `site/build.py`、`site/dist`、README、CHANGELOG（不在写范围）；这些同步需 Lead 在发布轮处理。

---

## 5. 缺口与风险

1. **剩余 inn_drug 缺 ATC 3,016 个**（补 192 后剩 2,824 个）：高产品数缺口仍有 Sodium Fluoride(1,145)/Clavulanate(601)/Camphor(452)/Aciclovir(318)/Glycerin(299) 等，多为**多 ATC 码或非 WHO 名单品种**，ChEMBL 规则自动跳过；需要 WHO MedNet INN / RxNorm / 商业库（`reports/opensource-drug-data-20261026.md` §3.3）。
2. **分类是启发式**：预计整体精度 ~95%，`inn_drug` 有少量生药/消毒剂误收；不影响「非药物实体 3,887」的量级结论，但若对外公开新分母，建议再抽 100 条人工复核。
3. **许可**：ChEMBL CC BY-SA 4.0 的 share-alike 要求衍生映射以同许可共享；ATC 码本身是 WHOCC 第三方内容。对外展示按「ChEMBL 署名 + CC BY-SA」处理，与现有 Wikidata 路线并存；若要更干净，可只保留「码 + INN 名」并注明。
4. **provenance**：`substance` 表没有 source 列（与 Wikidata ATC 同限制）；逐条出处 = 缓存 + 脚本版本 + `ingest_run` note（批次级）。若要逐条 provenance，需要 schema 加列（下一轮评估）。
5. **apply 到真实库需 Lead 决策**：本报告只验证了副本；真实库写入应与其它入库任务串行（AGENTS.md §7），并在 apply 前备份。

---

## 6. 下一步（可执行，带验收）

| 优先级 | 动作 | 验收 |
|---|---|---|
| P0 | Lead 决策：是否把 ChEMBL `--apply` 写入真实库（192 条），并在 About 加 CC BY-SA 署名 | `db/check_data.py` 前后 ATC 5,890→6,082；`coverage` 视图更新 |
| P0 | 站点/README 改用双口径（inn_drug 64.9%、全部 46.0%） | 三处数字一致（README/About/CHANGELOG） |
| P1 | 分类抽 100 条人工复核 + 修 single-word 生药/消毒剂规则 | 新精度 ≥97%；`data/entity_type.csv` 重生成 |
| P1 | 把 `classify_entity_type.py` 接进 `run_all.py`（在 ChEMBL ATC ingest 前） | 全量重建可复现 |
| P2 | WHO MedNet / RxNorm 评估补剩余 2,824 个 inn_drug（需授权/注册） | 见开源调研报告 P2 清单 |

---

## 7. 证据索引（`.tmp/atc/`）

| 文件 | 内容 |
|---|---|
| `classify.out.txt` / `classify_final.out.txt` | 分类统计、新分母覆盖率、各类型抽样 |
| `data/entity_type.csv`（仓库内） | 12,793 行分类结果（substance_id/entity_type/rule/confidence/evidence/…） |
| `validate.out.txt` | 抽验：cn- 全 inn_drug、homeopathic 纯度 98.9%、各类样例、other 残留清单 |
| `fetch_chembl.out.txt` | ChEMBL 分页抓取日志（5,579 行 / 4,841 WHO 名） |
| `data/raw/chembl/atc_class.json`、`meta.json` | 缓存（含许可/抓取时间）；`molecule_lookup.json` 为 molecule 端点查漏缓存 |
| `ingest_dryrun.out.txt` / `ingest_final.out.txt` / `chembl_atc_dryrun.json/.txt` | dry-run 统计与抽样 20 条 |
| `apply1.out.txt` / `apply2.out.txt` / `rollback.out.txt` | 副本 apply / 幂等 / rollback 实测 |
| `drugs-test.db` | apply 测试副本（450 MB，可删） |
| `check_counts.py` / `probe_db.py` / `probe2.py` | 只读探查与计数脚本 |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/classify_entity_type.py                 # → data/entity_type.csv + 覆盖率
& $py etl/fetch_chembl_atc.py --download          # → data/raw/chembl/（6 次请求，限速 1s）
& $py etl/ingest_chembl_atc.py --molecule-check 25 # dry-run
Copy-Item data/drugs.db .tmp/atc/drugs-test.db -Force
& $py etl/ingest_chembl_atc.py --apply --db .tmp/atc/drugs-test.db
& $py etl/ingest_chembl_atc.py --rollback --db .tmp/atc/drugs-test.db
```

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 git / 发布 / `site/build.py`。_
