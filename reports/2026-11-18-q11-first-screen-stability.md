# Q11 首屏守卫读数不稳 → 稳定化 + CI 串行

> 日期：2026-11-18 · 工位：pages-deploy · 任务：共享任务 task-7（Q11）
> 改动：`deploy/first_screen_check.py`（稳定化：多轮取稳 / unstable / suspect）＋
> `deploy/ci_checks.py`（全量模式下 first-screen 独占机器跑，其余 Chrome 组仍并行）

## 结论先行

1. **读数现在可复现**：同一产物（`site/dist` = v0.13.5，今天 10:46 构建）**连跑 3 次，24 组指标逐项 0 差异、
   `unstable=0`、`suspect=0`**，每次 85.5–86.0 s（改前 73 s，+17%）。
2. **并行/独立两种模式读数一致**：8 个 CPU 占用进程 + `ui-surface` + `ui-sort` 同时跑（模拟全量 CI 的三套 Chrome），
   与 standalone 逐项 **0 差异**；`ci_checks` 全量里 first-screen 改为**独占机器**串行跑，其余两个 Chrome 组仍并行。
3. **门禁不再把「没量到」当 0**：多轮不一致 → 记 `unstable`（各指标取中位数、不判红、单独计数）；
   `items=0` 但选择器命中 >0 条 → 记 `suspect`（WARN，不判红）。两条路径都用合成页验证过会触发。
4. **坏产物仍判红**：把成分页 195 个 `.mkrow` 改名后（选择器失配 → `available=0`），`--gate` 仍
   **FAIL、退出码 1**，不会被 suspect 放过。
5. 本机没能复现 Lead 记的那种「条目 48.5→13 / 4.5→0」——三次加压尝试全部 0 差异（见 §5），
   所以这次修的是**机制**（原来只量一帧），不是打补丁骗过某一台机器。

## 1. 问题与根因

Lead / atc4-ui / 我三方证据（2026-11-16～18）：

| 现象 | 证据 |
|---|---|
| 三套 Chrome 并行时宽视口条目数回落 | `drug@1440 4.5→0`、`atc@2560 48.5→13`、`atc@390 7.5→0`、`coverage@2560 15→3.5`；单独复测即回基线 |
| 同一份 CSS 连跑两次差 6 项 | `items 0↔5.5`、`chrome 0.073↔0.105`、`aux_min 14↔13` |
| 三次全量 CI 结论不同 | 「6 组 6 项 / 3 组 3 项 / 3 组 3 项」 |

根因（读代码 + 现场探针确认）：**每个「页面 × 视口」只在 `Page.loadEventFired` 之后量一帧**，
休息时间写死（`_wait_ready` 对多数页型只 `sleep(0.45)`，其余是「等选择器出现 + 0.35s」）。
这一帧可能还没被 JS 调整完：站点首页/结果页的 `assets/app.js` 是 **`window.load` 之后才动态插入**的，
`initMkBlocks()`（只展开第一个市场块，其余 `details` 收起）、结果页 `render()`（core 索引到位后整块重绘）
都在那之后改 DOM；同时 CPU 被另外两套 Chrome 抢走时，排版/绘制提交得慢，首帧和稳定帧不是同一个布局。

探针（`.tmp/pages-deploy-q11/probe_timeline.py`）实测：`drug/acetaminophen.html` 在 load 时
`details(141 个, open=1)`、`.mkrow` 195 行、`doc_h=3461` —— 也就是说**服务器渲染的初始态本身是稳的**，
一旦 `app.js` 在那之后重排（或被别的进程拖慢），就会量到「另一套布局」，条目数随之跳变。
所以修法不是「等更久」，而是**量到不动为止**。

## 2. 改了什么（`deploy/first_screen_check.py`）

