# ATC 类目页状态角标：为什么四色混杂 + 补丁规格

- 日期：2026-11-10（北京时间；调查发生在 2026-11-09 21:00Z 前后）
- 范围：**只读调查 + 出规格**。没有跑 `site/build.py`、没有写 `data/drugs.db`、没有改 `site/build.py`（写入权在另一会话）。
- 数据：`data/drugs.db` 现查（站点版本 v0.10.1）；代码行号以 v0.10.1 的 `site/build.py` 为准，落地后会移位。
- 证据图：[现网 375px 实测](../docs/img/atc-r06a-375px-20261110.png)（`/atc/R06A.html?lang=zh`）｜[现状 vs 方案 A 预演（390px）](../docs/img/atc-status-badges-preview-20261110.png)
  （预演页是独立 HTML，非站点产物；图里 ③ 区的文案写「都回到 2 行」，实际西替利嗪那行是 3 行——逐行实测见 §3.1 表）

---

## 0. 结论先行

1. **现象不是「同一状态重复出现」，而是「最多 4 个不同状态各挂一枚徽章，且不写国家」。**
   逐行验证：一行里同一状态最多出现 1 次（抽样 29 页 1,139 行，重复 0 次）。用户看到的「重复」来自**名字**：每个盐型名各贴一次「暂无中文名」，一行最多 5 次。
2. **量化**：以 ATC 页的「成分行」（盐型归并后的 base 成分）计，**2,693 个成分出现 ≥2 种状态**（占 49.3%），其中 **656 个四种状态全齐**；跨全部 1,154 个 ATC 页共 **22,215 行成员，10,877 行（49.0%）≥2 种状态**。
3. **四色混杂的真正原因是数据口径**：只有 CA / ES / MX 的登记库带「停售 / 撤市」列，AU / HK 无状态列（记 unknown），CN / US / GB / TW / SG 只有「在售」一种取值。所以一行四色 = 「ES/MX 的撤市 + CA/ES/MX 的停售 + 十个市场的在售 + AU/HK 的未知」被压平成一排。
4. **推荐**：方案 A + 紧凑样式 —— **一个状态一枚徽章，徽章内直接写「该状态记录在哪些市场」**（`在售 US·GB·CA·AU·SG·CN·ES·MX·TW`），市场码按 `COUNTRY_PRIORITY` 固定序、**不截断、不用 `title`、不做多数票**；市场码 11px、内边距收紧。390px 实测：四状态行 52–78px（平均 +6.5px/行，最长一行 +26px = 多 1 行），信息零丢失。
5. **不需要「丢信息才能好看」**。唯一取舍：把现在 `title="318"` 里的**原始记录条数**从行内拿掉（触屏永远看不到、且「在售 318」会被读成「318 个市场」）。状态 × 市场矩阵 100% 保留；如果以后要显示条数，走「阶段 2：行尾可展开的按市场计数」（§3.4）。
6. 附带两个根因级发现（不在本次补丁内，但要排期）：**成分页把所有非 active 记录隐藏**（§7.3），`_sub_base_map` 的「极短 norm 磁铁桶」把不相关成分塞进同一行、一行挂 35 个盐型名（§5 P2）。

---

## 1. 复核：现状到底怎么了

### 1.1 渲染链路（代码事实）

ATC / 大类页的成员行由 `_atc_members_html()`（`site/build.py:9423-9461`）生成，状态角标只有 6 行：

```python
# site/build.py:9447-9453（现状）
badges = ""
for st in ("withdrawn", "discontinued", "active", "unknown"):
    n = it["statuses"].get(st, 0)
    if n:
        badges += (f'<span class="st-badge st-{st}" data-i18n="drug.status.{st}" '
                   f'title="{n}">{esc(I18N["en"].get("drug.status." + st, st))}</span>')
lis.append(f'<li>{label} {codes}{salt}{badges}</li>')
```

三个结构性缺陷：

| # | 缺陷 | 后果 |
|---|---|---|
| 1 | `_sub_status_map()`（9372-9386）只聚合到 `{status: 产品数}`，**国家在 SQL 里被 GROUP BY 掉** | 徽章不可能写市场 |
| 2 | 状态词是产品记录级的，而一行是**成分级**；不同市场的记录被合并 | 「在售」到底是哪个国家在售，无从判断 |
| 3 | 计数只放在 `title` | 触屏 / 键盘 / 读屏都拿不到；且计数单位（产品记录条数）没有解释 |

相关调用面只有 3 处，`_atc_members_html` 被 **ATC 页（1,154 页）+ 大类页（16 页）** 共用：
`build_atc_pages()`（9595-9669，调用 9648）、`build_category_pages()`（9696-9750，调用 9744）。
`_member_context()`（9389-9392）是两条链路的共同入口。另有 7619（名字页产品表）、9727（大类页 notice）也用到 `st-badge`，但那两处是**单条产品记录**，本来就带国家，不是本次问题。

### 1.2 数据事实：状态只存在于 3 个市场的登记库

`& $py db/q.py "SELECT country, SUM(status='active') …, COUNT(*) FROM product GROUP BY country"` 现查：

| 市场 | active | discontinued | withdrawn | unknown | 合计 | 说明 |
|---|---:|---:|---:|---:|---:|---|
| CN | 145,051 | 0 | 0 | 0 | 145,051 | 无状态列 |
| US | 110,179 | 0 | 0 | 0 | 110,179 | openFDA 只按 `listing_expiration_date` 判停售，现库 0 条过期 |
| GB | 61,051 | 0 | 0 | 0 | 61,051 | 无状态列 |
| AU | 7,160 | 0 | 0 | 37,634 | 44,794 | ARTG 无状态列 → unknown |
| CA | 14,519 | 29,323 | 5 | 0 | 43,847 | 有状态列（停售为主） |
| ES | 16,030 | 5,057 | 4,308 | 0 | 25,395 | 有状态列（撤市主战场） |
| TW | 16,457 | 0 | 0 | 0 | 16,457 | 无状态列 |
| HK | 0 | 0 | 0 | 13,935 | 13,935 | 只有名字/成分级记录 |
| MX | 1,772 | 4,044 | 699 | 4,363 | 10,878 | 混合 |
| SG | 5,511 | 0 | 0 | 0 | 5,511 | 无状态列 |

