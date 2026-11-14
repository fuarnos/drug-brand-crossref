# T17 / H2：成分中文名与基础成分 / 盐型一致（v0.11.8 P0）

- 任务：task-2（工位 **phaseb-data**），对应用户评审第二轮 **H2**
- 日期：2026-11-15（库内 manifest 时间戳 `2026-11-14T18:49:25Z`）
- 结论一句话：**339 条成分中文名从「盐型名」改回基础成分名**（`caffeine` 枸橼酸咖啡因 → 咖啡因），
  盐型继续留在 `variant.salt / salt_code`；旧写法以 `nickname`（`kind=misnomer`）保留检索能力；
  **产品 / 组件 / 规格 / collision 数据一行未动**。

---

## 0. 结论（先看这一屏）

| 项 | 数字 |
|---|---|
| 扫全库含中文名成分 | 3,103 条（`substance.inn_zh` 非空） |
| 命中「中文名含盐型词」（宽口径 80 词系） | **1,117 条** |
| **可修正 → 已写库** | **339 条**（`confidence=high` 235 / `medium` 104） |
| **丢弃（不写库，计数留痕）** | **778 条**（原因分类见 §5） |
| `substance.inn_zh` 更新行数 | 339 行（单事务，毫秒级） |
| `nickname` 新增 | 339 条（`kind=misnomer`，`confidence=community`，`source` 带 T17 标记） |
| 产品 / 组件 / 变体 / collision | **0 变化**（494,992 / 650,358 / 14,244 / 25,088+925） |
| 旧写法可检索 | `cli.py "枸橼酸咖啡因"` → 命中 caffeine（misnomer 别名），`cli.py "咖啡因"` 同 |
| 页面影响（旧产物 v0.11.7） | 339 个成分页里旧盐型名共出现 **2,378 次**；`/drug/acetaminophen.html` **7 次**，重建后全变基础名 |
| 回滚 | manifest 全量 old→new；副本库演练：还原 339 行 + 删 339 条，二次回滚 exit 0 |

用户原始用例（`/drug/acetaminophen.html` 复方行）：

```html
<!-- 旧产物 site/dist/drug/acetaminophen.html（v0.11.7，改前） -->
Acetaminophen<span class="name-zh" data-inn-zh hidden style="display:none"> 对乙酰氨基酚</span> 500 mg
+ Caffeine<span class="name-zh" data-inn-zh hidden style="display:none"> 枸橼酸咖啡因</span> 65 mg

<!-- 新库 + 同一模板函数 _combo_line_html()（改后） -->
Acetaminophen<span class="name-zh" data-inn-zh hidden style="display:none"> 对乙酰氨基酚</span> 500 mg
+ Caffeine<span class="name-zh" data-inn-zh hidden style="display:none"> 咖啡因</span> 65 mg
```

> 含量 `65 mg` 一字未改：那是 `product_component` / `strength` 里的记录原样（盐型基准），
> 本条只改**名字**，不改含量、不改基准、不做换算。

---

## 1. 口径与基线对账（Lead 779 / 237 / 542 能复算）

Lead 的基线用 11–15 个中文盐型词做 `LIKE` 统计；本任务用**更宽**的口径，先把「可能写错」的全捞出来再逐条判：

| 口径 | SQL 要点 | 现查 |
|---|---|---|
| Lead 11 词（枸橼酸/盐酸/硫酸/磷酸/马来酸/琥珀酸/钠/钾/钙/镁/铵） | `inn_zh LIKE '%词%'` 取并集 | 703 |
| Lead 15 词（+酒石酸/富马酸/甲磺酸/苯磺酸） | 同上 | **780**（与 Lead 779 差 1 行 = 词表微差） |
| 其中 variant 层有盐型 | `variant.salt_code` 或 `variant.salt` 非空 | **252**（Lead 237，差 15 行：本报告把 `salt` 也算进来） |
| **本报告宽口径 80 词系** | 见 `etl/apply_inn_zh.py` 的 `SALT_ZH2EN / CATION_ZH2EN / DETECT_ZH` | **1,117** |

宽口径故意包含「整名可能刚好合法」的词（铵、氢氧化、氧化、碳酸、碘…）——
这 80 个词系里凡是**不该剥**的，全部进 §5 的丢弃桶并写明理由，不静默跳过。
词表结构：52 个酸根/成盐前缀（`SALT_ZH2EN`，含 苯磺、单磷酸、甲硫酸 这类少见的）＋
22 个阳离子/有机碱后缀（`CATION_ZH2EN`）＋ 9 个「整名可能合法」的检测词（`DETECT_ZH` 里的 铵/氢氧化/氧化/碳酸/碳酸氢/碱式/碘/氯/溴）。

