# T18 dist 差分脚本 + T19 lang-root 键评估（release 工位）

> 工位：release ／ 任务板 `task-6` ／ 源码 HEAD **`9a031d3f864`**（+ Lead 收尾提交 `ddcd25c9171`）／ 本段**未 commit**。
> 约束：**未真实 sync、未 build 生产 dist、未改 `site/build.py` / `data/drugs.db`**；所有远端动作都是**只读**（`-DryRun` / `-CheckOnly` / `rclone check` / `HEAD`）。
> 本报告含 **T17 误报澄清**（§5）：`db/nightly_metrics.py` 早已适配 sitemap 索引，不是缺口。

## 结论（先行）

| 项 | 结果 |
|---|---|
| **T18** `deploy/dist_diff.py` | ✅ 新建；四类（added / removed / changed(size) / **changed(content-only)**）+ UTF-8 无 BOM + SHA-256 + §6 三条判定提示 + `--json` |
| T18 合成样本验收 | ✅ added 2 / removed 2 / changed(size) 2 / **content-only 3** = 9（与预期逐项相符，含中文名 + 同长度替换） |
| T18 真实 dist 自检 | ✅ `--before site/dist --after site/dist` → **四类全 0**（362,112 vs 362,112，254.7 s，jobs 16） |
| T18 复现 v1.2.5 盲区 | ✅ 用 v1.2.5 的两份旧「路径+大小」清单跑：`changed(content-only) = 0` + WARN，而 `-DryRun` 哈希口径显示 **77 个同长度内容替换**（口径更正见 §1.4） |
| **T19** lang-root 5 键 | ✅ **已改（零写入证据齐全）**：`-DryRun` 的 `Deleted: 5 (files), 1.072 MiB` → **被删 0**；`-CheckOnly` 仍 `0 differences / 362,111 matching` |
| T19 效果 | 每版远端 Class A 操作 **27 → 17**（−5 DELETE −5 PUT；只省 2 类小操作，不省 assets 的 17） |
| 新增开关 | `fix_fr_root.py --check-remote`（只读 HEAD，报告「已一致→跳过」）＋ 默认「远端一致就跳过写」＋ `--force` |
| 未做 | 未 commit、未真实发布；`$BudgetExtra` 仍留 22（刻意保守上界） |

---

## 1. T18：`deploy/dist_diff.py`

### 1.1 为什么需要它

v1.2.5 发布时 A/B 只按「路径 + 大小」差分，**同长度内容替换**看不见：`v1.2.4 → v1.2.5`、`2026-11-25 → 2026-11-26`、
hashed 资源名都是等长替换，清单差分记 0 变化，只能靠 `sync_r2.ps1 -DryRun`（rclone `--checksum`，内容哈希）交叉核平。
本脚本把这套核对固化成工具：清单带 **SHA-256**，四类分开数，`changed(content-only)` 就是那条盲区的直接证据。

### 1.2 设计

| 项 | 实现 |
|---|---|
| 输入 | 两份**清单**（`相对路径<TAB>字节数[<TAB>sha256]`，UTF-8 无 BOM）或**两棵目录**（就地算哈希，不落中间文件） |
| 四类 | `added` / `removed` / `changed(size)` / `changed(content-only)`（两版都有、大小相同但哈希不同） |
| 编码（T16） | 读写都 `utf-8` 无 BOM、`\n` 换行；**自检并打印两侧非 ASCII 路径行数**；读时若带 BOM 会 WARN |
| 兼容 | 2 列旧清单（只有路径+大小）能读，但会明确 WARN「`changed(content-only)` 不可见」，**不静默** |
| 三条判定 | ① added 是否全在 `product/`（+ `assets/` / `sitemap-<n>.xml`）② **页面** removed 是否为 0（`assets/` 之外）③ 长尾六类变化是否只由产品链接引起 |
| ③ 精验 | 两边都是目录时自动做：把 `product/<pid>.html` 与 `product.html?pid=<pid>` **都归一成 `href="P:<pid>"`** 后逐字比较，输出 `links-only` / `non-link` 计数与样例 |
| 输出 | 文本（计数 + 每类前 N 条样例 + 判定提示）/ `--json [路径\|-]`（机器可读） |
| 退出码 | 0 分析完成；1 用了 `--expect-identical` 且有差异；2 参数/输入错误 |
| 只读 | 不写 dist、不碰 R2、不碰库；只有显式 `--write-manifest` 才写文件 |

