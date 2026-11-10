# 剂型 / 释放机制归一化 v2（task-7）· apply 交付

> 日期：2026-11-10 ｜ 状态：**已 apply 到 `data/drugs.db`**（未跑 `site/build.py`、未 commit、未发布）
> 上游：`reports/form-normalize-v2-dryrun-20261110.md`（Lead 已批准）｜ 脚本：`etl/normalize_form_v2.py`
> 纪律：apply 前手工备份；写库走单事务 + journal；所有数字现查可复核（命令见 §8）

---

## 0. 结论

**apply 成功。** 23,890 行按 dry-run 批准的范围写入，一条不多一条不少（journal 逐行可回滚）；四条规则与 dry-run 报告**逐项一致**，六项审计指标**全部落在预期值**：R1 conflict 20,188 → **463**、R2 2,187 → **0**、R3 原文有释放词但 `release='none'` 1,880 → **0**、effervescent 族 conflict 855 → **0**（ok 947）、injection 族 conflict 15,572 → **2**、powder 族 conflict 3,354 → **50**。`quick_check=ok`、FK 0 行违规、幂等复跑 **0 行**、四套测试与 `ci_checks --fast` 同基线。

| 验收项 | dry-run 预期 | apply 实测 | |
|---|---|---:|---|
| 改动行数 | 23,890 | **23,890** | ✅ |
| `FORM-EFF` | 948 | **948** | ✅ |
| `FORM-ORDER` | 18,875（liquid→injection 15,570 / liquid→powder 3,305） | **18,875（15,570 / 3,305）** | ✅ |
| `FORM-FALLBACK` | 2,187 | **2,187** | ✅ |
| `RELEASE` | 1,880（ER 1,182 / DR 698） | **1,880（1,182 / 698）** | ✅ |
| 审计 R1 conflict | 463 | **463** | ✅ |
| 审计 R2 | 0 | **0** | ✅ |
| 审计 R3（原文有词） | 0 | **0** | ✅ |
| `effervescent` 条数 | 948 | **948** | ✅ |
| 幂等复跑 | 0 行 | **0 行** | ✅ |
| 四套测试 | 46 / 59 / 29 / 69-72 | **46 / 59 / 29 / 69-72** | ✅ |

> **有一处「与 dry-run 报告不一致」，但不在批准口径内**：报告 §5「规则外 3,996 行」实测 **3,580 行**。原因是 §5 取自 15:25 的探针快照，而 `FORM_BASES` 在 15:39 又补过词（`gum, chewing` 320 行等），报告 15:53 落盘时没重跑该探针（报告自己的逐项相加也只有 3,641）。**四条规则的 23,890 行与全部六项指标不受影响**（这些行两边都是「不改」）。详见 §6。

---

## 1. 执行顺序（严格按 dry-run 报告 §8）

| # | 步骤 | 结果 |
|---|---|---|
| 0 | 手机指令队列 | `mobile/inbox.py pending` → 无待办 |
| 1 | 手工备份 | `data/backups/drugs-20261110-pre-form-v2.db`（419,905,536 B，sha256 `DA44E8B8…62E5AF5`，与备份时刻的 `data/drugs.db` 逐字节一致） |
| 2 | before 基线 | product 477,098 / component 628,013 / name 652,909 / `form_base` 取值 875（非 NULL）/ NULL 13,935 / `effervescent` 0 / `release` none 452,432 → `.tmp/task7/apply/stats-before.json` |
| 3 | dry-run 复核 | `& $py etl/normalize_form_v2.py` → **23,890 行**，四条规则数字与报告 §2 **完全相同**；投影 / 下游（806 / 204 / 145 / 480）也一致 |
| 4 | apply | `& $py etl/normalize_form_v2.py --apply --allow-real` → **已改 23,890 行**，35.5 s，`quick_check=ok`，FK 0 |
| 5 | 校验 | `quick_check` / `foreign_key_check` / `db/check_data.py` 前后对比 / 幂等复跑 / `collision` 派生差异（§2） |
| 6 | 审计复跑 | `db/consistency_audit_form.py --only R1,R2,R3` 前后各一次（§3） |
| 7 | 快照重生成 | `data/sources/atc4_forms_20261031.json`（§4.1）；`data/label_translations.csv` +1 行（§4.2，另两个产物未重生成，原因见 §4.3） |
| 8 | 测试 | etl 46 OK / lib 59 OK / mobile 29 OK / 三语 69-72；`deploy/ci_checks.py --fast` PASS 7 / FAIL 0 / SKIP 5 |

