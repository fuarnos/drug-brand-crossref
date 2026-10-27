# 开源项目/数据集调研：药名多语言映射与 ATC/成分补全（task-18）

> 日期：2026-10-26 ｜ 只读调研；不写 `data/drugs.db`、不跑 git / 发布 / `site/build.py`。
> 写范围：本报告 + `.tmp/opensource/`。
> 标记：`【已验证】` = 本次实际请求/下载/阅读许可证页并有证据；`【推断】` = 估计/未抽验。
> 当前库在其它任务并发更新：本报告快照为 substance 12,793 / 有 ATC 5,890 / 缺 ATC **6,903**（lead 给的 6,943 是另一时刻口径；数字会漂移，结论不变）。

---

## 0. 一句话结论

**没有哪个开源项目能「一次补掉」全部三块缺口。** 现实最优组合是：

| 缺口 | 最可能来源 | 可补量（估算） | 许可 | 结论 |
|---|---|---|---|---|
| **CN 1,683 uncertain + 38 no_english** | **国家药典委员会 WHO INN 中文译名公示** + **CDE 仿制药参比制剂目录**（中文通用名+英文名） | 约 50–70%（约 840–1,180 条）【推断】 | 政府公开信息，**无开放许可**（只能存事实+链原文） | 可做，需逐批解析，不是「下载即用」 |
| **ES/MX 674 no_english + 159 uncertain** | **WHO INN 公开清单（Latin/English/French/Spanish）** + Wikidata 西语标签 | 约 30–50%（约 250–420 条）【推断】 | WHO 内容 CC BY-NC-SA 3.0 IGO（署名+非商业+相同方式共享） | 可做；剩余是墨西哥本地名，仍需人工 |
| **ATC 缺口 6,903** | **ChEMBL**（CC BY-SA 4.0）+ **RxNav/RxClass**（免费）+ DrugCentral（CC BY-SA 4.0） | 约 **200–600 个成分**（抽样推断，占缺口 3–9%） | 开放/免费；但 ATC 本身是 WHOCC 第三方内容，对外展示有版权风险 | 能做，但天花板很低——**6,903 里近 4,100 个根本不是 INN 药物实体**（生药、顺势、生物材料、复方），任何 INN→ATC 项目都补不了 |

**建议**：把「ATC 缺口」重新定义成两个指标——①「真药物 INN 的 ATC 缺口」约 2,800 个（可补 200–600）；②「非标准成分 4,100 个」在数据模型里标 `substance_type=non-drug/botanical/biological`，**不再追求给它们 ATC**。这比继续手工策展更符合用户「别一直手工」的诉求。

---

## 1. 缺口基线（本次实测）

```text
DB 快照（只读）：substance 12,793；有 ATC 5,890；缺 ATC 6,903
  · cn- 专属成分 1,827（ATC 全覆盖，CN 不是 ATC 缺口）
  · mx-es- 717（缺 ATC 692）
  · 按市场：US-only 2,447 / GB-only 1,623 / AU-only 993 / MX-only 729 / CA-only 462 / ES-only 158 / 无产品 149（其余为组合）
CN 名称映射（data/cn_inn_overrides.csv，2,177 行）：
  mergeable 350 · uncertain 1,683 · no_english 38 · combination 106
ES/MX 名称映射（data/es_inn_overrides.csv，1,081 行）：
  mergeable 182 · no_english 674 · uncertain 159 · combination 66
```

ATC 缺口的「成分质量」实测：6,903 个缺失成分里，名字像标准 INN（单词、非生药/疫苗/生物材料关键词）**只有 2,809 个**；其余 4,094 个是 `Propionibacterium Acnes`、`Oxygen 50% Cylinders`、`Pork Heart`、`Generic Eno Sachets` 这类非 INN 实体（多来自 ES CIMA 顺势/生药与 AU/CA 的膳食补充剂条目）。

---

## 2. 候选清单（按「缺口覆盖 × 许可可行性 × 接入成本」排序）

