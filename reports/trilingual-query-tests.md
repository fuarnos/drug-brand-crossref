# 三语（en / es / zh）检索一致性测试报告

> 任务：`task-14`「三语检索一致性测试集」 · 日期：2026-10-26 · 数据：`data/drugs.db`（v0.3.3 线上同源，只读打开）
> 范围：**只用现有三种界面语言（en / es / zh）+ 现有 7 个市场**，不新增语言/市场、不改 schema、不写库、不跑 `site/build.py`。
> 产物：`tests/trilingual/run_tests.py`（可复跑测试集）· `.tmp/trilingual/results.json`（逐条明细）· 本报告。

---

## 1. 结论摘要

**整体结论：三语检索的主干是通的——96.6% 的查询在 Top-5 内落到同一成分，67/72 个案例三语全部一致，跨国商品名 72/72 都能带出。真正需要修的是 3 类「结构性断链」，不是零散的数据缺失。**

| 指标 | 结果 |
|---|---|
| 测试案例 | **72**（single 49 · salt 6 · er 4 · combo 5 · dup_inn 5 · zh_only 3） |
| 查询总数 | **354**（en 123 / es 116 / zh 115） |
| Top-5 命中同一成分 | **342 / 354 = 96.6%** |
| Top-1 命中同一成分 | **336 / 354 = 94.9%**（en 91.9% / es 96.6% / zh 96.5%） |
| 案例级三语一致通过 | **67 / 72 = 93.1%** |
| 跨国可见（不指定国家也能带出他国商品名） | **72 / 72** |
| 硬失败（某语言 0 结果或落到别的成分） | **5 个案例 / 12 条查询** |
| 软失败（Top-5 内但非 Top-1） | 6 条查询 |
| 运行时长 | 约 562 秒（354 查询 + 约 210 次国家视图查询；检索层模糊匹配是主要耗时） |

**Top 3 断链（按影响面排序）：**

1. **中文 3 字通用名「幽灵精确命中」→ 0 结果**：`舍曲林`、`氟西汀`、`喹硫平` 三例。根因在 `lib/search.py:157`：`_resolve_keys()` 无条件把查询本身当作 exact key，而库里只有「盐酸舍曲林片」这类带盐型/剂型前缀的 key；于是返回一个不存在的 key → 0 产品，且错误提示"名字对上了，但没有在售产品"。**这一条同时打掉中文三字药名的一大类（中文 key 中长度 ≤3 字的有 4,569 个）**。
2. **同一药在中/英/西命名体系下被拆成两个 `substance`**：如 cyclosporine/ciclosporin、beclomethasone/beclometasone、chlorpheniramine/chlorphenamine、diosmectite/diosmectita；ES/MX 专属 `substance` 有 **1,515 个**，抽样 20 对里至少 13 对是英文名的西语写法重复。表现为：英文查询落到 A 成分、西语查询落到 B 成分，成分页/国家视图对不上。
3. **CN 复方产品只挂 1 个成分**：`西格列汀二甲双胍片` 的 126 个产品全部只有 `Sitagliptin` 一个 component（二甲双胍丢失）；全库 CN 名称含"复方"但只挂 1 个成分的产品有 **6,010 个**。这会连带 D2/D3 的复方判定失效。

---

## 2. 测试方法

### 2.1 被测对象与判定标准

- 检索层：直接 import **`lib/search.py` 的 `SearchIndex`**（不改代码、不 SQL 复刻），测的就是线上站点的检索行为。
- 每个案例：指定一个**期望成分 `substance_id`**，构造 en/es/zh 各 1–2 条查询（INN、本地商品名、中文通用名、盐型名、复方名）。
- 单条查询判定：结果卡（`SearchResult.cards`）里前 10 张卡的 `substances` 是否包含**期望成分的 `inn_en`**；命中位置 = rank。`Top-5 命中` = rank < 5，`Top-1` = rank == 0。
- 案例判定：三语中所有"有查询的语言"都至少有一条查询命中期望成分（Top-5）。
- 附加检查：
  - **国家视图**：按该语言主场国家（en → US/GB/CA/AU 中第一个有产品的；es → ES/MX；zh → CN）带 `country=` 过滤重查第一条查询，必须命中。
  - **跨国可见**：不指定国家时，结果卡覆盖的国家里必须包含该成分在其他市场的国家（该语言只测本国名字时，用于验证"查一个国家的名字能看到其他国家商品名"）。
