# 清理 nickname / drug_term 中的毒品与娱乐性用药黑话

日期：2026-10-27 ・ 任务：task-32 ・ 站点版本：v0.3.5
产物：`data/drug_term_removals.csv`（337 行）、`etl/clean_drug_terms.py`、本报告；撤销清单目录 `.tmp/drug-term-cleanup/`
本轮**未写真实 `data/drugs.db`**（Lead 备份后 apply）；apply/回滚只在 `.tmp/drug-term-cleanup/drugs-test.db` 副本验证。

用户口径：**毒品/娱乐性用药不要包含在内，只保留合法药品俗名**。据此对 `nickname`(57) 与
`drug_term`(365) 全量扫描、规则定案（无人工 review）。

---

## 1. 摘要

| 指标 | 数值 |
|---|---|
| 扫描行数 | 422（nickname 57 + drug_term 365） |
| **删除（remove）** | **337 行**（全部在 drug_term） |
| 保留（keep） | 85 行（nickname 57 + drug_term 28） |
| review-none（需人工） | 0（全部按规则定案） |
| 删除后 drug_term | 365 → **28** |
| 删除后 nickname | 57 → **57（不变）** |
| alias_all 视图 | 422 → **85** |
| 删除行 kind 分布 | street 266 / class 66 / folk 5 |

**未删除任何 nickname**：现有 57 条均为合法药品的旧名/民间叫法（安定、心得安、心痛定、
胃复安、伟哥、蓝色小药丸…），不含毒品黑话。

---

## 2. 分类规则（可复核）

### 2.1 remove（毒品/娱乐性用药）
| 规则 | 来源 | 条数 | 理由 |
|---|---|---|---|
| R1 | `nida_slang`（247） | 247 | NIDA「街头叫法/滥用」语料：大麻、海洛因、可卡因、冰毒、MDMA、LSD、GHB、合成大麻素/卡西酮、吸入剂、合成代谢类固醇、镇静剂等 |
| R1 | `dea_slang`（64） | 64 | DEA Slang Terms & Code Words（街头/暗语） |
| R1 | `frank_uk`（12） | 12 | 英国 FRANK 毒品信息：可卡因/大麻/海洛因叫法（Charlie/rocks/Hashish/Brown…） |
| R1 | `adf_au`（5） | 5 | 澳洲 ADF：海洛因叫法（Hammer/The Dragon/Homebake…） |
| R1 | `pnsd_es`（4） | 4 | 西班牙 PNSD：可卡因叫法（Nieve/Blanca/Farlopa/Perico） |
| R2 | `medlineplus`（3） | 3 | 娱乐性吸入剂/笑气叫法：`laughing gas` / `whippets`（笑气）、`poppers`（亚硝酸酯） |
| R3 | `community_cn`（2） | 2 | `聪明药`（哌甲酯/莫达非尼的促智药滥用叫法） |

### 2.2 keep（合法药品俗名 / 类别词）
- **medlineplus 17 行**（合法药品的患者通俗类别词）：water pill=利尿剂、blood thinner=抗凝药、
  painkiller=止痛药、sleeping pill=安眠药、tranquilizer=镇静/抗焦虑、antibiotic=抗生素、
  steroid/cortisone=糖皮质激素、allergy pill=抗组胺、acid reducer=抑酸、laxative=泻药、
  decongestant=减充血、birth control/the pill/morning-after pill=避孕类、insulin=胰岛素、statin=他汀；
- **community_cn 11 行**（合法药品社区叫法）：闭口神器=阿达帕林、祛痘神药=异维A酸、
  生发神药=米诺地尔、P药=奈玛特韦/利托那韦（2 行）、便秘神器=甘油、美白丸=氨甲环酸/谷胱甘肽（2 行）、
  减肥神药=司美格鲁肽、长效伟哥=他达拉非、延时药=达泊西汀；
- **nickname 57 行**：legacy 52 / slang 3 / abbrev 1 / misnomer 1，全部为合法药品旧名或民间叫法。

删除清单逐条见 `data/drug_term_removals.csv`（列：`id,table,alias,substance_id,reason,evidence`；
`evidence` 含来源 source_id、指向 label、source_url，便于复核）。

---

## 3. 工具与安全设计（`etl/clean_drug_terms.py`）

- 默认 **dry-run**：只读打开，逐条校验「表存在 + id 存在 + alias 与库内一致」，打印计划；
- `--apply`：事务内 DELETE，先写**完整行快照**撤销清单（默认 `.tmp/drug-term-cleanup/undo_*.json`），
  再 commit；任一行 rowcount≠1 即整体回滚；
