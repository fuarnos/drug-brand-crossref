# 数据字典（派生层，v0.9.2）

> 本文件对应站点根 `datapackage.json` / `dataset.jsonld` / `checksums.txt`。
> **对外只发派生层**：聚合覆盖、市场摘要、名称层摘要、成分清单；不整包分发受限来源原始记录。
> 许可与来源分级见 `docs/数据溯源与许可.md`、`docs/许可清单.md`。

## 1. 资源一览

| 资源 | 路径 | 粒度 | 行数（构建期） | 说明 |
|---|---|---|---|---|
| coverage | `data/exports/coverage.csv` | 国家/地区 | 10 | 产品/规格/在售计数与同步日期 |
| market-summary | `data/exports/market-summary.csv` | 国家/地区 | 10 | 产品、成分、name_key 数 |
| name-summary | `data/exports/name-summary.csv` | 国家 × name_type | 16 | 名称层汇总；不导出逐条名称 |
| substances | `data/exports/substances.csv` | substance | 12,649 | INN 标识、英文/中文名、ATC |

`datapackage.json` 给出每个资源的字段、类型、bytes、`sha256`、行数；`checksums.txt` 是独立校验文件。

## 2. 字段

### coverage

| 字段 | 类型 | 含义 |
|---|---|---|
| `country` | string | ISO 3166-1 alpha-2（含 GB/TW/HK 等站点市场码） |
| `n_products` | integer | 产品（一行 = 一个国家/来源的产品记录） |
| `n_variants` | integer | variant（成分 × 盐型/释放等）去重数 |
| `n_active` | integer | `status='active'` 的产品数；`unknown` 不推断在售 |
| `last_synced` | date | 该市场最近同步日期 |

### market-summary

`country`、`products`、`substances`、`name_keys`：按国家聚合；`name_keys` 是该国产品名 key 去重数。

### name-summary

`country`、`name_type`（`trade` / `inn`）、`n`：名称层**聚合**；不发布逐条名称/包装。

### substances

| 字段 | 类型 | 含义 |
|---|---|---|
| `substance_id` | string | 站内稳定成分 id（通常为 INN slug） |
| `inn_en` | string | 主名（可能是英文 INN，也可能是来源主名；见 provenance 说明） |
| `inn_zh` | string | 中文名（可空） |
| `atc` | string | ATC 码（可空；不是所有成分都有） |

## 3. 口径与边界

- **商品名不是主键**：同一商品名在不同国家/成分/规格下可能是不同产品；导出只给候选/聚合，不给单一答案。
- **strength**：站内展示层把重量统一到 mg，并保留原写法；本数据包不导出逐产品 strength 列。
- **status**：`active` / `discontinued` / `withdrawn` / `unknown`；`unknown` 不等于在售，也不等于停售。
- **provenance**：`datapackage.json` 的 `sources[]` 列出 source_id、许可、数据日期、国家范围与 `redistributable`；CN/AU/MX 等未确认或限制再发布来源标 `non_redistributable`，仅以聚合/事实层出现。
- **不包含**：原始商品名逐条表、包装行、受限来源原始记录、剂量换算或用药建议。
- **版本**：`datapackage.json` / `dataset.jsonld` 的 `version` 取 CHANGELOG 第一节；构建时间取 UTC。
- **校验**：`checksums.txt` 每行 `<sha256>  <相对路径>`；变更任何资源后重新生成。
