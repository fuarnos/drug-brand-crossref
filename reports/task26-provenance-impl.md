# task-26 溯源字段 + 仓库治理文件 — 执行报告

> 日期：2026-10-30（北京 06:0x）｜ 状态：**✅ 已写真实库**（Lead 2026-10-30 批准；schema 迁移 + brand_family 回填）
> 备份：`data/backups/drugs-before-provenance-20261030.db`（419,627,008 B，sha256 `D1A5EF4889E204BBA87C66E4F678CC832ABE2E47FDDF86EAF1EB456447FF5E2C`）
> 决策依据：Lead 2026-10-30「① confidence 枚举 ② v1 不做历史表 ③ 旧行 NULL ④ 与 task-5 合并窗口分开验收 ⑤ 导出归 build 侧」
> 产物：`db/schema.sql`、`db/init_db.py`、`db/migrate_provenance.py`（新）、`etl/provenance.py`（新）、`lib/search.py`（1 处）、`LICENSE`、`CONTRIBUTING.md`、`CITATION.cff`、`docs/数据溯源与许可.md`

---

## 0. 结论

| 项 | 结果 |
|---|---|
| schema | `substance` 与 `brand_family` 各加 **4 个 nullable TEXT**：`source_id / method / confidence / decided_at`；`method` CHECK 4 值、`confidence` CHECK 4 值 |
| 迁移 | `db/init_db.py` 幂等 `ALTER TABLE ADD COLUMN`（照 `_ensure_source_columns` 模式）；真实库 **0.19s**、复跑 0 迁移输出；**体积 +0 字节**（419,627,008 B 不变） |
| 数据 | 行数不变：products **477,098** / components 628,013 / substances **12,649** / brand_family **4**；`quick_check=ok`、`foreign_key_check=0`；`check_data.py` 前后 **115 行逐行一致** |
| 回填 | 只回填 `brand_family` **4 行** → `manual_seed / editorial / high / decided_at`（该表 100% 人工种子，来源可确证）；**`substance` 12,649 行保持 NULL**（按决定 ③ 不伪造） |
| 读取安全 | `lib/search.py:823` 的 `SELECT * FROM substance` → **显式 9 列**；`drug_page()` 返回的 substance 键与迁移前完全一致（9 键，无 provenance 泄漏） |
| 回滚 | `db/migrate_provenance.py --apply`（DROP COLUMN ×8）；副本实测 0.11s、行数不变、`quick ok`，回滚后可再被 `init_db` 重新加列；整库兜底用备份 |
| 治理文件 | `LICENSE`（MIT，明确**不覆盖 data/**）、`CONTRIBUTING.md`、`CITATION.cff`（CFF 1.2.0）、`docs/数据溯源与许可.md`（来源/方法/置信度 + 派生层策略 + non_redistributable 清单） |
| 测试 | `etl` 25/25、`lib` 29/29 通过；未跑 build/publish |

---

## 1. 执行记录

| # | 步骤 | 结果 |
|---|---|---|
| 0 | 备份 | 419,627,008 B；sha256 `D1A5EF48…` |
| 1 | **先改 `lib/search.py`** | `SELECT *` → 显式列（9 列）；`lib` 单测 29/29；`drug_page("atorvastatin")` 冒烟：substance 键 = atc/atc_name/ddd_route/ddd_unit/ddd_value/drug_class/inn_en/inn_zh/substance_id，**无 provenance** |
| 2 | schema + init_db | `db/schema.sql` 两表各加 4 列；`init_db.py` 新增 `_ensure_substance_columns()` / `_ensure_family_columns()` 并在主流程调用；**副本**先跑：8 列一次加完（0.33s），复跑无输出 |
| 3 | 真实库迁移 | `db/init_db.py` → 8 条 `迁移 xxx 表：新增列`，0.19s；复跑幂等；`PRAGMA table_info` 就位 |
| 4 | provenance 回填 | `etl/provenance.py --backfill --apply` → `brand_family` 4 行写入；`--status`：substance 0/12,649、brand_family 4/4；再跑「无需回填」（幂等） |
| 5 | 验数 | 计数不变、quick/FK ok、size 不变；`check_data.py` 前后完全一致 |
| 6 | 治理文件 | LICENSE / CONTRIBUTING / CITATION.cff / docs/数据溯源与许可.md 落盘（纯文件，无库改动） |

## 2. schema 变更（`db/schema.sql`）

```sql
-- substance（末尾新增）
source_id   TEXT,
method      TEXT CHECK (method IN ('rule','multi-source','editorial','imported')),
confidence  TEXT CHECK (confidence IN ('high','medium','low','unknown')),
decided_at  TEXT
-- brand_family 同上 4 列（该表人工维护，method 固定 editorial）
```

`db/init_db.py`：新增两个 helper（`PRAGMA table_info` → 缺列才 `ALTER TABLE ADD COLUMN`），空库建表已带全列、老库自动补列、重复运行无输出。

## 3. `etl/provenance.py`（唯一写入口）

| 接口 | 语义 |
|---|---|
| `mark_substance(con, sid, source_id, method, confidence, decided_at=None) -> bool` | 空才写；已有值按强度提升 `editorial(4) > multi-source(3) > rule(2) > imported(1)`；**同级不覆盖**（保留最早决策） |
| `mark_family(con, fid, ...)` | 同上，用于 `brand_family` |
| CLI `--status` | 覆盖率（已标记 / NULL / method 分布） |
| CLI `--backfill [--apply]` | 只回填 `brand_family`（`manual_seed / editorial / high`，`decided_at` 取种子文件 mtime）；默认 dry-run |
| CLI `--mark <sid> --source ... --method ... --confidence ...` | 单条标记（默认 dry-run，`--apply` 提交） |

## 4. 回滚

```powershell
# 数据级 schema 回滚（DROP COLUMN ×8，默认 dry-run）
& $py db\migrate_provenance.py --apply
# 整库兜底（推荐）
Copy-Item data\backups\drugs-before-provenance-20261030.db data\drugs.db
```

副本实测：8 列全删 **0.11s**、`quick_check=ok`、行数 12,649/4/477,098 不变；回滚后再跑 `init_db` 可重新加列（往返验证通过）。
注意：`init_db` **只加不删**，不能当回滚；DROP 后如需回收体积再 `VACUUM`（本次 +0 字节，不需要）。

## 5. 影响面（已核对）

| 位置 | 影响 | 处理 |
|---|---|---|
| `lib/search.py:823` | `SELECT *` + `dict(sub)` → 新列会泄进 drug_page JSON | **已改显式列**，冒烟确认 9 键无泄漏 |
| `site/build.py`（11 处 `FROM substance`） | 全部显式列 | 不改；数据页如要展示来源另加查询（build 侧） |
| `db/check_data.py` | 只有 `COUNT(*)` | 不改；前后一致 |
| 视图 `collision` / `coverage` | 不引用新列 | 不改 |
| 测试（etl/lib） | 建库语句用显式列；无 `SELECT *` 断言 | 不改；25+29 通过 |
| `db/optimize_indexes.py` | 不重建 substance | 不改 |
| 导出 `site/dist/datapackage.json` | provenance/许可分级段 | **build 侧**（数据侧已提供列与文案） |

## 6. 受影响脚本清单（**本轮未改**，下窗口一次性接 provenance）

新数据要带溯源，需要在下列 15 个写入点各加 1–2 行 `mark_substance()`（或 merge 后用 `mark_family()`）：

| 脚本:行 | 建议 method | confidence | 说明 |
|---|---|---|---|
| `etl/ingest_openfda_ndc.py:244` | imported | high | US NDC |
| `etl/ingest_dmd.py:235` | imported | high | GB dm+d |
| `etl/ingest_ca_dpd.py:470` | imported | high | CA DPD |
| `etl/ingest_pbs.py:260` | imported | high | AU PBS |
| `etl/ingest_tga_cmi.py:126` | imported | high | AU CMI |
| `etl/ingest_artg_details.py:166` | imported | high | AU ARTG 明细 |
| `etl/ingest_cima.py:1334` | imported | high | ES CIMA |
| `etl/ingest_mx.py:293` | imported | high | MX COFEPRIS |
| `etl/ingest_nhsa.py:1653` | imported | high | CN NHSA（含 inn_zh/atc） |
| `etl/merge_cn_substances.py:466` | rule | medium | CN 合并 |
| `etl/merge_es_substances.py:425` | rule | medium | ES 合并 |
| `etl/auto_merge_substances.py:250` | rule | medium | 跨市场合并 |
| `etl/fix_cn_combos.py:245` | rule | medium | 复方拆分 |
| `data/seed_manual.py:168` | editorial | high | 人工种子 |
| `data/seed_families.py:54` | editorial | high | 品牌家族（**已回填**，写入时也应 mark） |

> 本轮只做 schema + 工具 + 回填，不动 15 个 ETL（避免未逐脚本回归就改写入路径）；wiring 建议下一窗口与 task-5（name_lang）合并做、按来源逐个跑 dry-run 验证。

## 7. 非 DB 交付

| 文件 | 内容 |
|---|---|
| `LICENSE` | **MIT**（代码）；明确不覆盖 `data/`、docs 来源内容、站点数据；声明 data/raw、drugs.db、dist 不入库 |
| `CONTRIBUTING.md` | 三条红线、四套测试、数据纪律（许可先行/溯源/俗称不入 product_name/计数口径）、漂移检查、提交规范、issue 模板、许可 |
| `CITATION.cff` | CFF 1.2.0：title/abstract/type=software/license MIT/version 0.9.2/repository；notes 说明数据不随代码许可 |
| `docs/数据溯源与许可.md` | 结论（代码 MIT/数据分级/只发派生层/不等于人工复核）、4 列语义与查询示例、各类数据来源+method+confidence+再发布表、派生层策略表、**non_redistributable 清单**（NHSA/CIMA/COFEPRIS/TGA 正文等）、维护流程、声明 |

## 8. 验收（对照 task-26）

- [x] LICENSE 为 MIT 且声明数据不适用（`LICENSE` 范围说明 4 条）
- [x] 迁移可回滚（`db/migrate_provenance.py`，副本实测）、老库可升级（init_db 幂等，0.19s）
- [x] 导出含 provenance —— **数据列已就位**；`datapackage`/数据页展示归 build 侧（决策 ⑤）
- [x] CONTRIBUTING / CITATION 存在
- [x] 派生层策略写进 `docs/数据溯源与许可.md`（datapackage 由 build 侧加 `non_redistributable` 标记）
- [x] 旧行 NULL 不伪造；`brand_family` 4 行 editorial 回填；quick/FK/计数/check_data 全部一致
- [ ] 新数据 provenance —— **待 wiring 15 个写入点**（§6，下窗口）

## 9. 风险 / 后续

| # | 事项 | 处理 |
|---|---|---|
| 1 | 新数据 provenance 仍为 NULL（ETL 未接线） | 下窗口按 §6 表逐脚本接 `mark_substance()`，每接一个跑 dry-run |
| 2 | `datapackage`/数据页尚未展示 provenance | build 侧（impl）读 DB 4 列；文案「规则自动定案 + 多源交叉 ≠ 人工复核」已备 |
| 3 | 与 task-5（`name_lang`）同窗口 | init_db 已有两份 helper；task-5 迁移只需再加一组列，互不冲突 |
| 4 | `brand_family` 回填的 `decided_at` 取种子文件 mtime（2026-10-25） | 近似值，已在 `docs/数据溯源与许可.md` 说明；如需精确需人工改 |
| 5 | 漂移基线 | schema 变化不影响 `data/raw`，基线无需更新 |

## 10. 证据

| 文件 | 内容 |
|---|---|
| `data/backups/drugs-before-provenance-20261030.db` | 迁移前备份（sha256 `D1A5EF48…`） |
| `.tmp/prov/init_real.txt` / `init1.txt` | 真实库/副本迁移日志（8 条「新增列」） |
| `.tmp/prov/check_before.txt` / `check_after.txt` | check_data 前后（115 行完全一致） |
| `.tmp/prov/drugs.db` | 副本（迁移 → 回填 → 回滚 → 再迁移 往返验证用，可删） |
| `reports/task26-provenance-design.md` | 只读设计方案（决策前的成本/影响实测） |

_本报告为 task-26 执行结果：已迁移真实库并回填 brand_family；substance 旧行保持 NULL；未跑 build/publish，未改 markets/languages。_
