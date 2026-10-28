# v0.6.2 繁体中文 UI（zh-Hant）实现报告

> 日期：2026-10-28 ｜ 任务：`task-70` ｜ 目标版本：**v0.6.2**
> 改动文件：**仅 `site/build.py`** + 新增 `data/zh_hant_t2s.json`（可选文件名已获准）。
> 未跑 git / 未发布 / 未改 `site/dist`、`data/drugs.db` 或其它跟踪文件。
> 构建：`SITE_OUT=.tmp/dist-hant` → `== done ==`（exit 0）。
> 输入：`data/i18n_zh_hant.json`（247 键，refresh 版）、`data/languages.json`（zh-Hant 预留）、
> `reports/zh-hant-i18n.md` / `zh-hant-i18n-refresh.md`、`reports/markets-integration-plan.md`。

---

## 0. 结果

| 项 | 数值 |
|---|---:|
| UI 语言 | 3 → **4**（en / es / zh / **zh-Hant**） |
| zh-Hant 字典 | **247 / 247 键**（`data/i18n_zh_hant.json`，0 键回退简体；缺键回退 zh 的机制已实现） |
| 新增静态页面 | **5**：`/zh-hant/index.html` + `about` / `confused` / `warn` / `whats-new` 副本 |
| 构建产物 | **57,840 文件 / 398.7 MB**（v0.6.1 基线 57,835 / 395.5 MB；+5 文件 / +3.2 MB） |
| sitemap | **57,693 URL**（+5，含 5 个 `/zh-hant/` 页面） |
| 繁体输入归一 | `data/zh_hant_t2s.json` **2,966 字对 / 35.3 KB**（OpenCC Apache-2.0 子集 + 1 个字补充） |
| 三语回归 | en/es/zh 字典 **247/247 值完全不变**；页面数不变（仅 +5 新语言页） |
| node --check | app.js **0** / i18n.js **0** |
| 静态验收 | **54 / 54 PASS**（副本、head、hreflang、字典、回归、sitemap、t2s） |
| DOM 抽查 | **22 / 22 PASS**（语言识别 / T / 切换跳转 / setLang） |
| HTTP 抽查 | **15 / 15 PASS**（`/zh-hant/` 页面 200 + head 标记） |

---

## 1. `site/build.py` 改动清单

> 行号是改后快照；patch 脚本在 `.tmp/hant-impl/patch_build.py`（16 处，全部断言唯一命中）。

