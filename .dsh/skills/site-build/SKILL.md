---
name: site-build
description: 改站点/前端/文案、重建 site/dist 或发布前验收时用：构建、完整性与确定性检查、三语与市场抽查、性能体积预算、本地预览。
whenToUse: 任务涉及 site/build.py、页面/样式/文案/i18n、索引与分片、发布前检查、首屏性能或 dist 体积时。
---

# 建站与验收（site-build）

`site/build.py` 从 `data/drugs.db` 生成整个静态站到 `site/dist/`（约 12 万文件 / 800+ MB）。
**`site/build.py` 是唯一写者**：构建期间冻结，同一时间只允许一个会话跑它或 `deploy/publish.ps1`。

## 1. 构建

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py site/build.py            # 等终端出现 == done ==
& $py run_all.py --no-ingest   # 等价写法（不重建库）
```

全量构建约 20 分钟（机器/缓存不同；`docs/网站优化流程.md` §2.1 有耗时预算）。

## 2. 产物清单

- 根页面：`index.html`、`about.html`、`confused.html`、`whats-new.html`、`404.html`、
  `robots.txt`、`sitemap.xml`、`.nojekyll`
- 目录：`assets/`、`data/`、`drug/`（成分页）、`name/`（同名碰撞页）、`atc/`、`maker/`、
  `cat/`、`combo/`、`docs/`、`es/`、`zh/`、`zh-hant/`（语言落地页；其余页面客户端 i18n）
- 搜索索引（v0.6.1 起只有它）：`data/idx/core.json` + `shard-*.json` + `detail-*.json` +
  `pinyin.json` + `atc4-forms.json` + `manifest.json`
- 数据资产：`data/{aliases,artg,categories,confused,export-only,maker-map,terms}.json`；
  导出 CSV 在 `data/exports/`
- `data/index.json` 已废弃（v0.6.1 起不再生成），不要再当验收项。

## 3. 必做检查

```powershell
& $py deploy/ci_checks.py --fast          # 18 秒：编译 / unittest / dist 完整性
& $py deploy/ci_checks.py                 # 全量（发版前，约 10 分钟，含 trilingual）
& $py deploy/check_build_determinism.py   # 构建确定性（按脚本用法）
& $py serve.py 8000                       # 预览 http://127.0.0.1:8000/
```

手工抽查：

- 必需文件都在：`index.html`、`404.html`、`robots.txt`、`sitemap.xml`、`.nojekyll`、
  `data/idx/core.json`、`assets/style.css`、`assets/app.js`
- 文件数 / 体积：`(Get-ChildItem site/dist -Recurse -File).Count`、
  `(Get-ChildItem site/dist -Recurse -File | Measure-Object Length -Sum).Sum`；0 字节文件必须为 0
- `data/idx/core.json` raw ≥ 10 MB（publish 门槛）；gzip 体积按 `docs/网站优化流程.md` §2.1 预算
  （近期约 9.8 MB gz，目标 ≤ 9.5 MB；`verify_live.py` 护栏 gzip 2.5–12 MB / raw 11–50 MB）
- dist 总量：自设 900 MiB 上限，GitHub Pages 已发布上限 1 GB；当前约 839 MiB，余量约 60 MiB
- sitemap URL 数 = HTML 数 − noindex 数（公式见 `docs/网站优化流程.md` §4-11）
- 三语：同一成分用英 / 西 / 中名都落到同一 substance 页；语言切换与 `hreflang` 正常
- 十个市场：国家视图与 `data/markets.json` 一致

## 4. 站点/前端改动的完整流程

先读 `docs/网站优化流程.md`：改前 §3.1–§3.2，改后 §4 的 12 项，发布后 §5 的 6 项。
门槛：Lighthouse 移动端四项 ≥ 90；首屏 ≤ 330 KB raw / 110 KB gz；单页 HTML ≤ 6 KB。
三项纪律：`build.py` 唯一写者、发布只走 `publish.ps1`、数字以实测为准（不抄旧数字）。

## 5. 常见坑

- **没出现 `== done ==` 就发布**：曾导致 gh-pages 只有 assets/、整站 404（见 [DEPLOY.md](DEPLOY.md)）。
- 只改一种语言 / 一个市场：i18n 三份字典 + `data/markets.json` 要一起改。
- 手工改 `site/dist/`：下次构建就没了，改源头。
- 构建进行中跑测试 / 入库 / 发布：会读到半成品，串行做。
- 索引或体积改动后忘了同步预算和 `verify_live.py` 的体积断言。
