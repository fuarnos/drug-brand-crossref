# P0 修复：中文 1–3 字通用名「幽灵 exact」导致 0 结果

> 任务：`task-19` · 来源：`reports/trilingual-query-tests.md`（task-14 三语测试发现）· 日期：2026-10-26
> 改动文件：`lib/search.py`（修复）· `lib/test_search_short_cjk.py`（新增回归测试，10 项）· 本报告
> 未改：`data/drugs.db`（只读）、`site/build.py`、`site/dist`、`tests/trilingual/`；未跑 git / 发布 / 站点构建。

---

## 1. 问题

三语测试里 3 条中文通用名查询返回 0 结果，提示却是「名字对上了，但没有在售产品」：

| 查询 | 期望 | 修复前 |
|---|---|---|
| `舍曲林` | Sertraline（盐酸舍曲林片 47 个产品） | 0 卡，虚假提示 |
| `氟西汀` | Fluoxetine（盐酸氟西汀胶囊 26 个产品） | 0 卡，虚假提示 |
| `喹硫平` | Quetiapine（富马酸喹硫平片 59 个产品） | 0 卡，虚假提示 |

同类症状还包括 2 字中文查询（`地平` → 0 卡）以及所有"库里只有「盐型+剂型」长名、没有裸通用名 key"的中文名。

### 根因（两处，都在 `lib/search.py` 的 `_resolve_keys()`）

1. **幽灵 exact**（旧 L157）：`add(n.norm, "exact")` 无条件把**查询本身**当成 `name_key`，不校验它是否存在于库里。库里 `name_key` 没有 `舍曲林`，真实 key 是 `盐酸舍曲林片`；于是 `keys=['舍曲林'(exact)]` → 查 `product_name` 0 行 → 提示误导。
2. **中文 contains 门槛错用英文标准**（旧 L165）：`len(n.norm) >= 4 and n.norm in norm` 对中文也要求 4 字，导致 2–3 字中文名无法子串命中 `盐酸舍曲林片` 这类长 key。

**影响面（只读 SQL 实测）**：中文 `name_key` 共 11,914 个，其中 `norm` 长度 ≤3 字 4,569 个；带剂型后缀的中文 key（`…片`/`…胶囊`/`…注射液`…）4,370 个（36.7%）。三字药名 + 盐型前缀是常见组合，属于真实用户输入形态。

> **范围澄清**：线上静态站的检索在浏览器端 `app.js` 里执行，其 `tier()` 已经是 `cjk ? 2 : 4` 且只遍历真实索引 key（不存在幽灵 exact），因此**线上 JS 侧没有这个 bug**；本 P0 影响的是 Python 检索层 `lib/search.py`（`cli.py` 命令行检索、单测/回归基线、三语测试集、未来的服务端 API）。客户端 v0.2.1 的 2 字口径正是本修复的对齐基准。

---

## 2. 修复

改动仅 `lib/search.py`，26 行 diff（`+22 / −4`，含注释），完整 diff 见 `.tmp/search-fix/search_py.diff`：

```diff
 class SearchIndex:
     def __init__(...):
         self._norms = [...]
+        # exact 命中必须真实存在于 name_key，不能把查询本身当成 key（见 _resolve_keys）。
+        self._norm_set = {norm for _key_id, norm, _compact in self._norms}

+    @staticmethod
+    def _min_substring(n) -> int:
+        """子串匹配要求的最短查询长度。中文沿用站点客户端 v0.2.1 tier() 的
+        `cjk ? 2 : 4`；拉丁文仍是 4 字，避免短英文串把噪声大规模带出。"""
+        return 2 if n.script == "han" else 4

     def _resolve_keys(self, n):
-        add(n.norm, "exact")
+        # P0 修复：exact 只认库里真实存在的 key。
+        if n.norm in self._norm_set:
+            add(n.norm, "exact")
         for key_id, norm, compact in self._norms:
             ...
-            elif len(n.norm) >= 4 and n.norm in norm:
+            elif len(n.norm) >= self._min_substring(n) and n.norm in norm:
                 add(key_id, "contains")
+        # 模糊匹配保持与客户端一致：仅 4 字以上查询才做（中文也是 4 字）。
         if len(hits) < 5 and len(n.norm) >= 4:
```

### 设计取舍

