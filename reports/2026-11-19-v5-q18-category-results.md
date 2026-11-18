# V5 分类页市场计数单位 ＋ Q18 results@390 首屏条目（阶段 1 方案 + 阶段 2 落地与自验）

> 日期：2026-11-18（任务给的报告名用 2026-11-19）· 工位：atc4-ui · 任务：共享任务 `task-4`（队列 V5 + Q18）· 目标版本 v0.14.0
> 阶段 1：只读调研与方案（§1–§7）；**阶段 2：已落地 + 自验（§8）**——改 `site/build.py` 9 个 hunk，temp 构建 `== done ==`，
> Q18 真机态 390 首屏 3.5 → 5.0（探针态 6.5）、V5 对账 0 fail、六语齐、体积 −4%~−8%。未写 `site/dist`、未 commit、未发布。

## 结论先行（阶段 1 计划）

1. **Q18 走方案①（不改阈值）**：`≤767px` 的结果卡从「5 行竖排」改成「3 行两列 grid」——品牌名独占一行，`成分 | 规格与剂型`、`市场 | 操作` 各占一行。浏览器内原型实测：卡高 **146 → 78 px**，`results@390` 首屏条目 **3.5 → 5.5**（真实态，含 123 px 的「各国叫法」条）/ **≈7.5**（探针态）。字号、`items_min=5` 阈值、探针选择器都不动。
2. **V5**：`_status_summary_html()` 的折叠摘要从「第一组状态 + 前 5 个市场码 + 另有 N 个」改成「**每组状态 + N 个市场**」，展开态（市场码清单）不变。新增 1 个 i18n 键 `atc.mk_count`（六语）走 `data-i18n-tpl`，**不新增语言块**，23,888 处摘要的 HTML 体积预计下降。
3. 顺带修一个既有小瑕疵：结果卡 `.c-det` 没有 `data-label`，`td::before{content:attr(data-label) " · "}` 会在操作行前渲染一个孤立的「· 」（改前截图可见）。

## 1. Q18 现状（改前数字，`deploy/first_screen_check.py`，v0.13.7 产物）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -X utf8 deploy\first_screen_check.py --pages results --json .tmp\atc4-v5q18\before-results.json
& $py -X utf8 deploy\first_screen_check.py --pages results --viewports 390x844 `
    --shots .tmp\atc4-v5q18\shots-before --json .tmp\atc4-v5q18\before-390.json
```

| 视口 | AFCR | 条目 | chrome | 横向溢出 | 判定 |
|---|---|---|---|---|---|
| 390x844 | 0.88 | **3.5** | 0.18 | 否 | **未达：items 3.5 < 5** |
| 768x1024 | 0.98 | 10.5 | 0.13 | 否 | ok |
| 1440x900 | 0.97 | 9.0 | 0.09 | 否 | ok |
| 2560x1440 | 0.98 | 20.0 | 0.06 | 否 | ok |

- 稳定：2 轮签名逐项一致（`unstable 0 / suspect 0`），5.4 s。与 `reports/2026-11-18-q5-q8-deploy.md` §1.2 的 3.5 完全一致。
- 改前截图：`.tmp/atc4-v5q18/shots-before/fs-results-390x844.png`（4 张卡可见，第 4 张截在操作行）。

### 1.1 量到的几何（390x844，浏览器实测 `getBoundingClientRect`）

| 元素 | 改前 | 说明 |
|---|---|---|
| `#reswrap` 顶 | **256**（探针态） | 页头 57 + H1 26 + 搜索框 40 + 解析条 36 + `.restools` 44 + 间距 |
| 同上 | **395**（真实态） | 多了 `.u2bar`「各国叫法」条 **123 px**（`data/idx/core.json` 到位后才渲染） |
| 单卡 | **146–148**，卡距 8（pitch 154） | 5 行：品牌 25 + 成分 24 + 规格 24 + 市场 24 + 操作 29 + 上下 padding 12 |
| 首屏条目 | 3.5 | 3 张完整 + 第 4 张 0.85（0.90 才是 1 条） |

> ⚠️ 给 Lead / pages-deploy 的口径提醒：探针在 `u2bar` 还没插入时量（`core.json` 11 MB，比 Q11 的 220 ms 静默窗口慢），所以探针读 3.5，**真机首屏是 3.0**。这不是本任务要修的（`deploy/` 不在我写权限内），但「探针数字偏乐观 3 行」这件事值得记一笔。

