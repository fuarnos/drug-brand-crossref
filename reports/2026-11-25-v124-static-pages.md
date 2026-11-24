# v1.2.4：T14 第 3 批静态产品页 84,000 → 114,000（frontend 自验报告）

- 日期：2026-11-25（北京时间凌晨谷段；本机 US-Pacific 2026-11-24 晚）
- 工位：`frontend`；任务：共享任务板 `task-5`（blocked_by task-4 = v1.2.3 sitemap index 上线，已完成）
- 基线：HEAD `bed03b561db`（v1.2.3 已上线，verify 54/0/0）；pins/静态页 **84,000**；sitemap **170,435 / 4 片**；`PRODUCT_STATIC_CAP = 150,000`（v1.2.3 已抬，本版**不动**）
- 自验构建：`SITE_OUT=.tmp/frontend-v124`，共两轮（A / A′），跑完已删除临时目录。
- **未 commit、未跑生产构建（`site/dist` 仍是 v1.2.3 线上产物）、未跑 `sync_r2.ps1` / `verify_live`、未改 `deploy/` / `data/drugs.db` / 队列与交接文档。**

## 0. 结论（先行）

| 验收项 | 结果 | 证据 |
|---|---|---|
| `PRODUCT_STATIC_TOP_N` | ✅ 84,000 → **114,000**（`PRODUCT_STATIC_CAP` 保持 150,000） | §1 |
| 静态页数 | ✅ **114,000** | §2.1 |
| pins 只增不减 | ✅ 84,000 → **114,000**：added **30,000**、missing **0**、排序/唯一 | §2.1 |
| `[STATIC]` 分档告警 | ✅ **1 条** 90,000 档提示（114k < 120k，预期）；无 120k/140k/150k 行 | §2.1 |
| sitemap | ✅ **5 片**：50,000 / 50,000 / 50,000 / 50,000 / 435 = **200,435**，每片 ≤ 50,000、逐片可解析 | §2.2 |
| 旧 URL 保留 | ✅ 与 v1.2.3 线上一笔不差：旧 URL 丢失 **0**，新增 **30,000** 且全部是 `/product/<pid>.html` | §2.2 |
| A/A′ 确定性 | ✅ 第二次构建 `sitemap.xml` + 5 片共 **6 个文件逐字节 0 差异**（sha256 全同） | §2.3 |
| 0 字节文件 | ✅ **0**（临时 dist 332,112 文件） | §2.4 |
| 九语 i18n | ✅ `deploy/i18n_check.py` **FAIL 0**（WARN 27 / INFO 43 均存量）；release notes「92 版 / 92 版，最新 v1.2.4 译文齐」 | §2.5 |
| 临时目录 / 磁盘 | ✅ `.tmp/frontend-v124`、`.tmp/frontend-v124-a` 已删；D 盘空闲 11.33 GB（自验前 11.34） | §3 |

**一句话**：静态产品页 84,000 → 114,000（pins 只增不减，旧 URL 0 丢失），sitemap 自动扩到 5 片 200,435 条（≤50k/片），A/A′ 0 差异、0 字节 0、i18n FAIL 0；生产构建与发布留给 `release`。

### ⚠️ 与任务书的一处偏差（必要修正，请 Lead 知悉）

- 任务书只要求改 `PRODUCT_STATIC_TOP_N`，但**首跑（只改 TOP_N）静态页只到 86,971**：`PRODUCT_STATIC_MARKET_CAP = 6,000` 在 114,000 轮转时**先于 TOP_N 截断**（16 个合格市场：13 个吃满 6,000 + LV 3,391 + MX 542 + SG 5,038 = 86,971）。
- 因此本版**同时把 `PRODUCT_STATIC_MARKET_CAP` 6,000 → 12,000**（同一文件、同一「每市场硬上限」护栏；12,000 × 16 市场 > CAP 150,000，轮转不再成为瓶颈）。首跑产物已由第二次构建覆盖，pins 单调只增，无副作用。
- 另：任务书写的「+29,824」是 v1.2.2（54,176→84,000）的增量；本批 **84,000 → 114,000 = +30,000**，恰好等于 F7「每夜新增 ≤30,000 页」的上限（不超限）。

## 1. 改动清单（只改这些）

| 文件 | 改动 |
|---|---|
| `site/build.py` | `PRODUCT_STATIC_TOP_N` 84,000 → **114,000**（注释写明第 3 批）；**`PRODUCT_STATIC_MARKET_CAP` 6,000 → 12,000**（原因见上，注释写明「原值在 114k 轮转会先于 TOP_N 截断」）；`select_static_product_ids()` docstring 同步 114k。`PRODUCT_STATIC_CAP` **不动**（150,000）。 |
| `data/product/static_pins.json` | 构建自动追加：84,000 → **114,000**（append-only、排序、`count` 同步；构建每次都会重写该文件）。 |
| `CHANGELOG.md` | 顶部新增 `## v1.2.4 — 2026-11-25`，3 条用户可感知变化。 |
| `data/release_notes_i18n.json` | 新增 `v1.2.4`：**3 条 × 9 语**（zh/en/es/zh-Hant/fr/ko/ja/cs/lv），键集一致、无空值；`_meta` 91→**92 版**、360→**363 条**、`generated_at` 更新。 |
| `reports/2026-11-25-v124-static-pages.md` | 本报告。 |

