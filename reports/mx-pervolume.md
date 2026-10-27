# MX per_volume 浓度挽回（task-33，dry-run + 副本验证）

> 日期：2026-10-27 ｜ 数据库：`data/drugs.db`（**只读**，本轮未写入；apply 只在 `.tmp/mx-pervolume/drugs-test.db` 副本验证）
> 产物：`data/mx_pervolume_candidates.csv`、`etl/ingest_mx_pervolume.py`、本报告；提取脚本与全部证据在 `.tmp/mx-pervolume/`。
> 背景：上轮 963 条 MX 浓度回填中 357 FAIL + 19 UNCERTAIN，其中相当一部分是「原文有明确基数（每 mL / 每 5 mL / 每瓶 / 每安瓿 / 每克），但 ETL 只取了第一个浓度、没写基数」，本轮用 `product_component.per_volume_*` 安全挽回。

---

## 1. 结论

1. **可安全挽回 125 条**（= 上轮 376 条 FAIL/UNCERTAIN 的 **33%**、963 条的 13%）：原文能明确解析出「数值 + 基数」，且通过剂型一致性检查。
2. MX 有浓度产品：**3,707 / 10,878 = 34.1% → 3,832 = 35.2%**（+1.1pp）；MX 有 `per_volume` 的产品：**0 → 125**（此前全库 MX 无任何 per_volume）。
3. 按基数：`per_ml` 39、`per_volume_ratio`（X mg / N ml）56、`per_container`（每瓶/每安瓿总量）26、`per_gram`（外用 mg/g）4。
   按剂型：liquid 93、injection 27、topical 4、powder（重建悬液）1。
4. **不再挽回的 43 条**：24 条是「固体产品套用了液体/注射原文」的放宽规则误配（营养/抗生素混悬液串到片剂/胶囊），19 条原文有多个互相矛盾的折算值——按「宁可缺不可错」全部排除。
5. 显示语义已验证：`lib/search.py::_fmt_strength` 本来就支持 per_volume（输出形如 `75 mg/3 ml`、`64 mg/100 g`），**不需要改站点代码**；apply 后即可在结果卡/成分页展示。
6. **apply 建议**：125 条都建议入；建议 Lead 先人工抽核 §4 的 9 条「many_numbers」（本次已逐条目检，均正确），然后备份库、加 `--allow-real` 跑正式 apply（脚本默认拒绝写真实库，是刻意的保护）。

---

## 2. 候选怎么来的（`data/mx_pervolume_candidates.csv`，168 行）

提取脚本：`.tmp/mx-pervolume/extract.py`（只读）。输入：
- 上轮审核结果：`reports/mx_strength_vetted.csv`（963 行，decision）+ `.tmp/mx-audit/audit_all.csv`（每条的 CC-BY 原文 `evidence_text`）；
- 候选池 = `decision ∈ {FAIL, UNCERTAIN}` 的 **376 条**（已有 584 条 PASS 已在库中，不重复处理）。

解析规则（按优先级；命中后统一做唯一性检查）：

| 规则 | 语境 | 例子 | 输出（strength / per_volume） |
|---|---|---|---|
| R1 ratio | `X mg / N ml`、`X mg en N ml` | `Ranibizumab 2.3 mg ... 0.23 ml` | 2.3 mg / 0.23 ml |
| R2 cada_ml | `cada [N] ml contiene(n): X mg` | `Cada 5 mL de suspensión contienen: Cefixima 100 mg` | 100 mg / 5 ml |
| R3 cada_container | `cada frasco/ampolleta contiene X mg ... N ml` | `Cada ampolleta contiene: Diclofenaco sódico 75 mg ... 3 ml` | 75 mg / 3 ml |
| R4 cada_g | `cada [N] gramos contiene X mg` | `Cada 100 gramos contiene: Dipropionato de betametasona 64 mg` | 64 mg / 100 g |
| R5 total_bottle | `X g env N ml`（整瓶总量） | `claritromicina, suspension 2.5g env 60ml` | 2.5 g / 60 ml |

排除/降级：
- **剂型误配**（24 条）：产品是 tablet/capsule，但原文是「Suspensión oral / Solución inyectable」→ 上轮放宽规则的串行，不能当该产品浓度；
- **多值冲突**（19 条）：同一原文解析出多个不同 strength/basis；
- **low confidence**（27 条，与上面部分重叠）：折算不确定，只留在 CSV 里供人工看，不自动 apply。
- 其余字段：`write_ok`（yes/no）、`exclude_reason`、`risk_flags`、`evidence_datasets`、`evidence_url`（CC-BY 数据集资源页）、`evidence_text`（≤600 字原文）。

