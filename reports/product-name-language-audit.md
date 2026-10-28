# 品牌名语言一致性审计（task-121）

> 日期：2026-10-29 ｜ 只读 `data/drugs.db`（431,555 产品 / 184,766 name_variant）＋源数据快照 ｜ **未改 DB/build.py、未 git/发布**
> 用户截图：中文界面成分页矩阵里 **CA 列**显示中文商品名「欧双宁」，**CN 列**却多为英文（Jentadueto / Trijardy XR），问「为什么 CA 能写中文」。
> 产物：本报告；证据 `.tmp/name-lang-audit/`；关联 task-122（全量数据质量审计 §3.3）。

---

## 0. 结论（先看这段）

1. **截图与 DB 实际相反**：`欧双宁` 是 **CN 注册商品名**（Boehringer 的 **Jentadueto**，linagliptin+metformin；CN 产品 CN-XA10BDL358A00-*）。**CA 没有任何中文 trade 名**（43,847 个 CA 产品的 trade 名全部拉丁/法语；Health Canada DPD 原始 `drugproduct.json` 58,379 条中 **CJK 记录 = 0**）。CA 对应产品（如 CA-02403250）的商品名是 **Jentadueto（拉丁）**。
2. **我们未做机器翻译**：`etl/build_translation_tables.py` 明确「品牌名不翻译」，`product_name` 原值直接来自源快照；CA 中文名不存在于 DB、也不存在于 DPD 源，不可能由我们生成。
3. **CN 的「英文名」只有 35 个**：CN 146,347 产品中，**18,252 个有中文 trade 名**、**35 个英文 trade 名**（进口品牌如 PLASBUMIN-20、PARLODEL），其余 **128,060（87.5%）没有 trade 名**——矩阵/详情显示的是 **注册通用名（中文）**，不是商品名。35 个英文 trade 名中 34 个有中文通用名 `inn_zh`，可附中文通用名但不改品牌名。
4. **修复方向**：UI 在列头/单元格明确「**当地注册名（本地语言）**」；矩阵对无 trade 名或英文 trade 名的产品可**附中文通用名**（已有 101,199 个 CN 无 trade 产品可显示中文通用名），**不翻译品牌名**；CN 商品名补全已排期（task-85/task-108），不重复排期。截图另可能是 build 矩阵列错位（Lead 已开 task-136 排查每行固定 td/占位）。

---

## 1. 统计口径

- 「trade 名」：`product_name.name_type='trade'`，代表性 raw 取 `name_variant.raw`；文字构成按 raw 的 CJK（U+3400–4DBF/4E00–9FFF/F900–FAFF）与 Latin（A-Z/a-z）判定。
- 产品级去重；「无 trade」= 该产品没有任何 trade 名。
- 源数据：`data/raw/ca/dpd/drugproduct.json`（CA）、`data/raw/nhsa/`（CN，商品名称/注册名称列）、`data/raw/tw/`（TW）；源快照只读。

---

## 2. 各市场 trade 名文字构成

| 市场 | 产品数 | 有 trade 名 | 中文 trade | 拉丁 trade | 无 trade（显示通用名） | 备注 |
|---|---:|---:|---:|---:|---:|---|
| **CN** | 146,347 | 18,287 | **18,252** | **35** | **128,060（87.5%）** | 中文 trade 如「欧双宁」「洛赛克MUPS」；35 个英文如 PLASBUMIN-20、PARLODEL |
| **TW** | 16,457 | 16,457 | 16,453 | 16,446 | 0 | 多为中英双名（同一产品两个 trade key） |
| **CA** | 43,847 | 43,847 | **0** | 43,847 | 0 | 全部拉丁/法语；DPD 源无 CJK |
| US | 110,179 | 55,570 | 0 | 55,570 | 54,609 | 只有约一半产品有 trade 名 |
| GB | 61,051 | 24,649 | 0 | 24,649 | 36,402 | dm+d 无中文 |
| ES | 25,395 | 25,387 | 0 | 25,387 | 8 | CIMA 西语 |
| MX | 10,878 | 10,766 | 0 | 10,766 | 112 | COFEPRIS 西语 |
| SG | 5,511 | 5,511 | 0 | 5,511 | 0 | 英文注册名 |
| AU | 11,890 | 11,877 | 0 | 11,877 | 13 | 英文 |

> 「中文 trade 名」按 `name_key.script='han'` 统计的产品数（可重叠：TW 同一产品可同时有中英两个 trade key）。

---

## 3. CA「中文名」核查

| 检查 | 结果 |
|---|---|
| CA 产品 trade 名含 CJK | **0**（43,847/43,847 全拉丁） |
| CA 产品所有 name_variant.raw 含 CJK | **0** |
| Health Canada DPD `drugproduct.json` 记录 | 58,379 条；**含 CJK 记录 0**（`json.dumps(ensure_ascii=False)` 检查） |
| 我们是否机器翻译？ | **否**：`etl/build_translation_tables.py` 原则「**品牌名不翻译**：product_name 原值以 source=non_translation 入表」；`etl/ingest_*` 直接把 DPD Brand Name 写入；`data/translations.csv` 不产生品牌译名（brand 行 0）；无任何 MT 写入 product_name |
| CA 是否华人市场产品？ | 不是按语言区分：DPD 注册名以英/法为主；个别产品虽可能由华人企业持有，但注册商品名仍为拉丁 |

**结论**：DB 中不存在「CA 中文商品名」；`欧双宁` 只出现在 CN（见 §4）。

---

## 4. CN「英文名」核查与可补中文

