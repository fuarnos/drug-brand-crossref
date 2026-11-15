# CZ 新增 908 成分质量审查 + 处置方案（只读）

- 任务：task-14（工位 phaseb-data，只读）；时间 北京时间 2026-11-16 03:30–04:00
- 范围：v0.13.0 CZ 窗口新建的 **908 个 substance**（`substance.source_id='sukl_dlp'`）与其 2,108 个无组件产品的关联名字
- 纪律：**未写库、未改 `etl/`·`site/`·`db/`、未 commit**；库用 `mode=ro` 只读
- 复现脚本：`.tmp/m1/substance_quality.py`（只读快照+库；输出 `.tmp/m1/substance_quality.json`）

## 0. 结论（先行）

1. **908 个新成分里约 45% 不是「药物成分」**：顺势/稀释写法 **409**（45.0%）、生药/植物 **60**、疫苗株/生物抗原 **42**、
   辅料/溶剂/化学品 **20**；真正 INN 侧只有 **2 个**命中 WHO 名录 + **192 个**词形像 INN 待复核。
2. **`data/entity_type.csv` 对这 908 个覆盖为 0**（12,793 行全是旧成分）；`with_atc=0`（全部无 ATC）、
   `confidence` 906 medium / 2 high——分类信息缺口是「整批缺失」，不是个别遗漏。
3. **可合并到已有成分的只有 3 个**（`Acetic Acid Glacial`→`Acetic Acid`、`Ethinylestradiol Micronized`、
   `Ferrous Sulfate Dried`）——「改名合并」收益很小，不能当主方案。
4. **推荐方案 A（只分类不改库）+ 3 个合并顺带做（方案 C 的最小集）**；方案 B（规则层 non-substance 词表）
   只用于**真正的辅料/溶剂**（908 里的 20 个 + 未入库 170 个名字里的 24 个），不要把它当处理顺势/生药的手段。
5. 前置条件：现有 `data/who_inn_names.csv` 只有 **1,737 条**（真实 INN 约 6,000+），
   「真实 INN/盐型」判定需要补一份完整 INN 名录，否则 192 个「疑似 INN」只能标待复核。

## 1. 分类计数（908 个，规则见 §5）

| 类别 | 数量 | 占比 | 例子（≤3） |
|---|---|---|---|
| **顺势/稀释写法** | **409** | 45.0% | `Abrotanum Dilutio Homeopathica`、`Abrus Precatorius 6 C`、`Achillea Millefolium 3 D` |
| ├ 含 `Dilutio Homeopathica` 字样 | 222 | 24.5% | `Ledum Palustre Tinctura Basica Ad Usum Homeopathicum` |
| └ 数字稀释度（`6 C` / `3 D` / `30 CH`…） | 187 | 20.6% | `Abrus Precatorius 6 C`、`Achillea Millefolium 3 D` |
| **其它·疑似 INN（词形规则，待名录复核）** | **192** | 21.1% | `Acetyltyrosine`、`Ademetionine Busilate`、`Alclometasone Dipropionate` |
| **其它·无法判定** | **183** | 20.2% | `Aconite Tincture`、`Alfa Tocopheryl`、`Aminofluoride Mix` |
| **生药/植物（含提取物）** | **60** | 6.6% | `Alchemilla Herb`、`Arnica Tincture`、`Bean Pericarp Without Seeds` |
| **疫苗株/生物抗原** | **42** | 4.6% | `Neisseria Meningitidis Group A Polysaccharide`、`Haemophilus Influenzae Type B Polysaccharide…` |
| **辅料/溶剂/化学品** | **20** | 2.2% | `2 4 Dichlorobenzyl Alcohol`、`Acetic Acid Glacial`、`Ascorbic Acid Coated With Ethylcellulose` |
| **真实 INN（WHO 名录命中）** | **2** | 0.2% | `Melphalan flufenamide`、`Trimecaine` |
| 合计 | **908** | 100% | — |

补充事实：

