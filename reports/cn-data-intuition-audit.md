# CN 数据使用直觉专项审计（task-123）

> 日期：2026-10-28 ｜ 只读 `data/drugs.db`（未写库）、未改 `site/build.py`、未 git/发布。
> 数据快照：DB mtime 2026-10-28 13:35（CN 产品 **146,347**、成分 **3,065**、组件 **150,193**）。
> 明细与可复现脚本：`.tmp/cn-intuition/`（`audit.py`、`audit2.py`、`top20.py`、`audit.json`、`audit2.json`、`top20.json`）。
> 报告按 Lead 要求标注**排期状态**：已排期（v0.8.2 / v0.8.3 / CN 品牌名扩充 / 双语显示）只给结论/风险提示，**不重复提方案**；重点给**未排期**问题与建议。

## 0. 结论摘要（按优先级）

| # | 问题 | 频次/影响 | 排期状态 | 优先级 |
|---|---|---|---:|---|
| 1 | **CN 产品显示英文通用名**：substance.inn_zh 缺失 | **236 成分 / 31,055 产品 = 21.2% CN 产品**（葡萄糖、氯化钠、左氧氟沙星、阿司匹林、红霉素、维生素 C/B6/B1、替米沙坦、氨苄西林、氯化钾、环丙沙星、锌、生育酚、维 A…） | **未排期**（v0.8.1 双语显示只覆盖 536 个有官方来源的译名；这 236 个明确留空不盲译；v0.8.3 不涉及） | **P0** |
| 2 | **无商品名产品显示**：87.5% CN 产品无 trade 名，显示「通用名（含剂型词）」且与剂型列重复 | 128,060 产品无商品名；其通用名 key **5,173/5,534 = 93.5%** 自带剂型词（如「地喹氯铵含片」+ 剂型「片剂(口含)」） | **未排期**（v0.8.3「未收录空行隐藏」只藏空矩阵行，不处理此） | **P0** |
| 3 | **剂型 form_base 非规范**：67 种非 canonical 值、1,214 行；检测/试剂类混入药品产品 | 灌肠剂 173、体外诊断试剂 150、缓释制剂 97、冻干粉针剂 87、滴剂 72、口服乳剂 72、眼膏剂 67、鼻用制剂 64…；检测类（体外诊断试剂 150 + 放免诊断试剂盒 31 + 诊断试剂盒 11）= 192 行 | **未排期**（v0.8.3 筛选器按 form_base 分组，会暴露这些问题） | **P1** |
| 4 | **规格异常/缺失**：解析错误值、0 值、无规格 | 异常 27+3 行（**Macrogol 400064 g ×22**、400013 g ×2、3350100 g ×1；Cefoperazone 0 g ×2、Dinoprostona 0 mg ×1）；5,230 产品（3.6%）无规格 | **未排期**（v0.8.3「常用剂量排序」会把 400064 g 当最大剂量排最前，属风险提示） | **P1** |
| 5 | **重复产品**：同批文/同厂家/同剂型/同包装/同规格签名的重复行 | 精确重复 **756 组 / 2,042 行**（单组最多 100 行：国药准字H20213256 原子高科）；同批文+成分+规格 **4,763 组 / 14,572 行**（可能含不同包装，需复核） | **未排期** | **P1** |
| 6 | **批文格式异常** | 993 行非「国药准字」前缀（进口 H/HC/S 文号；其中 115 行无标准前缀）、339 行带「(参照)」后缀、1 行缺失 | **未排期**（展示规范化） | **P1** |
| 7 | **商品名混入规格/剂型**（少量） | 严格判定：含浓度 3 个键（Parlodel/Zyprexa/Plaquenil 的「x mg tablets」变形）；「欣普尼 注射液」等；英文商品名 12 键/35 产品（0.02%）；中英混写 41 键/124 产品（胰岛素 R/N 等合理） | **未排期**（P2） | **P2** |
| 8 | **厂家英文名** | 4,219 产品（2.9%）厂家为英文（743 个名称；Novartis 128、AstraZeneca 123…）；31 行厂家名 >50 字 | **未排期**（低优先，境外持证商可保留原名） | **P2** |
| 9 | 同名不同成分（品牌页/搜索碰撞） | 107 个品牌名对应 >1 成分（恺诺 5、泰诺 4、苏复 4、日夜百服咛 4…） | 已有 `collision` 机制，**无需新方案**（仅提示） | **P2** |
| 10 | 通用名混写/罗马数字/维生素字母 | 607 个中文+字母 key，其中 216 个含英文单词（铝镁混悬液(II)、复方芦荟维U片、口服乳杆菌LB散…多合理）；控制字符/乱码复核 **0** | 无需方案（数据本身合理） | — |

