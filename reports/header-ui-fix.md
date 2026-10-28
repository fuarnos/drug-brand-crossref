# v0.8.2 页头导航/语言切换换行修复报告（task-118）

> 任务：task-118（`site/build.py` 独占，构建 `.tmp/dist-header`）。
> 用户截图：中文界面 nav 每字竖排断行、语言切换「中文/繁」竖排、logo 副标题换行。未改 `data/*`、tests、`site/dist`。

## 0. 结果

| 项 | 结果 |
|---|---|
| nav 禁止竖排 | `header nav` / `nav a` 全部 `white-space:nowrap`；链接 nowrap，宽屏一行；≥1100px 超宽时整体换到第二行（logo 一行、nav 一行），不逐字断行 |
| 响应式 | **≥1100px**：一行布局（nav 与 langs 横排）；**768–1099px**：header 换行，nav 独占整行 `flex-basis:100%`、链接横排；**<768px**：nav 折叠为汉堡菜单，点击展开；语言切换始终紧凑横排 |
| 汉堡菜单 | `bilingual.js` 动态注入 `#navToggle`（☰，aria-label/aria-expanded），点击 toggle `header.nav-open`；移动端 nav 链接 `min-height:40px` |
| 语言切换 | `.langs` flex 横排、`white-space:nowrap`、点击区≥36/40px、当前语言高亮不变 |
| logo 副标题 | `.logo-zh` `white-space:nowrap`；<768px 隐藏；仅简体中文界面显示逻辑不变 |
| 四语 | 四语页面同一套结构；`nav.menu` 四语文案（Menu/Menú/菜单/選單） |
| 构建 | exit 0；62,880 文件 / 476.0 MB；sitemap 62,720 不变 |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| header/nav/langs/logo nowrap 基础样式 + 768–1099 换行 + <768 折叠菜单 CSS | CSS header 段 |
| `.nav-toggle` 按钮样式（移动端 ≥40px） | CSS |
| `initNavToggle()` 注入汉堡按钮 + aria-expanded + `header.nav-open` | BILINGUAL_JS start |
| `nav.menu` 四语文案 | BILINGUAL_I18N |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-header'; & $py -X utf8 site/build.py   # exit 0, 476.0 MB
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-header' '<repo>'  # 11/11 PASS
# 临时 http.server 8816 + headless.mjs → ALL CHECKS PASSED
```

- **静态 11/11**：nav nowrap、nav a nowrap、langs 紧凑、`.nav-toggle`、<768 媒体查询（nav 隐藏/展开）、移动 nav 链接 ≥40px、logo-zh 窄屏隐藏、汉堡注入与 nav.menu 四语、首页 nav 链接齐全、无 0 字节。
- **Headless（Chrome CDP）**：1280/1024/768 宽度：无横向溢出、nav 可见、**每个链接单行横排**（不再竖排）、语言切换紧凑横排；390px：nav 默认隐藏、汉堡可见、点击展开、`aria-expanded=true`、展开后 nav 链接可点区≥36px、语言切换≥36px、logo 副标题隐藏、无横向溢出。

## 3. 风险 / 已知事项

1. 768–1099px 采用「logo 一行 + nav 独占第二行」布局（任务允许两种方案之一），比下拉菜单更少点击。
2. 汉堡按钮由 `bilingual.js` 注入（无 JS 时移动端 nav 默认隐藏 → 链接不可达；站点其余功能亦依赖 JS，已在报告注明）。
3. 极长语言名/超窄屏（<360px）下语言切换仍横排，可横向滚动（页面本身不溢出验证通过）。

## 4. 回滚

`git checkout -- site/build.py` 后重建；或仅回退 header CSS 与 `initNavToggle`/nav.menu 改动。

## 5. 产物

- `.tmp/dist-header/`（62,880 文件 / 476.0 MB）。
- 验收脚本：TEMP `header-verify-20261028/`。
- `reports/header-ui-fix.md`：本报告。
