# JP 缺失 INN 清单（v0.11.6 前置 · 只读）

日期：2026-11-13 ｜ 工位：phaseb-plan ｜ 任务：task-4
范围：**纯只读**。未写 `data/drugs.db`（`mode=ro` 连接）、未改 `etl/**`、未建站、未 commit / 发布。
产物：`data/sources/jp_missing_inn_20261113.csv`（79 行，UTF-8 无 BOM）、本报告。临时中间件在 `.tmp/jp-plan/`（不入库）。

---

## 0. 结论先行

| 项 | 数 | 说明 |
|---|---|---|
| 基线（现查复现） | token **9,934 / 11,925 = 83.30%**；产品加权 **9,251 / 11,221 = 82.44%** | 与 `reports/2026-11-14-jp-mapping.md`、`.tmp/jp-ingest/jp_dry_run.json` 完全一致 |
| ① 真缺 INN（`missing_inn`） | **36 行 / 35 个 INN / 305 token 出现次数** | 库内按 `inn_en` 精确+前缀查不到，必须**新建 substance 行** |
| ② 映射表缺口（`mapper_gap`） | **31 行 / 241 token** | 库内**已有** substance（含盐型/酯型/水合物行），只缺 `jp_inn_map.csv` 行——**不需要写库** |
| ③ 应归非单一成分（`reclassify_nonsub`） | **12 行 / 86 token** | 生药 / 血制品 / 辅料，应进 `jp.py` 的 non-substance 规则（改代码，本任务不做） |
| 合计 | 79 行 / 632 token，占全部未映射出现次数 **1,738 的 36.4%** | top80 未映射写法里的全部高频项 |

**补齐后的映射率（逐条模拟，非拍脑袋）**

| 方案 | token 率 | 产品加权·完全匹配 | 需要写库？ |
|---|---|---|---|
| 现状 | 83.30% | 82.44% | — |
| S1 只补 ②（映射表） | **85.32%** | 84.58%（未过） | ❌ 只改 `data/sources/jp_inn_map.csv` |
| S2 只补 ①（缺 INN） | **85.86%** | **85.15%** | ✅ 36 行 substance + variant |
| S3 = ①+②（推荐） | **87.88%** | **87.29%** | ✅ 上面两项 |
| S4 = ①+②+③（含 non-substance 重分类） | **88.52%** | **87.97%** | ✅ + 改 `jp.py` 规则 |

> **结论：过 85% 不需要"发明 20 个药"，也不需要放宽匹配阈值。**
> ① 单独做就能让两个口径都过线（85.86% / 85.15%）；② 是零写库的廉价增量（token 单独就够 85.32%，但产品加权 84.58% 仍差 0.4pp）。
> 上一份报告担心的"继续扩人工表收益递减"只对了一半：**人工表里还没被利用的恰好是 top80 里的这 241 个 token**，因为上一轮 CSV 只收了 `substance_id` 能校验通过的行，这些行当时以为是"库内没有"。

**三个必须先知道的发现（会影响写库窗口的做法）**

1. **"缺 INN"里有 5 条不是缺行，是主名语言不对**：
   `セフカペン ピボキシル塩酸塩水和物 → cn-d4f6d6b6a0（盐酸头孢卡品酯）`、`トスフロキサシン… → cn-0ed19799d0（甲苯磺酸妥舒沙星）`、`ナルフラフィン塩酸塩 → cn-9905031733（盐酸纳呋拉啡）` 是**中文主名的 CN 行**；
   `イミダフェナシン → mx-es-imidafenacina`、`セフジトレン ピボキシル → cefditoreno` 是**西语主名行**。
   这 5 条都已经挂着真实产品（CN 6/14/1 个、MX 1 个、ES 4 + MX 1 个）。**照"新建 substance"处理会造出重复分子**，正确做法是补英文 INN / `name_variant` 后再加 `jp_inn_map` 行（本报告已把它们归到 ②，不是 ①）。
2. **库内有 1,759 行 `substance.inn_en` 主名是中文**（`name_lang='zh'`，实测 `SELECT count(*) … WHERE inn_en GLOB '*[ぁ-んァ-ヶ一-龥]*'` = 1,759）。新建 ① 之前必须按 **ATC + 中文名** 查重，否则同一分子会有两条 substance。
3. **12 行 / 86 token 根本不该算进分母**（生药 ハンゲ・コウブシ・ガジュツ・ビンロウジ・モクツウ；血制品 pH4 処理酸性人免疫グロブリン ×2・PEG 処理 IVIG；辅料 酒石酸・クエン酸水和物；院内制剂 ヨードチンキ ×2）。`jp.py` 的 non-substance 规则还没覆盖它们，所以现在它们同时拉低分子和拉高分母。

