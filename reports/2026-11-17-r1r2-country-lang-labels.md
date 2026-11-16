# R1+R2 国家「本语言名称 · 简写」+ 语言菜单本语言自称（v0.13.3）

> 工位：site-ui ｜ 任务：task-1 ｜ 日期：2026-11-17 ｜ 改动文件：`site/build.py`（+153/−26 行）
> 不改 `lib/` `deploy/` `etl/` `data/`，不写 `site/dist`：构建输出到 `.tmp/dist-r1r2`。

## 结论（先看这段）

1. **R1 完成**：国家/地区在结果行、成分页市场块头 /「也在」链接 / 筛选 chip 提示、复方页、矩阵列头全部变成
   「本语言名称 · 简写」（中文「美国 · US」/ 英文「United States · US」/ 西语「Estados Unidos · US」/
   繁中「美國 · US」/ 法「États-Unis · US」）。名称只取现成译名（`UI_I18N` 的 `home.<code>` →
   `data/markets.json` 的 `name.<lang>` → 英文），**没有新造译名**、没有手工国家表。
   覆盖页 / About / 首页市场面板本来就是「名称 + 简写」两段，未动。
2. **R2 完成**：语言菜单三处渲染（页头下拉、移动「⋯」菜单、长尾页 `boot.js` 注入壳）+ 客户端改写
   （`i18n.js` 的 `LBL`）一律 `English / Español / 中文 / 繁體中文 / Français`；hreflang 与 URL 目录未变。
3. **长尾页语言**：`drug/*.html` 只有英文产物，块头名称走 `data-mkc-name` + `i18n.js apply()` 改写，
   切到中文后是「中国 · CN」（浏览器实测见 §4）。
4. 验收数字：`i18n_check.py` FAIL 0、`ci_checks.py --fast` PASS 8 / FAIL 0、首屏守卫与改前基线逐项对比见 §5。

## 1. 改了什么（最小行数）

| 位置 | 改动 |
|---|---|
| `site/build.py` L1504 区 | `LANG_NATIVE_LABELS` + `_BASE_LANGS` 标签 `EN/ES/中文/繁` → `English/Español/中文/繁體中文`，fr 追加标签 `FR` → `Français` |
| 紧接其后（新增 ~45 行） | `_market_names()` / `_country_name()` / `_country_label()`：名称优先级 + 去掉与简写重复的尾部括号（「欧盟（EU）」→「欧盟」） |
| `_shell_right()` | 缺省标签 `EN` → `English` |
| 成分页市场块头（`_drug_list_html`，新增 `lang` 参数） | `<h2 class="mkhead-t"><span data-mkc-name="CN">China</span><span class="mkc"> · CN</span> …` |
| 成分页「也在」链接（两处：前 3 个 / 展开后的其余） | `<a href="#mk-US" data-mkc="US">United States · US</a>` |
| 成分页筛选 chip | 仍只写简写（14 个字块会撑爆筛选条），全名进 `title` |
| 矩阵列头（`?view=table`） | 列太窄（`min-width:860` + 横向滚动）→ 仍写简写，全名进 `title` / `aria-label` |
| 复方页 `.mktxt` | 服务端写英文 + `data-mkc="US GB"`，客户端按界面语言改写 |
| `APP_JS` | 新增 `mktLabel()`；`mktText()` 改用它、多国用 `, ` 连接、`title` 放完整列表；结果行 `max` 按视口取值（§3） |
| `i18n.js` 模板 | `LBL` 从构建期注入的 `LANG_NATIVE_LABELS` 生成（不再写死 `EN/ES/中文/繁`）；新增 `[data-mkc]` / `[data-mkc-name]` 改写 |
| `CSS` | `.mktxt` 手机（<768px）允许换行；`.mkhead .mkc` 手机上隐藏；≥1200px 结果表市场列 28%（见 §3） |

## 2. R2 语言菜单：五语逐项自称（构建产物实测）

