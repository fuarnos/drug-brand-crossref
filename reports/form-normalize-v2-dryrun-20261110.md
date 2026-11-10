# 剂型 / 释放机制归一化 v2（task-7）· dry-run 交付

> 日期：2026-11-10 ｜ 状态：**只读 dry-run**（`data/drugs.db` 一个字节没动、未跑 `site/build.py`、未 commit、未发布）
> 触发：`reports/consistency-audit-form-20261110.md`（R1 剂型族 / R2 回退成原文整串 / R3 释放机制）
> ＋`reports/form-effervescent-20261110.md`（新增 `effervescent` 类，948 行；用户报的「力度伸显示片剂」）
> 产物：`etl/normalize_form_v2.py`（迁移脚本，`--dry-run` / `--apply` / `--rollback`）、`etl/test_form_base.py`（21 项单测）、本报告
> 演练库：`.tmp/task7/copy.db`（`data/drugs.db` 的副本，AGENTS §9 不入库）

---

## 0. 结论

**一句话**：四条规则一共 **23,890 行**（占 477,098 的 5.0%），全部由来源原文派生、无人工标注；**泡腾 948 行达标、注射剂/粉剂误判按审计口径归零、AU/SG 释放机制冲突归零、R2 回退归零**；副本上 apply → 审计 R1 冲突 20,188→463（−97.7%）→ 幂等 0 行 → 回滚逐行恢复，正式库等批准。

| 验收项 | 预期 | dry-run（投影） | 副本实测（apply 后） |
|---|---|---:|---:|
| `effervescent` 最终条数 | 948 | **948** | **948** ✅ |
| 注射剂误判剩余（族口径） | 0 | **0** | **0** ✅ |
| 粉剂误判剩余（族口径：原文粉剂 + `form_base='liquid'`） | 0 | **0** | **0** ✅ |
| 粉剂族其余冲突（不在液体系列） | —— | 50 | 50（原因见 §3.3） |
| AU/SG `release='none'` 与原文冲突剩余 | 0 | **0** | **0** ✅ |
| 审计 R2「回退成原文整串」 | <100 | —— | **2,187 → 0** ✅ |
| 审计 R1 硬冲突 | —— | —— | **20,188 → 463**（−97.7%） |
| 审计 `effervescent` 族 | conflict 0 / gap 0 | —— | **ok 947 / conflict 0 / gap 0** ✅ |
| 下游：name_key / 成分页 / 矩阵拆分行 / 单包装页 | 806 / 204 / 145 / 484 | **806 / 204 / 145 / 480** | —— |
| 四套测试 | 绿 | etl 46 / lib 59 / mobile 29 OK，三语 69/72（历史基线） | —— |

**没有 apply**。等 Lead 批准后执行 §8 的 5 步。

---

## 1. 改了什么

### 1.1 ETL（一次改完，下次重跑 ingest 不会退回）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `etl/ingest_openfda_ndc.py` | `FORM_BASES` **顺序**：`liquid` 从第 3 位移到**最后**（`injection` / `powder` 因此先命中）；首行新增 `("effervescent", EFFERVESCENT_KEYS)`；词表补复数与西语（`suppositor` / `pessar` / `ovul` / `perlas` / `dressing` / `nail lacquer` / `scalp application` / `polvo` / `granulado` / `sobre` / `linctus` / `irrigant` / `dialisis` / `semisolido` / `barniz` / `laca` / `adhesivo` / `intravesical` …）；兜底**不再返回原文整串**（占位词→`unknown`、单值剂型名→原样、其余→`other`）；`release_of()` 扩成 ER / DR 双词表（`controlled` / `prolonged` / `modified` / `retard` / `liberación prolongada` / `肠溶` / 短码 `ER/XR/SR/MR/CR` …），并接受附加文本 |
| 2 | `etl/ingest_artg_medicines.py` | 自己的 `FORM_BASE` 同步顺序 + 泡腾；`release` 从**写死 `'none'`** 改为 `release_of(剂型原文)` |
| 3 | `etl/ingest_artg_details.py` | 同上：`release='none'` → `release_of(...)` |
| 4 | `etl/ingest_pbs.py` | 删掉自带的 `RELEASE_WORDS`（只认 `modified/extended/…release` + 短码，漏 `enteric coated`），改用共享 `release_of()` |
| 5 | `etl/ingest_tw_tfda.py` | `FORM_MAP` 首行加 `("effervescent", ("發泡","发泡","泡騰","泡腾","fizzy"))`（`發泡錠` 含「錠」、`發泡顆粒劑` 含「顆粒」，不排第一永远改不出来）；`injection` 词表补 `靜脈/静脉/輸注/输注`（TW 5 行 `靜脈輸注液` 原先落 liquid） |
| 6 | `etl/ingest_nhsa.py` | `FORM_ZH_EN` 首行加 `("泡腾","effervescent")` / `("泡騰","effervescent")`（`片剂(泡腾)` 里「片」原本先命中） |
| 7 | `etl/ingest_mx.py` | `FORM_BASES` 首行加泡腾；`SOLID_BASES` 加 `effervescent`；兜底改走共享 `form_base_of()`（不再把 `chicle`/`perlas` 塞进 `form_base`） |
| 8 | `etl/cleanup_cn_data.py` | `CANON_FORMS` 加 `effervescent`（否则下次 CN 清洗会把新值当长尾重写） |
| 9 | `etl/build_translation_tables.py` | `EXTRA_FORMS` 加 `("effervescent", …, "efervescente", "泡腾剂", "泡騰劑", …)`（**快照未重生成**，见 §7） |
| 10 | `db/consistency_audit_form.py` | `effervescent` 族 `ok={"effervescent"}`（原先 `ok=∅`，改后若不改它会报 948 条 conflict）；`CANON_BASES` 同步。**其余 21 族判据一行未动** |
| 11 | `db/schema.sql` | `form_base` 注释补 `effervescent`（无 DDL 变化，`init_db.py` 不用改） |

