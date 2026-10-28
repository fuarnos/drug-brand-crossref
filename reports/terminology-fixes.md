# 术语校验 critical/warning 修复报告（task-91）

> 日期：2026-10-28 ｜ 基线：`reports/terminology-accuracy.md`（38 findings：2 critical / 36 warning）
> 只改 **data 译文文件**（`data/es_ui_missing.csv`、`data/release_notes_i18n.json`）；
> `site/build.py` 改动只给**精确 patch 清单**（由 impl-lazyload 在 v0.6.6 应用）；
> 未写 DB、未改 build.py、未 git / 未发布。
> 验证工具：`etl/check_translations.py`（只读、7 规则）。

---

## 0. 结果

| 口径 | findings | critical | warning | 说明 |
|---|---:|---:|---:|---|
| 修复前（`terminology-accuracy.md`） | 38 | **2** | 36 | dist + 全部 7 规则 |
| **仅数据修复后（当前 site/dist 未重建）** | 31 | **1** | 30 | 只剩 `combo.cross_overlap` 的旧 dist 值（源码已修，见 §2） |
| **当前源码口径（checker --i18n site/build.py）** | 27 | **0** | 27 | build.py 已含 combo es 强译 + es about.samename 修复；AST 解析不完整（269/328 键）仅作参考 |
| **模拟 patch 已应用 + 已重建** | **25** | **0** | 25 | `i18n_sim.js`（328 键×4）；`--strict` 退出码 **0** ✅ |

- **critical 2 → 0**：① `es_ui_missing` 占位符已在数据侧修复；② `combo.cross_overlap` 的 es 值
  **build.py 源码里已经是 `no son intercambiables`**（当前 L1665–1666），dist 是旧构建（`no es intercambiable`）——
  **重建即消失，无需再改 build.py**（详见 §2）。
- **warning 36 → 25**：数据修复直接消掉 8 条（es_ui_missing 占位符/标签 4 条 + release notes es 术语 2 条 +
  旧 dist 的 2 条 html/term）；剩余 25 条中 **4 条是 checker 对代码跨度里 `<term>` 的误报**、
  **21 条为词义/产品名/基准变体缺口**（详见 §5），不属于「必须改译文」的真错。

---

## 1. 数据文件修复（已落地，可直接复核）

### 1.1 `data/es_ui_missing.csv`（39 行不变，改 3 行）

| key | 字段 | 修复前 | 修复后 |
|---|---|---|---|
| `page.title.template` | `es_suggested` | `«{título localizado} · Medicine Brand Cross-Reference»` | `<title>{title} · Referencia cruzada de marcas de medicamentos</title>` |
| `meta.description.template` | `en_text` | `(无 <meta name="description">)`（伪 HTML 被 checker 当标签） | `(无 HTML meta description 标签)` |
| `meta.description.template` | `es_suggested` | `«descripción localizada de cada página»` | 同左（保持；只改 en_text 消除误报） |
| `whatsnew.release.v0.2.4` | `es_suggested` | `?v=<marca de tiempo del build>`（尖括号被当 HTML） | `?v=«marca de tiempo del build»` |

效果：`placeholder` critical 1 → 0；`html` warning 3 → 0（该文件相关）。

### 1.2 `data/release_notes_i18n.json`（24 版本 / 95 条不变，改 2 条 es）

| 位置 | 修复前 | 修复后 | 理由 |
|---|---|---|---|
| `v0.1.0#3` | `principio → dosis → marca → fabricante; principio y dosis…` | `principio → concentración → marca → fabricante; principio y concentración…` | 站点 es 统一用 `concentración` 表 strength（es 术语表/About 一致） |
| `v0.3.5#1` | `(tirzepatide / semaglutide …)` | `(tirzepatida / semaglutida …)` | 西语 INN 名应用西语拼写（与 terminology_glossary `inn_name` 行一致） |

> 其余 release notes 的 es 改动**不做**：`Excedrin Extra Strength`、`Pain Relief Patch`、`strength_basis`、
> `unknown` 等是产品名/code token，改成「术语」反而错；`search-<term>` 是内联代码里的字面量——
> 这些是 checker 的代码跨度检测缺陷（见 §5），不应通过改译文来「消警告」。

---

## 2. `site/build.py` patch 清单（给 impl-lazyload，v0.6.6）

> 当前源码行号（2026-10-28 **12:19 快照：6,064 行 / 348,243 B**；build.py 在本任务期间被其它任务更新过，
> 下列锚点已按 12:19 版本复核；仍可能漂移，请按**锚点字符串**定位）。
> 本任务**未改 build.py**，以下为待应用清单。