`assets/i18n.js` 的 `LBL` 由构建期注入的 `LANG_NATIVE_LABELS` 生成（改前写死 `EN/ES/中文/繁`），
页头下拉 / 移动端「⋯」菜单 / 长尾页 `boot.js` 注入壳三处共用 `_BASE_LANGS` 的标签。

浏览器实测（`.tmp/dist-r1r2`，Playwright 读 DOM）：

| 检查点 | 结果 |
|---|---|
| `.lang-menu a` 文案（每页 2 份菜单） | `English / Español / 中文 / 繁體中文 / Français`（五语页面都一样） |
| 下拉摘要 `.lname`（界面 zh / en） | `中文` / `English`（改前是「EN」；coverage/about 服务端仍写英文，由 `apply()` 改写） |
| `hreflang` / URL 目录 | 未变（`en / es/ / zh/ / zh-hant/ / fr/`） |
| 静态 HTML（不执行 JS）里的菜单文案 | 同样是 5 个自称（服务端渲染） |

## 3. 结果行市场列：改前 / 改后实测（1440 / 1024）

改前 / 改后都只量「真实 DOM」（`getBoundingClientRect` / `scrollWidth`，环境 Chrome + `.tmp/dist-r1r2`）。

改前（v0.13.2 的 5 列等宽 + 裸简写）：

| 视口 | 表宽 | 列宽 | 可用宽（扣 12+12 padding） | 现状文本 |
|---|---|---|---|---|
| 1440×900 | 920px | 184px | 160px | 「AU CA ES GB +3」94px |
| 1024×768 | 643px | 128px | 104px | 同上 |

候选标签文本宽（同一 `.mktxt` 计算样式，13px）：

| 文本 | 宽 |
|---|---|
| `United States · US` | 102px |
| `United Kingdom · GB` | 120px（`scrollWidth` 144 含 padding） |
| `美国 · US` | 52px |
| `United States · US, United Kingdom · GB` | 229px |
| `美国 · US, 英国 · GB` | 110px |

结论（所以「桌面 2 / 手机 1」不是拍脑袋）：

- 1440 等宽时可用 160px → 2 个英文标签（229px）放不下；1024 可用 104px → 连 1 个
  「United Kingdom · GB」（120px）都会被裁（实测 20 行里 3 行被裁）。
- 改后：市场列**768px 起加宽到 32%**（`table-layout:fixed` 的列宽只认首行 thead th，所以改的是
  `thead th:nth-child(4)`）→ 实测 768：表 713 / 列 228 / 可用 204；1024：表 643 / 列 205 / 可用 181；
  1440：表 920 / 列 294 / 可用 270。加宽后 768 / 1024 / 1440 三档**行高仍 40px、商品名列换行数不变**。
- 标签数量按**字符预算 27 单位**（CJK 记 2，13px 下 ≈ 170px）挑，并给「 +N」留 4 单位：
  「Spain · ES, Mexico · MX」= 23 单位 → 显示 2 个；「United Kingdom · GB, United States · US」= 39 单位
  → 只显示 1 个 + 「+N」；完整市场列表永远在 `title` 里。
- 结果（实测 5 语 × 1440）：`Australian · AU +6` / `西班牙 · ES, 墨西哥 · MX` / `捷克 · CZ` …
  `clipped = 0`（20 行），页面无横向溢出；1024 改后同样 `clipped = 0`。
- 手机（390×844）：列变成整宽卡片（347px），`white-space:normal` 允许换行，只放 1 个 + 「+N」，
  页面 `scrollWidth = 375`（视口 390）→ **无横向溢出**。

## 4. 长尾页切语言实测（浏览器，`.tmp/dist-r1r2`）

成分页只有一份英文产物（`drug/*.html`），所以块头名称与「也在」链接由 `i18n.js apply()` 按界面语言改写：

