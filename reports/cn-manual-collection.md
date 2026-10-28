# CN 省级挂网目录人工采集包（给人看的清单）— task-110

> 用途：用户/人工从各省医保局/阳光采购平台下载「含商品名的挂网目录/医保支付范围明细表/集采价格表」，放入
> `data/raw/cn_provinces/manual/`，由 `etl/fetch_cn_brand_names.py --expand-manual` 自动解析、对齐 DB、去重合并到
> `data/cn_brand_candidates.csv`（非盈利/公益、非商业使用；只取事实字段；来源署名+可撤下）。
> 不放原始文件进仓库跟踪区（`data/raw/` 不入库）；不写 DB、不改 build.py。

## 1. 优先省份与入口（按「已验证有商品名 + 可得性」排序）

| 优先级 | 省份 | 入口（人工浏览器打开） | 找什么文件 | 已知情况 |
|---|---|---|---|---|
| **P0** | **北京** | https://ybj.beijing.gov.cn/zczxs/2020_zhgga/ （医药阳光采购→挂网通知公告） | 「挂网目录」PDF/XLSX | ✅ 已验证 105 页 PDF：医保编码/通用名/**商品名**/剂型/规格/生产企业/**批准文号**/价格；1,725 行、264 品牌行、+19 新增 |
| **P0** | **江苏** | http://ybj.jiangsu.gov.cn/ （搜索「药品阳光采购挂网产品公布表」；月度/分批） | 公布表 PDF（每月一批） | ✅ 已验证 11 个 PDF 含商品名（第 5/6/14/18/20 批、202602、202607 等）；202607 29 页/661 行/29 品牌行 |
| **P0** | **浙江** | https://www.zjyxcg.cn/ （浙江药械采购中心）；附件域名 `zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn` | 挂网目录 PDF/XLSX | ✅ 已验证 4 页 PDF：通用名/**商品名**/剂型/规格/企业/投标企业 |
| **P1** | **天津** | https://ylbz.tj.gov.cn/xwzx/tzgg/ （通知公告，搜「医保支付范围」「挂网」） | 医保支付范围明细表 PDF | ⚠️ 已知含商品名/批准文号，但站点对本机 403；人工浏览器可下，值得优先 |
| **P1** | **上海** | https://www.smpaa.cn/ （上海阳光医药采购网）；https://ybj.sh.gov.cn/ （通知附件） | 挂网/价格公示附件 PDF/XLSX | ⚠️ 本机 403，人工可下；含商品名的表格优先 |
| **P1** | **山东** | http://ybj.shandong.gov.cn/ ；招采子系统 https://ypjc.ybj.shandong.gov.cn/trade/drug/query-of-hanging-directory/index | 挂网目录（页面可导出/复制） | 页面可访问，导出需人工 |
| **P2** | **青海** | http://ybj.qinghai.gov.cn/ （挂网目录/价格申报） | 挂网目录 PDF | ✅ 已验证 2 个 PDF 含商品名（2026-02：119 行/26 品牌行；但新增多为 0，老品牌已在 DB） |
| **P2** | **福建** | http://ybj.fj.gov.cn/ztzl/yxcg/ggtz/ （阳光采购→通知公告） | 挂网名单 PDF | 已验证挂网 PDF **无商品名**；可找支付范围表；收益较低 |
| **P2** | **湖南** | http://ybj.hunan.gov.cn/ （挂网目录/价格联动） | 挂网目录 PDF | 部分表有「商品通用名称」列；PDF 表格结构不一 |
| **P2** | **吉林** | http://ybj.jl.gov.cn/ybxw/gsgg/ （通知公告） | 挂网/价格文件 PDF | 有公开 PDF；商品名列需逐个看 |
| **P2** | **河北** | https://ylbzj.hebei.gov.cn/ （公布部分化学药品挂网的通知等） | 挂网目录/支付范围附件 | 公开通知页；附件可能含商品名 |
| **P2** | **四川** | https://www.scyxzbcg.cn/ （四川省药械招标采购服务中心 webPortal） | 挂网/分类采购公示 PDF | 有公开公示；商品名视批次 |
| **P2** | **湖北** | http://ybj.hubei.gov.cn/ （通知公告栏目） | 挂网/集采公示附件 | 有公开通知；附件商品名视文件 |
| **P3** | **广东** | http://hsa.gd.gov.cn/ ；广东省药品交易中心 https://mall.gdaee.com.cn/ | 挂网价格/集采公示 | 站点可访问；挂网目录多在交易中心（需人工） |
| **P3** | **河南** | 河南省医药集中采购平台/省公共资源交易中心（搜「豫医保办挂网规则」） | 挂网公示 | 入口待确认，可先搜「河南 药品 挂网 公示 附件」 |
| **P3** | **安徽** | https://ybj.ah.gov.cn/ （本机 403，人工试） | 挂网/支付范围 | 待验证 |
| **P3** | **辽宁** | https://ybj.ln.gov.cn/ ；旧采购平台 lnypcg.com.cn | 挂网/价格 PDF | 部分公开 PDF |
| **P3** | **贵州/广西** | 贵州 gpo.gzggzy.cn / 广西 http://ybj.gxzf.gov.cn/ | 挂网/集采公示 | 本机 418/连接重置；人工可试 |

