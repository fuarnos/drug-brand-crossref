# v0.11.3 备份通道发布报告（gh-pages）

- 工位：`pages-deploy`（任务板 `task-51`）
- 执行：2026-11-12 05:06:52 → 05:24:28 北京（America/Los_Angeles 2026-11-11 13:06:52 → 13:24:28）
- 结果：**成功**，gh-pages 已上线 **v0.11.3**；commit `9c802bdfba26fb838681b81ae916967a01f4e5f6`；Pages build **`1361296242` built**（80,512 ms）；备份冒烟 PASS；**0 失败 / 0 重试**。
- 入口：`powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1`（唯一入口，未手工推 gh-pages）。
- 日志：`.tmp\publish-v0113.log`；manifest：`.tmp\publish-opt\last-publish.json`。
- 说明：R2 主域由 `phaseb-data` 并行上传；本次未跑 `sync_r2.ps1`、未跑全量 `verify_live`、**未打 tag**（等 Lead 确认 R2 verify 31/31）。

## 0. 结论

| 项 | 值 |
|---|---|
| 版本 / 日期 | **v0.11.3 · 2026-11-12**（CHANGELOG 第一节） |
| gh-pages 新 sha | **`9c802bdfba26fb838681b81ae916967a01f4e5f6`** |
| 上一版 sha | `8d5c3a60d7f6e8b9271d25a405e61ed238ea01a5`（v0.11.2） |
| 模式 | incremental（增量提交 + 快进推送） |
| 时长 | **1,055.7 s（17m36s）**；push 115 s、Pages 构建 80 s |
| 增量 | **112,796 文件**（269,754 insertions / 268,939 deletions） |
| 推包 | **28,135,344 B（26.83 MB，thin）**；传输 112,810 objects / 26.83 MiB（2.43 MiB/s） |
| 发布树 | `git ls-tree -r HEAD` = **121,450**（与 dist 一致） |
| Pages | build **`1361296242`**，`status=built`，`build_type=legacy`，**80,512 ms** |
| 备份冒烟 | 首页 200 / 页脚 v0.11.3 / whats-new 顶部 v0.11.3 |
| 失败 / 重试 | **0 / 0** |

## 1. 前置与「先 repack 再发布」

| 项 | 实测 |
|---|---|
| dist 冻结 | **121,450 文件 / 920,332,551 B / 0 字节 0**；最新 mtime `2026-11-11 12:26:54`（发布前后一致） |
| build/run_all 进程 | 无 |
| 远端 gh-pages | `8d5c3a60`（v0.11.2），与本地缓存 HEAD 一致 |
| 缓存松散对象 | **225,625**（v0.11.2 发布后累积；本次发布将再加约 11 万 → 预估 ~33.8 万，超过事故报告 30 万阈值） |

**处置（主动、只动 `.tmp` 缓存，不改远端）**：

```powershell
& $git -C .tmp\publish-opt\gh-pages-cache repack -d -q --threads=4
```

| 项 | 前 | 后 |
|---|---:|---:|
| 松散对象 | 225,625 | **0** |
| 松散体积 | 465,231 KB | 0 |
| pack 数 | 1 | 2（size-pack 1,160,968 KB） |
| 耗时 | — | **310.7 s（5m11s）** |

> 依据 [`2026-11-11-发布卡点-gh-pages缓存松散对象.md`](2026-11-11-发布卡点-gh-pages缓存松散对象.md)：244 万松散对象曾让 push 卡 1h50m。本次发布前主动 repack，push 阶段只 115 s、无卡顿。`publish.ps1` 的 loose-object 守卫仍未落地（方案见 [`2026-11-12-v0116-r2-closeout-plan.md`](2026-11-12-v0116-r2-closeout-plan.md) §5），下一个版本前建议落地。

## 2. 时间线

| 时刻（北京） | 相对开始 | 步骤 | 本步耗时 |
|---|---|---:|---:|
| 05:06:52 | 0 s | 启动 `publish.ps1`；检查本地构建（121,450 文件 / 877.7 MiB / 最新 12:26:54） | 7 s |
| 05:06:59 | 7 s | 解析 CHANGELOG → v0.11.3 / 2026-11-12（5 条 release notes） | 0 s |
| 05:06:59 | 7 s | 更新缓存（fetch → checkout → reset → clean） | 4 s |
| 05:07:03 | 11 s | robocopy /MIR（staged 121,450） | 154 s |
| 05:09:37 | 165 s | `git add -A` + commit（112,796 files changed） | **610 s** |
| 05:19:47 | 775 s | 估算 thin push pack → **26.83 MB** | 83 s |
| 05:21:10 | 858 s | `git push` → `8d5c3a60..9c802bdf`（增量） | **115 s** |
| 05:23:05 | 973 s | 等 Pages 构建：`built`（build `1361296242`，80,512 ms） | 82 s |
| 05:24:27 | 1,055 s | 首页校验：**200 OK，version v0.11.3** | 1 s |
| 05:24:28 | 1,056 s | 结束（exit 0） | — |

