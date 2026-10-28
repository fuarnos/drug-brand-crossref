# 术语基准表 + AI 译文自动校验（WHO / 药典来源核实与实现）

> 日期：2026-10-28 ｜ 任务：`task-83` ｜ 站点版本：v0.6.4 工作区（build.py 328 键 ×4 语言）
> 交付：`data/terminology_glossary.csv`（135 行）+ `etl/check_translations.py`（只读校验器）+ 本报告。
> 边界：**只写 data / etl / reports / .tmp**；未改 `site/build.py`、未写 `data/drugs.db`、未 git / 未发布。

---

## 0. 结论

1. **WHO 没有官方中文 INN 名**：WHO 公开电子版的 INN 名只有 **Latin / English / French / Spanish** 四种写法；
   WHO 网站/IRIS 上没有任何中文版 INN list（本轮再次核实入口与最新 PL135，见 §1）。
   中文通用名是中国 **CADN（China Approved Drug Name，国家药典委员会备案）**，属于「国家命名」而非 WHO 译文；
   台湾用《中華藥典》（食藥署）、香港用衞生署藥物辦公室清单中的官方中英文名。
   → 本站中文/繁体中文术语是**参考译名/自建基准**，不冒充 WHO 或药监官方译文（报告与基准表均标注）。
2. **可用来源与许可分级**：WHO INN / stem book = CC BY-NC-SA 3.0 IGO（署名 + 非商业 + 相同方式共享）；
   WHOCC ATC/DDD = © WHOCC（引用须注明、禁止商业复制与改动）→ 只存事实/码值；
   中国药典委/CADN、台湾中華藥典、香港衞生署 = 政府公开信息/付费出版物 → **仅事实 + 链接，不整表复制**。
3. **术语基准表已建立**：`data/terminology_glossary.csv` **135 行 / 10 个域 / 8 个来源**，每行带
   `source_id / source_url / source_license / confidence / severity / do_not_weaken`，可复核、可再生成。
4. **自动校验已跑通**：扫描 4 语言 i18n 328 键、What's new 24 个版本 95 条 AI 译文、es UI 缺口表 39 行，
   共 **38 条 findings（2 critical / 36 warning）**。2 条 critical 是真问题（占位符被改写、安全用语被弱化），
   已列入 §5 修正建议；校验器支持 `--strict` 作为发布前护栏（有 critical 退出码 1）。

---

## 1. WHO / ATC-DDD / 中文基准来源核实（2026-10-28）

| # | 来源 | 链接 | 访问结果 | 名称/语言 | 许可与可再发布结论 |
|---|---|---|---|---|---|
| 1 | **WHO INN Lists** | https://www.who.int/teams/health-product-and-policy-standards/inn/inn-lists | HTTP 200 | 官方 INN 列表入口；每个列表一份 PDF | WHO 出版物：**CC BY-NC-SA 3.0 IGO**（IRIS `dc.rights`；2026-10-26 抽样核验）。可引用/派生，须署名 + 非商业 + SA，不得暗示 WHO 背书 |
| 2 | **WHO INN Proposed List 135** | https://www.who.int/publications/m/item/inn-pl-135 | HTTP 200（2026-07-19） | PDF 内名称 **Latin / English / French / Spanish**；**无中文名**（PL135 版式；与 `reports/who-inn-20261026.md` §0 一致） | 同上 |
| 3 | **WHO INN stem book 2024** | https://www.who.int/publications/b/75124 | HTTP 200 | 英文；词干（-olol/-pril/-sartan…）与类别 | 同 WHO 出版物许可 |
| 4 | **WHOCC ATC/DDD Index** | https://atcddd.fhi.no/atc_ddd_index_and_guidelines/atc_ddd_index/ | HTTP 200 | 英文；在线可检索，完整 Index+DDD 需注册/订购 | ❌ 不可整表再发布：© WHOCC，见下 |
| 5 | **WHOCC Copyright/Disclaimer** | https://atcddd.fhi.no/copyright_disclaimer/ | HTTP 200 | 原文要点：「Use of all or parts of the material requires reference to the WHOCC. Copying and distribution for commercial purposes is not allowed. Changing or manipulating the material is not allowed.」 | 只可用**事实/码值**并注明 WHOCC；本站 ATC 码来自 Wikidata P267（CC0），不复制 ATC 表 |
| 6 | **中国药品通用名称命名原则（CADN）** | https://ypjg.ln.gov.cn/ypjg/ztzl/ypyfcxxxfw/zcfgzq/flfg/2026071923334752646/index.shtml | HTTP 200（药监局转发全文） | 中文；明确「中文通用名由药典委员会备案、英文名依据 INN」——**中文名是国家命名，不是 WHO 译文** | 政府公开信息，未标注开放许可 → 仅事实/参考 + 链接；不复制全文 |
| 7 | **中国药典委员会（原页面）** | https://www.chp.org.cn/ydw/upload/sites/chp/newscenter/news/attachments/000033.html | fetch 失败（网络层 TypeError；内容已由 #6 官方转发全文覆盖） | — | 同上 |
| 8 | **中華藥典第九版（台湾）** | https://gpi.culture.tw/books/1011001667 | HTTP 200 | 繁体中文；2021/12 出版，食藥署，5236 頁 / 3,004 品目 / 中英文索引（ISBN 9789865469498） | © 食藥署（付費出版品，著作財產權人食藥署）→ 仅事实/参考 + 链接；不可批量复制 |
| 9 | **香港衞生署藥物辦公室** | https://www.drugoffice.gov.hk/eps/do/en/consumer/reg_pharm_products/index.html | HTTP 200 | 繁体/英文；註冊藥劑製品清單、藥物資料庫、Compendium | 香港政府网站；仅事实 + 链接（再发布前按香港政府版权条款复核） |

