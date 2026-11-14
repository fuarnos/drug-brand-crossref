# 批次 C/D + L1/L8 改动计划（只读准备，未改代码）

> 工位：site-ui　｜　日期：2026-11-15　｜　状态：**计划稿**
> Lead 在构建/发布 v0.11.10 期间冻结 `site/build.py`；本文件只做「按规范直接能落」的施工图。
> 每条给出：改成什么样 / 落到哪个函数 / 验收数字（可脚本复算）/ 风险与回退。
> 待 task-7 的 `reports/2026-11-15-ui-redesign-spec.md` 落盘后，把「规范原文编号」补进第 4 列。

## 0. 通用约束（每条都适用）

- 只改 `site/build.py`；行尾 **CRLF**；四语 + fr 键集一致（`deploy/i18n_check.py` FAIL 0）。
- 新文案一律进 `UI_I18N`（en/es/zh/zh-Hant）＋`FR_I18N`（zh-Hant 才拿得到 build.py 真值，
  `data/i18n_zh_hant.json` 不在写权限）。
- 三条硬门槛每次自验：`band_ratio 0.652–0.682`（1440/1920/2560）、`overflow = 0`、内容页 `items ≥ 5`。
- 每批做完：`py_compile` → `i18n_check` → `lib 61 / etl 55` → `ci_checks --fast` → 首屏守卫（临时产物）。
- 回退单位：每批独立成一组函数级 diff；任一批挂掉可只回退该批。

## 1. 批次 C（次级页统一）

| 项 | 改成什么样 | 落点（函数） | 验收数字 |
|---|---|---|---|
| **L7** 页头四件套 | 每个次级页 `<main>` 顶部固定四件：① 返回路径（`← 搜索` / 面包屑文本）② H1 标题 ③ 一句话摘要（现 `drug-identity` / `sub` 行）④ 「继续搜索」入口（现 `_shell_search_html` 在页头，改为正文顶部一行「换个名字再查」） | `page()` 的 `main` 开头模板 + `_shell_search_html()`；`build_drug_pages` / `build_name_pages` / `build_combo_pages` / `build_maker_pages` / `build_category_pages` / `build_coverage_page` / `build_about` / `build_warn` | 8 个页型抽检脚本：`main > .pagehead` 存在且含 4 个部件（选择器计数 = 4）；缺件 = 0 |
| **L9** 成分页层级 | ① 中文名从「H1 后的隐藏 span」提到 H1 同行的次级名（`h1 .name-zh` 可见于 zh/zh-Hant）；② 筛选条（`.listfilters`）置顶到粘性条下方（不折叠）；③ 已选筛选变成可点 × 的标签行；④ 与 K1 的 `<details>` 市场块共存（市场块 summary 里显示「已筛选」计数） | `build_drug_pages`（body 拼接）、`_drug_list_html`（`lf_html`）、`CSS` | AFCR ≥0.5、items ≥5、`html.has-q` 下筛选行高度 ≤44px；筛选标签点击后 `data-mk-filter` 计数变化 |
| **L10** 商品名页顺序 | 现顺序：H1 → 候选行 → banner/notice → 成分卡 → 品牌差异表 → 单包装明细。改为：**概览（名字 + 候选数 + 一句话）→ 具体制剂（成分卡/明细表）→ 市场差异（family 块）→ 登记详情（折叠）** | `build_name_pages`（body 拼接顺序）、`_family_block`（挪到最后并包 `<details open>`） | 4 段标题在 DOM 里按序出现（脚本按 `data-section` 排序断言）；页高 +≤5% |
| **L11** 复方页每成分一行 | 成分清单 `<ul class="sub">` 改表格化一行一个成分（名字 + 结构 ID + 该成分在这组里的含量范围，来自 H3 的 per-record 数据）；长配方（>6 成分）折叠 | `build_combo_pages`（`ing_items` 生成） | 成分行数 = 页面成分数（DB 现查）；`details` 折叠只对 >6 成分生效 |
| **L12** 厂商页搜索+分页 | 页内搜索框（按品牌名过滤行，纯 JS）+ 分页（每页 60 行 → `?p=2` 深链，服务端也可用）+ 同名不同成分的区分列（「成分」列已有，补「同名不同药」badge 只在 collision=severe 时） | `build_maker_pages`、`APP_JS`（页内过滤） | 分页链接可用（`?p=` 存在 2 页以上的厂商页数现查）；搜索过滤后行数变化有测试 |
| **L13** 分类页 | 类别页顶部加「本类成分数 / 记录数」两数字 + 子类折叠（默认收起，`<details>`）；行内成分名与 ATC 码分列 | `build_category_pages`、`build_atc_pages` | 折叠块数 = 子类数；首屏 items ≥5 不退化 |
| **L14** 覆盖页 | 表头 `position:sticky`；数字列右对齐 + `tabular-nums`；每行加比例条（宽度 = 有成分记录比例）；「缺口」段落收进 `<details>` | `build_coverage_page`、`CSS` | 表头 sticky 计算值 = `sticky`；比例条数 = 市场数；数字列 `text-align:right` |
| **L15** 关于/警示页 | 顶部页内目录（锚点列表，8–12 项）；「许可/来源」段移到页面最末（现 About 在中间）；警示页按严重度分三段（high/medium/info） | `build_about`、`build_warn` | 目录锚点数 ≥8 且每个锚点目标存在（脚本断言）；来源段是正文最后一个 `<div data-i18n-html>` |

