# Phase B 批次 B1：21 条 CJK 主名 → 英文 INN（已写库）

> 2026-11-07 谷段，Lead 执行。依据 `data/sources/phaseb-merge-plan-20261107.csv`（task-6 计划）的 `rename_inn` 动作。
> **已写库**（提前备份 + 逆操作清单 + 全量校验）；**只改显示名，不合并任何身份**。

## 0. 结果

| 项 | 前 | 后 |
|---|---|---|
| substance 总数 | 12,649 | **12,649**（不变） |
| `name_lang='zh'`（CJK 主名） | 1,791 | **1,770（−21）** |
| `inn_en` 重复 | 0 | **0** |
| `quick_check` / FK | ok / 0 | **ok / 0** |
| product / product_component | 477,098 / 628,013 | **不变** |

- 备份：`data/backups/drugs-before-phaseb-rename-20261107.db`（419,799,040 B）
- 逆操作清单：`.tmp/phaseb-rename-manifest.json`（21 行旧 `inn_en`/`inn_zh`/`name_lang`）
- 三语回归：**72 例 69 通过**（与改前基线一致，无新增失败）；Top-5 **98.6%**、Top-1 **95.5%**；耗时 553.6s
- 单条抽查：`cli.py "贝美格"` 仍命中 CN 产品（成分显示 Bemegride）

## 1. 改了什么（21 条）

`甘羟铝→Aluminium Glycinate`、`磷酸铝→Aluminium Phosphate`、`吉法酯→Gefarnate`、`瑞巴派特→Rebamipide`、`羟甲烟胺→Nicotinyl Methylamide`、
`吲哚布芬→Indobufen`、`胰蛋白酶→Trypsin`、`长春胺→Vincamine`、`西尼地平→Cilnidipine`、`二硫化硒→Selenium Disulfide`、
`磺胺林→Sulfalene`、`磺胺对甲氧嘧啶→Sulphamethoxydiazine`、`普卢利沙星→Prulifloxacin`、`西他沙星→Sitafloxacin`、`司莫司汀→Semustine`、
`卡莫氟→Carmofur`、`依普黄酮→Ipriflavone`、`地佐辛→Dezocine`、`丙戊酰胺→Valpromide`、`妥洛特罗→Tulobuterol`、`贝美格→Bemegride`

- 每条：`inn_en` 改为英文 INN、`name_lang='en'`、**`inn_zh` 原样保留**（中文名不丢）、`substance_id` 不变、产品归属不变。
- 校验（执行前）：目标 id 全部存在、新名全部拉丁字母、与现有 `inn_en` **无冲突**（21/21 通过）。

## 2. 边界与已知限制

- **只是改名，不是重键**：`product_name` 的 `name_key`/`name_variant` 仍按旧中文名建键，所以「搜 Bemegride」目前仍是模糊命中（rebuild 后成分页显示英文名，检索主要仍走中文名）。要让英文 INN 也可搜，需要在 name 层补 `name_type=inn` 的英文键（下一窗口做，属 task-141 的延伸）。
- 28 条候选**没动**：盐/酯未落 `variant.salt/ester`，改名会抹平盐型身份 → 留 `candidate_only`。
- 12 条 `merge_duplicate` **没动**：合并需要单独窗口（产品/组件计数必须不变，计划里已带校验 SQL）。

## 3. 回滚

```powershell
# 方案一：整体还原
Copy-Item data\backups\drugs-before-phaseb-rename-20261107.db data\drugs.db -Force
# 方案二：按清单逆操作（不丢期间的其它改动）
#   读 .tmp/phaseb-rename-manifest.json，对每行 UPDATE substance SET inn_en=old, name_lang=old WHERE substance_id=...
```

## 4. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/check_data.py
& $py db/q.py "SELECT COUNT(*) FROM substance WHERE name_lang='zh'"   # 1770
& $py tests/trilingual/run_tests.py                                   # 72 例 69 通过
```

## 5. 下一步

1. **B2 合并 12 条**（单批、带前后计数校验；`manitol→mannitol` 330 产品是最大一条）。
2. **英文 INN 补 name 键**（让 rename 真正可搜）。
3. 28 条盐/酯先行落 `variant`，再决定是否改名。
