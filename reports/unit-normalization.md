# 单位归一 v1（重量 → mg，DB 层）— task-16

> 日期：2026-10-30（北京 00:02–00:40）｜任务：task-16（Lead 批准后执行）｜执行人：data-depth
> 结果：**已写真实库**，换算 **109,161 行**，跳过 **134,308 行**（全部计数、不猜）；产品/成分/名称/substance **零变化**；`check_data` 前后逐行一致；quick ok / FK 0。
> 脚本：`etl/normalize_units_mass.py`（新，dry-run 默认只读 + `--apply/--rollback` + Decimal + 撤销清单）
> 证据：`.tmp/unit-norm-mass/`（`audit_real.csv` 12 MB 逐行明细、`manifest.json` 5.1 MB 撤销清单、`check_data_before.txt` / `check_data_after.txt`）

---

## 0. 结论（先看这段）

| 项 | 结果 |
|---|---|
| 换算行数 | **109,161**：`g` 100,845 / `mcg` 4,752 / `ug` 2,124 / `microgram` 1,398 / `kg` 32 / `micrograms` 6 / `μg` 2 / `µg` 2（`ng` **0 行**，库内无此单位） |
| 单位维度 | `strength_unit` 取值 **131 → 125**（含 NULL；非 NULL 130 → 124）；重量维只剩 `mg` **399,938** + 异常未换算的 `g` **899** / `kg` **140** |
| 跳过 | **134,308 行**：无单位且无值 79,215、非重量单位 52,545、复合单位 1,507、换算后 >100,000 mg 1,037、非正值 2、缺单位 2 |
| 验收（0.12 g） | 库内 0.12 g 记录 **275 行全部 → 120 mg（剩 0 行）**；奥利司他 CN 92 行 `0.12 g` → `120 mg` |
| 身份不变 | products 431,555 / components 534,246 / name_keys 168,943 / names 607,317 / substances 12,649 / variants 14,249 **全部不变**；`product_id`、`name_variant`、`product_name`、`substance` 内容 sha256 与备份**完全一致** |
| 精确性 | 与备份逐行对比 534,246 行：**仅 109,161 行 strength 变化且全部变成 `mg`**；`per_volume` 变化 **0**；行身份不匹配 **0** |
| 完整性 | `db/check_data.py` 前后输出 **114 行逐行一致**（coverage/collisions/别名等全不变）；`quick_check=ok`、`foreign_key_check=0` |
| 体积 | 364,195,840 B → **366,137,344 B（+1,941,504 B，+0.53%）**；`page_count` 88,915 → 89,389；`freelist_count=0` → **未 VACUUM**（无可回收页，且此刻 impl-lazyload 在建站，避免抢排他锁） |
| 耗时 | dry-run 扫描 ~2s；apply **2.42s 事务 / 2.54s 墙钟**；rollback（副本验证）0.60–0.66s |
| 回滚 | `--rollback` 按 manifest 逐行还原（副本两轮验证后指纹逐字节回到 `3eba9993…`）；整库兜底 = 备份 |

---

## 1. 范围与规则（只动一个字段族）

只改 `product_component.strength_value / strength_unit`，**不动** product / 批文号 / 厂家 / 成分映射 / 名称表：

| 原单位（`strip().lower()`） | 因子 | 规则 | 本次行数 |
|---|---|---:|---|---:|
| `g` | ×1000 | g → mg | 100,845 |
| `kg` | ×1,000,000 | kg → mg | 32 |
| `mcg` / `ug` / `microgram` / `micrograms` / `μg` / `µg` | ×0.001 | 微克同义写法 → mg | 8,284 |
| `ng` | ×0.000001 | ng → mg | 0（库内无） |
| `mg` | 1 | 已是目标单位，no-op | 290,777 |

- 数值换算用 `decimal.Decimal(repr(float(value))) * Decimal(factor)`，再回写 float：不引入 `0.1+0.2` 类浮点误差；单位统一写成 `mg`。
- **`mcg` 一并换算**（任务字面只写 µg/ug）：`mcg` 就是微克的另一种写法，留 `mcg` 会导致「重量维只剩 mg」验收不成立；报告单列此项供复核。
- 幂等：换算后单位已是 `mg`，二次 `--apply` = **0 行**（副本实测）。

## 2. before / after（按单位）

| strength_unit | before | after | 说明 |
|---|---:|---:|---|
| `mg` | 290,777 | **399,938** | +109,161 |
| `g` | 101,744 | **899** | 剩余全部为「换算后 >100,000 mg」的异常值，未猜 |
| `kg` | 172 | **140** | 同上（>0.1 kg） |
| `ug` / `mcg` / `microgram` / `micrograms` / `μg` / `µg` | 2,124 / 4,752 / 1,398 / 6 / 2 / 2 | **0** | 全部 → mg |
| `ng` | 0 | 0 | 库内没有 |
| `<NULL>` | 79,217 | 79,217 | 无单位且无值，不动 |
| `%` / `ml` / `l` / `iu` / `unit` | 26,522 / 18,538 / 435 / 3,208 / 2,790 | 不变 | 第二批 |
| `mg/ml` / `g/l` / `mg/vial` / `mg/g` | 506 / 238 / 223 / 93 | 不变 | 复合单位，第二批 |

