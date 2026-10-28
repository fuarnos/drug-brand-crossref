# ATC 类名 v2：Wikipedia 补 L2–L4 + 合并（人工 > Wikidata > Wikipedia）

> 日期：2026-10-28 ｜ 任务：`task-134` ｜ 依据：`reports/atc-class-names.md`（v1 Wikidata 覆盖 28.8%）与 `reports/atc-intuition-audit.md`。
> 交付：**`data/atc_class_names_v2.csv`（1,154 行）** + `etl/fetch_atc_class_names.py --v2`（可重跑）+ 本报告 + `.tmp/atc-names2/` 缓存/统计。
> **只写 etl/data/reports/.tmp**；未写 `data/drugs.db`、未改 `site/build.py`、未 git/发布。

---

## 0. 结论与目标达成

| 指标 | 结果 | 目标 | 判定 |
|---|---:|---:|---|
| 总类目 | 1,154（L1 14 / L2 93 / L3 249 / L4 798） | — | — |
| **有任一语言名** | **1,134 / 1,154（98.3%）** | — | — |
| L1 覆盖 | **14 / 14（100%）** | 100% | ✅ |
| L2 覆盖（任一语言） | **92 / 93（98.9%）** | 100% | ⚠️ 差 1（V02） |
| L1+L2 合计 | **106 / 107（99.1%）** | 100% | ⚠️ 唯一缺口 V02（见 §5） |
| **L3 覆盖** | **246 / 249（98.8%）** | ≥70% | ✅ |
| **L4 覆盖** | **782 / 798（98.0%）** | ≥50% | ✅ |
| en 覆盖 | 1,074 / 1,154（93.1%） | — | — |
| zh 覆盖 | 841 / 1,154（72.9%） | — | — |
| es 覆盖 | 441 / 1,154（38.2%） | — | — |
| zh-Hant 覆盖 | 841 / 1,154（72.9%，全部由 zh 或 Wikidata 派生） | — | — |

- **v1（Wikidata）→ v2 新增覆盖**：任一语言 332 → **1,134（+802）**；en 309 → **1,074**；zh 176 → **841**；es 164 → **441**；zh-Hant 176 → **841**。
- **仍缺 20 个**：`V02`（L2）；`A02D`、`V02D`、`V20A`（L3）；`A02DA`、`A02XA`、`A09AX`、`A10XX`、`C02CX`、`C03XW`、`H01BX`、`J07XX`、`N05CJ`、`R05XX`、`V02DC`、`V02DD`、`V02DE`、`V02DX`、`V04CW`、`V20AX`（L4）。这些行 `fallback_text = "ATC <code> · 类名待补充"`，build 应显示该文案（或现有「待校订」），**不瞎造名**。
- **V02 说明**：V02 在 WHO 人类 ATC 官方 L2 类目中未查到对应标准类（V 组常见为 V01/V03/V04/V06/V07/V08/V09/V10/V20）；DB 中有 V02 前缀的码（V02D/V02DC…）。**不为其编造类名**，作为 1 个 L1/L2 例外记录；若后续确认其为 ATCvet/历史码，可补来源后加入。

---

## 1. 来源与许可（必须保留署名）

| 来源 | 用途 | 许可 | 署名/义务 |
|---|---|---|---|
| **Wikipedia en / zh / es** | L2–L4 类名（页面标题/锚点/表格中只取类目名事实） | **CC BY-SA 4.0** | 需署名 + **相同方式共享**；逐行 `url_en/url_zh/url_es` 指向具体页面；报告/About 建议写「部分类名来自 Wikipedia（CC BY-SA 4.0）」 |
| **Wikidata**（v1） | 332 条 en/zh/es/zh-Hant 标签 | **CC0 1.0** | 无强制署名；保留 `url_*` 中的 Wikidata URL |
| **人工/编辑**（build.py 38 条 + 6 条 L2 补充） | L1 官方名、25 个常用 L2–L4 | 项目编辑/事实字段 | 无需外部署名；source=`editorial` |

**署名/许可文本（可直接用）**

> ATC class names are derived from Wikipedia (en/zh/es) under CC BY-SA 4.0; see each row's `url_en/url_zh/url_es` for the source page and its contributors. Some names are from Wikidata (CC0 1.0). Additional editorial names are maintained by this project (site/build.py). ATC codes/classification are based on WHO ATC/DDD; this site is not affiliated with WHO. The merged CSV (containing Wikipedia-derived text) must be redistributed under **CC BY-SA 4.0** (share-alike), even though Wikidata rows are CC0.

