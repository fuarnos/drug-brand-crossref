# v1.2.5：T14 第 4 批静态产品页 114,000 → 144,000（frontend 自验报告）

- 日期：2026-11-26（北京时间凌晨谷段；本机 US-Pacific 2026-11-25 中午）
- 工位：`frontend`；任务：共享任务板 `task-1`
- 基线：HEAD `24e48bf7e83`（v1.2.4 已上线，verify 54/0/0）；pins / 静态页 **114,000**；线上 sitemap **200,435 / 5 片**；`PRODUCT_STATIC_CAP = 150,000`、`PRODUCT_STATIC_TIERS = (90k, 120k, 140k)`（本版**不动**）
- **未跑 `site/build.py`（未写 `site/dist`）、未 commit / push / tag、未改 `data/drugs.db`、未改 `deploy/`、未碰队列 / 开工卡 / 交接。**
- 只读复算脚本：`.tmp/calc_v125_static.py`、`.tmp/verify_v125_static.py`（`.tmp/` 不入库），日志 `.tmp/calc_v125_static.log`。

## 0. 结论（先行）

| 验收项 | 结果 | 证据 |
|---|---|---|
| `PRODUCT_STATIC_TOP_N` | ✅ 114,000 → **144,000**（`PRODUCT_STATIC_CAP` 保持 150,000、`TIERS` 不动） | §1 |
| `PRODUCT_STATIC_MARKET_CAP` | ✅ **保持 12,000 不动**：只读复算 16 个有数据市场在 12,000 上限下的合格供给合计 **148,814 ≥ 144,000**，能取满 | §2.2 |
| 预计实际静态页条数 | ✅ **144,000**（= TOP_N 选中 ∪ pins；pins 114,000 全含于新选，无「复活」页） | §2.3 |
| pins 只增不减 | ✅ 114,000 → **144,000**：added **30,000**、missing **0**、pinned-only extra **0** | §2.3 |
| `[STATIC]` 分档告警 | ✅ 构建时会打印 **3 条**（90,000 / 120,000 / 140,000 各一条）；**不触发** 150,000 软上限 WARN | §2.4 |
| sitemap 预期 | ✅ **5 片**：50,000 ×4 + **30,435** = **230,435**（200,435 + 30,000，每片 ≤ 50,000） | §2.5 |
| 九语 i18n | ✅ `deploy/i18n_check.py` **FAIL 0 / WARN 27 / INFO 43**（与 v1.2.4 基线同）；「CHANGELOG 93 版 / json 93 版，最新 v1.2.5 译文齐」 | §2.6 |
| 语法 | ✅ `python -m py_compile site/build.py` 退出码 0 | §3 |

**一句话**：把静态产品页上限抬到 144,000 并只读复算确认能取满（16 市场供给 148,814，`MARKET_CAP` 12,000 不必动）；pins 由 114,000 单调扩到 144,000（+30,000 / 丢 0），sitemap 预期 5 片 230,435，九语文案同步且 i18n 门禁 FAIL 0。生产构建与发布留给 `release`。

### ⚠️ 与任务书的两处口径差异（请 Lead 知悉）

1. **任务书建议 CHANGELOG 写「剩余约 587,078 继续按夜分批补齐」——这个数不是「可补」数。**
   现查：`product` 总数 **731,078**，静态页 144,000 → 没有静态页的产品 731,078 − 144,000 = **587,078**（数字本身对），但其中**只有约 360,030 个属于「静态页合格集」**（active + 成分已映射 + 有剂型 + pack 或含量至少一项，单市场不限上限求和 = **504,030**，504,030 − 144,000 = 360,030），**另外约 227,048 个缺剂型 / 成分映射 / 规格，按设计只走长尾页、永远不进静态集**。
   若写「剩余 587,078 继续按夜分批补齐」，等于承诺补一批永远补不了的产品。CHANGELOG / 九语 notes 因此写成：其余 587,078 个产品目前无静态页但都能在长尾页查到，其中约 **360,030** 个合格、以后按夜分批补齐，另约 227,048 个按设计只走长尾。
2. **`[STATIC]` 告警条数**：任务书写「会触发 140k 分档告警」。实际分档是 `(90k, 120k, 140k)` 三条**逐条**判断，144,000 会**同时**打印 90k / 120k / 140k 三行（不是只打 140k 一行）；150,000 软上限 WARN 不触发（144,000 < 150,000）。

## 1. 改动清单（只改这些）

