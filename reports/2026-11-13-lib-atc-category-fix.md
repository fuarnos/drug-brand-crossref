# 修 `lib-atc-category` 长期红：重建 CATEGORY_SNAPSHOT + 接进 `--fast`

> 工位：search-alias · task-26 · 2026-11-13 · 随 **v0.11.3** 验证，不单独发版
> 上游：[reports/2026-11-12-v0112-ci.md](2026-11-12-v0112-ci.md) §2.1（v0.11.2 发布前 CI 发现该条红）
> 未跑 build / publish / sync；未改 `site/build.py`；未动数据与 dist。

---

## 0. 结论先行

1. **根因确认**：`CATEGORY_SNAPSHOT.aliases` 是**手工镜像**，v0.10.3 把 66 条口语别名接进构建后
   一直没重建 → 16/16 个大类与产物不一致，差的 65 条正好是 `66 − 1 条防遮蔽白名单`。
2. **修法不是「把 97 条重抄一遍」，而是让 aliases 变成派生**：`[官方英文 label, 大类 id, *该类口语别名]`，
   与 `site/build.py:11544` 同一口径。手工镜像这份数据源直接删掉 —— 漂移这一类问题在结构上不再可能复发。
3. 为保住 `source` 三分类语义，`match_category()` 的 alias 循环**跳过口语词**，
   让它们仍旧由 colloquial 分支认领（行为与 v0.10.3 逐条一致，见 §5 抽查表）。
4. **测试转绿**：`tests.test_lib_atc_category` **22 项 OK（43.7 s）**；`lib` 套件 **61 项 OK**；
   `etl` 套件 55 项 OK（顺带确认没被牵连）。
5. **接进 `--fast`**：`ci_checks --fast` 现在跑 `CategoryMatchTest` 这一组
   （**4 例 0.008 s**，不碰 DB / Chrome），整体 **PASS 8 / FAIL 0 / SKIP 4，11.9 s，exit 0**。
   新增耗时 **0.1 s**（要求 <1 s）。
6. 顺带拆掉一个雷：`tests/gen_categories.py` 停在 v0.7.1 模板，**再跑一次会把 lib 覆盖回旧版**
   （丢防遮蔽白名单与派生逻辑）。已改为拒绝执行 —— 见 §7，如不认可可单独回退这一处。

---

## 1. 根因

`tests/test_lib_atc_category.py:54` 的 `test_snapshot_sync_with_dist` 逐字段比对
`lib/categories.py` 的 `CATEGORY_SNAPSHOT` 与构建产物 `site/dist/data/categories.json`。

构建侧（`site/build.py:11540-11544`）：

```python
colloquial = colloquial_aliases_by_category()          # 66 条口语词按大类分组，已剔除 1 条白名单
aliases = [labels.get("en", ""), cat["id"], *colloquial.get(cat["id"], [])]
```

lib 侧（修复前）：每条大类手写 `'aliases': [官方英文 label, 大类 id]` —— **只有前两项**。

结果：

| | 条数 |
|---|---:|
| 构建产物 `aliases` 合计 | 97 |
| lib 快照 `aliases` 合计 | 32（16 × 2） |
| 差 | **65 = `COLLOQUIAL_ALIASES` 66 − `NAME_KEY_SHADOW_EXCEPTIONS` 1（`antibiotic`）** |
| 受影响大类 | **16 / 16（全部）** |

时间线：v0.10.3（2026-11-09）把口语别名接进构建 → 快照没重建 → 该用例红了 **3 个版本**
（v0.10.3 / v0.11.0 / v0.11.1 / v0.11.2）没人发现，因为它只在 `ci_checks.py` **全量模式**跑，
`--fast` 里直接记 `SKIP`（原 `ci_checks.py:263-264`）。

---

## 2. 修法：把 aliases 变成派生，而不是重抄

先验证了构建公式能否精确复现产物（含顺序）：

```
全部 16 类可由 [en_label, id, *colloq] 精确复现: True      # .tmp/check_formula.py
```

既然产物本来就是「快照里已有的两个字段 + 词表」算出来的，就没有理由再手抄第三份。改动：

```python
# lib/categories.py：删掉 16 行 'aliases': [...] 字面量，改为
_COLLOQUIAL_BY_CAT: dict[str, list[str]] = colloquial_aliases_by_category()
_COLLOQUIAL_WORDS: frozenset[str] = frozenset(COLLOQUIAL_ALIASES)

for _cat in CATEGORY_SNAPSHOT:
    _cat["aliases"] = [_cat["labels"]["en"], _cat["id"],
                       *_COLLOQUIAL_BY_CAT.get(_cat["id"], [])]
del _cat
```