| # | 项目 / 数据集 | URL | 许可（可否公开再发布） | 字段（中/西/英名、INN、ATC、商品名） | 量级 | 接入成本 | 本次证据 |
|---|---|---|---|---|---|---|---|
| **1** | **国家药典委员会 · WHO INN 中文通用名称公示** | `chp.org.cn` 公示（如 WHO INN P-List 131，2025-05-23） | 政府公开信息，**无开放许可** → 只存事实字段+出处链接 | **中文通用名 ↔ 英文 INN（P-List 表 1/2）**；无商品名、无 ATC | P-List 1–131 分批；累计约 6,000–7,000 个 INN【推断】 | 中：逐批抓公示页 + 附件 PDF 解析（PDF 为表格，可用 pymupdf） | 【已验证】公示文本确认「对 WHO INN 建议目录 131 的中文通用名称予以确定」；附件名 `WHO+INN+P-List131部分品种及有关化学药品通用名称.pdf` |
| **2** | **CDE 仿制药参比制剂目录（1–94 批）** | `cde.org.cn/yzxpj/...`（如 2025 年第 26 号通告，第九十四批） | 政府公开通告，**无开放许可** → 事实+链接 | **药品通用名（中文）+ 英文名 + 规格 + 持证商** | 94 批，累计数千条 | 中：通告页 JS 渲染（本次 GET 返回 202，页内无直接附件链接），需浏览器/已知附件 URL；PDF/表格解析 | 【已验证】通告标题与表头（通用名/英文名/规格/持证商）来自公开索引；页面可达但正文由 JS 渲染 |
| **3** | **ChEMBL（EBI）** | `https://www.ebi.ac.uk/chembl/api/data/`；dump：`https://chembl.gitbook.io/chembl-interface-documentation/downloads`；工具 `https://pypi.org/project/chembl-downloader/` | **CC BY-SA 4.0**（可公开再发布，须署名+相同方式共享；衍生数据库也要 CC BY-SA） | **INN（pref_name）+ ATC classification + 同义名（synonyms，含部分商品名）**；无中文名 | 2.4M 化合物；带 ATC 的分子约数千 | 低：API 单条查询（本次验证 `molecule.json?pref_name__iexact=metformin` 返回 `atc_classifications:["A10BA02"]`）；或 `chembl-downloader` 拉 SQLite 离线 join | 【已验证】API 200 + ATC 字段；`atc_class.json` 200 |
| **4** | **RxNav / RxClass（NLM）** | `https://rxnav.nlm.nih.gov/REST/`；条款 `https://www.nlm.nih.gov/research/umls/rxnorm/docs/termsofservice.html` | API 免费无 key；**RXCUI/名称是 NLM 公有领域**；**ATC 是 WHOCC 第三方内容（SRL 限制），整表再发布有风险**；full release 需免费 UMLS 账号 | 英文 INN/品牌名 + **ATC（RxClass ATC）**；无中/西名 | API 实时；RxNorm 全量 SCD/SBD 约 10 万级 | 低：`/REST/rxclass/class/byDrugName.json?drugName=X&relaSource=ATC`（本次验证 metformin 返回 ATC 类） | 【已验证】version 200（05-Oct-2026）、rxcui、ATC by drugName 200；ToS 页面确认 UMLS license/第三方 SRL |
| **5** | **DrugCentral（UNM）** | `https://drugcentral.org/download`；许可 `https://drugcentral.org/privacy` | **CC BY-SA 4.0**（可再发布，署名+相同方式共享） | INN 名、CAS、结构、ATC（DB dump 内）；有 FDA/EMA/PMDA approved CSV | DB dump（Postgres）；FDA 2,331 行 / PMDA 435 行 CSV | 中：dump 需 PostgreSQL 16 + RDKit cartridge；CSV 可直接用但只有 id+英文名 | 【已验证】许可页 CC BY-SA 4.0；PMDA/FDA CSV 已下载（无日文名） |
| **6** | **WHO INN 推荐清单（公开 PDF，L/EN/FR/ES）** | `https://www.who.int/publications/m/item/inn-rl-94` | **WHO 版权，CC BY-NC-SA 3.0 IGO**（署名+非商业+相同方式共享） | **Latin/English/French/Spanish（西班牙语 INN！）**；无中文、无 ATC | List 94：252 页；历史 List 1–94 累计约 7,000 INN | 低-中：下载 94 份 PDF 解析（本次验证列表 94：表头「Latin, English, French, Spanish」；前 30 页 CJK 字符 0） | 【已验证】PDF 下载（4.26 MB/252 页）+ 文本抽验；WHO 版权页 CC BY-NC-SA 3.0 IGO |
| **7** | **WHO MedNet INN 数据库** | `https://extranet.who.int/soinn/`（MedNet INN services） | 免费**会员制** + WHO CC BY-NC-SA 3.0 IGO 级条款 → **需注册/同意条款** | **Arabic/Chinese/English/French/Spanish/Russian INN 名称 + ATC（若已分配）** + 化学信息 | 全量 INN（约 7,000+） | 中：需 MedNet 会员账号；无公开 API/批量导出（以检索为主，需核 ToS） | 【已验证】SoINN 页面原文：会员可「display the equivalent of the Latin INN name in Arabic, Chinese, English, French, Spanish and Russian … ATC codes if assigned」 |
| **8** | **Wikidata（P267 ATC + 多语言标签）** | `https://www.wikidata.org`；SPARQL `https://query.wikidata.org/` | **CC0 1.0**（可自由再发布） | 多语言 label/altLabel（zh/es/en…）+ ATC P267；无商品名 | 4,371 个 ATC 码；约 4.4k 药物条目 | 已接入（CN 映射 330 条、ES 109 条、ATC +594）；剩余增益小 | 本项目既有证据（`.tmp/cn-map`、`.tmp/es-map`） |
| **9** | **MeSH / MeSH 翻译文件（NLM FTP）** | `https://www.nlm.nih.gov/mesh/MeSH_FTP_Guide.html`（`mtms` 目录=翻译文件） | MeSH 英文数据公有领域；**翻译版权归属各翻译机构，需单独核** | 英文 MeSH 主题词 + 各国翻译；药物多为类别/通用名 | 全量 MeSH 30k+ 词 | 中：FTP 目录本次未成功列目录（返回文档页，未验证具体语种/文件） | 【部分验证】FTP 指南确认存在 `mtms`（MeSH translation files）子目录；语种/许可未抽验 |
| **10** | **openFDA** | `https://open.fda.gov` | 美国政府作品（可再发布） | 英文 `brand_name`/`generic_name`/成分强度；**无 ATC、无中文** | 110k+ NDC | 已接入（US 层） | 既有项目 |
| **11** | **CMeKG / 中文医学知识图谱** | GitHub/论文项目（如 `tyang816.github.io` 的 CMeKG 页面） | 多为研究用途，许可各异 | 中医/医学实体关系；**不是「中文药名→INN」映射表** | — | 高（需 NLP 抽取） | 【已验证】检索到项目页，但定位是中医知识图谱；不匹配本缺口 |
| **12** | **NMPA_Scraper（GitHub 第三方）** | `https://github.com/Billy-FIN/NMPA_Scraper` | 代码无明确 LICENSE；**数据再发布许可不明** | README 实测：抓的是 **企业生产许可/公司信息**（法定代表人、经营方式、地址…），**不是药品商品名/规格** | — | — | 【已验证】README 与建表语句（`company_name/legal_representative/business_scope`）；**对本次缺口无用** |
| **13** | **DrugBank** | `https://go.drugbank.com` | **CC BY-NC 4.0（学术非商业）**，商业需授权；再发布受限 | 英文 INN/品牌名/靶点；无中文 | 15k+ 药物 | 中（账号/API key） | 【推断，未逐条核条款】需授权 |
| **14** | **WHODrug Global（UMC）** | `https://who-umc.org` | **商业许可** | 含中文药名（无官方英文名时用拼音）、ATC、商品名 | 全球药物字典 | 高（采购） | 【已验证】中文用户指南 PDF 提及「当中文药品名称缺乏官方英文名时用拼音录入」 |
| **15** | **WHOCC ATC/DDD Index** | `https://atcddd.fhi.no/atc_ddd_index/` | 版权，整表复制/再发布需授权 | 全量 ATC 码+名称+DDD | 约 6,000 个 5 级码 | 商务 | 既有项目结论（`reports/data-depth-20261026.md`） |
| **16** | **KEGG** | `https://www.kegg.jp/kegg/legal.html` | 学术订阅/商业授权；再发布受限 | 药物/通路；无中文商品名 | — | 中 | 【推断】需授权 |

