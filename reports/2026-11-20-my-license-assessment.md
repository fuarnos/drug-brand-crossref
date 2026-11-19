# 马来西亚（MY）NPRA / QUEST 3+ 产品级数据许可评估

- 日期：2026-11-20（北京时间）｜工位：phaseb-data｜任务：task-3（M8 新数据源自主检索）
- 用户原话（2026-11-20）：「马来西亚也可以做」。对应需求队列 **M7 / T46**。
- 本轮只读评估：**未写 `data/drugs.db`、未跑 ingest、未改 `site/build.py`、未发布**；只下载了官方开放数据 CSV 到系统临时目录做计数与字段核对。
- 结论：**🟢 可入库（CC BY 4.0，产品级，无需申请、无需账号）**。这是目前能最快补上「产品级 + 商品名 + 成分 + 规格线索」的市场。

## 0. 结论先行

| 问题 | 答案 |
|---|---|
| 有没有产品级批量入口？ | **有**。马来西亚官方开放数据门户 `data.gov.my` 收录 NPRA（QUEST3+）的「Approved Pharmaceutical Products」数据集，CSV/Parquet 直接下载，无账号、无 API key |
| 许可允许再发布吗？ | **允许**。数据集页明写 **CC BY 4.0**（可商用、可修改、可再分发，须署名 + 保留许可链接） |
| 数据量 | **28,333 条**「已批准产品」（2026-11-18 数据截止；CSV 10,661,861 B）；另有 **1,623 条**已注销产品（独立数据集） |
| 字段 | 16 列：注册号、参考号、商品名、状态、产品类别、持有人、制造商、进口商、注册日、到期日、**活性成分+含量**、MDC 代码、通用名 |
| 规格 / 剂型 | **规格在 `active_ingredient` 字符串里**（如 `TERBINAFINE HYDROCHLORIDE[281.250;mg;;0]`）；**没有独立剂型列**，剂型多数写在商品名/通用名里（Tablet / Capsule / Syrup…），需派生 |
| ATC | `mdc_code` 前 7 位是 ATC（如 `D01BA02-110-T10-01-009`）；全体 8,477/28,333，**西药类 8,466/9,085 ≈ 93.2%**（PRESCRIPTION + NON PRESCRIPTION + NCE + BIOLOGICS） |
| 通用名 | 4,068/28,333（处方药 2,340/5,150；天然产品基本没有） |
| 更新频率 | **每日**（数据集页：Last updated 2026-11-19 03:00；下次 2026-11-20 12:00） |
| 入库成本估算 | **4–6 人时**（CSV 直读；主要工作量在成分串拆解、剂型词表、规格归一、状态映射） |
| 对目标贡献 | 产品 **+28,333**（M5：594,781 → 623,114）；商品名 **+约 28,135**（M6：780,843 → 约 808,978，**单这一国即可越过 80 万目标**；未计与现有商品名的重名，即使重叠 30% 仍 > 80 万） |

## 1. 官方入口与许可证据（2026-11-20 抓取）

| # | 证据 | 内容 | 判定 |
|---|---|---|---|
| 1 | 数据集页：<https://data.gov.my/data-catalogue/pharmaceutical_products> | 标题「Approved Pharmaceutical Products」；说明「Complete list of pharmaceutical products approved by the Drug Control Authority」「exact copy of the administrative record of approved products, with any columns containing personal data excluded」；数据源 NPRA / MOH；`Last updated: 19 Nov 2026, 03:00` | 产品级、官方 |
| 2 | 同页 License 段 | **「This data is made open under the Creative Commons Attribution 4.0 International License (CC BY 4.0)」** + 许可链接 <https://creativecommons.org/licenses/by/4.0/> | **🟢 可再发布** |
| 3 | 数据文件：<https://storage.data.gov.my/healthcare/pharmaceutical_products.csv> | 实测 HTTP 200；**10,661,861 B**；UTF-8；16 列；**28,333 行**（不含表头） | 可批量 |
| 4 | 注销数据集：<https://data.gov.my/data-catalogue/pharmaceutical_products_cancelled> | 同为 CC BY 4.0；CSV 223,753 B；**1,623 行**；7 列（注册号、商品名、类别、持有人、制造商、注册日、注销生效日） | 可做状态回填 |
| 5 | 门户原则页：<https://data.gov.my/> 底部「Public Sector Open Data」 | 马来西亚政府开放数据门户；同一门户的 NPRA 制造商/进口商/批发商数据集也均标 CC BY 4.0 | 许可口径一致 |

> **许可结论**：CC BY 4.0 是本站口径里的 ✅「可再发布」。义务只有：署名 NPRA / data.gov.my、附 CC BY 4.0 链接、标明是否修改。**不需要向 NPRA 发信申请**，也不属于「统计汇总有许可、产品清单没许可」的情况——这次看的正是产品级清单本身。

## 2. 字段与质量核对

CSV 表头（逐字）：

```
reg_no, ref_no, product, status, description, holder, holder_osa, manufacturer,
manufacturer_osa, importer, importer_osa, date_reg, date_end, active_ingredient,
mdc_code, generic_name
```

实测分布：

