# 搜索埋点修复（v0.9.1 task-32）

> 2026-10-30 ｜ `site/build.py`（APP_JS / About 四语）｜ 未写 DB、未发布。
> 背景：GoatCounter 3 天 103 事件≈全自测；`search` 事件在每次输入时发送，13 条里 5 条是「盐酸左旋西替利嗪」逐字中间态。

## 0. 结论

- 搜索事件改为**只在提交时发送**：Enter、示例词 chip、自动完成选择、`?q=` 深链；输入过程不再发送。
- 同会话**前缀合并**：已发送词与当前词互为前缀时跳过，避免「盐」「盐酸」「盐酸左」重复。
- 事件路径带 **`lang`** 与 **`q_len`**：`search-<term>?lang=zh&q_len=8`。
- `search0-*` 零结果事件同样只在**提交查询**且确实零结果时发送，字段一致，仍 900ms 防抖 + 会话去重。
- About 隐私说明四语更新：说明只在提交时发送、输入中间态不发送、仅带查询长度与界面语言。
- 事件仍匿名（GoatCounter cookieless，不落 IP/账号/设备标识）；无新增第三方。

## 1. 代码位置

| 位置 | 改动 |
|---|---|
| `APP_JS` `trackSearchSubmit(q)` | 提交时上报；`SEARCH_SENT` 互为前缀跳过；`encodeURIComponent(lang)`、`q_len` |
| `APP_JS` `scheduleSearchEvent` | 保留函数名但 no-op；render 内部不再隐式上报 |
| `APP_JS` `scheduleSearch0` | 增加 `SEARCH_SUBMIT_Q` 校验；仅提交后的零结果发送；事件带 lang/q_len |
| `box` keydown Enter | 非自动完成选择时 `trackSearchSubmit` |
| `[data-q]` 示例 chip / `acSelect` / `?q=` | 提交式上报 |
| `about.analytics` en/es/zh/zh-Hant | 新增提交语义说明 |

## 2. 验证

- `py_compile` + `node --check` APP_JS/BILINGUAL_JS 通过。
- 代码审查：`render`/`renderATC`/`renderCategory` 中的 `scheduleSearchEvent` 已改为 no-op；只有 `trackSearchSubmit` 调 `gcEvent('search-…')`，只有提交入口调用它。
- 未做线上 GoatCounter 断言（`.env` 未配置 code，测试构建不注入统计脚本）；上线后看事件是否每条提交 1 条、无中间态。
- 观测侧建议：GoatCounter 后台按 path 前缀 `search-`/`search0-` 过滤；自测排除用 GoatCounter 的 ignore IP / 浏览器 Do Not Track 或本地不注入 code 的构建。

## 3. 已知边界

- 站点是即时搜索，没有传统「搜索按钮」；当前把 Enter/示例/chip/自动完成/深链视为提交。若真实用户只输入不按 Enter，将不会产生搜索事件（这是「只在提交时发送」的代价；可用 `search0`/点击结果补足行为证据）。
- 前缀合并会丢弃同会话中更长的后续词（例如先提交「盐酸」再提交「盐酸左旋西替利嗪」只保留前者）；若后续需要「最长词优先」，可在 v0.9.2 改成延迟发送/替换策略。
- `q_len` 是归一化词长，不是原始输入长度；不含任何可识别信息。