- **7 个是孤儿成分**（没有任何 `product_component` 引用）：`Aconite Tincture`、`Dorocubicel`、
  `Granulated Calcium Carbonate`、`Haemophilus Influenzae Type B…`、`Ledum Palustre Tinctura…` 等；
- **407 个只覆盖 ≤2 个产品**（长尾），Top：`Colecalciferol` 128、`2 4 Dichlorobenzyl Alcohol` 109、
  `Human Normal Immunoglobulin For Intravenous Administration` 84；
- `inn_zh` 全为 NULL、无 ATC → 成分页只能显示英文名（页面需要「类型说明」而不是「药物说明」）。

## 2. 与 `data/entity_type.csv` 对照

| 指标 | 值 |
|---|---|
| `entity_type.csv` 现有行数 | 12,793（全部旧成分） |
| 908 个新成分被覆盖 | **0 / 908** |
| 未被覆盖（= 本轮要补） | **908** |
| 其中 `with_atc=1` | **0**（`ensure_substance` 只写 `substance_id/inn_en/source_id/method/confidence/decided_at/name_lang`，不带 ATC） |
| 其中 `confidence` | medium 906 / high 2（WHO 名录命中） |
| 与 `data/who_inn_names.csv` 对照 | 命中 **2**（该快照仅 1,737 条，覆盖率远不足以做 INN 判定） |

> 结论：908 个是「同一批、同一规则」产生的缺口，适合**批量补分类**（一次脚本 + 人工抽检），
> 不适合逐条人工核对——但「疑似 INN」192 个必须有名录依据才能定，不能凭词尾拍板。

## 3. 未入库的 170 个名字（167 个黑名单 + 3 个边界）

上一窗口「判不了就不写库」的 170 个名字 / 2,400 行，按同一套规则分类：

| 类别 | 名字数 | 例子 |
|---|---|---|
| 生药/植物提取物 | 70 | `SAW PALMETTO EXTRACT`、`NETTLE ROOT DRY EXTRACT`、`AGNUS CASTUS FRUIT DRY EXTRACT` |
| 疫苗株/病毒 | 67 | `LIVE ATTENUATED VARICELLA VIRUS`、`POLIOMYELITIS VIRUS TYPE 1, INACTIVATED` |
| 辅料/溶剂 | 24 | `BENZALKONIUM CHLORIDE SOLUTION`、`HUMAN ALBUMIN SOLUTION`、`CHLORHEXIDINE DIGLUCONATE SOLUTION` |
| 其它（血浆蛋白 / 抗蛇毒血清 / 细胞制品） | 9 | `HUMAN PLASMA PROTEIN`、`VIPER VENOM ANTISERUM, EUROPEAN`、`TRANSDUCED CD34+ CELLS…` |

→ **2,108 个无组件 CZ 产品**的成因里，**约 137 个名字（70+67）其实是真活性物**（生药提取物/疫苗抗原），
按「non-substance 词表」删要慎重；真正该挡的是 24 个辅料/溶剂 + 9 个特殊生物制品。

## 4. 三种处置方案对比

| 维度 | **A. 只分类不改库**（补 `entity_type.csv`） | **B. 规则层剥离**（`cz.py` 加 non-substance 词表） | **C. 合并到已有成分** |
|---|---|---|---|
| 做什么 | 908 行补进 `data/entity_type.csv`：`homeopathic` / `herbal` / `vaccine_antigen` / `excipient` / `inn_drug`；成分页按类型显示一句说明、检索降权 | 在 `etl/markets/cz.py` 建词表（OIL/SOLUTION/VIRUS/EXTRACT…），下一窗口把 170 个名字整条不写组件 | 把 3 个重复实体 re-point 到已有成分（`variant.substance_id` 改指），删新成分 |
| 改动面 | `data/entity_type.csv`（数据表，非 schema）+ 成分页/检索排序（site-ui） | `etl/` + 下一次写库（T1 重跑或补丁脚本） | DB 写窗口（`variant`/`substance` + 组件 re-point） |
| 风险 | 低：不动 DB、不丢数据；缺点是需要 site-ui 配合展示 | 中：**会丢信息**（SÚKL 把这些列为活性成分，删了产品变「成分未收录」）；词表维护成本高 | 低但收益小：只清 3 个 |
| 覆盖问题面 | 908 全量（含顺势/生药/疫苗/辅料） | 只能挡 24 个辅料/溶剂（+9 特殊生物），挡不住顺势 409 | 3 / 908 |
| 可逆性 | 完全可逆（CSV 可改回） | 需 manifest 回滚；重跑成本高 | 需 manifest；re-point 可逆 |
| 工作量 | 0.5 天（脚本分类 + 人工抽检 60 条） | 1–2 天（词表 + 复算 + 回归） | 0.5 天（一个窗口） |

