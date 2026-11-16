# Q10 客户端检索排序冒烟（`deploy/ui_sort_smoke.py`）

> 日期：2026-11-17 · 工位：pages-deploy · 任务：共享任务 task-2（Q10）
> 产物：`deploy/ui_sort_smoke.py`（新建，776 行）＋ `deploy/ci_checks.py`（只加一条 SKIP 安全钩子）

## 结论先行

1. **客户端「同名下基名优先」从人工冒烟变成可复跑门禁**：本机 `site/dist`（v0.13.2 产物）实跑
   **规则层 7/7 PASS、数据层 8/8 PASS、exit 0、16.7s**（`.tmp/pages-deploy-q10/ui-sort-final.json`）。
2. **门禁不空转**：把页面里的 `g3PreferBase()` 换成空函数（模拟规则失效）后，规则层 **4 条立刻 FAIL、
   exit 1、1.3s**（`--no-data`）。
3. **`ci_checks.py` 只加一条钩子**：全量模式的并行组多一项 `ui-sort`（实测 16.6s）；无 Chrome / 无产物自动
   SKIP，`--fast` 记 SKIP。全量实跑 **13 项 PASS / 0 FAIL / 260.0s**。
4. 顺带查出两条**现有问题**（本脚本只记 WARN、不阻塞，均不属 pages-deploy 改的范围）：
   - ① **两端去盐词表不一致**：页面 `G3_SALT_WORDS` 80 词 vs `lib/search.py` 87 词（缺 15 / 多 8）；
   - ② **Plavix / Cipralex 首行误挂「同名不同药」severe 徽章**：实为同一成分的基名/盐型两条记录没在构建期
     折起来（`site/build.py::SALT_WORDS` 缺 `hydrogen` / `oxalate`）→ 单成分品牌被打成「复方 / 同名不同药」。

## 0. 外部方案检索（AGENTS §12「先找现成工具再自研」）

| 候选 | 许可 / 依赖 | 结论 |
|---|---|---|
| **Playwright**（Python/Node 包） | Apache-2.0；需 `pip/npm install` + `playwright install` 下载浏览器（数百 MB） | **不采用**：与「无 npm / 无第三方依赖 / CI 只跑 stdlib」冲突，CI 无浏览器时还得另做 SKIP |
| **Selenium + chromedriver** | Apache-2.0；需额外匹配版本的 driver 二进制 | **不采用**：多一个版本敏感的二进制，本机换 Chrome 就断 |
| **Puppeteer** | Apache-2.0；Node 依赖 | **不采用**：本机没有 node（任务前提） |
| **本仓已有的 CDP 直连**（`deploy/ui_surface_check.py` 的 `Site` / `CDP` / `launch_chrome`） | 仓库自带、纯 stdlib、已在三处 UI 守卫里用 | **采用**：`ui_sort_smoke.py` 复用 `Site` + `CDP` + `pick_browsers`，只补一个「现取空闲端口」的 `boot()`（`ci_checks` 并行跑三个浏览器时不会抢 9427/9431 端口） |

## 1. 脚本做什么（三层断言）

| 层 | 内容 | 依赖 | 为什么这样判 |
|---|---|---|---|
| **① 规则层** | 在真浏览器里直接调页面导出的 `g3PreferBase(hits)`，喂 7 组合成 hits，断言换位结果 | 只要首页 + `assets/app.js` | 规则在客户端是一段 JS，**不依赖数据**就能验；规则被删/改坏/语义分叉立刻红 |
| **② 数据层** | 8 条真实查询：页内提交 → 读 `#reswrap table.res.rows tbody tr.br` 的 `td.c-ing` → 断言**首条候选卡的基名** | 产物里的 `core.json`（40 MB） | 复刻 v0.13.2 那次人工冒烟（5 条品牌查询看首行）+ 3 条反例 |
| **③ 词表一致性** | 页面 `G3_SALT_WORDS` vs `lib/search.py::SALT_WORDS` | 无需数据 | 「两端同一口径」要求词表同源；缺词会让盐型条目在页面上不换位 |

