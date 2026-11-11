# v0.11.6 R2 收尾方案（canonical / 404 / Cache-Control / publish 缓存守卫）

- 工位：`pages-deploy`（任务板 `task-11`）
- 时点：2026-11-12 01:4x 北京（America/Los_Angeles 2026-11-11 09:4x）
- 状态：**只读研究 + 方案**。未改 `site/build.py` / `deploy/publish.ps1`，未跑 publish / sync（非 `-CheckOnly`），未调任何 Cloudflare 写 API。
- 上游：[`AGENTS.md`](../AGENTS.md) §6（2026-11-12 起「自有域名为主、Git 只作备份」）、[`docs/工作组与流程.md`](../docs/工作组与流程.md) §五、[`reports/2026-11-11-发布卡点-gh-pages缓存松散对象.md`](2026-11-11-发布卡点-gh-pages缓存松散对象.md)、[`reports/2026-11-11-r2-closeout.md`](2026-11-11-r2-closeout.md)、[`docs/托管迁移执行清单.md`](../docs/托管迁移执行清单.md)、[`docs/交接-20261112.md`](../docs/交接-20261112.md) §5。
- 一句话：**canonical 切换已在 v0.11.2 工作树落地（`SITE_URL` L63 = 主域，未提交/未构建），v0.11.6 只剩 404、Cache-Control、loose-object 守卫三件；三件都能在免费额度内做完，唯一需要人做的是 Cloudflare 控制台配置（仓库里没有 CF API token）。**

---

## 0. 结论

| # | 缺口 | 结论 | 优先级 | 成本 | 谁做 |
|---|---|---|---|---|---|
| ① | canonical / hreflang / sitemap / robots / OG / datapackage 仍写死 gh-pages | **构建期单一主域**（`SITE_URL` = `https://drugcrossref.com/`），不做运行时 JS。工作树已由 site-ui 改好（未提交、未构建），本报告给验收守卫与兜底 | P0 | 0 元 | site-ui（改 `build.py`，已做）+ Lead（验收守卫） |
| ② | R2 默认 404（`Object not found`） | **Cloudflare Worker 回源**：Route `drugcrossref.com/*` 做 pass-through，404 时用 R2 binding 取 `/404.html`，保持 404 状态。免费额度 10 万请求/日，路由 fail-open 兜底 | P1 | 0 元 | 人（控制台）；代码可先落 `deploy/` |
| ③ | 对象无 `Cache-Control`、`cf-cache-status: DYNAMIC` | **Cloudflare Cache Rules（4 条）+ 可选 Response Header Transform**，不改对象元数据。HTML 不缓存、`assets/*` 1 年、`data/*` 30 分钟、sitemap/robots 10 分钟 | P1 | 0 元 | 人（控制台） |
| ④ | `publish.ps1` 松散对象可能再爆炸（曾 244 万 / 卡 1h50m） | push 前加 loose-object 守卫：>12 万做增量 `repack -d`，>30 万或 pack ≥8 做全量 `repack -ad`；耗时写进 manifest | P1 | 0 元 | 下一版改 `publish.ps1`（今日禁改） |

**关键决策依据**：`AGENTS.md` §6 已定「`SITE_URL` 一律写主域」+「gh-pages 上 canonical 指主域是预期行为、不跑全量 `verify_live`」，所以 canonical 只剩「怎么落地 + 怎么验」，不再是「选哪个方案」。

---

## 1. 现状（现查）

### 1.1 站点产物（`site/dist` 现查，v0.11.1 构建）

| 指标 | 现查 |
|---|---|
| 文件 / 字节 | **121,450 / 903,622,525 B（861.8 MiB）**；900 MiB 自设上限余量 **≈38.2 MiB** |
| HTML | **121,239**（正式 combo **6,790** + combo noindex stub **8,458** + name 77,147 / maker 15,213 / drug 12,431 / atc 1,154 / cat 16 / 四语根副本 21 / 根页 9） |
| sitemap | **63,685** 条 `<url>`，**63,685 条 `<loc>` 全部 `https://fuarnos.github.io/drug-brand-crossref/`** |
| core.json | 41,624,434 B（raw）；`data/` 共 **193 个文件 / 209,954,746 B（≈200 MB）**（核心 + 51 个 detail 桶 + shard + exports） |
| 旧域残留 | **112,785 个文件**（112,781 HTML + `sitemap.xml` + `robots.txt` + `datapackage.json` + `dataset.jsonld`），**339,813 次**出现 |
| 换域后体积 | 每个绝对 URL 短 **21 B**（46 → 25），339,813 × 21 ≈ **−7.14 MB**（dist ≈ 896.5 MB，余量升到 ≈45 MiB） |

> 复现：`.tmp\scan_domain.py`、`.tmp\scan_delta.py`（本次写的一次性只读脚本，`.tmp/` 不入库）；命令列在 §10。

**受影响文件按目录**（含旧域的文件数 / 出现次数）：

| 目录 | 文件数 | 出现次数 |
|---|---:|---:|
| `name/` | 77,147 | 154,294 |
| `maker/` | 15,213 | 45,639 |
| `drug/` | 12,431 | 49,724 |
| `combo/`（正式页） | 6,790 | 20,370 |
| `atc/` | 1,154 | 5,770 |
| 根目录 | 13（9 HTML + 4 非 HTML） | 63,779（含 sitemap 63,685） |
| `cat/` / `es/` / `zh/` / `zh-hant/` | 16 / 7 / 7 / 7 | 48 / 63 / 63 / 63 |

`combo/` 的 **8,458 个 stub** 是 v0.9.0 旧链接兼容页：内联 CSS、无 canonical / hreflang、`noindex,follow`，**不随 `SITE_URL` 变化**（不在本次重建 diff 里）。

### 1.2 `SITE_URL` 定义与使用点（`site/build.py`）

> **写作过程中 site-ui 已在工作树把它改掉了**：`SITE_URL` 旧值 `https://fuarnos.github.io/drug-brand-crossref/`（原 L61）→ 现 **L63 `SITE_URL = "https://drugcrossref.com/"`**（+2 行注释，未提交、未构建）。下表行号按当前工作树（`build.py` 12,868 行）取；`site-ui` 继续改文件时行号会再漂，复核请用符号搜索（`SITE_URL` / `hreflang` / `canonical`）。