### 推荐：**A 为主 + C 的最小集（3 个）顺带做；B 只做「真辅料」窄版**

理由：

1. 45% 是顺势稀释写法、6.6% 生药、4.6% 疫苗——它们**不是数据错误，是 SÚKL 注册库里的真实条目**
   （顺势/生药产品在 CZ 合法上市）。删掉会让「这盒药是什么」失去可检索的活性物，违反身份对应目标；
2. 页面/检索的问题本质是「**把非药物实体当药物展示**」，用类型标注 + 排序降权即可解决，不必删数据；
3. 方案 B 只对 24 个辅料/溶剂成立；把生药提取物/疫苗抗原当 non-substance 会与 EU 层口径冲突
   （EU 层把疫苗株也按成分处理）；
4. 方案 C 的 3 个是**确定性重复**（去限定词后同名），做掉可减少 3 个成分页，成本极低；
5. 前置条件（必须写进任务）：补一份完整 **WHO INN 名录**（现快照 1,737 条不够），否则 192 个「疑似 INN」
   无法定论。建议同时用「库内 13,648 个现有成分名 + `data/sources/inn_zh_salt_forms_20261115.csv`」做第二道匹配。

### 方案 A 的分类落表建议（`entity_type` 取值）

| entity_type | 数量（908 内） | 页面/检索处理 |
|---|---|---|
| `homeopathic` | 409 | 成分页标「顺势稀释制剂（非剂量单位）」，不进「药物成分 Top」；不显示可互换/剂量块 |
| `herbal` | 60 + 70（未入库） | 标「生药/植物提取物」，显示来源植物名 |
| `vaccine_antigen` | 42 + 67（未入库） | 标「疫苗抗原/株」，只做身份对应 |
| `excipient` | 20 + 24（未入库） | 标「辅料/溶剂」，成分页可保留但默认折叠、检索降权 |
| `inn_drug` | 2（WHO）+ 192（待名录复核后） | 正常药物成分 |
| `unknown` | 183 | 先标 unknown，人工抽检后再定（不阻塞） |

## 5. 分类规则（可复核，不用「感觉」）

按顺序命中，先命中先生效（脚本 `.tmp/m1/substance_quality.py`）：

1. **顺势**：名字含 `\b\d{1,3}\s*(C|CH|D|DH|LM|MK|X)\b`（数字稀释度）或含 `DILUTIO`/`HOMEOPATH`/`DILUTION`；
2. **疫苗**：含 `VIRUS|VACCINE|VACCINUM|TOXOID|INACTIVATED|SEROTYPE|POLYSACCHARIDE|ANTIGEN|ANATOXIN|BACTERIN`；
3. **真实 INN**：归一后（或去盐母体）命中 `data/who_inn_names.csv`；
4. **库内已有同名实体**：归一后（或去盐母体）命中库内其它 substance（= 合并候选）；
5. **生药**：含 `HERBA|RADIX|FOLIUM|FLOS|FRUCTUS|SEMEN|CORTEX|RHIZOMA|TINCTURA|EXTRACT|LEAF|ROOT|FRUIT|HERB|FLOWER|BARK|SEED|POLLEN|…`；
6. **辅料/溶剂**：含 `OIL|SOLUTION|WATER|ALCOHOL|PARAFFIN|GLYCOL|WAX|GELATIN|LACTOSE|STARCH|CELLULOSE|TALC|SILICA|GLACIAL|ANHYDROUS|…`；
7. **疑似 INN**：归一后 ≤4 词、无数字、命中常见 INN 词尾（`-ine/-ol/-mycin/-mab/-tinib/-pril/-sartan/-olol/-prazole/-cillin/-cycline/-azole/-parin/…`）——
   **只作排序依据，不作结论**；
