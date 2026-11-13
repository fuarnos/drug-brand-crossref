# T10/T12 独立复核（源码级第二意见，2026-11-14）

> 任务：task-8。对 `site-ui` 本轮 T10/T12 交付做**独立复核**——不看它的报告结论，自己跑命令。
> 只读：不改实现文件、不构建、不写 `site/dist`、不写库、不 commit。
> 复核对象：工作区未提交改动（`HEAD` = `90981b193f3 docs: 需求登记硬规则…`）。
> 探针脚本：`reports/2026-11-14-t10-independent-review.ratio-probe.py`（只读连接 `mode=ro`，可复跑）。

## 结论先行：**源码 + 产物级 PASS，可进入发布流程**；无阻塞项，5 条非阻塞建议（1 条建议发布前改文案）

| # | 复核项 | 结论 |
|---|---|---|
| 1 | 越界 | **PASS** —— `etl/` `lib/` `db/`（tracked）零改动；`collision` 仍是视图、无手工标注表；`data/drugs.db` 未被写（mtime 停在 11-12） |
| 2 | 归整窄口 | **PASS** —— `_snap_strength` 就是方案的三条窄口，未放宽；SQL 复算 **137 行 / 54 值**、41 个 500.x **41/41 全在窗内**；16 条单测独立跑 OK |
| 3 | 原始值可追溯 | **库侧 PASS / 页面侧 FAIL（P2 文案）** —— 499.9996 在库仍 31 行、也没再当主规格；但「原记录」小字**全站 0 次**（只在有矩阵的页面渲染），CHANGELOG 那句不成立，见 §3.2 + 建议 S1 |
| 4 | 红线措辞 | **PASS** —— 新增 20 个 i18n 键全是「不可互换 / 身份对应」方向；无换算、无替代推荐、无剂量建议；复方行只列「成分 + 各自含量」，无求和；`collision`/`dose_warning` 逻辑一字未改；产物级扫描 0 命中 |
| 5 | 数字对账 | **PASS** —— `core.json` 46,295,974 B、`acetaminophen.html` 238,208 B 与我实测**逐字节一致**；`960 mg/30 mL` 命中 4 页 |
| 6 | 矩阵 922→812 | **可接受**（不建议为这版阻塞）：实测站内 **812** 页仍带 `#tableview`；这是新分组键的算术副作用，不是有意砍功能；用「只看单方行」的 ratio 可把 878/929 页救回（见 §6） |

**与我的方案不一致但可接受的三处**（site-ui 收紧，均有代码注释说明）：
1. `fs` 每 key 最多 **3** 组（方案 §3.4 写 4）→ 体积优先；`tylenol extra strength` 的 liquid 恰在第 3 组内，靶点仍能显示（§5 实测确认）。
2. `COMBO_ROWS_PER_BLOCK=5`（方案 §5.4 建议 8）→ 更紧，方向正确。
3. **「规格待核实」徽标默认关闭**（方案 §6 假定 T15 清单驱动）→ 机制已就绪、构建期零渲染（实测 0 页）；已在需求队列 G2 登记「补 `base_fraction`/`salt_code` 后再开」。**这意味着用户 §1.4 那条本轮不会被「修」**——发布说明里不要暗示已修，见建议 S4。

---

## 1. 越界（PASS）

**命令**：`git status --short` / `git diff --stat` / `git diff --stat -- etl lib db`