| 决策 | 选择 | 理由 |
|---|---|---|
| exact 校验方式 | 启动时建 `self._norm_set`（135k 字符串引用），O(1) 查 | 比每查一次 SQL 便宜；内存增量几 MB；`_norms` 本来就全量载入 |
| 中文 contains 门槛 | 2 字 | 与站点客户端 v0.2.1 `tier()` 完全一致（`const cjk = /[\u4e00-\u9fff]/.test(nq); const minSub = cjk ? 2 : 4;`），避免"服务端/客户端两套口径" |
| 拉丁 contains 门槛 | 保持 4 字不变 | 不引入英文短串噪声，现有回归测试（`test_search.py` 19 项）全过 |
| fuzzy | 保持 `len>=4`（中文也 4）且阈值不变 | 客户端 fuzzy 同样 4 字起；短中文名走 contains 已足够，不扩大模糊风险 |
| 2 字是否降权 | **暂不降权** | 客户端就是 `contains=0.70` + `MAX_KEYS=60`，站点定位"返回候选集不是唯一答案"；降权会制造客户端/服务端排序差异。若后续出现 2 字噪声投诉，可在 scoring 层给 `han && len==2` 的 contains 加 -0.05 微调（客户端同步改），本次不做 |
| 1 字查询 | 不进入 contains（<2），保留原有 prefix/exact 行为 | 1 字 contains 噪声过大；实测 `地` 仍能靠 prefix 返回 43 个 key 的候选 |

---

## 3. 修复前后行为对比（真实库）

`.tmp/search-fix/repro_before.json` / `repro_after.json`（对 `data/drugs.db` 只读实测）：

| 查询 | 修复前 keys / 卡数 | 修复后 keys / 卡数 | 修复后 Top-1 成分 |
|---|---|---|---|
| `舍曲林` | `['舍曲林']` / **0**（虚假提示） | `盐酸舍曲林片` 等 3 key / **3** | Sertraline |
| `氟西汀` | `['氟西汀']` / **0** | 6 key / **6** | Fluoxetine |
| `喹硫平` | `['喹硫平']` / **0** | 2 key / **2** | Quetiapine |
| `埃索美拉唑`（旧名，库里无） | 虚假 exact / 0 | **0 key**，提示"没有匹配的名字" | —（如实告知） |
| `地平`（2 字） | 虚假 exact / **0** | 60 key / **25**（候选集） | Levamlodipine |
| `布洛芬` | 23 key / 23 | 30 key / 25 | Ibuprofen |
| `立普妥`（库里有 key） | 1 key / 2 | 1 key / 2 | Atorvastatin |
| `地`（1 字） | 43 key / 25（靠 prefix） | 42 key / 25（行为不变） | Dexamethasone |

**结论**：目标三类 3 字药名与 2 字部分名从 0 → 正常候选集；真实不存在的名字改为诚实提示；已有 exact 名字与 1 字 prefix 行为不变。

---

## 4. 回归测试

### 4.1 新增 `lib/test_search_short_cjk.py`（10 项）

夹具库刻意构造「盐型+剂型」长 key（`盐酸舍曲林片`、`盐酸氟西汀胶囊`、`富马酸喹硫平片`、`苯磺酸氨氯地平片`），覆盖：

| # | 测试 | 断言 |
|---|---|---|
| 1 | `test_three_char_generic_hits_salt_prefixed_key` | 舍曲林/氟西汀/喹硫平 均命中盐型长 key，且不出现虚假提示 |
| 2 | `test_exact_tier_requires_real_key` | `_resolve_keys('舍曲林') == [('盐酸舍曲林片','contains')]`，没有幽灵 key |
| 3 | `test_unknown_cjk_name_is_honest` | 不存在的 `埃索美拉唑` → `total_keys=0`、提示"没有匹配的名字" |
| 4 | `test_two_char_cjk_contains` | `地平`/`氨氯` 2 字可子串命中 |
| 5 | `test_two_char_cjk_prefix_still_works` | `盐酸` 仍走 prefix，命中两药 |
| 6 | `test_one_char_cjk_does_not_contains` | 1 字不进入 contains |
| 7 | `test_latin_contains_threshold_unchanged` | 拉丁 4 字 `tati` 命中、3 字 `tat` 不命中（不回归） |
| 8 | `test_latin_exact_and_fuzzy_unchanged` | exact / fuzzy tier 行为不变 |
| 9 | `test_short_cjk_no_fuzzy` | 3 字中文拼错不做 fuzzy（与客户端一致） |
| 10 | `test_two_char_nickname_still_resolves` | 2 字俗称 `伟哥` 仍先走 alias 路径 |

### 4.2 全量单测

