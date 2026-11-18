# V7b 别名→成分检索定位（服务端 + 客户端同一口径）

- 日期：2026-11-19（北京时间谷段）
- 工位：search-alias
- 任务：task-6（V7b，目标版本 v0.14.0）
- 结论先行：**两端同一口径、有效别名 1,404 条 Top-1 漏 0，两端逐条一致 1,404/1,404**
  （服务端 `lib/search.py` 实测；客户端用 Node 执行 `site/build.py` 里真实的
  `aliasKey/aliasHits` + 构建期同一函数生成的 `aliases.json`，2026-11-19 09:19 现跑）。
  改前基线：服务端漏 139、客户端漏 236、两端一致 1,167/1,404。
- 交付物：`lib/search.py`、`lib/test_search_nickname_key.py`、`site/build.py`
  （仅 nickname 索引/查询区段）、本报告 + `reports/2026-11-19-v7b-alias-full-check.py`
  + `reports/2026-11-19-v7b-alias-full-check.csv`（1,404 行逐条明细）。

## 1. 口径（Lead 2026-11-18 定）

| 项 | 数字 | 说明 |
|---|---|---|
| `aliases.json` 全量 | **1,438** | `alias_all` 1,413（`nickname` 396 + `drug_term` 1,017）+ `data/substance_aliases.csv` 同物异名 **25**；= `site/build.py` 日志 `building nickname index` 的同一份口径 |
| 有效分母（有成分） | **1,404** | 1,438 − 34 条无 `substance_id` 的类别词 |
| 无成分别名 | **34** | `drug_term` 的 class/folk 类别词（如 `water pill`＝利尿剂），本来就不落到某个成分页，单列、不算漏 |
| 多成分别名 | **2 个叫法 / 4 行** | 「P药」→ nirmatrelvir + ritonavir；「美白丸」→ tranexamic-acid + glutathione；Top-1 只能落一个，另一条必须在候选集里 |

> 注意：`nickname` 表本身只有 **396** 行；「1,438」是构建产物 `aliases.json` 的条数。
> tirzepatide 在 `nickname` 表 **0 行**，「替西帕肽 / 猛健樂」来自 `drug_term`（CN folk）——
> 只做 nickname 会漏掉用户点名的两条。

「Top-1 落到该成分页」的判定：

- `nickname` / `drug_term`：搜索结果的**首张别名卡**（服务端 `SearchResult.alias`；
  客户端 `nickHTML` 的第一张卡）指向的 substance == 该行指向的成分；有在售产品时，
  首张结果卡的成分集合还要包含它。
- `substance_alias`（CSV）：别名卡指向 canonical 成分（服务端 `lib/aliases.py` 并查集；
  客户端 aliases.json 的 `v`）。按 task-141b 设计，异名层**只追加候选、不替换主结果**，
  所以商品结果卡的首张可能仍是别名写法自身（如搜 Dextrose 先出 Dextrose 的条目），
  canonical 成分页由**别名卡**直达。
- 多成分别名：Top-1 落其中一个、另一条在候选集（`res.aliases` / 前 3 张别名卡）即通过。

## 2. 基线（改前，2026-11-19 现查）

全量脚本：`reports/2026-11-19-v7b-alias-full-check.py`（只读 DB，遍历 1,438 条；
客户端用 Node 执行从 `site/build.py` 原样抽取的 `toSimp/norm/_flatAccents/aliasHits`）。

| 侧 | 指标 | 改前 |
|---|---|---|
| 服务端 `lib/search.py` | 别名未被识别（`res.alias` 为空） | **139** |
| 服务端 | Top-1 不是目标成分（在售产品存在时） | 139（同上，未识别即落到名字路径） |
| 客户端 `aliasHits` | 别名卡未命中（resolved 为空） | **236** |
| 两端 | Top-1 substance 一致 | **1,167 / 1,404（83.1%）** |
| 演示 | 猛健樂 | 服务端 ✅ tirzepatide；客户端 ❌ 0 命中 |
| 演示 | 替西帕肽 | 两端 ✅ tirzepatide |

### 根因（都不是「数据缺条」，是匹配键口径分叉）

1. **DB 里的 `alias_norm` 是历史归一化写下的**：服务端旧 `_alias_hits` 直接比
   `alias_norm`，而 `drug_term` 有 **116 条** 的 `term_norm` 与当前 `normalize()`
   不一致（如 `阿司匹靈` 存成 `阿司匹靈`，当前 `normalize()` 得 `阿司匹灵`）。
