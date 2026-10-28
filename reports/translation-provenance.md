# 翻译来源/版本数据模型（所有市场/语言，品牌不译）— task-100

> 日期：2026-10-28 ｜ 版本：`2026-10-28.1` ｜ 任务：`task-100`（rev2：通用模型，普遍化到所有市场/语言）
> 交付：`data/translations.csv`、`data/ingredient_names_i18n.csv`、`data/label_translations.csv`、
> `etl/build_translation_tables.py`、本报告；证据在 `.tmp/translation-provenance/`。
> **只写 data/etl/reports/.tmp**；未写 `data/drugs.db`、未改 `site/build.py`、未 git/发布。
> 目标：支撑「本市场原名 + 已选语言译名 + 翻译来源/版本」显示；任何市场/语言只加行，不改表结构。

---

## 0. 结论

| 项 | 结果 |
|---|---|
| 通用模型 | **`data/translations.csv`**（长表，19,864 行 / 2.60 MB）：`entity_type/entity_id/field/lang/value/source/source_url/machine_translated/confidence/version/updated_at`；新增市场/语言只需追加行 |
| 成分 | `data/ingredient_names_i18n.csv`（12,649 个 substance / 12,649 行 / 2.33 MB）：en 100%、zh **2,879（22.8%，全部带 source/url）**、es **640（5.1%：WHO 官方 380 + AEMPS 260）**、zh-Hant **0**（无官方批量源，留空不瞎转）、pt **0**（待 INFARMED 授权）；**AI 名称 0 条入库**（不盲译；机制已预留） |
| 标签 | `data/label_translations.csv`（69 行 / 20 KB）：剂型 40、状态 4、单位 20、释放 5 × en/es/zh/zh-Hant/pt（pt 为**人工参考译名**，非 AI） |
| 品牌名 | **不翻译**：`translations.csv` 中 16,000 行 `entity_type=product_name`、`source=non_translation`、`value=对应市场 product_name 原值`（每市场 2,000 条高频名；覆盖率见 §2.3），AI 不参与 |
| 版本 | `2026-10-28.1`（规则见 §4）；每行带 `version` + `updated_at`，来源可追溯 |
| 缺口 | zh 77.2% 成分无官方/半官方中文名；zh-Hant/pt 无官方批量源；es 部分来自 AEMPS（许可待确认）；**都在报告显式标注，不用 AI 填充** |

**为什么没有 AI 译名**：任务要求「缺 zh 不盲译；AI 译名必须 machine_translated=true/low 且默认不显示」。
本轮对 zh-Hant 曾评估「简繁转换候选」（OpenCC 字表反向），但自动转换会产出错字（例：醋酸→醋痠），
**宁可留空让 build 回退原名，也不把错误候选写进数据**；模型与生成器已支持 `source=ai / machine_translated=1 / confidence=low / display_default=0`
（未来接入人工复核过的 AI 译名时直接加行即可，默认不上页面）。

---

## 1. 通用模型：`data/translations.csv`

| 列 | 说明 / 取值 |
|---|---|
| `entity_type` | `substance` / `product_name` / `label`（可扩展 `maker`、`atc_class`、`country` 等） |
| `entity_id` | substance_id；品牌为 `<country>:<key_id>`（按国家+商品名键去重，避免 40 万 product 行）；标签为 `<category>:<code>`，如 `form:tablet`、`unit:mg` |
| `field` | `name`（名称）/ `form`（剂型）/ `status`（状态）/ `release`（释放）/ `unit`（单位）；未来可加 `route`、`atc_name` |
| `lang` | `en` / `es` / `zh` / `zh-Hant` / `pt` / 任意 BCP47（新增语言=新行，无需改表） |
| `value` | 译名或原名 |
| `source` | `official`（WHO/EMA 等官方标准） / `regulator`（药监/EU 机构事实，如 CN 产品通用名、AEMPS、INFARMED 参考术语） / `pharmacopoeia`（药典/命名原则，如中国药品通用名称） / `ai`（机器候选，仅内部、默认不显示） / `non_translation`（品牌原名） |
| `source_url` | 逐行来源链接（WHO IRIS、NHSA、AEMPS CIMA、CHP、INFOMED、CITS 等；标签按语言分别给 URL） |
| `machine_translated` | 0/1；1 必须同时 `confidence=low` 且不显示 |
| `confidence` | `high` / `medium` / `low` / `reference` |
| `version` | 表版本（`YYYY-MM-DD.N`） |
| `updated_at` | ISO8601 生成时间 |

