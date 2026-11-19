# v0.18.0 首页精简 E1–E5：现状审计 + 设计稿

- 日期：2026-11-20
- 工位：alias-site（只读；**未改** `site/build.py`、`site/dist`、`data/drugs.db`、`CHANGELOG.md`，只写本报告）
- 范围：E1 合并重复导航 / E2 搜索按钮显示文字 / E3 三个可点击示例 / E4 移走加载机制说明 / E5 更新日志一句话
- 基线快照（**先看这一条**）：本轮开始时 `site/dist` 正被另一工位重建（09:01 起 python 进程，语言目录暂为空、文件数 104,705），**没有**拿它做基线。现状审计用 `.tmp/build_ja`（v0.16.0、2026-11-20、7 语完整；根页 en 202,637 B / ja 210,128 B）+ 当前 `site/build.py`（19,415 行）交叉核对。最终实现必须先按 §3 重建当前 HEAD 的 before/after，不要用旧 dist。
- 首屏基线（`.tmp/build_ja`，`first_screen_check --pages home --viewports 390x844,1440x900`，2026-11-20 09:04）：

| 视口 | AFCR | 首屏条目 | chrome | 悬浮 | 正文字号 | 辅助字号 | <14px 占比 | 横向溢出 |
|---|---|---|---|---|---|---|---|---|
| 390×844 | **0.93** | **0.0** | 0.14 | 0.068 | 16px | 14px | 10% | 否 |
| 1440×900 | **1.00** | **9.0** | 0.07 | 0.000 | 16px | 14px | 6% | 否 |

> 截图：`.tmp/e1-e5-20261120/before/fs-home-390x844.png`、`.tmp/e1-e5-20261120/before/fs-home-1440x900.png`；JSON：`.tmp/e1-e5-20261120/before-home.json`。390 档「首屏条目 0」是现状事实（类别卡/更新日志都在首屏外），E3 的三个示例正好可作为 390 首屏的第一组可点条目。

---

## 0. 结论先行

| 项 | 现查结论 | v0.18.0 设计要点 |
|---|---|---|
| **E1 合并重复导航** | **顶部「按类别」= 1 次**（`header` 里唯一 `data-i18n="nav.categories"`；v0.11.10 已删右上角重复入口）。但 header 下拉里还有 **16 个类别链接**（8.9 KB/页），首页另有 **8 个类别卡**（`catquick`，5.9 KB），且品牌中文名在 **1024–1279 / 1100–1440 / ≤767** 被 `display:none`（5 处 CSS），1280/1440 截图中确实看不到「药品商品名跨国定位」 | **推荐 A**：header「Categories」改成**直接链 `/atc.html`**（不再下拉 16 链），保留首页 8 个类别卡；页面底部 tabbar 的「类别」是移动导航，不动。另修 `logo-zh` 在 ≥1024 显示、390 仍隐藏。header 预计 13.0 KB → ≤4.5 KB/页，`boot.js` 少约 8.9 KB（一次，全站受益） |
| **E2 搜索按钮** | 桌面已有「搜索 →」，**390 只有箭头**：CSS `.sb-go .sbg-t{display:none}`，`@media (min-width:768px){…display:inline}`（6033/6035 行）；390 截图确认 | 文字在**所有宽度显示**；<480 隐藏箭头只留文字，`#q` 右内边距按按钮宽度重算；不新增 i18n 键（复用 `home.submit`） |
| **E3 三个示例** | `tryrow` **只有 2 个可点项**：V4 跨国链接 1 + 包装文字按钮 1；V4 那条**在**（`?q=Tylenol+Extra+Strength&src=US&country=CN`）。`HOME_EXAMPLES` **没有 ja 条目** | `quick` 改成 2 项（V4 链接 + 本地通用名按钮），保留 `pack` 1 项 → **3 个**；补 `HOME_EXAMPLES["ja"]`。三个示例逐个用 `cli.py` 验证 ≥1 候选（§附录 B） |
| **E4 加载机制说明** | 首页**已无** `42 MB / gzip / 分片` 可见文字（0 处，E4 已搬迁）；`/about.html` + 6 个语言副本各有 1 节技术说明（保留）。但**加载中提示仍含技术数字**：`home.hint_loading` 7 语中 6 语有「分片/中位 1.0 MB/gzip」；`home.hint_idle` 7 语是**死键**（`HINT_IDLE=''`，从不显示） | `home.hint_loading` 改成「正在补全搜索结果… / Loading more results…」7 语；**删除** `home.hint_idle` 7 键；`about.loading` 技术说明保留；失败路径沿用 `error.index_failed` + `error.retry` |
| **E5 一句话变化** | 首页「最近更新」**有** `rel.v0.16.0` 等动态键，**但 6/7 语以冒号结尾**（`New 7th interface language:` / `新增第 7 种界面语言：`）；ja 的 v0.15.0 / v0.14.0 **缺译文，回落英文**（`The coverage page now adds…`） | `_release_oneliner` 先取首条 `**标题**`（去尾部冒号），再取首句；**不再在冒号/分号处切**；上限 48 字；首页缺本地译文**不回落英文**（只显示版本+日期）。补 `data/release_notes_i18n.json` 的 ja v0.15.0/v0.14.0 首条；`build_whats_new` 的旧版回落规则保持并加 `(EN)` 说明 |

