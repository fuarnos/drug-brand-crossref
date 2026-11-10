# v0.11.0 P0：`lib/search.py` 对 EU 区域层行返回 `EU`

- 日期：2026-11-11（工作区时钟 2026-11-10 09:55–10:12 -08:00）
- 工位：`search-alias`（任务板 `task-1`）
- 验收对象：`lib/search.py`，SHA256 `B55852660DED8B2592774DD5B75E2EC254393E62255FC848C570210CEBF13C7F`（测试前后一致）
- 只读库：`data/drugs.db`（`mode=ro`）；未改 `site/build.py`、`site/dist`、DB、`docs/`；未 commit / 未发布。

## 结论先行

| 验收项 | 结果 |
|---|---|
| 1. `cli.py "波立维"` 含 `[EU]`、无 `[None]` | **PASS**：第 4 条 `[None]` → `[EU]`，全文件 `[None]` 0 处 |
| 2. `unittest discover -s lib -t lib` | **PASS**：`Ran 59 tests ... OK`（基线 59） |
| 3. `tests/trilingual/run_tests.py` | **PASS（达标）**：72 例全跑完，**69 通过 / 3 失败**，失败 = 既有 3 例（metformin/combo、beclometasone/dup_inn、chlorphenamine/dup_inn），**新增失败 0**；退出码 1 是「有失败」的正常返回 |
| 4. 本报告 | PASS |
| 5. 回归测试（`task-4`，§6） | **PASS**：`lib/test_search.py` +2 条 → **61 条全绿**；两条测试在 HEAD 实现上 1 FAIL + 1 ERROR |

补充（同批 39 条查询，HEAD 版 vs 修后版）：结果卡总数都是 **613 张**，`country=None` 从 **19 张（14 条查询）**降到 **0 张**，`country='EU'` 从 0 张升到 **19 张**——只补全字段，没改变命中数和排序。

**归属说明（重要）**：`lib/search.py` 的这 5 处改动**不是本工位写入的**。本工位 09:55 读源码时仍是裸 `p.country`；09:57:13 该文件被并行写入者改成 `COALESCE`（改动已完整落盘，非半成品）。本工位因此**没有重复改写**，转而做完整性核查 + 全量验收 + 对照实验。谁认领这次写入请由 Lead 在任务板上记录；若之后 `lib/search.py` 再被改动，请以本报告末尾的 SHA256 为准重跑本报告命令。

## 1. 改了什么（5 处，全文已无裸 `p.country`）

`git diff -- lib/search.py`：4 个 hunk / 8 insertions / 6 deletions，全部是同一主题：

| 位置（修后行号） | 函数 | 前 | 后 |
|---|---|---|---|
| 589 | `_substance_cards`（俗称 / 异名按成分列卡） | `SELECT p.product_id, p.country, ...` | `SELECT p.product_id, COALESCE(p.country, p.region) AS country, ...` |
| 745 | `_cards_for_keys`（名字 / ATC / 大类检索的主路径） | `SELECT pn.key_id, p.product_id, p.country, ...` | `... COALESCE(p.country, p.region) AS country, ...` |
| 1020 | `name_page`（名字页） | `SELECT p.country, ...` | `SELECT COALESCE(p.country, p.region) AS country, ...` |
| 1081 | `drug_page`（成分身份卡） | `SELECT p.product_id, p.country, ...` | `... COALESCE(p.country, p.region) AS country, ...` |
| 1089 | `drug_page` 的 **ORDER BY** | `ORDER BY p.country, pc.strength_value` | `ORDER BY COALESCE(p.country, p.region), pc.strength_value` |

- 5 处与建站侧 `site/build.py` 既有写法一致（`AS country` / `ORDER BY COALESCE(...)`），
  符合 `db/schema.sql`（`country` 与 `region` 互斥且必居其一，`COALESCE` 不会返回 NULL）。
- **顺带修掉的同类隐性子缺陷**（同一根因，HEAD 版实测可复现）：
  1. `name_page` 第 1057 行 `sorted(s["countries"])`：一个 key 同时挂 EU 行和国别行时，
     `None` 与 `'GB'` 比较会 `TypeError`。HEAD 版实测：`name_page("abasaglar")` →
     `TypeError: '<' not supported between instances of 'str' and 'NoneType'`（`search_head.py:1056`）；
     修后正常返回，`countries` 含 `'EU'`。与三语测试 `run_tests.py:355` 是同类崩溃；
  2. `drug_page` 的 `by_country` 键：EU 行原来落在 `None` 键上，现在落在 `'EU'`。