**一句话**：中文商品名本身质量不错（98.9% 纯中文、只有 0.02% 产品看到英文商品名）；真正破坏"使用直觉"的是 **① 21.2% 产品显示英文通用名**、**② 87.5% 无商品名产品显示通用名+剂型重复**、**③ 剂型/规格/重复/批文的展示脏数据**。前两项未排期，建议进下一版（或 v0.8.3 之后 hotfix）。

## 1. 商品名：中文/英文比例与混入

### 1.1 频次

| 指标 | 值 |
|---|---:|
| CN 商品名 key（trade） | 4,866 |
| 纯中文 | **4,813（98.9%）** |
| 中英混写 | 41（0.84%） |
| 纯英文/拉丁 | **12（0.25%）** |
| 含数字（多为胰岛素 30R/50R 等，合理） | 23 key |
| 含浓度/规格写法（明显异常） | 3 key（4 种写法） |
| 含厂家词 / 「详见说明书」噪声 / 商品名=通用名 | 0 / 0 / 0 |
| 商品名长度 | P50=3 字，P90=9 字，max=23 |

SQL：

```sql
-- 商品名 script 分布（按 key）
SELECT COUNT(DISTINCT nk.key_id), nk.script, COUNT(*)
FROM product p JOIN product_name pn ON pn.product_id=p.product_id
JOIN name_key nk ON nk.key_id=pn.key_id
WHERE p.country='CN' AND pn.name_type='trade' GROUP BY nk.script;
-- 含浓度/规格写法
SELECT nv.raw, COUNT(DISTINCT p.product_id)
FROM product p JOIN product_name pn ON pn.product_id=p.product_id
JOIN name_key nk ON nk.key_id=pn.key_id JOIN name_variant nv ON nv.key_id=nk.key_id
WHERE p.country='CN' AND pn.name_type='trade'
  AND nv.raw REGEXP '\d+(\.\d+)?\s*(mg|g|ml|μg|iu|毫克|克|毫升|微克|%)'  -- SQLite 需 REGEXP 扩展；报告用 Python 复算
GROUP BY nv.key_id;
```

**英文商品名 Top（全部 12 个键，按产品数）**：`ZYPREXA`(12)、`Obroxol`(6)、`Melnox`(4)、`GRAFALON`(3)、`ORGALUTRAN`(2)、`BLEOCIN`(2)、`Trast`(1)、`PLASBUMIN-20`(1)、`PLAQUENIL`(1)、`PARLODEL`(1)、`HDCV`(1)、`ABRAXANE`(1)。→ **CN 用户遇到英文商品名的概率 = 35 产品 / 146,347 = 0.024%**，可忽略；混写 Top：`赛增(Jintropin)`(15)、`重和林R`(7)、`重和林N`(6)、`重和林M30`(6)、`诺和灵N`(6)、`诺和灵30R`(5)、`妈咪爱；Medilac-Vita`(5)——多为胰岛素/进口品牌合理写法。

**混入异常样例（P2）**：