---

## 3. 对三个缺口的结论

### 3.1 CN 1,683 uncertain + 38 no_english

**能靠现成项目补吗？能，但不是「下载即用」。**

1. **首选：国家药典委员会 WHO INN 中文译名公示**（P-List 1–131 分批，附件 PDF 含「表 1/表 2」）：这是官方把 WHO INN 翻成中文通用名的清单，和 CN 的 `cn-*` 中文通用名天然对齐。逐批抓取 + PDF 解析后可建 `中文通用名 → 英文 INN` 表。
   - 覆盖估算：1,683 个 uncertain 中大部分是「INN 译名类」中文名 → **约 50–70% 可映射（840–1,180）**；38 个 no_english 里自研创新药/复方/生物制品可能仍缺【推断】。
   - 许可：政府公开信息，**无开放许可** → 与现有 NHSA 数据同一合规口径：只存「中文名/英文 INN/来源 URL」，不转载原 PDF。
2. **补充：CDE 仿制药参比制剂目录**（94 批，表头含中文通用名+英文名+规格+持证商）：覆盖已上市原研/参比，量比药典委小，但字段已验证、和现有产品更容易对上。页面 JS 渲染（GET 202）→ 需要浏览器或已知附件 URL，接入成本中等。
3. **不建议**：NMPA_Scraper（抓的是企业许可信息，不是药品）、CMeKG（中医图谱）、WHODrug（商业）、继续纯人工（1,683 条人工不现实）。
4. **一次性最优解（需授权）**：WHO MedNet INN 数据库—中文 INN 名称可直接批量检索；免费但需会员注册+同意条款，且无公开批量导出 API，需要先确认 ToS 是否允许本地缓存。

