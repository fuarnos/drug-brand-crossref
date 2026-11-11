# P0-2 只读定位：明细面板「品牌」栏显示成包装描述（`1 BOTTLE…` / `2/50/100…`）

- 日期：2026-11-12（北京时间窗口）
- 工位：phaseb-data（task-3）；**只读定位，未写 `data/drugs.db`、未改 `site/build.py`、未建站、未发布**
- 用户原话（`docs/下一轮优先级-20261111.md` §1）：`Tylenol Extra Strength` 详情「品牌」栏出现 `1 BOTTLE…` 包装描述、`2/50/100…` 数量列表
- 结论一句话：**不是 ETL 错位，数据是对的；是呈现层一行下标写错——「品牌」列取的是包装字段**
- 修复量：`site/build.py` 改 **1 个字符**（`r[3]` → `r[2]`）+ 加 1 条防回归单测

---

## 1. 结论（先看这段）

1. **根因**：`site/build.py` 里渲染「结果行 → 展开明细」面板的函数 `detPanelHTML()`，
   品牌单元格写成了 `const brandCell = r[3] ? esc(r[3]) : esc(T('brand.none'));`。
   明细行是 12 元组，`ROW_FIELDS` 定义在 `etl/build_detail_buckets.py`：
   `[0]=product_id, [1]=country, **[2]=brand**, **[3]=pack**, [4]=approval_id, …`。
   —— 取 `r[3]` 等于把 **包装字段** 塞进「品牌」列；同一行的「包装」列也是 `r[3]`（那列是对的），
   所以用户看到「品牌」和「包装」两列内容一模一样。
2. **不是 ETL、也不在市场解析**：`product.pack` 里装的是真包装（US=openFDA packaging 描述、
   CA=DPD `packaging.product_information`、CN/AU/TW 各自的包装原文），
   `product_name` 里的 trade 名（`TYLENOL EXTRA STRENGTH`）完整无损。用户猜的「源字段按位置解析错位」
   方向对，但错位发生在**前端读数组下标**这一步，不在入库解析。
3. **线上已中招**：`site/dist/assets/app.js`（v0.11.1 发布产物）第 360 行与
   `https://drugcrossref.com/assets/app.js` 第 364 行都是同一句 `r[3]`。
4. **影响面（线上明细桶实测，非估算）**：382,035 条明细行里 **232,353 条（60.8%）** 的「品牌」列
   显示的是包装原文，覆盖 **121,560 / 196,211 个 key（62.0%）**；
   另有 **138,460 条** 因包装为空而误显示「无商品名」（实际有商品名），覆盖 79,231 个 key（40.4%）。
5. **同一个字符还修掉另一半症状**：ES / GB / HK / MX / SG / EU 这些来源没有包装字段的市场，
   明细面板里「品牌」列**全部**显示「无商品名」（如 ES 的 `NOLOTIL`，实测 ES 37,948 行、GB 36,982 行、
   MX 13,433 行、HK 12,772 行、SG 5,147 行、EU 2,095 行）——改完后这些位置显示真实商品名。
   注意这是**明细面板**的症状，和 P0-1（分片索引 / 完整索引字段映射）不是同一处代码，别合并处理。
6. **今天没做的事**：改 `build.py`、重建 `site/dist`、发布。按仓库单写窗口纪律，留给
   site-ui / 单写窗口执行；本报告给出改动、dry-run 探针与验收步骤。

---

## 2. 复现

### 2.1 CLI（说明错位不在数据/检索层）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py cli.py "Tylenol Extra Strength"
```

```
query = 'Tylenol Extra Strength'  ->  norm = 'tylenol extra strength'  strengths=[]  keys=5
 1. TYLENOL EXTRA STRENGTH  [US]  Acetaminophen  500 mg  tablet  ×21  score=0.775 (exact)
 2. TYLENOL EXTRA STRENGTH  [CA]  Acetaminophen  500 mg  tablet  ×2  score=0.775 (exact)
 3. TYLENOL EXTRA STRENGTH  [US]  Acetaminophen  960 mg/30 mL  liquid  ×1  score=0.775 (exact)
 4. TYLENOL EXTRA STRENGTH  [US]  Acetaminophen  500 mg  capsule  ×1  score=0.775 (exact)
 5. TYLENOL EXTRA STRENGTH  [US]  Acetaminophen  500 mg/950 mg  powder  ×1  score=0.775 (exact)
 …（prefix 命中略）
