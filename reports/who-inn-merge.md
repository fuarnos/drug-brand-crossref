# WHO INN 9 条西语合并准备 + 搜索评测集扩容方案（task-27）

> 日期：2026-10-27 ｜ 上游：`reports/who-inn-20261026.md`（task-17，WHO INN 官方多语列表对比）
> 产物：`data/es_inn_overrides.csv`（9 行更新，BOM/列结构不变）· 本报告 · `.tmp/who-inn-apply/`（证据、快照、dry-run 日志）
> 边界：**未写 `data/drugs.db`**（merge 脚本全程 `--dry-run` 只读）、未跑 git/发布、未改 `site/build.py`/其它跟踪文件。DB 当前状态：substances 12,793 / variants 13,745 / mx-es-* 717 / components 497,513 / products 409,485。

---

## 1. 结论（先说重点）

1. **上游「9 条可新增合并」经 DB 复核只有 3 条成立**：
   - ✅ 真可合并 3 条：`Fenofibrato De Colina → choline-fenofibrate`、`Mebutato De Ingenol → ingenol-mebutate`、`Talimogén Laherparepvec → talimogene-laherparepvec`；
   - ❌ 自匹配假阳性 6 条：`Difenidol / Fimasartán / Asunaprevir / Lesinurad / Nimotuzumab / Saroglitazar`。上游对比脚本 `.tmp/who-inn/compare.py` 的 DB 英文索引**没有排除 `mx-es-*`**（只排了 `cn-`，L51-58），把「西语专属成分自己的 `inn_en`」当成了「库内已有英文 substance」。这 6 个英文名在库里**没有独立的英文 substance**（SQL 全表模糊查也只有 `mx-es-*` 自身），不可能合并；若照上游直接标 `mergeable`，merge 脚本会报 6 条行级校验错误并**整体拒绝 apply**。
2. **`data/es_inn_overrides.csv` 已按诚实口径更新**：共 1,081 行不变、仅 9 行变化、列结构与 UTF-8 BOM 不变。
   - 3 条 → `status=mergeable`、`confidence=high`、`evidence=WHO INN list N(high)→<英文目标>`；
   - 6 条 → 补 `en_inn`/WHO 证据/`confidence=high`，但**保持非 mergeable**（`no_english`），`reason` 写明「库内无独立英文 substance，需先补英文成分」。
3. **mergeable 数：182 → 185（+3）**，不是上游预估的 182 → 191。
4. **dry-run 实测**（当前库，只读）：
   - 默认模式：**可合并 2 个成分 / 2 个产品**（Fenofibrato、Mebutato），0 行级错误；
   - `--include-unprefixed`：**可合并 3 个成分 / 4 个产品**（+Talimogén，其 ES id 无 `mx-es-` 前缀），0 行级错误；
   - 6 条自匹配行因状态非 mergeable，不进入合并计划，**不产生 error、不阻塞 apply**。
5. **apply 建议**：Lead 在确认无并行写库后，用 `--include-unprefixed --apply` 一次合并 3 条（撤销清单自动落 `.tmp/es-map/`）；预期 substances 12,793→12,790、variants 13,745→13,742、mx-es-* 717→715、components/products 总数不变。**本任务不 apply。**
6. **评测集扩容方案**：72 → **320 例**（8 类：en 错拼 45、es 错拼 30、zh 错字 25、拼音 40、简繁 30、复方 55、盐型 55、零结果 40），逐类给了素材来源、生成算法、期望值来源、验收门槛与反循环论证要求（详见 §6）。

---

## 2. 9 条候选逐条复核（只读 SQL + CSV 对照）