### 1.1 备份与 journal（回滚资产）

| 资产 | 路径 | 大小 | sha256 |
|---|---|---:|---|
| apply 前备份（手工） | `data/backups/drugs-20261110-pre-form-v2.db` | 419,905,536 B | `DA44E8B8117254F890303F3AFDC76E08027789CCBBF9476BBB2E2DD9862E5AF5` |
| apply 前备份（脚本自动，同一状态） | `data/backups/drugs-before-normalize-v2-20261109-160434.db` | 419,905,536 B | `DA44E8B8117254F890303F3AFDC76E08027789CCBBF9476BBB2E2DD9862E5AF5` |
| **journal**（23,890 行） | `data/backups/form-normalization-v2-journal-20261109-160434.csv` | 2,490,537 B | `13D20C1F19A324E0E9EFAF47EF99271828A1D6DB7A9C502F194606D3E058D044` |
| 幂等复跑的自动备份（= apply 后状态） | `data/backups/drugs-before-normalize-v2-20261109-160615.db` | 420,581,376 B | `5AFE2116887AC9776CA0AB28FBDF86C2F35F6F7696716FE3251D3116F5B89C08` |
| 幂等复跑的 journal（0 行） | `data/backups/form-normalization-v2-journal-20261109-160615.csv` | 78 B（仅表头） | —— |

- run_id：apply `20261109-160434`（`applied_at=2026-11-10T00:04:35Z`），幂等 `20261109-160615`；
- journal 逐行核对：23,890 行 = `FORM-ORDER` 18,875 + `FORM-FALLBACK` 2,187 + `FORM-EFF` 948 + `RELEASE` 1,880；按字段 `form_base` 22,010 / `release` 1,880；按市场 GB 10,242 / US 7,298 / AU 2,421 / CA 2,110 / SG 1,283 / ES 343 / CN 107 / MX 51 / TW 35；
- 回滚：`& $py etl/normalize_form_v2.py --rollback --allow-real`（默认取最新 journal，逐行带 old/new 守卫，幂等）；
- **`data/drugs.db` 的 mtime 停在 16:04:34**（apply 那一刻），16:06 的二次 apply 没有再写文件 —— 这也从文件层面证明幂等。

---

## 2. 库侧 before / after

### 2.1 计数（`db/check_data.py`，before 用备份库跑同一脚本）

| 指标 | before | after |
|---|---:|---:|
| products | 477,098 | 477,098 |
| components | 628,013 | 628,013 |
| substances | 12,637 | 12,637 |
| variants | 14,237 | 14,237 |
| name_keys | 202,092 | 202,092 |
| names | 652,909 | 652,909 |
| collisions(severe) | 23,752 | **23,752**（+0） |
| collisions(warning) | 837 | **905**（+68，见 §2.4） |
| alias / nickname / drug_term | 1,119 / 57 / 1,062 | 不变 |

> `check_data.py` 两份输出只差 1 行：`collisions(warning) 837 → 905`。其余 100% 一致（`Compare-Object` 逐行比对）。

### 2.2 `form_base` 分布（只在有变化的档位列出；全量见 `.tmp/task7/apply/form_dist.log`）

| form_base | before | after | Δ |
|---|---:|---:|---:|
| tablet | 181,973 | 181,148 | −825 |
| injection | 71,443 | **87,013** | **+15,570** |
| liquid | 70,190 | **51,433** | **−18,757** |
| capsule | 55,070 | 55,075 | +5 |
| topical | 43,269 | 43,463 | +194 |
| powder | 10,409 | **13,697** | **+3,288** |
| pellet | 7,337 | 7,338 | +1 |
| unknown | 5,872 | 5,886 | +14 |
| inhalation | 3,096 | 3,096 | 0 |
| stick | 2,491 | 2,498 | +7 |
| kit | 2,247 | 2,282 | +35 |
| suppository | 1,729 | **2,150** | **+421** |
| other | 255 | **1,150** | **+895** |
| gas | 986 | 986 | 0 |
| **effervescent** | **0** | **948** | **+948** |
| mouthwash | 328 | 443 | +115 |
| film | 37 | 129 | +92 |
| implant | 57 | 98 | +41 |
| gum | 10 | 51 | +41 |
| plaster | 54 | 86 | +32 |
| oil | 278 | 303 | +25 |
| device | 0 | 20 | +20 |
| pastille | 105 | 120 | +15 |
| tincture | 50 | 55 | +5 |
| swab | 370 | 372 | +2 |
| strip | 39 | 41 | +2 |
| pad | 23 | 24 | +1 |
| 其余 21 档（cloth 602 / soap 416 / pill 390 / gum, chewing 320 / globule 290 / rinse 194 / jelly 193 / lipstick 149 / nasal 147 / inhalant 106 / salve 83 / radiofarmaco 72 / soap bar 57 / cord 51 / sponge 43 / tea (herbal) 39 / wipe 35 / null 29 / aposito 21 / liniment 13 / 空串 8） | —— | 不变 | 0 |
| **取值数** | **875**（非 NULL，含 NULL 876） | **48**（含 NULL 49） | **−827** |

