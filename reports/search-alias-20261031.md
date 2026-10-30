# task-141b 检索层接入同物异名（`lib/search.py` → `match_source="inn_alias"`）

> 执行：2026-10-31（task-2 / 检索工位）。**未改 `data/drugs.db`**（只跑 SELECT，库文件 mtime 仍是 2026-10-29 14:38:12）、
> **未改 `site/` / `db/` / `docs/`**、**未 commit / 未发布**。前置：[`reports/task141-alias-mapping-20261031.md`](task141-alias-mapping-20261031.md)（异名表 + 加载器）。

## 0. 结论

- 搜 `dextrose` 现在能看到 `Glucose`（CN 葡萄糖注射液 / GB Glucose）；搜 `葡萄糖` 能看到 `Dextrose`（US / TW / US）——
  双向都通，卡片标 `tier="inn_alias"` + `match_source="inn_alias"`，与俗称（`nickname` / `drug_term`）区分开。
- 异名命中是**追加候选**：分数 **0.709**（`TIER["inn_alias"]=0.88`），严格夹在精确名命中 **0.775**（exact）与纯前缀噪声 **0.665**（prefix）之间；
  主结果之间的相对顺序不变，主结果占满 `limit` 时只从**尾部**让位，**绝不挤掉** exact/compact/nickname/atc/category 卡。
- 关系只来自 `data/substance_aliases.csv`（24 行 / `lib/aliases.py` 的并查集），**没有另写归一化、没有写库、没有合并产品**。
- 验收：`lib` unittest **59 OK**（41 → 59，新增 `lib/test_search_alias.py` 18 项）；三语 **72 例 69 通过**（基线 68 通过；ciclosporin 由 CSV 行修好，**无新增失败**）；`cli.py "dextrose"` / `cli.py "葡萄糖"` 前 8 行互见（§4.3）。
- 代价（诚实写）：三语 **Top-1 96.3% → 95.5%**（354 条里少命中 3 条中文通用名查询，见 §6.2），Top-5 97.7% → **98.6%**；单查询平均多 **~17 ms**。

## 1. 接入点

只动 `lib/search.py` 一个文件（+ 一个新增测试文件），站点客户端（`site/build.py` / `assets/app.js`）**本轮未接**——那是 task-141 里列的后续批次（构建 ~20 分钟，单独为本表构建不划算）。

| 位置 | 改动 |
|---|---|
| `SearchIndex.__init__` | 新增 `alias_path` 参数 + `self.alias = load_aliases(alias_path)`；默认读 `data/substance_aliases.csv`，文件缺失 → 空表 → 异名层自动关闭 |
| `TIER` / 常量 | `TIER["inn_alias"]=0.88`；`ALIAS_MAX_CARDS=3`；`PRECISE_TIERS={exact, compact, nickname, atc, category}` |
| `Card` | 新增 `match_source` 字段（`""` = 名字本身命中 / `"inn_alias"` = 异名追加） |
| `SearchResult` | 复用既有 `match_source` / `match_detail`：结果**全是**异名带来时 `match_source="inn_alias"`；混合时看每张卡；`match_detail["inn_alias"]` 记 seeds / group / targets / shown / source |
| `_substance_cards(...)` | 加 `tier` 参数（默认 `"nickname"`，异名层传 `"inn_alias"`），俗称路径行为不变 |
| `_substances_for_keys(...)` | 新：名字（`name_key`）→ **单成分产品**的成分，异名扩展的种子 |
| `_alias_expand(...)` | 新：种子 → `AliasMap.group()` 同组写法 → 同组单成分卡片（轮转取前 3 张） |
| `_substances_of_products(...)` | 新：主结果卡片已覆盖的成分（避免重复追加） |
| `_merge_alias_cards(...)` | 新：按分数位插入 + 尾部让位保底 |
| `_alias_note(...)` | 新：说明文案（只讲「同一成分的不同写法」，明写「不代表剂型/规格可互换」） |
| `search()` | 名字检索出卡后追加异名层；异名卡没挤进前 `limit` 时不写说明、不改行为 |

流程（`search()` 名字分支）：

```
normalize → _resolve_keys → _cards_for_keys（主结果，原样）
        → _alias_expand（种子 → 同组写法 → 单成分卡，标 inn_alias）
        → _merge_alias_cards（按分数位插入，主结果相对顺序不变）
        → res.cards / res.note / res.match_detail["inn_alias"]
```

## 2. 打分策略

沿用既有 `score = 0.55*name_tier + 0.20*country + 0.15*strength + 0.10*form(+0.01*release)`，
只加一档 `name_tier = 0.88`：

