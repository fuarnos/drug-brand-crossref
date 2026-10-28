# CN 商品名/品牌名扩充：来源审计 + 候选抓取（task-85）

> 日期：2026-10-28 ｜ 只读 `data/drugs.db`（未写库）；未改 `site/build.py`；未跑 git/发布。
> 产物：`etl/fetch_cn_brand_names.py`、`data/cn_brand_candidates.csv`（471 行）、本报告；缓存/统计/许可记录在 `.tmp/cn-brands/` 与 `data/raw/cn_brands/`。

## 1. 结论（先看这）

1. **NHSA「医保药品分类与代码」的商品名列已被现有库基本吃干**：两版快照共 486,467 行、其中 36,154 行有商品名、去重 **5,004 个品牌名**；DB 现有 CN 品牌键 **4,866**，按批准文号匹配 **98.4%** 的品牌已在库里。NHSA 侧只剩 **465 行**「品牌名已存在但没挂到该批准文号商品上」的补挂机会 + **10 个**全新品牌名。
2. **候选 CSV**：`data/cn_brand_candidates.csv` 共 **471 行**（快照 465 + 公示批次增量 6）：
   - 唯一品牌 **353** 个，其中**新品牌名 17 行 / 15 个不同名**（如 严馨、奇纯、干舒乐、復安欣、达纳康…）；
   - 可补挂到 DB 产品的行 **471**（`approval_id` 直连 `product.product_id`）；
   - 置信度：新品牌行 high、补挂行 medium；来源/许可/source_url 逐行记录。
3. **覆盖估算**：品牌键 **4,866 → 4,881**（+15，+0.3%）；有 trade 名的 CN 产品 **18,287 → 18,758**（12.50% → **12.82%**）。
4. **真正的大缺口不在 NHSA**：DB 有 **69,380 个批准文号 / 146,347 个 CN 产品**，其中 **60,984 个批文（128,060 个产品）在 NHSA 里商品名就是「无」**——要补这些只能靠 NMPA 说明书/批准文号页、集采目录、商业数据或人工种子；本轮审计结论：**没有找到「开放许可 + 可批量」的中文商品名来源**（详见 §2）。因此本轮候选只能小幅提升，不建议为这 471 行单独发版；建议与「人工种子/商业授权」任务合并后再入库。

## 2. 来源审计（`--audit-sources` → `.tmp/cn-brands/source_audit.json`）

