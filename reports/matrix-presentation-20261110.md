# 成分页矩阵：呈现逻辑重设计 + 单位归一口径

> 任务：只读调查 + 出设计规格。**没有改 `site/build.py`、没有构建、没有写库。**
> 日期：2026-11-10 · 角色：信息设计员 · 样本：`/drug/polymyxin-b.html`、`/drug/acetaminophen.html`、`/drug/insulin-human.html`
> 用户原话（2026-11-10）：「这个呈现逻辑有很大的问题」「单位还可以归一」

---

## 0. 先读这一节：样本口径与一个必须知道的时差

| 项 | 值 | 说明 |
|---|---|---|
| 实测对象 | `site/dist`，构建时间 **11:48**（v0.10.2） | 所有「现状」数字都来自这个构建 |
| 源码状态 | `site/build.py` 最后修改 **13:34**（常驻成员正在改） | 与 dist 不是一个版本 |
| 已在源码里修好、**dist 里还没有** | ① `_fmt_qty()` 修 `1e+06` ② `_spec_num()` 认千分位 ③ 身份行 `n_markets/n_records` 取错列（`len({r[0]})`/`len({r[9]})` 已改对） | 所以下文标「待构建验证」，不列为待修 |
| 因此 | 文中「1e+XX 42 页 / 183 处」是 **dist 的现状**；源码更新后应为 0，**验收方法写在 §E** | 谁也不许拿「源码已修」当已验收 |

本节之后的所有数字都能用 §E 的命令复现。

---

## A. 量化

### A.1 三个样本页 × 两档视口（zh / Chrome 无头 / 视口 390×844 与 1440×900）

| 指标 | polymyxin-b | acetaminophen | insulin-human |
|---|---:|---:|---:|
| 规格行（渲染） | 30 | **120（封顶；实际 273）** | 20 |
| 其中有数据（默认列里至少 1 个名字） | 14 | 84 | 8 |
| **默认三列全空的行** | **16（53%）** | **36（30%）** | **12（60%）** |
| 市场列（`th[data-country]`） | 9 | 10 | 9 |
| 默认三列（`data-defcol`） | `HK · TW · US` | `AU · TW · US` | `CN · HK · US` |
| 可见格空比（默认列 × 全部行） | **82.2%** | **71.7%** | **86.7%** |
| （只算有数据的行） | 61.9% | 59.5% | 66.7% |
| 平均行高 @1440 | **109 px** | **148 px** | **126 px** |
| 平均行高 @390 | **251 px** | **307 px** | **257 px** |
| 最大行高 @1440 / @390 | 173 / **437** | 195 / **682** | 195 / 332 |
| 单格最多名字（含 `+N` 里的） | **165** | **344** | 18 |
| 单格 ≥7 个名字的格子 | 5 | 37 | 4 |
| `1e+XX` 行 | **1**（`1e+06 IU/100 mL`） | 0 | 0 |
| 质量比例式 `A mg / B mg` 行 | **2**（`520 mg/100000 mg`、`1000 mg/100000 mg`） | 1 | 0 |
| 任意 `A/B` 行 | 7 | 25 | 4 |
| 同成分单位写法种类 | **6**（`unit` `IU` `IU/mL` `mg` `g` `mL`） | 5（`mg` `g` `mL` `mg/mL` `%`） | 5（`IU` `IU/mL` `unit` `mg` `mL`） |
| 首屏可见行（≥90% 记 1、≥25% 记 0.5） | 6 / **2** | 3.5 / **0.5** | 4.5 / 2 |
| 文档总高 @1440 / @390 | 3,377 / 7,192 | 16,041 / 33,761 | 2,437 / 4,920 |
| 被 line-clamp 裁掉的名字数（占全部） | 195 / 295（66%） | 1,942 / 3,278（59%） | 19 / 78（24%） |

复现：`python .tmp/matrix-audit/probe.py site/dist .tmp/matrix-audit/probe.json docs/img`（脚本说明见 §E.3）

**读法**：行高不是「内容多」造成的，是**列选错 + 空行不隐藏 + 单格塞 3 个名字**三件事叠出来的。
polymyxin 的 30 行里 16 行在屏幕上是纯空白；acetaminophen 的一行（682 px）里塞了 344 个名字。

**那 165 个名字全在「未公开」那一行**：`polymyxin-b` 的 US 列有 383 个产品，只有 20 个带强度——剩下 363 个全落到
`not disclosed / topical` 与 `not disclosed / liquid` 两个格子里（最大一格 165 个名字，整行 188 个）。
即「美国有 383 个产品」这件事，在矩阵里只剩两行灰字。这也是为什么 v0.10.3 要把「未公开」压成一行折叠、把名字数写在行首。

### A.2 全站扫（11,137 个有矩阵的成分页，字节级统计）

| 指标 | 数字 | 口径 |
|---|---:|---|
| 页面数 / 数据格总数 | 11,137 / 348,358 | `<td data-country>` 计数 |
| 「未收录」格 | **255,451（73.3%）** | `data-i18n="matrix.none"` |
| 空比中位 / P90 / 最高 | 0 / 0.738 / 0.89 | 每页空比 |
| 空比 ≥50% 的页 / ≥80% 的页 | **3,034 / 645** | — |
| 规格行总数 | 76,444 | `<tr data-form=` |
| **默认三列全空的行** | **9,086（11.9%）**，落在 1,479 页 | `data-defcol` 全为 `none` |
| 市场列总数 / **整列无任何记录** | 23,682 / **95（0.4%）**，51 页 | 空列极少 |
| 行数 P50 / P90 / 最大 | 2 / 15 / 120（90 页顶到封顶） | — |
| 列数 P50 / P90 / 最大 | 1 / 6 / 10 | — |
| 含 `1e+XX` 的页 / 处数 | **42 / 183** | `oxygen` 18、`benzalkonium` 10、`petrolatum` 10 |
| 含质量比例式（`mg/100000 mg`）页 / 处数 | 330 / 2,371 | `camphor-synthetic` 62、`petrolatum` 61 |
| 单格 ≥7 个名字的格 / 页 | **7,285 / 1,708** | 最多 `chlorphenamine-maleate` **762 个** |

