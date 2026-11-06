# task-8 GitHub Pages 部署失败修复（2026-11-07）

> 范围：只碰部署侧。**未动** `data/drugs.db`、`site/build.py`、`docs/`、`gh-pages` 分支内容、`site/dist`；
> 没有本地重建、没有重跑 `publish.ps1`、没有 `git commit`。
> 底线不变：只做部署恢复与线上验收，不涉及身份对应 / 碰撞 / 警示语义，也没有任何用药建议口径变化。

## 0. 结论

1. **线上已经跑 v0.9.6**（gh-pages `fbf67c5a`）。恢复动作只有一步：`POST /repos/fuarnos/drug-brand-crossref/pages/builds`
   重试一次 legacy 构建 → build **1347179765** 在 **87.1 s** 内 `built`。
2. `deploy/verify_live.py --expect-version v0.9.6`：**exit 0 / 31 项检查 / 0 failures / 0 warnings**；
   页脚 `v0.9.6 · 2026-11-07`，sitemap 63,363，name/drug/atc 各抽 3 页全 200 且都是 v0.9.6。
3. **失败原因不是体量**：v0.9.6 比上一次成功上线的 v0.9.5 **小 57.5 MiB**，文件数完全相同（121,292）。
   三次失败构建的 `duration` 全是 `0 ms`、错误一律是笼统的 `Page build failed.`，同提交重试即成功
   → 判定为 GitHub 侧 legacy 构建队列/worker 的瞬时故障 + 一次 92 分钟的卡死（§1）。
4. **Actions 兜底路线已备好但未启用**：`.github/workflows/pages-fallback.yml` + `deploy/pages_deploy.ps1`。
   切 Source 需要 `pages:write`，**本仓库 `.env` 的 token 没有**（`PUT /pages` 实测 403）——
   所以这一步只能**人点 Settings → Pages → Source**，或换一个带 Pages:write 的 token（§1.4、§6）。
5. 不需要回滚：线上就是 v0.9.6，且没有半成品（失败构建不影响已发布的那一份）。

## 1. 证据（可直接复核）

### 1.1 构建时间线（`GET /repos/fuarnos/drug-brand-crossref/pages/builds?per_page=8`）

时间单位 UTC（括号内为北京时间 UTC+8），2026-11-06 抓取：

| build id | commit | created | updated | status | duration | error |
|---|---|---|---|---|---|---|
| 1346964099 | `fbf67c5a` | 17:52:04（11-07 01:52） | 18:03:21 | **errored** | 0 ms | Page build failed. |
| 1346989511 | `fbf67c5a` | 18:03:59（02:04） | 19:36:39 | **errored** | 0 ms | Page build failed. |
| 1347179555 | `fbf67c5a` | 19:36:39（03:36） | 19:36:46 | **errored** | 0 ms | Page build failed. |
| 1347179765 | `fbf67c5a` | 19:36:46（03:36） | 19:38:13 | **built** | 87,055 ms | — |
| 1346652015 | `977436aa`（v0.9.5） | 11-06 15:27:04 | 15:29:27 | built | 143,622 ms | — |
| 1325552695 | `230ef8c5`（v0.9.4） | 10-29 22:26:44 | 22:28:12 | built | 88,689 ms | — |

读法：
- 1346989511 从 18:03:59 到 19:36:39 一直是 `building`（同时 `GET /pages` 也报 `status=building`），
  **卡了 92 分 40 秒**——legacy 正常 87–144 s，这已经是卡死而不是「在慢慢构建」。
- 19:36:39 我发出 `POST /pages/builds` 后，卡死的那条被立刻标成 `errored`，同一秒生成 1347179555
  （7 s 内又报 `Page build failed.`），GitHub 随即自动再起一条 1347179765，**87 s 构建成功**。
- 由此判断：这个环节失败得快到没有真正开始构建（`duration=0`），且**同样的内容重试就过**。

### 1.2 体量对比（`git ls-tree -r -l <sha>` 汇总，gh-pages 缓存 `.tmp/publish-opt/gh-pages-cache`）

| 版本 | commit | 文件数 | 字节 | MiB | 1 GB 上限余量 |
|---|---|---|---|---|---|
| v0.9.5（上次成功） | `977436aa` | 121,292 | 943,600,998 | 899.9 | 53.8 MiB |
| v0.9.6（本次） | `fbf67c5a` | 121,292 | 883,334,350 | 842.4 | 111.3 MiB |

v0.9.6 目录分布（其余 es/zh/zh-hant/cat/assets/docs 合计约 2.0 MiB）：

| 目录 | 文件数 | 字节 | MiB |
|---|---|---|---|
| `name/`（含 CJK 转义路径 77,058 页） | 77,058 | 316,515,087 | 301.9 |
| `data/` | 174 | 191,384,993 | 182.5 |
| `drug/` | 12,442 | 148,153,036 | 141.3 |
| `maker/` | 15,213 | 138,345,411 | 131.9 |
| `combo/` | 15,191 | 61,079,603 | 58.3 |
| `atc/` | 1,154 | 16,289,679 | 15.5 |
| 根目录 | 16 | 9,000,562 | 8.6 |

