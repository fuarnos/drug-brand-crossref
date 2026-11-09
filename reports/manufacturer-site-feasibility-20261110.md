# 药企官网能不能当「核对与出处」——6 站小规模试点

> 试点执行：2026-11-10（北京时间）。**只读试点**：未写 `data/drugs.db`、未改任何代码。
> 产出：本报告 + `data/sources/brand_corroboration.csv`（5 行，只收公开可引用的站点）。
> 相关前置：`AGENTS.md` §1（三条底线）、§4（许可先行）、§9（不付费买数据、不绕 WAF）；`docs/许可清单.md` 分级口径；
> `reports/form-effervescent-20261110.md` §3.3 的 R1/R2（力度伸 剂型问题的两条路）。

---

## 0. 结论先行

| 问题 | 结论 |
|---|---|
| **能不能用？** | **能用，但只能当「核对 + 出处」，不能当数据源。** 6 个站里只有 **2 个**（拜耳中国 `bayer.com.cn`、Haleon `panadol.com`）适合「站内引用事实 + ≤200 字摘录 + 链接回原文」；**2 个条款明确禁止**（Reckitt `nurofen.co.uk`、上海强生 `jntlch.com.cn`）；**2 个直接 403 不可用**（Redoxon 全线、`tylenol.com`）。 |
| **用到什么程度？** | 只到**字段级佐证**：品牌 ↔ 成分 ↔ 剂型（+ 部分规格）。**不抓批量、不入库、不做定时爬虫**；官网只覆盖消费级 SKU，覆盖不了监管登记簿里的全部条目。 |
| **哪些站不能用？** | `redoxon.com/.me/.com.sg`、`bayer.com`、`bayer.com.au`（403 反爬，**未尝试绕过**）；`tylenol.com`（Akamai 403，连 `robots.txt` 都 403）；`nurofen.co.uk`（条款禁止自动采集，且需 JS）；`jntlch.com.cn`（条款禁止抓取与公开传播，仅内部人工核对）。 |
| **力度伸 问题能不能解决？** | **能，而且比 R2 更轻**：拜耳中国产品概览页原文就是「**力度伸® 维生素C泡腾片**」。不用动人工表（`brand_family`），就能把「来源写片剂、看着像错的」变成「有厂商出处的差异」。 |
| **力度伸 ↔ Redoxon 品牌家族？** | **这条厂商站给不了**：Redoxon 系站点（含 `bayer.com`/`bayer.com.au`）全部 403。品牌家族仍要人工表 + 其他可引用出处。 |

---

## 1. 试点范围与方法

6 个站点、覆盖 2 个中国市场品牌（力度伸、泰诺，符合「≥2 个中国市场」要求）：

| # | 品牌 | 运营方 | 试点站点 |
|---|---|---|---|
| 1 | 力度伸 | 拜耳（中国） | `https://www.bayer.com.cn` |
| 2 | Redoxon | Bayer Consumer Health | `redoxon.com` / `redoxon.me` / `redoxon.com.sg` / `bayer.com` / `bayer.com.au` |
| 3 | Tylenol | Kenvue | `https://www.tylenol.com`（+ `kenvue.com` 兜底） |
| 4 | Panadol | Haleon | `https://www.panadol.com` |
| 5 | Nurofen | Reckitt | `https://www.nurofen.co.uk` |
| 6 | 泰诺 | 上海强生制药（Kenvue 中国） | `https://jntlch.com.cn` |

每个站点记录 5 项：`robots.txt` 关键行 / 使用条款原句 / 可达性（HTTP、WAF、是否需 JS）/ 可核对字段 / 结论。
工具：`web_fetch`（无 JS 的静态抓取）+ 无头浏览器渲染（**仅用于判断「是否需 JS 渲染」，不把渲染结果入库**）。
所有抓取均为单次、逐页、无人值守之外的临时请求；**没有**任何并发批量抓取。

---

## 2. 逐站结果

### 2.1 力度伸（拜耳中国，CN）

