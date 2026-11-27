# v1.2.8 发布就绪检查（LANG1-A · 2026-11-28）

> **结论：发布通道就绪；发布输入未就绪 → B 段（生产构建 / 发布）暂不能开工。**
> 检查时刻：北京 **2026-11-28 05:10**（只读；未 build / 未 sync / 未写库 / 未改源码，源码状态为快照，工位仍在写）。
> 预算：Lead 预批 **planned ≤ 20,000**、当月累计 **≤ 700,000**；现查当月 **528,731 = 52.9%**（余 171,269）。

## 1 通道就绪（可复核）

| 项 | 状态 | 数字 / 证据 |
|---|---|---|
| rclone | ✅ | `tools\rclone.exe` **v1.76.0**；`sync_r2.ps1` L491 固定 `Join-Path $Root 'tools\rclone.exe'`，不在 PATH 无碍 |
| 凭据 | ✅ | `.env` 有 `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET`（另有 `GITHUB_TOKEN`）；rclone.conf 由脚本在 `%TEMP%` 临时生成后删除 |
| T19 排除 | ✅ | `sync_r2.ps1 -ShowAssetExcludes` exit 0：**9 条精确 exclude**、0 expired / 0 invalid / 0 wildcard；lang-root `fr/ ko/ ja/ cs/ lv/` 5 键兜底不动 |
| 线上 | ✅ | `verify_live --base https://drugcrossref.com`（只跑一次）→ **live v1.2.7 / 54 checks / 0 F / 0 W / 18.5 s / exit 0** |
| dist | ✅ | **362,112 文件 / 3,283.1 MiB / 0 字节文件 0**；最新 mtime 2026-11-26 14:33 = v1.2.7 产物，未被改动 |
| 台账 | ✅ | 2026-11 共 **12 行 / 528,709 PUT**；+ assets·lang-root 22 = 实际 **528,731 = 52.9%**（<700k 预批线、<900k 停线、不进计费） |
| 磁盘 | ✅ | D 剩 **34.3 GB**（dist 3.2 GiB） |
| A/B 工具 | ✅ | `deploy/dist_diff.py` 可用（`--before/--after/--write-manifest`；清单 UTF-8 无 BOM，T16 内建 BOM 告警）。**缺 v1.2.7 after 清单** → B 段先写 `.tmp/v128-dist-before.tsv`（参照 v1.2.7：362,112 行 / 122 s） |
| 空闲 | ✅ | 检查时无 `python` / `rclone` 进程；`.tmp/ref*.tsv` 是 data-scout 只读分析在写，不碰 dist |

## 2 未就绪的输入（B 段硬前置；**05:10 快照**，frontend 之后的进展见 §6 末尾）

| 前置 | 现状（05:10 快照） | 责任 |
|---|---|---|
| `CHANGELOG.md` v1.2.8 节 | ❌ 顶部仍是 `## v1.2.7 — 2026-11-27` → 版本号唯一来源缺，**build 只会产出 v1.2.7** | frontend |
| `site/build.py` I18N nb/ms | ⚠️ 已改（+157/−33：LANGS 改注册表驱动、`NB_I18N/MS_I18N = {}` 占位已就位），**译文尚未合入**；`.tmp/i18n_nb_ms.json` 还不存在 | frontend（等 i18n-translator） |
| release notes v1.2.8 × 11 语 | ❌ `data/release_notes_i18n.json` 95 版 / 375 条，无 `v1.2.8` → 构建会以 `release-latest-missing` 中止 | frontend + Lead 机械并入 |
| 注册表 / 门禁（backend） | ✅ `data/languages.json` 11 语启用、`data/markets.json` 18 市场 ui_languages +nb/ms、JP→ja / CZ→cs / LV→lv、MY/NO gaps=[]；`unittest:markets-registry` 已进 `ci_checks` job 名单；自测 **61 tests OK / 0.69 s** | backend（已完成） |
| 源码 commit | ❌ 改动全未提交（`git status`：8 项 M/??）→ **tag 只能打 commit，需 Lead 先提交 v1.2.8 源码** | Lead |

## 3 门禁覆盖缺口（需 Lead 一句话）

- `deploy/verify_live.py` L103–105 `LANG_ROOTS` **硬编码 9 语**，不含 `/nb/` `/ms/`；`lang-root-*` / `hreflang-*` / `hero-direct-text` / `i18n-pack-version` 都按它遍历 → 新语言的 404 与裸键名**不会被发布门槛发现**。
- `deploy/i18n_check.py` L88 `LANGS` 9 语、`RELEASE_LATE_LANGS` 无 nb/ms → release notes 只按 9 语判。
- 两文件不在 task-1/2/3 写作用域，也不在我 task-4 writeScopes（只列 `site/dist`、`data/r2_put_ledger.jsonl`、两份报告、`.tmp`）。**建议授权我在 B 段前补**（`deploy/` 属 release 默认写权限），否则 11 语只有「frontend 自验过」、门槛没查。