→ **失败的版本比上一次成功的版本小 60,266,648 B（57.5 MiB）、文件数一模一样**，
所以「越过 1 GB / 文件太多 / 构建超时」都解释不了这次失败：上一次是 899.9 MiB 都能过，
这一次 842.4 MiB 反而失败。（口径备注：任务书里的 883,334,408 B 与 git blob 汇总差 58 B，
是文件系统记账 vs blob 汇总的差异，不影响结论。）

### 1.3 平台侧

- `githubstatus.com` 未解决 incident：**0**；组件 `Pages: operational`、`Actions: operational`（19:41Z 查）。
  即当时没有公开的 Pages 事故——但这只能说明「不是大面积事故」，单个仓库的构建 worker 抖动不会被公开。
- Pages 设置：`build_type=legacy`、`source=gh-pages/`、`https_enforced=true`、`custom_404=true`；
  恢复后 `status=built`。

### 1.4 token 权限（决定「能不能用 API 切 Source」）

- `.env` 里的 `GITHUB_TOKEN` 是 **fine-grained PAT**（`GET /` 返回的 `x-oauth-scopes` 为空）；
  `GET /pages` 的 `x-accepted-github-permissions` 要求 `pages=read`。
- 幂等探针 `PUT /repos/fuarnos/drug-brand-crossref/pages` + `{"build_type":"legacy","source":{"branch":"gh-pages","path":"/"}}`
  （写回**与当前完全一致**的值，不改变配置）→ **HTTP 403** `Resource not accessible by personal access token`。
- 探针后复查：设置仍是 `legacy` + `gh-pages`，首页 200 且是 v0.9.6 —— 没有副作用。
- 结论：**这个 token 不能改 Pages Source**；`POST /pages/builds`（重试构建）可以用（本次就是靠它恢复的）。

## 2. 做了什么（按时间顺序）

| # | 动作 | 结果 |
|---|---|---|
| 1 | 读 Pages 设置 + 最近 8 次构建 | 确认 3 次 errored / 1 次卡死 92 min，线上仍是 v0.9.5 |
| 2 | `POST /repos/.../pages/builds`（body `{}`） | `{"status":"queued"}` → 新 build 1347179765 |
| 3 | 轮询到终态 | **built，87,055 ms** |
| 4 | `python deploy/verify_live.py --expect-version v0.9.6` | exit 0，0 failures |
| 5 | 从线上 sitemap 随机抽 name/drug/atc 各 3 页 | 9/9 HTTP 200 且含 v0.9.6 |
| 6 | 幂等 `PUT /pages` 探针 | 403 → 记录 token 权限边界 |
| 7 | 写兜底 workflow + 两个部署侧脚本（未启用） | YAML 解析通过、脚本 `-DryRun` 冒烟通过 |

没有做的事（有意）：本地重建、重跑 `publish.ps1`、改 gh-pages、改 Pages Source（token 无权限且当前不需要）。

## 3. 验收结果（`deploy/verify_live.py --expect-version v0.9.6`，19:41Z）

- `ok=true`、`failures=[]`、`warnings=[]`、`checks=31`、exit code **0**。
- 版本口径：首页页脚 `v0.9.6 · 2026-11-07`；`/es/`、`/zh/`、About 页脚、`whats-new.html` 顶部全部 v0.9.6。
- 首页 HTTP 200 / 205,532 B；`data/idx/core.json` gzip **10,028,805 B**（护栏区间 2.5–12 MB）；`data/index.json` 404（core-only 构建的预期行为）。
- sitemap 63,363 URL；robots 含 Sitemap 行；未知路径 404。
- 抽样（从线上 sitemap 随机，seed=9606）：`name/paliperidone`、`name/troferit-flow`、`name/抑那通`、
  `drug/darvadstrocel`、`drug/alefacept`、`drug/aloe-barbadensis-leaf-powder`、
  `atc/A03BA`、`atc/A10X`、`atc/G04BC` —— 全部 HTTP 200 且含 `v0.9.6`。
- JSON 存档：`.tmp/guardrails/verify-live-v096.json`（`.tmp/` 不入库）。

## 4. 推测（与上面证据分开）

- **推测 A（高置信）**：三次 `errored` 是 GitHub 侧 legacy 构建的**瞬时失败**，不是内容问题。
  依据：`duration=0`、错误码笼统、同 commit 重试即 built、体量比上次成功更小、平台无公开事故。
  这类失败在 API 里拿不到细节（`error.message` 永远只有 `Page build failed.`），只能靠「重试 + 重试是否成功」判定。
- **推测 B（中置信）**：1346989511 的 92 分钟 `building` 是构建队列卡住（status 字段也被冻结在 building），
  `POST /pages/builds` 起到的作用更像「踢了一脚队列」而不是「排队下一次构建」——证据是它几乎同秒被标 errored。
