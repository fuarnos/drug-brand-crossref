# 写库窗口：Q3 盐基表 40→68 + Q2 三条确定性合并 + Q6 CZ 未映射名字组件补写

- 任务：**task-1（工位 phaseb-data）**，唯一 DB 写窗口；执行时间 北京时间 2026-11-18 03:39–04:05
- 依据：`reports/2026-11-15-m1-window-dryrun.md` §D/§E、`reports/2026-11-16-m1-window-exec.md` §8/§10、
  `reports/2026-11-17-q2-cz-substance-classify.md` §4/§8、`reports/2026-11-16-cz-substance-quality.md` §3/§7
- 约束：未写 `site/`、未跑 `site/build.py`、未 commit、未发布；不改 `db/schema.sql` 语义；不换算剂量、不判断可互换、不手工标 `collision`

## 0. 结论（先行）

| 项 | 结果 | 关键数字 |
|---|---|---|
| A 备份 | ✅ 可回滚 | `data/backups/drugs-20261118-pre-q3q2q6.db` · 558,039,040 B · sha256 `B6182140…D76A3C0D`（与写前库逐字节一致） |
| 演练 | ✅ | 副本上三次 `--apply` 后三次 `--rollback` → 逐表 diff **0** |
| Q3 盐基表 | ✅ | 68 行逐行复核（usable 65 / note 2 / exclude 1）→ 回填 **38 个 variant**（16,546 组件行）：`base_fraction` 0→38、`strength_basis` unknown→salt 38 |
| Q2 三条合并 | ✅ | 3 对全部执行；`substance` **13,648 → 13,645**；`variant`/`product_component`/`product` 不变（15,248 / 767,080 / 594,781） |
| Q6 CZ 组件 | ✅ | 无组件 CZ 产品 **2,108 → 1,424**（−684）；CZ 组件行 **85,286 → 90,981**（+5,695）；`product_component` 767,080 → **772,775** |
| 写后核对 | ✅ | `db/check_data.py` **exit 0**、FK **0**、`quick_check` ok、`product` 仍 **594,781** |
| 回滚演练（写后副本） | ✅ | 三次 `--rollback` 后计数逐项回到写前基线（diff 0） |

## 1. 产物与清单

| 文件 | 说明 |
|---|---|
| `db/q2_merge_substances.py` | Q2：3 对成分 re-point + 删重复成分（`--dry-run/--apply/--rollback`，`--allow-real` 守卫） |
| `db/q3_apply_salt_map.py` | Q3：68 行盐表逐行复核（`--review` 出复核表）+ `base_fraction`/`strength_basis` 回填 |
| `db/q6_cz_component_fill.py` | Q6：CZ 未映射名字的「窄词表 + 去限定词映射」→ 组件补写 |
| `data/sources/salt_map_review_20261118.csv` | 71 行复核表（68 + salt_map 缺的 3 个旧表代码）：原值 vs 复核后的 `n_base`/`increment_mw` |
| `data/sources/salt_fraction_applied_20261118.csv` | 实际写入的 38 行（variant_id / 盐型 / n_base / Δ / 碱基 MW / f / 组件行） |
| `data/sources/q2_merge_manifest_20261118.json` | 3 对合并：被删 substance 行原值 + variant 清单 + 前后计数 |
| `data/sources/salt_fraction_manifest_20261118.json` | 38 行逐行 `(variant_id, old, new)` + 全部扫描决定与理由 |
| `data/sources/cz_component_fill_manifest_20261118.json` | 684 产品 / 5,695 行的 `(product_id, ord, variant_id, strength)` + 被摘掉的名字 |
| `data/backups/drugs-20261118-pre-q3q2q6.db` | 窗口前备份（手动命名带日期；`run_all` 的 5 份轮换不管它） |

## 2. 备份与回滚演练（写前）

```powershell
Copy-Item data\drugs.db data\backups\drugs-20261118-pre-q3q2q6.db
Get-FileHash data\drugs.db,data\backups\drugs-20261118-pre-q3q2q6.db -Algorithm SHA256
```

