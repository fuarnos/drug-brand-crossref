# T16 / H1：品牌页「释放方式」结论落到具体产品记录（v0.11.8 P0）

> 工位：site-ui　｜　任务：共享任务 task-1　｜　日期：2026-11-15
> 改动文件：`site/build.py`（只有这一个源码文件）＋ 本报告与同目录 6 个探针脚本。
> 未提交、未发布、未写 `site/dist`、未动 `data/` 与 `etl/`、`lib/`。

## 0. 结论（先看这 7 条）

1. **根因不是「渲染层没锁记录」，而是 `release='none'`（来源未记录）被当成一种释放方式参与比较。**
   `collision` 视图按 `COUNT(DISTINCT p.release) > 1` 分级，`'none'` 也算一个 distinct 值 ——
   于是「1 种已知释放方式 + 其余记录未标注」也会被判成 `warning`，页面再把 `warning` 固定写成
   「Different release — not interchangeable」。
   现查：925 个 `warning` 名字页里，**850 页属于「1 种已知码 + 未标注」**，只有 **75 页**真有 ≥2 种已知释放方式。
2. **泰诺林那一行**（用户评审原始截图）的「成分相同，释放机制不同，不可互换」来自
   `_key_releases()` 把 `{none}` 过滤成 `{}` 之后，与另一侧的 `{ER}` 比较 —— 一侧**没有任何释放记录**，
   另一侧 4 条 ER + 8 条未标注，两边都不是「每条记录都锁定到某一释放方式」。
3. **改法**：释放方式结论只在**两侧都能锁定到具体记录**时出现（该侧已知释放码恰好 1 种、且该侧没有
   未标注记录）；否则输出中性提示「请选择具体产品」，不说「不同」，也不说「不可互换」。
4. `fam.rel.release`（品牌对照表「关系说明」列）在现网 **2 行 → 0 行**，同样两行改为 `fam.rel.multi_unknown`；
   `fam.rel.same / partial / diff` 一行未动（9 / 6 / 4）。
5. 名字页顶部 `warning` 条纹 **925 页全部改写**：850 页 → 「释放方式未逐条记录 — 请选择具体产品后再对照」，
   75 页 → 「多种释放方式 — 请选择具体产品后再对照」（后者若同侧还有未标注记录，再补一句
   「部分记录未标注释放方式」）。**`severe`（同名不同药）条纹一字未动**，抽样页 before/after 逐字节一致。
6. 顺带修掉同源的另外两处「品牌级释放结论」：检索结果行的「释放机制不同」徽标（**925 → 75 条**，
   只有真有 ≥2 种已知释放码的条目才贴）、T11 对照框（`?pick=&pmk=`）的「释放」行（锁定 1:1 才给
   相同/不同，否则「选择具体产品」）。
7. 7 条新文案 **en / es / zh / zh-Hant 四语齐（另补 fr）**；`deploy/i18n_check.py` **FAIL 0**、
   五语各 **622 键**、zh-Hant 无回落；`unittest lib` 61 项、`unittest etl` 55 项全过；
   `ci_checks.py --fast` **PASS 8 / FAIL 0 / SKIP 4**（与改前同）。

