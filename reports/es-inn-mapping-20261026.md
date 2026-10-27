# 西语（ES/MX）成分身份合并：西语名 → 英文 INN（task-13）

> 日期：2026-10-26 ｜ 范围：现有三语言（en/zh/es）内的身份对齐，**不新增语言/市场**。
> 本轮只在 `.tmp/es-map/` 的 DB 副本上验证 apply/幂等/回滚；**本任务未写入 `data/drugs.db`**（快照取于 18:45：substance 13,282 / mx-es 759 / 组件 497,513；写这份报告时该快照的 13,282 与真实库一致）。注意：19:04 另一并行任务（CN→INN 合并）真实写库后 substance 为 12,932——正式 apply 前请重新 dry-run 取最新计数。

## 1. 结论

| 指标 | 数值 |
|---|---:|
| 审计的 ES/MX 西语侧成分 | 1,081（`mx-es-*` 759 + 只在 ES/MX 出现的西语 id 322） |
| 映射到库内已有英文 INN（CSV `mergeable`） | **182**（mx-es 59 / 非前缀 127） |
| 安全预检通过、可真正合并 | **139 个成分 / 621 个产品**（默认仅 mx-es：42 个成分 / 78 个产品） |
| 合并后能让西语产品连上英文市场的合并数 | 131 / 139（594 个西语产品因此看到 en 市场商品） |
| 目标成分所在市场增益（合并数） | US 85、GB 106、CA 107、AU 68 |
| 未映射分类 | no_english 674、uncertain 159、combination 66 |

一句话：**182 条可核实映射，安全校验后 139 条可合并（621 个产品）；其中 131 条直接把 ES/MX 的西语产品接到英/加/澳/美市场的同一成分下**。默认模式（只删 `mx-es-` 前缀）先合 42 条最稳的。

## 2. 审计方法与证据来源

SQL + Python 只读扫描 `substance / variant / product_component / product / corroboration / nickname / drug_term / confusable_pair`，候选来源按可靠性排序：

| 证据 | 说明 | mergeable 命中 |
|---|---|---:|
| exact_norm | 西语 inn_en 归一后与库内英文成分同名 | 4 |
| mx_inn_map | data/mx_inn_map.json（COFEPRIS ingest 的西→英表；via=manual/exact/rule 才算强证据） | 11 |
| cima_alias | etl/ingest_cima.py 的 ALIASES（人工核对的西→英表） | 25 |
| wikidata_es_en | Wikidata：同一实体的西语标签→英文标签（CC0 缓存），加名字相似度闸门 | 109 |
| atc_unique | ES 侧完整 7 位 ATC 全库唯一命中英文成分（5 位前缀码一律不用，防止 R03AC 这类误配） | 82 |
| es_suffix | 构词规则：-ina→-ine、-prazol→-prazole、-sartan→-sartan 等 | 17 |
| fuzzy | difflib 模糊（只作 uncertain，不直接合并） | 0 |

- 只把「英文 INN 在 DB 里已有对应 substance」的候选标 `mergeable`；西语化目标 id（nadroparina / aclidinio / suxametonio / bicarbonato…）先按规则改指英文拼写（nadroparin / aclidinium / suxamethonium），无英文兄弟则降 uncertain。
- 已知假朋友进了人工黑名单：`aceite de eucalipto ≠ eucalyptol`、`Lactobacillus ≠ L. plantarum`、`magnesio ≠ magnesium orotate`、`bicarbonato`（缺阳离子）。

## 3. `data/es_inn_overrides.csv`

共 1081 行；`status` 分布：mergeable 182（confidence: high 31 / medium 151）、uncertain 159、combination 66、no_english 674。

| status | 含义 |
|---|---|
| mergeable | 映射证据可核实，且英文目标在库；merge 脚本还会做 9 条安全校验 |
| uncertain | 多目标/弱证据/低相似度/西语化目标无英文兄弟 → 人工处理 |
| combination | 复方名（含 `y`/`+`/`/`/`con`），无法按单成分合并 |
| no_english | 库内没有对应英文成分（多为墨西哥本地药、商品名残留、生物制品） |

## 4. `etl/merge_es_substances.py`

仿 `etl/merge_cn_substances.py`（同一套操作语义），默认 dry-run：

```bash
python etl/merge_es_substances.py                       # 默认 dry-run；只处理 mx-es- 前缀
python etl/merge_es_substances.py --include-unprefixed  # 连同 ES/MX 独有的非前缀西语 id
python etl/merge_es_substances.py --apply               # 事务写库 + 撤销清单
python etl/merge_es_substances.py --rollback            # 按 .tmp/es-map 最新清单回滚
```

