# 批次 B（结果区 L2–L6 + L16）改动计划 + 已落地代码的证据

> 工位：site-ui　｜　日期：2026-11-15
> **状态：代码已在工作树里（未 commit、未进 v0.11.10 —— Lead 从 HEAD 构建），等 Lead 说「可以动手/已发布」再决定是否保留或调整。**
> 期间按 Lead 要求**冻结 `site/build.py`**（本文件之后没有再改）。只读的度量、计划、报告不受影响。

## 0. 结论（先看这 5 条）

1. **L2 列序已按用户口径**：结果表 = 产品名称 / 成分 / 规格与剂型 / 市场 / 操作；药名 **17px / 700**（全表最大字号最深字重）。
2. **L3 按钮语义**：「选择此产品」（原 `◎` 图标）、「查看登记详情」、「查看其余 {n} 个产品」（原 `加载更多 (+10)`）；
   「与目标市场产品对照」沿用 T11 的 `t11.compare_link`（在顶部 pickbar 里，选完即出现）。
3. **L4 选中态**：被选行浅绿底（`--accent-weak`）+ 左侧 3px 绿色标记 + 「已选择」徽标 + 行内「选择此产品」隐藏；
   顶部 pickbar 保留紧凑摘要（已选名称 / 市场 / 成分 / 规格）+「重新选择」。
4. **L5 一区一个实心绿主按钮**：搜索区只有 `#qgo` 实心；结果行内按钮全是描边/文字样式；
   身份卡里只有「查看成分页」是实心（`.idacts .primary`）。
5. **L6 搜索后压缩**：`html.has-q` 下隐藏 `home.sub` / `.candidate-line` / `#u1guide` / `.flow3` / `#loadhint`，
   H1 降到 22px；身份卡折成「标题 + 查询→成分 + 更多记录」两行（原来桌面默认展开 289px）。
   结果页正文字号 **14px → 16px**（修掉 `min_body_font=14` 未达标）。

## 1. 改动位置（`site/build.py`，供 Lead 复核 diff）

| 项 | 函数 / 常量 | 改动 |
|---|---|---|
| L2 | `flatRowHTML()` / `flatTableHTML()` | 列序改为 brand → `ingredientLabel(e)` → spec → market → actions；表头用 `res.col_product` / `col.ing` / `res.col_spec` / `res.col_market` / `res.actions` |
| L2 | `CSS`：`table.res.rows .c-brand{font-size:17px;font-weight:700;color:var(--fg)}` | 药名最大最深；`table-layout:fixed` + 列宽百分比，窄栏下省略号收，不撑破页面 |
| L3 | `flatRowHTML()` | `pickBtn` 文案 → `res.pick`；`det` 文案 → `res.reg`；`flatTableHTML()` 的 load-more → `res.more_n` |
| L4 | `flatRowHTML()` | `isPicked`（`window.T11.pick === e.k`）→ `tr.br.picked` + `.picked-tag`「已选择」+ 隐藏该行 pick 按钮 |
| L4 | `CSS` | `tr.br.picked{background:var(--accent-weak);box-shadow:inset 3px 0 0 var(--accent)}` |
| L5 | `CSS`：`.pickbtn/.detbtn` | 描边文字按钮（26px 高），不引入第二个实心绿 |
| L6 | `CSS`：`html.has-q …` | 隐藏引导块、H1 22px、身份卡压缩到 99px |
| L6 | 身份卡模板（`render` 内的 `<details class="idmore">`） | 去掉桌面 `open`，所有宽度默认折叠；`.idmore>summary` 从「仅 ≤600px 显示」改为始终显示 |
| L16 | — | **未做**（等 task-7 规范里的三条具体口径） |

## 2. 四语文案（新增 7 键，写在 `UI_I18N` 四语 + `FR_I18N`）

| key | en | es | zh | zh-Hant | fr |
|---|---|---|---|---|---|
| `res.col_product` | Product name | Nombre del producto | 产品名称 | 產品名稱 | Nom du produit |
| `res.col_spec` | Strength & form | Concentración y forma | 规格与剂型 | 規格與劑型 | Dosage et forme |
| `res.actions` | Actions | Acciones | 操作 | 操作 | Opérations |
| `res.pick` | Pick this product | Elegir este producto | 选择此产品 | 選擇此產品 | Choisir ce produit |
| `res.reg` | Registry details | Ficha del registro | 查看登记详情 | 檢視登記詳情 | Fiche d’enregistrement |
| `res.picked` | Selected | Seleccionado | 已选择 | 已選擇 | Sélectionné |
| `res.more_n` | Show the other {n} products | Ver los otros {n} productos | 查看其余 {n} 个产品 | 檢視其餘 {n} 個產品 | Voir les {n} autres produits |

`deploy/i18n_check.py`：**FAIL 0 / WARN 2 / INFO 24**，五语各 **638 键**（fr 的 `res.actions` 用 `Opérations`，
避免「与英文完全相同」的伪翻译 FAIL）。

## 3. 验收数字（`first_screen_check.py`，临时产物 `.tmp/v01110`，真实索引数据）

| 页面 / 视口 | items | AFCR | band_ratio | 正文px | overflow | 判定 |
|---|---|---|---|---|---|---|
| home 1440 | 9.0 | 1.00 | 0.67 | 16 | 否 | ok |
| home 390 | 0.0（entry 页 items_min=0） | 0.93 | 1.00 | 16 | 否 | ok |
| results 1440 | **3.0**（改前 3.0） | 0.90 | 0.67 | **16**（改前 14） | 否 | ok |
| results 390 | **0.5**（改前 0.5） | 0.88 | 1.00 | 16 | 否 | 未达（items，见 §4） |
| drug 1440 | 7.0 | 1.00 | 0.67 | 16 | 否 | ok |
| drug 390 | 4.5 | 0.92 | 1.00 | 16 | 否 | 未达（items，改前 4.5，未退化） |

- **results 页 items = 3.0 是查询本身的物理上限**：`index.html?q=泰诺&lang=zh` 只有 **3 条候选**
  （`document.querySelectorAll('#reswrap tbody tr.br').length === 3`），首屏第 1 行 top=579px、
  行高 40px → 首屏能放 8 行，但只有 3 行可放。改前同样是 3.0。
  **建议**把首屏守卫的结果页抽查改成候选更多的查询（如 `?q=tylenol` 或 `?q=paracetamol`，≥8 条），
  否则 `items_min=5` 这条对结果页永远不可能通过（`deploy/` 不在本工位写权限）。
- results 390 的 0.5 与改前一致（未退化）；手机首屏被 sticky 搜索 + 身份卡占掉，属 L16 范围。

## 4. 缺口 / 待 Lead 与规范

1. **L16 手机三项**：等 task-7 规范（`reports/2026-11-15-ui-redesign-spec.md`）明确「三项」指哪三项后实现。
2. **results 390 items 0.5** → 需要在移动端把身份卡收得更多（只留一行）、或把结果表头做成 sticky 悬浮；
   这是 L16/移动端专项，建议在批次 B 的移动端收尾里一并做。
3. **`dist-integrity` 现在 FAIL** 是 Lead 正在重建 `site/dist`（构建中点文件缺失），不是代码问题；
   Lead 构建结束后 `ci_checks --fast` 应回到 PASS 8 / FAIL 0。
4. 本批代码在 `site/build.py` 工作树里**未 commit**：若 Lead 的 v0.11.10 从 HEAD 构建，则不含本批；
   请 Lead 在「已发布」后告知是否保留（或需要我把它们拆成 patch 便于只取 L2/L3/L4 一部分）。
