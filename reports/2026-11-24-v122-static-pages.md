# v1.2.2 静态产品页第 2 批：50,000 → 84,000（+29,824 页，pins 只增不减）

- 日期：2026-11-24（北京时间）｜工位：`frontend`｜任务：共享任务板 `task-1`（T14 第 2 批）
- 版本主题：**v1.2.2**（本工位只改站点源码与自验产物，**不 commit / 不发布 / 不写 `site/dist`**）
- 写权限内改动：`site/build.py`（4 行）、`data/product/static_pins.json`（自验构建 append-only 增长）、`reports/`（本文件）
- 自验构建命令（临时目录，两次）：

  ```powershell
  $py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
  $env:SITE_OUT = '.tmp/frontend-t14'      # A：本批产物
  & $py site/build.py                       # == done ==，9.9 min
  $env:SITE_OUT = '.tmp/frontend-t14-b'    # A′：确定性复跑
  & $py site/build.py                       # == done ==，10.4 min
  ```

- 生产构建与上线归 `release`；两个自验目录已按磁盘纪律删除（只留数字）。

## 0 结论（先行）

1. **静态产品页 54,176 → 84,000（+29,824，落在任务给的 +28,000…+31,000 区间）**：`PRODUCT_STATIC_TOP_N`
   50,000 → 84,000；选择规则 / 轮转顺序 / URL 形状 / canonical / sitemap 生成逻辑一律未动，
   `roundrobin` 的前缀天然不变（旧 54,176 个已发布 pid **一个不少**，缺失 0）。
2. **pins 只增不减已核实**：`data/product/static_pins.json` 54,176 → **84,000**，旧集合 ⊆ 新集合（missing 0，
   added 29,824），`pids` 排序去重、`count` 字段一致；`+0 restored` 说明本批 84,000 页全部落在新 Top N 内。
3. **sitemap 140,611 → 170,435 URL**（+29,824，仍 < 180,000 红线）；dist **272,283 → 302,107 文件**（+29,824），
   体积 **2,792 MB → 3,010 MB**（+218 MB / +7.8%，10^6 口径），0 字节文件 0。
4. **软上限 60,000 → 90,000**，本批 84,000 **未触发告警**（余 6,000）；超限逻辑仍是「只报警不删 pins」。
5. 首屏守卫改前 / 改后 **24 次扫描结论一致**（唯一未达项 `coverage@390x844 items 3.5` 是既有项），
   baseline 退化 **0**；`ci_checks --fast` **PASS 8 / FAIL 0 / SKIP 5**；A/A′ 除「CHANGELOG 在两次构建之间
   新增 v1.2.2 一节」这一**外部改动**外 **0 差异**（302,083 / 302,107 文件大小一致、抽样哈希 0 不一致）。

## 1 改动（`site/build.py`，4 行，`git diff --stat` = 4 insertions / 4 deletions）

| 位置 | 改前 | 改后 |
|---|---|---|
| `PRODUCT_STATIC_TOP_N` | `50_000` | `84_000`（注释同步「v1.2.2 第 2 批：50,000 → 84,000」） |
| `PRODUCT_STATIC_CAP` | `60_000` | `90_000`（软上限，超限只报警不删 pins） |
| `save_static_pins()` description | 上限 60000 | 上限 90000 |
| `select_static_product_ids()` docstring | 硬上限 50,000 / 不产生 51k | 硬上限 84,000 / 不产生 85k |

未改：选择规则（`_eligible_market_products` 的 SQL 与排序）、`PRODUCT_STATIC_MARKET_CAP=6_000`、
`PRODUCT_STATIC_MODE="roundrobin"`、URL 形状（`/product/<pid>.html`）、canonical、sitemap 逻辑、
CSS / JS / i18n 文案。`product/` 页仍是 `slim` 模板，同一份数据口径。

## 2 自验数字（现查，before = 本批前 `site/dist`（v1.2.1 产物）／after = `.tmp/frontend-t14`）

| 项 | before | after | 差 |
|---|---|---|---|
| 静态产品页 `product/*.html` | 54,176 | **84,000** | **+29,824** |
| `static_pins.json` count | 54,176 | **84,000** | +29,824（只增不减） |
| sitemap `<loc>` 数 | 140,611 | **170,435** | +29,824（< 180,000 ✓） |
| dist 文件数 | 272,283 | **302,107** | +29,824 |
| dist 体积（10^6 MB） | 2,792 MB | **3,010 MB** | +218 MB（+7.8%） |
| 0 字节文件 | 0 | **0** | 0 |
| `data/idx/core.json` raw / gzip | 68.0 MB / 13.62 MB | 68.0 MB / 13.62 MB | 0（本批不动索引） |
| 构建耗时（A / A′） | — | **9.9 min / 10.4 min** | — |
| 软上限告警 | — | 未触发（84,000 ≤ 90,000，余 6,000） | — |

