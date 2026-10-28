# dose_warning 西语标题/正文补全（task-39）

> 日期：2026-10-27 ｜ 任务：`task-39` ｜ 纯 AI 翻译（无人工复核，发布前建议母语抽检）
> 产物：`data/seed_warnings.py`（ES_TRANSLATIONS + 41 条字段）、`etl/add_warning_es.py`、本报告、`.tmp/warn-es/` 证据
> 边界：真实库 `data/drugs.db` **未被写入**（apply/rollback 只在 `.tmp/warn-es/test.db` 副本验证）；未跑 git / 发布 / `site/build.py`。

## 0. 结论

| 项 | 结果 |
|---|---|
| 翻译条数 | **41 / 41**（40 published + 1 draft，`tainuo-vs-tainuolin` 也一并翻译，便于日后 promote 不留空） |
| 字段 | 每条 `title_es` + `body_es`；`etl/add_warning_es.py` **只更新这两列 + updated_at**，不动 status/其他列 |
| 长度 | title_es 41–101 字符（均值 76.8）；body_es 158–293（均值 220.4），约为英文正文 1.33×（西语正常膨胀） |
| 数字一致性 | 41/41 与英文段数字 token 完全一致（含 50 mg、97.25 %、0.721、2:1…14:1、U-100/U-500、24 小时等） |
| 库内现状 | title_es/body_es 41 条全 NULL → apply 后 41/41 非空；status 保持 published 40 / draft 1 |
| 副本验证 | **27/27 断言 PASS**：dry-run 不改库、apply 41 行、二次 apply 幂等（0 行）、rollback 41 行恢复 NULL、重放复现、`integrity_check=ok`；真实库只读核对仍 es 全空 |
| 回滚 | `.tmp/warn-es/backups/rollback_warning_es_*.csv`（before/after + NULL 哨兵），只还原仍等于 apply 后值的行 |

## 1. 实现方式（种子为唯一真相源）

1. **`data/seed_warnings.py`**：新增 `ES_TRANSLATIONS: dict[warning_id, (title_es, body_es)]`，
   在 41 条 `WARNINGS` 定义之后统一回填 `title_es/body_es`。这样 `seed_warnings.py --apply`
   （全量重建）不会丢西语，也不会出现「库里有、种子重建就回退」的双源漂移。
2. **`etl/add_warning_es.py`**：从种子导入译文 → 读 `dose_warning` 现值 → 只对差异行
   `UPDATE title_es, body_es, updated_at`；事务提交；apply 前备份旧值 CSV；rollback 按
   `(warning_id, after)` 安全还原；`--verify` 打印 es 覆盖率。
3. **自检**（脚本内 `validate_translations()`，dry-run 前强制跑）：
   - 41 条 id 唯一、es 非空、title ≤200 / body ≤900 字符；
   - **数字 token 与英文段一致**（`97.25%` ↔ `97,25 %` 视为一致）；
   - 无连续空格、无「吃几片/片/次」等用药建议措辞。
4. 命令：`python etl/add_warning_es.py --dry-run`（默认）/ `--apply --db PATH` /
   `--rollback --db PATH` / `--verify --db PATH`；真实库 apply/rollback 需 `--confirm-real-db`。

## 2. 术语表（zh / en / es）

| 中文 | English | Español | 使用次数 |
|---|---|---|---|
| 速释 | immediate-release (IR) | **liberación inmediata** | 17 |
| 缓释/控释 | extended-release (ER/XR) | **liberación prolongada** / controlada | 14 |
| 长效 | long-acting | acción prolongada / acción larga | 2 |
| 不可互换 | not interchangeable | **no son intercambiables** | 20 |
| 毫克对毫克 | milligram-for-milligram | **miligramo por miligramo** | 6 |
| 盐型 | salt form | **forma salina** | 7 |
| 碱基 | base | **base**（base libre） | 15 |
| 标示强度/强度基准 | label strength / strength basis | **concentración declarada / base de concentración** | 全篇 |
| 碱基系数/折算系数 | base fraction | **fracción de base** | 3 |
| 治疗窗窄 | narrow therapeutic index | **índice terapéutico estrecho** | 11 |
| 血药浓度监测 | monitor levels | **monitorizar niveles / monitorización de niveles** | 6 |
| 谷浓度 | trough level | concentración valle | 2 |
| 前药 | prodrug | **profármaco** | 2 |
| 复方 / 单方 | combination / single-ingredient | **combinado / único principio activo** | 5 |
| 爆发痛/按需镇痛 | breakthrough pain | **dolor irruptivo** | 1 |
| 撤药性反跳 | rebound withdrawal | **hipertensión de rebote** | 1 |
| 「开-关」现象 | on-off phenomenon | **fenómeno on-off** | 1 |
| 外消旋比例 | racemate composition | proporción de enantiómeros | 1 |
| 吸入（每次） | per actuation | **por inhalación** | 1 |
| 单位数 | unit counts | **número de unidades** | 1 |
| 抗 Xa/IIa 活性 | anti-Xa/IIa activity | **actividad anti-Xa/anti-IIa** | 1 |