**不新增 i18n 键**（E2/E3 复用 `home.submit`、`u1.try`、`home.try_pack`；E4 是改值/删键；E5 是动态 `rel.*` + 数据补译），所以 `deploy/i18n_check.py` 的目标仍是 **FAIL 0**，不是「加键后重跑」。
**红线：** 示例只教「怎么查」，点击后仍是候选集；不新增任何「可替代/可互换/剂量换算/用药建议」；不碰 `collision` 视图、`dose_warning`、`product_name`、`nickname` 数据；不改任何入库/写库脚本。

---

## 1. 现状审计（7 语首页）

### 1.1 审计口径

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
# 现状构建（本轮用 .tmp/build_ja，避免踩正在重建的 site/dist）
Get-Item .tmp\build_ja\index.html, .tmp\build_ja\ja\index.html |
  Select-Object FullName,Length,LastWriteTime
# 首屏 2 档 + 截图
& $py deploy/first_screen_check.py --dist .tmp/build_ja --pages home `
  --viewports 390x844,1440x900 `
  --json .tmp/e1-e5-20261120/before-home.json `
  --shots .tmp/e1-e5-20261120/before
```

7 语首页文件（`.tmp/build_ja`）：

| 语言 | 根文件 | 大小 |
|---|---|---|
| en | `index.html` | 202,637 B |
| es | `es/index.html` | 207,254 B |
| zh | `zh/index.html` | 198,625 B |
| zh-Hant | `zh-hant/index.html` | 198,443 B |
| fr | `fr/index.html` | 197,451 B |
| ko | `ko/index.html` | 207,262 B |
| ja | `ja/index.html` | 210,128 B |

### 1.2 E1 现状：顶部类别入口与 header 体积

| 语言 | header `data-i18n="nav.categories"` | 底部 tabbar `tab.categories` | header 下拉类别链接 | header `sn-dd` 下拉字节 | 首页类别卡 |
|---|---|---|---|---|---|
| en | **1** | 1（移动底栏，非顶部） | **16** | 8,872 B | 8 |
| es / zh / zh-Hant / fr / ko / ja | **1** | 1 | **16** | 8,923 B | 8 |

- 结论：**顶部重复已消除（1 次）**；但 header 下拉 16 个类别链接（`_shell_cat_links`，`CONSUMER_CATEGORIES` 前 16）与首页 8 个类别卡（`_home_cat_chips`，前 8）**内容重叠 8 个**，且 header 下拉占 8.9 KB/页、并进入 `boot.js`（全站每页一份字符串）。
- 品牌中文名：`logo-zh` 在 **5 处 CSS** 被 `display:none` —— `site/build.py` **5947 / 5994 / 7077 / 7206 / 7429** 行（含 `@media (min-width:1024px) and (max-width:1279px)` 与 `@media (min-width:1100px) and (max-width:1440px)`）。另有 `html:not([lang="zh"]) .logo-zh{display:none}`（**5967 行**）：根页用 `?lang=zh`/localStorage 切中文时 `html lang` 仍是 `en`，所以中文品牌名即使宽度够也不显示。1440 截图里页头只有 `Medicine Brand Cross-Reference`，没有中文副标题。
- `_shell_right` 的重复 Categories 已在 v0.11.10 删除（注释在 **11237–11240**），不要重复改。

### 1.3 E2 现状：搜索按钮只有箭头（仅 390）

- 按钮 HTML（`build_index_page`，**15381** 行）本身有文字和箭头两个 span：

```html
<button type="button" id="qgo" class="sb-go" aria-label="Search">
  <span class="sbg-t" data-i18n="home.submit">Search</span>
  <span class="sbg-ico" aria-hidden="true">→</span>
</button>
```

- CSS（**6029–6035** 行）：

```css
.sb-go .sbg-t{display:none}                 /* 默认（<768）隐藏文字 */
.sb-go .sbg-ico{font-size:17px}
@media (min-width:768px){.sb-go .sbg-t{display:inline}}  /* 桌面才显示文字 */
```

- 390 截图：搜索框右侧只有绿色箭头；1440 截图：绿色按钮「搜索 →」。**E2 只在移动端未满足**。

### 1.4 E3 现状：示例只有 2 个，V4 那条在

`tryrow`（`build_index_page`，**15391–15394** 行）实测 7 语均只有：

1. `a.try-cross`：V4 跨国链接（`?q=Tylenol+Extra+Strength&src=US&country=CN`），标签按界面语言本地化；
2. `button[data-q]`：包装文字示例 `Tylenol Extra Strength 960 mg/30 mL`；
3. 无第三个。

