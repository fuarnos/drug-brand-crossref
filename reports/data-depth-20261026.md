# 数据深度调研报告：MX 浓度 / CN 商品名 / ATC 覆盖

> 任务：`task-1`（只读调研，不改库、不改建站代码、不发布）
> 执行：并行子智能体 `data-depth` ｜ 日期：2026-10-26 ｜ 数据库快照：`data/drugs.db`（450 MB，只读打开）
> 写范围：本文件 + `.tmp/data-depth/`。所有 SQL/脚本/抽样输出都在 `.tmp/data-depth/`，可复跑。
> **标记约定**：`【已验证】` = 本次实际请求/查询/下载过并留下证据；`【推断】` = 基于已知事实或单点证据的估计，未做全量抽验。

---

## 0. 结论速览（按「影响 × 可行性」排序）

| 排名 | 方向 | 可提升量级（估算） | 可行性 | 许可 | 结论 |
|---|---|---|---|---|---|
| **P0** | **MX：并入 datos.gob.mx 上 4 个 CC-BY-4.0 药品明细数据集，扩充浓度回填字典** | **+1,615 个 MX 产品（28.7% → 43.6%）**，模拟值 | 高：CKAN API 一次拉取 2.9k+3.5k+2.2k+0.6k 行，字段已验证 | **CC-BY-4.0（可再发布，需署名）** | **立即做**，是本次唯一「许可干净 + 实测有量」的方向 |
| **P1** | **CN：改用「省级医保支付范围明细表」按批准文号回填商品名；同时刷新 NHSA 快照** | 商品名键 +1k～3k（推断）；数据新鲜度 +7.6% 行 | 中：需逐省 PDF/Excel 解析 + 批准文号对齐 | 政府公开信息、无开放许可 → 只存事实字段 + 出处链接 | **可做（有限）**，但要接受「商品名在官方表里大多就是 `/`」这一事实 |
| **P2** | **ATC：Wikidata P267（CC0）直接补** | **+341 个成分（缺口 4.5%）** | 高：一次 SPARQL，45 秒 | CC0 | **可做**，成本最低但量小 |
| P2 | ATC：CIMA（AEMPS）ATC 树补 `atc_name` | 最多 ~1.8k 条 ATC 名称（已覆盖部分），新增代码有限 | 中 | AEMPS 重用（署名） | 可做，属数据质量改善而非覆盖提升 |
| P3 | ATC：RxNorm ATC | 上限 US-only 2,521 个成分的一部分（推断 1,000–2,000） | 中：需 UMLS 账号 | **ATC 内容源自 WHOCC，第三方权利，再发布要确认** | 先问许可，再定 |
| P3 | ATC：WHOCC ATC/DDD 全量 | 理论上可把 43% 提到 80%+ | 低：需商务/书面授权 | 明确禁止未授权整表复制 | **不做**（除非拿到授权） |
| — | ATC：dm+d 派生 | **0**（原方案假设不成立） | — | OGL | **排除**：见 §4.2，dm+d 10.2.0/10.3.0 主包与 bonus 均无 ATC 字段 |
| — | CN：NMPA 药品查询批量抓取 | 理论高 | **低**：412 WAF、无批量入口 | 无开放许可 | **不可做**（见 §3.2） |

---

## 1. 基线（全部【已验证】，只读 SQL）

```sql
-- data/drugs.db 用 sqlite3 只读打开：file:data/drugs.db?mode=ro
select count(*) from product;                    -- 409,485
select count(*) from substance;                  -- 13,288
select count(*) from name_key;                   -- 135,081
select count(*) from product_component;          -- 497,513

-- 各国有规格（strength_value 非空）的产品数
select p.country, count(distinct p.product_id) products,
       count(distinct case when pc.strength_value is not null then p.product_id end) with_strength
from product p left join product_component pc on pc.product_id=p.product_id
group by p.country order by products desc;
-- CN 146,347 / 141,117；US 110,179 / 96,648；GB 61,051 / 51,307；CA 43,847 / 43,776
-- ES 25,293 / 24,797；AU 11,890 / 7,022；MX 10,878 / 3,123  ← MX 28.7%
```

