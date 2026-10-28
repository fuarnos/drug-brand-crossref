# 复方-复方跨市场匹配候选（task-59）

> 日期：2026-10-28 ｜ 数据：`data/drugs.db`（**只读**；未写库、未改 `site/build.py`、未跑 git/发布）
> 产物：`data/combo_match_candidates.csv`（5,713 行）、`etl/build_combo_matches.py`、本报告；统计/样例在 `.tmp/combo-match/`。

## 1. 结论

| 指标 | 数值 |
|---|---:|
| 原始复方产品（`product_component` ≥2 行） | **48,886**（任务书写 48,554，DB 已随其它任务更新） |
| 规范化后参与匹配的复方产品 | **34,144**（成分按盐/酯/同义名归一后 ≥2 个不同成分；**14,742** 个产品因「同一成分的盐型/重复行」去重后只剩 1 个成分被排除） |
| 成分集合签名数（复方 identity） | **4,787** |
| 站点现有 combo 页面口径（去重后的原始 substance_id 集合） | 7,947 |
| **exact（同成分集合双边都有）** | **228 个集合 / 11,985 个产品**（产品口径 **35.1%**；集合口径 4.8%） |
| overlap（不同集合但 Jaccard≥0.80） | 8 个集合 / 22 个产品 |
| none（对面市场无同集合/高重叠复方） | 4,551 个集合 / 22,137 个产品（产品口径 64.8%） |
| none 中「主成分在对面市场可找到」（降级可用） | **1,159 个集合（25.5%）**；不可用 3,392 个 |
| 东侧（CN/ES/MX）覆盖 | 东侧集合 **614** 个，其中 228 个有西侧同集合 → **37.1%** |
| 西侧（US/GB/CA/AU）覆盖 | 西侧集合 **4,401** 个，其中 228 个有东侧同集合 → **5.2%** |
| 按市场签名数 | US 2,894 / AU 862 / GB 720 / CA 536 / ES 483 / MX 191 / **CN 27** |

**解读**：跨市场复方匹配的「集合级」命中率不高（228/4,787=4.8%），但**产品级**有 35.1% 落在可匹配的同集合复方上——因为高销量复方（降压/降糖/复方感冒药）产品数集中。CN 侧集合少（27 个签名对应 3,048 个产品），但其中 19 个（11,985 产品中的 CN 部分）能对上西侧（如氯沙坦/缬沙坦/厄贝沙坦+氢氯噻嗪、氨氯地平+缬沙坦/阿托伐他汀、二甲双胍+格列本脲/格列吡嗪/维格列汀、阿莫西林+克拉维酸等）；西侧大量复方是 US OTC/医院专属复方，东侧无对应。

## 2. 方法（`etl/build_combo_matches.py`，可重跑）

1. **成分归一**：取 `product_component → variant → substance.inn_en`，去掉括号、盐/酯/水合物/剂型词（hydrochloride/sodium/sulfate/trihydrate/medoxomil…），再套常见跨市场同义表（`paracetamol→acetaminophen`、`glyburide→glibenclamide`、`clavulanate→clavulanic-acid`、`albuterol→salbutamol`、`ethinyl-estradiol→ethinylestradiol` 等）；
2. **签名**：产品内不同成分 key 排序后 `a|b|c`；同一签名可能来自不同盐型/厂家的多个原始 substance_id 集合（这些对应站点多个 combo 页，见 §4）；
3. **跨市场判定**：东侧 = CN/ES/MX，西侧 = US/GB/CA/AU。
   - `exact`：同一签名在对面区域至少 1 个国家有产品；
   - `overlap`：对面区域存在另一签名，成分集合 Jaccard = |∩|/|∪| **≥ 0.80**（如 5 成分 vs 4 成分差 1 个 → 0.8）；
   - `none`：以上都没有；
