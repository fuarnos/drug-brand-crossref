# 2026-10-30 谷段早报（v0.9.0 大版本 + v0.9.1 数据/修复版）

> 写作：2026-10-30 北京 03:1x（v0.9.1 发布后回填）｜作者：dose-mapping（文档/审计）｜数字以 `data/drugs.db`、`site/dist` 与发布记录实测为准。
> 本报告对应 task-18（v0.9.0 发布）+ task-3（统一 DB 窗口）+ task-16/17（单位归一）+ task-1/6/9/19/20（v0.9.0 展示批次）+ task-22/28/29/32（v0.9.1 Lighthouse/AU 展示/UX/埋点）+ v0.9.1 发布。**本谷段共 2 版：v0.9.0（第 20 版）、v0.9.1（第 21 版）。**

## 0. 结论

- **v0.9.1 = 本谷段最后一版（第 21 版，数据 + 修复）**：AU 全量上线（+32,904 → 44,794）+ UX 审计 4 个 P0 与 WCAG/i18n P1 修复 + 搜索埋点修复 + Lighthouse 移动端四项 ≥90（LCP 3.1–3.6s 未达标）+ AU 多国名字页误杀修复 + 体积策略（combo 15,191→6,736）。发布：**tag v0.9.1（annotated `3e03f2a`）+ Release、gh-pages `de26b591`、main `e0f64430`、smoke 0 failures / 0 warnings（live v0.9.1）、增量 28.83 MiB（3.2%）/ 1,115.5s（18m35s）**。
- **v0.9.0（第 20 版）**：重量单位归一 + ATC/大类 v2 + 矩阵 3 列/横滑 + 无商品名与全量厂家页 + HK 上线（10 市场）；tag v0.9.0、gh-pages `cbc3f6aa`、main `989d9c38e`、smoke ok、增量 46.28 MiB/1,118.5s。
- **数据（当前 DB，v0.9.1 发布时点）**：**477,098 产品 / 628,013 组件 / 652,909 名称 / 10 市场（AU 44,794、HK 13,935）**、DB **419.6 MB**；`quick_check=ok` / FK 0。AU 数据**已随 v0.9.1 上线**（About 四语署名 + 数据截止 2026-10-28、Export Only 徽章、无成分标注；许可口径=只写来源+署名）。
- **站点（v0.9.1）**：构建 `== done ==` exit 0、**3.29 分钟**（含修复重发）；dist **112,822 文件 / 936.97 MB（893.6 MiB）**、sitemap **63,359**、0 空文件；name **77,058** / combo **6,736** / drug 12,442 / maker 15,213；单包装名字页仍 44,040；**全量 102,192 未做**（体积策略下视 v0.9.2 再评估）。
- **测试**：发布后四套复跑——etl **25 OK** / lib **29 OK** / mobile **29 OK**；trilingual **72 例 68 通过**（354 查询 Top-5 **97.7%**、Top-1 96.3%，与 2026-10-28 基线一致，4 例为既有 dup_inn/combo 缺口，非回归）；v0.9.1 smoke **0 failures / 0 warnings**（live v0.9.1）。
- **已知缺口**：v0.9.0 的 **6,065 个小组合页 URL 仍 404**（v0.9.2 task-33 stub）；**LCP 3.1–3.6s 未达 2.5s**（v0.9.2）；**core 41.4 MB raw 未瘦身**（v0.9.2 可选）；AU 数据带入的单位（microgram/mg/g 等）未归一。
- **申请**：TGA 已答复且 AU 数据已上线（许可口径=只写来源+署名）；上海（11-12/11-26）、澳门（11-09/11-18）继续等；定时仍为 **2 条 cron**（00:35 开工 / 08:20 收尾）+ 申请跟进每日开工日检。

---

## 1. 发布（v0.9.0 + v0.9.1）

### 1.1 v0.9.0（第 20 版）

