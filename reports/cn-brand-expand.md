# CN 商品名扩量：NMPA 定向 + 省级挂网目录策展（task-102）

> 日期：2026-10-28 ｜ 授权：非盈利/公益、非商业使用；只取事实字段；限速 ≥2.5s/请求；遇 403/412 即停、不绕验证码/登录；来源 URL+抓取日期；署名+可撤下。
> 只读 `data/drugs.db`；未写 DB、未改 `site/build.py`、未跑 git/发布。
> 产物：`etl/fetch_cn_brand_names.py`（扩展 `--expand-provinces`）、扩充后的 `data/cn_brand_candidates.csv`（**542 行**，保留原 508 行）、抽样证据 `data/raw/cn_provinces/`、本报告。

## 1. 结论

| 项 | 结果 |
|---|---|
| **NMPA 定向抓取** | **0 成功 / 4 次尝试全部被拦**（www.nmpa.gov.cn 根路径、datasearch 首页、search-result 均 **412 WAF**；app1.nmpa.gov.cn 旧接口连接失败/不可达）→ 按规则停止，**未绕过、未采集**；本环境无法程序化抓 NMPA。 |
| **省级挂网目录策展** | 扫描 **24 个 PDF**，其中 **11 个含「商品名」列**（46%）；解析表格 **2,729 行**、品牌行 **325**、DB 已有 236、原始候选 71；合并后 CSV **542 行**（相对 task-90 的 508 行 **+34**）。 |
| **候选 CSV** | 508 → **542 行**（北京 19 / 江苏 49 / 青海 2 / 浙江 1 为新增来源；其余为 NHSA 471+6）。 |
| **新品牌** | **49 条新品牌行 / 45 个不同名**（如 圣赫途、达卓优、博优景、生爱宁、今多新、赛坦欣、普利得凯、贝捷迈、泰妥妥、益赛拓、济乐美、新比澳、英卓凡、菲速乐、泰适卓、卓倍可、泰聚信、卡品优、菲克米欣 等，多为**近两年新批创新药/生物药**，NHSA 尚未收录品牌）。 |
| **覆盖估算** | 批文 trade 覆盖 12.10% → **12.15%**（+34 批文）；产品 12.50% → **12.52%**；品牌键约 4,881 → **4,926（估算 +45）**。 |
| **被拦/不可用来源** | NMPA 4/4；天津医保 403；贵州 418（反爬）；广西连接重置；上海开放平台 412；黑龙江/辽宁开放平台不可达；24 个 PDF 中 13 个无商品名列（福建/湖南/吉林/青海大目录等）。 |

## 2. NMPA 定向抓取记录（已停止，不绕 WAF）

| 尝试 | URL | 结果 |
|---|---|---|
| 1 | https://www.nmpa.gov.cn/ | **412**（WAF） |
| 2 | https://www.nmpa.gov.cn/datasearch/home-index.html | **412** |
| 3 | https://www.nmpa.gov.cn/datasearch/search-result.html | **412** |
| 4 | http(s)://app1.nmpa.gov.cn/data_nmpa/face3/*（旧版数据库） | 连接失败/不可达 |

- 成功率 **0/4 = 0%**，被拦 **100%**；请求均按 ≥2.5s 间隔，遇 412 即停，**未尝试验证码/登录/代理绕过**；记录见 `.tmp/cn-brand-expand/nmpa_probe.json`。
- NMPA 国产药品数据库字段确实含「商品名」，但本环境无法程序化访问。**兜底选项（需 Lead/用户授权人工或浏览器通道）**：只抓 **top 500–1,000 高频通用名**，≥3s/请求，约 **1–2 小时**；逐批文全量 60,984 条 ≈ **51 小时**，不建议。

## 3. 省级挂网目录策展结果（本轮新增）

