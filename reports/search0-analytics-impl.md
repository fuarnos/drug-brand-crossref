# v0.8.2 零结果埋点 search0-* + 搜索词周报 实现报告

> 任务：task-112（`site/build.py` 前端 + `deploy/analytics_report.py`；`deploy/analytics_report.py` 为新增允许写范围）。
> 未改 `data/drugs.db`、markets/languages、tests、`site/dist`；构建：`SITE_OUT=.tmp/dist-search0`。

## 0. 结果

| 项 | 结果 |
|---|---|
| 零结果埋点 | 新增 `sendSearch0` 逻辑（`scheduleSearch0`）：`search0-<归一化查询>`，**同查询只发一次**（`SEARCH0_SENT` Set）、**900ms 去重/防抖**、查询截断 **≤64 字符**、空/单字符不发；挂到普通检索 / ATC 码 / 大类三个「无结果」分支；有结果保留原 `search-*` 事件 |
| 隐私说明 | `about.analytics` 四语补充「搜索词（含无结果查询）仅以聚合事件名发送——只含归一化查询文本，不与账号/IP/设备标识关联」，About/隐私链接保留 |
| 周报脚本 | `deploy/analytics_report.py` 新增 `--search-weekly`：Top 搜索词、零结果 Top、零结果词聚类（拉丁 bigram + CJK bigram Jaccard）、浏览器语言/国家维度；输出 `reports/metrics/search-weekly-YYYYMMDD.json` + `reports/search-weekly-YYYYMMDD.md`；`--self-test` 内置 fixture 自检 8/8 通过；日报新增 `search0-*` 段、`zero_result_event_implemented=True`、移除「未埋点」旧说明 |
| 验收 | `node --check` 0；静态 **23/23**；headless 全通过（无结果恰一次、重复不重发、有结果不发 search0 且 search-* 保留、单字符/空不发、长查询 64 截断、zh-Hant 页面不回归）；四语 I18N 374×4 一致；sitemap 62,720 不变 |

## 1. 改动清单

### `site/build.py`（app.js / About 文案）
| 内容 | 位置 |
|---|---|
| `scheduleSearch0`（≤64、去重、防抖、空/单字符不发） | APP_JS 搜索事件段（`SEARCH_EV` 之后） |
| 无结果调用点：普通检索末尾 / `renderATC` none / `renderCategory` no_data | render 相关分支 |
| `about.analytics` 四语隐私补充（en/es/zh + zh-Hant override） | ABOUT_I18N / BILINGUAL_I18N |

### `deploy/analytics_report.py`
| 内容 | 位置 |
|---|---|
| 搜索词/零结果周报聚合（summarize/cluster/search_weekly/render_search_md） | 新增函数（aggregate 之后） |
| `--search-weekly` / `--self-test` CLI 与输出文件 | main |
| 日报 `search0-*` 段与埋点 flag 更新 | build_report / render_md / analyze_russia |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-search0'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-search0\assets\app.js                     # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-search0' '<repo>'  # 23/23 PASS
& $py -X utf8 deploy/analytics_report.py --self-test                # 8/8 PASS
# 临时 http.server 8811 + headless.mjs（GoatCounter stub）→ ALL CHECKS PASSED
```

- **静态 23/23**：`scheduleSearch0`/`search0-`/`slice(0,64)`/`SEARCH0_SENT`/4 处调用/长度判断/900ms/`search-*` 保留；I18N 374×4 与四语隐私措辞；About 含匿名搜索词说明与 GoatCounter 隐私链接；analytics 脚本含 `--search-weekly`/`--self-test`/四个函数/输出路径/flag=True/旧「未埋点」说明移除；sitemap、无 0 字节。
- **Headless（Chrome CDP，GoatCounter stub）**：无结果 `zzzzqqqq` 恰一次 `search0-zzzzqqqq`；重复同查询不重发；有结果 `amlodipine` 不发 search0 且 `search-amlodipine` 保留；单字符/空输入不发；90 字符长查询事件截断 64；zh-Hant 页面正常加载。
- **自检**：`--self-test` 8/8（Top 搜索词、零结果 Top、次数、零结果率 62.5%、聚类合并变体、语言/国家透传）。

## 3. 风险 / 已知事项

1. **事件口径**：`search-*` 在有/无结果时都发送；零结果率 = `search0`/`search-`（近似，两者独立去重）；周报注明。
2. **语言/国家归因**：GoatCounter 事件不带页面路径，周报的「语言」用浏览器语言维度、「国家」用 locations 维度，无法精确归到 /es//zh//zh-hant/ 页面（脚本 notes 已注明）。
3. **API 字段**：按现有 GoatCounter client（stats/hits + stats/*）实现；若实际事件 path 前缀/聚合口径不同，脚本会输出空表并保留说明，需按线上数据核对一次。
4. **隐私**：只发归一化查询文本（≤64），无账号/IP/UA；About 已明示。
5. **`--search-weekly` 需 .env token**；无 token 时仅 `--self-test` 可跑（本次未联网验证真实 API）。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py deploy/analytics_report.py` 后重建/发布（Lead 执行） |
| 特性级 | 删 `scheduleSearch0`/调用点/隐私补充；analytic script 删除新函数与 CLI 分支、恢复旧说明 |
| 发布后 | gh-pages revert 上一提交（埋点为前端事件，无数据文件变化） |

## 5. 产物

- `site/build.py`：`search0-*` 埋点 + 四语隐私说明。
- `deploy/analytics_report.py`：`--search-weekly` 周报 + `--self-test`。
- `.tmp/dist-search0/`（验证构建）、`reports/analytics_report` 输出路径（未联网运行）。
- 验收脚本：`static_check.py`、`headless.mjs`（TEMP `search0-verify-20261028/`）。
- `reports/search0-analytics-impl.md`：本报告。
