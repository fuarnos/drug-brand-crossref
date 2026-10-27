# D2（盐基折算）/ D3（`/warn`）数据层实现报告

> 任务：共享任务 `task-8` · 状态：**实现完成 + 副本验证通过（60/60 断言 PASS）**
> 依据：`reports/dose-mapping-plan.md`（418 行设计）+ `.tmp/dose/` 盐表与证据
> 数据库副本：`.tmp/dose-impl/test.db`（`data/drugs.db` 的完整拷贝，450 MB）
> **真实库 `data/drugs.db` 本轮未被写入**；未跑 git / 服务 / `site/build.py` / 发布。

---

## 0. 一句话结论

数据层已就绪，且**默认全库不产生任何折算数字**：schema v0.4 幂等迁移通过、
1,555 条 `salt` 全部完成分类、`base_fraction` 只在 `strength_basis` 已知时才会写、
41 条人工策展警示已落成可执行种子。给 Lead 的 apply 顺序见 §7。

副本验证数字速览：

| 指标 | 数值 |
|---|---|
| variant / 组件 | 14,234 / 497,513（当前 `data/drugs.db`；设计报告快照为 14,240） |
| `salt` 非空 | **1,555**（485 个去重串） |
| 规范化后：可自动折算的单一纯盐 / 复盐待核 / 非盐 | **945 / 145 / 465** |
| 可识别盐/水合物（报告口径） | **1,134**（设计报告为 1,146，差 12 条为多词盐名归类口径） |
| `strength_basis` 存量 | **14,234 全部 `unknown`**（符合"未知不猜"） |
| `base_fraction` 存量 | 14,234 全部 1.0（未动） |
| 副本上模拟 basis 已知后可填 | 12 variant / 3,789 组件（仅为 fixture） |
| 全量潜在可填（38 个已有碱基 MW 的 variant） | 12,401 组件 ≈ 22.1% 含盐组件 / 2.49% 全部组件 |
| `dose_warning` 种子 | **41 条**（published 5 / draft 36） |
| init_db / normalize / fractions / seed 幂等 | 全部通过（二次 apply 0 变更） |
| 回滚 | 四个脚本均可用备份 CSV 还原，且还原后可重放 |
| `PRAGMA integrity_check` / `foreign_key_check` | `ok` / 无违规 |

---

## 1. 改动文件

| 文件 | 改动 |
|---|---|
| `db/schema.sql` | `variant` 新增 `salt_code TEXT NOT NULL DEFAULT ''`、`strength_basis TEXT NOT NULL DEFAULT 'unknown' CHECK (base/salt/salt_equivalent/unknown)` + 两个索引；新增 `dose_warning` 表（18 列：warning_id/两个 substance 外键可空/country 可空/rule/severity/三语标题正文/source_url/evidence/status/reviewed_by/时间）+ 两个索引；头部版本改 v0.4 |
| `db/init_db.py` | 新增 `_ensure_variant_columns()`：先补列再执行 schema（否则 schema 里建在 `salt_code` 上的索引在老库报 `no such column`）；`build()` 前后各调一次，幂等；docstring 更新 |
| `etl/normalize_salts.py` | **新增**。纯函数 `classify_salt()`/`salt_code_of()`（多语言同义词、复盐、水合物、酯、溶剂化物、非盐分流），`insert_variant()` 供 ingest 调用（老库自动回退旧 SQL），CLI `--dry-run/--apply/--rollback/--verify`，apply 前落回滚 CSV |
| `etl/apply_salt_fractions.py` | **新增**。读 `data/salt_base_fraction.csv` + 内嵌 27 个物质碱基 MW，按 `f = n·M/(n·M+Δ)` 回填；只填 `salt_code` 命中单一盐 + `strength_basis≠unknown` + MW 已知 + 当前仍为 1.0 的行；CLI 同上 + `--include-hydrate/--only-verified/--base-mw-csv` |
| `data/salt_base_fraction.csv` | **新增**。从 `.tmp/dose/` 的 40 行盐表整理为正式数据文件（`salt_code,salt_en,category,n_base,increment_formula,increment_mw,fraction_rule,example,example_fraction,source,status,note`）；status 机器可读：**verified 9 / computed 30 / manual_review 1** |
| `data/seed_warnings.py` | **新增**。41 条人工策展 `dose_warning` 种子 + 校验器（必填/枚举/唯一 id/监管域名/evidence≤200字/published 双人复核）+ 幂等 upsert + 备份/回滚 + dry-run 审计 CSV；**不主动写库** |
| `etl/ingest_openfda_ndc.py` | 仅 2 处：import `insert_variant`；variant INSERT 改为 `insert_variant(db, vid, sid, salt)`（salt 拆词逻辑 `split_salt` 未改） |
| `etl/ingest_ca_dpd.py` | 仅 2 处：import `insert_variant`；variant INSERT 改为 `insert_variant(db, vid, rid, salt or "")`（`canonical_base` 未改） |
| `.tmp/dose-impl/` | 副本 + 验证脚本 + 四类审计 CSV + 回滚备份 + `logs/validation.log`（证据，未跟踪） |
| `reports/dose-d2d3-impl.md` | 本报告 |

