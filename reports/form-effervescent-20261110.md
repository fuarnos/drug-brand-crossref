# 泡腾剂（effervescent）定位调查与实施方案

> 日期：2026-11-10 ｜ 状态：**只读调查 + 实施方案**（未改 `site/build.py`、未改 `data/drugs.db`、未建站、未发布）
> 触发：GitHub issue（3 天前）——搜「力度伸」→ 站点显示**片剂**，用户问「这是 VC 泡腾片，为什么变成片剂了」（`?q=力度伸&country=SG`）
> 复核口径：本文数字都是 2026-11-10 用 `& $py db/q.py` 现查（含一次自我修正，见 §1.3 末尾「复核记录」）；命令随文给出，可直接重跑。
> 关联：`reports/normalization-prep-20261107.md`（form_base 876→32 归一化 dry-run，**尚未落库**）、`docs/谷段需求队列.md` task-148、`db/consistency_audit_form.py`（已存在的剂型一致性审计）、`reports/cn-data-intuition-audit.md` §3

---

## 0. 结论

**一句话**：**新增 `effervescent` 一个剂型 class（方案 A），判定规则来自来源原文的泡腾字样（7 种拼写），全库只动 948 行产品（0.199%），不手工标注任何一条。**

三条判断：

1. **这不是归一化 bug，是 class 集合缺一个格子**：`form_base` 的实现里根本没有「泡腾」分支，泡腾在四个地方被上游的「片/錠/tablet」先吃掉（共享 `form_base_of` 的关键字顺序、CN 的 `translate_form`、ES 的 `form_base_es`、TW 的 `tw_form_base`）。库里有 **948 行**产品的**来源原文已经写了泡腾**，只是 class 没接住。而且仓库里**已经有一个剂型一致性审计**（`db/consistency_audit_form.py`，未入库，非本次会话所写）把这件事判成 `gap` 并写好了 `target="effervescent"`——本方案就是把它那条规则落地，不另造口径（§1.5）。
2. **CN 力度伸 那两行，规则推不出来**：来源 `dosage_form=片剂`、商品名「力度伸」不含任何剂型词、包装只写「铝管包装，10片/盒」。三种规则都在现库上跑过（名称剂型词冲突、同 key 跨市场冲突、包装铝管启发式），**没有一条命中它**；能落地的诚实做法是「来源原文并列 + 来源粒度说明」，要让 CN 力度伸真的显示泡腾，只剩「品牌家族」这张唯一允许的人工表（需人拍板，见 §3.3 R2）。
3. **「名称与来源剂型不一致」横幅现在不要上**：宽口径命中 960 行，真冲突约 10 条，其余是分类学伪冲突（品牌名含「栓/散/贴」字、给药途径被塞进 form、双剂型名）。上它会一天刷出近千条噪声，**且不含用户报的那一条**。

方案 A 的影响面（现查，7 种拼写口径）：

| 指标 | 数字 | 口径 |
|---|---:|---|
| 改写的 `product` 行 | **948** | 占 477,098 的 **0.199%** |
| 其中 现 `tablet` / `powder` / `liquid` | **828 / 92 / 28** | 泡腾片 / 泡腾颗粒（散） / 泡腾溶液 |
| 来源分布（11 源） | dmd 256 · artg_export 193 · openfda_ndc 139 · cima 125 · nhsa 107 · hc_dpd 41 · artg_detail 37 · **tfda_tw 28** · cofepris_mx 12 · hsa_sg 9 · pbs 1 | 一源一列 |
| 市场分布（9 市场） | GB 256 · AU 231 · US 139 · ES 125 · CN 107 · CA 41 · **TW 28** · MX 12 · SG 9 | HK 0 行 |
| 检索标签会变的 name_key | **806** | `index` 里 `f` 从 `["tablet"]`/`["powder"]`/`["liquid"]` 变 `["effervescent"]` |
| 成分页会多一行矩阵 / 一个筛选选项 | **204** 个成分（共 12,431 个有产品的成分页） | 1.6% |
| 现在被合并、改后要拆开的矩阵行 | **145** 行（同成分×同释放×同规格里泡腾与非泡腾混在一起） | 矩阵 key = 规格+剂型+释放 |
| 单包装名字页（走 raw form 表格的） | **484** 个 key | 这些页当前会打印英文原码 |
| 需要新增的四语标签 | **1 个 key × 4 语言**（+2 个披露文案 key） | `LABEL_I18N` |
| 现有测试会变红 | **0 套**（没有测试覆盖 `form_base_of`）；`deploy/i18n_check.py` 会红，如果漏加语言 | 见 §2.3 |

---

## 1. 归一化在哪、怎么归类、class 全集、测试覆盖

### 1.1 一处共享实现 + 5 处分叉（谁在写 `form_base`）

单一实现是 **`etl/ingest_openfda_ndc.py:96-115`**：

```python
FORM_BASES = (
    ("tablet", ("tablet", "caplet", "lozenge", "troche")),      # ← 「Tablet, effervescent」在这里就命中
    ("capsule", ("capsule", "gelcap", "softgel")),
    ("liquid", (...)), ("injection", (...)), ("topical", (...)),
    ("inhalation", (...)), ("suppository", ("suppository", "enema")),
    ("powder", ("powder", "granule", "packet")),
)

def form_base_of(form: str) -> str:
    f = (form or "").lower()
    for base, keys in FORM_BASES:
        if any(k in f for k in keys):
            return base
    return f or "unknown"        # ← 认不出的原样返回：875 个取值的长尾全是这条兜底
```

分叉（同一个概念有 5 套实现，改 class 必须一起改）：

