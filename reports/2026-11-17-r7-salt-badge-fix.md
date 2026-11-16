# R7 盐型词表补齐：Plavix / Cipralex 首行误挂「同名不同药」徽章（v0.13.3）

> 工位：site-ui ｜ 任务：task-6 ｜ 改动文件：`site/build.py`（SALT_WORDS +2 词，其余零改动）
> 不动 `lib/search.py`、不动数据、不写 `site/dist`。

## 结论

1. **根因确认**：`site/build.py` 的 Python `SALT_WORDS` 是 85 词，`lib/search.py` 是 87 词，
   缺的正是 **`hydrogen`** 和 **`oxalate`**（JS 侧 `G3_SALT_WORDS` 早就有这两个，所以排序对、徽章错）。
   于是 `Clopidogrel Hydrogen Sulfate` 只剥掉 `sulfate`，剩下 `clopidogrel hydrogen`（基名不存在）
   → 没折成 `clopidogrel` → 同一基名被当成两个成分 → 索引条目 `x` = 「Clopidogrel + Clopidogrel
   Hydrogen Sulfate」→ 客户端按 `l='severe'` 挂「同名不同药」+ 复方标签。
2. **改法**：只补词表（85 → 87，与 lib 完全一致），归并口径不变 —— 仍由 `_salt_base_of()` 剥尾部
   盐/水合物词，仍要求「拆盐后基名在 substance 表里存在」才并（`_sub_base_map` 的 `by_norm` 判定），
   真复方（多成分 `+`）不参与这条路径，不会被折平。
3. **顺带对齐客户端词表**（`--strict-words` 的要求）：`APP_JS` 的 `G3_SALT_WORDS` 原来是 80 词
   （含 8 个元素名、缺 15 个盐/水合物词），`--strict-words` 判红。现在客户端词表**逐字等于**
   `lib/search.py::SALT_WORDS`（87 词），元素名（钠/钾/钙…）单独放 `G3_ELEMENT_SET` 并在初始化时
   并进 `G3_SALT_SET`（去盐行为不变，实测 `diclofenac sodium → diclofenac` 仍成立）。
4. **效果**：Plavix / Cipralex 首条候选行从「Clopidogrel + Clopidogrel Hydrogen Sulfate（severe + combo）」
   变成单成分基名行、无徽章；`ui_sort_smoke.py` 数据层 exit 0、`--strict-words` 也 exit 0。

## 1. 词表对齐（现查，不照抄）

```
& $py -X utf8 .tmp\r7_salt_diff.py
site/build.py SALT_WORDS: 85 词   →   改后 87 词
lib/search.py SALT_WORDS: 87 词
lib 有、build 缺: ['hydrogen', 'oxalate']
build 有、lib 没有: []
```

客户端（`APP_JS`）的 `G3_SALT_WORDS` 原来也不一致（`ui_sort_smoke --strict-words` 现查）：

```
改前：页面 G3_SALT_WORDS 80 词 vs lib 87 词；
      客户端缺 15 词 ['asparto','bisulfate','butyrate','cypionate','decanoate','edetate','enantate',
                     'heptanoate','laurate','nitrite','oleate','phenylpropionate','phosphate','sulfite','undecylenate']
      客户端多 8 词 ['aluminium','aluminum','barium','copper','iron','lithium','selenium','zinc']（元素名）
改后：G3_SALT_WORDS = 87 词（与 lib 逐字一致，脚本 .tmp\r7_align_js_words.py 从 lib 直接生成）；
      元素名留在 G3_ELEMENT_SET、初始化时并入 G3_SALT_SET（G3_SALT_SET = 95 = 87 + 12 − 4 重复）。
```

JS 侧 `g3BaseName()` 实测（改后）：`Clopidogrel Hydrogen Sulfate → clopidogrel`、
`Escitalopram Oxalate → escitalopram`、`Metformin Hydrochloride → metformin`、
`Diclofenac Sodium → diclofenac`（元素名仍参与去盐）。


## 2. 归并口径没有放宽（Python 直接调用现查）

```
& $py -X utf8 .tmp\r7_probe.py
  escitalopram-oxalate         Escitalopram Oxalate          → base=escitalopram
  clopidogrel-hydrogen-sulfate Clopidogrel Hydrogen Sulfate  → base=clopidogrel   ← 改后新增折叠
  clopidogrel-bisulfate        Clopidogrel Bisulfate         → base=clopidogrel
  clopidogrel-besilate         Clopidogrel Besilate          → base=clopidogrel
  clopidogrel                  Clopidogrel                   → base=clopidogrel
```

只影响「尾部是盐/水合物词、拆完基名在 substance 表里存在」的名字；复方行（`+` 连接的多成分）
不走这条路径。

## 3. 改前证据（`site/dist` = v0.13.2 产物）

