# 规格单位归一化 + 液体浓度语义（task-135 准备）

> 日期：2026-10-29 ｜ 只读真实库（`mode=ro`）+ DB 副本验证 ｜ **未写真实库、未改 build.py、未 git/发布**
> 依据：`reports/data-quality-audit.md` P0（单位未归一化 11,880 / 液体无浓度 58,509）
> 产物：`etl/normalize_strength.py`（dry-run / apply / rollback）、`reports/strength-normalization-prep.md`、`.tmp/strength-norm/`

---

## 0. 结论

| 项 | 结果 |
|---|---|
| 单位归一化映射 | 131 种单位 → 97 种规范写法；**不换算数值**（g 不转 mg），只统一文本/符号/大小写/同义单位 |
| 副本 apply 变更 | **102,988 行**：strength_unit 27,567 + per_volume_unit 75,421（其中 ml→mL 93,381、iu→IU 3,208、ug/μg/µg/microgram→mcg 3,526、l→L 961、u/units→unit 255、meq→mEq 151、mci→mCi 101 等） |
| 液体「有规格无浓度」 | 58,509 行无 per_volume：其中 **38,522 行/30,371 产品**有 strength_value 但无浓度（`liquid_no_concentration`）；**19,987 行**连 strength 都无（`liquid_no_strength_no_concentration`）；1,005 行单位本身是 mg/ml、mg/vial 等 per-dose |
| 异常规格 | 0/负值 **44 行/44 产品**（`invalid_strength`）；≥100,000 **324 行/290 产品**（`extreme_strength`，多为 vg/genome copies） |
| trade 名混剂量 | **55,100 个产品**（`trade_name_contains_dose`，只标记，不改原文） |
| 副本验证 | change 102,988 行；products/components 不变；quick ok / FK 0；第二次 apply **0 行**（幂等）；rollback 102,988 行恢复，unit 内容 hash **与基线完全一致**、delta 0 |
| 真实窗口 | 尚未执行；命令已备：并入 task-133 统一窗口（CN 清洗后、check/VACUUM 前） |

---

## 1. 单位映射（`etl/normalize_strength.py`）

### 1.1 规则

- 先 `strip` + 空白归一（`mg / ml` → `mg/ml`），再按映射表规范化；数值原样保留。
- 不把 `g` 换算成 `mg`、不把 `万IU` 换算成 `IU`（`万IU` 保留并标记，需源数据确认）。
- 识别不了的（665 行）**保留原文**并输出 unrecognized 清单：`h`(312)、`tablet`(140)、`actuation`(167)、`actuation(s)`、`sachet`(16)、`d`(14)、`ampoule`(7)、`galu`、`billion(s)/sachet`、`hours` 等。

### 1.2 规范表（核心）

| 类别 | 原文示例 → 规范 | 影响行（approximate） |
|---|---|---|
| 体积 | `ml` → `mL`、`l` → `L`、`ml/ml` → `mL/mL` | 93,381 + 961 |
| 质量 | `ug`/`μg`/`µg`/`microgram(s)` → `mcg` | 3,526 |
| 国际单位 | `iu` → `IU`、`iu/ml` → `IU/mL`、`kiu` → `kIU`、`miu` → `MIU`、`万iu` → `万IU` | 3,500+ |
| 酶活单位 | `unit`/`units`/`u` → `unit`；`u/ml`、`units/ml` → `unit/mL`；`million units` → `million unit` | 300+ |
| 当量/摩尔 | `meq` → `mEq`、`umol` → `µmol`、`mcmol` → `µmol`、`mmol/ml` → `mmol/mL` | 170+ |
| 百分比 | `% w/v` → `%w/v`；`%` 保留 | 26,522 |
| 放射性 | `mci` → `mCi`、`uci` → `µCi`、`ci` → `Ci`、`mbq/ml` → `MBq/mL` 等 | 130+ |
| 生物制品 | `vg`→`VG`、`vp`→`VP`、`pfu`→`PFU`、`ffu`→`FFU`、`cfu`→`CFU`、`ccid50`→`CCID50`、`log10 tcid50`→`log10 TCID50`、`genome copies`/`cells` 保留 | 30+ |
| 每剂量/容器 | `mg/ vial`→`mg/vial`、`mg / ml`→`mg/mL`、`mgvial`→`mg/vial`、`mg/tab`→`mg/tablet`、`units/vial`→`unit/vial` | 200+ |

