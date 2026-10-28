# 搜索评测集 v3（500+ 例 + RxNorm oracle + CI 门槛）— task-84

> 日期：2026-10-28 · 任务：task-84 · 状态：**评测集扩容 + 外部 oracle + CI 门槛完成**（只写 tests/reports/.tmp；未改 `site/build.py`、未写 `data/drugs.db`、未跑 git/发布）
> 交付：
> - `tests/trilingual/cases_v3.json`（**511 例**，v2 320 + 新增 191）
> - `tests/search_eval/run_ci.py`（CI 门槛：Top-5 ≥ 95%、零结果误命中 = 0）
> - `tests/search_eval/gen_cases_v3.py`（可复现生成器，含 RxNorm 抓取与 DB 结构校验）
> - 证据：`.tmp/search-eval3/{ci_results.json, rxnorm_oracle.json, probe.json, fail_inspect.txt}`
> - 基线（v2，320 例）：`.tmp/search-eval3/v2_baseline.json`

---

## 0. 结论摘要

| 指标 | 结果 |
|---|---|
| 用例总数 | **511**（v2 320 + 新增 191；new_categories 218 含重新验证的 zero 用例） |
| 类别 | 14 类：v2 8 类 + 新增 `es_accent / brand_alias / pinyin_polyphone / jianfan_mixed / combo_brand / who_inn_zh`（`zero_result` 重新验证） |
| 期望来源 | DB 结构（product/name_key/component）+ **RxNorm/RxNav**（英文品牌↔IN 同义词）+ WHO INN 中文名（DB `substance.inn_zh`）+ `normalize_name._T2S` 反表（繁简）+ `build.py` 拼音字表（多音字）；**零结果用 name_key 3-gram/2-gram 反证，不靠检索输出** |
| CI 门槛 | `python tests/search_eval/run_ci.py` → Top-5 ≥ 95%（must_hit 分母）、零结果误命中 = 0；失败退出码 1 |
| **基线（v3，通过）** | **Top-5 380/391 = 97.2%**（门槛 ≥95%）；**零结果 40/40 通过、误命中 0**；Top-1 357/391 = 91.3%；gap 80 例（意外命中 15）；综合 420/431 = 97.5% → **✅ CI 门槛通过** |
| 运行 | 快照 DB（只读，`.tmp/search-eval3/eval-db-snapshot.db`）+ 6 进程：511 例 **373 s**（约 6 分钟） |

---

## 1. 新例配额

| 类别 | n | policy | 期望/oracle | 说明 |
|---|---:|---|---|---|
| es_accent（西语重音） | 40 | must_hit | DB 结构（带重音商品名 → 归一化 name_key 存在 → 该产品成分） | 覆盖 á/é/í/ó/ú/ñ/ü 等；查询原文保留重音 |
| brand_alias（品牌别名） | 46 | must_hit | **RxNorm/RxNav** 品牌→IN + DB 产品成分交叉验证 | 16 例来自 DB US 品牌名经 RxNorm 确认；30 例来自 IN→BN 且 BN 必须存在于 DB 商品名 |
| pinyin_polyphone（多音字） | 25 | gap | DB `substance.inn_zh` + build.py 拼音字表默认读音 | `lib/search.py` 无拼音层（与 v2 pinyin 同类），记 gap 不计入门槛；客户端 JS 有拼音层 |
| jianfan_mixed（繁简混写） | 25 | must_hit | v2 中文查询 + `_T2S` 反表逐字混写；另用 inn_zh 补足 | 验证归一化对混写的鲁棒性 |
| combo_brand（复方品牌） | 30 | must_hit | DB 多成分产品品牌名 → 全部成分 | 覆盖 US/GB/CA/AU/ES 复方品牌名 |
| who_inn_zh（WHO INN 中文名） | 25 | must_hit | DB `substance.inn_zh`（WHO INN 官方中文名）→ substance | 中文界面官方名查询 |
| zero_result（零结果） | 40 | must_empty | name_key 3-gram（拉丁）/2-gram（汉字）反证 + 符号串 | v2 40 例中 27 例因 DB 增长（新增 TW 数据等）失效，按当前 DB 重新验证替换 27 例，保留 13 例 |

v2 类别保持不变：en_typo 45 / es_typo 30 / zh_char_typo 25 / pinyin 40(gap) / jianfan 30 / combo 55 / salt 55 / zero_result（已刷新）。

---

## 2. oracle 来源与许可

