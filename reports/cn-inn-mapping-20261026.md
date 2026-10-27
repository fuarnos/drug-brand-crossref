# CN 中文名 → 英文 INN 系统映射报告

日期：2026-10-26 ・ 站点版本：v0.3.5 ・ 数据库：`data/drugs.db`（SQLite，本轮只读）
产物：`data/cn_inn_overrides.csv`、`etl/merge_cn_substances.py`、本报告
验证：apply / 幂等 / 回滚只在副本 `.tmp/cn-map/drugs-test.db` 上跑，**未写正式库**

---

## 1. 摘要

上一轮只把 GLP-1 六个中文名（替尔泊肽/司美格鲁肽/利拉鲁肽/度拉糖肽/艾塞那肽/利司那肽）
映射到了英文 INN。本轮把「只有中文名」的 CN 专属成分（`substance_id LIKE 'cn-%'`）
系统化过了一遍：

| 指标 | 数值 |
|---|---|
| CN 专属成分总数 | **2,177** |
| 其中国内产品数（去重） | 14,509 |
| 本轮**可合并**（英文 INN 在库中已有 substance） | **350 个成分 / 3,355 个产品** |
| 合并后 CN 专属成分预计 | 2,177 → **1,827**（−16.1%） |
| 受影响产品占 CN 产品 | **23.1%**（3,355 / 14,509） |
| 映射置信度 | high 165 ・ medium 185（无 low 进合并） |
| 合并目标覆盖 | 340 个英文 substance（有 10 个中文名共用一个目标） |

其余按「未匹配」分类并逐条给出原因：**复方 106 个**（832 产品）、
**无英文对应 38 个**（422 产品）、**不确定 1,683 个**（9,900 产品）。

---

## 2. 数据与方法

### 2.1 候选集
从 `data/drugs.db` 取 `substance_id LIKE 'cn-%'` 的全部成分（2,177 个，按产品数排序），
每个成分只有 1 个 variant 且 salt/hydrate/ester 全空（base variant），共挂 14,509 个 CN 产品。
中文名来源：`substance.inn_zh`（NHSA 2024-01-05 快照的通用名，已剥剂型/限定词）。

### 2.2 证据链（按优先级，可叠加）

1. **库内/仓库内人工表**
   - `data/cn_name_map.json`（中文注册名 → 英文成分，人工初判）——按 `reduction_chain`
     剥剂型/盐基后匹配；
   - `etl/ingest_nhsa.py` 的 `CN2EN` 表（1,088 条）；
   - `substance.inn_zh`（其它市场已人工挂了中文名的 228 条）。
2. **Wikidata**（CC0）
   - 对每个成分的完整中文名 + 剥盐/剥剂型后的候选名（共 **2,718 个查询名**）批量 SPARQL
     查 `rdfs:label` / `skos:altLabel`（语言标签 zh/zh-hans/zh-cn/zh-hant）；
   - 返回 item QID、en label、P267 ATC；**529 个查询名命中标签**，最终 330 条合并以
     Wikidata 为主证据（94%）。
   - 查询结果只缓存在 `.tmp/cn-map/wd_zh_lookup.json`（不入库、不进站点）。
3. **ATC-4 互证**：NHSA 药品代码带 ATC-4；若 Wikidata item 的 P267 前 5 位与之一致，
   作为强互证（245 条合并有 ATC 互证）。ATC 用于「多个候选收敛」与置信度升级，不单独定案。
4. **构词规律**：`-单抗→-mab`、`-替尼→-tinib`、`-沙坦→-sartan`、`-洛尔→-olol`、
   `-拉唑→-prazole`、`-列汀→-gliptin`、`-列净→-gliflozin`、`-肽→-peptide` 等**只用于
   分类/给出提示**（210 个 uncertain 标了规律），不直接作为合并依据。
5. **放射药/核素药手动映射**（10 条）：锝[99mTc]/碘[131I]/氟[18F] 类逐条对齐 DB 里已有的
   technetium/sodium iodide I-131/FDG 成分，证据 URL 用该英文成分在 DB 中的产品源页
   （FDA NDC / NHS TRUD）。

### 2.3 合并门槛（宁可少并，不可错并）
只有同时满足以下条件才标 `mergeable`：

1. 英文 INN 在 DB 里**已有 substance**，且英文名归一化后与目标 `substance.inn_en` 一致
   （或只差中文名里也写明的盐/酯后缀）；