### 2.1 无需再改（源码已修复，dist 待重建）

| key / 语言 | 当前 build.py 位置 | 现状 |
|---|---|---|
| `combo.cross_overlap` / es | L1665–1666（12:19 复核） | 已是 `La combinación más cercana en otros mercados es similar pero NO idéntica: **no son intercambiables**.'`——无需 patch；重建 dist 后 checker 的 critical 自动消失 |
| `about.samename` / es | L1128–1136 | 已含 `en el Reino Unido <b>Benadryl</b> es acrivastina`——无需 patch |

### 2.2 待应用：`about.nick` / `about.terms` 的中文 `<i>` 标签（补回 en 源的强调结构）

**A. build.py `I18N["zh"]["about.nick"]`（当前 L1186–1187）**

```python
# old 1
'「网络俗称 / 旧名」，再列该成分的商品名，绝不把它说成包装上的名字。每条都写出处；'
# new 1
'<i>「网络俗称 / 旧名」</i>，再列该成分的商品名，绝不把它说成包装上的名字。每条都写出处；'

# old 2
'「用户提供」只算线索，公开页标「未证实」，找到独立出处后才升级为 '
# new 2
'「用户提供」只算线索，公开页标<i>「未证实」</i>，找到独立出处后才升级为 '
```

**B. build.py `I18N["zh"]["about.terms"]`（当前 L1203）**

```python
# old
'<li><b>MedlinePlus（NLM）</b>提供常见民间/类别词（美国政府作品）；社区来源'
'（CN/GB/AU/ES）标「社区叫法」并保留检索。FDA 官方 tall-man 药对：'
# new
'<li><b>MedlinePlus（NLM）</b>提供常见民间/类别词（美国政府作品）；社区来源'
'（CN/GB/AU/ES）标<i>「社区叫法」</i>并保留检索。FDA 官方 tall-man 药对：'
```

**C. zh-Hant 字典**：`data/i18n_zh_hant.json` 当前 `about.nick`/`about.terms` 与 zh 同结构（缺 `<i>`）。
推荐流程（不手改 JSON）：应用 A/B 后跑现有转换流水线
`.tmp/zh-hant2/build_hant_refresh.py` 重新生成 `data/i18n_zh_hant.json`（OpenCC 会保留 `<i>` 标签）。
若需最小手改，三处替换（繁体值）：

```text
「網路俗稱 / 舊名」   → <i>「網路俗稱 / 舊名」</i>
「未證實」            → <i>「未證實」</i>
「社區叫法」          → <i>「社區叫法」</i>
```

应用后 `about.nick` 的标签序列将与 en 完全一致（18 个标签），`about.terms` 为 30 个标签；
模拟验证见 §3（`i18n_sim.js` 即按此补丁构造）。

### 2.3 可选：checker 误报修正（`etl/check_translations.py`，本任务范围外，建议下一轮 etl owner 做）

`check_html` 目前把**内联代码跨度**里的 `<term>` / `<build timestamp>` 当 HTML 标签，造成 4 条误报。
建议在比较前剥掉反引号代码跨度（不会影响真实 HTML，因为模板里的 HTML 不在反引号内）：

