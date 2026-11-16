# R3 筛选浮层自适应 + 全站 UI 模块调研（先找现成工具）

> 工位：**alias-site** ｜ 任务：task-17 ｜ 2026-11-16 ｜ 性质：**只读调研 + 方案**（未改代码 / 未建站 / 未写 dist / 未 commit）
> 依据：用户 2026-11-16 截图（成分页「筛选」浮层右侧被裁）+「最好各个 UI 显示模块都做自适应」+「每一个需求都要找有没有合适的工具或者代码，去 git 上找」（已写入 `AGENTS.md` §12）
> 代码基线：`site/build.py`（16,903 行，v0.13.0 + L8 徽章收敛）

---

## 0. 结论（可直接派给 site-ui）

1. **根因是两条叠加，不是单一 min-width**：
   - ① `.listfilters{position:relative}`（**L5086**）让面板的包含块落在 `.formchips` 里；而 `@media (max-width:767px)` 下 `.formchips{flex-wrap:nowrap;overflow-x:auto}`（**L5239**）是**横向滚动容器** → 绝对定位的 `.lf-panel` 被这个滚动容器**裁剪**，所以 390 下右侧 `A…`/`FR…` 被切。
   - ② `.lf-panel{min-width:min(92vw,640px);left:0}`（**L5097**）只有「最小宽度」没有「最大宽度」，1440/1024 下若按钮靠右，面板右侧越界；且**没有 max-height/overflow**，行数多时纵向也顶出视口。
2. **R3 推荐：纯 CSS 零依赖方案**（把包含块上移到 `.drug-sticky`、宽度 `min(92vw,640px)` 改 `width+max-width:calc(100vw-24px)`、`max-height:70vh+overflow:auto`、**≤767 改 fixed 底部抽屉**）。不改 JS、不引库、不动 `<details>` 语义，4 档（1440/1024/768/390）都不会越界。
3. **不采用**：CSS Anchor Positioning（Chrome 125+ 仍 *partial*、Safari 27 才 full、Firefox 147 才 partial；polyfill **35.4 KB gzip**）与 Floating UI/Popper（它们解决的是「锚点跟随 + 碰撞翻转」，而本面板改成「贴容器边缘 + 移动端 fixed」后**这类碰撞问题被结构性消除**）。**保留为下一批备选**：Floating UI（MIT、**8.19 KB gzip**、单文件 UMD）用于未来的 tooltip / autocomplete 跟随定位。
4. **同类隐患还有 2 处**：分类页子类浮层 `.catfinder .cf-chips`（**L5150**，同样是 absolute+92vw）、导航「菜单」`.sn-panel`（**L5435**，`min-width:300px` + 2×170px 网格 ≈ 364px）。建议与 R3 同批修（合计约 25 行 CSS）。
5. AutoComplete `#ac`（**L4826**）横向不会溢出（`left:0;right:0`），但**缺少 max-height/滚动**——长列表会顶出视口，属 P1。

---

## 1. 候选对比（A）