安全校验（任何一条不过只跳过该行，不部分合并）：
1. ES 侧存在；默认只删 `mx-es-*`；`--include-unprefixed` 时要求其全部产品只在 ES/MX 市场
2. 英文目标存在、不以 `mx-es-/cn-` 开头、`inn_en` 与 CSV 归一后一致
3. ES 侧恰好 1 个 base variant（salt/hydrate/ester 空、base_fraction=1）
4. 英文目标有 base variant；**ES 名里带盐时优先挂到 salt 匹配的英文 variant**（6+7 条走 salt 匹配，其余 base）
5. 无 nickname / drug_term / confusable_pair / dose_warning / corroboration 引用
6. 幂等：ES 成分已不存在 → already_merged；CSV 同 id 多目标 → 跳过

## 5. dry-run 实测（快照 `.tmp/es-map/snapshot.db`，只读）

| 模式 | 可合并成分 | 移动产品/组件 | 被安全校验拦下 |
|---|---:|---:|---:|
| 默认（mx-es-*） | 42 | 78 | 140 |
| `--include-unprefixed` | 139 | 621 | 43 |

拦截原因：`corroboration` 引用 38 条（人工核对过浓度的产品，按任务要求保持原样）、英文目标无 base variant 4 条、ES 侧非 base variant 1 条。其余行是 non-mergeable 状态或非前缀默认不处理。

### Top 合并例子（默认模式，按产品数）

| 产品 | ES 成分 | 西语名 | 英文目标（同成分） | 目标已有市场 |
|---:|---|---|---|---|
| 6 | mx-es-bleomicina | Bleomicina | bleomycin (Bleomycin) | AU, CA, ES, GB, US |
| 6 | mx-es-dinitrato-de-isosorbida | Dinitrato De Isosorbida | isosorbide-dinitrate (Isosorbide Dinitrate) | AU, CA, CN, GB, US |
| 4 | mx-es-astemizol | Astemizol | astemizole (Astemizole) | CA |
| 4 | mx-es-besilato-de-cisatracurio | Besilato De Cisatracurio | cisatracurium (Cisatracurium) | CA, CN, ES, GB, US |
| 4 | mx-es-cloruro-de-calcio | Cloruro De Calcio | calcium-chloride (Calcium Chloride) | AU, CA, CN, GB, US |
| 3 | mx-es-dextropropoxifeno | Dextropropoxifeno | dextropropoxyphene (Dextropropoxyphene) | CA, GB |
| 3 | mx-es-dipropionato-de-betametasona | Dipropionato De Betametasona | betamethasone (Betamethasone) | AU, CA, CN, ES, GB, MX, US |
| 2 | mx-es-acido-nalidixico | Acido Nalidixico | nalidixic-acid (Nalidixic Acid) | CA, GB |
| 2 | mx-es-acido-undecilenico-2 | Acido Undecilénico | undecylenic-acid (Undecylenic Acid) | CA, US |
| 2 | mx-es-bicarbonato-sodico | Bicarbonato Sódico | sodium-bicarbonate (Sodium Bicarbonate) | AU, CA, CN, ES, GB, MX, US |
| 2 | mx-es-bromuro-de-butilhioscina | Bromuro De Butilhioscina | hyoscine-butylbromide (Hyoscine Butylbromide) | MX |
| 2 | mx-es-carmelosa-de-sodio | Carmelosa De Sodio | carmellose (Carmellose) | ES, GB |

### Top 合并例子（`--include-unprefixed` 新增的大头）

| 产品 | ES 成分 | 西语名 | 英文目标 | 目标已有市场 |
|---:|---|---|---|---|
| 31 | polimixina-b | Polimixina B | polymyxin-b (Polymyxin B) | CA, GB, US |
| 28 | magaldrato | Magaldrato | magaldrate (Magaldrate) | AU, CA |
| 23 | acido-citrico | Ácido Cítrico | citric-acid (Citric Acid) | AU, CA, GB, US |
| 20 | alcohol-isopropilico | Alcohol Isopropílico | isopropyl-alcohol (Isopropyl Alcohol) | CA, GB, US |
| 20 | triamcinolona | Triamcinolona | triamcinolone (Triamcinolone) | AU, CA, CN, GB |
| 16 | acido-micofenolico | Ácido Micofenólico | mycophenolic-acid (Mycophenolic Acid) | AU, CA, GB, US |
| 16 | oxido-nitroso | Óxido Nitroso | nitrous-oxide (Nitrous Oxide) | AU, CA, GB, US |
| 15 | hidroxocobalamina | Hidroxocobalamina | hydroxocobalamin (Hydroxocobalamin) | AU, CA, GB, US |
| 14 | cisplatino | Cisplatino | cisplatin (Cisplatin) | AU, CA, CN, GB, US |
| 14 | hidroquinona | Hidroquinona | hydroquinone (Hydroquinone) | CA, GB, US |
| 13 | oxitetraciclina | Oxitetraciclina | oxytetracycline (Oxytetracycline) | CN, GB |
| 11 | levodropropizina | Levodropropizina | levodropropizine (Levodropropizine) | CN |

典型价值：`Polimixina B`→`polymyxin-b`（ES 13+MX 18 个产品接上 US 383/CA 119/GB 4）、
`Cloranfenicol`→`chloramphenicol`、`Cisplatino`→`cisplatin`、`Hidroxocobalamina`→`hydroxocobalamin`。