用 `write_ok=yes` 且 `confidence ∈ {high, medium}` 得到 **125 条**。

---

## 3. 125 条的分布

| 维度 | 分布 |
|---|---|
| 基数类型 | per_volume_ratio 56 · per_ml 39 · per_container 26 · per_gram 4 |
| 剂型 | liquid 93 · injection 27 · topical 4 · powder 1 |
| 置信度 | high 105 · medium 20 |
| 风险标记 | `per_container` 26（显示为「每瓶总量/每瓶体积」）· `text_mentions_other_form` 41（原文提到 suspensión/emulsión 等，属正常语境）· `many_numbers` 9（原文数字多，已人工目检）· `per_gram` 4 · `reconstituted` 1（粉末重建后浓度） |

**抽样 20 条**（完整 125 条见 `.tmp/mx-pervolume/pervolume_dryrun.json`）：

| # | product_id | 剂型 | 原文 | 折算 | 基数类型 |
|---:|---|---|---|---|---|
| 1 | MX-005M2004 | injection | 100 mg | 100 mg / 2 ml | per_volume_ratio |
| 2 | MX-051M2002 | injection | 60 mg | 60 mg / 2 ml | per_container |
| 3 | MX-052M2007 | injection | 2.3 mg | 2.3 mg / 0.23 ml | per_volume_ratio |
| 4 | MX-065M2005 | injection | 500 IU | 500 iu / 10 ml | per_container |
| 5 | MX-097M2005 | injection | 100 mg | 100 mg / 4 ml | per_container |
| 6 | MX-109M2008 | injection | 75 mg | 75 mg / 3 ml | per_container |
| 7 | MX-119M2001 | injection | 100 IU | 100 iu / 1 ml | per_ml |
| 8 | MX-174M2001 | injection | 160 mg | 160 mg / 100 ml | per_ml |
| 9 | MX-182M2006 | injection | 12 mg | 12 mg / 1.2 ml | per_volume_ratio |
| 10 | MX-198M2002 | injection | 500 IU | 500 iu / 10 ml | per_container |
| 11 | MX-235M2001 | injection | 100 mg | 100 mg / 2 ml | per_volume_ratio |
| 12 | MX-274M2007 | injection | 100 IU | 100 iu / 1 ml | per_ml |
| 13 | MX-281M2006 | injection | 250 mg | 250 mg / 5 ml | per_volume_ratio |
| 14 | MX-537M2002 | injection | 300 mg | 300 mg / 20 ml | per_container |
| 15 | MX-003M2009 | liquid | 50 mcg | 50 mcg / 1 ml | per_ml |
| 16 | MX-017M2021 | liquid | 500 mg | 500 mg / 50 ml | per_volume_ratio |
| 17 | MX-073M2020 | liquid | 10 mg | 10 mg / 1 ml | per_ml |
| 18 | MX-163M2022 | liquid | 2500 mg | 2.5 g / 60 ml | per_container |
| 19 | MX-169M2007 | topical | 5 mg | 5 mg / 1 g | per_gram |
| 20 | MX-294M2007 | topical | 64 mg | 64 mg / 100 g | per_gram |

> 典型修正：`Claritromicina 2500 mg`（上轮 FAIL，按每瓶总量）→ **2.5 g / 60 ml**；
> `Atropina 10 mg` → **10 mg / 1 ml**；`Diclofenac 75 mg` → **75 mg / 3 ml**；
> `Ranibizumab 2.3 mg` → **2.3 mg / 0.23 ml**；`Betametasona 64 mg` → **64 mg / 100 g**。

---

## 4. 风险与需人工确认的点

1. **`per_container`（26 条）**：写的是「每瓶/每安瓿总量」，展示成 `75 mg/3 ml`、`500 iu/10 ml`、`2.5 g/60 ml`。这类是标签原样（多数注射液/口服混悬液就是这么标示），**不应当作「每 mL 浓度」去和别的市场做等量比较**；站点展示时建议保持「/瓶体积」的写法（`_fmt_strength` 已经是这个语义）。若未来做 D2 浓度比较，需要再折算。
2. **`per_gram`（4 条）**：`per_volume_unit='g'` 的展示在 `_fmt_strength` 里是 `64 mg/100 g`，语义正确；但 schema 注释写「液体另存 per_volume」——**g 基数属扩展用法**，建议在数据字典里补一句（本轮未改 schema/文档）。
3. **`many_numbers`（9 条）**：已逐条目检，折算均正确：
   Ranibizumab 2.3 mg/0.23 ml、Insulina 100 IU/1 ml（×2）、Alemtuzumab 12 mg/1.2 ml、Diazoxide 300 mg/20 ml、Chloramphenicol 5 mg/g、Betamethasone 64 mg/100 g（×3）。
