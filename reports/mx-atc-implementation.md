# MX 浓度回填 + Wikidata ATC 补全：实现报告（task-5，dry-run）

> 日期：2026-10-26 ｜ 线上站：v0.3.3 ｜ 本轮**只跑 dry-run**：`data/drugs.db` 未被写入（复核：MX 有浓度组件 3,161、有 ATC 成分 5,751、ccby corroboration 0 行）。
> 依据：`reports/data-depth-20261026.md` §2.2/§3；证据脚本 `.tmp/data-depth/`。本报告数字全部取自 `.tmp/mx-atc/*_dryrun.json`，可复跑核对。

## 1. 交付物

| 文件 | 作用 |
|---|---|
| `etl/fetch_mx_ccby.py` | 从 datos.gob.mx CKAN 拉 4 个 CC-BY-4.0 数据集 → `data/raw/mx/ccby/`（默认看状态，`--download` 才联网） |
| `etl/ingest_mx_ccby.py` | 解析 → `(西语通用名归一, 剂型) → 浓度集合` → MX 空浓度回填；`--dry-run`(默认)/`--apply`/`--rollback` |
| `etl/fetch_wikidata_atc.py` | SPARQL 拉 P267(+P715/P231/en·es·zh 标签) → `data/raw/wikidata/atc_p267.json`（默认看状态，`--download` 才联网） |
| `etl/ingest_wikidata_atc.py` | 名称→ATC 唯一码补 `substance.atc`；`--dry-run`(默认)/`--apply`/`--rollback` |
| `.tmp/mx-atc/` | dry-run JSON/TXT、50 条人工核对清单 CSV、apply 副本实测、缓存 sha256、探查脚本 |

## 2. 用法速查

```bash
# A) MX 浓度回填
python etl/fetch_mx_ccby.py --download        # 4 次 package_show + 4 次 datastore_search，缓存 JSON（含许可/抓取时间）
python etl/ingest_mx_ccby.py                  # 默认 dry-run，只读库，输出统计 + 抽样 + 报告
python etl/ingest_mx_ccby.py --apply          # 正式写库（单事务）
python etl/ingest_mx_ccby.py --rollback       # 撤销本 ETL 写入的回填

# B) Wikidata ATC
python etl/fetch_wikidata_atc.py --download   # 一次 SPARQL，缓存 rows+meta（CC0）
python etl/ingest_wikidata_atc.py             # 默认 dry-run
python etl/ingest_wikidata_atc.py --apply     # 正式写库（单事务）
python etl/ingest_wikidata_atc.py --rollback  # 按 apply 清单撤销
```

两个 ingest 都支持 `--db <path>`（用于在副本上演练），默认 `data/drugs.db`。

## 3. A) MX 浓度回填

### 3.1 数据源与许可（全部 CC-BY-4.0，CKAN `license_id` 实测）

| key | datos.gob.mx package | 发布机构 | 行数 | 解析出浓度条目 | 无浓度 | 复方跳过 |
|---|---|---|---:|---:|---:|---:|
| inprfm | `adquisicion_medicamentos_demanda` | INPRFM（国家精神病学研究所） | 2,171 | 2,039 | 34 | 68 |
| hgmgg | `medicamentos_productos_farmaceuticos_adquiridos_hgmgg` | HGMGG（墨西哥总医院） | 3,537 | 2,455 | 813 | 151 |
| iner | `entrada_medicamentos` | INER（国家呼吸病研究所） | 2,968 | 2,589 | 211 | 123 |
| semar | `adquisicion_insumos_salud` | SEMAR（海军部） | 626 | 598 | 3 | 12 |
| **合计** | 4 个数据集 | — | **9,302** | **7,681** | — | — |

- 许可：`CC-BY-4.0`（每份缓存 JSON 的 `meta` 里带 `license` / `license_url` / `resource_id` / `retrieved_at` / 数据集页 URL）。**可再发布，需署名 + 注明修改**，见 §7。
- 缓存：`data/raw/mx/ccby/{inprfm,hgmgg,iner,semar}.json` + `meta.json`（sha256 见 `.tmp/mx-atc/CACHE_SHA256.md`）。

### 3.2 解析与归一（保守优先）

