# v0.6.3 实现报告：U1 首屏引导 / U2 各国叫法横排 / U3 界面标签本地化

> 日期：2026-10-28 ｜ 任务：`task-72` ｜ 版本：**v0.6.3**（构建产物 `.tmp/dist-u`，未发布）
> 代码：`site/build.py`（独占修改）｜ 依据：`reports/ui-u1-u3-plan.md`
> 构建：`$env:SITE_OUT='.tmp/dist-u'; python site/build.py` → `== done ==`
> 边界：未跑 git / 发布 / 写 `data/drugs.db` / 改 `site/dist`。

## 0. 结论

| 项 | 状态 | 要点 |
|---|---|---|
| **U1 首屏 3 步引导** | ✅ 完成 | 搜索框下方 3 卡（输入包装名 → 看成分/规格 → 切国家），真实示例复用 `data-q`；`×` 关闭写 `localStorage['u1.dismiss.v1']`；`page(head_js=U1_HEAD_JS)` 在 head 预置 `html.u1-off` 防 CLS；四语（en/es/zh/zh-Hant） |
| **U2 各国叫法横排** | ✅ 完成 | 结果顶部 7 国 chips（US/GB/CN/ES/MX/AU/CA），显示该国单成分条目名；无数据「未收录」；点击 = 切国家视图；**仅在唯一单成分且全量单成分命中同 sid 时显示**；复方（gaviscon）与跨国成分不同（benadryl）、模糊命中一律隐藏 |
| **U3 界面标签本地化** | ✅ 完成 | 新增 `LABEL_I18N`（剂型 13/release 4/单位 7）+ `UI_I18N`（U1/U2 文案），并入 `_merge_static_i18n`；zh-Hant 值直接写进 build.py（不依赖 JSON 是否补齐）；服务端 `_label_html/_label_join/_label_unit_html` 接入 drug/name 页；A1 明细 JS 用 `labelOf()`；`data-i18n-aria` 支持 |
| 构建/语法 | ✅ | `python site/build.py` 成功；`node --check assets/app.js` / `i18n.js` = 0 |
| DOM 测试 | ✅ 12/12 | node vm + 最小 DOM stub：U1 关闭隐藏+记忆、U2 单成分显示/复方+多结果+模糊隐藏/点击设国家、U3 四语标签+长尾兜底（脚本 `.tmp/u-plan/dom-test.js`，结果 `.tmp/dist-u/dom-test.out.txt`） |
| 四语 | ✅ | i18n.js 中 `u1.title/u2.title/form.tablet/release.ER/unit.iu` 各 4 份；zh-Hant = 錠劑/緩釋/國際單位 |
| 体积 |  | dist **57,841 文件 / 401.5 MB**（382.9 MiB）；core 27.1 MB、manifest 83 片/55.1 MB、detail 51 桶/46.9 MB（索引字段与 v0.6.2 相同，**零新增索引字段**）；i18n.js 100,109 B（v0.6.2 基线 93,947 B，**+6.2 KB raw**）；app.js 104,498 B |

## 1. U1 首屏引导

- HTML：`build_index_page()` 在 `#country` 行之后、`#loadhint` 之前插 `<section id="u1guide">`（3 步 card + `#u1close`）；四个落地页（`/`、`/es/`、`/zh/`、`/zh-hant/`）同源生成，静态副本同样带 guide（已验证 4 个 `index.html` 均含 `id="u1guide"`）。
- 防 CLS：`page()` 新增 `head_js` 参数（默认空，**只有首页**传 `U1_HEAD_JS`，不污染 5.7 万页）：`try{if(localStorage.getItem('u1.dismiss.v1')==='1')document.documentElement.className+=' u1-off';}catch(e){}`；CSS `html.u1-off #u1guide{display:none!important}`。
- 关闭：APP_JS DOM refs 区监听 `#u1close` → 写 flag + `u1El.hidden=true`；localStorage 失败（隐私模式）仍可关闭。
- 文案：`UI_I18N` 10 个 `u1.*` key ×4 语；`data-i18n-aria` 让关闭按钮 `aria-label` 本地化（i18n.js apply 新增一行）。
- 样式：`.u1guide/.u1head/.u1steps/.u1step/.u1try/.u1close`；移动端 `grid-template-columns:1fr`，关闭按钮 ≥44×44。

## 2. U2 各国叫法横排（防误配是核心）

- **唯一锚定算法** `anchorSubstance(hits, nicks)`：
  1. 取首个 `exact/compact/prefix` 命中（无则仅当唯一 hit 且非 fuzzy；昵称唯一映射也可）；
  2. 最佳命中必须是**单成分条目**（`vs` 为空或长度 1），否则返回 null；
  3. **结果集校验**：取前 20 个命中里所有「单成分条目」，若出现第二个不同 `substance_id` → 返回 null（benadryl 跨国不同成分、tylenol vs tylenol pm 这类隐藏）。
- **渲染** `countryNamesHTML(anchor, selected, T)`：一次扫描 IDX，只取「单成分且 sid=anchor」的条目，每国取「有品牌页优先 → n 大优先」；7 国 chips，缺数据 →「未收录」+ `u2.none_hint` 的 title（未收录≠没有）；当前国家 `.on` + `aria-pressed`；文案 `u2.title/hint/none/none_hint`。
- **点击**：`out` 事件委托 `[data-u2country]` → `ctry.value=code; updateCtryLabel(); render(); gcEvent('country-'+code)`，完全复用现有国家视图/URL，无新路由/参数/请求。
- 插入点：`render()` 内 `let nickHTML` 前计算 `countryBarHTML`；拼在 `parseBarHTML(...)` 之后；`partial`/`countryMiss`/模糊时为空。
- 实测边界（DOM stub 覆盖）：`gaviscon`（复方 vs=2）→ null；`benadryl`（两个不同单成分）→ null；`lipitor`（单成分）→ 显示 US/GB/CN 的 Atorvastatin/立普妥，缺 ES 等显示未收录。
- 样式：`.u2bar/.u2head/.u2chips/.u2chip(.on)`；移动端 `overflow-x:auto` 横滚、`max-width:70vw` 不撑破页面。

