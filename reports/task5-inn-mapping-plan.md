# task-5 CJK 主名 → INN 映射 — 只读方案与候选实测

> 日期：2026-10-30（北京 07:1x）｜ 状态：**只读准备，未写 `data/drugs.db`、未改 schema**
> 数据：`data/drugs.db`（只读 `mode=ro`）｜候选表：`.tmp/task5/candidates.csv`（1,791 行）、`.tmp/task5/a10.csv`、`.tmp/task5/stats.json`
> 目标：把 1,791 条 CJK `inn_en`（字段名实为「主名」）映射为英文 INN；映射不到按用户口径显示「原文 + 无译名角标」；**不机器翻译、不编造**。
> 关联：`reports/task26-provenance-design.md`（同一迁移窗口）、`reports/task26-provenance-impl.md` §6（15 个 mark 接入点）

---

## 0. 结论（先看这段）

| 项 | 实测 |
|---|---|
| CJK 主名 | **1,791 / 12,649**（`inn_en` 含 CJK；`inn_en == inn_zh`，全部有 ATC，来自 CN 来源） |
| **本地公开来源可映射** | **50 条唯一候选（2.8%）**：10 条 ATC-4 一致（strict）、34 条候选 INN 不在库、6 条低置信；**13 条 ATC 冲突**（拒绝）、**7 条多候选**（拒绝）、**1,721 条无候选** |
| **A10（糖尿病）28 条** | **28/28 无候选**——全是 CN 独有/新药（考格列汀、多格列艾汀、恒格列净…），ATC 只到 5 位（A10BH 等），无法定位到单一 INN |
| 外部免费源可行性 | Wikidata `wbsearchentities`（zh label）可用：15 个常见药抽样 **9 命中（60%）**（甘精胰岛素→insulin glargine、利拉鲁肽→liraglutide、达格列净→dapagliflozin…）；**实测 429 限流**（1.6s/次仍触发），需 ≥2s + 退避重试；1,791 条约 **1–1.5h** |
| 主要障碍 | ① 这些 CJK 名多为 CN 药典/注册名，**不在 WHO INN 清单**（`who_inn_names.csv` 的 `inn_zh` 全空）；② ATC 只有 5 位，无法唯一定位；③ 盐型/复方/生物制品多（salt-like 445 条） |
| 建议 | **Phase A（本轮可做）**：只加 `name_lang` 列 + 回填（CJK→`zh`、其余→`en`），**不改任何名字**；展示侧按用户口径加「无英文译名」角标 → A10 页立刻不再「无标注中文」。**Phase B（可选，需你批准）**：Wikidata 节流批（~1h）生成候选 → 严格规则自动定案（唯一 + ATC 类一致 + 盐型规则）；**Phase C**：15 个 mark 接入（同窗口）。 |

---

## 1. 现状与来源覆盖

| 来源（免费/本地） | 提供的映射 | 对 1,791 条的实际命中 |
|---|---|---|
| `substance.inn_zh` 反查（库内英文主名的中文别名） | 1,324 条 zh→en 对 | **29 条**（其余中文名是 CN 独有主名，无英文对应） |
| `data/cn_inn_overrides.csv`（2,177 行，含 evidence/status） | 417 条可用 zh→INN | **16 条**（其中低置信多为盐型丢盐，见 §3） |
| `data/ingredient_names_i18n.csv` | 2,879 条 name_zh→inn_en | 与库内反查高度重叠，新增少 |
| `data/raw/wikidata/atc_p267.json`（本地缓存，zh/en label 同 QID） | 2,481 条 zh→en 对 | **30 条** |
| `data/cn_name_map.json`（商品名→成分；精确 + 剂型后缀前缀） | 327 + 9 条 | **9 条**（低置信） |
| WHO INN 清单 `who_inn_names.csv` | 1,737 行，**`inn_zh` 全空** | **0**（不含中文名） |
| ChEMBL / RxNorm | 无本地缓存；英文库，无中文名 | **0**（不适用） |

> 说明：**本地来源合计只覆盖 50 条唯一候选（2.8%）**。这类 CJK 名是「CN 注册/药典中文名」，与 WHO INN 的中文译名不是同一套；只靠免费本地库无法批量映射。

## 2. 候选表（`.tmp/task5/candidates.csv`，1,791 行）

| status | 条数 | 说明 |
|---|---:|---|
| `unique` | **50** | 唯一候选；其中 `atc4_ok` 10、候选 INN 不在库 34、低置信 6 |
| `ambiguous` | **7** | 多候选且不一致 → 不写（交给 fallback） |
| `atc_conflict` | **13** | 候选 INN 在库但 ATC 前 4 位不一致 → **拒绝**（例：中文 ATC A07AA vs 候选 J01XB01） |
| `none` | **1,721** | 无任何候选 → fallback |
| 合计 | **1,791** | |

