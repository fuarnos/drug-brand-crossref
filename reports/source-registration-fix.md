# TW source 注册修复（tfda_tw）— task-71

> 日期：2026-10-28 ｜ 真实库：`data/drugs.db` **只读未写** ｜ 未跑 `site/build.py` / git / 发布
> 任务：修复 task-69 留下的「`data/markets.json` 引用 `tfda_tw` 但 DB `source` 表没有该行 → 注册表校验/测试失败」。
> 交付：`db/source_tfda_tw.sql`（source 行 SQL，已副本验证）、命名统一（`etl/ingest_tw_tfda.py`）、测试断言修正（`tests/test_markets_registry.py`）、本报告、`.tmp/source-fix/` 验证证据。
> **真实库 apply 由 Lead 执行**（本任务禁止写 DB）。

---

## 1. 结论

| 项 | 结果 |
|---|---|
| source SQL | ✅ 新增 `db/source_tfda_tw.sql`：幂等 `INSERT OR REPLACE` 一行 `source_id='tfda_tw'`（name/url/**OGDL v1.0**/license_url/retrieved_at=2026-10-28/**data_as_of=2026-10-22**/data_as_of_note/notes） |
| 命名统一 | ✅ `etl/ingest_tw_tfda.py` 的 `SOURCE_ID` 由 `"tw_tfda"` 改为 **`"tfda_tw"`**（与 `data/markets.json`、`docs/市场扩展接口.md` §3 模板一致）；`data/markets.json` notes 同步（并移除「测试断言待改」待办） |
| 测试修正 | ✅ `tests/test_markets_registry.py::test_tw_is_planned_placeholder`：`assertIsNone(tw.source_id)` → **`assertEqual("tfda_tw", tw.source_id)`**，并加注释说明 source 行登记前属预期过渡态 |
| **副本验证** | ✅ 在 DB 副本执行 `db/source_tfda_tw.sql` 后：`lib/markets.py --check` → **exit 0「OK: 注册表校验通过」**；`tests.test_markets_registry` → **47/47 全绿**（证据 `.tmp/source-fix/verify_on_copy.out.txt`） |
| 真实库现状 | ⚠️ 未执行 SQL：`lib/markets.py --check` 失败 1 项、`tests.test_markets_registry` 6 failures（**全部因为 source 行未登记**；测试断言项已修）。Lead apply 后预期 **47/47** |
| 真实库安全 | ✅ 未写：mtime/大小（325,398,528 B）与任务开始时一致；`source` 表仍无 `tfda_tw` 行 |

**一句话**：SQL 与测试都准备好了，副本上整套校验绿；Lead 在真实库执行一次 SQL 即可让仓库恢复绿色，随后可继续 TW ingest。

---

## 2. `db/source_tfda_tw.sql`（新增）

```sql
INSERT OR REPLACE INTO source
    (source_id, name, url, license, license_url, retrieved_at,
     data_as_of, data_as_of_note, notes)
VALUES (
    'tfda_tw',
    '衛生福利部食品藥物管理署（TFDA）全部藥品許可證資料集',
    'https://data.gov.tw/dataset/9122',
    '政府資料開放授權條款－第1版 (OGDL v1.0)',
    'https://data.gov.tw/license',
    '2026-10-28', '2026-10-22',
    'weekly（每 7 日與藥證業務管理系統同步）',
    '可再发布（OGDL v1.0，须按「顯名聲明」署名…）；本站只存事实字段，不存適應症/用法用量正文。'
);
```

- 文件内附：执行方式（sqlite3 / python / 由 `--write-db` 一并 upsert）、校验命令、回滚说明、`ingest_run` 示例（注释）。
- 幂等：`INSERT OR REPLACE`，重复执行无副作用；只写 `source` 一行，不动 product。
- 与 `reports/tw-ingest-runbook.md` §2.2 的草案一致（本任务把它固化为仓库文件）。

---

## 3. 命名统一（tfda_tw）

