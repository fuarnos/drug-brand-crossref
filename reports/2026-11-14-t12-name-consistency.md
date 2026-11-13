# T12：品牌页 / 成分页「名称与提示一致」（task-1，v0.11.6）

> 工位：**site-ui** ｜ 时间：2026-11-14（北京谷段）｜ 任务：`task-1`（T12，C1–C5）
> 状态：**实现 + 自验完成**。未 commit、未发布、未写 `site/dist`、未改 `data/drugs.db`、未改 `collision` 视图。
> 写作用域：仅 `site/build.py` 与本报告；构建产物在 `.tmp/dist-v0116`（临时目录，gitignore）。
> **注（T10 落地后）**：本报告的页面字节是 T12 单独产物（v0.11.6 首个构建）测的；随后 T10 在同一文件里加了「规格按剂型」等，
> 合并产物里 `/name/tylenol-extra-strength.html` 为 **6,019 B**（原 5,801），全站 125,515 文件 / 946.4 MiB —— 见
> `reports/2026-11-14-t10-spec-grouping.md` §2.6。C1–C5 的结论与 DOM 片段不受影响。

## 0. 结论先行

1. **C1–C5 全部落地**，`/name/*`、`/drug/*` 共用一套成分中文名映射（`load_substance_zh()` / `_sub_zh_name()`，数据源 `substance.inn_zh`）。
2. **全量扫描 80,885 个名字页**：出现内部术语「碰撞」的 **0 页**；写法列表重复（含标题重复）**0 页**；「链接文字 == 同名 tag」**0 页**（改前 `泰诺 泰诺` / `泰诺林 泰诺林` 是这一条）。
3. **构建到 `== done ==`**：12,438 成分页 / 80,885 名字页 / 6,896 组合页 / 15,213 厂家页；文件数 125,510、HTML 125,290、sitemap 66,300 — 与 v0.11.5 **完全同量**；`core.json` 仍 45.2 MB（本次不动索引）。
4. **i18n**：572 键 × en/es/zh/zh-Hant/fr 齐（改前 560）；`deploy/i18n_check.py` **FAIL 0 / WARN 2 / INFO 24**，WARN 与改前同两条（`es form.kit` / `es form.gas`），**未新增**；fr 译文 568/572。
5. **`ci_checks.py --fast --dist .tmp/dist-v0116`**：PASS 7 / **FAIL 1** / SKIP 4。唯一 FAIL 是 `release-latest-missing`——`CHANGELOG.md` 已有 `## v0.11.6`，但 `data/release_notes_i18n.json` 还没 v0.11.6 译文；**不是本改的产物，也不在我的写权限内**（`data/`）。
6. **首屏守卫在本机不可用**（官方脚本 `deploy/first_screen_check.py` 起 Chrome 报 `RuntimeError: Chrome 未就绪`；本机沙箱对 Chrome/Edge 的 mojo 通道 `拒绝访问`）→ 用同一个 MCP Playwright 替身口径（`reports/2026-11-14-before-baseline.md` 同一套选择器 / 同一算法）测前后：品牌页**手机端 chrome 占比 0.460 → 0.197、AFCR 0.803 → 0.903**，桌面 AFCR 0.931 → 0.998；成分页 / 结果页无实质变化。**官方 7 项仍需真 Chrome 补跑**（见 §4）。
7. 体积：dist 974,169,676 B → **980,743,373 B（+6,573,697 B / +0.67%）**，全部来自名字页成分卡的中文名（平均 +81 B/页）。单页 gzip：品牌页 1,489 → 1,836 B；成分页 19,119 B 不变。

## 1. 改了什么（`site/build.py`，按 C1–C5）