| 界面语言 | `.mkhead-t` 实测 | 「也在」实测 |
|---|---|---|
| zh（`?lang=zh`） | 中国 · CN / 美国 · US / 英国 · GB / 西班牙 · ES | 也在 美国 · US, 英国 · GB, 加拿大 · CA +4（展开：澳大利亚 · AU, 中国台湾 · TW, 新加坡 · SG, 日本 · JP） |
| en | United States · US / China · CN / United Kingdom · GB | also in United States · US, United Kingdom · GB, Canada · CA |
| zh-Hant（结果页） | — | 澳大利亞 · AU / 英國 · GB / 西班牙 · ES, 墨西哥 · MX |
| es / fr（结果页） | — | España · ES, México · MX / Espagne · ES, Mexique · MX |

## 5. 首屏守卫 before / after（`deploy/first_screen_check.py`）

改前基线 `.tmp/fsc-before-20261117.json`（v0.13.2 产物 `site/dist`），改后 `.tmp/fsc-after-20261117.json`
（最终产物 `.tmp/dist-r1r2`，含 R7）：

| 页面 | 视口 | 首屏条目 | chrome 占比 | AFCR | 横向溢出 |
|---|---|---|---|---|---|
| home | 390 / 768 / 1440 | 0 / 9 / 9 → 0 / 9 / 9 | 0.14 / 0.11 / 0.07 不变 | 0.93 / 1.01 / 1.00 不变 | 0 → 0 |
| results | 390 / 768 / 1440 | 3 / 3 / 3 → 3 / 3 / 3 | 0.19 / 0.19 / 0.13 不变 | 0.87 / 0.91 / 0.90 不变 | 0 → 0 |
| drug | 390 / 768 / 1440 | 5.5 / 5.5 / 4.5 → 5.5 / 5.5 / 4.5 | 0.14 / 0.11 / 0.07 不变 | 0.93 / 1.01 / 1.00 不变 | 0 → 0 |
| coverage | 390 / 768 / 1440 | 1.5 / 3.5 / 5.5 → 1.5 / 3.5 / 5.5 | 0.27 / 0.19 / 0.14 不变 | 0.79 / 0.91 / 0.90 不变 | 0 → 0 |

守卫自己的结论：`24 次扫描：3 组不达标（coverage 390/768 + drug 1440，与改前同一批）、
baseline 退化 0 项`。**没有一项退化**。

390×844 无横向溢出：results 页 `document.documentElement.scrollWidth = 375`（视口 390，扣滚动条），
drug 页 `scrollWidth = innerWidth`，`overflow = 0`。

## 6. 构建结果与体积

`SITE_OUT=.tmp/dist-r1r2`，构建到 `== done ==`（第 5 次构建，含 R7）。

| 指标 | 改前 `site/dist` | 改后 `.tmp/dist-r1r2` | 差 |
|---|---|---|---|
| 页面数（.html） | 137,101 | 137,093 | −8（R7 盐型合并让 7 个复方页 + 1 个名字页不再生成） |
| 文件数 | 137,331 | 137,323 | −8 |
| `core.json` raw | 40,243,026 B | 40,239,135 B | −3,891 B |
| `core.json` gzip | 9,232,865 B | 9,232,615 B | −250 B |
| `index.html` raw / gz | 185,946 / 49,677 | 187,805 / 50,277 | +1,859 / **+600 B（+1.2%）** |
| `zh/index.html` gz | 50,632 | 51,217 | +585 |
| `drug/metformin.html` raw / gz | 194,340 / 17,775 | 205,332 / 18,578 | +10,992 / **+803 B（+4.5%）**（「也在」链接从 2 字符变「名称 · 简写」） |
| `assets/app.js` gz | 66,186 | 67,474 | +1,288（mktLabel/mktFit + 词表对齐） |
| `assets/i18n.js` gz | 100,918 | 101,442 | +524（`LBL` 自称表 + `data-mkc` 改写） |
| `assets/boot.js` gz | 5,918 | 5,939 | +21 |
| `coverage.html` gz | 5,885 | 5,900 | +15 |