---

## 1. 怎么验的（可复核）

### 1.1 基线复现（不依赖库副本）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 直连真库只读 + 复用 jp.py 的映射器，跑一遍全量并导出 top80 未映射
# （脚本见 .tmp/jp-plan/；等价于 etl/markets/jp.py --dry-run 的核心三步）
```
关键调用面：`jp._connect_ro(data/drugs.db)` → `jp.load_snapshot()` → `jp.JpMapper(db)` → `jp._collect(...)`。
结果：`tokens 11,925 / mapped 9,934 = 83.30% / nonsub 1,417 / unique_unmapped 688`，**与 2026-11-11 的 dry-run JSON 逐位一致**，
说明 `reports/2026-11-14-jp-mapping.md` 的 83.3% 可复现，我这份清单不是抄旧数字。

> 库状态现查（2026-11-12，另一工位可能正在写库）：`substance 12,637` / `variant 14,237` / `product 494,992`。
> 我用 `mode=ro` + `timeout=120`，全程无写操作；journal_mode = `delete`。

### 1.2 每条 INN 的库内存在性（CSV 的 `db_status` 列）

```sql
-- 精确 + 前缀（覆盖盐型/水合物/酯）
SELECT substance_id, inn_en, coalesce(inn_zh,''), coalesce(atc,''), coalesce(name_lang,'')
FROM substance
WHERE lower(inn_en) = lower(:inn) OR lower(inn_en) LIKE lower(:base || '%')
ORDER BY length(inn_en) LIMIT 4;
```
判据：**0 行 → `missing_inn`**；有行 → `mapper_gap`（并给出 `substance_id`，写库窗口直接用）。

### 1.3 证据（CSV 的 `evidence_jp` / `evidence_inn` / `atc_source`）

| 证据级别 | 内容 | 用于哪些列 |
|---|---|---|
| 药价基准原文 | `data/raw/jp_yakka_20261112/`（2026-11-01 版，4 个 xlsx，12,442 品目）**成分名列**，每条附出现次数 | `evidence_jp`（全部 79 行） |
| 库外快照 | `data/sources/phaseb-candidates-20261031.csv` L720 / L743 / L1520（wikidata_cache，medium；含 ATC 差异比对） | `evidence_inn` / `atc` / `inn_zh`（3 行） |
| 库内直证 | `substance` 行本身（`inn_en`/`atc`） | `mapper_gap` 的 31 行 |
| **推定** | 日文一般名 ↔ INN 的片假名转写（一对一，无歧义） | 其余 `missing_inn` 行，标「待 PMDA 添付文書/WHO INN 逐条核对」 |

**没有做的事（不猜）**：`atc` 列只填有出处的 4 条（上表 3 条 + `cefditoreno` 库内行 ATC `J01DD16`），其余留空并注明「未核 ATC 索引」。
本时段没有 ATC 索引快照，凭记忆填 20 个 ATC 码会违反 §4「不确定就标待确认」。核对入口：`https://atcddd.fhi.no/atc_ddd_index/?name=<INN>`。

### 1.4 估算怎么算的（不是线性外推）

- token 率：`(9,934 + 命中 token 出现次数) / (11,925 − 重分类为 non-substance 的 token 数)`。
- 产品加权·完全匹配：用 `_collect` 的逐产品结果做**逐条模拟**——某产品剩余未映射 token 全在修复集内 → 计入 `products_all_mapped`；
  全在 non-substance 集内 → 从分母移除。分母恒为 `products − products_non_substance`（现查 12,442 − 1,221 = 11,221）。
- 模拟脚本：`.tmp/jp-plan/sim3.json`（可复跑，37 秒/次，只读）。

---

## 2. CSV 结构与清单

`data/sources/jp_missing_inn_20261113.csv`（79 行，列名自解释）：

`category, jp_name, inn_en, salt_or_ester, inn_zh, atc, atc_source, token_occurrences, db_status, substance_id, fix_action, evidence_jp, evidence_inn, verdict, note`

