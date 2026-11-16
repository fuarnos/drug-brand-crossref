# R3 筛选浮层自适应（视口内钳制 / 手机底部抽屉）

> 工位：**atc4-ui** ｜ 任务：task-4（队列 R3 / T41）｜ 目标版本：v0.13.3（Lead 决定是否并入 v0.13.4）
> 依据：用户 2026-11-16 10:00 截图（成分页「筛选」浮层右侧 chips 被切掉）+ `reports/2026-11-16-r3-adaptive-ui-research.md`
> 范围：`site/build.py` 的 CSS 区（`.lf-panel` / `.catfinder .cf-chips` / `.sn-panel` / `#ac`）+ 两个浮层 token
> 性质：**零 JS、零依赖**；未 commit、未发布、未写 `site/dist`

---

## 0. 结论（结论先行）

1. **改前的 bug 是「整页横向溢出」，不是「祖先 overflow 裁切」。** 1440×900 实测：`.lf-panel` 的
   `getBoundingClientRect().right = 1755`，而视口宽 1440 —— 面板右缘越界 315px，同时
   `document.documentElement.scrollWidth = 1755 > 1440`，整页被撑出横向滚动条（390/768/1024 同样越界）。
   这正是用户截图里「右侧 chips 被切掉」的直接原因：**chips 没被裁，是它们长在视口外面**。
2. **根因只有一条**：`.listfilters{position:relative;left:0}` 让浮层的**包含块**落在 `sticky` 条最右侧的
   那个 `筛选` chip 上，而 `.lf-panel` 只有 `min-width:min(92vw,640px)`、没有上限、没有 `max-height`。
   按钮靠右 → 面板从偏右处向右下展开 → 右缘越界。
3. **修法（纯 CSS，0 JS）**：把包含块上移到整宽的 `.drug-sticky`（sticky 本身已是定位祖先），
   `min-width` 换成 `width:min(92vw,640px) + max-width:calc(100vw - 2*12px) + max-height + overflow:auto`；
   分类页子类浮层同样上移到 `.catfinder`；≤767 两者改 `position:fixed` 底部抽屉。
   **四档（390/768/1024/1440）+ 第五档 1440×520 全部 `inViewport=true`，`docScrollW == 视口宽`（0 横向溢出）。**
4. **首屏守卫不退化**：`first_screen_check.py` 同一份 CSS 连跑两次本身会报 6 项差异（items 0↔5.5、
   chrome 0.073↔0.105、aux_min 14↔13、overlay 0↔0.068 —— 详见 §6），所以按 **n=2 before / n=3 after 的
   指标包络**比：24 个「页面×视口」× 6 个指标**全部落在 before 包络内**，无一项真实退化。
5. 其余守卫（全部跑在真构建产物 `.tmp/dist-r3` 上）：`ui_surface_check` **同色 0 处**、`i18n_check` **FAIL 0**、
   `ci_checks --fast` **PASS 8 / FAIL 0 / SKIP 5**、`SITE_OUT=.tmp/dist-r3` 全量构建到 `== done ==`
   （137,323 文件 / 1,182.8 MiB，与改前产物**逐项一致**，只有 CSS 一个文件从 93,573 → 96,899 B）。

---

## 1. 改前的真实根因（修正调研报告的一条假设）

调研报告 `2026-11-16-r3-adaptive-ui-research.md` §0 列了两条根因，其中**第 ① 条不成立**：

- 报告假设「`.listfilters` 在 `.formchips` 里，被 `.formchips{overflow-x:auto}` 裁掉」。
- 实际 DOM：`_drug_list_html()` 返回 `chip_head + chips + "</nav>"`（`.formchips`）与 `lf_html` **两个并列片段**，
  `lf_html` 直接挂在 `.drug-sticky` 里（`site/build.py` L11497：`…{lf_html}`）。
- 证据：改前量 `.lf-panel{overflow:visible}`、`kidsClampedRight = 0`（**没有任何 chip 被父级裁切**），
  但 `docScrollW` 跟着面板右缘一起变大（1323 / 1408 / 1755）—— 这是**溢出到文档**，不是裁切。

