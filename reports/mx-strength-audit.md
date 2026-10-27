# MX 浓度回填 963 条人工审核报告（task-9）

> 审核对象：`reports/mx-atc-implementation.md` + `.tmp/mx-atc/mx_ccby_dryrun.json` 中 `all_fills` 的 **963 条**回填候选（ETL 已 dry-run，未写库）。
> 审核方式：DB 只读 + 4 份 CC-BY 数据源原始记录回溯 + 分层人工复核；**本轮未写 `data/drugs.db`、未跑 git / site/build.py**。
> 交付：本报告 + `reports/mx_strength_vetted.csv`（963 行，decision/reason/evidence_url）+ `.tmp/mx-audit/`（证据与脚本）。
> 标记：`【已验证】` = 有原始记录/抽样证据；`【推断】` = 估计。

---

## 0. 结论（给 Lead 的 4 个数）

| 指标 | 数量 | 说明 |
|---|---:|---|
| **PASS** | **587** | 证据与数值一致，可安全回填 |
| **FAIL** | **357** | 典型：每克/每 mL/每瓶总量被当成单剂、放宽规则剂型误配、单位错 1000 倍 |
| **UNCERTAIN** | **19** | 证据缺剂型（INER 简写）或需 per_volume 才能判定 |
| **建议本轮 apply（严格集）** | **584** | = PASS 中「严格规则 name2+form」的 584 条；**放弃 3 条放宽规则 PASS** |
| 覆盖率变化 | 28.7% → **34.1%** | 3,123 → 3,707 / 10,878（产品级）；组件级 23.2% → 27.5% |

**关键决定：不要直接跑 `ingest_mx_ccby.py --apply`。** 当前 ETL 会把 963 条全部写库，其中 357 条是错的（现网会显示错误规格）。apply 前必须先加过滤（见 §6），本轮只建议入 584 条。

---

## 1. 审核方法（可复现）

1. **读 DB（只读）**：`file:data/drugs.db?mode=ro`，取 963 个 product_id 的 COFEPRIS 注册记录：`approval_id`、商品名（trade）、西语通用名（inn）、`dosage_form`、`variant.salt`。
2. **回溯原始证据**：用 `etl/ingest_mx_ccby.py` 的解析函数重放 4 份 CC-BY-4.0 数据（INPRFM / HGMGG / INER / SEMAR，共 9,302 行 → 解析 8,040 条），把每条 fill 对应的**原文描述**（含「Cada tableta contiene / Cada ml / Cada sobre / frasco ámpula」等字样）挂回去。脚本：`.tmp/mx-audit/prepare_audit.py`。
3. **人工复核 90 条**：原 50 条清单（`.tmp/mx-atc/mx_verify_50.csv`）逐条判定 + 按剂型分层补充 40 条（固体 20、液体/吸入/注射 20），判定标准：回填值是否等于原文**单剂/单位浓度**，剂型是否一致，单位是否正确。明细：`.tmp/mx-audit/manual_review.csv`。
4. **规则判定 873 条**：把人工复核里归纳出的失败模式固化成规则（§5），对剩余 873 条逐条分类。脚本：`.tmp/mx-audit/classify.py`。
5. **统计口径**：`decision ∈ {PASS, FAIL, UNCERTAIN}`；`apply=Y` 仅当 PASS 且 ETL 规则为严格 `name2+form`（放宽规则 `name2` 一律不自动 apply）。

抽检结果：人工复核的 20 条严格规则固体**全部 PASS**；50 条里 3 条 FAIL 全部来自**放宽规则 `name2`**（剂型误配）——这是放弃放宽规则的主要依据。

---

## 2. 50 条原清单逐条判定（人工）