判定谓词**只有一套**：迁移脚本 `import` 入库用的 `form_base_of` / `release_of` 和审计的 `is_unmapped` / `classify` / `RE_ER` / `RE_DR`，脚本自己**不写正则**（这是第 6 个调用点，不是第 6 套规则）。

### 1.2 迁移脚本 `etl/normalize_form_v2.py`

- `--dry-run`（默认，`mode=ro` 只读）/ `--apply`（自动备份 + journal CSV + 单事务）/ `--rollback`（按 journal 反向恢复，逐行带 old/new 守卫，幂等）；
- 每条 `UPDATE … WHERE product_id=? AND <field>=<old>`，`rowcount != 1` 立即回滚并报错（不会静默改错行）；
- 写真实库要 `--allow-real`（沿用 `cleanup_cn_data.py` / `ingest_artg_medicines.py` 的护栏）；
- 回滚点 `data/backups/drugs-before-normalize-v2-<run_id>.db`，journal `data/backups/form-normalization-v2-journal-<run_id>.csv`（与备份同一份回滚资产，AGENTS §9 不入库；**若 Lead 要求进仓库**，加 `--journal data/sources/…`）。

### 1.3 单测 `etl/test_form_base.py`（新增 21 项）

`FORM_BASES` 顺序（`injection, solution`→injection、`Powder For Solution`→powder、`injection, powder`→injection、`liquid` 必须最后）、泡腾 7 种拼写 × 4 条来源语言分叉（cima/tw/nhsa/mx）、`release_of` 的 ER/DR/西语/短码、兜底不返回原文（断言输出无空格无数字）、占位词→unknown、单值剂型名原样保留。
`etl` 套件 25 → **46 项**，全绿（此前 `form_base_of` 零覆盖）。

---

## 2. 四条规则的数字（dry-run，`& $py etl/normalize_form_v2.py`）

### 2.1 总量

| 规则 | 内容 | 行数 |
|---|---|---:|
| `FORM-EFF` | 原文写泡腾 → `form_base='effervescent'` | **948** |
| `FORM-ORDER` | 原文写注射剂/粉剂而 `form_base='liquid'` → `injection` / `powder` | **18,875** |
| `FORM-FALLBACK` | `form_base` 回退成原文整串 → 词表能认的落具体类，认不出落 `other` | **2,187** |
| `RELEASE` | 原文写缓释/肠溶而 `release='none'` → `ER` / `DR` | **1,880** |
| **合计** | | **23,890** |

### 2.2 `FORM-EFF` 948 行

改前 → 改后：`tablet` 828 ｜ `powder` 92 ｜ `liquid` 28 → 全部 `effervescent`

| 市场 | GB | AU | US | ES | CN | CA | TW | MX | SG |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 行数 | 256 | 231 | 139 | 125 | 107 | 41 | **28** | 12 | 9 |

| 来源 | dmd | artg_export | openfda_ndc | cima | nhsa | hc_dpd | artg_detail | tfda_tw | cofepris_mx | hsa_sg | pbs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 行数 | 256 | 193 | 139 | 125 | 107 | 41 | 37 | **28** | 12 | 9 | 1 |