复核：`SELECT status, group_concat(country||':'||n,' ') FROM (SELECT status, country, COUNT(*) n FROM product WHERE status IN ('withdrawn','discontinued') GROUP BY 1,2) GROUP BY status`
→ `discontinued = CA:29323 ES:5057 MX:4044`，`withdrawn = CA:5 ES:4308 MX:699`。

**结论**：一行四色不是「这个药忽明忽暗」，而是「三本登记簿各说各话 + 六本没有状态列」。所以徽章**必须**带市场，否则它表达的是一个不存在的事实（「全站在售 + 全站撤市」）。

### 1.3 用户看到的「重复」其实是名字标记

现网 375px 实测（[图](../docs/img/atc-r06a-375px-20261110.png)）里，噪音最大的是这一串：

```
西替利嗪 R06AE07 盐型 Cetirizine Hydrochloride 暂无中文名  已停售 在售 状态未知
Azelastine 暂无中文名 R06AX11 …
```

来源是 `renderNames()`（`site/build.py:5575-5584`）：

```js
if(lang === 'zh') el.textContent = zh || (en + ' 暂无中文名');        // 硬编码中文
else if(lang === 'zh-Hant') el.textContent = zhh || (en + ' 暫無中文名');
```

每个 `.nm` 元素各加一次：主名 1 次 + 每个盐型 1 次 → 一行最多 5 次（§4）。

---

## 2. 量化

### 2.1 口径与命令

三套口径都要说清，否则数字对不上：