## 2. 批次 D（收敛）

| 项 | 改成什么样 | 落点 | 验收数字 |
|---|---|---|---|
| **L8** 减少框套框 | ① 只在「表格容器」与「独立卡片」保留边框；② 页面内嵌提示框（`.notice`）去掉外框、改左侧 3px 色条；③ 徽章收敛：国家/剂型/状态三类胶囊降级为**纯文字 + 颜色**（`.tag` 去 border/背景），差异色只留：severe（红）/warning（橙）/EU（蓝）；④ 卡片内间距统一 12px | `CSS`（`.notice` / `.tag` / `.card` / `table.res`） | 主内容区边框元素数 **−50% 以上**、胶囊徽章数 **−60% 以上**（用 task-8 探针 before 数字对账） |
| **L1** 首页补齐 | ① 占位文字 = 「输入商品名、通用名或包装文字」（四语）；② 示例固定 3 个（现在 3 个 ✅）；③ 类别卡片统一尺寸（4×2 等宽等高，`min-height` 对齐）；④ 「最近更新」移到页脚上方（现在在 catquick 之后） | `build_index_page`（body 顺序 + `HOME_EXAMPLES`）、`CSS`（`.catgrid`）、`_home_cat_chips` | 4 张/2 行等高（脚本测高度差 = 0）；更新日志是 footer 前最后一个 `<section>` |

## 3. 依赖与顺序建议（避免相互打架）

1. 先 **L8（CSS 收敛）**：它改的是全局 token/类，先做完再改页面结构，避免重复调样式。
2. 再 **L7（页头四件套）**：一次覆盖 8 个页型，后续 L9–L15 只补各自正文。
3. 然后 **L9 → L11 → L10**（成分页/复方页/品牌页，都是我刚动过的函数，上下文最熟）。
4. 再 **L12 → L13 → L14 → L15**（互相独立）。
5. 最后 **L1**（首页小改，风险最低，可放最后避免被前面反复改 CSS 影响）。

## 4. 需要规范确认的三处（task-7 spec 落盘后回填）

- **L16 手机三项**：具体是哪三项（搜索框首屏 / 筛选入口文案 / 结果行高？）。
- **L4 选中态**的颜色值：用现有 `--accent-weak` 还是规范另给（现在实现是 `--accent-weak` + 3px 左边）。
- **L8 徽章保留清单**：severe/warning/EU 三类差异色是否够；国家徽章是否整体降级为文字。

## 5. 待办：v0.11.10 发布后的第一步

1. 重新跑 `ci_checks --fast`（现在 `dist-integrity` FAIL 是因为 Lead 正在重建 dist）。
2. 用 task-8 的探针量一次 v0.11.10 的 before（`reports/2026-11-15-ui-baseline-probe.py`），
   把结果页/次级页的边框数、徽章数、字号记下来，和批次 B 已改的结果表对齐。
3. 按 §3 顺序落批次 C。