| 维度 | 数值 |
|---|---|
| 总行数 | 28,333 |
| `status` | PRODUCT APPROVED 27,985；CONDITIONAL REGISTRATION 348 |
| `description`（产品类别，**不是剂型**） | NATURAL PRODUCT 13,036；HEALTH SUPPLEMENT 5,165；PRESCRIPTION 5,150；NON PRESCRIPTION 1,706；NEW CHEMICAL ENTITY 1,567；VETERINARY 1,047；BIOLOGICS 662 |
| `active_ingredient` 非空 | 28,311（99.9%） |
| `generic_name` 非空 | 4,068（14.4%） |
| `mdc_code` 非空 | 8,477（29.9%）；ATC 前缀 8,466 |
| 西药类 ATC 覆盖 | 8,466 / 9,085 = **93.2%** |
| 商品名去重（小写） | 28,135 |
| 注册号去重 | 28,261 |

字段样例（事实字段，原文照录）：

```
MAL11110010AZ | Terbicip 250mg Tablets | PRODUCT APPROVED | PRESCRIPTION
CIPLA MALAYSIA SDN BHD | 2021-11-23 | 2026-11-23
TERBINAFINE HYDROCHLORIDE[281.250;mg;;0] | D01BA02-110-T10-01-009
generic_name = Terbinafine HCI 250 mg Tablet
```

**成分串编码**：`成分名[数量;单位;包装量;?]`，多成分用逗号分隔；天然产品会出现 `[200mg;250mg]` 这类「每包装含量/总量」写法。拆解规则要写成 `etl/markets/my.py` 的单元测试，不能靠人眼。

**剂型缺口**：官方没有 `dosage_form` 列；`description` 只到「Prescription / Non prescription / Natural product / Veterinary / Biologics」这类监管类别。剂型只能从商品名/通用名派生：

- 商品名含剂型词的商品 **21,736 / 28,333（76.7%）**；
- 高频词：capsule 6,890、tablet 6,356、powder 2,072、solution 1,543、gel 1,497、injection 1,403、granule 1,375、syrup 561、cream 472、suspension 414；
- 剩余约 23% 需要「成分 + 包装单位 + 人工词表」兜底，页面应允许「剂型未知」，不要硬猜。

**状态/时间**：`status` 只有「批准 / 有条件注册」；`date_end` 是注册到期日。注销状态要用第二个数据集回填（1,623 条），不能把到期日直接当「已注销」。

## 3. 建议的入库口径（下一写库窗口）

1. **source 行**：`my_npra_products`，`license='CC BY 4.0'`，`license_url='https://creativecommons.org/licenses/by/4.0/'`，`source_url='https://data.gov.my/data-catalogue/pharmaceutical_products'`。
2. **product**：以 `reg_no` 为业务键（28,261 个唯一注册号，重复行是同一注册号的多包装/多记录，入库前按「注册号 + 商品名 + 成分串」去重）；`country='MY'`；`status` 映射 approved / conditional / cancelled；`date_reg`/`date_end` 保留。
3. **product_name**：`product` 原文进 `product_name`（按现有归一化规则做大小写/空白处理，**不把俗称写进 product_name**）。
4. **成分/规格**：解析 `active_ingredient`；成分名先做大小写与盐基归一，再走现有 substance 映射；解析失败的整行**保留商品名与注册号**，规格留空，不阻断入库。
5. **剂型**：从商品名尾缀 + 通用名抽取；抽不到写 `unknown`，页面显示「剂型未提供」，不做推断。
6. **About/页脚署名**：`Source: National Pharmaceutical Regulatory Agency (NPRA), Malaysia / data.gov.my — CC BY 4.0`，附数据集链接与「数据截止 2026-11-18」；若做归一化，加一句「本站对字段做了归一化处理」。
7. **验证**：`db/check_data.py` exit 0；对账 `SELECT COUNT(*) FROM product WHERE country='MY'` = 28,333（去重前）/ 实际入库数写进报告；抽 10 条商品名与 CSV 原文对照。

## 4. 风险与边界

| 风险 | 处理 |
|---|---|
| 官方是「行政记录」，明确写「不得作为法律行动依据」 | About 原样保留该免责声明的中文/英文表述；不把状态当作执法结论 |
| 每日更新，CSV 会被覆盖 | 入库快照写 `data/raw/my/YYYYMMDD/`（不入库）；报告记录 sha256 与抓取时间 |
| 天然产品/保健品占 64%，成分不是西药 INN | 只做「同成分在 MY 的叫法」；不强行映射到西药 substance，避免污染碰撞 |
| 剂型缺失、规格编码不统一 | 页面允许 unknown；不输出剂量换算或用药建议（§1.3） |
| 商品名可能含包装描述/多语言 | 只做事实字段展示；不转载说明书/宣传语 |

## 5. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$tmp = Join-Path $env:TEMP 'my_check'
New-Item -ItemType Directory -Force $tmp | Out-Null
Invoke-WebRequest -Uri 'https://storage.data.gov.my/healthcare/pharmaceutical_products.csv' -OutFile (Join-Path $tmp 'products.csv') -UseBasicParsing
& $py -c "import csv; rows=list(csv.DictReader(open(r'$tmp\products.csv',encoding='utf-8'))); print(len(rows), rows[0]['product'])"
```

_本报告只做许可与可行性评估，不含任何写库/发布动作。_
