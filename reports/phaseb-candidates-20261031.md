# Phase B 候选清单：CJK 主名 → INN（只读）

> 日期：2026-10-31（谷段）｜状态：**只读交付**，未改 `data/drugs.db`、未改 schema、**未合并任何身份**
> 目标池：`substance.name_lang='zh'` 的 **1,791** 条（ATC 全部只到第 4 级＝5 位）
> 产物：`data/sources/phaseb-candidates-20261031.csv`（1,791 行）、`db/phaseb_candidates.py`、本报告
> 上游：`reports/phaseb-prep-20261031.md`、`reports/phaseb-dup-zh-20261031.md`、`reports/task5-inn-mapping-plan.md`

## 0. 结论（先看这段）

| 项 | 数字 | 说明 |
|---|---|---|
| 池内 CJK 主名 | **1,791** | 全部 5 位 ATC，`drug_class='unmapped-cn'` |
| CSV 行数 | **1,791** | 池内每条一行（**含丢弃行**，丢弃行 `置信度=none`），所以行数不缺 |
| `high` | **37** | 唯一候选 + ATC 前 5 位同码 + 盐/酯/立体标记一致 + 有名字证据 |
| `medium` | **33** | 唯一候选 + 有名字证据，但盐型只到 base（盐要落到 `variant.salt`）或 ATC 只到前 4 位 |
| `low` | **2** | 多候选（只列不定案） |
| **判不了（丢弃）** | **1,719** | 分类见 §5，每条都写了原因 |
| 带候选的行合计 | **72（4.0%）** | `置信度 in (high, medium, low)` |
| 候选 INN 不在库 | **47 / 72** | Phase B 落库时需先建英文成分；其中 **5** 条库内已有等价记录，只是写法不同（见 §6.2） |

**一句话**：只靠本地免费来源（库内中文名、CN 注册记录、Wikidata 本地缓存、异名表），1,791 条里能给出候选的只有 **72 条（4.0%）**，与 `task5-inn-mapping-plan.md` 实测的 2.8% 同一量级；剩下 1,573 条（87.8%）根本没有任何「中文名 → 英文 INN」证据，不是阈值卡掉的，是本地确实没有。**没有做任何猜测、机器翻译或音译**。

## 1. 方法

### 1.1 证据渠道（gather）

脚本 `db/phaseb_candidates.py`（只读 `mode=ro`），按任务口径 ①-④ 在前，另加三条**本地名字反查**——因为 ② 要求「中文名/别名对得上」，没有名字反查就无从判定：

| 标签 | 规则 | 实际命中行数* |
|---|---|---|
| `alias_group` | ① `data/substance_aliases.csv` 同物异名组（`lib/aliases.py`；同组写法合并成一个候选） | 1 |
| `atc4_unique` | ② 同 ATC 前 5 位内唯一英文成分 | 结构证据，**不入候选**（114 条写进丢弃理由，见 §5） |
| `atc5_exact` | ③ ATC 第 5 级同码：用候选自带的 7 位 ATC 唯一命中库内成分（把写法对不上的候选归到已有记录） | 9 |
| `nickname/drug_term` | ④ `alias_all`（nickname + drug_term）精确匹配 | 0（命中 1 条「无水硫酸钠→Magnesium Sulfate」，盐型 sodium≠magnesium 被拒，见 §5） |
| `db_inn_zh` / `db_inn_zh_base` | 库内英文成分的 `inn_zh` 反查（精确/归一/剥盐后 base） | 3 |
| `cn_inn_overrides` | `data/cn_inn_overrides.csv`（CN 注册记录，未应用部分） | 45 |
| `cn2en` / `who_inn` / `cn_old_name` / `cn_name_map` | 仓库既有 `CN2EN` 表 / WHO INN 中文名 / 中文旧称表 / `cn_name_map.json`（全部经 `etl/build_cross_market_candidates.py` 的既有加载器复用，不另起一套） | 5 / 0 / 1 / 0 |
| `wikidata_cache` | `data/raw/wikidata/atc_p267.json` 本地缓存：同 QID 的 zh label → en label（+ P267 ATC） | 55 |

\* 一行可能有多个来源，按行计数；`who_inn`、`cn_name_map` 在最终候选里为 0（WHO 快照的 `inn_zh` 全空，`cn_name_map` 仅 3 条中文名且 ATC 不符）。