报告 §0 第 ② 条（只有 `min-width` 没有上限、没有 `max-height`）成立，是真正的原因。

---

## 2. 改了什么（`site/build.py`，**+54 / −10 行**，全部在 CSS 常量里，`git diff --numstat` 现查）

| # | 位置（改前行号） | 改前 | 改后 |
|--:|---|---|---|
| A | `:root`（L4372） | — | 新增 `--float-gutter:12px; --float-max-h:min(70vh,560px)`，浮层统一钳制 token |
| B | `.listfilters`（L5151） | `display:inline-flex;flex-direction:column;position:relative` | 去掉 `position:relative` → 包含块交给 `.drug-sticky` |
| C | `.lf-panel`（L5162-5164） | `position:absolute;top:calc(100% + 6px);left:0;…;min-width:min(92vw,640px)` | `width:min(92vw,640px); min-width:0; max-width:calc(100vw - 2*var(--float-gutter)); max-height:var(--float-max-h); overflow:auto; overscroll-behavior:contain` |
| C′ | 新增 `@media (max-width:767px)` | — | `.lf-panel` → `position:fixed;left/right:var(--float-gutter);bottom:calc(64px + env(safe-area-inset-bottom))` |
| C″ | 新增 `@media (max-height:640px)` | — | `.lf-panel` → `position:fixed` 贴底，`max-height:calc(100vh - 2*var(--float-gutter))` |
| D | `.catfinder`（L5202） | `display:flex;flex-direction:column;…` | 加 `position:relative` 作为子类浮层的包含块 |
| E | `.catfinder .cf-sub`（L5207） | `position:relative;flex:0 0 auto` | 去掉 `position:relative` |
| F | `.catfinder .cf-chips`（L5215-5218） | `…min-width:min(92vw,520px)` | `width:min(92vw,520px); min-width:0; max-width:calc(100vw - 2*var(--float-gutter)); max-height:var(--float-max-h); overflow:auto` |
| F′/F″ | 新增两个 media query | — | ≤767 底部抽屉 / 高≤640 贴底（同 C′/C″） |
| G | `.sn-panel`（L5500-5502） | `…min-width:300px` | 加 `max-width:calc(100vw - 2*var(--float-gutter)); max-height:calc(100vh - 96px); overflow:auto`（横向原来已有 L4392 的同值 `max-width`，实测不越界；这次补纵向） |
| H | `#ac`（L4893） | `…overflow:hidden` | 加 `max-height:min(50vh,420px); overflow:auto; overscroll-behavior:contain`（调研 §3 第 4 条 P1 顺手项） |

**没用的技术（写了理由）**：`:has()` 与容器查询都没用 —— 失败模式是「相对视口越界」，不是「相对容器越界」，
把包含块换到整宽祖先 + `max-width/max-height` 就能结构性消除，不需要选择器魔法；也就不必承担
`@container` 的额外心智成本。CSS Anchor Positioning / Popper / Floating UI 按调研结论**不引**
（体积 35 KB / 8 KB gzip，而本方案 0 字节依赖）。

---

## 3. 四档 + 第五档 `getBoundingClientRect`（before / after）

测量方式：真 Chrome（headless + CDP，复用 `deploy/ui_surface_check.py` 的 `Site` / `launch_chrome` / `CDP`），
`Emulation.setDeviceMetricsOverride` 设视口 → 打开 `<details>` → 量 `getBoundingClientRect()`。
`docScrollW` = `document.documentElement.scrollWidth`。复现命令见 §9。

### 3.1 成分页「筛选」浮层 `#listfilters > .lf-panel`

