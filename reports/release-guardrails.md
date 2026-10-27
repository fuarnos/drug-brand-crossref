# 发布护栏 + 数据质量夜间指标（2026-10-27）

> 任务：task-25（对应 `docs/谷段需求队列.md` 的「谷段发布护栏」「数据质量趋势监控」）。
> 交付：`deploy/verify_live.py`（线上 smoke）、`db/nightly_metrics.py`（夜间只读指标）、`reports/metrics/2026-10-27.json`（首份指标）、本报告。
> 约束：只写上述脚本/指标/报告与 `.tmp/guardrails/`；未改 `site/build.py`、`data/drugs.db`、`site/dist`，未跑 git、未发布。`deploy/publish.ps1` 的接入动作留给 Lead（见 §3）。

---

## 0. 结论（TL;DR）

| 项 | 结果 |
|---|---|
| 线上 smoke（当前线上 **v0.4.1**） | **33/33 项通过**，exit 0，耗时 4.4 s；JSON 存 `.tmp/guardrails/verify-live-2026-10-27.json` |
| 负例（错版本 / 站点不可达） | `--expect-version v0.4.0` → exit 1（仅 `expect-version` 失败）；不可达 base → exit 1（26 项失败） |
| 首份夜间指标 | **`reports/metrics/2026-10-27.json`（3,359 B）**，16.7 s 内写完，84 个可对比数值，无 warning（仅「无上一份，本次为基线」） |
| 指标对比/阈值逻辑 | 在 `.tmp/guardrails/metrics-sim/` 人工注入 6 种回退（产品 -9%、ATC -2pp、severe +25%、首搜 +11%、sitemap -4.8%、某国产品 -9%）→ **6 条 warnings 全部触发**，格式见 §2.4 |
| 接入建议 | `publish.ps1` push 后 smoke 改为调用 `verify_live.py`；push 前记录旧 gh-pages SHA，smoke 失败自动回滚旧 SHA 并复验（§3） |
| 本次线上关键数字 | `core.json` gzip **3,808,417 B**（本地 gzip -9 3,684,008 B，线上/本地 **1.03×**）；`sitemap.xml` **30,247** URL；页脚 `v0.4.1 · 2026-10-26` |

> 运行成本：smoke ≈5 s、约 8 次小型 GET + 2 次 HEAD；夜间指标 ≈17 s（其中 `collision` 视图 3 s、对 `index.json` 做 gzip -9 约 1.5 s），全程只读。

---

## 1. `deploy/verify_live.py` —— 线上 smoke（发布后护栏）

### 1.1 用法

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 日常/发布后：断言版本 + 对比本地构建体积，结果同时写 JSON 存档
& $py -X utf8 deploy/verify_live.py --expect-version v0.4.1 --compare-dist `
      --json-out .tmp/guardrails/verify-live-2026-10-27.json

# 其它参数
--base <URL>                  # 默认 https://fuarnos.github.io/drug-brand-crossref/
--expect-version vX           # 可省略 v；不传则只记录线上版本
--timeout 25 --retries 2      # 网络重试（5xx/超时；404/版本不符不重试）
--allow-missing-analytics     # GoatCounter 缺失降级为 warning（默认算失败）
--quiet                       # 不在 stderr 打人读摘要
```

- **stdout 永远是一个 JSON 对象**：`{ok, base_url, checked_at, expect_version, live_version, elapsed_s, checks[], failures[], warnings[]}`，每项 check 带 `name/ok/detail/ms`（warning 项带 `"warning": true` 且 `ok: true`）。
- **退出码**：`0` 通过（可带 warning）；`1` 有失败/站点不可达；`2` 参数错误。`--json-out` 同时落盘，便于 publish 流程留证。
- 所有 HTML/数据请求带 `?v=<epoch>` 破缓存 + `Accept-Encoding: gzip`；HEAD 用于大文件（不下 15 MB 正文）。

### 1.2 检查项（33 项）

