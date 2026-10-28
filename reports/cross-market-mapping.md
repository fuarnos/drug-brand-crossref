# 药物互相对应审计 + 合并候选（task-40）

> 日期：2026-10-28 ｜ 数据库：`data/drugs.db`（**只读**，本轮未写入）｜ 未跑 git / 发布 / `site/build.py`
> 产物：`data/cross_market_merge_candidates.csv`（457 行）、`etl/build_cross_market_candidates.py`（可重跑、只读）、`.tmp/cross-market/audit.json`（审计全量）、本报告。
> 说明：候选只是「可审核清单」，**不自动 apply**；apply 走既有 `merge_cn_substances.py` / `merge_es_substances.py` 的安全预检。

---

## 1. 结论（先说重点）

1. **成分×市场**：12,790 个 substance 中 12,377 个有产品；**2,953 个（23.86%）出现在 ≥2 个市场**——这是当前的「跨市场链接率」。
   单市场成分 9,424 个（其中 cn- 1,827 全部只在中国、mx-es- 715 只在 ES/MX 为主）。
2. **重复成分**：`reports/substance_duplicates.csv` 30 行 → 28 个 canonical、**27 个 dup 仍在库**；其中 **25 对** canonical+dup 都还在 substance 表（可合并），2 对 canonical 已不在库（需按「改名/升格」处理，见 §5）。
3. **复方同集合匹配**：48,554 个复方产品（去重后 ≥2 个不同成分）→ 7,757 个成分集合；**704 个集合（9.08%）出现在 ≥2 个市场**，覆盖 30,699 个产品。含 cn-/mx-es- 成分的集合 268 个；跨市场且涉及 CN/ES/MX 的集合 348 个。
4. **合并候选 457 条**：**mergeable 178**、needs_target 52、uncertain 227（只记录不写）。按前缀：**cn-* 41**（16 个单方合并 + 25 对重复成分）、**mx-es-* 95**、**非前缀西语 id 42**。
5. **模拟应用 178 条合并**（只算 mergeable 且有目标的）：
   - 成分：12,790 → **12,612**；≥2 市场成分 2,953 → **2,977**（把源市场并入目标）；跨市场链接率 23.86% → **23.60%**（分母缩小，比率略降但绝对多市场成分 +24）；
   - 复方：同集合跨市场集合 **704 → 710（+6）**、匹配率 9.08% → **9.18%**、匹配产品 30,699 → **30,827（+128）**；含 prefix 成分的集合 268 → 239（被合并吸收）。
6. **一句话**：单方合并能小幅提升跨市场链接（尤其 ES/MX 的 95 条 + 重复对 25 条）；**复方同集合匹配率低（9%）的主因不是成分 id 没合并，而是同名复方在各国的配比/剂型/组合不同**——合并只能解锁 +6 个集合，剩余要靠「成分集合近似匹配 + 配比核对」，不在本轮范围。

---

## 2. 审计口径与方法

脚本：`etl/build_cross_market_candidates.py`（只读 `data/drugs.db` + `data/` 下既有映射表）。
成分→市场映射 = `variant → product_component → product.country` 去重；复方集合 = 一个产品所有 `product_component.ord` 映射到 `substance_id` 后**去重排序**（≥2 个才算复方）。

证据来源（每条候选都有 evidence 字段）：

| evidence_type | 来源 | 本次条数（全部/其中 mergeable） |
|---|---|---:|
| existing_override | `data/cn_inn_overrides.csv` / `data/es_inn_overrides.csv` 中**尚未应用**的行（原 status=uncertain/no_english，带 en_inn） | 214 / 148 |
| duplicate_name | `reports/substance_duplicates.csv`（同名重复成分） | 25 / 25 |
| who_inn | `data/who_inn_names.csv`（WHO INN 官方中文/西语名 → 英文 INN，1,737 行） | 15 / 2 |
| cn2en | `etl/ingest_nhsa.py` 的 CN2EN 表（1,088 条） | 12 / 2 |
| mx_inn_map | `data/mx_inn_map.json`（西语→英文 INN，1,378 条） | 59 / 1 |
| cn_old_name | `data/cn_aliases_final.csv`（中文旧称/别名→现通用名，2,362 条）+ 上述表 | 1 / 0 |
| cima_vtm | CIMA 单方产品 `vtm`（西语名→库内 substance，1,810 条） | 0 / 0 |
| atc4 | 成分 ATC 前 5 位唯一命中英文成分（**弱证据**，仅记 uncertain） | 131 / 0 |

**安全复检（写进脚本）**：`mergeable` 必须通过「盐型/立体/复方」检查——源名里的盐/酯/水合物/立体标记（如 盐酸/钠/苯甲酸/右旋/乙酰/碳酸/水杨酸…）必须能在目标 `inn_en` 或目标的 variant `salt` 里找到对应；否则降级 uncertain。本轮 **96 条因此从 mergeable 降为 uncertain**（例：`乳酸亚铁→iron`、`右旋酮洛芬→ketoprofen`、`溴化钙→calcium`、`碳酸钙D₃→calcium-carbonate`）。另对 `mx_inn_map` 同名自匹配（如 `dimeticona→dimeticona`）做了剔除。

