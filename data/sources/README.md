# 美国俗称 / 易混淆药对快照

这三个文件是 `etl/ingest_us_terms.py` 与 `etl/ingest_fda_confusable.py` 的离线输入。
放 `data/sources/` 而不是 `data/raw/`，因为 `data/raw/` 被 `.gitignore` 排除（那里是
几百 MB 的原始缓存），而这三个文件是小型、可复现的策展快照，应该跟代码一起进仓库。

| 文件 | 来源 | 抓取/整理 | 许可 |
|---|---|---|---|
| `nida-drugs-a-to-z.md` | [NIDA — Drugs A to Z](https://nida.nih.gov/research-topics/drugs-a-to-z) | 2026-10-26，正文文本渲染 | US Government work（public domain） |
| `dea-slang-2018.txt` | [DEA — Slang Terms and Code Words (2018)](https://archive.org/details/dea-drug-slang-terms-and-code-words-july2018) | 2026-10-26，Internet Archive DjVu 文本 | Public Domain Mark 1.0 |
| `fda-tall-man-pairs.csv` | [FDA — Name Differentiation Project](https://www.fda.gov/drugs/medication-errors-related-cder-regulated-drug-products/fda-name-differentiation-project) | 2026-10-26，按官方表格逐行转录；页面标注 content current as of 2026-06-12 | US Government work（public domain） |

## 没有收进来的

- **ISMP/ECRI《List of Confused Drug Names》**：有版权，未整表复制。站上只收 FDA 官方
  tall-man 名单，并明确标注「不是完整 LASA 清单」。
- **DEA 报告里的度量、武器、地点等代码词**：与药品身份无关，不取。
- **NIDA 的类别条目里没有具体成分的例子**（如合成大麻素、合成卡西酮）：保留类别词，
  但不硬塞给某个成分。

## 重跑

```powershell
& $py etl/ingest_us_terms.py
& $py etl/ingest_fda_confusable.py
& $py site/build.py
```

`ingest_us_terms.py --dry-run --all` 可以先看全部候选行，不会写库。
