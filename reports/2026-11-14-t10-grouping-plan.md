# T10 方案与复现证据：规格 / 剂型 / 复方分组键（v0.11.6 前置，只读）

> 目标：把用户评审 §1.1 / §1.2 / §1.3 / §1.5 的四条根因，落成**可直接照着改**的实现方案 + 现查数字。
> 本文不写实现、不改 `site/build.py`、不写库。实现由工位 `site-ui` 做。
> **行号基线**：`site/build.py` 在本文取数期间被并行改动（13,942 → 14,121 → **14,168 行**）。下表行号是 **2026-11-14 08:40 的快照**，**会继续漂移**——请优先用「grep 锚点」列定位，行号只作参考。
> 复现命令全部只读（`db/q.py` 走 `mode=ro`；`site/dist` 产物只读）。

---

## 0. 结论先行

1. **§1.1 的归因要改一处**：成分页的行 key **已经**含剂型（`site/build.py:9347` `spec = (st.strip(), fb or df or "", rel)`），所以「500 mg / 960 mg · 片剂」**不是成分页产生的**。它来自 ① 搜索结果行 / 身份卡（索引 `s` 把强度跨剂型拼成一条、`f` 只取**第一个**剂型）② 品牌页成分卡（`strengths` 跨剂型合并）。改错地方会白改。
   现查（`site/dist/data/idx/core.json`，v0.11.5 产物）：`k=tylenol extra strength` 的索引行是 `s=["500 mg","960 mg"]`、`f="tablet"`、`n=26`、`c=["CA","US"]` → 页面必然渲染成「500 mg / 960 mg」+「片剂」，而这条名字实际有 **4 种剂型**。
2. **§1.2 根因是「三处规格串各自手搓，只有成分页拼了 per_volume」**：`per_volume_value` 在 `site/build.py` 只出现 **1 次**（`build_drug_pages`，`:9342–9346`）。品牌页（`collect_name_data` `:9775`、`_name_product_table` `:9790`）、搜索索引（`load_index` `:8666`）、明细桶（`etl/build_detail_buckets.py:201` 的 `load_strengths`）各写各的串。
   现查：`US-50580-187` = `960 mg` per `30 mL`，`form_base=liquid`，pack 里另有 `240 mL in 1 BOTTLE`；全库有 `per_volume_value` 的组件 **94,799 行 / 650,358 行（14.6%）**，单位不止 mL（见 §3.2）。
3. **§1.3 是「成分页按 (规格,剂型,释放) 聚合，未按成分集合二分」**：acetaminophen 成分页 `325 mg · tablet` 这一行里 **单方 157 条 / 复方 885 条**（active），复方名如 `APO-OXYCODONE/ACET`、`APO-TRAMADOL/ACET` 与纯对乙酰氨基酚并排，且不显示复方的其它成分与含量。全库 **2,113 个成分页**同时有单方和复方。
4. **§1.5 归整必须窄口**：全库「非整数强度」里 **2,434 行 < 1**（如 `0.00025`）、还有 `666666.666667`、`16666.67`、`2308.05` 这类合法长尾。宽口径归整会毁数据。本文给的口径（`v≥1 且 |v−round(v)|≤0.01 且相对偏差≤2e-5`）只影响 **137 行 / 54 个值（AU+CA）**，**含全部 41 个 500.x 案例**，其余一行不动。
5. 体积/行数影响面已量化：成分页行数 **48,565 → 63,406（+30.6%）**；搜索索引 `core.json` 现 **43.15 MB raw**（发布护栏 50 MB），本方案预估 **+1.5～2.0 MB**，仍在护栏内但**必须在 build 后复测**。

---

## 1. 现状定位（函数 + 行号 + 当前 key 组成）

### 1.1 聚合与渲染位置（行号 @08:40 / 14,168 行；**以 grep 锚点为准**）