| 套件 | 结果 | 命令 |
|---|---|---|
| lib（含新文件 10 项 + 既有 19 项） | **29 passed / 0 failed**（0.46s） | `python -m unittest discover -s lib -t lib` |
| etl（归一化 + 加拿大等） | **25 passed / 0 failed**（0.01s） | `python -m unittest discover -s etl -t etl` |

日志：`.tmp/search-fix/test_short_cjk.log`、`unittest_lib.log`、`unittest_etl.log`。

### 4.3 三语测试集前后对比（72 案例 / 354 查询，DB 固定快照）

> 方法：团队同时有其它任务在写 `data/drugs.db`，首轮直接跑真实库两次都因 `database is locked` 中断；改用 **SQLite backup API 快照**（`.tmp/search-fix/drugs_snapshot.db`，450 MB）+ `run_compare.py` 在不改 `tests/trilingual/run_tests.py` 的前提下替换被测模块（before = `.tmp/search-fix/search_before.py` 修复前快照，after = 当前 `lib/search.py`），两份结果跑在同一份库上，可严格对比。
> 命令：`python .tmp/search-fix/run_compare.py --phase before --json .tmp/search-fix/results_before.json`（after 同理）。

### 总览

| 指标 | 修复前 | 修复后 | 变化 |
|---|---|---|---|
| 案例级三语一致通过 | 67 | 67 | 0 |
| 查询数 | 354 | 354 | 0 |
| Top-5 命中 | 342 | 345 | +3 |
| Top-1 命中 | 336 | 339 | +3 |
| Top-5 命中率 | 96.6% | 97.5% | +0.9% |
| Top-1 命中率 | 94.9% | 95.8% | +0.9% |
| 跨国可见 | 72/72 | 72/72 | — |

**按语言（Top-5 命中率）**

| 语言 | 修复前 | 修复后 | 变化 |
|---|---|---|---|
| en | 118/123 = 95.9% | 118/123 = 95.9% | +0.0 pt |
| es | 113/116 = 97.4% | 113/116 = 97.4% | +0.0 pt |
| zh | 111/115 = 96.5% | 114/115 = 99.1% | +2.6 pt |

**解读（关键）**

- **目标 3 条中文查询全部由 0 结果 → Top-1 命中**（`舍曲林`→Sertraline、`氟西汀`→Fluoxetine、`喹硫平`→Quetiapine），且没有出现"命中转失败"或"Top-1 排名下滑"任何一条（回归 0 条、排名变化 0 条）。
- 中文 Top-5 命中率 **96.5% → 99.1%**（+2.6 pt），剩余 1 条失败是 `西格列汀二甲双胍片`（CN 复方成分未拆分，task-14 的 F3，不在本次范围）。
- 案例级通过数不变（67/72）是预期内：这 3 个案例的"品牌名查询"（左洛复/百优解/思瑞康）本来就能通过，case 判定是"每语言至少一条查询命中"；本次修复恢复的是**中文通用名**这一条，属于查询级质量。任务里 72 例全量数字已在此给出。
- en/es 命中率完全不变（+0.0 pt），说明拉丁查询没有回归，符合"只放松中文 contains、不动英文门槛"的设计。

**按分类（案例级通过数）**

| 分类 | 修复前 | 修复后 |
|---|---|---|
| single | 49/49 | 49/49 |
| salt | 6/6 | 6/6 |
| er | 4/4 | 4/4 |
| combo | 4/5 | 4/5 |
| dup_inn | 2/5 | 2/5 |
| zh_only | 2/3 | 2/3 |

### 修复带来的变化（查询级）

**由失败转命中（3 条）**

| 案例 | 语言 | 查询 | 修复前 | 修复后 rank | 修复后 Top-1 |
|---|---|---|---|---|---|
| sertraline | zh | `舍曲林` | 0 结果/未命中 | 0 | Sertraline |
| fluoxetine | zh | `氟西汀` | 0 结果/未命中 | 0 | Fluoxetine |
| quetiapine | zh | `喹硫平` | 0 结果/未命中 | 0 | Quetiapine |

**由命中转为失败（回归，0 条）**

| 案例 | 语言 | 查询 | 修复前 rank | 修复后 Top-1 |
|---|---|---|---|---|
| — | — | — | — | — |

**Top-1 排名变化但仍在 Top-5（0 条）**

| 案例 | 语言 | 查询 | 修复前 rank | 修复后 rank |
|---|---|---|---|---|
| — | — | — | — | — |

### 案例级变化

