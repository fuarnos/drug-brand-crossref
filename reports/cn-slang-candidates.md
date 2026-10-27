# 中文俗名抽取 / 成分映射 / Tier B 候选报告

日期：2026-10-27 ・ 任务：task-23 ・ 站点版本：v0.3.5（口径：只按 **Tier B**，不新增 nickname）
产物：`etl/extract_cn_slang.py`、`data/cn_slang_candidates.csv`（1,108 行）、本报告
本轮**未写 `data/drugs.db`**、未跑 site/build.py、未 git/发布；`nickname` 新增 = **0**。

---

## 1. 摘要（验收口径）

| 指标 | 结果 | 要求 |
|---|---|---|
| 去重后候选 | **1,108** 条（normalized 全局唯一） | ≥300 ✅ |
| 有 `substance_id` 可入库 | **1,089** 条 | ≥100 ✅ |
| documented / community | **450 / 658** | 2 独立来源 / 1 来源 ✅ |
| 类别词（substance_id 留空、带 examples） | 12 条（减肥针、瘦瘦针、抗组胺药等） | — |
| `nickname` 新增 | **0**（全部走 `drug_term`） | =0 ✅ |
| Tier C（丢弃） | **4,444** 条（§4 明细） | 计数并说明 ✅ |
| 来源（主平台） | 维基百科 806、维基数据 210、抓取快照 93 | — |

输入 `data/raw/cn_slang/raw_terms.jsonl` 为另一 agent 抓取中的**实时快照**（本次写 CSV 时
750 行；其中 1,200 条记录带成分候选）；抓取仍在继续，**重跑本脚本即可增量吸收**
（本轮从 33 行快照起步，脚本对空/缺文件也能只靠仓库别名表离线跑通）。

---

## 2. 输入与处理管线

### 2.1 输入
1. `data/raw/cn_slang/raw_terms.jsonl`（另一 agent 抓取；term/platform/url/title/snippet/
   fetched_at/lang）——用句式模式抽「俗称/外号/又叫/也叫/别名/商品名/品牌名/黑话/网络叫法/
   旧称/曾用名/音译」等术语，并用同文中的库内药名做**最近锚点**定成分；
2. `reports/cn_aliases.csv`（alias→target_cn，source=wikipedia/wikidata，2,204 行）；
3. `reports/wiki_aliases.csv`（中文维基重定向，kind/pageid，1,374 行）；
4. `data/cn_aliases_final.csv`（前两者合并表，2,362 行）；
5. `reports/ahospital_aliases.csv`（公开健康平台页面整理的 257 条别名：
   乐衡→吉非罗齐、义美仁→硫唑嘌呤、牙周宁→糠甾醇等）。

### 2.2 归一化
- NFKC（全半角/上标）、去空格标点、统一小写；
- 繁→简：`normalize_name._T2S` + **人工整理的药名常见繁简字表**（约 150 字：黴→霉、鹽→盐、
  銨→铵、鹼→碱、碸→砜、韋→韦…）。**不做「按等长别名对投票学习」**——实测会把品牌字学错
  （乐→唑、韦→韋），已弃用；
- `term` 保留原始写法（可繁体），`normalized` 才是简体去标点键（去重/匹配用）。

### 2.3 成分映射（只读 DB）
1. `substance.inn_zh` 及 `ingest_nhsa.reduction_chain`（剥剂型/限定词/盐基）后的基名 → substance；
2. 所有 `name_key.script='han'` 商品名（11,695 个不同写法）及其 reduction_chain 基名 → substance；
   （这批中文商品名里已含大量国内品牌名，如 开瑞坦/达喜/美林/泰诺/必理通/络活喜/立普妥/
   波立维/思密达/万艾可/希爱力/善存/忆孟返/吗丁啉……，因此它们会被正确地去重排除）
3. 库内已有 `nickname.alias_norm` / `drug_term.term_norm`（如 芬必得、扑热息痛、伟哥、
   蓝色小药丸、安定……同样去重排除）；
4. 匹配顺序：原名精确 → 剥剂型/盐基链 → normalize_name → 库内别名；
5. **消歧**：多候选时优先唯一的「非 cn-/非 mx-es-」英文成分；仍多解则 `substance_id` 留空
   并标 ambiguous（21 条）。
6. 类别词（减肥针/瘦瘦针/抗组胺药等，term_type=class）不挂具体成分，但把上下文命中成分写进
   `examples` 列（如 瘦瘦针→semaglutide;tirzepatide、减肥针→semaglutide）。

