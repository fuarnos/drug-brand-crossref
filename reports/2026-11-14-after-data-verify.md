# 改后数据级对账：v0.11.6 `site/dist` 页面事实 vs `data/drugs.db`（只读）

> 日期：2026-11-14（北京）｜任务：task-7｜工位：phaseb-data
> 前置（构建侧给的）：`site/dist` 已是 v0.11.6 产物 —— **125,515 文件 / 992,410,495 B / HTML 125,290 / 0 字节 0**、
> `data/idx/core.json` raw **46,295,974 B**、`index.html` 含 `v0.11.6 · 2026-11-14`。本次复算全部只读。
> **不看截图**（视觉归 atc4-ui），只做「页面上的数字/分组/成分能不能被库复算出来」。

## 结论先行

**数据层与页面一致：4 项全部 PASS，0 条硬 FAIL。**

| # | 检查 | 结论 | 关键数字 |
|---|---|---|---|
| 1 | 精度归整（74 行） | **PASS** | 59 行被构建期归整，页面主规格全部是整数（55 行页面可见 + 4 行该组未渲染）；**0 行「原值当主规格」**；全库 `drug/`+`name/` 93,323 文件里 `499.9996` / `500.0081` / `500.0082` **各 0 次** |
| 2 | per_volume `960 mg/30 mL` | **PASS** | `drug/` 1 文件×3、`name/` 3 文件×1、`data/` 6 文件×14（其中 `core.json`×5）；3 个「同名多剂型」key 的品牌页剂型-规格 = 库 |
| 3 | 单方/复方归属（3 页 × 5+5 行） | **PASS** | 单方 15 行**全部**成分数 = 1；复方 15 行**全部** >1 且页面列出的成分+含量与库逐项一致 → **30/30** |
| 4 | 索引 `f` / `fs` / `s`（5 个 key） | **PASS** | 5/5；`fs` 的每组规格都是库规格集合的子集（有 3 个/组的上限，见 §4 说明） |

两个**不是错、但要知道**的口径差，写在 §5：① 15 行我的清单建议归整、构建期窄口（相对 2e-5）不归整 → 页面保留 `100.008 mg` 这类原值；② 索引 `fs` 每组只放前 3 个规格，具体哪 3 个取决于构建期 SQL 顺序，**不可由库精确复算**（只有包含关系可复算）。

## 复算方法（怎么做到"独立"）

不 import `site/build.py`（避免复用它的函数就等于照着它的结果抄），而是**照它的显示口径在自己的只读脚本里重写一遍**，再拿页面产物反查：

| 复刻的口径 | 规则 | 出处 |
|---|---|---|
| 归整 `_snap_strength` | `v ≥ 1` 且 `|v − 整数| ≤ 0.01` 且 `≤ 2e-5 × 整数` → 取整 | `site/build.py:483804` |
| 规格串 `_spec_text` | 重量单位先换算到 mg（g/kg/mcg/µg），再加 `/每基数 单位` | `site/build.py:9315` |
| 索引打包 `_fs_pack` | 剂型→规格分桶，≥2 个剂型才写；**每组最多 3 个规格、最多 3 组** | `site/build.py:9373` |
| 成分页分组 | 行键 = (规格, 剂型, 释放, 其它成分签名)，单方/复方分段 | `site/build.py:9759` |

复算脚本放在 `.tmp/`（gitignore，不入库）：`_v_lib.py`（口径复刻 + core.json 解码）、`_v_prec2.py`、`_v_seg5.py`、`_v_idx2.py`、`_v_name2.py`、`_scan.py`。**全部只用 `sqlite3 mode=ro` + 读文件，没写库、没碰 `site/dist`。**

---

## 1. 精度归整（74 行清单 × 页面主规格）

**命令（核心两条）**

```powershell
# a) 全库扫描：原值有没有作为「主规格」出现在产物里（data-spec 是规格单元格）
& $py .tmp/_scan.py "drug,name" "499.9996|500.0082|500.0081|100.008 mg"
# b) 74 行逐行：库值 → 按构建期口径算期望主规格 → 在对应 drug 页里找 data-spec
& $py .tmp/_v_prec2.py
```

**期望**：59 行被构建期归整（`≤2e-5` 相对）；这些行的页面规格必须是整数（`500 mg` 等），且原值不得作为规格单元格出现。

