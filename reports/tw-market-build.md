# v0.7.0 台湾市场接入（build.py）实现报告

> 任务：task-81（`site/build.py` 独占，v0.6.7 之后；TW 16,457 产品已在真实库）。
> `data/markets.json` / `data/languages.json` **保持 disabled、未改**；`tests/`、`data/drugs.db`、`site/dist` 均未动。
> 构建：`SITE_OUT=.tmp/dist-tw`。

## 0. 结果

| 项 | 结果 |
|---|---|
| 首页国家选项 | 四语首页（/、/es/、/zh/、/zh-hant/）新增 **TW** 选项；显示名 Taiwan / Taiwán / 台湾 / 台灣 |
| 国家选择器 / chips | `#country` 下拉与结果顶部 8 国 chips 均含 TW；按界面语言排序：en `US,GB,CA,AU,CN,ES,MX,TW`；zh `CN,TW,…`；zh-Hant `TW,CN,HK,…`；es `ES,MX,…` |
| 覆盖徽章 | 首页覆盖行含 **TW 16,457**（自动来自 `coverage` 表） |
| About | 覆盖表自动含 TW 16,457 行（数据截止 **2026-10-22**，来自 `source.tfda_tw.data_as_of`）；新增四语 `about.tw_source`：**TFDA 「全部藥品許可證資料集」（data.gov.tw 9122）/ OGDL v1.0 署名 / 週同步 / 規格由品名解析、置信度有限**；`LICENCE_HTML` 增加 Taiwan TFDA+OGDL 署名条目 |
| drug 页 | 矩阵含 TW 列（en 第 8 列、zh 第 2 列、zh-Hant 第 1 列）；国家顺序按语言（headless 实测） |
| hreflang / sitemap | 全站根页/副本新增 `hreflang="zh-TW"` 别名（指向 `/zh-hant/` 副本）；sitemap 60,219（TW 不是新语言目录，页面数不变） |
| 搜索/索引 | `country` 字段自动包含 TW（DB 驱动，无索引 schema 变更）；TW 繁体搜索沿用现有 t2s 归一化 |
| 四语 | I18N **338 keys ×4 完全一致**；无 `@@` 残留 |
| 构建 | exit 0；**60,375 文件 / 436.3 MB**（与 v0.6.7 同，TW 数据此前已在库）；maker 6,997 等页面数不变 |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| `home.tw` 四语（Taiwan / Taiwán / 台湾；zh-Hant 台灣） | 基础 I18N L142/L297/L453；zh-Hant UI L788 |
| 首页 `#country` 新增 TW 选项 | `build_index_page` L5366 |
| `U2_COUNTRIES` 加 TW + `u2Order()` 按 `window.COUNTRY_ORDER` 排 chips | APP_JS L3217–3224 / chips 生成处 |
| `COUNTRY_PRIORITY` 加 TW（矩阵默认 en 序，EXTRA 国家随后） | L4645；矩阵列顺序 L4737 |
| maker 页国家分组改用 `COUNTRY_PRIORITY` 顺序（TW 进列表；数据侧 CSV 暂无 TW MAH） | `build_maker_pages` L5245 |
| `about.tw_source`（TFDA/OGDL v1.0/截止日期/规格置信度）+ About 渲染 | ABOUT_I18N en L1044 / es L1161 / zh L1263；zh-Hant UI L789；`build_about` L5473 |
| `LICENCE_HTML` Taiwan/TFDA/OGDL 署名条目 | 许可清单 Canada 条目之后 |
| `hreflang="zh-TW"` 别名（zh-hant 副本） | `page()` alternates L3975 |
| i18n.js：`MORDER` 含 TW、暴露 `window.COUNTRY_ORDER`、国家下拉按语言重排 | L5939–5975 |
| CSS `.tag.tw`（TW 国家徽章配色） | L2151 |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-tw'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-tw\assets\app.js                      # 0
& $node --check .tmp\dist-tw\assets\i18n.js                     # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-tw'    # 30/30 PASS
# 临时 http.server 8807 + headless.mjs（Chrome CDP）→ ALL CHECKS PASSED
```

- **静态 30/30**：四语首页含 TW option 与 `home.tw`；`hreflang="zh-TW"`；首页覆盖含 TW 16,457；`.tag.tw`；
  I18N 338×4 一致且 home.tw 四语正确；about.tw_source 四语含 TFDA/OGDL/2026-10-22 与置信度说明；
  About 含 TFDA/OGDL/覆盖表 TW 16,457/许可署名；drug acetaminophen/metoprolol 矩阵含 TW 列；
  app.js 含 TW+u2Order；i18n.js 含 MORDER TW/COUNTRY_ORDER/下拉排序；sitemap 60,219；四语副本存在；抽样链接无 404；无 0 字节。
- **Headless（Chrome CDP）**：en/zh/zh-Hant 首页下拉首项分别为 US/CN/TW，TW 显示名 Taiwan/台湾/台灣；三语首页 `hreflang` 含 zh-TW；
  搜索 acetaminophen 后 chips：zh `CN,TW,…`、zh-Hant `TW,CN,…`（TW 文案 台湾/台灣）；About 可见 TFDA/OGDL/2026-10-22/TW 16,457/置信度说明；
  drug 页列顺序 en `US,…,TW`（第 8 列）、zh `CN,TW,…`（第 2 列）、zh-Hant `TW,CN,…`（第 1 列）。
- **数据核对**：`coverage` TW 16,457；`source.tfda_tw` = TFDA 全部藥品許可證資料集，OGDL v1.0，`data_as_of=2026-10-22`，weekly。

## 3. 风险 / 已知事项

1. **markets/languages 仍 disabled**：首页/选择器/chips 已由 build.py 内置支持 TW，但 `data/markets.json`、`data/languages.json` 未启用（按任务要求），正式“市场启用”与测试断言由 task-87 负责；两侧若以配置为准可能出现“UI 有 TW 但配置未启用”的过渡状态。
2. **maker 页暂无 TW 分组**：`data/maker_candidates.csv` 生成于 TW 数据入库前，TW 产品的 MAH 多数不在候选清单；build.py 已按 `COUNTRY_PRIORITY` 支持 TW，待 data 侧重跑 maker candidates 后自动出现。
3. **warn 页国家**：数据驱动（`dose_warning.country` 字符串），当前 40 条无 TW 国家值，无需改代码；未来有 TW 警示会自动显示。
4. **hreflang zh-TW**：作为 zh-Hant 的语言-地区别名附加在根页/副本，指向 `/zh-hant/` 副本；不会新增语言目录或页面。
5. **sitemap 无新增页**：TW 是国家维度不是语言目录，站点页面数不变（60,375 文件 / 60,219 sitemap URL）；TW 可见性体现在国家下拉/chips/drug 矩阵/覆盖表。
6. **覆盖数字来源**：TW 16,457 来自 `coverage` 表；About 数据截止取 `source.data_as_of`（2026-10-22）；若 data 侧重跑 source_dates，数字/日期会自动更新。
7. **繁体搜索**：TW 繁体输入依赖既有 t2s 归一化（v0.6.2 已实现），本任务未改搜索逻辑。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | 从 COUNTRY_PRIORITY/U2_COUNTRIES/下拉删除 TW；删 home.tw/about.tw_source/许可条目/hreflang zh-TW/MORDER TW/下拉排序/`.tag.tw`；maker 国家顺序恢复 sorted |
| 发布后 | gh-pages revert 上一提交（纯 UI/国家文案，无数据文件变化） |

## 5. 产物

- `site/build.py`：TW 国家/语言支持、About TFDA/OGDL、hreflang zh-TW、chips/下拉语言排序、maker 国家顺序。
- `.tmp/dist-tw/`：构建产物（60,375 文件 / 436.3 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`、`probe_tw.py`（TEMP `tw-build-verify-20261028/`）。
- `reports/tw-market-build.md`：本报告。