- **通用名**：先取描述第一个分句、去掉混入的剂型短语；去重音、小写、去标点后，去掉 `de/la/y` 等填充词与盐/酯/水合物词（`clorhidrato`、`sodico`、`citrato`…），**取前 2 个实词**作 key（如「Clorhidrato de ranitidina」→`ranitidina`）。
- **剂型**：复用 `etl/ingest_mx.py` 的 `form_base_es`，另补 INER 的缩写（`tab.`/`sol.`/`i.v.`…）；剂型从整段描述提取（HGMGG 常写在第 1 句）。
- **浓度**：兼容 `µg/μg`、千分位（`600 000 UI`）、`UI→iu`、`%`；HGMGG/SEMAR 优先取「CONTIENE:」之后第一处，避免把包装数量当浓度。只取**第一处**浓度，与 `ingest_mx.py` 现有口径一致。
- **复方**（`A y B`、`A/B`）整条跳过：无法把产品级浓度安全分给每个成分。
- 结果：解析条目 7,681 条，(name, form) 组 929 个，通用名 709 个。

### 3.3 匹配规则（严格优先，冲突一律不写）

只处理 **MX + 单成分 + 浓度全空 + 有西语通用名** 的产品（候选 5,485 个；多成分产品无法按产品级浓度拆分，跳过）。

1. **严格**：通用名前 2 实词相同 + `form_base` 相同 + 该组浓度唯一 → 写。
2. **放宽**：只看通用名前 2 实词 + 浓度唯一，但**仅限固体制剂 + 质量单位(mg/g/mcg)**；液体制剂不跨剂型套用（mg 与 mg/mL 不可比）——与 `ingest_mx.py` 现有 2,837/215 的口径一致。
3. 同组 >1 个浓度一律不写，计入冲突。

### 3.4 dry-run 结果

| 项目 | 数量 |
|---|---:|
| 严格规则可回填 | 850 |
| 放宽规则可回填 | 113 |
| **合计可回填产品 / 组件** | **963** |
| 命中冲突（产品，未写） | strict 644 / relaxed 521 |
| 液体跳过放宽规则 | 2,876 |
| 无匹配 | 1,646 |

按来源数据集（一个产品可被多个数据集同时支持）：`hgmgg` 605，`inprfm` 349，`iner` 172，`semar` 52。

### 3.5 覆盖率变化预估

| 口径 | 现状 | dry-run 后（预估） | 变化 |
|---|---:|---:|---:|
| 产品级（有任一组分浓度 / 全部 MX 产品） | 3,123/10,878 = 28.7% | **4,086/10,878 = 37.6%** | +8.9 pp |
| 组件级 | 3,161/13,632 = 23.2% | **4,124/13,632 = 30.3%** | +7.1 pp |

> 这是**当前库快照上的实测预估，不是承诺值**。`reports/data-depth-20261026.md` §2.2 的模拟值 +1,615（28.7%→43.6%）用的是「描述前 2 词」朴素 key，会把「clorhidrato de / citrato de」这种前缀当作通用名互相命中（盐类之间可错配）；本实现去掉盐/填充词后只剩 **963**，少的 652 条大多是这类不可靠匹配——建议把 37.6% 当作本期可交付值。

### 3.6 抽样 20 条（完整 963 条见 `.tmp/mx-atc/mx_ccby_dryrun.json` 的 `all_fills`）

| # | product_id | 西语通用名 | 剂型 | 回填 | 来源 | 规则 |
|---:|---|---|---|---|---|---|
| 1 | MX-249M2021 | BROMURO DE PINAVERIO | tableta | 100 mg | hgmgg,inprfm | name2+form |
| 2 | MX-064M2022 | Bromuro pinaverio | tableta | 100 mg | hgmgg,inprfm | name2+form |
| 3 | MX-067M2022 | MISOPROSTOL | tableta | 0.2 mg | hgmgg | name2+form |
| 4 | MX-076M2022 | Ivermectina | tableta | 6 mg | hgmgg | name2+form |
| 5 | MX-082M2022 | TACROLIMUS | cápsula | 1 mg | hgmgg | name2+form |
| 6 | MX-096M2022 | PROPOFOL | emulsión | 500 mg | iner | name2+form |
| 7 | MX-097M2022 | Micofenolato de mofetilo | tableta | 500 mg | iner | name2 |
| 8 | MX-108M2022 | MISOPROSTOL | tableta | 0.2 mg | hgmgg | name2+form |
| 9 | MX-113M2022 | FENOFIBRATO | cápsula | 160 mg | hgmgg | name2+form |
| 10 | MX-133M2022 | VINORELBINA | cápsula | 10 mg | iner | name2 |
| 11 | MX-135M2022 | PROPOFOL | emulsión | 500 mg | iner | name2+form |
| 12 | MX-136M2022 | Atropina | solución | 10 mg | hgmgg | name2+form |
| 13 | MX-150M2022 | Dolutegravir | tableta | 50 mg | hgmgg | name2+form |
| 14 | MX-153M2022 | Senósidos A-B | solución | 10 ml | iner | name2+form |
| 15 | MX-161M2022 | Hidroxicloroquina | tableta | 200 mg | hgmgg,inprfm,semar | name2+form |
| 16 | MX-163M2022 | CLARITROMICINA | solución | 2500 mg | iner | name2+form |
| 17 | MX-207M2022 | Clorhidrato de amitriptilina | tableta | 25 mg | hgmgg,inprfm | name2+form |
| 18 | MX-212M2022 | PROPOFOL | emulsión | 500 mg | iner | name2+form |
| 19 | MX-213M2022 | FENOFIBRATO | cápsula | 160 mg | hgmgg | name2+form |
| 20 | MX-219M2022 | LATANOPROST | solución | 0.05 mg | hgmgg | name2+form |

