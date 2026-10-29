# name_lang 无译名角标（v0.9.4 Phase A）

> 2026-10-30 ｜ `site/build.py` ｜ **正式 `site/dist` 已构建（v0.9.4，898.241 MiB / 121,290 文件 / sitemap 63,363）** ｜ 未发布。
> DB 已由 data-depth 完成 `name_lang` 迁移：`en` 10,858 / `zh` 1,791。

## 0. 结论

- 非中文界面（en/es）遇到 `name_lang='zh'` 的 base 名：保留中文原名，加「No English name recorded / Sin nombre en español」角标。
- 中文界面（zh/zh-Hant）遇到 `name_lang` 非中文且**没有中文名**：保留原文，加「无中文名 / 無中文名」角标；若有 `inn_zh`，不误报。
- 不机器翻译、不音译；角标只是来源语言说明。
- 覆盖：成分页 H1（角标放 H1 下方来源行，H1 仍只药名）、名字页卡片、ATC/大类/组合成分列表、厂家页成分列、搜索结果成分列。
- 隔离构建仍 ≤900MiB；正式构建待 CHANGELOG v0.9.4 + Lead 放行。

## 1. 行为矩阵

| 界面 | `name_lang` | 有中文名？ | 展示 |
|---|---|---|---|
| en / es | zh | — | 中文原名 + No English / Sin nombre en español |
| zh / zh-Hant | en | 否 | 原文 + 无中文名 / 無中文名 |
| zh / zh-Hant | en | 是 | 中文名，无角标 |
| en / es | en | — | 原文，无角标 |
| zh / zh-Hant | zh | — | 中文名，无角标 |

## 2. 实现

- `SUB_NAME_LANG` 由显式 `SELECT substance_id, name_lang FROM substance` 一次性加载；不写 DB。
- 成分页 H1：`data-nl` + `data-zh`（是否有 `inn_zh`）；i18n.js 在 `.drug-name-src` 行加角标，**不把角标放进 H1**。
- 名字页卡片、ATC/大类/组合、厂家页成分列：按显示文本 CJK 判断，追加 `.nolang-badge`；不增加逐行 `data-*`，控制体积。
- 搜索结果：`ingredientHTML` 按 `e.x` 的 CJK 判断，同样追加角标。
- 四语文案键：`name.no_en` / `name.no_es` / `name.no_zh` / `name.no_zh_hant`。
- 数据包 `substances.csv` 加 `name_lang` 字段；`docs/data-dictionary.md` 同步。

## 3. 实测

```text
/drug/cn-7764ed6be6.html?lang=en  H1=地喹氯铵  角标=No English name recorded
/drug/cn-7764ed6be6.html?lang=es  H1=地喹氯铵  角标=Sin nombre en español
/drug/imipramine.html?lang=zh      H1=Imipramine 角标=无中文名
/drug/orlistat.html?lang=zh        H1=奥利司他  角标=0（有中文名，不误报）
/maker/100-karma-inc.html?lang=zh  厂家成分列角标=2
```

- H1 均只含药名/原文；角标在来源行或列表项，不进入 H1 可访问名。
- 无机器翻译/音译；原文完整保留。

## 4. 构建/体积

- 正式 `site/dist`：**121,290 文件 / 941,874,387 B / 898.241 MiB / sitemap 63,363 / 0 空文件**（3.64 min）。
- 相较无角标版本增量约 0.5MB（主要来自 i18n 字典、H1 `data-nl/data-zh` 与角标客户端逻辑；列表按 CJK 判断，不逐行加属性）。
- 未写 DB；临时 http.server 已全部关闭。

## 5. 边界

- 角标在 i18n.js 加载后生效；无 JS 时正文仍显示原文，但无角标。
- 名字页卡片/ATC/厂家页按**当前显示文本**是否含 CJK 判断，而不是逐条读 `name_lang`；H1 使用 DB `name_lang`。这是为控制 121k 页体积的折中。
- 如要求列表角标也严格按 DB `name_lang`（而非显示文本），需给逐行加属性并重新评估体积。
