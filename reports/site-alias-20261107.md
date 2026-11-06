# task-141c 站点侧接入「同物异名」（2026-11-07）

> 范围：只改 `site/build.py`（唯一代码文件）+ 本报告。**未动** `lib/` `db/` `data/` `docs/` `deploy/`；
> 未发布、未 `git commit`；**未写 `site/dist`**（线上 v0.9.5 产物原样保留，构建全部走 `SITE_OUT`）。
> 底线不变：只做身份对应 + 「不可互换」警示；别名一律不翻译、不改成分页主名；不判断两种药能否互换。

## 0. 结论

- **必做完成**：`data/substance_aliases.csv` 的 24 行异名覆盖 **46 个成分 id**，这 46 个成分页各多一行
  「也称 / Also known as」，最多列 5 个别写；原主名（`<h1>`）一字未动，别名不翻译。四语（en / es / zh / zh-Hant）
  走站点既有 `data-i18n` 机制，静态 HTML 里带英文兜底（无 JS 也能读）。
- **尽量做完成**：搜 `Dextrose` 会出现「Dextrose → Glucose」身份卡并链到 `/drug/glucose.html`；
  `Glyburide → Glibenclamide`、`Bromelaína/Bromelaina → Bromelain`、`Albuterol → Salbutamol`、
  `Chlorpheniramine → Chlorphenamine` 等 **24 条**同构。实现**复用**既有 `data/aliases.json`（俗称索引，
  客户端本来就懒加载），没有新建 `data/idx/aliases.json`，也没有改 `core.json`（理由见 §2.2）。
- **体积**：文件数 **121,292 不变**；总量 **883,306,630 → 883,330,256 B（+23,626 B = +0.023 MiB）**，
  验收上限 883,306,630 + 1 MiB = 884,355,206 B，**余量 1,024,950 B**。
- **成分页抽查**：glucose/dextrose、glibenclamide/glyburide 两组四语渲染全部正确（§4）。
- **CI**：`deploy/ci_checks.py --fast` → **PASS 6 / FAIL 0 / SKIP 2**（21.6s）。

## 1. 方案

### 1.1 数据从哪来

`data/substance_aliases.csv`（**只读**，24 行；`canonical_inn, canonical_id, alias_inn, alias_id, relation, source, note`）。
每行是「规范名 ↔ 另一个写法」：

| relation | 行数 | 例 |
|---|---|---|
| synonym（INN vs USAN） | 9 | Glucose ↔ Dextrose；Glibenclamide ↔ Glyburide |
| hydrate_variant | 1 | Glucose ↔ Anhydrous Dextrose |
| spelling | 2 | Glycerol ↔ Glycerine；Manitol ↔ Mannitol |
| synonym_salt | 2 | Furosemide ↔ Frusemide Sodium；Epinephrine ↔ Adrenaline Acid Tartrate |
| lang_variant（ES label） | 10 | Bromelain ↔ Bromelaína；Zinc Oxide ↔ Zinc Óxido |

46 个相关成分 id **全部在库里、全部有产品页**（现查 `variant`+`product_component` 确认），所以每一条都能点。

### 1.2 站内落点（两处）

| 落点 | 规则 | 为什么安全 |
|---|---|---|
| **成分页** `drug/<sid>.html` | CSV 成对**双向**：`glucose.html` 列 Dextrose / Anhydrous Dextrose，`dextrose.html` 列 Glucose；每页最多 5 个；显示名优先取库里 `substance.inn_en` 原文（保证与目标页 H1 一致），没有该成分才回退 CSV 原文 | 只加一行 `<p>`；主名、矩阵、警示、俗称行、JSON-LD 全不动；目标成分有页才加 `<a>`，否则纯文本 |
| **检索** `data/aliases.json`（俗称索引） | 只做 **alias → canonical 单向**（CSV 声明的方向）：搜别名得到一张「别名 → 规范名」身份卡，链到规范成分页；规范名已有名字索引，不反向加噪 | 复用客户端已有的懒加载索引与卡片渲染；不漏掉任何“没有名字索引”的西语别名；24 条 ≈ 7.9 KB |

卡片文案沿用既有 `nick` 卡片结构，但单独区分 `kind = "synonym"`：

- 标题：`Also known as` / `También conocido como` / `也称` / `也稱`
- 标签：`synonym` / `sinónimo` / `异名` / `異名`
- 说明：**只确认成分身份、产品仍不可互换**（四语，见 §2.3 的 key）
- 出处：CSV 的 `source` 列（`INN vs USAN`、`US label`、`ES label`、`record typo`），逐条显示

### 1.3 四语文案怎么保证

