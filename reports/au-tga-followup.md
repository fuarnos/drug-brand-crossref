# 澳大利亚 TGA 申请跟进（在线表单无确认 / 无参考号）

> 日期：2026-10-28 ｜ 任务：`task-106` ｜ 性质：只调研/写报告与邮件草稿；未写 DB、未改 `site/build.py`、未 git/发布。
> 背景：用户 **2026-10-26 21:33（America/Los_Angeles）** 通过 TGA 在线表单申请「ARTG 现行药品条目机器可读数据」；
> 页面显示 **Submission successful**，但**未给参考号**；提交时使用的邮箱（含 fuarnos@gmail.com）**未收到确认/回复**。
> 本报告核对正确渠道、公开数据现状（与现有 34,594 条 ARTG 名称/11,890 AU 产品对比）、SLA，并给可复制邮件。

---

## 0. 结论（先看）

| 问题 | 结论 |
|---|---|
| **ARTG 数据是否已公开** | **未发现公开的机器可读 ARTG 批量数据**：`data.gov.au` 无 TGA/ARTG 数据集（CKAN 搜索 `ARTG` 命中 1 条无关的博物馆年报；`TGA` 命中 9 条无关；组织列表无 TGA）；TGA 的 ARTG 公共查询是 **eBS 网页检索**（`https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview`，HTTP 200，Last updated 2026-10-29），有 Product/Sponsor/ARTG Id/Active Ingredient 等检索字段，但**无公开下载/API**。→ **申请不重复**，但首封邮件应问「是否已有公开数据集/API」，避免重复劳动。 |
| **正确申请渠道** | TGA 没有单独的「数据申请页」入口（至少公开页面未检索到）；正式路径是：① **在线 enquiry form / `info@tga.gov.au`**（现有申请就是在线表单，跟进走这里）；② **再发布/版权许可**：`tga.copyright@tga.gov.au`（TGA Copyright Officer，TGA 版权页明确「不得再传输/分发/商业化，需 prior written approval」）；③ 若 TGA 拒绝/不提供：**FOI** `foi@health.gov.au`（FOI Act；TGA FOI 页：**14 天内确认收到、30 天内决定**，可延长）。 |
| **在线表单是否应有确认/SLA** | TGA **《customer service standards》**：对 letters/emails **5 个工作日内确认（acknowledge）**；5 天内不能完整答复会告知预计时间并持续更新（该页归档快照，last updated 2017-08-23；当前页面 403，见 §6）。**没有**统一「10–20 工作日」SLA；10/20 工作日只能作为自我跟踪节点，不是 TGA 承诺。FOI 才有法定 14/30 天。 |
| **提交是否异常** | 页面显示成功但无参考号 + 无确认，可能是：① 在线表单本身不发参考号/确认；② 邮件进了垃圾箱或被过滤；③ 表单提交实际未送达（注意：我们这边访问 tga.gov.au 现在返回 **403 反爬拦截**，见 §6——但用户浏览器当时能显示成功页，说明提交可能已受理）。→ 先发跟进邮件，不重复盲目提交；若确认未收到再重交一次并截图。 |
| **我们已有数据 vs 申请** | DB `artg_entry` **34,594 条**（`artg_index`，仅名称/申办方/ARTG ID，抓取于 2026-10-26 13:23 LA = 2026-10-27 07:23 AEDT）；AU product **11,890**（PBS 5,452 / TGA CMI 4,730 / artg_detail 1,559 / enrich 144 / manual 5）。**名称层已接近覆盖当前 ARTG 药品目录**，但缺活性成分/规格/剂型/状态/日期等字段 → 申请仍有价值；若 TGA 已有公开数据集，改用公开源即可。 |
| **推荐动作** | **现在**发跟进邮件到 `info@tga.gov.au`，抄送 `tga.copyright@tga.gov.au`（许可问题）；按 TGA 5 工作日标准，**2026-11-02（周一）前**应收到确认；11-02 后无确认 → 电话 **1800 020 653 / +61 2 6289 4124** 并重交一次表单（截图）；若 10 个工作日（约 11-10）仍无实质答复 → 走 FOI（`foi@health.gov.au`，14 天确认/30 天决定）；期间保留邮件/截图，避免重复提交。 |

---

## 1. 渠道核实（证据与时间换算）

### 1.1 申请时间换算（务必在跟进信中写清）