| 检查 | 实测 | 判定 |
|---|---|---|
| 实现改动落点 | `site/build.py`（+803/−117，857 行变更）、新增 `tests/test_spec_grouping.py`、`data/release_notes_i18n.json`（Lead 允许） | PASS |
| Lead 记账类改动 | `CHANGELOG.md`（+8：v0.11.6 五条）、`docs/谷段需求队列.md`（+6：G1–G4）、`docs/跟进提醒.md`（+6） | 非 site-ui 实现范围，不作越界 |
| `etl/` `lib/` `db/` | `git diff --stat -- etl lib db` → **空**（零改动） | PASS |
| `db/schema.sql`、`db/init_db.py` | 文件 mtime 仍是 **2026-11-11**，未被本轮碰 | PASS |
| `data/drugs.db` | `LastWriteTime = 2026/11/12 09:20:08`（今天 11-14 构建只读），452,550,656 B | PASS |
| `collision` 仍是视图 | `SELECT type,name … name='collision'` → `view`；视图体仍是 `COUNT(DISTINCT v.substance_id)` / `release` 推导（无人工列） | PASS |
| 无手工标注表 | `sqlite_master` 里 20 张表全是既有表（`artg_entry…variant`，含 `cleanup_cn_*` 三张历史清理表，来源 `db/cleanup_cn_data.py`）；匹配 `manual/anno/override/curated` → 0 行 | PASS |
| 视图一致性 | DB 3 个视图（`alias_all`/`collision`/`coverage`）= `db/schema.sql` 的 3 个 `CREATE VIEW` | PASS |
| 新增未跟踪文件 | `data/sources/{name_spec_conflict,precision_normalize}_20261114.csv`（T15 产出）、`db/list_spec_issues.py`（T15 只读脚本，头注 `mode=ro`、不写库）、`tests/test_spec_grouping.py`（本轮单测）、`reports/*`、`docs/img/v0115-before-*.png`（构建前基线截图） | 均属对应工位/记账，PASS |

---

## 2. 归整窄口（PASS）

**源码**（`site/build.py:9211`，`_snap_strength`）：

```python
if v is None or v < 1:
    return v
r = v.to_integral_value(rounding=ROUND_HALF_UP)
dev = abs(v - r)
if dev <= Decimal("0.01") and dev <= Decimal("0.00002") * r:
    return r
return v
```

与方案 §4.1 **逐条一致**（`v≥1` ∧ `|dev|≤0.01` ∧ `|dev|≤2e-5·r`），没有第四条、没有环境变量旁路。

**旁路检查**：`_normalized_strength` 的两条分支都过 `_snap_strength`，但**只有真的归整时才换写法**（非重量单位分支 `if snapped != num` 才重排格式），其余保持 `_fmt_qty` 原样 → 不会「顺手改了 12 万页的数字写法」。

**SQL 复算**（`db/q.py`，只读）：

```sql
SELECT COUNT(*) rows_aff, COUNT(DISTINCT ROUND(strength_value,6)) vals,
       GROUP_CONCAT(DISTINCT p.country) mks
FROM product_component pc JOIN product p ON p.product_id=pc.product_id
WHERE pc.strength_value>=1 AND pc.strength_value<>ROUND(pc.strength_value)
  AND ABS(pc.strength_value-ROUND(pc.strength_value))<=0.01
  AND ABS(pc.strength_value-ROUND(pc.strength_value))<=2e-5*ROUND(pc.strength_value);
-- → 137 | 54 | CA,AU      （与方案 §4.2 完全一致）
```

41 个 500.x：`ABS(strength_value-500)<0.01 AND <>500` → **41 行，全部 41 行落在窗内**。
反例仍在窗外（`0.00025`/`469.01`/`100.008`/`666666.666667`），并被单测钉住（`tests/test_spec_grouping.py:65-78`）。

**独立跑单测**：`python -m unittest tests.test_spec_grouping -v` → **Ran 16 tests … OK**（16/16 PASS）。

---

## 3. 原始值可追溯

### 3.1 库侧（PASS，现在可证）

| 检查 | 实测 |
|---|---|
| `product_component` 里 499.9996 | **31 行**仍在（样本 `AU-ARTG-153435`） |
| 500.x 全族 | **41 行**仍在（未被库内改写） |
| `strength_value` 是否被批量改 | 无：`data/drugs.db` mtime = 11-12，本次构建只读 |

### 3.2 产物侧（**部分不成立**，P2 文案问题，不阻塞发布）

构建进程于 **09:54:30 左右退出**（`site/dist` 稳定：125,515 文件 / 946.4 MiB，`sitemap.xml`/`checksums.txt`/`whats-new.html` 均写于 09:53–09:54）。实测：

