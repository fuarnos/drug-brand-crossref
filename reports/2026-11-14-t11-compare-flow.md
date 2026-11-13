# T11：对照流程（三步确认 + 目标市场常驻 + 来源概念拆分）（task-11，v0.11.7 第二批）

> 工位：**site-ui** ｜ 时间：2026-11-14（北京谷段·第二批）｜ 任务：`task-11`（用户评审 B1–B3，方案 `reports/2026-11-14-t11-compare-plan.md`）
> 状态：**实现 + 自验完成**。与 T13 同落 `.tmp/dist-v0117`（一次构建、一次发布）。
> 未 commit、未发布、未写 `site/dist`、未改 `data/drugs.db`、未改 `collision` 语义；只做身份对照，不给替代建议/剂量换算/可互换判断。
> **T11 的 JS 全部在外置 `assets/app.js`**（+7,683 B），没有往每页内联里加。

## 0. 结论先行

1. **B1 三步流程**：结果行右侧新增「◎ 这条」（title/aria=「这条」）＋身份卡「我用的是这条」→ 点后 URL 变 `&pick=<key>&pmk=<市场>`，sticky 区出现 `#pickbar`：「已选 X · 市场 · 成分 · 规格 … [重选][逐项对照 →]」，**第二行固定写「候选集仍然是 N 条记录——这条只是其中一条」**；选目标市场后列表**不被替换**，下方多一块 `#cmp` 逐项对照（名称 / 规格 / 释放 → 相同 / 不同 / 未收录）。
2. **B2 目标市场常驻**：目标市场 chips（13 项，含「全部」）并进 `#meta` 那一行；桌面 1440 **首屏条目 4.5 = 改前 4.5**、chrome 0.292 = 改前 0.292；手机 390 **首屏条目 1.0 = 改前 1.0**、chrome 0.438 → 0.471（+0.033，见 §3）；横向溢出 0。
3. **B3 概念拆分**：`#src` 移入「高级筛选」折叠块、标签改「记录市场（只看登记在这里的记录）」，不再叫「来源市场」；目标市场 = sticky chips；两个 `<select>` 的 **id 与 13 个选项全部保留**。
4. **两条老路径逐字不变**（关键）：
   - **default** `?q=Tylenol&country=US`（无 pick）：**20 行、首行完全相同、`86 个名字命中`**，只把值灌进 `#country`（与 v0.11.6 一致）；
   - **legacy** `?q=Tylenol&country=US&legacy=1`：**187 个名字命中、整表替换、首行相同**（与 v0.11.6 逐字一致）。
5. 红线核对：`#cmp` 徽标只有 `相同/不同/未收录`；`t11.cmp_note` 明写「不代表这些产品可以互换」；「结果永远是候选集」仍在首 4000 字符内；无「等价/可替代/换算/建议」字样。
6. `ci_checks --fast --dist .tmp/dist-v0117` **PASS 8 / FAIL 0 / SKIP 4**；`i18n_check` **FAIL 0 / WARN 2（未新增）**；`core.json` raw **46,295,974（+0）**。

## 1. 改了什么（`site/build.py`，全部在 `APP_JS` / 首页模板 / 样式里）

| # | 位置 | 改动 |
|---|---|---|
| 1 | `APP_JS` 新增 `const T11 = {pick, pmk, parse, set, entry}` | 状态全走 URL（`pick` / `pmk`），`history.replaceState` + 重绘；无 pick 时 `T11.pick=''` |
| 2 | `render()` 里 `if(c && hits.length && !partial)` → `… && !T11.pick` | **只有不带 pick 才整表替换**（老深链逐字不变） |
| 3 | `flatRowHTML` / `identityCardHTML` | 新增 `data-pick="<key>|<市场>"` 按钮（行内是**一个字符**「◎」，整句在 title/aria：`.c-det` 列放整句会把行高 42→138px） |
| 4 | `render()` 末尾 `t11AfterRender(hits, c, T)` | 渲染 `#mkchips`、`#pickbar`、`#cmp`；`#pickbar` 永远带「候选集仍然是 N 条」 |
| 5 | 首页模板 | `.searchwrap` 内新增 `.t11row`（`#meta` + `#mkchips` + 手机端「目标市场 ▾」入口）与 `#pickbar`；`#ctrydetails` 改为 `<details class="advfilter">`（`#country`/`#src` 原样在里，13 选项不动） |
| 6 | i18n | 新增 20 个键（`t11.*` + `res.src_label` 改值），en/es/zh/zh-Hant/fr 五语齐 |
| 7 | CSS | `.t11row/.mkchip/.pickbar/.cmpbox/.cmp-b/.advfilter/.pickbtn/.src-asof` 等；**`td.c-det` 不许换行、`tr.br` 相对定位、「◎」绝对定位贴右缘**（保证结果行 42px 不变） |

