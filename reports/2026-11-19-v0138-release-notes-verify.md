# v0.13.8 What's new 六语译文 + 发布链兜底（pages-deploy）

> 日期：2026-11-19（北京时间）· 工位：pages-deploy · 任务：共享任务 `task-2`
> 改动：`data/release_notes_i18n.json`（v0.13.8 块）、`deploy/verify_live.py`、`deploy/fix_fr_root.py`、
> `deploy/sync_r2.ps1`（后三项为 Lead 2026-11-18 追加，本报告 §2 单列）。
> 未动：`site/build.py`、`deploy/i18n_check.py`（site-ui 在改）、`site/dist`、`data/drugs.db`；**未构建、未发布、未 commit**。
> 阶段 2（i18n_check / 首屏守卫 / `/ko/` 截图 / hreflang / sitemap）要等 Lead 说「合并完成」并构建完 `site/dist`，本文先记阶段 1。

## 结论先行

1. **阶段 1 完成**：`data/release_notes_i18n.json` 末尾追加 `v0.13.8` 块（`date` + zh/en/es/fr/zh-Hant/ko 六语 × **3 条**），
   内容照 `CHANGELOG.md` 第一节；历史块顺序与键序一字未动（JSON 字节 diff 只增不改历史内容）。
   `_meta.versions` 76 → **77**、`_meta.items` 308 → **311**（与现查一致；Lead 2026-11-18 给 CHANGELOG 补第 3 条后 310 → 311）。
2. **门禁已绿**：`deploy/i18n_check.py`（site-ui 已合入 ko 分支的版本）→ 最终 **FAIL 0 / WARN 2 / INFO 26**，
   `release notes: CHANGELOG 77 版 / json 77 版，最新 v0.13.8 译文齐；缺 0 版`；六语有效字典各 **667 键**。
   `etl/check_translations.py` → release notes **77 版 / 311 条 / 0 findings**（数字 / 占位符 / HTML 逐条过）。
3. **发布链兜底已泛化**（Lead 追加）：`verify_live.py` 的 `LANG_ROOTS` 加第 6 条 `("ko/", "/ko/")`；
   `fix_fr_root.py` 从「只写 `fr/`」改为按语言列表逐 PUT（默认 `fr,ko`，新增 `--langs`）；
   `sync_r2.ps1` 同步后按 `$FallbackLangs = @('fr','ko')` 调它，失败仍只 WARN、不影响上传退出码。
4. **数字现查核对**（只读开库）：产品 **594,781**（`SELECT COUNT(*) FROM product`）、启用市场 **15**
   （`data/markets.json` enabled 15 项），与 v0.13.8 文案里的「15 个市场 / 594,781 条不变」一致。
5. **移交 site-ui 两个渲染缺口**（不在本工位写域，见 §4）：`/fr/`、`/ko/` 的 whats-new 正文会被 JS 全部隐藏；
   `/ko/` 首页「最近更新」的一句话会被英文顶替。
6. **阶段 2 最终结论（重建 #2 产物）：全部通过。**
   语言块复扫 **22 页 / 1316 容器 / `noVisible` 0 / `emptyVisible` 0（PASS）**，ko 的 cat/atc/drug 也清零；
   副本页 404 **顺带清零**（22 页逐页 `4xx=0`）；`i18n_check` **FAIL 0**（最新版六语译文齐）；
   静态核验全绿（hreflang 8 条 / canonical / sitemap 75,609·ko 7·重复 0 / whats-new 六语 × 3 条 / liners 韩语）；
   首屏 ko 四档 **24 组扫描、无构建退化**（对同版本 zh：AFCR/chrome/字号/溢出 0 差异，items 差 0.5–2.5 行系韩文标签更长；
   未达标仅 Q18 已知 `results@390`、`coverage@390` 的 items）。4 张 `docs/img/ko-*.png`（1440×900）已交付。

## 1. 阶段 1：`data/release_notes_i18n.json` 新增 v0.13.8

### 1.1 结构（照 v0.13.7 块，不重排历史）

- 位置：追加在文件**末尾** `v0.13.7` 之后（v0.13.6 / v0.13.7 也在末尾，历史块顺序未动）。
- 键序：`date, zh, en, es, fr, machine_translated, zh-Hant, ko`——前 7 个键与 v0.13.7 完全同序，
  第 6 语言 `ko` 追加在末尾；历史块键序逐个断言未变（脚本见 §3.1）。
- 键集与条数：六语各 **3 条**，等于 `CHANGELOG.md` v0.13.8 的条目数（3）。第 3 条由 Lead 2026-11-18 补进
  CHANGELOG（「法语与韩语页面不再出现整段空白」），六语译文同日补齐；`zh` 与 CHANGELOG 逐字相同（脚本逐条比对 `identical=True`）。
- 行尾/缩进：保持原文件 `indent=1` + **CRLF** + 末尾换行；用「load → 追加 → dump → 字节比对」验证，
  改前改后除新增内容外格式零变化（未整文件重排）。
- `_meta`：`versions` 76 → 77、`items` 308 → **311**；另把 `ko` 补进 `_meta.translations`
  （`machine (AI) translation of the zh text; zh is authoritative`），与 en/es/fr 的披露同格式。

