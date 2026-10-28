# 部署

线上地址：<https://fuarnos.github.io/drug-brand-crossref/>

发布方式：**GitHub Pages（legacy 模式，从 `gh-pages` 分支发布）**。
唯一发布入口是 `deploy\publish.ps1`，不要手工往 `gh-pages` 推。

> 2026-10-26 事故：`site/build.py` 还在写页面时就提交并推送了 `gh-pages`，
> 那次提交只带上 `assets/`，根目录没有 `index.html`，全站变成 GitHub Pages 的
> "File not found" 404。下面的脚本就是用来堵这个洞的。

## 一条命令发布

1. 重建站点，等它跑完（终端出现 `== done ==`）：

   ```powershell
   python run_all.py              # 全量：入库 + 建站
   python run_all.py --no-ingest  # 只重建站点
   ```

2. 发布：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1
   ```

   也可以双击根目录的 `发布网站.cmd`。

脚本按顺序做这些事：

- 检查 `site/dist` 是否完整：`index.html`、`data/index.json`（≥ 5 MB）、
  文件数 ≥ 24,000、没有 0 字节文件
- 拒绝在“最新文件写入不足 15 秒”或 `build.py` / `run_all.py` 还在运行时发布
- 复制到系统临时目录，在干净目录里提交（不碰工作区、不碰 `main`）
- 复制完再核对一次源目录，如果复制期间有构建启动就中止
- 强制推送 `gh-pages`，然后等 Pages 构建结束，最后请求首页确认 200
- 成功后才删临时目录；失败会保留目录方便排查

可选参数：

| 参数 | 作用 |
|---|---|
| `-Message "..."` | 自定义提交信息 |
| `-MinFiles 25000` | 调高文件数下限 |
| `-SkipVerify` | 只推送，不等 Pages 构建 |
| `-DryRun` | 只做检查和临时提交，不推送 |
| `-Force` | 跳过文件数 / 新鲜度检查（不建议） |
| `-KeepWork` | 成功后保留临时目录 |

## 更新摘要 / 发布说明

`CHANGELOG.md` 是唯一来源：站点 `/whats-new.html`、全站页脚版本号、GitHub Release 都从
最上面那节 `## vX.Y.Z — YYYY-MM-DD` 生成。

每次上线：

1. 在 `CHANGELOG.md` 最上面加一节，写 2–5 条「用户能感知的变化」。
2. `python site/build.py`：生成 `whats-new.html`，全站页脚显示新版本号。
3. `deploy\publish.ps1`：先打印这节摘要，提交信息默认 `Publish vX.Y.Z (N files)`。
4. 打 tag / 建 GitHub Release，正文用这节 markdown（GitHub 会渲染）：

   ```powershell
   git tag -a vX.Y.Z -m "vX.Y.Z - 一句话"
   git push origin vX.Y.Z
   ```

   **Release 标题/正文统一用 Python 脚本创建**（避免 Windows PowerShell 5.1 把无 BOM 的
   UTF-8 `.ps1` 按本地 ANSI 读取，导致中文标题乱码）：

   ```powershell
   & $py deploy/github_release.py --tag vX.Y.Z --name "vX.Y.Z - 一句话"
   ```

   脚本从 `.env` 读 token、正文取 CHANGELOG 对应那一节；Release 已存在则更新，不存在则创建。
   不要在 `powershell.exe` 里用内联中文字面量直接调 GitHub API。

历史版本已补齐：v0.1.0（原有）、v0.1.1–v0.2.4（按 tag 补建，正文取自 CHANGELOG）。
**v0.3.0–v0.3.3** 已于 2026-10-26 补 tag / Release（源码统一归档到同一提交）；此后每版按上面步骤建。

## 认证

脚本先读 `GITHUB_TOKEN` 环境变量，没有就读仓库根目录 `.env` 里的 `GITHUB_TOKEN=`。

Fine-grained token 需要这个仓库的 **Contents: Read and write**；脚本用 Pages API 等构建
结果，还需要 **Pages: Read**（仓库元数据默认可读）。`.env` 已在 `.gitignore` 里。

## 访问统计

站点统计用 GoatCounter（cookieless，只后台看）。仓库根 `.env` 增加一行（不入库）：

```
GOATCOUNTER_CODE=drug-brand-crossref
```

`site/build.py` 构建时读取；没有该变量就不注入统计脚本。后台：
<https://drug-brand-crossref.goatcounter.com>；细节见 [docs/访问统计.md](docs/访问统计.md)。

## Pages 设置

仓库 Settings → Pages：

- Source：**Deploy from a branch**
- Branch：**gh-pages** / **/(root)**

`main` 放源码，`gh-pages` 只放构建产物。`site/dist` 自 v0.3.3 起已加入 `.gitignore`，
不再进版本库（构建产物只走 `gh-pages`；本地预览时跑 `python site/build.py` 重新生成）。
不要切到 GitHub Actions，原因见下。

## 回滚

每次发布都是 `gh-pages` 上的一个独立提交：

```powershell
git fetch origin gh-pages
git log --oneline origin/gh-pages          # 找到上一个可用提交
git push --force origin <commit>:refs/heads/gh-pages
```

推送后 Pages 会自动重建，约 1 分钟生效。

## 为什么不用 GitHub Actions

建站依赖本地 `data/drugs.db`（几百 MB，已 gitignore），CI 里没有这个库，跑不了
`site/build.py`。`deploy/pages.yml` 只是备用工作流，**当前没有启用**；哪天把数据入库
也搬进 CI，再切到 Actions。

## 备选：Netlify 拖拽

临时演示可以用，不作为主线。`site/dist` 现在约 30,750 个文件 / 124 MB。

1. 打开 <https://app.netlify.com/drop>
2. 把 `site/dist` 文件夹整个拖进去
3. 等 1–2 分钟得到 `https://随机名.netlify.app`

注意：Cloudflare Pages 单次部署上限 2 万个文件，这个站已经超了；Netlify 拖文件夹可以。

## 上线前检查

- [ ] `about.html` 里的来源署名完整（US openFDA / GB dm+d OGL / ES CIMA / MX COFEPRIS /
      CN 医保局快照 / **AU PBS API，须保留 Commonwealth 版权声明** / ARTG）
- [ ] 中国数据标明是 **2025-04-04 快照**，不是实时
- [ ] 澳洲数据标明 **PBS 只覆盖列名药品**、CMI / ARTG 的授权边界
- [ ] 全站无广告、无购买链接、无联盟代码
- [ ] `404.html` / `robots.txt` / `sitemap.xml` 存在（`site/build.py` 自动生成）
- [ ] 页脚版本号 = 最新 tag / GitHub Release（同一版本号）
