# 搜索/索引直觉审计（task-124）

> 日期：2026-10-28 · 任务：task-124 · 状态：**只读审计完成**（未改 `site/build.py`、未写 DB、未跑 git/发布）
> 快照：`site/dist`（core 32,803,175 B / gzip 7.7 MB，n=160,750；93 个分片 gzip 11.75 MB；`data/drugs.db` sha256 `24692e63…`）
> 产物：本报告 + [`search-intuition-issues.csv`](search-intuition-issues.csv)（109 行，含「是否已排期/排期引用」列）；证据 `.tmp/search-intuition/{index_stats,query_audit,summary,final_extra}.json`、`client_spot.json`、`audit.py`
> 说明（lead 补充）：报告标注问题是否已在排期——已排期项只做对照、不重复提方案；**重点给未排期问题**。

---

## 0. 结论（先看 5 条）

1. **索引字段总体完整**：core 25 列（含 `atc/xz/db/sl/rl/wi`）在 160,750 条目上无结构性缺列；分片 93 文件条目总和 = 160,750，`db` 桶名与文件 0 不匹配。缺省字段多为设计（`u` 80.6% 无品牌页、`vs/cu` 71% 单方、`d` 空=编码省略回退 k）。
2. **最大用户直觉问题是「伪复方」**：**1,489** 个 key 把同一活性成分的碱基+盐型当成多成分——如 `amoxicillin | x=Amoxicillin + Amoxicillin Trihydrate`、`lipitor | Atorvastatin + Atorvastatin Calcium`；同时生成 `combo/*` 组合页并触发 **l=severe「Same name, different drug」** 徽章。用户会以为 Lipitor 是复方/同名不同药。（**未排期**）
3. **索引含大量非在售名字**：160,750 个索引 key 中 **30,391（18.9%）不在 active 产品集**（32,013 个 key 仅有 inactive 产品）；抽样 3,000 条与 DB active 对账：mismatch 165 + 索引 key 在 DB 查无 599。搜索会出现「名字对上了，但没有在售产品」并让品牌计数失真。（**未排期**，数据口径）
4. **客户端 vs lib 检索能力不一致**（用户侧 vs CLI/CI 侧）：客户端 ATC 码/大类检索正常（`N02BE01` 5348 名称、`C10AA05` 302、`降压药/抗生素` 48/51 行），lib.search 对 ATC 10/10、大类 6/6 全部 0 结果 → CI/CLI 评测失真（同 task-111 拼音层问题）。（**lib 层未排期**；客户端 v0.6.4/v0.7.1 已上线）
5. **客户端拼音只支持「完整名字的全拼」**：`buluofen`（布洛芬）、`tai nuo`（泰诺）在客户端 **0 结果**；lib 层（task-111）已支持前缀/空格，但**客户端未同步**。另外 pinyin token 有 **871 个含 `ü`**（如 `j:ailitelühuabianerrongye50`），用户输入 `lv` 无法命中。（**未排期**）

---

## 1. 方法 / 口径

| 项 | 做法 |
|---|---|
| 索引审计 | 解码 `core.json` 全量 160,750 条（Python 等价 decodeCore）；逐字段缺失、name key 形态、`xz`/`x` 平行性、`u`（品牌页）、`atc`、`c/n` 与 DB 对账（抽样 3,000）；分片 93 文件全量核对字段与 `db` 桶 |
| 辅助文件 | `aliases.json`（1,119）、`pinyin.json`（53,883 token）、`categories.json/terms.json` 结构校验 |
| 100 高频查询 | 配比：品牌 25 / 成分英 20 / 成分中 5 / ATC 10 / 大类 6 / 大类口语词 4 / 俗名 15 / 错拼 10 / 中文名 5 = 100；期望来自 **DB 结构**（产品→成分、别名→substance、ATC→substance）或 cases_v3（错拼） |
| 客户端对照 | jsdom 跑真实 `site/dist/index.html + app.js`，抽 11 条（ATC/大类/拼音/品牌/俗名）验证「用户侧」行为；lib.search 结果作为 CLI/CI 层对照 |
| 限制 | 无搜索日志（GoatCounter 后台未导出），100 例是结构化抽样而非真实频次；lib 与客户端渲染层级不同，结论已分别标注 |

