# R5「未公开规格」块计数口径修正（v0.13.5 / 队列 T42）

- **日期**：2026-11-17 · 工位 page-slim · 任务 task-5
- **改的文件**：`site/build.py`（唯一实现文件）、`reports/2026-11-17-r5-*.py`（探针 / 对照脚本）
- **没改**：`site/dist`（构建全程 `SITE_OUT=.tmp/dist-r5`）、库（只读 `mode=ro`）、`lib/`、`deploy/`、`collision` 视图
- **产物**：`.tmp/dist-r5`（构建到 `== done ==`）+ `.tmp/dist-r5b`（第二次构建，用于确定性对照）

## 1. 结论（先看这四行）

| 项 | 修前（v0.13.4 产物） | 修后（`.tmp/dist-r5`，真浏览器实测） |
|---|---|---|
| tirzepatide · MX 块头 | `0 shown of 0` | `0 shown · 1 without a stated strength`（`data-und="1"`；中文「展示 0 个 · 1 条未公开规格」） |
| tirzepatide · MX 未公开段 | `1 records · 0 manufacturers`｜chip `Mounjaro ×14` | `1 records · 1 manufacturers`｜chip `Mounjaro`（×1 不写；中文「1 个记录 · 1 个厂家」） |
| tirzepatide · EU 块 | 同上（`×14`、0 个厂家） | 同上（1 记录 · 1 厂家） |
| tirzepatide · HK 块 | `0 shown of 0`｜`6 records · 0 manufacturers`｜chip `… 2.5mg/0.6ml ×72` | `0 shown · 6 without a stated strength`｜`6 records · 1 manufacturers`｜chip `×6` |

HK 的期望值按 SQL 现查订正：**HK 6 产品 / 1 MAH（ELI LILLY ASIA, INC.）**，不是 0 个厂家
（task 描述里「HK 0 个厂家」是错的口径，Lead 已确认按现查为准）。

## 2. 三处根因与修法

| # | 根因（修前） | 修法（`site/build.py`） |
|---|---|---|
| 1 | `×14 / ×72` 是 **名称拼写变体行数**：`und["names"][label] += 1` 在 `for key_id, raw in traded:` 里按 `product_name × name_variant` 的每一行累加（MX 1 产品 14 行、HK 6 产品各 12 行） | `und_meta[mk]` 改存 **pid 集合**（`name_pids` / `mah_pids`），×N = `len(pids)`；×1 不渲染（与名称位 MAH 桶的 ×N 规则一致） |
| 2 | 「0 个厂家」= `k_mah = len(mahs)`，而 `mahs` 只装「**无商品名**且落 MAH 桶」的厂家 → 有商品名的记录全被漏掉 | 新增 `und_meta[mk]["mahs"]`：**该块全部**未公开规格记录的 distinct MAH（`(mah or "").strip()` 非空），`k_mah = len(mahs)`；MAH 桶 chip 仍用 `mah_pids` 计 ×N |
| 3 | 块头 `shown_n / n_head` 只数结构化规格行 → 整块都没有规格的市场写出 `0 shown of 0` | `n_head == 0 且 n_rec > 0` 时改用新模板 `drug.spec_count_und`（`{shown}` + `{u}`），并给 `.mkspec` 加 `data-und="{n_rec}"`；有规格的块仍用原 `drug.spec_count`，行为零变化 |

配套：`drug.spec_count_und` 五语齐（`UI_I18N` 的 en/es/zh/zh-Hant + `FR_I18N` 的 fr）；
4 处会重写块头文本的 JS（i18n.js 的 `apply()`、`initListView.applyFormFilter`、
`initListFilters.sync`、boot.js `_mkblock_js().lfpSync`）都补了 `.replace('{u}', data-und)`，
所以切语言 / 点剂型 chip / 输入规格筛选之后不会露出 `{u}` 字面量。

作用面（SQL 现查，与 build.py 同口径）：有未公开规格记录的「成分 × 市场」块 **12,098** 个，
其中整块没有结构化规格（会从 `0 shown of 0` 换文案）**8,165** 块、分布在 **5,991** 个成分页。

## 3. 20 页 / 97 块逐条对照（页面数字 vs SQL 现查）

