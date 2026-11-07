# 数据归一化准备（dry-run）：`form_base` 876 → 30 类 + AU 单位

> 日期：2026-11-07（谷段）｜状态：**只读 dry-run 交付**，未改 `data/drugs.db`、未改 `site/ lib/ db/ docs/ deploy/`、未 commit、未发布
> 产物：`data/sources/form-normalization-20261107.csv`（876 行）、`data/sources/unit-normalization-au-20261107.csv`（87 行）、本报告
> 演练：两张表的 UPDATE 已在 `.tmp/norm/drugs-copy.db`（`data/drugs.db` 的副本）上跑通，**正式库一个字节没动**
> 关联：`reports/atc4-page-20261031.md` §4-5（剂型口径）、`reports/db-window-20261030.md` §3（CN 剂型已清洗）、`docs/谷段需求队列.md` task-148

## 0. 结论

| 项 | 数字 | 备注 |
|---|---:|---|
| `product.form_base` 取值 | **876** | 875 个非 NULL（含空串 1）+ NULL 1 |
| → 目标类目 | **32** | 30 个标准剂型 + `other` + `unknown` |
| 需改写的映射 | **851** 条 | 覆盖 100% 取值；其余 25 条是原值保留/占位符 |
| 改写影响的产品行 | **4,196** | 不含 HK 的 13,935 行 NULL；含则 18,131 |
| 改写后 `form_base` 取值数 | 875 → **32**（+NULL） | 演练实测 |
| AU `strength_unit` 取值 | **84** | 任务书写的「155」是**全市场**口径，见 §1 |
| 单位映射表行数 | **87** | 84 个 strength_unit + 2 个 per_volume 独有 + 1 行空值 |
| **可自动** | 8 个取值 / **66,021 行** | 其中需换算 5 个取值 / **6,134 行** / 2,572 产品 / 264 成分 |
| **需规则** | 76 个取值 / **21,064 行** | 复合单位、IU/生物效价、%、计数修饰词 |
| **暂不处理** | 3 个取值 / **6,940 行** | 空值 6,904 + `QS` 14 + `X` 22 |
| 是否必须重建 | **是** | `site/build.py` 全量 + `db/atc4_forms.py`；见 §4 |

**一句话**：剂型可以安全地收敛到 32 类（851 条映射、4,196 行，演练幂等）；单位只建议动 AU 的 5 个单量纲单位（6,134 行，纯机械换算），复合单位（mg/g、mg/mL…）、%、IU 类**不要**在没定 per-volume 口径前自动改。

## 1. 前置核对（三处口径差异，先对齐再执行）

| 任务书 | 现查结果 | 说明 |
|---|---|---|
| `form_base` 876 个取值 | 876（875 非 NULL + NULL） | ✅ 一致 |
| 前 30 个覆盖 99.41% | 前 30 覆盖 **99.40%** 的**非 NULL** 产品（460,404/463,163） | ✅ 一致（口径是「非 NULL」） |
| AU 单位 155 种 | AU `strength_unit` **84** 个取值（+`per_volume_unit` 4 个）；**155 是全市场** `strength_unit` 取值数 | ⚠️ 155 出自 `docs/交接-20261030.md:60` 的库级口径；AU 只是最大的集中地（SG 61、CA 34、US 14，其余市场 4–6） |

```powershell
& $py db/q.py "SELECT COUNT(DISTINCT form_base) FROM product"                       -- 875（不含 NULL）
& $py db/q.py "SELECT COUNT(*) FROM (SELECT form_base FROM product GROUP BY 1)"      -- 876（含 NULL）
& $py db/q.py "SELECT COUNT(DISTINCT strength_unit) FROM product_component"          -- 155（全市场）
& $py db/q.py "SELECT COUNT(DISTINCT pc.strength_unit) FROM product_component pc JOIN product p ON p.product_id=pc.product_id WHERE p.country='AU'"  -- 84
& $py db/q.py "SELECT country, COUNT(DISTINCT pc.strength_unit) d, COUNT(*) n FROM product_component pc JOIN product p ON p.product_id=pc.product_id GROUP BY 1 ORDER BY d DESC"
```

## 2. `form_base` 归一化（876 → 32 类）

### 2.1 目标类目（30 + `other` + `unknown`）