| 商品名 | 问题 | 说明 |
|---|---|---|
| `Parlodel 2.5mg tablets` / `PARLODEL 2.5MG` / `Zyprexa 2.5mg tablets` / `Plaquenil 200mg tablets` | 规格+剂型混入商品名 | NHSA 对进口药把「商品名 + 规格 + 剂型」整串放商品名列；应从 trade 名剥掉 `x mg tablets` 后缀 |
| `欣普尼 注射液` | 剂型混入 | 同上，商品名后带剂型 |
| `维敏胶囊` / `爱侣栓` / `华素片` / `意可贴` | 含剂型词但**大概率是合法品牌**（华素片、意可贴是注册品牌） | 不建议批量清洗，人工白名单 |

**建议（P2，未排期）**：展示层对 `trade` 名做**轻量后缀剥离**（`\s+\d+(\.\d+)?\s*(mg|g|ml|μg|iu)\s*(tablets?|capsules?|...)?$`），原文保留供复制/搜索；`维敏胶囊` 这类人工白名单不动。

## 2. 通用名：中文覆盖与英文显示（P0）

| 指标 | 值 |
|---|---:|
| CN 使用中的 substance | 3,065（另有大量非 CN 成分） |
| **inn_zh 为空的 substance（被 CN 产品使用）** | **236** |
| **受影响产品（任一成分缺中文）** | **31,055 / 146,347 = 21.2%** |
| 受影响产品（全部成分缺中文） | 30,608（20.9%） |
| CN 通用名 key 纯中文 / 混写 | 6,383（93.1%）/ 473（6.9%，多为罗马数字/维生素字母，合理） |

**缺失中文 Top20（按 CN 产品数）**：

| # | substance（inn_en） | 产品数 | 中文名（应显示） |
|---|---|---:|---|
| 1 | Glucose | 6,559 | 葡萄糖 |
| 2 | Sodium Chloride | 2,819 | 氯化钠 |
| 3 | Levofloxacin | 1,871 | 左氧氟沙星 |
| 4 | Ascorbic Acid | 1,575 | 维生素 C / 抗坏血酸 |
| 5 | Erythromycin | 1,033 | 红霉素 |
| 6 | Aspirin | 1,025 | 阿司匹林 |
| 7 | Diclofenac | 972 | 双氯芬酸 |
| 8 | Cefuroxime | 750 | 头孢呋辛 |
| 9 | Pyridoxine | 729 | 维生素 B6 / 吡哆醇 |
| 10 | Thiamine | 662 | 维生素 B1 / 硫胺 |
| 11 | Telmisartan | 592 | 替米沙坦 |
| 12 | Ampicillin | 583 | 氨苄西林 |
| 13 | Amino Acids | 468 | 氨基酸 |
| 14 | Cyanocobalamin | 443 | 维生素 B12 / 氰钴胺 |
| 15 | Potassium Chloride | 422 | 氯化钾 |
| 16 | Riboflavin | 408 | 维生素 B2 / 核黄素 |
| 17 | Ciprofloxacin | 377 | 环丙沙星 |
| 18 | Zinc | 352 | 锌 |
| 19 | Tocopherol | 349 | 维生素 E / 生育酚 |
| 20 | Retinol | 346 | 维生素 A / 视黄醇 |

SQL：

```sql
-- 受影响产品数
SELECT COUNT(DISTINCT p.product_id) FROM product p
JOIN product_component pc ON pc.product_id=p.product_id
JOIN variant v ON v.variant_id=pc.variant_id
JOIN substance s ON s.substance_id=v.substance_id
WHERE p.country='CN' AND (s.inn_zh IS NULL OR trim(s.inn_zh)='');
-- Top 缺失成分
SELECT s.inn_en, COUNT(DISTINCT p.product_id) n
FROM product p JOIN product_component pc ON pc.product_id=p.product_id
JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id
WHERE p.country='CN' AND (s.inn_zh IS NULL OR trim(s.inn_zh)='')
GROUP BY s.substance_id ORDER BY n DESC LIMIT 20;
```

