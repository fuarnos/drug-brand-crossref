# task-140 常用药双向对照审计（只读）

> 执行：2026-10-30（Lead，自治运营第一件）。脚本 `db/crossref_audit.py`（只读 `mode=ro`），明细 `data/sources/crossref-audit-20261030.csv`（200 行）。
> 目的：回答「数据库是不是太小 / 常用药为什么对不上」。**不改库、不发版、不判替代。**

## 0. 结论

| 方向 | Top100 成分 | 有对应产品 | 同物异名 | 盐/酯/描述词差异 | 非药品/化妆 | 市场确实没有 |
|---|---|---|---|---|---|---|
| **CN → US** | 100 | **78** | **6** | 0 | 1 | **15** |
| **US → CN** | 100 | **63** | **2** | **6** | 16 | **13** |

- **「查不到」的一半不是缺药，是「同一盒药两边叫法不同」**：CN 侧 22 条缺口里 **6 条**（葡萄糖/扑尔敏/头孢氨苄/开塞露/甘露醇/格列本脲）、US 侧 37 条里 **8 条**（右美沙芬、曲安奈德、奥美沙坦酯、樟脑、薄荷脑、聚维酮碘、甘油、扑尔敏）在对方市场**都有**，只是名字写法不同 → **task-141 的别名/盐型归一能立刻把这些补上，零新增数据源**。
- **16 条 US 缺口根本不是「药」**：防晒活性成分 7 条（Octisalate 3,309、Avobenzone 2,734、Octocrylene 2,684、Homosalate 2,526、Octinoxate 1,702、Oxybenzone 454、Titanium Dioxide 2,689）+ 非药品 9 条（酒精 2,899、异丙醇、氧、氟化钠、二甲基硅油、凡士林、铝盐止汗剂、吡硫翁锌）→ 应标「非药品/化妆品成分」，**不要补进药品对照**。
- **28 条是市场性差异**（15 + 13）：诺氟沙星 1,044、安乃近 1,029、头孢哌酮 918、氨溴索 894、罗红霉素 875（US 未上市）；苯肾上腺素 1,549、多西拉敏 455、托萘酯 346、多库酯 334、镁乳 307、右苯丙胺 293、氢可酮 244（CN 未上市/受控）。→ 页面要能说「该市场未收录/未上市」，而不是让用户以为数据缺了。

**一句话**：产品数 477,098 不小，缺的是**别名映射**与**口径标注**；先把这两件事做完，比继续堆数据更能提升「查得到」。

## 1. 方法

- 每侧按「该国有产品的不同 `product_id` 数」取成分 Top100（`variant → substance` 汇总）。
- 对每条缺口按优先级归因：`present`（同 `substance_id` 有产品）→ `synonym`（同物异名组，如 Glibenclamide/Glyburide）→ `same_base`（去掉盐/酯/水合物/描述词后 base 相同，如 Dextromethorphan HBr / Dextromethorphan、Povidone Iodine / Povidone-Iodine）→ `non_drug`（辅料/气体/溶剂/止汗）→ `cosmetic`（防晒活性物）→ `market_absent`。
- 归一化：小写 + 标点转空格（修 `Povidone-Iodine`）；盐/酯词表含 `medoxomil / cilexetil / axetil / acetonide …`。
- 已知局限：按**包装级产品数**排 Top100，会被「同一成分多规格多包装」放大（如葡萄糖 6,546）；名称层无成分产品（3,911）不在本表。

## 2. CN Top100 → US：22 条缺口

| # | 判定 | 成分（中文） | CN 产品 | US 侧同物候选 |
|---|---|---|---|---|
| 1 | **同物异名** | Glucose 葡萄糖 | 6,546 | **Dextrose 211**（+ Anhydrous Dextrose 7、Unspecified 38） |
| 10 | **同物异名** | Chlorphenamine 马来酸氯苯那敏 | 1,164 | **Chlorpheniramine 277** |
| 13 | 市场没有 | Norfloxacin 诺氟沙星 | 1,044 | — |
| 14 | 市场没有 | Metamizole 安乃近 | 1,029 | — |
| 21 | 市场没有 | Cefoperazone 头孢哌酮钠 | 918 | — |
| 22 | 市场没有 | Ambroxol 盐酸氨溴索 | 894 | — |
| 23 | 市场没有 | Roxithromycin 罗红霉素 | 875 | — |
| 32 | **同物异名** | Cefalexin 头孢氨苄 | 688 | **Cephalexin 182** |
| 33 | 市场没有 | Cefradine 头孢拉定 | 684 | — |
| 37 | **同物异名** | Glycerol 开塞露 | 613 | **Glycerin 299** |
| 41 | 市场没有 | Berberine 盐酸小檗碱 | 581 | — |
| 47 | **非药品** | Water For Injection 灭菌注射用水 | 547 | — |
| 52 | 市场没有 | Piracetam 吡拉西坦 | 521 | — |
| 58 | 市场没有 | Oxytetracycline 土霉素 | 461 | — |
| 62 | 市场没有 | Troxerutin 曲克芦丁 | 433 | — |
| 74 | 市场没有 | Acetylspiramycin 乙酰螺旋霉素 | 377 | — |
| 81 | 市场没有 | Glycyrrhizin 甘草酸单铵 | 366 | — |
| 89 | 市场没有 | Citicoline 胞磷胆碱钠 | 336 | — |
| 93 | 市场没有 | Potassium Dehydroandrographolide Succinate 穿琥宁 | 322 | — |
| 94 | **同物异名** | Manitol 甘露醇（拼写） | 320 | **Mannitol 12** |
| 95 | **同物异名** | Glibenclamide 格列本脲 | 317 | **Glyburide 84** |
| 97 | 市场没有 | Mecobalamin 甲钴胺 | 315 | —（AU 440 / GB 5 有） |