## 4 B 段执行计划（Lead 明确放行后；全程 T15 前台 / 同轮 `job_output(wait)`）

1. build 前 `deploy/collect_legacy_assets.ps1`：现 dist 的 `assets/boot.f3ac44a3f1.js` 未登记进 `data/legacy_assets.json`（9 条），不跑则本版发完旧缓存页缺脚本（REL6）→ 再 `dist_diff.py --write-manifest .tmp/v128-dist-before.tsv`
2. `& $py site/build.py` 到 `== done ==`（预计 ≈740 s；执行器 600 s 上限 → 转后台后**同一轮** `job_output(wait)`，T15）
3. `& $py deploy/ci_checks.py` 全量 **0 FAIL**（job 数 +1 = `unittest:markets-registry`，记录 PASS/FAIL/SKIP 与新总数）
4. A/B：`dist_diff.py --before .tmp/v128-dist-before.tsv --after site/dist`；**页面 removed 必须 0**、长尾六类（name/drug/combo/maker/atc/cat）0 差异——本版非 T14-D，按常规 ≤500 文件口径
5. `sync_r2.ps1 -DryRun`：**planned ≤ 20,000（已预批）且 `Deleted: 0`（T19）**；超 20,000 或 projected 当月 >700,000 立即停报
6. `powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\sync_r2.ps1`（预计 2–5 min；v1.2.7 实测 305 s / 实际 112 PUT）
7. `verify_live --base https://drugcrossref.com --expect-version v1.2.8 --compare-dist` 必须 **0 F / 0 W**；失败只重试 1 次
8. tag `v1.2.8`（打在 Lead 的源码 commit 上）+ GitHub Release（正文 = CHANGELOG v1.2.8 节逐字）→ 报告 `reports/2026-11-28-v128-release.md`

## 5 需要 Lead 一句话

1. **放行 B 段**（明确「开工 v1.2.8 发布」）；在此之前我不 build、不动 dist。
2. `verify_live` / `i18n_check` 扩到 11 语：**我改**（deploy/）还是另派？
3. 先提交 v1.2.8 源码并告知 commit 短号（tag 要打它）。
4. 预算口径确认：planned ≤ 20,000 预批；超 20,000 或当月 >700,000 立即停报（AGENTS 900k / 1M 计费线仍未变）。

## 6 A′ 段（05:25）：9 语硬编码 → 注册表驱动（Lead 05:12 授权）

> 结论：**4 个门禁文件改完，验收 4 条全绿；未 build / 未 sync / 未碰 `deploy/ci_checks.py`。**
> 语言清单唯一真相源 = `data/languages.json`（现 11 语），三处门禁自动跟随，不再手写 9 或 11。

| 文件 | 改动 |
|---|---|
| `deploy/verify_live.py` | `LANG_ROOTS` → `registry_lang_roots()` + `resolve_lang_roots(strict)`：带 `--expect-version`（发布门槛）按注册表全集 fail-closed；不带（巡检）收窄到「注册表 ∩ `site/dist` 实有语言根」，否则旧产物会被新注册表判假 FAIL。URL / dist 路径统一小写（`/zh-Hant/` 404、`/zh-hant/` 200 的坑）。 |
| `deploy/i18n_check.py` | `LANGS` 改为注册表 enabled 推导（兜底 `LANGS_FALLBACK` 9 语）；`FLAT_LANGS` + `NB_FLAT_TABLES`/`MS_FLAT_TABLES`（frontend 确认 nb/ms 是扁平表 `NB_I18N`/`MS_I18N` + `_install_nb_ms()`）；`RELEASE_LATE_LANGS` 加 `nb/ms → v1.2.8`（历史 95 版不追溯，否则成片 FAIL）；`effective_i18n()` / `run()` 接 nb/ms 与 stats；摘要标题不再写死语言。 |
| `deploy/fix_fr_root.py` | `LANG_ROOTS` → `registry_lang_roots()` = enabled − 4 条 Transform Rule 语言，兜底表仍 5 语；现算 **fr, ko, ja, cs, lv, nb, ms（7）**。 |
| `deploy/sync_r2.ps1` | `$FallbackLangs` 同上由注册表推导（PowerShell 读 JSON，文件仍 ASCII-only）；T19 排除清单随之为 **7 条精确 regex**（新增 `{{^nb/$}}` / `{{^ms/$}}`，0 通配）；`$BudgetExtra = 17 + N` → **24**（原 22）。 |

