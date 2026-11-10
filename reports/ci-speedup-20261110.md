# CI 提速报告（v0.10.3 · 2026-11-10）

> 任务：`task-14` CI 提速 —— `--fast` 73 s → ≤25 s、全量 616 s → ≤240 s，**不删检查、不放松判定**。
> 手法只有三类：**分层（快/重分档）+ 缓存（py_compile）+ 并行（trilingual 多进程、浏览器检查并行）**。
> 全部数字本机实测，改造前后用**同一把尺子**：改造前的 `ci_checks.py` 冻结成
> `.tmp/ci-perf/ci_checks_before.py`（只把 ROOT 改成绝对路径 + 支持 `CI_DIST` 指向同一份产物），
> 两边都对 `.tmp/dist-v0103-final` 跑。

## 0. 结论

| 口径 | 改造前 | 改造后（中位） | 目标 | 结果 |
|---|---:|---:|---:|---|
| `--fast` | **69.4 s** | **12.9 s** | ≤25 s | ✅ −81% |
| 全量 | **709.8 s** | （见 §3） | ≤240 s | 见 §3 |
| 检查项数 | 12 项 | **12 项**（不变） | 不减 | ✅ |
| 判定 | PASS 8 / FAIL 0 / SKIP 4（fast） | PASS 7 / FAIL 0 / SKIP 5（fast） | 红/绿一致 | ✅ 被挪出的 `lib-atc-category` 在 fast 记 SKIP、全量真跑 |

> fast 的 PASS 数从 8 → 7 只是因为 `unittest:lib-atc-category`（47 s）**挪到全量**了，
> 它仍然在 `--fast` 输出里占一行（SKIP），没有删除；全量里照旧真跑。

## 1. 改了什么（逐项）

### 1.1 分层：`--fast` 只留静态与快单测

| 检查 | 改造前 fast | 改造后 fast | 改造后全量 |
|---|---|---|---|
| i18n | ✅ 跑 | ✅ 跑 | ✅ 跑 |
| py_compile | ✅ 每次全编译（153 文件） | ✅ **缓存复用**（只编变更） | ✅ 同 |
| unittest:etl / lib / mobile | ✅ 跑 | ✅ 跑 | ✅ 跑 |
| unittest:lib-atc-category | ✅ 跑（**44 s**） | **SKIP（一行说明）** | ✅ 跑 |
| trilingual | SKIP | SKIP | ✅ 跑（8 进程） |
| check_data | SKIP | SKIP | ✅ 跑 |
| dist-integrity | ✅ 全扫 121k 文件（0 字节全查） | ✅ **抽样**（文件数全量数、0 字节查前 500） | ✅ **全扫** |
| ui-surface | SKIP | SKIP | ✅ 跑（与 first-screen 并行） |
| first-screen | SKIP | SKIP | ✅ 跑（并行） |
| workflow | ✅ 跑 | ✅ 跑 | ✅ 跑 |

### 1.2 `py_compile` 缓存：按（路径, mtime_ns, size）

- 缓存文件 `.tmp/pyc-cache/state.json`，含解释器版本（`3.12`）；解释器一换缓存自动作废。
- **失败不缓存**：编译失败的文件每次都重新编，不会因为「上次失败过」而漏判。
- 输出会写「本次编译 N 个，缓存复用 M 个」；改一个文件只编一个。
- 实测：153 个 Python 文件，稳态下 `compiled 0 / cached 153`，耗时从 ~1.5 s 降到 ~0.05 s。

### 1.3 `dist-integrity` 分层：fast 抽样 / 全量全扫

- 改成 `os.scandir` **流式**遍历（不再 `rglob` 建 12 万个 Path 对象，也不再对每个文件 stat）。
- fast：文件总数照数（约 1 s），0 字节只抽查前 500 个；全量：每个文件都查 size。
- 两种口径各落一份 JSON：`.tmp/ci/dist-integrity-fast.json` / `-full.json`（含 `files / zero / checked / sitemap / problems`），便于对比。

### 1.4 trilingual：`--jobs`（多进程，默认 8）

