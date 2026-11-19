# v0.17.0 第二批：LG8 语言切换控件 + P0 首页浓度解析修复（含追加项 C）

> 结论（北京时间 2026-11-20 02:5x）：两件都完成并进同一个 `SITE_OUT=.tmp/build_v017` 构建（`== done ==`）。
> **A（LG8）**：语言控件现在是「`Language: English ▾` / `语言：中文 ▾` / `Jazyk: Čeština ▾` …」的有边界下拉，
> `aria-label` / `aria-haspopup` / `aria-expanded` 齐、Enter 开 / Esc 收（焦点回 summary）、移动端「⋯」菜单有「语言」标题；
> 390 / 768 / 1440 截图见 `docs/img/lg8-*.png`。**B（P0）**：`Tylenol Extra Strength 960 mg/30 mL` 客户端命中
> **0 → 5 个名称行**（展开 8 条产品，与 `cli.py` 首条 `TYLENOL EXTRA STRENGTH` 一致），`500 mg`（5 行）与
> `875/125 mg`（20 行 / 27 名称）**前后不变**。**C**：`HOME_EXAMPLES` 九语齐（补 ja / cs / lv）。
> `i18n_check` FAIL 0 / WARN 25，`tests.test_markets_registry` 57 OK；首屏 home 四档 before×2 / after×2 全指标相同；
> `data/drugs.db` sha256/字节/mtime 与产品 594,781 均未变。未 commit / 未发布 / 未写 `site/dist`。

## 1. 改了什么（只改 `site/build.py`，相对 task-5 状态 **+104 / −9**；相对 git HEAD 合计 +2267/−39）

### A. LG8 语言切换控件（+81 行）

1. **可见「语言」标签**：新增构建期常量 `LANG_LABEL`（9 语：Language / Idioma / 语言 / 語言 / Langue / 언어 / 言語 /
   Jazyk / Valoda）+ `_lang_label()` / `_lang_sep()`（中日韩用「：」、其余「: 」）。**没有新增 I18N 键**——
   和 `LANG_NATIVE_LABELS` 一样走「构建期常量 + 客户端同一份」，避免让 9 份 i18n 字典一起变、也不动「684 条」口径。
2. **控件标记**：`_shell_right()` 的 `summary` 改成
   `<span class="llabel">Language</span><span class="lname">English</span> ▾` 结构（服务端按页面语言写死），
   加 `aria-haspopup="true"`、`aria-expanded="false"`、`aria-label="Language: English"`；
   移动端「⋯」面板在语言列表前加 `<div class="lang-head">语言</div>`。
3. **CSS**：`.langsum` 有边框 + 背景（`--line` / `--card`），hover / `:focus-visible`（2px 环）/ 展开三态都有反馈；
   当前语言仍是 `.lang-menu a.on` 高亮（R2 口径「选项用各语言本名」不变）；`.lang-head` 小标题只出现在移动菜单。
4. **JS**（`i18n.js` 的 `apply()`，随语言切换重跑）：`.llabel` / `.lang-head` 文本与 `aria-label` 跟随界面语言；
   `<details>` 的 `toggle` 事件同步 `aria-expanded`；`Escape` 收起并 `focus()` 回 summary。
   注入方式与 `__LANG_LABELS_JSON__` 相同（新增 `__LANG_LABEL_JSON__` 占位，构建期写入）。
5. **静态副本**：`_localize_copy()` 把 `.llabel` / `.lname` / `.lang-head` / `aria-label` 按副本语言写死
   （无 JS 的 `/cs/` `/lv/` 副本也不再是英文；有 JS 时再改一次，结果相同）。

### B. P0：`splitDose()` 认浓度（+10 行）

- 旧逻辑：`(数值)/(数值) 单位` 与 `数值 单位` 两式；`960 mg/30 mL` 只切掉 `960 mg`，把 `/30 mL` 留在药名里
  （解析条显示 `Name = Tylenol Extra Strength /30 mL` → 0 候选）。
- 新逻辑：**先**匹配浓度 `数值 单位 / 数值 单位`（mg、mcg、µg、ug、g、iu ／ ml、l、g、mg、mcg、µg、ug），
  **整段剥离**并把整段作为「剂量」显示（`960 mg/30 mL`）；浓度不参与剂量加权（与服务端一致）。
  `parseQuery()` 的剂量显示从 `st[0] + ' ' + st[1]` 改成 `st.join(' ')`（单值 / 配比 / 浓度三种形状都适用）。
