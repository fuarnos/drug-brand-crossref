# v0.13.0 站点接线：CZ / LV（照 v0.12.0 JP 范本）

- 工位 site-ui（task-3）｜2026-11-16｜只改 `site/build.py` + 本报告；**未跑全量构建、未写 `site/dist`、未 commit、不碰 DB / etl / markets.json**（同窗口 phaseb-data / phaseb-plan 在写）。
- **结论**：站点侧 15 市场接线完成 —— 6 个新 i18n 键 × 5 语（30 条文案）+ 7 处国家码/模板常量已就位；`py_compile` 通过，`deploy/i18n_check.py` **FAIL 0**（654 键 × 5 语，fr 650/654 有译文），`deploy/ci_checks.py --fast` **PASS 8 / FAIL 0 / SKIP 4**，构建期 `_assert_i18n_complete()` 模拟通过（zh-Hant「未登记回落」= 0）。
- **差异规模**：`git diff --numstat site/build.py` → `139 6`（+139 / −6）。文件仍是全 CRLF（CRLF=16829，孤立 LF=0），edit 工具局部替换未触发整文件行尾翻转（无 15,000 行 diff）。
- 说明：派单里「build.py 已归一为 LF」与实况不符 —— `git ls-files --eol` 是 `i/crlf w/crlf`，全程按 CRLF 处理。

## 1. 插入点清单（行号 = 本次改后的 `site/build.py`）

| # | 位置（行号） | JP 范本对应（2b90681） | 本次改动 |
|---|---|---|---|
| 1 | `I18N["en"]` L218–219 | `home.jp` | `home.cz: "Czechia"` / `home.lv: "Latvia"` |
| 2 | `I18N["es"]` L466–467 | 同上 | `Chequia` / `Letonia` |
| 3 | `I18N["zh"]` L710–711 | 同上 | `捷克` / `拉脱维亚` |
| 4 | `FR_I18N`（扁平表）L932–933 | 同上 | `Tchéquie` / `Lettonie` |
| 5 | `UI_I18N["zh-Hant"]` L2452–2453 | 同上（zh-Hant 走 UI_I18N 的先例） | `捷克` / `拉脫維亞` |
| 6 | `COVERAGE_I18N["en"]` L1675–1680 | `coverage.gap.jp` | `coverage.gap.cz` / `coverage.gap.lv`（一句：开放数据注册库 ≠ 在售清单 + 来源/日期） |
| 7 | `COVERAGE_I18N["es"]` L1715–1720 | 同上 | 同上（西语） |
| 8 | `COVERAGE_I18N["zh"]` L1748–1753 | 同上 | 同上（简中） |
| 9 | `COVERAGE_I18N["zh-Hant"]` L1781–1786 | 同上 | 同上（繁中） |
| 10 | `FR_I18N.update` L1292–1297 | 同上 | 同上（法语） |
| 11 | `ABOUT_I18N["en"]` L2918 / L2929 | —（JP 只加了 gap 文案） | `about.cz_source` / `about.lv_source`：SÚKL / ZVA 的许可与署名段 |
| 12 | `ABOUT_I18N["es"]` L3096 / L3108 | — | 同上（西语） |
| 13 | `ABOUT_I18N["zh"]` L3249 / L3258 | — | 同上（简中） |
| 14 | `UI_I18N["zh-Hant"]` L2479 / L2488 | — | 同上（繁中；理由见 §5） |
| 15 | `FR_I18N.update` L1307 / L1320 | — | 同上（法语） |
| 16 | `build_about()` 键表 L13243–13246 | — | 追加 `about.cz_source` / `about.lv_source`（About 按这张表顺序渲染段落） |
| 17 | `SHELL_MARKETS` L9125–9128 | v0.12.0 同一常量 | 加 `("CZ","home.cz"), ("LV","home.lv")`（EU 之前） |
| 18 | `COUNTRY_PRIORITY` L10408 | 同一常量 | `… "JP","CZ","LV","EU"`（JP 后、EU 前；矩阵/成分页块/首页覆盖计数都按它排序） |
| 19 | 首页「目标市场」下拉 L13110 | 两处 `<option>` | `CZ` / `LV` option（JP 之后、EU 之前） |
| 20 | 首页「来源市场」下拉 L13123 | 同上 | 同上 |
| 21 | `SOURCE_SHORT` L13194–13195 | 无（JP 未登记） | `sukl_dlp→SÚKL`、`zva_lv_register→ZVA`：About 覆盖表「数据截止」列不再显示裸 source_id |
| 22 | `_shell_market_links()` docstring L9272 | — | 「10 个国别市场」→「13 个国别市场」（随常量同步的事实修正） |

覆盖页/首页的市场行本身是**数据驱动**（`coverage` 视图 + 产品行），代码侧无需逐市场登记：`coverage.gap.{c.lower()}`（L13326）、`home.{c.lower()}`（L13334）都是按国家码拼 key，DB 写库后 CZ/LV 自动出列。

