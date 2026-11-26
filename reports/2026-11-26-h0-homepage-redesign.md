# H0 首页改版：白底极简居中 hero（按用户 2026-11-26 参考图 + 现有配色）

- 日期：2026-11-26（北京时间上午；本机 US-Pacific 2026-11-25 下午）
- 工位：`frontend`；任务：共享任务板 `task-7`（用户直接指令，P0）
- 参考图：`.tmp/homepage-mockup-20261126.png`（用户提供，1536×1024）
- 基线：HEAD `24e48bf7e83` + task-1 的 v1.2.5 源码改动（静态页 144,000）；`site/dist` 仍是 v1.2.4 线上产物
- 自验构建：`SITE_OUT=.tmp/frontend-home`，**未写 `site/dist`**；截图 `.tmp/frontend-home/shots/`
- **未 commit / 未发布 / 未改 CHANGELOG / 未改 `data/drugs.db` / 未改 `deploy/`**（只读跑脚本）

## 0. 结论（先行）

| 验收项 | 结果 |
|---|---|
| 与参考图一致 | ✅ 白底、左上 `DrugCrossRef` 字标、右上语言下拉（胶囊）、居中巨型标题、副标题、大搜索框 + 右侧实心按钮、下方三链接（竖线分隔） |
| 配色只用现有 token | ✅ 标题 `--fg` / 副标题与图标 `--muted` / 按钮与链接 `--accent #0b6b53` / 输入框 `--card` + `--line` 描边 / 页面 `--bg`；**新增 0 个色值**（参考图的蓝色没有采用） |
| 页头导航收进页脚 | ✅ 页头 `nav` 数 = 0；页脚 `.footnav` 内含 **43 个站内链接**（分类 / 市场两个下拉与全部入口一个不丢）；`.foot-links` 另补 Coverage |
| 功能不丢 | ✅ `#q` `#qgo` `#ac` `#out` `#mkchips` `#pickbar` `#meta` `#country` `#src` `#ctrydetails` `#u1guide` 全部在位；示例 / 分类 / 最近更新 / 覆盖声明 / 报告入口保留在 hero 之下（`.home-rest`） |
| URL / canonical / hreflang / 数据口径 | ✅ 未改（9 份首页仍是 `/`、`/es/`、`/zh/`、`/zh-hant/`、`/fr/`、`/ko/`、`/ja/`、`/cs/`、`/lv/`，head 模板未动） |
| 九语 i18n | ✅ 新增 6 键 × 9 语 = 54 条；`deploy/i18n_check.py` **FAIL 0**（WARN 28 / INFO 43，基线 27/43，+1 = 品牌字标 `DrugCrossRef` 不翻译） |
| 390 / 1440 一屏完整可见 | ✅ hero 底边正好 844 / 900（`min-height:100svh - header`），无横向溢出（`scrollWidth 375 < 390`、`1425 < 1440`） |
| 无障碍 | ✅ 输入框有 `<label class="sr-only">`、按钮 `aria-label`、`focus-visible` 描边 2px、对比度：`--fg` on `--bg` ≈ 15.6:1、白字 on `--accent` ≈ 5.5:1（均 ≥ 4.5:1）；`prefers-reduced-motion` 关闭过渡 |
| 构建 | ✅ `== done ==`，静态产品页 144,000、sitemap 5 片 230,435、总 3,442.4 MB |
| 首屏守卫 | ⚠️ 报告模式：新增 4 条 `primary:search:top`（0.46–0.53，限 0.4，属「居中 hero」的必然结果，见 §4）；**字号 / chrome / AFCR 全部达标**，`regressions 0` |

**一句话**：首页换成参考图那种白底居中 hero（配色全部沿用现有 token），导航整体下沉到页脚、功能与九语文案一个不丢；390/1440 一屏完整、无横向溢出，字号 16px+，i18n FAIL 0；唯一未达的内部阈值是「主操作在首屏上 40% 内」——参考图本身就是居中构图，需 Lead 拍板是否改成顶部布局。

## 1. 改动清单（只改 `site/build.py` + 本报告）

