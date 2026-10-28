# v0.6.5 英文/西语界面中文残留清理 + 首搜提示 实现报告

> 任务：task-74（`site/build.py` 独占）。用户反馈：英文首页仍有中文 logo 副标题、中文示例按钮、过时「~6 MB」首搜提示。
> 未跑 git/发布，未改 `site/dist`、`data/drugs.db`、`data/i18n_zh_hant.json` 或其他跟踪文件。
> 构建：`SITE_OUT=.tmp/dist-clean`。

## 0. 结果

| 项 | 结果 |
|---|---|
| Logo 中文副标题 | en / es / zh-Hant **隐藏**（`html:not([lang="zh"]) .logo-zh{display:none}`），仅 zh 显示；静态副本/客户端切换随 `html lang` 生效 |
| 首页示例 | 按页面语言渲染：en `Lipitor 20mg / Tylenol / Benadryl / Gaviscon`；es `Paracetamol 500mg / Ibuprofeno 600mg / Omeprazol 20mg / Loratadina 10mg`；zh 泰诺/两只青蛙；zh-Hant 泰諾/兩隻青蛙（U1 三步引导里的 Try 按钮同样本地化） |
| 首搜提示 | 四语改为「首次只加载一小片索引（~0.2 MB），完整索引后台补全」；zh-Hant 直接由 build.py 覆盖（`data/i18n_zh_hant.json` 里的旧 6 MB 文案不再生效） |
| 全站中文残留扫描 | en i18n 只剩 2 处**有意内容**：`about.sources`（中国监管/目录专名：国家医保局、医保药品分类与代码数据库）与 `about.samename`（品牌名 泰诺/泰诺林）；es 只剩 `about.samename`（品牌名）。其余 en/es 文案已无中文 |
| 四语 | I18N **328 keys × 4 语言完全一致**（构建日志 zh-Hant：328 from json, 0 fallback） |
| 构建 | exit 0；57,848 文件 / 408.7 MB；sitemap 57,697 URL（与 v0.6.4 一致） |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| Logo 中文副标题仅 zh 显示（其余语言 CSS 隐藏；静态副本随 `<html lang>`，移动端仍隐藏） | CSS `.logo-zh` 规则处 |
| 首页示例按页面语言：`HOME_EXAMPLES`（en/es/zh/zh-Hant）+ `_sample_buttons()`；落地页循环按 `code` 注入 `hero/try1/try2/try3` | `build_index_page`（`HOME_EXAMPLES` 定义 + f-string 占位符 `{{hero_examples}}`/`{{try1..3}}` + 循环 replace） |
| 四语首搜提示改写（en/es/zh 基础字典；zh-Hant 通过 `UI_I18N["zh-Hant"]` 覆盖 JSON） | I18N `home.hint_idle`/`home.hint_loading`；`UI_I18N["zh-Hant"]` 新增 `home.sub`/`home.hint_idle`/`home.hint_loading` |
| 英文 About 去掉裸中文：昵称示例改拼音「Two frogs (liǎng zhī qīngwā)」、`shuìqiányào`、TCM | `ABOUT_I18N["en"]` about.nick / about.terms / about.gaps |
| 西语 About 同样去中文：`Dos ranas (liǎng zhī qīngwā)`、`pastilla para dormir`、`medicamentos chinos tradicionales (TCM)` | `ABOUT_I18N["es"]` 对应段 |
| 首页静态默认文案同步新英文（无 JS 首帧） | `build_index_page` body 的 `home.sub` / `loadhint` 默认文本 |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-clean'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-clean\assets\app.js                      # 0
& $node --check .tmp\dist-clean\assets\i18n.js                     # 0
# headless Chrome（CDP，真实 innerText，explicit ?lang= / 语言目录）+ 静态扫描（见 _verify）
```

### Headless Chrome 抽查（visible text，非 DOM 源码）
- 语言正确：en-home / es-home / zh-home / zh-hant-home / en-about / es-about / en-glossary / es-glossary 的 `documentElement.lang` 均符合预期。
- **en/es 首页与 en/es 术语表：可见文本无中文**（语言切换标签「中文/繁」作为语言名允许）。
- **en/es About**：许可段以外无中文残留；剩余仅品牌名（泰诺/泰诺林）与语言切换标签；许可段内的中文/西语并列原文属有意内容（三语许可原文）。
- **logo 中文副标题**：en/es/zh-Hant computed `display:none`，zh 可见。
- **首搜提示**：en 含 `~0.2 MB` 且不再含 `6 MB`；es 含 `0,2 MB` 且不再含 `6 MB`。
- **示例按钮**：en/es/zh/zh-Hant 首屏按钮文本与预期列表一致（含 U1 Try 按钮）。

### 静态扫描
- 四语 I18N key 集合一致：328/328/328/328。
- en 值中 CJK 仅 2 处（about.sources 中国监管专名、about.samename 泰诺/泰诺林），es 仅 1 处（品牌名）——均属任务允许的「品牌/许可专名」。
- en/es/zh/zh-Hant 首页 `data-q` 示例列表分别符合语言要求；CSS 含 logo 隐藏规则；en 首页无旧 `6 MB` 文案。

## 3. 有意保留 / 风险

1. **About 许可段**：`LICENCE_HTML` 是三语（EN/中文/ES）并列的许可原文/署名（`reports/license-audit.md` §4），英文页里出现中文属**有意**；不改成单语以免丢失许可原文与署名。
2. **中国监管专名**：About「数据来源与覆盖」里 `国家医保局 医保药品分类与代码数据库` 是来源机构/目录的正式中文名，英文页保留并作为专名（任务许可例外）。
3. **品牌名**：About 的 `泰诺/泰诺林` 是中文品牌名（对照 Tylenol 用），保留。
4. **语言切换标签**：`中文 / 繁` 是语言名本身（各语言界面都显示原生语言名），不是漏翻。
5. zh-Hant 首页文案（sub/hint）由 build.py 在 JSON 覆盖之后强制写入；若 `data/i18n_zh_hant.json` 更新同 key，仍以 build.py 为准（避免旧 6 MB 文案回归）。
6. 首页示例按钮按静态页面语言渲染；语言切换走 `/es/`、`/zh/`、`/zh-hant/` 重新加载（与现有 `setLang` 行为一致），因此不会出现「切换语言后示例仍是上一语言」。
7. 本次未改索引/页面数量，dist 体积不变（408.7 MB）。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | 删 logo 隐藏 CSS / `HOME_EXAMPLES` 与占位符注入 / 恢复旧 `home.hint_*` 文案 / 恢复 About 中英混排示例 / 删 zh-Hant UI 覆盖 |
| 发布后 | gh-pages revert 上一提交（纯文案/示例变化，无数据影响） |

## 5. 产物

- `site/build.py`：logo CSS、`HOME_EXAMPLES`、四语 hints、About 去中文、zh-Hant 覆盖。
- `.tmp/dist-clean/`：构建产物（57,848 文件 / 408.7 MB）。
- `.tmp/dist-clean/_verify/`（headless.mjs、static_check.py 等，见 TEMP 同名脚本）。
- `reports/ui-lang-cleanup.md`：本报告。