- **已知不可判定的情况**：`氨茶碱` 在库里是 Aminophylline（另一成分），不算 theophylline 的断链；日/韩等语言不在本次范围。测试集首轮有 3 条自测错误（diltiazem 的 ES 品牌写成了 verapamil 的 Manidon 等），已修正后重跑，本报告数字来自修正后的 `run2` 结果（`.tmp/trilingual/run2.log`）。

### 2.2 测试集覆盖

| 维度 | 覆盖 |
|---|---|
| 市场 | US / GB / CA / AU / ES / MX / CN（每种语言的主场国家都有） |
| 分类 | 单方 49、盐型 6（苯磺酸/盐酸/酒石酸/琥珀酸/硫酸氢/左甲状腺素钠）、缓释 4（硝苯地平控释、琥珀酸美托洛尔缓释、单硝酸异山梨酯、非洛地平）、复方 5（阿莫西林克拉维酸、缬沙坦氨氯地平、西格列汀二甲双胍、厄贝沙坦氢氯噻嗪、泰诺四成分）、跨语言 INN 拆分 5、中文专属/旧名 3 |
| 名字类型 | INN、本地商品名（Lipitor/Eutirox/达美康/络活喜…）、中文通用名、旧名/俗称（安定、芬必得、扑热息痛、伟哥）、复方名 |

测试集以 **DB 勘查结果为依据**：每条查询名都先在 `name_key` / `product_name` 里核实过存在（见 `.tmp/trilingual/existence.txt`），不是凭空写的英文名。

### 2.3 复跑方式

```bash
# Windows 项目根目录
C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe tests\trilingual\run_tests.py
# 指定明细输出 / 只跑部分案例
python tests/trilingual/run_tests.py --json .tmp/trilingual/results.json --only amlodipine,metoprolol
```

- 脚本用 `sqlite3` URI **`mode=ro`** 打开 `data/drugs.db`（`_ro_connect` 拦截 `sqlite3.connect`），只读、不建表、不写库；
- 退出码：0 = 72 例全过；1 = 有失败（可用于 CI 卡口）；
- 结果明细（每条查询的 Top-1/成分集合/国家/指纹层级）在 `.tmp/trilingual/results.json`。

---

## 3. 通过 / 失败总表

### 3.1 按分类

| 分类 | 案例数 | 通过 | 查询数 | Top-5 命中 | Top-1 命中 | 说明 |
|---|---|---|---|---|---|---|
| single 单方 | 49 | **49** | 275 | 271 (98.5%) | 268 (97.5%) | 主干最稳，三语都通 |
| salt 盐型 | 6 | **6** | 17 | 17 (100%) | 16 (94.1%) | 盐型名都能落到碱基成分 |
| er 缓释 | 4 | **4** | 18 | 18 (100%) | 18 (100%) | 控释商品名（拜新同/Toprol-XL/欣康）正常 |
| combo 复方 | 5 | 4 | 16 | 15 (93.8%) | 14 (87.5%) | 唯一失败：CN 复方成分拆分 |
| dup_inn 跨语言 INN 拆分 | 5 | 2 | 15 | 9 (60.0%) | 9 (60.0%) | 3 对硬断链（见 §4.2） |
| zh_only 中文专属/旧名 | 3 | 2 | 13 | 12 (92.3%) | 11 (84.6%) | diosmectite 中英 substance 拆分 |

### 3.2 按语言

| 语言 | 查询数 | Top-5 命中 | Top-5 率 | Top-1 命中 | Top-1 率 |
|---|---|---|---|---|---|
| en | 123 | 118 | 95.9% | 113 | 91.9% |
| es | 116 | 113 | 97.4% | 112 | 96.6% |
| zh | 115 | 111 | 96.5% | 111 | 96.5% |

**读法**：es 单看命中率最高，但这是因为西语查询多以「西语 INN 精确匹配」进入；真正的断链集中在"同一药英文名/西语名落到不同 substance"（§4.2）和中文三字名（§4.1）——这两类会被分类口径掩盖，必须按失败类型看。

### 3.3 硬失败案例（5 个）

| 案例 | 分类 | 失败语言与查询 | 实际落到 |
|---|---|---|---|
| sertraline | single | zh `舍曲林` → 0 结果（"名字对上了，但没有在售产品"） | — |
| fluoxetine | single | zh `氟西汀` → 0 结果 | — |
| quetiapine | single | zh `喹硫平` → 0 结果 | — |
| metformin | combo | zh `西格列汀二甲双胍片` → Top-1 只有 Sitagliptin | Sitagliptin（二甲双胍丢失） |
| ciclosporin | dup_inn | en `cyclosporine`、es `ciclosporina` → 落到 **Cyclosporine**（期望 Ciclosporin） | Cyclosporine |
| beclometasone | dup_inn | en `beclomethasone`、es `beclometasona` → 落到 **Beclomethasone** | Beclomethasone |
| chlorphenamine | dup_inn | en `chlorpheniramine`、es `clorfenamina` → 落到 **Chlorpheniramine** | Chlorpheniramine |
| diosmectite | zh_only | en `diosmectite` → 落到 **Diosmectita** | Diosmectita |

