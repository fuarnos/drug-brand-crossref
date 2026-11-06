# task-149 name 页公共壳瘦身（2026-11-07）

> 范围：只改 `site/build.py`（唯一改动文件）+ 本报告。**未动** `lib/` `db/` `data/` `docs/` `deploy/`；
> 未发布、未 `git commit`；**未写 `site/dist`**（线上 v0.9.5 产物原样保留，构建全部走 `SITE_OUT`）。
> 底线不变：只影响 HTML 壳的体积与冗余，不改任何身份对应、碰撞或警示语义。

## 0. 结论

- **省下 60,294,426 B = 57.50 MiB**（目标 ≥ 45 MiB，余量 12.5 MiB）。总字节 **943,601,056 → 883,306,630 B**（842.39 MiB），文件数 **121,292 → 121,292（不变）**，0 字节文件 0。
- 省下来的**全部来自 `name/` 目录**：`376,809,513 → 316,515,087 B`（77,058 页，均 4,890 → 4,107 B/页）。其余目录逐字节不变（`index.html`、`drug/atorvastatin.html`、`atc/N02BE.html` 体积 0 变化，sitemap / core.json 一字未动）。
- 单页公共壳 **3,002–3,098 B → 2,239–2,308 B（−25.5%）**，正文（`<main>` 内）**0 字节变化**。
- 一致性：全量 77,058 页 **title / canonical / hreflang 不一致 0 页**；正文 104 页有差异，**全部是同内容不同顺序**（规格并列项顺序，见 §4.3，基线构建同样存在，与本次改动无关）。抽样 200 页（四语块 70 / CJK 标题 70 / 随机 60）**四项全部一致**。
- 无 JS / 桌面 / 移动三种情形的**无头截图逐像素比对通过**（桌面与无 JS 完全一致；移动 36 像素单通道差 1/255 的抗锯齿噪声）。
- `ci_checks.py --fast`：**PASS 6 / SKIP 2 / FAIL 0**（21.8s）。

## 1. 方案

name 页就地做「壳瘦身」，**不引入新文件、不引入新脚本、不改内联策略**（`style.css` 本来就是外链，`site/dist` 里没有内联 `<style>`；task-146 里「壳 1,416 B / 全外链省 104 MiB」的估算是按旧口径算的，实际大头在 head 的重复块，不在 CSS）。

| # | 规则 | 每页省 | 全站省 | 为什么安全 |
|---|---|---|---|---|
| ① | 去掉站点级 WebSite JSON-LD | 236 B | 18,185,688 B（17.34 MiB） | 站点级事实在首页/顶层页/成分页仍声明；7.7 万长尾页重复声明同一实体无结构化收益 |
| ② | 去掉模板化 `<meta name="description">` | 202 B | 15,587,702 B（14.87 MiB） | 77k 页同构文案（标题 + 固定句），搜索引擎会按正文生成摘要；title 不受影响 |
| ③ | favicon 的 SVG data URI → `data:,` | 207 B | 15,951,006 B（15.21 MiB） | 长尾页不再背 238 B 的 data URI；`data:,` 显式声明「无图标」，反而省掉每页对 `/favicon.ico` 的一次 404 请求 |
| ④ | 压掉壳内空白（标签之间 + 标签内部属性分隔） | 137 B | 10,570,366 B（10.08 MiB） | header/footer 都是 `display:flex` + `gap` 排版（`.wrap`/`nav`/`.langs`/`.foot-links` 全部 flex），标签间空白不参与渲染；**文本节点一个空格都不动** |
| | **合计** | **782 B** | **60,294,762 B（57.50 MiB）** | 实测总差 60,294,426 B（−336 B 是 chunk 边界 strip 的差异） |

**保留**：`<title>`、`<link rel="canonical">`、`<link rel="alternate" hreflang="x-default">`、`<meta name="robots" content="noindex,follow">`（单包装页）、`style.css` / `boot.js` 引用、`window.DSH_PREFIX`、GoatCounter、`skip-link`、完整 7 项导航 + 四语切换、页脚署名 + 免责声明 + 纠错入口。
→ 所以**无 JS 也能读正文、能走导航**（截图见 §4.4），且**没有新增任何脚本**（slim 页脚本数仍是 3：boot.js、DSH_PREFIX、统计）。

