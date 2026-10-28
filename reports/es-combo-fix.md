# ES CIMA 复方补全（task-38，dry-run + 副本验证）

> 日期：2026-10-27 ｜ 数据库：`data/drugs.db`（**只读**，本轮未写入；apply 只在 `.tmp/es-combos/drugs-test.db` 副本验证）
> 产物：`data/es_combo_candidates.csv`（208 行）、`etl/fix_es_combos.py`、本报告；证据 `.tmp/es-combos/`。
> 背景：早前审计说「ES 208 条四成分以上复方未入库」。本轮核实并补全。

---

## 1. 结论

1. **208 条的真实性质与任务描述不同**：它们不是「已入库但只挂 1 个成分」，而是 **CIMA 列表里被 `etl/ingest_cima.py` 整条跳过的 208 个注册**：
   - **203 条** `vtm.nombre = "multicomponente"`（CIMA 对 ≥4 成分复方/凝血因子/营养液/造影剂的占位名，ingest 直接 skip）；
   - **5 条** 列表缺 `nombre`/`vtm` 字段（ingest 也 skip）。
   - 数字对得上：CIMA 列表 25,501 − DB ES 产品 25,293 = **208**；其中「已有产品但组件数少于 CIMA 成分数」的 **0 条**（3,906 条多成分 VTM 全部已拆全）。
2. **CIMA 详情接口能恢复成分**：`/cima/rest/medicamento?nregistro=` 返回 `principiosActivos[]`（名称/数量/单位/顺序）。本轮抓取全部 **208 条详情**（0 失败），生成 `data/es_combo_candidates.csv`。
3. **成分映射结果（2,438 个成分）**：映射到库内已有 substance **2,143 个（87.9%）**；按产品分：
   - **105 条成分全部可映射**（`coverage=all`）；
   - **96 条部分可映射**（`partial`，缺 1–3 个成分居多）；
   - **7 条完全无法映射**（`none`）。
4. **本轮建议 apply（严格模式）= 102 个产品 / 932 个 product_component 行**（105 条 all 中 3 条是单成分产品，不是复方补全目标，排除）。
   预期：ES 产品 **25,293 → 25,395（+102）**；ES 组件 **29,931 → 30,863（+932）**。
5. **96 条部分映射不建议本轮自动入**：会造出「不完整复方」，影响成分页与 collision（同名复方配比风险）；先补映射词典更划算（见 §5）。
6. 副本实测：apply 102 → 重跑写 0（幂等）→ rollback 全部还原，无孤儿行；**真实库未被写入**（mtime/计数未变）。

---

## 2. 208 条从哪里来（证据）

| 检查 | 数值 | 说明 |
|---|---:|---|
| CIMA 列表缓存记录 | 25,501 | `data/raw/cima/page-*.json` |
| DB ES 产品 | 25,293 | `product where country='ES'` |
| 差额 | **208** | = 203 multicomponente + 5 缺字段 |
| CIMA 多成分 VTM（`A + B`）记录 | 3,906 | 全部已入库且组件数一致（2/3/4/5/6 成分分布吻合） |
| 已有产品但组件数 < VTM 成分数 | **0** | 所以不存在「只挂 1 个成分」的产品 |

> 早期审计的「208 条四成分以上复方未入库」指的就是这 208 条**整条缺失**，不是拆成分失败。

---

## 3. 候选构建（`data/es_combo_candidates.csv`，208 行）

1. 从 CIMA 列表找出 208 个 `nregistro`；
2. 逐个抓详情（缓存 `.tmp/es-combos/detail/<nreg>.json`，共 208 个，0 失败）——**只读网络 + 本地缓存**；
3. 用**西语→英语规则字典**（`etl/fix_es_combos.py` 内 `PHRASES` 200+ 条 + 盐词/水合词/反序规则 + `SubstanceIndex`）把 `principiosActivos[].nombre` 映射到库内已有 `substance`；
   - 优先英文市场（US/GB/CN 在用）的 substance，避免落到 ES 本地西语 id；
   - 只认「库内已存在」的 substance，**不新建成分**；
4. 强度取 `principiosActivos[].cantidad + unidad`（mg/g/mcg/iu/ml/%）；区间/非数值（如 `800-1920 UI`、`PEQUEÑAS CANTIDAD`）留空 — 932 个组件里 **792 个（85%）有数值强度**；
5. CSV 列：`product_id / nregistro / nombre / pactivos / cpresc / labtitular / forma_* / status* / brand_display / ing_es / ing_en / n_activos / n_mapped / coverage / confidence / missing / components_json / evidence_url / in_db`。
   `components_json` 含每个成分的 `{orden, name_es, sid, salt, value, unit, via}`，apply 可离线重放。

**映射分布：**

| coverage | 产品数 | 说明 |
|---|---:|---|
| all | 105 | 成分全部映射到库内 substance |
| partial | 96 | 缺 1–3 个成分居多（见 §5） |
| none | 7 | 见下 |

**7 条完全无法映射：**