**判定口径（关键，别按整串相等判）**：客户端索引是**一个名字 key 一条**，`x`（成分列）是该名字下所有
产品的成分**并集**——例如 plavix 首行是 `Clopidogrel + Clopidogrel Hydrogen Sulfate`（有的市场登记基名、
有的登记盐型）；而且 `site/build.py::_sub_base_map()` 构建期已把部分盐型折成基名（glucophage 的 9 行全叫
`Metformin`）。所以数据层按客户端 `g3BaseKey()` 的**同一口径**把成分串折成基名集合再比
（`{clopidogrel}` == 期望 `{clopidogrel}` → 过），另配两条结构性断言：`salt-kept`（盐型不许被丢）与
`salt-order`（同一基名组内「盐型」标记只能 非盐 → 盐，不许回退 = `g3PreferBase` 的稳定分区语义）。

查询集（`CASES`，8 条）与期望值来源：**期望值不是从页面抄的**，按 `data/drugs.db` 现查成分 +
`lib/search.py` 服务端首卡对齐（第 3 节给命令与输出）。

## 2. 命令 / 实测输出 / 退出码 / 耗时

### 2.1 主命令（本机 `site/dist`，v0.13.2 产物）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py deploy/ui_sort_smoke.py --json .tmp/pages-deploy-q10/ui-sort-final.json
```

退出码 **0**，耗时 **16.7 s**（首次查询 12.57 s 在拉 40 MB `core.json`，其余每条 0.35–0.43 s）。
5 条盐型/基名对照的实测原文：

```text
== ① 规则层：直接调页面里的 g3PreferBase()（合成用例，不依赖数据）
  [PASS] 盐型在前 → 换位成基名在前（组外不动）
  [PASS] 全是盐型 → 顺序不变（没有基名条目可比）
  [PASS] 不同基名组不跨组重排
  [PASS] 复方：基名组合优先于盐型组合（只比对应成分）
  [PASS] 组内换位不影响别的行的相对顺序
  [PASS] 只有基名条目 → 顺序不变
  [PASS] 基名+盐型并集条目单独成组（与 lib/search.py 的 tuple 口径一致，不换位）

== ③ 词表一致性：页面 G3_SALT_WORDS vs lib/search.py SALT_WORDS
  [WARN] 页面 G3_SALT_WORDS 80 词 vs lib/search.py 87 词；客户端缺 15 词 [...]
    多 8 词 ['aluminium','aluminum','barium','copper','iron','lithium','selenium','zinc']

== ② 数据层：8 条真实查询
== q=plavix（salt-base）同名下基名与两种盐型并存，首行基名必须是 clopidogrel
  [PASS] 首行成分='Clopidogrel + Clopidogrel Hydrogen Sulfate'（基名 ['clopidogrel']，期望 ['clopidogrel']）
         候选前 4 行：Clopidogrel + Clopidogrel Hydrogen Sulfate（Plavix…） /
                     Clopidogrel Hydrogen Sulfate（PLAVIX 300 mg, comprimé pelliculé） /
                     Clopidogrel Hydrogen Sulfate（PLAVIX clopidogrel (as hydrogen sulfate) 300…） /
                     Aspirin + Clopidogrel + Clopidogrel Hydrogen Sulfate + Starch（COPLAVIX…）
== q=glucophage（salt-base）盐酸二甲双胍条目不占多数 → 首行基名必须是 metformin
  [PASS] 首行成分='Metformin'（基名 ['metformin']，期望 ['metformin']）  （共 9 行）
== q=cipralex（salt-base）草酸艾司西酞普兰 → 首行基名必须是 escitalopram
  [PASS] 首行成分='Escitalopram + Escitalopram Oxalate'（基名 ['escitalopram']，期望 ['escitalopram']）（共 4 行）
== q=viagra（salt-base）枸橼酸西地那非 → 首行基名必须是 sildenafil
  [PASS] 首行成分='Sildenafil'（基名 ['sildenafil']，期望 ['sildenafil']）  （共 8 行）
== q=imodium（salt-base）盐酸洛哌丁胺 → 首行基名必须是 loperamide
  [PASS] 首行成分='Loperamide'（基名 ['loperamide']，期望 ['loperamide']）  （共 20 行）