| 口径 | 定义 | 命令 |
|---|---|---|
| 成分（base） | `_sub_base_map()` 把盐型/水合物并回主成分后的一行 | 脚本，import `site/build.py` 纯函数（§7 复现） |
| 成分（substance） | 不并盐型，纯 SQL 可复核 | `db/q.py`（见下） |
| 页 × 行 | 同一成分会在 L1/L3/L4 页各出现一次 | 脚本 |

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/q.py "SELECT status, COUNT(*) FROM product GROUP BY status ORDER BY 2 DESC"
& $py db/q.py "SELECT n AS statuses_per_substance, COUNT(*) AS substances FROM (SELECT v.substance_id sid, COUNT(DISTINCT p.status) n FROM product p JOIN product_component pc ON pc.product_id=p.product_id JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id WHERE s.atc IS NOT NULL AND s.atc<>'' AND p.status IS NOT NULL AND p.status<>'' GROUP BY v.substance_id) GROUP BY n ORDER BY n"
```

### 2.2 有多少成分带 ≥2 种状态

| 状态种类数 | 成分数（base 口径） | 占比 | 成分数（substance 口径） |
|---:|---:|---:|---:|
| 1 | 2,768 | 50.7% | 2,954 |
| 2 | 1,075 | 19.7% | 1,279 |
| 3 | 962 | 17.6% | 971 |
| 4 | 656 | 12.0% | 654 |
| **≥2** | **2,693** | **49.3%** | **2,904** |

分母：有产品的 base 成分 5,461（`substance` 12,637 → 有 ATC 6,009 → ATC 页上的 base 5,504 → 其中 5,461 个有产品记录）。

页 × 行口径（1,154 个 ATC 页、22,215 行成员）：`{0 种: 172, 1 种: 11,166, 2 种: 4,311, 3 种: 3,906, 4 种: 2,660}` → **≥2 种：10,877 行（49.0%）**。

现网 `/atc/R06A.html` 的 43 个成分行里：1 枚徽章 17 行、2 枚 8 行、3 枚 7 行、**4 枚 11 行（25.6%）**。

### 2.3 「同一状态被不同国家重复推了几次」

- **同一状态在同一行重复出现：0 次**（`_atc_members_html` 对 4 个状态名逐个 `if n:`，天然去重；抽样 29 页 1,139 行验证，最大 4 枚且互不相同）。
- **同一状态被多个市场「推」、然后被压成一枚徽章：4,647 个 (成分, 状态) 对**（跨 ≥2 个市场）；其中跨 ≥3 个市场 2,631 对、跨 ≥5 个市场 1,184 对。每对涉及市场数分布：`2 市场:2016  3:1182  4:265  5:217  6:221  7:253  8:261  9:232`。
- 全站 (成分, 状态, 市场) 有记录的格子：**22,777**。

举例（`data/drugs.db` 现查；市场按 `COUNTRY_PRIORITY` 固定序 = **US GB CA AU SG CN ES MX TW HK**；数字是该状态在该市场的产品记录条数，按 P0-1 的 SQL 口径逐 substance 求和——同一产品若同时挂了 base 与其盐型会计两次，所以条数只用来判断「这个市场有没有这种状态」，**不进 HTML**）：

| 成分（ATC） | 已撤市 | 已停售 | 在售 | 状态未知 | 现状显示 | 推荐显示（方案 A） |
|---|---|---|---|---|---|---|
| Loratadine 氯雷他定（R06AX13） | ES:3 MX:15 | CA:8 ES:1 MX:40 | US:416 GB:63 CA:16 AU:19 SG:17 CN:385 ES:20 MX:12 TW:27 | AU:46 MX:114 HK:48 | 已撤市 已停售 在售 状态未知 | 已撤市 ES·MX ｜ 已停售 CA·ES·MX ｜ 在售 US·GB·CA·AU·SG·CN·ES·MX·TW ｜ 未知 AU·MX·HK |
| Cetirizine 盐酸西替利嗪（R06AE07） | ES:4 MX:2 | CA:23 ES:6 MX:11 | US:436 GB:93 CA:45 AU:10 SG:25 CN:168 ES:32 TW:28 | AU:54 MX:19 HK:78 | 同上 4 枚 | 已撤市 ES·MX ｜ 已停售 CA·ES·MX ｜ 在售 US·GB·CA·AU·SG·CN·ES·TW ｜ 未知 AU·MX·HK |
| Ebastine 依巴斯汀（R06AX22） | ES:7 | ES:8 MX:3 | SG:2 CN:37 ES:56 TW:1 | MX:2 | 同上 4 枚 | 已撤市 ES ｜ 已停售 ES·MX ｜ 在售 SG·CN·ES·TW ｜ 未知 MX |
| Atorvastatin 阿托伐他汀（C10AA05） | ES:82 MX:3 | CA:121 ES:84 MX:9 | US:475 GB:233 CA:135 AU:66 SG:58 CN:524 ES:298 MX:13 TW:40 | AU:258 MX:8 HK:93 | 同上 4 枚 | 已撤市 ES·MX ｜ 已停售 CA·ES·MX ｜ 在售 US·GB·CA·AU·SG·CN·ES·MX·TW ｜ 未知 AU·MX·HK |
| Verapamil 盐酸维拉帕米（C08DA01） | **ES:1** | CA:51 MX:4 | US:138 GB:141 CA:6 AU:10 SG:1 CN:48 ES:6 MX:3 TW:11 | AU:15 MX:4 HK:7 | 同上 4 枚 | 已撤市 **ES** ｜ 已停售 CA·MX ｜ 在售 US·GB·CA·AU·SG·CN·ES·MX·TW ｜ 未知 AU·MX·HK |

最后一行就是「不许多数票」的活样例：撤市只有 1 条 ES 记录，在售覆盖 9 个市场——只要按主导状态渲染，这条撤市事实就没了。

### 2.4 少数市场的信息有多容易被「多数票」吃掉

- **341 个成分（6.2%）** 「已撤市」只出现在 1 个市场，而在售覆盖 ≥5 个市场（例：盐酸纳曲酮 ES、Hydroxyzine MX、醋酸泼尼松 ES、盐酸维拉帕米 ES、阿米替林 ES、吗啡 ES、氨甲环酸 ES、薄荷脑 ES）。
- **658 个成分**的「已撤市」只出现在 1 个市场，且**全部**落在 ES（538）或 MX（120）——这两个市场正是唯二有撤市列的库。
- 「同一市场同时有 >1 种状态」的 (成分, 市场) 格子 **3,599** 个（同一国家的不同品种，有的在售有的停售——按市场归组时必须允许一个国家出现在多枚徽章里，这不是 bug）。

→ 任何「按多数票 / 只显示主导状态 / 只在多市场时省略少数」的方案，会让上面这 658 条撤市事实**整体消失**。这正是必须并列显示（且必须带市场）的理由。

### 2.5 体积与宽度预算

| 指标 | 现状 | 方案 A（市场不截断） | 差值 |
|---|---:|---:|---:|
| 全站 ATC/大类页徽章 HTML | 3.92 MB | 5.27 MB | **+1.35 MB（+34%）** |
| `site/dist` 总量 | 839.4 MB | ~840.8 MB | +0.16% |
| `/atc/R06A.html` | 28.5 KB | ~32 KB | +3–4 KB |
| 徽章可见文本宽（390px 屏可用 335–342px） | p50 74px / max 221px | p50 89 / p90 377 / **max 492px** | 12.5% 的行徽章文本超一行，**0% 超两行** |

（宽度估算按 CJK 12px、大写/数字 7.2px、`·` 2px；实测见 §3.1 的 390px 浏览器测量。）

---

## 3. 方案对比

三个候选都用真数据 + 站点真实 CSS 在 **390px 视口（列表可用宽 335px）** 实测，见 [预演图](../docs/img/atc-status-badges-preview-20261110.png)（脚本见 §7.1）。

### 3.1 方案 A（推荐）：按状态归组，徽章内直接写市场

```
氯雷他定 R06AX13  已撤市 ES·MX  已停售 CA·ES·MX  在售 US·GB·CA·AU·SG·CN·ES·MX·TW  状态未知 AU·MX·HK
```

- **信息**：状态 × 市场 100% 保留；不截断、不 `+N`、不用 `title`（触屏无效）、不做多数票。
- **390px 实测行高**（同一份真数据，行高 26px/行）：

| 成分行 | ① 现状（无市场） | ② 方案 A（市场码 12px） | ③ 方案 A + 紧凑 CSS（11px） |
|---|---:|---:|---:|
| 氯雷他定（4 状态 / 9 市场） | 52px（2 行） | 104px（4 行） | **52px（2 行）** |
| 依巴斯汀（4 状态 / 市场少） | 52px | 52px | **52px** |
| 盐酸西替利嗪（4 状态 / 8 市场） | 52px | 78px | **78px（+1 行）** |
| 盐酸维拉帕米（4 状态 / 9 市场） | 52px | 78px | **52px** |

  合计 4 行 × 26px 的差异：平均 **+6.5px/行**，最坏 +26px。**关键在市场码 12px→11px + `padding:0 5px`**（12px 时氯雷他定行 104px，11px 时 52px）——**CSS 是方案的一部分，不是装饰**。
  单状态行：徽章宽度随市场数增长（9 市场时 186px），名字较长时会多折 1 行；市场少的单状态行高度不变。
- **四语**：状态词走 `data-i18n="drug.status.*"`（四语齐全）；市场码是 2 字母码，与成分页矩阵列头、`atc4` 明细表同一套，**不翻译**（`deploy/i18n_check.py` 的 `ACRONYM_RE` 判为「全大写缩写」，最多 WARN 提示确认）。
- **读屏**：读作「氯雷他定 R06AX13 已撤市 ES MX 已停售 CA ES MX 在售 …」——与视觉同序、同内容，**没有隐藏文本，也没有 title 依赖**。`·` 可能被读成「中点」或被跳过，两种都可接受（不承载语义）；`US` 可能读作「U S」或「us」，同样可接受。**不使用 `aria-label`**：`<span>` 是 generic role，作者命名不可靠。
- **代价**：字节 +1.35 MB；一行文本变长，桌面两栏（每栏约 428px）里长行会折成 2–3 行。

### 3.2 方案 B：按市场归组，一个市场一枚徽章

```
氯雷他定 R06AX13  US 416  GB 63  CN 385  ES 20·1·3  MX 12·40·15·114  AU 19·46  …
```

- **信息**：完整，但**语义靠颜色/位置约定**（`ES 20·1·3` 里的 20/1/3 分别是什么状态？）。需要图例；色盲用户无法解码。
- **390px**：宽度反而更窄（p50 47px / max 520px），但 9 个市场 = 9 枚徽章，行数往上走。
- **四语**：市场码同样不翻译；但「状态 → 数字位置」的映射没有任何语言承载，四语都得靠图例解释。
- **读屏**：读作「US 416 GB 63 …」，**状态名缺失**，等于靠颜色传达信息 → 不满足「信息不只靠颜色」。
- **代价**：字节 **+4.26 MB**（最贵）；语义解释成本最高。

### 3.3 方案 C：徽章不动 + 每行加「按市场」折叠

- **信息**：最全（可给到「市场 × 状态 × 记录数」），但**要多一次点击**；徽章本身仍不说国家，用户第一眼的疑问没解决（用户问的正是「为什么混在一起」）。
- **390px**：默认高度不变（最安静），展开后很高。
- **四语**：折叠标题要四语文案；表内市场码不翻译。
- **读屏**：折叠内容可读，但默认要展开才能拿到。
- **代价**：字节约 +2.5–3 MB（每行一个 `<details>` + 表格）。

### 3.4 对比结论

| 维度 | 现状 | 方案 A（+紧凑 CSS） | 方案 B | 方案 C |
|---|---|---|---|---|
| 状态 × 市场完整性 | ✗ 无市场 | **✓ 全量** | ✓ 全量 | ✓ 全量（需展开） |
| 390px 四状态行高度（实测） | 52px | **52–78px（平均 +6.5px）** | ≥78px | 52px |
| 一次视线能回答「哪个国家」 | ✗ | **✓** | △ 需图例 | ✗ |
| 四语成本 | — | 1 个新 key + 1 个改写 | 图例文案难写 | 折叠标题 |
| 读屏 | 「已撤市 已停售 在售 状态未知」 | **「已撤市 ES MX …」** | 只有数字 | 需展开 |
| 字节 | 3.92 MB | **5.27 MB** | 8.19 MB | ~6.5–7 MB |
| 实现风险 | — | 低（1 个函数 + 1 段 CSS） | 中（新渲染器） | 中（新模板） |

**推荐 A + 紧凑 CSS**。它正面回答用户的问题、零信息丢失、手机高度基本不涨（+6.5px/行）、字节增量最小、读屏与视觉同构。
B 只在「想知道每个国家在卖几个品种」时才更顺手，而那件事应该去成分页做（阶段 2）。
C 留作阶段 2 的可选件：**只有在需要恢复「记录条数」时才做**（例如行尾 `<details><summary>按市场看条数</summary>`），不做也不损失状态×市场。

> 关于用户主动提出的思路：**「按市场归组 + 同类状态合并 + 徽章内中点分隔 + 超 N 折 +N」→ 与方案 A 一致，我采纳；但「超 N 折成 +N」我建议改成「不折」**。理由：(a) 实测不折也只要 2 行，折了省不了高度；(b) `+N` 的完整清单只能放 `title`，触屏拿不到，等于真的丢信息；(c) 数据里一个状态最多 9 个市场，最长文本 492px，物有所值。

---

## 4. 去噪：「暂无中文名」怎么收

### 4.1 现状数字（全站 ATC 页）

| 项 | 数量 |
|---|---:|
| `.nm` 名字元素 | 24,281（主名 22,215 + 盐型 2,066） |
| 缺中文名的名字元素 | 11,752（48.4%） |
| 其中**盐型**缺中文名 | **1,614（占盐型的 78.1%）** |
| 含「盐型缺中文名」的行（页×行） | 1,439 |
| zh 视图一行最多出现次数 | 5（主名 + 4 个盐型） |
| 缺标记最多的页 | A 456 / L 378 / N 342 / J 331 / V 252 / L01 239 / C 208 / B 200 / D 197 / R 133（每页 p50 = 3、p90 = 20） |

顺带一个**不是本次修**但同属「密密麻麻」的：一行盐型最多 35 个（`碘[125I]癌胚抗原放射免疫分析药盒`，来自 §5 P2 的归并 bug）；盐型数分布 `0 个: 4,914 行 / 1: 448 / 2: 67 / 3: 12 / 4: 9 / ≥5: 11`。

### 4.2 三个问题，三种改法

| 问题 | 改法 | 影响 |
|---|---|---|
| ① 标记写进名字文本（`en + ' 暂无中文名'`），在 zh 视图把链接文字撑长一倍 | 从 `renderNames()` 里删掉后缀，改由 `applyNameLangBadges()` 统一加**徽章式**标记 | 链接文字变短、可访问名变干净；zh-Hant 的「暫無中文名」硬编码一起消失 |
| ② 每个盐型各贴一次「暂无中文名」 | 盐型**不贴**标记：这一行主名已经给了锚点（`盐酸西替利嗪 / 盐型 Cetirizine Hydrochloride`），盐型只是变体 | 少 1,614 处；`盐型` 行从「英文名 + 暂无中文名」变成「英文名」 |
| ③ 标记贴在链接里（`<a>…<span class="nm">名 暂无中文名</span></a>`） | 标记插到最近的 `<a>` **之后** | 链接可访问名不再含「暂无中文名」；读屏不会把提示读成名字的一部分 |

改完每行**最多 1 个**标记（只在主名确实缺当前语言名时），总量 11,752 → 10,138（主名级），且全部在链接外。**这不是丢信息**：盐型本来就没有中文名，标记只是重复陈述；主名缺名的 10,138 处（占 45.6%）属于**数据缺口**，靠补 `substance.inn_zh` 解决，不靠 UI。

### 4.3 i18n 顺带修正

现状是硬编码中文（`' 暂无中文名'` / `' 暫無中文名'`），`deploy/i18n_check.py` 看不到（在 `*_JS` 常量里被跳过）。改用**已有的 4 个键**（`NAME_LANG_I18N`，`site/build.py:1028-1039`，四语已在）：

| key | 值 | 用于 |
|---|---|---|
| `name.no_zh` | 无中文名 | zh 视图，主名无中文名 |
| `name.no_zh_hant` | 無中文名 | zh-Hant 视图 |
| `name.no_en` | No English name recorded | en 视图，主名无拉丁名 |
| `name.no_es` | Sin nombre en español | es 视图 |

→ **本项不需要新增 i18n key**，只把硬编码换成 `T()`，四个键的语义本来就一致。

---

## 5. 补丁规格

> 三个补丁互相独立：P0 解决用户报的问题；P1 去噪；P2 是根因（另一个 bug），建议单独提交、单独 CHANGELOG 条目。
> 文件：`site/build.py`（写入权在另一会话）。**行号 = 2026-11-10 当时磁盘上的文件**；该文件正被另一会话同时编辑（调查期间已整体下移 16 行），落地前用这行重新定位锚点：
>
> ```powershell
> Select-String -Path site\build.py -Pattern 'def _sub_status_map|def _atc_members_html|badges \+=|def _collapse_members|function applyNameLangBadges|el.textContent = zh|atc.status_note|COUNTRY_PRIORITY =|by_norm.setdefault'
> ```

### P0 状态角标按市场归组

#### P0-1 `_sub_status_map()`（9372-9386）→ 带上国家

```python
def _sub_status_map(db: sqlite3.Connection,
                    base_of: dict[str, str]) -> dict[str, dict[str, dict[str, int]]]:
    """base substance_id → {status: {country: 产品记录数}}。

    v0.10.4：状态角标必须写清是哪些市场（一行四色其实是「三本登记簿各说各话」，
    见 reports/atc-status-aggregation-20261110.md）。计数只用于判断有无，
    同一产品同时挂了 base 与它的盐型时会计两次，所以计数不进 HTML。
    """
    out: dict[str, dict[str, dict[str, int]]] = {}
    for sid, status, country, n in db.execute(
            """SELECT v.substance_id, p.status, p.country, COUNT(DISTINCT p.product_id)
               FROM product p
               JOIN product_component pc ON pc.product_id = p.product_id
               JOIN variant v ON v.variant_id = pc.variant_id
               WHERE p.status IS NOT NULL AND p.status <> '' AND p.country IS NOT NULL
               GROUP BY v.substance_id, p.status, p.country"""):
        per = out.setdefault(base_of.get(sid, sid), {}).setdefault(status, {})
        per[country] = per.get(country, 0) + int(n)
    return out
