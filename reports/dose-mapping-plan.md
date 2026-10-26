# D2（盐基折算）/ D3（不可互换）与 `/warn` 页设计方案

> 任务：共享任务 `task-3` · 状态：设计稿（只读审计已完成，未写库、未构建、未发布）
> 数据快照：`data/drugs.db`（v0.3.3 线上版本同源，读取于 2026-10-26，只读 URI 打开）
> 代码快照：`site/build.py` 1924 行、`etl/*.py`、`db/schema.sql`、`docs/方案与数据模型.md`
> 标记约定：**[已验证]** = 本轮用 SQL/代码/PubChem 实测；**[推断]** = 由已知事实外推，发布前须复核。

---

## 0. 一句话结论与交付物

**结论：D2 可以做、但不要"全自动"——先把 `variant.salt` 的脏数据（1555 条里约 409 条不是盐）和"强度基准（label strength basis）"这两个坑修掉；D3 不需要新算法，用现有 `release`、复方多成分、`collision` 视图三个信号就能自动出候选，`/warn` 页的价值在人工策展的 30–50 条，而不是算法自动生成。**

数量速览（已验证）：

| 指标 | 数值 |
|---|---|
| `variant` 总数 / 带 `salt` | 14,240 / **1,555**（10.9%） |
| 其中可识别为真实盐/水合物的 variant | **1,146**（另 409 条是疫苗株、油脂、螯合物等误判） |
| `base_fraction ≠ 1.0` | **0**（14,240 行全是默认 1.0，代码零引用） |
| `interchange = 'unknown'` / `interchange_note` 非空 | **14,240 / 0** |
| `hydrate` / `ester` 非空 | **0 / 0** |
| 含盐型 variant 的 `product_component` | **56,204 / 497,513**（11.3%） |
| 可识别真实盐的组件占比（US/CA/MX/AU/GB/ES/CN） | 26.3% / 12.7% / 31.7% / 10.1% / 2.0% / 1.5% / **0.3%** |
| 已有产品落地的"多盐型/碱基"成分（D3 候选） | **840 个 substance** |
| 同时有 IR 与 ER/DR 产品的成分（D3 候选） | **383 个 substance**，ER/DR 产品 **23,855** |
| 跨国盐型不一致的成分 | **771 个 substance** |
| 复方（多成分）产品 | **48,784** 个（全部 409,485 的 11.9%） |
| CN 注册名称含强盐型词 / 规格含"按…计" | **39,767 / 146,526** 行；**16,811** 行 |
| GB dm+d 原料名含盐型词 | **963 / 4,532** 个 ingredient |

交付文件（全部在 `.tmp/dose/`，均未执行写库）：

| 文件 | 内容 |
|---|---|
| `salt_base_fraction.csv` | 盐→碱基通用折算规则 **40 行**（30 行盐/形态 + 1 行复盐 hyclate + 9 行酯类），含分子式、Δ 分子量、公式、示例、PubChem 来源、验证状态 |
| `variant_base_fraction_candidates.csv` | 首批具体 variant 候选 **51 行**：34 行可自动填、17 行须人工核对 |
| `update_base_fraction.sql` | 回填模板（staging 表→事务更新→抽查→回滚），**未执行** |
| `base_mw_verified.csv` | 27 个物质的碱基分子量（PubChem 逐个核对） |
| `audit1.py/.txt` `audit2.py/.txt` `audit3.py/.txt` `audit4.py/.txt` | 审计脚本与原始输出，可复跑 |
| `build_salt_tables.py` | 本 CSV 的生成脚本（可复现） |

---

## 1. 现状审计（全部 [已验证]）

### 1.1 schema 与文档不一致

- `db/schema.sql` 里 `variant` 的字段是 `salt / hydrate / ester`，**不是**文档 §3 写的 `salt_form`。实现以实际 schema 为准。
- `docs/方案与数据模型.md` §3 示例写"苯磺酸氨氯地平 ≈ 0.876"。**这是错的**：PubChem 核对苯磺酸氨氯地平 `C26H31ClN2O8S` MW **567.1**、氨氯地平碱基 `C20H25ClN2O5` MW **408.9**，折算系数 = 408.9/567.1 = **0.7210**（5 mg 苯磺酸氨氯地平 ≈ 3.60 mg 碱基；反过来 1 mg 碱基 ≈ 1.387 mg 盐）。**[已验证]** 发布前必须改掉这个示例值，否则 D2 上线即带错误锚点。

### 1.2 `salt` 值质量：1,555 条里约 409 条不是盐

`etl/ingest_openfda_ndc.py:63` 的 `split_salt()` 用尾部白名单匹配，把疫苗株、油脂、螯合物等一起吞进 `salt`。去重后 484 个 salt 串，只有 **204 个**能映射到真实盐/水合物（覆盖 1,146 个 variant），其余是：

