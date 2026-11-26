# STR1 化学结构图：许可 + 覆盖率 + 体积可行性评估

日期：2026-11-26（北京）｜执行：data-scout（task-11）｜需求来源：用户 2026-11-26 12:35「能不能去 pubmed 之类的把药物的结构图什么的找过来」+ 12:45 补充口径「产品页放链接去成分页」
边界：**只读 web 抓取 + 探针脚本（`.tmp/`）+ 写本报告与 `docs/许可清单.md`**；未写库、未 build、未发布、未 commit、未绕 WAF、未登录、未付费。

## 0. 结论先行

| 问题 | 结论 |
|---|---|
| 许可：能不能把结构图**下载到本站服务器**再发布？ | **🟡 条件性可用**（不是 🔴）——PubChem 属美国政府作品（公有领域），NCBI 明写「no restrictions on the use or distribution」；但「PubChem」被 NCBI 单独点名可能含第三方权利。**4 条硬条件必须同时满足**：① 每张图可见署名 + 链回 `pubchem.ncbi.nlm.nih.gov/compound/<CID>`；② 站点（About/许可页）明示 NCBI Disclaimer & Copyright notice（NCBI 脚本指南要求「must be evident to users of your service」）；③ 不整库镜像、只取本站成分页用得到的图；④ 页面显式声明「PubChem/NLM 不背书本站」 |
| 覆盖率 | 随机 300 个 `inn_en`（seed `20261126`）：**97 命中 = 32.3%**。但缺的一半基本**不是小分子**（草药/提取物/疫苗/单抗/酶/顺势药/西语变体/复方）→ 在「有 ATC 的真药」子集里命中 **48.4%（62/128）**，外推 **≈3,300 张**；在「ASCII 小分子面相」子集 **56.4%**，外推 ≈5,100 张。**规划按 3,300–5,100 张（取 5,000 做容量估算）** |
| 体积 | 实测 50 张：**300×300 平均 2,865 B**（min 252 / max 5,448）；**200×200 平均 1,784 B**。按 5,000 张算 **+13.7 MB**（300px）/ **+8.5 MB**（200px）；最坏全量 16,550 张 = 45.2 MB / 28.2 MB。相对现 `site/dist`（362,112 文件 / 3,282.9 MB）= **+0.42% 体积 / +1.4% 文件数** |
| 推荐尺寸 | **300×300**（PubChem 官方 `image_size=large`），页面用 CSS 限宽 ≈180 px 显示。理由：官方档位、视网膜屏不糊、单图仅 2.9 KB，比 200px 只多 5.3 MB，取舍不值得为省 5 MB 牺牲清晰度 |
| 显示位置 | **只在成分页 `drug/<inn>.html` 放图**；**产品页不改**（现有产品页已有到成分页的链接 ×2：成分名 + 「Ingredient page」→ 用户 12:45 口径已成立、**零改动**，避免重传 144,000 页 ≈ +14.4 万 PUT） |
| 需人拍板 | **1 条**：PubChem `robots.txt` 对 `/rest/pug/` 全组 `Disallow`（2026-10-29.1）而官方 usage policy 又明示「≤5 req/s 可用」——取图通道按「API 客户端」口径走，还是改走 FTP 批量？见 §1.4 |

## 1. 许可评估（逐条原文 + URL + 抓取日期）

抓取时间：2026-11-26 12:0x–12:3x 北京时间（与探针同一时段），单次 GET、无登录、无 cookie。

### 1.1 PubChem 官方使用政策（**速率与取数合法性**）

URL：<https://pubchem.ncbi.nlm.nih.gov/docs/programmatic-access>（HTTP 200，页面标注 `Last updated: May 19, 2025`；注：该站文档是 SPA，纯文本抓取只得到标题，本段原文用浏览器渲染后取 `innerText`）