### 1.2 译文口径

- `zh` 原样复制 CHANGELOG 那一节（权威原文，未改字）；en / es / fr / zh-Hant / ko 为对应译文。
- 术语按仓库既有口径：ko 用 `.tmp/ko_i18n.py` 的术语（인터페이스 / 시장 / 성분 페이지 / 커버리지 /
  호환 불가 / 복약 조언 / 대체 추천）；zh-Hant 用既有「介面 / 選單 / 涵蓋頁 / 成分頁 / 資料來源」；
  es 用 `página de principio activo`、`página de cobertura`；fr 用 `page de principe actif`、`page de couverture`。
- 数字逐语保留本地写法：zh/zh-Hant/en `594,781`、es `594.781`、fr `594 781`（与 v0.13.0 的既有写法一致）；
  `667`、`15`、`/ko/`、`hreflang`、`canonical` 六语一致。
- 红线：只描述语言与数据事实，没有任何用药建议、剂量换算或替代判断。

## 2. 发布链兜底（Lead 追加，纳入 task-2）

### 2.1 `deploy/verify_live.py`

- `LANG_ROOTS` 5 条 → **6 条**，新增 `("ko/", "/ko/")`；模块 docstring 的语言根清单同步加 `/ko/`。
- 影响：发布门槛现在会逐个验 `/ko/` 200（≥500 B），且 `hreflang-links` 的下限从 5 提到 **6**。
- 这正是 v0.11.4 `/fr/` 漏检的同一条护栏（注释里补了 v0.13.8 的由来）。

### 2.2 `deploy/fix_fr_root.py`（文件名保留，行为泛化）

- `KEY = "fr/"` → `LANG_ROOTS = ("fr", "ko")` + `--langs`（逗号分隔，默认 `fr,ko`；去斜杠/去重/校验语言标签）。
- 逐语言读 `<dist>/<lang>/index.html` 并 PUT 对象键 `<lang>/`：
  - 某语言源文件缺失 → 只打 `WARN: 源文件不存在 …（跳过 /xx/ 兜底）`，继续其它语言；
  - 一个源文件都没有 / 缺 `.env` / 缺 botocore → 退出码 **2**；
  - 任一 PUT 失败 → 逐条 `WARN`，退出码 **1**；全部成功 → **0**。
- `--dry-run` 逐语言打印计划；`.env` / `site/dist` 仍只读，不写库、不改 dist。

### 2.3 `deploy/sync_r2.ps1`

- 新增 `$FallbackLangs = @('fr', 'ko')`（注释写明与 `fix_fr_root.py` / `verify_live.py` / `data/languages.json` 三处同步）；
  同步 + 体积核对通过后调用
  `fix_fr_root.py --dist $Dist --langs ($FallbackLangs -join ',')`（PowerShell 里作为一个参数 `fr,ko` 传入，已实测）。
- `Resolve-FrPython` / `Test-FrPython` / `$FrRuntimePython` → `Resolve-FallbackPython` / `Test-FallbackPython` /
  `$FallbackRuntimePython`（脚本内部符号，无外部引用；顺序仍是 `$env:PYTHON → python → py → 运行时路径`，仍以 `import botocore` 探测）。
- 失败语义保持不变：只 `WARN`，**上传成功仍 exit 0**；WARN 文案改为语言列表（`fr, ko`）而不是只写 `/fr/`。
- `-CheckOnly` 注释里的「synthetic `fr/` fallback object」改为复数（`fr/`, `ko/`）。

## 3. 自检（可复核）

