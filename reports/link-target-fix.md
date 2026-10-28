# v0.5.3 品牌/成分点击目标修复 + 品牌页/组合页 实现报告

> 任务：task-46。用户报告：**Excedrin Extra Strength 点品牌跳到 acetaminophen 页**。
> 改动文件：**仅 `site/build.py`**。未跑 git / 发布，未改 `site/dist`、`data/drugs.db` 或其他跟踪文件；
> **未改** `/* 搜索增强（task-28） */` 块与 `searchLayers*` 函数；UI P0 / i18n P1 / /warn 文案保留。
> 构建：`SITE_OUT=.tmp/dist-nav`，产物 `.tmp/dist-nav/`；验收脚本 `.tmp/dist-nav/_verify/`。

---

## 0. 结论

| 项 | 结果 |
|---|---|
| **品牌列点击** | → `name/<u>.html`（品牌页）；**没有品牌页就渲染成不可点文本 `<span class="brand-plain">`，绝不回退 drug 页**（旧 `u ? name : drug` 三处回退已删） |
| **成分列点击** | 复方（索引 `cu` 非空）→ `/combo/<成分集合slug>.html`；单成分 → `drug/<v>.html`（原有成分页） |
| **品牌页** | 共 **29,140** 个（原 17,870 + 新增 **11,270** 个有 ≥2 包装的 trade 品牌轻量页）；仍无页的 97,945 个名字（其中 trade 单包装 69,019）→ 不可点文本 |
| **组合页** | 新增 **9,339** 个（唯一成分集合数），覆盖 **37,514** 条复方索引条目；页面含成分链、同组合商品名/国家/规格/MAH、来源与许可；单页最多 200 条显式截断（最大集合 1,732 条） |
| **索引** | 每条复方加 `cu` 字段（`combo/<slug>.html`）；品牌页字段 `u` 覆盖率提升；`core.json`/分片同步编码 |
| **「展开全部品牌」** | 复用同一 `brandRowHTML`/`brandHTML` 规则，展开后的行同样不回退 drug 页 |
| **无 404** | 索引里每个 `u`/`cu` 都有文件；组合里每个成分都有 drug 页；抽样名页链接全部命中；DOM 5 查询 88 个结果链接全部存在 |
| **三语** | 新增 11 个 `combo.*` key × en/es/zh；I18N **191 keys ×3** 一致 |

## 1. 用户报告 bug 的根因

旧逻辑（`rowHTML` / `brandRowHTML` / 家庭卡片）：
```js
const link = e.u ? `${BASE}name/${e.u}` : `${BASE}drug/${e.v}.html`;
```
绝大多数 trade 品牌**没有** name 页（旧 `worth_page` 只为「碰撞/多包装」建页），于是品牌列退化成「第一个成分的 drug 页」——
Excedrin 组合名点品牌就落到 `drug/acetaminophen.html`。本次把「品牌」与「成分」两类点击目标彻底解耦：
品牌只认品牌页（无页 → 纯文本），成分按「单成分/复方」分别去 drug / combo 页。

## 2. 改动清单（`site/build.py` file:line）

| 内容 | 位置 |
|---|---|
| 组合页三语文案 11 键（标题/说明/成分/商品名/免责/空态/截断/来源许可/查看警示/无品牌页提示/组合标签） | `COMBO_I18N` L1035–1155 |
| 组合页/品牌页排版样式（`.brand-plain` 不可点文本、`.grp-name` 链接） | CSS L1440–1442 |
| `combo_slug()`：成分集合 → 稳定文件名（`key_file('+'.join(sorted(sids)))`，与索引共用） | L2805–2807 |
| 索引新增 `cu`；`worth_page` 增加「trade 且 n≥2」生成品牌页 | `load_index`：worth_page L2897–2900、`cu` L2914–2916 |
| `core.json` / 分片编码加入 `cu`（字典列） | `CORE_DICT_COLS` L3624、字段列表 L3673；`encode_shards` 直接序列化条目（自动带 `cu`） |
| 名页「同品牌其他市场」段：只对真实存在 name 页的成员做链接，否则 `<b>` 文本（防 404） | `page_keys` L3219、`_family_block(..., page_keys)` L3263、调用 L3257 |
| COMBO_I18N 合并进运行时字典 | `_merge_static_i18n` L937 |
| `build_combo_pages()`：按成分集合分组生成 9,339 页（成分链、商品名/国家/规格/MAH、来源与许可、/warn 入口） | L3290–3380（`COMBO_ROW_CAP=200` L3290、函数 L3293） |
| main 调用 + done 输出 `combo pages` | L4028、L4040 |
| APP_JS 链接规则函数（品牌→name 页或不可点；成分→cu/drug） | `brandHTML` L1566、`ingredientHTML` L1570 |
| 结果表成分/品牌列使用新规则（旧回退删除） | `rowHTML`、`brandRowHTML`、分组头 L1643、家庭卡片 L2231、同成分表 `cu` L2257 |

> `combo/` 与 `name/` 目录同时进 sitemap（walk `*.html`），URL 由构建器自动生成。

## 3. 验收证据

```powershell
$py  = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$node= 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$env:SITE_OUT='D:\同种药物商品名剂量对应网站\.tmp\dist-nav'
& $py -X utf8 site/build.py              # == done ==, exit 0
& $node --check .tmp\dist-nav\assets\app.js    # exit 0
& $node --check .tmp\dist-nav\assets\i18n.js   # exit 0
& $node --max-old-space-size=4096 .tmp\dist-nav\_verify\ui-links.test.mjs  # 6/6 PASS
& $py -X utf8 .tmp\dist-nav\_verify\static_check.py                        # 39/39 PASS
# 临时 http.server 8798 + http_check.mjs → 20/20 PASS
```