> TW 的 28 行（`發泡錠` 20 / `發泡顆粒劑` 8）是这次必须改 `ingest_tw_tfda.py` 的原因：不改 `FORM_MAP` 顺序，`錠`/`顆粒` 永远先命中。

### 2.3 `FORM-ORDER` 18,875 行

| 改前 → 改后 | 行数 | GB | US | CA | SG | AU | TW | ES |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `liquid` → `injection` | **15,570** | 8,289 | 6,114 | 0 | 1,151 | 4 | 7 | 5 |
| `liquid` → `powder` | **3,305** | 164 | 858 | 1,912 | 64 | 307 | 0 | 0 |

| 来源 | dmd | openfda_ndc | hc_dpd | hsa_sg | artg_export | pbs | tfda_tw | cima | artg_enrich | artg_detail |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 行数 | 8,453 | 6,972 | 1,912 | 1,215 | 181 | 124 | 7 | 5 | 3 | 3 |

> 注射剂 15,570 与审计报告 R1 的 `injection → liquid` **完全一致**（审计报告 §Top10 里「GB 8,589 / US 6,114 / SG 1,151」的分项加总为 15,854，与它的总数 15,570 不自洽；本表按市场现查加总 15,570，以本表为准）。
> 粉剂 3,305 比审计的 3,304 多 1 行：`Posaconazole … gastro-resistant powder and solvent for oral suspension`，审计父族判「肠溶」，但肠溶族的 ok 集合含 `powder`，所以按 powder 改。

### 2.4 `FORM-FALLBACK` 2,187 行（与审计 R2 逐行对齐）

- **1,292 行**落回具体类：suppository 421（`… suppositories` / `… pessaries`）、topical 194、liquid 146、mouthwash 115、film 92、powder 75、implant 41、gum 41、kit 35、plaster 32、oil 25、device 20、pastille 15 …
- **895 行 → `other`**（词表认不出，按纪律丢弃并计数）：`system` 26、`chicle` 26、`nitrous oxide 50% / oxygen 50%` 22、`insert` 19、`pulverizacion bucal` 19、`dispositivo vaginal` 16、`implante` 16、`disc` 13、`bar, chewable` 13、`wafer` 13 …
- **0 行**把原文整串留在 `form_base` 里（脚本断言：输出不含空格/数字）。

| 市场 | GB | ES | US | CA | AU | MX | SG |
|---|---:|---:|---:|---:|---:|---:|---:|
| 行数 | 1,533 | 213 | 187 | 151 | 59 | 39 | 5 |

| 来源 | dmd | cima | openfda_ndc | hc_dpd | cofepris_mx | pbs | artg_detail | artg_enrich | hsa_sg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 行数 | 1,533 | 213 | 187 | 151 | 39 | 37 | 16 | 6 | 5 |

### 2.5 `RELEASE` 1,880 行

`none` → `ER` **1,182** ｜ `none` → `DR` **698**

| 市场 | AU | SG | CA |
|---|---:|---:|---:|
| 行数 | 1,820 | 54 | 6 |

| 来源 | artg_export | pbs | hsa_sg | artg_detail | artg_enrich | hc_dpd |
|---|---:|---:|---:|---:|---:|---:|
| 行数 | 1,633 | 161 | 54 | 18 | 8 | 6 |

改后 `release` 分布：`DR` 9,289 ｜ `ER` 17,066 ｜ `MR` 191 ｜ `none` 450,552（改前 `none` 452,432）。
**反向类不动**：`release` 有值但原文没有释放词 8,392 行（CN 5,985 / ES 2,151…）保持原样——那是「按商品名推的」，属显示层要标注依据，不在本规则内。

---

## 3. 改后复核（投影状态，尚未写库）

### 3.1 四条验收式

```
effervescent 条数：948（预期 948）
注射剂误判剩余（审计族判 injection、form_base 仍 liquid）：0
粉剂误判剩余（审计族判 powder、form_base 仍 liquid）：0
AU/SG release='none' 与原文冲突剩余：0
```

### 3.2 「族口径」与「关键词口径」的差别（为什么要留 301 + 204 行）

规则里加了一道**审计族闸门**（`family_accepts()`）：只有当审计把该行的原文判成 injection/powder 族、且新值在该族的 ok 集合里时才改。这样迁移**不会把一条审计判「不算错」的行改成冲突**。