4. **签名之外保留**：`form_release`（剂型/释放）、`strength_sig`（该组最常见规格组合）、代表性 `brands`（trade 名，最多 3 个）、`n_products`、`sample_product_id`，供页面展示用（**匹配本身不要求规格/剂型一致**，避免把不同国家常见规格差异误判为不匹配；页面只做身份对应，不给剂量建议）；
5. **降级主成分**：签名内 `ord` 最小的成分（缺失时取排序第一），检查该成分 key 是否出现在对面市场的任意复方里 → `primary_cross_market=yes/no`，作为无同组合时的页面降级依据。

CSV 列（每个「签名 × 国家」一行，共 5,713 行）：
`signature, combo_slug, country, n_products, brands, form_release, strength_sig, match_strength, match_markets, match_products, matched_signatures, overlap_ratio, primary_ingredient, primary_cross_market, sample_product_id`。

## 3. 样例（含任务指定三条）

| 复方 | 集合签名 | 产品数 | 市场 | 匹配 |
|---|---|---:|---|---|
| **二甲双胍 + 格列本脲** | `glibenclamide\|metformin` | 304 | CN, US | **exact**（US 的 glyburide 经同义归一后命中）；CN 274 个（唐柯柠/立将/齐亭…），US 30 个；规格 1.25 mg + 250 mg 起 |
| **阿莫西林 + 克拉维酸** | `amoxicillin\|clavulanic-acid` | 638 | AU, CA, CN, ES, MX, US | **exact**，6 市场全命中 |
| **复方氨酚烷胺** | `acetaminophen\|amantadine` | 695 | CN | **none**：西侧无同成分复方（美国复方感冒药多为 acetaminophen+dextromethorphan/doxylamine 等）；主成分 acetaminophen 在对面市场可用 → 可降级展示 |
| 氯沙坦 + 氢氯噻嗪 | `hydrochlorothiazide\|losartan` | 333 | CA, CN, ES, GB, MX, US | exact |
| 氨氯地平 + 阿托伐他汀 | `amlodipine\|atorvastatin` | 204 | AU, CA, CN, ES, US | exact |
| 二甲双胍 + 维格列汀 | `metformin\|vildagliptin` | 106 | AU, CN, ES, GB, MX | exact（美/加无该复方） |
| 复方氨酚氯丙那敏 | `acetaminophen\|chlorphenamine\|pseudoephedrine` | 774 | CN | none（西侧无同 3 成分组合） |
| overlap 样例 | `…5 成分` vs `…4 成分` | — | CA↔US/ES | Jaccard 0.80（差 1 个成分，仅作「近似组合」提示，不可互换） |

Top exact 集合（按产品数）：阿莫西林+克拉维酸 638、右美沙芬+愈创木酚甘油醚 482、缬沙坦+氢氯噻嗪 419、厄贝沙坦+氢氯噻嗪 402、氯沙坦+氢氯噻嗪 333、格列本脲+二甲双胍 304、缬沙坦+氨氯地平 303、奥美沙坦+氢氯噻嗪 285、氟替卡松+沙美特罗 255、对乙酰氨基酚+右美沙芬+多西拉敏 246、替米沙坦+氢氯噻嗪 223 等。

## 4. 无匹配的原因

1. **市场专属复方**：CN 中成药/复方感冒药（如复方氨酚烷胺 695 个产品、氨酚氯丙那敏 774 个）、MX/ES 本地复方、US OTC 多成分感冒/止痛复方——对方市场没有同固定组合；共 4,551 个 none 集合（东侧 386 / 西侧 4,173）。
2. **成分集合大小不同**：复方感冒药常差 1–2 个成分，Jaccard 达不到 0.8（如 CN 3 成分 vs US 5 成分）。
3. **成分命名长尾**：跨市场同义/盐型未覆盖全（如部分避孕复方 `drospirenone|ethinylestradiol` 与西侧 `ethinyl-estradiol` 变体仍未归一；`gliclazide|metformin` 等 GB 侧无对应 FDC）——同义表目前手工 30 余对，可继续扩。
4. **原始复方被去重剔除**：14,742 个「≥2 行」产品在成分归一后只算 1 个成分（同一成分的盐型/重复行，或复方被拆成同成分多行），无法作为复方参与匹配；属数据处理遗留，后续可在 ingest 侧去重。
5. **数据源覆盖差异**：西侧集合 4,401 个远多于东侧 614 个（US OTC/医院复方多），天然拉低「集合口径」匹配率。