**新增市场/语言**：只追加行，例如未来巴西（`lang=pt-BR`）或新加坡（`lang=en`，但 `entity_id`/`source` 换成本地来源）；
`source` 与 `version` 按来源真实填写；**不需要改表结构、不需要改 build 的映射逻辑**（build 只按 key 查表 + 回退）。

---

## 2. 三张表与覆盖率

### 2.1 成分：`data/ingredient_names_i18n.csv`（宽表，给人工审阅/导出）

| lang | 有值 | 覆盖率 | 来源与说明 |
|---|---:|---:|---|
| en | 12,649 | 100% | DB `substance.inn_en`（INN/监管名称，事实字段） |
| zh | **2,879** | **22.8%** | 全部带 `source_zh=regulator` + `source_url_zh`：`override` 318、`product_majority` 536、`product_base_aggregate` 6（来自 `inn_zh_backfill.csv`）、`legacy_batch` 2,019（任务-42 旧回填批次，NHSA 产品通用名，medium） |
| zh-Hant | **0** | 0% | **无官方台湾 INN 批量清单**（中華藥典/食藥署无开放数据）；不自动简繁转换，留空 → build 回退原名 |
| es | **640** | 5.1% | WHO INN 官方西语名 **380**（CC BY-NC-SA，`source=official`，confidence=high）；AEMPS CIMA 合并 **260**（`source=regulator`，confidence=medium，许可待确认） |
| pt | **0** | 0% | 无官方/授权葡语 INN 数据（INFOMED 未授权，CITS 让与待申请）→ 留空，不盲译 |

- **不盲译**：9,770 个 substance 无 zh 行，宽表留空，`notes` 明确「zh 缺官方/半官方来源，留空未盲译」。
- `confidence=high` 的 zh 才 `display_default_zh=1`；medium/low 默认 0，build 可显示但加「参考/待核」标记（见 §5）。
- 宽表列：`substance_id, inn_en, name_zh, source_zh, source_url_zh, confidence_zh, name_zh_hant, source_zh_hant, source_url_zh_hant, confidence_zh_hant, name_es, source_es, source_url_es, confidence_es, name_pt, source_pt, source_url_pt, confidence_pt, machine_translated, display_default_zh, display_default_zh_hant, display_default_es, display_default_pt, version, updated_at, notes`。

### 2.2 标签：`data/label_translations.csv`（69 行）

| category | 行数 | 例子 | 来源 |
|---|---:|---|---|
| form（剂型） | 40 | tablet/comprimido/片剂/錠劑/comprimido；liquid、topical、pellet、inhalation、stick、kit、gas、cloth、soap、swab、mouthwash、gum, chewing、globule、oil、rinse、jelly、灌肠剂、体外诊断试剂、lipstick 等 DB 高频值 | en official；es AEMPS 参考；zh/zh-Hant 药典/命名原则；pt INFARMED/欧洲葡语参考术语 |
| status（状态） | 4 | active/activo/在售/販售中/ativo；discontinued、withdrawn、unknown | 与站点 `drug.status.*` 对齐；pt 参考 |
| unit（单位） | 20 | mg、g、%、ml、mcg、iu（IU/UI/国际单位/國際單位/UI）、unit、ug/microgram→mcg、l、万iu、kg、meq、u、mci、IU、units、lf、mm、m | 国际单位保持原写法；zh 参考药典，pt 参考 INFARMED 术语 |
| release（释放） | 5 | IR/速释/速釋/libertação imediata；ER/缓释/緩釋/prolongada；DR/迟释肠溶/延遲釋放/retardada；MR/改良释放/修飾釋放/modificada；none/—/—/não aplicável | 项目参考译名（术语表无 release 域） |

- 每行含 5 语 + `source_en/es/zh/zh_hant/pt` + `source_url` + `confidence` + `machine_translated` + `display_default`；
  `machine_translated=0`（标签为人工整理参考译名）；pt 全部 filled（69/69），但标注 `confidence=reference`，build 显示时建议加「参考/待母语复核」。
- 单位 code 与 DB `strength_unit`/`variant` 原始 token 对齐（build 可直接按 token 查表，查不到回退原 token）。
- 剂型 code 与 DB `form_base` 对齐（含 `gum, chewing`、`灌肠剂` 等原始值）。

### 2.3 品牌名：不翻译（`translations.csv` 内 `non_translation`）

- 16,000 行（每个市场 **2,000** 条最高频商品名；`--brand-limit 0` 可全量，文件会明显变大）；
  `entity_type=product_name`、`field=name`、`lang=该市场语言`、`value=product_name 原值`、`source=non_translation`、`machine_translated=0`。