为什么不用 `tests/gen_categories.py` 重跑生成：那份模板停在 v0.7.1，
`NAME_KEY_SHADOW_EXCEPTIONS` / `is_shadowed()` / `colloquial_aliases_by_category()` 全都不在里面，
跑一次会把这些功能覆盖掉（这也是它被退役的原因，见 §7）。

**守卫仍然有效**：`test_snapshot_sync_with_dist` 继续拿 lib 的 `aliases` 跟真实产物逐字段比。
派生的只是「该有的值」，产物是否真按这个公式写进去，仍由这条用例判定 ——
例如哪天 `site/build.py` 改了 label 来源或拼接口径，它照样变红。

---

## 3. 改动清单与 diff 规模

| 文件 | 增 | 删 | 说明 |
|---|---:|---:|---|
| `lib/categories.py` | 34 | 19 | 删 16 行 aliases 字面量；加派生块（含注释）；`match_category` 加口语词跳过；模块 docstring 更新 |
| `deploy/ci_checks.py` | 9 | 3 | `--fast` 从 SKIP 改为跑 `CategoryMatchTest`；顶部分层说明同步 |
| `tests/gen_categories.py` | 44 | 145 | 退役为拒绝执行（145 行模板 → 31 行说明），见 §7 |

`lib/categories.py`：298 行（改前 283）。

---

## 4. 测试结果

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py -m unittest tests.test_lib_atc_category      # Ran 22 tests in 43.686s | OK   exit 0
& $py -m unittest discover -s lib -t lib           # Ran 61 tests in 5.079s   | OK   exit 0
& $py -m unittest discover -s etl -t etl           # Ran 55 tests in 0.031s   | OK   exit 0（未被牵连）
```

改前：`tests.test_lib_atc_category` → `Ran 22 tests … FAILED (failures=1)`，卡在 `antihypertensives 的 aliases 与构建产物不同步`。
改后：22/22 通过。

快照与产物逐字段对照（`.tmp/diff_cat_aliases.py`）：`id 集合一致: True`，16 类无任何差异行；
`aliases` 合计 97 = 产物 97。

---

## 5. 行为一致性（`source` 语义没变）

派生的副作用：`cat["aliases"]` 现在**包含口语词**，而 `match_category()` 的 alias 循环排在
colloquial 循环之前 —— 不处理的话「退烧药」会被判成 `source="alias"`，`source` 三分类语义就变了
（`tests/test_lib_atc_category.py:84` 与 `:199` 都会红）。所以在 alias 循环里加一句跳过：

```python
for alias in cat.get("aliases") or []:
    if alias in _COLLOQUIAL_WORDS:
        continue        # 口语词留给下面的 colloquial 分支，source 语义不变
    ...