> 注：前 3 行是**查询级失败**（案例靠本地品牌名仍然通过，但中文通用名这一条会 0 结果）；后 5 行是**案例级失败**（三语中至少一种语言没有一条查询落到期望成分）。`albuterol/salbutamol`、`rifampin/rifampicin` 两对虽然库里也有两个 substance 记录，但名称归一化把它们正确合并到了同一成分，**用本测试集验证通过**，说明"拆分"不是必然断链，取决于归一化是否覆盖到该写法。

### 3.4 软失败（Top-5 命中但 Top-1 不对，6 条）

| 查询 | 期望 | Top-1 | 原因 |
|---|---|---|---|
| `escitalopram` / `lexapro`（en）· `escitalopram`（es） | Escitalopram | **Escitalopram Oxalate** | 盐型被建成了独立 `substance`（`inn_en='Escitalopram Oxalate'`），应归并到 Escitalopram |
| `clopidogrel bisulfate`（en） | Clopidogrel | **Clopidogrel Bisulfate** | 同上，盐型独立 substance |
| `augmentin`（en） | Amoxicillin | **Co-Amoxiclav** | 复方被抽象成"Co-Amoxiclav"成分，与 Amoxicillin 并列，用户看到的是第三成分 |
| `metamizole`（en） | Metamizole | **Methimazole** | 模糊匹配把 `metamizole` 误配到甲巯咪唑（fuzzy tier，0.55 权重）；西语 `metamizol` 正常 |

---

## 4. 失败归类、根因与修复建议

### F1【P0】中文 3 字通用名：幽灵 exact key → 0 结果（3 例）

**现象**：`舍曲林`、`氟西汀`、`喹硫平` 返回 0 卡，提示"名字对上了，但没有在售产品"。

**根因**（已用代码 + SQL 双向确认）：

- `lib/search.py:157` 的 `_resolve_keys()` 第一行 `add(n.norm, "exact")` **不检查该 key 是否真的存在**；
- 库里 `name_key` 没有 `舍曲林`（SQL 实测 `key exists=False`），产品挂在 `盐酸舍曲林片`(47 个产品)、`盐酸氟西汀胶囊`(26)、`富马酸喹硫平片`(59) 上；
- 由于 exact 已"命中"，后续 prefix/contains/fuzzy 扩展仍然执行，但 `contains` 条件 `len(n.norm) >= 4`（L165）把 3 字中文名挡掉；prefix 要求 key 以查询开头，而真实 key 以「盐酸/富马酸」开头 → 全部落空；
- 结果：`keys=['舍曲林'(exact)]` → 查产品 0 行 → 提示误导。
- 同结构还影响 `布洛芬`这类"恰好在库里存在 exact 空壳/裸名"的情况（布洛芬 exact 表项存在且挂了 23 个产品，所以侥幸通过）；**没有裸名 key 的 3 字药名必挂**。中文 key 中长度 ≤3 的共 **4,569 个**，带剂型后缀的中文 key **4,370 / 11,914（36.7%）**。

**修复建议（改 `lib/search.py`，须建站 owner 执行）**：

1. `_resolve_keys()`：exact 仅当 `n.norm in self._key_set` 时才 `add(...,'exact')`；否则从 prefix/contains/fuzzy 起找。建议 `SearchIndex.__init__` 顺手建 `self._norm_set = {norm}`（现有 `self._norms` 已有全部数据，O(1) 判断）。
2. `contains` 长度门槛按文字区分：`len(n.norm)>=4` 对拉丁文合理，对 `han` 应为 **>=2**（中文 2 字药名也有意义，如「安定」走昵称、但「华法林」3 字必须能 contains 到「华法林钠片」）。
3. 兜底：当 resolved keys 查询产品为 0 时，回退一次"去盐型/去剂型后的 contains 搜索"，或把「去盐型前缀」的别名 key 在 ETL 阶段写好（`盐酸舍曲林片` 同时生成 `舍曲林` 别名 key 挂同一批 product_name）。
4. 测试：在 `tests/trilingual/run_tests.py` 的 F1 三例即为回归用例（修好后应 100%）。

