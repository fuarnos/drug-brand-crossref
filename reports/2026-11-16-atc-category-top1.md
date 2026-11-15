# ATC 类目检索 2 项红灯：判定与修复（task-5 / 工位 search-alias）

- 日期：2026-11-16
- 库：`data/drugs.db`（**594,781 产品 / 13,648 成分 / 15 市场**；`status='active'` 477,244）
- 触发：v0.13.0 数据窗口新增 **CZ 68,581 + LV 18,766** 产品后，`tests/test_lib_atc_category.py`
  红 2 项（`test_colloquial_acceptance_words` / `test_category_top1_by_ingredient_total`）。

## 0. 结论（先看这一屏）

| 问题 | 判定 |
|---|---|
| 是排序/过滤 bug 吗？ | **否**。实现与文档口径、评测期望生成器、线上客户端**同一口径**（类别内 active 产品最多的 substance 行）；lib 现算数字与 SQL 现查**逐项相同** |
| 是口径问题吗？ | **口径本身是 v0.10.3 已审核通过的「方案 H」**（产品数是目录覆盖度代理），本次变化由新市场数据造成；改口径会牵动 `site/build.py`（本任务禁改）与全站排序，不属于修红灯范围。两个边界写进 §5，建议单独立项 |
| 处理 | **只更新 3 处测试期望**（含 v0.13.0 注释 + 数字），`lib/search.py` **0 改动**，不写库、不构建、不发布 |
| 顺带发现（非本任务红线） | trilingual **72 例 / 69 通过 = 基线**、Top-5 **98.6% = 基线**、跨国 72/72；**Top-1 95.5% → 93.2%**：用 v0.13.0 前备份库对比，9 条查询因「盐型名 substance 行」变大掉到 rank 1（数据驱动，非本次改动），建议 Lead 决定是否立项（§5-1） |


旧期望在**剔除 CZ+LV** 后仍然成立（见 §2），说明这是数据窗口变化，不是实现回归。

## 1. 口径核查：测试意图 = lib 实现 = 客户端

1. **测试定义**（`tests/test_lib_atc_category.py:244`）：
   > `v0.10.3 #3 排序：Top-1 = 该类别里 active 产品最多的成分（方案 H）`。
2. **lib 实现**（`lib/search.py:689-730`）：`_ingredient_totals(prefixes)` 按 **`s.substance_id`** 统计
   `COUNT(DISTINCT p.product_id)`（`p.status='active'`，ATC 前缀命中），`_order_by_ingredient()`
   用卡内成分的 `max(totals)` 当排序权重；`_search_category()` / `_search_atc()` 传入该 `order`
   （`lib/search.py:942-945`、`:911-914`）。名字检索路径不受影响。
3. **期望生成器**（`tests/search_eval/gen_atc_category_cases.py:40-52`）：
   `top_substance()` 同样 `GROUP BY v.substance_id ORDER BY COUNT(DISTINCT p.product_id) DESC LIMIT 1`。
4. **线上客户端**（`site/build.py`，只读核对）：
   - `_cat_ing_totals()`（`site/build.py:14937-14953`）→ 16 大类 `cats[].ing`，`GROUP BY s.substance_id`；
   - `build_atc_ing_json()`（`site/build.py:15033-15051`）→ `data/idx/atc-ing.json`，`GROUP BY s.substance_id`，
     docstring 明写「**不合并成分**」。
5. **来源报告**：`reports/search-discovery-audit-20261110.md` §4.3（方案 H：24/24 类别用例）、
   §4.5（期望=该类别里 active 产品最多的成分）。

→ 这四条链路同源。**改 lib 排序 = 改口径**，且 lib/CI 会与线上客户端不一致（`build.py` 本任务禁改），
所以不能当作 bug 修；只能按「现查 DB」更新验收期望。

## 2. 现查 SQL 数字（全部 `status='active'`，2026-11-16 现查）

### 2.1 减肥药（`weight-loss`，prefixes = `A08` / `A10BJ` / `A10BX16`）

| 成分（substance 行） | 全市场 | 其中 CZ | 其中 LV | 剔除 CZ+LV | 名次（全市场） |
|---|---:|---:|---:|---:|---:|
| **Semaglutide** | **316** | 95 | 14 | 207 | **1** |
| Orlistat | 308 | 52 | 2 | 254 | 2 |
| Tirzepatide | 226 | 60 | 6 | 160 | 3 |
| Phentermine | 151 | 8 | 0 | 143 | 4 |
| Liraglutide | 120 | 46 | 1 | 73 | 5 |

