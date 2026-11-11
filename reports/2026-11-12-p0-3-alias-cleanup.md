# P0-3 只读审计：成分页「也叫」混入整句 / 说明文字 / 别的药名

日期：2026-11-12 ・ 任务：task-4 ・ 工位：alias-site
范围：**只读审计，不写库、不改 `site/build.py`、不 commit**。写权限只有 `reports/` 与 `.tmp/`。
产物：本报告 + `.tmp/alias_audit_rows.tsv`（1,119 行逐行标记）+ `.tmp/alias_cleanup_removals.csv`（45 行删除清单，可直接喂既有清洗脚本）+ `.tmp/alias_dryrun/`（库副本 dry-run 证据）。

三条底线不变：商品名不是主键（查询仍返回候选集）；碰撞仍由 `collision` 视图推导；不判断可替代、不给剂量。

---

## 0. 结论（先行）

1. **脏源只有一处：`drug_term` 的 45 行**。`nickname` 57 行**全部干净**；`data/substance_aliases.csv`（25 组、48 个成分）**全部干净**——用户看到的「也叫」是 `alias_all`（俗称+民间叫法），不是那份异名表。
2. **根因是入库闸门的锚点写错了**：主要质量闸门 `etl/extract_cn_slang.py::is_junk_term()` 里，「是 / 为 / 的」被锚在**行首**（`^是`、`^为`、`^的`），出现在**句中**就一律放行。`platform=bing` 的搜索摘要被整句当成候选，于是「宣传自己的商品」「生产厂家为突出」「硫酸氢氯吡格雷片是波立维」原样入库，并统一挂到该页成分 `acetaminophen` 名下。
3. **规模**：删除 **45 行**、改写 **6 行**（拆成 6 条新名，5 个目标名已在库），影响 **25 个成分页**；用户点名的三条 **100% 复现**，全在删除清单里。
4. **只清库会被复活**：`run_all.py` 的顺序是 `clean_drug_terms.py --apply`（第 119 行）**先**、`ingest_cn_slang.py --apply`（第 122 行）**后**，而后者是「不存在才插入」——删掉的脏词下次全量重建会重新长回来。**必须同时补入库闸门**（同一套规则在候选 CSV 上拦掉 64/1,108 行）。
5. **站点侧不需要加过滤**。`site/build.py` 的「也叫」就是 `alias_all WHERE substance_id IS NOT NULL` 全量拼串（`build.py:8297-8302` → `8625-8629`），没有过滤也没有长度上限；加页面侧黑名单会和 About 页的 `COUNT(alias_all)` 口径打架。建议另开一条 site-ui 任务给「也叫」加**显示上限**（acetaminophen 清洗后仍有 15 个）。

---

## 1. 数据基线（现查，不照抄历史）

```sql
SELECT COUNT(*) FROM alias_all;                                              -- 1119
SELECT COUNT(*) FROM nickname;                                               --   57
SELECT COUNT(*) FROM drug_term;                                              -- 1062
SELECT COUNT(*), COUNT(DISTINCT substance_id) FROM alias_all
 WHERE substance_id IS NOT NULL;                                             -- 1083 / 430
SELECT COUNT(*) FROM alias_all WHERE substance_id IS NULL;                   --   36
```

| 口径 | 数值 | 说明 |
|---|---|---|
| `alias_all` | **1,119** | `nickname` 57 + `drug_term` 1,062 |
| 会渲染到成分页「也叫」的行 | **1,083**（430 个成分页） | `build.py` 只取 `substance_id IS NOT NULL`；`dist/drug` 共 12,431 页 → 覆盖 **3.5%** |
| 不进成分页、只进检索索引 | **36** | `substance_id` 为空（类别词，设计内） |
| `data/aliases.json`（构建产物） | **1,144** | 1,119 + `substance_aliases.csv` 的 25 条 |
| `data/substance_aliases.csv` | **25 行 / 48 个成分** | 历史报告写「24 行 / 46 个成分」，CSV 后来加过 1 行；这份是「**也称**」行，**不含脏数据** |

