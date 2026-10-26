# 药物社区叫法 / 各国街头叫法 / 易混淆药物：入库结果

日期：2026-10-26 · 数据库：`data/drugs.db`

## 一句话

已经入库。美国街头叫法、各国社区叫法、类别俗称、常见民间叫法和 FDA 官方易混淆药对
都进了库；检索、成分页、`/confused.html` 三个入口都能用。

## 数量

| 层 | 表 | 条数 | 说明 |
|---|---|---|---|
| 中文旧名 / 网络俗称 | `nickname` | 57 | 原有，不变 |
| 美国 + 各国街头 / 类别 / 民间叫法 | `drug_term` | 365 | 331 美国 + 34 社区/各国 |
| 统一别名检索入口 | `alias_all`（视图） | 422 | 57 + 365 |
| FDA tall-man 易混淆药对 | `confusable_pair` | 22 对 / 44 个方向 | 单名条目 hydromorphone / mitoxantrone 无配对不对，未列入 |

### `drug_term` 按来源

| 来源 | 条数 | 许可 |
|---|---:|---|
| NIDA — Drugs A to Z | 247 | US Government work（public domain） |
| DEA — Slang Terms and Code Words (2018) | 64 | Public Domain Mark 1.0 |
| MedlinePlus (NLM) — 民间叫法 | 20 | US Government work（public domain） |
| 中国社区 / 消费健康文章（小红书、知乎、丁香园、科普中国等） | 13 | 用户生成内容；只存叫法 + 链接，不转载正文 |
| Talk to FRANK（英国） | 12 | Crown copyright；短事实叫法 + 署名 |
| Alcohol and Drug Foundation（澳洲） | 5 | © ADF；短事实叫法 + 署名 |
| PNSD（西班牙） | 4 | 西班牙政府公开文件；短事实叫法 + 署名 |
| **合计** | **365** | |

### `drug_term` 按类型

| `term_type` | 条数 | 例子 | 检索行为 |
|---|---:|---|---|
| `street` | 266 | molly、bars、lean、oxy、Charlie、Skag | 指向具体成分；无上市产品时只说明成分 |
| `class` | 66 | downers、uppers、benzos、spice、bath salts | 类别叫法，列出举例成分，不冒充具体药 |
| `folk` | 33 | water pill、闭口神器、聪明药、P药 | 民间/功效叫法，提示「名字含该词的商品不一定是该类别」 |

其中 `street` 有 175 行能落到具体 `substance_id`，177 行是本库没有上市产品的
管制物质或类别词（MDMA、LSD、海洛因、大麻等）。

### 按国家

| country | 条数 | 说明 |
|---|---:|---|
| US | 331 | NIDA / DEA / MedlinePlus |
| CN | 13 | 闭口神器、祛痘神药、聪明药、P药… |
| GB | 12 | FRANK 的 Also called（Charlie、Draw、Brown…） |
| AU | 5 | ADF 的 Other names（Hammer、The Dragon…） |
| ES | 4 | PNSD 的俗称（Nieve、Farlopa、Perico…） |

## 几个可以直接查的例子

| 输入 | 返回 |
|---|---|
| `molly` | MDMA（摇头丸）；本库没有该成分的上市产品记录 |
| `lean` | 可待因 + 异丙嗪（复方糖浆）；提示可能指两个成分 |
| `bars` | 阿普唑仑；列各国商品名 |
| `闭口神器` | 阿达帕林；社区叫法，标 URL |
| `聪明药` | 哌甲酯 / 莫达非尼；处方兴奋剂，提示风险 |
| `Charlie` | 可卡因；英国 FRANK 叫法 |
| `Brown` | 海洛因；英国 FRANK 叫法，本库无上市产品 |
| `Hammer` | 海洛因；澳洲 ADF 叫法 |
| `water pill` | 利尿剂类别；举呋塞米、氢氯噻嗪、螺内酯；并警告名字含 water pill 的商品不一定是利尿剂 |
| `hydralazine` | 正常结果 + 「易与 Hydroxyzine 混淆（hydrALAZINE ↔ hydrOXYzine）」 |
| `prednisone` | 正常结果 + 「易与 Prednisolone 混淆」 |

## 来源审计

422 条别名全部有 `source` 字段，但「有字段」不等于「已证实」。按 `confidence` 分：

| 级别 | 条数 | 含义 |
|---|---:|---|
| `documented` | 364 | 有具体官方/文献/药典/商品名出处 |
| `community` | 57 | 社区/民间/旧名，有链接或来源类型，但不冒充已证实 |
| `user` | 1 | 用户提供，只有线索 |

`community` 的 57 条按来源分：

| 来源 | 条数 |
|---|---:|
| 中文旧名 / 网络俗称（只有来源类型） | 23 |
| 中国社区 / 消费健康文章（逐条 URL） | 13 |
| Talk to FRANK（英国，逐条 URL） | 12 |
| Alcohol and Drug Foundation（澳洲，逐条 URL） | 5 |
| PNSD（西班牙，逐条 URL） | 4 |

`user` 是 `两只青蛙`（用户提供，本站缘起）。
**决策：社区叫法保留检索，不移到 pending、不删除。** 公开页对 `community` 标「社区叫法」，
对 `user` 标「用户提供（未证实）」，每条都显示 source；找到独立出处后才升为 `documented`。
没有来源线索的不新增；审核只核实出处，不能代替出处。

## 授权边界（重要）

- **收了**：NIDA、DEA、MedlinePlus、FDA 的官方内容；都是美国政府作品或公共领域标记。
- **没收**：ISMP/ECRI《List of Confused Drug Names》。该清单有版权，不能整表复制；
  站上明确写「这是 FDA 官方 tall-man 名单，不是完整 LASA 清单」。
- **没收 DEA 报告里的**：度量、武器、地点等与药品身份无关的代码词。
- **没收 NIDA 类别条目里没有具体成分的**：保留类别词，但不硬塞给某一个成分。

## 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/ingest_us_terms.py           # NIDA + DEA + MedlinePlus → drug_term
& $py etl/ingest_community_terms.py    # CN/GB/AU/ES 社区叫法 → drug_term
& $py etl/ingest_fda_confusable.py     # FDA tall-man → confusable_pair
& $py site/build.py                   # 重建静态站
```

快照在 `data/sources/`（已进仓库，不受 `data/raw/` 忽略规则影响）。

## 验证

- `python -m unittest discover -s etl -t etl` → 25 项通过
- `python -m unittest discover -s lib -t lib` → 19 项通过
- `python site/build.py` → 建站成功（成分页 / 名字页 / 22 对药对）
- 客户端检索用 Node 夹具跑过：`molly`、`lean`、`bars`、`闭口神器`、`聪明药`、`Charlie`、`Brown`、`hydralazine`
