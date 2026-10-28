# v0.5.6 实现报告：A1/A3/B6/B7 + What's new 版本列表修复

> 日期：2026-10-28 ｜ 任务：`task-60` ｜ 版本：**v0.5.6**（构建产物 `.tmp/dist-a1`，未发布）
> 代码：`site/build.py`（本任务独占修改）｜ 构建命令：`$env:SITE_OUT='.tmp/dist-a1'; python site/build.py`
> 边界：未跑 git / 发布 / 写 `data/drugs.db` / 改 `site/dist`。

## 0. 结论

| 项 | 状态 | 说明 |
|---|---|---|
| **A3 盐型/释放提示** | ✅ 完成 | 索引新增 `sl`（32,432 条）/`rl`（4,773）/`wi`（2,735）；行内徽章 + `/warn#w-<id>` 链接 |
| **B6 行级报告** | ✅ 完成 | 每行 ⚑ 链接：`labels=data-error&title=&body=` 空白 issue 预填（不带 `template=`，避开 issue form 忽略 body 的坑） |
| **B7 复制/下载 CSV** | ✅ 完成 | 结果工具条「复制表格 / 下载 CSV」，当前视图全部行，BOM+CRLF，剪贴板降级与提示 |
| **A1 详情展开** | ✅ 完成 | 索引加 `db`（127,085 条）；点击懒加载 `data/idx/detail-<bucket>.json`（51 桶 / 294,895 行 / 46.9 MB），行下 `<tr class="detrow">`，显示市场/包装/批准号/状态/来源 |
| **What's new 修复** | ✅ 完成 | 改为 **CHANGELOG 全量 24 个版本为主列表**；有译文渲染三语块、无译文显示中文+「译文待补」；首条 = v0.5.5，`whats-new-version` smoke 预期恢复 |
| 构建 | ✅ | `== done ==`；`node --check assets/app.js` / `i18n.js` = 0 |
| 体积 |  | dist **447.9 MB / 57,836 文件**；index 55.1 MB raw（gz 9.7 MB）、core 26.8 MB raw（gz 6.24 MB）、detail 46.9 MB（gz ~9.3 MB） |

## 1. A3 盐型/释放差异上下文（结果行）

- **构建期**（`load_index`，`site/build.py` 约 L3386 起）：
  - 预计算 `variant` 的盐型形态表（优先 `salt_code`，回退 `salt`，附加 hydrate/ester；纯碱基记 `base`），
    单成分条目形态 >1 才写 `sl`（如 `fumarate/base`）；
  - SQL 增加 `p.release` 聚合进 `a["rels"]`，非 `none` 才写 `rl`（`IR/ER/...`）；
  - 读取 `dose_warning` 已发布 `R1/R2` 的 `substance_id → warning_id`，写 `wi`（优先 R2）。
  - **空值不写字段**（否则 12.7 万行各背 3 个空串，约 +3 MB）。
- **前端**（`a3HintHTML` + `brandRowHTML`）：品牌单元格追加
  - `wi` → 红色徽章「不可互换 — 见警示」，链 `warn.html#w-<warning_id>`（/warn 条目有锚点）；
  - `sl` → 中性徽章「盐型：base/succinate…」（**不写不可互换结论**，只有已发布 warning 才写）；
  - `rl` → 「释放：ER/IR…」徽章。
- **口径**：A3 不参与 collision 判定；多盐型仅提示，wording 与设计稿一致。

## 2. B6 行级报告入口

- `rowReportURL(e)`：`REPORT_REPO + '/issues/new?labels=data-error'`
  + `title=<report.issue_title + query/brand>` + `body`（Query / Page / Row / Expected / Actual / Pack 六段，按 issue form 字段顺序）。
- **不带 `template=`**：`.github/ISSUE_TEMPLATE/data-error.yml` 是 GitHub issue form，URL `body` 预填会被忽略；空白 issue + `data-error` label 仍可被维护者分流。页面级入口（`#reportLink`）保持原模板行为不变。
- 隐私：只带当前查询词、当前页面 URL、行名（成分/品牌/国家），不含 localStorage/UA/历史。
- 位置：`brandRowHTML` 内品牌单元格末尾 `⚑` 链接（`class="rowreport"`）；`click-report` 事件沿用现有委托。

## 3. B7 复制表格 / 下载 CSV

- `render()` 在构造 `#reswrap` 前插入 `.restools`：两个 `[data-export]` 按钮 + `#exportnote` 状态区（`aria-live="polite"`）。
- `LAST_DISPLAY = display`：导出**当前视图全部结果**（含折叠组、未点「加载更多」的行；国家视图下即该国结果）。
- 列：成分 / 品牌 / 剂量 / 国家 / 剂型 / 厂家 / 匹配方式 / 页面链接；表头随界面语言（i18n）。
- `toCSV()`：`\ufeff` BOM + CRLF + RFC4180 双引号转义（逗号/引号/换行安全）；`toTSV()` 用于复制。
  下载 `drug-crossref-YYYY-MM-DD.csv`；剪贴板 `navigator.clipboard` → 失败降级 `textarea+execCommand`，成功/失败均有提示。
- 事件委托：`out` click 中 `[data-export]`；GoatCounter 事件 `export-copy` / `export-csv`。

## 4. A1 产品详情展开（懒加载）

