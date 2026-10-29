# AU ARTG Medicines 2026-10-28 入库执行报告（task-11 数据侧）

> 日期：2026-10-30（北京 10:0x）｜ 状态：**✅ 已写真实库**（Lead 2026-10-30 批准；v0.9.0 已上线、DB 空闲后执行）
> 数据：`data/raw/artg_20261028/`（TGA ARTG 导出，2 CSV / 37,097 行 / **34,606 ARTG ID** / 32 列；zip sha256 `771f1220…`）
> 脚本：`etl/ingest_artg_medicines.py`（`--keep-name-only`；dry-run 默认只读；apply 单事务 + manifest；`--rollback`）
> 备份：`data/backups/drugs-before-artg-20261030.db`（391,098,368 B，sha256 `64B10F2843A585A215D6FA555431D866EB5AAA638A32B9F09B6224871081947C`）
> 撤销清单：`.tmp/artg-ingest/artg_write_manifest.json`（4.8 MB：32,904 product_ids / 23,940 keys / 31,652 variants / 1 added_name / 626 enriched）

---

## 0. 结论（实际 vs 预期）

| 项 | 预期 | 实际 | 偏差 |
|---|---:|---:|---:|
| products | 477,098 | **477,098** | 0 |
| product_component | 628,013 | **628,013** | 0 |
| product_name | 652,909 | **652,909** | 0 |
| name_key | 202,092 | **202,092** | 0 |
| name_variant | 229,794 | **229,794** | 0 |
| sources | 39 | **39** | 0 |
| AU products | 44,794 | **44,794**（11,890 + 32,904） | 0 |
| DB 体积 | ~410–420 MB（VACUUM 后） | **419,627,008 B（419.6 MB）** | ✓ |

- 全部计数**与预期完全一致（偏差 0%）**；`quick_check=ok`、`foreign_key_check=0`。
- 写入：**新增 32,904 产品**（34,606 ARTG ID 中 1,702 个已有产品只补字段）、**73,054 components**（variant 解析丢 284）、**+23,940 name_key**、**+31,652 name_variant**、**+32,904 product_name**、**source +1（`artg_export`）**。
- 补字段：**route +144、pack +482**（enriched 记录 626）。
- 耗时：apply **10.4s 事务 / 16.7s 墙钟**；VACUUM **6.4s**（433.8 → 419.6 MB）。
- 口径：`status='unknown'` **32,904/32,904**（导出无状态列，不推断在售）；Listed (Export Only) 新产品 **2,278** 带 note 标注「僅供出口，非澳洲境內供應」（另有 **354** 个既有 `artg_detail` 产品本就是 Export Only，保留原 note）。

---

## 1. 执行记录

| # | 步骤 | 结果 |
|---|---|---|
| 0 | 备份 | 391,098,368 B；sha256 `64B10F28…` |
| 1 | 副本 dry-run（`.tmp/artg-ingest/drugs-dryrun.db`） | 34,606 产品 / 32,904 新增 / 81,269 可写成分 / 1,446 仅名称 / 2,640 Export Only / token 82.1% |
| 2 | 正式 apply | 32,904 产品 / 73,054 成分 / 284 variant 丢弃 / 626 补字段 / 23,940 keys / 31,652 variants；10.4s |
| 3 | 验数 | 477,098 / 628,013 / 652,909 / 202,092 / 229,794 / 39；quick ok / FK 0 |
| 4 | VACUUM | 433,750,016 → **419,627,008 B**（6.4s） |
| 5 | check_data | 前后各 115 行；差异仅：AU 行 `(AU, 44,794, 3,595, 7,160, 2026-10-29)`、counts、collisions severe 20,666 → **23,753** |

**check_data 前后差异（全量）**

| 项 | before | after |
|---|---:|---:|
| products | 444,194 | **477,098** |
| components | 554,959 | **628,013** |
| name_keys | 178,152 | **202,092** |
| names | 620,004 | **652,909** |
| AU coverage | (AU, 11,890, 2,758, 7,160) | **(AU, 44,794, 3,595, 7,160, 2026-10-29)** |
| collisions severe | 20,666 | **23,753**（+3,087，新名归一后预期） |
| collisions warning | 837 | 837（不变） |
| substances / variants | 12,649 / 14,249 | 不变 |

---