| # | product_id | 商品名/通用名 | 剂型 | 回填值 | 判定 | 理由 |
|---|---|---|---|---|---|---|
| 1 | MX-097M2022 | MMF-CORD / Micofenolato de mofetilo | tablet | 500 mg | **PASS** | 每片 500 mg，原文一致 |
| 2 | MX-082M2022 | PLASCORD / TACROLIMUS | capsule | 1 mg | **PASS** | 每粒 1 mg |
| 3 | MX-201M2023 | SAIRFLO / SALMETEROL | inhalation | 330 mg | **FAIL** | 原文 0.330 mg/g（每克），fill=330 mg 缩放 1000 倍错误 |
| 4 | MX-274M2007 | WOSULIM 30/70 / INSULINA HUMANA ISOFANA | injection | 100 iu | **FAIL** | 原文 100 UI **/mL**，fill 无 per_volume |
| 5 | MX-096M2022 | STARFOL / PROPOFOL | liquid | 500 mg | **FAIL** | 原文 500 mg/50 mL，fill 是每瓶总量 |
| 6 | MX-160M2024 | SFHIRAX / BROMURO DE TIOTROPIO | powder | 0.018 mg | **PASS** | 每粒 18 µg=0.018 mg（每次吸入剂量） |
| 7 | MX-038M2011 | LOMECAN V / CLOTRIMAZOL | suppository | 500 mg | **PASS** | 每枚 500 mg |
| 8 | MX-249M2021 | — / BROMURO DE PINAVERIO | tablet | 100 mg | **PASS** | 每片 100 mg |
| 9 | MX-334M2023 | LOSIL / TERBINAFINA | topical | 1 g | **FAIL** | 原文 1 g/100 g（1%），fill 缺 per_gram |
| 10 | MX-133M2022 | VERTIRE / VINORELBINA | capsule | 10 mg | **FAIL** | 放宽规则误配：原文是注射液 10 mg/1 mL，产品是胶囊 |
| 11 | MX-113M2022 | NOCOLODI / FENOFIBRATO | capsule | 160 mg | **PASS** | 每粒 160 mg |
| 12 | MX-424M2023 | A-TROFINSA / BROMURO DE IPRATROPIO | inhalation | 286 mg | **FAIL** | 原文 0.286 mg/g，fill 缩放 1000 倍错误 |
| 13 | MX-052M2007 | LUCENTIS / RANIBIZUMAB | injection | 2.3 mg | **UNCERTAIN** | 2.3 mg/0.23 mL 每瓶；数值是每瓶总量，需 per_volume 才能与其它市场对齐 |
| 14 | MX-135M2022 | SOLREMIN / PROPOFOL | liquid | 500 mg | **FAIL** | 500 mg/50 mL 每瓶总量 |
| 15 | MX-186M2026 | PUREBLACK / Carbón activado | powder | 1000 g | **FAIL** | 1 kg/包，整包总量 |
| 16 | MX-007M2015 | CANDIMON / CLOTRIMAZOL | suppository | 500 mg | **PASS** | 每枚 500 mg |
| 17 | MX-064M2022 | BRIOMON / Bromuro pinaverio | tablet | 100 mg | **PASS** | 每片 100 mg |
| 18 | MX-090M2024 | SOTISOL / HIDROCORTISONA | topical | 1 mg | **FAIL** | 乳膏原文仅「1 mg」缺 /g，疑似 1 mg/g 或 0.1%，不能直接写 |
| 19 | MX-259M2023 | SUNDERIN / Cefixima | tablet | 100 mg | **FAIL** | 放宽规则误配：原文是混悬液 100 mg/5 mL，产品是片剂 |
| 20 | MX-213M2022 | 5-LESS / FENOFIBRATO | capsule | 160 mg | **PASS** | 每粒 160 mg |
| 21 | MX-060M2014 | IPRALONG / BROMURO DE IPRATROPIO | inhalation | 286 mg | **FAIL** | 0.286 mg/g，缩放错误 |
| 22 | MX-109M2008 | DICLOPISA / DICLOFENACO SODICO | injection | 75 mg | **FAIL** | 75 mg/3 mL 每安瓿，fill 缺 per_volume |
| 23 | MX-136M2022 | BELLAMUS / Atropina | liquid | 10 mg | **FAIL** | 10 mg/mL 滴眼液，fill 缺 per_volume |
| 24 | MX-009M2021 | GLIBOFHEN / Resina de colestiramina | powder | 4 g | **PASS** | 每袋（sobre）4 g，按剂剂量正确 |
| 25 | MX-069M2020 | SONSVAL / Estriol | suppository | 0.5 mg | **PASS** | 每枚 0.5 mg |
| 26 | MX-067M2022 | TANECIPROL / MISOPROSTOL | tablet | 0.2 mg | **PASS** | 200 µg=0.2 mg/片 |
| 27 | MX-198M2025 | — / HIDROCORTISONA | topical | 1 mg | **FAIL** | 同 #18，缺 /g |
| 28 | MX-272M2023 | GAMINI / Micofenolato de mofetilo | tablet | 500 mg | **PASS** | 500 mg/片 |
| 29 | MX-239M2022 | VANGORN / TACROLIMUS | capsule | 1 mg | **PASS** | 1 mg/粒 |
| 30 | MX-305M2014 | CLOFHIVEN / Dipropionato de beclometasona | inhalation | 0.05 mg | **PASS** | 50 µg/吸=0.05 mg，按次剂量正确 |
| 31 | MX-174M2001 | AVELOX / MOXIFLOXACINO | injection | 160 mg | **FAIL** | 160 mg/100 mL，fill 是每 100 mL 含量 |
| 32 | MX-153M2022 | DOTAB / Senósidos A-B | liquid | 10 ml | **FAIL** | fill 单位是体积 ml，不是浓度 |
| 33 | MX-026M2021 | FHLACTUL / Carbón activado | powder | 1000 g | **FAIL** | 1 kg/包 |
| 34 | MX-156M2020 | GINIOL / Estriol | suppository | 0.5 mg | **PASS** | 0.5 mg/枚 |
| 35 | MX-076M2022 | EXELTRET / Ivermectina | tablet | 6 mg | **PASS** | 6 mg/片 |
| 36 | MX-294M2007 | SONBLEFAM´S / BETAMETASONA | topical | 64 mg | **FAIL** | 64 mg/100 g，fill 缺 per_gram |
| 37 | MX-311M2023 | ADIAL OD¡FS / TADALAFIL | powder | 20 mg | **FAIL** | 放宽规则误配：原文是片剂 20 mg，产品是颗粒剂 |
| 38 | MX-248M2023 | LILEMIDOL / LENALIDOMIDA | capsule | 25 mg | **PASS** | 25 mg/粒 |
| 39 | MX-146M2017 | QUINFORT / Dipropionato de beclometasona | inhalation | 0.05 mg | **PASS** | 50 µg/吸 |
| 40 | MX-535M2001 | YGALEX / FENITOINA SODICA | injection | 250 mg | **FAIL** | 250 mg/5 mL 每安瓿，fill 缺 per_volume |
| 41 | MX-163M2022 | MIDIOTIC / CLARITROMICINA | liquid | 2500 mg | **FAIL** | 2.5 g/60 mL 每瓶总量 |
| 42 | MX-051M93 | DENVAR / Cefixima | powder | 100 mg | **FAIL** | 干混悬 100 mg/5 mL，不是每克散剂剂量 |
| 43 | MX-037M2021 | VARNASIN / CLOTRIMAZOL | suppository | 500 mg | **PASS** | 500 mg/枚 |
| 44 | MX-108M2022 | LOPRETEC / MISOPROSTOL | tablet | 0.2 mg | **PASS** | 200 µg/片 |
| 45 | MX-169M2007 | INFEBYE / CLORANFENICOL | topical | 5 mg | **FAIL** | 5 mg/g 眼膏，fill 缺 per_gram |
| 46 | MX-374M2023 | FENOKEM / Micofenolato de mofetilo | tablet | 500 mg | **PASS** | 500 mg/片 |
| 47 | MX-257M2023 | DEXGSTROL / Dexlansoprazol | capsule | 60 mg | **PASS** | 60 mg/粒 |
| 48 | MX-114M2021 | BROMURO DE IPRATROPIO / BROMURO DE IPRATROPIO | inhalation | 286 mg | **FAIL** | 0.286 mg/g，缩放错误 |
| 49 | MX-051M2002 | LEOFRIN / Orfenadrina | injection | 60 mg | **FAIL** | 60 mg/2 mL 每安瓿，fill 缺 per_volume |
| 50 | MX-212M2022 | QUISHVAN / PROPOFOL | liquid | 500 mg | **FAIL** | 500 mg/50 mL 每瓶总量 |