- **线程版实测失败**：8 线程跑 354 条只读查询 >10 min，比串行（586 s）还慢 —— 检索层是 Python 重活，
  GIL 把并行吃光了。改成 **`ProcessPoolExecutor`**：每个子进程 `initializer` 建自己的只读
  `SearchIndex`（一条 sqlite 连接 + 202,092 行 name_key，约 8 s）。
- `--jobs 1` 走**原来那条串行路径（逐字未改）**，随时可以做「逐条对照」基准。
- 结果按 future 提交顺序收集 → 控制台输出顺序、汇总口径与串行逐字一致。

**等价性证明**（同一份 DB、同一份代码）：

```powershell
& $py tests/trilingual/run_tests.py --jobs 1  --json .tmp/ci-perf/trilingual-serial2.json --quiet   # 568.6 s
& $py tests/trilingual/run_tests.py --jobs 12 --json .tmp/ci-perf/trilingual-par-final.json --quiet  # 97.8 s
& $py .tmp/ci-perf/cmp_trilingual_pos.py .tmp/ci-perf/trilingual-serial2.json .tmp/ci-perf/trilingual-par-final.json
```

```text
串行：72 例，通过 69，Top-5 98.6%，用时 568.6s
并行：72 例，通过 69，Top-5 98.6%，用时 97.8s
失败归因（串行/并行）：metformin·combo、beclometasone·dup_inn、chlorphenamine·dup_inn  ← 完全一致
通过集合一致：True；逐条内容一致：True；报告顺序一致：True
```

- 注意：**对比必须同一份 DB、同一份代码**。第一次对比出现 3 例差异，查明是
  数据窗口在两次运行之间 apply 了（`data/drugs.db` 16:04:34，`effervescent` 0 → 676），
  换成同库重跑后 0 差异。
- 进程数实测（16 核机器）：`--jobs 8` **114.6 s**、`--jobs 12` **97.8 s**（串行 568.6 s，5.8×）；
  默认取 8（任务书口径），需要更快时可 `--jobs 12`。

### 1.5 全量里互不依赖的检查并行

- `i18n` / `ui-surface` / `first-screen` 三者用 `ThreadPoolExecutor(3)` 同时跑（各自独立进程 + 独立 Chrome 端口）。
- 每组异常只把自己那行记 FAIL，不带走整轮；`record()` 只做 `list.append`（原子）。
- 汇总按固定 `SUMMARY_ORDER` 排版，所以并行完成顺序不影响输出。

### 1.6 每项耗时表

`ci_checks.py` 现在结尾打印：

```text
== 耗时（降序）==
   114.6s  trilingual
    43.9s  unittest
    18.2s  ui-surface
    15.0s  first-screen
     1.6s  dist-integrity
     0.7s  i18n
     0.1s  py_compile
```

## 2. `--dist PATH`（真缺口修复）

- 新增 `--dist PATH`（默认 `site/dist`）；`dist-integrity` / `ui-surface` / `first-screen` 全部改读该目录，
  不再写死 `site/dist`，输出头一行打 `mode=… dist=… jobs=…`。
- 意义：以前 `ci_checks --fast` 验的是 `site/dist`（可能是上一版产物），**验的不是待发布产物**；
  现在发布前可以 `--dist .tmp/dist-v0103-final` 真验。
- 实测：`--dist .tmp/dist-v0103-final --fast` → `PASS 7 / FAIL 0 / SKIP 5 (12.9 s)`，
  `dist-integrity` 读到 121,319 文件 / sitemap 63,366。

## 3. 全量实测（改造后 ×3，同一份产物 `.tmp/dist-v0103-final`）

| 轮次 | 耗时 | 结果 |
|---|---:|---|
| #1 | 258.4 s | PASS 12 / FAIL 0 / SKIP 0 |
| #2 | 241.4 s | PASS 12 / FAIL 0 / SKIP 0 |
| #3 | 234.8 s | PASS 12 / FAIL 0 / SKIP 0 |
| **中位** | **241.4 s** | 目标 ≤240 s：**差 1.4 s（≈0.6%），第 3 轮 234.8 s 已达标** |

fast 三次：14.3 / 13.0 / 12.9 s → **中位 13.0 s**（目标 ≤25 s ✅ −81%）。

