# 挪威 NO 站点注册（第 16 个市场，v1.1.0 前端交付）

- 日期：2026-11-22（北京时间）｜工位：frontend｜任务：共享任务板 `task-2`
- 数据：backend `task-1`（`data/drugs.db` 的 NO 写入）｜发布：release `task-3`（本报告不含构建/发布结论）
- 只读/写边界：本工位只改 `site/build.py`、`data/markets.json`、`tests/test_markets_registry.py`（Lead 批准的连带改动）、`reports/`；
  **未写 `site/dist`**（全部自验构建显式 `SITE_OUT=.tmp/frontend-no`）、未改 `etl/` `db/` `lib/`、未 commit、未发布。

## 0 结论（先行）

1. **NO 已注册为第 16 个国家市场**：`data/markets.json` `order=150`、`source_id=dmp_fest`、
   许可 **NLOD 2.0**、`data_as_of=2026-11-10`、`ui_language_gaps=["nb","no"]`（挪威语界面未接入，本版**不新增界面语言**）。
2. **市场清单只有一份**：顶部菜单 / 覆盖页行 / 首页两处筛选 / 矩阵列序 / 覆盖页行序全部由
   `data/markets.json`（`SHELL_MARKETS`）+ `COUNTRY_PRIORITY` 派生；本次没有新增任何硬编码国家清单。
3. **署名三处落点**：About 许可块（NLOD 英文原句逐字 + 中文 + 挪威语）、About 来源段（9 语）、
   覆盖页 NO 缺口说明（9 语）、`datapackage.json` 的 `sources[].attribution`（英文原句逐字）。
4. **口径**：FEST 是**处方链数据服务，不是注册库全量**；**只有活动条目**（无停用/撤市状态）、**没有注册号**
   （只有订货号 `Varenr` 与条码 `Ean`）。页面/署名均按这个口径写，未出现「注册库全量」。
5. **门禁**：`deploy/i18n_check.py` **FAIL 0**；`lib/markets.py --check` 通过；`tests/test_markets_registry.py` 通过。
   首屏守卫改前/改后数字见 §6（改前 = 同一份源码的 v1.0.0 产物 `.tmp/v101-after2`）。
6. **顺带修复**：首页两处筛选此前漏了 MY（注册表已启用但下拉框是手写清单），本次一并修好（§7）。

## 1 改了什么（文件级）

| 文件 | 改动 | 为什么 |
|---|---|---|
| `data/markets.json` | 新增 NO 条目（17 个市场：16 国 + EU）；`updated` 2026-11-20 → 2026-11-22 | 市场注册表是唯一真相源；`lib/markets.py` 校验、站点派生的输入 |
| `site/build.py` | ① `COUNTRY_PRIORITY` 加 `NO`；② 新增 `market_order_for()` / `MORDER_JSON` 取代 i18n.js 里手写的 4 份 `MORDER` 数组；③ 新增 `_market_filter_codes()` / `_market_options_html()`，首页 `#country`、`#src` 两个 `<select>` 改由同一份清单生成；④ `SOURCE_SHORT` 加 `dmp_fest`；⑤ 新增 `SOURCE_ATTRIBUTION` 并写进 `datapackage.json`；⑥ `MARKET_EXTRA_I18N` 加 3 个键 × 9 语；⑦ About 渲染循环加 `about.no_source`；⑧ `LICENCE_HTML` 加挪威条目（EN/中文/挪威语署名） | 加市场只改两处（注册表 + 统一序），不再到处手写国家清单 |
| `tests/test_markets_registry.py` | `SITE_COUNTRY_I18N`、`MARKET_NATIVE_LANGS["NO"]`、市场集合/计数/缺口断言、新增 `test_no_market_row` | 该文件把注册表现状写成常量；不更新必红。**Lead 2026-11-22 已批准** |
| `reports/2026-11-22-no-site-registration.md` | 本报告 | 证据与缺口 |