```

CLI 只读检索层，看不到「品牌列」；**这本身就说明候选集与身份没问题**，问题出现在网页的展开面板。

### 2.2 数据库原始值（只读 `mode=ro`，`.tmp/p02_probe.py`）

```powershell
& $py .tmp\p02_probe.py "Tylenol Extra Strength"
```

```
  CA-00559407    CA  type=trade prim=1 raw='TYLENOL EXTRA STRENGTH'
      pack='2/50/100/130/150/200/230/325'          mah='KENVUE CANADA INC.'
  US-50580-451   US  type=trade prim=1 raw='TYLENOL EXTRA STRENGTH'
      pack='1 BOTTLE, PLASTIC in 1 CARTON (50580-451-50)  / 50 TABLET, COATED in 1 BOTTLE, PLASTIC'
      mah='Kenvue Brands LLC'
```

`product_name` = 商品名，`product.pack` = 包装，`product.mah` = 厂家，三者都正确、没有互换。

### 2.3 前端实际渲染（问题现场）

明细桶（线上同款 `site/dist/data/idx/detail-*.json`）解码 + 按 `detPanelHTML()` 的下标模拟，
即用户点结果行「详情」后看到的那张表：

```
市场 | 「品牌」列渲染值（= r[3] = pack）              | 「包装」列渲染值（= r[3]）
CA   | 2/50/100/130/150/200/230/325                   | 2/50/100/130/150/200/230/325 · 500 mg
CA   | (brand.none →「无商品名」)                      | — · 500 mg
US   | 1 BOTTLE, PLASTIC in 1 CARTON (50090-0005-0)…  | 1 BOTTLE, PLASTIC in 1 CARTON (50090-0005-0)…
US   | 1 BOTTLE in 1 CARTON (50580-187-08)  / 240 mL… | 1 BOTTLE in 1 CARTON (50580-187-08)  / 240 mL…
```

`1 BOTTLE…` 与 `2/50/100…` 正好是用户报的两个值 → 复现成立。

---

## 3. 故障链（谁把包装放进了品牌列）

```
etl/build_detail_buckets.py  SELECT p.pack …  ROW_FIELDS = [product_id, country, brand, pack, …]
        │  写 site/dist/data/idx/detail-<bucket>.json：k[key] = [[pid, country, brand, pack, …], …]
        ▼
site/build.py  detPanelHTML(payload, key, e, T)          ← 读数组下标
        │  const brandCell = r[3] ? esc(r[3]) : esc(T('brand.none'));   ← 错：r[3] 是 pack
        │  … `<td>${esc(r[3]) || '—'}${strength}</td>`                   ← 对：r[3] 是 pack
        ▼
结果页 4 列表「详情」按钮 → `<tr class="detrow"><td class="detcell">` 面板
        表头：市场 | 品牌 | 包装 | 批准号 | 状态 | 来源 | 厂家
```

定位信息：

| 位置 | 内容 |
|---|---|
| 当前工作区 `site/build.py:4288` | `const brandCell = r[3] ? esc(r[3]) : esc(T('brand.none'));`（行号因其他工位未提交改动漂移 +32） |
| `HEAD`（`git show HEAD:site/build.py`） | 第 4256 行，同一句 |
| `site/dist/assets/app.js:360`（v0.11.1 产物） | 同一句 |
| 线上 `https://drugcrossref.com/assets/app.js:364` | 同一句（已核实，2026-11-12） |
| 字段定义 | `etl/build_detail_buckets.py:96-98` `ROW_FIELDS`，`[2]=brand`、`[3]=pack` |
| 引入提交 | `989d9c38e`（2026-10-29，v0.9.0「大类 v2 + 矩阵 3 列…」）——明细面板首次上线就带着这个下标 |

同一函数的其它列（市场 `r[1]`、包装 `r[3]`、批准号 `r[4]`、厂家 `r[9]`、来源 `r[11]`）都对，
**只有品牌这一列错位**，所以是一处孤立的下标笔误，不是整行错位。

---

## 4. 为什么能排除「ETL 解析错位」

