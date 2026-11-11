---
name: release
description: 版本发布、打 tag、更新 CHANGELOG、回滚线上站点时用：ci_checks → build == done == → publish.ps1 → verify_live → tag/Release 的完整流程。
whenToUse: 任务涉及发版、CHANGELOG 版本节、gh-pages、verify_live 失败、Pages 构建失败或回滚时。
---

# 发布（release）

**主站 = 自有域名 <https://drugcrossref.com/>（Cloudflare R2 + 自定义域）**；**备份 = gh-pages <https://fuarnos.github.io/drug-brand-crossref/>**（GitHub Pages legacy，仅回滚/备份，不承担主索引）。
**主入口是 `deploy/sync_r2.ps1`，备份入口是 `deploy/publish.ps1`**；不手工推 `gh-pages`、不手工改线上文件。
`SITE_URL`（canonical / hreflang / sitemap / robots / OG）一律写主域；gh-pages 上 canonical 指主域是预期行为，对 gh-pages 只做首页 + 版本冒烟。

> 背景：曾有一次 `site/build.py` 还在写页面就推送，gh-pages 只有 `assets/`、根目录没有
> `index.html`，全站 404。publish.ps1 就是为堵这个洞写的（见 [DEPLOY.md](DEPLOY.md)）。

## 1. 发布前

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py deploy/ci_checks.py --fast     # 改代码时基线（18 秒）
& $py deploy/ci_checks.py            # 发版前全量（约 10 分钟，含 trilingual）
```

1. 测试全过（CI 里没有 `data/drugs.db`，库相关检查会 SKIP，以本地为准）。
2. `CHANGELOG.md` 最上面加一节 `## vX.Y.Z — YYYY-MM-DD`（2–5 条用户能感知的变化）。
   版本号唯一来源就是这一节：站点页脚、`whats-new.html`、GitHub Release 都从它生成。
3. `& $py site/build.py` 等 `== done ==`，按 site-build 技能检查 `site/dist` 完整性。
4. 确认没有别的会话在构建 / 发布（构建与发布串行）。

## 2. 发布（主域先、备份后）

```powershell
# 主通道：R2 自定义域（发布门槛）；先干跑看增量
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1

# 备份通道：gh-pages（GitHub 备份/回滚；默认增量）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1
```

- **顺序：先 R2（主域）后 gh-pages（备份）**；R2 直接吃 `site/dist`，不必等 Pages 构建。
- `sync_r2.ps1` 是 `rclone sync --checksum` 增量，但改 CSS/JS/模板时几乎所有页面都变（样式内联），增量≈准全量：按约 30 分钟、Class A ≈11 万排窗口；Class A 写入数与耗时记进发布报告。
- `publish.ps1` 检查项：`index.html`、`data/idx/core.json`（≥ 10 MB）、文件数 ≥ `-MinFiles 24000`、无 0 字节、最新文件 ≥ `-StableSeconds 15`、无 build/run_all 进程。
- 参数：`-Message`、`-Dist`、`-CacheDir`、`-SkipVerify`、`-FullPush`（仅应急，全量重传）、
  `-AutoRollback`、`-PagesWaitMinutes 45`、`-KeepWork`、`-DryRun`、`-Force`（不建议）。
- token：`$env:GITHUB_TOKEN`，否则仓库根 `.env` 的 `GITHUB_TOKEN=`（Contents: RW + Pages: Read）。
- 发布前**不要**跑 `site/build.py`；发布期间 `site/dist` 冻结。失败会保留临时目录 / 缓存，别手动清理。

## 3. 发布后验证

```powershell
# 主域（发布门槛：必须 0 failures）
& $py deploy/verify_live.py --base https://drugcrossref.com --expect-version vX.Y.Z
& $py deploy/verify_live.py --base https://drugcrossref.com --compare-dist

# 备份通道：只做首页 + 版本冒烟（其 robots/sitemap 行指向主域，不跑全量 verify_live）
& .\deploy\pages_status.ps1 -Wait -MaxMinutes 15              # Pages 构建状态（只读）
```

`verify_live.py` 检查：首页 200/标题/版本、`es/` `zh/` 落地页版本、`whats-new` 顶部版本、
About、GoatCounter、`data/idx/core.json` gzip 体积区间（2.5–12 MB）、关键页面、sitemap 数、
robots、404。退出码 0 才算上线成功；失败先看 stdout 的 JSON。
发布后还按 `docs/网站优化流程.md` §5 的 6 项复核（smoke 复核 / 统计 / 搜索 / 漂移 / 夜间指标）。

## 4. tag / Release

```powershell
$git = '.\tools\git\cmd\git.exe'      # 本机 git 不在 PATH
& $git tag -a vX.Y.Z -m "vX.Y.Z - 一句话"
& $git push origin vX.Y.Z
& $py deploy/github_release.py --tag vX.Y.Z     # 正文取 CHANGELOG 该节
```

## 5. 失败与回滚（人工拍板）

- Pages 构建失败 / 首页检查失败：带 `-AutoRollback` 会恢复上一个 gh-pages commit 并复验；
  先 `pages_status.ps1` 看最近构建时间线，再决定重试或回滚。
- legacy 构建连续失败：`.github/workflows/pages-fallback.yml` 是备选（默认不启用；
  启用/回滚顺序见文件注释，切 Pages Source 前必须按序）。
- 源码层回滚：revert → 重建 → 重新发布；数据层变了要一起回。
- 绝不手工推 gh-pages 或手工改线上文件。

## 6. 体积与限额

`site/dist` 约 839 MiB / 12 万文件；自设 900 MiB 上限，GitHub Pages 已发布上限 1 GB。
逼近上限先清冗余 / 优化索引，并在报告与 CHANGELOG 说明。

## 7. 红线

- 不在构建过程中发布；不用 `-Force` 绕过完整性检查（除非已确认原因并记录）。
- 每版三件齐：CHANGELOG 版本节、build 完成、verify_live 通过 + tag/Release。
- 涉及花钱 / 公开口径 / 连续 2 次发布失败：停下来写报告等人。