- **MX**：10,878 产品，3,123 有浓度（28.7%）；**7,634 个产品无浓度**，其中 **7,572 个有商品名（99.2%）** —— 缺口是浓度，不是商品名。
- **CN**：146,347 产品；`name_type='trade'` 覆盖 **18,287 个产品 / 4,866 个 name_key**；`inn` 覆盖 146,344 / 6,856。商品名键少是「官方表里大多没有商品名」，不是没抓。
- **ATC**：`substance` 5,751 / 13,288 有 ATC（43.3%）；长度分布：7 位 2,849、5 位 2,879、4 位 20、3 位 3。
- 本次新增的基线数字（原任务未给）：`name_variant` 146,369 行；`product_name` 568,602 行。

---

## 2. MX 规格（浓度）深度调研

### 2.1 缺口结构【已验证：`.tmp/data-depth/mx_gap_fast.out.txt`】

按 `(substance_id, form_base)` 给 MX 产品分组（2,992 组）：

| 组类型 | 组数 | 产品数 | 说明 |
|---|---|---|---|
| 整组无浓度 | 2,484 | 8,121（组件行） | 现有回填逻辑完全没碰到 |
| 部分有浓度 | 191 | 4,067（组件行），其中缺 2,344 | 组内浓度已被写成唯一值 |
| 全有浓度 | 317 | 1,438 | — |

缺口的剂型分布（组件行）：liquid 3,991、tablet 3,657、capsule 987、topical 756、injection 587、powder 240、suppository 131、inhalation 90。

**两个硬限制**：
1. **`mx-es-` 专属成分**：MX 2,007 个成分里 759 个没有映射到英文 INN（按设计保留，避免误配）；缺口组里 835 组的成分是 `mx-es-` 专属。这些产品即使有西语采购目录也难跨源对齐。
2. **同名多浓度**：项目现有回填规则是「同通用名 + 同剂型，浓度唯一才写」；多浓度的组一律留空。模拟中「严格规则」与「放宽到只看通用名」分开统计，见下。

### 2.2 已验证来源 A：datos.gob.mx 的 4 个 CC-BY-4.0 药品明细数据集（本次核心发现）

CKAN API：`https://datos.gob.mx/api/3/action/package_search?q=medicamentos` 共 **23 个数据集**，全部 `license_id=CC-BY-4.0`。逐个抽验 `datastore_search` 字段后，以下 4 个**含「通用名 + 剂型 + 浓度」或「CNIS 代码 + 含浓度的描述」**：

| 数据集（package id） | 机构 | 行数 | 关键字段 | 许可 |
|---|---|---|---|---|
| `adquisicion_medicamentos_demanda` | INPRFM（国家精神病学研究所） | **2,171** | `sus_activ`（成分）、`forma_farma`（剂型）、`cntcn`（浓度，如 `2mg`）、`prese`、`clave_ssa` | CC-BY-4.0 |
| `medicamentos_productos_farmaceuticos_adquiridos_hgmgg` | 墨西哥总医院 | **3,537** | `clave_cnis`、`descripcion`（长描述含浓度，如 `...equivalente a 20 mg...`）、`unidad` | CC-BY-4.0 |
| `entrada_medicamentos` | INER（国家呼吸病研究所） | **2,968** | `clave`、`descripcion`（如 `paracetamol 500 mg.`）、`precio_unitario` | CC-BY-4.0 |
| `adquisicion_insumos_salud` | SEMAR（海军部） | **626** | `clave`（CNIS 键）、`descripcion_insumo`（全描述含浓度，如 `ATORVASTATINA ... 20 MG ...`） | CC-BY-4.0 |

+ 已用的 ISSSTE 目录（`catalogo_institucional_insumos`，1,590 行）与 PROFECO 价格（`programa_quien_es_quien_precios_2024/2025/2026`，Medicamentos 目录）也同属 CC-BY-4.0。**这 4 个新数据集与现有两个来源同许可、同结构，属于「顺着现有 ETL 加一个 fetch 函数」的成本。**

**模拟回填实测**（`mx_ccby_sim.py` / `mx_sim2.py`，脚本把 4 个数据集解析成 `(西语通用名, 剂型) → 浓度集合` 字典，再对 MX 缺口产品匹配）：

```text
字典：1,082 个 (generic, form) 组 / 875 个 generic 组
MX 缺口 distinct products：7,634（其中 5,485 个有西语通用名）
严格（通用名前 2 词 + 同剂型，浓度唯一）：+763
放宽（只看通用名，浓度唯一）：            +852
合计：+1,615 / 7,634 = 21.2% 缺口
覆盖率：28.7% → 43.6%（3,123+1,615 = 4,738 / 10,878）
```