> 两条线别混：成分页上有 **「也称为/又叫」两种行**——
> `drug.also_called`「也叫：」← `alias_all`（**脏的是这条**）；`drug.also_known`「也称：」← `substance_aliases.csv`（干净）。
> 用户 2026-11-11 走查说的是前者。

---

## 2. 脏模式统计（规则 + SQL 双口径）

### 2.1 规则命中（一行可命中多条，不做加总）

| 规则 | 含义 | 命中 | 去向 |
|---|---|---|---|
| **R1** | 句子/说明残句：含「是 / 为」、句尾「的」、说明词（宣传/生产厂家/厂家/商品/药品/说明/可以/可能/啥/别称/分别/收载/曾用名/误导/音译/类药物…） | **41** | 39 删、2 拆（`就是必利劲`、`分别为慷定来和化疣敵`） |
| **R1d** | 连接词「或/和/与/及」：两个真名挤在一格 | **6** | 5 拆分、1 删（跨药） |
| **R2** | 标点（中英文句读、括号、引号） | **0** | — |
| **R3** | 长度异常（汉字 ≥12 / 拉丁 ≥20 字符 / ≥4 词） | **3** | 1 删、1 拆、1 待复核（化学长名合法） |
| **R4** | 剂型结尾（片/胶囊/注射液/丸…） | **21** | 3 删、18 待复核（多为真商品名） |
| **R5** | 归一化后精确命中**别的成分名/别的商品名键** | **1** | 经查为**误报**（见 §2.4） |
| **R6** | 纯描述词挂到具体成分（多个/啥名/药品/不同/之一…） | **15** | 删除 |
| **R7** | 来源不可核定（`community_web_cn` 抓取句） | **71** | 标签，不单独成罪 |

**SQL 复核**（LIKE 口径，比正则宽/窄都可能有偏差，仅作交叉验证）：

```sql
SELECT COUNT(*) FROM drug_term WHERE term LIKE '%是%';                       --  4
SELECT COUNT(*) FROM drug_term WHERE term LIKE '%为%';                       --  5
SELECT COUNT(*) FROM drug_term WHERE term LIKE '%的';                        -- 12
SELECT COUNT(*) FROM drug_term WHERE term LIKE '%宣传%' OR term LIKE '%厂家%'
      OR term LIKE '%商品%' OR term LIKE '%药品%';                            --  5
SELECT COUNT(*) FROM drug_term WHERE term LIKE '%，%' OR term LIKE '%。%'
      OR term LIKE '%；%';                                                   --  0
SELECT COUNT(*) FROM drug_term WHERE term LIKE '%片' OR term LIKE '%胶囊'
      OR term LIKE '%注射液';                                                 -- 12
SELECT COUNT(*) FROM drug_term d JOIN source s ON s.source_id = d.source_id
 WHERE s.name LIKE '%中文社区%';                                             -- 71（其中 65 挂到具体成分）
```

### 2.2 处置分桶（每行只进一个桶）

| 桶 | 行数 | 说明 |
|---|---|---|
| **删除** | **45** | 规则 37 + 人工判定 8 |
| **改写** | **6** | 6 行 → 6 条新名（11 条候选名里 5 条已存在） |
| **待复核** | **19** | 剂型尾缀 / 化学长名；本轮**不删** |
| **保留** | **1,049** | 含 36 个设计内的类别词 |
| 合计 | 1,119 | |

### 2.3 删除桶分布

| 维度 | 分布 |
|---|---|
| 来源族 | `community_web_cn`（bing 等搜索抓取）**40** / `wikipedia_zh`（中文维基重定向）**5** |
| 表 | `drug_term` **45** / `nickname` **0** |
| 市场 | `CN` **45**（这批中文俗名全是 `country='CN'`） |
| 影响成分页 | **25 个**；其中 2 行 `substance_id` 为空（只影响检索卡片） |
| 删了会不会搜不到 | **45 条全都不是商品名键**（`name_key` 无同词）→ 删掉不损失任何真实产品检索，只去掉「搜怪词出一张别名卡」 |

