# V3 名字页规格拆成可选行 — 阶段 1（只读调研 + 方案）

- 工位：page-slim（task-3，revision 2）
- 时间：2026-11-19 00:35–01:05（北京时间；本机 2026-11-18 08:35–09:05 PT）
- 状态：**只读完成，未改 `site/build.py`、未构建、未写库**；等 Lead 发「BUILD-FREE」（v0.13.8 构建完）后进阶段 2。
- 需求原文：`docs/谷段需求队列.md` 第 21 行 V3 [P1]（用户点名「泰诺林」页）。

## 结论先行

1. **问题确认**：`name/泰诺林.html`（v0.13.7 产物）现在把剂型 + 规格 + 释放压成一句 **209 字符**的长句（不含开头 `Countries: CN ·`；整段 225 字符）：
   `Form: liquid、tablet、unknown · Strength by dosage form: tablet 500 mg、650 mg；liquid 20 mL、120 mL、160 mg/5 mL、960 mg/30 mL、1,000 mg/10 mL、1,500 mg/15 mL、3,200 mg/100 mL；unknown 650 mg · Release: extended-release`。
   其中「Release: extended-release」还被读成整个名字都是缓释——实际只有 650 mg 的 **4 条**记录是 ER，其余 8 条未记录。
2. **数据支持拆三层**（SQL 见 §3）：片剂 **4 条 / 2 个规格**、液体 **7 条 / 7 个规格**、剂型未注明 **1 条 / 1 个规格**；液体内部「有浓度信息」**5 条 / 5 个规格**、「仅记录体积」**2 条 / 2 个规格**。合计 12 条产品记录。
3. **推荐实现**：每个剂型一个**原生 `<details>` 折叠行**（summary = 剂型 + 规格数 + 记录数），展开后每行 = `规格 · 释放方式（或「释放方式未记录」）· N 条记录（N>1 时显示）`；液体再分「有浓度信息 / 仅记录体积」两个小标题。**零 JS、零依赖、原生可键盘操作、find-in-page 可搜**，符合 Modern Web Guidance 的 `accordion` + `search-hidden-content` 两篇指南；不采用「标签页 / 分段控件」（需要 JS + `focusgroup`/`hidden=until-found`，见 §5）。
4. **体积可控（WIP 实测后收紧门槛）**：「多剂型 / 规格多 / 释放方式混杂」按原门槛 A 会命中 12,963 张卡（10,036 页，11.0%），净增 **+15.3 MB（name 目录 +3.30%）**，略超报告预留的 3%。按报告预设的收紧规则改成门槛 B（2 剂型且 ≥3 规格 / ≥5 规格 / 释放混杂）后实际命中 **5,419 个名字页（13,526 个 details / 35,910 行）**，name 目录 **+10,059,409 B（+2.08%）**；泰诺林（3 剂型 10 规格）仍在范围内。CSS 只加一段全局样式（约 +0.8 KB，一次）。
5. **文案口径**：新增 10 个 i18n 键 × **6 种语言**（en/es/zh/zh-Hant/fr/**ko**——v0.13.8 起 `i18n_check` 六语键集必须一致，不能只补五语）。基线现查 667 键、FAIL 0 / WARN 2。

## 1. 需求口径（队列 V3 原文）

> **V3 [P1] 名字页规格长句拆成可选行**（用户点名「泰诺林」页）——先选剂型（片剂 / 液体 / 剂型未注明）；选「液体」后把 `160 mg/5 mL` 放「有浓度信息」、`20 mL` / `120 mL` 放「仅记录体积」；释放方式只跟有依据的具体记录显示；缺信息显式标缺。**验收**：泰诺林页三类分组与组内计数和 SQL 一致；切剂型后条目变化正确；五语；390 无溢出。

拆成可验收的 5 条：
1. 三类分组：`片剂 4 · 液体 7 · 剂型未注明 1`（记录数），组内规格数 `2 · 7 · 1`。
2. 液体二分：`有浓度信息 5`（160 mg/5 mL、960 mg/30 mL、1,000 mg/10 mL、1,500 mg/15 mL、3,200 mg/100 mL）+ `仅记录体积 2`（20 mL、120 mL）。
3. 释放方式只挂在有依据的记录上：650 mg（片剂）`ER×3`、剂型未注明 650 mg `ER×1`；其余 8 条显式写「释放方式未记录」。
4. 缺信息显式标缺：剂型 `unknown` → 「剂型未注明」；无释放 → 「释放方式未记录」；无结构化规格（复杂卡内）→ 「规格未记录」。
5. 390 无横向溢出；zh/en/es/zh-Hant/fr（+ko）文案齐；`i18n_check` FAIL 0。

## 2. 现状（代码 + 线上产物，只读）

### 2.1 代码位置（函数名为准；抓取时 `site/build.py` 18,062 行）

> 说明：阶段 1 期间 LG1 正在同一文件里并入韩语（17,382 → 18,062 行），下表的行号会漂移；**阶段 2 只用函数名 / 唯一字符串做锚点**，不按行号改。

| 位置 | 现查行号 | 作用 |
|---|---|---|
| `collect_name_data()` | 12,390 | 名字页数据一次性聚合：`s`（规格集合）、`fs`（剂型→规格集合）、`f`（剂型集合）、`rel`（释放集合） |
| `build_name_pages()` 卡片循环 | 12,529 起，卡片块 12,579–12,616 | 生成 `<div class="card">…<div class="meta">` 长句 |
| `_form_display()` | 11,732 | 剂型受控词 → `data-i18n` 标签 |
| `_FORM_RANK_OUTER()` | 13,450 | 剂型排序（tablet→capsule→liquid→…→unknown） |
| `.card .meta` CSS | 5,272 | 名字页卡片元信息样式 |
| `.name-more` CSS | 6,361 | 现有「显示更多」`<details>` 样式，可复用交互语言 |

现有卡片渲染（`build_name_pages` 内，摘要）：
```python
rel = g["rel"] - {"none"}
strengths = '、'.join(sorted(g['s'], ...))
_fs = {fm: sorted(specs, ...) for fm, specs in (g.get("fs") or {}).items() if specs}
if len(_fs) > 1:
    ... strength_key, strength_value = "name.form_spec", "；".join(_parts)
else:
    strength_key, strength_value = "name.strength", ...
...
<div class="meta"><span data-i18n="name.countries">Countries</span>:
{...} · <span data-i18n="name.form">Form</span>: {_label_join('form', sorted(g['f']))}{strength_bit}
{... · Release: ... if rel else ''}</div>
```
问题不在数据，在「一个 `.meta` 行塞了所有剂型的全部规格 + 一个全局释放值」：无法按剂型看，也无法表达「哪些记录没写释放」。

### 2.2 线上产物抽样（`site/dist` 只读，v0.13.7，2026-11-17 15:07）

- `site/dist/name/泰诺林.html`：**6,999 B**，卡片元信息就是 §结论 1 的长句（dist 第 10–13 行）。
- name 目录：**91,073 页 / 464,466,532 B（442.9 MiB）/ 平均 5,100 B**（`Get-ChildItem site\dist\name -File | Measure-Object Length -Sum`）。
- 现成可复用的客户端能力：`[data-i18n]`、`[data-i18n-tpl]` + `data-total`（`apply()` 只替换 `{shown}`/`{n}`/`{u}`，见 build.py 17,116–17,123），**新增文案不需要新 JS 语法**。

## 3. 数据账（`db/q.py` 只读 SQL，现查）

命令模板：
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/q.py "SELECT ..."
```

### 3.1 三类剂型分组（验收第 1 条）

```sql
SELECT COALESCE(p.form_base, '(none)') AS form, COUNT(DISTINCT p.product_id) AS records
FROM product_name pn
JOIN product p ON p.product_id = pn.product_id
WHERE pn.key_id = '泰诺林' AND pn.name_type = 'trade'
GROUP BY form ORDER BY form;
```
现查输出：
```
form | records
liquid | 7
tablet | 4
unknown | 1
```
规格数与记录数（按 `(剂型, 规格串)` 去重）：
```sql
SELECT COALESCE(p.form_base, '(none)') AS form,
       COUNT(DISTINCT p.product_id) AS recs,
       COUNT(DISTINCT COALESCE(pc.strength_value,'')||'|'||COALESCE(pc.strength_unit,'')||'|'||
                      COALESCE(pc.per_volume_value,'')||'|'||COALESCE(pc.per_volume_unit,'')) AS specs
FROM product_name pn
JOIN product p ON p.product_id = pn.product_id
LEFT JOIN product_component pc ON pc.product_id = p.product_id
WHERE pn.key_id = '泰诺林' AND pn.name_type = 'trade'
GROUP BY form ORDER BY form;
```
现查输出：
```
form | recs | specs
liquid | 7 | 7
tablet | 4 | 2
unknown | 1 | 1
```
（阶段 2 会把这两条查询写进对账脚本，逐组断言。）

### 3.2 液体二分（验收第 2 条）

```sql
SELECT CASE
         WHEN pc.per_volume_value IS NOT NULL THEN 'concentration'
         WHEN lower(COALESCE(pc.strength_unit,'')) IN ('ml','l','cl','dl') THEN 'volume_only'
         ELSE 'amount' END AS grp,
       COUNT(DISTINCT p.product_id) AS recs
FROM product_name pn
JOIN product p ON p.product_id = pn.product_id
JOIN product_component pc ON pc.product_id = p.product_id
WHERE pn.key_id = '泰诺林' AND pn.name_type = 'trade' AND p.form_base = 'liquid'
GROUP BY grp;
```
现查输出：
```
grp | recs
concentration | 5
volume_only | 2
```
明细（阶段 2 的行内容与顺序）：
| 分组 | 规格行 | 释放 | 记录数 |
|---|---|---|---|
| 有浓度信息 | 160 mg/5 mL | 未记录 | 1 |
| 有浓度信息 | 960 mg/30 mL | 未记录 | 1 |
| 有浓度信息 | 1,000 mg/10 mL | 未记录 | 1 |
| 有浓度信息 | 1,500 mg/15 mL | 未记录 | 1 |
| 有浓度信息 | 3,200 mg/100 mL | 未记录 | 1 |
| 仅记录体积 | 20 mL | 未记录 | 1 |
| 仅记录体积 | 120 mL | 未记录 | 1 |

### 3.3 释放方式（验收第 3 条）

```sql
SELECT COALESCE(p.form_base,'(none)') form, p.dosage_form, p.release,
       pc.strength_value, pc.strength_unit, pc.per_volume_value, pc.per_volume_unit,
       COUNT(DISTINCT p.product_id) recs
FROM product_name pn
JOIN product p ON p.product_id = pn.product_id
LEFT JOIN product_component pc ON pc.product_id = p.product_id
WHERE pn.key_id = '泰诺林' AND pn.name_type = 'trade'
GROUP BY form, p.dosage_form, p.release, pc.strength_value, pc.strength_unit,
         pc.per_volume_value, pc.per_volume_unit
ORDER BY form, pc.strength_value;
```
现查 12 行 → 12 条记录（下表把单位列整理成规格串）：
```
liquid  | 混悬滴剂   | none | 20 mL            | 1
liquid  | 口服混悬剂 | none | 120 mL           | 1
liquid  | 口服溶液剂 | none | 160 mg/5 mL      | 1
liquid  | 混悬剂     | none | 960 mg/30 mL     | 1
liquid  | 滴剂       | none | 1,000 mg/10 mL   | 1
liquid  | 混悬滴剂   | none | 1,500 mg/15 mL   | 1
liquid  | 口服混悬剂 | none | 3,200 mg/100 mL  | 1
tablet  | 片剂       | none | 500 mg           | 1
tablet  | 片剂(缓释) | ER   | 650 mg           | 3
unknown | tablet     | ER   | 650 mg           | 1
```
→ 释放行：`650 mg · ER ×3`（片剂）、`650 mg · ER ×1`（剂型未注明）；其余全部「释放方式未记录」。

## 4. 阶段 2 方案（等 BUILD-FREE）

### 4.1 数据层：`collect_name_data()` 加粒度，不动现有键

现有 `s`/`fs`/`f`/`rel` 保留（索引与紧凑路径还在用），新增：
- `s["sp"][(fm, st, rel)] = {"n": 记录数, "kind": "concentration"|"volume"|"amount"}`；
- `s["und"][fm] = n`（有产品、但无结构化规格）；
- `s["fr"][fm] = n`（该剂型的 distinct 记录数，用于 summary 的 4/7/1）。

查法：主查询改成按 `(key_id, sid, mk, fm, rel, strength/per_volume)` 聚合（`COUNT(DISTINCT p.product_id)`，现查 **520,880 组 / 12.1 s**）；再补一条按 `(key_id, sid, fm)` 的 distinct 记录数查询（现查 **397,745 组 / 2.8 s**）；`name_only`（10,708 个无成分产品）单独一条小查询保持现有语义。构建耗时预计 +15–25 s，可接受。

> 为什么不用「行级循环 + set 去重」：现库有 3,759 个 `(product, substance)` 组合出现 ≥2 行（如 Trikafta 同成分两个规格），行级循环会把记录数算重；SQL 聚合是唯一和「SQL 逐条一致」验收口径对齐的写法。

### 4.2 渲染层：只在「长句卡」上替换，其余卡片逐字节不变

启用条件（最终版 = 门槛 B；避免 91k 页全站涨体积）：
```python
complex = ((len(forms) >= 2 and n_specs >= 3) or n_specs >= 5 or len(g["rel"]) > 1)
```
WIP 快照实测（`.tmp/verify_v3_variants.py`，只读；页面集合来自 `load_index()` 的 91,073 个真实名字页）：

| 门槛 | 命中块 | 命中页 | 净增量（新块 − 旧长句） |
|---|---|---|---|
| A `forms>=2 or specs>=5 or rel>1`（原方案） | 12,963 | 10,036（11.0%） | +15,328,415 B（+3.30%） |
| **B `(forms>=2 and specs>=3) or specs>=5 or rel>1`（采用）** | **6,136** | **5,419（5.9%）** | **+10,077,472 B（+2.17%）** |
| C `forms>=3 or specs>=5 or rel>1` | 4,955 | 4,407（4.8%） | +8,889,847 B（+1.91%） |
| D `specs>=5 or rel>1` | 3,981 | 3,615（4.0%） | +7,609,972 B（+1.64%） |

→ 采用 B：泰诺林（3 剂型 / 10 规格）照常拆行，2 剂型但只有 1–2 个规格的短句保持原紧凑行，净增控制在 name 目录 **+2.17%**（另：紧凑 `.meta` 被替换的部分已从净增量里扣掉）。其余 ~85k 页保持原 `.meta` 行，无 diff、无体积变化。

命中后 `.meta` 只留 `Countries`，追加（示意，数值来自 §3）：
```html
<div class="nsforms">
  <details class="nsform"><summary>
    <span data-i18n="form.tablet">tablet</span>
    <span class="nsf-n" data-i18n-tpl="name.specs_n" data-total="2">2 strengths</span>
    <span class="nsf-r" data-i18n-tpl="name.records_n" data-total="4">4 records</span>
  </summary><div class="nsrows">
    <div class="nsrow"><span class="nsrow-spec">500 mg</span>
      <span class="nsrow-rel" data-i18n="name.rel_unrecorded">Release not recorded</span></div>
    <div class="nsrow"><span class="nsrow-spec">650 mg</span>
      <span class="nsrow-rel" data-i18n="release.ER">extended-release</span>
      <span class="nsrow-n" data-i18n-tpl="name.records_n" data-total="3">3 records</span></div>
  </div></details>
  <details class="nsform"><summary>
    <span data-i18n="form.liquid">liquid</span>
    <span class="nsf-n" data-i18n-tpl="name.specs_n" data-total="7">7 strengths</span>
    <span class="nsf-r" data-i18n-tpl="name.records_n" data-total="7">7 records</span>
  </summary><div class="nsrows">
    <p class="nsg-h"><span data-i18n="name.spec_conc">With concentration</span>
      <span data-i18n-tpl="name.specs_n" data-total="5">5 strengths</span></p>
    <!-- 5 行：160 mg/5 mL / 960 mg/30 mL / 1,000 mg/10 mL / 1,500 mg/15 mL / 3,200 mg/100 mL，均「释放方式未记录」 -->
    <p class="nsg-h"><span data-i18n="name.spec_vol">Volume only</span>
      <span data-i18n-tpl="name.specs_n" data-total="2">2 strengths</span></p>
    <!-- 2 行：20 mL / 120 mL，均「释放方式未记录」 -->
  </div></details>
  <details class="nsform"><summary>
    <span data-i18n="name.form_unstated">Form not stated</span>
    <span data-i18n="name.specs_one">1 strength</span>
    <span data-i18n="name.records_one">1 record</span>
  </summary><div class="nsrows">
    <div class="nsrow"><span class="nsrow-spec">650 mg</span>
      <span class="nsrow-rel" data-i18n="release.ER">extended-release</span></div>
  </div></details>
</div>
```
规则：
- **默认全部收起**（先选剂型）；`<details>`/`<summary>` 原生可点、可 Tab、可 find-in-page，**不写一行 JS**；按 MWG `accordion` 指南**不加 `name` 属性做互斥**（该指南明确建议避免 exclusive accordion）。
- 行按 `(规格, 释放)` 拆开：同一规格若有 ER 与未记录两种记录，会出两行，各自带计数，绝不合并成一句结论。
- 液体内部按 `kind` 分「有浓度信息 / 仅记录体积 / 其他记录量」；只有两类以上才出小标题。
- 剂型 `unknown` / 空 → 「剂型未注明」（`name.form_unstated`），不再显示英文 `unknown`。
- 复杂卡内「无规格」记录 → 末尾一行「规格未记录 ×N」（`name.spec_unrecorded`）。
- 计数加千分位（与站内 `12,645` 口径一致）；`<summary>` 内不放 heading（MWG 警告 JAWS/TalkBack 会丢 heading）。
- CSS 新增 `.nsforms/.nsform/.nsrows/.nsrow/.nsg-h`（约 0.7 KB，一次），沿用现有 `--muted` / `--line` / 44px 触控高度；390 用 `flex-wrap` + `min-width:0`，不需要横向滚动。
- 不改碰撞/关系推导、不出用药建议、不做剂量换算；只呈现 DB 里的 `release` / 成分 / 规格事实。

### 4.3 i18n：10 个新键 × 6 语言

| key | en | zh | 用途 |
|---|---|---|---|
| `name.form_unstated` | Form not stated | 剂型未注明 | 剂型缺失/unknown |
| `name.specs_one` | 1 strength | 1 个规格 | 单规格组 |
| `name.specs_n` | {n} strengths | {n} 个规格 | 多规格组 |
| `name.records_one` | 1 record | 1 条记录 | 单记录组 |
| `name.records_n` | {n} records | {n} 条记录 | 多记录组/行计数 |
| `name.spec_conc` | With concentration | 有浓度信息 | 液体子组 |
| `name.spec_vol` | Volume only | 仅记录体积 | 液体子组 |
| `name.spec_amount` | Other recorded amounts | 其他记录量 | 液体兜底子组 |
| `name.rel_unrecorded` | Release not recorded | 释放方式未记录 | 缺释放 |
| `name.spec_unrecorded` | Strength not recorded | 规格未记录 | 缺规格 |

- 同时补 es / zh-Hant / fr / **ko**（v0.13.8 起 `deploy/i18n_check.py` 的 `LANGS` 是 6 语、键集必须一致；只补五语会 FAIL）。
- 插入位置：各语言字典里 `name.form_spec` 相邻行（en 2,046 / es 2,237 / zh 2,400 / zh-Hant 2,666 / fr 1,202 / ko 4,073，行号会漂移）；每处用**唯一整行**做 `edit` 锚点。
- 数字句沿用现有 `data-i18n-tpl` + `data-total`（只认 `{n}`），不新增客户端占位符语法。

## 5. 外部方案检索（AGENTS §12「先找现成工具」）

| 候选 | 许可 | 体积 / 维护 | 与本仓兼容性 | 结论 |
|---|---|---|---|---|
| [alphagov/govuk-frontend](https://github.com/alphagov/govuk-frontend) Accordion | MIT（`package.json` 现查） | `accordion.bundle.js` **30,682 B**（未压缩，含 GOV.UK 基类）；持续维护 | Nunjucks 模板 + Sass + `new Accordion()` 初始化，要求 npm 构建链；本仓是单文件内联构建、无 npm | **不采用**，只作可访问性交互参考 |
| [javan/details-element-polyfill](https://github.com/javan/details-element-polyfill) | MIT（GitHub API 现查） | **6,953 B**；仓库最近 push 2025-06-05，README © 2019 | 只补旧浏览器的 click/键盘/open；不补 `name` 互斥；`<details>` 早已是基线能力 | **不采用**（多余依赖） |
| [scottaohara/a11y_accordions](https://github.com/scottaohara/a11y_accordions) | MIT（GitHub API 现查） | ES5 vanilla，最后一次 push 2020；139★ | 自定义 button + `aria-expanded` 手写组件，需要 JS 与焦点管理；原生 `<details>` 已覆盖同样语义 | **不采用**，作 ARIA 参考 |

**Modern Web Guidance（本地 `vendor/modern-web-guidance/`，`DISABLE_TELEMETRY=1` 检索）**：
- `accordion`：*“Build accordions from a set of adjacent `details` elements.”*；并明确 *“Avoid exclusive accordions”*（`name` 互斥会让放大镜用户丢内容）→ 本方案用非互斥 `<details>`。
- `search-hidden-content`：*“The `<details>` element is generally recommended as it's simpler to implement and maintain”*，且隐藏内容仍可被浏览器 find-in-page 找到 → 正好解决「规格行默认收起」的可发现性。
- `content-first-noise-reduction`：*“show secondary content only when asked”* → 长句收起、按剂型展开符合「内容优先」。
- `tabs`（看过、不采用）：推荐 `focusgroup="tablist"` + `hidden="until-found"` + `beforematch` 脚本，需要 JS 且 `focusgroup` 尚非基线；本需求只有 2–4 个剂型，用标签页是过度设计。

**结论**：零依赖、零 JS 的原生 `<details>` 是本需求最合适的「现成工具」；不引入任何第三方包/构建链。

## 6. 体积与验收预算

| 项 | 现查/估算 | 实测（2026-11-19，`.tmp/dist-v3`） |
|---|---|---|
| 名字页总量 | 91,073 页 / 483,535,651 B（v0.13.8） | 91,073 页 / 493,595,060 B |
| 命中页 | 门槛 B 预估 5,419 页 | **5,419 页 / 13,526 details / 35,910 行** |
| 净增量 | 预估 +10,077,472 B（+2.17%） | **+10,059,409 B（+2.08%）** |
| 泰诺林单页 | 6,999 B（v0.13.7） | **7,046 → 9,241 B**（v0.13.8 → v0.14 WIP） |
| i18n | 阶段 1 基线 667 键 × 6 | 构建期 687 键 × 6；`i18n_check` **FAIL 0 / WARN 2（存量）** |
| 首屏守卫 | name 页 4 档 | **4 档全 ok**、溢出否、AFCR 1.00–1.01 |

## 7. 风险 / 并行纪律

- **`site/build.py` 是移动目标**：阶段 1 期间被 LG1 追加约 680 行；阶段 2 只用 `edit` + 唯一锚点（函数名、整行 i18n 键、唯一 CSS 行），绝不 `write` 整文件；`FS_STALE_VERSION` 就重读重标。另 4 个工位在改首页/覆盖页/分类页/成分页，**只碰 name 页规格区段**。
- **不写 `site/dist`**：验收构建一律 `SITE_OUT=.tmp/dist-v3`；不 commit、不发布、不改 CHANGELOG。
- **数据口径**：只用 `release` / `strength` / `per_volume` / `form_base` 现查字段；`unknown` 显示为「未注明」，不当成一种剂型事实；不手工标注关系、不判断可互换、不做剂量换算。
- **已知缺口（阶段 2 报告里明说）**：单剂型且 0 个结构化规格的 84,812 张卡仍不显示「规格未记录」（超出本次长句问题范围）；若 Lead 要求全站显式标缺，再单独评估体积。

## 8. 阶段 2 步骤（收到 BUILD-FREE 后）

1. 重读 `site/build.py` 当前版本，确认 `collect_name_data` / `build_name_pages` 区段未被他人改动；`git diff site/build.py` 留底。
2. `edit`：`collect_name_data` 改聚合查询 + 新增 `sp/und/fr`；新增 `_name_spec_block()`；卡片循环按门槛分流（复杂卡走新块，简单卡原样）。
3. `edit`：6 处 i18n 字典加 10 键；CSS 加 `.nsforms…` 一段。
4. 自验：
   - `SITE_OUT=.tmp/dist-v3 & $py site/build.py` 等到 `== done ==`；
   - SQL 对账脚本：`泰诺林` 三类 4/7/1、规格 2/7/1、液体 5+2、650 mg ER×3，逐条与渲染 HTML 的 summary/行数比对；
   - 五语 + ko 切语言抽查（`?lang=zh` / `zh-Hant` / `es` / `fr` / `ko`）；
   - Playwright 390 截图：收起态 + 展开「液体」态；`document.documentElement.scrollWidth <= innerWidth`；
   - `deploy/i18n_check.py` FAIL 0；
   - name 目录字节数 before/after、泰诺林单页大小；
   - 首次屏守卫改前/改后数字（Lead 全量构建时一并跑）。
5. 报告追加「实测」段 + 截图 `docs/img/v3-name-spec-*.png`，task-3 置 completed，回报 ≤200 字。

## 9. 阶段 1 自检

- 只读命令：`db/q.py` 全部 `SELECT`；`deploy/i18n_check.py` 只读；`site/dist` 只读抽样；MWG CLI 只读（`DISABLE_TELEMETRY=1`）。
- 未改 `site/build.py`、未跑 `site/build.py`、未写 `data/drugs.db`、未 commit。
- 行号说明：本文行号是 2026-11-19 00:45 左右快照，`build.py` 正被 LG1 修改；实现锚点以函数名/唯一字符串为准。

## 10. 阶段 2 实施记录（WIP，等 BUILD-FREE #2 构建）

### 10.1 已写入 `site/build.py` 的改动（按函数名定位）

| # | 位置 | 改动 |
|---|---|---|
| 1 | `_spec_kind_of()`（`collect_name_data` 前） | 新函数：`per_volume` → concentration；纯体积单位 → volume；其余 → amount。只读 DB 字段，不换算。 |
| 2 | `collect_name_data()` | 主查询改按 `(key_id, sid, mk, fm, release, strength/per_volume)` 聚合（`COUNT(DISTINCT product_id)`，现查 520,880 组 / 约 12.1 s）；新增 `sp`（行＝剂型×规格×释放→计数+kind）、`und`（剂型→无规格记录数）、`fr`（剂型→distinct 记录数，第二查询 397,745 组 / 约 2.8 s）；`name_only` 单独查询（10,708 个无成分产品），保持原 pid 语义。 |
| 3 | `_name_spec_block()`（`_release_variant_notice` 后、`build_name_pages` 前） | 新函数：门槛 B 判定 → 按剂型排序 → 原生 `<details>`/`<summary>`；液体分 `name.spec_conc` / `name.spec_vol` / `name.spec_amount`；`release='none'` 显式 `name.rel_unrecorded`；`n>1` 才显示 `name.records_n`；`und` 行 `name.spec_unrecorded`。 |
| 4 | `build_name_pages()` 卡片块 | 复杂卡：`.meta` 只留 Countries，追加 `_name_spec_block()`；简单卡：原长句逐字节不变。 |
| 5 | CSS（`.card .meta` 后） | `.nsforms/.nsform/.nsrows/.nsrow/.nsf-t/.nsf-c/.nsrow-*/.nsg-h` 14 条；summary 44px 触控高、`flex-wrap` + `min-width:0`，390 不横向溢出；无 JS。 |
| 6 | i18n 字典 6 处 | 10 个键 × en/es/zh/zh-Hant/fr/ko（含 `_one` 单数键）；插入在各语言 `name.form_spec` 相邻行。 |

### 10.2 构建前已做的只读验证

- `& $py -m py_compile site\build.py` → ok。
- `& $py deploy/i18n_check.py` → 六语各 **683 键**、`FAIL 0 / WARN 2`（WARN 为存量 es `form.kit` / `form.gas`，非本任务）。
- 新旧聚合等价：301 个抽样 key（含泰诺林）用旧 SQL 逐行聚合 vs 新 `collect_name_data()`，`s/f/fs/rel/country/inn/nl/name_only` **0 差异**（`.tmp/verify_v3_equiv.py`）。
- 泰诺林渲染片段（`.tmp/verify_v3.py`）：3 个 `<details>` / 10 行 / 液体 5 浓度 + 2 体积 / 8 条「释放方式未记录」/ ER 只在 650 mg 两行；块 2,809 B。
- 门槛与体积：`load_index()` 的 91,073 个真实名字页上，门槛 B 命中 6,136 块 / 5,419 页 / 净增 +10,077,472 B（`.tmp/verify_v3_variants.py`）。
- 构建后断言脚本已备好：`.tmp/v3_assert.py`（HTML vs SQL 对账、10 行、8 条缺释放、2 条 ER、无占位符、CSS 进产物）。

### 10.3 HOLD 与解除

Lead 要求 v0.13.8 干净重建：`site/build.py` 曾临时换回「已提交 v0.13.8 + `_lang_block_text` 一行热修」，5 个工位的 WIP 快照在 `.tmp/build-wip.py`。HOLD 期间未 edit `site/build.py`、未跑构建；**BUILD-FREE #2** 后 WIP 原样放回，门槛 A → B 一行已落回 `_name_spec_block()`（唯一锚点），`py_compile` ok、`i18n_check` FAIL 0。

### 10.4 构建实测（2026-11-19 02:00 前后，`SITE_OUT=.tmp/dist-v3`）

```
== done ==
  name pages : 91073（与 v0.13.8 相同）
  total size : 1305.2 MB