### 3.7 冲突样例（同组多浓度 → 不写）

- `MX-225M2021` Bevacizumab ／ `bevacizumab`/liquid：(100.0, 'mg')、(400.0, 'mg')（strict）
- `MX-228M2021` Bevacizumab ／ `bevacizumab`/liquid：(100.0, 'mg')、(400.0, 'mg')（strict）
- `MX-233M2021` BUDESONIDA ／ `budesonida`/liquid：(1280.0, 'mg')、(250.0, 'mg')（strict）
- `MX-010M2022` BUDESONIDA ／ `budesonida`/liquid：(1280.0, 'mg')、(250.0, 'mg')（strict）
- `MX-016M2022` Bevacizumab ／ `bevacizumab`/liquid：(100.0, 'mg')、(400.0, 'mg')（strict）
- `MX-079M2022` IBUPROFENO ／ `ibuprofeno`/capsule：(400.0, 'mg')、(600.0, 'mg')（strict）
- `MX-139M2022` Metilfenidato ／ `metilfenidato`/tablet：(10.0, 'mg')、(18.0, 'mg')、(27.0, 'mg')、(36.0, 'mg')、(54.0, 'mg')（strict）
- `MX-189M2022` OMEPRAZOL ／ `omeprazol`/capsule：(20.0, 'mg')、(40.0, 'mg')（strict）

其他风险样例：`MX-163M2022 CLARITROMICINA solución 2500 mg`（INER 描述可能是每瓶总量而非每剂）、`MX-136M2022 Atropina solución 10 mg`（注射液安瓿含量）——这类液体/注射剂必须进人工核对清单（§5）。

### 3.8 `--apply` 的写入语义（本轮未执行，已在副本验证）

- 写 `product_component.strength_value/strength_unit`（仅 `ord=0` 且当前为空）。
- 来源写 `corroboration`：`source_type='provincial_list'`（现有 schema 允许值中最贴近「公立机构目录/采购清单」，ISSSTE 现用同类值）、`url='ccby:<key>'`、`verified_by='etl/ingest_mx_ccby.py'`、`note='浓度回填自 mx_ccby:<key>'`；每个支撑数据集一行，可多行。
- 注册 `source` 行：`inprfm_ccby` / `hgmg_ccby` / `iner_ccby` / `semar_ccby`（名称、数据集页、CC BY 4.0、抓取日）。
- **不覆盖 `product.source_id/source_url`**：那是产品身份出处（COFEPRIS），覆盖会污染产品本体来源；浓度出处走 corroboration 是现有设计（`ingest_mx.py` 的 ISSSTE/PROFECO 也这么做）。
- 每轮写 `ingest_run`（run_id=`mx_ccby-<date>`，note 为统计 JSON）。事务包裹，异常 rollback。

## 4. B) Wikidata ATC 补全

### 4.1 数据源、许可与缓存

- 来源：Wikidata Query Service 一次 SPARQL；缓存 `data/raw/wikidata/atc_p267.json`：**10,425 行 / 3,764 个药物 / 4,371 个 ATC 码**（含 P267、P715 DrugBank、P231 CAS、en/es/zh 标签）。
- 许可：**CC0 1.0**（公共领域贡献）→ 可再发布/可改编。本站只取 P267 码值做对齐，**不复制 WHOCC 受版权保护的 ATC/DDD 文本**；`atc_name` 用 Wikidata 英文标签（INN 名），不是 WHOCC 原文。
- `P715`/`P231` 本次只缓存备用：`substance` 表没有 DrugBank/CAS 列，暂不参与匹配（未来可加列再启用）。