---

## 2. 索引体检结果

### 2.1 字段缺省（条目级，n=160,750）

| 字段 | 缺失 | 判断 |
|---|---:|---|
| `c/x/l/f/n/v/db/mn` | 0% | ✅ |
| `atc` | **9.39%（15,089）** | 数据覆盖：无 ATC 的成分无法被 ATC 检索/类目命中 |
| `xz` | 45.28%（72,788） | 正常（英文市场无中文名）；仅 15 条中文 key 无 xz，长度不齐 **0** ✅ |
| `s`（强度） | **24.88%（39,988）** | 源无剂量；结果行会显示无规格（用户直觉缺口） |
| `u`（品牌页） | **80.63%（129,611）** | 按 v0.5.3 设计（纯 INN/单包装不建页）；**需核对：trade-ish 多包装仍空 8,741 条** |
| `vs/cu` | 71.33% | 单方正常（复方才有） |
| `mu/ml` | 30.75% / 87.87% | 厂家页规则（≥5 产品）+ 展开列表，设计 |
| `g/gn`（品牌家族） | 99.99% | 人工表极小，正常 |
| `sl/rl/wi` | 71.8/96.26/97.77% | 只有单成分有盐型/释放/警示，正常 |
| `d` 空 | 14,855（9.24%） | **非问题**：编码省略，客户端 `decodeCore` 回退 `d←k`（`build.py` 注释/实现） |

- `u` 页面缺失 **0**（索引不变量守住）；`u_weird` 1 条（文件名含异常字符，需抽查）。
- `aliases.json`：1,119 条；`missing_substance=36` 均为**类别别名**（`water pill → Diuretics`）设计为 `v=None`；`duplicate_labels=2`（待清理）；`bad_kind=0`。
- `pinyin.json`：53,883 token（i: 25,174 / j: 28,337 / s: 372），id 最大 160,652 < n、无越界；**bad_format=871**（含 `ü` 的 token，见 §4 问题 4）。
- 分片：entries 160,750 = core n；`db` 桶 0 不匹配；字段漂移：`dp`（仅 core 编码用）、`sl/rl/wi` 在 shard 条目缺省（客户端按 undefined 处理）→ 文档化即可，非用户可见。

### 2.2 name key 异常（6,898 + 2,416 + 少量）

| 类型 | 数量 | 样例 |
|---|---:|---|
| 超长（>60 字符） | **6,898** | `dextroamphetamine saccharate amphetamine aspartate …`（长产品标题被当 key） |
| 单词数 >12 | **2,416** | `hypodermic insulin pen reusable for cartridge 1 unit dial up range 1 60 units`、整段疫苗抗原名 |
| 单字符 | 9 | `b`、`e`、`鸣` |
| 纯数字 | 11 | `282`、`692`、`292` |
| 控制字符 | 1 | `糠酸莫米松乳膏\x02` |

> 重复 key = 0；无大小写重复（normalize 后唯一）。长 key 会进入前缀/子串匹配，可能造成无关命中与 URL 噪声。

### 2.3 xz / x 与「伪复方」

- `xz` 与 `x` 的 `" + "` 分段**长度不齐 = 0** ✅；中文 key 但 xz 空 = 15（中文界面回退英文）。
- **伪复方（重点）**：`vs` 含 ≥2 个 substance、但英文名首词相同（同一活性成分的盐型/碱基）→ **1,489 条**；这些条目 `x` 显示 `A + A salt`、`cu` 指向 `combo/a+a-salt.html`、`l=severe`（同名不同药徽章）。样例：
  - `amoxicillin` → `Amoxicillin + Amoxicillin Trihydrate`，combo 页，l=severe
  - `lipitor` → `Atorvastatin + Atorvastatin Calcium`（n=44，u=lipitor.html，l=severe）
  - `lisinopril`、`ondansetron`、`escitalopram`、`citalopram`、`azithromycin`、`sitagliptin`、`candesartan`…
