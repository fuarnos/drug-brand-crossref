# 三语用例落地：CZ / LV 各 3 条 + CI 基线 78/74（task-12 / 工位 search-alias）

- 日期：2026-11-16
- 库：`data/drugs.db` **594,781 产品 / 13,648 成分 / 15 市场**（2026-11-16 现查；`active` 477,244）
- 依据：task-9 设计 `reports/2026-11-16-trilingual-cz-lv-design.md`（只读试跑 6/6 能过）
- 产物：本报告 + 两处改动（见 §1）；未改 `lib/`、`site/`、`db/`，未写 DB / `site/dist`，未 commit。

## 0. 结论（先看这一屏）

| 项 | 实测 |
|---|---|
| 三语套件 | **78 例（通过 75）**；查询 **360** 条：Top-5 **98.6%**、Top-1 **93.1%**；跨国可见 **78/78**；673.9 s |
| 新增 6 条 | **全部 PASS**（3 条 CZ + 3 条 LV，各 1 条查询） |
| 新增失败 | **0**。3 个失败仍是既有 allowlist：`metformin/combo`、`beclometasone/dup_inn`、`chlorphenamine/dup_inn` |
| CI 门槛 | `TRILINGUAL_MIN_CASES 72→78`、`TRILINGUAL_MIN_PASS 68→74`（实测 75 通过 ≥ 74）；`ALLOWED_TRILINGUAL_FAILURES` 未动 |
| 退出码 | `1` = 存在 3 个既有 allowlist 失败（该脚本历史行为）；CI 判定按 `cases≥78 且 passed≥74 且 未登记失败为空` → **PASS** |
| `ci_checks --fast` | **PASS 8 / FAIL 0 / SKIP 4**（13.6 s，12 项） |

## 1. 改动（只两处）

| 文件 | 行 | 改动 |
|---|---|---|
| `tests/trilingual/run_tests.py` | `:306-330` | 在 `CASES` 末尾（`metoclopramide` 之后、`]` 之前）插入 6 条：CZ `hydrochlorothiazide` / `pyridoxine` / `atorvastatin`，LV `indometacin` / `warfarin` / `semaglutide`；`cat="cz"/"lv"`，本地原文放 `en` 槽，`foreign` 写 `CZ` / `LV`，`note` 写实测 rank 与盐型行说明 |
| `deploy/ci_checks.py` | `:61-62` | `TRILINGUAL_MIN_CASES = 78`、`TRILINGUAL_MIN_PASS = 74`；`:55-60` allowlist **未动** |

- 未改其他用例的期望值（`git diff` 只有上述插入块 + 两个常量）。
- 未动 `lib/search.py`、`site/build.py`、`db/`、`site/dist`；`data/drugs.db` 只读。

## 2. 三语实测（原文）

```text
== 汇总 ==
案例 78（通过 75）；查询 360 条：Top-5 命中 98.6%，Top-1 命中 93.1%；跨国可见 78/78；用时 673.9s
  en: 129 条查询, Top-5 127, Top-1 116 (98.4%)
  es: 116 条查询, Top-5 114, Top-1 108 (98.3%)
  zh: 115 条查询, Top-5 114, Top-1 111 (99.1%)
```

新增 6 条逐行：

```text
[PASS] hydrochlorothiazide    cz     查询 1/1 命中Top5, Top1 1/1  跨国✓
[PASS] pyridoxine             cz     查询 1/1 命中Top5, Top1 0/1  跨国✓
[PASS] atorvastatin           cz     查询 1/1 命中Top5, Top1 1/1  跨国✓
[PASS] indometacin            lv     查询 1/1 命中Top5, Top1 1/1  跨国✓
[PASS] warfarin               lv     查询 1/1 命中Top5, Top1 1/1  跨国✓
[PASS] semaglutide            lv     查询 1/1 命中Top5, Top1 1/1  跨国✓
```

> `pyridoxine` 的 `Top1 0/1` 不是失败：`pyridoxin leciva` 的期望成分 `Pyridoxine` 在 rank 2
> （Top-1/2 是 CZ 盐型行 `Pyridoxine Hydrochloride`），按套件规则 rank<10 即 resolved；
> 这是 task-9 §3-2 已记录的「软过」，本轮没有为凑 Top-1 改其他用例期望。