### 4.2 匹配策略与歧义处理（只补空，按可靠性分层）

| 路径 | 规则 | 命中 |
|---|---|---:|
| en_exact | `inn_en` 归一后 = 英文标签 | 311 |
| en_base | `inn_en` 去盐/酯后缀后 = 英文标签（如 `metformin hydrochloride`→`metformin`） | 255 |
| zh_exact | `inn_zh` = 中文标签（本库缺 ATC 的成分暂无中文名，本轮 0） | 0 |
| mx_es_slug | `substance_id=mx-es-<slug>` 的西语名 = 西语标签 | 27 |
| es_fallback | `inn_en` 本身是西语写法（含 de/la/y）→ 西语标签 | 1 |
| **歧义跳过** | 同一名字多个 ATC 且无唯一 7 位完整码（如阿司匹林 N02BA01/B01AC06/A01AD05） | 127 |
| 未匹配 | — | 6,816 |

歧义规则：一名字命中多码时，**恰好一个 7 位完整码**才采用；否则只有**唯一一个码**才采用；其余跳过（宁可缺，不可错）。一个成分只写一个 ATC。

### 4.3 dry-run 结果

- 成分 13,288，有 ATC 5,751（43.3%），缺 7,537（其中 `mx-es-` 专属 754，有中文名 0）。
- **可补 594 个成分 → 覆盖率 43.3% → 47.7%**（5,751 → 6,345 / 13,288）。
- 缺口大头仍未解：6,816 个成分在 Wikidata 无同名实体（多为商品名/复方/小语种名），且 754 个 `mx-es-` 里仅 27 个能对上西语标签——ATC 覆盖提升主要靠更全的公开 ATC 来源，不是名字技巧。

### 4.4 抽样 20 条（完整 594 条见 `.tmp/mx-atc/wikidata_atc_dryrun.json` 的 `all_hits`）

| # | substance_id | inn_en | atc | atc_name | 路径 |
|---:|---|---|---|---|---|
| 1 | benzonatate | Benzonatate | R05DB01 | benzonatate | en_exact |
| 2 | carisoprodol | Carisoprodol | M03BA02 | carisoprodol | en_exact |
| 3 | sulconazole | Sulconazole | D01AC09 | sulconazole | en_exact |
| 4 | balsalazide | Balsalazide | A07EC04 | balsalazide | en_exact |
| 5 | dalfampridine | Dalfampridine | N07XX07 | dalfampridine | en_exact |
| 6 | methylergonovine | Methylergonovine | G02AB01 | methylergonovine | en_exact |
| 7 | droxidopa | Droxidopa | C01CA27 | droxidopa | en_exact |
| 8 | isocarboxazid | Isocarboxazid | N06AF01 | isocarboxazid | en_exact |
| 9 | tavaborole | Tavaborole | D01AE24 | tavaborole | en_exact |
| 10 | cevimeline | Cevimeline | N07AX03 | cevimeline | en_exact |
| 11 | propyphenazone | Propyphenazone | N02BB04 | propyphenazone | en_exact |
| 12 | niacinamide | Niacinamide | A11HA01 | niacinamide | en_exact |
| 13 | sodium-chlorite | Sodium Chlorite | D03AX11 | sodium chlorite | en_exact |
| 14 | benznidazole | Benznidazole | P01CA02 | benznidazole | en_exact |
| 15 | armodafinil | Armodafinil | N06BA13 | armodafinil | en_exact |
| 16 | methylcobalamin | Methylcobalamin | B03BA05 | methylcobalamin | en_exact |
| 17 | tazobactam | Tazobactam | J01CG02 | tazobactam | en_exact |
| 18 | nalmefene | Nalmefene | N07BB05 | nalmefene | en_exact |
| 19 | chlophedianol | Chlophedianol | R05DB10 | chlophedianol | en_exact |
| 20 | isradipine | Isradipine | C08CA03 | isradipine | en_exact |

### 4.5 `--apply` 的写入语义（本轮未执行，已在副本验证）