```

同步改类型标注：`_collapse_members()` 形参（9397）`status_by_base: dict[str, dict[str, dict[str, int]]]`；
`items["statuses"]`（9419）语义从「{status: n}」变成「{status: {country: n}}」，默认值 `{}` 不变。
`_member_context()`（9389-9392）返回值签名不用动（Python 不校验）。

#### P0-2 新增 `_status_badges_html()` + 替换徽章块（9447-9453）

```python
def _status_badges_html(statuses: dict[str, dict[str, int]]) -> str:
    """状态角标 + 该状态记录在哪些市场（固定序；不截断、不写 title）。"""
    out: list[str] = []
    for st in ("withdrawn", "discontinued", "active", "unknown"):
        per = statuses.get(st) or {}
        if not per:
            continue
        markets = "·".join(sorted(
            per, key=lambda c: (COUNTRY_PRIORITY.index(c) if c in COUNTRY_PRIORITY
                                else len(COUNTRY_PRIORITY), c)))
        out.append(
            f'<span class="st-badge st-{st}">'
            f'<span data-i18n="drug.status.{st}">'
            f'{esc(I18N["en"].get("drug.status." + st, st))}</span>'
            f'<span class="mk">{esc(markets)}</span></span>')
    return "".join(out)
```

`_atc_members_html()`（9431-9453）：

```python
        badges = _status_badges_html(it["statuses"])          # 替换 9447-9452
        lis.append(f'<li>{label} {codes}{salt}{badges}</li>')