| # | 文件 / 函数 | 行 | 用途 | 泡腾现状 |
|---|---|---|---|---|
| 1 | `etl/ingest_openfda_ndc.py` `FORM_BASES` + `form_base_of()` | 96-115 | US 原始入库；被 `ingest_dmd` / `ingest_ca_dpd` / `ingest_cima` / `ingest_nhsa` / `ingest_pbs` / `ingest_sg_hsa` / `ingest_artg_details` / `ingest_artg_enrich` / `fix_cn_combos` 复用（**9 处 import**） | tablet 先命中 |
| 2 | `etl/ingest_artg_medicines.py` `form_base_of()`（**自己的副本**，`FORM_BASE` 是 `(keys, base)` 反序） | 109-114 | AU `artg_export` 193 行 | tablet 先命中 |
| 3 | `etl/ingest_mx.py` `FORM_BASES` + `form_base_es()`；同文件 `SOLID_BASES = {"tablet","capsule","powder"}` | 68-92 | MX 12 行 | tablet / powder |
| 4 | `etl/ingest_cima.py` `FORM_ES_EN` + `form_base_es()` | 731-760 / 884-897 | ES 125 行（`efervescente` 已翻成 `effervescent`，但 `form_base_of` 不认这个词） | tablet 106 / liquid 28（**注意：`液`先命中时连泡腾也丢**） |
| 5 | `etl/ingest_nhsa.py` `FORM_ZH_EN` + `translate_form()` | 1304-1314 / 1386-1392 | CN 145,051 行；**首个命中即返回**，`片` 在列表里 | `片剂(泡腾)` → `tablet` |
| 6 | `etl/ingest_tw_tfda.py` `FORM_MAP` + `tw_form_base()` | 377-394 | TW 16,457 行 | `發泡錠` → tablet（`錠` 先命中）、`發泡顆粒劑` → powder |
| — | `etl/cleanup_cn_data.py` `CANON_FORMS` / `FORM_MAP` | 44-72 | CN 清洗白名单（15 个 canonical 值）；非白名单会被当长尾重写 | 白名单里没有 effervescent |
| — | `etl/build_translation_tables.py` `EXTRA_FORMS` | 318-340 | 剂型五语（含 pt）参考译名 → `data/sources/` 快照 | 无 effervescent 行 |
| — | `db/atc4_forms.py` `KEEP_FORMS_DEFAULT=30` | 29-50 | ATC4 页「剂型 × 市场」事实表 | 按 product 数取前 30，泡腾会自己进来（rank 15） |

### 1.2 class 全集（现查）

```powershell
& $py db/q.py "SELECT COUNT(*), COUNT(DISTINCT form_base) FROM product"          -- 477,098 / 875
& $py db/q.py "SELECT COUNT(*) FROM product WHERE form_base IS NULL"             -- 13,935（全部 HK）→ 含 NULL 共 876 个取值
& $py db/q.py "SELECT form_base, COUNT(*) n FROM product GROUP BY 1 ORDER BY n DESC"
```

**受控值只有 8 个关键字分支**（tablet / capsule / liquid / injection / topical / inhalation / suppository / powder），其余全是 `form_base_of()` 的 free-text 兜底——「class 全集」实际是「8 个 canonical + 867 个来源原样字符串 + NULL」：

| 档 | 取值数 | 说明 |
|---|---:|---|
| 前 30 个（像枚举的） | 30 | tablet 181,973 · injection 71,443 · liquid 70,190 · capsule 55,070 · topical 43,269 ·（空串，全 HK）13,935 · powder 10,409 · pellet 7,337 · unknown 5,872 · inhalation 3,096 · stick 2,491 · kit 2,247 · suppository 1,729 · gas 986 · cloth 602 · soap 416 · pill 390 · swab 370 · mouthwash 328 · gum, chewing 320 · globule 290 · oil 278 · other 255 · rinse 194 · jelly 193 · lipstick 149 · nasal 147 · inhalant 106 · pastille 105 · salve 83 |
| 长尾 | 845 | GB/AU 的自由文本（`oxygen cylinders …` 90 个取值、`salicylic acid … in white soft paraffin` 122 个取值…）。task-148 的 876→32 归一化就是冲这一档去的，**目前只在副本上 dry-run，正式库没改**（`reports/normalization-prep-20261107.md` §2；`db/`、`etl/` 下都没有对应的 apply 脚本） |

> 关键：**`effervescent` 今天既不在 canonical 8 个里，也不在 876 个长尾里**——它从来没被写进 `form_base`，只存在于 `dosage_form`。

### 1.3 泡腾在四处被吃掉（复现）

```powershell
# 1) 共享实现：tablet 排在前面
& $py -c "import sys; sys.path.insert(0,'etl'); from ingest_openfda_ndc import form_base_of; print('A', form_base_of('Tablet, effervescent'), form_base_of('Tablet (Effervescent)'), form_base_of('granule, effervescent'))"
-- A tablet tablet powder

# 2) CN：第一个命中的中文剂型词是「片」
& $py -c "import sys; sys.path.insert(0,'etl'); from ingest_nhsa import translate_form; print('B', translate_form('片剂(泡腾)'), translate_form('颗粒剂(泡腾)'))"
-- B tablet granule

# 3) ES：翻成英文了，但 form_base_of 不认 effervescent
& $py -c "import sys; sys.path.insert(0,'etl'); from ingest_cima import form_base_es; print('C', form_base_es('comprimido efervescente'))"
-- C tablet

# 4) TW：錠 先命中
& $py db/q.py "SELECT dosage_form, form_base, COUNT(*) FROM product WHERE country='TW' AND (dosage_form LIKE '%發泡%' OR dosage_form LIKE '%泡騰%') GROUP BY 1,2"
-- 發泡錠 | tablet | 20    ／    發泡顆粒劑 | powder | 8
```

现库分布（**7 种拼写**：effervesc / efervesc / 泡腾 / 泡騰 / 發泡 / 发泡 / fizzy）：

```powershell
$E = "lower(dosage_form) LIKE '%effervesc%' OR lower(dosage_form) LIKE '%efervesc%' OR dosage_form LIKE '%泡腾%' OR dosage_form LIKE '%泡騰%' OR dosage_form LIKE '%發泡%' OR dosage_form LIKE '%发泡%' OR lower(dosage_form) LIKE '%fizzy%'"
& $py db/q.py "SELECT form_base, COUNT(*) n FROM product WHERE $E GROUP BY 1 ORDER BY 2 DESC"       -- tablet 828 / powder 92 / liquid 28（948）
& $py db/q.py "SELECT country, COUNT(*) n FROM product WHERE $E GROUP BY 1 ORDER BY 2 DESC"         -- GB256 AU231 US139 ES125 CN107 CA41 TW28 MX12 SG9
& $py db/q.py "SELECT source_id, COUNT(*) n FROM product WHERE $E GROUP BY 1 ORDER BY 2 DESC"       -- dmd256 artg_export193 openfda139 cima125 nhsa107 hc_dpd41 artg_detail37 tfda_tw28 cofepris_mx12 hsa_sg9 pbs1
```

