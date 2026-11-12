# 发布链修复 · `sync_r2.ps1` python fallback + 并发默认值（task-9）

> 2026-11-13 · 工位 **pages-deploy** · 结论先行
> 范围：只改 `deploy/`；**未 commit、未重新发布、未上传 dist、未动 site/data/DB**。
> 唯一一次 R2 写入 = `fix_fr_root.py` 的**幂等 PUT**（同内容 `fr/`，138,139 B），按任务要求执行。

## 0. 结论

1. **`/fr/` 兜底静默失败已修**：根因不是「PATH 里没有 python」，而是本机 `python` 解析到了
   `C:\Users\asus\AppData\Local\Microsoft\WindowsApps\python.exe`——Microsoft Store 应用别名，
   **exit 9009、没有任何输出**。旧代码 `else { 'python' }` 正好踩中它，`fix_fr_root.py` 从未执行。
   现已改为显式解析 + **能力探针**（能启动且能 `import botocore`），顺序
   `$env:PYTHON → python → py → 运行时路径`；解析不到时 WARN 写清「`/fr/` 会 404 + 加第 5 条 Transform Rule」
   并记录 `exit 9009`。
2. **并发默认值 32 → 64**：同一批 125,510 文件实测 **55m13s → 21m15s（2.60×）**，两次都是 exit 0 /
   0 differences；R2 Class A 写入数不随并发变化（≈11.7 万次/全量，免费额度 100 万/月），
   rclone 侧 64 并发最坏 ≈1 GiB 缓冲上限（实际文件均值 7.8 KB）。**结论：默认改 64 安全**，
   保留 `-Transfers 32` 作为 429/503 或内存吃紧时的回退，实测数字已写进脚本头注释。
3. **顺带修了验证路径**：`-CheckOnly` 原来的严格双向 `rclone check` 在健康 bucket 上**永远失败**——
   因为 `/fr/` 兜底对象按设计不在 dist 里（首次跑就复现：`1 differences / 1 files missing`）。
   改为 `--one-way`（本地每个文件都必须在远端，忽略兜底对象与待删除的旧对象），
   复跑 **exit 0 / 44 s / 0 differences / 125,510 matching**。
4. `/fr/` 现状复核：`fix_fr_root.py` **PUT 200**；`https://drugcrossref.com/fr/` 与 `/fr/index.html`
   均 **200**，138,139 B，sha256 与本地 dist **完全一致**；只读 `verify_live` **42/42 / 0 failures / 0 warnings**
   （`lang-root-/fr/` 与 `hreflang-target-fr` 均 True）。

## 1. 改动（仅 `deploy/sync_r2.ps1`，+95 −12）

`deploy/fix_fr_root.py` **未改**（不需要改，它本身是幂等的）。`git status` 只有 `M deploy/sync_r2.ps1`。

### 1.1 python 解析：显式 + 能力探针

旧代码（v0.11.5 首轮 404 的直接原因）：

```powershell
$pyExe = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
& $pyExe (Join-Path $PSScriptRoot 'fix_fr_root.py') --dist $Dist
```

本机实测：

| 候选 | 实际解析到 | 探针结果 |
|---|---|---|
| `$env:PYTHON` | 未设置 | — |
| `python`（PATH） | `...\Microsoft\WindowsApps\python.exe` | **exit 9009**（商店别名，无输出） |
| `py`（PATH 启动器） | `...\Python\Launcher\py.exe` → Python **3.15** | 能启动，但 **`import botocore` 失败** |
| `py -0p` 另装版本 | `Python312\python.exe` | 同样 **无 botocore** |
| 运行时路径（AGENTS.md §2） | `C:\Users\asus\.dsh\...\python\python.exe` (**3.12.14**) | **botocore 1.43.127 ✓** |

新逻辑（脚本第 73–132 行附近）：

- 候选顺序按 AGENTS.md §2：`$env:PYTHON` → `Get-Command python` → `Get-Command py` → 运行时路径；
- 每个候选做 `& $Exe -c 'import botocore'` 探针（`fix_fr_root.py` 靠 botocore 做 SigV4 签名，
  「能启动」不够——直接用 `py` 会以 exit 2 失败）；