> 这是**模拟，不是入库结果**：字典来自 4 个数据集的 9,302 行原始明细。回填规则与现有 `ingest_mx.py` 一致（唯一值才写），但抽样里的 `IBUPROFENO solución 10 mg`、`ACIDO ACETILSALICILICO granulado 500 mg` 等需要人工复核（描述里可能是「100 mg/5 mL」被截成 10 mg）。**抽查 20 条样本中方向正确的约 85%【推断】**，上线前必须人工抽 50 条。

**能再多拿的（同一许可，未逐一抽验）**：23 个数据集里还有 `listado_medicamento_registrado_almacen...`（INGER，272 行，直接有 `conc` 列）、`recetas...`（ISSSTE 6 份）、`existencias_mensuales...`（INGER 2,170 行，只有数量无浓度）等。前两个可以并进字典，预计再 +100～300 个产品【推断】。

### 2.3 其它 MX 候选与抽验状态

| 来源 | 抽验结果 | 证据 | 判断 |
|---|---|---|---|
| **DOF：Cuadro Básico y Catálogo de Insumos del Sector Salud（CBCISS）** | 未找到可直接机器下载的现行全量文件；DOF 是逐条公告页；`diariooficial.gob.mx` HEAD 200 | 搜索索引显示国家层面目录以「Acuerdo + 附件」形式发布 | 能补但需人工/PDF 解析；**无开放许可**，属政府公开文件 |
| **州级 CBCISS（如 Edomex《CUADRO BÁSICO DE MEDICAMENTOS 2025》）** | 本次从本机网络 **HEAD 超时（10 s）**，未验证 | `legislacion.edomex.gob.mx/.../mar051e.pdf` | 同上；逐州解析成本高，只作补充 |
| **IMSS / Birmex「Compra Consolidada」附件** | `reposipot.imss.gob.mx` 根路径 403，但搜索索引显示合同/招标 PDF 有「CLAVE + 描述 + 价格」 | 例：`reposipot.imss.gob.mx/contratos/.../012NEF001I01825-032-00_Censurado.pdf` | 有货号+描述，**无开放许可**；可作为核价/核对源 |
| **ComprasMX** | HEAD 200（HTML） | `comprasmx.buengobierno.gob.mx` | 无已知公开 API；暂不投入 |
| **datos.gob.mx（本次 A 类）** | **已验证字段 + CC-BY-4.0** | 见 §2.2 | **首选** |
| 商业库（DEF / Vademécum / Farmacias 在线） | 未抽验 | — | 版权明确，排除 |
| 医院「Ficha Técnica」PDF（本地 `data/raw/mx/*.pdf` 250 份） | 本地已有，均为**疫苗/生物制品**说明书 | 文件名 `FT_*.pdf`、`*_Ficha_T_cnica_*.pdf` | 不是本次缺口主力，先不碰 |

### 2.4 ETL 步骤（照现有架构落地）

1. 新增 `etl/fetch_mx_catalogos_ccby.py`：对 4 个 package 各发 1 次 `package_show` + 至多 2 次 `datastore_search`（行数均 < 4k，1 页拉完），落 `data/raw/mx/ccby/*.csv`；记录 `retrieved_at`、`package_id`、`resource_id`、`license=CC-BY-4.0`。
2. 新增 `etl/extract_mx_ccby.py`：把四种字段形态归一为 `(clave_cnis, generic_raw, form_raw, strength_value, strength_unit, per_volume)`；`descripcion` 用现有 `ingest_mx.py` 里的西语浓度正则（同 ISSSTE 解析器复用），`cntcn` 直接取值。
3. 与现有回填逻辑合并：优先「同通用名+同剂型唯一值」，其次「固体制剂只看通用名唯一值」（与 README §墨西哥 现有 2,837/215 口径一致），冲突值一律不写。
4. 每条回填写 `product.note` 或 `corroboration(source_type='regulator'?)` —— 建议在 `source` 表新增 `mx_ccby_*` 条目（4 个），`corroboration.url` 指向 CKAN 资源页，满足「每条剂量可追溯」。
5. 行数/schema 漂移告警：4 个数据集的 `total` 若环比变化 > 50%，打警告（单医院采购是月度更新，波动大）。
6. 验收：抽 50 个新产品人工核对，然后跑 `site/build.py` 前先看覆盖率页（本报告不跑）。
7. **署名**：footer/About 加 "Datos abiertos de México (SECRETARÍA DE MARINA, HGMGG, INPRFM, INER, ISSSTE, PROFECO) — CC BY 4.0"。