## 2. 验收证据（浏览器实测，`?lang=zh`）

### 2.1 两条老路径（before = `.tmp/dist-v0116` = v0.11.6；after = `.tmp/dist-v0117`）

| 路径 | before | after |
|---|---|---|
| **default** `?q=Tylenol&country=US` | 20 行 · 首行「500 mg 片剂 TYLENOL FILM COATED TABLETS 500MG SG 详情」· `86 个名字命中` · `#country=US` | **20 行 · 同一首行（多了「数据截止」与「◎」）· `86 个名字命中` · `#country=US`**；`#pickbar` 隐藏 |
| **legacy** `?q=Tylenol&country=US&legacy=1` | 20 行 · 首行「泡腾剂 1,000 mg / 500 mg · 片剂 500 mg / 650 mg …」· `187 个名字命中` | **完全相同**（整表替换仍是 ≤200 条） |

### 2.2 三步流程（深链样例 `?q=Tylenol&pick=tylenol+extra+strength&pmk=US&country=CN`）

`#pickbar`（DOM 文本）：
```
已选 · Tylenol Extra Strength · US · 对乙酰氨基酚 · 片剂 500 mg · 胶囊 500 mg   [重选] [逐项对照 →]
候选集仍然是 86 条记录——这条只是其中一条。看全部候选 ↓
```
`#cmp`：
```
逐项对照（只比身份字段）   你这条 | 目标市场 CN
注册名   Tylenol Extra Strength | — | 未收录
规格     500 mg / 500 mg/950 mg / 960 mg/30 mL | — | 未收录
释放     — | — | 未收录
只按登记字段做身份对照；名字相同或成分相同都不代表这些产品可以互换。
```
- 列表**仍是 20 行**（未被替换）✓；`结果永远是候选集` 在首 4000 字符内 ✓；0 console error。
- 点「重选」→ 清 `pick/pmk`（列表不变）；点「逐项对照 →」→ `/drug/<成分>.html?pick=<key>&country=<市场>#mk-<市场>`（成分页用 T13 的筛选器与 `#mk-` 锚点，T11 只读不改）。

### 2.3 首屏 / chrome / 溢出（同一会话、同一脚本、结果页 `?q=Tylenol`）

| 视口 | 首屏条目（改前 → 改后） | chrome（改前 → 改后） | 行高 | 横向溢出 |
|---|---|---|---|---|
| 1440×900 | **4.5 → 4.5** | 0.292 → 0.292（+0） | 42 → 42 px | 0 → 0 |
| 390×844 | **1.0 → 1.0** | 0.438 → **0.471（+0.033）** | 223 → 223 px | 0 → 0 |

## 3. 取舍与已知缺口

1. **390 的 chrome +0.033（略超 +0.03）**：来自 sticky 行里多出的「目标市场 ▾」入口（市场 chips 在手机上收进高级筛选，避免 +32px 让首屏条目掉 0.5）。首屏**条目**没退化（1.0 = 1.0），但 chrome 占比确实多了 0.033 —— 这是「选择器常驻」与「chrome 不涨」之间的取舍，需要 atc4-ui 用官方口径复测确认可否接受。
2. **「◎ 这条」在桌面只是一个图标**（title/aria 是完整文案「这条」）：放整句会把 `.c-det` 列撑到 138px 行高（首屏条目 4.5 → 1.5）。身份卡上的「我用的是这条」是完整文案入口。
3. **对照只有 3 行**（名称 / 规格 / 释放）：状态与剂型在索引里没有 per-market 数据（方案 §5.1），按两段式落到成分页；`#cmp` 的「不同/未收录」不附任何处置建议。
4. **`#src` 只是位置与标签变了**（进高级筛选、改叫「记录市场」），筛选语义仍是「按记录市场筛候选集」；「登记库来源」的过滤要等下一版加索引字段（方案 B 案，+0.3–0.4 MB）。
5. `index.html` +19.6 KB：主要是**内联 i18n 字典**新增键（T13+T11 共 ~40 键 × 4 语）与 `.t11row` 标记；**T11 的 JS 逻辑不在内联里**（全在 `assets/app.js`，+7,683 B，全站共享）。

## 4. 复跑命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
$env:SITE_OUT='.tmp/dist-v0117'; & $py site/build.py            # == done ==
& $py deploy/ci_checks.py --fast --dist .tmp/dist-v0117          # PASS 8 / FAIL 0 / SKIP 4
& $py deploy/i18n_check.py                                       # FAIL 0 / WARN 2
& $py -m http.server 8013 --directory .tmp/dist-v0117
# 三步流程：/index.html?q=Tylenol&pick=tylenol+extra+strength&pmk=US&country=CN
# 老路径：/index.html?q=Tylenol&country=US（默认）  /index.html?q=Tylenol&country=US&legacy=1
```
