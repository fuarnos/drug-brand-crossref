# v0.11.2 备份通道发布报告（gh-pages）

- 工位：`pages-deploy`（任务板 `task-19`）
- 执行：2026-11-12 02:46:57 → 03:04:26 北京（America/Los_Angeles 2026-11-11 10:46:57 → 11:04:26）
- 结果：**成功**，gh-pages 已上线 **v0.11.2**；commit `8d5c3a60d7f6e8b9271d25a405e61ed238ea01a5`；Pages build **`1361026906` built**（81,415 ms）；备份冒烟 6/6 PASS；**0 失败 / 0 重试**。
- 入口：`powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1`（唯一入口，未手工推 gh-pages）。
- 日志：`.tmp\publish-v0112.log`（全文）；manifest：`.tmp\publish-opt\last-publish.json`。

## 0. 结论

| 项 | 值 |
|---|---|
| 版本 / 日期 | **v0.11.2 · 2026-11-12**（CHANGELOG 第一节） |
| gh-pages 新 sha | **`8d5c3a60d7f6e8b9271d25a405e61ed238ea01a5`** |
| 上一版 sha | `ec99a135527cf20005afbbc657bf2919449d0eee`（v0.11.1） |
| 模式 | incremental（增量提交 + 快进推送） |
| 时长 | **1,048.7 s（17m29s）**，其中 push 139 s、Pages 构建 81 s |
| 增量 | **112,801 文件**（453,038 insertions / 453,891 deletions） |
| 推包 | **29,292,174 B（27.94 MB，thin）**；对端 delta **111,588** / 本地对象 **57,131** |
| Pages | build **`1361026906`**，`status=built`，`build_type=legacy`，**81,415 ms** |
| 备份冒烟 | 首页 200 / 页脚 v0.11.2 / whats-new 顶部 v0.11.2 / robots+sitemap 指主域（预期） |
| 失败 / 重试 | **0 / 0** |

## 1. 前置核对（开工时现查）

| 项 | Lead 宣布 / 期望 | 本机现查 | 结论 |
|---|---|---|---|
| dist 文件数 | 121,450 | **121,450** | ✅ |
| dist 字节 | 901,613,979 B | **901,553,420 B** | ⚠️ **−60,559 B（−0.0067%）**，见 §7 |
| sitemap 条数 | 63,685 | **63,685**（全部 `https://drugcrossref.com/`，旧域 0 处） | ✅ |
| 0 字节文件 | 0 | 0 | ✅ |
| dist 最新 mtime | 构建已结束 | `2026-11-11 10:37:28`（比开工早 9 分 29 秒，稳定） | ✅ |
| build/run_all 进程 | 无 | **无** | ✅ |
| CHANGELOG 顶部 | v0.11.2 | `## v0.11.2 — 2026-11-12` + 5 条 | ✅ |
| gh-pages 缓存 | 可增量 | `112,810` 松散对象 / 225,988 KB / 1 pack | ✅（未触发 30 万阈值） |
| 远端 gh-pages | v0.11.1 | `ec99a135527`（与本地缓存 HEAD 一致） | ✅ |

> 说明：publish.ps1 打印的 `size: 859.8 MB` 是 MiB（901,553,420 / 1,048,576 = 859.87），不是十进制 MB。

## 2. 时间线

| 时刻（北京） | 相对开始 | 步骤 | 本步耗时 |
|---|---|---:|---:|
| 02:46:57 | 0 s | 启动 `publish.ps1`；检查本地构建（121,450 文件，最新 10:37:28） | 7 s |
| 02:47:04 | 7 s | 解析 CHANGELOG → v0.11.2 / 2026-11-12（5 条 release notes） | 0 s |
| 02:47:04 | 7 s | 更新 gh-pages 缓存（fetch → checkout → reset --hard → clean） | 6 s |
| 02:47:10 | 13 s | robocopy /MIR `site/dist` → 缓存工作树（staged 121,450） | 151 s |
| 02:49:41 | 164 s | `git add -A` + commit（`112,801 files changed`） | **565 s** |
| 02:59:06 | 729 s | 估算 thin push pack → **27.94 MB**（全树 859.8 MiB） | 98 s |
| 03:00:44 | 827 s | `git push` → `ec99a135527..8d5c3a60d7f`（增量） | 139 s |
| 03:03:03 | 966 s | 等 GitHub Pages 构建：`building` ×8 → `built`（build `1361026906`，81,415 ms） | 81 s |
| 03:04:25 | 1,048 s | 首页校验：**200 OK，version v0.11.2** | 1 s |
| 03:04:26 | 1,049 s | 结束（exit 0） | — |