## 3. 换算明细（109,161）

**按国家**：CN 69,590 · US 25,622 · CA 6,073 · ES 2,503 · GB 2,293 · AU 2,018 · SG 606 · TW 244 · MX 214。

**样例 10 条**（完整逐行见 `.tmp/unit-norm-mass/audit_real.csv`）：

| product_id | ord | before | after |
|---|---:|---|---|
| `AU-10007Q-flutiform-125-5-81ccbf` | 0 | 125 microgram | 0.125 mg |
| `AU-10035E-nesina-met-12-5-1000-28696f` | 1 | 1 g | 1,000 mg |
| `AU-ARTG-409578-pulmicort-respules-500mcg-2ml` | 0 | 500 mcg | 0.5 mg |
| `CA-00240494` | 0 | 0.02665530303030303 kg | 26,655.30303030303 mg |
| `CN-XG03AAQ132A00-0fdb330e` | 1 | 30 μg | 0.03 mg |
| `CN-XG03AAQ132A00-4f4089db` | 1 | 30 µg | 0.03 mg |
| `SG-SIN14232P` | 0 | 5 micrograms | 0.005 mg |
| `CN-XA08ABA209A00-9b4539d5`（奥利司他） | 0 | **0.12 g** | **120 mg** |
| `CA-00783625` | 0 | 0.12 g | 120 mg |
| `US-87325-001` | 1 | 0.12 g | 120 mg |

## 4. 跳过清单（134,308 行，全部计数、不猜）

| 原因 | 行数 | 说明 / 明细 |
|---|---:|---|
| `no_unit_no_value`（无单位且无值） | 79,215 | `strength_unit` 与 `strength_value` 都空 |
| `not_mass`（非重量单位） | 52,545 | `%` 26,522、`ml` 18,538、`iu` 3,208、`unit` 2,790、`l` 435、`万iu` 255、`meq` 151、`u` 139、`mci` 101、`IU` 91、`units` 81… |
| `compound_unit`（复合/每剂单位） | 1,507 | `mg/ml` 506、`g/l` 238、`mg/vial` 223、`mg/g` 93、`mcg/ml` 52、`mcg/dose` 47、`g/vial` 35、`iu/ml` 34… |
| `abnormal_converted`（换算后 >100,000 mg） | 1,037 | `g` 897（如 3,350,100 g、400,064 g×22、400,013.125 g×2、24,200 g…）+ `kg` 140（1,306 kg、280 kg×5、145.6 kg×4…） |
| `non_positive`（0 / 负值） | 2 | `CN-XJ01DDT081B00-337879c9`、`…-dfec7b3b`（0 g） |
| `unit_missing`（有值无单位） | 2 | `ES-69850` ord 0/1（300、400，单位空） |
| **合计** | **134,308** | 与「components 534,246 − convert 109,161 − already_mg 290,777」一致 |

- **范围值 / 复方比例**：`strength_value` 是 REAL 列，库内不存在「5-10 mg」这类区间或「30/70」比例值（检测 = 0 行）；若未来出现，脚本的 `RANGE_RE` 会归入 `range_text` 并跳过。
- **阈值决定**：`--max-mg` 默认 100,000 mg（=100 g）。按此阈值 `g>100 g` 897 行、`kg>0.1 kg` 140 行被判异常不换算（含 CN Macrogol 源文本 `聚乙二醇400064g` 的真实脏数据，属 task-3 CN 清洗范围）。如需放宽（例如把 kg 全部换算，或阈值调到 1,000,000 mg），改一个参数重跑即可，无需改代码。

## 5. 验证（可复核）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 单位分布（期望 mg 399,938 / g 899 / kg 140；mcg/ug/microgram/μg/µg/ng = 0）
& $py db/q.py "SELECT strength_unit, COUNT(*) FROM product_component GROUP BY 1 ORDER BY 2 DESC LIMIT 12"

# 2) 0.12 g 归零（期望 0）+ 奥利司他 120 mg（期望 154 行）
& $py db/q.py "SELECT COUNT(*) FROM product_component WHERE strength_unit='g' AND strength_value=0.12"
& $py db/q.py "SELECT COUNT(*) FROM product_component pc JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id WHERE lower(s.inn_en)='orlistat' AND pc.strength_value=120 AND pc.strength_unit='mg'"

