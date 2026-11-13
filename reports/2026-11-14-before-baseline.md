# 改前基线：v0.11.5 产物 6 类页面（T10 / T12 前后对照用）

> 工位：atc4-ui ｜ 取数时间：2026-11-14（北京谷段）｜ 任务：task-4
> 状态：**只读取证**，未改 `site/build.py`、未构建、未写 `site/dist`、未写库、未 commit、未发布。
> 用途：T10（规格/剂型/复方分组）与 T12（品牌页/成分页名称与提示一致）改完后，用**同一口径**再测一遍，与本文件逐项对比。

## 0. 结论先行

1. **基线锚定成功**：本文所有数字来自 `site/dist`（mtime `2026-11-12 10:45:13`，页脚 `v0.11.5 · 2026-11-13`，`checksums.txt` 在位），**早于本轮任何构建**；关键产物已记 sha256（§1.3），改后可直接判定「换没换产物」。
2. **官方首屏守卫在本机不可用**：`deploy/first_screen_check.py` 实测抛 `RuntimeError: Chrome 未就绪（--remote-debugging-port 没起来）`（§1.1），故用 **MCP Playwright** 做替身取证；12 张截图 + 12 组页面度量已落盘，口径差异写在 §1.2。
3. **规模数字（现查）**：`site/dist` **125,510 文件 / 974,169,676 B（929.0 MiB）**、HTML **125,290** 页、0 字节文件 0；`data/idx/core.json` **raw 45,243,092 B（43.15 MiB）/ gzip 10,164,238 B（9.69 MiB）**；`sitemap.xml` **66,300** 条 URL。
4. **一屏现状（12 项测点全部 0 横向溢出）**：桌面端首屏条目 首页 12 / 结果页 4.5 / 成分页 9 / 品牌页 3 / 覆盖页 6.5 / 分类页 10.5；手机端依次 8.5 / 1 / 5.5 / 3 / 1.5 / 1.5。最小字号 13–14 px，`<12px` 硬违规 0。
5. **T10/T12 靶点已文字化**（§3）：`?q=Tylenol` 在 v0.11.5 **是扁平表、没有组头**，串在剂量单元格 —— `500 mg / 960 mg <span class="form-tag">片剂</span>`（`/30 mL` 丢失）；品牌页 `无中文名` 徽标贴在**成分** `Acetaminophen` 上、H2 为「同一品牌在其他市场的写法」、警示含内部术语「属严重碰撞」；成分页「325 mg 片剂」组内**单方与复方混排**（DB 口径：acetaminophen 325 mg 片剂共 1,267 条 = 单方 214 + 复方 1,053）。

---

## 1. 方法、口径与限制

### 1.1 工具链（为什么用替身）

| 项 | 内容 |
|---|---|
| 官方守卫 | `& $py deploy/first_screen_check.py --base-url http://127.0.0.1:8000 --viewports 1440x900 --pages home` |
| 实测结果 | **失败**：`File "deploy/ui_surface_check.py", line 434, in launch_chrome → RuntimeError: Chrome 未就绪（--remote-debugging-port 没起来）`，退出码 1（本机沙箱不给 Chrome 开 CDP 端口） |
| 替身方案 | **MCP 浏览器（Playwright）**：`browser_run_code_unsafe` 驱动本机浏览器（UA `Chrome/157.0.0.0` + `Edg/157.0.0.0`，DPR 1，1440×900 屏），`browser_evaluate` 取 DOM/度量，`page.screenshot` 出图 |
| 被测量对象 | 本地预览 `& $py serve.py 8000` → `http://127.0.0.1:8000/`（`serve.py` 自带 `Cache-Control: no-store`，产物不会串缓存） |
| 可复跑脚本 | `reports/2026-11-14-before-baseline.measure.js`（同一脚本改后直接再跑） |

### 1.2 与官方守卫的口径对照（差异照实记）