| 目标 | 视口 | 有盒子 | left | right | top | bottom | position | docScrollW / 视口 | 在视口内 |
|---|---|---|---|---|---|---|---|---|---|
| **改前** | 390×844 | 否¹ | – | – | – | – | absolute | 390 / 390 | – |
| 改前 | 768×1024 | 是 | 683 | **1323** | 442.6 | 637.4 | absolute | **1323 / 768** | ❌ |
| 改前 | 1024×768 | 是 | 768.3 | **1408.3** | 442.6 | 637.4 | absolute | **1408 / 1024** | ❌ |
| 改前 | 1440×900 | 是 | 1115 | **1755** | 396.6 | 591.4 | absolute | **1755 / 1440** | ❌ |
| 改前 | 1440×520 | 是 | 1115 | **1755** | 396.6 | 591.4 | absolute | **1755 / 1440** | ❌ |
| **改后** | 390×844 | 否¹ | – | – | – | – | fixed | 390 / 390 | – |
| 改后 | 768×1024 | 是 | 21 | **661** | 448.6 | 643.4 | absolute | **768 / 768** | ✅ |
| 改后 | 1024×768 | 是 | 191.7 | **831.7** | 448.6 | 643.4 | absolute | **1024 / 1024** | ✅ |
| 改后 | 1440×900 | 是 | 261 | **901** | 402.6 | 597.4 | absolute | **1440 / 1440** | ✅ |
| 改后 | 1440×520 | 是 | 12 | **652** | 313.2 | 508 | fixed（矮视口贴底） | **1440 / 1440** | ✅ |

¹ 390 档 `#listfilters` 不渲染：`@media (max-width:767px){main .drug-sticky{display:none}}`（L4589）把成分页
粘性条（筛选入口在它里面）在手机上收起了。所以成分页在手机上**本来就没有这个浮层**，改前改后一致；
≤767 的抽屉规则是为「粘性条回到手机端」预留的（见 §7 残留说明）。

### 3.2 分类页子类浮层 `.catfinder .cf-sub > .cf-chips`

| 目标 | 视口 | left | right | top | bottom | position | docScrollW / 视口 | 在视口内 |
|---|---|---|---|---|---|---|---|---|
| **改前** | 390×844 | 302 | **660.8** | 542.8 | 634.8 | absolute | **661 / 390** | ❌ |
| 改前 | 768×1024 | 536.1 | **1056.1** | 648.8 | 702.8 | absolute | **1056 / 768** | ❌ |
| 改前 | 1024×768 | 621.4 | **1141.4** | 648.8 | 702.8 | absolute | **1141 / 1024** | ❌ |
| 改前 | 1440×900 | 968.1 | **1488.1** | 602.8 | 656.8 | absolute | **1488 / 1440** | ❌ |
| 改前 | 1440×520 | 968.1 | **1488.1** | 602.8 | 656.8 | absolute | **1488 / 1440** | ❌ |
| **改后** | 390×844 | **12** | **378** | 688 | 780 | fixed（底部抽屉） | **390 / 390** | ✅ |
| 改后 | 768×1024 | 20 | **540** | 648.8 | 702.8 | absolute | **768 / 768** | ✅ |
| 改后 | 1024×768 | 190.7 | **710.7** | 648.8 | 702.8 | absolute | **1024 / 1024** | ✅ |
| 改后 | 1440×900 | 260 | **780** | 602.8 | 656.8 | absolute | **1440 / 1440** | ✅ |
| 改后 | 1440×520 | 12 | **532** | 454 | 508 | fixed（矮视口贴底） | **1440 / 1440** | ✅ |

> 注意分类页在 **1440 也越界**（right 1488 > 1440）—— 不是只有手机有问题。
> 改后 390 的抽屉底边 780，视口 844，正好让开 56px 固定底栏（`.tabbar`）+ 8px。

### 3.3 页头下拉 `.sn-panel`（本来不越界，只补纵向）

| 视口 | 改前 left/right/top/bottom | 改后 | 说明 |
|---|---|---|---|
| 768×1024 | 76 / 452 / 110 / 531 | 同左 | 已在视口内（横向原本就有 L4392 `max-width`） |
| 1024×768 | 246.7 / 622.7 / 110 / 531 | 同左 | 同上 |
| 1440×900 | 563.7 / 939.7 / 62 / 483 | 同左 | 同上 |
| 390×844 | 不渲染（`header nav{display:none}`） | 同左 | 手机上只有「⋯」菜单，见下 |
| 390×844（`⋯` `.mmenu`） | 168 / 378 / 58 / 343.4 | 同左 | 已右对齐、在视口内 |