**50 条小计：PASS 23 / FAIL 26 / UNCERTAIN 1。**

## 3. 分层补充抽审（40 条）

- **固体 20 条（tablet/capsule/suppository/gragea）**：**19 PASS / 1 FAIL**。FAIL 是 `MX-378M2007`（产品：特比萘芬片；原文：乳膏 1 g/100 g）——放宽规则剂型误配。其余 19 条（多替拉韦 50 mg、阿比特龙 500 mg、唑吡坦 10 mg、埃索美拉唑 40 mg、他达拉非 20 mg、格列美脲 2 mg、来那度胺 25 mg、匹维溴铵 100 mg、法莫替丁 40 mg、雷尼替丁 150 mg、双氯芬酸 100 mg、骨化三醇 0.25 µg、泮托拉唑 40 mg、帕罗西汀 20 mg、甲苯咪唑 100 mg 等）原文均为「Cada tableta/cápsula contiene: X」且数值一致。
- **液体/吸入/注射 20 条**：**PASS 4 / FAIL 15 / UNCERTAIN 1**。
  - PASS：`MX-101M2007`、`MX-042M2012`（氯化钠 0.9%，百分比浓度本身正确）、`MX-398M2002`（头孢呋辛**粉针** 750 mg/瓶）、`MX-497M2003`（美罗培南**粉针** 1 g/瓶）。
  - FAIL 与 UNCERTAIN 全部是「原文按每 mL / 每 5 mL / 每 100 mL / 每安瓿 / 每瓶」：拉坦前列素 50 µg/mL、罗哌卡因 150 mg/20 mL、氢化可的松 100 mg/2 mL、丙泊酚 500 mg/50 mL、溴莫尼定 2 mg/mL、克拉霉素 2.5 g/60 mL、右美沙芬 300 mg/100 mL、双碘喹啉 210 mg/5 mL、左卡尼汀 1 g/5 mL、复方磺胺 40 mg/5 mL 等。