## 1. 现查基线（可复核）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# ① trade name key 里 release 有多种的 key（与 Lead 给的 844 一致）
& $py db/q.py "SELECT COUNT(*) FROM (SELECT pn.key_id FROM product_name pn JOIN product p ON p.product_id=pn.product_id WHERE pn.name_type='trade' GROUP BY pn.key_id HAVING COUNT(DISTINCT p.release)>1)"
# ② collision 分级
& $py db/q.py "SELECT level, COUNT(*) FROM collision GROUP BY level"
# ③ warning 页按「已知释放码数 × 是否有未标注记录」分组的现查脚本
& $py reports/2026-11-15-t16-count2.py
```

| 指标 | 现查值 |
|---|---|
| `product.release` 取值分布 | `none` 467,387 / `ER` 17,796 / `DR` 9,618 / `MR` 191（合计 494,992；`none` = 未记录，占 **94.4%**） |
| trade name key 中 `release` 有多种（含 none） | **844** |
| `collision` 分级 | info 177,566 / severe 25,088 / **warning 925** |
| warning 页：1 种已知码 + 有未标注记录 | **850 页 / 28,441 行未标注** |
| warning 页：2 种已知码（无未标注） | 23 页 |
| warning 页：2 种已知码 + 有未标注 | 48 页 |
| warning 页：3 种已知码 + 有未标注 | 4 页 |
| warning 页：0 种已知码 | 0 页 |
| 泰诺林（`泰诺林`）记录 | ER 4 条 + `none` 8 条（全部 CN） |
| Tylenol Extra Strength（`tylenol extra strength`）记录 | `none` 26 条（CA 2 / US 24） |

## 2. 代码改动（`site/build.py`，169 增 / 15 删）

| 位置 | 改动 |
|---|---|
| `RELEASE_UNKNOWN` + `_key_releases()` | 新增常量 `frozenset({"none",""})`；`_key_releases()` 只返回**已知**释放码（原来只去掉 `"none"`，语义写清） |
| `_release_unrecorded(subs)`（新） | 该侧是否存在「释放方式未标注」的记录 |
| `_key_release_locked(subs)`（新） | 该侧能否锁定到唯一释放方式 = 已知码恰好 1 种 且 无未标注记录 |
| `_family_relation()` | 成分集合相同、且释放集合不同时：两侧都 locked → `fam.rel.release`（原结论）；否则 `fam.rel.multi`（≥2 种已知码）或 `fam.rel.multi_unknown`（只有 1 种 + 未标注）。释放集合相同仍回 `fam.rel.same`（这句只说「活性成分相同」，不含释放主张） |
| `_family_rel_html()`（新） | 关系说明单元格：中性提示 + （仅 multi 情形）「部分记录未标注释放方式」 |
| `_release_variant_notice()`（新） | 名字页 `warning` 条纹：≥2 种已知码 → 「多种释放方式」；1 种 + 未标注 → 「释放方式未逐条记录」；0 种已知码 → 不出条纹 |
| `build_name_pages()` 的 `banner` | `warning` 分支从固定字符串改为调用上面的函数；`severe` 分支原样保留 |
| `_family_block()` | 关系列改用 `_family_rel_html()`（原来直接拼 `<span data-i18n="{rel_key}">`） |
| `APP_JS`：`brandRowHTML` / `flatRowHTML` | 「释放机制不同」徽标加条件：条目 `e.rl` 里 ≥2 个已知释放码才贴（`e.l==='warning'` 不足为证） |
| `APP_JS`：`t11RelList` + `t11CompareHTML` | 新增 `t11RelList()`（逗号分隔的已知码 → 数组）；「释放」行改走 `relRow()`：两侧各只 1 种才 same/diff，否则 `cmp-b multi`「选择具体产品」，任一侧未记录仍报「未收录」 |
| `UI_I18N` ×4 + `FR_I18N` | 7 条新 key（见 §5） |
| CSS | `.cmp-b.multi{color:var(--muted);border-style:dashed}`、`.rel-why{…}`（与现有 tokens 一致，未另起一套） |

红线：没有新增用药建议 / 剂量换算 / 可替代判断；结论仍只由数据（`release` 字段、成分集合）推导，
没有手工标注；`collision` 视图本身未改（不属于本工位作用域）。

## 3. 受影响面 before / after

| 位置 | before | after |
|---|---|---|
| 品牌对照表 `fam.rel.release`（全站） | **2 行** | **0 行** |
| 品牌对照表 `fam.rel.multi_unknown` | 0 行 | **2 行**（泰诺林 2 个成员行） |
| 品牌对照表 `fam.rel.same / partial / diff` | 9 / 6 / 4 | 9 / 6 / 4（未动） |
| 名字页 `warning` 条纹「Different release — not interchangeable」 | **925 页** | **0 页** |
| ├ 「释放方式未逐条记录」条纹 | 0 | **850 页** |
| └ 「多种释放方式」条纹 | 0 | **75 页**（其中 52 页带「部分记录未标注」） |
| `severe` 条纹 | 25,088 个 key | 不变（抽样 `alcohol` / `sodium-fluoride` 逐字节一致） |
| 检索结果行「释放机制不同」徽标 | 925 条 | **75 条** |
| T11 对照框「释放」行 | 品牌汇总 join 后用 `a===b` 判 same/diff | 两侧各 1 种才判，否则「选择具体产品」 |

复现：

```powershell
# 品牌对照表逐行现状（before/after 都跑同一脚本；after 的数字见上表）
& $py reports/2026-11-15-t16-count.py           # JSON：family_rel_keys / family_rows_total …
& $py reports/2026-11-15-t16-count2.py          # warning 页分组（SQL 口径）
```

> 说明：`fam.rel.multi`（≥2 种已知码的中性提示）在现网品牌表里**暂时 0 行** —— 9 个品牌家族 / 21 行里
> 没有这种组合；它是这条规则的安全分支（将来家族变大时会用到），不是死代码。

## 4. before / after DOM 片段

> **口径说明（抽样 3 页为什么不是「存在多种释放方式」）**：任务的验收文字写的是「改为『存在多种释放方式，
> 请选择具体产品』」，但现查数据里 tylenol-extra-strength / lyrica / lamictal 这三页**只有 1 种已知释放方式**
> （ER），另一部分记录压根没记 release —— 真说「存在多种释放方式」是另一种形式的不实结论，与 H1 要修的
> 毛病同源。所以中性提示按记录状况分两句：**≥2 种已知码**用「存在多种释放方式，请选择具体产品」
> （`fam.rel.multi` / 「多种释放方式」，如 §4.3 depakote）；**只有 1 种已知码 + 其余未标注**用
> 「释放方式未逐条记录，请选择具体产品」（`fam.rel.multi_unknown` / 「释放方式未逐条记录」）。
> 两句话都不下「相同/不同」与「可互换」结论、都引导用户去选具体产品，符合 goal 2 的语义；
> 若 Lead 要求这三页也出现「存在多种释放方式」字样，请回一句，我改成统一文案（不建议）。

渲染方式（不跑全量构建）：直接调用 `site/build.py` 里的 `build_name_pages()` 渲染指定名字页；
before 侧把 T16 改掉的 4 个函数在内存里换回旧实现（同一份源码、同一份数据，只切 T16 逻辑）：

```powershell
$env:T16_OLD='1'; & $py reports/2026-11-15-t16-render.py site/build.py .tmp\t16-before "tylenol extra strength,lyrica,lamictal,depakote"
$env:T16_OLD='0'; & $py reports/2026-11-15-t16-render.py site/build.py .tmp\t16-after  "tylenol extra strength,lyrica,lamictal,depakote"
& $py reports/2026-11-15-t16-dom-diff.py
```

### 4.1 `/name/tylenol-extra-strength.html`（品牌对照表 · 泰诺林那一行）

```html
<!-- before -->
<td data-label="Relation" data-i18n-label="fam.cmp_rel">
  <span data-i18n="fam.rel.release">Same active ingredients, different release — not interchangeable</span>
