# v0.5.4 厂家页实现报告

> 任务：task-50（`site/build.py` 独占）。输入：`data/maker_candidates.csv`、`data/maker_blacklist.json`、`reports/maker-pages-data.md`。
> 改动文件：**仅 `site/build.py`**。未跑 git/发布、未改 `data/drugs.db`；`site/dist` 由 Lead 的发布构建占用（本任务从未写入）。
> 构建：`SITE_OUT=.tmp/dist-maker`；验收脚本 `.tmp/dist-maker/_verify/`。

## 0. 结果

| 指标 | 数值 |
|---|---|
| 厂家页 | **6,997** 个（`/maker/<slug>.html`），阈值 **≥5 产品**（`MAKER_MIN_PRODUCTS=5`） |
| 其他页 | drug 12,377 · name 29,140 · combo 9,339 · 静态页若干；sitemap **57,860 URL** |
| 产物 | **57,958 文件 / 390.1 MB**（守卫：<70k 文件、<400 MB，均通过但接近体积上限） |
| 索引 | `index.json 50.6 MB / core 25.1 MB`；新增 `mu`（主厂家页 slug）+ `ml`（可展开厂家 [name,slug]） |
| 结果行 | 第一厂家可点（mu）；`+N` 展开列表所有带页厂家可点；无页厂家纯文本 / 「另有 K 家暂无页面」；无 404 |
| 三语 | 新增 `maker.*` 12 键 × en/es/zh；I18N 203×3；表头/列名走 `data-i18n`/`data-i18n-label` |

## 1. 阈值选择与体积守卫（按要求记录）

1. `reports/maker-pages-data.md` 建议首版 **≥2 产品（10,975 页）**；`etl` 的 `has_page` 也按 ≥2。
2. 按 v0.5.3 基线（50,953 文件 / 279.2 MB）预估 ≥2 会超 400 MB，因此直接采用 **≥5（6,997 页）**。
3. 第一次实测（≥5，每页 cap 300 产品 + **每行**来源链接）：**452.9 MB > 400 MB 守卫** → 收紧：
   - 每页产品行上限 300 → **60**（按国家均摊，超出显示截断提示）；
   - 来源链接从每行改为 **每国家一条**（行内只留 品牌/成分/剂型 三列）；
   - 移动端列名改为 `data-i18n-label`（JS 注入 `data-label`，省每行 2 个静态属性）。
4. 最终 **390.1 MB**（<400）落盘。若后续再加字段，需重新评估该守卫。
5. 修正 **厂家名规范化**：`norm_maker()` 与 `etl/build_maker_candidates.py::norm_key` 完全对齐
   （NFKC→空白折叠→casefold→`[.,;:'"()[]{}&/\\|]`→空格→破折号→`-`）；此前用宽泛 `\w` 规则导致
   `A-S ...` 类 199 个厂家匹配不到 DB，页面数 6,798 → 修正后 **6,997**。

## 2. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| 厂家清单加载（CSV→`{norm_key:{name,slug,n,has}}`，占位厂家 `is_placeholder=1` 排除） | `MAKER_MIN_PRODUCTS`/`MAKERS`/`norm_maker`/`load_makers`，`WARN_I18N` 之后 |
| 厂家页三语文案 12 键 | `MAKER_I18N` |
| 索引字段 `mu`（主厂家页）/`ml`（其它可点厂家 [name,slug]） | `load_index` 条目构造（`ordered_mah` 起） |
| core/分片编码同步 `mu`（字典列）`ml`（数组列） | `CORE_DICT_COLS`/`CORE_ARRAY_COLS`/`encode_core` 字段列表 |
| `/maker/` 页面生成（国家分组、品牌→品牌页/不可点、成分→drug/combo、来源/许可、截断提示、i18n 表头） | `build_maker_pages()` + main 调用（`n_maker`） |
| 结果行厂家列：`makerHTML()`（首厂家链接 + `+N` 展开列表） | APP_JS `makerHTML`、`rowHTML`/`brandRowHTML`、同成分行字段 |
| 「+N」展开/收起事件 | `out` 点击委托 `[data-mah]`（hidden + aria-expanded） |
| 厂家页/展开列表样式 | CSS `.maker-link`/`.mah-toggle`/`.mah-list` |
| 移动端列名随语言 | i18n.js apply 新增 `[data-i18n-label]` → `data-label` |
| 组合页 `combo.capped` 占位符残留修复（v0.5.3 遗留） | `{cap}/{total}` 替换（§3 风险 5） |