`tablet` `capsule` `liquid` `injection` `topical` `powder` `pellet` `pill` `suppository` `pessary`
`enema` `inhalation` `nasal` `drops` `cream` `ointment` `gel` `patch` `implant` `device`
`mouthwash` `gum` `soap` `swab` `cloth` `oil` `stick` `kit` `gas` `diagnostic` `radiopharmaceutical`
＋ `other`（无法归类）＋ `unknown`（空值/占位符）

这些名字沿用库里已经收敛出来的剂型词（CN/US/ES 等市场本来就是这套），只做了**同义收敛**，没有另造新词：

| 收敛 | 例子 |
|---|---|
| 同义写法 | `gum, chewing`→`gum`、`soap bar`→`soap`、`inhalant`→`inhalation`、`plaster`→`patch`、`salve`/`jelly`/`rinse`→`ointment`/`gel`/`mouthwash`、`globule`→`pill`、`radiofarmaco`→`radiopharmaceutical` |
| 自由文本（GB/AU/CA/US 长尾） | `clotrimazole 500mg pessaries`→`pessary`、`amorolfine 5% medicated nail lacquer`→`topical`、`salicylic acid 40% in white soft paraffin`→`ointment`、`oxygen cylinders 1360litres`→`gas`、`kit for radiopharmaceutical preparation`→`radiopharmaceutical` |
| 空值/占位符 | `NULL`→（建议**保持 NULL**）、`unknown`/`null`/`cancelado`/`-`/`route of administration oral`→`unknown` |

### 2.2 映射方式与类目分布

| 映射方式 | 取值数 | 产品行数 |
|---|---:|---:|
| 已是标准类目（原值保留） | 22 | 452,840 |
| 同义写法收敛 | 13 | 1,423 |
| 自由文本·关键词归类 | 741 | 2,525 |
| 无法归类 → `other` | 93 | 449 |
| 空值/占位符 → `unknown` | 7 | 19,861 |
| **合计** | **876** | **477,098** |

| 类目 | 产品行 | 占比 | 取值数 |
|---|---:|---:|---:|
| tablet | 182,112 | 38.17% | 51 |
| injection | 71,445 | 14.97% | 3 |
| liquid | 70,497 | 14.78% | 59 |
| capsule | 55,070 | 11.54% | 1 |
| topical | 43,410 | 9.10% | 12 |
| unknown | 19,861 | 4.16% | 7 |
| powder | 10,409 | 2.18% | 1 |
| pellet | 7,338 | 1.54% | 2 |
| inhalation | 3,222 | 0.68% | 4 |
| stick | 2,659 | 0.56% | 13 |
| kit | 2,254 | 0.47% | 8 |
| suppository | 2,052 | 0.43% | 122 |
| gas | 1,149 | 0.24% | 90 |
| pill | 810 | 0.17% | 20 |
| cloth | 773 | 0.16% | 15 |
| other | 761 | 0.16% | 171 |
| mouthwash | 641 | 0.13% | 34 |
| soap | 477 | 0.10% | 6 |
| gum | 397 | 0.08% | 8 |
| swab | 372 | 0.08% | 3 |
| oil | 280 | 0.06% | 3 |
| ointment | 204 | 0.04% | 122 |
| gel | 193 | 0.04% | 1 |
| device | 151 | 0.03% | 27 |
| nasal | 147 | 0.03% | 1 |
| implant | 114 | 0.02% | 23 |
| radiopharmaceutical | 101 | 0.02% | 23 |
| patch | 98 | 0.02% | 12 |
| pessary | 95 | 0.02% | 30 |
| drops | 3 | 0.00% | 1 |
| diagnostic | 2 | 0.00% | 2 |
| cream | 1 | 0.00% | 1 |

> `cream`/`drops`/`diagnostic` 行数少，不是漏映射：这三个形态在库里本来就大多落在 `topical`/`liquid`/`other` 桶里（ES/MX/US 源只给到 `topical`），自由文本里出现时才单独归类。

### 2.3 `other`（761 行）与 `unknown`（19,861 行）的构成

