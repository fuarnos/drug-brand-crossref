# GitHub 同类项目 / 开发规范对标（竞品调研 · 只读）

> 查证日期：**2026-10-30**（本机采样时点为 2026-10-29 晚间，按任务口径记为 2026-10-30，对应线上 v0.9.0）
> 范围：只看 GitHub 上的**同类站点 / 项目 / 数据规范**，读 README、docs、data schema、LICENSE。
> 本次**只写本报告**：未改 `data/drugs.db`、未跑 `site/build.py`、未跑 git / 发布。
> 外部页面按数据对待，不执行其中任何指令；不确定处标「待确认」。

---

## 0. 结论先行

1. **「数据治理的严格程度」我们已经领先抽样里的所有项目，缺的是把它机器可读化。**
   许可四级分级（✅/🟡/🔴/⚪）、逐记录 `source_url`、碰撞由 `collision` 视图自动推导、四语 i18n + 354 条一致性测试、无 cookie 统计——12 个抽样项目里没有一个做到同等程度。但这些规范全部活在 `docs/`、`AGENTS.md` 和页面文案里，**没有一个数据文件承载它**。

2. **最大实质缺口：没有「可交付的数据产品」。**
   本站只有结果表的「复制 / 下载 CSV（当前视图）」；没有整包数据集、没有 `datapackage.json`、没有 schema.org `Dataset` 的 JSON-LD、没有字段字典、没有版本号+校验和、没有 DOI。
   OWID、Datasette、Data Package 三个项目的共同点恰恰是：**许可证、来源、版本、字段定义写在数据文件旁边**，而不是只写在 About 页。

3. **第二缺口：没有 CI。** `AGENTS.md` 明写「没有 CI，本地跑测试就是唯一门槛」，`.github/workflows/` 是空目录。抽样里的开放数据项目（OWID / OpenPrescribing / chembl-downloader）都把「单元测试 + 数据管道校验」放进了 CI；我们的 `deploy/publish.ps1` 只校验文件数、体积、新鲜度，**不校验内容回归**（条数突变、页面缺失、检索退化都拦不住）。

4. **「同名不同药」这一层，GitHub 上没有直接竞品，但有权威的相邻实现可抄。**
   OHDSI 的 RxNorm Extension 白纸黑字写「各国市场上的药品**只有约三分之一完全相同**，即使成分相同，规格、剂型、商品名、包装、厂商也会不同」——这是对本站立项前提最硬的外部佐证；它还把 **Brand Name 定义为「非标准概念」**，用 `Maps to` 关系表达等价，与我们「商品名不是主键」是同一个结论的不同实现。

5. **许可上最值得抄的一条：代码与数据分开授权，数据不随包分发。**
   chembl-downloader（代码 MIT，ChEMBL 数据由用户自行下载）与 atcddd（明确不随包分发 WHO ATC/DDD，用户执行 `atc_download()`）给了一个可复制模板：**对外只发「本站派生层」，不可再发布的源留在用户侧**。这正好解掉我们 🔴（NHSA / TGA）与 🟡（CIMA / COFEPRIS）不能整包再发布的死结。

---

## 1. 方法与样本

| 项 | 做法 |
|---|---|
| 检索 | GitHub 仓库搜索（`openfda` / `drug name normalization` 等）+ 定向核实；候选按 star 排序，主题匹配优先 |
| 取证 | 优先读 `raw.githubusercontent.com` 上的 README / 规范页；仓库元数据（star、license）用 GitHub API / ungh.cc 读，**star 为抓取时点读数** |
| 判据 | 只记录项目**明确写出**的做法，不替它推断；README 没写的（如许可）标「待确认」 |
| 排除 | 付费/需登录的商业库（WHODrug、DrugBank、Martindale）不在本轮；消费级 App 见 `docs/竞品与空位.md` |

**检索结论**：`openfda`、`datasette`、`datapackage` 这类「数据基础设施」项目很成熟（数百到上万 star、有 CI、有规范）；而「多国药品注册聚合」「商品名跨国对应」这两个方向**几乎全是低 star 的单国爬虫或个人项目**，没有形成生态。换句话说：**这件事没有开源标杆可抄，能抄的是数据工程规范，不是业务实现。**

