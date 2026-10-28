# 谷段自动工作汇报 — 2026-10-29（v0.5.2 → v0.6.x）

> 状态：**框架 v1（收尾版，2026-10-29 发布结束后定稿）**。`v0.5.2–v0.8.4` **已发布 19 版**（v0.6.6 内部版本号未单独发布，已并入 v0.6.7）；**v0.8.4 为今晚最后一版**：smoke **32/32**、tag/Release、commit `611a45afa`、gh-pages `b2123de77`；dist **62,217 文件 / 472.5 MB**、sitemap **62,057**；增量上传 **13.37 MiB**（−97.2%）、526s。**最终 metrics + dashboard 已按最终 dist 跑完**（`reports/metrics/2026-10-29.json`、`docs/工作集群-架构与进度.html` + `docs/img/cluster-progress.png`）；下一谷段：v0.8.5（task-131 大类 v2+ATC 去重）→ HK build（task-132）→ HK 版本；task-133 统一 DB 窗口。
> **2026-10-29 更新**：TW 数据已由 data-depth 写入真实库（非发布，等 task-81 build 支持后 v0.7.0）；最终版本数、站点体积/页面数、线上 smoke、nightly metrics 与 dashboard 快照在最后一版发布完成后回填（发布经理确认 dist 稳定后再跑）。
> 数据口径：`data/drugs.db` 只读现查（2026-10-29）；站点数字以最终 build 为准；不夸大未验证项。

---

## 1. 结论（截至 v0.8.1）

- 本谷段**已连续发布 19 个版本（v0.5.2 → v0.8.4；v0.6.6 内部版本号未单独发布）**：**9 个市场**、四语（en/es/zh/zh-Hant）全站；v0.8.4 为今晚最后一版；
  - **页面体系**：品牌页 / 组合页 / 厂家页 / 术语表页，结果行可展开产品明细（A1）、可复制/导出（B7）；
  - **跨市场**：141 个成分身份合并（substances 12,790 → **12,649**），组合页跨市场同组合区块；
  - **体积**：DB VACUUM **450 MB → 325 MB**；站点停写冗余 `data/index.json`（发布体积 −54.9 MB）；
  - **检索**：首搜 ~254 KB（分片）、ATC 码搜索（113,244 条目带码）、`/glossary` 13 术语 × 4 语；
  - **语言**：zh-Hant 界面（/zh-hant/ 5 页 + 繁→简检索 2,966 字对）；zh-Hant 文案字典本轮补齐至 **328 键**（v0.6.2 时 247/328）。