**这张表最该被记住的一句**：空列只有 0.4%，**空行 11.9%、空格 73.3%**。
所以「隐藏空列」是顺手做的，真正的杠杆是**默认三列选谁** 和 **空行不渲染**。

### A.3 全库单位写法（`product_component`，628,013 行）

`strength_unit` Top 20（原样）：

| # | 写法 | 行数 | # | 写法 | 行数 |
|--:|---|--:|--:|---|--:|
| 1 | `mg` | 445,291 | 11 | `microgram/g` | 1,047 |
| 2 | `%` | 26,362 | 12 | `g` | 871 |
| 3 | `mL` | 19,059 | 13 | `microgram/mL` | 676 |
| 4 | `mg/g` | 9,771 | 14 | `microlitre/mL` | 437 |
| 5 | `microgram` | 6,102 | 15 | `million` | 415 |
| 6 | `mg/mL` | 4,402 | 16 | `mg/vial` | 247 |
| 7 | `IU` | 3,640 | 17 | `万IU` | 233 |
| 8 | `unit` | 3,042 | 18 | `microgram/actuation` | 187 |
| 9 | `g/L` | 1,482 | 19 | `IU/mL` | 154 |
| 10 | `billion` | 1,357 | 20 | `mEq` | 151 |

中文写法与变体逐条计数（**全部为精确匹配**）：

| 写法 | exact | 说明 |
|---|---:|---|
| `单位` / `毫克` / `毫升` / `微克` / `克` / `千克` / `升` / `国际单位` | **0 / 0 / 0 / 0 / 0 / 0 / 0 / 0** | 库里没有中文单位；中文「单位 / 国际单位」是**界面层**由 i18n 生成（`unit.unit`→单位，`unit.iu`→国际单位） |
| `IU` | 3,640 | 另有 `万IU` 233、`IU/mL` 154、`IU/g`… 合计 4,079 |
| `unit` / `units` / `U` / `u` | 3,042 / 0 / 0 / 0 | 只有 `unit` 一种；`U`/`u` 只在复合写法里出现（4,262 行含 `U`） |
| `microgram` / `micrograms` | 6,102 / 0 | 界面显示为 `mcg`（en/es）或 `微克`？→ 实为 `mcg`（四语都映射到 `mcg`） |
| `mcg` / `µg` / `μg` / `ug` | 0 / 0 / 0 / 0 | 只作为复合写法出现（`mcg/mL` 53 行等，含 `mcg` 的 147 行） |
| `㎎` / `㏄` / `gr` / `ml` / `l` | 0 / 0 / 0 / 0 / 0 | 无 |
| `mg` / `mL` / `g` / `kg` / `L` / `%` | 445,291 / 19,059 / 871 / 140 / 0（`L` 只作复合）/ 26,362 | — |

- 需要改写的行（写法不是规范小写/规范符号）：**17,478（2.8%）**，主要是 `microgram` 6,102、`unit` 3,042、`g/L` 1,482、`mEq` 151。
- **同一成分存在 ≥2 种单位写法**：2,206 个成分（按原样）；归一后仍 **≥2 个单位族**的：**1,192 个（成分×国家）对、887 个成分**；其中**同一数值出现 ≥2 个单位族**（会拆成多行）的 **545 组**。
- **二元式强度**：`strength_unit` 含 `/` 的组件行 **19,408**（7,957 个产品）；`per_volume` 非空 **89,560 行 / 74,570 个产品**。
  - 分母是容量：`mL` 75,149（其中 `/100 mL` 14,254）；分母是质量：`mg` 13,625（其中 `/100000 mg` **9,474**）；`actuation` 167、`tablet` 140、`h` 312。
  - 也就是说：**13,629 行会显示成「质量/质量」的比例式**，这就是用户看到的 `1000 mg/100000 mg`。

### A.4 「规格待核」标签在打谁（顺手量出来的）

现规则（`_strength_suspect`：值 ≥1e6，或值 >10,000 且单位不是 `u/iu/unit/units/%/ml`）在 active 组件里命中 **11,526 行（2.96%）、629 个成分**，其中大量是**合法**的 w/w 浓度（`15000 mg/100000 mg` 面霜）和高效价（1,000,000 IU）。改成「只对质量单位可疑」后命中 **2,738 行（−76%）**。这直接关系到「排序无规律」——被标黄的行会被排序键踢到最后。

---

## B. 单位归一：**规范化** 与 **换算** 是两件事

### B.1 可以做（显示规范化 + 同量纲缩放）

| 类 | 映射 | 影响行数 |
|---|---|---:|
| 质量 | `克/g/gr/gm`→`g`；`毫克/mg/㎎`→`mg`；`微克/µg/μg/mcg/ug/microgram(s)`→`µg`；`千克/kg`→`kg` | `microgram` 6,102 行显示为 `µg`（或 `mcg`） |
| 容量 | `毫升/mL/ml/cc/㏄`→`mL`；`升/L/l/liter/litre`→`L`；`microlitre`→`µL` | `mL` 已规范，`microlitre/mL` 437 行 |
| 效价 | `IU/iu/I.U./国际单位`→`IU`；`单位/U/units/unit`→`单位`（**不合并数值**） | `unit` 3,042 行 |
| 数字 | 去浮点表示（`1e+06`→`1 000 000`）、千分位、去尾 0 | 57 行 ≥1e6；`_fmt_qty` 已修 |
| 同量纲缩放 | `0.5 g` ≡ `500 mg`、`1000 µg` ≡ `1 mg` → **合并一行**，规范值 + 小字「原记录 0.5 g」 | task-17 已生效（见 B.3 实测） |
| 分母同量纲化 | `1000 mg/100000 mg` → `1000 mg · 每 100 g`（100000 mg = 100 g，质量→质量） | 9,474 行；设计稿 `matrix-spec-mock-*.png` 已经这么显示 |