> **「WHO 有无官方中文 INN 名」结论：没有。** 证据链：WHO INN 官方列表 PDF 内名称为 Latin/EN/FR/ES；
> WHO 全站/IRIS 无中文 INN list（2026-10-26 检索 + 本轮入口复核）；中文通用名的官方来源是中国 CADN/药典委。
> 因此本站中文名一律标注「参考译名，非官方译文」；术语基准表中亦不写 `official Chinese INN`。

**许可对本站的含义**（与 `docs/许可清单.md` 一致）：
- `data/terminology_glossary.csv` 作为**内部校验基准**，不是公开发布的官方词典；
  其中 WHO 派生行（INN/stem）只保留短事实（词干字符串、类别名/项目参考译名），不复制 WHO 正文；
- 若未来把本表作为数据产品对外发布：WHO 派生部分需 **CC BY-NC-SA 3.0 IGO**（署名+非商业+同许可），
  ATC 相关只可引用码值与 WHOCC 引用声明，中文/台湾/香港列只可保留事实字段并链接来源；
- 站点目前非商业、无广告——与 WHO NC 条款相容；商业化前必须重评（已在许可清单标注）。

---

## 2. `data/terminology_glossary.csv`（基准表）

- **规模**：135 行 / **130 个唯一 en 术语**（同名词条 checker 合并：安全项优先）；10 个域：
  `abbreviation 13 / regulatory 23 / safety 11 / status 4 / dosage_form 20 / unit 8 / country_org 12 /
  naming_stem 26 / inn_name 11 / atc_ddd 4 / identifier 3`。
- **来源分布**：project 59、chp_naming 42、who_stem 26、whocc_atc 3、who_inn 2、tw_pharmacopoeia 2、
  hk_drugoffice 1（wikidata 0——ATC 码本身已在 DB/索引，不重复收录）。每行 `source_url + source_license + confidence` 齐全。
- **列**：`term_id, domain, term_en, term_es, term_zh, term_zh_hant, zh_variants, zh_hant_variants,
  es_variants, en_definition, do_not_weaken, severity, naming_stem, source_id, source_url,
  source_license, confidence, notes`。
- **可信度分层**：`official`（WHO/WHOCC/药典/食藥署/衞生署事实）、`project`（自建参考译名，已与站点
  `I18N`/`GLOSSARY_I18N`/zh-Hant 字典交叉核对）、`reference`（药典中文剂型名等参考译法）。
- **安全项（critical）**：`not interchangeable`、`do not substitute`、`contraindicated`、`adverse reaction`、
  `drug interaction`、`overdose` 6 条 `do_not_weaken=1`；`warning/risk/pregnancy/lactation` 为一般 warning 级
  （避免把普通 "warning" 一词的所有上下文误判 critical）。
- **可复现**：生成脚本 `.tmp/terminology/build_glossary.py`（读取 build.py 的 `GLOSSARY_I18N` 保持术语表四语一致；
  变体表 `EXTRA_VARIANTS` 收录站点真实译法，减少误报）。后续如需入库版本控制，可把生成脚本移入 `etl/`。

---

## 3. `etl/check_translations.py`（自动校验）

只读脚本，标准库实现，不联网、不写 DB、不改译文。