站点机制：正文默认英文 + `data-i18n` key，`assets/i18n.js`（由 `I18N` 字典生成）按 ?lang / localStorage /
浏览器语言替换。本次新增 5 个 key，写在 `I18N["en"]` / `["es"]` / `["zh"]`，繁中直接写进
`UI_I18N["zh-Hant"]`（`_install_zh_hant()` 会覆盖 zh 兜底，避免回落简体）。**别名本身（Dextrose / 葡萄糖 /
Bromelaína…）一个字都不翻译。**

## 2. 改动点（`site/build.py`，7 处）

| # | 位置（改后行号） | 改动 |
|---|---|---|
| 1 | `build.py:6062` | 新增 `SUBSTANCE_ALIASES_CSV` / `SUBSTANCE_ALIAS_CAP = 5`，中文注释写明「只读 CSV、不翻译、不改主名」 |
| 2 | `build.py:6077` `load_substance_aliases()` + `_norm_alias()` | 读 CSV → `(also, hits)`。`also` = 双向页面行（46 个 sid）；`hits` = 24 条检索条目（与 `load_aliases()` 同构）。`_norm_alias()` 与 `app.js` 的 `norm()` 逐条同口径（NFKC→小写→去组合音标→压空白） |
| 3 | `build.py:6356` `build_drug_pages(db, entries=None, also=None)` | 新增可空参数 `also`；缺省时自己读一次 CSV（兼容老调用）。**46 个块之外不产生任何字节变化**（模板改成 `{syn_line}{nick_line}`，空串时与原模板逐字节相同） |
| 4 | `build.py:6651` | 生成 `syn_line`：`<p class="sub drug-also">…</p>\n`，插在警示行与「也叫（俗称）」行之间 |
| 5 | `build.py:9739` `main()` | 昵称索引处一次读入：`aliases = load_aliases(db) + sub_alias_hits`，并把 `sub_aliases` 传给 `build_drug_pages()`；进度行打印 `1143 nicknames (24 substance synonyms)` |
| 6 | `build.py:223/271/414/462/604/642/1049/1052` | 四语键：`drug.also_known`、`syn.tag`、`nick.synonym`、`nick.synonym_hit`、`nick.synonym_caveat`（en/es/zh + zh-Hant） |
| 7 | `build.py:3222` / `4220` / `4238`（`APP_JS`） | `_flatAccents()`：重音折叠（`Bromelaina` 也能命中 `Bromelaína`，只影响匹配不改显示）；`aliasHits()` 多一条折叠比较；`nickHTML` 对 `kind=synonym` 用新标题/新说明 |

风格沿用现有做法：常量放模块级、`from __future__ import annotations`、中文 docstring 说明「为什么」、
`data-i18n` key 与 `I18N` 字典同源；没有新增脚本、没有新增前端文件。

### 2.1 为什么检索不塞进 `core.json`

`core.json` 41.38 MB / 195,553 个名字键，且是「列式 + 字典编码」（`encode_core`）。把 24 条异名塞进去要么
改编码列（牵动客户端 `decodeCore`），要么给相关条目加字段（`Dextrose`/`Glyburide` 有名字键，但
`Anhydrous Dextrose`、西语别名多数没有键，仍然搜不到）。**体积不是问题（< 30 KB），结构才是**。
复用 `aliases.json` 是零新请求、零新文件、客户端已有渲染路径的方案，所以任务里「core.json 附异名」
与「新建 `data/idx/aliases.json`」两个备选**都没有采用**（不是做不完，是有一个更小的等价路径）；
若后续要求严格按 `data/idx/aliases.json` 落地，迁移量约 30 行。

### 2.2 为什么反向检索不加噪

CSV 的语义是「规范名 ← 别名」。规范名（Glucose / Glibenclamide…）本来就在名字索引里有条目，反向再挂一张
「Glucose → Dextrose」的卡片只会让结果页多一条噪声。所以**页面双向、检索单向**。

## 3. 体积 delta

同一份 `data/drugs.db`、同一台机器；基线 `.tmp/build-slim`（task-149 瘦身后的 **883,306,630 B**），
本次 `.tmp/build-alias`（构建到 `== done ==`：drug 12,442 / name 77,058 / combo 6,736 / maker 15,213 页）：

| 目录 | 基线 | 本次 | delta |
|---|---|---|---|
| `drug/`（12,442 页） | 148,144,387 | 148,153,036 | **+8,649**（46 页，均 188 B/页） |
| `data/`（aliases.json） | 191,377,119 | 191,384,993 | **+7,874**（1,119 → 1,143 条） |
| `assets/`（app.js / i18n.js） | 330,678 | 332,769 | **+2,091**（+838 / +1,253） |
| 根目录 `index.html` + `es/` `zh/` `zh-hant/index.html` | 4×~204 KB | 4×~205 KB | **+5,012**（首页内联 I18N 字典，+5 key × 4 语） |
| `name/`（77,058 页） | 316,515,087 | 316,515,087 | **0** |
| `maker/` `combo/` `atc/` `cat/` `docs/` | — | — | **0** |
| **合计** | **883,306,630** | **883,330,256** | **+23,626 B（+0.023 MiB）** |