既有 3 个失败（未新增，与 task-9 前一致）：

```text
[FAIL] metformin      combo   zh '西格列汀二甲双胍片' cards=8 top1=['Sitagliptin']
[FAIL] beclometasone  dup_inn en 'beclomethasone' / es 'beclometasona' top1=['Beclomethasone']
[FAIL] chlorphenamine dup_inn es 'clorfenamina' cards=17 top1=['Chlorpheniramine','Tramazoline']
```

CI 门禁（`deploy/ci_checks.py:287-304`）：失败集合 ⊆ allowlist（3 个全在表中）、案例 78 ≥ 78、通过 75 ≥ 74 → **trilingual PASS**。
脚本自身退出码 1 是「不满 78/78」的既有行为（与 72 例时 69 通过仍 exit 1 相同），不是本轮回归。

## 3. 抽查（CLI 首屏）

```text
& $py cli.py "pyridoxin leciva"
 1. PYRIDOXIN LÉČIVA  [CZ]  Pyridoxine Hydrochloride  20 mg  tablet  ×1  (exact)
 2. PYRIDOXIN LÉČIVA  [CZ]  Pyridoxine Hydrochloride  50 mg  injection ×1  (exact)
 3. PYRIDOXINE        [GB]  Pyridoxine  10–100 mg  tablet ×62  (fuzzy)
 …

& $py cli.py "orfarin tabletes"
 1. Orfarin 3 mg tabletes  [LV]  Warfarin  3 mg / 5 mg  tablet  ×2  (exact)
 2. Agen 10 mg tabletes    [LV]  Amlodipine  5 mg / 10 mg  tablet ×2  (fuzzy)
 …
```

## 4. `ci_checks --fast` 原文

```text
12 项：PASS 8 / FAIL 0 / SKIP 4（总 13.6s · mode=fast · dist=site/dist）
[PASS] i18n / py_compile（175 文件）/ unittest:etl（55）/ unittest:lib（61）
[PASS] unittest:mobile（29）/ unittest:lib-atc-category（4）/ dist-integrity / workflow
[SKIP] trilingual（--fast 跳过，全量跑）/ check_data（--fast 跳过）/
       ui-surface / first-screen（要无头 Chrome）
```

## 5. 与 task-9 设计的差异 / 已知点

1. **实测通过数 = 75**（设计预期 75）→ CI 门槛按任务写 **78/74**；未把 MIN_PASS 提到 75，保留旧基线「留 1 例」的斜率
   （原 72 例 / 69 通过 / 门槛 68）。
2. **`pyridoxine` Top-1 不是期望成分**（盐型行占位）—— 已在 task-9 报告 §3-2 标注；本轮只为「能过」加用例，未改口径。
3. **查询数 360 = 354 + 6**（每例 1 条 en 槽查询）；`es/zh` 空槽不计。
4. **跨国可见 78/78**：6 条新例的 `foreign` 均能在默认 25 卡内命中（`orfarin tabletes` 只有 LV 卡，但 `foreign=["LV"]` 成立）。
5. 运行 673.9 s（上次 613.7 s），差值来自机器负载与 6 条新例，非代码变更。
6. 下一轮（若需要）可把 `cat` 说明补进 `run_tests.py` 顶部 docstring / `:61-70` 分类注释；本轮按任务「只两处」未动。

## 6. 复核

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py tests/trilingual/run_tests.py          # 78 例 / 75 通过 / Top-5 98.6% / 360 查询 / 78-78 跨国（exit 1 = 3 个既有 allowlist 失败）
& $py deploy/ci_checks.py --fast             # PASS 8 / FAIL 0 / SKIP 4
& $py cli.py "pyridoxin leciva"
& $py cli.py "orfarin tabletes"
```

工作树（本人范围）：`M tests/trilingual/run_tests.py`、`M deploy/ci_checks.py`（另有其他工位的 `site/build.py` 等改动，不属本任务）。