- **v0.7.0 已上线**：台湾 TFDA **16,457 产品**、四语国家列表/chips、成分页矩阵 **TW 列**、zh-Hant 全站启用、TFDA OGDL v1.0 署名；live v0.7.0、smoke **0 failures**、tag v0.7.0、gh-pages `3ce2b035`（Release 待发布经理确认）。
- **v0.7.1 已上线（ATC 类别浏览）**：1,154 个 ATC 类目页（L1–L4）+ 16 常见大类入口 + `/atc.html` + 四语类名/类名搜索 + WHO ATC/DDD 引用；smoke 32/32、tag/Release 已建、gh-pages `29fab5ecd`、dist 61,547 文件/446.2 MB、sitemap 61,390、增量上传 13.85 MiB（−96.9%）/511s。
- **v0.8.0 已上线（SG）**：HSA 5,511 产品、全库 **431,555**；四语国家列表/chips/矩阵新增 SG 列，站点 **9 个市场**；矩阵 9 列全显不再截断；About HSA/SODL v1.0 署名与数据截止 2026-08-07，明确「在册名单不代表在售」、商品名保留英文；smoke 32/32、gh-pages `fc7986d1a`、dist 62,878 文件/455.7 MB、sitemap 62,720、增量 17.94 MiB（−96.1%）/515s。
- **v0.8.4 已上线（今晚最后一版，第 19 版）**：显示层修复——剂型去重、异常规格「待核」、长品牌名截断、状态角标、空值语义、CN 拉丁品牌旁中文通用名；smoke 32/32、commit `611a45afa`、gh-pages `b2123de77`、62,217 文件/472.5 MB、sitemap 62,057、增量 13.37 MiB（−97.2%）/526s。
- **v0.8.3 已上线（排序/筛选器 + 伪复方归并）**：矩阵常用剂量排序+空行隐藏+筛选器（国家/剂型/释放/规格/URL/移动抽屉）+ 伪复方 base 归并（combo 10,942→10,284、severe 19,381→18,862）；smoke 32/32、gh-pages `6e864fdaf`、dist 62,217 文件/468.4 MB、sitemap 62,057、增量 16.52 MiB（−96.5%）/594s。
- **v0.8.2 已上线（七项修复）**：零结果埋点+搜索词周报、ATC 大类四语、ATC 成分名中文化、引导卡上移、搜索后收起大类、页头响应式、矩阵列错位修复+当地注册名标注；What's new 补 v0.6–v0.8 译文；smoke 32/32、gh-pages `75b81209f`、dist 62,880 文件/476.0 MB、增量 15.01 MiB（−96.8%）/564s。
- **v0.8.1 已上线（双语对照）**：本市场原名 + 当前语言译名（默认 zh 536 / es 640）+ 来源徽章 + 数据版本 v2026-10-28.1；无译名回退原名、品牌永不翻译；「显示原文对照」默认开启（zh-Hant 暂回退原名）；smoke 32/32、gh-pages `46a6bfd37`、dist 62,880 文件/463.7 MB、sitemap 62,720、增量 14.92 MiB（−96.8%）/519s；体积 +8 MB。
- **后续（v0.8.x）**：`v0.8.2`（零结果埋点 + ATC/UI 多项修复，开发中）→ 第 17 版；`v0.8.3`（成分页矩阵常用剂量优先排序 + 筛选器 + 空行隐藏，待做）→ 第 18 版（最后一版）；`v0.8.2` = **零结果埋点 + ATC 大类四语修复 + 首页三步引导卡上移（待发，impl-lazyload）**：search0-* 匿名零结果事件（去重/防抖/≤64 字）、About 四语隐私说明、`deploy/analytics_report.py --search-weekly` 周报（Top 搜索词/零结果聚类/语言国家）；**bug 修复 1**：中文界面 ATC 大类入口仍显示英文类名；**bug 修复 2**：ATC/大类页「该类别下的活性成分」在中文界面仍显示英文（用户截图）；**UI 修复**：首页「三步看懂」引导卡位置上移/更醒目（用户截图要求）；**UI 修复 2**：搜索后收起首页「按大类浏览」（用户截图要求）；**UI 修复 3**：页头导航/语言切换换行崩坏（中文 nav 单字竖排、logo 副标题/语言切换断行）；最终 **18 版**（v0.8.2=17、v0.8.3=18），metrics/dashboard 等最后一版后跑。
- **TW 数据已入库并随 v0.7.0 上线**：2026-10-29 写入真实库——products 409,587→**426,044**（TW **16,457**）、product_component +28,721、product_name +32,899，substances/variants 不变，DB 325.4→**351.4 MB**；`markets.json` TW / `languages.json` zh-Hant 已启用，TW 页面已构建并随 **v0.7.0** 发布（About 加 TFDA OGDL v1.0 署名）。
- **新批准需求已入队（task-82~86）**：ATC 类别浏览、术语基准表+AI 译文校验、评测集 500+ 与 RxNorm oracle、CN 商品名扩充、HK/MO 审计。
- **用户 2026-10-29 决定**：**HK** 下一谷段上线（名称/成分层，无规格/剂型/状态，页面明示；task-88 准备中）；**SG 提前**（HSA 免费、明确可再发布、有规格、英文市场；排在 HK 后、PT 前）；**PT 降为备选/暂缓**（pt-PT UI 与 EMA/EU 层不优先；等 INFARMED 回复或澳门数据需要葡语字段再评估，不排期）；**CN 商品名不花钱**（不询价/不采购商业 API，接受开放来源已吸收 98.4%，缺口 60,984 批文 / 128,060 产品无商品名记档；不再列人工种子，低优先找 CC0/CC-BY 说明书数据集）；**MO 先链接层 + 申请保留**（task-89 起草申请信，用户本人发，获批前不入库）。

---

## 2. 版本一览