**没有改**：`data/languages.json`（本版不新增界面语言；`ui_language_gaps` 只写在 markets.json）、
`docs/市场扩展接口.md`、`docs/许可清单.md`、`CHANGELOG.md`（由 release 决定）、`etl/` `db/` `lib/`。

## 2 单一真相源与派生链

| 页面/功能 | 数据来源 | 代码位置 |
|---|---|---|
| 顶部「Markets」菜单 + 移动菜单 | `data/markets.json` 的 `enabled` 市场，按 `order` | `_registry_shell_markets()` → `SHELL_MARKETS` → `_shell_market_links()` |
| 覆盖页行序 | 同上（`SHELL_MARKETS` 的下标） | `build_coverage_page()` 的 `_mk_order` |
| 覆盖页行内容（产品数/映射率/规格率/数据截止） | DB `coverage` 视图 + `source` 表 | `build_coverage_page()`、`_as_of_cell()` |
| 首页「目标市场 / 来源市场」下拉 | `SHELL_MARKETS` ∪ 库里有数据的市场 | `_market_filter_codes()` / `_market_options_html()` |
| 成分页矩阵列序 / 国家 chips 排序 | `COUNTRY_PRIORITY` + 语言偏好前缀 | `market_order_for()` → `MORDER_JSON`（注入 i18n.js） |
| 首页覆盖提示 `covline` | DB `coverage` | `build_index_page()` |

加一个市场的维护点是 **2 处**：`data/markets.json` 一条 + `site/build.py` 的 `COUNTRY_PRIORITY` 一个码
（若该市场有专属文案，再加 `MARKET_EXTRA_I18N` 的 3 个键 × 9 语）。

## 3 九语文案（新增 3 个键 × 9 语言）

`MARKET_EXTRA_I18N`（构建期注入 9 份 I18N，与 v0.18.0 的 MY 同型；不改 9 张全键表，键数 684 → 687 × 9 语）：

| key | en | es | zh | zh-Hant | fr | ko | ja | cs | lv |
|---|---|---|---|---|---|---|---|---|---|
| `home.no` | Norway | Noruega | 挪威 | 挪威 | Norvège | 노르웨이 | ノルウェー | Norsko | Norvēģija |
| `coverage.gap.no` | FEST 处方链口径 + NLOD + 截止日 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `about.no_source` | 来源段（含署名原句） | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

- `deploy/i18n_check.py`：**FAIL 0**（WARN/INFO 与改前同一类，未新增）。
- 构建期 `_assert_i18n_complete()` 复核：9 语键集完全一致（`== 687 keys × 9 语言`，见 §5 构建日志）。
- **不新增界面语言**：`data/languages.json` 未动，仍是 en/es/zh/zh-Hant/fr/ko/ja/cs/lv 九种；
  `ui_language_gaps=["nb","no"]` 只用于覆盖页「母语未覆盖」状态（现有 LG3/LG4 组件）。

## 4 署名与口径落点

**要求的英文原句（逐字，NLOD 2.0 §5）**

> Contains data under the Norwegian Licence for Open Government Data (NLOD 2.0) distributed by the
> Norwegian Medical Products Agency (DMP). Changes have been made by DrugCrossRef (normalisation of
> ingredient names, strengths and dosage forms).

| 落点 | 位置 | 内容 |
|---|---|---|
| About（许可块） | `LICENCE_HTML` 的 Norway 条目 | 英文原句逐字 + 中文署名 + **挪威语署名**（`Norsk lisens for offentlige data (NLOD 2.0)`）+ `DMP FEST` 与 `NLOD 2.0` 链接 + 数据截止 2026-11-10 + 口径 |
| About（来源段） | `about.no_source`（9 语） | 来源、许可、署名原句（en/fr/cs/lv 用英文原句引用，zh/zh-Hant/ja/ko 本地化）、数据截止、范围与缺口 |
| 覆盖页 | `coverage.gap.no`（9 语，可点开「Why」） | NLOD 2.0 署名 + 截止日 + 「处方链数据服务、只有活动条目、无注册号」 |
| 数据包 | `datapackage.json` → `sources[dmp_fest].attribution` | 英文原句逐字；另有 `license`（DB `source.license`）、`license_url`、`data_as_of=2026-11-10` |
| 其它 | 覆盖页「数据截止」列、`data/sources.json` | 来自 DB `source.data_as_of`，构建期自动取 |

