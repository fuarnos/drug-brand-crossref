# L8 徽章收敛 · 实现报告（site/build.py，临时构建自验）

> 工位：**alias-site** ｜ 任务：task-11 ｜ 2026-11-16 ｜ 依据：`reports/2026-11-16-l8-badge-audit.md`（task-8 施工清单）
> 产物：**临时构建** `.tmp/dist-l8`（`SITE_OUT`），**`site/dist` 全程未写**（mtime 仍 10:39:30）、未改数据/DB、未 commit、未发布
> 改动：`site/build.py` **56 insertions / 35 deletions**，CRLF 未翻转（CRLF=16,853 / 纯 LF=0）

---

## 0. 结论

1. **状态胶囊 159,647 → 16,479（−89.7%）**，目标 16,512（差 33 个 = 0.2%，全部来自 CZ/LV 数据带来的页增长）。结构正是「该留的差异色」：已停售 12,394 + 已撤市 3,485 + 警示 sev/warn 600 = **16,479**。
2. **普通属性全部文字化**：plain `.tag` 20,877 → **0**；`.form-tag`（客户端剂型）→ **0**（改名 `.form-txt`，视觉不变）；`st-badge st-active / st-unknown`、`nolang-badge`、`brand-none`、ATC 级别、`cmp-b same` 全部改纯文字。
3. **国家胶囊维持 0**（未回退 `.mktxt`）；差异色保留：severe 360 / warning 240（warn 页，静态审计可见）、combo 17,498（本轮起带差异色）、picked（客户端选中态）、export（客户端行级徽标）；EU 仍是 `.mktxt` 文字（不套胶囊）。
4. **首屏守卫零退化**：与 `.tmp/first-screen/release-v0130.json` 比 **12/12 行指标完全相同、baseline 退化 0 项**（2 项「未达」是 baseline 既有）。**ui-surface 12 次扫描 0 同色**（含 drug 复方页）。
5. 临时构建：**137,331 文件 / 137,101 HTML / 0 个 0 字节 / 1,172.1 MiB**，页数与 v0.13.0 一致（combo 页 7,469 + 8,699 兼容 stub）。

---

## 1. 改了什么（按函数 / 行号，行号为改后）

| # | 位置 | 改法 | 影响元素 |
|--:|---|---|---:|
| 1 | `_status_span_html()` **11388**（新增）+ `_name_product_table` **11402/11448** | 状态词统一走新helper：`discontinued`/`withdrawn` → `st-badge st-<st>`；`active`/`unknown` → `st-text` | name 页 86,610 → 7,288 |
| 2 | `_status_summary_html()._word()` **≈14311** | 同上：`st-word` 只给停售/撤市，其余 `st-text`；`<details>`/排序/市场码不动 | atc 56,803 → 7,925；cat 4,645 → 666 |
| 3 | `_drug_list_html()` **12122** | `st-badge st-unknown`（状态未知）→ `st-text` | drug 9,218 → 0 |
| 4 | maker `ingredient_cell()` **12741** | 「成分未收录」→ `st-text` | maker 1,771 → 0 |
| 5 | 复方标记 **11098 / 12115** | 纯 `tag` → `tag combo`（差异色，与客户端 6228/6395 一致） | 17,498 获得 combo 色 |
| 6 | ATC 级别 **14667** | `<span class="tag">L{n}</span>` → `st-text` | 1,154 |
| 7 | 药名页「本页」**11786**、nickname/synonym 标记 **11255/11268**、昵称卡 **7668/7681**、矩阵「无法比较」**11094** | `tag` → `st-text` | 2,217 |
| 8 | 结果页客户端（APP_JS）**5993**（无商品名）、**6007**（成分未收录）、**6019/6021**（无译名，保留 `nolang-badge` 供 JS 移除钩子）、**6138**（详情表状态，仅停售/撤市留徽标）、**7430/7446**（`cmp-b same` → 文字）、**6250/6408/6414**（`form-tag`→`form-txt`） | 同口径；`badge sev/warn/export`、`tag combo/picked-tag`、`cmp-b diff/miss/multi` 保留 | 客户端每行 ≤3 |
| 9 | 结果页市场码 **7486**（pickbar）、**7799**（同药列表） | `tag` → `mktxt`（与 combo 静态页一致，国家继续是文字） | — |
| 10 | 品牌/成分缺名静态点 **8533 / 10960 / 11583 / 11617 / 11434** | `st-badge st-unknown brand-none` → `st-text`（保留 `brand-none` 钩子给 8759 的 JS） | 192 |
| 11 | CSS **4483–4484**（新增 `.st-text`）+ **4906**（`.form-tag`→`.form-txt`） | `.st-text{font-size:13px;color:var(--muted)}`，ATC 内 `line-height:1.25`；字号沿用 v0.12.1 的 13px，不回 12px | — |
| 12 | 死代码 | `_status_badges_html()`（`atc-st`）保留未删（现查 0 元素，仅 docstring 引用）；`.st-active/.st-unknown/.brand-none` 成死规则但保留 | — |