**降级主成分可用**：none 4,551 个集合中，1,159 个（25.5%）的主成分在对面市场有产品（单方或其它复方），可用于「无同组合 → 去主成分页看」的降级路径；其余 3,392 个是植物药/疫苗/生物制品/本地特殊复方等，主成分本身也只在单侧有。

## 5. 页面接入建议（不改本任务代码，供 build 任务参考）

1. **组合页加「其他国家同组合」区块**：`site/build.py:build_combo_pages()` 已按「活性成分集合」生成 `/combo/<slug>.html`；构建时读 `data/combo_match_candidates.csv`，用当前页面的 `sids`（原始 substance_id 排序集合）反查签名 → 展示 `match_strength=exact` 的 `match_markets` + 各国 `brands`/`n_products`/`sample_product_id`（可链到 name/drug 页），并加三语标题（en: "Same combination in other markets" / es: "Misma combinación en otros mercados" / zh: 「其他国家/地区的同组合」）。
2. **无匹配提示**：`match_strength=none` 时展示「本组合在其他已收录市场暂无同复方」；若 `primary_cross_market=yes`，追加「可查看主成分在其他市场的商品」链接（成分页 `/drug/<primary>.html`）——只做身份对应，不给剂量/替代建议。
3. **overlap 近似组合**：只在「近似组合（相差 N 个成分）」提示里展示 `matched_signatures`，明确「近似≠可互换」；是否展示可先用开关灰度。
4. **页面 slug 与签名不一致**：站点 combo 页按**原始 substance_id 集合**（7,947 个），本 CSV 按**归一成分集合**（4,787 个签名）——一个签名可能对应多个 combo 页（盐型/厂家差异）。接入时建议以「页面 sids → 归一签名」反查；后续可考虑把 combo 页也按归一签名合并（链接 301/聚合），减少重复页。
5. **数据体积/构建**：CSV 1.39 MB / 5,713 行，构建期读入内存无压力；无 DB 写入、无运行时请求，不增加首屏体积。
6. **三语**：区块标题/空态/近似提示需 zh/en/es 三语（复用 `COMBO_I18N`）。

## 6. 风险与限制

- **同义表是手工的**（30+ 对）：长尾 INN 名/盐型差异仍会造成 none，后续可按 `substance.atc`（5 位）+ 名称相似度扩表；本轮故意不用 ATC-4（4 位码如 A10BB 会把不同磺脲类混在一起）。
- **exact 不要求规格/剂型/释放一致**：只做「同成分集合」身份对应（页面须沿用「不可互换」警示，不给剂量建议）；`strength_sig/form_release` 仅展示。
- **brands 仅取 trade 名**：部分市场（如美国仿制药）商品名在 `name_type=inn` 下，brands 可能为空——接入时可回退展示 INN 名或 generic 名。
- **DB 持续被其它任务写入**：本报告数字为 2026-10-28 10:24 UTC 快照；换库后重跑脚本即可。
- **降级主成分**：只用于「无同组合」的页面引导，不代表可替代；需沿用站点「不给用药建议」底线。

## 7. 复现与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/build_combo_matches.py            # 只读 DB，生成 CSV + stats + samples
& $py etl/build_combo_matches.py --dry-run  # 只看统计
```

| 文件 | 内容 |
|---|---|
| `data/combo_match_candidates.csv` | 5,713 行（签名×国家），字段见 §2 |
| `etl/build_combo_matches.py` | 只读构建器（可重跑；`--db/--dry-run`） |
| `.tmp/combo-match/stats.json` | 汇总统计 |
| `.tmp/combo-match/samples.txt` | 指定样例 + overlap 样例 |
| `reports/combo-crossmatch.md` | 本报告 |
