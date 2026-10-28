# 西语（es）UI 缺口审计 + What's new 三语翻译数据（task-43）

> 日期：2026-10-28 ｜ 范围：现有三种界面语言（en / zh / es），不新增语言、不改 build.py、不写 DB
> 产物：`data/release_notes_i18n.json`（21 版本 / 86 条目，中英西）· `data/es_ui_missing.csv`（39 行残余缺口）· 本报告
> 复现脚本与原始审计数据：`.tmp/es-i18n/`；边界：未改 `site/build.py`、`data/drugs.db`、未跑 git/发布。

---

## 1. 结论（先说答案）

| 审计项 | 结果 |
|---|---|
| I18N 字典（合并 ABOUT/PAGE/WARN 后） | **en/es/zh 各 191 键，完全对齐，缺 es = 0** |
| 模板实际使用的 117 个字面 key | **全部有 en + es**（无回退英文的 key） |
| en 与 es 值相同的键 | 5 个，均为专有名词/技术词（`home.au`=Australia、`home.cn`=China、`parse.match.nickname`=alias、`parse.match.pinyin`=pinyin、`warn.sev.info`=Info）——**无需处理** |
| **`/warn` 页标签与警示正文** | 标签键 es 全覆盖；`dose_warning` 41 条（40 published + 1 draft）**title_es / body_es 均 41/41** → **0 缺口**（v0.5.1 已闭合，本轮复核） |
| **About 页** | 正文 `about.*` 键三语齐全；83 条"不受 i18n 控制"的可见文本中 78 条是**许可段三语并列**（设计如此）+ 品牌/语言切换，**无漏翻段落** |
| **404 页** | 不受 i18n 控制的可见文本 **0 条**（v0.5.0 已闭合） |
| **真正残余的 es 缺口** | **39 行**（CSV）：`title` 7 + `meta`/`og` 8 + `html lang`/`hreflang` 2 + 品牌 logo 1 + **What's new 正文 21 个版本** |
| 优先级分布（CSV） | **P1 30 / P2 4 / P3 5** |
| What's new 翻译 | **21 个版本 / 86 条要点**，中文权威，en + es 机器翻译，已落 `data/release_notes_i18n.json`（`machine_translated: true`） |

一句话：**字典与 warn/About/404 的西语化已经做过（v0.5.0–v0.5.1），剩下的缺口集中在「页面骨架」——`<title>`/meta/og/hreflang/静态 lang 仍是英文，以及 What's new 正文仍是中文；后者翻译数据本轮已备好、等 build.py 接线。**

---

## 2. What's new 三语翻译数据：`data/release_notes_i18n.json`

### 2.1 结构与口径

- **中文是唯一权威**：`zh` 数组逐条来自 `CHANGELOG.md`（由 `.tmp/es-i18n/parse_changelog.py` 解析；不重写、不改写原文）。
- **en / es 为 AI 机器翻译**：每个版本对象带 `machine_translated: true`，顶层 `_meta.translations` 明确写 "machine (AI) translation of the zh text; zh is authoritative"。
- 版本范围：`v0.5.2` → `v0.1.0`，共 **21 个版本**（CHANGELOG 现有全部 `##` 段；任务写 20 个，实际 21 个，全部覆盖）。
- 条目：**86 条**（85 bullet + 2 heading，v0.1.0 的"首次上线"表格按原文保留在 zh 字符串里，en/es 用一句市场清单翻译）。
- 字符量：zh 9,521 / en 18,232 / es 20,060（西语比中文长 2.1×，属正常印欧语膨胀；UI 排版风险见 §5）。
- 生成脚本可复现、带长度校验：每个版本 en/es 数组长度必须等于中文条目数，否则拒绝写文件。

```json
{
  "_meta": {
    "schema": 1, "source": "CHANGELOG.md", "authoritative_language": "zh",
    "translations": {"en": "machine (AI) translation of the zh text; zh is authoritative",
                     "es": "machine (AI) translation of the zh text; zh is authoritative"},
    "machine_translated": true, "versions": 21, "items": 86,
    "note": "Keep this file out of site/build.py until the review is done."
  },
  "v0.5.2": {
    "date": "2026-10-29",
    "zh": ["**修复 /warn 与成分页警示在中文/西语下空白**：……"],
    "en": ["**Fix: /warn and ingredient-page warnings were blank in Chinese/Spanish** — ……"],
    "es": ["**Corrección: los avisos de /warn y de la página de principio activo aparecían en blanco en chino/español** — ……"],
    "machine_translated": true
  }
}
```