- `HOME_EXAMPLES`（**15136–15167**）的 `quick` 只有 1 条 dict（V4）；`pack` 1 条；**没有 `ja` 键**（`build_index_page` 用 `HOME_EXAMPLES.get(code) or HOME_EXAMPLES["en"]`，所以 ja 用英文示例）。
- `u1guide`「三步看懂」里另有 5 个示例按钮（`try1/try2/try3`），但该块可关闭、且在首屏下方；不能算 E3 的「首页三示例」。390 截图首屏只看到 V4 链接 + 包装按钮两个。

### 1.5 E4 现状：技术说明在哪几处

| 位置 | 现查 | 说明 |
|---|---|---|
| 首页可见正文 | **0 处** `42 MB` / `gzip` / `分片` | E4 已把静态说明搬走（`build_index_page` 注释 **15456–15458**，`#loadhint` 静态为空、`hidden`） |
| `/about.html` + 6 个语言副本 | **7 页 × 1 节**「How search loads / 搜索是怎么加载的」 | `about.loading`：en **2052** / es **2258** / zh **2433** / fr **1181** / zh-Hant **2712** / ko **3750** / ja **4442** 行；保留 |
| `home.hint_loading` | **7 语值**，6 语仍含「分片/中位 1.0 MB/gzip」 | en **241** / es **494** / zh **731** / zh-Hant **2601** / ko **4060** / ja **4751**；fr **951** 已是「Chargement de l'index…」 |
| `home.hint_idle` | **7 语值**，全部含 core 42 MB/gzip，但**从不显示** | `APP_JS` **9780** 行 `const HINT_IDLE = '';`；`#loadhint` 的 idle 态为空 → 元素隐藏。属死键，建议删除 |
| 客户端加载逻辑 | `HINT_LOADING = Tr('home.hint_loading')`（**9781** 行），首次搜索/聚焦时显示 | 失败路径已有 `error.index_failed` + `error.retry`（en **265/269**、es **518/522**、zh **751/754** 等），保留 |

> 结论：**E4 的「首页不出现 core 42 MB」已达成**；未达成的是「加载中提示也只说人话」——6/7 语仍在加载时显示技术数字。

### 1.6 E5 现状：一句话变化是否生效

| 版本 | en | zh | es | zh-Hant | fr | ko | ja |
|---|---|---|---|---|---|---|---|
| v0.16.0 | `New 7th interface language:` | `新增第 7 种界面语言：` | `Nuevo séptimo idioma de interfaz:` | `新增第 7 種介面語言：` | `Nouvelle 7e langue d'interface :` | `새로운 7번째 인터페이스 언어:` | `7 番目の表示言語として日本語を追加：` |
| v0.15.0 | `The coverage page now adds an "interfac…` | `覆盖页每行多一句「界面语言覆盖」：` | `La página de cobertura añade una frase…` | `涵蓋頁每列多一句「介面語言覆蓋」：` | `La page de couverture ajoute une mentio…` | `커버리지 페이지 각 행에 「인터페이스 언어 커버리지」 한 줄 추가:` | **`The coverage page now adds an "interfac…`（英文回落）** |
| v0.14.0 | `The home-page examples now demonstrate…` | `首页示例改成能演示「跨国查名」：` | `Los ejemplos de la portada ya demuestra…` | `首頁示例改成能示範「跨國查名」：` | `Les exemples de la page d'accueil montr…` | `홈 예시가 이제 「국가 간 이름 조회」를 실제로 보여 줍니다:` | **`The home-page examples now demonstrate…`（英文回落）** |

- 结论：**E5 机制已生效**（`rel.<version>` 动态键存在、7 语页面都有值），但**质量未达标**：
  1. `_release_oneliner`（**15295**）在 **15314** 行用 `[。！？.!?；;：:]` 切句，首条常用「**标题**：细节」格式 → 首页只剩标题+冒号；
  2. `_release_oneliner`（**15308**）缺该语言时 `or …get("en")` **回落英文**，`_home_recent`（**15338**）注释却写「不静默用英文顶替」——ja 的 v0.15/v0.14 因此出现英文；
  3. ja 的 v0.15.0 / v0.14.0 在 `data/release_notes_i18n.json` 缺条目；`build_whats_new`（**11643**）对 ja 缺译回退 en（**11679–11681**）。

### 1.7 首屏基线（改前）

见开头表：390 AFCR 0.93 / 条目 0.0 / chrome 0.14；1440 AFCR 1.00 / 条目 9.0 / chrome 0.07；两档无横向溢出、正文 16px。截图目录见 §3。

---

## 2. E1–E5 设计稿（每题：函数/行号 → 改什么 → 验收）

> 行号为 2026-11-19 09:00 读数（`site/build.py` 19,415 行）；后续再有 ja/其他合入会让行号整体位移，**以函数名/选择器为准**。

### 2.1 E1：合并重复导航 + 品牌中文名

**目标**：顶部「按类别」只 1 个入口；不再有 16 链下拉与 8 卡重复；品牌中文名在 1024–1440 可见且不挤成省略号。

**推荐方案 A（header 直接链）**