| 位置 | 用途 |
|---|---|
| **L63** `SITE_URL = "https://drugcrossref.com/"` | 唯一定义；L60–62 注释已改为「主站 = 自有域名，gh-pages 上的 canonical 指主域是预期行为」 |
| L7182 / L7185 / L7187 | `page()` 的 hreflang（4 语 + x-default + zh-TW） |
| L7198 / L7207 | `page()` 的 `canonical` / `og:url` |
| L7214–7216 | 无 `meta_key` 页的 canonical + x-default |
| L7227 | 全站 `WebSite` JSON-LD 的 `url` |
| L7307–7310 | `/es/ /zh/ /zh-hant/` 静态副本的 canonical / og:url |
| L8779 / L11339 / L11341 | 成分页/ATC 页 JSON-LD 的 `item` 绝对 URL |
| L11722–11757 | `404.html` 的全部导航/语言/样式/i18n 绝对链接 |
| L11860 / L11879 / L11884 / L11887 / L11890 | `datapackage.json` 的 `homepage`、`dataset.jsonld` 的 `url`/`creator.url`/`distribution[].contentUrl` |
| L11937–L11953 | sitemap `<loc>` 与 `robots.txt` 的 `Sitemap:` 行 |

**代价放大器**：`_compute_build_v()`（L102–112）对 **`site/build.py` 自身字节 + 两份 zh-Hant 字典** 做 sha1，得到一个 10 位十进制 `BUILD_V`，写进**每一页**的 `assets/*.css|js?v=BUILD_V`。因此**只要动 `build.py` 一行，BUILD_V 就变 → 121,239 个 HTML 全部变**，与「只改 4 个文件」的直觉无关。这解释了 v0.11.1 为何改了 112,796/121,450 个文件；site-ui 这次给 `SITE_URL` 加了两行注释 + 改常量，已经触发了这个放大器。
→ 结论：`SITE_URL` 的切换必须当作**一次全站发布**排窗口（R2 ≈30 min / Class A ≈11.3 万；gh-pages ≈16 min），不能按「7 MB 小改」估。

### 1.3 Cloudflare / R2 现状

| 项 | 现查 |
|---|---|
| 自定义域 | `drugcrossref.com` → bucket `drug-brand-crossref`，**Active / Access: Enabled** |
| Transform Rules | **4 条 URL Rewrite**：`/`→`/index.html`、`/zh/`→`/zh/index.html`、`/es/`→…、`/zh-hant/`→…；ruleset **`83d79c38e13b4b27839b7ed340348c85`** |
| zone | **`c9f0f6bb6a652741de5bef5c09c8da5b`** |
| Worker | **无** |
| Cache Rules | **无** |
| 对象元数据 | `index.html` / `core.json` / `sitemap.xml` / `404.html` / `zh/index.html` 的 **`Cache-Control` 全部为空**（rclone 上传默认） |
| 边缘缓存 | `cf-cache-status: DYNAMIC`（HTML/JSON 本就不在 Cloudflare 默认缓存扩展名里） |
| 不存在路径 | **404 状态对，但 body 是 R2 的 “Object not found”**，不是站点 `/404.html` |
| R2 桶 | **121,450 对象 / 898,159,644 B**（= v0.11.0 产物，比 gh-pages 落后一版；v0.11.2 会一次补齐） |
| 仓库凭据 | `.env` 只有 `R2_*`（S3 兼容 key）；`deploy/check_r2_env.py` 只认这 4 个键 → **没有 Cloudflare API token**，Worker / Cache Rules / Transform Rules 只能控制台人工配置 |

### 1.4 双通道现查

| 通道 | 现状 |
|---|---|
| gh-pages | **v0.11.1**，`ec99a135527`（`git ls-remote` + 本地缓存 HEAD 一致） |
| R2 主域 | **v0.11.0**（待 v0.11.2 补齐） |
| 发布缓存 | `.tmp/publish-opt/gh-pages-cache`：**112,810 个松散对象 / 225,988 KB / 1 个 pack**（`in-pack 2,385,899 / size-pack 1,069,837 KB`） |
| 事故参照 | v0.11.1 前缓存 **2,440,758 松散 / 4.98 GB**，push 卡 **1h50m**；v0.11.0 发布 969 s / 推包 38.75 MB |

---

## 2. canonical / hreflang / sitemap / OG

### 2.1 三个候选方案与取舍

| 方案 | 做法 | 额外成本 | 优点 | 缺点 / 否决理由 |
|---|---|---|---|---|
| **A. 构建期单一主域（推荐，已定）** | `SITE_URL` = `https://drugcrossref.com/`；**一份产物同时发两通道** | 1 次全量重建（≈4.3 min）+ R2 ≈30 min + gh-pages ≈16 min | canonical/hreflang/sitemap/robots/OG/datapackage 全部自洽；两份产物逐字节一致，`rclone check` 口径不变；SEO 只认主域 | gh-pages 上 canonical 指主域（**AGENTS §6 明确是预期行为**）；gh-pages 的 robots/sitemap 也指主域，对备份通道不再跑全量 `verify_live` |
| A2. 构建期双产物 | gh-pages 一份自指、R2 一份自指（`SITE_URL` 走环境变量） | **2 次全量重建 + 两份 900 MB dist + 两条发布链各验一次**（≈+45 min/版） | 每个域都能独立自洽 | 备份通道自指会与主域**竞争索引**，与「Git 只作备份」口径冲突；`publish.ps1` 要吃第二份 dist，发布链复杂化。**不采用** |
| B. 运行时 JS 改 canonical | 页面里加几行 JS，按 `location.origin` 重写 canonical/hreflang/og:url | 1 次构建 | 零发布 | **sitemap.xml / robots.txt 是静态文件，运行时改不了**；Facebook/X/Slack/微信等 OG 爬虫不执行 JS → OG 仍指旧域；Google 对 JS 注入的 hreflang 不保证识别；HTML 源码与 DOM 不一致是 SEO 反模式。**只能当补丁，不能当方案** |
| C. canonical 用相对 URL | `<link rel="canonical" href="/zh/...">` | 0 | 一份产物两域自适应 | canonical 相对虽被 Google 接受，但 **hreflang 必须绝对 URL、sitemap `<loc>` 必须绝对、OG 建议绝对** → 只解决 1/4 问题。**不采用** |