### B.2 禁止（红线，写进代码评审也照这条）

1. **`IU ↔ mg/µg` 不做**：需要物质专属系数（肝素、维D、维E 各不相同），属剂量换算。
2. **`% ↔ mg/mL` 不做**：需要密度。
3. **`单位 ↔ IU` 不合并数值**：只加提示「来源分别写作…」。全库有 **36 组**同成分同剂型同数值、IU/unit 分属不同国家（如 `epoetin-alfa` 4,000：`CN·ES·SG·TW` 写 IU、`AU` 写 unit）。
4. **复方 `A/B` 不做比例换算**：`1000/125` 不能约成 `8:1` 再比。
5. **`mg/100000 mg` 不折算成 `%`**（哪怕数学上等价）：一旦开始折算，下一个人就会问「那 5% 的乳膏换成 mg/g 是多少」。

> 一句话给实现者：**同量纲乘除 1000 可以，跨量纲一步都不行；显示可以改写法，数值只许在同一量纲内缩放。**

### B.3 「74 组当验收」需要修正（复核结论）

brief 里的「74 个同成分同国家 g/mg 并存且数值等价」——**74 这个数能复现，但它不是「等价」**：

```
同成分同国家同时出现 g 与 mg 写法：(成分, 国家) = 74 对   ✅ 与 brief 一致
其中数值真的等价（0.5 g ↔ 500 mg）  = 0 组              ❌ 不是 74
数值等价的组（同成分+同国家+同一 mg 当量，≥2 种写法）= 428 组，全部是 microgram ↔ mg
```

74 对长这样（`zinc-oxide/US`：`g` 侧是 110,000 g、`mg` 侧是 0.05 mg）——是**完全不同的产品**，绝不能合并。
真正的等价集是 **428 组 `microgram ↔ mg`**（`cholecalciferol/AU` 0.025 mg ← 25 microgram 等），而它 **v0.10.2 已经合并了**（`cholecalciferol.html` 里 `0.025 mg` 带小字「原记录：25 microgram」52 处）。

**所以验收标准改成**：
- 真实数据：428 组必须仍然合并成一行（回归，不许退化）；
- 构造用例：`0.5 g` vs `500 mg`、`1000 µg` vs `1 mg`（今天库里没有，用单元测试/fixture 保证规则在）；
- 反向用例：74 对必须**不**合并；36 组 IU/unit 必须**不**合并数值、只出提示。

### B.4 写法归一到底能省多少行（别高估）

| 动作 | 全库省行 | 三页效果 |
|---|---:|---|
| 写法归一（`/1 mL` = `/mL`、`µg`=`mcg`、`unit`=`units`） | **323 行（0.4%）** | polymyxin −1、acetaminophen −6、insulin −1 |
| 再让 IU 与 unit「并列」（per_volume 相同才并列） | **48 行（0.1%）** | epoetin-alfa −8、follitropin-alfa −8；polymyxin/insulin **0** |
| 「未公开规格」行（无强度） | 11,036 行（12.8%） | polymyxin 6、insulin 5、acetaminophen 8 |

**结论**：单位归一提升的是**可读性**（`6000 unit` / `6000 IU` / `6000 IU/mL` 不再像三个不同东西），**它救不了行数**。
行数要靠 §C 的「空行不渲染 + 默认列换人 + 剂型分组」，直到方案 ② 把「行」这个概念整个换掉。

---

## C. 呈现逻辑重设计

### C.1 一个人打开成分页 3 秒要知道的三件事

```
① 有什么剂型？        → 片剂 / 胶囊 / 注射液 / 外用 …
② 每个剂型有哪些规格？ → 500 mg / 325 mg / 160 mg/5 mL …
③ 每个规格在哪些国家有注册名、叫什么？ → US: Tylenol…, CN: 泰诺…
```
现在页面的回答顺序是「按记录数排序的 30 行 × 3 个恰好没数据的国家」，三问一个都答不了。

### C.2 方案 ① · 剂型分组矩阵（保留表格，收窄它）

结构（1440 宽）：

```
Acetaminophen  ATC N02BE01 · 10 个市场 · 12,645 条产品记录
[筛选 120/273 · 3/10]                                    ← 现有筛选器保留
────────────────────────────────────────────────────────
片剂 (18 个规格)                        ← 组标题行（吸顶，带规格数）
  规格        国家①        国家②        国家③      更多
  325 mg      …            …            …          +2 个市场
  500 mg      …            …            …          +3 个市场
胶囊 (9 个规格)
  250 mg      …
────────────────────────────────────────────────────────
另有 12 个规格只在 CA · CN 有记录 → [把 CA 加为一列]
「未公开」6 个规格（来源不披露强度，不等于没有强度）→ 折叠一行
```

390 宽：一个规格 = **一行**（不是三段）

```
片剂 (18)                                     ← 组标题
325 mg                                        ← 规格这一行
  US 2 · TW 1 · CN 3            ← 市场 chips（名字数不为 0 才出现）
[详情]                          ← <details> 展开：逐市场名字（无 JS 也能开）
```