| 文件/函数（行号） | 改什么 |
|---|---|
| `site/build.py` `_shell_nav_html`（**11207**，片段 **11212–11215**） | 把 `<details class="sn-dd"><summary data-i18n="nav.categories">Categories</summary><div class="sn-panel">…16 链…</div></details>` 换成 `<a href="{prefix}atc.html" data-i18n="nav.categories">Categories</a>`；`_shell_cat_links`（**11177**）不再被调用（可保留函数，避免别的入口引用） |
| `site/build.py` `CSS`（**5947 / 5994 / 5967 / 7077 / 7206 / 7429**） | 删/改 `logo-zh` 的 `display:none` 与 `html:not([lang="zh"])` 条件：**≥1024 显示**、≤767 保持隐藏；1100–1440 允许 logo 两行/压缩 nav 间距，禁止 `text-overflow:ellipsis` 吃掉中文名 |
| `site/build.py` `_home_cat_chips`（**17621**） | **不动**：首页保留 8 个类别卡；它现在是首页唯一的类别浏览入口（header 直接链到 atc 全量页） |
| `site/build.py` `_shell_right`（**11233**） | 不动：右上角只有「⋯ / 全部类别」；v0.11.10 已删重复 Categories |

**方案 B（保留下拉但减半）**：`_shell_nav_html` 调 `_shell_cat_links(prefix, limit=8)`，只留前 8 个高频类别 + 「All categories & ATC」；header 下拉从 8.9 KB 降到约 4.6 KB。若 Lead 认为「顶部 Categories 必须保留下拉」，用 B；A 更符合「首页精简」。

**验收（数字/命令）**

```powershell
# 1) 7 语首页 header 计数：nav.categories 必须 1，cat/ 链接必须 0（A）
$env:PYTHONIOENCODING='utf-8'; $py='C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$code = @'
import pathlib,re
for rel in ['index.html','es/index.html','zh/index.html','zh-hant/index.html','fr/index.html','ko/index.html','ja/index.html']:
    t=pathlib.Path('.tmp/e1-e5-after/'+rel).read_text(encoding='utf-8')
    h=re.search(r'<header.*?</header>',t,re.S).group(0)
    print(rel, h.count('data-i18n="nav.categories"'), len(re.findall(r'href="(?:\.\./)?cat/',h)), len(h.encode()))
'@; $code | & $py -
# 2) 1280/1440 品牌中文名可见 + 不被省略
#    Chrome DevTools console:
#    getComputedStyle(document.querySelector('.logo-zh')).display !== 'none'
#    document.querySelector('.logo').scrollWidth <= document.querySelector('.logo').clientWidth
# 3) 首屏（改后）不退化
& $py deploy/first_screen_check.py --dist .tmp/e1-e5-after --pages home `
  --viewports 390x844,1440x900 --baseline .tmp/e1-e5-20261120/before-home.json
```

- 目标数字：header `nav.categories` **1**；header `cat/` 链接 **0**（A）或 **8**（B）；header 字节 ≤ **4.5 KB**（A）/ ≤ **4.8 KB**（B）；7 语首页 390/1440 无横向溢出；1440 nav 仍 1 行（`Range.getClientRects().length === 1`）；AFCR/chrome 不退化 >5%。
- 截图：`.tmp/e1-e5-20261120/after/{390x844,1440x900}.png`（中文界面）。

### 2.2 E2：搜索按钮显示文字

| 文件/函数（行号） | 改什么 |
|---|---|
| `site/build.py` `CSS`（**6029–6035**） | `.sb-go .sbg-t{display:inline}`（所有宽度）；`@media (max-width:479px){.sb-go .sbg-ico{display:none}}`（小屏只留文字，防止按钮过宽）；`.searchbar #q` 的 `padding-right` 从 56px 调到 **88–96px**（按按钮实测宽） |
| `site/build.py` `build_index_page`（**15381**） | **不改 HTML**：`sbg-t`/`sbg-ico`/`data-i18n="home.submit"` 已在；只让 CSS 显示文字 |
| `site/build.py` `_search_form`（**11249**） | 不动（次级页搜索按钮本来就有文字） |

**验收**

```powershell
# 390 下按钮必须有可读文字（不是只有箭头）
# Chrome DevTools console（页面切 zh / ja 各一次）：
# document.querySelector('#qgo').innerText.trim()  // 期望「搜索」/「検索」等
# document.querySelector('#qgo').getBoundingClientRect().width  // ≤ 96
# document.querySelector('#q').getBoundingClientRect().width    // ≥ 180
# document.documentElement.scrollWidth === innerWidth           // true
& $py deploy/first_screen_check.py --dist .tmp/e1-e5-after --pages home `
  --viewports 390x844,1440x900 --baseline .tmp/e1-e5-20261120/before-home.json
```

- 目标数字：390 `#qgo` 文字 = `T('home.submit')`（七语）；按钮宽 ≤96px；输入框可见宽 ≥180px；无横向溢出；1440 按钮仍「搜索 →」；首屏 AFCR/chrome 不退化 >5%。
- 截图：390 中文/日文两张（`.tmp/e1-e5-20261120/after/390x844-{zh,ja}.png`）。

### 2.3 E3：三个可点击示例（含 V4 那条）

