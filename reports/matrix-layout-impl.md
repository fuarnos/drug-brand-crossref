# v0.6.6 成分页：语言优先 + 多国并排矩阵 + 隐藏停售 实现报告

> 任务：task-77（`site/build.py` 独占，v0.6.5 之后）。用户反馈：中文页先显示 US/英语区；希望不同国家并排、商品名/规格有表格线、停售不显示。
> 另按 task-91 / Lead 要求顺手应用术语补丁（§4）。
> 未跑 git/发布、未改 `site/dist`、`data/drugs.db` 或其他跟踪文件。构建：`SITE_OUT=.tmp/dist-matrix`。

## 0. 结果

| 项 | 结果 |
|---|---|
| 成分页布局 | 改为**多国并排矩阵**：行 = 规格 + 剂型 + 释放机制，列 = 国家（≤8）；单元格品牌 ≤3 + `+N`，无记录「未收录」；行上限 120 |
| 语言列序（headless 实测） | en 首列 **US**；es 首列 **ES**（MX 第二）；zh 首列 **CN**；zh-Hant 首列 **TW**（TW 已有数据） |
| active-only | 只显示 `status='active'`；停售/撤市/状态未确认默认隐藏，页面有四语说明；metoprolol 停售品牌（LOPITROL/KAPIRMETOL/DELANDEX/OVAXTYL）实测不出现 |
| 表格线 | `table.matrix th/td{border:1px solid var(--line)}`，headless 计算样式确认 borderLeftWidth ≠ 0 |
| 移动端 | 390px 宽：页面 **不横向溢出**（390 ≤ 390），矩阵容器内部横滚（1037 > 362） |
| 四语 | `matrix.spec/none/hidden_note/capped` ×4 语；I18N **332 keys ×4 完全一致** |
| 构建 | exit 0；**60,375 文件 / 436.3 MB**；sitemap **60,219 URL**；drug 12,246 / name 30,383 / combo 10,569 / maker 6,997 |
| 样例 | acetaminophen：**87.4 KB**、8 列、120 行（截断提示 “Showing the first 120 of 291 strength/form rows”）；metoprolol：**42.0 KB**、7 列、58 行 |