**根因（重要）**：这些成分并不缺中文——CN 产品自身的 `name_variant.raw`/`name_key.norm` 里有中文通用名（CN 纯中文 inn key 有 **7,048 个**）。缺的是 `substance.inn_zh` 回填：
- task-42 的 `data/inn_zh_backfill.csv`（898 行）已覆盖一部分（如 **左氧氟沙星、双氯芬酸、头孢呋辛** 在 CSV 中），但**未覆盖**葡萄糖/阿司匹林/红霉素/维生素类/替米沙坦 等——因为 backfill 的歧义处理把「葡萄糖」在 glucose/dextrose、维生素 B1/B6 在多个盐型间判为冲突而丢弃；
- task-100 的 `data/ingredient_names_i18n.csv` 对这 236 个明确 `name_zh=''`（notes：「zh 缺官方/半官方来源，留空未盲译」）→ **v0.8.1 双语显示不会显示中文**；
- 这些药的中文名是**公开通用名**（药典/NHSA 产品名里就有），不是需要 AI 翻译的内容。

**建议（P0，未排期，不用新翻译）**：
1. **数据层**：把 `data/inn_zh_backfill.csv` 的 898 行按 apply 流程落库（若尚未），并对 236 个缺失成分扩展回填规则：用 CN 产品名中文（name_variant/name_key）+ 盐型剥离 → inn_zh；对 glucose/dextrose、维生素盐型等同义成分做**同名归并**（一个中文名可对应多个 INN 时，至少标 `inn_zh` 到主成分或双向显示）。
2. **展示层兜底（未排期，成本低）**：CN 产品页/结果行显示成分时，若 `substance.inn_zh` 为空，回退用**该 CN 产品名中的中文成分**（或显示「中文名待补」+ 英文 INN 小字），避免中文界面直接显示 `Glucose`/`Aspirin` 这类英文词。
3. 不建议：AI 盲译（task-100 已明确不做）。

## 3. NHSA「无商品名」产品在页面上的显示（P0）

| 指标 | 值 |
|---|---:|
| 无 trade 名的 CN 产品 | **128,060 / 146,347 = 87.5%** |
| 无任何名字的产品 | 0 |
| 无 trade 产品的 inn key | 5,534 |
| 其中 inn 名**含剂型词** | **5,173（93.5%）** |
| 其中 inn 名纯中文 / 混写 | 5,021 / 513 |
| 所有名字均无中文（纯英文）的产品 | 0（但 30,608 产品**成分名**全缺中文，见 §2） |

**现状显示**：页面对无商品名产品显示「注册名（含剂型）」，例如：
`地喹氯铵含片`、`碘化铵含片`、`丁硼乳膏`、`复方氯己定含漱液`、`度米芬滴丸`、`甲硝唑含漱液`…，而同一行的「剂型」列还显示「片剂(口含)/乳膏剂/含漱剂」→ **名称与剂型重复**，视觉上像「产品名写了两遍剂型」。

**建议（P0，未排期）**：
1. 当产品无 trade 名时，**展示名去掉尾部剂型词**（与剂型列去重）；在名称旁标注「无商品名」或留空品牌列（不要用通用名冒充品牌）。
2. 与 §2 的「中文兜底」一起做（无 trade 产品正好都是中文通用名，去掉剂型词后即得「地喹氯铵」）。
3. 不要把「无商品名」翻译成英文/占位符显示（当前数据没有该问题，但展示规则要明确）。

## 4. 规格：异常/缺失（P1）

| 指标 | 值 |
|---|---:|
| CN 组件 | 150,193 |
| 有 strength_value | 143,602（95.6%） |
| 无任何规格的产品 | **5,230（3.6%）** |
| 异常值（>100000 或 <=0） | **30 行** |
| 无 strength_unit 但有值 | 0（干净） |

**异常 Top（按行数）**：