| 检查 | 结果 |
|---|---|
| `brand` 来源 | US `openFDA NDC.brand_name`（`etl/ingest_openfda_ndc.py:302`）、CA `DPD drugproduct.brand_name`、其余市场各自来源；均为**按字段名取值**，非按列位置切分 |
| `pack` 来源 | US `NDC.packaging[].description`（`ingest_openfda_ndc.py:311-314`）、CA `packaging.product_information`（`ingest_ca_dpd.py:366-367,499`）、CN/AU/TW 各自包装原文 |
| `2/50/100/130/150/200/230/325` 出处 | `data/raw/ca/dpd/packaging.json` 里 `drug_code=5255`（DIN `00559407`）原样一条：`{"package_size": "", "product_information": "2/50/100/130/150/200/230/325"}` —— **就是 DPD 的包装字段**，不该进 `product_name` |
| 反向核查：`pack` 里混进商品名 | 23 行，逐条看全是「品牌词本身出现在包装描述里」（`Penthrox`、`Gripe Water`、`Swab`），不是错位 |
| 反向核查：`pack` 里混进厂家名 | 7 行，是 `mah` 本身存成了 NDC labeler 数字码（见 §8 顺带发现），与 pack 无关 |
| 结论 | **数据层无错位**；`product_name`（trade 名）/ `product.pack`（包装）/ `product.mah`（厂家）三者边界清晰 |

> 关于「哪个市场 ingest」：本仓库的 `etl/markets/` 目录目前只有 `nl.py`（荷兰，名称/成分层，
> `schema.sql` 的 `country` 枚举里还没有 NL，也不写 `product` 行）；真正的市场入库脚本都在
> `etl/ingest_*.py`（US `ingest_openfda_ndc.py`、CA `ingest_ca_dpd.py`、CN `ingest_nhsa.py`、
> AU `ingest_artg_*.py`/`ingest_pbs.py`、TW `ingest_tw_tfda.py`、ES `ingest_cima.py` …）。
> 本次逐个看过 brand/pack 两条赋值路径，都是**按字段名取值或按该字段自身内容拼装**
> （US `brand_name` / `packaging[].description`、CA `brand_name` / `packaging.product_information`、
> CN `pack_of(row)` 取「最小包装单位」等字段、AU ARTG `Pack Size`、AU PBS 从 form 串 `split_pack()`、
> TW `包裝`、ES CIMA 无包装字段），
> 没有「按列位置切分整行」的解析，因此不存在把品牌/厂家串到包装列的路径。

---

## 5. 影响面（线上明细桶实测）

统计口径：`site/dist/data/idx/detail-*.json`（51 个桶，v0.11.1 构建产物）逐行解码，
`r[3]` 非空 →「品牌」列显示包装原文（`bad_brand`）；`r[3]` 空而 `r[2]` 非空 → 误显示「无商品名」（`false_none`）。

```
& $py .tmp\p02_stats.py
```

| 市场 | 品牌错位（行） | 误显示「无商品名」（行） | 真无商品名（行） | 该市场明细行合计 |
|---|---:|---:|---:|---:|
| US | 79,710 | 249 | 27 | 79,986 |
| CN | 59,443 | 3 | 0 | 59,446 |
| TW | 32,388 | 139 | 0 | 32,527 |
| AU | 30,416 | 20,041 | 0 | 50,457 |
| CA | 30,396 | 9,651 | 0 | 40,047 |
| ES | 0 | 37,948 | 1 | 37,949 |
| EU | 0 | 2,095 | 0 | 2,095 |
| GB | 0 | 36,982 | 11,157 | 48,139 |
| HK | 0 | 12,772 | 0 | 12,772 |
| MX | 0 | 13,433 | 37 | 13,470 |
| SG | 0 | 5,147 | 0 | 5,147 |
| **合计** | **232,353** | **138,460** | 11,222 | **382,035** |

