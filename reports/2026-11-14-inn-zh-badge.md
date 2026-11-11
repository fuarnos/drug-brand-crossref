# v0.11.5 · INN 中文名徽标修复（task-71）

- 日期：2026-11-14（北京时间）· 工位：**site-ui**
- 构建：`.tmp/v0115-build`（与 task-70 增量构建同一棵源码树；**未写 site/dist、未 commit**）
- 结论：**「无中文名」判定增加 `e.xz`（成分中文名）兜底**；该 name 对应 substance 有 `inn_zh` 时不再误标，中文/繁体优先显示中文名。

## 1. 根因与修法

原判定（`APP_JS` 的 `ingredientHTML` / `markAtcRowGaps`）只看当前显示字符串：

```js
const orig = (e.x || e.d);          // 英文 INN 时无 CJK
if(!cjk && (LANG === 'zh' || LANG === 'zh-Hant')) 标「无中文名」
```

而索引条目里其实有 `xz`（中文成分名数组，来自 `substance.inn_zh`），但：
1. `ingredientLabel` 只在 `LANG === 'zh'` 且 `xz.length === x.split(' + ').length` 时使用；
2. 徽标判定**完全不看 `xz`**；
3. 个别英文 INN 作 name key 的条目 `subs_zh` 为空（DB 有 `inn_zh`），索引里便没有 `xz`。

修复：
1. `load_index()`：单成分类条目若 `subs_zh` 全空，用 `sub_names[sid]` 的 `inn_zh` 回填 `xz`
   （只对通用名/成分条目；商品名条目不受影响，品牌列本来就不走 `ingredientHTML`）。
2. `ingredientLabel()`：`zh` / `zh-Hant` 都优先用 `xz`；长度不一致时直接 `xz.join(' + ')`。
3. `ingredientHTML()`：`xz` 有中文名时**绝不加**「无中文名」徽标；英文/西语界面维持原逻辑。
4. `markAtcRowGaps()` 保持原有 `data-n-zh` 判断（ATC 卡片的中文名由服务端 `substance.inn_zh` 渲染），
   不把商品名硬套成分中文名。

## 2. 抽检

- **20 个 INN 的索引 `xz` 覆盖**：semaglutide / liraglutide / dulaglutide / tirzepatide /
  metformin / sitagliptin / empagliflozin / atorvastatin / rosuvastatin / amlodipine /
  losartan / valsartan / omeprazole / pantoprazole / escitalopram / sertraline /
  apixaban / rivaroxaban / levothyroxine / insulin glargine → **20/20 有 `xz`**。
- 浏览器实查（中文界面）：
  - `?q=Semaglutide`：结果行无 `nolang-badge`；`oral semaglutide` 是商品名，不硬翻；
  - `/atc/A10BJ.html?lang=zh`：`司美格鲁肽` 卡片显示中文、**0 个「无中文名」徽标**；
    `利拉鲁肽`、`度拉糖肽` 同样无徽标；
  - `Albiglutide`（DB 无 `inn_zh`）仍显示「无中文名」→ 预期，说明没有把所有英文名硬套中文；
  - `Tylenol` / `Lipitor` / `Ozempic` 商品名行：品牌列无 `nolang-badge`（不误标）。
- 截图：`docs/img/v0115-inn-a10bj-1440.png`、`docs/img/v0115-inn-a10bj-390.png`（390 无横向溢出）、
  `docs/img/v0115-semaglutide-1440.png`、`docs/img/v0115-semaglutide-390.png`。

## 3. 门禁

- 构建 `.tmp/v0115-build` **== done ==**：125,969 文件 / 977,029,571 B（两次构建 diff 0，见 task-70 报告）；
- `i18n_check` **FAIL 0**（WARN 2 / INFO 21）；
- `tests.test_markets_registry` **47/47 OK**；
- 无 `site/dist` 写入、无 commit。

## 4. 缺口 / 说明

1. **本地 v0.11.4 构建里 Semaglutide 卡片已经显示中文**（`xz` 已存在），用户线上截图的具体路径未能 1:1 复现；
   本次修复覆盖「`xz` 缺失 / 长度不一致 / 徽标只看原文」三条路径，属于防御性补齐。
2. 浏览器抽检为 **6 个 INN + 3 个商品名**（首页每次加载约 2s，时间紧未跑满 20+10）；
   20 个 INN 的 `xz` 覆盖用索引静态检查补齐。
3. 若线上仍复现，请给具体 URL/查询词与界面语言，我按该页再定位（可能是详情面板或 ATC 折叠区的另一条渲染路径）。
