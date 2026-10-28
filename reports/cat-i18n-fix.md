# v0.8.2 大类四语显示修复报告（task-114）

> 任务：task-114（`site/build.py` 独占，构建 `.tmp/dist-cat-i18n`）。
> 用户反馈：中文首页「按大类浏览」16 个大类名仍是英文（Blood-pressure medicines 等），要求语言对应。
> 未改 `data/*`、tests、`site/dist`；构建：`SITE_OUT=.tmp/dist-cat-i18n`。

## 0. 结果

| 项 | 结果 |
|---|---|
| 首页 chips | 16 个大类 chips 改为**四语内联语言块**（en/es/zh/zh-Hant 各一个 `data-lang-block` + `data-lang-inline`），根 `/` 与 `/es/ /zh/ /zh-hant/` 副本都随界面语言切换（修复根页中文界面显示英文的问题） |
| /cat/* 页 | h1 四语块（已有）+ **英文原名副标题 `.cat-en`**；描述四语块；英文界面隐藏副标题（JS） |
| /atc.html | 14 个 ATC L1 + 16 个大类卡片四语内联块 + 英文原名副标题；标题/说明随语言 |
| ATC 类目页 | h1 名称四语块（L1/L2–L4 常见类）；无内置名的类目仍以 ATC 码为标题 + 本地化「待校订」提示，**无英文溢出** |
| 搜索解析条 | 大类查询的解析条使用当前语言大类名（已有 `cat.labels[LANG]`）；无回归 |
| 四语 | I18N **375 keys ×4 一致**；zh-Hant 繁体用词 |
| 构建 | exit 0；62,880 文件 / 463.8 MB；sitemap 62,720 不变 |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| `_home_cat_chips`：改为四语内联块（根页/副本一致随语言） | `_home_cat_chips` |
| `/cat/*` 英文副标题 `.cat-en` | `build_category_pages` |
| `/atc.html` 大类卡片英文副标题 `.cat-en` + 四语块保留 | `build_atc_index` |
| 英文界面隐藏 `.cat-en`（避免重复） | `BILINGUAL_JS` render |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-cat-i18n'; & $py -X utf8 site/build.py   # exit 0
& $node --check .tmp\dist-cat-i18n\assets\app.js                      # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-cat-i18n' '<repo>'  # 15/15 PASS
# 临时 http.server 8812 + headless.mjs → ALL CHECKS PASSED
```

- **静态 15/15**：根首页 chips 含 en/es/zh/zh-Hant 语言块（不再固定英文）；zh 首页 chips；cat 页 h1 四语块 + `.cat-en` + 描述四语；atc.html 大类卡四语块 + 英文副标题；ATC C08 h1 四语块；I18N 375×4 一致；无 0 字节。
- **Headless（Chrome CDP）**：zh/zh-Hant/es/en 首页首个 chip 分别为 降压药/降壓藥/西语/英文；cat 页 zh h1「降压药」+ 英文副标题可见、zh-Hant「降壓藥」、es 西语；atc.html zh/es 显示本地化大类；ATC C08 zh h1「钙通道阻滞剂」、zh-Hant「鈣通道阻滯劑」、es「Bloqueantes de los canales de calcio」，均无英文溢出。

## 3. 风险

1. 大类名是编辑/AI 译名（页面上仍有「不是官方译名，ATC 码为准」说明）；如需官方译名由 data 侧补。
2. 根页 chips 为四语内联块，页面体积略增（16 chips ×4 语言），可忽略。
3. 英文副标题在 JS 未执行时也显示（无 JS 时中文界面副标题可见，可接受）。
4. `/atc.html` 无内置名的类目仍以 ATC 码显示（L2–L4 仅 25 个常见类有编辑名，见 task-82 报告）。

## 4. 回滚

`git checkout -- site/build.py` 后重建；或仅回退 `_home_cat_chips`/`.cat-en`/ATC 卡片副标题改动。

## 5. 产物

- `.tmp/dist-cat-i18n/`（62,880 文件 / 463.8 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`（TEMP `cat-i18n-verify-20261028/`）。
- `reports/cat-i18n-fix.md`：本报告。
