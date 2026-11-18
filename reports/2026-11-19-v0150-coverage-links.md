# v0.15.0：LG3 覆盖页界面语言状态 + Q19 澳门 / K2 韩国官方入口

> task-9（site-ui）。只改 `site/build.py` 的覆盖页 / About 两段；**未写库、未改 `data/markets.json`、未写 `site/dist`、未跑全量构建**。

## 1. 结论先行

| 验收项 | 结果 |
|---|---|
| 覆盖页 15 行界面语言状态 | ✅ 15/15 行都有；读 `data/markets.json`（phaseb-plan 13:35 已落盘）：12 个市场在「查看原因」summary 显示 `· 界面语言 ✅`，**JP / CZ / LV 显示「母语 ja/cs/lv 未覆盖」**（六语短词，不新增行） |
| 与 markets.json 逐行一致 | ✅ 自检逐行对照（合成与真实数据两轮；缺字段容错） |
| About 六语 MO/KR 入口 | ✅ 6 语副本都含 `isaf.gov.mo` + `nedrug.mfds.go.kr`、署名（ISAF / MFDS）、「只提供官方查询入口，不复制其数据」+「韩国需本人注册 data.go.kr、暂不入库」 |
| 覆盖页官方入口 | ✅ 表格下方新增「官方查询入口」六语块（同两条 + 同措辞） |
| `i18n_check` | ✅ FAIL 0（WARN 26 / INFO 26，未新增 I18N 键） |
| `ci_checks.py --fast` | ✅ PASS 8 / FAIL 0 / SKIP 5（26.0s） |
| 变化面 | 只改覆盖页 / About 渲染 + 两个页内六语字典；**刻意不加 I18N 键** → `assets/i18n.js`、首页内联字典、其它 13.7 万页都不变（预期只有 coverage/about 12 页 + build.py 变化） |

## 2. 改动（`site/build.py`，+119/−1）

- 新增 `MARKETS_JSON` / `_market_ui_meta(code)`：读 `data/markets.json` 的 `ui_languages` / `ui_language_gaps`；
  **容错**：文件缺失、字段缺失、类型不对 → 返回空 dict，该行不显示状态、构建不崩（用「去掉字段的临时 markets.json」验证 0 个状态且页面正常）。
- 新增 `_UI_LANG_STATUS`（六语模板：`✅ 母语已覆盖（{n} 种）` / `⚠️ 仅 {langs}；母语 {gaps} 未覆盖`）与
  `_market_ui_lang_html(code)`：每行输出六语块（`data-lang-block`），按界面语言只显示一块。
- 覆盖页市场格：代码后追加 `.covui` 状态块（每行一句，六语）。
- 新增 `_OFFICIAL_LINKS`（六语 HTML）+ `_official_links_html()`：MO「澳门药物监督局 · 澳门特区药品查询（ISAF）」
  → `https://www.isaf.gov.mo`；KR「MFDS 의약품안전나라（식품의약품안전처）」→ `https://nedrug.mfds.go.kr/`；
  两条都写明「只提供官方查询入口，本站不复制其数据」，KR 另写「需本人注册 data.go.kr，暂不入库」。
  覆盖页置于表格下方；About 置于来源段之后、许可折叠之前。
- **不加 I18N 键**是刻意选择：新增键会改 `assets/i18n.js` 与首页内联字典 → 全站页面变化、R2 增量变大；本需求只在两页显示，用页内六语块即可（与现有 `data-lang-block` 机制一致）。

## 3. 自检（`.tmp/check_v0150.py`，不写 dist）

```
覆盖页：15 行 .covui ✓；全覆盖市场「✅ 母语已覆盖（6 种）」✓；JP/CZ/LV ⚠️ 且列 ja/cs/lv ✓；US 无 ⚠️ ✓
官方入口：MO/KR 链接 ✓；六语块 6 个 ✓；「不复制数据」中英措辞 ✓
About：两个入口 + 署名 + 六语块 ✓；es/zh/zh-hant/fr/ko 五个副本各含两入口 ✓
容错：市场字段缺失 → 0 个状态、页面正常、不崩 ✓
未新增 I18N 键（i18n.js 不变）✓
结论：PASS
```

`deploy/i18n_check.py` → **FAIL 0**；`deploy/ci_checks.py --fast` → **13 项 PASS 8 / FAIL 0 / SKIP 5**；
`py_compile site/build.py` OK。

## 4. 紧凑版（Lead 选 B）：状态并进 summary，**不新增行**

第一版把状态做成独立一行（卡片 132→169px，coverage@390 items 3.5→2.5），按 Lead 要求改成紧凑版：

- **✅ 行**：在既有「查看原因」`<summary>` 末尾追加短词：`查看原因 · 界面语言 ✅`（六语短词：
  `UI languages ✅` / `Idiomas ✅` / `界面语言 ✅` / `介面語言 ✅` / `Langues ✅` / `언어 ✅`）。
- **⚠️ 行（JP/CZ/LV）**：summary 里显式写母语缺口：`查看原因 · 母语 ja 未覆盖`
  （en `Why · native ja not covered`、fr `Pourquoi · langue maternelle ja absente`、ko `이유 · 모국어 ja 미지원`…）。
- 状态文本用 `data-lang-block` 六语块并进 summary，**仍是 22px 行高、不加行**；只有「无原因」的行才退化为
  独立 `.covui` 行（当前数据 0 行，纯防御）。

**390×844 实测**（`deploy/first_screen_check.py --pages coverage`，改前 `.tmp/dist-cov-before` / 改后 `.tmp/dist-cov`）：

| 轮次 | items | chrome | AFCR | 溢出 | 卡片高 |
|---|---|---|---|---|---|
| 改前（V6 修复后） | **3.5** | 0.27 | 0.79 | 否 | 132px |
| 改后（LG3 紧凑版） | **3.5** ✅ | 0.27 | 0.79 | 否 | 132px |

- JSON：`.tmp/fs-cov-before-v0150.json` / `.tmp/fs-cov-after-v0150.json`；截图 `.tmp/fs-shots-v0150/`。
- 六语 coverage 副本各 15 条 summary 状态（`<span class="covui">` ×15）；About 六语入口不变。
- 仍未新增 I18N 键（`i18n.js` / 首页内联字典不变）→ 预期只有 coverage/about 12 页 + `site/build.py` 变化。

## 5. 一句话交接

改了什么：覆盖页 15 行按 `data/markets.json` 的 `ui_languages/ui_language_gaps` 显示六语界面语言状态（JP/CZ/LV ⚠️），覆盖页与 About 各加 MO ISAF / KR MFDS 官方入口（六语、署名、只链接不复制数据）。
怎么验的：临时渲染 6 语 coverage/about（`.tmp/v0150`）+ 缺字段容错、i18n_check FAIL 0、ci_checks --fast PASS、py_compile。
还剩什么：coverage@390 首屏因状态行 +37px 掉到 2.5，等你拍板接受或下一轮压缩；未跑全量构建/未发布。
