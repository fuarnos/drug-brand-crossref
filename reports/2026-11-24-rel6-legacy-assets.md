# REL6 过渡 hashed 资源保活自动化（task-2，2026-11-24）

> 工位：release ／ 任务板 `task-2`（REL6，v1.2.2 发布前置）／ 写作用域：`deploy/sync_r2.ps1`、`deploy/collect_legacy_assets.ps1`（新增）、`data/legacy_assets.json`（新增）、本报告。
> **本段只做实现 + 自验：没有跑生产 `site/build.py`、没有跑真实 `sync_r2.ps1`、没有写 `site/dist`、没有 commit。**

## 结论（先行）

| 项 | 结果 |
|---|---|
| 保活名单 | 从「`sync_r2.ps1` 里两条手写 `--exclude`」改为**数据驱动** `data/legacy_assets.json`（精确名 + 过期日），每版不再需要人手补哈希名 |
| 收集入口 | 新增 `deploy/collect_legacy_assets.ps1`（**build 之前**跑，读上一版 `site/dist/assets`；`expires = 收集日 + 30 天`；去重、幂等；`-DryRun` / `-PruneExpired`） |
| sync 侧 | `sync_r2.ps1` 读清单生成**精确** `--exclude`（正则校验，**通配符条目直接 exit 2**），过期条目自动忽略；`-DryRun` 与真实发布都打印「本次保活名单 + 已过期忽略 + 无效忽略」 |
| REL2-B 收敛 | 原有两条手写（`style.885ce0a604.css` / `boot.510d5a90dd.js`，至 **2026-12-20**）**保留**为硬编码兜底，与清单按名字合并（清单行优先），过渡无缝 |
| 自验 | 自测脚本 **63 项断言全 PASS（0 失败，exit 0）**；另有真实 `-DryRun` 端到端 2 次（临时清单 + 假 dist + 临时台账，见 §3.3） |
| 未做 | 生产构建、真实上传、`verify_live`、tag/Release、`CHANGELOG`、commit —— 全部留给 Lead 批准后的「v1.2.2 构建 + 发布」派单 |

## 1. 背景与问题

v1.0.0 起的增量发布契约：长尾页用稳定名 `assets/style.css` / `assets/boot.js`，但**顶层页仍引用带内容哈希的资源名**（`assets/style.<sha256[:10]>.css` / `assets/boot.<sha256[:10]>.js`，生成处是 `site/build.py` 的 `CSS_HASH` 与 `BOOT_JS_FILE`）。
`rclone sync` 是「镜像删除」：新版构建不再生成上一版的哈希名 → 上一版哈希文件在远端被删 → **上一版页面若还在浏览器缓存里，请求这些资源就是 404**。

历史证据（见 `reports/2026-11-22-v110-release.md` §边界）：v1.0.1 发布时把 v1.0.0 的 `boot.882e52f15e.js` 删掉了；REL2-B 之后靠**两条手写精确 `--exclude`** 保住 v0.19.0 的两个名字，**每版都要人记住上一版哈希名**，且已漏过两次（`boot.882e52f15e.js`、`boot.c161b56276.js`）。

REL6 = 把这份名单搬到数据文件里，由脚本自动收集 + 自动过期，且**永不接受通配符**（避免 bucket 无限增长 / 掩盖拼写错误）。

## 2. 改动

### 2.1 `data/legacy_assets.json`（新增，唯一真相源）

```json
{
  "schema": 1,
  "generated_at": "2026-11-24",
  "updated_at": "2026-11-24",
  "retention_days": 30,
  "name_pattern": "^(style|boot)\\.[0-9a-f]{10}\\.(css|js)$",
  "notes": "...",
  "entries": [
    { "name": "style.885ce0a604.css", "added": "2026-11-24", "expires": "2026-12-20", "source": "rel2-b-hardcoded" },
    { "name": "boot.510d5a90dd.js",   "added": "2026-11-24", "expires": "2026-12-20", "source": "rel2-b-hardcoded" }
  ]
}
```