4. **`reconstituted`（1 条）**：Cefixima 干混悬 100 mg/5 ml —— 是「重建后混悬液浓度」，不是粉末本身；展示为 `100 mg/5 ml` 正确，但若用户拿粉末袋直接比对可能误解。
5. **单位/基数一致性**：`per_ml`（39）+ `per_volume_ratio`（56）都是真正的浓度；`per_container` 26 条本质是「每容器量」——**两者不能混用**（报告/查询要把它们分开统计）。
6. **许可**：数据来自 4 份 CC-BY-4.0 数据集（INPRFM/HGMGG/INER/SEMAR），可再发布，需署名 + 注明改编；`corroboration` 里逐条写 `url=数据集资源页` 与原文片段。

---

## 5. apply / 幂等 / rollback 副本实测

| 步骤 | 副本状态 | 结果 |
|---|---|---|
| 初始（`data/drugs.db` 副本） | MX 有浓度产品 3,707；per_volume 0 | 与真实库一致 |
| `--apply --db .tmp/mx-pervolume/drugs-test.db` | **3,832**；per_volume **125** | 写 125 组件 + 125 行 corroboration + 1 行 ingest_run |
| 再跑 `--apply` | 3,832；per_volume 125 | **写 0**（`already_strength` 125，幂等；不清空 apply 清单） |
| `--rollback` | **3,707；per_volume 0** | 125 条按清单还原，删除 corroboration / ingest_run |
| 真实库 `data/drugs.db` | 3,707；per_volume 0 | **未被写入**（mtime 未变；`ingest_run` / corroboration 均为 0） |

- `--apply/--rollback` 默认**拒绝写 `data/drugs.db`**；Lead 批准正式 apply 时加 `--allow-real`（先备份库）即可。
- 写入语义：`product_component.ord=0` 且 `strength_value IS NULL AND per_volume_value IS NULL` 才写；不覆盖任何已填浓度。

---

## 6. 下一步

| 优先级 | 动作 | 验收 |
|---|---|---|
| P0 | Lead 抽 10 条人工核对（重点 §4 的 `per_container`/`per_gram`） | 无错 → 批准 |
| P0 | 备份库 → `--apply --db data/drugs.db --allow-real` → `db/check_data.py` | MX 有浓度 3,707→3,832（35.2%）；per_volume 0→125；`ingest_run` 多 1 行 |
| P1 | 站点/README 口径更新（MX 35.2%，注明含 per_volume 折算） | 三处数字一致（Lead/发布轮） |
| P1 | 把「per_container 26 / per_ml 95 / per_gram 4」在查询/展示层分开（不要做等量比较） | `lib/search.py` / 站点文案 |
| P2 | 剩余 251 条 FAIL/UNCERTAIN（原 376−125）放弃：主要为剂型误配/多值冲突/缺基数，继续人工不划算 | 不再投入 |

---

## 7. 证据索引（`.tmp/mx-pervolume/`）

| 文件 | 内容 |
|---|---|
| `extract.py` / `extract.out.txt` | 候选提取逻辑与运行日志（168 候选 / 125 可写） |
| `pervolume_dryrun.json` / `.txt` | dry-run 全量（125 条明细、覆盖率、样例） |
| `apply1.out.txt` / `apply2.out.txt` / `rollback.out.txt` | 副本 apply（125）→ 幂等（0）→ rollback（125）实测 |
| `drugs-test.db` | apply 测试副本（450 MB，可删） |
| `check.py` / `probe.py` / `probe.out.txt` | 真实库 vs 副本计数核对、候选池盘点 |
| `data/mx_pervolume_candidates.csv`（仓库内） | 168 行候选（含 write_ok/exclude_reason/evidence） |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp/mx-pervolume/extract.py                       # → data/mx_pervolume_candidates.csv
& $py etl/ingest_mx_pervolume.py                          # dry-run（只读）
Copy-Item data/drugs.db .tmp/mx-pervolume/drugs-test.db -Force
& $py etl/ingest_mx_pervolume.py --apply --db .tmp/mx-pervolume/drugs-test.db
& $py etl/ingest_mx_pervolume.py --rollback --db .tmp/mx-pervolume/drugs-test.db
```

---

_本报告由并行子智能体 data-depth 生成；`data/drugs.db` 只读未写，未跑 git / 发布 / `site/build.py`。_