> **复核记录（自我修正）**：第一版调查只用 `effervescent|efervesc|泡腾` 三种写法，得 920 行，并据此写了「TW 0 条，本期不改 TW 的入库脚本」——**这是错的**。仓库里已有的 `db/consistency_audit_form.py` 用的是 `effervescen|efervescen|泡腾|泡騰|發泡|发泡|fizzy`，跑出来 947 行（它按「族优先级 first-match」，比 SQL 少 1 行）。补上繁体写法后 **948 行、TW 28 行**，TW 的 `ingest_tw_tfda.py` 因此**必须改**。issue 里给的 702/81 是只算英文 `effervescent` 一档的口径（676 行），三者口径差异全部由拼写集合解释。

### 1.4 测试覆盖：**0**

```powershell
Select-String -Path etl\test_*.py,lib\test_*.py,tests\*.py -Pattern 'form_base_of|FORM_BASES|effervesc'
-- 无匹配（`lib/test_search*.py` 只在 fixture 里 INSERT form_base='tablet'，不复核取值）
```

四套测试的职责里没有剂型归一化：`etl`（名称归一 / 各入库）、`lib`（检索 / 碰撞）、`tests/test_mobile_inbox.py`、`tests/trilingual`（三语检索一致性）。
`tests/test_lib_atc_category.py` 是 **ATC 码 / 16 大类**的快照测试，与剂型无关，**不会因为这个改动变红**。
唯一会红的是 **`deploy/i18n_check.py`（四语键集一致性门禁；`LABEL_I18N` 必须四语齐全）**——见 §2.3。

**这是既有缺口**：`form_base_of()` 是 9 个入库脚本共用的核心函数，却没有一条单测；建议随本次改动补 `etl/test_form_base.py`（6 条断言，见 §5.1）。

### 1.5 仓库里已经有一个剂型一致性审计（本次改动的权威出处）

`db/consistency_audit_form.py`（**未入库文件，非本次会话所写**，只读开库、7 条规则 R1-R7、可 `--json` 复跑）已经把「来源原文剂型族 × form_base」做成规则表，共 **22 个剂型族**，其中：

```python
Family("effervescent", "effervescent", "泡腾（片/颗粒）", _pat(
    r"effervescen", r"efervescen", r"泡腾", r"泡騰", r"發泡", r"发泡", r"fizzy"),
    ok=frozenset(), coarse=frozenset(), gap=frozenset({"powder"}),
    target="effervescent"),
```

它的 R1 现行输出（`& $py db/consistency_audit_form.py --only R1`）：

| 项 | 数字 |
|---|---:|
| R1 非 ok 总计 | 30,330（ok 424,775 / **conflict 22,627** / **gap 5,509** / coarse 1,711 / unmapped 2,194） |
| `effervescent` 族 | **947 行**：tablet 827 · powder 92 · liquid 28；判定 conflict 855 / gap 92；`target="effervescent"` |
| 最大 conflict 格 | `injection, solution → liquid` **15,570 行**（比泡腾大一个量级，是下一件事） |

**结论**：方案 A 的 class 名（`effervescent`）、判定谓词、目标值在这份审计里都已定好，**实施时直接 import 它的 `FAMILIES`/正则，不要另写一套**——否则 build 层、迁移脚本、审计三处规则会漂移（这正是仓库里 form 逻辑已有的病：5 套实现）。

---

## 2. 泡腾算不算一个独立剂型

### 2.1 事实基础：它不只是「显示不好看」，而是身份键

`form_base` 是**身份键**的两处成员：

1. `site/build.py:7275` 成分页矩阵行键 `spec = (归一后规格, form_base or dosage_form, release)` → 同成分、同规格、同释放的泡腾片与普通片**合成一行**；
2. `lib/search.py:622` 结果签名 `sig = (country, form_base, release, 成分组合)` → 它们**合成一张卡**。

也就是说，AGENTS §1.1 承诺的「一行 = 国家 × 剂型 × 规格 × 成分」对泡腾**不成立**：泡腾片与普通片被列成同一行，读者会读成「互相对应」。这是方案 A 的真正理由。

现查（改前基线，见 §6.1 R4a）：

```powershell
& $py db/q.py "…GROUP BY substance,release,规格 的混合行…"
-- 同 (substance, release, 规格) 分组里泡腾与非泡腾混在一起：145 行；纯泡腾组：125；含泡腾的组：270
```

### 2.2 三方案对比

| | **A：新增 `effervescent` class** | **B：沿用 tablet + 显示提示** | **A′：不动 form_base，加 `form_modifier` 列** |
|---|---|---|---|
| 数据改动 | 948 行 `UPDATE`（规则派生，无人工标注） | 0 行 | `ALTER TABLE ADD COLUMN` + 948 行写入 |
| ETL 改动 | 7 处关键字/映射（§5.1） | 0 处 | 7 处 + 各入库脚本写新列 |
| 显示改动 | 1 个标签 + `_FORM_WORD_ZH`/`_form_rank` | 3 个显示面都要拼「片剂 · 泡腾」 | 同上（可拼「泡腾片 / 泡腾颗粒」，粒度最细） |
| 检索标签变化 | **806 个 key** 变 effervescent | 0（卡片仍 tablet，只加文案尾巴） | 0 |
| 矩阵行 | **+145 行**（拆开混装行），204 个成分页受影响 | 不变（错误合并不消除） | +145 行 |
| 剂型筛选器 | 有泡腾产品的页多 1 个选项 | 不变 | 多 1 个选项 |
| ATC4 页 | 剂型榜 **rank 15**（948 行，前 14 个值都 >948）→ 进 top-30，挤掉 `salve`/`pastille` 一档到 `other`；需重生成快照 | 不变 | 同 A |
| 丢信息 | 丢「片 vs 颗粒」细分（92 行 powder 变泡腾剂） | 不丢 | 不丢（二维都留） |
| i18n 成本 | 1 键 × 4 语 | 1 键 × 4 语 | 2 键 × 4 语 |
| schema 迁移 | 无（`form_base` 已有） | 无 | 有（新列 + `init_db.py` 幂等 `ADD COLUMN`） |
| 与 task-148（876→32）的关系 | 必须把 `effervescent` 加进那 32 类的目标集，否则归一化一跑就被并回 tablet | 无冲突 | 无冲突，但归一化只收敛 `form_base`，修饰列仍在 |

