# /warn 页 + 成分页 dose_warning 接线实现报告

> 任务：task-30（`site/build.py` 独占；DB 迁移/入数由 Lead 完成）。数据口径：**published 40 / draft 1**
> （AI 核验后 apply；唯一 draft 是 `tainuo-vs-tainuolin`，NMPA TLS 不可达保留草稿）。
> 改动文件：**仅 `site/build.py`**。未跑 git / 发布，未改 `site/dist`、`data/drugs.db` 或其他跟踪文件；
> **未改** `/* 搜索增强（task-28） */` 块与 `searchLayers*` 函数；UI P0 / i18n P1 既有文案保留。
> 构建：`SITE_OUT=.tmp/dist-warn`，产物 `.tmp/dist-warn/`；验收脚本 `.tmp/dist-warn/_verify/`。

---

## 0. 结论

| 项 | 结果 |
|---|---|
| **/warn 页 URL** | `https://fuarnos.github.io/drug-brand-crossref/warn.html`（构建产物 `warn.html`；sitemap 已收录，sitemap URL 30,245） |
| **入口** | 全站共享导航新增 **Warnings / 警示 / Alertas**（`data-i18n="nav.warn"`，所有 `page()` 页面都有；深链接可用 `warn.html#w-<warning_id>`） |
| **展示条数** | **40 条 published**（只查 `status='published'`；draft/retracted 不展示）；按 severity 分组：**high 24 条、medium 16 条**（info 目前 0 条） |
| **成分页接线** | published 中 **35 条与成分关联**，覆盖 **34 个成分**；**34/34 个成分页顶部都挂上了摘要**（每条最多 3 条警示 + 链 `/warn`）；另 5 条是品牌级警示（Tylenol/Benadryl/Gaviscon 等），不属于单个成分，只在 /warn 展示 |
| **三语** | 页面 UI 文案三语（I18N **160 → 179 keys × en/es/zh**，0 缺失）；警示正文用 `data-lang-block` 按语言切换（zh/en 数据齐全；**es 数据字段当前全为 NULL → 回退英文并标 `(EN)`**，属数据层缺口） |
| **不做用药建议** | 页面顶部 `warn.no_advice` 三语明示「不是医疗建议」；正文只做同名不同药/不可互换警示；每行带监管来源链接 |
| **来源/许可** | 每条警示显示 `source_url` 域名链接（DailyMed/FDA、MHRA/EMC、AEMPS 等）；页脚 `warn.source_note` 说明只发事实摘录、不转载全文、指向 About 许可清单 |

## 1. 改动清单（`site/build.py` file:line）

| 内容 | 位置 |
|---|---|
| `/warn` 三语文案（19 键：标题/导语/计数/免责/严重度分组与徽标/来源/相关成分/市场/核验/成分页摘要/查看全部/空态/来源说明） | `WARN_I18N` L943–1030 |
| 新 i18n 键合并进 I18N（与 ABOUT/PAGE 字典同一机制；i18n.js 随后重写） | `_merge_static_i18n` L969 起 |
| 动态计数占位符（@WARN_TOTAL@/@WARN_HIGH@/@WARN_MEDIUM@/@WARN_INFO@，构建期从 `dose_warning` 现查） | `_i18n_placeholders` L924–927 |
| 警示徽标/来源·相关成分·市场·核验行/三语块渲染 | `_warn_badge` L1032、`_warn_meta_html` L1038、`_warn_lang_blocks` L1062 |
| 成分页顶部摘要（最多 3 条 + 「查看全部警示」；只显示当前语言块） | `_drug_warn_html` L1082–1099 |
| `/warn` 页生成（published + severity 排序 + 分组 + 锚点 + 空态） | `build_warn()` L1100–1150；main 调用 L3685 |
| 成分页接线：预取 published 警示，按 substance_id/related_substance_id 去重分组 | `build_drug_pages` L2886–2901；`warn_line` 注入 L2988（位于 ATC 行之后、昵称/易混淆提示之前） |
| 共享导航入口 | `page()` L2463 |
| 语言块客户端切换（`[data-lang-block]` → 只显示当前 LANG） | i18n.js `apply()` L3538–3542 |
| 样式：`.lang-block` 默认英文（无 JS 可读）、`.warn-item` 卡片、`.warn-meta`、`.drugwarn`、移动端字号 | CSS L1371–1384 |
| main 统计（published only） | L3613–3620：`warn_by_sev` → `stats["warn_*"]`；done 输出 `warnings : 40 published` L3696 |

> 数据查询只有一个入口且写死 `WHERE status = 'published'`（`build_warn()` 与 `build_drug_pages()` 各一处），
> draft/retracted 在构建产物里不出现。

## 2. 验收证据