| 条目 | 改动 | 位置 |
|---|---|---|
| **C5 共享中文名映射** | 新增模块级 `SUB_ZH` + `load_substance_zh(db)`（唯一数据源 `substance.inn_zh`）+ `_sub_zh_name(sid)`（只返回含 CJK 的值，不硬翻）。`main()` 在建成分页之前装一次（日志 `ingredient zh: 3,103 substances with inn_zh`）；成分页 H1 下方、品牌页成分卡、配方差异表都读这一个函数 | 近 `SUB_NAME_LANG`；`build_drug_pages`（原 `inn_zh or ""` 改为 `_sub_zh_name(sid)`） |
| **C1 成分自己的中文名** | 品牌页成分卡：`<a data-zh="1">Acetaminophen</a><span class="name-zh" data-inn-zh hidden>对乙酰氨基酚</span>`；`i18n.js` 的 `applyNameLangBadges()` 遇到 `data-zh="1"` 直接返回 → 「无中文名」徽标**只贴在没有中文名的名称上**，不再贴成分 | `build_name_pages` 成分卡；`applyNameLangBadges` |
| **C2 标题与内容一致** | 品牌页原「同一品牌在其他市场的写法」+ 编辑中文注 → 改为 **「相关品牌名称与配方差异」表**：市场 / 注册名 / 完整活性成分 / 关系说明；表前一句「同一品牌名在各市场注册名与成分可以不同，下表只做身份对应——不是翻译对照，也不代表可以互换」。**不再把品牌关系写成翻译关系** | `_family_block()` 重写 + `_key_subs / _key_releases / _family_relation / _family_ing_html / _family_name_html` |
| **C3 去掉内部术语** | 品牌页不再渲染 `brand_family.note`（原文含「属严重碰撞」且只有中文）；搜索结果页的族警示正文改成 `name.severe`（「这个商品名在不同国家或不同变体下指向不同活性成分，选药前必须核对成分，不能按名字等同」）。关系说明只由成分集合 + 释放机制推导（`fam.rel.same/diff/partial/release/none`）。`collision` 视图**未改**、无手工标注 | `_family_block`；搜索结果页 `famnotice` |
| **C4 名称去重** | 新增 `_dedupe_variants(display, variants)`：NFKC + 空白折叠 + casefold，把标题本身也放进判重集合 → `Tylenol Extra Strength / TYLENOL EXTRA STRENGTH` 只算一条（该页「写法」整行消失）；族列表去掉 `<span class="tag">key</span>`（`泰诺 泰诺` 的来源） | `_dedupe_variants`；`build_name_pages` 头部；`_family_block` |
| 构建期守卫 | 名字页渲染后再查一次「碰撞」，命中就 `SystemExit` 中止构建；沿用既有 `_assert_no_internal_tokens` | `build_name_pages` 写盘前 |

文案 12 个新键（`fam.cmp_title / cmp_intro / cmp_market / cmp_name / cmp_ing / cmp_rel / cmp_this` + `fam.rel.same / diff / partial / release / none`）分别写进 `UI_I18N` 的 en / es / zh / zh-Hant 与 `FR_I18N`；zh-Hant 走 `_install_zh_hant()` 的 extra 字典，**没有**去改 `data/i18n_zh_hant.json`（不在写作用域）。

## 2. 验收证据

### 2.1 构建

```powershell
$env:SITE_OUT='.tmp/dist-v0116'; & $py site/build.py   # == done ==
```

```
drug pages : 12438   name pages : 80885   combo pages: 6896   maker pages: 15213
core.json  : 45.2 MB (legacy index.json: off)   total size : 980.7 MB
i18n zh-Hant: 572 keys (560 from json, 12 fallback zh)
i18n 四语一致: 572 keys × 5 语言（zh-Hant 回落 0 个已登记 key）
```

> 注：本次构建早于 Lead 把 v0.11.6 写进 `CHANGELOG.md`，所以临时产物页脚仍是 `v0.11.5 · 2026-11-13`；发布构建会自己取新版号，无需在这里改。

### 2.2 三处页面的 before / after（真浏览器 DOM，`?lang=zh`）

工具：MCP Playwright（Chrome/157，DPR 1）；before = `site/dist`（v0.11.5）+ `& $py serve.py 8011`，after = `.tmp/dist-v0116` + `python -m http.server 8012`。

**(a) `/name/tylenol-extra-strength.html`**