**推荐 A。一句话理由**：泡腾是来源自己写出来的剂型（948 行、7 种拼写、11 个来源），规则可判且审计工具已给出 `target`；把它并进 `tablet` 会让成分页把两种不可互换的给药形态列成同一行（违反 AGENTS §1.1），而 A 是唯一在不手工标注的前提下同时修掉「身份错误」和用户看到的那句「片剂」的方案。

A 的三个代价，必须写进 CHANGELOG，别藏：

1. **92 行泡腾颗粒（散）**（如 GB `Ispaghula husk 3.5g effervescent granules sachets`、TW `發泡顆粒劑`）从 `powder` 变 `effervescent`，颗粒/散剂的区分在 `form_base` 层就没了（`dosage_form` 原文还在，页面并列显示，见 §3.3 R1）；
2. **ATC4 事实表快照要重生成**（`data/sources/atc4_forms_20261031.json`，受版本控制，1.21 MB）；
3. **`SOLID_BASES`**（`etl/ingest_mx.py:92`，放宽浓度匹配的固体制剂集合）要把 `effervescent` 加进去，否则 MX 12 行会掉出固体制剂的规格规则分支。

> 若将来要同时保留「给药形态」和「是否泡腾」两个维度，再升级到 A′（`form_modifier TEXT`，值域 `effervescent` / NULL），那时可做到「泡腾片 / 泡腾颗粒」两级标签。那是下一件事，别和这次混做。

### 2.3 会不会红：四套测试不动，i18n 门禁必须同步

| 门禁 | 结果 | 说明 |
|---|---|---|
| `etl` unittest | 绿 | 无 `form_base_of` 覆盖（建议本次补） |
| `lib` unittest | 绿 | fixture 自造行 |
| `tests/test_lib_atc_category.py` | 绿 | ATC 大类快照，与剂型无关 |
| `tests/test_mobile_inbox.py` | 绿 | 无关 |
| `tests/trilingual/run_tests.py` | 绿 | 只查三语检索一致性，不断言剂型 |
| **`deploy/i18n_check.py`** | **红（若漏语言）** | `LABEL_I18N` 不在 `ZH_HANT_FROM_JSON` 名单里 → **en/es/zh/zh-Hant 四份都必须有** `form.effervescent`；`es` 值不能等于 `en`（否则 FAIL「与英文完全相同」） |
| `deploy/ci_checks.py --fast` | 绿 | 不校验 `form_base` 枚举 |
| `db/check_data.py` | 绿（计数不变） | 只统计，不校验剂型取值 |
| `db/consistency_audit_form.py` | `effervescent` 族的 conflict 应降为 0、gap 归 0 | 改后可拿它当验收脚本（§6.1 R14） |

---

## 3. CN 力度伸 这类「来源原文与商品名矛盾」怎么处理

### 3.1 现库还原（力度伸只有 2 行，来源写得清清楚楚是片剂）

```powershell
& $py db/q.py "SELECT nk.norm, p.country, p.dosage_form, p.form_base, p.pack FROM name_key nk JOIN product_name pn ON pn.key_id=nk.key_id JOIN product p ON p.product_id=pn.product_id WHERE nk.norm LIKE '%力度伸%'"
-- 力度伸 | CN | 片剂 | tablet | 铝管包装，10片/盒
-- 力度伸 | CN | 片剂 | tablet | 铝管包装，30片/盒
& $py db/q.py "SELECT nk.norm, nv.raw FROM name_key nk JOIN name_variant nv ON nv.key_id=nk.key_id WHERE nk.norm LIKE '%力度伸%'"
-- 力度伸 | 力度伸      （name_variant 里也只有「力度伸」，没有「力度伸泡腾片」）
```

页面为什么显示「片剂」：力度伸有 2 个包装 → 不是单包装页 → 走名字页成分卡的 `_label_join('form', sorted(g['f']))`（`site/build.py:7675`，数据来自 `:7559` 的 `form_base or dosage_form`）→ `form.tablet` → **片剂**。检索结果行与身份卡走 `formLabelOf(e)`（`:3887`、`:4026`）读同一份 `f`。

**关键事实**：「泡腾」这两个字**在库存的任何字段里都不存在**——名称无剂型词、来源写片剂、包装写铝管。所以任何 build 层规则都推不出泡腾。同品牌其他市场（Redoxon）的 8 个 key 里确实有 4 个是泡腾（`redoxon cal` CA、`redoxon immunity blackcurrant` AU、GB 两条），但 `name_family` 里**没有** 力度伸↔redoxon 的家族行（`& $py db/q.py "SELECT * FROM name_family"` → 全库只有 9 行：tylenol×5 / benadryl×2 …）。

### 3.2 「名称剂型词 vs 来源剂型」规则实测：宽口径 960 行，真冲突约 10 条

规则：`name_key.norm` 里出现剂型词，且 `form_base` **不在**该词允许的集合里（`form_base` 为 NULL/unknown/other 视为「来源没记」，不计冲突）。

```powershell
& $py .tmp\form-effervescent-20261110\probe2.py   # 宽口径词表（含 片/丸/散/栓/贴 等单字）
-- 冲突 960 行 / 243 name_key，全部来自 CN(nhsa 817) 与 TW(tfda_tw 143)

& $py .tmp\form-effervescent-20261110\probe3.py   # 窄口径（只留无歧义剂型词）
-- 冲突 63 行 / 63 产品 / 25 name_key：胶囊 33 · 漱口 11 · 吸入 7 · 注射用 5 · 软胶囊 4 · 注射液 2 · 栓剂 1
```

宽口径 960 行的构成（逐条看过，按性质归类）：