- 服务端基准（`cli.py` 现查）：`Tylenol Extra Strength 960 mg/30 mL` → strengths `[('960/30','mg/ml')]`、
  **8 条候选 / 5 个名称键**，首条 `TYLENOL EXTRA STRENGTH [US]`；客户端修复后是同一条目（5 个名称行，首行
  `Tylenol Extra Strength … Canada · CA, United States · US`）。

### C. 追加项：`HOME_EXAMPLES` 补 ja / cs / lv（+13 行）

- 审计说 `tryrow` 在 `/ja/` 回落到英文示例：源级确实 `HOME_EXAMPLES.get("ja")` 为空 → 回落 `["en"]`。已补
  ja / cs / lv 三条（药名保留原文，`quick` = `Tylenol Extra Strength (US) → 中国`、`pack` = `… 960 mg/30 mL`），
  九语均有自己的条目、不再回落。
- **如实说明（一行）**：`tryrow` 只渲染 `quick` 与 `pack` 两个字段，而这两字段在 en / ko / ja / cs / lv 的取值本来就相同，
  所以补 key **前后 `/ja/` 首页渲染字节完全一致**（已逐语对比，9/9 相同）；日文来自 `data-i18n` 标签
  （`米国の Tylenol Extra Strength — 中国では何と呼ばれている？` / `包装の文字で検索：`），补 key 的价值是杜绝回落。
  若要让示例查询本身用日语惯用名（如「ロキソニン」），需先确认索引命中，本轮未改（避免 0 命中）。

## 2. 怎么验的（命令 + 现查数字）

**① 编译 / 门禁 / 测试**

```
& $py -m py_compile site\build.py deploy\i18n_check.py   → exit 0
& $py deploy\i18n_check.py                               → FAIL 0 / WARN 25 / INFO 43（九语，最新 v0.17.0 齐）
& $py -m unittest tests.test_markets_registry             → Ran 57 tests / OK
```

**② 构建**：`$env:SITE_OUT='.tmp/build_v017'; & $py site/build.py` → `== done ==`；
`files 137,372 / HTML 137,138 / 1,394.9 MB`；`sitemap 75,630`；`core.json 40.3 MB（gzip 9.2 MB）`；
`i18n split` 九语（cs 105,211 B / lv 105,078 B）；`/ja/` `/cs/` `/lv/` 的 What's new 都有 v0.17.0 九语块。

**③ LG8（真实浏览器 Playwright，390×844 / 768×1024 / 1440×900，本地临时服务）**

| 检查 | 1440（en） | 1440（zh） | 390 |
|---|---|---|---|
| summary 文本 | `Language : English ▾` | `语言 : 中文 ▾` | （桌面控件隐藏，用「⋯」） |
| `aria-label` | `Language: English` | `语言：中文` | — |
| `aria-haspopup` / `aria-expanded` | true / false→true（开） | true / — | 「⋯」true / true（开） |
| 边框 / 背景 | 0.8px `rgb(207,202,191)` / 白 | 同 | — |
| 键盘 | 聚焦 summary → Enter 展开；Esc 收起且 `activeElement` 仍是 summary | — | — |
| 移动端「⋯」 | — | — | `langdd` 隐藏；`.lang-head` = `Language` 且可见；9 个本语言名 |
| 横向溢出 | 否 | 否 | 否（`scrollWidth 375 < 390`） |

截图（`docs/img/`）：`lg8-1440.png`（en 展开）、`lg8-1440-zh.png`（zh「语言：中文」展开）、`lg8-768.png`（展开）、
`lg8-390.png`（移动「⋯」菜单 + 「语言」标题 + 9 语言）。

**④ P0 before / after（同一台浏览器，`?q=…`，等索引就绪后读数）**

| 查询 | before（旧 JS） | after（新 JS） | 判定 |
|---|---|---|---|
| `Tylenol Extra Strength 960 mg/30 mL` | **0 行**；解析条 `Name = Tylenol Extra Strength /30 mL` | **5 个名称行**（`5 names matched`）；`Name = Tylenol Extra Strength`、`Dose = 960 mg/30 ml`；首行 = `Tylenol Extra Strength … CA, US`（与 `cli.py` 首条 `TYLENOL EXTRA STRENGTH` 一致） | 修复 ✅ |
| `Tylenol Extra Strength 500 mg` | 5 行 / `5 names matched`；`Dose = 500 mg` | 5 行 / 5 names；`Dose = 500 mg` | 不回归 ✅ |
| `Augmentin 875/125 mg` | 20 行 / `27 names matched`；`Dose = 875 mg` | 20 行 / 27 names；`Dose = 875 mg` | 不回归 ✅ |