- key 级：**121,560 / 196,211（62.0%）** 的 key 至少有一行品牌错位；**79,231（40.4%）** 至少有一行误显示「无商品名」。
- 按来源：`openfda_ndc` 79,710 / `nhsa` 59,443 / `tfda_tw` 32,388 / `hc_dpd` 30,396 / `artg_export` 20,413 / `pbs` 9,522 / `artg_detail` 344 / `artg_enrich` 137 行错位；`cima`、`dmd`、`cofepris_mx`、`hk_dh` 无包装字段 → 全是「假无商品名」。
- DB 全量口径（`product` 表，479,193 个产品）：**330,832 个产品有 `pack`（69.0%）**，
  它们只要被展开明细就必然错位；线上桶每 key 最多 12 行，所以页面可见 232,353 行，全量对不上是截断所致，不是统计口径差。

```sql
-- 分市场：有包装 / 无包装（DB 全量，mode=ro）
SELECT COALESCE(country, region) AS mk,
       SUM(pack IS NOT NULL AND TRIM(pack) <> '') AS with_pack,
       SUM(pack IS NULL OR TRIM(pack) = '')      AS no_pack,
       COUNT(*)                                  AS n
FROM product GROUP BY mk ORDER BY n DESC;
```

| 市场 | 有包装 | 无包装 | 合计 |
|---|---:|---:|---:|
| CN | 145,048 | 3 | 145,051 |
| US | 109,783 | 396 | 110,179 |
| GB | 0 | 61,051 | 61,051 |
| AU | 26,372 | 18,422 | 44,794 |
| CA | 33,242 | 10,605 | 43,847 |
| ES | 0 | 25,395 | 25,395 |
| TW | 16,387 | 70 | 16,457 |
| HK | 0 | 13,935 | 13,935 |
| MX | 0 | 10,878 | 10,878 |
| SG | 0 | 5,511 | 5,511 |
| EU | 0 | 2,095 | 2,095 |
| **合计** | **330,832** | 148,361 | **479,193** |

---

## 6. 抽样 22 条（含用户复现的 2 条，全部与 DB 对拍 `pack` 一致）

> 「现状」= 现在网页「品牌」列显示的内容；「修复后」= 同位置的 trade 名（`product_name`，`name_type='trade'`）。