瓶颈：`git add -A` + commit 占 610 s（58%）；push 仅 115 s（repack 生效）。

## 3. 发布数字（manifest 现查）

```json
{
  "mode": "incremental",
  "version": "v0.11.3",
  "previous_sha": "8d5c3a60d7f6e8b9271d25a405e61ed238ea01a5",
  "gh_pages_sha": "9c802bdfba26fb838681b81ae916967a01f4e5f6",
  "changed_files": 112796,
  "shortstat": "112796 files changed, 269754 insertions(+), 268939 deletions(-)",
  "estimated_pack_bytes": 28135344,
  "elapsed_s": 1055.7,
  "pages_url": "https://fuarnos.github.io/drug-brand-crossref/",
  "ok": true
}
```

push 进度：`Enumerating objects: 171,468` / `Writing objects: 112,810 (26.83 MiB, 2.43 MiB/s)`。

## 4. Pages 构建

```text
Pages: status=built build_type=legacy source=gh-pages/ https_enforced=True
build 1361296242 status=built commit=9c802bdf
  created=2026-11-11T21:23:05Z updated=2026-11-11T21:24:25Z duration=80512ms
```

历史对照：v0.11.2 `1361026906` 81,415 ms；v0.11.1 `1358744477` 100,449 ms。本版 80,512 ms，正常。

## 5. 备份冒烟（只做 gh-pages；不跑全量 `verify_live`）

请求均带时间戳破缓存。

| 检查 | 结果 |
|---|---|
| `https://fuarnos.github.io/drug-brand-crossref/` | **200**，133,561 B，标题含 Medicine Brand Cross-Reference |
| 页脚版本 | **v0.11.3 · 2026-11-12** |
| `whats-new.html` | **200**，顶部 `<h2>` **v0.11.3**，正文含 v0.11.3 |
| `canonical`（首页） | `https://drugcrossref.com/`（**主域，预期**） |
| `robots.txt` | 200，`Sitemap: https://drugcrossref.com/sitemap.xml`（**主域，预期**） |

> 按 `AGENTS.md` §6 与交接：gh-pages 自 v0.11.2 起只作备份，robots/sitemap/canonical 指主域是预期行为；备份冒烟只覆盖「首页 200 + 版本一致」。**未跑全量 `verify_live`**（其 robots 断言会用 base 拼 sitemap，必然误报）。

## 6. 失败 / 重试 / 发布后状态

- **0 次失败、0 次重试**。日志里 `NativeCommandError` 是 PowerShell 把 `git push` 进度 stderr 当错误记录（`Enumerating objects: …`），非失败。
- 远端 `gh-pages` = `9c802bdf`（已核对 `git ls-remote`）；本地缓存 HEAD = `9c802bdf`，发布树 121,450。
- 发布后缓存：**112,810 松散对象 / 227,327 KB / 2 packs**（本版新增；低于 30 万阈值）。
- `site/dist` 未被修改：仍是 121,450 / 920,332,551 B / 0 字节 / 最新 12:26:54。
- **未打 `v0.11.3` tag**（按 Lead 指令，等 R2 verify 31/31 后再打）。
- 回滚参考：上一版 gh-pages = `8d5c3a60`（v0.11.2）；回滚要人拍板。

## 7. 复现命令

```powershell
$py   = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$git  = '.\tools\git\cmd\git.exe'

# 前置
Get-ChildItem site\dist -Recurse -File | Measure-Object Length -Sum
& $git ls-remote origin gh-pages

# 发布缓存维护（本次做了；publish.ps1 内置守卫尚未落地）
& $git -C .tmp\publish-opt\gh-pages-cache count-objects -v
& $git -C .tmp\publish-opt\gh-pages-cache repack -d -q --threads=4

# 发布（唯一入口）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1

# Pages 状态
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\pages_status.ps1 -Wait -MaxMinutes 30 -History 3

# 备份冒烟
& $py .tmp\smoke_ghpages_v0113.py
```