```powershell
& $py etl/check_translations.py                     # 默认：全规则，退出码 0
& $py etl/check_translations.py --strict            # 发布护栏：有 critical → 退出码 1
& $py etl/check_translations.py --json              # 机器可读摘要
& $py etl/check_translations.py --i18n site/build.py  # 直接分析源码字典（不依赖 dist）
& $py etl/check_translations.py --checks term,safety  # 只跑部分规则
```

| 规则 | 检查内容 | 默认严重度 |
|---|---|---|
| `term` | en 文本命中基准术语时，es/zh/zh-Hant 必须含对应译名（四语 + 变体；同名词条合并） | warning |
| `number` | en 的数字 token 必须在目标语言出现；支持 146,344→14.6 万 / 146k 本地化近似（±5%）、1–10 中文数字 | warning |
| `unit` | mg / ml / IU / % / mEq 等剂量单位必须在目标语言出现（允许 毫克/毫升/国际单位 等写法） | warning |
| `placeholder` | `@@X@@`、`{name}` 占位符集合必须完全一致 | **critical** |
| `html` | HTML 标签序列一致（防止译文吃掉 `<b>/<a>` 结构） | warning |
| `safety` | 6 条硬安全用语不得缺失/弱化为「提示/参考/注意」类词 | **critical** |
| `zh_hant` | 繁体字典缺键（回退简体）、与简体完全相同且含明确简体字（保守集合） | warning |

**输入（自动选择，可显式指定）**：
`site/dist/assets/i18n.js`（构建产物，优先）或 `site/build.py`（AST 解析 I18N + 6 个静态字典 + `GLOSSARY_I18N`）；
`data/i18n_zh_hant.json`（328 键，用于繁体缺失/残留）；`data/release_notes_i18n.json`（24 版本 × 95 条 AI 译文，
检查 zh→en/es 的数字/占位符/HTML 保留）；`data/es_ui_missing.csv`（39 条 en_text→es_suggested 建议）。

**输出**：`.tmp/terminology/translation_check.json`（摘要+findings）、`translation_findings.csv`（逐条），
stdout 摘要（规则/严重度/语言分布 + 样例）。

---

## 4. 本轮校验结果（v0.6.4 工作区，2026-10-28）

| 指标 | 值 |
|---|---|
| i18n 字典 | 4 语言 × **328 键**（en/es/zh/zh-Hant；zh-Hant 328/328，0 缺键） |
| 扫描数据 | i18n 4×328 + release notes 24 版本/95 条 + es_ui_missing 39 行 |
| findings | **38**（critical **2** / warning 36） |
| 按规则 | term 24、html 12、safety 1、placeholder 1 |
| 按语言 | es 21、zh 7、zh-Hant 8、en 2（release notes 的 en 目标） |
| 术语命中覆盖 | en 文本命中基准术语 113 次：abbreviation 49、regulatory 31、safety 12、country_org 7、dosage_form 6、status 5、inn_name 2、identifier 1 |
| 繁体字典 | 328/328 键；与简体完全相同且含可靠简体字 = **0**（无残留转化遗漏） |

**2 条 critical（真实问题，建议改）**：
1. `es_ui_missing.csv` 的 `page.title.template`：en 模板含 `{title}`，es 建议写成 `{título localizado}`
   → **占位符被改写**，若直接采用会插入失败/字面量。改用 `{title}` 或在生成侧重命名占位符。
2. `combo.cross_overlap` 的 es 译文：en `not interchangeable` 的 es 句子里没有
   `no son intercambiables / no intercambiables` 等强译 → **安全用语可能被弱化**，需人工确认并补强。

**36 条 warning（择要）**：
- **HTML 结构 12 条**（zh/zh-Hant/es）：`about.nick`、`about.terms`、`about.samename` 等译文丢了
  `<i>/<b>/<code>` 标签（en 有 4 个 `<i>`，zh 只有 `<code>` 等）→ 译文丢失强调/代码样式，建议按源 HTML 补齐。
- **术语不一致 24 条**（多为「基准表述 vs 站点实际译法」差异，不一定错，需人工确认）：
  `Strength`→es `Concentración` 缺失（about.sources/gaps 等 5 处）；`tall-man lettering`、`look-alike, sound-alike`、
  `fixed-dose combination`、`ATC code`、`ARTG number`、`tablet`、`unknown` 等少数键；`semaglutide`/`tirzepatide`
  的 es 名未在对应译文出现（可能是译文省略药名，建议保留 INN）。
- 数字规则未发现真问题（146,344→14.6 万 已按本地化近似通过；3→三 按中文数字通过）。

