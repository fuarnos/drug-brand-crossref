# 厂家页数据准备（task-47）

> 日期：2026-10-28 ｜ 数据库：`data/drugs.db`（**只读**，本轮未写入）｜ 未跑 git / 发布 / `site/build.py`
> 产物：`data/maker_candidates.csv`（15,225 行）、`data/maker_blacklist.json`（12 条占位）、`etl/build_maker_candidates.py`（可重跑）、`.tmp/maker-data/stats.json`
> 目标：为 v0.5.4「厂家页」提供可构建清单（厂家 → 页数/URL/slug/产品数/国家/品牌/黑名单）。

---

## 1. 结论

| 指标 | 数值 |
|---|---:|
| 产品总数 | 409,587（其中 mah 为空 4,760 = 1.2%，主要是 AU TGA CMI 4,730 条无厂家字段） |
| 原始 distinct mah | **17,724** |
| **原始 mah 中 ≥2 产品的厂家** | **12,360**（= task 给的目标口径） |
| 规范化后厂家（大小写/标点/空格合并） | **15,225**（合并掉 2,499 个重复写法） |
| 占位/黑名单厂家 | **12 个**（覆盖 7,539 个产品） |
| 仅 1 个产品的厂家 | 4,238（不建页） |
| **建议建页厂家（≥2 产品、非占位、规范化后）** | **10,975** |
| 其中跨市场厂家（≥2 市场） | 521 |
| 非拉丁名厂家（中文等，用短哈希 slug） | 3,503 |
| slug 冲突（全局唯一后） | **0** |

- **页数取决于阈值**（规范化后）：`≥2 → 10,975`、`≥3 → 8,994`、`≥5 → 6,997`、`≥10 → 4,889`、`≥50 → 1,638`。
- 与 task 给的 12,360 的差异来自**规范化合并**：同一厂家的大小写/标点变体（如 `PFIZER CANADA ULC` 与 `Pfizer Canada ULC`）合并后，两个「≥2 产品」的键并成 1 页，所以 12,360（原始）→ 10,975（规范化）。
- **建议 v0.5.4 首版用 ≥2 产品（10,975 页）**：其中真正「生产厂家」与「分装/代理（如 Bryant Ranch Prepack、A-S Medication Solutions）」混在一起——按 `product.mah` 语义它们都是「上市许可持有人/分装商」，页面统一叫「上市许可持有人（厂家）」并在 About 说明；若希望控制页数，可先上 `≥5`（6,997 页）。

---

## 2. 数据现状

### 2.1 各国家：产品数 / 空 mah / distinct mah

| 市场 | 产品数 | mah 空 | distinct mah（原始） |
|---|---:|---:|---:|
| CN | 146,347 | 0 | 4,242 |
| US | 110,179 | 0 | 7,666 |
| GB | 61,051 | 0 | 988 |
| CA | 43,847 | 0 | 2,456 |
| ES | 25,395 | 0 | 1,184 |
| AU | 11,890 | **4,730** | 195 |
| MX | 10,878 | 30 | 1,136 |
| **合计** | **409,587** | **4,760** | **17,724** |

> AU 的 TGA CMI 目录不带 MAH 字段（4,730 条）；这些产品**没有厂家页**是数据事实，页面应显示「厂家未知 / 来源未提供」而不是空白。

### 2.2 厂家产品数分布

- 1 个产品：5,364（原始）→ 规范化后 4,238；
- 2–4 个产品：约 3k；
- ≥10 个产品：4,889（规范化后）；
- 头部：`Hahnemann Laboratories, INC.` 4,851、`Bryant Ranch Prepack` 4,328、`A-S Medication Solutions` 2,807、`A A H Pharmaceuticals Ltd` 2,622、`DE Pharmaceuticals` 2,349、`Waymade Healthcare Plc` 2,257、`Alliance Healthcare (Distribution) Ltd` 2,237、`Boiron` 2,040、`Mawdsley-Brooks & Company Ltd` 1,779、`Proficient Rx LP` 1,737、`辰欣药业股份有限公司` 1,709（slug 短哈希 `maker-d2a83a38cc`）……

### 2.3 占位 / 黑名单（`data/maker_blacklist.json`）

| 厂家（规范化） | 产品数 | 规则 |
|---|---:|---|
| Special Order | 7,226 | exact_special order |
| Drug Tariff Special Order | 246 | exact_drug tariff special order |
| Part VIIID Drug Tariff Special Order | 52 | exact_part viiid drug tariff special order |
| S+ | 4 | exact_s+ |
| 70541 | 3 | digits_only |
| c / C | 2 / 1 | too_short |
| 其余 6 条（纯符号/纯数字/≤2 字符） | 0–1 | 各类 |

> `Special Order` 家族 = 英国 dm+d 里「药品未备货时的代订占位」，**不是真实生产厂家**，必须跳过；7,539 个产品（占全部产品 1.8%）不应产生厂家页。黑名单 JSON 同时保留每个占位词的 `raw_forms`，供 build.py 按原始字符串再兜底匹配。

---

## 3. 产物格式

### 3.1 `data/maker_candidates.csv`（15,225 行，UTF-8 BOM）

