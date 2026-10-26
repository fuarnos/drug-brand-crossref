# 美国药物俗称 / 常见民间称呼 / 易混淆药物：入库结果

日期：2026-10-26 · 数据库：`data/drugs.db`

## 一句话

已经入库。美国街头叫法、类别俗称、常见民间叫法和 FDA 官方易混淆药对都进了库，
检索、成分页、`/confused.html` 三个入口都能用。

## 数量

| 层 | 表 | 条数 | 说明 |
|---|---|---|---|
| 中文旧名 / 网络俗称 | `nickname` | 57 | 原有，不变 |
| 美国街头 / 类别 / 民间叫法 | `drug_term` | 331 | 新增 |
| 统一别名检索入口 | `alias_all`（视图） | 388 | 57 + 331 |
| FDA tall-man 易混淆药对 | `confusable_pair` | 22 对 / 44 个方向 | 新增 |

### `drug_term` 按来源

| 来源 | 条数 | 许可 |
|---|---:|---|
| NIDA — Drugs A to Z | 247 | US Government work（public domain） |
| DEA — Slang Terms and Code Words (2018) | 64 | Public Domain Mark 1.0 |
| MedlinePlus (NLM) — 民间叫法 | 20 | US Government work（public domain） |
| **合计** | **331** | |

### `drug_term` 按类型

| `term_type` | 条数 | 例子 | 检索行为 |
|---|---:|---|---|
| `street` | 245 | molly、bars、lean、oxy、dillies | 指向具体成分；无上市产品时只说明成分 |
| `class` | 66 | downers、uppers、benzos、spice、bath salts | 类别叫法，列出举例成分，不冒充具体药 |
| `folk` | 20 | water pill、blood thinner、the pill、statin | 民间类别词，提示「名字含该词的商品不一定是该类别」 |

其中 `street` 有 168 行能落到具体 `substance_id`，163 行是本库没有上市产品的
管制物质或类别词（MDMA、LSD、海洛因、大麻等）。

## 几个可以直接查的例子

| 输入 | 返回 |
|---|---|
| `molly` | MDMA（摇头丸）；本库没有该成分的上市产品记录 |
| `lean` | 可待因 + 异丙嗪（复方糖浆）；提示可能指两个成分 |
| `bars` | 阿普唑仑；列各国商品名 |
| `water pill` | 利尿剂类别；举呋塞米、氢氯噻嗪、螺内酯；并警告名字含 water pill 的商品不一定是利尿剂 |
| `hydralazine` | 正常结果 + 「易与 Hydroxyzine 混淆（hydrALAZINE ↔ hydrOXYzine）」 |
| `prednisone` | 正常结果 + 「易与 Prednisolone 混淆」 |

## 授权边界（重要）

- **收了**：NIDA、DEA、MedlinePlus、FDA 的官方内容；都是美国政府作品或公共领域标记。
- **没收**：ISMP/ECRI《List of Confused Drug Names》。该清单有版权，不能整表复制；
  站上明确写「这是 FDA 官方 tall-man 名单，不是完整 LASA 清单」。
- **没收 DEA 报告里的**：度量、武器、地点等与药品身份无关的代码词。
- **没收 NIDA 类别条目里没有具体成分的**：保留类别词，但不硬塞给某一个成分。

## 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/ingest_us_terms.py          # NIDA + DEA + MedlinePlus → drug_term
& $py etl/ingest_fda_confusable.py   # FDA tall-man → confusable_pair
& $py site/build.py                  # 重建静态站
```

快照在 `data/sources/`（已进仓库，不受 `data/raw/` 忽略规则影响）。

## 验证

- `python -m unittest discover -s etl -t etl` → 13 项通过
- `python -m unittest discover -s lib -t lib` → 19 项通过
- `python site/build.py` → 10,843 张成分页 / 13,632 张名字页 / 22 对药对
- 客户端检索用 Node 夹具跑过：`molly`、`lean`、`bars`、`water pill`、`hydralazine`、`Lipitor`