### 2.5 许可与风险

- **A 类（4 个 CKAN 数据集 + ISSSTE + PROFECO）：CC-BY-4.0，可公开再发布，需署名 + 注明修改。零许可风险。**
- DOF/州表/IMSS 附件：无开放许可，属「政府公开信息」；若要用，只可提取事实（浓度、剂型）、署名、链原文，不整表镜像。风险与 CN 省级表面同级。
- 数据语义风险：采购明细是**某家医院的单次采购**，不是「墨西哥全量浓度表」；浓度可能是范围/复方/含量体积型。**必须保留「唯一值才写」规则**，否则会把 A 药浓度写到 B 药上。
- 建议：报告里明确「MX 覆盖率 28.7% → 约 43.6% 为可达成上限估算，非承诺值」。

---

## 3. CN 商品名深度调研

### 3.1 基线【已验证】

- DB：146,347 产品；`trade` 名 18,287 产品 / **4,866 个键**；`inn` 名 146,344 / 6,856。
- NHSA 公开表快照 `data/raw/nhsa/nhsa_codes_20240105.csv`（本项目已在用）：**234,370 行**，`商品名称` 非空 **17,799 = 7.6%**（`reports/nhsa_full_stats.txt`；本次复算脚本 `.tmp/data-depth/` 未改文件，引用既有统计）。`批准文号` 唯一 108,980，`药品代码` 唯一 23,778。
- 2025-04-04 快照（既有 `reports/nhsa_diff_2024_2025.txt`）：**252,097 行**（+7.6%），`批准文号` +2,039，`注册名称` +162，**商品名只 +435**。

**结论：CN 商品名覆盖率低不是「抓取失败」，是官方表里 92% 的行商品名栏就是 `/`/空。** 任何「批量拿商品名」的方案都在跟这 92% 对抗。

### 3.2 渠道逐项（抽验证据）

| 渠道 | 能否批量 | 本次抽验 | 许可边界 | 结论 |
|---|---|---|---|---|
| **NHSA 医保药品分类与代码数据库**（现行已用） | 能（附件下载） | `code.nhsa.gov.cn/file/attachment/downloadFileByUser.html?path=…&fileName=…`（2025-04-04、2026-02-27 两个维护版本）GET 返回 **200 + `%PDF`**；首页 HEAD 200 | 未标注开放许可；政府公开信息 | **可做**：刷新快照（新增约 7.6% 行、+435 商品名）；**不能解决商品名缺口** |
| **NMPA 国家药监局药品查询**（国产药品库有「商品名」列） | **否** | `https://www.nmpa.gov.cn/` 与 `/datasearch/search-result.html` 从本机 **HEAD 均 412 Precondition Failed**（WAF 拦截非浏览器 UA）；无批量导出入口 | **无开放许可**、无可接受抓取声明 | **不可做**（批量）；单条人工核对可以 |
| **省级医保支付范围明细表**（天津样本） | 能（逐省 PDF/Excel） | `tjmpc.cn` 2021 年第一期 PDF：HEAD 200 / GET **6,576,880 B（6.58 MB）** / **674 页**；表头实测含 **序号·通用名·商品名·剂型·规格·规格描述·包装量·单位·批准文号·药品本位码·生产企业·最高医保支付标准·…**；每页约 27.6 行，合计约 1.8 万行；**商品名多为 `/`**（如「八味芪龙颗粒」= `/`，「铝碳酸镁咀嚼片」= `泰尔赛克`） | 政府公开信息，无开放许可 → 只存事实字段 + 出处链接，不整表镜像 | **可做（有限）**：按 `批准文号` join 回填已知商品名；预计 +1k～3k 个键【推断，取决于覆盖省份数与年份】 |
| 集采中选结果表 | 能 | 既有项目结论：只有通用名/规格/企业/价格，无商品名 | — | 不做（对商品名无用） |
| 药企官网/说明书 | 否（人工） | 既有结论：原研 200–400 个商品名 | 事实+链原文风险可控 | 仅作高价值补录 |
| 商业库（药智/摩熵/丁香园） | 能（付费） | 未抽验 | 商业授权 | 需要时才采购 |
| 第三方爬取 NMPA 的 GitHub 数据（如 `Billy-FIN/NMPA_Scraper`） | 能 | 仅搜索结果（未下载） | **数据再分发许可不明**，来源链条不清 | **不采用**；只作为「技术上可抓」的旁证 |

