# 部署

产物：`site/dist/`（23,016 个文件 / 62.6 MB），打包好的 `site/dist.zip`（23.8 MB，根目录就是 index.html）。

**为什么不用 Cloudflare Pages**：单次部署上限 2 万个文件，我们 23,016 个，超了。

## 方案 A：Netlify 拖拽（最快，零安装，推荐先用这个）

1. 打开 https://app.netlify.com/drop
2. 把 `site/dist.zip` **整个拖进去**（不用解压，Netlify 会自己解）
3. 等 1–2 分钟，得到一个 `https://随机名.netlify.app` 的网址
4. 免费额度：100 GB 流量/月，静态站点够用到天荒地老

登录后可以改名成 `drugbrand.netlify.app` 这种；绑定自定义域名在 Domain settings。

*注意*：拖 zip 时如果提示文件数超限，改拖 `site/dist` 文件夹本身。

## 方案 B：GitHub Pages（长期维护用）

本机没装 git，先装：`winget install --id Git.Git -e`

```powershell
cd D:\同种药物商品名剂量对应网站
git init
git add -A
git commit -m "drug brand cross-reference"
git branch -M main
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin main
```

仓库 Settings → Pages → Source 选 `GitHub Actions`，然后加这个工作流
`.github/workflows/pages.yml`：

```yaml
name: Deploy
on:
  push: { branches: [main] }
permissions: { contents: read, pages: write, id-token: write }
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/upload-pages-artifact@v3
        with: { path: site/dist }
      - uses: actions/deploy-pages@v4
```

地址是 `https://<账号>.github.io/<仓库名>/`。
**坑**：站点在子路径下，`assets/` 用的是相对路径没问题，但首页 `fetch(BASE + 'data/index.json')`
里的 BASE 是从 `app.js` 的 src 推出来的，子路径下也能正确解析；`/es/`、`/zh/` 同理。
唯一要改的是 `site/build.py` 里的 hreflang（写的是 `/`、`/es/`），子路径部署要改成相对或完整域名。

## 方案 C：自建 VPS（不推荐）

静态站不需要。VPS 要自己管证书、补丁、备份、带宽，成本从 0 变成每月几十到几百。

## 上线前检查

- [ ] 域名要不要买（¥60–100/年）；不买就用 `*.netlify.app`
- [ ] `about.html` 里的来源署名是否完整（US openFDA / GB dm+d OGL / ES CIMA / MX COFEPRIS / CN 医保局 2024-01-05 快照）
- [ ] 中国数据要标明是 **2024-01-05 快照**，不是实时
- [ ] 全站无广告、无购买链接、无联盟代码