**实测**

| 项 | 结果 |
|---|---|
| 扫描范围 | `site/dist/drug/` + `site/dist/name/` 共 **93,323 个文件** |
| `499.9996` | **0 次 / 0 文件** |
| `500.0081` | **0 次 / 0 文件** |
| `500.0082` | **0 次 / 0 文件** |
| `100.008 mg` | 2 次 / 1 文件（`drug/aspirin.html`）→ 属「构建期窄口未归整」组，见 §5-① |
| 74 行状态 | `PASS` **55** ｜ `页面保留原值(未归整)` **15** ｜ `未渲染(该组不在页面)` **4** ｜ **`FAIL-原值当主规格` 0** |

**10 行抽样**（前 8 行=PASS，后 2 行=口径差样例）

| 状态 | product_id | ord | 国家 | 剂型 | 库里 strength_value | 页面主规格 | 归整 | 页面 |
|---|---|---|---|---|---|---|---|---|
| PASS | AU-ARTG-119994 | 1 | AU | tablet | 500.0081 mg | **500 mg** | 是 | drug/acetaminophen.html |
| PASS | AU-ARTG-120945 | 0 | AU | tablet | 500.0082 mg | **500 mg** | 是 | drug/acetaminophen.html |
| PASS | AU-ARTG-153435 | 1 | AU | tablet | 499.9996 mg | **500 mg** | 是 | drug/acetaminophen.html |
| PASS | AU-ARTG-153436 | 2 | AU | tablet | 499.9996 mg | **500 mg** | 是 | drug/acetaminophen.html |
| PASS | AU-ARTG-155648 | 2 | AU | tablet | 499.9996 mg | **500 mg** | 是 | drug/acetaminophen.html |
| PASS | AU-ARTG-170501 | 15 | AU | capsule | 500.0003 mg | **500 mg** | 是 | drug/concentrated-fish-omega-3-triglycerides.html |
| PASS | AU-ARTG-174026 | 0 | AU | tablet | 499.9996 mg | **500 mg** | 是 | drug/acetaminophen.html |
| PASS | AU-ARTG-177325 | 4 | AU | tablet | 499.9996 mg | **500 mg** | 是 | drug/acetaminophen.html |
| 页面保留原值 | AU-ARTG-177614 | 0 | AU | tablet | 100.008 mg | 100.008 mg | 否（窄口未过） | drug/aspirin.html |
| 页面保留原值 | AU-ARTG-177615 | 0 | AU | tablet | 100.008 mg | 100.008 mg | 否（窄口未过） | drug/aspirin.html |

**关于「原始值只在原记录小字」**：`499.9996` 这类值在 `drug/`、`name/` **一次都没出现**，所以当然没有作为主规格出现；
它也没有出现在「原记录 / Recorded as」小字里，原因是 `_raw_strength()` 的来源快照
`data/sources/unit_normalization_20261030.csv`（task-16 审计）**不含这批 ARTG 行** —— 即这批 500.x 是**我们自己的 g↔mg 换算残渣**，
来源标签本来就是 `500 mg`，显示成 500 mg 即正确，无需「原记录」旁注。全站「Recorded as」仍正常工作（`drug/` 里 372 处）。

**判定：PASS**（0 条把残渣当主规格；15 行进 §5-① 口径差）。

## 2. 每单位基数 `960 mg/30 mL`（三处产物）

**命令**

```powershell
& $py .tmp/_scan.py "drug" "960 mg/30 mL"     # 分别对 drug / name / combo / data 跑一次
& $py .tmp/_v_name2.py                        # 3 个同名多剂型 key 的品牌页 vs 库
```

**期望**：`drug/acetaminophen.html`、`name/tylenol-extra-strength.html`、`data/idx/core.json` 三处各 ≥1 次；且「同名字不同剂型」不再被单一剂型代表。

**实测**

| 目录 | 命中文件 | 命中次数 | 前几个文件 |
|---|---|---|---|
| `drug/` | **1** | **3** | `drug/acetaminophen.html×3` ✅ |
| `name/` | **3** | **3** | `name/acetaminophen.html`、`name/tylenol-extra-strength.html` ✅、`name/泰诺林.html` |
| `data/` | 6 | 14 | `data/idx/core.json×5` ✅、`data/idx/cat-analgesics.json×2`、`cat-cold-medicine.json×2` |
| `combo/` | 0 | 0 | 复方页不列成分强度，预期为 0 |

