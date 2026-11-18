# V7a / V7c 成分页「也叫」区块 + name 页别名 chip —— 阶段 1（只读调研）

> 工位 alias-site · task-5（V7a + V7c；V7b 归 search-alias）· 目标版本 v0.14.0
> 本阶段**只读 + 报告**：没有改 `site/build.py`、没有构建、没有写库、没有 commit。
> 需求原文：`docs/谷段需求队列.md` 第 25–34 行（V7）。

## 0. 结论先行

1. **V7a 必须从 `alias_all` 视图渲染，不能只读 `nickname` 表**：`nickname` 现查 **396 行 / 374 个成分**，而验收点名的 tirzepatide（`替西帕肽` / `猛健樂`）在 `nickname` 表里**是 0 行**——它们来自 `drug_term`（CN folk，中文维基重定向/别名）。只渲染 nickname 表 → tirzepatide 页不出块，验收必挂。
   - `alias_all` = `nickname`(396) ∪ `drug_term`(1,017) = **1,413 行**；build 的 `data/aliases.json` = 1,413 + 25 条同物异名 = **1,438**，与需求里「1,438 条」对得上（现查复现，见 §2.2）。
2. **成分页现在已有这一行，只是太薄**：`site/build.py` 的 `nick_line` 是单行 `<p class="sub">Also called: … nickname</p>`，无语言、无类型、无出处、不成块。V7a = 把它升级成块，位置不动（列表之后），避免抢占首屏。
3. **V7c 的「name 页那行末尾 chip」全站只有一处**：`/drug/<sid>.html` 成分页这行的 `data-i18n="nick.tag"`（英文 `nickname` / 中文「俗称」）。`/name/<u>.html` 名字页（77k 页）**没有 nickname 行、也没有这个 chip**（`grep` 全文件只有 1 处引用）。所以 V7c = 同一处：chip 六语化 + 别名可点。
4. **chip / 类型标签的六语其实已经齐**：en `nickname` / es `apodo` / zh「俗称」/ zh-Hant「俗稱」/ fr `surnom` / ko `속칭`；类型标签 `nick.slang|legacy|misnomer|abbrev|translit|street|folk|class` 六语也都有（zh-Hant 从 `data/i18n_zh_hant.json` 覆盖）。**唯一缺口**是 fr 没有 `nick.source`（会静默回落英文 `Source`），V7a 要用它，需补一条 `Provenance`。
5. **数据里没有「语言」字段**：只能用「`drug_term.country`（CN/US）+ 文字脚本」两条规则推导，且现查别名 99.9% 是汉字（1,373）或拉丁字母（19）。方案：CN→中文、US→English；无 country 时汉字→中文、谚文/假名→对应语言、纯拉丁→**不标**（英文/西语/品牌名不可区分，不猜）。新增 2 个 i18n key `nick.lang.zh|en`（六语各补一次）。

### 0.1 Lead 口径确认（2026-11-19，已写进队列 V7 条目）

1. 数据源 = 与 build 现有 `aliases.json` 同一份（1,438 条）：`nickname` 396 + `drug_term` 1,017 + 同物异名 25；**含 drug_term 的 folk / street / class / brand_generic，带 `source_url`**；不许只读 nickname 表、不许硬编码物质名。
2. 类型词：`alias_all`（`db/schema.sql:244`）已经把 `nickname.kind` 与 `drug_term.term_type` 统一到同一列 `kind`（street/folk/class → 原样；nickname 侧 slang/legacy/translit/abbrev/misnomer），且 8 个值都已有六语 i18n 键 → **不需要新造映射表 / 新类型词**，直接 `data-i18n="nick.<kind>"`。
3. V7c：既然 `nick.tag` chip 全站只在成分页 `nick_line` 一处，就把这行做成 6 语（含 ko）+ 别名链回成分页；**不要为对齐「name 页」措辞另造行**，报告里写明实际位置。`product_name` 780,843 行不变。

## 1. 需求原文要点（`docs/谷段需求队列.md` V7）