## 3. US Top100 → CN：37 条缺口

| # | 判定 | 成分 | US 产品 | CN 侧同物候选 |
|---|---|---|---|---|
| 3 | 化妆品 | Octisalate | 3,309 | — |
| 4 | 非药品 | Alcohol | 2,899 | — |
| 5 | 化妆品 | Avobenzone | 2,734 | — |
| 6 | 化妆品 | Titanium Dioxide | 2,689 | — |
| 7 | 化妆品 | Octocrylene | 2,684 | — |
| 8 | 化妆品 | Homosalate | 2,526 | — |
| 9 | **盐型差异** | Dextromethorphan Hydrobromide | 1,982 | **Dextromethorphan 183** |
| 12 | 化妆品 | Octinoxate | 1,702 | — |
| 14 | 市场没有 | Phenylephrine | 1,549 | — |
| 19 | 非药品 | Sodium Fluoride | 1,093 | — |
| 23 | 非药品 | Isopropyl Alcohol | 685 | — |
| 29 | 非药品 | Oxygen | 597 | — |
| 32 | 非药品 | Aluminum Sesquichlorohydrate | 574 | — |
| 33 | 非药品 | Dimethicone | 569 | — |
| 38 | 非药品 | Petrolatum | 530 | — |
| 45 | 市场没有 | Doxylamine | 455 | — |
| 46 | 化妆品 | Oxybenzone | 454 | — |
| 47 | **描述词差异** | Camphor (Synthetic) | 452 | **Camphor 40** |
| 49 | 市场没有 | Aluminum Zirconium Tetrachlorohydrex Gly | 429 | — |
| 53 | **描述词差异** | Menthol, Unspecified Form | 411 | **Menthol 18** |
| 54 | 非药品 | Aluminum Chlorohydrate | 398 | — |
| 63 | 市场没有 | Tolnaftate | 346 | — |
| 64 | 非药品 | Pyrithione Zinc | 344 | — |
| 67 | 市场没有 | Bacitracin Zinc | 336 | —（CA 40） |
| 69 | 市场没有 | Docusate | 334 | — |
| 74 | 市场没有 | Magnesium Hydroxide | 307 | — |
| 75 | **酯型差异** | Olmesartan Medoxomil | 305 | **Olmesartan 194** |
| 79 | 同物异名 | Glycerin | 299 | **Glycerol 613** |
| 80 | **酯型差异** | Triamcinolone Acetonide | 299 | **Triamcinolone 281** |
| 82 | 市场没有 | Dextroamphetamine | 293 | — |
| 83 | 市场没有 | Amphetamine | 289 | — |
| 84 | 市场没有 | Pramoxine | 289 | — |
| 87 | 同物异名 | Chlorpheniramine | 277 | **Chlorphenamine 1,164** |
| 96 | **标点差异** | Povidone Iodine | 248 | **Povidone-Iodine 198** |
| 97 | 市场没有 | Bismuth Subsalicylate | 245 | — |
| 99 | 市场没有 | Sennosides | 245 | — |
| 100 | 市场没有 | Hydrocodone Bitartrate | 244 | — |

## 4. 给 task-141 的输入（可直接落规则表）

1. **同物异名（8 组已确认，可先加）**：glucose↔dextrose、chlorphenamine↔chlorpheniramine、glycerol↔glycerin/e、manitol↔mannitol、glibenclamide↔glyburide、salbutamol↔albuterol、lignocaine↔lidocaine、cefalexin↔cephalexin、cefradine↔cephradine、amoxycillin↔amoxicillin。
2. **标点归一**：连字符/逗号/括号统一为空格（`Povidone-Iodine` 一类）。
3. **盐/酯/描述词词表**：现有 `SALT_TOKENS` 已含 `medoxomil / acetonide / hbr / hydrate…`，再补 `unspecified form / synthetic / [盐] monohydrate` 等描述词。
4. **非药品白名单**：酒精、异丙醇、氧、注射用水、氟化钠、二甲基硅油、凡士林、铝盐止汗剂、吡硫翁锌、防晒 7 种 → 产品/成分页标「非药品/化妆品成分」，不参与药品对照。
5. **「市场未上市」文案**：成分页/名字页在该市场无产品时，注明「本市场未收录/未上市」，避免被读成数据缺失（配合 `coverage.html` 口径）。

## 5. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/crossref_audit.py --top 100          # 打印分类计数 + 每条缺口的同物候选
& $py db/crossref_audit.py --top 100 --quiet  # 只写 CSV
```

产物：
- `data/sources/crossref-audit-20261030.csv`（200 行：side/rank/substance_id/inn_en/inn_zh/home_n/partner_n/verdict/base/partner_candidates）
- 脚本 `db/crossref_audit.py`（只读；不写库、不发版）

## 6. 边界

- 只做**身份对照**：不说「可替代」、不给剂量、不判断疗效等价。
- Top100 是产品数口径，不等于「临床最常用」；后续可按 ATC 类目或处方量口径再审计（数据源待定）。
- 名称层无成分产品（3,911：US 2,229 / AU 1,495 / MX 121 / SG 66）不在本表，需单独补成分（已列 task-140 后续）。
