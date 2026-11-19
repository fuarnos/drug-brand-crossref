# v0.19.0 首屏主流程（F1'/F2'/F3 + F4）实现与自验

- 工位：site-ui；日期 2026-11-20；源码 `site/build.py` **已冻结**（最后改动：F2' 直列分支）
- 自验产物：`.tmp/build_f1f2`（**干净产物**，显式 `SITE_OUT`）
- 命令：`$env:SITE_OUT='.tmp/build_f1f2'; & $py site/build.py` → `== done ==`，157,122 文件 / 1,468 MB（日志 total 1,539.4 MB）
- `deploy/i18n_check.py`：**FAIL 0 / WARN 25 / INFO 43**；最新 **v0.19.0 九语齐**（83 版 / 333 条）；`py_compile` 过
- 未写 `site/dist`、未 commit、未发布（构建与发布归 pages-deploy）

## 已达标（有截图/现查）

| 项 | 证据 |
|---|---|
| **F1' 首页四件** | 标题「这款药在别的地方叫什么？」、输入标签「药盒上写的名字」+ placeholder「例如：Tylenol Extra Strength」、地区「想查哪里？」、按钮「查药名 →」；首屏无「候选/来源/目标市场」字样（走查 5 次一致） |
| **F3 教程** | 三步示例统一 `Tylenol Extra Strength` / `500 mg`（源码 17304–17306，`data-q` 现查） |
| **F4 语言按钮** | 390/768/1440 均右上可见 `🌐 简体中文 ▾`（`docs/img/f1f2-langbtn-390.png` / `-768` / `-1440`），无横向溢出；点开 9 语本名；切到中文后 URL 保留 `?q=Tylenol+Extra+Strength&country=CN`、仍 5 条结果、`#country=CN`；刷新记忆（localStorage） |
| **地区记忆** | 选 CN → 刷新（URL 无 country）→ `#country` 仍 `CN` |
| **无结果** | 输入 `zzzznotexist` → 输入框保留原词、标题「没有匹配…」、提示「试试包装上的英文名或成分名」（提示在最后一次重建中修复，见下「待复验」） |
| **一次性查询直达** | `?q=Tylenol Extra Strength&country=CN` → 标题直接「中国有哪些相关药名」，**无确认屏**（`f1f2-1440-direct.png` / `f1f2-390-direct.png`） |
| **同名分叉** | `?q=Tylenol&country=CN` → 出现「你的药盒上写的是哪一款？」+ 两个包装选项 + 「我不确定」展开成分差异（`f1f2-1440-fork.png` / `-fork-unsure.png`） |

## 未达标 / 缺口（必须写清）

**F2'.1「同成分集合 → 直接列目标市场药名、不出现『选这项』」当前对验收样例未触发。**
现查 `?q=Tylenol Extra Strength&country=CN`：20 行（市场列全部「中国 · CN」），但每行仍有「选这项，查看中国药名」按钮（`.pickbtn` 21 个），因为该查询的候选集**包含多种成分集合**（对乙酰氨基酚；对乙酰氨基酚+氯苯那敏+伪麻黄碱；对乙酰氨基酚+金刚烷胺），按规则 2 属于「真分叉」，但当前分叉框只在「不同 name_key 的成分集合不同」时出现，未覆盖「同一查询下多成分集合」这一路径 → 既没直列、也没问二选一。

修复方向（约 30 分钟 + 12 分钟重建）：把判定改成对 `display` 的**成分集合分布**：
1. 只有一个集合（或占比 ≥ 阈值且其余为同集合变体）→ 直列该集合的目标市场条目（隐藏「选这项」）；
2. 多个集合 → 分叉框按集合分组展示（每个集合给代表包装名 + 成分差异），不再按 name_key；
3. 「选这项」只在「同成分集合但规格/剂型影响目标匹配」时保留，并在按钮旁写一句原因（新键 ×9 语）。

## 待复验

- 无结果提示：最后一次重建已加 `#f2hint`（`hint && hits.length` 才隐藏），但**尚未在浏览器复验**（重建后只跑了直达/分叉检查）。
- 首屏守卫 24 组对 `.tmp/fs_v0180.json` 基线：**本轮未跑**（时间用尽，产物已在 `.tmp/build_f1f2`，可复跑 `deploy/first_screen_check.py --dist .tmp/build_f1f2 --pages home --viewports 390x844,1440x900 --baseline .tmp/fs_v0180.json`）。

## 走查 5 次（清 localStorage，只看首屏）

5/5 次首屏一致：H1「这款药在别的地方叫什么？」、输入框（placeholder 示例）、按钮「查药名 →」、示例行；**第一次停留点=输入框，下一步=输入药名点「查药名」**，无需读说明即可完成一次查询（判为「一次点完」）。未出现「候选/来源市场/目标市场」等需要解释的词。

## 截图

`docs/img/f1f2-1440-direct.png`、`f1f2-390-direct.png`、`f1f2-1440-fork.png`、`f1f2-1440-fork-unsure.png`、`f1f2-1440-noresult.png`、`f1f2-langbtn-390.png` / `-768` / `-1440`；另 `f1f2-1440-direct2.png` / `f1f2-390-direct2.png`（最后一次重建后直列分支未触发的现状证据）。

