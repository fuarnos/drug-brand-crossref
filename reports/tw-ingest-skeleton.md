# 台湾 TFDA 入库 ETL 骨架（dry-run 样本）— task-54

> 日期：2026-10-28 · 任务：task-54 · 状态：**骨架 + dry-run 完成（未写 DB、未改 `site/build.py`、未发布）**
> 脚本：`etl/ingest_tw_tfda.py`（658 行，默认 `--dry-run`；`--write-db` 为占位报错）
> 产物：`data/tw_ingest_dryrun.csv`（样本 1,535 行 × 32 列）、`.tmp/tw-ingest/`（全量/样本统计、未匹配清单、剂型表）
> 输入：`data/raw/tw/tfda_36.csv`（72,096 行 × 28 列，data_as_of=2026-10-22；源审计见 `reports/tw-tfda-audit.md`）

---

## 0. 结论摘要

| 项目 | 样本 dry-run（前 2,000 条候选） | 全量 dry-run（72,096 行） |
|---|---:|---:|
| 扫描 / 产品类候选 | 6,669 / 2,000 | 72,096 / 21,312 |
| **可入产品（去重后许可证数）** | **1,535** | **17,892** |
| 其中多行变体（同证多包装） | 252 | 1,969 |
| 拒绝（注销/非产品类/过期/成藥草案/中藥草稿/无成分） | 3,123 + 1,414 + 47 + 72 + 5 + 7 | 35,556 + 13,457 + 1,095 + 324 + 281 + 71 |
| **成分 token 映射覆盖率** | **91.3%**（2,090/2,289） | **83.5%**（32,598/39,045） |
| 成分全匹配行占比 | 1,373/1,535 = **89.4%** | 14,344/17,892 = **80.2%** |
| 未匹配 token（distinct / 次数） | 121 / 162 行 | 893 / 3,548 行 |
| 多成分（复方）行 | 155（10.1%） | 5,048（28.2%） |
| 规格置信度（medium/none/low） | 910 / 623 / 2 | 8,541 / 9,316 / 35 |
| 剂型 base 分布 | tablet 713 / injection 301 / topical 197 / capsule 157 / liquid 114 / powder 36 / supp 8 / inhale 8 / other 1 | tablet 7,864 / injection 2,878 / topical 2,567 / capsule 2,177 / liquid 1,680 / powder 511 / supp 105 / inhale 89 / other 14 / unknown 7 |
| release（ER/DR） | 41 / 24 | 417 / 258 |

**一句话**：骨架能稳定地把 TFDA 许可证压缩成「产品 + 成分 + 剂型 + 厂商 + 状态 + 规格（带置信度）」的 dry-run 行；样本可入 1,535 张证、成分映射覆盖 91.3%，全量约 17,892 张、覆盖 83.5%；真正写库前必须先做 `product.country` 的 `'TW'` 枚举迁移（本任务写范围外）。

---

## 1. 脚本结构（`etl/ingest_tw_tfda.py`，file:line）