- 影响：用户查 Lipitor/阿莫西林会看到「混了两种成分」「同名不同药」→ 直接违背「符合使用直觉」。

---

## 3. 100 查询结果（lib.search 层；客户端对照见 §3.2）

### 3.1 命中（期望来自 DB 结构/cases_v3，非检索输出）

| 类别 | 查询数 | Top5 命中 | Top1 命中 | 说明 |
|---|---:|---:|---:|---|
| 品牌 | 25 | 23 | 23 | Tylenol/Advil 期望集为空（DB 里 trade 名大小写/变体不同，oracle 未建立），不计 miss |
| 成分（英） | 20 | 20 | 20 | ✅ |
| 成分（中） | 5 | 5 | 5 | ✅ |
| 中文 key（高频） | 5 | 5 | 5 | ✅ |
| 俗名/别名 | 15 | 12 | 12 | miss 3：`硝化甘油炸藥`、`蘇達菲`、`維他命B9`（繁体别名；lib 别名归一未覆盖繁简/旧名，**未排期**） |
| 错拼 | 10 | 8 | 6 | v2 既有难例（长商品名/生僻名），与 task-84 一致 |
| **ATC** | 10 | **0** | 0 | lib 未下沉 ATC 搜索（客户端正常，v0.6.4 已上线） |
| 大类 | 6 | 1 | 1 | lib 未下沉大类搜索（客户端正常，v0.7.1 已上线） |
| 大类口语词 | 4 | — | — | `退烧药` 客户端也 0；`解热镇痛` 仅 substring 命中 3 条产品名 |
| **合计** | **100** | **74** | **72** | 26 条 miss 中 20 条是 ATC/大类（lib 层能力缺口），3 条繁体别名，2 条错拼难例，1 条其它 |

### 3.2 用户直觉问题（100 查询 Top5 汇总）

| 现象 | 量 | 样例 |
|---|---:|---|
| **品牌不可点**（`u` 空） | **176/500 个品牌格（45/100 查询）** | `nicotine`/`nicotina` 5/5 不可点；`bupropion hydrochloride` 2/5 |
| **同名不同药混排**（Top5 内同品牌对应多个成分集） | **18/100 查询** | `Dove`、`ALLERGY RELIEF`、`Degree` 各出现同品牌多成分 |
| **规格缺失**（Top5 卡片无强度） | **23/500 格（10/100 查询）** | 部分源无剂量 |
| 排序不理想（命中但非 Top1） | 2/10 错拼 | `MODOIDAL`→Modafinil 排第 2（第 1 是 `Modisal XL`）；`DAlOSAR`→Dapagliflozin 排第 2 |
| 空白名称 | 0 | 客户端 `d` 回退 `k`，未见空白 |

### 3.3 客户端 vs lib 抽检（jsdom，真实 app.js）

| 查询 | 客户端结果 | lib.search | 结论 |
|---|---|---|---|
| `N02BE01` | ATC 结果 **5348 产品名** | 0 | 客户端 ✅ / lib 缺 ATC 层 |
| `C10AA05` | ATC **302 产品名** | 0 | 同上 |
| `降压药` | 大类 topic **48 行** | 0 | 客户端 ✅ / lib 缺大类层 |
| `抗生素` | 大类 topic **51 行** | 0 | 同上 |
| `解热镇痛` | 仅 substring 3 行（TW 产品名含该词） | 2 行 substring | 口语类名无映射（客户端/服务端都弱） |
| `退烧药` | 0 | 0 | 口语类名缺失 |
| `buluofen` | **0** | 有结果（前缀兜底） | **客户端拼音不支持部分输入** |
| `tai nuo` | **0** | 有结果（空格 compact） | 客户端拼音不支持空格 |
| `lipitor` | 84 行；首行显示 `Atorvastatin + Atorvastatin Calcium` +「Same name, different drug」 | 卡片同 | **伪复方 + collision 误导**（问题 1） |
| `tylenol` | 129 行（按国家分组） | 命中 | ✅ |
| `扑热息痛` | 49 行（别名命中） | 命中 | ✅ |

