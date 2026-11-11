# v0.11.3 更新日志四语补齐（release notes backfill）

> 日期：2026-11-12（北京时间）· 工位：page-slim · 任务：`task-36`
> 结论先行：`data/release_notes_i18n.json` 从 **43 版 / 174 条**补到 **56 版 / 239 条**，
> 每版 `zh / en / es / zh-Hant` 条数与 `CHANGELOG.md` **逐版一致**（0 条差异）；
> `deploy/i18n_check.py` 从 **FAIL 0 / WARN 4** → **FAIL 0 / WARN 2**（只剩既有的 `pseudo-suspect=2`，
> `release-backlog` 与 `release-backlog-incomplete` **清零**）；独立构建 `.tmp/v0113-notes-build`
> 到 `== done ==`，`whats-new.html` **56 个版本、0 个「译文待补」**。
> 唯一遗留：`site/build.py` 的 `build_whats_new()` 只渲染 zh/en/es 三块，zh-Hant 正文块尚未渲染
> （数据已齐，见 §6）。

---

## 1. 缺口清单（改动前实测）

用与 `deploy/i18n_check.py:parse_changelog()` 相同的口径逐版对账（`.tmp/check_release_notes_detail.py`）：

| 缺口 | 明细 | 条目数 |
|---|---|---|
| A · 整段缺失 12 版 | `v0.8.3`、`v0.8.4`、`v0.9.0`–`v0.9.8`、`v0.10.0` | **57 条** |
| B · 24 个老版本缺 `zh-Hant` | `v0.5.5`–`v0.1.0`（zh/en/es 有、zh-Hant 空数组） | 89 条需生成 |
| C · v0.8.2 条数少 4 | notes 5 条 vs CHANGELOG 9 条；且原 5 条是压缩稿，不是原样抄 | +4 条 |
| D · v0.3.0 条数少 2 | notes 6 条 vs CHANGELOG 8 条（两个嵌套 `- ` 子条目被合并进父条目） | +2 条 |
| E · v0.1.0 条数多 3 | notes 16 条 vs CHANGELOG 13 条（前导段 + 市场表 + 「功能」标题被拆成独立条目） | 合并为 13 条 |

改动前 `deploy/i18n_check.py`：`FAIL 0 / WARN 4`，其中
`release-backlog` = 12 版 / 57 条，`release-backlog-incomplete` = 25 版（含 v0.8.2 条数不符）。

## 2. 做法（CHANGELOG 为唯一真相源）

1. **解析口径**：复用 `deploy/i18n_check.py:parse_changelog()` 的版本/条目计数（`^## v… — YYYY-MM-DD`
   起节，`^\s*-\s+\S` 计条目），保证「补齐后条目数 = 检查器眼里的 CHANGELOG 条目数」。
2. **zh 原样抄**：逐条抄 CHANGELOG，续行合并进同一条（与现有 JSON 风格一致：条目内含 `\n  ` 缩进）；
   嵌套子条目按检查器口径另起一条（只影响 v0.3.0，见 §3.2）。**没有改一个中文字**。
3. **en / es**：AI 机器翻译，措辞沿用现有条目风格（`**粗体标题**：具体数字/文件名`）；
   `_meta.translations` 与每版 `machine_translated: true` 保持原说明不变。
4. **zh-Hant**：**不手写**，调用项目现有管线
   `.tmp/zh-hant/build_hant.py`（OpenCC STPhrases → TWPhrases → STCharacters → TWVariants +
   自建台湾 IT/药事术语表 `TW_TERMS`），逐条转换；词典缓存 `.tmp/zh-hant/*.txt`。
5. **v0.11.3 插队先落盘**：release 最新版缺译文会触发 `release-latest-missing` FAIL、卡住 site-ui
   的最终构建，所以先单独写入 v0.11.3 五条（四语），确认 `FAIL 0` 后再做历史补齐。
6. **`_meta` 重算**：`versions=56`、`items=239`（= 各版 zh 条数之和），`generated_at` 更新；
   `note` / `translations` / `authoritative_language` / `provisional_versions` 原样保留。
7. 版本顺序按 CHANGELOG（最新在上）重排；`v0.11.0` 原先被追加在 JSON 末尾，已归位。