首屏体积（`index.html` gz）**+600 B / +1.2%**，在一次 1,800 B 的文案变化范围内，未触发预算告警。

## 7. 验收命令（全部实跑）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -X utf8 deploy\i18n_check.py                                    # FAIL 0 / WARN 2（改前同样是 WARN 2）
& $py -X utf8 deploy\ci_checks.py --fast --dist .tmp\dist-r1r2        # PASS 8 / FAIL 0 / SKIP 5
& $py -X utf8 deploy\first_screen_check.py --dist .tmp\dist-r1r2 --json .tmp\fsc-after-20261117.json --baseline .tmp\fsc-before-20261117.json
& $py -X utf8 .tmp\r1r2_verify.py .tmp\dist-r1r2                      # 语言菜单 + 国家标签结构，FAIL 0
$env:SITE_OUT='.tmp/dist-r1r2'; & $py -X utf8 site\build.py           # == done ==
& $py deploy\ui_sort_smoke.py --dist .tmp\dist-r1r2                   # R7 门禁，exit 0
```

## 8. 截图（`docs/img/`）

| 文件 | 内容 |
|---|---|
| `v0133-r1r2-results-zh-1440.png` | 结果页（中文）：`西班牙 · ES, 墨西哥 · MX` / `澳大利亚 · AU, 加拿大 · CA +5` |
| `v0133-r1r2-results-en-1440.png` | 结果页（英文）：`United States · US` 等 |
| `v0133-r1r2-results-es-1440.png` | 结果页（西语）：`España · ES, México · MX` |
| `v0133-r1r2-results-zh-hant-1440.png` | 结果页（繁中）：`澳大利亞 · AU`、`英國 · GB` |
| `v0133-r1r2-results-fr-1440.png` | 结果页（法语）：`Tchéquie · CZ`、`Royaume-Uni · GB` |
| `v0133-r1r2-results-zh-390.png` | 结果页 390×844：单列卡片，换行不溢出 |
| `v0133-r1r2-drug-zh-mkhead-1440.png` | 成分页（中文）：市场块头 `美国 · US` / `英国 · GB`…，行内「也在 美国 · US, 英国 · GB…」 |
| `v0133-r1r2-coverage-zh-1440.png` | 覆盖页（中文）：名称 + 简写两段 |
| `v0133-r1r2-langmenu-zh-1440.png` | 语言下拉：English / Español / 中文 / 繁體中文 / Français |
| `v0133-r1r2-home-markets-zh-1440.png` | 首页「Markets」下拉：14 个市场 + EU，名称 + 简写 |

## 9. 还剩什么 / 已知缺口

1. **成分页「也」链接会被省略号截断**：`.mkx` 是单行省略号（`white-space:nowrap; overflow:hidden`），
   换成名称后 1440 下通常只显示前 1–2 个市场，完整列表在点开的「另 N 个市场」里。若要每行都显示全，
   需要把 `.mkx` 改成两行（会动成分页行高，得单独评估首屏条目）。
2. **矩阵视图（`?view=table`）列头仍只写简写**：列宽 `min-width:860` + 横向滚动，写全名会挤爆列；
   全名放在 `title` / `aria-label`。手机矩阵用 `td[data-country]::before` 输出简写，同理。
3. **成分页市场块头在 <768px 只显示名称**（`.mkc` 隐藏），为保住 390 首屏条目 5.5 条；结果行 / 复方页
   在手机上仍是「名称 · 简写」。
4. **ATC 页 / 大类页行内的市场串（`.atc-mk`）仍是简写**：一页几十行、每行 1–8 个市场，写全名会把行宽拉爆；
   本轮未改，若要改需要单独的密度方案。
5. `coverage.html` / `about.html` 服务端仍写英文下拉摘要（`English`），由 `i18n.js apply()` 在客户端改成
   当前语言（改前基线同样如此，`EN` → `English` 不改变行为）。


（待填）