| 项 | 实测 |
|---|---|
| 版本 / 日期 | **v0.9.0** / 2026-10-30（CHANGELOG 第一节；本谷段/本轮第 **20** 版） |
| main commit | `989d9c38e` |
| gh-pages commit | `cbc3f6aa6fcb4b0d533e81f009713d1f9c63764f` |
| tag / Release | **tag v0.9.0 + GitHub Release**（https://github.com/fuarnos/drug-brand-crossref/releases/tag/v0.9.0） |
| smoke | **ok**（`failures: []`、live 版本 v0.9.0） |
| 构建 | `site/build.py` exit 0，**2.92 分钟**（`.tmp/build-v090.log`） |
| dist（发布时点） | **116,883 文件 / 770.8 MB（735.0 MiB）**；HTML **116,717**；0 字节文件 **0** |
| sitemap | **68,430** URL（旧 62,057；noindex 页已排除） |
| 增量发布 | **46.28 MiB（≈全量 6.3%）/ 1,118.5s（18m39s）**；changed **116,897** 文件（+2,961,530 / −363,260 行） |
| 页脚 / What's new | v0.9.0（四语） |

**v0.9.0 用户可感知变化**（CHANGELOG 5 条）：重量单位归一与等价规格合并（0.12 g ≡ 120 mg，保留原写法）· ATC/大类 v2（四语类名 + 来源许可、减肥药补 GLP-1、感冒/过敏拆分、他汀去撤市、盐型归并 + 查看更多）· 矩阵按需 3 列 + 横向滑动 + 筛选加列 · 无商品名显示「无商品名」+ 全量厂家页 15,213（单产品页标注）· **HK 上线，10 个国家和地区、HK 13,935 产品**。

### 1.2 v0.9.1（第 21 版，数据 + 修复）

| 项 | 实测 |
|---|---|
| 版本 / 日期 | **v0.9.1** / 2026-10-30（CHANGELOG 第一节；本谷段第 **21** 版） |
| main commit | `e0f64430` |
| gh-pages commit | `de26b591` |
| tag / Release | **tag v0.9.1（annotated `3e03f2a`）+ GitHub Release**（https://github.com/fuarnos/drug-brand-crossref/releases/tag/v0.9.1） |
| smoke | **0 failures / 0 warnings**（live 版本 v0.9.1） |
| 构建 | `== done ==` exit 0，**3.29 分钟**（含 AU 多国名字页修复重发） |
| dist | **112,822 文件 / 936.97 MB（893.6 MiB）**；0 字节 **0** |
| sitemap | **63,359** URL（v0.9.0 为 68,430；combo 裁剪 −8,455、AU 多国 name 恢复 +2,622） |
| 页数 | drug **12,442** · name **77,058** · combo **6,736** · maker 15,213 |
| core.json | **41,381,256 B raw / 9,831,307 B gzip**（v0.9.0 为 35.8 MB raw / 8.68 MB gzip） |
| 增量发布 | **28.83 MiB（3.2%）/ 1,115.5s（18m35s）** |
| 页脚 / What's new | v0.9.1（四语） |

**v0.9.1 内容（CHANGELOG 5 条）**
1. **澳大利亚全量上线**：AU 11,890 → **44,794**（+32,904 TGA ARTG 2026-10-28）；页面/About 标注来源与数据日期；无状态列 → 「状态未确认」；Export Only 单独标注；无成分 → 「成分未收录（名称层）」不臆造。
2. **检索与移动端 UX 修复**：搜「泰诺」不再混入不同成分；计数口径统一；移动端首屏可见结果/零结果；矩阵筛选器可用、默认 3 列有说明；搜索框 label、对比度、触控目标等无障碍修复。
3. **搜索埋点修正**：只在**提交时**发送匿名事件，前缀合并，附 `lang` 与 `q_len`；About 隐私说明四语同步。
4. **Lighthouse 移动端基线**：性能 **90–95**、无障碍/最佳实践/SEO **100**；**LCP 3.1–3.6s 未达标**（v0.9.2）；首搜文案按实测更新（约 **1.05 MB raw / 0.16 MB gzip**）。
5. **体积策略**：combo 15,191 → **6,736**（只给 ≥2 产品或 ≥2 市场的组合建页）、AU-only name 页不建、AU 多国名字页恢复（**+2,622**）；总 dist **893.6 MiB ≤ 900 MiB**、十进制 <1e9 B。

