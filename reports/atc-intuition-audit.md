# ATC / 消费者大类「符合直觉」审计

> 日期：2026-10-28 ｜ 任务：`task-125` ｜ 性质：只读审计（DB `mode=ro` + `site/dist` 产物 + `site/build.py` 常量）；**未改 `site/build.py`、未写 DB、未 git/发布**。
> 审计对象：`substance.atc / atc_name / drug_class`、16 个消费者大类映射、`/atc/<code>.html`（1,154 页）与 `/cat/<id>.html`（16 页）。
> 数据快照：`site/dist`（2026-10-28 14:16 构建，v0.8.2 开发期）；`site/build.py` 2026-10-28 14:39（7,233 行）；DB 12,649 个 substance / 6,021 个有 ATC。

**排期对照口径**：`docs/谷段需求队列.md` L42（v0.8.2 = 零结果埋点 + ATC/UI 六项修复）、L43（v0.8.3 = 成分页矩阵常用剂量排序 + 筛选器 + 空行隐藏）、v0.7.1 报告（ATC 类名「待专业校订」）。
**本报告对「已排期」问题只标「已排期」，不重复方案；重点给未排期问题。**

---

## 0. 结论速览

| # | 问题 | 频次（快照） | 影响 | 优先级 | 排期 |
|---|---|---|---|---|---|
| 1 | 中文界面 ATC 大类入口/ATC 页成分名仍英文 | 属 v0.8.2 已修范围 | 中文用户看不懂类目 | P0 | **已排期（v0.8.2）** |
| 2 | 首页「按大类浏览」/三步引导/页头语言切换 | 属 v0.8.2 已修范围 | 首屏直觉 | P0 | **已排期（v0.8.2）** |
| 3 | 成分页矩阵常用剂量排序 + 筛选器 + 空行隐藏 | 属 v0.8.3 范围 | 找药效率 | P1 | **已排期（v0.8.3）** |
| 4 | **L2–L4 类名缺失** | **1,116 / 1,154 页（96.7%）**；L2 76/93、L3 247/249、L4 793/798 | ATC 页多数只有代码，无类名 | P1 | **已排期/已知（v0.7.1「译名待校订」，具体版本待定）** |
| 5 | **`drug_class` 全是占位** | **12,649 / 12,649（100%）**：空 10,639、`unmapped-cn` 1,791、`cn-only-en` 219 | 该字段不可用；任何展示/分组都不可信 | P1 | **未排期** |
| 6 | **`atc_name` 语义混浊** | 有 ATC 的 6,021 条中：空 **3,559（59.1%）**；非空 2,462 条中 **1,147（46.6%）等于药名本身**、185 条（7.5%）为西语描述、唯一值仅 2,252 | 不是 ATC 类名；若误用于类名/搜索会误导 | P1 | **未排期**（当前 build 未用它，见 §1.2） |
| 7 | **减肥大类缺 GLP-1** | `weight-loss` 仅 A08 **12 行（10 个基名）**；semaglutide（208 产品，A10BJ06）、tirzepatide（157，A10BX16）、liraglutide（89）等全在糖尿病 A10 | 用户搜「减肥药」看不到 Wegovy/Zepbound 类 | **P1（未排期）** |
| 8 | **ATC/大类页同一 ATC 码重复** | 851 / 1,154 页有重复 code；Top：V04CW×59、R05X×54、R05XX×51、D02×49、A05B/A05BA×47、A05×45、B05B×45、V01×42；盐型/基名重复 362 页 | 同一类下重复行，直觉上像「同一个药列多次」 | P1 | **未排期** |
| 9 | **大类成员盐型重复** | statins 13 行/8 基名（5 重复）、β阻滞剂 28/20（8）、抗抑郁 71/54（17）、抗病毒 157/138（19）、抗生素 247/226（21）、降压 202/181（21） | 大类列表虚高、重复 | P1 | **未排期** |
| 10 | **大类页成员截断（cap=80）** | 16 类中 **10 类 >80**：皮肤 390→80+310、抗生素 247→80+167、止痛 205→80+125、降压 202→80+122、感冒 200→80+120、抗病毒 157→80+77、酸相关 111→80+31、降糖 109→80+29、抗凝 103→80+23、哮喘 93→80+13 | 大类只有前 80 个（按 inn_zh 字母序），常见长尾看不到；无分页/加载更多 | P1 | **未排期**（v0.8.3 的筛选器是成分页矩阵，不含 ATC/大类页） |
| 11 | **感冒大类混抗组胺、与过敏类 100% 重叠** | `cold-medicine` 200 行 = R05 149 + N02BE 2 + R06 **49**；R06 49 条与 `allergy` 类别**完全重合**；N02BE（acetaminophen）2 条与止痛类重叠 | 「感冒药」= 咳嗽药 + 抗过敏药；两个大类重复展示同一批药 | P2 | **未排期** |
| 12 | **他汀类含撤市药与盐型重复** | C10AA 13 行=8 个基名：atorvastatin×3 行、pravastatin×2、rosuvastatin×2、fluvastatin×2；**cerivastatin（已撤市，9 产品）**仍出现；无状态徽标 | 「他汀类」列表重复/过时 | P2 | **未排期** |
| 13 | **A08 减肥类含撤市/刺激性老药** | sibutramine（已撤市，40 产品）、rimonabant（已撤市，5）等与 orlistat/phentermine 同列；无状态提示 | 直觉上「减肥药」应标风险/撤市 | P2 | **未排期** |
| 14 | **23 个成分只有 L2/L3 级 ATC 码** | 长度 3：4 条；长度 4：19 条；例：Eucalyptus Oil `R05X`、Bamlanivimab `J06B`、Vacuna `J07`、Rhodiola `A13A` | 父级代码当成分级码；ATC 页/搜索可能显示「类目级码」而不知具体药 | P2 | **未排期** |
| 15 | **同一 base INN 多个 ATC** | 59 个基名 >1 ATC：lidocaine `N01BB02`/`N01BB52`、dextromethorphan hydrobromide `R05DA09`/`R05DA20`、diphenoxylate `A07DA`/`A07DA01` 等 | 有的为异构体/父子码（合理），但展示/去重需规则；否则同一药出现多次 | P2 | **未排期** |
| 16 | **大类重叠无互见说明** | 降压∩β阻滞剂=28；感冒∩过敏=49；感冒∩止痛=2 | 用户以为大类互斥，看到重复/漏项 | P2 | **未排期**（可加注/互链） |
| 17 | **「激素类」仅 H02 全身用** | 19 行；外用糖皮质激素在 D07，未纳入 | 用户搜「激素药膏」不会进这个大类 | P2 | **未排期** |
| 18 | **ATC 成员 cap=60 与大类 cap=80 不一致** | 71 个 ATC 页触发「and N more」截断 | 两级列表规则不统一，用户预期混乱 | P3 | **未排期** |
| 19 | **ATC/大类页不显示状态** | 撤市/停售药（cerivastatin、sibutramine 等）无徽标；类别页按字母序 | 过时药与现售药同列，直觉差 | P2 | **未排期** |
| 20 | **WHO 类目存在性无法离线核验** | 6,021 条 ATC 长度/首字母全部合法（0 非法格式），但无 WHOCC 官方列表许可 | 「指向不存在类目」无法确认；需 WHOCC 授权/人工核对 | 说明项 | 限制（非 bug） |

