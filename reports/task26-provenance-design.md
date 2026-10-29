# task-26 溯源字段 — 只读设计方案（schema 迁移 + 回滚 + 影响面）

> 日期：2026-10-30（北京 05:5x）｜ 状态：**只读设计，未改 `db/schema.sql` / `db/init_db.py`，未写 `data/drugs.db`**
> 范围：本方案只覆盖 task-26 第 2–4 项（溯源字段 / 导出标记 / 数据溯源文档）；第 1 项 `LICENSE`(MIT) / `CONTRIBUTING.md` / `CITATION.cff` 是纯文件、不涉及库，可同任务直接落。
> 目标：给 `substance` 主名、`brand_family`、映射候选 CSV 加 `source/method/confidence/decided_at`；**规则自动定案 + 多源交叉，不等于人工复核**；对外只发派生层。
> 迁移成本已在**数据库副本**实测（见 §2），真实库未动；写库前需 Lead 批准。

---

## 0. 结论（先看这段）

| 项 | 方案 |
|---|---|
| 表结构 | `substance` 与 `brand_family` 各加 4 个 **nullable TEXT** 列：`source_id`、`method`、`confidence`、`decided_at`；**不重建表**（走 `ALTER TABLE ADD COLUMN`，与 `source`/`variant` 的既有迁移模式一致） |
| 枚举 | `method ∈ {rule, multi-source, editorial, imported}`；`confidence ∈ {high, medium, low, unknown}`（**待 Lead 定**，见 §10） |
| 旧数据 | **保持 NULL，不伪造来源**；文档与数据页文案统一「NULL = 迁移前遗留，来源未记录」 |
| 写入 | 新增 `etl/provenance.py`：`mark_substance()/mark_family()`，只在空时写、按强度提升（editorial > multi-source > rule > imported），同级不覆盖；15 个写入点各加 1–2 行 |
| 映射 CSV | `cross_market_merge_candidates` / `combo_match_candidates` / `cn_inn_overrides` / `es_inn_overrides` / `tw_ingredient_aliases` / `inn_zh_backfill_v2` 加 `source_id/method/decided_at`（`confidence` 已有）；生成脚本同批更新 |
| 实测成本（副本） | ALTER 8 列 **0.36s / +0 字节**；全量回填 12,649 行 **0.03s / +0.7 MB**；`DROP COLUMN` 回滚 **0.11s**，行数不变、`quick_check=ok` |
| 阻塞项（必须先处理） | `lib/search.py:823` 的 `SELECT * FROM substance` + `dict(sub)` 会把新列**泄进 drug_page JSON** → 写库前改成**显式列**（1 行改动，见 §7） |
| 回滚 | ① 备份恢复（推荐）；② `db/migrate_provenance.py --rollback` 用 `DROP COLUMN`（SQLite 3.53 支持，实测可用）；init_db 只加不删，不能作为回滚手段 |
| 与 task-5 协调 | task-5 要给 `substance` 加「主名语言」（`inn_en` 语义 → canonical + name_lang）→ **建议合并为一次迁移窗口**，避免两次 ALTER/两次基线变更 |

---

## 1. 现状（只读实测）

| 表 | 行数 | 现有列 | 谁在写 |
|---|---:|---|---|
| `substance` | **12,649** | substance_id, inn_en, inn_zh, atc, atc_name, drug_class, ddd_value, ddd_unit, ddd_route | 14 个脚本 INSERT、8 个脚本 UPDATE（见 §5） |
| `brand_family` | **4** | family_id, label, note | `data/seed_families.py`（INSERT OR REPLACE） |
| 已有「准溯源」 | — | `source`（license/license_url/data_as_of）、`ingest_run`（每批 rows_in/kept）、`product.source_url/retrieved_at/note` | 各 ingest 自动写 |

- 结论：**批次级溯源已有**（source + ingest_run），缺的是**成分主名级的「这条名字是谁定的、用什么方法、什么置信度、什么时候」**。
- 映射候选 CSV 现状（表头实测）：多数已有 `confidence`/`status`/`evidence`，**缺 `source_id` / `method` / `decided_at`**：