- `UPDATE substance SET atc=?, atc_name=COALESCE(NULLIF(atc_name,''), ?) WHERE substance_id=? AND (atc IS NULL OR atc='')`：只补空、不覆盖已有 ATC；`atc_name` 为空才填。
- 批次级出处：`source` 表 `wikidata_atc_p267`（CC0、属性页 URL、今日）；`ingest_run` 一行（note 为统计 JSON + 缓存抓取时间）。
- **schema 没有 `substance.source_id` 列**，无法逐条记来源 → 报告里明确写出这个限制；复现路径 = 缓存 sha256 + 脚本版本 + ingest_run。若要逐条 provenance，需改 schema（下一轮评估）。

## 5. 人工核对清单（≥50 条，分层抽样）

50 条清单已生成，可直接分批人工核对：

- `.tmp/mx-atc/mx_verify_50.csv`：50 条 MX（按「规则 × 剂型」分层：strict/tablet、strict/liquid、strict/injection、strict/capsule、relaxed…；含 product_id、西语名、剂型、回填值、来源数据集、核对要点）。
- `.tmp/mx-atc/atc_verify_50.csv`：50 条 ATC（按路径分层：en_exact / en_base / mx_es_slug / es_fallback；含候选码集合与核对要点）。**再加**歧义样例 15 条（`.tmp/mx-atc/wikidata_atc_dryrun.json` 的 `ambiguous`）用来确认「多码跳过」没有误杀。

建议的核对方法（每条 1–2 分钟，两人交叉 20%）：

1. MX 每条用 `product_id` 里的 COFEPRIS 注册号去查该注册的说明书/药监页；或横向查 ISSSTE/PROFECO/同名药规格。重点：**单剂含量 vs 每包装总量 vs 每 mL 含量**。
2. 剂型边界：`tablet` 的缓释/肠溶要与原研规格对照；`liquid`（solución/suspensión/jarabe）若回填的是 `mg` 且源描述含「cada 5 ml」，一律标记为可疑，改为不写。
3. 复方/盐类：确认回填的是同一盐型（如「Diclofenaco sódico」不应套到「Diclofenaco potásico」的 ATC/剂量；ATC 层盐类可共用母体码，但需抽样确认）。
4. ATC 每条打开 Wikidata 实体页核对 P267 值（`https://www.wikidata.org/wiki/Property:P267`）；`en_base` 路径要确认「母体 ATC 适用该盐」。
5. 判定标准：≥95% 无错才建议 `--apply`；错误集中在某条规则时先收紧规则再跑，不做人工补丁。

## 6. 幂等与回滚（已在 `data/drugs.db` **副本** 实测，未触碰真实库）

| 步骤 | MX 有浓度组件 | ATC 有码成分 | 说明 |
|---|---:|---:|---|
| 初始副本 | 3,161 | 5,751 | 与真实库一致 |
| MX `--apply` #1 | 4,124 | 5,751 | 写 963 产品/963 组件、1,178 行 corroboration |
| MX `--apply` #2 | 4,124 | 5,751 | 写 0（已填跳过） |
| MX `--rollback` | 3,161 | 5,751 | 还原 963 组件、删 1,178 行 corroboration |
| ATC `--apply` #1 | — | 6,345 | 写 594 |
| ATC `--apply` #2 | — | 6,345 | 写 0 |
| ATC `--rollback` | — | 5,751 | 按 apply 清单还原 594 |

- **幂等**：两条 ETL 都只写「当前为空」的行（`pc.strength_value IS NULL` / `atc IS NULL`），重跑第二次写入 0；报告与 dry-run 数字可复现。
- **事务**：`--apply` 全程包在一个事务里，异常 `rollback`（不会留半截数据）；实测副本 `PRAGMA integrity_check=ok`、`foreign_key_check` 空。
- **回滚**：MX 用 `corroboration.verified_by` 定位（自描述、在库内）；ATC 用 apply 时写出的清单 `data/raw/wikidata/applied_wikidata_atc.json`（schema 无 provenance 列，回滚**不重算匹配**，避免误伤库里原有 ATC；清单缺失时脚本拒绝回滚，提示从 `data/backups/` 恢复）。
- 注意：若回滚前跑过全量重建（`ingest_mx.py` 会清空 MX corroboration），MX 回滚将无事可做；此时以重建为准，重新跑本 ETL 即可。

## 7. 许可与署名