> 说明：术语检查以**基准表**为参照，站点文案可能有合理同义写法；已用 `EXTRA_VARIANTS` 收敛常见差异，
> 剩余 warning 应逐条人工判断「改译文」还是「补基准变体」，**校验器不自动改文案**。

---

## 5. 建议修正项（按优先级）

| 优先级 | 位置 | 问题 | 建议 |
|---|---|---|---|
| P0 | `data/es_ui_missing.csv` `page.title.template` | 占位符 `{title}` → `{título localizado}` | 保留 `{title}`（或同步改生成代码占位符） |
| P0 | i18n `combo.cross_overlap`（es） | 安全用语 `not interchangeable` 未被强译 | 补 `no son intercambiables`；若语义确为「部分重叠」需改写为不弱化的表述 |
| P1 | i18n `about.nick` / `about.terms` / `about.samename`（zh、zh-Hant、es） | 译文丢失 `<i>/<b>/<code>` 标签 | 按 en 源标签补齐（或改 `data-i18n-html` 渲染方式） |
| P1 | about.* 若干键 | `Strength` 等术语未按基准译名 | 统一为 规格/Concentración/規格；或在基准表加变体 |
| P2 | INN 名（semaglutide/tirzepatide 等） | es 译文偶尔省略药名 | 保留 INN 名，便于检索与核对 |

> 本轮**不修改** `site/build.py`（不在写范围）与任何译文；以上修正留给 build.py/文案 owner。

---

## 6. 后续「无需人工盯」的流程

1. 新增/修改界面文案 → 先跑 `python etl/check_translations.py --strict`；0 critical 才进入 build。
2. 每次 build 后（或发布前）再跑一次（默认读 dist i18n.js，能覆盖最终运行时字典）。
3. 新增术语/剂型/警示语 → 追加到 `data/terminology_glossary.csv`（或生成脚本的列表），
   并补变体；**新词条必须有来源 + 许可 + 置信度**（WHO 派生注意 CC BY-NC-SA、ATC 只事实、中文参考非官方）。
4. 繁体字典更新 → 用 `.tmp/zh-hant2/build_hant_refresh.py` 流水线刷新 `data/i18n_zh_hant.json` 后重跑校验
   （`zh_hant` 规则会报缺键/残留）。
5. 发布前用 `--strict` 作为护栏；把输出 JSON 附到 release 记录（或 CI 若未来有）——当前无 CI，本地即为门槛。

---

## 7. 已知限制与风险

1. **基准表中文不是官方译文**：中文列=参考译名（对照 CADN/药典命名原则、台湾药典/食藥署、香港衞生署用词），
   不能对外宣称官方；正式对外发布需逐条人工复核（尤其 INN 中文名）。
2. **WHO 许可 share-alike**：若把本表公开为数据产品，WHO 派生部分需 CC BY-NC-SA 3.0 IGO；当前定位内部基准。
3. **术语匹配是字面命中**：同义改写、语序变化、缩写展开会漏报/误报；已用 `EXTRA_VARIANTS` + 同名词条合并降低噪声，
   但 24 条 term warning 仍需人工判定。
4. **数字检查只做「存在性」**：不验证四舍五入/换算正确性（如 14.6 万 ≈146,344 通过，但无法证明全部）；
   单位本地化写法列表可继续扩。
5. **繁体残留检测用保守字集**：宁漏不误；若字典整段复制简体，可能报缺键但未必逐字报残留。
6. **来源页面可能变化**：WHOCC/药典页面数据与许可条款按访问日记录（2026-10-28）；WHO INN 已按 IRIS 元数据核验，
   后续接入前需复核。中国药典委原页面本轮 fetch 失败（内容由药监局转发全文覆盖）。

---

## 8. 产物与证据

| 路径 | 内容 |
|---|---|
| `data/terminology_glossary.csv` | 术语基准表（135 行，UTF-8 BOM，Excel 可开） |
| `etl/check_translations.py` | 自动校验器（7 规则，`--strict` 发布护栏） |
| `reports/terminology-accuracy.md` | 本报告 |
| `.tmp/terminology/translation_check.json` | 校验摘要 + findings（38 条） |
| `.tmp/terminology/translation_findings.csv` | findings 明细 |
| `.tmp/terminology/web_verify.json` | WHO/WHOCC/药典/台湾/香港核实记录（HTTP/许可/结论） |
| `.tmp/terminology/build_glossary.py` | 基准表生成脚本（GLOSSARY_I18N 对齐 + 变体表） |
| `.tmp/terminology/README.md` | 证据索引 |
| `reports/who-inn-20261026.md`、`docs/许可清单.md` | 既有 WHO INN 语言/许可结论（本轮引用并复核入口） |