> USAGE POLICY: Please note that PubChem web services run on a limited pool of servers shared by all PubChem users. We ask that any user, application, or organization **not make more than 5 requests per second**, in order to avoid overloading these servers. … **We cannot offer API keys or whitelists to exceed these limits.** If you have a large data set that you need to compute with, please contact us for help on optimizing your task, as there are likely more efficient ways to approach bulk access. See also the help page for bulk data downloads.
>
> 503 HTTP STATUS CODE: … this status code may be returned when the server is temporarily unable to service your request … (Please try again later.)

→ 判定：**官方明确允许编程访问**，限速 ≤5 req/s，**没有 Key/白名单**，大批量建议走 bulk 下载。

### 1.2 NCBI 政策页（**版权 + 再发布**）

URL：<https://www.ncbi.nlm.nih.gov/home/about/policies/>（HTTP 200）

> **Copyright Status of Webpages**：Information that is created by or for the US government on this site is **within the public domain**. Public domain information on the National Library of Medicine (NLM) Web pages may be **freely distributed and copied**. However, it is requested that in any subsequent use of this work, **NLM be given appropriate acknowledgment**.
> NOTE: This site contains resources which incorporate material contributed or licensed by individuals, companies, or organizations that may be protected by U.S. and foreign copyright laws. … **and PubChem.**
>
> **Molecular Data Usage**：… **NCBI itself places no restrictions on the use or distribution of the data contained therein.** Nor do we accept data when the submitter has requested restrictions on reuse or redistribution. However, some submitters … may claim patent, copyright, or other intellectual property rights … **NCBI cannot provide comment or unrestricted permission** concerning the use, copying, or distribution of the information contained in the molecular databases.
>
> **Guidelines for Scripting Calls**：… **Make no more than 3 requests every 1 second.** Use the URL parameter email, and tool … **NCBI's Disclaimer and Copyright notice must be evident to users of your service.**

→ 判定：**结构图可再发布**（政府作品 + NLM 请求署名），**但**：① NCBI 只是「不施加限制」，**不等于代第三方给授权**；② 脚本调用更保守的旧口径是 ≤3 req/s（我们按 PubChem 的 5 但自降到 4.5，见 §2）；③ **Disclaimer 必须在页面上对用户可见**（这是硬要求，不只是客气话）。

### 1.3 引用规范（**署名的具体写法**）

URL：<https://pubchem.ncbi.nlm.nih.gov/docs/citation-guidelines>（HTTP 200，`Last updated: July 7, 2026`）

> Primary PubChem Citation … **Kim S, Chen J, Cheng T, et al. PubChem 2025 update. Nucleic Acids Res. 2025;53(D1):D1516-D1525. doi:10.1093/nar/gkae1059**
> If you use data or services from PubChem, proper citation helps readers locate the original source … Some records in PubChem are directly assembled from the contributing organization with attribution provided on the record. Other records, like Compound records, contain **derived data in addition to collected annotations with attribution**.

→ 采纳：About/许可页写 **「PubChem 2025 update, Nucleic Acids Res. doi:10.1093/nar/gkae1059」+ NLM 链接**；页面级写 `CID` 链接（可逐条复核）。

### 1.4 robots.txt（**唯一需要人拍板的地方**）

URL：<https://pubchem.ncbi.nlm.nih.gov/robots.txt>（HTTP 200，头部标注 `Version: 2026-10-29.1`）

> \# These are voluntary crawler instructions, **not authentication, a universal prohibition on reuse**, or a guarantee against training by unlisted agents.
> User-agent: * / `Crawl-delay: 5` / … **`Disallow: /rest/pug/`** … `Disallow: /rest/rdf`

→ 说明：**`/rest/pug/`（我们取 CID 与 PNG 的接口）对所有 UA 组都在 Disallow 里**；同文件的注释又自己声明这些条款「不是复用禁令」；而 §1.1 的官方 usage policy 正在鼓励≤5 req/s 的编程访问。三条信号并存，**这属于对外合规口径，不由我拍板**。

两条路（成本对比）：

