# 药品商品名跨国定位站

给一个名字（或包装上的一行字），定位到它是哪个药、什么规格，再给出其他国家的对应产品。

**范围**：公开上线 · 美国 / 英国 / 西班牙 / 墨西哥 / 中国 / 澳洲 / 加拿大 · 只用可公开许可（或官方明确允许再发布）的数据源，逐源许可见 [docs/许可清单.md](docs/许可清单.md)。
**当前状态**：七个市场全部入库，站点静态生成。美国、英国、中国、加拿大是全量；西班牙、墨西哥、澳洲各有各的缺口，页面上如实标注。

![检索示例](docs/img/search-tainuo.png)

## 现在已经能做什么

| 能力 | 状态 |
|---|---|
| 美国 110,179 个产品入库（openFDA NDC） | ✅ |
| 英国 61,051 个产品入库（dm+d 全量，129,266 条 AMP → 过滤器械后） | ✅ |
| 中国 146,347 个产品入库（医保药品分类与代码库，化学药；中成药未收） | ✅ |
| 西班牙 25,395 个产品入库（CIMA / AEMPS 全量 + 102 个复方恢复） | ✅ |
| 墨西哥 10,878 条注册入库（COFEPRIS 26 个按年 PDF + 3 份续期清单；1,040 条是 2001 年前的老注册号） | ✅ |
| 澳洲 11,890 个产品入库（PBS 5,452 + TGA CMI 4,730 + ARTG 明细 1,559 + ARTG 补全 144 + 人工核对 5） | ✅ |
| 加拿大 43,847 个产品入库（Health Canada DPD 全量，一行 = 一个 DIN；顺势疗法/兽药/消毒剂已排除） | ✅ |
| 中文 / 全角 / 西里尔 / 带剂量的输入归一化 | ✅ |
| 搜索增强：拼音 / 首字母、错拼容错、短中文片段、自动完成，结果按成分聚合 | ✅ 匹配 P50 ~1 ms |
| 首搜索引分片：输入后只拉首字符分片 | ✅ 3.78 MB → ~254 KB（gz） |
| 俗称 / 网络别名 / 旧名检索（两只青蛙 → 二甲双胍） | ✅ 57 条 `nickname`（指向成分） |
| 民间 / 类别 / 中文互联网叫法（water pill、blood thinner、必理痛、减肥针…；不含毒品/娱乐用药） | ✅ 1,062 条 `drug_term` / 1,119 条 `alias_all` |
| /warn「同名不同药 / 不可互换」警示页 | ✅ 顶栏入口 + 成分页提示 |
| 访问统计（GoatCounter，cookieless、只后台看、不公开计数） | ✅ 隐私说明见 About |
| 易混淆药对（FDA tall-man，hydrALAZINE ↔ hydrOXYzine…） | ✅ 22 对 |
| 候选集检索 + 打分 + 国家 / 剂量 / 剂型消歧 | ✅ |
| 同名碰撞自动推导（不同成分 → 严重，缓释差异 → 警告） | ✅ |
| 跨语言品牌家族（Tylenol ↔ 泰诺 ↔ 泰诺林） | ✅ 4 组 |
| BAN↔USAN 同义词（paracetamol ↔ acetaminophen、salbutamol ↔ albuterol 等 34 组） | ✅ |
| 成分身份卡（各国商品名对照） | ✅ 12,870 页 |
| 名字碰撞页 | ✅ 17,868 页 |

