# V101-A 结果页首屏条目收口（390 → 6.5 / 768 → 11.5）

- 任务：`task-6`（V101-A）· 工位 `frontend` · 目标版本 **v1.0.1**
- 改动文件：**只有 `site/build.py`**（+10 / −4 行，结果表 CSS）
- 未 commit、未写 `site/dist`、未发布、未碰 `deploy/` / 数据 / 九语键

## 0. 结论（先看这一段）

| 指标 | 改前 | 改后 | 目标 |
|---|---:|---:|---|
| 结果页 390×844 首屏条目 | **5.0** | **6.5** | ≥6.0 ✅ |
| 结果页 768×1024 首屏条目 | **10.5** | **11.5** | ≥11.0 ✅ |
| 结果页 1440×900 首屏条目 | **9.5** | **10.0** | 不回退 ✅（还 +0.5） |
| 结果页 2560×1440 首屏条目 | 20.0 | 20.0 | 不回退 ✅（RES_LIMIT=20 上限） |
| 结果页 AFCR / chrome / 悬浮 / 字号 / 溢出 | 0.87–0.98 / 0.06–0.19 / 0.000–0.068 / 16·13 / 否 | **完全同改前** | 不退化 ✅ |
| 首页 4 视口全指标 | — | **完全同改前** | 不退化 ✅ |
| A/A′ 确定性 | — | **0 差异**（157,122 文件 / 1,538,347,602 B） | 0 ✅ |
| A/B 版本 +1 | — | **78 文件**（≤500）；长尾六类 **0 差异** | ✅ |
| `i18n_check` / `ci_checks --fast` | — | **FAIL 0 / FAIL 0**（PASS 8 / SKIP 5） | ✅ |
| `first_screen_check --baseline`（改前） | — | **baseline 退化 0 项**（24 次扫描） | ✅ |

**一句话**：只把结果卡里「市场」和「操作」并到同一行、桌面行 padding 6→5px——每行信息一条没删，390 首屏多 1.5 条、768 多 1 条、1440 多 0.5 条，其余 7 指标与首页逐项不变。

## 1. 改了什么（`site/build.py`，结果表 CSS 4 处）

1. **桌面/平板行高**：`table.res.rows td{padding-top:6px;padding-bottom:6px}` → `5px`，行高 **40 → 38px**（768/1440，字号不动）。
2. **手机结果卡换行位**：
   - `.c-market`（市场）由「占满一整行」→ `grid-column:1 / 8`；
   - `.c-det`（操作）由「占满一整行」→ `grid-column:8 / 13`、右对齐；
   - 行 `margin 3px → 2px`、`padding 1px → 0`。
   - 卡片高度 **84 → 62px**（390 实测），仍保留 4 个语义块：药名 / 成分｜规格 / 市场｜操作。
3. **移动端操作列允许换行**：在 8759 行 `nowrap` 规则之后补 `@media (max-width:767px){…td.c-det{white-space:normal;text-align:right}}`——en/es 等长操作文案在有需要时只在操作列内换行，不会压到市场文字。
4. 以上均为 CSS；**结果行模板（`flatRowHTML`）与九语文案零改动**，数据零改动。

信息完整性：每行仍读得到 ① 当地商品名（含同名不同药 / 复方 / 仅出口 / 释放机制等关系徽标）② 活性成分 ③ 剂型+规格（无规格走既有「规格未确认」文案）④ 市场 ⑤ 操作（「不确定，查看差异」/「查看登记」）。只换行位，不删信息。

## 2. 命令（全部显式 `SITE_OUT`，只写 `.tmp/`）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 0) 改前 / 改后 构建
$env:SITE_OUT='.tmp\v101-before';  & $py site/build.py *> .tmp\v101-before-build.log;  Remove-Item Env:SITE_OUT
& $py .tmp\v101_patch.py && $py -m py_compile site/build.py
$env:SITE_OUT='.tmp\v101-after';   & $py site/build.py *> .tmp\v101-after-build.log;   Remove-Item Env:SITE_OUT
$env:SITE_OUT='.tmp\v101-after2';  & $py site/build.py *> .tmp\v101-after2-build.log;  Remove-Item Env:SITE_OUT