| # | 西语名（es_name） | es_substance_id | WHO 英文 INN | DB 里"英文目标" | 实际判定 | 依据 |
|---|---|---|---|---|---|---|
| 1 | Difenidol | `mx-es-difenidol` | difenidol | 不存在（仅 `mx-es-difenidol`，inn_en=Difenidol，54 产品 CN+MX） | ❌ 自匹配 | 全表 `lower(inn_en) like '%difenidol%'` 只有 ES 自身 |
| 2 | Fimasartán | `mx-es-fimasartan` | fimasartan | 不存在（仅自身，3 产品 MX） | ❌ 自匹配 | 同上 |
| 3 | Asunaprevir | `mx-es-asunaprevir` | asunaprevir | 不存在（仅自身，2 产品 CA+MX，**2 个 variant**） | ❌ 自匹配 | 无独立英文 substance；即便有目标也会因 variant 数≠1 被拦 |
| 4 | Lesinurad | `mx-es-lesinurad` | lesinurad | 不存在（仅自身，1 产品 MX） | ❌ 自匹配 | 同上 |
| 5 | Nimotuzumab | `mx-es-nimotuzumab` | nimotuzumab | 不存在（仅自身，2 产品 CN+MX） | ❌ 自匹配 | 同上 |
| 6 | Saroglitazar | `mx-es-saroglitazar` | saroglitazar | 不存在（仅自身，1 产品 MX） | ❌ 自匹配 | 同上 |
| 7 | Fenofibrato De Colina | `mx-es-fenofibrato-de-colina` | choline fenofibrate | ✅ `choline-fenofibrate`（US 4 产品） | ✅ 可合并 | 独立英文成分，1 base variant |
| 8 | Mebutato De Ingenol | `mx-es-mebutato-de-ingenol` | ingenol mebutate | ✅ `ingenol-mebutate`（GB 5 / CA 2） | ✅ 可合并 | 独立英文成分，1 base variant |
| 9 | Talimogén Laherparepvec | `talimogen-laherparepvec` | talimogene laherparepvec | ✅ `talimogene-laherparepvec`（GB 4 / US 2） | ✅ 可合并（需 `--include-unprefixed`） | 独立英文成分；ES 源 id 无前缀但产品只在 ES，满足该模式安全条件 |

**上游脚本根因（建议 Lead 让上游修复后重跑 WHO 对比）**：`.tmp/who-inn/compare.py` L51-58 建 `db_en` 索引时排除了 `cn-` 前缀，但**未排除 `mx-es-`**：

```python
for sid, inn_en in con.execute("SELECT substance_id, inn_en FROM substance"):
    if sid.startswith("cn-") or not inn_en:   # ← 缺 sid.startswith("mx-es-")
        continue
```

修复方式（一行）：`if sid.startswith(("cn-", "mx-es-")) or not inn_en: continue`。重跑后 ES「可新增合并」应为 **3 条**，与本文一致。

**6 条自匹配的后续两条路（写进建议，不在本轮做）**：
- **A. 先补英文成分**：用 WHO 官方名建 `difenidol` / `fimasartan` / `asunaprevir` / `lesinurad` / `nimotuzumab` / `saroglitazar` 等英文 substance（这些药在 US/GB 无上市记录，可从 WHO INN/EML 补名但不一定有产品），再合并；
- **B. 提升（promote）ES 专属成分为英文 id**：这 6 条的 `inn_en` 已是英文 INN（Fimasartán 仅多一个重音），可把 `mx-es-*` 直接重命名为英文 id 并 `UPDATE variant/substance` 引用——属 DB 迁移，需 Lead 拍板，风险比 merge 高，建议单独任务。

---

## 3. `data/es_inn_overrides.csv` 变更

### 3.1 变更审计（`audit_after.json`）

| 项 | 值 |
|---|---|
| 行数 | 1,081 → 1,081（不变） |
| 列 | 8 列前后一致：`es_name,en_inn,es_substance_id,en_substance_id,evidence,confidence,status,reason` |
| UTF-8 BOM | 保留（`EF BB BF`） |
| 实际变化行 | **9 行**（其余 1,072 行逐字节一致） |
| 新增 / 删除行 | 0 / 0 |

### 3.2 状态分布 before → after

| status | before | after | 说明 |
|---|---:|---:|---|
| mergeable | 182 | **185** | +3（Fenofibrato、Mebutato、Talimogén） |
| no_english | 674 | 672 | −2（上述两条离开该状态）；6 条自匹配留在此类但补了 en_inn/evidence |
| uncertain | 159 | 158 | −1（Talimogén 离开） |
| combination | 66 | 66 | 不变 |
| **合计** | 1,081 | 1,081 | 不变 |

### 3.3 9 行更新示例

真合并（3 条）：

```
Fenofibrato De Colina → en_inn=choline fenofibrate, en_substance_id=choline-fenofibrate,
  evidence="WHO INN list 59(high)→choline-fenofibrate", confidence=high, status=mergeable,
  reason="WHO INN 官方列表 list 59：西语名 Fenofibrato De Colina ↔ INN choline fenofibrate；
          source: https://iris.who.int/handle/10665/74120；安全预检通过（安全校验由 merge 脚本 dry-run 复核）"
```

自匹配（6 条，以 Difenidol 为例）：