成分名（保留 INN/通用名，首次出现带英文括注者由英文段沿用）：paracetamol (acetaminofén)、pseudoefedrina、dextrometorfano、clorfenamina、difenhidramina、acrivastina、fenilefrina、alginato de sodio、bicarbonato de sodio、carbonato de calcio、amoxicilina/clavulanato、metoprolol tartrato/succinato、levotiroxina、aminofilina、teofilina、morfina、oxicodona、nifedipino、diltiazem、verapamilo、carbamazepina、ácido valproico/valproato/divalproato、metilfenidato、venlafaxina、bupropión、metformina、clonidina、quetiapina、levodopa/carbidopa、amlodipino besilato、atorvastatina cálcica、omeprazol magnésico、fenitoína sódica、salbutamol (albuterol)、clindamicina、dexametasona、hidrocortisona、eritromicina、warfarina、digoxina、litio、tacrolimús、ciclosporina、insulina、heparina。

## 3. 样例（5 条，完整 title_es / body_es）

**1) `tylenol-vs-tainuo`（R4 high）**
- title_es: `Tylenol y 泰诺 (Tai Nuo) no son el mismo medicamento`
- body_es: `En Estados Unidos, Tylenol suele ser paracetamol (acetaminofén) como único principio activo. En China, 泰诺 es un antigripal combinado (paracetamol + pseudoefedrina + dextrometorfano + clorfenamina). El mismo nombre no significa los mismos principios activos.`

**2) `benadryl-us-vs-uk`（R4 high）**
- title_es: `Benadryl tiene principios activos diferentes en EE. UU. y el Reino Unido`
- body_es: `En EE. UU., Benadryl es principalmente difenhidramina; en el Reino Unido, Benadryl Allergy Relief es acrivastina 8 mg. Antes de comprar el mismo nombre en otro país, revise los principios activos.`

**3) `metoprolol-tartrate-vs-succinate`（R2 high）**
- title_es: `El metoprolol tartrato y el metoprolol succinato no son intercambiables miligramo por miligramo`
- body_es: `Son formas salinas distintas y, con frecuencia, mecanismos de liberación distintos (tartrato de liberación inmediata, succinato de liberación prolongada). La base de la concentración declarada también difiere; no cambie 50 mg por 50 mg. Cualquier cambio debe ser evaluado por el médico.`

**4) `levothyroxine-sodium-vs-base`（R6 high）**
- title_es: `La levotiroxina sódica no equivale a la base de levotiroxina`
- body_es: `Índice terapéutico estrecho. Que la concentración declarada se exprese como sal sódica o como base cambia la conversión (la sal sódica contiene ≈ 97,25 % de base), y la base empleada varía entre productos. Cualquier ajuste de dosis requiere control clínico, no una simple operación aritmética.`

**5) `gaviscon-us-vs-uk`（R4 high）**
- title_es: `Las formulaciones de Gaviscon difieren entre EE. UU., el Reino Unido y España`
- body_es: `En EE. UU., Gaviscon suele ser hidróxido de aluminio + carbonato de magnesio; las versiones del Reino Unido y España usan alginato de sodio + bicarbonato de sodio + carbonato de calcio. Misma marca, formulación distinta: cambian el mecanismo antiácido y la carga de sodio.`

## 4. 风险与待确认（纯 AI 翻译，无人工复核）