| 性质 | 典型行 | 行数（约） | 该不该报「不一致」 |
|---|---|---:|---|
| **品牌名含剂型字**（假冲突） | `栓易通膜衣锭`（「栓」是品牌）、`散列通`/`唯散宁`（「散」是品牌）、`意可贴`/`贴鑫`（「贴」是品牌）、`阿片酊`（「片」是鸦片） | ~200 | 不该 |
| **给药途径被塞进 form**（分类学问题，非来源问题） | `醋酸氯己定溶液` 来源「洗剂」→ topical；`利巴韦林滴鼻液` 来源「鼻用制剂」→ topical；`硫酸阿托品眼用凝胶` 来源「眼用制剂」→ liquid | ~400 | 不该（该改映射） |
| **双剂型名** | `维生素ad滴剂 胶囊型` 来源「口服溶液剂」；`利福喷丁胶囊异烟肼片组合包装` 来源「组合包装」 | ~30 | 不该 |
| **我们的映射粗了一档** | `骨化三醇软胶囊` 来源「胶丸剂」→ pill；`漱口液` 来源「漱口劑」→ liquid（应 mouthwash）；`吸入用布地奈德混悬液` 来源「混悬剂」→ liquid（应 inhalation） | ~20 | 不该（修 ingest 映射更对） |
| **真·名源矛盾** | `氨咖黄敏胶囊` 来源「片剂」×7；`感克敏胶囊` 来源「錠劑」；`歐適達陰道栓剂` 来源「陰道錠」；`甘露醇注射液` 来源「冲洗剂」；`法瑞西单抗注射液` 来源「眼用制剂」 | **~10** | 该 |

**结论**：这条规则**不能**当本次的修复手段：
- 噪声/真值 ≈ 100:1，上横幅会一天刷出近千条提示；
- **它命中的 10 条真冲突里没有力度伸**（力度伸名字里没有剂型词）。

顺带否掉第三条思路：`pack LIKE '%铝管%'` 在 CN 有 **1,132 行**，其中 **1,130 行是乳膏剂/软膏剂/凝胶剂**（药膏管），只有 2 行「片剂 + 铝管」——正好是力度伸这两条。用铝管当泡腾信号会一次性误标 1,130 条，不可用。

### 3.3 三档处理方案（都不改单条数据）

| | 做法 | 覆盖力度伸？ | 数据风险 | 需要谁拍板 |
|---|---|---|---|---|
| **R1（推荐，本期就做）** | **并列显示来源原文**：名字页/单包装表的剂型列显示「标签 + 来源原文」（如「片剂 · 来源原文：片剂」「泡腾剂 · 来源原文：片剂(泡腾)」），并在 CN 名字页加一句**来源粒度说明**（中国来源只记到「片剂」这一层，不细分泡腾/薄膜衣） | ✅ 把「看起来像错的」变成「有出处的事实 + 粒度说明」 | 零（只加展示，不动数据） | agent 可自决 |
| **R2（唯一能让 CN 力度伸显示泡腾的路）** | 往**品牌家族表**（`name_family`，AGENTS §1.2 明确「只有品牌家族是人工表」）加 `力度伸 → redoxon`，然后 build 层规则：**同家族其他市场为泡腾剂、本行来源为 tablet → 提示「同品牌家族其他市场记为泡腾剂，本条来源只记片剂」** | ✅（redoxon 在 CA/AU/GB 有 4 个泡腾 key） | 中：改人工表 + 公开口径变更，且会波及 redoxon 家族 8 个 key 的页面 | **人** |
| **R3（本期不做）** | 「名称与来源剂型不一致」横幅 | ❌ | 高噪声（§3.2，100:1） | —— |

**给 issue 的回复口径**（建议原样用）：*「力度伸这条的来源原文就是『片剂』（医保目录的剂型只记到大类），此前我们把它直接映射成『片剂』标签，看起来像否定它是泡腾片。现在页面同时给出标签和来源原文，并说明中国来源的剂型粒度；同品牌的 Redoxon 在澳/英/加/西等市场的 948 条带泡腾字样的记录会显示为『泡腾剂』。」*

> 红线：R1/R2 只做**身份与出处**的呈现，不写「怎么吃」，不给替代建议。

---

## 4. 四语标签

**字典位置**：`site/build.py:845-890` 的 `LABEL_I18N`（`en`/`es`/`zh`/`zh-Hant` 四份，`form.*` 现各 13 键）。
服务端用 `_label_html()` / `_label_join()`（`site/build.py:7003-7015`）；客户端用 `labelOf('form', f, f)` / `formLabel()`（`:9481-9483`）、`T('form.'+f, f)`；未登记的键**自动回落原码**（不空白、不报错）。
另有 `data/i18n_zh_hant.json`（346 键，含 13 个 `form.*` 副本，**无生成脚本、人工维护**）与 `etl/build_translation_tables.py:318` 的 `EXTRA_FORMS`（多语参考译名，含 pt）。

**建议加的值**（class 名 `effervescent`，覆盖泡腾片 828 + 泡腾颗粒 92 + 泡腾溶液 28）：

| 语言 | key | 值 | 理由 |
|---|---|---|---|
| en | `form.effervescent` | `effervescent` | 与 tablet/powder 同级名词，来源原词 |
| es | `form.effervescent` | `efervescente` | CIMA 原文用词（`comprimido efervescente`）；≠ en，不触 i18n FAIL |
| zh | `form.effervescent` | `泡腾剂` | 与「片剂/栓剂/吸入剂」同构；**不用「泡腾片」**，否则 92 行泡腾颗粒被标成片 |
| zh-Hant | `form.effervescent` | `泡騰劑` | 同上；`泡騰劑` ≠ `泡腾剂`，不会踩「繁体未转换」 |

**为什么不照 issue 的「泡腾片 / effervescent tablet / comprimido efervescente / 發泡錠」**：那组是「泡腾**片**」的标签。本 class 里 92 行是泡腾**颗粒/散**（GB `Ispaghula husk … effervescent granules sachets`、TW `發泡顆粒劑`）、28 行是泡腾**溶液**（ES `solución/suspensión oral efervescente`），写「泡腾片/發泡錠」会制造一次**反向**的剂型错标——正是用户报的这个 bug 的镜像。
若产品侧坚持要「泡腾片」，正确做法是把 class 定为 `effervescent tablet`（只收 828 行片剂，颗粒留 `powder`），那是另一个口径，§2.1 的全体数字要重算。