### 2.4 「指向其他药品」这条规则单独说

- **精确匹配（R5）命中 1 条且是误报**：`Mejoral` 是墨西哥对乙酰氨基酚品牌，同时出现在复方产品（paracetamol + caffeine）里，于是被算成「指向咖啡因」。
- **子串匹配太脏，不能单用**：拿 1,297 个中文成分名做「术语包含别的成分名」匹配，命中 34 条，其中 31 条是同母体/同类（`二甲胺四环素` 含 `四环素`、`葡萄糖胺` 含 `葡萄糖`），全是合法叫法。
- **可用的是组合规则**：`残句标记（R1/R1d）∧ 含另一个成分中文名` → 命中 **3 条，全对**：
  `硫酸氢氯吡格雷片是波立维`（挂 acetaminophen）、`无环鸟苷的阿昔洛韦`（挂 ganciclovir）、`多潘立酮或吗丁啉`（挂 dopamine）。

---

## 3. Top 30 抽样（全部在删除桶，含来源）

| # | term | 挂在成分 | flags | 来源族 | source |
|---|---|---|---|---|---|
| 1 | 他达拉非是药品 | tadalafil | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 2 | 可以说都很低调 | metformin | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 3 | 可能因生产厂商 | rosuvastatin | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 4 | 宣传自己的商品 | acetaminophen | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 5 | 生产厂家为突出 | acetaminophen | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 6 | 沙星类药物 | moxifloxacin | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 7 | 常见药品 | valsartan | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 8 | 不一样 | domperidone | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 9 | 啥名字 | diazepam | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 10 | 曾用名 | hydrotalcite | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 11 | 通常为 | valsartan | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 12 | 别称 | moxifloxacin | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 13 | 别被 | sildenafil | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 14 | 啥名 | ibuprofen | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 15 | 多个 | rosuvastatin | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 16 | 多为 | acetaminophen | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 17 | 常为 | metoprolol | R1,R6 | wikipedia_zh | 中文维基(重定向/别名) |
| 18 | 收载 | methylphenidate | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 19 | 而来 | acetaminophen | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 20 | 药品 | rosuvastatin | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 21 | 误导 | sildenafil | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 22 | 音译 | tadalafil | R1,R6,R7 | community_web_cn | 社区抓取(bing等) |
| 23 | 硫酸氢氯吡格雷片是波立维 | acetaminophen | R1,R3,R7 | community_web_cn | 社区抓取(bing等) |
| 24 | 选项C胶岭石是蒙脱石 | diosmectite | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 25 | 无环鸟苷的阿昔洛韦 | ganciclovir | R1 | wikipedia_zh | 中文维基(重定向/别名) |
| 26 | 多潘立酮或吗丁啉 | dopamine | R1d,R7 | community_web_cn | 社区抓取(bing等) |
| 27 | 阿司匹林的三个 | aspirin | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 28 | 右美沙芬片的 | dextromethorphan | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 29 | 瑞舒伐他汀的 | rosuvastatin | R1,R7 | community_web_cn | 社区抓取(bing等) |
| 30 | 利拉鲁肽的 | liraglutide | R1,R7 | community_web_cn | 社区抓取(bing等) |

完整 1,119 行（含 `source_name` / `meaning_zh` / `flags` / `bucket`）：`.tmp/alias_audit_rows.tsv`。

---

## 4. 用户走查点名的三条：复现与线上证据

三条都在库里、都挂在 `acetaminophen` 名下、都来自「中文社区/搜索抓取（维基/必应/头条/小红书/知乎等）」：