---

## 最终判定（用户第三轮后，2026-11-20 12:2x）

- **精确源商品名 → 不问**：`Tylenol Extra Strength → 中国` 现查 `fork=0`、20 行目标市场列表（每行当地商品名/活性成分/规格，「不确定，查看差异」次级按钮），截图 `docs/img/f1f2-final2-1440-direct.png`、`f1f2-final2-390-direct.png`。
- **源市场同名多配方 → 才问**：`Tylenol`（非精确名、无目标地区）出现「你的药盒上写的是哪一款？」+ 两个**源市场包装名**（`TYLENOL FILM COATED TABLETS 500MG` / `Tylenol Extra Strength`）+「我不确定」展开成分差异；目标市场中文名不再进入提问，截图 `docs/img/f1f2-final2-1440-fork.png`。
- 无结果复验：输入保留 +「试试包装上的英文名或成分名」（`f1f2-final-noresult.png`，上一轮构建截图；提示逻辑本轮未改）。
- 源码 EOL：`git ls-files --eol site/build.py` = `i/crlf w/crlf`；`git diff --numstat` = +2852/−61。
- 最终自验构建：`$env:SITE_OUT='.tmp/build_f1f2'; & $py site/build.py` → `== done ==`，157,122 文件 / 1,468 MB；`i18n_check` FAIL 0 / WARN 25，最新 v0.19.0 九语齐。
- 残留：`.pickbtn` 仍有 1 个（不在结果行内，疑为隐藏模板/identity 卡内）；首屏 24 组在本轮最终 build 上**未重跑**（上一轮 4 项 items 退化，本轮已恢复候选表，预计回到 0；可复跑 `deploy/first_screen_check.py --dist .tmp/build_f1f2 --baseline .tmp/fs_v0180.json`）。

## 首屏守卫（最终轮，`deploy/first_screen_check.py --dist .tmp/build_f1f2 --baseline .tmp/fs_v0180.json`）

- **home 1440**：items 8.5 → **9.0（达标）**；覆盖率页/字号全部 ok。
- **results 390**：items **5.0**（目标 ≥6.2，仍差 1.2）
- **results 768**：items **10.5**（目标 ≥11，差 0.5）
- 已做：删除「名称/匹配方式」行、移除列表上方身份摘要卡、「同名或同成分」提示改小字、压缩 fork/notice 字号回 16px（body_min 恢复 16px）、结果行 padding 收紧。
- 剩余两项是**列表上方仍占位的标题 + 搜索框 + 地区行**；在不隐藏「中国有哪些相关药名」标题与搜索框（F2' 要求）的前提下，靠 CSS 已压不出 1.2 行。可选：① 结果页把搜索框收成一行（高度再省 ~50px）；② 390 下标题与地区行并排；③ 接受 390/768 两项 items 低于基线（需你拍板）。
- JSON：`.tmp/fs_final4.json`；截图：`docs/img/f1f2-final2-*.png`。

## 首屏条目已知偏差（Lead 已记录在案，v0.20.0 再收）

- 基线：`.tmp/fs_v0180.json`；本轮：`.tmp/fs_final5.json`（`deploy/first_screen_check.py --dist .tmp/build_f1f2 --baseline .tmp/fs_v0180.json`）。
- 结果：24 组里 **22 组 0 退化**；仅 2 项低于基线：
  - results 390×844：items **6.5 → 5.0（-23.1%）**
  - results 768×1024：items **11.5 → 10.5（-8.7%）**
- 原因（判定）：瓶颈不在列表上方 chrome（已删「名称/匹配方式」行、移除身份摘要卡、提示改小字、压缩结果行 padding 后数值仍持平），而在**结果行本身变高**——新流程要求每行直接给「当地商品名 / 活性成分 / 规格或『规格未确认』」，比旧版一行多 1–2 行，属于「信息密度换行数」。
- 处置：Lead 决定**接受这两项作为已知偏差**（不是无意义空白），v0.19.0 照常发布；**v0.20.0 收口方向**：移动端结果行折成两行内（成分与规格同行），或默认精简视图 + 展开。
- 其余指标（AFCR / chrome / 字号 / 横向溢出）22 组全部 ok；`body_min` 已恢复 16px。

## ui-surface 收口（表头同色）

- 现象：home/results 在 1280/390 四组报 `th` 与 `tr` 同色 `rgb(246,245,240)`（压缩 chrome 时覆盖了表头底色）。
- 修复（只动 CSS）：在样式末尾加 `table th{background:#e9eee9 !important;border-bottom:1px solid var(--line) !important}`，桌面与 390 同一规则。
- 复跑：`& $py deploy/ui_surface_check.py --dist .tmp/build_f1f2` → **12 次扫描：同色 0 处（白名单放行 0 处）**，exit 0。
- 重建：`$env:SITE_OUT='.tmp/build_f1f2'; & $py site/build.py` → `== done ==`；`i18n_check` FAIL 0；`site/build.py` 保持 CRLF。
