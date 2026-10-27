# dose_warning 41 条来源 AI 核验与发布决定

> 日期：2026-10-27 ｜ 任务：`task-35` ｜ 纯 AI 自动核验（无人工复核）
> 产物：`etl/verify_warnings.py`、`data/warning_verification.csv`、本报告、`.tmp/warn-verify/` 证据
> 边界：真实库 `data/drugs.db` **未被写入**（apply/rollback 只在 `.tmp/warn-verify/test.db` 副本上验证）；未跑 git / 发布 / `site/build.py`。

## 0. 结论（先说答案）

| 决定 | 条数 | 含义 |
|---|---|---|
| **promote**（→ `published`） | **40** | 来源 HTTP 200 + 权威域名 + 页面可见文本命中关键药名/查询短语 |
| **keep**（→ `draft`） | **1** | `tainuo-vs-tainuolin`：NMPA 站点程序化不可达（TLS 证书链异常；服务器对自动请求还返回 HTTP 412），域名权威 → 保留 draft、不进 `/warn` |
| **drop**（→ `retracted`） | **0** | 无永久失效/非权威来源 |

- **可发布 40 条**：38 DailyMed（NLM）+ 2 eMC（medicines.org.uk，MHRA 授权标签库）；按 rule：R1 14 / R2 10 / R6 8 / R4 4 / R5 3 / R3 1；按 severity：high 24 / medium 16。
- **唯一不可达来源 = 国家药监局（NMPA）检索首页**：`urllib` 报 `CERTIFICATE_VERIFY_FAILED`（自签证书链），独立客户端（web_fetch）访问返回 **HTTP 412 反爬**、无正文。按规则「TLS/反爬异常但域名权威 → keep」，不 drop（丢一条 CN 高严重度警示不划算；换可达来源后可重新 promote）。
- **apply 后预期**：`published 40 / draft 1 / retracted 0`；`/warn` 页只渲染 `published` 即 40 条。副本验证 **20/20 断言 PASS**（含二次 apply 幂等、rollback、从 CSV 重放、`integrity_check=ok`）。
- **建议 Lead 用 CSV 定案 apply**（不重新联网，避免来源页面漂移）：命令见 §6。

## 1. 核验规则（写入 `etl/verify_warnings.py`，可复现）

数据源：`data/seed_warnings.py` 的 41 条 `WARNINGS`；逐条取 `source_url`，`ThreadPoolExecutor(6)` 并发请求，UA 标注本项目、超时 25s、最多 800KB 正文，超时/连接类重试 1 次。

| 规则 | 判定 | 输出 |
|---|---|---|
| R-promote | HTTP 2xx + 最终域名在白名单 + **可见文本**命中 ≥1 关键药名（或完整查询短语） | `published` |
| R-keep-hitmiss | HTTP 2xx 但正文未命中（JS 渲染/检索页无结果） | `draft` |
| R-keep-antibot | HTTP 403/406/429（反爬）或 TLS 证书链异常且域名权威 | `draft` |
| R-drop-dead | HTTP 404/410、DNS/连接失败、其它 4xx/5xx、最终域名不在白名单 | `retracted` |

- 白名单（含子域）：dailymed.nlm.nih.gov / nlm.nih.gov / fda.gov / nih.gov / medlineplus.gov / ema.europa.eu / who.int / iris.who.int / **medicines.org.uk** / canada.ca / health-products.canada.ca / health.gov.au / tga.gov.au / nhsbsa.nhs.uk / gov.uk / **nmpa.gov.cn** / nhsa.gov.cn / aemps.gob.es / cima.aemps.es / gob.mx / datos.gob.mx / cofepris.gob.mx。
- 关键药名：从 URL 的 `query=`/`q=` 参数提取（如 `metoprolol tartrate` → metoprolol），NMPA 无 query → 用 `["泰诺","泰诺林","对乙酰氨基酚","paracetamol","acetaminophen"]`。
- **只看可见文本**（去 `<script>/<style>/<标签>` 后匹配），避免命中 canonical URL/script 里的字符串；`phrase_hit` 另记「完整查询短语是否出现」。
- 判定表之外的全量原始证据（http/final_url/bytes/elapsed/snippet）写入 CSV 与 `.tmp/warn-verify/validation.log`。