复核命令（写库前的库 = `data/backups/drugs-20261114-104920.db`，用同样 SQL 可复算）：

```sql
SELECT COUNT(*) FROM substance WHERE trim(coalesce(inn_zh,''))<>''
  AND (inn_zh LIKE '%枸橼酸%' OR inn_zh LIKE '%盐酸%' OR ... );  -- 780
```

---

## 2. 产物（都在仓库里，可复核）

| 文件 | 大小 | 说明 |
|---|---|---|
| `data/sources/inn_zh_salt_forms_20261115.csv` | 215,118 B | **清单 1,117 行**：可修正 339 + 丢弃 778，逐条带 `substance_id / inn_en / inn_zh_old / inn_zh_new / salt_word / salt_variants / method / source / confidence / verdict / reason / evidence`；sha256 `1A5638ED…4985D2` |
| `data/sources/inn_zh_salt_fix_manifest_20261115.json` | 121,847 B | **撤销清单**：`mode=fix_salt_forms`、db、csv+sha256、时间、339 行 old→new 全量 + 每条 nickname 的 `alias_norm` |
| `data/backups/drugs-20261114-104920.db` | 452,550,656 B | 写库前备份（sha256 `3F0AE738…B807CB`） |
| `data/inn_zh_backfill.csv` | 899 行 | **280 行候选名同步改正**（原候选=盐型名 → 基础名，`evidence` 追加 T17 标记），防止重建后回填又把盐型名写回去 |
| `data/ingredient_names_i18n.csv` / `data/translations.csv` / `data/label_translations.csv` | 12,644 行 / 28,093 行 / 70 行 | 派生翻译表**重跑**（版本 `2026-10-28.1` → `2026-11-14.1`），客户端术语表随之更新，见 §6.5 |
| `etl/apply_inn_zh.py` | — | 新增 4 个模式，**原「只填空值」保护逻辑一行未改** |

`etl/apply_inn_zh.py` 新增：

```text
--build-salt-fix-list          只读 DB 重新生成清单 CSV（可复算）
--fix-salt-forms [--apply]     盐型名修正（默认 dry-run；--apply 单事务写库 + manifest）
--rollback <manifest>          兼容盐型清单：inn_zh 还原 + 删掉本次新增的 nickname（幂等）
--sync-backfill-csv [--apply]  把修正同步进 data/inn_zh_backfill.csv 的候选名
```

---

## 3. 判定规则（为什么这 339 条能改、其余不能）

只做**字符串剥离**，不翻译、不造句、不音译。判定顺序（`_classify_salt_row()`）：

1. `inn_en` 不是英文（中文成分名 `cn-*` / 西语名）→ **丢弃**（没有可对照的英文成分名，无从判断剥完是否正确）
2. `inn_en` 自带盐型词（`Sodium Bicarbonate`、`Aluminum Hydroxide`、`Iron Sucrose`、`Chondroitin Sulfate`，
   含 `dinitrate / triphosphate` 这类倍数前缀）→ **丢弃**（该成分本身**就是**这个盐，盐型词在中文名里合法）
3. 从两端剥盐型词（先词尾阳离子/有机碱，再词头酸根；**「铵」不进剥离词表**——季铵盐的铵属于基础名，如苯扎氯铵）
4. 剥完的残形必须过 5 道闸门，否则 **丢弃**：长度 ≥2 中文字 / 不以「盐·根·离子」结尾 /
   不是金属离子词 / 不与另一成分中文名重名（会撞名）/ 残形自身不是盐型词（`碘化` 这类，`依地酸` 这类以「酸」结尾的例外）
5. 证据分级：`variant` 层有对应盐型 → `high`（235 条）；只有构词证据 → `medium`（104 条，逐条人工过了一遍）

**人工复核覆盖（写死在代码里，清单 `reason` 列可见）**

