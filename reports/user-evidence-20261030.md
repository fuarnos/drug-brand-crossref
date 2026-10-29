# GoatCounter 真实行为数据 → 用户需求证据（2026-10-30）

> 任务：task-30 ｜ 性质：**只读**（GoatCounter API v0，cookieless）；未改站点、未写库、未提交。
> 数据窗口：**2026-09-30T00:00:00Z → 2026-10-31T00:00:00Z**（近 30 天，UTC）；生成于 **2026-10-30 01:56 北京**（2026-10-29 17:56 UTC）。
> 站点 `drug-brand-crossref`；token 打码 `qsea…6oyc`（只在 `.env`，报告不含明文）；原始数据 `.tmp/analytics/raw-30d.json`（不入库）。
> 结论先行，**样本极小**：本报告 = 观测基线 + 埋点质量检查，**不能当作用户需求结论**。

---

## 0. 结论（先看这 6 条）

1. **可用的真实用户样本 ≈ 0**：30 天只有 **103 次记录**（PV **81** + 事件 **22**）、**3 个活跃日**（10-27 14 次、10-28 23 次、10-29 66 次），其余 **27 天为 0**；全部 103 次集中在 **7 个小时桶**内（单小时 2–34 次、相邻小时多为 0）→ 更像**自测/审计/发布验证流量**，不是自然用户。**「谁来了 / 什么语言 / 搜什么 / 哪里放弃」只能给弱信号或「无法回答」。**
2. **没有外部获客**：103 次里 **站内自引用 86**（`fuarnos.github.io` 自身导航）+ **直接访问 13** + GitHub deployments **2** + **微信内置浏览器拦截页 2**（`weixin110.qq.com`）→ **搜索引擎/社交渠道 0**。站点处于「已上线但未触达」；分享/渠道比 UI 细节更缺。
3. **搜索埋点有真实缺陷（唯一硬证据，可行动）**：13 条 search 事件 = 13 个不同词、各 1 次；其中 **5 条是「盐酸左旋西替利嗪」的逐字输入中间态**（`盐酸西` / `盐酸左旋` / `盐酸左旋西` / `左旋盐酸` / `盐酸xi'ti'li'q`），另 1 条**重复词**（`cetirizine cetirizine`）→ **前端在每次输入时发送搜索事件**（缺提交时/去抖/前缀合并），搜索词统计被中间态稀释。**建议 v0.9.1 修埋点后再谈搜索词需求。**
4. **零结果数据为 0，不能解释为「没有零结果需求」**：`search0-*` 埋点自 **v0.8.2（2026-10-29）** 才有，窗口内只覆盖 1 天；且当天搜索多为前缀中间态。**零结果 Top 50 = 0 条**（详见 §5）。
5. **语言维度拿不到**：GoatCounter `languages` **103/103 全是 `(unknown)`**（采集/API 限制）→ 语言偏好只能用路径间接看：`/zh/` 5、`/es/` 3、`/zh-hant/` 2、根路径 5、`?lang=` 15（含语言切换），**不能当作用户语言偏好证据**。
6. **与 UX 审计对照**：`reports/ux-audit-20261030.md` 的 **5 个 P0 全部没有直接行为证据**（样本太小）；仅有的弱信号是「同一查询跨 3 个语言入口各试 1 次」`?q=Excedrin+Extra+Strength`、「4 次国家筛选事件」`country-CN/ALL/TW`、「3 次结果点击」`click-result`。**P0 仍应按可用性证据（截图/DOM）修，不能因行为数据缺失而降级。**

---

## 1. 数据与口径

| 项 | 值 |
|---|---|
| 窗口 | 2026-09-30 → 2026-10-31（UTC） |
| 总记录（含事件） | **103** |
| PV / 事件 | **81 / 22** |
| 活跃天数 | **3**（10-27、10-28、10-29） |
| 不同页面路径 | 71（另 18 条事件路径） |
| 国家 | US 102、RU 1 |
| 浏览器 / 系统 | Chrome 103；Windows 102、Linux 1 |
| 屏幕档位 | desktop 102、tablet 1、phone **0**、unknown 0 |
| 语言（GoatCounter） | `(unknown)` 103（不可用） |
| 搜索事件 / 零结果 | **13 / 0**；不同查询 13、零结果词 0 |
| 来源 | 站内 86、直接 13、GitHub deployments 2、微信拦截页 2、其他 0 |