## 2. 改动点（`site/build.py`，3 处）

| 位置 | 改动 |
|---|---|
| `_SLIM_JSONLD_RE` / `_SLIM_DESC_RE` / `_SLIM_ICON_RE` / `_WS_BETWEEN_TAGS_RE` / `_WS_RUN_RE` / `_TAG_RE` + `_collapse_tag_ws()` / `_slim_shell()` | **新增**。`_slim_shell(head, top, bottom)` 只处理三段壳（head、`<body>`~正文之间、正文~`</body>` 之间），正文 chunk 根本不传进去。规则 ①②③ 只在 head 段生效；④ 用 `_TAG_RE` 把连续空白限制在标签内部，避免改动文本节点 |
| `page(...)` | 新增 `slim: bool = False` 参数；把原来的单条 f-string 拆成 `head / top / bottom` 三段变量再拼 `head + top + body + bottom`（**非 slim 输出与旧模板逐字节相同**，已在 §4.1 验证）；`slim=True` 时先过 `_slim_shell` |
| `build_name_pages()` | name 页写盘处改调 `page(..., slim=True, ...)`。其余页面（首页/drug/atc/combo/maker/cat/顶层页 + 三语副本）调用点**一字未改**，继续走原模板 |

风格沿用现有做法：常量放模块级、`from __future__ import annotations`、中文 docstring 说明「为什么」。回滚粒度也按规则分了三个正则，可单独去掉任一条。

## 3. 体积 delta

三份构建（同一份 `data/drugs.db`、同一台机器；`site/dist` 全程只读）：

| 构建 | 说明 | 文件数 | 总字节 | MiB |
|---|---|---|---|---|
| `site/dist` | 线上 v0.9.5 产物（**未动**） | 121,292 | 943,601,056 | 899.89 |
| `.tmp/build-base` | **同代码基线**：`page(slim=False)` 强制关掉瘦身 | 121,292 | 943,601,056 | 899.89 |
| `.tmp/build-slim` | 本次改动（`build.py` 现状） | 121,292 | **883,306,630** | **842.39** |

- **基线 == dist（总量逐字节相同）**：说明本次对比里唯一的变量就是「壳瘦身」，不是数据或别的模板改动。
- 目标线：`943,601,056 − 45 MiB = 896,415,136 B`，实际 **883,306,630 B**，比目标线还低 **13,108,506 B**。
- 900 MiB 自设上限（943,718,400 B）下余量从 **0.11 MiB → 57.61 MiB**。

分目录（只列变化）：

| 目录 | dist | slim | 差 |
|---|---|---|---|
| `name/`（77,058 页） | 376,809,513 | 316,515,087 | **−60,294,426** |
| 其余全部（drug/combo/maker/atc/data/assets/顶层） | 566,791,543 | 566,791,543 | 0 |

## 4. 一致性验收

### 4.1 非 slim 页必须与旧模板逐字节一致

`page()` 拆成三段后，用同一入参分别渲染并与 `site/dist` 现存页比对（仅把 `?v=<时间戳>` 归一）：

| 检查 | 结果 |
|---|---|
| head 一致（普通 name 页） | ✅ |
| header 一致 | ✅ |
| 正文一致 | ✅ |
| footer 一致 | ✅ |
| 单包装页（带 `noindex` + 四语块）head / header / footer | ✅ / ✅ / ✅ |

### 4.2 全量逐页比对（77,058 页）

脚本对每一页抽取：正文（`<main>` 内）sha256、`<title>` 文本、`canonical`、全部 `hreflang` 对。

| 项 | 不一致页数 |
|---|---|
| `<title>` | **0** |
| `canonical` | **0** |
| `hreflang`（含 x-default） | **0** |
| 正文 | 104（见 §4.3，非本次改动引入） |
| 文件集合 | 只在旧 0 / 只在新 0 |
| 含四语 `data-lang-block` 的页 | 45,072（两版同） |
| 标题含 CJK 的页 | 21,254（两版同） |

### 4.3 那 104 页「正文不同」是什么

结论：**同内容、只是并列项顺序不同**，与本次改动无关。