- 上限：883,306,630 + 1 MiB = **884,355,206 B**，实际余量 **1,024,950 B**。
- 文件数 **121,292 → 121,292**；新增/缺失文件 **0 / 0**；0 字节文件 **0**。
- 只读不变量：`sitemap.xml` 8,454,507 B / **63,363 URL** 不变；`data/idx/core.json` **41,381,256 B** 不变；
  `name/` 316,515,087 B 逐字节不变。
- 体积来源可复核：46 页 × 平均 188 B（「Also known as:」+ 1–2 个带链接别名 + tag；最长是
  `water-for-injection` 的西班牙语全称，**+247 B**）。

## 4. 成分页抽查（无头 Chrome 实渲染）

同一个静态页，四语各渲染一次（`?lang=`），抽 `<p class="sub drug-also">` 文本（无头 Chrome `--dump-dom`）：

| 页面 | 语言 | 渲染结果 |
|---|---|---|
| `drug/glucose.html` | en | `Also known as: Dextrose, Anhydrous Dextrose synonym` |
| `drug/glucose.html` | es | `También conocido como: Dextrose, Anhydrous Dextrose sinónimo` |
| `drug/glucose.html` | zh | `也称： Dextrose, Anhydrous Dextrose 异名` |
| `drug/glucose.html` | zh-Hant | `也稱： Dextrose, Anhydrous Dextrose 異名` |
| `drug/glyburide.html` | zh | `也称： Glibenclamide 异名` |
| `drug/glibenclamide.html` | es | `También conocido como: Glyburide sinónimo` |
| `drug/dextrose.html` | en（静态） | `<a href="glucose.html">Glucose</a>` |
| `drug/glibenclamide.html` | en（静态） | `<a href="glyburide.html">Glyburide</a>` |

全量校验（脚本逐页读文件）：

- 46 个相关成分页：异名行 **恰好 1 行**、`<h1>` 与基线**完全一致**（46/46）。
- 反例：`drug/atorvastatin.html`、`drug/metformin.html` 无该行；抽 50 个未受影响成分页，
  除 `?v=<构建时间戳>` 外**逐字节一致**。
- 四语 key 值：`drug.also_known` = `Also known as:` / `También conocido como:` / `也称：` / `也稱：`；
  `syn.tag` = `synonym` / `sinónimo` / `异名` / `異名`（`assets/i18n.js` 解析确认）。
- 46 页里的异名链接（共 48 条 `<a>`）目标文件全部存在：**bad links 0**。
- 无 JS 兜底：`drug/glucose.html` 静态 HTML 内即含 `Also known as:` 与 `synonym` 文本。

## 5. 搜索验收（无头 Chrome，真实前端）

`data/aliases.json` 从 1,119 → **1,143** 条（+24 条 `kind=synonym`）。逐条起本地 http 服务 +
Chrome `--dump-dom` 渲染真实页面（非 mock）：

| 查询 | 语言 | 卡片标题（渲染后） | 链到 | 结果 |
|---|---|---|---|---|
| `Dextrose` | en | `Also known as` | `drug/glucose.html` | ✅ |
| `Glyburide` | en | `Also known as` | `drug/glibenclamide.html` | ✅ |
| `Bromelaína` | es | `También conocido como` | `drug/bromelain.html` | ✅ |
| `Dextrose` | es | `También conocido como` | `drug/glucose.html` | ✅ |
| `Dextrose` | zh | `也称` | `drug/glucose.html` | ✅ |
| `Dextrose` | zh-Hant | `也稱` | `drug/glucose.html` | ✅ |
| `Bromelaina`（不带重音） | es | `También conocido como` | `drug/bromelain.html` | ✅（重音折叠） |
| `acido mefenamico`（不带重音） | es | `También conocido como` | `drug/mefenamic-acid.html` | ✅（重音折叠） |

三语回归（普通检索仍正常出结果表）：`泰诺`（zh，102 行）、`Lipitor`（en，163 行）、
`paracetamol`（es，201 行）——全部 PASS。

> 注意：卡片标题沿用既有俗称卡的模板，en/es 后面跟的是全角冒号（`Also known as：`），
> 与站内既有卡片一致；要改成半角只需改 `nickHTML` 一处模板（未做，避免连带改 1,119 条俗称卡）。

## 6. CI 与不变量

```powershell
& $py deploy/ci_checks.py --fast
# 8 项：PASS 6 / FAIL 0 / SKIP 2（21.6s）
# [PASS] py_compile 145 个文件 · [PASS] unittest:etl 25 · [PASS] unittest:lib 59
# [PASS] unittest:mobile 29 · [PASS] dist-integrity 121,292 文件 / sitemap 63,363 URL / 0 字节 0
# [PASS] workflow · [SKIP] trilingual(--fast) · [SKIP] check_data(--fast)
```

