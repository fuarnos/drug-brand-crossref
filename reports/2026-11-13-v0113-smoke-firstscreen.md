# v0.11.3 · 交互冒烟 + 首屏守卫（task-45）

- 日期：2026-11-13（北京时间）· 工位：**atc4-ui**（站点交互 + 首屏守卫）
- 上游：UI 批改动清单 [reports/2026-11-13-v0113-ui.md](2026-11-13-v0113-ui.md)；产物：`site/dist`（v0.11.3 最终产物）
- 本工位权限内只改了 `deploy/ui_interaction_smoke.py`；未碰 `site/build.py` / `site/dist`，未 commit / publish / build。

## 0. 结论（先行）

| 项 | 结果 |
|---|---|
| CDP | **可用**（Chrome 157 headless，`--remote-debugging-port` 正常，0 次重启；`crashpad OpenProcess` / mojo named pipe 未复现） |
| 交互冒烟 | **17/17 PASS，0 FAIL，0 采集异常**；观察 WARN 15 条（不阻塞）；退出码 0 |
| 首屏绝对门槛 | 8 组里 **7 组 ok**；唯一「未达」= `results@390` 条目 0.5 < 3.0 —— **既有项**（v0.11.1 是 0.0、v0.11.2 是 0.5），本版未恶化 |
| 对 v0.11.1 基线 | 退化 9 项，但**只有 1 项是本版引入**：`home@1440` 条目 9→6（常显的市场面板把 3 个类别格子挤出首屏）；其余 8 项在 v0.11.2 就已存在 |
| 结论 | **可以发**。本版唯一的首屏代价是首页 1440 少 3 个类别格（面板 167px 常显的必然结果，属用户要求的改动）；results 页条目缺口是历史遗留，需另开 task |

## 1. 脚本改动（task-45 A）

文件：`deploy/ui_interaction_smoke.py`（`git diff --stat`：1 file changed, 108 insertions(+), 39 deletions(-)）

### 1.1 第 4 项：从「details 自动展开」改成「面板常显 + 深链回填」

v0.11.3 把目标/来源市场面板从 `<details>` 改成常显块（`site/dist/index.html` 实测：`<div class="mf-details ctry-visible ctry-details" id="ctrydetails" data-always-open="1">`，`#ctrylabel` 0 命中），旧断言（`open===true` + `summary` 存在）必然假红。

新判据（3 条，覆盖原 1 条 + 任务书新增的 `?src=US`）：

```python
one("?country=CN", "country=CN&lang=zh", {"country": "CN"}, need_src=True)
one("?src=US",     "src=US&lang=zh",     {"src": "US"})
```

每个 case 断言：① `#ctrydetails` **可见**（`hidden` 属性 / `display` / `visibility` 三档 + 几何尺寸，与 `.mkrow` 可见性同口径）；② **不是 `<details>`、里面没有 `summary`**（常显无折叠的语义）；③ 下拉值被 URL 回填（`?country=CN` 额外要求 `#src` 存在）。仍是**一条记录**，所以总数仍是 17。

新增探针常量 `COUNTRY_PANEL_JS`（`deploy/ui_interaction_smoke.py` 第 208–229 行），其余 5 项判据未动。

实测输出：

```
[PASS] 市场面板常显 + ?country=CN / ?src=US 深链回填
       面板常显：<div> 813x167px、display=block、summary=False、data-always-open='1'；
       ?country=CN → #country='CN'；?src=US → #src='US'、面板可见 True
```

### 1.2 ⚠ 顺带改了第 5 项的两行语言探针（超出「其余 16 项不变」，请 Lead 过一眼）

**为什么必须动**：第 5 项探的是「`#h1` / `.candidate-line` / 国家标签都换语言」，其中国家标签原来取 `#ctrydetails summary` 文本，回退取 `#ctrylabel`。v0.11.3 把这两处都删了（`#ctrylabel` 在 `site/dist/index.html` 里 0 命中），不改就**恒红**——实测：

```
== 5. 语言切换 zh/es → #h1 / .candidate-line / summary
  [FAIL] 语言切换
         选择器缺失：ctry ← 产物里没有该元素（v0.11.0 及更早没有 .candidate-line）
```