- **只取类目名事实**，不复制 Wikipedia 正文/段落；CSV 每语言都有 `source_*`、`url_*`、`license_*`（`CC0 1.0` / `CC BY-SA 4.0` / `editorial`）。
- 注意：**v2 CSV 不再是纯 CC0**；对外分发请遵守 CC BY-SA 4.0（署名 + 同许可）。内部 build 使用无需额外付费。

---

## 2. 合并规则（人工/编辑 > Wikidata > Wikipedia）

1. 每个 `code × lang` 依次取：
   - **人工/编辑**（build.py 的 `ATC_L1_I18N` / `ATC_CLASS_I18N`；L1 全 14 条、L2–L4 25 条）；
   - **Wikidata**（`data/atc_class_names.csv` v1 的 `name_*`）；
   - **Wikipedia**（en/zh/es 页面解析；L3/L4 从 L2 页面表格/标题取）；
   - 都缺 → 留空 + `fallback_text="ATC <code> · 类名待补充"`。
2. **zh-Hant**：人工 > Wikidata > Wikipedia zh 经 **OpenCC + 台湾术语表**转换（`source=wikipedia-zh-converted`，`notes` 标注待复核）；不从英文直接造中文。
3. **6 个 L2 编辑补充**（Wikipedia/Wikidata 均缺）：`A05 Bile and liver therapy`、`A12 Mineral supplements`、`A16 Other alimentary tract and metabolism products`、`B05 Blood substitutes and perfusion solutions`、`C01 Cardiac therapy`、`L03 Immunostimulants`（标准 ATC 名，source=editorial）。
4. 只补 **L2–L4**；L1 沿用人工官方 14 条（Wikipedia L1 概念名不可靠，见 v1 报告 §3）。
5. 冲突不自动覆盖：Wikipedia 与更高优先级来源不同时不采用 Wikipedia，记录到 `.tmp/atc-names2/conflicts.json`（352 条）。

**source 统计（CSV 实际行数）**

| lang | wikipedia | wikidata | editorial | 空 |
|---|---:|---:|---:|---:|
| en | 749 | 281 | 44 | 80 |
| zh | 635 | 168 | 38 | 313 |
| es | 250 | 153 | 38 | 713 |
| zh-Hant | 635（converted） | 168 | 38 | 313 |

---

## 3. 覆盖率（按层级 × 语言）

| level | 总数 | 任一语言 | en | zh | es | zh-Hant |
|---|---:|---:|---:|---:|---:|---:|
| L1 | 14 | 14（100%） | 14 | 14 | 14 | 14 |
| L2 | 93 | 92（98.9%） | 92 | 45 | 84 | 45 |
| L3 | 249 | 246（98.8%） | 240 | 197 | 218 | 197 |
| L4 | 798 | 782（98.0%） | 728 | 585 | 125 | 585 |
| 合计 | 1,154 | 1,134（98.3%） | 1,074 | 841 | 441 | 841 |

- en 侧已接近全覆盖（L1 100%、L2 98.9%、L3 96.4%、L4 91.2%）。
- zh 侧 L2 只有 45/93（zh Wikipedia L2 页覆盖 68/93；其余用 en 兜底，故「任一语言」L2 92/93）。
- **es 侧偏低（441）**：es Wikipedia 的 L1/L2 附录页表格里 L4 名称格式与 en/zh 不同，解析到 L4 仅 125/798；v1/Wikidata 补 153 后为 441。**目标按「任一语言/EN 主口径」达成**；es 需后续专门解析或人工补。
- zh-Hant 841 = zh 841（全部由 zh 转换/Wikidata 直取）；转换条目标 medium，需母语复核。

---

## 4. 冲突清单（Wikipedia vs 更高优先级）

- **352 条**：Wikipedia 类名与人工/Wikidata 名称不同（优先级决定不采用 Wikipedia）；完整见 `.tmp/atc-names2/conflicts.json`。
- 典型样例（`higher` 为人工/Wikidata，`wikipedia` 为未采用）：
  - `A02 zh`：人工「酸相关疾病用药」 vs Wikipedia「治疗与胃酸分泌相关疾病的药物」；
  - `A08 es`：人工「Preparados antiobesidad」 vs Wikipedia「Preparados contra la obesidad…」；
  - `B01 zh`：人工「抗血栓药」 vs Wikipedia「Antithrombotic agents」（en 混入）；
  - `C02`、`C03`、`C09`、`H02` 等 es/zh 措辞差异；
  - `B02`：Wikidata「antihemorrhagic」 vs Wikipedia「Antihemorrhagics」（单复数，保留 Wikidata）。
- 结论：冲突不自动改；**人工覆盖优先**，后续可人工挑选更好的措辞。