| 检查 | 实测 | 判定 |
|---|---|---|
| `product_component` 里 499.9996 | **31 行**仍在（全部是 `acetaminophen` 的 AU 记录） | 库侧 PASS |
| 500.x 全族 | **41 行**仍在，未被库内改写 | PASS |
| 页面里 `499.9996` 是否仍是主规格 | `site/dist/drug/` + `site/dist/name/` 命中 **0 个文件** → 已经不是主规格 | PASS（靶点达成） |
| 「原记录 499.9996 mg」小字是否出现 | **全站 0 次**。`class="m-orig"` 只出现在 **138 个成分页**（都是 task-16 单位换算那批，且有内嵌矩阵）；含归整行的 **45 个成分页里 0 个**有该小字（acetaminophen 页也无矩阵） | **FAIL（相对 CHANGELOG 的承诺）** |
| `datapackage.json` 里 499.9996 | **不含**（该文件 22,660 B，是 Frictionless 描述文件，本来就不装行值） | 口径需澄清 |
| `site/dist/data/**` 里 499.9996 | **0 个文件**（`core.json` 存的是显示串；`detail-*.json` 是抽样桶，未见该值） | 原值只在库内 |

**机制原因**（读源码定位）：`_strength_origin_html()` 全站**只有一个调用点**（`site/build.py:9796`，矩阵行 `st_html`），而矩阵只在 `multi_ratio >= 0.40` 的页面才输出；列表视图（v0.10.3 起的主视图）不渲染「原记录」小字。acetaminophen 页没有矩阵 → 那 31 行的原值在页面上**无处可追溯**。

**建议 S1（P2，发布前改 1 句文案即可，不必改代码）**：CHANGELOG v0.11.6 第 3 条现在写「同时保留可追溯的『原记录 499.9996 mg』小字；数据库与数据包里的原始值一个都不改」，实测只对「数据库」成立。改成：
> 「…显示成 `500 mg`；**数据库里的原始值一个都不改**（只影响显示，判定规则窄口写死：仅接近整数且偏差极小的值）。」
> 若想保留小字承诺，则需在列表行也调用 `_strength_origin_html`（受影响仅 137 行 / 45 页，体积可忽略），属下一版改动。

---

## 4. 红线措辞（PASS）

**扫法**：`git diff -U0 -- site/build.py` 取全部 **742 行新增**，正则命中 `替代|推薦|推荐|應服用|应服用|换算|換算|互换|互換|等效|equivalent dose|recommended dose|you should take|switch to|replace with|substitut|interchangeab|convert|conversion|总和|合计剂量|mg/kg`。

**结果**：命中 22 行，**逐条都是否定句或代码注释**，无一条给出建议/换算/可替代：

- 新增 i18n 一律走「不可互换」方向：`fam.rel.diff`「活性成分不同，不可互换」/ `fam.rel.partial`「成分部分相同，不是同一复方，不可互换」/ `fam.rel.release`「成分相同，释放机制不同，不可互换」；`fam.cmp_intro`「下表只做身份对应——不是翻译对照，也不代表这些产品可以互换」。
- T10 五个新键：`matrix.multi_form`「多剂型」、`drug.mono_section`「仅含此成分」、`drug.combo_section`「含此成分的复方」、`matrix.spec_conflict`「规格待核实」、`name.form_spec`「规格（按剂型）」——**全是身份信息，零建议**。
- 代码注释里出现「换算」都在说明「不做换算」：`_spec_text` docstring「只做显示，不改数据、不做换算」；`_combo_line_html` docstring「不做换算、不求和、不判断能否互换」。

**结构性证据（比词表更硬）**：

| 检查 | 实测 |
|---|---|
| 复方行是否做算术 | `_combo_line_html` 只做 `" + ".join(name + " " + 该成分自己的含量)`，无 `sum`/`total`/除法；单测还显式断言 HTML 里不含「合计/总量/换算/替代/等效」（`tests/test_spec_grouping.py:109`） |
| `collision` 结论是否被改写 | 视图定义零改动；`load_index` 仍 `SELECT key_id, level FROM collision`（`:8677`），统计仍 `SELECT COUNT(*) FROM collision WHERE level='severe'`（`:14388`）；diff 里 `collision` 只出现在**注释**（说明页面不再出现「碰撞」这个内部术语） |
| `dose_warning` 是否被动过 | diff 新增/删除行里 **0 处** `dose_warning` |
| 页面是否仍在教「可互换」 | 品牌页新表 `fam.rel.same`「活性成分相同」不带「不可互换」，但同表 `fam.cmp_intro` 与页脚 notice 已声明「不代表可以互换」 → **见建议 S3（非阻塞）** |

---

## 5. 数字对账（构建已完成，09:54 实测）