| tier | name_tier | 无国家/剂量线索时的得分 | 位置 |
|---|---|---|---|
| `exact` | 1.00 | **0.775** | 名字精确命中 |
| `compact` | 0.95 | 0.740 | 去空格/标点后相同 |
| **`inn_alias`** | **0.88** | **0.709** | **同组成分的其他写法（新增）** |
| `category` / `atc` | 0.88 / 0.92 | 0.709 / 0.731 | 大类 / ATC |
| `prefix` | 0.80 | **0.665** | 纯前缀（「葡萄糖酸钙」对「葡萄糖」= 噪声） |

- 国家过滤命中时 `country` 项 = 1.0 → 异名卡 0.809（仍低于同条件下的 exact 0.875）。
- 排序键：`(-score, is_inn_alias, -n_products, len(key_id), brand)`——**新增的只有「同分时主结果优先」一条平局判定**，
  主结果彼此之间的顺序与改造前逐条一致（有测试盯着：`test_main_result_order_unchanged`）。
- 上限 3 张 + 轮转取卡：同组里产品数多的写法（CN 葡萄糖 7,340 个产品）不会把同组其他写法（US DEXTROSE 1,080 个）挤掉。
- 保底：主结果把 `limit` 占满时，从**尾部**让位至多 3 个（只砍尾、不重排），且 exact/compact/nickname/atc/category 一张都不动。

## 3. 防误召规则（为什么第一版会串味）

第一版用「名字命中的全部成分」当种子，立刻出问题：`葡萄糖` 的某些输液产品里挂着 `water-for-injection`，
于是「Agua Estéril Para Preparaciones Inyectables」被当成异名排到第 1 位。收紧成四条：

1. **种子只认单成分产品**：复方/输液的辅料（灭菌注射用水、氯化钠）不当种子——只有单成分产品才能说「这个名字指的就是这个成分」；
2. **种子只扩异名表里有的成分**（`group` 大于自身），其余成分原样放过；
3. **卡片只收单成分条目**：`dextrose` 的同组 `anhydrous-dextrose` 在库里只有复方（PRISMASOL 等），不追加——「同组成分的条目」不是「配方里顺带有它」；
4. **与主结果去重**：按「国家 × 组成 × 剂型」+ 主结果卡的 `product_id` 反查成分，两边都挡一次，避免同一批 CN 葡萄糖条目出现两遍。

另：种子查询**不按国家过滤**，这样 `search("dextrose", country="CN")` 主结果被国家过滤清空时，仍能靠异名线索带出 CN 的葡萄糖（此时 `match_source="inn_alias"`，`test_country_filter_can_be_fully_alias`）。

## 4. 验收

### 4.1 `lib` 单元测试（全 OK）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m unittest discover -s lib -t lib
# Ran 59 tests in 5.244s
# OK
```

- 基线 41 项 → 59 项（新增 `lib/test_search_alias.py` 18 项：14 项夹具 + 4 项真库只读回归）。
- 既有 `lib/test_search.py`、`lib/test_search_short_cjk.py`、`lib/test_aliases.py` **一行断言未改**，全绿。
- `& $py -m py_compile lib/search.py lib/test_search_alias.py` → 0。

### 4.2 三语检索一致性（无新增失败）

```powershell
& $py tests/trilingual/run_tests.py
```

| | 案例 | 通过 | Top-5 | Top-1 | 跨国 | 用时 |
|---|---|---|---|---|---|---|
| 基线（改造前，本次实测） | 72 | **68** | 346/354 = 97.7% | 341/354 = 96.3% | 72/72 | 620.0s |
| 改造后 | 72 | **69** | 349/354 = 98.6% | 338/354 = 95.5% | 72/72 | 622.1s |

- 案例级：`ciclosporin/dup_inn` **False → True**（en `cyclosporine`、es `ciclosporina` 由异名扩到 Ciclosporin），其它案例状态不变，**没有新增失败**。
- 剩余 3 例失败 ⊆ 基线 4 例 allowlist：`metformin/combo`、`beclometasone/dup_inn`、`chlorphenamine/dup_inn`
  （后两者的另一写法 `beclomethasone`、`chlorphenamine↔chlorpheniramine` 里 beclometasone 这组**不在** CSV，故未修好）。
- 复跑一次（最终代码状态，期间另有工位在建站，机器较忙）：**72 例 69 通过 / Top-5 98.6% / Top-1 95.5% / 跨国 72/72，655.1s**
  ——数字与上表完全一致，判定稳定（明细 `.tmp/trilingual/results_final_alias.json`）。
- 基线 vs 改造逐条对比脚本：`.tmp/cmp_trilingual.py`（读 `.tmp/trilingual/results_baseline_alias.json` 与 `results_after_alias.json`）。

### 4.3 两条 CLI 查询互见（前 8 行）

```powershell
& $py cli.py "dextrose"    # 第 5、6 张卡是 Glucose [CN] / [GB]，tier=inn_alias
& $py cli.py "葡萄糖"       # 前 3 张卡是 Dextrose [US] / [TW] / [US]，tier=inn_alias
```

```
query = 'dextrose'  ->  norm = 'dextrose'  strengths=[]  keys=60
note  = 异名命中：Anhydrous Dextrose / Dextrose / Glucose 是同一成分的不同写法（data/substance_aliases.csv），已按「Dextrose」追加 3 条同组候选；只做身份对应，不代表剂型/规格可互换。
 1. DEXTROSE  [US]  Dextrose  50 mg / … / 100000 mg/1000 mL  liquid  ×57  score=0.775 (exact) !! 严重碰撞
 2. DEXTROSE  [US]  Dextrose  2500 mg/50 mL / 5000 mg/100 mL  injection  ×13  score=0.775 (exact) !! 严重碰撞
 3. DEXTROSE  [US]  Dextrose, Unspecified Form  5000 mg/100 mL / 10000 mg/100 mL  liquid  ×2  score=0.775 (exact) !! 严重碰撞
 4. DEXTROSE  [CA]  Dextrose  50 %  liquid  ×1  score=0.775 (exact) !! 严重碰撞
 5. Glucose  [CN]  Glucose  20 mL / … / 100000 mg/500 mL  injection  ×6481  score=0.709 (inn_alias)
 6. Glucose  [GB]  Glucose  50 mL / 100 mL / 150 mL / 250 mL / 500 mL  injection  ×86  score=0.709 (inn_alias)
