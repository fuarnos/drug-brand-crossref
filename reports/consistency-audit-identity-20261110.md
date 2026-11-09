# 名称 / 成分 / 状态 / 来源 一致性审计（2026-11-10）

> 触发：用户报「力度伸是 VC 泡腾片，站点显示片剂」后追问「肯定还有别的类似的问题」。
> 本报告只查**名称 / 成分 / 状态 / 来源**一侧的自相矛盾；剂型规格口径归另一路审计，
> 这里只在「名称里写了剂型词但 `form_base`/`release` 不符」时出数，不改剂型字段。
>
> 脚本：`db/consistency_audit_identity.py`（只读、可复跑、`--json` 出结构化结果）；
> 报告数字全部由该脚本现查，未照抄任何旧口径。

## 结论（先说答案）

- **8 条规则跑完，6 条有实质命中，合计 43,324 条/组**（R1 23,595 + R2 86 + R3 9,534 + R4 6,114 + R6 584 + R8 3,411；R5、R7 为 0）。
- 最该先修的不是力度伸这一类，而是**「复方」名只挂了 1 个成分**：5,971 个产品、513 个名称。
  典型 `复方磺胺甲噁唑片` 只登记了 sulfamethoxazole（缺 trimethoprim），跨国对应会把复方当成单方。
- **碰撞视图被重复成分污染**：584 对「本应同一成分」的记录（570 对可直接并入），牵连 20,130 条名称行的 severe 判定——
  `葡萄糖注射液`（Dextrose / Glucose，4,312 条）这类同药异名目前仍被标成「同名不同药」。
- **名称检索被重复 key 稀释**：同一 compact 有 638 组多 key，同一 raw 挂在 2,773 个 key 上（影响 89,480 条名称行）。
- **状态字段有一处 ETL 语义错**：1,703 条 AU（artg_detail / artg_enrich）`status='active'` 却写了
  `status_date=2026-10-26`（抓取日），可一次性清空；CIMA 的 4,411 条 discontinued 无日期是源本身缺失。
- **中文名缺失 9,534 / 12,637（75.4%）**，其中 2,928 条有 ATC 可按映射回填，6,606 条无 ATC 只能丢弃计数。
- 力度伸本身确认：`CN-XA11GAW043A01-f81e1c21` / `-4cc5b321`，`dosage_form=片剂`、`form_base=tablet`；
  名称侧没有「泡腾」字样（商品名只有「力度伸」），所以这是**剂型字段/显示层**问题，不是名称问题——归剂型审计。

## 口径

- 数据库：`data/drugs.db`，只读连接 `file:data/drugs.db?mode=ro`；统计时间 2026-11-09 13:20（本地）。
- 表计数（现查）：substance 12,637 / variant 14,237 / product 477,098 / product_component 628,013 /
  product_name 652,909 / name_key 202,092 / name_variant 229,794。
  （旧文档里的「12,649 成分」已过期，以本次现查 12,637 为准。）