| CSV | 现有相关列 | 生成/维护脚本 |
|---|---|---|
| `cross_market_merge_candidates.csv` | confidence, status, evidence_type, evidence | `etl/build_cross_market_candidates.py` |
| `cross_market_batchB.csv` | confidence, confidence_final, decision, reason, second_evidence | 同上（batch B 产物） |
| `combo_match_candidates.csv` | match_strength, overlap_ratio | `etl/build_combo_matches.py` |
| `cn_inn_overrides.csv` | confidence, status, reason, evidence_url | 人工种子（`data/`） |
| `es_inn_overrides.csv` | confidence, status, reason, evidence | 人工种子 |
| `tw_ingredient_aliases.csv` | confidence, status, evidence | `etl/build_tw_aliases.py` |
| `inn_zh_backfill_v2.csv` | confidence, evidence, source_url, status | `etl/build_inn_zh_backfill.py --v2` |
| `salt_base_fraction.csv` | source, status, note（已有 source） | `etl/apply_salt_fractions.py` |

## 2. 副本实测（迁移成本，真实库未动）

```powershell
# 副本实验（已做，副本已删；可复现）
Copy-Item data\drugs.db .tmp\prov-design\drugs.db
& $py -c "<见 §2 结果；ALTER/UPDATE/DROP 三段>"
```

| 步骤 | 耗时 | 体积变化 | 结果 |
|---|---:|---:|---|
| ALTER 8 列（substance 4 + brand_family 4） | **0.36s** | **+0 B**（SQLite 仅改元数据，NULL 不进记录体） | `PRAGMA table_info` 就位 |
| 回填 12,649 行（模拟日后全量回填） | **0.03s** | **+720,896 B（+0.69 MB）** | 行数不变 |
| `DROP COLUMN` ×8（回滚） | **0.11s** | 列消失、行数 12,649 不变 | `quick_check=ok`、FK 0；freelist 变大（可 VACUUM） |

> 结论：**迁移本身是秒级、零体积**；真正的成本在「15 个写入点 + 1 处 SELECT * + 文档/数据页」，不在 DB。

## 3. 字段设计

```sql
-- db/schema.sql（substance / brand_family 两处）
source_id   TEXT,      -- 主名决策来源（对应 source.source_id；不加 FK：source 行可能后补/合并）
method      TEXT CHECK (method IN ('rule','multi-source','editorial','imported')),
confidence  TEXT CHECK (confidence IN ('high','medium','low','unknown')),
decided_at  TEXT,      -- ISO8601（UTC），决策时间；不是抓取时间
```

| 列 | 语义 | 允许 NULL 的理由 |
|---|---|---|
| `source_id` | 主名/合并决策的**主来源**（如 `nhsa`、`openfda_ndc`、`manual_seed`） | 旧行无记录（12,649 行全部 NULL 起步） |
| `method` | `imported`=来源直接导入；`rule`=规则推导（合并/解析）；`multi-source`=多源交叉一致；`editorial`=人工种子/编辑决定 | 同上；**注意**：`editorial` 只表示「人工种子文件」，仍不等于逐条人工复核 |
| `confidence` | 对**这条主名**的置信度（high/medium/low/unknown） | 同上 |
| `decided_at` | 决策时间（ISO8601 UTC），用于审计与排序 | 同上 |

- **不加索引**（暂无按 provenance 过滤的查询；如数据页要按来源筛，再加 `idx_substance_source`，成本同样秒级）。
- `variant` / `product` / `name_key` 本轮**不加**（task 要求只到主名层）；产品级溯源已有 `source_id/source_url/retrieved_at`。

## 4. 迁移方案（init_db 幂等，不重建表）

1. `db/schema.sql`：在 `substance`、`brand_family` 的 CREATE TABLE 里加 4 列（空库直接建全）。
2. `db/init_db.py`：新增两个 helper，模式照抄现成的 `_ensure_source_columns` / `_ensure_variant_columns`：

```python
def _ensure_substance_columns(db):
    have = {r[1] for r in db.execute("PRAGMA table_info(substance)")}
    for name, ddl in (
        ("source_id", "TEXT"),
        ("method", "TEXT CHECK (method IN ('rule','multi-source','editorial','imported'))"),
        ("confidence", "TEXT CHECK (confidence IN ('high','medium','low','unknown'))"),
        ("decided_at", "TEXT"),
    ):
        if name not in have:
            db.execute(f"ALTER TABLE substance ADD COLUMN {name} {ddl}")
            print(f"迁移 substance 表：新增列 {name}")
    db.commit()
# brand_family 同理
```