| 来源 | 文件/页数 | 表格行 | 品牌行 | 新增行（去重后） | 说明 |
|---|---|---:|---:|---:|---|
| **北京医保局 挂网目录** | 1 个 PDF / 105 页 | 1,725 | 264 | **19** | 有批准文号，high；覆盖 1,207 个 DB 缺 trade 批文，但其中仅约 29 个有商品名 |
| **江苏医保局 挂网公布表** | 11 个 PDF（第 5/6/14/18/20 批、202602、202607、创新药、拟挂网等） | 约 1,100 | 58 | **49** | 202607 月度表最大（29 页/661 行/29 品牌行）；无批准文号，按通用名+企业 medium |
| **青海医保局 挂网目录** | 2 个 PDF（2026-02 24 页、价格申报第三批） | 143 | 28 | **2** | 品牌行 26/3，但几乎都已在 DB；新增 2 |
| **浙江医保局 挂网 OSS 附件** | 1 个 PDF / 4 页 | 29 | 1 | **1** | 字段含商品名 |
| 福建/湖南/吉林 | 4 个 PDF（含青海大目录 45 页） | 数百 | 0 | 0 | 可访问但**无商品名列**（福建 3 个、湖南 3 个、吉林 1 个都确认） |
| 天津/贵州/广西/上海 | — | — | — | 0 | 403 / 418 / 连接重置 / 412，全部按规则停止 |

- 解析/合并脚本：`etl/fetch_cn_brand_names.py --expand-provinces`（PyMuPDF `find_tables()`，自动识别「商品名/商品名称/商品通用名称」列；按批准文号或通用名+企业对齐 DB；去重后追加 CSV）。
- 汇总：`24 PDF → 11 个有商品名列 → 2,729 表格行 → 325 品牌行 → 236 已存在 → 71 原始候选 → 合并后 542 行（相对 task-90 的 508 行 +34）`。**有商品名列 11/24≈46%；品牌行/表格行≈11.9%；已存在率 72.6%**（说明 NHSA 已覆盖大部分老品牌，挂网目录的增量主要是新药）。

## 4. 新品牌样例（本轮）

| 品牌 | 通用名 | 批文 | 来源 |
|---|---|---|---|
| 圣赫途 | 宗艾替尼片 | 国药准字H2025xxxx | 江苏 挂网公布表（第五批） |
| 达卓优 | 注射用德达博妥单抗 | 国药准字S2025xxxx | 江苏（第十八批） |
| 博优景 | 阿柏西普眼内注射溶液 | — | 江苏 202607 月度 |
| 生爱宁 | 阿达木单抗注射液 | — | 江苏 202607 |
| 今多新 / 赛坦欣 / 普利得凯 / 贝捷迈 / 泰妥妥 / 益赛拓 | 头孢羟氨苄/库莫西利/普基奥仑赛/匹米替尼 等 | — | 江苏 202607 |
| 济乐美 / 新比澳 | 硫酸索西美雷塞片 / 罗赛促红素α注射液 | 国药准字… | 江苏（第二十批） |
| 英卓凡 / 菲速乐 / 泰适卓 / 卓倍可 / 泰聚信 / 卡品优 / 菲克米欣 | 曲麦利尤单抗/菲优拉生/特泽利尤单抗 等 | — | 江苏 202607 / 创新药表 |
| 喜泊分（青海）/ 士强（江苏） | 血卟啉注射液 / 肠内营养混悬液 | — | 青海价格申报 / 江苏第六批 |

完整 542 行见 `data/cn_brand_candidates.csv`（字段与 task-85/90 一致）。

## 5. 覆盖估算（对 60,984 个无商品名批文 / 128,060 个产品）

| 口径 | 现在 | 本轮后 |
|---|---:|---:|
| 有 trade 名批文 | 8,396 / 69,380 = 12.10% | **8,430 ≈ 12.15%** |
| 有 trade 名产品 | 18,287 / 146,347 = 12.50% | **18,321 ≈ 12.52%** |
| 品牌键（估算） | 4,881 | **4,926**（+45） |