| 口径 | 注射剂 | 粉剂 | 说明 |
|---|---:|---:|---|
| 审计族口径（验收式） | **0** | **0** | 审计报告的口径，已归零 |
| 关键词口径（原文含字样） | 301 | 204 | 闸门挡下来的，明细见下 |

- **301 行「原文含注射词但留 liquid」**：`… nebuliser liquid unit dose vials` 等，审计判**吸入族** 286 / 眼用 11 / 植入 3 / 鼻用 1 —— 改成 injection 会给审计**新增 301 条冲突**（吸入族不认 injection），所以保留 liquid（审计判 coarse，不算错）。
- **204 行「原文含粉剂词但留 liquid」**：CA `Kit; Powder For Solution` 等试剂盒 199 行（审计判 kit 族 gap）、栓剂族 4、外用族 1 —— 试剂盒该有自己的类（`kit`），本轮没有把 `kit` 加进 `FORM_BASES`（不在 task-7 的四条规则里）。

### 3.3 粉剂族剩余 50 条冲突（不在「液体系列」，本轮不动）

| 条数 | 当前 `form_base` | 样例 | 原因 |
|---:|---|---|---|
| 35 | `capsule` | GB/CA `Hydrocortisone 5mg granules in capsules for opening` | 原文同时写 granules 与 capsules，`capsule` 关键词先命中；属「哪个词更主」的判断，不做机械改 |
| 15 | `injection` | CN `冻干粉剂` | CN 的 `form_base` 是 `cleanup_cn_data` 白名单产物（`冻干粉剂`→injection），本脚本**不重算 CN**（见 §3.4） |

另有 2 行注射族冲突是历史遗留（AU `leuprorelin … modified release injection [1 syringe]` → `tablet`），改前就在，与本轮无关。

### 3.4 为什么 CN 只做 `effervescent`

CN 的 `form_base` = 「中文剂型 → 英文词（`translate_form`）→ `form_base_of` → `cleanup_cn_data` 白名单」三段拼出来的。按原文重算会把 1,005 行已收敛的值打回：`糊剂`→`other` 216、`缓释制剂`→`other` 113、`冻干粉`→`other` 42、`锭剂`→`other` 16、`滴丸剂`→`other` 107 …（dry-run 实测）。所以 CN 只落 `effervescent` 107 行，其余保持清洗口径。

---

## 4. 下游影响（现查，非照抄）

| 产物 | 泡腾口径（预期 806/204/145/484） | 全量口径（23,890 行） | 口径 |
|---|---:|---:|---|
| 检索标签会变的 `name_key`（索引里的 `f`） | **806** ✅ | 12,096 | `product_name.key_id`（任一 name_type） |
| 成分页受影响（矩阵行 / 剂型筛选器） | **204** ✅ | 2,439 | 受影响成分数 |
| 改后要拆开的矩阵行 | **145** ✅ | 145 | (成分 × 释放 × 规格) 里泡腾与非泡腾混装的键 |
| 单包装名字页（走 raw form 表格那批） | **480**（报告写 484，差 4） | 5,001 | 只挂 1 个产品的 **trade** 名 key |

> 单包装页 480 vs 484：484 是原报告的估计值，本次按「trade 名 + 全局单产品」口径现查 480（若按「任一 name_type + 单产品」是 533）。差 4 行不影响量级判断（±0.8%），报告口径以此处的可复现定义为准。

---

## 5. 规则外：新规则会算出不同值、但**本轮不改**的 3,996 行

| 行数 | 改前 → 改后 | 市场 | 为什么不改 |
|---:|---|---|---|
| 667 | `unknown` → `other` | AU 554 / CN 113 | `unknown` 是占位档，`other` 也是占位档，改了只挪桶不改信息 |
| 441 | `liquid` → `topical` | GB 183 / AU 130 / CA 46 / ES 40 | 审计判 topical 族的 `coarse`（同族粗粒度），不算错 |
| 370 | `liquid` → `other` | CN 327 / AU 25 / GB 18 | CN 不重算；AU/GB 是 VMP 名被 120 字符截断、尾部剂型词丢了 |
| 320 | `gum, chewing` → `gum` | US 299 / AU 17 / SG 4 | 同义收敛，不影响审计判定；留给 task-148 |
| 301 | `liquid` → `injection` | GB 301 | 审计族闸门挡下（吸入/眼用/植入族），见 §3.2 |
| 268 | `inhalation` → `topical` | AU 268 | `Aerosol, spray` 类；审计的「外用气雾」族判 ok，两种都不算错 |
| 249 | `tablet` → `pastille` | AU 249 | AU 自己的映射把 `Pastille` 判 tablet，共享表判 pastille；两套一致化留给下一批 |
| 216 | `topical` → `other` | CN 216 | CN 不重算（`糊剂`） |
| 204 | `liquid` → `powder` | CA 199 / GB 5 | 试剂盒行，见 §3.2 |
| 186 / 112 / 31 | `unknown` → `oil` / `stick` / `gas` | AU | AU `artg_export` 自己的兜底仍返回 `unknown`；改成共享兜底属 AU 入库口径变更，单列 |
| 142 | `injection` → `other` | CN 128 / GB 14 | CN 不重算；GB 14 是剂型被截断 |
| 72 | `powder` → `inhalation` | AU 72 | `powder for inhalation`（审计判吸入族 coarse） |
| 62 | `liquid` → `inhalation` | GB 35 / AU 18 / CA 7 / ES 2 | 同上 |
| 其余 | 长尾 | —— | 合计 3,996 |