**披露文案**（R1 用，四语）：

| key | en | es | zh | zh-Hant |
|---|---|---|---|---|
| `name.form_source` | `as recorded by source` | `según la fuente` | `来源原文` | `來源原文` |
| `name.form_granularity_cn` | `Source records dose form only at class level (e.g. "tablet"); effervescent/coated sub-forms are not distinguished.` | `La fuente registra solo la forma de nivel de clase (p. ej. «comprimido»); no distingue subformas como efervescente o recubierto.` | `来源只记到剂型大类（如「片剂」），不细分泡腾、薄膜衣等子剂型。` | `來源只記到劑型大類（如「錠劑」），不細分發泡、膜衣等子劑型。` |

---

## 5. 实施清单

> 顺序：**ETL 规则 → 单测 → 备份 → 迁移 dry-run → apply → 校验 → 快照 → build 补丁 → 建站验收 → 文档/CHANGELOG**。
> 动库前按 AGENTS §7 通知其他工位；同一时间只允许一个会话跑 `site/build.py`。

### 5.1 ETL：把「泡腾」接住（7 处，全部是规则，无人工标注）

| # | 文件 | 改什么 |
|---|---|---|
| E1 | `etl/ingest_openfda_ndc.py:96-115` | `FORM_BASES` **最前面**插 `("effervescent", ("effervesc", "efervesc", "泡腾", "泡騰", "發泡", "发泡", "fizzy"))`（顺序即优先级，必须在 tablet/powder 之前） |
| E2 | `etl/ingest_artg_medicines.py:109-114` | 同上，在 `FORM_BASE` 最前面插 `(("effervesc", "efervesc", "泡腾", "泡騰", "發泡", "发泡", "fizzy"), "effervescent")`（该文件是 `(keys, base)` 反序） |
| E3 | `etl/ingest_mx.py:68-92` | `FORM_BASES` 首行加 `("effervescent", ("efervesc", "effervesc"))`；**并且** `SOLID_BASES = {"tablet","capsule","powder","effervescent"}` |
| E4 | `etl/ingest_nhsa.py:1304-1314` | `FORM_ZH_EN` **首行**加 `("泡腾", "effervescent")`、`("泡騰", "effervescent")`（`translate_form` 首个命中即返回） |
| E5 | `etl/ingest_tw_tfda.py:377-394` | `FORM_MAP` **首行**加 `("effervescent", ("發泡", "发泡", "泡騰", "泡腾", "fizzy"))`（否则 `錠`/`顆粒` 先命中，TW 28 行改不出来） |
| E6 | `etl/cleanup_cn_data.py:44-46` | `CANON_FORMS` 增加 `"effervescent"`（否则下次跑 CN 清洗会把新值当长尾重写 / 在 `FORM_MAP` 查不到） |
| E7 | `etl/build_translation_tables.py:318-340` | `EXTRA_FORMS` 加 `("effervescent", "effervescent", "efervescente", "泡腾剂", "泡騰劑", "efervescente")`，重生成对应 `data/sources/` 快照 |
| **新增** | `etl/test_form_base.py` | 6 条断言：`Tablet, effervescent`→effervescent / `granule, effervescent`→effervescent / `comprimido efervescente`→effervescent / `片剂(泡腾)`→effervescent / `發泡錠`→effervescent / `Tablet, film coated`→tablet（防回归） |
| （说明） | `ingest_cima` / `ingest_dmd` / `ingest_ca_dpd` / `ingest_pbs` / `ingest_sg_hsa` / `ingest_artg_details` / `ingest_artg_enrich` / `fix_cn_combos` | **不用改**：`import form_base_of`，E1 一处生效 |
| （说明） | `db/consistency_audit_form.py` | **不用改**：它的 `effervescent` 族已经就是这条规则；实施后跑它验收即可（§6.1 R14） |

**若选择「重跑 ingest」而不是迁移脚本**：US `ingest_openfda_ndc`、GB `ingest_dmd`、CA `ingest_ca_dpd`、AU `ingest_artg_medicines`+`ingest_artg_details`+`ingest_pbs`、SG `ingest_sg_hsa`、ES `ingest_cima`、CN `ingest_nhsa`、MX `ingest_mx`、TW `ingest_tw_tfda`。代价：全量重跑几小时且会刷新 `retrieved_at` / 触发漂移；**因此推荐用迁移脚本一次改 948 行**，ETL 的 7 处改动保证「下次重跑不会退回去」。

### 5.2 迁移脚本：`etl/normalize_form_effervescent.py`（新增，仿 `cleanup_cn_data.py` 的 journal 模式）

```powershell
# 0) 备份（AGENTS §4：单独跑 ingest / 迁移不自动备份，必须手动）
Copy-Item data\drugs.db data\backups\drugs-20261110-pre-effervescent.db

# 1) dry-run（默认只读 + 只打印）
& $py etl/normalize_form_effervescent.py        # 948 行、按 form_base/来源/国家分布、10 条样例

# 2) apply（写 journal + 一条 UPDATE）
& $py etl/normalize_form_effervescent.py --apply

# 3) 校验（§6.1 R1-R5、R14）

# 4) 回滚（按 journal 逐行恢复 old form_base，幂等）
& $py etl/normalize_form_effervescent.py --rollback
```

脚本要点（照 `etl/cleanup_cn_data.py` 的既有做法，别另起一套）：

- 连接：dry-run 用 `file:...?mode=ro`；`--apply` 才用读写连接；
- **判定谓词单一来源**：从 `db/consistency_audit_form.py` 的 `effervescent` 族正则 import（或 `from etl.ingest_openfda_ndc import EFFERVESCENT_KEYS`），**不要在脚本里再写第三份正则**；
- SQL（apply 时）：
  ```sql
  UPDATE product SET form_base = 'effervescent'
   WHERE form_base <> 'effervescent'
     AND ( lower(dosage_form) LIKE '%effervesc%' OR lower(dosage_form) LIKE '%efervesc%'
        OR dosage_form LIKE '%泡腾%' OR dosage_form LIKE '%泡騰%'
        OR dosage_form LIKE '%發泡%' OR dosage_form LIKE '%发泡%'
        OR lower(dosage_form) LIKE '%fizzy%' );
  ```