**人工复核 90 条合计：PASS 46 / FAIL 42 / UNCERTAIN 2。**

## 4. 963 条全量判定结果

| 判定 | 数量 | 占比 |
|---|---:|---:|
| PASS | 587 | 61.0% |
| FAIL | 357 | 37.1% |
| UNCERTAIN | 19 | 2.0% |
| 其中**建议 apply**（严格规则 PASS） | **584** | 60.6% |

按剂型：

| 剂型 | PASS | FAIL | UNCERTAIN | 建议 apply |
|---|---:|---:|---:|---:|
| tablet | 450 | 44 | 13 | 447 |
| capsule | 83 | 42 | 4 | 83 |
| suppository（óvulo/栓） | 19 | 0 | 0 | 19 |
| powder（散剂/颗粒） | 4 | 12 | 0 | 4 |
| liquid（口服液/滴眼液） | 11 | 155 | 1 | 11 |
| injection（注射） | 10 | 44 | 1 | 10 |
| inhalation（吸入） | 2 | 10 | 0 | 2 |
| topical（外用） | 8 | 50 | 0 | 8 |

按 ETL 规则：

| 规则 | PASS | FAIL | UNCERTAIN |
|---|---:|---:|---:|
| `name2+form`（严格） | 584 | 264 | 2 |
| `name2`（放宽） | 3 | 93 | 17 |

> **放宽规则必须废弃**：113 条中仅 3 条 PASS（全部是 INER 简写的 MMF 500 mg，已人工核实），93 条 FAIL、17 条 UNCERTAIN，FAIL 主因是剂型误配（胶囊↔片剂、片剂↔乳膏、片剂↔注射液、片剂↔干混悬）。

## 5. 失败模式（规则依据）