- 只存 **`assets/` 下的精确文件名**（不含 `assets/` 前缀、不含通配符、不含路径）。
- `expires` **含当日**：`expires >= 今天` → 保活；过了当天 → 自动忽略。
- 初始两行 = REL2-B 手写那两条（`source: rel2-b-hardcoded`，到期日仍为 2026-12-20），即「清单化第一步不改变行为」。
- 工程细节：ASCII、UTF-8 无 BOM、LF（PS 5.1 无 BOM 按 ANSI 读，非 ASCII 会乱码；Python `json.loads` 也不吃 BOM）。

### 2.2 `deploy/collect_legacy_assets.ps1`（新增，唯一写清单的入口）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\collect_legacy_assets.ps1        # 正式收集
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\collect_legacy_assets.ps1 -DryRun  # 只看会加什么
```

- **顺序硬要求：在 `site/build.py` 之前跑**。`site/dist` 只有在 build 覆盖之前才还留着「上一版」的哈希名，这是唯一能取到它们的时刻。脚本头部、输出末行都写了这条，报告 §4 的 runbook 也写死顺序。
- 规则：文件名必须匹配 `^(style|boot)\.[0-9a-f]{10}\.(css|js)$`（稳定名 `style.css` / `boot.js` 自然被跳过）；**写入的永远不可能是通配符**；新条目 `expires = 收集日(北京) + 30 天`；已存在的名字**原样保留**（去重 → 同日重跑不重写文件，`git diff` 干净）；已过期但又被当前 dist 产出的名字 → 重新激活（`source: recollected`，输出 `~` 行）；读清单时发现非法行 → 丢弃并 WARN（会触发重写，坏行不会永久卡住 `sync` 的 exit 2）。
- `-PruneExpired`：额外删掉已过期条目（默认关，保留可审阅历史；`sync` 本来就会忽略它们）。
- 退出码：0 正常（含 `dist/assets` 尚不存在的情形，仅 WARN）、2 清单 JSON 坏（**拒绝覆盖**）/ dist 问题、1 写失败。
- 保留清单里原有的 `generated_at` / `notes` / `name_pattern`：重写只动 `entries` 与 `updated_at`。
- 日期统一按**北京时区**取（发布窗口是北京 00:30–08:30，本机是 UTC-8，否则会差一天）。

### 2.3 `deploy/sync_r2.ps1`（改，+205 / −25 行）

1. 新增 `-ManifestPath`（默认 `data\legacy_assets.json`，仅读）与 `-ShowAssetExcludes`（打印名单 + 精确 exclude 参数后 exit 0，**不碰凭据 / rclone**，给 runbook 和自测用）。
2. 原来写死的 `$LegacyAssetExcludes` 换成 `$AssetExcludes = 合并(硬编码两条, 清单未过期条目)`：
   - **合并顺序**：硬编码 REL2-B 两条 → 清单（同名时清单行覆盖）→ 这就是 2026-12-20 之后「硬编码自然消退、清单接管」的收敛路径；
   - 校验：文件名必须匹配 `^(style|boot)\.[0-9a-f]{10}\.(css|js)$`，`assets/` 前缀 / 非法日期 → 丢弃并 WARN；**含通配符 → `ERROR` + exit 2**（宁可挡住发布，也不让 `--exclude` 变成无界集合）。
3. 名单在**任何上传动作和预算闸门之前**打印（真实发布与 `-DryRun` 都打印）：

```
assets-keep: manifest = ...\data\legacy_assets.json
assets-keep: today (Beijing) = 2026-11-24; entries stay excluded through `expires` (inclusive)
assets-keep:   keep    assets/style.885ce0a604.css   expires 2026-12-20   (rel2-b-hardcoded)
assets-keep:   expired assets/boot.9999expired.js    expired 2026-10-31   (ignored, no --exclude)
assets-keep:   invalid assets/style.cccccccccc.css   (not an exact hashed asset name ...)   (ignored, no --exclude)
assets-keep: 3 exact --exclude(s), 1 expired ignored, 2 invalid ignored, 0 wildcard(s)
```

4. 生成的 exclude 同时喂给 **主 `sync` + `-CheckOnly` 的 check + 发布后的双向 check**（三处同一个 `$AssetExcludes`，不会出现「sync 排除、check 没排除 → 误报 N differences → exit 1」的老坑）。
5. `-DryRun` 行为不变：`--dry-run` 不写任何对象，**不写台账**（`data/r2_put_ledger.jsonl` 只在真实 sync 成功后追加），只是多打印保活名单。
6. 未动：REL3 预算闸门（90 万 / 5 万 / 100 万）、台账格式、`assets/` 的 `Cache-Control` 二次 `copy`、语言根 fallback、`-Transfers` 等。

### 2.4 边界（没碰别人的东西）

- **没改** `site/build.py`、**没改** `data/product/static_pins.json`（frontend 工位在用）、**没写** `site/dist`、**没动** `data/drugs.db`、**没 commit**。
- 唯一「额外」动作：`site/dist/assets` 的**只读列举**（`collect -DryRun` 预演），无写。

## 3. 自验（不发布、不真 sync、不写 dist）

### 3.1 命令

```powershell
# 1) 自测脚本（.tmp\rel6-selftest.ps1，跑完即删；断言 57 项）
powershell -NoProfile -ExecutionPolicy Bypass -File .\.tmp\rel6-selftest.ps1