**口径禁用词核对**：`site/build.py` 新增文案里没有「注册库全量 / register of all medicines」的正向表述；
FEST 一律写成「处方链数据服务（prescription-chain data service）」并紧跟「不是注册库全量（not the full register）」。

## 5 命令与数字

> 环境：`$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'`，仓库根执行。

```powershell
# 1) 注册表
& $py lib/markets.py --check
& $py -m unittest tests.test_markets_registry -v

# 2) i18n 门禁
& $py deploy/i18n_check.py

# 3) 结构自验构建（**必须显式 SITE_OUT**，不写 site/dist）
$env:SITE_OUT = '.tmp/frontend-no'; & $py site/build.py      # 等到 == done ==

# 4) 产物自验（脚本见 §6）
& $py .tmp/frontend-no-verify.py .tmp/frontend-no

# 5) 首屏守卫：改前（v1.0.0 产物）/ 改后
& $py deploy/first_screen_check.py --dist .tmp/v101-after2 --viewports 390x844,768x1024,1440x900 `
    --json .tmp/frontend-no-before/first-screen-before.json --shots .tmp/frontend-no-before/shots
& $py deploy/first_screen_check.py --dist .tmp/frontend-no --viewports 390x844,768x1024,1440x900 `
    --json .tmp/frontend-no/first-screen-after.json --shots .tmp/frontend-no/shots
```

| 项 | 改前 | 改后 | 说明 |
|---|---|---|---|
| 注册表市场数 | 16（15 国 + EU） | 17（16 国 + EU） | `lib/markets.py --check` |
| `tests/test_markets_registry` | 58 tests OK | 59 tests OK | 新增 `test_no_market_row` |
| `deploy/i18n_check.py` | FAIL 0 | FAIL 0 | 运行期字典 707 → 710 键 × 9 语（静态字典 684 不变；构建日志 `710 keys × 9 语言`） |
| 首页 `<option>`（每处） | 15（无 MY、无 NO） | 17（含 MY、NO） | 两处下拉同源 |
| 构建产物 | —（本次不写 site/dist） | **158,835 文件 / 1,563.2 MB**，构建 **500 s（8.3 min）** | `.tmp/frontend-no` |
| `core.json` | — | `44.8（gzip 10.1）` MB raw | 构建日志 |
| 覆盖页 NO 行 | 无 | **8,985 产品 / 映射 99.6%（8,949/8,985）/ 规格 96.9%（8,709/8,985）** | DB 现查（coverage 页同口径） |
| sitemap | 79,894 URL | **79,894 URL** | 未变（无新增市场页面路由） |
| 0 字节文件 | — | **0** | 产物全量扫描 |

## 6 自验明细

### 6.1 首屏守卫（`deploy/first_screen_check.py`，3 视口 × 6 页型 = 18 次扫描）

改前基线：**`site/dist`（当前生产产物 v1.0.1，2026-11-20 构建，157,122 文件 / 1,467 MB）**；
另在 `.tmp/v101-after2`（v1.0.0 产物）上跑过一次，18 组数字与生产产物一致，故以 `site/dist` 为准。
改后：`.tmp/frontend-no`（本次构建）。