```powershell
$py  = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$node= 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$env:SITE_OUT='D:\同种药物商品名剂量对应网站\.tmp\dist-warn'
& $py -X utf8 site/build.py            # == done ==, exit 0
& $node --check .tmp\dist-warn\assets\app.js     # exit 0
& $node --check .tmp\dist-warn\assets\i18n.js    # exit 0
& $node .tmp\dist-warn\_verify\warn-p0.test.mjs  # 5/5 PASS
& $py -X utf8 .tmp\dist-warn\_verify\static_check.py  # 257/257 PASS
# 临时 http.server 8796 + http_check.mjs → 11/11 PASS
```

- **构建**：`warnings : 40 published`，`sitemap 30245 urls`（含 warn.html），`drug pages 12377 / name pages 17861`，
  exit 0，产物 30,260 个文件；`site/dist` 未动（app.js mtime 仍 2026/10/26 20:46）。
- **行为测试 5/5**：① i18n 179 keys×3 + warn 文案三语；② `data-lang-block` 在 `/`、`?lang=`、localStorage、
  `/es/` 路径下只显示对应语言块；③ /warn 页 40 条 published、每行 3 语言块与锚点、监管来源域名、
  draft（tainuo-vs-tainuolin）不泄漏；④ 成分页接线（metoprolol/levothyroxine 有摘要 + `/warn` 锚点，对照成分无）；
  ⑤ 三语入口与静态页共享导航有 nav.warn。
- **静态验收 257/257**：i18n 179×3、无 `@@`；/warn 条数 = DB published 条数；每个 warning_id 锚点齐全；
  每行 en/zh/es 三块；published 的 severity 分组齐全（high+medium）；每条 source_url 域名出现在页面；
  **34/34 个警示关联成分页都挂上摘要**且含对应 zh 标题；控制组成分页无 `.drugwarn`；
  全站导航 `/warn` 入口；sitemap 含 warn.html；三入口 hreflang 不回归。
- **HTTP 抽查 11/11**：warn.html 200（40 条、medium 分组、draft 不泄漏、i18n.js 单次）；
  drug/metoprolol.html 摘要 + `/warn` 链接；about.html 导航；i18n.js 三语 warn 文案 + lang-block；
  `/`、`/es/`、`/zh/` 200。
- **数据未动**：`data/aliases.json`、`data/confused.json`、`data/artg.json` 与 i18n P1 构建
  （`.tmp/dist-i18n2`）逐字节一致；本任务只读取 `dose_warning`。
- **搜索增强块未动**：`/* 搜索增强 */` 标记与 `searchLayers*` 函数行号区间保持原样（未编辑）。

## 3. 已知风险 / 说明

1. **西语数据缺失**：`dose_warning.title_es/body_es` 当前 40 条全部为 NULL（seed 阶段只写 zh/en）。
   页面 es 块回退英文并标 `(EN)`；要真正西语需数据任务补 es 字段（P2）。
2. **展示口径随库变化**：页面只显示 `status='published'`，条数/分组在构建期动态统计。
   今晚若继续把 draft 提升为 published，需要**重新构建**才会更新（当前 40/1）。
3. **内容为 AI 核验数据**：警示正文由 `data/seed_warnings.py` + AI 核验 apply 入库；本任务只负责展示，
   不改写、不新增医学结论；页面明示「不是医疗建议」。
4. **成分页摘要最多 3 条**：同一成分若 published 警示 >3 条只列前 3（按 severe→high→medium 排序）+「查看全部」。
5. **品牌级警示（5 条）没有成分页入口**：Tylenol/Benadryl/Gaviscon 等没有 `substance_id`/`related_substance_id`，
   只能从 /warn 页看到；如需从相关成分页跳到，需在数据层补 substance 映射。
6. **锚点 + 语言块**：`#w-<id>` 指向 article 外层（非语言块内），切换语言不影响定位；无 JS 时英文块可见。
7. 未做截图（本任务验收以 DOM/HTML/HTTP 证据为准；如需留档可对 `warn.html` 与 `drug/metoprolol.html` 各拍一张）。

## 4. 回滚方法

| 层次 | 操作 |
|---|---|
| 源码回滚 | `git checkout -- site/build.py` 后重新构建/发布（由 Lead 执行；本子智能体未跑 git） |
| 特性级回滚 | ① 删 `main()` 的 `n_warn = build_warn(db)` 调用 → /warn 页消失；② `page()` 导航删 warn 链接 → 入口消失；③ `build_drug_pages` 删 `warnings_by_sub` 与 `warn_line` 注入 → 成分页不再显示摘要；④ 数据层回滚 `data/seed_warnings.py --rollback`（Lead 决策） |
| 发布后回滚 | gh-pages revert 上一提交（新增 `warn.html`，其余是现有页面的导航/成分页摘要 diff；数据文件未变） |

## 5. 产物

- `site/build.py`：WARN_I18N / 渲染 helpers / build_warn / 成分页接线 / 导航 / `data-lang-block` / CSS / main 统计。
- `.tmp/dist-warn/`：SITE_OUT 构建产物（30,260 文件，含 `warn.html`）。
- `.tmp/dist-warn/_verify/{warn-p0.test.mjs, static_check.py, http_check.mjs, probe_*.py}`：可复跑验收脚本。
- `reports/warn-page-impl.md`：本报告。