| 文件/函数（行号） | 改什么 |
|---|---|
| `site/build.py` `HOME_EXAMPLES`（**15136–15167**） | 每个语言 `quick` 从 1 条 dict 改成 **2 条**：`{V4 dict}` + `"本地通用名"`；`pack` 保持 1 条。补 `"ja"` 键（现在没有）：`{"try1": …, "try2": …, "try3": …, "quick": [{"q": "Tylenol Extra Strength", "src": "US", "country": "CN"}, "アセトアミノフェン"], "pack": ["Tylenol Extra Strength 960 mg/30 mL"]}` |
| `site/build.py` `_sample_buttons`（**15170**） | **不改**：已支持 dict → `<a class="try-cross">`、str → `<button data-q>` |
| `site/build.py` `build_index_page`（**15391–15394**） | **不改模板**：`{{examples}}` + `{{pack_examples}}` 会自然变成 2 + 1 = **3** 个可点项；文案复用 `u1.try` / `home.try_pack` |

**七语示例建议（每个已用 `cli.py` 实测 ≥1 候选，见附录 B）**

| 语言 | V4 链接（保留） | 新增第 2 个（本地通用名/别名） | 包装文字（保留） |
|---|---|---|---|
| en | `Tylenol Extra Strength` + `src=US&country=CN` | `Paracetamol` | `Tylenol Extra Strength 960 mg/30 mL` |
| es | 同上 | `Paracetamol` | 同上 |
| zh | 同上 | `对乙酰氨基酚` | 同上 |
| zh-Hant | 同上 | `乙醯胺酚`（昵称命中）或 `泰諾` | 同上 |
| fr | 同上 | `Paracétamol` | 同上 |
| ko | 同上 | `Paracetamol` | 同上 |
| ja | 同上 | `アセトアミノフェン` | 同上 |

**验收**

```powershell
# 1) DOM：tryrow 正好 3 个可点项（1 a.try-cross + 2 button[data-q]）
# Chrome console:
# document.querySelectorAll('.tryrow a.try-cross').length === 1
# document.querySelectorAll('.tryrow button[data-q]').length === 2
# 2) 每个示例点击后 #out 有结果（或用 CLI 逐个验证，见附录 B）
& $py cli.py "Paracetamol" | Select-Object -First 3
& $py cli.py "对乙酰氨基酚" | Select-Object -First 3
& $py cli.py "Tylenol Extra Strength 960 mg/30 mL" | Select-Object -First 3
# 3) 7 语 tryrow 文案 + 首屏不退化
& $py deploy/first_screen_check.py --dist .tmp/e1-e5-after --pages home `
  --viewports 390x844,1440x900 --baseline .tmp/e1-e5-20261120/before-home.json
```

- 目标数字：3 个可点项；每个示例候选 ≥1（附录 B 现查：Paracetamol 60 keys、对乙酰氨基酚 32、乙醯胺酚 1、アセトアミノフェン 18、包装行 5）；7 语 `HOME_EXAMPLES` 都有条目；390 示例区不横向溢出；V4 链接 URL 可分享且点击一次即出候选。
- 首屏守卫可选增强：`deploy/first_screen_check.py` 的 `PAGES home.items` 加 `.tryrow a, .tryrow button`，改前 = 2 / 改后 = 3（不改也不阻塞，用 DOM 计数验收）。

### 2.4 E4：移走加载机制说明（首页只留「正在补全」与重试）

| 文件/函数（行号） | 改什么 |
|---|---|
| `site/build.py` `home.hint_loading`（en **241** / es **494** / zh **731** / fr **951** / zh-Hant **2601** / ko **4060** / ja **4751**） | 7 语统一改成**只说人话**：`Loading more results…` /「正在补全搜索结果…」/「正在補齊搜尋結果…」/「 Chargement des résultats…」等；**删掉**「分片 / 中位 1.0 MB / gzip / core」 |
| `site/build.py` `home.hint_idle`（en **238** / es **490** / zh **728** / fr **948** / zh-Hant **2598** / ko **4059** / ja **4750**） | **删除 7 键**（`APP_JS` **9780** 已 `HINT_IDLE=''`，从未显示；留着只会进 i18n 包和误用） |
| `site/build.py` `APP_JS`（**9777–9781**） | 逻辑不动：`HINT_IDLE=''`、`HINT_LOADING=Tr('home.hint_loading')`；只改字典值 |
| `site/build.py` `about.loading`（en **2052** / es **2258** / zh **2433** / fr **1181** / zh-Hant **2712** / ko **3750** / ja **4442**） | **保留**：技术说明（core 42 MB/gzip/分片）只留在 `/about` 的「How search loads」 |
| `site/build.py` `build_index_page`（**15456–15458**） | 不动：`#loadhint` 静态空、`hidden`；运行时只显示 loading/失败 |

**验收**

```powershell
# 1) 首页正文（7 语）不出现技术词
Select-String -Path .tmp/e1-e5-after\index.html,.tmp/e1-e5-after\*\index.html `
  -Pattern '42 MB|42 Mo|gzip|shard|分片|索引碎片' | Measure-Object   # 期望 0
