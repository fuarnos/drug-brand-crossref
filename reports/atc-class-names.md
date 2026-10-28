# ATC 类名数据（Wikidata CC0，四语）— task-130

> 日期：2026-10-28 ｜ 任务：`task-130` ｜ 依据：`reports/atc-intuition-audit.md`
> 交付：`data/atc_class_names.csv`（1,154 行，65 KB）+ `etl/fetch_atc_class_names.py`（可重跑）+ 本报告 + `.tmp/atc-names/` 缓存/统计。
> **只写 etl/data/reports/.tmp**；未写 `data/drugs.db`、未改 `site/build.py`、未 git/发布。
> 许可：Wikidata 数据 **CC0 1.0**；每行保留 item URL；CC0 不要求署名，站点仍建议在 ATC 页保留「WHO ATC/DDD 引用 + 类名来源 Wikidata」说明。

---

## 0. 结论速览

| 项 | 结果 |
|---|---|
| 目标 | 1,154 个 ATC L1–L4 类目页（L1 14 / L2 93 / L3 249 / L4 798） |
| Wikidata 可用类目 item | **356 个 item，覆盖 344 个目标 code**（SPARQL：P267 长度 1/3/4/5；原始 380 item 含 36 个未命中目标 code） |
| 最终拿到至少 1 个名字 | **332 / 1,154（28.8%）** |
| 语言覆盖 | **en 309（26.8%）**、**zh 176（15.3%）**、**es 164（14.2%）**、**zh-Hant 176（15.3%）** |
| 按层级（any/en/zh/es/zh-Hant） | L1 8/8/1/7/1（共 14）；L2 80/80/6/3/6（共 93）；L3 77/76/54/48/54（共 249）；L4 167/145/115/106/115（共 798） |
| confidence | **high 73 / medium 236 / none 845**（none = 无 Wikidata 数据，names 留空；build 回退 ATC 码 + 现有「待校订」提示） |
| 与 build.py 手写 38 条对比 | 28 条 Wikidata 有名字；**10 条缺失**（L1 G/H/J/L/S/V、C10、C07A、C07AB、C10AA）；**37 条冲突 / 18 条同义**（详见 §3） |
| 关键质量结论 | Wikidata 的 L1 标签是「概念名」（gastrointestinal agent…），**不是 WHO 官方类目名**（Alimentary tract and metabolism…）→ L1 必须保留手写名；L2 官方名可从 item 描述提取（high）；L3/L4 主要是概念标签，部分语义偏差；**不得把 DB `atc_name`（46.6% 是药名）当类名** |
| 建议接入 | **手写 38 条优先**（人工覆盖）→ Wikidata 官方描述名 → Wikidata 概念名 → 留空/ATC 码；L1 全手写；L2 手写+Wikidata；L3/L4 用 Wikidata 补，common L3/L4（C10AA/C07AB/C07A/C10 等）手写；zh-Hant 转换条目标 medium、待母语复核 |

---

## 1. 数据与方法

### 1.1 来源/许可

- **Wikidata，CC0 1.0**；入口 `https://www.wikidata.org/`；属性 **P267 = ATC code**。
- 抓取两类 item：① P267 值长度 1/3/4/5 的「类目 item」（SPARQL，356 个 item；344 个命中目标 code）；② 同一 item 的四语标签（`wbgetentities`：`en/zh/zh-hans/zh-hant/zh-tw/zh-hk/es`）+ 英文描述 + P31。
- 每个 code 选**最像类目**的 item：优先英文描述中的
  `therapeutic subgroup of the Anatomical Therapeutic Chemical Classification System: <名称>`（视为官方类名，`quality=official`）；
  其次非「ATC code X」的概念标签；**排除与 `substance.inn_en` 相同的标签（禁止把药名当类名；CSV 最终 0 条药名）**。
- 四语：同一选中 item 的标签；**zh-Hant** 优先 Wikidata `zh-hant/zh-tw/zh-hk`，缺失时用 **OpenCC 词典 + 台湾药事术语表**（`.tmp/zh-hant/` 缓存，简→繁）转换并标 `notes`；不自动从英文翻译中文。
- 版本：脚本 `etl/fetch_atc_class_names.py --refresh` 可重抓；缓存 `.tmp/atc-names/wd_class_items_raw.json`、`wd_entities.json`；CSV 生成时间见 `.tmp/atc-names/build_stats.json`。

