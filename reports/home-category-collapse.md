# v0.8.2 搜索后收起首页大类块报告（task-116）

> 任务：task-116（`site/build.py` 独占，构建 `.tmp/dist-collapse`）。
> 用户截图要求：搜索后收起首页「按大类浏览」。未改 `data/*`、tests、`site/dist`。

## 0. 结果

| 项 | 结果 |
|---|---|
| 行为 | 搜索框**非空**（有结果或零结果）→ 首页大类块（标题 + 16 chips）收起；**清空查询/回首页** → 恢复；空查询初始不收起 |
| 实现 | `setCatsHidden(hide)`：给 `.catquick` 加/去 `cat-hidden` class + `aria-hidden="true"/"false"`；`render()` 开头按 `!!q` 调用；CSS `.catquick.cat-hidden{display:none!important}` |
| 四语/移动端 | 行为与文案无关（class 控制），四语首页一致；移动端同样收起/恢复 |
| 构建 | exit 0；62,880 文件 / 469.9 MB；sitemap 62,720 不变 |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| `setCatsHidden`（class + aria-hidden） | APP_JS U1 关闭逻辑之后 |
| `render()` 首行 `setCatsHidden(!!q)` | APP_JS render |
| `.catquick.cat-hidden` 样式 | CSS |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-collapse'; & $py -X utf8 site/build.py   # exit 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-collapse' '<repo>'  # 6/6 PASS
# 临时 http.server 8815 + headless.mjs → ALL CHECKS PASSED
```

- **静态 6/6**：首页 catquick/16 chips 存在；app.js `setCatsHidden` + `cat-hidden` + aria-hidden；render 按 `!!q` 调用；CSS 隐藏；四语首页均有大类块。
- **Headless**：初始可见；有结果查询后收起（hidden class + aria-hidden=true）；清空后恢复（aria-hidden=false）；零结果查询后收起；zh-Hant/es 查询后收起、清空后恢复。

## 3. 风险 / 已知事项

1. 输入非空即收起（在索引加载期间也会先收起），结果返回后保持收起；清空立即恢复。
2. 大类块仅首页存在，其他页面 `setCatsHidden` 为 no-op。
3. `aria-hidden` 只影响辅助技术；视觉隐藏由 class 控制，无 JS 时大类块始终显示。

## 4. 回滚

`git checkout -- site/build.py` 后重建；或仅回退 `setCatsHidden`/render 调用/CSS。

## 5. 产物

- `.tmp/dist-collapse/`（62,880 文件 / 469.9 MB）。
- 验收脚本：TEMP `collapse-verify-20261028/`。
- `reports/home-category-collapse.md`：本报告。