| 版本 | 日期 | 一句话 |
|---|---|---|
| v0.5.2 | 2026-10-29 | /warn 与成分页警示在中文/西语下空白热修（display 显式 block） |
| v0.5.3 | 2026-10-29 | 品牌/成分点击目标修复；新增品牌页 29,140 / 组合页 9,339；索引 `cu`/`mu` |
| v0.5.4 | 2026-10-29 | 厂家页 6,997（≥5 产品阈值）；品牌/成分/厂家三类跳转分开 |
| v0.5.5 | 2026-10-29 | 中文成分名 `xz`（65,075 条）；页面 title/description/OG/canonical/hreflang 本地化 + `/es/` `/zh/` 静态副本；What's new 三语；batch A+B 合并 141 成分；VACUUM 450→325 MB |
| v0.5.6 | 2026-10-29 | A1 产品详情懒加载；A3 盐型/释放/警示徽章；B6/B7 行级报告 + 复制/CSV；What's new 24 版本修复 |
| v0.6.0 | 2026-10-29 | 组合页跨市场同组合区块（exact 326 / overlap 8 / none 4,509 / unmatched 4,448 中性） |
| v0.6.1 | 2026-10-29 | 停写 55 MB `index.json`，core 唯一索引；dist 450→395 MB；core 加剂型字段 |
| v0.6.2 | 2026-10-29 | 繁体中文 UI（/zh-hant/ 5 页 + hreflang + 繁→简检索 2,966 字对）；TW 源注册 + schema 迁移就绪 |
| v0.6.3 | 2026-10-29 | 首屏三步引导（U1）、各国叫法横排（U2，安全单成分）、标签本地化（U3） |
| v0.6.4 | 2026-10-29 | ATC 码搜索（C07AB02→99、C07→680）；/glossary 13 术语 × 4 语；`/`、`Esc` 快捷键；57,697 URL |
| v0.6.5 | 2026-10-29 | EN/ES 界面中文残留清理（logo 副标题仅 zh、About 段落本地化）；首页示例按钮按语言；首搜提示改 ~0.2 MB 分片；四语 328 键对齐；已 published gh-pages e78d47f9f |
| v0.6.7 | 2026-10-29 | 合并发布（含 v0.6.6 成分页矩阵，内部版本号未单独 tag/Release）：成分页多国并排矩阵（行=规格/剂型/释放、列=国家≤8，语言优先列序）+ /warn 分页（10/页，?page=N）；四语 336 键；增量发布实测 27.55 MiB / −93.4% / 602s；smoke 32/32，gh-pages b650b30fb |
| v0.7.0 | 2026-10-29 | 台湾 TFDA 16,457 产品 / 四语国家列表 / chips / 矩阵 TW 列 / zh-Hant 全站启用 / TFDA OGDL v1.0 署名 / TW 规格解析提示；live v0.7.0、smoke 0 failures、gh-pages 3ce2b035 |
| v0.7.1 | 2026-10-29 | ATC 类别浏览：1,154 个 ATC 类目页（L1–L4）+ 16 常见大类 + /atc.html + 四语类名/类名搜索 + WHO ATC/DDD 引用；smoke 32/32，gh-pages 29fab5ecd，61,547 文件/446.2 MB，sitemap 61,390 |
| v0.8.0 | 2026-10-29 | 新加坡 HSA 5,511 产品（全库 431,555）；四语 SG、9 市场矩阵全显（不再截断）、About HSA/SODL v1.0 署名；「在册名单不代表在售」、商品名保留英文；smoke 32/32，gh-pages fc7986d1a，62,878 文件/455.7 MB，sitemap 62,720 |
| v0.8.1 | 2026-10-29 | 双语对照显示：本市场原名 + 当前语言译名（zh 536/es 640）+ 来源徽章 + 数据版本 v2026-10-28.1；无译名回退原名、品牌永不翻译；显示原文对照默认开；smoke 32/32，gh-pages 46a6bfd37，62,880 文件/463.7 MB，sitemap 62,720 |
| v0.8.2 | 2026-10-29 | 七项修复：零结果埋点+搜索词周报、ATC 大类四语、ATC 成分名中文化、引导卡上移、搜索后收起大类、页头响应式、矩阵列错位修复+当地注册名标注；What's new 补 v0.6–v0.8 译文；smoke 32/32，gh-pages 75b81209f，62,880 文件/476.0 MB |
| v0.8.3 | 2026-10-29 | 排序/筛选器 + 伪复方 base 归并：常用剂量排序（跨国家记录数、未公开最后）、空行隐藏、筛选器（国家/剂型/释放/规格/URL/移动抽屉）、伪复方 base 归并（combo 10,942→10,284、severe 19,381→18,862）；smoke 32/32，gh-pages 6e864fdaf，62,217 文件/468.4 MB，sitemap 62,057 |
| v0.8.4 | 2026-10-29 | 显示层修复：剂型去重、异常规格「待核」、长品牌名截断、状态角标、空值语义、CN 拉丁品牌旁中文通用名；smoke 32/32，commit 611a45afa，gh-pages b2123de77，62,217 文件/472.5 MB，sitemap 62,057 |
| *v0.8.5* | *计划* | *大类映射 v2 + ATC 去重（task-131：减肥药补 GLP-1、感冒/过敏拆分、他汀去撤市、cap 截断、ATC 去重）；ATC 类名四语数据（task-130，Wikidata CC0）* |
| *v0.8.6 / v0.9.0* | *计划* | *HK 市场版本（task-132 HK build 后；视发布进度定版本号）* |