| 项 | before | after |
|---|---|---|
| 写法行 | `写法: Tylenol Extra Strength、TYLENOL EXTRA STRENGTH` | **整行消失**（两条都等于标题，仅大小写不同）→ C4 |
| 成分卡 | `Acetaminophen<span class="st-badge st-unknown nolang-badge">无中文名</span>` | `Acetaminophen 对乙酰氨基酚`，无徽标 → C1 |
| 卡 DOM | `<a href="../drug/acetaminophen.html">Acetaminophen<span class="st-badge…">无中文名</span></a>` | `<a href="../drug/acetaminophen.html" data-zh="1">Acetaminophen</a><span class="name-zh" data-inn-zh style="display: inline;">对乙酰氨基酚</span>` |
| H2 | `同一品牌在其他市场的写法` | `相关品牌名称与配方差异` → C2 |
| 正文 | 警示 `强生同一商标；…三家不同成分，属严重碰撞。` + `泰诺 泰诺`、`泰诺林 泰诺林` 两条列表 | 一句口径说明 + 表格（3 行）→ C2/C3/C4 |
| 表格（after，zh） | — | 表头 `市场 / 注册名 / 完整活性成分 / 关系说明`；行：`CA、US｜Tylenol Extra Strength 本页｜Acetaminophen 对乙酰氨基酚｜活性成分相同`；`CN｜泰诺｜Acetaminophen 对乙酰氨基酚、Chlorphenamine 马来酸氯苯那敏、Dextromethorphan 氢溴酸右美沙芬、Pseudoephedrine 盐酸伪麻黄碱｜成分部分相同，不是同一复方，不可互换`；`CN｜泰诺林｜Acetaminophen 对乙酰氨基酚｜成分相同，释放机制不同，不可互换` |

**(b) `/drug/acetaminophen.html`**

- after 的 `<main>` 正文与 before **逐字节相同**（`[...]<main>…</main>` 比对），页面字节同为 160,024 B、gzip 19,119 B：C5 是**源码层统一映射**，不改变成分页外观。
- 该页 before/after 都是 `h1 <span data-nl="en" data-zh="1">Acetaminophen</span>` + `.drug-name-src` 里的 `对乙酰氨基酚`，`?lang=zh` 下 `display: inline`、`?lang=en` 下 `display: none`，**无「无中文名」徽标**（说明徽标问题只在品牌页）。

**(c) `/name/泰诺.html`（含泰诺/泰诺林的中文品牌页）**

| 项 | before | after |
|---|---|---|
| 4 张成分卡 | `Acetaminophen无中文名`、`Pseudoephedrine无中文名`、`Dextromethorphan无中文名`、`Chlorphenamine无中文名` | `Acetaminophen 对乙酰氨基酚`、`Pseudoephedrine 盐酸伪麻黄碱`、`Dextromethorphan 氢溴酸右美沙芬`、`Chlorphenamine 马来酸氯苯那敏`，`.nolang-badge` 数量 0 |
| H2 | `同一品牌在其他市场的写法` | `相关品牌名称与配方差异` |
| 族表（after） | — | `CN｜泰诺 本页｜4 个成分｜活性成分相同`；`CA、US｜Tylenol Extra Strength｜Acetaminophen 对乙酰氨基酚｜成分部分相同，不是同一复方，不可互换`；`CN｜泰诺林｜Acetaminophen 对乙酰氨基酚｜成分部分相同，不是同一复方，不可互换` |
| 页面中文字数 | 237 字 | 538 字（多了表格的 4 列标签与关系说明） |

**五语实测**（同一页 `?lang=en|es|zh|zh-Hant|fr`）：表头分别 `Market/Registered name/All active ingredients/Relation`、`Mercado/…/Relación`、`市场/注册名/完整活性成分/关系说明`、`市場/註冊名/完整活性成分/關係說明`、`Marché/…/Lien avec cette page`；英文/西语/法语界面下 `[data-inn-zh]` 全部 `display:none`（不混中文），中文/繁体 `inline`。

**C3 复验（搜索结果页 `/index.html?q=泰诺`）**：before 的族警示正文 = `…三家不同成分，属严重碰撞。`（页面 `innerText` 命中「碰撞」）；after = `这个商品名在不同国家或不同变体下指向不同活性成分，选药前必须核对成分，不能按名字等同。`（0 命中）。

### 2.3 全量扫描（80,885 个名字页，`.tmp/t12_verify.py`）