| # | 行号 | grep 锚点 | 当前 key / 行为 | 缺陷 |
|---|---|---|---|---|
| A | `:9230` | `def build_drug_pages` | 成分页主循环 | — |
| A1 | `:9342–9347` | `st = _normalized_strength(sv, su)` / `spec = (st.strip(), fb or df or "", rel)` | `if pv: st+=f"/{pv} {pu}"`；**key=(st, fb or df, rel)** | key 含剂型✅，但**不含成分集合**→复方混入；`pu` 未分类（见 §3.2） |
| A2 | `:9494` | `freq_by_spec = {` / `spec_rows.sort(` | 常用度 + `_spec_num` 排序 | 只取首个数字 |
| A3 | `:9530` | `st_html = _label_unit_html(st) if st else (` | 规格单元格 + `matrix.spec_check` 徽标 | 徽标已存在 → 可复用给「名称-规格冲突」 |
| A4 | `:10161` | `LIST_ROWS_PER_BLOCK = 12` | 每国块 ≤12 行 + 折叠 | 行数护栏，改动要沿用 |
| A5 | `:10187 / :10301–10316` | `def _drug_list_html` / `def _spec_chip` / `shown = specs[:10]` | 折叠摘要每剂型 ≤10 chip | **会吃掉 960 mg/30 mL**（§5.4 现查已证实） |
| B | `:8581` | `def load_index` | 搜索索引 | — |
| B1 | `:8666` | `st = f"{_fmt_qty(sv)} {su or ''}".strip()`（在 `a["s"].append(st)` 前） | `a["s"]` 收强度串 | **无 per_volume、无 mg 归一** |
| B2 | `:8643` 附近 | `f = form_base or dosage_form` → `a["f"].append(f)` | 剂型列表 | 记录了但没用全 |
| B3 | `:8781–8782` | `"s": a["s"][:6],` / `"f": a["f"][0] if a["f"] else "",` | 输出到索引 | **强度跨剂型拼一条；剂型只留第一个** ← §1.1 直接根因 |
| C | `:9751` | `def collect_name_data` | 品牌页成分卡数据 | — |
| C1 | `:9756 / :9775` | `"""SELECT pn.key_id, p.product_id, s.inn_en, ...` / `st = f"{_fmt_qty(sv)} {su or ''}"` | 每 (名字,成分) 收 `s:set` | **无 per_volume** |
| C2 | `:9842 / :9895` | `def build_name_pages` / `strengths = '、'.join(sorted(g['s'],` | 成分卡「Strength: 500 mg、960 mg」 | 强度集合跨剂型/跨市场合并 |
| C3 | `:9783` + `:9790` 附近 | `def _name_product_table` | 单包装明细表 `st=f"{_fmt_qty(sv)} {su}"` | 同样丢 per_volume |
| D | `:9050` | `def _strength_suspect` | `val>=1e6` 或 `val>1e4` 且非 u/%/ml → True | 只抓数量级荒谬（400064g），抓不到 499.9996 |
| E | `:9104` | `def _normalized_strength` | 重量单位→mg（`_WEIGHT_TO_MG`），>100000 mg 保留原单位 | **显示与分组同源 → 加归整的正确位置** |
| F | `:9120 / :9153 / :9160` | `def _strength_raw_map` / `def _raw_strength` / `def _strength_origin_html` | 原记录取 `data/sources/unit_normalization_20261030.csv`，缺则回退 `f"{_fmt_qty(sv)} {su}"` | 归整后自动显示「原记录 499.9996 mg」✅ 无需新代码 |
| G | `:9192` | `def _form_display` | 受控词 i18n；`effervescent` 按来源原文补亚型 | 单值函数，够用 |
| H | `:10043` | `def _family_block` | 同品牌其他市场列表（签名已被并行改动加 `data=None`） | **与分组无关**（T12 范围），别动 |
| I | `:10850` | `def _sort_strength` | `re.match(r"([\d.]+)")` | 只认首个数字 → 改用 `_spec_num`（`:9453`） |
| J | `:5329 / :5364 附近` | `function brandRowHTML` / `const ds = (e.s &&` | 结果行规格 = `e.s` 排序后 `join(' / ')` | 渲染「500 mg / 960 mg」 |
| K | `:5559 / :5589–5591` | `function identityCardHTML` / `strengths.join(' / ')` | `Dose: …` + `formLabelOf(e)`=`e.f` | 渲染「500 mg / 960 mg」+ 单一剂型「片剂」 |
| L | `:5441` | `function formLabelOf` | 取 `e.f`（单值） | 同上 |
| M | `:12056` | `def _lang_block_text` | 四语内联说明（`lang-block`） | 新段标题/说明走它，勿新造机制 |

### 1.2 规格串生成点（全站 5 处，必须收敛成 1 个函数）

| 调用点 | grep 锚点 | 现状 | 含 per_volume | 含单位归一 |
|---|---|---|---|---|
| ① 成分页（矩阵行 + 列表行 + chip） | `spec = (st.strip(), fb or df or "", rel)` | `_normalized_strength` + 手拼 `/pv pu` | ✅ | ✅ |
| ② 品牌页成分卡 | `def collect_name_data` 内 `st = f"{_fmt_qty(sv)} {su or ''}"` | 手拼 | ❌ | ❌ |
| ③ 品牌页单包装明细表 | `def _name_product_table` 内 `st = f"{_fmt_qty(sv)} {su}"` | 手拼 | ❌ | ❌ |
| ④ 搜索索引 → 结果行 / 身份卡 | `"s": a["s"][:6],`（消费方 `function brandRowHTML` / `function identityCardHTML`） | 手拼 | ❌ | ❌ |
| ⑤ 明细桶（详情面板） | `etl/build_detail_buckets.py` `def load_strengths` | `f"{sv:g} {su}"` + `" + "` 连接，per_volume 用**空格**拼 | ✅（`"500 mg 5 ml"`） | ❌ |

> ⑤ 属 `etl/`，不在 T10 写权限（`site/build.py` / `tests/` / `reports/`）内 → 本轮**只标注**：详情面板已含体积关系（用户看到的「960 mg 30 mL」就是它），只是分隔符与归整不同。要统一需另开任务改 etl，**不要**在 build.py 里用正则去拆 ⑤ 的串。

---

## 2. 新分组键方案（成分页）

### 2.1 key 定义

```python
# 现状（site/build.py:9347）
spec = (st.strip(), fb or df or "", rel)

# 方案：只加一维 others_sig（其余成分签名），不动前三维
spec = (st.strip(), fb or df or "", rel, others_sig)
```

`others_sig` **只放「除本页成分以外」的成分**，按 `substance_id` 排序后拼：

```python
# others_sig 生成（per product，一次预扫，不逐行查库）
# 期望形状："hydrocodone-bitartrate@5 mg|caffeine@30 mg"
others_sig = "|".join(f"{sid}@{_spec_text(sv, su, pv, pu)}"
                      for sid, sv, su, pv, pu in comps[pid] if sid != page_sid)
```

为什么只放「其他成分」而不是完整成分集合：

- **单方产品的 key 与今天逐字相同**（`others_sig=""`）→ 6,311 个纯单方成分页（123,445 产品）零回归；
- 「仅含此成分 / 含此成分的复方」二分 = `others_sig == ""`，不需要第二套判定（§5）；
- 复方行天然带「其他成分 + 各自含量」，满足 §1.3「复方行显示全部活性成分与各自含量」；
- 品牌 / 名称**不进 key**（名称仍是 `bucket[label]` 的键、仍然只是格子里的候选，符合底线①）。