```
& $py -X utf8 deploy\ui_sort_smoke.py --dist site/dist --json .tmp\r7-before-smoke.json
== 汇总：规则层 7/7 PASS；数据层 PASS 8 / FAIL 0；观察 WARN 6 条；词表漂移（WARN，不阻塞）
```

首行 DOM（JSON 里的 `cases[].top[0]`）：

| 查询 | 改前首行成分 | 改前首行徽章 |
|---|---|---|
| plavix | `Clopidogrel + Clopidogrel Hydrogen Sulfate` | `badge sev` Same name, different drug + `tag combo` Combination |
| cipralex | `Escitalopram + Escitalopram Oxalate` | `badge sev` Same name, different drug + `tag combo` Combination |
| glucophage | `Metformin` | 无 |

## 4. 改后证据（最终产物 `.tmp/dist-r1r2`）

```
& $py -X utf8 deploy\ui_sort_smoke.py --dist .tmp\dist-r1r2 --json .tmp\r7-after-smoke.json
== 汇总：规则层 7/7 PASS；数据层 PASS 8 / FAIL 0；观察 WARN 6 条（不阻塞）  → exit 0

& $py -X utf8 deploy\ui_sort_smoke.py --dist .tmp\dist-r1r2 --strict-words
  [PASS] 两端词表一致（87 词）
== 汇总：规则层 7/7 PASS；数据层 PASS 8 / FAIL 0；观察 WARN 6 条（不阻塞）  → exit 0
```

改前 / 改后逐条对照（同一套查询，首行成分 + 首行徽章，数据来自两份 smoke JSON）：

| 查询 | 行数（前→后） | 首行成分（前 → 后） | 首行徽章（前 → 后） |
|---|---|---|---|
| plavix | 4 → 4 | `Clopidogrel + Clopidogrel Hydrogen Sulfate` → `Clopidogrel` | `Same name, different drug` + `Combination` → **无** |
| cipralex | 4 → 4 | `Escitalopram + Escitalopram Oxalate` → `Escitalopram` | `Same name, different drug` + `Combination` → **无** |
| glucophage | 9 → 9 | `Metformin` → `Metformin` | 无 → 无 |
| viagra | 8 → 8 | `Sildenafil` → `Sildenafil` | 无 → 无 |
| imodium | 20 → 20 | `Loperamide` → `Loperamide` | 无 → 无 |
| tirzepatide / augmentin / tylenol / amlodipine | 不变 | 不变 | 不变 |
| 泰诺（反例：真复方 4 成分） | 3 → 3 | `Acetaminophen + Pseudoephedrine + Dextromethorphan + Chlorphenamine` | `Combination` → **`Combination`（保留，没被折平）** |

- 用例总行数 **88 → 88**（没有条目被并掉/丢掉，只是成分串与徽章变了）；
- 首行徽章数合计 **5 → 1**（剩下的 1 个是「泰诺」的合法 `Combination`）；
- 真复方（`Loperamide + Simeticone`、`Acetaminophen + Diphenhydramine` 等）在候选集里仍是复方行、
  仍挂 `Same name, different drug` / `Combination` —— 只折叠「拆盐后基名相同」。

## 5. 对产物的影响（构建到 `== done ==`）

| 指标 | 改前 `site/dist` | 改后 `.tmp/dist-r1r2` | 差 |
|---|---|---|---|
| 页面数（.html） | 137,101 | 137,093 | −8 |
| 文件数 | 137,331 | 137,323 | −8 |
| 复方页 | 7,469 | 7,462 | −7（`clopidogrel + clopidogrel hydrogen sulfate` 这类「同成分盐型」不再算复方） |
| sitemap URL | 75,592 | 75,585 | −7 |
| `core.json` raw / gz | 40,243,026 / 9,232,865 | 40,239,135 / 9,232,615 | −3,891 / −250 |
| `assets/app.js` gz | 66,186 | 67,474 | +1,288（词表 80→87 + 三个去盐函数说明） |

## 6. 已知缺口

1. **`--strict-words` 现在是硬门槛**：以后改 `lib/search.py::SALT_WORDS` 必须同步改 `site/build.py` 的
   `G3_SALT_WORDS`（客户端）与 `SALT_WORDS`（服务端），`deploy/ui_sort_smoke.py --strict-words` 会红。
   本轮没动 `lib/`，词表已 87=87 对齐。
2. `G3_SALT_SET` = 87 + 12 元素名 − 4 重复 = 95（元素名照样参与去盐，`diclofenac sodium → diclofenac` 不回归）；
   若以后 lib 增加元素名，这里的并集行为不变（元素表独立）。
3. 本轮只修「同一基名的盐型被当成不同成分」这一类误报；`collision` 视图本身没改（仍是 DB 单一真相源）。