| 项 | 结果 |
|---|---|
| **robots.txt** | `https://www.bayer.com.cn/robots.txt` → HTTP 200：`User-agent: *` / `Disallow:`（**空，即全站允许**）/ `Sitemap: https://www.bayer.com.cn/sitemap.xml` |
| **使用条款** | `https://www.bayer.com.cn/zh-cn/condition-of-use`（「使用条款」）：<br>「本网站中发布的所有内容、文件和插图均为拜耳的独家财产。允许使用这些财产的前提是在所有副本上展示相关著作权，且该等内容**仅可用于个人目的，不得作为商用**，且不得对内容进行任何方式的变更」 |
| **可达性** | 静态页 `web_fetch` **HTTP 200 直出正文**；但**产品列表是 JS 渲染**：`/zh-cn/portfolio/products-from-a-to-z` 用 `web_fetch` 只拿到空壳（正文只有「探索我们的产品」），无头浏览器渲染后才出现 40+ 张产品卡 |
| **可核对字段** | 品牌名 ✅（力度伸®）· 活性成分 ✅（维生素C）· 剂型 ✅（泡腾片）· 规格 ❌（页面不写 1 g）· 覆盖国家/地区 ✅（「在中国上市」+ 类目「健康消费品/维生素与补充剂」） |
| **出处片段** | 「**力度伸® 维生素C泡腾片**」（产品概览页产品卡标题；同页类目「维生素与补充剂」）·`.../portfolio/products-from-a-to-z` ·2026-11-10 |
| **结论** | 🟡 **可公开引用（条件性）**：非商业站 + 署名「拜耳（中国）」+ 短摘录 + 链接回原文 + **不使用官网图片**（条款要求插图只能随文使用）。产品列表需渲染才可见 → **不要写自动抓取脚本**，人工取一次、记 `retrieved_at`。 |

**附带收获（同一页面，一次抓取多行）**：拜耳中国的 A–Z 页把「品牌® + 成分 + 剂型」写在同一行，天然适合当佐证：
`开瑞坦® 氯雷他定片`、`开瑞坦®氯雷他定糖浆`、`凯妮汀®克霉唑阴道片`、`康王®酮康唑洗剂`、`彼康王®酮康唑乳膏`、`力度伸® 维生素C泡腾片`。

### 2.2 Redoxon（拜耳国际）

| 项 | 结果 |
|---|---|
| **robots.txt** | 全部 **HTTP 403**，返回反爬页：`Your bot have been rated as a harmful activity and will be blocked... Please supply bot IP address: 45.49.224.134`。<br>受影响：`redoxon.me`、`redoxon.com.sg`、`bayer.com`、`bayer.com.au`（`redoxon.com` 直接 DNS 失败）。`bayer.es` 301 跳到 `bayer.com` → 同样 403。 |
| **使用条款** | **未取到**（站点在 robots 层就拒绝，未继续请求条款页——**不绕过 WAF**） |
| **可达性** | ❌ 不可用。403 + bot 指纹拦截；无验证码，但是主动拒绝 |
| **可核对字段** | 品牌 ✗ · 成分 ✗ · 剂型 ✗ · 规格 ✗ · 国家 ✗ |
| **结论** | ⚫ **不可用**。按 §9「不绕 WAF」记「不可用」，不做任何规避尝试（换 UA、换 IP、镜像都不做）。 |

### 2.3 Tylenol（Kenvue，US）

| 项 | 结果 |
|---|---|
| **robots.txt** | `https://www.tylenol.com/robots.txt` → **HTTP 403**（Akamai：`Access Denied ... Reference #18.70ed217...`）——**连 robots.txt 都拿不到** |
| **使用条款** | 未取到（同上） |
| **可达性** | ❌ `tylenol.com` 全站 Akamai 403。兜底查企业站 `kenvue.com`：`robots.txt` 200（`Crawl-delay: 10`），但 `/tylenol`、`/brands/tylenol` 均 **404**（Kenvue 企业站没有产品级页面），`/zh-cn/news-features/...` 正文为 JS 空壳 |
| **可核对字段** | 全部 ✗ |
| **结论** | ⚫ **不可用**（WAF + 无产品页）。`kenvue.com` 只剩「企业新闻」层，没有成分/剂型字段，做佐证没有价值。 |

### 2.4 Panadol（Haleon）

