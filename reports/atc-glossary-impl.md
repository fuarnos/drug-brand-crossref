# v0.6.4 ATC 码搜索 + 术语表页 + 快捷键 实现报告

> 任务：task-73（`site/build.py` 独占，v0.6.3 之后）。输入：`reports/index-legacy-removal.md` 系列结论、
> 现有索引/四语 i18n 基建、`substance.atc`/`atc_name` 数据。
> 未跑 git/发布、未改 `site/dist`、`data/drugs.db` 或其他跟踪文件。构建：`SITE_OUT=.tmp/dist-atc`。

---

## 0. 结果

| 项 | 数值 |
|---|---|
| 构建 | exit 0；**57,848 文件 / 408.8 MB**（不含 `_verify`）；sitemap **57,697** URL |
| 索引 ATC | `atc` 数组字段：**113,244 / 127,085** 条目带 ATC（13,841 条无 ATC，无法按码找）；**3,062** 个不同码 |
| core | 27.8 MB（v0.6.1 基线 27.1 MB，+`atc` 列 ~0.7 MB）；`data/index.json` 仍不存在（v0.6.1 行为保持） |
| ATC 搜索 | `C07AB02` → **99 个商品名**；类前缀 `C07` → **680 个**；解析条明确「ATC 前缀匹配」；无命中清晰提示 |
| 术语表 | 新增 **/glossary.html**：**13 条术语 × 4 语言**（en/es/zh/zh-Hant），导航入口、canonical/hreflang、`/es//zh//zh-hant/` 静态副本 |
| 快捷键 | `/` 聚焦搜索、`Esc` 先关建议再清空；输入法 composition（`isComposing`/keyCode 229）不干扰 |
| 四语 | I18N **328 keys × 4 语言完全一致**；无 `@@` 残留；四语 glossary/ATC 文案齐全 |

## 1. 改动清单（`site/build.py`）

### A2 索引与 ATC 搜索
| 内容 | 位置 |
|---|---|
| `load_index` 查询加 `s.atc`，按条目聚合 `a["atc"]` | L4196（SELECT）、聚合逻辑在条目归属处 |
| 条目字段 `atc`（去重排序、最多 8 个、无则 `null`） | L4321–4322 |
| core 数组列 + 编码字段列表同步 `atc`（分片自动携带） | L5434 / L5482 |
| `atcQuery()`：只认 `^[A-Z]\d{2}(?:[A-Z]{0,2}\d{0,2})?$`（C07 / C07A / C07AB02；普通药名不误判） | L2350–2355 |
| `renderATC()`：独立渲染路径（不参与名称/别名/模糊匹配；仅 core 就绪后执行，分片阶段显示加载提示） | L3124–3155 |
| `render()` 顶部 ATC 优先分支 | L3157–3160 |
| `startSearch()`：ATC 查询先确保完整 core 到位，不走分片快速路径 | L3585 |
| 解析条：新增 ATC 项（码 + 「ATC 前缀匹配，不是商品名匹配」说明） | `parseBarHTML` L2661–2666 |
| 自动完成：ATC 码/前缀补全（distinct 码 + 命中条目数，点击回填） | `acCompute` L2708–2719、`acPaint` atc 分支、`acSelect` |
| 移动端/样式 | `.atcbar` CSS（L2204） |

### B10 术语表
| 内容 | 位置 |
|---|---|
| `GLOSSARY_I18N`：13 条术语（INN/BAN/USAN/ATC/MAH/DIN/NDC/ARTG/FDC/LASA/OTC/Rx/strength）× 4 语 | L745–约 L985 |
| 合并：en/es/zh 进 `_merge_static_i18n`（GLOSSARY_I18N 加入 source 元组）；zh-Hant 由 `_install_zh_hant` extras 直接注入 | merge/extras 两处 |
| `GLOSSARY_TERMS` + `build_glossary()`：四语 `data-lang-block` 表格 + meta/canonical/hreflang + 静态副本 | L5311–5338 |
| main 调用（在 `build_seo_files` 前，sitemap 自动收录） | L5926 |
| 导航：`page()` 每页新增 Glossary 入口（`nav.glossary` 四语） | L3856 |
| CSS：`dl.glossary` | L2200–2202 |
| UI/元信息 keys（四语）：`nav.glossary`、`meta.glossary.title/desc`、`parse.atc`、`parse.match.atc`、`atc.*` | `UI_I18N` 四个语言块 |