| 页面 | 视口 | 改前 AFCR / 条目 / chrome | 改后 AFCR / 条目 / chrome | 判定 |
|---|---|---|---|---|
| home | 390x844 | 0.93 / 0.0 / 0.14 | 0.93 / 0.0 / 0.14（同改前） | ok | |
| home | 768x1024 | 1.01 / 9.0 / 0.11 | 1.01 / 9.0 / 0.11（同改前） | ok | |
| home | 1440x900 | 1.00 / 9.0 / 0.07 | 1.00 / 9.0 / 0.07（同改前） | ok | |
| coverage | 390x844 | 0.79 / 3.5 / 0.27 | 0.79 / 3.5 / 0.27（同改前） | 未达 items 5（改前既有） | 改前即未达 items 5（历史基线） |
| coverage | 768x1024 | 0.91 / 8.5 / 0.19 | 0.91 / 8.5 / 0.19（同改前） | ok | |
| coverage | 1440x900 | 0.90 / 7.0 / 0.14 | 0.90 / 7.0 / 0.14（同改前） | ok | |
| drug / results / name / atc | 3 档 | 见 before JSON | 全部与改前同值（仅 results@1440 的 <14px 由 23% → 24%） | |

改前汇总：18 次扫描 / 2 组未达（`drug@1440` items 4.5、`coverage@390` items 3.5）/ 不稳定 0 / baseline 退化 0。
改后汇总：18 次扫描、2 组未达（同一组：drug@1440 items 4.5、coverage@390 items 3.5）、不稳定 0、疑似 0、baseline 退化 0（124.2s；改前 123.8s）

结论：**无回归**：18 组里 17 组逐项与改前同值，1 组只有 <14px 占比 1 个百分点的差异；2 项未达是改前既有（v1.0.1 生产产物同值），与 NO 无关

### 6.2 九语抽查（每语 1 页）

| 语言 | 页面 | 检查 | 结果 |
|---|---|---|---|
| en | `/coverage.html` | NO 行 + `coverage.gap.no` + 母语缺口 `nb, no` | PASS（NO 行 + `coverage.gap.no` + `nb, no` 状态） |
| es | `/es/coverage.html` | 同上（西语文案） | PASS（西语值已写入 `i18n.es.js`，副本含 NO 行） |
| zh | `/zh/coverage.html` | 同上（简体） | PASS（简体值「挪威 / 处方链数据服务」） |
| zh-Hant | `/zh-Hant/coverage.html` | 同上（繁体） | PASS（繁体值「挪威 / 處方鏈資料服務」） |
| fr | `/fr/coverage.html` | 同上（法语） | PASS（法语值「Norvège / chaîne de prescription」） |
| ko | `/ko/coverage.html` | 同上（韩语） | PASS（韩语值「노르웨이 / 처방 체인」） |
| ja | `/ja/coverage.html` | 同上（日语） | PASS（日语值「ノルウェー / 処方連鎖」） |
| cs | `/cs/coverage.html` | 同上（捷克语） | PASS（捷克语值「Norsko / předpisového řetězce」） |
| lv | `/lv/coverage.html` | 同上（拉脱维亚语） | PASS（拉脱维亚语值「Norvēģija / receptes ķēdes」） |

每语的 `assets/i18n.<lang>.js` 里 `home.no` / `coverage.gap.no` / `about.no_source` 均是该语言的真译文
（不是英文回落）；`<lang>/coverage.html`、`<lang>/about.html` 副本存在且含 NO 行/署名键。
逐条断言脚本 `.tmp/frontend-no-verify.py`：**112 项 PASS / 0 FAIL**（含「九语不是英文回落」与「旧口径不得出现」）。

### 6.3 三条挪威药名检索

