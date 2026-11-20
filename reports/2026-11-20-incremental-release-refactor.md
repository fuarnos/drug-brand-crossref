# REL2-A 前端：长尾页稳定资源名 + 页脚去版本号（T69）

- 任务：`task-1`（REL2-A）· 工位 `frontend` · 2026-11-20
- 方案：`docs/发布增量重构方案-20261120.md` §3.1 + §4.1–4.4
- 改动文件：**只有 `site/build.py`**（+14 / −4 行）；未 commit、未写 `site/dist`、未碰 `deploy/`、未改数据与九语文案

## 0. 结论（先看这一段）

| 验收项 | 结果 |
|---|---|
| 实现 | 长尾页（6 类目录，**147,263 页**）改用 `assets/style.css` / `assets/boot.js`；页脚版本号改为「What's new」链接；顶层页保持 hashed 资源名 + 版本号 |
| **A/A′ 确定性** | `157,122` 文件 / `1,538,345,910` B，**0 差异**（逐字节一致） |
| **A/B 版本 +1** | 版本与日期各 +1（v1.0.1 · 2026-11-22）：总差异 **78 文件**（门槛 ≤500）；`name 0 / drug 0 / combo 0 / maker 0 / atc 0 / cat 0`。另跑「只改版本、日期不变」变体：**77 文件**，长尾同样 0 |
| 页面取证 | 长尾页只引用稳定名、无 hashed 名、无版本号；顶层页仍 hashed + 版本号（样本 + 全量扫描见 §4） |
| `deploy/i18n_check.py` | **FAIL 0**（WARN 25，均为既有 hardcoded 文案） |
| `deploy/first_screen_check.py` | **baseline 退化 0**；24 次扫描与 v0.19.0 基线完全同判（2 项 items 未达为既有） |
| `deploy/ci_checks.py --fast` | **FAIL 0**（PASS 8 / SKIP 5 · 24.7s） |
| CHANGELOG 临时改动 | 已按字节恢复（sha256 与 `git diff` 长度同改前一致，见 §6） |

**一句话**：版本号（+日期）+1 时，15 万余长尾页 0 变化——增量发布的前提（A/B 只剩 78 个顶层/资源/清单文件），且资源名固定后改 UI 也不再牵动长尾页。

## 1. 实现（`site/build.py`，4 处）

`page()` 内（行号为补丁后）：

1. **13359–13364**：新增 `shell_top = nav_coverage`、`css_href` / `boot_href` / `foot_news` 三个派生量（顶层页走原值；`ver` 仍在 13354）。
2. **13423**：`head_scripts` 由 `BOOT_JS_FILE` 改为 `boot_href`。
3. **13432**：`<link rel="stylesheet">` 由 `CSS_FILE` 改为 `css_href`。
4. **13470**：页脚第一链由写死 `{ver}` 改为 `{foot_news}`；13437 处旧 `shell_top = nav_coverage` 定义改为注释（避免二处定义）。

```python
    shell_top = nav_coverage
    css_href = CSS_FILE if shell_top else "assets/style.css"
    boot_href = BOOT_JS_FILE if shell_top else "assets/boot.js"
    # 页脚：顶层页保留版本号；长尾页只留「更新日志」链接，版本号不再逐页写死。
    foot_news = (f'<a href="{prefix}whats-new.html">{ver}</a>' if shell_top else
                 f'<a href="{prefix}whats-new.html" data-i18n="nav.whatsnew">What\'s new</a>')
```

- **稳定副本每次构建都写**（补丁前后都是无条件写）：`assets/style.css` 在 20294、`assets/boot.js` 在 20363；已用构建产物核对：`style.css` 与 `style.885ce0a604.css` 同 sha256（`885CE0A6…`），`boot.js` 与 `boot.882e52f15e.js` 同 sha256（`882E52F1…`）。
- 顶层页 8 个（index/about/atc/coverage/confused/warn/glossary/whats-new）+ 九语副本 56 页保持旧状；首页与语言首页的「CSS/JS 内联」是既有首屏设计（`_optimize_home_html`），本次未动。
- `combo/` 的 **9,553 个 noindex 兼容 stub** 不走 `page()`（内联 style，本来就没有版本号/hashed 资源），本次不动。

