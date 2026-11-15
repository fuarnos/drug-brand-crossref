# 三语用例补 CZ / LV：设计 + 只读试跑（task-9 / 工位 search-alias）

- 日期：2026-11-16
- 库：`data/drugs.db` **594,781 产品 / 13,648 成分 / 15 市场**（2026-11-16 现查）
- 方式：**只读** `lib.search.SearchIndex`（`mode=ro`）逐条试跑；未改 `tests/trilingual/**`、`lib/`、`site/`、DB。
- 产物：本报告（下一轮落地清单见 §4）。`git status` 仅新增本文件。

## 0. 结论（先看这一屏）

| 项 | 结论 |
|---|---|
| 可加用例 | **CZ 3 条 + LV 3 条 = 6 条，试跑全部 `case_pass`**（1 条查询/例，共 +6 查询） |
| 需修数据 | **0 条**。但有 3 条属于「能过但不够干净」：Top-1 落在盐型 substance 行 / 非本国卡，见 §3 |
| 不建议直接加 | `efectin er`（期望 base Venlafaxine 必失败）、`indometacin` 若期望 `indomethacin`（会命中另一条 substance 行）、`orfarin tabletes`（只有 LV 卡，不证明跨市场） |
| 新基线 | **78 例 / 75 通过**（现 72/69 + 6 全过；3 个既有失败不变）；查询 **360** 条、Top-5 98.6%、Top-1 ≈93.1% |
| 要改的常量 | `tests/trilingual/run_tests.py:71-306`（`CASES` 插 6 条）；`deploy/ci_checks.py:61-62`（72→78、68→74）；`ALLOWED_TRILINGUAL_FAILURES` 不变 |

## 1. 用例格式与判定（读现有实现）

- `tests/trilingual/run_tests.py:71-306` `CASES`：每例 = `sid` + `cat` + `en/es/zh` 查询列表 + `foreign` 期望市场；
  `cat` 只用于分组统计 / CI allowlist（`:55-60` 在 `ci_checks.py`），不影响检索逻辑。
- `run_case()`（`:327-411`）：对每个非空语言槽逐条 `idx.search(query)`（默认 25 卡），
  **期望成分 `inn_of(sid)` 出现在前 10 张卡**即该语言 resolved；`case_pass_same_substance` = 所有被查语言都 resolved。
- `foreign`：`cross_market_ok` = 结果卡国家集合 ∩ `foreign` ≠ ∅（不参与 case pass，单独统计 72/72）。
- **新市场语言的放法（本轮推荐，不改 runner 逻辑）**：CZ/LV 原文放 **`en` 槽**（原文/拉丁名槽），`cat="cz"/"lv"`，
  `es=[]`、`zh=[]`；`note` 写清「本地原文」。若下一轮想更干净，可加 `local` 键并改 `run_case` 语言循环
  （属逻辑改动，本轮不做）。

## 2. 建议用例表（6 条，全部试跑通过）

> 「rank」= 期望成分在**前 10 张卡**里的位置（`0` = Top-1）；「卡国家」= 默认 25 卡内出现的市场。

| # | 市场 | 类型 | 查询（原文） | 期望 sid（INN） | 试跑 Top-1（国家 / 成分 / 规格） | rank | 卡国家 | 判定 |
|---|---|---|---|---|---|---:|---|---|
| CZ-1 | CZ | 成分名（捷克写法） | `hydrochlorothiazid` | `hydrochlorothiazide` | US / Hydrochlorothiazide / 12.5–50 mg | 0 | AU,CA,**CZ**,ES,FR,GB,SG,TW,US | ✅ 过（Top-1 是 US 英文名，CZ 复方卡在 25 卡内） |
| CZ-2 | CZ | 商品名（包装名） | `pyridoxin leciva` | `pyridoxine` | CZ / **Pyridoxine Hydrochloride** / 20 mg（brand=PYRIDOXIN LÉČIVA） | 2 | CZ,ES,GB,US | ✅ 过（Top-1 是盐型行；底座 Pyridoxine 在 rank 2） |
| CZ-3 | CZ | 包装上一行字（品牌+规格） | `sortis 20 mg` | `atorvastatin` | LV / Atorvastatin / 10–40 mg；CZ 第 2 张 = Atorvastatin Calcium Trihydrate | 0 | AU,CA,**CZ**,ES,EU,**LV**,MX,SG,US | ✅ 过 |
| LV-1 | LV | 成分名（国际/当地拼法） | `indometacin` | `indometacin` | GB / Indometacin / 25–50 mg | 0 | AU,**CZ**,ES,GB,**LV**,MX | ✅ 过（dup_inn：与 US `Indomethacin` 两行；LV 卡在 25 卡内） |
| LV-2 | LV | 商品名（原文含剂型） | `orfarin tabletes` | `warfarin` | LV / Warfarin / 3–5 mg（brand=Orfarin 3 mg tabletes） | 0 | **LV only** | ✅ 过（但无跨市场卡，见 §3-3） |
| LV-3 | LV | 英文原名 | `wegovy` | `semaglutide` | CZ / Semaglutide / 1.5–9 mg | 0 | CA,**CZ**,ES,EU,FR,GB,**LV**,MX,SG,TW,US | ✅ 过（LV 卡 rank 4） |

