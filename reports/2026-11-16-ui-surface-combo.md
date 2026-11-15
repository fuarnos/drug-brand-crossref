# ui-surface：`span.tag.combo` 填充色 == 所在行背景（v0.13.0 / task-6）

- 工位 site-ui（task-6）｜2026-11-16｜只改 `site/build.py` 的 CSS（+2 行注释 / 规则 +1 属性），**未跑全量 `site/build.py`、未写 `site/dist`、未 commit**。
- **结论**：「复方」胶囊原来用**中性底色** `--surface-2:#f6f5f0` 打底，而结果表数据行 `tr.br` 的底色也是 `--surface-2` → 同色守卫（`deploy/ui_surface_check.py`，用户 2026-11-10 硬规则「框内颜色和框外颜色不许能一致」）判 4 处 FAIL。改成**差异色** `--warnbg:#fdf1ec` 打底后：**4 → 0**，12 次扫描元素数不变（页面结构未动），只增 1 个颜色属性。
- 数字：**改前 4 处**（home 1280x900 / home 390x844 / results 1280x900 / results 390x844，均为 `span.tag.combo rgb(246,245,240) in tr.br rgb(246,245,240) 42x20 x1`）→ **改后 0 处**。

## 1. 根因（CSS 级联，不是数据问题）

| 层 | 规则 | 结果 |
|---|---|---|
| 胶囊基类 | `.tag{display:inline;font-size:13px;padding:0;border:0;border-radius:0;background:none;color:var(--muted)}`（v0.12.1 R2，L4475） | 国家/剂型/状态**纯文字**（这份收敛没动） |
| 差异徽章共用 | `.tag.combo,.tag.warn,.tag.sev,.tag.picked,.tag.export{display:inline-block;padding:1px 7px;border-radius:var(--r-pill);border:1px solid var(--line);background:var(--surface-2)}`（L4479） | 五个差异徽章共用**中性底色** `--surface-2` |
| 各类型差异色 | `.tag.combo{color:#7a3b1f;border-color:#e6c3b3}`（原 L4530，**没有 background**）；`.tag.warn{…background:#fff6e8}`（L4656） | warn 自己有差异底色 → 一直 PASS；**combo 没有** → 落到共用 `--surface-2` |
| 行底色 | 结果表斑马纹/移动卡片行 `tr.br`、`tr:nth-child(even)` 等也用 `--surface-2`（L5525/L5526 等） | **246,245,240 == 246,245,240** → 守卫判同色 |

CZ/LV 写库后结果里出现复方行（`复方` 徽章），这条既有 CSS 债才被扫描到 —— 与 v0.13.0 数据无关，属「新数据暴露旧样式」。

## 2. 改法（沿用 v0.12.1「差异徽章只留自己的差异色」口径）

```css
/* site/build.py L4530-4532 */
/* v0.13.0（task-6）：combo 胶囊原用 --surface-2 打底，和结果行斑马纹 / 浅色行同色（246,245,240）
   → 改「差异色」打底（--warnbg），与 .tag.warn 同一口径：差异徽章只靠自己的颜色区分，不靠中性底色。 */
.tag.combo{color:#7a3b1f;border-color:#e6c3b3;background:var(--warnbg)}
```

- **不新增 token**：复用既有 `--warnbg:#fdf1ec`（与 combo 自己的文字色 `#7a3b1f`、边框色 `#e6c3b3` 同一暖色系；warn 用的是 `#fff6e8`，两者仍能区分）。
- **没有改回全局胶囊边框**：胶囊基类 `.tag`（L4475）与共用规则（L4479）**一字未动**；只给 combo 补它缺的那一个「差异色」。
- 与 `.tag.warn`（L4656 自带 `background:#fff6e8`）**同一口径**：差异徽章各自有底色，中性底色不再冒充差异色。
- 为什么不用「去掉底色变纯文字」：combo/warn/sev/export/picked 是 R2 明确要保留颜色语义的一类（`docs/谷段需求队列.md` L274「颜色只留 combo/warn/sev/export/picked」），去掉底色等于改设计口径；补差异色是最小且一致的做法。

## 3. 改前 / 改后数字（同一套守卫、同一份 dist）