| 值 | 单位 | 成分 | 行数 | 判断 |
|---:|---|---|---:|---|
| **400064** | g | Macrogol | 22 | ❌ 解析 bug（应为 Macrogol 4000 + 64 g） |
| 400013.125 | g | Macrogol | 2 | ❌ 同类 bug |
| 3350100 | g | Macrogol | 1 | ❌ 同类 bug |
| 126000 | iu | 牛碱性成纤维细胞生长因子外用 | 1 | ⚠️ 可能合理（外用单位），需核对 |
| 300000 | iu | 外用重组人碱性成纤维细胞生长因子 | 1 | ⚠️ 可能合理 |
| 0 | g | Cefoperazone | 2 | ❌ 0 值 |
| 0 | mg | Dinoprostona | 1 | ❌ 0 值 |

SQL：

```sql
SELECT pc.strength_value, pc.strength_unit, s.inn_en, COUNT(*) n
FROM product p JOIN product_component pc ON pc.product_id=p.product_id
JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id
WHERE p.country='CN' AND (pc.strength_value<=0 OR pc.strength_value>100000)
GROUP BY 1,2,s.substance_id ORDER BY n DESC;
```

**建议（P1，未排期）**：加一次 Parser 后处理规则：`Macrogol` 类「4000xx g」纠正为 4000 + xx g；0 值置空（display 「未公开」）；**v0.8.3 做常用剂量排序前先清洗**，否则异常值会排到最前（风险提示，不重复提 v0.8.3 方案）。

## 5. 剂型：form_base 非规范/检测试剂混入（P1）

- `dosage_form` 309 种（长尾含括号描述如「注射剂(冻干粉针剂)」——可接受）。
- `form_base` 非 canonical 值：**67 种 / 1,214 行**。Top20：灌肠剂 173、**体外诊断试剂 150**、缓释制剂 97、冻干粉针剂 87、滴剂 72、口服乳剂 72、眼膏剂 67、鼻用制剂 64、粉雾剂 52、耳用制剂 33、冻干粉 33、**放免诊断试剂盒 31**、涂剂 27、植入剂 17、冻干制剂 17、锭剂 16、冻干粉剂 15、橡胶膏剂 13、**诊断试剂盒 11**、含漱剂 10。
- **检测/试剂类混入药品产品**：体外诊断试剂 150 + 放免诊断试剂盒 31 + 诊断试剂盒 11 = **192 行**，用户会看到「药品」列表里出现诊断试剂。

SQL：

```sql
SELECT form_base, COUNT(*) n FROM product WHERE country='CN'
AND form_base NOT IN ('tablet','capsule','injection','topical','powder','liquid',
                      'suppository','inhalation','pill','other','unknown')
GROUP BY form_base ORDER BY n DESC;
```

**建议（P1，未排期）**：
1. 补 form_base 映射：灌肠剂→liquid/enema、滴剂→liquid、眼膏剂→topical、鼻用制剂→topical、粉雾剂→inhalation、冻干粉针→injection 等；v0.8.3 筛选器依赖 form_base，映射前会漏项（提示）。
2. 检测/试剂类（192 行）标记 `other` 或从药品产品层过滤（需产品口径确认；不影响成分/检索）。
3. `dosage_form` 原文保留，不强行改（用户能看懂括号描述）。

## 6. 批文/厂家异常（P1/P2）

### 6.1 批准文号

| 指标 | 值 |
|---|---:|
| 非「国药准字」前缀 | **993 行**（进口 H/HC/S/J 文号，如 H20150630 16 行、H20160199 6 行、H20140354 5 行…） |
| 其中完全无标准前缀（非国药准字/H/HC/J） | 115 行 |
| 带「(参照)」后缀 | 339 行（多为放射性药品，如 `国药准字H10973054(参照)`） |
| 缺失 | 1 行 |

SQL：