# 3) 计数/完整性
& $py db/check_data.py
& $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');print(c.execute('pragma quick_check').fetchone()[0], len(c.execute('pragma foreign_key_check').fetchall()))"
```

| 检查 | 结果 |
|---|---|
| 与备份逐行 diff（534,246 行） | 仅 **109,161** 行 strength 变化，全部新单位 = `mg`；`per_volume` 变化 0；行身份不匹配 0 |
| `product_id` 内容 sha256 | 备份 `50a8c4914a1bdbcd` = 现在 `50a8c4914a1bdbcd` |
| `name_variant` / `product_name` / `substance` 内容 sha256 | `d4be5f0641227c6c` / `6a692229725082a5` / `4021a76c8612a025`，与备份**全部一致** |
| `db/check_data.py` | 前后各 114 行，**逐行一致**（coverage 9 市场、collisions severe 19,386 等不变） |
| `quick_check` / `foreign_key_check` | `ok` / **0** |
| 体积 / VACUUM | 364,195,840 → 366,137,344 B；`freelist_count=0` → 不 VACUUM（无可回收页；增长来自行内更新后新页分配 + 部分 float 表示变长） |

## 6. 撤销清单 / 回滚 / 幂等

- 撤销清单：`.tmp/unit-norm-mass/manifest.json`（5.1 MB；`run_id=unit-mass-20261029T160543Z`；逐行 `product_id/ord/old_value/old_unit/new_value` + 因子表 + before/after 计数）
- 明细 CSV：`.tmp/unit-norm-mass/audit_real.csv`（12 MB，`kind=change/skip` + 原因）
- 回滚：
  ```powershell
  & $py etl\normalize_units_mass.py --rollback --allow-real --db data\drugs.db --manifest .tmp\unit-norm-mass\manifest.json
  ```
  整库兜底：`Copy-Item data\backups\drugs-before-unitnorm-20261030.db data\drugs.db`（sha256 `24692E636D6ECBB0852C413495B3B0F2245D5D8E9DAC45BE7F35AB297960C3E6`）
- 幂等：再跑 `--apply` 输出「没有可换算的行」。

## 7. 风险 / 交接

| # | 事项 | 影响 | 处理 |
|---|---|---|---|
| 1 | **12,207 行换算后 >10,000 mg（11,529 产品）** | `site/build.py` 的 `_strength_suspect()`（v0.8.4：`value > 10_000` 且单位不在 `u/iu/unit/units/%/ml` 白名单 → 标「规格待核」并排最后）会把它们误标 | **交给 task-17（展示合并）**：给 mg 加白名单/按 `form_base` 区分，或把阈值改成按剂型判断；数据侧不改 |
| 2 | `g` 剩 899 / `kg` 剩 140 | 重量维不是 100% 单一单位 | 全部是 >100,000 mg 的异常/大包装，按任务要求「不猜」；CN Macrogol 400064 g×22 等由 task-3 CN 清洗置 NULL，之后这批会更少 |
| 3 | `mcg` 一并换算 | 与任务字面（只写 µg/ug）略有超出 | 为满足「重量维只剩 mg」的验收；如需保留 `mcg` 写法可回滚单段重跑 |
| 4 | `per_volume_*` 未动 | 液体浓度（如 2 g/10 ml）里仍是 `g` | 第二批（task-3 的「第二批单位」统一做）；当前 `per_volume_unit`：`g` 12,609、`mg` 919、`kg` 98、`ug` 4、`ul` 8、`mcl` 5 |
| 5 | 复合单位 1,507 行未动 | `mg/ml`、`g/l`、`mg/vial`、`mcg/dose`… | 第二批；需要「分子分母同时归一」的规则，单独评估 |
| 6 | 其他非重量单位 | `IU`/`unit`/`mEq`/`%`/`mL`/`L`/`vg` 等 | 第二批；`ml/iu/ug` 的**文本**统一（`mL`/`IU`/`mcg`）此前在 `reports/strength-normalization-prep.md` 已备好脚本，仍待窗口执行 |
| 7 | 展示层未验证 | 矩阵/结果行的单位文案、排序、筛选 | 本任务禁改 build；由 task-17 与 v0.8.5 发布窗口验证（build 由 impl-lazyload 串行改，未跑 build/publish） |

## 8. 复现（新机器/复核）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Copy-Item data\drugs.db .tmp\unit-norm-mass\drugs.db
& $py etl\normalize_units_mass.py --db .tmp\unit-norm-mass\drugs.db --dry-run          # 只读计划
& $py etl\normalize_units_mass.py --db .tmp\unit-norm-mass\drugs.db --apply `
      --manifest .tmp\unit-norm-mass\manifest_copy.json --audit .tmp\unit-norm-mass\audit_copy.csv
& $py etl\normalize_units_mass.py --db .tmp\unit-norm-mass\drugs.db --rollback `
      --manifest .tmp\unit-norm-mass\manifest_copy.json
```

_本报告为 task-16 v1（重量单位）执行结果；未跑 build/publish、未改 schema、未开 task-3。第二批（IU/体积/百分比/复合单位/per_volume）与 DB 窗口一起等 Lead 放行。_