**strict 子集（ATC-4 一致，10 条中的 8 条可读样例）**：复合维生素→multivitamin、酒石酸艾格司他→Eliglustat、乳酸亚铁→Iron、玻璃酸酶→Hyaluronidase、苯甲酸雌二醇→Estradiol、乙酰麦迪霉素→Midecamycin、磷酸雌莫司汀→Estramustine、酒石酸双氢可待因→Dihydrocodeine。

## 3. 质量警告（为什么不能直接用这 50 条）

1. **丢盐/丢离子**：`门冬氨酸钾 → Aspartic Acid`（丢钾）、`亚硒酸钠 → Selenious Acid`（丢钠）、`乳酸亚铁 → Iron`（丢盐）。直接改名会**改变成分身份**，违反「商品名不是主键/不合并身份」的底线。
2. **ATC 只有 5 位**：CN 数据的 ATC 是类目级（A10BH），无法像 7 位码那样唯一定位；用 5 位做校验只能排除明显冲突，不能确认。
3. **低置信来源**：`cn_inn_overrides` 的 `uncertain` 1,654 条、`cn_name_map` 前缀匹配属「商品名推测成分」，只能作候选不能直接写库。
4. **A10 全部无候选**：28 条都是近年 CN 新药（考格列汀/多格列艾汀/恒格列净/依苏帕格鲁肽α…），本地库与 WHO 名单都没有；AWS/维基可能有一部分（如 dorzagliatin、chiglitazar），需 Phase B 才能确认。

## 4. Wikidata 外部源可行性（只读实测，2026-10-30）

```text
GET https://www.wikidata.org/w/api.php?action=wbsearchentities&search=<中文名>&language=zh&uselang=en&format=json&limit=1
```

| 抽样 15 个常见药 | 命中 9（60%） | 未命中 6（其中多次为 429 限流，非「无条目」） |
|---|---|---|
| 命中例 | 甘精胰岛素→insulin glargine (Q417317)、利拉鲁肽→liraglutide、达格列净→dapagliflozin、西格列汀→sitagliptin、维格列汀→vildagliptin、沙格列汀→saxagliptin、阿格列汀→alogliptin、瑞格列奈→repaglinide、那格列奈→nateglinide | |
| 限流 | 连续请求会出现 **HTTP 429**；1.6s/次仍触发，需 2s+ 指数退避 + 单线程 | |
| 耗时估算 | 1,791 条 × 2–3s（含重试）≈ **60–90 分钟**；建议分批（每批 100 条，间隔 30s）并记录失败清单 | |
| 许可 | Wikidata 数据 CC0；API 为公开免费服务（遵守 UA/限流），**不付费、不绕限制** | |

> Phase B 的候选**仍需规则自动定案**（唯一 + ATC 类一致 + 盐型规则 + INN 存在性），不采用「搜到就用」。

## 5. `name_lang` 设计与迁移（与 provenance 同窗口、分开验收）

```sql
-- db/schema.sql（substance 表，新增 1 列）
name_lang TEXT CHECK (name_lang IN ('en', 'zh', 'zh-Hant', 'es', 'other'))
```

| 项 | 方案 |
|---|---|
| 语义 | `substance.inn_en` 改为「canonical 主名」，`name_lang` 标记其语言；中文别名仍在 `inn_zh`；**不改 `inn_en` 名字本身（Phase A）** |
| 回填（确定性，不猜测） | `name_lang = 'zh'` 当 `inn_en` 含 CJK（1,791 条）；否则 `'en'`（10,858 条）；一次性 UPDATE，实测 ~0.7 MB |
| 空值 | 保留 NULL 仅用于「迁移前未分类」（正常迁移后无 NULL）；CHECK 覆盖 5 值 |
| 迁移 | `db/init_db.py` 新增 `_ensure_substance_name_lang()`（`ALTER TABLE ADD COLUMN` + 回填），与 provenance 的 `_ensure_substance_columns` **同一次窗口**执行，分别验收 |
| 回滚 | 备份恢复（推荐）或 `db/migrate_provenance.py` 扩展 DROP `name_lang`（与 4 个 provenance 列同一套脚本） |
| 成本 | ALTER ~0.2s、`+0` 字节；回填 12,649 行 ~0.03s、**+0.7 MB**（与 provenance 实验同量级） |
| 展示（build 侧） | 读 `name_lang` + CJK 检测：非中文 locale 遇到 `name_lang='zh'` → 显示中文原名 + 角标「无英文译名 / No English name recorded」；es 同理「Sin nombre en español」；**不机器翻译** |

## 6. 映射落地（Phase B，写库时）的规则