> 正面结果：**空成员页 0、父子断链 0、缺页 0**（1,154 页完整闭环；父链接均指向存在页面）；`atc_name` **无乱码**（0 条 mojibake）。
> 说明：v0.8.2 已修「中文界面英文残留」，本审计仍把「类名/成分英文」标为已排期，不重复提方案。

---

## 1. DB 字段审计（`substance`）

### 1.1 ATC 码：格式/长度/覆盖

| 指标 | 值 |
|---|---:|
| substance 总数 | 12,649 |
| 有 ATC | **6,021（47.6%）** |
| 不同 ATC 码 | 3,094 |
| **格式非法 / 长度异常 / 首字母非法** | **0 / 0 / 0**（长度∈{3,4,5,7}，首字母∈A,B,C,D,G,H,J,L,M,N,P,R,S,V） |
| 长度分布 | 7：3,519（L5）、5：2,479（L4）、4：19（L3-only）、3：4（L2-only） |
| 多码字符串（`\| , ;` 等） | 0（每行单码） |
| 同一 ATC 码对应多个 substance | **1,041 个码**（盐型/异构体/父类归类共用） |
| 同一 base INN 多个 ATC | **59 个基名**（部分为父子码/立体异构，非全部错误） |

**L2/L3-only 样例（23 条）**：`Eucalyptus Oil=R05X`、`Eucalyptol=R05X`、`Bamlanivimab=J06B`、`Vacuna=J07`、`Rhodiola Rosea=A13A`、`Panax Ginseng=A13A`、`Germanio (68Ge)=V09X`、`Complejo De Oseína Hidroxiapatita=A12A` 等——这些是**父级/类别级码**，不是具体药品级 ATC；展示时容易让用户以为「这个药就是这个类」。