# 2) /about 仍保留技术说明（7 页各 1 节）
Select-String -Path .tmp/e1-e5-after\about.html,.tmp/e1-e5-after\*\about.html `
  -Pattern '42 MB|42 Mo|gzip|shard|分片' | Measure-Object
# 3) i18n 删键后仍 FAIL 0
& $py deploy/i18n_check.py
```

- 目标数字：首页 7 语技术词 **0**；about 7 页各 **1** 节；`home.hint_idle` 键 **0**（7 语）；`home.hint_loading` 7 语无数字/技术词；加载中可见文案只「正在补全…」；失败时出现 `error.index_failed` + `error.retry`；`i18n_check` FAIL 0（键集在 7 语一致）。
- 截图：首次搜索加载态 390（`.tmp/e1-e5-20261120/after/390x844-loading.png`）；失败态可用 DevTools 断网/404 模拟。

### 2.5 E5：更新日志「一句话变化」

| 文件/函数（行号） | 改什么 |
|---|---|
| `site/build.py` `_release_oneliner`（**15295**，切句 **15314**） | 新规则：① 先取首条 `**…**` 标题（去 markdown、去尾部 `：:；;，,`），长度 3–48 直接用；② 否则取首个句末 `[。！？.!?]` 的句子（**不再在冒号/分号处切**）；③ 超 48 字在最后一个空格处截断 + `…`；④ 缺本地译文时返回 `""`（首页不回落英文） |
| `site/build.py` `_home_recent`（**15338**） | 不改结构；`liner` 为空时只渲染版本+日期（已有分支）；确保不再因英文回落显示外语 |
| `site/build.py` `_inject_release_liners`（**15321**） | 不改；仍给最近 3 版注入 `rel.<version>`（7 语） |
| `data/release_notes_i18n.json` | **补 ja 的 v0.15.0 / v0.14.0 首条**（首页用）；若 `/whats-new` 也要 ja 完整正文，补该版全部 bullet。补齐后 ja 不再走 `build_whats_new` 的 en 回落（**11679–11681**） |
| `site/build.py` `build_whats_new`（**11643**） | 不改逻辑；若选择「旧版不补译」，把 en 回落标注 `(EN)`（与 Q21 同口径），但 E5 目标是 7 语首页都有本地一句话，优先补 ja 数据 |

**验收**

```powershell
# 1) 最近 3 版 × 7 语：非空、不以冒号/分号结尾、≤48 字
$env:PYTHONIOENCODING='utf-8'; $py='C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$code = @'
import re,pathlib
for rel in ['index.html','es/index.html','zh/index.html','zh-hant/index.html','fr/index.html','ko/index.html','ja/index.html']:
    t=pathlib.Path('.tmp/e1-e5-after/'+rel).read_text(encoding='utf-8')
    for v in ['v0.16.0','v0.15.0','v0.14.0']:
        m=re.search(r'data-i18n="rel\.'+v+r'"[^>]*>([^<]*)<',t)
        s=m.group(1) if m else ''
        print(rel,v,repr(s), 'BAD' if (not s or re.search(r'[：:；;]$',s) or len(s)>48) else 'ok')
'@; $code | & $py -
# 2) 7 语首页不出现英文回落（ja 的 v0.15/v0.14 应为日文）
Select-String -Path .tmp/e1-e5-after\ja\index.html -Pattern 'The coverage page|The home-page examples' # 期望 0
# 3) 全量 i18n/发布口径
& $py deploy/i18n_check.py
```

- 目标数字：最近 3 版 × 7 语 = **21 个非空**、**0 个**以 `：:；;` 结尾、长度 ≤48；ja v0.15/v0.14 为日文（或明确 `(EN)`，但 E5 目标是本地语）；`rel.*` 首屏值 ≠ 当前「标题+冒号」；`/whats-new` 七语最新版仍完整。
- 截图：首页 390/1440 `最近更新` 区块各一张（`.tmp/e1-e5-20261120/after/home-{390,1440}-recent.png`）。

---

## 3. 截图基线目录与复跑命令

**本轮已采（改前）**：

```
.tmp/e1-e5-20261120/before/
  fs-home-390x844.png      # 390 中文：搜索按钮只有箭头、2 个示例
  fs-home-1440x900.png     # 1440 中文：搜索按钮「搜索 →」、顶部按类别 1 次
.tmp/e1-e5-20261120/before-home.json
```

**改后目录（实现时生成）**：

```
.tmp/e1-e5-20261120/after/
  390x844.png / 1440x900.png              # 根页（中文界面）
  390x844-ja.png / 1440x900-ja.png        # 日语
  home-390-recent.png / home-1440-recent.png
  home-390-loading.png
```

