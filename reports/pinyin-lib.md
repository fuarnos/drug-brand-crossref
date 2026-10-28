# 拼音层下沉到 lib/search（task-111）

> 日期：2026-10-28 · 任务：task-111 · 状态：**实现 + 评测集成完成**（只改 lib/tests/reports/.tmp；未改 `site/build.py`、未写 DB、未跑 git/发布）
> 目标：把客户端 app.js 的拼音归一（1,582 字表 + s:/j:/i: token）移植进 lib，补多音字候选，让 CLI/tests/CI 也能命中拼音查询；客户端行为保持不变。
> 交付：`lib/pinyin.py`（新）、`lib/search.py`（拼音候选分支）、`tests/test_pinyin_lib.py`（11 项单测）、`tests/gen_pinyin_lib.py`（字表生成器）、`tests/search_eval/run_ci.py --gate-pinyin`（可选严格门槛）、本报告
> 证据：`.tmp/pinyin-lib/{ci_after.json, bench.json, probe.py}`、`.tmp/pinyin-lib/gen_pinyin_lib.py`

---

## 0. 结论摘要

| 指标 | 之前（task-84） | 之后（task-111） | 变化 |
|---|---:|---:|---|
| cases_v3 pinyin 40 例（gap 命中） | 0 / 40 | **34 / 40 (85.0%)** | **+34** |
| cases_v3 pinyin_polyphone（多音字）25 例 | 0 / 25 | **20 / 25 (80.0%)** | **+20** |
| 拼音类合计 | **0 / 65** | **54 / 65 (83.1%)** | **+54** |
| must_hit Top-5（门槛指标） | 380/391 = **97.2%** | 380/391 = **97.2%** | **不降** ✅ |
| 零结果误命中 | 0 / 40 | 0 / 40 | 不变 ✅ |
| CI 综合门槛（420/431 = 97.5%） | 通过 | 通过（退出码 0） | ✅ |
| 全量 511 例运行时间 | 373.1 s | **345.3 s（-7.5%）** | 拼音命中后不再走昂贵的模糊扫描 |
| 站点 payload 体积 | — | **0 增量**（lib 不进 dist；build.py 未改） | ✅ |
| 单测 | — | 新增 11 项通过；lib 既有 29 项通过 | ✅ |

**可选严格门槛**：`run_ci.py --gate-pinyin` 把 65 例拼音 gap 升为 must_hit 后，Top-5 = (380+54)/(391+65) = **434/456 = 95.2%**（≥95%，但余量很小）→ 可作为下一轮目标，默认门槛仍按原口径（不升格），保证与 task-84 数字可比。

---

## 1. 实现

### 1.1 `lib/pinyin.py`（新，19,722 B）

- **字表**：从 `site/build.py::_PINYIN_CHARS_TEXT` 快照 1,582 字（默认读音），与客户端同源；改动字表后重跑 `python tests/gen_pinyin_lib.py`（生成器会重新提取）。
- **token 口径**（与客户端 `_pinyin_tokens` 完全一致，polyphone=False）：
  汉字→默认读音；ASCII 字母数字按单字符；生成 `s:<音节>`、`j:<连写>`、`i:<首字母>`；长度 1 只有 `s:`。
- **多音字候选（lib 超集）**：`POLYPHONE_EXTRA` 约 50 个药名常见多音字（重 zhong/chong、参 shen/can、柏 bai/bo、薄 bao/bo、阿 a/e、枸 gou/ju、藏 cang/zang…）；`pinyin_tokens(polyphone=True)` 对每个多音字位置替换额外读音，最多 8 个变体，生成对应的 s:/j:/i: token。客户端仍只用默认读音（行为不变）。
- **查询归一**：`compact_query()`（小写 + 仅 ASCII 字母数字，对应客户端 compact）/ `query_tokens()`（优先级 j > i > s，对应 app.js:3123 的 `j: || i: || s:`）。

### 1.2 `lib/search.py`（拼音分支）