| 项 | Lead/site-ui 报的数 | 我实测 | 判定 |
|---|---|---|---|
| `core.json` raw | 46,295,974 B | **46,295,974 B** | **完全一致** |
| `acetaminophen.html` | 238,208 B | **238,208 B** | **完全一致** |
| `960 mg/30 mL` 出现页数 | — | **4 个页面**：`drug/acetaminophen.html`、`name/acetaminophen.html`、`name/tylenol-extra-strength.html`、`name/泰诺林.html` | 靶点达成（v0.11.5 时 drug 页为 **0**） |
| `core.json` 口径说明 | 「48.7 → 46.3 MB dec」 | 我基线 43.15 **MiB** = 45.25 MB dec；新值 46.30 MB dec = **44.15 MiB**（+1.0 MiB） | 不矛盾，只是 MiB/MB 口径差；与方案 §3.5 预估（+1.5～2.0 MB）同量级 |
| 发布护栏（raw 11–50 MB） | — | 46.30 MB dec，余量 **3.7 MB** | 仍在护栏内；建议后续再加索引字段前先测体积 |
| 站点体积 | — | `dist` **125,515 文件 / 946.4 MiB**（构建前基线 929.0 MiB，**+17.4 MiB / +1.9%**） | 可控 |
| 成分页均体积 | — | 12,438 页 / 均 **12.8 KiB**（基线 12.3 KiB） | +4% |
| acetaminophen 页 | site-ui 目标 ≤240 KB | 232.6 KiB（238,208 B），基线 156.3 KiB → **+48.8%** | 达标（在 240 KB 线内） |
| 版本号 | v0.11.6 | `index.html` / `whats-new.html` 均含 `v0.11.6` | 一致 |

**产物一致性抽查（与方案 §7 逐条对）**：

| 检查 | 实测 |
|---|---|
| 索引行 `tylenol extra strength` | `n=26`、`f="multi"`、`s=["500 mg","960 mg/30 mL","500 mg/950 mg"]`、`fs=["tablet\|500 mg","capsule\|500 mg","liquid\|960 mg/30 mL"]` → 与方案 §3.4 ④ + §7-A 一致（`fs` 3 组上限生效，powder 落在 `+N 多剂型`） |
| 品牌页成分卡 | `Strength by dosage form: tablet 500 mg；capsule 500 mg；liquid 960 mg/30 mL；powder 500 mg/950 mg` → 与 §7-C 一致 |
| 品牌页关系表 | 3 行：`CA、US Tylenol Extra Strength → fam.rel.same`、`CN 泰诺 → fam.rel.partial`（成分列列出 4 个活性成分）、`CN 泰诺林 → fam.rel.release`；泰诺 / 泰诺林 各出现 **1 次**（T12 C4 去重生效） |
| 成分页分段 | acetaminophen 页 **18 个 `mkseg`**（mono/combo 各自成段），两段标题键都在 |
| 复方行成分串 | 形如「对乙酰氨基酚 250 mg + Amantadine 盐酸金刚烷胺」「对乙酰氨基酚 500 mg + Diphenhydramine…」→ 全部成分 + 各自含量，无求和 |
| 冲突徽标 | 全站 `data-spec-conflict` 命中 **0 页** → 默认关闭生效，不会误报 |
| 红线措辞（产物级） | `recommended dose|应服用|建议服用|剂量换算|换算后|equivalent dose|换药|可替代` → drug/ + name/ 命中 **0 文件**；`interchangeable` 命中 21,295 文件，抽查上下文全部是 `not interchangeable` / `not a claim that … are interchangeable` |

### 5.1 一处措辞精度小问题（非缺陷）

CHANGELOG 说「浓度型规格不再被折叠吃掉…现在每个剂型至少保留一个带浓度基数的规格**可见**」。实测 acetaminophen 页的 `960 mg/30 mL` 出现在**折叠摘要（`<details><summary>` 内的 `ms-vol` 行）**，不是可见的 `li.mkrow` 行——它确实「不用展开就能看到」，但不是独立行。表述可接受，若用户较真可把「可见」写成「在折叠摘要里单独列出」，属 P3。

### 5.2 「浓度型规格保底」是个无上限列表（P3，不是缺陷但建议收口）

`_vol_specs`（`site/build.py:10674`）把该段**所有** `spec_kind=="volume"` 的折叠规格拼进 `<summary>`，没有数量上限：