### 2.2 翻译原则（写进 `.tmp/es-i18n/translations.py` 头注释）

1. 保留版本要点、关键数字、`etl/`、`data/`、表名/代码标识不译；
2. 命令、路径、`?legacy=1`、代码片段保持原样；
3. 语气与站点一致（信息参考，不构成用药建议）；
4. 超长功能条目压缩为"主结论 + 1–2 个数字"，避免 What's new 行文冗长；
5. 不把许可原文当普通文案机器翻译——About 许可段本来就有官方/人工三语并列（见 §3.4）。

### 2.3 接线建议（未来，需改 `site/build.py`，本任务禁止）

- `build_whats_new()`（`site/build.py:2707-2719`）目前 `load_releases()` 直接渲染 `CHANGELOG.md` 的中文 HTML，正文不区分语言。
- 建议：读 `data/release_notes_i18n.json`，按页面语言输出 `zh/en/es` 数组对应渲染；缺该语言时回退中文；页面保留 `whatsnew.lang_note` 说明"机器翻译，中文为准"。
- 过渡方案：在 `whats-new.html` 顶部给英/西用户一句 "Machine translations of the release notes are available in `data/release_notes_i18n.json`"（等接线后再移除）。
- **审校流程**：机器翻译先标 `machine_translated`，人工过一遍（重点：数字、药名、法规实体）后把 `_meta.translations` 改成 `"reviewed"` 再上线。

---

## 3. es UI 缺口审计（方法 + 结果）

### 3.1 方法（4 个只读脚本，均可复跑）

| 脚本 | 作用 |
|---|---|
| `.tmp/es-i18n/audit_i18n2.py` | 导入 `site/build.py` 模块、调用 `_merge_static_i18n({})` 得到**合并后** I18N（BASE + ABOUT/PAGE/WARN），对比三语键；再用正则取模板里 `data-i18n` / `T('…')` 实际使用的 key |
| `.tmp/es-i18n/audit_ui.py` | 从 `site/dist` 抽每页 `<title>` / `<html lang>` / meta / hreflang；查 `i18n.js` 是否更新 `document.title`；DB 只读查 `dose_warning` 的 es 覆盖率；列 `page()` 的硬编码 title 参数 |
| `.tmp/es-i18n/extract_untranslated.py` | 用 HTMLParser 抽 `site/dist` 每页**不受 i18n.js 控制**（不在 `data-i18n`/`data-i18n-html`/`data-lang-block`/`data-ph` 里）的可见文本 → 真正的残余缺口 |
| `.tmp/es-i18n/build_ui_missing.py` | 汇总成 `data/es_ui_missing.csv`（39 行，含建议西语与代码位置） |

判定"es 缺口"的口径：**es 界面下用户/搜索引擎最终看到的文本，是否已由构建期语言或运行时 i18n.js 换成西语**。`data-i18n` 键在、es 值在 = 已闭合；仅英文/中文且无 i18n 锚点 = 缺口。

### 3.2 字典层：0 缺口

- 合并后 en/es/zh 各 **191 键**（BASE 139 + ABOUT 22 + PAGE 21 + WARN 18 − 重复 9），三语逐键对齐，`missing_es=[]`。
- 模板使用的 117 个字面 key（不含 `warn.group.{sev}` 这类动态拼接）**全部命中 en 与 es**。
- 仅有 5 个 en=es 同值键，均为专有名词/技术词，不算漏翻。

### 3.3 /warn 页：0 缺口（已闭合）

| 项 | 结果 |
|---|---|
| UI 标签键（`warn.title/intro/count/no_advice/group.*/sev.*/source/related/countries/reviewed/drug_summary/see_all/empty/source_note`） | es 全部存在 |
| `dose_warning` 数据行 | 41 条：`title_es` 41/41、`body_es` 41/41（1 条 draft 不发布，published 40） |
| es 页面可见文本 | `warn.html` 仅剩品牌/语言/版本等 6 条（见 §3.4），**无英文标签残留** |