客户端页面无 JS 错误；ATC/大类/拼音行为的差异确认是「层能力」而不是渲染 bug。

---

## 4. 问题 Top 20（样例 / 期望→实际 / 建议 / 优先级 / 是否已排期）

| # | 优先级 | 问题 | 样例（期望 → 实际） | 影响 | 建议 | 排期状态 |
|---:|---|---|---|---|---|---|
| 1 | **P1** | **伪复方：碱基+盐型被当多成分** | `lipitor` → 期望「Atorvastatin（单成分）」；实际显示 `Atorvastatin + Atorvastatin Calcium` + combo 页 + Same-name-different-drug | 1,489 key；含大量常用药（amoxicillin/lisinopril/escitalopram…） | 按 base substance 归并 `x/vs/cu/l`；只有不同 base 才算复方/碰撞；combo 页去重 | **未排期** |
| 2 | **P1** | 客户端拼音不支持部分/带空格输入 | `buluofen`、`tai nuo` 期望布洛芬/泰诺；客户端 0 结果（lib 已修） | 中文用户常见输入习惯 | 客户端同步 task-111 的 compact + 全拼前缀兜底（pinyin.json 查询前先 compact、加前缀匹配） | **未排期**（lib 已下沉，客户端未改） |
| 3 | **P1** | 索引含大量非在售 key | 160,750 key vs active 130,359；30,391 不在 active、32,013 active 为空 | 命中但无在售产品 / 品牌计数失真 | 索引增加 status 维度或过滤 inactive-only key；或 UI 明示「历史/已下架」不计入「N 个品牌」 | **未排期**（数据口径） |
| 4 | **P1** | pinyin token `ü` 未转 `v` | `j:ailitelühuabianerrongye50` 等 871 个 token；用户输入 `lv` 无命中 | 含 lü/nü 音的药名拼音查询失效 | token 生成统一 `ü→v`（build 与 lib 同步）；或查询侧同时试 v/ü 变体 | **未排期** |
| 5 | P2 | lib 与客户端检索能力不一致（ATC/大类） | 客户端 ATC 5348/302 名称、大类 48/51 行；lib 0 | CI/CLI/评测低估真实能力 | 把客户端 `atcQuery`/`categoryCandidates` 下沉 lib（类似 task-111 pinyin）；CI 才能覆盖 | **未排期（lib 层）**；客户端 ATC v0.6.4 / 大类 v0.7.1 **已上线** |
| 6 | P2 | 同名不同药混排（结果行） | 18/100 查询 Top5 内同品牌多成分（Dove / ALLERGY RELIEF / Degree） | 用户以为同名同药 | 结果行按成分集合分组、给「同名不同药」提示（成分页已有，结果页缺） | **未排期** |
| 7 | P2 | 品牌不可点（含疑似多包装无页） | Top5 176/500 格不可点；trade-ish 多包装仍无页 **8,741**（如 `acetaminophen n=1368`、`维生素c片 n=632`） | 用户点品牌无反应 | 按 v0.5.3 设计不改链接；对 8,741 条逐类核对 `worth_page` 判定/源 trade 标记；UI 对不可点品牌加视觉提示 | 设计项**不排期改**；8,741 条**未排期核对** |
| 8 | P2 | 长/怪 name key | 6,898 条 >60 字符（长产品标题）、2,416 条 >12 词、9 单字符、11 纯数字、1 控制字符 | 噪声命中/URL/排序 | 长标题拆成别名或截断主 key；单字符/纯数字/控制符清理；入库校验 | **未排期** |
| 9 | P2 | ATC 覆盖缺口 | 15,089 条目（9.39%）无 atc；这些成分无法被 ATC 搜索/类目命中 | ATC 功能覆盖不全 | 补 ATC 映射（ChEMBL/Wikidata 等已接入源）+ 无 ATC 时不展示 ATC 入口 | **未排期**（数据侧；v0.8.2 只修 ATC 显示 i18n，不补数据） |
| 10 | P2 | 索引与 DB active 口径漂移 | 抽样 3,000：mismatch 165、索引 key 查无 599（20%）；`index.n` 含 inactive | 计数/结果不一致 | 索引构建按同一 active 口径或双列（active/total） | **未排期**（与 #3 同根） |
| 11 | P2 | 繁体/旧名别名查询未命中 | `硝化甘油炸藥`、`蘇達菲`、`維他命B9` → 期望 Nitroglycerin/Pseudoephedrine/Folic Acid；lib 0 结果（客户端未抽检） | 港澳台/繁体用户 | 别名归一补繁简/旧名映射（lib 与客户端 alias_norm 同步） | **未排期** |
| 12 | P3 | 口语大类词缺失 | `退烧药` 0；`解热镇痛` substring 命中 3 条含该词产品名，非分类语义 | 用户按「大类」搜索失败/误解 | 术语表补常见口语类名（退烧药/消炎药/胃药…）→ categories 别名 | **未排期**（v0.7.1 只覆盖官方类名） |
| 13 | P3 | 结果行规格缺失 | 24.88% 条目无 `s`；Top5 23/500 格无剂量 | 用户看不到规格 | 显示「规格未载」/数据源说明；成分页矩阵排序/筛选 | 结果行**未排期**；成分页矩阵 v0.8.3 **已排期**（不重复） |
| 14 | P3 | 排序不理想（错拼） | `MODOIDAL`→Modafinil 第 2、`DAlOSAR`→Dapagliflozin 第 2 | 少量 | 拼写距离/品牌权重微调 | **未排期**（任务 84 评测已有基线） |
| 15 | P3 | xz 覆盖缺口（中文 key） | 15 条中文 key xz 空 → 中文界面回退英文 | 少量 | 补中文名或标注「中文名未收录」 | **未排期**（v0.5.5 xz 已上线，缺口未排期） |
| 16 | P3 | 别名重复标签 | 2 条重复 alias 标签 | 少量 | 别名去重 | **未排期** |
| 17 | P3 | 伪复方产生的 combo/页面 | 1,489 个 combo 页（`combo/a+a-salt.html`）与同名页 | 站内 SEO/导航噪声 | 随问题 1 一并去重 | **未排期**（同 #1） |
| 18 | P3 | 不可点品牌无视觉提示 | 80.6% 条目品牌是纯文本，用户不知道为何不能点 | 交互直觉 | 纯文本品牌加 title/说明「无独立品牌页」 | **未排期**（与 #7 同源） |
| 19 | Info | d 空 / u/mu/ml 缺省 | d 空 14,855 条（回退 k）、u 空 80.6%（设计） | 无 | 无（文档已写明 decodeCore 回退） | **非问题** |
| 20 | Info | 分片字段漂移 | `dp` 仅 core；`sl/rl/wi` 缺省时 shard 条目不写 | 无（客户端按 undefined） | 文档化或构建校验 | **非问题** |

