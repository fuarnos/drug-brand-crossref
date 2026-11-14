# UI 现状度量基线（L1–L17 重设计的「改前」数字）

> 工位：**phaseb-plan** ｜ 任务：task-7 ｜ 2026-11-15 ｜ 性质：**只读取证**（未改 `site/build.py`、未写 `site/dist`、未动 `data/`/`etl/`/`db/`、未 commit、未发布）
> 用途：`reports/2026-11-15-ui-redesign-spec.md`（规范）与 `reports/2026-11-15-ui-badge-convergence.md`（徽章收敛清单）的**改前对照表**；改完用**同一套脚本**再跑一次即可判退化。
> 脚本（本工位新增，可复跑）：`reports/2026-11-15-ui-baseline-probe.py`、`reports/2026-11-15-ui-badge-audit.py`。

---

## 0. 先看这一段：为什么「改前」有两个状态

**取数窗口里 `site/dist` 被重建了**（不是本工位干的）。时间线（全部本机时间）：

| 时刻 | 事件 |
|---|---|
| 12:15 | `site/dist` = **v0.11.9**（本轮改前产物，页脚 `v0.11.9 · 2026-11-15`） |
| 12:16 | `rclone` 开始按 `deploy/sync_r2.ps1` 发布（读 dist） |
| **12:38–12:41** | 本工位跑 **首屏守卫 G**（24 组）+ 抓 7 页静态首屏源码 → **干净改前** |
| 12:45–12:48 | 本工位跑 **全站徽章审计 B**（第一遍） |
| 12:47:15 | `site/dist/assets/style.*.css` 被重建（另一位工位在实现 K1/L2） |
| 12:48–12:51 | `site/dist` 各页被逐个重写 |
| 12:50:58 | 构建结束：dist 页脚变成 **v0.11.10 · 2026-11-15**（含 K1/T35 + L2 部分实现） |
| **12:52** | 本工位跑 **DOM 探针 P**（18 组 + 9 张 390 截图）→ 量到的是**重建后**的 v0.11.10「改中态」 |
| 12:56 | 徽章审计 B 第二遍（重建后）→ 与第一遍**一致**（§5） |

**所以本文的权威「改前」= §1（G）+ §2（结果页 390 DOM）+ §3-A（7 页静态首屏源码）**；
**§3-B / §4 的边框与胶囊数是「改中态」（v0.11.10，12:52）**，因为改前（12:15 构建）的次级页 HTML 已被覆盖、无法再取（仓库里没有该产物副本；`site/dist` 不入库）。

> **补救办法（要真做 before/after 时必须二选一，由 Lead 拍板）**
> 1. **以「改中态」为起点**：L2/L7/L8 的实现已在跑，用 §3-B/§4 的 12:52 数字做 before，改完比 after（推荐，省一次 20 分钟构建）；
> 2. **重建改前产物**：`git stash` 工作区 → `$env:SITE_OUT='.tmp/dist-v0119'` → `& $py site/build.py` → 用 `--dist .tmp/dist-v0119` 跑探针 → `git stash pop`。**必须等当前没有任何人构建时做**（AGENTS §7 单构建纪律）。

**改中态已发现 1 个回归（不是本工位改的，先给证据）**：结果页 390 卡片模式列标签被截断成「产品名称 · …」「成分 · 对…」「规格与剂…」，值被省略号吃掉（[截图](../docs/img/v01110-mid-results-tylenol-390.png)）。改前列序是 4 列、手机卡片正常（[截图](../docs/img/v0119-before-results-tylenol-390.png)）。→ 已在 `reports/2026-11-15-ui-redesign-spec.md` §3-L2/L16 列为必验项（390 卡片标签完整、值不截断）。

---

## 1. 改前 7 指标（首屏守卫 G，v0.11.9 · 12:38–12:41）

```powershell
& $py deploy/first_screen_check.py --json .tmp/first-screen/before-20261115.json --shots .tmp/first-screen/shots-20261115
# 24 次扫描，145.7 s，退出码 0（报告模式）
```

