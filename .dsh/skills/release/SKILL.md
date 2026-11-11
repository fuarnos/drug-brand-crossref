---
name: release
description: 版本发布、打 tag、更新 CHANGELOG、回滚线上站点时用：ci_checks → build == done == → sync_r2.ps1（唯一通道）→ verify_live → tag/Release 的完整流程。
whenToUse: 任务涉及发版、CHANGELOG 版本节、R2 上传、verify_live 失败或回滚时。
---

# 发布（release）

**站点唯一发布通道 = 自有域名 <https://drugcrossref.com/>（Cloudflare R2 + 自定义域）**；**git 仓库只作源码/文件备份**。
**gh-pages 已停用**（历史分支与旧产物只作回滚参考，不再推送、不再做备份冒烟）；`deploy/publish.ps1`（及 `发布网站.cmd`）标注为**「历史 / 不再用于发布」**。
**唯一入口是 `deploy/sync_r2.ps1`**；不手工改 R2 对象、不手工推 `gh-pages`、不手工改线上文件。
`SITE_URL`（canonical / hreflang / sitemap / robots / OG）一律写主域。

> 背景：曾有一次 `site/build.py` 还在写页面就推送，gh-pages 只有 `assets/`、根目录没有
> `index.html`，全站 404。publish.ps1 就是为堵这个洞写的（见 [DEPLOY.md](../../../DEPLOY.md)）。

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

## 2. 发布（唯一通道：R2 主域）

```powershell
# 先干跑看增量，再实跑（唯一发布通道）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1
```

- **没有第二条通道**：gh-pages 已停用，不再跑 `publish.ps1`、不再做备份冒烟；R2 直接吃 `site/dist`。
- `sync_r2.ps1` 是 `rclone sync --checksum` 增量，但改 CSS/JS/模板时几乎所有页面都变（样式内联），增量≈准全量：
  v0.11.3 改 112,796 / 121,450 个文件；v0.11.4 上传 117,445 文件 / 868.4 MB。按 **30 分钟** 排窗口，Class A 写入数与耗时记进发布报告。
- 发布前**不要**跑 `site/build.py`；发布期间 `site/dist` 冻结。失败会保留临时目录，别手动清理。
- `deploy/publish.ps1`（及 `发布网站.cmd`）是**历史脚本**，只在回滚旧产物时由人拍板临时使用。

## 3. 发布后验证

```powershell
# 发布门槛：必须 0 failures
& $py deploy/verify_live.py --base https://drugcrossref.com --expect-version vX.Y.Z
& $py deploy/verify_live.py --base https://drugcrossref.com --compare-dist
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

- `verify_live` 失败：先看 stdout JSON 判断是「本机网络」还是「线上产物」；确认是产物问题再考虑回滚。
- 回滚 = 用上一版 `site/dist` 重新 `sync_r2.ps1`（或 gh-pages 历史分支里的旧产物）；**回滚要人拍板**。
- 源码层回滚：revert → 重建 → 重新发布；数据层变了要一起回。
- 绝不手工改 R2 对象、绝不手工推 gh-pages。

## 6. 体积与限额

**单通道后口径**：`site/dist` v0.11.4 约 **930.5 MiB（125,968 文件）**；唯一硬约束是 **R2 免费额度 10 GiB**（用量约 9%），
旧「900 MiB 自设 / GitHub Pages 1 GB」上限**已不适用**。
**页面性能单独看**：单页 KB（drug 页约 160 KB）与 `core.json` gzip（v0.11.4 为 10.164 MB，护栏 2.5–12 MB）；继续瘦身是为首屏速度，不是配额。

## 7. 红线

- 不在构建过程中发布；不用 `-Force` 绕过完整性检查（除非已确认原因并记录）。
- 每版三件齐：CHANGELOG 版本节、build 完成、verify_live 通过 + tag/Release。
- 涉及花钱 / 公开口径 / 连续 2 次发布失败：停下来写报告等人。