---

## 2. 项目清单（按方向）

### 2.1 药品名称 / 药品目录浏览器 / 监管开放数据

| 项目 | star | 许可 | 它明确写出的做法 |
|---|---|---|---|
| [FDA/openfda](https://github.com/FDA/openfda) | 721 | CC0-1.0 | Luigi 管道把公开数据集加工成 JSON 灌 Elasticsearch；仓库含各数据集的 **ES schema**；Node/Express API 服务；`docker-compose` 一键起服务 + 单元测试；README 首段就是「不要用 openFDA 做医疗决策」的免责声明 |
| [FDA/open.fda.gov](https://github.com/FDA/open.fda.gov) | 178 | MIT | 站点本身开源（Gatsby/React）；目录里专设 **`/aria`** 集中管理可访问性属性；测试说明单独放 `TESTING.md`；同样带免责声明 |
| [bennettoxford/openprescribing](https://github.com/bennettoxford/openprescribing)（原 ebmdatalab，会重定向） | 115 | 待确认（README 未写） | 公开看板 + REST API；数据来源集中写在 `/about`；月更数据由 `manage.py fetch_and_import` 管道跑（下载 → GCS → BigQuery → Postgres/SQLite，**数小时**）；CI 跑 Docker 化的测试，另有针对生产环境的检查；功能测试走 BrowserStack |
| [OHDSI/Vocabulary-v5.0 · RxNorm Extension](https://github.com/OHDSI/Vocabulary-v5.0/wiki/Vocab.-RXNORM_EXTENSION) | —（wiki） | 待确认 | 多国药品统一的**概念模型**：Ingredient / Brand Name / Clinical Drug / Branded Drug / Marketed Product 分层；概念有**生命周期**（生成、弃用、更新）；有等价物就记 source 概念 + `Maps to`，没等价物就新建标准概念；强度单位必须映射到 **UCUM**；Brand Name 一律 **非标准概念** |

### 2.2 开放数据聚合与「不转分发」

| 项目 | star | 许可 | 它明确写出的做法 |
|---|---|---|---|
| [cthoyt/chembl-downloader](https://github.com/cthoyt/chembl-downloader) | 待确认 | **代码 MIT**，ChEMBL 数据按上游 CC BY-SA | 主打「可复现下载 + 版本化」：`download_extract_sqlite(version='28')` 显式指定版本、缓存复用；**代码许可与数据许可分开写**；有 `CITATION.cff`、Zenodo DOI、CONTRIBUTING、CODE_OF_CONDUCT、tox + GitHub Actions + Codecov |
| [vanhungtran/atcddd](https://github.com/vanhungtran/atcddd) | 1 | **代码 MIT；WHO ATC/DDD 数据不随包分发** | 明确写「数据不由本包分发，用户必须自己 `atc_download()` 取，下载后仍受 WHOCC 条款约束」；品牌同义词（lipitor → atorvastatin）、模糊匹配、**分级排序检索**（synonym → exact → prefix → substring）；导出带 **SHA256 manifest**；Zenodo DOI + CONTRIBUTING + CoC |
| [Billy-FIN/NMPA_Scraper](https://github.com/Billy-FIN/NMPA_Scraper) | — | **无 LICENSE、无许可声明** | 反面样本：抓的是**企业生产许可信息**（法人、经营范围…），不是药品商品名/规格；无再发布许可。本项目 2026-10-26 已审过，见 `reports/opensource-drug-data-20261026.md` §2 第 12 行 |

### 2.3 开放数据站点 / schema / 许可 / 流水线

| 项目 | star | 许可 | 它明确写出的做法 |
|---|---|---|---|
| [owid/etl](https://github.com/owid/etl)（+ [metadata 规范](https://docs.owid.io/projects/etl/architecture/metadata/reference/)） | 161 | 待确认（文档站 CC BY 4.0） | 每个数据对象旁边放 **YAML 元数据**；字段级：`origin.license{name,url}`、`origin.date_accessed`、`origin.date_published`、`origin.version_producer`、`origin.citation_full`、`origin.url_download`、`variable.license`、`variable.presentation_license`；数据集级：**`dataset.licenses`、`dataset.non_redistributable`、`dataset.update_period_days`、`dataset.changelog`、`dataset.jsonld`**；CI 三条 Buildkite 流水线（单测 / 公共数据集构建 / 夜间全量重建） |
| [simonw/datasette](https://github.com/simonw/datasette)（[metadata 文档](https://docs.datasette.io/en/stable/metadata.html)） | 11,525 | 待确认 | 元数据可作用在**整站 / 单库 / 单表**三级：`license` + `license_url`、`source` + `source_url`、`about`；还有 `columns` 字段说明、`units`（用 Pint 解释）、`size`、`sortable_columns`、`hidden`；许可与来源同时进页脚，**每一页都带着** |
| [frictionlessdata/datapackage](https://github.com/frictionlessdata/datapackage)（[规范](https://datapackage.org/standard/data-package/)） | 593 | 待确认 | 数据集描述符 `datapackage.json`：`name`、`id`（可为 DOI）、`licenses[{name,path,title}]`、`sources[{title,path,version}]`、`version`（建议 semver）、`created`、`contributors[{roles}]`（对齐 DataCite）、`resources[]`（各带 schema：fields / primaryKey / foreignKeys / missingValues） |

### 2.4 名称消歧 / 身份对齐

| 项目 | star | 许可 | 它明确写出的做法 |
|---|---|---|---|
| [OHDSI/Usagi](https://github.com/OHDSI/Usagi) | 120 | Apache-2.0 | 术语→标准概念的映射工具：**先用词相似度自动出一版全量映射**，再用概念名/同义词找候选，按目标词表/域/概念类过滤；**交互式人工复核与修正**；可看目标概念的父子与来源概念；**导出 `source_to_concept_map`**；词表升级后可把旧映射套到新码集上 |
| [CogStack/MedCAT](https://github.com/CogStack/MedCAT)（主仓已迁 [cogstack-nlp](https://github.com/CogStack/cogstack-nlp)） | 待确认 | **Elastic License 2.0**（2022-08 由 Apache 改） | 病历实体识别 + 链接到 UMLS/SNOMED；**模型包需 UMLS 账号才能下载**，即「代码开源 ≠ 数据/模型可用」；有 CI badge、ReadTheDocs、discourse、论文引用；README 里保留完整的许可变更公告 |

---

## 3. 做法对照表

> 优先级：**P0** = 本周能做完、不改数据口径；**P1** = 需要设计或人工复核；**P2** = 可选 / 等条件。

| 做法 | 代表项目 | 本站现状 | 缺口 | 优先级 | 建议任务 |
|---|---|---|---|---|---|
| **标识符与层级**：品牌名不作身份锚点，等价关系用显式关系表表达 | OHDSI RxNorm Extension（Brand Name = 非标准概念 + `Maps to`） | `substance / variant / product / name_key` 四层 + `collision` 视图；只在墨西哥新建 `mx-es-*` 成分 | 没有「映射关系表」这种可导出的边（`brand_family` 只在库内）；无概念生命周期（合并/废弃历史） | P1 | T5、T6 |
| **数据版本写在数据里**（版本号、取数日期、上游版本、变更记录） | OWID：`dataset.changelog` / `origin.date_accessed` / `version_producer`；Data Package：`version` + `created` + `id`(DOI) | `CHANGELOG.md` 是唯一版本源（页脚 / whats-new / Release 都从它生成）；`source` 表 + `db/source_dates.py` 给「数据截止」 | 版本只存在于**站点层**，数据文件本身无版本、无校验和、无 DOI；外部拿到 CSV 无法自证是哪一版 | P0 | T1 |
| **许可与署名随数据走**（不止 About 页） | Datasette：`license`/`license_url` 三级作用域；atcddd：代码 MIT、数据不分发；chembl-downloader：代码/数据双许可 | `docs/许可清单.md` 四级分级（✅🟡🔴⚪）比多数项目细；About 三语逐源署名；记录级有 `source_url` | 记录级**没有 license 字段**；对外 CSV 无许可载体；仓库根**没有 LICENSE / CITATION.cff** | P0 | T1、T2 |
| **「不可再发布」是一等公民** | OWID：`dataset.non_redistributable: true`；atcddd：数据不随包分发 | 我们有同样的判断（🔴 仅事实+链接），但只写在 markdown 表里，构建与导出都不读它 | 口径靠人守；一旦有人做整包导出，🔴/🟡 来源会跟着出去 | P0 | T1（导出器只读许可分级） |
| **更新/发布流水线** | OpenPrescribing：月更 `fetch_and_import`；OWID：夜间全量重建；openFDA：Luigi 管道 + docker | `run_all.py`（备份→入库→种子→建站）+ `deploy/publish.ps1`（完整性闸门：体积、文件数、0 字节、构建未在跑） | 无定时构建；**无数据源漂移告警**（`方案 §6.5` 要求「行数/schema 漂移告警」，`etl/` 里没有实现）；`db/check_data.py` 只能手动跑 | P1 | T8 |
| **测试与 CI** | OWID 三条流水线；OpenPrescribing CI + 生产检查；chembl-downloader tox + Actions + Codecov | 4 套 unittest + 三语 354 条（本地全绿是唯一门槛）；`.github/workflows/` 为空 | 回归靠人记；发布闸门只挡「不完整」，不挡「内容变了」 | **P0** | T3 |
| **搜索/短语匹配**：分级排序 + 候选 + 置信度 | atcddd（synonym→exact→prefix→substring + Levenshtein）；Usagi（Lucene 初排 + 人工复核）；MedCAT（链接 + 置信度） | 归一化管线（NFKC→繁简→西里尔→强度切分）+ 0.55/0.20/0.15/0.10 打分 + 候选集 + 拼音/首字母 + 分片索引（3.78 MB→~254 KB gz，P50 ~1 ms） | 结果页不解释「为什么是这几条」（命中档位/字段未对用户展示，待确认）；昵称只做精确匹配是**有意设计**，不算缺口 | P2 | T11 |
| **国际化** | 抽样项目基本单语（openFDA / OWID / Usagi / Datasette 均英文） | 四语（en/es/zh/zh-Hant）+ `hreflang` + 三语检索一致性测试 | 无缺口，**本站领先** | — | 保持 |
| **可访问性 / 性能** | open.fda.gov 专设 `/aria` 目录集中管理 | 大量 `aria-*`、`aria-live`、`role=listbox/option`、`aria-expanded`、键盘可达；索引分片 + 首屏体积回归 | 没有 WCAG 声明、没有自动化 a11y 检查（axe/Lighthouse）；性能回归是人工比对，无基线文件 | P2 | T10 |
| **医疗内容边界** | openFDA：「Do not rely on openFDA to make decisions regarding medical care」 | D0–D3 四级、D3 命中禁止出现「等量替换」、全局不输出「几片」、每条结论可追 `source_url` | 无缺口，**本站更细** | — | 保持 |
| **隐私 / 统计** | OpenPrescribing 有 `TRACKING.md`（说明跟踪方式） | GoatCounter cookieless、只后台看、不公开计数；issue 模板首屏就写「不要贴病人个人信息」 | 无缺口 | — | 保持 |
| **贡献与纠错流程** | chembl-downloader：CONTRIBUTING + CoC + CITATION.cff + Zenodo DOI；OWID：Discussions + PR 指南；Usagi：issue tracker + wiki | 只有一个 `.github/ISSUE_TEMPLATE/data-error.yml`（字段设计很好：查询词、页面 URL、期望值、实际值、隐私提示） | 没有 CONTRIBUTING（外部人不知道怎么改数据、怎么验）、没有 CITATION、没有「我提交的纠错后来怎么样了」的回执机制 | P1 | T2、T12 |

---

## 4. 值得抄的 5 个具体做法

### 4.1 一个 `datapackage.json` 把「许可 + 来源 + 版本 + 字段」钉在数据上
抄 **Data Package 的字段集**（不是抄它的工具链）：
`name` / `title` / `version`（semver，跟 `CHANGELOG` 第一节同源）/ `created` / `licenses[{name,path,title}]` / `sources[{title,path,version}]` / `resources[]`（每国一个 CSV 或 JSON，带 `schema.fields` 与 `primaryKey`）。
落地：`site/build.py` 在建站末尾多写一个 `site/dist/data/datapackage.json`，字段定义从 `db/schema.sql` 派生，`licenses` 从 `docs/许可清单.md` 的分级派生。
**验收**：`datapackage-validator` 通过；🔴 来源的原始数据不出现在任何 resource 里。

### 4.2 OWID 的 `non_redistributable` 旗标
我们已经有 ✅/🟡/🔴/⚪ 四级判断，缺的是让**程序**读它：给每个来源打 `non_redistributable: true/false`，导出器与页面生成器都读这一个布尔值，而不是各自人肉记。
顺带抄 `dataset.jsonld`：给每个市场的数据页嵌一段 schema.org `Dataset`（name / license / creator / dateModified / distribution），这是搜索引擎与外部复用者认的格式，成本极低。

### 4.3 「代码 MIT / 数据不随包分发」的双许可结构
chembl-downloader 与 atcddd 是同一套解法：**代码一个许可，数据另一个许可，且数据不由项目分发**。
对我们：对外只发**派生层**（substance ↔ 各国商品名 ↔ 规格 ↔ 来源 URL），原始库与 🔴 来源的整表永不出站；想复现整库的人拿 `etl/` 脚本自己去抓。这既解决许可，也符合「公益项目该产出原料」的定位（`docs/竞品与空位.md` §7）。

### 4.4 Usagi 的「机器初排 + 人工复核 + 导出映射表」
我们已经有 `data/maker_candidates.csv`、`combo_match_candidates.csv`、`cn_inn_overrides.csv` 这类候选文件，也有 `brand_family` 人工表——但没有统一的**复核状态**。
抄它的三段式：候选（机器打分）→ 复核（人：接受/拒绝/改目标 + 日期 + 依据）→ 导出（`source_to_concept_map` 风格：source / target / relation / confidence / reviewer / reviewed_at）。
好处：碰撞页与成分页可以显示「这条对应关系来自规则还是人工」，这正是我们比商业 App 硬的地方。

### 4.5 发布闸门加「内容回归」，而不是只加体积检查
OpenPrescribing / OWID 把校验放进 CI；我们没有 CI，但**可以在 `publish.ps1` 里加三条不依赖 CI 的断言**：
① 各市场 `products` 计数相对上次构建漂移超过阈值（如 ±5%）就要求 `-Force`；
② `sitemap.xml` 的 URL 数与 `site/dist` 下页面文件数一致；
③ 固定 20 条查询（含「泰诺」「Benadryl」「Panadol」）的 Top-3 与基线 JSON 逐条比对，退化了就中止。
这三条都是纯本地、几十行 Python 的事，却能挡住 `v0.9.0` 之前那种「构建没跑完就发布」之外的另一类事故：**构建跑完了，但内容错了**。

---

## 5. 不要学 / 不适合我们的

| 不学 | 为什么 | 谁这么干 |
|---|---|---|
| 把品牌名当标准身份，一个名字给一个答案 | 与本站底线 1 直接冲突；OHDSI 明确把 Brand Name 定为**非标准概念**，是权威的反证 | 消费级 App（见 `docs/竞品与空位.md`）与多数"药名归一"脚本 |
| 选「源码可见但限制托管/服务」的许可 | 公共品项目一旦改许可，下游（包括那两款 App）会被卡住；MedCAT 2022 从 Apache 改 Elastic License 2.0 就是前车之鉴 | CogStack/MedCAT |
| 只写自己的 LICENSE，不管上游数据条款 | MedCAT 的模型包要 UMLS 账号才能下；我们若只写「代码 MIT」而不写「数据见许可清单」，等于把风险转给复用者 | 多数 ML 项目 |
| 服务端渲染 + 单一超大数据库 + 实时查询 | 引入运维、备份、可用性三座山；本项目「静态生成 + 预构建索引 + SQLite 单一真相源」更适合无运维交接 | OpenPrescribing（Postgres + BigQuery + GCS） |
| 页面直连上游 API 实时取数 | 违反 `方案 §6.5` 铁律（抓取只在离线 ETL）；上游改版/限流会直接变成线上故障 | openFDA 的 API-first 形态 |
| 用 LLM 直接产出药名归一/解释 | 不可复核、会编造；本轮检索到多个 2026 年新项目走这条路（如 `rxnorm-rag-normalizer`，0 star）。可用作**候选扩展**，但结论必须落回规则 + 人工复核 + 出处 | 一批新项目 |
| 给整个库发 DOI / 上 Zenodo | 只有「可再发布的派生层」值得发；给含 🔴 来源的整库盖章等于给不可再发布内容背书 | 常见于数据论文 |
| 把原始库或抓取缓存提交进 git | 770 MB 产物 + 上游条款不明；我们已 gitignore，别为了「可复现」破例 | 多数单国 scraper |

---

## 6. 建议任务（可直接派工）

| # | 任务 | 优先级 | 验收 | 触及文件 |
|---|---|---|---|---|
| T1 | 数据出口最小版：派生层 `datapackage.json` + 各国 CSV（只含可再发布字段），带 licences / sources / version / 字段字典；页面加「下载数据」入口（三语） | P0 | 校验器通过；不含 🔴 来源原始字段；About 加一句「本站派生数据许可」 | `site/build.py`、`docs/许可清单.md` |
| T2 | 仓库元数据：`LICENSE`（代码）+ 数据许可指向 `docs/许可清单.md` 的说明 + `CITATION.cff` | P0 | GitHub 仓库页显示 License；README 顶部一行「代码与数据分别授权」 | 仓库根 |
| T3 | 发布闸门加 3 条内容断言（计数漂移 / sitemap 一致性 / 20 条查询基线） | P0 | 故意改坏一条数据能让 `publish.ps1 -DryRun` 失败 | `deploy/publish.ps1`、`deploy/verify_live.py` |
| T4 | 每个市场的数据页嵌 schema.org `Dataset` JSON-LD | P0 | 富媒体测试通过；`dateModified` 取 `source_dates.py` | `site/build.py` |
| T5 | 映射表工业化：候选 CSV 加 `review_status/reviewer/reviewed_at/source`，导出 `source_to_concept_map` 风格表 | P1 | 成分页能显示「人工复核 / 规则推导」；碰撞页可下钻 | `data/*.csv`、`site/build.py` |
| T6 | 概念生命周期：`substance`/`variant` 合并留 `merged_into` + 日期（现在只有 override CSV，历史待确认） | P1 | 老 URL 不 404（重定向到新 slug） | `db/schema.sql`、`db/init_db.py` |
| T7 | 单位 → UCUM 映射表（mg/g/mcg/IU/mL/%），D0 输出 UCUM code | P1 | 导出数据里 `strength_unit` 同时给原文与 UCUM | `etl/normalize_name.py`、`lib/` |
| T8 | 数据源漂移告警：ingest 记录行数与 schema hash，超阈值非零退出 | P1 | 用旧缓存重跑能触发告警 | `etl/*.py`、`run_all.py` |
| T9 | 可选 CI：只跑 4 套 unittest + 索引体积断言，**不建站**（建站依赖本地库，见 `DEPLOY.md`） | P2 | PR 上能看到红/绿 | `.github/workflows/` |
| T10 | a11y 声明 + 一次 axe/Lighthouse 审计落 `reports/` | P2 | 报告列出 top-10 问题与修没修 | `reports/` |
| T11 | 检索解释：结果卡显示命中档位（精确/拼音/别名/前缀）与匹配字段 | P2 | 三语一致；不改变排序 | `lib/search.py`、`site/build.py` |
| T12 | 纠错回执：issue 模板增加「是否已处理」由 agent 回帖（复用 `inbox/` 的 append-only 思路） | P2 | 每个 data-error issue 有结论 | `.github/ISSUE_TEMPLATE/` |

> T1/T2 涉及「选什么许可」——按 `AGENTS.md` §11 需要人拍板，不要自行决定。T2 的代码许可若选 MIT/Apache-2.0，与 chembl-downloader、atcddd 一致即可。

---

## 7. 与既有调研的关系（避免重复）

| 既有文件 | 覆盖什么 | 本报告的关系 |
|---|---|---|
| `docs/竞品与空位.md`（2026-10-25） | 消费级 App（World Drugs Converter / MedMatch Pro）、商业库（Martindale / WHODrug / Lexicomp）、IDMP/PhPID 标准 | 本报告补**开源项目与开发规范**这一层；结论一致：空位在「可信度 + 同名不同药」 |
| `reports/opensource-drug-data-20261026.md` | 可用的**数据源**（ChEMBL / WHO INN / 药典委 / CDE）与许可 | 本报告不重评数据源，只引其结论；新增的是「同类**项目**怎么做工程」 |
| `reports/license-audit.md`、`docs/许可清单.md` | 本站在用来源的许可现状 | 本报告把它们的结论当「本站现状」的输入，不重复审计 |

---

## 8. 限制与待确认

1. **star 数为抓取时点读数**；`chembl-downloader`、`MedCAT` 的 star 因接口限流未取到，标「待确认」。
2. **多数项目的 LICENSE 全文未逐字核对**（Usagi Apache-2.0、chembl-downloader MIT、atcddd MIT 是 README 明示；openFDA CC0、open.fda.gov MIT、Usagi Apache-2.0 来自仓库元数据）。其余标「待确认」，引用前需复核。
3. 仓库位置有变动：`ebmdatalab/openprescribing` → `bennettoxford/openprescribing`；`CogStack/MedCAT` 主仓 → `cogstack-nlp`。旧链接会重定向，但引用时用新地址。
4. `opentargets/platform` 已不再作为代码仓存在（现为 issue tracker），本轮未纳入。
5. **未发现「商品名跨国对应」的成熟开源项目**。若存在，本轮检索词与 star 排序可能没覆盖到——这是「检索不到」而非「不存在」。
6. 本站「结果页不解释命中原因」是按代码与报告推断（`lib/search.py` 打分未上屏），**待确认**是否已有局部实现。
7. 是否需要开放 API 仍是 `docs/方案与数据模型.md` §10 的待定项；T1 只做静态数据包，不做 API。

---

## 9. 引用（查证日期 2026-10-30）

**药品 / 监管开放数据**
- openFDA 代码仓：https://github.com/FDA/openfda
- openFDA 站点仓：https://github.com/FDA/open.fda.gov
- OpenPrescribing：https://github.com/bennettoxford/openprescribing
- OHDSI RxNorm Extension（多国药品概念模型）：https://github.com/OHDSI/Vocabulary-v5.0/wiki/Vocab.-RXNORM_EXTENSION
- OHDSI Usagi：https://github.com/OHDSI/Usagi

**数据聚合 / 不转分发**
- ChEMBL Downloader：https://github.com/cthoyt/chembl-downloader
- atcddd（WHO ATC/DDD，数据不分发）：https://github.com/vanhungtran/atcddd
- NMPA_Scraper（反面样本）：https://github.com/Billy-FIN/NMPA_Scraper

**开放数据站点与规范**
- OWID ETL：https://github.com/owid/etl
- OWID 元数据说明：https://docs.owid.io/projects/etl/architecture/metadata/
- OWID 元数据字段参考：https://docs.owid.io/projects/etl/architecture/metadata/reference/
- Datasette 元数据（license / source / 字段说明）：https://docs.datasette.io/en/stable/metadata.html
- Data Package 规范 v2：https://datapackage.org/standard/data-package/
- Data Package 仓库：https://github.com/frictionlessdata/datapackage

**名称消歧 / 概念链接**
- CogStack MedCAT：https://github.com/CogStack/MedCAT
- MedCAT 新主仓：https://github.com/CogStack/cogstack-nlp

**本站内部依据**
- `AGENTS.md`、`README.md`、`DEPLOY.md`
- `docs/方案与数据模型.md`、`docs/许可清单.md`、`docs/竞品与空位.md`
- `reports/opensource-drug-data-20261026.md`、`reports/license-audit.md`
- `site/build.py`（`LICENCE_HTML`、CSV 导出、i18n、aria）、`deploy/publish.ps1`、`.github/ISSUE_TEMPLATE/data-error.yml`

_本报告由并行子智能体生成，全程只读：未改仓库代码/数据/构建，未发布。_