2. **繁简字表两端不一样**：客户端 `data/zh_hant_t2s.json` 有 **2,966** 字（OpenCC
   子集），Python `etl/normalize_name.py::_T2S` 只有约 **90** 字。客户端把
   `猛健樂` 转成 `猛健乐`、`阿司匹靈` 转成 `阿司匹灵`，但索引里的 `n` 是 DB 的旧
   归一化值（保留繁体）→ 对不上；`猛健樂` 因此在客户端 **0 命中**。
3. **标点处理两端不同**：客户端 `norm()` 不删标点，旧服务端 `normalize()` 把标点
   转空格，`654-2` / `morning-after pill` 这类叫法在两侧各漏一半。
4. **CSV 同物异名 25 条不走服务端 nickname 路径**：它们在服务端由异名层
   （`match_detail.inn_alias`）给出 canonical，客户端由别名卡直达；旧全量统计若
   只数 `res.aliases` 会把 25 条误记成漏。

量化：换用同一把 `alias_key` 后，`alias_all` 有 **276 条**的构建期 `n` 与旧
`alias_norm` 不同（全部是 `drug_term` 繁体写法/标点差异；其中 236 条在旧客户端实际
漏命中，其余旧三档比较/重音规则刚好兜住）；CSV 25 条的旧归一化与新键恰好一致。

## 3. 外部方案检索（AGENTS §12）