规则：
1. **行 = 剂型 × 规格**；组标题用现有 `_form_rank` 顺序（片/泡腾 → 胶囊 → 液体 → 注射 → 外用 → 吸入 → 粉/颗粒 → 其它）。
2. **组内排序**：单位类（mg → IU/单位 → mL → A/B 比例 → 未公开）→ 数值**升序** → 记录数降序。
   （把「常用度」从第 1 位降到第 4 位：这就是「10000 → 5000 → 10000 → 35000」的病根。）
3. **默认列 = 有「带强度的记录」最多的 3 个市场**，不再按总记录数；`US` 只在它自己进前 3 时才占位（现规则无条件插 US）。
4. **空行不渲染**：默认三列全空的行不渲染，落到「另有 N 个规格只在 X 有记录」+ 一键加列（现有 `matrix.hidden_rows` 机制）。
5. **空列不显示**：整列无记录的市场不进表头（全站只有 95 列，顺手）。
6. **单元格**：2 个名字 + `+N`（`<details>` 展开），名字 2 行截断 + `title` 全文。
7. **单位并列**：同一 (剂型, 数值, per_volume) 下 `unit`/`IU` 只是写法不同 → 一行内并列，小字「来源分别写作：6000 单位（CA）· 6000 IU（ES）」，**不换算**。
8. **保留**：`原记录` 小字（`matrix.original`）、「不可互换」notice、`?mk=`、状态徽章、HK/AU 例外说明。

### C.3 方案 ② · 规格列表（= 仓库里已有的设计稿方向）

> **注意**：`docs/img/matrix-spec-mock-1440.png` / `-390.png`（13:46 由另一工位产出，标「设计稿 · 方案 B」）
> 就是这个方向的原型。本节把它当**既有方案**来评估，不另起一套；我量的数字来自这两张图。

结构：剂型 chips（带规格数）→ 「有记录的市场: US 12 ES 5 CA 4 …」→ 按剂型分组的规格行；
**一行 = 一个规格**，市场名内联在行内（`US <名字> +6  CA <名字> +4`），per_volume 单独一列（`每 100 g`）。

```
Polymyxin B   ATC J01XB02 · 9 个市场 · 30 个规格 · 37 条注册名记录
剂型  [外用 16] [液体 9] [胶囊 1] [粉末 1] [注射 1] [其他 2]      ← ① 剂型 + ② 每剂型几个规格
有记录的市场: US 12  ES 5  CA 4  CN 4  SG 4  TW 3  GB 3  MX 1  HK 1
外用（topical）  16 个规格                                       ← ② 规格清单
10 000 单位      —          US Bacitracin Max Antibiotic…  +6   CA ANTIBIOTIC FOR KIDS  +4
5 000 单位       —          US ClaraVie  +6
1 000 mg        每 100 g    US Family Wellness Antiseptic…
520 mg          每 100 g    US Family Wellness
展开其余 9 个规格 ▾
液体（liquid）  9 个规格
1 000 000 IU    每 100 mL   SG POLYDEXA EAR DROPS               ← ③ 这个规格在哪些国家、叫什么
```

从两张设计稿 PNG 上量的间距（像素，按图内行 y 坐标）：

| 视口 | 行距（≈行高） | 首屏可见规格行 | 与 §C.4 目标比 |
|---|---:|---:|---|
| 1440×900 | **≈ 55 px** | ≈ 10 行（chrome 约 300 px 后开始） | ≤56 ✅ 正好压线 |
| 390×844 | **≈ 62–64 px** | ≈ 7 行 | ≤72 ✅ |

方案 ② 的**结构性优点**（都能折算成数）：
1. **「未收录」格从 73.3% 直接归零**——列表里没有格子，只有「有名字的市场」；`polymyxin` 的 16/30 空白行不再是「行」，而是「另有 N 个规格只在 X 有记录」一行字。
2. **一屏信息量**：现行矩阵 1440 首屏 3.5–6 行、390 首屏 0.5–2 行；列表 1440 ≈10 行、390 ≈7 行。
3. **行高与「剂型」同时解决**：剂型从单元格里搬到组标题/chips，规格行只剩 1 行数字 + 1 行名字。
4. **无 JS 可读天然成立**：整份列表是静态 HTML，`+N` / 「展开其余 N 个规格」用原生 `<details>`。

方案 ② 的三个风险（必须在实现前定死）：
1. **390 横向溢出**：设计稿 390 图里第二个市场名（`CA ANTIBIOTIC FO…`）在右边缘**被视口切掉**，没有省略号。这是首屏守卫指标 7（溢出必须 0）的硬违规，必须给 `.m-specrow-mk` 加 `min-width:0 + overflow:hidden + text-overflow:ellipsis`，并且一行最多 2 个市场 + `+N`。
2. **名字被裁得太狠**：设计稿 1440 把 `US Bacitracin Max Antibiotic…` 截到 ~28 字符。截断可以（有 `title`），但要保证**同一规格下 3 个市场的名字都占一行**，否则「这行到底有几个国家」又看不清。
3. **字节与回归面**：11,137 个成分页换模板 = 一次全站重建。矩阵现在是 348,358 个 `<td>` + 255,451 个「未收录」；换列表后 `<td>` 归零、但每行多 2–3 个市场标签，净字节变化需要构建后实测（预计 −5% ~ +5%，因为去掉了 73% 的「未收录」格）。

### C.4 两个方案对比 + 推荐