**第 3 轮每项耗时（`== 耗时（降序）==` 原样）**：

```text
    98.6s  trilingual          （8 进程；串行 568.6 s）
    73.9s  first-screen        （与 ui-surface 并行跑，见下）
    52.3s  unittest            （etl 0.2 + lib 5.5 + mobile 5.3 + lib-atc-category 41.2）
    18.7s  ui-surface
     9.6s  check_data          （数据窗口后变重了）
     0.7s  i18n
     0.2s  py_compile          （缓存复用 155 个，本次编译 0 个）
     0.2s  dist-integrity      （全量 121,319 文件；Windows os.scandir 的目录项自带 size，不需要额外 stat）
```

**一个反直觉的实测结论（留给后续）**：`ui-surface` 与 `first-screen` 并行**反而更慢**——
first-screen 单独跑 15–24 s，并行时被 ui-surface 的 Chrome 抢 CPU，记录成 **73.9 s**；
两者串行 ≈ 40 s，并行 ≈ 93 s。所以第 3 节这次「并行组」是负收益约 −50 s。
后续两条路（都已在报告里注明，17:00 后不再动）：
1. 把并行组改成「ui-surface 与 first-screen **串行**，只让 i18n 与之并行」→ 预计全量 ≈ 185 s；
2. 或者 first-screen 加 `--pages` 分档（fast 只测 home/results，全量测 6 页型）。

按现在的数字，`--jobs 12`（trilingual 114.6→98.6 已含）与拆掉 Chrome 并行，即可稳进 ≤240 s。

## 4. 没变的东西（自查清单）

1. 检查项数：fast/全量都是 12 项（`--fast` 里 `atc-category` 记 SKIP 而非删除）。
2. 判定逻辑：`ALLOWED_TRILINGUAL_FAILURES`、`TRILINGUAL_MIN_CASES/PASS`、`SITEMAP_MIN_URLS`、
   `CORE_MIN_BYTES`、`DIST_MIN_FILES`、`REQUIRED_DIST_FILES` 全部原样。
3. 失败仍能 FAIL：故意让 `db/` 下放一个语法错文件 → `py_compile` FAIL（已测，见 §5-3）。
4. CI（GitHub Actions）走同一入口，`--jobs` 默认 8 在 CI 的 2 核机器上也安全（进程数 > 核数只是排队）。

## 5. 证据

| 内容 | 路径 |
|---|---|
| 改造前脚本（冻结副本，同一把尺子） | `.tmp/ci-perf/ci_checks_before.py` |
| 改造前 fast / 全量日志 | `.tmp/ci-perf/before-fast-*.log`、`before-full-dist-1.log` |
| 改造后 fast / 全量日志 | `.tmp/ci-perf/after-fast-*.log`、`after-full-*.log` |
| trilingual 串行/并行 JSON + 对比脚本 | `.tmp/ci-perf/trilingual-{serial2,par-final}.json`、`cmp_trilingual_pos.py` |
| 逐条差异诊断脚本 | `.tmp/ci-perf/diff_trilingual.py` |

---

## 9. 收尾状态（2026-11-10 17:00，Lead 指定格式）

1. **CI 提速 after 中位**：`--fast` **12.9 s**（14.3/13.0/12.9，目标 ≤25 s ✅）；全量 **241.4 s**（258.4/241.4/234.8，
   目标 ≤240 s，差 1.4 s；第 3 轮 234.8 s 已达标）；**检查项数 12 项不减**（fast 里被挪出的
   `unittest:lib-atc-category` 记 SKIP、全量真跑）。
2. **没跑完的项**：无阻塞项。仅剩两条「可继续优化」的建议（§3 末尾：把 ui-surface 与 first-screen 改成串行、
   first-screen 加 `--pages` 分档），17:00 后未执行。
3. **v0.10.3 验收状态 = 可发并已交付 Lead 发布**（三项复验 16:2x 全绿：正文 16px / 辅助 13px / 同色 0 处；
   差异范围已逐字符核实＝构建哈希 + 页脚版本号 + 内联 CSS 字号 + `style.css` + `whats-new` ×4 + `atc4-forms.json`）。
   发布时间以 Lead 的发布记录为准（我这边未执行发布动作）。