```
'human'(20) 'hvp chelate'(8) 'borage oil'(7) 'inactivated'(5) 'h1n1'(5)
'evening primrose oil'(5) 'h3n2'(4) 'ephedra'(4) 'dolomite'(4) 'aspergillus oryzae'(4)
'yamagata'(3) 'victoria'(3) 'recombinant'(3) 'povidone-iodine'(3) ...
```

另有大量**酯类/水合物混进 salt 字段**（`valerate`、`propionate`、`dipropionate`、`decanoate`、`palmitate`、`monohydrate`、`trihydrate`、`hydrochloride monohydrate` 等），以及**同义写法未归一**：

| 同一盐的不同写法 | 数量 |
|---|---|
| `hydrochloride` / `hcl` | 272 / 6 |
| `sodium` / `sodio` | 108 / 27 |
| `chloride` / `cloruro` | 36 / 8 |
| `sulfate` / `sulfato` | 61 / 5 |
| `sulfate` / `bromide` / `bromuro` | 61 / 30 / 4 |

**结论：D2 开工前必须先做 salt 规范化（清洗 + 同义词 + 酯/水合物分流），否则折算表会算到疫苗和鱼油上。**

### 1.3 各来源实际提供了什么（代码级核实）

| 市场 | 来源 | ETL 是否写 `variant.salt` | 证据 | 结果 |
|---|---|---|---|---|
| US | openFDA NDC | ✅ `split_salt` | `etl/ingest_openfda_ndc.py:237-251` | 883/4,803 variant 带盐；组件 38,416/145,952 |
| CA | Health Canada DPD | ✅ 括号盐 + `split_salt` | `etl/ingest_ca_dpd.py:227-268, 479` | 850/3,536；组件 9,256/72,665 |
| ES | CIMA | ✅ 西语盐尾 `split_salt_es` | `etl/ingest_cima.py:900-914, 1342` | 70/2,106；组件 441/29,931 |
| GB | dm+d | ❌ 只建 base variant | `etl/ingest_dmd.py:232-240`（`vid = sid`，不写 salt） | 43/3,768；组件 1,314/65,619 |
| CN | 医保编码库 | ❌ 只建 base variant | `etl/ingest_nhsa.py:1850-1853`（同 `vid = sid`） | 5/3,105；组件 489/150,193 |
| MX/AU | COFEPRIS/PBS/TGA | ❌ 只建 base variant | `etl/ingest_mx.py:303`、`ingest_pbs.py:264` 等 | 盐型是"蹭"到的（按名字命中别人建的 variant） |

**注：US/CA/ES 的 43/70/298 等小数字不是它们的上限，而是中文/西语名映射后能命中的已有 variant；真正上限由来源原文决定（见 1.5）。**

### 1.4 D3 候选规模（用现有字段就能自动出清单）

```sql
-- (a) 同一成分有多种盐型/碱基，且都有产品：840 个 substance
SELECT v.substance_id, s.inn_en,
       COUNT(DISTINCT CASE WHEN v.salt='' THEN 'BASE' ELSE v.salt END) AS n_forms,
       COUNT(DISTINCT pc.product_id) AS n_products
FROM variant v JOIN substance s ON s.substance_id=v.substance_id
JOIN product_component pc ON pc.variant_id=v.variant_id
GROUP BY v.substance_id HAVING n_forms>1 ORDER BY n_products DESC;

-- (b) 同成分同时有 IR 与 ER/DR 产品：383 个 substance，ER/DR 产品 23,855 个
SELECT v.substance_id, s.inn_en,
       COUNT(DISTINCT CASE WHEN p.release='none' THEN 'IR' ELSE 'ER' END) AS n_rel,
       COUNT(DISTINCT p.product_id) AS n_products
FROM product_component pc JOIN product p ON p.product_id=pc.product_id
JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id
WHERE p.form_base IN ('tablet','capsule')
GROUP BY v.substance_id HAVING n_rel>1 ORDER BY n_products DESC;

-- (c) 跨国盐型不一致：771 个 substance（D2 展示 + D3 警示的交集）
SELECT v.substance_id, s.inn_en, COUNT(DISTINCT p.country) n_countries,
       COUNT(DISTINCT CASE WHEN v.salt='' THEN 'BASE' ELSE v.salt END) n_forms
FROM variant v JOIN substance s ON s.substance_id=v.substance_id
JOIN product_component pc ON pc.variant_id=v.variant_id
JOIN product p ON p.product_id=pc.product_id
GROUP BY v.substance_id HAVING n_countries>1 AND n_forms>1;
```

典型样本（已验证在库）：`metoprolol` 三种 variant：`metoprolol`(586 组件)、`metoprolol-tartrate`(304)、`metoprolol-succinate`(269)；`amlodipine` 四种：base 1,908、besylate 825、mesylate 2、benzoate 1；`levothyroxine` 三种：base 614、sodium 572、sodium-anhydrous 22。

### 1.5 来源原文里还有多少盐型可挖（D2 最大增量）