```

三个约束（照抄现有约定，别另起一套）：

1. **`data-i18n` 只挂在状态词那一层**。`i18n.js` 的 `apply()` 对 `[data-i18n]` 做 `el.textContent = T(key)`，挂在徽章外层会把市场码一起冲掉。
2. **排序用现成的 `COUNTRY_PRIORITY`（7048）**，不要新建常量；也不要用 `i18n.js` 的 `MORDER`（那是按界面语言重排的客户端逻辑，市场码不是词，服务端固定序保证构建确定性）。
3. **状态顺序保持现状** `withdrawn → discontinued → active → unknown`（问题状态靠左，手机上先看到）。

#### P0-3 图例 + 说明文案（2 处模板 + 2 个 i18n key）

模板：`build_atc_pages()` 9647 之后、`build_category_pages()` 9743 之后，各加一行：

```python
<p class="sub atc-mk-hint" data-i18n="atc.markets_hint">{esc(T["atc.markets_hint"])}</p>
```

同时更新 `ATC_I18N` 里的 `atc.status_note`（现 8757-8759 / 8814 / 8866 / 8908 四语内联），把「为什么会有四色」讲清。
**注意**：`atc.status_note` 现在被折叠进 `<details class="atc-notes">`（`_atc_notes_html`，9754-9764，和另外 3 条 notice 挤在一起），用户基本看不到——所以图例必须放在列表上方（`atc-mk-hint`），不能只改 notes。

#### P0-4 CSS（`CSS` 常量内，紧跟 3089-3094 的 `.st-badge` 之后）

```css
/* v0.10.4：ATC/大类页状态角标带市场码（reports/atc-status-aggregation-20261110.md） */
.st-badge .mk{margin-left:3px;font-size:11px;letter-spacing:0;font-variant-numeric:tabular-nums}
.atcmembers .st-badge{padding:0 5px;margin-right:3px}
.atc-mk-hint{margin:-4px 0 10px}
```

**11px 不是可选项**：同一份真数据、390px 下，市场码 12px 时氯雷他定行 104px（4 行），11px + `padding:0 5px` 时 52px（2 行 = 现状高度）。
`.atcmembers .st-badge` 的内边距只在该列表里收紧，不影响名字页产品表 / 大类页 notice 的徽章。

#### P0-5 新增 i18n key（四语齐全，`ATC_I18N` 内联四语，不需要改 json）

`atc.markets_hint`：

| 语言 | 值 |
|---|---|
| en | `The market codes after a status are the markets where that status is recorded (same codes as the product tables). An ingredient can be on sale in one market and withdrawn in another; that is a record fact, not a safety judgement.` |
| es | `Los códigos de mercado tras cada estado indican dónde consta ese estado (los mismos códigos que en las tablas de productos). Un mismo principio activo puede estar comercializado en un mercado y retirado en otro; es un hecho registral, no un juicio de seguridad.` |
| zh | `状态后面的市场码表示该状态记录在哪些市场（与产品表同一套代码）。同一成分可能在一个市场在售、在另一个市场已撤市；这只是登记事实，不是安全性判断。` |
| zh-Hant | `狀態後面的市場碼表示該狀態記錄在哪些市場（與產品表同一套代碼）。同一成分可能在一個市場販售中、在另一個市場已下市；這只是登記事實，不是安全性判斷。` |

`atc.status_note` 改写（四语，替换现有值）：

| 语言 | 值 |
|---|---|
| en | `Status badges summarise the product records held for each ingredient (active / discontinued / withdrawn / unknown), and the market codes after each badge show where that status is recorded. Only some registers publish a status column: CA, ES and MX do; AU and HK have no status column and are recorded as unknown; CN, US, GB, TW and SG records are on the register and marked active.` |
| es | `Las insignias de estado resumen los registros de producto de cada principio activo (activo / descatalogado / retirado / desconocido); los códigos de mercado tras cada insignia indican dónde consta ese estado. Solo algunos registros publican columna de estado: CA, ES y MX sí; AU y HK no la tienen y figuran como desconocido; los registros de CN, US, GB, TW y SG figuran como activos.` |
| zh | `状态角标按每个成分的产品记录汇总（在售 / 已停售 / 已撤市 / 状态未知）；每个角标后面的市场码表示该状态记录在哪些市场。只有部分市场的登记库带状态列：CA、ES、MX 有；AU、HK 没有状态列，记为状态未知；CN、US、GB、TW、SG 的记录按在售登记。` |
| zh-Hant | `狀態角標依每個成分的產品紀錄彙總（販售中 / 已停售 / 已下市 / 狀態未知）；每個角標後面的市場碼表示該狀態記錄在哪些市場。只有部分市場的登記庫帶狀態列：CA、ES、MX 有；AU、HK 沒有狀態列，記為狀態未知；CN、US、GB、TW、SG 的紀錄按販售中登記。` |

> i18n 门禁要点：`deploy/i18n_check.py` 对 `ATC_I18N` 做**四语键集一致**校验（`dict-key-missing` FAIL）+ **模板引用存在性**校验（`data-i18n="atc.markets_hint"` 找不到就 FAIL）。两个新文案必须四语同时进，否则 CI 直接红。

### P1 去噪（`暂无中文名`）

#### P1-1 `renderNames()`（5575-5584）：删后缀

```js
    document.querySelectorAll('.nm[data-n-en]').forEach(function(el){
      var en = el.getAttribute('data-n-en') || '';
      var zh = el.getAttribute('data-n-zh') || '', zhh = el.getAttribute('data-n-zhh') || '';
      var es = el.getAttribute('data-n-es') || '';
      var lang = window.LANG || 'en';
      if(lang === 'zh') el.textContent = zh || en;                 // 不再拼「 暂无中文名」
      else if(lang === 'zh-Hant') el.textContent = zhh || en;      // 不再拼「 暫無中文名」
      else if(lang === 'es') el.textContent = es || en;
      else el.textContent = en;
    });