| 失败模式 | 条数（估） | 例 | 处理 |
|---|---:|---|---|
| 吸入剂「每克含量」被当单剂，且缩放 1000 倍 | 10 | 沙美特罗 0.330 mg/g → 330 mg；异丙托溴铵 0.286 mg/g → 286 mg | 排除；需 per-actuation 解析 |
| 液体「每 mL / 每 5 mL / 每 100 mL」浓度被当规格 | 130+ | 克拉霉素 2.5 g/60 mL→2500 mg；右美沙芬 300 mg/100 mL；阿托品 10 mg/mL | 排除；需 per_volume 解析 |
| 注射液「每安瓿/每瓶总量」无体积 | 44 | 双氯芬酸 75 mg/3 mL；苯妥英钠 250 mg/5 mL；丙泊酚 500 mg/50 mL | 排除；仅**干粉针每瓶标示量**可入（10 条 PASS） |
| 外用「mg/g 或每管总量」 | 50 | 倍他米松 64 mg/100 g；特比萘芬 1 g/100 g；氯霉素 5 mg/g | 排除；仅**百分比浓度**可入（8 条 PASS） |
| 放宽规则剂型误配 | 93 | 片剂产品套用胶囊/乳膏/注射液原文 | 废弃 `name2` 规则 |
| 散剂整包/重建悬液 | 12 | 活性炭 1 kg/包；头孢克肟 100 mg/5 mL | 排除；仅每袋/每粒剂量可入（4 条 PASS） |
| fill 单位是体积 ml | 9 | 番泻苷 10 ml | 排除 |

**与任务提示一致的高风险样本全部命中**：`Claritromicina 2500 mg`（每瓶 2.5 g/60 mL）、`Atropina 10 mg`（10 mg/mL 滴眼液）、`Salmeterol 330 mg`（0.330 mg/g）均判 FAIL；`Ranibizumab 2.3 mg` 因是每瓶标示总量（2.3 mg/0.23 mL）判 UNCERTAIN。

## 6. 可安全 apply 的过滤规则（建议直接写进 ETL）

**规则集 R（本轮）**——只有同时满足才写：

1. **仅单成分、浓度为空的 MX 产品**（ETL 已保证）。
2. **只接受 `name2+form`（严格）匹配**；**删除 `name2`（放宽）分支**。
3. 按剂型分流：
   - `tablet / capsule / suppository`：单位 ∈ {mg, mcg, g}，原文剂型与产品剂型一致（`evidence_forms == product.form_base` 或原文无剂型词），原文含「Cada tableta/comprimido/cápsula/óvulo contiene」或为 INER 简写「通用名 + 浓度」；**INER 简写且无剂型词的，降级为 UNCERTAIN 不自动写**。
   - `powder`：仅当原文含「cada sobre / cada dosis / cada cápsula」且数值 ≤ 5 g；活性炭 1 kg、重建悬液（mg/5 mL）排除。
   - `inhalation`：仅当原文是「cada inhalación / cada dosis / por dosis」的每吸剂量且 ≤ 1 mg；「每克含量」排除。
   - `injection`：仅当原文为**干粉针**（「frasco ámpula con polvo」/「liofilizado」）的每瓶标示量；液体安瓿一律排除（需 per_volume）。
   - `liquid`：仅当单位是 `%` 且原文含 `%` 的浓度（如 0.9% NaCl）；其余排除（需 per_volume）。
   - `topical`：仅当单位是 `%` 且原文含 `%`（如他克莫司 0.1% 乳膏）；其余排除（需 per_gram）。
   - 单位 `ml` / `iu`：一律排除（需 per_volume）。
4. 数值归一：`< 0.01 mg` 的按 µg 显示（如骨化三醇 0.00025 mg → 0.25 µg）；`%` 保留原单位。
5. 每条写 `corroboration`（ETL 已实现，`source_type='provincial_list'`，url=数据集资源页）——**许可为 CC-BY-4.0，可再发布，需署名 + 改编声明**。

**按 R 的可 apply 条数：584 条**（product 级），预计：

```text
MX 有浓度产品：3,123 → 3,707 / 10,878 = 34.1%（+5.4 pp）
MX 有浓度组件：3,161 → 3,745 / 13,632 = 27.5%
corroboration 新增：约 700–900 行（一个产品可被多个数据集支撑）
```