## 2. 数据质量抽样

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/q.py "SELECT status, COUNT(*) FROM product WHERE source_id='artg_export' GROUP BY 1"
& $py db/q.py "SELECT COUNT(*) FROM product WHERE source_id='artg_export' AND note LIKE '%僅供出口%'"
& $py db/q.py "SELECT form_base, COUNT(*) FROM product WHERE source_id='artg_export' GROUP BY 1 ORDER BY 2 DESC"
& $py db/q.py "SELECT product_id, dosage_form, route, pack, mah, category FROM product WHERE source_id='artg_export' LIMIT 3"
```

| 项 | 结果 |
|---|---|
| status | `unknown` 32,904（全部） |
| Export Only 标注 | 新产品 2,278 + 既有 artg_detail 354 = 2,632（导出内 2,640，余 8 为既有 ARTG-ID 产品，保留原 note） |
| form_base | tablet 14,119 · capsule 7,255 · injection 4,522 · liquid 2,175 · topical 1,853 · powder 1,242 · unknown 1,002 · inhalation 410 · 其余少量 |
| 样例 | `AU-ARTG-100025`：Tablet, uncoated / Oral / 42 tablets / Arrotex / ARTG Registered / unknown |
| 无成分产品总数 | 2,416 → **3,911**（+1,495 = 1,446 仅名称层 + 49 成分全部无法解析）；build 侧需按「成分未收录/名称层」展示 |

---

## 3. 回滚

```powershell
# 数据级（副本实测：products/components/keys/variants/names 全部回基线，pid_hash 不变）
& $py etl\ingest_artg_medicines.py --rollback --allow-real --db data\drugs.db `
    --manifest .tmp\artg-ingest\artg_write_manifest.json
# 整库兜底
Copy-Item data\backups\drugs-before-artg-20261030.db data\drugs.db
```

- 回滚内容：删 32,904 产品（级联 component/name）、删本次创建的 23,940 name_key（仅无引用者）/ 31,652 name_variant（按 key+raw）/ 1 条 added product_name、恢复 626 条 enriched 旧值（route/pack → NULL）、删 `ingest_run(artg_export-2026-10-28)`；**保留 `source(artg_export)` 行**（来源登记）。
- 幂等：二次 apply 会先删本 source 产品再重写；manifest 合并历史撤销记录（副本实测 apply→apply→rollback 完整还原）。

---

## 4. 后续（不在本任务）

| # | 事项 | 归属 |
|---|---|---|
| 1 | About/页脚加 **TGA/ARTG 署名**（四语）+ 数据截止 2026-10-28 | task-11 build 侧 |
| 2 | 页面展示：「成分未收录/名称层」3,911 个无成分产品；Export Only 徽章；`status='unknown'` 明示「不代表在售」 | build（v0.9.1） |
| 3 | README / About / CHANGELOG 计数更新：AU 44,794、全库 477,098（口径统一） | 发布任务 |
| 4 | 名称碰撞 severe +3,087 抽检 Top | 发布前验收 |
| 5 | HK 页面启用（task-9）与本批 AU 各自独立窗口 | Lead 排期 |

## 5. 风险

| # | 风险 | 处置 |
|---|---|---|
| 1 | 3,911 个无成分产品（含 1,446 仅名称层） | build 先例 2,416；页面标「成分未收录」 |
| 2 | 碰撞 severe 23,753（+3,087） | 沿用 `collision` 视图；发布前抽检 |
| 3 | 82.1% token 覆盖 | 植物药/益生菌/防晒/THC 不硬造；后续如需补，走别名表 |
| 4 | `status='unknown'` 全部 | 页面明示；不推断在售/注销 |
| 5 | Export Only 2,632 | 结果行/详情标注「僅供出口」 |

## 6. 证据

| 文件 | 内容 |
|---|---|
| `data/backups/drugs-before-artg-20261030.db` | 开窗备份（sha256 `64B10F28…`） |
| `.tmp/artg-ingest/artg_write_manifest.json` | 撤销清单（4.8 MB） |
| `.tmp/artg-ingest/run/apply_real.txt` / `check_before.txt` / `check_after.txt` | apply 日志与 check_data 前后 |
| `.tmp/artg-ingest/checklist.md` | 执行清单（已执行） |
| `reports/artg-20261028-audit.md` | 数据审计（规模/字段/匹配） |
| `docs/许可清单.md` §2.6 | 来源 + 署名 TGA/ARTG（无授权措辞） |

_本报告为 task-11 数据侧执行结果：已写真实库、已 VACUUM；未跑 build/publish、未改 site/。_