**瓶颈**：`git add -A` + commit 占 565 s（54%）；push 只 139 s。松散对象 22 万时**提交阶段**也明显变慢，不只是 push——下一版前建议落地 loose-object 守卫（见 §8）。

## 3. 发布数字（manifest 现查）

```json
{
  "mode": "incremental",
  "version": "v0.11.2",
  "previous_sha": "ec99a135527cf20005afbbc657bf2919449d0eee",
  "gh_pages_sha": "8d5c3a60d7f6e8b9271d25a405e61ed238ea01a5",
  "changed_files": 112801,
  "shortstat": "112801 files changed, 453038 insertions(+), 453891 deletions(-)",
  "estimated_pack_bytes": 29292174,
  "elapsed_s": 1048.7,
  "pages_url": "https://fuarnos.github.io/drug-brand-crossref/",
  "ok": true
}
```

发布树：`git ls-tree -r HEAD | wc -l` = **121,450**（与 dist 一致；`.nojekyll` 按发布惯例写成 0 字节）。

## 4. Pages 构建状态（`deploy\pages_status.ps1 -Wait -MaxMinutes 30`）

```
Pages: status=built build_type=legacy source=gh-pages/ https_enforced=True
build 1361026906 status=built commit=8d5c3a60
  created=2026-11-11T19:03:03Z updated=2026-11-11T19:04:24Z duration=81415ms
```

历史对照：v0.11.1 `1358744477` 100,449 ms；v0.11.0 `1358121259` 101,298 ms。本版 **81,415 ms**（更快，无异常）。

## 5. 备份冒烟（按要求只做 gh-pages，不跑全量 `verify_live`）

请求均带时间戳破缓存；本机可直连 gh-pages。

| 检查 | 结果 |
|---|---|
| `https://fuarnos.github.io/drug-brand-crossref/` | **200**，130,166 B，标题含 Medicine Brand Cross-Reference |
| 页脚版本 | **v0.11.2 · 2026-11-12** |
| `whats-new.html` | **200**，顶部 `<h2>` **v0.11.2**，正文含 v0.11.2 |
| `robots.txt` | **200**，`Sitemap: https://drugcrossref.com/sitemap.xml`（**主域，预期**） |
| `sitemap.xml` | **200**，**63,685** 条 `<loc>`，全部 `https://drugcrossref.com/`（**主域，预期**） |
| `canonical`（首页） | `https://drugcrossref.com/`（**主域，预期**） |

> 按 `AGENTS.md` §6 与交接 §5：gh-pages 自本版起只作备份，其 robots/sitemap/canonical 指主域是**预期行为**，因此**不跑全量 `verify_live`**（其 `robots` 断言会用 base 拼 sitemap 地址，必然误报）。备份通道冒烟只覆盖「首页 200 + 版本一致」。

## 6. 失败 / 重试

- **0 次失败、0 次重试**。
- 日志里有一条 `NativeCommandError`（`Enumerating objects: …`）：这是 PowerShell 把 `git push` 的进度 stderr 当错误记录，**不是失败**；随后 `pushed: gh-pages (incremental)`、`homepage: 200 OK (version v0.11.2)` 均正常。
- 中断安全：push 前本地提交已生成（`8d5c3a60`），远端此前一直是 `ec99a135527`，无半推风险；本次一次成功。

## 7. 冻结核对与一处数字差异

