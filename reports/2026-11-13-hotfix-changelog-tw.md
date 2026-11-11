# 热修：公开更新日志移除「中国台湾」表述

- 日期：2026-11-13（北京时间）／本机 PT 2026-11-11
- 任务：**task-60**（用户 2026-11-12 要求：公开更新日志里不要写出「中国台湾」这条）
- 工位：alias-site
- 结论：**已改并推送**。`CHANGELOG.md` 的 v0.11.3 第 2 条 + `data/release_notes_i18n.json` 的 v0.11.3 四语第 2 条**整句删除台湾表述**，只保留页头竖排修复；条目数仍各 **5 条**；`i18n_check` **FAIL 0**。
- 提交：**`15683876054f015c299cafc01caeb65da7b294f8`**（`hotfix: 更新日志移除台湾表述（站点标签不变）`）→ 已 push main。
- **站点国家标签未动**（仍显示「中国台湾 / 中國台灣」）；未改 `site/build.py`、未 build/publish。

---

## 1. 改前 / 改后（逐条）

被删的句子（zh）：

```
**「中国台湾」**：中文与繁体界面的国家 / 地区标签统一为「中国台湾 / 中國台灣」
（英文 / 西语不变）；顺带修掉 1280–1440 宽度下页头「按类别」「中文」被挤成竖排的问题。
```

改后（zh，独立成一条，只保留页头竖排修复）：

```
**页头在 1280–1440 宽度下不再竖排**：修掉「按类别」「中文」被挤成竖排的问题。
```

四语对照（`data/release_notes_i18n.json` 的 `v0.11.3[1]`）：

| 语言 | 改后文本 |
|---|---|
| zh | **页头在 1280–1440 宽度下不再竖排**：修掉「按类别」「中文」被挤成竖排的问题。 |
| en | **Header no longer squeezes into vertical text at 1280–1440px**: fixes the "by category" and "中文" header items being squeezed into vertical text. |
| es | **La cabecera ya no se comprime en vertical a 1280–1440 px**: se corrige que «por categoría» y «中文» se compriman en vertical en la cabecera. |
| zh-Hant | **頁頭在 1280–1440 寬度下不再豎排**：修掉「按類別」「中文」被擠成豎排的問題。 |

被删句在各语里包含的表述（已全部清零）：`中国台湾` / `中國台灣` / `"Taiwan, China"` / `«Taiwán, China»`。

---

## 2. diff（git 口径）

```text
CHANGELOG.md                 | 2 +-
data/release_notes_i18n.json | 8 ++++----
2 files changed, 5 insertions(+), 5 deletions(-)
```

- `CHANGELOG.md`：v0.11.3 第 2 条 **1 删 1 加**（其它版本、其它条目未动）；
- `release_notes_i18n.json`：`v0.11.3` 的 **zh / en / es / zh-Hant 各 1 删 1 加**（其余 55 个版本未动）。

---

## 3. 自检

| 检查 | 结果 |
|---|---|
| `CHANGELOG.md` v0.11.3 条目数 | **5** |
| `release_notes_i18n.json` v0.11.3 条目数 | **zh 5 / en 5 / es 5 / zh-Hant 5** |
| v0.11.3 内 `中国台湾` / `中國台灣` / `Taiwan, China` / `Taiwán, China` 残留 | **0 / 0 / 0 / 0** |
| `& $py deploy/i18n_check.py` | **`FAIL 0 / WARN 5 / INFO 21`**（exit 0）；`release notes: CHANGELOG 56 版 / json 56 版，最新 v0.11.3 四语齐；缺 0 版` |
| WARN 5 条 | 均为既有项：es 同形词 `form.kit` / `form.gas` ×2 + `hardcoded` ×3（`site/build.py` 里的法国数据源文案，属 v0.11.4 FR 进行中内容，与本次改动无关） |

---

## 4. 站点标签未动（证据）

| 文件 | 现查 |
|---|---|
| `data/markets.json` | `中国台湾` ×**1**（TW 的 `name.zh`，原样保留） |
| `site/build.py` | `中国台湾` ×**3**、`中國台灣` ×**2**（I18N / ABOUT_I18N / UI_I18N，原样保留） |

→ 站点界面里的国家/地区标签**仍是「中国台湾 / 中國台灣」**，本次只动公开文案（CHANGELOG / release notes）。

---

## 5. 提交与影响面

| 项 | 值 |
|---|---|
| commit | **`15683876054f015c299cafc01caeb65da7b294f8`** |
| 提交信息 | `hotfix: 更新日志移除台湾表述（站点标签不变）` |
| 文件 | **2 files changed, +5 −5**（`CHANGELOG.md`、`data/release_notes_i18n.json`） |
| 推送 | `b13dce728..156838760  main -> main`；远端 `main` = `156838760`，本地/远端 0/0 |
| 未提交（按纪律） | `etl/markets/fr.py`、`data/markets.json`、`data/languages.json`、`db/*`、`site/build.py`、`tests/*` 等 **v0.11.4 WIP** 全部留在工作区 |

---

## 6. 已知缺口 / 后续

1. **线上仍是旧文案**：`https://drugcrossref.com/whats-new.html` 的 v0.11.3 一节仍含「中国台湾」那句——本热修只改仓库源文件，**要生效必须等下一次全量构建 + 双通道发布**（v0.11.4 或单独热发布，由 Lead 定）。
2. **`reports/metrics/goatcounter-*.json` 等未跟踪项**与本热修无关，未提交。
3. 本报告本身未提交（本任务只授权提交那 2 个文件）；如需入库，随下次 docs 提交一并带上。

---

## 7. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py deploy\i18n_check.py                      # FAIL 0
& .\tools\git\cmd\git.exe -c core.quotepath=false show --stat HEAD
& .\tools\git\cmd\git.exe -c core.quotepath=false diff HEAD~1 -- CHANGELOG.md data/release_notes_i18n.json
```