| substance_id | 决定 | 理由 |
|---|---|---|
| `methylprednisolone` | 剥 → 甲泼尼龙 | 甲泼尼龙琥珀酸钠：酯盐复合后缀，base 是甲泼尼龙 |
| `adenosine-triphosphate` | 剥 → 三磷酸腺苷 | 磷酸在「三磷酸」结构里，base 名即三磷酸腺苷 |
| `cytidine-triphosphate` | 剥 → 三磷酸胞苷 | 同上 |
| `valproic-acid` | 剥 → 丙戊酸 | 「戊酸」是拼词巧合（丙戊酸），base 名本身带「酸」 |
| `nitroglycerin` | 不剥 | 硝酸甘油：硝酸是硝酸酯的一部分，剥完「甘油」是另一个成分 |
| `lactasin` | 不剥 | 乳酸菌素：整名就是 lactasin，剥完「菌素」不是成分名 |
| `mesna` | 不剥 | 美司钠：钠是 INN 自带（mesna） |
| `sucralfate` | 不剥 | 硫糖铝：整名就是 sucralfate |
| `nitroprusiato` | 不剥 | 硝普钠：西语名 nitroprusside，剥完「硝普」不是成分名 |
| `cefetamet` | 不剥 | 盐酸头孢他美酯：酯是衍生物（cefetamet pivoxil），base 是头孢他美，剥到酯层反而写错 |
| `ytrio-citrato-90y` | 不剥 | 枸橼酸钇[90Y]：放射性核素名，残形带同位素标记 |

---

## 4. 写库与回滚（写前备份 + manifest + 副本演练）

```powershell
# ① 备份（写前）
Copy-Item data\drugs.db data\backups\drugs-20261114-104920.db
# ② 副本库演练（.tmp，不碰真实库）
Copy-Item data\drugs.db .tmp\phasebdata-t17\rehearsal.db
& $py etl/apply_inn_zh.py --db .tmp\phasebdata-t17\rehearsal.db --fix-salt-forms            # dry-run：339 行 / 冲突 0
& $py etl/apply_inn_zh.py --db .tmp\phasebdata-t17\rehearsal.db --fix-salt-forms --apply --manifest .tmp\...\undo_saltfix_rehearsal.json
& $py etl/apply_inn_zh.py --db .tmp\phasebdata-t17\rehearsal.db --rollback .tmp\...\undo_saltfix_rehearsal.json
# ③ 真实库（只跑一次）
& $py etl/apply_inn_zh.py --fix-salt-forms --apply --manifest data\sources\inn_zh_salt_fix_manifest_20261115.json
# → 已修正 339 行 inn_zh；新增 nickname 339 条
```

演练与幂等证据（副本库 `.tmp/phasebdata-t17/rehearsal.db`）：

| 步骤 | 结果 |
|---|---|
| dry-run | 可修正 339 / 冲突 0 / 幂等跳过 0 |
| `--apply` | 改 339 行 + 增 339 nickname |
| 再跑一次 `--apply` | **「没有需要修正的行」——0 行**（幂等，不重复刷库） |
| `--rollback` | 恢复 inn_zh **339 行**、删 nickname **339 条**（回到 baseline：`nickname=57`、含盐酸 264 行） |
| 二次 `--rollback` | `已恢复 0 行；删除 0 条`，**exit 0**（幂等，不报冲突） |
| 回滚后重放 `--apply` | 又改 339 行（可反复，安全） |
| **真实库写后复跑 dry-run** | `本次将写库 0 行；冲突 0；幂等跳过 339`（现库状态与清单完全一致） |
| **真实库写后复跑 `--sync-backfill-csv`** | `命中 0 行，改动 0 行`（回填 CSV 也已是修后状态） |

manifest 关键字段（`data/sources/inn_zh_salt_fix_manifest_20261115.json`）：

```json
{"tool":"etl/apply_inn_zh.py --fix-salt-forms","mode":"fix_salt_forms",
 "committed":true,"created_at":"2026-11-14T18:49:25+00:00",
 "committed_at":"2026-11-14T18:49:25+00:00","updated":339,"nicknames_created":339,
 "rows":[{"substance_id":"caffeine","old_inn_zh":"枸橼酸咖啡因","new_inn_zh":"咖啡因",
          "nickname_alias":"枸橼酸咖啡因","nickname_alias_norm":"枸橼酸咖啡因",
          "nickname_created":true, ...}]}
```

`created_at == committed_at` ⇒ 事务在 1 秒内提交；写库期间无其它写操作。

---

## 5. 丢弃 778 条：按原因 × 盐型词分类（Lead 要求可复算）

工具口径：`data/sources/inn_zh_salt_forms_20261115.csv` 里 `verdict != 'fix'` 的行，`reason` 列即分组依据。