```

反例 3 条（不许被规则改动顺序，全部 PASS）：

```text
== q=tylenol（control）    [PASS] 首行成分='Acetaminophen'（共 20 行）
== q=amlodipine（control） [PASS] 首行成分='Amlodipine'（共 20 行）
== q=泰诺（control）        [PASS] 首行成分='Acetaminophen + Pseudoephedrine + Dextromethorphan + Chlorphenamine'
                                  （基名 4 段全等，共 3 行）

== 汇总：规则层 7/7 PASS；数据层 PASS 8 / FAIL 0；观察 WARN 6 条（不阻塞）；词表漂移（WARN，不阻塞），耗时 16.7s
```

### 2.2 各模式耗时（同一台机器，实测）

| 命令 | 说明 | 耗时 | 退出码 |
|---|---|---|---|
| `ui_sort_smoke.py`（默认 page-submit） | 规则 7 + 词表 + 数据 8 | **16.7 s** | 0 |
| `ui_sort_smoke.py --no-data` | 只规则层 + 词表（CI 钩子/秒级巡检） | **1.3 s** | 0 |
| `ui_sort_smoke.py --only plavix --no-rules` | 单条数据查询（首次拉 core） | 13.0 s | 0 |
| `ui_sort_smoke.py --only plavix,tylenol --deep-link --no-rules` | 每条各自导航 `?q=`（慢路径） | 24.9 s | 0 |
| `ui_sort_smoke.py --dist <不存在>` | SKIP 不判红 | 0.1 s | 0 |
| `ci_checks.py --fast` | 全量快检查（含 ui-sort 记 SKIP） | 13.3 s | 0 |
| `ci_checks.py`（全量） | 13 项，ui-sort 在并行组 | 260.0 s（ui-sort 16.6 s） | 0 |

### 2.3 期望值怎么来的（可复核）

```powershell
# a) 名字 → 成分（data/drugs.db 只读）
& $py -c "…"   # SQL 见下
```

```sql
select nk.norm, s.inn_en, count(*) as n
  from name_key nk
  join product_name pn on pn.key_id = nk.key_id
  join product_component pc on pc.product_id = pn.product_id
  join variant v on v.variant_id = pc.variant_id
  join substance s on s.substance_id = v.substance_id
 where lower(nk.norm) = lower(?)
 group by s.inn_en order by n desc, s.inn_en
```

| 查询 | 库里成分（条数） | `lib/search.py` 服务端首卡 | 脚本期望首行基名 |
|---|---|---|---|
| plavix | Clopidogrel 44 / Clopidogrel Hydrogen Sulfate 23 / Clopidogrel Bisulfate 4 | `PLAVIX · Clopidogrel · GB` | clopidogrel |
| glucophage | Metformin Hydrochloride 97 / Metformin 29 | `GLUCOPHAGE · Metformin · GB` | metformin |
| cipralex | Escitalopram 40 / Escitalopram Oxalate 38 | `CIPRALEX · Escitalopram · GB` | escitalopram |
| viagra | Sildenafil 102 / Sildenafil Citrate 30 | `VIAGRA · Sildenafil · GB` | sildenafil |
| imodium | Loperamide Hydrochloride 11 / Loperamide 8 | `IMODIUM · Loperamide · GB` | loperamide |
| tylenol | Acetaminophen 1 | `TYLENOL FILM COATED TABLETS 500MG · Acetaminophen · SG` | acetaminophen |
| amlodipine | Amlodipine 279 | `AMLODIPINE · Amlodipine · GB` | amlodipine |
| 泰诺 | Acetaminophen + Pseudoephedrine + Dextromethorphan + Chlorphenamine（7 个产品同一组合） | `泰诺 · 同 4 段组合 · CN` | 同 4 段 |

> 服务端首卡用只读方式取（`sqlite3.connect` 被拦成 `mode=ro`，照 `tests/trilingual/run_tests.py` 的写法），
> 输出见 `.tmp/pages-deploy-q10/probe_search.py` 的运行记录。

## 3. 门禁不空转的证据（canary）

「规则层」如果只是恒绿就没意义，所以做了负向验证：把产物首页复制一份，在 `</body>` 前插一段
「等 `g3PreferBase` 出现后把它换成空函数」的脚本，再用 `--override` 指过去（**只读**：`site/dist` 不动）：

```powershell
& $py .tmp/pages-deploy-q10/make_nog3_page.py     # 生成 .tmp/pages-deploy-q10/index-nog3.html
& $py deploy/ui_sort_smoke.py --override "index.html=.tmp/pages-deploy-q10/index-nog3.html" --no-data
```

```text
⚠ 预览模式：index.html ← .tmp/pages-deploy-q10/index-nog3.html（只用于验证门禁本身会不会红…）
  [FAIL] 盐型在前 → 换位成基名在前（组外不动）
         期望 ['Clopidogrel', 'Clopidogrel Hydrochloride', 'Ibuprofen']，实测 ['Clopidogrel Hydrochloride', 'Clopidogrel', 'Ibuprofen']
  [FAIL] 不同基名组不跨组重排
  [FAIL] 复方：基名组合优先于盐型组合（只比对应成分）
  [FAIL] 组内换位不影响别的行的相对顺序
  [PASS] 全是盐型 → 顺序不变 / 只有基名条目 → 顺序不变 / 并集条目单独成组
