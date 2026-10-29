# 数据产品打包（v0.9.2 task-23）

> 2026-10-30 ｜ `site/build.py` 构建期生成 ｜ **正式 `site/dist` 已构建（v0.9.2，897.662 MiB / 121,286 文件）** ｜ 未写 DB、未发布。
> 只发布**派生层/聚合层**；受限来源不导出原始记录。字段/口径见 [`docs/data-dictionary.md`](../docs/data-dictionary.md)。

## 0. 结论

构建期自动产出：
- `datapackage.json`（Frictionless tabular-data-package profile；4 个资源，字段/类型/行数/bytes/sha256/version/sources/许可分级；version=v0.9.2）
- `dataset.jsonld`（schema.org `Dataset`，version/dateModified/license/distribution）
- `checksums.txt`（资源 + datapackage + dataset + docs 的 SHA-256）
- `data/exports/`：`coverage.csv`、`market-summary.csv`、`name-summary.csv`、`substances.csv`
- `docs/data-dictionary.md` 已复制进 dist；About 四语链接 `Data package / Dataset metadata / SHA-256 checksums / Data dictionary` 正确（副本自动加 `../` 前缀）。

实测资源：

| 资源 | 行数 | bytes |
|---|---:|---:|
| coverage.csv | 10 | 383 |
| market-summary.csv | 10 | 249 |
| name-summary.csv | 16 | 265 |
| substances.csv | 12,649 | 705,343 |

校验：`checksums.txt` 全部匹配；datapackage JSON 可解析；`dataset.jsonld @type=Dataset`。正式 dist 897.662 MiB（含 8,455 个 combo stub + docs 字典）。

## 1. 许可分级

- `sources[]` 列出 `source_id` / 名称 / URL / license / license_url / data_as_of / countries / `redistributable`。
- **CN / AU / MX** 标 `non_redistributable`（未确认或限制再发布），不导出逐条产品/名称记录；仅以聚合/覆盖/成分清单出现。
- 数据包 `licenses` 指向 `docs/数据溯源与许可.md`；`dataset.jsonld.license` 同链接。
- 本包**不含**原始商品名逐条表、包装行、受限来源原始记录；只含统计与成分标识。

## 2. 验证

```text
datapackage: 4 resources, checksums.txt
resources: coverage(10) / market-summary(10) / name-summary(16) / substances(12649)
dataset @type=Dataset
checksum bad: []
```

- `frictionless` 包未安装（`ModuleNotFoundError`），未跑官方 validator；按 Frictionless tabular-data-package 结构做 JSON/字段/路径/校验和自检。若 CI 需要，可在 GitHub Actions 装 `frictionless` 后补一行 `frictionless validate datapackage.json`。
- 版本：正式构建 `v0.9.2`；`dataset.jsonld` 与 `datapackage.json` 版本一致。
- 仅 About/首页引用 dataset link；全站每页不再加 dataset link（v0.9.1 P0 回归修复后为控制体积所做的调整）。

## 3. 边界

- 资源以聚合/覆盖/成分清单为主，**没有逐条 products/names 导出**：受限来源许可与体积（900MiB）双重约束；如后续要逐条导出，需先按来源过滤并做单独体积预算。
- `name-summary` 是名称层聚合（country × name_type），不是逐条名称表；字段字典已注明。
- 站点页面（HTML/索引）不是数据包资源；数据包只描述 `data/exports/` + 元数据。