- journal：`data/sources/form_effervescent_journal_20261110.csv`（`run_id, product_id, old_form_base, new_form_base, applied_at`），回滚按 `run_id` 反向 UPDATE；
- 幂等：二次 `--apply` 影响 0 行；
- 结束跑 `PRAGMA integrity_check` / `PRAGMA foreign_key_check`，`db/check_data.py` 前后各一次并贴进 `reports/`；
- **不新增 schema 列 → `db/init_db.py` 无需改**；只在 `db/schema.sql:103` 注释的枚举示例里补 `effervescent`。

### 5.3 数据派生的生成物（重生成并一起提交）

| 文件 | 谁生成 | 为什么 |
|---|---|---|
| `data/sources/atc4_forms_20261031.json` | `& $py db/atc4_forms.py`（只读库、写快照） | ATC4 页剂型维度多 `effervescent`（rank 15 进 top-30），挤掉一档低频剂型到 `other` |
| `dist/data/idx/atc4-forms.json` | 建站时 `build_atc4_forms_json()`（`site/build.py:9543`）压缩上面的快照 | 同上 |
| `data/sources/` 译文快照 | `etl/build_translation_tables.py` | E7 新增剂型译名 |

### 5.4 `site/build.py` 待落地补丁（**本次未改**，逐处列出）

| P | 位置 | 改法 | 影响面 |
|---|---|---|---|
| P1 | `LABEL_I18N`（L845-890，四份字典各加一行） | `"form.effervescent": "effervescent" / "efervescente" / "泡腾剂" / "泡騰劑"` | 806 个 key 的标签、矩阵筛选器、ATC4 表 |
| P2 | `data/i18n_zh_hant.json` | 加 `"form.effervescent": "泡騰劑"`（与 P1 同步；build.py 优先，json 只是不留缺键） | 一致性 |
| P3 | `_FORM_WORD_ZH`（L7141-7148） | 首行加 `"effervescent": ("泡腾", "泡騰")` | `_strip_form_from_label()` 去重时认得泡腾，避免「泡腾泡腾片」 |
| P4 | `_form_rank()`（L7339-7357） | 加 `if "effervescent" in f: return 0`（否则落到 `return 9`，矩阵里泡腾行排到最后） | 矩阵排序 |
| P5 | `_name_product_table()`（L7599-7601） | `esc(form)` → `_label_html('form', form_base, dosage)`，其后加 `<span class="m-orig">{来源原文：esc(dosage)}</span>`（`data-i18n="name.form_source"`） | **修既有 bug**：≈12.9 万（`HAVING COUNT(DISTINCT product_id)=1` 的 trade key **128,718** 个）单包装页现在打印英文原码（`tablet`），其中含 484 个泡腾 key；同时落地 R1 |
| P6 | 名字页成分卡（L7675） | `_label_join('form', ...)` 后追加同一句来源原文小字；CN 记录加 `name.form_granularity_cn` 说明 | 力度伸那类页面（R1 主战场） |
| P7 | 矩阵筛选器 `fsel.appendChild(opt(f, f))`（L5723） | `opt(f, _label_text('form', f))`，让选项显示「泡腾剂」而不是 `effervescent`（其余剂型一并受益） | 204 个成分页 + 顺带修所有剂型选项 |
| P8 | **可选/本期不做** R3 冲突横幅 | 新增纯函数 `_form_conflict(norm, form_base)` + 预计算集合 + `data-i18n="name.form_conflict"` | 噪声比 ~100:1（§3.2），建议等 R1 上线后再评估 |

> P5/P6/P7 顺手把三个显示面统一走同一套 label helper，是值得一起收的技术债（`_name_product_table` 是唯一还在打印原码的地方）。

### 5.5 文档 / 版本

- `CHANGELOG.md` 顶部新节（2–5 条用户能感知的变化）：① 泡腾剂成为独立剂型（948 条，9 市场）② 单包装名字页剂型列改四语标签 + 来源原文 ③ 中国来源剂型粒度说明；
- `data/release_notes_i18n.json` 同步该节四语（否则 `deploy/i18n_check.py` FAIL「最新版缺语言」）；
- `db/schema.sql:103` 注释补 `effervescent`；
- `docs/方案与数据模型.md` 加一小节「剂型 class 的收敛规则」（现在这份文档完全没写 `form_base` 口径，是本报告发现的文档缺口）；
- README / About 的**产品数与市场数不变**（477,098 / 10），无需改；
- task-148 的归一化目标集（30 + `other` + `unknown`）要加 `effervescent`，否则那个脚本一跑就把它并回 tablet。

---

## 6. 风险与回归验证

### 6.1 回归清单（命令 + 期望值）