- V7a：成分页加「也叫 / Also called」区块，列出该成分**全部** nickname（值 + 语言 + 类型 + 出处），五语标签；**不许**把俗称写进 `product_name`。
- V7c：那个 chip 补成五语（确认 zh-Hant / fr 有没有该键），并让该行别名**链接到对应成分页**；ko（v0.13.8 今天接入）必须一起覆盖。
- 全库口径：**通用渲染**（13,434 个成分页里有别名就出块、没别名不出空块），禁止白名单/硬编码物质名；别名原文不翻译；`product_name` 行数不变（现查 780,843）。

## 2. 现查数据（只读，`db/q.py` / `mode=ro`）

### 2.1 表结构

```sql
CREATE TABLE nickname (
  nickname_id INTEGER PRIMARY KEY, substance_id TEXT NOT NULL REFERENCES substance,
  alias TEXT NOT NULL, alias_norm TEXT NOT NULL, label_zh TEXT,
  kind TEXT NOT NULL DEFAULT 'slang'
       CHECK (kind IN ('slang','legacy','translit','abbrev','misnomer')),
  confidence TEXT NOT NULL DEFAULT 'community'
       CHECK (confidence IN ('user','community','documented')),
  source TEXT, note TEXT, created_at TEXT NOT NULL,
  UNIQUE (alias_norm, substance_id));
```

`alias_all`（`db/schema.sql:244`）= `nickname` ∪ `drug_term`，统一成
`alias_id / origin / substance_id / alias / alias_norm / label_zh / label_en / kind / confidence / source / source_url / country / meaning_en / meaning_zh / examples / note / created_at`。
**要求里的「语言 / 类型 / 出处」正好落在 `country`（仅 drug_term）、`kind`、`source` + `source_url`。**

### 2.2 分布（现查）

| 口径 | 数字 |
|---|---|
| `nickname` 行数 / 指向成分数 | **396 / 374** |
| `drug_term` 行数（有 `substance_id` 的 / 全部） | **983 / 1,017** |
| `alias_all` 行数 | **1,413** |
| `aliases.json` 口径（`load_aliases` 1,413 + 同物异名 25） | **1,438**（复现：`build.load_aliases(db)`+`load_substance_aliases(db)`） |
| 有别名且有产品页的成分 | **680**（nickname 374 + drug_term 410，交集 104；两边都 0 悬空/0 孤儿） |
| 成分页总数（`DISTINCT v.substance_id`） | **13,434**；`substance` 13,645 |
| `product_name` 行数 | **780,843**（红线：改后必须不变） |
| kind 分布 | nickname：misnomer 340 / legacy 52 / slang 3 / abbrev 1；drug_term：folk 1,005 / class 12 |
| confidence | community 938 / documented 474 / user 1 |
| 出处 | `alias_all` **0 行空出处**；drug_term **1,017 行都有 `source_url`**，nickname 无 URL（文字 provenance） |
| 每成分别名条数 | 1 条 405、2 条 127、3 条 51…最多 15 条（acetaminophen / povidone-iodine-57d2b4） |
| 文字脚本 | 汉字 1,373、纯拉丁 19、汉+拉丁 20、其它 1（`654-2`，纯数字编号） |
| tirzepatide | `nickname` **0 行**；`alias_all` 2 行：`替西帕肽`、`猛健樂`（kind=folk，source=中文维基百科重定向/别名） |

### 2.3 推导规则（不手工标注）

- 语言：`country='CN'` → `zh`；`country='US'` → `en`；无 country 时按脚本：汉字 → `zh`、谚文 → `ko`、假名 → `ja`；纯拉丁/纯数字 → **不标**（不猜 en/es）。
- 类型：直接用 `kind`（nickname 5 种 + drug_term 的 street/folk/class），全部已有六语 i18n 键。
- 出处：有 `source_url` 的做成外链（`rel="noopener"`），否则只显示 provenance 文本；一律**不翻译**别名原文。

## 3. `site/build.py` 现状（行号为调研时快照，别家工位在改，阶段 2 用唯一锚点）

