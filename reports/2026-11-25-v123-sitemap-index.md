# v1.2.3 源码：sitemap 索引拆分（170,435 → 4 片）+ T14-C 软上限 150k 分档告警（frontend 自验报告）

- 日期：2026-11-25（北京时间凌晨谷段；本机 US-Pacific 2026-11-24 晚）
- 工位：`frontend`；任务：共享任务板 `task-2`
- 范围：只改 `site/build.py`、`db/nightly_metrics.py`（只读 dist 的计数口径）、`CHANGELOG.md`、`data/release_notes_i18n.json`、本报告。
  **未 commit、未跑生产构建（`site/dist`）、未跑 `sync_r2.ps1`、未改 `deploy/`、未写 `data/drugs.db`。**
- 自验构建：`SITE_OUT=.tmp/frontend-v123`，两轮（A / A′），跑完已删除临时目录。

## 0. 结论（先行）

| 验收项 | 结果 | 证据 |
|---|---|---|
| `sitemap.xml` 是 `<sitemapindex>` | ✅ 4 个 `<sitemap>` | §2.1 |
| 分片数 / 每片 URL | ✅ 4 片：**50,000 / 50,000 / 50,000 / 20,435**，每片 ≤ 50,000 | §2.1 |
| 分片合计 = 旧口径 | ✅ **170,435**（与 v1.2.2 单文件一致，本次新增静态页 0） | §2.1 |
| 每片 XML 可解析 | ✅ `xml.etree.ElementTree` 逐片解析为 `<urlset>`，`<url>` 数如上行 | §2.1 |
| URL 顺序与现在完全一致 | ✅ 与 `site/dist/sitemap.xml`（v1.2.2 单文件）的 `<loc>` 序列**逐项一致**：170,435 项 / 差异 **0**（仅 `lastmod` 随构建日 2026-11-24→2026-11-25） | §2.2 |
| A/A′ 确定性 | ✅ 第二次构建：`sitemap.xml` + 4 片共 **5 个文件逐字节 0 差异**（sha256 全同） | §2.3 |
| 静态产品页数 | ✅ **84,000**（pins 84,000，`+0 restored`） | §2.4 |
| `[STATIC]` 分档告警 | ✅ **0 条**（84,000 < 90,000） | §2.4 |
| 九语 i18n 门禁 | ✅ `deploy/i18n_check.py` **FAIL 0**（WARN 27 / INFO 43，均为存量）；`release notes: CHANGELOG 91 版 / json 91 版，最新 v1.2.3 译文齐` | §2.5 |
| 临时目录清理 | ✅ `.tmp/frontend-v123`、`.tmp/frontend-v123-a` 已删；D 盘空闲 11.37 GB | §3 |

**一句话**：v1.2.3 的 sitemap 已从「单文件 170,435 URL（超协议上限 3.4 倍）」变成「索引 + 4 个稳定名分片（每片 ≤ 50,000）」，URL 顺序与内容 0 变化、A/A′ 0 差异；软上限 150,000 与三档告警已就位，当前 84,000 不触发任何 `[STATIC]` 行。发布（生产构建 / sync / verify）留给 `release`。

## 1. 为什么拆（T14-C 决策口径）

- sitemaps.org / Google 的协议上限：**单个 sitemap 文件 50,000 URL（且 ≤ 50 MB 未压缩）**。
- v1.2.2 线上/产物是**单文件 170,435 URL**，= 上限的 **3.4 倍**；超出部分搜索引擎没有义务抓取。
- T14 第 3 批把静态产品页 84,000 → 114,000，站点 URL 会到 **≈200,000**，更不可能塞进单文件。
- Lead 2026-11-25 决策：**T14-C 取选项 ③「与 sitemap 方案一起做」** —— 本版同时
  ① 拆 sitemap index（解协议上限）；② `PRODUCT_STATIC_CAP` 90,000 → **150,000** + 90k/120k/140k 分档告警（为第 3 批铺路，仍是只告警的软上限）。

## 2. 改动与自验

### 2.1 `site/build.py` · `build_seo_files()`：index + 分片