### 3.1 release notes JSON

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -c "import json;d=json.load(open('data/release_notes_i18n.json',encoding='utf-8'));print(d['_meta']['versions'], d['_meta']['items'], {k:len(d['v0.13.8'][k]) for k in ('zh','en','es','fr','zh-Hant','ko')})"
# → 77 311 {'zh': 3, 'en': 3, 'es': 3, 'fr': 3, 'zh-Hant': 3, 'ko': 3}
```

- 字节 diff（相对 v0.13.7 的基线文件）：只追加/替换 `_meta` 与 v0.13.8 块，历史内容不改。
- 历史块顺序 + 每块键序：逐块断言「改前键序 == 改后键序」，通过。
- `deploy/i18n_check.py`（site-ui 改后版本，补第 3 条后复跑）：

```
== i18n 一致性门禁（en / es / zh / zh-Hant / fr / ko）==
有效字典: en 667 / es 667 / zh 667 / zh-Hant 667 / fr 667 / ko 667 键
fr 译文: 663/667 键（99.4%，其余回落英文；已有缺口，非本次引入）
release notes: CHANGELOG 77 版 / json 77 版，最新 v0.13.8 译文齐；缺 0 版（0 条待译）
FAIL 0 / WARN 2 / INFO 26
```

WARN 2 = 既有 `es` `form.kit` / `form.gas` 同形可疑（与本改动无关）。
- `etl/check_translations.py --json`：`stats.release_notes = {'versions': 77, 'items': 311}`，**findings 0**。

### 3.2 deploy 链

- `python -m py_compile deploy/verify_live.py deploy/fix_fr_root.py` → exit 0；两者 `--help` 正常。
- `fix_fr_root.py` dry-run（真实 `site/dist`，旧产物只有 `fr/`）：`WARN: 源文件不存在 site\dist\ko\index.html（跳过 /ko/ 兜底）`
  + `[dry-run] 将 PUT r2:<bucket>/fr/ ← site\dist\fr\index.html（187,327 B）`，exit 0。
- 自建夹具 `.tmp/fake-dist/{fr,ko}/index.html`：默认语言列表与显式 `--langs fr,ko` 都输出**两条** PUT 计划；
  `--langs 'fr,XX!'` → `ERROR: 非法语言标签` exit 2；`--langs de`（无源文件）→ 两条 WARN + exit 2。
- `sync_r2.ps1`：`[System.Management.Automation.Language.Parser]::ParseFile` → **0 个语法错误**；
  `--langs ($FallbackLangs -join ',')` 的实参形态在夹具上冒烟（一条参数、不是两条）。
- `verify_live.py` 自检（不联网）：`LANG_ROOTS` = `['/', '/es/', '/zh/', '/zh-hant/', '/fr/', '/ko/']`（6 条）；
  构造含 6 语言 + `x-default` 的 head → `hreflang_targets` 7 条 / 6 个唯一目标，`hreflang-links` 门槛（≥6）通过。

### 3.3 数字口径（只读）

```python
sqlite3.connect("file:data/drugs.db?mode=ro", uri=True)
SELECT COUNT(*) FROM product            -- 594,781
# data/markets.json enabled            -- 15: US GB CA AU ES MX CN TW SG HK FR EU JP CZ LV
```

## 4. 发现（交 site-ui / Lead，本工位不改 `site/build.py`）

1. **`/fr/`、`/ko/` 的 whats-new 正文会整块空白（P1）**：`build_whats_new()` 只渲染
   `("zh", "en", "es", "zh-Hant")` 四个 `data-lang-block`（`site/build.py:10789`），而语言切换 JS
   （`site/build.py:17145`）按 `window.LANG` 把「非当前语言」的块全部 `display:none`。
   `/fr/` 页面 `window.LANG='fr'`，页里没有 `data-lang-block="fr"` → **一个 block 都不显示**。
   现网旧产物可复现：`site/dist/fr/whats-new.html` 有 `en/es/zh/zh-Hant` 4 块、**0 个 `fr` 块**。
   v0.11.4 起 fr 就一直如此（当时漏检），v0.13.8 会让 `/ko/whats-new.html` 同样空白。
   建议：块列表补 `fr`、`ko`（`item.get(lang) or item.get("zh")` 已有回落，补上即生效）。
2. **`/ko/` 首页「最近更新」的一句话会被英文顶替（P2）**：`_inject_release_liners()` 的动态键
   `rel.<version>` 只注入 `("en","es","zh","zh-Hant","fr")`（`site/build.py:14180`）。
   /ko/ 首页服务端先渲染出我新加的韩文一句，随后 `window.T()` 找不到 `rel.v0.13.8` 的 ko 值 → 回落 `D.en`（英文）。
   建议：循环里补 `"ko"`（本次 JSON 已有 ko 译文，补上即取到韩文）。

两条都只在 `site/build.py`（site-ui 写域），本工位只记录、不改。

**状态（2026-11-18，重建前）**：Lead 已确认两处都修（LG1 验收不合格项），site-ui 改 `site/build.py`。
在**首轮构建产物**（`dist`，重建前的这一版）上复验通过：
- whats-new 的 v0.13.8 小节六语块齐全：首轮构建（CHANGELOG 还是 2 条时）每块 **2 条**；
  CHANGELOG 补第 3 条后，重建产物应为每块 **3 条**，重建后复验。`/fr/whats-new.html` 也出现
  `data-lang-block="fr"`，不再只有 4 块。
- `/ko/` 首页 v0.13.8 的 liners 是韩语：`여섯 번째 인터페이스 언어 추가:`（`data-i18n="rel.v0.13.8"`），
  JS 注入后没有被英文顶替。v0.13.7 / v0.13.6 仍是英文兜底——这两版本来没有 ko 译文，属既有回落口径，不是缺陷。
- 但同一次扫描又发现**同一类「只生成 4 语 label」的更大缺口**，见 §5.3；不在 §4 这两条修复范围内。

## 5. 阶段 2 实测（2026-11-18，三版产物）

> 用途：固定「改前 → 修后」的事实链。三版产物：**首轮构建**（six-language 初版）→ **重建 #1**（壳层/分类/coverage 修复 + 六语 i18n + 数据块 en 兜底）→ **重建 #2**（`_lang_block_text` 补 ko，2026-11-18 晚）。
> 本机静态服务：`& $py serve.py 8000`（服务 `site/dist`，**不用线上**），全程只读 `dist`。

### 5.1 i18n 复跑：FAIL 0（最终源 = 干净重建 #2）

```
& $py deploy/i18n_check.py --json .tmp/i18n-final2.json --max-list 5     # 重建 #2 产物
== i18n 一致性门禁（en / es / zh / zh-Hant / fr / ko）==
有效字典: en 667 / es 667 / zh 667 / zh-Hant 667 / fr 667 / ko 667 键
fr 译文: 663/667 键（99.4%，其余回落英文；既有缺口，非本版引入）
release notes: CHANGELOG 77 版 / json 77 版，最新 v0.13.8 译文齐；缺 0 版（0 条待译）
硬编码文案: 0 处 {}
伪翻译(值==en): 106 条 {'INFO': 104, 'WARN': 2}
FAIL 0 / WARN 2 / INFO 26        （WARN 2 = 既有 es form.kit / form.gas，与本改动无关）
```

- 重建 #1 的中间态曾跑到 **683 键**（那次修法引入了分类/兜底专用键）；干净重建 #2 用「v0.13.8 + 一行
  `_lang_block_text` 热修」后回到 **667 键**，六语键集仍一致、`FAIL 0`。

### 5.2 静态核验（重建 #2 产物复跑，全部通过）

| 项 | 读数 | 判定 |
|---|---|---|
| `/ko/` 七页 `<html lang>` | 7/7 = `ko` | 通过 |
| hreflang（每页） | 8 条：`en/es/zh/zh-Hant/zh-TW/fr/ko/x-default`，六语互指；逐个目标的本地文件都存在 | 通过 |
| canonical | `https://drugcrossref.com/ko/`、`/ko/about.html`…`/ko/whats-new.html` 逐页正确 | 通过 |
| 根首页 hreflang | 含 `ko → https://drugcrossref.com/ko/` + `x-default` | 通过 |
| 语言菜单 | `/ko/` 首页出现「한국어」3 次（菜单 + 移动抽屉） | 通过 |
| `sitemap.xml` | `<url>` **75,609** / `<loc>` 75,609 / 其中 ko **7** / 重复 `<loc>` **0** | 通过 |
| `/ko/whats-new.html` 正文 | v0.13.8 小节**六语块 × 3 条**（`zh/en/es/fr/zh-Hant/ko` 各 3 个 `<li>`） | 通过 |
| `/ko/` 首页 liners | 服务端 `rel.v0.13.8` = 「여섯 번째 인터페이스 언어 추가:」；`assets/i18n.ko.js` 里同一键也是韩语 → JS 注入后不会被英文顶替；v0.13.7/6 = 英文（这两版无 ko 译文，既有回落口径） | 通过 |

