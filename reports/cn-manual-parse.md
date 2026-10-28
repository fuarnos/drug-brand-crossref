# CN 人工采集包解析器（`--expand-manual`）— task-110

> 日期：2026-10-28 ｜ 只读 DB；不写 DB、不改 `site/build.py`、不 git/发布。
> 产物：`etl/fetch_cn_brand_names.py`（新增 `--expand-manual`）、`data/raw/cn_provinces/manual/README.txt`、
> 采集清单 `reports/cn-manual-collection.md`、本报告；测试统计 `.tmp/cn-manual/manual_stats.json`。

## 1. 发生了什么

- **建立人工采集包**：`data/raw/cn_provinces/manual/`（含 README.txt：优先省份/入口 URL/命名规范/所需字段/许可注意）。
- **解析器扩展**：`etl/fetch_cn_brand_names.py --expand-manual`：
  - 扫描 `data/raw/cn_provinces/manual/**` 的 **PDF / XLSX / CSV / TXT / HTML**；
  - 自动识别表头中的「商品名 / 商品名称 / 商品通用名」列（前 40 行内扫描表头；兼容多级/换行表头）；
  - 抽取 商品名/通用名/批准文号/生产企业/剂型/规格/挂网价；
  - **对齐 DB**：有批准文号 → 直连 `product.approval_id`（high）；无批准文号 → 通用名+企业（medium）；
  - 跳过 DB 里已存在的 (批准文号, 品牌) 关联；按 `(brand_norm, approval_id, generic_norm)` 去重后追加
    `data/cn_brand_candidates.csv`；
  - 每文件输出 **解析行数 / 品牌行 / 候选 / 新增 / 失败原因**，写 `.tmp/cn-manual/manual_stats.json`；
  - **PDF 回退**：`find_tables()` 找不到含商品名的表时，尝试文本行 + 多空格分列解析（扫描件/图片 PDF 不支持）；
  - `.xls` 明确提示另存 `.xlsx`；CSV 自动试 UTF-8/GB18030/GBK 编码；HTML 解析 `<table>`。

## 2. 用法

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 人工把文件放到 data/raw/cn_provinces/manual/（建议同时填 sources.csv 记录来源）
# 2) 解析 + 合并候选 CSV
& $py etl/fetch_cn_brand_names.py --expand-manual
# 3) 只看统计、不写 CSV
& $py etl/fetch_cn_brand_names.py --expand-manual --dry-run
# 4) 指定其它目录（测试/分批导入）
& $py etl/fetch_cn_brand_names.py --expand-manual --manual-dir .tmp/cn-manual/samples
```

- 输出统计：`.tmp/cn-manual/manual_stats.json`（逐文件 rows/brand_rows/candidates/added/note）。
- 合并后的候选由 data-depth 的 **task-108 apply** 流程入库（high 优先；medium 抽检 20%）；本任务不写 DB。

## 3. 自测结果（2026-10-28）

### 3.1 真实省级 PDF（复制到 manual 自测）

| 文件（manual 下） | 格式 | 解析行 | 品牌行 | 候选 | 新增 | 说明 |
|---|---:|---:|---:|---:|---:|---|
| `jiangsu_202607_挂网公布表_2026-07_自测样本.pdf` | PDF | 661 | 29 | 29 | **0** | PyMuPDF find_tables；行已在候选 CSV 中（去重命中） |
| `qinghai_202602_挂网目录_自测样本.pdf` | PDF | 119 | 26 | 0 | **0** | 26 个品牌都已在 DB 挂接该批文，正确跳过 |

**结论**：真实 PDF 解析、对齐、去重、已存在跳过均符合预期；候选 CSV 保持 **542 行**（自测未新增重复行）。

### 3.2 合成格式样本（`.tmp/cn-manual/samples/`，dry-run）

| 文件 | 格式 | 解析行 | 品牌行 | 候选 | 说明 |
|---|---:|---:|---:|---:|---|
| `synthetic_挂网.html` | HTML | 1 | 1 | 1 | `<table>` 解析通过 |
| `synthetic_挂网目录.xlsx` | XLSX | 3 | 3 | 3 | openpyxl 表头识别通过（含批准文号） |
| `synthetic_支付范围.csv` | CSV (GB18030) | 2 | 2 | 0 | 编码识别通过；2 个品牌已在该批文下存在，正确跳过 |

## 4. 预期收益（供人工采集排序）

| 来源/批次 | 解析行 | 品牌行 | 新增（相对当前 CSV） |
|---|---:|---:|---:|
| 北京 挂网目录（105 页） | 1,725 | 264 | +19 |
| 江苏 月度（29 页） | 661 | 29 | +29（首次） |
| 浙江 4 页 | 29 | 1 | +1 |
| 青海 挂网目录（24 页） | 119 | 26 | 0（老品牌已在 DB） |
| 典型省级 PDF | 100–1,700 | 10–30% | 0–30/文件 |

- **10–20 个省 × 近 1–2 年批次**：预计累计新增 **200–2,000 行（0.3–3pp）**；优先级按
  `reports/cn-manual-collection.md` 的 P0（北京/江苏/浙江）→ P1（天津/上海/山东）→ P2/P3。
- 边际递减：70%+ 老品牌 NHSA 已覆盖，新增主要是**近两年新批创新药/生物药**（这些在 NHSA 目录里往往还没有商品名）。
- 纯通用名目录/扫描件 PDF 收益接近 0；请优先「带商品名列的表格型 PDF/XLSX」。

## 5. 风险与限制

- **扫描件 PDF 不支持**（无文本层）；请优先下载表格型 PDF，或人工录 CSV。
- **复杂表头/跨页合并**可能少解析几列：已用「前 40 行找表头 + 列名模糊匹配」；解析结果 medium 行需抽检。
- **旧版 .xls** 不支持（提示另存 xlsx）；**加密/受保护**文件不能解析。
- **来源许可**：政府公开信息，无开放再许可；只做事实字段、非商业使用、署名+可撤下；不转载原表/PDF。
- **同名不同企业**：按批准文号区分；无批文号时按通用名+企业对齐为 medium，入库前抽检。
- **人工量大**：单省单批约 1–2 分钟下载 + 解析 1 秒；建议每月/每季攒一批统一跑，不要逐日。

## 6. 验收

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/fetch_cn_brand_names.py --expand-manual --dry-run   # 期望：2 个 PDF 均解析成功、新增 0
& $py etl/fetch_cn_brand_names.py --expand-manual              # 合并（自测后 CSV 仍 542 行）
python -m py_compile etl/fetch_cn_brand_names.py
```

产物核对：`data/raw/cn_provinces/manual/README.txt` 存在；`reports/cn-manual-collection.md` 清单可照做；
`.tmp/cn-manual/manual_stats.json` 每文件统计齐全。
