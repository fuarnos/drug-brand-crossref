# 最小 CI（GitHub Actions + 本地同一入口）— 2026-10-30

> task-24。目标：在**不改业务代码**的前提下，给 main 加一条能挡合并的自动化检查，
> 并让「CI 跑什么」和「发布前本地跑什么」完全一致。只读：不发布、不写库、无付费服务、无 secrets。

## 0. 结论

- 新增 `.github/workflows/ci.yml`：push / PR 到 `main`（以及手动 `workflow_dispatch`）触发，跑 **`deploy/ci_checks.py`**。
- 新增 `deploy/ci_checks.py`：CI 与本地发布前**同一个入口、同一套判定**；本地全量实测 **8/8 PASS（708.3s，trilingual 672s）**。
- 发布路径不变：仍然只能在本地 `deploy/publish.ps1`；CI 不构建、不发布、不写库、不需要任何 secret。
- 分支保护需人工在仓库 Settings 点一次（步骤见 §5），之后 PR 不绿不能合并。

## 1. 文件与职责

| 文件 | 作用 |
|---|---|
| `.github/workflows/ci.yml` | GitHub Actions 工作流：checkout → Python 3.12 → `python deploy/ci_checks.py --verbose`；`permissions: contents: read`，无 secret |
| `deploy/ci_checks.py` | 唯一检查入口（Python 3.12 标准库）：py_compile、三套 unittest、trilingual（有 DB 才跑）、`db/check_data.py`（有 DB 才跑）、`site/dist` 完整性（有 dist 才跑）、workflow 自检 |
| `reports/ci-setup.md` | 本报告 |
| `README.md` §跑起来 | 新增「CI 与本地门槛一致」小节 |
| `DEPLOY.md` | 新增「CI（测试 + 内容完整性）」；改写「为什么发布不交给 GitHub Actions」；上线前检查加一条 |

本地入口：

```powershell
& $py deploy/ci_checks.py          # 全量（含 trilingual，约 10 分钟）
& $py deploy/ci_checks.py --fast   # 跳过 trilingual / check_data（改代码时用，约 16 秒）
```

退出码：`0` = 全过（允许 SKIP）；`1` = 有 FAIL。

## 2. CI 跑什么 / 跳过什么

| 检查 | 本地（有 DB/dist） | GitHub CI | 说明 |
|---|---|---|---|
| `py_compile` 全仓 Python（etl/lib/site/db/mobile/deploy/tests） | ✅ 135 文件 | ✅ | 语法门槛 |
| `etl` unittest | ✅ 25 项 | ✅ | |
| `lib` unittest | ✅ 29 项 | ✅ | |
| `mobile` unittest | ✅ 29 项 | ✅ | |
| `tests/trilingual/run_tests.py` | ✅（约 672s） | ⏭ SKIP | 需要 `data/drugs.db`（gitignore，CI 无库） |
| `db/check_data.py` | ✅ | ⏭ SKIP | 同上，只读 |
| `site/dist` 完整性（根文件 / core.json / sitemap 数 / 0 字节 / node --check） | ✅ 112,822 文件 | ⏭ SKIP | dist 是生成物、不入库 |
| workflow 自检 | ✅ | ✅ | 防止 ci.yml 被误删/改名 |

> 为什么 CI 里跳过 DB/产物：`data/*.db`、`site/dist` 都在 `.gitignore`（AGENTS §9），
> 仓库里没有它们；把几百 MB 文件塞进 CI 不划算，也没必要（发布本来就只在本地）。
> **发布前在本地跑全量**这一条已写进 DEPLOY.md 上线前检查。

## 3. trilingual 的 allowed-failures（4 项，逐步清零）

`tests/trilingual/run_tests.py` 的基线是 **72 例 / 354 查询 / Top-5 97.7% / 跨国 72/72**；
以下 4 例是**词表覆盖类**已知缺口（与 v0.9.1 发布前基线一致，非回归），在
`deploy/ci_checks.py` 的 `ALLOWED_TRILINGUAL_FAILURES` 登记，**只有这 4 个 (案例, 类别) 允许失败**：