| 项 | 值 |
|---|---|
| 备份字节 / sha256 | 558,039,040 B / `B6182140B4546524EB37F98D06BD937BD9313E945EC7BD1B73FB8E3DD76A3C0D`（= 写前库） |
| 副本演练 | `.tmp/q3q2q6/rehearsal.db`：Q2→Q3→Q6 依次 `--apply`，再 Q6→Q3→Q2 `--rollback` → `substance`/`variant`/`product_component`/`product`/`base_fraction≠1`/`strength_basis≠unknown`/CZ 无组件产品 **逐项 diff 0** |
| 写后副本回滚 | `.tmp/q3q2q6/rollback-drill.db`（写后库的副本）：三份 manifest 依次 `--rollback` → 计数逐项回到写前基线（diff 0） |

## 3. Q2 三条确定性合并

| from | to | 依据 | variant | 组件行 | 产品 |
|---|---|---|---|---|---|
| `acetic-acid-glacial` | `acetic-acid` | 冰醋酸 = 纯醋酸，仅性状限定词 Glacial | 1 | **6** | 6 |
| `ethinylestradiol-micronized` | `ethinylestradiol` | 微粉化炔雌醇，仅粒径限定词 | 1 | **20** | 20 |
| `ferrous-sulfate-dried` | `ferrous-sulfate` | 干燥硫酸亚铁，仅工艺限定词 | 1 | **4** | 4 |

开工卡写的 **6/6、20/20、4/4 现查一致**（`substance`/`to` 均存在、`nickname`/`drug_term` 引用 0）。

做法（单事务）：`UPDATE variant SET substance_id=<to>` ×3 → `DELETE FROM substance WHERE substance_id=<from>` ×3。

| 指标 | 写前 | 写后 | 现查复核 |
|---|---|---|---|
| `substance` | 13,648 | **13,645** | −3 = 三条合并 |
| `substance WHERE source_id='sukl_dlp'` | 908 | **905** | 3 个都是 CZ 窗口新建的成分 |
| `variant` | 15,248 | 15,248 | 不变（re-point，无新增/孤儿） |
| `product_component` | 767,080 | 767,080 | 不变（组件行只换 variant 指向） |
| `product` | 594,781 | 594,781 | 不变 |
| 三个 from 的 `substance` 残留 | — | **0 / 0 / 0** | ✅ |
| 指向 to 的 variant 数 | 1 / 1 / 2 | **2 / 2 / 3** | 各 +1（原 from 的 variant 已并入） |

## 4. Q3 T3 盐基表 40 → 68

### 4.1 68 行逐行复核（复核表：`data/sources/salt_map_review_20261118.csv`）

`salt_map_20261115.csv` 记的是**反离子离子量**（`n_counterions × counterion_mw`），直接代 `f = M/(M+n·M_ion)`
在化学上是错的；折算需要的是**增量 Δ**。本窗口按 IUPAC 2021 原子量逐条重算（复核表里每行都写了依据）：

| 类别 | salt_map 原值的问题 | 复核后的 Δ |
|---|---|---|
| 金属阳离子（Na/K/Ca/Mg/Zn/Al/Li/NH₄） | 只给离子 MW，未减成盐时失去的 H | Na 21.982、K 38.090、Ca 38.062(n=2)、Mg 22.289(n=2)、Zn 63.364(n=2)、Al 23.958(n=3)、Li 5.932、NH₄ 17.031 |
| 无机/有机酸胺盐（硝酸/磷酸/硫酸/硫酸氢） | 给的是离子，未加 H | HNO₃ 63.012、H₃PO₄ 97.994、H₂SO₄ 98.072 |
| 枸橼酸 | `n=3` 是价数，不是计量比 | 1:1 用 192.123（枸橼酸西地那非 0.7119 已核）；2:3 盐需另核 |
| 酯类（furoate/valerate/…/palmitate） | 给的是整酸 MW，成酯要脱一分子水 | 酸 MW − 18.015（如戊酸 102.133→84.118） |
| **cypionate** | 150.196 与环戊丙酸 C₈H₁₄O₂（142.198）不符 | **124.183**（与旧表一致） |
| **edisylate** | 109.145 与乙二磺酸（190.19）不符 | **190.19**（2 碱:1 酸） |
| napsylate | 207.248 是离子，未加 H | 208.231 |
| hyclate | 复盐 + 溶剂化物 | **exclude**（不可自动折算，旧表也是 manual_review） |
| ethylenediamine / piperazine | 二价，计量比依原料药 | **note**（登记不写） |
| chloride / bromide / iodide | **salt_map 68 行里缺**（旧表 40 行里有 → 本窗按旧表补回，避免口径倒退） | 35.450 / 79.904 / 127.912 |