- **`other` 171 个取值 / 761 行**：GB 的营养品与器械描述（`generic promin … sachets`、`softpac … bags`、`piece (chewable)`）、`film`/`film, soluble`/`film, extended release`（口溶膜/舌下膜，**需人定归 tablet 还是 other**）、`cord`（缝线 51）、`strip`（试纸/去疣贴 39）、`disc`、`adhesivo tisular`、`laminilla`（眼用薄片）、`tea (herbal)` 等。
- **`unknown` 7 个取值 / 19,861 行**：`NULL` 13,935（**全部是 HK**，来源没有剂型列）+ `unknown` 5,872（CN 的「未知」）+ `null` 29 + `cancelado` 14 + 空串 8 + `-` 等。

> **已知限制**：`form_base='other'`（255 行）和 `'unknown'`（5,872 行）内部是**混合剂型**——CN 的真实剂型（灌肠剂 173、体外诊断试剂 150、宫内节育系统…）只存在 `dosage_form` 里。要拆这两桶必须用 `dosage_form` 二次归类，**不在本表范围**（见 `reports/intuition-audit-20261029.md` U9、`reports/cn-data-intuition-audit.md` 第 3 条）。

### 2.4 与 ATC4 页现有口径的关系

`db/atc4_forms.py` 现在是「按 `form_base` 原始值取前 30 + `other` 桶」（`KEEP_FORMS_DEFAULT=30`），所以 ATC4 页那句「876 个取值归并为 29 类」其实只是取高频。归一化落库后，`form_base` 只剩 32 类，重跑 `db/atc4_forms.py` 就自然变成干净的类目表（`other` 桶基本空掉）；页面里 `radiofarmaco`、`gum, chewing` 这类原始键会变成 `radiopharmaceutical`、`gum`。

## 3. AU 单位归一化（87 行）

### 3.1 三类计数

| 类别 | 取值数 | component 行数 | 处理方式 |
|---|---:|---:|---|
| **可自动** | 8 | **66,021** | 单量纲单位，机械换算到 mg / mL / MBq；其中 **5 个取值 / 6,134 行需要乘系数**，其余 3 个（`mg`/`mL`/`MBq`）已是目标写法 |
| **需规则** | 76 | **21,064** | 复合单位、生物效价、百分比、计数修饰词 —— 要先定 per-volume / 效价口径 |
| **暂不处理** | 3 | **6,940** | `(空)` 6,904、`QS` 14、`X` 22 |

`kind` 分布：`mass` 17 个/81,802 行 · `volume` 11/1,869 · `iu` 39/887 · `other` 19/9,022 · `percent` 1/445。

### 3.2 可自动：5 个需要换算的单位（系数已确认）

| raw_unit | 行数 | → normalized | 系数 | 说明 |
|---|---:|---|---:|---|
| `microgram` | 6,102 | `mg` | ×0.001 | 100 microgram → 0.1 mg；库里其它市场同一产品已经是 mg 小数写法（如 AU 的 `salbutamol 100 microgram/actuation` 已存 0.1 mg），口径一致 |
| `microlitre` | 22 | `mL` | ×0.001 | |
| `nanolitre` | 3 | `mL` | ×0.000001 | |
| `kBq` | 4 | `MBq` | ×0.001 | 放射性活度 |
| `GBq` | 3 | `MBq` | ×1,000 | 放射性活度 |

合计 **6,134 行 / 2,572 产品 / 264 成分**。演练后 AU 的 `strength_unit` 取值 **84 → 79**。

### 3.3 需规则：为什么不能自动

| 子类 | 行数 | 例子 | 为什么不能自动 |
|---|---:|---|---|
| 复合单位（含 `/`） | 17,907 | `mg/g`(9,678)、`mg/mL`(3,881)、`g/L`(1,251)、`microgram/g`(1,047) | 分母是 per-mass / per-volume 语义：改成单量纲要同时决定分母和 `per_volume_value` 的配对；且 `mg/g` 与 `mg/mL` 不是一回事 |
| 计数修饰词 | 1,873 | `billion`(1,356)、`million`(415)、`thousand`(61) | 要先知道底层单位是 CFU / ALU / IU（保健品、酶制剂），数据里没有 |
| 生物效价单位 | 664 | `IU`(382)、`IR/mL`(40)、`LipU`(30)、`U/mL`(24)、`DAgU`(19)、`PFU`、`CCID`、`ELISA`、`anti`… | 各效价单位**不可互换**（ALU≠IU≠CFU），只能统一写法 |
| 百分比 | 445 | `%` | 无量纲，换成 mg 需要密度/质量分数口径 |
| per-actuation | 170 | `actuation` / `actuations` / `mg/actuation` / `microgram/actuation` | 按「揿/次」计量，不是质量或体积 |
| 摩尔量 | 5 | `mol`、`nmol/mL`、`mmol/mL` | 需分子量才能换成质量 |

