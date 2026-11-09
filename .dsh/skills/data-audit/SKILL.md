---
name: data-audit
description: 数据体检、覆盖率统计、来源溯源或写审计报告时用：只读查库、跑 check_data/ci_checks、按模板落 reports/。
whenToUse: 任务涉及数据质量、覆盖率、条数对账、字段缺失、碰撞/溯源统计、给发布决策做依据时。
---

# 数据体检与报告（data-audit）

原则：**审计只读**。不改库、不跑 ingest、不建站；数字要能一条命令复现。

## 1. 现成工具

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py db/check_data.py                 # 覆盖表 + 计数 + 样例（含 atorvastatin / 无源别名 / 严重碰撞）
& $py deploy/ci_checks.py --fast       # 18 秒全局基线（编译 / unittest / dist 完整性）
& $py lib/markets.py --check           # 市场注册表 vs DB source 表
& $py etl/provenance.py --status       # substance / brand_family 溯源覆盖率（只读）
& $py etl/drift_check.py               # 10 个来源的原始缓存漂移（只读扫描）
& $py db/q.py "SELECT * FROM coverage"
```

`db/check_data.py` 的输出分区：coverage / counts / top trade names / atorvastatin /
aliases without a verifiable source / US terms / confusable pairs / severe collisions。
比它更细的统计用 `db/q.py`，别写临时脚本另建连接。

## 2. 只读连接写法

```python
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "drugs.db"
db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
```

（`tests/trilingual/run_tests.py` 里有一模一样的写法。）

## 3. 常用口径（十个市场）

| 问题 | 查法 |
|---|---|
| 各国产品数 | `SELECT country, COUNT(*) FROM product GROUP BY country` |
| 各国强度覆盖率 | `SUM(strength IS NOT NULL) / COUNT(*)`，按 country 分组 |
| 成分 / 名称 / 别名规模 | `substance`、`product_name`、`alias_all`（按 confidence 分组） |
| 碰撞分级 | `SELECT level, COUNT(*) FROM collision GROUP BY level` |
| 数据截止日 | `SELECT * FROM source`（`data_as_of` / `data_as_of_note`） |
| 溯源覆盖 | `etl/provenance.py --status`（source_id / method / confidence / decided_at） |
| 某成分跨国分布 | 先按通用名 / 别名找 `substance_id`，再 join `product_component` → `product` 按 country 分组 |

口径提醒：

- 「查不到 ≠ 不存在」：覆盖不足是数据事实，报告要明说。
- 空白字段（MX 浓度约七成空缺、CN 商品名多数为空、HK 无规格）是源事实，不当 bug。
- 计数口径必须与 `db/check_data.py` / 站点 / README 一致；旧数字不能直接抄。
- 引用外部数据时附 URL 与许可；许可结论见 `docs/许可清单.md`、`docs/数据溯源与许可.md`。

## 4. 报告模板

写 `reports/YYYY-MM-DD-主题.md`（或沿用 `主题-YYYYMMDD.md`）：

```markdown
# 主题（日期）

## 结论
- 3–5 条，先说答案，带数字。

## 口径
- 数据库：data/drugs.db，只读；统计时间 / 源版本。
- SQL / 命令：（贴可复现的那几条）

## 数据
| 指标 | 数值 | 说明 |

## 缺口与风险
- 明确哪些是源限制、哪些是我们没做。

## 下一步
- 可执行项，带验收标准。
```

- 大改动前后各跑一次 `db/check_data.py`，把 before / after 贴进报告。
- 结论落到 `reports/` 或 `docs/`；跨会话交接靠工作区文件，不靠上下文。
- 当天审计结论要同步进 `docs/交接-YYYYMMDD.md`。

## 5. 红线

- 审计会话不写库、不跑 `run_all.py`、不跑 `deploy/publish.ps1`。
- 不在别人的入库 / 建站进行中改库或长时间占锁。
- 报告数字必须能复现；失败与缺口也要写。