复核结果：**usable 65 / note 2 / exclude 1**，无一遗漏（`missing=0`）。

### 4.2 回填（只写「盐型有出处 + 碱基分子量已知」的）

公式（纯质量分数，**不做剂量换算、不输出等效剂量**）：

```
f = n·M(base) / (n·M(base) + Δ + k·18.015)      k = variant.hydrate 的结晶水个数
```

| 指标 | 写前 | 写后 |
|---|---|---|
| `variant.base_fraction <> 1.0` | 0 | **38** |
| `variant.strength_basis <> 'unknown'` | 0 | **38** |
| 受影响组件行（这些 variant 的 `product_component`） | — | **16,546** |
| 扫描到「盐型 variant」 | 1,072（非 `non_salt`/`mixed`/空） | — |
| 跳过：碱基分子量未知 | — | **1,034**（`BASE_MW` 只有 27 个物质） |
| 跳过：盐型不在复核表 | — | **0**（补回 chloride/bromide/iodide 后为 0） |
| 跳过：已有非默认值 | — | 0 |

按盐型分布（现查，`base_fraction<1` 分组）：hydrochloride 12 个 variant / 8,076 行 · sodium 8 / 2,571 ·
calcium 3 / 1,586 · besylate 2 / 919 · citrate 2 / 704 · tartrate 2 / 391 · fumarate 1 / 971 ·
succinate 1 / 418 · phosphate 1 / 310 · acetate 1 / 251 · magnesium 1 / 159 · potassium 1 / 124 ·
sulfate 1 / 63 · mesylate 1 / 2 · benzoate 1 / 1。

**交叉核对**（与旧表 `data/salt_base_fraction.csv` 里 PubChem 已核的示例值对得上，误差 ≤0.0002）：
苯磺酸氨氯地平 0.7211 vs 0.7210 · 枸橼酸西地那非 0.7118 vs 0.7119 · 富马酸喹硫平 0.8686 vs 0.8685 ·
琥珀酸美托洛尔 0.8191 · 酒石酸美托洛尔 0.7808 · 阿托伐他汀钙 0.9671 vs 0.967 · 左甲状腺素钠 0.9725 ·
奥美拉唑镁 0.9687 · 盐酸舍曲林 0.8936 vs 0.8935。

38 行明细见 `data/sources/salt_fraction_applied_20261118.csv`；逐行 `(variant_id, old, new)` 见 manifest。

## 5. Q6 CZ 未映射名字 → 组件补写

### 5.1 判定三分（不硬塞）

167 个挡路名字（2,376 行）按能不能落地分三类，**只处理前两类**：

| 类 | 名字数 | 处理 |
|---|---|---|
| ① 去性状/剂型/浓度限定词后**精确**命中库内已有成分 | 15 | 映射到库内 substance（逐条写「去掉了什么」）；例：`SODIUM (S)-LACTATE SOLUTION`→`sodium-s-lactate`、`CHOLECALCIFEROL CONCENTRATE`→`cholecalciferol`、`SOYA-BEAN OIL, REFINED`→`soya-oil`、`TRIGLYCERIDES, MEDIUM-CHAIN`→`medium-chain-triglycerides`、`HUMAN PLASMA PROTEIN`→`human-plasma-proteins` |
| ② 窄 non-substance 词表（多组分配方 / 特殊生物制品） | 15 | 不当成分、不建 substance（口径同 `etl/markets/jp.py::is_non_substance`）：复方植物油、中链甘油三酯以外的油脂混合物、复方挥发油馏出物、多价抗蛇毒血清、自体细胞制品 |
| ③ 判不了 | 137 | **不写库并计数**：生药/植物提取物 70、疫苗株/抗原 67（<br>`LIVE ATTENUATED … VIRUS`、`INFLUENZA VIRUS …`、`POLIOMYELITIS VIRUS …`） |

写库条件：该产品当前 0 行组件 ∧ 至少 1 个成分能落到库内 **variant** ∧ 其余成分全部落在 ①② 里。
写出的组件只含能映射的成分；被 ② 摘掉的名字逐条记在 manifest 与本节。

### 5.2 before → after（现查）