| 位置 | 内容 |
|---|---|
| L91–L114 | 口径常量：`KEEP_KINDS=("製劑","菌疫")`；成藥草案排除；中藥/植物药拉丁名草稿名单；32 列出表 |
| L141–L178 | `load_substance_map()`：**只读 DB（`mode=ro`）** 的 substance+variant(盐) → `{(归一成分,盐): substance_id}`（12,679 组合）；DB 缺失时降级 `site/dist/data/index.json` |
| L117–L139 | 归一工具：`nk()`（NFKC/大写/去括号/折叠空白）、`cn_units_to_en()`（公絲/毫克→mg、公撮/毫升→ml、微克→mcg、公克→g、國際單位→IU） |
| L221–L310 | 成分解析：`_clean_variants()`（去剂型/描述词/同位素前缀/百分号）、`_split_salt_local()`（盐/水合物尾部，含 hbr/hcl/2hcl/bisulfite/拼写差异）、`match_component()`（整段→拆盐→去 DL-/L-→BAN/USAN 别名；括号内盐型补回） |
| L312–L326 | `split_ingredients()`：`;;` / `;` / `、` / ` + ` 拆分 |
| L328–L368 | 剂型：`FORM_MAP`（205 种 → tablet/capsule/injection/topical/powder/liquid/suppository/inhalation/other）+ `tw_form_base()`；`release_of()` 识别 持續/緩釋/控釋/長效/腸溶/ER/SR/XR/DR |
| L370–L431 | 规格：复用 `normalize_name.normalize().strengths`，中文单位先转英文；`parse_strengths()`（数值按 float 去重）；`decide_strength()` 输出 `strength_value/unit + per_volume_value/unit + confidence`（medium/none/low，复方不猜） |
| L433–L450 | `status_of()`（注销→discontinued / 过期→discontinued / 否则 active）；`product_id_of()`（`TW-TFDA-<slug|md5>`） |
| L480–L615 | `main()`：读 CSV → 逐行过滤/映射/去重（同证多行合并、`variant_count`）→ 写 dry-run CSV + 统计 |
| L600–L640 | 统计落盘：默认 `stats.json`；全量/其它样本写 `<out名>-stats.json`，互不覆盖；未匹配 token 清单、剂型草表 |

**只读边界**：DB 连接为 `sqlite3.connect("file:...?mode=ro", uri=True)`；`--write-db` 直接报错（提示先做 TW 枚举迁移）。本次运行前后 `data/drugs.db` mtime 未变。

---

## 2. 字段映射（TFDA → dry-run 列 → DB 目标）

| TFDA 字段 | dry-run 列 | 目标 schema / 说明 |
|---|---|---|
| 許可證字號 | `approval_id` + `proposed_product_id` | `product.approval_id` / `product_id`（`TW-TFDA-*`）；同证多行合并为 1 产品 + `variant_count` |
| 中文品名 / 英文品名 | `name_zh` / `name_en` | `product_name`（`name_type=trade`，lang=zh-Hant/en）；经 `normalize_name.normalize()` 生成 `name_key`（繁转简对 CN 碰撞检测有影响，见 §7） |
| 主成分略述 | `ingredients_raw` / `ingredient_tokens` / `components` / `unmapped_tokens` | `product_component`（多行）+ `variant`（盐型/酯）；每段含 `原串 => substance_id [salt_code]` 审阅信息 |
| 劑型 | `form_raw` / `form_base` / `release` | `product.dosage_form` / `form_base` / `release` |
| 申請商名稱 | `mah` | `product.mah` |
| 製造商名稱 / 製造廠國別 | `manufacturer` / `origin_country` | 厂商与产地（产地用于跨市场线索，不等于上市国） |
| 藥品類別 | `category` | `product.category`（处方/指示/成藥…，本次成藥已按草案排除） |
| 有效日期 / 註銷狀態 / 註銷日期 | `status` / `status_date` / `valid_until` | `product.status`（active/discontinued）+ `status_date` |
| （品名解析） | `strength_*`（6 列） | `product_component.strength_value/unit + per_volume_value/unit`，`confidence` 只用于内部审阅，不入库 |
| 不输出 | `適應症` / `用法用量` / `包裝與國際條碼` | 前两者按站点边界不存不展示；条码字段官方全空 |

---

## 3. 状态判定与过滤口径（本次结果）

1. 只留 `許可證種類 ∈ {製劑, 菌疫}`（排除原料藥 13,457 行等非产品类）。
2. 注销（`註銷狀態` 非空）→ discontinued，不进产品层（35,556 行）。
3. 未注销但 `有效日期 < 今天` → discontinued（expired，1,095 行）。
4. **草案排除**：藥品類別含「成藥/乙類成藥」→ 324 行（下一轮可按产品策略放开）；成分含中藥/植物药拉丁名草稿名单 → 281 行（需人工复核，尤其 SILYMARIN 等植物提取物）。
5. 无成分 71 行、无品名 0 行。
6. 剩余 **21,312 行候选 → 去重后 17,892 张证**（1,969 张证有多行包装/重复行变体）。

---

## 4. dry-run 样本（`data/tw_ingest_dryrun.csv`）

