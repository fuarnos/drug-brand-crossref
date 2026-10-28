# 中文成分名 inn_zh 回填报告

日期：2026-10-28 ・ 任务：task-42 ・ 站点版本：v0.3.5
产物：`etl/build_inn_zh_backfill.py`、`data/inn_zh_backfill.csv`、`etl/apply_inn_zh.py`、本报告；
验证明细在 `.tmp/inn-zh/`。
本轮**未写 `data/drugs.db`**（apply 由 Lead 审后执行）；未跑 site/build.py、git/发布。

---

## 1. 摘要

| 指标 | 结果 |
|---|---|
| DB 快照 | `.tmp/inn-zh/drugs-base.db`（sha256 `31bcae91abc21796b39aa83f9ce2e8458c4bb90c515af41b48c09b0eefd6b313`，size 450,396,160） |
| substance 总数 / 修复前已有 `inn_zh` | 12,790 / **2,055（16.1%）** |
| **可回填候选** | **898 个成分**（high 536 / medium 324 / low 38） |
| 回填后覆盖率（全部 898） | **2,953 / 12,790 = 23.1%**（+898，+7.0pp） |
| 仅 high（推荐首轮 apply） | 2,591 / 12,790 = 20.3%（+536） |
| high + medium | 2,915 / 12,790 = 22.8%（+860） |
| 冲突/丢弃 | 与现有 inn_zh 重名 1 个、同形异义（同名多成分）2 个；`ambiguous` 221 个成分判不了留空；复方/多成分产品名 23,174 条不当成分名 |
| apply 验证 | 副本上 apply high 536 行 → 覆盖率 20.3%；再 apply 0 行（幂等）；rollback 后 substance 表 sha256 与回填前**完全一致**；再 rollback 幂等；high+medium 副本 860 行 → 22.8% |

---

## 2. 来源与推导规则（`etl/build_inn_zh_backfill.py`）

只读 DB；只处理 **`inn_zh` 为空** 的成分（不覆盖已有值；`cn-*`/`mx-es-*`/非 ASCII 的
`inn_en` 跳过）。

| 优先级 | 证据 | 说明 |
|---|---|---|
| 1 | `data/cn_inn_overrides.csv`（`status=mergeable`，`en_substance_id` 命中） | CN 中文名 → 英文 INN 的人工/自动确认映射；318 条用上。候选名会再清洗剂型尾巴（如「紫杉醇聚合物胶束」→「紫杉醇」），若产品候选里有更规范写法则回退 |
| 2 | CN 单成分产品的中文通用名 | `product(country='CN')` → `product_component`（**单成分产品**）→ `variant` → `substance`；`product_name` 里 `name_key.script='han'` 的名字经 `ingest_nhsa.canonical_name` 剥剂型/限定词（盐基保留，与现有 inn_zh 约定一致） |
| 3 | 去盐基聚合回退 | 同成分多个盐型/写法且无单一多数时，剥掉盐基前缀后聚合（如地塞米松磷酸钠/醋酸地塞米松 → 地塞米松） |

**过滤**：
- 复方/多成分名不当成分名：`复方/多维/葡萄糖/氯化钠/人工牛黄…` 词表 + 用现有中文名
  （`substance.inn_zh`、`cn_name_map.json`、`cn_aliases*.csv`、`drug_term.label_zh`）
  做最长覆盖切分，≥2 个已知成分即丢弃（共 23,174 条产品名被跳过）；
- 剂型/规格残留（`…片/胶囊/注射液/乳膏/聚合物胶束` 等）→ 反复剥尾巴后仍非法则丢弃（3,711 条）；
- 同成分多候选：多数派 `share≥0.6` 采纳；否则去盐基聚合（`share≥0.6`）；仍判不了 → 留空（221 个）；
- 同一中文名被推荐给多个成分（如 `Mannitol` vs 西语重复 `Manitol`）或与现有 `inn_zh` 重名
  → 丢弃（3 个）；优先保留非 `mx-es-*` 的英文成分；
- confidence：override 沿用人工文件 confidence；产品多数派 `share≥0.8 且产品数≥3` → high，
  ≥3 → medium，其余 low；去盐基回退 ≤medium。