### 2.4 模式抽取（raw_terms）
`extract_cn_slang.py` 内置正则覆盖：
`又称|又名|又叫|也叫|俗称|俗称其|别称|别名|外号|简称|通常叫|民间叫|网络叫法|黑话|谐音|
代称|商品名|商品名称|商业用名|品牌名|商标名|注册名|译名|旧称|曾用名|中文名|音译`
+ 连接词 `为/作/做/叫/有/是/包括/如/例如/：`；捕获串可含 `/`、`、` 多名并自动拆分；
另支持**反向模式**「X 的通用名/商品名/学名是 Y」与**标题品牌词**（「开瑞坦又叫…」「芬必得
- 百度百科」）。无自身映射时用**最近锚点**：取同文命中的最长库内药名（≥3 字、非术语片段、
与术语字符距离最近）反查成分；类别词/歧义词落 `examples`。

### 2.5 过滤 / Tier 规则
- **Tier C 丢弃**：毒品/娱乐性用药黑话、纯商品名（已在 product_name）、同形异义无法消歧、
  句子碎片/广告/段子、化学系统名、含英文片段、含剂量、与库内规范名相同（不是俗名）、
  目标未映射到库内成分；
- **Tier B 全部保留**：`term_type` ∈ folk（默认）/ class（类别词）/ street（黑话类）；
- `confidence`：独立来源数 ≥2 → `documented`，1 → `community`
  （来源族按 wikipedia/wikidata/alihealth/抓取网站域名 计，同一维基数据只算一次）；
- 去重：`nickname` + `drug_term`（只读查库）+ 全部商品名 + 表内 normalized 全局去重。

---

## 3. 结果

### 3.1 分布
| 维度 | 分布 |
|---|---|
| confidence | documented 451 / community 656 |
| term_type | folk 1,096 / class 12 |
| 语言 | zh-Hans 933 / zh-Hant 174 |
| 有 substance_id | 1,086（其中 cn-* 目标 74 条，其余为英文/mx-es 成分） |
| 主平台 | wikipedia_zh 806 / wikidata 210 / raw（wiki 17 + bing 75）92 |
| 有 examples（类别词/歧义） | 21 |
| 许可 | CC BY-SA 4.0（维基/维基数据，仅短名+链接）996；用户/社区内容（仅叫法+原链接）92；维基重定向 20 |

### 3.2 样例（documented，含成分）
| term | 成分 label | substance_id | 来源 |
|---|---|---|---|
| 万乃洛韦 | Valacyclovir | valacyclovir | wikidata+wikipedia |
| 三苯氧胺 | Tamoxifen | tamoxifen | wikidata+wikipedia |
| 丙硫咪唑 / 丙硫达唑 | Albendazole | albendazole | wikipedia+alihealth |
| 东青 | Aspirin | aspirin | wikipedia+alihealth |
| 义美仁 | Azathioprine | azathioprine | wikipedia+alihealth |
| 乐衡 | Gemfibrozil | gemfibrozil | wikipedia+alihealth |
| 乃柏欣 | Tobramycin | tobramycin | wikipedia+alihealth |
| 乙醯胺酚 | 对乙酰氨基酚 | acetaminophen | wikipedia+raw |
| 争光霉素 | Bleomycin | bleomycin | wikidata+wikipedia |
| 必理痛（HK 名） | 对乙酰氨基酚 | acetaminophen | 抓取快照 |
| 百服宁 | 对乙酰氨基酚 | acetaminophen | 维基+抓取 |
| 康泰克 | 盐酸伪麻黄碱 | pseudoephedrine | 维基+抓取 |
| 乐比克 / 胃达喜 | Zopiclone / Hydrotalcite | zopiclone / hydrotalcite | 维基 / 抓取 |
| 减肥针 / 瘦瘦针（class） | semaglutide（examples） | —（类别词留空） | 抓取快照 |
| 白加黑（class/folk） | 复方感冒药，留空 | — | 抓取快照 |
| 普拿疼 | 对乙酰氨基酚（多来源歧义，留空待人工） | — | 维基+抓取 |

### 3.3 对「覆盖示例目标」的实际情况
- **已是库内既有名称（去重正确排除，站点现在就能搜到；不算新增）**：
  开瑞坦、达喜、美林、泰诺、必理通、络活喜、立普妥、波立维、思密达、万艾可、希爱力、
  善存、忆孟返、吗丁啉（以上在 `product_name`）；芬必得、扑热息痛、伟哥、蓝色小药丸、
  安定（以上在 `nickname`）；