### 1.2 CSV 字段（`data/atc_class_names.csv`，UTF-8 BOM）

`code, level, name_en, name_zh, name_es, name_zh_hant, source_url, license, confidence, wikidata_id, notes`

- `source_url` = 选中 Wikidata item URL（`https://www.wikidata.org/wiki/Q…`）；`license=CC0`；无数据的行 names/URL/license 留空、confidence=none。
- `confidence`：high = 官方描述类名或官方域内标签；medium = 概念标签/由 zh 转换的 zh-Hant；none = 无数据。
- `notes`：zh 标签原为繁体已转简体（70 条）、zh-Hant 由 zh 经 OpenCC+TW 术语转换（54 条，待复核）等。

### 1.3 示例（CSV 摘录）

| code | en | zh | es | zh-Hant | confidence |
|---|---|---|---|---|---|
| A02 | Drugs for acid related disorders | — | — | — | high |
| C07 | Beta blocking agents | — | — | — | high |
| A10BA | biguanide | 双胍类 | biguanida | 雙胍類 | medium |
| A08 | anti-obesity medication | 抗肥胖药物 | — | 抗肥胖藥物 | medium |
| A10 | anti-diabetic medication | 抗糖尿病药 | antidiabético | 抗糖尿病藥 | medium |
| R06 | Antihistamines for systemic use | — | — | — | high |
| C10AA | — | — | — | — | none（手写表有，见 §3） |

> 说明：Wikidata 的 L2 官方 item 一般有英文描述类名，但大多**没有 zh/es 标签**；因此 en 覆盖 309 > zh 176 > es 164。L1 的 item 是概念条目（如 A=gastrointestinal agent），四语常只有 en/es，且**语义比 WHO 官方 L1 名更窄/更泛**。

---

## 2. 覆盖统计（1,154 类）

| level | 总数 | any 名字 | en | zh | es | zh-Hant | 无数据 |
|---|---:|---:|---:|---:|---:|---:|---:|
| L1 | 14 | 8 | 8 | 1 | 7 | 1 | 6 |
| L2 | 93 | 80 | 80 | 6 | 3 | 6 | 13 |
| L3 | 249 | 77 | 76 | 54 | 48 | 54 | 172 |
| L4 | 798 | 167 | 145 | 115 | 106 | 115 | 631 |
| **合计** | **1,154** | **332（28.8%）** | **309（26.8%）** | **176（15.3%）** | **164（14.2%）** | **176（15.3%）** | **845（73.2%）** |

- **L1 8/14**：缺 G/H/J/L/S/V 六个大类（手写表已有，见 §3）；L1 Wikidata 概念名语义不统一，**不建议直接替换手写名**。
- **L2 80/93**：en 覆盖较好；zh/es 只有 6/3（官方 item 多数没中文/西语标签）；缺口 13 个可由手写 C10 等补。
- **L3/L4**：zh 覆盖（54/115）高于 L2，因为部分概念 item 有中文标签；但整体仍 73% 无数据；L4 798 中 631 无任何名字，只能回退 ATC 码（现有「待校订」提示）。
- confidence：high 73 / medium 236 / none 845；CC0 行 332（有名字即有来源 URL）。

---

## 3. 与 build.py 手写类名对比（缺失/冲突）

现状：`ATC_L1_I18N` 14 条（L1）+ `ATC_CLASS_I18N` 25 条（L2–L4）；与 14 条 L1 合并去重后 **38 个唯一 code**，为人工/AI 编辑名。对比结果：

| 指标 | 值 |
|---|---:|
| 手写 code 数 | **38**（L1 14 + L2–L4 25，含 1 个重复 code） |
| Wikidata 有对应名字 | **28** |
| 同义（归一化相同） | **18** |
| 冲突（文字/语义不同） | **37**（按语言计） |
| 缺失（Wikidata 无名字） | **10** |

### 3.1 缺失的 10 条（Wikidata 没有名字 → 必须保留手写）

`G`（Genito-urinary system and sex hormones）、`H`（Systemic hormonal preparations）、`J`（Antiinfectives for systemic use）、`L`（Antineoplastic and immunomodulating agents）、`S`（Sensory organs）、`V`（Various）；`C10`（Lipid modifying agents）、`C07A`（Beta blocking agents）、`C07AB`（Selective beta-1 blocking agents）、`C10AA`（HMG-CoA reductase inhibitors (statins)）。