> 这一档**不是遗漏**：每一条都写清了「为什么不改」。要动它们需要先定「试剂盒/咀嚼/口崩/贴剂」这几类（审计报告 §下一步 第 2 条）或者改 AU 的兜底口径，属下一批。

---

## 6. 副本演练（`.tmp/task7/copy.db`，419.9 MB 副本）

| 步骤 | 命令 | 结果 |
|---|---|---|
| ① 基线审计 | `db/consistency_audit_form.py --db 副本 --only R1,R3` | R1 count 28,542（conflict 20,188 / gap 5,829 / unmapped 2,525 / coarse 2,004 / ok 426,352）、R3 1,880+8,392 |
| ② apply | `etl/normalize_form_v2.py --db 副本 --apply --journal .tmp/task7/journal.csv` | **23,890 行**；`quick_check=ok`；`foreign_key_check` 0；备份 `.tmp/task7/copy-before-normalize-v2-*.db` |
| ③ 幂等 | 再跑一次 `--apply` | **计划改动 0 行 / 已改 0 行** ✅ |
| ④ 改后审计 | `--only R1,R2,R3` | 见下表 |
| ⑤ 回滚 | `--rollback --journal .tmp/task7/journal.csv` | **23,890 行逐行恢复**；`quick_check=ok`、FK 0；`form_base` 取值数回到 **875**、`liquid` 70,190 / `injection` 71,443 / `release='none'` 452,432（与基线逐项一致）✅ |

副本 apply 后的审计前后（同一份库、同一份脚本）：

| 指标 | 改前 | 改后 |
|---|---:|---:|
| R1 count（conflict+gap+unmapped） | 28,542 | **7,676** |
| R1 conflict | 20,188 | **463** |
| R1 gap | 5,829 | 5,819 |
| R1 unmapped | 2,525 | 1,394 |
| R1 coarse | 2,004 | 2,058 |
| R1 ok | 426,352 | 447,164 |
| 　`effervescent` 族 | conflict 855 / gap 92 | **ok 947 / conflict 0 / gap 0** |
| 　`injection` 族 | ok 71,308 / conflict 15,572 | ok 86,878 / **conflict 2** |
| 　`powder` 族 | ok 10,157 / conflict 3,354 / unmapped 83 | ok 13,535 / **conflict 50** / unmapped 9 |
| R2 回退成原文整串 | 2,187 | **0** |
| R3 原文有释放词但 `release='none'` | 1,880 | **0** |
| R3 反向（`release` 有值原文无词） | 8,392 | 8,392（不动） |

R1 conflict 剩下 463 = 原 20,188 − **改好 19,726** + **新增 1**（`Implant; Kit` 这一行落 `implant`，kit 族不认 implant；审计按 first-match 把它的原文判成 kit 族）。
`effervescent` 族 after 是 ok **947** 而不是 948：有 1 行的原文是 `Kit; Granules (Effervescents); Tablet`，审计 first-match 判成 kit 族，所以它没进泡腾族的计数（`form_base` 仍是 `effervescent`）。

---

## 7. 门禁与测试（dry-run 后）