### 3.2 ES/MX 674 no_english + 159 uncertain

1. **首选：WHO INN 公开清单的西班牙语列（DCI Recomendada）**：List 94 已实测表头「Latin, English, French, Spanish」，PDF 免费；把 94 份清单解析成 `Spanish INN ↔ English INN` 字典，可直接服务 `mx-es-*`/ES 西语名。
   - 覆盖估算：674 no_english 中约 30–50% 是标准西语 INN 写法 → **约 200–340 条**；159 uncertain 里也有一部分能靠「西语名→英文 INN→库内已有成分」收敛【推断】。
   - 许可：WHO 版权 **CC BY-NC-SA 3.0 IGO**（署名、非商业、相同方式共享）；本站为公开非商业信息站，可接受，但需在 About 页署名并注明许可。
2. **补充：Wikidata 西语标签/别名**（CC0，已接入 109 条合并）：剩余可再扫 altLabel（本次 ES 任务用的是 label，未用 altLabel 全量）。
3. **剩余**：墨西哥本地商品名/本地药（如 `mx-es-` 里的本地拼写、生物制品），WHO 清单也没有 → **必须人工或商业库**；不建议再投入。

### 3.3 ATC 缺口 6,903

- **不是「6,903 个药物缺 ATC」，而是「6,903 个 substance 里 4,094 个不是 INN 药物实体」。**
- 2,809 个「标准 INN 形态 + 西方市场有产品」的成分上抽样 15 个：**ChEMBL 有分子 4、带 ATC 1；RxNav ATC 命中 3** → 按比例外推 **约 190（ChEMBL）/560（RxNav）**，并集估计 **200–600 个成分（占缺口 3–9%）**【推断，样本小】。
- 组合方案：ChEMBL（离线 dump，批量匹配 pref_name）+ RxNav（单名补漏，免费）+ DrugCentral（补 ChEMBL 未覆盖的 INN），可实现上述 200–600。
- **不要指望**：Wikidata 已用尽（+594 后剩余名字都不在 Wikidata）；WHOCC 全量需授权；4,094 个非 INN 实体任何 ATC 项目都补不了。
- 建议同时改数据模型：给 `substance` 加「实体类型」（drug / botanical / biological / supplement / device-material），把这 4,094 个标出来，ATC 覆盖率分母只算 drug，指标才真实。

---

## 4. 3 个「立刻可用」 vs 3 个「需授权」

### ✅ 立刻可用（今天就能接）

1. **ChEMBL（EBI）** — CC BY-SA 4.0，可公开再发布（署名+相同方式共享）。
   - 用途：ATC 补充（INN→ATC classification）、INN 归一同义名。
   - 接入：`chembl-downloader` 拉 SQLite（或 REST 单条）；`molecule.pref_name` join `molecule_atc_classification/atc_class`；离线 join 到 `substance.inn_en`。
   - 验证：REST 已通，`metformin` 返回 `A10BA02`。
   - 风险：CC BY-SA 的 share-alike 会「传染」衍生映射表（编译产物需 CC BY-SA）；务必在 About 页标注。