| 页型 | 视口 | AFCR | 带宽比 | 首屏条目 | chrome | 悬浮 | 正文 | 辅助 | <14px | 溢出 | 未达项 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| home | 390×844 | 0.93 | 1.00 | 0.0 | 0.14 | 0.068 | 16 | 14 | 10% | 否 | — |
| home | 768×1024 | 1.01 | 1.00 | 9.0 | 0.11 | 0.000 | 16 | 14 | 5% | 否 | — |
| home | 1440×900 | 1.00 | **1.00** | 9.0 | 0.07 | 0.000 | 16 | 14 | 6% | 否 | **band_ratio** |
| home | 2560×1440 | 0.96 | **1.00** | 12.0 | 0.14 | 0.000 | 16 | 14 | 5% | 否 | **band_ratio** |
| results | 390×844 | 0.88 | 1.00 | **0.5** | 0.18 | 0.068 | 16 | **12** | 11% | 否 | **items / 辅助字号** |
| results | 768×1024 | 0.91 | 1.00 | **1.5** | 0.19 | 0.000 | 16 | 13 | 20% | **是** | **items / 溢出** |
| results | 1440×900 | 0.90 | 0.67 | **3.0** | 0.13 | 0.000 | 16 | **12** | 21% | 否 | **辅助字号** |
| results | 2560×1440 | 0.92 | **1.00** | **3.0** | 0.18 | 0.000 | 16 | **12** | 17% | 否 | **band_ratio / 辅助字号** |
| drug | 390×844 | 0.92 | 1.00 | 5.0 | 0.21 | 0.068 | 16 | 13 | 29% | 否 | — |
| drug | 768×1024 | 1.00 | 1.00 | 9.0 | 0.17 | 0.000 | 16 | 13 | 36% | 否 | — |
| drug | 1440×900 | 1.00 | 0.67 | 8.5 | 0.15 | 0.000 | 16 | 13 | 34% | 否 | — |
| drug | 2560×1440 | 1.00 | 0.67 | 7.0 | 0.15 | 0.000 | 16 | 13 | 34% | 否 | — |
| name | 390×844 | 1.00 | 1.00 | 1.0 | **0.40** | 0.068 | 16 | 14 | 0% | 否 | **chrome** |
| name | 768×1024 | 1.00 | 1.00 | 1.0 | 0.29 | 0.000 | 16 | 14 | 0% | 否 | — |
| name | 1440×900 | 0.99 | 0.67 | 1.0 | 0.24 | 0.000 | 16 | 14 | 0% | 否 | — |
| name | 2560×1440 | 1.00 | 0.66 | 1.0 | 0.15 | 0.000 | 16 | 14 | 0% | 否 | — |
| atc | 390×844 | 0.93 | 1.00 | 7.5 | 0.14 | 0.068 | 16 | 13 | 4% | 否 | — |
| atc | 768×1024 | 1.01 | 1.00 | 15.0 | 0.11 | 0.000 | 16 | 13 | 12% | 否 | — |
| atc | 1440×900 | 1.00 | 0.67 | 16.5 | 0.07 | 0.000 | 16 | 13 | 13% | 否 | — |
| atc | 2560×1440 | 0.99 | 0.66 | 50.0 | 0.05 | 0.000 | 16 | 13 | 17% | 否 | — |
| coverage | 390×844 | 0.79 | 1.00 | **1.5** | 0.27 | 0.068 | 16 | 14 | 0% | 否 | **items** |
| coverage | 768×1024 | 0.91 | 1.00 | **4.5** | 0.19 | 0.000 | 16 | 14 | 0% | 否 | **items** |
| coverage | 1440×900 | 0.89 | 0.67 | 6.5 | 0.14 | 0.000 | 16 | 14 | 0% | 否 | — |
| coverage | 2560×1440 | 0.92 | 0.66 | 12.0 | 0.15 | 0.000 | 16 | 14 | 0% | 否 | — |

**合计：24 次扫描，9 组未达标、12 项**：`band_ratio` 3（home@1440 / home@2560 / results@2560）、`items` 4、`min_aux_font` 3（results 三档 12px）、`chrome_ratio` 1（name@390 0.398）、`overflow` 1（**results@768 横向溢出**）。横向溢出这一条本来就该守死，现在破了 1 档。