| 方案 | 做法 | 成本 / 风险 |
|---|---|---|
| **A. PUG-REST 取图（推荐 v1）** | 单进程、≤4.5 req/s、唯一 UA（含站点域名 + 联系邮箱）、404 不重试、429/503 退避。**只取本站成分页需要的图，不做全库镜像** | 5,000 次 GET ≈ 22 分钟（按实测 0.44 s/次）；合规依据 = usage policy + robots 自述「非复用禁令」；**需 Lead 认可这条口径** |
| **B. FTP 批量（备选 v2）** | 下载 `Compound` 2D SDF 全量 → 本地渲染 PNG | 全量 SDF 数十 GB + 需要渲染器（RDKit，MIT）→ 引入新依赖与磁盘/时间成本，**本轮不推荐** |

### 1.5 图片本身：能否落盘 + 再发布（结论 🟡 + 4 条条件）

| 判定项 | 结论 |
|---|---|
| 2D 结构图是否「可版权作品」 | **弱**：结构式是化学事实的表达，PubChem 自己也把它作为公开数据提供；但为避免争议**不主张拥有版权**，按「事实 + 署名」处理 |
| 能不能本地托管（`assets/…png`）? | **可以（条件性）**——依据 §1.2「freely distributed and copied」+「no restrictions on use or distribution」 |
| 必须的署名与链接 | 图上/图下：`PubChem (NIH/NLM) · CID <cid>`（可见文本，非仅 `alt`）+ 链回 `https://pubchem.ncbi.nlm.nih.gov/compound/<cid>`；站点级：NCBI Disclaimer + 引用规范（§1.3）；**不得写「授权 / 合作 / 认可」字样**（沿用 TGA 的既有口径） |
| 「图片由 PubChem 渲染（CACTVS/OPSIN）」要不要额外声明？ | **无法确认**：本轮抓取的 PubChem 文档（programmatic-access / pug-rest / citation-guidelines）**未检索到**渲染器名称，PNG 也未带工具标识。→ **文案只写「Image: PubChem (NIH/NLM)」，不写渲染器名**（写错反而制造风险）。若要写，先向 PubChem 问 |
| 附加约束 | ① **不做整库镜像/不转售**；② 只对 `substance` 里有的成分取图；③ 非小分子（单抗/疫苗/草药）**没有结构图就不放图**，不造图；④ 若将来商业化（广告/收费）按 §1 原则重评 |

### 1.6 备选源（各一句结论）

| 备选 | 结论 | 证据 |
|---|---|---|
| **Wikimedia Commons** | 🟡 覆盖不稳：图来自不同作者/不同许可（CC0 / CC BY / CC BY-SA 混杂），要逐图读许可；对 16,550 个成分无法批量保证。**可作补图通道，不作主源** | Commons 许可政策（逐文件许可）与 Wikidata 化学结构图片属性（属性号 P117，**本轮未复核**） |
| **ChEMBL（EMBL-EBI）** | 🟡 **CC BY-SA**：署名 + share-alike 会传染到派生库，且带 SA 的图片会牵扯本站「图片+映射」的再许可；我们已有 ATC 计划受同一约束。**不作图片主源**。⚠️ **口径纠正**：官方 About 页现写「ChEMBL data is made available on a **Creative Commons Attribution-Share Alike 3.0 Unported License**」，本仓 `docs/许可清单.md` §1/§3 一直写 **4.0** → 建议下次统一更正为 3.0（本次不动历史行） | <https://chembl.gitbook.io/chembl-interface-documentation/about.md>（2026-11-26 抓取，HTTP 200） |
| **DrugBank** | 🔴 **明确不用**：数据集为 **CC BY-NC 4.0**（署名 + **非商业**），学术下载 2026-11-26 实测页面写「All Academic downloads are temporarily paused」，商业需付费授权 → 与本站「公开免费 + 未来可能商业化」冲突 | <https://go.drugbank.com/releases/latest>（HTTP 200，5.1.22，2026-06-27 发布） |
| **RDKit 本地渲染（自建）** | ⚪ 备选 v2：需先拿到 SMILES/SDF（还是 PubChem/其他源），只换渲染器不解决许可问题，还多一个依赖 → **v1 不做** | — |

### 1.7 许可小结

