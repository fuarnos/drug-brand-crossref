# 国家/地区措辞合规（静默修复）— 2026-10-29

> 性质：**P0 合规静默修复**。不发新版本、不打 tag、不写 `CHANGELOG.md` / What's new / Release notes；发布由发布经理做**静默 publish**，发布侧数字由 index-p1 回填。
> 建站侧改动：`site/build.py`（四语 i18n + 模板兜底文案）+ `data/i18n_zh_hant.json`（zh-Hant 整段覆盖 key 的同步，见 §4）。未改数据库、未改 `data/*.csv`、未动品牌名/具体国家名/数据。
> 依据：用户 2026-10-29 截图「首页市场下拉首项『全部国家』把台湾与主权国家并列」；`.tmp/cat2-plan` 外的本轮口头范围。

## 0. 结论

- 首页市场下拉首项、结果表列标题、成分页矩阵列标题、矩阵筛选器「国家」、结果顶部「各国叫法」、About 覆盖表头、覆盖提示句，已统一为**国家/地区**口径（en `countries and regions` / es `países y regiones` / zh `国家/地区` / zh-Hant `國家/地區`）。
- 全量构建到 `== done ==`：`site/dist` **62,217 文件 / 472,531,095 B（≈472.5 MB，450.6 MiB）/ sitemap 62,057 URL**；页脚版本 **v0.8.4**（CHANGELOG 顶部仍是 v0.8.4，本轮不发版，属预期）。
- 四语 i18n 实测：从 `site/dist/assets/i18n.js` 反解 388 键字典，市场清单相关 key 全部命中新措辞；单值残留检查 `bad values: []`。
- 具体国家名（美国/中国/台湾…）、品牌名、数据一律未动；正文泛指句（如「同一成分在不同国家可能不同」）保留；TW 旗标按 Lead 决定**本轮不动**（只改文字）。
- 已知缺口：zh-Hant 的 About「数据来源与覆盖」表格表头仍是「市場」（该整段 HTML 由 `data/i18n_zh_hant.json` 覆盖，非「國家」，不影响下拉/结果/矩阵）。建议下次构建顺带改为「國家/地區」，本轮为避免发布快照与源码不一致不再改。

## 1. 改动清单 before → after

### 1.1 市场清单 / 列标题 / 筛选器（核心）

| key | before | after |
|---|---|---|
| `home.all` en | All countries | **All countries and regions** |
| `home.all` es | Todos los países | **Todos los países y regiones** |
| `home.all` zh | 全部国家 | **全部国家和地区** |
| `home.all` zh-Hant | 全部國家（JSON） | **全部國家和地區** |
| `res.col_country` en | Countries | **Countries & regions** |
| `res.col_country` es | Países | **Países y regiones** |
| `res.col_country` zh | 国家 | **国家/地区** |
| `res.col_country` zh-Hant | 國家（JSON） | **國家/地區** |
| `name.countries` en | Countries | **Countries & regions** |
| `name.countries` es | Países | **Países y regiones** |
| `name.countries` zh | 国家 | **国家/地区** |
| `name.countries` zh-Hant | 國家（JSON） | **國家/地區** |
| `matrix.country` en | Countries | **Countries & regions** |
| `matrix.country` es | Países | **Países y regiones** |
| `matrix.country` zh | 国家 | **国家/地区** |
| `matrix.country` zh-Hant | 國家 | **國家/地區** |
| `u2.title` en | Names by country | **Names by country/region** |
| `u2.title` es | Nombres por país | **Nombres por país/región** |
| `u2.title` zh | 各国叫法 | **国家/地区叫法** |
| `u2.title` zh-Hant | 各國叫法 | **國家/地區叫法** |

### 1.2 入口标签 / 提示 / 计数语境