| 位置 | 改动 |
|---|---|
| `page()`（新增参数 `home_hero`） | 首页壳：`<body class="home-hero">` + `.hdr-hero`（字标 `DrugCrossRef` + `_shell_right(hero=True)` 只留语言下拉），**页头不再输出 `<nav>`**；页脚新增 `.footnav`（原 `_shell_nav_html` 整体搬过去）与 `.foot-links` 的 Coverage 入口 |
| `_shell_right()`（新增参数 `hero`） | `hero=True` 时不出「⋯」菜单（导航已在页脚），语言下拉标记与 i18n 逻辑完全复用 |
| `build_index_page()` | 新的首屏结构：`.hero`（`h1.hero-title` / `p.hero-sub` / `.hero-search`（原 `.searchwrap`→`.searchbar` 结构不变）/ `.hero-links` 三链接）→ `.home-rest`（3 步流程条、示例、`#srcnote`/`#identity`/`#out`、高级筛选、报告行、`#u1guide`、分类、最近更新、加载提示、覆盖声明） |
| `HOME_HERO_CSS`（新增常量，约 70 行） | 只通过首页 `head_js` 内联；**不进 `assets/style.css`** → 其它页面（含 33 万长尾页）CSS 哈希与字节不变 |
| i18n | `UI_I18N`（en/es/zh/zh-Hant）与 `FR_I18N`/`KO_I18N`/`JA_I18N`/`CS_I18N`/`LV_I18N` 各加 `hero.title` / `hero.sub` / `hero.howto` / `hero.sources` / `hero.about` / `hero.cta` |

`git diff --stat -- site/build.py`：**158 insertions / 19 deletions**（含 CSS 常量、hero 标记、`page()` 分支与 54 条译文）。

## 2. 与参考图的对应关系

| 参考图 | 实现 | 数值（1440×900 实测） |
|---|---|---|
| 白底 | `--bg #fbfbf9`（页面）+ `--card #fff`（输入框） | 背景 `rgb(251,251,249)` |
| 左上 `DrugCrossRef` 字标 | `<a class="logo logo-word">DrugCrossRef`，800 字重 | 22px / x=24（页头全宽，右缘 1416） |
| 右上「🌐 简体中文 ▾」 | 复用 `.langdd > summary.langsum`（原有语言切换逻辑与九语菜单） | 110×44 胶囊，`--card` + `--line` 描边 |
| 巨型深色标题 | `h1.hero-title`，`data-i18n="hero.title"` | **64px / 800 / `--fg`**，居中 |
| 副标题 | `p.hero-sub`，`data-i18n="hero.sub"` | 20px / `--muted` |
| 大搜索框 + 实心按钮 | `.searchbar`（放大镜图标 + `#q` + `#qgo`） | 输入框 736×60（`--card`+`--line`）、按钮 132×60（`--accent` + 白字） |
| 三链接「怎么用 \| 数据来源 \| 关于我们」 | `.hero-links`：`#u1guide` / `coverage.html` / `about.html` | 16px、`--accent`、竖线用 `--line` 边框 |
| 居中构图 | `.hero{min-height:calc(100svh - 72px);justify-content:center}` | hero 底边 = 900（等于视口高） |

中文文案严格按参考图：标题「国际药品名称对照」、副标题「查药盒上的名字，看它在其他国家或地区叫什么。」、按钮「查药名」、三链接「怎么用 / 数据来源 / 关于我们」；其余 8 语为等价短句（见 `data` 字典）。

> 按钮为何不直接用 `home.submit`：该键的 zh 值是「搜索」（全站搜索按钮共用），参考图要求「查药名」，因此新建 `hero.cta`（仅首页 hero 用，`home.submit` 不动）。差异记在这里备查。
> 占位文案：沿用 `home.q_ph`，zh 值已按参考图改成「输入药名，例如 Tylenol」（zh-Hant 同步「輸入藥名，例如 Tylenol」；en/es/fr/ko/ja/cs/lv 保持各自等价文案）。

## 3. 自验

### 3.1 九份首页产物 + 结构

```
file                        bytes  hero  body  hdr_nav  ft_nav  bad
index.html                224,378  True  True  True    True    -
es/index.html             229,546  True  True  True    True    -
zh/index.html             220,006  True  True  True    True    -
zh-hant/index.html        219,803  True  True  True    True    -
fr/index.html             219,960  True  True  True    True    -
ko/index.html             229,182  True  True  True    True    -
ja/index.html             233,035  True  True  True    True    -
cs/index.html             230,647  True  True  True    True    -
lv/index.html             230,668  True  True  True    True    -
```

（`hdr_nav` = 页头里**没有** `<nav class="sn">`；`ft_nav` = 页脚里有它；`bad` 为空 = hero/`.home-rest`/`#q`/`#qgo`/`#ac`/`#out`/`#mkchips`/`#u1guide`/筛选/三条链接/`app.js` 全部命中。）

### 3.2 交互（真浏览器，Playwright）