**未动**：v0.12.4 操作列（`.c-det` / `.linkbtn` / `.pickbtn` / `.detbtn`）、`.atcmembers .st-badge` 文本化规则（4617）、`.formchip`/`.lf-chip`/`.catchip` 交互控件、`_status_summary_html` 的 `<details>` 结构与排序、`mktxt` 国家文字、i18n 文案。

---

## 2. 前后数字（同一脚本、同一口径，全扫 137,101 HTML）

### 2.1 总账

| 类别 | v0.13.0（改前） | **临时构建（改后）** | 变化 | 目标 |
|---|---:|---:|---:|---:|
| **状态胶囊** | 159,647 | **16,479** | **−143,168（−89.7%）** | ≈16,512 ✅ |
| 国家胶囊 | 0 | **0** | 0 | 0 ✅ |
| 其它 `.tag`（non-warn） | 20,877 | **0** | −20,877 | 0 ✅ |
| `tag.combo`（差异色） | 0 | **17,498** | +17,498 | 保留 |
| 警示 `tag.warn` | 19,461 | **19,461** | 0 | 保留 |
| 剂型 `form-tag`（阅读性） | 0（静态）/3（客户端） | **0 / 0** | −3 | 0 ✅ |
| 剂型 `formchip`（交互） | 50,430 | **50,430** | 0 | 保留 |
| 筛选 `lf-chip`（交互） | 61,010 | **61,010** | 0 | 保留 |
| 分类入口 `catchip` | 45 | **45** | 0 | 保留 |

### 2.2 状态胶囊逐项

| class | 改前 | 改后 |
|---|---:|---:|
| `st-badge st-active` | 63,676 | **0** |
| `st-word st-active` | 44,460 | **0** |
| `st-badge st-unknown` | 26,443 | **0** |
| `st-word st-unknown` | 8,397 | **0** |
| `brand-none st-badge st-unknown` | 192 | **0** |
| `st-badge st-discontinued` | 5,067 | **5,067** |
| `st-word st-discontinued` | 7,327 | **7,327** |
| `st-badge st-withdrawn` | 2,225 | **2,225** |
| `st-word st-withdrawn` | 1,260 | **1,260** |
| `badge sev/warn`（warn 页） | 600 | **600** |
| **合计** | **159,647** | **16,479** |

### 2.3 按页型

| 页型 | 改前 | 改后 |
|---|---:|---:|
| name | 86,610 | **7,288** |
| atc | 56,803 | **7,925** |
| cat | 4,645 | **666** |
| drug | 9,218 | **0** |
| maker | 1,771 | **0** |
| warn 页（root+4 语） | 600 | **600** |
| combo / locale / 静态页 | 0 | **0** |

> 两遍全扫（`.tmp/l8-badge-after.json` / `after2.json`）**完全一致**；`country_detail` 为空（国家胶囊 0）。

---

## 3. 首屏守卫（`deploy/first_screen_check.py --dist .tmp/dist-l8`）

与 `.tmp/first-screen/release-v0130.json` 同视口（390x844 / 1440x900）对比，**12 行指标逐项相同**：

| 页 / 视口 | AFCR | 条目 | chrome | 悬浮 | 正文/辅助 | <14px | 溢出 | baseline 退化 |
|---|---|---|---|---|---|---|---|---|
| home 390 / 1440 | 0.93 / 1.00 | 0 / 9 | 0.14 / 0.07 | 0.068 / 0 | 16 / 14 | 9% / 6% | 否 | 0 |
| results 390 / 1440 | 0.87 / 0.90 | 3 / 3 | 0.19 / 0.13 | 0.068 / 0 | 16 / 13 | 7% / 18% | 否 | 0 |
| drug 390 / 1440 | 0.93 / 1.00 | 5.5 / 4.5 | 0.14 / 0.07 | 0.068 / 0 | 16 / 13 | 28% / 38% | 否 | 0 |
| name 390 / 1440 | 1.01 / 1.00 | 1 / 1 | 0.33 / 0.17 | 0.068 / 0 | 16 / 14 | 11% / 10% | 否 | 0 |
| atc 390 / 1440 | 0.93 / 1.00 | 7.5 / 13.5 | 0.14 / 0.07 | 0.068 / 0 | 16 / **13→14** | 14% / 16% | 否 | 0 |
| coverage 390 / 1440 | 0.79 / 0.90 | 1.5 / 5.5 | 0.27 / 0.14 | 0.068 / 0 | 16 / 14 | 12% / 4% | 否 | 0 |