未改：`PRODUCT_STATIC_CAP`、`deploy/**`、`data/drugs.db`、`docs/谷段需求队列.md`、交接文档；未删任何已发布 pid。

## 2. 自验

### 2.1 pins 只增不减 + 静态页数 + [STATIC]

构建输出（第二轮，最终口径）：

```
selecting static product pages ...
  static pins : 86,971 pinned pids, +0 restored this build      ← 首跑后 pins 已涨到 86,971
  [STATIC] 114,000 pages ≥ 90,000 — 分档告警（提示档位，不影响构建、不删 pins；软上限 150,000）
  static top N: 114,000 products, markets 16
    (AU 7,146, CA 8,229, CN 8,228, CZ 8,228, ES 8,228, FR 8,228, GB 8,229, JP 8,228,
     KR 8,228, LV 3,391, MX 542, MY 7,372, NO 8,228, SG 5,038, TW 8,228, US 8,229)
building product pages ...
  product     : 114,000 static pages (top 114,000)
```

pins 比对（对照构建前快照 `.tmp/pins-before-v124.json`，84,000 条）：

```
before : 84,000
after  : count=114,000 pids=114,000 unique=114,000 sorted=True
added  : 30,000（= 114,000 − 84,000）
missing: 0
total == 114,000: True
```

- `[STATIC]`：最终两轮构建各 **1 条**（都是 90,000 档）；**没有** 120,000 / 140,000 / 150,000 行（114,000 < 120,000，属预期）。
- 首跑（只改 TOP_N、未改市场上限）日志 `.tmp/build-v124-a.log` 里 `[STATIC]` 为 0 条（当时只有 86,971 页，未到 90k 档）——该跑产物已被覆盖，仅作偏差证据保留。

### 2.2 sitemap：5 片 200,435、旧 URL 0 丢失

索引 / 分片（`xml.etree` 逐片解析 + `<loc>` 计数）：

| 分片 | URL 数 | 首条 `<loc>` | 末条 `<loc>` |
|---|---|---|---|
| `sitemap-1.xml` | 50,000 | `https://drugcrossref.com/` | `…/name/e-z-gas-ii.html` |
| `sitemap-2.xml` | 50,000 | `…/name/e-z-hd.html` | `…/product/CA-02416131.html` |
| `sitemap-3.xml` | 50,000 | `…/product/CA-02416158.html` | `…/product/JP-6131001M1088.html` |
| `sitemap-4.xml` | 50,000 | `…/product/JP-6131001M1100.html` | `…/product/US-0904-5847.html` |
| `sitemap-5.xml` | 435 | `…/product/US-0904-5853.html` | `…/zh/whats-new.html` |
| **合计** | **200,435** | — | — |

索引仍是 `<sitemapindex>`（5 个 `<sitemap>`，绝对地址 + `lastmod 2026-11-25`），`robots.txt` 不变；每片 ≤ 50,000 且 XML 可解析。

与 v1.2.3 线上产物（`site/dist/sitemap.xml`，4 片 170,435）做集合对比：

```
v1.2.3 线上 sitemap URL: 170,435
v1.2.4 自验 sitemap URL: 200,435
旧 URL 丢失: 0 （期望 0）
新增 URL: 30,000（期望 30,000）
新增全部 /product/ 静态页: True
新增样例: …/product/AU-10036F-keyomega-742c24.html … …/product/US-0904-7400.html
```

（170,435 + 30,000 = 200,435，与任务书预期一致。）

### 2.3 A/A′ 确定性

两次同参数构建的 6 个 sitemap 文件 sha256 全同：

```
A: 6 个 sitemap 文件；B: 6 个
  sitemap.xml    A=bf0ceee5a6e5  B=bf0ceee5a6e5  same
  sitemap-1.xml  A=ff9f7acd9ca0  B=ff9f7acd9ca0  same
  sitemap-2.xml  A=aea77f2646a1  B=aea77f2646a1  same
  sitemap-3.xml  A=1654ac91c2b3  B=1654ac91c2b3  same
  sitemap-4.xml  A=28f0d2bb4b04  B=28f0d2bb4b04  same
  sitemap-5.xml  A=ee0337b4d9de  B=ee0337b4d9de  same
A/A′ 逐字节差异：0 个文件
```

两次构建 `build version` 均为 `1196836084`；用最终源码重算 `_compute_build_v()` 仍为 `1196836084` → 自验源码 = 当前工作区源码。