- **未证实**：legacy 构建是否有隐藏的「文件数 / inode」上限（121,292 个文件距常见 65k/100k 阈值不近但也不是没风险）。
  下一次发布若再次失败，优先按 §6 的顺序处理，不要先去删页。

## 5. 回滚方式

线上现状 = v0.9.6 且已验收，**不需要回滚**。留两条路给以后：

1. **内容回滚到 v0.9.5**（要人拍板，AGENTS §6）：把 gh-pages 指回 `977436aa` 再让 legacy 重建一次。
   `publish.ps1` 自带「推送失败回退上一版」的逻辑，但**主动回滚不做自动**——按纪律由人决定。
2. **Source 回滚（切到 Actions 之后才用到）**：Settings → Pages → Source 改回 `Deploy from a branch` + `gh-pages / (root)`，
   线上立刻回到「上一个成功构建的 legacy 版本」（现在就是 v0.9.6；如果将来的 workflow 部署坏了，就是回到 v0.9.x 上次 branch 构建）。
   API 等价物是 `deploy/pages_deploy.ps1 -RollbackToBranch`，但**当前 token 会 403**（§1.4），需要人点或换 token。

## 6. 下一个版本发版注意（写进流程）

1. `publish.ps1` 推完 gh-pages 后，**立刻**跑 `deploy/pages_status.ps1`（只读，打印设置 + 最近 8 次构建 + latest）。
2. 若 latest 是 `errored`：直接 `deploy/pages_deploy.ps1 -RetryBuild`，然后 `deploy/pages_status.ps1 -Wait -MaxMinutes 15`。
   本次证明「同 commit 重试一次」就能过；**最多重试 2 次**，仍失败就停下来写报告（AGENTS §12：连续 2 次发布失败即停）。
3. 若 `building` 超过 15 分钟：同样用 `-RetryBuild` 踢队列（本次就是这样解掉 92 分钟卡死的）。
4. 验收一律 `python deploy/verify_live.py --expect-version vX.Y.Z`，**exit 0 才算上线**；`ok=true` 但还有 warning 时看 warning 是否可接受。
5. **1 GB 硬顶还在**：现在 842.4 MiB，余量 111.3 MiB。Actions 兜底**不绕过**这个上限（已发布站点体积限制两种模式共用），
   所以下一次若接近 900 MiB，就要先做瘦身（`name/` 301.9 MiB 仍是最大头，`data/` 182.5 MiB 次之），
   而不是先切 Source。
6. legacy → Actions 的切换顺序（缺一步线上就 404）：先把 `.github/workflows/pages-fallback.yml` 提交到 `main`
   → 再把 Source 切到 "GitHub Actions" → 立刻 `deploy/pages_deploy.ps1 -Dispatch`
   → `pages_status.ps1` 看 workflow 结果 → `verify_live.py` 验收。回退用 §5.2。

## 7. 新增 / 改动文件

| 文件 | 说明 |
|---|---|
| `.github/workflows/pages-fallback.yml` | **新增**。`workflow_dispatch`（默认不自跑）：checkout `gh-pages` → preflight（`.nojekyll`/`index.html`/`404.html`/`sitemap.xml`/`data/idx/core.json` + 体积 > 1 GB 直接失败）→ `upload-pages-artifact` → `deploy-pages`。只在 legacy 连续失败时启用。 |
| `deploy/pages_status.ps1` | **新增**。只读：Pages 设置 + 最近 N 次构建 + latest；`-Wait` 轮询到终态（正常 90–150 s，>15 min 视为卡死）。 |
| `deploy/pages_deploy.ps1` | **新增**。`-Status` / `-RetryBuild` / `-SwitchToWorkflow` / `-Dispatch` / `-RollbackToBranch`，都支持 `-DryRun`；文件头写明 token 的 403 边界与切换顺序。 |
| `reports/pages-deploy-fix-20261107.md` | 本报告。 |

未改：`deploy/publish.ps1`（工作区里它的 `M` 状态是别的会话改的，我不碰）、`site/`、`db/`、`data/`、`docs/`、`gh-pages`、`site/dist`。

## 8. 遗留 / 需要人决定

1. **Pages Source 的写权限**：要不要换一个带 `Pages:write` 的 token？换了之后 `-SwitchToWorkflow` / `-RollbackToBranch` 才能用 API 走；
   不换就只能人点 Settings。**当前不影响发版**（legacy 已恢复）。
2. **`deploy/pages.yml` 是早期草稿**（`on: push: main` + 上传 `site/dist`，但 `site/dist` 被 gitignore，CI 里永远拿不到内容，
   且现在 `build_type=legacy` 会直接失败）。建议删除或明确标注废弃，真正的兜底是 `.github/workflows/pages-fallback.yml`。
   不在我的写权限（`deploy/pages_*`）内，留给人/Lead 决定。
3. **1 GB 上限**：v0.9.5 只剩 53.8 MiB 余量，本版瘦身后 111.3 MiB。再涨一版就该做结构瘦身（`name/` 77k 页、`data/` core.json 10 MB gzip）。
4. 本报告与三个新文件**都没有 commit**，等 Lead 统一提交。