**结论：A**（与 `AGENTS.md` §6 一致）。canonical 用绝对 URL、hreflang 用绝对 URL 是 Google 的硬要求；既然只换一次域，就让构建期常量说了算，运行时不引入第二套真相源。

### 2.2 落地契约（给改 `build.py` 的工位）

> 现查：site-ui 已把常量改成主域（L63），但**没有**环境变量覆盖、**没有**格式校验、**没有**构建日志；以下 1–2 是建议增补，不阻塞 v0.11.2。

1. `SITE_URL` 已改为主域（L63）。建议加**校验**（`https://` 开头、末尾补 `/`），构建日志打印 `site url: ...`（发布报告可复核）。
2. 建议顺带支持 `SITE_URL` 环境变量覆盖、默认主域：以后换域/演练双产物无需再改代码。注意 `_compute_build_v()` **不含** `SITE_URL`，所以资产文件的 `?v=` 不随域名变——正好让「域名」与「代码版本」解耦。
3. `page()` L7179 的注释（「必须带 GitHub Pages 的项目子路径」）已过期，改成「绝对 URL 指主域」。
4. 不动 `REPORT_REPO`（GitHub Issue 仍是 `github.com/fuarnos/...`，不是 `fuarnos.github.io`）。
5. 构建后**全量断言 0 残留**（4 类产物，HTML 除外）：
   ```python
   # 建议接进 deploy/ci_checks.py（本地发布门槛；CI 无 dist 时 SKIP）
   old = "fuarnos.github.io"
   assert all(old not in p.read_text("utf-8", "replace")
              for p in (dist/"sitemap.xml", dist/"robots.txt",
                        dist/"datapackage.json", dist/"dataset.jsonld"))
   # HTML 抽 200 页（首页/四语/atc/drug/name/maker/combo 各若干）也不得出现 old
   ```
   HTML 全量 112,781 个文件逐个 grep 约 10–20 s，可以在发布前跑一次（不是每版都要）。

### 2.3 时间线：v0.11.2 与 v0.11.6 的分工

- [`docs/交接-20261112.md`](../docs/交接-20261112.md) §5 已写：**v0.11.2 本版把 `SITE_URL` 改为主域**，验收含「`fuarnos.github.io` 残留 0」。
- **现查（写作时）**：`site/build.py` 工作树已改（L63），但 `site/dist` 还是 v0.11.1 的旧构建（canonical 仍指旧域），也**还没提交/构建/发布**。所以本报告 §2 在 v0.11.6 里只剩两件事：
  1. 若 v0.11.2 因故没发成，重建即可（常量已就位）；
  2. **验收守卫**（§2.4 / §2.5）——现在的 `verify_live.py` 检不出 canonical 回归，这是比改常量更长期的缺口。

### 2.4 验收守卫缺口（`deploy/verify_live.py` 现查）

| 现状 | 问题 |
|---|---|
| L38 `DEFAULT_BASE = "https://fuarnos.github.io/drug-brand-crossref/"` | 默认还是旧主站，与「主域为发布门槛」不符 |
| L333–335 `robots` 检查断言 `f"{base}sitemap.xml" in rb_text` | 换主域后 **gh-pages 必然 FAIL**（它的 Sitemap 行指主域）→ 只能不跑，等于备份通道没有冒烟脚本 |
| L324–330 sitemap 只数 `<url>` 个数 | **不校验 `<loc>` 域名**：canonical 退回旧域也能全绿 |
| L336–338 404 只断言状态码 | 现在 R2 返回 R2 默认 404 也算 PASS → 缺口 ② 永远测不出来 |
| 全文件无 canonical / hreflang / OG / datapackage 断言 | 缺口 ① 无回归护栏 |

**建议 diff（v0.11.6，由 Lead/发布工位改，本报告不改文件）**：

```diff
- DEFAULT_BASE = "https://fuarnos.github.io/drug-brand-crossref/"
+ DEFAULT_BASE = "https://drugcrossref.com/"

  ap.add_argument("--expect-version", ...)
+ ap.add_argument("--expect-site-url", default="",
+                 help="断言 canonical/hreflang/OG/sitemap/robots 的主域，如 https://drugcrossref.com/")
+ ap.add_argument("--smoke-only", action="store_true",
+                 help="备份通道冒烟：只查首页 + 页脚版本，不查 robots/sitemap/core/404")
```

```python
# 首页 canonical / og:url / hreflang（--expect-site-url 时）
site = args.expect_site_url.rstrip("/") + "/"
checks.add("homepage-canonical", f'<link rel="canonical" href="{site}">' in home_text,
           f"canonical 应为 {site}")
checks.add("homepage-og-url", f'<meta property="og:url" content="{site}">' in home_text,
           f"og:url 应为 {site}")
checks.add("homepage-hreflang",
           all(f'hreflang="{h}" href="{site}{p}"' in home_text
               for h, p in (("en", ""), ("es", "es/"), ("zh", "zh/"),
                            ("zh-Hant", "zh-hant/"), ("x-default", ""))),
           "五条 hreflang 都指主域")

# sitemap：全部 <loc> 同域 + 无旧域
locs = re.findall(r"<loc>([^<]+)</loc>", sm_text)
checks.add("sitemap-host", bool(locs) and all(u.startswith(site) for u in locs),
           f"{len(locs):,} 条 loc 均在 {site}")

# 404：状态 + 内容 + noindex
checks.add("404-body", missing["status"] == 404
           and b"Page not found" in missing["body"]
           and b"Object not found" not in missing["body"],
           "404 内容是站点 404 页（不是 R2 默认）")

# datapackage：homepage 同域
dp = get("datapackage.json")
checks.add("datapackage-home", f'"homepage": "{site}"' in text_of(dp), ...)
```

备份通道用 `--smoke-only`（只跑 §1 首页 + §2 页脚版本），不再被 robots/sitemap 的「预期跨域」误伤；主域仍跑全量。