### 1.3 用法

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 目录 → 带哈希清单（可归档、可离线比较）
& $py deploy/dist_diff.py --write-manifest .tmp/t18/a.tsv --root .tmp/t18/a
# 两份清单比较
& $py deploy/dist_diff.py --before .tmp/t18/a.tsv --after .tmp/t18/b.tsv
# 直接比两棵目录（顺带做 ③ 逐字节核实）
& $py deploy/dist_diff.py --before .tmp/t18/a --after .tmp/t18/b --samples 3
# 发布自检：同目录 vs 同目录必须 0 差异
& $py deploy/dist_diff.py --before site/dist --after site/dist --jobs 16 --expect-identical
# JSON（给报告/CI 消费）
& $py deploy/dist_diff.py --before A --after B --json .tmp/diff.json
```

### 1.4 验收 1：合成样本（`.tmp/t18/`，含中文名 + 同长度替换 + 增删）

样本树：`a`（旧，8 文件）/ `b`（新，8 文件）；另造 `c1/c2` 一对「只改链接形态」的正例。构造脚本 `.tmp/t18_build_samples.py`。

| 预期 | 实测 |
|---|---|
| added 2（`product/NEW-1.html`、`assets/boot.34f2134837.js`） | **2** ✓ |
| removed 2（`name/被删页面.html`、`assets/boot.971f514202.js`） | **2** ✓ |
| changed(size) 2（`drug/keep.html`、`name/linkcase.html`） | **2** ✓ |
| changed(content-only) 3（`index.html`、`whats-new.html`、`name/中文页面-泰诺.html` —— 版本号/日期/`诺→諾` 同长度替换） | **3** ✓ |
| 中文路径无乱码 | 非 ASCII 路径 `a=2 / b=1`，样例打全为 `name/中文页面-泰诺.html`、`name/被删页面.html` ✓ |

```
$ & $py deploy/dist_diff.py --before .tmp/t18/a --after .tmp/t18/b --samples 3
before: .tmp\t18\a  files=8  编码=utf-8（无 BOM）  非 ASCII 路径=2
after : .tmp\t18\b  files=8  编码=utf-8（无 BOM）  非 ASCII 路径=1
四类（algo=sha256）：
  added                          2  {'assets': 1, 'product': 1}
  removed                        2  {'assets': 1, 'name': 1}
  changed(size)                  2  {'drug': 1, 'name': 1}
  changed(content-only)          3  {'(root)': 2, 'name': 1}
  changed(content-only) 样例：
    index.html  [41B -> 41B]
    name/中文页面-泰诺.html  [27B -> 27B]
    whats-new.html  [25B -> 25B]
三条判定：
  ① added 是否全在 product//assets//sitemap-N.xml: 成立  {"violations": 0, "by_dir": {"assets": 1, "product": 1}}
  ② 页面 removed（assets/ 之外）是否为 0: 需人工看  {"count": 1, "samples": ["name/被删页面.html"],
                                                      "assets_removed": ["assets/boot.971f514202.js"]}
  ③ 长尾页变化是否只由新增静态页链接引起: 需人工看  {"longtail_changed": 3, "checked": 3, "links_only": 1, "non_link": 2,
                                                      "non_link_samples": ["drug/keep.html", "name/中文页面-泰诺.html"]}
合计差异 9 文件（added 2 / removed 2 / changed(size) 2 / changed(content-only) 3）
```

② 和 ③ 在这里**故意判「需人工看」**（样本里确实删了一个页面、且 `drug/keep.html` 是正文变化）：判定器不是只会点头。
正例 `c1/c2`（同一页只把 `product.html?pid=JP-9` 换成 `product/JP-9.html`）：

```
  changed(size) 1（drug/only-link.html，90B -> 86B）
  ③ …: 成立  {"longtail_changed": 1, "checked": 1, "links_only": 1, "non_link": 0}
```

### 1.5 验收 2：真实 dist「同目录 vs 同目录」= 0 差异

```
$ & $py deploy/dist_diff.py --before site\dist --after site\dist --jobs 16 --expect-identical
before: site\dist  files=362,112  编码=utf-8（无 BOM）  非 ASCII 路径=77,942
after : site\dist  files=362,112  编码=utf-8（无 BOM）  非 ASCII 路径=77,942
  added 0 / removed 0 / changed(size) 0 / changed(content-only) 0