> **版本计数以实际 tag 为准**：v0.6.6 不对外（无 tag/Release），已并入 v0.6.7 行「含 v0.6.6 矩阵（内部版本号未单独发布）」；当前 **12 版（v0.5.2–v0.6.7）**，v0.7.0 后 13 版。

---

## 3. 每版要点（按 CHANGELOG 摘要）

- **v0.5.2**：/warn 与成分页警示在中文/西语下空白——语言块显隐把匹配项设为 `display:''` 回落到 CSS `display:none`，三块全隐藏；改为显式 `display:block`。中/西语恢复 40 条警示与成分页摘要，英文不变。
- **v0.5.3**：点品牌只进品牌页（无页不可点，不再回退第一个成分的药物页），单方→药物页、复方→新组合页；品牌页 29,140（新增 11,270 个 ≥2 包装的 trade 轻量页）、组合页 9,339（覆盖 37,514 条复方条目）；索引新增 `cu` 字段，88 个抽样链接 0 404。
- **v0.5.4**：厂家页 6,997（≥5 产品；规范化去重、占位名不建页），列覆盖国家/产品品牌/成分/来源；结果行厂家可点，`+N` 每个厂家都有链接；索引/分片加厂家字段，三类目标彻底分开。
- **v0.5.5**：中文界面显示中文成分名（`xz` 65,075 条，回退英文）；页面元信息四类本地化 + `/es/` `/zh/` 静态副本；What's new 三语（AI 翻译标注）；batch A+B 合并 141 成分（12,790→12,649）、DB VACUUM 450→325 MB、补 2 个查询索引、外键清零。
- **v0.5.6**：A1 产品详情按桶懒加载（首次 ~180 KB gz）；A3 盐型/释放/警示徽章（警示链 /warn#w-ID）；B6 行级报告 + B7 复制表格/CSV；What's new 改 CHANGELOG 全量 24 版本为主列表、无译文显示中文并标「译文待补」。
- **v0.6.0**：9,291 个组合页加「其他国家同组合」区块——exact 326 / overlap 8 / none 4,509 / unmatched 4,448 中性；「仅主成分相同」降级标注，不把复方当单方替代；构建期读 `combo_match_candidates.csv`，零运行时开销。
- **v0.6.1**：停写冗余 `data/index.json`（55.1 MB），core 成为唯一索引；`?legacy=1` 统一 core+decodeCore，结果逐字段对拍一致；dist 450→395 MB，GH 单文件 50 MB 警告消失；core 加剂型字段。
- **v0.6.2**：新增繁体中文界面（语言切换「繁」、/zh-hant/ 首页与 About/What's new/Confused/Warn 5 页、hreflang `zh-Hant`、浏览器语言自动识别）；繁→简输入归一 2,966 字对（OpenCC 子集）；站点 +5 页 +3.2 MB。
- **v0.6.3**：首屏三步引导（真实示例、可关闭记住、四语、防布局跳动）；结果顶部「各国叫法」横排（能唯一确定单成分时，未收录明确显示；多成分自动隐藏）；剂型/释放/单位/状态标签四语本地化。
- **v0.6.4**：ATC 码搜索（成分级 C07AB02、类目级 C07/C07A 前缀；普通药名不误判）；`/glossary.html` INN/BAN/USAN/ATC/MAH/DIN/NDC/ARTG 等 13 术语四语；`/` 聚焦、`Esc` 关闭；索引新增 ATC 字段（113,244 条目带码）。
- **v0.6.5**：英文/西语界面去中文残留（首页 logo 副标题仅 zh 显示；About 昵称/类别词/已知缺口段落改本语言文案，如 Two frogs (liǎng zhī qīngwā)、pastilla para dormir）；首页示例按钮按语言本地化（en/es/zh/zh-Hant 各 4 例）；首搜提示四语改为「首次只加载一小片索引（约 0.2 MB），完整索引后台补全」；四语 328 keys 完全对齐；页面数/索引体积不变（57,848 文件 / 408.7 MB，sitemap 57,697 URL）；已发布 gh-pages e78d47f9f。