### 5.3 P1：`data-lang-block` 只生成 en/es/zh/zh-Hant → ko/fr 页面大面积空白

**扫描口径**（脚本 `.tmp/scan_lang_blocks.py`，headless Chrome + 只读静态服务，1440x900）：
对每个「直接子节点里有 `data-lang-block` 的容器」判两件事——
`noVisible` = 一个可见块都没有（整块空白）；`emptyVisible` = 有可见块但可见文本为空。
「可见」= 该块 `display`/`visibility` 正常，文本用 `textContent`（**不收 `offsetParent` / `innerText`**：
折叠抽屉里的导航块本身是隐藏容器，用 `innerText`/`offsetParent` 会把「有 ko 块但抽屉没展开」误判成空白。
口径修正的对照见下面的收敛链）。

**收敛链（22 页 / 1316 个容器）**

| 产物 / 口径 | noVisible | emptyVisible | 说明 |
|---|---:|---:|---|
| 首轮构建（修复前，口径 v1：+offsetParent/innerText） | **823** | **148** | 是 v1 口径读数；v1 会把隐藏容器（抽屉/折叠块）误判为空白，故 148 含误报，不能当精确真值 |
| 重建 #1（壳层/分类/coverage/六语 i18n/数据块 en 兜底，口径 v1） | 401 | 500 | v1 把「隐藏抽屉里有 ko 块」误判为空白（样本全是 `A` 导航链） |
| 重建 #1（口径 v2：display/visibility + textContent） | **340** | **0** | 误报清零，剩下的是真缺口 |
| 重建 #2（`_lang_block_text` 补 ko，口径 v2） | **0** | **0** | **PASS**（22 页逐页 0/0，见 §5.6） |

重建 #1 在口径 v2 下的 340 个 `noVisible` 全部落在 **ko 的 6 个页面**，块语言清一色 `en,es,zh,zh-Hant,fr`（缺 ko）：
`/cat/analgesics.html?lang=ko` 80、`/cat/antibiotics.html?lang=ko` 126、`/atc/R06A.html?lang=ko` 27、
`/atc/N02BE.html?lang=ko` 2、`/drug/acetaminophen.html?lang=ko` 92、`/drug/tirzepatide.html?lang=ko` 13；
涉及 `.ln`（规格/记录摘要）、`.ms-more`（还有 N 个）、`.sub.atc-count`（N 个活性成分）、`.und-h`（未公开规格块头）、
full-list 链接。**单一根因**：`_lang_block_text()`（`site/build.py:15798`）硬编码
`["en","es","zh","zh-Hant"] + ["fr"]`，v0.11.4 加了 fr 却漏了 ko；`.atc-src-line` 等直接走
`I18N_REQUIRED_LANGS` 的块已是 6 语，证明其余循环都修到了。重建 #2 改这一行后应收敛到 0/0。

**改前（v0.13.8 首轮构建，2026-11-18，22 页，口径 v1）：1316 个容器 / `noVisible` 823 / `emptyVisible` 148**

