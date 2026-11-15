# L8 徽章收敛 · 现查审计 + 施工清单（v0.13.0 产物，只读）

> 工位：**alias-site** ｜ 任务：task-8 ｜ 2026-11-16 ｜ 性质：**只读**（没改代码 / 没写库 / 没建站 / 没发布）
> 产物：`site/dist`（v0.13.0，**137,331 文件 / 137,101 HTML / 1,173.5 MiB**，与派单里的 137,331 一致）
> 脚本：`.tmp/l8-badge-audit.py`（分类口径与 `reports/2026-11-15-ui-badge-audit.py` **逐条一致**，只加了「页型 / class 变体」两个拆分维度；副本见 `reports/2026-11-16-l8-badge-audit.py`）
> 现查 JSON：`.tmp/l8-badge-audit2.json`（`badge-audit.json` 第一遍与第二遍结果一致，偏差 0.0%）

---

## 0. 结论（先看这四句）

1. **国家胶囊已经收敛到 0**（旧基线 48,315 → 现查 **0**）：combo 静态页与结果页 `marketTags()` 都改成 `.mktxt` 纯文字（`build.py` 6374–6379、12581）。目标 0 **已达成**，下一轮实现**不要再回退**，新增市场（CZ/LV/以后）自动走同一条路。
2. **状态胶囊 159,647**（旧基线 150,651，+6.0%；页数 +9.4%），目标 ≈16,512 → 还要降 **143,168**。现查里「该保留的差异色」正好 **16,479**（已停售 12,394 + 已撤市 3,485 + sev/warn 600），与目标的 16,512 结构一致 —— **不是结构跑偏，是还没动手**。
3. **真正看得见的胶囊墙在商品名页，不在 ATC**：`.st-badge` 仍是圆角 + 边框 + 底色（5007），商品名页 **86,610 个**（91,078 页几乎每页 1 个）；ATC/分类页的 `st-word` CSS 已经是纯文字（5640），视觉上不算胶囊，但 **class 还在**。所以：**验收按 class 口径（与旧基线可比），本报告同时给视觉口径**，避免「数字降了但页面没变」。
4. **剂型 / 其它**：`.form-tag` 静态 0（只在客户端结果行 3 处），`.formchip` 50,430 是交互筛选控件 → 按 L8 保留；其它 `.tag` 20,877 里 17,498 是药名页复方标记、1,154 是 ATC 级别、2,217 待按 `data-i18n` 归属；**`tag.warn` 19,461 保留**（橙红只给需注意的差异）。

---

## 1. 现查数字表

### 1.1 总账（可直接对旧基线）

| 类别 | 旧基线（125,290 HTML，2026-11-15） | **现查（137,101 HTML，v0.13.0）** | 差 | 目标 | 距目标 |
|---|---:|---:|---:|---:|---:|
| **状态胶囊**（class 口径） | 150,651 | **159,647** | +8,996（+6.0%） | 16,512 | **−143,135** |
| **国家胶囊** | 48,315 | **0** | −48,315 | 0 | **✅ 达成** |
| 其它 `.tag`（非国家、非警示） | 17,435 | **20,877** | +3,442 | 0 | −20,877 |
| 警示 `.tag.warn` | 15,559 | **19,461** | +3,902 | 保留 | 0 |
| 剂型 `.form-tag`（阅读性） | 0（静态） | **0**（静态） | 0 | 0 | ✅ |
| 剂型 `.formchip`（交互筛选） | 46,873 | **50,430** | +3,557 | 保留 | 0 |
| 筛选 `.lf-chip` / `.mkchip`（交互） | 53,541 | **61,010** | +7,469 | 保留 | 0 |
| 分类入口 `.catchip`（导航） | 45 | **45** | 0 | 保留 | 0 |
| `badge sev` / `badge warn`（警示页） | 360 / 240 | **360 / 240** | 0 | 保留 | 0 |

> 增长来源：页数 125,290 → 137,101（+9.4%）＋ CZ/LV 数据让复方行 / 警示行变多。按每页密度看状态胶囊 1.202 → 1.164（−3.2%），**没有新增样式债**。