| 用户原话 | term_id | `term_type` | `confidence` | 现状 |
|---|---|---|---|---|
| 「宣传自己的商品」 | 963 | folk | community | 渲染在 `/drug/acetaminophen.html` |
| 「生产厂家为突出」 | 1123 | folk | community | 同上 |
| 「硫酸氢氯吡格雷片是波立维」 | 1157 | folk | community | 同上 |

现网构建产物（`site/dist`，v0.10.x）里的实际渲染：

```text
/drug/acetaminophen.html
Also called: 扑热息痛、必理通、Tempra、Mejoral、乙醯胺酚、必理痛、百服宁、退热净、
             速效伤风胶囊、速效感冒胶囊、醋氨酚、乙醯氨酚、多为、宣传自己的商品、
             对羟基乙酰苯胺、對乙醯胺基酚、撲熱息痛、普拿疼或醋氨酚、生产厂家为突出、
             硫酸氢氯吡格雷片是波立维、羟苯基乙酰胺、而来
```

同类污染页（逐页扫 `dist/drug/*.html` 的「也叫」行）：

| 页面 | 「也叫」行里的脏词 |
|---|---|
| `acetaminophen` | 宣传自己的商品 / 生产厂家为突出 / 硫酸氢氯吡格雷片是波立维 / 多为 / 而来 / 速效伤风胶囊 / 速效感冒胶囊 |
| `rosuvastatin` | 可能因生产厂商 / 多个 / 瑞舒伐他汀的 / 药品（**整行 100% 是脏词**） |
| `moxifloxacin` | 别称 / 沙星类药物（**整行 100% 是脏词**） |
| `valsartan` | 常见药品 / 通常为 |
| `aspirin` | 阿司匹林的 / 阿司匹林的三个 |
| `sildenafil` | 万艾可的 / 伟哥的 / 西地那非的 / 别被 / 误导 |
| 其余 18 页 | 各 1 条（详见 `.tmp/alias_audit_rows.tsv`） |

---

## 5. 清洗规则（可落地）

### 5.1 现库清洗：复用既有框架，不新写脚本

仓库已有 `etl/clean_drug_terms.py`（dry-run / `--apply` 事务 / `--rollback` 快照，**id + alias 双键校验**），
它接受 `--csv` 参数。本次把 45 行写成同构清单，**零改代码**即可执行：

`.tmp/alias_cleanup_removals.csv`（列 `id,table,alias,substance_id,reason,evidence`）：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl\clean_drug_terms.py --csv .tmp\alias_cleanup_removals.csv          # dry-run
# 输出：删除清单 45 行 / 可删除 45 行 / 跳过 0 行 —— 45 行 id+alias 全部对得上
```

### 5.2 入库闸门（否则下次 `run_all.py` 复活）

**最小改动**（推荐先做这个）：在 `etl/ingest_cn_slang.py::build_plan()` 的去重检查之前加一段。
`run_all.py` 只跑 ingest、**不跑 extract**，所以闸门必须放在 ingest 侧（放在 `extract_cn_slang.py` 只能挡住下次重新抽取）：

```python
# etl/ingest_cn_slang.py 顶部
RE_ALIAS_JUNK = re.compile("|".join([
    r"[是为]",                       # 药名不含「是/为」（原闸门只锚行首，句中漏过）
    r"的$",                          # 句尾「的」= 抓取残句（万艾可的 / 阿司匹林的三个）
    r"的(?!松)",                     # 句中「的」只有「的松」合法（强的松/考的松/可的松）
    r"宣传|生产厂家|生产厂商|厂家|厂商|商品|药品|说明|注意",
    r"可以|可能|啥|别称|分别|收载|曾用名|误导|音译|类药物",
    r"而来|多为|多个|不一样|常为|通常为|常见",
    r"别被|吗$",                     # 抓取残片（别被 / 芬必得吗）
    r"(片|胶囊|注射液|口服液|颗粒|乳膏|软膏|滴眼液|糖浆)$",   # 商品名+剂型
    r"[或和与及]",                   # 两名挤一格，需人工拆分后再入
]))