**验收（05:20–05:25，命令 + 数字）**

- `py_compile` × 3 个 .py：全部 exit 0；`i18n_check.py --self-test`：**全部通过**（自检「全部启用语言齐」用例已补 nb/ms）。
- `i18n_check.py`：**FAIL 0 / WARN 30 / INFO 45，exit 0**（`HEAD` 基线 **0/28/43**）；+2 WARN = ms `form.kit`/`form.gas` 与英文同形（仅 WARN，es 早已同形）。
- `verify_live.py --base https://drugcrossref.com`：**54 passed / 0 F / 0 W，exit 0**（= Lead 要求）。
- `verify_live.py --expect-version v1.2.7`（严格模式自测，**预期红**）：57 checks，`/nb/` `/ms/` **404** + `hreflang-links 9 < 11` = 3 FAIL → 证明 v1.2.8 发布门槛按 11 语 fail-closed：发版前必红、发完转绿。
- `fix_fr_root.py --dry-run --check-remote`：exit 0；5 个现存键「已一致 → 跳过」，`nb/` `ms/` 因 dist 还是 v1.2.7 无源文件（WARN 跳过）→ 0 PUT。**行为变化：默认清单 5→7；v1.2.8 首发若 nb/ms 键缺失会 +2 PUT（已计入 24）。**
- `sync_r2.ps1 -DryRun`（只读预演，**未 sync**）：exit 0；`lang-root-keep: 7 exact --exclude(s)`、`assets-keep: 9`、planned **0**（dist 未变）、projected 当月 **528,733 = 52.9%**（BudgetExtra 24）、无 `Deleted`。

**nb/ms 同形词白名单 22 条（逐条登记，供 frontend 复核）**：nb 16 = 国名 5（Mexico / Canada / Singapore / Japan / Latvia）+ `dose`×3、`status`×3、`form`×4、`synonym`×2、`sponsor`；ms 6 = Mexico、Latvia、Status×2、`unit.万iu`（10k IU）、`nav.menu`（Menu）。若 frontend 认为某条该译，删掉对应条目即恢复 FAIL。
→ **frontend 2026-11-28 05:55 逐条复核：0 条需改，22 条全部保留**；另确认 ms `form.kit`（kit）/ `form.gas`（gas）亦为真同形，保持 `pseudo-suspect` **WARN**（与 es 的 kit/gas 先例一致，不阻塞）。

**风险 / 遗留**：① 巡检模式依赖 `site/dist` 存在；dist 不存在时退回注册表全集（fail-closed，会给旧站 +2 假 FAIL，属预期）。② 严格模式在 v1.2.8 上线前跑必红（预期，不是回归）。③ 05:20 快照：frontend 已写入 `CHANGELOG v1.2.8`、11 语 notes（96 版）与 `NB_I18N`/`MS_I18N`；仍差 Lead 提交源码 + frontend 自验回报。

## 7 B 段口径确认（Lead 05:35 问的三件）

1. **发布后两向 `rclone check` 已同步带这 7 条排除**（不用再改）：`sync_r2.ps1` 两处 check —— L588 `-CheckOnly`（`--size-only --one-way`）与 **L744 发布后两向**（`--size-only`，v1.2.7 的「N differences → exit 1」就是这里）—— 都传 `@confArgs @AssetExcludes @LangRootExcludes`；`$LangRootExcludes` 由 `$FallbackLangs` 生成，现 **7 条**（fr ko ja cs lv nb ms），与主 sync 的 `--exclude` 同源同批。`-DryRun` 实测已打印 `lang-root-keep: 7 exact --exclude(s)`。
2. **PUT 拆分口径（B 段报告按此写）**：`本次 PUT = 主 sync（rclone 最后一条 Transferred: N/N）+ assets 17（稳定名 + Cache-Control，--ignore-times）+ lang-root 7（上界；T19 保活 + md5 相同即跳过，常态 0，首发若 nb/ms 键缺失则 +2）`。预算门禁用 `planned + 24`（17 + 7）当上界，只高估不低估。
3. **planned 真数字在 build 后**：现在 `-DryRun planned 0` 正常（dist 仍是 v1.2.7 产物）；B 段构建完**必重跑一次** `-DryRun`，预批线 **≤20,000**、`Deleted` 必须 **0**，超线或 `Deleted > 0` 立即停报。
4. **`verify_live` 严格模式 3 FAIL 保持原样**（`/nb/` `/ms/` 404 + `hreflang 9 < 11`）：这是发版前的预期红，不改代码；B 段发版后应转 11 语全绿。