- `category`：`missing_inn`（36）/ `mapper_gap`（31）/ `reclassify_nonsub`（12）
- `verdict`：`可定案` 75 / `待确认` 4（`ウパシカルセト` 盐名写法、`クエン酸第一鉄ナトリウム` 是否为 WHO INN、`dl-メチルエフェドリン` 消旋体写法、`チアミンジスルフィド` INN 拼写）
- 同一 INN 的两行**没有合并**（`フルスルチアミン塩酸塩` 6 + `フルスルチアミン` 5 = 11 token，同一个 `Fursultiamine`，写库时只建一行 substance）→ 36 行 = 35 个 INN。

### 2.1 缺 INN top15（`missing_inn`，按 token 次数）

| # | 日文名（薬価基準 成分名） | 推定 INN | 盐型/酯 | token |
|---|---|---|---|---|
| 1 | マキサカルシトール | Maxacalcitol | — | 23 |
| 2 | ブロナンセリン | Blonanserin | — | 20 |
| 3 | ナファモスタットメシル酸塩 | Nafamostat | mesilate | 17 |
| 4 | サルポグレラート塩酸塩 | Sarpogrelate | hydrochloride | 15 |
| 5 | パンテチン | Pantethine | — | 14 |
| 6 | ベニジピン塩酸塩 | Benidipine | hydrochloride | 13 |
| 7 | 酢酸亜鉛水和物 | Zinc acetate | hydrate | 11 |
| 8 | エルデカルシトール | Eldecalcitol | — | 10 |
| 9 | ベラプロストナトリウム | Beraprost | sodium | 9 |
| 10 | トラニラスト | Tranilast | — | 9 |
| 11 | スプラタストトシル酸塩 | Suplatast | tosilate | 9 |
| 12 | エチゾラム | Etizolam | — | 8 |
| 13 | タルチレリン水和物 | Taltirelin | hydrate | 8 |
| 14 | ミロガバリンベシル酸塩 | Mirogabalin | besilate | 8 |
| 15 | パルナパリンナトリウム | Parnaparin | sodium | 7 |

（完整 36 行见 CSV；`トスフロキサシン` 13 / `セフカペン` 18 / `ナルフラフィン` 8 已按 `mapper_gap` 处理，见 §0 发现 1。）

### 2.2 映射表缺口 top10（`mapper_gap`，**不用写库**）

| 日文名 | 已有 substance_id | token | 备注 |
|---|---|---|---|
| イミダフェナシン | `mx-es-imidafenacina` | 15 | 主名是西语，补英文别名 |
| セフカペン ピボキシル塩酸塩水和物 | `cn-d4f6d6b6a0` | 18 | 主名中文，补英文 INN |
| セフジトレン ピボキシル | `cefditoreno` | 13 | 主名西语，ATC `J01DD16` |
| トスフロキサシントシル酸塩水和物 | `cn-0ed19799d0` | 13 | 主名中文 |
| セファゾリンナトリウム | `cefazolin-sodium` | 11 | 盐型行已有 |
| パリペリドンパルミチン酸エステル | `paliperidone-palmitate` | 9 | 酯型行已有 |
| セフタジジム水和物 | `ceftazidime-pentahydrate` | 9 | 水合物行已有 |
| セフォペラゾンナトリウム | `cefoperazone` | 9 | 只有裸名，需补 variant |
| シメチジン | `cimetidine` | 8 | 骨架层没命中（/ʃ/ vs /s/） |
| クロルフェニラミンマレイン酸塩 | `chlorpheniramine` | 8 | 需补 maleate variant |

### 2.3 应归 non-substance（12 行，86 token）

生药 5（ハンゲ・コウブシ・ガジュツ・ビンロウジ・モクツウ）、血制品 3（pH4 処理酸性人免疫グロブリン ×2、PEG 処理 IVIG）、
辅料 2（酒石酸、クエン酸水和物）、院内制剂 2（希ヨードチンキ、ヨードチンキ）。
> 血制品/抗体类有 5 条**库内已有 substance**（`human-immunoglobulins` J06BB02、`efmoroctocog-alfa`、`lonoctocog-alfa`、`emicizumab`、`asfotase-alfa`），
> 已放进 `mapper_gap` 但备注「口径待定」：**要么按 §5 口径归 non-substance，要么照实映射**，需要产品口径拍板，不能两套并存。

---