| # | 市场 | 明细 key | product_id | 现状「品牌」列（= pack） | 修复后「品牌」列 | DB 对拍 |
|---|---|---|---|---|---|---|
| 1 | CA | `tylenol extra strength` | `CA-00559407` | 2/50/100/130/150/200/230/325 | TYLENOL EXTRA STRENGTH | ✓ |
| 2 | US | `tylenol extra strength` | `US-50090-0005` | 1 BOTTLE, PLASTIC in 1 CARTON (50090-0005-0) / 24 TABLET, FILM COATED in 1 BOTTLE | TYLENOL EXTRA STRENGTH | ✓ |
| 3 | US | `1 0% camphor` | `US-44224-1665` | 1 CYLINDER in 1 BOX (44224-1665-1) / 1 g in 1 CYLINDER | After Bite Natural | ✓ |
| 4 | US | `2 0% lidocaine burn` | `US-43473-097` | 59.1 mL in 1 BOTTLE, SPRAY (43473-097-02) | 2.0% LIDOCAINE BURN | ✓ |
| 5 | US | `4 in look ginseng … essence` | `US-85977-001` | 30 mL in 1 BOTTLE (85977-001-01) | 4 IN LOOK Ginseng Anit wrink Anti wrinkle essence | ✓ |
| 6 | US | `5 adhesive bandages 2 antibiotic ointments` | `US-66715-7021` | 1 KIT in 1 BAG (66715-7021-9) * .5 g in 1 POUCH | First Aid Kit, Lil Drug Store | ✓ |
| 7 | CN | `埃万妥单抗注射液` | `CN-XL01FXA418B00-4b3b2a21` | 1型玻璃西林瓶，用胶塞和带易掀盖铝盖密封，1瓶/盒 | 锐珂 | ✓ |
| 8 | CN | `奥妥珠单抗注射液` | `CN-XL01XCA356B00-ca56994d` | 西林瓶装，1瓶/盒 | 佳罗华 | ✓ |
| 9 | CN | `桉柠蒎肠溶胶囊` | `CN-XR05CBA101E00-31cdc333` | 铝塑，12粒/盒 | 切诺 | ✓ |
| 10 | CN | `氨咖麻敏胶囊` | `CN-XR05XXA177E00-020db49c` | 铝箔，6粒/盒 | 元顺 | ✓ |
| 11 | CA | `a 10000 i u` | `CA-01984144` | 100 | A 10000 I.U | ✓ |
| 12 | CA | `b 100 complex` | `CA-02243923` | 90 | B-100 COMPLEX | ✓ |
| 13 | CA | `c 1000` | `CA-00663395` | 100 | C-1000 | ✓ |
| 14 | CA | `d 12043 conc electrolyt pour dialy` | `CA-00703397` | 4/4.5l | D-12043 CONC ELECTROLYT POUR DIALY | ✓ |
| 15 | AU | `0 02% w v chlorhexidine acetate … ahf7981` | `AU-ARTG-19459` | 500mL AHF7980, 100mL AHF7976, 1000mL AHF7981 | 0.02% w/v Chlorhexidine Acetate Aqueous Antiseptic Solution AHF7980/AHF7981 | ✓ |
| 16 | AU | `3 4% magnesium chloride … intravenous` | `AU-ARTG-171154` | 500mL x 18 | 3.4% magnesium chloride hexahydrate and 4.8% calcium chloride dihydrate Intravenous Infusion | ✓ |
| 17 | AU | `6% dextran 70 in 0 9% sodium chloride fkb` | `AU-ARTG-19429` | 500mL x 15 | 6% Dextran 70 in 0.9% Sodium chloride 500mL injection FKB5013G | ✓ |
| 18 | AU | `e coxip etoricoxib blister pack` | `AU-ARTG-281552` | 30 Tablets, 10 tablets | E-COXIP etoricoxib 120 mg tablet blister pack | ✓ |
| 19 | TW | `傲朴舒膜衣锭10毫克` | `TW-TFDA-000034-50de3867` | PVC/PE/PVDC鋁箔盒裝 | OPSUMIT | ✓ |
| 20 | TW | `安与持續性药效锭150毫克` | `TW-TFDA-057963-32a90bef` | 塑膠瓶裝;;AL-AL鋁箔盒裝 | Anbutrine XL 150mg Tablets | ✓ |
| 21 | TW | `昂力膜衣锭100毫克` | `TW-TFDA-059273-acdda5af` | PVC/PVDC-AL鋁箔盒裝;;塑膠瓶裝(HDPE) | Uppu Film-Coated Tablets 100mg | ✓ |
| 22 | TW | `癌並通膜衣锭250毫克` | `TW-TFDA-028683-73407d1d` | ALU-PVC-PE-PVDC鋁箔盒裝;;HDPE塑膠瓶裝 | ABIRATERONE SANDOZ TABLETS 250MG | ✓ |

生成命令：`& $py .tmp\p02_sample20.py`（输出同时写 `.tmp/p02-sample20.md`）。
「假无商品名」示例（同一行代码造成）：`detail-n.json` 的 `nolotil` → `mk=ES brand='NOLOTIL' pack=''`
→ 现在「品牌」列显示「无商品名」。

---

## 7. 修复方案

### 7.1 改动（1 行）

```diff
--- a/site/build.py
+++ b/site/build.py
-    const brandCell = r[3] ? esc(r[3]) : esc(T('brand.none'));
+    const brandCell = r[2] ? esc(r[2]) : esc(T('brand.none'));
```

（`HEAD:site/build.py:4256`；当前工作区 `site/build.py:4288`。只改这一处，其它列不动。）

顺带说明：改完后「包装」列仍显示 `r[3]`，两列不再重复；包装为空的 key 会显示真实商品名而不是「无商品名」。
**不涉及 `db/schema.sql` / `etl/**` / `lib/**`**，因此不需要重跑入库、不需要 DB 备份。
明细桶本身也不用重建：`etl/build_detail_buckets.py` 产的 `data/idx/detail-*.json`（51 个桶 / 60.9 MB，
2026-11-10 10:42）不动，`site/build.py:12494` 只是把它们拷进 `site/dist/data/idx/`。

### 7.2 防回归（建议同批加，1 个小单测）

新建 `tests/test_detail_row_fields.py`（本工位不落这个文件，交给实现窗口）：

