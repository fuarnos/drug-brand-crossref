# 朋友反馈分析与排期（2026-10-30）

> 输入：微信语音转文字 4 张截图（2026-10-30 收到，含 37" / 15" / 6" / 8" / 15" / 3" 六段语音）。
> 范围：**只做产品判断 + 排期入队**；本文不改 DB、不改 `site/build.py`、不发版。
> 数字均为 `data/drugs.db` 只读现查（419,799,040 B / 477,098 产品 / 10 市场，与 v0.9.4 记录一致）。

---

## 0. 结论

- 朋友共提 **12 条**：**采纳 6 条**（其中 2 条并入今晚的 v0.9.5）、**改写成合规表述后采纳 3 条**、**不采纳 2 条**、**与产品无关 1 条**。
- **最值钱的一条**是「US ↔ CN 常用药双向对照」。现库其实已经做到 **CN Top100 成分中 78 个在 US 有产品**、**US Top100 中 63 个在 CN 有产品**；剩余缺口**不是「药太少」**，而是两个数据问题：
  1. **盐型/水合物/别名把同一成分拆成多个 `substance`**（如 `Dextromethorphan Hydrobromide` US 1,982 个产品，CN 侧是 `Dextromethorphan` 183 个产品 → 页面上互相对不上）；
  2. **名称层无成分产品** 3,911 个（US 2,229 / AU 1,495 / MX 121 / SG 66）根本没进成分对照。
  → 这两件正好是 **v0.9.5 task-5 Phase B** 的同一个窗口，**不需要新数据源、不需要新版本**。
- **「按治疗类别分类」这条其实已经做了**：1,154 个 ATC 类目页 + 16 个常见大类 + `/atc.html`。真正缺的是**入口可见**——静态 `<nav>` 只有 5 项（Search / Confused / Warnings / About / What's new），类别与大类没有入口；coverage 页的链接还是 `boot.js` 注入（无 JS 不可见，交接 §8 坑 11）。这条排 **v0.9.6**。
- **明确不做**：① **login**（静态站无后端、无账号体系，且与「只做身份对应 + 隐私最小化」定位冲突）；② **「替代药推荐 / 哪个药能替代哪个」**（红线：不判断两药能否互换，只做同成分跨市场对照 + 既有 `collision` 警示）。

---

## 1. 逐条判定

| # | 原话要点 | 判定 | 落点 / 理由 |
|---|---|---|---|
| 1 | 「相当于做了个 database + filter」 | ✅ 已成立 | 现状即此定位（静态站 + 客户端检索） |
| 2 | 「database 现在也不大，先把市面上常用的药弄上去」 | ⚠️ 改写采纳 | 产品数 477,098 不算小，但**成分×市场**才是「查得到对应」的粒度（每市场唯一成分 1,550–4,440）。真正能补的不是堆量，而是盐型归一 + 名称层补成分 → **task-141** |
| 3 | 「看国内哪些药常用、又能对应美国哪些药，双向扩展」 | ✅ 采纳（最高优先） | 已量化：CN Top100→US 78/100、US Top100→CN 63/100；缺口清单化 → **task-140**（只读审计）+ **task-141**（盐型归一，并入 Phase B） |
| 4 | 「按品种 / 治感冒 / 治什么 分类一下」 | ⚠️ 大部分已完成 | 已有 ATC 1,154 类目 + 16 大类；缺**导航入口**与**客户端口语大类词**（队列既有未排期项）→ **task-142** |
| 5 | 「UI 一定得改，完全没有菜单」 | ⚠️ 部分成立 | 静态 nav 只有 5 项，类别/市场/coverage 不在 nav；coverage 靠 `boot.js` 注入 → **task-142**（含静态化体积评估） |
| 6 | 「没有什么 login」 | ❌ 不采纳 | 静态站无后端、无账号；登录会引入 PII 与「个性化推荐」联想，与「不给用药建议」定位冲突。替代：本地 `localStorage` 收藏/对比（已规划在 B8/v0.9.5） |
| 7 | 「让它（AI）去对齐市面上的药，最好有药监局认证的 source」 | ✅ 已在做 | 10 个官方来源（FDA/EMA/MHRA/TGA/TFDA/HK/HSA/COFEPRIS/AEMPS/NMPA 系）；8 个受限来源标 `non_redistributable`；`docs/许可清单.md`。无需新排期 |
| 8 | 「从 source 找 → 直接做 PDF / Excel 表 → 写成站点当 database」 | ⚠️ 拆分采纳 | Excel/CSV 已有：结果页 CSV 导出（B7）+ `datapackage.json` 4 个聚合资源；**PDF 卡**评估后做单成分/单产品分享卡（无用药建议）→ **task-144**（可选，需许可+体积评估） |
| 9 | 「主页要简洁，就为查数据」 | ✅ 采纳 | 并入既定 UI P1 余项 + **task-143**（首页收敛：一个搜索框 + 3 步引导 + 类别入口） |
| 10 | 「UI 要很多轮一点点改」 | ✅ 认可 | 与现有「每版 1–2 个体验主题」节奏一致，不新增机制 |
| 11 | 「后端没那么难，就是个数据库 + filter，不用接 API」 | ✅ 已如此 | 站点即静态生成 + 客户端 `core.json` 检索，无后端、无 API |
| 12 | 「ChatGPT Plus 邀请给你额度（referral）」 | ➖ 无关 | 与产品无关；截图显示 `This user cannot be referred`，邀请失败。不排期、不进 CHANGELOG |