| 维度 | 方案 ① 矩阵收窄 | 方案 ② 规格列表 |
|---|---|---|
| 3 秒回答「剂型 / 规格 / 国家」 | 剂型在单元格里（要读每行第二行小字）；规格 3.5–6 行/屏 | 剂型 chips 一行看完；规格 10 行/屏 |
| 空格 | 靠「默认列换人 + 空行不渲染」压到 ~35% | **结构上为 0** |
| 390 行高 | 必须改成 chips（≈ 60 px）才达标 | 设计稿已 ≈62 px |
| 横向比较「同一规格 4 国名字」 | 列对齐，最强 | 行内内联，够用（附图里 US/CA 并排） |
| 改动量 | 中：改 tbody 渲染 + CSS + 排序键 | 中偏大：换渲染模板 + 全站重建 |
| 破坏「无 JS 可读」风险 | 低 | 低（全静态） |
| 与已有设计稿的关系 | 无 | **就是设计稿** |

**推荐：方案 ② 作为默认视图（v0.10.3 主线）；方案 ① 不做第二条渲染管线，只保留其中 3 条小规则到 v0.10.2 先落地**
（默认列按「有强度的记录」选、空行不渲染、单格 2 名字 + `+N`）。
理由：① 的工作量不会更小，但 73.3% 的空格只有 ② 能结构性消掉；② 已经有设计稿，改的是「一个渲染函数」而不是「两个视图」。

### C.5 若采纳 ②，v0.10.2 仍然值得先做的三件事（与结构无关，构建后立即可验）

1. `1e+06` / 千分位 / 单位写法归一（源码已有，只等一次构建）；2. `_strength_suspect` 收窄；3. 「未公开」行合并成一行 + 名字数写在行首。

### C.6 目标行高的算术（否则 ≤56 px 是空话）

| 视口 | 一行里必须放什么 | 最小高度 | 目标 |
|---|---|---:|---:|
| 1440 | 规格 1 行（24 px）+ 名字 2 行（21.6×2=43.2）+ padding 6×2 | **≈ 56 px** | ≤56 ✅ 可行（padding 8→6、`.m-brand` 去掉 `min-height:24px`） |
| 390 | 规格 1 行（24）+ 市场 chips 1 行（24）+ padding 6×2 | **≈ 60 px** | ≤72 ✅ 可行 |
| 390（**现状**：每市场一段） | 3 市场 × (标签 18 + 名字 2 行 44) | **≥186 px** | ❌ 数学上不可能 |

→ **390 ≤72 px 的前提是「手机端不再把 3 个市场竖着摊开」**（改成 chips 摘要 + `<details>` 展开）。这条是 v0.10.3 的主要工作量，也是本报告唯一「必须改结构」的地方。
注：chips 上写「US 2 · TW 1 · CN 3」，名字在详情里——**没有隐藏事实**，只是把「哪个国家有几个名字」压成一行。

---

## D. 补丁清单（函数名 + 特征串，不含行号——文件今天改过多次）

### D.1 v0.10.2 小修（只做格式化 / 空列空行 / 单格 +N / 单位写法归一；不动表格结构）

| # | 位置（函数 · 特征串） | 改什么 | 验收信号 |
|--:|---|---|---|
| 1 | `_fmt_qty()`（源码已有）；`_normalized_strength()` 的 `return f"{_fmt_qty(value)} {unit}"`；`build_drug_pages` 里 `st += f"/{_fmt_qty(pv)} {pu}"` | 确认 `1e+06` 全部走定点+千分位；`_raw_strength` 同源 | `grep -c "1e+" site/dist/drug/*.html` 合计 **0**（今天 183） |
| 2 | 新 helper `_unit_canon(unit)`，放在 `_fmt_qty` 之后 | 按 §B.1 映射 `microgram→µg`、`unit→unit`、`microlitre→µL`、`gr→g`…；在 #1 的两处拼接前后套用 | 规格串里不再出现 `microgram` / `units`（全站 0） |
| 3 | `_label_unit_html()` 的 `_RE_UNIT = re.compile(r"(?<![\w])(万iu\|microgram\|unit\|meq\|mci\|iu\|ug)(?![\w])")` | 正则扩到 `i\.u\.\|units\|u\|µg\|μg\|mcg\|micrograms`；`unit.mcg` 四语补 key（en/es=`mcg`，zh/zh-Hant=`微克`） | 四语切换后单位文字一致；`_assert_i18n_complete()` 通过 |
| 4 | `_strength_suspect(text)` | 只对**质量单位**可疑（值 ≥1e6，或 >10,000 且无 per_volume）；IU/unit/`mg·mg⁻¹` 比例的合法值不再标黄 | 待核行 11,526 → **2,738**（本报告口径） |
| 5 | `build_drug_pages` 里 `ordered = sorted(cell_brands.items(), ...)` 之后的 `ordered[:3]` 与 `if len(ordered) > 3:` | 3 → **2**；`rest_bits` 取 `ordered[2:]`；`+N` 文案保留 `class="m-more"` | 单格 `m-brand` 可见数 ≤2；≥7 名字的格 7,285 → **0** |
| 6 | `hide_empty`（`data-hide-empty="1"`）+ CSS `table.matrix tr[data-hide-empty="1"]{display:none}` | 确认这条 CSS 进了构建（**11:48 的 dist 里没有**，所以 16/30 行是空白） | 全站默认三列全空行 9,086 → **0** |
| 7 | `countries` 计算处（`countries = [c for c in COUNTRY_PRIORITY if any(...)]`） | 剔除整列无记录的市场；被剔除的市场名仍进 `hidden_rows` 提示 | 空列 95 → **0** |
| 8 | `build_drug_pages` 的 `country_totals` | 计数改成「有**强度**的品牌记录数」，不再数所有 bucket | 三页空比 82.2/71.7/86.7% → 目标 ≤35% |
| 9 | `default_cols` 循环 `for c in ([order[0]] if order else []) + ["US"] + order[1:]:` | `US` 只在 `order[:3]` 里才保留 | polymyxin 默认列 `HK·TW·US` → `CA·US·CN`（或按记录数） |
| 10 | `spec_rows.sort(key=lambda kv: (...))` | **可选塞进 v0.10.2**：把 `-freq_by_spec.get(kv[0], 0)` 从第 3 位挪到第 4 位（数值升序提到前面）。一行改动，不改结构 | 排序「10000/5000/10000/35000」→ 单调 |

