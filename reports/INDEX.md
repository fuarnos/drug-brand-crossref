# reports/ 索引

> 本文件由脚本扫描 `reports/*.md` 生成：文件名日期 + 首个标题 + 「结论」小节首句（无则取正文首段），按日期倒序。
> 新增报告后重跑生成器即可，不必手改本文件（生成器 `.tmp/docs-organizer/gen_reports_index.py`，规则见 `docs/现状.md` §5）。
> 共 **449** 份报告；「发布」列 = 发布/上线/事故类报告。无日期前缀的文件排在最后。

| 日期 | 报告 | 一句话结论 | 发布 |
|---|---|---|---|
| 2026-11-26 | [2026-11-26-v126-release.md](2026-11-26-v126-release.md) | 1. 首页改版：白底居中大标题 + 大搜索框与「查药名」按钮（参考图 docs/img/homepage-mockup-20261126.png，配色全用现有 token，零新色值）。 | 是 |
| 2026-11-26 | [2026-11-26-v125-static-pages.md](2026-11-26-v125-static-pages.md) | 一句话：把静态产品页上限抬到 144,000 并只读复算确认能取满（16 市场供给 148,814，MARKET_CAP 12,000 不必动）；pins 由 114,000 单调扩到 144,000（+30,000… |  |
| 2026-11-26 | [2026-11-26-v125-release.md](2026-11-26-v125-release.md) | === D: free space === D UsedGB 942.9 FreeGB 11 | 是 |
| 2026-11-26 | [2026-11-26-t18-t19-release-tooling.md](2026-11-26-t18-t19-release-tooling.md) | v1.2.5 发布时 A/B 只按「路径 + 大小」差分，同长度内容替换看不见：v1.2.4 → v1.2.5、2026-11-25 → 2026-11-26、 | 是 |
| 2026-11-26 | [2026-11-26-t17-nightly-metrics-check.md](2026-11-26-t17-nightly-metrics-check.md) | 1. T17 是误报：db/nightly_metrics.py L221–236 早在 v1.2.3（commit ec9e3981993） 就适配了 sitemap 索引——<sitemapindex → 逐分片… |  |
| 2026-11-26 | [2026-11-26-t10-index-sharding-design.md](2026-11-26-t10-index-sharding-design.md) | 推荐「方案 A：按文字系统把 core.json 拆成 latin / cjk / other 三片」，core.json 保留一个版本周期做旧客户端兜底，第二版起只发分片。 |  |
| 2026-11-26 | [2026-11-26-license-followup.md](2026-11-26-license-followup.md) | 一句话：今天没有新增许可；上海到期但看不到结果（需人开邮箱看一眼），荷兰确认没变，韩国还差人给邮箱登录方式。 |  |
| 2026-11-26 | [2026-11-26-h0-homepage-redesign.md](2026-11-26-h0-homepage-redesign.md) | 参考图：.tmp/homepage-mockup-20261126.png（用户提供，1536×1024） |  |
| 2026-11-25 | [2026-11-25-v124-static-pages.md](2026-11-25-v124-static-pages.md) | 自验构建：SITE_OUT=.tmp/frontend-v124，共两轮（A / A′），跑完已删除临时目录。 |  |
| 2026-11-25 | [2026-11-25-v124-release.md](2026-11-25-v124-release.md) | static pins : 114,000 pinned pids, +0 restored this build | 是 |
| 2026-11-25 | [2026-11-25-v123-sitemap-index.md](2026-11-25-v123-sitemap-index.md) | 自验构建：SITE_OUT=.tmp/frontend-v123，两轮（A / A′），跑完已删除临时目录。 |  |
| 2026-11-25 | [2026-11-25-v123-sitemap-gates.md](2026-11-25-v123-sitemap-gates.md) | 旧线上 / 旧 dist（单文件 urlset）：ci_checks 与 verify_live 判定、检查项名、阈值全部不变；verify_live 不会多出 sitemap-shards 检查（checks 数 5… | 是 |
| 2026-11-25 | [2026-11-25-v123-release.md](2026-11-25-v123-release.md) | 清单现 5 条（全部 active）：style.885ce0a604.css / boot.510d5a90dd.js（至 2026-12-20）、 | 是 |
| 2026-11-24 | [2026-11-24-v122-static-pages.md](2026-11-24-v122-static-pages.md) | 1. 静态产品页 54,176 → 84,000（+29,824，落在任务给的 +28,000…+31,000 区间）：PRODUCT_STATIC_TOP_N |  |
| 2026-11-24 | [2026-11-24-v122-release.md](2026-11-24-v122-release.md) | data/legacy_assets.json 现 4 条（全部 active）： | 是 |
| 2026-11-24 | [2026-11-24-rel6-legacy-assets.md](2026-11-24-rel6-legacy-assets.md) | rclone sync 是「镜像删除」：新版构建不再生成上一版的哈希名 → 上一版哈希文件在远端被删 → 上一版页面若还在浏览器缓存里，请求这些资源就是 404。 |  |
| 2026-11-22 | [2026-11-22-v121-static-pins.md](2026-11-22-v121-static-pins.md) | 曾发布 pid，与 v1.2.0 的 50,000 个求并集 = 54,176（差集正好 4,176，与发布 Deleted: 4,184（其中 4,176 为静态产品页）吻合）。 |  |
| 2026-11-22 | [2026-11-22-v121-release.md](2026-11-22-v121-release.md) | 静态产品页改「只增不减」：新增 data/product/static_pins.json（append-only，54,176 条），构建时 静态集 = pins ∪ 本期新选，构建结束把本期静态集并回 pins；上… | 是 |
| 2026-11-22 | [2026-11-22-v112-release.md](2026-11-22-v112-release.md) | 韩国成为第 17 个国家市场：HIRA「약가마스터」医保药价清单 97,356 条（65,086 在药价表内 / 32,270 不在），50,533 条（51.9%）有含量、全部有剂型与品目基准代码、93,779 条（… | 是 |
| 2026-11-22 | [2026-11-22-v112-kr-market.md](2026-11-22-v112-kr-market.md) | 1. KR 已注册为第 17 个国家市场（order=160、source_id=hira_kr_medprice、data_as_of=2026-08-31、 |  |
| 2026-11-22 | [2026-11-22-v111-release.md](2026-11-22-v111-release.md) | About 致谢：九语新增致谢区块（白雨舟，人名原文不译）。 | 是 |
| 2026-11-22 | [2026-11-22-v111-product-pages.md](2026-11-22-v111-product-pages.md) | 1. 每个产品一个页面（B 混合）已上线：静态 /product/<pid>.html 50,000 个（index,follow，进 sitemap）； |  |
| 2026-11-22 | [2026-11-22-v110-release.md](2026-11-22-v110-release.md) | 挪威成为第 16 个国家市场：DMP FEST 处方链数据服务 8,985 条（活动 8,778 / 停用 175 / 撤市 32；8,709 条有含量，全量有剂型与包装规格）；市场 16 → 17（16 国 + EU… | 是 |
| 2026-11-22 | [2026-11-22-no-site-registration.md](2026-11-22-no-site-registration.md) | 1. NO 已注册为第 16 个国家市场：data/markets.json order=150、source_id=dmp_fest、 |  |
| 2026-11-22 | [2026-11-22-no-ingest.md](2026-11-22-no-ingest.md) | 🟢 已入库并生效：product.country='NO' 8,985 条（第 16 个国家市场），许可 NLOD 2.0（可再发布，须署名 + 标明修改）。 |  |
| 2026-11-22 | [2026-11-22-main-conversation-idle.md](2026-11-22-main-conversation-idle.md) | 用户 2026-11-22 提出「主对话还是经常无法保持空闲」。查证后落地 5 处改动（纯文档 / prompt，无代码、无构建、无发布、无写库）： |  |
| 2026-11-22 | [2026-11-22-kr-license-assessment.md](2026-11-22-kr-license-assessment.md) | 背景：用户 2026-11-22 02:10 定 v1.2.0 = 韩国市场；本任务只做许可与可得性，不写库（入库由 backend 在获批后另派）。 | 是 |
| 2026-11-22 | [2026-11-22-kr-ingest-plan.md](2026-11-22-kr-ingest-plan.md) | 依据：reports/2026-11-22-kr-license-assessment.md（data-scout，2026-11-22）候选 B = data.go.kr 15067462（표준코드）+ 150674… |  |
| 2026-11-21 | [2026-11-21-v101-result-density.md](2026-11-21-v101-result-density.md) | 改动文件：只有 site/build.py（+10 / −4 行，结果表 CSS） |  |
| 2026-11-21 | [2026-11-21-v101-release.md](2026-11-21-v101-release.md) | 版本号唯一来源 CHANGELOG 顶部 = v1.0.1；页脚 / whats-new / Release 都从它生成（本报告写完时 tag 未打）。 | 是 |
| 2026-11-21 | [2026-11-21-no-license-assessment.md](2026-11-21-no-license-assessment.md) | 队列依据：M5「产品记录 80 万」、M2「NO / CH 只读复核」；上一轮概览见 reports/2026-11-20-data-source-scan.md §3 | 是 |
| 2026-11-21 | [2026-11-21-ch-license-assessment.md](2026-11-21-ch-license-assessment.md) | 队列依据：M5「产品记录 80 万」、M2「NO / CH 只读复核」；上一轮概览见 reports/2026-11-20-data-source-scan.md §4 | 是 |
| 2026-11-20 | [2026-11-20-v100-release.md](2026-11-20-v100-release.md) | 一句话：v1.0.0 已上线，线上 53 项门禁 0 failures，两条新门禁（assets-cache-control / longtail-footer）从发布前的 2 FAIL 转为 PASS；下一次发版预演… | 是 |
| 2026-11-20 | [2026-11-20-v0190-release.md](2026-11-20-v0190-release.md) | 验收：Lead（全量 CI 13/13、首屏守卫结论、P0 例外决定） | 是 |
| 2026-11-20 | [2026-11-20-v0180-sync-aborted.md](2026-11-20-v0180-sync-aborted.md) | 1. v0.18.0 的 R2 同步跑到 19m59s / 113,203 个文件（92%） 时被人工终止，日志收尾 ERROR: rclone exit -1；没有 upload done、没有 rclone che… | 是 |
| 2026-11-20 | [2026-11-20-v0180-my-wiring.md](2026-11-20-v0180-my-wiring.md) | _meta.versions 81→82、items 326→329、generated_at 更新；文件仍 CRLF。 | 是 |
| 2026-11-20 | [2026-11-20-v0170-release.md](2026-11-20-v0170-release.md) | 4. 只加语言、不碰数据（v0.17.0 构建时）：15 市场 / 594,781 产品不变。 | 是 |
| 2026-11-20 | [2026-11-20-v0170-cs-lv.md](2026-11-20-v0170-cs-lv.md) | 阶段 A 的附加文案表在 .tmp/extra_i18n.py（不进仓库，阶段 B 已把内容并进 build.py）。 |  |
| 2026-11-20 | [2026-11-20-v0160-release.md](2026-11-20-v0160-release.md) | 会话类型：谷段交付会话（首条消息带 【谷段交付会话】 标签） | 是 |
| 2026-11-20 | [2026-11-20-v0160-ja-merge.md](2026-11-20-v0160-ja-merge.md) | site/build.py 现查 19,415 行全 CRLF（lone LF = 0，改前 18,700 行同 CRLF）；两个 JSON 保持 CRLF；deploy/i18n_check.py 保持 LF。 |  |
| 2026-11-20 | [2026-11-20-s4-card-research.md](2026-11-20-s4-card-research.md) | 3. 这是唯一需要 Lead 拍板的一点： 需求原文写「数据走已有分片，不新增索引」。现查证明没有任何已有分片能按 substance_id 取出六块数据（core.json 是 name-key 索引；detail-… |  |
| 2026-11-20 | [2026-11-20-rel3-r2-budget-guard.md](2026-11-20-rel3-r2-budget-guard.md) | sync_r2.ps1 现在发布前读 data/r2_put_ledger.jsonl 算当月累计、并先用一次 rclone sync --dry-run（零写入）拿到 planned 数，再决定是否放行： | 是 |
| 2026-11-20 | [2026-11-20-my-license-assessment.md](2026-11-20-my-license-assessment.md) | 用户原话（2026-11-20）：「马来西亚也可以做」。对应需求队列 M7 / T46。 |  |
| 2026-11-20 | [2026-11-20-my-ingest.md](2026-11-20-my-ingest.md) | 范围：阶段 A 在临时副本库试跑；阶段 B 已在 Lead 明确说「写库窗口开」后写真实库。未 build / 未发布；site/build.py 未碰。 |  |
| 2026-11-20 | [2026-11-20-lg8-switcher-splitdose.md](2026-11-20-lg8-switcher-splitdose.md) | Jazyk / Valoda）+ _lang_label() / _lang_sep()（中日韩用「：」、其余「: 」）。没有新增 I18N 键—— |  |
| 2026-11-20 | [2026-11-20-incremental-release-refactor.md](2026-11-20-incremental-release-refactor.md) | 方案：docs/发布增量重构方案-20261120.md §3.1 + §4.1–4.4 | 是 |
| 2026-11-20 | [2026-11-20-f1f2-first-run-flow.md](2026-11-20-f1f2-first-run-flow.md) | 自验产物：.tmp/build_f1f2（干净产物，显式 SITE_OUT） |  |
| 2026-11-20 | [2026-11-20-e1-e5-home-slim-spec.md](2026-11-20-e1-e5-home-slim-spec.md) | 首屏基线（.tmp/build_ja，first_screen_check --pages home --viewports 390x844,1440x900，2026-11-20 09:04）： |  |
| 2026-11-20 | [2026-11-20-data-source-scan.md](2026-11-20-data-source-scan.md) | 用户原话（2026-11-20）：「数据部分你自己找」「马来西亚也可以做」。 |  |
| 2026-11-19 | [2026-11-19-v7b-alias-search.md](2026-11-19-v7b-alias-search.md) | （服务端 lib/search.py 实测；客户端用 Node 执行 site/build.py 里真实的 |  |
| 2026-11-19 | [2026-11-19-v7a-v7c-nickname-block.md](2026-11-19-v7a-v7c-nickname-block.md) | alias_all = nickname(396) ∪ drug_term(1,017) = 1,413 行；build 的 data/aliases.json = 1,413 + 25 条同物异名 = 1,438，与… |  |
| 2026-11-19 | [2026-11-19-v5-q18-category-results.md](2026-11-19-v5-q18-category-results.md) | 2. V5：_status_summary_html() 的折叠摘要从「第一组状态 + 前 5 个市场码 + 另有 N 个」改成「每组状态 + N 个市场」，展开态（市场码清单）不变。新增 1 个 i18n 键 atc… |  |
| 2026-11-19 | [2026-11-19-v4-v6-home-coverage.md](2026-11-19-v4-v6-home-coverage.md) | HOME_EXAMPLES.get(code) or HOME_EXAMPLES["en"]（14314 行）回落英文）。 |  |
| 2026-11-19 | [2026-11-19-v3-name-spec-rows.md](2026-11-19-v3-name-spec-rows.md) | 1. 问题确认：name/泰诺林.html（v0.13.7 产物）现在把剂型 + 规格 + 释放压成一句 209 字符的长句（不含开头 Countries: CN ·；整段 225 字符）： |  |
| 2026-11-19 | [2026-11-19-v0160-ja-i18n.md](2026-11-19-v0160-ja-i18n.md) | 口径：不新造药名/市场名（商品名与 INN 保留原文）；红线句译成「服薬助言は行いません」「互換性はありません」； |  |
| 2026-11-19 | [2026-11-19-v0150-coverage-links.md](2026-11-19-v0150-coverage-links.md) | 容错：文件缺失、字段缺失、类型不对 → 返回空 dict，该行不显示状态、构建不崩（用「去掉字段的临时 markets.json」验证 0 个状态且页面正常）。 |  |
| 2026-11-19 | [2026-11-19-v0138-v0140-release.md](2026-11-19-v0138-v0140-release.md) | 功能：KO_I18N 667 键（键集与 en 对称差 0）、/ko/ 路由 + hreflang + canonical、语言菜单「한국어」；不加市场、不写库。 | 是 |
| 2026-11-19 | [2026-11-19-v0138-release-notes-verify.md](2026-11-19-v0138-release-notes-verify.md) | 内容照 CHANGELOG.md 第一节；历史块顺序与键序一字未动（JSON 字节 diff 只增不改历史内容）。 | 是 |
| 2026-11-19 | [2026-11-19-q15-q17-cz-etl-fold.md](2026-11-19-q15-q17-cz-etl-fold.md) | reports/2026-11-18-write-window-q3q2q6.md §5 / §7.4：Q6 的 5,695 行组件只写在 |  |
| 2026-11-19 | [2026-11-19-lg3-markets-ui-languages.md](2026-11-19-lg3-markets-ui-languages.md) | 一句话：字段 + 门禁都落地了；「收了几万条数据却没有该语言界面」这件事，从此在数据层被写成显式声明、在测试层被卡住（缺字段 / 写错 / 谎报都会红）。 |  |
| 2026-11-19 | [2026-11-19-lg1-ko-merge.md](2026-11-19-lg1-ko-merge.md) | 一句话：韩语界面已并进站点，注册、键集、市场/产品计数全过；唯一未达的 i18n_check FAIL 0 卡在 |  |
| 2026-11-19 | [2026-11-19-kr-english-portal-check.md](2026-11-19-kr-english-portal-check.md) | 用户追加指令：「韩国那个网站英语版没给注册链接，你试试看英语版网站再找找看」 |  |
| 2026-11-19 | [2026-11-19-kr-account-free-sources.md](2026-11-19-kr-account-free-sources.md) | data.mfds.go.kr 文件版（同样手机真名验证）、nedrug 文件下载（已停）。 |  |
| 2026-11-18 | [2026-11-18-write-window-q3q2q6.md](2026-11-18-write-window-q3q2q6.md) | Copy-Item data\drugs.db data\backups\drugs-20261118-pre-q3q2q6.db |  |
| 2026-11-18 | [2026-11-18-v1v2-fr-entry-and-relation.md](2026-11-18-v1v2-fr-entry-and-relation.md) | 结论：两处都已改完并在临时产物上验过，site/build.py 可定稿一次构建发 v0.13.7。 |  |
| 2026-11-18 | [2026-11-18-session-type-split.md](2026-11-18-session-type-split.md) | 用户 2026-11-18 选定方案 A：新会话默认是「对接会话」，只有每日 00:30 定时任务创建的会话 |  |
| 2026-11-18 | [2026-11-18-q5-q8-deploy.md](2026-11-18-q5-q8-deploy.md) | 1. Q5 探针已换：index.html?q=%E6%B3%B0%E8%AF%BA&lang=zh → index.html?q=tylenol&lang=zh（只改 URL， | 是 |
| 2026-11-18 | [2026-11-18-q13-q7-q4-site.md](2026-11-18-q13-q7-q4-site.md) | 结论：三处全部改完并在临时产物上验过，site/build.py 可定稿；site/dist 未动、未 commit。 |  |
| 2026-11-18 | [2026-11-18-q11-first-screen-stability.md](2026-11-18-q11-first-screen-stability.md) | 1. 读数现在可复现：同一产物（site/dist = v0.13.5，今天 10:46 构建）连跑 3 次，24 组指标逐项 0 差异、 |  |
| 2026-11-18 | [2026-11-18-kr-data-source-scan.md](2026-11-18-kr-data-source-scan.md) | 结论先行：韩国官方渠道全部需要账号，其中 data.go.kr 的 API 与 data.mfds.go.kr 的文件下载都要登录； |  |
| 2026-11-18 | [2026-11-18-ko-language.md](2026-11-18-ko-language.md) | 1. 键集来源不是抄来的清单：用 deploy/i18n_check.py 的 load_build_i18n() + effective_i18n() |  |
| 2026-11-17 | [2026-11-17-v0135-release.md](2026-11-17-v0135-release.md) | 整站扫描：13,435 个成分页 → 新生成 8,165 个未公开块（与 SQL 预测一致）；0 shown of 0 0 处、残留 {u} 0 处。 | 是 |
| 2026-11-17 | [2026-11-17-v0134-release.md](2026-11-17-v0134-release.md) | r/ PUT 200（183,947 B） / | 是 |
| 2026-11-17 | [2026-11-17-v0133-release.md](2026-11-17-v0133-release.md) | 渲染范围：结果行（mktText / mktLabel）、成分页市场块头、「也在」链接（前 3 + 「另 N 个市场」展开）、复方页、矩阵列头 title / aria-label、筛选 chip title。 | 是 |
| 2026-11-17 | [2026-11-17-r7-salt-badge-fix.md](2026-11-17-r7-salt-badge-fix.md) | 1. 根因确认：site/build.py 的 Python SALT_WORDS 是 85 词，lib/search.py 是 87 词， |  |
| 2026-11-17 | [2026-11-17-r5-unpublished-block-counts.md](2026-11-17-r5-unpublished-block-counts.md) | HK 的期望值按 SQL 现查订正：HK 6 产品 / 1 MAH（ELI LILLY ASIA, INC.），不是 0 个厂家 | 是 |
| 2026-11-17 | [2026-11-17-r3-filter-panel-adaptive.md](2026-11-17-r3-filter-panel-adaptive.md) | 1. 改前的 bug 是「整页横向溢出」，不是「祖先 overflow 裁切」。 1440×900 实测：.lf-panel 的 |  |
| 2026-11-17 | [2026-11-17-r1r2-country-lang-labels.md](2026-11-17-r1r2-country-lang-labels.md) | 繁中「美國 · US」/ 法「États-Unis · US」）。名称只取现成译名（UI_I18N 的 home.<code> → |  |
| 2026-11-17 | [2026-11-17-q2-cz-substance-classify.md](2026-11-17-q2-cz-substance-classify.md) | 389 行按「判不了就留空 + 计数」留空（183 疑似 INN 未确认 + 183 规则未命中 + 23 词表误命中）。 |  |
| 2026-11-17 | [2026-11-17-q10-ui-sort-smoke.md](2026-11-17-q10-ui-sort-smoke.md) | 1. 客户端「同名下基名优先」从人工冒烟变成可复跑门禁：本机 site/dist（v0.13.2 产物）实跑 |  |
| 2026-11-16 | [2026-11-16-v0132-release.md](2026-11-16-v0132-release.md) | 结论：5/5 首条均为基名成分卡，0 console error，无空白/报错。这是客户端 JS 镜像（无 node 校验）的唯一人工门禁。 | 是 |
| 2026-11-16 | [2026-11-16-v0131-release.md](2026-11-16-v0131-release.md) | 12 次扫描，2 组 2 项未达，与 v0.13.0 完全相同；baseline 退化 0： | 是 |
| 2026-11-16 | [2026-11-16-v0130-release.md](2026-11-16-v0130-release.md) | 未达 2 项（与改前相同，baseline 退化 0）：drug@1440x900 items 4.5 未达 5、coverage@390x844 items 1.5 未达 5。 | 是 |
| 2026-11-16 | [2026-11-16-ui-surface-combo.md](2026-11-16-ui-surface-combo.md) | 结论：「复方」胶囊原来用中性底色 --surface-2:#f6f5f0 打底，而结果表数据行 tr.br 的底色也是 --surface-2 → 同色守卫（deploy/ui_surface_check.py，用户… |  |
| 2026-11-16 | [2026-11-16-trilingual-cz-lv-landing.md](2026-11-16-trilingual-cz-lv-landing.md) | 依据：task-9 设计 reports/2026-11-16-trilingual-cz-lv-design.md（只读试跑 6/6 能过） |  |
| 2026-11-16 | [2026-11-16-trilingual-cz-lv-design.md](2026-11-16-trilingual-cz-lv-design.md) | cat 只用于分组统计 / CI allowlist（:55-60 在 ci_checks.py），不影响检索逻辑。 |  |
| 2026-11-16 | [2026-11-16-site-cz-lv-wiring.md](2026-11-16-site-cz-lv-wiring.md) | 差异规模：git diff --numstat site/build.py → 139 6（+139 / −6）。文件仍是全 CRLF（CRLF=16829，孤立 LF=0），edit 工具局部替换未触发整文件行尾翻转… |  |
| 2026-11-16 | [2026-11-16-r3-adaptive-ui-research.md](2026-11-16-r3-adaptive-ui-research.md) | 1. 根因是两条叠加，不是单一 min-width： |  |
| 2026-11-16 | [2026-11-16-markets-cz-lv.md](2026-11-16-markets-cz-lv.md) | 1. ~~步骤 9 发布入口过时（写 deploy/publish.ps1）~~ → 已在本次并行修改中改为 deploy/sync_r2.ps1（唯一通道）+ verify_live，§8 末项同改。 |  |
| 2026-11-16 | [2026-11-16-m1-window-exec.md](2026-11-16-m1-window-exec.md) | Copy-Item data\drugs.db data\backups\drugs-20261115-095816.db |  |
| 2026-11-16 | [2026-11-16-l8-badge-implement.md](2026-11-16-l8-badge-implement.md) | 1. 状态胶囊 159,647 → 16,479（−89.7%），目标 16,512（差 33 个 = 0.2%，全部来自 CZ/LV 数据带来的页增长）。结构正是「该留的差异色」：已停售 12,394 + 已撤市 3… |  |
| 2026-11-16 | [2026-11-16-l8-badge-audit.md](2026-11-16-l8-badge-audit.md) | 1. 国家胶囊已经收敛到 0（旧基线 48,315 → 现查 0）：combo 静态页与结果页 marketTags() 都改成 .mktxt 纯文字（build.py 6374–6379、12581）。目标 0 已达… |  |
| 2026-11-16 | [2026-11-16-g3-salt-split.md](2026-11-16-g3-salt-split.md) | 结论：掉级根因 = 同一活性成分在 substance 表被拆成「基名行 + 盐型行」，而 CZ/LV 新数据把盐型行的产品数放大（CZ 一侧 25,270 个盐型名 active 产品，GB 仅 2,848），结果卡… |  |
| 2026-11-16 | [2026-11-16-g3-salt-fix.md](2026-11-16-g3-salt-fix.md) | 结论：达标——Top-1 93.1% → 96.1%（335 → 346 / 360）；9 条掉级查询全部回到 rank0 且含期望基名； |  |
| 2026-11-16 | [2026-11-16-cz-substance-quality.md](2026-11-16-cz-substance-quality.md) | 辅料/溶剂/化学品 20；真正 INN 侧只有 2 个命中 WHO 名录 + 192 个词形像 INN 待复核。 |  |
| 2026-11-16 | [2026-11-16-atc-category-top1.md](2026-11-16-atc-category-top1.md) | 旧期望在剔除 CZ+LV 后仍然成立（见 §2），说明这是数据窗口变化，不是实现回归。 |  |
| 2026-11-15 | [2026-11-15-v0122-l9-drug-page.md](2026-11-15-v0122-l9-drug-page.md) | 自验命令与结果：py_compile 0、i18n_check FAIL 0、node --check boot.js 0、 |  |
| 2026-11-15 | [2026-11-15-v0121-release.md](2026-11-15-v0121-release.md) | 结构固定：返回路径 → h1 → 一句话摘要（≤1 行）→ 继续搜索。 | 是 |
| 2026-11-15 | [2026-11-15-v0121-l7-r1r4.md](2026-11-15-v0121-l7-r1r4.md) | 1. L7 页头四件套落地：新增 _page_head()（返回路径 → h1 → 一句话摘要 → 继续搜索）+ |  |
| 2026-11-15 | [2026-11-15-v0118-release.md](2026-11-15-v0118-release.md) | 根因（比任务描述更深一层）：product.release='none' 表示「来源未记录」，占全库 94.4%；collision 视图按 | 是 |
| 2026-11-15 | [2026-11-15-ui-redesign-spec.md](2026-11-15-ui-redesign-spec.md) | 0) 现成基线（本工位已跑好，直接当 before 用）： |  |
| 2026-11-15 | [2026-11-15-ui-probe-before.md](2026-11-15-ui-probe-before.md) | 就绪：ready=True，索引稳定 True，#meta 显示完整索引（187 个名字命中），首屏渲染 20 行（默认每页 20 行）。 |  |
| 2026-11-15 | [2026-11-15-ui-baseline.md](2026-11-15-ui-baseline.md) | 取数窗口里 site/dist 被重建了（不是本工位干的）。时间线（全部本机时间）： |  |
| 2026-11-15 | [2026-11-15-ui-badge-convergence.md](2026-11-15-ui-badge-convergence.md) | 一句话：只有两样东西配得上颜色——「选中/主操作」（绿）和「需注意的差异」（橙红）；其余一律文字。 |  |
| 2026-11-15 | [2026-11-15-t18-t21-combo-spec.md](2026-11-15-t18-t21-combo-spec.md) | 1. H3 复方页：Dose 列从「多值斜杠串」改成每条记录一行的「剂型 · 完整成分 + 各自含量」； |  |
| 2026-11-15 | [2026-11-15-t17-inn-zh-salt-forms.md](2026-11-15-t17-inn-zh-salt-forms.md) | 结论一句话：339 条成分中文名从「盐型名」改回基础成分名（caffeine 枸橼酸咖啡因 → 咖啡因）， |  |
| 2026-11-15 | [2026-11-15-t16-release-conclusion.md](2026-11-15-t16-release-conclusion.md) | 改动文件：site/build.py（只有这一个源码文件）＋ 本报告与同目录 6 个探针脚本。 | 是 |
| 2026-11-15 | [2026-11-15-release-notes-patch.md](2026-11-15-release-notes-patch.md) | zh（可直接用 CHANGELOG 原文） | 是 |
| 2026-11-15 | [2026-11-15-m1-window-dryrun.md](2026-11-15-m1-window-dryrun.md) | 未映射 8,586 的原因分类（按 token 频次）：辅料/溶剂（SODIUM (S)-LACTATE SOLUTION 309、SOYA-BEAN OIL 138、 |  |
| 2026-11-15 | [2026-11-15-jp-wiring.md](2026-11-15-jp-wiring.md) | py_compile 0、unittest lib 61 OK、unittest etl 55 OK。 |  |
| 2026-11-15 | [2026-11-15-jp-dryrun.md](2026-11-15-jp-dryrun.md) | 结论：可以上 v0.12.0，但要先把三轮清单落地（映射行不写库、96 条新 substance 需写库窗口）。 | 是 |
| 2026-11-15 | [2026-11-15-home-slim-desktop-width.md](2026-11-15-home-slim-desktop-width.md) | 1. E6（用户「这是硬条件」）已达标：桌面 ≥1024px 内容带 = 视口 2/3 居中。首屏守卫三档 |  |
| 2026-11-15 | [2026-11-15-drug-page-collapsible.md](2026-11-15-drug-page-collapsible.md) | 1. 12 个市场块全部改成原生 <details>（/drug/amlodipine.html 实测 12 个 details.mkblock）， |  |
| 2026-11-15 | [2026-11-15-data-source-scan.md](2026-11-15-data-source-scan.md) | 能在本周开写库窗口的只有两件事：① 捷克 CZ + 拉脱维亚 LV 入库（许可最硬、ETL 已写好）② 「剂型→给药途径」规则派生（≈223,641 行，零新源）。 |  |
| 2026-11-15 | [2026-11-15-core-slim.md](2026-11-15-core-slim.md) | 改前 29 列合计 47,888,325 B；改后 28 列合计 37,854,354 B，另有顶层 mk 815,185 B、q 1,114 B。 |  |
| 2026-11-15 | [2026-11-15-batchCD-plan.md](2026-11-15-batchCD-plan.md) | 只改 site/build.py；行尾 CRLF；四语 + fr 键集一致（deploy/i18n_check.py FAIL 0）。 |  |
| 2026-11-15 | [2026-11-15-batchC-step1-L7-plan.md](2026-11-15-batchC-step1-L7-plan.md) | 新增一个共用函数 _page_head(...)，输出固定的四件套 |  |
| 2026-11-15 | [2026-11-15-batchB-results-area.md](2026-11-15-batchB-results-area.md) | 2. L3 按钮语义：「选择此产品」（原 ◎ 图标）、「查看登记详情」、「查看其余 {n} 个产品」（原 加载更多 (+10)）； |  |
| 2026-11-15 | [2026-11-15-batchB-regressions.md](2026-11-15-batchB-regressions.md) | L7 页头四件套 before（A12）： |  |
| 2026-11-14 | [2026-11-14-v0117-review-fixes.md](2026-11-14-v0117-review-fixes.md) | 首屏条目 结果页 1440=4.5 / 390=1.0、成分页 1440=8.5 / 390=5、分类页 1440=10.5（全部与改前一致），#mkchips top 257（未变），横向溢出 0。 |  |
| 2026-11-14 | [2026-11-14-v0117-release.md](2026-11-14-v0117-release.md) | B2 目标市场常驻：#mkchips（13 chip）top=257、在 #reswrap（625）之上、首屏内；#reswrap 仅 +5px（已接受噪声）。 | 是 |
| 2026-11-14 | [2026-11-14-v0117-before-baseline.md](2026-11-14-v0117-before-baseline.md) | 3. ✅ 产物漂移已澄清（Lead 2026-11-14 确认，此项已关闭）：当前 site/dist 就是线上 v0.11.6 产物 —— |  |
| 2026-11-14 | [2026-11-14-v0117-after.md](2026-11-14-v0117-after.md) | 本构建（85AFFED1…）不下「可发布」，三个理由： |  |
| 2026-11-14 | [2026-11-14-v0116-release.md](2026-11-14-v0116-release.md) | H2 = Related brand names and formula differences（原「同一品牌在其他市场的写法」）； | 是 |
| 2026-11-14 | [2026-11-14-v0116-release-notes-i18n-patch.md](2026-11-14-v0116-release-notes-i18n-patch.md) | 把下面这个块插入 data/release_notes_i18n.json 的 "_meta" 之后（必须在最前，因为发布门槛只看最新版）： | 是 |
| 2026-11-14 | [2026-11-14-v0114-wip.md](2026-11-14-v0114-wip.md) | 背景：v0.11.3 已发布（main b13dce728）；本批为 v0.11.4 前置，FR 全部 enabled:false。 |  |
| 2026-11-14 | [2026-11-14-v0114-release-tag.md](2026-11-14-v0114-release-tag.md) | 时点：2026-11-12 07:3x–07:5x 北京（America/Los_Angeles 2026-11-11 15:3x–15:5x） | 是 |
| 2026-11-14 | [2026-11-14-v0114-publish-r2.md](2026-11-14-v0114-publish-r2.md) | 结论：上传成功、verify_live 0 failures，但发现一个 verify 未覆盖的缺口：/fr/（法语落地页根路径）返回 404， | 是 |
| 2026-11-14 | [2026-11-14-v0114-build.md](2026-11-14-v0114-build.md) | 构建窗口：2026-11-12 06:41:06 → 06:45:22 北京（America/Los_Angeles 2026-11-11 14:41:06 → 14:45:22） | 是 |
| 2026-11-14 | [2026-11-14-t15-spec-lists.md](2026-11-14-t15-spec-lists.md) | 两条清单的收窄阶梯都是可复跑的，脚本把每一步命中数打出来（§4.2），所以「为什么只剩 832 行」可以当场核对。 |  |
| 2026-11-14 | [2026-11-14-t13-secondary-pages.md](2026-11-14-t13-secondary-pages.md) | 1. 成分页清单（_drug_list_html） |  |
| 2026-11-14 | [2026-11-14-t12-name-consistency.md](2026-11-14-t12-name-consistency.md) | 2. 全量扫描 80,885 个名字页：出现内部术语「碰撞」的 0 页；写法列表重复（含标题重复）0 页；「链接文字 == 同名 tag」0 页（改前 泰诺 泰诺 / 泰诺林 泰诺林 是这一条）。 |  |
| 2026-11-14 | [2026-11-14-t11-compare-plan.md](2026-11-14-t11-compare-plan.md) | 2. ?country= 现在不是筛选，是整表替换：选了国家就把候选集换成「该国该成分的全部商品名」（最多 200 条，render() 里 countryView）。这正是「点一下国家，候选集就没了」的由来——它已经… |  |
| 2026-11-14 | [2026-11-14-t11-compare-flow.md](2026-11-14-t11-compare-flow.md) | 2. B2 目标市场常驻：目标市场 chips（13 项，含「全部」）并进 #meta 那一行；桌面 1440 首屏条目 4.5 = 改前 4.5、chrome 0.292 = 改前 0.292；手机 390 首屏条目… |  |
| 2026-11-14 | [2026-11-14-t10-spec-grouping.md](2026-11-14-t10-spec-grouping.md) | 1. 分组键补上「完整成分组合」：spec = (规格, 剂型, 释放, others_sig)，others_sig = 除本页成分外的「成分@各自含量」签名（plan §2.1）。单方产品 others_sig="… |  |
| 2026-11-14 | [2026-11-14-t10-independent-review.md](2026-11-14-t10-independent-review.md) | 与我的方案不一致但可接受的三处（site-ui 收紧，均有代码注释说明）： | 是 |
| 2026-11-14 | [2026-11-14-t10-grouping-plan.md](2026-11-14-t10-grouping-plan.md) | 2. §1.2 根因是「三处规格串各自手搓，只有成分页拼了 per_volume」：per_volume_value 在 site/build.py 只出现 1 次（build_drug_pages，:9342–934… |  |
| 2026-11-14 | [2026-11-14-jp-mapping.md](2026-11-14-jp-mapping.md) | 没打到 85%，但差的那 2.6pp 不在解析，在 substance 表缺口： |  |
| 2026-11-14 | [2026-11-14-inn-zh-badge.md](2026-11-14-inn-zh-badge.md) | 构建：.tmp/v0115-build（与 task-70 增量构建同一棵源码树；未写 site/dist、未 commit） |  |
| 2026-11-14 | [2026-11-14-incremental-build.md](2026-11-14-incremental-build.md) | 1. 共享 CSS 内容哈希文件名：site/build.py 生成 |  |
| 2026-11-14 | [2026-11-14-fr-quality.md](2026-11-14-fr-quality.md) | 建议 apply（v0.11.5），但有条件： |  |
| 2026-11-14 | [2026-11-14-fr-enable.md](2026-11-14-fr-enable.md) | FR 市场 + fr 语言已启用：markets.json FR enabled:true、languages.json fr enabled:true；/fr/ 顶层页与 hreflang 已生成。 |  |
| 2026-11-14 | [2026-11-14-fr-db-window.md](2026-11-14-fr-db-window.md) | 结论：两步都成功，data/drugs.db 现有 FR 15,799 产品、总产品 494,992； |  |
| 2026-11-14 | [2026-11-14-before-baseline.md](2026-11-14-before-baseline.md) | 1. 基线锚定成功：本文所有数字来自 site/dist（mtime 2026-11-12 10:45:13，页脚 v0.11.5 · 2026-11-13，checksums.txt 在位），早于本轮任何构建；关键产… |  |
| 2026-11-14 | [2026-11-14-after-data-verify.md](2026-11-14-after-data-verify.md) | 数据层与页面一致：4 项全部 PASS，0 条硬 FAIL。 | 是 |
| 2026-11-14 | [2026-11-14-after-compare.md](2026-11-14-after-compare.md) | 37 条断言在 v0.11.5 上跑过（19 红），本次在 v0.11.6 上跑出 34 绿 / 1 红 / 2 灰。 |  |
| 2026-11-14 | [2026-11-14-after-compare.checklist.md](2026-11-14-after-compare.checklist.md) | 用法：构建到 == done == 之后照 §5 的顺序跑；每条断言给「判定表达式 + 期望值 + 改前值」，红/绿一目了然。 |  |
| 2026-11-13 | [2026-11-13-用户评审-triage.md](2026-11-13-用户评审-triage.md) | 现查：name_key = tylenol extra strength 在库有 26 个产品（全 US），其中 8 个抽样产品均为 form_base=tablet、acetaminophen 500 mg（US-5… |  |
| 2026-11-13 | [2026-11-13-v0115-smoke.md](2026-11-13-v0115-smoke.md) | 替代方法：DSH 的 MCP 浏览器（Playwright + Chromium），没有用 deploy/first_screen_check.py 的 CDP 流程，也没起 --remote-debugging-po… | 是 |
| 2026-11-13 | [2026-11-13-v0115-site.md](2026-11-13-v0115-site.md) | site/build.py 两处同句文案（diff = 8 insertions / 2 deletions，CRLF 未变）： |  |
| 2026-11-13 | [2026-11-13-v0115-release.md](2026-11-13-v0115-release.md) | 2. 「无中文名」不再误标：成分有中文名时不贴角标（商品名行不硬套）。 | 是 |
| 2026-11-13 | [2026-11-13-v0115-cache-fix.md](2026-11-13-v0115-cache-fix.md) | 引用样例（/drug/acetaminophen.html，长尾页）： |  |
| 2026-11-13 | [2026-11-13-v0114-fr-ci.md](2026-11-13-v0114-fr-ci.md) | CI PASS，可 R2。无相对 v0.11.3 的新增失败。 | 是 |
| 2026-11-13 | [2026-11-13-v0113-verify-r2.md](2026-11-13-v0113-verify-r2.md) | 结果：ok: true ・ failures: [] ・ warnings: [] ・ live_version: v0.11.3 | 是 |
| 2026-11-13 | [2026-11-13-v0113-ui.md](2026-11-13-v0113-ui.md) | 验收环境：MCP 真实浏览器（8125 服务 .tmp/v0113-build；8127 服务 site/dist 的 v0.11.2 作「改前」） |  |
| 2026-11-13 | [2026-11-13-v0113-tw-label.md](2026-11-13-v0113-tw-label.md) | 需求：首页目标市场下拉里 TW 由「台湾」改为 「中国台湾」（与「中国香港」一致）；en 保持 Taiwan、es 保持 Taiwán。 |  |
| 2026-11-13 | [2026-11-13-v0113-smoke-firstscreen.md](2026-11-13-v0113-smoke-firstscreen.md) | 文件：deploy/ui_interaction_smoke.py（git diff --stat：1 file changed, 108 insertions(+), 39 deletions(-)） |  |
| 2026-11-13 | [2026-11-13-v0113-release.md](2026-11-13-v0113-release.md) | gh-pages 备份 9c802bdf（Pages build 1361296242 built）；源码 commit 4e662d3ed（历史重写后）+ tag v0.11.3（3bc0bf05d → 73efdc… | 是 |
| 2026-11-13 | [2026-11-13-v0113-release-tag.md](2026-11-13-v0113-release-tag.md) | 执行：2026-11-12 05:3x–05:4x 北京（America/Los_Angeles 2026-11-11 13:3x–13:4x） | 是 |
| 2026-11-13 | [2026-11-13-v0113-publish-r2.md](2026-11-13-v0113-publish-r2.md) | 结论：上传成功、主域验证 0 failures —— sync_r2.ps1 exit 0（1,805.1 s）， | 是 |
| 2026-11-13 | [2026-11-13-v0113-publish-ghpages.md](2026-11-13-v0113-publish-ghpages.md) | 执行：2026-11-12 05:06:52 → 05:24:28 北京（America/Los_Angeles 2026-11-11 13:06:52 → 13:24:28） | 是 |
| 2026-11-13 | [2026-11-13-v0113-ci.md](2026-11-13-v0113-ci.md) | 1. 没有相对 v0.11.2 的新增失败，可以发布。 | 是 |
| 2026-11-13 | [2026-11-13-v0113-build.md](2026-11-13-v0113-build.md) | 构建窗口：2026-11-12 04:22:55 → 04:27:15 北京（America/Los_Angeles 2026-11-11 12:22:55 → 12:27:15） |  |
| 2026-11-13 | [2026-11-13-retag-v0113.md](2026-11-13-retag-v0113.md) | 时点：2026-11-12 06:15–06:20 北京（America/Los_Angeles 2026-11-11 14:15–14:20） |  |
| 2026-11-13 | [2026-11-13-release-notes-backfill.md](2026-11-13-release-notes-backfill.md) | 用与 deploy/i18n_check.py:parse_changelog() 相同的口径逐版对账（.tmp/check_release_notes_detail.py）： | 是 |
| 2026-11-13 | [2026-11-13-lib-atc-category-fix.md](2026-11-13-lib-atc-category-fix.md) | 1. 根因确认：CATEGORY_SNAPSHOT.aliases 是手工镜像，v0.10.3 把 66 条口语别名接进构建后 |  |
| 2026-11-13 | [2026-11-13-jp-yakka-acquisition.md](2026-11-13-jp-yakka-acquisition.md) | 数据方：厚生労働省（MHLW）。 |  |
| 2026-11-13 | [2026-11-13-jp-missing-inn.md](2026-11-13-jp-missing-inn.md) | 补齐后的映射率（逐条模拟，非拍脑袋） |  |
| 2026-11-13 | [2026-11-13-jp-kr-sources.md](2026-11-13-jp-kr-sources.md) | 推荐排期：日本 → 韩国。 理由不是数据质量（韩国字段更全、体量更大），而是落地摩擦： |  |
| 2026-11-13 | [2026-11-13-i18n-fr-gate.md](2026-11-13-i18n-fr-gate.md) | fr 在 site/build.py 里不是 {"fr": {...}} 那一层，而是两张扁平表（键就是 i18n key）： |  |
| 2026-11-13 | [2026-11-13-hotfix-republish.md](2026-11-13-hotfix-republish.md) | 时点：2026-11-12 05:51–06:12 北京（America/Los_Angeles 2026-11-11 13:51–14:12） | 是 |
| 2026-11-13 | [2026-11-13-hotfix-r2.md](2026-11-13-hotfix-r2.md) | 结论：热修已上线 —— sync exit 0（132.7 s）、rclone check 0 differences / 121,450 matching files、 | 是 |
| 2026-11-13 | [2026-11-13-hotfix-changelog-tw.md](2026-11-13-hotfix-changelog-tw.md) | 结论：已改并推送。CHANGELOG.md 的 v0.11.3 第 2 条 + data/release_notes_i18n.json 的 v0.11.3 四语第 2 条整句删除台湾表述，只保留页头竖排修复；条目数仍… |  |
| 2026-11-13 | [2026-11-13-history-rewrite.md](2026-11-13-history-rewrite.md) | 1. 远端 main 与 tag v0.11.3 已重写并推送完成，git log --all --grep='台湾' = 0， |  |
| 2026-11-13 | [2026-11-13-github-release-site-url.md](2026-11-13-github-release-site-url.md) | Lead 问「v0.11.2 Release 正文 Site 字段现在是 gh-pages，对吗？」——不对，现状是主域 + 备份： | 是 |
| 2026-11-13 | [2026-11-13-fr-quality-apply.md](2026-11-13-fr-quality-apply.md) | 给 CHANGELOG 的两个口径（别混用）： |  |
| 2026-11-13 | [2026-11-13-fr-apply-ready.md](2026-11-13-fr-apply-ready.md) | 真库护栏：_guard_real() —— 真库 + --allow-real 缺失 → SystemExit（实测真库 sha 未变，见 §4.3）。 | 是 |
| 2026-11-13 | [2026-11-13-deploy-sync-fix.md](2026-11-13-deploy-sync-fix.md) | 1. /fr/ 兜底静默失败已修：根因不是「PATH 里没有 python」，而是本机 python 解析到了 | 是 |
| 2026-11-13 | [2026-11-13-country-check-migration-ready.md](2026-11-13-country-check-migration-ready.md) | 一句话：四国已进枚举；init_db.py 的既有「枚举不一致→重建表」路径自动覆盖（幂等）； |  |
| 2026-11-13 | [2026-11-13-atc4-forms-i18n.md](2026-11-13-atc4-forms-i18n.md) | 用户报障（2026-11-12 截图，简中界面）：成分页剂型筛选 chip 与统计摘要仍是英文 |  |
| 2026-11-12 | [2026-11-12-v0116-r2-closeout-plan.md](2026-11-12-v0116-r2-closeout-plan.md) | 关键决策依据：AGENTS.md §6 已定「SITE_URL 一律写主域」+「gh-pages 上 canonical 指主域是预期行为、不跑全量 verify_live」，所以 canonical 只剩「怎么落地… | 是 |
| 2026-11-12 | [2026-11-12-v0112-verify-r2.md](2026-11-12-v0112-verify-r2.md) | 主域 core.json 可访问、内容正确、体积合规；失败仅因 R2/Cloudflare 对 gzip JSON 采用 | 是 |
| 2026-11-12 | [2026-11-12-v0112-site-ui.md](2026-11-12-v0112-site-ui.md) | 构建产物：.tmp/v0112-build（$env:SITE_OUT），未写 site/dist、未 commit、未 publish |  |
| 2026-11-12 | [2026-11-12-v0112-release.md](2026-11-12-v0112-release.md) | gh-pages 转备份（8d5c3a60d7f，Pages build 1361026906 built）。 | 是 |
| 2026-11-12 | [2026-11-12-v0112-release-tag.md](2026-11-12-v0112-release-tag.md) | 执行：2026-11-12 03:36–03:47 北京（America/Los_Angeles 2026-11-11 11:36–11:47） | 是 |
| 2026-11-12 | [2026-11-12-v0112-publish-r2.md](2026-11-12-v0112-publish-r2.md) | 结论：上传成功（exit 0，rclone check 0 differences / 121,450 matching files）， | 是 |
| 2026-11-12 | [2026-11-12-v0112-publish-ghpages.md](2026-11-12-v0112-publish-ghpages.md) | 执行：2026-11-12 02:46:57 → 03:04:26 北京（America/Los_Angeles 2026-11-11 10:46:57 → 11:04:26） | 是 |
| 2026-11-12 | [2026-11-12-v0112-ci.md](2026-11-12-v0112-ci.md) | 1. 没有 v0.11.2 新增失败。12 项里 8 项 PASS，4 项非 PASS —— 全部可解释为「既有红」或「本机环境限制」，没有一项是这一版引入的。 | 是 |
| 2026-11-12 | [2026-11-12-p0-3-removals.md](2026-11-12-p0-3-removals.md) | 2. 独立复核覆盖 45/45（换了判定思路：先定义「像药名」的白名单，再取补集，不复用 P0-3 的黑名单正则）。 |  |
| 2026-11-12 | [2026-11-12-p0-3-etl-gate.md](2026-11-12-p0-3-etl-gate.md) | 改为句中判定，规则抽到新模块 etl/alias_rules.py（抽取 + 入库共用一份）。 |  |
| 2026-11-12 | [2026-11-12-p0-3-alias-cleanup.md](2026-11-12-p0-3-alias-cleanup.md) | 1. 脏源只有一处：drug_term 的 45 行。nickname 57 行全部干净；data/substance_aliases.csv（25 组、48 个成分）全部干净——用户看到的「也叫」是 alias_al… |  |
| 2026-11-12 | [2026-11-12-p0-2-brand-field-misalignment.md](2026-11-12-p0-2-brand-field-misalignment.md) | 1. 根因：site/build.py 里渲染「结果行 → 展开明细」面板的函数 detPanelHTML()， |  |
| 2026-11-12 | [2026-11-12-p0-1-index-fields.md](2026-11-12-p0-1-index-fields.md) | 1. 根因是一处漏字段，不是「两套索引各有一套字段映射」。分片把 load_index() 的条目原样序列化（字段齐全）， |  |
| 2026-11-12 | [2026-11-12-lv-zalu-acquisition.md](2026-11-12-lv-zalu-acquisition.md) | 前置：reports/2026-11-12-eu-member-states-scan.md §12.1 / §14③（LV 判 A 类，CC0 1.0） |  |
| 2026-11-12 | [2026-11-12-fr-bdpm-acquisition.md](2026-11-12-fr-bdpm-acquisition.md) | 数据方：ANSM / HAS / CNAM（BDPM 由 ANSM 维护，base-donnees-publique.medicaments.gouv.fr）。 |  |
| 2026-11-12 | [2026-11-12-eu-member-states-scan.md](2026-11-12-eu-member-states-scan.md) | 欧盟 27 国里，现在就能「入库 + 再发布」的只有 2 个成员国：法国（FR）和捷克（CZ）。 |  |
| 2026-11-12 | [2026-11-12-early-brief.md](2026-11-12-early-brief.md) | 工作区：HEAD 0fb071072（v0.11.1 收尾）+ 本次 docs: 双通道… 提交；tag v0.11.0 / v0.11.1 均在。 |  |
| 2026-11-12 | [2026-11-12-cz-sukl-acquisition.md](2026-11-12-cz-sukl-acquisition.md) | 1. 许可：SÚKL 开放数据条款原文允许「šířit – kopírovat, distribuovat a sdělovat veřejnosti」「využívat |  |
| 2026-11-12 | [2026-11-12-core-fields-guard.md](2026-11-12-core-fields-guard.md) | 1. 新增 deploy/check_core_fields.py（只读，5 项检查，PASS 退出 0 / FAIL 退出 1，--json 落盘）。 |  |
| 2026-11-11 | [v0110-verify-20261111.md](v0110-verify-20261111.md) | 验收对象：v0.11.0 第二次全量构建产物 site/dist/（未发布） | 是 |
| 2026-11-11 | [v0110-site-eu-i18n-firstscreen-20261111.md](v0110-site-eu-i18n-firstscreen-20261111.md) | 一句话： EU 区域层的口径说明已接到用户能看到的位置（块头 + 矩阵列），四语齐；drug 390x844 的「7.0 → 6.5」经同机 A/B 证实是陈旧基线（原基线测的是一个早 20 分钟的 preview 产… |  |
| 2026-11-11 | [v0110-release-r2-20261111.md](v0110-release-r2-20261111.md) | verify_live.py --expect-version v0.11.0 32/32 项 PASS、0 failures、0 warnings；Pages 构建 built； | 是 |
| 2026-11-11 | [v0110-release-20261111.md](v0110-release-20261111.md) | 未发布。线上仍是 v0.10.3，v0.11.0 未上线、未打 tag、未建 Release。 | 是 |
| 2026-11-11 | [v0110-p0-search-country-20261111.md](v0110-p0-search-country-20261111.md) | 补充（同批 39 条查询，HEAD 版 vs 修后版）：结果卡总数都是 613 张，country=None 从 19 张（14 条查询）降到 0 张，country='EU' 从 0 张升到 19 张——只补全字段，… |  |
| 2026-11-11 | [v0110-final-build-20261111.md](v0110-final-build-20261111.md) | 构建时刻：2026-11-10 10:47:00 → 10:50:25（3 分 25 秒，America/Los_Angeles） |  |
| 2026-11-11 | [v0110-detail-buckets-eu-20261111.md](v0110-detail-buckets-eu-20261111.md) | 体积：raw +16,931,755 B（+16.1 MiB）、gzip +4,205,288 B（+4.0 MiB）；按上一版 dist 总量 |  |
| 2026-11-11 | [v0110-acceptance-r2-20261111.md](v0110-acceptance-r2-20261111.md) | 7 项门禁全部给到证据，无阻塞项。同时有 4 条已知缺口（都不是本版回归，逐条写在 §8）： |  |
| 2026-11-11 | [r2-domain-readiness-20261111.md](r2-domain-readiness-20261111.md) | R2 桶内 121,450 对象 / 898,159,644 B，与 v0.11.0 产物逐字节同口径（rclone check --size-only：0 differences / 121,450 matching… | 是 |
| 2026-11-11 | [nl-dry-run-20261111.md](nl-dry-run-20261111.md) | 不能进库。 一句话原因：GIP 数据文件没有任何再发布授权（data.overheid.nl 的 DCAT 记录把许可标为 |  |
| 2026-11-11 | [eu-ingest-write-20261111.md](eu-ingest-write-20261111.md) | _dry_run_counts() 只按「库里是否已存在」判断 name_variant，没有对同一批内两个产品共用一个商品名去重，预测 1,319 而 INSERT OR IGNORE 实际写 1,311（多算 8… |  |
| 2026-11-11 | [analytics-20261111.md](analytics-20261111.md) | 定位到候选路径：/drug-brand-crossref（该路径共 12 次；系统 {'Windows': 9, 'Linux': 2, 'iOS': 1}；浏览器 {'Chrome': 11, 'Safari': 1… |  |
| 2026-11-11 | [2026-11-11-新UI-基线.md](2026-11-11-新UI-基线.md) | 可以作对照。 采集窗口内 site/dist 就是 v0.11.0 的发布产物，未被改写： |  |
| 2026-11-11 | [2026-11-11-新UI-site-ui.md](2026-11-11-新UI-site-ui.md) | 自验构建：SITE_OUT 临时目录，未写 site/dist、未 commit、未发布 |  |
| 2026-11-11 | [2026-11-11-发布卡点-gh-pages缓存松散对象.md](2026-11-11-发布卡点-gh-pages缓存松散对象.md) | deploy/publish.ps1 在 v0.11.1 发布时卡在 git push 的对象枚举阶段 1 小时 50 分： | 是 |
| 2026-11-11 | [2026-11-11-厂商页分页体积实测.md](2026-11-11-厂商页分页体积实测.md) | 一句话：MAKER_PRODUCT_CAP 从 60 提到 120 是零风险的一行改动（+14.9 MB / 余量仍 24 MiB / 构建不变）； |  |
| 2026-11-11 | [2026-11-11-交互冒烟清单.md](2026-11-11-交互冒烟清单.md) | 1. 静态检查看不见的那一类 bug，现在有机器判据了。 两起已发生事故各对应一条硬判据： |  |
| 2026-11-11 | [2026-11-11-v0111-验收.md](2026-11-11-v0111-验收.md) | 可发布：构建到 == done ==、四语 i18n FAIL 0、ci_checks --fast PASS 7 / FAIL 0 / SKIP 5、首屏守卫无新增未达标类（atc 正文 14px → 16px、条目… |  |
| 2026-11-11 | [2026-11-11-v0111-收尾交接.md](2026-11-11-v0111-收尾交接.md) | 1. 900 MiB 软上限仍然有效：gh-pages 双活（GitHub Pages 1 GB 软上限），不能按 R2 的 10 GiB 放宽。 |  |
| 2026-11-11 | [2026-11-11-r2-closeout.md](2026-11-11-r2-closeout.md) | 时点：2026-11-10 13:20–13:30 America/Los_Angeles（北京时间 2026-11-11 05:20–05:30） | 是 |
| 2026-11-11 | [2026-11-11-nl-license-assessment.md](2026-11-11-nl-license-assessment.md) | 依据：docs/欧盟抓取-20261111.md §2.2 / §4 第 1 步；AGENTS.md §4「许可先行」 | 是 |
| 2026-11-11 | [2026-11-11-closeout.md](2026-11-11-closeout.md) | 唯一未闭环的是换托管：新域名 drugcrossref.com 已绑 R2 自定义域（Active / Access Enabled），但 .env 的 R2_SECRET_ACCESS_KEY 只有 62 位（R2… | 是 |
| 2026-11-11 | [2026-11-11-cbg-meb-letter-sent.md](2026-11-11-cbg-meb-letter-sent.md) | 关键区分（写进所有文档的同一句话）： |  |
| 2026-11-11 | [2026-11-11-UI批前置事实.md](2026-11-11-UI批前置事实.md) | 每行字节取自 dist 实测线性估计：1–5 行页中位 6,353 B、近满（59–60 行）页中位 19,086 B ⇒ ≈220 B/行（含表格包裹）。dist 余量：900 MiB 自设上限 943,718,40… |  |
| 2026-11-10 | [v0103-search-impl-20261110.md](v0103-search-impl-20261110.md) | 三语 72 例 / 354 查询 通过 69 ≥ 门槛 68、跨国 72/72、Top-5 98.6%（3 条失败全在 |  |
| 2026-11-10 | [v0103-build-impl-20261110.md](v0103-build-impl-20261110.md) | 1. v0.10.3 三件交付全部落地并构建过：桌面内容带 2/3（task-17）、成分页换「按国家分组清单」（task-16）、 |  |
| 2026-11-10 | [v0102-ui-surface-20261110.md](v0102-ui-surface-20261110.md) | 用户 2026-11-10 硬规则：「框内颜色和框外颜色不许能一致」。任何嵌套表面（面板里的输入框、 |  |
| 2026-11-10 | [v0102-impl-20261110.md](v0102-impl-20261110.md) | 净效果（本地 gzip -6，与审计同口径） |  |
| 2026-11-10 | [v0102-i18n-gate-20261110.md](v0102-i18n-gate-20261110.md) | data-i18n 引用 188 处、服务端直取 16 处，没有一处指向不存在的 key。所以「西语滞后」不是字典缺键造成的。 |  |
| 2026-11-10 | [v0102-build-impl-20261110.md](v0102-build-impl-20261110.md) | deploy/i18n_check.py FAIL 0 / WARN 5（exit 0，WARN 全是历史欠账，见 §5）。 |  |
| 2026-11-10 | [v0102-acceptance-20261110.md](v0102-acceptance-20261110.md) | 真浏览器（冷缓存）实测首页首屏请求（gzip，逐请求累加，见 .tmp/qa-v0102/size-new.json）： |  |
| 2026-11-10 | [v0101-acceptance-20261110.md](v0101-acceptance-20261110.md) | assets/i18n.js 仍为四语完整字典（['en','es','zh','zh-Hant']），非首页页面行为不变。 |  |
| 2026-11-10 | [search-discovery-audit-20261110.md](search-discovery-audit-20261110.md) | 一句话：三个都能做，都不碰数据层。#2 / #3 是一个低风险提交；#1 收益最大（12.7 s → 0.06 s 量级）但要重写首查路径，单独提交并保留今天的 core.json 回退。 |  |
| 2026-11-10 | [perf-mobile-audit-20261110.md](perf-mobile-audit-20261110.md) | en 用户（浏览器语言与页面内联字典一致） |  |
| 2026-11-10 | [matrix-presentation-20261110.md](matrix-presentation-20261110.md) | brief 里的「74 个同成分同国家 g/mg 并存且数值等价」——74 这个数能复现，但它不是「等价」： |  |
| 2026-11-10 | [matrix-form-decision-20261110.md](matrix-form-decision-20261110.md) | site/build.py L7921 的 country_totals 数的是「每国名字格总数」，不是「有强度的记录数」； |  |
| 2026-11-10 | [manufacturer-site-feasibility-20261110.md](manufacturer-site-feasibility-20261110.md) | 6 个站点、覆盖 2 个中国市场品牌（力度伸、泰诺，符合「≥2 个中国市场」要求）： |  |
| 2026-11-10 | [form-normalize-v2-dryrun-20261110.md](form-normalize-v2-dryrun-20261110.md) | 一句话：四条规则一共 23,890 行（占 477,098 的 5.0%），全部由来源原文派生、无人工标注；泡腾 948 行达标、注射剂/粉剂误判按审计口径归零、AU/SG 释放机制冲突归零、R2 回退归零；副本上 a… |  |
| 2026-11-10 | [form-normalize-v2-apply-20261110.md](form-normalize-v2-apply-20261110.md) | apply 成功。 23,890 行按 dry-run 批准的范围写入，一条不多一条不少（journal 逐行可回滚）；四条规则与 dry-run 报告逐项一致，六项审计指标全部落在预期值：R1 conflict 20… |  |
| 2026-11-10 | [form-effervescent-20261110.md](form-effervescent-20261110.md) | 一句话：新增 effervescent 一个剂型 class（方案 A），判定规则来自来源原文的泡腾字样（7 种拼写），全库只动 948 行产品（0.199%），不手工标注任何一条。 |  |
| 2026-11-10 | [consistency-audit-identity-20261110.md](consistency-audit-identity-20261110.md) | 8 条规则跑完，6 条有实质命中，合计 43,324 条/组（R1 23,595 + R2 86 + R3 9,534 + R4 6,114 + R6 584 + R8 3,411；R5、R7 为 0）。 |  |
| 2026-11-10 | [consistency-audit-form-20261110.md](consistency-audit-form-20261110.md) | 全库 477,098 个 product / 628,013 个成分行，七条规则命中如下 |  |
| 2026-11-10 | [ci-speedup-20261110.md](ci-speedup-20261110.md) | fast 的 PASS 数从 8 → 7 只是因为 unittest:lib-atc-category（47 s）挪到全量了， |  |
| 2026-11-10 | [atc-status-aggregation-20261110.md](atc-status-aggregation-20261110.md) | 1. 现象不是「同一状态重复出现」，而是「最多 4 个不同状态各挂一枚徽章，且不写国家」。 |  |
| 2026-11-10 | [2026-11-10-域名上线准备.md](2026-11-10-域名上线准备.md) | 用户已拍板：独立域名 drugcrossref.com + Cloudflare Registrar + Cloudflare R2 静态托管（自定义域），零服务器、零月费；旧 gh-pages 保留 30 天回滚。卡… | 是 |
| 2026-11-10 | [2026-11-10-impeccable-detect-取证.md](2026-11-10-impeccable-detect-取证.md) | 1. 6 个构建产物的源码扫描全部为 []（exit 0），包含任务里点名的 index.html，复现成功。 |  |
| 2026-11-10 | [2026-11-10-UI外挂与首页评审.md](2026-11-10-UI外挂与首页评审.md) | results@390 报「首屏条目 0.0 + first-result 未完整可见」，与截图矛盾。 .tmp/fs_shots/fs-results-390x844.png 里第一张身份卡（泰诺 → 四个成分、规格… |  |
| 2026-11-10 | [2026-11-10-UI修复可行性评估.md](2026-11-10-UI修复可行性评估.md) | 2. zh-Hant 生成链在 .tmp。 任何新键都必须同步进繁体，否则 i18n_check FAIL（"缺译不许静默回落英文"是用户 2026-11-10 定的规则）。生成器在，能跑；但它不在仓库里，属于必须补的… |  |
| 2026-11-09 | [dsh-preset-reset-20261109.md](dsh-preset-reset-20261109.md) | 预设本身没坏，是 profile 的 bundle 列表被桌面端的崩溃自愈机制重置了： |  |
| 2026-11-07 | [ui-batch-b-20261107.md](ui-batch-b-20261107.md) | 2. 首页类别：_home_cat_chips() 只出 8 个高频类别（2×4 chip 网格）+「全部类别 →」链到 /atc.html；其余类别保留在顶部「按类别」面板（全 16 个）。 |  |
| 2026-11-07 | [ui-batch-a2-20261107.md](ui-batch-a2-20261107.md) | 六项必做全部落地：桌面 5 项导航 + <details> 面板、移动底栏 4 tab + 语言常显、六类触控目标 ≥44px、名字页「不可互换」警示 + 首屏 ≤3 卡、成分页固定层级（H1 → 身份行 → 矩阵 →… |  |
| 2026-11-07 | [ui-batch-a1-20261107.md](ui-batch-a1-20261107.md) | 全站增量 +42,433 B（883,325,077 → 883,367,510 B），预算 +2 MB；首页 HTML +6,251 B（+3.04%，spec 上限 +8 KB / +5%），style.css 2… |  |
| 2026-11-07 | [site-alias-20261107.md](site-alias-20261107.md) | 必做完成：data/substance_aliases.csv 的 24 行异名覆盖 46 个成分 id，这 46 个成分页各多一行 |  |
| 2026-11-07 | [readability-audit-20261107.md](readability-audit-20261107.md) | 一句话：主要的可读性问题不是对比度不达标（实测全部 ≥4.5:1），而是字号档位太多、正文/表格偏小、次要文字色不够深、分隔线太浅、标题行高与正文一样松。 |  |
| 2026-11-07 | [provincial-brand-collect-20261107.md](provincial-brand-collect-20261107.md) | 一句话：这一轮拿到 558 个可立即补上商品名的产品（205 个批文）+ 243 个全新品牌词；量不大，但都是「批准文号精确匹配 + 事实字段」，可安全入库。 |  |
| 2026-11-07 | [phaseb-rename-20261107.md](phaseb-rename-20261107.md) | 备份：data/backups/drugs-before-phaseb-rename-20261107.db（419,799,040 B） |  |
| 2026-11-07 | [phaseb-merge-plan-20261107.md](phaseb-merge-plan-20261107.md) | 一句话：92 行 = 12 异名 + 21 改名 + 12 合并 + 37 只留候选 + 10 行丢弃（聚合 1,719 + 个体 3）。 |  |
| 2026-11-07 | [pages-deploy-fix-20261107.md](pages-deploy-fix-20261107.md) | 重试一次 legacy 构建 → build 1347179765 在 87.1 s 内 built。 |  |
| 2026-11-07 | [normalization-prep-20261107.md](normalization-prep-20261107.md) | 一句话：剂型可以安全地收敛到 32 类（851 条映射、4,196 行，演练幂等）；单位只建议动 AU 的 5 个单量纲单位（6,134 行，纯机械换算），复合单位（mg/g、mg/mL…）、%、IU 类不要在没定 p… |  |
| 2026-11-07 | [name-page-slim-20261107.md](name-page-slim-20261107.md) | 省下 60,294,426 B = 57.50 MiB（目标 ≥ 45 MiB，余量 12.5 MiB）。总字节 943,601,056 → 883,306,630 B（842.39 MiB），文件数 121,292… |  |
| 2026-11-07 | [i18n-404-fix-20261107.md](i18n-404-fix-20261107.md) | 验证：本地按 GitHub Pages 子路径静态服务 + 无头 Chrome 真实点击，168 个「页面 × 语言 × 视口」组合：修复前 16 个 404（只有首页/结果页），修复后 0 个；四语 <html la… |  |
| 2026-11-07 | [eu-ingest-prep-20261107.md](eu-ingest-prep-20261107.md) | sha256：ods_products.json = 84abdd66…f15782d7d，ema_medicines.json = bc5385a2…a85e9519（完整值见同目录 fetch_meta.json）。 |  |
| 2026-11-07 | [ema-evaluation-20261107.md](ema-evaluation-20261107.md) | 建议接入，但按「区域层 region='EU'」接入，不当作第 11 个国家市场。 分两步走： |  |
| 2026-11-07 | [cn-brand-open-data-20261107.md](cn-brand-open-data-20261107.md) | 2. 可落地只有 2 个：① 省级医保局挂网/集采目录（季度增量策展）——已验证，预计最多 +200～2,000 个批文（0.3–3pp）；② Wikidata CC0——唯一可自由再发布，但预计只有 约 15–20… |  |
| 2026-11-07 | [build-determinism-20261107.md](build-determinism-20261107.md) | 一句话根因：112,642 个差异里 112,533 个只是 <head> 里的 ?v=<构建时刻秒级时间戳> 变了（同一份 HTML，版本号不同）；剩下 109 个名字页是 sorted(set, key=_sort… |  |
| 2026-11-07 | [benchmark-crossref-20261107.md](benchmark-crossref-20261107.md) | 1. 「按 ATC 同类 + 剂型/给药途径筛选」的跨国对照，是有商业先例的——Vidal 的「Équivalences internationales」就是：49 国、50 万药品、按 ATC 同类列出，并明确写「不… |  |
| 2026-10-31 | [task146-size-budget-20261031.md](task146-size-budget-20261031.md) | 不要做 798 页静态明细表：28,378 行 × ~130 B ≈ 3.7 MB，直接超限。 |  |
| 2026-10-31 | [task141-alias-mapping-20261031.md](task141-alias-mapping-20261031.md) | 已建同物异名对照表 data/substance_aliases.csv：14 行 / 8 组，覆盖 task-140 里 CN→US 的 6 条、US→CN 的 2 条命名缺口（葡萄糖↔Dextrose、扑尔敏、头孢… |  |
| 2026-10-31 | [site-ui-20261031.md](site-ui-20261031.md) | task-143 首页收敛：结果区从「引导卡 + 筛选 + 类别之后」上移到搜索表单正下方；删掉与查数据无关的技术提示（移到页底）和与 3 步引导重复的整排示例按钮；新增「最近更新」（CHANGELOG 最近 3 个版… |  |
| 2026-10-31 | [search-alias-20261031.md](search-alias-20261031.md) | 双向都通，卡片标 tier="inn_alias" + match_source="inn_alias"，与俗称（nickname / drug_term）区分开。 |  |
| 2026-10-31 | [phaseb-prep-20261031.md](phaseb-prep-20261031.md) | 例：naltrexone → 盐酸纳曲酮；sildenafil → 枸橼酸西地那非；verapamil → 盐酸维拉帕米。 |  |
| 2026-10-31 | [phaseb-dup-zh-20261031.md](phaseb-dup-zh-20261031.md) | manitol（CN 330 产品，ATC B05BC01）与 mannitol（85 产品，同 ATC）——同一 ATC、同一中文名，属拼写差异。 |  |
| 2026-10-31 | [phaseb-candidates-20261031.md](phaseb-candidates-20261031.md) | 一句话：只靠本地免费来源（库内中文名、CN 注册记录、Wikidata 本地缓存、异名表），1,791 条里能给出候选的只有 72 条（4.0%），与 task5-inn-mapping-plan.md 实测的 2.8… |  |
| 2026-10-31 | [atc4-page-20261031.md](atc4-page-20261031.md) | 我的净增量 +1,699,796 B；其余 +22,057 B 是另一位同事的导航/首页改动（逐文件比对 site/dist 得出，见 §2.2）。 |  |
| 2026-10-30 | [ux-fixes-20261030.md](ux-fixes-20261030.md) | 4 个 P0 全部修复，并在隔离测试构建里复现验证；WCAG/i18n 必做 P1 全部完成。四语同步；最终 Lighthouse 移动端可访问性 100、最佳实践 100、SEO 100。 |  |
| 2026-10-30 | [ux-audit-20261030.md](ux-audit-20261030.md) | 一句话：检索与「不可互换」方向是对的，但结果页的身份叙事和移动端首屏反馈必须先在 v0.9.1 修；矩阵筛选器的默认状态与按钮语义是第二大坑。 |  |
| 2026-10-30 | [user-evidence-20261030.md](user-evidence-20261030.md) | 2. 没有外部获客：103 次里 站内自引用 86（fuarnos.github.io 自身导航）+ 直接访问 13 + GitHub deployments 2 + 微信内置浏览器拦截页 2（weixin110.qq… |  |
| 2026-10-30 | [task140-crossref-audit-20261030.md](task140-crossref-audit-20261030.md) | 16 条 US 缺口根本不是「药」：防晒活性成分 7 条（Octisalate 3,309、Avobenzone 2,734、Octocrylene 2,684、Homosalate 2,526、Octinoxate… |  |
| 2026-10-30 | [schedule-2cron-align-20261030.md](schedule-2cron-align-20261030.md) | 同文件 §11 新会话模板、§10 已知坑第 10 条、§13 第 8 条、§5 台账 同步，文档中不再有任何「重建 7 条 at 提醒」的要求。 |  |
| 2026-10-30 | [overnight-20261030.md](overnight-20261030.md) | v0.9.0 用户可感知变化（CHANGELOG 5 条）：重量单位归一与等价规格合并（0.12 g ≡ 120 mg，保留原写法）· ATC/大类 v2（四语类名 + 来源许可、减肥药补 GLP-1、感冒/过敏拆分、… |  |
| 2026-10-30 | [lighthouse-lcp-20261030.md](lighthouse-lcp-20261030.md) | page() 不再在 <head> 放 i18n.js/bilingual.js；改为一个极小的 assets/boot.js（defer），在 load 后再加载 i18n，i18n onload 后加载 bilin… |  |
| 2026-10-30 | [lighthouse-baseline-20261030.md](lighthouse-baseline-20261030.md) | 首页 A11y：aria-allowed-attr（input#q 的 aria-expanded）；Perf：render-blocking JS（i18n.js/app.js）+ CLS 0.309。 |  |
| 2026-10-30 | [github-similar-projects-benchmark-20261030.md](github-similar-projects-benchmark-20261030.md) | 1. 「数据治理的严格程度」我们已经领先抽样里的所有项目，缺的是把它机器可读化。 |  |
| 2026-10-30 | [friend-feedback-20261030.md](friend-feedback-20261030.md) | 朋友共提 12 条：采纳 6 条（其中 2 条并入今晚的 v0.9.5）、改写成合规表述后采纳 3 条、不采纳 2 条、与产品无关 1 条。 |  |
| 2026-10-30 | [drift-baseline-20261030.md](drift-baseline-20261030.md) | 与现库入库记录交叉核对（基线行数 = 当时 ingest rows_in）：NDC 138,032 ✓、dm+d AMP 167,533 ✓、CA DPD 58,379 ✓、CIMA 25,501 ✓、NHSA 234… |  |
| 2026-10-30 | [doc-number-fix-20261030.md](doc-number-fix-20261030.md) | 「首搜 ~0.2 MB」是页面文案旧值：实测前缀分片中位 1.04 MB raw、core 8.68 MB gzip 后台加载——文案修正归建站岗 v0.9.1，本文档只标注「待更新」，不替建站岗改页面文案。 | 是 |
| 2026-10-30 | [db-window-20261030.md](db-window-20261030.md) | 实际：products 13,935、components 22,302、name_keys +9,197、name_variants +13,363、components_no_variant 51、丢弃 340；复… |  |
| 2026-10-30 | [artg-display-20261030.md](artg-display-20261030.md) | Export Only：2,632 个（新增 ARTG 2,278 + 既有 354，按 note/category 识别）；结果行与明细加「仅供出口 / Export Only」四语徽章，与 unknown 状态并存。 |  |
| 2026-10-29 | [v085-hold-20261029.md](v085-hold-20261029.md) | CHANGELOG 草稿：.tmp/cat2/CHANGELOG-v085-draft.md。 |  |
| 2026-10-29 | [tga-artg-response-20261029.md](tga-artg-response-20261029.md) | 结构提示：2,170 个 ARTG ID 有多行（最多 11 行，合计 4,661 行），未去重；无单条「ARTG 状态」列；成分/含量需解析后才能入库（与现有 etl 口径一致）。 |  |
| 2026-10-29 | [overnight-20261029.md](overnight-20261029.md) | 跨市场：141 个成分身份合并（substances 12,790 → 12,649），组合页跨市场同组合区块； |  |
| 2026-10-29 | [intuition-audit-20261029.md](intuition-audit-20261029.md) | Triage 规则（Lead 2026-10-29）：P0 立即修、P1 下一批、P2 backlog；按此自动执行，不必等用户确认。本报告只对未排期项给优先级；已排期项只在 §2 对照。 |  |
| 2026-10-29 | [handoff-20261029.md](handoff-20261029.md) | 线上：v0.8.1（16 版：v0.5.2→v0.8.1，v0.6.6 内部版本并入 v0.6.7）；gh-pages 46a6bfd37，smoke 32/32。 |  |
| 2026-10-29 | [db-window-prep-20261029.md](db-window-prep-20261029.md) | 缺口：docs/许可清单.md §2 只到 CA（且标题仍写「27 行」，现 source 已 36 行）；HK 行缺失 → 见 §4 阻塞项 ①。 |  |
| 2026-10-29 | [analytics-20261029.md](analytics-20261029.md) | 定位到候选路径：/drug-brand-crossref（该路径共 3 次；系统 {'Windows': 2, 'Linux': 1}；浏览器 {'Chrome': 3}；尺寸 {'tablet': 1, 'deskt… |  |
| 2026-10-27 | [overnight-20261027.md](overnight-20261027.md) | 8 个 teammate 全部复用：搜索、UI P0、i18n P1、/warn、中文俗名、ATC/ChEMBL、GB 盐型、MX per_volume、WHO INN、许可、发布护栏、指标 |  |
| 2026-10-26 | [who-inn-20261026.md](who-inn-20261026.md) | 证据（原文，pl135.pdf 第 2 页）：Proposed INN (Latin, English, French, Spanish) / DCI Proposée / DCI Propuesta。 |  |
| 2026-10-26 | [opensource-drug-data-20261026.md](opensource-drug-data-20261026.md) | 没有哪个开源项目能「一次补掉」全部三块缺口。 现实最优组合是： |  |
| 2026-10-26 | [i18n-audit-20261026.md](i18n-audit-20261026.md) | 一句话：字典本身是干净的（0 缺 key），问题全在“没走字典的文案 + 入口语言状态没打通”；西语是最大短板。 |  |
| 2026-10-26 | [es-inn-mapping-20261026.md](es-inn-mapping-20261026.md) | 已知假朋友进了人工黑名单：aceite de eucalipto ≠ eucalyptol、Lactobacillus ≠ L. plantarum、magnesio ≠ magnesium orotate、bicar… |  |
| 2026-10-26 | [data-depth-20261026.md](data-depth-20261026.md) | data/drugs.db 用 sqlite3 只读打开：file:data/drugs.db?mode=ro |  |
| 2026-10-26 | [cn-inn-mapping-20261026.md](cn-inn-mapping-20261026.md) | 产物：data/cn_inn_overrides.csv、etl/merge_cn_substances.py、本报告 |  |
| 2026-10-26 | [2026-10-26-手机通道.md](2026-10-26-手机通道.md) | 手机现在有两种访问方式，都不依赖云端服务： |  |
| — | [zh-hant-ui-impl.md](zh-hant-ui-impl.md) | 语言切换：导航栏 <span class="langs"> 由 LANGS 生成 4 个链接，zh-Hant 显示「繁」；i18n.js 点击拦截 → setLang → langTarget： |  |
| — | [zh-hant-i18n.md](zh-hant-i18n.md) | convert() 对每个汉字位置按以下优先级做单次扫描： |  |
| — | [zh-hant-i18n-refresh2.md](zh-hant-i18n-refresh2.md) | 旧 247 键中只有 2 个值有改进：parse.match.prefix（字首→前綴，与 ATC 前缀统一）、about.sources（程式碼→代碼，避免把药品代码误用程序代码译法）；其余 245 键保持不变。 |  |
| — | [zh-hant-i18n-refresh.md](zh-hant-i18n-refresh.md) | 44 个新键全部完成转换，键集合与 zh 完全一致；旧 203 键中只有 5 个值发生变化（2 个因中文源文更新、3 个因新增台湾术语），其余保持原样。 |  |
| — | [who-inn-merge.md](who-inn-merge.md) | 1. 上游「9 条可新增合并」经 DB 复核只有 3 条成立： |  |
| — | [warn-verify.md](warn-verify.md) | 唯一不可达来源 = 国家药监局（NMPA）检索首页：urllib 报 CERTIFICATE_VERIFY_FAILED（自签证书链），独立客户端（web_fetch）访问返回 HTTP 412 反爬、无正文。按规则「… | 是 |
| — | [warn-pagination-impl.md](warn-pagination-impl.md) | 无 404：分页仅 query 参数（同文件），四语副本 warn.html 均存在；sitemap 仍 60,219。 |  |
| — | [warn-page-impl.md](warn-page-impl.md) | 构建：warnings : 40 published，sitemap 30245 urls（含 warn.html），drug pages 12377 / name pages 17861， |  |
| — | [warn-es.md](warn-es.md) | 1. data/seed_warnings.py：新增 ES_TRANSLATIONS: dict[warning_id, (title_es, body_es)]， |  |
| — | [v091-size-strategy.md](v091-size-strategy.md) | 达标：936,965,162 B（893.6 MiB） / 112,822 文件 / sitemap 63,359。 |  |
| — | [v091-aufix.md](v091-aufix.md) | 修复：改为 set(a["c"]) != {"AU"}，只排除 AU-only；AU+其他国家保留。 |  |
| — | [ux-p1-v093.md](ux-p1-v093.md) | v0.9.1 task-29 已落地的 P1 在 v0.9.2/v0.9.3 逐项复核通过；本轮补强 H1 来源 badge 的样式，并确认中文表头、ATC 分隔、厂家剂型列、西语页头无回归。 |  |
| — | [us-terms-summary.md](us-terms-summary.md) | 已经入库。美国街头叫法、各国社区叫法、类别俗称、常见民间叫法和 FDA 官方易混淆药对 |  |
| — | [unit-normalization.md](unit-normalization.md) | 数值换算用 decimal.Decimal(repr(float(value)))  Decimal(factor)，再回写 float：不引入 0.1+0.2 类浮点误差；单位统一写成 mg。 |  |
| — | [unit-normalization-display.md](unit-normalization-display.md) | 规格待核：换算后的合法 mg 值不再标 data-suspect；无单位/范围/异常值保持原逻辑。 |  |
| — | [ui-u1-u3-plan.md](ui-u1-u3-plan.md) | U2 动 render() 核心逻辑，必须有 DOM 测试 + 性能/边界验收，放最后。 |  |
| — | [ui-u1-u3-impl.md](ui-u1-u3-impl.md) | 防 CLS：page() 新增 head_js 参数（默认空，只有首页传 U1_HEAD_JS，不污染 5.7 万页）：try{if(localStorage.getItem('u1.dismiss.v1')==='1… |  |
| — | [ui-p0-impl.md](ui-p0-impl.md) | 另顺带完成验收清单第 ④ 条：?q=/?country= 用 history.replaceState 同步到 URL（可分享），popstate 可前进后退。 |  |
| — | [ui-lang-cleanup.md](ui-lang-cleanup.md) | logo 中文副标题：en/es/zh-Hant computed display:none，zh 可见。 |  |
| — | [ui-a1-b6-plan.md](ui-a1-b6-plan.md) | 3. B6 每行报告入口：reportURL() 已有页面级实现（build.py:2285-2298）。每行复用同一 prefill 逻辑，但 GitHub issue form（.github/ISSUE_TEMP… |  |
| — | [ui-a1-b6-impl.md](ui-a1-b6-impl.md) | 构建期（load_index，site/build.py 约 L3386 起）： |  |
| — | [tw-tfda-audit.md](tw-tfda-audit.md) | OGDL v1.0 §二·授與權利： |  |
| — | [tw-market-enable.md](tw-market-enable.md) | "enabled": true, // was false |  |
| — | [tw-market-build.md](tw-market-build.md) | 静态 30/30：四语首页含 TW option 与 home.tw；hreflang="zh-TW"；首页覆盖含 TW 16,457；.tag.tw； |  |
| — | [tw-ingredient-aliases.md](tw-ingredient-aliases.md) | 未匹配 893 个 distinct token（样本 121 个）的处置： |  |
| — | [tw-ingest-write.md](tw-ingest-write.md) | 一句话：--write-db 已可用并在副本上全流程通过（幂等 + 精确回滚 + 完整性 OK）；真实库执行一条命令即可入库 16,457 个 TW 产品（+28.7k 组件、+26 MB），但需先决定 1,435 个… |  |
| — | [tw-ingest-skeleton.md](tw-ingest-skeleton.md) | 一句话：骨架能稳定地把 TFDA 许可证压缩成「产品 + 成分 + 剂型 + 厂商 + 状态 + 规格（带置信度）」的 dry-run 行；样本可入 1,535 张证、成分映射覆盖 91.3%，全量约 17,892 张… |  |
| — | [tw-ingest-runbook.md](tw-ingest-runbook.md) | 一句话：数据、审计、dry-run 骨架、schema 迁移都已就绪；现在缺「3 个实现/登记动作 + 2 个决策」（--write-db、别名表、source 行；成藥/中藥边界、zh-Hant 启用），齐了就能按… |  |
| — | [tw-country-migration.md](tw-country-migration.md) | 2. db/init_db.py 的自动迁移可用，但原来有个索引丢失 bug，已修： |  |
| — | [trilingual-query-tests.md](trilingual-query-tests.md) | 整体结论：三语检索的主干是通的——96.6% 的查询在 Top-5 内落到同一成分，67/72 个案例三语全部一致，跨国商品名 72/72 都能带出。真正需要修的是 3 类「结构性断链」，不是零散的数据缺失。 |  |
| — | [translation-provenance.md](translation-provenance.md) | 为什么没有 AI 译名：任务要求「缺 zh 不盲译；AI 译名必须 machine_translated=true/low 且默认不显示」。 |  |
| — | [terminology-fixes.md](terminology-fixes.md) | critical 2 → 0：① es_ui_missing 占位符已在数据侧修复；② combo.cross_overlap 的 es 值 |  |
| — | [terminology-accuracy.md](terminology-accuracy.md) | WHO 网站/IRIS 上没有任何中文版 INN list（本轮再次核实入口与最新 PL135，见 §1）。 |  |
| — | [task5-phaseA-namelang.md](task5-phaseA-namelang.md) | 回填规则（确定性，不看外部源）：inn_en 含 CJK（[\u3400-\u9fff\uf900-\ufaff]）→ zh；否则 en。非 ASCII 的西语名（如 Insulina Isófana）按规则归 en（… |  |
| — | [task5-inn-mapping-plan.md](task5-inn-mapping-plan.md) | strict 子集（ATC-4 一致，10 条中的 8 条可读样例）：复合维生素→multivitamin、酒石酸艾格司他→Eliglustat、乳酸亚铁→Iron、玻璃酸酶→Hyaluronidase、苯甲酸雌二醇→… |  |
| — | [task26-provenance-impl.md](task26-provenance-impl.md) | substance（末尾新增） |  |
| — | [task26-provenance-design.md](task26-provenance-design.md) | 结论：批次级溯源已有（source + ingest_run），缺的是成分主名级的「这条名字是谁定的、用什么方法、什么置信度、什么时候」。 |  |
| — | [strength-normalization-prep.md](strength-normalization-prep.md) | 先 strip + 空白归一（mg / ml → mg/ml），再按映射表规范化；数值原样保留。 |  |
| — | [source-registration-fix.md](source-registration-fix.md) | 一句话：SQL 与测试都准备好了，副本上整套校验绿；Lead 在真实库执行一次 SQL 即可让仓库恢复绿色，随后可继续 TW ingest。 |  |
| — | [sg-market-enable.md](sg-market-enable.md) | "code": "SG", "kind": "country", "parent": null, "group": "ASIA", |  |
| — | [sg-market-build.md](sg-market-build.md) | 数据核对：coverage SG 5,511；source hsa_sg = HSA Listing of Registered Therapeutic Products，SODL v1.0，data_as_of 20… |  |
| — | [sg-ingest-prep.md](sg-ingest-prep.md) | 1. 可以接入，且是成本最低的英語市場：data.gov.sg / HSA 名冊 5,511 條、12 欄，含規格（Strength）、劑型、ATC、MAH，SODL 可再發布（署名 + 鏈許可）。與 HK（無規格）相… |  |
| — | [sg-ingest-apply.md](sg-ingest-apply.md) | SG 数据：5,511 产品（在册名册）、7,080 成分（全部有 variant FK）、1,672 个 variant 被引用、映射 94.7%（全成分匹配产品 95.4%）、规格 90.1% 组件有值；sourc… |  |
| — | [sg-audit.md](sg-audit.md) | 重要区别：同一份「西药注册名册」在 data.gov.sg 上以 SODL 发布（可再发布），而 HSA 自己网站上的查询界面/说明书按 HSA Terms 限制。本项目应只使用 data.gov.sg 数据集，不要抓… |  |
| — | [search0-analytics-impl.md](search0-analytics-impl.md) | Headless（Chrome CDP，GoatCounter stub）：无结果 zzzzqqqq 恰一次 search0-zzzzqqqq；重复同查询不重发；有结果 amlodipine 不发 search0 且… |  |
| — | [search-p0-fix.md](search-p0-fix.md) | 三语测试里 3 条中文通用名查询返回 0 结果，提示却是「名字对上了，但没有在售产品」： |  |
| — | [search-intuition-audit.md](search-intuition-audit.md) | 3. 索引含大量非在售名字：160,750 个索引 key 中 30,391（18.9%）不在 active 产品集（32,013 个 key 仅有 inactive 产品）；抽样 3,000 条与 DB active… |  |
| — | [search-eval-v3.md](search-eval-v3.md) | 门槛（可覆盖）：--top5-min 0.95（must_hit Top-5）、零结果误命中必须 = 0；gap 用例不计入通过率，只记录「意外命中」。 |  |
| — | [search-eval-expansion.md](search-eval-expansion.md) | 结论：除「拼音」类（py 侧索引只在站点客户端，Python lib/search.py 尚无拼音层）外， |  |
| — | [search-engine-v2.md](search-engine-v2.md) | ?legacy=1：完全走旧 data/index.json 全量索引 + 旧线性扫描（DOM 已验证 fetch 只拉 data/index.json，结果与旧版一致）。 |  |
| — | [search-engine-bench.md](search-engine-bench.md) | 1. 不建议引入任何第三方检索库：为等价功能，索引体积会额外增加 1.10 MB（Fuse）→ 5.68 MB（MiniSearch）→ 12.39 MB（FlexSearch）→ 23.22 MB（Orama）gzi… |  |
| — | [search-analytics-fix.md](search-analytics-fix.md) | 搜索事件改为只在提交时发送：Enter、示例词 chip、自动完成选择、?q= 深链；输入过程不再发送。 |  |
| — | [schema-indexes.md](schema-indexes.md) | L74-78：variant 的索引组 |  |
| — | [release-notes-i18n-v055.md](release-notes-i18n-v055.md) | 任务要求的 4 个版本（v0.5.2–v0.5.5）现在全部在 JSON 中： | 是 |
| — | [release-notes-i18n-refresh3.md](release-notes-i18n-refresh3.md) | What's new 不再出现「译文待补」：v0.6.0–v0.8.1 全部有 zh/en/es 三语块；v0.8.2 为发布说明草拟的占位（CHANGELOG 尚未定稿，见 §4）。 | 是 |
| — | [release-guardrails.md](release-guardrails.md) | json-out .tmp/guardrails/verify-live-2026-10-27.json | 是 |
| — | [publish-incremental.md](publish-incremental.md) | 决定性优点：未变文件复用已有 git 对象；所有 HTML 虽然因 ?v=BUILD_V 都变了，但相对上一版的 thin delta 很小，60,319 个变更文件最终只传 27.55 MiB。 | 是 |
| — | [pt-data-request.md](pt-data-request.md) | 公益/非商业豁免：页面没有公布；只能在申请中询问（信中 §4）。 |  |
| — | [pt-audit.md](pt-audit.md) | 现有 schema 关键列（只读核对）：product(country, dosage_form, form_base, route, release, pack, mah, approval_id, category… |  |
| — | [pseudo-combo-build.md](pseudo-combo-build.md) | Headless：搜索 aadfer → 成分只显示 Ferrous（不再 Ferrous + Ferrous）、无 combo 链接、无 severe/同名不同药；搜索 amoxicillin clavulanate… |  |
| — | [pseudo-combo-audit.md](pseudo-combo-audit.md) | 1. 对每个 substance 的 inn_en 做规范化（小写、括号/连字符→空格）。 |  |
| — | [product-name-language-audit.md](product-name-language-audit.md) | 1. 截图与 DB 实际相反：欧双宁 是 CN 注册商品名（Boehringer 的 Jentadueto，linagliptin+metformin；CN 产品 CN-XA10BDL358A00-）。CA 没有任何中… |  |
| — | [pinyin-lib.md](pinyin-lib.md) | 可选严格门槛：run_ci.py --gate-pinyin 把 65 例拼音 gap 升为 must_hit 后，Top-5 = (380+54)/(391+65) = 434/456 = 95.2%（≥95%，但余… |  |
| — | [no-trade-name-display.md](no-trade-name-display.md) | 结果行 / 成分页矩阵 / 名字页：无 trade 名的产品在商品名位置只显示「无商品名」纯文本角标（st-badge st-unknown brand-none），不链接、不放厂家；可附通用名+剂型小字。 |  |
| — | [name-lang-badges.md](name-lang-badges.md) | 非中文界面（en/es）遇到 name_lang='zh' 的 base 名：保留中文原名，加「No English name recorded / Sin nombre en español」角标。 |  |
| — | [mx-strength-audit.md](mx-strength-audit.md) | 关键决定：不要直接跑 ingest_mx_ccby.py --apply。 当前 ETL 会把 963 条全部写库，其中 357 条是错的（现网会显示错误规格）。apply 前必须先加过滤（见 §6），本轮只建议入 5… |  |
| — | [mx-pervolume.md](mx-pervolume.md) | 1. 可安全挽回 125 条（= 上轮 376 条 FAIL/UNCERTAIN 的 33%、963 条的 13%）：原文能明确解析出「数值 + 基数」，且通过剂型一致性检查。 |  |
| — | [mx-atc-implementation.md](mx-atc-implementation.md) | 两个 ingest 都支持 --db <path>（用于在副本上演练），默认 data/drugs.db。 |  |
| — | [mo-data-request.md](mo-data-request.md) | 1. 對口單位：藥物監督管理局（ISAF，Instituto para a Supervisão e Administração Farmacêutica）註冊廳（藥品註冊職能）；gov.mo 服務頁列出的執行單位是「… |  |
| — | [matrix-sort-filter.md](matrix-sort-filter.md) | 排序语义：常用度=跨国家产品/品牌记录数，仅展示排序，不代表疗效/推荐。 |  |
| — | [matrix-layout-impl.md](matrix-layout-impl.md) | 样例：acetaminophen（291 个规格行 → 截断 120、8 国含 TW）；metoprolol（58 行、7 国）。 |  |
| — | [matrix-columns-ondemand.md](matrix-columns-ondemand.md) | 矩阵默认 3 列：产品数最多的市场 + 当前界面语言市场 + 第二多市场；其余通过筛选器「国家」多选加入；mk=CN,TW 可分享，localStorage 记忆；加「全选/清空」。 |  |
| — | [matrix-alignment-fix.md](matrix-alignment-fix.md) | 根因（confirmed）：成分页矩阵 tbody 的 <td> 没有 data-country 属性，而 i18n.js 按界面语言重排矩阵时只按 data-country 排序单元格；表头 <th> 有属性会被重排… |  |
| — | [markets-integration-plan.md](markets-integration-plan.md) | 1. 硬编码点共 23 类结构点（国家 13 类 / 语言 10 类），集中在 3 个位置： |  |
| — | [maker-pages.md](maker-pages.md) | 1. reports/maker-pages-data.md 建议首版 ≥2 产品（10,975 页）；etl 的 has_page 也按 ≥2。 |  |
| — | [maker-pages-data.md](maker-pages-data.md) | 页数取决于阈值（规范化后）：≥2 → 10,975、≥3 → 8,994、≥5 → 6,997、≥10 → 4,889、≥50 → 1,638。 |  |
| — | [maker-pages-all.md](maker-pages-all.md) | 阈值从 ≥5 产品降为 1：data/maker_candidates.csv 中所有非占位厂家都生成独立页（slug 沿用现有逻辑，旧 URL 不破坏）。 |  |
| — | [link-target-fix.md](link-target-fix.md) | 旧逻辑（rowHTML / brandRowHTML / 家庭卡片）： |  |
| — | [lighthouse-optimization.md](lighthouse-optimization.md) | CLS 全部 <0.1（0.021–0.082）；TBT <200ms（0–90ms）；实验室环境无 INP（用 TBT 代理）。 |  |
| — | [license-audit.md](license-audit.md) | 2. 最高风险 3 条（详见 §3）： |  |
| — | [lib-atc-category-search.md](lib-atc-category-search.md) | TIER 增加 atc=0.92、category=0.88（仅用于这些结果卡排序；不是名字匹配层）。 |  |
| — | [lazyload-implementation.md](lazyload-implementation.md) | // 全量索引（34.8 MB，gzip 约 6 MB）等用户真的要用搜索时再下。 |  |
| — | [inn-zh-backfill-v2.md](inn-zh-backfill-v2.md) | 目标达成：英文通用名比例 0%（保守 0.106% < 5%）。 |  |
| — | [ingredient-i18n.md](ingredient-i18n.md) | 验证明细在 .tmp/inn-zh/。 |  |
| — | [index-perf-plan.md](index-perf-plan.md) | 推荐落地顺序：P0 → P1 → P2，P3 作为下一版优化。P2 的收益：首屏字节 6.06 MB → 0.092 MB（约 1/66）；每次按键查找从 102 ms（全量扫描）→ 约 2 ms（本机 Node 基准… |  |
| — | [index-p2-impl.md](index-p2-impl.md) | 一句话：首搜从「3.78 MB 全量 core」变成「254 KB（manifest + 1 个分片），core 在后台补全」；最终检索结果与接入前逐字一致，?legacy=1 与全部失败路径均可回退。 |  |
| — | [index-p1-impl.md](index-p1-impl.md) | 净收益是传输字节：首搜 6.06 MB → 3.84 MB（线上预估），raw 体积 -56%；解析/解码耗时没有明显下降（V8 解析 34.8 MB JSON 本来就快），这部分留给 P2 分片解决。 |  |
| — | [index-legacy-removal.md](index-legacy-removal.md) | 推荐 方案 A（分两步）： |  |
| — | [index-legacy-impl.md](index-legacy-impl.md) | ?legacy=1 现在与默认路径共用 core.json + decodeCore()；旧 index.json 仅在 |  |
| — | [i18n-v055.md](i18n-v055.md) | DOM 5/5：① zh 搜 Excedrin Extra Strength → 成分显示 对乙酰氨基酚（Aspirin 无中文按段回退英文、Caffeine→枸橼酸咖啡因）；② en 仍显示英文、无中文泄漏； |  |
| — | [i18n-p1-impl.md](i18n-p1-impl.md) | I18N：137 → 160 keys × en/es/zh（新增 23 键；0 缺失、0 空值、0 残留 @@占位符@@）。 |  |
| — | [i18n-p0-fix.md](i18n-p0-fix.md) | I18N 字典：112 keys × en/es/zh（原 91 + 新增 21），0 缺失、0 空值。 |  |
| — | [home-guide-position.md](home-guide-position.md) | 静态 10/10：index 中 #q < #u1guide < .row（顺序正确）、大类块未误删；CSS 标题 18px/700、桌面三等分、移动单列、步骤 b 独立行；localStorage 关闭逻辑保留。 |  |
| — | [home-category-collapse.md](home-category-collapse.md) | 静态 6/6：首页 catquick/16 chips 存在；app.js setCatsHidden + cat-hidden + aria-hidden；render 按 !!q 调用；CSS 隐藏；四语首页均有大… |  |
| — | [hk-mo-audit.md](hk-mo-audit.md) | data.gov.hk 数据集：hk-dh-dh_do-hk-dh-do-pharmaceutical-product |  |
| — | [hk-market-enable.md](hk-market-enable.md) | HK 已按名称/成分层接入：注册表 enabled、首页下拉/覆盖页 10 市场、矩阵 HK 列可筛选、About 四语署名 + 数据截止 + 覆盖边界。 |  |
| — | [hk-ingest-prep.md](hk-ingest-prep.md) | <lastUpdate>2026-10-23</lastUpdate> |  |
| — | [hk-ingest-apply.md](hk-ingest-apply.md) | country TEXT NOT NULL CHECK (country IN ('US', 'GB', 'CN', 'ES', 'MX', 'AU', 'CA', 'TW')), |  |
| — | [header-ui-fix.md](header-ui-fix.md) | 静态 11/11：nav nowrap、nav a nowrap、langs 紧凑、.nav-toggle、<768 媒体查询（nav 隐藏/展开）、移动 nav 链接 ≥40px、logo-zh 窄屏隐藏、汉堡注入与… |  |
| — | [gb-salt-recovery.md](gb-salt-recovery.md) | 一句话：dm+d 里的盐型证据（AMP→VMP→VPI→ISID→原料名）足够可靠地恢复 1.5 万个 GB 组件（约 23%），干跑/回滚全部验证通过；真实库未动，等 Lead 拍板 apply。 |  |
| — | [eu-layer-schema.md](eu-layer-schema.md) | 一句话：region 建模与迁移已通过副本全流程验证；EU/EMA 可作为「区域层」与国别产品共存（coverage 单独一行、不污染 9 国统计），真实库 apply 待 Lead 批准并与 HK/TW 窗口协调（见… |  |
| — | [es-ui-audit.md](es-ui-audit.md) | 中文是唯一权威：zh 数组逐条来自 CHANGELOG.md（由 .tmp/es-i18n/parse_changelog.py 解析；不重写、不改写原文）。 |  |
| — | [es-combo-fix.md](es-combo-fix.md) | 1. 208 条的真实性质与任务描述不同：它们不是「已入库但只挂 1 个成分」，而是 CIMA 列表里被 etl/ingest_cima.py 整条跳过的 208 个注册： |  |
| — | [ema-ingest-prep.md](ema-ingest-prep.md) | 1. 可做、且許可在線上路徑上是最乾淨的：EMA 集中審批數據可按 EMA Legal notice 免費再發布（含商業用途），只需在每份內容署名 EMA。對比葡萄牙 INFARMED 國別數據（無開放許可、需書面授權… |  |
| — | [drug-term-cleanup.md](drug-term-cleanup.md) | 用户口径：毒品/娱乐性用药不要包含在内，只保留合法药品俗名。据此对 nickname(57) 与 |  |
| — | [dose-mapping-plan.md](dose-mapping-plan.md) | 结论：D2 可以做、但不要"全自动"——先把 variant.salt 的脏数据（1555 条里约 409 条不是盐）和"强度基准（label strength basis）"这两个坑修掉；D3 不需要新算法，用现有… |  |
| — | [dose-d2d3-impl.md](dose-d2d3-impl.md) | 数据层已就绪，且默认全库不产生任何折算数字：schema v0.4 幂等迁移通过、 |  |
| — | [display-fixes-impl.md](display-fixes-impl.md) | 静态 12/12：存在 data-suspect=1 行且排最后；品牌 title 全名；CSS 两行截断；matrix.spec_check 四语；.m-zh 样式与实例；状态 4 类 CSS；客户端去重+title… |  |
| — | [deploy-verification-file.md](deploy-verification-file.md) | — |  |
| — | [db-window-runbook.md](db-window-runbook.md) | 1. Lead 批准窗口时间；确认无其它会话在跑 build/ingest/publish。 |  |
| — | [db-optimization.md](db-optimization.md) | 默认 2 个索引合计约 -18 ms/build（ARTG），远小于构建总时长（分钟级）；不要期望用索引解决 build 慢——大头是 load_index/collision 的全表聚合（合计约 6 s，由数据量决定… |  |
| — | [data-quality-audit.md](data-quality-audit.md) | 1. 数据没有大面积损坏：真乱码仅 1 条（U+FFFD），名称占位 0 条，country/region 无空值，approval_id 无空格式异常；问题集中在来源字段缺失/表达方式，而不是编码事故。 |  |
| — | [data-packaging.md](data-packaging.md) | checksums.txt（资源 + datapackage + dataset + docs 的 SHA-256） |  |
| — | [cross-market-mapping.md](cross-market-mapping.md) | 1. 成分×市场：12,790 个 substance 中 12,377 个有产品；2,953 个（23.86%）出现在 ≥2 个市场——这是当前的「跨市场链接率」。 |  |
| — | [cross-market-batchB.md](cross-market-batchB.md) | overrides 状态变化： |  |
| — | [cross-market-apply-prep.md](cross-market-apply-prep.md) | 1. batch A 30 条已写入 overrides CSV（结构/列序/UTF-8 BOM 均保持不变）： |  |
| — | [country-region-wording.md](country-region-wording.md) | 具体国家名（美国/中国/台湾…）、品牌名、数据一律未动；正文泛指句（如「同一成分在不同国家可能不同」）保留；TW 旗标按 Lead 决定本轮不动（只改文字）。 |  |
| — | [combo-url-compat.md](combo-url-compat.md) | 对 v0.9.1 体积策略裁剪掉的全部 8,455 个旧组合页生成极简 noindex stub；v0.9.0 的 combo URL（含 AU-only 旧组合）不再 404。 |  |
| — | [combo-page-integration.md](combo-page-integration.md) | 组合页的 vs 是「同一 name_key 下所有产品的成分并集」，不一定等于单个产品成分集合（报告 §5.4 已提示）。 |  |
| — | [combo-crossmatch.md](combo-crossmatch.md) | exact：同一签名在对面区域至少 1 个国家有产品； |  |
| — | [cn-slang-ingest.md](cn-slang-ingest.md) | term_norm 与现有 community_cn 行一致（中文保持、小写、去空格标点），与站内 |  |
| — | [cn-slang-crawl.md](cn-slang-crawl.md) | raw_terms.jsonl 共 772 行短事实，覆盖 78 个检索词（72 个种子 + 维基部分条目标题差异）；来自 4 个来源：百度搜索、必应搜索、头条搜索、中文维基。 |  |
| — | [cn-slang-candidates.md](cn-slang-candidates.md) | 产物：etl/extract_cn_slang.py、data/cn_slang_candidates.csv（1,108 行）、本报告 |  |
| — | [cn-manual-parse.md](cn-manual-parse.md) | 解析器扩展：etl/fetch_cn_brand_names.py --expand-manual： |  |
| — | [cn-manual-collection.md](cn-manual-collection.md) | 1. 首选 PDF（表格型，非扫描件）：可用 PyMuPDF find_tables() 直接抽表；扫描图片 PDF 不可解析（请换源或人工录 CSV）。 |  |
| — | [cn-data-intuition-audit.md](cn-data-intuition-audit.md) | 商品名 script 分布（按 key） |  |
| — | [cn-data-cleanup-prep.md](cn-data-cleanup-prep.md) | 2. 影响面（以当前 DB 实测，与 audit 略有数据漂移）： |  |
| — | [cn-brand-names.md](cn-brand-names.md) | 1. NHSA「医保药品分类与代码」的商品名列已被现有库基本吃干：两版快照共 486,467 行、其中 36,154 行有商品名、去重 5,004 个品牌名；DB 现有 CN 品牌键 4,866，按批准文号匹配 98.… |  |
| — | [cn-brand-expand.md](cn-brand-expand.md) | 本轮后：trade 批文 8,430/69,380 ≈ 12.15%，产品 18,321/146,347 ≈ 12.52%，品牌键约 4,926；候选 CSV 542 行（high 31），已交 task-108 入库。 |  |
| — | [cn-brand-channels.md](cn-brand-channels.md) | 2. 省级集采/挂网目录是唯一验证成功的合法批量渠道： |  |
| — | [cn-brand-apply.md](cn-brand-apply.md) | 1. 匹配：product(country='CN').approval_id == candidate.approval_id；同一批文多产品时逐产品挂同一品牌名（同品牌多包装），不合并产品。 |  |
| — | [ci-setup.md](ci-setup.md) | 新增 deploy/ci_checks.py：CI 与本地发布前同一个入口、同一套判定；本地全量实测 8/8 PASS（708.3s，trilingual 672s）。 |  |
| — | [category-v2-impl.md](category-v2-impl.md) | 已应用 .tmp/cat2/build-partial-v085-b.patch（含 ATC v2 加载、大类 v2、base 去重、cap 80 + <details>、状态徽标、逐语来源；根目录验证文件 write… |  |
| — | [cat-i18n-fix.md](cat-i18n-fix.md) | 1. 大类名是编辑/AI 译名（页面上仍有「不是官方译名，ATC 码为准」说明）；如需官方译名由 data 侧补。 |  |
| — | [bilingual-impl.md](bilingual-impl.md) | Headless（Chrome CDP）：zh 成分页 h1 =「苯磺酸氨氯地平」+ 来源徽章「监管机构」+ v2026-10-28.1 + 原文（默认开）；关闭开关 → 原文消失、localStorage=0、刷新后… |  |
| — | [au-tga-followup.md](au-tga-followup.md) | = 2026-10-27 04:33 UTC |  |
| — | [atc-intuition-audit.md](atc-intuition-audit.md) | 排期对照口径：docs/谷段需求队列.md L42（v0.8.2 = 零结果埋点 + ATC/UI 六项修复）、L43（v0.8.3 = 成分页矩阵常用剂量排序 + 筛选器 + 空行隐藏）、v0.7.1 报告（ATC… |  |
| — | [atc-ingredient-i18n.md](atc-ingredient-i18n.md) | 静态 14/14：ATC C08 成分带 data-n-（≥8），zh 值含中文（氨氯地平），存在无中文名成分（data-n-zh=""）；cat 页多语标记 + 中文；组合页多语标记；atc.html 大类中文；ap… |  |
| — | [atc-glossary-impl.md](atc-glossary-impl.md) | document keydown：/ 在非输入控件中聚焦搜索并全选；Esc 先关自动完成，再清空查询并重绘； |  |
| — | [atc-class-names.md](atc-class-names.md) | 每个 code 选最像类目的 item：优先英文描述中的 |  |
| — | [atc-class-names-v2.md](atc-class-names-v2.md) | v1（Wikidata）→ v2 新增覆盖：任一语言 332 → 1,134（+802）；en 309 → 1,074；zh 176 → 841；es 164 → 441；zh-Hant 176 → 841。 |  |
| — | [atc-chembl.md](atc-chembl.md) | 1. 旧的 ATC 覆盖率分母不对：5,890 / 12,793 = 46.0% 把生药、顺势药、医疗气体、营养配方、ARTG 解析残留都算进分母了。 |  |
| — | [atc-browse-impl.md](atc-browse-impl.md) | 1. 类别名非官方：L2–L4 仅 25 个常见类别有编辑/AI 四语名，其余以 ATC 码为标题并标「类别名待校订」；页面/About 均声明 ATC 码与 WHO 层级为准。 |  |
| — | [artg-20261030-ingest.md](artg-20261030-ingest.md) | 全部计数与预期完全一致（偏差 0%）；quick_check=ok、foreign_key_check=0。 |  |
| — | [artg-20261028-audit.md](artg-20261028-audit.md) | 编码 UTF-8 with BOM；字段数校验 0 异常（bad_field_rows=0）。 |  |
| — | [a4-coverage-page.md](a4-coverage-page.md) | 产品数、成分映射率、规格覆盖率、最后同步、数据截止、已知缺口。 |  |
| — | [a1-detail-buckets.md](a1-detail-buckets.md) | 做法：直接从只读 data/drugs.db 生成「key → 最多 12 条产品明细」桶；用 build.py 同款 _shard_bucket(k) 分桶；桶内做枚举字典 + URL 前缀压缩，把平铺估算的 71.… |  |