- **GB dm+d**：`f_ingredient2_3151026.xml` 共 4,532 个 `NM` 原料名，**963 个含盐型词**（如 `Amlodipine besilate`、`Atorvastatin calcium trihydrate`、`Doxazosin mesilate`）。当前 ETL 用 VTM 名建 variant，把盐丢了；只要用 `ISID` 关联 VMP/AMP 原料名即可补回。**[已验证]**
- **CN nhsa**：`nhsa_codes_20250404.csv` 化学药 146,526 行中，**39,767 行注册名称含强盐型词**（盐酸 15,721、氯化 8,184、硫酸 3,199、磷酸 2,798、枸橼酸 1,327、乳酸 1,311、苯磺酸 1,219…）；**16,811 行规格含"按…计"**——后者直接写明强度基准是碱基，是 D2 最干净的输入。**[已验证]**
- **US openFDA / CA DPD / ES CIMA**：原始 JSON 都在 `data/raw/{openfda,ca/dpd,cima}`（openFDA 243 MB、CA activeingredient 17.6 MB、CIMA 目录下 128 个分页 JSON + `atc/`），可离线重跑；本轮没有重扫全文，覆盖率按已入库结果计。**[已验证存在，未重扫]**

### 1.6 D2 的硬前提没人满足：强度基准未知 [已验证 + 推断]

折算的前提是"标签上那个 mg 到底指什么"，现实中三种基准都存在：

| 基准 | 例子 | 折算方向 |
|---|---|---|
| 强度 **= 碱基** | 美国 Norvasc "5 mg amlodipine（以苯磺酸盐存在）"；Seroquel 25 mg 片含 28.78 mg 富马酸喹硫平、相当于 25 mg 喹硫平；中国规格"5mg(按 C20H25ClN2O5 计)" | 盐量 = 碱基量 ÷ f |
| 强度 **= 盐** | Lopressor "metoprolol tartrate 50 mg"；Synthroid "levothyroxine sodium 50 mcg" | 碱基量 = 盐量 × f |
| 强度 **= 另一种盐的等效量** | Toprol-XL 25/50/100/200 mg：实际含 23.75/47.5/95/190 mg 琥珀酸美托洛尔，标示值按**酒石酸盐等效量**计 | 必须先换到 base 再换目标盐 |

**三种基准混在同一个 `strength_value` 里，数据库却没有任何字段区分。** 因此 D2 不能只看 `variant.salt` 就折算，必须新增 `strength_basis` 并把默认值设为 `unknown`；`unknown` 时只显示"D2 暂不可用"，不猜。**[推断：US 标签基准需逐药按 FDA label 原文核对，openFDA NDC 的 `strength` 不携带基准信息]**

---

## 2. D2 设计：盐基折算

### 2.1 公式（一条，通用）

```
f = base_fraction = n · M(碱基) / [ n · M(碱基) + Δ ]
```

- `n` = 1 分子盐里含几个碱基分子（盐酸盐/苯磺酸盐 n=1；酒石酸/琥珀酸/富马酸/马来酸/硫酸/钙/镁 n=2）；
- `Δ` = 反离子（含成盐时的 H 转移）的分子量：`HCl=36.458`、`H2SO4=98.072`、`Ca−2H=38.062`、`Na−H=21.982`、`C6H6O3S=158.171`、`C4H6O6=150.086`…；
- 强度基准为碱基时：`盐量 = 碱基量 / f`；基准为盐时：`碱基量 = 盐量 × f`；
- 水合物：`f_hydrate = n·M(base) / (n·M(base) + Δ + k·18.015)`，**必须先确认标签强度按无水物还是水合物计**。

### 2.2 折算表 `.tmp/dose/salt_base_fraction.csv`（40 行）

结构：`salt_code, salt_en, category, base_per_salt, increment_formula, increment_mw, fraction_rule, example, example_fraction, source, status, note`

- 30 行盐/形态（含 `anhydrous` 这种非盐形态行）+ 1 行复盐 `hyclate`（标"必须人工核对"）+ 9 行**酯类**（`valerate/propionate/dipropionate/decanoate/enanthate/cypionate/palmitate/furoate/stearate`，标"酯类非盐，应落 `variant.ester`"）。
- **9 个盐-碱基对已用 PubChem PUG REST 逐个核对分子式与分子量**（[已验证]）：苯磺酸氨氯地平 0.7210、酒石酸美托洛尔 0.7808、琥珀酸美托洛尔 0.8191、阿托伐他汀钙 0.9671、左甲状腺素钠 0.9725、富马酸喹硫平 0.8686、盐酸舍曲林 0.8936、枸橼酸西地那非 0.7119、奥美拉唑镁 0.9687。其余盐的 Δ 按 IUPAC 原子量自算，标 **[推断]**，上线前补 PubChem 核验。
- 碱基分子量 `.tmp/dose/base_mw_verified.csv`：27 个物质；有 PubChem 直接值的用直接值，只有盐值的用盐反推（如瑞舒伐他汀 1001.1 − 38.06）/2 = 481.5）。