```
Difenidol → en_inn=difenidol, en_substance_id=""（留空）, evidence="WHO INN list 43(high)→difenidol",
  confidence=high, status=no_english,
  reason="WHO INN 官方列表 list 43：西语名 Difenidol ↔ INN difenidol；source: ...；
          ⚠ en_substance_id 与 es_substance_id 相同（compare.py 自匹配）：库内无独立英文 substance，
          须先补英文成分后才能合并（compare.py 的 db_en 索引应排除 mx-es-*/cn-*）"
```

> 注：上游 `es_new_mergeable_candidates.csv` 与 `who-inn-20261026.md §4.1`（"9 条可新增合并 / 182→191"）是历史产物，本轮更正为 3 条 / 182→185；建议 Lead 在后续 WHO 报告里加一行更正说明，避免下一轮误用。

---

## 4. merge 脚本 dry-run 结果（`etl/merge_es_substances.py`，只读）

### 4.1 before / after 对照

| 模式 | before（backup CSV） | after（新 CSV） | 增量 |
|---|---:|---:|---|
| 默认 `--dry-run` | 可合并 **0** / 产品 0 / 行级错误 0 | 可合并 **2** / 产品 2 / 组件 2 / 行级错误 0 | +2 |
| `--include-unprefixed --dry-run` | 可合并 **0** / 产品 0 | 可合并 **3** / 产品 4 / 组件 4 / 行级错误 0 | +3 |

（before 之所以是 0：现有 182 条 mergeable 里 42 条 already_merged（历史已合并）、124 条需 unprefixed、14 条 corroboration 拦截、3 条英文目标无 base variant，均已消化完；上游 task-13 报告里的 139 条可合并已在之前批次落地。）

### 4.2 after 模式下的「将合并清单」（`dryrun_final_*.log`）

| ES 成分 | 西语名 | 英文目标 | 挂载 | 产品 | 组件 | 目标已有市场 |
|---|---|---|---|---|---:|---|
| `talimogen-laherparepvec` | Talimogén Laherparepvec | `talimogene-laherparepvec` | base | 2 | 2 | GB、US |
| `mx-es-fenofibrato-de-colina` | Fenofibrato De Colina | `choline-fenofibrate` | base | 1 | 1 | US |
| `mx-es-mebutato-de-ingenol` | Mebutato De Ingenol | `ingenol-mebutate` | base | 1 | 1 | GB、CA |

- **行级校验错误 errors = 0**（6 条自匹配已不在 mergeable 状态，不会被 plan 处理）；
- skip 的 182/183 条均为既有非本次行（`--include-unprefixed`：139 already_merged、38 corroboration、4 无 base variant、1 非 base variant），**与本轮 9 条无关**；
- 唯一"模式相关"：Talimogén 默认模式因 `es_sid` 无 `mx-es-` 前缀被跳过（124 条"非前缀"之一），所以默认只并 2 条。

### 4.3 apply 建议（Lead 执行，本任务不写库）

前置：确认无并行入库/写库任务（AGENTS.md §7）；先备份 `data/drugs.db` → `data/backups/`。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 再确认（只读）
& $py etl/merge_es_substances.py --include-unprefixed --dry-run      # 应显示：可合并 3、errors 0

# 2) 一次合并 3 条（会自动生成撤销清单 .tmp/es-map/merge_undo_<UTC>.json）
& $py etl/merge_es_substances.py --include-unprefixed --apply

# 3) 验收
& $py db/q.py "SELECT COUNT(*) FROM substance"                        # 预期 12,790（−3）
& $py db/q.py "SELECT COUNT(*) FROM variant"                          # 预期 13,742（−3）
& $py db/q.py "SELECT COUNT(*) FROM product_component"                # 预期 497,513（不变）
& $py db/q.py "SELECT COUNT(*) FROM substance WHERE substance_id LIKE 'mx-es-%'"  # 预期 715（−2）

# 4) 抽检：MX/ES 产品现在能看到英文市场
& $py cli.py "Fenofibrato De Colina"   # 结果卡应带 US
& $py cli.py "Mebutato De Ingenol"     # 应带 GB/CA