- 新增模块常量 `SITEMAP_SHARD_MAX = 50_000`。
- `sitemap.xml` 改为 `<sitemapindex>`；URL 仍先 `urls.sort()`，再按 50,000 切片写 `sitemap-1.xml` … `sitemap-N.xml`（空站兜底写 1 个空 `<urlset>`，索引至少 1 项）。
- 分片内仍是 `<url><loc>…</loc><lastmod>…</lastmod></url>`，`lastmod` 逻辑不变；index 内 `<sitemap><loc>{SITE_URL}sitemap-N.xml</loc><lastmod>…</lastmod></sitemap>`，**全部绝对地址**。
- 分片名是**稳定名**（不带版本号 / 哈希，符合增量发布契约）；`robots.txt` 不变（`Sitemap: https://drugcrossref.com/sitemap.xml`）。
- 打印行（便于 CI/报告核对）：

```
  seo files  : 404 + robots + sitemap index (4 shards, 170,435 urls) + deploy verify
  sitemap    : sitemap.xml → sitemap-1.xml…sitemap-4.xml（50,000 / 50,000 / 50,000 / 20,435 = 170,435 URL，每片 ≤ 50,000）
```

索引全文（实测 522 B）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://drugcrossref.com/sitemap-1.xml</loc><lastmod>2026-11-25</lastmod></sitemap>
  <sitemap><loc>https://drugcrossref.com/sitemap-2.xml</loc><lastmod>2026-11-25</lastmod></sitemap>
  <sitemap><loc>https://drugcrossref.com/sitemap-3.xml</loc><lastmod>2026-11-25</lastmod></sitemap>
  <sitemap><loc>https://drugcrossref.com/sitemap-4.xml</loc><lastmod>2026-11-25</lastmod></sitemap>
</sitemapindex>
```

分片实测（`xml.etree` 解析 + `<loc>` 计数）：

| 分片 | URL 数 | 字节 | 首条 `<loc>` | 末条 `<loc>` |
|---|---|---|---|---|
| `sitemap-1.xml` | 50,000 | 5,803,666 | `https://drugcrossref.com/` | `…/name/e-z-gas-ii.html` |
| `sitemap-2.xml` | 50,000 | 6,267,933 | `…/name/e-z-hd.html` | `…/product/CN-XA02BAL050E00-b74b2b63.html` |
| `sitemap-3.xml` | 50,000 | 5,337,951 | `…/product/CN-XA02BAL050E00-b7557fc4.html` | `…/product/NO-darunavir-zentiva-3f30077a.html` |
| `sitemap-4.xml` | 20,435 | 2,238,228 | `…/product/NO-darunavir-zentiva-702c2203.html` | `…/zh/whats-new.html` |
| **合计** | **170,435** | 19,648,300（+索引 522） | — | — |

旧单文件 `site/dist/sitemap.xml` = 19,647,448 B；拆分后多出 852 B（4 份 XML 头尾 + 索引行开销）。语法抽样（`sitemap-1.xml`）：

```
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://drugcrossref.com/</loc><lastmod>2026-11-25</lastmod></url>
  ...
  <url><loc>https://drugcrossref.com/name/e-z-gas-ii.html</loc><lastmod>2026-11-25</lastmod></url>
</urlset>
```

### 2.2 URL 序列与旧单文件逐项一致

用 `xml.etree` 把 v1.2.2 单文件的 `<loc>` 列表与「4 片按序拼接」的 `<loc>` 列表比对：

```
old locs 170435 new locs 170435
loc 序列逐项一致: True
差异项数: 0
```

差异只在 `<lastmod>`：旧产物是 2026-11-24（上一构建日），本次构建是 2026-11-25（`LATEST_DATE`/当天），属预期，不是内容变化。

### 2.3 A/A′ 确定性（第二次同参数构建）

```
A: 5 个 sitemap 文件；B: 5 个
  sitemap.xml    A=15700a5bdafe  B=15700a5bdafe  same
  sitemap-1.xml  A=ff9f7acd9ca0  B=ff9f7acd9ca0  same
  sitemap-2.xml  A=7809f9917fa6  B=7809f9917fa6  same
  sitemap-3.xml  A=901a728a9ace  B=901a728a9ace  same
  sitemap-4.xml  A=a0baca421f1d  B=a0baca421f1d  same
A/A′ 逐字节差异：0 个文件
```