- 875 → 48 是「回退成原文整串」的 2,187 行被收敛的直接后果（R2 → 0）：GB 的 `paracetamol 500mg suppositories`、`oxygen cylinders 3400litres` 这类整串值全部落到具体类；
- `effervescent` 948 行按市场＝GB 256 / AU 231 / US 139 / ES 125 / CN 107 / CA 41 / TW 28 / MX 12 / SG 9，按来源＝dmd 256 / artg_export 193 / openfda_ndc 139 / cima 125 / nhsa 107 / hc_dpd 41 / artg_detail 37 / tfda_tw 28 / cofepris_mx 12 / hsa_sg 9 / pbs 1 —— 与报告 §2.2 逐格相同。

### 2.3 `release` 分布

| release | before | after | Δ |
|---|---:|---:|---:|
| none | 452,432 | **450,552** | −1,880 |
| ER | 15,884 | **17,066** | +1,182 |
| DR | 8,591 | **9,289** | +698 |
| MR | 191 | 191 | 0 |

### 2.4 派生产物变化：`collision` 视图 warning 837 → 905（**dry-run 没算到的唯一一处**）

`collision` 由视图自动推导（AGENTS §1.2），warning 档的判据就是「成分相同但 `release` 不同」——`RELEASE` 规则把 1,880 行的 `none` 补成 ER/DR，必然改变这一档：

| collision | before | after | Δ |
|---|---:|---:|---:|
| severe | 23,752 | 23,752 | 0 |
| warning | 837 | **905** | **+68** |
| info | 168,076 | 168,008 | −68 |
| 总 key 数 | 192,665 | 192,665 | 0（没有新增/消失的 key，只有分级迁移） |

- **70 个 key 从 info 升到 warning**：释放机制组合为 `('DR','none')` 55 个 / `('ER','none')` 14 个 / `('DR','ER','none')` 1 个，例：`acamprosate`、`apo sodium valproate`、`apo tramadol…SR`、`apx pantoprazole`、`budenofalk`、`duloxetine sandoz`、`advagraf tacrolimus prolonged release` —— 这些正是「原文写了缓释/肠溶，旧库没识别出来」的药，现在会正确提示「同类名不同释放机制、不可互换」；
- **2 个 key 从 warning 降到 info**（旧库的假警示）：`rabeprazole`、`salazopyrin en`——旧库同 key 下有的行 `none` 有的行 `DR`，补全后统一为 `DR`，警示消失；
- 净 +68。这不是手工标注，也不是新增数据，属规则修正的正确副作用；**站点 `/warn`、`dose_warning` 相关页面的条数会随之变化**，builder 侧若要写进 CHANGELOG/README 口径，用 §2.1 的新数字（warning 905）。

---

## 3. 六项审计指标（`db/consistency_audit_form.py --only R1,R2,R3`）

同一份脚本、同一个库，apply 前后各跑一次（before 用 `data/backups/drugs-20261110-pre-form-v2.db`，after 用 `data/drugs.db`）：

| 指标 | before | after | dry-run 预期 | |
|---|---:|---:|---:|---|
| **R1 conflict**（原文与 form_base 直接冲突） | 20,188 | **463** | 463 | ✅ |
| **R2**（form_base 回退成原文整串） | 2,187 | **0** | 0 | ✅ |
| **R3**（原文有释放词但 `release='none'`） | 1,880（ER 1,182 / DR 698） | **0** | 0 | ✅ |
| R3 反向（`release` 有值原文无词，不动） | 8,392 | 8,392 | 8,392 | ✅ |
| **effervescent 族** | conflict 855 / gap 92 | **ok 947 / conflict 0 / gap 0** | ok 947 | ✅ |
| **injection 族** | ok 71,308 / conflict 15,572 | **ok 86,878 / conflict 2** | conflict 2 | ✅ |
| **powder 族** | ok 10,157 / conflict 3,354 / unmapped 83 | **ok 13,535 / conflict 50 / unmapped 9** | conflict 50 | ✅ |