> v0.5.1 的"41 条警示补 `title_es/body_es`"本轮复核属实；本轮不需要新增 warn 文案 key。

### 3.4 从 `site/dist` 抽出的"不受 i18n.js 控制"文本（按页）

| 页面 | 条数 | 内容与判定 |
|---|---:|---|
| `index.html` / `es/index.html` / `zh/index.html` | 12 / 12 / 12 | 品牌名、中文副标题、EN/ES/中文切换、5 个示例药名、覆盖率数字、"v0.5.2 · 日期"——**均为语言中立或品牌元素**，无漏翻（但 title 另算，见 §4） |
| `about.html` | 83 | **78 条是许可段三语并列**（EN + 中文 + ES 同段展示，`reports/license-audit.md §4` 的设计）+ 品牌/语言切换；**无漏翻段落** |
| `warn.html` | 6 | 品牌/语言/版本，无缺口 |
| `whats-new.html` | 379 | **release notes 正文（中文）**：21 个版本全部中文，en/es 界面同样显示中文 → **最大残余缺口**（翻译数据已备好，见 §2） |
| `confused.html` | 89 | FDA tall-man 药名（专有名词）+ 品牌；正文注释键 es 已覆盖，无缺口 |
| `404.html` | **0** | v0.5.0 已三语化，无缺口 |

### 3.5 页面骨架缺口（title / meta / lang）

| 观测 | 现状 |
|---|---|
| `<title>` 模板 | `page()`（`site/build.py:2610`）固定 `{title} · Medicine Brand Cross-Reference`；title 参数全是英文：`Warnings`(1199)、`What's new`(2782)、`About`(3470)、`Easily confused drug names`(3509)、404 独立模板 `Page not found`(3523) |
| 入口页 title | `page("Medicine Brand Cross-Reference", …)`(3397) 再拼站名 → **`Medicine Brand Cross-Reference · Medicine Brand Cross-Reference`**（站名重复，三语入口相同） |
| i18n.js | `apply()` 更新 `data-i18n` / `data-i18n-html` / `data-lang-block` / `data-ph` 与 `documentElement.lang`，**但不更新 `document.title`** → 即使客户端切到 es，标签页/分享卡仍是英文 |
| meta | 全站只有 `viewport`（+404 的 `robots`）；**无 meta description、无 og:title/og:description/og:locale** |
| `<html lang>` | 静态输出：入口页正确（es/zh 有 `lang="es"/"zh"`），about/warn/whats-new/confused/404 **固定 `lang="en"`**；运行时由 JS 修正，无 JS/爬虫看到 en |
| hreflang | 只有 3 个入口页有 alternate（且已用 `SITE_URL` 修正子路径）；**子页面全部没有 hreflang** |
| 品牌/logo | `page()` header 写死 `Medicine Brand Cross-Reference` + 中文副标题 `药品商品名跨国定位`，es 页面仍显示中文副标题 |

---

## 4. `data/es_ui_missing.csv`（39 行）说明

列：`key, page, location, en_text, es_suggested, issue, priority, evidence`（UTF-8 BOM，Excel 可直接开）。

| 类别 | 行数 | key 示例 | 优先级 | 建议改法（需建站 owner 执行） |
|---|---:|---|---|---|
| `<title>` | 7 | `page.title.warn`、`page.title.index` | P1 | `page()` 增加 `title_i18n` 参数，按语言取标题；修 3397 的站名重复 |
| meta description / og | 10（8 行 + 模板 2 行） | `meta.description.index`、`meta.og.tags` | P1–P3 | `page()` 增加 `description` / og 参数，接 I18N 键（新增 `meta.*` 三语键） |
| html lang / hreflang | 2 | `page.html_lang.static`、`page.hreflang.subpages` | P2/P3 | 静态输出按语言渲染；子页 `alternates=True` |
| 品牌 logo | 1 | `brand.logo` | P3 | 品牌名保留英文，副标题跟随语言（或移除中文副标题） |
| What's new 正文 | 21（每版本 1 行） | `whatsnew.release.v0.5.2` … `v0.1.0` | P1 | 接 `data/release_notes_i18n.json`（§2.3） |
| **合计** | **39** | — | P1 30 / P2 4 / P3 5 | — |