| 分组 | 检查 |
|---|---|
| 首页 | 200；标题 `Medicine Brand Cross-Reference`；首搜加载提示（兼容旧版中英静态文案与 v0.4.1 的 `data-i18n="home.hint_idle"` 两种形态）；无 `preload index/core.json`；`assets/app.js?v=` 引用 |
| 版本 | 页脚 `vX.Y.Z · YYYY-MM-DD`（`--expect-version` 时断言相等）；`/es/`、`/zh/` 页脚版本一致；`whats-new.html` 顶部 `<h2>` 版本 = 页脚版本；`About` 页脚版本一致 |
| 访问统计 | 首页 `data-goatcounter="https://<code>.goatcounter.com/count"` + `gc.zgo.at/count.js`；es/zh 落地页同样有；About 含 GoatCounter 说明 + `goatcounter.com/privacy` 链接 |
| P1 索引 | `data/idx/core.json` HEAD 200、`Content-Type: application/json`、gzip 传输体积在 **2.5–6.5 MB**（明文则 11–20 MB，并告警未 gzip）；`--compare-dist` 时线上/本地 gzip -9 比值应在 **0.85–1.25×**；`data/index.json`（`?legacy=1`/解码失败回退）HEAD 200 且 gzip **4.5–7.5 MB**（明文 28–42 MB） |
| 关键页面 | `drug/tirzepatide.html`（含 tirzepatide）、`drug/atorvastatin.html`（含 atorvastatin）、`name/lipitor.html`（含 lipitor）、`confused.html`：均 200 且页内含线上版本号 |
| SEO/兜底 | `sitemap.xml` 200 且 `<url>` ≥ **25,000**；`robots.txt` 含 `Sitemap: <base>sitemap.xml`；未知路径返回 **404** |

体积阈值依据：P1 核心线上实测 3.81 MB（本机 gzip -9 3.68 MB，Pages 动态压缩 ≈×1.034），5 倍余量给未来索引增长；`index.json` 现状 6.06 MB。阈值集中在文件头常量里，调整时同步本报告。

### 1.3 实测结果（线上 v0.4.1，2026-10-27）

```
homepage-status        HTTP 200, 4,155 B
footer-version         页脚 = v0.4.1 · 2026-10-26
expect-version         期望 v0.4.1，线上 v0.4.1
whats-new-version      whats-new 顶部 v0.4.1
about-version          About 页脚 v0.4.1
analytics-script       code=drug-brand-crossref; 脚本 + count.js 存在
core-json-http         HTTP 200, content-type=application/json; charset=utf-8
core-json-size         gzip 3,808,417 B (3.81 MB)（合理区间 2,500,000–6,500,000 B）
core-size-vs-dist      线上 3,808,417 B / 本地 gzip -9 3,684,008 B = 1.03×
legacy-index-size      gzip 6,059,167 B (6.06 MB)
page-drug/tirzepatide.html   HTTP 200, 15,713 字符, 含 'tirzepatide'
page-drug/atorvastatin.html  HTTP 200, 34,543 字符
page-name/lipitor.html       HTTP 200, 2,426 字符
sitemap-urls           30,247 个 URL（下限 25,000）
404-status             未知路径 HTTP 404（应为 404）
==> live v0.4.1; 33 passed, 0 failed, 0 warnings   （exit 0，4.42 s）
```

负例验证：

```
--expect-version v0.4.0 → exit 1, failures=["expect-version"]      （版本不符必须 fail，不能静默）
--base https://…/no-such-site-xyz/ → exit 1, 26 项失败（含 homepage-status）
```

---

## 2. `db/nightly_metrics.py` —— 夜间数据质量指标（只读）

### 2.1 用法

```powershell
& $py -X utf8 db/nightly_metrics.py                    # 写 reports/metrics/<今天>.json
& $py -X utf8 db/nightly_metrics.py --date 2026-10-27  # 补跑/覆盖当天
& $py -X utf8 db/nightly_metrics.py --fail-on-warning  # 有回退 warning 时 exit 1（接计划任务用）
& $py -X utf8 db/nightly_metrics.py --out-dir <dir> --db <path> --dist <path> --print-json
```

- 只读：`sqlite3` 用 `mode=ro`；只读 `site/dist` 与 `data/drugs.db`，**不写库、不建站**。
- 退出码：`0` 指标已写（允许 warnings）；`1` 读取失败或 `--fail-on-warning` 且有 warning；`2` 参数错误。
- 与「上一份」对比 = `reports/metrics/` 中日期早于本次的最近一份 JSON（同日重跑覆盖当天文件，不会和自己比）。

