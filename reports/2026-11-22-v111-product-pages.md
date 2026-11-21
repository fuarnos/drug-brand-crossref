# v1.1.1 产品页（B 混合）+ 详情页搜索框层级（F5）+ About 致谢

- 日期：2026-11-22（北京时间）｜工位：frontend｜任务：共享任务板 `task-5`
- 版本：**v1.1.1**（用户 2026-11-22 定：产品主页放 1.1.1，韩国排 1.2）
- 写权限内改动：`site/build.py`、`data/languages.json`（未改）、`reports/`；**未写 `site/dist`**、未 commit、未发布
- 自验构建：`$env:SITE_OUT='.tmp/frontend-v111'; & $py site/build.py`（另有 `.tmp/frontend-v111-b` 做 A/A′）

## 0 结论（先行）

1. **每个产品一个页面（B 混合）已上线**：静态 `/product/<pid>.html` **50,000** 个（`index,follow`，进 sitemap）；
   其余产品走长尾 `/product.html?pid=<pid>`（`noindex,follow`，canonical 由 JS 指回名字页，不进 sitemap）。
   长尾数据是 **512 个桶** `data/product/b-000.json … b-511.json`（633,722 条记录，单桶 gzip **P50 79 KB / P95 83 KB / max 86 KB**，目标 ≤120 KB）。
2. **发现入口**：名字页单产品明细表的「市场」格 → 产品页；成分页新增「本页收录的产品记录」折叠块（最多 24 条 + 计数）。
   静态产品直链 `/product/<pid>.html`，其余走 `/product.html?pid=`。
3. **F5 已修**：详情页（名字/成分/复方/厂家）的「继续搜索」从 h1 正下方收进页头图标（🔍「换个药名搜」），
   标签改「换个药名搜」，**预填当前页药名/成分名**；h1 之后直接是页面主语信息。九语同步。
4. **About 页底部新增「致谢 / Acknowledgements」**（九语，人名原文不译）：`感谢 白雨舟 在 UI 设计上给出的建议与贡献。`
   其他八语为本地化句子 + `白雨舟 (Bai Yuzhou)` 括注；根页 + 8 个语言副本都含该区块。
5. **口径红线未破**：产品页只做身份对应（商品名原文、INN 原文、含量/规格、剂型、释放、包装、MAH、注册号、状态、
   数据截止、来源/许可），并给「不可互换」警示；**没有**用药建议、剂量换算、可替代判断（抽样逐页断言）。
6. 硬数字：构建 **486.5 s（8.1 min）**；dist **209,349 文件 / 2,228.5 MB**；`core.json` **44.76 MB raw / 10.1 MB gzip**；
   sitemap **79,894 → 129,894**（+50,000）；0 字节文件 **0**；A/A′ **209,349 文件 0 差异**（含 `product/**` 与 `data/product/**`）。

## 1 交付内容

### 1.1 A · 产品页（B 混合）

| 项 | 实现 |
|---|---|
| 静态页 | `/product/<product_id>.html`，`<title>`＝商品名（无商品名时用 INN）— INN · 市场；canonical 指自身；`index,follow`；进 sitemap；`slim` 壳（与长尾页同一套精简壳） |
| 长尾页 | `/product.html?pid=<pid>` 单文件；静态 `noindex,follow`；JS 按 pid 计算桶号 → 只拉 1 个桶 → 渲染；拿到 `name_slug` 后把 canonical 指回该产品的**名字页**；找不到 → 「记录不存在」+ 指向品牌页/搜索；`<noscript>` 兜底 |
| 桶数据 | `data/product/b-<000..511>.json`（FNV-1a 32 位 % 512，Python/JS 同一算法）；字段：`name / inn / strength / form / pack / mah / approval_id / status / data_as_of / source / name_slug / drug_slug`（另带 `c` 市场、`release` 释放机制） |
| 来源元数据 | `data/product/sources.json`：`source_id → {name, url, license, license_url, as_of}`（长尾页署名/许可用，避免每条记录重复存长字符串） |
| 页面内容 | 商品名原文 / INN 原文（不译）/ 含量·规格 / 剂型 / 释放（有依据才显示）/ 包装规格 / MAH（有厂家页则链）/ 注册号（有才显示，没有写「未记录」）/ 状态 / 数据截止 / 来源 + 许可 / 「同名·同成分的其他产品」身份对应列表 / **不可互换**警示 / 品牌页 + 成分页入口 |
| 发现入口 | 名字页单产品明细表（市场格变成产品链接）；成分页新增 `.p-records` 折叠块（最多 24 条 + `product.records_more` 说明） |
| i18n | 新增 22 个键 × 9 语（`product.*` + `search.swap`），构建期注入；产品名/INN 原文不译 |