| 位置 | 现状 |
|---|---|
| `load_aliases()`（约 11222） | `alias_all` 全量 → `data/aliases.json`（检索用，含 NULL sid 的类别词） |
| 成分页 `nicknames`（约 11187） | `SELECT substance_id, alias FROM alias_all WHERE substance_id IS NOT NULL` → `dict[sid, list[str]]`（**已含 drug_term**） |
| `nick_line`（约 12290–12294） | `<p class="sub"><span data-i18n="drug.also_called">Also called:</span> 名字、名字 <span class="st-text" data-i18n="nick.tag">nickname</span></p>` |
| 模板（约 12365） | `{syn_line}{nick_line}`，位于列表/并排表之后、`conf_line`（易混）之前 |
| 成分页 JSON-LD（约 12373–12378） | `MedicalWebPage` + `about: {"@type":"Drug","name":inn_en}`，目前**没有** `alternateName` |
| CSS 可复用 | `.st-text`（13px 灰）、`.tag`（13px 纯文字，无胶囊）、`.mkblock>h2`（16px）、`.notice.nick`（检索页俗称卡样式） |
| i18n | en/es/zh 在 `I18N`（190 起）；fr 扁平表 `FR_I18N`（916）；ko `KO_I18N`（3639，667 键）；zh-Hant 覆盖在 `data/i18n_zh_hant.json`（667 键全在） |

**i18n 基线（改动前，`deploy/i18n_check.py` 现跑）**：en/es/zh/zh-Hant/fr/ko 各 **667 键**；`FAIL 1` = 「v0.13.8 release notes 缺译文」（pages-deploy task-2 的活，不是我的）；`WARN 2`（es kit/gas 同形）；硬编码文案 0 处。阶段 2 判据 = **FAIL 数不增加**（目标 0 需等 task-2）。

## 4. 外部方案检索（AGENTS §12，先找现成工具）

| 候选 | 许可 / 体积 / 兼容 | 结论 |
|---|---|---|
| **schema.org `alternateName`**（`Thing` 属性，"An alias for the item"；1M–10M 域名使用）<br>https://schema.org/alternateName | 词表规范、零运行时、零字节 JS | **采纳（可选小改）**：成分页现有 `Drug` JSON-LD 加 `alternateName: [...]`，把「别名 → 成分」写进结构化数据；不新增依赖、不影响渲染 |
| **Modern Web Guidance：`html` / `single-line-overflow` / `card` / `accessibility`**（`vendor/modern-web-guidance/`，Apache-2.0） | 离线存档，只是参考，不进产物 | **采纳其规则**：块用原生 `<section>` + `<h2>` + `<ul>`（不用 div 拼列表）；长别名/出处按 `single-line-overflow` 的 `min-inline-size:0` + 省略号，不脚本截断；不引入任何组件库 |
| **GitHub 上的 alias/tag/chip 组件**（npm 包如 `@altrugenix/chip`、`@xsolla/xui-tag`、各类 React/Web Component chips） | 需要 npm / 打包链 / 框架 | **不采用**：本仓「无 npm、静态构建、HTML/CSS/JS 内联进 `site/build.py`」；引入依赖反而破坏构建确定性与体积预算。需求只是「块 + 小标签」，原生 HTML + 现有 `.tag/.st-text` 足够 |

> 另：检索「also known as list component accessibility」没有比原生列表更好的成熟方案；这类「别名 + 类型 + 出处」属于内容结构问题，不是组件问题。

## 5. 阶段 2 实现方案（等 Lead 发 BUILD-FREE 后执行）

### 5.1 改动点（全部 `edit` + 唯一锚点，绝不 `write`）

1. **数据读入**（成分页区段）：把 `nicknames: dict[sid, list[str]]` 扩成 `dict[sid, list[dict]]`，一次查 `alias_all`（`alias_id, alias, kind, confidence, source, source_url, country, note`），仍排除 `substance_id IS NULL`。**不新增 SQL 往返**。
2. **渲染 `nick_block`**（替换 `nick_line`）：
   ```html
   <section class="also-called" aria-labelledby="also-called-h">
     <h2 class="also-h" id="also-called-h"><span data-i18n="drug.also_called">Also called:</span>
       <span class="st-text" data-i18n="nick.tag">nickname</span></h2>
     <ul class="nick-list">
       <li><a href="../drug/<sid>.html" aria-current="page">猛健樂</a>
           <span class="tag" data-i18n="nick.folk">folk name</span>
           <span class="st-text" data-i18n="nick.lang.zh">Chinese</span>
           <span class="st-text src"><span data-i18n="nick.source">Source</span>:
             <a href="…" rel="noopener" target="_blank">中文维基百科…</a></span></li>
       …
     </ul>
     <p class="sub" data-i18n="nick.caveat">Nicknames point to an ingredient…</p>
   </section>
   ```
   - 有别名才出块；别名原文不翻译；每成分**全量**列出（不截断，最多 15 条，现查无失控页）。
   - 位置不动（列表之后），不进首屏、不改 `.mkblock h2` 首屏守卫选择器。