**预期收益**：直接修复 3/72 案例；按中文 key 结构推算，能覆盖"裸名不存在、只有盐型+剂型名"的一大类中文查询（4,569 个短 key 场景中受影响部分），**推断**中文 Top-5 命中率可到 98%+。

### F2【P1】同一药被拆成多个 `substance`（3 例硬失败 + 13 对实锤 + 1,515 个候选）

**现象**：英文名与西语名各落到一个 substance：`cyclosporine↔ciclosporin`、`beclomethasone↔beclometasone`、`chlorpheniramine↔chlorphenamine`、`diosmectite↔Diosmectita`。

**规模证据**（只读 SQL）：

- 只有 ES/MX 产品的 substance：**1,515 个**；抽样 20 对里 **13 对**可确认是英文 INN 的西语写法/拼写变体：
  `nystatin/nistatina`、`dimethicone/dimeticona`、`cinnarizine/cinarizina`、`chlorthalidone/clortalidona`、`triamcinolone/triamcinolona`、`medroxyprogesterone/medroxiprogesterona`、`chloramphenicol/cloranfenicol`、`pinaverium/pinaverio`、`ferrous/hierro`、`diosmectite/diosmectita` 等；
- 另有盐型被建成独立成分：`Escitalopram Oxalate`、`Clopidogrel Bisulfate`、`Co-Amoxiclav`（复方抽象）；
- 因 CIMA 用西语名 `resolve()` 时"没对上英文成分就新建 substance"（`etl/ingest_cima.py` 的 `resolve` 分支），MX 同样按自己的 INN 拼写建成分。

**修复建议**：
1. 建**成分别名归并表**（不新增语言/市场，纯数据）：`substance_alias(alias_sid, canonical_sid, source)` 或复用现有 `ALIASES` 思路落库；把上面 13+ 对写成映射，脚本把 `variant.substance_id` 改到 canonical，并删/标 retired 的重复 substance。
2. ETL 侧：CIMA/MX 的 `resolve()` 增加"西语↔英语 INN 规则映射表"（-ina→-ine、-ol、-ilo、-ina 等词尾规则 + 常用药白名单），对不上时才新建。
3. 盐型 substance 归并：`inn_en` 含 salt 词的 substance 应降为 variant（与 `variant.salt` 方案对齐，参考 D2 任务报告）。
4. 测试：F2 三类案例修好后应从 60% → 100%。

**预期收益**：3/72 案例转通过 + 消除成分页"同药两个成分页"的长期隐患（1,515 个候选里预计 300–600 个可自动归并，其余需人工）。

### F3【P1】CN 复方产品成分未拆分（1 例）

**现象**：`西格列汀二甲双胍片` 的 126 个产品全部只有 1 个 component（Sitagliptin），search 的国家视图/卡片看不到 metformin。

**规模证据**：CN 产品 146,347；多成分产品只有 3,048（2.1%）；名称含"复方"但只挂 1 个成分的产品 **6,010 个**；该复方 126 个产品 `max_comp=1`。

**根因**：`etl/ingest_nhsa.py` 用 `mapper.resolve(注册名称)` 只解析出**一个**主成分，`product_component` 只落一行；复方（尤其"xx二甲双胍片""xx氨氯地平片"这类以 ATC 首成分为名的复方）丢掉了其他成分。

**修复建议**：
1. ETL：对 `注册名称` 做成分切分（按已知成分名词表做最长匹配，如 西格列汀+二甲双胍；氨氯地平+缬沙坦；厄贝沙坦+氢氯噻嗪），多成分时按顺序写 `product_component(ord=0,1,...)`；
2. 先用「名称含 '复方' 或能切出 ≥2 个已知成分」的 6,010 个 CN 产品做 dry-run 统计，人工抽检 top 100 后入库；
3. 与剂量任务（D3 复方配比）共用这套切分结果，避免二次开发。

### F4【P2】本地商品名/停售状态的覆盖缺口（1 条硬失败 + 若干国家视图空）

- `levaquin`（en，US 品牌）：`name_key` 命中但 US 产品全是 `discontinued`，默认 `include_status=('active',)` → 0 结果，提示"名字对上了，但没有在售产品"。**这是产品策略问题**：撤市药保留在库（设计如此），但检索默认只返回在售 → 用户搜老品牌得到空。建议：结果页在 0 条时自动 fallback 显示"仅在撤市记录中存在"并列出（带灰色徽标），或检索默认 `active+discontinued` 但排序/标注。
- 国家视图空样本：`metformina`+ES 直接查有 10 张卡（23 个 active 产品），但用例首条查询的国家视图出现 0 卡——原因是同一西语 INN 的产品分散在多个 key（`metformina` / `metformina xxx` / 复方名），国家过滤后按 key 分组丢失；建议国家视图不要只取首条查询，而是合并该语言全部查询后再过滤（测试脚本能力，非产品 bug，记录以便站点侧复核）。
- `beloken retard`（ES 缓释商品名）不在库：CIMA 只进了部分商品名，属于覆盖缺口（与 D2/D3 的数据补全同一批工作）。