> 「你这 database 说实话现在也不是很大」这句要澄清口径：**产品 477,098 / 成分 12,649 / 名称 652,909 / 10 市场**；但**单市场成分覆盖**只有 1,550（SG）–4,440（US），这才是朋友体感的来源，也是 task-140 要审计的对象。

---

## 2. 证据（只读现查，可复跑）

### 2.1 CN 高频成分 → 其他市场有没有对应产品

| # | 成分（中文 / INN） | CN 产品 | US | GB | AU |
|---|---|---|---|---|---|
| 1 | 葡萄糖 / Glucose | 6,546 | 0 | 261 | 254 |
| 2 | 对乙酰氨基酚 / Acetaminophen | 4,299 | 3,482 | 443 | 707 |
| 5 | 阿莫西林 / Amoxicillin | 1,907 | 483 | 211 | 72 |
| 9 | 盐酸二甲双胍 / Metformin | 1,308 | 630 | 358 | 141 |
| 10 | 马来酸氯苯那敏 / Chlorphenamine | 1,164 | **0** | 0 | 0 |
| 12 | 苯磺酸氨氯地平 / Amlodipine | 1,047 | 560 | 197 | 135 |
| 14 | 安乃近 / Metamizole | 1,029 | **0** | 0 | 0 |
| 15 | 阿司匹林 / Aspirin | 1,024 | 731 | 206 | 82 |
| 17 | 布洛芬 / Ibuprofen | 999 | 1,332 | 384 | 301 |

→ CN 侧「0 对应」的多是**中国特有注册 / 这些市场未上市**（氯苯那敏、安乃近、诺氟沙星），这类应做**「该市场未收录」解释**，不是补数据。

### 2.2 US 高频成分 → CN 有没有对应产品

| # | 成分（INN / 中文） | US 产品 | CN |
|---|---|---|---|
| 1 | Zinc Oxide / 氧化锌 | 4,544 | 18 |
| 2 | Acetaminophen / 对乙酰氨基酚 | 3,482 | 4,299 |
| 3–8 | Octisalate / Avobenzone / Octocrylene / Homosalate / Octinoxate / Titanium Dioxide | 1,702–3,309 | **0**（防晒剂，非处方药范围外） |
| 9 | **Dextromethorphan Hydrobromide** / — | **1,982** | **0** |
| 14 | Phenylephrine / — | 1,549 | 0 |
| 15 | Guaifenesin / 愈创甘油醚 | 1,439 | 18 |
| 16 | Ibuprofen / 布洛芬 | 1,332 | 999 |

