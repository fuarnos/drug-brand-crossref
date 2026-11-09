# 剂型 / 规格 / 释放机制 / 包装 四类字段一致性审计（2026-11-10）

> 触发：「力度伸是 VC 泡腾片，站点显示片剂」。泡腾只是同一族错误里的一格，
> 本报告系统扫描四类字段里「来源原文与归一化字段自相矛盾」的记录。
> 只读审计：不写库、不改 `site/build.py`、不构建。可复跑脚本
> [`db/consistency_audit_form.py`](../db/consistency_audit_form.py)。

## 结论

- 全库 **477,098** 个 `product` / **628,013** 个成分行，七条规则命中如下
  （每条规则的条数**互不包含**，但同一条产品可能同时踩多条规则，不要直接相加）：

  | 规则 | 内容 | 条数 |
  |---|---|---|
  | R1 | 剂型族 × `form_base` 不符（硬冲突 + 子类缺失 + 归一化回退） | **28,542** |
  | R2 | `form_base` 回退成原文整串 | 2,187 |
  | R3 | 释放机制与原文不符（及反向） | 10,272 |
  | R4 | 规格异常（含「根本没有强度」） | 175,521 |
  | R5 | 包装异常（含 pack 只有数字） | 27,075 |
  | R6 | 重复身份 | 109 |
  | R7 | `form_base` 空 / unknown / other | 20,099 |