渲染：`$py reports/2026-11-17-r5-undisclosed-probe.py .tmp/r5-after20 <20 个 sid>`
对照：`$py reports/2026-11-17-r5-verify.py .tmp/r5-after20 <20 个 sid>` → **块数 97 · 不一致 0**。

SQL 口径（与页面同一套过滤，脚本里的 `VISIBLE` 常量）：

```sql
WITH u AS (
  SELECT COALESCE(p.country, p.region) AS mk, p.product_id AS pid, p.mah, pc.strength_value AS sv
  FROM product p
  JOIN product_component pc ON pc.product_id = p.product_id
  JOIN variant v ON v.variant_id = pc.variant_id
  JOIN substance s ON s.substance_id = v.substance_id
  WHERE s.substance_id = ?                                    -- 页面 = 一个成分
    AND (p.status = 'active'
         OR (COALESCE(p.status,'') IN ('','unknown')
             AND COALESCE(p.country,p.region) IN ('HK','AU','EU')))
), und AS (SELECT DISTINCT pid, mk, mah FROM u WHERE sv IS NULL)   -- 未公开规格
SELECT mk, COUNT(DISTINCT pid)                                  -- 记录数
FROM und GROUP BY mk;
-- 厂家数：COUNT(DISTINCT mah) WHERE TRIM(COALESCE(mah,'')) <> ''
-- 名字 ×N：未公开规格记录里「同一 name_key 的 distinct product_id」
```

对照表（节选；`cap` = 该组超过 8 个键，页面按设计只列前 8 个，multiset 不比）：

| 页面 | 市场 | 记录 页面/SQL | 厂家 页面/SQL | 名字 ×N | 块头模板 |
|---|---|---|---|---|---|
| tirzepatide | AU | 1 / 1 | 0 / 0 | ok | drug.spec_count |
| tirzepatide | HK | 6 / 6 | 1 / 1 | ok | drug.spec_count_und |
| tirzepatide | MX | 1 / 1 | 1 / 1 | ok | drug.spec_count_und |
| tirzepatide | EU | 1 / 1 | 1 / 1 | ok | drug.spec_count_und |
| acetaminophen | HK | 693 / 693 | 82 / 82 | cap | drug.spec_count_und |
| epinephrine | MX | 7 / 7 | 4 / 4 | ok | drug.spec_count_und |
| sodium-chloride | TW | 315 / 315 | 39 / 39 | cap | drug.spec_count |
| onasemnogene-abeparvovec | CZ | 38 / 38 | 1 / 1 | ok | drug.spec_count_und |
| heparin | US | 122 / 122 | 25 / 25 | ok | drug.spec_count_und |
| dexamethasone | HK | 94 / 94 | 37 / 37 | cap | drug.spec_count_und |
| amlodipine | HK | 141 / 141 | 44 / 44 | cap | drug.spec_count_und |
| betamethasone | GB | 286 / 286 | 43 / 43 | cap | drug.spec_count |
| tisagenlecleucel | AU | 1 / 1 | 0 / 0 | ok | drug.spec_count_und |
| filgrastim | EU | 7 / 7 | 7 / 7 | ok | drug.spec_count_und |
| …（共 97 块） | | **全部一致** | **全部一致** | 0 处 DIFF | 全部符合规则 |

20 页清单：tirzepatide、acetaminophen、epinephrine、sodium-chloride、onasemnogene-abeparvovec、
ascorbic-acid、estradiol、insulin-glargine、aspirin、diclofenac、heparin、buprenorphine、zinc、
dexamethasone、amlodipine、hydrocortisone、betamethasone、tisagenlecleucel、filgrastim、carbidopa。

判定规则（脚本硬校验，不靠人眼）：① 记录数 = SQL distinct pid；② 厂家数 = SQL distinct 非空 MAH；
③ 未达 8 键上限时 chip 的 ×N 多重集合 = SQL 每 name_key 的 distinct pid（含「无商品名」桶）；
④ `0 shown` 的块必须用 `drug.spec_count_und` 且 `data-und` = 记录数，有规格的块必须是
`drug.spec_count` 且不带 `data-und`；⑤ 不得残留 `{shown}/{n}/{u}`、`0 shown of 0`、`__mah__` / `__no_trade__`。