| 文件 | 改动 |
|---|---|
| `site/build.py` | `PRODUCT_STATIC_TOP_N` 114,000 → **144,000**（注释写「v1.2.5 第 4 批」）；`PRODUCT_STATIC_MARKET_CAP` **值不动**，只在注释里补一行「v1.2.5 只读复算 148,814 ≥ 144,000」的依据；`select_static_product_ids()` docstring 同步 144k（「不产生 145k」）。`PRODUCT_STATIC_CAP` / `PRODUCT_STATIC_TIERS` / `PRODUCT_STATIC_MODE` 均不动。 |
| `CHANGELOG.md` | 顶部新增 `## v1.2.5 — 2026-11-26`，**4 条**用户可感知变化（144,000 / +30,000；旧地址一条没删；sitemap 230,435 / 5 片；剩余 587,078 中约 360,030 合格可补、约 227,048 按设计只走长尾）。 |
| `data/release_notes_i18n.json` | 新增 `v1.2.5`：**4 条 × 9 语**（zh / en / es / zh-Hant / fr / ko / ja / cs / lv），键集与 CHANGELOG 条数一致、无空值；`_meta` 92→**93 版**、363→**367 条**、`generated_at` 更新。**旧 92 个版本逐版本序列化零改动**（写入脚本里逐版断言）。 |
| `reports/2026-11-26-v125-static-pages.md` | 本报告。 |

`git status`（本工位相关）：仅 `M CHANGELOG.md`、`M data/release_notes_i18n.json`、`M site/build.py`，加本报告（新文件）。
**未改**：`PRODUCT_STATIC_CAP`、`deploy/**`、`data/drugs.db`、`data/product/static_pins.json`（那是构建时自动写的，归 `release`）、`docs/谷段需求队列.md`、`docs/每日开工卡.md`、交接文档。

## 2. 自验（数字全部现查，命令见 §3）

### 2.1 复算口径可信度：先用旧值复现 v1.2.4

用**现库** + `TOP_N = 114,000` 跑我的只读复算，结果与 v1.2.4 报告逐市场完全一致：

```
selected: 114,000   unique: 114,000
dist: AU 7,146  CA 8,229  CN 8,228  CZ 8,228  ES 8,228  FR 8,228  GB 8,229  JP 8,228
      KR 8,228  LV 3,391  MX 542  MY 7,372  NO 8,228  SG 5,038  TW 8,228  US 8,229
dist sum: 114,000
```

→ 与 `reports/2026-11-25-v124-static-pages.md` §2.1 的 `static top N: 114,000 products, markets 16` 那一行**逐数字相同**，说明复算（同一份 SQL：直接调 `site/build.py` 的 `_eligible_market_products()` / `_market_dist()`，不抄 SQL）可信。

### 2.2 合格集 / 每市场供给（决定 MARKET_CAP 要不要抬）

```
products total: 731,078          markets: 18（16 个有合格供给，HK / EU 为 0）
每市场合格供给（LIMIT 12,000）：
  US 12,000  GB 12,000  CA 12,000  AU 7,146  ES 12,000  FR 11,986  MX 542  CN 12,000
  TW 12,000  SG 5,038   HK 0       EU 0      JP 8,597   MY 7,372   CZ 12,000  LV 3,391
  NO 8,742   KR 12,000
supply sum: 148,814   ← 12,000 上限下的总可供给量
eligible total（单市场不限上限求和）: 504,030
```

- **148,814 ≥ 144,000 ⇒ `MARKET_CAP = 12,000` 不会先于 TOP_N 截断，本版不动**（这正是任务书要求的「先复算，只有当 12,000 会导致取不满才抬」）。
- 轮转下 8 个供给充足的市场（US/GB/CA/ES/CN/TW/CZ/KR）各吃满 12,000；AU/JP/NO/MY/SG/LV/MX 因供给不足被「吃干」；这正是下面 144k 分布长这样（11,46x / 3,391 / 542 …）的原因。

### 2.3 144,000 选中 + pins 只增不减

```
TOP_N = 144,000  MARKET_CAP = 12,000  CAP = 150,000  TIERS = (90000, 120000, 140000)
selected : 144,000   unique: 144000   两次独立复算结果一致: True
pins     : 114,000（data/product/static_pins.json，count=114000 / pids=114000）
pinned-only extra : 0      （新选是旧选的超集，没有需要「复活」的页）
added    : 30,000          （= 144,000 − 114,000 = F7 每夜上限，正好用满、不超）
missing  : 0               （旧 114,000 条一条不丢）
static pages: 144,000      （= TOP_N 选中 ∪ pins）
```