- 参数过滤路径未改但要说明：`search(..., country=...)`、`_score_card`、`sorted({c.country ...})`
  都是对卡片字段做比较，字段补全后自动成立，因此 **`--country EU` 过滤从「恒 0 条」变为可用**（见 §2.6）。

## 2. 怎么验的

Python：`C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`（3.12）。

### 2.1 验收 1：CLI 用户可见输出

```powershell
& $py cli.py "波立维"
```

before（改前 / HEAD 版）：

```
 4. CLOPIDOGREL ZENTIVA  [None]  Clopidogrel    unknown  ×11  score=0.775 (nickname)
```

after（当前工作区）：

```
 4. CLOPIDOGREL ZENTIVA  [EU]  Clopidogrel    unknown  ×11  score=0.775 (nickname)
```

`Select-String -Pattern '\[None\]'` → 0 处；退出码 0。

### 2.2 验收 2：`lib` 单测

```powershell
& $py -m unittest discover -s lib -t lib
```

- before：`Ran 59 tests in 5.484s` / `OK`
- after：`Ran 59 tests in 6.240s` / `OK`，退出码 0

### 2.3 验收 3：三语一致性（72 例）

```powershell
& $py tests/trilingual/run_tests.py
```

- **before：崩溃，未跑完**。前 6 例 PASS 后在 `tests/trilingual/run_tests.py:355`
  `sorted({c.country for c in cards})` 抛 `TypeError: '<' not supported between instances of 'NoneType' and 'str'`，退出码 1。
- **after：完整跑完 72 例**

```
案例 72（通过 69）；查询 354 条：Top-5 命中 98.6%，Top-1 命中 95.5%；跨国可见 72/72；用时 610.7s
  en: 123 条查询, Top-5 121, Top-1 115 (98.4%)
  es: 116 条查询, Top-5 114, Top-1 112 (98.3%)
  zh: 115 条查询, Top-5 114, Top-1 111 (99.1%)
```

3 例失败与 v0.10.3 起的既有失败**逐条同名**，无新增：

```
[FAIL] metformin      combo    查询 2/3 命中Top5, Top1 2/3   zh '西格列汀二甲双胍片' cards=8 top1=['Sitagliptin']
[FAIL] beclometasone  dup_inn  查询 1/3 命中Top5, Top1 1/3   en 'beclomethasone' / es 'beclometasona' top1=['Beclomethasone']
[FAIL] chlorphenamine dup_inn  查询 2/3 命中Top5, Top1 0/3   es 'clorfenamina' top1=['Chlorpheniramine','Tramazoline']
```

（这 3 例的同物异名 / 复方归并问题与本次 country 修复无关，HEAD 版跑到那一步会先崩，故无法在 HEAD 上直接对比；判定依据是任务书列的既有失败清单。）

### 2.4 补充证据：同批查询 HEAD 版 vs 修后版

39 条跨语言查询（含 clopidogrel / denosumab / aripiprazole / apixaban / humira 等有 EU 产品的成分），
用 `git show HEAD:lib/search.py` 载入同一 `SearchIndex` 对照（只读）：

| 版本 | 结果卡 | `country=None` | `country='EU'` | 含 None 的查询 |
|---|---|---|---|---|
| HEAD（改前） | 613 | **19** | 0 | 14 条（波立维/Plavix/Denosumab/Prolia/Xgeva/Aripiprazole/Abilify/Clopidogrel/Apixaban/Eliquis/Jardiance/Ozempic/Humira/Keytruda） |
| 当前工作区（改后） | 613 | **0** | **19** | 0 条 |

卡数不变 = 修复没有增删候选、没有改变排序，只把 `country` 字段从 `None` 补成 `'EU'`。

### 2.5 补充证据：三条取 country 的路径都干净

- `name_page`：抽 5 个含 EU 行的 trade key，`substances[*].countries` 与 `countries` 键均无 `None`；
  首个 key 的 `countries = ['AU','CA','ES','EU','MX','US']`。
  HEAD 版对照：`name_page("abasaglar")`（同时挂 EU 与国别行）直接
  `TypeError: '<' not supported between instances of 'str' and 'NoneType'`，修后返回
  `countries` 含 `'EU'` 的完整字典 —— 即本 P0 同时修掉了名字页的一条崩溃路径。
