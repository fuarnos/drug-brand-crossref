# REL3 / T71：R2 免费额度护栏（PUT 台账 + 发布前月累计拦截）

> 状态：**已完成并自验（2026-11-21 北京谷段）**。只改 `deploy/sync_r2.ps1`；**未跑真实 sync、未构建、未写 `site/dist`、未 commit**。
> 背景：用户 2026-11-20 定「R2 Class A 免费 1M/月是硬预算」；REL2（v1.0.0）已把日常发版从 ~147,348 文件降到 **78 文件/版**（本报告不重复数字，见 `reports/2026-11-20-v100-release.md`）。本任务给下一次发布加护栏。

## 0. 结论

- `sync_r2.ps1` 现在**发布前**读 `data/r2_put_ledger.jsonl` 算当月累计、并先用一次 `rclone sync --dry-run`（**零写入**）拿到 planned 数，再决定是否放行：
  - 当月累计 **≥ 900,000** → **硬停**（exit 3，无 override），打印「停发布报 Lead/报人」；
  - 单次 planned **> 50,000** → 需显式 `-ApproveLarge`（Lead 批准）；
  - 预计发布后当月累计 **≥ 900,000** → 需 `-ApproveLarge`；**≥ 1,000,000** 另打印「需用户批准、批准记录写进报告」。
- **真实 sync 成功后**解析 `Transferred: N / N, 100%` 与 `Elapsed time:`，追加一行 JSONL（`mode=real`）；`-DryRun` **不写台账**，但同样执行上述门禁（会以 exit 3 代替上传）。
- 自验（全部只读 / DryRun，**0 次真实上传**）：模拟台账 950k → exit 3；899,990 + planned 2（projected 900,014）→ exit 3；同参数加 `-ApproveLarge` → exit 0；planned 50,001 → exit 3。`ci_checks.py --fast` **PASS 8 / FAIL 0 / SKIP 5（24.8s）**。
- 已知缺口：**真实 sync 分支的 planned pass + 台账追加**只能在下次真实发布时首次执行（本任务禁止真实 sync）；台账从 0 开始（**不补 v1.0.0 历史行**），11 月周期仍需按 Cloudflare 账单人工核对。

## 1. 台账（`data/r2_put_ledger.jsonl`）

- 格式（一行一次真实发布，UTF-8 无 BOM、LF）：
  `{"date":"YYYY-MM-DD","version":"vX.Y.Z","files":N,"seconds":S,"mode":"real"}`
  - `version` = CHANGELOG 第一节版本号（`Get-ChangelogVersion`；读不到记 `unknown`，不阻塞发布）；
  - `files` = rclone 日志最后一个 `Transferred: N / N, 100%` 的 N（= 主 sync 写入文件数 ≈ Class A PUT；assets 第二遍刻意不打印 NOTICE stats，见 REL2-B 注释）；
  - `seconds` = rclone `Elapsed time:`（解析失败用 stopwatch 兜底）；
  - 只记录**真实** sync；`-DryRun` 不写（也不写 `mode=dryrun`，避免 rehearsal 污染台账）。
- 文件**不预创建**（首次真实发布时由脚本创建）；**不补 v1.0.0 / 更早历史行**（任务明确「不补历史行」）。
- 追加失败只 WARN、不阻断发布（PUT 已花掉；下一次判定会少一条记录，需人工留意）。

## 2. 发布前护栏（顺序）

1. 读台账当月（本地日历月）`mode != dryrun` 的 `files` 合计 → 打印 `budget: month ...`；**≥900,000 立即 exit 3**（在 rclone 之前，不产生任何请求）。
2. **真实 sync**：先跑一次 planning `rclone sync --dry-run`（**零写入**）→ 解析 planned；**DryRun**：本次 dry-run 即 planning。
3. `planned > 50,000` 且无 `-ApproveLarge` → exit 3。
4. `projected = 当月累计 + planned + 22`（22 = 17 assets PUT + 5 语言根兜底 PUT）；`projected ≥ 900,000` 且无 `-ApproveLarge` → exit 3；`≥1,000,000` 打印 WARN（必须已有用户批准并写进发布报告）。
5. 通过后才执行真实 sync（或 DryRun 直接报 OK）。
- 新增参数：`-ApproveLarge`（Lead 批准大发布用；**不能**绕过 900k 硬停）、`-LedgerPath`（测试/运维覆盖台账路径，默认 `data\r2_put_ledger.jsonl`）。
- 退出码更新：`0` 正常、`1` rclone 失败、`2` 缺凭据/rclone/dist、**`3` 预算/批准门禁拒绝**（写进 `.NOTES`）。
- **代价**：真实发布多一次 planning dry-run（实测 dry-run 全站 1m07s、增量产物更短），零 Class A 写入；换来「超预算在花钱之前停下」。

