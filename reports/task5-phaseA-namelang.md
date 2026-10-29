# task-5 Phase A：`name_lang` 迁移 — 执行报告

> 日期：2026-10-30（北京 07:5x）｜ 状态：**✅ 已写真实库**（Lead 批准 Phase A；本轮**不改任何名字**、不做身份合并）
> 备份：`data/backups/drugs-before-namelang-20261030.db`（419,627,008 B，sha256 `5448D3D6397D749197AB4B4B000CCAAC4560D2CD0FEA4CCFEBF7942DCE8F7A9D`）
> 决策：Lead 2026-10-30 —— ①本轮 Phase A + Wikidata 只读候选并行；②不做合并；③`name_lang` 5 值；④fallback 四语文案；⑤15 个 mark 同窗口分开验收
> 边界：**不跑 build/publish**；Wikidata 批只读、只写 `.tmp/task5/`

---

## 0. 结论

| 项 | 结果 |
|---|---|
| schema | `substance` 新增 **`name_lang TEXT CHECK (name_lang IN ('en','zh','zh-Hant','es','other'))`**（空库建表带全列；老库 `ALTER TABLE ADD COLUMN`） |
| 回填 | **12,649 行全部回填**：`zh` **1,791**（主名含 CJK）/ `en` **10,858**；**无 NULL**；`name_lang` 与 CJK 检测**逐行一致**（CJK 但非 zh = 0；非 CJK 但 zh = 0） |
| 迁移成本 | 副本 **0.28s**；真实库 **2.10s**（含 product 等表检查）；DB 419,627,008 → **419,799,040 B（+172,032 B / +0.16 MB）** |
| 完整性 | `quick_check=ok`、`foreign_key_check=0`；products **477,098** / components 628,013 / substances **12,649** 不变；`check_data.py` 前后 **115 行逐行一致** |
| 幂等 | 第二次 `init_db` **无迁移/回填输出**（0 行变更） |
| 名字 | **未改任何 `inn_en`/`inn_zh`**——本轮只加语言标记；映射（含合并）留下一窗口按规则做 |
| Wikidata 批 | 已启动（只读、A10 优先、3s 间隔、429 退避、断点续跑）；**外部源当前限流**（见 §3），候选数见消息/§3 |

---

## 1. 迁移执行

| # | 步骤 | 结果 |
|---|---|---|
| 0 | 备份 | 419,627,008 B；sha256 `5448D3D6…` |
| 1 | `db/schema.sql` | `substance` 末尾加 `name_lang`（CHECK 5 值）+ 注释（回填规则） |
| 2 | `db/init_db.py` | 新增 `_ensure_substance_name_lang()`：缺列才 `ALTER`；只回填 `name_lang IS NULL` 的行（CJK 正则 → `zh`，其余 `en`）；主流程调用 |
| 3 | 副本 dry-run | `.tmp/task5/drugs-copy.db`：`迁移 substance 表：新增列 name_lang` + `回填 12,649 行（zh 1,791 / en 10,858）`，0.28s；复跑无输出；quick/FK ok |
| 4 | 真实库 | `db/init_db.py` → 同上两条输出，**2.10s**；复跑幂等 |
| 5 | 验数 | `name_lang` 分布 `{'en': 10858, 'zh': 1791}`；CJK 行 1,791 全部 `zh`（不一致 0）；NULL 0；quick ok / FK 0 |
| 6 | check_data | 前后各 115 行，**完全一致** |

**回填规则（确定性，不看外部源）**：`inn_en` 含 CJK（`[\u3400-\u9fff\uf900-\ufaff]`）→ `zh`；否则 `en`。非 ASCII 的西语名（如 `Insulina Isófana`）按规则归 `en`（本轮不细分 es，`es` 值留给未来有明确西语主名的数据）。

## 2. 与 task-26 provenance 的关系（同窗口、分开验收）

- 同一 `init_db` 主流程：`_ensure_substance_columns`（provenance 4 列）→ `_ensure_family_columns` → **`_ensure_substance_name_lang`**（本任务）→ `_ensure_indexes`。
- 分开验收：task-26 已在上一轮验收（8 列 + brand_family 回填）；本轮只验收 `name_lang`（列/回填/幂等/check_data 一致）。
- 15 个 `mark_substance()` 接入仍按 `reports/task26-provenance-impl.md` §6 清单，与下一窗口映射批一起做（分开验收），本轮未动。

## 3. Wikidata 只读候选批（并行，状态）

- 脚本：`.tmp/task5/wikidata_batch.py`（只读 DB；输出 `.tmp/task5/wikidata_candidates.csv`，增量可续跑；A10 优先；3s 间隔；429 退避 120s×n，连续 3 次自动停并保留进度）。
- **限流实测（重要）**：
  - `wbsearchentities`（搜索 API）：连续请求后 **HTTP 429**；单次探测可恢复（阿司匹林 → aspirin OK），说明是**突发限流**而非封禁。
  - `query.wikidata.org`（WDQS）：返回 **“Aggressively rate-limiting to 1 req / min - this rule was created during active wdqs outage”** → **本轮不可用**（1,791 条需 30 小时）。