- **本批新增候选**：必理痛、普拿疼、乐比克、胃达喜、百服宁、白加黑、康泰克、减肥针、瘦瘦针等；
- 未出现：999感冒灵（复方中成药，库内无对应成分，Tier C）；阿司匹林/氯雷他定等规范名
  本身（按「非俗名」丢弃）。

---

## 4. Tier C 丢弃计数（写 CSV 那次运行，合计 4,485）

| 原因 | 条数 |
|---|---|
| 与库内规范名/成分名相同（不是俗名） | 1,873 |
| 目标未映射到库内成分（无法确认是药品/本库无产品） | 1,624 |
| 与来源规范名相同 | 251 |
| 句子碎片/功能词/广告/乱码 | 221 |
| 含异常标点 | 145 |
| 同形异义（映射到多个成分，无法消歧） | 100 |
| 库内已有 nickname/drug_term（重复） | 94 |
| 无来源链接（抓取记录 url 为空） | 60 |
| 含英文片段（如「有Aprovel」「包括Indocin」） | 41 |
| 非中文/空 | 38 |
| 化学系统名/编号（如 6-巯基嘌呤） | 26 |
| 毒品/娱乐性用药 | 6 |
| 纯商品名（已在 product_name，重复） | 4 |
| 段子/点评/网络噪音 | 2 |

---

## 5. 入库建议（供 Lead 审后落库）

CSV 列（14 列）：
`term,normalized,lang,region,platform,substance_id,method,confidence,source_url,snippet,license,term_type,label_zh,examples`
→ 映射到 `drug_term`：

| CSV | drug_term | 说明 |
|---|---|---|
| term | term | 原始写法（可繁体） |
| normalized | term_norm | 唯一键 |
| term_type | term_type | folk / class（本轮无 brand_generic/street 仅 1） |
| confidence | confidence | documented/community |
| substance_id | substance_id | 74 条指向 cn-*，入库前建议用当前库再校验一次（成分合并可能删 cn-*） |
| examples | examples | JSON 数组（类别词的举例成分） |
| source_url / snippet / license | source_url / note | 只存短名事实+链接，不转载正文 |
| — | country | 'CN'（繁体条目可再细分） |
| — | source_id | 建议新增 source：`wikipedia_zh`（CC BY-SA 4.0）、`wikidata`（CC0）、
`alihealth_cn`（许可待确认）、`community_web`（用户内容，仅叫法） |

注意：
1. `drug_term` 有 `UNIQUE(term_norm, term_type, substance_id)`；`substance_id` 为 NULL 时
   SQLite 允许多行同 norm —— 入库脚本需自行按 normalized 再去重；
2. 本轮 **nickname 新增 = 0**；入库后同步 About/README/CHANGELOG 的 drug_term 计数；
3. 维基百科 CC BY-SA 4.0：站上需署名「维基百科/维基数据」并链原条目；阿里健康/社区来源
   许可「待确认」，建议入库前由人拍板，或先只入 Wikipedia/Wikidata 部分（约 1,024 条）。
4. 类别词（减肥针/瘦瘦针/抗组胺药等）建议保持 `substance_id` 空、用 `examples` 展示举例成分，
   与现有「类别词/歧义」展示逻辑一致。

---

## 6. 质量说明与已知缺口

- 别名表以「旧称/异体字/繁体写法」为主（无环鸟苷、乙醯胺酚、丙硫咪唑…），纯网络黑话比例
  取决于 raw_terms 抓取量；当前抓取快照质量分层：wiki > bing > toutiao（后两者常有购物清单/
  段子噪音，已过滤）。
- 繁简处理用人工常用字表，不做统计学习（已修掉 乐→唑、韦→韋 等错误映射）。
- `cn-*` 目标 74 条：多为合并后仍只有中文名的成分；若后续再合并，入库前需复核。
- 待人工复核：普拿疼（多来源指向对乙酰氨基酚但被判歧义，建议人工合并）、减肥针/瘦瘦针
  （examples 已是 semaglutide/tirzepatide，可补 examples 到 drug_term）。
- raw_terms 为实时快照且仍在增长（写 CSV 时 750 行）：重跑 `etl/extract_cn_slang.py` 即可
  增量更新 CSV；抓取侧下一步建议把「品牌名 + 通用名」成对作种子（如 开瑞坦 氯雷他定、
  达喜 铝碳酸镁），以补齐品牌覆盖。

---

## 7. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/extract_cn_slang.py --dry-run   # 只统计
& $py etl/extract_cn_slang.py             # 写 data/cn_slang_candidates.csv
```

脚本只读打开 `data/drugs.db`；`raw_terms.jsonl` 不存在时自动只用仓库别名表（离线可跑通）。
