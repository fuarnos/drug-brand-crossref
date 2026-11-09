---
name: market-ingest
description: 接入新市场、重跑某国入库或更新数据源时用：许可与市场注册表先过、抓取落 data/raw、ingest 进库、核数并同步口径。
whenToUse: 任务涉及 etl/ingest_*、etl/fetch_*、新市场接入、数据源更新、条数对不上、覆盖表或许可清单要更新时。
---

# 市场入库（market-ingest）

目标：把公开数据变成 `data/drugs.db` 的产品行，每一步可离线重跑、每次核数。

## 0. 动手前（缺一不可）

1. **许可**：先看 `docs/许可清单.md` 与 `docs/数据溯源与许可.md`；新源先写结论再入库。
2. **市场注册表**：新增市场 = 改 `data/markets.json`（必要时 `data/languages.json`）+ 写
   ETL 插件 + 跑测试；完整 9 步见 `docs/市场扩展接口.md`。校验：

   ```powershell
   & $py lib/markets.py --check
   & $py -m unittest tests.test_markets_registry -v
   ```

   不要在任何页面/脚本里硬编码国家列表。
3. **缓存**：原始数据落 `data/raw/<source>/`（不入库）；没有缓存时 ingest 应跳过而不是报错
   （`run_all.py` 就是这个写法）。

## 1. 现有十个市场（以 DB `source` 表为准）

| 市场 | 抓取 → 入库 | 备注 |
|---|---|---|
| US | `etl/ingest_openfda_ndc.py` | `data/raw/openfda/ndc-01.json`；SSL 被代理拦时先手动下好 |
| GB | `etl/trud_fetch.py` → `etl/ingest_dmd.py`；盐型 `etl/fix_dmd_salts.py --apply --confirm-real-db` | TRUD key 在 `.env`；器械/耗材按「名字里有没有剂量」滤掉 |
| CN | `etl/extract_nhsa_pdf.py` / `merge_nhsa_parts.py` → `etl/ingest_nhsa.py`；`diff_nhsa_snapshots.py`、`fix_cn_combos.py`、`cleanup_cn_data.py`、`build_cn_aliases.py`、`apply_cn_brand_candidates.py` | 产品身份 = 通用名 + 厂家 + 规格 + 批准文号；商品名可空 |
| ES | `etl/ingest_cima.py`；`fix_es_combos.py`、`merge_es_substances.py` | `data/raw/cima/page-*.json` + ATC 详情 `atc/` |
| MX | `mx_discover.py --download alop` → `extract_cofepris_alop.py` → `extract_cofepris_status.py`（+ prorroga）→ `fetch_mx_catalogs.py` → `build_mx_inn_map.py` → `ingest_mx.py`；`ingest_mx_ccby.py`、`ingest_mx_pervolume.py --apply --allow-real` | 源无浓度列，只能唯一值回填；空是数据事实 |
| AU | `fetch_pbs.py` → `ingest_pbs.py`；`fetch_tga_cmi.py` → `ingest_tga_cmi.py`；`fetch_artg_index.py` → `ingest_artg_index.py`；`ingest_artg_enrich.py`；`fetch_artg_details.py` → `ingest_artg_details.py`（慢，单独跑）；`ingest_artg_medicines.py`（ARTG 全量 32,904） | PBS 限速 20 秒/次 |
| CA | `etl/fetch_ca_dpd.py` → `etl/ingest_ca_dpd.py` | 9 端点全量；排除顺势 / 兽药 / 辅料 |
| TW | `etl/fetch_tw_tfda.py` → `etl/ingest_tw_tfda.py`；`build_tw_aliases.py` | 规格来自品名解析，置信度有限 |
| SG | `etl/ingest_sg_hsa.py` | HSA SODL v1.0 |
| HK | `etl/ingest_hk_druglist.py` | 仅名称/成分层，无规格/剂型/状态 |
| EU（占位） | `etl/ingest_eu.py` / `etl/ingest_ema_medicines.py` | region 占位；写库窗口等排期 |

## 2. 标准流程

抓取（限速写死）→ 解析（PDF/HTML → CSV/JSONL，落 `data/raw/`）→ 归一化
（`normalize_name.py`、`normalize_strength.py`、`normalize_salts.py --apply --confirm-real-db`、
`normalize_units_*.py`）→ 入库（幂等、只读缓存）→ 合并/补全（`merge_*_substances.py`、
`auto_merge_substances.py`、`apply_salt_fractions.py`、`ingest_chembl_atc.py`、`ingest_wikidata_atc.py`、
`seed_warnings.py`）→ 核数 → 收尾。

`run_all.py` 已串全量重建（建库 → 各市场 → 种子 → 俗名/术语 → 归一化/补全 → `db/source_dates.py`
→ `site/build.py`）。注意其中不少脚本带 `--apply --confirm-real-db`，跑前确认是写正式库还是先 dry-run。

## 3. 入库后必查

```powershell
& $py db/check_data.py
& $py deploy/ci_checks.py --fast
& $py lib/markets.py --check
& $py db/q.py "SELECT country, COUNT(*) FROM product GROUP BY country ORDER BY 2 DESC"
& $py etl/provenance.py --status      # 溯源覆盖率（只读）
& $py etl/drift_check.py              # 10 个来源的漂移扫描（只读；写基线看脚本用法）
```

- 条数变化要对得上；对不上先查去重键（品牌 + 成分 + 规格 + 剂型 + 包装）与排除规则。
- 新成分确认没和英文 INN 分家（`merge_cn_substances.py` / `merge_es_substances.py` /
  `auto_merge_substances.py` / `build_cross_market_candidates.py` 是现成入口）。
- 空字段是源事实，不要伪造；改数据截止日重跑 `db/source_dates.py`。
- 改口径 → README / About / CHANGELOG 同步；新源/许可结论 → `docs/许可清单.md`。

## 4. 红线

- 不提交 `data/raw/`、`data/*.db`、中间 CSV（除许可明确的 `data/sources/` 小快照）。
- 许可未定必须页面标「待确认」并署名链回；不绕 WAF、不付费买数据。
- 不在别的会话构建/发布时并行改 `data/drugs.db`；动库前先在任务里写明。
- 大改前后各跑一次 `db/check_data.py`，before/after 写进 `reports/`。