1. 三项检验（对 104 页逐页）：可见文本词多项集 **104/104 相同**；药物页链接多项集 **104/104 相同**；差异只出现在 `、` 连接的规格列表内部，例如
   `250 unit、250 IU、500 unit、500 IU…` ↔ `250 unit、250 IU、500 IU、500 unit…`。
2. 机制（读代码可复核）：`build_name_pages` 的规格列 = `'、'.join(sorted(g['s'], key=_sort_strength))`，`g['s']` 是 **`set`**（`collect_name_data` 里 `"s": set()`），`_sort_strength` 只按数字前缀排序 → 并列项（`250 unit` / `250 IU`）保留集合迭代顺序；CPython 字符串哈希按进程随机加盐（`PYTHONHASHSEED`），两次独立构建就会翻转。用真实取值跑同一排序键，三种种子给出三种顺序：

   ```
   PYTHONHASHSEED=0: 250 unit、250 IU、500 IU、500 unit、750 unit、1000 unit、1000 IU、1500 unit
   PYTHONHASHSEED=1: 250 IU、250 unit、500 IU、500 unit、750 unit、1000 IU、1000 unit、1500 unit
   PYTHONHASHSEED=3: 250 unit、250 IU、500 unit、500 IU、750 unit、1000 unit、1000 IU、1500 unit
   ```
3. 对照实验（决定性证据）：**同代码、同数据、只把 `slim` 关掉的基线构建**，与 `site/dist` 比对同样是 **130 页**正文顺序差异、title/canonical/hreflang 全 0；基线 vs slim 是 92 页。也就是说「不瘦身」的两份构建之间也有同样差异 → 这是既有的构建非确定性，不是壳瘦身带来的（壳瘦身按构造不触碰 `body`，见 §2）。

### 4.4 抽样 200 页（含四语）

抽样池：含四语 `data-lang-block` 的单包装页 70 + 标题含 CJK 的页 70 + 随机 60，去重后 200 页。
对每页比对 正文 sha256 / `<title>` / `canonical` / `hreflang`：**不一致 0 页**。

### 4.5 视觉与无 JS（无头 Chrome）

同一页 `name/lipitor.html`，旧 dist 与新构建各截一次（两份产物各自的 `../assets/style.css`）：

| 场景 | 结果 |
|---|---|
| 桌面 1280×900（JS 正常） | **像素完全一致** |
| 移动 390×844（JS 正常） | 36 像素单通道差 **1/255**（抗锯齿噪声，无位移；重跑一次为完全一致） |
| 无 JS（删掉全部 `<script>` 后渲染，1280×900） | **像素完全一致**，且 `<h1>`、卡片、导航、页脚都在静态 HTML 里 |

## 5. LCP 目标页（必须不变或变小）

| 页 | dist | slim | 差 |
|---|---|---|---|
| `index.html` | 204,279 | 204,279 | **0** |
| `drug/atorvastatin.html` | 102,897 | 102,897 | **0** |
| `atc/N02BE.html` | 7,390 | 7,390 | **0** |
| `name/lipitor.html` | 4,303 | 3,540 | **−763（−17.7%）** |

## 6. 其它不变量

| 项 | dist | slim |
|---|---|---|
| 文件数 | 121,292 | 121,292 |
| 0 字节文件 | 0 | 0 |
| `sitemap.xml` | 8,454,507 B / 63,363 URL | 8,454,507 B / 63,363 URL |
| `data/idx/core.json` | 41,381,256 B | 41,381,256 B |

## 7. CI

```powershell
& $py deploy/ci_checks.py --fast
# 8 项：PASS 6 / FAIL 0 / SKIP 2（trilingual、check_data 都是 --fast 跳过）
# [PASS] py_compile 145 个文件 · [PASS] unittest:etl 25 · [PASS] unittest:lib 59
# [PASS] unittest:mobile 29 · [PASS] dist-integrity 121,292 文件 / sitemap 63,363 URL / 0 字节 0
# [PASS] workflow
```

## 8. 风险与回滚

**风险（都已在报告里量化）**