- 输入 `Tylenol` → 点「查药名」→ URL `?q=Tylenol`、结果区 86 个名字命中、页面标题切到结果页 → **搜索/联想/结果链路未受影响**。
- 查询生效（`html.has-q`）后 hero 自动收起：hero 高度 585 → **160**，标题/副标题/三链接 `display:none`，`#out` 顶边 **353**（1026×~700 视口下结果直接进首屏）——落地页的极简与结果页的密度不再互相拖累。
- 页脚导航 43 个链接、语言下拉 9 语都在 DOM 里；无横向滚动。

### 3.3 首屏 7 指标（`deploy/first_screen_check.py`，before = 现 `site/dist` v1.2.4 / after = 新产物）

| 页型 · 视口 | AFCR | chrome 占比 | 首屏条目 | 正文/辅助最小字号 | 主操作 top |
|---|---|---|---|---|---|
| home · 390×844 | 0.9301 → **0.9231** | 13.5% → **14.9%** | 0 → **0** | 16/14 → **16/17** | 0.251 → **0.462** |
| home · 768×1024 | 1.0055 → **1.0021** | 10.5% → **7.0%** | 9 → **0** | 16/14 → **16.1/17** | 0.239 → **0.511** |
| home · 1440×900 | 0.9988 → **1.0000** | 7.3% → **8.0%** | 9 → **0** | 16/14 → **20/17** | 0.221 → **0.528** |
| home · 2560×1440 | 0.9610 → **1.0000** | 12.6% → **5.0%** | 12 → **0** | 16/14 → **20/17** | 0.138 → **0.517** |

- `before` 24 次扫描：1 项未达（`coverage 390 items`，**存量**）；`after` 24 次扫描：5 项未达 = 4 条 `primary:search:top`（新，见下）+ 同一条 coverage 存量；`regressions 0`、不稳定 0。模式仍是 `report`（不阻塞发布）。
- **`primary:search:top` 0.46–0.53 > 0.4**：主操作（搜索框顶边占视口高度）在居中 hero 里必然落到 45–53%；参考图的搜索框也在 ~0.54。主操作仍 100% 可见（`vis_ratio 1.0`）。**要不要为这条内部阈值改成「顶对齐」布局，请 Lead 拍板**（改法是一行 CSS：`.home-hero .hero{justify-content:flex-start;padding-top:12vh}`）。
- **首屏条目 9 → 0**：首页在 `first_screen_check` 里是 `entry` 类型，`items_min = 0.0`——参考图的构图本来就只有「标题 + 副标题 + 搜索 + 三链接」，分类 chips 现在在 hero 之下；这不是把内容删了。
- 字号：390 档曾出现 `min_body_font 15px`（副标题 clamp 下限 15），已改到 **16px** 并重跑（本轮结果 16/17 达标）。

### 3.4 其它

```
& $py -m py_compile site/build.py                 # exit 0
& $py deploy/i18n_check.py                        # FAIL 0 / WARN 28 / INFO 43（基线 27/43，+1 = 「DrugCrossRef」品牌字标）
$env:SITE_OUT='.tmp/frontend-home'; & $py site/build.py   # == done ==
  static top N: 144,000 products, markets 16
  product     : 144,000 static pages (top 144,000)
  seo files   : 404 + robots + sitemap index (5 shards, 230,435 urls)
  core.json   : 68.0 MB    total size: 3442.4 MB
```

截图（Chrome headless，1440×900 / 390×844 / 768×1024）：

- `.tmp/frontend-home/shots/home-zh-1440x900.png`
- `.tmp/frontend-home/shots/home-zh-390x844.png`
- `.tmp/frontend-home/shots/home-zh-768x1024.png`

（1440 实拍：`DrugCrossRef` 左上、语言胶囊右上、64px 标题、20px 副标题、736×60 输入框 + 132×60 实心按钮、三链接竖线分隔，与参考图逐项对位，唯一差别是主色为本站绿 `#0b6b53`。）

## 4. 命令（可复核）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'