- 由失败转通过：无
- 由通过转失败：无
- 仍未通过：metformin(combo), ciclosporin(dup_inn), beclometasone(dup_inn), chlorphenamine(dup_inn), diosmectite(zh_only)

**额外证据：2 字「药名片段」从 0 到候选集**（快照库，`.tmp/search-fix/short_cjk_probe.json`；这是本次修复带来的最大可用性提升——用户只记得药名一部分时）：

| 查询 | 修复前 | 修复后 | 修复后 Top-1 |
|---|---|---|---|
| `地平`（钙拮抗剂） | 0 卡 | 25 卡 | Levamlodipine |
| `沙坦`（ARB） | 0 卡 | 25 卡 | Telmisartan |
| `洛尔`（β 阻滞剂） | 0 卡 | 25 卡 | Metoprolol |
| `拉唑`（PPI） | 0 卡 | 25 卡 | Omeprazole |
| `他汀`（他汀类） | 0 卡 | 25 卡 | Simvastatin |
| `列汀`（DPP-4） | 0 卡 | 23 卡 | Sitagliptin |
| `列净`（SGLT2） | 0 卡 | 17 卡 | Empagliflozin |
| `洛韦`（抗病毒） | 0 卡 | 25 卡 | Ganciclovir |
| `泼尼松`（3 字通用名） | 2 卡 | 12 卡 | Prednisone |
| `波依定`/`立普妥`/`万艾可`/`泰诺`（2–3 字品牌，对照） | 17/2/1/10 卡 | 17/2/1/10 卡（不变） | 无回归 |

**解读**：3 条目标查询由 0 结果变为 Top-1 命中；2 字药名片段的候选集从 0 打开到 17–25 张卡；既有 2–3 字品牌的命中数与排序不变，未观察到噪声回归（`头孢` 修复前后都是 25 卡，`diosmectite`/复方等失败属于 task-14 的 F2/F3，不在本次修复范围）。

---

## 5. 残余风险与后续

| 风险 | 等级 | 说明/缓解 |
|---|---|---|
| 2 字中文 contains 候选变多（`地平` 60 keys） | 低 | 站点定位候选集 + `MAX_KEYS=60` + 前端 `contains=0.70`；如需收敛，加 `han && len==2` 微降权（服务端+客户端同步），本次未做 |
| 服务端/客户端两套口径需持续对齐 | 中 | 本次已对齐 `cjk?2:4`；建议后续把 `tier()` 门槛抽成共享常量并在测试里断言两端一致（JS 侧可读同一 JSON 配置），避免再一次漂移 |
| exact 集合内存占用 | 低 | +135k 字符串引用，几 MB；`SearchIndex` 本就全量载入 `_norms` |
| 旧名/别名仍缺（埃索美拉唑、止血环酸） | 中 | 不在本次范围（task-14 F5），修的是"如实告知"；旧名需按 nickname 政策补数据 |
| DB 快照对比的时效性 | 低 | 快照取自修复当天库；后续数据更新后数字会小幅变化，结论方向不变 |

---

## 6. 产物清单

| 文件 | 内容 |
|---|---|
| `lib/search.py` | 修复：exact 校验 + 中文 contains 门槛 2 字（与客户端 v0.2.1 对齐） |
| `lib/test_search_short_cjk.py` | 新增回归测试 10 项 |
| `reports/search-p0-fix.md` | 本报告 |
| `.tmp/search-fix/search_before.py` | 修复前 `search.py` 快照（diff/对比用） |
| `.tmp/search-fix/search_py.diff` | 完整 diff |
| `.tmp/search-fix/repro_before.json` / `repro_after.json` | 真实库修复前后行为记录 |
| `.tmp/search-fix/drugs_snapshot.db` | 对比用 DB 快照（只读来源，非项目数据） |
| `.tmp/search-fix/results_before.json` / `results_after.json` | 72 案例前后完整结果 |
| `.tmp/search-fix/run_before_snapshot.log` / `run_after_snapshot.log` | 对比运行日志 |
| `.tmp/search-fix/unittest_lib.log` / `unittest_etl.log` / `test_short_cjk.log` | 单测日志 |
| `.tmp/search-fix/run_compare.py` | 前后对比运行器（固定快照、替换被测模块，不改测试集本身） |

边界：未写 `data/drugs.db`（修复后验证全部走 `mode=ro` 或快照副本）；未跑 `git`、发布、`site/build.py`；`site/build.py`（客户端 `tier()`）未改。
