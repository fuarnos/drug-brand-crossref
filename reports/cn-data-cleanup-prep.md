# CN 数据清洗批次准备（form_base / 规格 / 重复 / 批文）

> 日期：2026-10-28 ｜ 任务：`task-129` ｜ 依据：`reports/cn-data-intuition-audit.md` P1
> 产物：`etl/cleanup_cn_data.py`（dry-run / apply / rollback / --allow-real）、本报告、`.tmp/cn-cleanup/`（dry-run/验证日志）
> 边界：**真实 DB 未写**、未改 `site/build.py` / `data/markets.json`；未 git/发布。所有验证只写 `.tmp/cn-cleanup/test.db` 副本。

## 0. 结论（先看这段）

1. **清洗规则已实现且可回滚**：`etl/cleanup_cn_data.py` 用 journal（字段级 old/new）+ 去重快照表实现 apply/rollback；副本 **27/27 断言 PASS**，幂等（二次 apply journal 行数不变）、回滚后 CN 产品数/form_base/规格/note 指纹与基线**逐字节一致**，`integrity_check=ok`。
2. **影响面（以当前 DB 实测，与 audit 略有数据漂移）**：
   - **form_base**：1,214 行 / **67 类**长尾 → canonical；其中检测/试剂类 **218 行**（audit 192 的 top3 已扩为 10 类）→ `other` + note 标记。
   - **规格**：异常 **30 行**（`>100000` 27 + `<=0` 3）→ 全部置 NULL + note 标记，**不猜值**；无规格 **5,230 产品** → 只加 note 标记（不改数值）。
   - **重复**：精确重复 **756 组 / 2,042 行** → 删除 1,286 行（保留每组最小 product_id，删除前快照）；近重复 **4,763 组 / 14,499 行**（audit 14,572，数据漂移）→ 标记 `pending review`，**不删**。
   - **批文**：参照后缀 **339 行** 去掉；进口格式 **993 行**（H/HC/S/J）保留原格式并标 import；中国 MAH 缺前缀 **76 行**按启发式补「国药准字」（需复核）；多文号 3 行、空白/全角 1 行、国药试字 1 行、缺失 1 行按规则保留/标记。
3. **真实窗口执行步骤**（待批准）：备份 → 停建站 → `--dry-run`（真实库只读）→ `--apply --allow-real` → `db/check_data.py` + 计数核对 → 重建站 → README/CHANGELOG 更新；回滚 = `--rollback --allow-real`（本脚本自带）。
4. **重要前置**：v0.8.3 的「常用剂量排序/筛选器」上线前应先执行本清洗，否则 `400064 g` 会被排到最前、非 canonical 剂型会被筛掉（与 audit 风险提示一致）。

## 1. form_base canonical 映射（1,214 行 / 67 类）

canonical 枚举 = audit 口径 11 值（tablet/capsule/injection/topical/powder/liquid/suppository/inhalation/pill/other/unknown）+ build.py `LABEL_I18N` 已支持的 pellet/stick/kit/gas（本次实际只用到 **stick**，映射「棒剂」）。**原剂型文本仍在 `dosage_form` 列，不删不改**；检测/试剂类额外加 note `cn-cleanup:diagnostic_reagent`。