| 项 | 结果 |
|---|---|
| **robots.txt** | `https://www.panadol.com/robots.txt` → HTTP 200：`User-agent: *` / `Disallow: /search-results` / 30+ 条多语 `Sitemap:`（en-gb、en-au、zh-hk、en-sg、es-cac…） |
| **使用条款** | `https://www.terms.haleon.com/en-gb/`（Last updated 07.05.2025）：<br>「You may freely browse the Site, but you may only access or download material on this Site for **your personal, non-commercial use**... Without the express written permission of Haleon, **no other use of material on the Site is permitted.**」<br>另有一节 Linking：允许链首页，但**不得暗示 Haleon 背书** |
| **可达性** | ✅ **最好的一个**：服务端渲染，`web_fetch` HTTP 200 直出正文（产品页、robots、sitemap 都通），**不需要 JS** |
| **可核对字段** | 品牌 ✅（Panadol，含 11 个英国 SKU）· 成分 ✅（paracetamol）· 剂型 ✅（film-coated tablet / capsule / soluble）· 规格 ✅（500 mg）· 覆盖国家/地区 ✅（站点导航列出 UK/AU/HK/SG/IE/… 30+ 市场，含 `zh-hk`、`en-sg`） |
| **出处片段** | ①「**500mg Paracetamol**」「Panadol Original Tablets are round and **film-coated**」·`/en-gb/adult-products/panadol-original-tablets/`<br>②「**500mg Paracetamol**」「Panadol Capsules are the first and only **liquid paracetamol capsules**」·`/en-gb/adult-products/panadol-500mg-capsules/`<br>均 2026-11-10 |
| **结论** | 🟡 **可公开引用（条件性）**：非商业 + 署名 Haleon + 短摘录 + 链接；**不复制包装图**（条款要求图片只能随文使用）。链接按条款走「首页或来源标注」，不宣称任何背书。 |

### 2.5 Nurofen（Reckitt）

| 项 | 结果 |
|---|---|
| **robots.txt** | `https://www.nurofen.co.uk/robots.txt` → HTTP 200：`User-agent: *` / `Allow: /` / `Disallow: /search`；`sitemap.xml` 也 200（30+ 产品页 URL） |
| **使用条款** | 站内 `/terms-and-conditions/` **客户端渲染失败**（返回空壳，正文 0 字符）→ 改用 Reckitt 集团条款 `https://www.reckitt.com/terms-and-conditions/` §3.3：<br>「You may only copy, reproduce, republish, download, post, broadcast, record, transmit, commercially exploit, edit, communicate to the public or distribute in any way the Content ... **for your own personal use.** **You may not use any automatic or manual device, program, algorithm or method**...」 |
| **可达性** | ⚠️ **需 JS 渲染**：产品页 `web_fetch` 返回 200 但**正文为空**（React 客户端渲染）；无头浏览器渲染后可读到完整事实 |
| **可核对字段** | 品牌 ✅ · 成分 ✅（contains ibuprofen）· 剂型 ✅（Format: Tablets）· 规格 ✅（200 mg）· 包装 ✅（8/12/16/24/48/96 片）· 覆盖国家 ✅（UK） |
| **出处片段** | 「Nurofen 200mg Tablets」「Contains **ibuprofen**」「Format: **Tablets**」「View available pack sizes: 8/12/16/24/48/96 Tablets」·`/products/nurofen-200mg-tablets/`·2026-11-10 |
| **结论** | 🔴 **仅内部人工核对，不公开引用**：条款明确禁止用自动设备收集，并限制「communicate to the public」。技术上可读，但**不写抓取脚本、不在站内引用其原文**。 |

### 2.6 泰诺（上海强生制药，CN）