- **可用，但标 🟡**（条件性），与 `docs/许可清单.md` §1 的 🟡 定义一致：可以展示/托管，**必须署名 + 链回 + 明示免责**；不得声称授权。
- 已写入 `docs/许可清单.md` **§2.17**（新增节）+ 待办 1 条。

## 2. 覆盖率抽样（可复现）

### 2.1 方法

- 样本：`data/drugs.db` 的 `substance.inn_en`（16,550 行，`inn_en` 唯一），`random.Random(20261126).sample(..., 300)` 后**按字母排序**再看结果（排序只为便于复查，不改变抽样）。
- 请求：`GET https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/<urlquote(INN)>/cids/JSON`，`User-Agent: drugcrossref-STR1-probe/0.1 (…; contact via drugcrossref.com)`，每次请求后 `sleep 0.22 s`（**≈4.5 req/s，低于官方 5 上限**），429/503 退避重试 3 次。
- 探针脚本：`.tmp/str1_probe.py`（一次性探针，不入库、不进 `run_all.py`）；缓存：`data/raw/pubchem-probe/cid-probe-300.jsonl`（每行一条，含 `status/cid/elapsed_s/bytes`）。

### 2.2 结果

| 口径 | 样本 | 命中 | 命中率 | 备注 |
|---|---|---|---|---|
| **全部 `inn_en`** | 300 | **97** | **32.3%** | 只有 200/404 两种状态，**全程 0 次 429/503**（说明 4.5 req/s 很安全） |
| 有 ATC 的「真药」子集 | 128（该子集在 300 里占 42.7%；全库 `substance` 有 ATC 者 **6,865 / 16,550 = 41.5%**） | 62 | **48.4%** | 外推 **≈3,325 张** |
| ASCII + 无数字 + 非草药/提取物/顺势关键词 | 165 | 93 | **56.4%** | 外推 ≈5,130 张（上限参考） |
| 其中「生物制品后缀」（-mab/-cept/-ase/-cog/-tide…） | 7 | 1 | 14% | 印证：**生物制品没有 2D 结构**，不是匹配失败 |

> 结论：**不要按 16,550 估容量**。STR1 的真实规模是 **3,300–5,100 张**（规划取 5,000）。

### 2.3 失败分类（203 个 404 的构成，附真实样本）

| 类别 | 数量（占 300） | 示例（原文照抄） |
|---|---|---|
| 草药 / 植物 / 动物组织 | 63 | `Arnicae`、`Cocillana`、`Betula Pendula Wood`、`Dog Rose Without Achenes`、`Beef Heart`、`Armadillidium Vulgare Whole` |
| 提取物 / 过敏原 / 顺势药 | 21 | `Allergen extract from sweet vernal grass`、`Allium Cepa 3 C`、`Calcii Fluoridum Dilutio Homeopathica` |
| 生物制品（单抗/酶/凝血因子/疫苗/肝素类） | 39 | `Atezolizumab`、`Crizanlizumab`、`Catridecacog`、`Danaparoid`、`Crofelemer`、`Hepatitis A Vaccine`、`Tetanus Toxoid Antigen` |
| 非英文名 / 拼写变体 / 本地俗名 | 43 | `Antipoliomielítica Inactivada`、`Cipionato`、`Clofenamina`、`Oxibuprocaína`、`Diyodohidroxiquinolei Na` |
| 复方 / 盐 / 复合物 | 12 | `Co-Methiamol`、`Doxorubicin Citrate Complex`、`Dl-Alpha-Tocopheryl Acid Succinate`、`Sodium Tetradecyl` |
| 数据脏（**我们自己的**） | 9 | `Equivalent: Aloysia Citrodora`、`Equivalent: Bacopa Monnieri`、`.Mu. Conotoxin G Iiic`（μ 被写成 `.Mu.`）、`Condensed Glucose` |