- 发布前后 `site/dist` 未被修改：**121,450 文件 / 901,553,420 B / 0 字节 0 / 最新 mtime 10:37:28**（发布后复测一致）。
- **差异**：Lead 宣布冻结值为 **901,613,979 B**，本机（发布前后两次）均测得 **901,553,420 B**，差 **60,559 B**；文件数（121,450）与 sitemap（63,685）完全一致。
  - 已排除：0 字节文件、构建进程；`.nojekyll`（58 B）与其它文件都在统计内（`-Force` 与不带 `-Force` 同值），最新 mtime 停在 10:37:28，未再变动。
  - 可能来源：Lead 的数字取自最终构建完成前的某一瞬间，或另一份副本（如确定性二次构建）的统计口径。
  - **不影响本次发布**：`publish.ps1` 自己复核了文件数/最新 mtime/总字节，且发布于 10:47 后 dist 未变。建议 Lead 在 v0.11.2 发布报告 / R2 报告里以**现查 901,553,420 B** 为准，或注明差异来源，避免两通道数字对不上。

## 8. 缺口 / 下一步

1. **缓存已到 225,625 松散对象 / 465,231 KB**（push 不改本地松散对象；本版 `git add` 后就是这个量级）。下一版 push 前将约 **33.8 万 > 30 万阈值** → **建议下次发布前落地 `publish.ps1` loose-object 守卫**（方案见 [`2026-11-12-v0116-r2-closeout-plan.md`](2026-11-12-v0116-r2-closeout-plan.md) §5；本版按 Lead 指令未改脚本、未额外 repack）。
2. **tag / GitHub Release 未做**（不在本任务范围）：源文件仍有未提交改动（`git status` 多文件），按 §6 由 Lead 提交后 `git tag -a v0.11.2` + Release（正文用 CHANGELOG 一节）。
3. **R2 主域**由 `phaseb-data` 并行上传（本工位未跑 `sync_r2.ps1`，未验证 R2 侧；其发布门槛应为主域 `verify_live`）。
4. **回滚参考**：上一版 gh-pages = `ec99a135527`（v0.11.1）；回滚要人拍板，按 §6 用 `publish.ps1 -AutoRollback` 或重新发布上一 tag 产物，不手工推。

## 9. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 前置
Get-ChildItem site\dist -Recurse -File | Measure-Object Length -Sum
& $py -c "s=open('site/dist/sitemap.xml',encoding='utf-8').read();print(s.count('<url>'),s.count('fuarnos.github.io'))"
& .\tools\git\cmd\git.exe ls-remote origin gh-pages

# 发布（唯一入口；本报告即此命令的输出）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1

# Pages 状态（需显式 Bypass，直接 & 调用会被执行策略拦）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\pages_status.ps1 -Wait -MaxMinutes 30 -History 3

# 备份冒烟
& $py .tmp\smoke_ghpages_v0112.py

# 发布后核对
Get-Content .tmp\publish-opt\last-publish.json
& .\tools\git\cmd\git.exe -C .tmp\publish-opt\gh-pages-cache count-objects -v
```

## 10. 日志摘录（关键行）

```
==> [0s] Checking local build
files: 121,450   size: 859.8 MB   newest: 2026/11/11 10:37:28
==> [7s] Release notes: v0.11.2 - 2026-11-12
==> [164s] Committing changes on top of gh-pages
changed: 112,801 files (112801 files changed, 453038 insertions(+), 453891 deletions(-))
commit: 8d5c3a60d7f6e8b9271d25a405e61ed238ea01a5
==> [729s] Estimating the incremental push pack
estimated push pack: 27.94 MB (thin, vs 859.8 MB full tree)
==> [827s] Pushing incremental commit to gh-pages
To https://github.com/fuarnos/drug-brand-crossref.git
   ec99a135527..8d5c3a60d7f  HEAD -> gh-pages
pushed: gh-pages (incremental)
==> [966s] Waiting for the GitHub Pages build
build 8d5c3a60 built
==> [1,048s] Checking the homepage
homepage: 200 OK (version v0.11.2)
Done. https://fuarnos.github.io/drug-brand-crossref/
```