| # | 候选 | GitHub / 来源 | License | 体积（min / gzip） | 浏览器支持（caniuse 2026-10） | 与「无 npm / 静态 / 内联」兼容性 | 迁移成本 | 结论 |
|--:|---|---|---|---|---|---|---|---|
| 1 | **原生 Popover API**（`popover` / `showPopover`） | [whatwg/html](https://github.com/whatwg/html)、[MDN Popover API](https://developer.mozilla.org/docs/Web/API/Popover_API) | 规范（无代码） | 0 | Chrome/Edge 114+、Firefox 125+、Safari 17+（iOS 18.3 才完整）、Samsung 23+；**全球 93.95%** | ★★★ 原生，无依赖；top-layer 可**完全脱离祖先 overflow 裁剪**；但需改标记（`<details>`→`popovertarget`）并补 Esc/light-dismiss 的 JS 兜底 | 中（改模板 + 少量 JS） | **备选（下一批）**：能一劳永逸解决裁剪，但 Safari 17 语义差异需实测；本轮不值得为它改标记 |
| 2 | **CSS Anchor Positioning** | 规范 [w3c/csswg-drafts](https://github.com/w3c/csswg-drafts)（`css-anchor-position-1`）；polyfill [oddbird/css-anchor-positioning](https://github.com/oddbird/css-anchor-positioning)（493★，2026-11-02 仍在提交） | 规范；polyfill **BSD-3-Clause** | polyfill **119,028 B / 35,448 B gzip**（0.10.2，4 依赖） | Chrome 125+ **partial**、Edge 125+ partial、Safari **27+ full**（26 partial）、Firefox **147+ partial**；全球 full 仅 **2.75%** + partial 85.2% | ★ 规范写法优雅；**polyfill 超 10 KB 预算 3.5 倍**，且不支持动态增删锚点（README 明列限制） | 高（要 polyfill + 浏览器差异） | **不用**：体积/支持面都不达标；等 Firefox/Safari 全量后再回来 |
| 3 | **Floating UI**（`@floating-ui/dom`） | [floating-ui/floating-ui](https://github.com/floating-ui/floating-ui)（**32,811★**，2026-11-12 提交） | **MIT** | **21,365 B / 8,190 B gzip**（1.8.0；单文件 `dist/floating-ui.dom.umd.min.js`，core+utils 已内联） | 所有目标浏览器（纯 JS，无新 API 依赖） | ★★★ 可 vendoring 单文件、无构建链需求；在 `build.py` 里读取后哈希命名即可；无 CDN | 中（vendoring + 初始化调用） | **备选（下一批）**：本轮不需要翻转/跟随；未来 tooltip、autocomplete 跟随定位首选 |
| 4 | **Popper.js v2**（对照） | [floating-ui/floating-ui `v2.x` 分支](https://github.com/floating-ui/floating-ui/tree/v2.x)（原 `popperjs/popper-core` 已重定向到 floating-ui）；官网 [popper.js.org](https://popper.js.org/) | **MIT** | **19,984 B / 14,468 B gzip**（`@popperjs/core@2.11.8`） | 同 Floating UI（纯 JS） | ★★ 可 vendoring，但官方 README 已写「Popper is now Floating UI」 | 高（迁移到已停更 API） | **不用**：2.11.8 是终点，官方把用户往 Floating UI 引；gzip 反而更大 |
| 5 | **纯 CSS 钳制 + 底部抽屉** | 规范 [w3c/csswg-drafts](https://github.com/w3c/csswg-drafts)（Position/Overflow）、[MDN container queries](https://developer.mozilla.org/docs/Web/CSS/CSS_containment/Container_queries) | 规范（无代码） | **0** | `inset/max-width/overflow` 全绿；容器查询 Chrome 105+/Safari 16+/Firefox 110+（**现基线全覆盖**） | ★★★ 零依赖、零 JS、离线/CSP 无影响 | **低（3 处 CSS ≈25 行，无 JS）** | **✅ 采用（R3）** |
| 6 | **`<dialog>` + `showModal()`** | [whatwg/html](https://github.com/whatwg/html)；polyfill [GoogleChrome/dialog-polyfill](https://github.com/GoogleChrome/dialog-polyfill)；无障碍参考 [KittyGiraudel/a11y-dialog](https://github.com/KittyGiraudel/a11y-dialog) | 规范；polyfill Apache-2.0 | 0（原生） | Chrome 37+、Safari 15.4+、Firefox 98+；**全球 97.27%** | ★★★ 原生；top-layer + `::backdrop` + 焦点陷阱 + Esc 全内置 | 中（`<details>`→`<dialog>` + 打开/关闭 JS） | **备选（v0.13.4）**：移动端底部抽屉的**升级形态**（现在先用 fixed 面板，行为已够；dialog 可带来滚动锁定/焦点陷阱） |

> 体积取自 bundlephobia API（`@floating-ui/dom@1.8.0`、`@popperjs/core@2.11.8`、`@oddbird/css-anchor-positioning@0.10.2`、`@oddbird/popover-polyfill@0.7.3`）；浏览器支持取自 caniuse（数据 2026-10，全球用量 87.95%/93.95%/97.27% 分别对应 anchor/popover/dialog）。
> 所有候选均满足「零新增支出、无外部 CDN、可离线」；1/5/6 为零代码量，3/4 需 vendoring。

---

## 2. R3 推荐方案（B）

### 2.1 架构选择

| 档位 | 面板形态 | 实现 |
|---|---|---|
| **≥768** | 贴 sticky 条左缘的下拉浮层（覆盖内容） | `.lf-panel` 包含块上移到 `.drug-sticky`（它是 `position:sticky`，天然是定位祖先），`left:0; width:min(92vw,640px); max-width:calc(100vw-24px); max-height:min(70vh,560px); overflow:auto` |
| **≤767** | **底部抽屉**（fixed，左右各 12px，拇指可达） | `.lf-panel{position:fixed;inset-inline:12px;bottom:calc(8px + env(safe-area-inset-bottom));top:auto;width:auto;max-height:70vh;overflow:auto}` |
| 键盘/读屏 | 不变 | 仍是 `<details>/<summary>`（`<summary>` 可聚焦、可 Enter/Space 切换），面板内 chip/input 顺序不变；不引入 `aria-*` 变更 |

**为什么这就够**：面板相对视口的位置只有两种失败模式（横向越界、纵向越界）。横向：面板包含块换成 sticky 条（其宽度 = 内容带宽 ≤ 视口），`max-width` 再兜一层；纵向：`max-height + overflow:auto`。移动端 fixed 抽屉把「相对按钮定位」彻底移除，所以**任何按钮位置都不可能再裁切**。面板不再被 `.formchips` 的 `overflow-x:auto`（L5239）裁剪，因为包含块（sticky）是它的祖先而不是它的子元素。

### 2.2 CSS 骨架（改 3 处，无 JS）

```css
/* ① L5086：把包含块从 .listfilters 上移到 .drug-sticky（sticky 已是定位祖先） */
.listfilters{display:inline-flex;flex-direction:column}      /* 删掉 position:relative */

/* ② L5097：宽度/高度双向钳制（任何档位都不越界、可滚动） */
.lf-panel{position:absolute;top:calc(100% + 6px);left:0;z-index:30;
  width:min(92vw,640px);min-width:0;max-width:calc(100vw - 24px);
  max-height:min(70vh,560px);overflow:auto;overscroll-behavior:contain;
  -webkit-overflow-scrolling:touch;background:var(--surface-2);border:1px solid var(--line);
  border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px;
  box-shadow:0 8px 24px rgba(0,0,0,.10)}

/* ③ 新增（放在现有 @media (max-width:767px) 块内）：底部抽屉 */
@media (max-width:767px){
  .lf-panel{position:fixed;inset-inline:12px;left:12px;right:12px;top:auto;
    bottom:calc(8px + env(safe-area-inset-bottom));width:auto;max-width:none;
    max-height:70vh}
  /* 面板打开时不把 sticky 条顶高（fixed 已脱离文档流，无需额外处理） */
}
```

> 同批建议一起改：`.catfinder .cf-chips`（**L5150**）同样去掉 `min-width:min(92vw,520px)` → `width:min(92vw,520px);max-width:calc(100vw - 24px);max-height:min(70vh,520px);overflow:auto`，≤767 同样切 fixed 抽屉；`.sn-panel`（**L5435**）加 `max-width:calc(100vw - 24px)` 并把网格 `repeat(2,minmax(170px,1fr))`（L5438）改 `repeat(auto-fit,minmax(150px,1fr))`。

### 2.3 四档验收（本轮方案应全部通过）

| 档位 | 断言 |
|---|---|
| 1440×900 | 面板 `getBoundingClientRect().right ≤ innerWidth-12`、`bottom ≤ innerHeight`；可滚动；Esc 关闭（`<details>` 原生不支持 Esc —— 记 TODO，下一批 popover/dialog 补） |
| 1024×768 | 同上；面板不覆盖 sticky 条自身之外的主操作（`#q` 在页头，不受影响） |
| 768×1024 | 同上；面板宽 ≤ 640，左右各留 ≥12px |
| 390×844 | 面板 `position:fixed`、左右各 12px、底部 8px+safe-area；**`document.documentElement.scrollWidth === 390`（无横向溢出）**；chips 全部可见可点（含 `A…`、`FR…`）；键盘 Tab 能进入面板并循环回 summary |

自动化：`deploy/first_screen_check.py --dist … --viewports 390x844,1440x900`（横向溢出指标）+ 现有 `deploy/ui_surface_check.py`（面板底色 `--surface-2` ≠ 内部白 chip，不会触发同色规则）。

---

## 3. 全站 UI 模块自适应清单（C）

> 现状风险按「会不会裁切/顶出视口」分级：**P0 = 已出现裁切或必然溢出；P1 = 特定数据量下会溢出；P2 = 可读性/性能提升**。

| # | 模块（代码位置） | 现状风险 | 建议做法 | 优先级 |
|--:|---|---|---|---|
| 1 | 筛选浮层 `.lf-panel`（**L5097**）+ 锚点 `.listfilters`（L5086）+ 容器 `.formchips`（L5239） | **已裁切**（390 右侧被切；min-width 无 max；无滚动） | §2 方案：包含块上移 + `width/max-width/max-height/overflow` + ≤767 fixed 抽屉 | **P0 · v0.13.3** |
| 2 | 分类页子类浮层 `.catfinder .cf-chips`（**L5150**） | 同 1（`min-width:min(92vw,520px)`、无 max-height） | 同上（`width/max-width/max-height/overflow` + ≤767 fixed） | **P0 · v0.13.3** |
| 3 | 导航「菜单」`.sn-panel`（**L5435**，网格 L5438） | 768–1024 header 换行后菜单靠右 → 300px min + 2×170 网格可能越界 | `max-width:calc(100vw-24px)`、`right:0`（菜单在右侧）、网格 `auto-fit,minmax(150px,1fr)` | **P0 · v0.13.3** |
| 4 | 搜索自动补全 `#ac`（**L4826**） | 横向安全（`left:0;right:0`），但无 `max-height`，长列表顶出视口；390 键盘弹起更糟 | `max-height:min(50vh,420px);overflow:auto;overscroll-behavior:contain`；≤767 `max-height:40vh` | **P1 · v0.13.3** |
| 5 | 结果对比表 `.cmpbox` / `table.res.cmp`（**L5175/L5177**） | 4 列表格在 390 依赖 `table.res` 卡片化，cmp 自绘表格不在卡片规则内 | 复用 `table.res` 的 `td::before` 卡片机制，或 `.cmpbox .tablewrap{overflow-x:auto}` | **P1 · v0.13.4** |
| 6 | 横滑 chips `.formchips`（5239）/`.mkchips`（5165）/`.u2chips`（4969） | 已 `overflow-x:auto`，但边缘无渐隐提示，用户读成「被截断」 | `mask-image:linear-gradient(...)` 渐隐 + `scroll-snap-type:x proximity` | P1 · v0.13.4 |
| 7 | 多国矩阵 `.matwrap`（**L4980**）/明细表 `table.det`（5360）/`.tablewrap`（5374） | 已横滑；长表滚动条占位不稳 | `scrollbar-gutter:stable`；`contain:content` | P2 |
| 8 | 覆盖页/About 长表 `table.coverage-table`（4485–4494 已卡片化） | 桌面 7 列在 1024 可能挤压 | 桌面 `overflow-x:auto` + 列 `min-width`；已卡片化的 <768 保持 | P2 |
| 9 | 成分页市场块 `.mkblock` / `.mkrow`（5050、5500+；首屏 52 块） | 长页 DOM 重；非溢出问题 | `content-visibility:auto;contain-intrinsic-size:auto 320px` | P2 |
| 10 | 厂商页 15,213 页长列表 / 名称页 91,078 页 | 无分页/懒加载（L12 待办） | 每页 60 行 + `?p=` 深链；或 `content-visibility` 先兜 | P2 · 下一批 |
| 11 | 手机底栏 `.tabbar`（**L5457**） | 已有 `safe-area-inset-bottom`，安全 | 维持；新增页面复用 | — |
| 12 | 通用约定（新增组件默认） | 浮层类没有统一 token | 新增 `--float-max-h:min(70vh,560px)`、`--gutter:12px`；所有浮层默认 `max-width:calc(100vw - 2*var(--gutter)); max-height:var(--float-max-h); overflow:auto`；容器级适配优先 `@container`（现基线已支持） | **P0 约定** |

---

## 4. 分阶段落地（D）

| 版本 | 内容 | 改动面 | 验收 |
|---|---|---|---|
| **v0.13.3（R3）** | §2 筛选浮层 + 分类页子类浮层 + 导航菜单 3 处 CSS；`#ac` max-height（P1 顺手） | `site/build.py` **CSS 约 30–35 行**，0 JS、0 模板改动 | 390/768/1024/1440 四档无横向溢出；面板可滚动；`first_screen_check` 与 v0.13.2 比退化 0；`ui_surface_check` 0 同色 |
| v0.13.4 | `.cmpbox` 卡片化；chips 边缘渐隐；浮层 token 收敛；可选升级 `popover`（Esc/light-dismiss）或 `<dialog>`（移动端滚动锁定/焦点陷阱） | CSS ~40 行 + 可选 JS ~30 行 | 同上 + a11y 键盘回归 |
| 下一批 | 厂商页/名称页分页（L12）；`content-visibility`；Floating UI 只在出现「必须跟随锚点滚动」的组件时引入 | 中 | 分页深链可用、首屏指标不退化 |

---

## 5. 若将来 vendoring（E）——以 Floating UI 为例

- **文件**：`site/assets/vendor/floating-ui.dom.umd.min.js`（取 `@floating-ui/dom@1.8.0` 的 `dist/floating-ui.dom.umd.min.js`，MIT；单文件、无外部依赖）。
- **引入方式**（沿用现有哈希命名做法，参考 `CSS_FILE` 约 **L4759**）：`site/build.py` 里新增 `FLOATING_UI_JS = (ROOT/"site"/"assets"/"vendor"/...).read_text()`，写出 `assets/floating-ui.<sha256[:10]>.js` + 兼容名 `floating-ui.js`，只在需要的页型 `<script defer>` 引用；不改变现有 `app.js` 内联方式。
- **许可声明**：新增 `LICENSE-THIRD-PARTY.md`（Floating UI MIT 全文 + 版本/哈希），About 页加一行「第三方组件」链接；构建时校验文件 sha256 写进注释，便于复核。
- **不引入 CDN**：离线可用、隐私、CSP 都保持现状（`script-src 'self'` 不变）。

---

## 6. 参考链接（全部 GitHub / 规范）

- 原生 Popover：https://github.com/whatwg/html ｜ https://developer.mozilla.org/docs/Web/API/Popover_API ｜ https://caniuse.com/mdn-api_htmlelement_popover
- CSS Anchor Positioning：https://github.com/w3c/csswg-drafts ｜ polyfill https://github.com/oddbird/css-anchor-positioning ｜ https://caniuse.com/css-anchor-positioning
- Floating UI：https://github.com/floating-ui/floating-ui ｜ https://floating-ui.com/docs/computePosition
- Popper v2：https://github.com/floating-ui/floating-ui/tree/v2.x ｜ https://popper.js.org/
- 纯 CSS 规范：https://github.com/w3c/csswg-drafts ｜ 容器查询 https://developer.mozilla.org/docs/Web/CSS/CSS_containment/Container_queries
- `<dialog>`：https://github.com/whatwg/html ｜ polyfill https://github.com/GoogleChrome/dialog-polyfill ｜ a11y https://github.com/KittyGiraudel/a11y-dialog ｜ https://caniuse.com/dialog
- Popover polyfill（备选，3.75 KB gzip，BSD-3-Clause）：https://github.com/oddbird/popover-polyfill

> 只读声明：本单未运行 `site/build.py`、未写 `site/dist`、未改任何代码/数据、未 commit。所有体积数字来自 bundlephobia（2026-11-16 查询），支持数据来自 caniuse（2026-10 数据）。