### 1.2 按页型（现查）

| 页型 | HTML 页数 | 状态胶囊 | 国家胶囊 | 其它 `tag` | `tag.warn` | formchip / lf-chip |
|---|---:|---:|---:|---:|---:|---:|
| `name/` 商品名 | 91,078 | **86,610** | 0 | 8 | 0 | 0 |
| `drug/` 成分 | 13,435 | 9,218 | 0 | **19,715** | 19,461 | 50,430 / 60,930 |
| `atc/` 类目 | 1,154 | **56,803** | 0 | 1,154（L 级） | 0 | 0 |
| `cat/` 分类 | 16 | 4,645 | 0 | 0 | 0 | 80 |
| `maker/` 厂商 | 15,213 | 1,771 | 0 | 0 | 0 | 0 |
| `combo/` 复方 | 16,168 | **0** | **0**（`.mktxt` 纯文字） | 0 | 0 | 0 |
| 警示页（根 + 4 语 × 各 1） | 5 | 600（sev 360 / warn 240） | 0 | 0 | 0 | 0 |
| 静态页（about/coverage/glossary/confused/whats-new/atc.html） | 8 | 0 | 0 | 0 | 0 | 0 |
| 首页 / 结果（`index.html`） | 1 | 0（客户端渲染，静态扫不到） | 0 | 0 | 0 | 0 |

### 1.3 状态胶囊逐项（class 变体，与旧清单逐行对应）

| class 组合 | **现查** | 旧基线 | 分布 | 决策 |
|---|---:|---:|---|---|
| `st-badge st-active` | **63,676** | 61,576 | name | **降为文字** |
| `st-word st-active` | **44,460** | 44,424 | atc 41,114 / cat 3,346 | **降为文字** |
| `st-badge st-unknown` | **26,443** | 20,095 + 192 | name 15,454 / drug 9,218 / maker 1,771 | **降为文字**（信息不能删） |
| `st-word st-unknown` | **8,397** | 7,852 | atc 7,764 / cat 633 | **降为文字** |
| `st-word st-discontinued` | **7,327** | 7,319 | atc 6,774 / cat 553 | **保留差异色** |
| `st-badge st-discontinued` | **5,067** | 5,100 | name | **保留差异色** |
| `st-badge st-withdrawn` | **2,225** | 2,247 | name | **保留差异色** |
| `st-word st-withdrawn` | **1,260** | 1,246 | atc 1,151 / cat 109 | **保留差异色** |
| `badge sev` / `badge warn` | **360 / 240** | 360 / 240 | warn 页（每语 72 / 48） | **保留** |
| `st-badge st-unknown brand-none` | **192** | 192 | name | **降为文字**（信息保留） |
| **合计** | **159,647** | 150,651 | | 可降 **143,168** / 应留 **16,479** |

---

## 2. 施工清单（按 `site/build.py` 函数 / 行号）