```python
CODE_SPAN_RE = re.compile(r"`[^`]*`")

def check_html(key: str, lang: str, src: str, tgt: str) -> None:
    a = TAG_RE.findall(CODE_SPAN_RE.sub("", src))
    b = TAG_RE.findall(CODE_SPAN_RE.sub("", tgt))
    ...
```

同理 release notes 的 `term` 规则建议跳过（自由文本里的产品名/INN 英文名/代码 token 不是术语错误），
或只保留 `safety` 强项检查。改完可直接把剩余 25 条降到约 21 条（全是词义/变体类，需人工判定）。

---

## 3. 验证（可复现）

```powershell
# 1) 仅数据修复后（当前 site/dist 未重建；critical 1 来自旧 dist 的 combo 值）
& $py etl/check_translations.py --quiet
#    → findings 31（warning 30 / critical 1），--strict 退出 1（旧 dist 未重建）

# 2) 当前源码口径（build.py 已含 combo/about.samename 修复）
& $py etl/check_translations.py --i18n site/build.py --quiet
#    → findings 27（warning 27 / critical 0）；注意 AST 只解析到 269 键（部分 f-string 字典未展开）

# 3) 模拟「patch 已应用 + 已重建」的 4 语言 328 键产物
& $py etl/check_translations.py --i18n .tmp/terminology-fix/i18n_sim.js --quiet
#    → findings 25（warning 25 / critical 0）；--strict 退出 0 ✅
```

三口径的完整输出：`.tmp/terminology-fix/check_{dist_after_data,build_py_source,sim_patched}.json`
与对应 `findings_*.csv`；模拟产物构造脚本 `.tmp/terminology-fix/build_sim.py`。

> 注意：`site/dist/assets/i18n.js` 是 12:04 的旧构建（含旧 combo es / 旧 about.samename es）。
> 应用 §2.2 patch 并重建后，用**默认口径**跑 checker 应得到 critical 0、warning ≈25；
> 若仍有 4 条 release-notes html 误报，按 §2.3 修 checker 即可。

---

## 4. 修复后剩余事项

| 类别 | 数量 | 处理 |
|---|---:|---|
| build.py 待 patch（zh about.nick/terms + zh-Hant 字典重生成） | 3 处 + 字典 | §2.2，交给 impl-lazyload（v0.6.6） |
| release notes html 误报（代码跨度 `<term>`） | 4 | §2.3 checker 修正（etl owner；不改译文） |
| term 词义/变体类 warning | 21 | §5 分类；不加急、分批在下次 glossary 更新时补变体或人工判定 |
| es_ui_missing / release_notes 的其它「建议」行 | — | 本任务已处理可直接改的；其余等 build.py es 接线时统一处理 |

---

## 5. 剩余 25 warning 分类（均为 warning，无 critical）

**A. checker 误报：内联代码跨度（4 条，全是 html）**
`release:v0.4.1#2`（en/es，`search-<term>`）、`release:v0.2.4#1`（en/es，`?v=<build timestamp>`）——
反引号内字面量被 TAG_RE 当标签；按 §2.3 修 checker 即可，**不改译文**。

**B. 产品名 / 代码 token（不应改译，~8 条）**
`Strength`（`Excedrin Extra Strength` 产品名、`strength_basis` 字段名）、`warning`（`dose_warning` 字段名）、
`patch`（`Pain Relief Patch` 产品名）、`unknown`（状态代码字面量）。这些在 en/zh/es 中都是专名或代码，保持原样。

**C. 基准变体缺口（建议下次 glossary 更新补变体，~5 条）**
`ARTG number`（zh 用「ARTG 号」）、`look-alike, sound-alike`（zh 用「形似/音似」拆写）、
`tablet`（zh-Hant 用「錠」）、`active ingredient`（es 用「principio」简写）。属基准表写法覆盖不足，
不是译文错；可在 `data/terminology_glossary.csv` 的 variants 列补齐。

**D. 需人工判定的措辞（~4 条）**
`Strength` 出现在 `about.gaps` / `meta.index.desc` / `about.sources`（`强度`/`fuerza`/`concentración` 混用）、
`conf.source_note` 的 `warning`（zh 写作「提示/警告」需确认语气）。这些是**文案选择**，
不影响 critical，列入下一轮文案统一即可。

---

## 6. 风险与边界

1. **es_ui_missing.csv 是「缺口建议表」**，不是 build.py 的运行时文案；本次修复让建议本身正确
   （占位符/HTML 合法、术语一致），真正接线仍由 build.py owner 决定（es 标题模板一直未接线）。
2. **dist 未重建**：当前 checker 默认口径仍会看到 1 条旧 critical；重建后消失（源码已修）。
3. **build.py patch 行号会漂移**：清单按锚点字符串给出；应用前建议 `python -m py_compile site/build.py`。
4. **zh-Hant 字典必须重生成**：直接手改 `data/i18n_zh_hant.json` 会在下次 refresh 时被覆盖；
   推荐先改 build.py zh，再跑既有流水线。
5. 本任务未改 `etl/check_translations.py`（不在写范围）：4 条 release-notes html 误报保留到 §2.3 修复。

---

## 7. 证据文件

| 路径 | 内容 |
|---|---|
| `data/es_ui_missing.csv` | 39 行；3 行修复（§1.1） |
| `data/release_notes_i18n.json` | 24 版本 / 95 条；2 条 es 修复（§1.2） |
| `.tmp/terminology-fix/fix_es_missing.py` / `fix_release_notes.py` | 修复脚本（可复现） |
| `.tmp/terminology-fix/i18n_sim.js` / `build_sim.py` | 模拟 patch 后 328 键×4 产物与构造脚本 |
| `.tmp/terminology-fix/check_*.json` / `findings_*.csv` | 三口径校验结果（31/27/25） |
| `.tmp/terminology-fix/tag_diff.py` / `dump_about.py` / `dump_build.py` | about.*/combo 标签差异与源码定位证据 |
| `.tmp/terminology-fix/README.md` | 证据索引 |
| `reports/terminology-accuracy.md` | 原始 38 findings 报告（task-83） |