144k 切点的市场分布（`_market_dist` 现查）：

| 市场 | 页数 | 市场 | 页数 | 市场 | 页数 | 市场 | 页数 |
|---|---|---|---|---|---|---|---|
| US | 11,464 | GB | 11,464 | CA | 11,464 | ES | 11,464 |
| CN | 11,463 | TW | 11,463 | CZ | 11,463 | KR | 11,463 |
| NO | 8,742 | JP | 8,597 | MY | 7,372 | AU | 7,146 |
| SG | 5,038 | LV | 3,391 | MX | 542 | — | — |
| **合计** | **144,000** | | | | | | |

（与 v1.2.4 的 114k 分布相比：8 个供给充足市场各 +3,235~3,236 页，其余市场不变——因为它们的合格供给已经用尽。）

**改码后第二遍复核**（`verify_v125_static.py`，`TOP_N` 直接从模块读，不再由脚本传参）：

```
TOP_N = 144000  MARKET_CAP = 12000  CAP = 150000  TIERS = (90000, 120000, 140000)
selected: 144,000  unique: 144000  两次一致: True
added: 30,000   missing: 0   pinned-only extra: 0   pins sorted/unique: True
static pages: 144,000   dist sum: 144,000
sitemap: 200,435 + 30,000 = 230,435   分片: 5
products total: 731,078   eligible total: 504,030
remaining（合格 − 静态）: 360,030   no static page: 587,078（其中不合格 227,048）
```

与第一遍（§2.1–§2.3）逐数字一致 ⇒ 结果不依赖脚本传参、只取决于已提交的源码常量。

### 2.4 `[STATIC]` 分档告警预期（构建时会打印，属预期）

```
tier lines hit: [90000, 120000, 140000]   条数: 3
soft-cap WARN : False                        （144,000 < 150,000）
```

即生产构建日志里会依次出现 3 条 `[STATIC] 144,000 pages ≥ {90,000|120,000|140,000} — 分档告警…`，**不是失败**；`≥ 软上限 150,000` 的醒目 WARN **不会**出现。`release` 看到这 3 行不要当成回归。

### 2.5 sitemap 预期：5 片 230,435

线上（v1.2.4）现数：`sitemap-1..4.xml` 各 50,000 + `sitemap-5.xml` 435 = **200,435**，索引 5 个 `<sitemap>`。
本版静态页 +30,000 ⇒ **230,435**，按 `SITEMAP_SHARD_MAX = 50_000` 顺序切片 ⇒ **5 片**（50,000 / 50,000 / 50,000 / 50,000 / **30,435**），仍 ≤ 50,000/片、索引片数不变（5→5）。

### 2.6 九语 i18n

```
$env:PYTHONIOENCODING='utf-8'; & $py deploy/i18n_check.py
== i18n 一致性门禁（en / es / zh / zh-Hant / fr / ko / ja / cs / lv）==
build.py: 有效字典 en/es/zh/zh-Hant/fr/ko/ja/cs/lv 各 684 键
release notes: CHANGELOG 93 版 / json 93 版，最新 v1.2.5 译文齐；缺 0 版（0 条待译）
FAIL 0 / WARN 27 / INFO 43
exit=0
```

WARN 27（hardcoded 25 + pseudo-suspect 2）与 INFO 43 与 v1.2.4 基线**完全一致**，本版未新增；`_meta.versions` 与实际 93 版一致（否则会出 `release-meta` WARN）。
九语条目逐条对齐 CHANGELOG 4 条（脚本里 `assert len(items) == 4` 每语各断言一次），旧 92 版序列化逐版零改动。

## 3. 命令（可复核）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'

# 0) 基线现查（不写任何东西）
& $py -c "import json,pathlib; d=json.loads(pathlib.Path('data/product/static_pins.json').read_text(encoding='utf-8')); print(d['count'], len(d['pids']))"   # 114000 114000
& $py -c "import re,pathlib; [print(p.name, len(re.findall('<loc>', p.read_text(encoding='utf-8')))) for p in sorted(pathlib.Path('site/dist').glob('sitemap*.xml'))]"   # 200,435 / 5 片

# 1) 只读复算（同一份 SQL 直接调 site/build.py 的函数；只读开库 mode=ro）
& $py .tmp/calc_v125_static.py        # 旧值 114k 复现 + 144k 预演（§2.1 / §2.2 / §2.3）
& $py .tmp/verify_v125_static.py      # 改码后复核（TOP_N 从模块读，pins 只增不减 / sitemap 预期）

