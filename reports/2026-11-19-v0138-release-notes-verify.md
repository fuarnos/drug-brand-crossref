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
2. **门禁已绿**：`deploy/i18n_check.py`（site-ui 正在改的版本，含 ko 分支）→ **FAIL 0 / WARN 2 / INFO 25**，
   `release notes: CHANGELOG 77 版 / json 77 版，最新 v0.13.8 译文齐；缺 0 版`；六语有效字典各 **667 键**。
   `etl/check_translations.py` → release notes **77 版 / 311 条 / 0 findings**（数字 / 占位符 / HTML 逐条过）。
3. **发布链兜底已泛化**（Lead 追加）：`verify_live.py` 的 `LANG_ROOTS` 加第 6 条 `("ko/", "/ko/")`；
   `fix_fr_root.py` 从「只写 `fr/`」改为按语言列表逐 PUT（默认 `fr,ko`，新增 `--langs`）；
   `sync_r2.ps1` 同步后按 `$FallbackLangs = @('fr','ko')` 调它，失败仍只 WARN、不影响上传退出码。
4. **数字现查核对**（只读开库）：产品 **594,781**（`SELECT COUNT(*) FROM product`）、启用市场 **15**
   （`data/markets.json` enabled 15 项），与 v0.13.8 文案里的「15 个市场 / 594,781 条不变」一致。
5. **移交 site-ui 两个渲染缺口**（不在本工位写域，见 §4）：`/fr/`、`/ko/` 的 whats-new 正文会被 JS 全部隐藏；
   `/ko/` 首页「最近更新」的一句话会被英文顶替。

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

## 5. 阶段 2 实测（dist = v0.13.8 首轮构建产物，2026-11-18）

> 用途：先固定「重建前」的事实与证据；等 Lead 重建（修 §5.3 / §5.4）后，同一批命令复跑一次作最终数字。
> 本机静态服务：`& $py serve.py 8000`（服务 `site/dist`，**不用线上**），全程只读 `dist`。

### 5.1 i18n 复跑：FAIL 0

```
& $py deploy/i18n_check.py --json .tmp/i18n-stage2.json --max-list 5
== i18n 一致性门禁（en / es / zh / zh-Hant / fr / ko）==
有效字典: en 667 / es 667 / zh 667 / zh-Hant 667 / fr 667 / ko 667 键
fr 译文: 663/667 键（99.4%，其余回落英文；既有缺口）
release notes: CHANGELOG 77 版 / json 77 版，最新 v0.13.8 译文齐；缺 0 版（0 条待译）
硬编码文案: 0 处 {}
伪翻译(值==en): 106 条 {'INFO': 104, 'WARN': 2}
FAIL 0 / WARN 2 / INFO 25        （WARN 2 = 既有 es form.kit / form.gas，与本改动无关）
```

### 5.2 静态核验（全部通过，重建后按同一脚本复核）

| 项 | 读数 | 判定 |
|---|---|---|
| `/ko/` 七页 `<html lang>` | 7/7 = `ko` | 通过 |
| hreflang（每页） | 8 条：`en/es/zh/zh-Hant/zh-TW/fr/ko/x-default`，六语互指；逐个目标的本地文件都存在 | 通过 |
| canonical | `https://drugcrossref.com/ko/`、`/ko/about.html`…`/ko/whats-new.html` 逐页正确 | 通过 |
| 根首页 hreflang | 含 `ko → https://drugcrossref.com/ko/` + `x-default` | 通过 |
| 语言菜单 | `/ko/` 首页出现「한국어」3 次（菜单 + 移动抽屉） | 通过 |
| `sitemap.xml` | `<url>` **75,609** / `<loc>` 75,609 / 其中 ko **7** / 重复 `<loc>` **0** | 通过 |
| `/ko/whats-new.html` 正文 | 首轮构建：v0.13.8 小节六语块 × 2 条；ko 块 556 字符、含韩国语正文（重建后应 × 3 条） | 通过（重建后复验 3 条） |
| `/ko/` 首页 liners | v0.13.8 = 韩语；v0.13.7/6 = 英文（无 ko 译文的既有回落） | 通过 |

### 5.3 P1：`data-lang-block` 只生成 en/es/zh/zh-Hant → ko/fr 页面大面积空白

**扫描口径**（脚本 `.tmp/scan_lang_blocks.py`，headless Chrome + 只读静态服务，1440x900）：
对每个「直接子节点里有 `data-lang-block` 的容器」判两件事——
`noVisible` = 一个可见块都没有（整块空白）；`emptyVisible` = 有可见块但可见文本为空。
「可见」= `display`/`visibility` 正常且 `offsetParent` 不为 null；语言由 `applyLang` 跑完后取 `window.LANG`。

**改前（v0.13.8 首轮构建，2026-11-18，22 页）：1316 个容器 / `noVisible` 823 / `emptyVisible` 148**

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

### 5.5 修后应验的断言（重建后逐条打勾）

- [ ] `curl` 式扫描：`.tmp/scan_lang_blocks.py`（22 页）→ **`noVisible 0 / emptyVisible 0`**（改前 823 / 148）。
- [ ] `/ko/index.html`：`.catgrid a.catchip` **8/8 文本非空**、`.sn-cats a` **16/16 非空**（`/fr/` 同）。
- [ ] `/ko/warn.html`：`article.warn-item` 正文 **40/40 非空**（英文兜底也算过）。
- [ ] `/cat/*?lang=ko`、`/atc/*?lang=ko`、`/drug/*?lang=ko`：空容器只剩 **0**（导航分类修完后应为 0）。
- [ ] 六个语言副本页控制台 **0 条 404**；Network 里 `data/sources.json`、`data/terms.json` 为 200。
- [ ] `/ko/whats-new.html`：v0.13.8 小节 **六语块 × 3 条**，ko 正文非空。
- [ ] hreflang / canonical / `sitemap.xml`（ko 7 条、无重复）/ html lang=ko 与本报告 §5.2 一致。
- [ ] 首屏守卫 ko 四档 + 与基线对比（见 §6 命令）。

### 5.6 改后复扫（待重建后填）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp/scan_lang_blocks.py --json .tmp/lang-blocks-after.json
# 期望：22 页 / 1316 容器 / noVisible 0 / emptyVisible 0 → PASS
```

| 指标 | 改前（首轮构建） | 改后（重建产物） |
|---|---:|---:|
| 容器数 | 1316 | 待填 |
| 无可见块 `noVisible` | **823** | 待填 |
| 可见但空 `emptyVisible` | **148** | 待填 |
| 断言 | FAIL | 目标 0 / 0 |

## 6. 重建后一把跑（命令已备好）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 0) 语言块可见性复扫（22 页；期望 noVisible 0 / emptyVisible 0）
& $py .tmp/scan_lang_blocks.py --json .tmp/lang-blocks-after.json

# 1) i18n（应 FAIL 0）
& $py deploy/i18n_check.py --json .tmp/i18n-final.json --max-list 5

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