| # | 原 form_base（非规范） | 行数 | → canonical | 备注 |
|---:|---|---:|---|---|
| 1 | 灌肠剂 | 173 | liquid | enema；canonical 无 enema |
| 2 | 体外诊断试剂 | 150 | other | 检测试剂，note 标记 |
| 3 | 缓释制剂 | 97 | unknown | 释放信息属 release 列，剂型不可判 |
| 4 | 冻干粉针剂 | 87 | injection | |
| 5 | 滴剂 | 72 | liquid | |
| 6 | 口服乳剂 | 72 | liquid | |
| 7 | 眼膏剂 | 67 | topical | |
| 8 | 鼻用制剂 | 64 | topical | |
| 9 | 粉雾剂 | 52 | inhalation | |
| 10 | 耳用制剂 | 33 | topical | |
| 11 | 冻干粉 | 33 | powder | 剂型不明，保守取 powder |
| 12 | 放免诊断试剂盒 | 31 | other | 检测试剂，note 标记 |
| 13 | 涂剂 | 27 | topical | |
| 14 | 植入剂 | 17 | other | |
| 15 | 冻干制剂 | 17 | injection | |
| 16 | 锭剂 | 16 | tablet | |
| 17 | 冻干粉剂 | 15 | injection | |
| 18 | 橡胶膏剂 | 13 | topical | |
| 19 | 诊断试剂盒 | 11 | other | 检测试剂，note 标记 |
| 20 | 含漱剂 | 10 | liquid | |
| 21 | 乳胶剂 | 10 | topical | |
| 22 | 控释制剂 | 9 | unknown | |
| 23 | 外用冻干制剂 | 9 | topical | |
| 24 | 诊断试剂 | 7 | other | 检测试剂 |
| 25 | 皮肤点刺试剂 | 7 | other | 检测试剂 |
| 26 | 糊剂 | 6 | topical | |
| 27 | 咀嚼胶 | 6 | other | |
| 28 | 冻干粉末 | 6 | injection | |
| 29 | 醑剂 | 5 | liquid | |
| 30 | 粉剂 | 5 | powder | |
| 31 | 放射性密封源 | 5 | other | |
| 32 | 其他:制剂(非中国药典剂型 冻干粉剂) | 5 | unknown | |
| 33 | 无菌冻干粉 | 4 | injection | |
| 34 | 抗体诊断试剂盒 | 4 | other | 检测试剂 |
| 35 | 外用粉末剂 | 4 | powder | |
| 36 | 其他:制剂(非中国药典剂型冻干粉剂) | 4 | unknown | |
| 37 | `-` | 4 | unknown | 脏值 |
| 38 | 硬膏剂 | 3 | topical | |
| 39 | 火棉胶剂 | 3 | topical | |
| 40 | 漱液剂 | 3 | liquid | |
| 41 | 海绵剂 | 3 | topical | |
| 42 | 泡沫剂 | 3 | topical | |
| 43 | 宫内释放系统 | 3 | other | |
| 44 | 合剂 | 3 | liquid | |
| 45 | 体外诊断制剂 | 3 | other | 检测试剂 |
| 46 | 乳剂 | 3 | liquid | |
| 47 | （空白） | 3 | unknown | 脏值 |
| 48 | 热敷剂 | 2 | topical | |
| 49 | 点刺液 | 2 | other | 检测试剂 |
| 50 | 液体剂 | 2 | liquid | |
| 51 | 液体制剂 | 2 | liquid | |
| 52 | 外用制剂(冻干) | 2 | topical | |
| 53 | 体外诊断试剂盒 | 2 | other | 检测试剂 |
| 54 | `/` | 2 | unknown | 脏值 |
| 55 | 靶向制剂 | 1 | other | |
| 56 | 露剂 | 1 | liquid | |
| 57 | 试剂盒 | 1 | other | 检测试剂 |
| 58 | 棒剂 | 1 | stick | build 支持 stick |
| 59 | 放射性密封籽源 | 1 | other | |
| 60 | 宫内节育系统 | 1 | other | |
| 61 | 外用制剂 | 1 | topical | |
| 62 | 外用冻干剂 | 1 | topical | |
| 63 | 制剂:密封源 | 1 | other | |
| 64 | 冻干粉针 | 1 | injection | |
| 65 | 冻干 | 1 | injection | |
| 66 | `\` | 1 | unknown | 脏值 |
| 67 | `----` | 1 | unknown | 脏值 |

> 检测/试剂类实际 218 行（10 类）：体外诊断试剂 150、放免诊断试剂盒 31、诊断试剂盒 11、诊断试剂 7、皮肤点刺试剂 7、抗体诊断试剂盒 4、体外诊断制剂 3、体外诊断试剂盒 2、点刺液 2、试剂盒 1。**仍留在产品表**（form_base=other + note 标记），页面过滤/隐藏建议另开 build 任务（本任务禁改 build.py）。

## 2. 规格规则（异常 30 行 + 无规格 5,230）

### 2.1 异常判定与处理

判定：`strength_value > 100000` 或 `strength_value <= 0`（与 audit 一致）。

| 值 | 单位 | 成分 | 行数 | 处理 |
|---:|---|---|---:|---|
| 400064 | g | Macrogol | 22 | 置 NULL + note `cn-cleanup:strength_anomaly` |
| 400013.125 | g | Macrogol | 2 | 同上 |
| 3350100 | g | Macrogol | 1 | 同上 |
| 126000 | iu | 牛碱性成纤维细胞生长因子外用 | 1 | 同上（可能合理，但规则一致不猜） |
| 300000 | iu | 外用重组人碱性成纤维细胞生长因子 | 1 | 同上 |
| 0 | g | Cefoperazone | 2 | 同上 |
| 0 | mg | Dinoprostona | 1 | 同上 |

**处理原则**：`strength_value / strength_unit / per_volume_value / per_volume_unit` 全部置 NULL（不是只置 value 留 unit），原值写入 journal 供回滚；产品 note 加标记。**不自动纠正**（如 400064 → 4000 + 64g），因为纠正属猜测、且同一产品可能多成分多规格，需人工/后续 parser 规则验证。

### 2.2 原 source 解析 bug 核对（已确认）

NHSA 原始 CSV（`data/raw/nhsa/nhsa_codes_20240105.csv`）中原文即：
> `本品为复方制剂,每袋含:聚乙二醇400064g,无水硫酸钠5.7g,…`

**source 文本本身缺分隔**（「聚乙二醇 4000」+「64g」连写），不是我们 ETL 的切分错。建议后续在 NHSA ingest 增加**可验证规则**（对 Macrogol 类匹配 `聚乙二醇4000(\d+)g` → 4000 + xx g，仅当总袋数/标签可交叉验证时），并保留 confidence；本批次只把当前 DB 的异常值置 NULL，不修 source。

### 2.3 无规格 5,230 产品

- 判定：产品下所有 component 的 `strength_value` 均为 NULL。
- 处理：**只加 note 标记** `cn-cleanup:no_strength`（不改任何数值；页面显示「未公开」由展示层后续任务做）。
- 与异常的关系：30 个异常组件置 NULL 后，对应产品如果因此变成「全 NULL」，会同时带 `strength_anomaly` 与出现在无规格统计中——本批按组件标记 + 产品标记分别记录，互不覆盖。

## 3. 重复产品方案

### 3.1 精确重复：756 组 / 2,042 行 → 删除 1,286 行

- 签名：`(approval_id, mah, dosage_form, release, pack, 成分规格签名)`；成分规格签名 = 按 ord 拼接 `strength_value/strength_unit`。
- 策略：每组**保留最小 product_id**（字典序，与任务要求一致）；其余 1,286 行删除。
- 删除前：整行（product + product_component + product_name）快照到 `cleanup_cn_deleted_product`，支持完整回滚。
- 引用迁移：`product_component` / `product_name` 对 product 有 `ON DELETE CASCADE`，随删；`name_key` / `name_variant` 为全局名称表，保留（不删）；`collision`/检索索引在建站时重算，无需迁移。
- 效果：CN 产品 146,347 → **145,061**（−1,286）；重复组归零。

### 3.2 近重复：4,763 组 / 14,499 行 → 标记「待复核包装」，不删

- 口径（与 audit 一致）：`(approval_id, 商品名 norm, strength_value, strength_unit)` 分组，组内行数 >1（含多成分产品按组件行计数）。
- 处理：写入 `cleanup_cn_dup_review` 表（run_id, product_id, group_key, reason），**不删任何行**；共标记 **14,242 个不同产品**（行数 14,499，部分产品跨组）。
- 复核建议：按包装/药品代码/价格核对后，再决定是否合并；本批次不做自动合并（避免误删不同包装真实产品）。

## 4. 批文格式规范化（1,331 行受影响 / 993 行进口格式）

| 类型 | 行数 | 规则 | 结果 |
|---|---:|---|---|
| 带「(参照)」的国产文号 | 339 | 去 `(参照)/(参照)` 后缀，保留 `国药准字H...` | approval_id 规范化；原值进 note `approval_raw=...` |
| 进口格式（H/HC/S/J + 8 位） | 993 | **保留原格式**，不补「国药准字」（补了会误标国产）；note 标 `approval_origin=import` | 其中 912 行标 import（被去重删 8 行） |
| 其中中国 MAH 的裸文号 | 76 | 启发式补 `国药准字` 前缀 + note `approval_prefix_added`（**需复核**） | 76 行 |
| 多文号字符串（如「米非司酮片:国药准字H.../米索前列醇片:国药准字H...」） | 3 | 抽取全部文号、补缺失前缀、去重后用 ` / ` 连接；原值进 note | 3 行 |
| 空白/全角字符 | 1 | NFKC + 去空白 | 1 行 |
| `国药试字...` | 1 | 保留原格式（试行文号，不强行改） | 0 变更 |
| 缺失文号 | 1 | 不动（无法规范化） | 0 变更 |

> 说明：任务口径「993+339 行规范化」= 339 去参照 + 993 行进口/裸号处理；「补前缀」仅对 76 行中国 MAH 裸号做启发式（audit 未给判定依据），报告标记需人工复核；其余进口格式不改格式只标来源。

## 5. DB 副本验证（27/27 PASS）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
copy data\drugs.db .tmp\cn-cleanup\test.db
& $py etl/cleanup_cn_data.py --dry-run --db .tmp\cn-cleanup\test.db
& $py etl/cleanup_cn_data.py --apply --db .tmp\cn-cleanup\test.db
& $py etl/cleanup_cn_data.py --apply --db .tmp\cn-cleanup\test.db   # 幂等
& $py etl/cleanup_cn_data.py --rollback --db .tmp\cn-cleanup\test.db
```