3. **链接规则**：别名 → 其 `substance_id` 的成分页（`../drug/<sid>.html`）。现查该成分就是本页 → 加 `aria-current="page"`，语义上仍是「别名 → 成分页」；若将来同一渲染复用到别的页（如名字页），链接自动指向正确成分页。**不手工标注任何例外。**
4. **i18n**：
   - 新增 `nick.lang.zh|en`：en `Chinese/English`、es `chino/inglés`、zh `中文/英文`、zh-Hant `中文/英文`、fr `chinois/anglais`、ko `중국어/영어`（zh-Hant 写进 `UI_I18N["zh-Hant"]`，否则构建期 `_assert_i18n_complete` 会因「只能回落简体」中止）。
   - 补 fr `nick.source` = `Provenance`（现缺，i18n_check 会记 fr 回落；补后 fr 664/669）。
   - 其余标签全部复用现有键（`drug.also_called` / `nick.tag` / `nick.slang|legacy|translit|abbrev|misnomer|street|folk|class` / `nick.source` / `nick.caveat` / `nick.unverified|community`），**不新增第二套词表**。
5. **CSS**：`.also-called` / `.also-h`（16px，与 `.mkblock>h2` 同级）/ `.nick-list`（`list-style:none`、`display:flex;flex-wrap:wrap;gap`）/ `.nick-list li{min-inline-size:0}`；挂 `.tag`/`.st-text` 既有样式。390 无横向溢出（长出处 `overflow-wrap:anywhere`）。
6. **可选**：成分页 JSON-LD 加 `alternateName`（§4 候选 1），零依赖；若 Lead 认为越界就不做。

### 5.2 自验清单（阶段 2 交付证据）

- [ ] `SITE_OUT=.tmp/dist-v7` 构建到 `== done ==`（**不写 `site/dist`**），构建日志 `i18n 四语一致: 669 keys × 6 语言`。
- [ ] `tirzepatide.html` 出现「替西帕肽」「猛健樂」+ 类型 + 语言 + 出处；另抽 3 个不同市场成分页（拟 `acetaminophen` CN/US、`povidone-iodine-…`、`zopiclone`）同样有块。
- [ ] 抽 20 个「有别名 / 无别名」页：无空块、无残留 `@@`/`{}` 占位符、无硬编码英文标签残留（六语抽查各 1 页 DOM）。
- [ ] `product_name` 行数 = **780,843**（只读 SQL 前后各一次）。
- [ ] `deploy/i18n_check.py`：FAIL 数不增加（当前 1 = release notes 缺译，非本任务）、硬编码 0。
- [ ] `deploy/check_build_determinism.py`（同输入两次构建逐字节一致）由 Lead 全量构建时复核。
- [ ] 报告补：改动 diff stat、块 HTML 片段、页数/体积增量、六语截图或 DOM 摘录。

### 5.3 风险 / 未决（请 Lead 复核）

1. ~~**V7c 的「name 页」= 成分页同一行**~~ → **Lead 2026-11-19 已确认**：实际位置就在成分页 `nick_line`，报告写明即可，不为措辞另造行。
2. **别名链接是自链接**：别名指向的成分就是本页；按需求字面做成链接 + `aria-current="page"`。若不想要自链接，可改「只有指向别的成分页时才成链」（一行判断，等 Lead 验收时定）。
3. **语言标签是推导值**：`Tempra` / `Mejoral`（墨西哥西语品牌名）按规则会落进「纯拉丁 → 不标」，不硬判成英文；`654-2` 无标签。
4. **i18n 基线 FAIL 1 不是本任务引入**：v0.13.8 release notes 由 pages-deploy task-2 补齐后归零。
5. **并发**：`site/build.py` 有 4 个工位同时在改；本任务只用 `edit` + 唯一锚点，`FS_STALE_VERSION` 就重读重标；改的区段 = 成分页 nickname 块 + 对应 i18n 键 + 一小段 CSS。