### 1.2 原型（只注入浏览器 CSS，没碰 build.py）

两版原型都在真实态（含 `u2bar`，`#reswrap` 顶 395）量：

| 原型 | 布局 | 卡高 | 首屏条目 | 结论 |
|---|---|---|---|---|
| A | 12 列 grid，`成分\|规格` / `市场\|操作`，卡距 6、padding 4 | 81–83 | 5.0 | 刚好 5，无余量 |
| **B（推荐）** | 12 列 `minmax(0,1fr)`，`成分`占 5/12、`规格`占 7/12；`市场`5/12、`操作`7/12；卡距 4、padding 3、按钮 `min-height:22` | **77–79** | **5.5** | 第 6 张 0.53；探针态约 7.5 |

- B 版 10 行逐格量：没有一格换行（高度 22/24 px 恒定）；首行 5 格全部不截断；组合药（`TYLENOL SINUS SEVERE`）的 `成分`/`规格`仍是省略号——**与改前 `规格` 列同一行为**（改前 390 的 `c-dose` 也截断，见改前截图第 2 张「液体 96…」），不是新增缺陷。
- 品牌名 18 px / 正文 16 px / 辅助 13 px 全部不动；`table.res.rows` 只用于结果页（`build.py` 里只有一处 `class="res rows"`），`res grouped / res cmp / res famcmp / res ctable / coverage-table` 不受影响。
- 顺带：`td.c-det::before{content:""}` 去掉孤立的「· 」。

## 2. V5 现状与口径

### 2.1 折叠摘要现在的单位为什么难猜

`_status_summary_html()`（读取时 `site/build.py` 15452–15502）：

```python
remaining = total_codes - len(shown) + max(0, len(groups) - 1)
summary = _word(first_st) + ' <span class="atc-mk">' + esc(" ".join(shown)) + '</span>'
if remaining > 0:
    summary += ' · ' + _lang_block_text("atc.more", n=remaining)
```

`remaining` 把「剩下的市场码」和「剩下的状态组」**加在一起**，于是 `cat/analgesics.html` 里布洛芬显示
`在售 US GB CA AU SG · 另有 11 个` —— 11 = 10 个市场 + 1 个状态组，展开实为 **在售 14 个市场 · 状态未知 1 个（HK）**。

### 2.2 SQL 对账（`data/drugs.db` 只读，按市场聚合）

折叠计数必须用「**每个市场只算一次**、状态按 active > released > discontinued > withdrawn > unknown 取最强」的口径，否则同一个市场会在多组里重复出现：

```sql
SELECT v.substance_id, p.status, COALESCE(p.country, p.region) AS mk,
       COUNT(DISTINCT p.product_id) AS n
  FROM product p
  JOIN product_component pc ON pc.product_id = p.product_id
  JOIN variant v ON v.variant_id = pc.variant_id
 WHERE p.status IS NOT NULL AND p.status <> ''
   AND COALESCE(p.country, p.region) IS NOT NULL
 GROUP BY v.substance_id, p.status, COALESCE(p.country, p.region);
```

布洛芬（`M01AE01`， analgesics 页「另有 11 个」那一条）：

| 口径 | 数 |
|---|---|
| 原始分组（同市场可在多组重复） | active 14 / discontinued 5 / unknown 4 / withdrawn 4 |
| **按市场聚合后（折叠/展开都用它）** | **active 14**（AU CA CN CZ ES EU FR GB JP LV MX SG TW US）**+ unknown 1**（HK）= 15 个市场 |

对乙酰氨基酚：active 13 + unknown 1；普瑞巴林 / 美洛昔康 / 丁丙诺啡：active 14 + unknown 1（脚本：`.tmp/atc4-v5q18/probe_v5.py`）。

### 2.3 影响面（v0.13.7 产物现查）

| 页面 | 折叠摘要处数 |
|---|---|
| `cat/*.html`（16 页） | 1,777 |
| `atc/*.html`（1,153 页） | 22,111 |
| **合计** | **23,888** |

`drug/*.html` 不用 `st-details`（状态行在成分页是 `_status_badges_html`，不动）。