| 检查 | 结果 |
|---|---|
| 出现「碰撞」的名字页 | **0** |
| 有「写法」列表的名字页 | 9,452（改前 11,528）→ 2,076 页的写法全等于标题，整行自然消失 |
| 列表内重复（含与标题重复，NFKC+casefold 口径） | **0**（改前 11,528 页里 **3,691 页**有重复） |
| 仍是「`<a>x</a><span class="tag">x</span>`」的名字页 | **0** |
| 出现新族表（`fam.cmp_title`）的名字页 | 8（4 个品牌族 × 有页成员；`gaviscon original aniseed relief` 无独立页 → 表内显示为不可点文本） |
| 族表内站内链接 | 144 条，**缺目标 0**（其余 `?lang=` / `data:` 不是页面链接） |
| `404.html` | 在位（2,621 B）；无品牌的普通名字页（`name/ibuprofen.html`）仍只有 1 张成分卡 + 1 个中文名，无族表、无「碰撞」 |

### 2.4 i18n

```powershell
& $py deploy/i18n_check.py --json .tmp/i18n-after.json
# 有效字典: en 572 / es 572 / zh 572 / zh-Hant 572 / fr 572 键
# FAIL 0 / WARN 2 / INFO 24   （改前 560 键、FAIL 0 / WARN 2 / INFO 24）
```

`fr 译文 568/572`（4 个键回落英文，其中本改 0 个：12 个新键都给了法语）；`伪翻译(值==en) 87 条 {INFO 85, WARN 2}` 与改前同。构建期另有 `i18n 四语一致: 572 keys × 5 语言` 硬拦通过。

### 2.5 CI（fast）

```powershell
& $py deploy/ci_checks.py --fast --dist .tmp/dist-v0116
# PASS py_compile 172 文件 / unittest:etl 55 / unittest:lib 61 / unittest:mobile 29
#      unittest:lib-atc-category 4 / dist-integrity 125,510 文件·0 字节 0·sitemap 66,300
#      workflow
# FAIL i18n  release-latest-missing: 最新版 v0.11.6 在 release_notes_i18n.json 里没有译文
# SKIP trilingual / check_data / ui-surface / first-screen（--fast 跳过）
# 12 项：PASS 7 / FAIL 1 / SKIP 4（11.8s）
```

FAIL 归属：`data/release_notes_i18n.json` 缺 v0.11.6 五语译文（`CHANGELOG.md` 已有 v0.11.6 一节）。**不在本工位写权限（`data/`）**，需另一工位或 Lead 补；与本改的 `site/build.py` 无关（改前跑同一命令时 v0.11.5 译文是齐的，FAIL 是版本号前移后才出现）。

### 2.6 首屏守卫（官方不可用 → 同口径替身，前后各一次）

官方脚本报错原文：

```
File "deploy/ui_surface_check.py", line 434, in launch_chrome
    raise RuntimeError("Chrome 未就绪（--remote-debugging-port 没起来）")
```

直接起 Chrome/Edge 也被沙箱挡住：`FATAL:mojo\public\cpp\platform\platform_channel.cc… Check failed: 拒绝访问 (0x5)`。
替身口径 = `reports/2026-11-14-before-baseline.md` §1.2 那一套（同选择器表、同 0.9/0.25 折算、同 16 px 网格、同 chrome 选择器），本次**同一会话、同一脚本、同一 `?lang=zh` 状态**分别打 before(8011) / after(8012)：

