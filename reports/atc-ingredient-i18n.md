# v0.8.2 ATC/大类/组合页成分名四语修复报告（task-120）

> 任务：task-120（`site/build.py` 独占，构建 `.tmp/dist-atc-i18n`）。
> 用户反馈：中文界面 ATC 大类页「该类别下的活性成分」全是英文（Acebutolol/Aliskiren/Amlodipine Besylate…）。
> 未改 `data/*`、tests、`site/dist`；构建：`SITE_OUT=.tmp/dist-atc-i18n`。

## 0. 结果

| 项 | 结果 |
|---|---|
| ATC 类目页成分列表 | 每个成分渲染**紧凑多语标记** `data-n-en/zh/zhh/es`（`bilingual.js` 按界面语言替换）：zh 优先 `inn_zh`，无中文名 → 英文 + 「暂无中文名」；zh-Hant 优先 zh-Hant 译名（数据暂无）→ 英文+「暫無中文名」；es 优先 es 译名（640 条）→ 否则英文；en 原名 |
| /cat/* 页面 | 成分列表同样多语（中文优先/暂无中文名提示）；与已有相关 ATC 类目四语名并列 |
| /atc.html | 大类/ATC L1 入口保持四语（task-114），不受影响 |
| 组合页 /combo/* | 成分名改用同一多语机制（中文优先） |
| 搜索/解析条 | `ingredientLabel()` 优先 `window.BILINGUAL_TERMS` 当前语言译名（bilingual.js 暴露），zh 仍走既有 `xz` 中文名；品牌名仍不翻译（政策，不是 bug） |
| 排序 | 成分列表**有中文名的排前**（中文用户优先看到可读名），其余按 en；避免前 60 个全是无中文名成分 |
| 验收 | `node --check` 0；静态 **14/14**；headless 全通过（zh ATC 成分显示中文、zh-Hant/es 回退非空、cat 页 zh 中文、首页/atc.html 大类中文） |
| 构建 | exit 0；62,880 文件 / **469.9 MB**（比 463.8 MB +6.1 MB：多语属性比四个 lang-block 省体积）；sitemap 62,720 不变 |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| `_sub_name_spans(en, zh, sid)`：紧凑多语属性（es/zh-Hant 译名来自 terms，中文用 inn_zh） | ATC 构建器前 |
| 成分列表使用多语标记 + 有中文名排序优先 + `.atcmembers` 类 | `_atc_members_html` |
| 组合页成分列表改用同一机制 | `build_combo_pages` |
| `BILINGUAL_TRANS` 全局保存 terms（build_terms_json 生成） | build_terms_json |
| `renderNames()`：ATC/cat/combo 静态页按 LANG 渲染成分名（无译名提示），i18n apply 后再次调用 | BILINGUAL_JS |
| `window.renderBilingualNames` 暴露并在 i18n.js apply 末尾调用（修复 defer 早于 ?lang 解析） | BILINGUAL_JS / i18n.js apply |
| `ingredientLabel` 使用 `window.BILINGUAL_TERMS` 译名（搜索/结果/组合同类） | APP_JS |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-atc-i18n'; & $py -X utf8 site/build.py   # exit 0, 469.9 MB
& $node --check .tmp\dist-atc-i18n\assets\app.js / bilingual.js / i18n.js  # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-atc-i18n' '<repo>'  # 14/14 PASS
# 临时 http.server 8813 + headless.mjs → ALL CHECKS PASSED
```

- **静态 14/14**：ATC C08 成分带 `data-n-*`（≥8），zh 值含中文（氨氯地平），存在无中文名成分（`data-n-zh=""`）；cat 页多语标记 + 中文；组合页多语标记；atc.html 大类中文；app.js 用 BILINGUAL_TERMS；bilingual.js 暴露 terms；I18N 无 @@；无 0 字节。
- **Headless**：zh ATC C08 成分列表显示中文名（如 尼索地平/尼群地平 等）；zh-Hant 回退非空（含「暫無中文名」）；es 回退非空；cat 页 zh 成分中文；首页 chips 与 atc.html 中文大类正常。
- **说明**：DB 中部分成分 `inn_en` 本身为中文（CN-only 记录），ata-n-en 原样显示；这是数据侧命名，不是翻译 bug。

## 3. 风险 / 已知事项

1. **无中文名成分**：显示英文 + 「暂无中文名」；如要补中文名由 data 侧补 `inn_zh`/译名后重建。
2. **zh-Hant 无成分译名**（`name_zh_hant` 0 条）：回退英文+「暫無中文名」；task-99 已记录同风险。
3. **es 译名 640 条**：无 es 译名的成分显示英文（或数据中原本中文的 en 值）。
4. **品牌名不翻译**：按政策保留市场注册名，不是 bug。
5. **体积**：紧凑 `data-n-*` 属性比四个 lang-block 省约 18 MB（初版 487.6 MB → 469.9 MB）；仍比 task-99 前 +6.1 MB。

## 4. 回滚

`git checkout -- site/build.py` 后重建；或仅回退 `_sub_name_spans`/`_atc_members_html`/组合页/`renderNames`/`ingredientLabel` 改动。

## 5. 产物

- `.tmp/dist-atc-i18n/`（62,880 文件 / 469.9 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`、`debug_lang.mjs`（TEMP `atc-i18n-verify-20261028/`）。
- `reports/atc-ingredient-i18n.md`：本报告。