| # | 渲染点（函数） | 行号 | 现查元素 | 改法 | diff 估计 |
|--:|---|---|---:|---|---|
| 1 | `_name_product_table()` · 状态徽章节 | **11425–11431** | **86,610**（name） | `discontinued` / `withdrawn` → 保留 `st-badge st-<st>`；`active` / `unknown` → `<span class="st-text">`（13px `--muted`，保留 `data-i18n="drug.status.*"`）；`brand-none`（11599）同步 | 8–12 行 |
| 2 | `_status_summary_html()` · 内部 `_word()` | **14261–14308**（14293–14295） | **61,444**（atc + cat） | 同上：`st-word st-<st>` 只给 `discontinued` / `withdrawn` 留；其余换 `st-text`。`<details>` 结构与排序 **不动** | 5–8 行 |
| 3 | `_drug_list_html()` · 行尾状态 | **12102–12105** | 9,218（drug） | `st-badge st-unknown`（「状态未知」）→ `st-text` | 3 行 |
| 4 | `build_maker_pages().ingredient_cell()` | **12723–12728** | 1,771（maker） | 「成分未收录」`st-badge st-unknown` → `st-text`（缺名/缺成分同族） | 2 行 |
| 5 | 复方标记（`_drug_list_html` / `_combo_line_html`） | **12097–12098**、11093 | 17,498 | 纯 `tag` → `tag combo`（差异色），与客户端 6224 / 6391 统一；**注意**：CSS `.tag.combo` 目前是胶囊（4479–4480 + 4532 暖底），要么保留「暖底文字」，要么把 4479 的 padding/border 去掉（见 §3-1 决策） | 3–5 行 |
| 6 | ATC 页级别 `L{level}` | **14646** | 1,154（atc） | `<span class="tag">L1</span>` → 纯文字（`class="lv"`） | 1 行 |
| 7 | 药名页「本页」标记 | **11768**（`_family_name_html`） | 8（name） | `tag` → 纯文字 | 1 行 |
| 8 | 其余 2,217 个 drug plain `tag` | 11250 / 11263（nickname / synonym 标记）、7662–7676（昵称提示） | 2,217 | 说明性标记 → 文字；`tag.warn`（未核实）保留 | 3–4 行 |
| 9 | CSS 胶囊化 | **4475–4480**（`.tag` 已是文字；`.tag.combo/.warn/.sev/.picked/.export` 仍是胶囊）、4532、4656、4675–4679（`.badge`）、5007–5012（`.st-badge`）、5175–5180（`.cmp-b`） | — | 新增 `.st-text{font-size:13px;color:var(--muted)}`；`.st-badge` 只服务差异色后，`st-active` / `st-unknown` 的底色分支可删 | ≈15 行 |
| 10 | 客户端结果行（APP_JS，静态审计扫不到） | 6130 / 6134（名字页产品表 JS）、6220–6225、6246、6388–6392、6404 / 6410、6426 | 每行 ≤3 | 同步降级；`cmp-b same` → 文字（7424–7426），`diff` / `miss` 保留 | ≈10 行 |
| 11 | 死代码（可选） | **14311–14343** `_status_badges_html()`（emits `atc-st`） | **0**（只有 docstring 引用 14407） | 可删；不删也不影响数字。**别误用它做改法** | −33 行（可选） |

**预计规模**：`site/build.py` 约 **11 处渲染点 / 60–90 行 diff + CSS ≈15 行**；不动 `etl/`、`lib/`、DB、i18n 文案；`tests/` 里 grep 无徽章断言（0 命中），不需要改测试。

---

## 3. 风险点

1. **v0.12.1 的边框 / 字号收敛不能回退**：`.tag` 13px 纯文字（4475–4476）、`.form-tag` 纯文字（4902）、`.tag` 无 border/background —— 新 `.st-text` **必须 13px**（不许回到 12px），别顺手给 `.tag` 加回 padding/border。
2. **v0.12.4 操作列不能回退**：结果行两个按钮在 `<td class="c-det">`（6425–6430），触控 44px（4673）。去 badge 样式时**不要碰** `.linkbtn` / `.detbtn` / `.c-det` / `.pickrow`。
3. **手机卡片（<768）要同步**：结果表变卡片靠 `td::before` 字段名（4914 区）；`.tag` 的 `margin-left:6px`（4476）在卡片首列会产生行首空格 → 降级元素在 `.c-brand` / `li.mkrow` 内设 `margin-left:0`。`.atcmembers .st-badge{padding:0;border:0;background:none}`（4617）是 ATC 缺名徽章的文本化开关，**不要删**。
4. **首屏守卫口径会变**：`deploy/first_screen_check.py` 把 `.tag` / `.st-badge` 列入 `AUX_ANC`（218、224）—— class 去掉后这些文字会算进正文，AFCR / chrome 占比可能偏移。改完必须按 AGENTS §5 跑**改前 / 改后**两份数字。
5. **「可见胶囊」≠「class 胶囊」**：atc + cat 的 61,444 个 `st-word` 视觉上已经是文字（5640–5644），改 class 只是让审计口径收敛；**不要为了数字删信息**（状态未知 / 无中文名 / 成分未收录都是身份事实）。
6. **不新增人工颜色表**：状态仍由 DB `status` / `collision` / release 推导，combo 由活性成分数推导（红线 2）。降级只改呈现层。
7. `_status_badges_html()` 是死代码（0 元素）；ATC 现走 `_status_summary_html()`，别改错函数。