## 6. 附：可复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/q.py "SELECT COUNT(*), COUNT(DISTINCT substance_id) FROM nickname"          # 396 / 374
& $py db/q.py "SELECT origin, COUNT(*) FROM alias_all GROUP BY origin"              # nickname 396 / drug_term 1017
& $py db/q.py "SELECT alias, kind, source FROM alias_all WHERE substance_id='tirzepatide'"
& $py db/q.py "SELECT COUNT(*) FROM product_name"                                   # 780843
& $py deploy/i18n_check.py                                                          # FAIL 0（release notes 已由 pages-deploy 补齐）
```

---

# 阶段 2 交付（2026-11-19，已实现并自验）

> 触发：Lead「BUILD-FREE」（v0.13.8 commit/tag/CI 13/13 PASS 后）。改动全在 `site/build.py`，
> **`edit` + 唯一锚点**，未 `write`、未 commit、未发布、未写 `site/dist`；temp 构建
> `SITE_OUT=.tmp/dist-v7`。期间 Lead 发 HOLD（v0.13.8 干净重建，工作树 `build.py` 被替换约 25 分钟），
> 已停止改文件、把工作树快照存到 `.tmp/build.py.snapshot-v7-alias-site`，等 BUILD-FREE #2 复核锚点。

## 7. 改动清单（11 处 edit，全部在成分页昵称区段 + 对应 i18n/CSS）

| # | 位置（锚点） | 改动 |
|---|---|---|
| 1 | `I18N` en `nick.source` 后 | +`nick.lang.zh` = Chinese、`nick.lang.en` = English |
| 2 | `I18N` es `nick.source` 后 | +`nick.lang.zh` = chino、`nick.lang.en` = inglés |
| 3 | `I18N` zh `nick.source` 后 | +`nick.lang.zh` = 中文、`nick.lang.en` = 英文 |
| 4 | `FR_I18N.update` 的 `nick.tag` 前 | +`nick.source` = Provenance、`nick.lang.zh` = chinois、`nick.lang.en` = anglais（补 fr 唯一缺口） |
| 5 | `KO_I18N` `nick.source` 后 | +`nick.lang.zh` = 중국어、`nick.lang.en` = 영어 |
| 6 | `UI_I18N["zh-Hant"]` `nick.synonym` 前 | +`nick.lang.zh` = 中文、`nick.lang.en` = 英文（繁简同形，防构建期回落简体拦截） |
| 7 | 同物异名区段前 | +`NICK_KIND_KEYS`（8 种 kind）、`NICK_LANG_KEYS`（zh/en）、`_nick_i18n()`、`_alias_lang()` |
| 8 | `nicknames` 读取 | `list[str]` → `list[dict]`：一次查 `alias_all`（alias/kind/confidence/source/source_url/country），只读、不新增 SQL 往返 |
| 9 | `nick_line` → `nick_block` | 单行 `<p>` 升级为 `<section class="also-called">`：`<h2>`（Also called + 六语 chip）+ `<ul>` 每条「值(链回成分页) + 类型 + 语言 + 出处(有 URL 则外链)` + `nick.caveat`；有别名才出块 |
| 10 | 成分页模板 | `{syn_line}{nick_line}` → `{syn_line}{nick_block}`（位置不变，列表之后、易混提示之前） |
| 11 | CSS（`.notice.nick .sub.src` 后） | `.also-called` / `.also-h`(16px) / `.nick-list`（原生 flex 列，`min-inline-size:0`+`overflow-wrap:anywhere`）/ 390 下出处换行 |

**类型词没有新造映射表**：`alias_all` 已把 `nickname.kind` 与 `drug_term.term_type` 归一到 `kind`
（folk/street/class + slang/legacy/translit/abbrev/misnomer），8 个键六语都现成。