| 项 | 结果 |
|---|---|
| **robots.txt** | `https://jntlch.com.cn/robots.txt` → HTTP 200（Drupal 默认）：允许静态资源，禁 `/search/`、`/user/login`、`/core/`、`/profiles/`；**产品页 `/zh-hans/products/1` 未被禁** |
| **使用条款** | `https://jntlch.com.cn/legal-notice`（服务条款 §5「可接受的用途和行为准则」）：<br>「未经我们事先明确书面同意，擅自复制、修改、改编、翻译、创建衍生作品…**分发或以其他方式利用服务的任何部分**」<br>「…使用任何机器人（robot）、蜘蛛（spider）…来检索、索引、"抓取"、"数据挖掘"或以其他方式收集服务内容…**我们允许公共搜索引擎运营商**…（仅用于建立公开可搜索索引）」<br>另禁「**系统下载和存储服务内容**」与「将服务用于任何商业目的」 |
| **可达性** | ✅ 服务端渲染，`web_fetch` HTTP 200 直出正文（不需要 JS），但**条款不允许** |
| **可核对字段** | 品牌 ✅（泰诺 Tylenol）· 成分 ✅（「泰诺®含有有效成分对乙酰氨基酚」）· 剂型 ✅（酚麻美敏片 / 对乙酰氨基酚缓释片 / 氨酚拉明片 / 混悬滴剂 / 口服混悬液）· 规格 ❌ · 国家 ✅（中国） |
| **出处片段** | 「泰诺®是强生消费者健康旗下解热镇痛药药品品牌…自 1995 年进入中国市场」「泰诺®含有有效成分**对乙酰氨基酚**」「旗下产品包括成人感冒（泰诺®酚麻美敏片）、成人镇痛（泰诺林®对乙酰氨基酚缓释片）…儿童退热（泰诺林®对乙酰氨基酚混悬滴剂/口服混悬液）」·`/zh-hans/products/1`·2026-11-10 |
| **结论** | 🔴 **仅内部核对，不公开引用**：条款同时禁止「自动抓取」与「复制/分发」，比拜耳中国更严。**结论只写进内部报告，不带原文上公开页。** |

---

## 3. 三个问题的回答

### 3.1 法律/许可面

| 站点 | 分级 | 能做什么 | 不能做什么 |
|---|---|---|---|
| 拜耳中国 `bayer.com.cn` | 🟡 条件性 | 引用「品牌® + 成分 + 剂型」事实 + ≤200 字摘录 + 链回原文；署名「拜耳（中国）有限公司」 | 商用；改字（含改写后当成原文）；单独使用官网图片；批量抓取列表页 |
| Haleon `panadol.com` | 🟡 条件性 | 同上；署名「Haleon」 | 商用；「personal, non-commercial use」之外的任何用途（**风险最高的边界**，见 §5 待决） |
| Reckitt `nurofen.co.uk` | 🔴 仅内部 | 人工读一次、内部记录 | 自动采集；公开引用原文 |
| 上海强生 `jntlch.com.cn` | 🔴 仅内部 | 人工读一次、内部记录 | 抓取（除公共搜索引擎）；复制/分发；公开引用 |
| Redoxon 全线 / `tylenol.com` | ⚫ 不可用 | 无 | 任何形式的抓取或规避 |

**总的法律判断**：厂商官网的**公开产品页**可以作为「核对与出处」使用，但只能落到本站 `docs/许可清单.md` 的 🟡 档——**只引事实字段 + 短摘录 + 链接，不分发全文/图片**。这条口径与现有 `nhsa`（🔴 仅事实+链接）、`cima`（🟡 待确认）完全同构，不需要新造一档。
风险高的两站（Reckitt、上海强生）**直接标「仅内部核对，不公开引用」**，不进 CSV。

### 3.2 工程面

| 指标 | 数值 |
|---|---|
| 可稳定 `web_fetch` 的站 | **2 / 6（33%）**：`bayer.com.cn`（静态页）、`panadol.com` |
| 半可用（部分页面需 JS） | **1 / 6**：`bayer.com.cn` 的**产品列表**需 JS（静态页不用） |
| 需 JS 渲染才能读正文 | **3 个站**：`bayer.com.cn`（列表层）、`nurofen.co.uk`（全站 React）、`kenvue.com`（全站） |
| 硬阻断（403/反爬，记不可用） | **2 个站点组**：Redoxon 系（含 `bayer.com`、`bayer.com.au`）、`tylenol.com` |
| 条款禁止自动采集（技术上可读也不抓） | **2 个站**：`nurofen.co.uk`、`jntlch.com.cn` |