### 1.2 B · F5（详情页搜索框层级）

- `_page_head(search_mode="quiet", prefill=…)`：搜索从 h1 正下方移到「返回路径」行右端的 `<details class="qsearch">`（🔍 + 短标签），
  原生 `<details>`，无 JS 也能展开；面板里是 40px 表单，`value` 预填当前页药名（名字页＝名称，成分页＝INN，复方页＝组合标题）。
- 标签键 `search.swap`（9 语）：en `Search another name` / zh `换个药名搜` / zh-Hant `換個藥名搜` …
- 只影响详情页（name / drug / combo / maker）；顶层页（about / coverage / 404 等）仍用原「继续搜索」布局，URL / canonical / hreflang / SEO 骨架未动。
- CSS 只加 `.qsearch` / `.qs-panel` 与产品页样式块（长尾页用稳定资源名 `assets/style.css`，不触发逐页哈希）。

### 1.3 追加 · About 致谢区块（用户 2026-11-22 当天追加）

- `about.thanks`（9 语，`data-i18n-html`）：`<h2>致谢/Acknowledgements/…</h2><p class="sub">…</p>`，放在 About 页**底部**。
- 人名「白雨舟」**原文不译**；非中文页面统一写作 `白雨舟 (Bai Yuzhou)`（不做 Bai 姓式、不自造拼法），句子本身本地化。
- 只改 About 模板 + 该 i18n 键；根页与 8 个语言副本都含该区块（自验脚本逐份断言）。

## 2 决策与规则（可复算）

**静态页合格集 + 分配（Lead 2026-11-22 定，代码在 `select_static_product_ids`）**

1. 合格集 = `status='active'` + 成分已映射（有 `product_component`）+ 有剂型 + (**pack 或含量至少一项**)。
2. 市场顺序 = `data/markets.json` 的 `order`（不硬编码国家名单）；市场内按完整性得分降序
   （有含量 + 有 ATC + 有批准号，越多越前）→ `product_id` 升序（确定性）。
3. 分配 = **轮转**：外循环按市场序，每轮每市场取 1 条，直到 **50,000**（硬上限，不会出现 51k）；每市场硬上限 6,000（轮转下不触发）。
4. 实际结果：**15 个市场、每市场 3,391–3,544 条**（见 §3），HK / EU 不合格（无剂型/含量/包装，见 §6）。