```

| 项 | 实测 |
|---|---|
| `.tmp/v3_assert.py` | **31 项 PASS / FAIL 0**（3 details、10 行、旧长句移除、液体 5+2、8 条缺释放、ER 仅 2 行、无 `{n}` 残留、CSS 进产物、SQL 三组 4/7/1 与 ER=4 全对） |
| 命中产物 | **5,419 页**含 `.nsforms`；**13,526 个 `<details>` / 35,910 条行** |
| name 目录体积 | 493,595,060 B；v0.13.8 `site/dist` 为 **483,535,651 B** → **+10,059,409 B（+2.08%）**，与门槛 B 预估 +10,077,472 B 相差 18 KB |
| 泰诺林单页 | **7,046 B → 9,241 B**（+2,195 B；块 2,809 B，旧长句 −614 B） |
| 390 断言 | 收起态 3 个 `.nsrows` 高度 **0**、`scrollWidth 375 ≤ 390`；展开液体 **7 行 + 2 小标题（5/2）**；展开片剂 **2 行**（500 mg 未记录 / 650 mg 缓释 3 条）；展开剂型未注明 **1 行** |
| 六语切换 | en/es/zh/zh-Hant/fr/ko 的 summary、行文案、计数模板全部正确，均无横向溢出 |
| 首屏守卫（name 页） | 390/768/1440/2560 四档 **全 ok**：AFCR 1.01/1.01/1.00/1.00、正文 16px、溢出否、chrome 0.33/0.22/0.17/0.10 |
| 截图 | [390 收起](../docs/img/v3-name-spec-390-closed.png) · [390 展开液体](../docs/img/v3-name-spec-390-liquid.png) · [1440 收起](../docs/img/v3-name-spec-1440.png) |

**构建中发现并修复的 1 个 UI bug**：`.nsrows{display:grid}`（作者样式）会覆盖浏览器对关闭 `<details>` 内容的隐藏，导致收起时 10 行仍占 84–342px 高度。已改成 `.nsrows{display:none}` + `.nsform[open]>.nsrows{display:grid}`，重建后收起高度实测 0；CSS 进产物已断言。

**简单页无回归**：抽 500 个未命中门槛的名字页，与 v0.13.8 归一化资源哈希后比较，字节长度全部一致（65 个差异来自其他工位并发改动，非本任务）。
