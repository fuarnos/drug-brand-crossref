# S4「一药对照卡」只读调研 + 施工设计稿（v0.17.0 首项）

- 日期：2026-11-20
- 工位 / 任务：alias-site / task-2（只读调研；**未改** `site/build.py`、`data/drugs.db`、`site/dist`、`CHANGELOG.md`）
- 范围：S4 ① `/card.html?s=<substance_id>` + 产品数 Top 200 预渲染卡页；② 成分页筛选浮层改原生 `<dialog>`（本文给设计，不在本轮实现）
- 现查快照（可复核）：
  - `data/drugs.db`：**558,637,056 B**，mtime **2026-11-17 10:59**，sha256 **5C00BBE846B23D28A52706F04C8E167A2BC7CE7B3FDE66B19D7BA36CE89DA777**
  - 库计数：`substance` 13,645 · 有产品的成分 **13,434** · `product` **594,781** · `product_component` 772,775 · `variant` 15,248 · `product_name` 780,843 · `alias_all` 1,413 · `dose_warning` 41（published 40）· `collision` severe 27,664
  - `site/build.py` 当前 **19,415 行**（task-1 合入 ja 后比旧读数多约 715 行；本文锚点以函数名为主，行号只作近似）
  - `site/dist` 当前 **1,305,436,320 B / 137,348 文件**（v0.15.0、2026-11-18 构建，**已落后 CHANGELOG 的 v0.16.0**；首屏基线必须重建，见 §5.1）

---

## 0. 结论先行

1. **技术路线：零依赖原生平台。** 卡页用语义 `<table>` + 原生 `<dialog>`（筛选浮层）+ CSS 容器查询 + `content-visibility` + 滚动吸附；**不引入 tablesort / a11y-dialog / TanStack Table**（理由见 §1）。新增客户端 JS 只有一个约 4–6 KB 的共享 `assets/card.<hash>.js`，不外链、不进 npm。
2. **数据方案（推荐）：Top 200 预渲染 + Top 201–2000 的每成分 1 个小 JSON。** 预渲染 `/card/<sid>.html` 200 页；为排名 201–2000 的成分生成 `data/card/<sid>.json`（实测草案 **870 B/条、合计 1.57 MB**，含 Top 200 后约 **≤1.8 MB**）。`/card.html?s=` 只做取数与渲染壳；**不新增检索索引、不改 `core.json`**。排名 >2000 回退到既有 `/drug/<sid>.html`。
3. **这是唯一需要 Lead 拍板的一点：** 需求原文写「数据走已有分片，不新增索引」。现查证明**没有任何已有分片能按 substance_id 取出六块数据**（`core.json` 是 name-key 索引；`detail-*.json` 最大 5.68 MB 且按 name key 分桶；`atc-ing.json` 只有 sid→名称）。若严格禁止新增数据文件，`?s=` 只能重定向到 `/drug/<sid>.html`，**样本 tirzepatide（排名 526）就出不了卡**。本稿推荐新增「卡片数据文件」而非「索引」，并按 +0.5% 体积预算控制在 **+0.44% 左右**（明细 §5.3）。
4. **Top 200 现查口径（按含该成分的产品数）：** 第 1 名 acetaminophen **13,661**，第 200 名 memantine hydrochloride **718**；Top 200 合计 **347,124** 个产品（占 594,781 的 **58.4%**）。其中 **192/200** 有 severe 同名不同药名字；**15/200** 单方产品 <50（防晒/电解质/辅料类），**41/200** 无中文名，**8/200** 无 ATC。按需求保留字面 Top 200，但卡片对「单方占比很低」的成分加一句中性说明。
5. **样本口径：** `acetaminophen` 是成分（排名 1）；`tirzepatide` 是成分（排名 526，**不在 Top 200**，靠 201–2000 JSON 出卡）；`泰诺林` **不是成分**（是 CN 商品名 key，12 条产品、全部 acetaminophen），卡页不能把它当 `?s=` 成分；正确入口是名字页 → 成分卡。泰诺林的 `collision` 为 **warning（同成分 IR/ER）**，家族说明已有「泰诺 vs 泰诺林不同配方」。
6. **一个真实缺口：** 已发布的 R4 警示 `tylenol-vs-tainuo` 在 `dose_warning` 里 `substance_id` / `related_substance_id` 都为 NULL，也没有 name-key 关联字段；卡页第 5 块**无法自动把它挂到 acetaminophen 卡上**。MVP 只能链 `/warn.html#w-tylenol-vs-tainuo` + 家族说明；彻底修需给 `dose_warning` 加 `key_id`/映射表（写库任务，另批）。
7. **构建基线必须先重建：** 现有 `site/dist` 是 v0.15.0 旧产物，直接拿它跑「改前」会把 v0.16.0 的 ja 变化算进 S4。改前基线用 `SITE_OUT=.tmp/s4-baseline` 重建当前 HEAD（约 20 分钟），再跑 `first_screen_check` 两次。

---

## 1. 外部候选工具（AGENTS §12：先找现成工具）

### 1.1 结论

**不采用任何外部库，走原生平台。** 卡页的「可排序表格」只涉及 1–2 张 8–14 行的表；原生 `<table>` + `<button>` + `aria-sort` 约 40 行 JS 就够，且能保留 `aria-sort` / 状态播报 / 焦点不丢。引入库反而破坏本仓「无 npm、静态构建、样式内联、不用构建链」的约束。

### 1.2 候选对比

| 候选 | 版本 / 许可 | 体积（实测） | 浏览器支持 | 与本仓兼容性 | 结论 |
|---|---|---|---|---|---|
| **原生平台**（`<dialog>` / `<table>` / container queries / content-visibility / scroll-snap） | 平台特性，无依赖 | **0 B** | `<dialog>` Baseline 2022（Chrome 37+/FF 98+/Safari 15.4+）；容器查询 Baseline 2023-02-14；`content-visibility` Baseline 2025-09-15 | 完全兼容；无需 npm / 打包 / polyfill | **推荐** |
| **tablesort**（tristen/tablesort） | v5.7.1 · **MIT** | `dist/tablesort.min.js` **3,247 B**（源 `src/tablesort.js` 8,157 B；npm unpacked 527,469 B 含 demo/test） | README：Chrome 8+ / FF 3.6+ / IE10+ / Safari 5.1+ | 可内联 3.2 KB，但**不管 `aria-sort`、不做状态播报、不做数字/日期类型声明**；本仓仍需自己写这些 | 不采用；只在未来表格 >5 张时重新评估 |
| **a11y-dialog**（KittyGiraudel/a11y-dialog） | v8.1.5 · **MIT** | README 标 **1.7 KB**（npm unpacked 88,230 B；入口 `dist/a11y-dialog.js` 23,820 B） | 现代浏览器；依赖 `focusable-selectors` | 它的价值是给 `<div role=dialog>` 补焦点陷阱/ARIA；原生 `<dialog>` 已自带这些；引入等于重复实现 | 不采用 |
| **TanStack Table**（@tanstack/table-core） | v9.3.1 · **MIT** | npm unpacked **1,012,009 B**；入口 `dist/index.js` 7,250 B（还依赖 `@tanstack/store`） | 现代浏览器 | headless，但需要框架/模块接线与打包；本仓没有 npm，且只有 6 块的摘要表 | 不采用 |