**同 base INN 多 ATC 样例**：lidocaine `N01BB02` + `N01BB52`（立体异构码）、dextromethorphan hydrobromide `R05DA09` + `R05DA20`、diphenoxylate `A07DA` + `A07DA01`（父子）、brompheniramine `R01BA51` + `R06AB01`、histamine `M02AB` + `V04CL`。其中父子/立体异构属正常 ATC 体系，但**同一成分在搜索结果/大类里会出现多条**，需要显示规则（不是简单判错）。

### 1.2 `atc_name`（不是类名）

- 有 ATC 的 6,021 条中：**空 3,559（59.1%）**；非空 2,462 条，唯一值 2,252。
- 非空值中：**1,147 条（46.6%）等于 `inn_en` 药名本身**（如 Atorvastatina/Naltrexona）；**185 条（7.5%）是西语描述**（如 `Peroxido de benzoilo`、`Preparados anti-verrugas y callicidas`、`Metilprednisolona, aceponato de`、`ANTIACIDOS CON BICARBONATO DE SODIO`）；其余 2,276 条为 plain 拉丁/英文药名。
- 结论：`atc_name` 是**药名/西语描述**，不是 WHO ATC 类名；`site/build.py` L6028 注释也承认「DB 的 atc_name 是西语药名，不含类别名，故类别名内置」；当前 ATC 页只用内置 `ATC_CLASS_I18N`，**未使用该字段**。未排期风险：以后若有人按字段名误用会出错；建议字段改名/注释/移除，或补官方类名后再用（不属本任务改码）。

### 1.3 `drug_class`（100% 占位）

| 值 | 条数 |
|---|---:|
| 空/None | 10,639 |
| `unmapped-cn` | 1,791 |
| `cn-only-en` | 219 |
| **合计（全部）** | **12,649（100%）** |

- `site/build.py` **0 处引用** `drug_class`（grep 结果为空）；即该字段目前是死字段。建议：**不要展示/依赖**；要么从数据库层删除，要么在补全前明确标「不可用」。未排期。

---

## 2. ATC 类目页审计（`site/dist/atc/*.html`）

| 指标 | 结果 |
|---|---:|
| 页面总数 | **1,154**（L1 14 / L2 93 / L3 249 / L4 798） |
| 空成员页 | **0** |
| 父链接坏链 | **0** |
| DB 前缀应有但缺页 | **0**（L1/L2/L3/L4 均 0） |
| **有名字的页** | **38**（L1 14、L2 17、L3 2、L4 5）→ 其余 **1,116 页无名（96.7%）** |
| 成员 cap=60 触发截断 | **71 页**（“and N more”） |
| 同一 ATC 码在页内重复 | **851 页**（Top：V04CW 59、R05X 54、R05XX 51、D02 49、A05B/A05BA 47…） |
| 同基名/盐型重复页 | **362 页**（如 A02B：omeprazole×2、esomeprazole magnesium×2、ranitidine×2） |

- L2–L4 缺类名比例：**L2 81.7%（76/93）、L3 99.2%（247/249）、L4 99.4%（793/798）**——与 v0.7.1 报告一致（内置仅 25 个常见类名）；已排期/已知（ATC 类名待校订），不重复方案。
- 父子/空页结论：**结构健康**（0 断链/0 空页/0 缺页）；问题集中在命名与去重/截断。

---

## 3. 16 个消费者大类映射审计

| 大类 id | ATC 前缀 | 行数 | 唯一基名 | 页面实际渲染 | 截断 |
|---|---|---|---:|---:|---:|---|
| antihypertensives 降压药 | C02,C03,C07,C08,C09 | 202 | 181 | 80 | +122 more |
| antibiotics 抗生素 | J01 | 247 | 226 | 80 | +167 |
| diabetes 降糖药 | A10 | 109 | 101 | 80 | +29 |
| **weight-loss 减肥药** | **A08** | **12** | **10** | 12 | — |
| **cold-medicine 感冒咳嗽药** | **R05,N02BE,R06** | **200** | **192** | 80 | +120 |
| analgesics 退烧止痛 | N02,M01A | 205 | 192 | 80 | +125 |
| allergy 抗过敏药 | R06 | 49 | 44 | 49 | — |
| acid-related 胃药 | A02 | 111 | 104 | 80 | +31 |
| anticoagulants 抗凝药 | B01 | 103 | 96 | 80 | +23 |
| **statins 他汀类** | **C10AA** | **13** | **8** | 13 | — |
| beta-blockers β受体阻滞剂 | C07 | 28 | 20 | 28 | — |
| antidepressants 抗抑郁药 | N06A | 71 | 54 | 71 | — |
| asthma-copd 哮喘·慢阻肺 | R03 | 93 | 88 | 80 | +13 |
| corticosteroids 激素类 | H02 | 19 | 17 | 19 | — |
| antivirals 抗病毒药 | J05 | 157 | 138 | 80 | +77 |
| dermatologicals 皮肤外用药 | D | 390 | 388 | 80 | +310 |

