# EU 区域层写入窗口（v0.11.0 第一步）

日期：2026-11-11 ｜ 库：`data/drugs.db`（真实写库，已备份）｜ 依据：`reports/eu-ingest-prep-20261107.md` §11

## 0. 结论

| 项 | 结果 |
|---|---|
| 写入 | `region='EU'` **2,095 产品 / 2,138 组件 / 2,095 名称**；`name_key` 新建 **647**、`name_variant` 新建 **1,311**；`corroboration` 2,072；`source` 2 行（`eu_union_register` CC BY 4.0、`ema_medicines` EMA legal notice） |
| 全库 | products **477,098 → 479,193**（+2,095）、components 628,013 → **630,151**、product_name 652,909 → **655,004**、name_key 202,092 → 202,739、name_variant 229,794 → 231,105；substance 12,637 不变 |
| 校验 | `PRAGMA foreign_key_check` **0**、`integrity_check` **ok**、`quick_check` **ok**、`country`/`region` XOR 违规 **0**、`db/check_data.py` 退出码 **0** |
| coverage | 10 行 → **11 行**，EU 行 `(2095, 1045, 1547, 2026-11-10)`；`collision(warning)` **905 → 925** |
| 回滚 | 已演练（副本 apply → rollback → 回到 477,098 / EU 0 / coverage 10 行 / FK 0）；真实库撤销清单 `data/backups/eu-manifest-20261111.json` |
| 备份 | `data/backups/drugs-20261111-pre-eu.db`（420,581,376 B，sha256 `5AFE2116…B89C08`，与写库前逐字节一致） |
| 耗时 | dry-run 0.81 s / check-sql 1.0 s / 副本 apply 1.41 s / rollback 1.0 s / 真实 apply 1.19 s |

## 1. 快照（重抓，`data/raw/ema_20261111/`）

| 文件 | 字节 | sha256 | 说明 |
|---|---|---|---|
| `ods_products.json` | 16,768,535 | `84abdd66…782d7d` | 与 11-06 快照**逐字节相同**，HTTP `Last-Modified: 2026-11-03 08:24:24 GMT` → UR 未更新，仍是 11-03 版 |
| `ema_medicines.json` | 6,804,196 | `4340e0e3…536e6426` | 新抓（11-10 05:00 GMT），`meta.timestamp=2026-11-10T06:01:39Z`；旧快照为 11-06 |

> 抓取方式：`Invoke-WebRequest` / `curl.exe` 在本机 schannel 报 `SEC_E_NO_CREDENTIALS`，改用 Python `urllib` 成功（记在这里省下次踩坑）。

## 2. 步骤与判定（照 §11）

| # | 步骤 | 结果 |
|---|---|---|
| 1 | 备份 | ✅ 420,581,376 B，副本 sha256 与源一致 |
| 2 | 重抓快照 + sha256 | ✅ 见 §1；UR 未变，EMA 更新 |
| 3 | `--dry-run`（新快照） | ✅ 2,095 / 2,138 / 647 / 1,311 / 成分映射 86.8%（1,212/1,396 token） |
| 4 | `--check-sql` | ✅ FK 0 / integrity ok / XOR 0 / 行数与 dry-run 一致；区域层体积 2.72 MB |
| 5 | 副本演练（apply → 校验 → rollback） | ✅ 副本 479,193 / EU 2,095 / coverage 11 行 / FK 0；rollback 后 477,098 / EU 0 / coverage 10 行 / FK 0 |
| 6 | 真实库 `--apply --allow-real --manifest` | ✅ 一次事务，written = dry-run |
| 7 | 校验（SQL + check_data） | ✅ 见 §0 |
| 8 | 站点接入 + 构建 | v0.11.0（见 `reports/eu-site-integration-20261111.md`） |

## 3. 修掉的一个 ETL 预测偏差

`_dry_run_counts()` 只按「库里是否已存在」判断 `name_variant`，没有对**同一批内两个产品共用一个商品名**去重，预测 **1,319** 而 `INSERT OR IGNORE` 实际写 **1,311**（多算 8 行，另 10 个 key 各有 2 个 variant）。

已修：`etl/ingest_eu.py` 加 `seen_variant_pairs` 去重（写库端本来就是 `INSERT OR IGNORE`，语义不变）；修后 dry-run 预测 = 实际写入 **1,311**。影响：`--manifest` 的 `counts.name_variants_new` 与 `written.name_variant` 从此一致，回滚清单不会多删。

## 4. 回滚方法

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/ingest_eu.py --rollback --manifest data/backups/eu-manifest-20261111.json --db data/drugs.db
# 或整库恢复：Copy-Item data/backups/drugs-20261111-pre-eu.db data/drugs.db -Force
```

回滚后复核：`SELECT COUNT(*) FROM product` = 477,098、`region='EU'` = 0、`coverage` 10 行、FK 0。
（`source` 表两行**不随数据回滚删除**——它们与数据无关，可复用。）

## 5. 复现

```powershell
& $py etl/ingest_eu.py --dry-run --ur data/raw/ema_20261111/ods_products.json --ema data/raw/ema_20261111/ema_medicines.json
& $py etl/ingest_eu.py --check-sql --ur data/raw/ema_20261111/ods_products.json --ema data/raw/ema_20261111/ema_medicines.json
& $py db/check_data.py
& $py db/q.py "SELECT COALESCE(country,region) m, COUNT(*) FROM product GROUP BY 1 ORDER BY 1"
```