| 环节 | 改前 | 改后 |
|---|---|---|
| 量之前 | 固定 sleep（0.35–0.45s） | `SETTLE_JS`：禁动画/过渡/平滑滚动 → 滚回顶部 → `document.fonts.ready` → **等 DOM 静默**（220ms 无 mutation，上限 2.5s）→ 双 `rAF` |
| 量几次 | 1 次 | **连续 2 轮签名完全一致**才算稳（`--stable-rounds`）；不稳继续量，最多 5 轮（`--max-rounds`） |
| 不稳怎么办 | 记成 0 / 记成那一帧 | 记 `unstable`：**中位数**兜底（不取 0、不取最小），**不参与判定**，summary 单独计数并列出 |
| `items=0` | 一律判 `items` 未达 | 选择器命中 >0 条 → 记 `suspect`（只 WARN，需人工复核）；命中 0 条（真失配）仍判红 |
| 输出 | `fails` / `warns` | 保留原字段，新增 `unstable` / `suspect` / `stability{rounds,signatures,samples,settle_ms,...}` / `vh` / `scroll_y`；`summary` 新增 `unstable_scans/unstable_list/suspect_scans/suspect_list/ok_gate`；矩阵与逐行日志加 `[unstable]`/`[suspect]` 标记 |
| baseline 对比 | 拿不稳的读数也比 | 本轮 `unstable` 的组**跳过对比**并出一条「注意」 |
| 速度 | — | `MEASURE_JS` 两处「先取 `getComputedStyle` 再判几何」改成**先判几何/是否在首屏、再取样式**（语义不变），把多轮测量的成本压回来 |

**向后兼容**（两个调用方：`ci_checks.py` 与工位自验脚本）：
`--json` / `--baseline` / `--pages` / `--viewports` / `--dist` / `--gate` / `--shots` / `--scroll-probe` /
`--expand` / `--rows-selector` / `--table-view-probe` 语义**全不变**，旧 JSON 字段一个没改名；
新增只有：`--stable-rounds` / `--max-rounds` / `--settle-ms` / `--override`（验证坏产物用）和上面那些新字段。
`--gate` 退出码只由 `fails` + baseline 退化决定，`unstable` 不算红（会单独打一行 WARN 提醒复跑）。

实测兼容性：拿**改前**的 JSON 当 `--baseline` 跑改后脚本，比对正常执行（本次只扫 2 组、baseline 有 24 组，
所以报了 22 条「baseline 有但本轮没扫到」——这是原有语义，不是新问题），旧字段解析无异常。

判定口径没动：阈值、选择器、AFCR v2 算法、`items` 半条（0.5）口径、字号/溢出/悬浮判定全部原样。

## 3. 改了什么（`deploy/ci_checks.py`）

全量模式的 Chrome 组从「三套并行」改成「**first-screen 独占 → 另两套并行**」：

```diff
-        _run_parallel([("i18n", …), ("ui-surface", …), ("first-screen", …), ("ui-sort", …)])
+        # Q11：first-screen 先独占机器跑（三套 Chrome 并行时它会量到中间态）
+        check_first_screen(args.verbose)
+        _run_parallel([("i18n", …), ("ui-surface", …), ("ui-sort", …)])
```

`--fast` 行为不变（first-screen 照旧记 SKIP，13 项 / 12.9 s 实测）。`check_first_screen()` 的明细行
现在会带上「不稳定 N 组 / 疑似 N 组」（有才打），CI 里一眼能看见。

## 4. 验收：改前 / 改后数字