| 原因（不可修正的具体原因） | 条数 | 该组里的盐型词（前 4） |
|---|---|---|
| `inn_en` 本身不是英文（中文 `cn-*` / 西语名） | **621** | （未剥）×199、盐酸 ×103、钠 ×72、钙 ×25 |
| 盐型词在词中/词尾但剥不动（如氯霉素、苯扎氯铵、氯雷他定） | **71** | （未剥）×71 |
| `inn_en` 自带盐型词（成分本身就是盐：碳酸氢钠、氢氧化铝、蔗糖铁…） | **65** | 钠 ×13、钙 ×11、（未剥）×6、锌 ×4 |
| 人工复核决定不剥（§3 表里的 7 条） | **7** | 钠 ×2、盐酸 ×1、乳酸 ×1、硝酸 ×1 |
| 残形里仍有盐型词（混合物名：缩合葡萄糖氯化钠、右旋糖酐20氯化钠、长春西汀氯化钠…） | **6** | 钠 ×5、镁 ×1 |
| 残形过短/无中文（碘化油、葡萄糖酸锑钠、依地酸钙钠） | **3** | 碘化 ×1、钠+葡萄糖酸 ×1、钠+依地酸 ×1 |
| 残形与另一成分中文名重名（甘珀酸钠/醋酸甲地孕酮/水杨酸三乙醇胺） | **3** | 钠 ×1、醋酸 ×1、三乙醇胺 ×1 |
| 剥掉阳离子后剩下是酯名（头孢孟多酯钠） | **1** | 钠 ×1 |
| 残形本身仍是盐型词（碘化钾 → 「碘化」） | **1** | 钾 ×1 |
| **合计** | **778** | |

其中 **621 条（79.8%）** 是 `inn_en` 本身就是中文（`name_lang='zh'` 的 CN 成分）——
按任务口径「inn_en 本身是中文 → 不写库、丢弃并计数」，本工具不碰它们；
它们的 `inn_zh` 与 `inn_en` 内容相同，要修得先有英文 INN 对应，属于另一条任务线。

> 写后复核：现库含「盐酸」的行从 264 → **110**，其中 **109 行是 `inn_en` 为中文的 `cn-*` 成分**，
> 唯一剩下的英文名行就是人工决定不剥的 `cefetamet`（盐酸头孢他美酯）。数字自洽。

可修正 339 条的盐型词分布（前 14）：
盐酸 ×153、钠 ×53、硫酸 ×22、甲磺酸 ×13、醋酸 ×11、磷酸 ×9、富马酸 ×8、枸橼酸 ×8、
氢溴酸 ×7、马来酸 ×6、酒石酸 ×6、硝酸 ×6、二钠 ×5、甲苯磺酸 ×5。

---

## 6. 验收清单（逐条给证据）

### 6.1 before / after 计数（同一 SQL，备份库 vs 现库）

```powershell
& $py db/q.py "SELECT COUNT(*) FROM substance WHERE inn_zh LIKE '%盐酸%'"   # 备份库 / 现库各跑一次
```

| 指标 | before | after | Δ |
|---|---|---|---|
| `substance.inn_zh` 非空 | 3,103 | 3,103 | 0（只改名，不删名） |
| `nickname` | 57 | **396** | +339 |
| `product` | 494,992 | 494,992 | **0** |
| `product_component` | 650,358 | 650,358 | **0** |
| `variant` | 14,244 | 14,244 | **0** |
| 命中「盐酸」 | 264 | 110 | −154 |
| 命中「硫酸」 | 48 | 24 | −24 |
| 命中「磷酸」 | 40 | 28 | −12 |
| 命中「枸橼酸」 | 24 | 16 | −8 |
| 命中「马来酸」 | 13 | 7 | −6 |
| 命中「琥珀酸」 | 10 | 7 | −3 |
| 命中「钠」 | 199 | 141 | −58 |
| 以「钠」结尾 | 174 | 116 | −58 |
| 命中「铵」 | 38 | 38 | **0**（铵从不剥离） |
| 重复中文名组数（`GROUP BY inn_zh HAVING COUNT(*)>1`） | 14 | 14 | **0**（没造出撞名） |

`db/check_data.py`：**exit 0**（全文无告警；`collisions(severe) 25,088 / warning 925` 与写前一致，
`nickname 396`、`aliases(total) 1,413`、`aliases(community) 938` 随之变化——这是本次新增别名的必然结果，见 §7）。