### 2.4 实施方案（阶段 2 才动手）

1. 新增 i18n 键 **`atc.mk_count`**：en `"{n} markets"` · es `"{n} mercados"` · zh `"{n} 个市场"` · zh-Hant `"{n} 個市場"` · fr `"{n} marchés"` · ko `"{n}개 시장"`（ko 已由 site-ui 并进 build.py，键集必须与 en 一致，`deploy/i18n_check.py` 会查）。
2. 折叠摘要改成**每组一截**：`<状态词> <span class="atc-mk" data-i18n-tpl="atc.mk_count" data-total="14">14 markets</span>`，组间 ` · `；展开态 `.st-list` 原样（列出每组全部市场码）。
   - 用 `data-i18n-tpl`（`data-total` → `{n}`，见 build.py `apply()` 17116–17123）而不是 `_lang_block_text`：**每处摘要只加 1 个元素**，不复制 5–6 份语言块；切语言由客户端换文案。
   - 不复用 `drug.markets`：它是纯单位（"个市场"），拼不出「14 个市场」的语序，且 `_lang_block_text()` 目前**不含 ko**（Q13 同类问题，属 site-ui 区段，我不改）。
3. 展开态与折叠态用**同一份** `groups`（`len(cs)`）→ 计数天然对得上；SQL 对账脚本会独立重算一遍聚合口径。
4. `atc.more` 保留：盐型行（`salt_more`）与 `atc.show_all` 仍在用。

## 3. 外部候选检索（AGENTS §12）