### 4.1 三次连跑逐项一致（同一产物，standalone）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
foreach ($i in 1..3) { & $py deploy/first_screen_check.py --json ".tmp/pages-deploy-q11/run-$i.json" }
```

| 轮次 | 24 组差异 | unstable | suspect | 不达标组/项 | 耗时 |
|---|---|---|---|---|---|
| run-1 | — | 0 | 0 | 3 组 / 3 项（沿用基线缺口） | 85.6 s |
| run-2 | **0** | 0 | 0 | 3 组 / 3 项 | 86.0 s |
| run-3 | **0** | 0 | 0 | 3 组 / 3 项 | 85.5 s |

> 3 组不达标是**存量**（`drug@1440` items 4.5<5、`coverage@390` 1.5<5、`coverage@768` 3.5<5），
> 与改前完全相同（改前 `before-run.json` 也是 3 组 3 项）——说明稳定化没有掩盖或制造问题。

### 4.2 并行模式 vs standalone（8 个 CPU 占用 + 两套 Chrome）

| 对比 | 24 组差异 |
|---|---|
| 改前 standalone ↔ 改前 + 压力 | 0 |
| 改后 standalone（run-1）↔ 改后 + 压力（`after-stress.json`） | **0** |
| 改前 standalone ↔ 改后 standalone | **0**（数值口径没变） |

> 诚实记录：本机（16 逻辑核）三次加压都没能复现 Lead 记的条目回落，说明那是**机器/时序敏感**的问题。
> 所以本报告把「可复现性」落在机制层（§4.3 的合成页 + §4.1 的三连跑），而不是宣称「修好了某台机器的抖」。

### 4.3 新路径都验证会触发（合成页，`.tmp/pages-deploy-q11/make_synth_pages.py`）

| 合成页 | 造法 | 实测 |
|---|---|---|
| 不稳定 | 每 150ms 把前 8 行 `hidden` 来回切 | `[unstable 3 轮]`，样本 `items=[4.5, 4, 4.5]` → 取中位数 4.5、**不判红**、`不stable 1 组`、exit 0、24.5 s |
| 疑似 | `.mkblock{display:none}`（命中 195 条、首屏 0 条） | `[suspect]`，WARN「items 0 但选择器命中 195 条」、**不判红**、exit 0 |
| 坏产物 | 195 个 `class="mkrow"` 改名 `mkrow-broken`（选择器失配） | `FAIL`、`items 0.0 未达 5`、**exit 1**（`--gate`） |

```powershell
& $py deploy/first_screen_check.py --pages drug --viewports 1440x900 --max-rounds 3 `
    --override "drug/acetaminophen.html=.tmp/pages-deploy-q11/drug-unstable.html"
& $py deploy/first_screen_check.py --pages drug --viewports 1440x900 `
    --override "drug/acetaminophen.html=.tmp/pages-deploy-q11/drug-suspect.html"
& $py deploy/first_screen_check.py --pages drug --viewports 1440x900 --gate `
    --override "drug/acetaminophen.html=.tmp/pages-deploy-q11/drug-bad.html"
```

### 4.4 全量 CI（`ci_checks.py`，first-screen 独占跑）

```powershell
& $py deploy/ci_checks.py        # 日志：.tmp/pages-deploy-q11/ci-after.log
```

实测（改后）：

| 项 | 改前（`ci-before.log`，三套 Chrome 并行） | 改后（`ci-after.log`，first-screen 独占） |
|---|---|---|
| first-screen 结论 | 24 次扫描，3 组不达标、3 项 | 24 次扫描，3 组不达标、3 项（**同一组、同一项**） |
| first-screen 耗时 | 73.9 s（与另两套 Chrome 并行） | 85.9 s（独占） |
| unstable / suspect | 旧版没有这两个概念 | **0 / 0** |
| 全量总耗时 | 259.1 s | **287.3 s**（+28 s；仍远低于 10 分钟预算） |
| 全量 13 项 | PASS 13 / FAIL 0 | **PASS 13 / FAIL 0** |

并且把全量 CI 里那一次的 `.tmp/first-screen/ci.json` 跟 standalone 的 `run-1.json` 逐项比：
**24 组 0 差异** —— 「CI 里跑的」和「单独复测的」现在是同一组数字，不再需要「改前×2 / 改后×2 取包络 + standalone 复测」那套兜底。

## 5. 本机为什么复现不出来（诚实记录）

三次加压都试过，全部 24 组 0 差异：