| key | before | after |
|---|---|---|
| `home.country_label` en | …called in: | **…called in each country/region:** |
| `home.country_label` es | …en: | **…en cada país/región:** |
| `home.country_label` zh | 看这个药在哪个国家叫什么： | **看这个药在哪个国家/地区叫什么：** |
| `home.country_label` zh-Hant | 看這個藥在哪個國家叫什麼： | **看這個藥在哪個國家/地區叫什麼：** |
| `home.coverage` en | Coverage: | **Coverage (countries and regions):** |
| `home.coverage` es | Cobertura: | **Cobertura (países y regiones):** |
| `home.coverage` zh | 当前覆盖： | **当前覆盖（国家和地区）：** |
| `home.coverage` zh-Hant | 當前覆蓋： | **目前涵蓋（國家和地區）：** |
| `country.change` | Change country / Cambiar país / 换国家 / 換國家 | **Change country/region / Cambiar país/región / 换国家/地区 / 換國家/地區** |
| `country.missing`、`country.missing_note` | 市场/该国 | **国家/地区**口径（四语） |
| `res.notin` | 所选国家 / No incluido en este país | **所选国家/地区 / No incluido en este país/región** |
| `u1.step3`、`u1.step3_hint` | Switch to a country / 切国家看叫法 | **Switch to a country/region / 切国家/地区看叫法**（四语） |
| `u2.hint`、`u2.multi` | click a country / switch country | **country/region**（四语） |
| `matrix.brand_note` | Each country column | **Each country/region column**（四语） |
| About 覆盖表头 en/es/zh | Market / Mercado / 市场 | **Country / region / País / región / 国家/地区**（zh-Hant 见 §4） |
| 首页 HTML 兜底（无 JS 时） | All countries / Switch to a country | **All countries and regions / Switch to a country/region** |

### 1.3 文件与规模

```
 site/build.py              | 131 +++++++++++++++++++++----------------------
 data/i18n_zh_hant.json     |  18 +++++-----
 2 files changed, 75 insertions(+), 74 deletions(-)
```

- 未改 `CHANGELOG.md`、未写 What's new、未改 `site/dist` 生成物本身（构建生成）。
- `data/i18n_zh_hant.json` 是 zh-Hant 的整段覆盖字典：`home.all` / `res.col_country` / `name.countries` / `home.coverage` / `home.country_label` / `country.change` / `country.missing*` / `res.notin` 若只改 build.py 的 zh，会被 JSON 覆盖回旧值，因此同步改了该 JSON（仅 i18n 文案，非 DB/数据源）。

## 2. 四语实测（构建后反解）

来源：`site/dist/assets/i18n.js` 的 `window.I18N`（`.tmp/cat2/wording_check.py` 反解，结果 `.tmp/cat2/wording-check.json`）。

| key | en | es | zh | zh-Hant |
|---|---|---|---|---|
| home.all | All countries and regions | Todos los países y regiones | 全部国家和地区 | 全部國家和地區 |
| res.col_country | Countries & regions | Países y regiones | 国家/地区 | 國家/地區 |
| name.countries | Countries & regions | Países y regiones | 国家/地区 | 國家/地區 |
| matrix.country | Countries & regions | Países y regiones | 国家/地区 | 國家/地區 |
| u2.title | Names by country/region | Nombres por país/región | 国家/地区叫法 | 國家/地區叫法 |
| home.coverage | Coverage (countries and regions): | Cobertura (países y regiones): | 当前覆盖（国家和地区）： | 目前涵蓋（國家和地區）： |
| home.country_label | …in each country/region: | …en cada país/región: | …在哪个国家/地区叫什么： | …在哪個國家/地區叫什麼： |
| country.change | Change country/region | Cambiar país/región | 换国家/地区 | 換國家/地區 |

- 单值残留检查（只看市场清单 key 的取值，不做全文泛匹配）：`bad values: []`。
- 首页四份静态副本（`/index.html`、`/zh/`、`/zh-hant/`、`/es/`）下拉首项的无 JS 兜底均为 `All countries and regions`；运行时由 i18n.js 替换为对应语言。
- About 表头：en/es/zh 实测命中 `Country / region`、`País / región`、`国家/地区`；zh-Hant 见 §4。
- 页脚：`v0.8.4 · 2026-10-29`（构建从 CHANGELOG 现读，未出现 v0.8.5）。

## 3. 构建与验证命令（可复核）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 语法 / JSON 校验
& $py -m py_compile site/build.py
& $py -c "import json; json.load(open(r'data/i18n_zh_hant.json', encoding='utf-8')); print('json OK')"

# 2) 全量构建（独占；输出到日志，等 == done ==）
$env:PYTHONIOENCODING='utf-8'
& $py site/build.py *> .tmp/build-v085.log
Select-String -Path .tmp/build-v085.log -Pattern '== done =='

# 3) dist 规模 / sitemap / 页脚版本
$files = Get-ChildItem site/dist -Recurse -File
($files | Measure-Object Length -Sum).Sum
(Select-String -Path site/dist/sitemap.xml -Pattern '<loc>' -AllMatches).Matches.Count
Select-String -Path site/dist/index.html -Pattern 'v0\.8\.[0-9]'

# 4) 四语 key 反解检查（脚本见 .tmp/cat2/wording_check.py）
& $py .tmp/cat2/wording_check.py
Get-Content .tmp/cat2/wording-check.json -Encoding utf8