3. 在主流程里调用（空库建表后也会走一遍：`have` 已包含四列 → 不输出）。
4. **不做表重建**：不碰 `product.country` CHECK、不动视图（`collision`/`coverage` 只引用 `substance_id`/`substance` 的既有列）。
5. 幂等验证：连续跑两次 `db/init_db.py`，第二次 0 输出、`PRAGMA table_info` 稳定。

## 5. 写入口与合并策略

新增 `etl/provenance.py`（唯一写口，避免 15 处各写各的）：

```python
METHOD_RANK = {"imported": 1, "rule": 2, "multi-source": 3, "editorial": 4}

def mark_substance(con, sid, source_id, method, confidence, decided_at=None) -> bool:
    """只在空时写；若已有，method 强度更高才覆盖（同级保留最早，不覆盖）。"""
```

| 脚本（14 个 INSERT + 相关 UPDATE） | 建议 `method` | 建议 `confidence` |
|---|---|---|
| `ingest_openfda_ndc` / `ingest_dmd` / `ingest_ca_dpd` / `ingest_pbs` / `ingest_tga_cmi` / `ingest_cima` / `ingest_mx` / `ingest_nhsa` / `ingest_artg_details` | `imported` | `high`（来源直给 INN 名） |
| `merge_cn_substances` / `merge_es_substances` / `auto_merge_substances` / `fix_cn_combos` | `rule` | `medium`（合并规则推导） |
| 同一 substance 被第二个来源命中 | 提升为 `multi-source` | `high`（两源一致） |
| `data/seed_manual.py` / `data/seed_families.py` | `editorial` | `high`（人工种子文件，逐条有出处） |
| `apply_inn_zh` / `build_inn_zh_backfill`（只改 `inn_zh`） | `editorial`/`rule`（按 CSV 的 confidence 映射） | 沿用 CSV |

- **多源交叉表达**：不新增历史表，`source_id` 记主来源、`method='multi-source'` 表示「至少两源一致」；如需逐源明细，v2 再加 `substance_provenance` 历史表（本方案预留，不实现）。
- **不覆盖原则**：同 rank 不覆盖（保留最早决策），高 rank 可覆盖低 rank；`decided_at` 随覆盖更新。

## 6. 映射候选 CSV 的 provenance

加 3 列（`source_id, method, decided_at`）到 §1 表中的 6 个 CSV；`confidence` 已有则复用。规则：
- 由脚本生成的行：生成时写 `source_id`（生成脚本对应的 source）、`method='rule'`、`decided_at`=生成时间；
- 人工种子行：`method='editorial'`、`decided_at`=该行加入日期（可按文件 mtime 或手填）；
- 影响：文件 sha 变化 → `drift_check` 的「文件 sha 变化」只会记提示（不告警），并需重生成基线（Lead 批准后 `--force`）。

## 7. 影响面（读/写/导出）

| 位置 | 影响 | 处理 |
|---|---|---|
| **`lib/search.py:823`** | `SELECT * FROM substance` + `dict(sub)` → 新增 4 列会进 `drug_page()` 返回 JSON（API/页面数据泄漏） | **写库前改成显式列**（`substance_id, inn_en, inn_zh, atc, atc_name, drug_class`）或显式暴露 provenance；1 行改动 + 回归 |
| `site/build.py`（11 处 `FROM substance`） | 全部是显式列（已核对） | 不改；数据页如要展示来源，另加显式查询 |
| `db/check_data.py` | 只有 `COUNT(*) FROM substance` | 不改 |
| `views: collision / coverage` | 只引用 `substance_id` / variant 关联 | 不改 |
| `tests`（lib/etl） | 建库语句用显式列 `INSERT INTO substance (substance_id, inn_en, inn_zh)`；无 `SELECT *` 断言 | 不改（新增列 nullable，插入不受影响） |
| `db/optimize_indexes.py` | 只做统计/索引，不重建 substance | 不改 |
| 导出 `site/dist/datapackage.json` | 已由 build 生成；provenance 段/许可分级要加在 build 侧 | **build 侧任务**（data 侧提供列与文案）；不在本方案写范围 |
| 老库升级 | 12,649 行加 0 字节；`vacuum` 不需要 | — |