- 复跑：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/consistency_audit_identity.py --json .tmp/identity_audit.json   # 约 17 秒
```

- 修法归类固定五类：`规则`（入库/建站按规则重算，可自动）/ `迁移`（一次性数据迁移）/
  `显示层`（数据不动、页面标注或降级）/ `来源本身`（源没有这个信息）/ `丢弃计数`（判不了，不猜、不手工标注）。

## Top 10（按影响面排序）

| # | 问题 | 条数 | 影响 | 修法 | 能自动修？ | 工作量 |
|---|---|---|---|---|---|---|
| 1 | 名称写「复方」但成分表只有 1 个成分 | 5,971 产品 / 513 名称 | 复方被当单方，跨国对应与「不可互换」判断都错（如复方磺胺甲噁唑缺 TMP） | 迁移（补成分） | 否：源没给全，只能按名称+批文批量补可对上的部分，其余丢弃计数 | M |
| 2 | collision severe 里本应同一成分（重复 substance 记录） | 584 对 / 20,130 名称行 | 同药异名被标成「同名不同药」，警示噪声、成分页/对照页失真 | 迁移（合并）+ 规则（视图读异名表） | 清单可自动生成，合并需 DB 窗口 dry-run | M |
| 3 | 重复名称（compact / raw 多 key） | 638 组 + 2,773 组 / 影响 6,589 + 89,480 名称行 | 检索召回被拆散、同一药出现多条同义结果 | 规则（compact 归一）+ 迁移 | 是（归一化规则 + 一次合并） | M |
| 4 | `name_type='inn'` 名称与成分通用名对不上 | 17,384（可行动 759 + 拼写 1,249） | 输入通用名可能落到别的药；EN/ES/CN 供应商通用名混用 | 迁移（改映射/补异名表） | 部分：拼写类可自动补 alias；中文名映射错需按 ATC/别名规则批量核 | M |
| 5 | 中文名缺失 | 9,534（75.4%） | 中文检索/三语页面靠英文兜底，CN 用户命中率低 | 来源本身（+ 迁移回填） | 部分：2,928 条有 ATC 可回填，其余丢弃计数 | M |
| 6 | 状态与 `status_date` 冲突 | 1,703（可自动）+ 4,411（源缺失） | AU active 产品显示「某日停用/生效」；ES 停用无日期 | 规则（active 置空）/ 来源本身 | 1,703 是；4,411 否（丢弃计数） | S |
| 7 | 名称剂型词与 `form_base` 矛盾 | 86（另有 138 条属 form_base 粒度不足） | 与力度伸同型：名称说胶囊/注射液，字段说片剂/冲洗剂 | 显示层（名称词优先）+ 规则 | 是（显示层）；form_base 改动归剂型审计 | S |
| 8 | 同一 `approval_id` 跨国同号 | 870 组 | 批文号不是全局唯一键，任何单键 join 都会串国 | 显示层 / 规则 | 是（加「source_id+country+approval_id」复合键断言） | S |
| 9 | 同成分同国家 active + withdrawn 并存 | 938 组（多为不同批文，正常） | 页面若按成分聚合状态会自相矛盾 | 丢弃计数（仅计数，不处置） | 否 | S |
| 10 | `source_id × country` 非对角 | 0（manual_seed 11 条跨 AU/GB/CN，属人工种子表） | 来源与市场错配会让「哪个国家的药」失真 | 规则（ci_checks 断言） | 是 | S |

> R7（`name_key.script` 与字符集不符）现查 **0**，已无需处理，建议留一条断言防止回归。

## 逐条明细

### R1 品牌被当成成分 / INN 名称与成分不符 —— 23,595

| 子项 | 条数 | 说明 |
|---|---|---|
| `inn_en` 含 ®/™/© | 0 | 干净 |
| `inn_en` 等于品牌家族写法（name_family） | 0 | 干净，说明 substance 层没有被品牌污染 |
| `inn_en` 被「不含该成分」的产品当 trade 名 | 240 | **不是品牌当成分**，是成分语义缺口：Coenzyme Q10 = Ubidecarenone、Calamine=炉甘石 之类 |
| `name_type='inn'` 与成分通用名对不上 | 17,384 | 见下方分桶 |
| 名称含「复方」但只登记 1 个成分 | 5,971 | **最大一块**，全在 CN |

**1c 样例（240，别名/语义缺口）**

| substance | 被谁当 trade 名 | 涉及产品 |
|---|---|---|
| `coenzyme-q10`（Coenzyme Q10） | 辅酶Q10 保健品，成分登记为 Ubidecarenone | 37（AU/CA） |
| `petroleum`（Petroleum） | 凡士林类产品 | 32（US） |
| `calamine`（Calamine） | 炉甘石洗剂 | 30（US） |
| `calcium`（Calcium） | 复方钙制剂 | 23（AU/CA/GB） |

根因：同名不同 INN（USAN vs INN）没有进 `data/substance_aliases.csv`。
修法：补异名表（规则可执行）；补不了的丢弃计数。

**1d 分桶（17,384）**

| 分桶 | 条数 | 处置 |
|---|---|---|
| 中文名带剂型后缀（复方/制剂通用名，正常） | 6,330 | 丢弃计数 |
| 拉丁名对不上（顺势疗法名 / OTC 商品名 / 本地语言，源语义） | 8,523 | 丢弃计数 |
| 复方/多成分名，别名表未覆盖 | 1,721 | 丢弃计数 |
| **中文名与成分 `inn_zh` 对不上（需核，可能是映射错）** | **759** | 迁移（改映射） |
| 成分缺中文名，无法核对 | 51 | 丢弃计数 |
| （另列）只差拼写，如 `simethicone` vs `dimethicone`、`gaunfacine` vs `guanfacine` | 1,249 | 补异名表（可自动） |

759 条样例（中文名 vs 成分）：

| 产品名 | 挂的成分 | 备注 |
|---|---|---|
| 曲安奈德口腔软膏 | triamcinolone | 曲安奈德=acetonide 酯，映射到 base |
| 氨来呫诺糊剂 | carbenoxolona | 明显张冠李戴 |
| 糠甾醇片 | carbenoxolona | 同上；A01AD 整类被映射到同一成分 |
| 复方氯己定达克罗宁乳膏 | carbenoxolona | 同上 |
| 复方三氧化二砷糊剂 | carbenoxolona | 同上 |

根因（值得单独立项）：CN 入库按 **ATC 前缀**回填成分时，把整类（A01AD…）挂到了该类下第一条成分
`carbenoxolona` 上——32 个产品共享同一个错误成分，不是单条脏数据。
修法：迁移（按名称/批文重挂），并用「一个 ATC 前缀只能映射到一个成分」当断言；
判不了的丢弃计数，**不手工标注单条**。

**1e 复方只挂 1 个成分（5,971 / 513 名称）**

| 名称 | 已登记成分 | 产品数 |
|---|---|---|
| 复方磺胺甲噁唑片 | sulfamethoxazole（缺 trimethoprim） | 470 |
| 复方氯化钠注射液 | sodium chloride（缺 KCl/CaCl₂） | 309 |
| 复方氨酚那敏颗粒 | acetaminophen（缺 氯苯那敏/人工牛黄） | 220 |
| 复方乙酰水杨酸片 | aspirin（缺 非那西丁/咖啡因） | 158 |
| 复方氨林巴比妥注射液 | aminophenazone（缺 巴比妥/安替比林） | 140 |

根因：NHSA 复方只取了主成分。修法：迁移（按名称拆分补成分）；`复方氨基酸` 这类「混合物本身就是一个成分」的
名称按白名单保留，其余判不了的丢弃计数。

### R2 名称里带剂型词但字段不符 —— 86（+138 粒度不足）

词 × `form_base` 矩阵（`矛盾` = 名称词与字段冲突，且词不在 `dosage_form` 原文里）：

| 词 | 命中产品 | form_base 分布（Top） | 矛盾 |
|---|---|---|---|
| 注射液 | 54,214 | injection 54,204 / liquid 5 / topical 2 | 7 |
| 胶囊 | 19,748 | capsule 19,700 / liquid 24 / tablet 9 | 14 |
| 膏 | 4,117 | topical 4,047 / liquid 69 | 48 |
| 肠溶 | 4,081 | tablet 2,520 / capsule 1,525 | 0（release=DR 基本对得上） |
| 缓释 | 3,288 | tablet 2,360 / capsule 799 | 2 |
| 乳 | 2,781 | topical 2,714 / liquid 47 / injection 20 | 9 |
| 咀嚼 | 1,357 | tablet 1,351 | 0 |
| 栓 | 953 | suppository 952 / tablet 1 | 1 |
| 滴剂 | 401 | liquid 263 / capsule 137 | 1 |
| 泡腾 | 389 | tablet 320 / powder 63 / capsule 6 | 0 |
| 喷雾 | 235 | topical 211 / inhalation 20 | 4 |
| 控释 | 231 | tablet 219 | 0 |
| 贴 | 254 | topical 238 | 0 |
| 口服液 | 118 | liquid 118 | 0 |

矛盾样例：

| 名称 | dosage_form | form_base | release | 国 |
|---|---|---|---|---|
| 氨咖黄敏胶囊 | 片剂 | tablet | none | CN |
| 红霉素眼膏 | 眼用制剂 | liquid | none | CN |
| 甘露醇注射液 | 冲洗剂 | topical | none | CN |
| 骨化三醇软胶囊 | 胶丸剂 | pill | none | CN |
| 得喜胃通60毫克缓释胶囊 | 膠囊劑 | capsule | DR | TW |

- 判读：**膏 48 条主要是「眼膏 → liquid」的 form_base 映射粒度问题**，不是名称写错；这类应与剂型审计合并处理。
- 另有 138 条是「名称词在 `dosage_form` 原文里也有，只是 `form_base` 更粗」（如 `口服溶液剂;滴剂(胶囊型)` → capsule），
  **单列不计矛盾**，属显示层：名称原词优先于 form_base。
- `form_base` 为 `NULL/unknown/other`（HK 全表 NULL、部分 CN「靶向制剂」）一律不计矛盾——「不知道」≠「不符」。

修法：显示层（名称词直接展示，form_base 只做归组）；入库时按词表给名称打 `form_qualifier`（规则）。
**不动 form_base 本身**（归剂型规格审计）。

### R3 中文名缺失 / name_lang —— 9,534

- `substance.inn_zh` 缺失 **9,534 / 12,637 = 75.4%**（现查；旧口径 12,649 成分已过期）。
- `name_lang` 为空 **0**；与文本不符 **0**（en 10,878 + zh 1,759 全部自洽）。

按 ATC 大类（Top 10）：

| ATC 大类 | 缺失 | 该类总数 | 缺失率 |
|---|---|---|---|
| (无 ATC) | 6,606 | 6,628 | 99.7% |
| A 消化代谢 | 453 | 956 | 47.4% |
| L 抗肿瘤 | 377 | 789 | 47.8% |
| N 神经 | 342 | 656 | 52.1% |
| J 抗感染 | 331 | 680 | 48.7% |
| V 其他 | 252 | 510 | 49.4% |
| C 心血管 | 208 | 444 | 46.8% |
| B 血液 | 199 | 409 | 48.7% |
| D 皮肤 | 196 | 388 | 50.5% |
| R 呼吸 | 131 | 360 | 36.4% |

样例：`hydroxyzine-dihydrochloride`、`imipramine`（N06AA02）、`benzonatate`（R05DB01）、
`carisoprodol`（M03BA02）、`magnesium-sulfate-heptahydrate`。
根因：源事实——WHO INN 中文表只覆盖部分；辅料/疫苗株/植物提取物/无机盐没有标准中文名。
修法：有 ATC 的 2,928 条按 `atc → 中文名` 映射回填（迁移）；6,606 条无 ATC 的**丢弃计数**。

### R4 状态自相矛盾 —— 6,114

| 子项 | 条数 | 分布 | 修法 |
|---|---|---|---|
| `withdrawn/discontinued` 但 `status_date` 为空 | 4,411 | 全部 CIMA / ES | 来源本身（丢弃计数，不猜日期） |
| `active` 但 `status_date` 非空 | **1,703** | artg_detail 1,559 + artg_enrich 144；日期全是 `2026-10-26`（抓取日） | 规则：active 一律置空（可一次迁移） |
| 同一 `approval_id` 同源同国状态冲突 | **0** | — | 无需处理 |
| 同一 `approval_id` 跨国同号（命名空间） | 870 组 | 如 `42956` 同时是 AU/ES | 显示层/规则：不得单键 join |
| 同成分同国家 active+withdrawn 并存 | 938 组 | ES 为主，如 hydrochlorothiazide 609 active / 172 withdrawn | 丢弃计数（不同批文，正常） |

样例（active+status_date）：`AU-ARTG-68954-aldactone-100mg-tablet-blister-pack`、`AU-ARTG-68953-…`、
`AU-ARTG-11083-alkeran-tablets-5mg`。

### R5 来源与市场错配 —— 0

- 15 个有用例的 `source_id`，每个只服务一个市场；`markets.json` 的主源/辅助源映射与数据完全一致。
- 唯一「跨市场」的 `manual_seed`（人工种子表）11 条：AU 5 / GB 3 / CN 3，属设计如此，不计入。
- 修法：把这套交叉表当 `ci_checks` 断言（规则，可自动）；真错配就是入库国家参数写错，重跑该源。

### R6 collision severe 里的重复成分 —— 584 对 / 20,130 名称行

| 证据类型 | 对数 | 处置 |
|---|---|---|
| 同 base（只差盐型写法） | 290 | 并入同一 substance（迁移） |
| 同 ATC 全码（7 位） | 280 | 并入同一 substance（迁移） |
| 异名表已收录但 collision 未使用 | 11 | 改视图读 `alias_all`/别名组（规则） |
| 仅拼写差异 | 3 | 补 `data/substance_aliases.csv` |

样例：

| 同名 key | A | B | 产品数 |
|---|---|---|---|
| 葡萄糖注射液 | Dextrose（B05BA03） | Glucose（B05BA03） | 4,312 |
| amoxicillin | Amoxicillin | Amoxicillin Trihydrate | 582 |
| lisinopril | Lisinopril | Lisinopril Dihydrate | 524 |
| ondansetron | Ondansetron | Ondansetron Hydrochloride Dihydrate | 476 |
| candesartan | Candesartan | Candesartan Cilexetil | 322 |

口径说明：只比较**单方/简单复方**（≤12 个成分）的 severe key；两侧盐型不同（tartrate vs succinate）、
只差末位字母（vitamin A / D / D3）**不算重复**，已排除——盐型是 variant 的事，不是 substance 重复。
修法：合并走 `db/phaseb_merge.py --dry-run`（产品/组件/variant 三项计数核对后再 apply）；
异名已覆盖的改 collision 视图（规则）；证据不足的丢弃计数。

### R7 name_key.script —— 0

28,267 个 han key、173,825 个 latin key，按「含 CJK → han」重算后**零不符**（用 `[一-鿿]` + 扩展区判定）。
修法：保留为归一化断言（规则，可自动）。

### R8 重复名称 —— 3,411

| 子项 | 条数 | 影响 |
|---|---|---|
| 同一 `norm` 多 key | 0 | schema `UNIQUE` 生效 |
| 同一 `compact` 多 key | 638 组 | 6,589 条名称行 |
| 同一 `raw` 多 key | 2,773 组 | 89,480 条名称行 |

样例：

- compact `coq10`：`co q 10` / `co q10` / `coq10` / `coq 10`（4 个 key）
- compact `antidandruffshampoo`：`anti dandruff shampoo` / `antidandruff shampoo` / `antidandruffshampoo`
- raw `perindopril + amlodipino` 同时挂在 `perindopril amlodipino` / `perindopril amlodipine` / `perindopril arginine amlodipin`
- raw `simeticona` 同时挂在 `simethicone` / `simeticone` / `simeticona`

根因：归一化只做了标点/大小写，没做「同 compact 归一」和跨语言词形归一。
修法：规则（归一化时按 compact 复用 key）+ 迁移（存量合并）；raw 多 key 按 compact 归一后自动收敛。

## 不能自动修的：丢弃并计数

| 项 | 条数 | 为什么不猜 |
|---|---|---|
| R1 `name_type='inn'` 里拉丁名对不上（顺势疗法名、OTC 商品名、本地语言） | 8,523 | 没有权威对照表，硬猜会造出新的错映射 |
| R1 中文名带剂型后缀（复方/制剂通用名） | 6,330 | 名称本身不等于单一成分名，属正常 |
| R1 复方/多成分名，别名表未覆盖 | 1,721 | 需要成分级证据 |
| R1 成分缺中文名，中文名无法核对 | 51 | 没有 `inn_zh` 就无从比对 |
| R2 「名称词在 dosage_form 里也有」的粒度不足 | 138 | 是 form_base 粒度问题，归剂型审计 |
| R3 无 ATC 且无标准中文名 | 6,606 | 源没有这个信息 |
| R4 CIMA discontinued 无停用日期 | 4,411 | 源没给日期，填任何日期都是编造 |
| R4 同成分同国家 active+withdrawn 并存 | 938 | 多为不同批文，正常现象 |
| R6 证据不足的 severe 对 | 0（本轮全部有证据） | — |

## 已知误报与边界

1. **R1「拉丁名对不上」里混着正常的本地化写法**：西班牙语 `atorvastatina`、葡萄牙语词形已用「公共前缀 ≥6」放行；
   仍有 `calcarea fluorica`（顺势疗法拉丁名）这类，属源语义，已在桶里标注。
2. **R2 的「膏 48 条」主要是 form_base 映射粒度**（眼膏 → liquid），不是名称错误。
3. **R6 不判「同 ATC 4 位」**：4 位是类别（A02BA 下有 cimetidine / 拉呋替丁），只认 7 位全码。
4. **R4「同成分同国家并存」不判脏数据**：ES 同一成分常有多个历史批文，active 与 withdrawn 并存是正常的。
5. 本审计**只读**，没有写库、没有改 `site/build.py`、没有构建；`data/drugs.db` 未被触碰。
6. **与同日剂型审计的分工**：`reports/consistency-audit-form-20261110.md` 从字段侧扫「原文 × `form_base`/`release`/规格/包装」
   （其 R1 28,542 条，力度伸归它）；本报告 R2 只负责「**名称词** × `form_base`」这一格，两边数字**不可相加**。
   同理它的 R6「重复身份」是产品级（109 条），本报告 R6 是成分级（584 对），口径不同。

## 下一步（可执行，带验收）

| 优先级 | 动作 | 验收 |
|---|---|---|
| P0 | 修 CN 的 ATC 前缀误映射（R1 `carbenoxolona` 一类）：按名称/批文重挂，加「一个 ATC 前缀一个成分」断言 | 759 条「中文名与 inn_zh 对不上」降到 <100；`carbenoxolona` 产品数从 32 回到 ES 的 1 条 |
| P0 | 复方补成分（5,971 条 / 513 名称）：按名称拆成分，`复方氨基酸` 类白名单保留 | `复方%` 且成分数=1 的产品数 = 0（白名单除外，白名单写进报告） |
| P1 | 修 `collision`：读异名表 + 合并 570 对重复成分（dry-run → apply） | `葡萄糖注射液` 级别从 severe 降为 info；severe 总数从 23,752 下降，下降量写进 CHANGELOG |
| P1 | 清 `active` 行的 `status_date`（1,703 条），ETL 侧停止写抓取日 | `SELECT COUNT(*) FROM product WHERE status='active' AND status_date IS NOT NULL` = 0 |
| P2 | compact 归一 + 存量合并（638 组），raw 多 key 收敛（2,773 组） | `SELECT COUNT(*) FROM (SELECT compact FROM name_key GROUP BY compact HAVING COUNT(*)>1)` = 0 |
| P2 | 补异名表：R1 的 1,249 拼写 + 240 语义缺口 + R6 的 3 条 | `data/substance_aliases.csv` 新增行都带 source 列 |
| P3 | 把 R5 / R7 / 「active 无 status_date」写成 `deploy/ci_checks.py --fast` 断言 | 三项断言在 CI 里恒为 0 |

## 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/consistency_audit_identity.py                    # 人读：规则总览 + 每条的分桶/矩阵/样例
& $py db/consistency_audit_identity.py --json out.json    # 机器可读：规则/条数/样例/修法/可自动修
```

报告中每个数字都来自上面这条命令的当次输出（2026-11-09 13:20 本地，17 秒），
没有引用 README / CHANGELOG / About 页的旧口径。
