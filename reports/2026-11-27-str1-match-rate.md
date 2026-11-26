# STR1 前置复测：PubChem 名称匹配率（300 样本，原始 vs 规范化）

日期：2026-11-27（北京）｜执行：backend（task-2）｜类型：只读分析 + 报告
关联：`docs/谷段需求队列.md` STR1（第 38 行）、[2026-11-26 STR1 可行性报告](2026-11-26-str1-structure-license-feasibility.md)
脚本：[etl/pubchem_match_eval.py](../etl/pubchem_match_eval.py)｜结果：`data/raw/pubchem-match-eval/eval-300.json`（缓存，不入库）

## 0. 结论先行

| 问题 | 结论 |
|---|---|
| **是否达到「≥85% 命中」可实施门槛** | **❌ 未达到**。全样本 after = **105/300 = 35.0%**；即使只看英文名（248 条）也只有 **41.9%**；有 ATC 的子集 **51.6%**；小分子粗筛子集 **82.1%**，仍差 2.9 个百分点 |
| before / after | 原始 `inn_en`：**97/300 = 32.3%**；规范化后（任务指定的去括号 / 去盐·酯 / 去 `(as …)` / 拆复方）：**105/300 = 35.0%（+8）**；再加共晶配体与脏前缀清理：**107/300 = 35.7%（+10）** |
| 为什么提升有限 | 主要瓶颈不是匹配写法，而是 **`substance.inn_en` 的名字集合**：全表非 ASCII **2,332 条（14.1%）**，其中中文 **1,760 条（10.6%）**；样本未命中的 193 条里 **173 条**是中文 / 草药 / 生物制品 / Generic 配方 / 剂型浓度名，规范化救不了 |
| 理论上限 | ASCII 名 **14,218 / 16,550 = 85.9%**——就算每条英文名都命中，也刚好贴着 85% 门槛；不翻译中文名（或换结构标识通道）不可能稳定超过 85% |
| 全量预计 | 按 after 35.0% 外推 **≈5,800 张**；按 ASCII 命中率外推 **≈5,963 张**；按小分子粗筛面外推 **≈6,487 张**。规划取 **6,000–6,500 张** |
| 图片体积 | 300×300 实测均值 **2,865 B/张**（2026-11-26 的 50 张实测）→ **15.8–17.7 MB**；按任务给的 1.6–4.1 KB 极值 **9.1–25.3 MB**。200×200 均值 1,784 B → **10.2–11.0 MB** |
| 建议 | **不要把「全量 16,550 × 85%」作为 STR1 验收门槛**。要么把 STR1 限定到「可结构面」清单（粗筛 7,900 条，样本 82.1%，需更大样本确认），要么换 ATC / ChEMBL / UniChem 的结构标识通道；不要用模糊匹配补缺口（会把结构图配错药）。需 Lead 拍板范围与门槛 |

> 一句话：**规范化只把 32.3% 抬到 35.0%，离 85% 差 50 个百分点；差的不是算法，是中文名 / 生物制品 / 草药 / 非 INN 这些「本来就没有英文小分子结构」的名字。**
> 若把 STR1 定位为「英文小分子可结构面」：粗筛样本 **101/123 = 82.1%**（95% CI 74.4–87.9），仍低于 85%；事后剔除 9 条明显非单一成分（`Dog Rose Without Achenes`、`rhizoma chuangxiong`、`Magnesium Amino Acids Chelate`、`Iodophor`、`Polyoxyethylene Lauryl Ether`、`Quinoline mix`、`S.a.`、`Condensed Glucose`、`Crofelemer`）后为 **101/114 = 88.6%**（95% CI 81.5–93.2），点估计过线但区间跨 85%，且是事后口径，**不能据此宣称全量达标**。

## 1. 口径与可复现命令

### 1.1 样本（与 2026-11-26 报告同一种子，便于对照）

```sql
-- 只读连接：file:data/drugs.db?mode=ro
SELECT substance_id, inn_en, COALESCE(atc, '') FROM substance ORDER BY inn_en;
```