- 提交：**2026-10-26 21:33 America/Los_Angeles**
- = **2026-10-27 04:33 UTC**
- = **2026-10-27 15:33 AEDT（Canberra/Sydney，UTC+11）** → 属于 TGA 工作时间（周一至周五 9:00–17:00 AET）
- 5 个工作日（按 TGA 服务标准）：27 Oct（二）、28（三）、29（四）、30（五）、**2 Nov（一）** → **2026-11-02 前**应有确认；
  10 个工作日 ≈ **2026-11-10**；20 个工作日 ≈ **2026-11-24**（仅自跟踪，非 TGA 承诺）。

### 1.2 TGA 联系/渠道（归档页/搜索证据）

| 渠道 | 地址/说明 | 证据 |
|---|---|---|
| 在线 enquiry form | `https://www.tga.gov.au/contact-us` → 「Email us」表单（/node/349746） | TGA Contact us（Wayback 2025-10-03 快照；当前 403，见 §6） |
| 通用邮箱 | **info@tga.gov.au**；电话 **1800 020 653**（澳）/ **+61 2 6289 4124**（海外）；9:00–17:00 AET | TGA 版权/联系页归档文本 |
| 版权/再发布许可 | **tga.copyright@tga.gov.au**，TGA Copyright Officer, PO Box 100, Woden ACT 2606 | TGA Copyright 页（Wayback 2015 快照）：非商业个人/内部使用可下载/打印；**「You are not permitted to re-transmit, distribute or commercialise the material without obtaining prior written approval」** |
| FOI（拒绝后的正式路径） | **foi@health.gov.au**（Department of Health FOI） | TGA FOI 页（Wayback 2015 快照）：收到请求 **14 天内确认**，**30 天内决定**（第三人咨询可 +30 天，复杂可协商延长） |
| eBS/ARTG 数据技术问题 | **eBS@health.gov.au** | eBS 公共注册页 footer |
| 数据公开入口（已查无） | data.gov.au CKAN API：`package_search?q=ARTG` → 1 条无关；`q=TGA` → 9 条无关；组织列表无 TGA | 本任务 `.tmp/au-tga/data_gov_au_search.json`（HTTP 200） |

> TGA 网站对自动访问有反爬：我们从本机访问 `tga.gov.au` 的 contact/data/ARTG 页均 **HTTP 403 blocked**（含 "reference number" 安全页），
> 只能读 Wayback 归档。**这不影响用户自己浏览器提交**，但说明：**用邮件跟进比反复提交网页表单更稳妥**。

### 1.3 ARTG 公共注册（ebs）现状

- 入口：`https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview`（HTTP 200）。
- 页面：**Australian Register - Current Medicines**；检索字段：Product name / Sponsor name / ARTG Id / ARTG Label Name / Active Ingredient（Fuzzy search）；
  列表列：Product / Sponsor / ARTG Id；**30 条/页**；Last updated **29 October 2026**；footer 联系 `eBS@health.gov.au`。
- 详情页（`openMILL(...)` JavaScript）可看条目摘要/CMI/PI 链接，但**没有批量导出、没有公开 API、没有 CSV/JSON 下载**。
- 我们 DB 的 34,594 条名称来自同一 eBS 视图的翻页抓取（`source_id=artg_index`，只取名称/申办方/ARTG ID），与公开网页一致；**缺字段**（成分、规格、剂型、状态、日期、类别）。

---

## 2. 公开数据现状 vs 我们的数据（避免重复申请）

| 项 | 数值/事实 |
|---|---|
| 我们 DB `artg_entry` | **34,594** 条（`artg_index`；字段 ARTG ID/名称/申办方/name_norm；retrieved 2026-10-26T13:23–13:25 LA） |
| 我们 DB AU products | **11,890**：PBS 5,452、TGA CMI 4,730、artg_detail 1,559、artg_enrich 144、manual_seed 5 |
| eBS 当前药品注册 | 公共网页可检索；按页 30 条，未给总数；最后更新 2026-10-29；**无公开批量文件** |
| data.gov.au | 无 TGA/ARTG 数据集（见 §1.2） |
| 是否存在官方 API/数据集 | **未发现公开 API**；TGA Business Services/ARTG-AMT（SNOMED CT-AU/AMT）是给注册申办方/术语实施方的受许可渠道（digitalhealth.gov.au 页面我们这边 403；不视为开放数据）；如 TGA 回复说有，优先用官方源 |
| 结论 | 我们的 34,594 **名称层**不等于完整 ARTG 数据；申请要的是**字段级机器可读数据**（成分/规格/剂型/状态/日期/类别），**不是重复申请**；首封邮件先问「是否已公开」并列出我们已有名称层，避免 TGA 误以为重复劳动 |