## 2. 命令（全部显式 `SITE_OUT`，本工位只写 `.tmp/`）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 0) 打补丁（字节级、断言每处只命中 1 次、保持原行尾）
& $py .tmp\rel2a_patch.py
& $py -m py_compile site/build.py

# 1) A：当前 CHANGELOG（v1.0.0 · 2026-11-21）
$env:SITE_OUT = '.tmp\rel2a-a';  & $py site/build.py *> .tmp\rel2a-a-build.log;  Remove-Item Env:SITE_OUT
# 2) A′：同输入再构一次
$env:SITE_OUT = '.tmp\rel2a-a2'; & $py site/build.py *> .tmp\rel2a-a2-build.log; Remove-Item Env:SITE_OUT
# 3) B：CHANGELOG 顶部 v1.0.0 · 2026-11-21 → v1.0.1 · 2026-11-22（版本+日期各 +1；
#    同时把 v1.0.1 九语条目临时复制进 data/release_notes_i18n.json ——
#    build.py 的 _assert_i18n_rules() 要求最新版九语齐全）
#    备份两文件 → rel2a_bump.py → build → finally 按字节恢复
#    （另跑过「只改版本号、日期不变」变体到 .tmp/rel2a-b：77 文件差异，结论一致）
$env:SITE_OUT = '.tmp\rel2a-b2'; & $py site/build.py *> .tmp\rel2a-b2-build.log; Remove-Item Env:SITE_OUT

# 4) A/A′ 与 A/B 对比（仓库自带脚本，sha256 清单）
& $py deploy/check_build_determinism.py .tmp\rel2a-a .tmp\rel2a-a2 --json .tmp\rel2a-aa.json
& $py deploy/check_build_determinism.py .tmp\rel2a-a .tmp\rel2a-b2 --json .tmp\rel2a-ab2.json

# 5) 页面取证（样本 + 全量扫描）
$env:PYTHONIOENCODING='utf-8'
& $py .tmp\rel2a_probe.py .tmp\rel2a-a --scan

# 6) 门禁
& $py deploy/i18n_check.py --json .tmp\rel2a-i18n.json          # 需 PYTHONIOENCODING=utf-8（GBK 控制台会崩）
& $py deploy/first_screen_check.py --dist .tmp\rel2a-a --baseline .tmp\fs-baseline-v0190.json --json .tmp\rel2a-fs.json
& $py deploy/ci_checks.py --fast --dist .tmp\rel2a-a
```

构建三个目录均跑到 `== done ==`；`build version: 3933853198`（build.py 改了，相对 v0.19.0 的 `510d5a90dd` 是预期变化；同一源码两次构建相同）。

## 3. 数字

| 项 | A | A′ | B（v1.0.1 · 2026-11-22） |
|---|---:|---:|---:|
| 文件数 | 157,122 | 157,122 | 157,122 |
| 字节数 | 1,538,345,910 | 1,538,345,910 | 1,538,345,910（替换串等长，总量恰好相同） |
| 相对 A 差异 | — | **0** | **78** |

- A/A′：`only_a=0 only_b=0 differ=0`，`deploy/check_build_determinism.py` 退出码 0。
- A/B：`common=157,122 only_a=0 only_b=0 **differ=78**`（≤500 ✅）；另跑的「只改版本号、日期不变」变体（`.tmp/rel2a-b`）为 **77**，长尾同样 0。
- 页面数未变：name 109,575 / drug 13,434 / combo 17,424（其中真页 7,871）/ maker 15,213 / atc 1,154 / cat 16；sitemap 78,224 URL（与 v0.19.0 相同）。

## 4. 页面取证

### 4.1 页脚原文（`.foot-links` 第一个链接）

| 页面 | A（v1.0.0 · 2026-11-21） | B（v1.0.1 · 2026-11-22） |
|---|---|---|
| `index.html` / `atc.html`（顶层） | `<a href="whats-new.html">v1.0.0 · 2026-11-21</a>` | `<a href="whats-new.html">v1.0.1 · 2026-11-22</a>` |
| `es/index.html`（顶层副本） | `<a href="../whats-new.html">v1.0.0 · 2026-11-21</a>` | 同型（v1.0.1 · 2026-11-22） |
| `name/…` / `drug/…` / `atc/A.html`（长尾） | `<a href="../whats-new.html" data-i18n="nav.whatsnew">What's new</a>` | **同 A（不含版本号/日期）** |