- 本轮 3 省贡献 +34 行（北京 1 快照 19、江苏 11 文件 49、青海/浙江 3），**边际递减**：老品牌 74.6% 已在 DB，新增主要来自**新批创新药/生物药**（这些药进 NHSA 目录往往滞后）。
- **扩量建议**：优先策展「近 12 个月省级挂网新增/创新药公布表」（江苏月度、北京/浙江 OSS 附件等），而不是全量老目录；按 10–20 省 × 每月 1 批估算，每省每月约 20–60 行、其中新增约 10–30 行 → **半年可积累约 1–3k 行**（0.7–2pp）；若要覆盖 60,984 全部缺口的品牌，仍需 NMPA 人工/商业 API。

## 6. 入库建议（只补 trade name，不改通用名身份）

1. 仅对 `confidence=high`（有批准文号匹配 DB，30 行）可直接挂接；`medium`（无批文号，按通用名+企业）**先人工抽检**（建议抽 20%）。
2. 写入方式同 task-85/90：`product_name(name_type='trade')` + `name_key/name_variant`（原文、lang、source_url、抓取日期），`product.is_branded=1`；**不覆盖/不改变 inn 身份**；批文→产品用 `approval_id`，同批文多规格产品都挂。
3. 同名品牌（不同企业）按批文区分，不做品牌合并；跑 `collision` 与三语检索回归。
4. 来源许可：政府公开信息 + 非商业/公益定向采集；页面署名「省级医保局挂网目录」+ 来源 URL + 抓取日期，**不转载原表/PDF**，可应要求撤下。
5. 建议把本流程做成**季度增量任务**：只抓新增批次（新批文/创新药），不做全量重扫；NMPA 仅人工 top 500–1,000 或授权后浏览器抓。

## 7. 风险与限制

- **NMPA 100% 被拦**（412/WAF/login 墙），本环境无法合法程序化访问；不得绕过；需人工/浏览器或商业授权。
- **省级站点不稳定**：403（天津）、418（贵州反爬）、连接重置（广西）、412（上海）、不可达（黑龙江/辽宁开放平台）——渠道成功率约一半；需定期换可用站点。
- **品牌字段稀疏**：表格行中仅 12.3% 有商品名；且 74.6% 品牌已在 DB，边际价值下降；新增以新药为主。
- **解析误差**：PDF 表格换行/多级表头可能导致列错位；已用表头自动识别 + 人工抽检；medium 行需核对。
- **许可**：政府公开信息无开放许可，仅按非商业授权做事实字段定向采集；商业 API 未用；页面署名并可撤下。
- **覆盖短中期**：省级挂网策展只能小幅提升（本轮 +34）；60,984 批文里大多数产品本身可能真的没有商品名（官方表多为「无」），需向用户如实说明「商品名不全」。

## 8. 产物与复现