### 2.3 哪些能自动填、哪些必须人工（`.tmp/dose/variant_base_fraction_candidates.csv`）

首批 51 个 variant 里 **34 可自动填（11,983 个组件）**、**17 须人工核对（755 个组件）**。

**可自动填的条件（三条同时满足）：**
1. `salt` 串只含**一个**盐型 token，且能规范化（`hcl→hydrochloride`、`sodico→sodium` 等）；
2. 化学计量比确定（HCl/HBr/苯磺酸/甲磺酸/钠/钾 1:1；酒石酸/琥珀酸/富马酸/马来酸/硫酸/钙/镁 2:1；枸橼酸 1:1 仅限有依据的如西地那非）；
3. 该 substance 的碱基分子量已核对。

**必须人工核对的情况（已全量枚举）：**

| 情况 | 库内示例 | 原因 |
|---|---|---|
| 水合物/溶剂化物 | `atorvastatin-calcium-trihydrate`(441 组件)、`venlafaxine-besylate-monohydrate` | 无水盐 f=0.9671，按三水合物 f=0.9238，差 4.3 个百分点；取决于标签基准 |
| 复盐/酯盐 | `dexamethasone-sodium-phosphate`(126)、`hydrocortisone-sodium-succinate`(34)、`clindamycin-phosphate`(259) | 含酯键+钠盐，Δ 不能简单相加 |
| 混合盐/复方写法 | `sodium phosphate`、`calcium phosphate`、`estolate`、`hyclate` | 化学计量比须按说明书 |
| 未知/垃圾 token | `hemihydrate`、`sodico`、`hcl`、`amoxicillin` 等 409 个 variant | 先清洗 |
| 无碱基分子量 / 生物制品 | 疫苗、单抗、肽类、肝素 | 无"碱基"概念，D2 不适用 |
| 无机盐本身是活性成分 | `calcium carbonate`、`sodium chloride`、`magnesium sulfate`、口服补液盐 | 盐就是有效成分，D2 无意义，必须排除 |

### 2.4 schema v0.4 建议（由 schema 负责人执行，不在本任务写范围）

```sql
-- 1) 强度基准：最关键的 1 个字段；默认 unknown，宁可不出结论也不猜
ALTER TABLE variant ADD COLUMN strength_basis TEXT NOT NULL DEFAULT 'unknown'
  CHECK (strength_basis IN ('base', 'salt', 'salt_equivalent', 'unknown'));
-- 2) 盐型规范化后的代码（与 salt_base_fraction.csv 的 salt_code 对齐；salt 保留原文）
ALTER TABLE variant ADD COLUMN salt_code TEXT NOT NULL DEFAULT '';
-- 3) 折算证据（哪个物质/分子量/公式/来源，避免"魔法数字"）
ALTER TABLE variant ADD COLUMN base_fraction_source TEXT;
-- 4) D2 关闭原因（'ok' / 'need_review' / 'not_applicable' / 'biologic'）
ALTER TABLE variant ADD COLUMN d2_status TEXT NOT NULL DEFAULT 'need_review'
  CHECK (d2_status IN ('ok', 'need_review', 'not_applicable', 'biologic'));
```

配套：`docs/剂量对应` 增补"强度基准"定义；`CHANGELOG.md` 记一条；新增 `db/migrations/v04_dose.sql`（不修改既有 schema.sql 正文，或按项目习惯同步）。**这一步需要和管 schema 的同事对齐，本任务只出设计。**

### 2.5 回填步骤（`.tmp/dose/update_base_fraction.sql`，不执行）

1. **清洗先行**（不改 schema 也能做）：
   - 同义词归并：`hcl→hydrochloride`、`sodico→sodium`、`cloruro→chloride`、`sulfato→sulfate`、`bromuro→bromide`、`lactato→lactate`、`mesilate/besilate→mesylate/besylate`；
   - 酯类与水分流：`valerate/propionate/...` 移入 `variant.ester`，`monohydrate/dihydrate/trihydrate/hemihydrate` 移入 `variant.hydrate`，`salt` 只留盐；
   - 409 条垃圾 variant 标 `d2_status='not_applicable'`，不删（保留可追溯）。
2. **staging → 事务更新**（模板已给）：先 `cp data/drugs.db data/backups/drugs.db.bak-YYYYmmdd-HHMM`；CSV 导入 `tmp_base_fraction_candidate`；`UPDATE variant ... WHERE base_fraction=1.0`（只补空，不覆盖人工值）；抽查；回滚 SQL 同文件。
3. **不可逆校验**：`SELECT variant_id, salt, base_fraction FROM variant WHERE base_fraction NOT IN (1.0) ORDER BY base_fraction`，抽查值与公式一致；跑一遍 `site/build.py`（**由发布会话执行，本任务不跑**）确认页面无异常。

### 2.6 前端展示规则（写进代码，不靠自觉）