### 3.3 明确回答：可做 / 不可做 / 需要什么

**可做**
1. 刷新 NHSA 快照（脚本级小改：现有 `extract_nhsa_pdf.py` 走 PDF 解析；下载端点已验证可用）。收益：数据新鲜度 +7.6% 行，商品名 +435。
2. 逐省策展「医保支付范围明细表 / 挂网目录」：优先天津（已验证 674 页结构）、北京、上海、江苏、广东，目标 5–8 省 × 近 2 期；按 `批准文号 + 企业 + 规格` 对齐 DB，把商品名写成 `trade` 名。**产地、许可风险可控（只存事实+链原文），与现有 NHSA 数据同级。**
3. 页面上把 CN 口径写死：「商品名以官方目录/说明书为准，官方表多数行为空」——避免用户以为「没有商品名 = 没收录」。

**不可做**
1. NMPA 全量批量抓取（412 WAF + 无许可 + 破坏性风险）。
2. 指望任何「公开官方批量文件」一次性补齐 CN 商品名——**不存在**（NHSA 7.6% 是天花板证据）。
3. 整表转载省级表/医保表（再发布许可不明）。

**需要什么（若要突破）**
- 商业库采购授权（药智/摩熵/丁香园），或 NMPA 数据共享的书面授权/合作；
- 若走人工核对路线：每个原研品牌 1 条「说明书 URL + 商品名 + 规格」的策展预算（约 200–400 条）。

### 3.4 提升估算

- 天花板公式：`可回填商品名数 ≈ 省级表覆盖的 批准文号 数 × 该表商品名非空率`。天津样本非空率目测 10–20%【推断，未逐行统计】 → 每省每期约 +1k～3k 行，去重后 +1k～3k 个键【推断】。
- 这会把 4,866 键提升到约 6k～8k（仍覆盖不到 10 万+ 批准文号的多数）——**符合项目「CN 商品名可选」的既定设计**，不建议为此投入重资源。

---

## 4. ATC 覆盖深度调研

### 4.1 缺口按市场分解【已验证：`.tmp/data-depth/atc_probe.out.txt`】

7,537 个缺 ATC 的成分，按「出现在哪些市场」：

| 只出现在 | 成分数 | 可用来源 |
|---|---|---|
| **US** | **2,521** | RxNorm（ATC，需许可确认） |
| **GB** | **1,730** | ❌ 本次证明 dm+d 无 ATC；只能 WHOCC/商业库 |
| **AU** | **1,056** | PBS items.json 实测**无 ATC 字段**（0 命中）；TGA/ARTG 无批量 |
| **MX** | **771**（其中 759 是 `mx-es-` 未映射西语名） | 先解决 INN 映射，再谈 ATC |
| **CA** | **478** | DPD `therapeuticclass` 只到 ATC-4，且已用；到 5/7 位缺口仍在 |
| **无产品** | **355** | 不重要（孤儿成分） |
| **ES** | 161 | CIMA 可再抽（ATC-5 树已有本地 1,808 份 JSON） |
| 组合（GB+US 72、CA+US 60、AU+GB 54…） | 其余 | 同上 |

> 注：因 ATC 存在 `substance` 上，任一市场的 ATC 命中会自动惠及所有共享该成分的市场；上面是「不共享」的成分数，也就是真正卡住的天花板。

### 4.2 重要纠正：dm+d 不提供 ATC【已验证】