```python
"""明细面板的列下标必须跟 etl/build_detail_buckets.py 的 ROW_FIELDS 对齐。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 从 ROW_FIELDS 里取真实下标的唯一真相源
src = (ROOT / "etl" / "build_detail_buckets.py").read_text(encoding="utf-8")
fields = re.search(r"ROW_FIELDS = \[(.*?)\]", src, re.S).group(1)
ROW_FIELDS = [s.strip().strip('"') for s in fields.replace("\n", " ").split(",") if s.strip()]

build = (ROOT / "site" / "build.py").read_text(encoding="utf-8")
def idx_of(var: str) -> int:
    return int(re.search(rf"const {var} = r\[(\d)\]", build).group(1))

assert idx_of("brandCell") == ROW_FIELDS.index("brand")   # 现在会失败（3 != 2）
assert ROW_FIELDS.index("pack") == 3
```

要点：断言的是「**下标来自 ROW_FIELDS 的 index**」，以后 `ROW_FIELDS` 再变形（例如插字段）
也会立刻红，而不是等下一个人肉眼查。

### 7.3 dry-run 验证方法（改前 / 改后各跑一次，不需要建站、不需要起服务）

探针 `.tmp/p02_render_check.js`：从 `site/build.py` 里**抽出 `detPanelHTML()` 函数原文**，
用真实明细桶数据在 Node 里跑一遍，解析回表格单元格，比对「品牌」列取的是 `r[2]` 还是 `r[3]`。

```powershell
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'

# 改前（当前 HEAD 行为）→ 期望 exit 1、判定「仍错位」
& $node .tmp\p02_render_check.js "tylenol extra strength"

# 改后（把改好的 build.py 复制到 .tmp 再跑，用于改代码前先验证方案；实改后直接跑上面那条）
& $node .tmp\p02_render_check.js "tylenol extra strength" ".tmp/p02-build-fixed.py"
```

已实测（本次就是拿 `.tmp/p02-build-fixed.py` 当「改后」副本，仓库文件未动）：

```
改前：判定：品牌列 = 本行包装原文 11 行 / 品牌列 = 本行商品名 0 行（共 12 行）→ 仍错位 [exit 1]
改后：判定：品牌列 = 本行包装原文  0 行 / 品牌列 = 本行商品名 12 行（共 12 行）→ 已修   [exit 0]
      表内容：CA | TYLENOL EXTRA STRENGTH | 2/50/100/130/150/200/230/325 · 500 mg | 00559407
             US | TYLENOL EXTRA STRENGTH | 1 BOTTLE, PLASTIC in 1 CARTON (50090-0005-0)… | 50090-0005
```

跨市场复验（4 个 key，改前 1 / 改后 0）：

| key | 市场 | 改前错位行 | 改后错位行 |
|---|---|---:|---:|
| `abraxane` | CN | 3 / 6 | 0 / 6 |
| `a 10000 i u` | CA | 1 / 1 | 0 / 1 |
| `e coxip etoricoxib blister pack` | AU | 4 / 4 | 0 / 4 |
| `a a c` | TW | 1 / 1 | 0 / 1 |

（探针只读 `site/build.py` + `site/dist/data/idx/detail-*.json`，不写任何文件。）

### 7.4 实改后的验收（按 AGENTS §5 站点类改动）

1. `& $py site/build.py` 跑到 `== done ==`（明细桶数据不变，只需重生成 JS/页面）。
2. `& $node .tmp\p02_render_check.js "tylenol extra strength"` → exit 0。
3. `Select-String site\dist\assets\app.js -Pattern "brandCell = r\[2\]"` 命中；`r\[3\]` 版为 0 命中。
4. `& $py deploy/first_screen_check.py` 改前/改后各一次，把数字写进当批报告。
5. 三语各抽 3 条检索（含 `Tylenol Extra Strength`），确认明细面板「品牌 / 包装」两列不再重复。
6. `& $py deploy/ci_checks.py --fast`（dist-integrity 等）；发布走 `deploy/publish.ps1` + `sync_r2.ps1` 双通道。
7. 发布后用 `deploy/verify_live.py --expect-version vX.Y.Z` 两个域名各验一次；
   再抽 `https://drugcrossref.com/assets/app.js` grep `brandCell = r[2]`。

---

## 8. 回滚清单草案（给执行窗口）

代码侧（本次修复只动这里）：