## 6. apply / 幂等 / 回滚（DB 副本实测，真实库未写）

副本：`data/drugs.db` → `.tmp/es-map/snapshot.db`（18:45 快照）→ 再复制为 test_apply2*.db；下表数字来自 `.tmp/es-map/apply_test_result.json`，可复跑。

| 步骤 | substance | variant | mx-es-* | 结果 |
|---|---:|---:|---:|---|
| 快照 | 13,282 | 14,234 | 759 | — |
| 默认 `--apply` | 13,240 | 14,192 | 717 | 合并 42 个（产品 78）；清单 merge_undo_20261027T020934Z.json |
| 默认 `--apply` 第 2 次 | 13,240 | 14,192 | 717 | 写入 0（幂等） |
| 默认  `--rollback` | 13,282 | 14,234 | 759 | 完全复原（integrity ok） |
| `--include-unprefixed --apply` | 13,143 | 14,095 | 717 | 合并 139 个（产品 621）；清单 merge_undo_20261027T021033Z.json |
| `--include-unprefixed --apply` 第 2 次 | 13,143 | 14,095 | 717 | 写入 0（幂等） |
| `--include-unprefixed `--rollback` | 13,282 | 14,234 | 759 | 完全复原（integrity ok） |

- `product_component` 总数全程不变（497,513）：只改 `variant_id` 指向，不丢行。
- 两个模式各自 apply/幂等/回滚后 `PRAGMA integrity_check=ok`、`foreign_key_check` 空。
- 撤销清单：`.tmp/es-map/merge_undo_*.json`（含 substance/variant 全行 + 每个被移动组件的旧 variant；回滚按 `(product_id, ord)` 精确回挂，重复回滚幂等）。
- **合并后西语名仍然可搜**：`product_name`/`name_key` 不变（西语名挂在产品上），只是成分身份并到英文 INN，因此国家视图里能看到该英文成分在 US/GB/CA/AU 的商品。

## 7. 未匹配分类（供下一轮）

- `no_english` 674：库内无候选英文成分（墨西哥本地药/商品名残留/生物制品为主）；需要查说明书或新增英文 INN 才能处理。
- `uncertain` 159：多目标（如 dimeticone/dimethicone 两个都全）、低置信模糊、或名字相似度不足（如 atc 单一弱证据）→ 建议人工过一遍 top 30 产品数即可覆盖大半。
- `combination` 66：复方，需按成分拆分，本轮不做。

## 8. 风险与建议

1. **corroboration 拦截 38 条**：该表记录的是「浓度出处」，与成分身份无关；按任务要求保守跳过。建议 Lead 评估后放宽（这些是最有价值的大头，如 cloranfenicol 37 产品、nafazolina 34、cinarizina 23）。
2. **非前缀 ES id 默认不处理**：127 条候选里 101 条通过了全部安全校验（其产品只在 ES/MX），但删除非前缀 id 风险更高，故默认 `--include-unprefixed` 显式开启；建议先跑默认 42 条、人工抽 10 条，再开 101 条。
3. **映射置信度**：medium 154 条，其中多数由 Wikidata/ATC/构词规则支撑且已过相似度闸门；`data/es_inn_overrides.csv` 可逐行复核（evidence 列写明来源）。
4. **DB 快照**：本报告 counts/apply 基于 18:45 快照（substance 13,282 / mx-es 759）；期间 19:04 另一并行任务（CN→INN）已真实写库至 12,932，`mx-es-*` 仍 759。正式 apply 前请先对**当前库**跑 `--dry-run` 重取计数（脚本本身不依赖快照数字）。
5. 未改 `site/build.py`、未发布；合并后由 Lead 决定何时 rebuild/publish。

## 9. 复现与证据

```bash
python .tmp/es-map/build_candidates.py   # step1：候选/证据（只读 DB）
python .tmp/es-map/finalize.py           # step2：安全闸门 + 人工修正 → data/es_inn_overrides.csv
python .tmp/es-map/impact.py             # 影响面统计 → .tmp/es-map/impact.json
python etl/merge_es_substances.py --db .tmp/es-map/snapshot.db                     # dry-run
python etl/merge_es_substances.py --db .tmp/es-map/snapshot.db --include-unprefixed --dry-run
```

证据目录 `.tmp/es-map/`：`build_candidates.py`、`finalize.py`、`impact.py`、`step1_candidates.csv`、`step2_candidates.csv`、`step1_stats.txt`、`impact.json`、`dryrun_default.txt`、`dryrun_unprefixed.txt`、`APPLY_TEST.md`、`snapshot.db`（副本；test_apply*.db 已在验证后删除）。

---

_本报告由并行子智能体 impl-mx-atc 生成；数据只读审计 + 副本 apply 验证；`data/drugs.db`、`site/build.py`、`site/dist`、git 均未触碰。_
