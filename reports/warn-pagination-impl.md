# v0.6.7 /warn 分页（10 条/页）实现报告

> 任务：task-78（`site/build.py` 独占，v0.6.6 之后）。用户反馈：/warn 一次显示 40 条太多，希望 10 条/页可翻页。
> 未跑 git/发布、未改 `site/dist`、`data/drugs.db` 或其他跟踪文件。构建：`SITE_OUT=.tmp/dist-warn-pager`。

## 0. 结果

| 项 | 结果 |
|---|---|
| 分页 | **40 条 → 4 页 × 10 条**；上一页/下一页 + 页码 1..N + 「第 X / N 页 · 共 40 条」 |
| 深链 | `?page=N` 刷新/分享保持；越界 `?page=99` 自动收敛到末页并 `history.replaceState` 规范化 URL |
| 排序 | 保持 severity **high→medium→info**、同 severity 按 `warning_id`（沿用 DB 查询顺序）；**移除按 severity 的分组 heading**（避免分页跨组混乱） |
| 条目内容 | 每条保留 severity 徽章、国家/盐型标签、来源链接、相关成分、免责提示（headless/静态均验证） |
| 无 JS 降级 | 静态 HTML **不隐藏任何条目**（脚本运行前全部可见），分页仅客户端增强；不新增静态页 |
| 四语 | `warn.page_prev/page_next/pagination/page_status` × en/es/zh/zh-Hant（336 keys ×4 一致） |
| 可访问性 | `<nav aria-label>` + `data-i18n-aria`、`aria-current="page"`、首末页 `aria-disabled="true"`、页码状态 `aria-live="polite"`；链接可键盘操作 |
| 移动端 | 390px 宽无横向溢出；分页按钮 40×40px 可点 |
| 构建 | exit 0；60,375 文件 / 436.3 MB；sitemap 60,219（无新增静态页） |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| 分页文案 4 键 ×4 语（含 zh-Hant） | `UI_I18N`：en L156–159 / es L310–313 / zh L462–465 / zh-Hant L781–784 |
| `/warn` 渲染：40 条平铺 `#warnlist`（不再按 severity 分组标题） | `build_warn` L1921–1927 |
| 客户端分页脚本（PAGE=10、`?page=` 解析/收敛/替换历史、显示切片、上一页/下一页/页码、aria） | `build_warn` inline script L1928–1972 |
| 分页控件容器（`<nav id="warnpager"> aria-label + data-i18n-aria`） | L1975 |
| 分页 CSS（36px 可点、accent 高亮、disabled、移动端 40px） | L2321–2333 |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-warn-pager'; & $py -X utf8 site/build.py  # == done ==, exit 0
& $node --check .tmp\dist-warn-pager\assets\app.js                     # 0
& $node --check .tmp\dist-warn-pager\assets\i18n.js                    # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-warn-pager'   # 29/29 PASS
# 临时 http.server 8806 + headless.mjs（Chrome CDP）→ ALL CHECKS PASSED
```

- **静态 29/29**：40 条 article、`#warnlist`/`#warnpager`、PAGE=10、`?page` 支持、无 severity 分组标题、徽章/meta/来源/免责保留、静态 HTML 无隐藏条目（无 JS 降级）、`/es/ /zh/ /zh-hant/` 副本均含分页脚本、四语 336 keys 一致且 zh-Hant 为繁體、无 `@@`、CSS/移动端、sitemap 4 个 warn 页、无 0 字节。
- **Headless（Chrome CDP）**：默认 10 条（1–10）；`?page=3` → 21–30；`?page=99` → 收敛第 4 页；首/末页按钮禁用；当前页码 `aria-current`；页码链接 2,3,4,Next；四语分页文案（Page 1 of 4 / Página 1 de 4 / 第 1 / 4 页 / 第 1 / 4 頁）；移动端无横向溢出、按钮 40×40 可点。
- **无 404**：分页仅 query 参数（同文件），四语副本 `warn.html` 均存在；sitemap 仍 60,219。

## 3. 风险 / 已知事项

1. **JS-only 分页**：无 JS 时显示全部 40 条（任务允许的优雅降级）；有 JS 才按 10 条/页。
2. **页码 URL 不新增静态页**：`?page=N` 是同一 `warn.html` 的查询参数，canonical 仍指向 `warn.html`；搜索引擎不会索引每个分页版本（可接受）。
3. **条数变化自动适配**：分页总数由 JS 按实际 article 数计算；未来 40→更多条时页数自动变化，无需重建逻辑。
4. **wcag 细节**：`aria-disabled` 用 span 模拟禁用（不是 disabled 按钮），键盘不会被误导可点；如需严格可改用 `<button disabled>`。
5. **GoatCounter 事件（可选）**：warn 页未引入 app.js，未加 `warn-page` 事件；如需统计翻页，可后续在分页脚本内调用 `window.goatcounter.count`。
6. **severity 分组标题移除**：徽章仍在每条内，排序未变；如需视觉分组可在页内加当前页统计（本轮不做）。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | 删 `items_html`/`#warnpager`/pager 脚本与 CSS，恢复按 severity 分组 heading 渲染（旧 40 条长列表） |
| 发布后 | gh-pages revert 上一提交（纯 /warn 页面行为，无数据变化） |

## 5. 产物

- `site/build.py`：/warn 分页渲染 + 内嵌脚本 + CSS + 四语分页 keys。
- `.tmp/dist-warn-pager/`：构建产物（60,375 文件 / 436.3 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`（TEMP `warn-pager-verify-20261028/`）。
- `reports/warn-pagination-impl.md`：本报告。