> 其它省同理：找「医保局 → 通知公告/医药价格和招标采购 → 药品挂网/支付范围/集采」栏目；优先下载**带商品名列**的表格。

## 2. 文件类型与选择

1. **首选 PDF（表格型，非扫描件）**：可用 PyMuPDF `find_tables()` 直接抽表；扫描图片 PDF 不可解析（请换源或人工录 CSV）。
2. **其次 XLSX**：openpyxl 自动识别表头（前 40 行内含「商品名/商品名称/商品通用名」）。
3. **CSV**：自动尝试 UTF-8 / GB18030 / GBK 编码。
4. **HTML**：浏览器「另存为网页」或整页保存的表格页（解析 `<table>`）。
5. 旧版 `.xls` 请先另存 `.xlsx`（解析器明确不支持 .xls）。

**必须有「商品名」列**（商品名 / 商品名称 / 商品通用名）；同时最好有：
通用名（或药品名称）、**批准文号**（有则 high 直连 DB）、生产企业、剂型、规格、挂网价（可选）。
纯通用名/无商品名的目录收益接近 0，可跳过。

## 3. 命名规范与存放

- 目录：`data/raw/cn_provinces/manual/`（本采集包，已放 README.txt）。
- 文件名：`<省拼音>_<主题>_<期间/批次>_<下载日期>.<扩展名>`，例：
  `beijing_guawang_2026-07.pdf`、`jiangsu_guawang_20260701-0731.pdf`、`tianjin_zhifufanwei_2026-01.pdf`；
  主题用 `guawang`（挂网）/`zhifufanwei`（支付范围）/`jicai`（集采）/`jiage`（价格）。
- 来源登记（建议）：同目录 `sources.csv`，列 `file,province,title,url,download_date,license_note`；每文件一行。
- 同名/同批只放一份；不确定是否重复先放进来，解析器按 (品牌, 批文, 通用名) 去重。

## 4. 许可与撤下

- 政府公开信息，通常无开放再发布许可；本采集包仅在**非盈利/公益、非商业使用**下抽取事实字段，
  **不转载原表/PDF/整页**，不上传原始文件；页面署名来源（省医保局/文件名），并**可按来源方要求撤下**。
- 不登录、不绕验证码/WAF、不抓患者/个人数据；文件若标注「不得转载」请不要放（或仅内部核对并注明）。

## 5. 下载后怎么跑

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/fetch_cn_brand_names.py --expand-manual              # 解析 + 合并候选 CSV
& $py etl/fetch_cn_brand_names.py --expand-manual --dry-run    # 只看每文件统计
```
统计：`.tmp/cn-manual/manual_stats.json`（每文件 行数/品牌行/候选/新增/失败原因）。
新增行随后由 data-depth 的 task-108 apply 流程入库；**本轮不写 DB**。

## 6. 预期收益（按已知样本）

| 文件/省批 | 表格行 | 品牌行 | 新增（相对现有 CSV） |
|---|---:|---:|---:|
| 北京 挂网目录（105 页） | 1,725 | 264 | +19 |
| 江苏 月度（29 页） | 661 | 29 | +29（首次） |
| 青海 挂网目录（24 页） | 119 | 26 | 0（老品牌已在 DB） |
| 浙江 4 页 | 29 | 1 | +1 |
| 典型省级 PDF | 100–1,700 | 10–30% | 0–30/文件 |

10–20 个省 × 近 1–2 年批次，估计累计可补 **200–2,000 行**（0.3–3pp）；边际递减主要因为 70%+ 老品牌 NHSA 已覆盖，新增集中在**近两年新批创新药/生物药**。**NMPA 单条人工兜底**见
`reports/cn-brand-expand.md` §9.4（top 500–1,000 通用名，≥3s/请求，约 1–2 小时）。