| 案例 | 类别 | 现象（查询） |
|---|---|---|
| metformin | combo | zh「西格列汀二甲双胍片」Top-1 落到 Sitagliptin |
| ciclosporin | dup_inn | en「cyclosporine」/ es「ciclosporina」未进 Top-1 |
| beclometasone | dup_inn | en「beclomethasone」/ es「beclometasona」未进 Top-1 |
| chlorphenamine | dup_inn | en「chlorpheniramine」/ es「clorfenamina」未进 Top-1 |

判定规则：出现**未登记**的 `[FAIL]`、或案例数 < 72、或通过数 < 68 → CI 红。
清零后从 allowlist 删掉对应行即可（脚本里有注释）。

## 4. 本地验证证据（2026-10-30）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py deploy/ci_checks.py --fast --verbose   # 6 PASS / 2 SKIP，16.2s
& $py deploy/ci_checks.py --verbose          # 8 PASS / 0 FAIL / 0 SKIP，708.3s
```

全量结果：

```
[PASS] py_compile         135 个 Python 文件编译通过
[PASS] unittest:etl       Ran 25 tests ... OK（0.2s）
[PASS] unittest:lib       Ran 29 tests ... OK（0.9s）
[PASS] unittest:mobile    Ran 29 tests ... OK（5.3s）
[PASS] trilingual         72 例通过 68，跨国 72/72，已知缺口 4（672.0s）
[PASS] check_data         exit 0
[PASS] dist-integrity     112,822 文件 / sitemap 63,359 URL / 0 字节 0 / node 未安装跳过
[PASS] workflow           ci.yml 存在且引用同一入口 deploy/ci_checks.py
8 项：PASS 8 / FAIL 0 / SKIP 0（708.3s）
```

`ci.yml` 用 PyYAML `safe_load` 校验通过（job `checks`，3 个 step）。

## 5. 分支保护（需人工在 GitHub 点一次）

Settings → Branches → **Add branch protection rule**：

1. Branch name pattern：`main`
2. 勾选 **Require a pull request before merging**（可选，按团队习惯）
3. 勾选 **Require status checks to pass before merging**
4. Status checks 里选 **`tests + integrity`**（workflow `ci` 的 job 名）
5. Save

之后：PR 的 CI 不绿不能合并；直接 push main 仍可用（CI 会跑但不会阻止 push，
若要连 push 也挡，需改用 ruleset/PR-only 流程）。

## 6. 已知缺口 / 后续

1. **CI 里 trilingual / check_data / dist 完整性都会 SKIP**：CI 没有 DB 与产物。
   这是有意的（不入库大文件）；发布前本地全量跑是硬门槛（DEPLOY 上线检查第一条）。
   可选后续：把 `data/sources/` 的小快照做成 fixture DB 给 CI 跑 subset；或用 nightly 在
   有缓存的自托管机器跑全量。
2. **`node --check` 实际未执行**：本地没装 node，CI 的 runner 有 node 但没有 `site/dist`。
   该检查逻辑已就位（有 dist + 有 node 就跑），等本地装 node 或 v0.9.2 拆出内联 JS 后可覆盖。
3. **CHANGELOG**：本任务不单独占版本条目，随 v0.9.2 版本节写一句「新增最小 CI」。
4. CI 不发布、不写库、不依赖任何 secret；`deploy/pages.yml` 仍未启用，发布仍走 `deploy/publish.ps1`。

## 7. CI 首次运行（verification）

- 触发：commit **`c5d20776d`** push 到 `main`（2026-10-30）。
- Run：<https://github.com/fuarnos/drug-brand-crossref/actions/runs/40942725745> → **success**；
  job `tests + integrity`，全部 step 绿：Checkout / Set up Python 3.12 / **Run checks (same entry as local)**。
- 运行内容：py_compile + etl/lib/mobile 三套 unittest + workflow 自检；trilingual / `check_data` /
  dist 完整性按设计 SKIP（GitHub 上没有 `data/drugs.db` 与 `site/dist`）。
- 待人工：按 §5 在仓库 Settings 把 `tests + integrity` 设为 required status check（设好后 CI 不绿即挡合并）。