- `--rollback [manifest]`：从快照 `INSERT` 恢复（含所有列），已存在的 id 跳过（幂等）；
- **id + alias 双匹配**，防止 SQLite id 复用误删；
- 与任务-31 的入库脚本互不干扰（删除清单只涉及现有 365 行 id）。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/clean_drug_terms.py                 # dry-run（安全预览）
& $py etl/clean_drug_terms.py --apply         # Lead 备份 DB 后执行
& $py etl/clean_drug_terms.py --rollback      # 如需回滚
```

---

## 4. 副本验证证据（`.tmp/drug-term-cleanup/drugs-test.db`）

| 步骤 | 结果 |
|---|---|
| 基线 | drug_term 365（sha256 `3d5d32…`）、nickname 57（`73ed67…`）、alias_all 422、source 28 |
| dry-run | 可删除 337 / 跳过 0；库无变化 |
| `--apply` | 删除 337；drug_term 365→28；nickname 57 不变；alias_all 422→85；source 不变 |
| 残留检查 | 滥用语料源残留 0；`molly/lean/weed/pot/speed/bars/oxy` 残留 0 |
| 幂等（再 apply） | 可删除 0、跳过 337（行不存在），写 0 行；表 sha256 不变 |
| `--rollback` | drug_term/nickname 两表 sha256 与清理前**完全一致**；alias_all 回到 422 |
| 再 `--rollback` | 幂等成功（0 行恢复、已存在跳过；退出码 0） |

---

## 5. 对站内别名检索的影响评估

- **删除的 337 条**都是英文毒品/街头叫法（molly、lean、bars、speed、weed、pot、oxy…）与
  娱乐性吸入剂/笑气、聪明药 —— 这正是用户明确要求排除的内容；
- **不受影响**：商品名/通用名/成分检索（`product_name`/`substance` 未动）；中文合法俗名
  （昵称 57 条 + 社区叫法 11 条）全部保留；合法类别词 17 条保留（water pill、painkiller 等）；
- **直接影响**：`alias_all` 视图 422→85，英文街头叫法不再返回结果；这是产品口径变化，
  需在 About/README 说明「已移除毒品/娱乐性用药黑话」；
- **顺序建议**：备份 DB → `clean_drug_terms.py --apply`（365→28）→ `ingest_cn_slang.py --apply`
  （+1,034）→ 最终 `drug_term` = **1,062 条**、`alias_all` = **1,119 条**、`nickname` = 57 条。
  （若先跑入库再清理亦可：删除清单 id 只涉及现有 365 行，不影响新增行。）

---

## 6. README / About 示例替换建议（不直接改 build.py，供 Lead/后续版本采用）

现有站点/文档里多处用 molly/lean 作为「毒品/街头叫法」示例，清理后应改为**合法药品叫法**示例：

| 位置 | 现有示例 | 建议替换为 |
|---|---|---|
| `site/build.py:2241`（About 数据说明） | “molly” = MDMA（无上市产品的管制物质） | `water pill` = 利尿剂（合法药品类别叫法）；或 `P药` = 奈玛特韦/利托那韦 |
| `site/build.py:2250` | slang (bars, addy, vikes, dillies, oxy, lean…) | slang（water pill, painkiller, blood thinner, 闭口神器, 减肥针…） |
| `README.md:23` 表格行 | 美国街头 / 民间 / 类别叫法（molly、lean、bars、water pill…）｜✅ 365 条 drug_term | 民间 / 类别叫法（water pill、painkiller、闭口神器、减肥针…）｜✅ 清理后 28 + 中文新增（以 apply 后计数为准） |
| `README.md:130` | molly = MDMA、acid = LSD（本库没有上市产品的管制物质） | 删除该行；或改为 `water pill` = 利尿剂（类别词、无单一成分） |
| `README.md:131` | lean = 可待因 + 异丙嗪（复方） | `P药` = 奈玛特韦/利托那韦；`美白丸` = 氨甲环酸 + 谷胱甘肽 |
| `CHANGELOG.md:162/164` | 类别词（downers…）、molly = MDMA、lean… | 下一版加一节：清理 337 条毒品/街头叫话，drug_term 365→28（+中文 1,034）；示例改为合法药品叫法 |
| `docs/方案与数据模型.md:122-123` | molly = MDMA / lean = 可待因+异丙嗪 | water pill = 利尿剂 / P药 = 奈玛特韦+利托那韦 |

> 另：`README`/`CHANGELOG`/About 的 `drug_term` 计数、`alias_all` 口径需按 apply 后的实际值同步
> （建议：nickname 57 不变；drug_term = 28 + 中文俗名 1,034 = 1,062；alias_all = 1,119）。

---

## 7. 已知取舍与后续

- NIDA/DEA/FRANK/ADF/PNSD 语料被整体移除（含少量指向合法药品的街头叫法，如
  `Bennies`=苯丙胺、`Bars`=阿普唑仑）——按用户「毒品/娱乐性用语不要包含」从严处理；
  若以后需要保留「合法药品的英文街头叫法」，应另建白名单而不是恢复来源。
- `聪明药` 判定为娱乐性/滥用叫法（指向哌甲酯/莫达非尼），删除 2 行；其成分本身仍在库内，
  `减肥神药`/`长效伟哥` 等合法叫法保留。
- 将来若重新引入英文 slang，建议只允许「合法药品 + 非毒品文化」来源（如 MedlinePlus
  patient terms），并在 About 明示排除毒品内容。