# 1) 首屏守卫：改前 / 改后（各 24 次扫描 = 6 页型 × 4 视口）
& $py deploy/first_screen_check.py --dist .tmp\v101-before --json .tmp\v101-before-fs.json --shots .tmp\v101-before-shots
& $py deploy/first_screen_check.py --dist .tmp\v101-after  --json .tmp\v101-after-fs.json  --shots .tmp\v101-after-shots
& $py deploy/first_screen_check.py --dist .tmp\v101-after --baseline .tmp\v101-before-fs.json --json .tmp\v101-after-vs-before.json

# 2) A/A′ 与 A/B（B = CHANGELOG 临时 v1.0.1 · 2026-11-22，try/finally 恢复）
& $py deploy/check_build_determinism.py .tmp\v101-after .tmp\v101-after2 --json .tmp\v101-aa.json
& $py deploy/check_build_determinism.py .tmp\v101-after .tmp\v101-b      --json .tmp\v101-ab.json

# 3) 门禁
$env:PYTHONIOENCODING='utf-8'
& $py deploy/i18n_check.py --json .tmp\v101-i18n.json
& $py deploy/ci_checks.py --fast --dist .tmp\v101-after
& $py .tmp\rel2a_probe.py .tmp\v101-after --scan      # 长尾页无 hashed 资源名 / 无版本号
```

三个构建均到 `== done ==`；`build version: 4084371471`（build.py 改了，相对 v1.0.0 的 `3933853198` 是预期变化）。

## 3. 首屏守卫：改前 / 改后（`first_screen_check`）

### 3.1 结果页（`index.html?q=tylenol&lang=zh`）

| 视口 | items | AFCR | chrome | 悬浮 | 正文/辅助/最小 | 横向溢出 |
|---|---|---|---|---|---|---|
| 390×844 | **5.0 → 6.5** | 0.87 → 0.87 | 0.19 → 0.19 | 0.068 → 0.068 | 16/13/13 → 同 | 否 → 否 |
| 768×1024 | **10.5 → 11.5** | 0.98 → 0.98 | 0.13 → 0.13 | 0.000 → 0.000 | 16/13/13 → 同 | 否 → 否 |
| 1440×900 | **9.5 → 10.0** | 0.97 → 0.97 | 0.09 → 0.09 | 0.000 → 0.000 | 16/13/13 → 同 | 否 → 否 |
| 2560×1440 | 20.0 → 20.0 | 0.98 → 0.98 | 0.06 → 0.06 | 0.000 → 0.000 | 16/13/13 → 同 | 否 → 否 |

### 3.2 首页（不回归对照）

| 视口 | items | AFCR | chrome |
|---|---|---|---|
| 390×844 | 0.0 → 0.0 | 0.93 → 0.93 | 0.14 → 0.14 |
| 768×1024 | 9.0 → 9.0 | 1.01 → 1.01 | 0.11 → 0.11 |
| 1440×900 | 9.0 → 9.0 | 1.00 → 1.00 | 0.07 → 0.07 |
| 2560×1440 | 12.0 → 12.0 | 0.96 → 0.96 | 0.13 → 0.13 |

`first_screen_check --baseline .tmp/v101-before-fs.json`：**baseline 退化 0 项**，不稳定 0 组、疑似 0 组；24 次扫描 2 项未达与改前完全相同（`drug` 1440 items 4.5、`coverage` 390 items 3.5，均为既有已知偏差，不在本任务范围）。

### 3.3 几何证据（真实 Chrome 量取，`.tmp/v101_geom.py`）

| 视口 | 结果行高 | `#reswrap` 顶 | 首屏窗口 | 条目计算 |
|---|---:|---:|---|---|
| 390×844 | **84 → 62px** | 402 → 402 | 844（tabbar 顶 788） | 6 行全见（第 6 行 728–790）+ 第 7 行 51/62 → **6.5** |
| 768×1024 | **40 → 38px** | 541 → 541 | 1024 | 11 行全见（第 11 行 971–1009）+ 第 12 行 15/38 → **11.5** |
| 1440×900 | **40 → 38px** | 472 → 472 | 900 | 第 10 行 865–903 可见 35/38 = 0.92 → **10.0** |

> 非探针语言备注（真实几何量取）：en/es 的 h1 在 390 下占 2 行（53px，既有），操作文案「Not sure, see differences」在操作列内换行 → 行高 71px（zh 62px），首屏条目 **4.5 → 5.0**（仍为净改善）。若后续要让 en/es 也到 6.0，可把操作列再放宽（如 6/13 列）；本次未做，避免改窄 zh 的市场列、也不动桌面档。

