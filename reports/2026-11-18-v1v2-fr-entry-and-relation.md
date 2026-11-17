# v0.13.7：V1 市场菜单补法国 FR + V2 商品名详情页关系前置

**结论：两处都已改完并在临时产物上验过，`site/build.py` 可定稿一次构建发 v0.13.7。**
`deploy/i18n_check.py` **FAIL 0 / WARN 2**（五语各 **667 键**，fr 663/667）；
临时产物 `.tmp/site-ui-v0137` 全量构建到 `== done ==`（name 页 91,073）；`site/dist` 未写、未 commit。

| 验收项 | 结果 |
|---|---|
| V1 菜单项数 == 覆盖页行数 == 15、顺序一致 | ✅ `US GB CA AU ES FR MX CN TW SG HK EU JP CZ LV`（两处逐字相同，`boot.js` 也已带 `market-FR`） |
| V2 案例①「Tylenol Extra Strength → 中国」 | ✅ 泰诺林 = `Same active ingredients · release type to be checked`；泰诺 = `Different formula · 3 more active ingredients`（N=3，与验收预期一致） |
| V2 20 条名字页 SQL 对账 | ✅ **0 差异**（8 页 / 11 行 —— 全站带关系表的名字页就这么多，见 §2.1） |
| 首屏守卫（name 页 768 / 390） | ✅ 改前 1.0 / 1.0 → 改后 1.0 / 1.0，chrome 0.22 / 0.33 不变，溢出 否，正文 16px |
| 五语文案 | ✅ `fam.cmp_current` / `fam.badge.same` / `fam.badge.diff` 五语齐（fr 实测见下） |

---

## 1. V1 市场菜单补 FR（P0）

**根因**：`SHELL_MARKETS` 是 build.py 里**手写的 14 项国家清单**（漏了 FR），而覆盖页的行来自
`data/markets.json`（15 项）—— 两处各维护一份，必然漂移。

**改法（单一真相源）**：

```python
def _registry_shell_markets() -> tuple[tuple[str, str], ...]:
    """(市场码, i18n key)：读 data/markets.json 的 enabled 项，按 order 排序。"""
SHELL_MARKETS = _registry_shell_markets()
```

- 菜单（`_shell_market_links` → 顶部「市场」面板，`boot.js` 运行时注入的那份也是同一模板）与
  覆盖页行**同源**：覆盖页在 `build_coverage_page()` 里按同一份 `SHELL_MARKETS` 的顺序排序
  （原来按 SQL 的 `ORDER BY country` 字母序）。
- 译名不新造：用 `markets.json` 的 `i18n_key`（`home.fr` = France / 法国 / Francia…），
  与既有 `home.*` 键一致，五语由 i18n.js 切换。
- `COUNTRY_PRIORITY` 原本已含 FR（`_market_is_enabled("FR")`），本次不动它的顺序 ——
  它管的是矩阵列序等既有排版，改序会牵动全站页面，超出 V1 范围。

**验收（产物实测）**：

```
index.html 菜单：  US GB CA AU ES FR MX CN TW SG HK EU JP CZ LV   → 15 项
coverage.html 行： US GB CA AU ES FR MX CN TW SG HK EU JP CZ LV   → 15 行（id="market-XX"）
assets/boot.js 含 market-FR： True
```

## 2. V2 关系前置到药名旁（P1）

**改法**：

1. **当前记录移到表头**：新增 `.famcur` 卡片（`fam.cmp_current`「正在对照的产品」+ 注册名 +
   覆盖市场 + 完整活性成分），表格里不再出现「本页」行，下面每行都是可查看候选。
2. **关系做成药名旁的徽标**：新增 `_fam_badge()`，关系仍由既有 `_family_relation()`
   （成分集合 + `release` 字段）**自动推导**，只是把结论压成一句短话：
   - 成分集合相同 → `fam.badge.same`「成分相同 · 释放方式待核对」
   - 成分集合不同且对方另有成分 → `fam.badge.diff`「配方不同 · 另含 {n} 种活性成分」，
     `n = |对方成分集合 − 当前集合|`，走现有 `data-i18n-tpl` + `data-total`（切语言只换数字）
   - 两侧都能锁定且 release 不同 → 复用既有 `fam.rel.release`（「不可互换」信号不能丢）
   - **对方是当前记录的子集（n=0）** → 不能写「另含 0 种」：退回既有中性表述
     `fam.rel.partial`（「部分成分相同，不是同一组合，不可互换」）—— 这是本轮自验时抓到的真 bug，
     第一版把 n 夹到 1，会说假话。
3. **表格列序**：关系列并入药名单元格 → 表头变「注册名（含徽标）/ 完整活性成分 / 覆盖市场」，
   桌面徽标在药名右侧、`<768px` 落到药名下一行（`.famcmp-name .famrel{display:block}`）。
4. 没有硬编码任何药名/市场结论；`fam.cmp_this` 键保留但不再渲染。

**案例①逐字证据**（`.tmp/site-ui-v0137/name/tylenol-extra-strength.html`）：

```
表头： Product being compared | Tylenol Extra Strength | CA、US | Acetaminophen 对乙酰氨基酚
行：   泰诺    → Different formula · 3 more active ingredients      （data-i18n-tpl=fam.badge.diff, data-total=3）
行：   泰诺林  → Same active ingredients · release type to be checked（data-i18n=fam.badge.same）
```

**五语实测**（产物 `assets/i18n.fr.js`）：

```
fr fam.badge.same    Mêmes principes actifs · type de libération à vérifier
fr fam.badge.diff    Formule différente · {n} principes actifs de plus
fr fam.cmp_current   Produit comparé
（zh/zh-Hant/es 见 build.py 对应字典块，i18n_check 键集一致 ⇒ 五语齐）
```