2. 目标英文名的盐/酯/水合后缀**必须能在中文名里找到对应写法**，否则按盐型/前药风险拒绝
   （例：`阿齐沙坦` 的目标 Azilsartan Medoxomil 含中文名没有的 medoxomil → 不合并；
   `苯甲酸雌二醇` 的目标 Estradiol 缺 benzoate → 不合并）；
3. 复方/多成分、放射性药盒、非单一药品实体一律不合并；
4. 目标必须有可挂的 variant（优先挂中文名对得上的盐/酯 variant，见 §4）。

---

## 3. 结果：350 条可合并

完整清单见 `data/cn_inn_overrides.csv`（2,177 行，列：
`zh_name,en_inn,cn_substance_id,en_substance_id,evidence_url,confidence,status,reason`）。

### 3.1 Top 30（按受影响产品数）

| # | 中文名 | 英文目标 | 产品 | 置信度 | 证据 |
|---|---|---|---|---|---|
| 1 | 甲苯磺酸艾多沙班 | Edoxaban | 128 | medium | [Q21011234](https://www.wikidata.org/wiki/Q21011234)，ATC B01AF 一致，挂 edoxaban-tosylate variant |
| 2 | 治疗用碘[131I]化钠 | Sodium Iodide I 131 | 100 | high | DB 产品源页（NHS TRUD） |
| 3 | 罗沙司他 | Roxadustat | 62 | high | [Q27088611](https://www.wikidata.org/wiki/Q27088611)，ATC 一致 |
| 4 | 高锝[99mTc]酸钠 | Technetium Tc 99M Sodium Pertechnetate | 58 | high | 放射药手动映射（DB 产品源页 FDA NDC） |
| 5 | 琥珀酸普芦卡必利 | Prucalopride | 52 | medium | [Q68484](https://www.wikidata.org/wiki/Q68484)，ATC 一致，挂 succinate variant |
| 6 | 锝[99mTc]亚甲基二膦酸盐 | Technetium Tc 99M Medronate | 52 | high | 放射药手动映射（DB 产品源页 FDA NDC） |
| 7 | 锝[99mTc]甲氧异腈 | Technetium Tc 99M Sestamibi | 51 | high | 放射药手动映射（DB 产品源页 FDA NDC） |
| 8 | 苯甲醇 | Benzyl Alcohol | 44 | medium | [Q52353](https://www.wikidata.org/wiki/Q52353) |
| 9 | 碘[131I]化钠 | Sodium Iodide I 131 | 42 | high | 放射药手动映射（DB 产品源页 NHS TRUD） |
| 10 | 盐酸鲁拉西酮 | Lurasidone | 39 | medium | [Q416992](https://www.wikidata.org/wiki/Q416992)，ATC 一致，挂 hydrochloride variant |
| 11 | 菠萝蛋白酶 | Bromelain | 38 | medium | [Q415756](https://www.wikidata.org/wiki/Q415756) |
| 12 | 阿戈美拉汀 | Agomelatine | 38 | high | [Q395229](https://www.wikidata.org/wiki/Q395229)，ATC 一致 |
| 13 | 吡仑帕奈 | Perampanel | 36 | high | [Q868658](https://www.wikidata.org/wiki/Q868658)，ATC 一致 |
| 14 | 佐米曲普坦 | Zolmitriptan | 35 | high | [Q218820](https://www.wikidata.org/wiki/Q218820)，ATC 一致 |
| 15 | 聚乙烯醇 | Polyvinyl Alcohol | 34 | medium | [Q146339](https://www.wikidata.org/wiki/Q146339) |
| 16 | 米拉贝隆 | Mirabegron | 33 | high | [Q3702534](https://www.wikidata.org/wiki/Q3702534)，ATC 一致 |
| 17 | 拉西地平 | Lacidipine | 32 | high | [Q1163827](https://www.wikidata.org/wiki/Q1163827)，ATC 一致 |
| 18 | 盐酸依匹斯汀 | Epinastine | 32 | medium | [Q632405](https://www.wikidata.org/wiki/Q632405)，ATC 一致，挂 hydrochloride variant |
| 19 | 盐酸左布比卡因 | Levobupivacaine | 32 | medium | data/cn_name_map.json |
| 20 | 丙酸氯倍他索 | Clobetasol | 30 | medium | [Q421637](https://www.wikidata.org/wiki/Q421637)；英文名在 DB 以 base + propionate variant 建模，改挂 base |
| 21 | 阿瑞匹坦 | Aprepitant | 30 | high | [Q621834](https://www.wikidata.org/wiki/Q621834)，ATC 一致 |
| 22 | 泊沙康唑 | Posaconazole | 29 | high | [Q906453](https://www.wikidata.org/wiki/Q906453)，ATC 一致 |
| 23 | 酒石酸伐尼克兰 | Varenicline | 29 | medium | [Q411330](https://www.wikidata.org/wiki/Q411330)，ATC 一致，挂 tartrate variant |
| 24 | 匹多莫德 | Pidotimod | 28 | high | [Q3902720](https://www.wikidata.org/wiki/Q3902720)，ATC 一致 |
| 25 | 福尔可定 | Pholcodine | 28 | high | [Q3124290](https://www.wikidata.org/wiki/Q3124290)，ATC 一致 |
| 26 | 阿伐那非 | Avanafil | 28 | high | [Q2873270](https://www.wikidata.org/wiki/Q2873270)，ATC 一致 |
| 27 | 乌洛托品 | Methenamine | 27 | medium | [Q71969](https://www.wikidata.org/wiki/Q71969) |
| 28 | 盐酸罂粟碱 | Papaverine | 27 | medium | [Q410374](https://www.wikidata.org/wiki/Q410374)，ATC 一致，挂 hydrochloride variant |
| 29 | 钆布醇 | Gadobutrol | 27 | high | [Q2570844](https://www.wikidata.org/wiki/Q2570844)，ATC 一致 |
| 30 | 咪喹莫特 | Imiquimod | 26 | high | [Q423417](https://www.wikidata.org/wiki/Q423417)，ATC 一致 |

> 表中 QID 仅为示例来源；CSV 的 `evidence_url` 列逐行给出实际证据（Wikidata item URL、
> 放射药对应的 DB 产品源页，或 `repo:` 指向仓库内人工表）。

### 3.2 证据构成（可叠加）

| 证据 | 条数 |
|---|---|
| Wikidata zh 标签/剥盐后标签命中 | 330 |
| ATC-4 与 Wikidata P267 前 5 位一致（互证） | 245 |
| 挂到中文名对得上的盐/酯 variant | 74 |
| 仓库人工表 `cn_name_map.json` / DB inn_zh / CN2EN | 10 |
| 放射药手动映射（FDA/NHS 源页） | 10 |

### 3.3 生物制品/疫苗类（单列，便于复核）
`乙型肝炎疫苗 → Hepatitis B Vaccine`（23 产品）、
`利妥昔单抗 → Rituximab`（17）、`贝伐珠单抗 → Bevacizumab`（15）、
`曲妥珠单抗 → Trastuzumab`（11）、`司库奇尤单抗 → Secukinumab`（8）、
`链激酶 → Streptokinase`（7）、`门冬酰胺酶 → Asparaginase`（6）等；
单抗类一律要求 Wikidata 中文标签精确命中 + 目标英语 INN 精确匹配，未使用构词规则直推。

---

## 4. 盐型/酯型如何处理（重点）

DB 的建模方式有两种：① 盐/酯作为 base 成分下的 `variant`（如
`lurasidone` 下有 `lurasidone-hydrochloride`）；② 盐/酯作为独立 substance 且没有 variant
（如 `clobetasol-propionate`）。工具两种都能处理：

- 中文名带盐/酯（如「盐酸」「甲苯磺酸」「琥珀酸」「丙酸」「醋酸」）时，
  **优先把 product_component 挂到英文目标下盐/酯对得上的 variant**（本轮 74 条）：
  - 甲苯磺酸艾多沙班 → `edoxaban` / `edoxaban-tosylate`
  - 琥珀酸普芦卡必利 → `prucalopride` / `prucalopride-succinate`
  - 盐酸鲁拉西酮 → `lurasidone` / `lurasidone-hydrochloride`
- 目标英文名本身是盐/酯独立 substance 时，回退到 base 成分并以 variant 落地（如
  丙酸氯倍他索 → `clobetasol` / `clobetasol-propionate`）；
- 目标没有任何 variant 行 → 直接跳过（本轮 CSV 里已提前剔除，故 apply 时 0 skip）；
- 目标名含中文名没有的盐/酯后缀 → 视为盐型/前药风险，**不合并**（10 个进 uncertain，另有 13 个「证据不足/多候选」也归 uncertain）：
  例：`阿齐沙坦`（目标 Azilsartan Medoxomil）、`苯甲酸雌二醇`（目标缺 benzoate）、
  `乳酸亚铁`（目标 Iron）、`西吡氯铵`、`曲司氯铵`、`溴化钙`、`碘化铵`。
- 中文名有盐/酯但目标无对应 variant 的 29 条按 base variant 合并（reason 列标注
  「目标无对应盐/酯 variant，按 base variant 合并」，置信度已降为 medium）。

---

## 5. 未匹配分类统计

### 5.1 `combination` 复方/多成分 —— 106 个成分 / 832 产品
按「名字可切出 ≥2 个已知成分、含复方/复合/多维/多维/维D+矿物质、或含 / 、 ＋」判定。
不做合并（合并进单一成分会把复方药错记成单方）。Top 例：
`四维葡钙`（38）、`三维葡磷钙`（35）、`电解质补给`（32）、
`口服五维赖氨酸葡萄糖`（30）、`五维赖氨酸`（29）、`脂溶性维生素`（28）、
`赖氨肌醇维B12`（28）、`复合磷酸氢钾`（24）、`多种微量元素`（22）、
`人凝血酶原复合物`（21）。下一步应建「复方成分层」，而不是并入某一成分。

### 5.2 `no_english` 有英文 INN、但 DB 无该 substance —— 38 个成分 / 422 产品
这些是最值得下一批补的「英文成分缺口」（证据为 Wikidata 中文标签精确命中）：

| 中文名 | Wikidata 英文 INN | 产品 |
|---|---|---|
| 瑞巴派特 | rebamipide | 93 |
| 吲哚布芬 | indobufen | 47 |
| 普卢利沙星 | prulifloxacin | 26 |
| 西尼地平 | cilnidipine | 24 |
| 羟甲烟胺 | nicotinyl methylamide | 19 |
| 二硫化硒 | selenium disulfide | 14 |
| 呋喃西林 | nitrofurazone | 14 |
| 马来酸桂哌齐特 | cinepazide | 14 |
| 硼酸 | orthoboric acid | 12 |
| 磺胺对甲氧嘧啶 | sulphamethoxydiazine | 12 |
| 妥洛特罗 | tulobuterol | 11 |
| 西他沙星 | sitafloxacin | 11 |
| 长春胺 | vincamine | 11 |
| 磷酸铝 | aluminium phosphate | 10 |
| 地佐辛 | dezocine | 9 |
| 交沙霉素 | josamycin | 8 |
| 其余 22 个 | — | 131 |

### 5.3 `uncertain` 不确定 —— 1,683 个成分 / 9,900 产品

| 原因桶 | 条数 |
|---|---|
| 无外部证据（现有表/Wikidata 完全未命中） | 1,350 |
| 无外部证据，但有构词规律提示 | 210 |
| 放射性药物/诊断药盒（需核素-配体完整 INN） | 89 |
| 证据不足（仅剥盐后命中/多候选并列） | 13 |
| 非单一成分/非药品实体（腹膜透析液、营养类、中药材等） | 11 |
| 盐型/前药风险未排除 | 10 |

构词规律提示分布（不直接用于合并，供下一批按类攻关）：
单抗→-mab 85、替尼→-tinib 44、肽→-peptide 22、霉素→-mycin 14、列汀→-gliptin 7、
沙星→-floxacin 7、洛尔→-olol 7、地平→-dipine 6、康唑→-conazole 5、
替丁→-tidine 3、列净→-gliflozin 3 等。

---

## 6. 合并工具与安全校验

### 6.1 工具
`etl/merge_cn_substances.py`（默认 dry-run）：

```
python etl/merge_cn_substances.py                     # 只读：列出将合并的 id 对/组件数/跳过原因
python etl/merge_cn_substances.py --db X.db --apply   # 事务内 UPDATE product_component、DELETE variant/substance
python etl/merge_cn_substances.py --db X.db --rollback [manifest]  # 按撤销清单回滚
```

- 只处理 `status=mergeable` 的行；`--csv` 可换映射表；默认 `--db data/drugs.db`；
- 每行安全校验：CN 侧成分存在且 id 以 `cn-` 开头（**永不删英文成分**）、英文目标存在且
  `inn_en` 与 CSV 一致、CN 侧恰好 1 个 base variant、目标有可挂 variant、
  CN 成分没有被 nickname / drug_term / confusable_pair / dose_warning（若表存在）引用、
  受影响产品没有 corroboration 记录；任何一条不过即跳过该行（不部分合并）；
- 幂等：CN 成分已不存在（上轮已合并）记为 `already_merged`，再跑 `--apply` 不写库；
- 撤销清单：默认 `.tmp/cn-map/merge_undo_<UTC>.json`，记录完整 substance 行、variant 行、
  被移动的 `product_component(product_id, ord, 旧 variant_id)`，先写盘再 commit；
  `--rollback` 按 (product_id, ord) 精确回挂，可重复回滚（第二次幂等）。

### 6.2 在 DB 副本上的实测（`.tmp/cn-map/drugs-test.db`）
- `apply`：350 个 CN 成分合并，substance 13,282→12,932、variant 14,234→13,884、
  product_component 497,513 行**数量不变**、product 409,485 不变；无悬空外键
  （component→variant、variant→substance 均为 0 孤儿）；被合并的 CN 成分/variant 全部消失；
- **幂等**：第二次 `--apply` 输出「没有可合并的行」，不写库、退出码 0；
- **回滚**：`--rollback` 后 `substance` / `variant` / `product_component` 三表内容
  与合并前 **sha256 完全一致**（逐行 dump 校验）；第二次回滚幂等成功。

### 6.3 人工复核发现的数据问题
- `data/cn_name_map.json` 有一条错误初判：`枸橼酸锌片 → potassium citrate`；
  已在最终 CSV 中排除（改标 uncertain，理由写明），建议把该条修正为 zinc citrate。
- 放射药 10 条为手动映射，逐条核对 DB 中已有英文成分（FDA NDC/NHS TRUD 源页），
  未使用配体（如 medronic acid、bicisate）冒充核素药。
- 未合并的放射药/诊断药盒（89 个）留在 uncertain，等待补核素-配体完整 INN。

---

## 7. CSV 字段

| 列 | 含义 |
|---|---|
| `zh_name` | 中文通用名（NHSA 的 CN 成分名） |
| `en_inn` | 英文 INN / 英文成分名（uncertain 且无证据时为空） |
| `cn_substance_id` | CN 专属成分 id |
| `en_substance_id` | 目标英文 substance id（仅 mergeable / 部分 uncertain 填写） |
| `evidence_url` | Wikidata item URL、DB 产品源页，或 `repo:` 仓库内人工表引用 |
| `confidence` | high（精确标签+ATC 互证/人工表）/ medium（单一强证据） |
| `status` | `mergeable` / `combination` / `no_english` / `uncertain` |
| `reason` | 判定理由（证据种类、盐型处理、跳过原因或构词规律提示） |

---

## 8. 建议下一批

1. **先审后 apply 本批**：`etl/merge_cn_substances.py --apply` 预计把 CN 专属成分
   2,177→1,827、3,355 个 CN 产品（23.1%）首次能定位到海外产品；建议先 dry-run 复核
   Top 30 与 20 条人工表/手动映射证据行。
2. **补英文成分再合并（no_english 38 个 / 422 产品）**：`rebamipide`、`cilnidipine`、
   `prulifloxacin`、`indobufen`、`nicotinyl methylamide` 等库中确实没有对应 substance，
   用现有 ETL 的 new_en 机制补英文成分后，这 38 条可直接并入。
3. **单抗/生物制品 85 个 → 分小批**：Wikidata 中文标签覆盖差，改用「英文 INN 候选池 +
   P267 ATC-4 反查 + NMPA/FDA/EMA 说明书」逐批确认；生物类似药只并到 INN 层，不并品牌。
4. **构词规律 210 个（替尼 44 / 肽 22 / 霉素 14 …）**：先建「中文词干 → 英文后缀」候选
   生成器（本轮规则只做提示），加上 ATC-4 反查与公开说明书 URL 后人工确认。
5. **盐型补全**：把 29 条 base_fallback 与 10 条盐型风险行的英文成分补齐 salt/ester
   variant 后再合并；同时为 106 个复方（832 产品）设计复方成分层，不在单成分合并里处理。
6. **顺带修数据**：`data/cn_name_map.json` 的 `枸橼酸锌` 条目。

---

## 9. 局限与许可

- Wikidata 中文标签覆盖率有限（529/2,718 查询名命中），部分国内创新药/生物药没有 zh
  label；这是 uncertain 的最主要来源，不代表「没有英文名」。
- NHSA 快照为 2024-01-05，中文名与现行说明书可能有出入；盐基信息在 CN 侧未建模
  （全部 variant 的 salt 为空），本轮按 DB 既有语义挂到英文 base/盐 variant。
- Wikidata 数据为 CC0；NHSA 为公开数据（未标注开放许可，按公开数据引用）；
  放射药证据页来自 FDA NDC / NHS TRUD 公开接口，具体 URL 在 CSV 中逐行标注。
- 本轮没有写 `data/drugs.db`、没有跑 `site/build.py`、没有发布；`--apply` 只作用于
  `.tmp/cn-map/drugs-test.db` 副本。
