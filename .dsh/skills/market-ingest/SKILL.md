---
name: market-ingest
description: 接入新市场、重跑某国入库或更新数据源时用：抓取落到 data/raw、ingest 进 data/drugs.db、核对计数并同步 README/CHANGELOG。
whenToUse: 任务涉及 etl/ingest_*、etl/fetch_*、新市场接入、数据源更新、条数对不上、覆盖表要更新时。
---

# 市场入库（market-ingest）

目标：把某个市场的公开数据变成 `data/drugs.db` 里的产品行，且**每一步都能离线重跑、每次都核对计数**。

## 0. 动手前确认三件事

1. **许可**：这个源能不能再发布？结论写在哪份 `docs/` 里？现有状态见 README「数据现实」表
   （ES / MX 待确认，CN 没找到明确许可，AU 的 ARTG 全量只能走 FOI）。
2. **批量可得性**：官方批量文件 / API / PDF？拿不到就先记进 docs 并标「待确认」，不要硬写爬虫。
3. **缓存位置**：`data/raw/<source>/`，不进版本库。没有缓存时 ingest 应**跳过而不是报错**
   （`run_all.py` 里每个市场都是这个写法）。

## 1. 标准流程

| 步骤 | 做法 |
|---|---|
| 抓取 | `etl/fetch_*.py` / `etl/*_discover.py`，原始响应落 `data/raw/<source>/`，限速写死在代码里 |
| 解析 | PDF / HTML 先落中间 CSV / JSONL（`etl/extract_*.py`），原始和中间产物都留在 data/raw |
| 归一化 | 复用 `etl/normalize_name.py`（NFKC / 全角 / 西里尔 / 繁简 / 尾部剂量切分），不要另写一套 |
| 入库 | `etl/ingest_<market>.py`：幂等（先删后插或 UPSERT），只读缓存不联网 |
| 核数 | `db/q.py` 查条数与字段覆盖率；跑 `db/check_data.py` |
| 收尾 | 同步 README / CHANGELOG 数字；`db/source_dates.py` 更新数据截止日；新脚本接进 `run_all.py` |

## 2. 各市场入口（含坑）

| 市场 | 抓取 → 入库 | 缓存 / 坑 |
|---|---|---|
| US | `etl/ingest_openfda_ndc.py` | `data/raw/openfda/ndc-01.json`；无缓存时 run_all 跳过美国；SSL 被企业代理拦时先用 PowerShell 下好再跑 |
| GB | `etl/trud_fetch.py` → `etl/ingest_dmd.py` | TRUD key 在 `.env` 的 `TRUD_API_KEY`；`data/raw/dmd/nhsbsa_dmd_*.zip`；名字里没有剂量的是器械/耗材，要滤掉（约 10 万条） |
| CN | 快照 PDF/公示 → `etl/extract_nhsa_pdf.py` → `etl/ingest_nhsa.py` | 医保库；产品身份是「通用名 + 厂家 + 规格 + 批准文号」，商品名可缺省；`merge_nhsa_parts.py`、`diff_nhsa_snapshots.py`、`fix_cn_combos.py` 处理切片与复方 |
| ES | `etl/ingest_cima.py`（自己下载 128 页列表） | `data/raw/cima/page-*.json`、ATC 详情 `data/raw/cima/atc/`；首次联网后离线 |
| MX | `etl/mx_discover.py --download alop` → `extract_cofepris_alop.py` → `extract_cofepris_status.py`（+ `extract_cofepris_prorroga.py`）→ `fetch_mx_catalogs.py` → `build_mx_inn_map.py` → `etl/ingest_mx.py` | `data/raw/mx/`；源**没有浓度列**，只能唯一值回填（≈29%），空是数据事实不是 bug；状态 = 有效期 + 注销清单 + 续期清单三线索 |
| AU | `fetch_pbs.py`（3 个请求，20 秒/次限速）→ `ingest_pbs.py`；`fetch_tga_cmi.py` → `ingest_tga_cmi.py`；`fetch_artg_index.py` → `ingest_artg_index.py`；`ingest_artg_enrich.py`；`fetch_artg_details.py` → `ingest_artg_details.py`（很慢，单独跑） | `data/raw/pbs/api/items.json`、`data/raw/tga_cmi/cmi.json`、`data/raw/artg/*.jsonl`；ARTG 无批量导出，全量只能 FOI（`docs/foi-artg-request.md`） |
| CA | `etl/fetch_ca_dpd.py`（9 个端点一次全量） → `etl/ingest_ca_dpd.py` | `data/raw/ca/dpd/`；排除顺势疗法 / 兽药 / 辅料；复方剂量按每片、每 mL 折算 |

## 3. 入库后必查

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py db/q.py "SELECT country, COUNT(*) FROM product GROUP BY country ORDER BY 2 DESC"
& $py db/q.py "SELECT country, ROUND(100.0*SUM(strength IS NOT NULL)/COUNT(*),1) AS pct FROM product GROUP BY country"
& $py db/check_data.py
```

- 条数变化要和预期对得上；对不上先查去重键（品牌 + 成分 + 规格 + 剂型 + 包装）和排除规则。
- 新增 substance 时确认没和英文 INN 分家：现成合并入口是 `merge_cn_substances.py`、
  `merge_es_substances.py`、`auto_merge_substances.py`。
- 改了数据截止日就重跑 `db/source_dates.py`，覆盖表要显示源自己的日期而不是抓取时间。
- 改了顶层数字后，同步 README / About 文案 / CHANGELOG（口径一致，别只改一处）。

## 4. 红线

- 不提交 `data/raw/`、`data/*.db` 和中间 CSV；只有 `data/sources/` 那种许可明确的小快照入库。
- 不要「先写进库再说许可」；许可未定的源，页面上必须标「待确认」并署名链回原文。
- 不在别的会话跑构建 / 入库时并行改 `data/drugs.db`；动库前先在任务里写明。