**抓取频率建议**（如果采纳这 2 个可用站点）：
- **不做定时任务、不写爬虫**。品牌消费页一年改不了几次，按「**事件驱动 + 季度复核**」：新品/包装换代/用户报错时才人工取一次，记 `retrieved_at`。
- 硬上限：**单站单次 ≤ 20 页**，**≤ 1 请求/秒**，带可识别 UA + 联系邮箱；遇到 `Crawl-delay`（如 Kenvue 10 s）就按它来或直接放弃。
- 渲染只用于「人工看一眼」，**渲染结果不入库、不进 `data/raw/`**（避免把受条款限制的正文缓存进仓库）。

### 3.3 价值面

| 用途 | 能不能解决 | 依据 |
|---|---|---|
| **剂型核对**（用户报的力度伸问题） | ✅ **能** | 拜耳中国原文写「力度伸® 维生素C泡腾片」，而现库 CN 来源是「片剂」（`form_base=tablet`，1000 mg，铝管 10/30 片） |
| **规格核对** | ✅ **部分能** | Panadol GB 500 mg 片/胶囊与 `dmd` 3 行一致；但**官网没有规格的品规**（力度伸不写 1 g、泰诺不写 325/500 mg）→ 规格仍以监管来源为准 |
| **品牌家族**（力度伸 ↔ Redoxon） | ⚠️ **只解一半** | 「力度伸® 是拜耳在售品牌」✅ 可查；「力度伸 = Redoxon（同一品牌的中/英名）」**拿不到**——Redoxon 全线 403。这条仍要靠人工表 + 包装/说明书等其他出处 |
| **反例（说明不能当数据源）** | —— | Panadol GB 现库有 `Paracetamol 500mg **soluble tablets sugar free**`，官网 11 个 SKU 里没有对应页 → 官网只覆盖消费级 SKU，**替不了监管登记簿** |

---

## 4. 两个可落地的例子（品牌 → 成分 → 剂型，带出处）

### 例 1：力度伸（CN）——把「看着像错的」变成「有厂商出处的差异」

| 项 | 内容 |
|---|---|
| 厂商出处 | `https://www.bayer.com.cn/zh-cn/portfolio/products-from-a-to-z`（2026-11-10；列表需 JS 渲染） |
| 原句 | 「**力度伸® 维生素C泡腾片**」；同页类目「健康消费品 / 维生素与补充剂」；适应症一行「增强机体抵抗力，用于预防和治疗各种急、慢性传染性疾病或其他疾病…」 |
| 现库（只读现查） | `力度伸` · CN · `dosage_form=片剂` · `form_base=tablet` · `1000 mg` · 包装「铝管包装，10片/盒」「铝管包装，30片/盒」· `source_id=nhsa` · MAH 拜耳医药保健有限公司（2 行） |
| 可落地做法 | 名字页/单包装表的剂型列旁边加一行「**厂商页面：力度伸® 维生素C泡腾片（拜耳中国）**」+ 链接 + 抓取日期，配 `reports/form-effervescent-20261110.md` §3.3 的 R1「来源粒度说明」 |
| 为什么比 R2 好 | R2 要动唯一的人工表（`brand_family`）并波及 redoxon 家族 8 个 key，需人拍板；这一条**零数据改动、零口径风险**，且证据是可点开的厂商页 |
| 边界 | 官网**不给规格**（没有 1 g）→ 规格仍写 nhsa 原文；不写服法、不写替代 |

### 例 2：Panadol（GB）——规格与剂型的双向核对（一次核对 = 一致 / 缺页）

| 项 | 内容 |
|---|---|
| 厂商出处 A | `https://www.panadol.com/en-gb/adult-products/panadol-original-tablets/` →「**500mg Paracetamol**」「Panadol Original Tablets are round and **film-coated**」 |
| 厂商出处 B | `https://www.panadol.com/en-gb/adult-products/panadol-500mg-capsules/` →「**500mg Paracetamol**」「Panadol Capsules are the first and only **liquid paracetamol capsules**」 |
| 现库（只读现查） | `panadol` · GB · 3 行：`Paracetamol 500mg tablets`(tablet) · `Paracetamol 500mg soluble tablets sugar free`(tablet) · `Paracetamol 500mg capsules`(capsule)，全部 500 mg，`source_id=dmd` |
| 核对结果 | 片 ↔ 片 ✅ 一致；胶囊 ↔ 胶囊 ✅ 一致；**「soluble tablets sugar free」官网无对应 SKU** ❌ → 官网覆盖不全，只能做「佐证」，不能做「补全」 |
| 可落地做法 | 把这两行写进 `data/sources/brand_corroboration.csv`（已落），供将来名字页显示「厂商页面」链接；同时把「官网缺 soluble SKU」写进报告的缺口清单，**不要**因此判定 dmd 那条可疑 |