- 工具结论：**`baseline 退化 0 项`**；2 项「未达」= `drug@1440 items 4.5<5`、`coverage@390 items 1.5<5`，**baseline 同值同项**，不是本轮引入（属原有待办 L14/首屏条目）。
- 唯一变化：`atc` 辅助字号 13→14px（文字化后不再有 13px 徽章），属改善。

## 4. 同色守卫（`deploy/ui_surface_check.py --dist .tmp/dist-l8`）

**6 页 × 2 视口 = 12 次扫描，同色 0 处**（白名单放行 0 处，17.7s），含 `drug` 复方页（6,102 元素）。即 task 要求「combo 项 0 FAIL」：`.tag.combo` 的暖底（`background:var(--warnbg)`，4532）不触发嵌套同色。

## 5. 完整性与抽样

- `.tmp/dist-l8`：**137,331 文件 / 137,101 HTML / 0 个 0 字节 / 1,172.1 MiB**；页数 name 91,078、combo 16,168（7,469 + 8,699 stub）、maker 15,213、drug 13,435、atc 1,154、cat 16；构建到 `== done ==`。
- 抽样（HTML 内计数）：`name/tylenol-extra-strength` st-text 1 / 差异徽标 0 / plain tag 0；`drug/amlodipine` `tag combo` 37 / `tag warn` 2 / plain tag 0；`atc/R06A` st-text 104 / `st-word` 差异色 22；`maker/kenvue` st-badge 0；`combo/metformin+sitagliptin` 徽章 0；`warn.html` sev+warn 120。
- 全站残留（应为 0）：`st-badge st-active` 0、`st-badge st-unknown` 0、`form-tag` 0、`class="tag"` 0。
- 客户端 `assets/app.js`：`form-txt` 3、`st-text` 9、`tag combo` 2、`badge sev` 2、`badge export` 3、`nolang-badge` 2（钩子保留）。

---

## 6. 风险 / 遗留

1. **`.tag.combo` 仍是胶囊**（17,498 个，暖底 + 边框，CSS 4479/4532）：按本任务「保留六类差异色徽章」口径保留；若用户要求「差异色文字不套胶囊」，只需改 4479 这一行（去掉 padding/border/background），成本 1 行 + 重扫。
2. **APP_JS 是字符串，`py_compile` 不覆盖 JS 语法**：已通过完整构建 + `results` 页两档首屏扫描（AFCR/条目/字号全同 baseline）+ `ui-surface` results 扫描验证解析正常；但结果行「每行 ≤3」的逐行 DOM 断言未单独跑（`--rows-selector` 只对成分页），建议发布前在 `/?q=tylenol` 抽查一次。
3. **死代码/死规则**：`_status_badges_html()`（`atc-st`）0 引用保留；`.st-active`、`.st-unknown`、`.brand-none` CSS 规则已无发射点（保留以免影响其它页，删除可另开小任务）。
4. **并行工位影响**：`git status` 显示 `deploy/ci_checks.py`、`tests/trilingual/run_tests.py` 被其他工位改动（**非本轮**）；本轮未跑 CI 全量/trilingual，避免与并行改动互踩。发布前需由 Lead 在干净状态跑 `ci_checks.py`。
5. `.tmp/dist-l8` 为临时产物（1.17 GiB），验收后可删；`site/dist` 未被写（mtime 10:39:30，供线上发布使用）。

---

## 7. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'

# 1) 临时构建（绝不写 site/dist）
$env:SITE_OUT='.tmp/dist-l8'; & $py site/build.py        # 等 == done ==

# 2) 徽章对账（两遍应完全一致）
& $py reports/2026-11-16-l8-badge-audit.py --dist .tmp/dist-l8 --json .tmp/l8-badge-after.json
# 期望：status:capsule 16,479；country:capsule 0；plain tag 0；tag.combo 17,498；tag.warn 19,461
#       form:capsule 50,430（仅 formchip）；filter:chip 61,010；catchip 45

# 3) 首屏守卫（对 baseline 应为「退化 0」）
& $py deploy/first_screen_check.py --dist .tmp/dist-l8 --viewports 390x844,1440x900 `
    --json .tmp/first-screen/l8.json --baseline .tmp/first-screen/release-v0130.json

# 4) 同色守卫（应 0 同色）
& $py deploy/ui_surface_check.py --dist .tmp/dist-l8 --json .tmp/ui-surface-l8.json
```