> 证据：`lighthouse-optimization.md`、`lighthouse-baseline-20261030.md`、`ux-fixes-20261030.md`、`search-analytics-fix.md`、`artg-display-20261030.md`、`v091-size-strategy.md`、`v091-aufix.md`。

## 2. 数据变化（task-3 统一 DB 窗口 + task-16）

| 项 | 窗口前 | 现在 | 变化 |
|---|---:|---:|---:|
| products | 431,555 | **444,194** | +12,639（HK +13,935、CN −1,296） |
| product_component | 534,246 | **554,959** | +20,713 |
| product_name | 607,317 | **620,004** | +12,687 |
| name_key / name_variant | 168,943 / 184,766 | **178,152 / 198,142** | +9,209 / +13,376 |
| substance / variant | 12,649 / 14,249 | 12,649 / 14,249 | 0（身份不动） |
| source / coverage | 36 / 9 行 | **38 / 10 行** | +2（`hk_dh`、`beijing_ybj`）/ +HK |
| DB 体积 | 366,137,344 B | **391,098,368 B（391.1 MB / 373.0 MiB）** | +24.96 MB（+6.8%） |
| collision | severe 19,386 / warning 820 | **severe 20,666 / warning 837** | +1,280 / +17（HK 英文名归一） |

**10 市场产品数（发布时点 v0.9.0 build 时）**：CN 145,051 · US 110,179 · GB 61,051 · CA 43,847 · ES 25,395 · TW 16,457 · **HK 13,935** · AU 11,890 · MX 10,878 · SG 5,511。状态：active 377,730 / discontinued 38,424 / unknown 23,028 / withdrawn 5,012。

### 2.1 AU ARTG 入库（v0.9.0 发布后、v0.9.1 发布前；v0.9.1 起已上线）

> 来源：`reports/artg-20261030-ingest.md`（task-11 数据侧，Lead 批准；未跑 build/publish）。脚本 `etl/ingest_artg_medicines.py --keep-name-only`；备份 `data/backups/drugs-before-artg-20261030.db`（391,098,368 B，sha256 `64B10F28…`）+ 撤销清单 `.tmp/artg-ingest/artg_write_manifest.json`（4.8 MB）。

| 项 | 入库前（v0.9.0 发布时点） | 当前（AU 入库后） | 变化 |
|---|---:|---:|---:|
| products | 444,194 | **477,098** | +32,904 |
| product_component | 554,959 | **628,013** | +73,054 |
| product_name / name_key / name_variant | 620,004 / 178,152 / 198,142 | **652,909 / 202,092 / 229,794** | +32,905 / +23,940 / +31,652 |
| source | 38 | **39**（+`artg_export`） | +1 |
| AU products | 11,890 | **44,794**（+32,904） | 11,890→44,794 |
| DB 体积 | 391,098,368 B | **419,627,008 B（419.6 MB）** | +28.5 MB（VACUUM 后） |
| collision severe | 20,666 | **23,753** | +3,087（新名归一，预期） |