> CSV 里有 109 行（含每查询的 relevance/brand_link/spec_missing 明细），字段：`category, priority, scope, sample, expected, actual, metric, suggestion, scheduled, scheduled_ref, evidence`。

---

## 5. 未排期问题重点（lead 要求；不重复已排期方案）

**P1（先做）**
1. **伪复方/盐型归并**（#1/#17）：1,489 key 的错误「复方/同名不同药」是本次最明显的「不符合直觉」问题；需要数据侧 base-substance 归并规则（是否已有 `variant` 基盐映射/`salt_base_fraction` 可复用需确认）。
2. **客户端拼音同步 lib 改进**（#2）：compact（空格/符号）+ 全拼前缀兜底 + `ü→v`（#4）；lib 侧 task-111 已有实现，客户端可直接对齐。
3. **索引 active 口径**（#3/#10）：30,391 个非 active 索引 key 会制造「命中但无在售」；建议索引分 active/total 两列或构建时区分，UI 明确历史状态。

**P2（下一批）**
4. lib 下沉 ATC/大类检索（#5）——注意：**客户端功能已上线（v0.6.4/v0.7.1），这里只是 lib/CI 层补齐，不重做客户端**。
5. 同名不同药结果分组（#6，客户端渲染层）。
6. 品牌不可点 8,741 条多包装核对（#7，数据规则）。
7. 长/怪 name key 治理（#8）+ ATC 覆盖（#9）。
8. 繁体/旧名别名归一（#11）。