== 汇总：规则层 3/7 PASS；数据层 PASS 0 / FAIL 0；…耗时 1.1s
```

退出码 **1**，耗时 **1.3 s** ⇒ 规则失效时门禁会红，且能定位到「哪一条用例、期望什么、实测什么」。

补丁页是临时脚本生成的（`.tmp/` 不入库，下面这段可以自己在任意产物首页重做：把 `</body>` 前插进去即可）：

```html
<script>
(function(){ var n=0; var t=setInterval(function(){
  if (typeof g3PreferBase === 'function') { window.g3PreferBase = function(){}; clearInterval(t); }
  else if (++n > 300) { clearInterval(t); }
}, 20); })();
</script>
```

## 4. `ci_checks.py` 改了什么（只加一条 SKIP 安全钩子）

只动三处（不碰任何判定逻辑）：

1. `SUMMARY_ORDER` 增加 `"ui-sort"`（打印在 `first-screen` 之后）；
2. 新增 `check_ui_sort()`（照 `check_ui_surface` 的写法）：脚本缺失 → SKIP；`DIST_PATH` 不存在 → SKIP；
   跑 `ui_sort_smoke.py --dist <DIST_PATH> --json .tmp/ui-sort/ci.json`；输出里出现 `[SKIP]` → SKIP；
   解析汇总行 → PASS/FAIL（exit 0 且两句「词表漂移（WARN」会写进明细）；
3. 全量模式的并行组加一项：`ui-surface ∥ first-screen ∥ **ui-sort** ∥ i18n`；
   `--fast` 分支照 ui-surface/first-screen 的惯例记一条 `SKIP`（fast 仍是 13 项，不增加耗时）。

实测（两个模式都跑过）：

```text
# --fast：ui-sort 记 SKIP，13 项 PASS 8 / FAIL 0 / SKIP 5，13.3s
[SKIP] ui-sort            --fast 跳过（要拉无头 Chrome，全量才跑）

# 全量：13 项 PASS 0 FAIL，260.0s
[PASS] ui-sort            规则层 7/7、数据层 8 通过、WARN 6 条（明细 .tmp/ui-sort/ci.json）；
                          两端去盐词表有差异（WARN，需 site/build.py 工位对齐）
  16.6s  ui-sort
```

失败分支也单独验过（把 `ci_checks._run` 用假输出喂进 `check_ui_sort()`）：记录成
`('FAIL', 'ui-sort', '规则层 4 条不过（exit 1）：- FAIL [rule] …')`，能定位到用例。

> 口径说明：exit 2（采集异常：core 索引等不到 / 页面没有结果表）在钩子里记 **FAIL** —— 全量模式下产物必然
> 存在，出现采集异常就是真问题（重跑一次即可分辨是不是抖动）。CI（GitHub Actions）没有 `site/dist`，
> 钩子会在「无产物」处 SKIP，不会红。

## 5. 两条现有问题（本脚本只记 WARN，需别的工位决定）

### 5.1 两端去盐词表不一致（页面 80 词 vs `lib/search.py` 87 词）

```text
客户端缺 15 词：asparto, bisulfate, butyrate, cypionate, decanoate, edetate, enantate,
                heptanoate, laurate, nitrite, oleate, phenylpropionate, phosphate, sulfite,
                undecylenate