> 附（仅内部，不上公开页）：泰诺 `jntlch.com.cn` 列出 4 条产品线（酚麻美敏片=复方 / 对乙酰氨基酚缓释片 / 氨酚拉明片 / 混悬滴剂+口服混悬液），而现库 CN 泰诺 5 行只记「片剂 / 片剂(薄膜衣) / 口服溶液剂 / 口服混悬剂」，**不区分复方与单方、不标缓释**。这是一条内部质量线索（「来源粒度」问题的第二个实例），因条款限制不公开引用。

---

## 5. 建议的数据结构（已落地的小快照）

`data/sources/brand_corroboration.csv`（**5 行，只放公开可引用的 2 个站点**）：

```
brand,inn,form,strength,country,source_url,quote,retrieved_at,license_status
```

| 字段 | 说明 |
|---|---|
| `brand` | 商品名（与 `name_key.norm` 同形，便于对照） |
| `inn` | 英文通用名（`ascorbic acid` / `loratadine` / `clotrimazole` / `paracetamol`），与 `substance` 表口径一致 |
| `form` | **`form_base` 词表值**（`effervescent`/`tablet`/`liquid`/`capsule`），不是官网原文措辞 |
| `strength` | 原样带单位（`500 mg`）；官网不写的留空，**不推断** |
| `country` | ISO-2，与 `product.country` 同词表 |
| `source_url` | 厂商页 URL（不是首页） |
| `quote` | ≤200 字原文摘录，原样不改写 |
| `retrieved_at` | 抓取日期（`YYYY-MM-DD`） |
| `license_status` | 受控词表，见下 |

`license_status` 词表（本试点只用到前两档）：

| 值 | 含义 | 可否公开引用 |
|---|---|---|
| `conditional-noncommercial-attribution` | 条款允许个人/非商业使用；须署名 + 短摘录 + 链接 | ✅ 可以（本 CSV 全部此值） |
| `internal-only` | 条款禁止抓取或禁止传播 | ❌ 不入 CSV |
| `unavailable-waf` | 403 / 反爬，未取得任何数据 | ❌ 不入 CSV |
| `ok-open` | 开放许可（本批没有） | ✅ |

**为什么不进 `product` 表**：这张 CSV 是「品牌 × 市场 × 字段」的**佐证层**，不产生产品行、不参与碰撞推导、不参与剂量对应。它只回答「这条事实有没有一个可点开的厂商出处」。若将来要展示，建议在名字页做一个独立小节「厂商页面（核对出处）」，与 `source` 表分开署名。
**登记位置**：若采纳，应在 `docs/许可清单.md` 新增 §2.10「厂商官网（核对用途）」分组，按站登记 🟡/🔴，并同步 `data/sources/README.md` 的文件说明（本试点未改这两处，等拍板）。

---

## 6. 边界与红线（本次已遵守）

1. **不绕 WAF**：Redoxon / `bayer.com` / `bayer.com.au` / `tylenol.com` 全部 403 → 记「不可用」，未换 UA、未换 IP、未用镜像/缓存站替代。
2. **只引事实**：没有复制说明书、SmPC、CMI 正文，没有下载 Packshot 图片。
3. **不做批量**：单次逐页请求；渲染只为判断「是否需 JS」，结果不入库、不进 `data/raw/`。
4. **不给用药建议**：本报告与 CSV 只有「品牌 ↔ 成分 ↔ 剂型 ↔ 规格」身份事实，没有适应症用法、没有剂量换算、没有替代判断。
5. **只读**：未执行任何写库命令；未改 `site/build.py` / `etl/**` / `db/**`。

---

## 7. 待人工决策 / 下一步建议

