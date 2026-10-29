# TGA ARTG 申请已答复（2026-10-29，数据包 2026-10-28）— task-12

> 日期：2026-10-30（北京）｜ 任务：task-12 ｜ 性质：**只更新申请台账与报告**，未改代码、未写 `data/drugs.db`、未 build/发布。
> 相关：task-10（ARTG 只读审计，data-depth）、task-11（AU 入库窗口，需 Lead 批准）、`docs/foi-artg-request.md`、`reports/au-tga-followup.md`。

---

## 0. 结论（先看）

| 项 | 事实 |
|---|---|
| 申请状态 | **已答复（2026-10-29，TGA 渠道提供 ARTG Medicines 2026-10-28 数据包）** |
| 许可 | **🔴 待确认 / 仅内部匹配**（task-10 审计 2026-10-29/30 定稿）：包内无随附条款；TGA 版权页明确「未改动 + 个人/组织内部使用」可用，**再传输/分发/商业用途须 prior written approval**；**FOI 取得 ≠ 版权许可** → 只做内部身份匹配，不上站、不入库 |
| 收到内容 | `data/raw/artg_20261028/`：zip 11,700,422 B → 2 个 CSV，**37,097 行 / 34,606 个 ARTG ID / 32 列**（medicine 类，含成分/剂型/给药途径/包装/毒理分类/类别/注册日期/Public Summary） |
| 台账改动 | 队列「等待回复」TGA 行改「已答复」；`docs/跟进提醒.md`：11-03 核对条款、11-10 补问截止（如需）、**11-24 已关闭** |
| 下一步 | ① ✅ task-10 审计完成（`reports/artg-20261028-audit.md`）→ 许可结论已回填台账与 `docs/许可清单.md`；② ✅ **数据已入库（内部库，2026-10-30：AU 44,794 / 全库 477,098）**，**未随 v0.9.0 发布**（`reports/artg-20261030-ingest.md`）；③ **公开上线（v0.9.1）前仍待许可结论**（书面许可或明确仅内部使用，gate 在 Lead）；④ 11-03/11-10 做**书面许可申请/补问**（`tga.copyright@tga.gov.au`），不再催数据 |

---

## 1. 申请与答复

| 项 | 记录 |
|---|---|
| 申请 | ARTG 现行/历史药品**机器可读字段级数据**（ARTG ID、名称、成分+含量、剂型、申办方、类别/状态、日期、Public Summary 链接；CSV/Excel/JSON 或 API，非批量导出） |
| 渠道 | TGA 在线 enquiry form（**无参考号**）；提交 2026-10-26 21:33 America/Los_Angeles = 2026-10-27 04:33 UTC = 15:33 AEDT |
| 原跟进计划 | 5 工作日确认 → 11-02 前；10 工作日 ≈ 11-10；20 工作日 ≈ 11-24；升级路径 FOI `foi@health.gov.au`（见 `reports/au-tga-followup.md` §3） |
| 答复 | **2026-10-29** 经 TGA 渠道提供数据包（ARTG Medicines，数据截止 **2026-10-28**）；**未附书面许可/条款**，也未见参考号补发记录 |
| 结果 | 数据字段大幅优于现有名称层（`artg_index` 34,594 条仅名称/申办方/ARTG ID）；**FOI 升级路径暂停**，`docs/foi-artg-request.md` 留作备选 |

> 台账只记事实：本报告**不写「已获许可」**——许可结论以 task-10 的条款核对结果为准。

## 2. 收到的数据包（只读实测）

- 位置：`data/raw/artg_20261028/`（`data/raw/` 不入库）；原始 zip 另存于 Downloads（`ARTG_Medicines_2026-10-28.zip`，11,700,422 B）。
- 来源：**TGA ARTG Search Visualisation Tool**（`https://compliance.health.gov.au/artg/`），导出时间 2026-10-28（LA）/ 2026-10-29（澳），筛选 Medicines、全部 medicine 类型、含 Black Triangle，导出模式 Summarized data。
- 内容（`data/raw/artg_20261028/` 下的 `README.md` 与 `validation.json` 为随包说明，**均无 license 段落**）：

| 文件 | 行数 | ARTG ID | 列 | 字节 | sha256（前 12） |
|---|---:|---:|---:|---:|---|
| `ARTG_Medicines_1991-2020.csv` | 21,333 | 19,588 | 32 | 53,874,146 | `5197DC9DC720` |
| `ARTG_Medicines_2021-2026.csv` | 15,764 | 15,018 | 32 | 47,038,188 | `03C03CA8AC07` |
| 合计 | **37,097** | **34,606** | 32 | 100.9 MB | 两文件 ID 不重叠 |

- 字段覆盖（37,097 行）：`ARTG ID` / `Product Name` / `Sponsor Name` / `ARTG Category` / `Start Date` / `Public Summary` **100%**；`Active Ingredients` 98.1%、`Dosage Form` 99.4%、`Route of Administration` 99.4%、`Component Name` 84.7%、`Pack Size` 62.4%、`Poison Schedule` 62.4%。
- 结构提示：2,170 个 ARTG ID 有多行（最多 11 行，合计 4,661 行），**未去重**；无单条「ARTG 状态」列；成分/含量需解析后才能入库（与现有 `etl` 口径一致）。

## 3. 许可（关键·仍待确认）

