# 2026-10-30 谷段早报（v0.9.0 大版本）

> 写作：2026-10-30 北京 01:1x（发布后回填）｜作者：dose-mapping（文档/审计）｜数字以 `data/drugs.db`、`site/dist` 与发布记录实测为准。
> 本报告对应 task-18（v0.9.0 发布）+ task-3（统一 DB 窗口）+ task-16/17（单位归一）+ task-1/6/9/19/20（展示批次）。

## 0. 结论

- **v0.9.0 = 本谷段唯一大版本（第 20 版）**：合并「重量单位归一 + ATC/大类 v2 + 矩阵按需 3 列/横滑 + 无商品名与全量厂家页 + HK 市场上线（10 个国家和地区）」；发布：**tag v0.9.0 + Release、gh-pages `cbc3f6aa`、main `989d9c38e`、smoke ok（failures: []、live v0.9.0）、增量 46.28 MiB（≈全量 6.3%）/ 1,118.5s（18m39s）**。
- **数据**：DB 窗口一次写完——products **444,194**（HK +13,935、CN 清洗 −1,296）、10 市场、components 554,959、names 620,004；DB 391,098,368 B（391.1 MB）；`quick_check=ok` / FK 0。**（以上为 v0.9.0 发布时点；发布后 AU ARTG 已入库，当前 DB 见 §2.1，两者不要混用）**
- **发布后（本报告写作时）AU ARTG 入库刚完成**：DB 现为 **477,098 产品 / 628,013 组件 / 652,909 名称 / 10 市场（AU 44,794）**、DB 419,627,008 B（419.6 MB）；**未随 v0.9.0 发布**（线上仍是发布时点数字）；README 已回填 477,098/AU 44,794，**线上 About 仍是 v0.9.0 构建时点 444,194** → task-28 在 v0.9.1 更新；许可仍待书面确认（见 §6）。
- **站点**：构建 `== done ==` exit 0、**2.92 分钟**；dist **116,883 文件 / 770.8 MB（735.0 MiB）**、HTML 116,717、sitemap **68,430**、0 空文件；单包装名字页本版生成 **44,040**（CN/TW/ES/MX 子集，noindex、不进 sitemap），**全量 102,192 留待 v0.9.1 及以后**。
- **测试**：发布后四套复跑全绿——etl **25 OK** / lib **29 OK** / mobile **29 OK**；trilingual **72 例 68 通过**（354 查询 Top-5 **97.7%**、Top-1 96.3%，与 2026-10-28 基线完全一致，4 例为既有 dup_inn/combo 缺口，非本次回归）；发布 smoke **ok**（failures: []、live v0.9.0）。
- **申请**：TGA 已答复（2026-10-29 数据包，审计 task-10 完成）但**许可 🔴 待确认/仅内部匹配**；上海（11-12/11-26）、澳门（11-09/11-18）继续等；定时任务仍为 **2 条 cron**（00:35 开工 / 08:20 收尾），申请跟进走每日开工日检。

---

## 1. 发布（v0.9.0）

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

### 2.1 发布后：AU ARTG 入库（当前 DB，2026-10-30 北京 01:0x）

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
- **发布/许可**：AU 数据**未随 v0.9.0 发布**（线上 dist 仍是发布时点 116,883 文件 / 770.8 MB）；计划随 **v0.9.1** 发布，**公开前需许可结论**（TGA 版权页要求书面许可；FOI≠版权许可）。README 已回填 477,098/AU 44,794；线上 About 仍 444,194（v0.9.1 重建 + task-28）。

**窗口内 6 步（实际值，详见 `reports/db-window-20261030.md`）**
1. **HK 入库**：13,935 产品 / 22,302 成分 / +9,197 name_key；token 映射 93.8%，丢弃 340；无规格/剂型/状态（页面明示）。
2. **CN inn_zh v2**：2,879 → **3,115**（+236），旧值修正 9 条。
3. **CN 清洗**：CN 146,347 → **145,051**（−1,296 产品）；form_base 1,214、异常规格 30→NULL、批文 1,331、近重复 14,507 只标 review。
4. **伪复方删盐**：214 产品 / 删 285 行 component（与 task-137 审计原值一致）。
5. **CN 商品名**：+229 product_name、+12 name_key、+13 name_variant。
6. **第二批单位**：数值 13,680 行（L→mL 961、per_volume g→mg 12,609、kg→mg 98、µL→mL 13）+ 文本 98,161 行；IU/U/vg/mEq 只做文本。