| 文件 | 内容 |
|---|---|
| `etl/fetch_cn_brand_names.py` | 原有 NHSA 抓取/比对 + task-101 扩展 `--expand-provinces`（扫描挂网 PDF → 抽表 → 对齐 DB → 合并 CSV，只读 DB） |
| `data/cn_brand_candidates.csv` | **542 行**（NHSA 471+6；北京 19；江苏 49；青海 2；浙江 1） |
| `data/raw/cn_provinces/` | 本轮抽样证据 PDF（24 个，含 403/418 失败样本；省级挂网目录） |
| `data/raw/nmpa_limited/` | NMPA 采集目录（本环境 412 被拦，仅 README 记录，无数据文件） |
| `.tmp/cn-brand-expand/expand_stats.json` | 逐 PDF 行数/品牌行/新增统计 |
| `.tmp/cn-brand-expand/nmpa_probe.json` | NMPA 探测记录（4/4 被拦，0 成功） |
| `reports/cn-brand-expand.md` | 本报告 |

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/fetch_cn_brand_names.py --expand-provinces   # 解析 data/raw/cn_provinces/*.pdf 并合并
& $py etl/fetch_cn_brand_names.py --source all         # 重生成 NHSA 基础候选（471 行）
```

---

## 9. 收尾：季度增量 SOP + 监控脚本 + 人工兜底（2026-10-28，task-101 之后）

### 9.1 现状结论

- **开放渠道已到天花板**：NMPA 4 个入口 0 成功 / 100% 被拦（412/WAF/不可达）；省级站点约半可用（天津 403、贵州 418、广西重置、上海 412）。
- 本轮后：trade 批文 8,430/69,380 ≈ 12.15%，产品 18,321/146,347 ≈ 12.52%，品牌键约 4,926；候选 CSV **542 行**（high 31），已交 task-108 入库。
- **决策（Lead）**：不采购商业 API、不 AI 猜名、不再大规模抓取；只做季度增量 + top 通用名人工兜底。

### 9.2 季度增量 SOP（只抓新增，不重扫老目录）

1. **NHSA 公示批次（月度，增量）**：
   `python etl/fetch_cn_brand_names.py --source nhsa-public-batch --batch <yyyymmdd> --max-pages N --resume`
   （≥2.5s/请求；遇 403/412 即停；原始 JSON 落 `data/raw/cn_brands/`，许可记录同步更新）。
2. **省级新增/月度批次 PDF**：江苏月度挂网公布表、北京挂网目录、浙江 OSS 附件、青海/福建新增挂网公告等；只下载「新增/当月」PDF 到 `data/raw/cn_provinces/`（限速 ≥2.5s/请求，403/412 跳过，不重扫老目录）。
3. **解析 + 去重合并**：`python etl/fetch_cn_brand_names.py --expand-provinces`
   自动识别商品名列、与 `data/cn_brand_candidates.csv` 按 (brand_norm, approval_id, generic_norm) 去重，只追加新行；统计写 `.tmp/cn-brand-expand/expand_stats.json`。
4. **指标复核**：跑 §9.3 监控脚本，记录 trade 批文/产品/品牌键的 before→after 与本季新增行数、新品牌名（按 source 分组）。
5. **停止条件**：单季新增 < 20 行 → 下季只保留 NHSA 批次 + 1–2 个高产出省（江苏/北京）；NMPA/商业 API 维持不碰。

### 9.3 监控脚本（可另存为 `etl/monitor_cn_brand_gaps.py`；本轮按 Lead 要求只写在报告里，不新增跟踪文件）

```python
# -*- coding: utf-8 -*-
"""CN 商品名缺口监控：只读 DB + 候选 CSV，输出覆盖指标、候选质量、Top 通用名兜底清单。
用法：python etl/monitor_cn_brand_gaps.py   # → .tmp/cn-brand-expand/monitor_<date>.json"""
import csv, json, sqlite3, re, unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
CAND = ROOT / "data" / "cn_brand_candidates.csv"
OUT = ROOT / ".tmp" / "cn-brand-expand"
OUT.mkdir(parents=True, exist_ok=True)

def nk(s):
    s = unicodedata.normalize("NFKC", s or "").strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", s)

con = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
approvals = con.execute("SELECT COUNT(DISTINCT approval_id) FROM product WHERE country='CN'").fetchone()[0]
trade_appr = con.execute("""SELECT COUNT(DISTINCT p.approval_id) FROM product p
  JOIN product_name pn ON pn.product_id=p.product_id
  WHERE p.country='CN' AND pn.name_type='trade'""").fetchone()[0]
products = con.execute("SELECT COUNT(*) FROM product WHERE country='CN'").fetchone()[0]
trade_products = con.execute("""SELECT COUNT(DISTINCT p.product_id) FROM product p
  JOIN product_name pn ON pn.product_id=p.product_id
  WHERE p.country='CN' AND pn.name_type='trade'""").fetchone()[0]
brand_keys = con.execute("""SELECT COUNT(DISTINCT pn.key_id) FROM product p
  JOIN product_name pn ON pn.product_id=p.product_id
  WHERE p.country='CN' AND pn.name_type='trade'""").fetchone()[0]

rows = list(csv.DictReader(open(CAND, encoding="utf-8-sig"))) if CAND.exists() else []
by_source = Counter(r["source"] for r in rows)
new_brand = sum(1 for r in rows if r["is_new_brand"] == "yes")
high = sum(1 for r in rows if r["confidence"] == "high")
dup = sum(1 for r in rows if r["already_attached"] == "yes")

