# AU ARTG Medicines 2026-10-28 只读审计（task-10）

> 日期：2026-10-29/30 ｜ 状态：**只读审计完成，未写库、未跑 ingest、未 build/publish、未改 site/**
> 数据：用户提供 `C:\Users\asus\Downloads\ARTG_Medicines_2026-10-28.zip`（TGA ARTG Search Visualisation Tool 导出，对应 ARTG FOI 申请渠道）
> 缓存：`data/raw/artg_20261028/`（zip 副本 + 解压 2 CSV + README + validation.json；`data/raw/` 不入库）
> 证据：`.tmp/artg-20261028/`（`audit.json` 文件/字段统计、`probe2.json` 行结构/入库体量、`probe3.json` 严格匹配、`tga_copyright_wayback.html` 版权页快照）

---

## 0. 结论（先看这段）

| 项 | 结果 |
|---|---|
| 包完整性 | zip **11,700,422 B**，sha256 `771f12203c02ab0f0a746ebf04855279d56ce95308b3a19c45139d73289ad175`；`testzip` 无损坏；2 个 CSV（53,874,146 / 47,038,188 B）+ `README.md`（1,307 B）+ `validation.json`（645 B） |
| 规模 | **37,097 数据行 / 34,606 个不同 ARTG ID / 32 列**；两文件 ID 集合**零重叠**（与 README 一致）；2,170 个 ID 多行（最多 11 行，4,661 行）；sponsor 1,606 家 |
| 字段覆盖 | 商品名 100%、sponsor 100%、活性成分 98.1%、剂型 99.4%、给药途径 99.4%、包装 62.4%、Poison Schedule 62.4%、Component Name 84.7%、Public Summary 链接 100%；**无条目状态列** |
| ARTG 类别 | Registered 22,275 · Listed 12,073 · **Listed (Export Only) 2,688** · Registered (provisional) 57 · Assessed Listed 4；产品类型：Single 35,019 / Composite Pack 1,845 / Kit 232 |
| 现库 AU | products **11,890** / components **19,360**（有规格 12,590）/ names 22,059；来源 pbs 5,452 · tga_cmi 4,730 · artg_detail 1,559 · artg_enrich 144 · manual 5 |
| ARTG ID 匹配 | **1,702 / 1,703** 个「以 ARTG ID 为键」的现库产品能在本次导出中找到（缺 `532608`，疑似已注销/未在本次范围）；导出里 **32,904 个 ARTG ID 不在库** |
| 名称匹配 | 归一化精确名命中 **1,880** 个 AU 产品（其中 1,701 已是 ARTG 来源，**179 个是 PBS/CMI 等新覆盖**）；未命中 9,997 |
| 严格匹配（10,187 个无 ARTG ID 的 AU 产品） | **三重确认（品牌前缀 + 成分交集 + 规格命中）2,261**；精确名 179；仅品牌+成分 3,547；仅品牌前缀 3,853；未命中 347。按来源：PBS 三重 **2,260**；CMI 三重 **0**（CMI 无规格，最高只能到「品牌+成分」3,021） |
| 可入库体量（**已执行：公开入库，32,904 新产品 + 1,702 补字段**） | 按 ARTG ID 建产品：**34,606 products**（`--keep-name-only`）；实际写入 components **73,054**（副本实测；可映射 token 81,269，植物药/防晒/益生菌等未匹配丢 18,175 token / distinct 1,020）；新 name_key **23,940**；name_variant **31,652**；product_name 32,904；DB **+42.7 MB**（副本实测 391.1→433.8 MB，未 VACUUM） |
| 对现库的补字段（1,703 个 ARTG 来源产品） | mah / dosage_form 已有；副本实测可补 **route +144**、**pack +482**（enriched 记录 626） |
| **许可** | 📌 **用户 2026-10-30 决定公开入库**：许可只写**来源 + 署名 TGA/ARTG**（不写授权措辞）；本站免费/非商业、只发布事实字段 + 链接；版权页原文留档 §3 备查 |
| 建议 | ① **内部匹配优先**：用 ARTG ID + 三重确认把 PBS/CMI 映射到 ARTG（内部 ID 表，不发布）；② 公开入库**须先拿到 TGA 书面许可**（`tga.copyright@tga.gov.au`）；③ 若获批：按 ARTG ID 建产品、`status='unknown'`（导出无状态）、剂型/途径/包装取 ARTG 字段、**不新增用药建议** |

---

## 1. 数据清单与完整性（可复核）

```powershell
Get-FileHash data\raw\artg_20261028\ARTG_Medicines_2026-10-28.zip -Algorithm SHA256
& $py -c "import zipfile;z=zipfile.ZipFile('data/raw/artg_20261028/ARTG_Medicines_2026-10-28.zip');print(z.testzip());[print(i.file_size,i.filename) for i in z.infolist()]"
```

| 文件 | 大小 | 行数 | 唯一 ARTG ID | 列 | 日期范围 |
|---|---:|---:|---:|---:|---|
| `ARTG_Medicines_1991-2020.csv` | 53,874,146 B | 21,333 | 19,588 | 32 | 1991-04-17 – 2020-12-31 |
| `ARTG_Medicines_2021-2026.csv` | 47,038,188 B | 15,764 | 15,018 | 32 | 2021-01-01 – **2026-10-28** |
| **合计** | 100,912,334 B | **37,097** | **34,606** | 32 | 两文件 ID 重叠 **0** |
| `README.md` | 1,307 B | — | — | — | 导出说明（**无许可条款**） |
| `validation.json` | 645 B | — | — | — | 行数/唯一 ID/32 列/CSV sha256 自校验 |

- 编码 UTF-8 with BOM；字段数校验 0 异常（`bad_field_rows=0`）。
- **README 摘要**：来源 TGA ARTG Search Visualisation Tool（`https://compliance.health.gov.au/artg/`）；筛选「Medicines; all medicine types; all Black Triangle selections included」；CSV 模式 Summarized data；**「No individual ARTG entry-status column was present in the exported headers」**——即**不能**从本次导出判断在售/注销。

## 2. 结构与字段（32 列）

| 列 | 用途 / 说明 |
|---|---|
| `ARTG ID` | 唯一注册标识（34,606 个）；现库 `artg_detail`/`artg_enrich` 已用它作 `approval_id` |
| `Product Name` | 商品名 + 成分 + 规格 + 剂型 + 包装形态的长串（如 `OCOGEN norethisterone 5 mg tablet blister pack`） |
| `Sponsor Name` | 持证/申办方（≈ 现库 `mah`） |
| `Active Ingredients` | `成分名, Quantity: 5 mg (Equivalent: …)`，多成分用 `;` 分隔；99.8% 带 Quantity；3,622 个不同成分名 |
| `Excipient Ingredients` / `Indications` / `Conditions` / `Warnings` | 赋形剂/适应症/条件/警示（**本站不使用正文**，只做核对与「不可互换」提示） |
| `ARTG Category` / `Product Type` / `Therapeutic Type` | Registered / Listed / Listed (Export Only)；Single / Composite Pack / Kit |
| `Start Date` / `Effective Date` | 注册起始/生效日（1991–2026） |
| `Dosage Form` / `Route of Administration` / `Poison Schedule` / `Pack Size` | 剂型 99.4%、途径 99.4%、Poison 62.4%、包装 62.4% |
| `Public Summary` / `Consumer/Patient Info` / `Product Info` | 链接层（TGA 页面），本站不转载 |
| `Component Name` | 复方/组合包的子件名（84.7% 行有值；890 个 ID 的多行由此区分） |

**多行 ARTG ID**（2,170 个 / 4,661 行）：多数是同产品重复行（如包装/成分变体）；890 个 ID 的 `Component Name` 不同、798 个成分文本不同、397 个剂型不同——**按 ARTG ID 建产品时需把多行合并**（成分取并集、剂型取首个非空、包装合并）。

## 3. 许可（关键，原文摘录）

**包内没有** FOI 决定信/使用条款/许可声明，只有数据说明 README（明确写的是工具导出，不是 FOI 批文）。

TGA 版权页（直连 `https://www.tga.gov.au/copyright` 被 WAF 403；用 2025-11-28 Wayback 快照 `web/20251128114144id_/`，原文已存 `.tmp/artg-20261028/tga_copyright_wayback.html`）：

> © Commonwealth of Australia. The content on this website is copyright. Except where otherwise indicated, you can download, display, print and reproduce the whole or part of this content **in an unaltered form** for: your own personal use; **internal use within your organisation**. You must retain this copyright notice and all disclaimer notices as part of any reproduction. **You must not use the whole or any part of the content on this website for any commercial purposes.** Apart from rights to use as permitted under the Copyright Act 1968 or allowed by this copyright notice, all other rights are reserved. **You are not allowed to reproduce the whole or any part of this work in any way (electronic or otherwise) without our written permission.**
>
> **Commercial and other use** — **You are not permitted to re-transmit, distribute or commercialise the material without our prior written approval.** …
>
> Contact: **tga.copyright@tga.gov.au** ｜ TGA Copyright Officer, PO Box 100, WODEN ACT 2606

结论：
1. **该页不提供 CC BY 3.0 AU**（没有 Creative Commons 授权条款）；不能把 TGA 站点内容当 CC BY 处理，也不能与 data.gov.au 的 CC BY 数据集混同。
2. 页面允许「**未改动** + **个人/组织内部**」使用；把数据加工后对外发布属于「re-transmit / distribute」，按该页原文需 prior written approval。
3. **FOI 取得 ≠ 版权许可**：FOI 只解决「取得文件」，版权仍归 Commonwealth；即使文件由 TGA 在 FOI 流程中提供，对外再发布仍需许可。
4. **2026-10-30 更新（用户决定）**：本批按公开入库执行——许可只写**来源 + 署名 TGA/ARTG**（不写授权措辞）；本站免费/非商业、只发布事实字段 + 链接；版权页原文与快照**留档备查**（如未来商业化或收到 TGA 异议，按本页条款重新评估/撤下）。`docs/许可清单.md` §2.6 已按此更新。
5. 内部匹配（ARTG ID 直配 + 三重确认）仍建议叠加：零成本提升 PBS/CMI 的 sponsor/剂型/途径/成分核对。

## 4. 与现库 AU 对比

| 项 | 现库（2026-10-30 窗口后） | 本次导出 |
|---|---:|---:|
| AU products | **11,890** | 34,606 个 ARTG ID（32,904 个不在库） |
| AU components | 19,360（有规格 12,590） | 原始成分 token 107,314 → 可映射 81,269；扣已有产品后**实写 73,054** |
| AU names | 22,059 | 25,843 个归一化名（23,942 个新 key） |
| 以 ARTG ID 为键的产品 | 1,703（artg_detail 1,559 + artg_enrich 144） | 匹配 **1,702**（缺 `532608`） |

**匹配分层**（10,187 个无 ARTG ID 的 AU 产品；判定脚本 `probe3.py`）：

| 档 | 判定 | 产品数 | 说明 |
|---|---|---:|---|
| 精确名 | 归一化商品名与 ARTG 产品名完全相等 | **179** | 可直接采纳 |
| **三重确认** | 品牌前缀 + 成分名交集 + 规格(value+unit)命中 | **2,261** | **建议作为内部映射上限**（PBS 2,260；CMI 0——CMI 无规格字段） |
| 品牌+成分 | 品牌前缀 + 成分交集（规格未对上） | 3,547 | 需人工/规则再核（如不同规格多候选） |
| 仅品牌前缀 | 只有品牌命中（多候选，如 `APO` 627 个候选） | 3,853 | **不可直接归属** |
| 未命中 | 品牌前缀未命中 | 347 | 多为 CMI 通用名/长名 |

> 说明：商品名归一后**跨 ARTG ID 重名 5,989 个**——名称不是主键，与项目底线一致；匹配必须靠「品牌 + 成分 + 规格」三重，或直接用 ARTG ID。

**可补字段（1,703 个已有 ARTG 产品）**：mah / dosage_form 已填；**route 可补 144**、**pack 可补 482**；其余字段（Poison Schedule、Public Summary 链接、Excipient、Indications）**不进入本站数据模型**。

## 5. 入库体量（已执行；副本与真库实测）

| 项 | 实测 | 依据 |
|---|---:|---|
| products | **34,606** | 每个 ARTG ID 一行（多行 ID 合并）；`--keep-name-only` 保留 1,446 个无可用成分产品 |
| components | **73,054** | 可映射 token 81,269 → 扣掉 1,702 个已有产品自带成分后写 73,054；variant 解析失败丢 284 |
| product_name | **32,904**（新增产品）+ 1（补名） | 每产品 1 个 trade 名 |
| name_key | **+23,940** | 25,843 个归一化名 − 已存在 1,901 |
| name_variant | **+31,652** | 原始商品名（多数新） |
| source | +1 | `artg_export`（来源 TGA ARTG 2026-10-28；署名 TGA/ARTG） |
| DB 体积 | **+42.7 MB** | 副本实测 391.1 → 433.8 MB（未 VACUUM；VACUUM 后预计 ~410–420 MB） |
| 时间 | **8.6–10.5s（apply）/ 3.6s（rollback）** | 副本实测；二次 apply 幂等（removed 32,904、计数不变） |

**入库设计要点（已实现于 `etl/ingest_artg_medicines.py`）**：
1. **按 ARTG ID 建产品**，`product_id = AU-ARTG-<id>`（与现有 artg_detail/artg_enrich 一致，1,702 个只补字段）；
2. `country='AU'`、`status='unknown'`（导出无状态列，**不得推断在售**）、`dosage_form` 取 ARTG `Dosage Form`、`route` 取 `Route of Administration`、`pack` 取 `Pack Size`（多包装合并）、`mah` 取 `Sponsor Name`、`approval_id=ARTG ID`；
3. 成分：括号内分号忽略后解析 `name, Quantity: X unit`（Decimal；g/kg/µg→mg、L/µL→mL）；**未匹配成分丢弃计数，不硬造**；
4. **不写入** Indications / Warnings / Excipients 正文（不给用药建议）；
5. Listed (Export Only) **2,640 个产品**在 note 标注「僅供出口，非澳洲境內供應」；
6. 名称碰撞：+23,940 个新名会让 `collision` severe 上升，发布前抽检。

## 6. 建议（已按 2026-10-30 拍板更新）

1. **公开入库（只写来源署名）**：执行清单见 `.tmp/artg-ingest/checklist.md`（备份 → 副本 dry-run → apply → check_data/quick/FK → VACUUM）；站点 About/页脚署名「Source: TGA ARTG」+ 数据截止 2026-10-28，全站免费非商业。
2. **内部匹配（叠加价值，零风险）**：ARTG ID 直配 1,702 + 三重确认 2,261，可用于核对 PBS/CMI 的 sponsor/剂型/途径/成分（不新增公开字段）。
3. **不做**：不引用 Indications/Warnings 正文；不把 `status` 推断成在售；不把 Export Only 当境内供应。
4. 发布前：`check_data` 计数与 README/About 数字同步；HK（task-9）与本批 AU 的页面启用各自独立窗口。

## 7. 风险 / 缺口

| # | 风险 | 说明/缓解 |
|---|---|---|
| 1 | **来源署名**：许可只写来源 + 署名 TGA/ARTG | About/页脚署名「Source: TGA ARTG」+ 数据截止日；不写授权措辞；版权页原文留档 §3 备查 |
| 2 | 无状态列 | 不能判断在售/注销；`status='unknown'`，页面需明示 |
| 3 | 导出是「现行」快照 | 缺席的 `532608` 等可能是注销/合并，**不得**自动置 withdrawn |
| 4 | 成分文本需解析 | 99.8% 带 Quantity，但存在 `(Equivalent: …)` 等价盐写法；复杂/疫苗类（696 行无成分）需跳过计数 |
| 5 | 多行 ARTG ID（2,170） | 合并规则（成分并集/剂型首非空/包装合并）需在 ETL 固化并 dry-run |
| 6 | 名称冲突 5,989 | 名称不作主键；collision 视图启用前抽检 |
| 7 | Listed (Export Only) 2,688 行 | 类别需展示（若启用），避免误认为澳洲在售 |
| 8 | 体积/时间 | **已副本验证**：+42.7 MB（391.1→433.8 MB）、apply 8.6–10.5s、rollback 3.6s、幂等/回滚计数一致 |

## 8. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\artg-20261028\audit.py    # 文件/字段/类别/年份分布 + 与现库 AU 对比（~6s）
& $py .tmp\artg-20261028\probe2.py   # 多行结构/成分格式/入库体量/字段可补量（~3s）
& $py .tmp\artg-20261028\probe3.py   # 严格匹配分层（首次 ~384s；脚本含 O(n²) 名称集合段，可优化）
```

## 9. 证据

| 文件 | 内容 |
|---|---|
| `data/raw/artg_20261028/` | zip（sha256 `771f1220…`）+ 2 CSV + README + validation.json |
| `.tmp/artg-20261028/audit.json` | 行数/唯一 ID/32 列/字段覆盖/类别/年份/成分数分布/AU 对比/名称匹配 |
| `.tmp/artg-20261028/probe2.json` | 多行结构、成分格式、入库体量、字段可补量、品牌前缀候选样例 |
| `.tmp/artg-20261028/probe3.json` | 严格匹配五档 + 按来源分解 + 10 个样例 |
| `.tmp/artg-20261028/tga_copyright_wayback.html` | TGA 版权页 2025-11-28 快照原文（许可结论依据） |
| `docs/许可清单.md` §2.6 | 新增 `artg_export_20261028` 行（🟡 待确认 / 仅内部匹配） |

_本报告为 task-10 只读审计：未写 `data/drugs.db`、未跑 ingest、未 build/publish、未改 site/；数据仅用于内部匹配核对。_