- 仅当 `strength_basis != 'unknown'` 且 `d2_status='ok'` 时输出折算；
- 文案模板（三语）：
  - EN: `Label strength basis: base. 100 mg of the salt ≈ 72.1 mg amlodipine (calculated from molecular weights; not a dosing recommendation).`
  - ZH: `标签强度按碱基计。100 mg 苯磺酸氨氯地平 ≈ 72.1 mg 氨氯地平（按分子量折算，不构成用药建议）。`
- **禁止措辞**：等量替换、可互换、吃几片/几粒、等效剂量、换算后应服用；D3 命中时整块 D2 结论隐藏。
- 每个 D2 数字旁必须有 `base_fraction_source`（分子式/MW/来源），否则不显示。

---

## 3. D3 设计与 `/warn` 页

### 3.1 规则族（R1–R7）

| 规则 | 判定信号（现有数据即可算） | 输出 | 规模 [已验证] |
|---|---|---|---|
| **R1 释放机制不同** | 同 substance 存在 `release='none'` 与 `ER/SR/DR/MR` 产品；`collision.level='warning'` 已有同类逻辑 | "同成分缓释 vs 速释，不可直接互换" | 383 substance / 23,855 个 ER/DR 产品 |
| **R2 盐型不同且生物等效性未证明** | `variant.salt` 不同；`interchange` 未标 yes；典型 metoprolol tartrate(IR) vs succinate(ER) | 只警示、**不折算成等量** | 840 substance（其中 771 跨国） |
| **R3 复方配比不同** | 同商品名/同成分组，`product_component.strength_value` 比例不同（Augmentin 2:1/4:1/7:1；复方感冒药） | 列出配比差异表，不建议换 | 48,784 个复方产品 |
| **R4 同名不同药** | `collision.level='severe'`（已有） | 红色横幅（现有能力） | 泰诺/Tylenol、Benadryl 已在库验证 |
| **R5 剂型/途径不同** | 同成分 IV vs 口服、外用 vs 全身；盐型跟着剂型变（如 dexamethasone 磷酸钠注射液） | 警示 + 说明不同盐型对应不同给药途径 | 待统计 |
| **R6 治疗窗窄/生物制品不折算不互换** | 白名单：warfarin, digoxin, lithium, levothyroxine, phenytoin, carbamazepine, valproate, tacrolimus, ciclosporin, theophylline, insulin, heparin… | 固定提示，D2 关闭 | 人工清单 |
| **R7 名称里写着配方** | 名称含浓度/配比（"0.9% sodium chloride"、"875/125"） | 归"提示"级，不报严重（`collision` 视图已按此设计） | — |

### 3.2 数据模型：新增 `dose_warning` 表（不塞进 `variant`）

`variant.interchange/interchange_note` 只够放"variant 级、一句话"结论；`/warn` 页需要可解释、可追溯、可多语言、可排序的条目。建议：

```sql
CREATE TABLE IF NOT EXISTS dose_warning (
    warning_id   TEXT PRIMARY KEY,              -- 如 'metoprolol-tartrate-vs-succinate'
    scope        TEXT NOT NULL CHECK (scope IN ('substance','variant','pair','name_key','class')),
    subject_id   TEXT NOT NULL,                 -- substance_id / variant_id / key_id / 自由 slug
    related_id   TEXT,                          -- pair 时的另一端
    rule         TEXT NOT NULL CHECK (rule IN ('R1','R2','R3','R4','R5','R6','R7')),
    severity     TEXT NOT NULL CHECK (severity IN ('high','medium','info')),
    title_zh     TEXT NOT NULL, title_en TEXT NOT NULL, title_es TEXT,
    body_zh      TEXT NOT NULL, body_en TEXT NOT NULL, body_es TEXT,
    evidence_url TEXT NOT NULL,                 -- 监管原始文件（label/说明书/SmPC）
    evidence_note TEXT,                         -- 原文摘录（只引用事实，不转载全文）
    reviewed_by  TEXT NOT NULL,
    reviewed_at  TEXT NOT NULL,
    source_id    TEXT REFERENCES source (source_id),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_dose_warning_scope ON dose_warning (scope, subject_id);
```

`/warn` 页只读这张表；成分页/名字页按 `subject_id` 反查挂警示；`interchange`/`interchange_note` 继续做 variant 级快查，两者由 ETL 从同一份 CSV 维护（`data/sources/dose-warnings.csv`，人工审过才能进库）。

### 3.3 编辑政策（写进流程，不靠自觉）

1. 每条 warning 必须有 **≥1 个监管来源**（FDA label / DailyMed / EMA SmPC / MHRA / Health Canada DPD / 中国说明书）的 `evidence_url`；事实摘录 ≤ 200 字，不转载全文。
2. **双人复核**：`reviewed_by` 至少 2 人（录入 + 核对），未复核条目只在内部 staging 可见。
3. 分级：`high`=可能导致治疗失败/中毒/重复用药（盐型不可互换、复方配比、同名不同药）；`medium`=释放机制差异；`info`=规格/剂型提示。
4. 每条带日期，修订留历史（`updated_at`），撤回不删（与撤市药保留一致）。
5. **未核实不发布**：`docs/方案与数据模型.md` §11 已列 3 条已验证（Tylenol/泰诺、Benadryl、Gaviscon），Augmentin 配比与 "Benadryl One a Day 是否含西替利嗪" 标注为未核实——保持这个口径，`/warn` 页首批只收已验证的。
6. 对齐现有规则：D3 命中页不出现任何"等量替换"；全站不输出"吃几片"；每个结论可追 `source_url`。

