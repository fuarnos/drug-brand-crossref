# v0.8.1 双语对照显示 + 翻译来源标注 实现报告

> 任务：task-99（`site/build.py` 独占；数据用 `data/translations.csv`、`data/ingredient_names_i18n.csv`、`data/label_translations.csv`，只读）。
> 未改 `data/drugs.db`、`data/markets.json`、`data/languages.json`、`tests/`、`site/dist`；构建：`SITE_OUT=.tmp/dist-bilingual`。

## 0. 结果

| 项 | 结果 |
|---|---|
| 成分双语 | 生成 `data/terms.json`（**181.6 KB**）：**536 个 zh 默认译名 / 640 个 es 默认译名**（1,065 个成分含至少一个译名）；仅 `display_default=1` 且非 AI（`machine_translated=0`）；每条带 `source/source_url/confidence/version` |
| 页面显示 | 成分页 h1、ATC/大类页成分列表、搜索结果成分名：显示**当前语言译名 + 来源徽章 + 版本 v2026-10-28.1**；无译名成分只显示原名（英文），不空白/不占位 |
| 原文对照开关 | 页头新增「显示原文对照」复选（四语文案），**非英文界面默认开**；开启时显示「译名 (原名)」，关闭只显示译名；localStorage `dsh.showOrig` 持久化（headless 验证刷新保持） |
| 品牌永不翻译 | 品牌列/矩阵单元格保持市场注册原名，添加 `data-brand` 标记与「该市场注册名，不是翻译」title（headless 验证 105 个品牌行均有标注）；不生成任何品牌译名 |
| 剂型/状态/释放/单位 | 沿用现有 `_label_html`/`_label_unit_html` + I18N 四语标签体系（form/status/release/unit），长尾原样回退；本轮未改变该行为，未回归 |
| 四语 | I18N **374 keys ×4 一致**；`zh-Hant` 无 ingredient 默认译名（数据 0 条）→ 回退原名；pt 数据保留（ingredient 0 条/标签 69 行），UI 仍 4 语（pt-PT UI 由 task-95 另做） |
| 构建 | exit 0；**62,880 文件 / 463.7 MB**（较 SG 455.7 MB +8.0 MB；terms 181.6 KB + `data-brand`/双语标记页面开销）；sitemap **62,720** 不变；drug 12,447 / name 31,139 / combo 10,942 / maker 6,997 |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| `BILINGUAL_I18N` 四语（开关/品牌非翻译/来源 official、regulator、pharmacopoeia、manual） | L~...（`BILINGUAL_I18N` 常量）；合并进 I18N 的 en/es/zh + zh-Hant extras |
| `BILINGUAL_JS`（独立脚本）：terms.json 加载、`[data-sub-ingredient]` 渲染译名+徽章+版本+原文、`[data-brand]` title、开关注入/localStorage、MutationObserver 处理动态搜索结果 | L4124–4217 |
| `build_terms_json()`：读 CSV → `data/terms.json`（display_default=1 且非 AI；含来源/版本）；`TERMS_SUB_IDS` 供页面标记 | L4226–4275 |
| 页面统一加载 `assets/bilingual.js`（defer）+ `window.DSH_PREFIX` | page() head L4325–4326 |
| 成分页 h1：有默认译名的成分加 `data-sub-ingredient/data-sub-orig`，其余直接原文 | `build_drug_pages` |
| ATC/大类页成分列表：有译名标记双语，其余原名；去掉重复 meta | `_atc_members_html` |
| 矩阵品牌单元格 `data-brand="1"`（永不翻译） | `build_drug_pages` 矩阵渲染 |
| APP_JS：`ingredientHTML` 加成分双语标记、`brandHTML` 加品牌标记 | APP_JS |
| CSS：`.bil-toggle/.tr-badge/.tr-ver/.tr-orig` | 样式表 |
| main：构建期写 `assets/bilingual.js`、生成 terms.json 并打印计数 | main |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-bilingual'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-bilingual\assets\bilingual.js               # 0
& $node --check .tmp\dist-bilingual\assets\app.js                     # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-bilingual'   # 23/23 PASS
# 临时 http.server 8810 + headless.mjs（Chrome CDP）→ ALL CHECKS PASSED
```

- **静态 23/23**：terms.json 计数 zh 536 / es 640、版本、amlodipine zh/es 译名、无 AI 内容；bilingual.js 读 terms/localStorage/徽章/原文/品牌 title；head 加载脚本 + DSH_PREFIX；drug h1 标记与原名；矩阵 data-brand；ATC 成分标记；app.js 标记；I18N 374×4、双语键四语；CSS；h1 非空；无 `@@`；抽样链接 0 404；无 0 字节。
- **Headless（Chrome CDP）**：zh 成分页 h1 =「苯磺酸氨氯地平」+ 来源徽章「监管机构」+ `v2026-10-28.1` + 原文（默认开）；关闭开关 → 原文消失、localStorage=0、刷新后保持；en 只显示原名、开关默认关闭；es h1 =「Almlodipino」+ regulador + 原文；zh-Hant 无译名 → 原名不空白；ATC C08 页 8 个双语成分、含氨氯地平译名+徽章；搜索结果 12 个成分标记（含译名+徽章）、105 个品牌行均有「非翻译」title。
- **构建期日志**：`bilingual : 536 zh / 640 es display-default ingredient translations`。

## 3. 风险 / 已知事项

1. **zh-Hant 无 ingredient 默认译名**（数据 0 条）→ 回退原文（英文）；如需要繁中译名，由 data 侧补 `name_zh_hant` + `display_default_zh_hant=1` 后重建生效。
2. **pt 数据保留但未显示**：ingredient pt 0 条、label_translations 有 pt 列；站点 UI 仍 4 语，task-95 启用 pt-PT UI 后自动可用。
3. **ATC/大类页无译名成分改显示英文原名**（原先显示简体中文 inn_zh）：这是按「无默认译名只显示原名」规则的行为变化；有默认译名的成分正常显示译名。
4. **原文开关在英文界面可见且默认关闭**（英文原文即当前语言，切换无可视变化）；四语 key 已备。
5. **页面体积 +8.0 MB**：`data-brand`/双语标记属性分布在 1.2 万 drug 页矩阵与 ATC 页；如需缩减可改为客户端注入标记（当前实现简单可靠）。
6. **来源/版本**直接取 CSV（source/source_url/confidence/version）；`machine_translated=1` 一律不显示（当前 ingredient 表 0 条、translations 15 条不影响成分显示）。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | 删 BILINGUAL_I18N/BILINGUAL_JS/build_terms_json 与 main 调用、page head 脚本、data-sub/data-brand 标记、app.js 标记、CSS；`data/terms.json` 不再生成 |
| 发布后 | gh-pages revert 上一提交；terms.json/bilingual.js 为新增静态文件，回滚后可有残留但不被引用（下次发布覆盖） |

## 5. 产物

- `site/build.py`：双语对照（译名+来源+版本+原文开关）、品牌非翻译标注、terms.json 生成。
- `.tmp/dist-bilingual/`：构建产物（62,880 文件 / 463.7 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`、`smoke.py`、`probe*.py`（TEMP `bilingual-verify-20261028/`）。
- `reports/bilingual-impl.md`：本报告。