## 8. 构建与自验（`.tmp/dist-v7`，`== done ==`）

- 构建：`drug pages 13,434`、`name pages 91,073`、`total 1,306.9 MB`；
  `i18n 四语一致: 686 keys × 6 语言（zh-Hant 回落 0 个已登记 key）`；`1438 nicknames (25 substance synonyms)` 不变。
- `deploy/i18n_check.py`（改后、工作树含本任务改动时）：**FAIL 0**（683 键 × 6 语，硬编码文案 0；
  另 2 条存量 WARN 是 es `form.kit/gas`，与本任务无关）。

### 8.1 ① tirzepatide 页 DOM（块 1,333 B，2 条）

```html
<section class="also-called" aria-labelledby="also-called-h">
<h2 class="also-h" id="also-called-h"><span data-i18n="drug.also_called">Also called:</span>
  <span class="st-text" data-i18n="nick.tag">nickname</span></h2>
<ul class="nick-list">
<li><a href="../drug/tirzepatide.html" aria-current="page">替西帕肽</a>
  <span class="tag" data-i18n="nick.folk">folk name</span>
  <span class="st-text" data-i18n="nick.lang.zh">Chinese</span>
  <span class="st-text nick-src"><span data-i18n="nick.source">Source</span>:
    <a href="https://zh.wikipedia.org/wiki/%E6%9B%BF%E5%B0%94%E6%B3%8A%E8%82%BD" target="_blank" rel="noopener">Chinese Wikipedia (中文维基百科：重定向/别名)</a></span></li>
<li><a href="../drug/tirzepatide.html" aria-current="page">猛健樂</a>
  <span class="tag" data-i18n="nick.folk">folk name</span>
  <span class="st-text" data-i18n="nick.lang.zh">Chinese</span>
  <span class="st-text" data-i18n="nick.community">community name</span>
  <span class="st-text nick-src"><span data-i18n="nick.source">Source</span>: …</span></li>
</ul>
<p class="sub" data-i18n="nick.caveat">Nicknames point to an ingredient…</p>
</section>
```

### 8.2 ② 另抽 3 个不同市场的成分页（有块，条数与库一致）

| 成分页 | 覆盖市场 | 块大小 | 别名条数（=DB） | 语言标签 |
|---|---|---|---|---|
| acetaminophen | 14（AU/CA/CN/CZ/ES/FR/GB/HK…） | 7,156 B | 15 | 13（2 个墨西哥品牌名纯拉丁 → 不猜语种，不标） |
| zopiclone | 13 | 5,607 B | 10 | 10 |
| gliclazide | 13 | 4,612 B | 10 | 10 |
| metamizole（第 4 个） | 5（CN/CZ/ES/LV/MX） | 4,544 B | 9 | 9 |

### 8.3 ③ 全站 13,434 页扫描 + 20 页抽检

- 有块页 **680 = DB 期望 680**（`alias_all` 有 `substance_id` 且有产品页的成分）；无块空页 **0**；
  `<li>` 不配对 **0**；`class="also-called"` 重复 **0**；块内 `@@`/`{u}`/`{n}`/`{…}` 残留 **0**；
  全站 drug 页 `{u}`/`{n}`/`@@NICK` 残留 **0**；旧单行 `<p class="sub"><span data-i18n="drug.also_called">` 残留 **0**。
- 块体积合计 **938.8 KB**（≈ 全站 1.3 GB 的 0.07%）；块内引用 **12 个 i18n 键**，六语值全在（见 8.4）。
- 20 页随机抽检（10 有块 + 10 无块，seed 20261119）**20/20 通过**。

### 8.4 六语标签（构建产物 `assets/i18n.*.js` 实测，686 键 × 6 语、键集差 0）