**P3（体验/数据治理）**：口语大类词（#12）、规格缺失显示（#13）、错拼排序（#14）、xz 缺口（#15）、别名去重（#16）、不可点品牌提示（#18）。

---

## 6. 已排期/已上线项对照（不重复提方案）

| 已有工作 | 与本次审计的关系 |
|---|---|
| **v0.8.2（开发中）**：零结果埋点 `search0-*`、About 四语隐私、search-weekly 周报、**ATC 大类入口/活性成分四语显示修复**、首页引导卡、搜索后收起大类、页头导航换行 | ATC/大类**显示 i18n** 已排期（本次未发现新的显示 i18n 问题）；零结果埋点将为后续「高频零结果」提供真实日志，可替代本报告的抽样假设 |
| **v0.8.3（待做）**：成分页矩阵常用剂量优先排序 + 筛选器（国家/剂型/释放/规格）+ 全部未收录空行隐藏 | 与「规格缺失/排序/筛选」相关的**成分页矩阵**已排期；**搜索结果行**的规格/排序不在该范围 |
| 拼音层下沉 lib（task-111，已完成） | 已有 lib 版前缀/空格拼音；本次 #2 是**客户端缺同步**，#4 是 `ü→v`（lib/build 都需改） |
| 搜索评测 v3 + CI（task-84，已完成） | 提供 100/500+ 评测基线；本次 #5 指出 CI 用 lib 层会漏掉 ATC/大类能力 |
| ATC 码搜索（v0.6.4）、大类/类名搜索（v0.7.1，客户端） | 已上线，不重复；#5 只是 lib/CI 层缺 |
| index.json 移除（v0.6.1）、品牌页规则（v0.5.3 设计） | 不再重复；#7 的设计项不排期改 |
| A1/A3/B6/B7（v0.5.6 已上线） | 详情/盐型徽章/报告/导出已上线，不重复 |

---

## 7. 复现 / 证据

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\search-intuition\audit.py        # 索引+100 查询审计（只读）→ .tmp/search-intuition/*.json + CSV
& $py .tmp\search-intuition\summarize.py    # 查询/伪复方汇总
& $py .tmp\search-intuition\pack_summary.py # 摘要 + 追加重点未排期 issue
& $py .tmp\search-intuition\finalize.py     # 同品牌混排/u空/规格/索引 active 覆盖等收尾指标
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$env:NODE_PATH = (Resolve-Path '.tmp\dist-search\node_modules').Path
& $node .tmp\search-intuition\client_spot.mjs   # 客户端 jsdom 抽检
```

- 全量结果：`.tmp/search-intuition/index_stats.json`（字段/键/分片/别名/拼音/DB 对账）、`query_audit.json`（100 条明细）、`summary.json`、`final_extra.json`、`client_spot.json`
- CSV：`search-intuition-issues.csv`（108 行，含 scheduled 列）
- 本任务未改 `site/build.py`、`data/drugs.db`，未 git/发布。