### 2.2 指标口径（schema 1）

| 分组 | 字段 | 口径 |
|---|---|---|
| totals | `products/components/substances/variants/name_keys/names/aliases/nicknames/drug_terms/confusable_pairs/artg_entries/dose_warnings_published` | 各表 `COUNT(*)`；不存在的表（如当前库无 `dose_warning`）记 0，不报错 |
| countries | `<CC>.products / active_products / products_with_strength / strength_pct / variants` | `product` 按国家聚合；`strength_pct = 有 strength_value 的产品 / 产品数`（产品级去重） |
| atc | `substances / with_atc / coverage_pct` | `substance.atc` 非空占比（当前 6,081/12,790 = 47.54%） |
| collisions | `info / warning / severe / total` | `collision` 视图（自动推导，非手工） |
| duplicates | `pairs / ids / atc4_groups` | 疑似「同一成分拆成两个 id」：同 ATC 前 5 位 + `inn_en` 归一化后相同或 `inn_zh` 相同（**只读复刻** `etl/auto_merge_substances.py` 判据） |
| pages | `total_files / html_total / drug_pages / name_pages / total_bytes / sitemap_urls` | `site/dist` 文件系统扫描 + `sitemap.xml` 的 `<url>` 数 |
| sizes | `first_screen_gz / first_search_gz / core_gz / index_gz / core_raw / index_raw` | 本地 `gzip -9 (mtime=0)`：首屏 = index.html+app.js+i18n.js+style.css；首搜 = core.json+aliases.json+confused.json |
| ingest | `running / failed` | `ingest_run` 状态计数（并发入库护栏） |
| sources | `db.bytes/mtime`、`dist.files/newest_mtime` | 快照可信度 |

JSON 结构：`{schema, date, generated_at, elapsed_s, sources, metrics, compare:{prev_file, prev_date, deltas}, warnings[], ok}`。

### 2.3 回退阈值（warnings）

| 指标 | 方向 | 阈值 |
|---|---|---|
| 产品/成分/名字键/产品名/成分行 等总数、页面数、HTML 数、成分页、名字页、sitemap URL、某国产品数 | 下降 | > 1% |
| 规格覆盖率（各国）、ATC 覆盖率 | 下降 | > 1pp |
| severe / warning 碰撞数 | 变化（双向） | > 5% |
| 重复成分对数 | 上升 | > 20% |
| 首搜体积 gzip / core.json 体积 | 上升 | > 5% |
| 首屏体积 gzip | 上升 | > 10% |

另有「现场状态」warning：`site/dist` 最新文件 < 120 s（可能正在构建）、`core.json`/`index.json` 缺失、`ingest_run` 有 running（并发入库快照）。

### 2.4 首份指标 + 对比逻辑验证

首份 `reports/metrics/2026-10-27.json`（基线，无上一份 → 1 条 info warning）：

| 指标 | 值 |
|---|---|
| 产品 / 成分 / name_keys | **409,485 / 12,790 / 135,081** |
| ATC 覆盖 | 6,081 / 12,790 = **47.54%** |
| 碰撞 | info 110,609 · warning 810 · **severe 15,509** |
| 重复成分 | **27 对 / 51 个 id / 11 组** |
| 页面 | 30,248 HTML / 30,259 文件（成分页 12,380、名字页 17,861，共 158.5 MB） |
| sitemap | 30,247 URL |
| 首搜体积 | core 3,684,008 B + aliases 396,481 B → **3,702,607 B gzip**（raw 15,262,378 / 34,790,223） |
| 首屏体积 | **20,428 B gzip** |
| 各国产品 | CN 146,347 · US 110,179 · GB 61,051 · CA 43,847 · ES 25,293 · AU 11,890 · MX 10,878 |

对比/阈值验证（`.tmp/guardrails/metrics-sim/`，对 2026-10-26 基线副本注入回退，再跑 2026-10-27）：