### F5【P2】中文旧名/别名表覆盖不足

- `埃索美拉唑`（esomeprazole 的旧中文名）在 `name_key` 中 **0 命中**（现在通用名是 `艾司奥美拉唑`）；`止血环酸`（氨甲环酸旧名）同样 0 命中。
- 现有 `nickname` 只有 **57 条**（覆盖 扑热息痛/安定/芬必得/伟哥 等常见旧名，这些全部测试通过）；旧名（埃索美拉唑、止血环酸、胃复安已测通过）建议按"有公开出处才新增"的既有规则补到 100–200 条。
- 另：`name_key` 的 `lang` 字段全为 NULL（135,081 行），三语无法按语言字段区分，只能靠 `script`；不影响本次主流程，但会影响未来"同名跨语言"排序策略，建议后续 ETL 填 `lang`。

### F6【P3】长尾 Top-1 精度

- `metamizole` → Top-1 **Methimazole**（fuzzy 误配）；建议对拉丁短词（≤10 字符）提高 fuzzy 阈值或要求首字母一致，或给 `drug_term`/INN 建立精确别名。
- `augmentin` → Top-1 `Co-Amoxiclav`（复方抽象成分）：建议检索结果卡把"复方抽象成分"折叠进成分列表而不是作为独立 substance 展示，或把 `Co-Amoxiclav` 归并为 `Amoxicillin+Clavulanate` 组合签名。

---

## 5. 修复优先级与预期

| 优先级 | 修复项 | 改动位置 | 影响面 | 预期 |
|---|---|---|---|---|
| **P0** | 幽灵 exact key + 中文 contains 长度门槛 | `lib/search.py:146-182`（`_resolve_keys`） | 0 案例（靠品牌名通过）/ 3 条查询 + 3 个国家视图；潜在 4,569 个短中文 key 场景 | 恢复 3 条中文通用名查询；中文命中率预计 +1–3pt |
| **P1** | 成分别名归并（西语/英式 INN、盐型 substance） | 新增 `substance_alias` + ETL resolve 规则（CIMA/MX） | 4 案例 / 7 条查询；1,515 个 ES/MX 候选 | +4 案例；跨语言一致性质变 |
| **P1** | CN 复方成分拆分 | `etl/ingest_nhsa.py` product_component 循环 | 1 案例 / 1 查询；6,010 个 CN 复方产品 | 复方检索与 D3 复方判定同时受益 |
| **P2** | 停售/撤市名 fallback；ES 国家视图合并查询 | `lib/search.py` 结果空分支 / `site/build.py` 结果页 | 1 条硬查询 + 国家视图 | 减少"查不到"误导 |
| **P2** | 中文旧名扩展（埃索美拉唑等） | `data/sources` + `nickname` 种子 | 2 条查询（本次未列入硬失败表） | 用户输入旧名可查 |
| **P3** | 拉丁短词 fuzzy 精度、复方抽象成分折叠 | `lib/search.py:168-178`、`site/build.py` 卡片 | 2 条软失败 | Top-1 更准 |

**通过率预期（推断）**：F2+F3 修好后案例级 67→**72/72**；F1 修好后查询级恢复 3 条中文通用名与 3 个国家视图。整体查询级 Top-5 命中率 96.6% → **99%+**；Top-1 94.9% → 97%+。以上为按失败根因推算，需按本测试集回归验证。

---

## 6. 复现与证据文件

| 文件 | 内容 |
|---|---|
| `tests/trilingual/run_tests.py` | 测试集（72 案例、354 查询、内核只读打开 DB）；运行约 9 分钟 |
| `.tmp/trilingual/results.json` | 每条查询的 rank、Top-1、成分集合、国家、匹配层级、国家视图结果 |
| `.tmp/trilingual/run2.log` | 修正测试集后的完整运行输出（本报告数字来源） |
| `.tmp/trilingual/analysis.txt` | 失败/软失败/案例级明细的机读汇总 |
| `.tmp/trilingual/existence.txt` | 测试集里每条查询名在 DB 中的存在性核验（避免"查不存在的东西"） |
| `.tmp/trilingual/rootcause.txt` / `rootcause2.txt` | F1–F3 的 SQL/代码证据 |
| `.tmp/trilingual/audit1.txt`、`candidates.txt` | DB 勘查：name_key 分布、三语 brand 候选、ES-only substance 规模 |