### 2.2 排序列

```python
spec_rows.sort(key=lambda kv: (
    kv[0][0].strip() == "",                    # 未公开规格最后（保留）
    suspect_by_spec.get(kv[0], False),         # 规格待核最后（保留）
    kv[0][3] != "",                            # 新增：单方在前、复方在后
    len(kv[0][3].split("|")) if kv[0][3] else 0,  # 复方内：成分少的在前
    -freq_by_spec.get(kv[0], 0),
    _form_rank(kv[0][1]),
    -_spec_num(kv[0][0]),
    kv[0][1], kv[0][2], kv[0][3],
))
```
末位补 `(form, rel, others_sig)` 保证**全序**。这一条必须有：`build_name_pages` 里已有同类先例注释——`g['s']` 是 `set`，`_sort_strength` 只比数值，并列时退回 set 迭代顺序（受 `PYTHONHASHSEED` 影响），曾让 109 个名字页两次构建逐字节不同。新 key 的最后一个分量同样要做全序兜底，否则第二次构建可能出现行序抖动。

### 2.3 组头文案规则（多剂型时禁止单一剂型）

规则（服务端与客户端同一条，避免两套）：

1. 取该名字/该行涉及的**剂型集合** `forms`（去重、按 `_form_rank`）。
2. `len(forms) == 1` → 显示该剂型名（`_label_html('form', ...)`）。
3. `len(forms) >= 2` → **禁止**输出单一剂型；显示 `多剂型：片剂 / 胶囊`（前 2 个）+ ` 等 N 种`，i18n 键 `matrix.multi_form`。
4. 规格与剂型**必须成对**出现：`(剂型, 规格)` 对，最多 3 对，超出 `+N`。
5. 只有「该名字下所有产品共享同一 `(剂型, 规格, per_volume)`」时才允许合并成一条。

### 2.4 影响面（现查）

```sql
-- 现查：48,565 行 → 63,406 行（+30.6%）
WITH rows AS (
  SELECT v.substance_id AS sid, p.product_id, p.form_base, p.release,
         pc.strength_value AS sv, pc.strength_unit AS su
  FROM product p
  JOIN product_component pc ON pc.product_id = p.product_id
  JOIN variant v ON v.variant_id = pc.variant_id
  WHERE p.status = 'active'
), sets AS (
  SELECT pc.product_id, GROUP_CONCAT(v.substance_id,'+') AS sig
  FROM product_component pc JOIN variant v ON v.variant_id = pc.variant_id
  GROUP BY pc.product_id
)
SELECT COUNT(DISTINCT rows.sid||'|'||rows.sv||'|'||COALESCE(rows.su,'')||'|'
             ||COALESCE(rows.form_base,'')||'|'||COALESCE(rows.release,'')||'|'||sets.sig) AS new_rows,
       COUNT(DISTINCT rows.sid||'|'||rows.sv||'|'||COALESCE(rows.su,'')||'|'
             ||COALESCE(rows.form_base,'')||'|'||COALESCE(rows.release,'')) AS cur_rows
FROM rows JOIN sets ON sets.product_id = rows.product_id;
-- → cur_rows 48565 / new_rows 63406
```
acetaminophen 单页：**223 → 740** 行（同一条 SQL 换成 `WHERE v.substance_id='acetaminophen'`）。

---

## 3. 统一规格渲染函数（`960 mg/30 mL` 保留关系）

### 3.1 API（新增，放在 `def _strength_origin_html`（`:9160`）之后）

```python
def _spec_text(sv, su, pv=None, pu=None) -> str:
    """强度 + 每单位基数 → 全站唯一规格串（只做显示，不改数据）。

    - 无 per_volume：沿用 _normalized_strength（重量单位归一到 mg）
    - 有 per_volume：拼 "{强度}/{每基数} {单位}"，如 "960 mg/30 mL"
    """
    s = _normalized_strength(sv, su)
    if s and pv is not None:
        s += f"/{_fmt_qty(pv)} {(pu or '').strip()}".rstrip()
    return s


def _spec_kind(pu: str) -> str:
    """per_volume 单位分类：volume / mass / time / count。只用于加属性与排序，不改文案。"""
    u = (pu or "").strip().lower()
    if u in ("ml", "l", "cl", "dl"):                      return "volume"
    if u in ("mg", "g", "mcg", "ug", "μg", "µg", "kg"):   return "mass"
    if u in ("h", "hours", "d", "day", "days"):           return "time"
    return "count"                                        # tablet/dose/sachet/actuation/unit/ampoule/mm/cm/um
```

`_spec_text` 与旧行为**逐字节等价**于成分页今天的 `:9342–9346`（先 `_normalized_strength`、再 `+= "/pv pu"`），所以 ① 号调用点替换后页面不变；变化全部来自 ②③④ 开始调用它。

### 3.2 `per_volume` 不是只有 mL（决定文案能否统一用 `/`）

现查（`SELECT per_volume_unit, COUNT(*) FROM product_component WHERE per_volume_value IS NOT NULL GROUP BY 1 ORDER BY 2 DESC`）：