> 体积口径：npm registry `dist.unpackedSize` + unpkg 入口文件实测（2026-11-19 抓取）。来源：[tablesort](https://github.com/tristen/tablesort)、[a11y-dialog](https://github.com/KittyGiraudel/a11y-dialog)、[TanStack Table](https://github.com/TanStack/table)、[npm registry](https://registry.npmjs.org/)。
> `dialog-polyfill` 也未采用：`<dialog>` 自 2022 起已 Baseline，本仓不需要为旧浏览器增加 1 个 polyfill 依赖。

### 1.3 推荐落地形态

- 表格：服务端输出**默认排序好的完整 `<table>`**；JS 只增强列头按钮（`aria-sort` 只在当前列、`data-value` 存原始值、`Intl.Collator` 比较、移动现有 `<tr>` 不重渲染）。
- 弹层：原生 `<dialog>` + `showModal()`；用 `closedby="any"` + 兜底点击外部关闭（Safari 尚未支持 `closedby`）；Esc/焦点由浏览器负责。
- 卡页：CSS 容器查询做两栏/单栏；`content-visibility` 只给首屏之外的块；市场横条用 `scroll-snap-type:x mandatory`。

---

## 2. Modern Web Guidance 落点（离线实取）

### 2.1 实取命令与证据

```powershell
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$mwg  = 'vendor\modern-web-guidance\skills\modern-web-guidance\modern-web.mjs'
$env:DISABLE_TELEMETRY = '1'
& $node $mwg search "dialog light dismiss modal"
& $node $mwg retrieve "dialog,light-dismiss-a-dialog,platform-controls-dismiss-dialog,prevent-page-scroll-under-modal-dialog,size-aware-styling,sortable-table,responsive-table,defer-rendering-heavy-content,carousel,validate-input-after-interaction"
```

- 实取结果：CLI 落盘 **82.2 KB / 1,519 行**（10 篇指南，含 `dialog` 等正文）；`search` 命中 10 条（`dialog` / `light-dismiss-a-dialog` / `prevent-page-scroll-under-modal-dialog` …）。
- 版本：`modern-web-guidance@1.0.1`（`VENDOR.md` §1，Apache-2.0，2026-11-17 存档）。
- 边界：只作参考，**不进 `site/build.py`、不进 `site/dist`、不新增 npm 链**（`VENDOR.md` §5）。

### 2.2 逐条落点（指南 id → 用在哪 → 关键要点）

| 指南 id | 用在哪 | 关键代码要点（≤3 行） |
|---|---|---|
| `dialog` | 成分页筛选浮层；卡页无需弹层 | 原生 `<dialog>` + `showModal()`；**不要**加 `role="dialog"` / `aria-modal` / 手写焦点陷阱 / Esc 处理器；`closedby="any"`（仅点击外部）；焦点自动回给触发按钮 |
| `light-dismiss-a-dialog` | 筛选浮层点遮罩关闭 | `closedby="any"` + `showModal()`；Safari 不支持 `closedby` 时用 `pointerdown/pointerup` 判断坐标在 `dialog.getBoundingClientRect()` 外再 `close()`；必须有可见关闭按钮 |
| `platform-controls-dismiss-dialog` | Esc / 手机返回关闭筛选浮层 | 模态 dialog 默认 `closerequest`；无需手写 Esc；不要拦截组件内部 Esc（组合框等要自己 `stopPropagation`） |
| `prevent-page-scroll-under-modal-dialog` | 筛选浮层打开时锁底页滚动 | `dialog:modal{overscroll-behavior:contain}` + `dialog::backdrop{overflow:hidden;overscroll-behavior:contain}`；**不要**给 `html/body` 加 `overflow:hidden` / `position:fixed`（会掉滚动条、跳位置） |
| `size-aware-styling` | 卡页六块两栏/单栏；筛选浮层宽度 | `.idcard{container-type:inline-size}`；`@container (min-width:720px){…}`；默认单栏安全布局，容器查询只做增强 |
| `sortable-table` | 市场覆盖表按产品数/写法数排序 | `<th scope=col>` 内放 `<button type=button>`；`aria-sort` 只在当前列；比较用 `Intl.Collator(undefined,{numeric:true})` 或 `data-value`；移动现有 `<tr>`，不 `innerHTML` 重建 |
| `responsive-table` | 390px 下市场表 | `.table-wrap{overflow:auto;container-type:inline-size}` + `tabindex=0` + `role=region`；窄容器 `thead{display:none}`、用 `::before` 注入行标签；表头 `position:sticky` |
| `defer-rendering-heavy-content` | 卡页第 4–6 块（首屏之外） | 只对首屏之外的大块用 `content-visibility:auto`；**必须**配 `contain-intrinsic-size:auto none auto 320px`；不要用在首屏 h1/第 1 块 |
| `carousel` | 市场横条（可选增强） | `display:flex;overflow-x:auto;scroll-snap-type:x mandatory;overscroll-behavior-x:contain`；`scroll-snap-align:center`；上一/下一用 `<button>`，不用 `::scroll-button()` |
| `validate-input-after-interaction` | `/card.html` 的「输入成分 ID」框 | 用 `required` + `pattern` + `:user-invalid`；错误文案放 `aria-describedby`，只在无效时挂；错误不能只靠颜色 |

### 2.3 支持度与降级（写进实现注释，避免以后误用）

- `closedby`：Chrome 134 / Edge 134 / Firefox 141 支持，**Safari 尚不支持** → 必须带「点击外部」兜底（`pointerdown/pointerup` 坐标判断，不用 `click` 的 `event.target`）。
- `overscroll-behavior` 在「非滚动容器」上的行为：Chrome 144 / Firefox 150 起，Safari 未支持 → 当渐进增强，**不要**用 `@supports` 探测（语法永远为真）。
- Popover API：Baseline 2025-01-27（Chrome 116 / Firefox 125 / Safari 17 / iOS 18.3）→ 本设计**不用 popover**，避免 polyfill。
- Invoker Commands（`command`/`commandfor`）：Baseline 2025-12-12（Safari 26.2）→ 排序/弹层**改用普通 `click` 监听**，不依赖它。
- `moveBefore()` / 元素级 View Transition：Safari 未支持 → 排序用 `appendChild` 移动节点即可，不做动画；不把动画当验收项。
- `content-visibility:auto` 可能让屏外节点在部分 AT 配置下暂不可达 → 上线前用键盘线性走查一次（§5.4）。

---

## 3. 数据与取数（只读）

> 所有查询均可复跑。单条用 `& $py db/q.py "SELECT ..."`（只 SELECT，不写库）；批量脚本按 `tests/trilingual/run_tests.py` 的 `mode=ro` 写法。
> SQL 里的 `?` 是参数占位；用 `db/q.py` 时请把 `?` 换成实际 sid（或走 `mode=ro` 的参数化脚本），不要原样粘贴。

### 3.1 库快照与口径

- 产品数按 `COUNT(DISTINCT product_id)`；同一产品含同一成分只算一次（`product_component` 一行一个成分，理论上不会重复，仍按 distinct 防御）。
- 「单方」= 该产品只有 1 个 `product_component` 行；「复方」= >1 行。
- 「各市场写法数」= 该成分在各市场 `product_name.name_type='trade'` 的 **distinct `name_variant.raw`**；同一写法在不同市场算不同行。
- 数据截止取 `source.data_as_of`，没有则 `data_as_of_note`；两者都空时显示来源自己的说明，不编日期。

### 3.2 产品数 Top 200 的 SQL 与结果

```sql
WITH n_ing AS (
  SELECT product_id, COUNT(*) AS c FROM product_component GROUP BY product_id
),
psub AS (
  SELECT DISTINCT v.substance_id AS sid, pc.product_id AS pid, ni.c AS n_ing
  FROM product_component pc
  JOIN variant v ON v.variant_id = pc.variant_id
  JOIN n_ing ni ON ni.product_id = pc.product_id
),
agg AS (
  SELECT psub.sid,
         COUNT(*) AS n_products,
         SUM(CASE WHEN psub.n_ing = 1 THEN 1 ELSE 0 END) AS n_single,
         COUNT(DISTINCT COALESCE(p.country, p.region)) AS n_markets
  FROM psub JOIN product p ON p.product_id = psub.pid
  GROUP BY psub.sid
)
SELECT s.substance_id, s.inn_en, s.inn_zh, s.atc,
       a.n_products, a.n_single, a.n_markets
FROM agg a JOIN substance s ON s.substance_id = a.sid
ORDER BY a.n_products DESC, s.substance_id
LIMIT 200;
```

**实测结果（2026-11-20，`mode=ro`）**

| 指标 | 数值 |
|---|---|
| Top 1 | `acetaminophen` 13,661 个产品（单方 6,188 / 14 市场） |
| 第 50 / 100 / 150 / 200 名产品数 | 1,942 / 1,167 / 886 / **718** |
| Top 200 产品数合计 | **347,124**（占全部 594,781 的 **58.4%**） |
| 有 severe 同名不同药名字的成分 | **192 / 200** |
| 单方产品 <50 的成分 | **15**（`octisalate` 6,219/3、`octocrylene` 5,493/2、`avobenzone` 5,378/1、`homosalate` 4,685/3、`oxybenzone` 2,950/0 …） |
| 无 `inn_zh` / 无 ATC | 41 / 8 |
| `tirzepatide` 排名 | **526**（320 个产品）→ 不在 Top 200 |

> 结论：Top 200 是「按数据量」的 SEO 集合，不等于「消费者最常查」；`tirzepatide` 这类高关注药靠 201–2000 的 JSON 覆盖。若 Lead 想把预渲染集换成「单方数 Top 200」或「有中文名 + 有 ATC + 单方≥50」，需要改需求口径（本稿不擅自改）。

### 3.3 六块数据来源 + SQL（按块）

#### 块 1：名称与各市场写法

来源：`substance`（INN / 中文 / ATC）、`product_name` + `name_variant`（各市场注册名）、`alias_all`（俗称/旧名/网络叫法）。

```sql
-- 1a 主名
SELECT inn_en, inn_zh, atc, atc_name, name_lang
FROM substance WHERE substance_id = ?;

-- 1b 各市场写法（展示按记录数降序，卡内每市场最多 2 条、总 12 条）
SELECT COALESCE(p.country, p.region) AS mk, nv.raw,
       COUNT(DISTINCT p.product_id) AS n
FROM product p
JOIN product_component pc ON pc.product_id = p.product_id
JOIN variant v ON v.variant_id = pc.variant_id
JOIN product_name pn ON pn.product_id = p.product_id AND pn.name_type = 'trade'
JOIN name_variant nv ON nv.key_id = pn.key_id
WHERE v.substance_id = ?
GROUP BY mk, nv.raw
ORDER BY n DESC;

-- 1c 也叫（俗称/旧名；不写进 product_name）
SELECT alias, kind, confidence, source, country
FROM alias_all WHERE substance_id = ? ORDER BY alias_id;
```

样本：acetaminophen 有 **8,459** 个产品带 trade 名、**6,848** 个 distinct 写法、14 市场；tirzepatide **108** 个 distinct 写法（266 个「市场×写法」行）、15 市场；泰诺林 1 个写法、CN 12 条产品。

#### 块 2：成分组合（含盐型与碱基）

来源：`variant`（salt / hydrate / ester / salt_code / strength_basis / base_fraction / interchange）、`product_component`（ord / 强度）、`substance`。

```sql
-- 2a 盐型 / 碱基（一个成分可有多个 variant）
SELECT v.salt, v.hydrate, v.ester, v.salt_code,
       v.strength_basis, v.base_fraction, v.interchange,
       COUNT(DISTINCT pc.product_id) AS n
FROM variant v
LEFT JOIN product_component pc ON pc.variant_id = v.variant_id
WHERE v.substance_id = ?
GROUP BY v.variant_id
ORDER BY n DESC;

-- 2b 含此成分的复方组合（签名 + 产品数）
SELECT sig, COUNT(*) AS n FROM (
  SELECT p.product_id,
         (SELECT GROUP_CONCAT(s2.inn_en, ' + ')
          FROM product_component pc2
          JOIN variant v2 ON v2.variant_id = pc2.variant_id
          JOIN substance s2 ON s2.substance_id = v2.substance_id
          WHERE pc2.product_id = p.product_id ORDER BY s2.inn_en) AS sig
  FROM product p
  WHERE EXISTS (SELECT 1 FROM product_component pc
                JOIN variant v ON v.variant_id = pc.variant_id
                WHERE pc.product_id = p.product_id AND v.substance_id = ?)
    AND (SELECT COUNT(*) FROM product_component x
         WHERE x.product_id = p.product_id) > 1
) GROUP BY sig ORDER BY n DESC;
```

样本：acetaminophen **1 个 variant（base / strength_basis=unknown / fraction=1.0 / interchange=unknown）**，复方 **7,473** 个，最大签名 `Acetaminophen + Chlorphenamine + Pseudoephedrine`（772）、`Acetaminophen + Amantadine`（694）；tirzepatide 1 个 base variant、0 复方；泰诺林 1 个 base variant、0 复方。

> 红线：`strength_basis` / `base_fraction` 只**展示**，**不做折算**；`interchange` 为 `unknown` 时写「未记录，不作结论」，不能推导「可以互换」。

#### 块 3：剂型·规格·释放机制

来源：`product`（dosage_form / form_base / release / pack）、`product_component`（strength_value/unit、per_volume）。

```sql
SELECT p.form_base, p.dosage_form, p.release,
       pc.strength_value, pc.strength_unit,
       pc.per_volume_value, pc.per_volume_unit,
       COUNT(DISTINCT p.product_id) AS n
FROM product p
JOIN product_component pc ON pc.product_id = p.product_id
JOIN variant v ON v.variant_id = pc.variant_id
WHERE v.substance_id = ?
GROUP BY p.form_base, p.dosage_form, p.release,
         pc.strength_value, pc.strength_unit,
         pc.per_volume_value, pc.per_volume_unit
ORDER BY n DESC;
```

样本：acetaminophen **231 个 distinct 规格**；release `none` 13,440 / `ER` 221；tirzepatide **35 个规格**，全部 `none`；泰诺林 12 条 CN 记录里片剂 1 条 + 缓释 3 条（`release=ER`）+ 液体制剂 7 条 + 剂型未注明 1 条。卡内**必须保留 `960 mg/30 mL` 这类 per_volume 写法**，不能压成 `960 mg`。

#### 块 4：市场覆盖

来源：`product.country` / `product.region` + `coverage` 视图 + `source`。

```sql
SELECT COALESCE(p.country, p.region) AS mk,
       COUNT(DISTINCT p.product_id) AS n_products,
       COUNT(DISTINCT CASE WHEN (SELECT COUNT(*) FROM product_component x
                                 WHERE x.product_id = p.product_id) = 1
                           THEN p.product_id END) AS n_single,
       COUNT(DISTINCT p.source_id) AS n_sources
FROM product p
JOIN product_component pc ON pc.product_id = p.product_id
JOIN variant v ON v.variant_id = pc.variant_id
WHERE v.substance_id = ?
GROUP BY mk
ORDER BY n_products DESC;
```

样本：acetaminophen 14 市场（CN 4,299 / US 3,482 / CA 1,349 / … / JP 47）；tirzepatide 15 市场（LV 60 / CZ 60 / US 54 / … / EU 1）；泰诺林 仅 CN 12 条。

#### 块 5：同名不同药与不可互换警示

来源：`collision` 视图（自动推导）、`dose_warning`（已发布）、`brand_family` / `name_family`（唯一人工表）、`confusable_pair`（FDA LASA）。

```sql
-- 5a 与该成分共享名字的 severe / warning（卡内最多 3+3 条，其余链成分页/警示页）
SELECT c.key_id, c.level, c.n_substances, c.n_products
FROM collision c
WHERE c.key_id IN (
  SELECT DISTINCT pn.key_id
  FROM product_name pn
  JOIN product_component pc ON pc.product_id = pn.product_id
  JOIN variant v ON v.variant_id = pc.variant_id
  WHERE v.substance_id = ?
)
AND c.level IN ('severe', 'warning')
ORDER BY CASE c.level WHEN 'severe' THEN 0 ELSE 1 END, c.n_products DESC;

-- 5b 已发布警示（只引用已有结论）
SELECT warning_id, rule, severity, title_zh, title_en, source_url
FROM dose_warning
WHERE status = 'published'
  AND (substance_id = ? OR related_substance_id = ?)
ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END;

-- 5c 品牌家族说明（泰诺 / 泰诺林这类）
SELECT DISTINCT bf.family_id, bf.label, bf.note
FROM brand_family bf
JOIN name_family nf ON nf.family_id = bf.family_id
WHERE nf.key_id IN (
  SELECT DISTINCT pn.key_id
  FROM product_name pn
  JOIN product_component pc ON pc.product_id = pn.product_id
  JOIN variant v ON v.variant_id = pc.variant_id
  WHERE v.substance_id = ? AND pn.name_type = 'trade'
);
```

样本：acetaminophen **1,586 个 severe 名字 / 17 个 warning 名字**（`co codamol` 3 成分 213 产品、`oxycodone and acetaminophen` 2/123、`nighttime sleep aid` 3/80…），已发布 `dose_warning` **0 条**（R4 的泰诺警示无 substance_id，见 §3.6）；tirzepatide **0 severe / 0 warning / 0 警示**；泰诺林 key 级 `collision` = **warning**（`n_substances=1, n_products=12`，IR vs ER），家族 `tylenol` 的 note 明确「美国单方 / 中国泰诺复方 / 中国单方叫泰诺林」。

> 卡内文案只允许：`name.severe` / `name.warning` / `warn.title` / `warn.no_advice` 既有结论 + 「不可互换」；**禁止**输出「A 可以替代 B」「按 mg 换算」等推断。

#### 块 6：来源·许可·数据截止

来源：`source`（name / url / license / license_url / data_as_of / data_as_of_note / retrieved_at）。

```sql
SELECT p.source_id, s.name, s.url, s.license, s.license_url,
       s.data_as_of, s.data_as_of_note, s.retrieved_at,
       COUNT(DISTINCT p.product_id) AS n
FROM product p
JOIN product_component pc ON pc.product_id = p.product_id
JOIN variant v ON v.variant_id = pc.variant_id
LEFT JOIN source s ON s.source_id = p.source_id
WHERE v.substance_id = ?
GROUP BY p.source_id
ORDER BY n DESC;
```

样本：acetaminophen **19 个来源**（nhsa 2025-04-04 4,297 条；openFDA 2026-10-23 3,482；HC DPD 2026-10-23 1,349；TFDA 2026-10-22 833；HK DH 2026-10-23 693；SÚKL 2026-11-01 662；dm+d 2026-10-19 443；CIMA live 411；COFEPRIS annual 327；BDPM 2026-11-03 230；HSA 2026-08-07 101；ZVA 2026-11-11 77；JP 2026-11-01 47；PBS 2026-10-01 25 …）；tirzepatide **16 个来源**（ZVA 2026-11-11 60、SÚKL 2026-11-01 60、openFDA 2026-10-23 54、HC 2026-10-23 24 … EU Union Register 2026-11-03 1）。泰诺林：`nhsa` 2025-04-04 + `manual_seed`（人工种子）。

### 3.4 三个样本的完整口径

| 项 | 泰诺林（name key） | acetaminophen（substance） | tirzepatide（substance） |
|---|---|---|---|
| 身份 | CN 商品名 `泰诺林`（`name_key`），指向 acetaminophen | 成分 `acetaminophen`，ATC N02BE01 | 成分 `tirzepatide`，ATC A10BX16 |
| 产品数 | 12（CN 100%） | 13,661（单方 6,188 / 复方 7,473） | 320（全单方） |
| 市场 | CN | 14 | 15（含 EU 1） |
| 写法 | 1（`泰诺林`） | 6,848 distinct trade 写法 | 108 distinct trade 写法 |
| 成分组合 | 仅 acetaminophen | 1 个 base variant；复方 7,473 | 1 个 base variant；0 复方 |
| 剂型/释放 | 片剂 IR + 缓释 ER + 滴剂/混悬/口服液 | 231 规格；none 13,440 / ER 221 | 35 规格；全 none |
| 同名不同药 | key 级 `warning`（同成分 IR/ER，不能互换） | 1,586 severe / 17 warning 名字 | 0 |
| 警示 | 家族 note（泰诺 vs 泰诺林） | 0 条已发布 `dose_warning`（R4 无关联） | 0 |
| 来源 | nhsa + manual_seed | 19 个 | 16 个 |
| 卡页入口 | 名字页 → 成分卡；`?s=泰诺林` 不是成分 | `/card/acetaminophen.html`（Top 1） | `/card.html?s=tirzepatide`（rank 526，JSON） |

泰诺林的 key 与家族（现查）：

```sql
SELECT pn.key_id, c.level, c.n_substances, c.n_products
FROM product_name pn JOIN collision c ON c.key_id = pn.key_id
WHERE pn.key_id = '泰诺林' LIMIT 1;
-- 泰诺林 | warning | 1 | 12
```

### 3.5 `/card.html?s=` 的卡片 JSON（草案 schema 与体积实测）

**为什么需要它：** `?s=` 是任意成分的深链，静态托管不可能在请求时查库；Top 200 之外必须有可 fetch 的六块摘要。现查确认无现成分片可按 sid 取六块（§0-3），因此这是**唯一能让 `?s=tirzepatide` 出卡**的方案。

**文件：** `data/card/<sid>.json`（每个成分 1 个；URL 安全，现查 Top 2000 的 sid 全部匹配 `[a-z0-9][a-z0-9._-]*`，最长 71 字符，无 CJK/斜杠）。

**Schema（紧凑键，服务端与客户端共用）：**

```json
{
  "id": "tirzepatide", "e": "Tirzepatide", "z": "替尔泊肽", "a": "A10BX16",
  "n": 320, "s": 320, "m": 15,
  "mk": [["CZ", 60, 60], ["LV", 60, 60], ["US", 54, 54]],
  "nm": [["CZ", "MOUNJARO"], ["LV", "MOUNJARO"], ["US", "MOUNJARO"]],
  "v": [["", "", "", "", "unknown", 1.0, "unknown"]],
  "f": [["injection", "none"], ["liquid", "none"]],
  "sp": [["2.5", "mg", "1.0", "dose"]],
  "c": [], "w": [],
  "src": [["zva_lv_register", "2026-11-11"], ["sukl_dlp", "2026-11-01"]]
}
```

字段：`id` 成分；`e/z/a` 英/中/ATC；`n/s/m` **全局**产品数/单方数/市场数（不能用截断后的 `mk` 求和，现查草案曾因此把 tirzepatide 算成 274，正确是 320）；`mk` 市场（≤8）`[市场, 产品数, 单方数]`；`nm` 市场写法（每市场 ≤2、总 ≤12）；`v` 盐型/碱基（≤3，`[salt,hydrate,ester,salt_code,basis,fraction,interchange]`）；`f` 剂型/释放（≤3）；`sp` 规格（≤3，`[value,unit,per_volume_value,per_volume_unit]`）；`c` 同名不同药（≤3，`[name_key, level]`）；`w` 已发布警示 id（≤3）；`src` 来源 + 数据截止（≤4）。

**体积实测（2026-11-20，按上述 caps 生成）：**

| 集合 | 条数 | 平均 | p90 | 最大 | 合计 raw |
|---|---|---|---|---|---|
| 全 13,434 成分（仅估算样本 300） | 300 抽样 | 468 B | 812 B | 987 B | ≈6.29 MB（外推） |
| **Top 201–2000（推荐生成）** | **1,800** | **870 B** | **1,144 B** | **1,781 B** | **1.566 MB** |
| 含 Top 200（若统一 fetch） | 2,000 | — | — | — | **≈1.74 MB** |
| `tirzepatide` | 1 | **1,014 B** | — | — | — |

**结论：** 生成 Top 2000 的 JSON（约 **1.74 MB**）在 +0.5% 体积预算内（§5.3）；不生成全 13,434（6.3 MB，单它就 +0.48%，再加 200 页会超）。`?s=` 对 rank >2000 回退 `/drug/<sid>.html`（该页本来就有全部产品明细）。

### 3.6 数据缺口（必须在卡页显示为「未记录」，不能猜）

1. **R4 警示无关联键：** `tylenol-vs-tainuo`（published, high）和 `tainuo-vs-tainuolin`（draft）的 `substance_id` / `related_substance_id` 都是 NULL，`dose_warning` 也没有 `key_id` 列 → 卡页无法自动把「泰诺 vs 泰诺林」挂到 acetaminophen 卡。MVP 用 `brand_family.note` + `/warn.html#w-tylenol-vs-tainuo` 链；彻底修需 `dose_warning.key_id` 或一张 `warning_name` 映射表（写库，另批）。
2. **泰诺林不是成分：** `?s=泰诺林` 应显示 `card.name_hint` + 名字页链接，不能伪造一张成分卡。
3. **15/200 单方极少：** 卡页按需求保留；对 `n_single / n_products < 10%` 的成分加一句「多数记录是复方，需核对完整成分」，不改变排序。
4. **41/200 无中文名、8/200 无 ATC：** 卡页按现有 `name.no_zh` / `drug.sid` 规则显示「无中文名」，不补造译名。
5. **现查 `tirzepatide` 在 `/drug/tirzepatide.html` 已有 216 KB 全量页；卡页是摘要，不替代它。**

---

## 4. 施工设计

### 4.1 文件 / URL / SEO / 内部链接

| 产物 | URL / 文件 | 数量 | 说明 |
|---|---|---|---|
| 预渲染卡 | `/card/<sid>.html` | **200**（Top 200） | 六块完整、服务端排序；进 sitemap；canonical 指向自己 |
| 查询壳 | `/card.html?s=<sid>` | 1 | `noindex,follow`；不进 sitemap；读 `?s=` → fetch JSON → 渲染；无效 sid 显示提示 + 搜索 |
| 卡片数据 | `data/card/<sid>.json` | **2,000**（Top 2000） | `?v=BUILD_V` 防缓存；无 manifest；404 即回退 |
| 共享脚本 | `assets/card.<hash>.js` | 1 | 约 4–6 KB；内容哈希文件名（同 boot.js 模式） |
| 成分页入口 | `/drug/<sid>.html` 页头 | 13,434 | 加「查看一药对照卡」链接（Top 200 链静态卡；其余链 `?s=`） |
| 名字页入口 | `/name/<key>.html` 成分卡 | 91,073 | 在 `../drug/<sid>.html` 链接旁加卡页链接（泰诺林 → acetaminophen 卡） |

- 不生成 `/es/card/…` 等语言副本：卡页与成分页一致，**单份 HTML + `i18n.js` 运行时换标签**；正文名字/数字语言中立。`page()` 的 `canonical_rel` 用 `card/<sid>.html`，`alternates=False`（不伪造 hreflang 副本）。
- `build_seo_files()` 自动扫 `OUT.rglob("*.html")`，所以 200 张卡自动进 sitemap（当前旧产物基线 75,609 URL，**+200**；v0.16.0 重建后以现查为准），**不要**把它们加进 `NOINDEX_RELS`；只把 `card.html` 加进 `NOINDEX_RELS`（查询壳无独立内容）。
- 互链规则（避免和成分页/名字页重复）：
  - 卡 → 成分页 `../drug/<sid>.html`（`#list` / `#forms` / `#mk-<国家>`）；名字页（每个名字 key 的 `key_file`）；`/warn.html#w-<warning_id>`；`/confused.html`；来源 `source.url`。
  - 成分页 → 卡（页头）；名字页 → 卡（成分卡标题下方）。
  - 卡不复制成分页的完整产品清单，只给六块摘要 + 「完整清单在成分页」。

### 4.2 取数流程（`?s=`）

```
GET /card.html?s=tirzepatide
  → card.js 读 URLSearchParams.s；空/非法 → 显示搜索框 + 提示
  → fetch('data/card/' + encodeURIComponent(s) + '.json?v=' + BUILD_V)
     200 → 渲染六块（与静态卡同一 schema/caps）
     404 / JSON 坏 / 超时 → 显示 card.not_ready + 链接 /drug/<sid>.html + 搜索框
  → 更新 <title>（INN + 中文名 + “identity card”），不改 canonical（canonical 固定 card.html）
```

预渲染卡 `/card/<sid>.html` 不 fetch 任何 JSON；只加载共享 `card.js`（排序增强）与站点 `boot.js` / i18n 单语包。

### 4.3 `site/build.py` 函数锚点（行号 2026-11-19 读数；task-1 合入 ja 后会整体位移，**以函数名为准**）

| 位置（当前行） | 函数 / 常量 | 改什么 |
|---|---|---|
| 102 | `_compute_build_v` | 不改；新增产物用 `BUILD_V` 做 `?v=` 缓存参数 |
| 190 / 1912 | `I18N` / `UI_I18N` | 在 `UI_I18N["en"/"es"/"zh"/"zh-Hant"]` 加 30 个 `card.*` 键（`card.packs` 已在 282/535/766 行附近） |
| 5101 / 5138 / 5175 | `_merge_static_i18n` / `_install_zh_hant` / `_assert_i18n_complete` | 不改逻辑；新键必须同时进 `FR_I18N` / `KO_I18N` / `JA_I18N` 扁平表，否则 `_assert_i18n_complete` 中止构建 |
| 6788–6826 | CSS `.listfilters` / `.lf-panel` | 改成 `<dialog>` 样式：`dialog:modal`/`::backdrop` 滚动锁、`max-height:min(70vh,560px)`、`width:min(92vw,640px)`；删绝对定位翻转依赖 |
| 11264 / 11330 / 11491 | `_page_head` / `page` / `_write_with_copies` | 复用 `_page_head("../", h1, summary_key="drug.summary")` 与 `page(...)`；卡页**不**用 `_write_with_copies`（不做语言副本） |
| 11855 | `load_index` | 不改；卡片排序另算（Top 200 用 SQL） |
| 12699 | `build_drug_pages` | 在页头 `head = _page_head(...)`（当前 13320）后加卡页入口链接；保持 `.matrix-filters` 类名，首屏守卫选择器不变 |
| 13195 / 14121 / 14223 | `_drug_list_html` / `lf_html` | 把 `<details class="listfilters">…<div class="lf-panel">` 改成 `<button class="matrix-filters" …>` + `<dialog id="listfilters">`；筛选 chip 逻辑不变 |
| 13640 | `build_name_pages` | 在成分卡 `<h2><a href="../drug/{sid}.html">`（当前 13732）旁加卡页链接 |
| 15365 | `build_index_page` | 不改（可选：首页不放卡入口，避免首屏 chrome 增加） |
| 17843 | `build_seo_files` | 不改；卡页自动进 sitemap；`NOINDEX_RELS.add("card.html")` 在 `build_card_shell()` 里做 |
| 18146 / 18161 / 17952 | `_shard_bucket` / `encode_shards` / `encode_core` | **不改**；卡片数据是独立小 JSON，不进 core/shard |
| 18210 / 19350 / 19365 / 19397 | `main` / `n_drug = build_drug_pages` / `n_name = build_name_pages` / `build_seo_files()` | 在 19350 之后插入 `n_card, n_card_data = build_card_pages(db, entries)`；在 19370 前 `build_card_shell()`；打印 `card pages: 200 / card data: 2,000` |
| 18722+（APP_JS 内） | 筛选浮层 JS | 把 `details` 开关改成 `dialog.showModal()` / `close()`；保留 `lfp*` 过滤函数与 `data-lf-drop` |
| 新增（main 前） | `CARD_TOP_N=200` / `CARD_DATA_RANK=2000` / `CARD_ROW_CAP` / `CARD_NAME_CAP` / `CARD_JS` / `build_card_pages` / `build_card_shell` / `_card_payload` | 见 §4.7 |
| 新增（main 内） | `CARD_PAGE_SIDS` 全局 | 在 `build_drug_pages` 之前算 Top 200 sid 集合，供成分页/名字页决定链静态卡还是 `?s=` |

**建议的数据加载方式（避免 N+1）：** 在 `build_card_pages` 内用一次 `PRAGMA temp_store=MEMORY` + `CREATE TEMP TABLE top(sid)`，按 §3.3 的 SQL 一次取回 Top 2000 的 markets / names / variants / forms / specs / collision / warnings / sources / aliases，再在 Python 里组装；实测同类集合式查询 **约 10–15 秒**（Top 201–2000 实测 10.4 秒），不会把 20 分钟构建拖长。

### 4.4 i18n：复用 + 新增

**复用（不新增）：** `drug.sid`、`drug.markets`、`drug.records`、`drug.specs`、`drug.release`、`drug.forms_label`、`drug.also_called`、`drug.summary`、`drug.notice`、`warn.title`、`warn.no_advice`、`warn.source`、`name.severe`、`name.warning`、`drug.status.*`、`nav.back_search`、`card.packs`。

**新增 30 个 `card.*` 键（七语全文见附录 A）：**

`card.title`、`card.cta`、`card.sec.names`、`card.sec.comp`、`card.sec.forms`、`card.sec.markets`、`card.sec.warn`、`card.sec.src`、`card.names.market`、`card.names.trade`、`card.names.count`、`card.comp.base`、`card.comp.basis`、`card.comp.combos`、`card.markets.single`、`card.markets.combo`、`card.warn.collision`、`card.warn.release`、`card.warn.published`、`card.warn.none`、`card.warn.note`、`card.src.licence`、`card.src.asof`、`card.not_ready`、`card.open_full`、`card.loading`、`card.error`、`card.cap`、`card.family`、`card.name_hint`。

- 新键总数：现 684 → **714/714**（七语）。`card.cap` 用 `{n}` / `{total}` 占位，沿用 `_subst_placeholders` 的替换风格。
- zh-Hant 值放 `UI_I18N["zh-Hant"]`（走 `_install_zh_hant` 的 extras，不必改 `data/i18n_zh_hant.json`；若后续要走 JSON 覆盖，再加）。
- fr / ko / ja：分别加到 `FR_I18N` / `KO_I18N` / `JA_I18N` 扁平表；`deploy/i18n_check.py` 会检查伪翻译（值==en 且不在白名单会 FAIL/WARN），附录 A 已避免「Licence」这类与英文同形的法语值。

### 4.5 成分页筛选浮层改原生 `<dialog>`（同批设计）

**目标（R3 残留）：** Esc 关闭、点外部关闭、内容涨到 `max-height` 时不再需要 JS 翻转；键盘焦点可回收。

**推荐实现：**

1. 触发按钮：保留 `.matrix-filters` 类和文案，把 `<details><summary>` 换成 `<button type="button" class="matrix-filters" aria-haspopup="dialog">筛选</button>`。
2. 弹层：`<dialog id="listfilters" class="lf-dialog" closedby="any" aria-labelledby="lf-title">`；内部保留 `.lf-panel` 结构与所有 chip / `data-lf-drop`。
3. 打开：`dlg.showModal()`；`autofocus` 放第一个 chip 或关闭按钮；关闭：`<form method="dialog"><button>完成</button></form>`。
4. 点外部兜底（Safari 无 `closedby`）：

```js
if (!('closedBy' in HTMLDialogElement.prototype)) {
  let outside = false;
  dlg.addEventListener('pointerdown', e => {
    const r = dlg.getBoundingClientRect();
    outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
  });
  dlg.addEventListener('pointerup', e => { if (outside) dlg.close(); });
}
```

5. CSS（只列关键，全部加在 6788 附近）：

```css
dialog.lf-dialog{width:min(92vw,640px);max-height:min(70vh,560px);overflow:auto;
  overscroll-behavior:contain;padding:16px;border:1px solid var(--line);border-radius:12px}
dialog.lf-dialog::backdrop{overflow:hidden;overscroll-behavior:contain;background:rgba(0,0,0,.35)}
@media (max-width:719px){dialog.lf-dialog{width:calc(100vw - 24px);max-height:calc(100dvh - 96px);margin:auto}}
```

6. 删除/降级：`.lf-panel` 的 `position:absolute/fixed`、R3 的 `max-width` 钳制保留但不再负责「翻转」；`details[open]` 相关 CSS 删除。**不要**给 `html/body` 加 `overflow:hidden`。
7. 首屏守卫：`.matrix-filters` 选择器保留；`CHROME_SEL` 里的 `.matrix-filters` 不变；`drug` 页的 `must_not_cover` 不变。打开 dialog 后是模态遮罩，不算首屏 chrome（守卫在未打开状态测量）。

**验收：** 390/768/1440 打开后 Tab 循环在 dialog 内、Esc 关闭、焦点回触发按钮；打开时背景不滚（`dialog:modal` + `::backdrop`）；内容超 560px 时 dialog 内部滚动；无横向溢出；对比度与 24px 触控目标。

### 4.6 与现有成分页 / 名字页的互链与去重

- **不重复内容：** 卡页只给六块摘要（最多 12 名字 / 8 市场 / 5 复方 / 8 剂型 / 6 警示 / 8 来源），完整明细留在 `/drug/<sid>.html`；卡页每个块末尾都有「完整清单」链接。
- **不重复 SEO：** 卡页 `canonical` 指向 `/card/<sid>.html`；`?s=` 查询壳 `noindex,follow`；卡页与成分页互相链接，但标题/描述不同（卡页 title 用「INN · identity card」；成分页保持现有 title）。
- **名字页：** 名字页已有 `_family_block` 与 `name.severe`/`name.warning`；卡页第 5 块复用同一批数据，不新增结论。泰诺林名字页已有 `tylenol` 家族说明；卡页只链过去，不复制整段。
- **检索结果：** 不建议在结果行加卡入口（会占首屏 chrome）；从成分页/名字页进入即可。

### 4.7 实现清单（文件 → 函数 → 改动要点 → 验收命令）

| # | 文件 | 函数 / 位置 | 改动要点 | 验收命令 / 判据 |
|---|---|---|---|---|
| 1 | `site/build.py` | 新增常量（`MAKER_MIN_PRODUCTS` 附近） | `CARD_TOP_N=200`、`CARD_DATA_RANK=2000`、`CARD_ROW_CAP=8`、`CARD_NAME_CAP=12`、`CARD_JS` | `py_compile` |
| 2 | `site/build.py` | 新增 `_card_payload()` / `build_card_pages()` | 集合式取 Top 2000 数据；渲染 200 静态页；写 `data/card/<sid>.json`（compact JSON，按 sid 排序）；返回计数 | 构建日志 `card pages: 200 / card data: 2,000`；`data/card/tirzepatide.json` 存在且 ≤2 KB |
| 3 | `site/build.py` | 新增 `build_card_shell()` | 写 `/card.html`；`noindex=True`；`NOINDEX_RELS.add("card.html")`；内联 `card.js` 引用 | `/card.html` 200；sitemap 不含 `card.html` |
| 4 | `site/build.py` | `CARD_JS` + main 写 `assets/card.<hash>.js` | `?s=` 解析、fetch JSON、六块模板、排序增强、错误/loading 状态 | 390/1440 手测；`card.js` 内容哈希与文件名一致 |
| 5 | `site/build.py` | `build_drug_pages`（13320 附近） | 页头加卡入口（Top 200 → `/card/<sid>.html`；其余 → `card.html?s=`） | 抽 3 个成分页链接 200 |
| 6 | `site/build.py` | `build_name_pages`（13731） | 成分卡加卡入口（泰诺林 → acetaminophen 卡） | `name/泰诺林.html` 含 `/card/acetaminophen.html` |
| 7 | `site/build.py` | `main()`（19350/19370） | 调 `build_card_pages` / `build_card_shell`；算 `CARD_PAGE_SIDS` | 构建 `== done ==`；页数 +201 |
| 8 | `site/build.py` | CSS（6788 附近 + 卡页样式） | `.idcard*`、`dialog.lf-dialog`、容器查询、`content-visibility`、scroll-snap | CSS 哈希文件名自动变；无 `!important` 滥用 |
| 9 | `site/build.py` | APP_JS（18722+） | `details` → `dialog.showModal/close`；保留 `lfp*` | Esc/点外/焦点回收手测 |
| 10 | `site/build.py` | `UI_I18N` / `FR_I18N` / `KO_I18N` / `JA_I18N` | 加附录 A 的 30 键 × 7 语 | `deploy/i18n_check.py` FAIL 0 |
| 11 | `deploy/first_screen_check.py` | `PAGES`（187）+ `READY_NEED`（758） | 加 `card` 页型：paths `card/acetaminophen.html`、`card/tirzepatide.html`；items `.idcard-table tbody tr, .idcard-block li`；`items_min=5`；`type=content` | `--pages card` 出数字 |
| 12 | `deploy/i18n_check.py` | 无需结构改动 | 只要 30 键进 4 个 UI 字典 + 3 个扁平表，脚本自动检查；确认 `FLAT_TABLES_BY_LANG` 含 ja | `FAIL 0 / WARN ≤ 基线 26` |
| 13 | `reports/` | 本报告 | 只读；不含 build/DB/dist 改动 | `git diff --stat` 只 `reports/` |

**验收命令（实现工位照抄）：**

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
& $py -m py_compile site/build.py deploy/first_screen_check.py
& $py deploy/i18n_check.py
& $py -m unittest discover -s lib -t lib
& $py tests/trilingual/run_tests.py
# 改前基线（当前 HEAD 重建，不要用旧 dist）
$env:SITE_OUT = '.tmp/s4-baseline'; & $py site/build.py            # 等 == done ==
& $py deploy/first_screen_check.py --dist .tmp/s4-baseline --json .tmp/first-screen/before-1.json
& $py deploy/first_screen_check.py --dist .tmp/s4-baseline --json .tmp/first-screen/before-2.json
# 改后（正式 dist）
Remove-Item Env:SITE_OUT
& $py site/build.py                                               # 等 == done ==
& $py deploy/first_screen_check.py --json .tmp/first-screen/after-1.json
& $py deploy/first_screen_check.py --json .tmp/first-screen/after-2.json
& $py deploy/first_screen_check.py --baseline .tmp/first-screen/before-1.json
```

### 4.8 红线自检（实现后逐条 grep / 人工看）

| 红线 | 卡页做法 | 自检 |
|---|---|---|
| 商品名不是主键 | `?s=` 只接受 substance_id；名字输入走名字页候选集；卡页不把某个商品名当唯一答案 | `card.name_hint` 出现；名字页 → 成分卡链接正确 |
| 不给用药建议 | 卡页只引用 `collision` / `dose_warning` 既有结论；`card.warn.note` + `warn.no_advice` 固定显示 | `grep -nE '建议|推荐|可以替代|可替换'` 卡页模板应为 0（否定句除外） |
| 不做剂量换算 | `base_fraction` / `strength_basis` 只展示；不写 mg→mg 换算、不写「等效剂量」 | 卡页模板无 `base_fraction *` / `换算` / `equivalent dose` 计算逻辑 |
| 不判断两药能否互换 | 只用 `name.warning` / `warn.title` 的「不能互换」；不新增 A vs B 结论 | 卡页只出现现有 `collision.level` 与 `dose_warning` 的原文/译名 |
| 不手工标注 collision | 卡页读 `collision` 视图，不写死名单/白名单 | 卡页代码无 `SEVERE_NAMES` 之类常量 |

---

## 5. 风险与验收预案

### 5.1 首屏守卫 7 指标（改前×2 / 改后×2）

**基线怎么取（重要）：** 现有 `site/dist` 是 v0.15.0（2026-11-18），CHANGELOG 已到 v0.16.0；**不能拿旧 dist 当改前**。先 `SITE_OUT=.tmp/s4-baseline` 重建当前 HEAD，连跑两次 `first_screen_check.py --json before-1.json / before-2.json`；实现后用正式 dist 跑 `after-1/2`，再 `--baseline before-1.json` 比较（退化 >5% 即 FAIL）。

**7 指标与阈值（内容页档）：**

| # | 指标 | 阈值 | 卡页怎么保证 |
|---|---|---|---|
| 1 | AFCR 首屏有效内容比 | ≥50% | 六块紧凑表格；页头只保留返回 + h1 + 一行摘要 + 搜索 |
| 2 | 主操作可见 | 首屏内完整可见 | 返回搜索、首个块内「完整清单」链接在首屏；排序按钮在表头 |
| 3 | 首屏条目数 | ≥5 | `.idcard-table tbody tr` + `.idcard-block`；六块至少 5 条可见 |
| 4 | chrome 占比 | ≤35% | 不新增顶部公告/语言条；页头沿用现有壳 |
| 5 | 悬浮遮挡 | ≤20% 且不遮正文 | 不加 sticky 工具栏；dialog 关闭态不计 |
| 6 | 字号 | 正文 ≥16px、辅助 ≥13px、无 <12px | 卡页表格 15–16px；来源/日期等辅助 13px |
| 7 | 横向溢出 | 0 | 表格 `.table-wrap{overflow-x:auto}`；390 无整页横溢 |

**新增 `card` 页型**（`deploy/first_screen_check.py`）：

```python
{
    "name": "card", "type": "content",
    "paths": ["card/acetaminophen.html", "card/tirzepatide.html"],
    "primary": [("first-action", "main a[href*='drug/']", False, None)],
    "items": [".idcard-table tbody tr", ".idcard-block li"],
    "items_min": 5,
    "must_not_cover": ["main h1", ".idcard-table thead"],
},
```

并在 `READY_NEED`（当前 758 行）加 `"card": "none"`（卡页不依赖筛选初始化）。

### 5.2 Lighthouse 四页（+ 卡页作为第五页）

- 现本机 Lighthouse CLI 未预装（`docs/网站优化流程.md` §4）；用 Chrome DevTools Lighthouse 移动端或 PageSpeed Insights。
- 四页：首页、成分页 `drug/acetaminophen.html`、名字页（`name/tylenol.html`）、`atc/N02BE01.html`；**额外**测 `card/acetaminophen.html`（不作发布阻塞，但记录四项分数）。
- 门槛：Performance / Accessibility / Best Practices / SEO **各 ≥90**；LCP <2.5 s、CLS <0.1、TBT <200 ms。未达标写「差距 + 原因 + 跟进任务号」，不静默放行。
- 改前基线必须先重建（同 §5.1）；新卡页的 a11y 重点：`aria-sort` 唯一、表头 `<th scope>`、dialog `aria-labelledby`、关闭按钮可聚焦。

### 5.3 体积预算（按现测 dist 1,305,436,320 B 计算）

| 项 | 预算 | 本方案 |
|---|---|---|
| 单页卡 HTML | ≤50 KB raw | 目标 **≤20 KB**，硬上限 22 KB（超过就砍行/cap） |
| 单页 `?s=` 壳 | ≤50 KB raw | ≤10 KB（不含共享 CSS/JS） |
| 卡片 JSON（Top 2000） | — | **≈1.74 MB raw**（实测 201–2000 = 1.566 MB + Top 200 ≈0.17 MB） |
| 200 张卡 HTML | ≤4.4 MB（22 KB×200） | **≤4.4 MB** |
| **总增量** | **≤+0.5% = 6,527,181 B（6.53 MB）** | **≈5.6–6.1 MB（+0.43%–+0.47%）** |
| `core.json` | 不变 | 不变（不新增检索索引/字段） |
| sitemap | +200 URL | 当前旧产物 75,609；重建后 +200（以现查为准） |
| 文件数 | 无硬门槛（现 137,348） | +200 HTML +2,000 JSON +1 JS ≈ **+2,201** |

> 注意：现 dist **已经 1.245 GB**，超过 `docs/网站优化流程.md` §3.2 的旧「dist ≤900 MiB」门槛（该门槛是 GitHub Pages 时代，现走 R2）。本报告按 AGENTS §5 / 队列的 **+0.5%** 现测口径计算；不等于总容量合规。若 Lead 认为总容量也要管，S4 不应背这个历史账，另开任务。

### 5.4 键盘可达 + 无横向溢出

- **卡页：** Tab 顺序 = skip link → 返回搜索 → 搜索框 → 六块链接 → 排序按钮；排序按钮 Enter/Space 触发，`aria-sort` 只在一列，`role="status"` 播报「Sorted by …」；排序后焦点留在按钮；表格外层 `tabindex=0` + `role=region` + `aria-labelledby`（窄屏可横滚）。
- **筛选 dialog：** 打开后焦点在第一个 chip/关闭按钮；Tab 在 dialog 内循环（原生 modal）；Esc 关闭；关闭后焦点回触发按钮；打开时背景不滚；内容超 `max-height` 时 dialog 内部滚动（不做 JS 翻转）。
- **`?s=` 壳：** 非法/空 sid 时显示可见错误（不只颜色）+ `:user-invalid`；错误文案通过 `aria-describedby` 关联。
- **390/768/1440 实测：** `document.scrollingElement.scrollWidth === innerWidth`；dialog 右缘 ≤ 视口；无 `position:fixed` 遮挡正文。

### 5.5 i18n（七语，FAIL 0）

- 当前启用语言：**en / es / zh / zh-Hant / fr / ko / ja**（`data/languages.json` 2026-11-20，ja 为 v0.16.0 新增；`deploy/i18n_check.py` 已是七语口径）。
- 30 个新键 × 7 语 = 210 个值；键集 684 → **714/714**。
- 门槛：
  - `& $py deploy/i18n_check.py` → **FAIL 0**，WARN 不高于基线 26；`ja` 与 `en` 键集一致；无伪翻译（值==en 且不在白名单）。
  - `site/build.py` 的 `_assert_i18n_complete()` / `_assert_i18n_rules()` 通过（缺键直接中止构建）。
  - `tests/trilingual/run_tests.py` 通过；三语各抽 3 条检索（含新卡页链接）不 404。
- 文案边界：卡页只做身份对应；`card.warn.note` / `warn.no_advice` 必须有；不出现「可替代」「按 mg 换算」等措辞（实现后用 `grep` 抽查）。

### 5.6 其它风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 严格「不新增索引」被解释为「不新增任何数据文件」 | `?s=` 只能重定向，tirzepatide 样本出不了卡 | 本报告把两种方案与体积都列出，请 Lead 拍板（推荐 1.74 MB JSON；不采用全量 6.3 MB） |
| R4 警示无 substance/key 关联 | 泰诺林警示无法自动挂到 acetaminophen 卡 | MVP 链 `/warn.html#w-tylenol-vs-tainuo` + 家族说明；另登记 `dose_warning.key_id` 写库任务 |
| 泰诺林不是成分 | `?s=泰诺林` 无卡 | 显示 `card.name_hint` + 链 `/name/泰诺林.html`；验收从名字页进卡 |
| Top 200 有 15 个单方极少的成分 | 卡片内容偏薄、SEO 价值低 | 按需求保留；卡片加「多数为复方」中性说明；不硬编码白名单 |
| Python / JS 两套渲染器 | 内容漂移 | 共用 JSON schema；构建期用 3 个 sid（acetaminophen/tirzepatide/泰诺林→acetaminophen）对比静态卡与 JSON 渲染的关键文本/数字 |
| `site/dist` 是旧 v0.15.0 | 基线污染 | §5.1 先重建 `.tmp/s4-baseline` |
| `build.py` 行号漂移（task-1 ja +715 行） | 施工找错位置 | 以函数名/注释锚点为准；本表行号只作近似 |
| R2 上 2,000 个 JSON 的 404/缓存 | `?s=` 首次加载失败 | `?v=BUILD_V` 防旧缓存；404 → 回退 `/drug/<sid>.html`；`sync_r2.ps1` 后抽 3 个 JSON 直链验证 |
| 确定性构建 | 两次构建不一致 | 卡片 JSON 按 sid 排序、无时间戳；HTML 走现有 `page()`；跑 `deploy/check_build_determinism.py` / 两次构建 diff |
| 公开口径 | 卡片数字与 README/About 不一致 | 卡页数字全来自 DB 现查；README/CHANGELOG 不改（本版只加页面）；发布前 `db/check_data.py` |

### 5.7 发布前最低验证清单（S4 专属）

1. `site/build.py` 到 `== done ==`；日志含 `card pages: 200 / card data: 2,000 / card json: 1.7 MB`。
2. 抽查 3 张卡：`/card/acetaminophen.html`、`/card/tirzepatide.html` 不存在（rank 526）→ `/card.html?s=tirzepatide` 出卡；`/name/泰诺林.html` → `/card/acetaminophen.html` 链接有效。
3. `?s=` 对 rank >2000 的成分回退 `/drug/<sid>.html`（抽 1 个）。
4. sitemap 含 200 个 `/card/<sid>.html`，不含 `card.html`；robots 正常。
5. 首屏守卫 before×2 / after×2 + `--baseline` 0 FAIL；Lighthouse 四页 + 卡页记录。
6. `deploy/i18n_check.py` FAIL 0；`tests/trilingual/run_tests.py` 通过；`db/check_data.py` 产品数 594,781 不变。
7. 390/768/1440 键盘走查 + dialog Esc/焦点回收 + 无横向溢出。
8. `site/dist` 两次构建逐字节一致（或 `check_build_determinism.py` 通过）。

---

## 附录 A：新增 i18n 键（30 个 × 七语）

> 键名与现有 `card.packs` 同前缀；`{n}` / `{total}` 占位符沿用 `_subst_placeholders`。法语避免与英文同形（如 `card.src.licence` 用「Licence d'utilisation」）。

| key | en | zh | es |
|---|---|---|---|
| card.title | One-drug identity card | 一药对照卡 | Ficha de identidad del principio activo |
| card.cta | View identity card | 查看一药对照卡 | Ver ficha de identidad |
| card.sec.names | Names and market spellings | 名称与各市场写法 | Nombres y grafías por mercado |
| card.sec.comp | Ingredient composition (salt / base) | 成分组合（盐型 / 碱基） | Composición (sal / base) |
| card.sec.forms | Dosage forms, strengths, release | 剂型、规格、释放机制 | Formas, concentraciones y liberación |
| card.sec.markets | Market coverage | 市场覆盖 | Cobertura por mercado |
| card.sec.warn | Same name, different drug / not interchangeable | 同名不同药与不可互换警示 | Mismo nombre, otro medicamento / no intercambiables |
| card.sec.src | Sources, licences, data as of | 来源、许可、数据截止 | Fuentes, licencias y fecha de los datos |
| card.names.market | Market | 市场 | Mercado |
| card.names.trade | Registered trade name | 注册商品名 | Nombre comercial registrado |
| card.names.count | Records | 记录 | Registros |
| card.comp.base | Base (no salt) | 碱基（无盐） | Base (sin sal) |
| card.comp.basis | Strength basis | 强度基准 | Base de la concentración |
| card.comp.combos | Combination products containing this ingredient | 含此成分的复方产品 | Productos combinados con este principio |
| card.markets.single | Single-ingredient products | 仅含此成分的产品 | Productos de un solo principio |
| card.markets.combo | Combination products | 复方产品 | Productos combinados |
| card.warn.collision | Names also used for other ingredients | 同时指向其他成分的名字 | Nombres usados también para otros principios |
| card.warn.release | Same ingredient, different release — not interchangeable | 同成分不同释放机制，不能互换 | Mismo principio, liberación distinta: no intercambiables |
| card.warn.published | Published warnings for this ingredient | 与该成分相关的已发布警示 | Alertas publicadas para este principio |
| card.warn.none | No published same-name warning is linked to this ingredient. | 该成分暂无已发布的同名警示。 | No hay alertas publicadas de mismo nombre para este principio. |
| card.warn.note | Identity only: no advice, no dose conversion, no claim that two products can be substituted. | 只做身份对应：不给用药建议、不做剂量换算、不判断两药能否互换。 | Solo identidad: sin consejo, sin conversión de dosis y sin afirmar que dos productos sean sustituibles. |
| card.src.licence | Licence | 许可 | Licencia |
| card.src.asof | Data as of | 数据截止 | Datos a fecha de |
| card.not_ready | This substance has no pre-rendered card yet. | 该成分暂无预渲染卡页。 | Este principio aún no tiene ficha pregenerada. |
| card.open_full | Open the full ingredient page | 打开完整成分页 | Abrir la página completa del principio |
| card.loading | Loading card… | 正在加载对照卡… | Cargando ficha… |
| card.error | Could not load the card data. | 对照卡数据加载失败。 | No se pudieron cargar los datos de la ficha. |
| card.cap | Showing {n} of {total} | 展示 {n} 项，共 {total} 项 | Mostrando {n} de {total} |
| card.family | Brand family note | 品牌家族说明 | Nota de la familia de marcas |
| card.name_hint | This is a name, not a substance ID. Open the name page to see which ingredients it points to. | 这是名称，不是规范成分 ID；请先打开名字页看它指向哪些成分。 | Esto es un nombre, no un ID de principio; abre la página del nombre para ver a qué principios apunta. |

| key | zh-Hant | fr | ko | ja |
|---|---|---|---|---|
| card.title | 一藥對照卡 | Fiche d'identité du principe actif | 성분 신원 카드 | 成分アイデンティティカード |
| card.cta | 查看一藥對照卡 | Voir la fiche d'identité | 신원 카드 보기 | アイデンティティカードを見る |
| card.sec.names | 名稱與各市場寫法 | Noms et graphies par marché | 이름과 시장별 표기 | 名称と市場ごとの表記 |
| card.sec.comp | 成分組合（鹽型 / 鹼基） | Composition (sel / base) | 성분 조성(염 / 염기) | 成分構成（塩 / 塩基） |
| card.sec.forms | 劑型、規格、釋放機制 | Formes, dosages et libération | 제형, 함량, 방출 | 剤形・規格・放出 |
| card.sec.markets | 市場覆蓋 | Couverture par marché | 시장 커버리지 | 市場カバレッジ |
| card.sec.warn | 同名不同藥與不可互換警示 | Même nom, autre médicament / non interchangeables | 같은 이름, 다른 약 / 호환 불가 | 同名異薬・互換不可 |
| card.sec.src | 來源、授權、資料截止 | Sources, licences et date des données | 출처, 라이선스, 데이터 기준일 | 出典・ライセンス・データ基準日 |
| card.names.market | 市場 | Marché | 시장 | 市場 |
| card.names.trade | 註冊商品名 | Nom commercial enregistré | 등록 상품명 | 登録商品名 |
| card.names.count | 紀錄 | Enregistrements | 기록 | 記録 |
| card.comp.base | 鹼基（無鹽） | Base (sans sel) | 염기(염 없음) | 塩基（塩なし） |
| card.comp.basis | 強度基準 | Base du dosage | 함량 기준 | 含量基準 |
| card.comp.combos | 含此成分的複方產品 | Produits combinés contenant ce principe | 이 성분을 포함한 복합제 | この成分を含む配合剤 |
| card.markets.single | 僅含此成分的產品 | Produits à principe unique | 단일 성분 제품 | 単一成分製品 |
| card.markets.combo | 複方產品 | Produits combinés | 복합제 | 配合剤 |
| card.warn.collision | 同時指向其他成分的名稱 | Noms aussi utilisés pour d'autres principes | 다른 성분에도 쓰이는 이름 | 他の成分にも使われる名称 |
| card.warn.release | 同成分不同釋放機制，不能互換 | Même principe, libération différente : non interchangeables | 같은 성분, 다른 방출 — 호환 불가 | 同一成分でも放出が異なるため互換不可 |
| card.warn.published | 與該成分相關的已發布警語 | Alertes publiées pour ce principe | 이 성분 관련 게시된 경고 | この成分に関する公開警告 |
| card.warn.none | 該成分暫無已發布的同名警語。 | Aucune alerte publiée de même nom pour ce principe. | 이 성분에는 게시된 동명 경고가 없습니다. | この成分に公開済みの同名警告はありません。 |
| card.warn.note | 只做身分對應：不給用藥建議、不做劑量換算、不判斷兩藥能否互換。 | Identité uniquement : aucun conseil, aucune conversion de dose, aucune affirmation de substitution. | 정체성 정보만: 복약 조언, 용량 환산, 대체 가능성 판단은 하지 않습니다. | 同一性のみ：服薬助言・用量換算・代替可否の判断は行いません。 |
| card.src.licence | 授權 | Licence d'utilisation | 라이선스 | ライセンス |
| card.src.asof | 資料截止 | Données au | 데이터 기준일 | データ基準日 |
| card.not_ready | 該成分暫無預先產生的卡頁。 | Ce principe n'a pas encore de fiche pré-générée. | 이 성분은 아직 미리 생성된 카드가 없습니다. | この成分には事前生成カードがまだありません。 |
| card.open_full | 開啟完整成分頁 | Ouvrir la page complète du principe | 전체 성분 페이지 열기 | 成分ページ全体を開く |
| card.loading | 正在載入對照卡… | Chargement de la fiche… | 카드 불러오는 중… | カードを読み込み中… |
| card.error | 對照卡資料載入失敗。 | Impossible de charger les données de la fiche. | 카드 데이터를 불러오지 못했습니다. | カードデータを読み込めませんでした。 |
| card.cap | 顯示 {n} 項，共 {total} 項 | Affichage de {n} sur {total} | {total}개 중 {n}개 표시 | {total} 件中 {n} 件を表示 |
| card.family | 品牌家族說明 | Note sur la famille de marques | 브랜드 계열 설명 | ブランドファミリーの説明 |
| card.name_hint | 這是名稱，不是規範成分 ID；請先開啟名字頁看它指向哪些成分。 | Ceci est un nom, pas un ID de principe ; ouvrez la page du nom pour voir les principes visés. | 이것은 이름이며 성분 ID가 아닙니다. 이름 페이지에서 어떤 성분을 가리키는지 확인하세요. | これは名称であり成分 ID ではありません。名称ページでどの成分を指すか確認してください。 |

## 附录 B：`tirzepatide` 卡片 JSON（实测 1,014 B，供实现对照）

```json
{"id":"tirzepatide","e":"Tirzepatide","z":"替尔泊肽","a":"A10BX16","n":320,"s":320,"m":15,
"mk":[["CZ",60,60],["LV",60,60],["US",54,54],["CA",24,24],["ES",21,21],["AU",19,19],["SG",18,18],["TW",18,18]],
"nm":[["CZ","MOUNJARO"],["CZ","MOUNJARO INJECTION 10MG/0.5ML"],["LV","MOUNJARO"],["LV","MOUNJARO INJECTION 10MG/0.5ML"],["US","MOUNJARO"],["US","MOUNJARO INJECTION 10MG/0.5ML"],["CA","MOUNJARO"],["CA","MOUNJARO INJECTION 10MG/0.5ML"],["ES","MOUNJARO KWIKPEN PRECARGADA"],["ES","MOUNJARO"],["AU","MOUNJARO KwikPen tirzepatide 12.5 mg/mL solution for injection multidose pre-filled pen"],["AU","MOUNJARO KwikPen tirzepatide 16.67 mg/mL solution for injection multidose pre-filled pen"]],
"v":[["","","","","unknown",1.0,"unknown"]],
"f":[["injection","none"],["liquid","none"],[null,"none"]],
"sp":[["2.5","mg","1.0","dose"]],
"c":[],"w":[],
"src":[["zva_lv_register","2026-11-11"],["sukl_dlp","2026-11-01"],["openfda_ndc","2026-10-23"],["hc_dpd","2026-10-23"]]}
```

> 说明：`n=320` 是全局产品数（不是 `mk` 截断求和）；`c`/`w` 空表示现查无 collision / 无已发布 `dose_warning`；`v` 的 `unknown` 是数据记录，不是结论。

## 附录 C：证据与复跑命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
# 库快照
Get-Item data\drugs.db | Select-Object Length,LastWriteTime
Get-FileHash data\drugs.db -Algorithm SHA256
# Top 200（把 §3.2 SQL 替换进 -c）
& $py db/q.py "SELECT COUNT(*) FROM product"
# 三样本计数
& $py db/q.py "SELECT COUNT(DISTINCT product_id) FROM product_component pc JOIN variant v ON v.variant_id=pc.variant_id WHERE v.substance_id='acetaminophen'"
# 卡页/分片检查（实现后）
Test-Path site\dist\card\acetaminophen.html
Test-Path site\dist\data\card\tirzepatide.json
Select-String site\dist\sitemap.xml -Pattern '/card/' | Measure-Object
```

- MWG 实取：`DISABLE_TELEMETRY=1 & $node $mwg retrieve "dialog,light-dismiss-a-dialog,platform-controls-dismiss-dialog,prevent-page-scroll-under-modal-dialog,size-aware-styling,sortable-table,responsive-table,defer-rendering-heavy-content,carousel,validate-input-after-interaction"` → 82.2 KB / 1,519 行。
- 外部候选：npm registry `latest`（2026-11-19 抓取）与 unpkg 入口文件实测；tablesort 3,247 B / a11y-dialog 23,820 B（unminified）/ table-core 7,250 B；unpackedSize 见 §1.2。
- 报告数字均为 2026-11-20 现查；若 `data/drugs.db` 在实现前被重跑，Top 200 / 样本数字需重查（不要照抄本报告）。