| # | 事项 | 建议 | 谁 |
|---|---|---|---|
| 1 | Haleon / 拜耳中国条款都是「个人、非商业使用」，公开站引用 ≤200 字摘录是否接受 | **接受，但压到最小形态**：只引「品牌® + 成分 + 剂型」这类短事实短语，摘录长度 ≤200 字、逐条署名 + 链接；若法务更保守，就只留链接与字段，不显示原文 | **人**（法务口径） |
| 2 | 把 `bayer.com.cn`、`panadol.com` 登记为 🟡 来源（`docs/许可清单.md` §2.10 + `data/sources/README.md`） | 采纳；顺带给 About 页补一句「厂商页面仅用于核对」的四语说明 | agent（口径确定后） |
| 3 | 力度伸 的展示 | **走「厂商出处 + R1 粒度说明」**，不动 `brand_family`；R2 保持「需人拍板」原状 | **人**（公开口径） |
| 4 | 品牌家族（力度伸 ↔ Redoxon） | 厂商站这条路**关掉**（403）。若要落这条家族关系，需另找可引用出处（包装/说明书扫描、可访问的拜耳年报 PDF——目前 `bayer.com` 也 403） | agent 调研 / **人**拍板 |
| 5 | 是否继续扩站 | **不扩**。6 站里 2 站可用已说明方向成立；再扩只会撞到同一批反爬/条款墙。真正缺的不是站点数量，而是「可引用的品牌家族出处」 | agent |
| 6 | 泰诺 / Nurofen 的内部价值 | 只作内部质量线索（复方/缓释、液填胶囊等粒度缺口），**不公开引用**；如需公开，先拿书面许可 | **人** |

---

## 8. 复核方式（可重跑）

```text
# robots（2026-11-10 实测）
https://www.bayer.com.cn/robots.txt          200  Disallow: (空)
https://www.panadol.com/robots.txt           200  Disallow: /search-results
https://www.nurofen.co.uk/robots.txt         200  Allow: / ; Disallow: /search
https://jntlch.com.cn/robots.txt             200  Disallow: /search/ /user/...（产品页允许）
https://www.tylenol.com/robots.txt           403  Akamai Access Denied
https://www.redoxon.me/robots.txt            403  bot block
https://www.bayer.com/robots.txt             403  bot block
https://www.bayer.com.au/robots.txt          403  bot block
https://www.kenvue.com/robots.txt            200  Crawl-delay: 10

# 条款
https://www.bayer.com.cn/zh-cn/condition-of-use        （个人目的 / 不得商用 / 不得变更）
https://www.terms.haleon.com/en-gb/                    （personal, non-commercial use only）
https://www.reckitt.com/terms-and-conditions/ §3.3     （personal use；禁自动设备收集）
https://jntlch.com.cn/legal-notice §5                  （禁抓取 / 禁复制分发 / 禁系统下载）
https://www.nurofen.co.uk/terms-and-conditions/        （客户端渲染失败，空壳 → 用集团条款）

# 事实页
https://www.bayer.com.cn/zh-cn/portfolio/products-from-a-to-z     （JS 渲染；力度伸® 维生素C泡腾片）
https://www.panadol.com/en-gb/adult-products/panadol-original-tablets/    （500mg Paracetamol / film-coated）
https://www.panadol.com/en-gb/adult-products/panadol-500mg-capsules/      （500mg Paracetamol / liquid capsules）
https://www.nurofen.co.uk/products/nurofen-200mg-tablets/                 （需 JS；200mg / ibuprofen / Tablets）
https://jntlch.com.cn/zh-hans/products/1                                  （泰诺® 四条产品线）
```

现库对照用的只读 SQL（`mode=ro`，未写库）：

```sql
-- 力度伸 / 泰诺 / 开瑞坦 / 凯妮汀 / Panadol / Nurofen 的现库行
SELECT k.norm, p.country, p.dosage_form, p.form_base,
       pc.strength_value, pc.strength_unit, p.pack, p.source_id, p.mah
FROM product p
JOIN product_name pn ON pn.product_id = p.product_id
JOIN name_key k       ON k.key_id = pn.key_id
LEFT JOIN product_component pc ON pc.product_id = p.product_id AND pc.ord = 0
WHERE k.norm IN ('力度伸','泰诺','开瑞坦','凯妮汀','panadol','nurofen','redoxon','tylenol');
```

_本报告为只读试点产物：未写库、未改代码、未发布。CSV 为 5 行人工策展快照，只收公开可引用站点。_