### 3.4 许可边界（逐源）

| 来源 | 许可 | 用于 `/warn` 的边界 |
|---|---|---|
| FDA label / DailyMed / openFDA / NLM | 美国政府作品（公有领域） | 可引用事实、可存储结构化条目；署名 FDA |
| Health Canada DPD | 非商业再使用 + 署名 | 可存事实字段，注明来源与日期 |
| NHSBSA dm+d | OGL v3.0 | 可再发布，署名 + 许可链接 |
| CIMA (AEMPS) | 公开数据，署名再使用 | 可存事实，署名 |
| TGA / PBS / COFEPRIS | 事实字段可用；PBS 明确"不得修改" | 只存事实字段，不改写原文 |
| 中国说明书 / 医保库 | 未标注开放许可 | 只存事实 + 链原文；**不转载说明书全文**；页面标"部分覆盖" |
| ISMP LASA 清单 | 第三方版权 | **不使用**；沿用 `confusable_pair` 只用 FDA tall-man 官方名单 |
| WHO ATC/DDD | 不可整表复制再发布 | 继续只用 RxNorm/dm+d 派生，不在 `/warn` 页整表展示 |

### 3.5 `/warn` 页结构与建站接入点

**路由**：`/warn.html`（英文默认）+ `zh/warn.html`、`es/warn.html`（与现有 `zh/`、`es/` 目录模式一致；`build_index_page()` 已按 `path` 生成 `/zh/index.html`、`/es/index.html`）。

**页面结构**（单页静态，无 JS 依赖，SEO 友好）：
1. 顶部：标题 + 一句话定义（"这些情况**不能**互相替换；是警示，不是用药建议"）+ 数据日期 + 语言切换；
2. 区块 A · 同名不同药（`R4`，红色）：泰诺 vs Tylenol、Benadryl vs 英国 Benadryl Allergy Relief、Gaviscon（均已入库可验证）；
3. 区块 B · 同成分不可互换（`R1/R2/R5`，黄色）：缓释 vs 速释、metoprolol tartrate vs succinate、levothyroxine sodium vs base、注射 vs 口服；
4. 区块 C · 复方配比差异（`R3`）：Augmentin 各配比、复方感冒药；
5. 区块 D · 高警示/不折算药物清单（`R6`）；
6. 区块 E · 数据来源、编辑政策、最后更新、纠错入口（复用现有 `report.note` i18n 与 `REPORT_REPO`）。

**`site/build.py` 接入点（行号基于当前 1924 行版本）**：

| 位置 | 改动 |
|---|---|
| `I18N` dict（L60–318） | 新增 `nav.warn`、`warn.title/lead/section.*/source_note` 三语键（en/es/zh 各一段） |
| 导航模板 L787–790 | `<a href="{prefix}warn.html" data-i18n="nav.warn">` 加在 `nav.confused` 之后 |
| 新函数 `build_warn(db)`（参照 `build_confused()` L1676–1721） | 读 `dose_warning`，用 `page()`（L765）渲染，写 `warn.html`；同时写 `data/warnings.json` 供成分页反查 |
| `main()` L1906 附近 | 在 `build_confused(db)` 后加 `n_warn = build_warn(db)`，并在结尾 print |
| `build_drug_pages()` L1151–1290 | 成分页顶部按 `subject_id` 查 `dose_warning` 渲一条警示（复用 L633 的 `notice warnbox` 样式）；D2 折算块只在 `strength_basis!='unknown'` 时渲染 |
| `collect_name_data()` / `build_name_pages()` L1294–1362 | 名字页复用同一警示块（同名不同药已有 `severe` 逻辑，改为优先用 `dose_warning.R4` 文案） |
| `build_seo_files()` L1757 | `rglob("*.html")` 自动收 `warn.html`，无需改；站点 404/sitemap 自动生效 |
| `docs/方案与数据模型.md` §7 路由表、`README.md` 页面清单、`CHANGELOG.md` | 发布时同步 |

**注意**：`site/build.py` 是被跟踪文件，且本任务禁止改；上述是给建站任务的设计输入，实际改动需由有写权限的同事执行并跑 `python site/build.py`+`python -m pytest`。

### 3.6 首批 `/warn` 内容建议（全部可在库内验证 [已验证]）