| key | en | es | zh | zh-Hant | fr | ko |
|---|---|---|---|---|---|---|
| `nick.tag`（V7c chip） | nickname | apodo | 俗称 | 俗稱 | surnom | 속칭 |
| `drug.also_called` | Also called: | También llamado: | 也叫： | 也叫： | Aussi appelé : | 다른 이름: |
| `nick.lang.zh` | Chinese | chino | 中文 | 中文 | chinois | 중국어 |
| `nick.lang.en` | English | inglés | 英文 | 英文 | anglais | 영어 |
| `nick.source` | Source | Fuente | 出处 | 出處 | **Provenance**（本次补） | 출처 |
| `nick.folk` / `legacy` / `misnomer` / `slang` / `abbrev` | folk name / older name / common misnomer / internet nickname / abbreviation | … | 民间叫法 / 旧名 / 常见误称 / 网络俗称 / 简称 | 民间叫法 / 舊名 / 常見誤稱 / 網路俗稱 / 簡稱 | nom populaire / ancien nom / terme abusif / surnom Internet / abréviation | 통칭 / 옛 이름 / 흔한 오칭 / 인터넷 속칭 / 약어 |

### 8.5 ④ 红线

```
product_name = 780,843   （改前改后一致；本任务全程无写库）
nickname     = 396       alias_all = 1,413   aliases.json = 1,438（构建日志）
```

## 9. 未做 / 已知缺口（如实记录）

1. **name 页 chip 不存在**：`/name/<u>.html`（91,073 页）从来没有 nickname 行；需求原文说的
   「name 页那行末尾 chip」实际就在成分页 `/drug/<sid>.html`。按 Lead 确认不为措辞另造行。
2. **别名链接是自链接**：别名 `substance_id` 就是当前成分页，`href` 指回本页并带
   `aria-current="page"`（按需求「链到对应成分页」字面实现；同一渲染若复用到他页会自动指向正确成分页）。
   若验收认为自链接无意义，改一行判断即可只在跨成分时成链。
3. **语言标签是推导值**：`drug_term.country` CN→中文 / US→English；nickname 无 country 只看汉字
   （谚文/假名键未提供，纯拉丁不猜语种）。故 `Tempra`/`Mejoral`（墨西哥品牌名）、`654-2` 不标语言。
4. **未做 JSON-LD `alternateName`**（阶段 1 报告 §4 的候选 1）：属于 scope 外，等 Lead 决定是否另派。
5. **first-screen guard 抽检**（`--dist .tmp/dist-v7 --pages drug --viewports 390x844,1440x900`）：
   drug@390 AFCR 0.93 / 条目 5.5 / chrome 0.14 / 溢出「否」→ **ok**；
   drug@1440 条目 4.5（未达 5）——这是**存量基线**（`deploy/first_screen_check.py` 头注释记的
   「drug@1440 4.5→0」就是它），块在列表之后、不进首屏，与本任务无关。正式改前/改后数字由 Lead 全量构建时补。

## 10. 复核命令（BUILD-FREE #2 后重跑）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Select-String -Path site\build.py -Pattern 'also-called','nick.lang.zh','nick_block'   # 改动仍在
& $py deploy/i18n_check.py                                                            # FAIL 0
& $py .tmp/_v7_verify.py                                                              # 本报告 8.x 全部数字
```

## 11. BUILD-FREE #2 收尾核对（2026-11-19 09:50，未再构建）

- Lead 已把工作树 `site/build.py` 原样放回 WIP（1,169,497 B）：与 `.tmp/build-wip.py` 快照的差异
  **只有 page-slim 的 V3 门槛 3 行**（name 页规格拆行），**V7a/V7c 的 11 处改动全在**——
  `also-called` ×4、`nick.lang.zh` ×6、`nick_block` ×3、`_nick_i18n(` ×6、`_alias_lang(` ×2、
  `NICK_KIND_KEYS` ×2；helpers 实测：`_alias_lang('替西帕肽','CN')=zh`、`('water pill','US')=en`、
  `('Tempra','')=''`（不猜语种）；fr 扁平表 `nick.source=Provenance`、ko `nick.lang.zh=중국어`。
- `py_compile site/build.py` **exit 0**；`deploy/i18n_check.py` **FAIL 0**（683 键 × 6 语、
  硬编码 0、fr 680/683、存量 WARN 2 条 es kit/gas）；`product_name` = **780,843**。
- 按 Lead 要求**未跑全量 temp 构建**（等「构建窗口开放」）；`.tmp/dist-v7` 的 8.x 全量自验结论仍有效
  （源码唯一差异在 name 页 V3 逻辑，与成分页昵称块无关）。