| 类 | 单位（行数） | 语义 | 文案 | 例 |
|---|---|---|---|---|
| volume | `mL` 79,554 · `L` 11 | 浓度 | `960 mg/30 mL` | `US-50580-187` |
| mass | `mg` 13,666 · `g` 782 · `mcg` 4 | 每份基质 | `500 mg/950 mg`（+pack 说明「.95 g in 1 PACKET」） | `US-50580-209` |
| count | `tablet` 140 · `unit` 54 · `dose` 46 · `sachet` 16 · `actuation(s)` 170 · `ampoule` 7 | 每剂量单位 | `0.4 mg/tablet` | `ES-76248` |
| time | `h` 312 · `hours` 2 · `d` 14 | 速率 | `7 mg/24 h` | `US-76282-781` |
| 尺寸 | `mm` 17 · `cm` 3 · `um` 1 | 装置尺寸 | `2 mm/15 mm` | `US-84545-215` |

合计 **94,799 行**（`per_volume_value IS NOT NULL`），按 `country` 分布：US 35,942 · CN 31,885（CN 全部 31,885 个产品都有，多为 1 个每瓶总量）· GB 11,702 · FR 5,239 · CA 3,942 · ES 3,153 · AU 1,611 · SG 1,093 · MX 125 · TW 107。

**方案**：全部用同一个 `/` 连接（不造第二套模板），但在 HTML 上加 `data-spec-kind` 属性（`volume|mass|count|time`），供 CSS/JS 与后续 T15 抽检；`mass` 类必须同时可见 pack 文本（成列已有 pack 位置），否则 `500 mg/950 mg` 会被读成比值。**不做**任何「每袋含多少 mg」的换算。

### 3.3 包装总量（第三个维度，别混进规格）

`US-50580-187` 的 `pack = "1 BOTTLE in 1 CARTON (50580-187-08)  / 240 mL in 1 BOTTLE"` 已含总量；`_name_product_table` 与明细面板都有 pack 列。**规格串里不拼包装总量**（否则 `960 mg/30 mL/240 mL` 无法阅读）。只在 pack 列/详情保持原文。

### 3.4 调用点改造清单（before / after）

| 调用点 | before | after |
|---|---|---|
| ① 成分页 `:9342–9347` | `st=_normalized_strength(sv,su)` + `if pv: st+=f"/{_fmt_qty(pv)} {pu}"` | `st=_spec_text(sv,su,pv,pu)`（等价，顺手把 `raw_st` 同步为 `_spec_text` 版本 + `_strength_raw_map` 覆盖） |
| ② 品牌页成分卡 `:9775` | `st=f"{_fmt_qty(sv)} {su}".strip()` → `s["s"].add(st)` | 先按剂型分桶：`s["fs"][form].add(_spec_text(sv,su,pv,pu))`（`pv/pu` 需在 `collect_name_data` 的 SQL 里补两列，`def collect_name_data`（`:9756`）的 SELECT 加 `pc.per_volume_value, pc.per_volume_unit`） |
| ③ 单包装明细表 `:9790` | `st=f"{_fmt_qty(sv)} {su}".strip()` | 行里带 per_volume：`single_rows` SQL（`:9858`）加两列，改用 `_spec_text(...)` |
| ④ 搜索索引 `:8666` | `st=f"{_fmt_qty(sv)} {su}"` → `"s"`；`"f": a["f"][0]` | 拆成两列：`"s"`=去重后的规格串（含 per_volume，最多 6，供兼容），新增 `"fs"`= `[[form, [spec,...]], ...]` 最多 4 组；`"f"` 改为 `a["f"][0] if len(a["f"])==1 else "multi"`；`load_index` 的 SELECT（`:8608`）需加 `pc.per_volume_value, pc.per_volume_unit` |
| ⑤ 明细桶 | `"500 mg 5 ml"`（空格） | **本任务不改**（`etl/`），记为 T10b；详情面板已含关系，仅格式不同 |
| 排序 | `_sort_strength`（`:10850`） | 直接 `from _spec_num`（`:9453` 内已有实现）→ 提成模块级 `_spec_num()`，两处共用 |

**搜索两处的渲染规则**（服务端只给数据，客户端按 §2.3 规则出文案）：

- `brandRowHTML` 规格单元格（`:5346`）：`e.fs` 存在时渲染 `片剂 500 mg · 液体 960 mg/30 mL`，超过 3 组加 `+N 种剂型`；`formLabelOf` 不再用于这一格。
- `identityCardHTML` 剂型字段（`:5589–5591`）：`len(e.fs) > 1` → `matrix.multi_form`（多剂型：X / Y 等 N 种），否则单一剂型；规格字段改为 `剂量 500 mg · 960 mg/30 mL`。

### 3.5 体积预算

`site/dist/data/idx/core.json` 现 **43.15 MB raw**（发布护栏 raw 11–50 MB，`AGENTS.md` §6）。现查：**24,279** 个 trade name key 至少有一条 per_volume 产品（`s` 变长），**59,930** 个 key 有 ≥2 个 `(剂型,规格)` 对（`fs` 新增），其中 17,211 个 ≥4 对。按每 key 平均 +24 B 估 `fs` ≈ **+1.4 MB**，`s` 变长 ≈ **+0.2 MB** → 预估 44.7 MB。**build 后必须复测**；若超 48 MB，`fs` 上限从 4 组降到 3 组。

---

## 4. 精度归整规则（499.9996 → 500）

### 4.1 规则（只改显示层，写在 `_normalized_strength` 里 = 显示与分组同源）