1. **需母语抽检**：本次为 AI 翻译 + 术语表约束，未做人类母语审校。建议上线前由西语母语者抽检 **5–10 条**，重点：R6 治疗窗窄/高警示条目、含数字折算的 R2 条目。
2. **ES/MX 用词差异**：已尽量取两者通用写法（`paracetamol (acetaminofén)`、`ficha técnica`、`comprimidos`），但西班牙常用「prospecto」、墨西哥常用「tableta」等，不影响事实但影响语感。
3. **医学术语选择**：`liberación prolongada` 覆盖 ER/XR/SR；`concentración declarada` 对应「标示强度」；`forma salina` 对应「盐型」；若建站方已有西语 UI 术语表，应以此为准做一次统一。
4. **不新增断言**：译文严格对应英文/中文段，未加任何剂量建议或新医学结论；`no cambie 50 mg por 50 mg` 是「禁止等量替换」的警示，不是给药建议。
5. **回退机制**：apply 后 41/41 有西语；若发现译文问题，`--rollback` 可恢复 NULL（`/warn` 页会回到英文 + (EN) 标记），修正种子后重跑即可。
6. **db 并发**：另一任务可能同时在写 `dose_warning.status`（warn 核验 apply）。本脚本只 UPDATE `title_es/body_es/updated_at`，不覆盖 status；建议 Lead 把两个 apply 串行执行。

## 5. 副本验证（真实库未写）

`.tmp/warn-es/test.db`（`data/drugs.db` 拷贝）：

| 步骤 | 结果 |
|---|---|
| 初始 | 41 行；es 覆盖 0；status published 40 / draft 1 |
| dry-run | 计划 41 行；不改库（es 仍 0） |
| apply | es 41/41；**只有 title_es/body_es/updated_at 变化**（逐列 diff 断言）；status 不变；中英文列不变 |
| 二次 apply | `计划更新 0 行`（幂等） |
| rollback | es 恢复 0/41；status 不变 |
| 重放 | es 41/41 |
| verify | `title_es+body_es 非空 : 41/41`（published 40 / draft 1 均翻译） |
| integrity / FK | `integrity_check=ok`；FK 有历史既有 `ingest_run 32→source 0`（验证前后一致，非本次引入） |
| 真实库只读 | es 仍全空、status 仍 40/1（未被写） |

断言 **27/27 PASS**；日志 `.tmp/warn-es/validation.log`，验证脚本 `.tmp/warn-es/run_validation.py`（可复跑）。

## 6. 给 Lead 的 apply 建议

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 0) 备份 + 确认 warn-verify 的 status apply 已完成/串行
Copy-Item data\drugs.db data\backups\drugs.db.bak-20261027-warn-es
# 1) 预览
& $py etl/add_warning_es.py --dry-run          # 预期 本次将更新 : 41 行
# 2) 写入（真实库需 --confirm-real-db）
& $py etl/add_warning_es.py --apply --db data\drugs.db --confirm-real-db
# 3) 核对
& $py etl/add_warning_es.py --verify --db data\drugs.db   # title_es+body_es 非空 : 41/41
# 4) 如需回滚
& $py etl/add_warning_es.py --rollback --db data\drugs.db --confirm-real-db
```

- 该脚本**不改 status**，与 task-35 的 `verify_warnings.py --apply` 互不覆盖；建议先 status 后 es（或反之）串行。
- `/warn` 页接西语时：apply 后 es 非空，页面可按语言取 `title_es/body_es`，不再回退英文、不必显示 `(EN)`；仍建议保留「无译文时回退英文」的兜底逻辑。

## 7. 证据索引（`.tmp/warn-es/`）

| 文件 | 内容 |
|---|---|
| `source_texts.txt` / `warnings.json` | 41 条种子中英文原文快照（翻译输入） |
| `validation.log` | 副本验证全过程（27/27 PASS） |
| `run_validation.py` | 验证脚本（copy → dry-run → apply → 幂等 → rollback → 重放 → integrity） |
| `stats.py` | 长度、术语计数、数字一致性统计 |
| `backups/` | rollback CSV（before/after，NULL 用 `\N` 哨兵） |

_本报告为只读核验 + 副本验证产物：未写 `data/drugs.db`、未改 `site/build.py`、未跑 git / 发布。_
