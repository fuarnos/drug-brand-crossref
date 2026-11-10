# 荷兰 CBG-MEB 药品信息库（GIP）再发布许可评估

日期：2026-11-11 ｜ 结论：🔴/🟡 **未获再发布许可，NL 不写库、不上线**（EU 区域层不受影响，可继续）
依据：`docs/欧盟抓取-20261111.md` §2.2 / §4 第 1 步；`AGENTS.md` §4「许可先行」

## 0. 结论先行

| 问题 | 答案 |
|---|---|
| GIP 数据文件能否再发布（整表进本站）？ | **不能，现在不能**。无任何授权声明，国家级数据目录把该数据集标为「 licentie onbekend 」（许可未知），而 `data.overheid.nl` 自己的许可口径页明写「 licentie onbekend = **geen hergebruik licentie**（无再使用许可），**Open Data? Nee**」 |
| 是否「明确禁止」？ | 不是。没有禁止条款，属「未授权」而非「禁止」→ 定级 🟡（待确认），不进 §3「明确不用」 |
| 影响 v0.11.0 吗？ | **不影响 EU 区域层**（EC Union Register = CC BY 4.0、EMA = 署名可再分发，均 ✅）。NL 成员国试点与 `nl` 语言**顺延**，等书面许可或等许可方给出明确开放许可 |
| 今天做了什么 | ① 许可登记更新（`docs/许可清单.md` §2.10 三行）② 跟进台账加行（`docs/跟进提醒.md`）③ `etl/markets/nl.py` 只做干跑（缓存 + 统计，**不写库**）④ 起草许可请求信 |

## 1. 证据链（2026-11-11 实测）

| # | 证据 | 内容 | 判定 |
|---|---|---|---|
| 1 | GIP 首页/数据文件页 | 页面只写「as a data file」可下载，**无许可、无使用条款、无版权声明** | 无授权 |
| 2 | `data.overheid.nl` 数据集条目 `87bf9724-971f-5bfc-82de-f2aef049bbd4`（原入口 404，经 FDS 国家目录镜像取到同一 DCAT 记录） | `dct:license = http://standaarden.overheid.nl/owms/terms/licentieonbekend`；`dct:accessRights = PUBLIC`；`dct:rightsHolder = College ter Beoordeling van Geneesmiddelen`；法定依据 `Artikel 53 Geneesmiddelenwet`；联系点 `Geneesmiddelgebruik@cbg-meb.nl` | **许可未知** |
| 3 | data.overheid.nl 许可口径页 [`/en/node/70`](https://data.overheid.nl/en/node/70) | 「 licentie onbekend 」定义为 **Geen hergebruik licentie**、**Open Data? Nee**；并建议「拿不准就选 CC0」 | 许可未知 **≠** 开放数据 |
| 4 | Rijksoverheid 开放数据条款 [`/opendata/voorwaarden`](https://www.rijksoverheid.nl/opendata/voorwaarden) | **rijksoverheid.nl 的**开放数据是 CC0——只覆盖该站数据集，**不覆盖 CBG-MEB 的 GIP** | 不能类推 |
| 5 | `cbg-meb.nl` 站内条款页 | `/disclaimer` → HTTP 404；未找到可引用的版权/使用条款页 | 无授权 |
| 6 | 法定依据 | 荷兰《Geneesmiddelenwet》第 53 条要求 CBG 公开药品注册信息——这是**公开义务**，不是**再发布许可** | 不构成授权 |

> 结论：荷兰「政府数据默认开放」的说法在这里**不成立**。GIP 的数据集登记自己就写着「许可未知」，国家目录的口径页又把「许可未知」排除在开放数据之外。按本站 §1 分级，这是 🟡（条件性/待确认），不是 ✅。

## 2. 本站处置（已执行 / 将执行）

1. **不写库**：`data/drugs.db` 不出现任何 `country='NL'` 行；今天只跑 `etl/markets/nl.py --dry-run`（读缓存、出统计），产物留在 `.tmp/`。
2. **不上线**：站点不加 NL 国家、不加 NL 名字页、不开 `nl` 界面语言（没有数据就开语言只会多一套空壳四语字典）。
3. **许可登记**：`docs/许可清单.md` §2.10 `cbg_meb_nl` 行改为「🟡 待确认（国家目录明标许可未知）」并写清证据；`docs/欧盟抓取-20261111.md` §2.2/§7 同步。
4. **跟进**：`docs/跟进提醒.md` 加一行，两个节点（11-25 首查、12-09 复审）；到期无答复则把 NL 从 v0.11.x 移到「长期待批」。
5. **请求信**：`docs/许可请求-CBG-MEB.md` 起草完成，**由人决定是否以本站名义发出**（涉及以谁的名义对外发文，属「人的原话」范畴，不自行发送）。
6. **EU 区域层照常推进**：CC BY 4.0 + EMA 署名，是本窗口唯一要写库的数据。

## 3. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/q.py "SELECT COUNT(*) FROM product WHERE country='NL'"        # 必须为 0
& $py etl/markets/nl.py --dry-run                                      # 只读缓存 + 统计
```