---

## 4. 数据变化（现查 `data/drugs.db`，只读）

| 指标 | 数值 | 说明 |
|---|---:|---|
| 产品总数 | **431,555** | 9 市场：7 市场 409,587 + **TW 16,457** + **SG 5,511**（均随 v0.7.0/v0.8.0 上线） |
| product_component / product_name | **527,166 / 601,806** | TW +28,721 组件 / +32,899 命名（入库存量） |
| variant / substance | **13,772 / 12,649** | TW 入库不新增成分；141 个成分合并后 |
| name_key / name_variant | 135,251 / 146,544 | 名字键未随 TW 改名（TW 命名走 product_name） |
| nickname / drug_term / alias_all | 57 / 1,062 / 1,119 | 中文互联网俗名 1,034 条、清理毒品黑话 337 行 |
| confusable_pair | 22 | FDA tall-man |
| dose_warning | 41（published **40**） | 1 条 draft 不发布 |
| ATC 覆盖 | 全部 **47.6%**（6,021 / 12,649）；药物实体 **67.4%**（5,702 / 8,459） | 以 `data/entity_type.csv` 分类；entity 文件待随库重建同步 |
| GB 盐型组件 | 16,396（2.0% → 25.0%） | `reports/gb-salt-recovery.md` |
| zh-Hant 字典 | **328 / 328 键** | 本轮补齐 81 键，`reports/zh-hant-i18n-refresh2.md` |
| DB 体积 | **364.2 MB** | v0.5.5 VACUUM 450→325.4 MB；TW+SG 入库后 364.2 MB（最终快照） |
| 各市场产品 | CN 146,347 · US 110,179 · GB 61,051 · CA 43,847 · ES 25,395 · AU 11,890 · MX 10,878 · **TW 16,457** · **SG 5,511**（v0.8.0 已上线） |
| 站点文件/体积/页面数 | **v0.8.4（最终）：62,217 文件 / 472.5 MB / 62,058 HTML**；sitemap **62,057**；drug 12,447 · name 31,134；core gzip **7.60 MB**（raw 32.5 MB）；首搜 0.25 MB gz / 首屏 95,439 B gz | 最终 dist，metrics 已跑 |

---

## 5. 测试与验证