| 位置 | 变更 |
|---|---|
| `etl/ingest_tw_tfda.py:83` | `SOURCE_ID = "tw_tfda"` → **`SOURCE_ID = "tfda_tw"`**（注释：与 markets.json 统一） |
| `data/markets.json` TW.notes | 更新为「已统一为 tfda_tw」；待办①改为指向 `db/source_tfda_tw.sql`；删除「测试断言待改」 |
| `docs/市场扩展接口.md` | 无需改：§3 ETL 模板与 §6 runbook 本来就用 `SOURCE_ID = "tfda_tw"`（本次让代码对齐文档） |
| 保留 `tw_tfda` 的地方 | ① 脚本/模块文件名 `etl/fetch_tw_tfda.py`、`etl/ingest_tw_tfda.py`（文件命名，不是 source_id，保留）；② `data/tw_ingest_dryrun.csv` 的 `source_id` 列仍是旧值 `tw_tfda`（**数据快照，本次写范围外**；下次 dry-run 会按新常量写成 `tfda_tw`）；③ `.tmp/tw-ingest/*` 旧统计（临时文件，忽略） |

> 生产代码中已无 `SOURCE_ID = "tw_tfda"`；剩下的 `tw_tfda` 仅是文件名/旧数据快照。

---

## 4. 测试修正（`tests/test_markets_registry.py`）

```diff
     def test_tw_is_planned_placeholder(self) -> None:
         tw = self.reg.require_market("TW")
         self.assertEqual(M.KIND_COUNTRY, tw.kind)
         self.assertFalse(tw.enabled)
-        self.assertIsNone(tw.source_id)
+        # task-71：TW 数据源已钉为 tfda_tw（source 行由 Lead 按 db/source_tfda_tw.sql 登记；
+        # 登记前 lib/markets 校验会报「不在 DB source 表」，属预期过渡态）。
+        self.assertEqual("tfda_tw", tw.source_id)
         self.assertEqual("zh-Hant", tw.default_lang)
         self.assertIn("zh-Hant", tw.languages)
```

- 其余测试不改：`test_enabled_market_sources_exist_in_db` 只校验 **enabled** 市场（TW disabled 不受影响，但 source_id 非空仍会走 `_validate_markets` 的存在性校验 → 需要 §2 SQL）。
- `test_enabled_markets_match_db_countries` 仍要求「enabled 市场集合 = DB countries」→ TW 启用必须与 DB 首次含 TW 行同一窗口（runbook §4 已写）。

---

## 5. 验证记录

### 5.1 副本验证（绿）

证据：`.tmp/source-fix/verify_on_copy.py` / `verify_on_copy.out.txt`（脚本把 `data/drugs.db` 复制到 `.tmp/source-fix/db-copy.db`，执行 `db/source_tfda_tw.sql`，再让 `lib/markets.py` CLI 与测试套件指向副本；真实库只读）。

```text
副本 db-copy.db 已应用 source SQL → ('tfda_tw', '衛生福利部食品藥物管理署（TFDA）全部藥品許可證資料集', '政府資料開放授權條款－第1版 (OGDL v1.0)', '2026-10-22')

=== 1) lib/markets.py --check（副本 DB，source 行已登记）===
exit: 0
stdout: OK: 注册表校验通过

=== 2) tests.test_markets_registry（副本 DB + CLI 包装器）===
Ran 47 tests in 0.453s
OK
tests run: 47 failures: 0 errors: 0 skipped: 0
RESULT: CLI=PASS | TESTS=PASS
```

> 说明：测试文件硬编码 `data/drugs.db`，因此副本验证时把 `tests.test_markets_registry.DB` 指向副本，并把 `test_cli_check_passes` 的 `lib/markets.py` 子进程替换为 `lib.markets.main` 的副本包装器（`.tmp/source-fix/markets_cli_wrapper.py`，行为等价、仅 DB 路径不同）。真实库 apply SQL 后**无需**任何包装器，原生命令即绿。

### 5.2 真实库当前状态（红，预期过渡态）

证据：`.tmp/source-fix/real_markets_check.out.txt`、`real_unittest.out.txt`。

```text
lib/markets.py --check → exit 1
  - 市场 TW: source_id=tfda_tw 不在 DB source 表（先登记数据来源）

python -m unittest tests.test_markets_registry → Ran 47 tests, FAILED (failures=6)
  test_registry_is_valid / test_cli_check_passes / test_dummy_region_with_child /
  test_dummy_market_disabled_allows_no_source / test_dummy_market_registers_without_error /
  test_dummy_language_registers_without_error
（test_tw_is_planned_placeholder 已修，不再失败）
```

→ 6 个失败全部是「source 行缺失」派生；执行 §2 SQL 后即变绿（副本已验证同一状态）。