这一项**改前后数字完全一致**（说明本轮没有把它们改坏），新增的只有「超高可滚」的能力：
注入 1400px 假内容后 `clientH` 由 421 封到 `max-height`（928 / 672 / 804 / 424），`scrollH` 变 1819（可滚）。

### 3.4 chips 是否被裁（每个面板内所有 chip 的 rect 对比面板 rect）

四档 + 第五档、三个面板、改前改后：`kidsClampedRight` 全部为 **0**。
即改前也**不是**「被面板/父级裁掉」，而是整块跑到视口外面 —— 与 §0 结论 1 一致。

---

## 4. 溢出 / 可滚动能力测试（max-height 是不是真生效）

对每个「有盒子」的面板注入一个 `height:1400px; flex:0 0 auto` 的假子节点，再量一次：

| 面板 | 视口 | 面板高（注入前） | 注入后盒高 | `max-height` | clientH | scrollH | 封顶且可滚 |
|---|---|---|---|---|---|---|---|
| `.lf-panel` | 768×1024 | 194.8 | 560 | 560px | 558 | 1599 | ✅ |
| `.lf-panel` | 1024×768 | 194.8 | 537.6 | 537.6px | 536 | 1599 | ✅ |
| `.lf-panel` | 1440×900 | 194.8 | 560 | 560px | 558 | 1599 | ✅ |
| `.lf-panel` | 1440×520 | 194.8 | 496 | 496px | 494 | 1599 | ✅ |
| `.cf-chips` | 390×844 | 92 | 560 | 560px | 558 | 1458 | ✅ |
| `.cf-chips` | 768/1024/1440 | 54 | 560 / 537.6 / 560 | 同 | 同 | 1420 | ✅ |
| `.sn-panel` | 768×1024 | 421 | 928 | 928px | 926 | 1819 | ✅ |

改前同一测试：`overflowY = visible`、面板高随内容线性增长（无上限）—— 即**改前没有任何纵向兜底**。

> **残留（写在这，不藏）**：`max-height:min(70vh,560px)` 不知道面板自己的 `top`。真实内容远小于上限
> （成分页 194.8、分类页 54/92、页头 421），四档都够；但如果内容真的涨到 `max-height`，面板底边
> 在「锚点靠下 + 屏幕较高」的组合里仍可能探出视口下沿（注入测试里 1024×768 / 1440×900 两档的
> `ovfInVP=false`）。彻底解法是 JS 翻转（Floating UI）或原生 popover/dialog —— 按调研结论留给 v0.13.4，
> 本轮不做。

---

## 5. `details` 浮层覆盖清单（任务要求「凡有筛选浮层的地方都覆盖」）

把 `CSS` 常量里所有 `position:absolute|fixed` 逐条过了一遍（`grep` 脚本见 §9），结论：

| 位置 | 形态 | 处置 |
|---|---|---|
| 成分页 `.lf-panel`（`#listfilters`） | absolute 浮层 | ✅ 本轮修（§2 C/C′/C″） |
| 分类页 `.cf-chips`（`.cf-sub`） | absolute 浮层 | ✅ 本轮修（§2 D/E/F/F′/F″） |
| 页头 5 个 `.sn-panel`（类别/市场/关于/语言/⋯） | absolute 浮层 | ✅ 补纵向钳制（§2 G）；横向原本已不越界 |
| `#ac` 搜索自动补全 | absolute 浮层 | ✅ 补 `max-height`（§2 H，调研 P1 顺手项） |
| 结果页「高级筛选」`details.advfilter` | **在流内**（`.mf-panel` 是 grid） | 无需改：不是浮层，不会越界 |
| 结果页「国家/地区」`details.ctry-details` | 在流内 | 无需改 |
| 结果页「已选条件」`.idmore` / `.mkx-more` / `.more-specs` / `.undis` | 在流内（`inline`/块级） | 无需改 |
| `.tabbar`（固定底栏） | fixed | 未动（已带 `safe-area-inset-bottom`） |
| `.sb-hint` / `.sb-go`（搜索框装饰） | absolute | 未动（在 `.searchbar` 内，`left/right` 约束，不越界） |