```

#### P1-2 新增 `markAtcRowGaps()`（接在 `applyNameLangBadges()` 之后，10506 附近）

```js
  // v0.10.4：ATC/大类页「缺当前语言名」每行只标一次，且标在链接外（盐型不单独标）。
  function markAtcRowGaps(){
    document.querySelectorAll('.atcmembers li').forEach(function(li){
      li.querySelectorAll('.nolang-badge').forEach(function(n){ n.remove(); });
      var nm = li.querySelector('.nm');            // 主名；盐型在 .salt 里，不再逐个标
      if(!nm) return;
      var cjk = /[\u3400-\u9fff]/.test(nm.textContent || '');
      var L = window.LANG, key = '';
      if(cjk && (L === 'en' || L === 'es')) key = (L === 'en' ? 'name.no_en' : 'name.no_es');
      else if(!cjk && (L === 'zh' || L === 'zh-Hant')) key = (L === 'zh' ? 'name.no_zh' : 'name.no_zh_hant');
      if(!key) return;
      var s = document.createElement('span');
      s.className = 'st-badge st-unknown nolang-badge';
      s.textContent = window.T(key);
      var host = (nm.closest && nm.closest('a')) || nm;   // 徽章放链接之后，别污染链接文本
      host.parentNode.insertBefore(s, host.nextSibling);
    });
  }