### 2.5 本机验收跑不了 → 用 GitHub Actions（零成本）

本机对 `drugcrossref.com` 被 FortiGuard 拦（TLS 中间人，`SEC_E_UNTRUSTED_ROOT`），`verify_live.py --base https://drugcrossref.com/` 本机会误报 `homepage` failure（见 [`reports/r2-domain-readiness-20261111.md`](r2-domain-readiness-20261111.md) §3）。建议加一个手动工作流（公开仓库，免费）：

```yaml
# .github/workflows/verify-live.yml
name: verify-live
on:
  workflow_dispatch:
    inputs:
      base:
        description: "站点根 URL"
        default: "https://drugcrossref.com/"
      version:
        description: "期望版本，如 v0.11.6（留空则不校验）"
        default: ""
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: verify
        env:
          BASE: ${{ inputs.base }}
          VERSION: ${{ inputs.version }}
        run: |
          python deploy/verify_live.py --base "$BASE" \
            ${VERSION:+--expect-version "$VERSION"} \
            --expect-site-url "$BASE" \
            --json-out verify-live.json
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: verify-live, path: verify-live.json }
```

这样「主域发布门槛」不再依赖本机网络，也不再需要外部代理手工抄头。注意 `base` 只填**主域**（备份通道的跨域 robots/sitemap 会被 `--expect-site-url` 判失败）；备份冒烟用 `--smoke-only` 在本地或另一个 workflow 跑。

---

## 3. R2 自定义 404（v0.11.6）

### 3.1 为什么必须是 Worker

| 候选 | 结论 |
|---|---|
| R2 自定义域「404 document / error document」配置 | **不存在**。官方 Public buckets 文档只有 custom domain / cache / access；R2 的 S3 兼容文档没有 website 配置（`PutBucketWebsite`）→ 换不了错误页 |
| Cloudflare **Custom Errors**（可替换 4xx 响应体，正好够用） | **Free 计划不可用（Availability: No）**，Pro 起才有 → 违反「零新增支出」 |
| Cloudflare **Snippets**（5 ms 轻量 JS） | **Free 计划不可用（0 snippets）** → 不行 |
| **Workers Static Assets**（自带 `404-page` 语义） | Free **20,000 文件/版本**，本站 121,450 → 不行（Paid 10 万也不够） |
| Cloudflare Pages | 同上，单次部署文件数上限 20,000 → 不行 |
| Transform Rules / Cache Rules / Redirect Rules | 只能改请求或响应头，**无法按上游 404 改响应体** → 不行 |
| **Worker Route + 回源**（R2 作为 origin） | ✅ 唯一免费可行路径 |

### 3.2 推荐方案：Route 做 pass-through，404 用 R2 binding 取 `/404.html`

关键事实：Cloudflare 文档明确 **Routes 可以 `fetch()` 同主机的 Custom Domain**（路由的 `fetch(request)` 回源到 DNS 指向的源站）；社区实例显示 **Routes 优先于 R2 自定义域**（同一主机上通配路由会先于 R2 响应）。路由模式支持 `drugcrossref.com/*`。所以 Worker 挂在主域前面，正常请求 `fetch(request)` 回源到 R2（Cache Rules 照常生效），只有 404 才从 binding 取站点 404 页——**不碰 121k 个正常对象**。

```js
// deploy/r2-404-worker.js（建议落 deploy/，wrangler.toml 同目录；今天未创建）
export default {
  async fetch(request, env) {
    // 回源到 R2 自定义域（同 zone 的 Custom Domain，Cache Rules 生效）
    const res = await fetch(request);
    if (res.status !== 404) return res;          // 200/206/304 原样返回

    // 只取一个对象，避免同 zone 递归 fetch /404.html
    const page = await env.BUCKET.get("404.html");
    if (!page) return res;                        // 兜底：R2 默认 404

    const headers = new Headers();
    page.writeHttpMetadata(headers);
    headers.set("content-type", "text/html; charset=utf-8");
    headers.set("cache-control", "no-store");     // 404 不进边缘/浏览器缓存
    headers.set("x-robots-tag", "noindex");
    return new Response(request.method === "HEAD" ? null : page.body, {
      status: 404,
      headers,
    });
  },
};
```

```toml
# wrangler.toml（示意）
name = "drug-brand-crossref-404"
main = "r2-404-worker.js"
compatibility_date = "2026-11-01"
[[r2_buckets]]
binding = "BUCKET"
bucket_name = "drug-brand-crossref"
[[routes]]
pattern = "drugcrossref.com/*"
zone_id = "c9f0f6bb6a652741de5bef5c09c8da5b"
```

要点：
- **HEAD 必须处理**：`deploy/verify_live.py` 对 `core.json` 用 `HEAD`；`body: null` 才不会报错。
- 404 页里是绝对 URL（主域 `assets/style.css` 等），Worker 回源能正常取到。
- 不要给 404 页写 `Cache-Control: public`：避免错误 URL 被缓存后长期 404。
- 若后续出现 Range 请求（目前只有 HTML/JSON/CSV/SVG，无媒体文件），再补 `R2GetOptions.range`。

### 3.3 配置步骤（人执行，控制台；含 staging 验证）

1. **准备**：确认 bucket 仍是 `drug-brand-crossref`，主域自定义域 Active；记下 zone `c9f0f6bb…`。
2. **staging 子域**（避免直接挂主域）：R2 → bucket → Custom Domains → 加 `stage.drugcrossref.com`（免费，几分钟 Active）。
3. **部署 Worker**（不挂主域路由）：`wrangler deploy`；绑定 `BUCKET`；路由先只加 `stage.drugcrossref.com/*`。
   - 路由 **fail-open**（配额用尽时绕过 Worker 直连 R2，404 退化为 R2 默认页，站点不挂）。