### 2.1 关系徽标 × SQL 现算对账（**0 差异**）

**为什么不是「抽 20 条」**：全站「品牌家族」只有 **4 个家族 / 9 个名字 key**
（`SELECT COUNT(DISTINCT family_id), COUNT(*) FROM name_family` → 4 / 9），
对应**带关系表的名字页一共 8 个**、行 11 条 —— 这就是全部母体，所以**做的是全量对账**，不是抽样。

**口径**：成员 key 从 `name_family` JOIN `brand_family` 取（与 build.py 的 families 同源，
不再从 HTML 链接反推；文件名是 `key_file(key)`，空格被换成 `-`，脚本用 slug→key 映射反查）。
SQL 独立算成分集合（`product_name → product_component → variant.substance_id`）与 release 集合，
再按与 `_family_relation` 相同的规则推期望徽标，与产物里的 `data-i18n` / `data-i18n-tpl`+`data-total` 逐条比对。

```
对账页数 8，行数 11：通过 11，差异 0
  benadryl-allergy-relief.html → benadryl                    产物 diff    N=3  SQL diff    N=3  OK
  benadryl.html                → benadryl allergy relief     产物 diff    N=1  SQL diff    N=1  OK
  gaviscon.html                → gaviscon original aniseed…  产物 diff    N=1  SQL diff    N=1  OK
  lipitor.html                 → 立普妥                       产物 partial N=0  SQL partial N=0  OK
  tylenol-extra-strength.html  → 泰诺                         产物 diff    N=3  SQL diff    N=3  OK
  tylenol-extra-strength.html  → 泰诺林                       产物 same    N=0  SQL same    N=0  OK
  泰诺.html                     → tylenol extra strength      产物 partial N=0  SQL partial N=0  OK
  泰诺.html                     → 泰诺林                       产物 partial N=0  SQL partial N=0  OK
  泰诺林.html                   → tylenol extra strength      产物 same    N=0  SQL same    N=0  OK
  泰诺林.html                   → 泰诺                         产物 diff    N=3  SQL diff    N=3  OK
  立普妥.html                   → lipitor                     产物 diff    N=1  SQL diff    N=1  OK
RESULT: 0 差异
```

脚本：`.tmp/recon_v2.py`（只读开库 `mode=ro` + 读 `.tmp/site-ui-v0137` 产物，不入库不写站）。
对账过程本身抓到并修掉了产品侧一个真 bug（对方是子集时不能说「另含 0 种」，见 §2 第 2.4 条），
修复后重新构建再对账 = 0 差异。

**首屏守卫**（`deploy/first_screen_check.py --pages name --viewports 768x1024,390x844`）：

```
改前（site/dist，11/17 11:44 产物）  name 768x1024  AFCR 1.01 items 1.0 chrome 0.22 溢出 否 正文 16px  ok
                                    name 390x844   AFCR 1.01 items 1.0 chrome 0.33 溢出 否 正文 16px  ok
改后（.tmp/site-ui-v0137）          name 768x1024  AFCR 1.01 items 1.0 chrome 0.22 溢出 否 正文 16px  ok
                                    name 390x844   AFCR 1.01 items 1.0 chrome 0.33 溢出 否 正文 16px  ok
```
（name 页本身只有 1 条「产品」条目族，items 恒为 1；关键是没有退化，chrome 不变、无横向溢出。）

---

## 3. 命令（全部只读 / 只写 `.tmp`）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:SITE_OUT = '.tmp\site-ui-v0137'; & $py site/build.py            # == done ==（name 页 91,073）
& $py deploy/i18n_check.py                                          # FAIL 0 / WARN 2（667 键 ×5）
& $py deploy/first_screen_check.py --dist site/dist --pages name --viewports 768x1024,390x844 --json .tmp/first-screen/v2-before.json
& $py deploy/first_screen_check.py --dist .tmp/site-ui-v0137 --pages name --viewports 768x1024,390x844 --json .tmp/first-screen/v2-after.json
python .tmp/recon_v2.py .tmp/site-ui-v0137 20                        # 对账脚本（未跑全，见 §剩余）
```

## 4. 剩余（按 Lead 的时间盒要求，未做完就写清）

1. `fam.cmp_rel` 键已不被渲染（关系并入药名徽标），按 i18n 规则未删键（键集一致优先）；
   下版可连同 `fam.cmp_this` 一起清理。**（Lead 已定：不在这版做）**
2. V1 只改了菜单与覆盖页的行序，**没有**把 `COUNTRY_PRIORITY` 改成 registry 顺序
   （那会牵动矩阵列序、成分页块序等既有排版）。**（Lead 已定：不在这版做；如需「全站市场顺序统一为
   FR 在 ES 之后」，单开一条需求做全量回归）**
3. 关系徽标的「档位」只有 4 种（same / diff·N / partial / release）；如果后续用户希望
   「成分相同且释放也相同 → 明确写『释放方式相同』」，再加一个 `fam.badge.release_same` 键即可，
   现有推导函数已能区分（`rel_cur == rel_sib`）。

## 5. 一句话交接

改了什么：菜单改成读 `data/markets.json`（补上 FR，与覆盖页 15 行同源同序）；
名字页把当前记录提到表头、关系压成药名旁徽标（成分相同 / 配方不同·另含 N 种，自动推导，五语）。
怎么验的：产物实测菜单 15 项 == 覆盖页 15 行且逐字同序；案例①三行徽标逐字对；
**全量 8 页 / 11 行关系徽标与 SQL 现算对账 0 差异**；i18n FAIL 0；
name 页首屏 768/390 无退化、无横向溢出。还剩什么：`fam.cmp_rel` 死键与 `COUNTRY_PRIORITY` 顺序（均已记待办）。