→ **剔除 CZ+LV 时旧期望 `Orlistat 254 > Semaglutide 207` 成立**；加上新窗口后
`Semaglutide 316 > Orlistat 308`（差 8 条 = 2.6%）。新窗口给 Semaglutide +109、Orlistat +54。

### 2.2 抗抑郁药（`antidepressants`，prefixes = `N06A`）

| 成分（substance 行） | 全市场 | 其中 CZ | 其中 LV | 剔除 CZ+LV | 名次（全市场） |
|---|---:|---:|---:|---:|---:|
| **Duloxetine** | **866** | 203 | 5 | 658 | **1** |
| Escitalopram Oxalate | 844 | 546 | 0 | 298 | 2 |
| Venlafaxine | 815 | 0 | 2 | 813 | 3 |
| Mirtazapine | 777 | 215 | 5 | 557 | 4 |
| Sertraline | 595 | 0 | 4 | 591 | 5 |
| Venlafaxine Hydrochloride | 434 | 395 | 0 | 39 | 6 |
| Escitalopram | 364 | 0 | 8 | 356 | 8 |

→ **剔除 CZ+LV 时旧期望 `Venlafaxine 813 > Duloxetine 658` 成立**；加上新窗口后
`Duloxetine 866 > Escitalopram Oxalate 844 > Venlafaxine 815`。新窗口给 Duloxetine +208、
Venlafaxine +2（CZ 的 Venlafaxine 以「Venlafaxine Hydrochloride」单独一行入库，见 §5-1）。

### 2.3 交叉校验（lib 现算 vs SQL）

对同一 prefixes 调 `SearchIndex._ingredient_totals()`，结果与上表**逐项相同**：

```text
weight-loss       -> Semaglutide 316, Orlistat 308, Tirzepatide 226, Phentermine 151, Liraglutide 120
antidepressants   -> Duloxetine 866, Escitalopram Oxalate 844, Venlafaxine 815, Mirtazapine 777, Sertraline 595
```

`idx.search("减肥药")` 首卡 = `['Semaglutide']`；`idx.search("抗抑郁药"/"抗抑鬱藥")` 首卡 = `['Duloxetine']`。
旧期望成分并非「被排序挤掉」：Orlistat / Venlafaxine 的首张卡片分别落在 200 张卡的第 **54** 位
（排序按成分总量整组下移，符合"同成分相邻"的设计）。

复算 SQL（与 `_ingredient_totals` 同口径）：

```sql
SELECT s.inn_en, COUNT(DISTINCT p.product_id) AS n
FROM substance s
JOIN variant v ON v.substance_id = s.substance_id
JOIN product_component pc ON pc.variant_id = v.variant_id
JOIN product p ON p.product_id = pc.product_id AND p.status = 'active'
WHERE s.atc IS NOT NULL AND (s.atc LIKE 'A08%' OR s.atc LIKE 'A10BJ%' OR s.atc LIKE 'A10BX16%')
GROUP BY s.substance_id ORDER BY n DESC;          -- 减肥药；抗抑郁药把 WHERE 换成 s.atc LIKE 'N06A%'

-- 剔除 CZ+LV（复现旧窗口）：WHERE 再加 COALESCE(p.country,p.region) NOT IN ('CZ','LV')
```

## 3. 改动（3 处断言，0 处实现）

`tests/test_lib_atc_category.py`：

| 位置 | 改动 | 数字依据 |
|---|---|---|
| `:237`（12 词验收） | `减肥药`：Orlistat → **Semaglutide** | 316 vs 308（剔 CZ+LV：207 vs 254） |
| `:242`（12 词验收） | `抗抑郁药`：Venlafaxine → **Duloxetine** | 866 vs 815（剔 CZ+LV：658 vs 813） |
| `:264`（方案 H Top-1） | `抗抑鬱藥`：Venlafaxine → **Duloxetine** | 同上 |
| 模块 docstring / 两个测试 docstring | 补 v0.13.0 说明 + 数字 + 本报告路径 | — |

- `lib/search.py`：**未改**（`git diff -- lib/search.py` 为空）。
- 未写 DB、未改 `db/`、未改 `site/build.py`、未 commit、未发布、未写 `site/dist`。
- 断言未删除、未放宽：仍是 `assertIn(expected, res.cards[0].substances)`。

## 4. 验证

| 命令 | 结果 |
|---|---|
| `& $py -m unittest tests.test_lib_atc_category -v` | **22 tests OK**（红 2 → 0） |
| `& $py -m unittest discover -s lib -t lib` | **61 tests OK** |
| `& $py tests/trilingual/run_tests.py --quiet` | **72 例 / 69 通过 = 基线**；354 查询 Top-5 **98.6%** = 基线；跨国 72/72；**Top-1 93.2%（基线 95.5%，-8 条查询，见 §5-1，数据驱动、非本次改动）** |