### 6.2 `caffeine`（用户原始用例）

```text
$ & $py db/q.py "SELECT substance_id, inn_en, inn_zh FROM substance WHERE substance_id IN ('caffeine','lidocaine','clindamycin','lysine','afatinib','methylprednisolone')"
afatinib             | Afatinib             | 阿法替尼
caffeine             | Caffeine             | 咖啡因
clindamycin          | Clindamycin          | 克林霉素
lidocaine            | Lidocaine            | 利多卡因
lysine               | Lysine               | 赖氨酸
methylprednisolone   | Methylprednisolone   | 甲泼尼龙

$ & $py db/q.py "SELECT variant_id, salt, salt_code FROM variant WHERE substance_id='caffeine'"
caffeine            |            |
caffeine-citrate    | citrate    | citrate
caffeine-anhydrous  | anhydrous  |
```

`LOWER(inn_en)='caffeine'` 不变； citrate / anhydrous 变体仍在（盐型信息没丢，页面自己在 variant 层呈现）。

### 6.3 旧写法仍可检索（nickname 精确别名）

```text
$ & $py cli.py "枸橼酸咖啡因"
note  = 「枸橼酸咖啡因」是 咖啡因 的常见误称；下面按成分列出商品名
alias = 枸橼酸咖啡因 -> 咖啡因 (misnomer, community; T17 盐型名剥离：合并前 substance.inn_zh)
 1. Headache Relief Extra Strength  [US]  Acetaminophen + Aspirin + Caffeine  ...

$ & $py cli.py "咖啡因"
 1. 氨基比林咖啡因片  [CN] ...   （仍是商品名 contains 命中，逻辑没变）
```

另抽 6 条旧写法（全部命中正确成分，并明确标注「常见误称」）：
`盐酸二甲双胍 → 二甲双胍`、`硫酸阿托品 → 阿托品`、`枸橼酸西地那非 → 西地那非`、
`盐酸昂丹司琼 → 昂丹司琼`、`甲磺酸伊马替尼 → 伊马替尼`、`华法林钠 → 华法林`。

### 6.4 测试

| 套件 | 结果 |
|---|---|
| `& $py db/check_data.py` | **exit 0** |
| `& $py -m unittest discover -s etl -t etl` | **Ran 55 tests — OK** |
| `& $py -m unittest discover -s lib -t lib` | **Ran 61 tests — OK** |
| `& $py tests/trilingual/run_tests.py` | **72 例 / 69 通过**；Top-5 98.6% / Top-1 95.5%；en 98.4 / es 98.3 / zh 99.1 —— **与基线逐项相同**（基线 72/69、98.6%/95.5%） |
| `& $py deploy/ci_checks.py --fast` | **12 项：PASS 8 / FAIL 0 / SKIP 4**，exit 0（dist-integrity 125,516 文件 / 0 字节 0 / sitemap 66,300 URL） |

### 6.5 派生翻译表重跑（Lead 追加要求，2026-11-14 晚）

`data/ingredient_names_i18n.csv` / `data/translations.csv` / `data/label_translations.csv` 是
`etl/build_translation_tables.py` 从库生成的**派生快照**，页面正文不读它们（读 DB），
但 `site/build.py` 的 `data/terms.json`（客户端术语表）从 `ingredient_names_i18n.csv` 派生 ——
不重跑的话客户端名称表仍会把盐型名发上线。

```powershell
& $py etl/build_translation_tables.py     # exit 0；只读 DB，不写库
```

| 文件 | before | after | sha256（after） |
|---|---|---|---|
| `data/ingredient_names_i18n.csv` | 12,649 行 / 2,328,444 B / `2026-10-28.1` | **12,644 行** / 2,346,512 B / `2026-11-14.1` | `3BC4DDA6…2A5C4D` |
| `data/translations.csv` | 19,864 行 / 2,602,263 B | **28,093 行** / 3,870,061 B | `4AE6E0E1…D6C72F6` |
| `data/label_translations.csv` | 70 行 / 23,846 B | 70 行 / 23,846 B（只有版本列变） | `FA1230C1…DE200D8` |

`name_zh` 变化 **583 行**，拆开看：