**改动（2 处，语义不变）**：`_lang_probe` 的国家标签改取 `.ctry-panel` 里仍在的 `label[for="country"]`（i18n 键 `home.country_label`，四语齐）；`summary#ctrylabel` / `#ctrylabel` 两条命中留作兼容证据（新产物应为 false，写进 detail）。`fields` 与 detail 文案同步。改后：

```
[PASS] 语言切换 zh/en/es（#h1 / .candidate-line / 市场面板标签）
       en='Look up a medicine name — see what it is in each country'｜zh='查一个药名，看它在各国是什么'｜es='Busca un nombre…'
       市场面板标签 zh='目标市场：看当地用什么名字（可选）'；`summary#ctrylabel` 命中=False、`#ctrylabel` 命中=False
```

**如果坚持「其余 16 项不变」**：把 `_lang_probe` 的 `ctry:` 一行、`fields` 的 `("ctry", …)` 文案、`out.append` 的 title/detail 三处回退即可，代价是第 5 项恢复恒红（16/17）。

## 2. 交互冒烟 · 17/17（`--dist site/dist`）

跑法：`& $py deploy/ui_interaction_smoke.py --dist site/dist --json .tmp/v0113-fs/smoke.json`
时间：`2026-11-11T12:36:38`（本机时区）· 浏览器 Chrome 157 headless · 重启 0 次 · 退出码 0 · **约 10 分钟**（正常 1–2 分钟；本轮与另一工位的 `ci_checks.py` 抢 CPU，见 §5）

| # | 检查 | 结果 | 证据 |
|---|---|---|---|
| 1 | 剂型筛选 `drug/acetaminophen.html` | PASS | 10 个 chip 筛选生效性全对；全量 98 行，点「全部」回到 98 行；WARN 11 条（chip 数字是规格数、行是规格×市场，口径差不是 bug） |
| 1 | 剂型筛选 `drug/abacavir.html` | PASS | 4 个 chip 全对；全量 19 行，恢复 19 行；WARN 4 条 |
| 2 | `?view=table`（abacavir） | PASS | 带参数：矩阵 visible=True（h=1369px）、清单 False；不带：矩阵 False、清单 True |
| 3 | `#qgo` 提交 → `#meta` | PASS | `#meta` `''` → `'3 个名字命中 · 部分结果 —— 正在加载完整索引…'`；结果行 3 行 |
| 4 | 市场面板常显 + 两个深链 | PASS | `<div>` 813×167px、`display=block`、`summary=False`；`#country='CN'`；`#src='US'` |
| 5 | 语言切换 zh/en/es | PASS | 三语 `#h1` 各不相同；市场面板标签 zh='目标市场：看当地用什么名字（可选）' |
| 6 | ATC 说明行 ≤1 | PASS | `atc.html` / `atc/A.html` / `atc/R06A.html` 各 1 处（`atc/N02BE01.html` 不存在，脚本按「文件不存在就跳过」处理，故 3 条） |
| 7 | `<details>` 点开内容高 >0 | PASS ×8 | 4 个页面 × 2 视口（1280×900 / 390×844）全部通过；`index/drug/coverage` 各 6 个 details、`atc.html` 7 个；展开后内容高 ≤0 的 0 个 |

WARN 15 条全部来自第 1 项「chip 数字 vs 可见行数」的口径观察（例：`liquid 107` → 可见 14 行、`powder 44` → 可见 9 行、`injection 17` → 可见 1 行、`other forms 7` → 可见 0 行），**不是回归**，与 v0.11.1 的判定口径一致。

## 3. 首屏守卫 · 8 组数字（`site/dist` vs v0.11.1 基线）

跑法（与任务书一致）：

```powershell
& $py deploy/first_screen_check.py --dist site/dist --viewports 390x844,1440x900 `
    --pages home,results,drug,atc --json .tmp/v0113-fs/after.json `
    --baseline .tmp/first-screen/v0111-baseline.json
```

结果 JSON：`.tmp/v0113-fs/after.json`（`2026-11-11T12:47:33`，`metric_version=afcr-band-v2`，34.8s）