## 4. A/A′ 确定性

```
A = .tmp\v101-after   files 157,122  bytes 1,538,347,602
B = .tmp\v101-after2  files 157,122  bytes 1,538,347,602
只在 A: 0   只在 B: 0   共有: 157,122   内容不同: 0
== 一致：两次构建逐字节相同 ==
```

## 5. A/B 版本差分（v1.0.0 → 临时 v1.0.1 · 2026-11-22）

- 总差异 **78 文件**（门槛 ≤500）；`only_a=0 / only_b=0`。
- `name 109,575 / drug 13,434 / combo 17,424 / maker 15,213 / atc 1,154 / cat 16` —— **全部 0 差异**。
- 差异族：8 个语言副本 ×7=56、顶层 html 8、`assets/i18n*.js` 10、清单 4（`datapackage.json` / `dataset.jsonld` / `checksums.txt` / `sitemap.xml`）——与 REL2-A 的 78 文件结构一致，说明本次 CSS 改动没有把任何长尾页拖进版本差异。
- `CHANGELOG.md` / `data/release_notes_i18n.json` 临时改动已按字节恢复：两文件 sha256 与 `git diff` 长度改前=改后（`7E5AB403…` / `EC0FA41A…`；`0 / 0`）。

## 6. 门禁与资源

| 项 | 结果 |
|---|---|
| `i18n_check.py` | `ok=True`、**fail=0**、warn=25（既有 hardcoded 文案） |
| `ci_checks.py --fast --dist .tmp/v101-after` | **FAIL 0**（PASS 8 / SKIP 5 / 25.5s）；`dist-integrity` 157,122 文件 / 0 字节 0 / sitemap 78,224 |
| 长尾页全量扫描 | name/drug/combo/maker/atc/cat 共 147,263 页：`style.css`+`boot.js` 覆盖 100%，**hashed 资源名 0、版本号 0** |
| 资源名 | CSS `style.885ce0a604.css` → **`style.9d53b4dc0d.css`**（107,887 → 108,337 B）；boot `882e52f15e` → `c161b56276`；稳定副本 `assets/style.css` / `assets/boot.js` 照常写盘 |
| 引用面 | 顶层页（如 atc.html）引用新 hashed 名；长尾页仍只引用 `assets/style.css` / `assets/boot.js`（HTML 字节不变）；首页照旧内联 CSS |
| dist 体积 | 157,122 文件；1,538,345,910 → **1,538,347,602 B**（+1,692 B，只来自内联 CSS 增大） |

## 7. 截图（`docs/img/`）

| 视口 | 改前 | 改后 |
|---|---|---|
| 390×844 | [v101-results-390-before.png](../docs/img/v101-results-390-before.png) | [v101-results-390-after.png](../docs/img/v101-results-390-after.png) |
| 768×1024 | [v101-results-768-before.png](../docs/img/v101-results-768-before.png) | [v101-results-768-after.png](../docs/img/v101-results-768-after.png) |
| 1440×900 | [v101-results-1440-before.png](../docs/img/v101-results-1440-before.png) | [v101-results-1440-after.png](../docs/img/v101-results-1440-after.png) |

## 8. 剩余 / 交接

- **不在本工位范围**：写 `CHANGELOG v1.0.1`、生产构建、`sync_r2.ps1`、`verify_live`、增量 `-DryRun` 预演、tag/Release —— 由 Lead / `release` 执行。
- 发布时注意：本次 CSS 变更会让 `assets/style.<hash>.css` 与 `assets/boot.<hash>.js` 改名（顶层页引用变），长尾页不受影响；`release` 的增量预演应看到与 A/B 同量级的 78 文件左右。
- 已知既有偏差（未在本次范围）：`drug` 1440 items 4.5、`coverage` 390 items 3.5；2560 结果页 20.0 是 `RES_PAGE=20` 上限，不是密度瓶颈。
- 证据文件：`.tmp/v101-{before,after,after2,b}`、`.tmp/v101-{before,after}-fs.json`、`.tmp/v101-after-vs-before.json`、`.tmp/v101-{aa,ab,i18n}.json`、`.tmp/v101-geom-*.log`、`.tmp/v101-*-build.log`。