| 条目 | 库内事实 | 规则 |
|---|---|---|
| 泰诺 / Tylenol | `泰诺` = 对乙酰氨基酚+伪麻黄碱+右美沙芬+氯苯那敏（7 个产品，4 成分）；Tylenol 单方对乙酰氨基酚；`泰诺林` 单独是单方 | R4 high |
| Benadryl | 美国/多数市场苯海拉明；`benadryl allergy relief` = 阿伐斯汀（Acrivastine）8 mg | R4 high |
| Gaviscon | 美国=氢氧化铝+碳酸镁；英国/ES=海藻酸钠+碳酸氢钠+碳酸钙 | R4 high |
| Augmentin | 同名字段下 amoxicillin/clavulanate 多配比 | R3 high |
| metoprolol | `metoprolol-tartrate`（304 个组件，IR）vs `metoprolol-succinate`（269 个组件，ER），另有 base (586) | R1+R2 high |
| levothyroxine | `levothyroxine-sodium`(572 组件) vs base(614) vs `sodium-anhydrous`(22)，治疗窗窄 | R2+R6 high |

---

## 4. 实现顺序（建议 6 个 PR，按依赖排序）

| 阶段 | 内容 | 产出 | 依赖/工时 [推断] |
|---|---|---|---|
| **P0 数据清洗** | salt 同义词归一、酯/水合物分流、409 条垃圾标 `d2_status`；只改数据不改 schema | 清洗脚本 + 审计前后对比 | 1 人日；先于一切 |
| **P1 schema v0.4** | `strength_basis`、`salt_code`、`base_fraction_source`、`d2_status`、`dose_warning` 表 | migration SQL + schema.sql 同步 + 文档 §3/§4 更新 | 0.5 人日；需 schema 负责人 |
| **P2 D2 引擎** | 新 `lib/dose.py`：`base_fraction_of(variant)`、`convert(value, frm, to, basis)`；`salt_base_fraction.csv` 入库为参考表；20 条单元测试（含 9 个已验证对 + 3 种基准） | 纯函数 + pytest | 1 人日；不依赖 UI |
| **P3 各市场补盐** | US：标签基准抽样核对后补 `strength_basis`；CA/ES：已有 salt 直接映射；GB：dm+d `ISID`→VMP 原料名补 salt；CN：注册名称盐词 + 规格"按…计"解析 | 各 ETL 小 PR + 覆盖率报告 | US 0.5 / CA+ES 0.5 / GB 1.5 / CN 1.5 人日 |
| **P4 展示 + `/warn`** | 成分页 D2 块 + D3 警示；`build_warn()`；三语 i18n；导航 | 静态页 diff + 20 条人工查询集 | 1.5 人日；需建站负责人 |
| **P5 发布** | 全量重建、测试、版本号/Release、线上抽查 | 发布记录 | 由 Lead/发布会话执行，**本任务不发布** |

**并行建议**：P0 与 P3(GB/CN 补盐) 可并行（都只碰 ETL/数据侧、不碰 build.py）；P2 与 P1 可并行（引擎先按现有 schema 写，字段就位后接）。P4 必须等 P1+P2。

---

## 5. 覆盖率提升预估

基线（已验证）：含盐型组件的 `base_fraction` 可解释占比 **0%**（全库 1.0 无引用）；此时页面只能对"同 variant 同剂型"做 D1。

| 阶段 | 覆盖 | 占含盐组件 | 占全部组件 | 口径 |
|---|---|---|---|---|
| 现状 D1 | 0 | 0% | 0% | 已验证 |
| D2 试点（27 物质 / 34 variant，含 9 个 PubChem 核对对） | 11,983 组件 | **21.3%** | **2.4%** | 已验证（候选 CSV 统计） |
| 扩到 top 200 物质（盐表 + 碱基分子量补到 200 个） | — | **约 60–70%**（推断） | 约 7% | 推断：top 27 已覆盖 22.7% 含盐组件，长尾集中度按现有产品分布外推 |
| 加 GB dm+d 原料名补盐（963 个原料名） | — | GB 含盐组件比例可从 2.0% 抬到 **20% 量级**（推断） | — | 推断：dm+d 约 61k 产品，盐类原料占比按 963/4,532 原料名×产品权重估 |
| 加 CN 注册名称+按…计（39,767 / 16,811 行） | — | CN 含盐组件比例可从 0.3% 抬到 **25% 量级**（推断） | — | 推断：CN 146,347 产品；16,811 行"按…计"可直接定基准 |
| 稳定态（全部市场 + top 200 物质 + 基准核对） | 约 8–12 万组件（推断） | 约 60% | 约 20% | 推断，须用真实 ETL 跑数验证 |

`/warn` 页规模：自动候选 383（R1）+ 840（R2，去重后约 900 个 substance）+ 48,784 个复方产品（R3 抽头部），但**首批发布按人工复核量控制在 30–50 条**（R4 三条已验证 + R1/R2/R6 各 10 条），后续按"新增有监管来源的条目"滚动加。

---