> 体积从 v0.6.5 的 408.7 MB 增至 436.3 MB，主要来自 **DB 数据增长**（构建时索引 157,462 keys，v0.6.5 构建时为 127,085；TW 16,457 产品等），矩阵本身：drug 页 56.9 MB（v0.6.5 约 54 MB 量级），acetaminophen 53.7→87.4 KB、metoprolol 38.8→42.0 KB。

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| 常量：默认国家顺序（en）、矩阵行上限 | `COUNTRY_PRIORITY` / `MATRIX_ROW_CAP = 120`（`build_drug_pages` 前） |
| `build_drug_pages(db, entries)`：品牌按 `key_id → entry` 映射（`e.d` 显示、`e.u` 链 name 页；无页纯文本，不回退 drug） | 函数签名 + `entry_by_k` + names 查询（`pn.key_id`） |
| 矩阵聚合：行 (strength, form, release)，列 = 出现国家；品牌去重 ≤3 + `+N`；空单元格 `matrix.none` | `build_drug_pages` 中部 |
| active-only + 停售说明 + 截断提示（四语 lang-block，数字构建期替换） | 同上 / 页面 body 尾部 |
| 主调用传 entries | main：`n_drug = build_drug_pages(db, entries)` |
| 客户端列序：`MORDER`（en/es/zh/zh-Hant）在 i18n.js `apply()` 中重排 `table.matrix` 的 `data-country` 单元格 | `_render_i18n_js` apply |
| 矩阵 CSS：表线、`min-width`、`.matwrap` 横滚、移动端 | CSS `.matwrap` / `table.matrix` / `@media` |
| 新增 i18n：`matrix.spec/none/hidden_note/capped` 四语 | `UI_I18N` 四个语言块 |
| 站内链接不变量：`u` 有值的 name 条目即使 data 缺行也生成最小页（防 `../name/` 404） | `build_name_pages` |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-matrix'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-matrix\assets\app.js                      # 0
& $node --check .tmp\dist-matrix\assets\i18n.js                     # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-matrix'    # 25/25 PASS
# 临时 http.server 8805 + headless.mjs（Chrome CDP）→ ALL CHECKS PASSED
```

- **静态 25/25**：矩阵表格/表头 i18n/国家列 ≤8 且默认 en 首列 US；行数 120 截断 + 四语 lang-block；停售说明；空态 `matrix.none`；品牌链 name 页；旧纵向 H2 布局消失；metoprolol 停售品牌不出现；**抽样 80 页 267 个品牌链接全部存在（无 404）**；CSS 表线/横滚；四语 332 keys 一致；`MORDER` 存在。
- **Headless（Chrome CDP，真实布局）**：en/es/zh/zh-Hant 首列分别为 US/ES/CN/TW；表头本地化（Strength… / Concentración… / 规格… / 規格…）；停售说明四语；矩阵可见表线；active-only；品牌链接 HTTP 200；移动端无溢出 + 内部横滚。
- **样例**：acetaminophen（291 个规格行 → 截断 120、8 国含 TW）；metoprolol（58 行、7 国）。

## 3. 风险 / 已知事项

1. **TW 已出现在矩阵**：DB 已有 TW 16,457 产品，矩阵按数据自动多出 TW 列（acetaminophen 8 列）；`markets/languages` 配置仍 disabled，首页/国家选择器尚未开放 TW（task-87 负责启用与断言；task-81 负责 build.py 内置 TW 文案/来源）。
2. **体积增长**：436.3 MB（主要 DB 数据增长 + 矩阵/名称页）；矩阵行上限 120 控制极端页（最大成分 837 规格行 → 截断）。
3. **语言列序为客户端 JS**：服务端默认 en 顺序；无 JS 时 en 顺序可读、不影响内容。zh-Hant 的 TW/CN/HK 顺序在 TW 有数据时生效。
4. **品牌→品牌页**沿用 v0.5.3 规则（无品牌页纯文本，不回退 drug 页）；矩阵单元格最多显示 3 个品牌 + `+N`（不逐个链接全部品牌）。
5. **停售隐藏**无开关（本轮按任务不做历史开关）；unknown 状态同样隐藏（比任务要求的 discontinued/withdrawn 更保守）。
6. 旧 `drug.showing/records/status.*` 等纵向表格文案不再使用（数据保留在字典，无副作用）。

## 4. 术语补丁（task-91 / Lead 要求，v0.6.6 一并修）

| 项 | 状态 |
|---|---|
| `combo.cross_overlap` / es 强化为不可互换 | ✅ 已是：`…similar pero NO idéntica: no son intercambiables.`（dist 实测） |
| `about.samename` / es 补回 1 个 `<b>`（UK Benadryl） | ✅ 已修，es about.* 标签结构与 en 完全一致 |
| `about.nick` / zh 补 2 个 `<i>`（「网络俗称 / 旧名」「未证实」） | ✅ 已按 patch 清单应用（dist：zh about.nick `<i>` ×2） |
| `about.terms` / zh 补 1 个 `<i>`（「社区叫法」） | ✅ 已应用（dist：zh about.terms `<i>` ×1） |
| zh-Hant 的 `about.nick`/`about.terms` 缺 `<i>` | ⚠️ 在 `data/i18n_zh_hant.json`（data 侧；patch 清单 §2.2C 建议重新生成），**不在本任务写范围**，未改；build.py 侧已有 zh 值，zh-Hant 待 data 任务 regenerate 后自动带标签 |

## 5. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | 删 `COUNTRY_PRIORITY/MATRIX_ROW_CAP` 与矩阵渲染段、恢复旧纵向国家表格；删除 i18n.js `MORDER` 重排；删 matrix.* keys/CSS；删 name 页兜底 |
| 发布后 | gh-pages revert 上一提交（页面布局/文案变化，无数据文件变化） |

## 6. 产物

- `site/build.py`：矩阵布局、语言列序、active-only、矩阵 CSS/i18n、术语补丁、name 页链接兜底。
- `.tmp/dist-matrix/`：构建产物（60,375 文件 / 436.3 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`（TEMP `matrix-verify-20261027/`）。
- `reports/matrix-layout-impl.md`：本报告。