# 5) 如异常回滚
& $py etl/merge_es_substances.py --rollback
```

预期影响面：3 个 ES/MX 产品分别接上 US / GB+CA 市场视图（Fenofibrato 1、Mebutato 1、Talimogén 2）；`product_component` 只改 `variant_id` 指向，总数不变；合并后西语名仍可搜（`product_name/name_key` 不动）。**apply 后需 rebuild/publish 才在线上可见，由 Lead 按发布纪律执行。**

---

## 5. 与上游 WHO 报告的差异（需要 Lead 知道的更正）

| 项 | 上游 `who-inn-20261026.md` | 本轮复核 |
|---|---|---|
| ES 可新增合并 | 9 条 | **3 条**（6 条是 `compare.py` 把 `mx-es-*` 自身当英文目标） |
| mergeable | 182 → 191 | **182 → 185** |
| ES 专属成分 | 833 → 824 | 本轮 apply 后 832（只并 3 条；833 → 830 为最终态） |
| 证据 | WHO list 条目 | 一致（9 条 WHO 命中本身无误，错在"库内英文目标存在"判定） |

**结论**：WHO INN 作为高置信证据有效（9 条西语名↔英文 INN 全部核对一致），但"能否合并"必须再用 DB 的英文目标存在性独立复核——这也写进了 §6 的评测集「期望值来源」原则。

---

## 6. 搜索评测集扩容方案：72 → 320+ 例

### 6.1 目标与 case schema

现有 `tests/trilingual/run_tests.py`：72 例 / 354 查询（手工精选，覆盖 7 市场 × 3 语言）。扩容目标：**自动生成 320 例以上**，覆盖用户真实错法（错拼、拼音、简繁、复方、盐型、零结果），并作为后续搜索改造（拼音键、OpenCC 全量表、2 字降权等）的验收基线。

统一 case schema（JSON Lines 或 CSV，供 harness 读取）：

```json
{
  "case_id": "v2-en-typo-0001",
  "category": "en_typo",
  "lang": "en",
  "query": "atorvastatni",
  "query_type": "typo",
  "country": null,
  "expected": {
    "substance_ids": ["atorvastatin"],
    "policy": "must_hit",
    "min_tier": "top5",
    "must_include_countries": ["US", "GB"]
  },
  "expect_empty": false,
  "provenance": {"source": "product_name", "row_ids": ["..."], "generator": "gen_cases.py v1", "seed": 20261027},
  "tags": ["latin", "trade", "error_edit_distance_1"]
}
```

三条期望策略：
- `must_hit`：Top-5 内必须出现期望成分（可用于 CI 卡口）；
- `must_empty`：必须 0 结果且提示在允许文案集合（"没有匹配的名字" / "在 XX 没有收录到这个名字"）；
- `gap`：当前基线预期 miss、作为改造目标（拼音/全量简繁），单独统计，不计入当前通过率。

### 6.2 八类用例生成规则与配额（合计 320）

| # | 类别 | 目标数 | 素材来源（现库规模） | 生成算法 | 期望成分来源 | 期望 |
|---|---|---:|---|---|---|---|
| 1 | **en 错拼** | 45 | `name_variant.raw` 拉丁 134,266 条 / 商品名去重 107,397 | 取长度 ≥6 的贸易名/INN，做 1 次编辑：相邻换位 40%、键盘邻键替换 30%（qwerty 邻接表）、删字符 20%、插字符 10%；先按 difflib ratio≥0.78 过滤（否则当前 fuzzy 不命中） | 该产品 `product_component → variant → substance`（DB 关系，独立于检索） | must_hit（Top-5，fuzzy tier） |
| 2 | **es 错拼** | 30 | ES/MX 贸易名去重 23,755 + WHO 西语名 1,415 | 同上 + 去重音符（é→e）子类 | 同上 | must_hit |
| 3 | **zh 错字** | 25 | 中文名 12,103 条（`name_variant` han） | 字形混淆表（人工 curated 30 对，如 氨/胺、氯/禄、唑/坐、嗪/秦），替换 1 字；长度 ≥4 才生成（3 字命中风险低） | 同上 | must_hit |
| 4 | **拼音** | 40 | 中文 INN/常用名 top 150（从 `substance.inn_zh` 2,405 + CN 贸易名 top 中取；全拼/首字母各半） | 拼音需 `pypinyin`（**当前环境未安装**，见 §6.4）：全拼 `jiasuan'erlinsuan`、首字母 `jsels` | 中文名→`substance_id`（DB 关系） | 当前 `gap`（预期 miss）；加拼音索引后 must_hit |
| 5 | **简繁** | 30 | 中文名中含 `normalize_name._T2S` 90 对覆盖字的 top 名 | 用 `_T2S` 反表把简体字转回繁体，构造繁体查询（如 嗎丁啉/嗎丁啉、鹽酸/盐酸） | 同上 | must_hit（现 normalize 已做 T2S）；未覆盖字记 `gap`，推动换 OpenCC 全表 |
| 6 | **复方** | 55 | 多成分产品 48,784 个（component ≥2） | 两种查询：a) 该产品贸易名原样；b) 成分英文名用 " + " 连接；期望其为「成分集合」（卡片 `substances` 应包含全部成分，或至少 ≥2 且含主成分） | `product_component` 全集合 | must_hit（成分集合 ⊆ 卡片成分） |
| 7 | **盐型** | 55 | `variant.salt<>''` 1,555 条 + CN 盐型前缀名 1,126 条 | 从盐型 variant 找挂它的产品名/中文名，或英文 INN+salt 拼接（"metformin hydrochloride"）；期望碱基 substance | variant→substance | must_hit（→ 碱基成分） |
| 8 | **零结果预期** | 40 | 生成器 + DB 负校验 | 随机拉丁串（5–10 字符）、随机 CJK 2–4 字、非药词（"hello"、"20 mg"、"tablet"、乱序商标名） | 无 | must_empty；每个候选必须先 SQL 验证：无 `name_key` 命中（CJK 还要验证 2 字 contains 不命中）、无 nickname/drug_term/confusable 命中，否则重采样 |
| | **合计** | **320** | | | | |