两次构建的 `build version` 都是 `0590199023 (content hash)`；构建结束后用最终源码重算 `_compute_build_v()` 仍为 `0590199023` → **自验用的源码 = 当前工作区源码**（`_compute_build_v` 只哈希 build.py 自身与 zh-Hant 字典）。

### 2.4 T14-C：软上限 150k + 分档告警

- `PRODUCT_STATIC_CAP`: 90,000 → **150_000**（注释写明「第 3 批 TOP_N 84,000→114,000 之前先抬软上限；仍是只告警、真正 prune pins 要人拍板」）。
- 新增 `PRODUCT_STATIC_TIERS = (90_000, 120_000, 140_000)`：静态页数达到某档即打印一行
  `[STATIC] {n} pages ≥ {tier} — 分档告警（提示档位，不影响构建、不删 pins；软上限 150,000）`；
  达到 150,000 再打印 `!! [STATIC] WARN: …`（仍不失败）。
- 本次构建实测：`static pins : 84,000 pinned pids, +0 restored this build`、`static top N: 84,000 products, markets 16`、`product : 84,000 static pages`；两轮构建日志里 `[STATIC]` 行 **0 条**（84,000 < 90,000）。
- 副作用（预期）：`save_static_pins()` 每次构建都会重写 `data/product/static_pins.json`；本次因 `description` 改为引用常量而出现 1 行差异（**pids 84,000 条不变**，`count` 仍 84,000）。

### 2.5 `db/nightly_metrics.py`：sitemap 计数改「索引 → 分片求和」

- `dist_metrics()` 里 `sitemap_urls`：若 `sitemap.xml` 含 `<sitemapindex` → 解析各分片 `<loc>`、逐片累加 `<url>`；否则仍按旧单文件数 `<url>`。指标口径与 v1.2.2 完全一致，不会误报「sitemap 下跌 >1%」。
- 单测（临时 fixture，两情形）：索引 + 2 片（3+2）→ `sitemap_urls = 5`；旧单文件 4 条 → `sitemap_urls = 4`。
- 全量临时 dist 现算：`files 302,111 / html_total 301,305 / sitemap_urls 170,435 / total_bytes 3,010.6 MB`。
- 对照 v1.2.2 产物：`site/dist` 302,107 文件 → 本次 **302,111**（+4，正好是多出的 4 个分片）；0 字节文件 **0**。

### 2.6 CHANGELOG 与九语 release notes

- `CHANGELOG.md` 顶部新增 `## v1.2.3 — 2026-11-25`，3 条用户可感知变化（sitemap 索引 / 地址一个没少 / 为下一批静态页铺路）。
- `data/release_notes_i18n.json` 新增 `v1.2.3`：**3 条 × 9 语**（zh / en / es / zh-Hant / fr / ko / ja / cs / lv），键集一致、无空值；`_meta` 同步 90→**91 版**、357→**360 条**、`generated_at` 更新。
- `site/build.py` 的 whats-new 相关常量无需改：`build_whats_new()` 已按 9 语渲染（`data-lang-block` 九块），`_inject_release_liners()` 自动取最近 3 版注入首页「最近更新」；本版只是新增 JSON 条目。
- 门禁结果（`PYTHONIOENCODING=utf-8` 下跑，否则 Windows GBK 控制台打印韩文会 `UnicodeEncodeError`，与内容无关）：

```
== i18n 一致性门禁（en / es / zh / zh-Hant / fr / ko / ja / cs / lv）==
release notes: CHANGELOG 91 版 / json 91 版，最新 v1.2.3 译文齐；缺 0 版（0 条待译）
FAIL 0 / WARN 27 / INFO 43
exit=0
```

WARN 27（hardcoded 25 + pseudo-suspect 2）与 INFO 43 均为存量项，本次未新增。