| 页面（URL） | 语言 | 容器 | 无可见块 | 可见但空 | 明细 |
|---|---|---:|---:|---:|---|
| `/ko/index.html` | ko | 24 | **24** | 0 | 8 个首页分类 chip（`.catgrid a .catchip`）+ 16 个导航抽屉分类链接（`.sn-cats a`） |
| `/fr/index.html` | fr | 24 | **24** | 0 | 同上（fr 自 v0.11.4 起如此） |
| `/ko/warn.html` | ko | 56 | **56** | 0 | 16 导航 + **40 条警示正文**（`article.warn-item` 只写 en/zh/es） |
| `/fr/warn.html` | fr | 56 | **56** | 0 | 同 ko |
| `/ko/coverage.html` | ko | 16 | 16 | 0 | 全是导航分类链接（正文/覆盖表 15 行正常） |
| `/fr/coverage.html` | fr | 16 | 16 | 0 | 同 ko |
| `/ko/glossary.html` | ko | 17 | 17 | 0 | 16 导航 + 1 个 `.wrap` 块 |
| `/fr/glossary.html` | fr | 17 | 17 | 0 | 同 ko |
| `/cat/analgesics.html?lang=ko` | ko | 100 | **100** | 0 | 导航 + 约 84 个内容块（H1 空、面包屑、分类名/描述、ATC 列表项空） |
| `/cat/analgesics.html?lang=fr` | fr | 100 | 20 | 6 | fr 块部分存在但文本空 |
| `/cat/antibiotics.html?lang=ko` | ko | 145 | **145** | 0 | 同源（分类页内容块最多） |
| `/cat/antibiotics.html?lang=fr` | fr | 145 | 19 | **41** | fr 有可见块但文本为空 |
| `/atc/R06A.html?lang=ko` | ko | 51 | 51 | 0 | 导航 + H1、来源行、成分计数等 |
| `/atc/R06A.html?lang=fr` | fr | 51 | 24 | 0 | 同源 |
| `/atc/N02BE.html?lang=ko` | ko | 19 | 19 | 0 | 同源 |
| `/atc/N02BE.html?lang=fr` | fr | 19 | 17 | 0 | 同源 |
| `/drug/acetaminophen.html?lang=ko` | ko | 108 | **108** | 0 | 导航 + 约 92 个标签（`Other strengths: 104 · 9 dosage forms`、`This form has 3 more` 等 `.ln` / `.ms-more`） |
| `/drug/acetaminophen.html?lang=fr` | fr | 108 | 16 | **89** | fr 有可见块但文本为空 |
| `/drug/tirzepatide.html?lang=ko` | ko | 29 | 29 | 0 | 同源 |
| `/drug/tirzepatide.html?lang=fr` | fr | 29 | 17 | 12 | 同源 |
| `/ko/whats-new.html` | ko | 93 | 16 | 0 | 仅导航（首轮构建时 v0.13.8 小节六语块 × 2 条已正常；重建后应 × 3 条） |
| `/fr/whats-new.html` | fr | 93 | 16 | 0 | 仅导航（四语块问题已由 site-ui 修好） |

- `/ko/?q=tylenol`（结果页）此前单独扫过：只有 24 个导航空链，**20 行结果内容正常**；`/name/tylenol-extra-strength.html?lang=ko`
  只有 16 个导航空链，正文正常。claim 里的「搜索结果」不受影响。
- 根因（`site/build.py`）：`SHELL_LANGS`（导航分类）/ `_home_cat_chips()` 只写 4 语、`_warn_block()` 只写 en/zh/es、
  `CONSUMER_CATEGORIES[].labels` 与 ATC 显示名也只有 4 语；JS（`site/build.py:17145`）按 `window.LANG` 隐藏
  「非当前语言」的块 → 容器里没有当前语言块时整块空白。
- 修复方向（Lead 2026-11-18 定，site-ui 执行）：① i18n 驱动的块循环 4 语 → 6 语；
  ② 数据型警示正文不做机翻，客户端「无匹配语言块 → 显示 en（zh-Hant 优先 zh）」兜底；
  ③ `boot.js` 烘焙壳分类链接补 fr/ko。改后结论见 §5.6。
- 证据截图（改前）：`docs/img/ko-home-before-fix.png`（8 个空 chip）、
  `docs/img/ko-cat-blank-before-fix.png`（`/cat/analgesics.html?lang=ko`：H1 空、「관련 ATC 분류」两条空 bullet）。

### 5.4 P2：语言副本页请求 `/<lang>/data/*.json` → 404

- `/ko/coverage.html`、`/ko/about.html`、`/ko/confused.html`、`/ko/glossary.html`、`/ko/warn.html`、`/ko/whats-new.html`
  控制台各 2 条 404：`http://127.0.0.1:8000/ko/data/sources.json`、`http://127.0.0.1:8000/ko/data/terms.json`。
- 同一路径在根下是 **200**：`/data/sources.json` 1,441 B、`/data/terms.json` 185,110 B；
  `/fr/coverage.html` 同样 404 两条（预存在）。
- 影响：两文件是补充数据（页面主体仍正常：`/ko/coverage.html` 覆盖表 **15 行**、标题/说明韩语正常），
  但控制台报错、且任何依赖这两个 JSON 的增强功能在语言副本页上静默失效。