</td>
<!-- after -->
<td data-label="Relation" data-i18n-label="fam.cmp_rel">
  <span data-i18n="fam.rel.multi_unknown">Release not recorded for every product — pick a specific product</span>
</td>
```

zh 用户看到的是 `fam.rel.multi_unknown` 的简体值：**「释放方式未逐条记录，请选择具体产品」**。
整页 5,974 B → 5,980 B（+6 B，只这一行变化）。

### 4.2 `/name/lyrica.html`、`/name/lamictal.html`（顶部条纹）

```html
<!-- before -->
<div class="notice"><b data-i18n="badge.warning">Different release</b><span data-i18n="name.warning"> — not interchangeable.</span></div>
<!-- after -->
<div class="notice"><b data-i18n="name.rel_unknown_title">Release partly unrecorded</b><span data-i18n="name.rel_note"> — pick a specific product to compare</span></div>
```

zh：**「释放方式未逐条记录 — 请选择具体产品后再对照」**。lyrica 3,653 B → 3,685 B（+32 B）；
lamictal 3,491 B → 3,523 B（+32 B）。

### 4.3 `/name/depakote.html`（真有 ≥2 种已知释放方式的 75 页之一）

```html
<!-- before -->
<div class="notice"><b data-i18n="badge.warning">Different release</b><span data-i18n="name.warning"> — not interchangeable.</span></div>
<!-- after -->
<div class="notice"><b data-i18n="name.rel_multi_title">Multiple release types</b><span data-i18n="name.rel_note"> — pick a specific product to compare</span></div>
```

zh：**「多种释放方式 — 请选择具体产品后再对照」**。2,959 B → 2,986 B（+27 B）。

### 4.4 `severe` 条纹不变（goal 4）

```powershell
# alcohol / sodium-fluoride 两页 before/after 逐字节一致
alcohol.html:        identical=True (sha256 E4689F5FBC71CD09…)
sodium-fluoride.html identical=True (sha256 D52130B4001812AD…)
```

### 4.5 T11 对照框（`?pick=` / `?pmk=` 深链的逐项对照 · 释放行）

真机浏览器需要整站索引（`data/idx/core.json` 42 MB + 分片），本轮**不写 `site/dist`、不跑全量构建**，
所以改成「从 `APP_JS` 里原样取出 `t11Subs / t11RelList / t11CompareHTML` 三段源码，套最小 stub 用 Node 跑」
（测的是要上线的那份 JS，不是复写的伪代码）：

```powershell
& $py reports/2026-11-15-t16-t11-harness.py
```

| 用例（「你这条」→ 目标市场） | 释放行渲染 | 判定 |
|---|---|---|
| A 你 ER / 目标市场 IR + ER（多个候选） | `<span class="cmp-b multi">Pick a product</span>` | PASS（无 same/diff） |
| B 你 ER / 目标 ER（两条记录都锁定） | `<span class="cmp-b same">Same</span>` | PASS |
| C 你 ER / 目标 IR（两条记录都锁定） | `<span class="cmp-b diff">Different</span>` | PASS |
| D 你 ER,DR（多种）/ 目标 ER | `<span class="cmp-b multi">Pick a product</span>` | PASS |
| E 你 ER / 目标未记录 | `<span class="cmp-b miss">Not recorded</span>` | PASS |

即：**构造 pick/pmk 深链、两侧都锁定到 1 种具体记录时仍出相同/不同（B/C）**；任一侧多种或未记录就不出结论（A/D/E）。

## 5. 四语文案（新增 7 键，五语齐）

| key | en | zh | zh-Hant |
|---|---|---|---|
| `fam.rel.multi` | Multiple releases recorded — pick a specific product | 存在多种释放方式，请选择具体产品 | 存在多種釋放方式，請選擇具體產品 |
| `fam.rel.multi_unknown` | Release not recorded for every product — pick a specific product | 释放方式未逐条记录，请选择具体产品 | 釋放方式未逐條記錄，請選擇具體產品 |
| `fam.rel.multi_why` | some records do not state a release type | 部分记录未标注释放方式 | 部分記錄未標註釋放方式 |
| `name.rel_multi_title` | Multiple release types | 多种释放方式 | 多種釋放方式 |
| `name.rel_unknown_title` | Release partly unrecorded | 释放方式未逐条记录 | 釋放方式未逐條記錄 |
| `name.rel_note` | pick a specific product to compare | 请选择具体产品后再对照 | 請選擇具體產品後再對照 |
| `t11.multi` | Pick a product | 选择具体产品 | 選擇具體產品 |

es / fr 见 `reports/2026-11-15-t16-i18n-keys.py` 的输出。旧键 `badge.warning` / `name.warning`
**保留未删**（检索行徽标仍用 `badge.warning`；`name.warning` 现在全站无引用，留着便于回滚，
下一轮清理时再删并同步 5 份字典）。

校验：

```powershell
& $py reports/2026-11-15-t16-i18n-keys.py
# → zh-Hant 只能回落简体的 key: 0 个；缺失: 无；键数 en/es/zh/zh-Hant/fr = 622/622/622/622/622
& $py deploy/i18n_check.py
# → 有效字典 622 键 ×5；FAIL 0 / WARN 2 / INFO 24（与改前一致，2 条 WARN 是 form.kit / form.gas 的历史项）
```

## 6. 测试与命令（本轮实跑）

| 检查 | 命令 | 结果 |
|---|---|---|
| 语法 | `& $py -m py_compile site/build.py` | exit 0 |
| 四语一致性 | `& $py deploy/i18n_check.py` | **FAIL 0 / WARN 2 / INFO 24**（同基线） |
| lib 单测 | `& $py -m unittest discover -s lib -t lib` | **Ran 61, OK**, exit 0 |
| etl 单测 | `& $py -m unittest discover -s etl -t etl` | **Ran 55, OK**, exit 0 |
| 快速全局 | `& $py deploy/ci_checks.py --fast` | **PASS 8 / FAIL 0 / SKIP 4**（改前同） |
| 名字页 DOM | `reports/2026-11-15-t16-render.py` + `…-dom-diff.py` | 4 页 only-intended-lines diff |
| T11 对照框 | `reports/2026-11-15-t16-t11-harness.py` | 5/5 PASS |

体积回归（名字页）：只有 warning 页与品牌表行变，单页 **+27 ~ +32 B**；
按 850×32 + 75×27 + 2×6 估算全站名字页 **≈ +29 KB**（`core.json` / 分片索引不含这些文案，不受影响）。
含 `?v=` 的构建版本号会因 `build.py` 内容变化而全站换号（v0.11.4 以来每次改模板都如此）。

## 7. 缺口 / 需要 Lead 接手的事

1. **全量构建与首屏守卫未跑**：本工位按规则不写 `site/dist`、不跑全量构建（约 20 分钟 / 1 GB）。
   `deploy/first_screen_check.py`（改前/改后各一次）与页数 / 索引 / 首屏体积回归需在 Lead 的全量构建上做。
   预期影响：名字页正文只多 27–32 B，AFCR 与首屏条目不应变化。
2. **T11 端到端（真浏览器 + 真索引）未跑**：本轮用 Node 直测上线 JS（§4.5）。若 Lead 要浏览器证据，
   可在全量构建后开 `?q=lyrica&pick=lyrica&pmk=US&country=<市场>` 看 `#cmp` 释放行。
3. **925 页少了「不可互换」表述**：按任务 goal 2「不得输出『释放方式不同 / 不可互换』这类结论」，
   warning 条纹里不再有「not interchangeable」。若产品口径希望名字页**始终**有一句
   「同名不代表可互换」，建议单独建任务加一句页面级提示（不在本任务里夹带）。
4. `collision` 视图把 `'none'` 当成一种释放方式参与分级（925 个 warning 里 850 个由此而来）。
   改视图属 `db/schema.sql` 作用域，**本轮未动**；建议单独立项评估（会影响 `collision` 计数口径与
   README/About/CHANGELOG 的数字）。

## 8. CHANGELOG 草稿（v0.11.8 建议条目）

- **「释放方式不同」不再拿整个品牌下结论**：品牌页只在**两边都能锁定到具体产品记录**时才说释放方式相同/不同；
  其余情况改成「请选择具体产品」的中性提示（925 个名字页里 850 个其实是「来源没记释放方式」，不是真的不同）。
- **检索结果与“逐项对照”同步收紧**：结果行的「释放机制不同」徽标只在条目真有 ≥2 种已知释放方式时出现
  （925 → 75 条）；对照框的「释放」行两侧各锁定 1 种才给相同/不同。