```

调用点：`applyNameLangBadges();` 之后（10726）加 `markAtcRowGaps();`——顺序很重要，先让原函数铺一遍（覆盖 `.card h2 a`、`[data-nl]` 等非 ATC 场景），再对 ATC 行做收口。

#### P1-3 影响面

- HTML 字节：**0 变化**（标记本来就是 JS 生成的）。
- zh 视图「暂无中文名」出现次数：11,752 → 10,138（主名级），一行最多 5 次 → 1 次。
- 链接可访问名变短（原来把提示读进链接）。
- 行为差异（可接受、需在验收时看一眼）：JS 关闭时本来就没有这些标记（与现状一致）；成分页 / 组合页 / 名字页的 `.nm` 也从「名字内后缀」变成「名字后徽章」，内容等价。

### P2（建议单独立项）`_sub_base_map()` 的极短 norm 磁铁桶

`_norm_name()` 只保留 `[a-z0-9]`，纯中文名会归一成空串（v0.10.1 已热修跳过空串），但**只留 1–2 个 ASCII 字符的名字没有防住**：`多黏菌素E甲磺酸钠` → `e`、`三维B` → `b`、`A型肉毒毒素` → `a`、`维D2磷葡钙` → `d2`、`碘[125I]…` → `125i`。这些桶在 `by_norm`（6498-6505）/`canon`（6507-6510）/盐型剥离（6511-6528）里成了**磁铁**，把不相关成分并进同一行：

```sql
-- 现查：归并后成员最多的 base 桶
碘[125I]癌胚抗原放射免疫分析药盒  36 个 substance（norm='125i'）→ ATC 行挂 35 个「盐型」
多黏菌素E甲磺酸钠（norm='e'）        9 个（维E三油 / 参芪维E / 亚油酸维生素E胶丸 …）
Ferrous 亚铁（norm='ferrous'）       9 个；Manganese 7 个；锝[99mTc]亚甲基二膦酸 7 个
```

最小改法（**会改变行数与 `atc.count`、也会影响检索索引，必须单独构建 + 单独 CHANGELOG**）：
`by_norm` 只收 `len(n) >= 3` 的名字（6503-6505），并在 `canon`/盐型剥离里对 `len(toks)==1` 直接跳过。改完 5,461 行会变少几十行、`atc.count` 数字同步变——属于「改动公开口径」，按 AGENTS §11 要人确认后再做。

### P3 测试 / 快照影响评估

| 检查 | 影响 | 说明 |
|---|---|---|
| `tests/test_lib_atc_category.py` | **不受影响** | 没有对徽章 HTML 的断言；`test_snapshot_sync_with_dist` 比的是 `data/categories.json`（本次不改），`test_category_top1_by_ingredient_total` 只看排序 |
| `deploy/i18n_check.py` | **必须同步** | 新 key 四语齐全 + 模板引用必须存在，否则 `dict-key-missing` / `template-ref-missing` FAIL。当前基线：`FAIL 1 / WARN 15`（FAIL 是 v0.10.1 release notes 缺译文，与本次无关），改完不应新增 FAIL |
| `deploy/ci_checks.py` | 无 FAIL 风险 | `dist-integrity` 只看文件数（不变）、0 字节、sitemap、`core.json`（不变）；`node --check assets/app.js` 会校验 P1 的 JS 语法 |
| 构建确定性 | 需注意 | 市场列表必须 `sorted()` + `COUNTRY_PRIORITY` 固定序；状态遍历用固定元组（不要遍历 dict） |
| 体积 | +1.35 MB（+0.16%） | 记进 CHANGELOG / 报告，不触碰发布护栏（`verify_live.py` 只管 `core.json` gzip 2.5–12 MB） |
| 三语检索一致性 | 不受影响 | 检索链路不读 ATC 页 HTML |

---

## 6. 验收方法

### 6.1 必看页面（本地 `& $py serve.py 8000`，改完 build 到 `== done ==` 后）

| 页面 | 看什么 | 期望 |
|---|---|---|
| `/atc/R06A.html` | 43 个成分行、11 行四状态 | 每行徽章后带市场码；氯雷他定一行应渲染出 `已撤市 ES·MX` `已停售 CA·ES·MX` `在售 US·GB·CA·AU·SG·CN·ES·MX·TW` `状态未知 AU·MX·HK`（以现查库为准） |
| `/atc/A.html` | 890 行，缺中文名最多（456 处） | 「暂无中文名」不再出现在盐型后；每行最多 1 个标记，且在链接外 |
| `/atc/R06AX.html` | L4 页 + 折叠区（`<details>`） | 折叠区里的行与首选行同一格式（共用 `_atc_members_html`） |
| `/cat/allergy.html` | 大类页（cap=80） | 同上；并且也有 `atc-mk-hint` 图例行 |
| `/atc.html`、`/cat/statins.html` | 未被波及 | 无回归 |
| `/atc/R06A.html?lang=en` / `?lang=es` / `?lang=zh-Hant` | 四语 | 状态词跟着语言变；市场码不变；图例四语正确 |

### 6.2 抽哪几个成分

| 成分 | 用途 | 期望 |
|---|---|---|
| Loratadine 氯雷他定 | 四状态 + 9 个在售市场 | 4 枚徽章，市场清单最长（492px 文本级），390px 下 2 行 |
| Ebastine 依巴斯汀 | 四状态但市场少 | 4 枚短徽章，一行放得下 |
| Cetirizine 盐酸西替利嗪 | 4 状态 + 主名有中文但盐型无中文 | `已撤市 ES·MX`；盐型不再跟「暂无中文名」，主名不加标记 |
| Verapamil 盐酸维拉帕米 | **少数市场风险样例**（撤市只有 ES，在售 9 市场） | `已撤市 ES` 必须仍然出现（这条就是「不许多数票」的验收项） |
| Azelastine / Bilastine | 主名无中文 | 每行 1 个「无中文名」徽章，且在链接外 |

### 6.3 机器可核的判据

```powershell
# 1) 每行最多 1 个缺名标记、且不出现在 <a> 内（P1）
Select-String -Path site\dist\atc\R06A.html -Pattern '暂无中文名' -AllMatches   # 期望 0（服务端 HTML 本来就没有）
# 2) 徽章不再带 title 计数（P0）
(Get-Content site\dist\atc\R06A.html -Raw) -match 'st-badge st-active title='      # 期望 False
# 3) 每个徽章后面都有市场码
(Select-String -Path site\dist\atc\R06A.html -Pattern 'class="st-badge st-[a-z]+"><span data-i18n' -AllMatches).Matches.Count
# 4) 体积回归
(Get-ChildItem site\dist -Recurse -File | Measure-Object Length -Sum).Sum/1MB     # 基线 839.4 MB → 期望 ≈ 840.8 MB
(Get-ChildItem site\dist -Recurse -File).Count                                    # 文件数不变
# 5) 门禁
& $py deploy\i18n_check.py                                                        # FAIL 仍应为 1（release notes，与本次无关）
& $py -m unittest tests.test_lib_atc_category -v                                  # 全绿
```

### 6.4 手机 / 读屏

- 375px 与 390px：`/atc/R06A.html` 四状态行高度 **52–78px**（2–3 行文本，平均 52px；实测口径见 §3.1），无横向滚动；`document.documentElement.scrollWidth ≤ innerWidth`。
- 920px：两栏布局下最长行（Loratadine）在自己的栏内折行，不溢出容器。
- 读屏（浏览器可访问性树或 VoiceOver/NVDA）：一行读作「氯雷他定 R06AX13 已撤市 ES MX 已停售 CA ES MX 在售 US GB CA AU SG CN ES MX TW 状态未知 AU MX HK」，**不依赖 `title`**；「无中文名」只读一次且在名字之后。
- 关 JS：徽章 + 市场码仍在（服务端渲染）；缺名徽章消失（与现状一致，本来就靠 JS）。

---

## 7. 复现与未做

### 7.1 复现脚本（本报告的量化来源）

`.tmp/` 下的探针（不入库，`.tmp/` 被 gitignore；下面这段可独立重跑）：

```python
# -*- coding: utf-8 -*-
"""只读：ATC 页状态分布（base 口径）+ 市场清单。不写库、不建站。"""
import importlib.util, sqlite3, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(".").resolve()
spec = importlib.util.spec_from_file_location("sitebuild", ROOT / "site" / "build.py")
build = importlib.util.module_from_spec(spec); sys.modules["sitebuild"] = build
spec.loader.exec_module(build)                      # 只加载，不会 main()