| 验证项 | 结果 |
|---|---|
| 基线 | CN 产品 146,347；form 非规范 1,214；规格异常 30；无规格 5,230；参照 339 |
| dry-run | form 1,214/67 类（检测 218）、规格异常 30、无规格 5,230、精确重复 756 组/删 1,286 行、待复核 4,763 组/14,499 行 |
| apply 后 | form 非规范 **0**、异常 **0**、参照 **0**；检测标记 210（218−8 去重删）、异常标记 30、无规格标记 5,071（5,230−159 去重删）、import 标记 904、补前缀 76；CN 产品 **145,061**；删除快照 1,286；待复核 14,242 产品；journal 9,473 行 |
| 幂等 | 第二次 apply：CN 产品数不变（145,061）、journal 行数不变（9,473） |
| 回滚 | CN 产品恢复 146,347；form 非规范恢复 1,214；**指纹与基线完全一致**；journal/备份/review 清空；`integrity_check=ok`、FK 0 违规 |
| 真实库 | 无 `cleanup_cn%` 表、无 `cn-cleanup:` note（**未写**）；副本 372.0 MB、真实库 364.2 MB |
| 时间 | 全流程 ~26 秒（副本，含 copy/apply/幂等/回滚） |

> 验证中临时出现的差异均已解释：apply 后「检测 210 / 无规格标记 5,071」是去重删除连带计数；「异常 30 + 无规格 5,101」中 30 个产品因异常置 NULL 后新落入无规格口径。