- `drug_page`：`denosumab`（10 键）/ `aripiprazole`（11 键）/ `clopidogrel`（9 键）均含 `EU`、无 `None` 键。
- `search()`：39 条查询 613 张卡，`country=None` 0 张。

### 2.6 补充证据：`--country EU` 从「恒 0 条」变为可用（用户可感知的第二个 bug）

| 版本 | `cli.py "波立维" --country EU` |
|---|---|
| HEAD | `cards=0`，提示「「波立维」对应的 氯吡格雷 在 EU 没有收录 —— 查不到不代表该药不存在」← **假阴性** |
| 当前 | `1. CLOPIDOGREL ZENTIVA  [EU]  Clopidogrel  unknown  ×11  score=0.875 (nickname)` |

即 EU 入库后若不修这层，CLI / 手机看板按 EU 过滤会得到「没收录」的错误结论。

### 2.7 完整性核查

- 全仓库扫非 `COALESCE` 的 `p.country`：`lib/`、`cli.py`、`mobile/` **0 处**；
  其余 52 处全在 `etl/**`、`db/**`（ETL 入库、按具体国家 `WHERE p.country='CN'` 的过滤、审计/指标），
  不在检索路径；`db/consistency_audit_form.py` 本就写 `p.country or p.region`。
- `git status`：本次只读验收，未新增/修改任何被跟踪文件（`site/build.py` 的改动属 `site-ui` 工位）。
- 测试前后 `lib/search.py` SHA256 一致（见页首），验收对象稳定。

## 3. 剩余风险

1. **并发归属**：改动由并行写入者在 09:57:13 落盘，本工位只做核查与验收。若 `site/build.py` 之外的工位也在改
   `lib/search.py`，以页首 SHA256 为准重跑 §2 命令；不一致就说明验收对象已变。
2. **站点明细桶不含 EU 行**（P2，非检索层）：`data/idx/detail-*.json`（51 个文件，2026-10-28 10:26 生成，
   294,895 行）由 `etl/build_detail_buckets.py` 预生成、`site/build.py` 原样复制。现查：空 country 行 0、
   含 EU 产品 **0/2,095** —— 桶早于 EU 入库，站点「展开明细」里看不到 EU 行。需重跑该 ETL
   （`run_all.py --no-ingest` 不含它，属 ETL / 建站侧，不在本工位写权限），不属本 P0，但发布前要知道。
   另外该脚本里是 `r["country"] or ""`，重跑时应改成 `COALESCE(p.country, p.region)`，否则 EU 行会以空串出现。
3. **回归测试**：已由 `task-4` 补上（`lib/test_search.py`，见 §6，本报告追加节）；这一项已关闭。
   当前唯一没锁的是「其它区域层代码（未来新增 region）」，加新 region 时按同一模式在夹具里补一行即可。
4. **未跑全量 CI**：`deploy/ci_checks.py`（全量，含 trilingual / check_data / first-screen）属发布前 Lead 门槛；
   本工位按任务书只跑 lib 单测 + 三语。
5. **数据事实**：`product` 共 479,193 行，其中 `region='EU' AND country IS NULL` **2,095** 行（0.44%），
   修复后这 2,095 行在所有检索路径都以市场键 `'EU'` 出现，与站点索引口径（`site/build.py` 的
   `COALESCE(p.country, p.region)`）一致。

## 4. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'

(Get-FileHash lib/search.py -Algorithm SHA256).Hash       # B558...（验收对象）
& $py cli.py "波立维"                                    # 第 4 条应为 [EU]，无 [None]
& $py cli.py "波立维" --country EU                       # HEAD 版为 0 条，现为 1 条
& $py -m unittest discover -s lib -t lib                 # Ran 59 tests / OK
& $py tests/trilingual/run_tests.py                      # 72 例，69 通过，3 例既有失败