4. **staging 验收**（本机对 `drugcrossref.com` 被 FortiGuard 拦，`stage.` 子域大概率同样被拦 → 用 §2.5 的 CI 或外部节点；能连的环境至少 `curl -I` 看头）：
   - `/` → 200、`content-type: text/html`、`content-encoding: gzip`
   - `/assets/style.css?v=<BUILD_V>` → 200、`text/css`、大小与 dist 一致（**若返回 `text/html` 说明 Worker 把 R2 吃了**，见 §6 风险）
   - `/data/idx/core.json` → 200、`application/json`、gzip（HEAD 也 200）
   - `/this-page-does-not-exist` → **404**、`content-type: text/html`、body 含站点 404 文案、`x-robots-tag: noindex`
   - `/sitemap.xml`、`/robots.txt`、`/e2fea3dfe91d65e7c4dc23106afa53e2.txt` → 200
5. **切主域**：删 `stage.` 路由（保留 Worker）→ 加 `drugcrossref.com/*` 路由（fail-open）→ 重跑第 4 步全部用例 + §7 的 `verify_live`。
6. **记录**：Worker 名 / 版本 / 路由 / 绑定 / 部署时间写进发布报告；`stage.drugcrossref.com` 自定义域用完删除（避免多一个公开入口）。

### 3.4 回滚 / 成本 / 风险

| 项 | 内容 |
|---|---|
| 回滚 | **删除 `drugcrossref.com/*` 路由** → 秒级回到 R2 直连（默认 404，站点其余功能不变）；Worker 可保留不用（0 元）或删除 |
| 成本 | Workers Free：**100,000 请求/日**、10 ms CPU、128 MB；本站在此额度内；超额 fail-open 只降级 404 页，不产生费用 |
| 风险 1 | Worker 代码错误 → 全部请求 1101（主站不可用）。缓解：先 stage 子域验证；路由删除即回滚；Worker 代码保持 <30 行、无外部依赖 |
| 风险 2 | 通配路由会**吃掉 R2 自定义域**（Cloudflare 社区有实例：`media.example.com` 被 `*.example.com/*` Worker 拦成 404）。缓解：staging 必查 `content-type` 与文件大小；只挂 `drugcrossref.com/*` 一条最具体路由 |
| 风险 3 | 边缘缓存行为变化（Worker 在缓存之前执行，`fetch` 子请求才吃 Cache Rules）。缓解：staging 连打两次同一资源看 `cf-cache-status: MISS → HIT`；不达标就回滚路由 |

### 3.5 备选：不做（可接受，但要写明）

R2 默认 404 的状态码是**正确**的，只是内容不友好；`/404.html` 本身 200 可直接访问，SEO 上 404 页是 `noindex`，**没有排名损失**。如果不想在主域前面加一个 Worker（多一个故障点），v0.11.6 可以只做 Cache-Control，把自定义 404 记成 P2 待办。**建议仍做**：主域已是「主站」，错误页是品牌与排查体验的一部分，且成本 0、回滚秒级。

---

## 4. Cache-Control（v0.11.6）

### 4.1 现查与关键约束

- R2 对象**全部没有 `Cache-Control`**；HTML/JSON 不在 Cloudflare 默认缓存扩展名里 → `cf-cache-status: DYNAMIC`（每次都回 R2）。
- **关键坑**：`/data/idx/*` 的 `?v=BUILD_V` 是**代码版本**（`_compute_build_v()` **刻意不含数据库**，见 build.py L102–112，L107 注释），数据更新时 URL 不变 → **数据 JSON 不能设长缓存**，否则用户可能长期拿到旧索引。
- `assets/*` 的 `?v=BUILD_V` 只在 `build.py` / zh-Hant 字典变化时变，且这些改动本来就会让所有页面一起变 → **assets 可以 1 年 immutable**。
- Cloudflare 文档：**Response Header Transform 改 `Cache-Control` 不改变 Cloudflare 缓存判定**；要控制边缘缓存必须用 **Cache Rules**。

### 4.2 建议值

| 路径 | 边缘 TTL | 浏览器 TTL | 理由 |
|---|---|---|---|
| `*.html`、`/`、`/zh/`、`/es/`、`/zh-hant/` | **Bypass**（或 0） | **0**（must-revalidate 由可选 Header Transform 补） | 每版都变；ETag 304 足够；避免旧页脚/旧 canonical |
| `/assets/*` | **1 年** | **1 年 + immutable**（可选） | URL 带 `?v=`（build.py/字典哈希），内容变必换 URL |
| `/data/*`（`data/idx/*` + 其它 JSON/CSV） | **30 分钟** | **30 分钟** | `?v=` 是代码版本不是数据版本；数据每天更新，30 min 内可接受 |
| `/sitemap.xml`、`/robots.txt` | **10 分钟** | 10 分钟 | 每日更新，给搜索引擎留新鲜窗口 |
| 404（Worker 生成） | `no-store` | — | 错误 URL 不缓存 |

> 若想把 `/data/*` 提到 1 天/1 年，先做一个小改动：给数据请求加**数据版本**（例如 `DATA_V = sha1(DB 大小 + CHANGELOG 日期)`，只注入 `app.js` 里的 `data/...` URL，不动每页 `?v=`）。这是一次 `build.py` 改动（会换 `BUILD_V` → 全站重发），**建议与 v0.11.6 的其它 build.py 改动同批做**，否则为它单独发一版不值。

### 4.3 配置（Free 计划：Cache Rules 10 条、Transform Rules 10 条且无 regex）

**Cache Rules（4 条，按顺序）**：

1. `assets`：表达式 `starts_with(http.request.uri.path, "/assets/")`；Eligible for cache；Edge TTL **Ignore origin / 1 year**；Browser TTL **Override / 1 year**。
2. `data`：`starts_with(http.request.uri.path, "/data/")`；Eligible；Edge **30 min**；Browser **30 min**。
3. `sitemap/robots`：`http.request.uri.path eq "/sitemap.xml" or http.request.uri.path eq "/robots.txt"`；Eligible；Edge **10 min**；Browser 10 min。
4. `HTML 显式不缓存`：`ends_with(http.request.uri.path, ".html") or ends_with(http.request.uri.path, "/")`；**Bypass cache**；Browser TTL 0。

（HTML 本来默认就不缓存；第 4 条是「显式化」，防止以后有人开 Cache Everything 把 121k 页缓存住。）

**可选：Response Header Transform（≤2 条，给 `immutable` / `must-revalidate` 关键字）**：