> 说明：warn 页标签与 About 段落**不在 CSV 里**，因为本轮复核确认已闭合（§3.3/§3.4）；如果后续把许可段改成"按语言只显示一份"，那属于产品决策，不是漏翻。

---

## 5. 风险与限制

1. **机器翻译未经人工审校**：`release_notes_i18n.json` 全部 en/es 都是 AI 翻译；上线前需人工过一遍（重点：剂量/数字、药名、法规实体、许可表述）。数据里已用 `machine_translated` 明确标注。
2. **西语长度膨胀**（zh 9.5k → es 20k，2.1×）：What's new 是老式卡片布局，es 长句可能换行/溢出；`reports/i18n-audit-20261026.md §5` 已提示 CSS 无 `@media`，接线时建议先抽查 3 个版本的 es 渲染。
3. **静态 es 页面缺失**：目前只生成 `es/index.html`；about/warn/whats-new/confused/404 是"英文 HTML + 运行时 JS 翻译"，无 JS/搜索引擎看到 en。这是架构级缺口（`reports/i18n-audit-20261026.md` P3），本轮只登记未改。
4. **title/meta 改动需重建+发布**：本任务禁止改 `site/build.py`/构建；CSV 给的是建议值与精确行号，接线后需按 AGENTS.md 跑 `site/build.py` 全量验收（三语抽检 + 页数/索引回归）。
5. **许可段不是漏翻**：About 的许可文字是三语并列原文（避免机器翻译法律文本），不得按"未翻译"处理。
6. **数据漂移**：I18N 键数/CSV 行数基于当前 `site/build.py`（3,944 行）与 `site/dist`；后续页面改动需重跑 `.tmp/es-i18n/audit_ui.py` 更新。

---

## 6. 复现命令与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) CHANGELOG → 结构化中文条目
& $py .tmp/es-i18n/parse_changelog.py
# 2) 合并 I18N 审计（键覆盖 / 模板使用）
& $py .tmp/es-i18n/audit_i18n2.py
# 3) 页面 title/meta/lang + warn 数据 es 覆盖 + 硬编码扫描
& $py .tmp/es-i18n/audit_ui.py
# 4) dist 中不受 i18n.js 控制的可见文本
& $py .tmp/es-i18n/extract_untranslated.py
# 5) 生成 release_notes_i18n.json（校验长度后写）
& $py .tmp/es-i18n/build_notes.py
# 6) 生成 es_ui_missing.csv
& $py .tmp/es-i18n/build_ui_missing.py
```

| 产物 | 内容 |
|---|---|
| `data/release_notes_i18n.json` | 21 版本 × 86 条目 ×（zh 权威 / en / es 机器翻译）+ `_meta` |
| `data/es_ui_missing.csv` | 39 行 es UI 缺口（key/page/location/en_text/es_suggested/issue/priority/evidence） |
| `.tmp/es-i18n/parsed.json` | CHANGELOG 结构化中文原文 |
| `.tmp/es-i18n/translations.py` | en/es 翻译源（86 条 ×2） |
| `.tmp/es-i18n/audit.json` + `i18n_keys.json` | I18N 键对比、used key、dist title/meta、warn 数据覆盖 |
| `.tmp/es-i18n/dist_untranslated.json` | 每页"不受 i18n 控制"的可见文本明细 |
| `.tmp/es-i18n/build_notes.py` / `build_ui_missing.py` / `parse_changelog.py` / `audit_*.py` / `extract_untranslated.py` | 可复跑脚本 |

边界：只写了 `data/release_notes_i18n.json`、`data/es_ui_missing.csv`、本报告与 `.tmp/es-i18n/`；**未改 `site/build.py`、`data/drugs.db`，未跑 git/发布**。报告里的"建议改法"是给建站 owner 的输入，不是已实施改动。