- 口径：`status='unknown'` **32,904/32,904**（导出无状态列，**不推断在售**）；**Export Only 2,632**（新增 2,278 + 既有 354，note 标「僅供出口」）；**无成分产品 2,416 → 3,911**（+1,495 = 1,446 仅名称层 + 49 成分全部无法解析；US 2,229 / AU 1,495 / MX 121 / SG 66）；补字段 route +144、pack +482；apply 10.4s / VACUUM 6.4s。
- **单位未归一（v0.9.1 数据跟进）**：新数据带入 `microgram` 6,102、`mg/g` 9,771、`mg/mL` 4,402 等写法（现测 `strength_unit` 取值 155），下一版数据批再归一。
- **发布/许可**：AU 数据**已随 v0.9.1 上线**（About 四语 TGA/ARTG 署名 + 数据截止 2026-10-28、Export Only 徽章、无成分「成分未收录」、README/About 计数 477,098 / AU 44,794）；**许可口径=只写来源+署名，不写「授权」措辞**（Lead 2026-10-29 决定；TGA 版权页仍要求书面再发布许可，若未来收到要求再评估）。
- **v0.9.2 数据跟进**：AU 带入的单位未归一（`microgram` 6,102 / `mg/g` 9,771 / `mg/mL` 4,402 等，`strength_unit` 取值 155），随下一数据批处理。

**窗口内 6 步（实际值，详见 `reports/db-window-20261030.md`）**
1. **HK 入库**：13,935 产品 / 22,302 成分 / +9,197 name_key；token 映射 93.8%，丢弃 340；无规格/剂型/状态（页面明示）。
2. **CN inn_zh v2**：2,879 → **3,115**（+236），旧值修正 9 条。
3. **CN 清洗**：CN 146,347 → **145,051**（−1,296 产品）；form_base 1,214、异常规格 30→NULL、批文 1,331、近重复 14,507 只标 review。
4. **伪复方删盐**：214 产品 / 删 285 行 component（与 task-137 审计原值一致）。
5. **CN 商品名**：+229 product_name、+12 name_key、+13 name_variant。
6. **第二批单位**：数值 13,680 行（L→mL 961、per_volume g→mg 12,609、kg→mg 98、µL→mL 13）+ 文本 98,161 行；IU/U/vg/mEq 只做文本。

**单位归一（task-16 第一批，重量）**：109,161 行 g/mcg/µg/microgram/kg → **mg**（Decimal）；0.12 g 记录 275 行全部 → 120 mg（归零）；身份/名称/product_id sha256 全部不变；现测 `strength_unit`：mg **399,260**、NULL 101,148、% 26,098、mL 18,933、IU 3,280、unit 3,010、g 871（剩余 g/kg 全是 >100,000 mg 异常值，未猜）。

**质量**：`db/check_data.py` 前后 114 → 115 行（+1 = HK coverage 行）；`quick_check=ok`；`foreign_key_check=0`；`inn_zh` 非空 3,115。

## 3. 站点（v0.9.1 构建产物）

| 项 | 值 |
|---|---|
| dist 文件 / 体积 | **112,822 / 936.97 MB（893.6 MiB）**（v0.9.0：116,883 / 770.8 MB） |
| sitemap | **63,359**（v0.9.0：68,430） |
| drug / name / combo / maker | 12,442 / **77,058** / **6,736** / 15,213 |
| core.json | **41,381,256 B raw / 9,831,307 B gzip**（v0.9.0：35.8 MB raw / 8.68 MB gzip；未瘦身） |
| 构建耗时 | **3.29 分钟**（含 AU 多国名字页修复重发；v0.9.0 为 2.92 分钟） |
| 0 字节文件 | **0** |

> 体积策略：combo 15,191 → **6,736**（只给 ≥2 产品或 ≥2 市场的组合建页，−8,455 页 / 约 −36.7 MB）、AU-only name 页不建（−7,405 页 / −30.9 MB）、AU 多国 name 页恢复 **+2,622**；从测试构建 980.9 MiB 压到 **893.6 MiB（≤900 MiB、十进制 <1e9 B）**。代价：**v0.9.0 的 6,065 个小组合 URL 仍 404**（v0.9.2 task-33 补 stub）。

**抽查**：泰诺不再混入不同成分（同成分/含相同成分之一分区块）；无商品名行显示「命中名」、组头改「N 条记录」；移动端首屏可见「3 个名字命中」/零结果；矩阵摘要「市场 3/10」、筛选器可用、恢复默认可点；AU 页（Lipitor/Abilify 等）已恢复、Export Only 徽章、无成分「成分未收录」；About 四语 TGA/ARTG 署名 + 数据截止 2026-10-28；四语 key 无缺。

