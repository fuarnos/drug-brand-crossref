# lib/search 补 ATC / 大类检索（task-139，lead 消息里称 task-141）

> 日期：2026-10-28 · 任务：task-139（任务板 id；lead 消息写 task-141，同一需求）· 状态：**实现 + 单测 + CI 接入完成**
> 只改 `lib/`、`tests/`、`reports/`、`.tmp/`；**未改 `site/build.py`、未写 `data/drugs.db`、未跑 git/发布**。
> 依据：task-124 审计（客户端 v0.6.4 ATC 码搜索 / v0.7.1 大类搜索已上线，lib/CLI/CI 缺失 → 评测失真）。
> 交付：`lib/categories.py`（新）、`lib/search.py`（ATC/大类分支 + 卡片构建重构）、`tests/test_lib_atc_category.py`（14 项）、`tests/gen_categories.py`、`tests/search_eval/gen_atc_category_cases.py`、`tests/trilingual/cases_v4.json`（548 例）、`tests/search_eval/run_ci.py`（默认优先 v4）、本报告
> 证据：`.tmp/lib-cat-search/{ci_v4.json, bench.json, eval-db-snapshot.db}`

---

## 0. 结论摘要

| 指标 | 结果 |
|---|---|
| **ATC 查询** | `C07` / `C07AB02`（大小写均可）→ 按 `substance.atc` 前缀匹配；`match_source="atc"`；ATC 用例 **13/13 Top-5 = 100%** |
| **大类查询** | 16 大类 × 四语 label/alias（en/es/zh/zh-Hant）+ **口语别名**（退烧药/消炎药/他汀…）→ ATC 前缀结果；`match_source="category"`；大类用例 **21/24 = 87.5%** |
| 匹配来源 | `SearchResult.match_source`（""/atc/category）+ `match_detail`（atc 码 / 大类 id、labels、prefixes、matched、source=label/alias/colloquial） |
| 与客户端一致 | ATC 识别正则、前缀语义、排序（按该名字 active 产品数降序）、大类 `catNorm` 整串等值匹配均复刻客户端；**客户端行为不变** |
| 评测集 | `cases_v4.json`：**548 例**（v3 511 + 新增 ATC 13 / 大类 24），37 例全部为 must_hit（期望来自 DB 结构） |
| **CI 门槛** | ✅ 通过：must_hit Top-5 **414/428 = 96.7%**（≥95%）；零结果 **40/40、误命中 0**；综合 **454/468 = 97.0%**；退出码 0 |
| 原有 391 例 | Top-5 380/391 = **97.2% 不降**（ATC/大类是新增用例，未改旧期望） |
| 单测 | 新增 `tests/test_lib_atc_category.py` 14 项全过；lib 既有 29 项 / pinyin 11 项回归通过 |
| 冷启动/性能 | SearchIndex 初始化 284 ms（不变）；ATC/大类索引**首次查询懒构建 ~10.0 s/进程**；热查询 ATC p50 697 ms、大类 p50 1,579 ms（见 §3） |
| CI 耗时 | 548 例 **366.4 s**（6 进程；v3 511 例时 345 s，新增用例+索引构建约 +21 s / +6%） |

---

## 1. 实现

### 1.1 `lib/categories.py`（新）

| 行 | 内容 |
|---|---|
| L21 | `CATEGORY_SNAPSHOT`：16 大类（id/url/prefixes/**四语 labels**/aliases），快照自 `site/dist/data/categories.json`（客户端同源）；生成器 `tests/gen_categories.py`，单测校验同步 |
| L121 | `COLLOQUIAL_ALIASES`：约 60 条口语 → 大类 id（退烧药/退熱藥/消炎药/胃药/降压药/降糖药/减肥药/感冒药/抗过敏药/抗凝药/他汀/抗抑郁药/哮喘药/激素/抗病毒药/皮肤药 + 英文 colloquial）——**lib 扩展**（客户端目前只认官方 label/alias；task-124 实测客户端「退烧药」0 结果） |
| L159 | `atc_query(raw)`：与客户端 `atcQuery()` **逐字一致**的正则 `^[A-Z]\d{2}(?:[A-Z]{0,2}\d{0,2})?$`，strip+upper，非法返回空 |
| L165 | `cat_norm(s)`：复刻客户端 `_catNorm`（NFKD 去组合重音 + 去空白 + lowercase） |
| L179 | `match_category(query)`：先官方 label（按大类顺序）→ 官方 alias → 口语别名；返回 `{cat, matched, source(label/alias/colloquial), lang}`；长度 <2 不匹配、整串相等（与客户端一致，不做子串） |

### 1.2 `lib/search.py`