> 口径：GoatCounter 的 `hits` 含页面浏览与自定义事件；`events` 是 `search-*`、`search0-*`、`click-*`、`country-*` 等。API **不提供独立访客数**（只有 hits / total_events / total_utc），也不提供 UA/IP/ASN。统计自 v0.4.1（2026-10-26）接入，**30 天窗口里 27 天无数据是「未接入/无访问」，不是「用户不感兴趣」**。

### 查询命令（可复核，只读）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'

# 用 deploy/analytics_report.py 的只读客户端拉数据（输出到 .tmp/analytics，不写 reports/）
& $py .tmp\analytics\pull.py       # 9 次 API 调用（0.3s 间隔，4 req/s 限速内），写 .tmp/analytics/raw-30d.json
& $py .tmp\analytics\analyze.py    # 汇总表（页面类型/语言入口/搜索词/来源）

# 官方脚本（会写 reports/metrics + reports/analytics-*.md；本次为遵守写范围未直接跑）
& $py deploy\analytics_report.py --start 2026-09-30T00:00:00Z --end 2026-10-31T00:00:00Z
& $py deploy\analytics_report.py --start 2026-09-30T00:00:00Z --end 2026-10-31T00:00:00Z --search-weekly
```

> `pull.py` 复用 `deploy/analytics_report.py` 的 `GoatCounter`/`aggregate`（token 从 `.env` 读、打码输出），只把 JSON 落到 `.tmp/analytics/`；未改脚本、未写 `reports/metrics`。

---

## 2. 谁来了（结构：桌面为主，疑似自测）

### 2.1 每日与小时分布（UTC）

| 日期 | 记录数 | 命中小时（UTC，括号为次数） | 读法 |
|---|---:|---|---|
| 2026-10-27 | 14 | 14 时（14） | 单小时爆发 |
| 2026-10-28 | 23 | 12 时（23） | 单小时爆发 |
| 2026-10-29 | 66 | 2 时（10）、5 时（34）、7 时（17）、13 时（3）、14 时（2） | 三个峰值 |
| 其余 27 天 | 0 | — | 无访问 |

- **判断（置信度中）**：单小时 2–34 次（3 个高峰 14/23/34）、相邻小时多为 0、Chrome/Windows/desktop 100%、US 102/103 → 与**团队自测（点击/截图/冒烟/发布验证）**的特征一致；无法剔除（GoatCounter 后台是否配置 skip-dev 未知）。
- 若按北京时间看，峰值落在 **10:00–15:00 与 20:00–22:00**（北京）区间，跨时区解释不唯一；本报告不据此推断「用户习惯」。
- 设备：**桌面 102 / 平板 1 / 手机 0**；但「30 天没有手机访问」只能说明**目前没有移动用户进来**，不能反证移动 P0 不重要（见 §7）。

### 2.2 语言入口（间接）

| 入口 | 记录数 | 说明 |
|---|---:|---|
| 根 `/`（含 `/index.html`） | 5 | 默认 en |
| `/zh/` 首页 | 2 | 简体中文 |
| `/es/` 首页 | 2 | 西语 |
| `/zh-hant/` 首页 | 1 | 繁体 |
| `/index.html?lang=zh` | 2 | 语言切换落到中文首页 |
| 语言子页 `/zh/*`、`/zh-hant/*` | 3 | whats-new ×2、confused ×1 |
| 带 `?lang=` 的页面（About / warn / what's-new / cat 等） | 15 | 四值 `en/es/zh/zh-Hant` 都有；是除站内导航外最明显的交互 |

> 语言切流「15 次 `?lang=`」无法区分用户与自测；GoatCounter 自带 languages 维度不可用（103/103 unknown）。

---

## 3. 从哪来（渠道：几乎全站内）

| 来源 | 次数 | 类型 | 读法 |
|---|---:|---|---|
| `fuarnos.github.io/drug-brand-crossref/*`（站内导航） | **86** | 站内（h） | 站内互点；不代表外部用户 |
| 直接访问（无 referrer） | **13** | 直接（o） | 浏览器地址栏/书签/隐私模式 |
| `github.com/fuarnos/drug-brand-crossref/deployments/github-pages` | 2 | 外链 | GitHub 部署页 |
| `weixin110.qq.com` | **2** | 外链 | **微信内置浏览器安全拦截页**（打开链接后先到该域，非文章阅读） |
| 搜索引擎 / 社交 / 其他 | **0** | — | 无 |

- 站内来源细项（前 8）：`index.html` 16、`atc/A10.html` 13、`whats-new.html` 5、`warn.html` 5、`zh/index.html` 5、`zh` 4、`cat/allergy|diabetes|weight-loss` 各 4。
- **关键判断**：没有搜索引擎/外部渠道流量 → **发现与分享是当前第一瓶颈**；`weixin110.qq.com` 说明有人在微信里打开过（2 次到拦截页），但**不能证明内容被阅读**，也提示微信内打开体验需要单独验证（https/UA/拦截页）。

---

## 4. 看什么（页面类型与 Top 路径）

### 4.1 页面类型分布（PV，共 81）

| 类型 | PV | 占比 | 说明 |
|---|---:|---:|---|
| 成分页 `/drug/*` | **28** | 34.6% | 核心页；`acetaminophen` 2、`cetirizine` 2，其余多为 1 |
| 工具/说明页（about/warn/whats-new/confused，含 `?lang=` 变体） | **15** | 18.5% | `confused.html` 2、`whats-new` 2、`about` 1、`warn` 1，其余为语言变体 |
| 首页/语言入口（`/`、`/index.html`、`/zh`、`/es`、`/zh-hant`） | **12** | 14.8% | 根 5、`/zh` 2、`/es` 2、`/zh-hant` 1、`/index.html?lang=zh` 2 |
| 大类页 `/cat/*` | **11** | 13.6% | allergy/diabetes/weight-loss/statins 等各 1，`diabetes` 有 4 个语言变体 |
| 商品名页 `/name/*` | **6** | 7.4% | 含单包装页（`xenical`、`jentadueto`、`欧唐宁`、`甘舒霖30R` 等） |
| `?q=` 深链搜索页 | **3** | 3.7% | 同一查询 `Excedrin Extra Strength` 在 `/`、`/zh/`、`/es/` 各 1 |
| 语言子页（`/zh/*`、`/zh-hant/*`） | **3** | 3.7% | whats-new ×2、confused ×1 |
| ATC（`atc.html` + `/atc/A10.html`） | **2** | 2.5% | — |
| 组合页 `/combo/*` | **1** | 1.2% | 复方感冒药组合 |
| 厂家页 `/maker/*` | **0** | 0% | 30 天内无访问 |

### 4.2 Top 路径（前 20，PV）

| # | 路径 | 次数 |
|---:|---|---:|
| 1 | `/`（首页，含 `/index.html`） | 4 |
| 2 | `/confused.html` | 2 |
| 3 | `/drug/acetaminophen.html` | 2 |
| 4 | `/drug/cetirizine.html` | 2 |
| 5 | `/es` | 2 |
| 6 | `/index.html?lang=zh` | 2 |
| 7 | `/whats-new.html` | 2 |
| 8 | `/zh` | 2 |
| 9 | `/?q=Excedrin+Extra+Strength` | 1 |
| 10 | `/about.html`（及 `?lang=en/es/zh` 各 1） | 1+3 |
| 11 | `/atc.html` / `/atc/A10.html` | 1 / 1 |
| 12 | `/cat/allergy.html` / `antidepressants` / `antihypertensives` / `asthma-copd` / `corticosteroids` / `diabetes`（+en/es/zh-Hant）/ `weight-loss` | 各 1（diabetes 合计 4） |
| 13 | `/combo/acetaminophen+chlorphenamine+dextromethorphan+pseudoephedrine.html` | 1 |
| 14 | `/name/xenical.html`、`/name/jentadueto.html`、`/name/excedrin-extra-strength-pain-reliever.html`、`/name/dna-pancreas-formula.html`、`/name/甘舒霖30r.html`、`/name/欧唐宁.html` | 各 1 |
| 15 | `/drug/canagliflozin.html`、`/drug/linagliptin.html`、`/drug/sitagliptin-*.html`、`/drug/trazodone.html`、`/drug/phentermine-resin.html`、`/drug/acetohexamide.html`、`/drug/cn-*.html` | 各 1 |
| 16 | `/zh/whats-new.html`、`/zh/confused.html`、`/zh-hant`、`/zh-hant/whats-new.html` | 各 1 |

**读法（弱）**：成分页是主要落点（34.6%），且 `acetaminophen`/`cetirizine` 有重复访问 → 与「搜索品牌名后要进成分页确认」的路径一致（见 §6），但次数太少，**不能当证据**。

---

## 5. 搜什么（13 条搜索事件全表）

> 全部 13 条，各 1 次；均为药品名/输入中间态，**不含个人信息**（GoatCounter 只记归一化查询文本 ≤64 字符）。

| # | 查询 | 次数 | 归类 |
|---:|---|---:|---|
| 1 | `benadryl` | 1 | 英文商品名 |
| 2 | `cetirizine` | 1 | 英文 INN |
| 3 | `cetirizine cetirizine` | 1 | **重复词**（疑似重复发送） |
| 4 | `excedrin extra strength` | 1 | 英文商品名（另 3 次走 `?q=` 深链） |
| 5 | `lipitor` | 1 | 英文商品名 |
| 6 | `泰诺` | 1 | 中文商品名 |
| 7 | `开瑞坦` | 1 | 中文商品名 |
| 8 | `左西替利嗪` | 1 | 中文通用名 |
| 9 | `左旋盐酸` | 1 | **输入中间态**（盐酸左旋西替利嗪，语序不同） |
| 10 | `盐酸西` | 1 | **输入中间态** |
| 11 | `盐酸左旋` | 1 | **输入中间态** |
| 12 | `盐酸左旋西` | 1 | **输入中间态** |
| 13 | `盐酸xi'ti'li'q` | 1 | **输入中间态**（拼音分片） |

- **中间态 5/13（38%）**、**重复 1/13（8%）**：说明搜索事件在**每次输入**时发送（未见提交/去抖），会把一个查询拆成多条、并污染 Top 词与零结果率。**这是本报告唯一「可行动的硬证据」**。
- `?q=` 深链 3 次：同一查询 `Excedrin Extra Strength` 在 `/`、`/zh/`、`/es/` 各 1 次（语言切换/分享链接测试特征）。
- `泰诺`/`开瑞坦`/`左西替利嗪` 等中文查询存在 → 中文用户（或我们）用中文商品名/通用名找药；`benadryl`/`lipitor`/`cetirizine` 说明英文入口也在用。

### 零结果词 Top 50（`search0-*`）

**0 条**——区间内没有 `search0-*` 事件。

- 原因 1：`search0-*` 埋点自 **v0.8.2（2026-10-29）** 才上线，窗口内只覆盖 1 天；
- 原因 2：当天的搜索多为前缀中间态（如 `盐酸西`），前端命中前不触发零结果；也可能是这些词都能命中（`cetirizine`/`benadryl`/`lipitor`/`泰诺` 均有结果）；
- **不能**据此说「没有零结果需求」；修埋点（提交时发送、前缀合并）后再看。

---

## 6. 哪里放弃（问题无法用现有埋点回答）

现有埋点能看到的「下一步」只有：

| 事件 | 次数 | 说明 |
|---|---:|---|
| `click-result` | 3 | 结果行点击（**不带排名/查询/页面**，无法归因） |
| `click-whatsnew` | 2 | What's new 点击 |
| `country-CN` / `country-ALL` / `country-TW` | 2 / 1 / 1 | 结果页国家筛选（**唯一的筛选使用证据**） |

- **缺漏斗**：没有「搜索 → 结果页 → 成分页/矩阵 → 名称页」的会话级序列；GoatCounter 也不提供会话；无法判断「进成分页后无下一步」。
- `?q=Excedrin Extra Strength` 3 次（三个语言入口）但对应 `click-result` 无法归因 → **不能判断是否放弃**。
- 结论：**「哪里放弃」本轮无法回答**；需先补埋点（见 §8）。

---

## 7. 与 UX 审计 P0/P1 对照（`reports/ux-audit-20261030.md`）

| UX 审计项 | 级别 | 本次行为证据 | 判断 |
|---|---|---|---|
| **C-1 / P0-2 同成分表混入不同成分** | P0 | 搜 `泰诺` 1 次后，`drug/acetaminophen.html` 2 PV、复方 combo 页 1 PV（无查询归因） | **无直接证据**；间接弱信号（<5），不改变其 P0 |
| **C-2 / P0-3 搜品牌名结果看不到品牌** | P0 | `click-result` 3 次不带排名/查询；`泰诺`/`benadryl`/`lipitor` 搜索后无对应名称页点击记录 | **无证据**（埋点不足，不能证伪） |
| **F-1 / P0-4 移动端首屏无反馈** | P0 | phone **0** / 103；tablet 1 | **无证据**；且「没有手机访客」不能反证移动不重要（说明还没触达移动用户） |
| **M-1 / C-7 / P0-5 矩阵默认列/筛选按钮无效** | P0 | `country-CN` 2、`country-ALL` 1、`country-TW` 1（4 次筛选） | **弱支持**：确实有人用国家筛选；但无「筛选按钮点击/空选」埋点，不能量化 |
| C-3 厂家页「剂量」列实为剂型 | P1 | `/maker/*` **0 PV** | **无证据**（30 天无人到厂家页） |
| C-4 名称页英文表头 / I-1 data-label | P1 | `/name/*` 6 PV；`?lang=` 15 次（切换语言时最易暴露表头问题） | **弱信号**：有名称页访问与语言切换，但无「表头语言错误」埋点 |
| C-5 H1 混入版本号 | P1 | `about`/`whats-new`/`drug` 页有访问，但无法从 hits 判断 H1 内容 | **无证据** |
| C-6 ATC 中文类名中英拼接 | P1 | `atc.html` 1 + `atc/A10.html` 1；`atc/A10.html` 作为站内来源 13 次 | **弱信号**：A10 是常用入口之一 |
| E-1 零结果无下一步入口 | P1 | `search0-*` 0 条（埋点仅 1 天） | **无法验证** |
| E-5 404 无搜索框 | P1 | 无 404 路径命中（GoatCounter 页面路径里没有 404） | **无证据** |
| **新增（审计未列）** | — | **搜索埋点逐字中间态 5/13 + 重复 1/13** | **P1（埋点质量）→ v0.9.1 修** |
| **新增（审计未列）** | — | **无外部来源；微信拦截页 2 次** | **P1（渠道/分享）→ B11 分享卡 + 微信打开验证** |

> 说明：UX 审计的 P0 来自可复现的 DOM/截图证据，**不因行为数据缺失而失效**；本表只回答「行为数据是否支持它」，答案是：**暂不支持（样本太小），但也不反驳**。

---

## 8. 证据 → 建议任务

| # | 证据 | 建议任务（v0.9.1 / 后续） | 优先级 |
|---|---|---|---|
| 1 | 搜索中间态 5/13、重复 1/13；事件无页面/语言上下文 | **埋点修复**：只在「提交/停止输入 ≥500ms」发送；前缀去重（同一会话只发最终词）；`search` 事件编码 `lang`/`market`（如 `search:zh:泰诺`）；零结果也同样编码 | **P1（v0.9.1）** |
| 2 | 无搜索引擎/社交来源；微信拦截页 2 | **渠道**：B11 分享卡优先；验证微信内打开（https、UA、拦截页原因）；外部分享带 UTM（GoatCounter `campaigns` 维度可用） | **P1** |
| 3 | 4 次国家筛选（CN/ALL/TW） | 矩阵 P0 修复（M-1/C-7）保持 v0.9.1；补 `filter-apply` / `filter-empty` 埋点 | P0（按审计） |
| 4 | 结果点击 3 次无归因 | 补 `result_click`（带 rank/成分/市场，不含个人信息）；补 `matrix_expand`、`name_open`；形成「搜索→结果→成分→名称」漏斗 | P1 |
| 5 | 语言维度 unknown；`?lang=` 15 次 | 不用 GoatCounter 判语言；用路径 + `lang` 参数 + 后续小样本调查；i18n P1 批按审计修 | P1 |
| 6 | 30 天 103 次、3 天、疑似自测 | **观测计划**（见 §9）：先解决「有没有人来」，再谈「来了怎么用」 | — |

---

## 9. 限制与观测计划

**限制（必须写进任何引用本报告的结论）**

- **无独立访客数**（API 只有 hits/events），**无 UA/IP/ASN/登录/会话**；事件不带页面与语言上下文。
- **样本极小**：103 hits / 13 次搜索 / 3 天；任何比例都只是「这 103 次里」的描述，**没有统计意义**；不能外推到真实用户。
- **无法剔除自测流量**（无 skip-dev 配置证据；Chrome/Windows/desktop + 单小时爆发符合自测特征）。
- **统计接入晚**：v0.4.1（2026-10-26）接入；30 天里 27 天为 0；`search0-*` 仅 v0.8.2（10-29）起。
- 语言维度 `(unknown)`；微信 referrer 是拦截页，不能证明阅读；GoatCounter 按 UTC 聚合，与北京/洛杉矶时区不同。
- GoatCounter 免费版数据保留期有限 → 建议每 2 周把 JSON 落盘到 `reports/metrics/`（已有先例）。

**观测计划（等流量）**

1. **排除自测**：GoatCounter 后台配置 skip-dev（按 UA/IP）或另开 property；团队冒烟/截图流量单独标记。
2. **埋点规范（v0.9.1 一起发）**：`search` 提交时发送 + 前缀去重 + 带 `lang`/`market`；`search0` 同上；`result_click(rank)`、`filter_apply(country)`、`filter_empty`、`matrix_expand`、`name_open`、`share_click(channel)`。
3. **渠道与归因**：分享卡/微信/知乎/医生社群；外链带 UTM（`?utm_source=wechat…`，GoatCounter `campaigns` 已支持）。
4. **复跑节奏**：v0.9.1 发布后每 2 周跑一次 `--search-weekly`（或本报告的 `.tmp/analytics/pull.py`）+ 落盘 JSON；**门槛 ≥1,000 PV、≥300 搜索事件、≥30 零结果** 才出「用户需求证据 v2」。
5. **在此之前**：UX P0/P1 按可用性证据执行，不用「没有行为数据」当降级理由。

---

## 10. 复现与证据

| 文件 | 内容 |
|---|---|
| `.tmp/analytics/pull.py` | 只读拉取（复用 `deploy/analytics_report.py`），9 次 API 调用，输出 `raw-30d.json` |
| `.tmp/analytics/analyze.py` | 汇总（页面类型/语言入口/搜索词/来源/事件） |
| `.tmp/analytics/raw-30d.json` | 原始数据（totals/paths/events/dims/search），不入库 |
| `deploy/analytics_report.py` | 官方脚本（4 req/s 限速、token 打码、`--search-weekly`） |

- token：`.env` 的 `GOATCOUNTER_TOKEN`，报告只写打码值 `qsea…6oyc`。
- 本报告不改站点、不写 `data/drugs.db`、不提交；GoatCounter 只读查询。