未做（按任务边界）：`docs/方案与数据模型.md`、`CHANGELOG.md`、`site/build.py`、`/warn` 页面接线、`base_fraction_source`/`d2_status` 字段（本任务 schema 只要求 `salt_code` + `strength_basis`；证据落在审计 CSV 与 `dose_warning.evidence`）。

---

## 2. schema v0.4 与迁移（幂等）

### 2.1 改动

```sql
ALTER TABLE variant ADD COLUMN salt_code TEXT NOT NULL DEFAULT '';
ALTER TABLE variant ADD COLUMN strength_basis TEXT NOT NULL DEFAULT 'unknown'
  CHECK (strength_basis IN ('base','salt','salt_equivalent','unknown'));
CREATE INDEX idx_variant_salt_code ON variant (salt_code);
CREATE INDEX idx_variant_basis    ON variant (strength_basis);

CREATE TABLE dose_warning (
  warning_id TEXT PRIMARY KEY,
  substance_id TEXT REFERENCES substance(substance_id),          -- 可空（R4 商品名警示）
  related_substance_id TEXT REFERENCES substance(substance_id),  -- 可空（pair 另一端）
  country TEXT,                                                  -- 可空（空=跨国）
  rule TEXT CHECK (rule IN ('R1'..'R7')), severity TEXT CHECK (severity IN ('high','medium','info')),
  title_zh/title_en/title_es, body_zh/body_en/body_es,
  source_url TEXT NOT NULL, evidence TEXT NOT NULL,
  status TEXT CHECK (status IN ('published','draft','retracted')),
  reviewed_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
```

语义：`salt` 保留来源原文，`salt_code` 是规范化分类结果；`'mixed'`=复盐/混合/未收录盐（人工核对），`'non_salt'`=不是盐，`''`=来源没给盐。`strength_basis` 默认 `unknown` 时 D2 只显示"暂不可用"，不折算。

### 2.2 迁移机制（老库直接升级，无需重建库）

`init_db.build()` 现在做三件事，全部幂等：
1. **先** `_ensure_variant_columns()`：`PRAGMA table_info(variant)` 缺列才 `ALTER TABLE ADD COLUMN`（顺序关键：schema.sql 里 `CREATE INDEX ... ON variant(salt_code)` 若在新列之前执行会报 `no such column`，第一次副本验证就是踩到这个坑后修正的）；
2. `executescript(db/schema.sql)`：`CREATE TABLE/INDEX IF NOT EXISTS` 补 `dose_warning` 等；
3. `_ensure_source_columns()` + 再跑一次 `_ensure_variant_columns()`（新库/老库统一收口）。

副本实测：第 1 次输出 `迁移 variant 表：新增列 salt_code / strength_basis`，第 2 次**无迁移输出**，variant 数不变，存量 14,234 行 `salt_code=''`、`strength_basis='unknown'`。

---

## 3. 盐名规范化（`etl/normalize_salts.py`）

### 3.1 分类规则（保守优先，宁可不折算）