### 4.2 全量 HTML 扫描（`rel2a_probe.py --scan`）

| 目录 | html | 引用 `style.css` | 引用 `boot.js` | hashed css | hashed boot | 版本号 |
|---|---:|---:|---:|---:|---:|---:|
| name | 109,575 | 109,575 | 109,575 | **0** | **0** | **0** |
| drug | 13,434 | 13,434 | 13,434 | **0** | **0** | **0** |
| combo | 17,424 | 7,871（真页；其余 9,553 为 noindex stub） | 7,871 | **0** | **0** | **0** |
| maker | 15,213 | 15,213 | 15,213 | **0** | **0** | **0** |
| atc | 1,154 | 1,154 | 1,154 | **0** | **0** | **0** |
| cat | 16 | 16 | 16 | **0** | **0** | **0** |

即 **147,263 个走 `page()` 的长尾页 100% 用稳定名，0 处 hashed 资源名、0 处版本号**。样本页（name/drug/combo/maker/atc/cat 各 1）另已逐页断言通过。

- 长尾页体积每页 **−8 B**（资源名变短、页脚文字变短）：`name/tylenol-8-hr-arthritis-pain.html` 4,110→4,102 B、`drug/02-6221-6900.html` 10,941→10,933 B、`maker/100-karma-inc.html` 13,765→13,757 B、`atc/A.html` 797,490→797,482 B。
- 顶层页样本（atc/about/coverage/whats-new/warn/confused/glossary + es/zh 副本）均仍为 `assets/style.<hash>.css` + `assets/boot.<hash>.js` + 版本号。

## 5. A/B 差异明细（78 文件）

| 族 | 共有 | 不同 | 说明 |
|---|---:|---:|---|
| 八种语言副本（cs/es/fr/ja/ko/lv/zh/zh-Hant） | 56 | 56 | 每语 7 个顶层副本，页脚版本号/日期 |
| 顶层 html | 9 | 8 | index/about/atc/coverage/confused/warn/glossary/whats-new（404 无版本号，不变） |
| assets | 17 | 10 | `i18n.js` + 9 个 `i18n.<lang>.js`：字典内含 `rel.vX` 键（由 CHANGELOG + release_notes 生成） |
| 清单/元数据 | 4 | 4 | `datapackage.json`、`dataset.jsonld`、`checksums.txt`、`sitemap.xml`（日期 +1 改 lastmod；只改版本号的变体里 sitemap 不变，故为 77） |
| **长尾六类** | **156,816** | **0** | name 109,575 / drug 13,434 / combo 17,424 / maker 15,213 / atc 1,154 / cat 16 |
| data / data/idx 等 | 其余 | 0 | — |
| **合计** | 157,122 | **78** | 门槛 ≤500 ✅ |

- 版本 bump **不会**改 `BUILD_V`（它只哈希 build.py + zh-Hant 字典），所以 boot.js 里的资源版本不变、长尾 HTML 不跟着变——这是本次 A/B 只剩 78 个文件的直接原因。
- 观察（留给 release/后续）：版本 bump 仍会改 10 个 `assets/i18n*.js`（字典嵌 `rel.vX` 键），属每次发布的小额上传（≈10 个文件），远小于单次 3,000 PUT 目标；不影响长尾页。

