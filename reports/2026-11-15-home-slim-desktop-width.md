# v0.11.10 首页精简 E1–E5 ＋ 桌面内容宽度 2/3（E6/T34）

> 工位：site-ui　｜　任务：task-5　｜　日期：2026-11-15
> 改动：`site/build.py`（唯一源码；行尾 CRLF）＋ 本报告与 3 个探针脚本。未 commit / 未发布 / 未写 `site/dist`。

## 0. 结论（先看这 6 条）

1. **E6（用户「这是硬条件」）已达标**：桌面 ≥1024px 内容带 = 视口 2/3 居中。首屏守卫三档
   `band_ratio`：**1440 = 0.67 / 1920 = 0.67 / 2560 = 0.66**（目标 0.652–0.682），改前是 **1.00 / 1.00 / 1.00**（3 档越界）。
   三档 `overflow = 否`、`items` 9/12/12（≥0）、`chrome ≤ 0.13`、AFCR 0.96–1.00。
2. **根因不是 `.wrap` 的宽度变量，而是首页 HTML 里一个错位的 `</div>`**：`#ctrydetails`（高级筛选）
   本该用 `</details>` 收尾，写成了 `</div>` —— 浏览器把它当成 `.wrap` 的结束，于是「按类别 / 最近更新 /
   覆盖率提示」这些块落在 `.wrap` **外面**、横跨整个视口，band 量出来就是 100%。改对标签后，
   `.wrap` 的 2/3 宽度立刻生效（`band 0.67`）。
3. **E1** 顶部重复的「按类别」入口从 2 个减到 **1 个**（删掉右上角那份，桌面导航保留；移动端「⋯」仍可进
   「全部类别」）；品牌中文名不再被省略号截断（≥1100px 的 `text-overflow:ellipsis` 改成允许换行 + `title`）。
4. **E2** 搜索按钮显示文字：**Search / Buscar / 搜索 / 搜尋 / Rechercher**（服务端输出英文兜底，
   `i18n.js` 按界面语言替换；zh 页实测按钮文字 = 「搜索」）。手机端仍只留箭头（省宽度）。
5. **E3** 首页新增一行**可点击示例**：`泰诺` / `Tylenol Extra Strength` / `960 mg/30 mL`（各语言本地化），
   点击即填入搜索框并搜索。
6. **E4/E5** 首页底部那段「分片 / core 42 MB / gzip」技术说明**移到 `/about.html` 的「How search loads」新节**
   （四语）；首页 `#loadhint` 只剩脚本写入的加载/失败状态与重试。最近更新每个版本号后补**一句变化**
   （取 `data/release_notes_i18n.json` 该版第一条首句，~40 字截断，按界面语言服务端渲染）。

## 1. E6：三档「内容宽 ÷ 视口宽」实测（硬门槛）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py reports/2026-11-15-home-slim-render.py .tmp\v01110 acetaminophen amlodipine   # 渲染证据产物
& $py deploy/first_screen_check.py --dist .tmp/v01110 --pages home,drug `
      --viewports 1440x900,1920x1080,2560x1440 --json .tmp/v01110-final.json
# 改前对照：& $py deploy/first_screen_check.py --dist site/dist --pages home,drug --viewports 1440x900,1920x1080,2560x1440
```

| 视口 | band_ratio 改前（site/dist v0.11.9） | band_ratio 改后 | 判定 |
|---|---|---|---|
| 1440×900（home） | **1.00** | **0.67** | ✅ 0.652–0.682 |
| 1920×1080（home） | **1.00** | **0.67** | ✅ |
| 2560×1440（home） | **1.00** | **0.66** | ✅ |
| 1440×900（drug） | 0.67 | 0.67 | ✅ |
| 1920×1080（drug） | 0.67 | 0.67 | ✅ |
| 2560×1440（drug） | 0.66 | 0.66 | ✅ |

- 6 次扫描 **0 组不达标 / 0 项未达**；`溢出 = 否`（三档都是 0 横向滚动）。
- 窄栏下宽表格横滑：结果表 / 矩阵 / 成分明细本来就在 `.tablewrap{overflow-x:auto}` 里，
  实测三档 `scrollWidth == clientWidth`（无横向溢出）。
- 1024–1279 这一档（首屏守卫不扫，但真实用户有）：窄栏放不下「logo + 5 项导航 + 语言」，
  额外加了 `@media (min-width:1024px) and (max-width:1279px)` 让页头换行、隐藏 logo 中文副标题、
  下拉面板 `max-width:calc(100vw - 24px)`；实测 1030 宽窗口 **hscroll = 0**、`wrap=0.667`。

CSS（`site/build.py` 的 `CSS` 常量）：

```css
.wrap{width:var(--band-w);max-width:1680px;margin-inline:auto;padding:0 var(--wrap-pad)}
@media (min-width:1024px){:root{--band-w:min(66.67vw,1680px)}}
@media (max-width:1023px){:root{--band-w:100%}}
```

## 2. E1–E5 before / after（DOM）

```powershell
& $py reports/2026-11-15-home-slim-dom.py     # ①首页 ②成分页块 ③About ④四语首页
```