| # | 位置（锚点） | 改动 |
|---|---|---|
| 1 | `CHANGELOG = …` 之后 | 新增 `ZH_HANT_I18N_FILE` / `ZH_HANT_T2S_FILE` 常量 + `_load_json_file` / `_load_zh_hant_dict` / `_load_zh_hant_t2s` / `_subst_placeholders`（文件缺失时降级为 `{}`，构建不炸） |
| 2 | `LANGS`（原三语） | `LANGS = [("en","EN",""),("es","ES","es/"),("zh","中文","zh/"),("zh-Hant","繁","zh-hant/")]`；新增 `LANG_PATH` / `LANG_HREFLANG`（BCP47 `zh-Hant` 与 URL 目录 `zh-hant/` 解耦）/ `LANG_ALIASES`（`zh-hant`、`zh-tw`、`zh-hk`、`zh-mo` → `zh-Hant`；`zh-hans`、`zh-cn`、`zh-sg` → `zh`）/ `LANG_META_JS`（注入 i18n.js） |
| 3 | `_merge_static_i18n` 之后 | 新增 `_install_zh_hant(values)`：**简体 zh 兜底 + JSON 覆盖 + `@@占位符@@` 替换**，写入 `I18N["zh-Hant"]`，打印 `247 keys / 0 fallback` |
| 4 | `page()` hreflang 循环 | 用 `LANG_HREFLANG[code]` + `LANG_PATH[code]` 生成 alternates（`hreflang="zh-Hant"` 指向 `…/zh-hant/`，`x-default` 仍指英文根） |
| 5 | `page()` locale 映射 | `og:locale` 增加 `zh-Hant → zh_Hant` |
| 6 | `_localize_copy()` | `<html lang>` 正则支持大写（`zh-Hant`）；canonical/og:url 用 `LANG_PATH` 生成 `…/zh-hant/<rel>`；相对链接统一加 `../` |
| 7 | `_write_with_copies()` | 遍历 `LANGS` 中所有非空 path → 写 `/es/`、`/zh/`、`/zh-hant/` 三份副本 |
| 8 | `main()` 静态字典合并处 | `_values = _i18n_placeholders(...)` → `_merge_static_i18n(_values)` → `_install_zh_hant(_values)` → 重写 `assets/i18n.js`（第二次写，含 4 语言全量字典） |
| 9 | `_render_i18n_js()` | 注入 `LANG_PATH` / `LANG_ALIAS` / `DEFAULT_LANG`；`pick()` 用 `canon()` 规范化 `?lang=`、路径首段、localStorage、`navigator.language`；`T()` 增加 **zh-Hant 缺键 → zh → en** 回退链；`langTarget()` 用 `LANG_PATH` 映射静态副本 |
| 10 | `APP_JS` DOM refs 区 | 注入 `const T2S = __T2S_JSON__;` + `toSimp()`（仅在字符串含 CJK 时逐字映射，性能友好） |
| 11 | `APP_JS` `norm()` | 改为 `toSimp(s||'').normalize('NFKC')…`（**匹配归一前做繁→简**；显示/结果不变） |
| 12 | `main()` app.js 写出处 | 从 `data/zh_hant_t2s.json` 读取映射并替换 `__T2S_JSON__`（无文件时写 `{}` 并在日志报 0 字） |
| — | `build_index_page` / 副本 docstring | 三份 → 四份（文案更新） |

**语言切换**：导航栏 `<span class="langs">` 由 `LANGS` 生成 4 个链接，`zh-Hant` 显示「繁」；`i18n.js` 点击拦截 → `setLang` → `langTarget`：
- 根入口 / `/es/` / `/zh/` / `/zh-hant/` 之间互跳对应目录；
- 首页/about/confused/warn/whats-new → 对应语言静态副本；
- 其它内容页（drug/name/combo/maker）留在原页 `?lang=zh-Hant`。

**hreflang**：首页/about/confused/warn/whats-new（根页 + 3 份副本）均输出
`en / es / zh / zh-Hant / x-default` 五条 alternate 链接；`zh-Hant` 指向 `/zh-hant/` 副本。
sitemap 由 `rglob("*.html")` 自动收录 5 个新页面。

**`<html lang>`**：`/zh-hant/` 5 个页面为 `lang="zh-Hant"`（`_localize_copy` 正则已支持大写语言码），根页仍 `en` 由 i18n.js 运行时改 `document.documentElement.lang`。

---

## 2. 繁体输入归一（`data/zh_hant_t2s.json` + app.js）

| 项 | 值 |
|---|---|
| 来源 | OpenCC `TSCharacters.txt`（Apache-2.0）BMP 单字子集，`.tmp/zh-hant/` 缓存可复现 |
| 规模 | **2,966 字对 / 35.3 KB**（task 预估 20–50 KB） |
| 补充 | `醯→酰`（OpenCC 单字表未覆盖的化学用字；台湾「乙醯」= 简体「乙酰」） |
| 注入 | 构建期读取 → `app.js` 内 `const T2S={...}`；**不新增网络请求**（app.js 增量 < 40 KB raw，gzip 后约 10 KB） |
| 生效点 | `norm()` 之前，仅用于匹配归一；输入框/解析条/页面文案保持用户原文 |
| 抽样 | `泰諾→泰诺`、`對乙醯氨基酚→对乙酰氨基酚`、`脈優→脉优`、`開瑞坦→开瑞坦`、`撲熱息痛→扑热息痛`；`普拿疼`/`立普妥` 繁简同形不变 |
| 已知边界 | 只做单字级；词级/异体（如台湾「乙醯胺酚」全词）依靠逐字映射 + DB 内已有别名（`drug_term`/`name_variant`），报告列出，不阻塞上线 |