---

## 3. SLA / 确认建议

| 节点 | 依据 | 建议动作 |
|---|---|---|
| 提交后 **5 个工作日（2026-11-02 前）** | TGA Customer service standards（归档页）：「acknowledge your letters and emails within 5 working days」；不能完整答复会告知预计时间 | 发跟进邮件，礼貌请确认收到/给参考号/预计时间；**不要**在这之前重复提交 |
| **2026-11-02 后仍无确认** | 同上 | 电话 TGA（1800 020 653 / +61 2 6289 4124）；重交一次在线表单并截图；邮件再提醒 |
| **10 个工作日（≈2026-11-10）无实质答复** | 无公开 10 天承诺；按实际进度判断 | 升级：向 TGA 明确要求给出书面处理计划；准备 FOI |
| **仍未解决** | FOI Act / TGA FOI 页：**14 天确认、30 天决定**（可延长） | 用 `foi@health.gov.au` 正式 FOI；用户本人递交（费用/范围按 FOI 规定） |
| 再发布许可 | TGA Copyright：非商业个人/内部使用可以，但**再传输/分发/商业化需 prior written approval** | 同一封跟进信抄送 `tga.copyright@tga.gov.au`；如只允许内部使用，申请许可/说明公益用途；得到书面同意前**不要把 TGA 数据上线** |

> 「10–20 工作日」不是 TGA 公开承诺，只作为内部跟踪窗口；**正式法定时限只有 FOI 的 14/30 天**。

---

## 4. 跟进邮件草稿（英文，可复制发送）