可直接粘贴的 `CASES` 片段（下一轮用）：

```python
    # ---- CZ / LV（v0.13.0 新市场；本地原文放 en 槽，cat 标 cz/lv）----
    dict(sid="hydrochlorothiazide", cat="cz",
         en=["hydrochlorothiazid"], es=[], zh=[],
         foreign=["CZ"],
         note="CZ 写法（去 e）；top1 为 US 英文名，CZ 复方卡在 25 卡内"),
    dict(sid="pyridoxine", cat="cz",
         en=["pyridoxin leciva"], es=[], zh=[],
         foreign=["CZ"],
         note="CZ 包装名（Léčiva→leciva）；top1 是 Pyridoxine Hydrochloride 盐型行，底座 rank 2"),
    dict(sid="atorvastatin", cat="cz",
         en=["sortis 20 mg"], es=[], zh=[],
         foreign=["CZ", "LV"],
         note="包装行（品牌+规格）；top1 LV，CZ 卡为 Atorvastatin Calcium Trihydrate 盐型行"),
    dict(sid="indometacin", cat="lv",
         en=["indometacin"], es=[], zh=[],
         foreign=["LV"],
         note="国际/当地拼法（dup_inn：与 Indomethacin 两行；top1 GB，LV 卡在 25 卡内）"),
    dict(sid="warfarin", cat="lv",
         en=["orfarin tabletes"], es=[], zh=[],
         foreign=["LV"],
         note="LV 商品名+剂型原文（tabletes）；结果只出 LV 卡"),
    dict(sid="semaglutide", cat="lv",
         en=["wegovy"], es=[], zh=[],
         foreign=["LV"],
         note="英文原名；LV 卡 rank 4，另有 CZ/US/…"),
```

## 3. 试跑中的「会失败 / 不够干净」（下一轮不要照抄）

1. **`efectin er`（CZ，Venlafaxine）会失败**：结果首卡 = CZ `Venlafaxine Hydrochloride`
   （152 产品，brand=EFECTIN ER），前 10 卡里**没有 base `Venlafaxine`**（rank=None）→ 若期望 `venlafaxine` 必红。
   只有改成期望 `venlafaxine-hydrochloride` 才能过，但那是盐型行，不建议为凑绿灯改期望。
2. **`pyridoxin leciva` 是「软过」**：Top-1/2 都是 CZ 盐型行 `Pyridoxine Hydrochloride`；底座 `Pyridoxine`
   靠 GB fuzzy 卡在 rank 2 才进前 10。若下一轮把口径收紧为「Top-1 必须是期望成分」，这条会红。
3. **`orfarin tabletes` 没有跨市场卡**：25 卡只有 LV；`foreign=["LV"]` 能过 `cross_market_ok`，
   但体现不了「跨市场定位」。要跨市场证据，改用 `orfarin`（24 卡，含 TW/US/GB/ES/CZ/LV）或把 `foreign` 写 `["LV","TW"]`。
4. **`indometacin` 的 sid 只能写 `indometacin`**（GB/AU 那条，无 ATC）；US 的 `indomethacin`（M01AB01）是另一条 substance。
   写 `indomethacin` 也能 top10 过（rank 6），但 LV 卡属于 `Indometacin` 行，语义会错位。
5. **`hydrochlorothiazid` 是「软过」**：Top-1 为 US 英文名，CZ 只出现在 25 卡内（复方名 `IRBESARTAN/HYDROCHLOROTHIAZID TEVA`）。
   若要「Top-1 落在 CZ」，改用 `chlorprothixen leciva`（试跑：Top-1 = CZ Chlorprothixene，rank 0，卡国家 CZ/GB，仅 2 卡）。