## 8. 回滚方案

| 方案 | 操作 | 适用 |
|---|---|---|
| **A. 备份恢复（推荐）** | 写库前 `Copy-Item data\drugs.db data\backups\drugs-before-provenance-<ts>.db`；回滚=覆盖回来 | 任何失败；schema+数据一起回 |
| B. `DROP COLUMN` 脚本 | `db/migrate_provenance.py --rollback`（按 `PRAGMA table_info` 存在才删，先删后加的反序）；实测 0.11s，行数不变、`quick_check=ok`；回滚后 `db/schema.sql` 也要退回、`init_db` 重跑不重建 | 只想撤 schema、保留数据 |
| C. init_db | ❌ 只加不删，**不能**回滚 | — |

回滚后建议 `VACUUM`（DROP COLUMN 会留 freelist，实测 +0.69 MB 未回收）。

## 9. 验收清单（写库窗口时逐项勾）

- [ ] 副本：`init_db` 两次幂等（第二次 0 迁移输出）；`PRAGMA table_info(substance)` 含 4 列、`brand_family` 含 4 列
- [ ] 副本：行数不变（substance 12,649 / brand_family 4）；`check_data` 计数与迁移前一致；`quick ok` / `FK 0`
- [ ] 副本：全量回填实验（12,649 行 +0.7 MB、0.03s）→ 回滚（0.11s）→ 列消失、行数不变
- [ ] `lib/search.py` 改显式列后：`drug_page` JSON 不再带 provenance 键（或按设计显式暴露）；`tests/trilingual` 通过
- [ ] 迁移后 DB 体积记录（初始 +0；回填后 +0.7 MB）
- [ ] 新 ingest 抽 1 个来源（如 HK/ARTG）→ 新行 `method/confidence/decided_at` 非空；旧行仍 NULL
- [ ] 映射 CSV 重生成后含 3 列；`drift_check` 只提示 sha 变化（不告警）
- [ ] 文档：`docs/数据溯源与许可.md`（来源/许可/方法/置信度 + 「≠人工复核」声明）；`datapackage` 的 non_redistributable 分级（build 侧）

## 10. 需 Lead 决定

1. **`confidence` 口径**：`high/medium/low/unknown`（建议）还是 0–1 数值？（本项目其它表已用 `high/medium/low` 风格，建议枚举）
2. **是否要「多源明细」历史表**（`substance_provenance`：每源一行，可追溯多源交叉）？建议 v1 不做（`method='multi-source'` 足够），v2 再评估。
3. **旧行回填**：建议 NULL + 文档说明（不伪造）；若要求「全库都有值」，只能写 `method='imported', confidence='unknown'` 并注明无法核验（不推荐）。
4. **是否与 task-5（`substance` 主名语言）合并一次迁移**：合并可少一次 ALTER/基线变动，但两任务验收耦合；建议**合并窗口、分开验收**。
5. **`datapackage` / 数据页的 provenance 展示与 non_redistributable 分级**属 build 侧（`site/build.py` 已生成 `site/dist/datapackage.json`）——由 build 任务做还是 data 侧提供数据文件？

## 11. 附：迁移脚本草案（写库窗口才落地）

```sql
-- schema.sql（substance / brand_family）
source_id TEXT,
method TEXT CHECK (method IN ('rule','multi-source','editorial','imported')),
confidence TEXT CHECK (confidence IN ('high','medium','low','unknown')),
decided_at TEXT
```

```powershell
# 窗口步骤（获批后）
Copy-Item data\drugs.db data\backups\drugs-before-provenance-20261030.db
Copy-Item data\drugs.db .tmp\prov\drugs.db
& $py db\init_db.py --db .tmp\prov\drugs.db       # 副本升级 + 幂等验证
& $py db\check_data.py                            # 真实库基线（只读）
& $py db\init_db.py                               # 真实库升级
& $py db\check_data.py; & $py -c "..."            # quick/FK/体积
# 回滚（如需）
& $py db\migrate_provenance.py --rollback --db data\drugs.db
```

_本方案为只读设计：未改 `db/schema.sql`、`db/init_db.py`、`data/drugs.db`，未跑 build/publish。写库前请 Lead 批准并确认 §10 五项。_