---

## 5. 接入 build 建议

1. **读取 `data/atc_class_names_v2.csv`** 替换/补充现有 `ATC_CLASS_I18N`/`ATC_L1_I18N`（数据驱动；build.py 由后续任务改，本次未动）。
2. 优先级：**manual/editorial > Wikidata > Wikipedia**；CSV 已按此合并，build 只需按 `name_*` 取值 + 按 `source_*` 打标注。
3. 缺名行：显示 `fallback_text`（「ATC <code> · 类名待补充」）或现有「类别名待校订」，不要显示空标题/英文占位。
4. 署名/许可：ATC 页/About 增加「类名来源：Wikipedia（CC BY-SA 4.0，逐页 URL）+ Wikidata（CC0）+ 本站编辑；ATC 码以 WHO ATC/DDD 为准」；**CSV 再分发需 CC BY-SA 4.0**。
5. 语言回退：某语言缺名时回退到 en 原名/编码，不要用英文冒充中文/西语（沿用 v0.8.2 的本地化修复原则）。
6. 版本：CSV 由 `etl/fetch_atc_class_names.py --v2` 生成；建议随 build 页数变化重跑；`url_*` 可按季度抽检 Wikipedia 变更（CC BY-SA 要求保留署名）。
7. 仍缺 20 个 code 的类名（§0）：保留 fallback；V02 需确认是否标准码后再补。

---

## 6. 剩余缺口与风险

| # | 项 | 说明/处理 |
|---|---|---|
| R1 | 20 个 code 无名字 | V02（L2）、A02D/V02D/V20A（L3）、16 个 L4；fallback_text 已生成；不建议编造，等官方/人工补 |
| R2 | L1/L2 目标 100% 差 1 | V02 疑似非 WHO 标准码；其余 106/107；如确认 V02 无效可从目标分母移除并记「1 例外」 |
| R3 | es 覆盖 38.2% | es Wikipedia L4 解析/覆盖有限；en/zh/any 目标已达成；后续可专门解析 es 附录表格或人工补 |
| R4 | Wikipedia 许可 | CC BY-SA 4.0（署名+ShareAlike）；v2 CSV 对外分发必须 CC BY-SA 4.0，不可只标 CC0 |
| R5 | 类名质量 | Wikipedia 是社区编辑，名称可能是概念名/措辞不一；人工/Wikidata 优先；冲突 352 条已列出 |
| R6 | zh-Hant | 全部由 zh 转换（不计 Wikipedia 直接繁体页），需母语复核；`notes` 已标 |
| R7 | 数据更新 | Wikipedia 页面会变；重跑脚本可刷新，保留 URL 以便复核 |
| R8 | 不涉及 DB/build.py | 本任务只产数据/报告；接入由后续 build 任务完成 |

---

## 7. 产物 / 复现 / 证据

| 路径 | 内容 |
|---|---|
| `data/atc_class_names_v2.csv` | **1,154 行 / 约 415 KB**；code/level/四语名/source/url/license/fallback/notes |
| `etl/fetch_atc_class_names.py` | v1 逻辑 + **`--v2`**：Wikipedia en/zh/es 抓取/解析、合并、OpenCC zh-Hant、冲突/统计；缓存；只读 DB |
| `.tmp/atc-names2/wiki_{en,zh,es}.json` | Wikipedia L1/L2 页面 wikitext 缓存（107 页/语言） |
| `.tmp/atc-names2/build_stats.json` | 覆盖/层级/缺失/冲突统计 |
| `.tmp/atc-names2/conflicts.json` | 352 条 Wikipedia vs 高优先级冲突 |
| `.tmp/atc-names2/README.md` | 证据索引 |
| `data/atc_class_names.csv`、`reports/atc-class-names.md` | v1（Wikidata 基线，未删除，便于对比/回滚） |

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/fetch_atc_class_names.py --v2              # 使用缓存生成 v2
& $py etl/fetch_atc_class_names.py --v2 --refresh    # 重新抓 Wikipedia/Wikidata
```

**关键引用**
- English Wikipedia：`https://en.wikipedia.org/wiki/ATC_code_A02`（L2 页含 L3/L4 表格）
- 中文 Wikipedia：`https://zh.wikipedia.org/wiki/ATC代码_(A02)`
- 西语 Wikipedia：`https://es.wikipedia.org/wiki/Anexo:Código_ATC_A02`
- v1 Wikidata 基线：`data/atc_class_names.csv` / `reports/atc-class-names.md`
- ATC 码/类目权威：WHO ATC/DDD（页面保留引用；本任务不复制 WHO 全表）
