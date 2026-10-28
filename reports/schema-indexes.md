# schema / init_db 落地 2 个索引（2026-10-28）

> 任务：task-57（schema/init_db 落地 `reports/db-optimization.md` §3.2 的两个小索引）。
> 改动：**只改 `db/schema.sql` + `db/init_db.py`**；真实库 `data/drugs.db` 只读（未执行任何写语句）；未改 `site/build.py`、未跑 git/发布。
> 验证全部在 `.tmp/schema-idx/` 副本上（`old.db` 模拟老库、`fresh.db` 全新建库）。

---

## 0. 结论（TL;DR）

| 项 | 结果 |
|---|---|
| 两个索引 | `idx_variant_substance ON variant(substance_id)`、`idx_artg_name ON artg_entry(name)`，均 `CREATE INDEX IF NOT EXISTS` |
| schema.sql | 索引写在对应表定义后：`variant` 三个索引一组（L74–78）、`artg_entry` 两个索引一组（L381–387） |
| init_db.py | 新增幂等迁移 `_ensure_indexes()`（L86–100），`build()` 中调用（L117）：老库跑 `init_db` 自动补索引 |
| 老库升级验证 | 副本删掉两索引模拟旧库 → `init_db --db <副本>` **exit 0，0.14 s**，索引 33 → **35**；第二次运行幂等（索引/数据不变） |
| 数据不变 | 10 张表行数、`product` 表 DDL 哈希、`quick_check=ok` 前后完全一致；未触发 product 表重建 |
| 未跑 ANALYZE | 升级后**无 `sqlite_stat1`**（审计已证明 ANALYZE 会让 build 查询慢 2–3 倍） |
| 空库建库 | `fresh.db`：17 表 / 3 视图 / **35 索引** / 233 KB / quick_check ok |
| 查询计划 | 副本上 `EXPLAIN QUERY PLAN`：artg 列表 `SCAN artg_entry USING INDEX idx_artg_name`；variant 点查 `SEARCH variant USING INDEX idx_variant_substance` |
| 真实库现状 | 已是 **35 索引**（含这两个，另一个任务已手工建过）+ 已 VACUUM 到 325,398,528 B + 无 sqlite_stat1；**再跑 init_db 是 no-op** |
| 回归 | `db/check_data.py` exit 0（products 409,587 / substances 12,649 / variants 13,772 …） |
| 验证脚本 | `.tmp/schema-idx/verify.py` → `13/13 checks passed`，证据 `.tmp/schema-idx/verify.json` |

---

## 1. 改动

### 1.1 `db/schema.sql`

```sql
-- L74-78：variant 的索引组
CREATE INDEX IF NOT EXISTS idx_variant_salt_code ON variant (salt_code);
CREATE INDEX IF NOT EXISTS idx_variant_basis ON variant (strength_basis);
-- v0.4.2：成分 → variant 点查（lib/search.py / 成分页），实测 0.6 ms → 0.1 ms
CREATE INDEX IF NOT EXISTS idx_variant_substance ON variant (substance_id);

-- L381-387：artg_entry 的索引组
CREATE INDEX IF NOT EXISTS idx_artg_norm ON artg_entry (name_norm);
-- v0.4.2：site/build.py 的 ARTG 列表 SELECT ... FROM artg_entry ORDER BY name，
-- 实测 50 → 32 ms（-39%，免 temp b-tree 排序）
CREATE INDEX IF NOT EXISTS idx_artg_name ON artg_entry (name);
```

- 放在对应表定义之后（符合 schema.sql 既有风格：表 → 索引 → 下一张表）。
- 依据（`reports/db-optimization.md` §3.2）：两个索引都是小表（13.9k / 34.6k 行）、只带来正收益、无查询计划副作用；被否决的 `product_name` 覆盖索引 / 全库 ANALYZE 等**没有**写进 schema。

### 1.2 `db/init_db.py`

- 模块 docstring 的「结构迁移」从两处改为三处，第 2 条即本改动。
- 新增 `_ensure_indexes(db)`（L86–100）：

```python
def _ensure_indexes(db):
    """v0.4.2：给已有库补 DB 优化审计落地的两个小索引（幂等）。..."""
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_variant_substance ON variant (substance_id)",
        "CREATE INDEX IF NOT EXISTS idx_artg_name ON artg_entry (name)",
    ):
        db.execute(ddl)
    db.commit()
```

- `build()` 中在 `_ensure_variant_columns()` / `executescript(schema)` 之后调用（L117）：
  空库由 schema.sql 建索引；老库即使 schema.sql 因某种原因没执行到，也会被 `_ensure_indexes` 补上；
  真实库已手工建过同名索引时 `IF NOT EXISTS` 直接跳过，不会报错、不会重建。
- **不**在迁移里跑 ANALYZE / VACUUM（前者实测有毒，后者属于运维动作、需独占锁）。

---

## 2. 验证（全部在副本上，真实库只读）