## 6. 真实窗口执行步骤（待批准）

1. **备份**：`copy data\drugs.db data\backups\drugs-before-cn-cleanup-20261028.db`（或让 `run_all.py` 自动备份）；确认无并行入库/建站。
2. **真实 dry-run（只读）**：`& $py etl\cleanup_cn_data.py --dry-run` → 核对本报告数字（应一致；若数据有新增，按新数字确认）。
3. **应用**：`& $py etl\cleanup_cn_data.py --apply --allow-real`（脚本会先自动回滚同 run_id 的旧结果，再清洗；单事务）。
4. **核对**：`& $py db\check_data.py`；SQL 抽查：form 非规范 0、参照 0、CN 产品 145,061、删除快照 1,286、review 14,242；抽查 5 个被删产品已不存在、5 个 keeper 仍在。
5. **重建站**：`& $py site\build.py` 等 `== done ==`（页面计数/筛选器会按新 form_base 生效）。
6. **更新计数/文案**：README/About/coverage/CHANGELOG 的 CN 产品数（146,347 → 145,061）与「检测试剂已分流」说明；发布走 `deploy/publish.ps1`（另任务）。
7. **回滚（如异常）**：`& $py etl\cleanup_cn_data.py --rollback --allow-real`（恢复字段/产品/note；建议回滚后再建站）。

## 7. 风险与缺口

1. **补前缀 76 行是启发式**：按「中国 MAH」判定，可能含进口持证商（如国内公司代理进口），需窗口前抽样人工确认；如不放心可先把 `MARK_APPROVAL_PREFIX` 行改为仅标记不改值（脚本一处开关）。
2. **检测试剂仍在产品表**：已标 `other` + note，但列表/计数仍含它们；页面隐藏/过滤需另开 build 任务（本任务禁改 build.py）。
3. **规格异常不纠正**：Macrogol 等仍是无规格（NULL）；若要做「4000 + 64g」正确值，需 parser 规则 + 人工/官方核对，另任务。
4. **近重复未合并**：14,242 产品仍重复计数；需按包装/药码复核，不能一刀切。
5. **note 变长**：5,230+30+218 等标记会加长 note；页面不展示全 note，无 UI 风险，但 DB 体积微增（本次副本未明显增长）。
6. **幂等依赖 run_id**：同一 run_id 二次 apply 会先回滚自身（耗时 ~数秒）；不同 run_id 会叠加标记（设计上只支持一个清洗 run）。
7. **audit 数字漂移**：检测 192→218、待复核 14,572→14,499，因审计后数据有新增；报告以当前实测为准。

## 8. 证据

- `.tmp/cn-cleanup/probe.json` / `probe2.json`（form 67 类、30 异常、批文分桶、原始 NHSA 文本）
- `.tmp/cn-cleanup/dryrun.json`（规则影响面）
- `.tmp/cn-cleanup/validation.json` + `validation.log`（27/27 PASS、幂等/回滚/指纹）
- `.tmp/cn-cleanup/probe_summary.txt` / `probe2_summary.txt`
- 脚本：`etl/cleanup_cn_data.py`

_本报告为清洗批次准备：未写 `data/drugs.db`、未改 `site/build.py`、未跑 git/发布；真实 apply 待窗口批准。_