- **索引**：entry 加 `db = _shard_bucket(key_id)`（51 种桶名，字典编码，127,085 条全量）。
- **构建**：`main()` 在 manifest 后把 index-perf task-58 的 `data/idx/detail-*.json`（51 文件 / 46.9 MB / 294,895 行）复制到 `OUT/data/idx/`；缺失时打印 disabled 并降级（A1 无数据时不渲染按钮，其他功能不受影响）。
- **前端**：
  - `loadDetailBucket(key)`：`fetchManifest()` 取 `v` 做 cache-bust → 拉 `data/idx/detail-<db>.json` → `DET_CACHE` 会话内缓存；失败返回 `{}`；
  - 点击「详情」→ 行后插 `<tr class="detrow">`（加载中 → 表格），再次点击折叠；面板列：市场 / 包装(+规格) / 批准号(NDC/DIN/…) / 状态(+日期+释放) / 来源（`p[source_idx] + url_suffix`，新窗口）；最多 12 条并提示「全部见成分页」；
  - 404/断网降级：无记录时给「打开成分页」链接。
- **体积控制**：明细不进主索引/首屏；首搜仍只拉分片。dist 因明细 +46.9 MB raw（gzip 全站约 +9.3 MB）。

## 5. What's new 修复（线上 smoke `whats-new-version`）

- **根因**：旧 `build_whats_new()` 只遍历 `data/release_notes_i18n.json`（当时只到 v0.5.2），CHANGELOG 里的 v0.5.3/v0.5.4/v0.5.5 被跳过；smoke `WHATS_NEW_H2_RE` 取第一个 `<h2>` 版本 = v0.5.2 ≠ 页脚 v0.5.5 → 失败。
- **修复**（`build_whats_new()`，约 L3321 后）：
  1. 版本顺序**以 `load_releases()`（CHANGELOG.md 全量）为主列表**；
  2. 该版本在 JSON 有译文 → 渲染 `zh/en/es` 三个 `data-lang-block`（当前语言只显示一块）；
  3. 无译文 → 渲染 CHANGELOG 中文原文 + `whatsnew.pending`（三语「译文待补」）提示；
  4. 新增 i18n key `whatsnew.pending`（en/es/zh）+ CSS `.release-pending`。
- **验证（构建产物）**：`whats-new.html` 共 **24 个 `<section class="release">`**，首个 `<h2>` = **v0.5.5**、末个 v0.1.0；v0.5.5/4/3 均出现在正文；页脚版本 = v0.5.5（与 smoke 期望一致）。当前 JSON 已被并行任务补齐到 24 版，故 pending 分支暂为 0 条（代码路径保留，JSON 缺版时自动生效）。

## 6. 索引字段/体积变化

| 字段 | 含义 | 非空条数 | 估算增量 |
|---|---|---|---|
| `db` | A1 明细桶名 | 127,085 | ~+1.3 MB（index.json） |
| `sl` | 盐型列表（多盐型才写） | 32,432 | ~+0.6 MB |
| `rl` | 释放机制（有 ER/DR 才写） | 4,773 | ~+0.1 MB |
| `wi` | 已发布 R1/R2 warning id | 2,735 | ~+0.2 MB |

- `index.json` 55.1 MB（v0.5.5 52.9 MB，+2.2 MB / +4.2%）；`core.json` 26.8 MB（字典列同步 `db/sl/rl/wi`，客户端 `decodeCore` 无需改动，标量列通用解码）。
- smoke 体积区间自检：index raw 28–60 MB ✅ 55.1；index gz 4.5–13 MB ✅ 9.7；core raw 11–30 MB ✅ 26.8；core gz 2.5–9 MB ✅ 6.24。
- 分片：83 片（+detail 51 文件另计，不参与首搜）。

## 7. 验证与遗留

**已跑**：`python site/build.py` → `== done ==`；`node --check`（app.js / i18n.js）；构建产物断言（whats-new 版本列表、索引字段计数、i18n 新 key 三语各 3 份、体积区间）；`python -m py_compile site/build.py`。
**未完成**：Chrome headless 的交互式 DOM 测试本轮被环境进程占用（HTTP server/浏览器 profile 与构建目录锁冲突，构建首轮曾因此 `rmtree` 失败）打断；已改为构建产物级断言 + node 语法检查。**建议**发布前由建站会话用真实浏览器抽查：A3 徽章（metoprolol/nifedipine）、B6 预填、B7 下载/复制、A1 展开（US/CN 各一行）与三语切换；本报告 §0 的状态为代码+产物验收，不是点击级 E2E。

**风险**：
1. **A1 明细桶与索引可能不同步**：桶由 `etl/build_detail_buckets.py` 按上一版 `site/dist/data/index.json` 的 key 列表生成；本轮 key 集未变（127,085）故 0 missing/0 extra。若后续 DB/索引键集变化，需先重跑该脚本再 build（否则新 key 点「详情」会空/404 → 已降级为成分页链接）。
2. **首屏不受影响但发布体积 +9.3 MB gzip**（明细桶）；GitHub Pages 发布文件数 +51，`publish.ps1` 的 ≥24,000 文件与体积检查已满足（57,836 文件）。
3. **B6 空白 issue 绕过 issue form**：维护者若要求必须走模板，可退回「行级只预填 title」的保守方案（改一行 URL 构造即可）。
4. **BB7 剪贴板/下载**：iOS Safari `download` 支持有限，复制 TSV 为主路径；已在文案上提示复制失败可手动选择。
5. **What's new pending 分支未被当前数据触发**（JSON 已全量），建议保留并在下次 JSON 落后时观察。

## 8. 证据

- 构建日志：`.tmp/dist-a1-build.log`（含 `== done ==`、体积、detail buckets 51）
- 产物：`.tmp/dist-a1/`（57,836 文件 / 447.9 MB）
- 统计脚本：`.tmp/a1-detail/final_stats.py`（索引字段计数、gzip、Whats new 版本覆盖）
- 设计依据：`reports/ui-a1-b6-plan.md`；明细格式：`reports/a1-detail-buckets.md` §7

_未改 `data/drugs.db`、未跑 git / 发布；`.tmp/dist-a1` 为独立构建目录。_