| 行 | 改动 |
|---|---|
| L35 | import `atc_query / category_by_id / cat_norm / match_category` |
| L94–L105 | `SearchResult` 新增 `match_source: str`、`match_detail: dict` |
| L505 | `_cards_for_keys()`：把原 `search()` 内「key_ids → 结果卡」逻辑抽出为共用方法（rows/comp/collision/raw_names/cards/score/sort/country 过滤），**普通名字检索改为调用它，行为不变**（CI/评测证明） |
| L598 | `_get_atc_index()`：懒构建 `atc 码 → {key_id}` + `key_id → active 产品数`；只在首次 ATC/大类查询触发，不影响 SearchIndex 冷启动 |
| L628 | `_keys_by_atc_prefixes()`：按 ATC 前缀（客户端口径 startswith）取 key，按产品数降序、上限 200；默认 active 走懒索引，非 active 回退 SQL（L648） |
| L668 / L689 | `_search_atc()` / `_search_category()`：构造结果卡、设置 `match_source` / `match_detail` / 说明 note |
| L734–L739 | `search()` 开头：与客户端一致，**先判 ATC 码，再判大类词**（不进入名字/别名/模糊匹配）；其余逻辑不变 |

`TIER` 增加 `atc=0.92`、`category=0.88`（仅用于这些结果卡排序；不是名字匹配层）。

### 1.3 与客户端行为对照

| 项 | 客户端（app.js） | lib（本次） |
|---|---|---|
| ATC 识别 | `atcQuery()` 正则 + strip/upper | 同（`categories.atc_query`） |
| ATC 结果 | 遍历索引条目 `e.atc` 任一 `startswith(code)`；按 `e.n` 降序；显示 200 行内 | DB 聚合同一 `substance.atc startswith` 语义；key 按 active 产品数降序；返回 `limit` 卡（默认 25） |
| ATC 匹配来源 | 解析条 `parse.match.atc` / ATC 卡 | `match_source="atc"`, `match_detail.atc` |
| 大类识别 | `catHit()`：`_catNorm` 整串匹配 16 大类 labels/aliases（四语） | 同（含官方 label/alias），**额外**口语别名（source=colloquial） |
| 大类结果 | 条目 `e.atc` 任一 `startswith(prefixes)`；按 `e.n` 降序；显示 200 行内 | DB 同语义，`match_source="category"`，`match_detail` 含 category_id/url/labels/prefixes/matched/source |
| 优先级 | ATC 先于大类先于名字检索 | 同（L734–L739） |
| 普通名字/拼音/别名 | 不变 | 不变（分支只在命中 ATC/大类时生效；单测 + CI 旧 391 例不降） |

---

## 2. 测试与评测

### 2.1 单测（`tests/test_lib_atc_category.py`，14 项）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m unittest tests.test_lib_atc_category -v    # 14 passed
& $py -m unittest discover -s lib -t lib           # 既有 29 passed
& $py -m unittest tests.test_pinyin_lib            # 11 passed（回归）
```

覆盖：ATC 识别与客户端样例一致；`C07AB02` 命中 metoprolol/bisoprolol/atenolol 之一且 `tier=atc`；`C07` 结果集 ≥ 单码；大小写不敏感；16 大类四语 label（zh/zh-Hant/en/es）与 `Antibióticos` 重音归一；口语别名（退烧药→analgesics，source=colloquial）；非法码（C7/C07AB021）不误路由；普通 `lipitor` 仍 exact 且 `match_source=""`；大类快照与 `site/dist/data/categories.json` 同步。

### 2.2 评测集 `cases_v4.json`（548 例）

- `tests/search_eval/gen_atc_category_cases.py` 生成：v3 511 + 37 新用例 = **548**；
  - ATC 13：8 个 7 位精确码（取有 active 产品最多的）+ C07/C10AA/N02/J01/A10 前缀；
  - 大类 24：16 大类四语 label 轮换 + 8 个口语别名；
  - 期望 = 该码/该大类前缀下 **active 产品最多的成分**（来自 DB 结构，不取检索输出）。
- `run_ci.py` 默认优先读 `cases_v4.json`（不存在回退 v3）；`--gate-pinyin` 等旧参数不变。

### 2.3 CI 结果（`--db .tmp/lib-cat-search/eval-db-snapshot.db --jobs 6`，366.4 s）

```
atc                 13 must_hit 13  top1 10  top5 13  100.0%
category            24 must_hit 24  top1 17  top5 21   87.5%
其余 14 类（v3 旧例）与 task-111 结果一致（Top-5 380/391 = 97.2%）