### 5.3 其他
- `python -m py_compile etl/ingest_tw_tfda.py tests/test_markets_registry.py` → OK。
- `data/markets.json` JSON 解析 OK；TW 项：`source_id=tfda_tw, data_as_of=2026-10-22, enabled=false, default_lang=zh-Hant`。
- 真实库 `source` 表仍无 `tfda_tw` 行；DB 文件 mtime/大小未变。

---

## 6. 真实库 apply 步骤（Lead 执行；~1 秒）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 备份（run_all 也会自动备份；手动迁移建议先复制）
Copy-Item data\drugs.db data\backups\drugs-before-source-tfda_tw-$(Get-Date -Format yyyyMMdd-HHmm).db

# 2) 执行 SQL（二选一）
sqlite3 data\drugs.db < db\source_tfda_tw.sql
# 或：
& $py -c "import sqlite3; c=sqlite3.connect('data/drugs.db'); c.executescript(open('db/source_tfda_tw.sql', encoding='utf-8').read()); c.commit(); c.close()"

# 3) 校验
& $py db\q.py "SELECT source_id,name,license,license_url,data_as_of FROM source WHERE source_id='tfda_tw'"
& $py lib\markets.py --check                    # 期望 exit 0「OK: 注册表校验通过」
& $py -m unittest tests.test_markets_registry -v  # 期望 Ran 47 tests, OK

# 4) 之后可继续 TW 入库 runbook（reports/tw-ingest-runbook.md §4）
```

- 单行 insert，耗时 <1 s；无需 VACUUM/重建；不影响 product/其它表。
- 若 CI/其他会话正在跑，先确认没有并发写库（本操作事务性、很快，但按纪律避免叠加）。

---

## 7. 回滚

| 场景 | 操作 |
|---|---|
| 只撤销 source 登记 | `DELETE FROM source WHERE source_id='tfda_tw';`；随后 `lib/markets.py --check` 会再次报错（markets.json 仍引用）→ 需同时把 `data/markets.json` TW.source_id 改回 `null`（+ 把测试断言改回 `assertIsNone`）才算完整回滚 |
| 完整回滚到 task-71 前 | 恢复备份 DB + `git checkout -- data/markets.json etl/ingest_tw_tfda.py tests/test_markets_registry.py`（若已提交；本任务未提交） |
| 回滚后重试 | 再次执行 `db/source_tfda_tw.sql` 即可（幂等） |

> 注意：单独 `DELETE source` 会让仓库回到「市场引用不存在的 source」的红状态；只建议在彻底放弃 TW 时做，并同步回退 markets.json/测试。

---

## 8. 变更文件

| 文件 | 变更 |
|---|---|
| `db/source_tfda_tw.sql` | **新增**：source 行 SQL（幂等）+ 执行/校验/回滚说明 |
| `etl/ingest_tw_tfda.py` | `SOURCE_ID: "tw_tfda" → "tfda_tw"`（1 行） |
| `tests/test_markets_registry.py` | TW 断言 `assertIsNone → assertEqual("tfda_tw", ...)` + 注释 |
| `data/markets.json` | TW.notes 更新（统一命名、SQL 文件位置、移除已修的测试待办） |
| `reports/source-registration-fix.md` | 本报告 |
| `.tmp/source-fix/` | `verify_on_copy.py/.out.txt`、`markets_cli_wrapper.py`、`real_markets_check.out.txt`、`real_unittest.out.txt`、`db-copy.db`（325 MB 副本，可删） |

## 9. 关联与遗留

- `reports/tw-ingest-runbook.md` 的阻塞项 **B3（命名冲突）、B4（source 登记）、B5（测试断言）** 已由本任务解决（B4 待 Lead 执行 SQL；B5 已修）；B1（`--write-db`）、B2（成藥/中藥）、B6（zh-Hant）仍开放。
- 旧数据快照 `data/tw_ingest_dryrun.csv` 的 `source_id` 列仍是 `tw_tfda`（下次 dry-run 自动变新值）；`.tmp/tw-ingest/*` 旧统计同理。
- `docs/市场扩展接口.md` §6 step 2 仍写「TW 占位 `source_id:null`」——现在是 `tfda_tw`，docs 更新不在本任务写范围，建议后续一行修正。

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 git / 发布 / `site/build.py`。_