- **最大的剂型错不是泡腾**：原文写注射剂（`injection` / `vial` / `infusion` /
  `pre-filled syringes`）却被归成 `liquid` 的有 **15,570 行**，占 R1 硬冲突
  （20,188 行）的 77%。根因是 `FORM_BASES` 的匹配顺序把 `liquid` 排在
  `injection` 之前，`"injection, solution"` 里先命中了 `solution`
  （[`etl/ingest_openfda_ndc.py:96`](../etl/ingest_openfda_ndc.py#L96)）。
- 泡腾族的真实规模：**947 行命中泡腾原文，827 行落到 `form_base='tablet'`、92 行落到
  `powder`、28 行落到 `liquid`**——泡腾根本没有对应取值，`form_base_of()` 只是返回了
  最近的关键词族。同族还有咀嚼片 2,851 行、口崩/口溶 2,313 行、贴剂 76 行
  （该格与膏/霜共用 `topical` 组，只看 `topical_patch` 条目是 58 行）。
  （按原文全文匹配是 829 行 `tablet`，差 2 行被更高优先的族先命中；见 R1 明细。）
- **规格侧最大的问题不是单位写错，是「根本没有强度」**：64,718 个产品（13.6%）一个强度值
  都没有（HK 13,935 / US 13,531 / GB 9,744 / TW 8,671 / MX 7,046 / AU 6,427 / CN 5,101…），
  而站点的唯一性口径是「国家 × 剂型 × 规格 × 成分」——缺规格的产品在结构上就无法唯一。
  这一档 90% 是来源没给，属**不能猜**，只能标注并计数。
- 释放机制：AU 1,820 行原文写 `controlled release` / `enteric` 但 `release='none'`
  （AU 的 ingest 根本不算 release）；反向 8,392 行 `release` 有值、剂型原文却没有释放词
  （CN 5,985 / ES 2,151），根因是按商品名推的（奥施康定、倍他乐克）——不算错，但页面上
  「剂型=片剂、释放=缓释」缺一个依据说明。
- 重复身份只有 **109 行**（88 组，全在 CN，同一批文号 + 同包装 + 同强度出现 2–7 次）。
  这一条我先按「同成分同规格」判，误报 15.8 万行（把所有仿制药都撞成一组），改成
  「同批文 + 同商品名 + 同包装」后收敛到 109——**判重键必须带名字**，这条经验要写进
  以后任何 dedup 脚本。
- 用户报的泡腾专项报告 `reports/form-effervescent-20261110.md` **目前不存在**（本目录
  下没有该文件），所以泡腾这一格我在 R1 里自己算了一遍，没有重复别人的工作。

## Top 10 问题（按影响面排序）

| # | 问题 | 条数 | 影响 | 修法 | 工作量 |
|---|---|---|---|---|---|
| 1 | 原文写注射剂（`injection, solution` / `infusion` / `vial` / `pre-filled syringe`），`form_base` 却是 `liquid` | **15,570** | 站点卡片把注射剂显示成「液体」：给药途径、不可互换判断、检索筛选全错；GB 8,589 / US 6,114 / SG 1,151 | 归一化规则（改 `FORM_BASES` 优先级：`injection` 必须排在 `liquid` 前） | M |
| 2 | 原文写粉剂/颗粒/散（`powder for solution` / `granule` / `sachet`），`form_base` 是 `liquid` | **3,304** | 固体粉末显示成液体；CA `Powder For Solution` 1,636 行为主 | 归一化规则（`powder` 排在 `liquid` 前） | S |
| 3 | 子类没有取值：泡腾 / 咀嚼 / 口崩口溶 / 贴片 全被吞进 `tablet` | **6,387**（泡腾 827 + 咀嚼 3,171 + 口崩口溶 2,313 + 贴剂 76） | 用户报的力度伸就在这一族；泡腾片要溶水、咀嚼片要嚼、口崩片含服、贴片贴皮，显示成「片剂」直接误导给药动作 | 归一化规则 + 新增 `form_base` 取值（`effervescent` / `chewable` / `orodispersible` / `patch`）+ 站点/检索层同步 | L |
| 4 | 产品完全没有强度值（不是单位错，是空的） | **64,718 个产品**（101,280 个成分行） | 唯一性四要素缺一：这些产品之间无法靠规格区分，跨国对应会给出无法核对的候选 | 来源本身（US openFDA 部分 NDC、HK 名称层、TW、MX 浓度空缺）；显示层标注「来源未给规格」并计数 | S |
| 5 | 液体/注射类有强度但**没有 per_volume**（每容量），浓度不可计算 | **70,196 行**（占液体/注射成分 174,881 行的 40.1%） | `500 mg` 是一支还是一瓶？同成分不同浓度的产品无法区分，碰撞分级也判不了 | 迁移脚本（把 `mg/mL` 写进 `strength_unit` 而不是留空 `per_volume`）+ 来源本身（CN 29,060 / US 12,570 / CA 10,943） | L |
| 6 | 原文写缓释/控释/肠溶，`release='none'` | **1,880**（AU 1,820 / SG 54 / CA 6） | AU `Tablet, enteric coated` 644 行、`(controlled release)` 1,176 行被当成普通片：碰撞视图该出 `warning` 的地方出不来 | 归一化规则（AU/SG 的 ingest 没算 release，`release_of()` 也不认 enteric/controlled） | S |
| 7 | `release` 有值但剂型原文没有任何释放词 | **8,392**（CN 5,985 / ES 2,151 / TW 102 / MX 91 / CA 53 / GB 10） | 不算错（按商品名推的，如奥施康定、倍他乐克 ZOK、liberación prolongada），但页面上「剂型=片剂、释放=缓释」缺依据 | 显示层（在 release 旁标「据商品名/通用名推断」），其中 GB 10 行是真误判 | S |
| 8 | `form_base` 回退成原文整串（归一化没命中，直接把 VMP 全名存进去） | **2,187**（GB 1,533 / ES 213 / US 187 / CA 151） | 卡片上「剂型」一栏显示 `Indometacin 100mg suppositories` 这种整串名字，检索/筛选按剂型全部失效 | 归一化规则（词表补复数与西语：`suppositories` / `pessaries` / `plasters` / `implantes`） | S |
| 9 | `pack` 只有数字、没有单位 | **26,840**（CA 16,267 / AU 10,573） | 「包装：100」无法判断是 100 片还是 100 mL，比较页上等于没写 | 显示层（按 `form_base` 拼单位：tablet→片、liquid→mL） | S |
| 10 | `form_base` 为空 / `unknown` / `other` / `null` | **20,099**（HK 13,935 / AU 5,737 / CN 367 / ES 29） | 无法按剂型展示与筛选；HK 全库 100% 无剂型（名称层来源），AU 4,730 行原文就是 `not stated` | 来源本身（93%：HK / AU tga_cmi）；另 1,369 行（AU artg_export 1,002 + CN 367）可用迁移脚本兜底 | S |

附（不进 Top 10，但同批发现，都是「小数」）：

| 问题 | 条数 | 修法 |
|---|---|---|
| 产品没有成分行（`product_component` 无记录） | 3,911（US 2,229 / AU 1,495 / MX 121 / SG 66） | 迁移脚本（US 多为 `kit`，成分表为空是正常，需按 `form_base='kit'` 豁免） |
| 强度值为 0 或负数 | 91（MX 30 / AU 49 / ES 4 / CA 4） | 归一化规则（`0 IU`、`QS`、`nil` 应在入库时判为「未给」而不是 0） |
| 强度量级离谱（>100,000 质量单位） | 35（AU 33 / US 2） | 迁移脚本（`Xylocard 500 500mg/5mL` 被拼成 `500500`） |
| 强度量级过小（<0.0001） | 6（CA 5 / AU 1） | 迁移脚本（`7e-05 mg` 实际应是 `70 µg`） |
| 有强度值但单位为空 | 2 | 归一化规则 |
| 同成分同国家同时存在 `g` 与 `mg` 写法 | 74 个（成分 × 国家）组合，**0 个**数值等价对 | 归一化规则（不构成重复身份，只是单位词表不统一） |
| 复方内跨单位尺度（mg + µg + %） | 3,974（AU 2,210 / CA 1,388） | 显示层（多数是不同成分天然量级不同，不算错，只是同一行里单位不齐） |
| MX `dosage_form` 被填成厂家名（`boehringer ingelheim promeco` / `gelpharma`），`form_base` 因 `gel` 子串被归成 `topical` | 21 | 来源本身（COFEPRIS 导出串列）+ 归一化规则（`\bgel\b` 词边界） |
| 重复身份（同批文 + 同商品名 + 同强度 + 同包装） | 109 行 / 88 组（全 CN，`nhsa`） | 迁移脚本（要人拍板：同一批文号 7 行只留 1 行还是保留多医保代码） |

## 哪些能规则化自动修，哪些必须人工判断

### A. 能规则化自动修（改纯函数 + 单测 + 重灌，结论可复核）

1. **`FORM_BASES` 匹配顺序与词表**（一次改完，覆盖 R1 的 20,188 条硬冲突里的 19,000+）：
   - 顺序：`injection` / `inhalation` / `suppository` / `topical`（粘贴/外用）必须排在
     `liquid` 之前；`powder` 排在 `liquid` 之前。现在的顺序是 `tablet, capsule, liquid,
     injection, topical, inhalation, suppository, powder`，`liquid` 在第 3 位。
   - 词表补：`suppositor(y|ies)`、`pessar(y|ies)`、`plaster(s)`、`implant(s)`、
     `pessary`、`ovule`、`óvulo`、`implante`、`chicle`、`perlas`、`barniz` 等（R2 的 2,187 行
     全是词表缺口）。
   - 词边界：`\bgas\b`（否则 `gastro-resistant` 命中）、`\botic\b`（否则 `antibiotic`）、
     `\bgel\b`（否则 `ingelheim` / `gelpharma` → MX 21 行的错就出在这）。
   - 单测：把本报告 R1 的 14 个大格做成 `etl/test_*.py` 的用例（输入原文 → 期望 `form_base`）。
2. **新增 `form_base` 取值**（泡腾/咀嚼/口崩口溶/贴片/棒剂/微丸/试剂盒/植入）：先加枚举，
   再加规则，再动站点与检索的展示映射。**枚举要先定**，否则改了规则也没有地方落。
3. **`release_of()` 扩展**：`controlled release` / `prolonged release` / `modified release` /
   `enteric` / `gastro-resistant` / `肠溶` / `缓释` 都要认；AU（`artg_export` / `pbs`）和
   SG（`hsa_sg`）的 ingest 目前根本不调用它——这是 1,880 行的全部来源。
4. **`pack` 只有数字时按剂型补单位**（显示层，不动库，26,840 行）。
5. **`release` 依据标注**（显示层，8,392 行）：页面在 `release` 旁标「据商品名推断」。

### B. 必须人工判断（按纪律：判不了就丢弃并计数，不硬改）

1. **64,718 个产品没有任何强度**：不能从商品名、包装或另一种盐型反推——反推就是剂量换算，
   踩 §9 红线。处理方式：显示层标注「规格来源未给」，并在报告/覆盖率里如实计数。
2. **70,196 行液体缺 per_volume**：CN 医保库写「10mg」、US NDC 写「10 mg」都不带容量；
   用 `pack` 里的「10支/盒」去反推每支容量＝猜。只能等来源补，或人工抽样核对说明书。
3. **重复身份 109 行**：同一批文号在 CN 医保库里对应多条医保代码（不同支付标准/包装描述），
   删哪一条是业务决定，需要人拍板（不是技术判断）。
4. **GB 10 行「glutaraldehyde modified 花粉疫苗」→ `release='ER'`**：`modified` 在变态反应
   领域指「化学修饰变应原」，与缓释无关。规则可以排除，但**「modified 出现在哪些语境下不算
   缓释」需要人确认**，所以这 10 行先计数、不自动改。
5. **MX 21 行 `dosage_form` 是厂家名**：来源导出串列，得回去核对 COFEPRIS 原始记录。

### C. 来源本身（改不了，只能如实标注）

- HK（`hk_dh`）13,935 行：名称层来源，没有剂型/规格/包装，`form_base` 全空、`pack` 全空。
- AU `tga_cmi` 4,730 行：原文就是 `not stated`。
- GB / ES / HK / MX / SG 五个市场的 `pack` **100% 为空**（来源就没这个字段）。
- MX 强度约七成空缺、CN 商品名多数为空（122,133 个产品没有 primary 名称，占 25.6%）。

> 红线复核：本报告只做身份对应与「不可互换」提示所需的字段核对，**没有**给出任何用药建议、
> 剂量换算或替代判断。

## 明细

### R1 剂型族 × 当前 `form_base`（28,542 = 硬冲突 20,188 + 子类缺失 5,829 + 回退 2,525）

判定分四档，判据写在脚本的 `FAMILIES` 表里（顺序即优先级，命中即停）：

- `ok` 原文族与 `form_base` 相符（426,352 行，89.4%）
- `conflict` **跨族/跨相态/跨途径的硬矛盾**——这一档才是必须修的错（20,188）
- `gap` 同族同相态但子类有实质差异、当前没有对应枚举（5,829）
- `unmapped` `form_base` 为空 / `unknown` / `other` / 回退成原文整串（2,525）
- `coarse` 同族同相态的粗粒度（滴眼剂→`liquid`、鼻喷→`topical`），不算错（2,004）

| 原文剂型族（`group`） | 命中 | ok | conflict | gap | unmapped | coarse | 该族最大的误归类格 |
|---|---|---|---|---|---|---|---|
| 片剂 / 锭 / 丸（`tablet`） | 173,858 | 173,727 | 1 | 0 | 25 | 105 | — |
| 注射（针/瓶/安瓿/预充）（`injection`） | 86,880 | 71,308 | 15,572 | 0 | 0 | 0 | `liquid`=15,570 / `tablet`=2 |
| 胶囊 / 胶丸（`capsule`） | 54,111 | 54,097 | 3 | 5 | 6 | 0 | `tablet`=5 / `topical`=3 |
| 外用（膏/霜/凝胶/贴/气雾）（`topical`） | 46,295 | 44,672 | 130 | 0 | 662 | 831 | `tablet`=76 / `capsule`=54 |
| 液体（溶液/混悬/糖浆/滴剂）（`liquid`） | 44,730 | 44,657 | 3 | 0 | 70 | 0 | — |
| 粉 / 颗粒 / 散（`powder`） | 13,594 | 10,157 | 3,354 | 0 | 83 | 0 | `liquid`=3,304 / `capsule`=35 / `injection`=15 |
| 微丸 / 滴丸（`pellet`） | 7,392 | 7,391 | 0 | 0 | 1 | 0 | — |
| 眼用（滴眼/眼膏）（`ophthalmic`） | 4,918 | 4,848 | 63 | 0 | 7 | 0 | `injection`=46 / `liquid`=17 |
| 吸入（气雾/粉雾/雾化）（`inhalation`） | 3,493 | 2,904 | 29 | 0 | 20 | 540 | `topical`=28 / `injection`=1 |
| 咀嚼（片/胶）（`chewable`） | 3,315 | 0 | 41 | 3,171 | 103 | 0 | `tablet`=2,851 / `gum, chewing`=320 |
| 肠溶 / 胃溶 resistant（`enteric`） | 3,126 | 3,124 | 2 | 0 | 0 | 0 | `liquid`=2 |
| 试剂盒 / 放射性药盒（`kit`） | 2,919 | 2,319 | 118 | 248 | 234 | 0 | `liquid`=237 / `tablet`=73 / `topical`=31 |
| 栓剂 / 直肠 / 阴道用（`suppository`） | 2,673 | 1,729 | 0 | 0 | 460 | 484 | — |
| 棒剂 / 尿道棒（`stick`） | 2,610 | 2,491 | 0 | 0 | 119 | 0 | — |
| 口崩 / 口溶（膜/片）（`orodispersible`） | 2,502 | 0 | 0 | 2,313 | 189 | 0 | `tablet`=2,313 |
| 医用气体 / 气瓶（`gas`） | 1,199 | 986 | 0 | 0 | 195 | 18 | — |
| 泡腾（片/颗粒）（`effervescent`） | 947 | 0 | 855 | 92 | 0 | 0 | `tablet`=827 / `powder`=92 / `liquid`=28 |
| 鼻用（`nasal`） | 820 | 820 | 0 | 0 | 0 | 0 | — |
| 其他杂项剂型（`other`） | 543 | 456 | 0 | 0 | 87 | 0 | — |
| 含漱 / 漱口（`mouthwash`） | 519 | 402 | 2 | 0 | 115 | 0 | — |
| 植入剂 / 宫内·阴道装置（`implant`） | 244 | 57 | 12 | 0 | 149 | 26 | — |
| 耳用滴剂（`otic`） | 210 | 207 | 3 | 0 | 0 | 0 | `injection`=2 / `powder`=1 |

最大的 14 个「族 × `form_base`」格（判定为 `conflict`/`gap`/`unmapped`）：

| # | 原文族 | 当前 `form_base` | 判定 | 条数 |
|---|---|---|---|---|
| 1 | `injection` | `liquid` | conflict | 15,570 |
| 2 | `powder` | `liquid` | conflict | 3,304 |
| 3 | `chewable` | `tablet` | gap | 2,851 |
| 4 | `orodispersible` | `tablet` | gap | 2,313 |
| 5 | `effervescent` | `tablet` | conflict | 827 |
| 6 | `topical` | `unknown` | unmapped | 447 |
| 7 | `chewable` | `gum, chewing` | gap | 320 |
| 8 | `kit` | `liquid` | gap | 237 |
| 9 | `kit` | `other` | unmapped | 198 |
| 10 | `stick` | `unknown` | unmapped | 112 |
| 11 | `effervescent` | `powder` | gap | 92 |
| 12 | `topical` | `tablet` | conflict | 76 |
| 13 | `kit` | `tablet` | conflict | 73 |
| 14 | `topical` | `capsule` | conflict | 54 |

按市场 / 来源（硬冲突 20,188）：GB 8,833 / US 7,142 / CA 2,074 / SG 1,223 / AU 553 /
CN 136 / ES 134 / TW 81 / MX 12；来源 `dmd` 8,833 / `openfda_ndc` 7,142 / `hc_dpd` 2,074 /
`hsa_sg` 1,223（四个来源占 97%）。

样例（硬冲突）：

- `US-0409-6727` · 镁硫酸盐葡萄糖注射液 · 原文 `injection, solution` → `form_base='liquid'`
- `GB-549511000001107` · `Indometacin 100mg suppositories` → `form_base='indometacin 100mg suppositories'`（回退整串）
- `TW` · `穿皮貼片劑`（经皮贴片）37 行 + `貼片劑` 16 行 → `form_base='tablet'`（`片` 命中 `tablet`）
- `CN` · `片剂(泡腾)` 70 行、`片剂(泡腾片)` 14 行、`阴道泡腾片剂` 3 行 → `tablet`
- `US` · `tablet, chewable` → `tablet`；`tablet, orally disintegrating` → `tablet`

泡腾族按国（原文全文匹配 `form_base='tablet'`，合计 829）：AU 226 / GB 212 / US 131 /
ES 97 / CN 94 / CA 32 / TW 20 / MX 9 / SG 8。另有 92 行泡腾颗粒→`powder`、28 行泡腾溶液→
`liquid`，这两档算 `gap`（同相态的粗粒度），不算错。

> 未命中任何族 20,200 行：HK `unknown` 13,946、AU `not stated` 4,810、其余为零散
> （`Herb, dried`、`Toothpaste`、`缓释制剂`、`膜剂` 等）。这 20,200 行不进矩阵，
> 在 R7 / 覆盖率里计数，不当作「归类错」。

### R2 `form_base` 回退成原文整串（2,187）

- 判据：`form_base` 不在脚本的 `KNOWN_BASES` 词表内，或长度 > 25、或含数字（canonical 取值
  既不含数字也不会这么长）。
- 分布：GB 1,533 / ES 213 / US 187 / CA 151 / AU 59 / MX 39 / SG 5；
  来源 `dmd` 1,533、`cima` 213、`openfda_ndc` 187、`hc_dpd` 151。长度 > 60 字符的 94 行。
- 根因：`form_base_of()` 没命中任何关键词时 `return f or "unknown"`，把整串原文当剂型值返回。
  GB 的 VMP 名是「通用名 + 强度 + 剂型」，所以整串被存进来。
- Top 值：`dialisis peritoneal` 36、`chlorhexidine gluconate 0.2% mouthwash` 32、`irrigant` 28、
  `dressing` 26、`film, soluble` 26、`clotrimazole 500mg pessaries` 26、`chicle` 26、
  `mouthwash/gargle` 26、`amorolfine 5% medicated nail lacquer` 25。
- 修法：**归一化规则**（词表 + 复数归一 + 西语词表），S。

### R3 释放机制（10,272）

| 方向 | 条数 | 分布 |
|---|---|---|
| 原文有 ER 词（缓释/控释/长效/`controlled release`/`prolonged`），`release='none'` | 1,182 | AU 1,176 / CA 6；`artg_export` 1,137 |
| 原文有 DR 词（`enteric` / `gastro-resistant` / 肠溶），`release='none'` | 698 | AU 644 / SG 54；`artg_export` 496、`pbs` 146、`hsa_sg` 54 |
| `release` 有值但剂型原文无任何释放词（反向） | 8,392 | CN 5,985 / ES 2,151 / TW 102 / MX 91 / CA 53 / GB 10 |
| 原文与 `release` 类别矛盾（原文 DR 但标 ER，或反之） | 46 | — |

样例：

- `AU-13420H-metrol-xl` · `METOPROLOL SUCCINATE Tablet 190 mg (controlled release)` → `release='none'`
- `AU-10295W-noxicid-caps` · `esomeprazole 20 mg enteric capsule` → `release='none'`
- `GB-5017511000001105` · `12 grass mix (B2) glutaraldehyde **modified** 1,800units/3ml vaccine
  solution for injection vials` → `release='ER'`（反向误判：`modified` 是「化学修饰变应原」）
- `CN` · `奥施康定` / `倍他乐克`，剂型 `片剂` → `release='ER'`（按商品名推，正确但依据不可见）

修法：前两档 **归一化规则**（S）；反向档 **显示层**（S）＋ GB 10 行人工确认（见 §B.4）。

### R4 规格（175,521，含「根本没有强度」）

| 子项 | 条数 | 说明 |
|---|---|---|
| 强度值为空 | 101,280 成分行 / **64,718 产品** | HK 22,302 / TW 20,858 / US 20,145 / GB 12,185 / MX 9,756 / AU 6,904 / CN 6,457 |
| 值为 0 或负 | 91 | MX 30 / AU 49 / ES 4 / CA 4；`0 IU`、`QS`、`nil` |
| 单位空但有值 | 2 | — |
| 量级 > 100,000（质量单位） | 35 | AU 33 / US 2；`Xylocard 500 500mg/5mL` → `500500` |
| 量级 < 0.0001 | 6 | CA 5 / AU 1；`7e-05 mg` 应是 `70 µg` |
| 同成分同国家 g/mg 并存 | 74 组合 | **0 个数值等价对** → 不是重复身份，只是单位词表不统一 |
| 液体/注射有强度无 per_volume | **70,196 行** | 占 174,881 行的 40.1%；CN 29,060 / US 12,570 / CA 10,943 / GB 7,022 / AU 4,233 / ES 4,024 |
| 复方内跨单位尺度 | 3,974 | AU 2,210 / CA 1,388；多为不同成分天然量级不同，只作提示 |
| 产品无成分行 | 3,911 | US 2,229 / AU 1,495 / MX 121 / SG 66；多为 `kit` |

样例：

- `US-0409-7650` · `heparin sodium` · `injection, solution` —— **一个强度都没有**（该行 pack 有 250 mL）
- `US-66949-139` · `afco 5508 sanifect foam` · `2,081,980 mg / 208,198 mL`（量级离谱但自洽，源数据如此）
- `AU-ARTG-12036-xylocard-500` · `500500 mg`（原文 `Xylocard 500 500mg/5mL`，两个 500 被拼起来）
- `CA-00555118` · `neo bex` · `0.00007 mg`（应为 70 µg，单位选错）
- `ES-34887` · `auxina a e fuerte` · `0 IU`（源写 0，实为未给）

修法：**迁移脚本**（0/负值、量级、`g`↔`mg`、`mcg`↔`microgram`）+ **来源本身**（强度全空、
per_volume 空缺——不能反推，见 §B）。

### R5 包装（27,075）

| 子项 | 条数 | 分布 |
|---|---|---|
| `pack` 只有数字、没有单位 | 26,840 | CA 16,267 / AU 10,573（`hc_dpd` 16,267、`artg_export` 6,402、`pbs` 4,017） |
| 固体剂型 `pack` 只写容量、没有数量 | 91 | US 42 / CA 32 / AU 11 / CN 6 |
| 液体/注射剂型 `pack` 只写数量 | 144 | 全 CN（`滴剂` 写 `30粒/盒`、`注射剂` 写 `1瓶/盒`） |
| `pack` 是占位符（`Na` / `N/A`） | 7 | — |

`pack` 空值率按市场：

| 市场 | 产品数 | pack 空 | 空值率 |
|---|---|---|---|
| CN | 145,051 | 3 | 0.0% |
| US | 110,179 | 396 | 0.4% |
| TW | 16,457 | 70 | 0.4% |
| CA | 43,847 | 10,605 | 24.2% |
| AU | 44,794 | 18,422 | 41.1% |
| GB | 61,051 | 61,051 | **100%** |
| ES | 25,395 | 25,395 | **100%** |
| HK | 13,935 | 13,935 | **100%** |
| MX | 10,878 | 10,878 | **100%** |
| SG | 5,511 | 5,511 | **100%** |

矛盾判定刻意要求「只出现另一类的量词」：CN 的 `160ml高密度聚乙烯瓶，120片/盒` 同时含容量与
数量，不算矛盾（否则会误报上万行）。修法：**显示层**（S）。

### R6 重复身份（109 行 / 88 组）

- 键：有 `approval_id` 时 = 国家 + 批文号 + 商品名 + 强度 + 包装 + 成分；
  没 `approval_id` 时 = 国家 + 商品名 + MAH + `form_base` + **非空** pack + 成分。
- 结果：109 行多余（88 组，组大小 2 的 83 组、3 的 1 组、7 的 4 组），全部 CN / `nhsa`，
  0 组跨来源。样例：`国药准字h10973014` + `一次性使用无菌注射器装入注射器铅防护套，1支/支` → 7 行。
- **无法判定并计数**（按纪律丢弃，不硬改）：
  - `undecidable_no_strength` **61,594** 行：所有成分强度都为空，判不了；
  - `undecidable_no_key` 7 行：既无批文号也无包装；
  - 另外 122,133 个产品没有 primary 名称（25.6%），去重键里的名字维度对它们是空的。
- 过程记录：v1 判据（不带名字、不带批文号）报 158,756 行，全是把同成分同规格的不同品牌撞成
  一组；v2（带名字与 MAH）降到 9,035；v3（批文号 + 强度 + 包装 + 名字）收敛到 109。
  **判重键必须带名字**，这条要写进以后的 dedup 脚本。

### R7 空值族（20,099）

| 市场 | 条数 | 来源 |
|---|---|---|
| HK | 13,935 | `hk_dh`（名称层，无剂型字段） |
| AU | 5,737 | `tga_cmi` 4,730（原文 `not stated`）+ `artg_export` 1,002 |
| CN | 367 | `nhsa` 364（`体外诊断试剂` 142、`缓释制剂` 93、`控释制剂` 9…） |
| ES | 29 | `cima`（原文 `null`） |
| TW | 16 | `tfda_tw` |
| MX | 11 | `cofepris_mx` |
| GB | 3 | `dmd` |
| SG | 1 | `hsa_sg` |

`form_base` 取值：空 13,943 / `unknown` 5,872 / `other` 255 / `null` 29。

Top 30 原始 `dosage_form`（完整列表见 JSON 的 `detail.top_raw_dosage_form`）：
`unknown` 13,946、`not stated` 4,810、`Essential Oil` 166、`体外诊断试剂` 142、
`Drug delivery system, transdermal` 136、`Herb, dried` 124、`Diluent, not applicable` 105、
`Stick` 96、`缓释制剂` 93、`Application` 73、`Wafer` 46、`Liniment` 33、
`放免诊断试剂盒` 31、`Gas, medicinal` 31、`null` 29、`Oil` 20、`植入剂` 17、`Stick, lip` 16、
`Drug delivery system` 13、`诊断试剂盒` 11、`Gum, chewing` 11、`Implant` 11、`控释制剂` 9、
`Block` 9、`皮肤点刺试剂` 7、`诊断试剂` 7、`咀嚼胶` 6、`Foam` 6、
`其他:制剂(非中国药典剂型 冻干粉剂)` 5、`放射性密封源` 5。

修法：**来源本身**（HK 13,935 + AU `tga_cmi` 4,730 = 93%，改不了）；
剩余 1,369 行（AU `artg_export` 1,002 + CN 367）都有原文可映射（`Stick`、`Wafer`、
`Liniment`、`Implant`、`Gum, chewing`、`缓释制剂`、`膜剂`），可用**迁移脚本**兜底。

## 口径与复现

- 数据库：`data/drugs.db`，只读连接 `file:data/drugs.db?mode=ro`。
  审计时刻 2026-11-10（北京时间；本机为 UTC−8 的 11-09 13:16）；
  `product` 477,098 行、`product_component` 628,013 行。
- 市场口径：`COALESCE(country, region)`，与 `coverage` 视图一致（本轮无 EU 区域层行）。
- 命令：

  ```powershell
  $py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
  & $py db/consistency_audit_form.py                        # 终端摘要
  & $py db/consistency_audit_form.py --json .tmp/form-audit.json --top 10
  & $py db/consistency_audit_form.py --only R1,R3 --top 3   # 只跑指定规则
  ```

- JSON 结构：`totals`（总行数 / 市场分布）+ `rules[]`，每条形如
  `{id, title, count, detail, by_market, by_source, samples, fix, note}`。
  `samples` 按 `--top` 给条数，样例是「按 product_id 排序后的前 N 条」，可复现。
- R1 的判定判据（`FAMILIES` 表、`KNOWN_BASES` 词表）在脚本里，改判据就改脚本，
  不要在报告里手改结论。

## 缺口与风险

1. **报告不含 `pack` 与剂型的「语义级」矛盾**（例如「口服溶液剂」的 pack 写「10粒/盒」这种
   跨市场错位），只做了量词级判定。CN 144 行 `滴剂`/`注射剂` 的「粒/瓶」量词，可能需要
   结合 `dosage_form` 看，本轮判为「只写数量」而非「写错数量」。
2. **R4 的 70,196 行 per_volume 缺口，本轮只按「有质量单位、无每容量」统计**，没有判断
   「这个产品本来就不该有浓度」（例如 bulk 输液、口服补液盐）。真正的缺口可能比 70,196 小，
   要看抽样核对结果。
3. **R1 的族判据是启发式关键词**：`spray` 分给 `topical`、`drops` 分给 `liquid`、
   `aerosol, spray` 单独给了「外用气雾」族——都是按库里实际分布回调过的（每次都记录了
   回调前后的条数：`inhalation` 硬冲突从 1,022 降到 29、`topical` 从 737 降到 130）。
   这条判据本身需要人看一遍是否同意（尤其 `\bgel\b`、`膏`、`喷雾` 这几个宽词）。
4. **未命中的 20,200 行**没有归类，其中 AU `not stated` 4,810 是来源事实，但
   `缓释制剂` / `膜剂` / `体外诊断试剂` 这些是可以归一的，本轮没做（属 R7 的 367 行 CN）。
5. **本报告没有动任何数据**：所有「修法」都是建议，落地前要按 AGENTS.md §5 走
   ingest → `db/check_data.py` → 三语回归。

## 下一步（建议顺序，每步带验收）

1. **改 `FORM_BASES` 顺序 + 词表 + 词边界**（S）：先写单测（用本报告 R1 的 14 个大格当用例），
   再重灌 US/GB/SG/CA，验收 `R1.conflict` 从 20,188 降到 <500，`R2` 从 2,187 降到 <100。
2. **新增 `form_base` 取值**（L）：`effervescent` / `chewable` / `orodispersible` / `patch` /
   `pellet` / `stick` / `kit` / `implant`。要先定枚举再改规则，站点与检索的展示映射同步改
   （三语）。
3. **`release_of()` 扩展 + AU/SG ingest 接入**（S）：验收 `R3.text_release_none` 从 1,880 降到
   <50。
4. **显示层两件小事**（S）：`pack` 纯数字补单位（26,840 行）、`release` 标注推断依据（8,392 行）。
5. **人工清单**（见 §B）建立 `reports/` 下的核对表，逐条确认后才允许迁移脚本动数。

## 附：本次运行的原始数字（JSON 摘要）

```
R1  count=28,542  ok=426,352  conflict=20,188  gap=5,829  unmapped=2,525  coarse=2,004  unmatched=20,200
R2  count=2,187   (dmd 1,533 / cima 213 / openfda_ndc 187 / hc_dpd 151)
R3  count=10,272  er_none=1,182  dr_none=698  set_no_text=8,392  cross=46
R4  count=175,521 value_null=101,280(64,718 产品) zero=91 >1e5=35 <1e-4=6 liquid_no_per_volume=70,196 no_component=3,911
R5  count=27,075  numeric_only=26,840 solid_volume=91 liquid_count=144
R6  count=109     groups=88 undecidable_no_strength=61,594 undecidable_no_key=7
R7  count=20,099  HK=13,935 AU=5,737 CN=367 ES=29 TW=16 MX=11 GB=3 SG=1
```