**apply 前必须改 ETL**：`etl/ingest_mx_ccby.py` 目前 `--apply` 会写全部 963 条。建议加 `--vetted reports/mx_strength_vetted.csv`（只写 `apply=Y`），dry-run 复核写入数 = 584 后再 apply；apply 前备份库、用现成 `--rollback` 兜底。

## 7. 下一轮可挽回量（需 per_volume / per_gram 解析）

本轮 FAIL 里约 **249 条**（liquid 155 + injection 44 + topical 50）是「数值本身对、但缺每 mL/每 g 基数」。若 ETL 解析原文里的「Cada ml / Cada 100 ml / Cada g / Cada 100 g / 每瓶体积」并写入 `product_component.per_volume_value/unit`：

- 保守估计可再安全入 **100–150 条**【推断】（例：胰岛素 100 IU/mL、双氯芬酸 25 mg/mL、氯化钠 0.9%、特比萘芬 1 g/100 g）；
- 需同时改 schema 语义（per_volume 已存在字段）与站点展示（显示「5 mg/mL」而不是「5 mg」）；
- 吸入剂另需「每揿 µg」字段，建议单独排期。

## 8. 证据索引与复现

| 文件 | 内容 |
|---|---|
| `reports/mx_strength_vetted.csv` | **963 行判定**：product_id / decision / reason / form / evidence_url / apply / brand / inn / fill / rule / evidence_datasets / evidence_snippet |
| `.tmp/mx-audit/manual_review.csv` | 90 条人工复核明细（含原始描述、剂型、group_strengths） |
| `.tmp/mx-audit/audit_all.csv` | 963 条：DB 字段 + 证据原文 + 风险 flags + 预分类 |
| `.tmp/mx-audit/review_50.txt` / `review_strata.txt` | 带证据原文的人工核对清单（50 + 40） |
| `.tmp/mx-audit/rule_spotcheck.txt` | 规则判定抽检（PASS 每剂型 15 条 + FAIL 抽样 + unknown 全量） |
| `.tmp/mx-audit/prepare_audit.py` / `classify.py` / `spotcheck.py` | 只读复现脚本 |
| `.tmp/mx-audit/stats.json` | 全部统计（可被其它智能体引用） |
| `.tmp/mx-audit/report_tables.md` | 50 条表与统计的机器生成版本 |

复现：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\mx-audit\prepare_audit.py   # 只读 DB + 原始缓存 → audit_all.csv / review_*.txt
& $py .tmp\mx-audit\classify.py        # 规则+人工 overrides → vetted CSV / 统计
& $py .tmp\mx-audit\spotcheck.py       # 规则抽检清单
```

## 9. 风险与限制

1. **证据层级**：判定的「原文」是公立机构采购记录里的药品描述（INPRFM/HGMGG/INER/SEMAR，CC-BY-4.0），**不是 COFEPRIS 说明书原件**；COFEPRIS 侧只用 DB 里的注册号/商品名/剂型做身份核对。建议 apply 后再对 10%（约 58 条）做厂商说明书二次抽查。
2. **未做在线逐条核验**：本轮未对 963 条逐一请求厂商/COFEPRIS 页面（时间与限流约束），高风险样本的高置信度来自原文本身（「Cada ml」「Cada 100 g」「frasco ámpula con polvo」字样清楚）。
3. **UNCERTAIN 不自动写**：19 条（17 条 INER 简写无剂型 + 雷珠单抗 + 依托咪酯）留待 per_volume/说明书核验。
4. **语义边界**：本轮只回填 `strength_value/unit`，未填 `per_volume_*`；因此液体制剂即使数值对也被判 FAIL —— 这是刻意的保守策略，避免站上把「每瓶总量」显示成「规格」。
5. **许可**：4 份数据源 CC-BY-4.0（可再发布，需署名 + 注明改编）；产物 `reports/mx_strength_vetted.csv` 含原始描述片段（改写自 CC-BY-4.0 数据），随站发布时保留署名即可。

---

_本报告由并行子智能体 data-depth 生成；DB 只读（未写 `data/drugs.db`），未跑 git / 发布 / `site/build.py`。_