# 5) 市场清单单值残留（应无输出/0）
Select-String -Path site/build.py,data/i18n_zh_hant.json `
  -Pattern 'All countries"|Todos los países"|全部国家"|全部國家"|"Countries"|"Países"' -Encoding utf8
```

本轮实跑结果：

- 构建日志：`.tmp/build-v085.log`，最后输出 `== done ==`；构建完成时间 **2026-10-29 08:04（北京）/ 17:04（本机 PDT）**。
- `site/dist`：**62,217 文件 / 472,531,095 B（≈472.5 MB；450.6 MiB）**；`sitemap.xml` **62,057 URL**。
- 变更前后 dist 文件数、sitemap 数不变；体积 +874 B（仅文案）。
- 关键页面存在性：`index.html`、`about.html`、`atc.html`、`data/categories.json`、`zh/index.html`、`zh-hant/index.html`、`es/index.html`、`zh|zh-hant|es/about.html` 均存在。

## 4. 未做 / 限制（如实记录）

1. **zh-Hant About 表头仍是「市場」**：`about.sources` 整段 HTML 由 `data/i18n_zh_hant.json` 覆盖，未同步「國家/地區」；它是中性词「市场」而非「国家」，不影响本次用户截图位置（首页下拉/结果列/矩阵筛选）。为避免发布中改源码导致快照不一致，本轮**不改**，留待下次构建。
2. **TW 旗标未动**：按 Lead 指示本轮只改文字；task-4 描述里的「TW 换中性标记」不在本轮范围。
3. **未做 headless 截图/点击回归**：发布经理正在静默 publish，避免并发；本轮用「静态 HTML 兜底 + 构建后 i18n 字典反解 + 关键文件存在性」验证，Lead 已完成四语抽查。
4. 未运行 `deploy/publish.ps1`（发布经理独占）；未跑 `db/check_data.py`（未改 DB）。
5. 正文泛指句按范围保留，例如 `drug.notice` 的「同一成分在不同国家可能用完全不同的商品名」、`name.severe`、meta description 的 `across countries`；这些不是市场清单/列标题，不在本次合规口径内。

## 5. 验证结论一句话

首页下拉首项、结果/矩阵列标题、矩阵筛选器、结果「各国叫法」、About 覆盖表头与覆盖提示已完成四语「国家/地区」口径，构建 `== done ==`、页脚 v0.8.4、dist 与 sitemap 无回归；zh-Hant About 表头「市場」与 TW 旗标为明确留待项。

## 6. 发布侧记录（index-p1 回填，2026-10-29）

- 发布入口：`powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1 -Message "compliance: country/region wording (no release note)"`
  （增量；本机直接 `& .\deploy\publish.ps1` 会被 PowerShell ExecutionPolicy 拒绝，需 `-File` + `-ExecutionPolicy Bypass`，与 `发布网站.cmd` 一致）
- gh-pages：`b2123de77f03185da2c70219e1c1bb956321b52b` → **`9d2ec4c623c6a9bdf113c4e1682e35a0c8dd94cc`**
- 提交统计：**62,061 files changed，+186,541 / −186,541**（整站重写：文案内联在 HTML 与 `assets/i18n.js`）
- 增量包：**12.48 MiB（13,086,429 B）**，全量树 450.6 MiB（≈472.5 MB 十进制）→ **≈2.8%**
- 发布耗时：**595.1 s（≈9 分 55 秒）**；Pages build `9d2ec4c6 built`；首页 `200 OK (version v0.8.4)`
- smoke：`deploy/verify_live.py --expect-version v0.8.4` → **31/31 通过，0 failures，0 warnings**（live v0.8.4；当前脚本共 31 项检查）
- 线上抽查（publish 之后实拉）：
  - 四语首页下拉静态兜底均为 **All countries and regions**（HTTP 200；页脚 v0.8.4）
  - 线上 `assets/i18n.js`：`home.all` = en **All countries and regions** / es **Todos los países y regiones** / zh **全部国家和地区** / zh-Hant **全部國家和地區**；无单独「全部国家」单值
  - `home.coverage` 四语已更新（…Coverage (countries and regions): / …Cobertura (países y regiones): / …当前覆盖（国家和地区）： / …目前涵蓋（國家和地區）：）
  - `matrix.country`、`res.col_country`、`name.countries` 四语 = Countries & regions / Países y regiones / 国家/地区 / 國家/地區
  - About 静态表头 >Country / region<；四语页脚/whats-new 顶部仍 v0.8.4
- 未发版、未打 tag、未发 GitHub Release、未新增 What's new 条目、`CHANGELOG.md` 保持 v0.8.4。