6. **可选替代（也都试跑通过）**：`atorvastatin ratiopharm`（CZ，rank 0，CZ/ES/EU/LV）、
   `bulgaplin 100 mg cietās kapsulas`（LV，rank 0，LV；带变音符号的包装行）、
   `atorvastatin tevapharm 10 mg apvalkotās tabletes`（LV，rank 0，CZ/ES/LV）。

## 4. 下一轮落地清单（不改代码逻辑，只改常量/数据）

| 文件 | 位置 | 改什么 |
|---|---|---|
| `tests/trilingual/run_tests.py` | `:71-306` `CASES` | 在 `metoclopramide` 条目后、`]` 前插入上面 6 条；`cat` 用 `cz`/`lv` |
| `tests/trilingual/run_tests.py` | `:1-29` 模块 docstring / `:61-70` 分类注释 | 补一行「cz/lv：本地原文放 en 槽」；`cat` 说明加 `cz`/`lv`（可选） |
| `deploy/ci_checks.py` | `:61` `TRILINGUAL_MIN_CASES = 72` | → **78**（72 + 6） |
| `deploy/ci_checks.py` | `:62` `TRILINGUAL_MIN_PASS = 68` | → **74**（新基线 75 通过，沿用「留 1 例」的旧斜率；若按严格基线可写 75） |
| `deploy/ci_checks.py` | `:55-60` `ALLOWED_TRILINGUAL_FAILURES` | **不变**（3 个既有失败；6 条新例全过，不需要新 allowlist） |
| `docs/市场扩展接口.md` | `:234` | 文档写「加 `tests/trilingual/cases_v2.json`」，实际 CI 跑的是 `run_tests.py` 的 `CASES`；下一轮顺手改准确（文档改动，非测试） |

**预计影响**（按 6 条全过算）：

| 指标 | 现基线 | 加 6 条后 |
|---|---:|---:|
| 案例 | 72（通过 69） | **78（通过 75）** |
| 查询 | 354 | **360** |
| Top-5 | 98.6% | **98.6%**（355/360） |
| Top-1 | 93.2%（v0.13.0 数据） | **≈93.1%**（335/360） |
| 跨国可见 | 72/72 | **78/78**（6 条 `foreign` 均能在 25 卡内命中） |

落地顺序：v0.13.0 发布完成后 → 改 `CASES` + 两个常量 → 串行跑一次
`& $py tests/trilingual/run_tests.py --quiet`（约 620 s，预期 78/75）→ 全量 CI（`ci_checks.py`）确认 trilingual PASS。
**本轮不动文件**，避免发布流程中 CI 口径漂移。

## 5. 判据与复核

- 用例格式/判定读自 `tests/trilingual/run_tests.py`：`CASES`（`:71-306`）、`run_case`（`:327-411`）、
  `case_pass_same_substance`（`:401`）、跨国检查（`:404-409`）、CI 阈值（`deploy/ci_checks.py:55-62`）。
- 试跑查库（只读 `SearchIndex`，默认 `limit=25`；`rank` 取前 10 卡）；DB 现查
  `SELECT COUNT(*) FROM product` = 594,781、`COUNT(*) FROM substance` = 13,648、
  `COUNT(DISTINCT COALESCE(country,region)) FROM product` = 15。
- 试跑输出摘要：

```text
[CZ] 'hydrochlorothiazid'  n=25 rank0 countries=[AU,CA,CZ,ES,FR,GB,SG,TW,US]  top1=US Hydrochlorothiazide
[CZ] 'pyridoxin leciva'    n=10 rank2 countries=[CZ,ES,GB,US]                 top1=CZ Pyridoxine Hydrochloride
[CZ] 'sortis 20 mg'        n=14 rank0 countries=[AU,CA,CZ,ES,EU,LV,MX,SG,US]  top1=LV Atorvastatin
[LV] 'indometacin'         n=16 rank0 countries=[AU,CZ,ES,GB,LV,MX]           top1=GB Indometacin
[LV] 'orfarin tabletes'    n=13 rank0 countries=[LV]                          top1=LV Warfarin
[LV] 'wegovy'              n=19 rank0 countries=[CA,CZ,ES,EU,FR,GB,LV,...]    top1=CZ Semaglutide
[FAIL 示例] 'efectin er'   n=5  rankNone（base Venlafaxine 不在前 10）          top1=CZ Venlafaxine Hydrochloride
```

> 注：`cat="cz"/"lv"` 只是分组标签；若 CI 的 `ALLOWED_TRILINGUAL_FAILURES` 未来要登记新例，
> 元组 =（`sid`, `cat`），所以 `cat` 名一旦定下（`cz`/`lv`）下一轮不要改。