| 组 | 行数 | 说明 |
|---|---|---|
| A 盐型名 → 基础名 | **339** | **本次 T17 的全部修正**（与 DB 一一对应，如 `abiraterone 醋酸阿比特龙→阿比特龙`） |
| B 空 → 有中文名 | 235 | 旧快照是 2026-10-28 的，之后其它任务的 `inn_zh` 回填没有进过这份表（如 `aceclofenac → 醋氯芬酸`） |
| C 其它改名 | 9 | 品牌名 → 通用名等（如 `fluoxetine 百优解→氟西汀`、`methylphenidate 专注达→哌甲酯`），同样来自 2026-10-28 之后的其它任务 |

行数差（12,649 → 12,644）与 `translations.csv` +8,229 行（`product_name` 16,000 → 24,000 段）也是同一原因：
旧快照之后别的任务合并了 12 个 `cn-*` 成分、新增 7 个成分、并把 FR/HK/SG 三个市场接进了 `COUNTRY_LANG`。
**即：本次重跑把「我这 339 条」和「2026-10-28 以来别人改的」一起刷进了派生表**——
这两份是生成物（不进语义、可随时重生成），构建会读到最新版；如需把漂移拆开单独发布，请 Lead 决定。

`name_zh_hant` 变化 0 行（繁体走简繁转换，跟随 `name_zh` 在构建时生成）。

### 6.6 页面抽检（四语同一份映射；18 个复方/单方成分）

成分页、品牌页「成分卡」、配方差异表、复方行全部读同一个入口
`site/build.py::_sub_zh_name()` → `load_substance_zh()`（`SELECT substance_id, inn_zh FROM substance`，唯一数据源），
中文名以 `<span class="name-zh" data-inn-zh hidden>` 输出：**zh / zh-Hant 界面可见，en / es / fr 界面隐藏**
（`applyInnZh()` 按语言开关）——所以四语页面拿到的是同一份、同一个名字。

用同一模板函数 `_combo_line_html()` + 新库数据渲染（未构建 dist，避免与 site-ui/Lead 构建冲突）：

```text
Acetaminophen<span class="name-zh" data-inn-zh hidden …> 对乙酰氨基酚</span> 500 mg
+ Caffeine<span class="name-zh" …> 咖啡因</span> 65 mg          ← 改后
```

| # | substance_id | inn_en | inn_zh（改前） | inn_zh（改后） | salt_word | 佐证 | confidence |
|---|---|---|---|---|---|---|---|
| 1 | `caffeine` | Caffeine | 枸橼酸咖啡因 | **咖啡因** | 枸橼酸 | variant=citrate | high |
| 2 | `lidocaine` | Lidocaine | 盐酸利多卡因 | **利多卡因** | 盐酸 | variant=hcl,hydrochloride | high |
| 3 | `clindamycin` | Clindamycin | 克林霉素磷酸酯 | **克林霉素** | 磷酸酯 | none | medium |
| 4 | `lysine` | Lysine | 赖氨酸磷酸氢钙 | **赖氨酸** | 磷酸氢钙 | none | medium |
| 5 | `afatinib` | Afatinib | 马来酸阿法替尼 | **阿法替尼** | 马来酸 | none | medium |
| 6 | `methylprednisolone` | Methylprednisolone | 甲泼尼龙琥珀酸钠 | **甲泼尼龙** | 钠 | manual | medium |
| 7 | `sildenafil` | Sildenafil | 枸橼酸西地那非 | **西地那非** | 枸橼酸 | variant=citrate | high |
| 8 | `metformin` | Metformin | 盐酸二甲双胍 | **二甲双胍** | 盐酸 | variant=hcl,hydrochloride | high |
| 9 | `ondansetron` | Ondansetron | 盐酸昂丹司琼 | **昂丹司琼** | 盐酸 | variant=hcl,hydrochloride | high |
| 10 | `amlodipine` | Amlodipine | 苯磺酸氨氯地平 | **氨氯地平** | 苯磺酸 | variant=besylate | high |
| 11 | `clopidogrel` | Clopidogrel | 硫酸氢氯吡格雷 | **氯吡格雷** | 硫酸氢 | none | medium |
| 12 | `warfarin` | Warfarin | 华法林钠 | **华法林** | 钠 | variant=sodium | high |
| 13 | `alendronic-acid` | Alendronic Acid | 阿仑膦酸钠 | **阿仑膦酸** | 钠 | variant=sodium | high |
| 14 | `ketorolac` | Ketorolac | 酮咯酸氨丁三醇 | **酮咯酸** | 氨丁三醇 | variant=tromethamine | high |
| 15 | `adenosine-triphosphate` | Adenosine Triphosphate | 三磷酸腺苷二钠 | **三磷酸腺苷** | 二钠 | manual | medium |
| 16 | `cisatracurium` | Cisatracurium | 苯磺顺阿曲库铵 | **顺阿曲库铵** | 苯磺 | variant=besylate | high |
| 17 | `esomeprazole` | Esomeprazole | 艾司奥美拉唑镁 | **艾司奥美拉唑** | 镁 | variant=magnesium | high |
| 18 | `propranolol` | Propranolol | 盐酸普萘洛尔 | **普萘洛尔** | 盐酸 | variant=hcl,hydrochloride | high |

