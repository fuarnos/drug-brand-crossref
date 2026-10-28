# 发布管线优化：gh-pages 增量提交（2026-10-29）

> 任务：task-94（发布经理 index-p1）。改动：`deploy/publish.ps1`（备份 `deploy/publish.ps1.bak`）。
> 目的：旧发布每次「干净临时仓库 + orphan commit + 强制推送」，导致每版上传完整 380–450 MB pack（upload ~1.4 Mbps → 30–40 min）。
> 结果：**v0.6.7 实测实际上传 27.55 MiB（全量树 416 MB，-93.4%），publish 总耗时 602 s**。

---

## 0. 结论（TL;DR）

| 指标 | 旧流程（v0.6.5 及以前） | 新流程（v0.6.7 实测） | 变化 |
|---|---:|---:|---:|
| 每版上传 | 完整 site tree（v0.6.5 实传 ~390 MB，v0.6.6+ 436 MB） | **27.55 MiB**（`Writing objects: 27.55 MiB`） | **-93.4%** |
| push 阶段耗时 | 30–40 min（1.4 Mbps 上限推算）/ v0.6.5 实测 publish 13.4 min 全量 | **93 s**（push，含压缩+上传） | -90% 左右 |
| publish 总耗时 | v0.6.5：13.4 min；推导 436 MB 全量约 35–40 min | **602 s（10.0 min）** | 436 MB 版约 **-70~75%** |
| gh-pages 历史 | 每次 1 个 orphan commit + force push | 线性历史，`HEAD` 在上一发布之上 fast-forward | 可正常 `git log` |
| 失败回滚 | 无自动；靠上一提交人工恢复 | `-AutoRollback`：force-push 上一 SHA + 等 Pages + 首页复验 | 自动化 |
| 保底路径 | — | `-FullPush` 一键回到旧全量流程（备份 `.bak` 同效） | 可回退 |

决定性优点：**未变文件复用已有 git 对象**；所有 HTML 虽然因 `?v=BUILD_V` 都变了，但相对上一版的 **thin delta 很小**，60,319 个变更文件最终只传 27.55 MiB。

---

## 1. 根因（旧流程为什么慢）

旧 `publish.ps1`：`site/dist` → 全新 `.tmp/pages-publish-*` → `git init` → 全量 add/commit（唯一一个 commit）→ `git push --force` 覆盖 `gh-pages`。

- 临时仓库里没有任何历史对象，push 时 git 无法对服务器已有对象做 thin delta（本地没有 base blob），只能上传**全部 57k–60k 个文件的新 blob**；每次发布等于重新上传整个站点。
- 每次还触发一次「390 MB 全量 repack/commit」，commit 阶段就要数分钟。
- `?v=BUILD_V` 让每次构建所有 HTML 都变，进一步放大变更面（但旧流程无论如何都是全量）。
- 实测上传带宽约 1.4 Mbps → 436 MB 需要 35–40 min，v0.6.5 的 390 MB 实测约 13 min（带宽波动/压缩率不同）。

---

## 2. 实现（`deploy/publish.ps1`，默认增量；`-FullPush` 为旧流程）

新增参数：`-FullPush`（旧全量流程）、`-CacheDir`（默认 `.tmp\publish-opt\gh-pages-cache`）、`-AutoRollback`。
默认流程：

1. **缓存更新**：若 cache 不存在 → 一次性 `git clone --branch gh-pages --single-branch`（v0.6.5 实测 57,848 文件，一次约数分钟，之后不再下载全树）；否则 `fetch origin gh-pages` + `checkout -f -B gh-pages origin/gh-pages` + `reset --hard` + `clean -fdx`。
2. **镜像**：`robocopy $Dist $CacheDir /MIR /XD <cache>\.git`（删除已下线页面、复制新页面）；`.nojekyll` 保持历史约定（存在但空）；随后重新统计 `site/dist`（文件数/最新 mtime/总字节）确认构建没在拷贝期间被改写。
3. **增量提交**：`git add -A` → `git diff --cached`；**无变化则直接退出**（幂等）；有变化则在 gh-pages HEAD 之上 `git commit`。禁用自动 gc/repack（`gc.auto=0`、`maintenance.auto=false`）——否则每版 commit 都会触发 390 MB 全量 repack。
4. **上传量预估**：`git pack-objects --stdout --revs --thin --delta-base-offset`（`new ^prev`）离线生成 thin pack 并记录字节数（就是 push 会传的量级）。
5. **push**：`git push --progress origin HEAD:refs/heads/gh-pages`（普通 fast-forward，不 force）；失败时 fetch 检查远端是否被并发移动，给出明确错误。
6. **验证**：保留原有「等 Pages build（按新 commit sha 匹配）→ 首页 200」；失败时（`-AutoRollback`）force-push 上一 SHA、等 Pages、复验首页 200，仍在 manifest/日志记录。
7. **manifest**：`.tmp\publish-opt\last-publish.json`（mode/version/prev_sha/new_sha/changed_files/shortstat/estimated_pack_bytes/elapsed/pages_url/ok）。
8. 所有 Step 带 `[N s]` 计时，便于每版记录瓶颈。