> 其中 **C10AA / C07AB / C07A / C10** 都是常用类目，说明「Wikidata 补名」不能替代手写表；手写表必须保留为 override。

### 3.2 冲突 37 条（完整清单见 `.tmp/atc-names/manual_compare.json`）

**A. L1 概念名 ≠ WHO 官方类目名（12 条，优先保留手写）**
`A` Alimentary tract and metabolism → gastrointestinal agent；`B` Blood and blood forming organs → hematologic agent；`C` Cardiovascular system → cardiovascular agent；`D` Dermatologicals → dermatologic drug；`M` Musculo-skeletal system → musculoskeletal drugs；`N` Nervous system → central nervous system agent；`P` Antiparasitic products → antiparasitic；`R` Respiratory system → respiratory system agent（另 es 7 条同型）。

**B. 单复数/同义改述（不影响理解，可保留手写）**
A08 `Antiobesity preparations` vs `anti-obesity medication`；A10 `Drugs used in diabetes` vs `anti-diabetic medication`；A10BA `Biguanides` vs `biguanide`；B01 `Antithrombotic agents` vs `antithrombotic`；B01AA `Vitamin K antagonists` vs `Vitamin K antagonist`；N06A `Antidepressants` vs `antidepressant`；N02BE `Anilidas` vs `anilida` 等。

**C. 语义偏差（需人工拍板，不宜直接采用 Wikidata）**
- `B01AA` zh-Hant：手写「維生素 K 拮抗劑」vs Wikidata「豆香素抗凝血劑」（后者是 coumarin 子类，窄/可能错）；
- `B01` es：手写「Agentes antitrombóticos」vs Wikidata「anticoagulante」（anticoagulant 是 antithrombotic 的子集）；
- `N02BE` zh：手写「苯胺类」vs Wikidata「酰替苯胺」（anisidide 是子类，语义偏差）；
- `P` zh/zh-Hant：手写「抗寄生虫药/抗寄生蟲藥」vs Wikidata「抗寄生物药」（用词差异）；
- `A08`/`A10` 的 zh/zh-Hant：手写「减肥/抗肥胖药」「糖尿病用药」vs Wikidata「抗肥胖药物」「抗糖尿病药」（可接受但风格不同）。

> 结论：**手写表（人工覆盖）优先**，Wikidata 只补手写缺失的类目（尤其 L3/L4），冲突项不自动覆盖。

---

## 4. 禁止把药名/占位当类名

| 检查 | 结果 |
|---|---|
| CSV 中类名与 `substance.inn_en` 相同的条目 | **0**（构建时显式排除；Wikidata 药名 item 不进入类目名） |
| DB `substance.atc_name` 误用风险 | 有 ATC 的 6,021 条中 **59.1% 为空**；非空 2,462 条中 **1,147（46.6%）等于药名本身**、185（7.5%）西语描述；**禁止当类名/搜索词**（详见 `reports/atc-intuition-audit.md` §1.2） |
| DB `drug_class` | 12,649 条 **100% 占位/空**；`site/build.py` 0 处引用；**禁止依赖** |
| 本次 CSV class 名来源 | 仅 Wikidata item 的英文描述（官方类名）或概念标签；无 DB `atc_name`/`drug_class` 参与 |

---

## 5. 接入 build 建议（人工覆盖优先）

1. **数据驱动替换手写表**：build.py 读取 `data/atc_class_names.csv`（1,154 code → 四语名）；现有 `ATC_L1_I18N`/`ATC_CLASS_I18N` 保留为 **manual override**，优先级最高。建议顺序：
   ```
   manual_override(code, lang) > wikidata_official(code, lang)
   > wikidata_concept(code, lang) > fallback(code / 「待校订」)
   ```