**直觉问题（重点未排期）**
1. **减肥药只有 A08（12 行/10 基名）**：A08 是传统抗肥胖药（orlistat/phentermine/sibutramine/rimonabant 等）；现代主流减重药 semaglutide（Wegovy，A10BJ06，208 产品）、tirzepatide（Zepbound，A10BX16，157）、liraglutide（Saxenda，A10BJ02，89）都在 A10（糖尿病大类），**减肥大类看不到**。建议（未排期）：把 GLP-1 相关 ATC（A10BJ、A10BX16 等）纳入 `weight-loss` 并在 UI 标明「与糖尿病大类重叠/同一药不同适应症」；或至少在大类页加「相关：糖尿病大类里的 GLP-1」互链。
2. **感冒药 200 行 = R05 149 + N02BE 2 + R06 49**：R06（全身抗组胺）与 `allergy` 类 **49 条完全重复**；N02BE（对乙酰氨基酚）与止痛类重复 2 条。消费者语义上「感冒药」常包含抗组胺+退烧止痛，但将 R06/N02BE 整类放入会造成**两个大类展示同一批药**。建议（未排期）：大类页加「与抗过敏/退烧止痛重叠」提示，或把 R06/N02BE 拆分/建「感冒复方」独立映射（不简单删，避免漏药）。
3. **他汀 13 行 = 8 基名**：逐项核对如下；缺 base 药没有（C10AA01–08 都有），但盐型重复 + 撤市药在列：

| substance | ATC | 产品数 | 备注 |
|---|---|---:|---|
| Atorvastatin | C10AA05 | 2,121 | 基药 |
| Simvastatin | C10AA01 | 1,515 | 基药 |
| Rosuvastatin | C10AA07 | 1,508 | 基药 |
| Pravastatin | C10AA03 | 644 | 基药 |
| Pitavastatin | C10AA08 | 249 | 基药 |
| Lovastatin | C10AA02 | 207 | 基药 |
| Fluvastatin | C10AA04 | 146 | 基药 |
| **Cerivastatin** | C10AA06 | 9 | **已撤市（2001）仍列**，无状态徽标 |
| Atorvastatin Calcium Trihydrate | C10AA05 | 14 | 盐型重复 |
| Rosuvastatin Calcium | C10AA07 | 45 | 盐型重复 |
| Atorvastatin Calcium | C10AA05 | 33 | 盐型重复 |
| Pravastatin Sodium | C10AA03 | 3 | 盐型重复 |
| Fluvastatin Sodium | C10AA04 | 0 | 盐型重复 |

4. **大类成员重复/截断**：见上表（`rows` vs `unique base`；页面 cap 80）；大类页只按 `inn_zh`/`inn_en` 字母序截取，**不是「常用度」排序**（v0.8.3 的排序/筛选仅针对成分页矩阵，不含大类页，故列为未排期）。
5. **状态缺失**：ATC/大类页不展示 `product.status`（active/withdrawn/…）；撤市药（cerivastatin/sibutramine/rimonabant）与现售药同列，消费者无法判断。

---

## 4. 建议与优先级（只列未排期）