> 需规则里只有 **1 个取值真的要改写法**：`anti` → `anti-Xa`（17 行，dalteparin / danaparoid）。**建议先不动**：要确认这 17 行都是 anti-Xa 而不是 anti-IIa。

### 3.4 暂不处理

| raw_unit | 行数 | 原因 |
|---|---:|---|
| `(空)` | 6,904 | `strength_unit IS NULL`（AU 有 6,904 条 component 没有强度单位）→ 保持 NULL |
| `QS` | 14 | quantity sufficient，值 0，无计量意义 |
| `X` | 22 | 大麻花 `T20:C1` 之类的比例占位 |

## 4. 影响评估：哪些页面会变、变多少、要不要重建

### 4.1 会变的下游产物

| 产物 | 谁生成 | 变什么 |
|---|---|---|
| `data/idx/core.json`（检索索引） | `site/build.py`（L10521） | 结果行的 `f`（剂型集合）与规格串；索引体积轻微变化 |
| `site/dist/drug/<sid>.html` | `site/build.py` | 成分页的剂型集合、规格、多国矩阵 |
| `site/dist/name/*.html` | `site/build.py` | 单包装明细表的「剂型」「规格」列（`_name_product_table`） |
| `site/dist/atc/<code>.html`、`atc.html`、`cat/*.html` | `site/build.py` | ATC 类目页里的剂型分布 |
| `data/sources/atc4_forms_20261031.json` | `db/atc4_forms.py` | `form_base` 事实表：`other` 桶缩水、类目变干净（1.15 MiB，需重生成） |
| 检索结果行数 | `lib/search.py` 的 `sig=(country, form_base, release, …)` | 同 key 同规格的 GB 产品会合并：签名 **293,524 → 293,440（−84 行）** |

### 4.2 受影响数量（现查）

| 维度 | 数字 | 复核 |
|---|---:|---|
| `form_base` 改写产品行 | 4,196 | 演练 `changes()`；不含 HK NULL |
| 受影响成分（有产品的） | 2,444 | `SELECT COUNT(DISTINCT v.substance_id) …`（见 §2 CSV + join） |
| 受影响 ATC4 组 | 557 | 同上，`substr(atc,1,5)` |
| 受影响 `name_key`（→ name 页） | 14,869 | 同上，`product_name.key_id` |
| AU 单位换算 component 行 | 6,134 | 演练 `changes()` 合计 |
| AU 单位换算产品 / 成分 | 2,572 / 264 | 见 §3.2 |
| AU 单位换算后取值数 | 84 → 79 | 演练实测 |
| 按市场（form 改写行） | HK 13,935（NULL，建议不动）、US 1,685、GB 1,536、CA 457、ES 335、AU 121、MX 39、SG 23 | §2 CSV |

### 4.3 是否必须重建：**是**

- 不重建 → 页面继续显示旧剂型/旧单位，与库不一致；`core.json` 与 `atc4_forms.json` 也是生成物，必须重生成。
- 顺序：`db/atc4_forms.py` → `site/build.py` 跑到 `== done ==` → 按 `docs/网站优化流程.md` 的前 12 项抽检。
- **i18n 影响**：`LABEL_I18N` 只给 13 个 form 键配了译名（tablet/capsule/liquid/injection/topical/powder/suppository/inhalation/pellet/stick/kit/gas/unknown）；32 类里其余 17 类仍按原文显示（**与今天一致，不会变差**）。单位 i18n（`site/build.py` 的 `_RE_UNIT`）**大小写敏感**，只匹配小写 `microgram/unit/iu/…`：归一后 `IU` 仍不触发译名（今天也不触发），`microgram→mg` 后显示从「100 microgram（→mcg）」变成「0.1 mg」。是否让单位 i18n 大小写不敏感、是否给新剂型补译名，属于 `site/` 改动，**不在本任务写权限内**。

## 5. UPDATE SQL 模板（**不执行**；已在 `.tmp/norm/drugs-copy.db` 演练通过）

### 5.1 剂型（851 条映射，4,196 行）