1. 多语言同义词归一：`hcl→hydrochloride`、`sodio/sódico/sodica→sodium`、`cloruro→chloride`、`sulfato→sulfate`、`bromuro→bromide`、`lactato→lactate`、`besilato→besylate`、`mesilato→mesylate` 等；
2. 复盐/混合：同一串出现 ≥2 个盐词，或"1 个盐词 + 未识别词"（如 `sodium phosphate`、`ferrous sulfate`、`palmitate hydrochloride`）→ `mixed`，只统计不折算；
3. 水合物/无水晶型：`hydrochloride monohydrate` → `hydrochloride`（kind `salt_hydrate`，D2 默认跳过待人工确认强度基准）；`hydrochloride anhydrous` → `hydrochloride`（正常折算）；单独 `monohydrate/anhydrous` → `non_salt`；
4. 酯类：`valerate/propionate/palmitate/...` 及 `hydrocortisone acetate` 类 → `non_salt`（kind `ester`）；
5. 溶剂化物（`propylene glycol solvate`）→ `mixed`；
6. 非盐标记（疫苗株 `human/h1n1/inactivated/recombinant`、油脂、`chelate`、动植物提取物、无机氧化物/碳酸盐）→ `non_salt`；纯数字/符号垃圾 → `non_salt`；
7. 唯一一个可识别单盐 + 其余只有晶型词 → 可折算的 canonical 盐代码（与 `data/salt_base_fraction.csv` 对齐，共 28 种落库）。

### 3.2 规范化前后数量（副本实测）

| 分类 | variant 数 | 说明 |
|---|---|---|
| 原 `salt` 非空 | 1,555（485 个串） | 设计报告口径 1,555/484 |
| → canonical 单一纯盐 | **945** | 28 种盐；top：hydrochloride 293、sodium 143、sulfate 68、acetate 61、chloride 49、bromide 36、phosphate 35、mesylate 31 |
| → `mixed` 复盐/待核 | **145** | 如 sodium phosphate(4)、calcium phosphate(3)、epinephrine hydrochloride 等整段成分名 |
| → `non_salt` | **465** | 其中垃圾/生物制品/油脂/螯合物 391、纯水合物 50、酯 24 |
| 原 `salt` 为空 | 12,679 | `salt_code=''` |
| **可识别盐/水合物（报告口径）** | **1,134** | = salt 915 + salt_hydrate 30 + salt_mixed 139 + hydrate 50；设计报告 1,146，差 12 条（多词盐名口径，不影响写入安全性） |

`variant.salt` 原文**一行未改**（可追溯，collision/命名逻辑不受影响）；`salt_code` 与 `salt` 并存。审计明细：`.tmp/dose-impl/salt_normalization.csv`（485 行，含每串的 kind/reason）。

### 3.3 ingest 接入（只改两处调用）

`openFDA` 与 `CA DPD` 建 variant 时改调 `insert_variant(db, vid, sid, salt)`：新库写 `salt_code`，**老库未迁移时自动回退旧 SQL**（不因缺列崩 ETL）。已验证两个 ingest 模块可正常 import、两条路径均写入正确。ES/GB/CN/MX/AU 的补盐属于后续 P3，本轮未动。

---

## 4. 盐基折算（`data/salt_base_fraction.csv` + `etl/apply_salt_fractions.py`）

- **公式**：`f = n·M(base) / (n·M(base) + Δ)`（水合物 `+k·18.015`，默认跳过待核）；
- **数据文件**：40 行规则（30 盐/形态 + 1 复盐 hyclate + 9 酯），含分子式、Δ、示例、PubChem 来源、status（verified 9 / computed 30 / manual_review 1）；
- **碱基分子量**：27 个物质内嵌在 `apply_salt_fractions.py` 的 `BASE_MW`（来源逐条标注；可用 `--base-mw-csv` 覆盖）——因本任务写范围不含额外 data 文件，故放在脚本内并保留来源字符串，后续可迁到 `data/`；
- **写入条件**（四条同时满足）：`salt_code` 命中盐表单一盐（`mixed/non_salt/hyclate` 排除；水合物默认排除）→ `strength_basis ∈ {base,salt,salt_equivalent}` → substance 有碱基 MW → 当前 `base_fraction=1.0`（不覆盖人工值）。

