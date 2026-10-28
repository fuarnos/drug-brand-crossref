# v0.8.2 首页「三步看懂」引导位置上移报告（task-115）

> 任务：task-115（`site/build.py` 独占，构建 `.tmp/dist-guide`）。
> 用户截图要求：首页三步引导卡在 UI 上提高/提前。未改 `data/*`、tests、`site/dist`。

## 0. 结果

| 项 | 结果 |
|---|---|
| 位置 | 引导卡移到**搜索框正下方、国家选择行之前**（DOM 顺序：`#q`/searchwrap → `#u1guide` → `.row`）；桌面视觉上紧随搜索框，先看到引导再选国家 |
| 样式 | 标题 `.u1head h2` 16px→**18px / 700 字重**；卡片 padding 增大、轻阴影；步骤卡 `.u1step b` 15px 独立成行、卡片背景/边框层级更清晰；桌面 **三等分**（`repeat(3,1fr)`），移动端 **纵向单列** |
| 关闭 | 关闭按钮与 `localStorage['u1.dismiss.v1']` 记忆完全不变（headless 验证点击隐藏、刷新仍隐藏） |
| 四语 | 引导标题/步骤文案四语（zh 三步看懂、zh-Hant 同形、es、en）；页面其余布局不变 |
| 构建 | exit 0；62,880 文件 / 469.9 MB；sitemap 62,720 不变 |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| `#u1guide` 区块从「大类块之后」移到 searchwrap 与 `.row` 之间 | `build_index_page` body |
| U1 样式增强（18px/700 标题、padding/阴影、step b block、gap 12px） | CSS `.u1guide/.u1head h2/.u1step` |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-guide'; & $py -X utf8 site/build.py   # exit 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-guide' '<repo>'  # 10/10 PASS
# 临时 http.server 8814 + headless.mjs → ALL CHECKS PASSED
```

- **静态 10/10**：index 中 `#q` < `#u1guide` < `.row`（顺序正确）、大类块未误删；CSS 标题 18px/700、桌面三等分、移动单列、步骤 b 独立行；localStorage 关闭逻辑保留。
- **Headless（Chrome CDP）**：桌面 1280：引导 top ≥ 搜索框 bottom、bottom ≤ 国家行 top、默认可见、grid 3 列、标题「三步看懂」；zh-Hant/es/en 标题本地化；390px 移动端单列、无横向溢出；点击关闭→隐藏且 `u1.dismiss.v1=1`，刷新仍隐藏。
- 位置选择说明：放在搜索框正下方（国家选择行之前），让用户在输入前先看到用法；比放在 h1/简介前更贴近操作区，且不打断搜索主流程。

## 3. 风险 / 已知事项

1. 首屏高度增加约一个卡片；引导可关闭且记忆，重复访问不占空间。
2. zh-Hant 引导标题与简体同形（三步看懂），无简体/繁体差异字符；文案来自现有 i18n。
3. 无 JS 时引导同样显示（位置提升不依赖脚本）。

## 4. 回滚

`git checkout -- site/build.py` 后重建；或仅回退 body 顺序与 U1 样式。

## 5. 产物

- `.tmp/dist-guide/`（62,880 文件 / 469.9 MB）。
- 验收脚本：TEMP `guide-verify-20261028/`。
- `reports/home-guide-position.md`：本报告。