- `\WindowsApps\` 别名按路径**直接跳过**（不执行，避免弹 Store），日志仍注明 `exit 9009`；
- 成功时打印 `fr/: python = <路径> (via <来源>; botocore ok)`，失败时逐条打印 skip 原因，
  便于下次发布日志一眼定位。

**退出语义保持不变**：`/fr/` 兜底失败仍然只 WARN，不让「sync 本身成功」变成失败。理由有两条：
① rclone 同步确实已完成，改退出码会误导回滚；② 发布门槛 `verify_live.py` 把 5 个语言根（含
`/fr/`）都当硬检查（`LANG_ROOTS`），`/fr/` 坏了发布**不可能 0 failures**——本次实测
`verify_live` 42/42、`lang-root-/fr/` True 可证。无 python 时 WARN 文案：

```
WARN: /fr/ fallback NOT written (fix_fr_root.py exit 9009 = no usable python: tried
$env:PYTHON, python, py, runtime path; all missing or lacking botocore);
https://drugcrossref.com/fr/ will 404 until the 5th Transform Rule is added in Cloudflare.
```

### 1.2 `-Transfers` 默认 32 → 64：评估依据

**实测（v0.11.5 发布报告 `reports/2026-11-13-v0115-release.md` §5）**：

| 并发 | 耗时 | 结果 |
|---|---|---|
| 32 | **55m13s**（09:36:09→10:31:22） | exit 0、0 differences、125,510 matching |
| 64 | **21m15s**（10:49:58→11:11:13） | exit 0、0 differences、125,510 matching |

2.60× 加速，高于线性 2×：单文件均值 **7.8 KB**（974,169,676 B / 125,510），瓶颈是每请求往返延迟，
不是带宽。依据分三块：

- **R2 免费额度**：Class A 免费 **100 万次/月**、Class B 1,000 万次/月、存储 10 GB-month
  （[R2 Pricing](https://developers.cloudflare.com/r2/pricing/)）。一次全量 ≈**11.7 万次 PUT**
  （dry-run 口径 116,862 文件），占月额度 **11.7%**；v0.11.5 两次发布 ≈23.4%。**并发数不改变操作数**，
  所以 64 不会多花钱；`-CheckOnly` 的 `rclone check --size-only --fast-list` 以分页 LIST 为主
  （≈125 次对象列举，Class A），单次 44 s，对额度与限流都可忽略。
- **错误率 / 限流**：R2 文档只对**桶管理操作**（50 次/秒）、`r2.dev` 公共端点（数百 req/s 会 429）
  和**同一对象键并发写 >1 次/秒**（429）给出限制；S3 API 写**不同**对象键没有公布速率上限
  （[R2 Limits](https://developers.cloudflare.com/r2/platform/limits/)）。本项目走自定义域、写 12.5 万个
  **不同**键，64 并发在文档范围内。两次 64 并发实跑均 exit 0 / 0 differences，未观察到 429/503；
  rclone 自带 `--retries 3` / `--low-level-retries 10`（默认值，本机 `rclone help flags` 复核）。
  日志只留了摘要（rclone 默认不打印逐文件统计），**没有**逐请求重试计数——这是证据缺口，已在 §4 写明。
- **内存**：rclone `--buffer-size` 默认 **16 MiB / transfer**、`--max-buffer-memory` 默认 **off**
  （本机 rclone v1.76.0 `help flags` 复核），64 并发最坏 **≈1 GiB**；实际文件均值 7.8 KB，
  分配远低于上限；v0.11.5 的 64 并发实跑稳定完成（无 OOM/中断）。本机总内存因沙箱拒绝 WMI
  （`Win32_ComputerSystem` 拒绝访问）**未能取到**，这是本评估的证据缺口。
- **回退**：脚本头注释写明「R2 返回 429/503 或机器内存吃紧 → `-Transfers 32`」；如未来需要更省内存，
  可加 `--max-buffer-memory`（本次未加，保持最小改动）。

### 1.3 `-CheckOnly` 改为 one-way（验证时发现并修复）

首次 `-CheckOnly`（严格双向）：

```
check: ... (size-only)
ERROR: rclone check failed        # 46 s
ERROR : fr/: file not in Local file system at ...\site\dist
NOTICE: ... 1 differences found / 1 errors while checking / 125,510 matching files
```

`fr/` 是 `fix_fr_root.py` 故意写进 bucket 的合成对象（不在 dist 里），所以健康 bucket 上严格双向 check
**必然失败**。改为 `--size-only --one-way`（本地每个文件都必须存在于远端、尺寸一致；
忽略合成对象与「同步时会删掉的旧对象」）。复跑：

```
check: ... (size-only, one-way)
check: OK (size-only, one-way)          # 44 s，0 differences / 125,510 matching，exit 0
```

上传后的严格 `rclone check`（脚本内、`fix_fr_root.py` 之前）**保持原样**，没有放宽。

## 2. 验证（不重新发布 / 不上传 dist）

### 2.1 解析逻辑 4 个场景（Windows PowerShell 5.1，`powershell -NoProfile -File`）

从 `deploy/sync_r2.ps1` 用 AST 抽出 `$FrRuntimePython` + `Test-FrPython` + `Resolve-FrPython`，
在受控 PATH / 环境变量下调用（脚手架 `.tmp/test-resolve-fr-python.ps1`，临时文件、未提交）：

| 场景 | PATH / 环境 | 结果 |
|---|---|---|
| `real` | 本机真实环境，无 `$env:PYTHON` | skip python（Store 别名 exit 9009）→ skip py（无 botocore）→ **runtime 3.12.14（botocore ok）** ✅ |
| `no-python-path` | `PATH=C:\Windows\System32;C:\Windows`，无 `PYTHON` | **runtime 路径** ✅（正是任务要求的「无 python 的 PATH」模拟） |
| `no-python-at-all` | 同上 + 运行时路径改成不存在的 `C:\__no_such_dir__\python.exe` | 返回 `null` → 走 §1.1 的 WARN 分支（`/fr/` 404 + 第 5 条 Transform Rule + exit 9009）✅ |
| `env-python` | `PYTHON=` 运行时路径 | 优先命中 `via PYTHON` ✅ |

完整输出：`.tmp/task9-resolver-tests.log`（3,834 B）；脚本解析：**0 错误 / 1,078 tokens**。

> **踩坑记录（重要）**：本机 ACP=936（GBK），而 `.ps1` 是 **UTF-8 无 BOM**。我第一版把新增注释写成中文，
> PowerShell 5.1 按 GBK 解码时**吃掉了换行**，产生 1 个 parse error（`line 82: 意外的标记 }`）——
> 也就是说「注释里写中文」足以让发布脚本整体不可执行。已把新增注释/日志全部改成英文（与原脚本风格一致），
> 中文只留在报告里。以后若必须在这个脚本里写中文，请存为 **UTF-8 with BOM**。

### 2.2 `deploy/sync_r2.ps1 -CheckOnly`（只比对，不上传）

```
check: D:\...\site\dist -> r2:drug-brand-crossref (size-only, one-way)
check: OK (size-only, one-way)
NOTICE: S3 bucket drug-brand-crossref: 0 differences found
NOTICE: S3 bucket drug-brand-crossref: 125510 matching files
END: 2026-11-12 11:23:35  EXIT=0  ELAPSED=44s
```

日志：`.tmp/task9-checkonly.log`。全程无 PUT/上传（rclone 子命令是 `check`）。

### 2.3 `fix_fr_root.py` 幂等 PUT + 线上 200

```
local site\dist\fr\index.html: 138139 B sha256=915B3404...612DB2A
fr/ -> PUT 200（138,139 B, text/html; charset=utf-8）   # exit 0, 1 s
https://drugcrossref.com/fr/             status=200 bytes=138139 sha256=915B3404...612DB2A same_as_dist=True
https://drugcrossref.com/fr/index.html   status=200 bytes=138139 sha256=915B3404...612DB2A same_as_dist=True
```

用脚本解析出的运行时 python（3.12 + botocore）执行，**同内容、幂等**。

> **环境限制（不是站点问题）**：本机 `curl.exe`（8.22.0 Schannel）访问 HTTPS 一律
> `curl: (35) schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`（`--ssl-no-revoke` / `-k` /
> `--tlsv1.2` 均 `code=000`）。这是本机 schannel 凭证问题，与 `docs/交接-20261113.md` §4.1 里
> `git push` 要用 openssl 后端是同一类问题。因此 200 校验用 **Python urllib（OpenSSL）** 完成，
> 并做了 sha256 与本地 dist 的逐字节比对；curl 的失败证据也记录在此。

### 2.4 只读线上门禁复核（`verify_live`，不属于发布动作）

```
& $py deploy/verify_live.py --base https://drugcrossref.com --expect-version v0.11.5 --quiet
exit=0  42 checks / 0 failures / 0 warnings / 11 s
lang-root-/fr/          True  /fr/ HTTP 200, 138,139 B
hreflang-target-fr      True  https://drugcrossref.com/fr/ HTTP 200, 138,139 B
```

JSON：`.tmp/task9-verify-live.json`。这证明「WARN-only 也不会让 `/fr/` 404 悄悄上线」——门禁会拦住。

## 3. 数字汇总

| 项 | 数字 | 来源 |
|---|---|---|
| dist | 125,510 文件 / 974,169,676 B（929.0 MiB） | `Get-ChildItem` 现查 + 发布报告 |
| 单文件均值 | 7.76 KB | 974,169,676 / 125,510 |
| 32 → 64 并发耗时 | 55m13s → 21m15s（2.60×） | `reports/2026-11-13-v0115-release.md` §5 |
| 一次全量 Class A | ≈116,862 PUT（≈11.7% 月免费额度） | v0.11.5 dry-run |
| `-CheckOnly`（one-way） | exit 0 / 44 s / 0 differences / 125,510 matching | `.tmp/task9-checkonly.log` |
| `fix_fr_root.py` | exit 0 / 1 s / PUT 200 / 138,139 B | 本次现跑 |
| `/fr/` 线上 | 200 / 138,139 B / sha256 与 dist 一致 | Python urllib 现查 |
| `verify_live` | 42/42 PASS / 0 failures / 0 warnings / 11 s | `.tmp/task9-verify-live.json` |
| 脚本解析 | 5.1 / ACP936：0 errors，1,078 tokens | PowerShell AST |
| 改动 | +95 −12，`deploy/sync_r2.ps1` 单文件 | `git diff --stat` |

## 4. 剩余风险 / 未做 / 建议

1. **`AGENTS.md` §6 第 81 行仍写「增量同步 `--transfers 32`」**（不在本工位写权限内）——
   请 Lead 改成 64 或「默认 64，可 `-Transfers 32` 回退」。`docs/托管迁移执行清单.md` 60–61 行的手工
   rclone 示例也还是 32（手工命令仍可用，只是不是新默认）。
2. **没有做完整 sync 验证**：任务明确禁止重新发布/上传 dist，所以只验了解析函数、`-CheckOnly`、
   幂等 PUT；「下一次真实发布时最终日志出现 `fr/: python = ... (via runtime; botocore ok)` + `PUT 200`」
   才算闭环 → 建议 Lead 在 v0.11.6 发布时确认这两行。
3. **运行时路径是用户特定硬编码**（`C:\Users\asus\.dsh\...`）。换机器/换运行时布局时，前三个候选仍可能命中；
   若都没有，WARN 会指路。建议将来把该路径挪到 `.env`（如 `PYTHON=`）或按仓库相对路径提供，避免再硬编码。
4. **内存证据缺口**：本机 WMI 被沙箱拒绝（`Win32_ComputerSystem` 拒绝访问），拿不到总内存；
   64 并发的 ~1 GiB 缓冲上限是 rclone 语义推算 + v0.11.5 实跑无 OOM，不是实测峰值 RSS。
   如需硬证据，可在下次发布时用 `Get-Process rclone | Select WorkingSet64` 采样（发布窗口内做）。
5. **错误率证据缺口**：rclone 默认不打印逐文件统计，日志里没有重试/429 计数；依据是两次 exit 0 +
   0 differences + 线上 check 125,510 matching。若要把「失败重试数」纳入发布报告，可给 rclone 加
   `--stats 30s --stats-log-level NOTICE`。
6. **`/fr/` 兜底仍是临时方案**：最终解是 Cloudflare 第 5 条 Transform Rule（`/fr/ → /fr/index.html`）；
   规则加好后可连同脚本里的 fallback 段一起删。
7. **`.ps1` 中文 = 雷**：ACP 936 + UTF-8 无 BOM 会破坏解析（本次已踩）。以后动这个脚本要么全英文，
   要么存 UTF-8 with BOM；建议 Lead 在 `docs/` 里记一条。
8. 未 commit（按要求）；报告未改 `CHANGELOG.md`（本次无用户可感知的站点变化）。

## 5. 复现命令（PowerShell，仓库根）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# ① 解析函数 4 场景（脚手架在 .tmp/，未提交）
foreach ($c in 'real','no-python-path','no-python-at-all','env-python') {
  & powershell -NoProfile -ExecutionPolicy Bypass -File .\.tmp\test-resolve-fr-python.ps1 -Case $c
}

# ② 只比对，不上传
& powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\sync_r2.ps1 -CheckOnly

# ③ 幂等 PUT + 线上 200（本机 curl 走 schannel 不可用，用 Python 校验）
& $py .\deploy\fix_fr_root.py --dist .\site\dist
& $py .\.tmp\check_fr_live.py

# ④ 只读门禁（不发布）
& $py .\deploy\verify_live.py --base https://drugcrossref.com --expect-version v0.11.5 --quiet
```

## 6. 证据文件

- `.tmp/task9-resolver-tests.log`（4 场景原始输出）
- `.tmp/task9-checkonly.log`（`-CheckOnly` 全程）
- `.tmp/task9-verify-live.json`（只读门禁 JSON）
- `.tmp/check_fr_live.py`、`.tmp/test-resolve-fr-python.ps1`（临时脚手架，`.tmp/` 已 gitignore）
- `git diff deploy/sync_r2.ps1`（+95 −12）