# 改前基线（只读现 site/dist）
& $py deploy/first_screen_check.py --dist site/dist --json .tmp/first-screen-before.json --shots .tmp/first-screen-before-shots
# 自验构建（只写 .tmp，绝不写 site/dist）
$env:SITE_OUT = '.tmp/frontend-home'; & $py site/build.py          # 等 == done ==
# 结构自验（9 份首页 + 关键 ID）
& $py .tmp/verify_home.py
# 改后首屏 + 截图
& $py deploy/first_screen_check.py --dist .tmp/frontend-home --json .tmp/first-screen-after.json --shots .tmp/first-screen-after-shots
& $py .tmp/compare_home.py                                         # before/after 表
# 九语 + 语法
& $py deploy/i18n_check.py ; & $py -m py_compile site/build.py
# 截图归档
Copy-Item .tmp\first-screen-after-shots\fs-home-1440x900.png .tmp\frontend-home\shots\home-zh-1440x900.png
```

## 6. 390 移动档修复（Lead 复审后追加，2026-11-26 上午）

Lead 复审 `.tmp/frontend-home/shots/home-zh-390x844.png` 时发现三处问题，已修复并重建：

| 问题（改前） | 原因 | 改法（改后） |
|---|---|---|
| 放大镜图标掉到输入框外左下方 | `.sb-mag` 绝对定位挂在 `.searchbar` 上，而移动端 `.searchbar` 换行成「输入框 + 按钮」两行，`top:50%` 落到两行中间（输入框下沿之外） | 新增 `.sb-field` 包裹「图标 + label + input」并 `position:relative`，图标 `left:14–18px; top:50%; translateY(-50%)` 永远在**框内**左侧；输入框 `padding-left:44–50px` 留位 |
| 「查药名」按钮下方叠着「想查哪里?」 | `.t11row` 与两行搜索区零间距，`#meta`（空）撑开行、把链接挤到按钮右下角 | 移动端 `.t11row{margin:10px 0 0;justify-content:center;gap:6px}` —— 次级控件独立成行，与按钮/输入框**零重叠** |
| 输入框 / 按钮 / 次级控件垂直间距混乱 | 同上（换行后 `row-gap` 未定义） | `.searchbar{row-gap:10px}` + `.sb-go{margin-top:0}` |

改后 390×844 实测（Playwright，`getBoundingClientRect`）：

```
input   l=14 t=399 r=361 b=453   (347×54)
button  l=14 t=463 r=361 b=515   (347×52)        → btnBelowInput = true
mag     l=28 t=415 r=50  b=437   → magInsideInput = true
mkopen  l=296 t=525 r=361 b=546  → mkBelowBtn = true
links   l=63  t=568 r=313 b=612  → linksBelowMk = true
hero    t=64  b=844              → heroBottom = 844（视口内）
tabbar  t=788 b=844              → 内容最低点 612 < 788，tab 栏不遮 hero 内容
scrollW = 375 < 390              → 无横向溢出
placeholder = 「输入药名，例如 Tylenol」（zh 值已改；zh-Hant 同步「輸入藥名，例如 Tylenol」，其余 7 语保持各自等价文案）
```

重建后首屏守卫复跑：home 390 AFCR 0.9301 → **0.9231**、chrome 13.5% → **14.9%**、字号 16/17、无横向溢出；`primary:search:top` 0.458（Lead 已核：该项属报告模式，不在 v0.10.3 阻塞四项内，保持居中构图）。
截图已覆盖：`.tmp/frontend-home/shots/home-zh-390x844.png`（新）与 `home-zh-1440x900.png`（桌面未回归）。

## 5. 还剩什么 / 交给 Lead 与 release

1. **要 Lead 拍板**：`primary:search:top` 0.46–0.53（内部阈值 0.4）。保持居中（像参考图）= 接受这 4 条报告项；要清零就把 hero 改成顶对齐（一行 CSS，视觉上会比参考图更「上重」）。
2. **可选文案**：搜索占位严格照图（「输入药名，例如 Tylenol」）需改 `home.q_ph` 的 9 语字典值（现为「例如：Tylenol Extra Strength」），会再触发一次构建。
3. **页脚导航**：`_shell_nav_html` 原样复用，两个下拉在页脚向上展开（已加 `.footnav .sn-panel{bottom:100%}`），移动端仍可用底部 tabbar。
4. **release 构建提示**：本改动只影响 9 个首页文件 + 无 `assets/` 变化（`HOME_HERO_CSS` 走首页内联，`style.<hash>.css` 哈希不变 → 其它顶层页只有 v1.2.5 版本号带来的页面变化）。生产构建后请再跑一次 `first_screen_check` 留档，并按 v1.2.6 的 CHANGELOG 决定版本号。
5. 临时产物：`.tmp/frontend-home` 已按「只留证据」处理——保留 9 份语言副本、顶层页、sitemap 与 `shots/`，删掉 `name/ product/ drug/ maker/ combo/ atc/ cat/ data/ assets/` 等 144,000+ 页面目录（释放 3.82 GB，D 盘空闲 10.50 GB），给 `release` 的生产构建留空间；`site/dist` 全程未被触碰。