# 2) 真实 dist 的收集预演（只读 dist，不写清单）
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\collect_legacy_assets.ps1 -DryRun

# 3) 端到端 -DryRun：临时清单 + 假 dist + 临时台账（不发布）
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\sync_r2.ps1 -DryRun `
  -Dist .tmp\rel6-dryrun\dist -ManifestPath .tmp\rel6-dryrun\manifest.json -LedgerPath .tmp\rel6-dryrun\ledger.jsonl
```

### 3.2 断言结果：**63 PASS / 0 FAIL / exit 0**

| 组 | 断言（摘要） | 结果 |
|---|---|---|
| T0 脚本卫生 | 两个 `.ps1` 语法解析 0 error；无 BOM；LF-only；`collect` 纯 ASCII；`sync` 的非 ASCII 行仍只有 HEAD 里那 3 行（两条中文文档路径 + 一条中文注释），**REL6 新增行 0 非 ASCII** | 9 PASS |
| T1 名单解析 | 默认清单 → 2 条精确 exclude；fixture：活跃条目 → `--exclude assets/style.aaaaaaaaaa.css`；**过期条目 `boot.bbbbbbbbbb.js` 不 exclude** 且输出 `expired ... ignored`；`assets/` 前缀名与非法日期名被忽略；计数 `3 exact / 1 expired / 2 invalid / 0 wildcard`；exclude 参数里**无 `*` `?` `[`** | 11 PASS |
| T1b 清单缺失/损坏 | 清单文件不存在 → exit 0 + `manifest not found` WARN，仍出 2 条硬编码 exclude；JSON 坏 → exit 0 + `manifest is not valid JSON` WARN，同样回落 2 条（**降级不阻塞发布**） | 6 PASS |
| T2 通配符硬停 | 清单含 `style.*.css` → `sync_r2.ps1 -ShowAssetExcludes` **exit 2** + `refusing to publish with an unbounded ...` | 3 PASS |
| T3 rclone 行为（本地双目录，零网络） | 用 T1 真实生成的 6 个 exclude 参数跑 `rclone sync`：dst 里 4 个旧哈希资源 → 被排除的 3 个**保住**（含两条硬编码），**未排除的对照文件被删**，新哈希正常上传 | 7 PASS |
| T4 连续两次发版 | 以真实清单为种子 → 收集 dist-A（+2，共 4 条）→ 同 dist 重跑**文件 sha 不变**（幂等）→ 收集 dist-B（哈希全变，+2，共 6 条）：旧两条**仍在**且 `expires` 保持 2026-12-24，新两条已加；全部名字符合精确正则；重写文件 ASCII + LF | 15 PASS |
| T4b 过期 / 修剪 | 2026-10-31 过期条目不 exclude、2026-12-20 条目仍 exclude；`-PruneExpired` 删过期留活跃；`dist` 无 `assets/` 时 WARN 且继续 | 5 PASS |
| T4c 坏行清理 | 清单里手加的 `style.*.css` 被 `collect` 丢弃并 WARN，重写后无通配符，合法行保留 | 4 PASS |
| T5 生产文件未动 | `data/legacy_assets.json`、`data/r2_put_ledger.jsonl` sha 不变；`site/dist/index.html` sha 不变 | 3 PASS |