## 6. 风险与缓解

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| 1 | **强度基准误判导致算错剂量**（把"盐 50 mg"当"碱基 50 mg"） | 极高 | `strength_basis` 默认 `unknown`、未知不出结论；US 逐药按 label 核对；20 条金标准测试；页面明示基准 |
| 2 | salt 字段脏数据（疫苗株/油脂/酯类）被当盐折算 | 高 | P0 清洗先行；只对 `d2_status='ok'` 的 variant 折算；用白名单不用黑名单 |
| 3 | 分子量/化学计量比错误（水合物、复盐、2:1 盐） | 高 | 全部 MW 存 `base_fraction_source`；PubChem PUG REST 批量核验脚本；水合物单独出两个值并人工确认 |
| 4 | 复方产品把"整片强度"当成"单成分强度"折算 | 中高 | 折算只发生在 `product_component` 粒度；同产品多成分页面并列展示，不合成一个数 |
| 5 | 生物制品/无机盐/治疗窗窄药物被折算 | 中高 | `not_applicable`/`biologic` 状态 + R6 清单；D2 关闭 |
| 6 | 法律与药政：展示折算被解读为用药建议 | 高 | 沿用"信息参考、不构成用药建议"；禁止"等量替换/吃几片"；每个数字带来源；不上购买链接 |
| 7 | 数据许可：ISMP/WHO ATC/中国说明书全文 | 中 | 见 §3.4；只引事实 + 链接；ISMP 不用 |
| 8 | 维护成本：逐药人工核对不可持续 | 中 | 自动候选 CSV + "只有审核通过才进库"；按产品量排序先做头部 |
| 9 | 与其它任务冲突（schema/build.py 都有人改） | 中 | 本任务只写 `reports/dose-mapping-plan.md` + `.tmp/dose/`；schema/站点改动由对应 owner 执行并 review |

---

## 7. 附录：可执行 SQL 清单

```sql
-- A. salt 现状
SELECT COUNT(*) AS n_variant FROM variant;
SELECT COUNT(*) AS n_with_salt FROM variant WHERE salt <> '';
SELECT base_fraction, COUNT(*) FROM variant GROUP BY base_fraction;
SELECT interchange, COUNT(*) FROM variant GROUP BY interchange;
SELECT COUNT(*) FROM variant WHERE interchange_note IS NOT NULL AND interchange_note <> '';
SELECT salt, COUNT(*) c FROM variant WHERE salt <> '' GROUP BY salt ORDER BY c DESC;

-- B. 各国含盐组件占比
SELECT p.country, COUNT(*) n_comp,
       SUM(CASE WHEN v.salt <> '' THEN 1 ELSE 0 END) n_salt_comp
FROM product_component pc
JOIN product p ON p.product_id = pc.product_id
JOIN variant v ON v.variant_id = pc.variant_id
GROUP BY p.country;

-- C. salt 可疑值（非盐 token / 酯 / 水合物）
SELECT salt, COUNT(*) c FROM variant
WHERE salt <> '' AND (
      salt LIKE '%oil%' OR salt LIKE '%chelate%' OR salt LIKE '%hydrate%'
   OR salt LIKE '%valerate%' OR salt LIKE '%propionate%' OR salt LIKE '%decanoate%'
   OR salt LIKE '%palmitate%' OR salt IN ('human','h1n1','h3n2','inactivated','recombinant'))
GROUP BY salt ORDER BY c DESC;

-- D. D2 候选筛子（单盐 + 已知碱基分子量，示例：先人工维护 tmp_substance_mw）
--    join tmp_substance_mw 后按 40 行 salt 表算 f，落在 .tmp/dose/variant_base_fraction_candidates.csv

-- E. /warn 自动候选
SELECT v.substance_id, s.inn_en, COUNT(DISTINCT p.product_id) n_products
FROM product_component pc
JOIN product p ON p.product_id = pc.product_id
JOIN variant v ON v.variant_id = pc.variant_id
JOIN substance s ON s.substance_id = v.substance_id
WHERE p.release <> 'none'
GROUP BY v.substance_id HAVING n_products >= 20
ORDER BY n_products DESC;         -- 与 IR 版交集后再进人工复核队列
```

复跑审计：`python .tmp/dose/audit1.py && python .tmp/dose/audit2.py && python .tmp/dose/audit3.py && python .tmp/dose/audit4.py`
（只读 URI 打开 `data/drugs.db`，输出写 `.tmp/dose/*.txt`，不写库。）

---

## 8. 边界声明

- 本任务**未修改**任何被跟踪文件（`reports/dose-mapping-plan.md` 为新建报告，其余全部在 `.tmp/dose/`）；
- **未运行** `git`、**未运行** `site/build.py`、**未改** `site/dist`、**未写** `data/drugs.db`（全程 `file:...?mode=ro`）；
- 所有"可执行 SQL / 脚本片段"均为设计输入，不含任何已执行写操作；
- `[已验证]` 项可用 `.tmp/dose/audit*.txt` 与 PubChem CID 复现；`[推断]` 项（尤其是覆盖率外推与 US 强度基准结论）发布前需实测或按说明书逐药核对。