构建日志关键行（A）：

```
  static pins : 54,176 pinned pids, +0 restored this build
  static top N: 84,000 products, markets 16 (AU 5,772, CA 5,772, CN 5,771, CZ 5,771,
               ES 5,772, FR 5,772, GB 5,772, JP 5,771, KR 5,771, LV 3,391, MX 542,
               MY 5,771, NO 5,771, SG 5,038, TW 5,771, US 5,772)
  product     : 84,000 static pages (top 84,000)
  seo files   : 404 + robots + sitemap (170435 urls) + deploy verify
  == done ==
```

新增 29,824 页的市场分布（DB 现查，按 `COALESCE(country, region)` 聚合）：
KR 2,474 / NO 2,228 / ES 2,228 / CA 2,228 / CN 2,227 / AU 2,225 / TW 2,200 / GB 2,193 /
US 2,180 / JP 2,174 / CZ 2,135 / FR 2,074 / MY 1,983 / SG 1,275（LV / MX 受每市场额度所限本批无新增）。

## 3 断言逐条核对

| 断言（任务原文） | 结果 |
|---|---|
| 新增静态页在 +28,000…+31,000 | **+29,824 ✓** |
| pins 旧 54,176 条全部仍在（只增不减） | **旧集合 ⊆ 新集合，missing 0 ✓**；`pids` 排序去重、`count`=84,000；两次重算回写**字节相同**（SHA256 幂等） |
| sitemap < 180,000 | **170,435 ✓** |
| 抽 3 个新页（含 KR / NO 等新市场）存在且含 canonical 与商品名 | ✓ 见下 |
| 抽 2 个旧 pins 页仍存在 | ✓ 见下 |

抽检明细（`canonical_self` = `<link rel="canonical" href="https://drugcrossref.com/product/<pid>.html"`，
`in_sitemap` = 该 URL 在 sitemap；`noindex=False` 表示静态页仍 `index,follow`）：

| pid | 市场 | 商品名（DB） | 页面 |
|---|---|---|---|
| `KR-199903120`（新） | KR | 메트몰주(메토카르바몰) / Methocarbamol | canonical ✓ / 名字 ✓ / in_sitemap ✓ |
| `NO-insulin-lispro-minimed-sa-ed74c3c6`（新） | NO | Insulin lispro MiniMed SA | canonical ✓ / 名字 ✓ / in_sitemap ✓ |
| `JP-2331007D1029`（新） | JP | リパクレオン顆粒300mg分包 / Pancrelipase | canonical ✓ / 名字 ✓ / in_sitemap ✓ |
| `AU-10001J-xifaxan-56fd56`（旧） | AU | XIFAXAN / Rifaximin | canonical ✓ / 名字 ✓ / in_sitemap ✓ |
| `AU-10003L-tafinlar-9dfeef`（旧） | AU | TAFINLAR / Dabrafenib | canonical ✓ / 名字 ✓ / in_sitemap ✓ |

三语/多文字页面标题也抽过（韩文商品名、挪威英文名、日文商品名均正确进 `<title>` 与 `<h1>`）；
404.html / robots.txt / assets/style.css / assets/boot.js 均在产物根。

## 4 首屏守卫（AGENTS §5 要求，改前 / 改后各一次）

```powershell
& $py deploy/first_screen_check.py --dist site/dist --json .tmp\fs-before-t14.json
& $py deploy/first_screen_check.py --dist .tmp/frontend-t14 --baseline .tmp\fs-before-t14.json --json .tmp\fs-after-t14.json
```

| 项 | 改前（`site/dist`） | 改后（A） |
|---|---|---|
| 扫描 | 6 页型 × 4 视口 = 24 次 | 24 次 |
| 不达标 | 1 组 / 1 项（`coverage@390x844` items 3.5 < 5，**既有项**） | **同 1 组 / 1 项**（未扩大） |
| WARN | 0 | 0 |
| 不稳定扫描 | 0 组 | 0 组 |
| baseline 退化 | — | **0 项（无退化）** |
| 耗时 | 86.8s | 87.0s |