安全性保留不变：完整性检查（index.html、core.json ≥10 MB / legacy index.json ≥5 MB、文件数 ≥24,000、0 字节、构建进程未在跑、最新文件 ≥15 s）、staging 隔离与「拷贝后源目录未变」复核、Pages build 等待、首页检查、token 从 `.env`/环境变量读取（不打印）。

---

## 3. 验证证据

### 3.1 缓存镜像与已发布树完全一致（DryRun）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1 -DryRun
# 输出：
# files: 57,848   size: 389.8 MB   newest: ...
# previous gh-pages commit: e78d47f9…
# staged: 57,848 files
# no file changes vs the current gh-pages tree - nothing to publish
```

→ 以 v0.6.5（线上已发布树）为基准时**零变更**，证明 clone/mirror/`.nojekyll` 规范化与线上内容逐字节一致（不会引入意外 diff）。

### 3.2 pack 估算机制单测

在 cache 里对 `index.html` 加一行 → commit → `pack-objects --revs --thin` 生成 336 B pack（预期的小 delta）；随后 `reset --hard` 恢复基线。→ 估算命令（LF revs 输入、stderr 可见）工作正常。

### 3.3 v0.6.7 真实发布实测（线上生效）

| 阶段（日志时间戳） | 耗时 | 说明 |
|---|---:|---|
| 检查 + release notes + cache fetch | 8 s | 缓存已存在，无全树下载 |
| 镜像 site/dist → cache（60,375 文件 / 416 MB） | 95 s | robocopy /MIR |
| `git add -A` + commit（60,319 文件变更） | **358 s** | 逐文件 hash+压缩写入 loose objects（当前最大瓶颈） |
| thin pack 估算 | 36 s | 预估 29.3 MB |
| push（压缩 60,244 对象 + 上传） | **93 s** | 实际 **27.55 MiB**，约 2.5 MB/s |
| 等 Pages build + 首页 200 | 12 s | build 按新 sha 匹配 |
| **合计** | **602 s（10.0 min）** | 旧全量 436 MB 预计 35–40 min |

发布结果：gh-pages commit `b650b30fb`（在 `e78d47f9f` 之上 fast-forward）、homepage 200、`verify_live --expect-version v0.6.7` **32/32 通过**；变更 60,319 文件（+314,081/−189,672 行），上传 **27.55 MiB**。

### 3.4 回退/保底

```powershell
# 回到旧的全量发布流程（应急）：
powershell -File deploy\publish.ps1 -FullPush
# 或用备份文件整体回退：
Copy-Item deploy\publish.ps1.bak deploy\publish.ps1 -Force
```

### 3.5 v0.7.0 发布实测（第二次增量发布，TW/zh-Hant 上线）

| 阶段（日志时间戳） | 耗时 | 说明 |
|---|---:|---|
| 检查 + release notes + cache fetch | 6 s | 缓存已存在 |
| 镜像 site/dist → cache（60,375 文件） | 83 s | robocopy /MIR |
| git add -A + commit（60,222 文件变更） | 299 s | 仍为最大瓶颈 |
| thin pack 估算 | 44 s | 预估 12.16 MB |
| push（压缩 + 上传） | 123 s | 实际 **11.60 MiB**（约 94 KB/s） |
| 等 Pages build + 首页 200 | 2 s | — |
| **合计** | **557 s（9.3 min）** | 全量树 436.3 MB → 上传 **-97.3%** |

结果：gh-pages 3ce2b0353（在 650b30fb 之上 fast-forward），线上 v0.7.0，smoke 32/32 通过。
与 v0.6.7 对比：v0.6.7 变更 60,319 文件 / 上传 27.55 MiB / 602 s；v0.7.0 主要变更来自 ?v= 与 TW/zh-Hant 文案，delta 更小（11.60 MiB）。

v0.7.0 收尾记录（2026-10-29）：
- Release commit 88a047c10（main e578ee549 为其后的报告补记提交）；tag **v0.7.0** 已推送（annotated）；GitHub Release 已创建并 API 确认为 published / 非 draft：<https://github.com/fuarnos/drug-brand-crossref/releases/tag/v0.7.0>
- gh-pages 3ce2b0353（上一版 650b30fb 的 fast-forward 增量提交）；线上 smoke **32/32 通过**（0 failed / 0 warnings）
- 下一版起继续用默认增量流程；本地 cache 已自动刷新到 3ce2b0353，无需重新 bootstrap。

### 3.6 v0.7.1 发布实测（ATC 类目浏览）

| 阶段 | 耗时 |
|---|---:|
| 检查 + release notes + cache fetch | 4 s |
| 镜像 site/dist → cache（61,547 文件 / 446.2 MB） | 87 s |
| git add -A + commit（61,397 文件变更） | 311 s |
| thin pack 估算 | 44 s |
| push（压缩 + 上传） | 62 s（实际 **13.85 MiB**） |
| 等 Pages build + 首页 200 | 12 s |
| **合计** | **511 s（8.5 min）** |

结果：gh-pages 29fab5ecd，线上 v0.7.1，smoke 32/32；全量树 446.2 MB → 上传 **-96.9%**。三版增量实测：v0.6.7 27.55 MiB/602 s、v0.7.0 11.60 MiB/557 s、v0.7.1 13.85 MiB/511 s。

### 3.7 v0.8.0 / v0.8.1 发布实测

| 版本 | 变更文件 | 实际上传 | 全量树 | 总耗时 | 阶段（镜像/commit/估算/push） |
|---|---:|---:|---:|---:|---|
| v0.8.0 | 62,822 | **17.94 MiB** | 455.7 MB | 515 s | 89 / 300 / 46 / 72 s |
| v0.8.1 | 62,727 | **14.92 MiB** | 463.7 MB | 519 s | 90 / 318 / 44 / 60 s |

六版增量实测汇总：v0.6.7 27.55 MiB/602 s → v0.7.0 11.60 MiB/557 s → v0.7.1 13.85 MiB/511 s → v0.8.0 17.94 MiB/515 s → v0.8.1 14.92 MiB/519 s（全量树 390–464 MB，上传均 **-96% 左右**）。

### 3.8 Pages CDN 传播延迟与首页版本断言（v0.8.1 发现）

- v0.8.1 publish 完成时 homepage: 200 OK（仅校验标题），但**立即**跑 verify_live 仍读到 v0.8.0 页脚；约 90 s 后重跑才变成 v0.8.1（32/32 通过）。GitHub Pages 的 CDN 传播比 Pages build 完成再晚 1–2 分钟。
- 影响：publish 的「首页 200」不能证明线上已是新版本；若「publish 后立刻 smoke」会被误判为旧版本。
- 已修：deploy/publish.ps1 的 Test-Homepage 增加 ExpectVersion 参数，首页检查必须在响应中匹配 $Version（来自 CHANGELOG 顶部）才算通过（轮询 18×5 s）；回滚复验仍不校验版本（回滚目标版本号未知）。

---

## 4. 迁移注意 / 风险

1. **一次性 bootstrap**：首次增量发布会 clone 整个 gh-pages（v0.6.5 实测 57,848 文件，数分钟）。之后只 fetch 增量（版本提交），不再下载全树。缓存位于 `.tmp\publish-opt\gh-pages-cache`（`.tmp/` 已 gitignore，不占仓库体积）。
2. **历史从 orphan 变线性**：gh-pages 现在保留历史；`git log` 可追溯每版。远端只接受 fast-forward（脚本不再 force）；若别的进程强推过 gh-pages，脚本会检测到远端 SHA 变化并报错，重新运行即可（fetch+reset 后在新 HEAD 上提交）。
3. **缓存对象增长**：`gc.auto=0` 避免每版全量 repack，代价是 loose objects 累积（每版新增变更 blob，约 30–100 MB 未打包）。磁盘充足（本机 290+ GB）；需要时在空闲窗口手动 `git -C .tmp\publish-opt\gh-pages-cache gc`（会重打包 ~400 MB，几分钟）。不要在日常发布中自动 gc。
4. **旧 `.bak` 与 `-FullPush`**：两条保底路径都在；`-FullPush` 上传全量（30–40 min），仅用于增量链路故障/紧急回滚。
5. **自动回滚范围**：仅「Pages build 失败/首页非 200」时触发（`-AutoRollback`）；数据语义问题不自动回滚（仍由人/Lead 决策）。
6. **进一步优化**（后续可做，非本次范围）：
   - `site/build.py` 的 `?v=BUILD_V` 改为**内容哈希**（app.js/css 变了才换 URL）→ 大多数 HTML 字节不变，`git add` 只写少量新对象、pack 更小，**当前 358 s 的 add/commit 可大幅下降**（需 impl-lazyload 改 build.py，单独任务）。
   - 预估 pack 与真实 push 各压缩一次（重复 CPU）；可在 `-DryRun` 保留、正式发布时跳过预估（用 `--progress` 实测值即可）。
7. **测试边界**：本次首次上线即真实发布验证（v0.6.7 成功）；`-AutoRollback` 未在真实失败场景触发过（代码路径与旧流程同样的 Pages API/等待逻辑，风险低），首次 v0.7.0 发布继续观察。

---

## 5. 文件清单

| 路径 | 说明 |
|---|---|
| `deploy/publish.ps1` | 增量发布实现（默认）+ `-FullPush` 旧流程 + `-AutoRollback` + manifest + 阶段计时 |
| `deploy/publish.ps1.bak` | 改动前旧脚本备份（一键回退） |
| `.tmp/publish-opt/gh-pages-cache/` | 本地 gh-pages 镜像（一次性 bootstrap，之后只增量 fetch） |
| `.tmp/publish-opt/last-publish.json` | 最近一次发布的 manifest（v0.6.7：upload 预估 29.3 MB / 实际 27.55 MiB / 602 s） |
| `.tmp/publish-opt/dryrun-current.log` / `dryrun-matrix.log` / `pack-unit.*` | DryRun 与 pack 估算单测证据 |
| `reports/publish-incremental.md` | 本报告 |