| 指标 | 写前 | 写后 | 变化 |
|---|---|---|---|
| CZ 产品 | 68,581 | 68,581 | 0 |
| CZ **有组件**产品 | 66,473 | **67,157** | **+684** |
| CZ **无组件**产品 | **2,108** | **1,424** | **−684（−32.4%）** |
| CZ 组件行 | 85,286 | **90,981** | **+5,695** |
| `product_component` 全库 | 767,080 | **772,775** | +5,695 |
| `product` 全库 | 594,781 | 594,781 | 0（验收线） |

新增行校验：manifest 里 684 产品 / **5,695 行** `(product_id, ord, variant_id)` 逐行现查存在 = 5,695；
`product_id+ord` 重复 = 0。强度按来源 `AMNT × UN` 原文落库：**5,648 行有数值**、47 行来源为空/非数值
（按原文留空，不换算、不四舍五入）。CZ 全量口径 `strength_value` 有值 **80,304 → 85,952 行**。

### 5.3 仍无组件的 1,424 个产品（逐项计数，不猜）

| 原因 | 产品数 |
|---|---|
| 唯一的活性成分就落在 ③（疫苗株/生药提取物…）→ 没有可映射的兄弟成分 | **861** |
| 还有 ③ 类名字挡着（其余成分已可映射） | **560** |
| `dlp_slozeni` 里没有 S='L' 行（源无活性成分记录） | **3** |
| 合计 | **1,424**（= 2,108 − 684） |

另有 **655 行**成分「能映射到 substance 但库内没有可用 variant」（`component_no_variant`，旧报告同口径）——
这些产品仍写不出组件，属下一窗「补 variant」的活。

## 6. 写后核对

```text
& $py db/check_data.py         → exit 0
PRAGMA foreign_key_check       → 0 行
PRAGMA quick_check             → ok
collision 视图                 → 219,949 行（可查，未手工标注）
dose_warning                   → 41 行（未新增异常）
SELECT COUNT(*) FROM product   → 594,781
data/drugs.db                  → 558,637,056 B · sha256 5C00BBE8…89DA777
```

另抽查：`product_component` 里 CZ 行 `strength_value` 有值 80,304 → **85,952 行**（新写 5,695 行里 5,648 行有数值），
`ord` 无重复。

## 7. 已知缺口（下一窗）

1. **`strength_basis='salt'` 是 variant 级声明**：本窗按「variant 就是该盐型 → 该 variant 下的强度按盐原文记录」
   回填；逐成分的 base / salt_equivalent 证据目前拿不到（抽查 38 个 variant：产品名里带盐词的只有 3/38，
   其余是商品名如 `Lipitor`，无法据此判定基准）。若某市场实际按碱基标注，需要逐成分证据纠正 —— **未做任何换算结论**。
2. **`variant.hydrate` 列为空但 `variant_id` 带水合物**的 2 个（`atorvastatin-calcium-trihydrate` 674 行、
   `venlafaxine-besylate-monohydrate` 1 行）：本窗以 `hydrate` 列为准、**不从 id 猜**，故 f 未含水；
   补 hydrate 列是一个小任务。
3. **碱基分子量只覆盖 27 个物质** → 1,034 个盐型 variant 未能折算（`benzalkonium`/`cetrimide` 类也在内）。
   补 PubChem 碱基分子量表（`etl/apply_salt_fractions.BASE_MW`）后可一次性回填。
4. **Q6 的两张表在 `db/q6_cz_component_fill.py` 里，不在 `etl/markets/cz.py`**：CZ 若重跑 ingest，
   这 684 个产品的组件会被「缺一味整条不写」再次跳过（`write_product` 是 INSERT OR REPLACE，组件不会自动补）。
   下一窗必须把 `NAME_MAP` / `NON_SUBSTANCE` 折进 `etl/markets/cz.py`（本工位无权改 `etl/`）。
5. **137 个 ③ 类名字**（生药 70 / 疫苗株 67）不是数据错误，是 SÚKL 注册库的真实活性条目；
   要么建成分（生药/疫苗抗原实体），要么进 `entity_type` 的 `herbal`/`biologic` 两类后按类型展示——需 editorial 决策。
6. **`data/entity_type.csv` 现在有 3 行指向已合并的成分**（Q2 删了 3 个 substance，13,701 行未同步）；
   该文件由 `etl/classify_entity_type.py` 整表重写，下一窗接覆盖层时一并清理（本窗未改它）。