> **To:** info@tga.gov.au
> **Cc:** tga.copyright@tga.gov.au
> **Subject:** Follow-up: data request submitted 27 Oct 2026 — no reference number or acknowledgement (ARTG medicines data)
>
> Dear TGA team,
>
> I am writing to follow up on a request for machine-readable ARTG data that I submitted through the TGA online enquiry form on **26 October 2026 at 21:33 (America/Los_Angeles)**, which is **27 October 2026, 04:33 UTC / 15:33 AEDT**.
>
> The page displayed **"Submission successful"**, but **no reference number was provided**, and I have not received any acknowledgement at the email address(es) used in the submission (including **fuarnos@gmail.com**). Could you please:
> 1. confirm whether the request was received;
> 2. provide a reference/case number; and
> 3. indicate the expected response date, in line with the TGA customer service standard of acknowledging letters and emails within 5 working days?
>
> **Request summary.** Machine-readable data for current human medicine entries on the Australian Register of Therapeutic Goods (ARTG). Fields requested: ARTG ID; product/ARTG label name; active ingredient(s) and strength; dosage form; sponsor; ARTG registration/approval status and relevant dates; product category/type; public ARTG summary URL (and ATC code if held). Preferred format: CSV/Excel/JSON or API; frequency: monthly or as updated (please advise); current register first (historical data if available). For context, our project currently holds a **name-level extract of the public eBS ARTG current medicines view (34,594 names with sponsor and ARTG ID)**, but it does **not** include the fields listed above.
>
> **Purpose and licence.** The data would be used on a free, non-commercial public-interest website (https://fuornos.github.io/drug-brand-crossref/) that helps users identify which active ingredient a brand name refers to and find corresponding products in other markets. We do **not** provide medical advice, dosing advice or interchangeability claims. We would display only factual fields with attribution such as **"Source: TGA ARTG (data as of YYYY-MM-DD)"**, link each record to the official ARTG/eBS page, and would **not** reproduce PI/CMI text, sell, sublicense or redistribute the raw data as a standalone product.
>
> **Permission.** Please confirm whether re-publication of these factual fields is permitted under TGA copyright terms and, if so, the required attribution/form; if written permission is required, please direct me to the TGA Copyright Officer (I have copied tga.copyright@tga.gov.au). If only internal/non-commercial use is permitted, please advise an appropriate licence or approval path for a non-commercial public-interest site.
>
> **Public data check.** I have not been able to find a bulk/machine-readable ARTG dataset on data.gov.au or the TGA website (the eBS register appears to be a web-only search interface). Could you confirm whether such a dataset/API already exists (including any TGA/ARTG-AMT or data.gov.au release)? If yes, please point me to the URL, licence and update frequency, and I will use the published source rather than asking for a new extract.
>
> Given the 5-working-day acknowledgement standard, I would be grateful for confirmation by **2 November 2026**. If the online form cannot issue a reference number, please let me know the correct channel; if a formal data request or FOI application is required, please advise and I will follow that process. If the original submission was not received for any technical reason, please let me know so I can resubmit once.
>
> Thank you for your help. I am happy to provide further details, sign any required conditions, or pay a reasonable fee.
>
> Kind regards,
> **傅振峰 (Zhenfeng Fu)**
> fuarnos@gmail.com
> https://fuornos.github.io/drug-brand-crossref/ (non-commercial)

**发送建议**：直接邮件（不要只依赖网页表单）；如希望留痕，可同时把同一正文粘到 TGA 在线 enquiry form 一次（附「email sent on 28 Oct 2026」），但只重交一次。发送后保存邮件与截图；若 11-02 无确认再电话。

---

## 5. 风险与注意事项

| # | 风险 | 说明/缓解 |
|---|---|---|
| R1 | 在线表单可能根本没送达（无参考号、无确认） | 现在改走邮件+抄送版权官；告知可能需重交一次；不要连续多次提交（防重复/被反爬标记） |
| R2 | TGA 网站反爬 403 | 我们本机访问被拦；用户浏览器可提交；跟进以邮件/电话为主；引用归档页作为依据 |
| R3 | 「10–20 工作日」不是 TGA 承诺 | 以 5 工作日确认 + FOI 14/30 天为准；10/20 只作自跟踪 |
| R4 | 再发布许可≠数据访问 | 即使拿到数据，TGA Copyright 默认仅个人/内部非商业使用；**必须拿到书面再发布许可**，否则不能上站 |
| R5 | 重复申请 | 首封邮件先问「是否已公开/已有 API」，并说明我们已有名称层；如官方有数据集就撤回申请 |
| R6 | 我们已有 34,594 名称层可能不是 ARTG 全量 | eBS 只给当前药品视图；名称层不等于完整注册库；申请书中不要声称「已覆盖全部 ARTG」，只作背景 |
| R7 | 数据字段/更新频率不确定 | 邮件中明确字段/频率/格式；拿到样本后先 dry-run 对比现有 AU 11,890 产品，再决定是否替换/补充 |
| R8 | 隐私/公开仓库 | 本报告含用户邮箱；若报告会公开，建议发送前把邮箱替换为占位（本地留有填好版） |

---

## 6. 证据文件（`.tmp/au-tga/`）

| 文件 | 内容 |
|---|---|
| `data_gov_au_search.json`、`data_gov_au_orgs.json`、`data_gov_au_tga_search2.json` | data.gov.au CKAN 查询结果（无 TGA/ARTG 数据集） |
| `recon.py` | DB `artg_entry`（34,594）/ AU products（11,890）/ 来源分布 |
| `fetch_tga.py` | 直接访问 TGA 页面返回 403/超时的记录 |
| `tga_contact_us.html`、`tga_copyright.html`、`tga_freedom_information.html`、`tga_resources_artg.html` | Wayback 归档的 TGA 联系/版权/FOI/ARTG 页 |
| `tga_customer_service_standards.html` | TGA 客服标准归档页（5 工作日确认） |
| `wayback*.py`、`css.py`、`followup-email.md`/.eml、`README.md` | 归档抓取/条款抽取脚本；跟进邮件（本地）；证据索引 |
| `ebs` 实测 | `https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview`（HTTP 200，2026-10-29 更新，无批量下载） |

**关键引用 URL**
- TGA Contact us：https://www.tga.gov.au/contact-us （归档：https://web.archive.org/web/20260922213901/https://www.tga.gov.au/contact-us）
- TGA Customer service standards：https://www.tga.gov.au/contact-us/tga-customer-service-standards （归档快照，5 工作日确认）
- TGA Copyright：https://www.tga.gov.au/copyright （归档 2015：非商业个人/内部使用；再发布需书面许可；`tga.copyright@tga.gov.au`）
- TGA FOI：https://www.tga.gov.au/freedom-information （归档 2015：14 天确认/30 天决定；`foi@health.gov.au`）
- ARTG eBS：https://www.ebs.tga.gov.au/ebs/ANZTPAR/PublicWeb.nsf/Medicines?openview （HTTP 200）
- data.gov.au API：https://data.gov.au/data/api/3/action/package_search?q=ARTG / ?q=TGA （无相关数据集）