---

## 3. 验收证据

```powershell
$env:SITE_OUT='.tmp/dist-hant'; & $py site/build.py        # exit 0，== done ==
& $node --check .tmp/dist-hant/assets/app.js               # exit 0
& $node --check .tmp/dist-hant/assets/i18n.js              # exit 0
& $py .tmp/hant-impl/verify/static_check.py                # 54 PASS / 0 FAIL
& $node .tmp/hant-impl/verify/dom_i18n.mjs                 # 22 PASS / 0 FAIL
& $py .tmp/hant-impl/verify/http_check.py                  # 15 PASS / 0 FAIL
```

- **静态 54/54**：5 个 `/zh-hant/` 页面存在、`html lang="zh-Hant"`、canonical 指向副本、`../assets` 相对资源、head title 本地化；根页 hreflang 含 `zh-Hant` 且指向 `/zh-hant/`；语言切换 4 个且含「繁」；i18n.js 4 语言、247=247 键、zh-Hant 抽样值（`nav.search=檢索`）、无 `@@占位符@@` 残留；**en/es/zh key 集合与值 247/247 与 v0.6.1 一致**；app.js 仅 t2s 相关改动（缓存戳除外）；sitemap +5；t2s 抽样转换正确。
- **DOM 22/22**：`/zh-hant/` 路径、`?lang=zh-hant`、`?lang=zh-Hant`、`navigator.language=zh-TW/zh-HK/zh-Hant` → `zh-Hant`；`zh-CN/zh-SG→zh`、`es-ES→es`、`fr-FR→en`；localStorage 记忆；`T()` 繁体值；`setLang` 跳转：根→`/zh-hant/`、about→`/zh-hant/about.html`、繁中副本→根/`/zh/about.html`、子页→`?lang=zh-Hant`。
- **HTTP 15/15**：本地 http.server 下 `/zh-hant/`（含目录索引）、4 副本、`/es/about.html`、`/zh/about.html`、`assets/i18n.js`、`assets/app.js`、`sitemap.xml` 全部 200 且关键标记齐全；zh-hant 副本 title 为繁体。
- **构建日志**：`i18n zh-Hant: 247 keys (247 from json, 0 fallback zh)`；`i18n t2s: 2,966 chars`；页数 drug 12,245 / name 29,140 / combo 9,291 / maker 6,997（与 v0.6.1 一致，无内容页回归）。

---

## 4. 风险与已知边界

| # | 风险 | 说明 / 处理 |
|---|---|---|
| R1 | **URL 目录大小写与注册表预留不一致** | 本实现按任务用 `/zh-hant/`（全小写、URL 友好）；`data/languages.json`（task-44 预留）写的是 `zh-Hant/`。**接入注册表（task-55 Phase 1）时必须二选一并同步**——建议保留小写 URL + BCP47 hreflang，只改 languages.json 的 path。当前未改 languages.json（不在写范围） |
| R2 | **i18n JSON 与 base 字典漂移** | `data/i18n_zh_hant.json` 需随 `site/build.py` 的 I18N 新键重生成（用 `.tmp/zh-hant2/build_hant_refresh.py` 同一 OpenCC+TW 流水线）。当前 247/247；未来构建日志会显示 `N fallback zh`，若 >0 说明需要 refresh（缺键回退简体，不空白） |
| R3 | 繁体字典人工复核 | `_meta.manual_review_required=true`：台湾用语优先，但专有名词/INN/许可法律表述仍需抽查（沿用 `reports/zh-hant-i18n.md` 的待办） |
| R4 | t2s 覆盖 | 单字级；词级/异体不保证。对零结果可额外靠 DB 别名层（`drug_term`/`name_variant`）；后续可加 50–200 条词级映射（同一 JSON 结构加 `phrases` 字段需要小改，不在本轮） |
| R5 | 静态副本仅 5 个根页面 | 内容页（drug/name/…）不生成 `/zh-hant/` 副本，沿用 v0.5.5 的「内容页 `?lang=`」设计；SEO 的 hreflang 只覆盖落地页，属既有约束 |
| R6 | 语言检测启发式 | `navigator.language` 的 `zh-TW/HK/MO/zh-Hant` → 繁中；`zh-CN/SG/zh` → 简中；其它 zh-* 前缀回落 `zh`。i18n.js 不主动请求地理位置 |
| R7 | localStorage 值可能是原始大小写 | `setLang('zh-hant')` 存原值，但 `pick()` 会 `canon()` 规范化（DOM 测试覆盖），不影响行为；后续可顺手统一存规范代码 |
| R8 | 体积 | +3.2 MB 主要来自 5 个副本（约 3 MB，含 About/What's new 正文）与 i18n.js 增 247 键繁体字典（约 40 KB raw）；远低于 P2 预算，无需拆包 |
| R9 | 发布纪律 | 本轮未发布/未 git；`site/dist` 未动。v0.6.2 的 CHANGELOG/build/publish/smoke 由 Lead 串行执行 |