| 情形 | 处理 |
|---|---|
| 唯一候选 + 候选 INN **不在库** + 盐型规则通过 | **改名**：`inn_en = INN`、`inn_zh = 中文原名`、`name_lang='en'`、`mark_substance(source, method='multi-source'/'rule', confidence)` |
| 唯一候选 + 候选 INN **已在库**（UNIQUE 冲突） | **合并**：把 CJK substance 的 variant 挂到目标 substance（`variant.substance_id` 重指向），迁移昵称/名称，删除 CJK 行；**必须用 manifest 记录 + 可回滚**；产品身份（product_id）不变 |
| 盐型中文名（盐酸/磷酸/钠/钙…445 条） | 先拆盐：base 中文名 → 候选 INN；盐部分映射到 `variant.salt`（hydrochloride/phosphate/sodium…）；**不把盐型名直接改成 base INN**（否则丢盐） |
| 复方/生物制品/多成分（如「德谷胰岛素利拉鲁肽」） | 不映射（fallback），计数 |
| 候选 ATC 冲突 / 多候选 / 无候选 | 不写，计数；走 fallback |
| 旧数据 | 无候选者保持原样，仅补 `name_lang='zh'`；**不伪造 INN** |

## 7. 15 个 mark 接入（与 provenance 合并，同窗口）

按 `reports/task26-provenance-impl.md` §6 的清单（15 个 文件:行号 + 建议 method/confidence）逐个接入 `etl/provenance.py` 的 `mark_substance()` / `mark_family()`；每接一个跑 `py_compile` + 抽 1 个来源 dry-run（不写库）。与 `name_lang` 迁移同一窗口、**分开验收**（先 name_lang 迁移验收 → 再做 mark 接入验收）。

## 8. 验收清单

- [ ] `name_lang` 列：`PRAGMA table_info(substance)` 含该列；CJK 行 `zh`、非 CJK 行 `en`、无 NULL
- [ ] 未映射的 1,741 条保持原 `inn_en`（中文），`inn_zh` 不变；**不出现机器翻译/音译**
- [ ] A10 页（en/es）不再出现「无标注中文」：显示中文原名 + 「无英文译名/Sin nombre en español」角标（build 侧，四语）
- [ ] 映射的子集（Phase B 才写）：`inn_en` 为 INN、`inn_zh` 保留中文、`name_lang='en'`、provenance 已记
- [ ] 计数：substance 总数变化 = −合并数（改名不减少）；`check_data` 前后差异仅预期项；quick/FK ok
- [ ] 回滚：备份恢复或 DROP `name_lang`；副本往返验证
- [ ] 报告：`reports/task5-inn-mapping-plan.md`（本文件）+ 写库后的 `reports/ingredient-name-consistency.md`（task-5 原定报告名）

## 9. 风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 只靠本地源只能映射 2.8%，A10 全无 | 用户口径允许 fallback；Phase B（Wikidata）另批做，不阻塞 v0.9.x |
| 2 | 盐型/离子丢失导致成分身份错误 | 盐型规则 + 不改名只做候选；冲突一律拒绝 |
| 3 | UNIQUE(`inn_en`) 冲突需要合并 | 合并走 manifest + 回滚；先副本验证；不合并无法改名 |
| 4 | Wikidata 429/不稳定 | 2s+ 退避、分批、失败清单；不重试到被封 |
| 5 | `inn_en` 语义变化影响 build/lib | `lib/search.py` 已显式列（task-26）；build 侧按 `name_lang` 适配（task-5 B） |
| 6 | 与 task-26 provenance 同窗口 | 同一 init_db helper、分开验收；先迁移 name_lang 再 mark 接入 |

## 10. 需 Lead 决定

1. **本轮范围**：是否只做 Phase A（`name_lang` 列 + 回填 + fallback），映射（Phase B）另排？还是现在就跑 Wikidata 批（~1h，读只读候选，不写库）？
2. **合并策略**：唯一候选且 INN 已在库时，是否允许**合并** CJK substance（substance 总数会减少，需 manifest/回滚）？还是保守只改名（那部分候选会因 UNIQUE 冲突被跳过）？
3. **`name_lang` 取值**：`en/zh/zh-Hant/es/other` 是否够用（CN 数据只有简体中文；未发现繁体主名）？
4. **fallback 文案**：en「No English name recorded」/ es「Sin nombre en español」/ zh-Hant 对应文案，确认后 build 侧落四语。
5. **15 个 mark 接入**是否与 name_lang 同窗口一起做（建议是，分开验收）。

## 11. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\task5\probe.py            # 只读：生成 .tmp/task5/{candidates,a10}.csv + stats.json
# 输出：CJK 1,791 / unique 50 / ambiguous 7 / atc_conflict 13 / none 1,721；A10 28/28 none
```

_本方案为只读准备：未写 `data/drugs.db`、未改 `db/schema.sql`、未跑 build；候选表在 `.tmp/task5/`。_