- 市场语言：US/GB/AU/CA→`en`，ES/MX→`es`，CN→`zh`，TW→`zh-Hant`，PT→`pt`（未来市场只需映射表加一行）。
- 产品覆盖率（按该市场产品数，高频子集）：GB 66.7%、US 58.3%、AU 53.4%、ES 41.1%、CA 29.8%、MX 27.0%、TW 12.8%、CN 9.1%。
  **完整商品名本来就在 DB/index 的 `product_name`/`name_key` 中**；本表只提供「同名不译 + 原名语言」的通用行，build 优先用索引原名，缺时回退本表。
- 品牌名是商标/专名，**永不机器翻译**；也不应把「Brufen」「Voltaren」等译成中文再当商品名。

---

## 3. 来源与许可

| source | 典型来源 | 许可/义务 |
|---|---|---|
| `official` | WHO INN 官方西语名（WHO INN Lists，IRIS）；EMA 数据 | WHO：**CC BY-NC-SA 3.0 IGO**（署名+非商业+SA；不得暗示 WHO 背书）；EMA：允许复制/分发（商业/非商业），须注明 EMA 来源 |
| `regulator` | 中国 NHSA 药品分类与代码/产品通用名（inn_zh 回填）；AEMPS CIMA 西语名；INFARMED/INFOMED 参考术语 | 中国：**未找到再发布许可**（仅事实字段+链回）；AEMPS：许可条款待确认（署名+更新日期）；INFARMED：书面许可/协议（task-96 正在申请） |
| `pharmacopoeia` | 《中国药品通用名称命名原则》（CADN）、台湾药典参考 | 政府公开信息/付费出版物；仅事实/参考 + 链接，不复制全文 |
| `ai` | 机器候选（当前 **0 条**） | 仅内部候选；`machine_translated=1`、`confidence=low`、**默认不显示**；上线前需人工/官方核对 |
| `non_translation` | 品牌名=市场原名 | 只存事实原名，不翻译、不创造译名 |

> 若未来把 `translations.csv` 作为公开数据产品发布：WHO 派生行需按 CC BY-NC-SA 署名+同许可；中国/AEMPS/INFARMED 行只能保留事实字段并链接来源；**不要整体打 CC0/CC BY**。

---

## 4. 版本号规则

- `version = <快照日期>.N`，本轮 `2026-10-28.1`；`updated_at` 为生成时间（ISO8601）。
- 触发升版：DB（substance/inn_zh/product_name）变化、`who_inn_names.csv`/`inn_zh_backfill.csv`/`es_inn_overrides.csv`/`terminology_glossary.csv` 变化、
  标签/术语修订、新增市场/语言。
- 用法：页面/About/下载链接可显示「翻译数据版本：2026-10-28.1」；行级 `version` 便于 diff 与回滚。
- 页面显示建议同时在译名旁标注来源类别（WHO/NHSA/AEMPS/药典）与「参考译名」字样（尤其 es/pt/medium 置信度）。

---

## 5. build 接入方式（本次不改 build.py，供后续任务）

1. 读取 `data/translations.csv`（构建期，不必上线时请求）：建立索引
   `(entity_type, entity_id, field, lang) -> row`；同一 key 不应重复（本表 0 重复，已校验）。
2. **字段级回退**（任意字段通用）：
   ```
   display(entity_type, entity_id, field, requested_lang):
     1) requested_lang 行，display_default=1 且 machine_translated=0 → 显示译名（带 source/version 标注）
     2) 请求语言无行/隐藏 → 回退该实体的「市场原名」（品牌=market original；成分/标签=en 或 DB 原值）
     3) 仍无 → 回退原始 token（如 form_base/status/release/strength_unit 原值）
     4) AI 行永不自动显示（除非显式「显示机器候选」开关 + 醒目提示）
   ```
3. 显示形态：「**本市场原名** + `译名`（来源：WHO/NHSA/药典；版本 2026-10-28.1）」；
   品牌名只显示市场原名（可显示「不翻译」说明）。
4. 选择语言时：UI 语言 = 用户选择；若该语言无官方/参考译名，**不要显示英文占位以外的 AI 译名**；
   zh-Hant 用户：无官方繁体名 → 显示 en 原名 + 「暂无可信繁体译名，暂显示原名」提示（也可回退 zh 简中并标注简繁差异，需产品决定）。