1. 改动前记录：`git rev-parse HEAD`、`site/build.py` 的 SHA1、`p02_render_check.js` 改前输出。
2. 本地兜底副本：改前 `Copy-Item site\build.py .tmp\build.py.p02-before`（`.tmp/` 已在 gitignore）。
3. 单点回滚：`git checkout -- site/build.py`（若已提交则 `git revert <fix-commit>`），然后
   `& $py site/build.py` 重建到 `== done ==` —— **不要手工改 `site/dist/`**。
4. 产物回滚：`site/dist` 是生成物；如需回到上一版线上，按 DEPLOY 流程用上一个 tag 的构建产物重发，
   先 `deploy/publish.ps1 -DryRun`。
5. 数据侧：**本次不写库、不动 `data/drugs.db`、不重跑 ingest**，因此不需要 DB 备份/还原；
   若同批任务另外动库，按 `run_all.py` 的自动备份（`data/backups/`，保留 5 份）另行记录。

判定回滚的触发条件（任一）：

- 改后 `ci_checks --fast` 出现 FAIL；
- 三语抽检里有任一语言的明细面板表头与内容错列；
- `verify_live.py` 有 failure；
- 明细桶 `detail-*.json` 行数/`checksums.txt` 异常变化（理论上不该变，变了说明动到了数据层）。

---

## 9. 顺带发现（本工位未处理，供排期参考）

1. **`mah` 偶尔存成 NDC labeler 数字码**（如 `US-70541-128` 的 `mah='70541'`、`US-73453-112` 的 `mah='73453-112'`），
   页面「厂家」列会显示一串数字。属数据质量，量级小（本次反向核查只撞到 7 条），与 P0-2 无关。
2. **openFDA `brand_name` 有非品牌值**：`US-85443-208` 的 trade 名就是 `208`、`US-87066-5912` 是 `87066-5912`、
   `US-68599-8630` 是 `Swab`。这会让「品牌」列即使修好也显示怪值——属 P0-1/P0-3 那条线（名称清洗），不是本工位范围。
3. **`pack` 过长**：1,671 个产品的 `pack` 超过 120 字符（US openFDA 多层包装最长的上百字符），
   明细面板「包装」列会撑行。修完 P0-2 后建议给该列加 `<col>` 限宽或截断 + `title` 全文。
4. **`2/50/100…` 这类数量列表的归属**（task 问的）：它来自 `product.pack`，
   **不该进 `product_name`**——商品名不是包装，进了 `product_name` 会污染检索键与同名页。

---

## 10. 本次没做 / 还剩什么

- ❌ 没改 `site/build.py`（只读工位，且 build.py 正被其它工位改动：`git diff --stat site/build.py` = 59 insertions / 27 deletions，未提交）。
- ❌ 没建站、没发布、没写 `data/drugs.db`（用 `mode=ro` 只读连接；`db/q.py` 是可写连接，本次改用自写只读脚本）。
- ✅ 剩给执行窗口：① 改 1 个字符 → ② 加 §7.2 单测 → ③ 建站到 `== done ==` → ④ §7.4 验收 → ⑤ 双通道发布 + `verify_live`。
- ⚠️ 线上当前（v0.11.1）仍是错的，修复要等一次正常发布，不要单独热推 `assets/app.js`。

## 附：本次用到的脚本与产物（都在 `.tmp/`，不入库）

| 文件 | 用途 |
|---|---|
| `.tmp/p02_probe.py` | 只读查 Tylenol Extra Strength 的 product / product_name / pack / mah 原始值 |
| `.tmp/p02_stats.py` | 51 个明细桶逐行统计影响面；输出 `.tmp/p02-stats.json` |
| `.tmp/p02_detail_repro.py` | 按 `ROW_FIELDS` 解码 + 模拟 `detPanelHTML()` 渲染，复现错位 |
| `.tmp/p02_sample20.py` | 生成 §6 的 22 条抽样（输出 `.tmp/p02-sample20.md`） |
| `.tmp/p02_pack_samples.py` | 各市场 `pack` 样本 + `pack` 混入品牌/厂家的反向核查 |
| `.tmp/p02_render_check.js` | 源码级 dry-run 探针（改前 exit 1 / 改后 exit 0） |
| `.tmp/p02-build-fixed.py` | `site/build.py` 的副本，仅把 `r[3]`→`r[2]`，用于验证修复方案（仓库文件未动） |