## 3. 下一窗口验证（≥85% 判据）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 1) 复制真库到演练目录（唯一允许的"写"，只写 .tmp）
& $py etl/markets/jp.py --prepare-copy
# 2) 干跑
& $py etl/markets/jp.py --dry-run
# 3) 判据：token 率 + 产品加权率（一次算完）
& $py -c "import json;d=json.load(open('.tmp/jp-ingest/jp_dry_run.json',encoding='utf-8'))['substance'];den=d['products_all_mapped']+d['products_partial_mapped']+d['products_none_mapped'];print('token',d['token_rate_pct'],'product',round(d['products_all_mapped']/den*100,2))"
```
**通过线**：`token ≥ 85.0` 且 `product ≥ 85.0`（S3 预计 87.88 / 87.29，留 2.3pp 余量）。
**回归**：`& $py etl/markets/jp.py --self-check`（12 项断言）；误配抽检仍按老规矩分层 30 条、判据「错 ≤1」。

### 3.1 写库前必做的查重（避免重复分子）

```sql
-- 新 INN 落地前：按 ATC 和中文名各查一遍，命中就改现有行而不是新建
SELECT substance_id, inn_en, inn_zh, atc, name_lang FROM substance
WHERE atc = :atc OR inn_en LIKE :zh_pattern OR inn_zh LIKE :zh_pattern;
-- 已知 5 条必须走"改名/补别名"：cn-d4f6d6b6a0 / cn-0ed19799d0 / cn-9905031733 / mx-es-imidafenacin(a) / cefditoreno
```

### 3.2 建议的施工顺序（下一次 DB 窗口）

1. **先做 ②**（零写库）：往 `data/sources/jp_inn_map.csv` 追加 31 行（列结构与现有 184 行一致：`jp_name,substance_id,inn_en,method,confidence,note,source`；CSV 里的 `substance_id` 已填好），`--dry-run` 应立即到 85.32% / 84.58%。
2. **再做 ①**：36 行 → 35 个 substance + variant（盐型/水合物按 CSV 的 `salt_or_ester` 列）；`jp_inn_map.csv` 再追加对应 36 行。预计 87.88% / 87.29%。
3. **最后处理 ③**（需改 `jp.py` 的 `is_non_substance`）：+0.6pp，但更重要的是把 86 个 token 从分母里去掉、不再假性拉低覆盖率。
4. ATC / 中文名：按 `https://atcddd.fhi.no/atc_ddd_index/?name=<INN>` 与 PMDA 添付文書逐条补，补完把 `verdict` 从「待确认」改「可定案」。

---

## 4. 缺口与风险（诚实说清）

1. **ATC 只填了 4 条**（3 条来自 phaseb 快照 + 1 条库内行）。本时段没有 ATC 索引快照，其余 35 条 `missing_inn` 的 ATC 留空。这不是漏做，是**不凭记忆填**。
2. **中文名只有 3 条有库内出处**（`盐酸头孢卡品酯` / `甲苯磺酸妥舒沙星` / `盐酸纳呋拉啡`，均来自 `phaseb-candidates-20261031.csv`），其余留空。
3. **INN 推定未经 PMDA 逐条核对**：日文一般名 → INN 的转写是一对一、无歧义的（药价基准成分名列本身是官方写法），但「推定」二字不省；4 条已标 `待确认`。
4. **重名风险未穷举**：我只实测了 5 条（§0 发现 1）。库内 1,759 行中文主名，剩下 35 条缺 INN 里**可能还有以中文主名存在的行**；`--dry-run` 之前的 §3.1 SQL 必须逐条跑。
5. **估算依赖 top80 口径**：688 个未映射写法里我只覆盖了 top80（632 token / 1,738 = 36.4%）。剩余长尾 608 个写法、1,106 token 未分类（多为低频 1–4 次），下一轮可以按同样流程扩到 top200。
6. **血制品/抗体口径没拍板**：5 条已在库内（J06BB02 等），归 non-substance 还是照实映射会同时影响分子与分母，建议由 Lead 定一次口径写进 `docs/`。

---

## 5. 复现清单

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/check_data.py      # 已跑：全库体检正常输出（只读；本任务无写库，before = after）
```
**没跑的**：`etl/` / `lib/` 的 unittest 与 `tests/trilingual/run_tests.py` —— 本任务**没有改任何代码**，也没有写库，
基线 83.30% 由 §1.1 的只读重跑证明；下一窗口改 `jp.py` / 写入库之后必须补跑这两套。
中间产物（不入库）：`.tmp/jp-plan/jp_probe.json`（top80 未映射 + 方法分布）、`.tmp/jp-plan/db_probe2.json`（存在性探测）、`.tmp/jp-plan/sim3.json`（四方案模拟）。