### 附：全案例逐条结果（自动生成）

| # | substance | 分类 | en 查询（Top-1 命中） | es 查询 | zh 查询 | 案例 |
|---|---|---|---|---|---|---|
| 1 | `acetaminophen` | single | ✓acetaminophen · ✓tylenol | ✓paracetamol · ✓gelocatil | ✓对乙酰氨基酚 · ✓泰诺林 | ✓ |
| 2 | `ibuprofen` | single | ✓ibuprofen · ✓advil | ✓ibuprofeno · ✓ibudol | ✓布洛芬 · ✓芬必得 | ✓ |
| 3 | `atorvastatin` | single | ✓atorvastatin · ✓lipitor | ✓atorvastatina · ✓cardyl | ✓阿托伐他汀 · ✓立普妥 | ✓ |
| 4 | `amlodipine` | single | ✓amlodipine · ✓norvasc | ✓amlodipino · ✓norvas | ✓氨氯地平 · ✓络活喜 | ✓ |
| 5 | `metoprolol` | single | ✓metoprolol · ✓lopressor | ✓metoprolol · ✓beloken | ✓美托洛尔 · ✓倍他乐克 | ✓ |
| 6 | `aspirin` | single | ✓aspirin · ✓ecotrin | ✓aspirina · ✓adiro | ✓阿司匹林 · ✓拜阿司匹灵 | ✓ |
| 7 | `clopidogrel` | single | ✓clopidogrel · ✓plavix | ✓clopidogrel · ✓plavix | ✓氯吡格雷 · ✓波立维 | ✓ |
| 8 | `omeprazole` | single | ✓omeprazole · ✓prilosec | ✓omeprazol · ✓losec | ✓奥美拉唑 · ✓洛赛克 | ✓ |
| 9 | `pantoprazole` | single | ✓pantoprazole · ✓protonix | ✓pantoprazol · ✓anagastra | ✓泮托拉唑 · ✓泮立苏 | ✓ |
| 10 | `metformin` | single | ✓metformin · ✓glucophage | ✓metformina · ✓eucreas | ✓二甲双胍 · ✓格华止 | ✓ |
| 11 | `gliclazide` | single | ✓gliclazide · ✓diamicron | ✓gliclazida · ✓diamicron | ✓格列齐特 · ✓达美康 | ✓ |
| 12 | `glimepiride` | single | ✓glimepiride · ✓amaryl | ✓glimepirida · ✓amaryl | ✓格列美脲 · ✓亚莫利 | ✓ |
| 13 | `sitagliptin` | single | ✓sitagliptin · ✓januvia | ✓sitagliptina · ✓januvia | ✓西格列汀 · ✓捷诺维 | ✓ |
| 14 | `levothyroxine` | single | ✓levothyroxine · ✓synthroid | ✓levotiroxina · ✓eutirox | ✓左甲状腺素 · ✓优甲乐 | ✓ |
| 15 | `prednisone` | single | ✓prednisone | ✓prednisona · ✓dacortin | ✓泼尼松 · ✓强的松 | ✓ |
| 16 | `dexamethasone` | single | ✓dexamethasone · ✓decadron | ✓dexametasona · ✓fortecortin | ✓地塞米松 | ✓ |
| 17 | `sertraline` | single | ✓sertraline · ✓zoloft | ✓sertralina | ✗舍曲林 · ✓左洛复 | ✓ |
| 18 | `fluoxetine` | single | ✓fluoxetine · ✓prozac | ✓fluoxetina | ✗氟西汀 · ✓百优解 | ✓ |
| 19 | `escitalopram` | single | ◐escitalopram · ◐lexapro | ◐escitalopram · ✓cipralex | ✓艾司西酞普兰 · ✓来士普 | ✓ |
| 20 | `diazepam` | single | ✓diazepam · ✓valium | ✓diazepam · ✓valium | ✓地西泮 · ✓安定 | ✓ |
| 21 | `lorazepam` | single | ✓lorazepam · ✓ativan | ✓lorazepam · ✓orfidal | ✓劳拉西泮 · ✓罗拉 | ✓ |
| 22 | `quetiapine` | single | ✓quetiapine · ✓seroquel | ✓quetiapina | ✗喹硫平 · ✓思瑞康 | ✓ |
| 23 | `olanzapine` | single | ✓olanzapine · ✓zyprexa | ✓olanzapina · ✓zyprexa | ✓奥氮平 · ✓再普乐 | ✓ |
| 24 | `levetiracetam` | single | ✓levetiracetam · ✓keppra | ✓levetiracetam · ✓keppra | ✓左乙拉西坦 · ✓开浦兰 | ✓ |
| 25 | `sildenafil` | single | ✓sildenafil · ✓viagra | ✓sildenafilo · ✓viagra | ✓西地那非 · ✓万艾可 | ✓ |
| 26 | `finasteride` | single | ✓finasteride · ✓proscar | ✓finasterida · ✓proscar | ✓非那雄胺 · ✓保列治 | ✓ |
| 27 | `tamsulosin` | single | ✓tamsulosin · ✓flomax | ✓tamsulosina · ✓omnic | ✓坦索罗辛 · ✓哈乐 | ✓ |
| 28 | `allopurinol` | single | ✓allopurinol · ✓zyloric | ✓alopurinol · ✓zyloric | ✓别嘌醇 | ✓ |
| 29 | `colchicine` | single | ✓colchicine · ✓colcrys | ✓colchicina | ✓秋水仙碱 | ✓ |
| 30 | `cetirizine` | single | ✓cetirizine · ✓zyrtec | ✓cetirizina · ✓zyrtec | ✓西替利嗪 · ✓仙特明 | ✓ |
| 31 | `loratadine` | single | ✓loratadine · ✓claritin | ✓loratadina · ✓clarityn | ✓氯雷他定 · ✓开瑞坦 | ✓ |
| 32 | `fexofenadine` | single | ✓fexofenadine · ✓allegra | ✓fexofenadina · ✓telfast | ✓非索非那定 | ✓ |
| 33 | `diltiazem` | single | ✓diltiazem · ✓cardizem | ✓diltiazem · ✓lacerol | ✓地尔硫䓬 · ✓恬尔心 | ✓ |
| 34 | `verapamil` | single | ✓verapamil | ✓verapamilo · ✓manidon | ✓维拉帕米 | ✓ |
| 35 | `meloxicam` | single | ✓meloxicam · ✓mobic | ✓meloxicam · ✓movalis | ✓美洛昔康 · ✓莫比可 | ✓ |
| 36 | `loperamide` | single | ✓loperamide · ✓imodium | ✓loperamida · ✓fortasec | ✓洛哌丁胺 · ✓易蒙停 | ✓ |
| 37 | `rivaroxaban` | single | ✓rivaroxaban · ✓xarelto | ✓rivaroxaban · ✓xarelto | ✓利伐沙班 · ✓拜瑞妥 | ✓ |
| 38 | `amoxicillin` | single | ✓amoxicillin · ✓amoxil | ✓amoxicilina | ✓阿莫西林 | ✓ |
| 39 | `azithromycin` | single | ✓azithromycin · ✓zithromax | ✓azitromicina · ✓zitromax | ✓阿奇霉素 · ✓希舒美 | ✓ |
| 40 | `levofloxacin` | single | ✓levofloxacin · ✗levaquin | ✓levofloxacino · ✓tavanic | ✓左氧氟沙星 · ✓可乐必妥 | ✓ |
| 41 | `ciprofloxacin` | single | ✓ciprofloxacin · ✓cipro | ✓ciprofloxacino · ✓ciproxin | ✓环丙沙星 · ✓悉复欢 | ✓ |
| 42 | `metronidazole` | single | ✓metronidazole · ✓flagyl | ✓metronidazol · ✓flagyl | ✓甲硝唑 | ✓ |
| 43 | `fluconazole` | single | ✓fluconazole · ✓diflucan | ✓fluconazol · ✓diflucan | ✓氟康唑 · ✓大扶康 | ✓ |
| 44 | `oseltamivir` | single | ✓oseltamivir · ✓tamiflu | ✓oseltamivir · ✓tamiflu | ✓奥司他韦 · ✓达菲 | ✓ |
| 45 | `budesonide` | single | ✓budesonide · ✓pulmicort | ✓budesonida · ✓pulmicort | ✓布地奈德 · ✓普米克令舒 | ✓ |
| 46 | `montelukast` | single | ✓montelukast · ✓singulair | ✓montelukast · ✓singulair | ✓孟鲁司特 · ✓顺尔宁 | ✓ |
| 47 | `theophylline` | single | ✓theophylline | ✓teofilina | ✓茶碱 | ✓ |
| 48 | `furosemide` | single | ✓furosemide · ✓lasix | ✓furosemida · ✓seguril | ✓呋塞米 | ✓ |
| 49 | `spironolactone` | single | ✓spironolactone · ✓aldactone | ✓espironolactona · ✓aldactone | ✓螺内酯 | ✓ |
| 50 | `amlodipine` | salt | ✓amlodipine besylate | ✓amlodipino besilato | ✓苯磺酸氨氯地平 | ✓ |
| 51 | `metformin` | salt | ✓metformin hydrochloride | ✓metformina hidrocloruro | ✓盐酸二甲双胍 | ✓ |
| 52 | `metoprolol` | salt | ✓metoprolol tartrate | ✓metoprolol tartrato | ✓酒石酸美托洛尔 | ✓ |
| 53 | `metoprolol` | salt | ✓metoprolol succinate | ✓metoprolol succinato | ✓琥珀酸美托洛尔 | ✓ |
| 54 | `clopidogrel` | salt | ◐clopidogrel bisulfate | — | ✓硫酸氢氯吡格雷 | ✓ |
| 55 | `levothyroxine` | salt | ✓levothyroxine sodium | ✓levotiroxina sodica | ✓左甲状腺素钠 | ✓ |
| 56 | `nifedipine` | er | ✓nifedipine · ✓adalat | ✓nifedipino · ✓adalat | ✓硝苯地平 · ✓拜新同 | ✓ |
| 57 | `metoprolol` | er | ✓toprol xl · ✓metoprolol succinate | ✓beloken | ✓琥珀酸美托洛尔缓释片 | ✓ |
| 58 | `isosorbide-mononitrate` | er | ✓imdur · ✓isosorbide mononitrate | — | ✓欣康 | ✓ |
| 59 | `felodipine` | er | ✓plendil · ✓felodipine | ✓felodipino | ✓非洛地平 · ✓波依定 | ✓ |
| 60 | `amoxicillin` | combo | ◐augmentin | ✓augmentine | ✓阿莫西林克拉维酸钾 | ✓ |
| 61 | `amlodipine` | combo | ✓valsartan amlodipine | ✓valsartan amlodipino | ✓缬沙坦氨氯地平片 | ✓ |
| 62 | `metformin` | combo | ✓sitagliptin metformin | ✓sitagliptina metformina | ✗西格列汀二甲双胍片 | **✗** |
| 63 | `hydrochlorothiazide` | combo | ✓hydrochlorothiazide · ✓co-diovan | ✓hidroclorotiazida | ✓厄贝沙坦氢氯噻嗪片 | ✓ |
| 64 | `acetaminophen` | combo | — | ✓frenadol · ✓gelocatil gripe | ✓泰诺 | ✓ |
| 65 | `albuterol` | dup_inn | ✓albuterol | ✓salbutamol | ✓沙丁胺醇 | ✓ |
| 66 | `rifampin` | dup_inn | ✓rifampin | ✓rifampicina | ✓利福平 | ✓ |
| 67 | `ciclosporin` | dup_inn | ✗cyclosporine | ✗ciclosporina | ✓环孢素 | **✗** |
| 68 | `beclometasone` | dup_inn | ✗beclomethasone | ✗beclometasona | ✓倍氯米松 | **✗** |
| 69 | `chlorphenamine` | dup_inn | ✗chlorpheniramine | ✗clorfenamina | ✓氯苯那敏 | **✗** |
| 70 | `metamizole` | zh_only | ◐metamizole | ✓metamizol · ✓nolotil | ✓安乃近 | ✓ |
| 71 | `diosmectite` | zh_only | ✗diosmectite | — | ✓蒙脱石 · ✓思密达 | **✗** |
| 72 | `metoclopramide` | zh_only | ✓metoclopramide · ✓reglan | ✓metoclopramida · ✓primperan | ✓甲氧氯普胺 · ✓胃复安 | ✓ |

> 图例：✓ = Top-1 命中期望成分；◐ = Top-5 内命中但非 Top-1；✗ = 未命中（0 结果或落到别的成分）；“—” = 该语言本案例无查询。

---

## 7. 边界声明

- 本测试**只使用现有 en/es/zh 三语和现有 7 个市场**；未新增语言、未新增市场、未改任何语言策略；
- `data/drugs.db` 只读（`mode=ro`，脚本内已拦截），未写库、未跑 `git` / 发布 / `site/build.py`；
- 写范围仅 `tests/trilingual/`、`reports/trilingual-query-tests.md`、`.tmp/trilingual/`；
- 判定口径是"Top-5 内命中期望成分"（站点设计上永不返回唯一答案），不是"精确替换"；跨国可见只验证"能带出他国商品名"，不代表药品可互换。