- 修后断言：六个语言副本页加载后 **0 条 4xx**，且请求路径是站点根相对（`/data/sources.json`、`/data/terms.json`），
  不再是 `/<lang>/data/...`。
- **重建 #1 复验：已修**。22 页语言块扫描里逐页统计的 4xx 全为 **0**（首轮构建时 warn/coverage/glossary/about/confused/whats-new
  各 2 条 404，重建后 0）；页面主体照旧（覆盖表 15 行）。
- **重建 #2 终验：仍为 0**。四张 `/ko/` 截图（首页 / 结果 / 成分 / 覆盖）加载后控制台与静态服务日志均无 4xx
  （`docs/img/ko-*.png` 由 headless Chrome 逐页采集，脚本同时记录 4xx=空）。

### 5.5 修后应验的断言（全部通过，重建 #2 终验）

- [x] `/ko/index.html`：`.catgrid a.catchip` **8/8 文本非空**、`.sn-cats a` **16/16 非空**（`/fr/` 同；重建 #1/#2 扫描该页 0/0）。
- [x] `/ko/warn.html`：**56 个容器 0/0**（含 40 条警示正文；数据型正文按 en 兜底 + `(EN)` 标注）。
- [x] `/ko/coverage.html`、`/ko/glossary.html`、`/ko/about.html`、`/ko/confused.html`、`/ko/whats-new.html`：**0/0**。
- [x] 六个语言副本页控制台 **0 条 404**；`data/sources.json`、`data/terms.json` 不再落到 `/<lang>/data/`。
- [x] `/ko/whats-new.html`：v0.13.8 小节 **六语块 × 3 条**，ko 正文非空。
- [x] hreflang / canonical / `sitemap.xml`（ko 7 条、无重复）/ html lang=ko / 语言菜单「한국어」。
- [x] `/cat/*?lang=ko`、`/atc/*?lang=ko`、`/drug/*?lang=ko`：重建 #1 的 **340 个 noVisible → 重建 #2 = 0**。
- [x] 语言块总扫描：**22 页 / 1316 容器 / 0 / 0 → PASS**（见 §5.6）。
- [x] 首屏守卫 ko 四档 + 与基线对比（见 §5.7）。