- `/assets/*` → `Cache-Control: public, max-age=31536000, immutable`
- `*.html` / `*/` → `Cache-Control: public, max-age=0, must-revalidate`

注意：这两条**只改发给浏览器的头，不改变边缘缓存**（官方明确），边缘仍由上面 4 条 Cache Rules 决定；现有 Transform Rules 4 条 + 新增 2 条 = 6/10，不超限。

### 4.4 为什么不用对象元数据（`rclone --header-upload`）

- 本机 rclone **v1.76.0** 支持 `--header-upload` / `--metadata-set`；`deploy/sync_static.py` L126 也早就打印了 `--header-upload "Cache-Control: public, max-age=3600"` 模板。
- 但 `sync_r2.ps1` 用 `--checksum`，**未变化的文件不会重传 → 元数据不会补写**；要给 121,450 个对象补头只能 `--ignore-times` 全量重传（≈30 min、Class A ≈12 万），且 HTML 与 assets 需要两遍不同头（rclone 一条命令只能一个值）：
  ```powershell
  # 可选第二层（只有当次本来就全量重传才划算）：assets 长缓存，其余 HTML/JSON 走 revalidate；
  # 数据 JSON 的 30 min 仍由 Cache Rule 决定（Cache Rule 优先于对象头）。
  & tools\rclone.exe sync site\dist r2:drug-brand-crossref --checksum --fast-list --transfers 32 `
      --include "/assets/**" `
      --header-upload "Cache-Control: public, max-age=31536000, immutable"
  & tools\rclone.exe sync site\dist r2:drug-brand-crossref --checksum --fast-list --transfers 32 `
      --exclude "/assets/**" `
      --header-upload "Cache-Control: public, max-age=0, must-revalidate"
  ```
  （`sync_r2.ps1` 目前不传 `--header-upload`；要长期走元数据，需要改脚本 + 首次 `--ignore-times` 全量。**性价比低于 Cache Rules**。）
- 建议：v0.11.6 先只上 Cache Rules；对象元数据留到「下次本来就全量重传」时顺手做。

### 4.5 验证（本机被拦 → CI/外部节点）

```powershell
# 同一 URL 连打两次，期望 MISS → HIT；第二次有 Age
curl.exe -sI "https://drugcrossref.com/assets/style.css?v=<BUILD_V>"
curl.exe -sI "https://drugcrossref.com/assets/style.css?v=<BUILD_V>"
# 期望头：cache-control: public, max-age=31536000, immutable
#         cf-cache-status: MISS 然后 HIT

curl.exe -sI "https://drugcrossref.com/"
# 期望：cache-control: public, max-age=0, must-revalidate；cf-cache-status: DYNAMIC

curl.exe -sI "https://drugcrossref.com/data/idx/core.json"
# 期望：cache-control: public, max-age=1800；cf-cache-status: HIT（第二次）
```

> `verify_live.py` 每次请求都带 `?v=<时间戳>` 和 `Cache-Control: no-cache`（L163、L89），**永远 MISS**——它验「新鲜内容」，**不能拿来验缓存**；缓存必须用上面的 curl 或 `api.hackertarget.com/httpheaders`。

### 4.6 发布后 purge 策略

**不需要 purge**：HTML 走 bypass；`assets/*` 与「带 `?v=` 的数据文件」（core/pinyin/manifest/detail-\*/shard-\*/atc4-forms）发布即换 URL；sitemap/robots 只有 10 min TTL；**不带 `?v=` 的 JSON**（`data/aliases.json`、`confused.json`、`categories.json`、`terms.json`、`artg.json`、`maker-map.json`、`export-only.json`、`data/idx/cats.json`、`atc-ing.json`、`cat-*.json`）靠 30 min TTL 自然过期。**别用 Purge Everything**（会把 assets 全清，首屏变慢）。

---

## 5. `publish.ps1` loose-object 守卫（只给 diff，不改文件）

### 5.1 现查与阈值依据

| 项 | 数字 |
|---|---|
| 现缓存松散对象 | **112,810**（v0.11.1 发布后） |
| 每版新增 | v0.11.1 改了 112,796 文件 → 每版约 **+11 万** 松散对象 |
| 事故 | 2,440,758 松散 / 4.98 GB → push 对象枚举 **1h50m**（约 22 个/秒） |
| 报告建议阈值 | 30 万（设计预期 6 万的 5 倍） |
| 本报告建议 | **>12 万做增量 repack**（否则下一版 push 前就是 22 万）；**>30 万或 pack ≥8 做全量 repack** |

守卫位置：**commit 之后、push 之前**（这样本次提交新产生的 blob/tree 也一起进 pack；放 mirror 之前会漏掉本版对象）。用 `git repack -d`（只打包松散对象、不重写既有 pack）而不是报告里的 `-ad`（全量重写 1 GB，10–20 min）；每 4–6 版再由 `packs ≥ 8` 触发一次 `-ad` 合并。

### 5.2 diff

```diff
@@ 变量块（L112 `$PackBytes = 0` 之后）
 $PackBytes = 0
+$LooseObjects = 0
+$RepackSeconds = 0
+$PushSeconds = 0
 $ManifestPath = Join-Path $tmpRoot 'publish-opt\last-publish.json'
```