7. `name_spec_conflict` 误报降幅要重跑 `db/consistency_audit_identity.py` 才出数字，**本窗未跑**（不阻塞）。
8. 站点/文案（成分数 13,648→**13,645**、product_component 767,080→**772,775**）需要发布流程统一改口径，
   本工位未写 `site/`、未跑 build。

## 8. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 备份
Copy-Item data\drugs.db data\backups\drugs-20261118-pre-q3q2q6.db
# 副本演练（先 apply 再 rollback，逐表 diff 应为 0）
Copy-Item data\drugs.db .tmp\q3q2q6\rehearsal.db
& $py db/q2_merge_substances.py --apply --db .tmp\q3q2q6\rehearsal.db --manifest .tmp\q3q2q6\q2.json
& $py db/q3_apply_salt_map.py  --review
& $py db/q3_apply_salt_map.py  --apply --db .tmp\q3q2q6\rehearsal.db --manifest .tmp\q3q2q6\q3.json
& $py db/q6_cz_component_fill.py --apply --db .tmp\q3q2q6\rehearsal.db --manifest .tmp\q3q2q6\q6.json
& $py db/q6_cz_component_fill.py --rollback --db .tmp\q3q2q6\rehearsal.db --manifest .tmp\q3q2q6\q6.json
& $py db/q3_apply_salt_map.py  --rollback --db .tmp\q3q2q6\rehearsal.db --manifest .tmp\q3q2q6\q3.json
& $py db/q2_merge_substances.py --rollback --db .tmp\q3q2q6\rehearsal.db --manifest .tmp\q3q2q6\q2.json
# 正式写（顺序 Q2 → Q3 → Q6）
& $py db/q2_merge_substances.py --apply --allow-real --db data\drugs.db --manifest data\sources\q2_merge_manifest_20261118.json
& $py db/q3_apply_salt_map.py  --apply --allow-real --db data\drugs.db --manifest data\sources\salt_fraction_manifest_20261118.json
& $py db/q6_cz_component_fill.py --apply --allow-real --db data\drugs.db --manifest data\sources\cz_component_fill_manifest_20261118.json
# 验收
& $py db/check_data.py
& $py db/q.py "PRAGMA foreign_key_check;"
```

Lead 独立复核用 SQL：

```sql
-- Q2
SELECT COUNT(*) FROM substance;                                            -- 13,645
SELECT COUNT(*) FROM substance WHERE substance_id IN
  ('acetic-acid-glacial','ethinylestradiol-micronized','ferrous-sulfate-dried');  -- 0
-- Q3
SELECT COUNT(*) FROM variant WHERE base_fraction<>1.0;                     -- 38
SELECT COUNT(*) FROM variant WHERE strength_basis='salt';                  -- 38
SELECT SUM(c) FROM (SELECT (SELECT COUNT(*) FROM product_component pc WHERE pc.variant_id=v.variant_id) c
                    FROM variant v WHERE base_fraction<>1.0);               -- 16,546
-- Q6
SELECT COUNT(*) FROM product p WHERE p.country='CZ' AND NOT EXISTS
  (SELECT 1 FROM product_component pc WHERE pc.product_id=p.product_id);    -- 1,424（写前 2,108）
SELECT COUNT(*) FROM product_component;                                    -- 772,775
SELECT COUNT(*) FROM product;                                              -- 594,781
```

## 9. 红线确认

- ✅ 不给用药建议、不做剂量换算、不判断可互换：`base_fraction` 只写「盐→碱基质量分数」，报告与 manifest 里没有
  任何「等效剂量」结论；Q6 只做身份对应（成分归属），未输出剂量。
- ✅ 商品名不是主键：Q6 只补 `product_component`，`product_name`/`name_key` 一行未动。
- ✅ 碰撞自动推导：`collision` 视图未改、未手工标注（现查 219,949 行可读）。
- ✅ 判不了的不硬塞：137 个名字（生药 70 / 疫苗株 67）+ 655 行「无 variant」+ 1,034 个「无碱基分子量」盐型，全部计数留空。
- ✅ 未写 `site/`、未跑 `site/build.py`、未碰 `site/dist`、未 commit、未发布。
- ✅ 唯一 DB 写窗口：三次写入串行、各自单事务、各有 manifest 与回滚，未与其它入库并行。