## 4. 测试

**发布时点**
- v0.9.0：`verify_live.py` smoke **ok**（`failures: []`、live v0.9.0）。
- v0.9.1：`verify_live.py` smoke **0 failures / 0 warnings**（live v0.9.1）；发布前四套测试由发布经理执行。

**发布后复跑**（只读，`AU 入库后的当前库`）：

| 套件 | v0.9.0 后（`.tmp/dose-mapping/tests-post-v090.log`） | v0.9.1 后（`.tmp/dose-mapping/tests-post-v091.log`） |
|---|---|---|
| `etl` | Ran 25 tests, **OK** | Ran 25 tests, **OK** |
| `lib` | Ran 29 tests, **OK** | Ran 29 tests, **OK** |
| `tests.test_mobile_inbox` | Ran 29 tests, **OK** | Ran 29 tests, **OK** |
| `tests/trilingual/run_tests.py` | 72 例 **68 通过**；Top-5 **97.7%**、Top-1 96.3%、跨国 72/72；728.3s | 72 例 **68 通过**；Top-5 **97.7%**、Top-1 96.3%、跨国 72/72；642.6s |

- **与基线对比**（`.tmp/trilingual/results_overnight_20261029.json`，2026-10-28）：基线同为 **72 例 68 通过 / Top-5 97.7%**、Top-1 96.0%；失败例完全相同（metformin combo 的 zh「西格列汀二甲双胍片」Top-5、ciclosporin/beclometasone/chlorphenamine 三个 dup_inn 拼写别名，均属**既有缺口**）→ v0.9.0/v0.9.1 均**未引入检索回归**；耗时 556.3s → 728s 量级（库 +32,904 产品后正常变慢）。
- 说明：三语套件在 PowerShell 管道下会把 unittest 进度点写到 stderr（`NativeCommandError` 噪音），结果以 `OK`/汇总行为准（`reports/2026-10-26-手机通道.md` §3 有同样说明）。

## 5. 未完成 / 下一步（v0.9.2 清单）

| # | 项 | 说明 | 归属 |
|---|---|---|---|
| 1 | **旧组合页 URL 兼容** | v0.9.0 的 **6,065 个小组合页**在 v0.9.1 被体积策略裁掉，URL 仍 **404**（内部链接已一致，无站内 404） | **task-33（v0.9.2）**：生成 noindex stub（≤2KB/页，约 8–12MB），sitemap 不增，总体积仍 ≤900MiB |
| 2 | **LCP 3.1–3.6s → <2.5s** | 移动端 Lighthouse 本地节流；Performance 已 ≥90（首页 90 / 成分页 93 / 名字页 94 / ATC 95），LCP 未达标 | v0.9.2：拆 i18n/app（首屏只加载 UI 文案）、关键 CSS、`content-visibility`、更细分片、首页 LCP 文本分析 |
| 3 | **core.json 瘦身** | 41.38 MB raw / 9.83 MB gzip（v0.9.0 为 35.8/8.68）；未执行 ≤30MB 目标 | v0.9.2 可选：列式/字典编码再压、去重字段或按需分片；护栏已改 **gzip 2.5–12MB / raw 11–50MB** |
| 4 | **数据打包 / CI** | datapackage + 字段字典 + dataset.jsonld + checksums；最小 CI（测试/完整性/产物） | task-23 / task-24（v0.9.2） |
| 5 | **漂移告警 / 溯源** | `etl/drift_check.py` + 基线；LICENSE/CONTRIBUTING/CITATION + provenance 字段 | task-25 / task-26（v0.9.2/v0.9.3） |
| 6 | **task-5 / task-14** | 成分名四语一致性（1,791 个 inn_en 含中文）+ ATC/大类页「通用名（代表商品名）」 | task-14 依赖 task-5；v0.9.2 数据批 |
| 7 | **AU 单位归一** | AU 带入 `microgram` 6,102 / `mg/g` 9,771 / `mg/mL` 4,402 等（`strength_unit` 155 值） | v0.9.2 数据跟进 |
| 8 | **EMA（EU region）** | 本轮未做 | 后续数据批评估 |
| 9 | **全量单包装名字页 102,192** | v0.9.0 只做 44,040 子集；v0.9.1 体积策略下未扩 | 视 900MiB 体积预算再评估（可分批 CN/TW 优先） |
| 10 | **UX 审计余项** | 404 搜索框、零结果三项动作、结果页分页/折叠、触控目标全量 44px、移动表头真实屏幕阅读器验证 | v0.9.2（UX audit §5） |
| 11 | **展示待核** | `mL/IU/mEq/mCi` 大写后 build `_RE_UNIT` 只匹配小写（失去 i18n span）；`≥10 万` flags 522 行 | build 放宽大小写 + 补 `unit.IU/mEq/mCi` 四语键 |
| 12 | **定时任务** | 只保留 **2 条 cron**（00:35 开工 / 08:20 收尾，Asia/Shanghai）；原 7 条 at 取消，申请跟进每日开工核对 `docs/跟进提醒.md` | 由 Lead 的会话用 `schedule_list` 核对 |