其中关键的「删除保护」证据（T3）与控制组：

```
dst/assets 同步前: style.aaaaaaaaaa.css  style.885ce0a604.css  boot.510d5a90dd.js  style.zzzzzzzzzz.css
src/assets (下一版): style.cccccccccc.css  style.css
rclone sync src dst --exclude assets/style.aaaaaaaaaa.css --exclude assets/style.885ce0a604.css \
              --exclude assets/boot.510d5a90dd.js      -> exit 0
dst/assets 同步后: style.aaaaaaaaaa.css  style.885ce0a604.css  boot.510d5a90dd.js  style.cccccccccc.css  style.css
                   （对照：未排除的 style.zzzzzzzzzz.css 被删，证明排除是真的在起作用而不是整体没删）
```

### 3.3 真实 `-DryRun` 端到端（临时清单 + 假 dist + 临时台账）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\sync_r2.ps1 -DryRun `
  -Dist .tmp\rel6-dryrun\dist -ManifestPath .tmp\rel6-dryrun\manifest.json -LedgerPath .tmp\rel6-dryrun\ledger.jsonl
```

`-Dist` 是只有 4 个文件的假 dist（`index.html` / `assets/style.css` / `assets/boot.js` / `assets/style.deadbeef01.css`），清单是临时 fixture。共跑 2 次：第 1 次用一条**非法名字**（`boot.9999expired.js`，不是 10 位 hex）验证「无效忽略」，第 2 次改成**合法但已过期**的 `boot.0000aaaa11.js`（2026-10-31 到期）验证「过期忽略」。第 2 次输出（节选）：

```
assets-keep: manifest = ...\.tmp\rel6-dryrun\manifest2.json
assets-keep: today (Beijing) = 2026-11-24; entries stay excluded through `expires` (inclusive)
assets-keep:   keep    assets/style.885ce0a604.css   expires 2026-12-20   (rel2-b-hardcoded)
assets-keep:   keep    assets/boot.510d5a90dd.js   expires 2026-12-20   (rel2-b-hardcoded)
assets-keep:   keep    assets/style.b39711abd5.css   expires 2026-12-24   (collect)
assets-keep:   expired assets/boot.0000aaaa11.js   expired 2026-10-31   (ignored, no --exclude)
assets-keep: 3 exact --exclude(s), 1 expired ignored, 0 invalid ignored, 0 wildcard(s)
budget: month 2026-11 = 0 PUT (0.0% of 1M free, ledger rows 0); ledger=...\.tmp\rel6-dryrun\ledger2.jsonl
sync: ...\.tmp\rel6-dryrun\dist -> r2:drug-brand-crossref (dry-run=True)
plan: Transferred:            4 / 4, 100%
plan: Deleted:           272288 (files), 0 (dirs), 2.601 GiB (freed)
budget: planned=4 + assets/fallback 22 -> projected month total 26 PUT (0.0% of 1M)
dry-run: skipped assets Cache-Control pass (would re-upload 3 files with --ignore-times ...)
OK
```

| 检查点 | 结果 |
|---|---|
| 退出码 | **0**（预算闸门通过） |
| 「本次将保活的资源清单」 | 打印 3 条精确 `--exclude`（2 条硬编码 + 1 条清单活跃项） |
| 「已过期 / 无效忽略」 | 两项都打印：`expired assets/boot.0000aaaa11.js ... (ignored, no --exclude)`（第 2 次）、`invalid boot.9999expired.js ... (ignored, no --exclude)`（第 1 次）；汇总行 `1 expired ignored` / `1 invalid ignored` |
| 计划上传数 | 两次都是 `planned=4`（= 假 dist 的 4 个文件），`projected` 里含固定的 assets/fallback 22；耗时 `1m30.6s`（第 2 次） |
| `Deleted: 272288` | **假 dist 与真实 bucket 的差集**（真实 bucket 27.2 万对象），是 dry-run 的账，`--dry-run` **没有删除任何对象**；用真实 dist 发布时这个数才会回到 0–百级 |
| 台账 | 临时台账 `.tmp\rel6-dryrun\ledger.jsonl` / `ledger2.jsonl` **都不存在**；生产台账 `data/r2_put_ledger.jsonl` sha256 两次前后一致（`AAFA35EC…`），月累计仍 **257,810 PUT**（2026-11 共 5 行：87 + 8,524 + 131,956 + 103,002 + 14,241；曾误写为 249,199 = 后 3 行，2026-11-24 按 Lead 复核修正） |
| 预算口径说明 | 因为 `-LedgerPath` 指到临时台账，日志里的 `month ... = 0 PUT` 是临时台账的口径；真实月份数据要读 `data/r2_put_ledger.jsonl` |

### 3.4 真实 `site/dist` 的收集预演（`-DryRun`，只读）

```
collect: today (Beijing) = 2026-11-24; retention = 30 day(s) -> new entries expire 2026-12-24
collect: existing manifest = 2 entr(ies)
collect: found 2 hashed asset(s): boot.ac6e1a8684.js, style.b39711abd5.css
collect:   + assets/boot.ac6e1a8684.js  expires 2026-12-24
collect:   + assets/style.b39711abd5.css  expires 2026-12-24
collect: added 2, re-activated 0, pruned 0, dropped-invalid 0, already tracked 0
collect: manifest would hold 4 entr(ies) = 4 active (kept alive by sync_r2.ps1) + 0 expired (ignored)
collect: DRY RUN - 2 change(s) not written
```

→ 当前 `site/dist` 是 **v1.2.1 产物**（`boot.ac6e1a8684.js` / `style.b39711abd5.css`）。**v1.2.2 发布时在 build 之前真正跑一次 `collect`，这 2 条就会进清单**（`expires 2026-12-24`），sync 的 exclude 从 2 条变 4 条——正好补上 REL6 之前的漏点（v1.2.1 的哈希名是 v1.2.2 的 `rclone sync` 会删掉的那一批）。

## 4. 对 v1.2.2 发布的影响（runbook）

顺序变成 **collect → build → sync**（原来只有 build → sync）：

```powershell
# ① 收集上一版（v1.2.1）dist 里的哈希名 —— 必须在 build 之前！
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\collect_legacy_assets.ps1
# ② 生产构建
& $py site/build.py                                  # 等 == done ==
# ③ 发布预演（预期 planned <= 1,000；打印 4 条保活）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -DryRun
# ④ 真实发布 + 台账 + verify/tag（Lead 批准后）
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1
& $py deploy/verify_live.py --base https://drugcrossref.com --expect-version v1.2.2
```

- **PUT 预算**：exclude 只影响「远端对象是否被删」，不增加上传；`assets/` 的 `Cache-Control` 二次 `copy` 仍约 17 PUT，主 sync 仍只传变化文件。**REL6 本身 0 额外 PUT**（清单是本地文件）。
- **exclude 会随版本增长但有限**：每版 +0–2 条（CSS 文本常不变 → style 哈希可跨多版复用，v1.0.0→v1.0.1 就是这样；boot 常随构建版本变）× 30 天窗口 → 稳态 ~4–10 条，bucket 只多几个 30–110 KB 的历史资源，远低于体积口径。
- **到期清理**：2026-12-20 之后 REL2-B 两条硬编码与清单里同名条目一起失效（`expires` 同为 2026-12-20）→ 下一次 sync 就会把远端这两个对象删掉；**按 AGENTS.md §6「到期后人拍板」**，本报告不做自动删除，届时 Lead 决定是否在清单里提前 `-PruneExpired` 或直接放任删除。
- 发布报告中需写：本次 exclude 名单（4 条）、`planned`、台账新增行、「本次 PUT / 当月累计 / 占免费额度 %」。

## 5. 已知缺口 / 后续候选（不在本任务内）

1. **顺序靠纪律，不靠机器**：`collect` 必须在 `build` 之前，脚本只能靠文档 + 输出末行提醒；若人手快先 build 了，上一版哈希名已从磁盘消失（无法自动补救，只能从 R2 现有对象反推或放弃）。候选改进：发布脚本里串成一条（`collect → build` 同一次调用）、或在 `build.py` 里加「构建前写入上一版资产清单」的钩子——两者都要动别人的写作用域，本任务不越界。
2. **历史已丢的两个 boot 哈希**（`boot.882e52f15e.js`、`boot.c161b56276.js`）远端已 404，本任务**不追补**（要重传得本地有对应文件；价值仅覆盖已过期缓存窗口）。
3. **清单损坏时的策略**：`sync_r2.ps1` 对 JSON 坏 / 缺文件只 WARN（降级为只剩硬编码两条、发布继续）；对**通配符**才硬停。这是有意的取舍（保护降级 ≠ 发布失败），但意味着「清单文件丢失」不会被发布挡住——靠 `git` 跟踪 + 本报告记录兜底。
4. 本任务**没跑** `deploy/ci_checks.py`：改动只涉及发布脚本壳（不产站点、不动数据），且当前工作区有 frontend 正在改的 `site/build.py` / `static_pins.json` 与旧 `site/dist`，此时跑 CI 的站点产物检查会混入别人的进行中状态。CI 与全部发布门禁留到 v1.2.2 发布派单时按 AGENTS.md §6 跑。

## 6. 复现与证据文件

| 文件 | 说明 |
|---|---|
| `deploy/sync_r2.ps1` | 改（+205 / −25）：`-ManifestPath`、`-ShowAssetExcludes`、清单合并 / 校验 / 打印，exclude 三处统一 |
| `deploy/collect_legacy_assets.ps1` | 新增（收集入口，唯一写清单者） |
| `data/legacy_assets.json` | 新增（名单真相源，初始 2 条 = REL2-B 手写对） |
| 本报告 | 自验数字、runbook、缺口 |
| `.tmp\rel6-selftest.ps1`、`.tmp\rel6-selftest.log`、`.tmp\rel6-dryrun\`（含 `dryrun.log` / `dryrun2.log`） | 自测脚本与其输出、2 次 `-DryRun` 日志；**跑完已清理**（磁盘紧张；内容见 §3.2–§3.3 摘录） |

提交注意（给 Lead）：

- 新增两个文件目前**未跟踪**：`data/legacy_assets.json`、`deploy/collect_legacy_assets.ps1`；改动的 `deploy/sync_r2.ps1` 已在工作树。
- 工作树里 `site/build.py`（frontend 在改）与 `data/product/static_pins.json` 的改动**与本任务无关**，不要算进本次提交。
- **v1.2.2 发布时**：build 前跑 `collect` 会让 `data/legacy_assets.json` 多 2 行（v1.2.1 的哈希名），这两行要和 `CHANGELOG` 一起提交。

复核命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -ShowAssetExcludes
& $py -c "import json;d=json.load(open('data/legacy_assets.json',encoding='utf-8'));print(d['schema'],len(d['entries']),[e['name'] for e in d['entries']])"
& .\tools\git\cmd\git.exe status --short -- deploy data
```