| 项 | before（site/dist v0.11.9） | after（本次 `.tmp/v01110`） |
|---|---|---|
| E1「按类别」入口 | **2** 个（导航 + 右上角 `qcat`） | **1** 个 |
| E1 品牌中文名 | ≥1100px 被 `ellipsis` 截断 | 允许换行 + `title`（不再截断） |
| E2 搜索按钮 | `<button id="qgo" class="sb-go">→</button>` | `<span class="sbg-t" data-i18n="home.submit">Search</span><span class="sbg-ico">→</span>` |
| E3 可点击示例 | **无** | `tryrow`：3 个 `data-q` 按钮（泰诺 / Tylenol Extra Strength / 960 mg/30 mL） |
| E4 `#loadhint` | `<p class="sub" id="loadhint" data-i18n="home.hint_idle">` + 技术长段 | `<p class="sub" id="loadhint" hidden>`（只由脚本写状态/重试） |
| E4 技术说明 | 只在首页 | `/about.html` 新增 `<div data-i18n-html="about.loading"><h2>How search loads</h2>…` |
| E5 更新日志 | 3 个「版本号 + 日期」 | 版本号 + 日期 + **一句变化**（`<span class="upd-liner">…`） |

E5 实测（首页内联）：`Combination pages no longer list doses…` / `"Different release" is no longer conclu…` /
`You can now say which candidate is your…`；zh 页面版：`复方页的剂量不再是一串斜杠：`。

首页 DOM 片段（after）：

```html
<button type="button" id="qgo" class="sb-go" data-i18n-aria="home.submit" aria-label="Search">
  <span class="sbg-t" data-i18n="home.submit">Search</span><span class="sbg-ico" aria-hidden="true">→</span></button>
...
<div class="tryrow"><span class="try-lbl" data-i18n="u1.try">Try:</span>
  <button type="button" data-q="Tylenol Extra Strength">Tylenol Extra Strength</button>
  <button type="button" data-q="Metformin">Metformin</button>
  <button type="button" data-q="960 mg/30 mL">960 mg/30 mL</button></div>
...
<section class="homeupd"><h2 id="updtitle" data-i18n="home.recent">Recently updated</h2>
  <ul class="updlist"><li><a href="whats-new.html"><b>v0.11.9</b><span class="upd-date">2026-11-15</span>
    <span class="upd-liner">Combination pages no longer list doses…</span></a></li>…
<p class="sub" id="loadhint" hidden></p>
```

## 3. 四语文案（新增/改动）

| key | en | es | zh | zh-Hant | fr |
|---|---|---|---|---|---|
| `home.submit`（可见文字复用现有 key） | Search | Buscar | 搜索 | 搜尋 | Rechercher |
| `about.loading`（新，E4） | How search loads … | Cómo se carga la búsqueda … | 搜索是怎么加载的 … | 搜尋是怎麼載入的 … | Chargement de la recherche … |
| `u1.try`（复用，E3 标签） | Try: | Prueba: | 试试： | 試試： | Essayer : |
| 示例词（`HOME_EXAMPLES[*]["quick"]`） | Tylenol Extra Strength / Metformin / 960 mg/30 mL | Paracetamol 500mg / Metformina / 960 mg/30 mL | 泰诺 / Tylenol Extra Strength / 960 mg/30 mL | 泰諾 / … | 同 en |

`home.hint_idle` 键**保留**（首页不再渲染；About 的 `about.loading` 是新键，四语齐）。
`deploy/i18n_check.py`：**FAIL 0 / WARN 2 / INFO 24**，五语各 **631 键**。

## 4. 自验

| 检查 | 命令 | 结果 |
|---|---|---|
| 语法 | `& $py -m py_compile site/build.py` | exit 0 |
| 四语 | `& $py deploy/i18n_check.py` | FAIL 0（631 键 ×5） |
| lib / etl | `& $py -m unittest discover -s lib -t lib` / `-s etl -t etl` | 61 OK / 55 OK |
| 快速全局 | `& $py deploy/ci_checks.py --fast` | PASS 8 / FAIL 0 / SKIP 4 |
| 首屏守卫（E6 + 硬指标） | 见 §1 | 6/6 组合 **ok**，band 0.66–0.67、溢出 0 |
| 真浏览器（zh 首页 @1030×…） | MCP 浏览器实测 | 按钮「搜索」、示例「泰诺…」、`wrap=0.667`、`hscroll=0` |

## 5. 缺口 / 交给 Lead

1. **全量构建 + `first_screen_check` 全页型**由 Lead 跑（本工位只渲染证据页到 `.tmp`）。全量产物里
   `home` / `drug` 之外的页型（results / name / atc / coverage）也吃 `.wrap` 的 2/3 宽度，
   预期 `band_ratio` 同为 0.66–0.67；若有页型因固定宽度容器越界，需要按同一口径补 CSS。
2. `first_screen_check.py` 的注释仍写「≥1280 视口内容带 66.7%，<1280 占满」，与本次新口径
   （≥1024 2/3）不一致 —— 那是 `deploy/` 文件，不在本工位写权限，建议 Lead 同步注释/阈值说明。
3. 首页内联的 i18n 字典里仍含 `home.hint_idle` 这段技术文案（键未删；页面不渲染它）。若要连键一起删，
   需同步 `data/i18n_zh_hant.json`（`data/` 不在本工位写权限）。
4. E5 的「一句话变化」按界面语言取译文；某语言缺该版译文时只显示版本号 + 日期（不拿英文顶替）。