| 页面 | 视口 | AFCR | 带宽 | 条目 | chrome | 悬浮 | 正文 | 辅助 | <14px | 溢出 | 判定 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| home | 390x844 | 0.93 | 1.00 | 0.0 | 0.14 | 0.068 | 16px | 14px | 7% | 否 | ok |
| home | 1440x900 | 1.00 | 0.67 | 6.0 | 0.07 | 0.000 | 16px | 14px | 6% | 否 | ok |
| results | 390x844 | 0.87 | 1.00 | **0.5** | 0.19 | 0.068 | 16px | 13px | 5% | 否 | **未达**（items 0.5 < 3.0） |
| results | 1440x900 | 0.90 | 0.67 | 3.0 | 0.13 | 0.000 | 16px | 13px | 7% | 否 | ok |
| drug | 390x844 | 0.92 | 1.00 | 6.0 | 0.21 | 0.068 | 16px | 13px | 31% | 否 | ok |
| drug | 1440x900 | 1.00 | 0.67 | 8.5 | 0.15 | 0.000 | 16px | 13px | 36% | 否 | ok |
| atc | 390x844 | 0.93 | 1.00 | 7.5 | 0.14 | 0.068 | 16px | 13px | 4% | 否 | ok |
| atc | 1440x900 | 1.00 | 0.67 | 16.5 | 0.07 | 0.000 | 16px | 13px | 13% | 否 | ok |

**绝对门槛逐条**（v0.10.3 起的四项阻塞项）：

- 正文最小字号 ≥16px：8/8 组都是 16px ✓
- 辅助最小字号 ≥13px：8/8 组 13–14px ✓
- 全站最小字号（<12px 硬线）：8/8 组 `hard_min=13px` ✓（出处例：`home` 的 `span.n «1»`、`drug` 的 `span.ds-meta «10 个市场 · 12645 条记录»`、`atc` 的 `span.tag «L3»`）
- 无横向溢出：8/8 `overflow=0` ✓
- chrome ≤35%（结果页 ≤40%）：最大 `drug@390` 0.21 ✓
- 首屏条目 ≥5：`drug` 6.0 / 8.5、`atc` 7.5 / 16.5、`home@1440` 6.0 ✓；`home@390` 条目门槛为 0（入口页）；**`results@390` 0.5 < 3.0 ✗（既有项）**
- 汇总：`8 次扫描：1 组不达标、共 1 项未达（WARN 0），baseline 退化 9 项`（报告模式，退出码 0）

## 4. 退化项与归属（关键：9 项里只有 1 项是本版）

工具按「>5% 相对退化」判出 9 项。我把 v0.11.1 基线与 v0.11.2 的实测（`.tmp/first-screen/v0112-final.json`）、v0.11.3（本报告）三列并排，逐项定责：

| 页面×视口 | 指标 | v0.11.1 | v0.11.2 | **v0.11.3** | 归属 |
|---|---|---:|---:|---:|---|
| home 390 | hard_min | 14px | 13px | 13px | v0.11.2 已变 |
| **home 1440** | **items** | **9.0** | **9.0** | **6.0** | **本版引入** |
| results 390 | afcr | 0.930 | 0.880 | 0.873 | 两版都动（本版 −0.7pp） |
| results 390 | chrome | 0.135 | 0.182 | 0.188 | 两版都动（本版 +0.7pp） |
| drug 390 | items | 6.5 | 6.0 | 6.0 | v0.11.2 已变 |
| drug 390 | chrome | 0.135 | 0.206 | 0.206 | v0.11.2 已变 |
| drug 1440 | items | 9.5 | 8.5 | 8.5 | v0.11.2 已变 |
| drug 1440 | chrome | 0.073 | 0.147 | 0.147 | v0.11.2 已变（+100% 在 v0.11.2 就发生了） |
| atc 390 | items | 8.5 | 7.5 | 7.5 | v0.11.2 已变 |

### 4.1 本版唯一引入：`home@1440` 首屏类别格 9 → 6（−33.3%）