```python
def _snap_strength(v: Decimal) -> Decimal:
    """显示归整：仅当值≥1 且同时满足「绝对≤0.01」与「相对≤2e-5」时取整到 round(v)。

    499.9996 → 500；500.0082 → 500；0.00025 不动；666666.666667 / 2308.05 不动。
    原始值不动：_raw_strength() 仍取审计 CSV / 原始 numeric，页面小字显示「原记录 …」。
    """
    if v is None or v < 1:
        return v
    r = v.to_integral_value(rounding=ROUND_HALF_UP)
    if abs(v - r) <= Decimal("0.01") and abs(v - r) <= Decimal("0.00002") * r:
        return r
    return v
```
调用顺序（`_normalized_strength` 内）：`num = Decimal(str(value)) * factor` 之后、`_fmt_decimal(num)` 之前套 `_snap_strength`。

### 4.2 影响面（现查）

```sql
SELECT COUNT(*) AS rows_aff, COUNT(DISTINCT ROUND(strength_value,6)) AS vals,
       GROUP_CONCAT(DISTINCT p.country) AS mks
FROM product_component pc JOIN product p ON p.product_id = pc.product_id
WHERE pc.strength_value >= 1 AND pc.strength_value <> ROUND(pc.strength_value)
  AND ABS(pc.strength_value - ROUND(pc.strength_value)) <= 0.01
  AND ABS(pc.strength_value - ROUND(pc.strength_value)) <= 2e-5 * ROUND(pc.strength_value);
-- → rows_aff 137 / vals 54 / mks AU,CA
```
含用户看到的全部 6 个 500.x 值（`499.9996`×31、`499.9995`×2、`500.0003`×1、`500.0053`×3、`500.0081`×2、`500.0082`×2 = **41 行**，与 triage §1.5 一致），另含 `160.001`、`320.001`、`299.9997`、`149.9998`、`250.003`、`79.9987` 等同族 AU/CA 转换噪声。

放宽档（去掉相对门槛，只 `|dev|≤0.01` 且 `v≥1`）：**325 行 / 138 个值**，会把 `469.01→469`、`242.01→242`、`262.99→263` 一起改掉。**建议用窄档**；宽档仅在这些值经 T15 确认是转换噪声后才可提。

### 4.3 反例保护（这就是不能宽口径的原因）

| 值 | 出现 | 若宽口径的结果 | 结论 |
|---|---|---|---|
| `0.00025` / `0.0001` / `0.008`… | **2,434 行 < 1 且 < 0.01** | → `0`，数据被抹平 | **`v>=1` 硬门槛必须有** |
| `666666.666667`、`16666.67`、`2308.05`（US，30 行） | 数十行 | dev 分别 0.333 / 0.33 / 0.05，均 >0.01 | 绝对门槛已挡 ✅ |
| `790.02`（dev 0.02）、`909.09`（dev 0.09）、`469.01`（dev 0.01，rel 2.1e-5） | 十数行 | 宽档会改成 790 / 909 / 469 | 绝对或相对门槛挡掉 ✅（这也是**不能去掉相对门槛**的原因：绝对门槛单独放过 469.01） |
| `100.008`（AU，9 行） | dev 0.008 ✓、rel 8e-5 > 2e-5 → **不动** | 仍是 `100.008 mg` | 归 T15 清单，不在显示层硬修 |

> 实测：窄档命中的值域是 **7.0 – 680.0 mg**（无 1e5 以上的值），所以不需要额外加「大值不归整」的特例。

### 4.4 可追溯（不需要新代码）

`_raw_strength()`（`:9153`）在审计 CSV 无记录时回退 `f"{_fmt_qty(sv)} {su}"` = `"499.9996 mg"`；归整后 `display="500 mg"` ≠ raw → `_strength_origin_html`（`:9160`）自动输出「原记录: 499.9996 mg」。**数据层不动**：`product_component.strength_value` 与 `datapackage.json` 仍是 499.9996。

---

## 5. 成分页单方 / 复方二分

### 5.1 判定（一条，别造第二套）

```python
is_combo = others_sig != ""      # 见 §2.1：成分集合是否恰为该成分
```
等价 SQL（现查用的就是这个口径）：

```sql
WITH acet AS (SELECT DISTINCT pc.product_id FROM product_component pc
                JOIN variant v ON v.variant_id = pc.variant_id
               WHERE v.substance_id = 'acetaminophen'),
n AS (SELECT p.product_id, p.status,
             (SELECT COUNT(*) FROM product_component c2 WHERE c2.product_id = p.product_id) AS ncomp
      FROM product p JOIN acet a ON a.product_id = p.product_id)
SELECT CASE WHEN ncomp = 1 THEN 'mono' ELSE 'combo' END AS kind, status, COUNT(*) AS n
FROM n GROUP BY kind, status;
```

### 5.2 文案与结构

- 段标题：`drug.mono_section`「仅含此成分」/ `drug.combo_section`「含此成分的复方」（四语见 §9）。
- **某侧为空就不渲染该段**（`combo_only` 有 2,527 个成分页，多为防晒/复方制剂；`mono_only` 6,311 个）。空标题会凭空多出 2,527 个标题。
- 复方行：名后跟「完整成分 + 各自含量」，数据来自一次预扫 `comps: dict[pid, list[(sid, inn, zh, strength_text)]]`（`product_component ⋈ variant ⋈ substance` 全表一次，650,358 行，构建期内一次即可）。
- **保留**现有「同类 ≠ 可互换」提示与 `collision`/`dose_warning` 结论；**新增的只是身份信息（成分与含量）**，不判断能否互换、不做剂量换算、不求和。

### 5.3 现查计数

| 成分页 | 单方（active） | 复方（active） | 备注 |
|---|---|---|---|
| **acetaminophen** | **4,911** | **5,256** | `325 mg·tablet` 这一行：单方 157 / 复方 885 |
| octisalate | 3 | 3,849 | 几乎纯复方 |
| avobenzone | 1 | 3,257 | 同上 |
| octocrylene | 1 | 3,181 | 同上 |
| homosalate | 3 | 2,980 | 同上 |
| hydrochlorothiazide | 313 | 2,891 | |
| zinc-oxide | 2,312 | 2,462 | |
| titanium-dioxide | 422 | 2,314 | |