| 来源 | 许可状态 | 可批量 | 本轮 | 备注 |
|---|---|---|---|---|
| **国家医保局 医保药品分类与代码**（[code.nhsa.gov.cn](https://code.nhsa.gov.cn/yp/toPublicGoodsData.html)，仓库已有 2024-01-05/2025-04-04 快照） | 🔴 未找到再发布许可（政府公开信息，非开放许可）；沿用 `docs/许可清单.md`：**仅事实字段 + 链原文，不发布原表/快照** | ✅ 快照本地解析 | ✅ 已用 | 商品名列「无」= 无商品名；是当前最重要来源，已接近饱和 |
| **NHSA 公示批次 API**（增量） | 🔴 同上 | ⚠️ 仅部分历史批次有数据（20220110 有；2023+ 返回 0） | ✅ 小批量（2 页/1,768 条） | 限速 2.5s、断点、缓存、许可记录已实现 |
| **NMPA 数据查询 / 药品说明书页**（[nmpa.gov.cn/datasearch](https://www.nmpa.gov.cn/datasearch/home-index.html)） | 🔴 未见开放许可；网站声明页本轮 **HTTP 412（WAF）**，无法确认转载条款 | ❌ 动态查询 + 反爬，无批量下载 | ❌ 未抓 | 只适合人工/逐条事实核对；批量前需法务确认 |
| **药监局/省级局 说明书 PDF** | 🔴 未找到开放许可 | ❌ 分散、非结构化 | ❌ 未抓 | 说明书【商品名称】栏可作人工核对来源 |
| **国家/省级药品集采中选结果**（联采办 [smpaa.cn](http://www.smpaa.cn/) 公告） | 🟡 公告类政府信息，无开放许可声明 | ⚠️ 可下载 PDF/Excel | ❌ 未抓 | 字段以**通用名/企业/规格**为主，商品名极少 → 对品牌扩充收益低 |
| **商业 API：摩熵数科「中国药品批文」**（[open.bcpmdata.com/api/12.html](https://open.bcpmdata.com/api/12.html)） | 🔴 商业 API（注册/API Key/询价），非开放许可，不能再发布 | ✅ 23 万+ 批文，含**商品名称**/活性成分/说明书 | ❌ 未用 | 若采购授权可一次性补齐；建议 Lead 评估预算 |
| **公开数据集（GitHub/Kaggle/HuggingFace）** | 🟡 本轮检索未找到「中文商品名 + 开放许可」数据集；命中的是医院百科（MIT，无商品名）或商业数据 | ❌ 无可用批量 | ❌ 未用 | 继续检索 CC0/CC-BY 说明书数据集 |

> 结论：可合法再发布的**事实字段**只有 NHSA（已用尽）；NMPA/集采/公开数据集要么无开放许可、要么无商品名、要么不可批量；商业 API 需要授权。**因此本任务无法完成「最大缺口」的大规模扩充，只能产出小批量候选 + 把缺口量化清楚。**

## 3. 脚本与抓取实现（`etl/fetch_cn_brand_names.py`）

- **只读 DB**（`mode=ro`），不写库；
- 模式：
  - `--source nhsa-snapshot`（默认合并）：离线解析 `data/raw/nhsa/*.csv` 商品名列 → 新品牌 + 未挂接的品牌-批文；
  - `--source nhsa-public-batch --batch 20220110 --max-pages N [--resume]`：GET 拿 JSESSIONID → API 分页；**限速 2.5s/请求**、断点 JSON（`.tmp/cn-brands/fetch_checkpoint.json`）、原始 JSON 缓存（`data/raw/cn_brands/batch_*.json`）、许可记录（`data/raw/cn_brands/license.json`）；
  - `--source all`（默认）：快照 + 公示批次合并，按 (品牌, 批文, 通用名) 去重；
  - `--audit-sources`：输出来源许可审计 JSON；
- **去重/过滤**：品牌≠「无」、≠通用名、长度 2–30、非「无商品名/不适用」等噪声；与 DB `name_key` 全集比较标 `is_new_brand`；按 `approval_id` 关联 DB 产品并标 `already_attached`；「已在 DB 品牌名但未挂到该批文」→ 补挂候选；
- 输出列：`brand_name, brand_norm, generic_name, approval_id, company, dosage_form, spec, source, source_url, license_note, data_as_of, confidence, is_new_brand, already_attached, db_product_ids, db_product_count, note`。

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/fetch_cn_brand_names.py --audit-sources
& $py etl/fetch_cn_brand_names.py                       # 快照 + 公示批次 → CSV
& $py etl/fetch_cn_brand_names.py --source nhsa-public-batch --batch 20220110 --max-pages 3 --resume
& $py etl/fetch_cn_brand_names.py --dry-run
```

本轮实际：快照 486,467 行 → 36,154 条有效商品名；公示批次抓 2 页 1,768 条（缓存 2 个 JSON）；候选 471 行写入 CSV。

## 4. 候选样例与分布

| 品牌 | 通用名 | 批准文号 | 企业 | 来源 | 类型 |
|---|---|---|---|---|---|
| 严馨 | 芩苓子阴道灌注液 | 国药准字Z20194010 | 苏州吴淞江制药 | NHSA 快照 | 新品牌 |
| 奇纯 | 去感热口服液 | 国药准字Z20080189 | 四川康特能药业 | NHSA 快照 | 新品牌 |
| 復安欣 | 磷霉素氨丁三醇散 | 国药准字H10930155 | 东北制药沈阳第一制药 | NHSA 快照 | 新品牌 |
| 冰中仙 | 冰硼散 | 国药准字Z41020254 | 河南蓝天药业 | 公示批次 | 新品牌（增量） |
| 优维显 / 典迈伦 / 信必可都保 / 舒利迭… | 对应复方/单方 | — | — | 快照 | 已存在但补挂（各 4–7 行） |

分布：快照 465 行 / 批次 6 行；新品牌行 17、补挂行 454；唯一品牌 353、唯一批文 470；`db_product_ids` 已填 470/471（1 行批文在 DB 无对应产品）。

## 5. 入库建议（只补 trade name，不改通用名身份）

1. **只作为 `product_name(name_type='trade')` 补挂**，不新增/不改变 substance/成分身份；批文→产品用 `approval_id` 直连（候选 CSV 的 `db_product_ids` 已给出），多条产品（不同规格/包装）同时挂同一品牌名。
2. **写库顺序建议**：先 apply 15 个新品牌 + 454 条补挂（幂等：同 key 已挂则跳过）→ `product.is_branded=1` → 生成/复用 `name_key`（`norm` 用 `normalize_name.normalize`，品牌原文进 `name_variant.raw`，lang 标 zh/en 由脚本按字符判断）→ 更新 `source/ingest_run`（source=nhsa，fact fields，保留 `source_url`）。
3. **验证**：`db/check_data.py`、`collision` 视图差异（品牌名可能与其他成分通用名碰撞，是预期展示）、三语检索抽检（搜品牌名应命中该产品）、README/About 计数同步（Lead 口径）。
4. **人工抽检**：15 个新品牌里建议人工核对 3–5 个（如「神水藏药」「达纳康」是否确为商品名而非企业/系列名）；补挂行 medium 可全量 apply（只是把已有名字挂到对应批文，风险低）。
5. 不把商品名写进 `product_name(name_type='inn')`，不改变通用名 key；商品名重复（不同企业同名）允许，但要按批文挂接，不能把同名品牌合并成一个产品。

## 6. 覆盖估算与剩余缺口

| 指标 | 当前 | 本轮候选后（估算） |
|---|---:|---:|
| CN 品牌键（trade key） | 4,866 | **4,881**（+15） |
| 有 trade 名的 CN 产品 | 18,287 / 146,347 = 12.50% | **18,758 = 12.82%** |
| 有 trade 名的批准文号 | 8,396 / 69,380 = 12.10% | **8,867 ≈ 12.78%** |
| NHSA 商品名覆盖 | 已吸收 98.4% 品牌 | — |

**剩余缺口（60,984 个批文 / 128,060 个产品在 NHSA 无商品名）** 的可能来源与处置：

1. **NMPA 说明书/批准文号页**：事实字段可用，但无开放许可 + 反爬（本轮 412）；**建议法务确认后，只对 top 通用名逐条核实**（不作为批量入库）。
2. **商业 API（摩熵数科）**：23 万+ 批文含商品名，**采购授权**可一次性把品牌覆盖从 12% 拉到大多数（估算取决于授权范围）；需 Lead/预算决策。
3. **人工种子（推荐先做）**：从药店/电商榜单/说明书人工录 top 500–1,000 个品牌名（1 天内可完成），覆盖大部分用户搜索；本任务可提供模板（本 CSV 列结构即可）。
4. **集采目录**：商品名极少，不建议作为来源。
5. **公开数据集**：继续检索 CC0/CC-BY 的中文说明书数据集；找到后走同样的 fetch/ingest 通道。
6. **NHSA 未来公示批次**：按月增量（每次几十条品牌），可设定期抓取。

## 7. 风险

- **许可风险（最高）**：NHSA 是政府公开信息但无开放再发布许可；本 CSV 只含事实字段+来源 URL，未复制原表；NMPA/集采同样无开放许可，**不可批量转载**；商业 API 需授权合同。
- **品牌 vs 通用名/企业名混淆**：候选已过滤「品牌=通用名」及噪声，但仍有「系列名/企业名/商品名混写」风险（如「达纳康」）；入库前抽检 15 个新品牌。
- **同名不同药**：不同企业可共用品牌名（如「优维显」多批文）；必须按 `approval_id` 挂接，不能按名字合并产品。
- **增量非全库**：NHSA 公示批次是增量、非全库快照；`商品名称=无` 不代表真的无品牌（可能未公示）。
- **抓取稳定性/限速**：NHSA API 会变；脚本已限速 2.5s + 断点 + 缓存，不要并发狂抓；NMPA 有 WAF。
- **数据漂移**：DB 在任务期间被其他 agent 更新（本轮只读，统计按 2026-10-28 12:08 快照）；换库后重跑脚本即可。

## 8. 产物

| 文件 | 内容 |
|---|---|
| `etl/fetch_cn_brand_names.py` | 快照解析/公示批次抓取（限速、断点、缓存、许可记录）+ 候选 CSV 生成 |
| `data/cn_brand_candidates.csv` | 471 行品牌候选（17 新品牌行 + 454 补挂行；含 source/license/confidence/DB 产品 ID） |
| `data/raw/cn_brands/batch_20220110_p1/p2.json` | 公示批次原始缓存（1,768 条） |
| `data/raw/cn_brands/license.json` | 抓取来源的许可记录（事实字段 policy） |
| `.tmp/cn-brands/stats.json` / `fetch_checkpoint.json` / `source_audit.json` | 覆盖统计 / 断点 / 来源审计 |
| `reports/cn-brand-names.md` | 本报告 |