副本实测：
- `strength_basis` 全 `unknown` 时：**可填 0 / 组件 0，不写库**（这是真实库当前会发生的默认行为，符合设计"未知不猜"）；
- fixture 模拟 8 个 PubChem 已核对物质共 22 个 variant 的 basis 已知：可填 **12 variant / 3,789 组件**（6.74% 含盐组件、0.76% 全部组件）；9 个已验证盐-碱基对逐一断言：metoprolol tartrate 0.7808、succinate 0.8191、levothyroxine sodium 0.9725、amlodipine besylate 0.7211、atorvastatin calcium 0.9671、quetiapine fumarate 0.8686、sertraline HCl 0.8936、sildenafil citrate 0.7119、omeprazole magnesium 0.9688；水合物（atorvastatin calcium trihydrate）默认跳过；`mixed/non_salt` 与 `unknown basis` 一行未写；
- 二次 apply：0 写入（幂等）；`--rollback` 后全部回到 1.0，重放可恢复同样 12 行；
- 审计：`.tmp/dose-impl/base_fraction_candidates.csv`（945 个候选 variant + decision/reason/base_mw）。

### 4.1 覆盖率预估（副本实测，非外推）

| 阶段 | 可解释组件 | 占含盐组件（56,204） | 占全部组件（497,513） |
|---|---|---|---|
| 现状 D1 | 0 | 0% | 0% |
| 本次 fixture（12 variant） | 3,789 | 6.74% | 0.76% |
| **真实 potential（38 个已核对 MW 的 canonical variant；前提：人工填 `strength_basis`）** | **12,401** | **≈22.1%** | **≈2.49%** |
| 长尾（945 个 canonical variant，需补碱基 MW + 逐药核 basis） | — | 上限约 60–70%（设计报告外推） | 约 7% |

> 与设计报告 D2 试点预估（11,983 组件 / 21.3% / 2.4%）基本吻合。

---

## 5. `/warn` 种子（`data/seed_warnings.py`，41 条，未写真实库）

| 维度 | 分布 |
|---|---|
| rule | R1 14、R2 10、R3 1、R4 5、R5 3、R6 8 |
| severity | high 25、medium 16 |
| status | published 5（报告 [已验证]：Tylenol/泰诺、Benadryl、Gaviscon、metoprolol tartrate vs succinate、levothyroxine sodium vs base）、draft 36（本任务未二次核实，只入种子不发布） |
| 挂点 | 34 个 substance_id 全部在库中存在；R4 商品名警示 `substance_id` 为空（人名/品牌，无单一成分） |

覆盖主题：R4 同名不同药（Tylenol/泰诺、泰诺/泰诺林、Benadryl、Gaviscon、Sudafed/Sudafed PE）；R1/R2 释放机制与盐型（美托洛尔酒石酸盐/琥珀酸盐、左甲状腺素钠、茶碱/氨茶碱、阿片类 IR/ER、硝苯地平、地尔硫䓬、维拉帕米、卡马西平、丙戊酸、哌甲酯、文拉法辛、安非他酮、二甲双胍、可乐定、喹硫平、左旋多巴）；R2 盐型（氨氯地平、阿托伐他汀、奥美拉唑镁、苯海拉明、苯妥英钠、沙丁胺醇、克林霉素、地塞米松磷酸钠、氢化可的松琥珀酸钠、红霉素酯类）；R5 途径（注射 vs 口服）；R6 治疗窗窄（华法林、地高辛、锂、他克莫司、环孢素、胰岛素 U-100/U-500、肝素）；R3 复方配比（Augmentin 2:1/4:1/7:1/14:1，标 draft）。

校验器强制：`source_url` 必须是监管来源域名（DailyMed/FDA/eMC/EMA/DPD/CIMA/NMPA…）、`evidence ≤200 字`、published 需 ≥2 位复核人、id 唯一、枚举合法。副本实测：apply 41 行 → rollback 0 行 → 重放 41 行，`dose_warning` 表可正常读写。

---

## 6. 命令与回滚