合计差异 0 文件            exit=0（254.7 s，jobs=16，两遍全量 SHA-256：3.28 GiB × 2）
```

### 1.6 验收 3：复现 v1.2.5 的 size 盲区（这就是「证据」）

拿 v1.2.5 发布时抓的两份**旧两列清单**（`.tmp/v125-dist-before.txt` 332,112 行 / `.tmp/v125-dist-after.txt` 362,112 行）跑：

```
四类（algo=sha256）：
  added                     30,001  {'product': 30000, 'assets': 1}
  removed                        1  {'assets': 1}
  changed(size)             47,135  {'product': 38296, 'name': 6683, 'drug': 2144, '(root)': 4, 8 语种根各 1}
  changed(content-only)          0        ← 旧口径的盲区：这里只能是 0
WARN: 至少一份清单没有哈希（旧 2 列清单）→ changed(content-only) 不可见，请用 --write-manifest 或直接给目录重算
合计差异 77,137 文件
```

**口径更正（重要）**：v1.2.5 发布报告里写「**78** 个文件内容变但大小不变」，那是把 removed 的 1 个也减掉了。
按 rclone 的传输口径重算：

```
同长度内容替换 = -DryRun planned 77,213 − added 30,001 − changed(size) 47,135 = 77
```

所以正确数字是 **77**（`Deleted` 的那 1 个不占 PUT）。四类计数本身没错、判定也没错，只是这一个数字的减法写错了一格；
tag `v1.2.5`、Release 正文、CHANGELOG 都**不含**这个数字，无需改公开口径。

### 1.7 其它已验项

- `--write-manifest`：`.tmp/t18/a.tsv` 8 行 / 701 B / `encoding=utf-8-algo=sha256 bom=False` / `non-ascii-rows=2`；三列格式（`路径<TAB>大小<TAB>sha256`）。
- 清单 vs 清单比较：四类计数与目录 vs 目录完全一致（9 / 2 / 2 / 2 / 3）。
- `--json`：`{"counts": {"added": 2, "removed": 2, "changed(size)": 2, "changed(content-only)": 3}, "total_differences": 9}`，`criteria` 三条齐全，UTF-8 无 BOM 写文件。
- 三条判定的「长尾只减不增」：`longtail_removed` 单独计数（应为 0），v1.2.5 的真实清单口径为 **0**。

### 1.8 已知限制（写下来，别踩）

1. **两份清单都没哈希时**，`changed(content-only)` 必然 0 —— 脚本会 WARN，但**必须**再拿 `-DryRun` planned 交叉核；单看清单不算验完。
2. ③ 的逐字节核实需要两边都有**目录**；只给清单时只能给计数 + 提示（`--check-links` 也需目录）。
3. ③ 默认最多核实 200 页（`--check-links-max`），大版本建议调到 2,000 或按目录名分层抽样。
4. 只做「§6 内容扩容例外」的**提示**，不替人/Lead 做放行决定。

---

## 2. T19：lang-root 5 个兜底键（`fr/ ko/ ja/ cs/ lv/`）

### 2.1 先查清事实

| 问题 | 结论（证据） |
|---|---|
| 谁生成 | `deploy/fix_fr_root.py`（S3 SigV4 直接 PUT），由 `deploy/sync_r2.ps1` 在**主 sync 之后**调用（`--dist … --langs fr,ko,ja,cs,lv`） |
| 为什么不在 dist | 键是 `<lang>/`（**结尾带斜杠**）：Windows 上无法存在名为 `fr/` 的文件；R2 自定义域又没有「目录索引」解析，`/fr/` 只能靠这个名字的对象响应。`rclone copyto` 也拒绝（把尾斜杠当目录） |
| R2 上是什么 | **真实对象键**，不是 0 字节、不是软链：`fr/` 216,016 B / `ko/` 225,230 / `ja/` 229,082 / `cs/` 226,717 / `lv/` 226,725（= 各语 `index.html` 的拷贝，`content-type: text/html; charset=utf-8`）。rclone 把它们当**名为 `fr/` 的文件**（`Skipped delete … (size 210.953Ki)`），`lsjson --max-depth 1` 则显示为 `IsDir=true, Size=0` 的目录项 —— 两种视图并存，正是「删了又补」的根源 |
| `verify_live` 的断言 | `LANG_ROOTS` 共 **9** 条：`/` `/es/` `/zh/` `/zh-hant/` `/fr/` `/ko/` `/ja/` `/cs/` `/lv/`；每条要求 **HTTP 200 且 body > 500 字节**（`lang-root-<label>`），另有首页 hreflang 目标可达校验。所以 5 个兜底键**不能直接删**，除非有 Transform Rule 顶上 |
| 现状成本 | 每版 `Deleted: 5 (files), 1.072 MiB` + 兜底 5 PUT（合计 10 次 Class A 操作），净效果 0 |

### 2.2 方案与实测风险

| # | 方案 | 实测/风险 | 结论 |
|---|---|---|---|
| 1 | `--exclude "/fr/"`（目录式精确路径） | **删是没了，但把整个语言目录也剪掉了**：`Checks: 362,116 → 362,076`（−40 = 5 语 × 8 个根文件）→ 以后 `fr/*.html` 改了也不会传，而且是**静默**的 | ❌ 否决 |
| 2 | `--exclude "{{^fr/$}}"`（rclone **regexp** 过滤器，literal 双花括号） | 只匹配 filter 路径恰好是 `fr/` 的这一个对象。实测（PS 5.1、5 条规则、不带 assets 排除）：`Deleted: 6 (files)`（只剩 6 个远端旧 hashed 资源）/ `Checks` 362,118 = 362,112 + 6 → **5 个键不再被删** | ✅ 采用 |
| 3 | `fix_fr_root.py` 改成「远端已一致就跳过」 | 只在键**活着**时才有意义（方案 2 之后成立）。用只读 HEAD 比对 `ETag(md5)` + `Content-Length`，任何不确定（HEAD 失败、无 ETag、multipart）都**回落到照写** | ✅ 采用 |
| 4 | 根治：给 5 种语言加 **Cloudflare Transform Rule**（`/fr/` → `fr/index.html`），然后删掉兜底与 5 条 exclude | 0 DELETE / 0 PUT，且不再依赖 synthetic 键；需要 infra 权限（属人的动作），钱 0 | 📌 推荐路线，本段不做 |

补充实测（说明为什么必须写 literal 双花括号）：单花括号 `{^fr/$}` 完全无效（`Deleted: 11` = 5 键 + 6 资源）；
而 PowerShell 的 `-f` 运算符会把 `{{` 反转义成 `{`，所以脚本里**必须用拼接** `'{{^' + $lang + '/$}}'` 而不是 `'{{^{0}/$}}' -f $lang`。

### 2.3 已实现（两个文件）

1. `deploy/sync_r2.ps1`
   - 新增 `$LangRootExcludes`（由既有的 `$FallbackLangs` 生成，5 条 literal 正则），**同时**加进三处：
     主 `rclone sync`、`-CheckOnly` 的 check、**发布后 sizes 校验的 check**（两向 check 会把保活键当 5 处差异 → 不加以会**让发布失败**，见 §2.4 证明 D）。
   - 启动时打印一行 `lang-root-keep: 5 exact --exclude(s): fr/ ko/ ja/ cs/ lv/ (trailing-slash object keys, not in site/dist)`。
   - `$BudgetExtra` **保持 22**（17 assets + 最多 5 兜底），是刻意保守的上界：投影只会高估不会低估。
2. `deploy/fix_fr_root.py`
   - 新增 `--check-remote`（配 `--dry-run` 用，只做 HEAD，零写入）与 `--force`；
   - 默认行为改为：先 HEAD，`ETag(md5)` 与长度都一致 → 打印「已一致 → 跳过」不发 PUT；否则照写（失败仍只警告、退出码语义不变）。
   - docstring 更新为 T19 后的口径 + 根治方向。

### 2.4 零写入证据（4 条，全部无写）

**A. 只读 HEAD：下次发布 0 写**

```
$ & $py deploy/fix_fr_root.py --dist site/dist --dry-run --check-remote
[dry-run] 已一致 → 跳过: fr/（216,016 B, ETag=md5 相同）
[dry-run] 已一致 → 跳过: ko/（225,230 B, ETag=md5 相同）
[dry-run] 已一致 → 跳过: ja/（229,082 B, ETag=md5 相同）
[dry-run] 已一致 → 跳过: cs/（226,717 B, ETag=md5 相同）
[dry-run] 已一致 → 跳过: lv/（226,725 B, ETag=md5 相同）
[dry-run] 汇总：5 个语言根 → 跳过 5，需要写 0                     # exit 0
```

**B. `-CheckOnly`（只读 one-way 检查）**

```
lang-root-keep: 5 exact --exclude(s): fr/ ko/ ja/ cs/ lv/ (trailing-slash object keys, not in site/dist)
check: D:\…\site\dist -> r2:drug-brand-crossref (size-only, one-way)
NOTICE: S3 bucket drug-brand-crossref: 0 differences found / 362,111 matching files
check: OK (size-only, one-way)                                   # exit 0
```

**C. `-DryRun`（零写入）：`Deleted` 从 5 → 0**

| | 改前基线 | 改后 |
|---|---|---|
| `plan: Deleted:` | `Deleted: 5 (files), 0 (dirs), 1.072 MiB (freed)` | **没有该行**（0 删除） |
| `plan: Transferred:` | 0 B / 0 B | 0 B / 0 B（一致） |
| `budget:` | planned=0 + 22 → 486,413 PUT（48.6%） | 完全相同 |
| 退出码 | 0 | 0 |

**D. 发布后 sizes 校验的 check 必须同步加排除（否则下一版会失败）**

```
[assets-only   ] rclone check … --size-only （两向）   exit=1  5 differences found / 362,111 matching
                 ERROR: cs/ | ja/ | fr/ | lv/ | ko/  file not in Local file system at …\site\dist
[assets+langroot] rclone check … --size-only （两向）   exit=0  0 differences found / 362,111 matching
```

即：键保活后，脚本里那个两向 `rclone check` 若不加这 5 条排除，会稳定报 5 处差异 → 发布在 sizes 校验处 **exit 1**。
所以「sync 排除 + 两个 check 排除」是一组改动，缺一不可。

### 2.5 效果与剩余风险

- 每版 Class A 操作：**27 → 17**（−5 DELETE −5 PUT；assets 的 17 PUT 不变）。
- 剩余风险 1：真正确认要等**下一次真实发布**（本段按要求只做零写入验证）。失败方向是「安全的」——多删了只是回到今天的成本，
  漏传会在两向 check 处 **exit 1** 明确失败，不会静默。
- 剩余风险 2：`{{^fr/$}}` 依赖 rclone 的 regexp 过滤器语义（v1.76.0 实测有效）。升级 rclone 后建议先跑一次 `-DryRun` 确认 `Deleted` 仍为 0。
- 建议：下个版本顺手做方案 4（Transform Rule），把兜底与 5 条 exclude 一起删掉，这才是 0 成本的终结。

### 2.6 顺带踩到的坑（写给后来人）

第一次改动我在这份 `.ps1` 里写了中文 `Write-Host`，结果：**`powershell`（5.1）按系统 ANSI 读无 BOM 的 .ps1**，
UTF-8 字节被当 GBK 解码后凑出多余引号 → 解析直接失败（`表达式或语句中包含意外的标记`）。
现在脚本里**新增内容一律 ASCII**（与文件既有风格一致）；文件里原有的 3 行非 ASCII（L192/484/494，中文文件名）**未动**。

---

## 3. 其它

- `deploy/ci_checks.py --fast`：**PASS 8 / FAIL 0 / SKIP 5**（51.2 s）；`dist-integrity` = 362,112 文件 / 0 字节 0 / sitemap 230,435（5 分片）。
- 本次改动清单（**未 commit**，等 Lead 决定）：
  - 新增 `deploy/dist_diff.py`
  - 改 `deploy/sync_r2.ps1`（`$LangRootExcludes` + 三处引用 + 注释/预算说明）
  - 改 `deploy/fix_fr_root.py`（HEAD 比对跳过 + `--check-remote` / `--force` + docstring）
  - 新增本报告；`.tmp/t18`、`.tmp/t19` 为样本与日志（gitignored）
- 未改：`site/build.py`、`data/drugs.db`、`site/dist`（未重建、未动）、CHANGELOG、`data/legacy_assets.json`。

## 4. 下次发版建议（一句话）

发布前多跑一条 `& $py deploy/dist_diff.py --before <上版目录或清单> --after site/dist --json .tmp/ab.json`，
用 `changed(content-only)` 直接看同长度替换，再把 `total_differences` 与 `-DryRun planned` 对一遍 —— 两者应当只剩 `removed` 的差额。

## 5. T17 误报澄清（一行）

**T17 是误报，不是缺口**：`db/nightly_metrics.py` L221–236 早在 **v1.2.3（commit `ec9e3981993`）** 就适配了 sitemap 索引
（`<sitemapindex` → 逐分片 `<url>` 求和，旧单文件兼容）；Lead 实跑 `pages.sitemap_urls = 230435`、**无**「sitemap URL 数下降」告警。
本报告先前版本（及 v1.2.5 发布报告 §8-3）把它写成待修项，属**第三次依据旧报告/旧代码未复核**导致的误报；以本节为准，后续报告不再把 T17 当缺口。