Python 侧：`random.Random(20261126).sample(names, 300)`，再按名字排序。
全表 **16,550** 条；样本 **300** 条（ASCII 248 / 中文 40 / 非 ASCII 52 / 有 ATC 128）。
本轮原始名结果与 2026-11-26 探针缓存**逐条比对 300/300 一致**（状态与首个 CID 均相同），说明抽样与 before 基线可复现。

### 1.2 全表构成（现查，不抄旧数字）

| 口径 | 条数 | 占 16,550 |
|---|---:|---:|
| `substance` 总数 | 16,550 | 100% |
| ASCII 名 | 14,218 | **85.9%** |
| 含汉字 | 1,760 | 10.6% |
| 非 ASCII | 2,332 | 14.1% |
| 有 ATC | 6,865 | 41.5% |
| 小分子可结构面（粗筛，见 §4） | **7,900** | 47.7% |

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/q.py "SELECT COUNT(*) AS n, SUM(atc IS NOT NULL AND atc <> '') AS atc FROM substance"
& $py etl/pubchem_match_eval.py --plan     # 只算样本 / 候选，不发请求
& $py etl/pubchem_match_eval.py --run      # 300 条 + 规范化候选
```

> ASCII / 汉字 / 非 ASCII / 可结构面的全表数字由脚本对 `SELECT inn_en FROM substance` 逐条扫描同一套纯函数得出（不是另写 SQL 估算）；抽样 SQL 见 §1.1。

### 1.3 网络纪律

| 项 | 本轮值 |
|---|---|
| 端点 | `GET https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/<urlquote(name)>/cids/JSON` |
| UA | `drugcrossref-match-eval/1.0 (+https://drugcrossref.com/; contact via drugcrossref.com)` |
| 限速 | 单进程串行，每次请求后 `sleep 0.22 s`（上限 ≈4.5 req/s，低于官方 5 req/s）；实测整体 342 请求 / 91.9 s ≈ **3.72 req/s**（含响应时间） |
| 重试 | 404 不重试；429 / 5xx 指数退避最多 3 次 |
| 本轮请求 | 新增 **342** 次（200: 107 / 404: 235 / 其他: 0），**0 次 429/503**，0 重试，0 错误 |
| 缓存 | `data/raw/pubchem-match-eval/cid-cache.jsonl`（JSONL，不入库）；重跑 343 命中缓存、0 新请求 |
| 结果 | `data/raw/pubchem-match-eval/eval-300.json`（逐条记录 + 汇总） |

### 1.4 规范化分档

| 档位 | 做什么 | 计入 after |
|---|---|---|
| `raw` | 原始 `inn_en` | 是 |
| `clean` | NFKC、去 ®™©、折叠空白、去尾部标点 | 是 |
| `paren` | 去括号：删 `(as …)`、盐型/晶型/同位素/编码/包装说明等限定括号；**化学分组括号只去括号、保留内容**（`(4 Methoxyphenyl)Glyoxal` → `4 Methoxyphenyl Glyoxal`，**不会**变成 `Glyoxal`） | 是 |
| `salt` | 从尾部逐词去盐/酯/水合物/络合词（如 hydrochloride、sodium、sulfate、citrate、succinate、hydrate、complex），处理化学计量数字与 `sulfate-iron` 复合词；只剩金属离子时拒绝查询 | 是 |
| `combo` | 复方按 `+ & ; / and with` 拆分，逐段再走括号/盐处理 | 是（但单独标注：只代表某个成分） |
| `coformer` | 去共晶配体（如 `dapagliflozin Bis L-proline` → `dapagliflozin`） | 附加档 |
| `dirty` | 去 `Equivalent:` 前缀、`.Mu.` 编码残留 | 附加档 |

**安全阀**：不做模糊匹配、不用 PubChem autocomplete、不删化学取代基、不把 `Cobaltous Carbonate` 这类名字降成 `Cobaltous`（金属离子）去查；命名候选少于 2 字符 / 以连接词结尾 / 只剩通用词时直接拒绝。上一轮一次性探针（`.tmp/str1_probe.py`）的 N2 会把括号内容删掉，曾把 `(4 Methoxyphenyl)Glyoxal` 查成 `Glyoxal`（CID 7860，配错药），本轮已修正该口径，这一条**不再算命中**。

## 2. before / after 对照

### 2.1 总表

| 口径 | n | before（原始名） | after core（任务指定四类规范化） | after extended（+共晶/脏前缀） |
|---|---:|---:|---:|---:|
| **全部样本** | 300 | **97（32.3%）** | **105（35.0%，+8）** | **107（35.7%，+10）** |
| ASCII 名 | 248 | 97（39.1%） | 104（41.9%） | 106（42.7%） |
| 中文名 | 40 | 0（0%） | 0（0%） | 0（0%） |
| 有 ATC | 128 | 62（48.4%） | 66（51.6%） | 66（51.6%） |
| 小分子粗筛面 | 123 | 94（76.4%） | 101（82.1%） | 101（82.1%） |

- 原始命中在规范化阶段**零丢失**（命中即停，不会把已命中的名字再改坏）。
- McNemar 精确检验（新增 8 / 丢失 0）：**p = 0.0078**（core）；extended 新增 10 / 丢失 0，**p = 0.0020**。提升统计上显著，但幅度只有 +2.7 个百分点（全样本）。
- 95% Wilson CI：before 27.3–37.8%；after core 29.8–40.6%；after extended 30.5–41.2%；ASCII core 36.0–48.2%；ATC core 43.0–60.0%；小分子粗筛 74.4–87.9%。

### 2.2 分档增量（谁贡献了 +10）

| 档位 | 新增命中 | 说明 |
|---|---:|---|
| `raw` | 97 | 基线 |
| `paren` | **+5** | `L-asparaginic acid(A실300ml중)`、`belotecan(CKD-602)`、`dapagliflozin Bis L-proline (as dapagliflozin)`、`risedronate sodium 2.5 hydrate(enteric coated)`、`sodium chromate(cr-51)` |
| `salt` | **+3** | `Doxorubicin Citrate Complex`、`Ferric Citrate Coordination Complex`、`chondroitin sulfate-iron complex` |
| `combo` | **0** | 本样本 2 条复方：`Thiopental Sodium And Sodium Carbonate` 原始名已命中；`Hawthorn Leaf With Flower` 拆分后各段仍 404 |
| `coformer` | **+1**（附加） | `empagliflozin L-proline (as empagliflozin 25mg)` → `empagliflozin` |
| `dirty` | **+1**（附加） | `.Mu. Conotoxin G Iiic` → `Mu Conotoxin G Iiic`（CID 119058018，mu-Conotoxin G IIIC） |

### 2.3 新增命中逐条核对（CID 与 PubChem Title）

| 档位 | 原始 `inn_en` | 实际查询 | CID | PubChem Title |
|---|---|---|---|---:|---|
| paren | `L-asparaginic acid(A실300ml중)` | `L-asparaginic acid` | 5960 | L-Aspartic Acid |
| paren | `belotecan(CKD-602)` | `belotecan` | 6456014 | Belotecan |
| paren | `dapagliflozin Bis L-proline (as dapagliflozin)` | `dapagliflozin Bis L-proline` | 25032144 | Dapagliflozin diproline |
| paren | `risedronate sodium 2.5 hydrate(enteric coated)` | `risedronate sodium 2.5 hydrate` | 11954322 | Risedronate sodium hemi-pentahydrate |
| paren | `sodium chromate(cr-51)` | `sodium chromate` | 24488 | Sodium Chromate |
| salt | `Doxorubicin Citrate Complex` | `Doxorubicin Citrate` | 50925403 | Doxorubicin citrate（络合物） |
| salt | `Ferric Citrate Coordination Complex` | `Ferric Citrate` | 61300 | Ferric citrate |
| salt | `chondroitin sulfate-iron complex` | `chondroitin sulfate` | 24766 | Chondroitin Sulfate |
| coformer | `empagliflozin L-proline (as empagliflozin 25mg)` | `empagliflozin` | 11949646 | Empagliflozin |
| dirty | `.Mu. Conotoxin G Iiic` | `Mu Conotoxin G Iiic` | 119058018 | mu-Conotoxin G IIIC |

**多 CID**：本轮 107 个命中里只有 1 个原始命中返回多个 CID（`Hydroxocobalamin Chloride` → `[154701308, 146014417]`，取第一个）；10 个规范化新命中均为单 CID。多 CID 的选取策略（按名称精确度 / 盐型 / 人工复核）尚未定，需在入库前补规则。

## 3. 失败分类（193 条未命中）

| 类别 | 条数 | 占未命中 | 代表样例（原文照抄） |
|---|---:|---:|---|
| 草药 / 提取物 / 动植物组织 | 52 | 26.9% | `Agrimony`、`Arnicae`、`Cocillana`、`Betula Pendula Wood`、`Beef Heart`、`Camellia Japonica Seed Oil` |
| 中文名（需翻译/映射） | 40 | 20.7% | `丁甘交联玻璃酸钠`、`乙磺酸尼达尼布`、`人尿激酶原`、`他扎罗汀倍他米松`、`醋酸阿托西班` |
| 生物制品 / 疫苗 / 抗体（无小分子 2D 结构） | 36 | 18.7% | `Atezolizumab`、`Crizanlizumab`、`Catridecacog`、`Hepatitis A Vaccine`、`Tetanus Toxoid Antigen`、`Anti-D Rho Immunoglobulin` |
| 拼写/语言变体或非 INN（未归类） | 20 | 10.4% | `(4 Methoxyphenyl)Glyoxal`、`Cemivameran`、`Clofenamina`、`Co-Methiamol`、`Condensed Glucose`、`Crofelemer`、`Cipionato`、`Pegunigalsidasa Alfa`、`Trafermin`、`erythromycine lactobionate` |
| 非 INN（Generic / 配方名） | 17 | 8.8% | `Generic Nutriflex Plus 2Litre Bags`、`Generic Synthamin 17 Bags`、`Generic Elleste Duet`、`Generic Lipoflex Plus 1 25Litre Bags` |
| 非英文 / 本地文字（重音、韩文残留等） | 11 | 5.7% | `Antipoliomielítica Inactivada`、`Hidrógenofosfato Disodio`、`Oxibuprocaína`、`cinnamon bark tinc.(1→5)`、`zanthoxylum fruit 30% ethanol soft ext.(3.3→1)` |
| 非 INN（剂型 / 浓度 / 混合物） | 7 | 3.6% | `Glucose 10%`、`Sodium Chloride 0 9% Intravenous Ampoules`、`Oxygen 50% Cylinders 2730Litres`、`cyanocobalamin 0.1 %`、`oxygen gas 93%   10L` |
| 数据脏（前缀 / 编码残留） | 5 | 2.6% | `Equivalent: Aloysia Citrodora`、`Equivalent: Bacopa Monnieri`、`Equivalent: Cistanche Deserticola`、`Equivalent: Equisetum Arvense`、`Equivalent: Sambucus Nigra` |
| 盐 / 酯形式（基名也无 PubChem 记录） | 3 | 1.6% | `Cipionato`、`Dl-Alpha-Tocopheryl Acid Succinate`、`Thallous 201Tl Chloride` |
| 顺势药 / 稀释液 | 2 | 1.0% | `Allium Cepa 3 C`、`Calcii Fluoridum Dilutio Homeopathica` |
| **合计** | **193** | **100%** | 全部名单见 `data/raw/pubchem-match-eval/eval-300.json` 的 `rows[].miss_class` |

> 名称缩写（如 `S.a.`）与商品配方名（`Generic …`）归入「非 INN」两档；复方在本样本没有形成独立失败类——2 条复方里 1 条原始名已命中（`Thiopental Sodium And Sodium Carbonate`），1 条按植物类归因（`Hawthorn Leaf With Flower`），复方拆分本身 +0。

### 3.1 Top 失败清单（优先看「还有没有救」）

1. **可能靠拼写/语言变体修复（但不做模糊匹配）**：`Clofenamina`（氯苯那敏）、`Cipionato`（cypionate 的西班牙语写法）、`Pegunigalsidasa Alfa`（pegunigalsidase alfa）、`Diyodohidroxiquinolei Na`、`L-glutamicacid`、`erythromycine lactobionate`——需要词典/翻译，不能靠编辑距离。
2. **中文名 40 条**：需要 `inn_zh ↔ inn_en` 的映射或翻译；目前 `substance.inn_en` 里混入 1,760 条中文，单靠英文名匹配永远为 0。
3. **生物制品 36 条**：单抗、酶、凝血因子、疫苗、多糖结合疫苗——**本来就没有小分子 2D 结构**，即使 PubChem 有 CID 也不应画「结构式」。
4. **草药/动植物 52 条**：提取物、全草、根、油、组织——同样没有单一结构式。
5. **Generic / 配方 / 剂型 24 条**（17+7）：TPN 袋、造影剂、氧气钢瓶、浓度规格名——需要先归一化到成分，不能直接按商品名画结构。
6. **数据脏 5 条**（全部 `Equivalent:` 前缀）：应清掉前缀后再查；`.Mu.` 编码残留 1 条已在本轮 dirty 档修复（Mu-Conotoxin G IIIC），不在失败清单里。

> **关键算术**：当前 after core 105；要达 85%（255/300）还差 **150 条**。193 条未命中里 173 条属于中文/生物/草药/Generic/剂型等结构性不匹配；只有 20 条残余「可能靠拼写/词典/人工复核修复」。**即使 20 条全修好，也只有 125/300 = 41.7%**，离 85% 仍差 43.3 个百分点。

## 4. 全量 16,550 的外推与图片体积

### 4.1 命中数

| 外推口径 | 公式 | 预计命中 |
|---|---|---:|
| before 原始名 | 97/300 × 16,550 | **5,351** |
| after core（样本整体） | 105/300 × 16,550 | **5,792** |
| after core（ASCII 命中率 × 全表 ASCII） | 104/248 × 14,218 | **5,963** |
| after core（小分子粗筛面） | 101/123 × 7,900 | **6,487** |
| after extended（样本整体） | 107/300 × 16,550 | **5,903** |

规划取 **6,000–6,500 张**（相对 2026-11-26 报告的规划值 5,000 张，增加约 1,000–1,500 张；旧区间 3,300–5,100 的上沿是 5,100，新规划仍高于它约 900–1,400 张）。

### 4.2 体积

按 2026-11-26 对 50 张 300×300 PNG 的实测：均值 **2,865 B**、min 252 B、max 5,448 B；本轮按任务给的 **1.6–4.1 KB** 区间做保守估算。

| 规模 | 300×300（均值 2,865 B） | 300×300（1.6–4.1 KB） | 200×200（均值 1,784 B） |
|---|---:|---:|---:|
| 5,792 张（简单外推） | 15.83 MB | 8.84–22.65 MB | 9.85 MB |
| 5,963 张（ASCII 外推） | 16.29 MB | 9.1–23.3 MB | 10.15 MB |
| **6,487 张（小分子粗筛）** | **17.72 MB** | **9.90–25.36 MB** | **11.04 MB** |
| 6,973 张（事后严格敏感性，仅参考） | 19.05 MB | 10.64–27.26 MB | 11.86 MB |

- 相对现 `site/dist`（2026-11-26 实测 362,112 文件 / 3,282.9 MB）：6,487 张 300px = **+0.54% 体积、+1.79% 文件数**；6,487 次一次性 GET/PUT，远低于「单次 >50,000 需 Lead 批准」的门槛，但仍是当月 R2 PUT 额度的一部分，发布报告要记「本次 PUT / 当月累计 / 占免费额度 %」。
- 若只做 3,300–5,100 张的旧规划，体积为 9–14 MB；规范化后建议按 **6,000 张左右** 备容量，不要按 16,550 全量备。

### 4.3 与上一版报告的差异

| 项 | 2026-11-26 报告 | 本轮 | 差异 |
|---|---:|---:|---|
| 300 样本 before | 97/300（32.3%） | 97/300（32.3%） | 一致（逐条 300/300 相同） |
| 300 样本 after | 未做（仅有 53 条子集探针） | 105/300（35.0%）；extended 107/300（35.7%） | 首次给出可复现的 300 条 after |
| 预计图张数 | 3,300–5,100（规划 5,000） | 5,800–6,500（规划 6,000–6,500） | +约 1,000–1,500 张 |
| 300px 体积 | 13.7 MB（5,000 张） | 17.7 MB（6,487 张） | +4.0 MB，仍 <0.6% dist |

## 5. 门槛判定与建议（需 Lead 拍板）

### 5.1 判定

**按任务口径（300 全样本，after 35.0%）——未达到 ≥85%。**
按任何单一子集也都没有稳定达到：

| 子集 | after core | 95% CI | 对 85% 的判定 |
|---|---:|---:|---|
| 全样本 300 | 35.0% | 29.8–40.6% | ❌ 远低于 |
| ASCII 248 | 41.9% | 36.0–48.2% | ❌ 远低于 |
| 有 ATC 128 | 51.6% | 43.0–60.0% | ❌ 远低于 |
| 小分子粗筛 123 | 82.1% | 74.4–87.9% | ❌ 点估计差 2.9 pp，CI 跨 85% |
| 事后严格剔除 9 条非单一成分（114） | 88.6% | 81.5–93.2% | ⚠️ 点估计过线，但事后口径、CI 下界 <85%，不能宣称稳定达标 |

**原因不是规范化写得不够，而是分母里 14.1% 是非 ASCII 名、且大量英文名本身不是「单一小分子药物」**。85% 门槛正好压在 ASCII 占比 85.9% 的天花板上：不处理中文名，理论最高就只有 85.9%。

### 5.2 三个可选方案

| 方案 | 做法 | 预计图数 | 风险 / 代价 |
|---|---|---|---|
| **A（推荐）限定范围 + 重新定门槛** | STR1 只覆盖「英文、单一小分子、非生物制品/草药/复方/剂型」的可结构面清单（粗筛 7,900 条）；门槛从「全量 85%」改为「可结构面 ≥80% + 覆盖数 ≥6,000」，先用 1,000 条样本确认 ≥80% | ≈6,487 张 | 需要把粗筛规则固化成可审计清单（不是临时 SQL）；约 1,400 条可结构面仍会没有图（正常，PubChem 无记录） |
| **B（若 85% 是硬门槛）预注册严格清单 + 扩大验证** | 在 A 的基础上再剔除植物聚合物/矿物螯合物/辅料/缩写等非单一成分，预注册约 7,870 条清单；用 ≥1,000 条样本验证，目标 ≥85% | ≈7,000 张 | 事后剔除会抬高比例，必须先定清单再抽样；本轮 88.6% 的 CI 下界 81.5%，样本太小 |
| **C 换匹配通道** | 用 ATC / ChEMBL / UniChem / PubChem xref 按结构标识补中文名和拼写变体；生物制品与草药仍无 2D 结构 | 可能 >7,000（但增量不确定） | ChEMBL 许可 CC BY-SA 3.0（见 2026-11-26 报告 §1.6），映射与许可成本高；不解决「无结构」类 |
| **不做** | 用 PubChem autocomplete / 模糊匹配补缺口 | — | **禁止**：会把结构图配到错误药物（上一轮已实测 `Atezolizumab` 等会返回无关结果），触碰 §1 底线 |

### 5.3 建议的验收口径（供 Lead 选择）

- 若走 A：**「可结构面 7,900 条，样本外推命中 ≥80%，计划 6,000–6,500 张，300px ≈17.7 MB」**；85% 不作为全量门槛。
- 若走 B：**先冻结清单，再用 ≥1,000 条独立样本验证 ≥85%**；本轮 300 条的 88.6% 只能作为假设，不能作为验收证据。
- 若必须覆盖 16,550 全量：**85% 在名字匹配通道下不可达**；需要先做中文名翻译/映射（预计最多把 40 条中文样本变成命中，全量 +700 左右）或换结构标识源，且生物制品/草药仍无图。

## 6. 外部方案检索（先找现成工具）

本项目上一轮已做过数据源与许可检索（见 [2026-11-26 报告](2026-11-26-str1-structure-license-feasibility.md) §1.6、§4）；本轮是同一通道的匹配率复测，不新增数据源，沿用结论并核对实现选型：

| 候选 | 结论 | 不采用 / 采用原因 |
|---|---|---|
| **PubChem PUG-REST + 标准库 urllib** | ✅ 采用 | 无第三方依赖、可精确控制 UA/限速/重试/缓存；本轮 342 请求 0 429/503 |
| **PubChemPy**（社区 Python 封装） | ⚪ 不采用 | 只是 PUG-REST 的薄封装；本项目已有统一请求/缓存纪律，引入依赖无收益；许可与维护状态未在本轮复核 |
| **RDKit + PubChem FTP SDF** | ⚪ 不采用（v2 备选） | 需下载数十 GB SDF + 本地渲染；本轮只需名字命中率，不引入重依赖 |
| **ChEMBL / UniChem / PubChem xref** | 🟡 留作方案 C | 可按 ATC/结构标识补覆盖；ChEMBL 为 CC BY-SA 3.0（2026-11-26 报告已核），许可与映射成本需 Lead 拍板 |

## 7. 边界与已知缺口

- **只读**：未写 `data/drugs.db`、未建表、未改 `db/schema.sql`、未 ingest、未 build、未发布、未 commit；脚本只读 DB + 网络，缓存写 `data/raw/`。
- **没做**：中文名翻译/映射、拼写变体词典、模糊匹配、按 ATC/ChEMBL 的交叉匹配；未拉取图片（体积沿用上一轮 50 张实测）；未对 97 个原始命中逐条人工核 CID（只对 10 个规范化新命中核了 Title）。
- **多 CID**：`Hydroxocobalamin Chloride` 原始命中 2 个 CID，本轮取第一个；入库前需定「多 CID 选一」规则（否则可能选到不同盐型/晶型）。
- **分类是规则自动分**：`miss_class` 有少量边界误判（如少数多词生物制品/植物名可能落入相邻类），报告按大类看趋势，不按单条做数据结论。
- **统计不确定性**：300 样本的 after core 95% CI 约 29.8–40.6%（extended 30.5–41.2%）；小分子粗筛 123 条的 CI 74.4–87.9%；所有外推都是点估计，STR1 立项前建议至少 1,000 条验证。
- **数据副产品（不属 STR1，建议另开单）**：`substance.inn_en` 里 `Equivalent: …` 5 条、`.Mu.` 编码残留、以及 1,760 条中文名；这些会持续拖累任何「按英文名匹配外部源」的工作。

## 8. 复现与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/pubchem_match_eval.py --plan
& $py etl/pubchem_match_eval.py --run
# 重跑（全缓存，0 新请求）：
& $py etl/pubchem_match_eval.py --run

# 核对原始缓存与上一轮探针一致：
& $py -c "import json; old={r['inn_en']:r for r in [json.loads(l) for l in open('data/raw/pubchem-probe/cid-probe-300.jsonl',encoding='utf-8')]}; new={r['inn_en']:r for r in json.load(open('data/raw/pubchem-match-eval/eval-300.json',encoding='utf-8'))['rows']}; print(sum(1 for n,o in old.items() if (o.get('cid') or None)!=(new[n]['raw_cid'] or None)))"
```

产物：

- `etl/pubchem_match_eval.py`（本任务新增脚本）
- `data/raw/pubchem-match-eval/cid-cache.jsonl`（342 条唯一查询缓存；本轮 343 次查询 = 342 新增 + 1 命中缓存，不入库）
- `data/raw/pubchem-match-eval/eval-300.json`（逐条样本 + 汇总 + 外推）
- 本报告

**一句话交接**：规范化把 PubChem 名称命中从 32.3% 提到 35.0%（+8 条，p=0.008），但距离 85% 差 50 个百分点；瓶颈是中文名/生物制品/草药/非 INN 的结构性缺口，建议 Lead 在「限定可结构面 + 80% 门槛」与「换 ATC/ChEMBL 通道」之间拍板，不要按全量 85% 立项。