> 为什么不是「按序吃满」：按序吃满会让 US/GB/CA/AU/ES/FR 各吃 6,000、SG 只拿 1,458，JP/MY/CZ/LV/**NO** 全部为 0
> （用户 2026-11-22 已拍板改为轮转，保证每个有数据的市场都有静态页，含挪威）。

**注意**：`product.html?pid=` 对**所有** 633,722 条记录都可用（长尾数据全量入桶），静态页只是「首期 Top 50k」。

## 3 数字

| 项 | 数字 |
|---|---|
| 构建时长 | **486.5 s（8.1 min）**（第二次 A/A′ 构建 420.4 s） |
| dist | **209,349 文件 / 2,228.5 MB**（v1.1.0 为 158,835 / 1,563.2 MB；+50,000 产品页 +513 数据文件 +1 长尾页） |
| `data/idx/core.json` | **44.76 MB raw / 10.10 MB gzip**（未变） |
| sitemap | **129,894** URL（79,894 → +50,000 静态产品页；长尾 `product.html` 不在内） |
| 0 字节文件 | **0** |
| 产品静态页 | **50,000**（`product/*.html`） |
| 长尾数据 | **512 桶 / 633,722 条记录 / 513 文件**（含 `sources.json`） |
| 桶 gzip | **P50 79 KB / P95 83 KB / max 86 KB**（目标 ≤120 KB） |
| About 致谢副本 | **9/9**（root + es/zh/zh-Hant/fr/ko/ja/cs/lv） |
| i18n 运行期字典 | **734 键 × 9 语**（v1.1.0 为 710） |

**每市场静态分布（15 个市场，无 0）**

| 市场 | 静态页 | 市场 | 静态页 |
|---|---:|---|---:|
| US | 3,544 | FR | 3,544 |
| GB | 3,544 | MX | 542（合格集只有 542，整取） |
| CA | 3,544 | CN | 3,544 |
| AU | 3,544 | TW | 3,544 |
| ES | 3,544 | SG | 3,543 |
| JP | 3,543 | MY | 3,543 |
| CZ | 3,543 | LV | 3,391（合格集只有 3,391，整取） |
| NO | 3,543 | **合计** | **50,000** |

## 4 首屏守卫（`deploy/first_screen_check.py`，390/768/1440 × 6 页型）

改前 = `site/dist`（当前生产 v1.1.0）；改后 = `.tmp/frontend-v111`。

| 页面 | 视口 | 改前 AFCR / 条目 / chrome | 改后 AFCR / 条目 / chrome | 判定 |
|---|---|---|---|---|
| home | 390x844 | 0.93 / 0.0 / 0.14 | 0.93 / 0.0 / 0.14 | 达标 |
| home | 768x1024 | 1.01 / 9.0 / 0.11 | 1.01 / 9.0 / 0.11 | 达标 |
| home | 1440x900 | 1.00 / 9.0 / 0.07 | 1.00 / 9.0 / 0.07 | 达标 |
| results | 390x844 | 0.87 / 6.5 / 0.19 | 0.87 / 6.5 / 0.19 | 达标 |
| results | 768x1024 | 0.98 / 11.5 / 0.13 | 0.98 / 11.5 / 0.13 | 达标 |
| results | 1440x900 | 0.97 / 10.0 / 0.09 | 0.97 / 10.0 / 0.09 | 达标 |
| drug | 390x844 | 0.93 / 5.5 / 0.14 | 0.93 / 5.5 / 0.14 | 达标 |
| drug | 768x1024 | 1.01 / 5.5 / 0.11 | 1.01 / 6.5 / 0.11 | 达标 |
| drug | 1440x900 | 1.00 / 4.5 / 0.07 | 1.00 / 5.5 / 0.07 | 改前未达 → **改后达标** |
| name | 390x844 | 1.01 / 1.0 / 0.29 | 1.01 / 1.0 / 0.29 | 达标 |
| name | 768x1024 | 1.00 / 1.0 / 0.19 | 1.00 / 1.0 / 0.19 | 达标 |
| name | 1440x900 | 1.00 / 1.0 / 0.17 | 1.00 / 1.0 / 0.17 | 达标 |
| atc | 390x844 | 0.93 / 7.5 / 0.14 | 0.93 / 7.5 / 0.14 | 达标 |
| atc | 768x1024 | 1.01 / 13.0 / 0.11 | 1.01 / 13.0 / 0.11 | 达标 |
| atc | 1440x900 | 1.00 / 13.5 / 0.07 | 1.00 / 13.5 / 0.07 | 达标 |
| coverage | 390x844 | 0.79 / 3.5 / 0.27 | 0.79 / 3.5 / 0.27 | 改前未达 → 改后未达 |
| coverage | 768x1024 | 0.91 / 8.5 / 0.19 | 0.91 / 8.5 / 0.19 | 达标 |
| coverage | 1440x900 | 0.90 / 7.0 / 0.14 | 0.90 / 7.0 / 0.14 | 达标 |

**无回归，且一条旧账被顺手修好**：18 组里 17 组与改前逐项同值；`drug` 页因新增「产品记录」块，1440 首屏条目 4.5 → 5.5（由未达转为达标）、768 5.5 → 6.5。唯一未达仍是 `coverage@390` 的 items 3.5（改前既有、与本次无关）。不稳定 0、疑似 0、baseline 退化 0。

## 5 A/A′ 确定性

同参数、同 DB 连续两次构建（`.tmp/frontend-v111` / `.tmp/frontend-v111-b`）：
**209,349 个文件逐字节比较，差异 0**；其中 `product/**` 50,000 个、`data/product/**` 513 个文件 **0 差异**。
（`data/product/b-*.json` 用 `json.dumps(separators=(",",":"), ensure_ascii=False)`，与页面同样不含构建时间戳。）

## 6 为什么只有 15 个市场有静态页

合格集要求「有剂型 + 有成分 + (pack 或含量)」。DB 现查各市场合格条数：

| 市场 | 合格条数 | 静态页 | 说明 |
|---|---:|---:|---|
| CN | 145,051 | 3,544 | 合格 |
| US | 107,933 | 3,544 | 合格 |
| CZ | 67,123 | 3,543 | 合格 |
| GB | 51,307 | 3,544 | 合格（dm+d 有剂型+含量；多数无包装规格） |
| TW | 16,431 | 3,544 | 合格 |
| ES | 15,738 | 3,544 | 合格（CIMA 有含量，无包装规格） |
| CA | 14,519 | 3,544 | 合格 |
| FR | 11,986 | 3,544 | 合格 |
| NO | 8,742 | 3,543 | 合格（FEST 有剂型/含量/包装） |
| JP | 8,597 | 3,543 | 合格（薬価リスト有剤形・含量） |
| MY | 7,372 | 3,543 | 合格 |
| AU | 7,146 | 3,544 | 合格 |
| SG | 5,038 | 3,543 | 合格 |
| LV | 3,391 | 3,391 | 合格集不足 6,000，整取 |
| MX | 542 | 542 | 合格集只有 542（COFEPRIS 无剂型/含量列），整取 |
| **HK** | 0 | 0 | 名称层来源：**无剂型、无含量、无包装** → 不合格 |
| **EU** | 0 | 0 | 区域层：只有授权事实，**无剂型/含量/包装** → 不合格 |

HK / EU 的产品**仍有自己的 URL**：`/product.html?pid=`（noindex，canonical 指名字页），自验里各抽了长尾页验证可打开。

## 7 抽样（每市场 1 个静态页 + 每市场 1 个长尾页）

静态页（15 市场各 1 个，抽查内容：h1 商品名/INN、成分、含量、剂型、包装、来源+许可、不可互换警示、无建议措辞）：

| 市场 | 抽样 pid | 字节 | 商品名/成分/规格/来源/警示 |
|---|---|---:|---|
| US | `US-0002-0152` | 7,477 | ✓ / ✓ / ✓ / ✓ / ✓ |
| GB | `GB-100111000001109` | 6,629 | ✓（无商品名 → INN `Rifampin` 兜底 + 「无商品名」标注） |
| CA | `CA-00000868` | 7,275 | 全 ✓ |
| AU | `AU-10001J-xifaxan-56fd56` | 7,638 | 全 ✓ |
| ES | `ES-00-2881` | 7,254 | 全 ✓ |
| FR | `FR-60002283` | 7,254 | 全 ✓ |
| MX | `MX-002M2024` | 6,663 | 全 ✓ |
| CN | `CN-XA01ABD075A00-0a2a2841` | 5,350 | 全 ✓（无商品名 → INN 兜底） |
| TW | `TW-TFDA-000001-65739378` | 6,710 | 全 ✓ |
| SG | `SG-SIN00041P` | 7,851 | 全 ✓ |
| JP | `JP-1115403D3019` | 7,048 | 全 ✓ |
| MY | `MY-MAL04010359XZ` | 7,388 | 全 ✓ |
| CZ | `CZ-0000009` | 7,229 | 全 ✓ |
| LV | `LV-00-0003` | 6,059 | 全 ✓ |
| NO | `NO-2-hydroxyethyl-methacrylate-2-h-010-5f54b74e` | 5,651 | 全 ✓ |

长尾页：**17 个市场（含 HK / EU）各 1 个** `product.html?pid=`，全部能在桶里定位到记录（脚本断言）；本机 HTTP 实测
（`NO-thylip-c868f0e9`）：JS 渲染出 h1 `Thylip`、成分 `Fenofibrate`、含量 `200 mg`、剂型 `capsule`、包装 `100 stykk`、
MAH、数据截止 `2026-11-10`、来源 `DMP FEST 2.5.1` + `NLOD 2.0`，canonical 指 `name/thylip.html`；
`product.html?pid=NOPE-0000` → 「记录不存在」+ 品牌页/搜索兜底；静态源码含 `<noscript>`。

## 8 门禁

| 门禁 | 结果 |
|---|---|
| `deploy/i18n_check.py` | **FAIL 0 / WARN 27 / INFO 43**（WARN 全部为既有 hardcoded 23 + SQL 串 2 + pseudo 2，无新增 FAIL） |
| `tests.test_markets_registry` | **59 tests OK** |
| `deploy/ci_checks.py --fast` | **13 项：PASS 8 / FAIL 0 / SKIP 5**（跳过的是要拉 Chrome 的 first-screen / ui-sort 等） |
| `lib/markets.py --check` | OK（市场注册表未改） |
| sitemap 抽检 | 5 条静态产品 URL 在 sitemap 内；`https://drugcrossref.com/product.html` **不在** sitemap |
| About 九语副本 | 9/9 含 `about-thanks` + `about.thanks` + `白雨舟` |

## 9 缺口 / 未做

- **v1.1.1 的 CHANGELOG / release notes 译文**：等 release 写 CHANGELOG 后补 `data/release_notes_i18n.json`（同 v1.1.0 流程）。
- **HK / EU 无静态产品页**：来源只有名称层/授权事实，不满足合格集 → 长尾 URL 仍可用（noindex）。
- 长尾页是**单文件 + 客户端渲染**：canonical 由 JS 写（爬虫若不执行 JS 只看到 `noindex,follow`，不会误收录）。
- 静态产品页只出英文正文 + `data-i18n`（与 110k 名字页同一套客户端 i18n 机制，不生成 9 份副本，避免 45 万文件）。
- 产品页里的「同名/同成分」列表是**身份对应**，上限 8 / 17 条（按市场），更多请走品牌页/成分页。

## 10 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:SITE_OUT = '.tmp/frontend-v111'; & $py site/build.py      # 等到 == done ==（≈8 min）
& $py .tmp/verify-v111.py .tmp/frontend-v111 --json .tmp/v111-verify.json
& $py deploy/first_screen_check.py --dist .tmp/frontend-v111 --viewports 390x844,768x1024,1440x900 `
    --json .tmp/v111-fs-after.json --shots .tmp/v111-fs-after
$env:SITE_OUT = '.tmp/frontend-v111-b'; & $py site/build.py     # A/A′ 第二次
& $py deploy/i18n_check.py; & $py deploy/ci_checks.py --fast
```