```powershell
& $py deploy/ui_surface_check.py --json .tmp/ui-surface-before.json   # 改前
# 12 次扫描（6 页 × 2 视口）：同色 4 处（白名单放行 0 处），17.9s
#  [FAIL] home    1280x900 span.tag.combo rgb(246,245,240) in tr.br rgb(246,245,240) 42x20 x1
#  [FAIL] home    390x844  span.tag.combo rgb(246,245,240) in tr.br rgb(246,245,240) 42x20 x1
#  [FAIL] results 1280x900 span.tag.combo rgb(246,245,240) in tr.br rgb(246,245,240) 42x20 x1
#  [FAIL] results 390x844  span.tag.combo rgb(246,245,240) in tr.br rgb(246,245,240) 42x20 x1
& $py .tmp/ui_surface_after.py                                        # 改后（预览补丁，见 §4）
# 12 次扫描：同色 0 处（combo 相关 0）
```

逐页元素数改前 = 改后（712 / 595 / 6102 / 217 / 398 / 420），说明只是颜色变化、DOM 没动。
像素级取证（1280x900 结果页「复方」胶囊）：**改前填充 `rgb(246,245,240)`（= 行/带同色）→ 改后 `rgb(253,241,236)`（`--warnbg`）**。

## 4. 「改后」怎么在不重建 dist 的前提下测出来的（可复核）

全量构建归 Lead，我不写 `site/dist`；用 `deploy/ui_surface_check.py` 自带的 `Site.overrides`（源码注释就写着「预览补丁用：rel 路径 → 替换文件」）在**内存里替换响应体**，`dist` 一个字节没动：

1. `.tmp/ui_surface_after.py`：把改后 `build.py` 的 `CSS` 常量落盘成 `.tmp/ui-surface/style-after.css`，并用 `overrides` 覆盖 `assets/style.<hash>.css` / `assets/style.css`；
2. 顶层首页/结果页的 CSS 是**内联压缩子集**（`.tmp/ui-surface/index.html`，65,683 字符，整段对不上）→ 在内联块里做等价替换：`.tag.combo{color:#7a3b1f;border-color:#e6c3b3}` → 加 `;background:var(--warnbg)`（构建期内联器会得到同样结果）；
3. `.tmp/ui_surface_shots.py`：用同一套 `Site.overrides` 留改前/改后截图（`.tmp/ui-surface/shots/`）。

> 正式验收仍以 Lead 重建后的全量 `ui-surface` 为准；本次只是把「同一属性改动」在真浏览器里先验一遍。

## 5. 截图（`.tmp/ui-surface/shots/`，临时留证）

- `before-results-1280x900.png` / `after-results-1280x900.png`、`before-results-390x844.png` / `after-results-390x844.png`：结果页整屏前后对照（「复方」胶囊在第一行 `泰诺` 后面）。
- `badge-before-after.png`：「复方」胶囊 10× 放大前后对照（上=改前中性底色，下=改后暖色差异底）。
- 截图里同时可见 **v0.12.4 P0 未回退**：操作列「选择此产品 / 查看登记详」在同一行、不叠字（`table.res.rows tr.br .pickbtn{position:static…}` L5211 未动）。

## 6. 没把 v0.12.1 / v0.12.4 弄回去（逐条核对）

| 检查项 | 现状 | 证据 |
|---|---|---|
| v0.12.1 R2 胶囊收敛（国家/剂型/状态纯文字） | 未回退 | `.tag{…border:0;border-radius:0;background:none}` L4475 未改；共用规则 L4479 未改 |
| v0.12.4 P0 结果表操作列 | 未回退 | `tr.br .pickbtn{position:static;…}` L5211 未改；截图里按钮不叠 |
| 全局胶囊边框 | 没有加回去 | diff 里只新增 1 条 `.tag.combo` 规则属性，`.tag` 基类零改动 |
| 新 token | 没有新增 | 复用 `--warnbg` |

## 7. 自验

```powershell
& $py -m py_compile site/build.py         # exit 0
& $py deploy/ci_checks.py --fast          # 12 项：PASS 8 / FAIL 0 / SKIP 4（13.0s；i18n 已随 v0.13.0 译文补齐）
```

`git diff --numstat site/build.py` = `147 11`（含 task-3/4/6 累计；task-6 本身 = 1 行规则 → 1 行含属性 + 2 行注释）。文件仍全 CRLF。

## 8. 遗留（未动，供 Lead 判）

- 同一条共用规则里的 `.tag.sev / .tag.export / .tag.picked` 仍是 `background:var(--surface-2)`：当前只有 `.tag.warn`（自带 `#fff6e8`）和 `.tag.combo`（本次补）在页面出现，`sev/export` 无引用、`picked` 实际用的是 `.picked-tag`（`--accent` 底）。若将来启用这几个，会撞同样的行底色 —— 建议一次给各自差异色（本轮不顺手改，避免动无关样式）。