# build_plan() 里，`if not term or not tkey:` 之后
if RE_ALIAS_JUNK.search(term):
    skipped["残句/说明文字/剂型尾缀（P0-3 规则）"] += 1
    continue
```

**更彻底（可选）**：把规则抽到 `etl/alias_rules.py`，让 `extract_cn_slang.py::is_junk_term()` 也调用同一函数，
再把 `JUNK_PATTERNS` 里 `r"^是" / r"^为" / r"^的"` 三个锚点去掉——**这三个 `^` 就是本次事故的直接原因**。

### 5.3 闸门 dry-run：候选 CSV 上拦 64/1,108

在同一份 `data/cn_slang_candidates.csv`（1,108 行）上跑上面的正则：

| 指标 | 数值 |
|---|---|
| 现闸门已拦 | **0**（这 1,108 行都是「通过现闸门」的 Tier B） |
| 新规则再拦 | **64 行（5.8%）** |
| 与本次删除清单重叠 | **43 / 45** |
| 覆盖不到 | 2 条：`不同` / `之一`（不在候选 CSV 里，来源同为 bing，`substance_id` 为空） |
| 闸门会拦、但本轮不清洗 | **15 行**：11 行在库但进「待复核」（`必除癌注射液`、`好娃娃蒙脱石颗粒`、`牙周康胶囊`、`葛根黄豆甙元片`、`血舒通注射液`、`乙酰胺吡咯烷酮注射液`、`碘片`、`克感敏片`、`扑感敏片`、`葛根素片`、`安定片`）+ 4 条候选不在库（`多维元素片`、`氨麻苯美片`、`得百利寧或安佳熱等是`、`白加黑的全称`） |

> **两套阈值是故意的**：入库可以保守（存疑就不收），清库必须严格（只删高置信脏行，真商品名不误删）。
> 所以闸门比清洗多拦 19 行，属预期，不是不一致。

---

## 6. dry-run 统计（删/改各多少、按来源）

在 `.tmp/alias_dryrun/drugs-clean.db`（现网库**副本**，409 MB 复制）上真删 45 行 + 改写 6 行：

| 指标 | 现网 | dry-run 后 | delta |
|---|---|---|---|
| `alias_all` | 1,119 | **1,074** | −45 |
| ├ `nickname` | 57 | 57 | 0 |
| └ `drug_term` | 1,062 | **1,017** | −45 |
| 成分页「也叫」可渲染行 | 1,083 | **1,040** | −43 |
| 有「也叫」的成分页 | 430 | **428** | −2（`moxifloxacin`、`rosuvastatin` 原来整行都是脏词） |
| 删除 | — | 45 行 | 社区抓取 40 / 中文维基 5 |
| 改写 | — | 6 行 → 6 条新名 | 11 条候选名里 5 条已存在（`醋氨酚`/`委丹扎`/`天冬酰胺酶`/`天门冬酰胺酶`/`诺罗芬`） |
| `PRAGMA integrity_check` | ok | **ok** | — |
| `PRAGMA foreign_key_check` | 0 | **0 条** | — |

**改写 6 行明细**（原文 → 拆出）：

| term_id | 原文 | 挂在 | → 新名 |
|---|---|---|---|
| 870 | 分别为慷定来和化疣敵 | podofilox | 慷定来 / 化疣敵 |
| 937 | 天冬酰胺酶或天门冬酰胺酶 | asparaginase | 天冬酰胺酶 / 天门冬酰胺酶 |
| 972 | 就是必利劲 | dapoxetine | 必利劲 |
| 1042 | 普拿疼或醋氨酚 | acetaminophen | 普拿疼 / 醋氨酚 |
| 1194 | 维达莎或委丹扎 | azacitidine | 维达莎 / 委丹扎 |
| 1284 | 诺罗芬和美林 | ibuprofen | 诺罗芬 / 美林 |

**`db/check_data.py` 同款计数前后对比**（证明只动别名两张表）：

| 指标 | 现网 | dry-run | delta |
|---|---|---|---|
| products / components / substances | 479,193 / 630,151 / 12,637 | 同 | 0 |
| name_keys / names | 202,739 / 655,004 | 同 | 0 |
| collisions(severe / warning) | 23,855 / 925 | 同 | 0 |
| confusable_pairs / dose_warnings | 22 / 41 | 同 | 0 |
| **drug_term** | 1,062 | **1,017** | **−45** |
| **aliases(total)** | 1,119 | **1,074** | **−45** |
| ├ documented | 476 | 474 | −2 |
| └ community | 642 | 599 | −43 |

**清洗后复算**：同一套审计规则跑副本库 → **delete 0 / fix 0**（review 19 不变），闭环。

**用户可见前后对照**（`/drug/acetaminophen.html` 的「也叫」行）：

```text
清洗前（22 个）：
扑热息痛、必理通、Tempra、Mejoral、乙醯胺酚、必理痛、百服宁、退热净、速效伤风胶囊、
速效感冒胶囊、醋氨酚、乙醯氨酚、多为、宣传自己的商品、对羟基乙酰苯胺、對乙醯胺基酚、
撲熱息痛、普拿疼或醋氨酚、生产厂家为突出、硫酸氢氯吡格雷片是波立维、羟苯基乙酰胺、而来