2. **RxNav / RxClass（NLM，免费无 key）** — ATC 补漏 + 英文名归一。
   - 接入：`/REST/rxclass/class/byDrugName.json?drugName=…&relaSource=ATC`，逐名缓存（~2,800 个候选名 ×1 次 ≈ 几分钟）。
   - 风险：API 是 NLM 公有领域名称，但 **ATC 码是 WHOCC 第三方内容**；对外展示 ATC 时需注明来源/风险，或只用它做内部对齐、对外展示改走 ChEMBL（CC BY-SA 已覆盖同类内容）。
3. **WHO INN 公开清单（L/EN/FR/ES）+ 国家药典委员会 INN 中文译名公示** — 名称映射主力。
   - 接入：PDF→文本（pymupdf 已在 `.pylibs`）→ 解析「Latin/English/French/Spanish」四列 → `es→en` 字典；药典委公示 PDF 解析「中文通用名/INN」→ `zh→en` 字典。
   - 许可：WHO CC BY-NC-SA 3.0 IGO（署名+非商业+相同方式共享）；药典委公示为政府公开信息（事实+链接）。**两者都不是「开放许可」，发布时必须只存事实字段并注出处。**

> 附加可用：**DrugCentral**（CC BY-SA 4.0，dump 里含 ATC/INN/CAS），作为 ChEMBL 的备份；接入成本中（PostgreSQL+RDKit）。

### 🔒 需授权 / 需注册

1. **WHO MedNet INN 数据库**（`extranet.who.int/soinn/`）— 唯一同时给「中文/西语/俄语 INN 名称 + ATC」的来源；免费但**需会员注册+同意 WHO 条款**，无公开批量 API → **联系 WHO INN Programme 确认 ToS 后**可用；一旦拿到，CN+ES+ATC 三块同时受益（本清单里覆盖最大）。
2. **RxNorm 全量 release / UMLS**（`nlm.nih.gov/research/umls/`）— 免费 UMLS 账号 + 第三方 ATC SRL 限制；只能在 UMLS 条款内用，不建议作为公开站数据源。
3. **DrugBank / WHODrug Global / KEGG / 商业库（药智、摩熵、丁香园）/ 《中国药品通用名称》2024 版** — 需付费或非商业学术许可；其中 **WHODrug 有中文名（无英文名用拼音）**，是 CN 商品名/通用名的商业级兜底。

---

## 5. 插件 / GitHub 工具核查结果

- **DSH 插件市场**：两个已配置索引（`dshopen.org/index.json`、`dsh-plugin-catalog`）按 `drug/medicine/translate/药品/翻译` 查询 **均 0 条**；当前 profile 已装 208 个插件全是 DSH 基础设施，**没有药名/翻译类插件** → 无现成插件可用。
- **GitHub 工具**：
  - `chembl-downloader`（PyPI，Zenodo）— 可复现下载/查询 ChEMBL，**可直接用于 ETL**。✅
  - `NMPA_Scraper` — 抓的是企业生产许可信息，**不是药品商品名**；数据再发布许可不明。❌
  - `CMeKG` — 中医知识图谱，非 INN 映射。❌
  - 未发现「中文药名→INN」的现成开源工具；同类需求都被商业库（WHODrug/药智）占据。
- **结论**：没有「装个插件就搞定」的路径；最接近的是 ChEMBL/RxNav 两个 API + WHO/药典委 PDF 解析（属于「开源项目/公开数据」而非插件）。

---

## 6. 建议的接入步骤（按优先级）

### P0（本周，许可干净，1–2 天）
1. **ChEMBL 离线 dump** → `data/raw/chembl/`（`chembl-downloader`，CC BY-SA 4.0）。
   - `molecule.pref_name` 归一后 join `substance.inn_en`；取 `molecule_atc_classification` 的 ATC；
   - 先 dry-run：统计命中数、与现有 ATC 冲突数（冲突不写）；
   - 写 `substance.atc`（只补空），`source=chembl`，报告里注 CC BY-SA + share-alike。
2. **RxNav 补漏**（可选，与 ChEMBL 并集）：对 ChEMBL 未命中的 ~2,800 个候选名逐个查 `RxClass`（缓存 `data/raw/rxnav/`），只补空；对外展示注明「ATC 来源含 WHOCC 派生」。
3. **ATC 缺口分类**（同一 PR）：给 `substance` 加 `entity_type`（drug/botanical/biological/supplement/device-material），把 4,094 个非 INN 实体标出；覆盖率指标改为「drug 成分 ATC 覆盖率」。