## 6. 门禁与恢复证明

| 检查 | 结果 |
|---|---|
| `i18n_check.py` | `ok=True`、**fail=0**、warn=25（既有 hardcoded 文案 + 2 条 es 白名单提醒） |
| `first_screen_check.py --baseline .tmp/fs-baseline-v0190.json` | `regressions=0`、`unstable=0`、`suspect=0`；24 次扫描中 `fail_scans=2 / fail_items=2（items）` —— 与 v0.19.0 基线**逐项相同**（drug 1440 行 4.5、coverage 390 行 3.5，均为已知既有偏差），结论「无退化」；耗时 86.6s |
| `ci_checks.py --fast --dist .tmp/rel2a-a` | **FAIL 0**（PASS 8 / SKIP 5 / 24.7s）；`dist-integrity`：157,122 文件、0 字节 0、sitemap 78,224；unittest etl/lib/mobile/lib-atc 全 OK |
| CHANGELOG 恢复 | 备份→临时 v1.0.1→try/finally 恢复：sha256 改前/改后均 `7E5AB403…`，`git diff CHANGELOG.md` 长度均 **825**（都是 Lead 的 v1.0.0 改动；工位临时改动零残留） |
| `data/release_notes_i18n.json` 恢复 | sha256 改前/改后均 `EC0FA41A…`，`git diff` 长度均 **8,394**（零残留） |
| 行尾 | `site/build.py` 仓库内本就是 CRLF（`git ls-files --eol` = `i/crlf w/crlf`），本次按原样保持：补丁后 `LF 21,520 / CRLF 21,520`、无混合行尾；`git diff --stat` 仅 18 行，无 EOL 噪声（未强转 LF，避免 21,520 行全文件 diff） |

> 过程坑：第一次尝试只把 `CHANGELOG` 升到 v1.0.1、没给 `release_notes_i18n.json` 补对应九语条目，被 build.py 的 `_assert_i18n_rules()` 拦截（v1.0.0 起新增门禁，构建中止）；之后两文件一起临时改、构建通过、`finally` 按字节恢复（失败那次的 `finally` 同样恢复了）。B 共跑两版：只改版本号（77 文件）、版本+日期各 +1（78 文件），结论一致。

## 7. 剩余 / 交接

- **不在本工位范围（未做）**：生产构建、`sync_r2.ps1`、`verify_live`、tag/Release、commit —— 按分工由 `release` / `Lead` 执行。
- 过渡期旧哈希资源 `assets/style.885ce0a604.css` / `assets/boot.510d5a90dd.js` 仍需 release 在 sync 里 `--exclude` 保留（REL2-B）。
- `deploy/verify_live.py` 的 `longtail-footer` 常驻门禁由 release 加；本实现产出的长尾页已满足：含 `assets/style.css`、`assets/boot.js`、`whats-new.html`，不含版本号正则。
- 证据目录（可复跑）：`.tmp/rel2a-a`（A）、`.tmp/rel2a-a2`（A′）、`.tmp/rel2a-b2`（B：版本+日期）、`.tmp/rel2a-b`（B 变体：只改版本）、`.tmp/rel2a-{aa,ab2,ab,i18n,fs}.json`、`.tmp/rel2a-*-build.log`。

## 8. 复现期望值

```text
A/A′:  files 157,122 / bytes 1,538,345,910 / differ 0
A/B :  differ 78 / only_a 0 / only_b 0     （只改版本号变体：77）
        name 109575/0  drug 13434/0  combo 17424/0  maker 15213/0  atc 1154/0  cat 16/0
scan:  hashed_css=0 hashed_boot=0 ver=0（六类长尾目录）
gate:  i18n fail=0 · first_screen regressions=0 · ci --fast FAIL 0
```