## 3. 补齐明细

### 3.1 新增 12 个历史版本（57 条，四语）

| 版本 | 条目 | 版本 | 条目 |
|---|---:|---|---:|
| v0.10.0 | 4 | v0.9.4 | 3 |
| v0.9.8 | 5 | v0.9.3 | 5 |
| v0.9.7 | 4 | v0.9.2 | 5 |
| v0.9.6 | 4 | v0.9.1 | 5 |
| v0.9.5 | 5 | v0.9.0 | 6 |
| v0.8.4 | 7 | v0.8.3 | 4 |

每条都写了 zh（原文）、en、es（机翻）、zh-Hant（生成器）。

### 3.2 三个条数不符的版本

| 版本 | 处理 | 说明 |
|---|---|---|
| v0.8.2 | 按 CHANGELOG **9 条重写**（原 5 条是压缩稿，不是原文）；补 4 条：ATC 成分名中文化、矩阵列错位修复、What's new 译文补齐、站点文件数 | zh 全部改成 CHANGELOG 原文；en/es 重写；zh-Hant 重新生成 |
| v0.3.0 | 把合并的父条目**拆成 3 条**（父条目 + `TGA CMI 目录` + `listed OTC 人工种子`）→ 6+2=8 条；其余 5 条原文不动，en/es 按标记切分 | 与检查器 `^\s*-\s+\S` 口径一致 |
| v0.1.0 | 16 → **13 条**：前导段+市场表+「功能」标题并入第 1 条功能条目；「已知缺口」标题并入第 1 条缺口条目；其余 12 条原文不动 | 文本无删减，只做分组对齐 |

### 3.3 zh-Hant

- **38 个版本**动过 `zh-Hant`：37 个由管线补/重生成（12 个新增历史版本 + 24 个老版本，
  其中 `v0.3.0` / `v0.1.0` 因条数重排一并重生成，外加 `v0.8.2` 因条目重写 5 → 9 条），
  另 `v0.11.2` 的手工版重生成修残留简体字；
- 逐条校验（`.tmp/validate_release_notes.py`）：`zh-Hant` 残留「只可能出现在简体侧」的字符 = **0 版**；
  台湾用语抽样命中：搜尋 42、廠商 22、規格 24、劑型 21、載入 12、連結 14、預設 12、發布 11；大陆用语残留 0。

## 4. 校验结果

| 检查 | 改动前 | 改动后 |
|---|---|---|
| JSON 版本数 | 43 | **56**（55 历史 + v0.11.3） |
| JSON 条目数（zh / en / es / zh-Hant 各自） | 174 / 174 / 174 / **79**（24 版 zh-Hant 为空） | **239 / 239 / 239 / 239** |
| 与 CHANGELOG 条数不一致的版本 | 3（v0.8.2、v0.3.0、v0.1.0）+ 12 缺失 | **0** |
| `i18n_check` | **FAIL 0 / WARN 4** | **FAIL 0 / WARN 2**（只剩既有 `pseudo-suspect=2`） |
| `release-backlog` | WARN（12 版 / 57 条） | **消失** |
| `release-backlog-incomplete` | WARN（25 版） | **消失** |
| `release-latest-missing` | 曾 FAIL（v0.11.3 缺四语，卡住 site-ui 构建） | **消失** |

```powershell
& $py deploy/i18n_check.py
# release notes: CHANGELOG 56 版 / json 56 版，最新 v0.11.3 四语齐；缺 0 版（0 条待译）
# FAIL 0 / WARN 2 / INFO 21 —— WARN 只剩 pseudo-suspect=2（与 release notes 无关，既有）
```

## 5. whats-new 页面前后对比（独立目录构建）

构建（**没有写 `site/dist`**，也没碰 site-ui 的 `.tmp/v0113-build`）：

```powershell
$env:SITE_OUT='.tmp/v0113-notes-build'
& $py site/build.py        # == done ==
```