## 2. 文案与许可口径（依据 `docs/许可清单.md` §2 + `reports/2026-11-12-{cz-sukl,lv-zalu}-acquisition.md`）

- **CZ / SÚKL**：`SÚKL 开放数据使用条款`（允许复制/再分发/商用；**须署名 SÚKL**、不得暗示背书、不得改变含义、再分发附条款链接，链接 `https://opendata.sukl.gov.cz/podminky-uziti-otevrenych-dat`）；**SPC/PIL/包装说明不取不发布**；排除 FSMP/PZLÚ 非药品行（REG ∈ {P,J}，1,451 行）；EU 集中审批与 EU 区域层去重；规格归一/成分拆分写明「派生自官方字段」；**收载 ≠ 当前在售**。
- **LV / ZVA**：`HumanProducts`（Latvijas Zāļu reģistrs）**CC0 1.0**（无强制义务，仍按惯例署名 ZVA）；包装级 → 注册号归并；EU 集中审批去重；**收载 ≠ 当前在售**。
- 数据日期：CZ **2026-11-01**（= DB `source.data_as_of` / `data/markets.json` 的口径；`data_as_of_note`：快照 `DLP20261027`、`dlp_platnost.platnost_od=01.11.2026`、抓取 2026-11-11）、LV **2026-11-11**（`HumanProducts.xml.zip` 的 `last_modified`，每日导出）。两处都带「快照 DLP20261027」注明（见 §5.1 的 task-4 补丁）。
- 五语市场名与本仓库既有口径一致：en `Czechia/Latvia`、es `Chequia/Letonia`、zh `捷克/拉脱维亚`、zh-Hant `捷克/拉脫維亞`、fr `Tchéquie/Lettonie`。