客户端多  8 词：aluminium, aluminum, barium, copper, iron, lithium, selenium, zinc
                （这些在服务端是 SALT_ELEMENTS，只做「基名护栏」用，不是盐型词）
```

影响：服务端会把 `Clopidogrel Bisulfate`、`Sodium Phosphate` 这类条目参与基名优先换位，页面上不会
（`g3BaseName('Clopidogrel Bisulfate')` 实测返回 `clopidogrel bisulfate`）。CHANGELOG v0.13.2 写的是
「浏览器端与服务器同一口径」，词表层面并不完全一致。**建议给 site-ui 工位**：把 `build.py` 的
`G3_SALT_WORDS` 与 `lib/search.py::SALT_WORDS` 对齐（或抽成同一份常量），对齐后本脚本可用
`--strict-words` 把这一项变成阻塞。

### 5.2 Plavix / Cipralex 首行误挂「同名不同药 / 复方」徽章（P1 展示层）

页面实测（`--lang=en`，首行商品名列）：

```text
plavix   → brand="PlavixSame name, different drugCombination"
           badges=[{cls:"badge sev", txt:"Same name, different drug"}, {cls:"tag combo", txt:"Combination"}]
cipralex → brand="Cipralex 10mg tabletsSame name, different drugCombination"（同样两个徽章）
```

`core.json` 里这两条索引的真实字段：

```text
plavix   l='severe' vs=['clopidogrel','clopidogrel-hydrogen-sulfate']
         cu='combo/clopidogrel+clopidogrel-hydrogen-sulfate.html' x='Clopidogrel + Clopidogrel Hydrogen Sulfate'
cipralex l='severe' vs=['escitalopram','escitalopram-oxalate']
         cu='combo/escitalopram+escitalopram-oxalate.html' x='Escitalopram + Escitalopram Oxalate'