- 下载 TRUD item 25（dm+d supplementary，现名 **dm+d bonus**）最新 **Release 10.3.0（2026-10-26）**：0.89 MB，sha256 与 TRUD 元数据一致；包内只有 `week442026-r2_3-BNF.zip`、`HISTORIC_CODES/`、`VTM_INGREDIENTS/`、`TRADE_FAMILY/`。
- 主包 dm+d 10.2.0（16.1 MB）：`f_amp/f_ampp/f_ingredient/f_lookup/f_vmp/f_vmpp/f_vtm`，无 ATC 字段。
- 包内 `<SUPPCD>` 是**旧编码/SNOMED 系**（`f_amp2` 里 167,533 处），不是 ATC。全文检索 `<ATC` / `ATCCD` / `ATC code` 均 0 命中。
- **结论：文档 §6.2/§6.4「dm+d supplementary 把 ATC 挂到产品上」这一假设在 2026-10 的数据上不成立。GB-only 的 1,730 个成分无法从 dm+d 得到 ATC。** 若后续要靠 dm+d 路线，需要向 NHS BSA 确认 ATC 映射是否有单独分发（目前公开包里没有）。

### 4.3 CIMA（AEMPS，西班牙）【已验证本地数据，可做】

- 本地 `data/raw/cima/atc/*.json` 共 **1,808 份**，每份是 `{nregistro, atcs:[{codigo, nombre, nivel}]}`，含 3/4/5 级 ATC 与西语名称（例：`H01C / H01CC / H01CC01 Ganirelix`）。
- 用途：① 补 `substance.atc_name`（当前只有 1,800 个有名字）；② 若 CIMA 全量 nregistro（约 1.5 万）都拉，可把西语 ATC 名称体系建全，但仍只映射**西班牙上市**成分——共享成分的 code 已经进库，边际主要在 `atc_name`。
- 许可：AEMPS CIMA 数据可重用（Ley 37/2007 / 署名），项目已在用同一来源，风险低【推断：具体条款未逐字核】。

### 4.4 RxNorm【未下载，仅凭既有项目文档 + 公开常识，标推断】

- RxNorm 的 ATC 来自 RXNSAT（SAB=ATC）；**完整 release 需免费 UMLS 账号**，项目尚未接入（P1 用 openFDA 替代了 RxNorm）。
- **关键风险**：RxNorm 里 ATC 是 WHOCC 的第三方内容，NLM 对再分发有约束（SRL/suppress 规则），公开站再发布前需法务确认；「只存 ATC 代码→成分的映射、不存 DDD」风险显著低于整表复制，但仍是**待确认项**。
- 量级：US-only 2,521 个成分中，RxNorm 能覆盖的以「美国上市小分子」为主，估 **1,000–2,000**【推断】；生物制品/复方/诊断用药多半没有 ATC。

### 4.5 WHOCC ATC/DDD 索引【不做】

- WHOCC 的 ATC/DDD 索引是权威全量（约 6,000 个 5 级码），但**版权在 WHOCC，整表复制/再发布需书面授权**，商用需付费许可；官网页明确限制再分发。
- 若要「一次到位」把 43% 提到 80%+，这是唯一路径，但要走授权谈判；**不建议本阶段投入**。

### 4.6 Wikidata P267（ATC code）【已验证：一次 SPARQL，`.tmp/data-depth/wikidata_p267.json`】

```text
query.wikidata.org SPARQL: ?drug wdt:P267 ?atc（label 服务 en/es/zh/fr/de）
返回 4,455 行 / 4,371 个不同 ATC 码：7 位 3,997、5 位 189、4 位 81、3 位 94
与 DB 13,288 个成分做精确名称匹配（大小写/空白归一）：
  全部可匹配 1,893；其中「缺 ATC」的 7,537 个里可补 341（ATC 唯一 301）= 缺口的 4.5%
样例：benzonatate/R05DB01、carisoprodol/M03BA02、sulconazole/D01AC09、dalfampridine/N07XX07
```

- 许可：Wikidata 数据 **CC0**，可自由再发布。
- 限制：P267 只有 4.4k 个条目，且多为小分子；**中文/西语名映射不要用 label 硬匹配**，本次只用英文 INN 精确匹配，避免误配。
- 建议：作为 **P0 级小任务**先做（一次请求就能拿到），把 +341 落库，同时留 `source=wikidata:P267` 可追溯。

### 4.7 其它 ATC 候选（未抽验，标注推断）

| 来源 | 许可 | 备注 |
|---|---|---|
| DrugCentral（UNM） | CC BY-SA 4.0【推断】 | 含 ATC 字段；share-alike 会影响混合库的许可声明 |
| ChEMBL（EMBL-EBI） | CC BY-SA 4.0 | 有 `atc_classifications`，分子级；需比对 INN/结构 |
| 挪威 FEST（Legemiddelverket） | NLOD（类 CC-BY） | 挪威语名 + ATC；映射到英文 INN 需词典 |
| 各国药监开放数据（瑞典/芬兰/丹麦等） | 各自开放许可 | 适合「只做 ATC 事实映射」的补漏，工作量大 |