## 跑起来

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py run_all.py          # 建库 → 美国入库 → 种子 → 品牌家族 → 建站
& $py serve.py 8000       # 预览 http://127.0.0.1:8000/
```

单独跑：

```powershell
& $py db/init_db.py                     # 建/升级库
& $py etl/ingest_openfda_ndc.py         # 美国入库（读 data/raw/openfda 缓存）
& $py etl/trud_fetch.py                 # 用 TRUD key 下载 dm+d（英国）
& $py etl/ingest_dmd.py                 # 英国入库（读 data/raw/dmd 缓存）
& $py etl/mx_discover.py --download alop   # 墨西哥：抓 COFEPRIS 26 个按年 PDF
& $py etl/extract_cofepris_alop.py     # 墨西哥：PDF → CSV
& $py etl/extract_cofepris_status.py   # 墨西哥：注销/撤销清单 → 状态
& $py etl/fetch_mx_catalogs.py         # 墨西哥：ISSSTE 采购目录 + PROFECO 价格（回填浓度用）
& $py etl/build_mx_inn_map.py          # 墨西哥：西语通用名 → 英文 INN
& $py etl/ingest_mx.py                 # 墨西哥入库
& $py etl/fetch_pbs.py                  # 澳洲：PBS 官方 API（3 次请求，20 秒/次限速）
& $py etl/ingest_pbs.py                 # 澳洲入库（读 data/raw/pbs/api 缓存）
& $py etl/fetch_ca_dpd.py               # 加拿大：Health Canada DPD Open API（9 个端点，一次全量）
& $py etl/ingest_ca_dpd.py              # 加拿大入库（读 data/raw/ca/dpd 缓存）
& $py etl/ingest_artg_index.py          # 澳洲 ARTG 名称层入库（artg_entry 表）
& $py etl/ingest_artg_enrich.py         # 用 ARTG 名字给已认识品牌补规格/剂型
& $py data/seed_manual.py               # 英/中人工种子
& $py data/seed_families.py             # 品牌家族
& $py data/seed_nicknames.py            # 俗称 / 网络别名 / 旧名
& $py etl/ingest_us_terms.py            # 民间/类别叫法（NIDA/DEA/MedlinePlus 快照）
& $py etl/ingest_community_terms.py     # 各国社区叫法（逐条 URL）
& $py etl/clean_drug_terms.py --apply   # 清除毒品/娱乐性用药黑话（只留合法药品俗名）
& $py etl/ingest_cn_slang.py --apply    # 中文互联网俗名（Tier B → drug_term，候选 CSV 在 data/）
& $py etl/ingest_fda_confusable.py     # FDA tall-man 易混淆药对
& $py etl/normalize_salts.py --apply --confirm-real-db   # 盐型规范化（D2 折算基础）
& $py data/seed_warnings.py --apply --confirm-real-db    # /warn 警示种子（41 条）
& $py etl/ingest_chembl_atc.py --apply --allow-real-db   # ChEMBL ATC 补空值（CC BY-SA）
& $py etl/ingest_mx_pervolume.py --apply --allow-real     # MX「每 mL/每瓶」浓度
& $py etl/fix_dmd_salts.py --apply --confirm-real-db     # 英国 dm+d 盐型恢复
& $py db/source_dates.py                # 覆盖表的「数据截止」：从各源自己的发布/生效/快照日期推
& $py site/build.py                     # 生成静态站到 site/dist
& $py cli.py "泰诺"                      # 命令行查一条
& $py db/check_data.py                  # 数据体检
```

TRUD 的 key 放在 `.env` 的 `TRUD_API_KEY=`，不要提交。

测试：

```powershell
& $py -m unittest discover -s etl -t etl   # 归一化 + 各入库（25 项）
& $py -m unittest discover -s lib -t lib   # 检索/碰撞（29 项）
& $py tests/trilingual/run_tests.py        # 三语检索一致性（354 条查询）
& $py -m unittest discover -s mobile -t .  # 手机指令队列
```

## 目录

```
docs/    方案、数据模型、数据源授权结论、截图
db/      schema.sql（单一真相源） + init_db.py + check_data.py + q.py
etl/     normalize_name.py（归一化） + ingest_openfda_ndc.py（美国入库）
         ingest_us_terms.py（NIDA/DEA/MedlinePlus 快照） + clean_drug_terms.py（清除毒品黑话）
         fetch_cn_slang.py / extract_cn_slang.py / ingest_cn_slang.py（中文互联网俗名）
         classify_entity_type.py / fetch_chembl_atc.py / ingest_chembl_atc.py（ATC 补全）
         normalize_salts.py / fix_dmd_salts.py（盐型） + seed_warnings / verify_warnings（/warn）
         ingest_ca_dpd.py（加拿大 DPD 入库，fetch_ca_dpd.py 抓）/ ingest_ca_dpd 的测试