- 本地单测（2026-10-28 复跑）：`etl` 25 项 OK、`lib` 29 项 OK、`mobile/inbox` OK。
- 三语回归（`tests/trilingual/run_tests.py`，72 例 / 354 查询，2026-10-28 晚复跑）：**68/72 通过；Top-5 97.7%、Top-1 96.0%、跨国可见 72/72**，对比 v0.5.0 基线（67/72、97.5%/95.8%）**无回归**；失败 4 例：dup_inn 3（ciclosporin / beclometasone / chlorphenamine，西语查询 Top1 命中英文名但排名被同名重复条目挤出）+ combo 1 例；明细 `.tmp/trilingual/results_overnight_20261029.json`（用时 556.3s）。
- **TW 入库后**：`quick_check` ok、FK 0；`tests.test_markets_registry::test_enabled_markets_match_db_countries` 1 项红为**预期过渡态**（DB 有 TW，markets.json 仍 disabled，等 task-81 启用后转绿）。
- `db/check_data.py`、`integrity_check`、FK：**待最终版本后复跑**（发布/合并期间不抢写库）。
- 发布 smoke：**v0.8.4 32/32**（gh-pages b2123de77；增量 13.37 MiB/−97.2%/526s；commit 611a45afa；今晚最后一版）；v0.8.3 **32/32**（gh-pages 6e864fdaf；增量 16.52 MiB/−96.5%/594s）；v0.8.2 **32/32**（gh-pages 75b81209f；增量 15.01 MiB/−96.8%/564s）；v0.6.7 **32/32**；v0.7.0 **0 failures**（Lead verify）；v0.7.1 **32/32**（gh-pages 29fab5ecd；增量 13.85 MiB/−96.9%/511s）；v0.8.0 **32/32**（gh-pages fc7986d1a；增量 17.94 MiB/−96.1%/515s）；v0.8.1 **32/32**（gh-pages 46a6bfd37；增量 14.92 MiB/−96.8%/519s）。
- nightly metrics / dashboard：v0.7.0 中间态已跑一次（metrics 见下；dashboard 快照已更新）；**v0.8.2（最后一版）发布后按最终 dist 再跑一次**（最后一次）并回填本报告最终数字。
- 最终 metrics **6 warnings（预期+需跟踪，非回退）**：`data/index.json` 缺失（v0.6.1 起主动移除，guardrail 未更新）、成分数 12,790→12,649（−1.1%，batch A+B 合并预期）、severe 15,509→19,386（+25%，TW/SG/双市场数据增加预期）、首搜 146 KB→249 KB gz（+70%，ATC 字段）、首屏 42 KB→95 KB gz（+125%，矩阵/四语/TW/SG/双语）、core gz 3.69→7.60 MB（+106%，ATC+TW/SG 索引）；**性能预算需下一谷段跟踪**。
- 不夸大：未收到发布经理确认的线上 smoke 数字不写进本报告。

---

## 6. 未完成项与下一步（与 `docs/谷段需求队列.md` 同步）

1. **TW 市场启用（目标 v0.7.0）**：数据已入库（16,457 产品）；**build 支持已完成（task-81）**；等 data-depth 启用 `markets.json` TW + `languages.json` zh-Hant → 国家列表/选择器/chips/i18n/覆盖页 → v0.7.0 构建发布。**v0.7.0 待发行内容**：TW 市场 / 四语国家列表 / chips / TFDA OGDL v1.0 署名 / 矩阵 TW 列（含 zh-Hant 启用）；验收：TW 产品数、成分映射 ≥85%、无 404、四语不回归。
2. **task-82 ATC 类别浏览 + 常见大类入口（build.py，v0.7.x，排 TW 后）**。
3. **task-83 术语基准表 + AI 译文自动校验（WHO INN/ATC/药典）**。
4. **task-84 搜索评测集 500+ + RxNorm oracle + CI 门槛**（替代原 320 例接 CI）。
5. **task-85 CN 商品名扩充（用户决定：不花钱）**：不询价/不采购商业 API，接受开放来源已吸收 98.4%；缺口 **60,984 批文 / 128,060 产品无商品名**记录在案；不再列人工种子；低优先继续找 CC0/CC-BY 说明书数据集。
6. **HK：下一谷段上线（名称/成分层）**：task-88（data-depth 准备中）；只做名称/成分层，无规格/剂型/状态字段，页面明示覆盖边界。
7. **SG（新加坡）提前**：HSA 免费可再发布、有规格、英文市场；排在 HK 后、PT 前；下一步审计 HSA 批量与字段 → 定入库/版本安排。
8. **MO：先做链接层 + 申请信（申请保留）**：task-89 起草申请信，用户本人发（免费前提下）；获批前不入库。
9. 市场/语言注册表接入 + 市场×语言矩阵；A4 覆盖与新鲜度页；/warn 分页；B8 对比；B9 手机粘性搜索；B11 分享卡剩余；U4–U7；UI P1 余项。
10. 剩余身份合并（CN）、ES partial 96 条、俗名扩展、ATC 长尾；索引收尾（254→~150 KB）。
11. **PT（葡萄牙）备选/暂缓**：pt-PT 界面与 EMA/EU 层不优先（除非澳门数据需要葡语字段），等 INFARMED 回复或需求出现再评估，不排期。
12. 文档侧：v0.8.1 已补队列行（16 版）；**v0.8.2（零结果埋点 + ATC/UI 多项修复，开发中）发布后补第 17 版行**；**v0.8.3（矩阵剂量排序 + 筛选器 + 空行隐藏，待做）发布后补第 18 版行**；**v0.8.4（显示层修复）/ v0.8.5（大类 v2 + ATC 去重，task-130/131）/ task-132 HK build / HK 市场版本（v0.8.6/v0.9.0）发布后逐版补行（版本数以实际 tag 为准；今晚能发多少算多少）**；**v0.8.3（最后一版）发布后按最终 dist 跑最后一次 metrics + dashboard**，回填本报告/README 最终数字。