| 列 | 说明 |
|---|---|
| `maker_name` | 显示名（同 key 下出现最多的原始写法，保留原大小写/标点） |
| `maker_key` | 规范化 key（NFKC → casefold → 去标点 → 空白折叠） |
| `slug` | URL slug（见 §3.3） |
| `n_products` | 产品数（distinct product_id） |
| `n_markets` / `markets` | 市场数 / 各市场产品数（`US:123;CA:45` 形式，最多 10 个） |
| `n_brands` | 该厂家下 distinct trade 名键数 |
| `sample_brands` | 前 5 个品牌名键（按出现次数） |
| `is_placeholder` | 1 = 黑名单/占位（不建页） |
| `placeholder_rule` | 命中规则（exact_…/digits_only/too_short/…） |
| `has_page` | 1 = 建议建页（`n_products>=2` 且非占位），共 **10,975** |

CSV 排序：先 `has_page=1`（按产品数降序），再 `too_few`（1 产品），最后占位。**build.py 只需筛 `has_page=1`。**

### 3.2 `data/maker_blacklist.json`

```json
{
  "min_products_for_page": 2,
  "rules": {"exact": [...], "contains": ["special order"], "heuristics": [...]},
  "entries": [{"maker": "Special Order", "maker_key": "special order",
               "n_products": 7226, "rule": "exact_special order",
               "raw_forms": ["Special Order"]}, ...]
}
```

### 3.3 slug 规则

1. **拉丁名**：NFKD 去重音 → 小写 → 非字母数字→`-` → 折叠；超长截断 48 字符。
   例：`A A H Pharmaceuticals Ltd → a-a-h-pharmaceuticals-ltd`；`Mawdsley-Brooks & Company Ltd → mawdsley-brooks-company-ltd`。
2. **非拉丁名（中文等）**：环境没有拼音库（pypinyin/unidecode 均未安装），用稳定短哈希 `maker-<sha1(key)[:10]>`，例如 `辰欣药业股份有限公司 → maker-d2a83a38cc`。
3. **全局唯一**：冲突/截断时追加 `-<sha1[:6]>`；本次冲突 **0**（唯一性校验通过）。
4. **不依赖 DB 自增/顺序**——同一厂家在任何一次重建中 slug 稳定（哈希基于规范化 key）。

> 若后续装了 pypinyin，可把中文厂家的 slug 升级为 `chen-xin-yao-ye` 形式；**升级会改变 URL**，需要 301/旧 slug 保留，建议 v0.5.4 先用短哈希、v0.6 再换可读 slug。

---

## 4. 厂家页字段建议（给 build.py）

| 区块 | 内容 | 数据来源 |
|---|---|---|
| 标题 | 厂家显示名 + 「厂家/上市许可持有人」 | `maker_name` |
| 概览 | 产品数、国家数、品牌数 | `n_products/n_markets/n_brands` |
| 国家分面 | 每国产品数（可点筛选） | `markets` 拆分 |
| 产品列表 | 品牌名 / 通用名或成分集合 / 国家 / 剂型 / 规格 / 包装 / 批准文号或来源链接 | `product_name`(trade) + `product` + `product_component` + `variant` + `substance` |
| 品牌聚合 | 同品牌不同规格折叠 | `name_key` |
| 来源与许可 | 每个产品链回 `product.source_url`（CIMA/NHSA/NDC/dm+d/DPD/PBS/TGA），页脚按国家来源署名 | `source` 表 |
| 互链 | 厂家 ↔ 成分页 / 品牌页（name_key）/ 同成分其它厂家 | 索引已有字段 |
| 空厂家 | 「厂家未知（来源未提供 mah）」 | `mah IS NULL` 的 4,760 产品不建页 |
| 三语 | 标题/说明 en/zh/es（厂家名不翻译） | i18n key |

**URL**：`/maker/<slug>.html`（静态生成，与 drug/name/combo 页同级）；跨市场厂家一页展示全部国家产品。
**页数控制**：10,975 页会显著增加构建文件数（当前 ~30,246 HTML → 约 41k），首件构建时间与 Pages 体积需评估；可先 `≥5`（6,997 页）或 `≥2` 但只对「跨市场 + 产品数 top N」建页，其余厂家在产品行内显示文本、不建页。

---

## 5. 风险与注意事项

1. **语义**：`product.mah` 是「上市许可持有人 / 分装商 / 代订方」，不完全是生产工厂。页面用「厂家/上市许可持有人」双标签，避免用户误以为都是生产商；占位（Special Order）已排除。
2. **规范化合并可能过度**：本轮只合并大小写/标点/空格差异（2,499 个原始写法的变体），不合并不同法律实体（Teva UK 与 Teva Canada 仍分开）；但如 `ABC Ltd` 与 `ABC, Ltd.` 属同一家的正确合并，抽查 20 条合并组未发现误并。
3. **中文厂家 slug 不可读**（3,503 个短哈希）——SEO 与用户可读性弱，建议后续装 pypinyin 升级并保留旧 URL 301。
4. **AU 4,730 条无 mah**：厂家页缺失是源限制，页面用「厂家未知」兜底，不要伪造。
5. **页数膨胀**：10,975 厂家页 + 现有 3 万页 → 构建/索引/Pages 体积需评估；建议先按 ≥5 或 top-N 试点（见 §4）。
6. **同名不同实体**：不同国家的同名厂家（如 "Sandoz" 各地法人）在 `mah` 里字符串不同，本清单按字符串区分；若需「集团合并」是另一层人工映射，不在本轮。

---

## 6. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/build_maker_candidates.py     # 只读 DB；重写 data/maker_candidates.csv + data/maker_blacklist.json + .tmp/maker-data/stats.json
```

证据：`.tmp/maker-data/stats.json`（全部统计）、`.tmp/maker-data/probe*.py/.out.txt`（DB 探查）、`.tmp/maker-data/build*.out.txt`（构建日志）。

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 git / 发布 / `site/build.py`。_