**7 语补齐截图**（`first_screen_check` 的 `PAGES.home` 只扫 `index.html`，语言副本用 Chrome headless 或 DevTools 手工截）：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
& $py serve.py 8765
# 另开终端；每个语言 × 2 视口：
foreach ($p in @('','es/','zh/','zh-hant/','fr/','ko/','ja/')) {
  foreach ($wh in @('390,844','1440,900')) {
    $name = ($p -replace '/','') + '-' + ($wh -replace ',','x')
    if ($p -eq '') { $name = 'home-' + ($wh -replace ',','x') }
    & $chrome --headless=new --disable-gpu --hide-scrollbars `
      --window-size=$wh --screenshot=".tmp/e1-e5-20261120/before-7lang/$name.png" `
      "http://127.0.0.1:8765/$p"
  }
}
```

- 目录约定：`before-7lang/`（改前 7 语）与 `after-7lang/`（改后 7 语），每语言 390/1440 两张；文件名 `<lang>-<w>x<h>.png`。不要求进 git；报告只引用 `.tmp` 路径。
- 若需要把关键 4 张留档进仓库：`docs/img/e1-e5-20261120/`（仅 `home-390-before/after`、`home-1440-before/after`），并按 `docs/` 现有图片命名 kebab-case。

---

## 4. 实施顺序、风险与红线

### 4.1 建议顺序（一次构建串 5 题）

1. E4 文案/删键（最小、无布局风险）→ `i18n_check`；
2. E5 `_release_oneliner` + ja 数据补译 → 首页 `rel.*` 检查；
3. E2 CSS（只影响按钮）→ 390 截图；
4. E3 `HOME_EXAMPLES` + ja → 3 示例 DOM/点击；
5. E1 nav/CSS（最大、影响全站 header）→ 最后跑首屏/7 语/链接；
6. 全量构建 `.tmp/e1-e5-after`（不要写 `site/dist`）→ `first_screen_check` before/after → 三语抽查 → `i18n_check` → `check_build_determinism`（若走发布）。

### 4.2 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| E1 删 header 下拉 | 用户少一个快速类别入口 | 保留首页 8 卡 + `/atc.html` 全量；方案 B 可只减到 8 链；改后 7 语截图确认入口可达 |
| E1 显示中文名 | 1100–1440 nav 拥挤/换行 | 允许 logo 两行、压缩 nav gap；验收「nav 1 行 + 无横向溢出」；390 仍隐藏 |
| E2 按钮变宽 | 390 输入框变窄/placeholder 截断 | 小屏隐藏箭头、按钮 ≤96px；输入框 ≥180px；`first_screen_check` 390 不退化 |
| E3 示例落空 | 用户点了 0 结果，比没有更糟 | 附录 B 每个示例实测 ≥1 候选；新增 ja 前用 `cli.py` 复测 |
| E4 删 `home.hint_idle` | i18n 键集不一致 | 7 语同时删，`i18n_check` FAIL 0；`HINT_IDLE=''` 无引用 |
| E5 切句规则 | 其他版本文案截断变短 | 单元测试/脚本扫最近 3 版 × 7 语；保留 48 字上限与 `…`；不改变 `whats-new` 全文 |
| E5 ja 补译 | 翻译工作量 | 至少补 v0.15/v0.14 首条（首页）；`whats-new` 全量可另批；缺译不得静默英文 |
| 旧 dist/正在构建 | 基线污染 | 本轮用 `.tmp/build_ja`；实现时先重建 `.tmp/e1-e5-before`；不要复用 `site/dist` |

### 4.3 红线（不碰）

- **商品名不是主键**：E3 只是把用户带到搜索框/候选集；页面仍显示「结果永远是候选集，不是唯一答案」（`home.candidate`，**15370**）。不得把示例包装成「标准答案」。
- **不手工碰撞**：E1/E2/E4/E5 不读/不改 `collision`、`dose_warning`、`product_name`、`nickname`；不做任何白名单/手工映射。
- **不给用药建议、不做剂量换算、不判断可互换**：首页现有 `home.notice` / `warn.no_advice` 一字不动；E3 示例只是搜索词，不是「替代药」；E5 只写版本变化，不写临床结论。
- **不写库/不重建**：本设计只改 `site/build.py` 的 CSS/常量/函数与 `data/release_notes_i18n.json`；不改 `data/drugs.db`、不跑 ingest、不动 `site/dist`、不发布。

---

## 5. 验收清单（实现工位照抄）

1. `& $py deploy/i18n_check.py` → **FAIL 0**（7 语键集一致；E4 删键后仍一致；E5 动态 `rel.*` 不参与静态键集）。
2. `.tmp/e1-e5-after` 全量构建到 `== done ==`；首页 7 语存在、`/ja/index.html` 非空。
3. E1：7 语 header `nav.categories` = 1；header cat 链接 0（A）/8（B）；`logo-zh` 在 1280/1440 可见且不省略；390/1440 无横向溢出。
4. E2：390 `#qgo` innerText = 本地「搜索」；按钮 ≤96px；输入框 ≥180px；1440 仍「搜索 →」。
5. E3：`.tryrow` = 1 个 V4 链接 + 2 个按钮；每个示例点击/CLI ≥1 候选；7 语 `HOME_EXAMPLES` 有值。
6. E4：7 语首页正文 `42 MB|gzip|shard|分片` = 0；`/about` 7 页各 1 节；`home.hint_idle` 键已删；加载提示只人话。
7. E5：最近 3 版 × 7 语 `rel.*` 非空、不以 `：:；;` 结尾、≤48 字；ja 无英文回落；`whats-new` 最新版七语完整。
8. 首屏：`first_screen_check --pages home --viewports 390x844,1440x900 --baseline .tmp/e1-e5-20261120/before-home.json` → 0 FAIL；AFCR 不低于基线 95%，390 条目不降（可因 E3 变为 3，更好），chrome 不升，字号/溢出全过。
9. 截图：§3 的 before/after 7 语目录齐；390/1440 首页 + 最近更新 + 加载态。
10. 报告：把 before/after 数字、截图路径、剩余缺口写进 `reports/2026-11-20-e1-e5-home-slim.md`（或本报告追加），不要只留在对话。