```diff
@@ function Fail 之后（L121 之后）
+function Invoke-CacheMaintenance {
+    # v0.11.6：gh-pages 缓存守卫。v0.11.1 曾因 244 万松散对象卡 push 1h50m。
+    # 在 commit 之后、push 之前跑：本次提交的 blob/tree 也一起进 pack，push 只枚举 pack 索引。
+    $co = @{}
+    foreach ($line in (& $Git -C $CacheDir count-objects -v)) {
+        if ($line -match '^([a-z-]+):\s*(\d+)$') { $co[$Matches[1]] = [int]$Matches[2] }
+    }
+    $loose = [int]$co['count']; $packs = [int]$co['packs']
+    $script:LooseObjects = $loose
+    Say ("cache: {0:N0} loose objects / {1:N0} MB / {2} pack(s)" -f `
+        $loose, ([double]$co['size'] / 1024), $packs)
+    if ($loose -le 120000 -and $packs -lt 8) { return }
+
+    $full = ($loose -gt 300000 -or $packs -ge 8)
+    Step $(if ($full) { 'Cache maintenance: full repack before push (10-20 min)' }
+                 else { 'Cache maintenance: packing loose objects before push' })
+    $t0 = Get-Date
+    if ($full) {
+        & $Git -C $CacheDir repack -adq --threads=4
+        if ($LASTEXITCODE -ne 0) { Fail 'git repack (full) failed; refusing to push with a bloated cache' }
+    } else {
+        & $Git -C $CacheDir repack -d -q --threads=4   # -d 自带 prune-packed
+        if ($LASTEXITCODE -ne 0) { Say 'warn: git repack failed; push may be slow' }
+    }
+    $script:RepackSeconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
+    $after = @{}
+    foreach ($line in (& $Git -C $CacheDir count-objects -v)) {
+        if ($line -match '^([a-z-]+):\s*(\d+)$') { $after[$Matches[1]] = [int]$Matches[2] }
+    }
+    $script:LooseObjects = [int]$after['count']
+    Say ("cache after: {0:N0} loose objects / {1} pack(s) / {2}s" -f `
+        $script:LooseObjects, [int]$after['packs'], $script:RepackSeconds)
+}
```

```diff
@@ DryRun 块之后（L398 之后，Step 'Pushing…' 之前）
+Invoke-CacheMaintenance
 Step 'Pushing incremental commit to gh-pages'
+$pushT0 = Get-Date
 & $Git -C $CacheDir push --progress origin HEAD:refs/heads/gh-pages
+$PushSeconds = [math]::Round(((Get-Date) - $pushT0).TotalSeconds, 1)
```

```diff
@@ Write-Manifest 字段（L134 附近）
     estimated_pack_bytes = $PackBytes
+    loose_objects = $LooseObjects
+    repack_s = $RepackSeconds
+    push_s = $PushSeconds
     elapsed_s     = ...
```

### 5.3 行为预期

| 松散对象 | 动作 | 预估耗时 | 说明 |
|---|---|---|---|
| ≤120,000 | 不处理 | 0 | 约一半发布落在这一档 |
| 120,001–300,000 | `repack -d -q --threads=4`（`-d` 自带 prune-packed） | 2–5 min（估，需首次实测） | 约每隔一版；打完 push 只枚举 pack |
| >300,000 或 pack ≥8 | `repack -adq --threads=4` | 10–20 min（报告口径） | 罕见；顺手合并多包 |

- `-DryRun` 在 push 前就退出，**不会触发 repack**（保持 dry-run 快）；正式发布才做维护。
- repack 失败：增量档只 `warn` 继续（松散对象 12–30 万仍可 push，只是慢）；全量档 `Fail`（30 万以上必须重来，避免复演 1h50m）。
- manifest 新增 `push_s` —— 落实事故报告「以后把 push 耗时写进发布报告」。
- 治本可选项（不在本任务）：`.tmp/publish-opt/gh-pages-cache.broken-20261111`（862 MB）可删；`gh-pages-cache` 862 MB 保留。

---

## 6. 风险与影响面（两个域名）

| 改动 | gh-pages（备份） | 主域 `drugcrossref.com` | 缓解 / 回滚 |
|---|---|---|---|
| `SITE_URL` 切主域 | 112,781 页 canonical/hreflang/OG 指主域（预期）；robots/sitemap 指主域；**不跑全量 verify_live** | canonical/hreflang/sitemap/OG 自洽；搜索引擎只认主域 | 回滚：`SITE_URL` 改回 + 重建 + 双通道重发（≈50 min）；保留上一版 `site/dist` 快照（`.tmp/dist-v0.11.x`，约 900 MB）可只回滚 R2（≈30 min） |
| R2 404 Worker | 无影响（gh-pages 自带 404 行为） | 不存在路径返回站点 404 页；`x-robots-tag: noindex` | 删路由（秒级）→ R2 直连默认 404 |
| Cache Rules | 无影响（GitHub Pages 不可自定义头） | HTML 不缓存；assets 1 年；data 30 min；sitemap 10 min | 逐条 disable（立即生效）；不需要 purge（HTML bypass / assets 带 `?v=` / 其余 TTL ≤30 min） |
| loose-object 守卫 | push 前多 2–5 min（约每隔一版） | 无影响 | 删掉守卫代码 / 恢复 `publish.ps1.bak` 后重跑 |

**顺序建议（v0.11.6 窗口）**：
1. 先做 ③ Cache Rules（纯边缘配置，可独立回滚，不动产物）；
2. 再做 ② Worker（先 stage 子域，再主域路由）；
3. ④ 守卫与 ②③ 无耦合，可同批提交，但必须等一次真实发布验证 `push_s`；
4. ① 若 v0.11.2 已发则只做 §2.4 / §2.5 守卫（纯 `verify_live.py` + workflow 改动，不影响站点产物）。

**公开口径影响**：主域成为唯一 canonical；gh-pages 从「双活」降为「备份/回滚副本」；`datapackage.json` / `dataset.jsonld` 的 `homepage` / `url` 改主域（外部若有引用需知会，目前无已知消费者）；GoatCounter 统计码不变（两域合计，与之前一致）。

---

## 7. 验收命令清单（可直接抄）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 0) 凭证形状（只读，不打印密钥）
& $py deploy/check_r2_env.py

# 1) 构建期：旧域残留必须 0（换域当版跑一次）
& $py -c "import os;r='site/dist';print('legacy_hits=',sum(open(os.path.join(d,f),'rb').read().count(b'fuarnos.github.io') for d,_,fs in os.walk(r) for f in fs))"
# 期望 legacy_hits= 0
& $py -c "s=open('site/dist/sitemap.xml',encoding='utf-8').read();print('main_locs=',s.count('<loc>https://drugcrossref.com/'),'legacy=',s.count('fuarnos.github.io'))"
# 期望 main_locs= 63685 legacy= 0（条数以当版为准）
& $py -c "import json;print(json.load(open('site/dist/datapackage.json',encoding='utf-8'))['homepage'])"
# 期望 https://drugcrossref.com/

# 2) 产物完整性（发布前，与 publish/sync 的门槛同源）
& $py deploy/ci_checks.py

# 3) R2 同步后对账（只读，允许）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -CheckOnly

# 4) 主域门禁（本机被 FortiGuard 拦 → 在 CI 的 verify-live 工作流里跑）
& $py deploy/verify_live.py --base https://drugcrossref.com/ --expect-version v0.11.6 `
      --expect-site-url https://drugcrossref.com/ --json-out .tmp/verify-live-r2.json
# 期望 ok=true / failures=[] / warnings=[]

# 5) 备份通道冒烟（--smoke-only 需先落地 §2.4 的建议 diff；
#    未落地前先手工：首页 200 + 页脚版本 + whats-new 顶部版本）
& $py deploy/verify_live.py --base https://fuarnos.github.io/drug-brand-crossref/ `
      --expect-version v0.11.6 --smoke-only

# 6) 404 / 缓存（本机被拦就用 CI 或外部节点）
curl.exe -sI "https://drugcrossref.com/this-page-does-not-exist-20261112"
curl.exe -s  "https://drugcrossref.com/this-page-does-not-exist-20261112" | Select-String "Page not found"
curl.exe -sI "https://drugcrossref.com/assets/style.css?v=<BUILD_V>"
curl.exe -sI "https://drugcrossref.com/data/idx/core.json"

# 7) 发布链缓存（发布前看一眼，别等 push 卡住）
& .\tools\git\cmd\git.exe -C .tmp\publish-opt\gh-pages-cache count-objects -v
```

---

## 8. 成本（全部免费额度内）

| 项 | 用量 | Free 额度 | 结论 |
|---|---|---|---|
| Worker 请求 | ≈ 站点页面浏览数（每个请求 1 次调用） | **100,000/日** | 0 元；超额 fail-open 降级 404 页 |
| Worker CPU | 10 ms/请求（只做一次 fetch + 404 时一次 R2 get） | 10 ms | 0 元 |
| Cache Rules | 4 条 | 10 条 | 0 元 |
| Transform Rules | 4（现有）+ ≤2（可选） | 10 条 | 0 元 |
| R2 存储 | 856.6 MiB | 10 GiB | 0 元 |
| R2 Class A（写） | 换域当版全量重传 ≈ **113,000** | 1,000,000/月 | 0 元（≈11%） |
| R2 Class B（读） | 缓存后大幅下降；未命中 1 次/请求 | 10,000,000/月 | 0 元 |
| 出网 | Cloudflare 自定义域不计 R2 出网费 | — | 0 元 |
| GitHub Actions（verify-live） | 公开仓库免费 | — | 0 元 |

**花钱的触发条件（不主动做）**：Workers 超过 10 万请求/日 → Workers Paid $5/月；想要「Custom Errors」原生错误页 → Pro 计划；两者都不必要。

---

## 9. 未做 / 待确认（只读边界）

1. **没有调 Cloudflare 读写 API**：仓库只有 R2 S3 凭据，没有 CF API token；Worker / Cache Rules / Transform Rules 需控制台人工配置，配置结果请按 §3.3 / §4.3 回填到本报告或发布报告。
2. **Worker 未实测**：pass-through 是否在 R2 自定义域前正常工作、`cf-cache-status` 是否仍 HIT，需 staging 子域验证（§3.3 第 4 步）——这是本方案最大的未知项。
3. **repack 实际耗时未测**：2–5 min 是估算；建议首次真实发布记录 `repack_s`（§5 diff 已加）。
4. **`verify_live.py` / `ci_checks.py` / `publish.ps1` 的 diff 只是建议**，本次未改文件；`site/build.py` 当前有 site-ui 的未提交改动（不是本工位）：`SITE_URL` 已改为 `https://drugcrossref.com/`（L63），但**尚未构建/发布**，`site/dist` 仍是 v0.11.1 旧产物（canonical 指旧域）。
5. **文档同步**：`DEPLOY.md`、`docs/托管迁移执行清单.md` §3（缓存表）、`deploy/sync_static.py` L126 的 `max-age=3600` 模板，落地后需与新口径对齐。

---

## 10. 复现（本次只读用到的命令）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 产物统计 / 旧域分布 / 体积差
& $py .tmp\scan_domain.py     # files_with_domain= 112785; occurrences= 339813
& $py .tmp\scan_missing.py    # html_missing_domain= 8458（全是 combo stub）
& $py .tmp\scan_delta.py      # len old/new/delta= 46/25/21; est saved= 7136073
& $py .tmp\inspect_facts.py   # sitemap urls= 63685, 全旧域；data/ 文件清单

# 发布缓存
& .\tools\git\cmd\git.exe -C .tmp\publish-opt\gh-pages-cache count-objects -v
# count: 112810 / size: 225988 / in-pack: 2385899 / packs: 1 / size-pack: 1069837

# 远端 gh-pages 现状
& .\tools\git\cmd\git.exe ls-remote origin gh-pages
# ec99a135527cf20005afbbc657bf2919449d0eee  refs/heads/gh-pages
```

外部依据（只作事实核对，未据此执行任何写操作）：
[Cloudflare R2 Public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/)（自定义域/缓存/无 error document）、
[Workers Limits](https://developers.cloudflare.com/workers/platform/limits/)（Free 10 万请求/日、静态资产 2 万文件）、
[Custom Errors](https://developers.cloudflare.com/rules/custom-errors/)（Free 不可用）、
[Snippets](https://developers.cloudflare.com/rules/snippets/)（Free 不可用）、
[Cache Rules](https://developers.cloudflare.com/cache/how-to/cache-rules/)（Free 10 条）、
[Transform Rules](https://developers.cloudflare.com/rules/transform/)（Free 10 条、无 regex）、
[Response Header Transform](https://developers.cloudflare.com/rules/transform/response-header-modification/)（改头不改缓存判定）、
[Workers Routes](https://developers.cloudflare.com/workers/configuration/routing/routes/)（Routes 优先于 R2 自定义域）、
[R2 缓存](https://developers.cloudflare.com/cache/interaction-cloudflare-products/r2/)（HTML/JSON 默认不缓存）。