> **两个可立即用的副产品（不属 STR1，但值得开单）**：① `substance.inn_en` 里混着 `Equivalent: …` 前缀 与 `.Mu.` 这类编码残留 —— 建议列入数据体检；② 43 个非英文名说明**英文名归一化有缺口**，会影响任何「按英文名匹配外部源」的工作（含 STR1）。
> **反面确认**：对 `Atezolizumab` / `Crofelemer` / `Danaparoid` 用 PubChem **autocomplete 接口**会给「看起来像」的无关结果（如 `Sacituzumab govitecan`、`Cashmeran`）→ **绝不能用模糊匹配补缺口**（会把结构图配错药，触碰 §1 底线）。

### 2.4 耗时

| 指标 | 实测 / 推算 |
|---|---|
| 单次 CID 查询平均 | **0.220 s**（p95 明显慢的在 0.3–1.4 s，最大 1.435 s） |
| 300 次（含 0.22 s 间隔） | **132 s**（≈2.27 req/s 有效速率） |
| 全量 16,550 次 | ≈ **7,280 s = 2.0 小时** |
| 只做 6,865 个有 ATC 的 | ≈ **50 分钟** |
| 5,000 张图（每张 1 次 GET） | ≈ **37 分钟** |

→ 结论：**单进程一夜跑得完**，不需要并发；并发只会把限速风险抬高，收益为零。

## 3. 体积与推荐尺寸

### 3.1 实测（命中里取 50 个，300×300 与 200×200 各拉一次，共 100 次请求）

| 尺寸 | n | 平均 | 最小 | 最大 | 50 张合计 | 尺寸校验 |
|---|---|---|---|---|---|---|
| **300×300** | 50 | **2,865 B** | 252 B | 5,448 B | 143,265 B | PNG 魔数 `89504e47…` ✔，IHDR 实测 300×300 ✔ |
| **200×200** | 50 | **1,784 B** | 216 B | 3,300 B | 89,211 B | IHDR 实测 200×200 ✔ |

单图 1.5–5 KB 量级，**和 Lead 初判（1.6–4.1 KB）一致**；分布比预估更集中。

### 3.2 推算

| 规模 | 300×300 | 200×200 |
|---|---|---|
| **5,000 张（推荐规划值）** | **13.7 MB** | 8.5 MB |
| 3,325 张（ATC 子集外推） | 9.1 MB | 5.7 MB |
| 5,130 张（小分子面上限） | 14.0 MB | 8.7 MB |
| 16,550 张（最坏全量） | 45.2 MB | 28.2 MB |

现 `site/dist`：**362,112 文件 / 3,282.9 MB**（2026-11-26 12:5x 实测）→ 5,000 张 300px = **+0.42% 体积、+1.4% 文件数**；发布侧一次性 **≈5,000 PUT**（远低于「单次 >50,000 需 Lead 批准」的门槛，但仍是当月额度的一部分，要记进发布报告的 PUT 计数）。

### 3.3 推荐

- **取 300×300**（官方 `image_size=large`；也可写 `image_size=300x300` 显式指定），**页面 HTML 用 `width="180" height="180"` + CSS 限宽**显示。
- 理由：① 官方档位，不依赖「任意尺寸」行为；② 视网膜屏 2x 需要 ≥360 px 才够锐，300 已接近，200 会糊；③ 差 5.2 MB，相对于 3.2 GB 的 dist 可忽略；④ 未来做 OG 分享卡/大图查看时不用重抓。
- **不存 SVG/SDF**（体积与解析成本高，v1 不需要）。

## 4. 接入方案（**只给设计，不写实现**）

### 4.1 表结构建议（`substance_structure`）