```

```
query = '葡萄糖'  ->  norm = '葡萄糖'  strengths=[]  keys=60
note  = 异名命中：Anhydrous Dextrose / Dextrose / Glucose 是同一成分的不同写法（data/substance_aliases.csv），已按「Dextrose、Glucose」追加 3 条同组候选；只做身份对应，不代表剂型/规格可互换。
 1. Dextrose  [US]  Dextrose  50 mg / … / 100000 mg/1000 mL  liquid  ×62  score=0.709 (inn_alias)
 2. 20% DEXTROSE INJECTION "ASTAR"  [TW]  Dextrose  5 % / 10 % / 20 % / 50 mg / 500 mg  injection  ×34  score=0.709 (inn_alias)
 3. DEXTROSE  [US]  Dextrose  2500 mg/50 mL / 5000 mg/100 mL  injection  ×13  score=0.709 (inn_alias)
 4. 葡萄糖注射液  [CN]  Glucose  20 mL / … / 100000 mg/500 mL  injection  ×4311  score=0.665 (prefix) !! 严重碰撞
 5. 葡萄糖氯化钠注射液  [CN]  Glucose  50 mL / … / 50000 mg/500 mL  injection  ×2123  score=0.665 (prefix)
 6. 葡萄糖酸钙片  [CN]  Calcium Gluconate  100 mg / 500 mg / 1000 mg  tablet  ×189  score=0.665 (prefix)