| 页 | 视口 | 首屏条目 | chrome 占比 | AFCR | 最小字号 | <12 px | 横向溢出 | 文档高 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 品牌页 tylenol-extra-strength | 1440×900 | 3 → **4** | 0.265 → **0.231** | 0.931 → **0.998** | 13 / 13 | 0 / 0 | 0 / 0 | 900 → 900 |
| 品牌页 tylenol-extra-strength | 390×844 | 3 → **3** | 0.460 → **0.197** | 0.803 → **0.903** | 13 / 13 | 0 / 0 | 0 / 0 | 867 → 1,278 |
| 成分页 acetaminophen | 1440×900 | 9 → **9** | 0.141 → 0.141 | 0.997 → 0.997 | 13 / 13 | 0 / 0 | 0 / 0 | 8,356 → 8,356 |
| 成分页 acetaminophen | 390×844 | 5.5 → **5.5** | 0.197 → 0.197 | 0.903 → 0.903 | 13 / 13 | 0 / 0 | 0 / 0 | 11,751 → 11,751 |
| 结果页 `?q=Tylenol` | 1440×900 | 4.5 → 3.5 | 0.093 → 0.093 | 0.960 → 0.960 | 13 / 13 | 0 / 0 | 0 / 0 | 2,197 → 2,413 |
| 结果页 `?q=Tylenol` | 390×844 | 1 → 0.5 | 0.177 → 0.194 | 0.860 → 0.841 | 13 / 13 | 0 / 0 | 0 / 0 | 3,807 → 3,976 |

- **品牌页是本改的直接受益页**：手机端 chrome −0.263（警示条被表格取代）、AFCR +0.100，首屏条目 3 → 3（持平：4 列表格在手机上改为两列后，市场/注册名同行、成分与关系说明各占整行，表高 686 → 518 px、页面 1,540 → 1,278 px，条目数回到改前水平；见下方 CSS 说明）。
- **成分页零回归**：AFCR / chrome / 条目 / 文档高与改前**完全相同**（正文逐字节相同）。
- **结果页的差值不是本改引起**：单独复测 `?q=Tylenol&lang=zh` 稳定态，两版 layout 完全相同（`docH 3,807` 都是；`#reswrap` top 589 / h 2,277 都一样）——差异来自「完整索引懒加载中」的行数状态，属替身噪声。
- **手机端两列 CSS**（`table.res.famcmp`，只在 `max-width:767px` 生效）：四行逐格堆叠时整表 686 px，两列后 518 px；字号仍是 16 px（不碰正文下限），实测桌面端表高 234 px 不受影响。
- 阈值核对（`deploy/first_screen_check.py` 自带表：内容页 AFCR ≥0.50、chrome ≤0.35、名字页 `items_min 1`、成分页 `items_min 5`、结果页 `items_min 5`）：品牌页 / 成分页全项达标（品牌页条目 3 ≥ 1）；**结果页条目 3.5 (1440) 与 0.5 (390) 低于 5，改前 4.5 / 1 也不达标** → 既有缺口，不是本改的回归，仍需官方守卫复核。

### 2.7 体积 / 页数回归（对照 `site/dist` = v0.11.5）

| 指标 | v0.11.6（.tmp） | v0.11.5（site/dist） | Δ |
|---|---:|---:|---:|
| 文件数 | 125,510 | 125,510 | 0 |
| HTML | 125,290 | 125,290 | 0 |
| 名字页 / 成分页 | 80,885 / 12,438 | 80,885 / 12,438 | 0 / 0 |
| 总字节 | 980,792,379 | 974,169,676 | **+6,622,703（+0.68%）** |
| 名字页总字节 | 342,608,097 | 336,052,106 | +6,555,991（+81 B/页，= C1 的中文名） |
| 成分页总字节 | 156,231,371 | 156,231,371 | 0 |
| `whats-new.html` | 306,450 | 297,149 | +9,301（CHANGELOG v0.11.6 一节，非本改） |
| 0 字节文件 | 0 | 0 | 0 |
| sitemap URL | 66,300 | 66,300 | 0 |
| `data/idx/core.json` | 45.2 MB | 45.2 MB | 0（不动索引） |
| 单页 >6 KB（HTML） | 32,977 | 32,915 | +62（全是名字页：多一张族表或多张成分卡） |

单页 raw / gzip(9)：`name/tylenol-extra-strength.html` 3,412 → **5,801** / 1,489 → **1,836**；`name/泰诺.html` 4,850 → **7,616** / 1,691 → **2,038**；`drug/acetaminophen.html` 160,024 → 160,024 / 19,119 → 19,119。
首屏静态资源：`assets/style.css` gzip 19,348 → 19,724（+376，含 §2.6 的手机两列规则）、`assets/i18n.zh.js` gzip 23,981 → 24,347（+366，12 个新键）、`app.js` gzip 58,769 → 59,066（+297，搜索结果页族警示与标题）——远低于 110 KB gz 首屏预算。
**取舍**：+62 个名字页越过 6 KB 单页软预算（最大 `泰诺.html` 7,616 B），换来 C1 的中文成分名与 C2 的差异表；若要压回 6 KB，只能砍表头行或中文名，属于产品取舍，本工位不擅自删。