```
WARNINGS（6）:
 - 产品总数下降: 450433 → 409485（-9.09%，阈值 1.0%）
 - ATC 覆盖率下降: 49.54 → 47.54（-4.04%，阈值 1.0pp）
 - severe 碰撞数变化: 12407 → 15509（+25.00%，阈值 5.0%）
 - 首搜体积（gzip）增加: 3332346 → 3702607（+11.11%，阈值 5.0%）
 - sitemap URL 数下降: 31759 → 30247（-4.76%，阈值 1.0%）
 - 某国产品数下降: 121196 → 110179（-9.09%，阈值 1.0%）
export ok=True, prev_file 相对路径正确, deltas=84
```

---

## 3. 接入发布流程的建议（Lead 后续改 `deploy/publish.ps1`；本任务未改）

### 3.1 发布前硬门槛（建议串成一个 preflight）

1. `& $py db/check_data.py` 正常输出；
2. 测试四套：`etl/`、`lib/`、`tests.test_mobile_inbox`、`tests/trilingual/run_tests.py` 全绿（**trilingual 较慢：本机全量 >5 min**，建议发布前跑、夜间指标不跑）；
3. 关键查询本地验证：泰诺 / 立普妥 / 替尔泊肽 / 罗沙司他 / 艾多沙班（可用 `cli.py` 或 `tests/trilingual/run_tests.py --only`）；
4. CHANGELOG 版本一致：`## vX.Y.Z — YYYY-MM-DD` 存在，且与 `site/dist` 页脚、`whats-new.html` 顶部一致（`verify_live.py --base <本地 http.server>` 也能复用）；
5. 改数据前备份 `data/drugs.db`（`run_all.py` 已自动备份最近 5 份，单独 ingest 不备份）。

### 3.2 发布后 smoke（publish.ps1 现有 homepage 检查的升级版）

建议把 publish.ps1 第 313–328 行的「Checking the homepage」替换/扩展为：

```powershell
# 1) push 之前记录旧 gh-pages SHA（用于自动回滚）
$PrevSha = (& $Git ls-remote origin refs/heads/gh-pages) -split '\s+' | Select-Object -First 1

# 2) Pages build 完成后：
& $Py -X utf8 deploy\verify_live.py --expect-version $Version --compare-dist `
      --json-out (Join-Path $tmpRoot 'verify-live-after-publish.json')
if ($LASTEXITCODE -ne 0) {
    # 3) 自动回滚：把 gh-pages 指回旧 SHA，等 Pages 重建后再跑一次 smoke
    & $Git -C $Work push --force origin "${PrevSha}:refs/heads/gh-pages"
    ... # 等 Pages build 完成（沿用现有轮询逻辑）
    & $Py -X utf8 deploy\verify_live.py --json-out (Join-Path $tmpRoot 'verify-live-after-rollback.json')
    Fail "post-publish smoke failed; rolled back to $PrevSha (see verify-live-*.json)"
}
```

- 队列（`docs/谷段需求队列.md`）已获用户认可「失败自动回滚到 gh-pages 上一个提交并验证」；`release` skill §5 要求回滚由人拍板，**建议把自动回滚严格限定在「部署类失败」**（首页/版本/关键页 404、core.json 缺失或体积异常），数据语义类问题（searched 结果不对）不自动回滚、由人决策。
- 配额：每晚最多发 3 个版本；连续 2 次发布失败即停止并写报告（队列要求，建议在 publish.ps1 外层计数）。
- `-SkipVerify` 时 smoke 也跳过（保持现有语义）。

### 3.3 夜间指标（计划任务）

```powershell
# 每晚（例如 03:30）：
& $py -X utf8 db\nightly_metrics.py --date (Get-Date -Format 'yyyy-MM-dd')
# 早报/巡检：读 reports/metrics/<昨天>.json 的 warnings[] 标红；接 cron 可加 --fail-on-warning
```

- 建议在「整点入库/建站都空闲」时跑（脚本已对 dist 新鲜度、ingest running 出 warning）。
- 首份基线已建立；之后每晚自动对比上一份，回退超阈值在早报标红。
- `reports/metrics/` 每份 ~3.4 KB，一年约 1.2 MB，建议长期保留（趋势数据）。

---

## 4. 验证证据（可复跑）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 线上 smoke（当前线上 v0.4.1，应 exit 0）
& $py -X utf8 deploy\verify_live.py --expect-version v0.4.1 --compare-dist `
      --json-out .tmp\guardrails\verify-live-2026-10-27.json