## 6. 申请台账（本谷段变化）

| 申请 | 状态 |
|---|---|
| 上海医保局 **SQMB2F30661120261029001** | 等待回复；提醒 11-12（10 工作日）/ 11-26（20 工作日，法定答复期） |
| 澳门 ISAF | 等待回复；11-09 / 11-18 |
| 澳大利亚 TGA（ARTG） | **已答复 2026-10-29**（ARTG Medicines 2026-10-28 数据包）；审计 task-10 完成；**AU 数据已随 v0.9.1 上线**（AU 44,794 / 全库 477,098，About 四语署名 + 数据截止 2026-10-28、Export Only 徽章、无成分标注）；**许可口径=只写来源+署名、不写「授权」**（Lead 2026-10-29 决定）；11-03 核对、11-10 补问截止（如需），**11-24 已关闭** |

## 7. 证据

| 文件 | 内容 |
|---|---|
| `reports/db-window-20261030.md` | DB 窗口逐步 before/after、命令、回滚矩阵、差异说明 |
| `reports/unit-normalization.md` / `unit-normalization-display.md` | 重量归一（109,161 行）与矩阵合并/原记录 |
| `reports/category-v2-impl.md` / `matrix-columns-ondemand.md` / `maker-pages-all.md` / `no-trade-name-display.md` / `hk-market-enable.md` | v0.9.0 各主题实现与构建后抽查 |
| `reports/lighthouse-optimization.md` / `lighthouse-baseline-20261030.md` | v0.9.1 Lighthouse/CWV/WCAG 基线与优化（四项 ≥90；LCP 未达标） |
| `reports/ux-fixes-20261030.md` / `search-analytics-fix.md` / `artg-display-20261030.md` | v0.9.1 UX P0/WCAG/i18n 修复、搜索埋点修复、AU 展示（署名/Export Only/无成分） |
| `reports/v091-size-strategy.md` / `v091-aufix.md` | v0.9.1 体积策略（combo 裁剪、AU-only 不建页）与 AU 多国名字页误杀修复（+2,622） |
| `.tmp/build-v090.log` / `.tmp/build-v091.log` / `.tmp/build-v091-aufix.log` | 构建输出（`== done ==`、耗时、文件数；v0.9.1 修复重发在 `-aufix`） |
| `reports/tga-artg-response-20261029.md` / `artg-20261028-audit.md` / `artg-20261030-ingest.md` | TGA 答复、许可结论与 AU 入库执行（+32,904 产品、DB 419.6 MB、回滚清单） |
| `reports/schedule-2cron-align-20261030.md` | 定时任务文档对齐（2 cron + 台账日检） |
| `data/backups/drugs-before-dbwindow-20261030.db` + 6 份撤销清单 | 窗口回滚点 |