清洗后（15 个）：
扑热息痛、必理通、Tempra、Mejoral、乙醯胺酚、必理痛、百服宁、退热净、醋氨酚、乙醯氨酚、
对羟基乙酰苯胺、對乙醯胺基酚、撲熱息痛、羟苯基乙酰胺、普拿疼
```

---

## 7. 回滚清单草案

**执行前必须做**（AGENTS §4：单独跑 clean/ingest 不自动备份）：

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item data\drugs.db "data\backups\drugs-$stamp.db"
```

**删除的回滚**由 `etl/clean_drug_terms.py` 自带：`--apply` 时把每一行的**完整快照**（所有列）写进
`.tmp/drug-term-cleanup/undo_<UTC时间戳>.json`，`--rollback <manifest>` 用快照 `INSERT OR REPLACE` 恢复（幂等）。

```powershell
# 执行（Lead 备份后）
& $py etl\clean_drug_terms.py --csv .tmp\alias_cleanup_removals.csv --apply

# 回滚
& $py etl\clean_drug_terms.py --rollback            # 缺省取最新 undo_*.json
```

**改写的回滚**（6 行，需人工，脚本不管这块）：

```sql
-- 1) 先删掉拆分出来的新行（靠 note 标记，不会误伤别的数据）
SELECT term, substance_id, note FROM drug_term WHERE note LIKE 'P0-3 由%';   -- 应为 6 行
DELETE FROM drug_term WHERE note LIKE 'P0-3 由%';
-- 2) 再按 manifest 恢复被删的原 6 行（原 term_id 870/937/972/1042/1194/1284）
```

**执行清单（建议顺序）**：

1. 补 `etl/ingest_cn_slang.py` 闸门 + 两条 unittest（正例/反例各 3 条：`宣传自己的商品` 拒、`强的松` 收）。
2. 备份库 → `clean_drug_terms.py --csv ... --apply` → 改写 6 行 → 重跑审计脚本确认 `delete=0`。
3. `& $py db/check_data.py` 前后各一次（预期只有 `drug_term` / `aliases(total)` 变化）。
4. `& $py -m unittest discover -s etl -t etl` + `-s lib -t lib`；`tests/trilingual/run_tests.py`
   （`tests/trilingual/gen_cases.py` 用 `alias_norm` 生成用例，删词后用例集会变，需重跑确认无回归）。