| 位置 | 改动 |
|---|---|
| imports | 新增 `from pinyin import compact_query, is_cjk_text, pinyin_tokens, query_tokens`（lib 目录加入 sys.path） |
| 常量 | `TIER["pinyin"] = 0.62`（contains 0.70 与 fuzzy 0.55 之间）；`PINYIN_MAX_KEYS = 300` |
| `__init__` | 新增 `self._pinyin_index = None`、`self.pinyin_build_ms`（**懒构建**，不增加冷启动） |
| `_get_pinyin_index()` | 首次拼音查询时扫描汉字 name_key（28,255 个）→ token → key_id；多音字开启。本机 **339.9–519.6 ms**，59,358 token / 261,018 绑定 |
| `_pinyin_keys()` | 先按 j→i→s 精确 token 查找（客户端口径）；再补 **全拼前缀兜底**（仅 `j:`，≥3 字母，如 `buluofen` → 布洛芬片）；返回 ≤300 key_id |
| `_resolve_keys()` | **仅当拉丁查询在 name_key 上零命中**时走拼音候选（客户端顺序：精确/前缀 → bigram → 拼音 → 拼写容错；lib 无 bigram，故拼音在 fuzzy 前）；一旦拼音命中则跳过 fuzzy 扫描；`order` 加 `pinyin` |

### 1.3 客户端行为不变

- `site/build.py` **零改动**（未 commit/发布）；客户端仍 fetch `data/idx/pinyin.json`（构建产物），拼音层逻辑照旧。
- 本层只服务 lib/CLI/tests/CI；`lib/` 不进入站点 dist，**页面 payload 变化 0**。
- 客户端与 lib 的默认 token 口径由单测 `test_token_parity` / `test_table_sync_with_build_py` 锁定；多音字/前缀兜底是 lib 超集（浏览器行为不变）。

---

## 2. 体积 / 性能

| 项 | 数值 |
|---|---|
| `lib/pinyin.py` | 19,722 B（源码，不随站点发布） |
| 新增站点 payload / 数据文件 | **0**（无新 dist 文件、pinyin.json 未变） |
| SearchIndex 冷启动 | 191–334 ms（与之前同量级；拼音索引懒构建，不在冷启动内） |
| 拼音索引首次构建 | 339.9–519.6 ms（2.8 万汉字 key；59,358 token / 261,018 绑定） |
| 拼音查询（CI 内命中例，6 进程并行） | p50 **0.55 s** / p90 0.62 s（含每 worker 一次索引构建与快照 DB IO） |
| 拼音查询未命中（回落 fuzzy） | p50 **3.96 s**（对 16.5 万 name_key 做 SequenceMatcher，既有慢路径） |
| 全量 511 例 CI | 373.1 s → **345.3 s（-7.5%）**：54 例从"零命中→fuzzy 全表扫描"变成"token 命中直接返回" |

> 性能注意：未命中拼音串仍会走既有 fuzzy 兜底（单例 4–6 s）。本轮不优化该路径（属既有检索层行为）；后续可把 fuzzy 改为索引/短名单候选。

---

## 3. 评测对比（cases_v3，快照 DB `.tmp/search-eval3/eval-db-snapshot.db`）

| 指标 | task-84 基线 | task-111 之后 |
|---|---:|---:|
| pinyin gap 命中 | 0 / 40 | **34 / 40** |
| pinyin_polyphone gap 命中 | 0 / 25 | **20 / 25** |
| 拼音合计 | 0 / 65 | **54 / 65（83.1%）** |
| must_hit Top-5 | 380/391（97.2%） | **380/391（97.2%，不降）** |
| Top-1 | 357/391（91.3%） | 357/391（91.3%） |
| 零结果 | 40/40，误命中 0 | **40/40，误命中 0** |
| gap 意外命中 | 15 | **69**（+54 = 拼音命中） |
| 综合 | 420/431（97.5%） | **420/431（97.5%）** |
| 运行时间 | 373.1 s | **345.3 s** |