| product_id | 产品 | 无法映射的成分 |
|---|---|---|
| ES-89446 / ES-80118 / ES-80119 | FEIBA（凝血酶原复合物，3 个规格） | COMPLEJO COAGULANTE ANTIINHIBIDOR（组合物，非单一 INN） |
| ES-33618 | BRONQUIDIAZINA 口服混悬液 | SULFAMETOXAZOL/BROMHEXINA/TRIMETOPRIMA/BALSAMO TOLU（复方+草药，映射未命中） |
| ES-61578 | DIURINAT 滴剂 | MAIZ/BETULA/EQUISETUM 等草药提取物 |
| ES-50169 | VINCISEPTIL 滴耳液 | FLUOCINOLONA/TETRACAINA/BENCIDAMINA/POLIMIXINA B（多成分，映射未命中） |
| ES-91687 | UROSYMBIO 6/0.4 mg | SOLIFENACINA/TAMSULOSINA（应为已知 INN，映射矩阵未覆盖，属词典缺口） |

**样例（all，前 10 条）：**

| # | product_id | 产品 | 成分数 | 映射成分（英文 INN） |
|---:|---|---|---:|---|
| 1 | ES-40869 | BECOZYME C FORTE 复合维生素 | 8 | Riboflavin + Nicotinamide + Pyridoxine + Calcium Pantothenate + Biotin + Cyanocobalamin + Ascorbic Acid + Thiamine |
| 2 | ES-76961 | BERIPLEX 1000 UI（凝血因子） | 6 | Coagulation Factor II + VII + IX + X + Protein C + Protein S |
| 3 | ES-69890 | BERIPLEX 500 UI | 6 | 同上 |
| 4 | ES-67057 | AMINOPLASMAL B.BRAUN 10%（氨基酸） | 18 | Isoleucine + Leucine + Lysine + … |
| 5 | ES-64983 | BALANCE 1.5% 葡萄糖腹膜透析液 | 5 | Glucose + Sodium Chloride + Sodium Lactate + Calcium Chloride + Magnesium Chloride |
| 6 | ES-67611 | ACCUSOL 35 钾 2 mmol/L | 6 | Calcium Chloride + Magnesium Chloride + Sodium Chloride + … |
| 7 | ES-67821 | VIAFLO PLASMALYTE 148 | 5 | Sodium Chloride + Potassium Chloride + Magnesium Chloride + … |
| 8 | ES-45434 | APIROSERUM 恢复液 | 7 | Calcium Chloride + Magnesium Chloride + Sodium Chloride + … |
| 9 | ES-64755 | BICAVERA 腹膜透析液 | 5 | Glucose + Sodium Bicarbonate + Sodium Chloride + … |
| 10 | ES-59669 | AMINOSTERIL N-HEPA 8% | 16 | Serine + Phenylalanine + Tryptophan + … |

> 这批 208 条主要是：复合维生素（~30）、氨基酸/TPN（~40）、电解质/透析液（~50）、凝血因子/血制品（~10）、造影剂、草药/局部复方。与「四成分以上复方」的描述一致。

---

## 4. 严格 apply 集与副本实测

**apply 集 = `coverage=all` 且去重后 ≥2 个成分 → 102 个产品 / 932 个组件。**

（105 条 all 里 3 条是单成分产品（1 个成分），不属于「复方补全」，排除；另有若干重复成分按 substance 去重，避免「Lysine + Lysine」式展示。）

| 步骤 | 副本状态 | 结果 |
|---|---|---|
| 初始（`data/drugs.db` 副本） | ES 产品 25,293；ES 组件 29,931 | 与真实库一致 |
| `--apply --db .tmp/es-combos/drugs-test.db` | **25,395；30,863** | 写 102 产品 / 932 组件 / 170 个新 name_key / 17 个新 variant；`ingest_run` +1 |
| 再跑 `--apply` | 25,395；30,863 | **写 0**（`already_product` 102，幂等；不清空清单） |
| `--rollback` | **25,293；29,931** | 删 102 产品 / 170 name_key / 17 variant；`product_name` 无孤儿；`ingest_run` 删除 |
| 真实库 `data/drugs.db` | 25,293；29,931 | **未被写入**（mtime 2026-10-27 11:29 未变；`cima_combo_fix` ingest_run=0） |

- apply 后样例（副本）：`ES-40869` 8 个维生素成分且有强度（Riboflavin 15 mg、Nicotinamide 50 mg、Biotin 0.15 mg、Cyanocobalamin 10 µg…）；`ES-76961` 6 个凝血因子成分；名字键含 trade（品牌）+ 西语成分组合 + 英文成分组合。
- `--apply/--rollback` 默认**拒绝写 `data/drugs.db`**；Lead 批准后加 `--allow-real`。
- rollback 修过一个真 bug：SQLite 连接默认 `foreign_keys=OFF`，不能依赖 `ON DELETE CASCADE`，现显式删 `product_name/product_component/corroboration` 再删 product，并清理无引用的 name_key/variant。

---

## 5. 部分映射（96 条）与可再挽回空间

96 条 partial 中很多只缺 **1–3 个成分**，属于词典缺口，不是数据缺失：