## 3. 自验（命令 + 输出）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m py_compile site/build.py            # exit 0
& $py deploy/i18n_check.py                    # FAIL 0 / WARN 2 / INFO 24
#   有效字典: en 654 / es 654 / zh 654 / zh-Hant 654 / fr 654 键（改前 648 × 5）
#   fr 译文 650/654（99.4%，改前 644/648）
& $py deploy/ci_checks.py --fast              # 12 项：PASS 8 / FAIL 0 / SKIP 4（12.8s）
#   [PASS] i18n  四语键集一致；WARN 2；最新版 v0.12.4 译文齐
```

构建期硬拦（`site/build.py` 的 `_assert_i18n_complete()`）不能等全量构建才验，用只读探针模块级模拟：
`_merge_static_i18n({})` → `_install_zh_hant({})` → `_assert_i18n_complete()`：
`i18n 四语一致: 654 keys × 5 语言（zh-Hant 回落 0 个已登记 key）`，`ZH_HANT_FALLBACK_KEYS = 0`。

grep 证据（改后行数）：

| key | 出现次数（= 五语各 1） | 示例行号 |
|---|---|---|
| `"home.cz":` | 5 | 218 / 466 / 710 / 932 / 2452 |
| `"home.lv":` | 5 | 219 / 467 / 711 / 933 / 2453 |
| `"coverage.gap.cz":` | 5 | 1292 / 1675 / 1715 / 1748 / 1781 |
| `"coverage.gap.lv":` | 5 | 1295 / 1677 / 1718 / 1750 / 1783 |
| `"about.cz_source":` | 5 | 1307 / 2479 / 2918 / 3096 / 3249 |
| `"about.lv_source":` | 5 | 1320 / 2488 / 2929 / 3108 / 3258 |

`data-i18n="home.cz"` / `home.lv` 各 **2** 处（两处下拉，L13110 / L13123）。行尾：`CRLF=16829 / 孤立 LF=0`。

## 4. 未做 / 已知缺口（请 Lead 判）

1. ~~**`MORDER`（`i18n.js` 段）缺 FR/JP/CZ/LV**~~ —— **task-4 已修**，见 §5.1。
2. **`atc.status_note` 五语（en L13532 / es L13603 / zh L13667 / zh-Hant L13716 / fr L1351）**：原文「只有 CA/ES/MX 有状态列；AU/HK 无状态列；CN/US/GB/TW/SG 记为 active」。CZ（`REG` 映射 active/discontinued/withdrawn）与 LV（`status` + `zr-prd-status.csv`）其实**有**状态列 —— 这句话自 JP 上线起就已不完整（JP 未列入），属既有 prose 债。改它要动五语 5 段，本轮未改。
3. **`about.sources` 紧凑来源段**（en/es/zh）只列最早 7 个市场；TW/SG/HK/AU/JP 都是走专段 `about.*_source`，CZ/LV 同口径，未改（保持既有结构）。
4. **出列前置条件**：覆盖率行来自 DB `coverage`，首页覆盖行/矩阵/成分页块来自 DB 产品行 → 要等 phaseb-data 写库完成、phaseb-plan 的 `markets.json` 落地后才会真正出现在页面上；本工位只保证常量、模板、文案就位。
5. **未跑**（按分工归 Lead 的全量构建）：`site/build.py` 全量、首屏守卫 `deploy/first_screen_check.py`、三语检索抽查、页数/索引/首屏体积回归、链接/404/sitemap 抽检。
6. **既有缺口（顺带发现，未改）**：`SHELL_MARKETS`（L9125）里没有 `FR` —— FR 自 v0.11.4 起已上线（有覆盖页行与 `home.fr`），但壳层的「按市场看覆盖」面板一直没它的入口（JP 范本也不含 FR）。要不要一次补上（`("FR","home.fr")` + docstring 改 14 国）请 Lead 定。

## 5. 两处口径说明

- **zh-Hant 值写在 `UI_I18N["zh-Hant"]`**，没有动 `data/i18n_zh_hant.json`（该文件不在本工位写权限；同 v0.11.9 的既有做法，见 `site/build.py` L1861 注释）。构建期 `_install_zh_hant()` 会把这两张表的 zh-Hant 值并入，实测「未登记回落」= 0。
- **JP 范本未加 `about.jp_source`**（只加了 `coverage.gap.jp`）。本轮派单明确要求 About 侧加 SÚKL / ZVA 署名段，所以 `about.cz_source` / `about.lv_source` 是本轮**超出 JP 范本**的唯一新增结构（ABOUT_I18N 3 语 + UI_I18N zh-Hant + FR_I18N.update + `build_about()` 键表）。

### 5.1 task-4 补丁（2026-11-16）：CZ「数据截止」对齐库口径 + MORDER 补 4 码

验收反馈的两个小缺口，只改 `site/build.py`（未构建 / 未写 dist / 未 commit）：

1. **CZ 日期口径统一（P1）**：`about.cz_source` 五语原来写 `2026-10-27`（快照 ZIP 的版本日），而 DB `source.data_as_of` 与 `data/markets.json` 都是 **2026-11-01**（`dlp_platnost.platnost_od=01.11.2026`，抓取 2026-11-11，见 `data_as_of_note`）→ 覆盖页读 DB、About 读文案，两页会显示不同日期。已把五语 `about.cz_source` 改成 **2026-11-01**，并统一加注「（快照 DLP20261027）」，同时把 `coverage.gap.cz` 五语里那处日期一并统一（同一句事实，避免覆盖页自己跟自己不一致）。**LV 的 2026-11-11 未动**（DB 与该文案一致）。
   - 核对命令（只读）：`.tmp/probe_cz_dates.py` → `source('sukl_dlp', …, '2026-11-01', 'DLP 快照 DLP20261027 的 dlp_platnost.platnost_od=01.11.2026；抓取 2026-11-11')`、`markets.json CZ 2026-11-01 / LV 2026-11-11`。
   - 改后：`Select-String '2026-10-27' site/build.py` → **0 处残留**；运行期探针（`.tmp/probe_cz_patch.py`）五语读数：en `as of 2026-11-01 (snapshot DLP20261027)`、es `Datos hasta …(instantánea DLP20261027)`、zh `数据截至 …（快照 DLP20261027）`、zh-Hant 同上繁体、fr `Données au …(instantané DLP20261027)`。
2. **`MORDER`（`i18n.js` 段，L15951–15954）**：原来只有 `en/es/zh/zh-Hant` 四组、都缺 `FR/JP/CZ/LV`，`rank[code]` 为 `undefined` → 矩阵列与「国家 chips」排序落到 99 之后且不稳定。已四组各补 `'FR','JP','CZ','LV'`，统一放在 `'EU'` 之前（内部顺序 FR, JP, CZ, LV，四条数组一致）。
   - **注意**：`MORDER` 只有 **4** 个语言数组（`fr` 没有独立数组，走 L15955 的 `MORDER[window.LANG] || MORDER.en` 兜底）——所以「五个数组」实际是 4 个数组 + fr 兜底；fr 用户现在也拿到含 4 码的 en 序。若以后要 fr 专属列序，再加 `fr:` 数组即可。
   - 排序逻辑本身（`rank` 构造 / `cells.sort`）未改。
3. **自验**：`py_compile` exit 0；`deploy/i18n_check.py` 键集/伪翻译/硬编码全过（654 键 × 5 语，`_assert_i18n_complete` 模拟通过、zh-Hant 未登记回落 0）。注意：本次 `i18n_check` 报 **FAIL 1 — `release-latest-missing`（v0.13.0 在 `data/release_notes_i18n.json` 里还没有译文）**，这是 Lead 刚加进 CHANGELOG 的 v0.13.0 节的 release-notes 译文尚未落盘（`data/release_notes_i18n.json` 不属本工位），**与本补丁无关**；本补丁只动 i18n 值与 JS 常量，未增删任何 key。
4. `git diff --numstat site/build.py` = **`144 10`**（累计任务 3+4）；文件仍全 CRLF（CRLF=16830 / 孤立 LF=0）。

## 6. 回滚

`git checkout -- site/build.py`（本工位未 commit、无产物、无 DB 影响）。