---

## 3. 成分×市场矩阵（before）

| 市场数 | 成分数 | 占比 |
|---:|---:|---:|
| 1 | 9,424 | 76.1% |
| 2 | 1,010 | 8.2% |
| 3 | 492 | 4.0% |
| 4 | 378 | 3.1% |
| 5 | 325 | 2.6% |
| 6 | 331 | 2.7% |
| 7 | 417 | 3.4% |
| **合计（有产品）** | **12,377** | 100% |

- **≥2 市场成分 2,953 / 12,377 = 23.86%**（跨市场链接率）。
- 各市场成分数：US 4,441 · GB 3,747 · **CN 3,084** · CA 3,045 · AU 2,519 · **ES 2,133** · **MX 1,993**。
- 全库 12,790 个成分中 413 个没有任何产品（多为重复合并后的残留/人工种子），不计入分母。

---

## 4. 复方成分集合审计

| 指标 | 数值 |
|---|---:|
| 复方产品（去重后 ≥2 个不同成分） | **48,554** |
| 不同成分集合 | **7,757** |
| 同集合出现在 ≥2 个市场 | **704（9.08%）** |
| 跨市场复方产品 | **30,699（63.2%）** |
| 含 cn-/mx-es- 成分的集合 | **268** |
| 含 CN 市场的集合 | 27 |
| 含 ES 市场的集合 | 607 |
| 含 MX 市场的集合 | 822 |
| 跨市场且涉及 CN/ES/MX 的集合 | **348** |

**Top 复用集合**（同集合跨市场）：`amoxicillin+clavulanate`（601 产品，CN/ES/MX/US）、`hydrochlorothiazide+valsartan`（482，7 市场）、`hydrochlorothiazide+irbesartan`（479，7 市场）、US/CA 防晒剂 4 成分（1,997）、`titanium-dioxide+zinc-oxide`（1,179）等。

> **为什么匹配率只有 9%**：复方在不同市场常以不同配比/组合上市（如中国 3 成分感冒药 vs 美国 4 成分；同一 ATC 组合在不同国家成分个数不同），按「成分集合完全相等」匹配天然低。模拟合并 178 条只能 +6 集合，说明瓶颈在复方本身，不在成分 id。

---

## 5. 合并候选（`data/cross_market_merge_candidates.csv`）

| status | 数量 | 说明 |
|---|---:|---|
| **mergeable** | **178** | 目标英文 substance 存在 + 证据 + 通过盐型/立体/复方检查 |
| uncertain | 227 | 弱证据/多候选/被安全复检降级 — **只记录，不自动 apply** |
| needs_target | 52 | 英文 INN 已知（WHO/CN2EN 等）但**库内没有独立英文 substance**，需先建英文成分再合并 |

**mergeable 明细（按前缀 × 类型）：**

| 前缀 | substance_merge | duplicate_merge | 小计 |
|---|---:|---:|---:|
| cn-* | 16 | 25 | **41** |
| mx-es-* | 95 | 0 | **95** |
| 非前缀西语 id（ES 专属） | 42 | 0 | **42** |
| 合计 | 153 | 25 | **178** |

**mergeable 按证据**：existing_override 148（cn_overrides 14 + es_overrides 134）、duplicate_name 25、cn2en 2、who_inn 2、mx_inn_map 1。

**样例（按产品数，全部标 mergeable）：**

| source_id | 源名 | 目标 | 证据 | 产品数 |
|---|---|---|---|---:|
| cn-2db2538bfa | 葡萄糖粉剂 | dextrose | existing_override / medium | 46 |
| cn-55bfea1cce | 氟伐他汀钠 | fluvastatin | existing_override / medium | 24 |
| cn-f1b9d21d85 | 米卡芬净钠 | micafungin | existing_override / medium | 21 |
| cn-2f1c20e347 | 苯甲酸阿格列汀 | alogliptin | cn2en / medium | 19 |
| cn-5bd9217c34 | 达肝素钠 | dalteparin | existing_override / medium | 19 |
| cn-ac79bd5204 | 聚苯乙烯磺酸钙 | polystyrene-sulfonate-calcium | existing_override / medium | 14 |
| condroitin | Condroitín | chondroitin | existing_override / low | 29 |
| amilmetacresol | Amilmetacresol | amylmetacresol | existing_override / low | 23 |
| fibrinogeno-humano | Fibrinógeno Humano | fibrinogen-human | existing_override / low | 20 |
| nimodipino | Nimodipino | nimodipine | existing_override / low | — |
| tetanos | Tétanos | tetanus | existing_override / low | — |