命令：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -X utf8 .tmp\schema-idx\verify.py           # 13/13 checks passed
```

验证脚本做的事（对应输出）：

```
[PASS] 老库模拟：2 个目标索引已移除 — index_count=33
[PASS] 老库 init_db 升级 exit=0 — 0.14 s（复制副本 0.12 s）
[PASS] 2 个索引均已创建 — index_count 33 → 35
[PASS] 老库数据未变（行数 + product DDL + quick_check） — quick_check=ok
[PASS] 没有误跑 ANALYZE（无 sqlite_stat1）
[PASS] 旧库升级没有触发 product 表重建
[PASS] 升级后 2 个索引可被查询计划使用 — EXPLAIN QUERY PLAN 命中两个新索引
[PASS] 老库 init_db 二次运行 exit=0（幂等）
[PASS] 二次运行后索引数量/数据不变
[PASS] 空库 init_db exit=0 且建出 2 个索引 — tables=17 views=3 indexes=35 quick_check=ok
[PASS] 空库无 sqlite_stat1（未 ANALYZE）
[PASS] schema.sql 含两条 CREATE INDEX IF NOT EXISTS
[PASS] init_db.py 含 _ensure_indexes 且被 build() 调用
== 13/13 checks passed ==
```

补充数据（`.tmp/schema-idx/verify.json`）：

| 项 | 值 |
|---|---|
| 副本（老库模拟，删索引后） | 33 索引 / 325,398,528 B |
| 跑 `init_db` 后 | **35 索引 / 325,398,528 B**（文件大小不变：删索引留下的空闲页正好被新索引复用） |
| 升级耗时 | **0.14 s**（450 MB→325 MB 库；建两个小索引很快） |
| 数据不变 | 10 个计数（product/product_component/substance/variant/name_key/product_name/collision severe/artg_entry/source/ingest_run）前后全等；`product` 表 DDL sha 相同 |
| 空库 | 17 表 / 3 视图 / 35 索引 / 233,472 B / quick_check ok |

### 2.1 真实库现状（只读核对，未写入）

| 项 | 值 |
|---|---|
| 大小 / mtime | 325,398,528 B / 2026-10-28T10:10:18（另一任务已执行 VACUUM，见 `reports/db-optimization.md`） |
| 索引数 | **35**，其中 `idx_artg_name`、`idx_variant_substance` **都已存在**（手工建过） |
| sqlite_stat1 | 无（保持无害状态） |
| `db/check_data.py` | exit 0，products 409,587 / components 498,445 / substances 12,649 / variants 13,772 … |

→ 对真实库跑 `python db/init_db.py` 是 **no-op + 视图重建**，两个 `CREATE INDEX IF NOT EXISTS` 会直接跳过；不会重复建索引、不会改数据。

---

## 3. 发布注意

1. **IF NOT EXISTS 安全性**：真实库已有这两个同名索引（由 `reports/db-optimization.md` 的手工 apply 落地），本次迁移重复运行安全；老库/新克隆跑 `db/init_db.py`（或 `run_all.py`）会自动补齐。
2. **版本号**：改动里注释写的是「v0.4.2」占位；实际版本号由 Lead 按 CHANGELOG 第一节决定（本任务未改 CHANGELOG / 未发布）。若版本号定成别的，注释可随下次发布顺手改，不影响功能。
3. **不做 ANALYZE / 不 VACUUM**：迁移只建索引。VACUUM 是独立运维动作（需独占锁 + 备份，见 db-optimization 报告 §2.4）；ANALYZE 实测有害，千万别在迁移里顺手加。
4. **对站点无影响**：索引只影响 DB 查询计划；`site/build.py` 不用改（两个索引对 build 的收益很小：ARTG 排序 -18 ms/次）。DB 不在 git / 不在发布产物里，发布流程（`publish.ps1`）不涉及。
5. **老库升级窗口**：`init_db` 会短暂拿写锁 ~0.1–0.4 s；和其它 ingest/build 并行时按纪律等空闲窗口，避免锁冲突。
6. **已有索引定义不一致的风险**：`IF NOT EXISTS` 只按索引名判断，不会校验旧索引的列是否一致。本库两个索引定义与 schema 完全一致（可用 `PRAGMA index_info('idx_artg_name')` 核对）；若未来手工建过同名异列索引，需要先 DROP 再跑迁移。

---

## 4. 交付物

| 路径 | 说明 |
|---|---|
| `db/schema.sql` | +2 条 `CREATE INDEX IF NOT EXISTS`（L78 variant、L387 artg_entry，含注释依据） |
| `db/init_db.py` | +`_ensure_indexes()` 幂等迁移（L86–100）+ `build()` 调用（L117）+ docstring 更新 |
| `.tmp/schema-idx/verify.py` | 可复跑验证（老库模拟 / 升级 / 二次幂等 / 空库 / 数据不变 / EXPLAIN） |
| `.tmp/schema-idx/verify.json` | 13 项检查结果与前后快照 |
| `.tmp/schema-idx/check_data.txt` | 真实库 `db/check_data.py` 输出（只读） |
| `reports/schema-indexes.md` | 本报告 |