```python
_vol_specs = [s[0] for s, _b in tail_rows if spec_kind.get(s, "") == "volume"]
_vol_bit = ('<span class="ms-vol"> · ' + "、".join(esc(v) for v in _vol_specs) + '</span>')
```

实测 acetaminophen 页 11 个 `ms-vol` 行，最长 **936 字符 / 71 个规格**（另有 470 字符 / 31 个、469 字符 / 33 个），整页这类可见文本合计 ≈2,192 字符。代码注释写「多为 3–6 个」，但大页不是。它在 `<summary>` 里 = **默认可见**，可能把页面拉长、影响首屏指标。
建议（**S5，P3**）：与 `ms-grp` 同口径收口——只列前 8 个 + `_lang_block_text("drug.ms_more", n=…)`，或只列「1 个最小 + 1 个最大 + 1 个带 per_volume」。改动约 3 行，不动语义。

---

## 6. 「内嵌并排矩阵 922→812」是不是功能回退

### 6.1 机制（读源码）

阈值判定只有一处：`site/build.py:9917` `if tbody and multi_ratio >= 0.40:`，它同时决定两件事——`compare_link`（`?view=table` 链接）与 `table_block`（矩阵 HTML）。而 `multi_ratio = 出现在 ≥2 国的规格行数 / 该成分全部规格行数`（`_drug_list_html`，`:10526-10527`）。

**新分组键把复方拆成独立行**（`others_sig`），分母比分子涨得快（复方多为单市场）→ ratio 掉 → 矩阵不再内嵌。**这是我方案 §2「行数 +30.6%」的连带效应，不是有人主动删功能**（diff 里阈值 0.40 没改过：`-U0` 新增行里没有 `0.40` 相关改动）。

### 6.2 独立复算（探针，不等构建）

`reports/2026-11-14-t10-independent-review.ratio-probe.py`（只读 `mode=ro`，复刻 build 的状态过滤 + 规格串 + 同一 ratio 定义）：

| 口径 | 内嵌矩阵页数 |
|---|---|
| 旧 key（3 元组，v0.11.5） | **929** |
| 新 key（4 元组，本轮） | **810** |
| 净变化 | **−119**（丢 124 / 增 5） |
| 对照：阈值只按**单方行**算（复方仍单独成段、仍全部渲染） | **878**（与旧 key 重合 839/929，只丢 90） |

> 我算的 929→810 与 site-ui 的 922→812 差 5～7 页，属复刻口径差（我没复刻 `MATRIX_ROW_CAP`、`hide_empty` 空行裁掉、`_form_chip_key` 等细节），**方向与量级一致**。

### 6.3 受影响页面举例（**成品实测**，不是估算）

| 页面 | 旧 ratio → 新 ratio（探针） | 现产物实测 | 用户少了什么 |
|---|---|---|---|
| `/drug/olmesartan-medoxomil.html` | 1.000 → 0.155（6 → 71 行） | `#tableview` **无**、`?view=table` 链接 **无**、`compare_note` **有**、列表行 **38** | 原来 6 行全跨 ≥2 市场 → 有并排表；现在 71 行里只有 11 行跨 ≥2 市场（多为复方），不再内嵌矩阵 |
| `/drug/perindopril.html` | 1.000 → 0.180（6 → 50 行） | 无矩阵 / 无链接 / 有解释 / 32 行 | 同上 |
| `/drug/metformin-hydrochloride.html` | 0.700 → 0.247（10 → 77 行） | 无矩阵 / 无链接 / 有解释 / 33 行 | 同上 |
| `/drug/deutivacaftor.html` | 1.000 → 0.200（3 → 10 行） | 无矩阵 / 无链接 / 有解释 / 10 行 | 同上（成分少、复方多，掉得最明显） |

全站对照（成品）：`grep -l 'id="tableview"' site/dist/drug/*.html` → **812 页**（与 site-ui 报的 812 一致；我探针算 810，差 2 属复刻口径差）。

**替代视图是什么**：`?view=table` 的矩阵从来不是主视图（v0.10.3 起主视图是按国家分组清单），清单在**所有**页面完整存在（每国每段 12 行 + 「其余规格 N 个 · 涉及 M 种剂型」折叠 + 数据包全量）。丢矩阵的页面同时**保留一句解释**（`drug.compare_note`「并排对照表只在该成分跨市场记录较多时提供；否则这份清单就是全部。」）。
另外 `?view=table` 在这些页面是**静默无效**（`initListView()` 找不到 `#tableview` 就什么都不做，清单照常显示），不会白屏、不会报错。