```sql
-- ① 备份（DB 窗口做，不是本任务）
--    Copy-Item data\drugs.db data\backups\drugs-before-normalize-20261107.db

-- ② 前后计数
SELECT COUNT(*) AS products, COUNT(DISTINCT form_base) AS distinct_form FROM product;
--   期望 477098 / 875

-- ③ 映射表：876 行从 CSV 灌进临时表（不落库）
CREATE TEMP TABLE form_map(raw TEXT PRIMARY KEY, normalized TEXT NOT NULL);
--   数据来源（只读 CSV，生成 INSERT 或直接 executemany）：
--   & $py -c "import csv;rows=list(csv.DictReader(open('data/sources/form-normalization-20261107.csv',encoding='utf-8-sig')));print(len(rows))"   -- 876

-- ④ 先看影响面，再改
SELECT COUNT(*) AS map_to_apply FROM form_map
 WHERE raw <> '(NULL)' AND raw <> normalized;                                  -- 期望 851
SELECT COUNT(*) AS will_change FROM product p JOIN form_map m ON p.form_base = m.raw
 WHERE m.raw <> '(NULL)' AND m.raw <> m.normalized;                            -- 期望 4196

-- ⑤ 执行（HK 的 NULL 不动；'(NULL)' 行故意排除）
BEGIN;
UPDATE product
   SET form_base = (SELECT m.normalized FROM form_map m WHERE m.raw = product.form_base)
 WHERE form_base IN (SELECT raw FROM form_map
                      WHERE raw <> '(NULL)' AND raw <> normalized);
SELECT changes();                                                             -- 期望 4196
COMMIT;

-- ⑥ 后置校验（全部应通过）
SELECT COUNT(DISTINCT form_base) FROM product;                                -- 期望 32
SELECT form_base, COUNT(*) n FROM product GROUP BY 1 ORDER BY n DESC;         -- 只剩 32 类 + NULL
SELECT COUNT(*) FROM product WHERE country='HK' AND form_base IS NULL;        -- 期望仍是 13935
-- ⑦ 幂等：再跑一次 ⑤，changes() 必须是 0
```

> `(NULL)` 是 CSV 里给 NULL 用的行标识（不是真实取值）。**建议不执行 NULL→unknown**：HK 的 13,935 行 NULL 的意思是「来源没有剂型列」，写成 `unknown` 会把「没有这一列」和「有但未知」混为一谈（`db-window-prep-20261029.md` 也是这个口径）。若 Lead 坚持要写，单独一条：
> ```sql
> UPDATE product SET form_base='unknown' WHERE country='HK' AND form_base IS NULL;  -- 13,935 行
> ```

### 5.2 AU 单位（5 条，6,134 行）

```sql
-- ① 前后计数
SELECT strength_unit, COUNT(*) FROM product_component pc
  JOIN product p ON p.product_id=pc.product_id
 WHERE p.country='AU' AND strength_unit IN ('microgram','microlitre','nanolitre','kBq','GBq')
 GROUP BY 1;
--   期望 microgram 6102 / microlitre 22 / nanolitre 3 / kBq 4 / GBq 3

BEGIN;
UPDATE product_component SET strength_value = ROUND(strength_value*0.001, 9), strength_unit='mg'
 WHERE strength_unit='microgram'
   AND product_id IN (SELECT product_id FROM product WHERE country='AU');   -- changes() 6102
UPDATE product_component SET strength_value = ROUND(strength_value*0.001, 9), strength_unit='mL'
 WHERE strength_unit='microlitre'
   AND product_id IN (SELECT product_id FROM product WHERE country='AU');   -- changes() 22
UPDATE product_component SET strength_value = ROUND(strength_value*0.000001, 9), strength_unit='mL'
 WHERE strength_unit='nanolitre'
   AND product_id IN (SELECT product_id FROM product WHERE country='AU');   -- changes() 3
UPDATE product_component SET strength_value = ROUND(strength_value*0.001, 9), strength_unit='MBq'
 WHERE strength_unit='kBq'
   AND product_id IN (SELECT product_id FROM product WHERE country='AU');   -- changes() 4
UPDATE product_component SET strength_value = ROUND(strength_value*1000, 9), strength_unit='MBq'
 WHERE strength_unit='GBq'
   AND product_id IN (SELECT product_id FROM product WHERE country='AU');   -- changes() 3
COMMIT;

-- ② 后置校验
SELECT COUNT(DISTINCT pc.strength_unit) FROM product_component pc
  JOIN product p ON p.product_id=pc.product_id WHERE p.country='AU';        -- 期望 84 → 79
SELECT COUNT(*) FROM product_component pc JOIN product p ON p.product_id=pc.product_id
 WHERE p.country='AU' AND pc.strength_unit IN ('microgram','microlitre','nanolitre','kBq','GBq'); -- 期望 0
SELECT pc.strength_value, pc.strength_unit, p.dosage_form FROM product_component pc
  JOIN product p ON p.product_id=pc.product_id
 WHERE p.country='AU' AND pc.strength_unit='mg' AND pc.strength_value BETWEEN 0.0001 AND 0.01
 LIMIT 5;    -- 抽查：1600 microgram → 1.6 mg、100 microgram → 0.1 mg
```