5. 全量 `run_all.py --no-ingest` 或 `site/build.py` 到 `== done ==` → 抽查 §4 那些页面的「也叫」行。

---

## 8. 站点侧是否需过滤：**不需要**（本轮结论）

理由：

1. **单一真相源**：About 页的 `@@ALIASES@@` 是构建期 `SELECT COUNT(*) FROM alias_all`（`build.py:12583-12584`），
   页面侧再过滤会让「About 说 1,119 条」和「页面上实际显示的条数」对不上，违反 AGENTS §4 的计数口径统一。
2. **过滤规则会漂移**：脏词是数据问题，改一次库就永久解决；页面侧正则等于把同一套规则复制两份。
3. **渲染路径没有别的漏洞**：`build.py:8297-8302` 取 `alias_all WHERE substance_id IS NOT NULL`，
   `8625-8629` 直接 `esc()` 后拼串——**有转义、无截断、无过滤**，脏数据会 1:1 显示出来，也正是本次现象。

> 行号是本次审计时（`site/build.py` 12,768 行）的；该文件正被其他工位改动，合并时以 `SELECT substance_id, alias FROM alias_all` 与 `data-i18n="drug.also_called"` 两处锚点为准。

**建议另开（不属于 P0-3，属 P2 成分页）**：

- 「也叫」行加**显示上限**（例：最多 12 个 + 「查看其余 N 个」）：`acetaminophen` 清洗后仍有 **15** 个，
  `aspirin` 清洗后仍有 14 个，长尾页会继续显得像垃圾桶。这跟 §1 P2 的「+218 不易发现」是同一类问题。
- 构建期**只告警不阻塞**的护栏（可选）：若 `alias` 命中残句规则就打印计数，下次数据回潮能早发现。

---

## 9. 判不了 / 未做 / 风险

### 9.1 待复核 19 行（本轮不删，留给下一轮）

| 类型 | 行 | 判断 |
|---|---|---|
| 真实叫法带「丸/片」字 | `蓝色小药丸`（西地那非）、`美白丸` ×2（氨甲环酸/谷胱甘肽）、`碘片`、`脷底丸`、`薄血丸`、`多仔丸`、`周末丸`、`安定片` | 属口语/港台叫法，**不该按剂型规则误删** |
| 商品名+剂型 | `好娃娃蒙脱石颗粒`、`牙周康胶囊`、`葛根黄豆甙元片`、`血舒通注射液`、`必除癌注射液`、`乙酰胺吡咯烷酮注射液`、`克感敏片`、`扑感敏片`、`葛根素片` | 更像商品名（AGENTS §4 说商品名不进 nickname；但 `drug_term` 是民间叫法表，口径需人工定） |
| 化学长名 | `去甲酰氧甲基唑肟头孢菌素`（头孢唑肟） | 维基别名，**合法但难读**；长度规则只能标不可删 |

其中 9 行 `substance_id` 为空（`克感敏片`/`扑感敏片`/`葛根素片`/`安定片`/`碘片`/`多仔丸`/`周末丸`/`脷底丸`/`薄血丸`），
**不会渲染到成分页**，只影响检索卡片。

### 9.2 判不了但保留：27 行社区来源

`丙戊沙坦`、`亿梦返`、`仙特敏`、`双氯灭痛`、`吡嗪哌酯`、`塞内昔布`、`安布索`、`左氧`、`待克菲那`、
`氟甲去氢氢化可的松`、`氢溴酸右甲吗喃`、`沫舒痰`、`溴环己胺醇`、`甲福明`、`米地诺尔`、`胃达喜`、
`舒喘灵`、`诺罗芬`、`赛利克西`、`阿伐他汀`、`阿托伐他丁`、`阿红霉素`、`阿齐红霉素`、`顺尔`、
`减肥针`、`瘦瘦针`、`白加黑`