全库成分页（active 口径）：**单方 6,311 页 / 复方 2,527 页 / 混 2,113 页**（共 10,951 页）。全库 `>1` 成分的产品 **70,783 / 494,992（14.3%）**。

acetaminophen 复方里最常见的搭档（去重产品数）：Dextromethorphan HBr 1,453 · Caffeine 1,420 · Phenylephrine 1,354 · Pseudoephedrine 1,242 · Chlorpheniramine 801。

### 5.4 体积护栏（必须照做）

acetaminophen 页现在 **156.3 KB**（110 个 `li.mkrow` + 57 个折叠组 + 11 个剂型 chip，12,438 个成分页平均 12.3 KB / 合计 149 MB）。
两段后行数 223→740，若全渲染会翻倍。**沿用既有护栏**：`LIST_ROWS_PER_BLOCK=12` **按「每国 × 每段」各算 12 行**，其余进「其余规格 N 个 · 涉及 M 种剂型」折叠；复方段另设 `COMBO_ROWS_PER_BLOCK=8`。目标：acetaminophen 页 ≤ 240 KB（+55% 上限），构建后实测。

**另一处现查缺陷（顺手修，很重要）**：`960 mg/30 mL` 那一行在 v0.11.5 的 acetaminophen 页**根本没有出现**（`grep -c '960' = 0`）。原因：每国块只渲 12 行 + 折叠摘要每剂型只列前 10 个 chip（`:10313`），液体规格多，被裁掉。所以 §1.2 的修复**必须同时**保证「每剂型至少保留一个浓度型（`spec_kind=volume`）规格可见」，例如：折叠摘要里先出该剂型的 1 个最小 + 1 个最大 + 1 个带 per_volume 的规格。

---

## 6. 名称-规格冲突的显示口径（T15 出清单，这里只定显示）

### 6.1 冲突判定口径（给 T15，避免假阳性）

**只能在同一 `name_key` 内「单一规格」时判定**，否则会把多规格键全打成冲突。现查反例：

| key | 产品数 | 不同规格数 | 规格集合 |
|---|---|---|---|
| `panadol` | 13 | **4** | `160/325/500/1000 mg` |

而 raw `PANADOL TABLET 500 mg` 挂在 `panadol` 这个键上 → 朴素做法会报「名说 500、结构化 160」（`US-0135-0537` 是 160 mg 液体），**这是假阳性**。

建议判定式（T15 落 CSV，只读）：
1. 只取 `name_type='trade'` 且该 key 下**所有单方产品共享唯一 `(strength_value, strength_unit)`**（现有 75,612 个 key 满足）；
2. 解析该 key 的每条 `name_variant.raw` 里的「数字 + 单位」（`mg|g|mcg|ml|iu|ui|%`）；
3. 与 key 的唯一规格比对（同单位族换算后比数值，比值容差 1e-6）；
4. 不一致 → 出 `(key_id, raw, 名称里的数, key 规格)`。

粗筛下限（现查，供 T15 复核量级）：满足 1 的 75,612 个 key 里，**1,625 个**的 raw 里出现了 ≠ 自身规格的 mg 数字。全库含剂量 token 的 trade name variant **62,901 / 207,934（30.3%）**。

### 6.2 显示口径（3 条，不判断谁对）

1. 规格单元格**保留原值**（不改数字、不改单位、不参与分组键变化）。
2. 追加徽标：`<span class="tag warn" data-i18n="matrix.spec_conflict">` + `title="名称写作 1000 mg"`（title 文本取 T15 清单里的 raw 片段，**原文照抄、不翻译**）。
3. 排序上**不**降到「规格待核」那一档（那条给数量级荒谬用，`:9050` `_strength_suspect`）；冲突项只在原位加标记，位置不变，避免整页顺序抖动。

### 6.3 before / after

- before：`250 mg 片剂`（名称写 `… 1000 mg …`，页面无任何提示）
- after：`250 mg 片剂` + 徽标 `规格待核实`，`title="名称写作 1000 mg"`，数值不变；T15 清单里可复核。

---

## 7. before / after 文案样例（5 条，可直接当验收对照）

**A. 搜索结果行 · `tylenol extra strength`（26 产品 / CA+US）**

- before：规格列 `500 mg / 960 mg`（索引 `s`），无剂型
- after：`片剂 500 mg · 胶囊 500 mg · 液体 960 mg/30 mL` + `+1 种剂型`（散剂 `500 mg/950 mg`）

**B. 身份卡（搜索首屏）· 同一查询**

- before：`Dose 500 mg / 960 mg` + `片剂`
- after：`剂型 多剂型：片剂 / 胶囊 / 液体 / 散剂`；`剂量 500 mg（片剂/胶囊）· 960 mg/30 mL（液体）· 500 mg/950 mg（散剂）`，超出 3 组时 `+N`

**C. 品牌页成分卡 · `/name/tylenol-extra-strength.html`**

- before：`Form: capsule、liquid、powder、tablet · Strength: 500 mg、960 mg`
- after：`剂型: 胶囊、液体、散剂、片剂 · 规格（按剂型）: 片剂 500 mg；胶囊 500 mg；液体 960 mg/30 mL；散剂 500 mg/950 mg`

**D. 成分页 · `/drug/acetaminophen.html` 的 325 mg 片剂**