### 4.8 组合方案与提升估算

| 方案 | 新增成分 | 覆盖率（成分级） | 许可 |
|---|---|---|---|
| 现状 | — | 5,751（43.3%） | — |
| + Wikidata P267（本次可做） | **+341** | **≈6,092（45.8%）** | CC0 ✅ |
| + CIMA 名称补全 | +少量 ATC 码，主要是 `atc_name` | ≈46% | AEMPS 署名 ✅ |
| + RxNorm（若许可通过） | +1,000～2,000【推断】 | ≈53%～61%【推断】 | 待确认 ⚠️ |
| + WHOCC 授权全量 | 可到 80%+ | — | 需谈判 💰 |

> 注意：覆盖率以「成分」计，不等同「产品行有 ATC」。产品行的 ATC 覆盖率会更低（因为一个成分下挂多个产品，共享同一 ATC）。

### 4.9 ETL 步骤（按优先级）

1. **Wikidata P267（1–2 小时）**：`etl/fetch_wikidata_atc.py` 用一次 SPARQL 拉 `(ATC, label)` → 落 `data/raw/wikidata/atc.json`；`etl/ingest_atc_wikidata.py` 按英文 INN 精确匹配写 `substance.atc`（只补空、不覆盖），写 `source_id='wikidata_p267'`，记录 QID。
2. **CIMA 名称（半天）**：扩展现有 CIMA 抓取，把 `atc` JSON 全量拉齐 → 建 `atc_code→atc_name` 字典，仅更新 `atc_name`（不覆盖已有非空值）。
3. **RxNorm（1 周，前置许可）**：先向 NLM/WHOCC 确认 ATC 再发布边界；可行则 RxNorm full release → RXNSAT `ATN='ATC'` → 按 RxCUI/INN 映射，只写代码+名称，不写 DDD。
4. **WHOCC（商务）**：拿到授权再谈整表。
5. **CN 侧不动**：CN 的 3,103 个成分里 3,102 已有 ATC（从 `药品代码` 首位 ATC 段提取），是全库覆盖最好的部分；不要为 CN 再做 ATC。

---

## 5. 优先级与下一步（给 Lead 的决策建议）

**P0（本周可做，许可干净、有实测收益）**
1. MX：新增 4 个 CC-BY-4.0 数据集的 fetch + extract + 回填合并（预期 28.7%→约 40%+，先人工抽 50 条校准）；同批做 ISSSTE/PROFECO 已有逻辑复用。
2. ATC：接 Wikidata P267（+341 成分，零许可风险）。
3. 页面/README 口径：MX「浓度来自采购/价格公开数据，空是数据事实」；CN「官方表多数行无商品名」；ATC「不含 WHOCC 授权内容」——三条都应在 About 页写清楚。

**P1（1–2 周）**
4. CN：刷 NHSA 新快照 + 5–8 省医保支付明细表按批准文号回填（先天津 1 期跑通，估算收益后再扩省）。
5. ATC：CIMA `atc_name` 补全。

**P2（需决策/谈判）**
6. RxNorm ATC 许可确认（决定是否把 US-only 2,521 的覆盖做上去）。
7. WHOCC 授权谈判（一次性解决 GB/AU/CA 的硬缺口，但成本最高）。
8. MX 州级 CBCISS（Edomex 等）与 IMSS 合同 PDF 的人工策展——只在 A 类跑完仍有明显缺口时才做。

**明确不做**
- NMPA 全量抓取（412 + 无许可）；
- dm+d 派生 ATC（已验证不存在）；
- 整表转载省级医保表 / 商业库内容。

---

## 6. 许可证与合规摘要