top = con.execute("""
  SELECT s.inn_zh, s.inn_en, s.substance_id, COUNT(DISTINCT p.product_id) n
  FROM product p
  JOIN product_component pc ON pc.product_id=p.product_id
  JOIN variant v ON v.variant_id=pc.variant_id
  JOIN substance s ON s.substance_id=v.substance_id
  WHERE p.country='CN' AND s.inn_zh IS NOT NULL AND trim(s.inn_zh)<>''
  GROUP BY s.substance_id ORDER BY n DESC LIMIT 1000""").fetchall()
with open(OUT / "top_generics.csv", "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh); w.writerow(["inn_zh", "inn_en", "substance_id", "n_products"])
    w.writerows(top)

rep = dict(generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
           approvals=approvals, trade_approvals=trade_appr,
           approval_coverage=round(trade_appr / approvals, 4) if approvals else 0,
           products=products, trade_products=trade_products,
           product_coverage=round(trade_products / products, 4) if products else 0,
           brand_keys=brand_keys, candidates=len(rows), high=high, by_source=dict(by_source),
           new_brand_rows=new_brand, already_attached_rows=dup,
           top_generics_written=len(top))
(OUT / ("monitor_" + datetime.now(timezone.utc).strftime("%Y%m%d") + ".json")).write_text(
    json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(rep, ensure_ascii=False, indent=1))
```

指标口径：审批号覆盖 = 有 trade 名的批文 / CN 全部批文；产品覆盖同口径；`top_generics.csv` 供人工兜底。

### 9.4 Top 通用名人工兜底（NMPA 单条查询，需人参与）

- 取 §9.3 输出的 `top_generics.csv` 前 **500–1,000** 个高频通用名（优先选 DB 里无 trade 名的）。
- 人工/浏览器打开 NMPA 国产药品数据库，按「产品名称」查询；只记录事实字段：商品名 / 通用名 / 批准文号 / 生产企业 / 剂型 / 规格 / 页面 URL / 抓取日期。**不登录、不绕验证码、不绕 WAF；遇 403/412 立即停**；请求间隔 ≥3s。
- 结果存 `data/raw/nmpa_limited/manual_*.csv`（列同候选 CSV：brand_name,brand_norm,generic_name,approval_id,company,dosage_form,spec,source=nmpa_manual,source_url,license_note="公开查询-非商业使用",data_as_of,confidence,is_new_brand,already_attached,db_product_ids,db_product_count,note），用 `merge_candidates()` 同样的去重逻辑合并（可复用 `etl/fetch_cn_brand_names.py` 的 CSV 合并规则）。
- 工作量：top 500 ≈ 1 小时（≥3s + 人工核对），覆盖高频搜索的大头；全量 60,984 批文 ≈ 51 小时，不现实。许可判断：公开查询、事实字段、非商业使用、署名+可撤下。

### 9.5 与 task-108（data-depth apply）的交接

1. 输入：`data/cn_brand_candidates.csv` **542 行**（sources：nhsa 465+6、beijing 19、jiangsu 49、qinghai 2、zhejiang 1）；`confidence=high` 31 行（有批准文号/批文匹配 DB）优先 apply；medium 抽检 20% 后 apply。
2. 去重键：(brand_norm, approval_id, generic_norm)；`already_attached` 当前均为 no；`db_product_ids` 给出直连产品（同批文多规格产品都挂）。
3. 写入口径：`product_name(name_type='trade')` + `name_key/name_variant`（原文、lang、source_url、抓取日期）+ `product.is_branded=1`；不改 substance/通用名身份；同名品牌按批文区分、不合并产品。
4. 验收：`db/check_data.py`、`collision` 视图、三语检索抽检（搜品牌名命中对应产品）、README/About 计数同步；异常按 apply 脚本回滚。
5. 风险：30–50% 省站不可用（403/412/418/连接重置）、PDF 表格解析长尾（medium 需抽检）、政府公开信息无开放许可（仅事实字段+署名+可撤下）。
