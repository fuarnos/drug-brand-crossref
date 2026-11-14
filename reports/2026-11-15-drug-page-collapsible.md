# v0.11.10 成分页每个国家/地区块可收起（K1/T35）

> 工位：site-ui　｜　任务：task-6　｜　日期：2026-11-15
> 改动：`site/build.py`（唯一源码；行尾 CRLF）＋ 本报告。未 commit / 未发布 / 未写 `site/dist`。
> 需求原话（用户 2026-11-15，截图 `/drug/amlodipine.html`）：「这个页面每个国家和地区都做成可以收起的」。

## 0. 结论（先看这 5 条）

1. **12 个市场块全部改成原生 `<details>`**（`/drug/amlodipine.html` 实测 12 个 `details.mkblock`），
   `${summary}` 保留原来的整行信息：市场 + 记录数 + 「展示 X 个，共 Y 个」+ 来源 · 数据截止 · 缺字段。
   无 JS 也能逐块点开（原生控件）。
2. **默认只展开 1 个**：`?mk=XX` 或 `#mk-XX` 时展开该市场；否则展开**第一个市场**（语言偏好市场已由
   `initListView` 置顶）。实测 `?mk=GB` → 仅 GB 展开；无参数 → 仅 CN（zh 界面第一个）展开，且
   展开块里 `.mkrow` ≥ 7 条 → **首屏条目不退化**。
3. **「全部展开 / 全部收起」**（页头下方两个按钮，只在有 JS 时显示；`html.js` 由 boot.js 打标记）：
   实测点「全部展开」→ 0 块收起，点「全部收起」→ 0 块展开。
4. **锚点 / 跨市场链接 / 打印**：点页内 `#mk-ES` 链接 → 只展开 ES；`hashchange` 同样；`beforeprint`
   → 全部展开（实测 0 块收起）。`#mk-CN` 这类 id 现在挂在 `<details>` 上，锚点仍跳到该块。
5. **硬指标未退化**（首屏守卫，1440/1920/2560 三档）：
   `items` **7 / 11 / 15**（≥5）、`AFCR 1.00`、`chrome ≤ 0.15`、`overflow 否`、
   `band_ratio` **0.67 / 0.67 / 0.66**（E6 硬条件 0.652–0.682）。改前同页型 items 8.5/11.5/16（全部展开状态）。

## 1. 改法（`site/build.py`）

| 位置 | 改动 |
|---|---|
| `_drug_list_html()` 市场块 | `<section class="mkblock" id="mk-CN"><h2>…</h2>…</section>` → `<details class="mkblock" id="mk-CN"><summary class="mkhead"><h2 class="mkhead-t">…</h2></summary>…</details>`；第一个块带 `open` |
| 同上 | 新增 `.mkctl`（全部展开 / 全部收起按钮，`data-mk-all="open|close"`），无 JS 时 CSS 隐藏 |
| `_mkblock_js()`（新） | 收起逻辑的渐进增强：`?mk=` / hash 展开对应块、默认展开第一个、全部展开/收起、锚点点击、`beforeprint`。**挂在 boot.js 尾部**（长尾页只加载这一份脚本、18 KB 可跨页缓存），不依赖 app.js |
| `APP_JS` | 同一套函数（`initMkBlocks`）也保留一份，供加载 app.js 的页面用；`document.documentElement.classList.add('js')` |
| CSS | `details.mkblock>summary.mkhead`（cursor / ▾ 指示）、`.mkctl`（`html.js` 才显示）、`@media print` 隐藏控件与指示 |

为什么放 boot.js：成分页（长尾壳）**不加载 app.js**（页面里只有 `boot.js` + `count.js`），
首次把逻辑放进 app.js 时浏览器实测「按钮点击无反应」——这是本轮踩到并修掉的坑。

## 2. before / after DOM（`/drug/amlodipine.html` 至少 3 个市场块）

```powershell
& $py reports/2026-11-15-home-slim-render.py .tmp\v01110 amlodipine     # 渲染证据产物
& $py reports/2026-11-15-home-slim-dom.py                              # 打印 ② 段
```