| 指标 | 官方 `first_screen_check.py` | 本次替身 | 影响 |
|---|---|---|---|
| 首屏可见条目数 | 主内容区条目矩形 ∩ 首屏，≥90% 记 1、≥25% 记 0.5；默认多选择器**求和**，仅成分页用 first-match | **同算法**（同样的 0.9/0.25 折算、同样的选择器表；除成分页外求和） | 可直接前后对比；与官方 JSON 比会因为 0 条/0.5 条边界抖动 |
| 横向溢出 | `documentElement.scrollWidth > innerWidth+1`，并数越界元素（排除横向滚动容器内部） | **同算法** | 同一 |
| chrome 占比 / AFCR(v2) / 带宽比 | 网格采样（步长与 chrome 选择器表在源码里） | **同算法 + 同选择器表 + 网格步长 16 px** | 同一量级；chrome 选择器若在 T10/T12 里改类名，需同步改脚本 |
| 字号 | body ≥16 / aux ≥13 / 硬线 <12，按 AUX 白名单分档 | **精简**：只统计首屏主内容区可见文字节点的最小字号与 `<12/<14` 计数，不分 body/aux | 只能看「有没有小于 12 px」，不能替代官方分档结论 |
| 悬浮 / 遮挡 | 有 | **本次未测**（只取用户要求的条目数/溢出/体积） | 改后若要跑官方 7 项，仍需真 Chrome |

**其它限制**：

- 结果页/品牌页/成分页是**客户端渲染**：脚本 `waitForSelector` 就绪后再等 700–800 ms 取样；截图时 `?q=Tylenol` 页顶部仍显示「正在加载完整索引…」（不影响表格已渲染部分，但改后截图对比要看同一状态）。
- 本地预览 `serve.py` **不做 gzip**：`transferSize` = 原始字节（含 ~300 B 响应头）。所以「gzip 体积」是**对落盘文件用 zlib level 9 实测压缩**得到的（§2.3），不是网络实测。
- 首屏下载量只统计到**页面就绪后 1.5 s**，更晚的懒加载（如完整索引）不在内。
- 手机档用 390×844（与官方手机档同尺寸），DPR 1（未模拟真机 DPR 2/3）。
- 未做 Lighthouse / 4G 实测（triarge §4 已注明本轮不做）。

### 1.3 基线锚定（改后用来判定「产物换没换」）

| 锚点 | 值 |
|---|---|
| `site/dist` mtime | 2026-11-12 10:45:13 |
| `index.html` / `data/idx/core.json` mtime | 2026-11-12 10:44:36 / 10:42:39 |
| 页脚版本串 | `本站只做标识对应… v0.11.5 · 2026-11-13` |
| `index.html` | sha256 `d23cb742944d1049` · 144,095 B |
| `drug/acetaminophen.html` | sha256 `3318a0258db3905c` · 160,024 B |
| `name/tylenol-extra-strength.html` | sha256 `0dcc4a2aa53d9f5f` · 3,412 B |
| `coverage.html` | sha256 `85db4570fbd45807` · 24,679 B |
| `cat/analgesics.html` | sha256 `18fa0ef6b2b253be` · 173,738 B |
| `data/idx/core.json` | sha256 `fd3d051e87696d1c` · 45,243,092 B |
| `sitemap.xml` | sha256 `428574dcf4622f38` · 7,487,207 B |

> 注：取证当时 `site/build.py` **在工作区已是修改态**（T10/T12 实现方在写），但 `site/dist` 仍是 v0.11.5 旧产物、且无 `.tmp` 构建残留 → 本基线描述的是**旧产物**，不是旧源码。

---

## 2. 现查数字

### 2.1 站点规模（`dist` 与索引）

```powershell
# 文件数 / 总字节 / HTML 页数 / 0 字节文件
$f = Get-ChildItem site/dist -Recurse -File
$f.Count; ($f | Measure-Object Length -Sum).Sum; ($f | ? {$_.Extension -eq '.html'}).Count
# core.json raw / gzip（zlib level 9）
# sitemap: <loc> 计数
```

| 指标 | 值 |
|---|---|
| `site/dist` 文件数 | **125,510** |
| `site/dist` 总字节 | **974,169,676**（929.0 MiB） |
| HTML 页数 | **125,290** |
| 0 字节文件 | **0** |
| `data/idx/core.json` raw | **45,243,092 B**（43.15 MiB） |
| `data/idx/core.json` gzip(9) | **10,164,238 B**（9.69 MiB）※护栏 2.5–12 MB，在区间内 |
| `sitemap.xml` URL 数 | **66,300**（去重后同值） |
| `sitemap.xml` 字节 | 7,487,207 |

### 2.2 页面度量（12 组，替身口径见 §1.2）