R1 总量与分档：

| R1 | before | after | Δ |
|---|---:|---:|---:|
| count（conflict+gap+unmapped） | 28,542 | **7,676** | −20,866 |
| ok | 426,352 | 447,164 | +20,812 |
| conflict | 20,188 | 463 | −19,725 |
| gap | 5,829 | 5,819 | −10 |
| unmapped | 2,525 | 1,394 | −1,131 |
| coarse | 2,004 | 2,058 | +54 |

`effervescent` 948 行里 947 行进 ok 档，剩 1 行原文是 `Kit; Granules (Effervescents); Tablet`——审计 first-match 判成 kit 族，所以不计入泡腾族（`form_base` 仍是 `effervescent`），与报告 §6 的解释一致。
R1 conflict 463 = 原 20,188 − 改好 19,726 + 新增 1（`Implant; Kit` 那行落 `implant`，kit 族不认 implant），与副本演练的 463 逐条对上。

---

## 4. 进仓库的小快照

### 4.1 `data/sources/atc4_forms_20261031.json`（`& $py db/atc4_forms.py`）

| | 重生成前（同库、apply 前） | 重生成后（apply 后） |
|---|---:|---:|
| rows | 28,377 | **28,733**（+356） |
| ATC4 / 成分 / 剂型 / 市场 | 797 / 5,831 / 29 / 10 | 797 / 5,831 / 29 / 10 |
| 产品合计（含被跳过档） | 543,781 | 543,781（Δ0，没有产品被丢） |
| 文件大小 | 1,206,858 B | 1,227,434 B |

- 剂型榜：**新增 `effervescent`（197 个键 / 1,972 条 product×substance）、`film`（29 键 / 167）**，挤掉 `radiofarmaco`（49 行）与 `salve`（82 行）——两档落 `other`，不丢行。报告 §8 预测「多一行 effervescent、挤掉一档」，实际挤掉两档（因为 `film` 也同时进了前 30）；
- 主要位移：`liquid` −1,731 键 / −10,391 条，`injection` +1,416 键 / +8,353 条（另有 384 个既有键改值 +6,449），`powder` +511 键 / +2,543 条；
- **为了把「10 天库漂移」和「本次改动」分开**，上表的 before 是**用 apply 前的备份库现生成**的；仓库里原来那份（2026-10-30 生成，28,378 rows）与它相差只有 16 个键新增 / 17 个键消失，属旧的入库漂移，与 form 归一无关（真正来自 form 的部分就是上表）。

### 4.2 `data/label_translations.csv`（`& $py etl/build_translation_tables.py`）

- 该脚本**没有 `--check` 模式**；它的剂型标签来自代码里的 `EXTRA_FORMS`（task-7 加了 `effervescent`），所以快照落后于词表；
- 重生成后 `69 → 70 行`，唯一差异是新增一行（忽略 `version`/`updated_at` 后逐行比对）：

  | category | code | en | es | zh | zh_hant |
  |---|---|---|---|---|---|
  | form | effervescent | effervescent | efervescente | 泡腾剂 | 泡騰劑 |

- 与 `site/build.py` 的 `LABEL_I18N.form.effervescent`（`efervescente` / `泡腾剂` / `泡騰劑`）**完全一致**，`deploy/i18n_check.py` 的「标签术语一致性」实测 PASS；
- 提醒：`deploy/i18n_check.py` 里这条检查是「以 build.py 的 `LABEL_I18N` 为准去查表」，builder 若把 `form.effervescent` 文案改成别的写法（例如「泡腾片」），现在会**报 FAIL**——要么改文案回「泡腾剂」，要么连这张表一起改。

### 4.3 同一脚本的另两个产物**没有**保留重生成

`& $py etl/build_translation_tables.py` 会一次写三个文件。实测另两个的差异**与 form 归一无关**，属「10 天库漂移 + 品牌上限口径」：

- `data/ingredient_names_i18n.csv`：12,649 → 12,637 行，277 行消失 / 265 行新增（成分 ID 合并、`name_zh` 增删），这是 `substance` 表漂移，会直接改站点 `data/terms.json` 的成分中文名；
- `data/translations.csv`：19,864 → 24,093 行（品牌名 +4,229，`--brand-limit 2000` 与上次运行口径不同）。

