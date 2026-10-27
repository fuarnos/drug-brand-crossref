---
name: release
description: 版本发布、打 tag、更新 CHANGELOG、回滚线上站点时用：唯一发布入口 deploy/publish.ps1 的完整流程与检查项。
whenToUse: 任务涉及发版、CHANGELOG 版本节、git tag / GitHub Release、gh-pages、线上 404 / 回滚时。
---

# 发布（release）

线上地址：<https://fuarnos.github.io/drug-brand-crossref/>，GitHub Pages（legacy，从 `gh-pages` 分支发布）。
**唯一发布入口是 `deploy/publish.ps1`**，绝不手工往 `gh-pages` 推。

> 背景：曾有一次 `site/build.py` 还在写页面时就提交并推送，那次 gh-pages 只有 `assets/`、
> 根目录没有 `index.html`，全站 404。publish.ps1 就是为堵这个洞写的（见 DEPLOY.md）。

## 1. 发布前检查

1. 测试全过（没有 CI，本地跑就是门槛）：

   ```powershell
   $py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
   & $py -m unittest discover -s etl -t etl
   & $py -m unittest discover -s lib -t lib
   & $py tests/trilingual/run_tests.py
   & $py db/check_data.py
   ```

2. `CHANGELOG.md` 最上面加一节，格式必须是 `## vX.Y.Z — YYYY-MM-DD`（2–5 条用户能感知的变化）。
   版本号唯一来源就是这一节：站点页脚、`whats-new.html`、GitHub Release 全从它生成，别在别处改版本。
3. 建站跑完：`& $py site/build.py`，等终端出现 `== done ==`。
4. 工作区没有正在跑的 build / run_all；确认没有别的会话在同时构建或发布。

## 2. 发布

```powershell
# 先干跑检查（不打公开变更）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1 -DryRun

# 正式发布（等价于双击 发布网站.cmd）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1
```

脚本会：检查 `site/dist` 完整性（`index.html`、`data/index.json` ≥ 5 MB、文件数 ≥ 24,000、无 0 字节、
最新文件写入 ≥ 15 秒、没有 build.py / run_all.py 在跑）→ 复制到临时目录干净提交 → 复核源目录
→ 强制推 `gh-pages` → 等 Pages 构建结束 → 请求首页确认 200。失败会保留临时目录，别手动清理。

常用参数：`-Message "..."`（提交信息）、`-MinFiles 25000`、`-SkipVerify`、`-DryRun`、
`-Force`（跳过完整性检查，不建议）、`-KeepWork`（保留临时目录）。
认证：先读 `$env:GITHUB_TOKEN`，再读仓库根 `.env` 的 `GITHUB_TOKEN=`（fine-grained token 需要
Contents: Read and write，Pages: Read）。

## 3. 打 tag / Release

```powershell
$git = '.\tools\git\cmd\git.exe'     # 本机 git 不在 PATH
& $git tag -a vX.Y.Z -m "vX.Y.Z - 一句话"
& $git push origin vX.Y.Z
```

GitHub Release 正文直接用 CHANGELOG 那一节 markdown（GitHub 会渲染）。

## 4. 发布后核对

- 首页 200：脚本已经检查；再人工开一次首页、`/whats-new.html`、任意一个成分页。
- 页脚版本号 = CHANGELOG 第一节；`whats-new.html` 列表顶部是最新版本。
- 随机抽一条检索，确认线上结果与本地一致（必要时 `?legacy=1` 对照）。

## 5. 回滚（先问人再动手）

回滚会动公开站点，必须由人拍板。可行路径按顺序考虑：

1. 先 `publish.ps1 -DryRun` 看当前 dist 是否完整，排除只是本地没建完。
2. 源码层回滚：`git revert` 出问题的提交 → 重新 build → publish（数据层若也变了要一起回）。
3. 构建层回滚：checkout 上一个 tag 的源码，重新 build 后 publish。
4. 直接恢复 gh-pages 上一个提交属于最后手段，且要人工确认后再操作。

## 6. 红线

- 不手工推 `gh-pages`、不手工改线上文件、不用 GitHub 网页删文件。
- 不在构建过程中发布；不用 `-Force` 绕过完整性检查（除非已确认原因）。
- 不启用 `deploy/pages.yml`（GitHub Actions Pages 模板，未启用）：本仓库发布走 gh-pages + publish.ps1，
  且 `site/dist` 不在版本库里，启用会得到一个空部署。