**单位归一（task-16 第一批，重量）**：109,161 行 g/mcg/µg/microgram/kg → **mg**（Decimal）；0.12 g 记录 275 行全部 → 120 mg（归零）；身份/名称/product_id sha256 全部不变；现测 `strength_unit`：mg **399,260**、NULL 101,148、% 26,098、mL 18,933、IU 3,280、unit 3,010、g 871（剩余 g/kg 全是 >100,000 mg 异常值，未猜）。

**质量**：`db/check_data.py` 前后 114 → 115 行（+1 = HK coverage 行）；`quick_check=ok`；`foreign_key_check=0`；`inn_zh` 非空 3,115。

## 3. 站点（v0.9.0 构建产物）

| 项 | 值 |
|---|---|
| dist 文件 / 体积 | **116,883 / 770.8 MB（735.0 MiB）**（旧 62,217 / 472.5 MB） |
| HTML / sitemap | HTML **116,717**；sitemap **68,430** |
| drug / name / combo / maker / atc / cat | 12,436 / **77,030**（单包装子集 44,040）/ 10,842 / **15,213** / 1,154 / 16 |
| core.json | 35.8 MB（legacy `index.json` 保持关闭） |
| 构建耗时 | **2.92 分钟**（旧 v0.8.4 约 6–8 分钟量级；新页多为轻量模板） |

**抽查**：orlistat 页 120 mg 合并行 + 「原记录：0.12 g」小字；矩阵默认 3 列 + 横向滑动 + 规格列 sticky；ARALEVO/RIDEXIN 单包装页 noindex + 底部文案 + 厂家链接；首页 HK、About HK 署名、矩阵 HK 列；四语 key 无缺。

## 4. 测试

**发布时点**：`verify_live.py` smoke **ok**（`failures: []`、live 版本 v0.9.0），首页/页脚/What's new/core/About/GoatCounter 全过。

**发布后复跑**（2026-10-30 北京 01:0x–01:1x，只读；日志 `.tmp/dose-mapping/tests-post-v090.log`，跑的是 **AU 入库后的当前库**）：

| 套件 | 结果 |
|---|---|
| `etl`（`unittest discover -s etl -t etl`） | **Ran 25 tests, OK** |
| `lib`（`unittest discover -s lib -t lib`） | **Ran 29 tests, OK** |
| `tests.test_mobile_inbox` | **Ran 29 tests, OK** |
| `tests/trilingual/run_tests.py` | **72 例 68 通过**；354 查询 **Top-5 97.7%**（346/354）、**Top-1 96.3%**（341/354）、跨国可见 72/72；耗时 728.3s |

- **与基线对比**（`.tmp/trilingual/results_overnight_20261029.json`，2026-10-28）：基线同为 **72 例 68 通过 / Top-5 97.7%**、Top-1 96.0%；失败例完全相同（metformin combo 的 zh「西格列汀二甲双胍片」Top-5、ciclosporin/beclometasone/chlorphenamine 三个 dup_inn 拼写别名，均属**既有缺口**）→ **本次 v0.9.0 + AU 入库未引入检索回归**；耗时 556.3s → 728.3s（库 +32,904 产品后正常变慢）。
- 说明：三语套件在 PowerShell 管道下会把 unittest 进度点写到 stderr（`NativeCommandError` 噪音），结果以 `OK`/汇总行为准（旧报告 `reports/2026-10-26-手机通道.md` §3 有同样说明）。

## 5. 未完成 / 下一步