两者都已从备份原样还原（sha256 与重生成前一致：`ingredient_names_i18n.csv 7BD1BF19…`、`translations.csv 2D5F3E54…`），避免把无关数据混进本次窗口（AGENTS §7「一次一个主题」）。**要动它们，需单开一批并配 build + 首屏 + 三语验收**，见 §7。

---

## 5. 测试与门禁

| 门禁 | 命令 | 结果 |
|---|---|---|
| `etl` 单测 | `& $py -m unittest discover -s etl -t etl` | **Ran 46 tests … OK** ✅ |
| `lib` 单测 | `& $py -m unittest discover -s lib -t lib` | **Ran 59 tests … OK** ✅ |
| 手机通道 | `& $py -m unittest tests.test_mobile_inbox` | **Ran 29 tests … OK** ✅ |
| 三语一致性 | `$env:PYTHONIOENCODING='utf-8'; & $py tests/trilingual/run_tests.py` | **69/72**（354 条查询 Top-5 98.6% / Top-1 95.5%，跨国 72/72）——与历史基线完全相同；脚本退出码 1 是「不满 72/72」的既有行为，非本次回归。3 个 FAIL 仍是 `metformin(combo, zh 西格列汀二甲双胍片)` / `beclometasone(dup_inn)` / `chlorphenamine(dup_inn)` |
| 快速全局检查 | `& $py deploy/ci_checks.py --fast` | **PASS 7 / FAIL 0 / SKIP 5**（12 项，13.1 s），与 dry-run 基线一致；i18n / py_compile / etl / lib / mobile / dist-integrity / workflow 全 PASS |
| 数据体检 | `& $py db/check_data.py`（before 用备份库同脚本跑） | 只有 `collisions(warning) 837 → 905` 一行差异，其余逐行相同（§2.1） |
| 库完整性 | `PRAGMA quick_check` / `PRAGMA foreign_key_check` | `ok` / **0 行违规**（apply 后与幂等复跑后各一次） |

证据文件（`.tmp/task7/apply/`，按 AGENTS §9 不入库）：`dryrun-rerun.log`、`apply.log`、`apply-idempotent.log`、
`audit-before.log` / `audit-after.log` / `audit-*.json`、`check_data-before.txt` / `check_data-after.txt`、
`stats-before.json`、`form_dist.log`、`atc4_forms.log`、`atc4_diff.py`、`build_translation.log`、`ci-fast.log`、
`tests-etl.log` / `tests-lib.log` / `tests-mobile.log` / `tests-trilingual.log`、`probe_outside.py`、`collision_diff.py`、`verify.py`。

---

## 6. 与 dry-run 报告对不上的地方（逐条核实）

| # | 报告写的 | 实测 | 判断 |
|---|---|---|---|
| 1 | §5「规则外 **3,996** 行」 | `etl/normalize_form_v2.py` 的 `[规则外]` 输出 = **3,580 行**（脚本 mtime 15:53，报告 15:53 之后落盘，脚本此后未改；库 11-06 之后未变） | **报告数字来自旧探针**，不影响 apply：这些行两边都是「不改」 |
| 2 | §5 表里「320 `gum, chewing` → `gum`」 | 现值 **0**（这 320 行 `form_base` 仍是 `gum, chewing`，重算也还是它 → 不算差异） | 同上：§5 取自 `probe_recompute.py`（15:25），`FORM_BASES` 15:39 又补过词 |
| 3 | §5 表逐项相加 | `667+441+370+320+301+268+249+216+204+186+112+31+142+72+62 = 3,641`，而标题写 3,996（差 355 被记成「其余长尾」） | 报告自身算术不闭合；实测长尾 259 |
| 4 | §2–§4、§6、§8 的**全部验收数字** | 逐项吻合（23,890 / 948 / 15,570 / 3,305 / 2,187 / 1,880 / 463 / 0 / 0 / 947 / 2 / 50） | ✅ |
| 5 | 未提及 `collision(warning)` | 837 → 905（+68） | **dry-run 漏算的派生产物变化**，已补进本报告 §2.4 |

**结论：apply 的改动集合与 dry-run 完全一致；不一致只出现在 §5「规则外」这一节的合计数（3,996 vs 3,580）与那条 `gum, chewing` 明细，属报告记录问题，不是执行偏差。** 建议在 dry-run 报告 §5 顶部加一行「本表取自 15:25 探针快照，最终脚本输出为 3,580 行（见 apply 报告 §6）」，我没有改那份已批准的报告。

