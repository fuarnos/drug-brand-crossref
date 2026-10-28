# 伪复方审计与修复（task-137）

> 日期：2026-10-29 ｜ 只读真实库 + DB 副本验证 ｜ **未写真实库、未改 build.py、未 git/发布**
> 依据：`reports/search-intuition-audit.md` §2.3（1,489 条「同一活性成分碱基+盐型被当多成分」）
> 产物：`etl/fix_pseudo_combos.py`、`data/pseudo_combo_issues.csv`、本报告、`.tmp/pseudo-combo/`

---

## 0. 结论

| 项 | 结果 |
|---|---|
| **key 级伪复方**（build `vs` 联合出现 base+salt） | **545 个 name_key**（vs 长度：2 个 538、3 个 6、4 个 1），涉及 **8,798 个产品**；按市场：US 2,404 / GB 2,383 / ES 1,430 / AU 1,286 / CA 597 / SG 279 / MX 185 / TW 172 / CN 49 |
| 假 combo 页 | **545 个**（`combo/base+base-salt.html` 及同名 key 的 combo 入口）；这 545 个 key 的 collision 级别：**severe 477 / warning 1 / info 67** |
| **产品级重复成分**（同一产品内 base+salt 两行） | **214 个产品 / 285 条重复 component 行**（可安全自动修复：保留 base 成分、删除 salt 重复行、重排 ord） |
| 与审计 1,489 的关系 | 审计用「substance 英文名首词相同」启发式（本库同口径 **1,548** key）；其中大量是**真正的不同活性成分**（如 Sodium Chloride vs Sodium Lactate、不同胰岛素类型）——不能按首词盲并。**严格 base+salt 关系 = 545 key**，是本任务可安全归并的核心集 |
| 修复建议 | **首选 build 层**：按 base substance 归并 `vs/x/cu/l`（combo/collision 只在不同 base 时生成）——零数据风险、立即消除 545 个假 combo/假 severe；**数据层级**：214 产品重复成分可用本脚本副本修复（已验证），跨产品 salt substance 合并留待数据任务 |
| 副本验证 | 214 产品 apply：components 534,246→**533,961**（−285）、products 不变、quick/FK 0；第二次 apply **0 产品**（幂等）；rollback **214 产品恢复、component 内容 hash 与基线完全一致**（delta 0） |

---

## 1. 识别规则（严格 base+salt）

1. 对每个 substance 的 `inn_en` 做规范化（小写、括号/连字符→空格）。
2. 若存在两个 substance：短名 `B`，长名 = `B` + 全部 salt/hydrate/ester 词（`hydrochloride/sodium/calcium/phosphate/trihydrate/mesilate/…`），则长名是 `B` 的盐/水合物/酯变体；**短名本身必须是独立 substance 名**，且短名不能是元素/无机离子词（排除 sodium/calcium/chloride 等误配）。
3. **key 级**：同一 `name_key` 下所有产品的 component substance 并集，若全部满足「B 或 B+salt」→ 该 key 是伪复方（build `vs` 会显示 `A + A salt`）。
4. **产品级**：同一 product 内同时存在 B 与 B+salt 的 component → 重复成分（不是复方）。
5. 仅按严格规则自动修复；首词相同但后缀不是标准 salt 词的（如不同胰岛素、不同无机盐）**不并入**，留审计清单人工/build 复核。

样例（key 级）：
- `lisinopril` → Lisinopril + Lisinopril Dihydrate（524 产品）
- `amoxicillin` → Amoxicillin + Amoxicillin Trihydrate
- `lipitor` → Atorvastatin + Atorvastatin Calcium
- `sitagliptin` → Sitagliptin + Sitagliptin Phosphate Monohydrate
- `zithromax` / `azithromycin` → Azithromycin + Azithromycin Dihydrate
- `singulair` → Montelukast + Montelukast Sodium

---

## 2. 统计

### 2.1 key 级（假 combo / 假 collision 的来源）

| 项 | 值 |
|---|---:|
| 伪复方 key | **545** |
| 涉及产品 | **8,798** |
| vs=2 / 3 / 4 | 538 / 6 / 1 |
| collision severe / warning / info | **477 / 1 / 67** |
| 假 combo 页（按 key） | **545** |

市场分布（涉及产品，合计含缺市场 13）：US 2,404 / GB 2,383 / ES 1,430 / AU 1,286 / CA 597 / SG 279 / MX 185 / TW 172 / CN 49。

### 2.2 产品级（同产品重复成分）

| 项 | 值 |
|---|---:|
| 可自动修复产品 | **214** |
| 删除重复 component 行 | **285** |
| 涉及市场 | 以 AU/CA/SG/TW 的 TPN/多电解质/复方营养产品为主（多族 base+salt，如 sodium acetate + sodium acetate trihydrate、calcium chloride + calcium chloride dihydrate） |
| 保留规则 | 保留 **base substance 成分**；删除 salt/hydrate/ester 重复行；剩余 ord 重排 |
| 安全性 | 仅删除「base 成分存在」的 salt 重复行；没有 base 成分的盐（如单独 Calcium Chloride）不删；强度是否一致**未自动校验**（窗口前建议抽查 214 产品样例，报告见 §5 风险） |

### 2.3 与审计 1,489 的差异（重要）

- 审计口径 **1,489**（本次同口径 1,548）是「vs≥2 且英文名首词相同」——会包含：
  - 真不同活性成分：Sodium Chloride vs Sodium Lactate、Sodium Bicarbonate vs Sodium Acetate、不同胰岛素等；
  - 同 base 不同盐但无 base 成分的真实复方（如两种盐都是有效成分的一部分）。