**CSV 列**：`substance_id,inn_en,zh_candidate,confidence,method,count,share,variants,evidence`
（evidence 含 override 的 `cn_substance_id`/URL 或产品证据的计数/示例 product_id）。

样例：

| inn_en | 回填中文 | 来源/置信度 |
|---|---|---|
| Abatacept | 阿巴西普 | override / high |
| Acarbose | 阿卡波糖 | 产品多数派 / high |
| Acetylcysteine | 乙酰半胱氨酸 | 产品多数派 / high |
| Metoprolol | 美托洛尔 | 去盐基聚合 / medium |
| Dexamethasone | 地塞米松 | 去盐基聚合 / medium |
| Afatinib | 马来酸阿法替尼 | 产品多数派 / high（盐基保留，与库内约定一致） |
| Mannitol | 甘露醇 | 产品多数派 / high（西语重复 Manitol 冲突已丢弃） |

---

## 3. 回填工具（`etl/apply_inn_zh.py`）

- 默认 **dry-run**（只读）：校验 substance 存在、`inn_en` 一致、当前 `inn_zh` 为空；
  打印可回填数 / 覆盖率 before-after / 按 confidence 分布；
- `--min-confidence high|medium|low`（默认 **high**）控制写入门槛；
- `--apply`：事务内 `UPDATE substance SET inn_zh=? WHERE substance_id=? AND
  (inn_zh IS NULL OR trim(inn_zh)='')`（**只填空，绝不覆盖**），先写完整撤销清单
  （旧值+新值）再 commit；任一行更新 0/多行即中止回滚；
- `--rollback [manifest]`：逐行把新值恢复为旧值（`NULL`/`''` 原样恢复）；
  只恢复「当前值 == 写入值」的行，被别人改过则记冲突不覆盖；可重复执行（幂等）；
- 撤销清单默认 `.tmp/inn-zh/undo_<UTC>.json`。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 生成/重建 CSV（只读快照 DB，可重跑）
& $py etl/build_inn_zh_backfill.py --db .tmp/inn-zh/drugs-base.db

# 2) dry-run（默认 high）
& $py etl/apply_inn_zh.py
& $py etl/apply_inn_zh.py --dry-run --min-confidence medium