- before：一行 `325 mg · tablet` 里单方 157 + 复方 885 混排，复方只显示名（如 `APO-OXYCODONE/ACET`）
- after：
  - 段 `仅含此成分`：`325 mg · tablet` → 157 条单方
  - 段 `含此成分的复方`：`325 mg · tablet` 下 885 条，每行显示「全部活性成分 + 各自含量」，如 `APO-OXYCODONE/ACET` → `羟考酮 5 mg + 对乙酰氨基酚 325 mg`（现查 `CA-02324628` 的 `ord` 0/1 两行）

**E. 精度 · 41 个 AU 组件 / `499.9996 mg`**

- before：`499.9996 mg`（并参与排序/分组）
- after：`500 mg` + 小字 `原记录: 499.9996 mg`；与真实 `500 mg` 合并到同一行（因为归整发生在分组键之前）

---

## 8. 改动点清单（函数级，给 `site-ui`；行号为 08:40 快照，**以 grep 锚点为准**）

| 序 | 位置（grep 锚点） | 改什么 | 依赖 |
|---|---|---|---|
| 1 | `def _normalized_strength`（`:9104`） | 内联 `_snap_strength`（§4.1） | 无 |
| 2 | 新增 `_spec_text` / `_spec_kind`，放 `def _strength_origin_html`（`:9160`）之后 | §3.1 两个纯函数 | 1 |
| 3 | `def build_drug_pages`（`:9230`；`spec = (st.strip()...`/`freq_by_spec`） | key 加 `others_sig`（§2.1）；排序（§2.2）；`_spec_text` 替换；`_spec_kind` 出 `data-spec-kind` | 2 |
| 4 | `def build_drug_pages` 预扫 | 新增一次 `product_component ⋈ variant ⋈ substance` 全表读建 `comps[pid]`（`sid, inn, zh, sv, su, pv, pu, ord`）；可与 `:9249` 那条 products SQL 合并省一次扫描 | 无 |
| 5 | `def build_drug_pages` 渲染段 | 单方/复方两段 + 段标题 + 空段不渲（§5）；`COMBO_ROWS_PER_BLOCK=8` | 3,4 |
| 6 | `def _drug_list_html`（`:10187`）、`def _spec_chip`（`:10301`，`shown = specs[:10]`） | 段内复用；折叠摘要改「每剂型保留最小/最大/一个浓度型」（§5.4） | 5 |
| 7 | `def collect_name_data`（`:9751`；SQL `:9756`、`st = f"{_fmt_qty(sv)} {su or ''}"`） | SELECT 补 `pc.per_volume_value, pc.per_volume_unit`；`s["s"]` → `s["fs"][form]`，用 `_spec_text` | 2 |
| 8 | `def build_name_pages`（`:9842`；`strengths = '、'.join(sorted(g['s'],`） | 成分卡规格按剂型分组（§7-C）；`_sort_strength`→`_spec_num` | 7 |
| 9 | `def _name_product_table`（`:9783`） | SQL 补两列 + `_spec_text` | 2 |
| 10 | `def load_index`（`:8581`；SQL `:8608`、`st = f"{_fmt_qty(sv)} {su or ''}"`、`"s": a["s"][:6]`、`"f": a["f"][0]`） | SQL 补两列；`"s"` 用 `_spec_text`；新增 `"fs"`（≤4 组）；`"f"` 多剂型时给 `"multi"` | 2 |
| 11 | JS `function brandRowHTML`（`:5329`）、`function identityCardHTML`（`:5559`）、`function formLabelOf`（`:5441`） | 按 `e.fs` 出「剂型 + 规格」对，多剂型走 `matrix.multi_form`（§2.3） | 10 |
| 12 | `def _sort_strength`（`:10850`） | 改为复用 `_spec_num`（`:9453`，提成模块级） | 无 |
| 13 | `I18N = {`（`:190`）等四语 dict | 新增 5 个键（§9） | 无 |
| 14 | 行属性 | 补 `data-others="<sig>"`、`data-spec-kind="volume|mass|count|time"`（不新增可见文案，便于抽检/测试） | 3 |

**不要动**：`def _family_block`（`:10043`，T12 范围，且已被并行改签名）、`etl/build_detail_buckets.py`（不在写权限；另开 T10b）、`collision` 视图（底线②）。

---

## 9. i18n 新增键（四语，追加到 `I18N` 各语 dict）

| key | en | es | zh | zh-Hant |
|---|---|---|---|---|
| `matrix.multi_form` | `Multiple dosage forms` | `Varias formas farmacéuticas` | `多剂型` | `多劑型` |
| `drug.mono_section` | `Only this ingredient` | `Solo este principio activo` | `仅含此成分` | `僅含此成分` |
| `drug.combo_section` | `Combination products containing this ingredient` | `Combinaciones que contienen este principio activo` | `含此成分的复方` | `含此成分的複方` |
| `matrix.spec_conflict` | `strength unverified` | `concentración sin verificar` | `规格待核实` | `規格待核實` |
| `name.form_spec` | `Strength by dosage form` | `Concentración por forma` | `规格（按剂型）` | `規格（按劑型）` |

> 中文/繁中/西语三处都要落（`AGENTS.md` §5「页面文案 zh/en/es 三语同步」；本站另有 zh-Hant，沿用现有四语习惯）。

---

## 10. 自验清单（`site-ui` 交付时逐条跑）+ 残余缺口

**必须先跑**：`& $py site/build.py` 到 `== done ==`；`deploy/first_screen_check.py` 改前 / 改后各一次并写数字。