## 3. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-maker'; & $py -X utf8 site/build.py   # exit 0
& $node --check .tmp\dist-maker\assets\app.js                      # exit 0
& $node --check .tmp\dist-maker\assets\i18n.js                     # exit 0
& $node --max-old-space-size=4096 .tmp\dist-maker\_verify\maker.test.mjs  # 5/5 PASS
& $py -X utf8 .tmp\dist-maker\_verify\static_check.py                     # 44/45 PASS
```

- **DOM 5/5**：① Excedrin 行 Haleon / Lil Drug Store 均链到各自厂家页且 `+N` 展开带链接；
  ② `+N` 展开/收起（hidden + aria-expanded）；③ 5 个查询共 **1,621 个厂家链接全部命中文档**；
  ④ 回归：品牌→品牌页、复方成分→组合页、品牌列无 drug 回退；⑤「展开全部品牌」行同规则。
- **静态 44/45**：6,997 厂家页 = CSV ≥5 且非占位；`Special Order` 不建页；n<5 抽样 200 不建页；
  索引 `mu` 107,712 条、`ml` 19,046 条，全部 slug 有文件（**无 404**）；`ml` 不含无页厂家；
  Excedrin 行可点 Haleon + Lil；Haleon 页国家分组/品牌链/成分链/来源/i18n/截断提示齐全；
  中文 hash 厂家页存在；抽样 120 厂家页站内链接全部存在；app.js 使用 mu/ml、旧 `span.more` 已删；
  I18N 203×3、maker 12 键齐全、无 `@@` 残留；sitemap 含 6,997 条 `/maker/`；dist 57,958 文件/390.1 MB。
  唯一失败项是自己写的「site/dist 未被修改」mtime 启发式：**Lead 正在并发构建/发布 v0.5.4 到 site/dist**，
  该目录 mtime 因此晚于本任务产物；本任务从未写入 site/dist（只写 `.tmp/dist-maker/`）。
- **样例**：`maker/haleon-us-holdings-llc.html`（382 产品）、`maker/lil-drug-store-products-inc.html`（244）、
  `maker/hahnemann-laboratories-inc.html`（4,851 → 截断提示）、中文厂家 hash slug 页；Excedrin 数据：
  `m=Haleon US Holdings LLC, mu=haleon-us-holdings-llc, ml` 含 Lil/Navajo 等可点厂家。

## 4. 风险

1. **dist 390.1 MB 接近 400 MB 守卫**：再加页面/字段前必须复测；发布拷贝与 gh-pages 会明显变慢。
2. **索引体积**：38.1 → **50.6 MB**（+12.5 MB，raw；`mu`≈3.8MB + `ml`≈6.5MB + 其它），
   core 16.5→25.1 MB、分片 50.6 MB；首搜 gzip 预计 +1 MB 左右，需在 v0.5.5 后观察。
3. **未建页厂家**：15,213 个规范厂家只有 6,997 个建页；其余（含单产品/2–4 产品）在结果行是纯文本，
   `+N` 展开只列有页厂家，并显示「另有 K 家暂无页面」；如需全覆盖需再扩页（体积不允许）。
4. **每页产品行上限 60**（按国家均摊）：大厂家页有截断提示；未做分页/加载更多。
5. **修复了 v0.5.3 遗留的 `combo.capped` `@@COMBO_CAP@@` 残留**（I18N 现在无 @@ 占位符）。
6. 厂家页来源链接为**每国家一条**（该国家第一个产品的 source_url），非逐产品；许可说明指向 About。
7. 中文厂家 slug 为 `maker-<sha1前10>` 短哈希，不可读（P2 可做拼音 slug）。

## 5. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | 删 `n_maker = build_maker_pages(...)` + `MAKERS=load_makers()`；索引删 `mu/ml`（core/分片字段同步）并恢复 APP_JS 旧 `span.more`（不建议，会回到「+N 不可点」） |
| 发布后 | gh-pages revert 上一提交（新增 `maker/`、索引体积变化；数据文件未变） |

## 6. 产物

- `site/build.py`：`load_makers`/`norm_maker`/`MAKER_I18N`/`build_maker_pages`/索引 `mu`·`ml`/APP_JS `makerHTML`/CSS/`data-i18n-label`。
- `.tmp/dist-maker/`：构建产物 57,958 文件、390.1 MB（`maker/` 6,997 页）。
- `.tmp/dist-maker/_verify/{maker.test.mjs, static_check.py, http_check.mjs, probe_*.py}`。
- `reports/maker-pages.md`：本报告。