must_hit：Top-5 414/428 (96.7%，门槛 ≥95%)  Top-1 383/428 (89.5%)
must_empty：40/40 通过；零结果误命中 0（门槛 = 0）
综合：454/468 = 97.0%   ✅ CI 门槛通过（退出码 0）
```

- **ATC 100%**：13/13。
- **大类 21/24**：3 例期望（按 active 产品数最多的成分）不在 Top-5：`Blood-pressure medicines` 期望 Hydrochlorothiazide（Top1 Amlodipine）、`抗过敏药` 期望 Chlorpheniramine、`抗抑鬱藥` 期望 Venlafaxine。原因：lib 结果卡按「名字」的产品数/评分排序，客户端按条目 `n` 排序；大类内成分级排名不等于卡级排名。阈值仍通过，记为已知缺口（§4）。
- 旧 391 例 must_hit 命中 380 不变；新增 37 例 34 命中（91.9%），合并 96.7%。

---

## 3. 性能 / 体积

| 项 | 数值 |
|---|---|
| SearchIndex 冷启动 | **283.9 ms**（与 task-111 后同量级，ATC/大类索引懒构建不在启动内） |
| ATC/大类索引首次查询 | **约 10.0 s/进程**（DB 全表 join 聚合 `atc→key` + `key→产品数`；仅首次） |
| 热 ATC 查询 | p50 **697 ms**（6 个样例码），max 1,012 ms |
| 热大类查询 | p50 **1,579 ms**（6 个样例），max 1,857 ms（当前最多为 200 key 构卡） |
| 普通名字查询 | 与之前一致（既有 fuzzy/慢路径不变；未受分支影响） |
| CI 全量 | 548 例 366.4 s（v3 511 例 345.3 s；+21 s，来自新增用例与每 worker 一次索引构建） |
| 站点 payload | **0 变化**（只改 lib；客户端仍用 `categories.json`/索引 `atc` 字段） |

> 性能缺口：首次 ATC/大类查询 ~10 s（CLI/单个测试可感知；CI 6 worker 并行只墙钟一次）。后续可把 atc→key 映射做成构建期产物（类似 pinyin.json）或给 DB 加索引/预聚合，避免运行时全表 join。

---

## 4. 缺口与建议

| 缺口 | 说明 | 建议 |
|---|---|---|
| 客户端无口语别名 | lib 支持「退烧药」等 60 条口语别名，客户端仍只认官方 label/alias（task-124 实测 0 结果） | 若产品要，客户端可复用 `COLLOQUIAL_ALIASES`（需改 build.py，属未排期/新任务；本次不改） |
| 大类结果排名 3/24 | 期望「产品数最多的成分」未进 Top-5（卡级 vs 成分级排序差异） | 大类结果按成分产品数排序或补充成分级候选；不影响门槛 |
| ATC 索引首查 10 s | 运行时 DB 聚合成本 | 构建期生成 `atc→key` 映射（同 pinyin.json 思路）或 DB 预聚合表 |
| ATC 数据覆盖 9.39% 缺失 | task-124：15,089 条目无 atc → ATC/大类查询覆盖不全 | 数据侧补 ATC（已有 ChEMBL/Wikidata 源）；本次不处理 |
| 大类快照同步 | `lib/categories.py` 快照自 dist；构建配置变化需重跑 `tests/gen_categories.py` | 单测 `snapshot_sync_with_dist` 会在不同步时报错；CI/建站后跑一次 |
| lib 返回条数 | lib 默认 `limit=25` 卡（客户端展示 200 行、分页）；`total_keys`/note 保留全量数 | 调用方（CLI/CI/未来 API）按需设 limit；文档已注明 |
| 评测口径 | cases_v4 的期望是「大类/ATC 下产品数最多的成分」，不是官方「类目代表成分」 | 可后续用 atc_class_names/人工映射（task-131 方向）做更权威 oracle |

---

## 5. 复现 / 证据

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 生成大类快照（构建配置变更后）与评测用例
& $py tests\gen_categories.py
& $py tests\search_eval\gen_atc_category_cases.py      # → tests/trilingual/cases_v4.json
# 单测
& $py -m unittest tests.test_lib_atc_category -v
& $py -m unittest discover -s lib -t lib
# CI（默认读 cases_v4）
& $py .tmp\lib-cat-search\mk_snapshot.py
& $py tests\search_eval\run_ci.py --db .tmp\lib-cat-search\eval-db-snapshot.db --jobs 6
# 基准
& $py .tmp\lib-cat-search\bench.py
```

- 证据：`.tmp/lib-cat-search/ci_v4.json`（548 例逐条）、`bench.json`、`eval-db-snapshot.db`；`tests/trilingual/cases_v4.json`（meta 含 db_sha/生成器）；`lib/categories.py` + `tests/gen_categories.py`。
- 未改 `site/build.py`、未写 DB、未跑 git/发布。
