# G3 盐型拆分：量化与修法方案（task-7 / phaseb-plan，只读）

- 日期：2026-11-16 ｜ **只读**：未改 `lib/`、`site/`、`tests/`、未写库、未 commit
- 结论：掉级根因 = **同一活性成分在 `substance` 表被拆成「基名行 + 盐型行」**，而 CZ/LV 新数据把盐型行的产品数放大（CZ 一侧 **25,270** 个盐型名 active 产品，GB 仅 2,848），结果卡排序的 `n_products` 平手键把盐型卡顶到 rank0。**最小修法 = 检索排序层「同名下基名卡优先」（不改库、不改输出结构）**；数据层合并成本高、会动 G2，不建议本轮做。

## 1. 机制（为什么 v0.13.0 才掉）

`lib/search.py::_cards_for_keys` 的卡片签名 = `(key_id, country, 成分 tuple, form_base, release)`，排序 `(-score, -n_products, …)`；`score` 只看名字档位/国家/规格/剂型，盐型与基名卡同分时按 `n_products` 决胜。
CZ/LV 的 INN 映射落到盐型 `substance` 行（如 `Clopidogrel Hydrogen Sulfate`），且 CZ 目录里同一品牌（`Plavix`）的新增包装远多于其他国家的基名行 → 盐型卡 `n_products` 变大，压过原来的基名卡。

| 证据 | 数 |
|---|---|
| CZ / LV active 产品落在盐型名 `substance` 行 | **25,270 / 410**（CZ 用到 440 个盐型名成分） |
| 对照：US 10,295 · GB 2,848 · ES 210 | — |
| 例：`plavix` 旧 rank0 = Clopidogrel（GB，11 条）→ 新 rank0 = Clopidogrel Hydrogen Sulfate（CZ，20 条） | — |

## 2. 全库量化（只读现查）

规则：`inn_en` 去掉尾部/头部盐·水合物·反离子词（Hydrochloride/Sulfate/Citrate/Oxalate/Besilate/Mesylate/Sodium/Calcium/Dihydrate…）后，**结果等于库里另一个 `inn_en`** 才算一对；排除离子/元素基名（Sodium/Chloride/Calcium…）。

| 指标 | 数 |
|---|---|
| `substance` 总行数 | 13,648 |
| 盐型-基名成对（规则命中 / 其中至少一方有 active 产品） | **691 / 685** |
| 涉及成分行（去重） | **1,203**（基名行 577 + 盐型行 655，29 个中间行两栖，如 `Sitagliptin Hydrochloride`） |
| 涉及 active 产品（去重）/ 按成分行累加 | **178,195 / 193,643** |
| 涉及 `product_component` 行 | 250,834 |
| 涉及 `name_key`（去重）/ 按行累加 | **50,381 / 50,725**；其中同一名字同时挂基名+盐型两行的 key = **964** |
| 成对两行 ATC 相同 | 49.6%（盐型行缺 ATC 240 个） |

## 3. 9 条掉级查询逐条（旧库 `data/backups/drugs-20261115-095816.db` vs 现库）

| 查询 | lang | 旧 rank0（产品数） | 现 rank1 = 新 rank0（产品数） | 基名行 active / 盐型行 active | 两行共享 name_key |
|---|---|---|---|---|---|
| plavix | en / es | Clopidogrel · GB（11） | **Clopidogrel Hydrogen Sulfate · CZ（20）** | 390 / 304 | 10 |
| glucophage | en | Metformin · GB（14） | **Metformin Hydrochloride · CZ（78）** | 2,913 / 2,582 | 28 |
| eucreas | es | Vildagliptin + Metformin · ES（15） | **Vildagliptin + Metformin Hydrochloride · CZ（36）** | 2,913 / 2,582 | 5 |
| zoloft | en | Sertraline · US（3） | **Sertraline Hydrochloride · CZ（102）** | 595 / 456 | 3 |
| cipralex | es | Escitalopram · GB（21） | **Escitalopram Oxalate · CZ（33）** | 364 / 844 | 9 |
| viagra | en / es | Sildenafil · GB（21） | **Sildenafil Citrate · CZ（22）** | 1,189 / 380 | 12 |
| imodium | en | Loperamide · GB（1） | **Loperamide Hydrochloride · CZ（10）** | 475 / 107 | 1 |