- 这 27 条里 **24 条是真实的中文旧名/港台名/译名**（`胃达喜`、`舒喘灵`、`白加黑` 甚至是真商品名），**不能按来源一刀切删**；
  `减肥针`、`瘦瘦针` 是 `term_type='class'` 的类别词（`substance_id` 为空，设计内）。
- 1 条存疑，但**判不了就不动**（按项目规则计数、不写库）：`顺尔`（像是 `顺尔宁` 被截断）。

### 9.3 未做（本轮写权限外）

- `etl/**` 未改：闸门补丁只给在 §5.2，**没有落地**（写权限只有 `reports/` 与 `.tmp/`）。
- `data/alias_cleanup_removals.csv` 未落 `data/`：清单先放 `.tmp/`，等 Lead 审批后再移位。
- `site/build.py` 未改（禁止）：显示上限建议另派工位。
- 本轮**零写库**，所以没有跑 `db/check_data.py` 的前后对比（改了会污染现网库）；改用「库副本 + 同款计数」代替（§6）。

### 9.4 风险

| 风险 | 影响 | 处置 |
|---|---|---|
| 只清库不补闸门 | 下次 `run_all.py` 脏词全量复活（ingest 在 clean 之后跑） | 闸门与清洗**同批上线**（§5.2 + §7） |
| 删除清单与现网库不同步 | id 复用会误删 | 框架已有 **id + alias 双键校验**，45/45 通过；执行前再跑一次 dry-run |
| README 的别名计数会过期 | `README.md:28` 写死「1,062 条 `drug_term` / 1,144 条 `alias_all`」；现查 `alias_all` 实际是 **1,119**（1,144 是 `aliases.json` 口径，本来就标错表名） | 清洗后改为 **1,017 条 `drug_term` / 1,074 条 `alias_all`**（若坚持用 `aliases.json` 口径则 1,099）；About 页 `@@ALIASES@@` 自动变 1,074，构建后核对 |
| 删词影响三语用例 | `gen_cases.py` 用 `alias_norm` 造用例 | 按 §7 第 4 步重跑 `tests/trilingual/run_tests.py` |
| 中文维基那 5 条不是「抓取句」 | 它们是重定向名（`常为`、`速效伤风胶囊`…），删的是**语义错**不是**来源脏** | 已在清单里逐条写 reason；如认，回滚只需按 manifest |

---

## 10. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 审计（只读）：生成逐行明细 + 汇总 + 删除清单
$env:PYTHONIOENCODING='utf-8'; [Console]::OutputEncoding=[Text.Encoding]::UTF8
& $py .tmp\alias_audit.py                       # → .tmp/alias_audit_summary.txt / alias_audit_rows.tsv
                                                #   .tmp/alias_cleanup_removals.csv

# 2) 独立复核删除清单（仓库既有脚本，只读）
& $py etl\clean_drug_terms.py --csv .tmp\alias_cleanup_removals.csv

# 3) 入库闸门模拟（候选 CSV 上会拦多少）
& $py .tmp\alias_gate_sim.py                    # → .tmp/alias_gate_sim.txt

# 4) 库副本 dry-run：真删 + 改写 + 复算 + 完整性
& $py .tmp\alias_dryrun.py                      # → .tmp/alias_dryrun/report.txt
& $py .tmp\alias_counts.py                      # → .tmp/alias_dryrun/counts.txt

# 5) 清洗后复算（应 delete=0）
$env:ALIAS_DB = (Resolve-Path '.tmp\alias_dryrun\drugs-clean.db').Path
& $py .tmp\alias_audit.py                       # → .tmp/alias_dryrun/alias_audit_summary.txt
Remove-Item Env:\ALIAS_DB
```

> `.tmp/` 全部不入库；本报告之外没有任何仓库文件被改。**未 commit / 未 push / 未发布 / 未写 `data/drugs.db`。**
> dry-run 用的库副本 `drugs-clean.db`（409 MB）在交付前已删，`report.txt` / `counts.txt` / 复算汇总保留；重跑步骤 4 即可再生。