| 页型 | 路径 | 视口 | 首屏条目 | 横向溢出 | 越界元素 | chrome | AFCR | 带宽比 | 文档高 | 最小字号 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 首页 | `/index.html` | 1440×900 | **12** | 0 | 0 | 0.093 | 0.960 | 0.667 | 1,096 | 13 |
| 首页 | `/index.html` | 390×844 | **8.5** | 0 | 0 | 0.143 | 0.898 | 0.961 | 1,596 | 13 |
| 结果页 | `/index.html?q=Tylenol` | 1440×900 | **4.5** | 0 | 0 | 0.093 | 0.960 | 0.667 | 2,197 | 13 |
| 结果页 | 同上 | 390×844 | **1** | 0 | 0 | 0.177 | 0.860 | 0.961 | 3,807 | 13 |
| 成分页 | `/drug/acetaminophen.html` | 1440×900 | **9** | 0 | 0 | 0.141 | 0.997 | 0.667 | 8,356 | 13 |
| 成分页 | 同上 | 390×844 | **5.5** | 0 | 0 | 0.197 | 0.903 | 0.961 | 11,751 | 13 |
| 品牌页 | `/name/tylenol-extra-strength.html` | 1440×900 | **3** | 0 | 0 | 0.265 | 0.931 | 0.667 | 900 | 13 |
| 品牌页 | 同上 | 390×844 | **3** | 0 | 0 | 0.460 | 0.803 | 0.961 | 867 | 13 |
| 覆盖页 | `/coverage.html` | 1440×900 | **6.5** | 0 | 0 | 0.138 | 0.887 | 0.667 | 1,443 | 14 |
| 覆盖页 | 同上 | 390×844 | **1.5** | 0 | 0 | 0.263 | 0.764 | 0.961 | 4,667 | 14 |
| 分类页（退烧止痛） | `/cat/analgesics.html` | 1440×900 | **10.5** | 0 | 0 | 0.070 | 0.996 | 0.667 | 3,408 | 13 |
| 分类页（退烧止痛） | 同上 | 390×844 | **1.5** | 0 | 0 | 0.143 | 0.898 | 0.961 | 9,429 | 13 |

- 条目选择器与求和方式（与官方 `PAGES` 一致）：首页 `.catgrid a` 9 + `.updlist li` 3 = 12；结果页 `#reswrap tbody tr.br`（扁平表无 `tr.grp`）；成分页 `.mkrow`（first-match，避免矩阵视图重复计数）；品牌页 `main .card` 1 + `main ul.sub li` 2 = 3；覆盖页 `#covtable tbody tr`；分类页 `ul.atcmembers li`（2 个列表共 187 项）。
- `<12 px` 文字节点：**全页 0**；`<14 px` 占比最高的两处是成分页 1440（65/183）与品牌页 390（3/26），属辅助字号区间。
- `scrollWidth` 1440 档恒为 1425、390 档恒为 375（差值 = 经典滚动条 15 px）→ **无横向溢出**（判定用 `scrollWidth > innerWidth+1`）。

### 2.3 首屏体积（文档 raw / gzip + 就绪后 1.5 s 实际下载）

| 页面 | 文档 raw | 文档 gzip(9) | 文档实测传输 | fetch 字节 | script 字节 | 首屏合计 |
|---|---:|---:|---:|---:|---:|---:|
| 首页 | 144,095 | **38,423** | 144,395 | 209,716 | 244,379 | 598,490 |
| 结果页 `?q=Tylenol` | 144,095 | **38,423** | 144,395 | 2,400,922 | 244,379 | **2,789,696** |
| 成分页 | 160,024 | **19,119** | 160,324 | 186,221 | 103,253 | 449,798 |
| 品牌页 | 3,412 | **1,489** | 3,712 | 186,221 | 103,253 | 293,186 |
| 覆盖页 | 24,679 | **5,157** | 24,979 | 186,221 | 103,253 | 314,453 |
| 分类页 | 173,738 | **12,397** | 174,038 | 186,221 | 103,253 | 463,512 |

- 结果页最贵的是按名分片：`shard-t-3.json` 997,847 B + `aliases.json` 852,140 B + `categories.json` 300,565 B（本地无压缩）。
- 6 个页面**首屏都不拉 `core.json`**（43 MiB）——完整索引是后置懒加载（截图里那句「正在加载完整索引…」就是它）。
- 线上 R2 有压缩，文档实际传输会接近上表的 gzip 列；本地 `serve.py` 不压缩，故 `传输 ≈ raw + 头`。