- 附加：`etl/check_translations.py`（报告模式，exit 0）`release_notes={'versions': 91, 'items': 360}`；v1.2.3 只多出 2 条与 v1.2.2 同型的 `html` 警告（zh 用 `<产品号>`、en/es 用 `<pid>`，历史版本同样被标，属已知基线），**没有新的数字 / 占位符不一致**。

## 3. 自验命令（可复核）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 第一轮构建（临时目录，绝不写 site/dist）
$env:SITE_OUT = '.tmp/frontend-v123'
& $py site/build.py            # 等 == done ==（约 14 分钟）
# 2) 备份 A 的 sitemap 文件后，同参数再构建一次（A′）
Copy-Item .tmp\frontend-v123\sitemap*.xml .tmp\frontend-v123-a\
& $py site/build.py
# 3) 校验：索引 / 分片 / 每片 ≤50,000 / 可解析 / 与旧单文件 loc 序列一致 / A-A′ 0 差异
& $py .tmp/verify_sitemap_v123.py check .tmp/frontend-v123 site/dist/sitemap.xml
& $py .tmp/verify_sitemap_v123.py diff  .tmp/frontend-v123-a .tmp/frontend-v123
# 4) i18n 门禁
& $py deploy/i18n_check.py     # FAIL 0
# 5) 清理（本步已执行）
Remove-Item -Recurse -Force .tmp\frontend-v123,.tmp\frontend-v123-a
```

> 校验脚本 `.tmp/verify_sitemap_v123.py` 是本次一次性临时脚本（`.tmp/` 不入库）：`check` 用 `xml.etree` 逐片解析并统计 `<loc>`，`diff` 对 5 个 sitemap 文件做 sha256 比对。

## 4. 未做 / 交给 release 与 Lead

- **未跑生产构建**：`site/dist` 仍是 v1.2.2 产物（302,107 文件 / 单文件 sitemap 170,435），本轮自验全部只写 `.tmp/frontend-v123`。生产构建由 `release` 执行。
- **`deploy/` 已由 release 改成支持 sitemap index**（本报告只读核对，未改）：`deploy/ci_checks.py` L396-422 走「索引 → 逐片 GET/读盘，每片 ≤ 50,000，求和 ≥ 下限」；`deploy/verify_live.py` L486-527 走 `sitemap_kind` / `sitemap_shards`，逐片 200 + 可解析 + 求和。本次输出格式（索引 `<loc>` 绝对地址、分片 `<urlset>`、稳定名 `sitemap-N.xml`）与这两处约定一致。
- **发布注意**：本版首次把 `sitemap.xml` 从 18.7 MiB 单文件换成 522 B 索引 + 4 个新分片（合计 ≈19.6 MB）；增量发布预计 **+5 个 PUT**（`sitemap.xml` 改写 + 4 个新文件），`-DryRun` planned 应把这 5 个算进去。旧 URL 与 `robots.txt` 都不变。
- 未 commit / 未发布会 / 未改需求队列与交接文档（Lead 负责）。
- 本报告不涉及发布结论；SEO 层面「索引被搜索引擎重新抓取、分片全部收录」需上线后由 `verify_live` 与 Search Console 观察，属 release/Lead 的发布后事项。

## 5. 风险与边界

- **分片名稳定**（`sitemap-N.xml`，不带版本号/哈希）：增量发布只上传变化分片；以后若 URL 总数下降导致分片数减少，旧分片对象不会被自动删除（R2 上残留），但本版只增不减，无影响。
- **每片 `lastmod` 相同**（都取构建日 `LATEST_DATE`/当天）：协议允许，且与旧单文件逐条 `lastmod` 的口径一致（旧文件所有条目的 lastmod 也相同）。
- **空站兜底**：`urls` 为空时仍写 1 个空 `<urlset>` 并在索引里引用，避免出现「索引指向不存在的分片」。
- **i18n 打印环境**：`deploy/i18n_check.py` 在 Windows GBK 控制台打印含韩文的 WARN 明细会抛 `UnicodeEncodeError`（脚本本身 FAIL 0）；本次用 `PYTHONIOENCODING=utf-8` 规避，属存量脚本问题，未在 `deploy/`（release 范围）内修改。