CSS 小修（v0.10.2 只加不动结构）：
- `.m-brand{...min-height:24px;padding:3px 0}` → `min-height:0;padding:0;line-height:1.32`（省 8–12 px/行）。
- `table.matrix td.m-spec{white-space:nowrap}` 保留；`<b>` 里加 `title` 全文（截断时用）。
- 新增 `.m-unit-alt{display:block;font-size:13px;color:var(--muted)}`（并列提示，v0.10.3 用，v0.10.2 先建类不启用）。

**v0.10.2 能塞的东西 = 上表 1–9（+10 可选）**，全部是「同一套结构内的修」，一次构建就能验；预计三页空比降到 ≤35%、行高 1440 降到 ~60 px、`1e+` 归零、≥7 名字格子归零。

### D.2 v0.10.3 结构改动

| # | 位置 | 改什么 | 新特征串 / 类名 |
|--:|---|---|---|
| 1 | `build_drug_pages` 的 tbody 渲染 | **剂型分组**：组标题行 + 组内规格行；组标题 `<tr class="m-group" data-form="…">`，`<th colspan>` + `{n} 个规格` | `m-group` / `m-group-name` / `m-group-count` / i18n `matrix.group_count` |
| 2 | 同上 | **单位并列**：规格键从 `(st, form, rel)` 改成 `(数量, 单位类, per_volume规范, form, rel)`；一格里渲染多个写法（各自带市场小字），附 `matrix.unit_alt` 提示 | `m-unit-alt` / `m-unit-alt-mk` |
| 3 | `freq_by_spec` / `spec_rows.sort` | 新排序键函数 `_strength_order_key(spec)`：`(form_rank, unit_class_rank, 数值, -freq)` | `_unit_class_rank()` / `_strength_order_key()` |
| 4 | `default_cols` | 抽 `_default_cols(countries, spec_countries, lang_market)`，按「有强度记录数」取 3；`LANG_MARKET` 仅在与第 3 名同分时加分 | — |
| 5 | CSS `table.matrix th,table.matrix td{...padding:8px 12px;...font-size:16px;line-height:1.5}` | `padding:6px 10px`；`.m-spec` 单行（剂型移到组标题） | 1440 行高 ≤56 |
| 6 | CSS `@media (max-width:767px){ table.matrix td{display:block;...} }` | **手机端换布局**：`td[data-country]` 不展开成段，改 `.m-mkchips` 一行 chips + `<details class="m-mkdetail">` 展开名字 | `m-mkchips` / `m-mkchip` / `m-mkdetail` |
| 7 | i18n `I18N` 四语 | 新增 key（见下） | `matrix.group_count` `matrix.unit_alt` `matrix.unit_hint` `matrix.names_more` `matrix.markets_more` |
| 8 | JS `defaultCols()` / `?mk=` 解析（`var rawMk = q.get('mk') \|\| q.get('mcountry')`） | 修「加为一列」的语义：选中集 = 默认列 ∪ `mk`，而不是**替换**（实测 `?mk=CA,CN,ES` 现在把 3 列换成 3 列） | 按钮/提示文案与行为一致 |

新增 i18n key（四语同步；`_assert_i18n_complete()` 会拦住漏翻）：

```
matrix.group_count : "{n} strengths" / "{n} concentraciones" / "{n} 个规格" / "{n} 個規格"
matrix.unit_alt    : "Same number, written differently:" / "Mismo número, escrito de otra forma:" / "同一数值，写法不同：" / "同一數值，寫法不同："
matrix.unit_hint   : "IU and “units” are kept as written — we do not convert between them." / "UI y «unidades» se muestran tal como constan; no se convierten." / "IU 与「单位」按来源原文并列，两者不换算。" / "IU 與「單位」按來源原文並列，兩者不換算。"
matrix.names_more  : "+{n} more" / "+{n} más" / "另有 {n} 个" / "另有 {n} 個"
matrix.markets_more: "{n} more markets" / "{n} mercados más" / "另有 {n} 个市场" / "另有 {n} 個市場"
```

**工作量**：v0.10.2 = **S**（1 人 1 个半天，一次构建 + 一轮截图）；v0.10.3 方案 ① = **M**（结构 + 手机端新布局 + 四语 + 全站回归，约 2–3 天）；v0.10.3 方案 ② = **M**（换一个渲染函数 + 新 CSS + 复用现有设计稿，验收面同样是 11,137 页一次全量构建，见 §D.3）。

### D.3 若采纳方案 ②（规格列表）：补丁清单

矩阵渲染的函数体（`build_drug_pages` 里 tbody 那段）**不加开关、直接换实现**，旧的 `<table class="matrix">` 相关 CSS 保留一版（回滚用），并在 `CHANGELOG` 写明「矩阵 → 规格列表」。