# 2) 语法 + 九语门禁
& $py -m py_compile site/build.py                       # exit 0
& $py deploy/i18n_check.py                              # FAIL 0 / WARN 27 / INFO 43
```

`product` 总数、市场数、每市场合格供给都用 `db/q.py` 同口径 SQL 现查（脚本内联，等价于）：

```sql
SELECT COUNT(*) FROM product;
SELECT DISTINCT COALESCE(country, region) AS mk FROM product WHERE COALESCE(country, region) IS NOT NULL;
-- 合格集（与 site/build.py `_eligible_market_products` 完全一致，按市场分组）
SELECT COALESCE(p.country, p.region) AS mk, COUNT(*) FROM product p
 WHERE p.status = 'active'
   AND COALESCE(NULLIF(TRIM(p.form_base), ''), TRIM(p.dosage_form), '') <> ''
   AND EXISTS (SELECT 1 FROM product_component pc0 WHERE pc0.product_id = p.product_id)
   AND (COALESCE(TRIM(p.pack), '') <> ''
        OR EXISTS (SELECT 1 FROM product_component pc1
                    WHERE pc1.product_id = p.product_id AND pc1.strength_value IS NOT NULL))
 GROUP BY mk ORDER BY mk;   -- 合计 504,030（16 个市场非 0）
```

## 4. 交给 `release` / Lead 的发布提示

- **生产构建必须重跑**（本工位按纪律没跑）：`& $py site/build.py` 等 `== done ==`；日志应出现 `static top N: 144,000 products, markets 16`、`product : 144,000 static pages (top 144,000)`、3 条 `[STATIC]` 分档提示。
- **`data/product/static_pins.json` 会由构建自动写到 144,000**（append-only、排序）。它不在本工位的写权限内，**要随源码一起提交**（v1.2.4 的提交 `510424fac9f` 就带了这个文件），否则下次构建会以「只发布过 114,000」为起点（结果相同，但 pins 是「已发布过」的唯一记录）。
- **增量发布规模**：新增 30,000 个 `/product/<pid>.html` + `sitemap-5.xml` 从 435 → 30,435 条、`sitemap.xml` 索引 5 行改写、既有 name/drug 等长尾页因新增静态页链接出现「同位置仅链接目标变化」的改写（同 v1.2.2 / v1.2.4 口径）。属 AGENTS §6 **内容扩容例外**，需三条同时成立（① added 全在 `product/`；② 页面 removed = 0；③ 长尾变化只由新增链接引起）+ `-DryRun` planned 实测；v1.2.4 同规模为 planned 72,136，本批预计同级（**以 `-DryRun` 实测为准**）。
- **R2 Class A 预算**：30,000+ PUT/版，按当月累计核对是否 < 900,000 停线、是否需要先向用户申请（Lead 拍板）。
- 发布后 `verify_live --base https://drugcrossref.com --expect-version v1.2.5` 应看到 `sitemap-shards` 5 片全部 200、`sitemap-urls` **230,435**、静态产品页抽样 200。
- **首屏守卫**（AGENTS §5）：本版**不触 HTML / CSS / JS**（只改静态页条数上限与注释），首屏 7 指标按构造不变；仍需 `release` 在生产构建后跑一次 `deploy/first_screen_check.py` 并对线上 v1.2.4 基线留档（本工位无构建产物，未跑）。

## 5. 风险与边界

- **下一批的硬瓶颈已经出现**：`MARKET_CAP = 12,000` 下总可供给只有 **148,814**，本版用掉 144,000，**余量只剩 4,814 页**。第 5 批（≥ 148,814）之前**必须**先抬 `PRODUCT_STATIC_MARKET_CAP`（例如 20,000；US/GB/CA/ES/CN/TW/CZ/KR 这 8 个市场各有 >12,000 的合格供给），并重估 `PRODUCT_STATIC_CAP = 150,000` 与 `TIERS` 的关系（150k 软上限在 144k 时只剩 6,000 页余量）。
- **合格集只有 504,030**（不是 731,078）：静态页最多做到 504,030 页就会自然收敛，之后只能靠补数据（剂型 / 成分映射 / 规格）扩大合格集；这条写进 CHANGELOG 第 4 条，避免对外承诺「全部产品都有静态页」。
- 本版用满 F7「每夜 ≤30,000 页」上限（+30,000）。
- sitemap 5 片、单片 ≤50,000，协议无风险；索引片数 5→5 不变（v1.2.3 的 sitemap index 机制继续有效）。