---

## 4. 验收数字与抽检页面

**命令**（只读，下一次实现后必须复跑）：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py reports/2026-11-16-l8-badge-audit.py --json .tmp/l8-badge-after.json
# 期望：status:capsule ≤ 16,512（结构 = 已停售 12,394 + 已撤市 3,485 + sev/warn 600）
#       country:capsule == 0        （已达，不许回退）
#       country:tag-other 里：plain tag == 0、tag.combo ≈19,715（差异色保留）、tag.warn ≈19,461（保留）
#       form:capsule ≤ 50,430（只剩 .formchip 交互控件）；filter:chip 61,010 不变；catchip 45 不变
& $py deploy/first_screen_check.py          # 改前 / 改后各一次，写两个数字
& $py tests/trilingual/run_tests.py          # 内容页结构性改动，必跑
& $py reports/2026-11-15-ui-baseline-probe.py --json .tmp/l8-after-dom.json   # 结果页 DOM：每行胶囊 ≤3、首屏 ≤24
```

**抽检页面（每页型 2 个，优先现查最重的页）**

| 页型 | URL 1 | URL 2 | 看点 |
|---|---|---|---|
| 商品名 | `/name/tylenol-extra-strength.html` | `/name/斯莫克必恩中心静脉輸注液.html`（54 徽章，全站最重） | active → 文字、discontinued/withdrawn 留色 |
| 成分 | `/drug/amlodipine.html`（38 tag + 2 warn） | `/drug/sodium-chloride.html`（182 徽章） | 复方标记带差异色、`tag.warn` 不变 |
| 复方 | `/combo/metformin+sitagliptin.html` | `/combo/fluticasone+salmeterol.html` | 市场码是 `.mktxt` 纯文字、**0 徽章** |
| 厂商 | `/maker/kenvue-brands-llc.html` | `/maker/sarepta-therapeutics-inc.html`（59） | 「成分未收录」→ 文字 |
| ATC | `/atc/A.html`（2,254 徽章） | `/atc/R06A.html`（四状态行） | 在售/未知 → 文字，停售/撤市留色 |
| 分类 | `/cat/dermatologicals.html`（1,012） | `/cat/analgesics.html` | 同上 |
| 结果 / 首页 | `/?q=tylenol`（390 宽看卡片） | `/zh/`（首页） | 每行徽章 ≤3、行内市场 `.tag` == 0 |
| 警示页 | `/warn.html` | `/zh/warn.html` | `badge sev` 72 / `badge warn` 48 全保留 |

---

## 5. 复现口径（供复核）

- 扫描 `site/dist` 下 `rglob("*.html")` = **137,101** 个（assets / data 不计）；dist 合计 137,331 文件 / 1,173.5 MiB / 页脚 v0.13.0。
- 分类口径与 `reports/2026-11-15-ui-badge-audit.py` **逐条一致**：`tag` + 2 位小写市场码 = 国家；`st-badge / badge / atc-st / st-word / cmp-b / nolang-badge / brand-none` = 状态；`form-tag / formchip / tr-badge` = 剂型；`lf-chip / mkchip` = 筛选；`catchip` = 导航。
- **一个元素 = 一处 `class="…"` 属性**，多类只算一次（`st-badge st-unknown brand-none` = 1 个状态）。
- 两遍扫描一致：`.tmp/l8-badge-audit.json` 与 `.tmp/l8-badge-audit2.json`（后者修了 tag 变体标签）。
- 未使用任何写操作：未跑 `site/build.py`、未写 `site/dist`、未写库、未 commit、未发布。