```sql
SELECT COUNT(*) FROM product WHERE country='CN' AND approval_id NOT LIKE '国药准字%';
SELECT approval_id, mah, COUNT(*) FROM product WHERE country='CN'
AND (approval_id NOT LIKE '国药准字%' OR approval_id LIKE '%参照%'
     OR approval_id IS NULL OR trim(approval_id)='')
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20;
```

**建议（P1，未排期）**：展示层统一「批准文号」格式：国产显示 `国药准字H...`；进口显示原 `H/HC/S...` 并加「进口注册」标签；「(参照)」只在内部保留、展示去掉（或标注「参照文号」）；不修改原值。

### 6.2 厂家（MAH）

| 指标 | 值 |
|---|---:|
| CN 产品厂家为非空 | 全部（0 缺失） |
| 厂家名为英文（无中文） | **4,219 产品（2.9%），743 个名称** |
| 厂家名长度 >50 | 31 行 |
| 厂家名含控制字符 | 0 |
| 同批文多厂家 | 33 个批文（如 `国药准字H10973054(参照)` 27 家） |

英文厂家 Top：Novartis PharmaSchweiz AG 128、AstraZeneca AB 123、BoehringerIngelheimInternationalGmbH 103、NAPPPHARMACEUTICALSLIMITED 92、Eli LillyNederland B.V. 86、Bayer AG 76…（多为进口持证商，英文原名可接受）。

**建议（P2，未排期）**：英文厂家保留原名，UI 标「境外持证商」；>50 字截断+tooltip；同批文多厂家在厂家列聚合（"+N"）。

## 7. 重复产品（P1）

| 口径 | 组数 | 涉及行 |
|---|---:|---:|
| 同批文+同厂家+同剂型+同释放+同包装+同规格签名（精确重复） | **756** | **2,042** |
| 同批文+同成分+同规格（可能不同包装，需复核） | **4,763** | **14,572** |

精确重复 Top：`国药准字H20213256`（原子高科，胶囊剂，100 行同 1 个包装/规格签名）、`国药准字H20043576`（中国工程物理研究院，口服溶液剂，16 行）、`国药准字H20083581`（广东香山堂，乳膏剂 1.0/%，15 行）、`国药准字H20173406`（武汉诺安，凝胶剂 0.1/%，15 行）…

SQL：

```sql
SELECT approval_id, mah, dosage_form, release, pack,
  (SELECT group_concat(strength_value || '/' || IFNULL(strength_unit,''), '|')
   FROM (SELECT strength_value, strength_unit FROM product_component pc
         WHERE pc.product_id=p.product_id ORDER BY pc.ord)) sig,
  COUNT(*) c
FROM product p WHERE country='CN'
GROUP BY approval_id, mah, dosage_form, release, pack, sig HAVING c>1
ORDER BY c DESC;
```

**影响**：结果行/品牌页/厂家页的产品计数偏高、同一产品可能重复出现；搜索按 key 聚合可能掩盖但成分页矩阵会重复计数。
**建议（P1，未排期）**：入库前去重（保留 1 行，记录来源行数）；「同批文+成分+规格」14,572 行需按包装/药品代码核对（不能一刀切，可能确实是不同包装规格）；先做 756 组精确重复即可。
（v0.8.3 的排序/筛选/空行隐藏不解决重复行问题，属未排期。）

## 8. 同名不同成分（P2，已有机制）

107 个 trade 品牌名对应 >1 个 substance：`恺诺`(5)、`苏复`(4)、`泰诺`(4)、`日夜百服咛`(4)、`彤贝得`(4)、`使力克`(4)、`泽荣`(3)、`金卡诺`(3)、`立林`(3)…。多为复方家族（泰诺有不同复方）或不同盐型/剂型，属品牌页正常聚合；`collision`/品牌页已能表达，无需新方案；仅建议搜索解析条提示「同名不同成分，点品牌页看全部」（已有 collision 展示，不重复）。

## 9. 排期对照与建议清单（重点：未排期）