## 3. U3 界面标签本地化

- **单一数据源**：`LABEL_I18N = {en,es,zh,zh-Hant}`：
  - `form.*`：tablet/capsule/liquid/injection/topical/powder/suppository/inhalation/pellet/stick/kit/gas/unknown；
  - `release.*`：ER/DR/MR/none；
  - `unit.*`：iu/unit/meq/mci/ug/microgram/万iu（mg/g/ml/%/mcg/kg 保持国际写法）。
- 合并：`_merge_static_i18n` 的 sources 加 `LABEL_I18N[lang], UI_I18N[lang]`（en/es/zh）；`_install_zh_hant` 在 JSON overrides 之后用 `LABEL_I18N['zh-Hant'] + UI_I18N['zh-Hant']` 直接覆盖，避免新 key 回落简体。
- 服务端 helper（`build_drug_pages` 前）：
  - `_label_html(prefix, code, fallback)` → 受控词输出 `<span data-i18n="…">EN</span>`；长尾（含中文/西语原值如「灌肠剂」）原样 `esc` 兜底；
  - `_label_join(prefix, codes)` → 名字页 Form/Release 多值；
  - `_label_unit_html(text)` → 强度串中单位包 `data-i18n="unit.*"`（正则只替换非国际单位，数字/单位原值不动）。
- 接入：`build_drug_pages` 的 Strength 列（`st_html`）与 Release 列；`build_name_pages` 的 Form/Strength/Release；A1 `detPanelHTML` 的 status（`drug.status.*`）与 release（`labelOf('release', …)`，JS helper 未命中回退原值）。
- 其他：`page()` 的 `og:locale` 已在 v0.6.2 支持 zh-Hant（`zh_Hant`）；i18n.js 新增 `[data-i18n-aria]` 支持（U1 关闭按钮）。
- 验证：`drug/nifedipine.html` 内 `data-i18n="release.ER"` 94 处、`drug/diltiazem.html` 153 处；`name/lipitor.html` Form 段 2 个 `data-i18n="form.*"`；四语 i18n.js 键值抽查通过。

## 4. 验证记录

- `python site/build.py` → `== done ==`（耗时 ~1:45，dist 401.5 MB / 57,841 文件）。
- `node --check .tmp/dist-u/assets/app.js`、`i18n.js` → 0。
- DOM/逻辑测试（`node .tmp/u-plan/dom-test.js`）：**12/12 PASS**
  （i18n 四语·zh-Hant 用字·U1 关闭+记忆·U2 单成分渲染/复方隐藏/多结果隐藏/模糊隐藏/点击设国家·U3 release 标签/长尾兜底）。
- 静态产物检查：4 个落地页均含 `#u1guide` + `u1.dismiss.v1` head 脚本；index/core 未新增字段（U2 只用现有 `c/v/vs/u/n/d`）；`i18n zh-Hant: 286 keys (247 from json, 39 fallback zh)` —— 39 是「JSON 覆盖前」的统计，新增 key 已在 `_install_zh_hant` 用 build.py 内值显式覆盖。

## 5. 风险与遗留

1. **i18n.js +6.2 KB raw**（略高于计划 <6 KB）：因 U1/U2/LABEL 三组文案 ×4 语。可接受（首屏 gzip 后增量 <1.5 KB），若需压缩可把 LABEL 合并到现有字典或按需拆文件。
2. **U2 是启发式**：只认 exact/compact/prefix + 单成分 + 同 sid 校验；品牌查询若品牌名恰好只对应一个成分会显示（符合预期），但「多包装品牌」仍只显示每国代表名（取有页/n 大者），不是全部商品名（全部在下面结果表/国家视图）。
3. **DOM 测试是 node stub**，非真实浏览器点击/布局；375 px 横向溢出、键盘 Tab/Enter 未做真机截图，建议发布前由建站会话在 Chrome 375/768 抽检 U1 卡与 U2 横滚。
4. **zh-Hant 字典漂移**：新 key 已内嵌 build.py，但 `data/i18n_zh_hant.json` 仍是 247 键；后续字典流水线重生成时应把 LABEL/UI 的 zh-Hant 值并入 JSON（当前不影响运行）。
5. **未改 CHANGELOG / 未发布**（不在本任务写范围）；v0.6.3 发布由 Lead 按发布纪律执行（构建产物 `.tmp/dist-u` 可直接拷贝/重建）。
6. U2 未加 `rAF` 节流：`render()` 每次新查询扫一次 IDX（127k，约 3–8 ms），与现有 `inCountry` 同量级；`paintResultsOnly`（折叠/加载更多）不重算。

## 6. 证据

- 构建日志：`.tmp/dist-u-build2.log`（`== done ==`、core/manifest/detail/体积）
- DOM 测试：`.tmp/u-plan/dom-test.js` → `.tmp/dist-u/dom-test.out.txt`（12/12 PASS）
- 产物：`.tmp/dist-u/`（57,841 文件 / 401.5 MB；4 个 `index.html`、`assets/i18n.js`、`assets/app.js`）

_未改 `data/drugs.db`、未跑 git / 发布；`.tmp/dist-u` 为独立构建目录。_