### P1（1–2 周，名称映射）
4. **WHO INN 清单解析**：下载 Recommended Lists（1–94，公开 PDF）→ 解析四语列 → `data/raw/who_inn/es_en.csv`、`fr_en.csv`；先只用于 ES/MX 的 `mergeable` 候选，人工抽验 10% 后再 apply。
5. **国家药典委员会 INN 中文译名公示**：抓 P-List 1–131 公示页与附件 PDF → `zh→en` 字典；与 `cn-*` 的 1,683 uncertain 对齐，跑 `merge_cn_substances.py` 同款 dry-run，人工抽验后 apply。
6. **CDE 参比制剂目录**（与 5 互补）：94 批通告，解析「通用名/英文名/规格/持证商」，用于高价值原研药的核对。

### P2（需商务/授权）
7. **WHO MedNet 会员**：向 WHO INN Programme 发邮件（`innprogramme@who.int`）确认：中文/西语 INN 名称的本地缓存与再发布条款、是否有批量导出 → 若允许，这是「一次补三块」的最优解。
8. WHODrug/药智等商业库：只有在 P0/P1 后 CN 商品名/名称仍不达标时才考虑采购。

---

## 7. 证据索引（`.tmp/opensource/`）

| 文件 | 内容 |
|---|---|
| `gap_check.out.txt` / `gap2.py` 输出 | DB 缺口基线（substance/ATC/CN/ES 数字） |
| `coverage_sample2.out.txt` / `coverage_sample2.json` | **精准抽样**：2,809 个 INN-like 缺 ATC 成分抽 15 个 → ChEMBL 分子 4/ATC 1；RxNav ATC 3 |
| `api_probe.py` / `api_probe.out.txt` | RxNav/RxClass、ChEMBL、Wikidata REST 可达性（200 + 响应片段） |
| `who_drugcentral_probe.py` / `who_dc.out.txt` | **WHO INN List 94 PDF 实测**（4.26 MB / 252 页；表头 Latin/English/French/Spanish；前 30 页 CJK=0）；DrugCentral FDA/PMDA CSV（无日文名） |
| `probe_sources2.py` / `probe_sources2.out.txt` | MeSH FTP `mtms` 目录存在（翻译文件）；CDE 页面 JS 渲染（GET 202）；ChEMBL 下载页；WHO 版权 CC BY-NC-SA 3.0 IGO |
| `who_inn_rl94.pdf` | WHO INN 推荐清单 94（用于复核） |
| `FDA_Approved.csv` / `PMDA_Approved.csv` | DrugCentral 批准药 CSV（2,331/435 行，英文名） |
| 本报告引用的许可证页 | RxNorm ToS、WHO 版权页、Open Targets licence、DrugCentral privacy、ChEMBL downloads、NMPA_Scraper README |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\opensource\gap_check.py
& $py .tmp\opensource\coverage_sample2.py
& $py .tmp\opensource\who_drugcentral_probe.py
& $py .tmp\opensource\probe_sources2.py
```

---

## 8. 限制与风险

1. **ATC 抽样样本小**（15 个），外推区间很宽（200–600）；正式接入前应扩大到 100 个抽验，并把「非 INN 实体」先剔除再算覆盖率。
2. **WHO 内容许可**是 CC BY-NC-SA 3.0 IGO：非商业+署名+相同方式共享；本站若保持非商业公开信息定位可用，但「相同方式共享」意味着基于 WHO 清单的映射表也要以同许可发布——需 Lead 拍板是否接受。
3. **ChEMBL/DrugCentral 的 CC BY-SA** 同样有 share-alike：写进库的 ATC 映射属于衍生数据库，需在 About 页声明并以 CC BY-SA 提供该映射的导出或链接。
4. **RxNorm ATC 的第三方权利**：RxNorm 全量需 UMLS 许可，ATC 属 WHO 第三方内容；对外站建议只用 ChEMBL 派生 ATC，RxNav 仅用于内部补漏/交叉验证。
5. **药典委公示/参比目录**：无开放许可，只能存事实字段+链接；PDF 分批、格式可能变化，需要解析与行数漂移告警。
6. 本轮未验证 WP/MedNet 是否有批量导出 API（需登录后才能确认），也未验证 WHODrug 报价。

---

_本报告由并行子智能体 data-depth 生成；调研过程只读，未写 `data/drugs.db`，未跑 git / 发布 / `site/build.py`。_