配额内部再分市场：每类按 US/GB/CA/AU/ES/MX/CN 分层抽样（尽量均衡，单一市场名上限 50%）；语言维度 en/es/zh 与查询语言一致（复方/盐型跨语言各半）。

### 6.3 生成流程（建议脚本 `tests/trilingual/gen_cases.py`，本任务只给设计）

1. **锁快照**：只读打开 `data/drugs.db`（`mode=ro`），记录 DB 文件 sha256/mtime、`PRAGMA user_version`、`coverage` 快照到 `cases_v2.meta.json`——评测集与库版本绑定，换库重生成而不是沿用旧期望。
2. **分层采样**：按 `category × country × script` 分层，`random.Random(seed=20261027)` 固定种子；每类配额见 §6.2。
3. **生成查询**：按表内算法构造；查询字符串**不得来自检索结果**，只来自 DB 原始名字/说明性规则。
4. **生成期望**：只走 DB 结构关系（`product_component → variant → substance`）与规范化规则；不调用 `lib/search.py`（**反循环论证**）。
5. **负例二次验证**：零结果类必须用 SQL 验证「无 key / 无 alias / 无 confusable / CJK 无 2 字子串」，通过才收录。
6. **落盘**：`tests/trilingual/cases_v2.csv`（或 .jsonl）+ `cases_v2.meta.json`（种子、DB 哈希、生成器版本、每类计数、provenance row ids）。
7. **人工抽检**：按类分层抽 10%（32 例）由人核对「期望是否成立」，抽检记录进报告；抽检不过的规则回改生成器。
8. **冻结**：抽样集冻结为 v2.0；后续只增不改（新增走 v2.1），与 `gap` 类改造进度绑定。

### 6.4 依赖与素材缺口（明确列出）

| 缺口 | 影响 | 建议 |
|---|---|---|
| `pypinyin` 未安装（实测 `ModuleNotFoundError`；`.pylibs/` 也没有） | 拼音 40 例无法自动生成 | 在 `.pylibs` 放 `pypinyin` wheel（MIT），或先人工建 `data/sources/pinyin_top300.csv`（Unihan `kMandarin` 派生，Unicode 数据许可） |
| 简体→繁体只有 `normalize_name._T2S` 的 90 对 | 简繁 30 例只能覆盖这 90 字 | 换 OpenCC `TSCharacters.txt`（Apache-2.0）完整表，同时升级 normalize；许可写入 `data/sources/README.md` |
| 中文错字混淆表不存在 | zh 错字 25 例需人工表 | 建 `data/sources/zh_char_confusions.csv`（30 对，人工审） |
| `name_variant` 里 ES/MX 本地商品名多、INN 少 | es 错拼可能集中在品牌名 | 用 `data/who_inn_names.csv`（1,415 西语 INN）补 INN 类查询 |

### 6.5 harness 改造与验收门槛

扩展现有 `tests/trilingual/run_tests.py`（新增 `--cases <csv>` 与 `--category`，保留现有 72 例为 `legacy` 子集）：