---

## 3. 文字化现状（T10 / T12 的直接靶点）

### 3.1 结果页 `/?q=Tylenol`：**没有「组头」，靶点串在剂量单元格**

- 表格：`#reswrap table` 的 class = `res rows`（**扁平表**），表头 4 列 = `剂量 / 品牌 / 市场 / 详情`，`tbody tr.br` **20 行**，`tbody tr.grp` **0 行** → triage §1.1 说的「组头」在 v0.11.5 的这页**并不存在**，实际是行内汇总。
- 目标行原文（`tr.br` 整行）：`500 mg / 960 mg 片剂  Tylenol Extra Strength  CA US  详情`
- `.c-dose` 单元格 innerHTML（原文照抄）：
  ```html
  500 mg / 960 mg <span class="form-tag">片剂</span>
  ```
  → **`960 mg` 后面没有 `/30 mL`**；剂型标签只取了一个 `片剂`，而该组含液体记录（§3.5 有 DB 证据）。`·` 分隔符只在有释放方式时才出现（`form · release`），此处为空格。
- 首 4 行（按页面顺序）：
  1. `500 mg 片剂 · TYLENOL FILM COATED TABLETS 500MG · SG`
  2. `500 mg / 960 mg 片剂 · Tylenol Extra Strength · CA US` ← 靶点
  3. `5 mg / 200 mg / 325 mg 片剂 · TYLENOL SINUS SEVERE〔复方〕· US`
  4. `1,000 mg / 25 mg / 50 mg / 500 mg 片剂 · Tylenol PM Extra Strength〔同名不同药〕〔复方〕· US`
- 页面顶部保留「共 86 条候选」「结果永远是候选集，不是唯一答案」——底线 1 在页面上是成立的。

### 3.2 品牌页 `/name/tylenol-extra-strength.html`：标题 / 徽标 / 警示原文

页面全文正文只有 **237 字**（无表格、无产品清单）：

```
Tylenol Extra Strength
写法: Tylenol Extra Strength、TYLENOL EXTRA STRENGTH · 覆盖: CA、US
Acetaminophen〔无中文名〕
国家/地区: CA、US · 剂型: 胶囊、液体、粉末、片剂 · 规格: 500 mg、960 mg
同一品牌在其他市场的写法
强生同一商标；美国是单方对乙酰氨基酚，中国「泰诺」是复方感冒药，中国单方叫「泰诺林」。三家不同成分，属严重碰撞。
泰诺 泰诺
泰诺林 泰诺林
```

| 项 | 现状（原文） | 对应 triage |
|---|---|---|
| H1 | `Tylenol Extra Strength` | — |
| 摘要行 | `写法: … · 覆盖: CA、US` | — |
| 主体卡 | `剂型: 胶囊、液体、粉末、片剂 · 规格: 500 mg、960 mg` | §1.2（`960 mg` 无 `/30 mL`；四种剂型压在一行） |
| H2 #1 | `Acetaminophen` + 徽标「无中文名」 | §1.6（成分有 `inn_zh` 对乙酰氨基酚，却贴「名称无中文名」） |
| `name.no_zh` 徽标 DOM | `<a href="../drug/acetaminophen.html">Acetaminophen<span class="st-badge st-unknown nolang-badge">无中文名</span></a>` → **挂在成分链接内部** | §1.6 同上 |
| H2 #2 | `同一品牌在其他市场的写法` | §1.6（把品牌关系读成翻译关系） |
| 警示原文 | `强生同一商标；美国是单方对乙酰氨基酚，中国「泰诺」是复方感冒药，中国单方叫「泰诺林」。三家不同成分，属严重碰撞。` | §1.6（`属严重碰撞` = 内部 collision 分级术语） |
| 中文名列表 | `<li><a href="泰诺.html">泰诺</a><span class="tag">泰诺</span></li>`（另一条同构：泰诺林） → **同一名字连排两次** | §1.6（「泰诺泰诺林重复」） |

### 3.3 成分页 `/drug/acetaminophen.html`：「325 mg 片剂」组单/复方混排