| # | 项 | 说明 | 下一步 |
|---|---|---|---|
| 1 | **单包装商品名页全量 102,192** | 本版按 800MB 守卫只做 **44,040**（CN/TW/ES/MX）；全量预估 dist >800MB、发布 1–3h；1,055 个 key 无 component 行无法建页 | **v0.9.1**：先压模板体积/分批（`SINGLE_NAME_ALL=1` 开关已留） |
| 2 | **AU ARTG 入库** | **已完成（内部库，2026-10-30）**：+32,904 产品（34,606 ARTG ID 中 1,702 个已有产品只补字段）→ AU **44,794**、全库 **477,098**；Export Only 2,632、无成分 3,911（含 1,446 仅名称层）；DB 419.6 MB；碰撞 severe 23,753 | **随 v0.9.1 发布**（About 加 TGA/ARTG 署名 + 数据截止 2026-10-28；Export Only 徽章；无成分「成分未收录/名称层」；`unknown` 明示不代表在售）；**许可仍 🔴 待确认**（TGA 书面许可/仅内部使用，gate 在 Lead）；README/About 计数由 task-28 回填 |
| 3 | **EMA（EU region）** | 本轮未做（原 task-107/EMA 计划顺延） | 后续数据批评估 |
| 4 | **v0.9.1** | **AU ARTG 数据发布**（署名/Export Only/无成分展示 + README·About 计数 task-28）+ Lighthouse/CWV/WCAG + UI/UX 审计（含体验批余项 A4/B8/B9/B11/U4–U7，视窗口） | 下一谷段 |
| 5 | **v0.9.2** | 数据打包/CI（AU 已随 v0.9.1） | 下一谷段 |
| 6 | **v0.9.3** | 数据漂移告警/溯源 | 排期 |
| 7 | **task-5 / task-14** | 成分名四语一致性（1,791 个 inn_en 含中文）+ ATC/大类页「通用名（代表商品名）」 | v0.9.1/数据批；task-14 依赖 task-5 |
| 8 | 展示待核 | `mL/IU/mEq/mCi` 大写后 build `_RE_UNIT` 只匹配小写（失去 i18n span）；`≥10 万` flags 522 行 | build 放宽大小写 + 补 `unit.IU/mEq/mCi` 四语键 |
| 9 | 定时任务 | 只保留 **2 条 cron**（00:35 开工 / 08:20 收尾，Asia/Shanghai）；原 7 条 at 取消，申请跟进改每日开工核对 `docs/跟进提醒.md` | 由 Lead 的会话用 `schedule_list` 核对 |

## 6. 申请台账（本谷段变化）

| 申请 | 状态 |
|---|---|
| 上海医保局 **SQMB2F30661120261029001** | 等待回复；提醒 11-12（10 工作日）/ 11-26（20 工作日，法定答复期） |
| 澳门 ISAF | 等待回复；11-09 / 11-18 |
| 澳大利亚 TGA（ARTG） | **已答复 2026-10-29**（ARTG Medicines 2026-10-28 数据包）；审计 task-10 完成，**许可 🔴 待确认/仅内部匹配**；**数据已入库（内部库，AU 44,794 / 全库 477,098），未随 v0.9.0 发布**；11-03 核对/申请书面许可、11-10 补问截止，**11-24 已关闭** |

## 7. 证据

| 文件 | 内容 |
|---|---|
| `reports/db-window-20261030.md` | DB 窗口逐步 before/after、命令、回滚矩阵、差异说明 |
| `reports/unit-normalization.md` / `unit-normalization-display.md` | 重量归一（109,161 行）与矩阵合并/原记录 |
| `reports/category-v2-impl.md` / `matrix-columns-ondemand.md` / `maker-pages-all.md` / `no-trade-name-display.md` / `hk-market-enable.md` | v0.9.0 各主题实现与构建后抽查 |
| `.tmp/build-v090.log` | 构建输出（`== done ==`、2.92 分钟、dist 770.8 MB） |
| `reports/tga-artg-response-20261029.md` / `artg-20261028-audit.md` / `artg-20261030-ingest.md` | TGA 答复、许可结论与 AU 入库执行（+32,904 产品、DB 419.6 MB、回滚清单） |
| `reports/schedule-2cron-align-20261030.md` | 定时任务文档对齐（2 cron + 台账日检） |
| `data/backups/drugs-before-dbwindow-20261030.db` + 6 份撤销清单 | 窗口回滚点 |