## 3. 实现细节 / 环境坑

- **PowerShell 5.1 读取无 BOM UTF-8 `.ps1` 按 ANSI**：本任务新增的中文注释/提示一度把引号打乱、脚本 parse error → 已把**本工位新增**的字符串/注释全部改成 ASCII 英文；原文件既有的中文（`docs/托管迁移执行清单.md` 等）保持不动。`Parser::ParseFile` 在 5.1 下 **parse OK**。
- **不能用 `2>&1 | Tee-Object` 抓 rclone 输出**：`$ErrorActionPreference='Stop'` 下原生 stderr 行会变成终止性 ErrorRecord，脚本直接退出。改为让 rclone 自己写日志：`--log-file <path>`（NOTICE stats 进文件），再从文件解析；同时对发布日志回显最后 6 行 `Transferred/Deleted/Elapsed` 摘要。
- **rclone 在本机不能写 `%TEMP%`**（实测 `Failed to open log file ... Access is denied`，而仓库 `.tmp` 可写）→ 临时日志放 **`.tmp\rclone\`**（gitignored，唯一文件名含 PID+GUID），脚本结束（含失败）`finally` 删除。
- 真实 sync 的日志仍照旧把 stats 回显到调用方日志；planning pass 只回显摘要（避免 15 万行刷屏）。

## 4. 自验（全部不真实上传）

| # | 场景 | 命令要点 | 结果 |
|---|---|---|---|
| A | 当月台账 950,000 → 硬停 | `-DryRun -Dist .tmp\rel3\probe-dist -LedgerPath .tmp\rel3\ledger-950k.jsonl` | **exit 3**；`ERROR: month-to-date 950,000 PUT is >= 900,000 ... STOP`；rclone **未运行**；台账 sha256 不变 |
| B | 899,990 + planned 2 → projected 900,014 需批准 | `-DryRun ... -LedgerPath .tmp\rel3\ledger-899990.jsonl` | 打印 `planned=2 + assets/fallback 22 -> projected month total 900,014 PUT` → **exit 3** |
| C | 同 B + `-ApproveLarge` | `-DryRun -ApproveLarge ...` | **exit 0**；dry-run 完成；台账 sha256 不变 |
| D | planned 50,001 > 50,000 需批准 | `-DryRun -Dist .tmp\rel3\big-dist -LedgerPath .tmp\rel3\ledger-empty.jsonl` | `planned=50,001` → **exit 3**（"needs Lead approval + explicit -ApproveLarge"） |
| E | 默认台账路径 + 真实 `site/dist` 的 dry-run | `-DryRun`（无 `-LedgerPath`） | `month=0 rows=0`、`planned=0` → `projected 22`、`Deleted: 5`（语言根兜底，原有行为）、**exit 0**；**未创建** `data/r2_put_ledger.jsonl` |
| F | 快速 CI | `& $py deploy/ci_checks.py --fast` | **13 项 PASS 8 / FAIL 0 / SKIP 5（24.8s）** |
| G | PS 5.1 语法解析 | `.tmp\rel2b\parse_check.ps1` | **parse OK** |

证据：`.tmp/rel3/test-a.log` / `test-b.log` / `test-c.log` / `test-d.log` / `dryrun-default.log` / `ci-fast.log`；模拟台账 `ledger-950k.jsonl`、`ledger-899990.jsonl`（`.tmp` 下，不入库）。
说明：`probe-dist` 只有 2 个文件，dry-run 会计划删除 bucket 里 157k 个远端对象（**dry-run 不写**，真实发布不会用这个小目录）；D 的 50,001 文件临时目录已删除。

## 5. 已知缺口 / 下次真实发布要确认

- **真实分支未端到端跑过**（本任务禁止真实 sync）：`planning pass → gates → 真实 sync → 台账追加` 的串联在下次发布首次执行。若台账追加失败只 WARN；发布后核对 `data/r2_put_ledger.jsonl` 是否新增一行、`files` 是否等于主 sync `Transferred: N / N`。
- **台账从 0 起步**：2026-11 周期（用户截图 3.48M / 2.48M 计费）**不补行**，该周期仍需人工对账；12 月起台账可覆盖整月。
- 预算口径按**本地日历月**；Cloudflare 计费周期可能不同，跨周期边界以账单为准。
- `+22` 是当前版固定开销（17 assets + 5 语言根兜底）；若 assets 文件数或语言根数量变化需同步改 `$BudgetExtra`。
- `-CheckOnly` 不触发预算门禁（只读 check）；`-DryRun` 会触发（exit 3 属预期）。