- 页面结构：`11 个市场 · 12,875 条记录`；`.mkblock` **11 个**（CN/US/TW/AU/HK/GB/CA/ES/FR/SG/MX），`.mkrow` **110 行**（HK 为 `693 条记录 · 0 个规格`）；剂型 chips：`液体 110 / 片剂 55 / 粉末 51 / 栓剂 23 / 泡腾剂 18 / 胶囊 17 / 注射剂 17 / 其他剂型 7 / 外用 4`。
- 页面警示原文：`同一成分在不同国家可能用完全不同的商品名；同名也可能指向不同成分。下方按国家列出，不代表可以互换。`
- **同属「325 mg 片剂」组的行共 9 条**（跨市场），行本身只有 `data-mk / data-spec / data-form`，没有单/复方标记：

| # | 市场 | 行文案（截断） | 实际成分（DB） | 判定 |
|---|---|---|---|---|
| 1 | CN | `325 mg 片剂 利乐对乙酰氨基酚 +11 也在 US·TW·AU +5` | Acetaminophen 325 mg | 单方 |
| 2 | US | `325 mg 片剂 ACETAMINOPHEN +371 也在 CN·TW·AU +5` | `US-0615-8609` Acetaminophen 325 mg | **单方** |
| 3 | GB | `325 mg 片剂 Tramacet 37.5mg/325mg tablets +14 …` | `GB-23439711000001104`（同注册名另有 `GB-38171011000001102`、`GB-7381611000001100`）Tramadol 37.5 mg + Acetaminophen 325 mg | **复方** |
| 4 | AU | `325 mg 片剂 TRAMADOL/PARACETAMOL 37.5/325 APOTEX … film-coated tablet blister pack +1 … 状态未知` | `AU-ARTG-280698` Acetaminophen 325 mg + Tramadol HCl 37.5 mg | **复方** |

→ 同一「325 mg 片剂」标题下，第 2 行是单方、第 3/4 行是复方，**页面没有任何区分、也不列复方的全部成分与各自含量**（只有长名里偶然带 `37.5mg/325mg`）。

### 3.4 其余 3 页（一句话现状）

- `coverage.html`：表头 = `市场 / 产品数 / 成分已映射 / 规格覆盖 / 最后同步 / 数据截止 / 已知缺口`，12 行（AU、CA、CN…）→ triage §2 要改的「产品数 → 记录数」指的就是第 2 列表头。
- `cat/analgesics.html`（退烧止痛）：H1 `退烧止痛`，两个 `ul.atcmembers` 列表 **80 + 107 = 187 项**，首个成分 `布洛芬 M01AE01 盐型：Ibuprofen Sodium Dihydrate 在售 US GB CA AU SG · 另有 8 个`；页内无搜索/筛选（对应 T13）。
- 首页：H1 `查一个药名，看它在各国是什么`；`.catgrid a` 9 个类别入口（降压药 / 抗生素 / 降糖药 / 减肥药 / 感冒咳嗽药 / 退烧止痛 / 抗过敏药 / 胃药 / 全部类别 →），`.updlist li` 3 条更新记录（`v0.11.5 2026-11-13`、`v0.11.4 2026-11-12`、`v0.11.3 2026-11-12`）；覆盖提示：`查不到不代表这个药不存在。当前覆盖（国家和地区）：AU 44,794, CA 43,847, CN 145,051, ES 25,395, EU 2,095, FR 15,799, GB 61,051, HK 13,935, MX 10,878, SG 5,511, TW 16,457, US 110,179.`

### 3.5 DB 只读现查（`file:data/drugs.db?mode=ro`，支撑 §3.1/§3.3）

| 查询 | 结果 |
|---|---|
| `name_key.norm='tylenol extra strength'` 的 26 个产品按 `form_base` | **tablet 23 / powder 1 / liquid 1 / capsule 1** |
| 同组内 `strength_value=960` | **1 条**：`US-50580-187`（liquid，960 mg / 30 mL） |
| 全库 `per_volume_value=30` | **1,722 行** |
| acetaminophen + 325 mg + `form_base='tablet'` 的产品 | **1,267 条 = 单方 214 + 复方 1,053** |

→ 这两条正好解释「一行写 `片剂`、实际组里有液体」与「`325 mg 片剂`组里单复方混排」：**分组键没把剂型/体积/成分集合纳入组头语义**。

---

## 4. 截图（12 张，1440×900 与 390×844 各一套）

方法：MCP Playwright `page.screenshot({fullPage:false})`（只截首屏视口），浏览器渲染落盘后再拷入 `docs/img/`。文件均可用任意看图软件打开，字节数如下（可核对是否被替换）。