24 项指标逐格与改前一致（AFCR / 条目 / chrome / 悬浮 / 字号 / 横向溢出全部同值），
因为本批不碰模板、只增静态产品页（该页型不在守卫清单里）。

## 5 确定性（A/A′）与版本差分（A/B）

- **A/A′（同源码 + 同 DB 连跑两次）**：路径集合 **0 差异**（302,107 = 302,107），
  24 个文件字节不同，逐行比对后**差异行全部是版本 / 日期串**（`v1.2.1`→`v1.2.2`、`2026-11-22`→`2026-11-24`），
  涉及 `index.html`、`whats-new.html` 与各语言首页、`assets/i18n*.js`。
  原因已核实：**CHANGELOG.md 在我 A（13:30:15）与 A′（13:45:27）两次构建之间被 release 工位加了 v1.2.2 一节**
  （mtime 13:30:44），构建从 CHANGELOG 读版本号 → 属外部输入变化，**不是本批代码的不确定性**。
  其余 **302,083 个文件 0 差异**，同尺寸文件抽 1,000 个核 SHA256 **0 不一致**。
- **A/B（旧产物 `site/dist` vs 本批 A）**：新增 **29,824 个 `product/*.html` + 1 个 hashed 资源名**
  （`assets/boot.<hash>.js` 换名，删 1 个旧名，属版本 bump 正常行为）。其余差异是 `site/dist`
  （11-22 旧产物）与当前 DB 之间**既有的数据漂移**（product 35,375 / name 4,499 / drug 2,331 页大小不同），
  **不是本批引入**：本批没有改模板、URL、canonical 与 sitemap 逻辑。
  → 本批增量发布预期 PUT ≈ 29,825（+sitemap），由 `release` 在正式发布时以 `-DryRun` 复核。

## 6 其它检查

| 检查 | 结果 |
|---|---|
| `deploy/ci_checks.py --fast` | **13 项：PASS 8 / FAIL 0 / SKIP 5**（54.4s；i18n / py_compile / etl 104 / lib 71 / mobile 29 / lib-atc-category 4 / dist-integrity / workflow） |
| sitemap 抽检 | 新页 URL 在册（KR / NO / JP 各抽 1），旧页 URL 在册（AU 抽 2），`<loc>` 总数 170,435 |
| 链接 / 404 | 产物根 `404.html`、`robots.txt`、`assets/style.css`、`assets/boot.js` 均在；产品页相对资源路径未变（模板未动） |
| 索引体积 | `core.json` 68.0 MB raw / 13.62 MB gzip，与改前**完全一致**（本批不动索引） |
| 三语 | 页面侧：韩 / 英 / 日 商品名与 `<title>` 正确；`tests/trilingual/run_tests.py` 见下方备注 |

> 三语备注：`tests/trilingual/run_tests.py` 本批**未跑完**（该套要遍历全库检索键，跑超过 10 分钟后转后台，
> 为不阻塞 release 的构建窗口已终止；本批未改 `lib/search.py`、归一化、i18n 词条与模板，
> 该套由 `ci_checks` 全量（发布前）覆盖）。**不把它算作已验项**。

## 7 缺口 / 注意（给 Lead / release）

1. **pins / 软上限余量变小**：84,000 / 90,000 = **93%**。下一批（T14 第 3 批）扩到 ~90k 前需要人决定：
   抬上限，还是定 prune 策略（只报警不删 → 删了就是 404，R2 静态托管无法 301）。
2. **体积**：dist 3,010 MB（+218 MB）；静态产品页平均 ~4 KB/页，后续每 +10,000 页约 +45 MB。
   `core.json` 未变，首屏体积无回归（守卫已核）。
3. **发布 PUT**：本批新增 ≈ 29,825 个对象（product 页 + sitemap + 1 个 hashed 资源名），
   `release` 需按「单次 PUT ≤ 50,000、当月累计 ≤ 900,000」护栏记账；超过 50,000 要 Lead 批准。
4. **`data/product/static_pins.json` 已在本机被自验构建写成 84,000 条（append-only，符合预期）**，
   是源码级清单（进仓库），release 的生产构建会得到同一份集合（选择集确定性已核）。
5. 未 commit、未发布、未写 `site/dist`；两个自验目录 `.tmp/frontend-t14` / `.tmp/frontend-t14-b`
   与临时脚本、日志已删除（D 盘可用空间 5.1 GB → **11.8 GB**，清理用时 5.98 min）。