```sql
-- 成分级结构图：一个活性成分（INN）最多一张图；与产品无关
CREATE TABLE IF NOT EXISTS substance_structure (
    substance_id  TEXT PRIMARY KEY REFERENCES substance(substance_id),
    source        TEXT NOT NULL DEFAULT 'pubchem',   -- 目前仅 pubchem
    source_id     TEXT NOT NULL,                     -- PubChem CID（存文本，便于拼 URL / grep）
    image_path    TEXT,                              -- 本地相对路径（如 assets/structure/2244.png）；NULL = 未取到
    image_bytes   INTEGER,
    image_w       INTEGER,
    image_h       INTEGER,
    image_url     TEXT,                              -- 官方原图 URL（可复核；不对外发布原图 URL 也行）
    license       TEXT NOT NULL,                     -- 'PubChem/NLM — 条件性可用（见 docs/许可清单.md §2.17）'
    license_url   TEXT NOT NULL DEFAULT 'https://www.ncbi.nlm.nih.gov/home/about/policies/',
    match_method  TEXT,                              -- 'name-exact'（v1 只用这一种）
    fetched_at    TEXT,                              -- UTC ISO8601
    note          TEXT                               -- 失败原因 / 人工复核备注
);
CREATE INDEX IF NOT EXISTS idx_substance_structure_src ON substance_structure(source, source_id);
```

要点：
- **主键挂 `substance_id`**（不是 `inn_en`、不是产品）——符合「结构属成分、不属商品」的口径；盐/复方共用同一张（见 §4.3 文案）。
- `image_path` 留空表示「查了但没图」，与「还没查」区分：**没查 = 无行**，查了没图 = 有行 + `image_path IS NULL` + `note`。这样重跑可增量。
- 表进 `db/schema.sql` 与 `db/init_db.py` 幂等迁移（**写库工位**做）；只读查询一律 `mode=ro`。

### 4.2 `etl/` 脚本要点（建议 `etl/structures/pubchem.py`）

| 关注点 | 建议 |
|---|---|
| 入口 | `--plan`（只算缺口，不请求）/ `--fetch`（真抓）/ `--limit N` / `--only-atc` / `--incremental`（跳过已有行的） |
| 限速 | **单进程串行，每次请求后 `sleep 0.22`**（≈4.5 req/s）；不做并发 |
| 身份 | 固定 `User-Agent`：`drugcrossref-structure/1.0 (+https://drugcrossref.com/; contact@…)`；**不伪装浏览器** |
| 失败 | 404 → 记 miss（**不重试**，见 §2.3 反面确认）；429/503/超时 → 指数退避 3 次后记 miss；单请求超时 30 s（PubChem 文档写明服务端 30 s 上限） |
| 缓存 | 原始 JSON/PNG 落 `data/raw/pubchem-probe/`（已有）；**可再发布的小快照**才进 `data/sources/structures/` 并在许可清单登记 |
| 图片落盘 | 源文件 `data/sources/structures/<cid>.png`（**不要直接写 `site/dist`**），由 `site/build.py` 负责复制成 `dist/assets/structure/<cid>.png`（稳定名，符合增量发布契约：长尾页不引 hashed 名） |
| 增量 | 按 `substance_id` upsert；失败清单 `data/raw/pubchem-probe/miss.jsonl` 供人工/下一轮 |
| 计数 | 输出「命中 / 404 / 无图 / 已跳过」四类计数，**写进覆盖页**（同 README/About 口径纪律） |
| 不做的 | 不抓 SDF/3D、不存 InChI、不抓说明书/安全数据、不做模糊匹配 |

### 4.3 显示位置（**成分页放图，产品页只给入口**）

| 页面 | 做什么 | 理由 |
|---|---|---|
| `drug/<inn>.html`（成分页） | **顶部信息卡内**放 300×300 图（显示 180 px），图下 1 行：`PubChem (NIH/NLM) · CID <cid>`（链回 PubChem）+ 免责句 | 结构属成分级事实；成分页是「一个药到底是什么」的页面，图在这里信息增益最大 |
| `product/<pid>.html`（产品页） | **零改动**。现已有到成分页的链接 **×2**（成分名 + 「Ingredient page」），实测 `product/AU-10001J-xifaxan-56fd56.html` → `../drug/rifaximin.html` | ① 用户 12:45 口径已成立；② 产品页 144,000 页，改模板 = 全量重传 ≈ +14.4 万 PUT，**不值当**；③ 长尾页受「不写版本号/不引 hashed 资源」约束，动模板风险大 |
| 其它 | 不放首页、不放搜索结果列表（首屏体积与条目密度会被拖累） | 首屏守卫（AFCR / 首屏条目 / chrome 占比）不该为一张图让步 |