### 1.2 判定顺序（decide）

对每个候选依次过 5 道闸，任何一道不过就**丢弃并计数**：

1. **复方/多成分**：`cn_inn_overrides status=combination`，或候选名含 `/`、`+` → 丢弃（复方不做成分映射）；
2. **立体标记**：中文名有「右旋/左旋」而候选名里没有 `dex/levo` → 丢弃（不同立体异构体是不同身份）；实测拦下 `右旋酮洛芬→Ketoprofen`、`右旋布洛芬→Ibuprofen` 两条**错误**候选；
3. **ATC**：与池内 ATC 前 4 位都不同 → 丢弃（冲突）；候选无 ATC 可校验 → 丢弃；
4. **盐/酯标记**：中文名的盐/酯/离子词（HCl、硫酸、钠、马来酸、苯丙酸…）与候选名/候选 `variant.salt` 比对 → `partial`（换了盐）、`diff`（完全不同盐）丢弃；`base_only`（候选是母体、盐要落到 `variant.salt`）、`extra`（候选带盐、中文名没带）最多 `medium`；
5. **唯一性**：池内带盐时多候选先按盐型收敛；仍 ≥2 个 → `low`（只列不定案）。

### 1.3 置信度定义与本池的口径说明（请 Lead 复核这一点）

| 级别 | 定义 |
|---|---|
| `high` | 唯一候选 + ATC 前 5 位同码 + 盐/酯/立体标记一致 + 有名字证据（非纯结构推断） |
| `medium` | 唯一候选 + 有名字证据，但盐型只能落到 base/候选多带盐，或 ATC 只到前 4 位，或候选名带剂型词（非单成分 INN 写法） |
| `low` | ≥2 个候选（只列不定案） |
| `none` | 判不了 → 丢弃计数 |

**两处需要说明的口径**（任务规则原文与池内数据有冲突，这里按「不猜」原则处理）：

1. 规则 2 的「唯一 + ATC 类一致 → high；唯一但只到 L4 一致 → medium」按字面执行会得到 **high=0**：池内 1,791 条 ATC **全部只有 5 位**（`SELECT LENGTH(atc)` 只有一行 `5`），与候选的 7 位码最多只能比到第 4 级，永远到不了「第 5 级同码」。所以本报告把 `high` 定义为「**唯一 + 前 5 位同码 + 盐型一致 + 有名字证据**」，把「只有结构证据（ATC4 唯一、中文名对不上）」判为**丢弃**而不是候选。
2. 规则 2 说「多候选 → low」，而纯结构推断（`atc4_unique`）也是「不定案」。实测这类结构线索噪声极大——`R05XX` 里 46 个不同中文名（`氨酚伪麻`、`愈酚待因`…）全被「唯一英文成分」指到 `Guaiacol`，`C05AX` 里 10 个指向 `Cocoa Butter`，`R05FA` 里 8 个指向 `Terpin`——所以**不写成候选**，只在丢弃行的 `理由` 里留线索（`丢弃[仅 ATC4 唯一]：…唯一英文成分 X，但中文名对不上`）。若 Lead 要把它们提为 `low`，改 `db/phaseb_candidates.py` 的 `if not evaluated and not combo and not notes:` 分支（1 处）即可。