| # | 位置（函数 · 特征串） | 改什么 | 新特征串 / 类名 |
|--:|---|---|---|
| 1 | `build_drug_pages`，从 `head = (f'<th data-i18n="matrix.spec">…` 到 `matrix_html = ('<div class="mf-slot" id="filters"></div>' '<div class="matwrap"><table class="matrix">…` 整段 | 换成列表渲染：`_spec_list_html(spec_rows, countries, ...)`；保留 `mf-slot`（筛选器挂载点）、`matrix-hidden-rows`、`matrix.original`、HK/AU 注 | `m-specwrap` / `m-specgroup` / `m-specrow` |
| 2 | 新函数 `_spec_list_html()`（紧跟 `build_drug_pages` 之前） | 剂型 chips（`_form_display` 已有四语标签）+ 计数；组标题 `_form_display(form) + n`；每行 `规格 | per_volume | 市场名` | `m-formchips` / `m-formchip` / `m-formchip-n` |
| 3 | 同上（市场名部分） | 每行最多 **2 个市场** + `+N`（`<details>`）；市场标签用 `COUNTRY_PRIORITY` 序；每个名字 `title` 全文 | `m-specrow-mk` / `m-mk` / `m-mk-n` |
| 4 | 同上（per_volume 列） | `100000 mg` → `每 100 g`（同量纲缩放，§B.1）；`mL` 保持 `每 100 mL`；**不得**折成 `%` | `m-specrow-per` |
| 5 | `spec_rows.sort(...)` | 新键 `_strength_order_key()`：`(form_rank, unit_class_rank, 数值升序, -freq)`；「未公开」永远最后 | `_strength_order_key()` / `_unit_class_rank()` |
| 6 | CSS 新增块（放在 `/* 成分页多国矩阵 */` 那段之后） | 行高：`padding:6px 0`、行距目标 55 px @1440 / 62 px @390；市场名 `min-width:0;overflow:hidden;text-overflow:ellipsis`（修设计稿 390 的右边缘裁切） | `.m-specrow{display:grid;grid-template-columns:minmax(90px,140px) 84px 1fr}` |
| 7 | `deploy/first_screen_check.py`：`PAGES` 里 drug 的 `"items": ["table.matrix tbody tr"]`、`"must_not_cover": [... "table.matrix thead", "table.matrix tbody tr .m-spec"]`、`SCROLL_PROBE` 的 `['thead','table.matrix thead']` / `['rowhead','table.matrix tbody tr .m-spec']` | 换列表后这些选择器全部落空 → 「首屏条目 0」「遮挡检查跳过」。必须同步改成 `.m-specrow` / `.m-specgroup` | 换皮与守卫同 PR |
| 8 | i18n 四语 | 上表 key + `matrix.specrow_more`（「展开其余 {n} 个规格」/「Expand {n} more」/「展開其餘 {n} 個規格」/es） | — |

> ⚠️ 第 7 条最容易漏：换掉 `table.matrix` 后，首屏守卫的「首屏可见条目数」会直接掉到 0（它按矩阵行数）。**换了渲染就必须同时改守卫**，否则 v0.10.3 的阻塞门禁会用一个错误的分母放行/拦人。

---

## E. 验收（可量化；改前 / 改后各一格）

### E.1 门槛表

| # | 指标 | 今天（dist 11:48） | v0.10.2 目标 | v0.10.3 目标（① 矩阵 / ② 列表） |
|--:|---|---|---|---|
| 1 | 三页规格行 / 其中有数据 | 30/20/120 → 14/8/84 | 不增（空行不渲染后渲染行 = 有数据行） | 同左 + 剂型分组 |
| 2 | 三页默认列可见空比 | 82.2% / 71.7% / 86.7% | **≤45%** | **≤35%** / **0**（列表没有格子） |
| 3 | 全站默认三列全空行 | 9,086（11.9%） | **0** | 0（列表里变成「另有 N 个规格」一行） |
| 4 | 全站空格比 | 73.3% | ≤70% | ≤65% / **0**（口径见下注） |
| 5 | 平均行高 @1440 / @390 | 109-148 / 251-307 | ≤72 / ≤120 | **≤56 / ≤72**（设计稿实测 55 / 62-64） |
| 6 | 首屏可见行 @1440 / @390 | 3.5-6 / 0.5-2 | ≥5 / ≥3 | **≥5 / ≥5**（设计稿 ≈10 / ≈7） |
| 7 | `1e+XX` 出现 | 42 页 / 183 处 | **0** | 0 |
| 8 | 单格 ≥7 个名字 | 7,285 格 / 1,708 页 | **0** | 0（2 名 + `+N`） |
| 9 | 同量纲并列成一行 | 428 组已合并（回归项） | ≥428（不许退化） | ≥428 + IU/unit 并列 48 组 |
| 10 | 名字截断可看全文 | `title` 已有但 66% 被裁 | 100% 有 `title` | 100% + 详情可读 |
| 11 | 四语一致 | `_assert_i18n_complete()` 通过 | 通过（新 key 四语齐） | 通过 |
| 12 | `?mk=` 可用 | 可换列（**不是加列**） | 可换列 | 加列语义修正 |
| 13 | 无 JS 可读 | 3 列 + 全部行在静态 HTML（实测） | 保持 | 保持（chips 详情用 `<details>`） |
| 14 | 「规格待核」标签 | 11,526 行 | 2,738 行 | 同左 |

> 注 4：空格比的分母是「默认可见列 × 全部行」。v0.10.3 把默认列换成有数据的市场 + 不渲染空行，分母会变小、分子更小；**不要**用「把空格藏掉」的方式刷这个数——空行/空格必须仍然能在「另有 N 个…」和 `?mk=` 之后看到。
> 注 5：首屏守卫的 drug 页型固定抽 `drug/acetaminophen.html`（`PAGES` 里的 `"paths"`），所以**上表第 5、6 项的验收页就是 acetaminophen**（今天 148 px / 3.5 行 / 390 只有 0.5 行）；它是最差样本，也是门禁样本。