---

## 6. 首屏守卫（`deploy/first_screen_check.py`）：同一份 CSS 自己就会差 6 项

**先说方法**：这个守卫**不是确定性读数**。我只改了 CSS，但同一份 CSS 连跑两次就能量出 6 项差异，
所以「改前 vs 改后各跑一次」的数字不能直接当结论。做法是：同一产物、同一份 HTML，**只换 CSS 文件字节**，
before 跑 2 次、after 跑 3 次，再比**指标包络**。

| 页面 | 视口 | 指标 | 同一份 CSS 两次运行（噪声） |
|---|---|---|---|
| drug | 390×844 | items 0 ↔ 5.5；aux_min 14 ↔ 13 | 两次都「同一份 CSS」 |
| drug | 768×1024 | items 4.5 ↔ 5.5；chrome_ratio 0.073 ↔ 0.105；afcr 0.999 ↔ 1.005 | 同上 |
| drug | 1440×900 | items 5.5 ↔ 4.5；chrome_ratio 0.135 ↔ 0.073；afcr 0.93 ↔ 0.999 | 同上（1440 那次还量到了 390 才有的 `.tabbar`，说明视口仿真串了） |
| drug | 2560×1440 | items 0 ↔ 13.5；chrome_ratio 0.135 ↔ 0.046 | 同上 |
| name | 390×844 | chrome_ratio 0.188 ↔ 0.327；overlay_ratio 0 ↔ 0.068 | 同上 |

**包络比较结果**（24 组 × `afcr / chrome_ratio / items / overlay_ratio / band_ratio / aux_min`）：

| 组 | 汇总 |
|---|---|
| before run#1 | 24 次扫描，6 组不达标 / 6 项（items 5、band_ratio 1） |
| before run#2 | 24 次扫描，3 组不达标 / 3 项（items 3） |
| after run#1 | 24 次扫描，3 组不达标 / 3 项（items 3） |
| after run#2 | 24 次扫描，3 组不达标 / 3 项（items 3） |
| after run#3 | 24 次扫描，3 组不达标 / 3 项（items 3） |

- **超出 before 包络的（页面×视口×指标）组合：0 个。**
- 即：after 的每一次读数都落在「同一份 CSS 两次运行之间」的范围内，**没有一项真实退化**。
- 不达标项（items 3）是 v0.13.3 之前就存在的既有项，与 R3 无关。

> 单跑一次的「after vs before」会报 6 项「退化」，恰好就是上表那 6 个噪声对（drug 390 aux_min、
> drug 768 chrome、drug 1440 items、drug 2560 aux_min、name 390 chrome / overlay）。
> Lead 2026-11-16 也独立复现了同类现象（三套 Chrome 并行时 drug@1440 items 4.5→0、atc@2560 48.5→13，
> 单独复测又回到 4.5 / 13.5），已登记为「守卫读数不稳」新任务；本轮按包络比法作证据。

---

## 7. 浏览器支持面（为什么这套纯 CSS 够用）

| 用到的能力 | 基线支持 | 说明 |
|---|---|---|
| `min()` / `max()` / `calc()` | Chrome 79 / Firefox 75 / Safari 11.1（2020-01 基线） | 宽度与高度钳制 |
| CSS 自定义属性（`--float-gutter` / `--float-max-h`） | Chrome 49 / Firefox 31 / Safari 9.1 | token 化 |
| `env(safe-area-inset-bottom)` | Chrome 69 / Firefox 65 / Safari 11.1 | 手机抽屉避开 Home 指示条 |
| `overscroll-behavior` | Chrome 63 / Firefox 59 / **Safari 16** | 只防「滚到底继续滚整页」；Safari ≤15 上退化为普通滚动，不影响不裁切 |
| `position:fixed` + `left/right` + `bottom` | 全绿 | 手机抽屉 |
| `@media (max-height:640px)` | 全绿 | 矮视口贴底 |
| `-webkit-overflow-scrolling:touch` | iOS Safari | 惯性滚动 |