- **4 个 CKAN 数据集**：CC-BY-4.0（`https://creativecommons.org/licenses/by/4.0/`）。本站做了字段归一、噪声清洗与抽样回填 → **属改编（adapted）**。再发布时需署名「Gobierno de México — datos.gob.mx，INPRFM / HGMGG / INER / SEMAR，CC BY 4.0；本站做了字段归一与浓度回填（改编）」并链接许可与数据集页。
- **Wikidata**：CC0 1.0，无署名义务；本站仍会在 About 页注明来源与「不含 WHOCC 授权内容」。
- 建议在 `site/build.py` 的 About/数据来源块加两行（Lead 决定文案）：
  - `MX 浓度：ISSSTE、PROFECO、datos.gob.mx（INPRFM/HGMGG/INER/SEMAR，CC BY 4.0，改编）；空值代表公开数据里没有唯一值`
  - `ATC：Wikidata P267（CC0）；不使用/不复制 WHOCC ATC/DDD 受版权保护内容`
- 缓存里的 `meta.json` 已记录 license/license_url/retrieved_at/resource_id，报告与站点可引用。

## 8. 与 `site/build.py` 的配合（本轮未改 build.py / site/dist）

仓库里 `site/build.py` 与 `site/dist/` 由 Lead/其他智能体在用，本轮**未触碰**。后续建议顺序：

1. 人工核对 50+ 条（§5），必要时先收紧规则再重跑 dry-run。
2. `python etl/ingest_mx_ccby.py --apply && python etl/ingest_wikidata_atc.py --apply`（建议先备份 `data/drugs.db` 到 `data/backups/`：现有 450MB 副本约 1 秒级拷贝）。
3. 复核：MX 产品级 28.7% → 37.6%、组件级 23.2% → 30.3%；ATC 43.3% → 47.7%；`ingest_run` 各多一行。
4. 由 Lead 跑 `site/build.py` → 重新生成 `site/dist` → 发布 v0.3.x（本轮不做，也不该由子智能体做）。
5. 站点文案口径：MX 写「公开采购/目录数据，唯一值才回填，空是数据事实」；ATC 写「Wikidata CC0，不含 WHOCC 授权内容」。覆盖率数字用「当前快照预估」，不要写成承诺。

## 9. 风险与限制

1. **数据语义**：4 份都是「某机构某次采购」明细，不是墨西哥全量浓度表；同名同剂型唯一值才写，冲突不写。抽样里液体/注射剂（Claritromicina 2500 mg、Atropina 10 mg）提示「每瓶总量 vs 每剂」风险真实存在，人工核对前不建议 apply。
2. **剂型边界**：放宽规则只对固体制剂生效；液体/注射剂不跨剂型，覆盖提升有限（预期内）。
3. **ATC 来源**：Wikidata 覆盖面有限（3,764 个药物 / 4,371 码），本轮 +594 已是名字匹配上限附近；`atc_name` 是标签近似，不是 WHOCC 官方名；127 个多码歧义按规则跳过。
4. **provenance**：`substance` 无 source 列（ATC 只能批次级记来源）；MX 的 corroboration 是表级现成方案。
5. **回滚语义**：回滚假设「自 apply 后没有其他 ETL 覆盖同一字段」；被覆盖后以最后一次 ETL 的 corroboration/清单为准（见 §6）。
6. **合规**：CC-BY-4.0 需署名+改编声明；上线 About 页前请 Lead 确认文案。

## 10. 复现与证据索引

```bash
python etl/fetch_mx_ccby.py --download
python etl/fetch_wikidata_atc.py --download
python etl/ingest_mx_ccby.py --dry-run
python etl/ingest_wikidata_atc.py --dry-run
# 副本演练：
cp data/drugs.db .tmp/mx-atc/test_apply.db
python etl/ingest_mx_ccby.py --apply --db .tmp/mx-atc/test_apply.db
```

- `.tmp/mx-atc/mx_ccby_dryrun.json`（963 条明细 + 冲突 + 覆盖率）
- `.tmp/mx-atc/wikidata_atc_dryrun.json`（594 条明细 + 歧义 + 覆盖率）
- `.tmp/mx-atc/mx_verify_50.csv` / `atc_verify_50.csv`（人工核对清单 50 条）
- `.tmp/mx-atc/APPLY_TEST.md`（apply/幂等/回滚实测）、`CACHE_SHA256.md`（缓存校验和）
- `data/raw/mx/ccby/meta.json`、`data/raw/wikidata/meta.json`（许可/抓取时间）

---

_本报告由并行实现子智能体 impl-mx-atc 生成；本轮 dry-run，`data/drugs.db` 未被写入；`site/build.py`、`site/dist/`、git 均未触碰。_