---

## 7. 遗留 / 下一批

| 项 | 数字 | 说明 |
|---|---:|---|
| `other` 兜底 | **895**（other 255 → 1,150） | 原文认不出剂型的 895 行按纪律落 `other`（`system` 26 / `chicle` 26 / `nitrous oxide 50%/oxygen 50%` 22 / `insert` 19 / `pulverizacion bucal` 19 …）。要落到具体类得先定「试剂盒 / 咀嚼 / 口崩 / 贴剂」几类 |
| 规则外（会算出不同值但不改） | **3,580** | 类目与报告 §5 一致（`unknown→other` 667、`liquid→topical` 441、`liquid→other` 370、`liquid→injection` 301 吸入/眼用族闸门、`inhalation→topical` 268、`tablet→pastille` 249、`topical→other` 216、`liquid→powder` 204 试剂盒 …），合计以脚本现查为准 |
| 粉剂族剩余冲突 | **50** | 35 行 `capsule`（`Hydrocortisone 5mg granules in capsules for opening`：granules 与 capsules 同时出现，属「哪个词更主」的人工判断）+ 15 行 CN `冻干粉剂`（`cleanup_cn_data` 白名单产物，本脚本不重算 CN） |
| 注射剂族剩余冲突 | **2** | AU `leuprorelin … modified release injection [1 syringe]` → `tablet`，历史遗留，改前就在 |
| CN 不重算 | 1,005 行 | CN 只做 `effervescent`（107 行）；按原文重算会把 `糊剂`/`冻干粉`/`锭剂` 打回 `other`，需单独立 CN 口径 |
| `collision(warning)` +68 | 70 升级 / 2 降级 | 释放机制补全后的正确副作用；站点 `/warn` 与相关计数（README / About / CHANGELOG）需在下次发布口径里同步为 **905** |
| 两个译文产物未重生成 | —— | `data/ingredient_names_i18n.csv`（影响 `data/terms.json`，成分中文名增删 265 行）与 `data/translations.csv`（品牌 +4,229 行）见 §4.3，需单开窗口 + build 验收 |
| 未做（不在本任务权限内） | —— | `site/build.py`（builder 在改，16:17 有一个 build 在跑，不是我起的）、`deploy/`、`site/dist`、`CHANGELOG.md`、git commit、发布 |

---

## 8. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

# 0) 备份（420 MB，AGENTS §9 不入库）
Copy-Item data\drugs.db data\backups\drugs-20261110-pre-form-v2.db
Get-FileHash data\backups\drugs-20261110-pre-form-v2.db -Algorithm SHA256

# 1) before 基线 + dry-run 复核（只读）
& $py .tmp/task7/apply/before_after_stats.py before
& $py db/consistency_audit_form.py --only R1,R2,R3 --json .tmp/task7/apply/audit-before.json
& $py etl/normalize_form_v2.py                       # 应打印 23,890 行

# 2) apply（写库，自动备份 + journal）
& $py etl/normalize_form_v2.py --apply --allow-real
& $py etl/normalize_form_v2.py --apply --allow-real  # 幂等复跑：0 行

# 3) 校验
& $py .tmp/task7/apply/verify.py
& $py db/check_data.py
& $py db/consistency_audit_form.py --only R1,R2,R3 --json .tmp/task7/apply/audit-after.json
& $py .tmp/task7/apply/collision_diff.py             # warning 837 → 905

# 4) 快照
& $py db/atc4_forms.py                               # data/sources/atc4_forms_20261031.json
& $py etl/build_translation_tables.py                # 只保留 label_translations.csv 的改动，另两个还原

# 5) 测试
& $py -m unittest discover -s etl -t etl
& $py -m unittest discover -s lib -t lib
& $py -m unittest tests.test_mobile_inbox
& $py tests/trilingual/run_tests.py
& $py deploy/ci_checks.py --fast

# 6) 回滚（如需）
& $py etl/normalize_form_v2.py --rollback --allow-real   # 默认取最新 journal；或
Copy-Item data\backups\drugs-20261110-pre-form-v2.db data\drugs.db
```

---

_红线复核：本报告只做剂型 / 释放机制身份字段的归一与计数，**没有**给出任何用药建议、剂量换算或「可互换」判断；`collision` 分级仍由视图自动推导（本次 warning +68 是规则补全后的自动结果，无一行手工标注）。_