1. **SEO**：name 页不再有 `meta description` 与站点级 JSON-LD。理由与代价见 §1；`title` / `canonical` / `hreflang` / 正文一处未动，搜索引擎仍能正常抓取与生成摘要。若后续想恢复 description，只去掉 `page()` 里 `_SLIM_DESC_RE` 那一步即可（回退 15.6 MB）。
2. **favicon**：77k 长尾页标签页图标退回浏览器默认（`data:,` 显式声明，避免每页 404）。顶层页/首页/成分页不受影响。
3. **版式**：空白压缩依赖 flex+gap 排版，已用桌面 / 移动 / 无 JS 三种截图核对（§4.5）。若将来给 `header`/`footer` 换成 inline/block 排版，需要同步回看这条规则。
4. **构建非确定性（既有问题，不是本次引入）**：`set` + 并列排序键导致规格顺序随 `PYTHONHASHSEED` 变化，会让「逐页 diff」出现 ~100 页噪声。建议后续单独做一件事：在构建入口固定 `PYTHONHASHSEED=0`（`run_all.py` / `publish.ps1`），或把 `g['s']` 换成有序结构。**本次未动**（超出本任务写权限与验收口径）。
5. **体积仍在 900 MiB 上限内**：842.39 MiB（new），余量 57.61 MiB。再多加页面前仍应看一遍 `reports/task146-size-budget-20261031.md` 的口径。

**回滚（任一即可，改动未提交，HEAD 干净）**

1. 整体回滚：`& .\tools\git\cmd\git.exe checkout -- site/build.py`（回到 v0.9.5 的模板，构建即恢复旧壳）。
2. 局部回滚：把 `build_name_pages()` 里的 `slim=True` 去掉（1 行）→ 全站回到旧壳，`_slim_shell` 不再被调用。
3. 单条规则回滚：删掉 `_slim_shell()` 里对应一行（`_SLIM_JSONLD_RE` / `_SLIM_DESC_RE` / `_SLIM_ICON_RE` / `_collapse_tag_ws`）。
4. 产物：`site/dist` 全程未被写过（本次构建产物在 `.tmp\build-slim`），线上仍是 v0.9.5；要上线按 `AGENTS.md` §6 走 `deploy/publish.ps1`。

## 9. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 瘦身构建（不写 site/dist）
$env:SITE_OUT = '.tmp\build-slim'; & $py site/build.py          # 末尾 == done ==

# 2) 同代码基线构建（slim 强制关掉，用于证明「只有壳变了」）
$env:SITE_OUT = '.tmp\build-base'; & $py .tmp\task149\build_baseline.py

# 3) 体积
(Get-ChildItem '.tmp\build-slim' -Recurse -File | Measure-Object Length -Sum).Sum
(Get-ChildItem 'site/dist'      -Recurse -File | Measure-Object Length -Sum).Sum

# 4) 逐页比对（正文/title/canonical/hreflang）
& $py .tmp\task149\compare_dirs.py site/dist/name .tmp/build-slim/name
& $py .tmp\task149\compare_dirs.py .tmp/build-base/name .tmp/build-slim/name

# 5) 规则拆解 / 无 JS 与截图对比
& $py .tmp\task149\rule_breakdown.py
& $py .tmp\task149\nojs_compare.py
& $py .tmp\task149\shot_compare.py
```

> 上面 `.tmp\task149\*.py` 是会话语临时脚本（`.tmp/` 不入库）。等价的单行自查：
> 任取一个 name 页 `grep -c "application/ld+json\|name=\"description\"\|data:image/svg"` 应为 0 或只剩 `data:,`；
> `grep -c "<script"` 应为 3；`<title>` / `<link rel=canonical>` / `hreflang="x-default"` 各 1 条。
>
> 产物与源码一致：构建完成后只补了注释，随后用当前 `build.py` 重新渲染 3 个页（普通页 / 带双空格标题页 / 单包装 noindex 页），
> 与 `.tmp\build-slim` 里的产物 head/top/body/bottom 四段逐字节相同。

## 10. 结论与下一步

体积这一关过了：**−57.50 MiB**（目标 −45 MiB），且 LCP 目标页 0 变化、四语与无 JS 可读性、SEO 骨架（title/canonical/hreflang）全部保住。
下一步（不在本任务内）：① 构建固定 `PYTHONHASHSEED` 消除逐页 diff 噪声；② v0.9.6 的 ATC4 静态方案现在有 ~57 MiB 预算可用；③ 若还要更多体积，下一个杠杆是 `maker/`（15,213 页 / 131.9 MiB）的同类壳瘦身。
