# task-6：矩阵按需 3 列 + 筛选加列 + 横滑 + 单包装名字页（代码完成，构建待 DB 窗口）

> 2026-10-29 ｜ `site/build.py` ｜ 未写 DB、未改数据、未构建。
> **体积降级（Lead 批准口径）**：全量单包装名字页预计 dist ~900MB、发布可能 1–3h，**本版不做**；默认只生成 CN/TW/ES/MX 子集（44,238 页）。`SINGLE_NAME_ALL=1` 仅作为下一版开关保留，本版不启用。
> **全量待做（下一版）**：102,192 个单包装 trade 名（其中 1,055 个无 component 行）需先压模板体积或分批发布，再启用全量。

## 0. 结论

- 矩阵默认 **3 列**：产品数最多的市场 + 当前界面语言市场 + 第二多市场；其余通过筛选器「国家」多选加入；`mk=CN,TW` 可分享，`localStorage` 记忆；加「全选/清空」。
- `.matwrap` 横滑 + 首列 sticky；移动端改为每规格一卡、市场纵向排列（无横滚）。
- 单元格最多 3 名 + 原生 `<details>`「+N」展开（无 JS 也能点开）。
- **单包装名字页（本版降级）**：默认生成 **44,238** 页（CN/TW/ES/MX 子集）；全量 trade 单包装 102,192 **本版不做**，留下一版（先压模板/分批）；总名字页 **75,383**（原 31,134，新增 44,249）。
- 单包装页：产品级表格（市场/规格/剂型/状态/厂家/来源）+ 成分页链接；底部四语「该名称目前仅收录 1 个产品记录」；`noindex,follow`、不进 sitemap。
- 预估 dist：现有 450.6 MiB + 名字页 ~172MB + 厂家页增量 ~68MB ≈ **690 MiB**（<800MB 守卫）；构建预计 5–8 分钟（<60min）。

## 1. 矩阵列行为

| 项 | 实现 |
|---|---|
| 默认列 | `defaultCols()`：按每列 `.m-brand` 计数降序取 top1 + `LANG_MARKET`（en→US/es→ES/zh→CN/zh-Hant→TW）+ top2，去重截 3 |
| 筛选加列 | 国家多选默认只勾 3 个；勾选/取消即显隐 `th` + 对应 `td[data-country]`；全选/清空按钮 |
| URL | `?mk=CN,TW` 优先；兼容旧 `mcountry`；变更时写 `mk`，删除 `mcountry` |
| 记忆 | `localStorage.dsh.matrix.mk` |
| 横滑/sticky | `.matwrap{overflow-x:auto}`；`thead th:first-child, td.m-spec{position:sticky;left:0}` |
| 移动端 | ≤719px：table/tr/td 变 block 卡片；隐藏 thead；国家 cell 用 `data-country` 作前缀；`.matwrap` 取消横滚 |
| +N | 服务端保留全部名字，前 3 展示，其余放 `<details class="m-more"><summary>+N</summary>…` |
| 无 JS | 所有列 + 全部名字仍可读（details 原生展开） |

## 2. 单包装名字页

| 项 | 数值/实现 |
|---|---|
| 全量 trade 单包装 key（DB） | 102,192（其中 1,055 无 product_component 行，索引不可建页） |
| 默认生成子集 | 44,238（CN/TW/ES/MX；`SINGLE_NAME_PAGE_MARKETS`） |
| 名字页总数 | 75,383（原 31,134） |
| 模板 | 现有 name 页 + 产品级 `.res` 表（市场/规格/剂型/状态/厂家/来源）+ 底部单条文案 |
| noindex | `name/<u>.html` 加入 `NOINDEX_RELS`；`page(noindex=True)` 输出 `noindex,follow` |
| sitemap | `build_seo_files` 跳过 `NOINDEX_RELS` |
| 厂家链接 | 通过 `MAKERS` 映射；无页厂家纯文本 |

## 3. 复核

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m py_compile site/build.py
& $py .tmp/cat2/index_smoke.py            # entries 160,750 / 有页 75,383 / 单包装 44,238 / trade 131,665
& $py .tmp/cat2/task6_smoke.py            # 单包装名字页 noindex/note/table + 单产品厂家页
& $py .tmp/cat2/v09_code_check.py         # 四语 key + noindex meta
```

## 4. 缺口 / 风险

- **未全量生成 102,192 单包装页**：按 Lead「dist >800MB 先降级」口径取 CN/TW/ES/MX；若要全量：`$env:SINGLE_NAME_ALL='1'` 后构建（预估 dist ~870MiB，需确认上限）。
- 1,055 个单包装 trade key 在 DB 无 `product_component` 行，索引无法建页；另有约 423 个差异见 `index_smoke` 口径，未强行造页（避免空页）。
- 移动端「市场折叠」用纵向卡片实现，未做折叠开关；无 JS 仍可读。
- 最终 build 后需实测「西替利嗪默认 3 列、横滚、sticky、ES 不截断、MX 筛入、CN 列高、+N、ARALEVO/RIDEXIN 页、noindex/sitemap」。