**needs_target 样例**（英文 INN 知道、库内无对应 substance，建议先「补英文名」再合并）：
`瑞巴派特→rebamipide`、`吲哚布芬→indobufen`、`普卢利沙星→prulifloxacin`、`西尼地平→cilnidipine`、`二硫化硒→selenium disulfide`、`呋喃西林→nitrofurazone`、`Difenidol→difenidol`、`Fimasartán→fimasartan` 等 52 条。

**uncertain 227 条构成**：atc4 131（ATC level-4 唯一命中，但 level-4 粗、可能是同类药）、mx_inn_map 58（映射证据弱/fuzzy）、existing_override 27（盐型检查不过）、cn2en 10（多候选/盐型）、其他 1。

---

## 6. 模拟应用后的 before / after

| 指标 | before | after（模拟合并 178 条） | 变化 |
|---|---:|---:|---:|
| substance 总数 | 12,790 | **12,612** | −178 |
| 有产品成分 | 12,377 | 12,199 | −178 |
| ≥2 市场成分 | 2,953 | **2,977** | +24 |
| 跨市场链接率 | **23.86%** | **23.60%** | −0.26pp（分母缩小） |
| 复方同集合跨市场集合 | **704** | **710** | **+6** |
| 复方集合匹配率 | **9.08%** | **9.18%** | +0.10pp |
| 跨市场复方产品 | 30,699 | **30,827** | +128 |
| 含 prefix 成分的复方集合 | 268 | 239 | −29 |
| 跨市场且涉及 CN/ES/MX 的集合 | 348 | **356** | +8 |

> 链接率略降是因为 178 个源成分被并入目标、分母变小；绝对「多市场成分」+24 才是真实增益。

---

## 7. apply 建议（给 Lead）

**不在本轮 apply**；建议分三批，全部走既有 merge 脚本的 dry-run 安全预检（`etl/merge_cn_substances.py` / `etl/merge_es_substances.py`，两者都有行级安全校验 + 撤销清单）：

| 批次 | 候选 | 条数 | 理由 / 风险 |
|---|---|---:|---|
| **A 可直接审** | duplicate_merge 25 + who_inn 2 + cn2en 2 + mx_inn_map 1 | **30** | 同名重复/官方名映射，证据最硬；先跑 dry-run 看行级错误 |
| **B 需抽审** | existing_override 148（cn 14 / es 134） | **148** | 原表状态是 uncertain/no_english，本轮虽过盐型检查，仍建议 **20% 人工抽核**（重点：`condroitin`/`amilmetacresol`/`fibrinogeno-humano` 这类西语拼写差异 + `米卡芬净钠→micafungin` 这类盐基） |
| **C 先补英文名** | needs_target 52 | **52** | 库内无英文 substance；先建英文成分（WHO INN 官方名），下一轮再合并。**不能直接写 DB 合并** |
| 不入 | uncertain 227 | 227 | ATC-4 太粗（131）、fuzzy 映射（58）、盐型不过（27）；宁可缺，不可错 |

**预期**：A+B 合计 178 条 → substance 12,790→12,612、复方跨市场集合 +6；若只做 A（30 条）则影响很小（约 +1~2 集合）。**复方优先**的实际收益有限，建议把资源放在 B 的抽审与 C 的补英文名。

**风险**：
1. 复方集合匹配**不看配比/规格/剂型**——合并后同名集合可能仍是「不同配比」，不能当等价；页面必须保留规格对照与警示。
2. 盐型/立体安全复检是规则式（ZH/ES 词表），可能漏掉生僻盐型（本轮降级 96 条，但仍有 `樟脑醑→camphor` 这类「剂型/溶剂名」被放行，需人工确认）。
3. ATC level-4 弱证据（131 条 uncertain）**一律不写**，避免把同类药并成一个成分。
4. `existing_override` 的 en_inn 来自历史 CSV，可能滞后于 WHO 新名；合并前应重跑 WHO INN 对照。
5. 合并会改变 `substance` 总数与 `coverage` 数字，apply 后需同步 README/About/CHANGELOG（由 Lead 在发布轮统一）。

---

## 8. 证据与复现

| 文件 | 内容 |
|---|---|
| `etl/build_cross_market_candidates.py` | 审计 + 候选生成（只读；可重跑） |
| `data/cross_market_merge_candidates.csv` | 457 行候选（列：candidate_type/source_id/source_name/source_markets/target_id/target_name/evidence_type/evidence/confidence/status/n_products/source_atc） |
| `.tmp/cross-market/audit.json` | 审计全量（成分矩阵、复方 before/after、市场分布、候选统计） |
| `.tmp/cross-market/probe.out.txt` | 初始探查（DB 现状 + 数据文件结构） |
| `.tmp/cross-market/build*.out.txt` | 4 次构建日志（含安全复检降级数） |

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/build_cross_market_candidates.py      # 只读；重跑生成 CSV + audit.json
```

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 git / 发布 / `site/build.py`。_