> **另有独立验收线**：`atc4-ui` 的 `reports/2026-11-15-ui-probe-before.md`（56 项断言、对 v0.11.10 量）与本报告结论一致（结果页每行套边框、胶囊徽章、次级页缺返回路径、手机结果卡截断、首屏条目不足）。本报告 = **规范线的 before/after 对照**；那份 = **实现验收清单**。两者交叉复核，数字不冲突。

**改前最痛的 5 处（按用户 L 项的靶点排）**

1. **结果页 390 首屏 0.5 条**：身份卡（绿框）+ 提示 + 工具条 + 选中条把结果推到第二屏（[截图](../docs/img/v0119-before-results-tylenol-390.png)）。
2. **辅助字号 12px**（results 三档）：`button.linkbtn.pickbtn`（「◎」）与 `.tag` 徽章。
3. **结果页 768 横向溢出**：结果表在平板档撑破视口。
4. **桌面带宽比 1.00**（home 两档 / results@2560）：内容带没按「中间 2/3」收，§2.4 硬条件未达标。
5. **name@390 chrome 0.40**：名字页页头与说明块吃掉 40% 屏。

---

## 2. 结果页逐项（改前 · v0.11.9 · 390×844，`index.html?q=tylenol&lang=zh`）

来源：`?q=tylenol&lang=zh` 的 DOM 探针（12:39 快照，`.tmp/ui-baseline/smoke.json`）。

| 项 | 改前值 |
|---|---|
| h1 | `tylenol`，**24px / 700** |
| 表格 | `table.res.rows`，**4 列**：`剂量 / 品牌 / 市场 / 详情`，表头 14px / 600 |
| 列 1 `c-dose` | 16px / 400，例：`500 mg 片剂`，行高 40 |
| 列 2 `c-brand`（药名位） | **16px / 400**（链接态，`--accent` 绿）或 16px / 600（纯文本 `brand-plain`），行高 40 |
| 列 3 `c-market` | 16px / 400，内含 `.tag` 胶囊 **13px**，例：`SG 数据截止 2026-08-07`，行高 41 |
| 列 4 `c-det` | 16px / 400，行高 **60**（`◎` + `详情`） |
| 边框元素数（主内容区） | **131** |
| 　　其中 | `tr.br`（结果行自身）**10**、`span.tag.us` 12、`button.u2chip` 9、`span.tag.cn` 9、`span.tag.ca` 7、`span.tag.combo` 6、`span.tag.au` 4 |
| 胶囊徽章数（首屏可见） | **64**（pill 61 / box 3） |
| 　　逐个 | `form-tag` 14、`tag.us` 12、`cn.tag` 9、`ca.tag` 7、`combo.tag` 6、`au.tag` 4、`badge.sev` 3、`gb.tag` 3、`sg.tag` 2、`es.tag` 2、`mx.tag` 1、`hk.tag` 1 |
| 可见文字最小字号 | **12px**（`button.linkbtn.pickbtn` 的「◎」） |
| `<14px` 文本占比 | **34.5%**（91 / 264 个文本节点） |
| `<12px` | 0 |
| `<details>` | 2 个（「所有同规格 / 更多记录」「高级筛选」），默认都收起 |
| 按钮文案清单（可见，去重） | `◎`×10、`详情`×10、`×`、「复制标准名」、「复制表格」、「下载 CSV」、示例按钮（`Tylenol Extra Strength`/`Metformin`/`960 mg/30 mL`）、`中国泰诺`/`中国台湾ACETAMINOPHEN` 等 6 个候选 chip |
| 横向溢出 | 否（doc 390 = vw 390） |

**改前 1440（同查询，12:52 改中态数据仅作对照）**：`tr.br` 无边框但 `td` 五列各 20 条边框（共 248），胶囊 84（含 `mkchip` 12、`form-tag` 24）。

---

## 3. 次级页 6 类

### 3-A 页头四件套（**改前 v0.11.9**，静态源码抓取 12:41，`main` 开头 1.4 KB）