**没用**：`:has()`、`@container`、CSS Anchor Positioning、`<dialog>`、popover、任何 JS / npm 依赖。

---

## 8. 真构建与其余守卫（全部跑在 `SITE_OUT=.tmp/dist-r3` 产物上）

### 8.1 全量构建（**未写 `site/dist`**）

```powershell
$env:SITE_OUT = 'D:\同种药物商品名剂量对应网站\.tmp\dist-r3'; & $py site\build.py
```

| 项 | 值 |
|---|---|
| 结束标记 | `== done ==`，exit code 0 |
| 构建版本号（内容哈希） | `4100101901` |
| 页数 | drug 13,435 / name 91,078 / combo 7,462 / maker 15,213；confused 22 对；warnings 40 条 |
| 索引 | `core.json` 40.2 MB；`i18n` 657 keys × 5 语言；`atc4-forms.json` 1.23 MB |
| 文件数 / 总字节 | **137,323 / 1,240,296,246 B（1,182.8 MiB）** |
| sitemap | 75,585 URL |
| CSS 产物 | `assets/style.f0430223e6.css` = **96,899 B**（改前 93,573 B，**+3,326 B / +3.6%**；兼容名 `style.css` 同内容） |

**与改前产物逐项对齐**：改前 `.tmp/dist-r1r2` 也是 137,323 文件 / 1,182.8 MiB —— 数量与总字节**完全一致**，
说明本轮**只有 CSS 一个文件变了**（93,573 → 96,899 B），没有新增/删除任何页面，也没有改任何模板字节。

几何数字复核：在真构建上重跑 §3 的探针，20 个「目标×视口」组合的 `left/right/top/bottom/docScrollW`
与 §3.3 的预览数值**逐位相同**（例：1440 → 261 / 901 / 402.6 / 597.4，`docScrollW=1440`），
即「CSS 覆盖预览」这一测量手法与真产物等价。

### 8.2 守卫三件套

| 检查 | 命令 | 结果 |
|---|---|---|
| 同色守卫 | `deploy/ui_surface_check.py --dist .tmp/dist-r3` | 12 次扫描（6 页 × 2 视口）**同色 0 处**，白名单放行 0 处 |
| 首屏守卫 | `deploy/first_screen_check.py --dist .tmp/dist-r3` | 见 §8.3 |
| i18n | `deploy/i18n_check.py` | **FAIL 0** / WARN 2 / INFO 24（WARN 是既有的 es 同形词 `form.kit` / `form.gas` 白名单提示，与 CSS 无关） |
| CI fast | `deploy/ci_checks.py --fast --dist .tmp/dist-r3` | **PASS 8 / FAIL 0 / SKIP 5**（13.2s；含 unittest etl 55 / lib 61 / mobile 29 / lib-atc-category 4，全 OK） |

### 8.3 首屏守卫 A/B（同一真产物、只换 CSS 文件字节，各跑 2 次）

| 轮次 | 失败组 | 失败项 | 明细 |
|---|---|---|---|
| before #1（HEAD 的旧 CSS，93,573 B） | 3 | 3 | items 3 |
| before #2 | 3 | 3 | items 3 |
| after #1（新 CSS，96,899 B） | 3 | 3 | items 3 |
| after #2 | 3 | 3 | items 3 |

- **超出 before 包络的组合：0 / 144**（24 组「页面×视口」× 6 指标 `afcr / chrome_ratio / items /
  overlay_ratio / band_ratio / aux_min`）→ **无退化**。
- 剩下的 3 项 items 不达标是 v0.13.3 之前就有的既有项，与 R3 无关。
- 脚本：`.tmp/r3_fs_ab.py`（从 `git show HEAD:site/build.py` 里取旧 CSS 常量，`sha256[:10]` 校验为
  `542cecc0b2`，与产物里 `style.542cecc0b2.css` 一致；跑完自动恢复新 CSS，并打印恢复后的哈希 `f0430223e6`）。