**必须在图上/图下写清的一句**（同时满足「不给用药建议」与「盐/复方差异」）：

> 图中是该活性成分（INN）的**通用化学结构**，**不代表任何具体商品形态**——同一成分在不同国家可能以不同盐型、复方或规格上市，结构与含量请以药品说明书/包装为准。

（英文版同理，见 §4.4。）

### 4.4 九语署名文案（建议）

> 站点语言集：`en / es / zh / zh-Hant / fr / ko / ja / cs / lv`（`site/build.py` 的 `LANGS`，fr 目前 enabled=false 但词条照写）。
> 变量：`{cid}`；链接：`image` → `https://pubchem.ncbi.nlm.nih.gov/compound/{cid}`；`disclaimer` → NCBI policies 页。

| 语言 | 文案 |
|---|---|
| en | Structure: **PubChem (NIH/NLM)**, CID {cid}. Generic structure of the active ingredient — **not a specific product form** (salt, combination, strength may differ). PubChem/NLM does not endorse this site. |
| es | Estructura: **PubChem (NIH/NLM)**, CID {cid}. Estructura genérica del principio activo — **no representa una forma comercial concreta** (sal, combinación o dosis pueden variar). PubChem/NLM no respalda este sitio. |
| zh | 结构式：**PubChem（美国国家医学图书馆 NLM）**，CID {cid}。图中为该活性成分的通用结构，**不代表任何具体商品形态**（盐型/复方/规格可能不同）；PubChem/NLM 不背书本站。 |
| zh-Hant | 結構式：**PubChem（美國國家醫學圖書館 NLM）**，CID {cid}。圖中為該活性成分的通用結構，**不代表任何具體商品形態**（鹽型／複方／規格可能不同）；PubChem/NLM 不為本站背書。 |
| fr | Structure : **PubChem (NIH/NLM)**, CID {cid}. Structure générique du principe actif — **ne représente pas une forme commerciale précise** (sel, association, dosage peuvent différer). PubChem/NLM n'approuve pas ce site. |
| ko | 구조식: **PubChem(NIH/NLM)**, CID {cid}. 해당 유효성분의 일반 구조이며 **특정 제품 형태를 의미하지 않습니다**(염·복합제·함량이 다를 수 있음). PubChem/NLM은 본 사이트를 보증하지 않습니다. |
| ja | 構造式：**PubChem（NIH/NLM）**、CID {cid}。有効成分の一般構造であり、**特定の商品形態を示すものではありません**（塩・配合・含量が異なる場合があります）。PubChem/NLM は本サイトを推奨するものではありません。 |
| cs | Struktura: **PubChem (NIH/NLM)**, CID {cid}. Obecná struktura účinné látky — **neoznačuje konkrétní obchodní formu** (sůl, kombinace, síla se mohou lišit). PubChem/NLM tento web neschvaluje. |
| lv | Struktūra: **PubChem (NIH/NLM)**, CID {cid}. Aktīvās vielas vispārīga struktūra — **nenorāda uz konkrētu tirdzniecības formu** (sāls, kombinācija, deva var atšķirties). PubChem/NLM šo vietni neapstiprina. |

站点级（About「Data sources and licences」段，九语各 1 段）：**「Structure images: PubChem, NIH/NLM. PubChem 2025 update, Nucleic Acids Res. doi:10.1093/nar/gkae1059. Data are U.S. Government works; NLM requests acknowledgment. NCBI disclaimer: …」+ NCBI policies 链接**（§1.2 的「Disclaimer must be evident」硬要求）。

### 4.5 `verify_live` 建议抽查项（**首版按 WARN，不阻塞发布**）