trilingual 原文：

```text
== 汇总 ==
案例 72（通过 69）；查询 354 条：Top-5 命中 98.6%，Top-1 命中 93.2%；跨国可见 72/72；用时 613.7s
  en: 123 条查询, Top-5 121, Top-1 111 (98.4%)
  es: 116 条查询, Top-5 114, Top-1 108 (98.3%)
  zh: 115 条查询, Top-5 114, Top-1 111 (99.1%)
```

> 说明：trilingual 的 Top-1 下降**不是本次测试改动造成的**（本次只改 `tests/test_lib_atc_category.py`，
> trilingual 走 `lib/search.py` 名字检索，未改）。用 v0.13.0 之前的库
> `data/backups/drugs-20261115-095816.db`（507,434 产品 / 13 市场，无 CZ/LV）复跑同一批查询，
> 9 条查询从 rank 0 变 rank 1（见 §5-1），与新增市场里「盐型名 substance 行」产品数变大有关；
> Top-5 与案例通过数（69/72）均与基线相同，无新增案例失败。

## 5. 已知边界（本任务不改语义，建议 Lead 决定是否立项）

1. **substance 行拆分盐型（本次同时影响 ATC 类目排序与名字检索 Top-1）**：
   - 类目排序：`Venlafaxine` 815 与 `Venlafaxine Hydrochloride` 434 是两条 substance 行（同 ATC `N06AX16`），
     合并后 = **1,249 > Duloxetine 866**；`Escitalopram` 364 + `Escitalopram Oxalate` 844 = 1,208。
     若按「基础成分」合并，抗抑郁药 Top-1 仍是 Venlafaxine。
   - 名字检索（trilingual Top-1 95.5%→93.2% 的直接原因）：用 v0.13.0 前的备份库
     `data/backups/drugs-20261115-095816.db`（507,434 产品 / 13 市场）对比，**9 条查询从 rank 0 掉到 rank 1**，
     首卡都是「盐型名 substance 行」：`plavix` en/es（Clopidogrel Hydrogen Sulfate）、`glucophage` en
     与 `eucreas` es（Metformin Hydrochloride）、`zoloft` en（Sertraline Hydrochloride）、
     `cipralex` es（Escitalopram Oxalate）、`viagra` en/es（Sildenafil Citrate）、`imodium` en（Loperamide Hydrochloride）。
     其余 15 条 Top-1 未命中为既有 dup_inn/combo 缺口，与基线相同。
   - 但合并/重排会改 16 大类 + 所有 ATC 码 + 名字检索的排序语义（客户端 `atc-ing.json`/`cats[].ing` 同源），
     必须同步改 `site/build.py` 并重建站点 —— 本任务禁改，且远超"修 2 条红灯"的范围；
     数据侧属「盐型名 → 基础成分」规范化（`reports/2026-11-15-t17-inn-zh-salt-forms.md` 只做了中文名，英文 `inn_en` 未合并）。
   → 建议登记为后续数据规范化 / 检索排序任务，不在本次修红灯里动。
2. **产品数 = 目录覆盖度代理**：新市场目录粒度会放大某些成分（CZ 的 Semaglutide 95 条、Duloxetine 203 条），
   这是方案 H 的已知性质（v0.10.3 审核通过），不是 bug；若要"临床常用度"，需另加权重/信号，属产品决策。
3. **期望值稳定性**：减肥药前二差 8 条（2.6%）、抗抑郁药前二差 22 条（2.5%），下一个数据窗口仍可能翻转。
   建议后续把这两条期望改为「DB 现查派生」或留容差（本次按任务要求只更新字面值 + 注释，未扩范围）。
4. **trilingual 复跑成本**：本次实测 613.7 s（基线 626 s 量级），串行 `--jobs 1` 绕过本机命名管道限制。

## 6. 复现命令

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m unittest tests.test_lib_atc_category -v
& $py -m unittest discover -s lib -t lib
& $py db/q.py "SELECT s.inn_en, COUNT(DISTINCT p.product_id) AS n FROM substance s JOIN variant v ON v.substance_id=s.substance_id JOIN product_component pc ON pc.variant_id=v.variant_id JOIN product p ON p.product_id=pc.product_id AND p.status='active' WHERE s.atc LIKE 'N06A%' GROUP BY s.substance_id ORDER BY n DESC LIMIT 8"
```