```

抽查（`.tmp/spot_source.py`，与 v0.10.3 行为逐条一致）：

| 查询 | 大类 | source |
|---|---|---|
| 退烧药 / 消炎药 / 他汀 | analgesics / antibiotics / statins | **colloquial** |
| 胃药 / 降糖药 / 降压药（本身就是官方 zh label） | acid-related / diabetes / antihypertensives | **label** |
| antibiotic（防遮蔽白名单） | —（走药名检索） | None |
| antibiotics / statins / Statins | antibiotics / statins | label |
| C07 / lipitor / 空串 | — | None |

附加断言：`口语词是否都不被判成 alias: True`（65 条全部）。

---

## 6. `--fast` 接入

### 6.1 diff

```diff
--- a/deploy/ci_checks.py
+++ b/deploy/ci_checks.py
@@ check_unittests()
-    # 2026-11-10 提速：这条要 47 s（占 fast 的 65%），挪到全量模式；判定逻辑没动。
-    if fast:
-        record("SKIP", "unittest:lib-atc-category", "--fast 跳过（47 s，全量才跑）")
-    else:
-        _run_unittest("unittest:lib-atc-category", ["tests.test_lib_atc_category"])
+    # 2026-11-10 提速：整条模块要 47 s（占 fast 的 65%），挪到全量模式；判定逻辑没动。
+    # 2026-11-12（v0.11.3）：这里长期 `--fast` 记 SKIP 是有代价的 —— CATEGORY_SNAPSHOT
+    # 与产物漂移了 16/16 个大类，红了 3 个版本没人看见（reports/2026-11-13-lib-atc-category-fix.md）。
+    # 现在快模式改跑 CategoryMatchTest：纯 Python、不碰 DB/Chrome，0.01 s 就能抓住快照漂移；
+    # 全量仍跑整个模块（含 SearchIndex 的 47 s DB 用例）。
+    if fast:
+        _run_unittest("unittest:lib-atc-category",
+                      ["tests.test_lib_atc_category.CategoryMatchTest"])
+    else:
+        _run_unittest("unittest:lib-atc-category", ["tests.test_lib_atc_category"])
```

顶部「分层」说明同步改成：`fast（≤25 s）… + unittest:lib-atc-category（快照同步那组，0.01 s）`，
全量注明跑「整模块（重，47 s）」。

### 6.2 为什么只跑 `CategoryMatchTest`

整模块 47 s 的耗时全在 `AtcCategorySearchTest` / `NameKeyShadowTest`（要开 DB、建 SearchIndex），
而**快照漂移只跟 `CategoryMatchTest` 有关**（4 例：`test_snapshot_sync_with_dist`、
`test_four_language_labels`、`test_colloquial_aliases`、`test_no_false_positive`），纯 Python、无依赖。
CI 里没有 `site/dist` 时 `test_snapshot_sync_with_dist` 自己 `skipTest`，不会误红。

### 6.3 实测

```
[PASS] unittest:lib-atc-category Ran 4 tests in 0.008s | OK（0.1s）
…
12 项：PASS 8 / FAIL 0 / SKIP 4（总 11.9s · mode=fast · dist=site/dist）
EXIT=0
```

- 改前：该行 `[SKIP] --fast 跳过（47 s，全量才跑）`，fast 是 `PASS 7 / SKIP 5`。
- 改后：`[PASS]`，**新增耗时 0.1 s**（unittest 内 0.008 s），远低于 <1 s 的要求；总时长 11.9 s 仍在 ≤25 s 预算内。

---

## 7. 顺带处理：`tests/gen_categories.py` 退役

发现它是一颗雷：该脚本把一份**内嵌的 v0.7.1 模板** `write_text()` 覆盖到 `lib/categories.py`。
模板里没有 `NAME_KEY_SHADOW_EXCEPTIONS` / `is_shadowed()` / `colloquial_aliases_by_category()` /
`assert_no_unlisted_shadow()`，也没有这次的派生块 —— **今天跑一次就会把修好的东西全部回退**。

处理：改为拒绝执行（exit 2），并在 docstring 里写明历史、退役原因、以及「现在改了构建侧配置该怎么同步」。
已实测：运行它 `EXIT=2`，`lib/categories.py` 的 sha256 前后一致（未被改动）。

> 若认为这一处超出本任务范围，可单独 `git checkout -- tests/gen_categories.py` 回退；
> 但请保留「不要运行它」这条约定，否则下次有人照着老报告
> （`reports/lib-atc-category-search.md:142` 还写着 `& $py tests\gen_categories.py`）跑一次就会把快照打回原形。

---

## 8. 边界与没做

- **未跑全量 `ci_checks`**（约 4 分钟）：本改动只碰 lib 与 `--fast` 分支，全量分支的判定逻辑一行没动
  （`else:` 里仍是 `tests.test_lib_atc_category` 整模块）。随 v0.11.3 发布前由 Lead 跑一次全量即可。
- **未跑 trilingual**：口语表与匹配口径都没变（§5 抽查已覆盖 65 条口语词的 source 归属），
  且 trilingual 用的是 `lib/search.py` 的检索路径，本次没碰。
- **未改 `site/build.py`**：构建侧公式（`build.py:11544`）保持原样，是 lib 去对齐它，不是反过来。
- **未接 `deploy/ci_checks.py` 之外的门禁**：GitHub Actions 跑的是同一个 `ci_checks.py`，
  所以 CI 的 `--fast` 也会自动带上这条（CI 无 dist 时该用例自动 skip，不会误红）。
- 首屏 / 交互冒烟与本条无关，仍需在能起 CDP 的环境另行验证（见 v0.11.2 CI 报告 §2.3）。

---

## 9. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 快照 vs 产物逐字段（应只剩 "id 集合一致: True"，无差异行）
& $py .tmp\diff_cat_aliases.py

# 构建公式能否精确复现产物（16 类应全 True）
& $py .tmp\check_formula.py

# source 语义抽查
& $py .tmp\spot_source.py

# 测试三连
& $py -m unittest tests.test_lib_atc_category
& $py -m unittest discover -s lib -t lib
& $py -m unittest discover -s etl -t etl

# 快检门禁
& $py deploy/ci_checks.py --fast

# 已退役的生成器（应 exit 2 且不改文件）
& $py tests\gen_categories.py
```