- 逐条明细：`.tmp/pinyin-lib/ci_after.json`（after）与 `.tmp/search-eval3/ci_results.json`（before）。
- 未命中 11 例示例：`syn`（期望 Insulin Glargine，检索返回 25 张无关卡）、`qusilüanpian` / `yansuanlü…`（查询串含表外字/拼写偏差）、`aishengte`/`ast`（v2 gap 用例本身期望为空/族名）等；见 §5。
- 可选严格门槛：`--gate-pinyin` 下 Top-5 = 434/456 = **95.2%**。

---

## 4. 测试

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m unittest tests.test_pinyin_lib -v     # 11 项：表同步/口径/多音字/检索/不回归
& $py -m unittest discover -s lib -t lib       # 既有 29 项，OK
& $py tests/search_eval/run_ci.py --db .tmp/search-eval3/eval-db-snapshot.db --jobs 6
# 可选严格门槛（拼音升 must_hit）：
& $py tests/search_eval/run_ci.py --db .tmp/search-eval3/eval-db-snapshot.db --gate-pinyin
```

新增单测 `tests/test_pinyin_lib.py`：
- 表同步（与 `site/build.py::_PINYIN_CHARS_TEXT` 抽样比较）；
- token 口径（布洛芬 → s:bu/s:luo/s:fen/j:buluofen/i:blf；泰诺；单字）；
- query_tokens 优先级；多音字（阿胶 a/e、重 zhong/chong）；compact；
- SearchIndex：buluofen / blf / 带空格拼音命中中文 key；英文 `lipitor` 仍 exact 且无 pinyin tier；无意义串不产生 pinyin tier。

---

## 5. 剩余缺口

| 缺口 | 说明 | 建议 |
|---|---|---|
| 11/65 拼音用例仍 miss | ① 查询串含 **表外字**（1,582 字表只覆盖索引出现过的字）或拼写偏差；② v2 少量 gap 用例期望本身是族名/空；③ 短首字母 token（如 `syn`）一对多，排序靠 n_products，可能把目标挤出 Top-5 | 补表外字读音（从 DB 汉字全集补表，需同步 build.py 或仅 lib 用）；对短 token 加「成分名优先」排序 |
| 客户端别名拼音未移植 | 客户端 pinyin.json 含 **俗称/旧名**（encode_pinyin 用 alias label）→ lib 只做 name_key；CLI/测试查俗称拼音仍 miss | 若需要，从 DB `alias_all` 生成 token（注意别名→substance 不是 name_key，需挂在成分卡上） |
| 多音字覆盖有限 | 约 50 个常用字手工表；表外多音字仍默认读音；客户端保持默认读音 | 可引入 pypinyin 之类的读音表做生成期扩展（需评估依赖/体积），或继续按需补表 |
| 前缀兜底仅 j: | 首字母前缀（如 `bl`）不支持，避免过泛；与客户端一致 | 视真实查询日志再评估 |
| 未命中路径慢 | 拼音未命中的纯拉丁串仍走 16.5 万 key 的 fuzzy 扫描（4–6 s/例） | 改为 trigram 短名单 + 编辑距离（客户端 v0.5.0 已有类似层），下一任务 |
| 站点仍用客户端拼音 | 本轮只下沉 lib；浏览器仍用 pinyin.json（行为不变） | 若未来做服务端 API/SSR，直接用 lib 层；站点端到端拼音评测可用 jsdom 对拍 |

---

## 6. 发布注意

- **无需重建站点**：本任务未改 `site/build.py` 与任何 dist 数据；站点行为/体积不变。若后续把 lib 层用于 API/SSR 再评估。
- **字表同步**：`lib/pinyin.py` 是构建侧 `_PINYIN_CHARS_TEXT` 的快照；`site/build.py` 拼音表变化时跑 `python tests/gen_pinyin_lib.py`，单测会因不同步而失败（提醒）。
- **门槛口径**：默认 `run_ci.py` 仍按 task-84 口径（pinyin gap 不计入）；`--gate-pinyin` 为可选严格模式，当前 95.2%（余量小，建议补齐 11 例后再切换）。
- 未改 DB / build.py；未 git/发布。