## 2. 结果明细

| 维度 | 分布 |
|---|---|
| decision | promote 40 / keep 1 / drop 0 |
| 域名 | dailymed.nlm.nih.gov 38、www.medicines.org.uk 2、www.nmpa.gov.cn 1 |
| HTTP | 200 40、不可达 1 |
| rule（promote） | R1 14、R2 10、R6 8、R4 4、R5 3、R3 1 |
| severity（promote） | high 24、medium 16 |
| 完整查询短语命中 | 40 / 41（NMPA 无正文） |
| 原本已是 published | 5（tylenol / benadryl / gaviscon / metoprolol / levothyroxine）→ apply 只改另外 **35** 行 |

**样例证据**（CSV `snippet` 字段摘录，已去 HTML）：

| warning_id | HTTP/域名 | 命中 | 可见文本摘录 |
|---|---|---|---|
| tylenol-vs-tainuo | 200 dailymed | tylenol | “DailyMed - Search Results for tylenol …” |
| benadryl-us-vs-uk | 200 emc | acrivastine | “… Active Ingredients acrivastine pseudoephedrine hydrochloride …” |
| gaviscon-us-vs-uk | 200 emc | gaviscon | “… Search results for gaviscon … 16 results found …” |
| metoprolol-tartrate-vs-succinate | 200 dailymed | metoprolol | “DailyMed - Search Results for metoprolol tartrate …” |
| warfarin-narrow-index | 200 dailymed | warfarin | “DailyMed - Search Results for warfarin sodium …” |

### 2.1 唯一 keep：`tainuo-vs-tainuolin`（NMPA）

- `source_url` = `https://www.nmpa.gov.cn/datasearch/home-index.html`；
- Python 请求：`SSL: CERTIFICATE_VERIFY_FAILED self-signed certificate in certificate chain`（自签证书链，属站点 TLS 配置问题，非 404）；
- 独立客户端（web_fetch）访问：**HTTP 412**（反爬拦截），无正文 → 无法做正文命中；
- 且该 URL 是**数据库检索首页**，即使可达也不一定出现「泰诺」文本；**AI 定案 keep draft**（域名权威、可浏览器人工打开、非永久失效），不 drop。
- 建议（后续任务，不属于本任务写范围）：把该条 `source_url` 换成可直达的 NMPA 药品查询结果页/说明书页（或国内权威说明书平台），再重跑 `verify_warnings.py` 即可自动 promote。

## 3. 局限与风险

1. **来源级核验 ≠ 逐句核对**：promote 只证明「来源域名权威 + 页面可见文本出现药名」，不证明 warning 的临床表述每句都被该页覆盖。40 条中 35 条由此前 draft 升级为 published，属「AI 依据来源可达性发布」。
2. DailyMed/eMC 命中的是**检索结果页**（查询词出现在标题/结果行），不是逐条标签正文；`evidence` 字段里的具体事实（盐型、释放机制）仍是策展时写的，本次未重核对。
3. 反爬/JS 页面（NMPA）无法核验；若未来更多来源改版为 JS 渲染，会批量落入 keep，需要浏览器型核验（Playwright 等）作为二期。
4. 中文关键词只覆盖 NMPA 一条；CN 来源普遍无英文键，换源时需同步维护 `KEY_TERMS_OVERRIDE`。
5. 网络时点性：CSV 记录 `checked_at`（UTC）；来源后续变化需重跑。

## 4. 副本验证（真实库未写）