- `site/dist`（线上 v0.9.5）**全程只读**：121,292 文件 / 943,601,056 B，构建产物只在 `.tmp/build-alias`。
- 未动库：本次不涉及 `data/drugs.db`，没跑 `db/check_data.py`；`trilingual` 与 `check_data` 按 `--fast`
  规则 SKIP，**发布前需补全量 CI**（见 §9）。
- 三语各 3 条检索已在 §5 用无头 Chrome 抽查；链接/404/sitemap 抽检见 §4、§3。

## 7. 未做项 / 已知缺口

1. **name 页（品牌页）与 ATC 页没有加异名行**（任务里的「酌情」项）。原因：`name/` 有 **77,058 页**，
   每页 +1 行约 150–200 B，全站约 **+11–15 MB**，直接超过本任务 +1 MiB 的体积口径；ATC 页同理但收益更低。
   若要做，应先按 task-146 的体积预算另批立项（或只对「通用名 key」的 name 页做，预计 1–2 万页）。
2. **公开计数口径未改**：About 页显示的是 DB `alias_all` 的 **1,119 条别名**（构建期 `@@ALIASES@@` 占位符），
   不含 CSV 里的 24 条同物异名（它们没入库）。这是数据层口径问题，按「不改 data/」的约束留给 v0.9.6
   统一（建议：入 `alias` 表或给 About 增加「同物异名 24 组」单独口径）。
3. **检索只做单向 alias → canonical**（见 §2.2），且别名卡片只按「精确 + 去空格 + 重音折叠」命中，
   不做模糊匹配（沿用既有俗称索引规则：差一个字母可能是另一个梗）。
4. **没有在 `core.json` 里附异名**（见 §2.1）；也没有新建 `data/idx/aliases.json`。
5. 异名行不标注 relation（synonym / spelling / lang variant），也不显示 `note`（CSV 备注仅进检索卡片的
   中文说明）。任务没要求，保持页面一行、低体积。

## 8. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 构建（不写 site/dist）
$env:SITE_OUT = '.tmp\build-alias'; & $py site/build.py        # 末尾 == done ==

# 2) 体积 / 文件数 / 逐页比对（基线 .tmp\build-slim）
& $py .tmp\alias_verify.py        # RESULT: PASS
& $py .tmp\alias_delta.py

# 3) 四语页面渲染 + 检索渲染（无头 Chrome，需本地 http 服务）
& $py -m http.server 8137 --directory .tmp/build-alias
& $py .tmp\alias_page_check.py
& $py .tmp\alias_search_check.py
& $py .tmp\alias_accent_check.py

# 4) CI
& $py deploy/ci_checks.py --fast
```

> `.tmp\alias_*.py` 是会话语临时脚本（`.tmp/` 不入库）。等价最小自查：
> `Select-String .tmp\build-alias\drug\glucose.html -Pattern 'drug-also'` 应命中 1 行；
> `Select-String .tmp\build-alias\data\aliases.json -Pattern '"k": "synonym"'` 应命中 24 行；
> `assets/i18n.js` 里 `drug.also_known` 应有 4 种语言值。

## 9. 发布前待办（不在本任务范围）

- 全量 CI：`& $py tests/trilingual/run_tests.py` + `& $py db/check_data.py`（本次 `--fast` 跳过）。
- 若要上线：按 `AGENTS.md` §6 走 `CHANGELOG v0.9.6` → `& $py site/build.py`（默认 dist）→
  `deploy/publish.ps1` → `verify_live.py --expect-version v0.9.6`。
- 本次改动会与 task-149（name 页瘦身）落在同一版：两者都在 `site/build.py` 未提交工作区里，
  体积基线 883,306,630 B 即瘦身后基线。

## 10. 回滚

本任务改动未提交，且与 task-149 的未提交改动同在一个 `site/build.py` 里，**不要用
`git checkout -- site/build.py`**（会连 name 页瘦身一起回滚）。按主题回滚：

1. **关掉页面行**：`main()` 里把 `build_drug_pages(db, entries, sub_aliases)` 改成
   `build_drug_pages(db, entries, {})`（不能只删第三个参数——缺省时函数会自己读 CSV），
   并把 `sub_alias_hits` 从 `aliases` 里去掉 → 46 页恢复原样、检索少 24 条。
2. **只关检索卡**：`aliases += sub_alias_hits` 一行注释掉即可（页面行保留）。
3. **只关四语文案**：删掉 5 个 key（en/es/zh/UI_I18N zh-Hant）会回落到 key 名——不建议；文案本身无副作用。
4. **产物**：`.tmp/build-alias` 可随时删；`site/dist` 未被写过，线上仍是 v0.9.5。