合计 **9 条掉级**（Top-1 338→330 = **-8**；余 1 条在别处回升，40 分钟盒内未定位，不影响结论）。其余 15 条非 Top-1 为既有 dup_inn/combo 缺口（与基线相同）。

## 4. 三种修法对比

| 方案 | 做法/落点 | 成本 | 风险 | 效果 |
|---|---|---|---|---|
| **a) 显示层合并** | `_cards_for_keys` 把同 key、同基名的卡合并成一张（成分列表含基名+盐名、产品数相加、国家合并） | M–L：卡片要跨国家合并，`Card.country` 单值语义、客户端 `app.js` 同源逻辑都要改，结果页国家标签需改版 | 中：改变「一卡=一国一产品族」的展示语义，碰撞/国家计数口径要同步 | 9 条全修好；顺带减少重复卡 |
| **b) 检索层聚合排序（推荐）** | 只改**排序键**：同名 key 下，成分全是「基名（无盐词）」的卡排在盐型卡前（`score` 后加 `is_salt` 优先位，不动 `n_products` 与输出字段）；`lib/search.py` + 客户端 `site/build.py` 内联 JS 各一处 | **S–M**：约 1 个排序函数 + 1 处镜像 + 回归测试；无 DB、无索引字段变化 | 中低：只影响「同名同时出现基名/盐型」的排序；盐型卡仍在结果里（候选集不变），需回归 354 条 | 9 条全部回到 rank0；盐型查询（如 clopidogrel bisulfate）也受益 |
| **c) 数据层合并** | 把盐型 `substance` 行并入基名行（`variant` 改挂、盐名保留在 `variant.salt`），一次性迁移 | L：写库窗口 + 68 万行校验 + 全量重建站；1,203 成分行/178,195 产品受影响 | 高：改成分身份与 ATC/大类计数、影响 G2 `base_fraction` 展示、盐型身份页消失；不可轻回滚 | 一并修 ATC 类目排序（Venlafaxine 等）；但远超 Top-1 需求 |

## 5. 推荐（最小可行）

**方案 b**，分两步落地（下一任务，不在本轮）：

1. `lib/search.py`：卡片构建时用现成 `variant.salt`/盐词表给每张卡算 `is_salt`（基名卡=false）；排序键改为 `(-score, is_salt, -n_products, len(key_id), brand)`，其余逻辑与输出字段不动。
2. 客户端镜像：`site/build.py` 内联检索 JS 同一排序键；构建后本地 `app.js` 查询 9 条回归。
3. 测试：新增 `tests/test_search_salt_base_rank.py`（9 条固定查询断言 rank0 含基名；只读库），trilingual 全量复跑。

> 不建议 c：本轮 `/data` 刚写完，再做成分合并会把 G2 盐基折算和 ATC 类目排序一起搅动；建议登记为「数据规范化（G3-data）」后续独立窗口，待 G2 稳定后再评估。

## 6. 验收口径草案

- `tests/trilingual/run_tests.py`：**Top-1 ≥ 338/354（95.5%）**、Top-5 ≥ 349/354（98.6%）、案例 72 例仍过 69（不新增失败）；9 条盐型查询 rank0 卡含期望基名。
- `lib` 单测全绿（当前 61 项）+ 新增盐型排序回归测试；`deploy/ci_checks.py --fast` 不红。
- 身份声明：结果卡/成分页仍显示盐型名；**不出现「可互换/interchangeable」措辞**（`grep` dist 检查），`collision` 视图与 `dose_warning` 不变。
- 计数口径：`substance=13,648`、`product=594,781`、`name_key` 不变（本方案零 DB 写入）；构建产物大小变化 < 0.1%。
- 性能：单查询 p95 相对基线 ≤ +5%（盐词表在 `SearchIndex` 装载时预计算一次，查询期只查表）。
- 回滚：单 commit revert，无数据迁移。

## 7. 复现

```powershell
& $py .tmp\g3\distinct.py      # 全库成对 distinct 统计
& $py .tmp\g3\queries_fast.py  # 9 条掉级查询旧/新库 rank0 对比
& $py .tmp\g3\probe.py         # 卡片国籍/国家分布 + 泛用名回升排查
```

证据 JSON：`.tmp/g3/g3_stats.json`、`.tmp/g3/g3_queries.json`、`.tmp/g3/g3_probe.json`。旧库基线：`data/backups/drugs-20261115-095816.db`（507,434 产品 / 13 市场）。