> 规范单位列表：`mg / g / mcg / kg / mL / L / % / %w/w / %w/v / IU / unit / mEq / mmol / µmol / mg/mL / mcg/mL / IU/mL / mg/g / mg/vial / mg/dose / … / VG / VP / PFU / FFU / CFU / genome copies`。完整映射见脚本 `UNIT_MAP` 与 dry-run 输出。

---

## 2. 液体「有规格、无浓度」语义

判定：`product.form_base='liquid'` 且 `product_component.per_volume_value IS NULL`。

| 分类（58,509 行） | 行数 | 含义/页面规则 |
|---|---:|---|
| `liquid_no_concentration`（有 strength_value） | **38,522**（30,371 产品） | 显示「总量 X mg（浓度未提供，不参与同规格比较）」；**不猜** per_volume，不从总量反推浓度 |
| 其中按单位细分 | 质量总量 25,604 / 体积 6,359 / 酶活 1,220 / 其他 4,334 / 已是 per-dose 单位 1,005 | 体积型（如 `0.7 ml`）显示为「体积 0.7 mL（浓度未提供）」 |
| `liquid_no_strength_no_concentration` | **19,987** | strength 与 per_volume 都空：页面标「规格未提供」，不参与规格/剂量比较 |
| 已带 per_volume 单位（mg/ml、mg/vial…） | 1,005（含在上面 38,522） | 单位本身已表达浓度/每剂；per_volume 空不影响展示，但应标记 `unit_already_per_dose` |

**为什么不能自动补**：per_volume 是「每 ml/每瓶含多少」，EMA/部分 CA/TW 源只给总量或缺失；补值属于推测，违反「数据可核」原则。窗口只做标记与展示规则。

---

## 3. 异常规格 / trade 名标记

| 标记 | 行/产品 | 规则 |
|---|---|---|
| `invalid_strength` | 44 行/44 产品（0 或负） | 展示「源值异常」/—；**不参与排序/比较**；窗口可选置 NULL（本文建议暂不置 NULL，保留源值+标记，便于溯源；如需要置 NULL，脚本留 TODO） |
| `extreme_strength` | 324 行/290 产品（≥100,000） | 多为 `vg`/`genome copies`（CA 疫苗）；显示科学计数（2×10^13 VG）并加单位说明；不参与常规 mg 比较 |
| `trade_name_contains_dose` | **55,100 个产品** | 只标记（CSV）供 build 拆分「品牌名 / 规格剂型」；**不改 name_variant 原文**（注册名保真） |

flags 全量导出：`.tmp/strength-norm/flags.csv`（product_id, ord, reason, detail）。

---

## 4. 副本验证（`.tmp/strength-norm/drugs.db`，真实库副本）

```powershell
$py = '...python.exe'
Copy-Item data\drugs.db .tmp\strength-norm\drugs.db
& $py etl\normalize_strength.py --db .tmp\strength-norm\drugs.db --apply
& $py etl\normalize_strength.py --db .tmp\strength-norm\drugs.db --apply   # 幂等
& $py etl\normalize_strength.py --db .tmp\strength-norm\drugs.db --rollback
```