### 4.1 35 个英文 trade 名

- 来源：NHSA/进口注册数据中 `商品名称` 为英文（如 PLASBUMIN-20、PARLODEL、EUTROPIAN 等）；**这些产品本身有中文通用名**（`substance.inn_zh` / 注册名）。
- 可补中文：**35 个中 34 个有成分 `inn_zh`** → 矩阵可在英文 trade 名旁附中文通用名（如「PLASBUMIN-20（人血白蛋白）」），**不能翻译成中文品牌名**（无官方中文品牌名则留空）。
- 另有 1 个英文 trade 名产品无可用的中文成分名（需个案核对）。

### 4.2 128,060 个无 trade 名产品

| 子类 | 数量 | 显示建议 |
|---|---:|---|
| 有中文通用名（`inn_zh`） | **101,199** | 矩阵显示「注册通用名（中文）」，不得当商品名/品牌名 |
| 无中文通用名 | **26,861** | 显示注册名原文/英文或标「通用名未提供」；不猜测 |

### 4.3 为什么矩阵会看到「A + A salt」

- 用户看到的「Atorvastatin + Atorvastatin Calcium」类，是 build 索引把同一 base 的 salt/base substance 当成两个成分（伪复方），**与商品名语言无关**；已在 task-137 审计并给 build 归并方案（545 key / 8,778? 产品）。
- `欧双宁` 例子：CN 注册商品名「欧双宁」+ 中文界面 CN 列；CA 对应是 Jentadueto（拉丁）。若截图把两列看反/或 build 矩阵 td 错位（task-136 在排查每行固定 N td/显式占位），需以 build 修复为准。

---

## 5. 原因

1. **数据源按「当地注册名」原样入库**：CA DPD 的 Brand Name 为英/法；CN NHSA 的商品名为中文（进口药可为英文）；TW TFDA 同时有中英文名。`product_name` 不做翻译（合规+可核）。
2. **CN 数据本身 trade 覆盖率低**：NHSA 注册数据以通用名为主（146,347 产品中仅 18,287 有商品名），因此矩阵大量显示中文通用名；用户感知为「CN 列名字不同（中文/英文混杂）」。
3. **v0.8.1 双语对照只覆盖「有译名的成分/商品名」**：品牌名永不翻译，所以不能靠它把 CA 英文品牌变中文。

---

## 6. 建议（与已排期项分工）

| # | 建议 | 状态 |
|---|---|---|
| 1 | **UI 列头/单元格标「当地注册名（本地语言）」**，并加语言徽章（CN 中文名/CA 英文名/TW 双语） | **未排期**（可随 v0.8.3 矩阵改造或单独小任务；不重复造方案） |
| 2 | 矩阵单元格对「无 trade 名 / 英文 trade 名」产品**附中文通用名**（101,199 + 34 可补，来源 inn_zh；非翻译品牌） | **未排期**（可并入矩阵展示任务；数据已存在，无需改 DB） |
| 3 | CN 商品名补全（542 候选/接受 98.4% 现状） | **已排期** task-85 / task-108（不在本报告重复） |
| 4 | 品牌名机器翻译 | **不做**（v0.8.1 口径：品牌名永不翻译；无官方中文名不生成） |
| 5 | 矩阵列错位排查（td 固定/占位） | **已排期** task-136（impl-lazyload） |
| 6 | CA 源数据无中文名结论 | 记录在案；未来若 Health Canada 更新含中文注册名，自动随 DPD 增量进入（无需特别处理） |

---

## 7. 风险 / 注意

| # | 风险 | 说明 |
|---|---|---|
| 1 | 把通用名当商品名展示 | CN 128,060 无 trade 产品若矩阵不标注「通用名」，用户仍会误认为商品名；需按建议 #1/#2 |
| 2 | 用机器翻译补中文品牌名 | 会制造不存在的注册名，违反数据可核；不做 |
| 3 | 同名不同产品（CA Jentadueto vs CN 欧双宁） | 是同一活性成分在不同市场的不同注册名，不是同一产品；页面已按国家分列，需避免用户以为可互换（矩阵 identity only 声明已有） |
| 4 | 截图列错位 | 若 task-136 确认 build 渲染错位，以 build 修复为准；本报告结论基于 DB 数据 |
| 5 | 语言徽章/本地化文案 | 四语同步（en/es/zh/zh-Hant）；`当地注册名` 的译法需进 i18n |

---

## 8. 证据

| 文件 | 内容 |
|---|---|
| `.tmp/name-lang-audit/probe.py` / `probe.out.txt` | 各市场 source/trade 覆盖、CN/CA 示例、name_key.script 分布 |
| `.tmp/name-lang-audit/probe2.py` / `probe2.out.txt` | 「欧双宁/Jentadueto/Trijardy」检索、DPD raw CJK 检查（0 条）、CN 无 trade 显示 inn |
| `.tmp/data-quality/supplement.json` / `last.py` | CN 18,287 trade（18,252 中文/35 英文）、128,060 无 trade、101,199 有中文通用名、26,861 无、CA 0 CJK |
| `etl/build_translation_tables.py` | 品牌名不翻译原则（non_translation） |
| `data/raw/ca/dpd/drugproduct.json` | Health Canada DPD 原数据（58,379 条，CJK 0） |
| `reports/data-quality-audit.md` §3.3 | 名称语言一致性的全量审计 |
| `reports/pseudo-combo-audit.md` | 伪复方（base+salt）另因 |

_本报告由并行子智能体 data-depth 生成；未写真实 DB、未改 build.py、未 git/发布。_