**构建结果**（exit 0）：
```
127,085 keys；core.json 16.5 MB（index.json 38.1 MB）；73 shards
name pages : 29,140    combo pages: 9,339
seo files  : 50,863 urls    total size: 279.2 MB（266 MiB）    文件数 50,953
```
`site/dist` 未动（app.js mtime 仍 2026/10/28 9:35，Lead 的 v0.5.2 构建）。

**DOM 行为测试 6/6**（Node vm + 真实索引）：
1. Excedrin Extra Strength：品牌 → `name/excedrin-extra-strength-pain-reliever.html`，成分 → `combo/acetaminophen+aspirin+caffeine.html`，品牌列无 `/drug/`；
2. aspirin / Lipitor / metoprolol / Gaviscon / 泰诺 五个查询：所有品牌单元格都不含 drug 链接（旧回退无回归）；
3. 阿莫西林克拉维酸钾片 → `combo/amoxicillin+clavulanate.html`；二甲双胍格列本脲片 → `combo/glibenclamide+metformin.html`；无品牌页名字为 `span.brand-plain`；
4. 单成分 Lipitor：成分 → `drug/atorvastatin.html`，品牌 → `name/lipitor.html`（未误用组合页）；
5. 「展开全部品牌」重绘行同样满足品牌列无 drug 回退；
6. 5 个查询结果共 88 个站内链接全部对应实际文件（**无 404**）。

**静态验收 39/39**：索引 127,085 条；`u` 29,140 全有 name 文件；`cu` 9,339 与 `combo/` 文件一一对应、无双 `.html` 后缀；组合内所有成分都有 drug 页；三个样例索引字段逐项断言；组合页含成分/品牌链接与三语 key；
app.js 旧回退字符串全部清除；I18N 191×3 且 combo 11 键齐全；sitemap 含 combo/name 页（50,863 URL）；产物 50,953 文件、无 0 字节、index ≥5 MB。
JSON 实测：最大组合页 1,732 条 → 页面按 200 条截断并显示「Showing the first 200 of 1732」；最长 slug 91 字符页存在。

**HTTP 抽查 20/20**：`/`、Excedrin 品牌页、三个组合页、`/warn.html`、`/es/`、`/zh/` 全部 200；组合页成分/品牌链接正确、i18n.js 单次、组合页无「品牌列 drug 链接」。

## 4. 风险 / 已知问题

1. **索引与站点体积增长**：`index.json` 34.8 → **38.1 MB**（+9.5%），`core.json` 15.3 → 16.5 MB；首搜多约 0.3–0.4 MB（gzip）。主要来自新增 `cu` 字段 + 11,270 个条目的 `u` 从空变文件名。可接受，但若后续再扩字段需评估首搜预算。
2. **构建/发布变慢**：文件数 30,260 → **50,953**（+20,693），total 162.5 → 279.2 MB。Pages 1 GB / 文件数无硬限制，但 `publish.ps1` 拷贝与 gh-pages 提交会明显变慢；发布时注意等构建 `== done ==`。
3. **仍有 97,945 个索引名字没有品牌页**（含 69,019 个单包装 trade 名字）：品牌列按设计渲染成**不可点文本**（无 404、不误导），若未来要「全品牌可点」需再扩页（成本 = 页数与构建时间）。
4. **品牌页阈值是启发式**：`trade 且 n≥2` 才建页（+11,270）。n=1 的冷门品牌仍不可点；该阈值可在 `load_index.worth_page` 一处调整。
5. **组合页最多显示 200 条**（最大组合 1,732 条），页面有截断提示；如需完整列表需分页/加载更多（复用 UI P0 的 loadmore 机制，本次未做）。
6. **组合页使用 slug 文件名**（含 `+` 等，已 URL 编码）：可读但较长；最长 91 字符，Windows 路径安全。
7. 未改数据语义：候选集/碰撞/国家视图逻辑未动；组合页与品牌页只是新的导航目标，检索排序不变。

## 5. 回滚方法

| 层次 | 操作 |
|---|---|
| 源码回滚 | `git checkout -- site/build.py` 后重新构建/发布（由 Lead 执行；本子智能体未跑 git） |
| 特性级回滚 | ① 删 `main()` 的 `n_combo = build_combo_pages(...)` + `warn.html` 不动；② 索引删 `cu` 字段并还原 `worth_page`（品牌页回 17,870）；③ APP_JS 恢复旧 `u?name:drug` 回退（不建议，会复现 bug） |
| 发布后回滚 | gh-pages revert 上一提交（新增 `combo/` 目录、`name/` 增量、索引体积变化；数据文件未变） |

## 6. 产物

- `site/build.py`：COMBO_I18N / combo_slug / build_combo_pages / 索引 `cu` + 品牌页阈值 / core·分片编码 / APP_JS 链接规则 / CSS。
- `.tmp/dist-nav/`：SITE_OUT 构建产物（50,953 文件，279.2 MB）。
- `.tmp/dist-nav/_verify/{ui-links.test.mjs, static_check.py, http_check.mjs, probe_nav.py}`：可复跑验收。
- `reports/link-target-fix.md`：本报告。