---

## 7. 本轮文档维护动作（长期角色）

- `docs/谷段需求队列.md`：已完成区补 zh-Hant 328 键（标注 v0.6.2 后补 / v0.6.5 前）；B11/评测集/UI P1 等待办改为准确口径；v0.6.7 只留占位不预写版本行（v0.6.6 不对外、无 tag/Release）。
- `README.md`：西语产品数 25,293→25,395；ATC 47.5%/67.0%→**47.6%/67.4%**（6,021/12,649、5,702/8,459）；页面数改为按版本口径（最终 build 后回填精确页数）。
- `render_dashboard.py` + `docs/dashboard.template.html`：新增 `{{LATEST_VER}}` token（从 CHANGELOG 自动取最新版本）；看板队列/关键节点/下一步更新到 v0.6.x 口径。
- `reports/metrics/2026-10-29.json`、`docs/工作集群-架构与进度.html` + `docs/img/cluster-progress.png`：**等最终版发布、dist 稳定后跑一次**（发布/构建期间不读半成品 dist）。
- 队列新增 task-82~86 与保留项；TW 数据入库（非版本）记入「已完成」并标注 markets/languages 仍 disabled、测试 1 红为预期过渡态。
- 队列补 **v0.6.5 已完成行**（11 版，gh-pages e78d47f9f；reports/ui-lang-cleanup.md）；早报版本数 10→11。
- 队列补 **v0.6.7 已完成行**（12 版：含 v0.6.6 矩阵注、/warn 分页、增量发布 27.55 MiB/−93.4%/602s、smoke 32/32、gh-pages b650b30fb）；早报版本数 11→12。
- 队列补 **v0.7.0 已完成行**（13 版：TW 16,457、四语国家列表/chips/矩阵 TW 列、zh-Hant 全站、TFDA OGDL 署名；live v0.7.0/smoke 0 failures/tag/gh-pages 3ce2b035）；发布计划调整为 v0.7.1（ATC 类别）/v0.8.0（SG），最终预期 15 版。
- 队列补 **v0.7.1 已完成行**（14 版：1,154 ATC 类目页 + 16 大类 + 四语类名/搜索 + WHO ATC/DDD；smoke 32/32、gh-pages 29fab5ecd、61,547 文件 446.2 MB/sitemap 61,390/增量 13.85 MiB −96.9% 511s）。
- 队列补 **v0.8.0 已完成行**（15 版：HSA 5,511/全库 431,555、9 市场矩阵全显、HSA/SODL 署名；smoke 32/32、gh-pages fc7986d1a、62,878 文件 455.7 MB/sitemap 62,720/增量 17.94 MiB −96.1% 515s）。
- 队列补 **v0.8.1 已完成行**（16 版：双语对照 zh 536/es 640 + 来源徽章 + 显示原文开关；smoke 32/32、gh-pages 46a6bfd37、62,880 文件 463.7 MB/sitemap 62,720/增量 14.92 MiB −96.8% 519s）。
- README：8 市场 + 台湾行 + 页数（12,246 成分页 / 30,383 名字页，v0.7.0）+ products 426,044。
- v0.7.0 中间态已跑 `db/nightly_metrics.py --date 2026-10-29`（7 warnings 已解释）与 `render_dashboard.py`（HTML/PNG 更新：8 市场/TW/v0.7.0/索引 32.2 MB）；**v0.8.0 发布后按最终 dist 再跑一次**。
- v0.7.0 待发行内容已写入队列/早报：TW 市场 / 四语国家列表 / chips / TFDA OGDL v1.0 署名 / 矩阵 TW 列（含 zh-Hant 启用）；TW build 支持（task-81）已完成，等 data-depth 启用 markets/languages。
- 队列/早报已写入用户三项决定：HK 下一谷段名称/成分层（task-88）、CN 商品名不花钱（98.4%/缺口记档/无人工种子/低优先 CC0-CC-BY）、MO 链接层+申请信（task-89，获批前不入库）；均未写「已完成」。
- 已写入 PT/SG 决定：PT 降「备选/暂缓」（pt-PT 与 EMA/EU 层不优先，等 INFARMED 或澳门葡语字段）；SG 提前（排 HK 后、PT 前）；MO 申请保留；均未写「已完成」。
- 新增「等待回复（申请台账）」：上海医保局 政府信息公开申请（编号 SQMB2F30661120261029001，10-29 提交，药品挂网+医保支付目录全量字段，法定 ≈11-26，提醒 11-12/11-26）；同表列澳门 ISAF（11-09/11-18）、澳大利亚 TGA（11-03/11-10/11-24）；均未标完成。