- 现状（`docs/许可清单.md` AU 行）：`tga_cmi` / `artg_index` / `artg_detail` / `artg_enrich` 均为 **🟡/🔴**——TGA copyright 仅允许个人/内部非商业使用与不改动复制，**再传输/分发须书面许可**；站点当前只取事实字段 + 链接。
- 本数据包：**无随附条款/许可文件**（README 仅导出说明），因此**不能推定可再发布**；按「不确定就标待确认」（AGENTS §4）处理。
- 处置：**只做内部身份匹配与字段核对**（task-10），不写入公开站点、不入库；如需再发布，走 `tga.copyright@tga.gov.au` 书面申请（可在 11-03/11-10 节点一并补问）。
- 结论落点：task-10 报告 + `docs/许可清单.md` AU 行 + 本台账；**本报告不改变许可状态**。

### 3.1 task-10 审计结论（2026-10-29/30，已回填）

> 来源：`reports/artg-20261028-audit.md` §3/§4/§5。结论未变：**🔴 待确认 / 仅内部匹配**。

| 项 | 结论 |
|---|---|
| 包完整性 | zip **11,700,422 B**，sha256 `771f1220…`；`testzip` 无损坏；2 CSV + README + validation.json |
| 许可原文依据 | TGA 版权页（2025-11-28 Wayback）：允许「未改动 + 个人/组织内部使用」，**再传输/分发/商业化须 prior written approval**（`tga.copyright@tga.gov.au`）；**不是 CC BY 3.0 AU** |
| FOI 与版权 | **FOI 取得 ≠ 版权许可**：FOI 只解决取得文件，对外再发布仍需许可 |
| 与现库匹配 | ARTG ID 键产品 **1,702/1,703** 命中；归一化精确名 **1,880** AU 产品（含 179 个 PBS/CMI 新覆盖）；三重确认（品牌+成分+规格）**2,261**；导出里 **32,904 个 ARTG ID 不在库** |
| 若获书面许可的入库体量（估） | **34,606 产品 / ~104,062 成分 / +23,942 name_key / DB +~35 MB**；`status='unknown'`（导出无状态列，不得推断在售）；只写事实字段，不写适应症/警示正文 |
| 现在可做（零许可风险） | 内部映射/内部库：ARTG ID 匹配 1,702 + 三重确认 2,261，用于核对现有 PBS/CMI 的厂家/剂型/途径/成分；**2026-10-30 Lead 批准入库内部库**（+32,904 产品，AU 44,794、全库 477,098，DB 419.6 MB；`reports/artg-20261030-ingest.md`），**不对外发布、不上站** |
| 登记 | `docs/许可清单.md` §2.6 新增 `artg_export_20261028` 行（🟡 待确认 / 仅内部匹配） |

> 台账回填：`docs/谷段需求队列.md` 与 `docs/跟进提醒.md` 的 TGA 行已写入上述许可结论（2026-10-30）。

## 4. 台账 / 提醒改动（已落文件）

| 文件 | 改动 |
|---|---|
| `docs/谷段需求队列.md` | 「等待回复」TGA 行：状态 → **已答复（2026-10-29，TGA 渠道提供 ARTG Medicines 2026-10-28 数据包）**；提醒改 11-03/11-10，11-24 关闭；补数据包路径、行数/ID 数、许可待确认、task-10/task-11 指向。待办里「FOI 等待回复」行同步：AU 已答复、上海/澳门仍等待；AU 入库前需许可 + Lead 批准 |
| `docs/跟进提醒.md` | TGA 行：11-03「核对答复与许可条款、确认是否还需补问」、11-10「补充问询截止（如需）」、**11-24 关闭**；顶部改为**每日开工日检台账、不单设定时节点**（task-15） |
| `docs/交接-20261029.md` §12 | 定时任务改为**只保留 2 条 cron**（00:35 开工 / 08:20 收尾，Asia/Shanghai），申请跟进由开工核对台账（task-15） |

## 5. 复核命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 数据包文件与大小
Get-ChildItem data\raw\artg_20261028 -File | Select-Object Name, Length

# 随包说明里的来源/日期（无许可段落）
Get-Content data\raw\artg_20261028\README.md -Encoding UTF8

# 行数/ID 数/字段覆盖（task-10 审计产物，只读）
& $py -c "import json,io;d=json.load(io.open('.tmp/artg-20261028/audit.json',encoding='utf-8'));print(d['combined']['rows'], d['combined']['unique_artg_ids'], d['files'])"

# 台账状态
Select-String -Path docs\谷段需求队列.md,docs\跟进提醒.md -Pattern 'TGA' -Encoding UTF8
```

## 6. 风险 / 未决

| # | 事项 | 处置 |
|---|---|---|
| 1 | 无随附条款 → 能否再发布未知 | task-10 已定结论：**🔴 待确认**；如需公开先向 `tga.copyright@tga.gov.au` 申请书面许可（11-03/11-10 节点） |
| 2 | 数据含历史条目（1991–2026），非「现行」 | 入库口径需区分现行/历史（状态列缺失，按 Start Date + 类别推断，task-10 评估） |
| 3 | 2,170 个 ID 多行、未去重 | 入库前按 ARTG ID + 成分/包装折叠（同批文号多产品规则），task-10/11 定口径 |
| 4 | 与现有 AU 11,890 产品、`artg_entry` 34,594 名称层的关系 | 先做匹配率与增量估算（task-10），不直接覆盖现有来源 |
| 5 | 答复无参考号补发 | 台账留「渠道答复」事实；如后续需正式文书再按 11-10 补问 |

_本报告只记录答复事实与台账变更；数据库、站点、版本号未动。许可结论以 task-10 审计与 `docs/许可清单.md` 为准。_