| oracle | 用法 | 来源/许可 |
|---|---|---|
| **RxNorm / RxNav** | 英文品牌名 → IN（`rxcui/{id}/related.json?tty=IN`）；IN → BN（`…?tty=BN`） | NLM（美国国立医学图书馆），**美国政府作品/公有领域**；RxNav API 免费、无 key；调用限速 0.2 s，快照 `.tmp/search-eval3/rxnorm_oracle.json`（140 个品牌查询记录，含 rxcui 与 URL） |
| **WHO INN 中文名** | `substance.inn_zh` → 查询期望该 substance | WHO INN 出版物署名 CC BY-NC-SA 3.0 IGO；本评测**只使用名称事实**（药名本身不构成受版权保护的表达），且仅本地测试集、不对外重发布 WHO 内容；站点 About 已按 `docs/许可清单.md` 署名 |
| **DB 结构** | product/product_name/product_component/name_key/name_variant 关系（产品 → 成分集合；重音名 → 归一化键） | 站内自有 DB，只读 `mode=ro` |
| **normalize_name._T2S 反表** | 简体 ↔ 繁体逐字替换，生成混写查询 | 站内归一化实现 |
| **build.py `_PINYIN_CHARS_TEXT`** | 汉字 → 默认拼音（多音字用默认读音） | 站内拼音表（1,582 字） |
| **零结果反证** | 随机串的 3-gram（拉丁）/2-gram（汉字）不在当前 `name_key` 中，符号串 normalize 后不可命中 | DB 结构 + 人工构造；不来自检索输出 |

> 说明：RxNorm 只用于**英文同义词/品牌别名**的 oracle；中文/西语期望仍来自 DB 结构与官方名表；所有期望值在生成时校验过（`name_key` 存在、产品成分可查），不拿检索输出反推。

---