盐型没丢的证据：以上每个成分的 `variant` 行（citrate / hydrochloride / sodium / besylate…）一条未动
（`variant` 总数 14,244 → 14,244）；`strength_basis`、`base_fraction` 同样未改。

### 6.7 影响面（旧产物 v0.11.7 实测）

| 指标 | 数 |
|---|---|
| 339 个修正成分中，旧产物有成分页的 | 339 / 339 |
| 这些页里旧盐型名出现次数合计 | **2,378** |
| `/drug/acetaminophen.html` 里「枸橼酸咖啡因」出现次数 | 7（全部在 `<span class="name-zh">` 成分名位） |

即：下一次构建后这些位置全部变成基础名；**不动 `site/dist`**（本次交付未写入一个文件）。

---

## 7. 已知缺口 / 需要下一步（不在本工位写权限内）

1. ~~`data/ingredient_names_i18n.csv` + `data/terms.json` 仍是旧中文名~~ → **已重跑**
   （Lead 追加要求，2026-11-14 晚，见 §6.5）：`etl/build_translation_tables.py` exit 0，
   `name_zh` 变化 583 行（其中 339 行是本次 T17，其余是 2026-10-28 以来别的任务没刷进派生表的漂移）；
   `data/terms.json` 由 `site/build.py::build_terms_json()` 在构建时从这份 CSV 重新生成，**不需要手改**。
2. **公开计数口径**：`nickname` 57 → 396（`aliases(community)` 599 → 938）。
   About 页文案写着「`@@NICKNAMES@@` 条俗称在 `data/seed_nicknames.py` 手工维护」，
   新增的 339 条不是手工维护的俗称，而是「合并前的成分中文名（盐型写法）」——
   三语文案建议改成「俗称 + 合并前中文名」，由 **site-ui** 在 T16/文案任务里同步（本工位不改 `site/build.py`）。
   （Lead 已登记进需求队列 **T28**，本工位不处理。）
3. **59 条修正不在 `data/inn_zh_backfill.csv`**（339 − 280）：它们的原中文名来自人工种子/其它入库路径，
   没有回填候选行。若将来删库重建，这 59 条只会回到「无中文名」，不会回到盐型名——**不会回归**；
   需要补候选可另开任务。
4. **778 条丢弃里 621 条是 `cn-*` 中文名成分**：要修得先有英文 INN 对应（另一条任务线，不在 T17 范围）。
5. **本报告未构建 `site/dist`**（遵守并行工位纪律）：页面级最终确认由 Lead/site-ui 的全量构建完成；
   构建后建议抽 `/drug/acetaminophen.html`、`/drug/lidocaine.html`、`/drug/warfarin.html` 三页复核。

---

## 8. 复现命令（任何人可重跑）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/apply_inn_zh.py --build-salt-fix-list            # 只读，重算清单 CSV（应得 1117 / 339 / 778）
& $py etl/apply_inn_zh.py --fix-salt-forms                 # dry-run：339 行 / 冲突 0（现库已是修后，会显示幂等跳过）
& $py etl/apply_inn_zh.py --rollback data\sources\inn_zh_salt_fix_manifest_20261115.json   # 还原（含 nickname）
& $py etl/apply_inn_zh.py --sync-backfill-csv               # 回填 CSV 同步 dry-run
& $py db/check_data.py
& $py -m unittest discover -s etl -t etl
& $py -m unittest discover -s lib -t lib
& $py tests/trilingual/run_tests.py
```

> 纪律说明：`data/drugs.db` 本轮**只写一次**（单事务）；写前备份 + manifest 全量 old→new + 副本库回滚演练；
> 未 commit、未发布、未写 `site/dist`、未改 `site/build.py` / `db/schema.sql` / 产品·组件·规格·collision 数据。
