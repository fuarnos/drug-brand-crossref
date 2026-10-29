# task-17：矩阵等价规格合并 + 原写法保留（代码完成，构建待 DB 窗口）

> 2026-10-29 ｜ `site/build.py` ｜ 未写 DB、未改数据、未构建。
> 前置：task-16 已完成写库（109,161 行 g/mcg/µg/kg → mg；0.12 g → 120 mg；身份零变化）。
> 原写法来源（稳定）：`data/sources/unit_normalization_20261030.csv`（109,161 行 changed 的 `product_id,ord,old_value,old_unit`，3.4 MB，进仓库）；
> `.tmp/unit-norm-mass/audit_real.csv` 仅兜底；两者都缺时构建直接 `RuntimeError`（不静默丢原记录）。

## 0. 结论

- 矩阵按**归一后的 (value, unit) + 剂型 + 释放机制**聚合：0.12 g 与 120 mg 合并为一行「120 mg」；不同剂型/释放/复方不合并，mg/mL/IU 等不同维度不合并。
- 行内小字「原记录：0.12 g」：从 task-16 审计 CSV 读原始写法，去重后最多 3 个 + N；多语 key `matrix.original`（Recorded as / Registrado como / 原记录 / 原紀錄）。
- 规格待核：换算后的合法 mg 值不再标 `data-suspect`；无单位/范围/异常值保持原逻辑。
- URL/筛选器：`data-spec` 同时包含归一显示 + 原记录，旧筛选词仍可命中；`mform/mrel/mspec` 行为不变。

## 1. 冒烟（orlistat）

```text
matrix rows 6
120 mg rows 2
0.12 g notes 2
orig blocks 2
row example:
<tr data-form="capsule" data-release="none"
    data-spec="120 mg 0.12 g 120 mg" data-suspect="0" data-freq="75">
<td class="m-spec"><b>120 mg
  <span class="m-orig"><span data-i18n="matrix.original">Recorded as</span>: 0.12 g</span>
</b><br>capsule</td> ...
```

- 奥利司他 0.12 g 与 120 mg 已合成同一行（同一剂型/释放），原记录小字可见。
- 仍保留 2 个 120 mg 行是不同剂型/释放组合，按需求不合并。
- `data-suspect=0`：换算后合法值不再标「规格待核」。

## 2. 代码点

| 位置 | 改动 |
|---|---|
| `_WEIGHT_TO_MG` / `_normalized_strength` | g/kg/mcg/ug/microgram/ng → mg（Decimal）；>100,000 mg 异常值不换算（task-16 跳过口径） |
| `_strength_raw_map` / `_raw_strength` | 优先读 `data/sources/unit_normalization_20261030.csv`（109,161 行，3.4 MB）；`.csv.gz` 兼容旧快照；`.tmp/unit-norm-mass/audit_real.csv` 兜底；都缺 → `RuntimeError` |
| `_strength_origin_html` | 去重、去掉与显示相同的写法，最多 3 个 + N |
| 矩阵聚合 key | `(归一显示串, form, release)`；原记录按 spec 聚合 set |
| 行渲染 | `m-spec` 内追加 `.m-orig`；`data-spec` 拼入原记录供筛选 |
| 四语 | `matrix.original` 四语 key；无 JS 可读 |

## 3. 复核命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m py_compile site/build.py
& $py .tmp/cat2/task17_smoke.py          # orlistat：120 mg + 原记录 0.12 g
```

## 4. 缺口 / 待办

- 全量构建后抽查：奥利司他页、西替利嗪页无重复规格、四语小字、筛选器/URL 不回归。
- 原记录快照已进仓库（`data/sources/unit_normalization_20261030.csv`，3.4 MB）；`.tmp` 只是兜底。缺快照时构建会报错，不会静默丢「原记录」。
- 未做名称页/结果行的规格原记录（本任务只要求矩阵）。
- **全量单包装名字页待做（下一版）**：见 `reports/matrix-columns-ondemand.md`；本版按 800MB 守卫用 CN/TW/ES/MX 子集。

## 5. 构建结果（2026-10-30，v0.9.0）

- `== done ==` exit 0，2.92 分钟；dist **116,883 文件 / 770,754,926 B（770.8 MB / 735.1 MiB）**；sitemap 68,430；页脚 v0.9.0。
- 构建后抽查 `site/dist/drug/orlistat.html`：**120 mg 合并行 + 「原记录：0.12 g」小字**通过；无「0.12 g」独立规格行。
- 原记录快照 `data/sources/unit_normalization_20261030.csv` 在构建期被优先读取（109,161 行），未报错。
- **未完成**：名称页/结果行的原记录未做（仅矩阵）；全量单包装名字页留待下一版。