## 4. i18n（五语同步）

`$py deploy/i18n_check.py` → **FAIL 0**（WARN 2 = 既有的 `form.kit` / `form.gas` 西语同形可疑，与本改动无关）。
构建期 `_assert_i18n_complete()` 通过：**658 键 × 5 语言**（zh-Hant 回落 0 个已登记 key）。

| 语言 | `drug.spec_count_und` | 浏览器实测（tirzepatide · HK 块） |
|---|---|---|
| en | `{shown} shown · {u} without a stated strength` | `0 shown · 6 without a stated strength` |
| es | `{shown} mostradas · {u} sin concentración indicada` | `0 mostradas · 6 sin concentración indicada` |
| zh | `展示 {shown} 个 · {u} 条未公开规格` | `展示 0 个 · 6 条未公开规格` |
| zh-Hant | `顯示 {shown} 個 · {u} 條未公開規格` | `顯示 0 個 · 6 條未公開規格` |
| fr | `{shown} affichées · {u} sans dosage indiqué` | `0 affichées · 6 sans dosage indiqué` |

## 5. 构建与确定性

| 项 | 数字 |
|---|---|
| 全量构建 | `SITE_OUT=.tmp/dist-r5` → **`== done ==`**（exit 0，4m29s） |
| 产物 | **137,323 文件 / 1,239,848,571 B**（1,182.4 MiB）· 0 字节文件 **0** · 成分页 13,435 / 名字页 91,078 / 组合页 7,462 / 厂家页 15,213 |
| 索引 | `core.json` **40.2 MB**（226,631 keys）· 124 shards 105.8 MB · 51 detail 桶 63.9 MB · sitemap **75,585 URL** |
| 与 v0.13.4（`site/dist`）对比 | 文件数相同（137,323）；体积 1,182.9 → 1,182.4 MiB（-0.5 MiB，chip 少写 `×1` 的净效果） |
| 确定性 | 两次独立构建 `.tmp/dist-r5` vs `.tmp/dist-r5b` → **逐字节相同**（137,323 文件，内容不同 0，`deploy/check_build_determinism.py`） |
| 改动面（新 vs `site/dist`，归一 boot/style 内容哈希后） | 8,915 完全相同 · 121,452 只因 `boot.<hash>.js` 改名 · **6,955 实质变化**：drug 6,937 + assets 9（boot/i18n/app/atc4 的 `?v=` 与新增键）+ index/语言落地页 5（内联 i18n 字典）+ data 3（manifest/datapackage 的构建号） |

> 6,937 与「有未公开规格块的 6,964 页」差 27 页：这些页的计数恰好没变（产品各 1 个名称变体、无厂家口径差），
> 渲染结果逐字节相同 —— 属预期，不是漏改。

## 6. 首屏守卫（改前 ×2 / 改后 ×2 取包络）

命令：`deploy/first_screen_check.py --dist <dir> --json …`（改后用 `--baseline` 比前一轮）。
**四次都是 24 次扫描；`--baseline` 退化 0 项**。

成分页（drug）逐视口，改前两次与改后两次**完全相同**：

| 视口 | AFCR | 首屏条目 | chrome | 悬浮 | 正文/辅助 | 横向溢出 |
|---|---|---|---|---|---|---|
| 390x844 | 0.93 | 5.5 | 0.14 | 0.068 | 16 / 13px | 否 |
| 768x1024 | 1.01 | 5.5 | 0.11 | 0.000 | 16 / 13px | 否 |
| 1440x900 | 1.00 | 4.5 | 0.07 | 0.000 | 16 / 13px | 否 |
| 2560x1440 | 1.00 | 13.5 | 0.05 | 0.000 | 16 / 13px | 否 |

未达标项 3 个，**改前就存在**（drug 1440x900 条目 4.5 < 5、coverage 390x844 1.5、coverage 768x1024 3.5），
改后数字一字不差 → 本改动不引入任何首屏退化。

## 7. 整站扫描 + 真浏览器验证

整站（`.tmp/dist-r5`，13,435 个成分页逐块检查）：