### 6.4 判定：**可接受**（不建议为这 1 版阻塞发布），但建议下一版改阈值口径

理由（按权重）：

1. **丢的是次要视图，不是数据**：清单 + 折叠 + 数据包都在；矩阵本来是「73.3% 格子是未收录」的降级视图（`_drug_list_html` docstring 的既有结论）。
2. **页面自解释**：没有矩阵的页面会显示 `drug.compare_note`，用户不会以为坏了。
3. **方向合理**：复方行本来就是「不同配方」，把它算进「跨市场密度」在语义上也不对——**用单方行算密度更准**。
4. **有量化救法**：阈值只看单方行 → 878/929 页保留（只丢 90 页，那 90 页的单方行本身就跨市场少，确实不该给矩阵）。改动量为 `_drug_list_html` 里 multi/denominator 各加一个 `if not spec[3]` 过滤，**风险很低**。

**建议 S2（P2，下一版）**：把 `multi_ratio` 改成「单方行跨市场占比」（复方行仍渲染、不参与阈值），并对 `?view=table` 在无矩阵页面加一句「本页无并排表」而不是静默无效。

---

## 7. 建议（4 条，均不阻塞本轮发布）

- **S1（P2，建议发布前改 1 句 CHANGELOG）**：v0.11.6 第 3 条的「同时保留可追溯的『原记录 499.9996 mg』小字」在本轮产物中**不成立**（全站 0 次；机制上只在有内嵌矩阵的 138 页渲染，而含归整行的 45 页都没矩阵）。改文案即可，见 §3.2 的具体改法；若想真保留小字，需在列表行也调用 `_strength_origin_html`（137 行 / 45 页，体积可忽略）→ 排下一版。
- **S2（P2，下一版）**：`multi_ratio` 改成「**只看单方行**的跨市场占比」（复方行仍全部渲染、只是不参与阈值）。独立复算：现口径 810（站内实测 812），单方口径可保留 **878** 页（只丢 90 页，那 90 页的单方行本身跨市场少，确实不该给矩阵）。顺带给无矩阵页的 `?view=table` 一句提示，避免静默无效。见 §6.4。
- **S3（P3，文案）**：品牌页关系表 `fam.rel.same`「活性成分相同」是四类关系里唯一不带「不可互换」的；同表 intro 已声明「不代表可以互换」，但当「成分相同、规格不同」时这行仍可能被读成「可以换」。可改成「活性成分相同（规格/释放仍需核对）」。
- **S4（P3，发布说明口径）**：「规格待核实」徽标默认关闭 → 用户 §1.4 本轮未修；Release notes 与 `whats-new` 不要暗示已修，引用需求队列 G2 的「等 `base_fraction`/`salt_code` 补齐再开」即可。
- **S5（P3，下一版）**：`ms-vol` 浓度规格列表加数量上限（现最长 936 字符 / 71 个），见 §5.2。

---

## 8. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
$git = '.\tools\git\cmd\git.exe'

# 1 越界
& $git status --short
& $git diff --stat
& $git diff --stat -- etl lib db          # → 空
& $py db/q.py "SELECT type,name FROM sqlite_master WHERE type IN ('view','table') AND name LIKE '%collision%'"
& $py db/q.py "SELECT type, COUNT(*) FROM sqlite_master WHERE type IN ('table','view') GROUP BY type"
Get-Item data/drugs.db | Select-Object LastWriteTime     # → 2026/11/12 09:20

# 2 窄口
& $py -m unittest tests.test_spec_grouping -v            # → 16 tests OK
& $py db/q.py "SELECT COUNT(*),COUNT(DISTINCT ROUND(strength_value,6)) FROM product_component WHERE strength_value>=1 AND strength_value<>ROUND(strength_value) AND ABS(strength_value-ROUND(strength_value))<=0.01 AND ABS(strength_value-ROUND(strength_value))<=2e-5*ROUND(strength_value)"   # → 137|54

# 4 红线
& $git diff -U0 -- site/build.py | Select-String '^\+' | Select-String '替代|推荐|换算|互换|等效|equivalent|recommended|interchangeab|convert'

# 6 矩阵页数（独立探针）
& $py reports/2026-11-14-t10-independent-review.ratio-probe.py
```