| 门禁 | 命令 | 结果 |
|---|---|---|
| `etl` 单测 | `& $py -m unittest discover -s etl -t etl` | **46 项 OK**（改前 25，新增 21） |
| `lib` 单测 | `& $py -m unittest discover -s lib -t lib` | **59 项 OK** |
| 手机通道 | `& $py -m unittest tests.test_mobile_inbox` | **29 项 OK** |
| 三语一致性 | `$env:PYTHONIOENCODING='utf-8'; & $py tests/trilingual/run_tests.py` | **69/72**（历史基线同为 69/72；354 条查询 Top-5 98.6% / Top-1 95.5%，跨国 72/72） |
| 快速全局检查 | `& $py deploy/ci_checks.py --fast` | **PASS 7 / FAIL 0 / SKIP 5**（13.7 s） |
| 数据体检 | `& $py db/check_data.py` | 基线：477,098 产品 / 628,013 成分 / 652,909 名称 / severe 23,752（**库未改，apply 后再跑一次做前后对比**） |
| 入库冒烟 | `& $py etl/ingest_sg_hsa.py`（dry-run） | 5,511 行；`form_base` 出现 `effervescent` 9、`release` DR 90 / ER 167（改前 SG 的 enteric 全落 none）✅ |

> 三语测试必须先 `PYTHONIOENCODING=utf-8`，否则 `✓` 在 GBK 控制台报 `UnicodeEncodeError`（环境问题，与本改动无关）。

**没做**（不在本轮权限 / 未批准）：`site/build.py`（builder 在改）、`--apply` 真实库、`db/atc4_forms.py` 重生成快照、`etl/build_translation_tables.py` 重生成译文快照、`site/dist`、`CHANGELOG`。

---

## 8. 批准后的执行顺序（我照这个跑）

1. **备份**：`Copy-Item data\drugs.db data\backups\drugs-20261110-pre-form-v2.db`（脚本内也会自动再备一份带 run_id 的）；
2. `& $py etl/normalize_form_v2.py`（再跑一次 dry-run，数字应与本报告一致）→
3. `& $py etl/normalize_form_v2.py --apply --allow-real`（23,890 行 + journal）→
4. 校验：`PRAGMA quick_check` / `foreign_key_check`、`& $py db/check_data.py`（前后对比贴报告）、`& $py db/consistency_audit_form.py --only R1,R2,R3`（期望 conflict 463 / R2 0 / R3 0）、
5. `& $py db/atc4_forms.py`（重生成 `data/sources/atc4_forms_20261031.json`：剂型榜会多一行 `effervescent` 948，挤掉一档低频剂型）→ 报最终数字给 Lead。

后续（不属于本任务批准范围）：`etl/build_translation_tables.py` 重生成译文快照、`site/build.py` 的 `LABEL_I18N` 补 `form.effervescent` 四语（builder 的活）、CHANGELOG。

---

## 9. 待 Lead 拍板（3 点，都不阻塞代码）

1. **journal 放哪**：默认 `data/backups/`（跟备份同一份回滚资产，AGENTS §9 不入库，约 2.4 MB）。若要进仓库归档，我改成 `data/sources/form-normalization-v2-journal-20261110.csv`。
2. **`other` 兜底是否接受 895 行**：这 895 行原文认不出剂型（`system` / `chicle` / `wafer` / `insert` …）。要把它们落到具体类，得先定「试剂盒/咀嚼/口崩/贴剂」几类（审计报告 §下一步 第 2 条），建议下一批做，不在本次硬猜。
3. **规则外 3,996 行**（§5）：本轮不动，是否接受？其中 249 行 AU `Pastille`、320 行 `gum, chewing`→`gum` 属「共享表 vs AU 自有表」的口径统一，可单开一批。

---

## 10. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

& $py etl/normalize_form_v2.py                       # dry-run（只读，本报告 §2-§4 的全部数字）
& $py -m unittest etl.test_form_base -v              # 21 项
& $py -m unittest discover -s etl -t etl             # 46 项
& $py db/consistency_audit_form.py --only R1,R2,R3   # 审计口径（改前）

# 副本演练（不碰真实库）
Copy-Item data\drugs.db .tmp\task7\copy.db
& $py etl/normalize_form_v2.py --db .tmp/task7/copy.db --apply --journal .tmp/task7/journal.csv
& $py db/consistency_audit_form.py --db .tmp/task7/copy.db --only R1,R2,R3
& $py etl/normalize_form_v2.py --db .tmp/task7/copy.db --rollback --journal .tmp/task7/journal.csv
```

探针脚本留在 `.tmp/task7/`（`probe_*.py` + `journal.csv` + `audit-before/after.json`），按 AGENTS §9 不入库。

---

_红线复核：本报告只做剂型身份字段的归一与计数，**没有**给出任何用药建议、剂量换算或「可互换」判断；碰撞分级仍由 `collision` 视图自动推导。_