> 这套 A/B 是「同产物 + 只换 CSS」的干净对照；§6 里那次「先 dist-r1r2 换 CSS」的历史数据保留，用来
> **证明守卫本身不稳定**（同一份 CSS 两次跑差 6 项）。两者结论一致：R3 没有真实退化。

---

## 9. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# ① 浮层几何：改前（旧产物自带旧 CSS）
& $py .tmp\r3_probe.py --dist .tmp\dist-r1r2 --json .tmp\r3-before.json --shots .tmp\r3-shots-before

# ② 浮层几何：改后（把 build.py 里的 CSS 常量覆盖到旧产物的 style.<hash>.css 上起服务）
& $py .tmp\r3_preview.py --dist .tmp\dist-r1r2 --port 8791 &
& $py .tmp\r3_probe.py --base-url http://127.0.0.1:8791 --json .tmp\r3-after-preview.json --shots .tmp\r3-shots-after

# ③ 首屏守卫：同一产物只换 CSS 文件字节，before ×2 / after ×3，再比包络
& $py deploy\first_screen_check.py --dist .tmp\dist-r1r2 --json .tmp\r3-fs-before2.json

# ④ 同色守卫（支持 --override，不用改磁盘）
& $py deploy\ui_surface_check.py --dist .tmp\dist-r1r2 `
  --override "assets/style.542cecc0b2.css=.tmp/r3-style-after.css" `
  --override "assets/style.css=.tmp/r3-style-after.css" --json .tmp\r3-ui-surface-after.json

# ⑤ i18n / CI
& $py deploy\i18n_check.py --json .tmp\r3-i18n.json
& $py deploy\ci_checks.py --fast --dist .tmp\dist-r1r2

# ⑥ 真构建（不写 site/dist）
$env:SITE_OUT = 'D:\同种药物商品名剂量对应网站\.tmp\dist-r3'; & $py site\build.py
```

`.tmp/` 下临时脚本（uv 未入库）：`r3_probe.py`（几何探针）、`r3_preview.py`（CSS 覆盖服务）、
`r3_patch.py` / `r3_patch2.py`（补丁，逐条断言「恰好命中 1 次」+ 行尾 CRLF 自检 + `py_compile`）、
`r3_css_scan.py`（列全部 `position:absolute|fixed`）。

---

## 10. 截图（`docs/img/`）

> `-after.png` 全部取自**真构建产物** `.tmp/dist-r3`；`-before.png` 取自改前产物 `.tmp/dist-r1r2`
> （两者 HTML 逐字节相同，只有 CSS 不同）。

| 文件 | 内容 |
|---|---|
| `r3-lf-panel-1440x900-before.png` / `-after.png` | 成分页筛选浮层，1440：改前右侧 chips 出界（用户截图那个 bug）/ 改后 14 个市场 chip 全在视口内 |
| `r3-lf-panel-1024x768-before.png` / `-after.png` | 1024 |
| `r3-lf-panel-768x1024-before.png` / `-after.png` | 768 |
| `r3-cf-chips-390x844-before.png` / `-after.png` | 分类页子类浮层，390：改前右滚出界 / 改后底部抽屉（让开底栏） |
| `r3-cf-chips-1440x900-before.png` / `-after.png` | 分类页子类浮层，1440：改前 right=1488 越界 |

---

## 11. 改动边界声明

- 只改了 `site/build.py` 的 **CSS 常量区**：`.lf-panel` / `.listfilters` / `.catfinder` / `.cf-sub` /
  `.cf-chips` / `.sn-panel` / `#ac` / `:root` token。
- **没碰** `data-mkc` / `data-mkc-name` / `LANG_NATIVE_LABELS` / `SALT_WORDS`（刚发布的 R1/R2/R7），
  没碰任何模板 / JS / 路由 / 数据。
- 没改 `deploy/`、`lib/`、`data/`、`etl/`；没 commit、没发布、没写 `site/dist`。
- 行尾：`site/build.py` 现状是 **CRLF**（`git show HEAD:site/build.py` 也是 CRLF，17102 行 CRLF / 0 裸 LF）；
  补丁脚本写完做了「LF == CRLF」自检，未把行尾翻掉。