| 页 | 桌面 1440 | 手机 390 |
|---|---|---|
| 首页 | [v0115-before-home-1440.png](img/v0115-before-home-1440.png) (91,708 B) | [v0115-before-home-390.png](img/v0115-before-home-390.png) (54,919 B) |
| 结果页 `?q=Tylenol` | [v0115-before-results-tylenol-1440.png](img/v0115-before-results-tylenol-1440.png) (98,812 B) | [v0115-before-results-tylenol-390.png](img/v0115-before-results-tylenol-390.png) (45,567 B) |
| 成分页 `/drug/acetaminophen.html` | [v0115-before-drug-acetaminophen-1440.png](img/v0115-before-drug-acetaminophen-1440.png) (93,676 B) | [v0115-before-drug-acetaminophen-390.png](img/v0115-before-drug-acetaminophen-390.png) (54,102 B) |
| 品牌页 `/name/tylenol-extra-strength.html` | [v0115-before-name-tylenol-extra-strength-1440.png](img/v0115-before-name-tylenol-extra-strength-1440.png) (53,565 B) | [v0115-before-name-tylenol-extra-strength-390.png](img/v0115-before-name-tylenol-extra-strength-390.png) (44,666 B) |
| 覆盖页 `/coverage.html` | [v0115-before-coverage-1440.png](img/v0115-before-coverage-1440.png) (101,917 B) | [v0115-before-coverage-390.png](img/v0115-before-coverage-390.png) (45,932 B) |
| 分类页 `/cat/analgesics.html` | [v0115-before-cat-analgesics-1440.png](img/v0115-before-cat-analgesics-1440.png) (79,622 B) | [v0115-before-cat-analgesics-390.png](img/v0115-before-cat-analgesics-390.png) (47,873 B) |

肉眼可见的靶点（供改后同一位置对照）：

- 结果页桌面图第 2 行：`500 mg / 960 mg 片剂 | Tylenol Extra Strength | CA US`。
- 品牌页桌面图：`Acetaminophen 无中文名` 徽标 + H2「同一品牌在其他市场的写法」+ 含「严重碰撞」的粉色警示条。

---

## 5. 改后对照怎么做（给下一个工位/Lead）

1. 构建完成后（`== done ==`），先看 `site/dist/index.html` 的 sha256 是否变化 —— 没变说明构建没落盘，别急着测。
2. 起 `& $py serve.py 8000`（旧预览进程先关，避免 8000 被占后静默换端口），然后**用同一份脚本**再跑一次：
   - 脚本：`reports/2026-11-14-before-baseline.measure.js`
   - 注意：MCP 浏览器只允许读写 `…\default-workspace\_tmp\browser-out\` 与 `…\.dsh\profiles\desktop\`（实测 `filename` 指到仓库会被拒 `outside allowed roots`），所以要么把脚本内容内联到 `browser_run_code_unsafe` 的 `code`，要么把截图先落到 `_tmp\browser-out\` 再拷进 `docs/img/`（本次就是这么做的）。
3. 逐项对比：§2.1 规模 7 项、§2.2 度量 12 行（首屏条目/横向溢出/AFCR/chrome/字号）、§2.3 体积 6 行、§3 文字靶点 4 组。
4. 官方门槛仍按 AGENTS §5：`deploy/first_screen_check.py` 改前/改后各一次 —— 本机跑不了要在报告里写明由谁在什么环境补跑，不能拿替身数字顶替官方结论。

---

## 6. 已知缺口（照实列）

- 官方 CDP 守卫、`ui_surface_check.py` 在本机均不可用（§1.1 报错原文），本轮**没有官方 7 项指标**的权威数字；§2.2 是替身口径，**只能和本文件自己比**。
- 悬浮/遮挡、`--expand` 展开态、`--scroll-probe` 滚动态未测。
- 真机 / 4G / Lighthouse 未测；DPR 固定 1。
- 截图是首屏视口，不是整页长图；`?q=Tylenol` 截图时「正在加载完整索引…」仍在外。
- 品牌页/成分页/结果页为客户端渲染，度量只覆盖「已渲染 + 700 ms」的稳定态。
- 本轮全程只读：`site/build.py`、`site/dist`、`data/*.db`、`inbox/*.jsonl` 均未被我修改；写入仅 `reports/`（本文件 + 度量脚本）与 `docs/img/`（12 张截图）。