| 检查名（沿用 `verify_live.py` 命名风格） | 断言 | 级别 |
|---|---|---|
| `structure-asset` | 从抽样的 1 个成分页里找出第一张 `assets/structure/*.png`，HTTP 200 + `content-type: image/png` + 体积 200–20,000 B + `cache-control` 含 `max-age` | WARN → 稳定后升 FAIL |
| `structure-attribution` | 该成分页 HTML 含 `pubchem.ncbi.nlm.nih.gov/compound/` 链接 + 文本含 `PubChem` + 含 `rel="noopener"` | WARN → 升 FAIL |
| `structure-disclaimer-evident` | About 页（或成分页页脚）含 `NCBI` + `policies` 链接 | FAIL（这是 §1.2 的硬要求） |
| `structure-coverage` | 抽 5 个成分页，含图比例 ≥ 40%（提示性，不代表错） | WARN（覆盖天生不全） |

发布侧注意：图片走 `assets/` 单独同步（`sync_r2.ps1` 已有 assets 分支），建议图片给 **`Cache-Control: public, max-age=604800`**（按 CID 命名的不可变资源），**不要**沿用 `max-age=300`；一次性 5,000 PUT 要记进发布报告的「本次 PUT / 当月累计 / 占免费额度 %」。

## 5. 需人拍板 / 建议排期

| # | 事项 | 建议 |
|---|---|---|
| 1 | **robots.txt `/rest/pug/` Disallow vs 官方 usage policy**（§1.4）——取图通道口径 | 建议按「**合规 API 客户端**」走 PUG-REST（≤4.5 req/s、唯一 UA、不做全库镜像），并把这句话写进 `docs/许可清单.md` §2.17；若 Lead/人认为 robots 优先，则 STR1 降级为「**只做链接层**」（成分页给 PubChem 查询链接，不存图）——那样 0 体积、0 PUT，但用户看不到图 |
| 2 | 队列建议（**未改队列**）：STR1 拆三张单 —— ①写库工位（表 + ETL，1 张单）②前端（成分页展示 + 九语，1 张单）③发布（首次 5,000 PUT 窗口，1 张单，需在报告记 PUT） | 由 Lead 决定是否拆 |

## 6. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 探针（300 查 CID + 50×2 拉 PNG；固定种子）
& $py .tmp\str1_probe.py

# 2) 统计（命中率 / 分类 / 体积）
& $py -c "import json,collections,re;rows=[json.loads(l) for l in open('data/raw/pubchem-probe/cid-probe-300.jsonl',encoding='utf-8')];print(len(rows), sum(1 for r in rows if r['cid']))"

# 3) 产物（不入库）
Get-ChildItem data\raw\pubchem-probe | Select-Object Name,Length

# 4) 抽样可复现性
& $py -c "import random,sqlite3;c=sqlite3.connect('file:data/drugs.db?mode=ro',uri=True);n=sorted(r[0] for r in c.execute('SELECT inn_en FROM substance'));s=random.Random(20261126).sample(n,300);print(len(s), s[:3])"

# 5) 目录体积（本轮实测 dist = 362,112 文件 / 3,282.9 MB，约 33 s）
Get-ChildItem site\dist -Recurse -File | Measure-Object -Property Length -Sum | ForEach-Object { "{0} files / {1:N1} MB" -f $_.Count, ($_.Sum/1MB) }
```

## 7. 边界与已知缺口

- **没做**：未写库（`data/drugs.db` 无任何 `substance_structure`）、未 build、未发布、未 commit；未抓 SDF/3D/说明书；未做全量 16,550 次探测（只 300 抽样）。
- **抓取纪律**：全部单次 GET、带 UA、≤4.5 req/s、0 次 429/503；未登录、未付费、未绕 WAF。
- **无法确认的 3 处**：① PubChem PNG 的渲染器（CACTVS/OPSIN）无官方文本 → 文案不写；② Wikimedia Commons 逐图许可未逐一核（只给「不作主源」的判断）；③ Wikidata P117 属性号本轮未复核。
- **口径纠正（建议，未改）**：ChEMBL 官方 About 页写 **CC BY-SA 3.0 Unported**，本仓记 4.0 → 建议下次统一更正。
- **数据副产品（建议另开单）**：`substance.inn_en` 里 `Equivalent: …` 前缀 与 `.Mu.` 编码残留；43/300 抽样名不是规范英文 INN。