- 口径：按文件顺序扫描，取前 **2,000 条产品类候选**（满足 1/2/3 后）；输出 **1,535 行 × 32 列**，UTF-8-SIG，659 KB。
- 覆盖：token 级 91.3%（2,090/2,289）；全匹配行 89.4%；未匹配 distinct 121；复方 155；多行变体证 252。
- 规格：medium 910（59.3%）、none 623（40.6%）、low 2（0.1%）。
- 剂型：tablet 713 / injection 301 / topical 197 / capsule 157 / liquid 114 / powder 36 / suppository 8 / inhalation 8 / other 1；release ER 41、DR 24。
- 样例（脚本输出，含盐型与强度）：
  - `內衛藥製字第006529號 | 信血平片０．２５公絲 | SINSERPINE TABLETS 0.25MG | 錠劑→tablet | RESERPINE => reserpine | 0.25 mg medium`
  - `內衛藥製字第006733號 | "人人"新黴素膠囊２５０公絲 | NEOMYCIN SULFATE CAPSULES 250MG | 膠囊劑→capsule | NEOMYCIN (SULFATE) => neomycin [sulfate] | 250 mg medium`
  - `內衛藥製字第006532號 | 持續性荷爾蒙－Ｍ針 | DEPOT HORMON-M INJECTION | 注射劑→injection/ER | TESTOSTERONE CYPIONATE => testosterone [non_salt]`（酯类应落 `variant.ester`，写库时补）
- 全量另存 `.tmp/tw-ingest/full_dryrun.csv`（17,892 行，8.9 MB）与 `full_dryrun-stats.json`。

---

## 5. 全量 dry-run 统计（`.tmp/tw-ingest/full_dryrun-stats.json`）

- 17,892 可入证；token 覆盖 83.5%（32,598/39,045）；全匹配行 80.2%；未匹配 distinct 893（涉及 3,548 行，19.8%）。
- 复方 5,048 行（28.2%）；规格 medium 8,541（47.7%）、none 9,316（52.1%）、low 35。
- 剂型 unknown 仅 **7 行**（膠劑/懸浮劑/牙膏劑/乳漿劑/丸劑/陰道避孕環/放射性藥品孳生器各 1），映射覆盖率 99.96%。
- release：ER 417、DR 258（本次靠品名/剂型关键词，长尾可能漏，待人工抽检）。

---

## 6. 未匹配 token top（→ 下一轮别名表）

**全量 top 15**：`DL-METHYLEPHEDRINE HCL(527)`、`GUAIACOL GLYCERYL ETHER(257)`、`ETHENZAMIDE(210)`、`POTASSIUM GUAIACOLSULFONATE(203)`、`NOSCAPINE(115)`、`PANTOTHENATE CALCIUM(94)`、`BROMISOVALUM(88)`、`GLYCYRRHIZINIC ACID(86)`、`GUAIACOL GLYCOLATE(78)`、`SILYMARIN(66)`、`IODOCHLORHYDROXYQUIN(63)`、`OROTIC ACID(62)`、`THIAMINE DISULFIDE(58)`、`METHIONINE DL-(56)`、`OXETHAZAINE(52)`。

**样本 top 10**：`ISOCONAZOLE NITRATE`、`VARICELLA ZOSTER VIRUS GLYCOPROTEIN E`、`CHLORMEZANONE`、`SIPONIMOD FUMARIC ACID`、`GUAIACOL GLYCERYL ETHER`、`OXETHAZAINE`、`ETHENZAMIDE`、`BASIC ALUMINUM SUCROSE SULFATE`、`CARBOCYSTEINE`、`OXAZOLAM`。

画像：**(a) 复方感冒/止咳/胃肠老药的别名与盐型写法**（guaiacol 系列、methylephedrine、ethenzamide、noscapine）→ 加 ~50–100 条 BAN/USAN/盐型别名预计可把 token 覆盖提到 ~90%；**(b) 生物制剂/疫苗**（病毒糖蛋白、载体蛋白）→ 保留 unmapped，不硬造；**(c) 植物提取物**（SILYMARIN、GLYCYRRHIZINIC ACID）→ 需和中藥边界一起定标。完整清单：`.tmp/tw-ingest/{unmatched_tokens.csv, full_dryrun-unmatched.csv}`。