### 2.8 三语抽检 + 链接

三语 × 三条查询（`Tylenol` / `benadryl` / `泰诺`，`?lang=en|es|zh`）：9 组全部渲染出结果行（20 / 20 / 3 行）、族警示按语言正确（`Same brand, different drug：Benadryl。` / `Misma marca, otro medicamento：Benadryl。` / `同名不同药：Benadryl。`）、`pageerror` 0、页面 `innerText` 里「碰撞」0 命中。

## 3. 数据与红线核对

- `collision` 视图、`brand_family` / `name_family` **一个字节都没改**；关系说明是**构建期从成分集合与释放机制推导**（`_family_relation`），不是人工标注；`brand_family` 仍是唯一人工表。
- 没有新增任何用药建议 / 剂量换算 / 可替代判断：新文案只说「成分相同 / 不同 / 部分相同 / 释放不同」+「不可互换」，与 §1.3 一致。
- 数据层零改动：`data/drugs.db` 未写；`data/sources/*_20261114.csv`（其他工位产物）未读入本次实现。
- **`brand_family.note`（编辑中文注）不再出现在任何页面上**：品牌页由差异表取代，搜索结果页改用 `name.severe` 的既有译文。原文仍在库里（`brand_family.note`），如需在页面保留这段编辑说明，需要先有 en/es/zh-Hant/fr 译文（属 i18n 翻译任务）。

## 4. 已知缺口 / 留给下一段

1. **官方首屏守卫（7 项指标）未跑**：本机 Chrome/Edge 被沙箱挡住 CDP。需在有真 Chrome 的环境补 `& $py deploy/first_screen_check.py --dist <产物> --pages name,drug,results --json …`，并把 §2.6 的替身数字当参考、不当结论。
2. **`ci_checks --fast` 的 i18n FAIL（v0.11.6 release notes 缺译文）**：需 `data/release_notes_i18n.json` 补 v0.11.6 的 en/es/zh-Hant/fr（zh 已有 CHANGELOG 原文）；不补则发布门槛过不去。
3. **碱基/盐型会被读成「部分相同」**：`立普妥`（Atorvastatin）vs `Lipitor`（Atorvastatin + Atorvastatin Calcium）显示 `fam.rel.partial`。这是 `substance_id` 粒度的既有事实（`collision` 视图同样按 `COUNT(DISTINCT substance_id)` 计数），要收敛得靠 `variant.salt_code` / `base_fraction` 的完整性（T15 记：`base_fraction` 全 1.0、`salt_code` 仅 15% 有值）——留给 T10/T15，不在显示层打补丁。
4. **zh-Hant 用户看到的成分中文名是简体**（`inn_zh` 只有一份简体）。与成分页既有行为一致（v0.11.4 task-63），本次不扩大。
5. 品牌页不做「一屏 5 条」类目标：结构就是一屏 1 张成分卡 + 族表，官方 `items_min` 对名字页是 1。

## 5. 复跑命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'

$env:SITE_OUT='.tmp/dist-v0116'; & $py site/build.py            # 等 == done ==
& $py deploy/i18n_check.py                                      # FAIL 0 / WARN 2
& $py deploy/ci_checks.py --fast --dist .tmp/dist-v0116         # 唯一 FAIL = release notes v0.11.6
& $py .tmp/t12_verify.py .tmp/dist-v0116                        # 全量扫名字页（C3/C4）+ 三页抽样
& $py .tmp/t12_impact.py                                        # 页数/体积/单页预算
& $py serve.py 8011                                             # before 对照（site/dist）
& $py -m http.server 8012 --directory .tmp/dist-v0116           # after
# 首屏：deploy/first_screen_check.py（需真 Chrome）；替身脚本见本报告 §2.6 与
#       reports/2026-11-14-before-baseline.measure.js（改 BASE 指向 8012 即可）
```