| 候选 | 许可 / 形态 | 结论 |
|---|---|---|
| **Modern Web Guidance** `responsive-table`（vendored v1.0.1，Apache-2.0，`vendor/modern-web-guidance/`） | 指南 | **采用其模式**：语义 `<table>` + 窄屏隐藏 `thead` + `::before` 注入列名 + 保留行语义。本仓 R1（v0.12.1）已经是这套；缺的只是「卡内两列」密度。相关 id：`css-layout`（网格）、`responsive-design`（视口/容器自适应） |
| [`zachleat/table-saw`](https://github.com/zachleat/table-saw) | 零依赖 Web Component（MIT），CSS grid 堆叠、`ratio` 控制窄屏列宽、可选 container query | **不采用**：思路与我们的 B 版一致，但本仓结果表是**客户端渲染**（`#reswrap` 由 app.js 生成），引入自定义元素要处理初始化时机 / 包裹层 / 新 JS 体积；为一个 3 行 grid 加依赖不划算 |
| [`filamentgroup/tablesaw`](https://github.com/filamentgroup/tablesaw) | jQuery 插件 / 无依赖 stack 版，MIT | **不采用**：仓库已 **archived 不再维护**；stack 模式是「表头左、值右」的 2 列，不是卡内两列摘要；且需要额外 JS 初始化 |
| [`evoluteur/isomorphic-table-cards`](https://github.com/evoluteur/isomorphic-table-cards) | 无依赖 vanilla JS，表格⇄卡片切换 | **不采用**：它解决的是「表格/卡片两种视图切换」，本仓已有「紧凑视图」开关，重复造轮子 |

→ 结论：**手写 CSS grid（B 版原型）**，不加依赖、不进构建链。

## 4. 阶段 2 的改动点（唯一锚点，`edit` 工具）

| # | 位置（读取时点行号） | 锚点 | 动作 |
|---|---|---|---|
| 1 | `_status_summary_html()` 15490–15502 | `    first_st, first_cs = groups[0]` | 折叠摘要改成每组「状态词 + N 个市场」，删掉 `remaining` 拼装 |
| 2 | `ATC_I18N["en"]` 14700 | `"atc.count": "{n} active ingredients", "atc.more": "and {n} more",` | 加 `atc.mk_count` |
| 3 | `ATC_I18N["es"]` 14772 | `"atc.count": "{n} principios activos", "atc.more": "y {n} más",` | 加 `atc.mk_count` |
| 4 | `ATC_I18N["zh"]` 14842 | `"atc.more": "另有 {n} 个", "atc.no_data":` | 加 `atc.mk_count` |
| 5 | `ATC_I18N["zh-Hant"]` 14892 | `"atc.more": "另有 {n} 個", "atc.no_data":` | 加 `atc.mk_count` |
| 6 | `FR_I18N` 1388 | `"atc.more": "et {n} plus",` | 加 `atc.mk_count` |
| 7 | `KO_I18N` 3702 | `'atc.more': '외 {n}개',` | 加 `atc.mk_count` |
| 8 | 结果卡 CSS `@media (max-width:767px)` 5571–5604 | `table.res.rows{display:block;border:0;font-size:16px}` 之后 | 追加 `tr.br` 的 grid 规则（B 版）与 `.c-det::before{content:""}` |

**不碰**：`_lang_block_text`、`_status_badges_html`、`atc.more` / `atc.show_all`、盐型行、其他工位正在改的 ko 字典主体。FS_STALE_VERSION 就重读重标。

## 5. 阶段 2 验收计划（逐条给证据）

| 项 | 命令 / 判据 |
|---|---|
| 构建 | `$env:SITE_OUT='.tmp\dist-v5q18'; & $py -X utf8 site\build.py` → `== done ==`（**不用 `site/dist`**） |
| Q18 首屏 | `first_screen_check --pages results --viewports 390x844 --shots` → `items ≥ 5`；再跑全量 24 组对比改前（drug@1440 / coverage@390/768 是既有缺口） |
| Q18 溢出 | 探针「溢出 否」+ 390 截图（`docs/img/`） |
| V5 计数 | 新脚本重算「按市场聚合」SQL，逐页比对 `cat/*.html` + `atc/*.html` 的折叠计数；展开态每组市场码数 == 折叠数，且市场码并集 = SQL 的市场并集 |
| 五语（+ko） | `deploy/i18n_check.py --build-py site/build.py`（键集一致）+ 浏览器按 `?lang=en/es/zh/zh-Hant/fr` 各抽 1 页看摘要文案 |
| 体积 / 确定性 | `site/dist` 文件数不变（页数不减）；`atc/`、`cat/` 页 HTML 体积对比（预期下降）；`deploy/check_build_determinism.py` |
| 快检 | `deploy/ci_checks.py --fast` |
| 红线 | 只做身份对应与「不可互换」警示，不新增任何用药建议 / 剂量换算 / 手工关系标注 |

## 6. 依赖与风险

1. **build.py 并行改动**：site-ui 正在并 ko（+684 行，含 `KO_I18N` / `deploy/i18n_check.py` 的 `LANGS`）。我全部用唯一锚点 + `edit`；同一函数只改一次。
2. **`_lang_block_text` 缺 ko**（Q13 同类）：V5 的新摘要避开它（走 `data-i18n-tpl`），但盐型行的「另有 N 个」在 ko 下仍会空白 —— 属 site-ui / LG1 范围，我只在报告里标注。
3. **探针态与真机态差 123 px**（`.u2bar`）：本任务不动 `deploy/`，但交付后真机首屏仍有 5.5 条（≥5），不会「探针绿、真机红」。
4. 等 Lead 发 **BUILD-FREE** 才动 build.py；构建串行（`SITE_OUT` 独立目录）。
5. 报告落盘：本文件；阶段 2 追加「改了什么 / 怎么验的 / 数字对照」。

---

## 7. 阶段 2 施工单（HOLD 期间写好，BUILD-FREE #2 后执行）

> 2026-11-18 09:20 Lead 发 **HOLD**：v0.13.8 干净重建（~25 分钟），期间不 edit / 不 build `site/build.py`。
> 到目前为止**没有 edit 过 build.py**（只读 + 浏览器注入 CSS 原型 + `reports/` 与 `.tmp/` 脚本），
> `site/build.py` 里现有的改动全部来自其他工位。基线改为 **v0.13.8**（`site/dist` 137,348 文件，09:09 构建）。

### 7.1 Q18：最终 CSS（插在 `@media (max-width:767px)` 里，`table.res.rows td.c-det{...}` 之后）

```css
  /* Q18（v0.14.0）：390 结果卡从「5 行竖排」压成「4 行紧凑卡」（品牌 / 成分｜规格 / 市场 /
     操作），卡高 146 → ~81 px、首屏条目 3.5 → 5.5（真机态，含「各国叫法」条）；市场与操作
     各占整行，六语都不换行。只压间距：正文 16 / 辅助 13 / 品牌 18 px 一律不动；
     长值仍走省略号（与改前 c-dose 的行为一致）。 */
  table.res.rows tr.br{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));
   column-gap:8px;margin:0 0 3px;padding:1px 0;border-bottom:1px solid var(--line)}
  table.res.rows tr.br td{padding:0;line-height:1.2}
  table.res.rows tr.br td.c-brand{grid-column:1 / -1;margin:0;line-height:1.15}
  table.res.rows tr.br td.c-ing{grid-column:1 / 6}
  table.res.rows tr.br td.c-dose{grid-column:6 / 13}
  table.res.rows tr.br td.c-market{grid-column:1 / -1}
  table.res.rows tr.br td.c-det{grid-column:1 / -1;margin-top:0;text-align:left;white-space:normal}
  table.res.rows tr.br td.c-det::before{content:""}
  table.res.rows tr.br td.c-det .pickbtn,table.res.rows tr.br td.c-det .detbtn{min-height:18px;
   font-size:13px;line-height:1.15;padding:0 6px 0 0;margin:0 2px 0 0}
```

**为什么从「3 行两列」改成「4 行紧凑卡」**（原型在 v0.13.8 产物上量，真机态含 `.u2bar`）：

| 原型 | 布局 | zh | en | es | fr | ko | 卡高 |
|---|---|---|---|---|---|---|---|
| A | 3 行：品牌 / 成分｜规格 / 市场｜操作（5/7 分） | 6.0 | **4.5** | **4.5** | **4.5** | 6.0 | 70（zh）/ 92（en/es/fr） |
| B3 | 4 行：品牌 / 成分｜规格 / 市场 / 操作（市场·操作整行） | 5.5 | 5.5 | 5.5 | 5.5 | 5.5 | 80–82 |
| **B4（采用）** | B3 + 卡距 3 px + 1 px 分隔线 | *构建后实测* | | | | | ~81 |

- A 的问题：`Elegir este producto / Ficha del registro / Choisir ce produit / Fiche d’enregistrement`
  在 199 px 列宽下换行（+20 px），es/fr/en 掉到 4.5；**不能靠下调阈值掩盖**，也不能砍掉「查看登记详情」。
- B3/B4 把「市场」和「操作」各放整行：六语都不换行、市场不再被挤，代价是 zh 从 6.0 降到 5.5（仍 ≥5）。
- 不动 `items_min`、不动探针、不动 ≥768px 的表格布局；`res grouped / cmp / famcmp / ctable / coverage-table` 都不匹配 `tr.br`，不受影响。
- `.c-det::before{content:""}` 同时修掉改前那个孤立的「· 」前缀（`c-det` 没有 `data-label`）。

### 7.2 V5：`_status_summary_html()` 摘要代码（替换 `first_st, first_cs = groups[0]` 起的 6 行）

```python
    # V5（v0.14.0）：折叠态改成「每组状态 + N 个市场」，市场名只在展开态出现。
    # 旧文案「另有 N 个」把「剩下的市场码」和「剩下的状态组」加在一起（布洛芬 14 个在售市场
    # + 1 个未知市场 → 折叠显示「另有 11 个」），单位猜不出，和展开后的市场名也对不上。
    # 数字走 data-i18n-tpl（data-total → {n}）：一处摘要只多 1 个元素，不复制 5–6 份语言块。
    def _n_markets(n: int) -> str:
        return esc(I18N["en"]["atc.mk_count"].replace("{n}", str(n)))

    summary = ' · '.join(
        f'{_word(st)} <span class="atc-mk" data-i18n-tpl="atc.mk_count"'
        f' data-total="{len(cs)}">{_n_markets(len(cs))}</span>'
        for st, cs in groups)
```

docstring 第 2 条同步改成「折叠态写『状态词 + N 个市场』（N = 展开后该组市场码个数）」。

### 7.3 六语键（各在 `atc.more` 旁边加一行）

| 语言 | 位置 | 值 |
|---|---|---|
| en（`ATC_I18N`） | `"atc.count": "{n} active ingredients", "atc.more": "and {n} more",` | `"atc.mk_count": "{n} markets",` |
| es（`ATC_I18N`） | `"atc.count": "{n} principios activos", "atc.more": "y {n} más",` | `"atc.mk_count": "{n} mercados",` |
| zh（`ATC_I18N`） | `"atc.more": "另有 {n} 个", "atc.no_data":` | `"atc.mk_count": "{n} 个市场",` |
| zh-Hant（`ATC_I18N`） | `"atc.more": "另有 {n} 個", "atc.no_data":` | `"atc.mk_count": "{n} 個市場",` |
| fr（`FR_I18N` 扁平表） | `"atc.more": "et {n} plus",` | `"atc.mk_count": "{n} marchés",` |
| ko（`KO_I18N` 扁平表） | `'atc.more': '외 {n}개',` | `'atc.mk_count': '{n}개 시장',` |

`atc.more` 保留（盐型行与 `atc.show_all` 仍在用）；`_lang_block_text` 不动。

### 7.4 HOLD 期间已备好的验收脚本

| 脚本 | 作用 |
|---|---|
| `.tmp/atc4-v5q18/check_v5.py` | V5 对账：①全站 `cat/*.html` + `atc/*.html` 每处 `st-details` 的结构一致性（折叠计数 = 展开码数、组序一致、无 `atc.more`、英文兜底 = 模板）；②6 个抽样成分的 SQL 聚合 ↔ 页面计数 |
| `.tmp/atc4-v5q18/after_checks.ps1` | 构建（`SITE_OUT=.tmp\dist-v5q18`）→ 首屏 390 截图 + JSON → 全量 24 组 → V5 对账 → i18n → 体积/页数对照；`-SkipBuild` 可只跑检查 |
| `.tmp/atc4-v5q18/size_compare.py` | 关键页体积 + `cat/atc` 页数 + 文件总数对照 |

### 7.5 已知风险（HOLD 期间确认）

1. 探索性测量里 `es/fr` 的操作按钮（`Elegir este producto` / `Fiche d’enregistrement`）在 199 px 列宽下会换行，卡高 +20 px → 4.5 条；最终 CSS 用 13 px/1.15 行高压到单行，**构建后必须逐语复核**（zh 是门禁口径，但不想让 fr/es 掉回 4.5）。
2. `.u2bar`（123 px）只在 `data/idx/core.json` 到位后出现：探针读数偏乐观约 3 条；本次验收同时给「真机态」数字。
3. 构建必须等 BUILD-FREE #2，且只做 1 次（`SITE_OUT` 独立目录，避免和 Lead 的 R2/重建抢 IO）。

---

## 8. 阶段 2 落地与自验（2026-11-18，BUILD-FREE #2 窗口）

> 改动：`site/build.py` **9 个 hunk**（6 个 `atc.mk_count` 键 + `_status_summary_html` docstring + 摘要代码 + 390 结果卡 CSS），全部落在我区段；
> 未写 `site/dist`、未 commit、未发布。构建：`SITE_OUT=.tmp/dist-v5q18 & $py -X utf8 site\build.py` → **`== done ==`**（exit 0，1,305.2 MB）。
> 注意：这份 WIP build.py 同时含 site-ui / alias-site / search-alias 的改动，下面凡不是本工位选择器的波动都已标注。

### 8.1 Q18：results@390 首屏条目（改前 / 改后，同一台机同一天）

| 指标 | 改前（`site/dist` v0.13.8） | 改后（`.tmp/dist-v5q18`） | 判定 |
|---|---|---|---|
| **首屏条目** | **3.5**（3 完整 + 0.85） | **6.5**（6 完整 + 0.69） | ✅ 门槛 5，未下调 |
| AFCR | 0.88 | 0.88 | 不退化 |
| chrome | 0.18 | 0.18 | 不退化 |
| 横向溢出 | 否 | 否 | ✅ |
| 稳定性 | 2 轮一致 / unstable 0 | 2 轮一致 / unstable 0 | 3.0 s |

- 全量 24 组（改前 → 改后）：`results@390` **3.5 → 6.5**（唯一新增达标项）；未达组 **3 → 2**（`drug@1440` 4.5 = 既有缺口；`coverage@390` 3.5 → 2.5 是 coverage 页，不是 `tr.br` 选择器，属同批 WIP 的其他工位）。
- **真机态**（浏览器等 `.u2bar` 出现后再量，六语各 390×844）：**en 5.0 / es 5.0 / zh 5.0 / zh-Hant 5.0 / fr 5.0 / ko 5.0**，卡高 83–84 px，`scrollWidth 375 / innerWidth 390` → **六语都 ≥5 且无横向溢出**。
- 截图：改前 [docs/img/q18-results-390-before.png](../docs/img/q18-results-390-before.png)、改后 [docs/img/q18-results-390-after.png](../docs/img/q18-results-390-after.png)（改后 6 张卡在首屏，卡片间 1 px 分隔线）。
- 归因边界：我的 CSS 全在 `@media (max-width:767px)` 内；`results@768` 10.5 → 9.5（doc_h 2076 → 2120，+44 px）**不是本工位改动**，需在最终合并构建复核。

### 8.2 V5：分类页市场计数对账（`.tmp/atc4-v5q18/check_v5.py`）

```text
页面 1170（cat 16 + atc 1154）· 折叠摘要 23888 处 · 成员 5479 个
抽样 SQL ↔ 页面：
  · acetaminophen  SQL [('active', 13), ('unknown', 1)]                    · 页面同 · OK
  · ibuprofen      SQL [('active', 14), ('unknown', 1)]                    · 页面同 · OK   ← V5 例子
  · pregabalin     SQL [('active', 14), ('unknown', 1)]                    · 页面同 · OK
  · meloxicam      SQL [('active', 13), ('withdrawn', 1), ('unknown', 1)]   · 页面同 · OK
  · buprenorphine  SQL [('active', 13), ('unknown', 1)]                    · 页面同 · OK
  · celecoxib      SQL [('active', 13), ('withdrawn', 1), ('unknown', 1)]   · 页面同 · OK
OK：折叠计数 = 展开市场码 = SQL（抽样）；摘要无 atc.more；英文兜底与模板一致
```

- 全站断言（每处 `st-details`）：折叠每组 `data-total` = 展开该组市场码数；组序一致；折叠计数和 = 展开后市场总数（每市场只出现一次）；旧「另有 N 个」0 处；英文兜底 = en 模板替换。**FAIL 0**。
- 布洛芬（analgesics 页）：折叠 `在售 14 个市场 · 状态未知 1 个市场`；展开 `在售 US GB CA AU SG CN ES MX TW JP CZ LV EU FR · 状态未知 HK`。
- 六语实测（同一页同一行）：en `active 14 markets · unknown 1 markets`；es `activo 14 mercados · desconocido 1 mercados`；zh `在售 14 个市场 · 状态未知 1 个市场`；zh-Hant `販售中 14 個市場 · 狀態未知 1 個市場`；fr `En vente 14 marchés · Statut inconnu 1 marchés`；ko `판매 중 14개 시장 · 알 수 없음 1개 시장`。

### 8.3 体积 / 页数 / i18n

| 项 | 改前 | 改后 | 说明 |
|---|---|---|---|
| `atc/N02B.html` | 56,023 B | 53,614 B | **−4.3%**（摘要不再带 5 个市场码 + 5 语「另有 N 个」） |
| `atc/M01A.html` | 75,963 B | 69,732 B | **−8.2%** |
| `cat/analgesics.html` | 187,797 B | 172,889 B | **−7.9%** |
| cat 页数 / atc 页数 | 16 / 1,154 | 16 / 1,154 | 不变 |
| 文件总数 | 137,348 | 137,348 | 不变 |
| i18n（`deploy/i18n_check.py --build-py`） | — | **FAIL 0 / WARN 2**（684→687 键 × 6 语，WARN 是同 2 条既有 es 伪翻译嫌疑） | `atc.mk_count` 六语齐 |
| `ci_checks.py --fast`（补丁后） | — | **8 PASS / 0 FAIL / 5 SKIP**（25 s） | py_compile / unittest×4 / i18n / dist / workflow |

### 8.4 验收对照（task-4）

| 验收项 | 结果 |
|---|---|
| V5 文案 ↔ SQL（按市场聚合：active 14 / unknown 1） | ✅ §8.2，抽样 6 成分全 OK；全站 23,888 处结构断言 0 fail |
| V5 展开态市场名 ↔ 折叠计数 | ✅ 逐组 `data-total` = 市场码数，和 = 市场总数 |
| V5 五语（+ko） | ✅ §8.2 六语实测文案；`i18n_check` 键集一致 |
| Q18 results@390 ≥5（真机态） | ✅ **5.0**（六语一致）；探针态 6.5 |
| Q18 无溢出 + 390 截图 | ✅ `overflow 0`；`docs/img/q18-results-390-{before,after}.png` |
| Q18 不下调阈值 | ✅ `TYPE_THRESHOLDS["results"]["items_min"]` 未改、探针未改、选择器未改 |
| 不写 `site/dist` / 不 commit / 不发布 | ✅ 只写 `.tmp/dist-v5q18`、报告、`docs/img/` 两张截图 |
| 红线 | ✅ 只做身份对应与状态计数，无用药建议 / 剂量换算 / 手工关系标注 |

### 8.5 剩余 / 可选项

1. **真机态余量**：现在 5.0（刚好过线）。把卡距 3 px → 1 px（或去掉 1 px 分隔线）预计到 5.5，但需要再跑一次全量构建才能给证据——本次没做，留给 Lead 定稿构建时决定。
2. `results@768` 10.5 → 9.5、`coverage@390` 3.5 → 2.5、`atc@2560` 48.5 → 46.0 与我的改动无关（选择器/媒体查询都不覆盖），请在**最终合并构建**上复测后归因给对应工位。
3. `_lang_block_text` 的 ko 空白已由 Lead 的 v0.13.8 热修解决（`langs = list(I18N_REQUIRED_LANGS)`），本工位未再动。
4. 本报告数字全部来自 `.tmp/dist-v5q18`（WIP build.py 构建）与 `site/dist` v0.13.8 现查；JSON 证据在 `.tmp/atc4-v5q18/`。

### 8.6 补充（2026-11-18 收尾，V5 原文第二句：`M01A` / `N02B` 代码配分类名）

Lead 复核指出 V5 原文还有「`M01A` / `N02B` 等代码配该语言的分类名」——这条属于 V5 本体，已补（**2 个 hunk**，只碰分类页区段）：

| # | 位置 | 改动 |
|---|---|---|
| 1 | `build_category_pages()` 子类 chip（`cf_chips.append`） | `<code>N02B</code>` 后面加 `_lang_inline(_atc_names(_k))` 的**六语行内类名块**：fr/ko 按现成 `_atc_names()` 给英文 +「(EN)」标注、不机翻 |
| 2 | `.lf-chip .n` 之后 | `.lf-chip .lf-chip-nm{color:var(--muted);font-size:13px;max-width:10em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}`——`M01A` 这类长类名限量省略，手机不撑破行 |

验证（**未跑全量构建**，Lead 随后统一构建 + CI；下面是对 `build_category_pages()` 的局部渲染 + 静态检查）：

- `py_compile site/build.py` = 0；`i18n_check --build-py` **FAIL 0 / WARN 2**（无新增键，WARN 仍是原来 2 条 es 伪翻译嫌疑）。
- 局部渲染 16 个 cat 页到 `.tmp/atc4-v5q18/catchk/cat/`（只读 DB + 临时 OUT）：`analgesics` 4 个子类 chip，每个 = 代码 + **6 个类名语言块** + 计数：

  | chip | 类名（en / es / zh） | 计数 |
  |---|---|---|
  | `M01A` | Anti-inflammatory and antirheumatic products, non-steroids / Productos antiinflamatorios… / （zh 数据缺 → 回落 en，与 `/atc/M01A.html` 标题同口径） | 63 |
  | `N02B` | Other analgesics and antipyretics / Otros analgésicos y antipiréticos / **其它解热镇痛药** | 53 |
  | `N02A` | opioid / opioide / 鸦片类药物 | 43 |
  | `N02C` | antimigraine / antimigrañoso / 抗偏头痛药 | 29 |

- 子类 chip 在**默认收起**的「子类」浮层里，不影响首屏条目（Q18 的 390 读数不受影响）。
- 收尾口径：这两处（chip + CSS）请并入最终全量构建；构建后抽 `cat/analgesics.html` 看一眼 `data-sub-filter` 三个 chip 的文案是否带类名即可复核。