- `spec_count_und` 块 **8,165** 个（= SQL 预测 8,165，一一对上）、普通 `spec_count` 块 **23,301** 个；
- **0** 处 `0 shown of 0`；**0** 处残留 `{u}`；**0** 处 `spec_count_und` 缺 `data-und` / `data-und` 与文本不一致；
- 五语资产 `assets/i18n.{en,es,zh,zh-Hant,fr}.js` 都含新键。

真浏览器（Chrome 打开 `http://127.0.0.1:8123/` 服务的 `.tmp/dist-r5`）：

| 操作 | 结果 |
|---|---|
| 打开 `/drug/tirzepatide.html`（zh） | HK「展示 0 个 · 6 条未公开规格」、MX/EU「展示 0 个 · 1 条未公开规格」、AU「展示 12 个，共 12 个」；`{u}` 未出现 |
| 点剂型 chip「注射剂」（`?form=injection`） | 三个未公开块文本不变、`data-shown=0`；普通块更新为「展示 6 个，共 6 个」；无 `{u}` |
| 展开筛选面板、输入规格 `2.5` | CZ「展示 2 个，共 6 个」、US「展示 3 个，共 12 个」；未公开块文本完整；无 `{u}` |
| 切 es / zh-Hant / fr / en | 块头分别「0 mostradas · 6 sin concentración indicada」/「顯示 0 個 · 6 條未公開規格」/「0 affichées · 6 sans dosage indiqué」/「0 shown · 6 without a stated strength」；zh-Hant 隐藏语言块后可见「6 個記錄 · 1 個廠商」 |
| 控制台 | 0 error（唯一 warning 是 goatcounter 在 localhost 不计数，与本改动无关） |

## 8. 待办 / 边界（明确没做）

- [x] 全量构建 `.tmp/dist-r5` 到 `== done ==`（4m29s）
- [x] 改后首屏守卫 + `--baseline`（改前×2 / 改后×2，退化 0）
- [x] 确定性（两次构建逐字节相同）
- [x] 真浏览器五语 + 剂型 chip + 规格筛选
- [ ] **Lead 收尾**：CHANGELOG v0.13.5 一节（建议 1 条：「未公开规格块按记录数计，厂家数不再显示 0，块头不再出现 0/0」）→
      `site/build.py` 全量构建到 `site/dist` → `sync_r2.ps1` → `verify_live`；工位不 commit / 不发布。

已知口径边界（不是本次 bug，**没改**，留给后续需求队列）：

1. 展开态「还有 N 个（K 个厂家）」里 `K` 仍只数「仅厂家」桶（无商品名的厂家），有商品名的市场该括号可能显示 0
   —— 同一族口径问题，但不在 R5 的三条根因里（本次只修折叠摘要与 chip）；
2. 块头「1 records」的单复数（`drug.records` 只有一个词形）是既有写法，五语都只修数字口径不动措辞；
3. 库里 30 条 `product.mah` 是非 NULL 空白串，页面按「无厂家」处理（与 `(mah or "").strip()` 一致），
   而裸 `COUNT(DISTINCT mah)` 会把它算 1 个 —— 对照脚本统一用 `TRIM(COALESCE(mah,'')) <> ''` 口径。

## 9. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 单页/多页探针（写 .tmp，不碰 site/dist）
& $py reports/2026-11-17-r5-undisclosed-probe.py .tmp/r5-after20 tirzepatide acetaminophen …
# 页面数字 vs SQL 现查
& $py reports/2026-11-17-r5-verify.py .tmp/r5-after20 tirzepatide acetaminophen …
# 全量构建（并行工位纪律：构建窗口内跑）
$env:SITE_OUT = "$PWD\.tmp\dist-r5"; & $py site/build.py     # 等 == done ==
# 确定性与改动面
& $py deploy/check_build_determinism.py .tmp/dist-r5 .tmp/dist-r5b
# 首屏（改前/改后各两次，--baseline 比退化）
& $py deploy/first_screen_check.py --dist site/dist --json .tmp/first-screen/r5-before.json
& $py deploy/first_screen_check.py --dist .tmp/dist-r5 --json .tmp/first-screen/r5-after1.json --baseline .tmp/first-screen/r5-before.json
```