| 指标 | 门槛 |
|---|---|
| `must_hit` Top-5（全类） | **≥ 95%** |
| `must_hit` Top-5（单类） | **≥ 90%**（en/es 错拼、盐型、复方、简繁） |
| `must_empty` | **100%**（零结果误报是硬伤） |
| `gap` 类（拼音/全量简繁） | 先记录基线，改造后 must_hit ≥ 90% |
| legacy 72 例 | 不得回退（当前 67/72 案例、96.6% Top-5 为基线） |
| 运行时长 | 320 例约 **3–4 分钟**（当前 354 查询约 9 分钟；新 harness 建议 `--limit/--sample` 与可缓存） |

### 6.6 风险与规避

1. **循环论证**：期望绝不能取自 `lib/search.py` 输出；生成器只读 DB 结构 + 规则表（已写入流程第 4 步）。
2. **负例意外命中**：2 字中文 contains 修复后，随机 CJK 更易误中 → 零结果例必须 SQL 二次验证后收录（第 5 步）。
3. **数据漂移**：期望与 DB 版本绑定（meta 里存 sha256），换库必须重生成并重跑抽检。
4. **许可**：pypinyin(MIT)、Unihan(Unicode License)、OpenCC(Apache-2.0) 的来源/许可写入 `data/sources/README.md` 后再入库。
5. **维护成本**：320 例 + 人工抽检每次改造跑一遍；建议只对 `must_hit` 类做 CI 卡口，`gap` 类出趋势报告。

---

## 7. 复现命令与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 生成 9 行更新草稿（只读 CSV/DB，不改库）
& $py .tmp/who-inn-apply/build_update.py

# 2) 变更审计（列/行数/BOM/9 行 diff + DB 当前计数）
& $py .tmp/who-inn-apply/audit_after.py

# 3) dry-run（只读 DB；本任务已跑，日志在 .tmp/who-inn-apply/）
& $py etl/merge_es_substances.py --dry-run
& $py etl/merge_es_substances.py --include-unprefixed --dry-run

# 4) apply（Lead 执行，本任务未跑）
& $py etl/merge_es_substances.py --include-unprefixed --apply
```

| 产物 | 内容 |
|---|---|
| `data/es_inn_overrides.csv` | 9 行更新（3 mergeable + 6 补 WHO 证据），1,081 行/列/BOM 不变 |
| `.tmp/who-inn-apply/es_inn_overrides.before.csv` | 变更前备份（diff 与回退用） |
| `.tmp/who-inn-apply/es_inn_overrides.draft.csv` | 生成草稿（与最终文件一致） |
| `.tmp/who-inn-apply/update_rows.json` | 9 行 before/after + 分类（mergeable/self_match） |
| `.tmp/who-inn-apply/stats_before_after.json` | 状态分布 182/674/159/66 → 185/672/158/66 |
| `.tmp/who-inn-apply/audit_after.json` | 变更审计（9 行、0 增删、BOM/列一致）+ DB 计数 + 目标成分市场 |
| `.tmp/who-inn-apply/dryrun_final_default.log` / `dryrun_final_unprefixed.log` | 最终 dry-run 日志（2 / 3 可合并，errors 0） |
| `.tmp/who-inn-apply/dryrun_baseline_unprefixed.log` / `dryrun_draft_default.log` | before 对照（0 可合并） |
| `.tmp/who-inn-apply/build_update.py` / `audit_after.py` / `eval_material_stats.py` | 可复现脚本 |
| `.tmp/who-inn-apply/eval_material_stats.json` | 评测集扩容素材规模（146,369 name_variant / 48,784 复方 / 1,555 盐型 / 1,737 WHO …） |

---

## 8. 边界与交接

- 本任务**未写 `data/drugs.db`**：所有 merge 调用均 `--dry-run`（脚本只读打开，日志首行 `(只读)`）；CSV/草稿/审计/日志全部落在 `.tmp/who-inn-apply/`。
- 未跑 `git`、未发布、未跑 `site/build.py`、未改任何其它跟踪文件；写范围仅 `data/es_inn_overrides.csv`、`reports/who-inn-merge.md`、`.tmp/who-inn-apply/`。
- 交接给 Lead：① 若认可，按 §4.3 在无并行写库窗口执行 `--include-unprefixed --apply`（预期 3 合并、products/components 总数不变），再决定 rebuild/publish；② 修上游 `compare.py` 的 `mx-es-` 过滤后重跑 WHO 对比；③ 评测集 v2 的 4 个素材缺口（pypinyin / OpenCC / 中文错字表 / 西语 INN 补盲）建议另开任务，按 §6.3 流程实现 `gen_cases.py`。