### E.2 命令（可直接抄）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 0) 基准：改前跑一次（现在只有 11:48 的 dist，所以「改前」就是本文数字）
& $py deploy/first_screen_check.py --json .tmp/first-screen/before.json --pages drug --viewports 390x844,1440x900
# 1) 三页 × 两档：行数/列数/空比/行高/首屏/1e+/A-B/单位种类 + 截图
& $py .tmp/matrix-audit/probe.py site/dist .tmp/matrix-audit/after.json docs/img
& $py .tmp/matrix-audit/static.py            # 纯 HTML 口径（可 diff）
# 2) 全站：空行 / 写法归一 / 单位并列 / 待核
& $py .tmp/matrix-audit/final_scan.py        # 默认三列全空行 + 写法归一可省行
& $py .tmp/matrix-audit/sitewide.py          # 1e+ / 质量比例 / 单格名字数 / 空格比
& $py .tmp/matrix-audit/empty_cols.py        # 空列
& $py .tmp/matrix-audit/suspect.py           # 待核标签命中
# 3) 一票否决项
Select-String -Path site/dist/drug/*.html -Pattern '1e\+0?\d' | Measure-Object   # 必须 0
Select-String -Path site/dist/drug/*.html -Pattern 'mg/100000 mg' | Measure-Object  # 允许（原样保留），但必须带千分位分组
& $py tests/trilingual/run_tests.py
```

### E.3 证据文件

| 文件 | 内容 |
|---|---|
| `docs/img/matrix-polymyxin-390.png` / `-1440.png` | polymyxin 首屏（zh）：16/30 行纯空白、`10000 单位 / 5000 单位 / 10000 单位 / 35000 IU` 的顺序、`+N` |
| `docs/img/matrix-acetaminophen-390.png` / `-1440.png` | 最差样本：一行 682 px、单格 `+341`、身份行「24 个市场 · 1 条记录」 |
| `docs/img/matrix-insulin-390.png` / `-1440.png` | 20 行里 12 行无数据；`100 IU/mL` 与 `100 IU/1 mL` 各占一行 |
| `.tmp/matrix-audit/*.json` | probe / sitewide / empty_cols / mkcheck 原始数字（`.tmp/` 不入库，脚本可照 §E.2 重跑） |

---

### E.4 红线自检（每次构建都要过，5 分钟）

```text
1) 不换算数值：抽 5 个成分（polymyxin-b / insulin-human / epoetin-alfa / cholecalciferol / acetaminophen），
   把页面规格串里的数字与 DB 的 strength_value 逐条对：只允许 §B.1 的同量纲缩放（×1000 台阶），
   出现任何 IU→mg、%→mg/mL、mg/mL→% 的折算值 = 不合格。
2) 不复方折算：复方页（combo/*）的 A/B 数字不动；grep 生成物里不应出现「:1」形式的比例化简。
3) 不合并效价：36 组 IU/unit 同数值的组，页面必须仍显示两种写法（并列或两行），
   不允许只剩一个数（那就是把「单位」当成了「IU」）。
4) 原记录不丢：`class="m-orig"` 的总数不得低于改前（今天 cholecalciferol 52 处、polymyxin 7 处）。
```

---

## F. 顺带发现（不在用户 6 条里，但同屏可见）

1. **身份行数字取错列**：dist 上 `polymyxin-b` 显示「9 个市场 · 1 条记录」、`acetaminophen` 显示「24 个市场 · 1 条记录」；真值 9 市场 / 587 产品、10 市场 / 12,645 产品。源码 13:34 已改成 `len({r[0]})` / `len({r[9]})`（待构建验证）。这是「3 秒读」的第一行，错得最刺眼。
2. **`?mk=` 是「换列」不是「加列」**：`?mk=CA,CN,ES` 实测可见列 = CA/CN/ES（3 列），原默认列被换掉；而按钮文案是「把这个市场加为一列」。用户点完会以为丢了列。
3. **手机端只显示 3 列**，但 `.matwrap` 保留横向滚动条语义（`min-width:860px`）——在 390 上其实滚不动（其余列 `display:none`），提示文案「左右滑动查看更多市场」名不副实。
4. **「未公开」规格占 12.8% 的行**（11,036 行），它们按设计排在最后，但每行仍占 40–60 px 且默认列通常是空的——是「大面积未收录」的第二大来源。
5. **`acetaminophen` 顶到 120 行封顶**：273 个规格行只显示 120，`matrix.capped` 提示在矩阵下方（滚 16,000 px 才看得到）——建议把「仅显示前 120/273」提到表头。
6. **「未公开」行是名字的黑洞**：`polymyxin-b` 的 US 一列 383 个产品里 363 个没有强度，全部堆进 2 个「未公开」行（单格 165 个名字）。全站 11,036 个「未公开」行占 12.8%。建议：每个「未公开」行只显示「N 个名字 · 前 2 个 + 详情」，并把 N 写在行首。

---

## G. 没做 / 需要人拍板

- **没有构建**（常驻成员正在改 `site/build.py`，且并行纪律只允许一个会话构建）：所有「改后」数字都是**目标**，不是实测。
- **没有跑 `deploy/first_screen_check.py`**：它需要当前 dist 的 24 次扫描，本文用 `probe.py` 的 6 次扫描替代；§E.2 第 0 步留给构建后补。
- **`390 ≤72 px` 需要承认一次折中**：手机端默认不再把 3 个市场竖着摊开，改成「市场 chips + 详情展开」。这算不算「为了好看隐藏事实」，**需要 Lead 拍一句**；我的判断是不算（chips 上有每个市场的名字数，详情无 JS 可展开）。
- 方案 ② 的 `docs/img/matrix-spec-mock-{1440,390}.png` 是**另一工位 13:46 产出的设计稿**，我只读引用、没有改动，也没有替它补实现；它 390 图右边缘的裁切问题见 §C.3 风险 1。
- 「列表化 vs 矩阵」这条属于**改公开页面结构**，按 AGENTS §11 应有人拍一句再动手；我只给规格与代价，不替你定版本号。