5. 语言/市场扩展：build 的 `LANGS`/`COUNTRIES` 加新语言/国家后，只需在 translations 表补行；回退逻辑不变。
6. 体积：可只为「页面实际展示的字段」构建期过滤（substance 名 + 标签），或生成 `data/translations.json` 按语言懒加载；
   不要首屏加载完整 2.6 MB CSV。
7. 本轮不动 `xz` 索引字段（成分中文名已有 v0.5.5 机制）；未来可用 translations 表作为 `xz` 的权威来源，逐步替换。

---

## 6. 缺口、风险与建议

| # | 缺口/风险 | 影响 | 处理 |
|---|---|---|---|
| R1 | zh 仅 22.8%，9,770 个成分无中文名 | 中文界面只能显示 en 原名（不盲译） | 继续用「CN 产品通用名/overrides」补（现有方法可重跑）；不引入 AI 直译；目标逐批提高并记录版本 |
| R2 | zh-Hant 0 官方名 | 繁中界面无成分中文名 | 待台湾官方 INN/药典开放数据或人工审核；当前回退原名 |
| R3 | pt 0 官方名 | 葡语界面无成分译名 | 等 INFARMED/CITS 授权（task-96 申请中）；拿到后按新增语言/来源加行 |
| R4 | es 官方仅 380（WHO 匹配到 DB 名称的盐型/组合差异），AEMPS 260 许可待确认 | 西语覆盖有限 | 改进 INN 基础名/盐型匹配（已去盐+同义词，覆盖率仍受 WHO 与 DB 名称域差异限制）；AEMPS 许可结论前只事实+链接 |
| R5 | 标签 pt 为人工参考（未母语复核） | 可能用词不地道 | 显示「参考译名」；zh-Hant/pt 母语校对后升 confidence |
| R6 | 品牌名覆盖是高频子集（2k/市场） | 长尾品牌不在 translations 表 | build 优先用 DB/index 原名；生成器 `--brand-limit 0` 可全量（注意仓库体积） |
| R7 | 来源/许可混合，WHO NC-SA、中国无开放许可、AEMPS 待确认 | 不能把整表当开放数据发布 | 保持内部/事实字段用途；对外发布前按来源拆分/署名；报告与 About 说明 |
| R8 | 简繁/地区用词差异（如 錠劑 vs 片劑） | 繁中用户看到简中词 | 有官方 zh-Hant 源前不自动转换；UI 标签已有 zh-Hant 字典单独校对 |

---

## 7. 复现与校验

```powershell
# 生成三张表（只读 DB；默认每市场 2000 条品牌高频名）
& $py etl/build_translation_tables.py
# 全量品牌名（文件会明显变大）
& $py etl/build_translation_tables.py --brand-limit 0
```

已校验（`.tmp/translation-provenance/check.py` 输出）：
- `translations.csv` 22,209→19,864 行（移除 zh-Hant 机器候选后），**0 重复 key**；
- 所有 `entity_type=product_name` 行 `source=non_translation`、`machine_translated=0`；
- 所有 `entity_type=substance/lang=zh` 行都有 `source_url` 和 `confidence`；
- `label_translations.csv` 69 行 × 5 语全部有值（pt 69/69，`machine_translated=0`，`confidence=reference`）；
- 宽表行数与 long 表对应（ingredient 12,649 行 = substance 总数）。

## 8. 产物与证据

| 路径 | 内容 |
|---|---|
| `data/translations.csv` | **通用长表**（19,864 行 / 2.60 MB；所有市场/语言只加行） |
| `data/ingredient_names_i18n.csv` | 成分宽表（12,649 行 / 2.33 MB；en + zh + es + pt + 来源/置信度/展示标记） |
| `data/label_translations.csv` | 标签宽表（69 行 / 20 KB；剂型/状态/单位/释放 × 5 语） |
| `etl/build_translation_tables.py` | 生成器（只读 DB，读 4 个既有映射/术语文件；`--brand-limit` 可调） |
| `.tmp/translation-provenance/build_stats.json` | 行数/字节/覆盖率/来源分布统计 |
| `.tmp/translation-provenance/check.py` | 结构与一致性校验脚本 |
| `.tmp/translation-provenance/recon*.py` | DB/来源文件盘点脚本 |
| `reports/translation-provenance.md` | 本报告 |
| 既有依据 | `reports/ingredient-i18n.md`（inn_zh 回填）、`reports/terminology-accuracy.md`（术语基准）、`reports/pt-audit.md`（pt 来源许可）、`reports/zh-hant-i18n*.md`（繁中 UI 字典） |
