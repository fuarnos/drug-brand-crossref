---
name: site-build
description: 改站点、重建 site/dist 或发布前验收时用：构建、完整性检查、三语抽查、性能与链接回归、本地预览。
whenToUse: 任务涉及 site/build.py、页面文案 / 样式 / 前端、站点计数口径、发布前检查、首屏性能或索引体积时。
---

# 建站与验收（site-build）

`site/build.py` 从 `data/drugs.db` 生成整个静态站到 `site/dist/`（约 3 万个文件 / 130+ MB）。
它同时是页面模板、i18n 字典和版本号的来源，改动会放大到全站，必须按顺序验收。

## 1. 构建

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py site/build.py            # 看到终端出现 == done == 才算完成
& $py run_all.py --no-ingest   # 等价写法（不重建库）
```

- 构建要几分钟，**构建期间不要跑 `publish.ps1`**，也不要在另一个会话同时构建（会互相踩 dist）。
- `site/dist/` 是生成物（gitignore），不要手工编辑；发布只走 `deploy/publish.ps1`。

## 2. 完整性检查（必做）

```powershell
$dist = 'site/dist'
'index.html','about.html','confused.html','whats-new.html','404.html',
'robots.txt','sitemap.xml','.nojekyll','data/index.json','data/aliases.json',
'data/artg.json','data/confused.json','assets/style.css','assets/i18n.js' |
  ForEach-Object { "{0,-22} {1}" -f $_, (Test-Path (Join-Path $dist $_)) }

(Get-ChildItem $dist -Recurse -File).Count                                        # 期望 ≥ 24,000（publish 门槛）
[math]::Round((Get-ChildItem $dist -Recurse -File | Measure-Object Length -Sum).Sum/1MB)  # 站点体积
[math]::Round((Get-Item "$dist/data/index.json").Length/1MB)                       # 期望 ≥ 5 MB
(Get-ChildItem $dist -Recurse -File | Where-Object Length -eq 0).Count            # 必须 0
```

目录结构：`drug/` ≈ 1.2 万张成分页，`name/` ≈ 1.8 万张同名碰撞页，`es/`、`zh/` 是语言入口页；
其余页面是一份 HTML + 客户端 `?lang=en|es|zh` 切换（`assets/i18n.js`），`hreflang` 指向 `/es/`、`/zh/`。

## 3. 三语与检索抽查

- 同一成分用英 / 西 / 中三种叫法都应落到同一 substance 页（示例：Tylenol / paracetamol / 泰诺 + 对乙酰氨基酚）。
- 结构化验证优先跑现成测试，不要手搓：

```powershell
& $py tests/trilingual/run_tests.py            # 全量三语一致性（只读开库）
& $py tests/trilingual/run_tests.py --only amlodipine,metoprolol
& $py cli.py "泰诺"                            # 单条查询
```

- 页面侧抽查：打开 `drug/` 下对应成分页，切 EN / ES / 中文，确认标题、剂量列、"查不到 ≠ 不存在" 提示一致。
- 改到检索语义时，加跑 `& $py -m unittest discover -s lib -t lib`。

## 4. 回归关注点

| 项 | 期望 |
|---|---|
| 首屏体积 | 只加载 HTML/CSS/JS（十几 KB）；`data/index.json` 是懒加载，首次输入 / 带 `?q=` 才拉 |
| 索引 | `data/index.json` 大小和条目数变化要能解释；`?legacy=1` 仍可回退到旧行为 |
| 版本号 | 页脚 / `whats-new.html` / Release 都取 CHANGELOG 第一节 `## vX.Y.Z — YYYY-MM-DD` |
| 链接与 SEO | `sitemap.xml` 覆盖全量页面；`404.html` 在任意子路径都能回站内；`robots.txt`、`.nojekyll` 在 |
| 资产缓存 | `assets/*.js|css` 带 `?v=` 时间戳，改完确认 URL 变了（否则浏览器拿旧文件） |
| 计数口径 | 页面上数字与 `data/drugs.db` 现查一致；README / About / CHANGELOG 同步 |

## 5. 本地预览

```powershell
& $py serve.py 8000    # http://127.0.0.1:8000/
```

预览能替代截图验收；需要留图时放 `docs/img/`（kebab-case），文档里相对链接引用。

## 6. 常见坑

- **没出现 `== done ==` 就发布**：曾导致 gh-pages 只有 assets/、整站 404（见 DEPLOY.md），这是本项目最贵的一次事故。
- 只改一种语言的文案：本站是客户端 i18n，三语字典在 `site/build.py` 里，漏一种就是漏全站。
- 手工改 `site/dist/`：下次构建就没了，改源头。
- 在构建进行中跑测试 / 入库 / 发布：都会读到半成品，串行做。