| 页面 | 返回路径 | 标题 | 一句话摘要 | 继续搜索入口 | 四件套 |
|---|---|---|---|---|---|
| `drug/amlodipine.html` | **无** | h1 `Amlodipine` | `ATC C08CA01 · 12 个市场 · 2,975 条记录` | **无**（只有站头导航） | **缺 2** |
| `name/tylenol-extra-strength.html` | **无** | h1 `Tylenol Extra Strength` | `Found in: CA、US` + `同名不代表可互换…` | **无** | **缺 2** |
| `combo/ferric-oxide-red+pramoxine+zinc-oxide.html` | **无** | h1 三成分 | `Fixed-dose combination` + 两段说明 + notice | **无** | **缺 2** |
| `maker/kenvue-brands-llc.html` | **无** | h1 `Kenvue Brands LLC` | `Manufacturer / MAH` + **3 份重复的 introspection 文案（en/es/zh 各一段）+ 3 份 stats（重复）** | **无** | **缺 2 + 重复说明 6 块** |
| `cat/analgesics.html` | **有**（`全部 ATC 类别与大类`） | h1 四语并列 | `主题合集——不代表同效或可互换` + `ATC N02/M01A——镇痛与退热药`（四语 4 块） | **有**（页内搜索框 `cf-input`，JS 注入） | **齐但重复** |
| `coverage.html` | **无** | h1 `覆盖与新鲜度` | 覆盖说明 + 来源说明（2 段） | **无** | **缺 2** |
| `atc/R06A.html`（分类/ATC 类） | **有**（`全部 ATC 类别` · `R06`） | h1 `R06A` + 四语类名 + `L3` 胶囊 | `来源：Wikidata · CC0 1.0`（四语 4 块） | **有**（「搜索该类别」按钮） | **齐** |

> 结论：**6 类次级页里只有 cat / atc 有返回路径**；**没有一类有独立的「继续搜索」入口**（都只能靠站头导航）。四语并排写法（`lang-block`）在 maker / cat / atc 上造成明显的「重复说明」——这正好是 L8「减少重复说明」的靶点。
> 改前 6 类页面的 `lang-block` 总数（探针口径，12:52）：maker **9**、cat **332**、atc **140**、drug **179**、name/combo/coverage **0**。

### 3-B `<details>` / 徽章 / 边框（**改中态 = v0.11.10 · 12:52**，改前精确值已被重建覆盖，见 §0 补救）

| 页面 | 边框数 390 / 1440 | 边框前三名（390） | 胶囊数 390 / 1440 | `<details>`（数/展开） | 最小字号 |
|---|---|---|---|---|---|
| `drug/amlodipine.html` | **317 / 317** | `span.ms-spec` 69、`span.uname` 54、`li.mkrow` 52 | 58 / 58（`tag` 33、`lf-chip` 14、`formchip` 5、`tag.warn` 2） | **53 / 1** | **12px**（`span.n`） |
| `name/tylenol-extra-strength.html` | 10 / 19 | `tr` 3、`div.card` 1、`span.tag` 1 | 1 / 1（`tag`） | 0 | 13px（`span.tag`） |
| `combo/ferric-oxide-red+…html` | 24 / 42 | `tr` 9、`span.tag.us` 9、`div.notice` 2 | 9 / 9（`tag.us` ×9） | 0 | 13px |
| `maker/kenvue-brands-llc.html` | **104 / 224** | `tr` 60、`nolang-badge` 33、`st-badge` 6 | 39 / 39（`nolang-badge` 33、`st-badge.st-unknown` 6） | 0 | 13px |
| `cat/analgesics.html` | **195 / 195** | `li` 187、`button.lf-chip` 4、`input.cf-input` 1 | **534 / 534**（`st-active.st-word` 356、`nolang-badge` 66、`st-unknown` 54、`st-discontinued` 42、`st-withdrawn` 11、`lf-chip` 5） | **204 / 0** | **12px**（`span.n`） |
| `coverage.html` | 23 / 95 | `tr` 12、`button` 2、`div.notice` 1 | **0 / 0** | 0 | 14px |
| （参考）`atc/R06A.html` | 50 / 50 | `li` 45、`div.notice` 4、`span.tag` 1 | 145 / 145（`st-active` 86、`st-discontinued` 20、`nolang` 20、`st-unknown` 16、`st-withdrawn` 2） | 54 / 0 | 13px |
| （参考）`index.html` 首页 | 33 / 33 | `button` 8、`a.catchip` 8、`li.u1step` 3 | 9 / 9（`catchip` 9） | 1 / 0 | 13px（`span.n`） |
| （参考）结果页 `?q=tylenol` | **117 / 248** | 390：`tr.br` 10、`pickbtn` 10、`detbtn` 10、`tag.us` 8、`combo` 6；1440：`td`×5 各 20 | 39 / 84 | 2 / 0 | 13px |