### 2.4 体积 / 文件数 / 耗时

| 指标 | v1.2.3 产物 | v1.2.4 自验 | 变化 |
|---|---|---|---|
| dist 文件数 | 302,111 | **332,112** | +30,000 产品页 + 1 个新分片 |
| HTML 总数 | 301,305 | **331,305** | +30,000 |
| sitemap URL | 170,435 | **200,435** | +30,000 |
| 0 字节文件 | 0 | **0** | — |
| total_bytes | 3,010.6 MB | **3,227.4 MB** | +216.8 MB |
| 构建耗时 | ≈14 分钟 | **11.1 / 11.3 分钟**（A / A′） | 本机负载不同，仅供参考 |

### 2.5 九语 i18n

```
$env:PYTHONIOENCODING='utf-8'; & $py deploy/i18n_check.py
== i18n 一致性门禁（en / es / zh / zh-Hant / fr / ko / ja / cs / lv）==
release notes: CHANGELOG 92 版 / json 92 版，最新 v1.2.4 译文齐；缺 0 版（0 条待译）
FAIL 0 / WARN 27 / INFO 43
exit=0
```

WARN 27（hardcoded 25 + pseudo-suspect 2）与 INFO 43 与 v1.2.3 基线相同，本次未新增；构建期 `i18n rules : 最新版 v1.2.4 四语齐全` 亦通过。

## 3. 命令（可复核）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'

# 0) 构建前快照 pins（只读备份）
Copy-Item data\product\static_pins.json .tmp\pins-before-v124.json

# 1) 构建 A（临时目录，绝不写 site/dist）
$env:SITE_OUT = '.tmp/frontend-v124'
& $py site/build.py                      # == done ==（11.1 分钟）
Copy-Item .tmp\frontend-v124\sitemap*.xml .tmp\frontend-v124-a\

# 2) 构建 A′（同参数，覆盖同一临时目录）
& $py site/build.py                      # == done ==（11.3 分钟）

# 3) 校验
& $py .tmp/check_pins_v124.py                                   # pins added 30,000 / missing 0
& $py .tmp/verify_sitemap_v123.py check .tmp/frontend-v124      # 5 片 / 200,435 / 每片 ≤50k / 可解析
& $py .tmp/verify_sitemap_v123.py diff  .tmp/frontend-v124-a .tmp/frontend-v124   # A/A′ 0 差异
& $py deploy/i18n_check.py                                      # FAIL 0

# 4) 清理（已执行）
Remove-Item -Recurse -Force .tmp\frontend-v124,.tmp\frontend-v124-a
```

> `.tmp/check_pins_v124.py`、`.tmp/verify_sitemap_v123.py` 是一次性临时脚本（`.tmp/` 不入库）。

## 4. 交给 release / Lead 的发布提示

- **生产构建必须重跑**（本报告只写 `.tmp`）：`site/dist` 当前是 v1.2.3 线上产物，不能复用。
- **增量发布规模**：新增 30,000 个 `/product/<pid>.html` + 1 个新分片 `sitemap-5.xml`；`sitemap.xml` 索引改写（5 行）；既有 name/drug 等长尾页因新增静态页链接会有「同位置仅链接目标变化」的改写（同 v1.2.2 口径）。预计 planned ≈72k —— 按 AGENTS §6 内容扩容例外，需 release 出 `-DryRun` planned 后由 Lead `-ApproveLarge` 拍板（Lead 已预核：当月累计 ≈40.2 万 < 50 万 T14 上限、< 90 万停线）。
- **pins 文件要随源码保留**：`data/product/static_pins.json` 已由构建写到 114,000（append-only）；发布前提交/保留该文件，否则下次构建会以为只发布过 84,000（虽然结果相同，但 pins 是「已发布过」的唯一记录）。
- 发布后 `verify_live --expect-version v1.2.4` 应看到 `sitemap-shards` 5 片全部 200 + `sitemap-urls` 200,435。

## 5. 风险与边界

- **本批用满 F7 每夜 30,000 页上限**（+30,000），下一批需等新的夜间窗口与当月预算；剩余可补产品 ≈617k。
- **sitemap 总量 200,435 已越过旧的「20 万红线」**——这正是 v1.2.3 先上线 sitemap index 的原因；现在单文件 ≤50k、索引 5 片，协议上无风险（上限是每索引 50,000 个 sitemap）。
- **市场轮转上限**已抬到 12,000/市场：本批 16 个市场里 13 个吃到 ≈8,228（TOP_N 截断点），LV/MX/SG 因合格集不足仍只到 3,391/542/5,038；若后续继续扩容，需再评估这两处（TOP_N / MARKET_CAP）与 CAP 150,000 的关系。
- `[STATIC]` 90k 档提示是**预期告警**（提示用、不失败）；下次到 120k 会出现第 2 条。
- 首跑（未改市场上限）的 86,971 页产物已被覆盖；pins 单调只增，无脏数据。