---

## 7. 阻塞 / 风险 / 下一步

### 阻塞（写库前必须解决）
1. **`product.country` CHECK 枚举没有 `'TW'`**（`db/schema.sql` 第 80 行；`db/init_db.py` 已有「重建表加枚举」的迁移框架）→ 需先加 `'TW'` 并验证老库可幂等升级。**本任务写范围不含 schema，未动。**
2. `source` 表需加一行 `tw_tfda`（许可/署名/data_as_of）；`ingest_run` 记录 rows_in/kept/rejected。
3. `product_name`/`name_key`：中文名经 `normalize_name` 会**繁转简**（name_key norm 是简体）——与 CN 市场同名不同药正是 `collision` 视图要暴露的；需确认 TW 繁体原文落 `name_variant.raw`、name_key 与 CN 共用归一规则（建议照旧，碰撞交给视图）。
4. 成藥/中藥草案排除（324 + 281 行）需产品/法务拍板；当前口径是「先不惹边界」。

### 风险
- 规格无结构化字段：52% 行无品名剂量（疫苗/注射剂/软膏常无「mg」；复方不猜）；medium 行也要抽检「多规格/每包裝量」误读。
- 剂型长尾已人工枚举 205→9 base，`unknown` 仅 7，但映射顺序可能误判（如「口內膏」归 topical、「口溶膜」归 tablet）。
- 成分匹配依赖 DB 现有英文名（12,679 组合）；新 substance 会分家 → 入库后跑 `db/check_data.py` + `auto_merge_substances.py` 检查。
- 去重按整行哈希/首行保留：多包装变体合并后仅存 `variant_count`，DB 层是否拆 variant 需产品决定（建议：包装不同不拆 variant，用 `product.pack`）。
- 数据量大：全量 dry-run 本机十几秒；正式 ingest 写 ~18k 产品/3–4 万组件，需批量事务 + `PRAGMA foreign_keys=ON`。

### 下一步（建议任务）
1. `db/schema.sql` + `db/init_db.py` 加 `'TW'` 枚举迁移（先用临时拷贝库验证幂等）。
2. `etl/ingest_tw_tfda.py --write-db` 实现：CLI 保留 dry-run 默认；写库路径 = 删 `source_id='tw_tfda'` 旧行 → 插 source/ingest_run → 分批插 product / product_name / product_component / name_key / name_variant / variant；读缓存不联网。
3. 补上 §6 的别名表（新 `data/sources/tw_alias_overrides.csv` 或脚本内嵌），重跑 dry-run 看覆盖率。
4. 接 `run_all.py`（无缓存跳过）；`db/source_dates.py` 记 data_as_of；同步 README/CHANGELOG/About 计数与署名（许可 ✅ OGDL v1.0）。
5. 全量验收：`db/check_data.py`、`tests/trilingual/run_tests.py`、`db/q.py` 条数/强度覆盖，报告 `reports/tw-ingest-report.md`。

---

## 8. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl\ingest_tw_tfda.py                                   # 默认 dry-run 前 2000 候选 → data/tw_ingest_dryrun.csv
& $py etl\ingest_tw_tfda.py --limit 0 --out .tmp\tw-ingest\full_dryrun.csv
& $py etl\ingest_tw_tfda.py --csv data\raw\tw\sample_active_500.csv --limit 500 --out .tmp\tw-ingest\sample_active_dryrun.csv
# 产物：.tmp/tw-ingest/{stats.json, full_dryrun-stats.json, sample_active_dryrun-stats.json,
#        unmatched_tokens.csv, form_map_draft.json, full_dryrun.csv}
```

**证据文件**：`data/tw_ingest_dryrun.csv`、`.tmp/tw-ingest/*`；脚本 `etl/ingest_tw_tfda.py`（658 行，`py_compile` 通过；本次未跑 unittest，因不接 DB）。未改 `data/drugs.db`、`site/build.py`、未跑 git/发布。