`name/tylenol-extra-strength.html` 原文（现查）：
`Strength by dosage form: tablet 500 mg；capsule 500 mg；liquid 960 mg/30 mL；powder 500 mg/950 mg` —— 四个剂型各带自己的规格，
**不再是「500 mg / 960 mg + 片剂」**。

3 个「同名多剂型」key（品牌页 vs 库复算）：

| key | 页面（剂型→规格） | 库 fs | 结论 |
|---|---|---|---|
| `tylenol extra strength` | tablet 500 mg；capsule 500 mg；liquid **960 mg/30 mL**；powder 500 mg/950 mg | 同 4 组，完全一致 | **PASS** |
| `a cys` | effervescent 600 mg；tablet 600 mg；capsule 600 mg | 同 3 组 | **PASS** |
| `abilify` | tablet 2/5/10/15/20/30 mg；liquid 1 mg；injection 7.5 mg | tablet 6 个规格 + liquid 1 mg + injection 7.5 mg | **PASS** |

**判定：PASS**（三处产物都有；同名多剂型不再被单一剂型代表）。

## 3. 单方 / 复方归属（3 个成分页 × 各 5 行 × 两段）

**命令**

```powershell
& $py .tmp/_v_seg5.py     # 解析 mkseg 段 + 行内品牌/厂家锚点 → 回库取 product_id 与成分数
```

**期望**：`drug/<成分>.html` 的 `data-seg="mono"` 段每行抽 5 个产品，`COUNT(product_component)` 必须 = 1；`data-seg="combo"` 段必须 > 1；
复方行还要和库的成分集合逐项对得上。

**实测：30 行抽查，PASS 30 / FAIL 0。**

| 页 | 段 | 行（市场·剂型·本成分规格） | 抽查 product_id（成分数） | 结论 |
|---|---|---|---|---|
| acetaminophen | mono | CN·tablet·500 mg | CN-XN02BEA277A00-5e115c01(1)、CN-XN02BED158A00-97e0fd72(1)、CN-XN02BED158A00-7dcbc2a0(1) | PASS |
| acetaminophen | mono | CN·tablet·300 mg | CN-XN02BED158A00-8937e7de(1)、-51aef6a8(1)、-fd3b4d8e(1) | PASS |
| acetaminophen | mono | CN·liquid·160 mg/5 mL | CN-XN02BED158X00-e17c91c6(1)、-b79d3c27(1) | PASS |
| acetaminophen | mono | CN·tablet·325 mg | CN-XN02BEA151A00-77c89091(1)、-f02b347f(1)、-9139631e(1) | PASS |
| acetaminophen | mono | CN·tablet·650 mg | CN-XN02BED158A01-9bed5cb4(1)、-99a37ff3(1) | PASS |
| acetaminophen | combo | CN·capsule·250 mg | CN-XR05XXF134E00-ce9003cf(2)、-c56ab5f9(2)、-b4c68bd6(2)† | PASS |
| acetaminophen | combo | CN·tablet·250 mg | CN-XR05XXF134A00-bac2fd05(2)、-adcaf2c2(2)、-fa27531f(2)† | PASS |
| acetaminophen | combo | CN·tablet·330 mg | CN-XN02BED159A00-d6997d56(2)†、-d33cfbff(2) | PASS |
| acetaminophen | combo | CN·capsule·250 mg | CN-XR05XXF134E00-20313585(2)† | PASS |
| acetaminophen | combo | CN·capsule·125 mg | CN-XR05XXF134E00-642a9bcd(2)†、-bdb8bb44(2) | PASS |
| hydrochlorothiazide | mono | US·tablet·25 mg | US-50090-6014(1)、US-50090-6158(1)、US-65862-133(1) | PASS |
| hydrochlorothiazide | mono | US·tablet·50 mg | US-43353-240(1)、US-63629-8992(1)、US-50090-6156(1) | PASS |
| hydrochlorothiazide | mono | US·tablet·12.5 mg | US-51407-330(1)、US-53401-038(1)、US-50090-6372(1) | PASS |
| hydrochlorothiazide | mono | US·capsule·12.5 mg | US-71335-0770(1)、US-46708-438(1)、US-62332-070(1) | PASS |
| hydrochlorothiazide | mono | US·liquid·50 mg/5 mL | US-72888-491(1) | PASS |
| hydrochlorothiazide | combo | US·tablet·12.5 mg | US-72162-1035(2)†、US-72162-2461(2)、US-43547-391(2) | PASS |
| hydrochlorothiazide | combo | US·tablet·12.5 mg | US-43547-420(2)、US-46708-209(2)、US-62332-210(2)† | PASS |
| hydrochlorothiazide | combo | US·tablet·12.5 mg | US-72162-1035(2)、US-46708-209(2)、US-53746-845(2)† | PASS |
| hydrochlorothiazide | combo | US·tablet·12.5 mg | US-72162-1035(2)、US-31722-887(2)、US-31722-895(3) | PASS |
| hydrochlorothiazide | combo | US·tablet·12.5 mg | US-0093-7369(2)、US-43547-391(2)、US-43547-331(2)† | PASS |
| zinc-oxide | mono | US·topical·200 mg | US-55560-0110(1) | PASS |
| zinc-oxide | mono | US·topical·160 mg | US-85443-208(1) | PASS |
| zinc-oxide | mono | US·topical·132 mg | 锚点未解析；同组单方产品 **119** 个（成分数全 = 1） | PASS |
| zinc-oxide | mono | US·topical·150 mg | US-84763-005(1) | PASS |
| zinc-oxide | mono | US·topical·25 kg/100,000,000 mg | US-83252-056(1) | PASS |
| zinc-oxide | combo | US·topical·38 mg | US-81381-203(2)† | PASS |
| zinc-oxide | combo | US·stick·55 mg | US-85351-212(2)、US-81679-220(2)† | PASS |
| zinc-oxide | combo | US·liquid·47.5 mg | US-51060-201(2)† | PASS |
| zinc-oxide | combo | US·topical·6,300 mg/100 mL | US-69259-0450(2)、US-69259-0412(2)† | PASS |
| zinc-oxide | combo | US·liquid·29.4 mg | US-14141-375(2)† | PASS |