**直接原因**：task-35「目标/来源市场面板常显」——`#ctrydetails` 从折叠 `<details>`（一行 summary，约 46px）变成常显块 **167px**（1440 下 `top=327, h=167`），首页 `doc_h` 从 1299 → 1420（**+121px = 167 − 46**，数字对得上），`.catgrid a` 在首屏「完整可见」的格子从 9 → 6（少 3 个，每个 −1 条）。

- 复核命令：`& $py .tmp/v0113-fs/probe_chrome.py index.html 1440 900` → `#ctrydetails {'top': 327, 'h': 167, 'display': 'block'}`
- 判定建议：**可接受**。这是用户明确要求的「面板常显、不用点一下」的代价；AFCR 仍是 1.00、chrome 仍 0.07、首页条目门槛为 0（入口页，主操作 `#q` 完整可见且上沿 0.27 < 0.40）。若要两全，只能把类别格子压到 4.5 行以内或折叠面板（与本次需求冲突）。

### 4.2 其余 8 项：v0.11.2 已存在，不是本版引入

`drug` 页 chrome 翻倍的根因不在面板，而在**页头多了一行搜索条**：

```
== drug/acetaminophen.html @1440x900   header {'h': 130}
   header> div.wrap           top=  0 h= 64
   header> div.hsearch-row    top= 64 h= 65   '搜一个药名 →'
== index.html @1440x900               header {'h': 65}
   header> div.wrap           top=  0 h= 64
```

- v0.11.1：`header×1` = 66px → chrome 0.0733
- v0.11.2 起：`.hsearch-row` 常显 → `header×1` = 130px → chrome 0.1467（1440 与 390 同因，390 上把 `.mkrow` 首屏从 6.5 挤到 6.0）
- `git show HEAD:site/build.py` 里已有 `.hsearch-row`，即**该行是 v0.11.2 引入的**，v0.11.3 未改（`git diff site/build.py` 中无 `hsearch`）。
- `results@390` chrome 从 0.135 涨到 0.182 的主因同样是 v0.11.2：`.restools×1`（排序/导出工具条）进入首屏（v0.11.1 `chrome_hits=['header×1', '.tabbar×1']` → v0.11.2/3 多一个 `.restools`）。

**建议**（不在本工位写权限内，留给 Lead 排 task）：
1. 收盘 v0.11.1 → v0.11.2 的这 8 项是否接受过（`v0112-final.json` 的 baseline 对比记录未落 `reports/`，口径断档）；
2. 若要把 `drug` 页 chrome 压回 ≤15%，可选方向：`.hsearch-row` 在内容页收成一行（与页头 `nav.sn` 合并）或滚动时吸顶、首屏只留一行。

## 5. 复跑稳定性记录（重要：有三方并发）

本轮测量期间**另一工位正在跑 `deploy/ci_checks.py --jobs 1`**，它内部会同时启动 `deploy/ui_surface_check.py` 与 `deploy/first_screen_check.py`（对同一个 `site/dist` 各起一个 Chrome）。因此：

- 冒烟跑了约 **15 分钟**（正常约 1–2 分钟）；
- `results` 页条目数**不可复现**（它依赖 42.8 MB `data/idx/core.json` 加载完成，`_wait_ready` 对 results 的判据含 `#identity`，索引没加载完也会判 ready）。三次复跑实测：

| 轮次 | 时间 | results@390 items | results@1440 items | 备注 |
|---|---|---:|---:|---|
| 主表（任务书命令） | 12:47 | 0.5 | 3.0 | `after.json` |
| 复跑 2 | 12:50 | 0.0 | 0.0 | `doc_h` 与首页相同（2170/1420）= 搜索还没执行（`.tmp/v0113-fs/after-vs-v0112.json`） |
| 复跑 3 | 12:52 | 0.0 | 3.0 | 390 组 `band_ratio=0.67`（390 视口量到桌面内容带），采集受干扰（`.tmp/v0113-fs/results-r2.json`） |
| 复跑 4 | 12:53 | 0.5 | 3.0 | 2.3s 干净跑完，与主表一致（`.tmp/v0113-fs/results-r3.json`） |