| 数据 | 许可 | 再发布 | 备注 |
|---|---|---|---|
| datos.gob.mx（4 个新数据集 + ISSSTE + PROFECO） | **CC-BY-4.0**（CKAN `license_id` 实测） | ✅ 可，需署名 + 修改声明 | 本次唯一「完全干净」的新增 |
| NHSA 医保药品分类与代码库 | 无开放许可 | ⚠️ 政府公开信息，事实字段+链接 | 现有已用，边际风险不变 |
| NMPA | 无 | ❌ | WAF 412 |
| 省级医保支付明细表（天津等） | 无开放许可 | ⚠️ 只存事实 + 原链，不镜像 | |
| dm+d（含 bonus） | OGL | ✅ 但**无 ATC 内容** | |
| CIMA | AEMPS 重用（署名） | ✅（推断：条款未逐字核） | |
| Wikidata | CC0 | ✅ | |
| RxNorm | UMLS 许可；ATC 为 WHOCC 第三方内容 | ⚠️ 待确认 | |
| WHOCC ATC/DDD | 版权，需授权 | ❌ 默认不可 | |

---

## 7. 附录：证据文件与可复跑命令

全部在 `.tmp/data-depth/`（本次写范围）：

| 文件 | 内容 |
|---|---|
| `probe_db.py` / `probe_db2.out.txt` | 表结构 + 各国/来源/强度/ATC 基线 SQL 输出 |
| `mx_gap_fast.py` / `.out.txt` | MX 缺口按 (substance, form) 分解 |
| `probe_ckan_mx.py` / `.out.txt` | datos.gob.mx CKAN 检索（23 个 medicamentos 数据集、license_id、ISSSTE 资源列） |
| `probe_fields.py` / `.out.txt` | 4 个数据集字段与样例记录；CN/其它候选 HEAD 结果 |
| `probe_candidates.py` / `.out.txt` | NHSA 附件下载端点（200 %PDF）、CKAN 更多检索、站点可达性 |
| `mx_ccby_sim.py` / `.out.txt`、`mx_sim2.py` / `.out.txt`、`mx_ccby_datasets.json` | MX 回填模拟（+1,615 / 43.6%）与原始数据集缓存 |
| `probe_dmd_supp.py` / `.out.txt`、`dmd_supp.zip`、`supp/` | dm+d bonus 10.3.0 下载与内容确认（无 ATC） |
| `atc_probe.py` / `.out.txt` | ATC 缺口按市场分解、dm+d 无 ATC 确认 |
| `probe_wikidata_atc.py` / `.out.txt`、`wikidata_p267.json` | Wikidata P267 SPARQL 结果与匹配统计（+341） |
| `probe_tj_pdf3.py` / `.out.txt`、`tj_medical_insurance_2021.pdf` | 天津医保明细表 674 页、6.58 MB、表头与 1,105 个批准文号抽样结果 |
| `probe_atc_raw.py` / `.out.txt` | PBS items.json 无 ATC 字段（0 命中）、CIMA ATC JSON 样例 |

复跑（只读，不写库）：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\data-depth\probe_db.py
& $py .tmp\data-depth\mx_gap_fast.py
& $py .tmp\data-depth\mx_ccby_sim.py      # 联网拉 CKAN；再跑 mx_sim2.py 直接读缓存
& $py .tmp\data-depth\probe_wikidata_atc.py
& $py .tmp\data-depth\probe_dmd_supp.py
```

**关键 SQL（可直接粘贴）：**

```sql
-- MX 缺口 distinct 产品数
select count(distinct p.product_id)
from product p join product_component pc on pc.product_id=p.product_id
where p.country='MX' and pc.strength_value is null;              -- 7,634

-- 各国 ATC 可达成分
select p.country, count(distinct v.substance_id) subs,
       count(distinct case when s.atc is not null and s.atc<>'' then s.substance_id end) subs_atc
from product p
join product_component pc on pc.product_id=p.product_id
join variant v on v.variant_id=pc.variant_id
join substance s on s.substance_id=v.substance_id
group by p.country;
-- US 4,441/1,638；GB 3,747/1,751；CN 3,103/3,102；CA 3,045/2,415；AU 2,519/1,279；ES 2,093/1,851；MX 2,007/1,119

-- CN 商品名键
select count(distinct pn.key_id), count(distinct pn.product_id)
from product p join product_name pn on pn.product_id=p.product_id
where p.country='CN' and pn.name_type='trade';                   -- 4,866 键 / 18,287 产品

-- ATC 长度分布
select length(atc) l, count(*) from substance
where atc is not null and atc<>'' group by l;                    -- 7:2849 5:2879 4:20 3:3
```

**报告边界**：本文件不构成医疗建议；所有回填量均为「模拟/估算」，真实入库须走 ETL + 人工抽验 + 覆盖率页复核。