| 优先级 | 未排期问题 | 建议（最小改动） | 影响面 |
|---|---|---|---|
| **P1** | 减肥类缺 GLP-1 | 大类 `weight-loss` 增前缀 `A10BJ`/`A10BX16`（或显式 ATC 列表），页内标注与糖尿病类重叠；搜索「减肥」同时命中 | 用户最常搜的减重药 |
| **P1** | ATC/大类成员盐型/重复码 | 构建期按「base INN（去盐/水合物）」分组：一基名一行，附「盐型/异构体 N」折叠；同 ATC 码重复合并 | 851 个 ATC 页/多个大类 |
| **P1** | 大类页 cap=80 截断 | 大类页用「加载更多/分页」或按常用度排序后截断，显示总数；与 ATC cap=60 统一策略 | 10/16 大类，最长 390 行 |
| **P1** | `drug_class` 死字段/100% 占位 | 不展示；字段注释/删除；如要按药理类分组，改用 `atc` 前缀派生 | 任何未来分组 |
| **P1/P2** | `atc_name` 空/语义混浊 | 保留但改名/注释为「drug name (legacy)」；不要当类名用；类名走 `ATC_CLASS_I18N`/官方补全 | 搜索/类目建议 |
| **P2** | 感冒/抗过敏重叠 | 大类页加互见提示；R06 是否留在「感冒药」由产品决定；不要静默去重 | 49 条重复 |
| **P2** | 他汀/减肥类撤市药 | 大类页显示状态徽标（withdrawn/discontinued）；或默认隐藏撤市（同 v0.6.7 成分页矩阵默认隐藏停售/撤市） | 13 个他汀行/12 个减肥行 |
| **P2** | 23 条 L2/L3-only 代码 | 构建/UI 标「仅类目级 ATC」；搜索结果显示时不要伪装成具体药；必要时从「药品 ATC」视图排除 | 23 个成分 |
| **P2** | 同基名多 ATC | 搜索/类目结果按 ATC 精确码分组，同 base 多码折叠；父子码不当重复 | 59 个基名 |
| **P2** | 「激素类」仅 H02 | 大类可加提示「不含外用激素（见皮肤外用药）」或新增类 D07 互链 | 19 行 vs 用户预期 |
| **P3** | ATC cap=60 / 大类 cap=80 不一致 | 统一参数或页面说明「最多显示 N 个」；配合加载更多 | 71 个 ATC 页 |
| **P3** | 大类/ATC 页无状态 | 与 v0.6.7 成分页状态隐藏策略对齐；页面上给状态徽标 | 撤市药可见性 |
| **限制** | 「不存在类目」无法确认 | 无 WHOCC ATC 授权列表；本次只验证格式/首字母/父子闭环。若要核对 WHO 全量类目：需 WHOCC 授权或人工对照 ATC/DDD Index（注意许可，见 `reports/terminology-accuracy.md` §1） | 6,021 条 ATC |

---

## 5. 方法与证据

**方法**
- DB 只读 `mode=ro`：`substance` 12,649 行（`substance_id/inn_en/inn_zh/atc/atc_name/drug_class`）+ `variant/product_component` 产品数；格式用长度/字符集/首字母校验；atc_name 用西语词表+变音符号+mojibake 规则分类；`drug_class` 全值分布。
- `site/build.py` AST 取 `ATC_L1_I18N/ATC_CLASS_I18N/CONSUMER_CATEGORIES/ATC_LEN_LEVEL`；页面侧解析 `site/dist/atc/*.html` 与 `site/dist/cat/*.html`（h1 名称块、atclist 成员、`atc.unnamed`、`and N more`、父链 href）。
- 大类成员 = `substance.atc.startswith(prefix)`（构建期同一逻辑）；重叠按 `substance_id` 集合；盐型重复按去盐基名近似（会低估/高估个别项，已在表内标样例）。
- **未联网**：本任务不需外部数据；「WHO 类目存在性」受 WHOCC 许可限制，未做（见上）。

**证据文件（`.tmp/atc-intuition/`）**
| 文件 | 内容 |
|---|---|
| `audit_fixed.json` | 完整审计数据（DB/页面/大类/重点药） |
| `audit.json`、`db_summary.json` | 首轮/DB 摘要（含早期口径） |
| `build_consts.json` | build.py 的大类/类名/长度常量快照 |
| `build_sections.txt`、`build_sections2.txt` | ATC 页/大类页生成逻辑 + 名称/成员函数源码快照（L6160–6590） |
| `audit.py`、`audit_fixed.py`、`extra.py`、`samples2.py` | 可复现审计脚本（只读 DB；可直接跑） |
| `inspect_pages.py` | 单页 HTML 结构核对（C10AA/A01A/R06/J01 等） |
| `roadmap.py` | v0.8.2/v0.8.3/类名待校订的排期对照证据 |

**复现**
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp/atc-intuition/audit_fixed.py   # DB + site/dist 全量审计，输出 .tmp/atc-intuition/audit_fixed.json
```

**限制**：`site/dist` 为 14:16 构建（v0.8.2 开发期），`site/build.py` 14:39 有过更新；本次审计的生成逻辑（atc/cat 页）与常量在当前源码中未变，但页面数/名称覆盖可能随下一次构建微调；不涉及 DB 写入。WHO ATC 类目名称/存在性以 WHOCC ATC/DDD Index 为准（未授权未引用全表）。