```html
<!-- before（site/dist v0.11.9）：12 个 <section>，全部展开 -->
<section class="mkblock" id="mk-CN" data-mk="CN"><h2>CN <span class="sub">1,047
  <span data-i18n="drug.records">records</span> · <span class="mkspec" data-total="14" data-shown="11"
  data-i18n-tpl="drug.spec_count">11 shown of 14</span></span> <span class="mkmeta" title="Source 国家医保局 …">…</span></h2>
  …（1,047 条记录一路铺开）…
</section>
<section class="mkblock" id="mk-US" data-mk="US">…</section>   ← 一起铺开

<!-- after：原生 <details>；首个市场 open，其余收起；标题仍是 h2（首屏守卫选择器 `.mkblock h2` 不失配） -->
<details class="mkblock" id="mk-CN" data-mk="CN" open><summary class="mkhead"><h2 class="mkhead-t">CN
  <span class="sub">1,047 <span data-i18n="drug.records">records</span> ·
  <span class="mkspec" data-total="14" data-shown="11" data-i18n-tpl="drug.spec_count">11 shown of 14</span></span>
  <span class="mkmeta" title="Source 国家医保局 医保药品分类与代码数据库 · Data as of 2025-04-04 …">…</span></h2></summary>
  …（展开内容：市场筛选条 / 单方·复方两段 / 未公开规格折叠 …
</details>
<details class="mkblock" id="mk-US" data-mk="US"><summary class="mkhead"><h2 class="mkhead-t">US <span class="sub">560 …</h2></summary>…</details>
<details class="mkblock" id="mk-GB" data-mk="GB"><summary class="mkhead"><h2 class="mkhead-t">GB <span class="sub">197 …</h2></summary>…</details>
…
<div class="mkctl js-only"><button type="button" data-mk-all="open" data-i18n="mk.expand_all">Expand all</button>
  <button type="button" data-mk-all="close" data-i18n="mk.collapse_all">Collapse all</button></div>
```

## 3. 真浏览器实测（MCP 浏览器 + `.tmp/v01110` 临时站点）

| 操作 | 结果 |
|---|---|
| 打开 `?mk=GB` | 只有 **GB** `open=true`（其余 11 块收起） |
| 无参数打开（zh 界面） | 只有 **CN** 展开，展开块内 `.mkrow` = 17 → 首屏条目不受影响 |
| 点「全部展开」 | 收起块数 = **0** |
| 点「全部收起」 | 展开块数 = **0** |
| 点页内 `a[href="#mk-ES"]` | 只有 **ES** 展开（锚点仍可用） |
| `hashchange` 到 `#mk-GB` | 只有 **GB** 展开 |
| 打印（`beforeprint`） | 收起块数 = **0**（全部展开） |

## 4. 硬指标（首屏守卫，改前 / 改后）

```powershell
& $py deploy/first_screen_check.py --dist .tmp/v01110 --pages home,drug `
      --viewports 1440x900,1920x1080,2560x1440 --json .tmp/v01110-final.json
```

| 指标 | 改前（site/dist）drug | 改后（本产物）drug | 门槛 |
|---|---|---|---|
| items（首屏条目） | 8.5 / 11.5 / 16 | **7 / 11 / 15** | ≥5 ✅ |
| AFCR | 1.00 / 1.00 / 1.00 | **1.00 / 1.00 / 1.00** | ≥0.50 ✅ |
| band_ratio（E6 硬条件） | 0.67 / 0.67 / 0.66 | **0.67 / 0.67 / 0.66** | 0.652–0.682 ✅ |
| chrome 占比 | 0.15 / 0.12 / 0.09 | **0.15 / 0.12 / 0.09** | ≤0.35 ✅ |
| 悬浮遮挡 | 0.000 | **0.000** | ≤0.20 ✅ |
| 正文 / 辅助字号 | 16 / 13 | **16 / 13** | ≥16 / ≥13 ✅ |
| 横向溢出 | 否 | **否** | 必须 0 ✅ |
| 6 次扫描判定 | 3 组未达（home 的 band_ratio，见 E6 报告） | **0 组不达标 / 0 项未达** | — |

⚠️ 首屏守卫的 `must_not_cover` 选择器里有 `.mkblock h2` —— 收起改造**保留了 h2 作为 summary 内的标题**，
所以这项检查继续生效（若改成纯文字，这项会静默失效）。

## 5. 四语文案（新增 2 键）

| key | en | es | zh | zh-Hant | fr |
|---|---|---|---|---|---|
| `mk.expand_all` | Expand all | Desplegar todo | 全部展开 | 全部展開 | Tout déplier |
| `mk.collapse_all` | Collapse all | Contraer todo | 全部收起 | 全部收起 | Tout replier |

`deploy/i18n_check.py`：**FAIL 0 / WARN 2 / INFO 24**（五语 631 键）。

## 6. 缺口 / 交给 Lead

1. **全量构建 + 首屏守卫全页型**由 Lead 跑：`/drug/*.html` 共 12,438 个页，本工位只渲染
   `acetaminophen` / `amlodipine` 两个做证据；`items` 保持 ≥5 的关键是「首个市场默认展开」，
   现查首个市场展开后 `.mkrow` 最少也有 7 条（1440 档）。
2. `<summary>` 里包 `<h2>` 属于「summary 内容模型之外的写法」，浏览器渲染正常、无 JS 行为一致，
   但严格 HTML 校验器会提示；保留 h2 是为了不打断首屏守卫与 a11y 的标题层级。若要严格化，
   建议后续把 `.mkblock h2` 在 `deploy/first_screen_check.py` 的选择器里换成 `.mkhead`（`deploy/` 不在本工位写权限）。
3. 折叠状态**不记忆**（刷新后回到「首个市场展开」）；若用户要「记住上次展开的市场」，需要 localStorage，
   属新需求，本轮不做。
4. 打印展开依赖 `beforeprint`（Chrome/Safari/Firefox 均支持）；极端环境不支持时，仅打印当前展开的块。