| 产品 | 成分 | 缺什么 |
|---|---|---|
| ES-81575 CLENSIA | 7 → 6 | SIMETICONA（simethicone） |
| ES-67267 ELEVIT | 19 → 18 | COLECALCIFEROL |
| ES-76222 GELASPAN | 6 → 5 | GELATINA SUCCINATO（明胶琥珀酸盐，非单一 INN） |
| ES-66709 ISOFUNDIN | 6 → 5 | MALICO ACIDO（malic acid） |
| ES-85115 / ES-62981 / ES-62983 AMINOMIX / AMINOVEN | 22→21、16→15 | TAURINA（taurine） |
| ES-67054 AMINOPLASMAL 10% E | 22 → 21 | FOSFATO DISODIO DODECAHIDRATO |
| ES-78892 AMINOPLASMAL 15% | 18 → 17 | ACETILCISTEINA |
| ES-59669 AMINOSTERIL N-HEPA | 16 → 15 | ACETICO ACIDO |

**若补 10–20 条词典（simeticone、taurine、colecalciferol、malic acid、acetycysteine、sodium phosphate、acetic acid 等），预计能把 20–30 条 partial 升为 all**；这是比「部分 apply」更安全的下一步（不改库、只补规则）。

**宽松模式 `--include-partial`（只写已映射成分）**：本次 dry-run 为 **191 产品 / 2,107 组件**（ES 25,293→25,484，组件 29,931→32,038）。**不建议本轮自动入**：产品会变成「成分不全的复方」，影响成分页、collision 与跨国对应；若要入，产品 `note` 必须标「部分成分未入库」。

---

## 6. 风险

1. **部分复方（96 条）**：不完整成分会误导 collision/成分页 —— 严格模式已规避。
2. **盐型扁平化**：本脚本按 substance 级补成分，variant 用 (substance, salt) 匹配/创建（17 个新 variant）；同一成分的不同盐（如赖氨酸醋酸盐/盐酸盐）在展示名上已去重，**会丢失盐型区分**。对成分页/检索无影响，但 D2 盐基折算需后续单独处理。
3. **强度只有 85%**：`principiosActivos` 的区间值（`800-1920 UI`）与非数值（`PEQUEÑAS CANTIDAD`、`Contiene + de un pa`）留空；932 组件中 792 有数值。
4. **产品状态/分类**：沿用 CIMA `estado/comerc` 与 ingest 口径；部分产品可能已撤市（照录，状态如实标注）。
5. **名称键 +170**：新的品牌/成分组合名键可能与其它市场同名（正常身份层，检索仍按候选集返回）。
6. **许可**：CIMA/AEMPS 数据「公开、可重用需署名」；来源链 `source_id='cima'`、`source_url` 指向 AEMPS 详情页，产品身份不变。

---

## 7. apply 建议

1. Lead 批准后：**备份 `data/drugs.db`** → `python etl/fix_es_combos.py --apply --db data/drugs.db --allow-real`（102 产品/932 组件）→ `python db/check_data.py` 复核（ES 产品 25,395、组件 30,863、`cima_combo_fix` ingest_run +1）。
2. 随后走站点重建/发布流程（本轮不跑 `site/build.py`）。
3. 先补 §5 的词典再做一轮 `--build-candidates`，可把 20–30 条 partial 升为 all；partial 一律不自动 apply。
4. 剩余 7 条 none（FEIBA 凝血酶原复合物、复方草药、Urosymbio 等）建议人工单独映射（Urosymbio 的 solifenacin/tamsulosin 其实是词典缺口，补上即可）。

---

## 8. 证据索引（`.tmp/es-combos/`）

| 文件 | 内容 |
|---|---|
| `probe.out.txt` / `probe2.out.txt` / `probe3.out.txt` / `probe4.out.txt` | CIMA 字段、208 差额、词典/映射评估、DB 英文成分存在性 |
| `fetch_details.py` / `fetch_details.out.txt` / `detail/*.json` | 208 条 CIMA 详情缓存（0 失败） |
| `build_candidates.py` / `build.out.txt` | 早期候选构建（被 `etl/fix_es_combos.py --build-candidates` 取代） |
| `es_combos_dryrun.json` | dry-run 全量（102 条与组件明细） |
| `apply1.out.txt` / `apply2.out.txt` / `rollback.out.txt` | 副本 apply（102）→ 幂等（0）→ rollback 实测 |
| `drugs-test.db` | apply 测试副本（450 MB，可删） |
| `check.py` | 真实库 vs 副本计数/孤儿行核对 |
| `data/es_combo_candidates.csv`（仓库内） | 208 行候选（含 components_json/evidence_url/coverage） |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp/es-combos/fetch_details.py                    # 208 条 CIMA 详情（有缓存则跳过）
& $py etl/fix_es_combos.py --build-candidates            # → data/es_combo_candidates.csv
& $py etl/fix_es_combos.py                               # dry-run（只读）
Copy-Item data/drugs.db .tmp/es-combos/drugs-test.db -Force
& $py etl/fix_es_combos.py --apply --db .tmp/es-combos/drugs-test.db
& $py etl/fix_es_combos.py --rollback --db .tmp/es-combos/drugs-test.db
```

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 git / 发布 / `site/build.py`。_