```

根因（只读核对 HEAD 的 `site/build.py`）：

```text
build.py 构建期 SALT_WORDS 含 'hydrogen': False   ← Clopidogrel Hydrogen Sulfate 折不掉
build.py 构建期 SALT_WORDS 含 'oxalate' : False   ← Escitalopram Oxalate 折不掉
build.py 构建期 SALT_WORDS 含 'bisulfate': True / 'hydrochloride': True（其余多数能折）
```

即：`_sub_base_map()` 的 `SALT_WORDS` 比 `lib/search.py` / 客户端 G3 词表都窄，缺 `hydrogen`、`oxalate`
等词 → 盐型没折成基名 → 条目 `vs` 长度 2 → 被当复方 → `collision` 判 `severe` → 单个活性成分的品牌
（Plavix、Cipralex）在结果页被打上「同一个名字挂了多种活性成分、不可互换」的红标 + 组合标签 + 组合页链接。
这和「只做身份对应与不可互换警示」的精神相反（**过度警示**），属于 site-ui（`site/build.py`）的范围。

修法建议（给 site-ui）：`SALT_WORDS` 补 `hydrogen` / `oxalate`（与 `lib/search.py` 对齐），重新构建后
plavix/cipralex 条目的 `x` 应变成单一 `Clopidogrel` / `Escitalopram`、`vs=None`、`l='info'`、无组合页。
**本脚本的期望值对这种修法是稳的**：数据层比的是「基名集合」，`Clopidogrel` 与
`Clopidogrel + Clopidogrel Hydrogen Sulfate` 折完都是 `{clopidogrel}`。
（另：`COPLAVIX` 条目的成分里出现 `Starch`，辅料进了成分表，属数据侧口径问题，建议数据工位核。）

## 6. 已知限制 / 缺口

1. **依赖本机 Chrome 路径探测**：复用 `ui_interaction_smoke.pick_browsers()`（注册表 → PATH →
   Program Files/LOCALAPPDATA → Edge）。本机实测 `chrome.exe` + `msedge.exe` 都在；一个都没有就
   `[SKIP] … 退出码 0`（照 `ui_surface_check.py` 惯例，不判红）。
2. **无 node 也能跑**：规则是页面里的 JS，本脚本用 CDP `Runtime.evaluate` 在真浏览器里求值，
   不需要 node / npm（这是选 CDP 直连而非 Playwright/Puppeteer 的主要原因）。
3. **数据层只覆盖「首行基名 + 组内顺序 + 盐型不丢」**：不验整表逐行顺序、不验分页/折叠/导出、
   不验 ATC/大类入口（那两个入口走分组表 `table.res.grouped`，本脚本只认扁平表 `table.res.rows`）。
4. **固定 `lang=en`**：成分列用英文 INN 才好在期望值里写死；中文/西语显示由
   `ui_interaction_smoke` 的第 5 项（语言切换）与 `i18n_check` 覆盖，本脚本不重复。
5. **首次查询要拉 40 MB `core.json`**（本机 12.6 s）：`--deep-link` 是每条都导航，8 条约 95 s；
   默认 page-submit 模式只拉一次，所以整轮 16.7 s。CI 钩子用默认模式（16.6 s）。
6. **期望值会随数据变**：`CASES` 里的 8 条来自 2026-11-16 的 `data/drugs.db`；数据大改（新市场/成分合并）后
   若某条不再成立，先按第 2.3 节的 SQL 复核再改期望，别直接改成页面现状。
7. **词表漂移默认不阻塞**（WARN）：词表对齐归 `site/build.py`；需要阻塞时加 `--strict-words`
   （届时 `ci_checks` 里那一条也要跟着加参数）。
8. **误报徽章只记 WARN**：5.2 属展示层问题，改成阻塞只需把 `validate_rows()` 里那条 WARN 搬进 `checks`
   （一行改动，报告留了位置）；现在不建议直接红，否则会挡住下一次发布构建。
9. **半成品产物按 SKIP 处理**：`--dist` 指向「有 `core.json` 但没有 `index.html`」的目录（构建还在跑、
   被中断，例如当时的 `.tmp/dist-r1r2`）时，脚本打印
   `[SKIP] 产物里没有 index.html：…（构建可能还在跑或未完成，等 == done == 再验）` 并退出 0 ——
   不会把「打开的是 404 页」误报成页面 bug。**本轮没能对 `.tmp/dist-r1r2` 做验收**（实测当时只有
   `assets/ data/ drug/ name/` 四个目录、没有 `index.html`，site-ui 的构建未完成）；构建到 `== done ==`
   后由 Lead 跑 `& $py deploy/ui_sort_smoke.py --dist .tmp/dist-r1r2` 复验即可。

## 7. 复现清单（复制即用）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py deploy/ui_sort_smoke.py --list                                   # 看 7 条规则用例 + 8 条查询
& $py deploy/ui_sort_smoke.py                                          # 主命令（16.7s）
& $py deploy/ui_sort_smoke.py --no-data                                # 只规则层（1.3s，CI 友好）
& $py deploy/ui_sort_smoke.py --only plavix,tylenol --json .tmp/q10.json
& $py deploy/ui_sort_smoke.py --dist .tmp/dist-r1r2                    # 验别的产物（只读）
& $py deploy/ui_sort_smoke.py --base-url http://127.0.0.1:8000/        # 验已起的服务
& $py deploy/ui_sort_smoke.py --strict-words                           # 词表漂移也判红

# 门禁自检（负向）：规则被换成空函数 → 必须红
& $py .tmp/pages-deploy-q10/make_nog3_page.py
& $py deploy/ui_sort_smoke.py --override "index.html=.tmp/pages-deploy-q10/index-nog3.html" --no-data

# 接进 CI 入口（全量模式并行组里，无 Chrome/无产物自动 SKIP）
& $py deploy/ci_checks.py --fast
& $py deploy/ci_checks.py
```

**发布前必跑**（若不想依赖 ci_checks 的钩子）：
`& $py deploy/ui_sort_smoke.py --dist site/dist`（exit 0 才算过）。

## 8. 涉及文件

- 新建：`deploy/ui_sort_smoke.py`（三层断言 + `--only/--no-data/--no-rules/--deep-link/--override/
  --strict-words/--json/--list`，纯 stdlib，只读）
- 修改：`deploy/ci_checks.py`（`SUMMARY_ORDER` + `check_ui_sort()` + 全量并行组 + `--fast` 记 SKIP）
- 证据（不入库）：`.tmp/pages-deploy-q10/ui-sort-final.json`、`.tmp/ui-sort/ci.json`、
  `.tmp/pages-deploy-q10/ci-full.log`