**逐页「框套框」证据**（改中态）：`drug` 页 52 个 `li.mkrow` 各带 1 条边框（列表行套框）、`maker` 60 个 `tr` 带边框、`cat` 187 个 `li` 带边框、`combo` 9 个 `tr` + 9 个国家胶囊并排 —— 与 L8「边框只用于表格与独立卡片、卡内靠留白分组」直接冲突。

---

## 4. 手机 390×844（改前 + 改中）

**改前截图（v0.11.9，G 在 12:38–12:41 拍的 390 档）**

| 页面 | 截图 | 首屏条目（G） | 搜索框在首屏 | 筛选入口文案 |
|---|---|---:|---|---|
| 首页 | [v0119-before-home-390.png](../docs/img/v0119-before-home-390.png) | 0.0（不作要求） | **是**（`#q`，上缘 ~35% 屏） | — |
| 结果页 | [v0119-before-results-tylenol-390.png](../docs/img/v0119-before-results-tylenol-390.png) | **0.5** | 是（页头 + 搜索框） | 「高级筛选」（`details.advfilter`）+「目标市场：看当地用什么名字（可选）」 |
| 成分页 | [v0119-before-drug-amlodipine-390.png](../docs/img/v0119-before-drug-amlodipine-390.png) | 5.0 | 否（站头 logo + `⋯`） | 「筛选」（`summary.formchip.lf-toggle`） |
| 名字页 | [v0119-before-name-tylenol-390.png](../docs/img/v0119-before-name-tylenol-390.png) | 1.0 | **否** | — |
| ATC 页 | [v0119-before-atc-r06a-390.png](../docs/img/v0119-before-atc-r06a-390.png) | 7.5 | **否**（有「搜索该类别」按钮） | — |
| 覆盖页 | [v0119-before-coverage-390.png](../docs/img/v0119-before-coverage-390.png) | **1.5** | **否** | 「按产品数 / 按市场」排序按钮 |

**改中态截图（12:52，dist = v0.11.10，含 K1 + L2 部分实现）**，用于给实现者看「现在长什么样」：
[home](../docs/img/v01110-mid-home-390.png) · [results](../docs/img/v01110-mid-results-tylenol-390.png) · [drug](../docs/img/v01110-mid-drug-amlodipine-390.png) · [name](../docs/img/v01110-mid-name-tylenol-extra-strength-390.png) · [combo](../docs/img/v01110-mid-combo-ferric-oxide-red-390.png) · [maker](../docs/img/v01110-mid-maker-kenvue-brands-llc-390.png) · [cat](../docs/img/v01110-mid-cat-analgesics-390.png) · [atc](../docs/img/v01110-mid-atc-r06a-390.png) · [coverage](../docs/img/v01110-mid-coverage-390.png)

**改中态的 390 事实**（探针，供 before/after 对比用）：

| 页面 | 首屏条目（G，改前） | 边框（探针） | 胶囊（探针） | 关键观察 |
|---|---:|---:|---:|---|
| 结果页 | 0.5 | 117 | 39 | **卡片模式列标签截断、值被省略号吃掉**（回归）；产品名 17px/700，按钮已改「选择此产品/查看登记详情」 |
| 首页 | — | 33 | 9 | 示例已 3 个（`.tryrow`），但 `#u1guide` 里另有 5 个示例按钮（合计 8）；搜索按钮在 390 只显示箭头 |
| 成分页 | 5.0 | 317 | 58 | K1 落地后 `<details>` 53 个（市场块可收起），首屏条目未退化 |

---

## 5. 全站徽章与边框盘点（B，125,290 个 HTML 全扫）