1. `ui-surface` + `ui-sort` 并行（三套 Chrome，模拟全量 CI）；
2. 再加 **8 个 CPU 占用进程**（模拟 trilingual 的 8 线程）；
3. 把测量退回「单帧模式」（`--settle-ms 0 --stable-rounds 1 --max-rounds 1`）再比：仍 0 差异。

这说明：**这台机器上页面在首帧就已经是最终布局**（静态 HTML + 内联 CSS + 无 webfont），所以旧写法也没抖；
Lead 那边抖，是因为同一时刻还有 R2 上传 / 构建 / 其它 Chrome 在抢资源，首帧未必是最终帧。
稳定化不依赖「复现某一次抖动」——它保证的是「量到不动为止 + 量不到就明说」，这在快机器上只是多花 12 秒，
在慢机器/并发机器上才是救命的那一步。

## 6. 已知限制 / 缺口

1. **耗时 +17%**：24 组从 73 s → 85.5 s（多测一轮 + 静默等待）；全量 CI 因为 first-screen 改为独占，
   总时长会从 ~260 s 涨到 ~330 s（仍远低于 10 分钟预算）。若赶时间可用 `--stable-rounds 2 --max-rounds 2`，
   但**不建议**再退到 1 轮（那就退回旧行为）。
2. **unstable 不阻塞**：这是有意的（没量到 ≠ 产品退化）。`--gate` 下会单独打 WARN；需要「量不稳就红」的话，
   在 ci_checks 里把那行 WARN 改成 FAIL 即可（一行改动）。
3. **suspect 不阻塞**：`items=0` 且选择器命中 >0 一律只 WARN。真回归（例如新模板让首屏一条放不下）
   也会落进 suspect，需要人看截图；`available=0`（选择器失配）仍判红，这条没放松。
4. **`--override` 只用于验证门禁**（补丁页），正式验收仍扫构建产物。
5. **静默等待上限 2.5 s**：页面若持续动画/轮询（例如未来加了实时刷新），会稳定地判 `unstable` 而不是给假数——
   这是期望行为，但也意味着那种页面要单独调 `--settle-ms/--max-rounds`。
6. **没动的**：`deploy/ui_surface_check.py`（同色守卫）与 `deploy/ui_sort_smoke.py`（排序冒烟）不在本次范围；
   它们的判定不依赖「首帧时序」（前者比颜色、后者等 `IDX_READY`），所以没跟着改。

## 7. 复现清单

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py deploy/first_screen_check.py --json .tmp/fs.json                  # 主命令（24 组，~85s）
& $py deploy/first_screen_check.py --pages drug --viewports 1440x900    # 单组排查
& $py deploy/first_screen_check.py --baseline .tmp/fs-before.json       # 退化对比（不稳组自动跳过）
& $py deploy/first_screen_check.py --settle-ms 0 --stable-rounds 1 --max-rounds 1   # 退回旧行为（对照用）
& $py deploy/ci_checks.py                                              # 全量 CI（first-screen 独占）
& $py deploy/ci_checks.py --fast                                       # 快检（first-screen 记 SKIP）

# 合成页（验证新路径会触发；页面在 .tmp/ 里，可随时重做）
& $py .tmp/pages-deploy-q11/make_synth_pages.py
& $py .tmp/pages-deploy-q11/make_bad_page.py
```

## 8. 涉及文件

- 修改：`deploy/first_screen_check.py`（稳定化 + unstable/suspect + 两处测量提速；旧字段/旧语义不动）
- 修改：`deploy/ci_checks.py`（全量模式 first-screen 独占 + 明细行带不稳定/疑似计数；`--fast` 不变）
- 证据（不入库）：`.tmp/pages-deploy-q11/{run-1..3,before-run,before-stress,after-stress,first-frame}.json`、
  `ci-before.log`、`ci-after.log`、`probe_timeline.py`、`make_synth_pages.py`、`make_bad_page.py`