## 2. 计数与复核（每个数字一条命令）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$csv = 'data\sources\phaseb-candidates-20261031.csv'
```

| 计数 | 值 | 复核命令 |
|---|---:|---|
| 池内 CJK 主名 | 1,791 | `& $py db/q.py "SELECT COUNT(*) FROM substance WHERE name_lang='zh'"` |
| 池内 ATC 全为 5 位 | 1,791 | `& $py db/q.py "SELECT LENGTH(atc) len, COUNT(*) FROM substance WHERE name_lang='zh' GROUP BY 1"` → 只有 `5 / 1791` |
| CSV 行数 | 1,791 | `(Import-Csv $csv).Count` |
| high | 37 | `(Import-Csv $csv \| Where-Object {$_.置信度 -eq 'high'}).Count` |
| medium | 33 | `(Import-Csv $csv \| Where-Object {$_.置信度 -eq 'medium'}).Count` |
| low | 2 | `(Import-Csv $csv \| Where-Object {$_.置信度 -eq 'low'}).Count` |
| none（判不了） | 1,719 | `(Import-Csv $csv \| Where-Object {$_.置信度 -eq 'none'}).Count` |
| 带候选行合计 | 72 | `(Import-Csv $csv \| Where-Object {$_.置信度 -ne 'none'}).Count` |
| 候选 INN 不在库 | 47 | `(Import-Csv $csv \| Where-Object {$_.置信度 -ne 'none' -and -not $_.候选substance_id}).Count` |
| 丢弃分类 | 见 §5 | `Import-Csv $csv \| Where-Object {$_.置信度 -eq 'none'} \| ForEach-Object { ($_.理由 -split '\]')[0] + ']' } \| Group-Object \| Sort-Object Count -Descending` |
| ATC4 组内英文成分数分布 | 0→224 / 1→137 / ≥2→1,430 | `& $py db/q.py "WITH en AS (SELECT substr(atc,1,5) a4, COUNT(DISTINCT substance_id) n FROM substance WHERE name_lang='en' AND length(atc)>=5 GROUP BY 1) SELECT COALESCE(en.n,0), COUNT(*) FROM substance s LEFT JOIN en ON en.a4=substr(s.atc,1,5) WHERE s.name_lang='zh' GROUP BY 1 ORDER BY 1"` |
| ④ 别名指向 zh 成分 | 0 | `& $py db/q.py "SELECT 'nickname' k, COUNT(*) n FROM nickname a JOIN substance b ON b.substance_id=a.substance_id WHERE b.name_lang='zh' UNION ALL SELECT 'drug_term', COUNT(*) FROM drug_term a JOIN substance b ON b.substance_id=a.substance_id WHERE b.name_lang='zh'"` |
| WHO 快照中文名 | 1,737 行 / 0 条有中文名 | `& $py -c "import csv;rows=list(csv.DictReader(open('data/who_inn_names.csv',encoding='utf-8-sig')));print(len(rows), sum(1 for r in rows if (r.get('inn_zh') or '').strip()))"` → `1737 0` |

复跑脚本本身：

```powershell
& $py db/phaseb_candidates.py                                   # 写 data/sources/phaseb-candidates-20261031.csv
& $py db/phaseb_candidates.py --summary .tmp/phaseb/summary.json --show 20   # 加分类计数 JSON + 样例
```

## 3. 与既有候选表的关系

仓库已有一张 `data/cross_market_merge_candidates.csv`（`etl/build_cross_market_candidates.py` 产物，`candidate_type=substance_merge`），池内有 **211** 行。本次与它的差异：

| 关系 | 数量 | 说明 |
|---|---:|---|
| 既有表有、本次也有候选 | 50 | 认同（本次另加了 ATC/盐型/立体校验和置信度分级） |
| 既有表有、本次判不了 | 161 | 其中 `atc4` 结构证据 131 条（本次判「仅 ATC4 唯一」，只留线索）；另 30 条是 `existing_override` / `cn2en` 候选被 ATC 冲突（19）、复方（13）、ATC 无法校验（8）、盐/酯（5）、立体异构（2）拦下 |
| 本次有、既有表没有 | 22 | 主要来自 `wikidata_cache`、`cn2en` 与异名组；既有表按 `cn_` 前缀建索引，未覆盖这几条 |

与 `reports/phaseb-dup-zh-20261031.md` §3 的 4 组「CJK-only 疑似重复」对齐结果：

| CJK 记录 | 本次结论 |
|---|---|
| 炔诺酮 | `medium` → `norethisterone`（ATC G03AA vs G03AC01，只到前 4 位；库内 `Noretisterona` 因 G03DC02 冲突被拒） |
| 曲安西龙 | 丢弃[ATC 冲突]（`Triamcinolone` A01AC vs 池内 H02AB） |
| 多黏菌素E甲磺酸钠 | 丢弃[ATC 冲突]（`Colistimethate` J01XB01 vs 池内 A07AA） |
| 地喹氯铵 | 丢弃[ATC 冲突]（`Decualinio` G01AC05 / `Dequalinium` R02AA02 vs 池内 A01AB） |

**本次没有合并任何记录**，15 组同名成分仍原样保留；上面 4 组的处置只能由 Phase B 窗口单独验收。

## 4. 抽查 12 条 `high`（人工看是否合理：10 条 ✅、2 条身份对但写法待核）

| # | substance_id | 池内中文主名 | ATC | 候选 INN | 候选 substance_id | 人工核对 |
|---|---|---|---|---|---:|---|
| 1 | cn-9be0c6ea3c | 甘羟铝 | A02AB | Aluminium glycinate | — | ✅ 合理（甘羟铝＝二羟基氨基乙酸铝，ATC A02AB07 正对） |
| 2 | cn-ac149aec0e | 磷酸铝 | A02AB | aluminium phosphate | — | ✅ 合理（A02AB03） |
| 3 | cn-44d979c469 | 吉法酯 | A02BX | gefarnate | — | ✅ 合理（A02BX07） |
| 4 | cn-c8e70a4bd8 | 瑞巴派特 | A02BX | rebamipide | — | ✅ 合理（A02BX14） |
| 5 | cn-b6e78d9b17 | 羟甲烟胺 | A05AB | nicotinyl methylamide | — | ✅ 合理（A05AB01） |
| 6 | cn-4843d6cbec | 蛋氨酸 | A05BA | Methionine | methionine | ✅ 合理（库内已有记录；同组 `Dl-Methionine` 因 A16AX 冲突被拒） |
| 7 | cn-c78abb9d43 | 水飞蓟素 | A05BA | silibinin A | silibinina | ⚠️ 身份对（ATC A05BA03），但候选写法是「组分名」，INN 应是 silymarin/silibinin，见 §6.2 |
| 8 | cn-9b556b8ffa | 美沙拉嗪 | A07EC | mesalazine | mesalamine | ✅ 合理（mesalazine＝mesalamine，USAN/INN 写法差异，ATC A07EC02） |
| 9 | cn-1b31a7a1f4 | 卡巴匹林钙 | B01AC | carbaspirin calcium | — | ⚠️ 身份对（ATC B01AC08），INN 正式写法是 carbasalate calcium，见 §6.2 |
| 10 | cn-b77647d164 | 吲哚布芬 | B01AC | indobufen | — | ✅ 合理（ATC B01AC10） |
| 11 | cn-b46751b5ce | 玻璃酸酶 | B06AA | Hyaluronidase | hyaluronidase | ✅ 合理（库内已有记录，ATC B06AA03） |
| 12 | cn-9d914cf7e9 | 胰蛋白酶 | B06AA | trypsin | — | ✅ 合理（B06AA07） |

**37 条 high 里有 4 条的「候选写法」需要核对**（身份／ATC 都对，只是名字不是正式 INN 写法；这也是本报告把 `high` 限定为「身份候选」而不是「可直接改名」的原因）：

| 池内 | 候选 | 问题 | 库内已有更好写法 |
|---|---|---|---|
| 水飞蓟素 | silibinin A | 组分名，不是 INN（ATC A05BA03 = silymarin） | `silibinin`（A05BA）、`silibinina`（A05BA03） |
| 卡巴匹林钙 | carbaspirin calcium | USAN 写法；INN 为 carbasalate calcium | 库内无（需新建或按 INN 写法补） |
| 放线菌素D | actinomycin | 家族名；INN 为 dactinomycin（ATC L01DA01） | `dactinomycin` |
| 丝裂霉素 | mitomycins | 复数/类名；INN 为 mitomycin（ATC L01DC03） | `mitomycin` |

另有 3 条 `high` 的候选写法在库内也存在等价记录（`硼酸→orthoboric acid` 而库内是 `boric-acid`；`间苯二酚→resorcin` 而库内是 `resorcinol`；`苯噻啶→pizotyline` 而库内是 `pizotifen`）。**落库前必须先做写法归一，否则会给同一成分建出第二条记录。**

## 5. 判不了（1,719 条）的分类

| 类别 | 条数 | 典型理由 |
|---|---:|---|
| `无名字证据` | 1,459 | 本地没有任何中文名→INN 证据；ATC 前 5 位组内英文成分 0 个（224 行）或多个（无法唯一定位） |
| `仅 ATC4 唯一` | 114 | 组内只有 1 个英文成分，但中文名对不上（例：`丁香罗勒口服→Calcium Silicate`、`罗布麻→Reserpine`；46 个 `R05XX` 复方名指向 `Guaiacol`、10 个 `C05AX` 指向 `Cocoa Butter`）→ 只留线索，不当候选 |
| `复方/多成分` | 99 | `cn_inn_overrides status=combination`，按方案 §6 不映射 |
| `ATC 冲突` | 30 | 候选 ATC 与池内前 4 位都不同（含 `曲安西龙`、`多黏菌素E甲磺酸钠`、`地喹氯铵`、`葡萄糖粉剂 V02DC→Dextrose B05BA03`） |
| `ATC 无法校验` | 8 | 候选在库但无 ATC（例：`亚硒酸钠→Selenious Acid`），或不在库且缓存无出处 |
| `盐/酯不一致` | 7 | 换了盐/酯（例：`铝镁→aluminium phosphate`、`无水硫酸钠→Magnesium Sulfate`） |
| `立体异构` | 2 | `右旋酮洛芬→Ketoprofen`、`右旋布洛芬→Ibuprofen`（应为 dexketoprofen / dexibuprofen，库内无 → 丢弃而不是错配） |

> 说明：`无名字证据` 的 1,459 条不是「规则太严」——它们连一条候选都没产生；把这部分补上只能靠 Phase B 的 Wikidata 在线批（1,791 条 × 2–3 s ≈ 60–90 min，见 `task5-inn-mapping-plan.md` §4）或 CN 注册名人工补录。

## 6. 下一步（给 Phase B 写库阶段）

### 6.1 可以直接进下一轮核对

- **37 条 `high`**：身份已定，落库方式（改名 / 新增 substance / 挂 variant）仍需选一条。
- **33 条 `medium`**：盐型要落到 `variant.salt`（如 `酒石酸艾格司他→Eliglustat`、`磷酸雌莫司汀→Estramustine`），或 ATC 只到前 4 位（如 `炔诺酮→norethisterone`、`舒洛地特→sulodexide`）。
- **2 条 `low`**：`钠钾葡萄糖`、`醋酸钠葡萄糖` 都是复方原料名，候选 `Glucose | intravenous sugar solution` 无法定案，建议直接按复方处理（丢弃）而不是进候选池。
- **库里有没有**：72 条候选里 25 条的 INN 已在库（可直接挂 `variant` / 改名），47 条不在库（需先建英文成分）。

### 6.2 落库前必须先做的两件事（否则会产生重复成分）

1. **写法归一**：先把候选名对到库里已有的 INN 写法（`orthoboric acid→boric-acid`、`resorcin→resorcinol`、`pizotyline→pizotifen`、`actinomycin→dactinomycin`、`mitomycins→mitomycin`；`carbaspirin calcium` 库内没有对应记录，需按 INN `carbasalate calcium` 新建），再决定「改名 / 新建」。
2. **重复记录**：`Pizotifen` 在库里有 3 条同 ATC5 码记录（`pizotifen` / `pizotifeno` / `pizotifen-malate`），`Silibinin`/`Silibinina` 同物两写法——这两处和 `phaseb-dup-zh-20261031.md` §2 的 manitol/mannitol 一样，需要单独的合并窗口（备份 + manifest + 合并前后计数），不在本任务范围。

### 6.3 不在本次范围（明确不做）

- 不改 `inn_en` / `inn_zh`，不改 `name_lang`，不建新 substance，不合并记录；
- 不判「两种药能否互换」、不做剂量换算；
- 不用机器翻译/音译补名字。

## 7. 边界与复跑

- 只读：DB 连接 `file:...?mode=ro`；未写 `data/drugs.db`、未改 `db/schema.sql`、未跑 build、未发版。
- 代码：`db/phaseb_candidates.py`（Python 3.12，`from __future__ import annotations`，复用 `lib/aliases.py`、`etl/build_cross_market_candidates.py` 的词表与加载器、`etl/normalize_name.py` 的剂型词、`etl/normalize_salts.py` 的盐型词表，不另起一套）。
- 复跑两次输出一致（无随机、无时间戳进 CSV）：

```powershell
& $py db/phaseb_candidates.py --csv .tmp/phaseb/a.csv --quiet
& $py db/phaseb_candidates.py --csv .tmp/phaseb/b.csv --quiet
(Get-FileHash .tmp\phaseb\a.csv).Hash -eq (Get-FileHash .tmp\phaseb\b.csv).Hash   # True
```

_本报告为只读准备：所有结论都是「候选」，不是已定案的数据变更。_