---

## 8. 等待回复的申请（台账）

> 政府信息公开/数据申请，**均未答复、不标完成**；答复到达后更新队列台账并评估入库/链接层。

| 申请 | 编号 / 渠道 | 提交 | 内容 | 提醒 | 状态 |
|---|---|---|---|---|---|
| **上海市医疗保障局 政府信息公开申请** | 编号 **SQMB2F30661120261029001** | 2026-10-29 | 药品挂网/集中采购目录 + 医保支付范围药品目录全量数据（通用名/商品名/批准文号/剂型/规格/企业/挂网价/支付标准/执行日期；电子数据优先），并询问是否已有公开查询渠道 | 2026-11-12（10 工作日）、2026-11-26（20 工作日） | 等待回复（法定 20 个工作日 ≈ 2026-11-26） |
| 澳门 ISAF（药物事务厅） | — | — | 澳门药物事务厅信息/数据申请（链接层，获批前不入库） | 2026-11-09、2026-11-18 | 等待回复 |
| 澳大利亚 TGA（ARTG FOI） | docs/foi-artg-request.md | — | ARTG 全量/名称层 FOI 申请（非批量导出） | 2026-11-03、2026-11-10、2026-11-24 | 等待回复 |

## 9. 报告索引（本谷段）

`reports/warn-verify.md`、`link-target-fix.md`、`maker-pages.md`、`i18n-v055.md`、`ingredient-i18n.md`、`cross-market-apply-prep.md`、`ui-a1-b6-impl.md`、`combo-page-integration.md`、`index-legacy-impl.md`、`zh-hant-ui-impl.md`、`tw-country-migration.md`、`ui-u1-u3-impl.md`、`atc-glossary-impl.md`、`zh-hant-i18n-refresh2.md`、`release-notes-i18n-refresh3.md`、`tw-ingest-write.md`（TW 数据入库）、`matrix-layout-impl.md`、`warn-pagination-impl.md`、`publish-incremental.md`（v0.6.7）、`ui-lang-cleanup.md`（v0.6.5）、`atc-browse-impl.md`（v0.7.1）、`sg-market-enable.md` / `sg-market-build.md`（v0.8.0）、`display-fixes-impl.md`（v0.8.4）、`pseudo-combo-build.md`、`search0-analytics-impl.md`、`cat-i18n-fix.md`、`header-ui-fix.md`、`matrix-alignment-fix.md`；`metrics/2026-10-29.json`（**最终**）、`docs/工作集群-架构与进度.html` + `docs/img/cluster-progress.png`（**v0.8.4 最终快照**）。

---

*本报告由文档/早报子智能体维护；数据只读现查，发布/构建数字以最终版本 build 与发布经理确认回填。*