2. **L1 全部用手写 14 条**（Wikidata 概念名不可直接当官方类目名）；L2 手写 + Wikidata 英文补缺；**L3/L4 优先用 Wikidata 补**（当前 73% 无数据，补 332 已是净增）；常用 L3/L4（C10AA、C07AB、C07A、C10 等）保留手写。
3. **四语回退**：当前 zh/es/zh-Hant 覆盖明显低于 en（176/164/176 vs 309）——缺翻译时**不要用英文顶替中文**（v0.8.2 已修中文界面英文残留）；继续回退「ATC 码 + 待校订」或保留手写人工名。
4. **zh-Hant**：直接 Wikidata 繁体标签 122 条 + 由 zh 转换 54 条（`notes` 标记）；转换条目标 medium，上线前做一轮台湾用词复核（OpenCC TW_TERMS 已应用；「抗凝血劑」「雙胍類」等符合台湾常用）。
5. **不要用 DB `atc_name`/`drug_class` 作为 fallback**；atc_name 是药名/西语描述，drug_class 全占位。
6. **许可/署名**：CC0 无需署名；页面建议保留「类名来源：Wikidata（CC0），ATC 码以 WHO ATC/DDD 为准」一句；source_url 已在 CSV 每行保留，便于追溯/更新。
7. **版本/更新**：CSV 由 `etl/fetch_atc_class_names.py` 生成；Wikidata 不定期更新，建议每季度 `--refresh` + 与 `ATC_CLASS_I18N` 重跑对比；build 只读 CSV，不联网。
8. **优先补齐顺序**：L1（手写已全）→ L2（手写/缺 13）→ 常用 L3/L4（按访问/搜索量，先 C10AA、C07AB、C07A、C10 等）→ 其余 L3/L4（可用其他 CC0 源或人工）。

---

## 6. 限制与风险

1. **Wikidata 不是官方 ATC 发布渠道**：类目 item 覆盖 344/1,154（29.8%），且很多只有英文描述/概念标签；不能宣称「完整 ATC 类名」。
2. **L1 概念名与 WHO 官方类目名不一致**：必须手写覆盖；不要把 `gastrointestinal agent` 当 A 大类的正式名。
3. **zh/es 覆盖低**：官方 item 缺中文/西语标签；本数据没有自行机器翻译（避免把 AI 译名当官方），缺就留空；后续可人工翻译或找 CC0 多语源。
4. **zh-Hant 转换质量**：54 条由 OpenCC+TW 术语转换，需母语复核；`B01AA` 等已见语义偏差，手写优先。
5. **Wikidata 内容可能变**：CC0 可自由使用，但编辑战/重命名会导致 diff；CSV 生成时固定 snapshot（生成时间 + item ID）。
6. **ATC 码/类目本身需 WHOCC 核对**：本任务只做名称数据；「类目是否存在」仍需 ATC/DDD Index（WHOCC 许可，未使用），见 `reports/atc-intuition-audit.md` §1。
7. **不要把 CSV 当临床分类依据**：类名为导航/显示用途；不改变「ATC 码为准」的现有 UI 声明。

---

## 7. 产物与证据

| 路径 | 内容 |
|---|---|
| `data/atc_class_names.csv` | 1,154 行（65 KB）；code/level/四语名/source_url/CC0/confidence/wikidata_id/notes |
| `etl/fetch_atc_class_names.py` | 可重跑 ETL（SPARQL + wbgetentities + 选名 + OpenCC zh-Hant + build.py 对比；只读 DB；缓存） |
| `.tmp/atc-names/wd_class_items_raw.json` | SPARQL 原始类目 item 行（380 item / 372 code） |
| `.tmp/atc-names/wd_entities.json` | 四语标签/描述/P31 缓存 |
| `.tmp/atc-names/build_stats.json` | 覆盖/置信度/层级统计 |
| `.tmp/atc-names/manual_compare.json` | 与 build.py 38 条手写名的缺失/冲突/同义完整清单 |
| `.tmp/atc-names/manual_compare.json`、`check_csv.py` | 校验脚本（覆盖/疑似药名/冲突） |
| `reports/atc-class-names.md` | 本报告 |

**复现**
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/fetch_atc_class_names.py            # 使用缓存（无网也可复算 CSV）
& $py etl/fetch_atc_class_names.py --refresh  # 重新抓 Wikidata
```

**关键引用**
- Wikidata P267（ATC code）：https://www.wikidata.org/wiki/Property:P267
- 示例 item：A02 `https://www.wikidata.org/wiki/Q239559`、C07 `https://www.wikidata.org/wiki/Q385681`、A10 `https://www.wikidata.org/wiki/Q575062`
- 现有手写表：`site/build.py` 的 `ATC_L1_I18N` / `ATC_CLASS_I18N`（本次只读对比，未改）