## 3. CI 门槛与用法

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 标准跑法（默认 data/drugs.db，只读；自动并行）
& $py tests/search_eval/run_ci.py
# 输出：控制台分类表 + .tmp/search-eval3/ci_results.json（逐条明细）
# 退出码：0 = 门槛通过；1 = 未通过（可用于本地/谷段自动跑；当前仓库无 GitHub Actions）
```

- 门槛（可覆盖）：`--top5-min 0.95`（must_hit Top-5）、零结果误命中必须 = 0；`gap` 用例不计入通过率，只记录「意外命中」。
- 只读：脚本把 `sqlite3.connect` 拦成 `mode=ro`，复用 `lib/search.py::SearchIndex`（与 v2 runner 同一层，测的是线上检索实现）。
- 并行：`--jobs`（默认 2–6）用 spawn 多进程；DB 正被入库任务写时建议先做快照（本次基线用 `.tmp/search-eval3/eval-db-snapshot.db`，`--db` 指定）。
- 稳定性：用例与 DB 快照绑定（`cases_v3.meta.db_sha256` 记录生成时 DB SHA），DB 更新后应重跑 `gen_cases_v3.py` 刷新期望（尤其 zero_result 与品牌名）。

---

## 4. 基线结果（v3，2026-10-28 13:06，快照 DB）

```
category             n must_hit   Top1   Top5   Top5%  empty    误命中  gap   gap命中
brand_alias         46       46     46     46  100.0%      0      0    0       0
combo               55       40     40     40  100.0%      0      0   15      15
combo_brand         30       30     28     30  100.0%      0      0    0       0
en_typo             45       45     35     41   91.1%      0      0    0       0
es_accent           40       40     37     38   95.0%      0      0    0       0
es_typo             30       30     17     27   90.0%      0      0    0       0
jianfan             30       30     30     30  100.0%      0      0    0       0
jianfan_mixed       25       25     24     25  100.0%      0      0    0       0
pinyin              40        0      0      0    0.0%      0      0   40       0
pinyin_polyphone    25        0      0      0    0.0%      0      0   25       0
salt                55       55     53     55  100.0%      0      0    0       0
who_inn_zh          25       25     24     24   96.0%      0      0    0       0
zero_result         40        0      0      0    0.0%     40      0    0       0
zh_char_typo        25       25     23     24   96.0%      0      0    0       0
```

- **must_hit：Top-5 380/391 = 97.2%**（门槛 ≥95% ✅），Top-1 357/391 = 91.3%；
- **must_empty：40/40 通过；零结果误命中 = 0**（门槛 = 0 ✅）；
- **综合门槛：420/431 = 97.5% ✅**（退出码 0）；
- 新类别（166 例 must_hit）：**Top-5 163/166 = 98.2%**；其中 brand_alias 46/46、combo_brand 30/30、jianfan_mixed 25/25、es_accent 38/40、who_inn_zh 24/25。
- v2 旧类（225 例 must_hit）：Top-5 217/225 = 96.4%（与 v2 基线一致，见 §5）。
- 失败 11 例（Top-5 未命中）：en_typo 4（长商品名/生僻顺势疗法名）、es_typo 3（拼写距离超出容错）、zh_char_typo 1（"输血用枸橼酸纳注射液" 少字 typo 未命中）、es_accent 2（`BICARBONATO SOSA TORRES MUÑOZ` 0 卡片、`MIRTAZAPINA SANDOZ FARMACÉUTICA` 命中错误卡片）、who_inn_zh 1（`多维` 期望 substance 本身为 "多维" 而排第一的是 Multivitamin）。
- 逐条明细：`.tmp/search-eval3/ci_results.json`（含 rank/top1/cards/tier/seconds）。

**数据快照说明**：case 生成时 DB sha `c8fdc7e6…`，评测快照 DB sha `ca9c9885…`（期间其他入库任务仍在写库；zero/brand 已按生成时 DB 结构校验，v2 旧类基线未见回归）。CI 建议在「入库完成、建站前」跑，或用同一快照生成+评测。

---

## 5. 与 v2 对比 / 漂移说明

- v2（320 例，旧 DB 快照）基线：Top-5 **217/225 = 96.44%**，零结果 **40 例中 2 例误命中**（`v2-zero-result-0023/0036`：查询在新增 TW 数据后已能命中 Kanamycin/Povidone-Iodine → 属**用例失效**，不是检索回归）。
- v3 对 zero_result 做了**结构再验证**：v2 40 例中 27 例因 DB 增长（TW/新市场产品名）已不再满足"无 3-gram/2-gram 出现"，已用当前 DB 重新生成 27 例；保留 13 例。→ v3 零结果 **40/40 通过、误命中 0**。
- v2 旧类在 v3 中 Top-5 217/225（96.4%），与 v2 基线完全一致；**新增类别 163/166（98.2%）**把整体 Top-5 拉到 97.2%。
- 差异原因：v2 的 zero 用例是 2026-10-27 DB 快照生成的，DB 之后增长 1.6 万产品（含 TW），旧 zero 用例被"自然命中"；这正说明评测集需要 **与 DB 快照绑定 + 定期重生成**（本报告 §6 建议）。

---

## 6. 缺口与后续

| 缺口 | 说明 | 建议 |
|---|---|---|
| pinyin / 多音字（65 例 gap） | `lib/search.py` 无拼音层（v2 pinyin 40 例 + v3 多音字 25 例均为 gap，不计门槛）；客户端 JS 有拼音 token 懒加载表，CI 未覆盖客户端 | 后续把拼音 token 层下沉到 `lib/search.py` 或加 jsdom 客户端评测；多音字默认读音错误（如「重楼/川芎」）可作为下一轮改进目标 |
| 11 例 Top-5 未命中 | 长商品名/生僻名（en_typo/es_typo/zh_char_typo 多为 v2 既有）、西语长品牌名、WHO INN「多维」等数据/归一化边界 | 分别归因：长名截断/分段、拼写距离阈值、`inn_zh` 含非药名 substance（多维）需数据侧修 |
| 15 例 gap 意外命中 | v2 pinyin/combo gap 用例在 v3 中有 15 例命中（combo gap 全部 15 命中）——说明部分旧 gap 已被搜索覆盖，可转为 must_hit | 下一轮把已命中的 gap 升级为 must_hit，避免永久"免检" |
| DB 漂移 | 无入库冻结时，cases 与评测 DB 可能不同步 | CI 约定：`gen_cases_v3.py` 在 DB 冻结后跑；或评测时用生成时 `db_sha256` 对应的快照（runner 已支持 `--db`） |
| 无 GitHub Actions | 当前仓库无 CI 配置 | 可先用谷段自动跑：`run_ci.py` 退出码非 0 即失败；后续可加 `.github/workflows/search-eval.yml`（需 DB 快照/建站环境，成本高，暂不做） |
| 运行时 | 串行极慢（v2 320 例 19.6 分钟），并行 6 进程 511 例 6.2 分钟 | 默认 `--jobs` 自动；大规模可再分片 |

**复现**：
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 1) 生成/刷新评测集（需联网 RxNorm；DB 冻结后跑）
& $py tests/search_eval/gen_cases_v3.py
# 2) 可选：做只读 DB 快照，避免入库写锁拖慢
& $py .tmp/search-eval3/snapshot.py
# 3) CI 门槛
& $py tests/search_eval/run_ci.py --db .tmp/search-eval3/eval-db-snapshot.db --jobs 6
# 退出码 0 = 通过；JSON：.tmp/search-eval3/ci_results.json
```