lib/     search.py（检索/打分/碰撞/别名） + 测试
data/    seed_*.py + sources/（NIDA/DEA/FDA 小快照，进仓库）+ drugs.db（可重建，不入库）
site/    build.py（静态生成，含 /confused.html） + dist/（产物）
```

## 三条设计底线

1. **商品名不是主键**——查询永远返回候选集，唯一性由「国家 × 剂型 × 规格 × 活性成分」锁定。
2. **碰撞自动推导**——`collision` 视图按"不同成分数"和"释放机制"分级，不手工标注；
   只有「品牌家族」这一张表是人工的，因为没有任何数据源写着"泰诺和 Tylenol 是同一个牌子"。
3. **不给用药建议**——只做标识对应与"不可互换"警示，不输出剂量换算后的服药方案。

## 俗称不是商品名

「两只青蛙」不是商品名，它是二甲双胍的网络俗称——`胍` 和青蛙的 `呱` 同音。这类叫法存在
`nickname` 表里，指向**活性成分**，不指向某个产品：

| 叫法 | 指向 | 类型 | 出处 |
|---|---|---|---|
| 两只青蛙 | 二甲双胍 metformin | 网络俗称 | 用户提供 |
| 伟哥 | 西地那非 sildenafil | 网络俗称 | 中文网络通行叫法 |
| 心得安 | 普萘洛尔 propranolol | 旧名 | 中文旧版药名 |
| 扑热息痛 | 对乙酰氨基酚 acetaminophen | 旧名 | paracetamol 的中文旧称 |

设计上做了三件事：

1. **不写进 `product_name`**：否则 `collision` 会把「两只青蛙」算成一个挂着几千个包装的商品名，
   还会生成一张没有意义的同名页。
2. **命中先说明再列商品**：页面标「网络俗称 / 旧名」，然后列出该成分在各国的商品名，
   不把俗称说成包装上的名字。
3. **只做精确匹配**：昵称差一个字往往就是另一个梗，模糊匹配会闹笑话；每条都人工写出处。

增补一条：改 `data/seed_nicknames.py`，再跑 `python data/seed_nicknames.py` 和
`python site/build.py`。当前 57 条（网络俗称 / 旧名 / 原研商品名 / 西语名），指向 40+ 个成分。

## 民间叫法 / 类别词 / 中文互联网俗名不是「又一个昵称表」

有些叫法不能只指向一个成分，硬塞进 `nickname` 会撒谎：

| 情形 | 例子 | 为什么不能塞 `nickname` |
|---|---|---|
| 类别词 | water pill = 利尿剂、blood thinner = 抗凝药、睡前药 | 不是某一个成分 |
| 中文互联网俗名 | 减肥针 / 瘦瘦针 → GLP-1 类（司美格鲁肽、替尔泊肽） | 一个叫法可能对应多个成分 |
| 地区品牌名 | 必理痛（香港）/ 普拿疼（台湾）→ 对乙酰氨基酚 | 是商品名/品牌别名，不是成分名 |

所以单独建 `drug_term`：允许 `substance_id` 为空，用 `alias_all` 视图把
`nickname` + `drug_term` 合成检索层唯一入口；单来源标 `community`，双来源标 `documented`。

**毒品 / 娱乐性用药不在收录范围**：NIDA / DEA / FRANK / ADF / PNSD 来的街头黑话已从库里清除
（337 行），`drug_term` 只保留合法药品的民间/类别叫法。数据来源与许可见
[docs/许可清单.md](docs/许可清单.md)。

查不到某个词时，页面会区分三种情况：类别词（不列商品）、本库无上市产品（只说明成分）、
叫法歧义（列出多个成分让人核对）。这三个提示都在 `lib/search.py` 和
`site/build.py` 的客户端检索里各实现一遍，口径一致。

## 数据现实（决定了难度排序）

| 市场 | 官方批量文件 | 含商品名 | 公开再用 | 状态 |
|---|---|---|---|---|
| 美国 | openFDA NDC / RxNorm | 有 | 可以 | ✅ 已接入 110,179 条 |
| 英国 | dm+d（OGL） | 有 | 可以（须署名） | ✅ 已接入 61,051 条 |
| 西班牙 | CIMA / AEMPS 全量 | 有 | 可以（须署名） | ✅ 已接入 25,293 条 |
| 墨西哥 | COFEPRIS 按年 PDF + 续期清单 | 有 | 未标注开放许可（用则署名） | ✅ 已接入 10,878 条，**无浓度列** |
| 中国 | 医保药品分类与代码库 | 有列，多数为空 | 未找到许可 | ✅ 146,347 条化学药 |
| 澳洲 | PBS API v3 + TGA CMI 目录 + ARTG 名称层 + 人工种子 | 有 | PBS API 可再发布（保留版权声明）；CMI/ARTG 只取事实字段 | ✅ 11,890 条＝PBS 5,452 + CMI 4,730 + ARTG 明细 1,559 + 补全 144 + Gaviscon 5；ARTG 名称层 34,594 条只做检索兜底 |
| 加拿大 | DPD 数据提取包（无授权下载路径则走同主机 DPD Open API） | 有 | 非商业再使用，须注明来源 | ✅ 已接入 43,847 条（Human，2026-10-23 DPD） |

英国这 61,051 条是从 167,533 条 AMP 里过滤出来的：dm+d 那个条目同时收录**器械/耗材**
（造口袋、弹力袜、敷料、支具），用「名字里有没有剂量」这一条滤掉约 10 万条。

**英国盐型恢复**：dm+d 的原料名里带盐型（besilate / fumarate / trihydrate…），早期入库只建了
base variant、把盐丢了。`etl/fix_dmd_salts.py` 从 `f_ingredient2` 解析盐型，已恢复 **15,083 个 GB 组件**
（盐型覆盖 2.0% → 25.0%，新建 127 个 variant），为 D2 碱基折算铺路；详见
[reports/gb-salt-recovery.md](reports/gb-salt-recovery.md)。

**ATC 覆盖率**：全部 substance **47.5%**（6,081 / 12,790）；只算药物实体
（INN / 生物制品 / 营养剂）是 **67.0%**（5,757 / 8,592）。生药 / 顺势 / 材料等非 INN 实体不再追 ATC
缺口——`data/entity_type.csv` 做实体分类，ChEMBL（CC BY-SA）只补空值。

> 2026-10 复核：国家医保局「医保药品分类与代码数据库」有独立的商品名一列，
> 但公开入口只给「公示批次」增量、不能整库导出；抽样 1,768 行里商品名有值 5.1%。
> 因此 CN 层按 **通用名 + 厂家 + 规格 + 批准文号** 设计，商品名可缺省。

中国部分以「通用名 + 厂家 + 规格 + 批准文号」为产品身份：146,347 条化学药已全量入库，
中成药（98,703 行、42 个真实商品名）按设计排除。商品名只在少数行有值，所以中国产品主要靠
通用名检索；页面显式标注覆盖边界：**查不到 ≠ 不存在**。

### 加拿大：一份官方全量，但下载路径要绕

加拿大没有「处方 + OTC 合在一起」的第二份名录，健康加拿大（Health Canada）的
**DPD（Drug Product Database）**就是全部——一行 = 一个 **DIN**（Drug Identification Number）：

| 字段 | 内容 |
|---|---|
| brand_name | 商品名。很多老产品把剂型/规格写进名字（`APO-AMOXI CAP 500MG`），入索引前剥掉 |
| activeingredient | 成分 + **强度**。双括号写法 `ATORVASTATIN (ATORVASTATIN CALCIUM)`，括号里是盐 |
| pharmaceutical_form | 剂型；`status` 给 Marketed / Approved / Dormant / Cancelled |
| therapeuticclass | ATC（4 位）；`schedule` 给处方 / 非处方 |

**为什么不用官方的 allfiles.zip**：它挂在 `www.canada.ca/content/dam/…`，程序化下载在这台机器上
HEAD/GET 都 30 秒超时（浏览器 UA 也一样），2026-10 实测。**为什么不用 DPD 网页查询**：结果是服务端
DataTables，只回首页，翻页接口 `getNextPage` 需要绑定搜索会话，直接请求恒定 500。所以改用**同一台
主机**上的公开 **DPD Open API**（`/api/drug/<endpoint>/?lang=en&type=json`，9 个端点、全量 JSON、
无需 key，字段与数据提取包一致），落在 `data/raw/ca/dpd/`。

入库时做了四件事：

1. **成分名统一**：加拿大用老式英文名——`ACETYLSALICYLIC ACID` → aspirin、`ADRENALINE` →
   epinephrine、`GLYCERYL TRINITRATE` → nitroglycerin；括号里的盐记成 variant。
   这样加拿大和美国/中国/澳洲落在同一张成分卡上（acetylsalicylic acid 与 aspirin 不再分家）。
2. **复方剂量按「每 N 片 / 每 N mL」折算**：DPD 给的范围量（`1 g / 4 TAB`、`355 mg / 30 ML`）
   换算成每片 / 每 mL，否则一盒「每 4 片 1 g」的配方会显示成 1 g/片。
3. **排除三类**：顺势疗法（`SCHEDULE=HOMEOPATHIC`，强度是 CH/DH/X 稀释度，不是剂量）、
   兽药/放射药/消毒剂（非 Human）、以及 DPD 里被登记成「有效成分」的辅料
   （HYPROMELLOSE、BENZYL ALCOHOL…——不排的话一种角膜保存液会把 4 万个产品挂到 hypromellose 名下）。
4. **名字键与显示名分开**：DPD 里很多条目的名字本身就是一个产品描述（`15 SPF FPS PREMIUM
   SUNSCREEN`），显示原样、键里再剥一层剂型词，否则「Sunscreen」这类词永远搜不到。

| 项 | 数值 |
|---|---|
| DPD 产品行 | 58,379 |
| 入库（Human、非顺势、成分 ≤8、剔除辅料后） | **43,847**（active 14,519 / discontinued 29,323 / withdrawn 5） |
| 有强度 | 43,775 / 43,847 ≈ 99.8% |
| 排除 | 兽药/放射/消毒剂 7,340 · 顺势疗法 5,571 · 复合维生素类（成分 >8）1,169 |
| 名字（索引键）带 CA | 25,223；只在加拿大出现的名字 22,172 |

**已知缺口**：DPD 没有包装数量和价格；很多 OTC 消费装（Tylenol / Advil / Motrin 的老包装）是
电子化之前批的，DPD 里只有部分 DIN，货架上有的 OTC 可能查不到。


### 墨西哥：有货号，没有剂量

COFEPRIS 的《Registros Sanitarios de Medicamentos Alopáticos Expedidos》按年发布 26 个 PDF
（2001–2026），列是：注册号 · 持有人 · 商品名 · 通用名 · 第 226 条分类 · 剂型 · 有效期。
**没有浓度列**——这是墨西哥和其他三个市场最不一样的地方。

绕开的两道墙：gob.mx 的 HTML 有 JS 反爬（只挡页面、不挡 `cms/uploads/attachment/file/...`），
所以用 r.jina.ai 取链接、再直连下载；datos.gob.mx 的 repodatos 直连 403（Akamai），
改走 CKAN `datastore_search` 取同一份数据。

浓度只能回填，且只在唯一值时才写：2,837 条来自 ISSSTE 采购目录（通用名+剂型唯一的浓度），
215 条是固体制剂放宽到「只看通用名」唯一值，72 条来自 PROFECO 零售价格调查，另有 CC-BY 采购目录
与「每 mL / 每瓶」解析（`reports/mx-strength-audit.md`、`reports/mx-pervolume.md`）。
合计 **3,832 / 10,878 ≈ 35.2%**（per_volume 字段 125 条）。剩下约 65% 页面上规格是空的——
**空是数据事实，不是 bug**。

试过但没用的：PROFECO 全量 150,876 行拉完，去重后仍然只有 378 个商品名（价格调查重复太多）；
CBCISS / CNIS 只在 DOF 和网页应用里，没有批量文件。所以商品名级浓度基本到顶了。

西语通用名 → 英文 INN 是这一层的关键：3,154 个西语名（含续期清单里的老药），映射上 1,513 个
（手工 377 · 精确 637 · 规则 256 · 模糊 219 · 构词 14 · 去空格 10），
其余建成「只在墨西哥出现」的 substance（id 加 `mx-es-` 前缀，避免下一轮映射自己命中自己）。

### 澳洲：只有 PBS，没有 ARTG 的批量

澳洲的「注册总表」是 **TGA 的 ARTG**（Australian Register of Therapeutic Goods）——
所有合法上市的药品/器械都在里面，条目名自带品牌 + 规格 + 剂型（如
`Atorvastatin Sandoz 40 mg tablet`）。但它**没有批量导出**：data.gov.au 上没有 ARTG 数据集，
官网只有逐条查询页，而且对程序化访问直接 403（Akamai：*Your request has been blocked*，
浏览器 UA、Node、r.jina.ai 都一样）。想拿全量只有 FOI（信息公开申请）一条路。

能稳定、合法拿到的批量数据是 **PBS**（药品福利计划，只覆盖政府补贴的处方药）：

| 通道 | 数据 | 许可 |
|---|---|---|
| PBS 网页（pbs.gov.au） | 品牌 / 成分 / 规格 / 厂家齐全 | ❌ 版权页只允许「个人参考用途」的复制 |
| **PBS 官方 API v3** | 每月 1 日更新，13 个月，JSON/CSV | ✅ `_meta` 明确允许再发布，须保留版权声明 |

API 是公开的：无需注册，`subscription-key` 就写在官方 Postman collection 的公开变量里，
限速 **20 秒/次**（全体用户共享），所以 `etl/fetch_pbs.py` 只发 3 个请求（schedules / items /
organisations），并把 sleep 写死在代码里。三个请求拿回 15,073 条 item × 品牌行
（schedule 4751，2026-10-01 生效），按「品牌 + 成分 + 规格 + 剂型 + 包装」去重后是 **5,452 个产品**。

几个取舍：

- 同一个品牌/规格常挂在多个 PBS 编码下（受限 vs 不受限、公立 vs 私立医院），
  去重后只保留一条，否则产品数会虚高一倍。
- `program R1`（造口/失禁：敷料、绷带、胶带，631 行）不是药，按 dm+d 滤器械的同一逻辑排除。
- 159 行没有剂型（extemporaneous 临配处方）跳过；179 行没有可解析的强度
  （营养配方、Zolgensma 的 `20 trillion vector genomes/mL`），强度留空——空是数据事实。
- PBS 不含 OTC：**Panadol、Nurofen、Gaviscon 查不到**，因为它们不进补贴目录，不代表澳洲没有。
  要补这块只能上 ARTG（FOI）或商业库（eMIMS / AMH / AusDI）。
- 澳洲用 BAN 名：在 dm+d 的 24 组之外又加了 10 组（ethinyloestradiol、pethidine、
  glibenclamide、colestyramine、sodium cromoglycate…），否则同一成分会和美英分家。

### 状态是怎么算出来的

这 26 个文件只列**当年新批**的注册，2001 年以前批的不在里面。三条线索合起来才敢写状态：

| 状态 | 判据 | 条数 |
|---|---|---|
| active | 有效期在未来 | 1,772 |
| discontinued | 有效期已过 | 4,044 |
| withdrawn | 出现在 revocados / cancelados 清单 | 699 |
| unknown | 2001–2010 的文件压根没有有效期列 | 4,363 |

另外 3 份 prórrogas（2011 / 2012 / 2013 续期清单）补回 **1,040 个 2001 年前的老注册号**
（3790、0136M79 这种），它们带品牌、通用名、剂型、持有人和新的到期日——这是「老药查不到」唯一的补救入口。
所以墨西哥的覆盖是「2001 年以来的新批 + 续期清单里出现过的老药」，仍然不是「当前全部在册」。