### 5.3 执行顺序（DB 窗口照这个走）

1. 读本报告 + 拍板 §6 的 5 个决策点；
2. `Copy-Item data\drugs.db data\backups\drugs-before-normalize-20261107.db`（回滚点）；
3. 只做 **§5.1 剂型** → 校验 ⑥（32 类、HK NULL 不变、幂等 0）；
4. 只做 **§5.2 AU 单位** → 校验（79 个取值、5 个单位清零）；
5. `& $py db/check_data.py`（before/after 各跑一次，贴进 DB 窗口报告）；
6. `& $py db/atc4_forms.py`（重生成 `atc4_forms_20261031.json`）；
7. `& $py site/build.py` 等到 `== done ==`；
8. 抽检：AU 3 条（原先 microgram 的）、GB 3 条（自由文本剂型）、三语各 1 次检索；
9. 计数口径：产品/成分总数不变（477,098 / 12,649），`README`/About/`coverage` 的条数**不需要改**；若 `docs/`/`reports/` 里提到「876 个剂型取值」，改这处文字（不在本任务写权限内）；
10. 发布走 `deploy/publish.ps1`（另批，本次不发布）。

**回滚**：`data/backups/drugs-before-normalize-20261107.db` 覆盖回去 → 重建站。两张映射表都是纯函数映射，回滚后再执行一遍即可复现。

## 6. 需 Lead 拍板（5 点）

1. **类目合并**：`rinse→mouthwash`、`jelly→gel`、`salve→ointment`、`inhalant→inhalation`、`plaster→patch`、`gum, chewing→gum`、`pastille/globule→pill`、`lipstick→topical`、`radiofarmaco→radiopharmaceutical`（合计约 1,100 行会改显示）。接受还是保持原值？
2. **HK 的 NULL**：保持 NULL（建议）还是写 `unknown`（13,935 行）？
3. **单位范围**：本轮只做 AU 的 5 个换算，还是同一窗口把 **SG（61 个取值，`mg/vial`、`mcg/mL`…）/ CA（`mCi`、`mmol`、`VP`…）/ US（`mEq`、`kg`、`Ci`、`µCi`…）** 也归进来？本表只覆盖 AU，其它市场要扩表。
4. **`anti` → `anti-Xa`**：17 行（dalteparin / danaparoid）是否确认全部是 anti-Xa？
5. **`site/` 侧是否同窗口改**：单位 i18n 大小写不敏感、给 32 类补译名（会让 17 类从英文原文变成中文/西语），这属于页面改动 + 需要跑全套验收。

## 7. 复现与边界

- 两张 CSV 是**交付物、也是唯一真相源**：每行 `raw → normalized` 都能单独核对；`note` 里写了归类依据/换算系数。
- 生成脚本是 scratch（`.tmp/norm/build_tables.py`，未进仓库）：从 DB 只读取值 + 跑规则 + 写 CSV。DB 窗口不需要它，直接按 CSV 执行即可。
- 演练脚本 `.tmp/norm/rehearse.py` 在 `data/drugs.db` 的**副本**上执行了 §5 的全部 SQL，输出见本报告 §0/§4.2 的实测数字。
- 只读：DB 连接全部 `mode=ro`（演练用的是副本）；未改 `data/drugs.db`、`site/`、`lib/`、`db/`、`docs/`、`deploy/`；未 commit、未发布。

_本报告为 dry-run 准备：映射表是「建议」，SQL 是「模板」，都不代表已经执行。_