† = 该行「页面列出的成分 + 各自含量」与这个 product_id 的 `product_component` **逐项完全一致**（例：
`Titanium Dioxide 80 mg + Zinc Oxide 38 mg` = `US-81381-203` 的两条组件；`Hydrochlorothiazide 12.5 mg + Irbesartan 150 mg` = `US-62332-210`）。

结构计数（HTML 行数 vs 库内分组数）：
`acetaminophen` mono 110 / combo 40；`hydrochlorothiazide` mono 33 / combo 40；`zinc-oxide` mono 34 / combo 21。
库内按 (剂型, 本成分规格, 其它成分签名) 分组的组数远大于 HTML 行数（例：zinc-oxide mono 组 545 / HTML 34 行），
这是**页面聚合 + 行数上限 + 尾部折叠**的结果（`MATRIX_ROW_CAP = 120`、`more-specs` 折叠、完整清单指回 `datapackage.json`），
不是分组错误 —— 抽查的 30 行全部落在正确分段。

**判定：PASS**（单方段没有复方，复方段列全成分；锚点共用的情况已单列说明）。

## 4. 索引一致性（core.json 的 `f` / `fs` / `s`）

**命令**

```powershell
& $py .tmp/_v_idx2.py     # 解码 core.json（列式+字典编码）→ 按 key 与库复算比对
```

**期望**：`f` = `"multi"`（多剂型）或单一剂型名；`fs` 每组 = `剂型|规格;规格`，规格必须来自库；`s` ⊆ 库规格集合。
`f`/`fs`/`s` 的口径见 `site/build.py:8882-8889`（`fs` 只在 ≥2 个剂型时写）。

**实测：5/5 PASS**