- 本任务严格 base+salt **545** 是可直接按 base 归并的安全集；建议 build 归并逻辑用「salt 词表 + base 存在」严格规则（或复用本脚本的映射表），不要按首词盲并。
- 对 1,489 中剩余的 1,000+ 首词相同 key：build/数据任务逐类核对（胰岛素、无机盐、肝素类等），避免二次误并。

---

## 3. 修复方案

### 方案 A（推荐，先做）：build 层按 base 归并
- 索引 `vs`：对同一 base 的 salt substance 只保留 base 的 substance_id；`x` 显示只留 base 名（不再 `A + A salt`）。
- combo 页：只有 **不同 base** 才生成 combo 页；545 个假 combo 页不再生成。
- collision：`n_substances` 按 base 去重，伪复方 key 不再 severe。
- 需要 build 侧使用 `data/pseudo_combo_issues.csv` 的 key/base 映射（或脚本输出的 salt→base 映射）；不需要写 DB。
- **优点**：零数据风险、立即修复用户直觉；**缺点**：只是索引/展示层归并，DB/vs 原始数据仍两份。

### 方案 B（数据层，副本已验证 214 产品）
- `etl/fix_pseudo_combos.py --apply --db <副本>`：同一产品内保留 base、删除 salt 重复 component（285 行）；写撤销清单；`--rollback` 精确恢复。
- 对 **key 级跨产品**问题：需要把 salt substance 合并进 base（variant 重挂/去重），属更大的 substance 合并任务（参考 `etl/auto_merge_substances.py` 模式）；本任务不做，建议 build 方案先行。
- 窗口步骤：产品级修复可并入 task-133 统一 DB 窗口（建议 CN 清洗后、单位归一化前/后均可；本报告建议在 **单位归一化前** 执行，避免 ord/删除后再归一化重复扫描）。
- 回滚：`--rollback --manifest .tmp/pseudo-combo/fix_manifest.json`；整库回滚用窗口备份。

---

## 4. 副本验证

```powershell
$py = '...python.exe'
Copy-Item data\drugs.db .tmp\pseudo-combo\drugs.db
& $py etl\fix_pseudo_combos.py --dry-run                          # CSV/统计
& $py etl\fix_pseudo_combos.py --db .tmp\pseudo-combo\drugs.db --apply --manifest .tmp\pseudo-combo\fix_manifest.json
& $py etl\fix_pseudo_combos.py --db .tmp\pseudo-combo\drugs.db --apply --manifest ...  # 幂等：0 产品
& $py etl\fix_pseudo_combos.py --db .tmp\pseudo-combo\drugs.db --rollback --manifest ...
```

| 步骤 | 结果 |
|---|---|
| dry-run | key 545 / 产品 8,798；产品级 214 / 删除 285 行；CSV **9,012 行** |
| apply | 214 产品、删除 285 行；components 534,246→**533,961**；products 431,555 不变；quick ok / FK 0 |
| apply#2（幂等） | **0 产品 / 0 行** |
| rollback | 214 产品恢复；components 回到 534,246；**内容 hash 与基线一致**、delta 0；quick/FK ok |

---

## 5. 风险 / 注意

| # | 风险 | 说明/缓解 |
|---|---|---|
| 1 | 产品级自动删除可能丢失 salt 成分的独立强度/来源信息 | 仅删除「base 成分存在」的重复行；窗口前抽查 214 产品（尤其 TPN/多电解质）；若强度不一致，改为 build 层归并、不删数据 |
| 2 | key 级跨产品问题不能靠删单产品成分解决 | 本任务未跨产品改数据；推荐 build 层按 base 归并（方案 A），或另开 substance 合并任务（方案 B 长期） |
| 3 | 严格 salt 词表可能漏掉罕见盐/酯名称 | CSV 保留首词审计集，后续按 `variant.salt/salt_code` 扩充词表；不盲并 |
| 4 | `povidone iodine` vs `Povidone-Iodine` 等连字符差异被归并 | 属同一成分写法差异，归并合理；build 层仍需保留原始显示名 |
| 5 | 545 个假 combo 页影响 SEO/导航 | 方案 A 后消失；发布前重建索引/站点 |
| 6 | 与 task-133 窗口顺序 | 产品级修复建议在 CN 清洗后、单位归一化前；key 级修复留给 build（task-136/下一版） |

---

## 6. 证据

| 文件 | 内容 |
|---|---|
| `data/pseudo_combo_issues.csv` | 545 key + 8,798 产品 + 214 产品级行（9,012 行） |
| `.tmp/pseudo-combo/dryrun_final2.out.txt` | 计数/市场/样例 |
| `.tmp/pseudo-combo/dryrun.json` | key 级 vs 列表 + 产品级 families/删除清单 |
| `.tmp/pseudo-combo/apply_final.out.txt` / `rollback_final.out.txt` | 副本 apply / rollback |
| `.tmp/pseudo-combo/fix_manifest_final.json` | 撤销清单（214 产品 old 成分行） |
| `.tmp/pseudo-combo/verify.py` | components/products/hash/quick/FK 对比 |
| `.tmp/pseudo-combo/collision.out.txt` | 545 key collision 级别（severe 477 等） |
| `reports/search-intuition-audit.md` | 上游审计（1,489 key 口径） |

_本报告由并行子智能体 data-depth 生成；未写真实库、未改 build.py、未 git/发布。_