| 审计发现 | 排期状态 | 处理建议 |
|---|---|---|
| CN 品牌名偏少（87.5% 无商品名） | **已排期**：CN 品牌名扩充（task-101/108 apply）＋ 人工采集包（task-110） | 不重复提方案；本审计只提供「显示规则」建议（见下） |
| 中文用户看到英文名称 | **部分已排期**：v0.8.1 双语显示（zh 536/es 640、来源徽章、不盲译）；但 236 个缺官方来源成分仍英文 | **未排期 P0**：数据回填（用 CN 官方中文名，不用 AI 翻译）+ 展示兜底 |
| 无商品名产品显示「通用名+剂型」重复 | **未排期**（v0.8.3 空行隐藏不覆盖） | **P0**：显示名去剂型后缀 + 标「无商品名」 |
| 规格异常值（Macrogol 400064 g 等） | **未排期**；v0.8.3 排序会放大 | **P1**：清洗 30 行异常 + 缺规格显示「未公开」 |
| 剂型 form_base 非规范/检测试剂混入 | **未排期**；v0.8.3 筛选器依赖 form_base | **P1**：补映射 67 类 + 检测类 192 行标 other |
| 重复产品（精确 756 组/2,042 行） | **未排期** | **P1**：入库前去重（保留来源计数），另 4,763 组复核包装 |
| 批文格式（993 非国药准字/339 参照/1 缺失） | **未排期** | **P1**：展示层规范化（不改原值） |
| 商品名混入规格/剂型、英文商品名 12 键 | **未排期（P2）** | 展示层轻量后缀剥离；人工白名单；低频可后置 |
| 厂家英文名 4,219 产品 | **未排期（P2）** | 保留原名 + 「境外持证商」标注/截断 |
| 同名不同成分 107 | 已有 collision/品牌页机制 | 不重复提方案 |

### 建议的落地顺序（供 Lead 排期）

1. **P0（数据+展示，1–2 天）**：
   - 数据：扩展 `inn_zh` 回填到 236 个成分（优先 Top20：葡萄糖/氯化钠/左氧氟沙星/阿司匹林/红霉素/维生素类…），处理同义成分（glucose/dextrose、维生素盐型）；风险：不要套用 `data/inn_zh_backfill.csv` 中的可疑行（如 `sodium-chloride → 乐敦清` 是品牌名，不是通用名——本审计发现）。
   - 展示：无 trade 名产品名称去剂型后缀 + 中文兜底；无中文成分时不在中文界面直接露英文（显示「中文名待补」或产品中文名中的成分）。
2. **P1（数据清洗，1–2 天）**：规格异常 30 行清洗；form_base 67 类映射 + 检测试剂 192 行分流；精确重复 756 组去重；批文展示规范化。
3. **P2（展示细节）**：商品名后缀剥离/白名单；厂家英文标注；同名品牌提示（已有）。
4. **风险提示（不另立方案）**：v0.8.3 的「常用剂量排序/筛选器/空行隐藏」上线前，建议先做 P1 的规格清洗与 form_base 映射，否则排序会把 400064 g 排最前、筛选器会漏掉非 canonical 剂型。

## 10. 附：方法与限制

- 全部只读 SQL/Python（`.tmp/cn-intuition/` 可复跑）；中文/英文判定用 Unicode 汉字区间 + 拉丁字母；混写判定含罗马数字/维生素字母（会高估，已在正文说明）。
- 「规格置信度」DB 未存 dry-run 的 medium/low 标记（ingest 只存最终值），本审计以「缺失/异常值/无单位」近似；不能区分 medium 误读，建议后续在 ingest 结果中保留 confidence 供审计。
- 「重复」仅基于 product 表列 + 组件规格签名；包装/药品代码未完全参与（`pack` 文本差异会造成部分漏判/误判），精确重复 756 组为保守口径。
- 数据为 2026-10-28 13:35 快照；随 DB 变化需重跑。