### B9 快捷键（可选）
- `document` keydown：`/` 在非输入控件中聚焦搜索并全选；`Esc` 先关自动完成，再清空查询并重绘；
  `ev.isComposing || keyCode===229` 直接返回（不干扰中文输入法），带 Ctrl/Meta/Alt 时不抢键。位置 L3724–3744。

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-atc'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-atc\assets\app.js                      # 0
& $node --check .tmp\dist-atc\assets\i18n.js                     # 0
& $node --max-old-space-size=6144 .tmp\dist-atc\_verify\dom.test.mjs  # 10/10 PASS
& $py -X utf8 .tmp\dist-atc\_verify\static_check.py                   # 39/39 PASS
# 临时 http.server 8803 + http_check.mjs → 21/21 PASS
```

- **DOM 10/10**：① `C07AB02` → 15 行可见结果、含 β-blocker、解析条 ATC 说明；② 前缀 `C07` 结果 ≥ 精确码；
  ③ `Lipitor` 不误判 ATC；④ `C7` 非法形态不按 ATC；⑤ `Z99XX` 无命中提示；⑥ 输入 `C07A` 自动完成提示 C07xx 码；
  ⑦ `/` 聚焦、`Esc` 关建议/清空；⑧ 输入法 composition 中 Esc 不干扰；⑨ 四语 ATC/glossary key 齐全。
- **静态 39/39**：四语 I18N 328 keys 完全一致、无 `@@`；core `atc` 数组列、3,062 码、每项 ≤8、格式合法；
  app.js 具备 ATC 识别/独立渲染/自动完成/键盘与 IME 保护；`glossary.html` 52 个 `<dt>`（13×4）、四语块、meta/canonical/hreflang；
  `/es//zh//zh-hant/glossary.html` 副本存在且 `<html lang>`/canonical 正确；抽样 32 页导航 glossary 链接无 404；
  sitemap 含 4 个 glossary URL；`data/index.json` 仍不存在；无 0 字节文件。
- **HTTP 21/21**：glossary 根页与三份副本 200（西/简/繁标题正确、四语术语均渲染）；首页导航含 glossary；
  app.js 含 ATC/快捷键；core 含 `atc`；`data/index.json` 404（v0.6.1 行为保持）。
- **样例**：`C07AB02` = 美托洛尔等 99 个商品名；`C07` = 680 个；`N02BE01`（对乙酰氨基酚）等按码可查；
  四语术语表含 INN/BAN/USAN/ATC/MAH/DIN/NDC/ARTG/FDC/LASA/OTC/Rx/strength。

## 3. 风险 / 已知问题

1. **ATC 覆盖不是全量**：113,244/127,085 条索引带 ATC；13,841 条（多为无 ATC 的复方/非标准成分）无法按码搜到，
   属数据层覆盖（substance.atc 6,021 条有码），不是前端问题。
2. **类前缀搜索可能很大**（`C07` 类命中 680 条、全站码前缀最坏 >10k）：候选截断 200 + 分组折叠 + 加载更多，
   meta 显示完整命中数；页面仍不会一次渲染全部。
3. **每条目 ATC 最多存 8 个**（复方成分极多时截断）：常规产品 ≤6 个成分，实际影响极小；如需完整性需扩字段。
4. **ATC 码格式**：接受 3–7 位前缀形态（含 `Z99XX` 这类不存在但格式合法的码）→ 显示无命中提示，不误当药名；
   若用户输入真实药名恰好形如 `C07`（极少见）会被当作 ATC 查询。
5. **产物体积**：408.8 MB（v0.6.1 395.5 MB；含 v0.6.3 改动 + `atc` 列 core +0.7 MB / 分片 +~2.5 MB + glossary 4 页）；
   发布拷贝时间继续上升，但无单文件 >50 MB（最大 core 27.8 MB）。
6. **术语表译文**：四语均为人工整理简短释义（非机器翻译）；zh-Hant 为直接繁体值，后续若改简体术语需同步 4 份。
7. **快捷键**：仅在非输入控件中拦截 `/`，浏览器自带快速查找仍可用 Ctrl+F；Esc 先关建议再清空（与既有行为一致）。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | ① 删索引 `atc` 字段（load_index/core 字段）；② 删 `atcQuery/renderATC` 及其分支；③ 删 `GLOSSARY_I18N/build_glossary/main` 调用与导航链接；④ 删快捷键监听、`atc.*`/glossary UI keys |
| 发布后 | gh-pages revert 上一提交（仅页面/索引内容变化，无数据文件变化） |

## 5. 产物

- `site/build.py`：ATC 索引字段与搜索路径、自动完成、术语表四语页/导航、快捷键。
- `.tmp/dist-atc/`：构建产物（57,848 文件 / 408.8 MB；sitemap 57,697）。
- `.tmp/dist-atc/_verify/{dom.test.mjs, static_check.py, http_check.mjs, probe_atc.py}`。
- `reports/atc-glossary-impl.md`：本报告。