| # | 命令 | 期望 |
|---|---|---|
| R1 | `& $py db/q.py "SELECT form_base, COUNT(*) FROM product GROUP BY 1 ORDER BY 2 DESC LIMIT 5"` | tablet **181,145** · injection 71,443 · liquid **70,162** · capsule 55,070 · topical 43,269（effervescent **948**） |
| R2 | `& $py db/q.py "SELECT COUNT(*) FROM product WHERE (lower(dosage_form) LIKE '%effervesc%' OR lower(dosage_form) LIKE '%efervesc%' OR dosage_form LIKE '%泡腾%' OR dosage_form LIKE '%泡騰%' OR dosage_form LIKE '%發泡%' OR dosage_form LIKE '%发泡%' OR lower(dosage_form) LIKE '%fizzy%') AND form_base <> 'effervescent'"` | **0** |
| R3 | `& $py db/q.py "SELECT COUNT(*) FROM product"` | **477,098（不变）**；`SELECT COUNT(*) FROM product_name` → 652,909（不变） |
| R4a | 改前基线（用来源文本判定，现查 **145**）：`SELECT COUNT(*) FROM (SELECT v.substance_id, p.release, pc.strength_value, pc.strength_unit, SUM(CASE WHEN <R2 谓词> THEN 1 ELSE 0 END) e, COUNT(*) n FROM product p JOIN product_component pc ON pc.product_id=p.product_id JOIN variant v ON v.variant_id=pc.variant_id WHERE pc.ord=0 GROUP BY 1,2,3,4) WHERE e>0 AND e<n` | 145（改后仍是 145：它量的是「源码写泡腾 vs 没写」，与 class 无关） |
| R4b | 改后验收（泡腾与非泡腾仍混在同一矩阵行 = 0）：同 R4a，把 `SUM(CASE …)` 换成 `SUM(p.form_base='effervescent')`，且去掉对 `dosage_form` 的判定 | **0**（改前此式也返回 0，因为 class 还不存在；改后它才是有效验收式） |
| R5 | `& $py db/q.py "SELECT COUNT(*) FROM product WHERE country='CN' AND form_base NOT IN ('tablet','capsule','injection','topical','powder','liquid','suppository','inhalation','pill','other','unknown','pellet','stick','kit','gas','effervescent')"` | **0**（CN 清洗白名单口径仍成立） |
| R6 | `& $py db/check_data.py` 前后各一次 | 产品/成分/名称/碰撞计数不变；before/after 贴进报告 |
| R7 | `& $py -m unittest discover -s etl -t etl` | 绿（含新增 `etl/test_form_base.py`） |
| R8 | `& $py -m unittest discover -s lib -t lib` | 绿 |
| R9 | `& $py tests/trilingual/run_tests.py` | 绿（历史遗留缺口不属本版） |
| R10 | `& $py deploy/i18n_check.py` | **FAIL 0**（新增 key × 4 语齐全） |
| R11 | `& $py deploy/ci_checks.py --fast`（约 18 s） | PASS |
| R12 | `& $py site/build.py` | `== done ==`；文件数不减（≈121,293）；`data/idx/core.json` raw 41–50 MB / gzip 9.5–12 MB（护栏） |
| R13 | 连续构建两次比对 | 逐字节一致（`BUILD_V` 内容哈希护栏） |
| R14 | `& $py db/consistency_audit_form.py --only R1` | `effervescent` 族 **conflict 0 / gap 0**；其余族（尤其 `injection, solution → liquid` 15,570）**不变** |

### 6.2 必抽查页面（四语各抽 3 条）

1. `/?q=力度伸&lang=zh` → 结果行/身份卡显示「片剂」+ **来源原文：片剂** + 「中国来源只记到剂型大类」说明（R1）；`lang=zh-Hant` 显示「錠劑 · 來源原文」；
2. `/?q=redoxon&lang=en|es|zh` → `redoxon cal`(CA) / `redoxon immunity blackcurrant`(AU) / GB 两条 → **effervescent / efervescente / 泡腾剂**；
3. **TW 抽一条**（`/?q=發泡錠` 或任一 TW 泡腾 key，`lang=zh-Hant`）→ 显示「泡騰劑」而不是「錠劑」；
4. 维生素 C（ascorbic acid）成分页 → 泡腾行与普通片行**分开**；剂型筛选器出现「泡腾剂」并可用；`data-form="effervescent"` 行紧跟 tablet 行（P4）；
5. 单包装泡腾 key 名字页（484 个里抽 2 个，如 `/name/<u>`）→ 剂型列不再是英文原码（P5）；
6. `/atc/…` 含维生素 C 的 ATC4 类目 → 「按剂型看跨市场明细」出现「泡腾剂」行，「同类 ≠ 可互换」notice 仍在；
7. 泡腾颗粒样例（GB `Ispaghula husk … effervescent granules sachets`、TW `發泡顆粒劑`）→ 显示「泡腾剂 / 泡騰劑」而不是「泡腾片」。

### 6.3 已知副作用 / 风险

| 风险 | 量级 | 处置 |
|---|---|---|
| 92 行泡腾颗粒丢 `powder` 分类 | 92 | 来源原文并列（R1）说明是颗粒；彻底解决走 A′ |
| 145 个矩阵行拆开 → 页面变长 | 204 个成分页 | 受 `MATRIX_ROW_CAP=120` 保护；抽查长页 |
| `lib/search` 结果卡变多（同成分泡腾/非泡腾不再合并） | 806 key 的一部分 | 抽查 3 条检索，确认不出现重复卡片轰炸 |
| ATC4 快照变化改了一个受控 `data/sources/` 文件 | 1.21 MB | 一起提交，`reports/` 记录 diff 摘要 |
| task-148 归一化把 effervescent 并回 tablet | —— | 在 task-148 目标集里加 class（§5.5） |
| 体检口径漂移：`liquid 无浓度` 分子 −28（ES 泡腾溶液离开 liquid） | 28 | `data-quality-issues.csv` 第 5 行（58,509 / 92,983）下次体检重算，**不要手改那个 CSV** |
| 与 issue 期望不完全一致（用户可能想看到「泡腾片」三个字） | —— | 标签用「泡腾剂」+ 名字页并列来源原文；若坚持「泡腾片」，改 class 口径为 `effervescent tablet`（重算 §2.1） |

---

## 7. 缺口与待确认

1. **CN 力度伸 仍显示「片剂」**（来源原文如此）。要让它显示泡腾只能走 R2（`name_family` 加 `力度伸→redoxon`，**需人拍板**：这是唯一的人工表，且属公开口径变更）。
2. **同一来源内部粒度不一致**：CN 有 `片剂(泡腾)` 70 行、`片剂(泡腾片)` 14 行…，而力度伸这条只写「片剂」。本报告不建议从 `pack` 猜（铝管启发式已否，§3.2）。
3. **`form_base` 口径从未写进 `docs/`**（`docs/方案与数据模型.md` 无相关内容），建议本次一并补。
4. **没有 `form_base_of()` 单测**；`db/check_data.py` 也不校验剂型取值——唯一能查剂型一致性的是未入库的 `db/consistency_audit_form.py`（建议入库并接进 `ci_checks.py`）。
5. **剂型有 5 套实现**（§1.1），本次只改「泡腾」关键字；`injection, solution → liquid`（15,570 行）等 R1 conflict 大项**不在本报告范围**。
6. 本报告**未做**：未改任何代码/数据、未建站、未跑全量 `ci_checks.py`（约 10 分钟，属发布前项，留给落地时跑）。
7. 调查探针留在 `.tmp/form-effervescent-20261110/`（`probe*.py` + 输出 + `form-audit.json`），按 AGENTS §9 不入库；复现命令见 §3.2。