| 候选 | License | 结论 |
|---|---|---|
| [OpenCC](https://github.com/BYVoid/OpenCC)（繁简转换，C++/Python/数据表） | Apache-2.0 | **采用其数据**：仓库已有 `data/zh_hant_t2s.json`（OpenCC `TSCharacters.txt` 的 BMP 单字子集，2,966 字，见 `_meta.source`），V7b 直接复用，**不新增依赖**；完整 OpenCC 运行时（含词级转换）体积/构建链不必要 |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz)（模糊匹配） | MIT | **不采用**：俗称/别名是「差一个字就是另一个梗」，既有设计明确只做精确 + 连写 + 去重音；模糊匹配会把噪声带进 Top-1 |
| SQLite FTS5 / trigram（内置全文索引） | Public Domain（SQLite） | **不采用**：要解决的是「归一化后精确相等」而不是全文检索；FTS5 需要重建索引/改库，违反本轮「不改数据」 |

结论：**零新增依赖**，只把「同一张 2,966 字表 + 同一套标点/重音规则」落到两端。

## 4. 实现（阶段 2）

### 4.1 服务端 `lib/search.py`（已完成，未提交）

新增（约 +110 行，全部只读）：

- `alias_key(text)`：与客户端 `app.js::norm()` 同口径——`toSimp`（读
  `data/zh_hant_t2s.json` 的 2,966 字，**不另写表**）→ NFKC → lower → 去 `®™©`
  → 去组合音标 → 标点/符号→空格 → 压空白。
- `alias_query_key(query)`：先按客户端 `splitDose()` 的同一对正则切掉 `mg/ml/iu/%/万单位`，
  再取 `alias_key`（`泰诺 500mg` → `泰诺`）。
- `alias_key_matches(stored, query)`：`aliasHits` 的三档比较（原样 / 去空格 / 去音标去空格）。
- `SearchIndex.__init__`：装载 `alias_all` 时为每行现算 `match_key`，**不再读 DB 的
  `alias_norm`**（不改库）；`_alias_hits(query)` 改用它。
- 同一叫法既有类别词（无成分）又有成分时**优先有成分的行**（如「普拿疼」），
  避免首张别名卡是不可点的类别词；`_search_alias` 的首卡同样取第一条有成分的。

不改：`alias_key` 只影响别名匹配，`normalize()`/name_key/模糊/拼音/ATC/大类路径原样；
`nickname` / `drug_term` / `product_name` 数据一行不动。

### 4.2 客户端 `site/build.py`（已完成，BUILD-FREE 后落地）

只改 nickname 索引/查询区段（5 处 `edit` 唯一锚点，未 `write` 整个文件）：

1. `load_aliases()` 的 `"n": norm` → `"n": alias_key(alias)`（`from lib.search import
   alias_key`，不在 build 里写第二份 Python 实现）；
2. 别名索引顺序：同一叫法下**有成分的行排前**（「普拿疼」首卡可点）；
3. `_norm_alias()`（CSV 同物异名）→ 薄包装 `alias_key`，不再另写 NFKC/标点规则；
4. 页内 `app.js` 新增 `aliasKey()`：与 Python `alias_key` 同一规则、同一张 `T2S`
   （构建期从 `data/zh_hant_t2s.json` 注入 `toSimp`）；
5. `aliasHits()` 改为 `aliasKey(a.n)` vs `aliasKey(nq)` 三档比较（原样 / 去空格 /
   去音标去空格），并兼容浏览器里旧的缓存 `aliases.json`（旧 `n` 再归一一次）。

「同一函数/同一张表」的机器验证：全量脚本把页内 JS 抽出来跑，**JS `aliasKey` 与
Python `alias_key` 在 1,438 条别名上键不一致 = 0 条**。

### 4.3 全量验证脚本（已落盘）

`reports/2026-11-19-v7b-alias-full-check.py`：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'

# 只跑服务端（约 2 分钟）
& $py reports/2026-11-19-v7b-alias-full-check.py --side server

# 两端全量（客户端用 Node 执行 app.js 里的 aliasHits；约 2–3 分钟）
& $py reports/2026-11-19-v7b-alias-full-check.py --side both
```

- 输出：1,404 行 CSV（默认 `.tmp/v7b/v7b_alias_full_check.csv`；**定稿已写
  `reports/2026-11-19-v7b-alias-full-check.csv`**）+ 汇总 JSON；
- 1,404 行逐条给 `target_sid / server_resolved / server_target_in_top1 /
  client_first_card / client_first_mapped / client_target_in_cards / agreed_top1`；
- 退出码 0 = 服务端漏 0 + 客户端漏 0 + 两端 Top-1 substance 一致 1,404/1,404。

> 说明：未跑全量 temp 构建（`SITE_OUT=.tmp/dist-v7b` 需 Lead 让位；v0.14.0 真实构建由
> Lead 统一做）。客户端读数用的是 `site/build.py` **同一对函数**（`load_aliases` /
> `load_substance_aliases` 现算 aliases.json）和**从源码原样抽取的页内 JS**，
> 与构建产物的索引/匹配代码逐字一致；v0.14.0 构建后可用同一条命令对 `site/dist`
> 再复核（属发布验收，不在本工位）。

## 5. 验收数字

### 5.1 服务端（已实测，lib/search.py 已改）

| 指标 | 数字 |
|---|---|
| 全量别名 | 1,438 |
| 有效分母（有成分） | 1,404 |
| 无成分（单列，不算漏） | 34 |
| 别名未识别 / Top-1 漏 | **0 / 1,404** |
| 多成分别名「候选命中」 | 2（P药、美白丸各 1 行；另 1 行是 Top-1 本身） |
| 演示「猛健樂」「替西帕肽」 | 两端均 tirzepatide（服务端实测；客户端见 5.2） |

复现：`& $py reports/2026-11-19-v7b-alias-full-check.py --side server`

### 5.2 客户端 + 两端一致（真实 build.py，2026-11-19 09:19 现跑）

BUILD-FREE 后 §4.2 的 5 处 `edit` 已落到真 `site/build.py`；先用 `.tmp/build_v7b.py`
副本预演（结论相同），再对真文件跑：

```powershell
& $py reports/2026-11-19-v7b-alias-full-check.py --side both --client-mode node `
    --csv reports/2026-11-19-v7b-alias-full-check.csv
```

| 指标 | 改前（真实 aliasHits） | 改后（真实 build.py） |
|---|---|---|
| 别名卡未命中 | 236 | **0** |
| 目标不在候选 | 0（未命中自然 0） | **0** |
| 两端 Top-1 substance 一致 | 1,167 / 1,404 | **1,404 / 1,404（100%）** |
| strict Top-1 非目标 | 239 | **2**（均为多成分别名，候选命中，见 §6） |
| JS `aliasKey` 与 Python `alias_key` 键不一致 | — | **0 / 1,438** |
| 演示「猛健樂 / 替西帕肽」客户端首卡 | 猛健樂 ❌ / 替西帕肽 ✅ | **两条均 tirzepatide ✅** |

- 34 条无成分别名单列（`unmapped`），不进 1,404 分母；
- 2 条多成分别名（P药/美白丸的第 2 行）记「候选命中」：Top-1 落一个成分、
  另一个在前 3 张别名卡 / `res.aliases` 里——与 AGENTS §1「查询永远返回候选集」一致；
- CSV 明细：`reports/2026-11-19-v7b-alias-full-check.csv`（1,404 行，含两端结论）。

> **复核**：上表为 2026-11-19 09:19 首跑；Lead 完成 v0.13.8 干净重建并把工作区
> `site/build.py`（含 V7b 5 处 edit）原样放回后，**09:47 用同一条命令重跑，数字完全一致**
> （1,404 漏 0、两端一致 1,404/1,404、JS/Python 键不一致 0、CSV 已按本次结果覆盖），
> 脚本退出码 **0**。

构建产物抽样（`load_aliases() + load_substance_aliases()` 现算，1,413 + 25 = 1,438）：

| 原始别名 | `aliases.json` 的 `n` | 指向 |
|---|---|---|
| 猛健樂 | `猛健乐` | tirzepatide ✅ |
| 替西帕肽 | `替西帕肽` | tirzepatide ✅ |
| 阿司匹靈 | `阿司匹灵` | aspirin ✅ |
| 654-2 | `654 2` | anisodamine ✅ |
| 普拿疼 | `普拿疼` | acetaminophen（可点）排前，无成分类别词排后 ✅ |
| P药 / 美白丸 | `p药` / `美白丸` | 两个成分各一条，候选集 ✅ |

### 5.3 其它门禁（最终读数）

- `& $py -m unittest discover -s lib -t lib`：**71 tests OK**（新增 10 条
  `lib/test_search_nickname_key.py`；改后复跑 10.7s）；
- `deploy/ci_checks.py --fast`（build.py 改后复跑）：**PASS 8 / FAIL 0 / SKIP 5**
  （etl 63、lib 71、mobile 29 全绿；py_compile 182 文件通过）；
- `tests/trilingual/run_tests.py`（build.py 改后复跑）：**78 例 / 75 通过**、查询 360 条、
  Top-5 **98.6%**、Top-1 **96.1%**、跨国 **78/78**、133.5s；失败恰为既有 3 个 allowlist
  （metformin/combo、beclometasone/dup_inn、chlorphenamine/dup_inn），**无新增失败**
  （Top-1 还从基线 93.1% 升到 96.1%，别名路径修好后部分中文查询不再落空）；
- 无新增依赖（只用 stdlib + 仓库既有 `data/zh_hant_t2s.json`）。

### 5.4 数据未动（AGENTS §1 / §9）

| 表 | 改前/改后 |
|---|---|
| `product_name` | **780,843**（不变；俗称没有写进商品名） |
| `nickname` | **396**（不变） |
| `drug_term` | **1,017**（不变） |
| `data/substance_aliases.csv` | 未改（25 条同物异名照旧） |

`alias_key` 只在**装载/构建期**现算匹配键；`data/drugs.db` 的 `alias_norm` / `term_norm`
一行未改，站点产物里 `aliases.json` 仍是 1,438 条。

## 6. 已知边界 / 残留

- 34 条无成分类别词：别名卡只给类别说明，**不链成分页**（设计如此，单列）。
- 2 个多成分别名：「P药」「美白丸」Top-1 只能落一个，另 2 行在候选集（Top-3 卡）里；
  按「别名不是主键、查询永远返回候选集」（AGENTS §1）记为候选命中，不算漏。
- CSV 同物异名：商品结果卡首张可能仍是别名写法自身的成分（task-141b「只追加、不替换」
  的既定语义），canonical 成分页由别名卡直达；报告 CSV 里 `server_target_in_top1`
  对 CSV 行取「别名卡结论」，避免把既定语义误判成漏。
- 浏览器缓存：`data/aliases.json` 没有 `?v=`；`aliasHits` 对旧 `n` 再做一次
  `aliasKey`，旧缓存也能命中，不做额外的缓存策略改动。
- **构建级门禁不在本工位跑**：本工位未跑全量 temp 构建（需 Lead 让位；v0.14.0 由 Lead
  统一构建）。`site/build.py` 内容变化会让 `BUILD_V`（源码哈希）变化 → 全站 `?v=`
  轮换，属既定构建行为；首屏守卫、页数 / 索引体积 / 链接 / 404 / sitemap、构建确定性
  由 Lead 在 v0.14.0 构建与发布验收里跑（AGENTS §5）。构建产物出来后可用同一条
  `--side both` 命令对 `site/dist` 再复核一次（本报告的数字来自同一对构建期函数 +
  同一份页内 JS 源码）。
- 发布前不需要再改数据：`nickname` / `drug_term` / `product_name` / CSV 全部未动；
  后续新增别名仍走「`nickname` 表 + 出处」或 `drug_term`，构建时自动获得同一匹配键。