8. 其余 `unknown`。

分类只用于展示与检索排序，**不改任何来源字段**；每个类别都保留 `evidence`（命中的词/规则）。

## 6. 验收口径（草案）

**数据层**

- `entity_type.csv` 覆盖：908 个新成分 **100% 有 entity_type**（`unknown` 也计数，不允许空），
  与 DB `source_id='sukl_dlp'` 成分集合一一对应（SQL 对账：`LEFT JOIN` 后空值 = 0）；
- 合并 3 个后：`substance` 13,648 → **13,645**；`product_component` 行数**不变**（re-point）；
  `variant` 无新增孤儿；`db/check_data.py` **exit 0**、`PRAGMA foreign_key_check` 0、`quick_check` ok；
- 孤儿成分 7 个：要么在分类里标 `homeopathic/herbal`，要么进下一窗口清理清单（不静默保留）。

**页面层**

- 成分页总数不变（当前 13,648；合并后 13,645），其中 409 顺势 / 60 生药 / 42 疫苗页有类型说明句；
- 顺势/生药/疫苗/辅料页 **不出现**「可互换」「等效剂量」「换算」措辞（grep 断言：`互换|等效|换算|equivalent dose` 命中 0）；
- `dose_warning`/`collision` 不对 `homeopathic|herbal|excipient` 实体生成警示块。

**检索层**

- 固定 20 条查询集（含 `泰诺`、`阿司匹林`、`metformin`、`6 C`、`Arnica`）：
  Top-1 结论不变、Top-5 里药物成分不被顺势/生药挤出；新增查询 `6 C`/`Arnica` 的 Top-5
  **不得**出现「可互换」类提示；
- `tests/trilingual/run_tests.py` 全绿（三语检索一致性不退化）。

**流程**

- 变更只在下一窗口执行（本任务不写）；manifest 记 908 条 `(substance_id, entity_type)` 与 3 条 re-point；
- 回滚：CSV 版本回退 + re-point manifest；不碰 `product`/`product_component` 行数。

## 7. 建议任务拆分（给 Lead 排期）

| # | 任务 | 产出 | 预估 |
|---|---|---|---|
| 1 | 补完整 INN 名录（WHO INN 全量）+ 192 个疑似 INN 复核 | `data/who_inn_names.csv` 扩展 + 复核 CSV | 2–3 h |
| 2 | 908 个补 `entity_type.csv`（脚本 + 60 条人工抽检） | CSV 908 行 | 0.5 天 |
| 3 | 3 个合并（下一 DB 窗口） | manifest + substance 13,645 | 0.5 h |
| 4 | site-ui：按 entity_type 显示类型说明 + 检索降权 | 页面/检索改动 | 0.5–1 天 |
| 5 | 170 个未入库名字的窄版 non-substance 词表（只 24 个辅料/溶剂 + 9 个特殊生物） | `cz.py` 词表 + 复算 | 0.5 天 |

## 8. 风险与红线

- 本报告只给「分类与展示」方案，**不判断任何两药可互换**、不给用药建议、不做剂量换算；
- 顺势/生药条目是 CZ 合法注册产品，**不能因为「不像西药」就删**；是否在页面上弱化展示属产品口径，
  需 Lead 按 `docs/为什么不做替代推荐.md` 的红线拍板；
- `entity_type.csv` 是数据表不是 schema，改它不需要 DB 迁移；但它会被建站读取，改后必须跑一次
  `site/build.py` + 三语抽查（归 site-ui 的发布流程，本任务不做）。