| 项 | 结果 |
|---|---|
| 副本 | `.tmp/warn-verify/test.db`（`data/drugs.db` 拷贝，初始 published 5 / draft 36） |
| dry-run | 不改库；CSV 40/1/0 |
| apply | 更新 35 行（5 条原本已 published）→ **published 40 / draft 1** |
| 二次 apply | `无需更新。`（幂等） |
| rollback | 恢复 **published 5 / draft 36** |
| `--from-csv` 重放 | 不联网，重新得到 published 40 / draft 1 |
| `integrity_check` | `ok` |
| `foreign_key_check` | 有**历史既有**违规 `ingest_run rowid 32 → source 0`（验证前后一致，非本次引入，未修） |
| 断言 | **20/20 PASS**，日志 `.tmp/warn-verify/validation.log` |
| 真实库 | 只读核对仍为 published 5 / draft 36（未被脚本写） |

## 5. `/warn` 页显示口径建议

1. **只显示 `status='published'`**（本次 apply 后 40 条）；draft 不进公开页，retracted 不显示但保留可追溯。
2. 排序：`severity DESC`（high → medium）→ `rule`（R4 同名不同药置顶）→ `warning_id`；R6 治疗窗窄单独区块（设计稿已有区块 D）。
3. 每条卡片必须带：`evidence` 事实摘录 + `source_url`（rel=noopener）+ 来源机构名 + 最后核验日期（新增列或页面脚注写「来源核验：AI 自动，2026-10-27」）。
4. `/warn` 页脚注明「信息参考，不构成用药建议；同名/盐型/释放机制警示仅是身份层面，不判断个体可替换性」。
5. 上线前重跑一次 `python etl/verify_warnings.py --dry-run` 刷新 CSV（来源可达性会漂移），别直接用过期 CSV 当页面数据。

## 6. 给 Lead 的 apply 建议（真实库）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 0) 先备份
Copy-Item data\drugs.db data\backups\drugs.db.bak-20261027-warn
# 1) 复核 CSV（40 promote / 1 keep / 0 drop）与 .tmp/warn-verify/validation.log
# 2) 用已定案的 CSV apply（不重新联网，避免页面漂移）
& $py etl/verify_warnings.py --apply --db data\drugs.db `
    --from-csv data\warning_verification.csv --confirm-real-db
# 3) 核对
& $py etl/verify_warnings.py --verify --db data\drugs.db
# 预期：published 40 / draft 1 / retracted 0
# 4) 如需回滚
& $py etl/verify_warnings.py --rollback --db data\drugs.db --confirm-real-db
```

- 真实库上的 `--apply/--rollback` 必须带 `--confirm-real-db`（脚本默认拒绝），回滚备份在 `.tmp/warn-verify/backups/`（apply 前 status + apply 后 status；只还原仍等于 apply 后值的行）。
- 若想按最新网络状态重验（不推荐在发布窗口）：去掉 `--from-csv`，会重新联网并覆盖 CSV。

## 7. 证据索引（`.tmp/warn-verify/`）

| 文件 | 内容 |
|---|---|
| `validation.log` | 副本验证全过程（20/20 PASS、各命令输出、integrity/FK、真实库只读核对） |
| `warning_verification.csv` | 同一份核验结果（副本 dry-run 生成，41 行） |
| `scan_raw.json` / `seed_dump.json` | 首轮扫描原始记录 + 41 条种子全字段快照 |
| `scan.py` / `inspect.py` / `stats.py` | 扫描、抽样检查、报告统计的复现脚本 |
| `run_validation.py` | 副本验证脚本（copy → dry-run → apply → 幂等 → rollback → from-csv → integrity） |
| `backups/` | rollback CSV（warning_id, status_before, status_after） |

正式产物：`data/warning_verification.csv`（列：`warning_id,current_status,decision,target_status,reason,http_status,domain,domain_ok,key_terms,text_hits,phrase_hit,final_url,bytes,elapsed_s,snippet,checked_at`）。

_本报告为只读核验 + 副本验证产物：未写 `data/drugs.db`、未改 `site/build.py`、未跑 git / 发布。_