# 同批 39 条查询 HEAD vs 修后 对照（脚本落在 .tmp，不入库）
& $py .tmp/p0-search/compare_head.py                     # HEAD: 613 卡 / None 19 / EU 0
& $py .tmp/p0-search/scan_no_none.py                     # 修后: 613 卡 / None 0  / EU 19
```

数据侧核对（只读）：

```sql
SELECT COUNT(*) FROM product;                                        -- 479193
SELECT COUNT(*) FROM product WHERE region='EU' AND country IS NULL;  -- 2095
```

## 5. 未做（明确出界）

- 未改 `site/build.py` / `site/dist` / `.tmp/dist-*`；未跑建站。
- 未动 `data/drugs.db`（只 `mode=ro` 打开）；未重跑任何 ingest。
- 未改 `docs/`、`CHANGELOG.md`；未 commit、未 tag、未发布。
- 未处理 `etl/build_detail_buckets.py` 的 EU 明细（§3.2，已派 `page-slim` / `task-3`）；未接线 `eu.region_title` 文案（`task-2`）。

## 6. 回归测试（`task-4`，2026-11-11 追加）

**结论**：`lib/test_search.py` 加夹具 + 2 条测试后，`unittest discover -s lib -t lib` → **61 条全绿 / 零失败**（原 59 + 2）；
把同样两条测试跑在 HEAD（裸 `p.country`）实现上 → **1 FAIL + 1 ERROR**，证明它们真的锁住了本 P0。
只改 `lib/test_search.py`；`lib/search.py` 未动（SHA256 仍为 `B558…`）。

### 6.1 夹具（`lib/test_search.py`）

| 改动 | 内容 |
|---|---|
| `SUBS` | 新增 `("denosumab", "Denosumab", "地舒单抗")` |
| `PRODUCTS` | 新增 `("US-prolia", "US", "Prolia", ...)` —— 让同名商品名同时有国别行 |
| `EU_PRODUCTS`（新） | `("EU-prolia", "Prolia", ...)`：**只写 `region='EU'`，`country` 保持 NULL**（`db/schema.sql` 二选一约束）。刻意只给 region：任何退回裸 `p.country` 的取数都会拿到 `None`，测试随之失败 |
| `insert_product()`（新） | 把「插产品 + 成分 + 商品名」抽成一处，`country` / `region` 关键字二选一；原 `PRODUCTS` 循环改调它（行为不变，59 条旧测试全过） |

### 6.2 新测试与断言结果

| 测试 | 断言 | 修后结果 |
|---|---|---|
| `SearchTests.test_eu_region_card_country_is_eu` | `search("Prolia")` 的结果卡中无 `country is None`；含 `'EU'`；`search("Prolia", country="EU")` 非空且国别集合 == `{'EU'}` | **ok** |
| `SearchTests.test_eu_region_pages_sort_eu_with_country` | `name_page("prolia")` 的 `countries` / `substances[0].countries` 排序为 `['EU','US']`（原 bug 在此 `TypeError`）；`drug_page("denosumab")` 的 `by_country` 含 `'EU'` 且无 `None` 键 | **ok** |

```powershell
& $py -m unittest discover -s lib -t lib -v
# test_eu_region_card_country_is_eu ... ok
# test_eu_region_pages_sort_eu_with_country ... ok
# Ran 61 tests in 6.039s / OK   （退出码 0）
```

### 6.3 反证：同一测试跑在 HEAD 实现上会失败

用 `git show HEAD:lib/search.py` 注册成 `sys.modules["search"]` 再跑同一份 `lib/test_search.py`
（脚本 `.tmp/p0-search/run_new_tests_on_head.py`，只读）：

```
test_search 实际用的实现文件: .tmp\p0-search\search_head.py
test_eu_region_card_country_is_eu ... FAIL
  AssertionError: [... Card(key_id='prolia', brand='Prolia', country=None,
                     product_id='EU-prolia', ...)] != []
  : EU 区域层卡片的 country 不能是 None
test_eu_region_pages_sort_eu_with_country ... ERROR
  TypeError: '<' not supported between instances of 'str' and 'NoneType'
  （lib/test_search.py → search_head.py:1056 `s["countries"] = sorted(s["countries"])`）
Ran 2 tests in 0.201s / FAILED (failures=1, errors=1)
```

即：以后谁把 `COALESCE(p.country, p.region)` 改回裸 `p.country`，这两条会立刻红。

### 6.4 边界

- 夹具只覆盖 `region='EU'` 这一种区域层；`db/schema.sql` 新增 region 时照 `EU_PRODUCTS` 再加一行即可。
- 新增 `denosumab` / `Prolia` 只影响 `lib` 测试夹具，不碰 `data/drugs.db`、`site/`、`etl/`。
- `test_eu_region_*` 是行为断言，不校验具体 SQL 文本；SQL 写法变了但只要行为对（EU 行返回 `'EU'`）就仍然通过。