| # | 检查 | 命令 / 判定 |
|---|---|---|
| 1 | 索引行已分组 | 读 `site/dist/data/idx/core.json`：`k=tylenol extra strength` 的 `fs` 有 4 组、`s` 含 `960 mg/30 mL` |
| 2 | 品牌页卡 | `grep -c '960 mg/30 mL' site/dist/name/tylenol-extra-strength.html` ≥1，且 `Strength:` 后不再出现 `500 mg、960 mg` 形态 |
| 3 | 成分页浓度行 | `grep -c '960 mg/30 mL' site/dist/drug/acetaminophen.html` ≥1（现为 0） |
| 4 | 归整生效 | `grep -ro '499\.9996 mg' site/dist/drug/ \| wc -l` 应只剩「Recorded as/原记录」小字里出现；规格单元格里应是 `500 mg`（抽 3 页人工看）。**不许**出现 `499.9996` 作为 `data-spec` 或 `mkst` 的内容 |
| 5 | 单复方两段 | acetaminophen 页含两个段标题，且 mono 段无 `APO-OXYCODONE` 类复方名 |
| 6 | 行数/体积 | acetaminophen 页 ≤ 240 KB（现 156.3 KB）；12,438 页平均 ≤ 16 KB |
| 7 | 索引体积 | `core.json` raw ≤ 48 MB（现 43.15 MB）；超了把 `fs` 上限降到 3 组 |
| 8 | 确定性 | 连续两次 build，`grep -c` 类断言与页数不变；`dist` 逐字节 diff 为空（排序末位补全序） |
| 9 | 三语抽检 | `?lang=zh|en|es`（+zh-Hant）看两组段标题 + `多剂型` 文案 |
| 10 | 不回归 | `tests/trilingual/run_tests.py` 0 failures；`& $py -m unittest discover -s lib -t lib` |

**残余缺口（照实记）**

- ⑤ 明细桶（详情面板）仍是 `960 mg 30 mL`（空格）+ `%g` 不归整 → 需另开任务改 `etl/build_detail_buckets.py`（写权限外）。
- `100.008 mg` 等 9 行 AU 转换噪声按窄口规则仍原样显示 → 交 T15 清单。
- 名称-规格冲突只给口径与量级（单规格键 75,612 / 粗筛候选 1,625），**清单由 T15 出**；本轮不标注任何一条为「错」。
- `panadol` 这类多规格键（13 产品 / 4 规格）必须排除在冲突判定外，否则假阳性成片 —— 已写进 §6.1。

---

## 11. 复现命令清单（全部只读，可逐条复跑）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'

# 0.1 案例一：US-50580-187
& $py db/q.py "SELECT p.product_id,p.country,p.dosage_form,p.form_base,p.release,p.pack,pc.ord,pc.strength_value,pc.strength_unit,pc.per_volume_value,pc.per_volume_unit,s.inn_en FROM product p JOIN product_component pc ON pc.product_id=p.product_id JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id WHERE p.product_id='US-50580-187'"
# → liquid / 960 mg / 30 mL / pack 含 240 mL

# 0.2 案例二：tylenol extra strength 剂型构成
& $py db/q.py "SELECT p.form_base,p.dosage_form,pc.strength_value,pc.strength_unit,pc.per_volume_value,pc.per_volume_unit,COUNT(*) n FROM name_key nk JOIN product_name pn ON pn.key_id=nk.key_id AND pn.name_type='trade' JOIN product p ON p.product_id=pn.product_id LEFT JOIN product_component pc ON pc.product_id=p.product_id WHERE nk.norm='tylenol extra strength' GROUP BY 1,2,3,4,5,6 ORDER BY n DESC"
# → tablet 500×23 / capsule 500×1 / liquid 960+30mL×1 / powder 500+950mg×1；CA 2 + US 24

# 0.3 案例三：acetaminophen 单复方
#   见 §5.1 的 SQL → combo 6,973 / mono 5,902（全状态）；active: 5,256 / 4,911

# 1 索引实测（v0.11.5 产物，取 s / f / n）
& $py -c @"
import json
C = json.load(open('site/dist/data/idx/core.json', encoding='utf-8'))['cols']
i = [j for j, k in enumerate(C['k']) if k == 'tylenol extra strength'][0]
g = lambda c: (C[c]['d'][C[c]['i'][i]] if isinstance(C[c], dict) else C[c][i])
print(C['k'][i], g('n'), g('s'), g('f'), g('c'))
"@
# → tylenol extra strength 26 ['500 mg', '960 mg'] tablet ['CA', 'US']

# 2 per_volume 单位分布（§3.2）
& $py db/q.py "SELECT COALESCE(per_volume_unit,'(null)') pu, COUNT(*) rows FROM product_component WHERE per_volume_value IS NOT NULL GROUP BY pu ORDER BY rows DESC"

# 3 归整影响面（§4.2）
& $py db/q.py "SELECT COUNT(*) rows_aff, COUNT(DISTINCT ROUND(strength_value,6)) vals FROM product_component WHERE strength_value>=1 AND strength_value<>ROUND(strength_value) AND ABS(strength_value-ROUND(strength_value))<=0.01 AND ABS(strength_value-ROUND(strength_value))<=2e-5*ROUND(strength_value)"
# → 137 / 54

# 4 per_volume 占比（§0-2）
& $py db/q.py "SELECT COUNT(*) total, SUM(per_volume_value IS NOT NULL) has_pv FROM product_component"
# → 650358 / 94799

# 5 索引 / 页面体积（§3.5、§5.4）
#   core.json 43.15 MB raw；acetaminophen.html 156.3 KB；12,438 个成分页 149.0 MB；dist 929.0 MB
```