# 负例：版本不符 exit 1；base 不可达 exit 1
& $py -X utf8 deploy\verify_live.py --expect-version v0.4.0 --quiet

# 夜间指标（写 reports/metrics/YYYY-MM-DD.json）
& $py -X utf8 db\nightly_metrics.py --date 2026-10-27

# 阈值逻辑演练（写 .tmp/guardrails/metrics-sim/，不动 reports/metrics 历史）
& $py -X utf8 db\nightly_metrics.py --date 2026-10-26 --out-dir .tmp\guardrails\metrics-sim
#   …把 2026-10-26.json 的关键指标调高/调低模拟回退…
& $py -X utf8 db\nightly_metrics.py --date 2026-10-27 --out-dir .tmp\guardrails\metrics-sim
```

产物：`.tmp/guardrails/verify-live-2026-10-27.json`（33 checks 全过）、`.tmp/guardrails/metrics-sim/{2026-10-26,2026-10-27}.json`（6 warnings 演练）、`reports/metrics/2026-10-27.json`（首份基线）。

---

## 5. 已知限制 / 风险

1. **体积阈值是绝对区间**（core gzip 2.5–6.5 MB、sitemap ≥25k…），索引 P2 分片上线后 core 体积会骤降，届时需按新架构调整 `CORE_GZ_RANGE`/`SITEMAP_MIN_URLS` 并在报告登记。
2. **HEAD 依赖 CDN 行为**：GitHub Pages 返回 `Content-Length` + `Content-Encoding: gzip`（已实测）；若 CDN 变化导致 HEAD 无长度，`core-json-size` 会失败——这是期望行为（无法验证即视为护栏失效），排查时看 JSON 的 `headers`。
3. **版本正则绑页脚结构**（`<a href="whats-new.html">vX · 日期</a>`）。站点页脚改版需同步 `FOOTER_RE`；`site/build.py` 的页脚模板在 `page()` 里（L1017 附近）。
4. **GoatCounter 检查与 `.env` 有关**：未配置 `GOATCOUNTER_CODE` 时页面不注入脚本，属于预期行为，可加 `--allow-missing-analytics`（默认 fail 是为了不让统计功能静默丢失）。
5. **夜间指标是快照**：本次任务期间其他任务正在补数据，两次读取间成分 12,793→12,790、ATC 46.04%→47.54%（并发写入）。脚本已加 `ingest.running` 与 dist 新鲜度 warning；建议在空闲窗口跑。
6. **阈值是首版经验值**：产品数允许 -1% 是为正常的数据修正留余量；上线后头几晚若出现「正常波动」误报，按实际分布微调 `RULES` 并在此登记。
7. **smoke 只覆盖 HTTP 层与页面标记**，不替代真实浏览器交互、检索结果正确性（那些由 trilingual/Node DOM 桩测试覆盖）；也不检查 GoatCounter 后端数据。
8. **自动回滚未在本任务实现**：脚本只给判定与证据；publish.ps1 的接线（§3.2）由 Lead 在新任务里做，改发布脚本属于危险区，需单独评审。

---

## 6. 文件清单

| 路径 | 说明 |
|---|---|
| `deploy/verify_live.py` | 线上 smoke（368 行；JSON+退出码，`--expect-version`/`--compare-dist`/`--allow-missing-analytics`/`--json-out`） |
| `db/nightly_metrics.py` | 夜间只读指标（447 行；DB+dist → `reports/metrics/YYYY-MM-DD.json`，对比+阈值 warnings） |
| `reports/metrics/2026-10-27.json` | 首份指标（基线，3,359 B） |
| `.tmp/guardrails/verify-live-2026-10-27.json` | 线上 smoke 全量证据（33 checks） |
| `.tmp/guardrails/metrics-sim/` | 阈值/对比逻辑演练（6 warnings） |
| `reports/release-guardrails.md` | 本报告 |