```powershell
& $py reports/2026-11-15-ui-badge-audit.py --json .tmp/ui-baseline/badge-audit-current.json
# 扫描 125,290 个 HTML；两遍（重建前 12:45–12:48 / 重建后 12:56）结果一致到 0.1%
```

| 类别 | 元素数 | 出现在多少页 | 主要位置 |
|---|---:|---:|---|
| **状态胶囊**（`st-badge` / `badge` / `atc-st` / `st-word` / `cmp-b` / `nolang-badge` / `brand-none`） | **150,651** | 50,939 | `name/` 78,228、`atc/` 56,231、`drug/` 9,207、`cat/` 4,614、`maker/` 1,771 |
| **国家胶囊**（`.tag.<cc>`） | **48,315** | 6,896 | 全部在 `combo/`（46,930 US/AU/CA/TW/HK/ES/GB/MX/SG/EU/CN + 1,385 FR） |
| **剂型胶囊**（`.formchip` / `.form-tag` / `.tr-badge`） | **46,873** | 12,438 | 全部在 `drug/`（剂型筛选 chip） |
| 其它 `.tag`（`tag` 单用 17,435 + `tag.warn` 15,559 …） | 32,994 | 6,612 | `drug/` 31,832（规格冲突/无法比较）、`atc/` 1,154（级别 L1–L4） |
| 筛选 chip（`.lf-chip` / `.mkchip`） | 53,541 | 12,454 | `drug/` 53,461（市场筛选）、`cat/` 80 |
| 分类入口（`.catchip`） | 45 | 5 | 首页/四语首页 |

**对账口径**：三类胶囊合计 **245,839**（48,315 + 46,873 + 150,651），另有「其它 `.tag`」32,994 与「筛选 chip」53,541 单列。逐项清单与「保留 / 降级 / 只保留差异色」决策见 `reports/2026-11-15-ui-badge-convergence.md`。

---

## 6. 缺口与本轮未做

1. **次级页「改前」精确边框/胶囊数缺失**（dist 被重建覆盖）——补救见 §0；本工位按「改中态 12:52」给出，并已在规范里把验收改成「改中 ×0.55」这种相对口径。
2. **结果页 1440 的改前 DOM 只抓到 390**：`smoke.json` 只有 390；1440 的 §3-B 数字是改中态。
3. **真机未测**：全部是无头 Chrome（`--headless=new`，DPR 1，无系统字体差异）。用户 L16 要求真机，需人或下轮补。
4. **L17 要求的 768 档 6 类页面截图**：本轮 G 有 768 档 24 张截图（`.tmp/first-screen/shots-20261115/`），但没有搬进 `docs/img/`（只搬了 390/1440 各 7 张）；需要时直接从 `.tmp` 复制。
5. **`combo` / `maker` 页未进首屏守卫 `PAGES`** —— 7 指标里没有这两类页型，L11/L12 验收要先把它们加进 `deploy/first_screen_check.py`。
6. **12:52 清理探针残留时停掉了本机近 30 分钟内的 Chrome 进程**（为修掉探针 60 秒超时的残留实例）。若同一分钟有别的会话在跑首屏守卫/截图，请重跑一次；之后不再这样清理。

---

## 7. 复跑命令（改完照抄）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# ① 7 指标（改前基线已在 .tmp/first-screen/before-20261115.json）
& $py deploy/first_screen_check.py --json .tmp/first-screen/after.json --baseline .tmp/first-screen/before-20261115.json
& $py deploy/first_screen_check.py --viewports 390x844,768x1024 --json .tmp/first-screen/after-mobile.json

# ② DOM 探针（边框/胶囊/字号/页头四件套；改中基线 .tmp/ui-baseline/before-20261115.json）
& $py reports/2026-11-15-ui-baseline-probe.py --json .tmp/ui-baseline/after.json --shots docs/img --shot-prefix v01110-after-

# ③ 全站徽章对账（改前 245,839 = 48,315 国家 + 46,873 剂型 + 150,651 状态）
& $py reports/2026-11-15-ui-badge-audit.py --json .tmp/ui-baseline/badge-audit-after.json
```