```bash
# 迁移（幂等）
python db/init_db.py                                   # 真实库；副本：--db .tmp/dose-impl/test.db
# 盐规范化
python etl/normalize_salts.py --dry-run                # 只统计 + 审计 CSV
python etl/normalize_salts.py --apply                  # 事务写 salt_code（先写回滚 CSV）
python etl/normalize_salts.py --verify
python etl/normalize_salts.py --rollback               # 用最近一次备份还原
# 盐基折算（strength_basis 未知时 0 写，正常）
python etl/apply_salt_fractions.py --dry-run
python etl/apply_salt_fractions.py --apply
python etl/apply_salt_fractions.py --verify
python etl/apply_salt_fractions.py --rollback
# /warn 种子
python data/seed_warnings.py --dry-run                 # 只校验 + 打印；默认不写库
python data/seed_warnings.py --apply                   # 需显式
python data/seed_warnings.py --rollback
```

安全阀：`normalize_salts` / `apply_salt_fractions` / `seed_warnings` 的 `--apply/--rollback` 默认**拒绝**写 `data/drugs.db`，必须加 `--confirm-real-db`；回滚备份在 `.tmp/dose-impl/backups/`（normalize 1,555 行、fractions 12 行、seed 41 行；均为 apply 前旧值 + apply 后新值，回滚只还原"仍等于 apply 后值"的行，避免覆盖人工修改）。

---

## 7. 给 Lead 的 apply 顺序（建议）

1. **备份真实库**：`copy data/drugs.db data/backups/drugs.db.bak-<时间戳>`；
2. **迁移**：`python db/init_db.py`（只加列/表/索引；预期不重建 product 表）；随后 `sqlite3 data/drugs.db ".schema variant"` 抽查；
3. **盐规范化**：`python etl/normalize_salts.py --dry-run` 看数字（预期 canonical≈945 / mixed≈145 / non_salt≈465），再 `--apply`（1,555 行），`--verify`；保留 `.tmp/dose-impl/salt_normalization.csv` 作为审计附件；
4. **人工填写 `strength_basis`（不在本任务写范围，必须做在 fractions 之前）**：先对 9 个 PubChem 已核对物质 / 38 个已有碱基 MW 的 variant 逐药按说明书填 `base|salt|salt_equivalent`；**不填则第 5 步写 0 行（安全默认）**；
5. **盐基折算**：`python etl/apply_salt_fractions.py --dry-run`（预期 38 variant / 12,401 组件潜力）→ `--apply`（只写 basis 已知行）→ `--verify`；
6. **/warn 种子**：先审 `data/seed_warnings.py` 中 36 条 draft（建议本轮只 apply `status='published'` 的 5 条，或人工改 status 后再 apply）→ `python data/seed_warnings.py --apply`；
7. **建站验证**（由建站/发布会话执行，本任务不跑）：`python site/build.py` + `python -m pytest`，抽查成分页 D2 块在 `strength_basis='unknown'` 时隐藏、`/warn` 三语页面；
8. 任一步异常：按 §6 反向 rollback（seed → fractions → normalize），必要时回退数据库备份。

---

## 8. 验证证据与边界

- 全量验证日志：`.tmp/dose-impl/logs/validation.log`（**60/60 断言 PASS**，11.2s；含两次 init_db、两轮 apply/二次 apply/rollback/重放、样本值逐条断言、`integrity_check=ok`、`foreign_key_check` 无违规）；
- 副本终态：`.tmp/dose-impl/test.db`（variant 14,234；`salt_code` 非空 1,555；`base_fraction` 非 1.0 共 12；`dose_warning` 41）；
- 验证脚本：`.tmp/dose-impl/run_validation.py`（可复跑）；集成检查：`.tmp/dose-impl/_integration_checks.py`；
- **未写真实库**：所有写操作只发生在 `.tmp/dose-impl/test.db`；对 `data/drugs.db` 只有只读 URI 查询；
- **未运行** git、服务、`site/build.py`、发布；
- 风险与后续：① `strength_basis` 仍是全库 unknown，D2 实际输出为 0，需数据策展（本任务按设计只统计不猜）；② 145 个 `mixed`（复盐/整段成分名）与 30 个水合物待人工核对，未折算；③ 盐表的 30 个 computed 盐 Δ 按 IUPAC 原子量自算，上线前建议补 PubChem 抽核（9 个 verified 已核）；④ `BASE_MW` 内嵌在脚本里是写范围限制下的折中，后续建议迁到 `data/` 并加入 `CHANGELOG`/文档；⑤ 本轮未重跑 openFDA/CA ETL（无网络/原始数据），`insert_variant` 只做了代码级与老库回退验证。