```

> 报告里把超长的规格列表用 `…` 截断了；原样输出在 `.tmp/cli-dextrose.txt` / `.tmp/cli-glucose.txt`（各 12 行，exit 0）。

### 4.4 其它只读抽查

- `search("dextrose", country="CN")` → 2 张卡全是 `inn_alias`（Glucose [CN]），`match_source="inn_alias"`，不再给「没有收录」的提示。
- `search("葡萄糖", country="US")` → 同理，全部是 Dextrose [US]。
- 不在表里的药不受影响：`lipitor` / `泰诺` / `布洛芬` / `C07AB02`（atc）/ `降压药`（category）→ 无 `inn_alias` 卡、`match_detail` 为空、`match_source` 与改造前一致。
- 俗称路径不变：夹具测试 `右旋糖`（nickname）仍是 `tier="nickname"`、`origin="nickname"`、不产出 `inn_alias` 卡；
  真库 `扑尔敏`（nickname → 氯苯那敏）结果与说明文案也与改造前一致（俗称分支不接异名，属后续）。
- 性能：20 条代表性查询 766 ms/查询（关异名）→ 783 ms/查询（开异名），**+2%（约 17 ms/条）**，主要花在多一次「名字 → 单成分成分」的 SQL。

## 5. 改动文件

| 文件 | 性质 |
|---|---|
| `lib/search.py` | 只改本层：新增异名层 + `Card.match_source` + `_substance_cards(tier=...)`（既有调用不传，行为不变） |
| `lib/test_search_alias.py` | **新增** 18 项测试（夹具 14 + 真库只读 4） |
| `reports/search-alias-20261031.md` | 本报告 |

没碰：`data/drugs.db`（mtime 未变、无 journal/WAL）、`data/substance_aliases.csv`、`site/`、`db/`、`docs/`、`deploy/`。
（`site/build.py` 在 `git status` 里是 M，那是**别的工位**在改，与本任务无关。）

## 6. 风险

### 6.1 误召（false positive）

- 现规则下**只有单成分产品**能当种子，所以「复方里含某成分」的名字（如中文「泰诺」四成分复方）不会触发异名扩展；
  代价是 `扑尔敏`（俗称→成分）这类**俗称路径**也拿不到异名追加（俗称分支不改，属后续）。
- `Anhydrous Dextrose` 这类「水合物写法」在库里只出现在复方，异名层本次不追加；若将来要「配方里含它也算」，需要另开一层并单独评估噪声。
- 极端情况：CSV 将来加的 `lang_variant`（西语写法）会让西语条目以异名身份进入中文查询结果——这是产品想要的（跨国定位），但会挤占 3 个上限名额。

### 6.2 排序抖动（Top-1 掉了 3 条）

三语 Top-1 96.3% → 95.5%，恰好是三条**中文通用名 + dup_inn 结构**的查询——主结果只有 `prefix`/`contains` 档，
异名卡按 0.709 排到了前面：

| 查询 | 期望成分 | 现在 Top-1 | 排名 |
|---|---|---|---|
| `沙丁胺醇` | Salbutamol | Salbutamol（异名卡，同成分另一条 substance 记录） | 0 → 3 |
| `环孢素` | Ciclosporin | Cyclosporine（异名卡） | 0 → 3 |
| `氯苯那敏` | Chlorphenamine | Chlorpheniramine（异名卡） | 0 → 3 |

- 语义上不算错（异名卡就是「同一成分的另一条记录」），但三语评测按 substance_id 判分，所以记为 Top-1 未命中；
  案例级判定（每语言至少一条查询命中）不受影响，反而 +1（ciclosporin）。
- 这是「异名分数必须高于 prefix 噪声」这条规则的直接后果，符合本任务要求；若产品上更希望「中文名条目先出」，
  把 `TIER["inn_alias"]` 降到 0.80 以下即可（代价：`葡萄糖` 的 Dextrose 会被 4311 个中文前缀卡挤出前 10，异名就白做了）。
- 主结果**内部**顺序没有变（`test_main_result_order_unchanged`）；变的只是异名卡插在 prefix 之前。

### 6.3 数据缺口（不在本工位写权限内）

异名表只有 24 行，库里同族 substance 还有一批没进表，`葡萄糖/dextrose` 这一族就有：

| substance_id | 产品数 | 是否在 CSV |
|---|---|---|
| `glucose` | 7,340 | ✅ |
| `dextrose` | 1,080 | ✅ |
| `glucose-monohydrate` | 268 | ❌ |
| `dextrose-unspecified-form` | 38 | ❌ |
| `dextrose-anhydrous` | 36 | ❌ |
| `glucose-anhydrous` | 9 | ❌ |
| `anhydrous-dextrose` | 7 | ✅ |
| `condensed-glucose` | 6 | ❌ |

结论：现在 `dextrose` ↔ `glucose` 双向通了，但 `Dextrose, Unspecified Form`、`Glucose Monohydrate` 这类变体仍不算「同组」。
补表属数据层（task-141 那条线）的活，需要逐条写出处；本工位按任务要求**不改 CSV**。

### 6.4 其它

- 站点侧未接：`site/build.py` + `assets/app.js` 仍是老逻辑，CLI / 三语测试新行为**先于**站点。要让线上看到，需并入下一次构建（task-141 §3）。
- ATC / 大类路径（`atc` / `category`）不参与异名扩展——它们返回的是成分集合，语义不同，另议。
- `deploy/ci_checks.py` 的 trilingual 门槛仍按 `≥68 通过 + 失败 ⊆ allowlist`，本次 69 通过，不受影响；本次没跑全量 CI（另有工位在建站）。
- `tests.test_lib_atc_category` 有一条**既有**且与本任务无关的失败：`test_snapshot_sync_with_dist`（`lib/categories.py` 快照 `降壓藥` vs `site/dist/data/categories.json` `降血壓藥`，即构建产物过期），不在本任务四项门槛内，未处理。

## 7. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m unittest lib.test_search_alias -v          # 18 OK
& $py -m unittest discover -s lib -t lib            # 59 OK
& $py tests/trilingual/run_tests.py --json .tmp/trilingual/results_after_alias.json   # 72 例 69 通过
& $py cli.py "dextrose"                             # 第 5–7 张卡 inn_alias（Glucose）
& $py cli.py "葡萄糖"                                # 第 1–3 张卡 inn_alias（Dextrose）
```

## 8. 边界声明

- 异名只说明「是同一成分的不同写法」，**不合并产品、不改 substance 主键、不判断疗效等价、不做剂量换算**；
  说明文案里明写「只做身份对应，不代表剂型/规格可互换」。
- 查询永远返回候选集（异名卡是追加候选，不是「唯一答案」）。