| 步骤 | 结果 |
|---|---|
| dry-run | 单位变更 102,988 行；flags：liquid 38,522 / no-spec-liquid 19,987 / zero 44 / extreme 324 / trade-dose 55,100 |
| apply#1 | 102,988 行（strength 27,567 + per_volume 75,421）；事务 **0.57s**（含计划+清单墙钟约 5–6s）；products 431,555、components 534,246 不变 |
| apply 后单位分布 | 131 → **97** 种；`ml`/`iu`/`ug` 小写残留 **0**；quick ok / FK 0 |
| apply#2（幂等） | **0 行**变更；撤销清单合并保留首次 old 值（修复了二次 apply 覆盖清单的 bug） |
| rollback | **102,988 行**恢复；单位内容 hash 与基线一致；products/components/单位分布 delta 全 0；quick ok / FK 0 |

> 说明：`ml→mL`（93,381 行）是**纯大小写规范化**，不改变语义；真正的同义单位变体约 8–9k 行（iu/ug/unit/meq 等）。任务里「11,880 行」来自审计的「非白名单单位」口径，与本次「可规范化文本行」口径不同，报告如实分列。

---

## 5. 真实库窗口步骤（并入 task-133）

1. **前置**：开窗备份（task-133 已有统一备份）。
2. 建议顺序：HK → EMA → CN inn_zh → CN trade → CN cleanup → **normalize_strength** → check_data / quick / FK → VACUUM。
   - 放在 CN 清洗后：清洗会删/标记部分 CN 行，归一化最后跑可覆盖剩余行；两者无字段冲突（cleanup 动 form_base/规格/批文，normalize 动 unit 文本）。
3. 命令：
   ```powershell
   & $py etl\normalize_strength.py --allow-real --manifest .tmp\strength-norm\normalize_manifest.json
   ```
4. 验数：`db/check_data.py`；`PRAGMA quick_check` / `foreign_key_check`；期望 products/components 不变、单位分布 97 种、flags 数量与副本一致。
5. **回滚**：
   - 数据级：`& $py etl\normalize_strength.py --rollback --allow-real --manifest .tmp\strength-norm\normalize_manifest.json`
   - 整库：恢复 task-133 窗口备份（schema 回滚走备份）。
6. 窗口后：build 任务按 flags 做展示规则（液体浓度、异常值、trade 名拆分）；不改变库内原文。

---

## 6. 风险 / 注意

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 单位文本变更量大（10 万行） | 只改文本、不改数值；撤销清单逐行 old/new；幂等/回滚已验证 |
| 2 | `ml→mL` 可能影响 build 现有单位文案/排序 | build 侧对单位展示用 `unitLabel` 兜底；本次不改 build；窗口后 smoke |
| 3 | 液体浓度无法从数据推断 | 只标记 + 页面规则；不写猜测值 |
| 4 | `万IU`、`mci/uci` 等特殊单位语义 | 保留原文/规范化文本，数值不换算；必要时源数据复核 |
| 5 | flag 的 `--mark-notes` 会改 product.note | 默认**关闭**；窗口建议只用 flags CSV/build 规则，不改 note |
| 6 | 真实库写入会与 task-133 其它步骤并发冲突 | 统一窗口串行执行，全窗口一个备份 |

---

## 7. 证据

| 文件 | 内容 |
|---|---|
| `.tmp/strength-norm/analyze.py` / `analyze.out.txt` | 液体无浓度分类、异常规格计数 |
| `.tmp/strength-norm/dryrun2.out.txt` | 102,988 行变更 + flags 统计 |
| `.tmp/strength-norm/flags.csv` | 全部 flags（liquid/invalid/extreme/trade-dose） |
| `.tmp/strength-norm/apply1b.out.txt` / `apply2b.out.txt` / `rollback2.out.txt` | apply / 幂等 / rollback 日志 |
| `.tmp/strength-norm/normalize_manifest.json` | 撤销清单（102,988 行 old/new） |
| `.tmp/strength-norm/verify.py` + `drugs.pristine.db` / `drugs.db` | 单位 hash/分布/FK/quick 前后对比 |

_本报告由并行子智能体 data-depth 生成；未写真实库、未改 build.py、未 git/发布。_