## 8 B 段执行记录：**中止在 A/B 红线 + 预算门禁**（2026-11-28 06:01 北京，未上线）

> **后续（07:14）：Lead 定方案 B（长尾切换器钉回九语）→ 重建后已上线 v1.2.8，见 [reports/2026-11-28-v128-release.md](2026-11-28-v128-release.md)。本节保留中止记录与根因，作为「长尾页不能内联语言清单」的证据。**

> 按 Lead「长尾 0 差异 / planned ≤20,000，超线即停报，不要硬发」：**未跑全量 CI、未 sync、未 verify、未打 tag**，`site/dist` 停留在本地新构建，线上仍 v1.2.7。

**已完成的前置与构建**

| 步骤 | 结果 |
|---|---|
| REL6 `collect_legacy_assets.ps1`（build 前） | exit 0；manifest **9 → 10 条**（+ `assets/boot.f3ac44a3f1.js`，expires 2026-12-28） |
| A/B 基线 `dist_diff.py --write-manifest` | `.tmp/v128-dist-before.tsv`，**362,112 行 / 40,366,234 B / 96.8 s / UTF-8 无 BOM（T16 ✓）** |
| 生产构建 `site/build.py` | **exit 0 / 727.2 s / `== done ==`**（T15：后台起 + 同轮 `job_output(wait)` 挂住） |
| dist 现查 | **362,128 文件 / 3,381.1 MiB / 0 字节 0 / 语言根 10 个**（cs es fr ja ko lv ms nb zh zh-hant） |

**A/B 四类（`--before .tmp/v128-dist-before.tsv --after site/dist`，97.2 s）**

- added **17**（ms 7 / nb 7 / assets 3：`i18n.nb.js` `i18n.ms.js` `boot.4b056daa02.js`）；removed **1**（仅旧哈希件 `assets/boot.f3ac44a3f1.js`，已进 REL6 保活）；changed(size) **349,607**；changed(content-only) **8**。
- **页面 removed = 0 ✓**；但**长尾六类全部 changed(size)**：`name` 163,379 / `product` 144,000 / `drug` 16,350 / `maker` 15,213 / `combo` 9,399 / `atc` 1,166 / `cat` 16 → **不是预期的 0 差异**。

**根因（抽样逐 token 核对：不是 hreflang、不是版本号）**：**语言切换器从 9 项变 11 项，内联到每一页**。

| 抽样（新 dist vs 线上 v1.2.7） | 证据 |
|---|---|
| `name/tylenol-8-hr-arthritis-pain.html` | 188 → 194 tokens / **+101 B**：新增 `<a data-lang="nb" href="?lang=nb">Norsk bokmål</a>`、`data-lang="ms"`；hreflang 仍 1 条、无 `v1.2.8` |
| `drug/atorvastatin.html` | **+7,132 B**：每行新增 `lang-block` nb/ms 文案（`Full liste i datapakken` / `Senarai penuh dalam pakej data`） |
| `product/AU-10001J-xifaxan-56fd56.html` | `data-lang` **9 → 11** / `?lang=` 9 → 11 / **+102 B** |
| `zh/index.html` | `data-lang` 9 → 11、`lang-block` 217 → 265 / **+5.6 KB** |
| `assets/app.js` | 191,952 → 192,581（**+629 B**，= frontend 的 P0 `norm()` NFD 修复，单文件） |

**预算门禁（`-DryRun`，只读，未上传）**：**exit 3 拒绝** —— `planned=349,632 + assets/fallback 24` → projected 当月 **878,365 PUT = 87.8%**；原因行 `planned 349,632 > 50,000: needs Lead approval + explicit -ApproveLarge`。`assets-keep: 10`、`lang-root-keep: 7` 均正常。

**两个选项（等 Lead 拍板，我不自行选）**

- **A｜批准近全量**：planned 349,632 + 24；当月 **878,387 = 87.8%**（未过 900k 停线、不进计费，但远超 700,000 预批）；sync 预计 30–40 min；需 Lead 明确 `-ApproveLarge` 授权。
- **B｜收回长尾语言切换器（推荐）**：frontend 让长尾六类页保持 9 项（或改共享 JS 动态注入），重构建 ~12 min 后 planned 应回到小增量（nb/ms 14 页 + 顶部 9 语页 + 2 i18n + assets 17 + lang-root 7），符合 v1.2.7 的「长尾页不含语言胶囊」假设与 ≤20,000 预批。

**未做**：全量 CI、`-DryRun` 真发、`sync_r2.ps1`、`verify_live`、tag/Release —— 等决定后再动。