db = sqlite3.connect(f"file:{ROOT/'data'/'drugs.db'}?mode=ro", uri=True)
base_of, sub_names = build._sub_base_map(db)
atc_bases = {base_of.get(s, s) for (s,) in db.execute(
    "SELECT substance_id FROM substance WHERE atc IS NOT NULL AND atc <> ''")}

prov = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))   # base -> status -> country -> n
for sid, st, c, n in db.execute(
        """SELECT v.substance_id, p.status, p.country, COUNT(DISTINCT p.product_id)
           FROM product p JOIN product_component pc ON pc.product_id=p.product_id
           JOIN variant v ON v.variant_id=pc.variant_id
           WHERE p.status IS NOT NULL AND p.status<>'' GROUP BY 1,2,3"""):
    b = base_of.get(sid, sid)
    if b in atc_bases:
        prov[b][st][c] += n

dist = Counter(len(m) for m in prov.values())
print("base 成分数", len(prov), "状态种类分布", dict(sorted(dist.items())))
pairs = [(b, st, sorted(cs)) for b, m in prov.items() for st, cs in m.items() if len(cs) >= 2]
print("跨>=2 市场的 (成分,状态) 对", len(pairs), Counter(len(cs) for _, _, cs in pairs))
```

页×行、字节、宽度三组数字用同一份数据在内存里重拼 HTML 统计（原脚本：`.tmp/atc_status_quant.py`、`.tmp/atc_size_probe.py`、`.tmp/opt_full_probe.py`）。
390px 高度是 Chromium 实测（`.tmp/status-preview.html` + `browser_evaluate` 读 `getBoundingClientRect().height`，行高 26px）。

### 7.2 本次没做（诚实交代）

- **没建站**：所有字节/行高数字来自「内存重拼的等价 HTML + 浏览器测高」，不是在真 `site/dist` 上量的。真构建后请按 §6.3 复核一次。
- **没跑 `db/check_data.py`**（不改数据，无需）。
- **没有实测读屏软件**：§6.4 的读屏结论基于标记结构（无 `title` 依赖、无隐藏文本、标记在链接外），需要在验收时用真读屏器确认一次。
- **方案 B / C 没有做原型页**：只做了字节与宽度估算。

### 7.3 两个附带发现（需要排期）

1. **成分页把所有非 active 记录隐藏**（`build_drug_pages` 7281-7284 + `matrix.hidden_note` 7470-7472：「Discontinued, withdrawn or unverified-status products are hidden by default」）。
   → 后果：**ATC 页的状态徽章是目前全站唯一能看出「某成分在某市场已撤市」的入口**（搜索明细面板按商品名逐条显示状态，但无法按成分枚举）。
   所以本次必须保留徽章而非「挪到成分页去」；反过来，长期应该做**阶段 2：成分页加一个「按市场看登记状态」折叠表**，再把 ATC 行做得更轻。
2. **极短 norm 磁铁桶**（§5 P2）：一行挂 35 个「盐型」、把 RIA 药盒和维 E 类并成一行，是「密密麻麻」的另一半根因，和状态无关但同样伤可读性。

---

## 8. 一句话交接

现状的「四色混杂」不是状态重复，而是「三个有状态列的登记库 + 六本只有『在售』」被压平成一排；**给每枚徽章加市场清单（不截断、11px、固定序）**即可一次解决，390px 行高平均 +6.5px（最长一行 +26px）、字节 +1.35 MB、四语只需 1 个新 key + 1 个改写；顺手把「暂无中文名」从每个盐型收到每行一次、并挪出链接。