| 查询 | 期望 | 结果 |
|---|---|---|
| ``Ibux`` | NO 候选集，含商品名/成分/规格 | NO 候选 5 组（Ibuprofen 200/400/600 mg 片、20/40 mg/mL 液、200/400 mg 胶囊、50 mg/g 外用），另有 MY 同名与 MX `CIBUX`（Trimebutine+Simethicone，标「严重碰撞」） |
| ``Pinex`` | 同上 | NO 候选 3 组（Acetaminophen 500 mg：片/粉/液）+ `Pinex Forte`（+Codeine，标「严重碰撞」） |
| ``Kvetiapin`（挪威语通用名）` | 同上 | NO 候选 3 组（Quetiapine 50–400 mg 片 ×50、25–300 mg 片 ×15、20 mg/mL 液，标「配方不同」），不返回单一答案 |

### 6.4 390 / 768 / 1440 首屏（截图 + DOM）

- 截图：`.tmp/frontend-no/shots/fs-home-390x844.png`、`fs-coverage-390x844.png`、`fs-home-768x1024.png`、
  `fs-coverage-768x1024.png`、`fs-home-1440x900.png`、`fs-coverage-1440x900.png`。
- DOM：`coverage.html` 里 `#market-NO` 行已渲染：8,985 条 / 99.6% / 96.9% / 数据截止 2026-11-10；同一行的可点开「Why」里同时是 NLOD 署名 + 处方链口径 + 「母语 nb, no 未覆盖」；`index.html` 两处 `<select>` 各 17 个 `<option>`（含 MY、NO）。

## 7 顺带修复（MY 筛选项缺失）

`site/build.py` 原来的首页 `#country` / `#src` 是**手写**的 15 个 `<option>`（含 FR，漏了 v0.18.0 上线的 MY），
顶部菜单则由注册表派生 —— 同一件事维护两份，MY 上线时漏改下拉框。本次把两处下拉改成
`_market_options_html()`（注册表 enabled 顺序，∪ 库里有数据的市场），
MY 与 NO 同时出现、FR 仍在；以后加市场不会再漏。改前 `index.html` 里 `value="MY"` 出现 0 次，改后 2 次。

## 8 缺口 / 未做

- **挪威语界面（nb/no）未接入**：本版只登记 `ui_language_gaps`，覆盖页显示「母语 nb, no 未覆盖」；
  新增界面语言是独立项目（`data/languages.json` + 全键表 + 路由 + hreflang）。
- **没有注册号 / 没有显式在售状态**：FEST 源里 `Status` 只有一个值（`Aktiv oppføring`），本站的
  `discontinued` / `withdrawn` 是由**包装级下线标记派生**（DB 现查 active 8,778 / discontinued 175 /
  withdrawn 32），不是源里的官方状态字段，页面文案已按这个口径写（`data/markets.json` 的 `notes`
  同步改成「源只有活动条目 + 派生」的写法，避免与 DB 实况自相矛盾）。
- `mobile/` 与 `render_dashboard.py` 的进度看板仍固定列 7 个市场（US/GB/ES/MX/AU/CN/CA + …），未含 NO；
  它们不是站点产物、不在本任务范围，留给后续。
- `docs/市场扩展接口.md` 的「现状硬编码清单」一节还写着旧状态（本任务未获 docs 写权限）。
- CHANGELOG / 版本号 / 发布：由 release（`task-3`）决定与执行，本报告不含发布结论。

## 9 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py lib/markets.py --check
& $py -m unittest tests.test_markets_registry -v
& $py deploy/i18n_check.py
$env:SITE_OUT = '.tmp/frontend-no'; & $py site/build.py
& $py .tmp/frontend-no-verify.py .tmp/frontend-no
& $py deploy/first_screen_check.py --dist .tmp/frontend-no --viewports 390x844,768x1024,1440x900 `
    --json .tmp/frontend-no/first-screen-after.json --shots .tmp/frontend-no/shots
```

产物与自验脚本都在 `.tmp/`（不入库）：`.tmp/frontend-no/`（本次构建）、`.tmp/frontend-no-before/`（改前基线）、
`.tmp/frontend-no-verify.py`（九语/署名/产物断言）。