---

## 附录 A：E5 现查 vs 目标（v0.16.0 示例）

| 语言 | 现查（`rel.v0.16.0`） | 目标（首条 `**标题**`） | 长度 |
|---|---|---|---|
| en | `New 7th interface language:` | `New 7th interface language: Japanese` | 36 |
| es | `Nuevo séptimo idioma de interfaz:` | `Nuevo séptimo idioma de interfaz: japonés` | 41 |
| zh | `新增第 7 种界面语言：` | `新增第 7 种界面语言：日本語` | 15 |
| zh-Hant | `新增第 7 種介面語言：` | `新增第 7 種介面語言：日本語` | 15 |
| fr | `Nouvelle 7e langue d'interface :` | `Nouvelle 7e langue d'interface : le japonais` | 44 |
| ko | `새로운 7번째 인터페이스 언어:` | `새로운 7번째 인터페이스 언어: 일본어` | 21 |
| ja | `7 番目の表示言語として日本語を追加：` | `7 番目の表示言語として日本語を追加` | 18 |

> v0.15.0 / v0.14.0 的 en/es/fr 标题 66–96 字，按 48 字在最后一个空格截断 + `…`；zh/zh-Hant/ko 直接取标题；ja 需补译（`data/release_notes_i18n.json`）。

## 附录 B：E3 示例候选实测（`cli.py`，2026-11-20）

| 示例 | 查询 | 命中 keys | 结论 |
|---|---|---|---|
| V4 跨国 | `Tylenol Extra Strength` + `src=US&country=CN` | 60 | 出候选、URL 可分享 |
| en/es/fr/ko 通用名 | `Paracetamol` / `Paracétamol` | 60 | 出候选 |
| zh 中文名 | `对乙酰氨基酚` | 32 | 出候选 |
| zh-Hant 别名 | `乙醯胺酚` | 1（昵称命中） | 出候选；也可用 `泰諾`（3 keys） |
| ja 日文名 | `アセトアミノフェン` | 18 | 出候选 |
| 包装行 | `Tylenol Extra Strength 960 mg/30 mL` | 5 | 出候选（`960/30 mg/ml` 识别） |

> 反例（不要用）：`아세트아미노펜`（韩文通用名）现查 0 keys；`타이레놀` 0 keys。ko 示例用 `Paracetamol`。

## 附录 C：本轮证据/命令

```powershell
# 现状构建选择
Get-Process python | Select-Object Id,StartTime   # 09:01 另一工位在重建 site/dist
Get-Item .tmp/build_ja/index.html, .tmp/build_ja/ja/index.html

# 7 语首页计数（E1/E2/E4）
$env:PYTHONIOENCODING='utf-8'; $py='C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$code = @'
import pathlib,re
base=pathlib.Path('.tmp/build_ja')
for rel in ['index.html','es/index.html','zh/index.html','zh-hant/index.html','fr/index.html','ko/index.html','ja/index.html']:
    t=(base/rel).read_text(encoding='utf-8'); h=re.search(r'<header.*?</header>',t,re.S).group(0)
    print(rel, 'navcat', h.count('data-i18n="nav.categories"'),
          'panelcat', len(re.findall(r'href="(?:\.\./)?cat/',h)),
          'tryrow-cross', t.count('class="try-cross"'),
          '42MB', t.count('42 MB'))
'@; $code | & $py -

# E5 现状
$code = @'
import json,pathlib
d=json.loads(pathlib.Path('data/release_notes_i18n.json').read_text(encoding='utf-8'))
for v in ['v0.16.0','v0.15.0','v0.14.0']:
    for l in ['en','es','zh','zh-Hant','fr','ko','ja']:
        e=(d.get(v) or {}).get(l) or []
        print(v,l, e[0][:50] if e else 'MISSING')
'@; $code | & $py -
```

- 首屏命令与结果：见 §1.1 / 开头表；截图 `.tmp/e1-e5-20261120/before/`。
- `site/dist` 现状：本轮 09:01–09:04 期间另一 python 进程在重建（语言目录暂空、104,705 文件），**未作为基线**；实现工位等它结束后不要复用，另行 `.tmp/e1-e5-before` 重建。
- 不写库/不构建：本报告所有命令均为只读（`first_screen_check` 只写 `.tmp` 截图/JSON；`serve.py` 仅本地静态服务）。