结论：`results` 两项数字**取主表那一次**，并把「0.5/3.0」当成区间的一侧；`home` / `drug` / `atc` 六组在四轮里稳定不变（静态页面，不依赖索引）。要拿到可复现的 results 数字，建议单独在无并发时重跑，或把 results 的 ready 判据改成「`.res-skeleton` 消失且 `#reswrap tbody tr` 出现或 `#meta` 含命中数」（改 `first_screen_check.py`，不在本工位写权限内）。

## 6. 没跑 / 缺口

1. **第 7 项覆盖不到本版新增的 ATC 卡片 `<details>`**（盐型 / 状态）：`DETAILS_PAGES` 是 `index.html, drug/acetaminophen.html, coverage.html, atc.html`，而 task-39/40 的新组件在 `atc/R06A.html`、`atc/A.html` 这类成员页。建议下一版把 `atc/R06A.html` 加进 `DETAILS_PAGES`（会从 17 条变 19 条，故本轮未改）。
2. **第 6/7 项的「文件是否存在」判据用的是 `DEFAULT_DIST`（`site/dist`）而不是 `--dist` 参数**：本轮 `--dist site/dist` 恰好一致，所以没影响；但如果扫 `.tmp/xxx-build`，第 6/7 项会按 `site/dist` 的文件清单决定跳过哪些页（内容仍从 `--dist` 取，只是存在性判断错源）。属脚本既有缺陷，建议单独修。
3. **`results@390` 首屏条目 0.5 < 3.0 未修**：既有项（v0.11.1 = 0.0、v0.11.2 = 0.5），根因是「泰诺」只有 3 条命中 + 390 首屏放不下整行；需要产品决策（收窄结果行 / 允许半条计 0.5 视为达标），本工位不动门槛。
4. 未跑 `ci_checks.py` / 三语检索（另一工位正在跑，避免并发抢占；不属本 task 验收范围）。
5. WARN 15 条（chip 数字 vs 可见行数）是老口径问题，本版未变，仍按「写进报告、不阻塞」处理。
6. **`drug` 页的主操作 `filter-entry` 是空转的**：它探 `.matrix-filters`，而 v0.10.3 起成分页主视图已换成按国家分组清单，产物里 `.matrix-filters` **0 命中**（v0.11.1 / v0.11.2 / v0.11.3 三版 `found=False` 都一样）。现行筛选入口是 `.formchips`（已被 `form-chips` 那条覆盖），所以不影响判定，但该选项应删掉或改成 `.formchips`，否则以后真出问题也报不出来。

## 7. 复跑命令与证据文件

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 交互冒烟（17 项）
& $py deploy/ui_interaction_smoke.py --dist site/dist --json .tmp/v0113-fs/smoke.json
# 首屏守卫（8 组，报告模式）
& $py deploy/first_screen_check.py --dist site/dist --viewports 390x844,1440x900 `
    --pages home,results,drug,atc --json .tmp/v0113-fs/after.json `
    --baseline .tmp/first-screen/v0111-baseline.json
```

| 文件 | 内容 |
|---|---|
| `.tmp/v0113-fs/smoke.json` | 冒烟 17 项全量数据（`summary` = total 17 / pass 17 / fail 0 / warn 15） |
| `.tmp/v0113-fs/after.json` | 首屏 8 组原始数据（主表来源） |
| `.tmp/v0113-fs/after-vs-v0112.json`、`results-r2.json`、`results-r3.json` | 复跑稳定性证据 |
| `.tmp/v0113-fs/probe_chrome.py`、`probe_header.py` | 页头 / chrome 元素定位探针（见 §4） |
| `.tmp/v0113-fs/compare_fs.py`、`compare_v0112.py`、`compare_v0111_v0112.py` | 三版逐组对照脚本（可复核 §4 表格） |
| `.tmp/first-screen/v0111-baseline.json` | v0.11.1 基线（任务书指定） |
| `.tmp/first-screen/v0112-final.json` | v0.11.2 实测（用于定责） |

> 本工位未 commit / 未发布 / 未写 `site/dist`。脚本改动在 `deploy/ui_interaction_smoke.py`（第 4 项重写、第 5 项探针 2 行、`CHECKS` 标题），如需只保留第 4 项改动，按 §1.2 回退第 5 项即可。