→ 真正的「查不到」缺口两类：**① 防晒/化妆类成分（应排除在药品对照外）**、**② 盐型拆分**（右美沙芬 HBr 在 US 1,982 个，CN 在 `Dextromethorphan` 183 个 → 两个记录互不可见）。

### 2.3 盐型拆分的实证（task-5 Phase B 的直接收益）

| substance | US | CA | CN | TW | HK | GB | AU |
|---|---|---|---|---|---|---|---|
| Dextromethorphan Hydrobromide | 1,982 | 739 | 0 | 0 | 128 | 0 | 0 |
| Dextromethorphan | 19 | 1 | **183** | 379 | 0 | 28 | 1 |

同一成分被拆成两个 `substance`，两边都有产品却彼此看不到——**做盐型归一后，US↔CN 同名对照会立刻多出一批**。量级可估：US Top100 缺 CN 的 37 条里，防晒类约 7 条、盐型/别名类约 5–8 条，其余是「市场未上市」。

### 2.4 覆盖口径（每市场唯一成分 / 产品数）

`CN 3,064/145,051 · US 4,440/107,950 · GB 3,747/61,051 · CA 3,045/43,847 · AU 3,192/43,299 · ES 2,131/25,395 · TW 1,868/16,457 · HK 1,625/13,935 · MX 1,955/10,757 · SG 1,550/5,445`
（注：这里按「有成分的产品」计，故与全库产品数有差；无成分产品 US 2,229 / AU 1,495 / MX 121 / SG 66。）

### 2.5 复现命令（只读，均可直接跑）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# ① CN Top20 成分 + 其 US 产品数
& $py db/q.py "WITH cn AS (SELECT v.substance_id sid, COUNT(DISTINCT p.product_id) n FROM product p JOIN product_component pc ON pc.product_id=p.product_id JOIN variant v ON v.variant_id=pc.variant_id WHERE p.country='CN' GROUP BY 1), us AS (SELECT v.substance_id sid, COUNT(DISTINCT p.product_id) n FROM product p JOIN product_component pc ON pc.product_id=p.product_id JOIN variant v ON v.variant_id=pc.variant_id WHERE p.country='US' GROUP BY 1) SELECT s.inn_en, cn.n CN, IFNULL(us.n,0) US FROM cn JOIN substance s ON s.substance_id=cn.sid LEFT JOIN us ON us.sid=cn.sid ORDER BY cn.n DESC LIMIT 20"

# ② 盐型拆分实证（右美沙芬）
& $py db/q.py "SELECT s.inn_en, v.salt, p.country, COUNT(DISTINCT p.product_id) n FROM product p JOIN product_component pc ON pc.product_id=p.product_id JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id WHERE s.inn_en LIKE 'Dextromethorphan%' GROUP BY 1,2,3 ORDER BY n DESC"