**⑤ 首屏守卫**（home，四档 390/768/1440/2560，改前×2 用 `.tmp/build_cs_lv`〔LG8 前〕、改后×2 用 `.tmp/build_v017`）：

| 视口 | AFCR 前→后 | chrome 前→后 | 首屏条目 前→后 | 带宽比 前→后 | 悬浮 前→后 | 横向溢出 |
|---|---|---|---|---|---|---|
| 390×844 | 0.930 → 0.930 | 0.135 → 0.135 | 0 → 0 | 1.000 → 1.000 | 0.068 → 0.068 | 无 |
| 768×1024 | 1.005 → 1.005 | 0.105 → 0.105 | 8.5 → 8.5 | 1.000 → 1.000 | 0 → 0 | 无 |
| 1440×900 | 0.999 → 0.999 | 0.073 → 0.073 | 9 → 9 | 0.667 → 0.667 | 0 → 0 | 无 |
| 2560×1440 | 0.961 → 0.961 | 0.126 → 0.126 | 12 → 12 | 0.656 → 0.656 | 0 → 0 | 无 |

（before×2 / after×2 每档读数一致，**逐指标 0 差异**；chrome 占比不退化。）全量 24 组扫描：
**2 组 2 项未达**（`drug@1440 items 4.5`、`coverage@390 items 3.5`，v0.13.8 起既有），**退化 0、不稳定 0**。

**⑥ 数据只读**：`bytes 558,637,056`、`mtime 2026-11-17T10:59:00.5335097-08:00`、
`sha256 5C00BBE846B23D28A52706F04C8E167A2BC7CE7B3FDE66B19D7BA36CE89DA777` 与开工前一致；`product 594,781` 未变。

**⑦ 行尾**：`site/build.py` `git ls-files --eol` = `i/crlf w/crlf`（与 HEAD 一致；lone LF = 0）。

## 3. 还剩什么

1. **C 的本质**：如 §1.C 所述，补 ja/cs/lv key 后 `/ja/` 渲染与补前逐字节相同（fallback 的取值恰好相同）；
   若 Lead 要的是「日语惯用名示例」（如 ロキソニン / タイレノール），需先验证索引命中，建议单独排期。
2. **LG8 尚未覆盖 `/ja/` `/cs/` `/lv/` 的截图**：截图取的是根页 en / zh（同一套 header 模板，副本由
   `_localize_copy` 写死标签，已用 `/cs/` `/lv/` 副本 DOM 校验过 `llabel` 文案）。
3. **未跑**：`tests/trilingual/run_tests.py`（未改检索层）、`ui_interaction_smoke`、`verify_live`（发布侧）；
   `site/dist` 仍是 v0.16.0 发布中，未碰。
4. 最终 v0.17.0 构建由 Lead 做：本报告用的 `.tmp/build_v017` 已含 9 语 What's new + v0.17.0 条目，可直接作对照。

## 4. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'

& $py -m py_compile site\build.py deploy\i18n_check.py
& $py deploy\i18n_check.py                               # FAIL 0 / WARN 25 / INFO 43
& $py -m unittest tests.test_markets_registry             # 57 OK

$env:SITE_OUT='.tmp/build_v017'; & $py site\build.py     # == done ==

# 首屏 before×2 / after×2（改前用 .tmp/build_cs_lv）
foreach ($i in 1..2) { & $py deploy\first_screen_check.py --dist .tmp\build_cs_lv --pages home `
  --viewports 390x844,768x1024,1440x900,2560x1440 --json ".tmp\lg8-before-$i.json" }
foreach ($i in 1..2) { & $py deploy\first_screen_check.py --dist .tmp\build_v017 --pages home `
  --viewports 390x844,768x1024,1440x900,2560x1440 --json ".tmp\lg8-after-$i.json" }
& $py deploy\first_screen_check.py --dist .tmp\build_v017 --json .tmp\fs_full_v017.json
```
