# v0.8.3 成分页矩阵：常用剂量优先 + 筛选器 + 空行隐藏 报告（task-119）

> 任务：task-119（`site/build.py` 独占，构建 `.tmp/dist-filter`）。未改 `data/*`、tests、`site/dist`。
> 用户截图：氯雷他定页按「未公开」/剂型排列且无筛选器。

## 0. 结果

| 项 | 结果 |
|---|---|
| 常用度排序 | 构建期统计每行 `freq = Σ_country len(bucket)`（该规格/剂型/释放组合的跨国家产品/品牌记录数）；排序 `(未公开置后, -freq, 剂型标准序, 数值降序, release)`；不再按规格数值简单降序 |
| 空行隐藏 | 所有国家 bucket 都为空的行不输出（防御性；正常数据每行至少 1 品牌） |
| 行属性 | `<tr data-form data-release data-spec data-freq>`（供客户端筛选/回归） |
| 筛选器 | 客户端工具栏：**国家多选**（默认 9 国全选，取消则隐藏该列）、**剂型**、**释放机制**下拉、**规格文本搜索**、**重置**、`{n}/{total} 行` 计数、**URL 参数**（`mform/mrel/mspec/mcountry`，`history.replaceState` + 深链恢复）、**移动端 <768 折叠抽屉**（按钮展开，`aria-expanded`） |
| 四语 | 筛选 12 个新 key ×4（en/es/zh/zh-Hant），I18N **387 keys ×4 一致** |
| 构建 | exit 0；62,880 文件 / **472.4 MB**；sitemap 62,720 不变 |

## 1. 现有库选型（报告要求）
| 库 | 许可/体积 | 结论 |
|---|---|---|
[List.js](https://github.com/jkeyes/list#1) | MIT / ~3–9 KB gzip，无依赖 | 不选：仅搜索/排序，不支持隐藏国家列、URL 状态、移动抽屉，仍需自写 60%+ |
tablesort / table-sort-js（[license](https://sources.debian.org/src/sortable-tablesort.js/3.1.0%2Bds-2/LICENSE/)） | MIT / ~1–2 KB | 不需要：本任务排序在构建期完成 |
[Grid.js](https://gridjs.io/docs/) | MIT / ~12 KB+ gzip | 不选：需重构整张矩阵，DOM/样式冲突 |
[Tom Select](https://tom-select.js.org/) | Apache-2.0 / ~16 KB gzip | 不选：富下拉超出需求（原生 select 足够） |
**vanilla 内联** | 项目自有 / ~4 KB | **选它**：列隐藏 + 行过滤 + 计数 + URL + 抽屉一次实现，无网络/无依赖/CSP 友好 |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-filter'; & $py -X utf8 site/build.py   # exit 0, 472.4 MB
& $node --check .tmp\dist-filter\assets\bilingual.js                # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-filter' '<repo>'  # 10/10 PASS
# 临时 http.server 8818 + headless.mjs → ALL CHECKS PASSED
```

- **静态 10/10**：矩阵行带 data 属性；抽样 60 页「未公开」行排在最后、常用度递减、无全空行；`initMatrixFilters`/列表隐藏/计数/URL/重置实现；CSS 抽屉折叠；I18N 387×4 且筛选 7 key 齐全；无 0 字节。
- **Headless（Chrome CDP）**：acetaminophen zh：工具栏、计数 120/120、未公开最后、常用度降序；剂型筛选 8/120、规格搜索 1/120、URL 写入、重置恢复、国家列隐藏；`?mform=tablet&mspec=500` 深链生效（5/120）；zh/zh-Hant/es/en 筛选标题本地化；移动端 390 面板默认折叠、按钮展开、无横向溢出、可点区 ≥36px。
- **排序语义**：常用度=跨国家产品/品牌记录数，仅展示排序，不代表疗效/推荐。

## 3. 风险 / 已知事项

1. 筛选在客户端；无 JS 时矩阵完整显示（无筛选/列隐藏），不空白。
2. URL 参数仅 `mform/mrel/mspec/mcountry`，不覆盖其他参数；非法值忽略。
3. 列隐藏与 i18n MORDER 列重排叠加时按 `data-country` 同时隐藏 th/td，回归 task-136 对齐。
4. 常用度统计为构建期快照；数据更新后需重建。

## 4. 回滚

`git checkout -- site/build.py` 后重建；或仅回退排序/行属性/筛选 JS/CSS/i18n keys。

## 5. 产物

- `.tmp/dist-filter/`（62,880 文件 / 472.4 MB）。
- 验收脚本：TEMP `filter-verify-20261028/`。
- `reports/matrix-sort-filter.md`：本报告。