# ③ 单市场唯一成分数 / 无成分产品数
& $py db/q.py "SELECT p.country, COUNT(DISTINCT v.substance_id) FROM product p JOIN product_component pc ON pc.product_id=p.product_id JOIN variant v ON v.variant_id=pc.variant_id GROUP BY 1"
```

> 明细表（CN/US Top20 全表、Top100 汇总）留在 `.tmp/friend-feedback/audit.md`（本地工作区，不入库）；本文已抄录关键行。


---

## 3. 排期

### 3.1 并入 **v0.9.5**（今晚 00:35 谷段起，不加新版本）

| 任务 | 内容 | 与既有计划的关系 |
|---|---|---|
| **task-140** 常用药双向对照审计（只读，今晚出） | CN Top100 / US Top100 逐条标注：有对应 / 盐型拆分 / 市场未上市 / 名称层无成分 / 范围外（防晒化妆）；产出缺口清单与可执行修复项；不写库 | 为 task-5 Phase B 提供目标集合，零风险 |
| **task-141** 盐型/水合物/别名归一规则表 | 用 `variant.salt` + 规则表把同一成分的盐型归到一个 base（不做身份合并、不改产品身份，只做**展示与对照层**归并）；难判的丢弃并计数 | 并入 task-5 Phase B 同窗口、分开验收；**DB 写需 Lead 批准 + manifest 回滚** |

> 原 v0.9.5 清单（Phase B INN 映射、15 个 `mark_substance()` 接入、U4–U7/B8/B9/B11、EMA）**不变**，task-140/141 作为 Phase B 的输入与伴生项，不抢排期。

### 3.2 排 **v0.9.6**（下一谷段，体验/导航版）

| 任务 | 内容 | 备注 |
|---|---|---|
| **task-142** 导航与发现入口 | 静态 nav 补「按类别 / 按市场 / 覆盖与新鲜度」；`/atc.html`、16 大类从 nav 可达；客户端口语大类词同步（退烧药/感冒药等 ~60 条） | 静态化 coverage 链接约 +9–10 MB，**需重算 900 MiB 预算**（当前 898.24 MiB，接近上限），先出预算再动手 |
| **task-143** 首页收敛 | 首屏 = 一个搜索框 + 3 步说明 + 类别入口 + 最近更新；去掉与「查数据」无关的堆叠 | 与既有 UI P1 余项合并做，避免两次改首页 |
| **task-144** 分享卡（含 PDF 卡，可选） | 单成分/单产品一页 PDF 或图片卡：名称/成分/规格/市场覆盖/「不可互换」提示；**不含用药建议与剂量方案** | 需先评估许可（8 个 `non_redistributable` 来源）+ 体积；做不了就只做图片卡（B11 已排） |

### 3.3 不排期 / 不做

| 项 | 结论 |
|---|---|
| login / 账号体系 | ❌ 不做。静态站无后端；引入账号与隐私成本，且与「不给用药建议、不做个性化推荐」冲突 |
| 「替代药推荐 / 何时药性相似」 | ❌ 不做推荐。只做**同成分跨市场对照**，互换风险一律引用既有 `collision` / `dose_warning` 结论 |
| 防晒/化妆品成分对照 | ❌ 范围外（US 榜前列多为防晒活性成分）；在 task-140 里标「非药品」并在口径页说明 |
| referral / Codex 工具链 | ➖ 与产品无关，不入队 |

---

## 4. 两件待拍板事项的结论（2026-10-30 已定）

1. **导航静态化体积** → **维持 900 MiB 上限**，不为此加页。导航入口（task-142）采用「顶层页静态 + 长尾页 boot.js 注入」的折中；ATC4 事实清单（task-145）走「JSON 明细（~0.1 MB gzip）+ 每成分紧凑徽章（+~0.4–0.6 MB）」，**不做全静态 12,367 行明细表**。腾空间由 **task-146** 出预算表（combo stub / 名字页长尾 / core 瘦身 / 模板复用），不删数据、不改 URL。
2. **PDF 导出** → 暂不做全量；只做单成分/单产品**分享卡**（task-144，无用药建议），受限来源（8 个 `non_redistributable`）保持只发派生层。
3. **服务器**（追加结论）→ 用户 2026-10-30 授权「后面可以租服务器」，但**明确排在 UI 改完之后**；方案与触发条件已落 `docs/服务器迁移路线.md`，本周期不动（task-147，触发式）。

---

## 5. 一句话

朋友的方向（常用药双向对照 + 分类 + 更干净的 UI）与项目路线一致；真正可执行的三件事已经落到 **v0.9.5 task-140/141（盐型归一 + 覆盖审计）** 与 **v0.9.6 task-142/143/144/145/146（导航/首页/分享卡/ATC4 事实清单/体积预算）**；login 与「替代推荐」按红线不做；服务器迁移排在 UI 批之后（task-147）。