- 实际尝试：换「搜索 API + 5s 间隔 + 429 退避」后仍被限流，**本窗口只跑完 29 / 1,791 条（0 命中、0 错误、29 miss）**，其中 A10 已尝试 19 条（全部 miss）；随后按预案停止（保留进度，可续跑）。
- 抽样验证：`司美格鲁肽 → semaglutide (Q27261089)` 命中，说明搜索可用；但 `德谷胰岛素` 在 zh / zh-hans / zh-cn 三个语言参数下均 0 命中（Wikidata 无对应中文标签），说明**大量 CN 注册名在 Wikidata 没有中文 label**，即使跑满 1,791 条，A10 这类 CN 新药的命中率也接近 0。
- 结论：**Wikidata 批本窗口不可行**（限流 + 低产出）。候选口径以本地多源为准：**unique 50（其中 ATC-4 严格校验 8）**；表在 `.tmp/task5/candidates.csv`。后续如要做，建议：① 低速率（1 请求/10s，跨窗口续跑，约 5h）；或 ② 用 zhwiki sitelinks/导出快照做离线匹配（需另设计）；③ 先按用户口径 fallback 上线（不阻塞）。
- 候选使用规则（下一窗口，本轮不入库）：**唯一 + ATC 类一致（5 位）+ 盐型处理正确** 才自动定案；`inn_en` 已在库的候选走「合并」需 manifest 回滚（本轮按决定②**不做合并**）。

## 4. fallback 四语文案（已确认，交 build 侧）

| locale | 文案 |
|---|---|
| en | `No English name recorded` |
| es | `Sin nombre en español` |
| zh | `无中文名` |
| zh-Hant | `無中文名` |

规则（task-5 B，build 侧实现）：非中文 locale 遇到 `name_lang='zh'` → 显示中文原名 + 上表角标；zh/zh-Hant 遇到 `name_lang='en'` 且无中文名 → 显示 INN + 无中文名角标；**不机器翻译、不音译**；角标 title 说明「原文为来源注册名，未找到官方译名」。

## 5. 验收清单

- [x] `substance.name_lang` 列存在（CHECK 5 值），`PRAGMA table_info` 可见
- [x] CJK 主名 1,791 → `zh`；其余 10,858 → `en`；**无 NULL**；逐行一致
- [x] 名字未改（`inn_en`/`inn_zh` 全部原样）
- [x] `init_db` 幂等（二次运行无输出）；老库可直接升级
- [x] 计数不变、`check_data` 前后一致、`quick ok`、`FK 0`
- [x] 体积记录（+172,032 B）；备份 sha256 记录
- [x] 回滚：备份恢复（`Copy-Item`）；如需只回退列，可扩展 `db/migrate_provenance.py` DROP `name_lang`（脚本已支持按存在列删除，加一行即可）
- [ ] build 侧四语角标（task-5 B）—— 归 build/发布任务
- [ ] 映射批（Phase B）与 15 个 mark 接入 —— 下一窗口

## 6. 风险

| # | 风险 | 说明/处置 |
|---|---|---|
| 1 | `name_lang='en'` 中混入西语/其他非 CJK 主名（如 `Insulina Isófana`） | 本轮规则只区分 CJK/非 CJK；如需要精确 es 需数据源侧支持，已在 §1 注明 |
| 2 | Wikidata 限流 | 已降速 + 退避 + 断点续跑；WDQS 本轮不可用（1 req/min） |
| 3 | 映射批若做合并会改 identity | 本轮决定不做；下一窗口需 manifest + 副本验证 |
| 4 | build 侧未适配前，A10 页仍显示无标注中文 | 归 build 任务（Phase A 已提供 `name_lang` 数据） |

## 7. 证据

| 文件 | 内容 |
|---|---|
| `data/backups/drugs-before-namelang-20261030.db` | 迁移前备份（sha256 `5448D3D6…`） |
| `.tmp/task5/init_real.txt` | 真库迁移日志（新增列 + 回填 12,649 行） |
| `.tmp/task5/check_before.txt` / `check_after.txt` | check_data 前后（115 行一致） |
| `.tmp/task5/drugs-copy.db` | 副本（dry-run 用，可删） |
| `.tmp/task5/candidates.csv` / `a10.csv` / `stats.json` | 本地多源候选（只读，1,791 行） |
| `.tmp/task5/wikidata_batch.py` / `wikidata_candidates.csv` | Wikidata 慢速批（只读、可续跑） |

_本报告为 Phase A 执行结果：已迁移真实库并回填 name_lang；未改名字、未做合并、未跑 build/publish。Wikidata 候选批在后台继续，候选数见 Lead 消息。_