| 指标 | 改动前（已发布的 `site/dist/whats-new.html`） | 改动后（`.tmp/v0113-notes-build/whats-new.html`） |
|---|---|---|
| 版本 section 数 | 55 | **56**（含 v0.11.3） |
| 「译文待补」提示（`release-pending`） | **12 处** | **0** |
| 每版语言块 | 43 版有 zh/en/es 三块；12 版只有中文原文 + 待补提示 | **56 版 × 3 块（zh/en/es）** |
| 页面体积 | 185,975 B | 225,097 B |
| 构建总量 | —（线上 121,450 文件 / 903.6 MB） | 121,450 文件 / 906.2 MB（906,190,882 B）/ 121,239 HTML；`core.json` 42.8 MB |
| 版本首尾 | v0.11.2 … v0.1.0 | **v0.11.3 … v0.1.0** |

构建日志 `== done ==`：drug 12,431 / name 77,147 / combo 6,790 / maker 15,213 / confused 22 /
warnings 40 / sitemap 63,685 URL（此构建同时包含 site-ui 的在途改动，总量数字不单独归因于本次 JSON）。

抽查完 `whats-new.html` 后已按 Lead 建议删除 `.tmp/v0113-notes-build`（避免与 site-ui 的
`.tmp/v0113-build` 抢磁盘/干扰），只保留页面快照 `.tmp/notes-whatsnew-after.html`（225,097 B）作证据。

## 6. 遗留：zh-Hant 正文块尚未渲染（需 site-ui 一行改动）

`site/build.py:7607` 的 `build_whats_new()` 目前只渲染三个块：

```python
for lang in ("zh", "en", "es"):
    items = item.get(lang) or item.get("zh") or []
```

而页面 JS（`build.py:12620`）只显示 `data-lang-block === window.LANG` 的块 →
**zh-Hant 界面下 56 个版本的正文会全部隐藏**（改动前同样存在）。数据侧已齐（239 条 zh-Hant），
site-ui 只需改成：

```python
for lang in ("zh", "en", "es", "zh-Hant"):
    items = item.get(lang) or item.get("zh") or []
```

再构建一次即可满足「55/56 版四语齐全」的页面级承诺。**本工位未改 `site/build.py`**（任务禁区）。

## 7. 改动文件

| 文件 | 说明 |
|---|---|
| `data/release_notes_i18n.json` | 唯一的数据改动：43 → 56 版、174 → 239 条（四语），`_meta` 重算 |
| `reports/2026-11-13-release-notes-backfill.md` | 本报告 |
| `.tmp/insert_release_notes_v0113.py` | 插队写 v0.11.3（四语） |
| `.tmp/backfill_release_notes_20261113.py` | 历史补齐 + zh-Hant 生成 + `_meta` 重算 |
| `.tmp/validate_release_notes.py` | 版本/条数/空值/简体残留校验 |
| `.tmp/check_release_notes_detail.py` | 改动前逐版对账 |
| `.tmp/release_notes_i18n.before-v0113.json` | 改动前备份（43 版 / 174 条） |
| `.tmp/notes-whatsnew-after.html` | 独立构建的 `whats-new.html` 快照（构建目录已删，留证据） |

**未改**：`CHANGELOG.md`、`site/build.py`、`site/dist`、`data/drugs.db`；**未 commit / 未发布**。
构建产物在 `.tmp/v0113-notes-build/`（`site/dist` 未写）。

## 8. 风险与说明

1. **机翻声明**：en/es 仍是 AI 机器翻译（`_meta` 原说明），whats-new 页已有「机翻、中文原文为准」提示；
   没有改公开口径。
2. **zh-Hant 待人工复核**：生成器输出「台湾用语优先」，专有名词/许可与法规表述建议人工过一遍
   （与 `data/i18n_zh_hant.json` 同一口径）。
3. **v0.8.2 / v0.3.0 / v0.1.0 的条目重排**：为对齐检查器口径做了拆分/合并（文本无删减），
   与旧 JSON 的条目边界不同；页面显示内容等价或更全。
4. **构建数字**：`.tmp/v0113-notes-build` 包含 site-ui 同期的 build.py 改动，总量变化不全是本次
   JSON 引起；发布前以最终一次构建为准。
5. **zh-Hant 块**：见 §6，需 site-ui 配合；不影响 i18n_check（检查的是 JSON 键集，不是页面渲染）。