---

## 5. 回滚

| 层次 | 操作 |
|---|---|
| 整体 | `cp .tmp/hant-impl/build.py.bak site/build.py`（改动前快照）→ 重建；3 语言恢复原样 |
| 仅 t2s | 删除 `data/zh_hant_t2s.json` → 构建继续（日志 `i18n t2s: 0 chars`），app.js 注入 `{}`，繁中输入不再归一，其余照常 |
| 仅繁中 UI | 把 `LANGS` 中 zh-Hant 元组删掉 → 4→3 语言、副本/sitemap/hreflang 自动消失（其余代码无副作用） |
| 发布后 | 按 `DEPLOY.md` 回滚 gh-pages 上一提交（本轮无发布） |

---

## 6. 下一步

1. Lead：写 CHANGELOG `## v0.6.2 — 2026-10-29`（繁体 UI P1：繁中入口/副本/hreflang/语言切换/繁体搜索归一），串行 build/publish/smoke。
2. `data/i18n_zh_hant.json` 纳入「I18N 变更 → 重生成」流程（可加到 build 前检查脚本；当前日志已有 fallback 计数）。
3. task-55 注册表接入时统一 `data/languages.json` 的 path（建议 `zh-hant/`）与 `lib/markets.py` hreflang（`zh-Hant`）。
4. TW 市场（P2）数据接入后，繁体商品名/俗名会直接可搜（t2s 只解决输入，数据本身来自市场 ETL）。
5. t2s 词级扩展（可选）：从 `.tmp/zh-hant/TW_TERMS` 与常见药名生成 50–200 条短语映射。

---

## 7. 证据文件（`.tmp/hant-impl/`）

| 文件 | 内容 |
|---|---|
| `.tmp/dist-hant/` | 构建产物（57,840 文件 / 398.7 MB） |
| `build.log` / `build2.log` | 构建日志（两次均 exit 0、`== done ==`） |
| `build.py.bak` | 改动前 `site/build.py`（回滚用） |
| `patch_build.py` | 16 处 patch 脚本（可审计替换点） |
| `build_t2s2.py` / `t2s_check.py` | t2s 生成（含 醯→酰 补充）与抽样验证 |
| `verify/static_check.py` + `.out.txt` | 54 项静态验收 |
| `verify/dom_i18n.mjs` + `.out.txt` | 22 项 DOM 桩测试 |
| `verify/http_check.py` + `.out.txt` | 15 项 HTTP 抽查 |
| `node_check.out.txt` / `metrics.json` | node --check、文件数/体积/i18n key/三语回归数字 |
| `README.md` | 证据索引 |

## 8. 参考

- `reports/zh-hant-i18n.md`、`reports/zh-hant-i18n-refresh.md`（247 键字典与台湾用词）
- `reports/ui-u1-u3-plan.md`（U3 四语言标签规划；本轮只做 UI 语言，不涉及标签映射表）
- `reports/markets-integration-plan.md`、`data/languages.json`（注册表路径/语言预留）
- `AGENTS.md`（发布纪律）、`DEPLOY.md`
