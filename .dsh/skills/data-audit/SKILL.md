---
name: data-audit
description: 数据体检、覆盖率统计、回答「某国覆盖多少 / 缺什么」或写审计报告时用：只读查库、跑 check_data、按模板落 reports/。
whenToUse: 任务涉及数据质量、覆盖率、条数对账、字段缺失、碰撞分级统计、写数据报告或给发布决策做依据时。
---

# 数据体检与报告（data-audit）

原则：**审计只读**。不改库、不跑 ingest、不建站；所有数字要能被一条命令复现。

## 1. 现成工具

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py db/check_data.py                 # 覆盖表 + 各类计数 + top trade names
& $py db/q.py "SELECT * FROM coverage"
& $py db/q.py "SELECT country, COUNT(*) FROM product GROUP BY country ORDER BY 2 DESC"
```

`db/check_data.py` 会打印 `coverage`、products / components / substances / variants / name_keys /
names / collisions(severe|warning) / nickname / drug_term / aliases(按 confidence) / confusable_pairs。
比它更细的统计用 `db/q.py`，别在脚本里临时建库连接。

## 2. 只读连接写法

```python
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "drugs.db"
db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
```

（`tests/trilingual/run_tests.py` 里有一模一样的写法。）

## 3. 常用口径（按需组合）

| 问题 | 查法 |
|---|---|
| 各国产品数 | `SELECT country, COUNT(*) FROM product GROUP BY country` |
| 各国强度覆盖率 | `SUM(strength IS NOT NULL) / COUNT(*)`，按 country 分组 |
| 成分 / 名字键规模 | `SELECT COUNT(*) FROM substance` / `FROM name_key` |
| 碰撞分级 | `SELECT level, COUNT(*) FROM collision GROUP BY level` |
| 别名来源 | `SELECT confidence, COUNT(*) FROM alias_all GROUP BY confidence` |
| 数据截止日 | `SELECT * FROM source`（看 `data_as_of` / `data_as_of_note`） |
| 某成分跨国分布 | 先按通用名/别名找到 `substance_id`，再 join `product_component` → `product` 按 country 分组 |

注意口径：
- 「查不到 ≠ 不存在」——覆盖不足是数据事实，报告里要明说，不能写成「没有这个药」。
- 空白字段（如 MX 浓度 71% 空缺、CN 商品名多数为空）是源数据的事实，不要当 bug 修。
- 计数类报告在 `db/check_data.py` 和站点之间必须一致（README / About / CHANGELOG 同口径）。

## 4. 报告模板

写 `reports/YYYY-MM-DD-主题.md`（现有文件命名两种都有，跟随同类文件）：

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
- 结论要落到 `reports/` 或 `docs/`，不要只留在对话里——跨会话靠工作区文件交接。

## 5. 红线

- 审计会话不写库、不跑 `run_all.py`、不跑 `publish.ps1`。
- 不在别人的入库 / 建站进行中改库或长时间占锁。
- 报告里的数字必须能复现；引用外部数据时附 URL 和许可。