### 5.6 改后复扫（重建 #2 = 0/0 PASS）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp/scan_lang_blocks.py --json .tmp/lang-blocks-final.json
# 22 页 / 1316 容器 / noVisible 0 / emptyVisible 0 → PASS
```

| 指标 | 首轮构建（口径 v1） | 重建 #1（口径 v2） | 重建 #2（口径 v2） |
|---|---:|---:|---:|
| 容器数 | 1316 | 1316 | **1316** |
| 无可见块 `noVisible` | 823 | **340**（全是 ko 的 cat/atc/drug，5 语块） | **0** |
| 可见但空 `emptyVisible` | 148（含 v1 误报） | **0** | **0** |
| 逐页 4xx | 每副本页 2 条（`/<lang>/data/*.json`） | 0 | **0** |
| 断言 | FAIL | FAIL（剩 `_lang_block_text` 缺 ko） | **PASS** |

22 页逐页读数：`/ko/` 与 `/fr/` 的首页、warn、coverage、glossary、whats-new、cat×2、atc×2、drug×2 **全部 0/0**；
容器数与原清单一致（24/56/16/17/93/100/145/51/19/108/29），没有页型被跳过。

### 5.7 首屏守卫（四档）+ 4 张截图（重建 #2）

**zh 全量 vs v0.13.7 基线**（`deploy/first_screen_check.py --baseline .tmp/first-screen/ci.json`）：
24 组扫描（6 页型 × 4 视口）、不稳定 0、疑似 0、**baseline 退化 0 项**；未达标 3 项且全是 items（Q18 已知）：
`results@390` 3.5、`drug@1440` 4.5、`coverage@390` 3.5（门槛 5）。AFCR / chrome / 字号 / 溢出全部在阈值内。

**ko 四档**（`.tmp/run_first_screen_ko.py`，home/results/coverage 走 `/ko/` 副本页，drug/name/atc 走 `?lang=ko`）：
24 组扫描、不稳定 0、疑似 0；未达标 **2 项**：`results@390` items 3.5、`coverage@390` items 3.0（同为 Q18 已知）。
对 v0.13.7 zh 基线报 9 项 items 差（-5.2% ~ -15.4%）；与**同版本 zh 读数**逐组比对后确认是韩文标签更长的排版差异：

| 页面×视口 | zh items | ko items | 差 |
|---|---:|---:|---:|
| home 768 / 1440 | 9 / 9 | 8.5 / 8 | -0.5 / -1 |
| atc 390 / 768 / 1440 / 2560 | 7.5 / 13 / 13.5 / 48.5 | 6.5 / 11 / 12 / 46 | -1 / -2 / -1.5 / -2.5 |
| coverage 390 / 768 / 1440 / 2560 | 3.5 / 8.5 / 6 / 15 | 3 / 8 / 5.5 / 14.5 | -0.5 ~ -1 |
| drug 390 / 768 / 1440 | 5.5 / 5.5 / 4.5 | 6 / 6 / 5 | **+0.5**（ko 更多） |
| results 768 | 10.5 | 11 | **+0.5**（ko 更多） |

- 其余指标：AFCR / chrome_ratio / overlay_ratio 差异 >0.02 的组 **0**；横向溢出 **0**；正文 16px、辅助 13–14px 全站一致。
- 结论：**ko 无构建退化**（zh 对基线 0 项；ko 的条目差全部可由语言文本长度解释，且 drug/results 反而更多），
  未达组与 zh 同为 Q18 的 `results@390` / `coverage@390`，留给 v0.14.0。
- JSON：`.tmp/first-screen/v0138-zh.json`、`.tmp/first-screen/v0138-ko.json`；截图目录 `.tmp/first-screen/shots-v0138{,-ko}`。

**交付截图（1440×900，headless Chrome + 本机静态服务，非线上）**

| 文件 | 页面 | 大小 |
|---|---|---:|
| `docs/img/ko-home.png` | `/ko/`（关掉首访「3 步用法」引导的常态视图：韩文分类 chip + 最近更新韩文 liner） | 58,821 B |
| `docs/img/ko-results.png` | `/ko/?q=tylenol`（86 个匹配、9 行结果、国家筛选韩文） | 86,941 B |
| `docs/img/ko-drug.png` | `/drug/acetaminophen.html?lang=ko`（14 市场 / 13,661 记录，`.ln` 等标签韩文，不再空白） | 78,408 B |
| `docs/img/ko-coverage.png` | `/ko/coverage.html`（15 行覆盖表，表头/缺口说明韩文） | 82,451 B |

改前证据（保留）：`docs/img/ko-home-before-fix.png`（8 个空 chip）、`docs/img/ko-cat-blank-before-fix.png`（分类页 H1 与 ATC 列表空白）。

## 6. 重建后的最终一把跑（已执行，2026-11-18 重建 #2）

> 本节命令已在重建 #2 产物上逐条执行；JSON / 截图落 `.tmp/`，交付截图落 `docs/img/`。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 0) 语言块可见性复扫（22 页；结果 0 / 0 → PASS）
& $py .tmp/scan_lang_blocks.py --json .tmp/lang-blocks-final.json

# 1) i18n（FAIL 0）
& $py deploy/i18n_check.py --json .tmp/i18n-final2.json --max-list 5

# 2) 静态核验：hreflang/canonical/sitemap/whats-new + 目标落地
& $py .tmp/check_ko_pages.py
& $py .tmp/check_hreflang_targets.py

# 3) 首屏守卫：zh 全量 vs v0.13.7 基线（.tmp/first-screen/ci.json，2026-11-17 15:17）
& $py deploy/first_screen_check.py --json .tmp/first-screen/v0138-zh.json `
    --baseline .tmp/first-screen/ci.json --shots .tmp/first-screen/shots-v0138

# 4) 首屏守卫：ko 四档（包装脚本把 6 个页型换成 /ko/ 变体，不改 deploy/ 源码；
#    home/results/coverage 用语言副本页，drug/name/atc 用 ?lang=ko）
& $py .tmp/run_first_screen_ko.py --json .tmp/first-screen/v0138-ko.json `
    --baseline .tmp/first-screen/ci.json --shots .tmp/first-screen/shots-v0138-ko
```

- `--viewports` 默认就是 390x844 / 768x1024 / 1440x900 / 2560x1440 四档。
- ko 的 baseline 是 v0.13.7 的 zh 读数：若出现 >5% 的「退化」，先用第 2 步同版本的 zh 读数区分
  「构建退化」还是「韩文文本长度带来的正常差异」，再写结论。
- 4 张交付截图（1440x900，本地服务、非线上）：`/ko/` 首页 → `docs/img/ko-home.png`；
  `/ko/?q=tylenol` → `ko-results.png`；`/drug/acetaminophen.html?lang=ko` → `ko-drug.png`；
  `/ko/coverage.html` → `ko-coverage.png`。
- 静态复核脚本：`.tmp/check_ko_pages.py`（hreflang/canonical/sitemap/whats-new）、
  `.tmp/check_hreflang_targets.py`（hreflang 目标落地）、浏览器 CDP 空容器扫描（§5.3 同一段）。

## 7. 发布注意

- [ ] 发布时注意：`sync_r2.ps1` 的 WARN 若出现「language-root fallback object(s) NOT written」，
      `/ko/`（或 `/fr/`）会在 `verify_live` 里报 `lang-root-/ko/` 失败，需重放 `fix_fr_root.py`。
- [ ] `verify_live.py` 现在会逐个验 6 条语言根（含 `/ko/`），`hreflang-links` 下限 6；
      `/ko/` 404 不会再被 0 failures 漏掉（v0.11.4 `/fr/` 的教训）。

## 8. v0.14.0（2026-11-19，追加）

> 同一工位、同一 JSON 的下一版：CHANGELOG 新增 `## v0.14.0 — 2026-11-19`（5 条），要求六语各 5 条译文。
> 本条先记「文案落盘 + 门禁」，最终产物核验等 `dist ready #3`。

### 8.1 `data/release_notes_i18n.json` 新增 v0.14.0

- 位置：文件末尾 `v0.13.8` 之后；键序与前块一致（`date, zh, en, es, fr, machine_translated, zh-Hant, ko`）。
- 六语各 **5 条**，`zh` 与 CHANGELOG v0.14.0 五条逐字一致（脚本逐条 `identical=True`）。
- `_meta.versions` 77 → **78**、`_meta.items` 311 → **316**（现查一致）。
- 译文口径：韩语沿用 `.tmp/ko_i18n.py`（상품명 / 일반명 / 성분 / 속칭 / 옛 이름 / 별칭 / 제형 / 함량 /
  방출 방식 / 카테고리 / 커버리지 / 판매 중）；es 用 `página de nombre` / `forma farmacéutica` / `concentración`；
  fr 用 `page de nom` / `forme galénique` / `dosage`。数字逐语保留：`960 mg/30 mL`、`0 候选`、`4/7/1`、
  `1,404`（es 1.404 / fr 1 404）、`漏 0`、`11`、`0.0%`、`390px`、`3.5 → ≥5`。

### 8.2 门禁（文案落盘后立即跑）

```
& $py deploy/i18n_check.py --json .tmp/i18n-v0140.json --max-list 5
有效字典: en 684 / es 684 / zh 684 / zh-Hant 684 / fr 684 / ko 684 键
fr 译文: 681/684 键（99.6%，既有缺口）
release notes: CHANGELOG 78 版 / json 78 版，最新 v0.14.0 译文齐；缺 0 版（0 条待译）
FAIL 0 / WARN 2 / INFO 26        （WARN 2 = 既有 es form.kit / form.gas）
```

- `etl/check_translations.py`：`release_notes = {'versions': 78, 'items': 316}`、v0.14.0 相关 findings **0**、
  全库 findings **0**（数字 / 占位符 / HTML 逐条过）。

### 8.3 最终产物核验（等 `dist ready #3`）

> 2026-11-18 Lead 在最终构建上发现一个可修回归并已派 site-ui 修：**`results@768` items 10.5 → 9.5**
> （结果页仍显示 `.tryrow` 示例区，V4 给示例加了第二行后 768 宽度换行、占掉 +40px）。
> 修法：一行 CSS `html.has-q .tryrow{display:none}`；修后**再重建一次**，`dist ready #3` 为最终产物。
> 验收要求：`results@768` 回到 **≥10.5**（与 `.tmp/first-screen/ci.json` 基线 10.5 持平，baseline 退化 0）。

| 项 | 参数 / 目标 |
|---|---|
| 语言块扫描 | `.tmp/scan_lang_blocks.py --json .tmp/lang-blocks-v0140.json`；22 页（ko + fr），目标 **0 / 0** |
| i18n | `deploy/i18n_check.py --json .tmp/i18n-final3.json`；**FAIL 0**，`最新 v0.14.0 译文齐` |
| 静态核验 | `.tmp/check_ko_pages.py` + `.tmp/check_hreflang_targets.py`；hreflang 8 条 / canonical / sitemap 75,609·ko 7·重复 0 / whats-new v0.14.0 **六语 × 5 条** / liners |
| zh 首屏 | `deploy/first_screen_check.py --json .tmp/first-screen/v0140-zh.json --baseline .tmp/first-screen/ci.json --shots .tmp/first-screen/shots-v0140`；**6 页型 × 4 视口 = 24 组**，`results@768` 目标 **≥10.5**、baseline 退化 **0** |
| ko 首屏 | `.tmp/run_first_screen_ko.py --json .tmp/first-screen/v0140-ko.json --baseline .tmp/first-screen/ci.json --shots .tmp/first-screen/shots-v0140-ko`；24 组四档 |
| 截图 | `.tmp/shoot_ko_v0140.py` → `docs/img/v0140-ko-{home,results,drug,coverage}.png`（1440×900，本地服务；首页先关「3 步用法」引导） |

**`results@768` 修复前后（待最终产物回填）**

| 产物 | results@768 items | 说明 |
|---|---:|---|
| v0.13.7 基线（`.tmp/first-screen/ci.json`） | 10.5 | 发布门槛参照 |
| v0.14.0 首次最终构建（修复前） | **9.5** | `.tryrow` 示例区在 768 占 +40px |
| v0.14.0 重建（`html.has-q .tryrow{display:none}` 后） | 目标 **≥10.5** | 待 `dist ready #3` 回填 |

- [ ] 语言块扫描（`.tmp/scan_lang_blocks.py`，22 页含 ko + fr）→ 目标 **0 / 0**；
      新增页面类型/锚点若超出 22 页清单，按新页补扫（v0.14.0 的「也叫」区块在成分页，已在 drug 两页覆盖）。
- [ ] `i18n_check` 复跑 → FAIL 0，`最新 v0.14.0 译文齐`。
- [ ] 静态核验：hreflang / canonical / sitemap（ko 7）/ whats-new v0.14.0 六语 × 5 条 / liners。
- [ ] zh 首屏四档对 `.tmp/first-screen/ci.json` 基线（`results@768` ≥10.5）；ko 四档（`.tmp/run_first_screen_ko.py`）。
- [ ] 4 张截图另存 `docs/img/v0140-ko-{home,results,drug,coverage}.png`（1440×900，本地服务）。
      v0.14.0 影响首页示例、名字页规格折叠、成分页「也叫」、分类/覆盖页计数、手机结果卡，四张都要重截。