# 3) Lead 备份 DB 后 apply（建议先 high）
& $py etl/apply_inn_zh.py --apply
# 4) 如需回滚
& $py etl/apply_inn_zh.py --rollback
```

**副本验证证据**（`.tmp/inn-zh/test_apply.py`，结果 `apply_test_stats.json`）：

| 步骤 | 结果 |
|---|---|
| 基线 | substance 12,790，`inn_zh` 2,055，表 sha256 `de83dbe6…` |
| apply（high） | 536 行；`inn_zh` 2,591（20.3%）；原 2,055 行值未被改动 |
| 再 apply | 0 行（幂等），表 sha 不变 |
| rollback | 表 sha256 恢复为 `de83dbe6…`（逐行完全一致） |
| 再 rollback | 幂等成功 |
| 另副本 apply（high+medium） | 860 行 → `inn_zh` 2,915（22.8%） |

---

## 4. 覆盖率与冲突/丢弃统计

| 项 | 数量 |
|---|---|
| 现有 inn_zh（快照） | 2,055 / 12,790（16.1%） |
| 有「单成分 CN 产品名」候选的空成分 | 1,020 |
| overrides 命中 | 334 |
| 决策（产品多数派/回退/override） | 901（override 319 / 多数派 564 / base 聚合 16） |
| 留空 ambiguous | 221（多候选竞争、无主导写法） |
| 冲突丢弃 | 3（与现有重名 1、同名多成分 2；西语重复成分优先保留英文 id） |
| 跳过的复方/多成分产品名 | 23,174 |
| 跳过的剂型/规格残留、非法候选 | 3,711 |
| 最终候选 | 898（high 536 / medium 324 / low 38） |
| 回填后 | 2,953 / 12,790（23.1%） |

> 快照 DB 之外的 ~9,800 个 substance（占 77%）**没有 CN 市场产品**，无法从中文产品名推导；
> 这部分需要别的数据源（ChP/CADN 中文通用名表、WHO 中文版等），本轮不覆盖。

---

## 5. 风险与 apply 建议

1. **建议先 apply high（536 个）**：dry-run 已核对；建议随机抽检 20 个中文名（对照 CN 产品名/说明书）
   后再决定是否 `--min-confidence medium`（+324 个）；low 38 个默认不 apply。
2. **不覆盖已有值**：apply 只填 `inn_zh` 为空的行，重复执行 0 行；已有 2,055 个不受影响。
3. **约定**：回填值是「CN 产品通用名（剥剂型、盐基保留）」，与现有 228 个 en substance 的
   `inn_zh` 风格一致（例：盐酸伪麻黄碱）。如果产品侧索引希望展示「碱基名」，可只取
   `product_base_aggregate`/去盐基版本（16+ 条）另议。
4. **残留风险**：少数成分的产品关系本身有建模误差（复方被拆成单成分），复方词表/切分过滤
   已拦截大部分（23,174 条），但可能仍有个别误配 → 建议 apply 前按 confidence/长度抽检；
   38 条 low 与 221 条 ambiguous 已留空，不用。
5. **并发写入风险**：本轮构建期间 `data/drugs.db` 正被其他 agent 写入（sha 多次变化），因此
   CSV 绑定快照 `31bcae91…` 生成；apply 脚本只填空值且幂等，可在最新库上安全执行。
   若 Lead 在 apply 前合并了其他成分数据，建议先用 `--dry-run` 复核（可回填数可能微调）。
6. **回滚**：撤销清单记录每行旧值/新值；`--rollback` 幂等；被他人改过的行不会被覆盖（会报冲突）。

---

## 6. 索引本地化字段 `xz` 的格式说明（供 build.py/索引改造参考，本任务不改）

现状（`site/build.py:load_index`）：每条检索索引 entry 的成分名是
`"x": " + ".join(a["subs"][:6])`——最多 6 个英文 INN 用 ` + ` 连接（复方）。

建议新增 **`xz`（中文成分名数组，与 `x` 平行）**：

```json
{
  "k": "aspirin",
  "x": "Acetylsalicylic Acid",           // 英文成分名，同上
  "xz": ["阿司匹林"],                      // 与 x 的 " + " 分段一一对应；无中文名用 ""
  "v": "aspirin", "c": ["US","GB"]
}
```

- 构建：在 `load_index()` 收集 `a["subs"]` 的同一循环里，按**相同顺序**追加对应
  `substance.inn_zh`（缺失则空串），形成等长数组；上限同 `x`（≤6）。
- 客户端：`lang=zh` 且 `xz` 存在时优先取 `xz`；逐元素为空则回退对应 `x` 分段；
  其它语言仍用 `x`。`data-i18n` 解析条可标注「中文名缺失，回退英文」。
- 列式索引 `data/idx/core.json`：把 `xz` 加入 `CORE_ARRAY_COLS`（数组先 JSON 序列化
  再字典编码，参见 build.py `cols[f] = {"d": ..., "i": ...}` 的数组分支），客户端解码逻辑
  同步加 `xz`。体积估算：898 条 × 平均 5 个汉字 ≈ +15 KB（gz 后 <5 KB），可忽略。
- 页面侧：drug/name/about 页目前直接用 `substance.inn_zh or inn_en`，回填后自动中文显示，
  无需改 schema；本次只补数据。

---

## 7. 文件与复现

| 文件 | 内容 |
|---|---|
| `etl/build_inn_zh_backfill.py` | 只读构建器（`--db/--dry-run`；可重跑；输出 CSV+统计） |
| `data/inn_zh_backfill.csv` | 898 行（UTF-8 无 BOM；列见 §2） |
| `etl/apply_inn_zh.py` | dry-run / apply / rollback（事务、只填空、幂等、撤销清单） |
| `.tmp/inn-zh/build_stats.json` | 构建统计（覆盖率/分布/丢弃） |
| `.tmp/inn-zh/drugs-base.db` | 构建绑定的 DB 快照（sha256 见 §1） |
| `.tmp/inn-zh/test_apply.py` / `apply_test_stats.json` | 副本验证脚本与结果 |
| `reports/ingredient-i18n.md` | 本报告 |

复现：

```powershell
& $py etl/build_inn_zh_backfill.py --db .tmp/inn-zh/drugs-base.db
& $py etl/apply_inn_zh.py                      # dry-run high
& $py .tmp/inn-zh/test_apply.py                # 副本 apply/幂等/回滚验证
```