| key | `f` 索引 / 库 | `fs` 索引 | 与库的关系 | 结论 |
|---|---|---|---|---|
| `tylenol extra strength` | `multi` / `multi` | `tablet\|500 mg`、`capsule\|500 mg`、`liquid\|960 mg/30 mL` | 与库**完全相同**（每组各 1 个规格） | **PASS** |
| `a cys` | `multi` / `multi` | `effervescent\|600 mg`、`tablet\|600 mg`、`capsule\|600 mg` | 完全相同 | **PASS** |
| `aceclofenac` | `multi` / `multi` | `tablet\|100 mg`、`liquid\|100 mg`、`topical\|1,500 mg` | 完全相同 | **PASS** |
| `abilify` | `multi` / `multi` | `tablet\|15 mg;2 mg;30 mg`、`liquid\|1 mg`、`injection\|7.5 mg` | 库 tablet 有 6 个规格 → 索引取前 3（**子集关系成立**） | **PASS** |
| `abilify maintena` | `multi` / `multi` | `liquid\|300 mg;400 mg`、`injection\|300 mg;400 mg`、`powder\|300 mg;400 mg` | 集合相同（injection 库内顺序 400→300） | **PASS** |

`s` 列：5 个 key 的索引规格集合都是库规格集合的子集（最多 6 个），例如 `tylenol extra strength` 索引 3 个 = 库 3 个，含 `960 mg/30 mL` ✅。

**判定：PASS**。唯一不可复算的是「每组取哪 3 个规格」——由构建期 SQL 顺序决定（`_fs_pack` 只做 `specs[:3]`），属已知取舍（§5-②）。

---

## 5. 口径差与观察（都不是错，但需要 Lead 知道）

**① 我的 74 行清单比构建期窄口更宽 → 15 行页面仍显示原值。**
清单容差是「≤0.01 且 ≤0.01% 相对」；`_snap_strength` 用的是 **2e-5 相对**（0.002%）。两者交集外的行不会被归整：

| 建议档位 | 行数 | 页面实际显示 |
|---|---|---|
| 100 mg | 9 | `100.008 mg`（如 AU-ARTG-177614，`drug/aspirin.html`） |
| 50 mg | 2 | `50.0035 mg`、`50.004 mg` |
| 20 mg / 20 mg/g | 2 | `20.001 mg`、`20.0008 mg/g` |
| 10 mg | 1 | `10.0008 mg` |
| 400 mg（CA 399.99） | 1 | `399.99 mg`（未进入页面可见组） |

影响：用户评审 §1.5 点名的 `499.9996 mg` **已彻底修好**（41 行 500 档全部归整）；但 `100.008 mg` 这 9 行仍会在页面上出现。
要不要把构建期窄口放宽到 1e-4（清单口径）是**产品决定**（会让 100.008/50.0035/20.001 也变成整数），我这轮只报数、不改 `site/build.py`。

**② 索引 `fs` 每组最多 3 个规格、最多 3 组**，取哪 3 个由构建期 SQL 顺序决定，**不可由库精确复算**；
可复算的是「索引规格 ⊆ 库规格」。所以 `abilify` 的 `tablet|15 mg;2 mg;30 mg` 与库顺序不同不是错。

**③ 4 行（已归整）所在分组未进入页面可见行**（成分页有行数上限/尾部折叠，完整清单指回 `datapackage.json`）。
这批行只能通过索引/数据包核对，不能从 `drug/*.html` 复核。

**④ 文档漂移（不是数据问题）**：`site/build.py:9344` 的注释仍写「T15 清单 B（614 行）」，实际清单已是 **832 行**。
属构建期注释，不影响产物；改它是 site-ui/Lead 的写权限，我没动。

**⑤ 复方页 `combo/*.html` 不含成分强度**（`960 mg/30 mL` 命中 0），与设计一致（组合页只列复方记录），不是漏渲染。

## 6. 明确没做的事

* **没写库**：全程 `sqlite3 mode=ro`；没跑 ingest / init_db / UPDATE / ALTER，索引与表结构未动。
* **没改 `site/dist`**：只读打开 93,323 个 HTML + `core.json`；没构建、没删改任何产物。
* 没改 `site/build.py`、没 commit、没发布。
* 没看截图、没做视觉判断（归 atc4-ui）。

## 7. 一句话结论

**v0.11.6 产物与库在本次抽到的四个维度上一致：精度归整的 500 档全部生效且无残渣泄漏，`960 mg/30 mL` 三处产物都在，单方/复方 30/30 归属正确，索引 `f`/`fs`/`s` 5/5 可复算 —— 数据层没有发现与页面矛盾的地方；剩余 15 行「清单建议归整但构建期未归整」属口径取舍，需 Lead 决定是否放宽窄口。**
